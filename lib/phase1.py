#!/usr/bin/env python3
"""The Phase 1 case layer: manifest lookup, Observation construction, one output shape.

`lib/arms.py` sends a corpus through a guardrail. This module is what sits between an
arm's tally and `lib/oracle.evaluate` — the step where a case says *which* number the
sealed oracle asked for. Eighteen scripts share it so that step is written once.

Three things live here rather than in each script, each for a reason that showed up
while the guardrail provisioner was being written.

1. A guardrail id is resolved through a status check, not by key lookup
------------------------------------------------------------------------
`CreateGuardrail` returns `status=CREATING`, not READY. `f3_efficacy/00_guardrails.py`
waits, but nothing stopped a case script from reading the manifest anyway — and an
`ApplyGuardrail` against a still-building guardrail fails with an error that lands in
the checkpoint's failure map looking exactly like a throttle. `guardrail()` refuses a
row whose status is not READY, so the confound cannot reach the data.

2. The observation is built by a named function per oracle KIND
---------------------------------------------------------------
`Observation` has 26 optional fields and `_decide` reads a different subset for each of
its 20 kinds. Filling the wrong subset does not raise: `_need` catches a *missing*
field, but nothing catches a field that is present and means something else. An FPR
count placed in `detect_x` would be silently evaluated as a detection rate. So each
shape gets a builder whose parameter names are the quantities, and the builders are the
only way this project constructs an Observation from a tally.

3. `n_usable` travels, and so does the failure reason
-----------------------------------------------------
Every emitted payload carries `n_attempted`, `n_usable` and `failure_codes` from the
checkpoint. A cell that shrank is visible on the face of the result rather than
recoverable from a log, and after the `CapturedCallError` defect (a throttle recorded
as `error_code="RuntimeError"`, retried zero times) the codes are the field that says
whether a shortfall was the service or was us.

Exit-code convention, inherited from `f5_redteam/07a_privatelink_enum.py`: the exit code
reports whether the *test ran*, never whether the document was right. A case that
refutes the document is a successful test and exits 0. Only a case that measured
nothing exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import arms as R
import awsclients as A
import oracle as O
import redact as _redact
import stats as S
from evidence import EvidenceStore, capture, new_run_id

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
MANIFEST_PATH = RESULTS / "phase1_guardrails.json"
PHASE1_OUT = RESULTS / "phase1"

# The strengths the provisioner created, in lattice order. Imported here rather than
# from f3_efficacy/00_guardrails.py because that file's name begins with a digit and is
# not importable; the manifest carries the same list under `strength_lattice` and the
# loader checks this constant against it, so a divergence fails instead of drifting.
#
# NONE is NOT in this tuple, and its absence is a measured API constraint rather than a
# design choice. `CreateGuardrail` rejects a contentPolicyConfig whose every filter sits at
# NONE:
#     ValidationException: At least one content filter strength must be set to not NONE.
# Probed three ways on 2026-08-10 (see FINDING-F3-9-LATTICE.md): all six filters at NONE is
# rejected; the same config with `inputEnabled=False`/`outputEnabled=False` is *also*
# rejected, so disabling is not a way around it; and every category at NONE with
# PROMPT_ATTACK at LOW is ACCEPTED, which locates the constraint as "at least one of the six
# strengths", not "the five categories must be armed".
#
# The consequence for F3-9 is that the ROC's leftmost non-trivial vertex — a guardrail that
# is configured but classifies nothing — **cannot be constructed**. The lattice is therefore
# 3 settings, and the reachable vertex count is 3 + 2 trivial endpoints = 5, still under the
# sealed oracle's ceiling of 7. Keeping NONE here would have been worse than wrong: every
# arm script calls P.guardrail("cf-none") on a manifest entry that no create call can
# produce, and the first run recorded that failure as `READY (pre-existing)`.
STRENGTHS = ("LOW", "MEDIUM", "HIGH")

# Kept as data because the analysis has to state what it could not measure. An ROC missing
# its leftmost vertex because the service forbids that configuration is a different object
# from one missing it because nobody ran it.
UNREACHABLE_STRENGTHS = {
    "NONE": "CreateGuardrail rejects an all-NONE contentPolicyConfig with "
            "ValidationException 'At least one content filter strength must be set to not "
            "NONE.' — also when every filter is inputEnabled=False, so the constraint is on "
            "the strengths and not on whether the filters are armed (measured 2026-08-10)",
}

# The strengths §7.3 and Appendix A actually recommend, which is what "at the
# recommended threshold" in F3-1/F3-2/F3-3/F3-8's sealed oracles refers to. Both are
# read out of the document under test, so both are quoted:
#   §7.3  "Prompt Attack (HIGH threshold), Content Filter (MEDIUM)"
#   App.A "Prompt Injection/Attack ✅ HIGH" / "Violent Content ✅ MEDIUM"
# Pinning them as constants matters because the phrase "the recommended threshold"
# appears in four oracles and picking a different strength per case would make the four
# results incomparable while each looked individually defensible.
RECOMMENDED_CONTENT_STRENGTH = "MEDIUM"
RECOMMENDED_ATTACK_STRENGTH = "HIGH"

# The five content-filter categories, and the three prompt-attack subtypes. The
# prompt-attack subtypes are a *content-filter* claim in only one direction:
# `contentPolicyConfig` has a single PROMPT_ATTACK filter, while
# `InvokeGuardrailChecks.promptAttack` has all three as separate categories. F3-8's
# per-subtype oracle is therefore answerable on ApplyGuardrail only as "did the single
# PROMPT_ATTACK filter fire on an item of this subtype", and the scripts say so.
CF_CATEGORIES = ("VIOLENCE", "HATE", "SEXUAL", "MISCONDUCT", "INSULTS")
ATTACK_SUBTYPES = ("JAILBREAK", "PROMPT_INJECTION", "PROMPT_LEAKAGE")

# Languages the document claims CLASSIC covers, and the ones it says are unprotected.
# §3.4: "English, French, Spanish only" vs "essentially no protection for
# Chinese/Japanese/Korean traffic".
CLASSIC_LANGS = ("en", "fr", "es")
UNSUPPORTED_LANGS = ("zh-TW", "zh-CN", "ja", "ko")


# ---------------------------------------------------------------------------
# the guardrail manifest
# ---------------------------------------------------------------------------

_MANIFEST: dict[str, Any] | None = None


def manifest(path: Path | None = None) -> dict[str, Any]:
    """The provisioner's output, read once.

    A missing manifest names the command that produces it. The alternative — a
    `FileNotFoundError` on `results/phase1_guardrails.json` — is a path with no
    indication that a provisioning step exists at all, and every one of the eighteen
    case scripts would produce it.
    """
    global _MANIFEST
    p = path or MANIFEST_PATH
    if _MANIFEST is None or path is not None:
        if not p.is_file():
            raise FileNotFoundError(
                f"{p} does not exist. The Phase 1 guardrails have not been provisioned; "
                f"run `python f3_efficacy/00_guardrails.py --ensure` first (it is "
                f"idempotent by name, so re-running it is safe)")
        body = json.loads(p.read_text(encoding="utf-8"))
        lattice = tuple(body.get("strength_lattice") or ())
        if lattice != STRENGTHS:
            raise RuntimeError(
                f"the manifest's strength lattice {lattice} differs from this module's "
                f"{STRENGTHS}. One of the two was edited; a case script that swept the "
                f"wrong lattice would report an ROC over operating points that do not "
                f"exist")
        if path is not None:
            return body
        _MANIFEST = body
    return _MANIFEST


def guardrail(key: str, *, man: dict | None = None) -> str:
    """The guardrail id for a logical arm name, or a refusal that says why.

    READY is checked, not assumed. See the module docstring: an ApplyGuardrail against a
    CREATING guardrail fails in a way that is indistinguishable from a throttle once it
    reaches the checkpoint's failure map, and the whole point of `n_usable` is to keep
    that class of loss visible.
    """
    # `man is None`, not `man or ...`: an EMPTY manifest dict is a manifest that was
    # read and found to record nothing, and the refusal below is the correct answer to
    # it. `man or manifest()` fell through to re-reading the file from disk instead,
    # which turns a stated-empty manifest into whatever happens to be on disk — and in
    # a run with no provisioned guardrails, into a FileNotFoundError about a missing
    # file rather than the missing key the caller actually passed.
    body = manifest() if man is None else man
    rows = body.get("guardrails") or {}
    if key not in rows:
        raise KeyError(f"no guardrail named {key!r} in {MANIFEST_PATH.name}; it has "
                       f"{sorted(rows)}")
    row = rows[key]
    if "error_code" in row:
        raise RuntimeError(
            f"guardrail {key!r} was rejected at create with {row['error_code']}: "
            f"{row.get('error_message', '')[:200]}. There is nothing to measure against "
            f"it, and running the arm anyway would fill the failure map with errors that "
            f"look like throttles")
    status = str(row.get("status", ""))
    if not status.startswith("READY"):
        raise RuntimeError(
            f"guardrail {key!r} has status {status!r}, not READY. A guardrail that has "
            f"not finished building rejects ApplyGuardrail with an error the checkpoint "
            f"cannot distinguish from a transient one — re-run the provisioner")
    gid = row.get("guardrail_id")
    if not gid:
        raise RuntimeError(f"guardrail {key!r} has no id in the manifest")
    return str(gid)


def configured_topic(man: dict | None = None) -> str:
    """The denied-topic name that was actually provisioned.

    Read from the manifest, not from a constant here. F3-5 scores a hit as "the topic
    policy reported THIS topic", and a name that disagreed with the provisioned guardrail
    would produce an in-topic recall of exactly 0 and an off-topic FPR of exactly 0 — a
    perfectly clean-looking pair of numbers describing a comparison that never happened.
    """
    # `man is None`, not `man or ...`: an EMPTY manifest dict is a manifest that was
    # read and found to record nothing, and the refusal below is the correct answer to
    # it. `man or manifest()` fell through to re-reading the file from disk instead,
    # which turns a stated-empty manifest into whatever happens to be on disk — and in
    # a run with no provisioned guardrails, into a FileNotFoundError about a missing
    # file rather than the missing key the caller actually passed.
    body = manifest() if man is None else man
    name = body.get("topic")
    if not name:
        raise RuntimeError(
            f"{MANIFEST_PATH.name} records no `topic`; it was written by an older "
            f"provisioner than the one F3-5 needs — re-run f3_efficacy/00_guardrails.py")
    return str(name)


def configured_words(man: dict | None = None) -> list[str]:
    """The custom word list that was actually provisioned, for the same reason."""
    # `man is None`, not `man or ...`: an EMPTY manifest dict is a manifest that was
    # read and found to record nothing, and the refusal below is the correct answer to
    # it. `man or manifest()` fell through to re-reading the file from disk instead,
    # which turns a stated-empty manifest into whatever happens to be on disk — and in
    # a run with no provisioned guardrails, into a FileNotFoundError about a missing
    # file rather than the missing key the caller actually passed.
    body = manifest() if man is None else man
    words = list(body.get("words") or [])
    if not words:
        raise RuntimeError(
            f"{MANIFEST_PATH.name} records no `words`; F3-6's listed-term half would have "
            f"nothing to check against — re-run f3_efficacy/00_guardrails.py")
    return words


# ---------------------------------------------------------------------------
# probe guardrails — created by a case, deleted by the same case
# ---------------------------------------------------------------------------
#
# Two Phase 1 cases cannot use the provisioner's manifest and must create their own
# guardrails: F8-5 (a tier x length boundary, and the provisioner's `topic` guardrail is
# CLASSIC-only) and F8-7 (a word-filter x language x tier matrix, and `wordPolicyConfig`
# has no `tierConfig` at all, so the tier has to be held by the guardrail). Both then have
# to delete what they made.
#
# That teardown lives here rather than being written twice because the failure mode is
# shared and is not visible locally: a probe guardrail that survives is a tagged resource,
# and `99_teardown.py`'s sweep exits non-zero on it — days later, in a different phase,
# with nothing to say which case left it. Writing the same `finally` in two scripts means
# two chances to get the ordering wrong; one helper means the guarantee is tested once.

@dataclass
class ProbeGuardrail:
    """One guardrail a case created for itself, and how it went."""

    label: str
    name: str
    accepted: bool
    guardrail_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    request_id: str = ""
    evidence: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def create_probe_guardrail(client, store, lim, *, label: str, name: str, config: dict,
                           tags: Sequence[dict], description: str,
                           **detail: Any) -> ProbeGuardrail:
    """One CreateGuardrail whose ERROR IS THE DATA.

    `capture` records the failure branch identically to the success branch, which is what
    makes "the service rejected a 201-character definition" quotable as an error code and a
    request id rather than as a Python traceback. Nothing here raises on a rejection: for
    F8-5 a rejection is the oracle firing.

    `description` is truncated to the model's 200-character maximum. That maximum is real
    and is on a different field from the one F8-5 is probing, so a long description would
    fail the create for a reason that has nothing to do with the boundary under test — and
    the result would read as the boundary holding.
    """
    lim.wait("CreateGuardrail")
    rec = capture(store, "create_guardrail", client,
                  name=name,
                  description=description[:200],
                  blockedInputMessaging="Blocked by the validation harness.",
                  blockedOutputsMessaging="Blocked by the validation harness.",
                  tags=list(tags),
                  **config)
    return ProbeGuardrail(
        label=label, name=name, accepted=rec.ok,
        guardrail_id=(rec.response or {}).get("guardrailId") if rec.ok else None,
        error_code=rec.error_code or None,
        error_message=rec.error_message or None,
        http_status=rec.http_status, request_id=rec.request_id,
        evidence=rec.path, detail=dict(detail))


def delete_probe_guardrails(client, store, lim,
                            probes: Sequence[ProbeGuardrail]) -> list[dict[str, Any]]:
    """Delete every probe that created something. Report per id, never as a bool.

    A single boolean would say "teardown failed" without saying which resource survived,
    and the difference between that and naming the id is the difference between a
    one-minute fix and sweeping an account that carries ~$27k/mo of unrelated resources.

    Every probe is attempted even if an earlier delete raised: stopping at the first
    failure would leave the rest behind for a reason unrelated to them.
    """
    out: list[dict[str, Any]] = []
    for p in probes:
        if not p.guardrail_id:
            continue
        lim.wait("DeleteGuardrail")
        rec = capture(store, "delete_guardrail", client,
                      guardrailIdentifier=p.guardrail_id)
        out.append({"label": p.label, "name": p.name, "guardrail_id": p.guardrail_id,
                    "deleted": rec.ok, "error_code": rec.error_code or None,
                    "request_id": rec.request_id})
    return out


def probe_residue(probes: Sequence[ProbeGuardrail],
                  deletions: Sequence[dict]) -> dict[str, Any]:
    """What this case left behind, computed from both lists rather than from the deletions.

    Deriving `n_created` from `deletions` would be circular: a probe that created a
    guardrail and whose delete was never *attempted* (the loop died, the process was
    killed between the create and the finally) contributes no row to `deletions` at all,
    so a residue computed from that list alone would report zero survivors for exactly the
    case where a survivor exists. The two lists are compared instead.
    """
    created = [p.guardrail_id for p in probes if p.guardrail_id]
    attempted = {d["guardrail_id"] for d in deletions}
    deleted = {d["guardrail_id"] for d in deletions if d["deleted"]}
    surviving = [g for g in created if g not in deleted]
    return {
        "n_created": len(created),
        "n_delete_attempted": len(attempted),
        "n_deleted": len(deleted),
        "surviving": surviving,
        "never_attempted": [g for g in created if g not in attempted],
        "clean": not surviving,
        "why_two_lists": ("a probe whose delete was never ATTEMPTED contributes no row to "
                          "`deletions`, so a residue computed from that list alone would "
                          "report zero survivors for exactly the case where one exists"),
    }


# ---------------------------------------------------------------------------
# hit readers, one per policy block
# ---------------------------------------------------------------------------
#
# `ArmSpec.hit` defaults to `asm.detected(item["label"])`, which reads
# `contentPolicy.filters[].type` — the CONTENT-FILTER block and nothing else. That
# default is right for F3-1/F3-8 and silently wrong for every other policy: a PII arm
# using it would score `EMAIL` against the content-filter type list, find nothing, and
# report recall 0/341 for a working filter. The failure is silent because the response
# is a success and the label is a legitimate string — there is no error to raise.
#
# So each policy block gets a named reader, and a case script picks the one matching the
# guardrail it configured. They are here rather than in `arms.py` because `arms.py` is
# about sending a request and reading the response; which field answers a given oracle is
# a per-case decision.

def hit_pii(item: dict, asm: R.Assessment) -> bool:
    """Did the PII policy detect *this item's own entity type*?

    The item's label, not "any entity". F3-4's oracle is per entity type, so an item
    carrying an EMAIL that the service reported as a NAME is a miss for EMAIL — which is
    the distinction the per-entity table exists to make. `any_detection` is reported
    beside it in the payload so the laxer reading stays visible.
    """
    return item.get("label", "") in asm.pii_detected


def hit_topic(topic: str) -> Callable[[dict, R.Assessment], bool]:
    """Did the denied-topic policy fire for the named topic?

    Parameterised by the topic name rather than reading the item's label, because both
    arms of F3-5 (in-topic and off-topic) are scored against the SAME topic: the
    off-topic arm's items are labelled `TOPIC_OFF`, and a reader keyed on the label
    would look for a topic called TOPIC_OFF, never find it, and report an FPR of exactly
    zero for any configuration whatsoever — including one with no topic policy at all.
    """
    def _hit(_item: dict, asm: R.Assessment) -> bool:
        return topic in asm.topics_detected
    return _hit


def hit_prompt_attack(_item: dict, asm: R.Assessment) -> bool:
    """Did the single PROMPT_ATTACK content filter fire?

    Not the item's label. `contentPolicyConfig` has ONE `PROMPT_ATTACK` filter type;
    JAILBREAK / PROMPT_INJECTION / PROMPT_LEAKAGE are subtypes of our *corpus*, not of the
    API's response — they appear as separate categories only under
    `InvokeGuardrailChecks.promptAttack`. The default label reader would look for a
    content-filter type called `JAILBREAK`, never find it, and report recall 0/360 for a
    filter that fired on every item.

    So F3-8 on ApplyGuardrail is answerable as "did PROMPT_ATTACK fire on an item of this
    subtype", with the subtype supplied by our label. The scripts say so, because the
    reader alone cannot: the per-subtype table is a property of our stratification and
    the service reports one bit.
    """
    return asm.detected("PROMPT_ATTACK")


def hit_word(_item: dict, asm: R.Assessment) -> bool:
    """Did the word policy match anything at all?

    Any match, not the item's own slot. F3-6's adverse events are "a listed term did not
    block" and "an unlisted near-miss did block", and the second is only observable as
    *some* word matching — a near-miss item that blocked would, by definition, not match
    a listed term. Restricting to the slot would score every near-miss block as a clean
    non-detection, i.e. would discard exactly the half of the corpus that makes "exact
    match" falsifiable.
    """
    return bool(asm.words_detected)


def hit_grounding(kind: str = "GROUNDING") -> Callable[[dict, R.Assessment], bool]:
    """Did the named contextual-grounding filter fire?

    Defaults to GROUNDING, and the guardrail also configures RELEVANCE. They are read
    separately because they answer different questions: GROUNDING scores the response
    against the source, RELEVANCE scores it against the query. F3-7's oracle is about
    grounding, and a corpus whose ungrounded items were also off-topic would let a
    RELEVANCE block be counted as grounding detection — so the reader names the filter
    and the payload reports both rates.
    """
    def _hit(_item: dict, asm: R.Assessment) -> bool:
        return any(g["detected"] for g in asm.grounding if g.get("type") == kind)
    return _hit


# ---------------------------------------------------------------------------
# Observation builders, one per oracle shape
# ---------------------------------------------------------------------------

def _counts(tallies: Iterable[dict]) -> tuple[int, int, int, list[str]]:
    """Pool x / n_usable / n_attempted / failure codes over one or more arms."""
    x = n_u = n_a = 0
    codes: set[str] = set()
    for t in tallies:
        x += int(t["x"])
        n_u += int(t["n_usable"])
        n_a += int(t["n_attempted"])
        codes.update(t.get("failure_codes") or [])
    return x, n_u, n_a, sorted(c for c in codes if c)


def obs_proportion(case_id: str, tallies: Sequence[dict], **detail: Any) -> O.Observation:
    """LOWER_ABOVE / UPPER_BELOW / ASYMMETRIC_FPR: x adverse-or-detected out of n.

    All three kinds read `adverse`, and which direction the threshold is compared in is
    the *kind's* business, not the caller's. That is deliberate: F3-2 counts false
    positives and F3-1 counts true positives, and both land in the same field. Naming
    the field `adverse` for a recall arm reads oddly, and the alternative — a per-case
    field name — would let a script decide the direction of its own oracle.
    """
    x, n_u, n_a, codes = _counts(tallies)
    return O.Observation(case_id=case_id, n_attempted=n_a, n_usable=n_u, adverse=x,
                         detail={"failure_codes": codes, "x": x, **detail})


def obs_existence(case_id: str, observed: bool, *, n: int,
                  **detail: Any) -> O.Observation:
    """EXISTENCE: TRUE iff `observed`, over `n` trials.

    `n` is REQUIRED and keyword-only, and it did not used to exist at all. That omission
    published a false shortfall.

    `Observation.n_usable` and `n_attempted` default to 0, and `evaluate` computes
    `n_met = (planned_n is None) or (n_usable >= planned_n)`. Of the 46 EXISTENCE cases,
    exactly one — F8-6 — carries a sealed `planned_n` (60); the other 45 are None, for
    which the default is harmless because there is nothing to fall short of. So F8-6's live
    run collected 60 usable trials, its own arm printed `xregion: 60/60  -> x=60
    n_usable=60`, and the record it published said `n_usable: 0, n_met: false` with the
    note "n_usable=0 is below the pre-registered 60 … does not clear the amendment bar".
    Every number in that sentence was produced correctly from a count that no caller had
    ever supplied — the shortfall was manufactured by the builder, not measured
    (feedback_label_must_match_computation: the label has to match the computation, and
    here the computation had no input).

    This is the same shape as DEV-P1-4's finding — a case's sealed KIND does not predict
    whether the seal gives it an n — so a builder may not assume its kind is n-less. `n`
    is therefore passed explicitly, exactly as `obs_zero_events` already does and for the
    same stated reason: an EXISTENCE verdict is a conjunction over cells, so the count is
    not derivable from a tally the builder can see. It is required rather than defaulted
    to 0 because a default is what caused this: a keyword with no default makes every one
    of the five call sites state its own denominator, and makes a sixth call site fail at
    the point of writing rather than at the point of publishing.

    What `n` means here is the number of trials the conjunction was evaluated over — the
    denominator a reader would check the sealed n against. For F8-6 that is the number of
    ApplyGuardrail trials; for F8-8, which reads a shipped service model and makes no call
    at all, it is 0, and 0 passed deliberately is a different fact from 0 defaulted.
    """
    if n < 0:
        raise ValueError(f"{case_id}: n={n} is negative; a trial count cannot be")
    return O.Observation(case_id=case_id, observed_bool=bool(observed),
                         n_attempted=int(n), n_usable=int(n), detail=dict(detail))


def obs_zero_events(case_id: str, adverse: int, n: int, **detail: Any) -> O.Observation:
    """ZERO_EVENTS: TRUE iff `adverse` is 0, with a ceiling reported either way.

    `n` is passed explicitly rather than derived from a tally because F3-6's adverse
    events come from two different populations — a listed term that failed to block and
    an unlisted near-miss that blocked — and their union is the trial count the ceiling
    is denominated in. A tally would supply the count of one of them.
    """
    return O.Observation(case_id=case_id, n_attempted=n, n_usable=n, adverse=int(adverse),
                         detail=dict(detail))


def obs_intervals(case_id: str, *, detect_x: int, detect_n: int,
                  fpr_x: int, fpr_n: int, **detail: Any) -> O.Observation:
    """DISJOINT_INTERVALS and INDISTINGUISHABLE: two rates, compared as intervals.

    Keyword-only, and that is the whole point of the function. The four integers are
    interchangeable positionally and swapping the pairs inverts the verdict of every
    case that uses this shape — F3-5, F3-7, F5-5 (disjointness confirms) and F8-2
    (overlap confirms). A positional call site would be one transposition away from a
    published result that reads correctly and says the opposite.
    """
    return O.Observation(case_id=case_id,
                         n_attempted=detect_n + fpr_n, n_usable=detect_n + fpr_n,
                         detect_x=int(detect_x), detect_n=int(detect_n),
                         fpr_x=int(fpr_x), fpr_n=int(fpr_n), detail=dict(detail))


def obs_boundary(case_id: str, *, at_limit_ok: bool, over_limit_rejected: bool,
                 **detail: Any) -> O.Observation:
    return O.Observation(case_id=case_id, at_limit_ok=bool(at_limit_ok),
                         over_limit_rejected=bool(over_limit_rejected),
                         detail=dict(detail))


def obs_distinct(case_id: str, values: Sequence[float], n: int,
                 **detail: Any) -> O.Observation:
    return O.Observation(case_id=case_id, n_attempted=n, n_usable=n,
                         distinct_values=list(values), detail=dict(detail))


def obs_paired(case_id: str, *, improved: bool, p_value: float, n: int,
               **detail: Any) -> O.Observation:
    return O.Observation(case_id=case_id, n_attempted=n, n_usable=n,
                         improved=bool(improved), p_value=float(p_value),
                         detail=dict(detail))


def obs_roc(case_id: str, *, operating_points: int, argmax_j_interior: bool,
            n: int, **detail: Any) -> O.Observation:
    return O.Observation(case_id=case_id, n_attempted=n, n_usable=n,
                         operating_points=int(operating_points),
                         argmax_j_interior=bool(argmax_j_interior),
                         detail=dict(detail))


def obs_recorded(case_id: str, **detail: Any) -> O.Observation:
    """RECORDED: the pre-registration declares the outcome unknown; both are findings."""
    return O.Observation(case_id=case_id, detail=dict(detail))


# ---------------------------------------------------------------------------
# per-stratum roll-up (F3-4 per entity, F3-8 per subtype)
# ---------------------------------------------------------------------------

def per_stratum(case_id: str, strata: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Evaluate a per-stratum oracle stratum by stratum, plus the roll-up rule.

    F3-4 ("FALSE for ANY entity whose CI upper bound is below 0.5") and F3-8 ("FALSE for
    any subtype whose UPPER bound is below 0.5") are both universally quantified over
    strata, so the case's verdict is not a function of the pooled rate — a pooled recall
    of 0.9 is compatible with one entity at 0.0, and pooling is what would hide it.

    The roll-up is stated rather than inferred:
      * any stratum FALSE  -> the case is FALSE (one counterexample decides a "for any")
      * else all TRUE      -> TRUE
      * else               -> INCONCLUSIVE (some stratum's interval straddles)
    """
    per: dict[str, dict] = {}
    for name, c in sorted(strata.items()):
        o = obs_proportion(case_id, [{"x": c["x"], "n_usable": c["n"],
                                      "n_attempted": c.get("n_attempted", c["n"]),
                                      "failure_codes": c.get("failure_codes", [])}],
                           stratum=name)
        per[name] = O.evaluate(o)
    verdicts = [r["verdict"] for r in per.values()]
    if O.FALSE in verdicts:
        roll = O.FALSE
    elif verdicts and all(v == O.TRUE for v in verdicts):
        roll = O.TRUE
    else:
        roll = O.INCONCLUSIVE
    return {
        "per_stratum": per,
        "rollup_verdict": roll,
        "rollup_rule": ("the sealed oracle is universally quantified over strata, so one "
                        "FALSE stratum decides the case and the pooled rate is reported "
                        "as a description only — a pooled 0.9 is compatible with one "
                        "stratum at 0.0"),
        "n_strata": len(per),
        "false_strata": [k for k, v in per.items() if v["verdict"] == O.FALSE],
        "inconclusive_strata": [k for k, v in per.items()
                                if v["verdict"] == O.INCONCLUSIVE],
    }


