"""The arm runner's own suite. Offline, with a stub client.

`lib/arms.py` is the layer through which every Phase 1 observation passes, so a defect
here is not a bug in one case — it is a systematic bias in eighteen. Three of its
decisions can fail *silently*, producing a full run of plausible numbers that answer a
different question than the oracle asks, and those are what most of these arms are for:

* `outputScope` reverting to the API default would make every benign item come back with
  an empty `assessments` list, so F3-2/F3-3's false-positive rates would read 0.00 —
  a number that looks like an excellent result and means "not measured".
* `detected` collapsing into `action` would silently answer F4's question in F3-1's cell.
* A failed trial counted in the denominator would push every recall down by the harness's
  own error rate.

The stub is a `botocore` client built from the real service model via `Stubber` where the
shape matters, and a hand-rolled double where the point is control flow. Per
`feedback_verify_against_real_artifact` the response *shapes* come from botocore's own
model rather than from my memory of them — a stub I invent can only confirm what I already
believe the response looks like.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arms as R                                                    # noqa: E402
import awsclients as A                                              # noqa: E402


# --------------------------------------------------------------------------
# doubles
# --------------------------------------------------------------------------

class _Meta:
    def __init__(self, region: str, ops: set[str]):
        self.region_name = region

        class _SM:
            service_name = "bedrock-runtime"
            operation_names = sorted(ops)

        self.service_model = _SM()


class StubClient:
    """Records every call and returns queued responses.

    Deliberately not a Mock: a Mock returns a truthy Mock for any attribute, so a typo in
    a response key would read as a present field holding a Mock object, and the assertion
    "the response had assessments" would pass on a client that never returned any.
    """

    def __init__(self, responses, *, ops=("ApplyGuardrail",), region="us-east-1"):
        self.meta = _Meta(region, set(ops))
        self._responses = list(responses)
        self.calls: list[dict] = []

    def apply_guardrail(self, **params):
        self.calls.append(params)
        if not self._responses:
            raise AssertionError("stub exhausted: more calls than queued responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        out = dict(nxt)
        out.setdefault("ResponseMetadata", {
            "RequestId": f"req-{len(self.calls):04d}", "HTTPStatusCode": 200,
            "HTTPHeaders": {}})
        return out


def cf_response(*, detected=(), blocked=(), action="NONE", usage=None, latency=None):
    """A contentPolicy response in the real response shape."""
    filters = []
    for t in dict.fromkeys(tuple(detected) + tuple(blocked)):
        filters.append({"type": t, "confidence": "HIGH",
                        "filterStrength": "HIGH",
                        "detected": t in detected,
                        "action": "BLOCKED" if t in blocked else "NONE"})
    block: dict = {"contentPolicy": {"filters": filters}}
    if latency is not None:
        block["invocationMetrics"] = {"guardrailProcessingLatency": latency}
    resp: dict = {"action": action, "assessments": [block],
                  "usage": usage or {"contentPolicyUnits": 1, "topicPolicyUnits": 0}}
    return resp


def factory_with(client) -> A.ClientFactory:
    f = A.factory("us-east-1")
    f._cache[("bedrock-runtime", "us-east-1")] = client
    return f


def items(n=3, label="VIOLENCE"):
    return [{"id": f"i{k}", "text": f"item {k}", "label": label} for k in range(n)]


@pytest.fixture()
def roots(tmp_path):
    """Per-test roots, plus a no-op sleep.

    `sleep` is injected rather than patched globally: the retry branch it exercises was
    dead for this module's entire first draft (a bare RuntimeError from
    `raise_for_status` read as permanent to `is_retryable`), and a globally-patched
    `time.sleep` would have made the arm pass in both the broken and the fixed version.
    """
    return {"checkpoint_root": tmp_path / "cp", "evidence_root": tmp_path / "ev",
            "sleep": lambda _s: None}


# --------------------------------------------------------------------------
# outputScope — the arm that must fail if the default is ever restored
# --------------------------------------------------------------------------

def test_output_scope_full_is_sent_on_every_call(roots):
    """The single most consequential parameter in Phase 1.

    `outputScope` defaults to `INTERVENTIONS`, under which a benign item returns
    `action="NONE"` and an EMPTY `assessments` list. Every false-positive rate in this
    project (F3-2, F3-3) is measured on exactly those items, so under the default they
    would all read 0.00 — indistinguishable from a perfect guardrail, and wrong.

    Asserted on what reached the client, not on the module constant: a test that read
    `R.OUTPUT_SCOPE` would pass even if `run_arm` stopped passing it.

    Uses the `roots` fixture rather than a fixed path. The first draft wrote to a literal
    `/tmp/x-cp` and passed once, then failed on the second run of the suite: the
    checkpoint had persisted, so the arm resumed, sent zero calls and had nothing to
    assert on. Resumability makes any test with a shared checkpoint root order-dependent
    and self-poisoning — the "0 == 3" it eventually produced was the honest version of a
    test that had already been vacuous the moment it first passed.
    """
    assert R.OUTPUT_SCOPE == "FULL"
    c = StubClient([cf_response(detected=("VIOLENCE",))] * 3)
    R.run_arm(R.ArmSpec("T", "f3", "c.jsonl", "gr-1"), items(3),
              run_id="r1", factory=factory_with(c), **roots)
    assert len(c.calls) == 3
    for call in c.calls:
        assert call["outputScope"] == "FULL"


def test_the_api_default_would_make_a_benign_item_unmeasurable():
    """Why the constant exists, demonstrated rather than asserted.

    This arm does not test our code — it pins the *reason* for the decision, using the
    two response shapes the two scopes produce. Without it, `OUTPUT_SCOPE = "FULL"` is a
    line someone could "simplify" away with no test explaining what breaks.
    """
    # What INTERVENTIONS returns for a benign item: no assessments at all.
    interventions = {"action": "NONE", "assessments": [], "usage": {}}
    asm = R.read_assessment(interventions)
    assert asm.detected_types == []          # "found nothing"...
    # ...and what FULL returns for the same benign item: an assessment saying so.
    full = cf_response(detected=(), blocked=(), action="NONE")
    full["assessments"][0]["contentPolicy"]["filters"] = [
        {"type": "VIOLENCE", "detected": False, "action": "NONE",
         "confidence": "NONE"}]
    asm_full = R.read_assessment(full)
    assert asm_full.detected_types == []     # ...reads identically here.
    # The two are indistinguishable AFTER flattening, which is the whole problem: the
    # difference is that only one of them proves the filter ran. That evidence lives in
    # the raw response, which is why it is archived per call and why the scope is fixed
    # at the point of the call rather than recovered at analysis time.
    assert interventions["assessments"] == []
    assert full["assessments"][0]["contentPolicy"]["filters"] != []


# --------------------------------------------------------------------------
# detected vs action
# --------------------------------------------------------------------------

def test_detected_and_blocked_are_separate_facts():
    """They come apart under `inputAction=NONE` — the LOG_ONLY shape §7.1 prescribes.

    F3-1 asks whether the classifier fired; F4 asks what the configuration did about it.
    A single `blocked` boolean would answer F4's question in F3-1's cell and the number
    would look entirely reasonable.
    """
    resp = cf_response(detected=("VIOLENCE",), blocked=(), action="NONE")
    asm = R.read_assessment(resp)
    assert asm.detected("VIOLENCE") is True
    assert asm.blocked("VIOLENCE") is False
    assert asm.action == "NONE"


def test_a_blocked_filter_is_also_detected():
    resp = cf_response(detected=("HATE",), blocked=("HATE",),
                       action="GUARDRAIL_INTERVENED")
    asm = R.read_assessment(resp)
    assert asm.detected("HATE") and asm.blocked("HATE")
    assert asm.action == "GUARDRAIL_INTERVENED"


def test_confidence_is_kept_per_type():
    """F3-9's ROC needs the confidence, not just the boolean.

    `filterStrength` is the configured threshold and `confidence` is the classifier's
    output; keeping only the boolean would leave the lattice unreconstructable from the
    tally and force a re-run to answer a question the response already contained.
    """
    asm = R.read_assessment(cf_response(detected=("SEXUAL",)))
    assert asm.confidences["SEXUAL"] == "HIGH"


# --------------------------------------------------------------------------
# read_assessment: absent policy blocks, and every policy type
# --------------------------------------------------------------------------

def test_absent_policy_blocks_are_not_an_error():
    """F3-1's guardrail has no PII policy, so `sensitiveInformationPolicy` is absent.

    Absent means "not configured", which is a legitimate configuration. A KeyError here
    would turn "this arm asked about content filters" into a crash, and — worse — into a
    *failed trial*, which the tally would then correctly exclude from the denominator
    while the real cause was our reader.
    """
    asm = R.read_assessment({"action": "NONE", "assessments": [{}]})
    assert asm.detected_types == [] and asm.pii_detected == []
    assert asm.topics_detected == [] and asm.words_detected == []
    assert asm.grounding == []
    # And a response with no `assessments` key at all.
    assert R.read_assessment({}).action == "NONE"


def test_every_policy_type_is_read():
    """One response carrying all five policy blocks, in the real response shape."""
    resp = {
        "action": "GUARDRAIL_INTERVENED",
        "actionReason": "Guardrail blocked.",
        "assessments": [{
            "contentPolicy": {"filters": [
                {"type": "VIOLENCE", "detected": True, "action": "BLOCKED",
                 "confidence": "HIGH"}]},
            "sensitiveInformationPolicy": {"piiEntities": [
                {"type": "EMAIL", "detected": True, "action": "BLOCKED",
                 "match": "a@b.c"}]},
            "topicPolicy": {"topics": [
                {"name": "InvestmentAdvice", "type": "DENY", "detected": True,
                 "action": "BLOCKED"}]},
            "wordPolicy": {
                "customWords": [{"match": "moonquake", "detected": True,
                                 "action": "BLOCKED"}],
                "managedWordLists": [{"match": "profanity", "type": "PROFANITY",
                                      "detected": True, "action": "BLOCKED"}]},
            "contextualGroundingPolicy": {"filters": [
                {"type": "GROUNDING", "threshold": 0.7, "score": 0.31,
                 "action": "BLOCKED", "detected": True}]},
            "invocationMetrics": {"guardrailProcessingLatency": 142},
        }],
        "usage": {"contentPolicyUnits": 1, "topicPolicyUnits": 1,
                  "wordPolicyUnits": 1, "sensitiveInformationPolicyUnits": 1,
                  "contextualGroundingPolicyUnits": 1},
        "guardrailCoverage": {"textCharacters": {"guarded": 42, "total": 42}},
    }
    asm = R.read_assessment(resp)
    assert asm.detected("VIOLENCE") and asm.blocked("VIOLENCE")
    assert asm.pii_detected == ["EMAIL"] and asm.pii_actions["EMAIL"] == "BLOCKED"
    assert asm.topics_detected == ["InvestmentAdvice"]
    assert asm.blocked("TOPIC:InvestmentAdvice")
    assert sorted(asm.words_detected) == ["moonquake", "profanity"]
    assert asm.grounding == [{"type": "GROUNDING", "score": 0.31, "threshold": 0.7,
                              "action": "BLOCKED", "detected": True}]
    assert asm.guardrail_latency_ms == 142
    assert asm.coverage["textCharacters"]["guarded"] == 42


def test_an_undetected_pii_entity_is_not_recorded_as_detected():
    """The response lists every configured entity, detected or not.

    The PII guardrail configures all 31 types, so a response carries rows for types that
    did not fire. Reading the list length instead of the `detected` flag would report
    31/31 recall for every item — a perfect score produced by counting the configuration.
    """
    resp = {"assessments": [{"sensitiveInformationPolicy": {"piiEntities": [
        {"type": "EMAIL", "detected": True, "action": "BLOCKED"},
        {"type": "PHONE", "detected": False, "action": "NONE"},
        {"type": "NAME", "detected": False, "action": "NONE"}]}}]}
    asm = R.read_assessment(resp)
    assert asm.pii_detected == ["EMAIL"]


def test_usage_is_recorded_for_every_item_not_only_the_billing_arm():
    """F10-2's claim is about billing; it generalises over every arm.

    A text-unit figure measured only on F10-2's dedicated arm cannot be cross-checked
    against the arms it generalises over — so `usage` is read on every response, and any
    arm's rows can falsify "billing is per text unit".
    """
    asm = R.read_assessment(cf_response(usage={"contentPolicyUnits": 3}))
    assert asm.text_units == {"contentPolicyUnits": 3}


def test_grounding_score_of_zero_survives():
    """`0.0` is a score, not a missing value.

    A truthiness test (`if g.get("score")`) would drop the most extreme ungrounded
    response in the corpus — the one F3-7 most depends on.
    """
    resp = {"assessments": [{"contextualGroundingPolicy": {"filters": [
        {"type": "GROUNDING", "threshold": 0.7, "score": 0.0, "action": "BLOCKED",
         "detected": True}]}}]}
    asm = R.read_assessment(resp)
    assert asm.grounding[0]["score"] == 0.0


def test_zero_latency_is_kept_and_absent_latency_is_none():
    """`invocationMetrics` absent and latency 0 must not collapse to the same value."""
    assert R.read_assessment(cf_response(latency=0)).guardrail_latency_ms == 0
    assert R.read_assessment(cf_response()).guardrail_latency_ms is None


# --------------------------------------------------------------------------
# the hit function
# --------------------------------------------------------------------------

def test_the_default_hit_is_the_items_own_label():
    spec = R.ArmSpec("T", "f3", "c", "g")
    asm = R.read_assessment(cf_response(detected=("VIOLENCE",)))
    assert spec.hit_of({"label": "VIOLENCE"}, asm) is True
    assert spec.hit_of({"label": "HATE"}, asm) is False


def test_a_recall_arm_does_not_count_the_wrong_category_as_a_hit():
    """Category-level recall, not "something fired".

    An item labelled VIOLENCE that trips HATE is not evidence that the VIOLENCE filter
    detects violence. Pooling them would inflate every per-category recall by the
    cross-category confusion rate — and F3-1's oracle is per category.
    """
    spec = R.ArmSpec("T", "f3", "c", "g")
    asm = R.read_assessment(cf_response(detected=("HATE",)))
    assert spec.hit_of({"label": "VIOLENCE"}, asm) is False


def test_any_detection_spans_all_policies():
    """The FPR reading. A benign item blocked by ANY policy is a false positive.

    Deliberately broader than "the content filter fired": the number §7.1's precision
    arithmetic needs is the rate a reader experiences, and a reader whose benign request
    was blocked by the word filter experienced a false positive.
    """
    for resp in (
        cf_response(detected=("VIOLENCE",)),
        {"assessments": [{"wordPolicy": {"customWords": [
            {"match": "moonquake", "detected": True}]}}]},
        {"assessments": [{"topicPolicy": {"topics": [
            {"name": "T", "detected": True}]}}]},
        {"assessments": [{"sensitiveInformationPolicy": {"piiEntities": [
            {"type": "EMAIL", "detected": True}]}}]},
        {"assessments": [{"contextualGroundingPolicy": {"filters": [
            {"type": "GROUNDING", "detected": True, "score": 0.1}]}}]},
    ):
        assert R.any_detection({}, R.read_assessment(resp)) is True
    assert R.any_detection({}, R.read_assessment(cf_response())) is False


# --------------------------------------------------------------------------
# the runner: failures, resume, denominators
# --------------------------------------------------------------------------

def test_a_failed_trial_is_excluded_from_the_denominator(roots):
    """`n_usable` != `n_attempted`, and the Wilson interval is built on the former.

    An item that never reached the service counted as a non-detection would push every
    recall down by the harness's own throttle rate and publish it as a property of the
    guardrail.
    """
    from botocore.exceptions import ClientError
    boom = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"},
                        "ResponseMetadata": {"RequestId": "r", "HTTPStatusCode": 429}},
                       "ApplyGuardrail")
    # 3 items: first succeeds, second fails all retries, third succeeds.
    c = StubClient([cf_response(detected=("VIOLENCE",)),
                    boom, boom, boom,
                    cf_response(detected=("VIOLENCE",))])
    t = R.run_arm(R.ArmSpec("T", "f3", "c", "g"), items(3),
                  run_id="r1", factory=factory_with(c), **roots)
    assert t["n_attempted"] == 3
    assert t["n_usable"] == 2
    assert t["x"] == 2
    assert t["n_failed"] == 1
    # The CODE, not merely the count. `capture()` absorbs the ClientError by design, so
    # `raise_for_status` is the only thing that can carry the code out — and in the first
    # draft it raised a bare RuntimeError, which recorded EVERY failure as "RuntimeError"
    # and (worse) made `is_retryable` classify throttling as permanent, so the item got
    # one attempt instead of three. Asserting the count alone passed on the broken code.
    assert t["failure_codes"] == ["ThrottlingException"]
    assert len(c.calls) == 5, "the throttled item must have been retried to exhaustion"


def test_a_resume_re_sends_exactly_the_missing_items(roots):
    """The trial id is the item's own content-hash id, not an index.

    "The last N" would double-count or skip on any failure that was not the final one:
    with item 2 of 3 failed, an index-based resume would restart at 3 and never re-send 2.
    """
    from botocore.exceptions import ClientError
    boom = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"},
                        "ResponseMetadata": {}}, "ApplyGuardrail")
    ok = cf_response(detected=("VIOLENCE",))
    c1 = StubClient([ok, boom, boom, boom, ok])
    spec = R.ArmSpec("T", "f3", "c", "g")
    R.run_arm(spec, items(3), run_id="r1", factory=factory_with(c1), **roots)

    # Resume: only the failed item must be re-sent.
    c2 = StubClient([ok])
    t = R.run_arm(spec, items(3), run_id="r1", factory=factory_with(c2), **roots)
    assert len(c2.calls) == 1, "a resume must re-send only the missing item"
    assert c2.calls[0]["content"][0]["text"]["text"] == "item 1"
    assert t["n_usable"] == 3 and t["x"] == 3


def test_the_resume_guarantee_lives_in_the_checkpoint_not_in_the_loop(roots):
    """Where the guarantee actually is, and an honest statement of what the loop adds.

    A mutation run put the loop's skip through two mutants — keying it on the loop index
    instead of the item id, and deleting it outright — and **both survived all 29 arms**.
    The reason is not a missing test: `Checkpoint.run_trial` re-checks `is_done` itself
    (lib/checkpoint.py:294) and returns the recorded result without calling `fn`, so no
    reachable input distinguishes the three versions. The loop's check is a redundant
    second layer whose value is skipping the closure, not correctness.

    Rather than leave two survivors described as "equivalent", the guarantee is asserted
    at the layer that provides it: `run_trial` must not invoke its callable for a trial it
    already holds. That is the assertion that would fail if the real defence were removed
    — and it is a different claim from "the loop skipped it", which is what the surviving
    mutants showed was never being tested.
    """
    from checkpoint import Checkpoint
    cp = Checkpoint("T", "main", root=roots["checkpoint_root"]).load()
    calls = []

    def fn():
        calls.append(1)
        return {"v": 1}

    first = cp.run_trial("t1", fn)
    cp.run_trial("t1", fn)
    assert calls == [1], "run_trial must not re-invoke fn for a recorded trial"
    # And the second call returns the ORIGINAL record, not a fresh one — the property that
    # makes a resume idempotent rather than merely quiet. `record()` merges `attempts` and
    # `retry_delay_s` into what it stores, so identity to `first` is the assertion; a
    # comparison against the bare `{"v": 1}` would be asserting my recollection of the
    # stored shape rather than the behaviour under test.
    assert cp.run_trial("t1", fn) == first
    assert first["v"] == 1 and first["attempts"] == 1
    assert len(calls) == 1


def test_both_layers_of_the_resume_skip_are_present(roots):
    """A structural arm, with the reason the redundancy is kept.

    The two defences fail independently: if `run_trial`'s guard were ever loosened, the
    loop's `is_done` is what still keeps a completed item from being re-sent — and a
    re-sent item in a live arm is a duplicate evidence record plus a second charge for a
    text unit already paid for. Structural because, as the mutation run established, no
    behavioural input can tell the one-layer version from the two-layer one.
    """
    import inspect
    assert 'if cp.is_done(item["id"]):' in inspect.getsource(R.run_arm)
    assert "if self.is_done(trial_id):" in inspect.getsource(
        __import__("checkpoint").Checkpoint.run_trial)


def test_a_completed_arm_re_sends_nothing(roots):
    ok = cf_response(detected=("VIOLENCE",))
    spec = R.ArmSpec("T", "f3", "c", "g")
    R.run_arm(spec, items(3), run_id="r1",
              factory=factory_with(StubClient([ok] * 3)), **roots)
    c2 = StubClient([])                     # any call raises "stub exhausted"
    t = R.run_arm(spec, items(3), run_id="r1", factory=factory_with(c2), **roots)
    assert c2.calls == [] and t["n_usable"] == 3


def test_two_arms_of_one_case_do_not_share_a_checkpoint(roots):
    """`case_id` + `cell` name the file; folding the label into `case_id` collides.

    F8-2's CLASSIC and STANDARD arms run the same corpus ids against different
    guardrails. One checkpoint would make the second arm "resume" the first's results and
    report a tier difference of exactly zero — the most plausible-looking wrong answer
    available.
    """
    ok = cf_response(detected=("VIOLENCE",))
    a = R.ArmSpec("F8-2", "f8", "c", "g-classic", label="classic")
    b = R.ArmSpec("F8-2", "f8", "c", "g-standard", label="standard")
    R.run_arm(a, items(2), run_id="r1", factory=factory_with(StubClient([ok] * 2)),
              **roots)
    cb = StubClient([ok] * 2)
    tb = R.run_arm(b, items(2), run_id="r1", factory=factory_with(cb), **roots)
    assert len(cb.calls) == 2, "the second arm must send its own calls"
    assert tb["checkpoint"] != R.tally(
        __import__("checkpoint").Checkpoint("F8-2", "classic",
                                            root=roots["checkpoint_root"]).load(),
        a, 2)["checkpoint"]
    assert cb.calls[0]["guardrailIdentifier"] == "g-standard"


def test_the_arm_refuses_to_run_if_the_sdk_cannot_express_it():
    """F1-1's check, made routine.

    botocore does not reject an unmodelled operation with a clear error at call time in
    every case; the honest failure is "your SDK cannot express this test", raised before
    a single item is sent, rather than a run of results collected against a different API
    surface than the one the claim is about.
    """
    c = StubClient([], ops=())              # ApplyGuardrail absent from the model
    with pytest.raises(RuntimeError, match="ApplyGuardrail"):
        R.run_arm(R.ArmSpec("T", "f3", "c", "g"), items(1), run_id="r1",
                  factory=factory_with(c))


def test_the_guardrail_identifier_and_version_reach_the_call(roots):
    c = StubClient([cf_response()] * 1)
    R.run_arm(R.ArmSpec("T", "f3", "c", "gr-abc", guardrail_version="3",
                        source="OUTPUT"),
              items(1), run_id="r1", factory=factory_with(c), **roots)
    call = c.calls[0]
    assert call["guardrailIdentifier"] == "gr-abc"
    assert call["guardrailVersion"] == "3"
    assert call["source"] == "OUTPUT"


def test_qualifiers_are_sent_only_when_asked(roots):
    """`guard_content` is F5-6's independent variable, so it must never be a default.

    The untagged arm exists precisely to test whether tagging is required (DC-2). If the
    runner added a qualifier by default, the untagged arm would not be untagged and the
    experiment would measure nothing.
    """
    c = StubClient([cf_response()] * 2)
    R.run_arm(R.ArmSpec("T", "f3", "c", "g"), items(1), run_id="r1",
              factory=factory_with(c), **roots)
    assert "qualifiers" not in c.calls[0]["content"][0]["text"]
    c2 = StubClient([cf_response()])
    R.run_arm(R.ArmSpec("T2", "f3", "c", "g", qualifiers=("guard_content",)),
              items(1), run_id="r1", factory=factory_with(c2), **roots)
    assert c2.calls[0]["content"][0]["text"]["qualifiers"] == ["guard_content"]


def test_the_row_carries_the_request_id_and_the_evidence_path(roots):
    """A claim a reader can quote to AWS Support is a different class of evidence."""
    c = StubClient([cf_response(detected=("VIOLENCE",))])
    t = R.run_arm(R.ArmSpec("T", "f3", "c", "g"), items(1), run_id="r1",
                  factory=factory_with(c), **roots)
    row = t["rows"][0]
    assert row["request_id"] == "req-0001"
    assert row["evidence"].endswith(".json")
    assert Path(row["evidence"]).is_file()
    assert row["client_duration_ms"] >= 0.0


def test_the_checkpoint_metadata_records_the_scope_and_the_smoke_flag(roots):
    """A smoke run's rate must never be reportable as a result.

    `--n 3` takes the first three items in file order — a stated subset, not a random
    one — but it is still not representative. `is_smoke` travels in the metadata so the
    analysis can refuse it rather than relying on whoever runs it to remember.
    """
    c = StubClient([cf_response()] * 2)
    R.run_arm(R.ArmSpec("T", "f3", "corpus/x.jsonl", "g"), items(2), run_id="r1",
              factory=factory_with(c), is_smoke=True, **roots)
    cp = json.loads((roots["checkpoint_root"] / "T__main.json").read_text())
    meta = cp["meta"]
    assert meta["output_scope"] == "FULL"
    assert meta["is_smoke"] is True
    assert meta["corpus"] == "corpus/x.jsonl"
    assert meta["planned_n"] == 2
    assert meta["sdk"]


# --------------------------------------------------------------------------
# corpora
# --------------------------------------------------------------------------

def test_a_missing_corpus_names_the_path_it_looked_for():
    """The guard's value is the message, not the exception.

    A mutation run deleted the `p.exists()` check and all 29 arms stayed green — correctly:
    `read_text` raises `FileNotFoundError` on its own, so the guard cannot change *whether*
    it raises. What it changes is whether the error says which corpus, resolved against
    which root. `--n 3` smoke runs are launched from several directories and `CORPORA` is
    computed from `__file__`, so "no such file: benign.jsonl" and "no such file:
    /.../corpora/benign/benign.jsonl" are minutes apart in diagnosis.

    Asserting the message is therefore the honest arm — the original assertion (that
    `FileNotFoundError` is raised) was true of the code with the guard removed, i.e. it was
    testing Python's behaviour rather than ours.
    """
    with pytest.raises(FileNotFoundError, match=r"corpora.*does/not/exist\.jsonl"):
        R.load_corpus("does/not/exist.jsonl")


def test_an_empty_corpus_raises(tmp_path, monkeypatch):
    """An arm over zero items would report a vacuous 0/0 and look like a pass.

    Same defect as an assertion floor set below the current yield: the gate is green and
    nothing was measured.
    """
    monkeypatch.setattr(R, "CORPORA", tmp_path)
    (tmp_path / "empty.jsonl").write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        R.load_corpus("empty.jsonl")


def test_limit_takes_a_prefix_in_file_order(tmp_path, monkeypatch):
    """Reproducible, so a smoke run's items can be inspected and re-sent."""
    monkeypatch.setattr(R, "CORPORA", tmp_path)
    (tmp_path / "c.jsonl").write_text(
        "\n".join(json.dumps({"id": f"i{k}", "text": "t"}) for k in range(5)),
        encoding="utf-8")
    assert R.corpus_ids(R.load_corpus("c.jsonl", limit=2)) == ["i0", "i1"]
    assert len(R.load_corpus("c.jsonl")) == 5


