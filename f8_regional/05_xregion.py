#!/usr/bin/env python3
"""F8-6: does Standard-tier cross-Region inference stay inside the request's geography?

    python3 f8_regional/05_xregion.py --dry-run
    python3 f8_regional/05_xregion.py --n 3
    python3 f8_regional/05_xregion.py

§3.4's key-implications bullet claims a US-Region request's cross-Region inference is
served only from US Regions. The sealed oracle is `EXISTENCE`: TRUE if all inference for a
US-Region request is served from US Regions per CloudTrail/response metadata; FALSE if any
out-of-geography Region appears.

THIS IS THE ONLY PHASE 1 CASE WHOSE ORACLE IS NOT ABOUT DETECTION
-----------------------------------------------------------------
Every other F3/F8 case counts hits and compares intervals. This one counts **Regions**. A
guardrail that detected nothing at all could still satisfy F8-6, and a guardrail with
perfect recall could still fail it. So `hit` here is deliberately NOT a detection reading:
it is "this trial disclosed a serving Region, and that Region is in-geography". The
detection tallies are reported beside it as descriptive context and are not the verdict.

The consequence for `n`: the sealed cell is `multilingual_cell` (n=60), whose rule is
written about **interval disjointness for an equivalence-shaped recall claim**. That rule
does not transfer to a Region count, and this script says so rather than borrowing its
power argument. n=60 is honoured because the seal says 60; what 60 buys here is 60
independent opportunities for an out-of-geography Region to appear, and the Clopper-Pearson
ceiling at x=0/n=60 (one-sided 95%: 4.87%) is the only quantitative statement available.
That is a bound on the RATE of disclosed out-of-geography serving, not on the rate of
out-of-geography serving — see the next section, which is the honest ceiling on this case.

WHAT THE RESPONSE ACTUALLY DISCLOSES, STATED BEFORE ANY DATA IS COLLECTED
------------------------------------------------------------------------
Three instruments, in descending order of directness, all verified against the botocore
1.43.67 model:

  1. `GetGuardrail.crossRegionDetails` -> `{guardrailProfileId, guardrailProfileArn}`.
     This proves the cross-Region configuration TOOK EFFECT. It is a precondition, not the
     measurement: without it an "in-geography" result would be from a guardrail that was
     never cross-Region, which is the failure mode that would look like success.
  2. `ApplyGuardrail assessments[].appliedGuardrailDetails.guardrailArn`. An ARN's 4th
     colon-field is a Region. This is the per-trial reading, and `guardrailOrigin` /
     `guardrailOwnership` come with it — so a trial served by an ACCOUNT_ENFORCED guardrail
     instead of the one requested is visible rather than silently substituted.
  3. CloudTrail. Recorded as a **declared gap, not collected here**: `ApplyGuardrail` is a
     high-volume data-plane operation and data events for Bedrock guardrails are not
     enabled on this account. Turning them on is a Phase 2 testbed change with account-wide
     blast radius, and this case does not need it to be decidable — but the oracle text
     names CloudTrail, so its absence is on the face of the output rather than in a note.

**The ceiling, and it is a real one.** `appliedGuardrailDetails.guardrailArn` names the
Region of the *guardrail resource*, which is the Region the request was sent to. Whether a
cross-Region profile routed the underlying inference to us-west-2 rather than us-east-1 is
not something the response is documented to disclose. So a run of 60 in-geography readings
is consistent with two very different worlds:

  * the profile only ever routes within the US (the document is right), and
  * the profile routes anywhere it likes and the response never says so.

This case therefore tests the **disclosed** geography and reports the verdict as such. The
FALSE branch is fully decisive — any out-of-geography Region appearing anywhere falsifies
the claim outright — while the TRUE branch is bounded by what the API discloses. An
asymmetric oracle is the correct shape for a universally quantified safety claim (the same
argument the report makes for F5's five bypass routes), and the payload says so in
`what_true_does_not_prove` rather than leaving a reader to infer it.

WHY THE ARM IS DRIVEN OFF A CORPUS AT ALL
-----------------------------------------
Region disclosure does not need attack content. But 60 identical benign calls would make
"the Region field is constant" trivially unsurprising, whereas 60 calls spanning blocked
and unblocked outcomes tests whether an INTERVENED response discloses the same geography as
a NONE one. The multilingual `en.jsonl` file is used because it is exactly 60 items with a
54-attack / 6-CLEAN split already on disk and hashed by `verify_corpora.py`, so the arm
sends a set of items a file on disk names.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R          # noqa: E402
import awsclients as A    # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
import stats as S         # noqa: E402
from evidence import EvidenceStore, capture  # noqa: E402

FAMILY = "f8"
CASE = "F8-6"
CORPUS = "multilingual/en.jsonl"     # 60 items: 54 labelled attacks + 6 CLEAN

# The geography §3.4's bullet is about. us.guardrail.v1:0 is the US profile the
# provisioner attached, so "in-geography" means a US Region. Enumerated rather than
# pattern-matched on the `us-` prefix, because `us-gov-west-1` also starts with `us-` and
# GovCloud is a separate partition, not the same geography — a prefix test would silently
# call a partition crossing in-geography.
US_REGIONS = frozenset({
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
})
PROFILE = "us.guardrail.v1:0"


def region_of(arn: str) -> str:
    """The Region field of an ARN, or "" if this is not a parseable ARN.

    `arn:partition:service:region:account:resource`. Returns "" rather than raising: an
    unparseable value is an observation about what the service disclosed, and a crash here
    would discard the 59 trials that parsed.
    """
    parts = (arn or "").split(":")
    return parts[3] if len(parts) > 5 and parts[0] == "arn" else ""


def partition_of(arn: str) -> str:
    parts = (arn or "").split(":")
    return parts[1] if len(parts) > 5 and parts[0] == "arn" else ""


def hit_in_geography(_item: dict, asm: R.Assessment) -> bool:
    """TRUE for a trial that disclosed a Region AND that Region is a US Region.

    Not a detection reading. F8-6's oracle counts Regions, so a trial that disclosed
    nothing is NOT counted as in-geography — silence is not compliance. That makes the
    `x`/`n` gap the disclosure gap, which is the quantity this case's honesty depends on.
    """
    return region_of((asm.applied_details or {}).get("guardrailArn", "")) in US_REGIONS


def plan(n: int | None) -> list[tuple[str, str, int]]:
    return [("xregion", CORPUS, len(R.load_corpus(CORPUS, limit=n)))]


def cross_region_details(client, store, lim, gid: str) -> dict[str, Any]:
    """`GetGuardrail.crossRegionDetails` — the precondition, read before the arm runs.

    Read live rather than trusted from `results/phase1_guardrails.json`: the manifest
    records what the provisioner ASKED for, and this case's whole subject is whether the
    cross-Region configuration took effect.
    """
    lim.wait("GetGuardrail")
    rec = capture(store, "get_guardrail", client,
                  guardrailIdentifier=gid, guardrailVersion="DRAFT")
    resp = rec.response or {}
    det = dict(resp.get("crossRegionDetails") or {})
    return {
        "ok": rec.ok,
        "error_code": rec.error_code or None,
        "request_id": rec.request_id,
        "cross_region_details": det,
        "profile_id": det.get("guardrailProfileId"),
        "profile_arn": det.get("guardrailProfileArn"),
        "profile_arn_region": region_of(det.get("guardrailProfileArn", "")),
        "took_effect": bool(det),
        "tier": ((resp.get("contentPolicy") or {}).get("tier") or {}).get("tierName"),
        "status": resp.get("status"),
        "expected_profile": PROFILE,
        "why_read_live": ("the manifest records what the provisioner ASKED for; an "
                          "in-geography result from a guardrail whose crossRegionConfig "
                          "never took effect is the failure mode that would look like "
                          "success"),
        "evidence": rec.path,
    }


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)
    want = O.planned_n(CASE)

    if args.dry_run:
        return P.dry_run_banner(
            CASE, plan(args.n),
            extra=[
                "`hit` is NOT a detection reading: it is 'this trial disclosed a Region "
                "and that Region is a US Region'. A guardrail detecting nothing could "
                "satisfy F8-6; one with perfect recall could fail it",
                f"the sealed cell is multilingual_cell (n={want}), whose power rule is "
                f"about interval disjointness for a recall claim and does NOT transfer to "
                f"a Region count; n={want} is honoured because the seal says so, and what "
                f"it buys is {want} independent chances for an out-of-geography Region to "
                f"appear",
                "silence is not compliance: a trial that disclosed no Region is excluded "
                "from x, so the x/n gap IS the disclosure gap",
                "in-geography is an ENUMERATED US Region set, not a 'us-' prefix test — "
                "us-gov-west-1 starts with 'us-' and is a different partition",
                "CloudTrail is named by the oracle and is a DECLARED GAP here: "
                "ApplyGuardrail data events are not enabled on this account and enabling "
                "them is a Phase 2 change with account-wide blast radius",
                "GetGuardrail.crossRegionDetails is read LIVE first as a precondition; "
                "one extra control-plane call, no text units"])

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid = P.guardrail("xregion", man=man)
    is_smoke = args.n is not None
    print(f"\nSTANDARD + crossRegionConfig {PROFILE} (guardrail {gid})")

    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()
    f = A.factory(args.region)
    lim = A.limiter()
    pre = cross_region_details(f.bedrock(), store, lim, gid)
    print(f"  crossRegionDetails: profile={pre['profile_id']}  "
          f"took_effect={pre['took_effect']}  tier={pre['tier']}")
    if not pre["took_effect"]:
        # Recorded, not crashed. "The cross-Region configuration did not take effect" is a
        # finding about the service or the provisioner, and it is a DIFFERENT finding from
        # "cross-Region inference left the geography". Computing the second from data that
        # only supports the first is what this branch exists to prevent.
        print("FATAL: GetGuardrail reports no crossRegionDetails, so this guardrail is "
              "not cross-Region and an in-geography reading would say nothing about "
              "cross-Region inference. Recording the precondition failure and stopping.",
              file=sys.stderr)
        # `O.not_measured`, not `O.evaluate(P.obs_recorded(...))`: F8-6's sealed kind is
        # EXISTENCE, whose `_need(observed_bool)` raises on a detail-only observation, so
        # the first draft of this branch would have crashed on the path it exists to
        # protect. RECORDED belongs to the seal, not to a script. DEVIATIONS.md/DEV-P1-8.
        rec = O.not_measured(
            CASE,
            "GetGuardrail reports no crossRegionDetails, so this guardrail is not "
            "cross-Region and an in-geography reading would say nothing about "
            "cross-Region inference",
            precondition=pre)
        P.emit(CASE, rec, {"run_id": run_id, "is_smoke": is_smoke,
                           "billable_calls": 0, "mutations": 0,
                           "precondition": pre,
                           "instrument": "ApplyGuardrail — NOT RUN"}, store)
        return 2

    items = R.load_corpus(CORPUS, limit=args.n)
    spec = R.ArmSpec(case_id=CASE, family=FAMILY, corpus=CORPUS, guardrail_id=gid,
                     region=args.region, label="xregion", hit=hit_in_geography)
    (t,) = P.run_arms([spec], [items], run_id=run_id, is_smoke=is_smoke)

    rc = P.require_measured([t], is_smoke=is_smoke)
    if rc:
        return rc

    rows = t["rows"]
    arns = [(r.get("applied_details") or {}).get("guardrailArn", "") for r in rows]
    regions = Counter(region_of(a) or "(not disclosed)" for a in arns)
    partitions = Counter(partition_of(a) or "(not disclosed)" for a in arns)
    origins = Counter(
        ",".join((r.get("applied_details") or {}).get("guardrailOrigin") or [])
        or "(not disclosed)" for r in rows)
    ownership = Counter((r.get("applied_details") or {}).get("guardrailOwnership")
                        or "(not disclosed)" for r in rows)

    disclosed = [region_of(a) for a in arns if region_of(a)]
    out_of_geo = sorted({g for g in disclosed if g not in US_REGIONS})
    n_disclosed = len(disclosed)
    n_undisclosed = len(rows) - n_disclosed

    # The verdict. FALSE the moment any disclosed Region is out of geography; TRUE only if
    # at least one trial disclosed a Region AND every disclosed Region is in geography.
    # The `n_disclosed > 0` conjunct is load-bearing: an arm that disclosed nothing has an
    # empty out-of-geography set, and `not out_of_geo` alone would return TRUE from a run
    # that measured no geography at all.
    observed = (n_disclosed > 0) and not out_of_geo

    # `n=t["n_usable"]`, not `len(rows)`: this is the count the sealed planned_n of 60 is
    # checked against, so it must be the checkpoint's usable count — the same number every
    # other case's `n_met` is computed from — rather than a length this script measures for
    # itself. They agree on a clean run; they diverge exactly when trials failed, which is
    # the case where `n_met` matters. `n_trials` stays in the payload as the descriptive
    # count beside `n_disclosed`.
    o = P.obs_existence(
        CASE, observed, n=t["n_usable"],
        n_trials=len(rows), n_disclosed=n_disclosed, n_undisclosed=n_undisclosed,
        distinct_regions=sorted(set(disclosed)),
        out_of_geography=out_of_geo,
        profile=pre["profile_id"])
    rec = O.evaluate(o)

    # Only meaningful in the x=0 direction, and only over the DISCLOSED trials — the
    # denominator has to be the number of chances an out-of-geography Region actually had
    # to appear, not the number of calls made.
    ceiling = (O.ceiling_at_zero(n_disclosed, O.alpha_for(CASE))
               if n_disclosed and not out_of_geo else None)

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "billable_calls": t["n_usable"],
        "mutations": 0,
        "precondition": pre,
        "geography": {
            "in_geography_definition": sorted(US_REGIONS),
            "why_enumerated": ("us-gov-west-1 also starts with 'us-' and is a separate "
                               "partition; a prefix test would call a partition crossing "
                               "in-geography"),
            "regions_seen": dict(regions),
            "partitions_seen": dict(partitions),
            "out_of_geography": out_of_geo,
            "n_disclosed": n_disclosed,
            "n_undisclosed": n_undisclosed,
            "disclosure_rate": (n_disclosed / len(rows)) if rows else None,
        },
        "applied_guardrail": {
            "origins_seen": dict(origins),
            "ownership_seen": dict(ownership),
            "why_reported": ("guardrailOrigin distinguishes REQUEST from "
                             "ACCOUNT_ENFORCED and ORGANIZATION_ENFORCED. A trial served "
                             "by an enforced guardrail rather than the one this arm named "
                             "would otherwise be silently substituted, and Phase 5c opens "
                             "exactly that window"),
        },
        "zero_out_of_geography_ceiling": (
            {"x": 0, "n": n_disclosed, "one_sided_95_upper": ceiling,
             "reads_as": (f"if every one of {n_disclosed} disclosed trials was in "
                          f"geography, the rate of DISCLOSED out-of-geography serving is "
                          f"under {ceiling:.4f} at one-sided 95%")}
            if ceiling is not None else
            {"why_absent": ("a ceiling in the null direction is only defined at x=0; an "
                            "out-of-geography Region was disclosed, which falsifies the "
                            "claim outright and needs no interval")}),
        "what_true_does_not_prove": (
            "appliedGuardrailDetails.guardrailArn names the Region of the GUARDRAIL "
            "RESOURCE — the Region the request was sent to. Whether the cross-Region "
            "profile routed the underlying inference elsewhere is not documented to be "
            "disclosed. A run of all-in-geography readings is therefore consistent both "
            "with a profile that only routes within the US and with a profile that routes "
            "anywhere and never says so. This case tests DISCLOSED geography: the FALSE "
            "branch is fully decisive, the TRUE branch is bounded by the API"),
        "cloudtrail": {
            "collected": False,
            "named_by_oracle": True,
            "why_not": ("ApplyGuardrail is a data-plane operation and Bedrock guardrail "
                        "data events are not enabled on this account. Enabling them is a "
                        "Phase 2 testbed change with account-wide blast radius, and this "
                        "case is decidable without it — but the oracle names CloudTrail, "
                        "so its absence belongs on the face of the result"),
            "what_it_would_add": ("awsRegion per event and the resource ARNs the service "
                                  "touched — an independent reading of the same question "
                                  "that does not depend on the response body"),
        },
        "hit_rule": ("disclosed a Region AND that Region is in US_REGIONS. NOT a detection "
                     "reading: F8-6 counts Regions, and silence is not compliance"),
        "detection_context": {
            "n_intervened": sum(1 for r in rows if r["action"] != "NONE"),
            "n_any_detection": sum(1 for r in rows if r["detected_types"]),
            "regions_by_action": {
                a: dict(Counter(region_of((r.get("applied_details") or {})
                                          .get("guardrailArn", "")) or "(none)"
                                for r in rows if r["action"] == a))
                for a in sorted({r["action"] for r in rows})},
            "why_reported": ("descriptive, never the verdict. The cross-tab tests whether "
                             "an INTERVENED response discloses the same geography as a "
                             "NONE one — which is the reason this arm runs over a corpus "
                             "with both outcomes instead of 60 identical benign calls"),
        },
        "n_interpretation": (
            f"planned_n={want} from the sealed multilingual_cell, honoured as a count. "
            f"That cell's power argument is about interval disjointness for an "
            f"equivalence-shaped RECALL claim and does not transfer to a Region count, so "
            f"no power claim is made here; n_met={rec['n_met']} says the arm was the "
            f"pre-registered size and nothing more"),
        "no_power_claim": ("the only quantitative statement available is the "
                          "Clopper-Pearson ceiling above, and it bounds the rate of "
                          "DISCLOSED out-of-geography serving, not the rate of "
                          "out-of-geography serving"),
        "corpus_rationale": (
            f"{CORPUS} is used because it is exactly {want} items with a 54-attack/6-CLEAN "
            f"split already hashed by verify_corpora.py, so the arm sends a set of items a "
            f"file on disk names"),
        "instrument": ("GetGuardrail.crossRegionDetails (precondition) + ApplyGuardrail "
                       "assessments[].appliedGuardrailDetails.{guardrailArn, "
                       "guardrailOrigin, guardrailOwnership}"),
    }, store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
