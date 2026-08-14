#!/usr/bin/env python3
"""F8-5: are the denied-topic definition length limits really 200 (Classic) / 1000 (Standard)?

    python3 f8_regional/04_topic_limits.py --dry-run
    python3 f8_regional/04_topic_limits.py --n 3          # same as full; see below
    python3 f8_regional/04_topic_limits.py

§3.4's tier table row: "Denied topic definition length | 200 chars | 1,000 chars". The
sealed oracle is `BOUNDARY`: TRUE if each tier accepts its limit and rejects limit+1;
FALSE otherwise.

THIS CASE IS FOUR CALLS, NOT AN ARM — AND `--n` CANNOT SHRINK IT
---------------------------------------------------------------
A boundary is four probes: (CLASSIC, 200) accepted, (CLASSIC, 201) rejected,
(STANDARD, 1000) accepted, (STANDARD, 1001) rejected. There is no corpus and no sample
size; `planned_n(F8-5)` is None because the question is not a rate. `--n` is accepted for
uniformity with every other Phase 1 script and **is ignored**, which the dry run says
outright: silently sampling 3 of 4 probes would drop one boundary and report a verdict over
a conjunction it never evaluated.

WHY THE NUMBERS ARE IN THE PAYLOAD AND NOT IN THE BINDING
---------------------------------------------------------
`BINDINGS['F8-5'].thresholds` is the **empty tuple**, so `oracle._decide`'s BOUNDARY branch
emits `"limits": []`. That is not an oversight to route around: the seal records the two
numbers on **F1-10** (`thresholds=(200.0, 1000.0)`, pinned to the prose tokens "200" and
"1000"), and F8-5 carries `limits_by_reference` naming F1-10 as the case that pins them.
The numbers therefore travel in this script's payload, labelled with where they come from,
so the output never shows an empty `limits` list beside a boundary result and leaves a
reader to guess which boundary was tested.

CLIENT-SIDE VALIDATION PROVABLY CANNOT DECIDE THIS
--------------------------------------------------
`topicsConfig[].definition` has `max=200` in the botocore 1.43.67 model — **regardless of
tier**. If botocore enforced it, a 1000-character STANDARD definition would be rejected in
process and the STANDARD half of the oracle would be untestable through this SDK.

It does not enforce it. `botocore.validate.range_check` has **only a `min` branch** and
`_validate_string` performs no length check at all, which was confirmed by running
`ParamValidator().validate()` on `CreateGuardrail` with definition lengths
1 / 200 / 201 / 1000 / 1001 / 5000: every one returned client-side OK. So each probe reaches
the service and the verdict is the **server's**. That check is re-run here, live, before any
mutating call — because if a future botocore adds the max branch, this script would
otherwise report "rejected at 1001" as a service boundary when the rejection never left the
machine. The re-check is an assertion about the instrument, and it is recorded either way.

The model's own `max=200` is itself reportable: an SDK that declares 200 as the ceiling on a
field the document says accepts 1000 on STANDARD is a surface the document does not mention,
and it is emitted as `sdk_declared_max` whatever the server does.

WHAT THIS SCRIPT CREATES, AND WHAT IT REFUSES TO TOUCH
-----------------------------------------------------
The Phase 1 provisioner's `topic` guardrail is **CLASSIC-only** (`tierConfig.tierName =
CLASSIC`, definition ~140 chars) because F3-5 needs one stable topic configuration. It
cannot answer the STANDARD half, and changing its tier would silently change F3-5's
instrument. So this case creates its own probe guardrails — one per (tier, length) that is
expected to succeed — and deletes them in a `finally`. It never reads, updates or deletes
anything from the manifest.

Every probe is a `CreateGuardrail` call whose **error is the data**: a rejected 201-char
definition is the oracle firing, not a failure. `lib/evidence.capture` records both branches
identically, which is what makes "rejected" quotable as a request id and an error code
rather than as a Python traceback.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A    # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
from evidence import EvidenceStore, capture  # noqa: E402

FAMILY = "f8"
CASE = "F8-5"

# The two limits, and where they come from. Not literals chosen here: F1-10's binding pins
# them to the document's own prose tokens, and F8-5's binding names F1-10 as the case that
# does so. Read off the seal at runtime rather than typed, so a re-seal that changed them
# would change this script's probes instead of leaving it testing the remembered numbers.
LIMIT_SOURCE_CASE = "F1-10"

# One filler character, repeated. Deliberately not English prose: a 1001-character sentence
# and a 200-character one differ in content as well as in length, and a rejection could then
# be about what the definition says. 'a' is in every accepted character set the service
# documents, so length is the only thing that varies across the four probes.
FILLER = "a"


def limits() -> tuple[int, int]:
    """(classic, standard) topic-definition limits, read off F1-10's sealed thresholds."""
    thr = O.BINDINGS[LIMIT_SOURCE_CASE].thresholds
    if len(thr) != 2:
        raise RuntimeError(
            f"{LIMIT_SOURCE_CASE}'s binding carries {len(thr)} threshold(s); F8-5's two "
            f"tier limits are read from it and cannot be recovered from anywhere else "
            f"(F8-5's own thresholds tuple is empty by design)")
    return int(thr[0]), int(thr[1])