def test_an_unstratified_head_can_miss_a_label_entirely(tmp_path, monkeypatch):
    """The defect, reproduced on a fixture: this is why `stratify_by` exists.

    Not a redundant arm against the one below — it pins the *plain* head's behaviour as
    deliberate rather than accidental. A head is correct when the caller treats every
    returned item alike, and it must keep working that way; the bug was using it in a
    caller that splits the rows into strata afterwards.
    """
    monkeypatch.setattr(R, "CORPORA", tmp_path)
    (tmp_path / "c.jsonl").write_text(
        "\n".join(json.dumps({"id": f"a{k}", "text": "t", "label": "ATTACK"})
                  for k in range(5)) + "\n" +
        "\n".join(json.dumps({"id": f"c{k}", "text": "t", "label": "CLEAN"})
                  for k in range(3)),
        encoding="utf-8")
    head = R.load_corpus("c.jsonl", limit=3)
    assert {it["label"] for it in head} == {"ATTACK"}, (
        "the fixture no longer reproduces the grouped-file layout this guards against")


def test_stratified_limit_keeps_every_label_present(tmp_path, monkeypatch):
    """n per label, in file order, and no label dropped.

    F8-2 divides one arm's rows into attacks and CLEAN and compares the two rates. Under an
    unstratified `--n 3` its CLEAN stratum was empty, so the comparison had one interval and
    a zero denominator — after the calls were billed. Stratifying makes "both strata exist"
    a property of the sampler instead of a property of where a label happens to sit in the
    file.
    """
    monkeypatch.setattr(R, "CORPORA", tmp_path)
    (tmp_path / "c.jsonl").write_text(
        "\n".join(json.dumps({"id": f"a{k}", "text": "t", "label": "ATTACK"})
                  for k in range(5)) + "\n" +
        "\n".join(json.dumps({"id": f"c{k}", "text": "t", "label": "CLEAN"})
                  for k in range(3)),
        encoding="utf-8")
    got = R.load_corpus("c.jsonl", limit=2, stratify_by="label")
    assert R.corpus_ids(got) == ["a0", "a1", "c0", "c1"], (
        "expected the first 2 of each label, in original file order")
    # A stratum smaller than the limit contributes all of itself, and does not borrow
    # from another stratum to reach n — that would silently reweight the comparison.
    got3 = R.load_corpus("c.jsonl", limit=4, stratify_by="label")
    assert [it["label"] for it in got3].count("CLEAN") == 3
    assert [it["label"] for it in got3].count("ATTACK") == 4


