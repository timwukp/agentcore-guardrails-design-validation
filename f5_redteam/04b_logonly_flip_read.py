#!/usr/bin/env python3
"""F5-4a supplementary read: what did the LOG_ONLY metric family say about a policy that
cannot evaluate?

WHY THIS EXISTS, SEPARATELY FROM F5-4a
--------------------------------------
F5-4a measured five arms and read the four *mismatch* metrics (`MismatchErrors`,
`TotalMismatchedPolicies`, `PolicyMismatch`, `LogOnlyEvalIncomplete`). It did not read
`LogOnlyMatches` or `LogOnlyDecisionFlips`, because its own question was about mismatch
reporting. But the document's most consequential LOG_ONLY claim is about the flip metric:

    §7.1, line 737: "Watch LogOnlyDecisionFlips: a sustained zero means promotion will
                     not block current traffic."
    §7.1, line 743 (diagram): "LogOnlyDecisionFlips sustained at zero?" -> promote

F5-4a's two missing-path arms are the sharpest possible test of that inference, and they
are already run:

  * `guardrail_missing_path`   ACTIVE   status ACTIVE, lint []  ->  DENY 20/20
  * `guardrail_missing_logonly` LOG_ONLY status ACTIVE, lint []  ->  ALLOW 20/20

Same statement, same engine, same gateway, same action, same payload, same n. Only the
enforcement mode differs. So if the flip metric was ZERO across the LOG_ONLY arm's window,
then a "sustained zero" was true of a policy whose promotion blocks 100% of traffic, and
§7.1's stated inference is measured false rather than merely doubted.

That claim needs the read, not an inference from the arm outcome. This script does the
read. It is read-only: no policy exists any more (F5-4a deleted all four), nothing is
created, and CloudWatch history is what is being consulted.

THE GUARD THAT MAKES A ZERO MEAN ANYTHING
-----------------------------------------
A zero from a metric that does not exist is not a measurement. `LogOnlyEvalIncomplete` is
exactly that case in this account: F7-1 recorded `name_in_namespace_inventory: false` and
F5-4a's poll found `dimension_combinations_listed: 0` over 15 bounded minutes. So this
script separates two readings that look identical in a dashboard:

    PUBLISHED_AND_ZERO   `list_metrics` names the metric -> the zero is a real zero
    NEVER_PUBLISHED      `list_metrics` does not name it -> the zero is instrument absence

`LogOnlyMatches` and `LogOnlyDecisionFlips` are known to be in the PUBLISHED class from
F7-1 (4708 and 3372 over F4's LOG_ONLY cells, 12 series each), so a zero from them here is
informative. The check is re-made here rather than cited, because it is the hinge.

WHAT THIS SCRIPT DOES NOT CLAIM
-------------------------------
It reads a window that has already closed. It cannot re-run the arm, so it cannot
distinguish "the flip metric was zero because the policy could not evaluate" from "the
flip metric was zero because CloudWatch dropped it" -- except by the baseline/probe
contrast and by F7-1's demonstration that the same metric publishes for a WORKING LOG_ONLY
policy on this same gateway. Both are reported; neither is presented as proof of a
mechanism inside the service.

It is also not a pre-registered case and deliberately does not print F5-4a's sealed
oracle: that oracle binds F5-4a's arm plan, not this read, and a banner quoting it would
imply a verdict this file has no standing to reach. It writes
`results/phase1/F5-4a_logonly_read.json` with `kind: SUPPLEMENTARY_READ` and no `verdict`
key, so nothing downstream can mistake it for a case result.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import phase1 as P       # noqa: E402
import redact as R       # noqa: E402
import testbed as T      # noqa: E402
from evidence import EvidenceStore  # noqa: E402

FAMILY = "f5"
PARENT_CASE = "F5-4a"
# A distinct evidence case id: these records are a later read, not part of F5-4a's archive,
# and `EvidenceStore` numbers records per directory.
EVIDENCE_CASE = "F5-4a-logonly-read"
OUT_NAME = "F5-4a_logonly_read.json"

# One definition of "sum a metric over every dimension combination it publishes", taken
# from the case that produced the window rather than copied beside it. Copying it would let
# the two reads drift apart while both claimed to be reading the same way.
_spec = importlib.util.spec_from_file_location(
    "_grx_f54a", ROOT / "f5_redteam" / "04_policy_failure_modes.py")
_f54a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_f54a)
_read_metric = _f54a._read_metric
NS = _f54a.NS

LOGONLY_METRICS = ("LogOnlyMatches", "LogOnlyDecisionFlips", "LogOnlyEvalIncomplete")

# The arm whose window this is, and its ACTIVE twin. Named, not described, so a later edit
# cannot quietly re-point the comparison at a different pair.
ARM_LOGONLY = _f54a.ARM_LOGONLY
ARM_ACTIVE_TWIN = _f54a.ARM_MISSING

RESULT = ROOT / "results" / "phase1" / f"{PARENT_CASE}.json"

# Readings. A zero is split by whether the instrument exists, which is the whole point.
PUBLISHED_AND_ZERO = "PUBLISHED_AND_ZERO"
PUBLISHED_AND_NONZERO = "PUBLISHED_AND_NONZERO"
NEVER_PUBLISHED = "NEVER_PUBLISHED"
AMBIENT = "AMBIENT_BEFORE_AND_DURING"


class ConfigError(RuntimeError):
    """The recorded result this read depends on is not usable. Never a reading."""


def _window_from_recorded_result(result: dict[str, Any]) -> dict[str, datetime]:
    """The union of the windows F5-4a actually read, taken from its own result file.

    Hardcoding `22:46:33Z .. 23:04:03Z` here would be a second statement of one fact, and
    the copy could not be wrong in a way the file would reveal
    (`feedback_two_numbers_two_claims`). The union is used rather than any single metric's
    window because each metric stopped being polled when it decided, so the four windows
    have four different ends and only their union is guaranteed to contain every arm.
    """
    per = ((result.get("mismatch_metrics") or {}).get("per_metric") or {})
    if not per:
        raise ConfigError(f"{RESULT.name} carries no mismatch_metrics.per_metric")
    starts, ends = [], []
    for rec in per.values():
        for half in ("before", "after"):
            w = (rec.get(half) or {}).get("window") or {}
            if half == "after" and w.get("start") and w.get("end"):
                starts.append(datetime.fromisoformat(str(w["start"])))
                ends.append(datetime.fromisoformat(str(w["end"])))
    if not starts:
        raise ConfigError(f"{RESULT.name} carries no probe-window timestamps")
    return {"start": min(starts), "end": max(ends)}


def _reading(baseline: dict[str, Any], probe: dict[str, Any]) -> str:
    """Absence of an instrument and absence of a signal are different facts.

    The baseline is consulted for the same reason F5-4a consulted one: a nonzero probe
    window is only attributable to F5-4a's arm if nothing in the account was already
    publishing the metric on its own cadence. AMBIENT is a refusal to attribute, not a
    result.
    """
    if not probe["dimension_combinations_listed"]:
        return NEVER_PUBLISHED
    if probe["sum"] == 0:
        return PUBLISHED_AND_ZERO
    return AMBIENT if baseline["sum"] > 0 else PUBLISHED_AND_NONZERO


def _dimension_values_seen(probe: dict[str, Any]) -> list[str]:
    """Every `Name=Value` a datapoint in the probe window carried.

    Attribution has to be checkable: if a nonzero flip count turns up, the reader must be
    able to see whether it names F5-4a's LOG_ONLY probe or something else in the account.
    """
    seen = set()
    for dp in probe.get("datapoints") or []:
        for d in dp.get("dimensions") or []:
            seen.add(f"{d.get('Name')}={d.get('Value')}")
    return sorted(seen)


def _contrast(result: dict[str, Any], flips: dict[str, Any]) -> dict[str, Any]:
    """The conjunction §7.1's refutation rests on, each conjunct read from a file or a read.

    Kept out of `main` so it can be tested against a planted false conjunct. A refutation
    assembled inline is a refutation nobody can check for vacuity: every one of these has to
    be capable of coming back False, and `tests/test_logonly_flip_read.py` shows each one
    doing so.
    """
    arms = result.get("arms") or {}
    probes = result.get("probes") or {}
    logonly_arm = arms.get(ARM_LOGONLY) or {}
    active_arm = arms.get(ARM_ACTIVE_TWIN) or {}
    return {
        "same_statement": (probes.get(ARM_LOGONLY, {}).get("statement")
                           == probes.get(ARM_ACTIVE_TWIN, {}).get("statement")
                           and probes.get(ARM_LOGONLY, {}).get("statement") is not None),
        "logonly_allowed_all": (logonly_arm.get("decision") == "ALLOW"
                                and logonly_arm.get("n_denied") == 0
                                and logonly_arm.get("unanimous") is True),
        "active_twin_denied_all": (active_arm.get("decision") == "DENY"
                                   and active_arm.get("n_allowed") == 0
                                   and active_arm.get("unanimous") is True),
        "flip_metric_exists_in_this_namespace":
            flips["probe"]["dimension_combinations_listed"] > 0,
        "flip_metric_was_zero_in_the_logonly_window": flips["probe"]["sum"] == 0,
        "n_per_arm": result.get("n_per_arm"),
    }


# The one key in `_contrast` that is a number rather than a conjunct. Named once, so the
# conjunction and the test agree on what is being ANDed.
NOT_A_CONJUNCT = ("n_per_arm",)

# The conjuncts, named as a fixed set rather than derived from whatever keys happen to be
# present. `all()` over an empty selection is True, so a `_contrast` that lost a key — a
# renamed arm, a schema change in the result file — would have made the refutation hold on
# nothing at all. Enumerating them means a missing key is a missing conjunct, which is a
# False. `tests/test_logonly_flip_read.py` caught exactly that.
CONJUNCTS = ("same_statement", "logonly_allowed_all", "active_twin_denied_all",
             "flip_metric_exists_in_this_namespace",
             "flip_metric_was_zero_in_the_logonly_window")


def _inference_holds(contrast: dict[str, Any]) -> bool:
    """True only if every named conjunct is present and exactly True.

    A missing key is a False, not a pass: see `CONJUNCTS`. An unexpected extra key is also
    a False, because a conjunct nobody enumerated is a conjunct nobody tested.
    """
    if set(contrast) - set(NOT_A_CONJUNCT) != set(CONJUNCTS):
        return False
    return all(contrast.get(k) is True for k in CONJUNCTS)


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(PARENT_CASE, __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        # Deliberately NOT `P.dry_run_banner`: see the module docstring. That banner prints
        # the sealed oracle for the case id it is given, and this read is not that case.
        print(f"{PARENT_CASE} supplementary LOG_ONLY read — dry run, no AWS call, "
              f"no mutation\n")
        print(f"reads {', '.join(LOGONLY_METRICS)} from {NS} over two windows:")
        print(f"  probe    the union of the windows recorded in results/phase1/"
              f"{PARENT_CASE}.json")
        print("  baseline the same duration immediately before it, to separate an ambient "
              "publisher\n")
        print("per metric: 1 list_metrics + 1 get_metric_statistics per discovered "
              "dimension combination, per window")
        print("mutations: 0 (no resource is created, changed or deleted; all four F5-4a "
              "probe policies were already deleted)")
        print("billable: CloudWatch reads only, under $0.01\n")
        print(f"the question: {ARM_LOGONLY} allowed 20/20 while {ARM_ACTIVE_TWIN} — the "
              f"SAME statement in ACTIVE — denied 20/20. §7.1 says a sustained zero "
              f"LogOnlyDecisionFlips means promotion will not block traffic. This read "
              f"establishes whether that zero was present.")
        print("a zero is reported as PUBLISHED_AND_ZERO only if list_metrics names the "
              "metric; otherwise NEVER_PUBLISHED. A zero from an absent instrument is not "
              "evidence.")
        return 0

    if not RESULT.is_file():
        raise ConfigError(f"{RESULT} does not exist — run {PARENT_CASE} first")
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    window = _window_from_recorded_result(result)
    span = window["end"] - window["start"]
    baseline_window = {"start": window["start"] - span, "end": window["start"]}

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    cw = fc.client("cloudwatch")
    store = EvidenceStore(run_id, FAMILY, EVIDENCE_CASE)
    store.write_environment()

    per_metric: dict[str, Any] = {}
    for metric in LOGONLY_METRICS:
        base = _read_metric(cw, store, metric,
                            start=baseline_window["start"], end=baseline_window["end"])
        probe = _read_metric(cw, store, metric,
                             start=window["start"], end=window["end"])
        per_metric[metric] = {
            "baseline": {k: base[k] for k in
                         ("sum", "n_datapoints", "dimension_combinations_listed")},
            "probe": {k: probe[k] for k in
                      ("sum", "n_datapoints", "dimension_combinations_listed")},
            "dimension_values_seen_in_probe_window": _dimension_values_seen(probe),
            "reading": _reading(base, probe),
        }

    flips = per_metric["LogOnlyDecisionFlips"]
    matches = per_metric["LogOnlyMatches"]
    incomplete = per_metric["LogOnlyEvalIncomplete"]

    contrast = _contrast(result, flips)
    inference_holds = _inference_holds(contrast)

    body = {
        "case_id": PARENT_CASE,
        "kind": "SUPPLEMENTARY_READ",
        "is_a_case_verdict": False,
        "what_this_is": (
            "a later read-only CloudWatch query over the window F5-4a already recorded. "
            "It adds the two LOG_ONLY metrics F5-4a did not read. It reaches no verdict "
            "and does not re-run any arm."),
        "run_id": run_id,
        "region": region,
        "namespace": NS,
        "windows": {"probe": window, "baseline": baseline_window,
                    "span_s": round(span.total_seconds(), 1),
                    "provenance": (f"the union of the after-windows recorded in "
                                   f"results/phase1/{PARENT_CASE}.json, not a literal")},
        "per_metric": per_metric,
        "contrast": contrast,
        "s7_1_inference_is_refuted": inference_holds,
        "s7_1_inference_quoted": ("Watch LogOnlyDecisionFlips: a sustained zero means "
                                  "promotion will not block current traffic."),
        "reading": (
            "a sustained zero LogOnlyDecisionFlips held over the LOG_ONLY arm's window "
            "while the identical statement in ACTIVE denied every request, so the zero "
            "did not mean promotion was safe" if inference_holds else
            "the conjunction did not hold; see `contrast` for which conjunct failed. No "
            "claim about §7.1 is made from this read."),
        "what_this_does_not_prove": [
            "nothing here explains WHY the flip metric was zero. A policy that cannot "
            "evaluate produces no comparison to flip, which is the natural reading, but "
            "this read cannot see inside the evaluator.",
            "LogOnlyEvalIncomplete's absence is bounded by F5-4a's 900s poll and by this "
            "window, not proven for all time.",
            "the flip metric publishing for a WORKING LOG_ONLY policy is F7-1's "
            "measurement on this same gateway, not this script's.",
        ],
        "f7_1_cross_reference": {
            "LogOnlyMatches": "published, sum 4708 over 42 datapoints in F7-1's project "
                              "window (F4's LOG_ONLY cells)",
            "LogOnlyDecisionFlips": "published, sum 3372 over 42 datapoints, same window",
            "LogOnlyEvalIncomplete": "name_in_namespace_inventory false; F7-1 recorded it "
                                     "NOT_EXERCISED because reproducing it needed a "
                                     "deliberately broken policy — which F5-4a then shipped",
        },
        "retires_in_f7_1": (
            "F7-1 excluded LogOnlyEvalIncomplete as NOT_EXERCISED on the grounds that the "
            "condition was 'not reproducible on demand without deliberately shipping a "
            "broken policy'. F5-4a shipped exactly that, in LOG_ONLY, for "
            f"{result.get('n_per_arm')} requests. The exclusion is discharged and the "
            f"reading is {incomplete['reading']}."),
        "matches_metric_reading": matches["reading"],
        "ambient_sdk": result.get("ambient_sdk"),
    }
    text = json.dumps(body, indent=2, sort_keys=True, default=str,
                      ensure_ascii=False) + "\n"
    out = ROOT / "results" / "phase1" / OUT_NAME
    # Masked in `results/` and unmasked in `evidence/`, the same split `P.emit` makes and
    # for the same reason (DEV-P1-13). `P.emit` itself is not used: it would write
    # `results/phase1/F5-4a.json` and overwrite a recorded verdict with a read.
    out.write_text(R.mask_text(text), encoding="utf-8")
    (store.dir / "analysis.json").write_text(text, encoding="utf-8")
    store.write_summary({"analysis_file": "analysis.json", "case_id": PARENT_CASE,
                         "kind": "SUPPLEMENTARY_READ"})

    print(f"\n  {PARENT_CASE} supplementary LOG_ONLY read")
    for metric, rec in per_metric.items():
        print(f"    {metric:24s} baseline {rec['baseline']['sum']:>8} | "
              f"probe {rec['probe']['sum']:>8} | combos "
              f"{rec['probe']['dimension_combinations_listed']:>3} | {rec['reading']}")
    print(f"    §7.1 inference refuted: {inference_holds}")
    print(f"  wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