def probes() -> list[dict[str, Any]]:
    """The four boundary probes, in a fixed order, each with its expected outcome."""
    classic, standard = limits()
    out = []
    for tier, limit in (("CLASSIC", classic), ("STANDARD", standard)):
        for length, expect in ((limit, "accepted"), (limit + 1, "rejected")):
            out.append({"tier": tier, "length": length, "expect": expect,
                        "label": f"{tier.lower()}-{length}"})
    return out


def client_side_check() -> dict[str, Any]:
    """Does botocore reject an over-length definition before the call leaves the process?

    Re-run live rather than trusted from a note. If a future botocore gains the `max`
    branch that `range_check` currently lacks, every "rejected" outcome below would be a
    client-side rejection reported as a service boundary — the finding would be about the
    SDK and would read as being about AWS.
    """
    from botocore.validate import ParamValidator

    f = A.factory(A.MAIN_REGION)
    client = f.bedrock()
    model = client.meta.service_model.operation_model("CreateGuardrail")
    shape = model.input_shape
    topic_def = (shape.members["topicPolicyConfig"].members["topicsConfig"]
                 .member.members["definition"])
    declared_max = topic_def.metadata.get("max")

    v = ParamValidator()
    results = {}
    for length in sorted({1, *[p["length"] for p in probes()], 5000}):
        report = v.validate({
            "name": "grx-clientside-probe",
            "blockedInputMessaging": "x", "blockedOutputsMessaging": "x",
            "topicPolicyConfig": {"topicsConfig": [
                {"name": "Probe", "definition": FILLER * length, "type": "DENY"}]},
        }, shape)
        results[str(length)] = ("client-side OK" if not report.has_errors()
                               else report.generate_report())

    enforced = any(r != "client-side OK" for r in results.values())
    return {
        "sdk_declared_max": declared_max,
        "sdk_declared_max_note": (
            f"the model declares definition max={declared_max} REGARDLESS of tier, on the "
            f"same field the document says accepts {limits()[1]} on STANDARD. Reported "
            f"whatever the server does: an SDK ceiling below a documented service ceiling "
            f"is a surface §3.4 does not mention"),
        "param_validator": results,
        "client_side_enforces_max": enforced,
        "instrument_is_sound": not enforced,
        "why_checked": (
            "botocore.validate.range_check has only a `min` branch and _validate_string "
            "performs no length check, so an over-length definition reaches the service "
            "and the verdict is the SERVER's. If a future botocore adds the max branch "
            "this flag flips and every 'rejected' below becomes a client-side rejection — "
            "a finding about the SDK that would read as one about AWS"),
        "sdk": A.sdk_versions(),
    }


def run_probe(client, store, lim, probe: dict, *, tags: list[dict],
              run_id: str) -> P.ProbeGuardrail:
    """One CreateGuardrail call. The error IS the observation.

    `phase1.create_probe_guardrail` is shared with F8-7 so the teardown guarantee is
    written and tested once; the boundary-specific reading of the result is below.
    """
    return P.create_probe_guardrail(
        client, store, lim,
        case_id=CASE,
        label=probe["label"],
        name=f"grx-gr-f8-5-{probe['label']}-{run_id}",
        description=f"F8-5 boundary probe: {probe['tier']} {probe['length']} chars",
        tags=tags,
        config={"topicPolicyConfig": {
            "topicsConfig": [{"name": "F8_5_Probe",
                              "definition": FILLER * probe["length"],
                              "type": "DENY"}],
            "tierConfig": {"tierName": probe["tier"]}}},
        tier=probe["tier"], length=probe["length"], expect=probe["expect"])


