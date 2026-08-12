"""An absent policy block must be a failed trial, never a measured negative.

THE INCIDENT
------------
F3-7 asks whether contextual grounding can tell a grounded response from an ungrounded one.
Its first live run sent 120 trials, every one succeeded, `blocks_per_trial` read `[3]`, both
arms reported `x=0`, and the case published:

    verdict: FALSE   (DISJOINT_INTERVALS)
    ungrounded: x=0 n=60   ci 0 [0, 0.06017]
    grounded:   x=0 n=60   ci 0 [0, 0.06017]

read as "the check cannot tell grounded from ungrounded" — a refutation of the document. The
filter had never executed. `ArmSpec.source` defaults to `"INPUT"`, contextual grounding scores
a *response*, and at INPUT the service returns 200 / `action=NONE` and simply omits
`contextualGroundingPolicy` from the assessment. Measured live, same three blocks, same
guardrail, only `source` differing:

    source=INPUT   -> 200, action=NONE,                 keys: [appliedGuardrailDetails,
                                                               invocationMetrics]
    source=OUTPUT  -> 200, action=GUARDRAIL_INTERVENED,  keys: [appliedGuardrailDetails,
                                                               contextualGroundingPolicy,
                                                               invocationMetrics]
                          GROUNDING score=0.0 BLOCKED / RELEVANCE score=0.97 NONE

WHY NO EXISTING GATE COULD SEE IT
---------------------------------
Every guard in this project was satisfied. `outputScope="FULL"` was set — and `FULL` governs
which *evaluated* policies are reported, so it cannot conjure a policy that never ran.
`require_measured` saw 120/120 usable. `n_met` was vacuous by design (F3-7 has no sealed n).
The oracle compared two Wilson intervals correctly. The flattener was right to tolerate an
absent block, because absence is also how the API says "this guardrail has no such policy
configured", which is a legitimate configuration F3-1 depends on.

The defect is at the seam between those two facts: tolerance is correct in a *flattener* and
wrong in a *reader*. `hit_grounding` reduced `grounding == []` to `False`, and that erases the
difference between "ran, did not fire" and "did not run".

WHY BLOCK-PRESENCE IS A VALID SIGNAL — AND ONLY FOR SOME POLICIES
-----------------------------------------------------------------
Measured on the live service, benign input that fires nothing, one guardrail per policy:

    contentPolicy               PRESENT   (cf-medium, determinism)
    sensitiveInformationPolicy  PRESENT   (pii)
    topicPolicy                 PRESENT   (topic)
    wordPolicy                  ABSENT    (words)
    contextualGroundingPolicy   ABSENT    (grounding — the liveness case)

The first three declare themselves whether or not they fire, so requiring one is a real
liveness check. `wordPolicy` is absent on a non-match, so a blanket "require every configured
policy" rule would turn every one of F3-6's 54 true negatives into a failed trial. Hence
`require_policy` is a per-arm opt-in naming ONE block, and these arms pin that asymmetry so a
future refactor cannot quietly generalise it.
"""

from __future__ import annotations

import sys
import re
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arms as R                                                    # noqa: E402
import checkpoint as C                                              # noqa: E402
import phase1 as P                                                  # noqa: E402
from test_arms import StubClient, factory_with, items, roots         # noqa: E402,F401


# Blocks the live service returns even when the policy fires on nothing, so requiring one is
# a liveness check rather than a detection check. Verified live 2026-08-10 (see docstring).
SELF_DECLARING = ("contentPolicy", "sensitiveInformationPolicy", "topicPolicy")

# Blocks that are absent on a non-detection, so requiring one would fail true negatives.
ONLY_WHEN_FIRING = ("wordPolicy", "contextualGroundingPolicy")


