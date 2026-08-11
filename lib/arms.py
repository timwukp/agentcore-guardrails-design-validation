#!/usr/bin/env python3
"""The Phase 1 arm runner: a corpus, a guardrail, and one row per item.

Phase 1 is the cheap half of the project — `ApplyGuardrail` and
`InvokeGuardrailChecks` only, no gateway, no policy engine, no model inference.
Seventeen cases (F3-1..9, F8-2..8, F2-5, F10-2) are all the same shape: send each
item of a labelled corpus to a guardrail and record what came back. That shape
lives here once, so a per-case script is a corpus, a config and an oracle rather
than a fresh loop over boto3.

Three decisions in here are load-bearing, and each was made against the 1.43.67
service model rather than from recollection of the docs.

1. `outputScope="FULL"`, always
------------------------------
The parameter defaults to `INTERVENTIONS`, which returns assessments **only for
the policies that intervened**. Under that default a benign item comes back with
`action="NONE"` and an empty `assessments` list — and "the filter evaluated this
and found nothing" is then indistinguishable from "the filter never ran". Every
false-positive rate in this project (F3-2, F3-3) is measured on exactly those
items, so the default would make the FPR cells unmeasurable while appearing to
work. `FULL` returns the assessment either way.

This costs nothing: `usage` (the text-unit count that F10-2 reads and that
billing is denominated in) is identical under both scopes, because scope controls
what is *reported*, not what is *evaluated*.

2. `detected` and `action` are recorded separately, and neither is renamed "blocked"
-----------------------------------------------------------------------------------
The response carries both `filters[].detected` (the classifier fired) and
`filters[].action ∈ {BLOCKED, NONE}` (the configured response). They come apart
whenever `inputAction=NONE` is set — which is exactly the LOG_ONLY-shaped
configuration §7.1 tells readers to use for shadow evaluation. Collapsing them
into one boolean would silently answer a different question than the oracle asks:
F3-1 is about detection, F4 is about enforcement. Both are recorded per item, and
`detected_and_blocked` is derived rather than assumed.

3. A failure is not a data point
--------------------------------
A `ThrottlingException` or a timeout is recorded in the checkpoint's failure map
and excluded from the denominator. `n_attempted` and `n_usable` are both reported
and the Wilson interval is built on `n_usable` (`lib/oracle.py`), because counting
an item that never reached the service as a non-detection would bias every recall
downward by the throttle rate — i.e. would make the harness's own reliability look
like a property of the guardrail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import awsclients as A
from checkpoint import Checkpoint
from evidence import EvidenceStore, capture

ROOT = Path(__file__).resolve().parent.parent
CORPORA = ROOT / "corpora"


class PolicyNotEvaluated(RuntimeError):
    """The service answered 200, but the policy this arm measures never ran.

    Carries `error_code` so `checkpoint.error_code` reports the name rather than falling
    back to the class of whatever wrapper reached it — the same reason `CapturedCallError`
    carries one. `failure_codes` then reads `['PolicyNotEvaluated']` instead of a generic
    `RuntimeError`, which is the difference between "the harness addressed the request
    wrongly" and "the service was unhappy".

    Absent from `RETRY_CODES` and `RETRYABLE_TRANSPORT` on purpose: a mis-addressed request
    fails identically on every attempt, so retrying would triple the cost of proving a
    harness bug. One attempt, recorded, and the run refuses at `require_measured`.
    """

    error_code = "PolicyNotEvaluated"

# The scope that makes a non-detection observable. See the module docstring; this is
# a constant rather than a per-call argument so no arm can quietly opt out of it.
OUTPUT_SCOPE = "FULL"


# --------------------------------------------------------------------------
# corpora
# --------------------------------------------------------------------------

def load_corpus(rel: str, *, limit: int | None = None,
                root: Path | None = None,
                stratify_by: str | None = None) -> list[dict]:
    """Load a corpus JSONL, in file order.

    File order, not shuffled: `corpora/build.py` emits items grouped by template
    and surface form, and `verify_corpora.py` pins the file's hash. Taking the
    first `limit` items under `--n` therefore yields a *stated* subset (the smoke
    run's items are reproducible and inspectable) rather than a random one that
    would differ between a dry run and the real run.

    The consequence is stated where it matters: a `--n 3` smoke sample is NOT a
    representative sample, so no smoke run's rate is ever reported as a result.
    `is_smoke` travels in the checkpoint metadata for that reason.

    `root` exists for the three Phase 1 corpora the sealed pre-registration does not
    name (F3-5 topic, F3-6 word probe, F3-7 grounding — see DEVIATIONS.md/DEV-P1-4).
    They live under `corpora_deviation/` rather than `corpora/`, because the sealed
    tree's gate fails on any `.jsonl` its manifest does not list and *that gate is
    right*: a corpus appearing inside the sealed tree without a sealed size would be
    indistinguishable from a pre-registered one at the moment a reader looks at it.
    Keeping them in a separately-named tree makes "not pre-registered" a property of
    the path instead of a sentence in a deviations file someone has to find.

    `stratify_by` and why a plain head is wrong for some files
    ---------------------------------------------------------
    A head is a fine smoke subset when the caller treats every returned item the same
    way. It is the wrong subset when the caller *splits the returned rows into strata
    afterwards*, because then `limit` silently decides the stratum sizes — and file order
    is grouped, so it decides them badly. `multilingual/<lang>.jsonl` holds 54 labelled
    attacks followed by 6 CLEAN items at positions 54-59, so `limit=3` returns three
    JAILBREAK items and **zero** CLEAN ones. F8-2 compares recall against that same
    file's CLEAN FPR, so its smoke run spent 24 billable calls and then divided by zero
    (DEVIATIONS.md/DEV-P1-10).

    With `stratify_by="label"` the head is taken **within each stratum, in first-appearance
    order**, so a value present in the file is present in the subset. Properties kept from
    the plain head, because they are the reasons it was a head in the first place:

    * deterministic — no shuffle, no seed, identical between `--dry-run` and the real run;
    * a stated subset — "the first `limit` of each label, in file order";
    * final order is still ascending by original position, so the evidence rows and the
      corpus line numbers stay comparable by eye.

    `limit=None` returns the whole file and `stratify_by` is then a no-op, which is why
    the full runs this project actually reports are unaffected by the choice.
    """
    p = (root or CORPORA) / rel
    if not p.exists():
        raise FileNotFoundError(f"corpus {rel} not found at {p}")
    items = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if not items:
        raise ValueError(f"corpus {rel} is empty — an arm over zero items would report "
                         f"a vacuous 0/0 rather than failing")
    if limit is None:
        return items
    if stratify_by is None:
        return items[:limit]
    missing = [i for i, it in enumerate(items) if stratify_by not in it]
    if missing:
        raise KeyError(f"corpus {rel}: {len(missing)} item(s) have no {stratify_by!r} "
                       f"field (first at line {missing[0] + 1}); stratifying on an absent "
                       f"key would silently pool them into one stratum")
    seen: dict[Any, int] = {}
    keep: list[int] = []
    for i, it in enumerate(items):
        k = it[stratify_by]
        n_so_far = seen.get(k, 0)
        if n_so_far < limit:
            seen[k] = n_so_far + 1
            keep.append(i)
    return [items[i] for i in keep]


def corpus_ids(items: Sequence[dict]) -> list[str]:
    return [it["id"] for it in items]


# --------------------------------------------------------------------------
# response reading
# --------------------------------------------------------------------------

@dataclass
class Assessment:
    """The flattened per-item reading of one ApplyGuardrail response.

    Every field is an observation. Nothing here consults an oracle, and nothing
    here is named for a verdict: `detected` is what the classifier said, `blocked`
    is what the configuration did about it, and the two are separate facts.
    """

    action: str = "NONE"                     # NONE | GUARDRAIL_INTERVENED
    action_reason: str = ""
    detected_types: list[str] = field(default_factory=list)
    blocked_types: list[str] = field(default_factory=list)
    confidences: dict[str, str] = field(default_factory=dict)
    pii_detected: list[str] = field(default_factory=list)
    pii_actions: dict[str, str] = field(default_factory=dict)
    topics_detected: list[str] = field(default_factory=list)
    words_detected: list[str] = field(default_factory=list)
    grounding: list[dict] = field(default_factory=list)
    text_units: dict[str, int] = field(default_factory=dict)
    guardrail_latency_ms: int | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    # `assessments[].invocationMetrics.usage` — the SAME nine counters as top-level
    # `usage`, reported per assessment. Read for every arm, like `text_units`, because
    # F10-2's oracle is that TextUnitCount "matches the billed quantity" and a
    # disagreement between the two places the service reports it is itself the finding.
    # If they always agree, that is a measured redundancy; the point is that F10-2 must
    # not be able to read only one of them.
    invocation_usage: dict[str, Any] = field(default_factory=dict)
    invocation_coverage: dict[str, Any] = field(default_factory=dict)
    # `assessments[].appliedGuardrailDetails` — F8-6's whole instrument. `guardrailArn`
    # embeds the Region that served the evaluation, `guardrailOrigin` is a LIST with enum
    # [REQUEST, ACCOUNT_ENFORCED, ORGANIZATION_ENFORCED], and `guardrailOwnership` is
    # [SELF, CROSS_ACCOUNT]. Read on every arm because an arm that silently ran against
    # an ACCOUNT_ENFORCED guardrail rather than the one it named would report the wrong
    # configuration's behaviour — which is precisely what Phase 5c's window could cause.
    applied_details: dict[str, Any] = field(default_factory=dict)
    # Which `assessments[]` keys the service actually returned, unioned over the list.
    #
    # This is a LIVENESS channel, not decoration, and it is not derivable from the flattened
    # fields above: `grounding == []` has two causes that are byte-indistinguishable once
    # flattened — "the filter ran and scored above threshold" and "the filter never ran at
    # all" — and F3-7 published a FALSE (a refutation of the document) from the second while
    # reading it as 120 clean negatives. See `ArmSpec.require_policy`.
    blocks_present: list[str] = field(default_factory=list)

    def detected(self, kind: str) -> bool:
        return kind in self.detected_types

    def blocked(self, kind: str) -> bool:
        return kind in self.blocked_types


def read_assessment(resp: dict) -> Assessment:
    """Flatten one ApplyGuardrail response. Tolerant of absent policy blocks.

    Absent means *this guardrail has no such policy configured*, which is a
    legitimate configuration and not an error — F3-1's guardrail has no PII policy,
    so `sensitiveInformationPolicy` is simply missing. A KeyError here would turn
    "the arm asked about content filters" into a crash.

    BUT TOLERANCE HERE IS NOT TOLERANCE AT THE ORACLE
    -------------------------------------------------
    Being tolerant of an absent block is right for a *flattener* and wrong for a *reader*.
    Flattening erases the difference between "the filter ran and did not fire" and "the
    filter did not run", and for one filter the second is reachable by a one-word mistake.
    Measured on the live service (2026-08-10, us-east-1), same three-block request, same
    guardrail, only `source` differing:

        source=INPUT   -> action=NONE,                 assessments[] keys:
                          [appliedGuardrailDetails, invocationMetrics]
        source=OUTPUT  -> action=GUARDRAIL_INTERVENED, assessments[] keys:
                          [appliedGuardrailDetails, contextualGroundingPolicy,
                           invocationMetrics]
                          GROUNDING score=0.0 BLOCKED, RELEVANCE score=0.97 NONE

    Contextual grounding scores a *response*; at `source=INPUT` the service accepts the
    request, bills it, returns 200 and `action=NONE`, and simply omits the policy block. No
    error, no warning. F3-7 sent all 120 trials that way and published `FALSE` — a refutation
    of the document — from a filter that had never executed, with x=0 on BOTH arms and
    `blocks_per_trial=[3]` looking correct beside it (DEVIATIONS.md/DEV-P1-18).

    So the key set is recorded, and `ArmSpec.require_policy` turns its absence into a failed
    trial. Which blocks are safe to require is itself measured, not assumed — on a benign
    input that fires nothing:

        contentPolicy               PRESENT   (cf-medium, determinism)
        sensitiveInformationPolicy  PRESENT   (pii)
        topicPolicy                 PRESENT   (topic)
        wordPolicy                  ABSENT    (words)
        contextualGroundingPolicy   ABSENT    (grounding — and this is the liveness case)

    The first three declare themselves whether or not they fire, so requiring them is a real
    liveness check. `wordPolicy` is absent on a non-match, so requiring it would fail every
    true negative — which is why this is a per-arm opt-in naming one block, and not a blanket
    rule applied to whatever the guardrail happens to configure.
    """
    a = Assessment(action=resp.get("action", "NONE"),
                   action_reason=resp.get("actionReason", ""))
    seen: set[str] = set()
    for block in resp.get("assessments") or []:
        seen.update(block)
        for f in ((block.get("contentPolicy") or {}).get("filters") or []):
            t = f.get("type", "")
            if f.get("detected"):
                a.detected_types.append(t)
                a.confidences[t] = f.get("confidence", "")
            if f.get("action") == "BLOCKED":
                a.blocked_types.append(t)
        for e in ((block.get("sensitiveInformationPolicy") or {})
                  .get("piiEntities") or []):
            if e.get("detected"):
                a.pii_detected.append(e.get("type", ""))
                a.pii_actions[e.get("type", "")] = e.get("action", "")
        for t in ((block.get("topicPolicy") or {}).get("topics") or []):
            if t.get("detected"):
                a.topics_detected.append(t.get("name", ""))
                if t.get("action") == "BLOCKED":
                    a.blocked_types.append("TOPIC:" + t.get("name", ""))
        wp = block.get("wordPolicy") or {}
        for w in (wp.get("customWords") or []) + (wp.get("managedWordLists") or []):
            if w.get("detected"):
                a.words_detected.append(w.get("match", ""))
        for g in ((block.get("contextualGroundingPolicy") or {}).get("filters") or []):
            a.grounding.append({"type": g.get("type"), "score": g.get("score"),
                                "threshold": g.get("threshold"),
                                "action": g.get("action"),
                                "detected": bool(g.get("detected"))})
        im = block.get("invocationMetrics") or {}
        if im.get("guardrailProcessingLatency") is not None:
            a.guardrail_latency_ms = im["guardrailProcessingLatency"]
        if im.get("usage"):
            a.invocation_usage = dict(im["usage"])
        if im.get("guardrailCoverage"):
            a.invocation_coverage = dict(im["guardrailCoverage"])
        agd = block.get("appliedGuardrailDetails") or {}
        if agd:
            # `guardrailOrigin` is modelled as a LIST, not a scalar. Copied as-is rather
            # than unwrapped: a reader that took `[0]` would report one origin for a
            # response carrying two, and the shape is the service's to define.
            a.applied_details = dict(agd)
    # `usage` is top-level, outside `assessments`. It is the text-unit count F10-2
    # tests and the quantity guardrail billing is denominated in, so it is recorded
    # for every item of every arm, not only F10-2's — a billing claim measured on a
    # dedicated arm cannot be cross-checked against the arms it generalises over.
    a.text_units = dict(resp.get("usage") or {})
    a.coverage = dict(resp.get("guardrailCoverage") or {})
    a.blocks_present = sorted(seen)
    return a


# --------------------------------------------------------------------------
# the runner
# --------------------------------------------------------------------------

@dataclass
class ArmSpec:
    """One arm: a corpus, a guardrail, and how to read a hit out of the response."""

    case_id: str
    family: str
    corpus: str
    guardrail_id: str
    guardrail_version: str = "DRAFT"
    source: str = "INPUT"                    # INPUT | OUTPUT
    qualifiers: tuple[str, ...] = ()         # ('guard_content',) for the tagging arms
    region: str = A.MAIN_REGION
    label: str = ""                          # arm label, for multi-arm cases
    # Contextual grounding needs THREE text blocks in one request — the source tagged
    # `grounding_source`, the question tagged `query`, and the candidate response
    # untagged — because the filter scores the response against the other two. A single
    # `qualifiers` tuple applied to one block cannot express that: it would send the
    # source and no response, and the filter would score nothing while returning
    # `action=NONE`, which reads exactly like "grounded".
    #
    # `multi_block` is a function of the item rather than a flag, so the block list is
    # built from the item's own fields and an item missing one of them fails loudly
    # instead of silently producing a one-block request.
    multi_block: Callable[[dict], list[dict]] | None = None
    # Given an item and its Assessment, did the thing this arm counts happen?
    # Defaults to "the item's own label was detected", which is what a recall arm
    # means; an FPR arm passes `hit=any_detection` instead.
    hit: Callable[[dict, Assessment], bool] | None = None
    # The `assessments[]` key that MUST be present, or the trial is a failure rather than a
    # negative. Opt-in and single-valued by design.
    #
    # Why opt-in: absence means different things per policy, measured rather than assumed
    # (the table in `read_assessment`). `contentPolicy`, `sensitiveInformationPolicy` and
    # `topicPolicy` are returned whether or not they fire, so requiring one of them is a
    # genuine liveness check. `wordPolicy` is absent on a non-match, so requiring it would
    # convert every true negative into a failed trial — a guard that turns correct data into
    # holes. A blanket "require every block the guardrail configures" rule would do exactly
    # that to F3-6.
    #
    # Why a failure and not an exception at the tally: a failed trial is already the concept
    # this project has for "no measurement here" — it stays out of `n_usable`, lands in
    # `failed` with a code, is retried by a resume, and makes `require_measured` refuse the
    # run below 90% completion. Raising inside the trial body reuses all of that; a check
    # after the loop would have to reinvent it.
    require_policy: str = ""

    def hit_of(self, item: dict, asm: Assessment) -> bool:
        if self.hit is not None:
            return self.hit(item, asm)
        return asm.detected(item.get("label", ""))


def any_detection(_item: dict, asm: Assessment) -> bool:
    """The FPR reading: did ANY policy fire on this item?

    Deliberately broader than "the content filter fired". A benign item blocked by
    the word filter is still a false positive from the reader's point of view, and
    an FPR that counted only one policy would understate the rate a reader
    experiences — which is the number §7.1's precision arithmetic needs.
    """
    return bool(asm.detected_types or asm.pii_detected or asm.topics_detected
                or asm.words_detected
                or any(g["detected"] for g in asm.grounding))


def run_arm(spec: ArmSpec, items: Sequence[dict], *, run_id: str,
            factory: A.ClientFactory | None = None,
            checkpoint_root: Path | None = None,
            evidence_root: Path | None = None,
            is_smoke: bool = False,
            progress: Callable[[int, int], None] | None = None,
            sleep: Callable[[float], None] | None = None) -> dict:
    """Send every item through the guardrail; return the arm's tally.

    Resumable. The trial id is the corpus item's own content-hash id, so a resumed
    run re-sends exactly the items that have no result — not "the last N", which
    would double-count or skip on any failure that was not the final one.

    `sleep` is injectable so the retry path can be exercised in the offline suite without
    the linear 5 s / 10 s backoff. It is threaded in rather than monkeypatched at the test
    site because the thing under test is that the backoff is *reached at all*: the retry
    branch was dead for the whole of this module's first draft (see
    `evidence.CapturedCallError`), and a test that patched `time.sleep` globally would have
    passed either way.
    """
    f = factory or A.factory(spec.region)
    client = f.bedrock_runtime()
    if not A.has_operation(client, "ApplyGuardrail"):
        raise RuntimeError(
            f"botocore {A.sdk_versions()['botocore']} does not model ApplyGuardrail; "
            f"this arm cannot be expressed by the installed SDK (F1-1)")

    # `cell` is the arm label, never folded into `case_id`: Checkpoint names its file
    # `<case_id>__<cell>.json` precisely so two arms of one case cannot collide, and
    # collapsing them into one string would reintroduce the collision it prevents.
    cell = spec.label or "main"
    name = f"{spec.case_id}{('-' + spec.label) if spec.label else ''}"
    kw = {"root": checkpoint_root} if checkpoint_root else {}
    cp = Checkpoint(spec.case_id, cell, **kw).load()
    cp.set_meta(case_id=spec.case_id, arm=spec.label, corpus=spec.corpus,
                guardrail_version=spec.guardrail_version, region=spec.region,
                source=spec.source, qualifiers=list(spec.qualifiers),
                output_scope=OUTPUT_SCOPE, planned_n=len(items),
                is_smoke=is_smoke, run_id=run_id,
                sdk=A.sdk_versions()["botocore"])
    store = EvidenceStore(run_id, spec.family, name, root=evidence_root)
    store.write_environment()
    lim = A.limiter()

    text: dict[str, Any] = {"text": ""}
    for idx, item in enumerate(items):
        if cp.is_done(item["id"]):
            continue

        def one(it=item) -> dict:
            lim.wait("ApplyGuardrail")
            if spec.multi_block is not None:
                blocks = spec.multi_block(it)
                if spec.qualifiers:
                    raise ValueError(
                        f"{spec.case_id}: an arm cannot set both `qualifiers` and "
                        f"`multi_block` — the first tags one block and the second builds "
                        f"the whole list, so honouring both would silently drop one")
            else:
                block = {"text": {"text": it["text"]}}
                if spec.qualifiers:
                    block["text"]["qualifiers"] = list(spec.qualifiers)
                blocks = [block]
            rec = capture(store, "apply_guardrail", client,
                          guardrailIdentifier=spec.guardrail_id,
                          guardrailVersion=spec.guardrail_version,
                          source=spec.source, outputScope=OUTPUT_SCOPE,
                          content=blocks)
            rec.raise_for_status()
            asm = read_assessment(rec.response or {})
            if spec.require_policy and spec.require_policy not in asm.blocks_present:
                # PolicyNotEvaluated, not a bare RuntimeError: `checkpoint.error_code` reads
                # a non-empty `error_code` attribute before falling back to the class name,
                # so this lands in `failure_codes` as a name that says what happened. It is
                # deliberately NOT in RETRY_CODES/RETRYABLE_TRANSPORT — a mis-addressed
                # request fails identically on all 3 attempts, and retrying it would spend
                # 3x the calls to re-prove a harness bug.
                raise PolicyNotEvaluated(
                    f"{spec.case_id}/{cell}: the service returned 200 and "
                    f"action={asm.action!r} but no {spec.require_policy!r} block "
                    f"(present: {asm.blocks_present}). The filter did not run, so this "
                    f"trial measured nothing — it is NOT a negative. Check `source`: "
                    f"contextual grounding scores a response and is silently skipped at "
                    f"source=INPUT (DEVIATIONS.md/DEV-P1-18).")
            return {
                "item_id": it["id"], "label": it.get("label", ""),
                "resembles": it.get("resembles", ""),
                "surface": it.get("surface", ""), "slot": it.get("slot", ""),
                "hit": spec.hit_of(it, asm),
                "action": asm.action, "action_reason": asm.action_reason,
                "detected_types": asm.detected_types,
                "blocked_types": asm.blocked_types,
                "confidences": asm.confidences,
                "pii_detected": asm.pii_detected, "pii_actions": asm.pii_actions,
                "topics_detected": asm.topics_detected,
                "words_detected": asm.words_detected,
                "grounding": asm.grounding,
                # Which policy blocks the service returned. On the row rather than only in
                # the raw evidence because this is what distinguishes "did not fire" from
                # "did not run", and an analysis reading `results/` must be able to tell
                # them apart without re-opening 4,500 evidence files.
                "blocks_present": asm.blocks_present,
                "text_units": asm.text_units,
                "guardrail_latency_ms": asm.guardrail_latency_ms,
                "coverage": asm.coverage,
                # The three fields F8-6 and F10-2 need, on every arm's rows for the same
                # reason `text_units` is: a claim measured only on its own dedicated arm
                # cannot be cross-checked against the arms it generalises over.
                "invocation_usage": asm.invocation_usage,
                "invocation_coverage": asm.invocation_coverage,
                "applied_details": asm.applied_details,
                # How many content blocks this trial sent. Recorded because a
                # multi-block request is billed and evaluated over the union of the
                # blocks: F10-2 reads `text_units` per trial, and a 3-block grounding
                # request whose block count is not on the row would look like a
                # 1-block request that cost three times as much.
                "n_blocks": len(blocks),
                "request_id": rec.request_id,
                "client_duration_ms": rec.duration_ms,
                "evidence": rec.path,
            }

        cp.run_trial(item["id"], one,
                     **({"sleep": sleep} if sleep is not None else {}))
        if progress:
            progress(idx + 1, len(items))

    store.write_summary({"arm": name, "n_items": len(items)})
    return tally(cp, spec, len(items))


def tally(cp: Checkpoint, spec: ArmSpec, planned_n: int) -> dict:
    """The arm's counts, in the shape `lib/oracle.Observation` consumes.

    `n_attempted` and `n_usable` are both reported and are not the same number.
    Anything that never reached the service is a failure, not a non-detection: a
    throttled item counted as a miss would push every recall down by the harness's
    own error rate and publish it as a property of the guardrail.
    """
    rows = list(cp.results().values())
    x = sum(1 for r in rows if r.get("hit"))
    fails = cp.failures()
    return {
        "case_id": spec.case_id, "arm": spec.label,
        "corpus": spec.corpus, "planned_n": planned_n,
        "n_attempted": planned_n,
        "n_usable": len(rows),
        "x": x,
        "n_failed": len(fails),
        "failure_codes": sorted({v.get("error_code", "") for v in fails.values()}),
        "rows": rows,
        "checkpoint": str(cp.path),
    }


def per_label_tally(rows: Iterable[dict]) -> dict[str, dict[str, int]]:
    """Split a tally by the item's own label.

    F3-8 (recall by prompt-attack subtype) and F3-4 (recall per PII entity type)
    have per-label oracles, and a pooled rate would let a strong subtype conceal a
    failing one — the pooled figure is an average over a corpus composition we
    chose, so it is not a statement about any subtype.
    """
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        k = r.get("label") or "?"
        d = out.setdefault(k, {"x": 0, "n": 0})
        d["n"] += 1
        d["x"] += 1 if r.get("hit") else 0
    return out
