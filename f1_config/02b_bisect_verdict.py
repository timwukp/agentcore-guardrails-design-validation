#!/usr/bin/env python3
"""F1-1 and F1-2: turn the completed SDK bisect into two sealed verdicts.

    python3 f1_config/02b_bisect_verdict.py --dry-run
    python3 f1_config/02b_bisect_verdict.py

WHY THIS FILE EXISTS AT ALL
---------------------------
`f1_config/01_sdk_bisect.py` did the work — 14 wheels downloaded, 249 candidate releases
searched, monotonicity verified in three directions — and wrote `results/f1_sdk_bisect.json`.
It imports only the standard library. It never imports `lib/oracle.py` or `lib/phase1.py`,
and it never calls `P.emit`. So after it ran successfully, F1-1 and F1-2 had:

  * a 36 KB evidence file,
  * a written finding (`results/FINDING-F1-1.md`),
  * and **no record in `results/phase1/`** — which is the index the analysis phase reads.

That is a silent coverage hole of exactly the shape this project keeps finding: not a wrong
number, but a measured result no gate can see. The Phase 9 rollup enumerates
`results/phase1/`, so two TRUE verdicts would have been dropped from the report with nothing
failing and nothing to notice.

The fix is deliberately a SEPARATE file rather than an edit to `01_sdk_bisect.py`:

  * that script is the instrument that produced a dated result. Adding imports to it now
    would mean the code that generated `results/f1_sdk_bisect.json` is no longer the code in
    the tree — the F8-8 precedent already refused that ("that module is the instrument of a
    published case whose result is dated by the exact code that produced it").
  * its stdlib-only import list is a property worth keeping: it is the one script that must
    run without this project's venvs, because its whole job is to install fourteen OTHER
    botocores.
  * re-running the bisect to re-emit would re-download wheels for a result already settled
    and monotone.

So this file reads the artifact and does only the part that was missing: the mapping onto
the sealed oracle. It downloads nothing and calls no AWS API.

HOW THE BOUNDARY IS RE-DERIVED, AND WHY IT IS NOT JUST READ
-----------------------------------------------------------
A stored JSON is not evidence merely because it parses (`feedback_provenance_stamp_liveness`).
The artifact states `first_version_with_field: "1.43.32"` as a summary, and a summary that
disagrees with the rows it summarises is invisible when both are version strings — the
`feedback_label_must_match_computation` defect. So the boundary is recomputed from two
independent parts of the artifact and both must agree with the summary:

 1. **the recorded per-version surfaces** — the claimed first version's surface must
    actually carry the deciding field, and every probed version below it must lack it.
 2. **the monotonicity check's candidate indices** — this is the part that makes it a
    boundary rather than a lower bound. `checked` carries `{version, index,
    predicate_true}`, and 1.43.31 sits at index 212 with the field absent while 1.43.32 sits
    at index 213 with it present. **Adjacent indices in the 249-release candidate list**, so
    no release exists between them. Without the index adjacency, "first version exposing X"
    would only mean "lowest version we happened to download", and 235 of the 249 releases
    were never downloaded.

`predicate_true == expected` is required on every checked entry as well: the bisect predicted
each outcome before probing, and a mismatch means the surface is not monotone even if the
summary flag says it is.

WHAT THESE TWO VERDICTS ARE, AND WHAT THEY ARE NOT
--------------------------------------------------
Statements about the released SDK, not about the service. `enforcementMode` first appearing
at botocore 1.43.32 means the field became callable from Python at that release; it does not
date the server-side feature, which may have shipped earlier and been reachable by raw HTTP
the whole time. Both records say so.

Their real function is protective. DEV-P1-15 is the incident where an absence read on
botocore 1.42.79 was nearly published as an absence in the API. These two verdicts put a
dated floor under every other F1 case's "absent from the model" — and unlike every other F1
result, they cannot silently drift, because released wheels are immutable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
from evidence import EvidenceStore  # noqa: E402

FAMILY = "f1"
CASES = ("F1-1", "F1-2")
ARTIFACT = ROOT / "results" / "f1_sdk_bisect.json"

# The pinned oracle SDK floor. F1-1's own result is what SET this number, which is why this
# script checks the artifact's search range reaches it rather than assuming it does.
MIN_BOTOCORE = (1, 43, 32)

# Which recorded surface field decides each case, and which bisect predicate covers it.
SUBJECTS: dict[str, dict[str, Any]] = {
    "F1-1": {
        "predicate": "enforcement_mode",
        "field": "enforcement_mode_values",
        "why": ("F1-1's oracle is `enforcementMode` on CreatePolicy carrying the enum "
                "{ACTIVE, LOG_ONLY}, so the deciding surface field is the recorded enum "
                "VALUES and not merely the member's presence: a field present with a "
                "different value set would satisfy 'exists' and refute the oracle"),
        "companion_predicate": "definition_policy",
        "companion_field": "policy_definition_members",
        "companion_why": (
            "the same release adds `definition.policy` beside `definition.cedar`, taking "
            "PolicyDefinition from two arms to three. Reported with F1-1 because it is the "
            "same boundary and because F1-4's union arity — the platform pre-flight every "
            "gateway case depends on — is only three-armed at or above this version"),
    },
    "F1-2": {
        "predicate": "invoke_guardrail_checks",
        "field": "guardrail_check_members",
        "why": ("F1-2's oracle is presence of the OPERATION in bedrock-runtime. The "
                "recorded input members are the presence witness because an operation "
                "present with no members would be a broken model read rather than a "
                "shipped API"),
        "companion_predicate": None,
        "companion_field": None,
        "companion_why": "",
    },
}


def _ver(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in s.split(".")[:3] if p.isdigit())


def load_artifact() -> dict[str, Any]:
    if not ARTIFACT.exists():
        return {"ok": False, "why": f"{ARTIFACT.relative_to(ROOT)} does not exist; run "
                                    f"f1_config/01_sdk_bisect.py --bisect "
                                    f"--verify-monotone first"}
    try:
        data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "why": f"{ARTIFACT.relative_to(ROOT)} is not valid JSON: {exc}"}
    for key in ("search_range", "candidate_count", "bisects", "surfaces",
                "wheels_downloaded"):
        if key not in data:
            return {"ok": False,
                    "why": f"the artifact has no {key!r} key, so it was not written by a "
                           f"completed --bisect --verify-monotone run"}
    return {"ok": True, "data": data}


def re_derive_boundary(data: dict[str, Any], predicate: str,
                       field: str) -> dict[str, Any]:
    """Recompute a first-appearance boundary from the artifact's own rows.

    Three independent checks, all of which must hold, because each alone is satisfiable by
    an artifact that measured the wrong thing:

      * **surfaces agree** — the claimed version's recorded surface carries the field, and
        no probed version below it does.
      * **indices are adjacent** — the monotonicity check probed the release at index i-1
        and found the field absent, and the claimed version sits at index i. Adjacency in
        the 249-release candidate list is what upgrades "lowest version we downloaded" into
        "first version that has it"; 235 releases were never downloaded.
      * **predictions held** — every checked entry's `predicate_true` equals its `expected`.
        The bisect predicted each outcome before probing, so a mismatch means the surface is
        not monotone whatever the summary flag says.
    """
    b = (data["bisects"] or {}).get(predicate) or {}
    surfaces: dict[str, Any] = data["surfaces"]
    claimed = b.get("first_version_with_field")
    mono = b.get("monotonicity") or {}
    checked: list[dict] = list(mono.get("checked") or [])

    def has(ver: str) -> bool:
        s = surfaces.get(ver)
        return bool(s and s.get(field))

    present = sorted((v for v in surfaces if has(v)), key=_ver)
    absent = sorted((v for v in surfaces if not has(v)), key=_ver)
    out: dict[str, Any] = {
        "predicate": predicate, "field": field, "claimed_first": claimed,
        "surface_derived_first": present[0] if present else None,
        "n_versions_probed": len(surfaces),
        "n_present": len(present), "n_absent": len(absent),
        "present_versions": present, "absent_versions": absent,
        "monotone_flag": bool(mono.get("monotone")),
        "monotone_note": mono.get("note", ""),
        "checked": checked,
        "n_checked": len(checked),
        "probe_order": b.get("probe_order"),
        "conclusion": b.get("conclusion"),
    }

    if claimed is None:
        out.update(established=False,
                   why=f"the artifact records no first_version_with_field for {predicate}")
        return out

    # check 1 — the recorded surfaces
    out["surfaces_agree"] = (out["surface_derived_first"] == claimed)
    if not out["surfaces_agree"]:
        out.update(established=False, why=(
            f"the artifact's summary says {claimed} but the lowest PROBED version whose "
            f"recorded surface carries {field!r} is {out['surface_derived_first']}. A "
            f"summary that disagrees with the rows it summarises is a second label over the "
            f"same computation"))
        return out

    # check 3 — predictions held (cheap, and it gates the adjacency reading)
    mismatches = [c for c in checked
                  if bool(c.get("predicate_true")) != bool(c.get("expected"))]
    out["prediction_mismatches"] = mismatches
    if not checked:
        out.update(established=False, why=(
            f"verify_monotone recorded no checked versions for {predicate}, so 'first "
            f"version exposing it' means only 'lowest version we happened to download' — "
            f"and only {len(surfaces)} of the {data['candidate_count']} candidate releases "
            f"were downloaded"))
        return out
    if mismatches:
        out.update(established=False, why=(
            f"{len(mismatches)} monotonicity check(s) contradicted their own prediction "
            f"({[c['version'] for c in mismatches]}), so the surface is not monotone "
            f"whatever the summary flag says, and a first appearance is not well defined"))
        return out
    if not out["monotone_flag"]:
        out.update(established=False, why=(
            f"verify_monotone reported non-monotone for {predicate} "
            f"({out['monotone_note'] or 'no note'}). A field added, removed and re-added "
            f"makes 'the first version exposing it' meaningless"))
        return out

    # check 2 — index adjacency in the candidate list
    idx = {c["version"]: c["index"] for c in checked if "index" in c}
    out["candidate_indices"] = idx
    if claimed not in idx:
        out.update(established=False, why=(
            f"the claimed first version {claimed} has no candidate index in the "
            f"monotonicity record, so its position in the "
            f"{data['candidate_count']}-release list is unknown and adjacency cannot be "
            f"shown"))
        return out
    i = idx[claimed]
    below = [v for v, j in idx.items() if j == i - 1]
    out["candidate_index_of_first"] = i
    out["adjacent_below"] = below
    if not below:
        out.update(established=False, why=(
            f"no probed release sits at candidate index {i - 1}, immediately below "
            f"{claimed} at index {i}. Without the adjacent release, {claimed} is the lowest "
            f"version we DOWNLOADED that has the field, which is a search lower bound and "
            f"not a first appearance"))
        return out
    b_ver = below[0]
    out["adjacent_below_version"] = b_ver
    out["adjacent_below_has_field"] = has(b_ver)
    if has(b_ver):
        out.update(established=False, why=(
            f"{b_ver}, at candidate index {i - 1}, ALSO carries {field!r}, so {claimed} is "
            f"not the boundary"))
        return out

    out.update(established=True, why=(
        f"{claimed} (candidate index {i}) carries {field!r} and {b_ver} (candidate index "
        f"{i - 1}, immediately below it in the {data['candidate_count']}-release list) does "
        f"not. Monotone over {len(checked)} checked versions with every prediction held"))
    return out


def main(argv: list[str] | None = None) -> int:                          # noqa: C901
    ap = P.parser("F1-1/F1-2", __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        rc = 0
        for cid in CASES:
            rc |= P.dry_run_banner(
                cid,
                [("artifact-read", "results/f1_sdk_bisect.json (already produced)", 0)],
                operations={}, mutations=0, billable=False,
                extra=[
                    "ZERO AWS calls and ZERO wheel downloads. This script only maps an "
                    "artifact f1_config/01_sdk_bisect.py already produced onto the sealed "
                    "oracle — the step that script omitted because it imports no lib/ module",
                    "the boundary is RE-DERIVED three ways and all three must agree with "
                    "the artifact's own summary: the recorded per-version surfaces, the "
                    "candidate-index adjacency, and every monotonicity prediction holding",
                    "index adjacency is what makes it a boundary: 235 of the 249 candidate "
                    "releases were never downloaded, so without an adjacent probed release "
                    "below it, a 'first version' is only the lowest one we happened to test",
                    "these verdicts date the SDK, not the service: a field callable from "
                    "Python at 1.43.32 may have been reachable by raw HTTP earlier",
                ])
            print()
        return rc

    run_id = P.resolve_run(args)
    art = load_artifact()
    ambient = A.sdk_versions()
    common: dict[str, Any] = {
        "run_id": run_id, "is_smoke": False,
        "billable_calls": 0, "mutations": 0, "aws_calls": 0, "wheel_downloads": 0,
        "ambient_sdk": ambient,
        "artifact": str(ARTIFACT.relative_to(ROOT)),
        "instrument": ("f1_config/01_sdk_bisect.py: pip download of botocore wheels, "
                       "service-2.json.gz read out of each wheel, shape members asserted "
                       "offline. No AWS API is called and no wheel is installed"),
        "why_a_separate_script": (
            "01_sdk_bisect.py imports only the standard library and never calls P.emit, so "
            "its result never reached results/phase1/ — the index Phase 9 enumerates. It is "
            "not edited because it is the dated instrument of a published result, and "
            "because its stdlib-only import list is a property worth keeping: it is the one "
            "script that must run without this project's venvs, since its job is to install "
            "fourteen other botocores"),
        "what_these_verdicts_date": (
            "the released SDK, not the service. A field callable from Python at a given "
            "botocore may have been reachable by raw HTTP earlier; the bisect has no "
            "instrument that could see that and does not claim to"),
        "why_it_matters": (
            "DEV-P1-15 is the incident where an absence read on botocore 1.42.79 was nearly "
            "published as an absence in the API. These two verdicts put a dated floor under "
            "every other F1 case's 'absent from the model'"),
    }

    def abort(reason: str, **detail: Any) -> int:
        print(f"FATAL: {reason}", file=sys.stderr)
        for cid in CASES:
            rec = O.not_measured(cid, reason, **detail)
            P.emit(cid, rec, {**common, "why_inconclusive": (
                "the stored artifact is the only instrument here, and an artifact that "
                "cannot be shown trustworthy is not evidence merely because it parses")},
                EvidenceStore(run_id, FAMILY, cid), quiet=True)
        return 2

    if not art["ok"]:
        return abort(art["why"])

    d = art["data"]
    rng = d["search_range"]
    surfaces = d["surfaces"]

    if not surfaces:
        return abort("the artifact recorded zero per-version surfaces, so every field would "
                     "read as absent and the first appearance would be None — an absence "
                     "over an empty search space is not an absence", n_surfaces=0)

    hi = _ver(rng[1]) if isinstance(rng, (list, tuple)) and len(rng) == 2 else ()
    if hi < MIN_BOTOCORE:
        return abort(
            f"the bisect searched up to {rng[1]}, below the pinned oracle SDK "
            f"{'.'.join(map(str, MIN_BOTOCORE))}. A 'present' result would then be an "
            f"extrapolation past the searched range", search_range=rng)

    print(f"artifact: {d['candidate_count']} candidate releases, {len(surfaces)} probed via "
          f"{d['wheels_downloaded']} wheels, range {rng[0]}..{rng[1]}")

    common.update({
        "search_range": rng,
        "n_candidates": d["candidate_count"],
        "n_versions_probed": len(surfaces),
        "wheels_downloaded": d["wheels_downloaded"],
        "min_botocore_required": ".".join(map(str, MIN_BOTOCORE)),
    })

    stores = {cid: EvidenceStore(run_id, FAMILY, cid) for cid in CASES}
    for st in stores.values():
        st.write_environment()

    for cid, subj in SUBJECTS.items():
        boundary = re_derive_boundary(d, subj["predicate"], subj["field"])
        if not boundary["established"]:
            return abort(f"{cid}: {boundary['why']}", boundary=boundary)

    rc = 0
    for cid, subj in SUBJECTS.items():
        boundary = re_derive_boundary(d, subj["predicate"], subj["field"])
        first = boundary["claimed_first"]
        surf = surfaces[first]
        companion = (re_derive_boundary(d, subj["companion_predicate"],
                                        subj["companion_field"])
                     if subj["companion_predicate"] else None)
        o = P.obs_existence(
            cid, bool(surf.get(subj["field"])),
            # n=0. The bisect's sample size is releases probed, not trials: it is carried by
            # `n_versions_probed` and `wheels_downloaded`. Putting 14 in `n` would present a
            # wheel count as a trial count against a sealed planned_n these cases do not
            # have.
            n=0,
            first_version=first,
            candidate_index=boundary["candidate_index_of_first"],
            adjacent_below=boundary["adjacent_below_version"],
            deciding_field=subj["field"],
            deciding_value=surf.get(subj["field"]),
            boundary=boundary,
            companion_field=subj["companion_field"],
            companion_boundary=companion)
        payload = {
            **common,
            "why_this_field_decides": subj["why"],
            "verdict_rule": (
                "TRUE iff the deciding field is present at the claimed first version, no "
                "probed version below it carries the field, the release at the immediately "
                "preceding CANDIDATE INDEX was probed and lacks it, and every monotonicity "
                "prediction held. All four, because each alone is satisfiable by an "
                "artifact that measured the wrong thing"),
            "verdict_reading": boundary["why"],
            "deciding_value": surf.get(subj["field"]),
            "field_locations": surf.get("enforcement_mode_location"),
            "monotonicity_checked": boundary["checked"],
            "probe_order": boundary["probe_order"],
            "what_true_does_not_prove": (
                "when AWS shipped the feature. This dates the SDK surface. The service may "
                "have accepted the field earlier over raw HTTP, and the bisect has no "
                "instrument that could see that"),
            "expiry": (
                "a statement about released wheels, which are immutable — so unlike every "
                "other F1 case this result cannot silently drift. A LATER release removing "
                "the field would be an AWS-BEHAVIOR-CHANGES.md entry, not a correction here"),
        }
        if companion:
            payload["companion_reading"] = subj["companion_why"]
            payload["companion_boundary"] = companion
        P.emit(cid, O.evaluate(o), payload, stores[cid])

    print(f"\n{len(CASES)} case(s) emitted from the existing artifact; "
          f"0 AWS calls, 0 wheel downloads, $0.00")
    return rc


if __name__ == "__main__":
    sys.exit(main())