def grounding_response(*, score, detected, action="NONE", present=True):
    """A contextualGroundingPolicy response, or the INPUT-side response that omits it.

    `present=False` reproduces the exact live shape at `source=INPUT`: HTTP 200,
    `action="NONE"`, an assessment carrying `invocationMetrics` and
    `appliedGuardrailDetails` and no policy block at all. Not an error, not an empty
    filters list — the key is simply not there, which is why nothing downstream noticed.
    """
    block: dict = {"invocationMetrics": {"guardrailProcessingLatency": 42},
                   "appliedGuardrailDetails": {"guardrailOrigin": ["REQUEST"]}}
    if present:
        block["contextualGroundingPolicy"] = {"filters": [
            {"type": "GROUNDING", "threshold": 0.7, "score": score,
             "action": "BLOCKED" if detected else "NONE", "detected": detected},
            {"type": "RELEVANCE", "threshold": 0.7, "score": 0.97,
             "action": "NONE", "detected": False},
        ]}
    return {"action": action, "assessments": [block],
            "usage": {"contextualGroundingPolicyUnits": 3}}


def grounding_spec(**kw):
    base = dict(case_id="G", family="f3", corpus="grounding/x.jsonl",
                guardrail_id="gr-1", source="OUTPUT",
                require_policy="contextualGroundingPolicy",
                hit=P.hit_grounding("GROUNDING"))
    base.update(kw)
    return R.ArmSpec(**base)


# ---------------------------------------------------------------- the regression itself

def test_an_absent_policy_block_is_a_failure_and_not_a_zero(roots):
    """The F3-7 defect, in the shape it actually took: 200 OK, action=NONE, no block."""
    client = StubClient([grounding_response(score=0.0, detected=False, present=False)] * 3)
    t = R.run_arm(grounding_spec(), items(3), run_id="r", factory=factory_with(client),
                  **roots)
    assert t["n_usable"] == 0, (
        "a trial whose policy never ran was counted as usable; that is how F3-7 published "
        "x=0/60 twice and read it as a refutation")
    assert t["n_failed"] == 3
    assert t["failure_codes"] == ["PolicyNotEvaluated"], t["failure_codes"]
    assert t["x"] == 0


def test_without_the_guard_the_same_responses_read_as_clean_negatives(roots):
    """The paired control: this is EXACTLY what the first F3-7 run recorded.

    Without `require_policy` the identical responses produce 3 usable trials and x=0 — a
    fully-populated, plausible, wrong measurement. The arm is here so the guard's value is
    demonstrated rather than asserted: if a refactor made `require_policy` a no-op, the
    arm above would fail and this one would keep passing, which is the wrong pair of
    signals to leave behind.
    """
    client = StubClient([grounding_response(score=0.0, detected=False, present=False)] * 3)
    t = R.run_arm(grounding_spec(require_policy=""), items(3), run_id="r",
                  factory=factory_with(client), **roots)
    assert (t["n_usable"], t["x"], t["n_failed"]) == (3, 0, 0)


def test_a_present_block_that_did_not_fire_is_a_genuine_negative(roots):
    """The other half, and the reason the guard is sound.

    Live check on a grounded response: `GROUNDING score=1.0 detected=false`, block PRESENT.
    So absence means "did not run", never "did not fire" — a guard that failed true
    negatives would be worse than the defect, since it would eat the FPR arm.
    """
    client = StubClient([grounding_response(score=1.0, detected=False)] * 3)
    t = R.run_arm(grounding_spec(), items(3), run_id="r", factory=factory_with(client),
                  **roots)
    assert (t["n_usable"], t["x"], t["n_failed"]) == (3, 0, 0)
    assert t["failure_codes"] == []


def test_a_present_block_that_fired_is_a_hit(roots):
    client = StubClient([grounding_response(score=0.0, detected=True,
                                            action="GUARDRAIL_INTERVENED")] * 3)
    t = R.run_arm(grounding_spec(), items(3), run_id="r", factory=factory_with(client),
                  **roots)
    assert (t["n_usable"], t["x"]) == (3, 3)