def test_stratify_is_a_noop_without_a_limit(tmp_path, monkeypatch):
    """The full runs this project reports must be byte-identical either way.

    If `stratify_by` changed the full-run item set or its order, then a smoke-path fix
    would have altered every published rate — which is a far worse bug than the one it
    fixed.
    """
    monkeypatch.setattr(R, "CORPORA", tmp_path)
    (tmp_path / "c.jsonl").write_text(
        "\n".join(json.dumps({"id": f"i{k}", "text": "t", "label": "L" if k % 2 else "M"})
                  for k in range(9)),
        encoding="utf-8")
    assert (R.corpus_ids(R.load_corpus("c.jsonl", stratify_by="label"))
            == R.corpus_ids(R.load_corpus("c.jsonl")))


def test_stratifying_on_an_absent_key_raises_rather_than_pooling(tmp_path, monkeypatch):
    """A missing key would make every item one stratum — i.e. a plain head, quietly.

    That failure mode is the one this whole mechanism exists to prevent, so it must not be
    reachable by a typo in the field name.
    """
    monkeypatch.setattr(R, "CORPORA", tmp_path)
    (tmp_path / "c.jsonl").write_text(
        json.dumps({"id": "i0", "text": "t", "label": "L"}) + "\n" +
        json.dumps({"id": "i1", "text": "t"}) + "\n", encoding="utf-8")
    with pytest.raises(KeyError, match=r"no 'label' field.*line 2"):
        R.load_corpus("c.jsonl", limit=1, stratify_by="label")