def apply_rollup_n_met(rec: dict, roll: dict, *, unit: str) -> dict:
    """Replace a roll-up case's `n_met` with the per-stratum AND, and say so *in the record*.

    F3-4 and F3-8 both have a sealed n that is **per stratum** (11 per PII entity, 120 per
    prompt-attack subtype), so the case-level `n_met` that `oracle.evaluate` computes —
    `n_usable >= planned_n` against the pooled counts — answers the wrong question. Both
    scripts already overrode it. What they did not do was tell the rest of the record.

    That produced a published sentence that was self-contradictory. `amendment_blockers`
    composes its text from `rec["n_usable"]` and `rec["planned_n"]`, so F3-4's blocker read

        "n_usable=93 is below the pre-registered 11"

    — every number in it correct, the sentence it forms false. 93 pooled observations were
    collected and the per-entity n of 11 was genuinely unmet in some strata; the blocker had
    joined a pooled numerator to a per-stratum denominator. This is
    `feedback_label_must_match_computation` exactly: a figure labelled with a computation
    that did not produce it. It is also not merely cosmetic — the shortfall is real, so a
    reader who checks the arithmetic and finds it nonsense may dismiss a true blocker.

    So the override records `n_met_basis` (the sentence a reader should see) and
    `n_met_strata_short` (which strata are actually short), and `oracle.amendment_blockers`
    prefers that basis over re-deriving one from the case-level counts.

    `evaluate`'s own shortfall note is **removed**, not merely supplemented: it was written
    against the pooled `n_met` this function is replacing, so leaving it in would put two
    incompatible statements about the same field in one record and let a reader pick.
    """
    per = roll["per_stratum"]
    short = sorted(k for k, v in per.items() if not v["n_met"])
    out = dict(rec)
    out["n_met"] = not short
    out["n_met_strata_short"] = short
    out["notes"] = [n for n in (rec.get("notes") or [])
                    if "is below the pre-registered" not in n]
    want = per[next(iter(per))]["planned_n"] if per else None
    if short:
        out["n_met_basis"] = (
            f"n_met is the AND over {len(per)} strata, because the sealed n={want} is per "
            f"{unit}, not per case: {len(short)} stratum/strata are short "
            f"({', '.join(f'{k} n={per[k]['n_usable']}' for k in short[:6])}"
            f"{', ...' if len(short) > 6 else ''}). The case-level n_usable="
            f"{rec.get('n_usable')} is a POOLED count over all strata and must not be "
            f"compared against a per-{unit} n")
    else:
        out["n_met_basis"] = (
            f"n_met is the AND over {len(per)} strata and every stratum reached the sealed "
            f"per-{unit} n of {want}")
    return out