def test_the_liveness_failure_costs_exactly_one_call(roots):
    """A mis-addressed request fails identically every time; retrying it buys nothing.

    Asserted on the CALL COUNT, not on the recorded `attempts`: the two agree only if the
    retry loop really did stop, and `attempts` alone would pass on a stub that was called
    three times and reported 1.
    """
    client = StubClient([grounding_response(score=0.0, detected=False, present=False)] * 9)
    t = R.run_arm(grounding_spec(), items(3), run_id="r", factory=factory_with(client),
                  **roots)
    assert len(client.calls) == 3, (
        f"{len(client.calls)} calls for 3 items — PolicyNotEvaluated is being retried, "
        f"which triples the cost of proving a harness bug")
    assert not C.is_retryable(R.PolicyNotEvaluated("x"))
    # Read the ATTRIBUTE, not `error_code()`'s output. The class is named
    # `PolicyNotEvaluated`, so `error_code`'s class-name fallback returns the identical
    # string whether or not the attribute exists — a mutation deleting it survived this arm
    # until the check was written against the attribute itself. Two failure modes look the
    # same through the function; only one of them survives a rename.
    assert R.PolicyNotEvaluated.error_code == "PolicyNotEvaluated", (
        "the failure must carry its own `error_code`, not rely on its class name: "
        "`checkpoint.error_code` reads the attribute first, and the fallback is what "
        "recorded 3,378 lost trials as 'CapturedCallError' in DEV-P1-11")


def test_the_code_survives_the_class_being_renamed(roots):
    """The mutation the arm above could not see, made visible.

    `error_code`'s fallback is the class name, so as long as the class is *called*
    `PolicyNotEvaluated` the recorded code is right by accident. A subclass with a different
    name isolates the attribute from the coincidence: if the attribute were gone,
    `failure_codes` would read `['Renamed']` and a triaging reader would learn nothing.
    """
    class Renamed(R.PolicyNotEvaluated):
        pass

    assert C.error_code(Renamed("x")) == "PolicyNotEvaluated", (
        "the code came from the class name rather than from the attribute; rename the class "
        "and `failure_codes` stops naming the defect")


def test_blocks_present_is_recorded_on_every_row(roots):
    """The liveness channel reaches `results/`, not only the raw evidence tree.

    An analysis that must reopen 4,548 evidence files to tell "did not fire" from "did not
    run" will not do it.
    """
    client = StubClient([grounding_response(score=1.0, detected=False)] * 2)
    t = R.run_arm(grounding_spec(), items(2), run_id="r", factory=factory_with(client),
                  **roots)
    for row in t["rows"]:
        assert row["blocks_present"] == ["appliedGuardrailDetails",
                                         "contextualGroundingPolicy",
                                         "invocationMetrics"], row["blocks_present"]


def test_blocks_present_is_the_union_over_a_multi_assessment_response(roots):
    """`assessments` is a LIST, and a per-block read would report only the last one."""
    resp = {"action": "NONE", "usage": {},
            "assessments": [{"contentPolicy": {"filters": []}},
                            {"contextualGroundingPolicy": {"filters": []}}]}
    asm = R.read_assessment(resp)
    assert asm.blocks_present == ["contentPolicy", "contextualGroundingPolicy"]


# ---------------------------------------------------------------- the scope of the guard

def armspec_kwargs(path: Path) -> list[dict[str, object]]:
    """The keyword literals of every `ArmSpec(...)` call in a script, read by AST.

    NOT `src.count('require_policy=...')`. The first version of this arm did exactly that
    and failed at 3 == 2, because `06_grounding.py`'s own docstring quotes the argument it
    documents. A text count cannot tell a call site from prose about a call site — and per
    `feedback_prose_is_not_verified`, prose is the half that is not verified. Counting
    call sites in the syntax tree makes documenting the fix impossible to confuse with
    applying it.
    """
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name != "ArmSpec":
            continue
        kw = {}
        for k in node.keywords:
            if k.arg and isinstance(k.value, ast.Constant):
                kw[k.arg] = k.value.value
        out.append(kw)
    return out