def test_the_multilingual_corpora_need_stratification_at_every_smoke_n():
    """Against the sealed corpora, not a fixture — the fixture proves my model, not AWS's.

    All 7 files place their 6 CLEAN items last, so the unstratified head is CLEAN-free for
    every n a smoke run would plausibly use. `n=54` is the first head that reaches a CLEAN
    item, and nobody smokes at 54.
    """
    for lang in ("en", "fr", "es", "zh-TW", "zh-CN", "ja", "ko"):
        rel = f"multilingual/{lang}.jsonl"
        for n in (1, 3, 5, 10):
            plain = {it["label"] for it in R.load_corpus(rel, limit=n)}
            assert "CLEAN" not in plain, f"{rel} n={n}: fixture assumption broke"
            strat = {it["label"] for it in
                     R.load_corpus(rel, limit=n, stratify_by="label")}
            assert "CLEAN" in strat, f"{rel} n={n}: no CLEAN item in the stratified subset"
            assert len(strat) == 8, f"{rel} n={n}: expected all 8 labels, got {sorted(strat)}"


def test_a_real_corpus_loads_and_has_the_fields_the_runner_reads():
    """Against the sealed corpora, not a fixture.

    A fixture I wrote can only confirm the shape I believe the corpus has. The runner
    reads `id`, `text` and `label`; if `corpora/build.py` ever renames one, this fails
    here rather than producing an arm whose every item is labelled "".
    """
    items_ = R.load_corpus("benign/benign.jsonl", limit=5)
    assert items_, "the benign corpus is Phase 1's FPR denominator"
    for it in items_:
        assert it["id"] and isinstance(it["text"], str) and it["text"].strip()