# ---------------------------------------------------------------------------
# ROC over the strength lattice
# ---------------------------------------------------------------------------

def trapezoid_auc(points: Sequence[tuple[float, float]]) -> float:
    """Trapezoidal AUC over ROC vertices, with the trivial endpoints closed in.

    It lives here rather than in `lib/stats.py` for a reason worth recording: `stats.py`
    is a **bound artifact** of the sealed pre-registration (`meta.bound_artifacts`, with
    a pinned sha256 that `verify_prereg.check_artifact_hashes` treats as fatal in strict
    mode). Adding a function to it after the seal breaks that hash and would require a
    re-stamp of the analysis layer — a much larger claim than "F3-9 needs a secondary
    descriptor". The seal is doing exactly its job by making that expensive.

    Downward-biased on a coarse lattice, and pre-registered as a secondary descriptor
    only for that reason. The bias has a direction, which is why it is reportable rather
    than merely imprecise: the trapezoid rule interpolates linearly between adjacent
    vertices, and with four `inputStrength` settings the gap between vertices can span
    much of the FPR axis. A concave ROC lies above every chord, so this is a LOWER bound
    on AUC, not a two-sided approximation.

    (0,0) and (1,1) are closed in because they are reachable by construction — classify
    nothing, classify everything. Omitting them truncates the integral over the
    unmeasured ends by a different amount for each arm, which would make arms
    incomparable; `roc_points` reports `endpoints_added` so the closure is visible rather
    than implicit.
    """
    pts = sorted({(float(f), float(t)) for f, t in points} | {(0.0, 0.0), (1.0, 1.0)})
    area = 0.0
    for (f0, t0), (f1, t1) in zip(pts, pts[1:]):
        area += (f1 - f0) * (t0 + t1) / 2.0
    return area


