#!/usr/bin/env python3
"""F8-8: can a non-en-US or enforce-mode Automated Reasoning request even be sent?

    python3 f8_regional/07_absent_surface.py --dry-run
    python3 f8_regional/07_absent_surface.py

§3.4, line 270: "Automated Reasoning checks are English (US) only." §3.2, line 182, adds
"detect mode only; English (US) only; available in 6 Regions; no streaming support". The
sealed oracle is EXISTENCE: TRUE if non-en-US and enforce-mode requests are **rejected**;
FALSE if **accepted**. Its family is `descriptive_no_test`.

WHY THIS CASE SENDS NOTHING TO AWS, AND WHY THAT IS THE STRONGER RESULT
----------------------------------------------------------------------
The oracle asks whether a request is rejected or accepted. Both answers presuppose the
request can be **constructed**. The finding is that it cannot: no field on any Automated
Reasoning operation can express a language, a locale or a mode. A rejection would be
evidence about a validator; an absent field is evidence about the API's shape, and it is
*stronger*, because a validator can be relaxed in a later release while a field that does
not exist cannot silently begin accepting values.

The observation is therefore a completed enumeration of the service model, and the mapping
onto the oracle is stated rather than assumed, because a reader is entitled to check it:

  * FALSE would require such a request to be **accepted**. Acceptance requires a request.
    No request exists. FALSE is unreachable **by construction** — not merely unobserved.
  * TRUE records the honest reading of "rejected": every such request is refused, at the
    earliest possible point, by the SDK, before serialisation. The payload says this in
    `verdict_reading` so nobody later quotes a bare TRUE as "we sent Japanese to Automated
    Reasoning and AWS rejected it". We sent nothing.

WHY THE SWEEP RUNS IN A SUBPROCESS UNDER `.venv-oracle`
-------------------------------------------------------
This case's entire content is *which fields the SDK model exposes*, so the sweep must run
under the pinned oracle SDK. But `.venv-oracle` carries botocore only — no numpy, no scipy
— so it cannot import `lib/oracle.py` and cannot evaluate a sealed oracle. The two halves
need different interpreters, so the sweep lives in `lib/ar_surface.py` (stdlib + botocore
only) and is executed here as a subprocess, its JSON read back and evaluated under the
interpreter that has scipy.

The version difference is not cosmetic. Measured, both ways, on this machine:

    botocore 1.43.67  ->  108 bedrock operations, 251 AR input members, 75 enums
    botocore 1.42.79  ->   98 bedrock operations, 244 AR input members, 72 enums

Same conclusion under both, but ten operations apart. Recording the older number as a fact
about AWS would be a fact about pip. F1-1 already established the concrete instance:
`InvokeGuardrailChecks` appears only at 1.43.30, `enforcementMode` at 1.43.32.

WHAT WOULD FALSIFY IT — four directions, each reporting what it EXAMINED
------------------------------------------------------------------------
An absence claim is only as good as the search that failed to find the thing:

  1. **Operation inventory** — every operation on `bedrock` and `bedrock-runtime` whose name
     contains "AutomatedReasoning". Establishes where the surface lives at all.
  2. **Member sweep** — every member of every input shape of those operations, walked
     recursively through structures, lists and maps, matched against a language/mode regex.
     This is the direction that would find `languageCode`, `locale`, `checkMode` or
     `enforcementMode` under any name containing those roots.
  3. **Enum sweep** — every enum in the *whole* `bedrock` model, searched for DETECT and
     ENFORCE. A mode could exist as a value on a differently-named field, which direction 2
     alone would miss.
  4. **Response sweep** — what the assessment surfaces back, since a mode that could not be
     requested might still be reported, and a report would mean the concept exists on the
     wire even where the request cannot name it.

Each direction reports its examined count, not just its hits, so a zero is distinguishable
from a search that ran over nothing (`feedback_zero_file_scan_is_error`).

THE REGEX HITS ARE CLASSIFIED, NOT DISCARDED
--------------------------------------------
The member regex is deliberately loose and it does match: four input paths, all of them
`addRuleFromNaturalLanguage` / `.naturalLanguage` on
`StartAutomatedReasoningPolicyBuildWorkflow` and `UpdateAutomatedReasoningPolicyAnnotations`.
Those are the *authoring* surface — the prose a policy author writes a rule in — not a
per-request language selector, and they are `string` with no enum.

A script that silently dropped them would be asserting the classification instead of
recording it, so every hit is classified against `AUTHORING_PATHS` and the count of
**unclassified** hits is what decides the verdict. A new match under a name this list does
not anticipate makes the surface *possibly* expressible and yields INCONCLUSIVE with the
path named — not a TRUE from a filter nobody re-read. Being wrong loudly beats being right
silently.

THE ONE THING THIS CASE CANNOT SETTLE
-------------------------------------
"English (US) only" may well be a claim about the *quality* of Automated Reasoning's
inference on non-English input. That is not what this oracle asks — it asks about acceptance
— and it is not measured here. Note that direction 4 finds `translation`, `naturalLanguage`
and `untranslatedPremises` in the response: the service reports a natural-language-to-logic
translation step, which is exactly where a language dependency would live and is a plausible
mechanism for the document's advice being sound for a reason the document does not give.
`what_true_does_not_prove` records this.

The Region half of the §3.2 bullet belongs to F8-1's nine-region probe in Phase 7; the
streaming and mode halves to F1-14. Neither is claimed here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
from evidence import EvidenceStore  # noqa: E402

FAMILY = "f8"
CASE = "F8-8"
SIBLING = "F1-14"

SWEEP = ROOT / "lib" / "ar_surface.py"
ORACLE_PY = ROOT / ".venv-oracle" / "bin" / "python"

# The oracle SDK floor. F1-1 established 1.43.32 as the first version exposing
# `enforcementMode` on CreatePolicy; an older botocore answers a question about pip.
MIN_BOTOCORE = (1, 43, 32)

# Input paths whose regex match is the POLICY-AUTHORING surface rather than a per-request
# language or mode selector. `addRuleFromNaturalLanguage.naturalLanguage` is the prose an
# author writes a rule in — a `string` with no enum, on a build-workflow operation, not on
# any invocation. Listed explicitly and by suffix so a NEW match under a name this list
# does not anticipate falls through to `unclassified` and forces INCONCLUSIVE.
AUTHORING_PATHS = (
    "addRuleFromNaturalLanguage",
    "addRuleFromNaturalLanguage.naturalLanguage",
)

AUTHORING_WHY = (
    "the policy-AUTHORING surface: the natural-language prose an author writes a rule in, "
    "typed `string` with no enum, on a build-workflow or annotation-update operation and on "
    "no invocation. A language SELECTOR would be an enum or a locale string on the request "
    "that performs a check, and no such member exists")


def _ver(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", s)[:3])


def run_sweep(region: str, *, interpreter: Path) -> dict[str, Any]:
    """Execute `lib/ar_surface.py --json` under `interpreter` and parse its output.

    A subprocess rather than an import, because the point is to load a DIFFERENT botocore
    than the one this process has. `check=False` and the returncode is recorded: a sweep that
    could not run must not be reported as a sweep that found nothing, which is the same
    defect as a redaction scan reading zero files and exiting 0.
    """
    if not interpreter.exists():
        return {"ok": False, "why": f"{interpreter} does not exist",
                "interpreter": str(interpreter)}
    proc = subprocess.run(
        [str(interpreter), str(SWEEP), "--json", "--region", region],
        capture_output=True, text=True, check=False, cwd=str(ROOT))
    if proc.returncode != 0:
        return {"ok": False, "why": f"sweep exited {proc.returncode}",
                "interpreter": str(interpreter),
                "returncode": proc.returncode, "stderr": proc.stderr[-2000:]}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "why": f"sweep output was not JSON: {exc}",
                "interpreter": str(interpreter), "stdout": proc.stdout[:2000]}
    return {"ok": True, "interpreter": str(interpreter), "data": data}


def classify_matches(matches: list[dict]) -> dict[str, Any]:
    """Split the member-sweep hits into authoring-surface and unclassified.

    `unclassified` is what decides the verdict. A hit this function cannot place is a member
    whose purpose nobody has read, and the honest answer is INCONCLUSIVE with the path
    named — not a TRUE produced by a filter that happened to swallow it.
    """
    authoring, unclassified = [], []
    for m in matches:
        path = m["path"]
        tail = path.rsplit("[]", 1)[-1].lstrip(".")
        if tail in AUTHORING_PATHS or any(
                path.endswith(a) or f".{a}." in path for a in AUTHORING_PATHS):
            authoring.append({**m, "classified_as": "policy_authoring_prose",
                              "why": AUTHORING_WHY})
        else:
            unclassified.append(m)
    return {
        "n_matches": len(matches),
        "authoring_surface": authoring,
        "n_authoring_surface": len(authoring),
        "unclassified": unclassified,
        "n_unclassified": len(unclassified),
        "classified_against": list(AUTHORING_PATHS),
        "why_classified_not_dropped": (
            "the regex is deliberately loose, so it matches the authoring surface. Dropping "
            "those matches silently would assert the classification instead of recording "
            "it; an unanticipated match therefore falls through to `unclassified` and "
            "forces INCONCLUSIVE with its path named"),
    }


def main(argv: list[str] | None = None) -> int:                     # noqa: C901
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            [("model-sweep:oracle-sdk", "lib/ar_surface.py under .venv-oracle", 0)],
            operations={},
            mutations=0, billable=False,
            extra=[
                "ZERO AWS calls. boto3.client loads a JSON service model off disk and opens "
                "no socket; no operation is invoked, no credential is used, and nothing "
                "leaves the machine",
                f"the sweep runs as a SUBPROCESS under {ORACLE_PY.relative_to(ROOT)} "
                f"(botocore 1.43.67), because .venv-oracle has no scipy and cannot import "
                f"lib/oracle.py — the two halves of this case need different interpreters",
                "measured both ways on this machine: 1.43.67 sees 108 bedrock operations / "
                "251 AR input members / 75 enums; 1.42.79 sees 98 / 244 / 72. Same "
                "conclusion, ten operations apart — recording the older number as a fact "
                "about AWS would be a fact about pip",
                "four independent directions: operation inventory over bedrock and "
                "bedrock-runtime; a recursive member sweep of every AutomatedReasoning "
                "input shape; an enum sweep of the WHOLE bedrock model for DETECT/ENFORCE; "
                "and the ApplyGuardrail response shape",
                "each direction reports what it EXAMINED as well as what it found — a scan "
                "reading zero shapes and reporting 'clean' is the defect "
                "feedback_zero_file_scan_is_error names",
                "the member regex DOES match (4 paths, all addRuleFromNaturalLanguage on "
                "the authoring surface). Matches are CLASSIFIED, not dropped: an "
                "unanticipated one forces INCONCLUSIVE with its path named",
                "FALSE is unreachable by construction — it needs such a request to be "
                "ACCEPTED, and no field exists in which to express one. TRUE records the "
                "honest reading of 'rejected': refused by the SDK before serialisation",
                f"the sibling case {SIBLING} carries the streaming and mode halves of the "
                f"same §3.2 bullet; 'available in 6 Regions' belongs to F8-1 in Phase 7",
            ])

    run_id = P.resolve_run(args)
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()

    result = run_sweep(args.region, interpreter=ORACLE_PY)
    ambient = A.sdk_versions()

    common: dict[str, Any] = {
        "run_id": run_id, "is_smoke": False,
        "billable_calls": 0, "mutations": 0, "aws_calls": 0,
        "ambient_sdk": ambient,
        "min_botocore_required": ".".join(map(str, MIN_BOTOCORE)),
        "sweep_interpreter": result.get("interpreter", str(ORACLE_PY)),
        "instrument": ("lib/ar_surface.py, run as a subprocess under .venv-oracle: the "
                       "botocore service models for bedrock and bedrock-runtime, read "
                       "locally. No operation is invoked"),
        "why_subprocess": (
            "this case's content is which fields the pinned SDK exposes, and .venv-oracle "
            "carries botocore only — no scipy — so it cannot import lib/oracle.py. The "
            "sweep and the oracle evaluation need different interpreters"),
        "sibling_case": {"case_id": SIBLING, "oracle": O.oracle_text(SIBLING),
                         "difference": ("F1-14 also asserts no streaming support and no "
                                        "enforce mode on the SDK surface; F8-8 asks only "
                                        "about acceptance of non-en-US and enforce-mode "
                                        "requests")},
    }

    # ---- the sweep could not run ---------------------------------------------------
    if not result["ok"]:
        print(f"FATAL: the model sweep did not run: {result['why']}", file=sys.stderr)
        rec = O.not_measured(
            CASE,
            f"the service-model sweep could not run under the pinned oracle SDK "
            f"({result['why']}), and a sweep that did not run must not be reported as a "
            f"sweep that found nothing",
            sweep=result)
        P.emit(CASE, rec, {**common, "sweep_failure": result,
                           "why_inconclusive": (
                               "an absence claim rests entirely on the search having "
                               "happened; a failed search reported as clean is the defect "
                               "feedback_zero_file_scan_is_error names")}, store)
        return 2

    data = result["data"]
    pinned = data["sdk"]
    got = _ver(pinned["botocore"])
    inventory = data["direction_1_operation_inventory"]
    members = data["direction_2_member_sweep"]
    enums = data["direction_3_enum_sweep"]
    responses = data["direction_4_response_sweep"]
    classified = classify_matches(members["matches"])

    common.update({
        "pinned_sdk": pinned,
        "sweep_python": data["python"],
        "direction_1_operation_inventory": inventory,
        "direction_2_member_sweep": members,
        "direction_2_classification": classified,
        "direction_3_enum_sweep": enums,
        "direction_4_response_sweep": responses,
    })

    print(f"sweep under botocore {pinned['botocore']} (ambient {ambient['botocore']})")
    for svc, v in inventory.items():
        print(f"  {svc}: {v['n_automated_reasoning']} AutomatedReasoning of "
              f"{v['n_operations_total']} operations")
    print(f"  members examined {members['n_members_examined']}   "
          f"matches {classified['n_matches']} "
          f"({classified['n_authoring_surface']} authoring, "
          f"{classified['n_unclassified']} unclassified)")
    for svc, v in enums.items():
        print(f"  {svc}: {v['n_enums_examined']} enums examined, {v['n_hits']} mode hits")

    if got < MIN_BOTOCORE:
        rec = O.not_measured(
            CASE,
            f"the sweep ran under botocore {pinned['botocore']}, older than the oracle pin "
            f"{'.'.join(map(str, MIN_BOTOCORE))}, so an absent field would be a fact about "
            f"this installation rather than about the API",
            sdk=pinned)
        P.emit(CASE, rec, {**common, "why_inconclusive": (
            "F1-1 established that the Automated Reasoning and enforcement surfaces appear "
            "only at 1.43.30/1.43.32; a sweep under an older model measures pip")}, store)
        return 2

    n_ar_ops = sum(v["n_automated_reasoning"] for v in inventory.values())
    if n_ar_ops == 0:
        # Not TRUE. With no Automated Reasoning surface at all, the absence of a language
        # field *within* it is vacuous — there is nothing for the document's sentence to be
        # about, and a TRUE here would be a scan over zero shapes.
        rec = O.not_measured(
            CASE,
            "this SDK exposes no AutomatedReasoning operation on either service, so the "
            "absence of a language or mode field within that surface is vacuous",
            inventory=inventory)
        P.emit(CASE, rec, {**common, "why_inconclusive": (
            "an absence claim requires a non-empty search space; zero AR operations means "
            "the sweep examined nothing that could have carried the field")}, store)
        return 2

    if not members["n_members_examined"]:
        rec = O.not_measured(
            CASE,
            f"the member sweep examined 0 members across {n_ar_ops} AutomatedReasoning "
            f"operations, so it cannot have looked where the field would be",
            member_sweep=members)
        P.emit(CASE, rec, {**common, "why_inconclusive": (
            "operations present but zero members walked means the walker failed, not that "
            "the surface is empty")}, store)
        return 2

    n_enum_hits = sum(v["n_hits"] for v in enums.values())
    if classified["n_unclassified"] or n_enum_hits:
        # A member or enum this script cannot place. The surface may be expressible, and
        # deciding acceptance would then require a live call this case does not make.
        paths = [m["path"] for m in classified["unclassified"]]
        rec = O.not_measured(
            CASE,
            f"the sweep found {classified['n_unclassified']} unclassified language/mode "
            f"member(s) {paths} and {n_enum_hits} mode enum hit(s). A present field makes "
            f"the request expressible, and acceptance can then only be decided by sending "
            f"one — which this instrument does not do",
            unclassified=classified["unclassified"],
            enum_hits={s: v["hits"] for s, v in enums.items() if v["hits"]})
        P.emit(CASE, rec, {**common, "why_inconclusive": (
            "the verdict turns on there being NO surface on which such a request could be "
            "built. An unplaced member is a member nobody has read, and asserting TRUE over "
            "it would be a filter deciding the finding")}, store)
        return 1

    # ---- the verdict --------------------------------------------------------------
    observed = True     # no unclassified member, no mode enum: the surface does not exist
    # n=0, and passed deliberately. F8-8 reads the service model shipped inside botocore
    # and makes no AWS call, so there are no trials: the finding is that a surface does not
    # exist in the model, which is not a rate over anything. The descriptive counts below
    # (members examined, enums examined) are the audit trail for that read, and putting one
    # of them in `n` would present a model walk as a sample. F8-8 has no sealed planned_n,
    # so 0 asserts no shortfall — a zero that is stated is a different fact from a zero
    # that defaulted, which is the whole reason `n` is required.
    o = P.obs_existence(
        CASE, observed, n=0,
        n_ar_operations=n_ar_ops,
        n_members_examined=members["n_members_examined"],
        n_matches=classified["n_matches"],
        n_matches_authoring_surface=classified["n_authoring_surface"],
        n_unclassified=classified["n_unclassified"],
        n_enums_examined=sum(v["n_enums_examined"] for v in enums.values()),
        n_enum_mode_hits=n_enum_hits,
        botocore=pinned["botocore"])
    rec = O.evaluate(o)

    P.emit(CASE, rec, {
        **common,
        "verdict_rule": (
            "TRUE iff every language/mode regex match on an AutomatedReasoning input shape "
            "classifies as the policy-authoring surface AND no enum anywhere in the bedrock "
            "model carries a mode value. Any unclassified match or mode enum makes the "
            "request expressible and yields INCONCLUSIVE, because acceptance would then "
            "have to be decided by sending one"),
        "verdict_reading": (
            "TRUE here means: every non-en-US and enforce-mode Automated Reasoning request "
            "is rejected, and rejected at the earliest possible point — the SDK cannot "
            "serialise one, because no field exists in which to express it. It does NOT "
            "mean we sent Japanese to Automated Reasoning and observed AWS refuse it. We "
            "sent nothing. FALSE is unreachable by construction, not merely unobserved: "
            "acceptance requires a request, and no request exists"),
        "what_true_does_not_prove": (
            "nothing about the QUALITY of Automated Reasoning's inference on non-English "
            "input. Direction 4 finds `translation`, `naturalLanguage` and "
            "`untranslatedPremises` in the response, so the service reports a "
            "natural-language-to-logic translation step — exactly where a language "
            "dependency would live, and a plausible mechanism for the document's advice "
            "being sound for a reason the document does not give. An API that accepted "
            "Japanese and translated it badly would satisfy this TRUE and leave the "
            "practical advice intact on grounds this case did not measure"),
        "why_no_aws_call": (
            "the oracle asks whether a request is rejected or accepted, and both presuppose "
            "the request can be constructed. The finding is that it cannot. An absent field "
            "is stronger evidence than a rejection: a validator can be relaxed in a later "
            "release, while a field that does not exist cannot silently begin accepting "
            "values"),
        "family_note": (
            f"family is {O.family_of(CASE)}, so no multiplicity correction and no power "
            f"claim: planned_n is None because there is no trial to count, and "
            f"n_met={rec['n_met']} is vacuous"),
        "expiry": (
            f"this is a statement about a MODEL, and models change. It is dated by botocore "
            f"{pinned['botocore']}; a later SDK exposing a language or mode field belongs in "
            f"AWS-BEHAVIOR-CHANGES.md, and re-running this script is how that is detected"),
    }, store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