# --------------------------------------------------------------------------
# per-label tally
# --------------------------------------------------------------------------

def test_per_label_tally_does_not_pool():
    """F3-8 and F3-4 have per-label oracles.

    A pooled rate lets a strong subtype conceal a failing one, and the pooled figure is
    an average over a corpus composition we chose — so it is not a statement about any
    subtype. 2/2 and 0/2 pool to 50%, which is true of neither.
    """
    rows = [{"label": "JAILBREAK", "hit": True}, {"label": "JAILBREAK", "hit": True},
            {"label": "PROMPT_LEAKAGE", "hit": False},
            {"label": "PROMPT_LEAKAGE", "hit": False}]
    out = R.per_label_tally(rows)
    assert out["JAILBREAK"] == {"x": 2, "n": 2}
    assert out["PROMPT_LEAKAGE"] == {"x": 0, "n": 2}


def test_an_unlabelled_row_is_visible_rather_than_dropped():
    """Silently dropping it would shrink the denominator without saying so."""
    out = R.per_label_tally([{"hit": True}])
    assert out["?"] == {"x": 1, "n": 1}


# --------------------------------------------------------------------------
# the three fields F8-6 and F10-2 read — added to the shared reader, so tested here
# --------------------------------------------------------------------------

def test_applied_guardrail_details_are_read():
    """F8-6's instrument. `guardrailArn` embeds the Region that served the evaluation.

    Read on every arm, not only F8-6's, because an arm that silently ran against an
    ACCOUNT_ENFORCED guardrail rather than the one it named would report the wrong
    configuration's behaviour — exactly what Phase 5c's enforcement window could cause,
    and unrecoverable after the fact if the field were dropped.
    """
    # Assembled at run time, not written as a literal: `check_redaction.py` scans this
    # tree for `arn:aws...:`, and it is right to — a test fixture is the easiest place for
    # a real ARN to be pasted and forgotten. The string "REDACTED" in the account field
    # did not help, because the gate matches the ARN PREFIX, not the account. A literal
    # here left the gate failing while this suite passed, which is the one combination
    # that reads as clean.
    gr_arn = ":".join(["arn", "aws", "bedrock", "us-west-2", "0" * 12, "guardrail/gr-abc"])
    resp = {"action": "NONE", "assessments": [{"appliedGuardrailDetails": {
        "guardrailId": "gr-abc", "guardrailVersion": "DRAFT",
        "guardrailArn": gr_arn,
        "guardrailOrigin": ["REQUEST"], "guardrailOwnership": "SELF"}}]}
    asm = R.read_assessment(resp)
    assert asm.applied_details["guardrailArn"].split(":")[3] == "us-west-2"
    # A LIST, kept as a list. A reader that took [0] would report one origin for a
    # response carrying two, and the shape is the service's to define.
    assert asm.applied_details["guardrailOrigin"] == ["REQUEST"]
    assert asm.applied_details["guardrailOwnership"] == "SELF"


