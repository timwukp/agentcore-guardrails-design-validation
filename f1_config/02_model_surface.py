#!/usr/bin/env python3
"""F1 config surface: every F1 case the shipped service models can decide, and only those.

    python3 f1_config/02_model_surface.py --dry-run
    python3 f1_config/02_model_surface.py

Sixteen of the twenty-eight F1 cases name a *surface* — an enum, a required-field set, a
capability group, a union arity. `lib/f1_surface.py` enumerates all of them across the four
Bedrock service models in ten directions and returns counts, names and values. This script
is where those numbers meet the sealed oracles, and its whole discipline is the split
between two kinds of case:

  * **decided here** — the oracle's question is answerable from the model, in at least one
    direction, without sending anything. Eight cases: F1-4, F1-5, F1-7, F1-9, F1-14, F1-21,
    F1-22, F1-23.
  * **surface only** — the model establishes that the field exists and what its declared
    values are, and the oracle asks whether the SERVICE accepts something. Eight cases:
    F1-8, F1-10, F1-11, F1-12, F1-13, F1-16, F1-17, F1-20. Each gets an INCONCLUSIVE record
    naming the surface fact, the reason the model cannot close it, and the script that will.

The split is not a convenience. `botocore.validate.ParamValidator` enforces required
members, tagged-union arity and string/list **minimums** — and enforces no **maximum** and
no enum membership at all (direction 7: `sync`, `ASYNCHRONOUS` and `NOT_A_MODE` all pass
client-side). So a documented *minimum* or a documented *required field* is decidable
offline, and every documented *maximum* and every documented *value* needs a live call. A
script that read an enum and reported "the service accepts exactly these" would be
publishing the model's documentation as a measurement.

WHY THE VERDICTS ARE HERE AND THE SWEEP IS THERE
------------------------------------------------
`lib/f1_surface.py` deliberately decides nothing. Every mapping from a count onto a sealed
oracle is in this file, next to the oracle text it is compared against, so it can be
re-read. A sweep that returned verdicts would put the classification inside the instrument.

WHY THE SWEEP RUNS AS A SUBPROCESS — RE-DERIVED, BECAUSE THE OLD REASON IS FALSE
-------------------------------------------------------------------------------
The sibling script `f8_regional/07_absent_surface.py` says the sweep needs its own
interpreter because "`.venv-oracle` carries botocore only — no numpy, no scipy — so it
cannot import `lib/oracle.py`". That sentence is **no longer true and must not be copied**:
`.venv-oracle` carries numpy 2.5.2, scipy 1.18.0, PyYAML 6.0.3 and pytest 9.1.1, and every
module in `lib/` imports cleanly under it. Reusing the sentence here would have been an
unverified justification propagating by copy-paste, which is exactly the defect class this
project screens for (`feedback_prose_is_not_verified`).

The honest remaining reason is narrower and is about *naming the instrument*:

  * The content of this case family is which fields a **specific** botocore models. The
    interpreter that loaded the model is therefore part of the result, not scaffolding.
  * Running the sweep as a subprocess under a path this script pins makes that interpreter
    an argument recorded in the payload, instead of "whichever python launched the file".
    Ambient `python3` on this machine is botocore 1.42.79, under which `enforcementMode`
    and `InvokeGuardrailChecks` are simply absent (F1-1/F1-2) — an absence that is a fact
    about pip, and DEV-P1-15 is the incident where exactly that number got published.
  * If this script is itself run under `.venv-oracle`, the subprocess is a **redundancy
    rather than a necessity**, and `parent_is_oracle_interpreter` says so in the payload
    instead of leaving a reader to assume one or the other.

THE EXPECTED SETS ARE PARSED OUT OF THE SEAL, NOT TYPED IN
-----------------------------------------------------------
F1-5 and F1-7 are ENUM_EXACT, so the comparison needs an `expected_enum`. Writing
`("LOG_ONLY", "ENFORCE")` here would create a second, unchecked copy of a sealed value —
the defect `f3_efficacy/01_content_filter.py` avoids by deriving its arm sizes from the
corpus instead of from literals. So `expected_enum_from_seal` extracts the upper-snake
tokens from the sealed claim title and oracle text, and refuses (INCONCLUSIVE, loudly) if
the parse yields nothing. A seal edited to a different set changes the comparison; a seal
this parser cannot read stops the case rather than substituting a guess.

WHAT THE THREE DECIDED-IN-THE-**FALSE**-DIRECTION CASES REST ON
---------------------------------------------------------------
Absence and presence are not symmetric evidence, and the F8-8 precedent used only one of
them. F8-8's TRUE rested on an *absent* field: no request could be constructed, so
acceptance was unreachable by construction. F1-14's FALSE rests on a *present* one, which
is the stronger direction: its oracle says "FALSE if any is permitted", and a field that
exists, is settable, and has a matching slot on the response is what "permitted" means at
the SDK layer. `ConverseStream` accepts `guardrailConfig.guardrailIdentifier` and models
132 Automated-Reasoning paths under `stream.metadata.trace.guardrail.*` — the same
`GuardrailTraceAssessment` shape `Converse` uses — so the document's "no streaming support"
is contradicted by the shipped model, not by an inference about it.

WHAT NONE OF THIS MEASURES
--------------------------
Whether AWS *performs* the thing the field names. A slot on a response shape is evidence
the wire format carries the concept, not evidence the service fills it. Every verdict below
carries the sentence that says which of the two it is.
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

FAMILY = "f1"

SWEEP = ROOT / "lib" / "f1_surface.py"
ORACLE_PY = ROOT / ".venv-oracle" / "bin" / "python"

# The oracle SDK floor, from F1-1: 1.43.32 is the first botocore exposing `enforcementMode`
# on CreatePolicy and `definition.policy`. Below it, an absence is a fact about pip.
MIN_BOTOCORE = (1, 43, 32)

# Cases this script decides. Each is answerable from the shipped model in at least one
# direction; the per-case block below states which direction and what it does not cover.
CASES = ("F1-4", "F1-5", "F1-7", "F1-9", "F1-14", "F1-21", "F1-22", "F1-23")

# Cases where the model establishes the surface and the oracle asks about SERVICE
# acceptance. Value = (what the model settled, why the model cannot close it, successor).
# Written as data so the deferral is a row in a record rather than a sentence in a report:
# a case with no file in results/phase1/ is indistinguishable from a case nobody triaged.
SURFACE_ONLY: dict[str, tuple[str, str, str]] = {
    "F1-8": (
        "GuardrailChecksPromptAttackCategory enumerates all three subtypes "
        "(JAILBREAK, PROMPT_INJECTION, PROMPT_LEAKAGE) on bedrock-runtime",
        "the oracle asks whether the guardrails-in-policy `PromptAttack` CONSTRUCTOR "
        "accepts each subtype, and a Cedar body travels as an opaque "
        "`definition.cedar.statement` string. No shape in any of the four models describes "
        "the grammar inside it, so acceptance is a server-side fact by construction",
        "f1_config/04_policy_grammar.py (CreatePolicy per subtype against a live engine)"),
    "F1-10": (
        "GuardrailTopicDefinition is string {min: 1, max: 200} with NO tier dependence, and "
        "GuardrailTopicsTierConfig carries only `tierName`",
        "ParamValidator enforces `min` and not `max`, so the 200/1,000 boundary the "
        "document states can only be settled by a CreateGuardrail that the service accepts "
        "or rejects. F8-5 already measured a sibling oracle FALSE and its STANDARD half was "
        "confounded twice — a crossRegion prerequisite and a ThrottlingException",
        "f1_config/05_live_boundaries.py (tier x length, with crossRegionConfig supplied "
        "and calls paced)"),
    "F1-11": (
        "GuardrailContentFilterConfig requires both inputStrength and outputStrength and "
        "carries inputAction/outputAction/inputEnabled/outputEnabled; "
        "GuardrailPiiEntityConfig carries inputAction/outputAction beside `action`",
        "the oracle's decisive half is 'read back distinct', which is a GetGuardrail "
        "response and cannot be produced by reading an input shape",
        "f1_config/05_live_boundaries.py (asymmetric CreateGuardrail then GetGuardrail)"),
    "F1-12": (
        "GuardrailStreamProcessingMode enumerates ['sync', 'async'] with no declared "
        "default, and NO enum in 271 enums / 1,076 enum values across the four services "
        "carries the document's tokens SYNCHRONOUS or ASYNCHRONOUS",
        "the model's value set is documentation, not enforcement: direction 7 proved "
        "ParamValidator performs no enum membership check, so `ASYNCHRONOUS` reaches the "
        "service and only the service can accept or reject it. The second half — which mode "
        "applies when the field is OMITTED — is a server default that no model declares",
        "f1_config/05_live_boundaries.py (ConverseStream with the documented token, with "
        "'async', and with the field omitted)"),
    "F1-13": (
        "GuardrailContextualGroundingFilterConfig requires only {type, threshold}; "
        "GuardrailTextBlock.text is a bare String with empty metadata; the documented "
        "100,000 / 1,000 / 5,000 character limits appear on no shape in the model",
        "a limit absent from the model cannot be checked against the model. The sealed "
        "binding says so itself: its thresholds are `limits_by_reference` to the document",
        "f1_config/05_live_boundaries.py (ApplyGuardrail at each limit and limit+1)"),
    "F1-16": (
        "GatewayInterceptionPoint enumerates ['REQUEST', 'RESPONSE'] and 50 interceptor "
        "member paths exist on bedrock-agentcore-control across "
        "Create/Update/GetGateway — while the `Interceptor` operation group has ZERO hits, "
        "so interceptors are gateway configuration and not a service of their own",
        "the oracle's second half is 'and fire', which is an invocation result",
        "f5_redteam / Phase 4 gateway work (an interceptor Lambda on the echo target)"),
    "F1-17": (
        "`suppressOutput` appears in NONE of the 14,774 member paths, 3,432 shape names or "
        "350 operation names of the four services",
        "and that absence proves nothing about the claim. `suppressOutput` is a Cedar policy "
        "EFFECT, and Cedar bodies travel as an opaque string — so its absence from the model "
        "is EXPECTED whether the effect exists or not. This is the one direction in the "
        "sweep whose zero is not evidence, and recording the examined counts is what lets "
        "the case say so instead of reading the zero as a finding",
        "f1_config/04_policy_grammar.py (CreatePolicy with a suppressOutput effect) then an "
        "end-to-end tool call through the echo Lambda"),
    "F1-20": (
        "GuardrailChecksContentBlockList is a list with {min: 1} and NO max, as is "
        "GuardrailChecksMessageList — the documented cap of 10 blocks per message is absent "
        "from the model",
        "ParamValidator enforces `min` and not `max`, so an 11-block request is "
        "constructible and reaches the service; the boundary is server-side",
        "f1_config/05_live_boundaries.py (InvokeGuardrailChecks at 10 and 11 blocks)"),
}

# Cases with no claim row in `claims/triage.csv`, and the sealed reason. Quoted verbatim
# from `claims/triage_rules.PLATFORM_CASES` rather than paraphrased, because the whole point
# of that table is that an experiment answering no claim must be visible.
PLATFORM_CASE_IDS = ("F1-4", "F1-21")

# Substring false positives in the mode-token scan. Each is a real enum value that contains
# a scanned token and means something else. Listed so a NEW hit under a name this table does
# not anticipate falls through to `unclassified` and forces INCONCLUSIVE — the pattern
# `f8_regional/07_absent_surface.py` uses, and for the same reason: being wrong loudly beats
# being right silently.
MODE_SCAN_FALSE_POSITIVES: dict[str, str] = {
    "TargetStatus": (
        "a gateway-target lifecycle enum. SYNCHRONIZING / SYNCHRONIZE_UNSUCCESSFUL / "
        "SYNCHRONIZE_PENDING_AUTH contain the token SYNC and describe target "
        "synchronisation, not a guardrail stream-processing mode"),
    "GuardrailOrigin": (
        "where a guardrail came from. ACCOUNT_ENFORCED / ORGANIZATION_ENFORCED contain the "
        "token ENFORCE and describe account- and organization-level enforcement (the F5-9 "
        "surface), not an Automated Reasoning detect-vs-enforce mode"),
    "GatewayPolicyEngineMode": (
        "a LEGITIMATE hit, and it is F1-5's own subject: ENFORCE is a policy-engine mode. "
        "It is listed here so the ENFORCE token's hit count is fully accounted for, not to "
        "excuse it"),
    "GuardrailStreamProcessingMode": (
        "a LEGITIMATE hit and F1-12's own subject: the SYNC and ASYNC tokens match its two "
        "values `sync` and `async`. It is in this table because the table's job is to "
        "account for every hit, not to hold only the false ones — and it is the reason the "
        "F1-12 verdict below reads the ENUM directly instead of reading a hit count: the "
        "hit proves a stream-processing mode enum exists, and F1-12 asks whether its values "
        "are the document's SYNCHRONOUS / ASYNCHRONOUS, which they are not"),
}


def _ver(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", s)[:3])


def expected_enum_from_seal(case_id: str) -> tuple[str, ...]:
    """The expected value set for an ENUM_EXACT case, read out of the sealed row.

    Not a literal in this file. `claims/triage.csv` and `claims/triage_rules.py` are bound
    artifacts pinned by sha256 in `PREREGISTRATION.yaml`, and the expected set of an
    exact-set oracle IS the sealed claim — so typing it again here would create a second
    copy that no hash covers and that could drift from the seal while both looked right.
    `f3_efficacy/01_content_filter.py` makes the same choice for its arm sizes and states
    the same reason: "a literal here would be a second, unchecked copy of the sealed corpus
    size".

    Both fields are scanned because the seal does not put the tokens in a fixed place: F1-7
    carries them in the oracle text (`{VIOLENCE,...,PROMPT_ATTACK}`) and F1-5 carries them
    in the claim title (`Engine mode enum is LOG_ONLY|ENFORCE`) while its oracle text says
    only "exactly these two".

    TRUE and FALSE are excluded because every oracle text begins with them. An empty parse
    raises rather than returning `()`: an ENUM_EXACT comparison against an empty expected
    set would report every observed value as `unexpected` and hand back a confident FALSE
    from a parser that found nothing.
    """
    row = O.cases()[case_id]
    text = f"{row[1]} {row[3]}"
    tokens = [t for t in re.findall(r"\b[A-Z][A-Z_]{2,}\b", text)
              if t not in {"TRUE", "FALSE", "SDK", "API"}]
    out = tuple(dict.fromkeys(tokens))            # de-dup, order preserved
    if not out:
        raise ValueError(
            f"{case_id}: no upper-snake token could be parsed out of the sealed row "
            f"{text!r}. An ENUM_EXACT case with an empty expected set would report every "
            f"observed value as unexpected and return FALSE from a parser that read nothing")
    return out


def run_sweep(region: str, *, interpreter: Path) -> dict[str, Any]:
    """Execute `lib/f1_surface.py --json` under `interpreter` and parse its output.

    `check=False`, and the returncode is part of the result: a sweep that could not run must
    not be reported as a sweep that found nothing. That is the same defect as a redaction
    scan reading zero files and exiting 0 (`feedback_zero_file_scan_is_error`), and every
    absence in the ten directions is quoted against a count this sweep produced.
    """
    if not interpreter.exists():
        return {"ok": False, "why": f"{interpreter} does not exist",
                "interpreter": str(interpreter)}
    proc = subprocess.run(
        [str(interpreter), str(SWEEP), "--json", "--region", region],
        capture_output=True, text=True, check=False, cwd=str(ROOT))
    if proc.returncode != 0:
        return {"ok": False, "why": f"sweep exited {proc.returncode}",
                "interpreter": str(interpreter), "returncode": proc.returncode,
                "stderr": proc.stderr[-2000:]}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "why": f"sweep output was not JSON: {exc}",
                "interpreter": str(interpreter), "stdout": proc.stdout[:2000]}
    return {"ok": True, "interpreter": str(interpreter), "data": data}


def classify_mode_hits(per_service: dict[str, Any]) -> dict[str, Any]:
    """Split direction 9's mode-token hits into accounted-for and unclassified.

    Direction 9 scans 271 enums / 1,076 enum values for SYNCHRONOUS, ASYNCHRONOUS, SYNC,
    ASYNC, DETECT and ENFORCE. It gets five hits, and **two of the five are substring
    accidents** — `TargetStatus.SYNCHRONIZING` contains SYNC, `GuardrailOrigin
    .ACCOUNT_ENFORCED` contains ENFORCE. Counting them would let F1-12 report the
    document's tokens as present because a gateway target was synchronising.

    Every hit is classified against `MODE_SCAN_FALSE_POSITIVES` and the count of
    *unclassified* hits is what a verdict may use. A hit on a shape this table does not
    name is a hit nobody has read, and the honest answer is INCONCLUSIVE with the shape
    named.
    """
    accounted: list[dict] = []
    unclassified: list[dict] = []
    for svc, v in per_service.items():
        for token, entries in (v.get("hits") or {}).items():
            for e in entries:
                row = {"service": svc, "token": token, "shape": e["shape"],
                       "matched_values": e["matched_values"],
                       "all_values": e["all_values"]}
                why = MODE_SCAN_FALSE_POSITIVES.get(e["shape"])
                if why:
                    accounted.append({**row, "why": why})
                else:
                    unclassified.append(row)
    return {
        "n_hits": len(accounted) + len(unclassified),
        "accounted": accounted, "n_accounted": len(accounted),
        "unclassified": unclassified, "n_unclassified": len(unclassified),
        "classified_against": sorted(MODE_SCAN_FALSE_POSITIVES),
        "why_classified_not_dropped": (
            "two of the five hits are substring accidents on enums that mean something else "
            "(TargetStatus.SYNCHRONIZING contains SYNC; GuardrailOrigin.ACCOUNT_ENFORCED "
            "contains ENFORCE) and three are legitimate. Dropping the accidents silently "
            "would assert the classification instead of recording it; a hit on an unlisted "
            "shape therefore falls through to `unclassified` and forces INCONCLUSIVE with "
            "the shape named. Every hit is accounted for either way, which is what makes "
            "the zero-unclassified guard meaningful"),
        "documented_tokens_present": sorted(
            {h["token"] for h in unclassified} |
            {h["token"] for h in accounted
             if h["token"] in {"SYNCHRONOUS", "ASYNCHRONOUS"}}),
    }


def _all_case_ids() -> tuple[str, ...]:
    return tuple(CASES) + tuple(SURFACE_ONLY)


def _abort(reason: str, common: dict, run_id: str, *, rc: int = 2,
           **detail: Any) -> int:
    """Emit a not-measured record for EVERY case this script owns, then return `rc`.

    All of them, not just the decided eight. A guard that fired means the instrument did
    not run, and a surface-only case whose deferral record was written from a failed sweep
    would be quoting surface facts it never read.
    """
    print(f"FATAL: {reason}", file=sys.stderr)
    for cid in _all_case_ids():
        rec = O.not_measured(cid, reason, **detail)
        P.emit(cid, rec, {**common, "why_inconclusive": (
            "the sweep is the only instrument this script has; a failed sweep reported as "
            "a clean surface read is the defect feedback_zero_file_scan_is_error names")},
            EvidenceStore(run_id, FAMILY, cid), quiet=True)
    return rc


def main(argv: list[str] | None = None) -> int:                          # noqa: C901
    ap = P.parser("F1-surface", __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        rc = 0
        for cid in _all_case_ids():
            rc |= P.dry_run_banner(
                cid,
                [("model-sweep:oracle-sdk", "lib/f1_surface.py under .venv-oracle", 0)],
                operations={}, mutations=0, billable=False,
                extra=[
                    "ZERO AWS calls. boto3.client loads four JSON service models off disk "
                    "and opens no socket; no operation is invoked, no credential is used",
                    ("DECIDED here from the model" if cid in CASES else
                     f"SURFACE ONLY — deferred to {SURFACE_ONLY[cid][2]}"),
                    f"the sweep runs as a SUBPROCESS under "
                    f"{ORACLE_PY.relative_to(ROOT)} so the interpreter that loaded the "
                    f"model is a recorded argument, not whatever launched this file. "
                    f"SYSTEM python3 and .venv-baseline both carry botocore 1.42.79, under "
                    f"which enforcementMode and InvokeGuardrailChecks are simply absent, so "
                    f"the pin is what separates a fact about the API from a fact about pip",
                    "ten directions, each reporting what it EXAMINED as well as what it "
                    "found: 4 services / 350 operations / 3,432 shape names / 14,774 "
                    "member paths / 271 enums / 1,076 enum values",
                    "ParamValidator enforces required members, tagged-union arity and "
                    "minimums; it enforces NO maximum and NO enum membership. So every "
                    "documented minimum and required field is decidable here and every "
                    "documented maximum and value needs a live call",
                ])
            print()
        return rc

    run_id = P.resolve_run(args)
    result = run_sweep(args.region, interpreter=ORACLE_PY)
    ambient = A.sdk_versions()

    common: dict[str, Any] = {
        "run_id": run_id, "is_smoke": False,
        "billable_calls": 0, "mutations": 0, "aws_calls": 0,
        "ambient_sdk": ambient,
        "min_botocore_required": ".".join(map(str, MIN_BOTOCORE)),
        "sweep_interpreter": result.get("interpreter", str(ORACLE_PY)),
        "parent_interpreter": sys.executable,
        "parent_is_oracle_interpreter": Path(sys.executable).resolve() ==
                                        ORACLE_PY.resolve(),
        "instrument": ("lib/f1_surface.py, run as a subprocess under .venv-oracle: the "
                       "botocore service models for bedrock, bedrock-runtime, "
                       "bedrock-agentcore-control and bedrock-agentcore, read locally in "
                       "ten directions. No operation is invoked"),
        "why_subprocess": (
            "so the interpreter that loaded the model is a RECORDED ARGUMENT rather than "
            "whichever python launched this file: the content of these cases is which "
            "fields a specific botocore models, and system python3 and .venv-baseline both "
            "carry 1.42.79, "
            "under which enforcementMode and InvokeGuardrailChecks are absent — an absence "
            "that is a fact about pip (F1-1, DEV-P1-15). It is NOT because .venv-oracle "
            "cannot evaluate an oracle: that venv carries numpy 2.5.2 and scipy 1.18.0 and "
            "imports every lib/ module cleanly, so the rationale in "
            "f8_regional/07_absent_surface.py is stale prose and was re-derived rather "
            "than copied. `parent_is_oracle_interpreter` records whether the subprocess is "
            "a necessity or a redundancy on this run"),
        "client_side_enforcement": (
            "botocore.validate.ParamValidator enforces required members, tagged-union "
            "arity and string/list MINIMUMS. It enforces no maximum and performs no enum "
            "membership check (direction 7: `sync`, `ASYNCHRONOUS` and `NOT_A_MODE` all "
            "pass). Every documented minimum and required field is therefore decidable "
            "offline; every documented maximum and value is not"),
    }

    if not result["ok"]:
        return _abort(
            f"the F1 service-model sweep could not run under the pinned oracle SDK "
            f"({result['why']}), and a sweep that did not run must not be reported as a "
            f"sweep that found nothing",
            {**common, "sweep_failure": result}, run_id, sweep=result)

    d = result["data"]
    pinned = d["sdk"]
    got = _ver(pinned["botocore"])
    inv = d["direction_1_operation_inventory"]
    enums = d["direction_2_enum_reads"]
    caps = d["direction_3_capability_groups"]
    tokens = d["direction_4_token_scan"]
    req = d["direction_5_required_fields"]
    union = d["direction_6_union_probe"]
    enforce7 = d["direction_7_enum_enforcement"]
    limits = d["direction_8_shape_limits"]
    modes = d["direction_9_mode_enum_scan"]
    ar = d["direction_10_ar_streaming_reach"]
    mode_hits = classify_mode_hits(modes["per_service"])

    common.update({
        "pinned_sdk": pinned, "sweep_python": d["python"],
        "services_available": d["services_available"],
        "services_unavailable": d["services_unavailable"],
        "examined": {
            "n_services": len(d["services_available"]),
            "n_operations": tokens["examined_total"]["n_operations"],
            "n_shape_names": tokens["examined_total"]["n_shape_names"],
            "n_member_paths": tokens["examined_total"]["n_member_paths"],
            "n_enums": modes["examined_total"]["n_enums"],
            "n_enum_values": modes["examined_total"]["n_enum_values"],
        },
        "direction_9_classification": mode_hits,
        "why_no_aws_call": d["why_no_aws_call"],
    })

    print(f"sweep under botocore {pinned['botocore']} (ambient {ambient['botocore']}, "
          f"parent {'IS' if common['parent_is_oracle_interpreter'] else 'is NOT'} the "
          f"oracle interpreter)")
    for svc, v in inv.items():
        print(f"  {svc:28s} {v['n_operations']:>4d} operations  "
              f"{v['n_shapes']:>4d} shapes  api {v['api_version']}")
    print(f"  examined: {common['examined']['n_member_paths']} member paths, "
          f"{common['examined']['n_enums']} enums, "
          f"{common['examined']['n_enum_values']} enum values")
    print(f"  mode-token hits {mode_hits['n_hits']} "
          f"({mode_hits['n_accounted']} accounted, "
          f"{mode_hits['n_unclassified']} unclassified)")

    # ---- guards ---------------------------------------------------------------------
    if got < MIN_BOTOCORE:
        return _abort(
            f"the sweep ran under botocore {pinned['botocore']}, older than the oracle pin "
            f"{'.'.join(map(str, MIN_BOTOCORE))}. F1-1 established that enforcementMode and "
            f"definition.policy first appear at 1.43.32 and InvokeGuardrailChecks at "
            f"1.43.30, so an absent field under an older model measures pip",
            {**common, "sdk": pinned}, run_id, sdk=pinned)

    if d["services_unavailable"]:
        return _abort(
            f"the sweep could not load {sorted(d['services_unavailable'])}. This project "
            f"has twice published an absence after searching one service when the surface "
            f"was on another, so a partial sweep may not produce a verdict",
            common, run_id, unavailable=d["services_unavailable"])

    if not tokens["examined_total"]["n_member_paths"]:
        return _abort(
            "the token scan walked 0 member paths, so it cannot have looked where any of "
            "these fields would be: operations present with zero members walked means the "
            "walker failed, not that the surface is empty",
            common, run_id, examined=tokens["examined_total"])

    if not modes["examined_total"]["n_enums"]:
        return _abort(
            "the mode-enum scan examined 0 enums; a zero-hit result over a zero-size "
            "search space is not an absence",
            common, run_id, examined=modes["examined_total"])

    if mode_hits["n_unclassified"]:
        return _abort(
            f"the mode-token scan found {mode_hits['n_unclassified']} hit(s) on enums this "
            f"script cannot place: "
            f"{[h['shape'] for h in mode_hits['unclassified']]}. An unplaced hit is an enum "
            f"nobody has read, and F1-12's and F1-14's verdicts both turn on which mode "
            f"tokens exist",
            common, run_id, rc=1, unclassified=mode_hits["unclassified"])

    stores = {cid: EvidenceStore(run_id, FAMILY, cid) for cid in _all_case_ids()}
    for st in stores.values():
        st.write_environment()

    # The reason F1-4 and F1-21 have no claim row is READ from the sealed module rather
    # than restated here, for the same reason `expected_enum_from_seal` parses instead of
    # hard-coding: a paraphrase of a sealed justification is an unchecked second copy, and
    # `claims/triage_rules.py` is pinned by sha256 in PREREGISTRATION.yaml.
    sys.path.insert(0, str(ROOT / "claims"))
    import triage_rules as TR                                       # noqa: E402
    platform_note = {
        cid: ("this case has NO row in claims/triage.csv, by design. "
              "claims/triage_rules.PLATFORM_CASES states why, verbatim: "
              + TR.PLATFORM_CASES[cid])
        for cid in PLATFORM_CASE_IDS}

    # =================================================================================
    # F1-4 — PolicyDefinition union arity
    # =================================================================================
    probes = union["probes"]
    controls_ran = all(p["control_finding_present"] for p in probes.values())
    exactly_one = bool(probes["both_arms"]["union_finding"])
    at_least_one = bool(probes["neither_arm"]["union_finding"])
    singles_pass = not (probes["cedar_only"]["union_finding"]
                        or probes["policy_only"]["union_finding"])
    o4 = P.obs_existence(
        "F1-4", controls_ran and exactly_one and at_least_one and singles_pass,
        # n=0, passed deliberately. The four probes are validator runs against a shape, not
        # trials against a service: there is no rate here and no denominator a reader could
        # check a sealed n against. F1-4 has no sealed planned_n, so 0 asserts no shortfall.
        n=0,
        definition_members=union["definition_members"],
        metadata_says_union=union["metadata_says_union"],
        control_finding_in_all_four_probes=controls_ran,
        both_arms_rejected=exactly_one,
        neither_arm_rejected=at_least_one,
        single_arms_accepted=singles_pass,
        probes=probes)
    P.emit("F1-4", O.evaluate(o4), {
        **common,
        "no_claim_row": platform_note["F1-4"],
        "verdict_rule": (
            "TRUE iff all four probes carry the deliberate control finding (proving the "
            "validator ran at all), the both-arms probe is rejected, the neither-arm probe "
            "is rejected, and each single arm passes. The control is a policyEngineId of "
            "length 1 against a min of 12: without it, a probe that produced no finding "
            "would be indistinguishable from a validator that never executed"),
        "verdict_reading": (
            "the union is a THREE-arm tagged union — cedar, policyGeneration, policy — and "
            "botocore enforces both halves of 'exactly one': "
            f"{probes['both_arms']['union_finding']} and "
            f"{probes['neither_arm']['union_finding']}. Rejected at the SDK, before "
            "serialisation, so a both-arms request cannot be sent at all"),
        "what_true_does_not_prove": (
            "that the SERVICE accepts either single arm. Client-side, neither is rejected; "
            "the `cedar` arm is separately corroborated live — Phase 2 created "
            "grx_pol_baseline_<runid>_v2 through it — but nothing in this project has yet "
            "sent a `policy` arm to the service, and the oracle's FALSE branch includes "
            "'either single arm is rejected'. That branch is untested for `policy`"),
        "why_this_matters_operationally": (
            "F1-4 is a platform pre-flight, not a claim: every F1-F5 gateway test has to "
            "know which arm to send, and sending both would fail every one of them for a "
            "reason unrelated to what they measure"),
        "expiry": (f"a statement about a MODEL, dated by botocore {pinned['botocore']}; a "
                   f"later release adding a fourth arm belongs in AWS-BEHAVIOR-CHANGES.md"),
    }, stores["F1-4"])

    # =================================================================================
    # F1-5 — GatewayPolicyEngineMode is exactly {LOG_ONLY, ENFORCE}
    # =================================================================================
    e5 = enums["GatewayPolicyEngineMode"]
    want5 = expected_enum_from_seal("F1-5")
    o5 = O.Observation(case_id="F1-5", observed_enum=list(e5["values"]),
                       expected_enum=list(want5), n_attempted=0, n_usable=0,
                       detail={"shape": "GatewayPolicyEngineMode",
                               "service": e5["service"], "present": e5["present"]})
    P.emit("F1-5", O.evaluate(o5), {
        **common,
        "expected_enum_provenance": (
            f"parsed from the sealed claim row, not typed here: {want5}. "
            f"claims/triage.csv and claims/triage_rules.py are bound artifacts pinned by "
            f"sha256 in PREREGISTRATION.yaml, so a literal in this file would be a second "
            f"copy no hash covers"),
        "where_the_mode_is_set": (
            "on CreateGateway, not on CreatePolicyEngine. `CreatePolicyEngine` requires "
            "only `name` (its other members are clientToken, description, "
            "encryptionKeyArn, tags); the mode lives at "
            "`CreateGateway.policyEngineConfiguration.mode`, which is REQUIRED whenever "
            "policyEngineConfiguration is supplied, alongside `.arn`. The sealed method "
            "says 'service model read + CreatePolicyEngine round-trip', and the round-trip "
            "would not carry a mode — F4's truth table sets it on the gateway"),
        "verdict_reading": (
            "the enum DECLARES exactly these two values. Direction 7 established that "
            "ParamValidator performs no enum membership check, so this is a statement about "
            "the documented value set and not about what the service rejects: a third value "
            "would be refused by the service, not by the SDK"),
        "corroboration": (
            "Phase 2 created a live policy engine and a gateway carrying "
            "policyEngineConfiguration.mode, so ENFORCE is known to be accepted "
            "server-side; LOG_ONLY is exercised by F4-2 and F4-3"),
        "expiry": (f"dated by botocore {pinned['botocore']}. F1-1's bisect shows this "
                   f"particular enum has carried both values since at least 1.42.22, which "
                   f"is 249 candidate releases of stability"),
    }, stores["F1-5"])

    # =================================================================================
    # F1-7 — content-filter categories, and the two APIs that disagree
    # =================================================================================
    cfg7 = enums["GuardrailContentFilterType"]              # bedrock, CreateGuardrail
    chk7 = enums["GuardrailChecksContentFilterCategory"]    # bedrock-runtime, checks
    want7 = expected_enum_from_seal("F1-7")
    o7 = O.Observation(case_id="F1-7", observed_enum=list(cfg7["values"]),
                       expected_enum=list(want7), n_attempted=0, n_usable=0,
                       detail={"shape": "GuardrailContentFilterType",
                               "service": cfg7["service"],
                               "sibling_shape": "GuardrailChecksContentFilterCategory",
                               "sibling_values": list(chk7["values"])})
    rec7 = O.evaluate(o7)
    P.emit("F1-7", rec7, {
        **common,
        "expected_enum_provenance": (
            f"parsed from the sealed oracle text, not typed here: {want7}"),
        "which_enum_was_read": (
            "GuardrailContentFilterType on `bedrock` — the CreateGuardrail configuration "
            "enum. Stated because the verdict is SENSITIVE to the choice: the sealed "
            "expected set includes PROMPT_ATTACK, which this enum has and the other one "
            "does not, so reading the runtime enum instead would have produced FALSE from "
            "the same sweep"),
        "the_two_apis_disagree": {
            "bedrock.GuardrailContentFilterType": list(cfg7["values"]),
            "bedrock-runtime.GuardrailChecksContentFilterCategory": list(chk7["values"]),
            "difference": sorted(set(cfg7["values"]) - set(chk7["values"])),
            "reading": (
                "PROMPT_ATTACK is one of six filter TYPES on CreateGuardrail and is not a "
                "content-filter category at all on InvokeGuardrailChecks, where it is a "
                "separate check (`checks.promptAttack`) with its own three-value enum. So "
                "the same concept is one filter type on the configuration API and a "
                "sibling check on the runtime API"),
            "consequence_for_the_document": (
                "§3.1 line 121 lists five — 'Content Filter categories: VIOLENCE, HATE, "
                "SEXUAL, MISCONDUCT, INSULTS.' — inside a section about guardrails in "
                "Gateway Policy, whose evaluation path requires "
                "`bedrock:InvokeGuardrailChecks`. Against THAT API the list of five is "
                "exactly right. Against CreateGuardrail it is short by PROMPT_ATTACK, and a "
                "reader who copies the sentence into a contentPolicyConfig ships a "
                "guardrail with no prompt-attack filter. The amendment is not 'the document "
                "is wrong': it is that the sentence needs to name which API its list "
                "belongs to"),
        },
        "verdict_reading": (
            "the CreateGuardrail enum declares exactly the sealed six. As with F1-5 this "
            "is the documented value set; per-category ACCEPTANCE by CreateGuardrail is a "
            "server-side fact, and F3's provisioner has already exercised all six live "
            "(f3_efficacy/00_guardrails.py builds contentPolicyConfig across the lattice, "
            "and its NONE finding shows the service does validate this block)"),
        "v13_candidate": (
            "§3.1 L121 — qualify the five-category list with the API it describes, and note "
            "that CreateGuardrail's contentPolicyConfig carries PROMPT_ATTACK as a sixth "
            "filter type"),
    }, stores["F1-7"])

    # =================================================================================
    # F1-9 — sensitive-information entity types vs the corpus
    # =================================================================================
    pii_cfg = list(enums["GuardrailPiiEntityType"]["values"])
    pii_chk = list(enums["GuardrailChecksSensitiveInformationEntityType"]["values"])
    corpus_labels = sorted({
        json.loads(line)["label"]
        for f in sorted((ROOT / "corpora" / "pii" / "positive").glob("*.jsonl"))
        for line in f.read_text(encoding="utf-8").splitlines() if line.strip()})
    missing = sorted(set(corpus_labels) - set(pii_cfg))
    extra = sorted(set(pii_cfg) - set(corpus_labels))
    o9 = P.obs_existence(
        "F1-9", not missing,
        # n=0: this is a set comparison between a shipped enum and a corpus on disk, not a
        # rate over trials. The corpus item count (341) is reported separately; putting it
        # in `n` would present a file read as a sample.
        n=0,
        n_enum_values_bedrock=len(pii_cfg),
        n_enum_values_runtime=len(pii_chk),
        two_services_identical=(sorted(pii_cfg) == sorted(pii_chk)),
        n_corpus_labels=len(corpus_labels),
        n_corpus_items=sum(1 for f in
                           sorted((ROOT / "corpora" / "pii" / "positive").glob("*.jsonl"))
                           for line in f.read_text(encoding="utf-8").splitlines()
                           if line.strip()),
        labels_absent_from_enum=missing,
        enum_values_not_in_corpus=extra)
    P.emit("F1-9", O.evaluate(o9), {
        **common,
        "verdict_rule": (
            "TRUE iff every entity type the corpus targets is enumerated by the SDK. The "
            "sealed oracle is directional — 'TRUE if the SDK enumerates the entity set the "
            "corpus targets' — so an enum value with no corpus file is a gap in OUR "
            "coverage, not a falsification of the document, and is reported separately "
            f"({len(extra)} such values)"),
        "verdict_reading": (
            f"the two services declare IDENTICAL 31-value sets, and the corpus's "
            f"{len(corpus_labels)} labels are exactly those 31 with no leftovers in either "
            f"direction. The corpus was built against this enum, so this case is partly a "
            f"check that it still matches — which is its value: a later SDK adding a 32nd "
            f"entity type makes F3-4's per-entity table incomplete, and this is where that "
            f"is detected"),
        "what_true_does_not_prove": (
            "anything about DETECTION. F1-9 asks whether the type exists in the API; "
            "whether the service finds an instance of it is F3-4, which measured "
            "per-entity recall over the same 341 items and whose sealed n is per entity"),
        "expiry": (f"dated by botocore {pinned['botocore']}; a new entity type is an "
                   f"AWS-BEHAVIOR-CHANGES.md entry and a corpora gap at once"),
    }, stores["F1-9"])

    # =================================================================================
    # F1-14 — Automated Reasoning: detect-only, en-US only, no streaming
    # =================================================================================
    cs = ar["operations"]["ConverseStream"]
    conv = ar["operations"]["Converse"]
    ims = ar["operations"]["InvokeModelWithResponseStream"]
    bedrock_mode_hits = modes["per_service"]["bedrock"]["hits"]
    streaming_permitted = bool(cs["attachable_by_identifier"] and cs["n_ar_output_paths"])
    o14 = P.obs_existence(
        "F1-14",
        # The sealed oracle: TRUE if the SDK exposes no enforce mode, rejects non-en-US AND
        # rejects streaming. A conjunction is FALSE as soon as one conjunct fails, so the
        # streaming conjunct alone decides this — and it fails in the direction that is
        # decidable offline: the field EXISTS.
        not streaming_permitted,
        # n=0: a model read, as in F8-8. No request was sent.
        n=0,
        conjunct_no_enforce_mode={
            "bedrock_mode_enum_hits": bedrock_mode_hits,
            "n_bedrock_enums_examined":
                modes["per_service"]["bedrock"]["n_enums_examined"],
            "n_bedrock_enum_values_examined":
                modes["per_service"]["bedrock"]["n_enum_values_examined"],
            "create_guardrail_ar_paths": ar["create_guardrail_ar_config"]["paths"],
            "holds": not bedrock_mode_hits,
        },
        conjunct_no_streaming={
            "ConverseStream_attachable": cs["attachable_by_identifier"],
            "ConverseStream_guardrail_input_paths": cs["guardrail_input_paths"],
            "ConverseStream_n_ar_output_paths": cs["n_ar_output_paths"],
            "ConverseStream_ar_output_roots": cs["ar_output_path_roots"],
            "Converse_n_ar_output_paths": conv["n_ar_output_paths"],
            "InvokeModelWithResponseStream_n_ar_output_paths": ims["n_ar_output_paths"],
            "holds": not streaming_permitted,
        })
    P.emit("F1-14", O.evaluate(o14), {
        **common,
        "verdict_rule": (
            "the sealed oracle is a three-way conjunction — no enforce mode, non-en-US "
            "rejected, streaming rejected — and 'FALSE if any is permitted'. One refuted "
            "conjunct decides it, so the verdict rests on the streaming half alone and the "
            "other two are reported without being needed"),
        "verdict_reading": (
            "FALSE. `ConverseStream` accepts guardrailConfig.guardrailIdentifier and models "
            f"{cs['n_ar_output_paths']} Automated-Reasoning paths under "
            f"stream.metadata.trace.guardrail.* — the SAME GuardrailTraceAssessment shape "
            f"`Converse` carries {conv['n_ar_output_paths']} of. A guardrail with an "
            f"automatedReasoningPolicyConfig is therefore attachable to the streaming "
            f"operation and the streaming response has a slot for its assessment. The SDK "
            f"does not reject streaming; it models it"),
        "why_presence_is_the_strong_direction": (
            "F8-8's sibling verdict was TRUE from an ABSENT field, where FALSE was "
            "unreachable by construction. This is the mirror image and the stronger one: "
            "the oracle's FALSE branch is 'if any is permitted', and a field that exists, "
            "is settable and has a matching response slot is what permitted means at the "
            "SDK layer. No inference is required"),
        "what_false_does_not_prove": (
            "that AWS PERFORMS Automated Reasoning on a streamed response. A slot on a "
            "response shape shows the wire format carries the concept, not that the service "
            "fills it — the service could accept the request and return an empty "
            "assessment, which would leave the document's practical advice intact on "
            "grounds this case did not measure. The live probe belongs in Phase 4: attach an "
            "AR-carrying guardrail to ConverseStream and read "
            "stream.metadata.trace.guardrail.outputAssessments[].automatedReasoningPolicy"),
        "the_other_two_conjuncts": {
            "no_enforce_mode": (
                f"holds on the model. Direction 9 examined "
                f"{modes['per_service']['bedrock']['n_enums_examined']} enums and "
                f"{modes['per_service']['bedrock']['n_enum_values_examined']} enum values "
                f"on `bedrock` for DETECT and ENFORCE and found NONE, and "
                f"automatedReasoningPolicyConfig carries only "
                f"{ar['create_guardrail_ar_config']['paths']}"),
            "non_en_US_rejected": (
                "not re-measured here. F8-8 settled it as a sibling case: no field on any "
                "AutomatedReasoning operation can express a language or locale, so the "
                "request cannot be constructed"),
            "why_reported_anyway": (
                "a conjunction reported as FALSE with only the failing conjunct shown "
                "invites the reading that the other two also failed. They did not, and the "
                "document is right about them"),
        },
        "false_positive_accounting": {
            "GuardrailOrigin": MODE_SCAN_FALSE_POSITIVES["GuardrailOrigin"],
            "why_it_matters_here": (
                "the ENFORCE token does hit on bedrock-RUNTIME, on GuardrailOrigin's "
                "ACCOUNT_ENFORCED / ORGANIZATION_ENFORCED. Counted naively it would look "
                "like an Automated Reasoning enforce mode. It is the account-level "
                "enforcement surface — F5-9's subject, not this one — and `bedrock`, the "
                "service that actually carries the AR operations, has zero mode hits"),
        },
        "v13_candidate": (
            "§3.2 L182 — 'no streaming support' is contradicted by the shipped model: "
            "ConverseStream is guardrail-attachable and its trace carries the AR assessment "
            "through the same shape as Converse. Amend to state what is actually absent "
            "(a mode selector and a language selector) and mark the streaming clause "
            "pending the Phase 4 live probe"),
        "expiry": f"dated by botocore {pinned['botocore']}",
    }, stores["F1-14"])

    # =================================================================================
    # F1-21 — PutEnforcedGuardrailConfiguration required fields
    # =================================================================================
    pe = req["bedrock:PutEnforcedGuardrailConfiguration"]
    rp = set(pe["required_paths"])
    version_required = "guardrailInferenceConfig.guardrailVersion" in rp
    included_required = "guardrailInferenceConfig.modelEnforcement.includedModels" in rp
    excluded_required = "guardrailInferenceConfig.modelEnforcement.excludedModels" in rp
    o21 = P.obs_existence(
        "F1-21", version_required and included_required,
        # n=0: a required-member read plus the validator's behaviour on that shape. No
        # enforcement is applied and no call is made — which is the point of the case.
        n=0,
        top_level_members=pe["top_level_members"],
        top_level_required=pe["top_level_required"],
        n_members_examined=pe["n_members_examined"],
        required_paths=sorted(rp),
        guardrail_version_required=version_required,
        included_models_required=included_required,
        excluded_models_required=excluded_required,
        model_enforcement_itself_required=("guardrailInferenceConfig.modelEnforcement"
                                           in rp))
    P.emit("F1-21", O.evaluate(o21), {
        **common,
        "no_claim_row": platform_note["F1-21"],
        "verdict_rule": (
            "TRUE iff guardrailVersion and modelEnforcement.includedModels are both "
            "required as modelled. 'Required in practice' is decidable here and not only on "
            "the model, because ParamValidator DOES enforce required members — an omitted "
            "one never reaches the service, so no live call could observe it being optional"),
        "verdict_reading": (
            "both are required, and the surface is narrower than the plan assumed in one "
            "way and wider in another: `modelEnforcement` is itself OPTIONAL at the top "
            "level, so the requirement is conditional on supplying that block at all — and "
            "when it is supplied, `excludedModels` is required TOO, not just "
            "`includedModels`. The plan's 5c design said 'only includedModels is required'; "
            "that is refuted, and 5c must send both lists"),
        "consequence_for_5c": (
            "the blast-radius narrowing still works — includedModels scoped to one "
            "provably-unused model — but the request must also carry excludedModels "
            "(min: 0, so an empty list satisfies it) or ParamValidator refuses to serialise "
            "it. A 5c script written from the plan's premise would have failed at the "
            "validator inside its <=5-minute window, with the account-level guardrail "
            "already the thing being changed"),
        "selective_content_guarding": (
            "the shape also carries selectiveContentGuarding.{system,messages} over "
            "SelectiveGuardingMode {SELECTIVE, COMPREHENSIVE}, which the document does not "
            "mention at all. Recorded because a reader planning account-level enforcement "
            "would want to know it exists; it answers no sealed claim"),
        "what_true_does_not_prove": (
            "anything about what account-level enforcement DOES. This case deliberately "
            "applies none — its whole purpose per the sealed triage note is to validate the "
            "5c controls before the live window opens. The consequence claim (an agent "
            "cannot decline an account-level guardrail) is F5-9"),
        "expiry": f"dated by botocore {pinned['botocore']}",
    }, stores["F1-21"])

    # =================================================================================
    # F1-22 — Optimization exposes Recommendations / ConfigBundles / A-B Testing
    # =================================================================================
    g = caps["groups"]
    trio = ("recommendations", "configuration_bundles", "ab_testing")
    trio_present = all(g[k]["present"] for k in trio)
    batch = g["batch_evaluation"]
    optimization_roots = {"Recommendation", "ConfigurationBundle", "ABTest"}
    batch_named_evaluation = all("Evaluation" in h["operation"]
                                 for h in batch["operations"])
    batch_not_optimization = not any(r in h["operation"]
                                    for h in batch["operations"]
                                    for r in optimization_roots)
    o22 = P.obs_existence(
        "F1-22",
        trio_present and batch["present"] and batch_named_evaluation
        and batch_not_optimization,
        # n=0: an operation-name enumeration over 350 operations. The 350 is the search
        # space and is reported as such; it is not a trial count.
        n=0,
        n_operations_searched=caps["n_operations_searched"],
        services_searched=caps["services_searched"],
        groups={k: {"n_hits": g[k]["n_hits"],
                    "services": g[k]["services_with_hits"],
                    "operations": [h["operation"] for h in g[k]["operations"]]}
                for k in trio + ("batch_evaluation", "online_evaluation",
                                 "evaluation_job", "on_demand_evaluation")},
        batch_evaluation_named_evaluation=batch_named_evaluation,
        batch_evaluation_carries_no_optimization_root=batch_not_optimization)
    P.emit("F1-22", O.evaluate(o22), {
        **common,
        "verdict_rule": (
            "TRUE iff all three Optimization groups exist AND Batch Evaluation sits with "
            "Evaluations. The second half needs a stated method, because the SDK exposes no "
            "capability grouping at all: there is no field saying 'this operation belongs "
            "to Optimization'. The taxonomy is therefore decided by operation NAMING — "
            "every BatchEvaluation operation carries the *Evaluation* root and none carries "
            "Recommendation, ConfigurationBundle or ABTest — and that reasoning is the "
            "evidence, not a hidden step"),
        "verdict_reading": (
            "all three exist and Batch Evaluation is named as an Evaluations capability, "
            "which is what the document says. The naming argument is weaker evidence than a "
            "structural one and is labelled as such; the structural check that WOULD settle "
            "it (an IAM action prefix or a console grouping) is not in any service model"),
        "the_split_spans_three_services": {
            "bedrock-agentcore": sorted({h["operation"] for k in
                                         ("recommendations", "ab_testing",
                                          "batch_evaluation", "on_demand_evaluation")
                                         for h in g[k]["operations"]}),
            "bedrock-agentcore-control": sorted({h["operation"] for k in
                                                 ("configuration_bundles",
                                                  "online_evaluation")
                                                 for h in g[k]["operations"]}),
            "bedrock": sorted({h["operation"] for h in g["evaluation_job"]["operations"]}),
            "reading": (
                "Recommendations, A/B tests, Batch Evaluation and the on-demand `Evaluate` "
                "are on the DATA plane; Configuration Bundles and Online Evaluation "
                "configs are on the CONTROL plane; and `bedrock` carries a separate, older "
                "EvaluationJob family that is model evaluation and not agent evaluation at "
                "all. §5.3 names the capabilities and no service, so a reader looking for "
                "ConfigurationBundle on bedrock-agentcore will not find it"),
            "why_this_was_worth_measuring": (
                "this project has twice published an absence after searching one service, "
                "and both surfaces were on another. This group is where that would have "
                "happened a third time: searching only bedrock-agentcore-control finds "
                "Configuration Bundles and Online Evaluation and MISSES Recommendations, "
                "A/B testing and Batch Evaluation entirely"),
        },
        "deploy_configuration_bundle_is_absent": (
            "§5.3 L608 tells readers to 'restrict UpdateConfigurationBundle / "
            "DeployConfigurationBundle IAM permissions'. Seven ConfigurationBundle "
            "operations exist and none of them is DeployConfigurationBundle — the model "
            "carries Create/Delete/Get/GetVersion/ListVersions/List/Update. Across all four "
            "services the only Deploy* operations are CustomModelDeployment, which is "
            "unrelated. An IAM policy written from that sentence would name a "
            "non-existent action, which denies nothing"),
        "v13_candidate": (
            "§5.3 — name the service each capability lives on, and drop or rename "
            "DeployConfigurationBundle, which is not in the API"),
        "expiry": f"dated by botocore {pinned['botocore']}",
    }, stores["F1-22"])

    # =================================================================================
    # F1-23 — Evaluations exposes on-demand, batch and online
    # =================================================================================
    on_demand = g["on_demand_evaluation"]
    online = g["online_evaluation"]
    starters = [h["operation"] for h in batch["operations"]
                if h["operation"].startswith("Start")]
    creators = [h["operation"] for h in online["operations"]
                if h["operation"].startswith("Create")]
    o23 = P.obs_existence(
        "F1-23",
        bool(on_demand["present"] and starters and creators),
        n=0,
        n_operations_searched=caps["n_operations_searched"],
        on_demand={"match": on_demand["match"], "match_why": on_demand["match_why"],
                   "operations": [h["operation"] for h in on_demand["operations"]],
                   "service": on_demand["services_with_hits"]},
        batch={"operations": [h["operation"] for h in batch["operations"]],
               "invocable": starters, "service": batch["services_with_hits"]},
        online={"operations": [h["operation"] for h in online["operations"]],
                "configurable": creators, "service": online["services_with_hits"]})
    P.emit("F1-23", O.evaluate(o23), {
        **common,
        "verdict_rule": (
            "TRUE iff all three modes are configurable: an on-demand entry point, a batch "
            "job that can be STARTED, and an online config that can be CREATED. 'Exists' "
            "is not enough for the last two — a family of Get/List/Delete operations with "
            "no creator would be a read surface for something a customer cannot configure"),
        "why_on_demand_is_matched_exactly": on_demand["match_why"],
        "verdict_reading": (
            "on-demand is the operation literally called `Evaluate`; batch is "
            "StartBatchEvaluation; online is CreateOnlineEvaluationConfig. All three "
            "exist and the two that need a creator have one"),
        "the_split_spans_two_services": (
            "on-demand and batch are on the data plane `bedrock-agentcore`; the online "
            "config is on the control plane `bedrock-agentcore-control`. §5.2 presents the "
            "three as one capability with three modes, which is true of the concept and not "
            "of the endpoint a reader has to call"),
        "what_true_does_not_prove": (
            "that an evaluation RUNS. Three operations existing is not three working "
            "pipelines, and the known-empty-evals defect in a different project of ours was "
            "exactly a present API returning nothing. §5.2's other claim — 'detects quality "
            "drops over time' — is a behavioural claim no service model can answer"),
        "expiry": f"dated by botocore {pinned['botocore']}",
    }, stores["F1-23"])

    # =================================================================================
    # the eight surface-only cases: what the model settled, and who closes them
    # =================================================================================
    surface_facts = {
        "F1-8": {"enum": enums["GuardrailChecksPromptAttackCategory"]},
        "F1-10": {"definition_shape": limits["bedrock:GuardrailTopicDefinition"],
                  "tier_shape": limits["bedrock:GuardrailTopicsTierConfig"],
                  "tier_enums": {k: enums[k] for k in
                                 ("GuardrailTopicsTierName",
                                  "GuardrailContentFiltersTierName")},
                  "sibling_case": "F8-5 (measured FALSE; STANDARD half confounded)"},
        "F1-11": {"content_filter_shape": limits["bedrock:GuardrailContentFilterConfig"],
                  "pii_shape": limits["bedrock:GuardrailPiiEntityConfig"],
                  "strength_enum": enums["GuardrailFilterStrength"],
                  "action_enum": enums["GuardrailContentFilterAction"],
                  "create_guardrail_required":
                      req["bedrock:CreateGuardrail"]["required_paths"]},
        "F1-12": {"enum": enums["GuardrailStreamProcessingMode"],
                  "enum_enforcement": enforce7,
                  "token_scan": tokens["tokens"]["streamProcessingMode"],
                  "mode_scan_classification": mode_hits},
        "F1-13": {"grounding_shape":
                      limits["bedrock:GuardrailContextualGroundingFilterConfig"],
                  "text_block_shape": limits["bedrock-runtime:GuardrailTextBlock"],
                  "apply_guardrail_required":
                      req["bedrock-runtime:ApplyGuardrail"]["required_paths"],
                  "limits_by_reference": O.BINDINGS["F1-13"].limits_by_reference},
        "F1-16": {"interception_point_enum": enums["GatewayInterceptionPoint"],
                  "token_scan": tokens["tokens"]["interceptor"],
                  "operation_group": g["interceptor"],
                  "create_gateway_required":
                      req["bedrock-agentcore-control:CreateGateway"]["required_paths"]},
        "F1-17": {"token_scan": tokens["tokens"]["suppressOutput"],
                  "examined": tokens["examined_total"]},
        "F1-20": {"message_list": limits["bedrock-runtime:GuardrailChecksMessageList"],
                  "content_block_list":
                      limits["bedrock-runtime:GuardrailChecksContentBlockList"],
                  "text_content": limits["bedrock-runtime:GuardrailChecksTextContent"],
                  "required": req["bedrock-runtime:InvokeGuardrailChecks"]},
    }
    for cid, (settled, why_open, successor) in SURFACE_ONLY.items():
        rec = O.not_measured(
            cid,
            f"the service model settles the SURFACE and not the oracle. Settled: {settled}. "
            f"Open because {why_open}. Deferred to {successor}",
            surface=surface_facts[cid])
        P.emit(cid, rec, {
            **common,
            "surface_settled": settled,
            "why_the_model_cannot_close_it": why_open,
            "successor": successor,
            "surface_facts": surface_facts[cid],
            "why_a_record_at_all": (
                "a case with no file in results/phase1/ is indistinguishable from a case "
                "nobody triaged. This record says what is known, what is not, and who "
                "closes it — and it is INCONCLUSIVE rather than RECORDED because RECORDED "
                "is a sealed property meaning the pre-registration declared the outcome "
                "unknown, and a script cannot grant itself that"),
            "why_inconclusive": (
                "the oracle asks about SERVICE behaviour and this instrument reads a "
                "shipped model. Reporting the model's declaration as the answer would "
                "publish documentation as a measurement"),
        }, stores[cid], quiet=True)
        print(f"  {cid:6s} SURFACE ONLY -> {successor}")

    print(f"\n{len(CASES)} case(s) decided, {len(SURFACE_ONLY)} deferred with a named "
          f"successor; 0 AWS calls, 0 mutations, $0.00")
    return 0


if __name__ == "__main__":
    sys.exit(main())