def test_f3_7_requires_the_grounding_block_on_both_arms():
    """Pinned at the case, because the general guard is opt-in.

    `require_policy` defaults to `""`, so a rewrite of `06_grounding.py` that dropped the
    argument would restore the original defect with every generic arm above still green.
    Read from the source rather than by importing, since the module resolves a live
    guardrail id at import-adjacent time.
    """
    path = Path(__file__).resolve().parents[2] / "f3_efficacy" / "06_grounding.py"
    specs = armspec_kwargs(path)
    assert len(specs) == 2, (
        f"expected F3-7's two arms (ungrounded, grounded), found {len(specs)} ArmSpec "
        f"call(s); this arm no longer knows what it is checking")
    for kw in specs:
        assert kw.get("require_policy") == "contextualGroundingPolicy", kw
        # Both arms, including the FPR cell. An unguarded grounded arm reporting 0/60 is
        # exactly the half of the original verdict that looked most reassuring.
        assert kw.get("source") == "OUTPUT", kw
    # The published provenance must agree with the request that produced the data. Checked
    # on the emitted `instrument` value rather than on the whole file, since the docstring
    # legitimately quotes `source=INPUT` when explaining what went wrong.
    assert '"ApplyGuardrail (source=OUTPUT' in path.read_text(encoding="utf-8"), (
        "the emitted `instrument` field still claims source=INPUT — a published provenance "
        "string that disagrees with the request that produced the data "
        "(feedback_label_must_match_computation)")


def test_only_grounding_opts_into_the_guard_for_now():
    """A tripwire on the blast radius, in both directions.

    Requiring `wordPolicy` would convert every one of F3-6's true negatives into a failed
    trial — the guard eating the data it protects. So the set of opted-in arms is asserted,
    and widening it is a deliberate, diffable edit rather than a quiet generalisation.
    """
    root = Path(__file__).resolve().parents[2]
    users = sorted(p.relative_to(root).as_posix()
                   for p in root.glob("f*/[0-9]*.py")
                   if "require_policy=" in p.read_text(encoding="utf-8"))
    # Widened 2026-08-12 for F3-11 (`07_model_drift.py`), which requires a block on all five
    # strata: `contentPolicy` on four and `sensitiveInformationPolicy` on the PII one. Both are
    # in SELF_DECLARING, so neither can eat a true negative — and F3-11's day-0 baseline is the
    # live proof rather than the reasoning: 300/300 usable with 0 failures while 19 of its 64 PII
    # items went undetected. Had `sensitiveInformationPolicy` been absent on a non-detection,
    # those 19 would have been failed trials instead of the drift signal the case is built on.
    assert users == ["f3_efficacy/06_grounding.py", "f3_efficacy/07_model_drift.py"], users

    # The allowlist above is about blast radius; THIS is the invariant. Every block any arm
    # requires must be one the service returns on a non-detection (or grounding, which is
    # required by design because its absence means did-not-run). Checked over the values rather
    # than the file list, so the next widening cannot smuggle in a fire-only block by editing
    # one line of the list above.
    allowed = set(SELF_DECLARING) | {"contextualGroundingPolicy"}
    for rel in users:
        src = (root / rel).read_text(encoding="utf-8")
        required = set(re.findall(r'"require_policy":\s*"([A-Za-z]+)"', src)) | set(
            re.findall(r'require_policy="([A-Za-z]+)"', src))
        assert required, f"{rel} matched the scan but no require_policy value could be read"
        assert required <= allowed, (
            f"{rel} requires {sorted(required - allowed)}, which the live service omits when "
            f"nothing fires; every true negative in that arm would become a failed trial")


@pytest.mark.parametrize("block", ONLY_WHEN_FIRING)
def test_a_block_absent_on_a_non_detection_is_not_required_anywhere(block):
    """`wordPolicy` and `contextualGroundingPolicy` are absent when nothing fires.

    Grounding is exempt from the conclusion — it is required, and legitimately, because it
    is absent only when the filter did not RUN (its block is present with
    `detected=false` on a grounded response). `wordPolicy` is the one that must never be
    required, and that is what this asserts.
    """
    if block == "contextualGroundingPolicy":
        pytest.skip("required by design; absence means did-not-run, verified live")
    root = Path(__file__).resolve().parents[2]
    for p in root.glob("f*/[0-9]*.py"):
        src = p.read_text(encoding="utf-8")
        assert f'require_policy="{block}"' not in src, (
            f"{p.name} requires {block}, which the live service omits on a non-detection: "
            f"every true negative would become a failed trial and the FPR cell would empty "
            f"itself out")