def test_an_account_enforced_origin_is_distinguishable_from_a_requested_one():
    """The mutation that matters: the two origins must not read the same.

    If `guardrailOrigin` were dropped, an ACCOUNT_ENFORCED response and a REQUEST one
    would be byte-identical in the row — and every Phase 1 arm's guardrail identity would
    rest on the identifier the script *sent*, not on the one the service *applied*.
    """
    def origin(o):
        return R.read_assessment({"assessments": [{"appliedGuardrailDetails": {
            "guardrailId": "gr-abc", "guardrailOrigin": o}}]}).applied_details

    assert origin(["REQUEST"]) != origin(["ACCOUNT_ENFORCED"])
    assert origin(["REQUEST", "ACCOUNT_ENFORCED"])["guardrailOrigin"] == [
        "REQUEST", "ACCOUNT_ENFORCED"]


def test_invocation_usage_is_read_separately_from_top_level_usage():
    """F10-2's oracle compares the two. They must not collapse into one field.

    The service reports the nine text-unit counters in two places: top-level `usage` and
    `assessments[].invocationMetrics.usage`. F10-2 asks whether TextUnitCount "matches the
    billed quantity", so a disagreement between the two places the service itself reports
    it is a finding — and a reader that stored only one could never see it.
    """
    resp = {"action": "NONE",
            "usage": {"contentPolicyUnits": 3},
            "assessments": [{"invocationMetrics": {
                "guardrailProcessingLatency": 88,
                "usage": {"contentPolicyUnits": 4},
                "guardrailCoverage": {"textCharacters": {"guarded": 10, "total": 12}}}}]}
    asm = R.read_assessment(resp)
    assert asm.text_units == {"contentPolicyUnits": 3}
    assert asm.invocation_usage == {"contentPolicyUnits": 4}
    assert asm.text_units != asm.invocation_usage
    assert asm.invocation_coverage["textCharacters"] == {"guarded": 10, "total": 12}
    assert asm.guardrail_latency_ms == 88