def read_probe(p: P.ProbeGuardrail) -> dict[str, Any]:
    """The boundary reading of one probe, with `expected` kept beside `observed`.

    `matches_expected` is recorded but is NOT the verdict: F8-5's verdict is the oracle's
    conjunction over `at_limit_ok` and `over_limit_rejected`. Keeping the per-probe
    expectation visible is what lets a reader see WHICH half of a FALSE verdict failed —
    "the document is wrong about STANDARD" and "the document is wrong about CLASSIC" are
    different findings and a bare FALSE distinguishes neither.
    """
    observed = "accepted" if p.accepted else "rejected"
    return {"label": p.label, "name": p.name,
            "tier": p.detail["tier"], "length": p.detail["length"],
            "expect": p.detail["expect"], "observed": observed,
            "accepted": p.accepted,
            "matches_expected": observed == p.detail["expect"],
            "guardrail_id": p.guardrail_id,
            "error_code": p.error_code, "error_message": p.error_message,
            "http_status": p.http_status, "request_id": p.request_id,
            "evidence": p.evidence}


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)
    classic, standard = limits()
    pr = probes()

    if args.dry_run:
        return P.dry_run_banner(
            CASE, [(p["label"], f"CreateGuardrail {p['tier']} {p['length']} chars", 1)
                   for p in pr],
            operations={"CreateGuardrail": len(pr)},
            mutations=len(pr), billable=False,
            extra=[
                f"plus up to {sum(1 for p in pr if p['expect'] == 'accepted')} "
                f"DeleteGuardrail calls in the teardown finally — 'up to', because a probe "
                f"that was REJECTED created nothing to delete, and the count therefore "
                f"depends on the result",
                f"the two limits are read from {LIMIT_SOURCE_CASE}'s sealed thresholds "
                f"(CLASSIC {classic}, STANDARD {standard}); F8-5's own thresholds tuple is "
                f"EMPTY by design, so oracle._decide prints limits=[] and the numbers "
                f"travel in the payload instead",
                f"--n is IGNORED for this case: a boundary is {len(pr)} probes and "
                f"sampling 3 of them would drop one boundary and report a verdict over a "
                f"conjunction it never evaluated",
                "each probe is a CreateGuardrail whose ERROR is the data; every accepted "
                "probe is deleted in a finally",
                "the client-side check is re-run live first: botocore's range_check has no "
                "max branch today, and if that changes every 'rejected' below would be a "
                "client-side rejection reported as a service boundary",
                "this is the ONLY Phase 1 case that creates AWS resources; it touches "
                "nothing in results/phase1_guardrails.json"])

    if args.n is not None:
        print(f"note: --n {args.n} ignored; this case is {len(pr)} fixed boundary probes")

    run_id = P.resolve_run(args)
    is_smoke = False          # there is no smaller version of a boundary
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()

    cs = client_side_check()
    print(f"\nSDK declares definition max={cs['sdk_declared_max']}   "
          f"client-side enforces it: {cs['client_side_enforces_max']}")
    if cs["client_side_enforces_max"]:
        # Not a crash: the finding is real and belongs in the record. But the verdict must
        # not be computed, because "rejected" would then mean "botocore refused".
        print("FATAL: botocore now enforces the definition max client-side, so an "
              "over-length probe never reaches the service and this instrument cannot "
              "measure a SERVER boundary. Recording the instrument finding and stopping.",
              file=sys.stderr)
        # `O.not_measured`, not `O.evaluate(P.obs_recorded(...))`. F8-5's sealed kind is
        # BOUNDARY, so `_decide` dispatches to BOUNDARY's `_need(at_limit_ok,
        # over_limit_rejected)` regardless of the observation's shape and raises — the
        # first draft of this branch would have crashed on exactly the path it exists to
        # protect. RECORDED is a property of the seal (the pre-registration declaring an
        # outcome unknown), not something a script may grant itself. See
        # DEVIATIONS.md/DEV-P1-8.
        rec = O.not_measured(
            CASE,
            "botocore enforces the topic-definition maximum client-side, so an "
            "over-length probe never reaches the service and this instrument cannot "
            "measure a SERVER boundary",
            client_side_check=cs)
        P.emit(CASE, rec, {"run_id": run_id, "is_smoke": is_smoke,
                           "billable_calls": 0, "mutations": 0,
                           "client_side_check": cs,
                           "instrument": "CreateGuardrail — NOT RUN"},
               EvidenceStore(run_id, FAMILY, CASE))
        return 2

    expires = (datetime.now(timezone.utc) + timedelta(hours=2)) \
        .replace(microsecond=0).isoformat()
    tags = [{"key": k, "value": v}
            for k, v in sorted(A.tags_for(run_id, expires).items())]

    f = A.factory(args.region)
    client = f.bedrock()
    lim = A.limiter()

    probes_made: list[P.ProbeGuardrail] = []
    results: list[dict[str, Any]] = []
    deletions: list[dict[str, Any]] = []
    try:
        for p in pr:
            made = run_probe(client, store, lim, p, tags=tags, run_id=run_id)
            probes_made.append(made)
            r = read_probe(made)
            results.append(r)
            mark = "ok " if r["matches_expected"] else "XX "
            print(f"  {mark}{p['tier']:9s} {p['length']:>5d} chars -> {r['observed']}"
                  + (f" ({r['error_code']})" if r["error_code"] else "")
                  + f"   request-id {r['request_id']}")
    finally:
        # In a `finally`, and over `probes_made` rather than over `results`: a probe that
        # created a guardrail and then raised while being READ would be absent from
        # `results` and its guardrail would survive.
        if any(x.guardrail_id for x in probes_made):
            print(f"\ndeleting "
                  f"{sum(1 for x in probes_made if x.guardrail_id)} probe guardrail(s)...")
            deletions = P.delete_probe_guardrails(client, store, lim, probes_made)
            for d in deletions:
                if not d["deleted"]:
                    print(f"  WARNING: {d['guardrail_id']} not deleted "
                          f"({d['error_code']}); Phase 99's tag sweep will flag it",
                          file=sys.stderr)

    residue = P.probe_residue(probes_made, deletions)
    by_label = {r["label"]: r for r in results}
    at_limit_ok = all(by_label[f"{t.lower()}-{n}"]["accepted"]
                      for t, n in (("CLASSIC", classic), ("STANDARD", standard)))
    over_limit_rejected = all(not by_label[f"{t.lower()}-{n + 1}"]["accepted"]
                              for t, n in (("CLASSIC", classic), ("STANDARD", standard)))

    o = P.obs_boundary(CASE, at_limit_ok=at_limit_ok,
                       over_limit_rejected=over_limit_rejected,
                       classic_limit=classic, standard_limit=standard)
    rec = O.evaluate(o)

    per_tier = {}
    for tier, limit in (("CLASSIC", classic), ("STANDARD", standard)):
        a = by_label[f"{tier.lower()}-{limit}"]
        b = by_label[f"{tier.lower()}-{limit + 1}"]
        per_tier[tier] = {
            "documented_limit": limit,
            "at_limit": {"length": limit, "accepted": a["accepted"],
                         "error_code": a["error_code"],
                         "request_id": a["request_id"]},
            "over_limit": {"length": limit + 1, "accepted": b["accepted"],
                           "error_code": b["error_code"],
                           "error_message": b["error_message"],
                           "request_id": b["request_id"]},
            "boundary_holds": a["accepted"] and not b["accepted"],
        }

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "billable_calls": 0,
        "billable_note": ("CreateGuardrail and DeleteGuardrail are control-plane calls and "
                          "bill no text units; this case sends no ApplyGuardrail at all"),
        "mutations": len(results),
        "mutation_note": (f"{len(results)} CreateGuardrail probes, "
                          f"{residue['n_created']} of which created a resource, deleted in "
                          f"a finally. This case and F8-7 are the only Phase 1 cases that "
                          f"create AWS resources; neither touches "
                          f"results/phase1_guardrails.json"),
        "limits_tested": {"CLASSIC": classic, "STANDARD": standard},
        "limits_provenance": {
            "read_from": f"{LIMIT_SOURCE_CASE}'s sealed thresholds",
            "f8_5_thresholds": list(O.BINDINGS[CASE].thresholds),
            "why_empty": O.BINDINGS[CASE].limits_by_reference,
            "consequence": ("oracle._decide's BOUNDARY branch emits limits=[] for this "
                            "case, so the two numbers are carried here instead — an empty "
                            "limits list beside a boundary verdict would leave a reader "
                            "guessing which boundary was tested"),
        },
        "per_tier": per_tier,
        "probes": results,
        "deletions": deletions,
        "residue": residue,
        "client_side_check": cs,
        "why_new_guardrails": (
            "the provisioner's `topic` guardrail is CLASSIC-only (tierConfig CLASSIC, "
            "~140-char definition) because F3-5 needs one stable topic configuration. "
            "Changing its tier to answer the STANDARD half would silently change F3-5's "
            "instrument, so this case creates and deletes its own probes"),
        "filler_rationale": (
            f"the definition is {FILLER!r} repeated. A 1001-character English sentence and "
            f"a 200-character one differ in content as well as length, and a rejection "
            f"could then be about what the definition says; here length is the only thing "
            f"that varies across the four probes"),
        "no_power_claim": (f"planned_n({CASE}) is None and this is not a rate: four "
                           f"deterministic probes, each decided by one service response. "
                           f"n_met={rec['n_met']} is vacuous and carries no information"),
        "instrument": ("CreateGuardrail with topicPolicyConfig.tierConfig.tierName set per "
                       "probe; the error branch of the response IS the observation"),
    }, store)

    # Exit code reflects whether the test RAN, not whether the document was right. A
    # boundary that differs from §3.4 is a successful test.
    if len(results) != len(pr):
        return 2
    if not residue["clean"]:
        print(f"FAIL: {len(residue['surviving'])} probe guardrail(s) survived: "
              f"{residue['surviving']}. Residue is a teardown failure, not a finding",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