def roc_points(by_strength: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Build the operating-point set F3-9's oracle counts, plus Youden's J.

    The lattice has **three** buildable settings (LOW/MEDIUM/HIGH), not six and not the
    four the `inputStrength` enum contains. The enum's fourth value, NONE, is real but
    unusable in isolation: `CreateGuardrail` refuses a contentPolicyConfig whose filters are
    all NONE, and refuses it just as firmly when they are all disabled
    (`UNREACHABLE_STRENGTHS`). So the leftmost non-trivial vertex of this ROC — "configured
    and classifying nothing" — is not a point we chose to skip, it is a point the service
    forbids.

    With three configurable points plus the two trivial endpoints (0,0) and (1,1) the
    reachable count is at most **5**, under the oracle's ceiling of 7 — so F3-9 cannot fail
    the count for a reason unrelated to the guardrail, and the reason it cannot is a
    property of the API. Reported rather than smoothed: `lattice_size`, `endpoints_added`
    and `unreachable_strengths` are all in the output, so a reader can see that the polyline
    has three measured vertices *because of a validation rule* and not because of n.

    "Interior" means the argmax of J does not land on a trivial endpoint — tested against
    the coordinates (0,0) and (1,1), never against position in the lattice. See the comment
    at the `interior` assignment for why that distinction became load-bearing when NONE left
    the tuple.
    """
    pts: list[dict] = []
    for s in STRENGTHS:
        c = by_strength.get(s)
        if not c:
            continue
        tpr = c["tp"] / c["pos"] if c["pos"] else 0.0
        fpr = c["fp"] / c["neg"] if c["neg"] else 0.0
        pts.append({"strength": s, "tpr": tpr, "fpr": fpr, "j": tpr - fpr,
                    "tp": c["tp"], "pos": c["pos"], "fp": c["fp"], "neg": c["neg"],
                    "ppv_at_prevalence": {str(pi): S.ppv_at_prevalence(tpr, fpr, pi)
                                          for pi in (0.001, 0.01, 0.1)}})
    # Distinct (FPR, TPR) pairs, because two strengths that behave identically are ONE
    # operating point. Counting configurations instead of points is how a 4-setting
    # lattice would be reported as 4 points when the service collapsed two of them.
    distinct = sorted({(round(p["fpr"], 6), round(p["tpr"], 6)) for p in pts})
    with_ends = sorted(set(distinct) | {(0.0, 0.0), (1.0, 1.0)})
    best = max(pts, key=lambda p: p["j"]) if pts else None
    # "Interior" is defined against the TRIVIAL endpoints (0,0) and (1,1), never against
    # position in the lattice. This used to exclude `STRENGTHS[0]`, which was NONE — a
    # setting that classifies nothing and therefore genuinely sits at (0,0). With NONE
    # unbuildable (see UNREACHABLE_STRENGTHS) STRENGTHS[0] is LOW, a real operating point,
    # and excluding it would have made an argmax at LOW report as non-interior: the oracle
    # would fail on a perfectly usable result, and the failure would look like a finding.
    # A measured point is trivial only if it lands ON an endpoint, which is what is tested.
    interior = bool(best
                    and not (best["tpr"] <= 0.0 and best["fpr"] <= 0.0)
                    and not (best["tpr"] >= 1.0 and best["fpr"] >= 1.0)
                    and best["j"] > 0.0)
    return {
        "points": pts,
        "distinct_measured_points": len(distinct),
        "operating_points_with_trivial_endpoints": len(with_ends),
        "lattice_size": len(STRENGTHS),
        "endpoints_added": len(with_ends) - len(distinct),
        "max_reachable_given_lattice": len(STRENGTHS) + 2,
        "unreachable_strengths": dict(UNREACHABLE_STRENGTHS),
        "youden_j_argmax": best["strength"] if best else None,
        "youden_j_max": best["j"] if best else None,
        "argmax_is_interior": interior,
        "auc_trapezoid": trapezoid_auc([(p["fpr"], p["tpr"]) for p in pts])
        if len(pts) >= 2 else None,
        "auc_caveat": (f"trapezoidal AUC over {len(pts)} measured point(s) is "
                       f"downward-biased and is a secondary descriptor only, per the "
                       f"pre-registration; the bias is larger here than the design "
                       f"anticipated because the NONE vertex is unbuildable"),
    }


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def emit(case_id: str, record: dict, payload: dict, store: EvidenceStore | None = None,
         *, quiet: bool = False) -> Path:
    """Write one case's analysis to `results/phase1/<case>.json` and to the evidence dir.

    Two copies, deliberately. The evidence directory is the per-run archive keyed by run
    id; `results/phase1/` is the latest-per-case index the analysis phase reads. Writing
    only the first would make the analysis phase enumerate run directories and guess
    which run was authoritative.
    """
    body = {"case_id": case_id,
            "oracle_text": O.oracle_text(case_id),
            "kind": O.BINDINGS[case_id].kind,
            "planned_n": O.planned_n(case_id),
            "verdict": record["verdict"],
            "record": record,
            "blockers": O.amendment_blockers(record),
            **payload}
    text = json.dumps(body, indent=2, sort_keys=True, default=str,
                      ensure_ascii=False) + "\n"
    PHASE1_OUT.mkdir(parents=True, exist_ok=True)
    out = PHASE1_OUT / f"{case_id}.json"
    # `results/` is distributable, so ARN account fields are masked there. The evidence
    # copy below is NOT masked: it is the local archive whose purpose is that a request id
    # and a full ARN can be quoted to AWS Support (lib/redact.py, DEVIATIONS.md/DEV-P1-13).
    out.write_text(_redact.mask_text(text), encoding="utf-8")
    if store is not None:
        (store.dir / "analysis.json").write_text(text, encoding="utf-8")
        store.write_summary({"analysis_file": "analysis.json", "case_id": case_id,
                             "verdict": record["verdict"]})
    if not quiet:
        print(f"\n  verdict: {record['verdict']}   ({O.BINDINGS[case_id].kind})")
        for note in record.get("notes") or []:
            print(f"    note: {note}")
        print(f"  wrote {out.relative_to(ROOT)}")
    return out


# ---------------------------------------------------------------------------
# the standard case front-end
# ---------------------------------------------------------------------------

def parser(case_id: str, doc: str) -> argparse.ArgumentParser:
    """The argument surface every Phase 1 case shares.

    `--dry-run` and `--n` are on every script by the plan's own rule (no script's first
    execution is on the expensive path). `--n` is a *prefix*, not a sample: see
    `arms.load_corpus`. A run under `--n` writes `is_smoke` into the checkpoint metadata
    so a smoke result can never be mistaken for the pre-registered arm.
    """
    ap = argparse.ArgumentParser(
        prog=f"{case_id}", description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and the oracle; make no AWS call")
    ap.add_argument("--n", type=int, default=None,
                    help="use only the first N items of each corpus (smoke run)")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--region", default=A.MAIN_REGION)
    return ap


def dry_run_banner(case_id: str, arms_planned: Sequence[tuple[str, str, int]],
                   *, extra: Sequence[str] = (), blocks_per_call: int = 1,
                   operations: Mapping[str, int] | None = None,
                   mutations: int = 0, billable: bool = True,
                   text_units: int | None = None, text_units_why: str = "") -> int:
    """Print what would run, the sealed oracle, and the pre-registered n. Returns 0.

    The oracle text is printed because a dry run is the last moment before the money is
    spent at which the question can be compared with the instrument. Printing the plan
    without it would show what the script does and not what it is for.

    `operations`, `mutations` and `billable` exist because the first version of this
    function hard-coded all three: it labelled every total "ApplyGuardrail calls",
    printed "mutations: 0" unconditionally, and always projected text units. That was
    true of the six F3 cases and of F8-2/F8-3, and false as soon as a case sent something
    else — F8-4 sends 230 `InvokeGuardrailChecks` among its 690 calls, and F8-5 sends four
    `CreateGuardrail` calls, no `ApplyGuardrail` at all, and creates resources. A label
    naming one operation over a total spanning two is exactly the defect this project
    exists to find (`feedback_label_must_match_computation`), and F8-4 first shipped a
    hand-written CORRECTION line under the wrong banner because the banner could not say
    it. Fixing it here rather than per script means the next case inherits the fix.

    The breakdown is **checked, not trusted**: if `operations`' counts do not sum to the
    arm total this raises. A breakdown that disagreed with the plan would be a second
    label over the same computation, which is the thing being fixed.

    `text_units` overrides the `total * blocks_per_call` estimate, and needs
    `text_units_why` to say where the number came from. The default estimate assumes one
    text unit per block, which holds for every case whose items are short — but a text
    unit is <= 1000 CHARACTERS, not one block (cost_model.yaml:47), so F10-2, whose whole
    design is a length sweep with items deliberately spanning the 1000-character step,
    would have its dominant cost term understated by the default. A projection that is
    wrong by construction on the one case that measures the quantity being projected is
    not a projection.
    """
    b = O.BINDINGS[case_id]
    want = O.planned_n(case_id)
    print(f"{case_id} dry run — no AWS call, no mutation\n")
    print(f"oracle ({b.kind}): {O.oracle_text(case_id)}\n")
    print(f"pre-registered n: {want if want is not None else 'none (see DEVIATIONS)'}"
          f"   alpha: {O.alpha_for(case_id)}"
          f"   thresholds: {b.thresholds or '(none — kind is not thresholded)'}")
    if b.limits_by_reference:
        print(f"limits by REFERENCE: {b.limits_by_reference}")
    if b.note:
        print(f"note: {b.note}")
    print(f"\narms ({len(arms_planned)}):")
    total = 0
    for label, corpus, n in arms_planned:
        print(f"  {label:22s} {corpus:38s} n={n}")
        total += n
    # Text units, not calls, are what guardrail spend is denominated in — and a
    # multi-block request sends more than one block per call. F3-7 sends three (source,
    # query, response), so a projection that equated the two would understate its cost by
    # 3x. `blocks_per_call` is the block count each trial of this case sends; the arms are
    # uniform within a case, and a case whose arms differed would have to say so here.
    units = total * blocks_per_call
    if text_units is not None:
        if not text_units_why:
            raise ValueError(
                f"{case_id}: an overridden text-unit projection needs `text_units_why`. "
                f"A number that replaces a derived one without saying how it was derived "
                f"is the unverified-prose defect this project screens for")
        units = int(text_units)
    if operations is None:
        operations = {"ApplyGuardrail": total}
    got = sum(operations.values())
    if got != total:
        raise ValueError(
            f"{case_id}: the operation breakdown sums to {got} but the arm plan totals "
            f"{total}. A breakdown that disagrees with the plan is a second label over "
            f"the same computation — which is the defect this argument exists to prevent")
    ops = "  ".join(f"{op} x{n}" for op, n in sorted(operations.items()))
    print(f"\ntotal calls: {total}   ({ops})")
    if billable:
        print(f"content blocks per call: {blocks_per_call}"
              f"   billable text-unit sources: ~{units}")
        if text_units is not None:
            print(f"  text-unit basis: {text_units_why}")
    else:
        print("billable text units: 0 — this case sends no ApplyGuardrail and no "
              "InvokeGuardrailChecks; control-plane calls bill no text units")
    print(f"mutations: {mutations}"
          + ("" if mutations else "   (no resource is created, changed or deleted)"))
    for line in extra:
        print(line)
    return 0


def run_arms(specs: Sequence[R.ArmSpec], corpora: Sequence[Sequence[dict]], *,
             run_id: str, is_smoke: bool,
             factory: A.ClientFactory | None = None,
             progress: bool = True) -> list[dict]:
    """Run several arms in order, printing one progress line per arm.

    Sequential, not concurrent. The rate limiter in `lib/awsclients.py` spaces calls
    below the documented 100 rps ApplyGuardrail ceiling, and concurrency would put the
    arms into contention for that budget — which for F2-5 (300 identical calls, looking
    for any variation at all) would introduce load as an alternative explanation for
    exactly the variation the case is trying to attribute to the service.
    """
    out = []
    for spec, items in zip(specs, corpora):
        label = spec.label or "main"
        print(f"  arm {label:20s} {len(items):>5d} items  {spec.corpus}")

        def tick(done: int, total: int, _l=label) -> None:
            if progress and (done % 50 == 0 or done == total):
                print(f"    {_l}: {done}/{total}", flush=True)

        t = R.run_arm(spec, items, run_id=run_id, is_smoke=is_smoke,
                      factory=factory, progress=tick if progress else None)
        print(f"    -> x={t['x']} n_usable={t['n_usable']}"
              + (f"  FAILED={t['n_failed']} {t['failure_codes']}"
                 if t["n_failed"] else ""))
        out.append(t)
    return out


def resolve_run(args: argparse.Namespace) -> str:
    return args.run_id or new_run_id()


def label_counts(rows: Iterable[dict], labels: Sequence[str]) -> dict[str, dict[str, int]]:
    """Per-label x/n over arm rows, restricted to `labels` and reporting each of them.

    Restricted *and* complete: a label in `labels` with no rows appears with n=0 rather
    than being absent. A per-subtype oracle over three subtypes that silently evaluated
    two would roll up to a verdict over a smaller quantifier than the sealed text names.
    """
    per = R.per_label_tally(rows)
    return {k: {"x": per.get(k, {}).get("x", 0), "n": per.get(k, {}).get("n", 0)}
            for k in labels}


# A full run must complete this fraction of its attempted trials, per arm and pooled.
#
# 0.90 rather than 1.00: a handful of throttles is a normal cost of a 2,190-call arm and
# aborting on one would make every long run hostage to a single hiccup — the interval simply
# widens, and `n_met` already reports the shortfall against the sealed n. Rather than 0.50 or
# "some": the number has to be far enough above the pre-registered power floor that a run
# passing it is still the run that was designed. At 0.90 an 87-item cell keeps >= 79, which
# holds the rule-of-three bound near where the seal put it.
#
# Deliberately NOT applied to `--n` smoke runs: a 3-item arm losing one trial is 0.67 and the
# smoke path's job is to prove the plumbing works, not to estimate a rate. Its results are
# never reported (`is_smoke` travels in the checkpoint metadata for that reason).
MIN_COMPLETION = 0.90


def require_measured(tallies: Sequence[dict], *, is_smoke: bool = False,
                     min_completion: float = MIN_COMPLETION) -> int:
    """Exit code for the "did the test run" question — and did it run *enough*.

    Split from the verdict on purpose: a case whose verdict refutes the document has
    succeeded, and a case that measured nothing has not. Collapsing the two would make a
    CI-style green/red signal report "the document was right" as success.

    WHY THERE ARE NOW TWO CHECKS AND NOT ONE
    ----------------------------------------
    `n_u <= 0` was the whole gate, and it is far too weak — it only catches the case where
    *nothing at all* survived. On 2026-08-10 an ~80 s local network outage killed 3,378 of
    3,464 Phase 1 trials. Every arm still held the 2-3 trials it had completed before the
    outage, so `n_u > 0` held, and all six F3 scripts exited **rc=0** and wrote verdicts:
    F3-1 published TRUE from **15 usable trials against a pre-registered 87**, and F3-2/F3-3
    reached INCONCLUSIVE from 3 (DEV-P1-11).

    Nothing lied. `n_usable=15`, `n_met=False` and `failure_codes` were all recorded
    faithfully, and the emitted note even said the interval was wider than the design
    promised. That is precisely the problem: **a shortfall reported beside a verdict is a
    verdict**, and rc=0 is the signal a batch driver reads. The pre-registered n is a
    precision commitment, so a run that silently keeps 3% of it has not produced a
    measurement with a wide interval — it has failed, and it must say so in its exit code.

    Per-arm, NOT pooled, because pooling hides the shape: eleven healthy arms and one empty
    one pool to 92% while the empty arm is a stratum some oracle divides by. That is the
    same defect as `n_usable` being the sum of two denominators in `oracle._decide` — a
    total cannot see an empty part.

    The first version of this gate checked `bad or pooled < min_completion`, and the pooled
    half was **unreachable**. With `f_i = u_i / a_i` and weights `a_i`,

        pooled = Σu_i / Σa_i = Σ(a_i · f_i) / Σa_i

    is a weighted mean of the per-arm fractions, and a weighted mean of numbers all `>= t`
    is itself `>= t`. So `all(f_i >= t) ⇒ pooled >= t`: the pooled condition could only
    fire in cases the per-arm loop had already caught. A guard that cannot fail reads as
    protection while providing none (`feedback_vacuous_test_check`), so it is gone as a
    *gate* and the pooled figure stays in the message as reporting. `test_require_measured`
    pins the implication, so weakening the per-arm loop — skipping small arms, say — fails
    there and says the pooled guard has to come back.
    """
    _x, n_u, n_a, codes = _counts(tallies)
    if n_u <= 0:
        print(f"FATAL: zero usable trials across {len(tallies)} arm(s); nothing was "
              f"measured. failure codes: {codes or '(none recorded)'}", file=sys.stderr)
        return 2
    if is_smoke:
        return 0

    bad = []
    for t in tallies:
        att = int(t["n_attempted"])
        if att <= 0:
            continue
        frac = int(t["n_usable"]) / att
        if frac < min_completion:
            bad.append((t.get("arm") or "main", int(t["n_usable"]), att, frac,
                        t.get("failure_codes") or []))
    # Reported, not tested: see the docstring's derivation. Kept in the message because a
    # reader triaging the refusal wants the run-level size next to the offending arms.
    pooled = n_u / n_a if n_a else 0.0
    if bad:
        print(f"FATAL: completion below {min_completion:.0%} — this run did not collect the "
              f"data it was designed to collect, so its verdicts would rest on a sample no "
              f"pre-registration authorised.", file=sys.stderr)
        print(f"  pooled {n_u}/{n_a} = {pooled:.1%}   failure codes: "
              f"{codes or '(none recorded)'}", file=sys.stderr)
        for arm, u, att, frac, fc in bad:
            print(f"  arm {arm:24s} {u:5d}/{att:<5d} = {frac:5.1%}  {fc}", file=sys.stderr)
        print("  the checkpoint is intact: re-running the SAME --run-id resumes only the "
              "missing trials (lib/checkpoint.run_trial keys on the item's content hash), "
              "so nothing already collected is re-sent or re-billed.", file=sys.stderr)
        return 2
    return 0