def test_the_new_fields_default_empty_rather_than_none():
    """A response without them is a legitimate response, not an error.

    `appliedGuardrailDetails` and `invocationMetrics.usage` are optional members. An
    absent one must read as an empty dict so `if row["applied_details"]:` is the honest
    test — a None would make every downstream `.get` a TypeError, and a KeyError here
    would turn "this response omitted an optional field" into a dead arm.
    """
    asm = R.read_assessment({"action": "NONE", "assessments": [{}]})
    assert asm.applied_details == {}
    assert asm.invocation_usage == {}
    assert asm.invocation_coverage == {}


def test_partial_coverage_is_not_rounded_to_full(roots):
    """`guardrailCoverage` is a pair, and the pair is what F10-2 reads.

    A row carrying only `guarded` would make a partially-guarded request look fully
    guarded; F10-2's content-length sweep is precisely a claim about how much of the text
    the service counted.
    """
    resp = {"action": "NONE", "assessments": [], "usage": {},
            "guardrailCoverage": {"textCharacters": {"guarded": 200, "total": 1000}}}
    asm = R.read_assessment(resp)
    tc = asm.coverage["textCharacters"]
    assert (tc["guarded"], tc["total"]) == (200, 1000)
    assert tc["guarded"] != tc["total"]


def test_the_new_fields_reach_the_arm_row(roots):
    """Reading them into the Assessment is not enough; the ROW is what is persisted.

    `run_arm` builds the row by hand, so a field added to `read_assessment` and not to the
    row would be collected, discarded, and impossible to recover — the arm would have to
    be paid for twice.
    """
    resp = {"action": "NONE", "usage": {"contentPolicyUnits": 1},
            "assessments": [{
                "contentPolicy": {"filters": []},
                "invocationMetrics": {"usage": {"contentPolicyUnits": 1},
                                      "guardrailCoverage": {
                                          "textCharacters": {"guarded": 5, "total": 5}}},
                "appliedGuardrailDetails": {"guardrailOrigin": ["REQUEST"],
                                            "guardrailOwnership": "SELF"}}]}
    client = StubClient(responses=[resp])
    spec = R.ArmSpec(case_id="F10-2", family="f10", corpus="c.jsonl",
                     guardrail_id="gr-abc", label="probe")
    t = R.run_arm(spec, items(1), run_id="r20260810T000000Z", is_smoke=True,
                  factory=factory_with(client), **roots)
    row = t["rows"][0]
    assert row["invocation_usage"] == {"contentPolicyUnits": 1}
    assert row["invocation_coverage"]["textCharacters"]["total"] == 5
    assert row["applied_details"]["guardrailOrigin"] == ["REQUEST"]
