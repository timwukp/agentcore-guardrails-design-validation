#!/usr/bin/env python3
"""F3-10 window audit: re-read a CLOSED metric window on a LATER UTC day, datapoint by datapoint.

WHY THIS EXISTS
---------------
`results/FINDING-F3-10.md` §11 names the blocker on its own amendment, and names it precisely:
three of its readings are claims about what a telemetry pipeline did inside one 283-second
window on 2026-08-12Z.

  (1) `ConfidenceScore` carried values summing to EXACTLY the per-request sums the application
      logs published for the same requests (24.6 vs 24.6, 0.8 vs 0.8, 24.2 vs 24.2);
  (2) NO score series held one request per datapoint in the two golden arms, which is the
      measured half of the FALSE verdict;
  (3) 61 of 122 requests published NO score at all, which is what makes §6's "the calibration
      loop can only tighten" asymmetry a reading rather than an inference.

Exactness and absence are the two things a single day cannot establish. A pipeline that was
degraded on 2026-08-12 would look exactly like (3); a pipeline that was unusually clean would
look exactly like (1). §11's own prescription is therefore two-part — take a FRESH window on a
later day (`08_score_label_join.py`, re-run) AND re-read the CLOSED one — and this file is the
second half.

WHAT A LATER RE-READ OF A CLOSED WINDOW CAN AND CANNOT SETTLE
-------------------------------------------------------------
It is worth being exact about this, because the obvious objection is sound: re-reading the same
window cannot re-run the pipeline, so it cannot distinguish "the score was never published" from
"the score was lost on the way to CloudWatch". That is true, and it is why the fresh arms exist.

What the re-read DOES settle is the bound on each reading:

  * F3-10 harvested each arm after a FIXED 120-second settle (`HARVEST_SETTLE_S`), chosen against
    F7-6's measured publish-lag p90 of 11.485 s. Every absence in reading (3) is therefore
    "absent within 120 s". Re-read a day later, the same absence becomes "absent after >= 12 h" —
    a bound two orders of magnitude wider, and one no plausible publish lag reaches.
  * Symmetrically, reading (1)'s exactness was measured while the window was minutes old. A
    late-arriving datapoint would have raised a `Sum` or a `SampleCount` after the fact and broken
    the agreement with the logs. If the sums still agree once the pipeline has had a day, the
    agreement is a property of the data and not of the moment it was read.
  * Reading (2) is re-derived rather than restated: `SampleCount` per datapoint is re-read, so
    "no series is one-request-per-datapoint" is measured again from the service.

So this read converts three claims about one moment into three claims about stored data with a
day of settle behind them. It does not convert them into claims about the service, and it does not
touch the verdict.

WHAT IT DOES
------------
1. Loads F3-10's own analysis record and its log-surface companion (by default the archived
   day-1 pair) and derives the observation day from the recorded window's `t0` — never from a
   date typed here.
2. REFUSES to run if that day is today's UTC day, or if less than `MIN_LAG_H` hours have passed
   since the last recorded bucket. A same-day re-read would be a second look at a still-open
   pipeline, and calling it a later re-read would be the same defect `07a_run_day2.sh` was
   written against (a local calendar rolling while UTC had not).
3. Re-issues `GetMetricStatistics` for EVERY score series the record enumerated for this
   gateway — including the ones that carried no datapoint, because those are exactly where a
   late arrival would show up — with the recorded dimensions, the recorded period, and a window
   spanning the recorded buckets with one period of margin either side.
4. Compares field by field: `Sum`, `SampleCount`, `Minimum`, `Maximum`, per bucket. A changed
   value, a vanished datapoint, or a NEW datapoint in a recorded bucket are all failures, and
   each is reported separately because they mean different things.
5. Re-derives the three §11 readings from the re-read and states, for each, whether it survives.

Every number this file compares against is READ FROM THE RECORDS. Nothing in the expected set is
typed in: a hardcoded 61, or 24.6, would be a second statement of a fact whose first statement is
the artefact being audited, and the copy could not be wrong in a way either file would reveal
(`feedback_two_numbers_two_claims`).

WHAT IT DOES NOT CLAIM
----------------------
* No verdict, and no `verdict` key. `kind: SUPPLEMENTARY_READ`. F3-10's FALSE stands on the
  metrics surface and this file has no standing to move it.
* No new traffic, no mutation, no resource created or deleted. It is `GetMetricStatistics` only.
* Nothing about the service's behaviour on any other day, in any other region, or for any other
  policy. It audits the stored form of one window.
* An agreement here is NOT a replication. Replication is the fresh window; this is provenance for
  the closed one. The finding must say which of its figures rest on which.

Cost: `GetMetricStatistics` at $0.01 per 1,000 requests. One call per score series per arm — on
the recorded day-1 pair that is 84 calls, about $0.0008. No metered guardrail traffic.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                              # noqa: E402
import phase1 as P                                                  # noqa: E402
import redact as R                                                  # noqa: E402
import testbed as T                                                 # noqa: E402
from evidence import EvidenceStore, capture                         # noqa: E402

FAMILY = "f3_efficacy"
PARENT_CASE = "F3-10"
# A distinct evidence case id, for the reason 08b has one: these records are a later read, not
# part of F3-10's archive, and `EvidenceStore` numbers records per directory.
EVIDENCE_CASE = "F3-10-window-audit"
OUT_NAME = "F3-10_window_audit.json"

PARENT_MODULE_NAME = "grx_f3_10c_parent_08_score_label_join"

# The parent's constants, imported rather than restated: `NS`, `PERIOD_S` and the arm keys must
# mean here exactly what they mean there, and `HARVEST_SETTLE_S` is the bound this file widens.
_parent = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location(
        PARENT_MODULE_NAME, ROOT / "f3_efficacy" / "08_score_label_join.py"))
sys.modules[PARENT_MODULE_NAME] = _parent
_parent.__spec__.loader.exec_module(_parent)

NS = _parent.NS
PERIOD_S = _parent.PERIOD_S
HARVEST_SETTLE_S = _parent.HARVEST_SETTLE_S
ARM_KEYS = tuple(a["key"] for a in _parent.ARMS)
ARM_ACTIVE_SPACED = _parent.ARM_ACTIVE_SPACED
GUARDRAIL_THRESHOLD = _parent.GUARDRAIL_THRESHOLD
GUARDRAIL_CATEGORY = _parent.GUARDRAIL_CATEGORY

ARCHIVE = ROOT / "results" / "phase1" / "archive"
DEFAULT_RECORD = ARCHIVE / "F3-10__day1_2026-08-12.json"
DEFAULT_LOG_RECORD = ARCHIVE / "F3-10_log_surface_join__day1_2026-08-12.json"

# The lag that makes this a LATER read rather than a second look at an open pipeline. 12 h is
# ~3,760x F7-6's measured publish-lag p90 (11.485 s) and 360x the parent's own 120 s harvest
# settle. It is deliberately not "one calendar day": a record from 23:50Z re-read at 00:10Z would
# satisfy a date comparison while being 20 minutes old, and the date comparison is kept as well
# because the amendment rule counts UTC days.
MIN_LAG_H = 12.0

# The statistics compared, per bucket. `Average` is deliberately absent: it is Sum/SampleCount,
# so including it would make a fourth check that cannot fail independently of two others and
# would inflate the comparison count this file reports.
STATISTICS = ("Sum", "SampleCount", "Minimum", "Maximum")
_STAT_KEY = {"Sum": "sum", "SampleCount": "sample_count", "Minimum": "min", "Maximum": "max"}

# Float comparison. CloudWatch returns IEEE doubles and `json.dumps` round-trips them exactly, so
# equality is expected to be EXACT and `n_exact` is reported separately. The tolerance exists so
# that a future record written through a lossy formatter degrades to "close" rather than to a
# false alarm — not to absorb a real change: 1e-12 relative is ~24 orders of magnitude below the
# 0.2 grid these scores actually land on.
REL_TOL = 1e-12
ABS_TOL = 1e-12

GUARDS = (
    "record_day_is_an_earlier_utc_day",
    "reread_lag_exceeds_the_floor",
    "every_score_series_was_reread",
    "no_read_error",
    "every_recorded_datapoint_was_compared",
    "no_datapoint_value_changed",
    "no_datapoint_vanished",
    "no_late_arrival_in_a_recorded_bucket",
    "detection_total_is_unchanged",
    "no_score_series_is_per_request_in_the_golden_arms",
    "logged_sums_still_match_the_metric_sums",
)


class ConfigError(RuntimeError):
    """A recorded input this read depends on is missing or unusable. Never a reading."""


# ---------------------------------------------------------------------------
# inputs, all derived from the records
# ---------------------------------------------------------------------------

def _load(path: Path, what: str) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"{what} {path} does not exist")
    body = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise ConfigError(f"{what} {path.name} is not a JSON object")
    return body


def _observation_day(record: dict[str, Any]) -> tuple[str, float, float]:
    """The record's UTC day, and the window it covers, from the recorded arm windows.

    Derived from `t0`/`t1` rather than from any date STRING in the record: a date string is prose
    and could disagree with the epochs the metric read actually used, and it is the epochs that
    decide which buckets are re-read here.
    """
    arms = record.get("arms") or {}
    if not arms:
        raise ConfigError("the record carries no arms block")
    t0s, t1s = [], []
    for key, arm in arms.items():
        w = arm.get("window") or {}
        if not isinstance(w.get("t0"), (int, float)) or not isinstance(w.get("t1"), (int, float)):
            raise ConfigError(f"arm {key} has no numeric window t0/t1")
        t0s.append(float(w["t0"]))
        t1s.append(float(w["t1"]))
    t0, t1 = min(t0s), max(t1s)
    days = sorted({datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
                   for t in (t0, t1)})
    if len(days) != 1:
        raise ConfigError(f"the recorded window straddles {days}; this audit compares one day")
    return days[0], t0, t1


def _recorded_score_series(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Every score series the record enumerated, per arm, with its recorded datapoints.

    Series with ZERO datapoints are included on purpose. They are the only place a late arrival
    can appear as a NEW datapoint rather than as a changed one, and reading (3) — 61 of 122
    requests published no score — is an absence claim, so the series that carried nothing are
    precisely the evidence for it.
    """
    out: list[dict[str, Any]] = []
    for arm_key, arm in (record.get("arms") or {}).items():
        ih = arm.get("identity_half") or {}
        per_series = ih.get("per_series")
        if not isinstance(per_series, list) or not per_series:
            raise ConfigError(f"arm {arm_key} has no identity_half.per_series list")
        buckets = [int(b) for b in (ih.get("our_buckets") or [])]
        if not buckets:
            raise ConfigError(f"arm {arm_key} records no our_buckets")
        period = int(ih.get("period_s") or 0)
        if period != PERIOD_S:
            raise ConfigError(f"arm {arm_key} was read at period {period}, not {PERIOD_S}; the "
                              f"re-read would not be comparable")
        n_score = 0
        for s in per_series:
            if not s.get("is_a_score_series"):
                continue
            n_score += 1
            dps = {}
            for dp in (s.get("datapoints") or []):
                b = dp.get("bucket_s")
                if b is None:
                    raise ConfigError(f"arm {arm_key} series {s.get('name')} has a datapoint "
                                      f"without bucket_s")
                dps[int(b)] = dp
            out.append({
                "arm": arm_key,
                "name": s["name"],
                "dimensions": s.get("dimensions") or [],
                "our_buckets": buckets,
                "recorded": dps,
            })
        if not n_score:
            raise ConfigError(f"arm {arm_key} enumerated no score series; a re-read over zero "
                              f"series would report clean (feedback_zero_file_scan_is_error)")
    return out


def _recorded_readings(record: dict[str, Any], log_record: dict[str, Any]) -> dict[str, Any]:
    """The three §11 readings, as the records state them. Nothing here is typed in."""
    arms = record.get("arms") or {}
    golden = [k for k in arms if k != ARM_ACTIVE_SPACED]
    if len(golden) != 2:
        raise ConfigError(f"expected two golden arms, found {sorted(golden)}")

    n_requests = 0
    for key, arm in arms.items():
        traffic = arm.get("traffic") or {}
        n = traffic.get("n_evaluated")
        if not isinstance(n, int):
            raise ConfigError(f"arm {key} has no integer traffic.n_evaluated")
        n_requests += n

    per_arm = (log_record.get("per_arm") or {})
    if not per_arm:
        raise ConfigError("the log-surface record carries no per_arm block")
    logged: dict[str, dict[str, Any]] = {}
    n_scored = 0
    for key, v in per_arm.items():
        s = v.get("score_sum")
        c = v.get("n_scored_requests")
        if not isinstance(s, (int, float)) or not isinstance(c, int):
            raise ConfigError(f"the log record's arm {key} has no numeric score_sum / "
                              f"n_scored_requests")
        logged[key] = {"score_sum": float(s), "n_scored_requests": c}
        n_scored += c

    per_request = {k: list((arms[k].get("identity_half") or {}).get("per_request_score_series")
                           or []) for k in golden}
    return {
        "n_requests_evaluated": n_requests,
        "n_scored_requests": n_scored,
        "logged_per_arm": logged,
        "golden_arms": sorted(golden),
        "per_request_score_series_in_golden_arms": per_request,
        "harvest_settle_s_at_record_time": HARVEST_SETTLE_S,
    }


# ---------------------------------------------------------------------------
# the re-read
# ---------------------------------------------------------------------------

def _reread(cw: Any, store: Any, series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in series:
        lo, hi = min(s["our_buckets"]), max(s["our_buckets"])
        # One period of margin below and two above: the lower margin catches a datapoint that
        # slipped into the bucket before ours, the upper one covers the recorded window's own
        # tail, so a late arrival adjacent to our buckets is visible rather than cropped.
        start = datetime.fromtimestamp(lo - PERIOD_S, timezone.utc)
        end = datetime.fromtimestamp(hi + 2 * PERIOD_S, timezone.utc)
        rec = capture(store, "get_metric_statistics", cw,
                      Namespace=NS, MetricName=s["name"], Dimensions=s["dimensions"],
                      StartTime=start, EndTime=end, Period=PERIOD_S,
                      Statistics=list(STATISTICS))
        entry = dict(s)
        if not rec.ok:
            entry["error"] = rec.error_code
            entry["reread"] = {}
            out.append(entry)
            continue
        dps: dict[int, dict[str, Any]] = {}
        for dp in (rec.response.get("Datapoints") or []):
            ts = dp.get("Timestamp")
            if ts is None:
                continue
            b = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts)
            dps[b] = {_STAT_KEY[k]: (float(dp[k]) if dp.get(k) is not None else None)
                      for k in STATISTICS}
        entry["error"] = ""
        entry["reread"] = dps
        out.append(entry)
    return out


def _compare(reread: list[dict[str, Any]]) -> dict[str, Any]:
    """Field-by-field, per bucket. The three failure modes are counted separately."""
    changed: list[dict[str, Any]] = []
    vanished: list[dict[str, Any]] = []
    late: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []
    n_compared = 0
    n_exact = 0
    n_fields = 0
    errors = [{"arm": s["arm"], "name": s["name"], "error": s["error"]}
              for s in reread if s["error"]]

    for s in reread:
        if s["error"]:
            continue
        for bucket, want in sorted(s["recorded"].items()):
            got = s["reread"].get(bucket)
            if got is None:
                vanished.append({"arm": s["arm"], "name": s["name"], "bucket_s": bucket,
                                 "recorded": {k: want.get(k) for k in _STAT_KEY.values()}})
                continue
            n_compared += 1
            for field in _STAT_KEY.values():
                a, b = want.get(field), got.get(field)
                if a is None and b is None:
                    continue
                n_fields += 1
                if a is None or b is None:
                    changed.append({"arm": s["arm"], "name": s["name"], "bucket_s": bucket,
                                    "field": field, "recorded": a, "reread": b})
                    continue
                if float(a) == float(b):
                    n_exact += 1
                elif not math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=ABS_TOL):
                    changed.append({"arm": s["arm"], "name": s["name"], "bucket_s": bucket,
                                    "field": field, "recorded": a, "reread": b})
                else:
                    # Within tolerance but not identical. Published rather than folded into
                    # `n_exact`, because the whole reason equality is expected here is that
                    # CloudWatch returns doubles and `json.dumps` round-trips them exactly. A
                    # non-empty list here is a fact about one of the two readers' formatting,
                    # and it must not be invisible behind a passing guard.
                    near.append({"arm": s["arm"], "name": s["name"], "bucket_s": bucket,
                                 "field": field, "recorded": a, "reread": b,
                                 "delta": float(b) - float(a)})
        # A NEW datapoint inside one of OUR buckets is a late arrival, and is the failure mode
        # that would refute reading (3). Datapoints outside our buckets are not comparable —
        # the recorded read window is not reconstructable from the record — so they are counted
        # and reported rather than judged.
        for bucket in sorted(s["reread"]):
            if bucket in s["recorded"]:
                continue
            if bucket in set(s["our_buckets"]):
                late.append({"arm": s["arm"], "name": s["name"], "bucket_s": bucket,
                             "reread": s["reread"][bucket]})

    outside = sum(1 for s in reread if not s["error"]
                  for b in s["reread"]
                  if b not in s["recorded"] and b not in set(s["our_buckets"]))
    return {
        "n_series": len(reread),
        "n_series_with_an_error": len(errors),
        "errors": errors,
        "n_recorded_datapoints": sum(len(s["recorded"]) for s in reread),
        "n_datapoints_compared": n_compared,
        "n_fields_compared": n_fields,
        "n_fields_exactly_equal": n_exact,
        "changed": changed,
        "within_tolerance_but_not_identical": near,
        "vanished": vanished,
        "late_arrivals_in_our_buckets": late,
        "n_datapoints_outside_our_buckets": outside,
    }


def _dim_key(dimensions: list[dict[str, str]]) -> str:
    """A stable name for one dimension COMBINATION."""
    return ",".join(f"{d['Name']}={d['Value']}" for d in sorted(
        dimensions, key=lambda d: (d.get("Name", ""), d.get("Value", ""))))


def _readings_now(reread: list[dict[str, Any]], recorded: dict[str, Any]) -> dict[str, Any]:
    """Re-derive §11's three readings from the re-read alone.

    PER DIMENSION COMBINATION, never summed across them. CloudWatch publishes the same
    observation once per dimension SUBSET it rolls up over — on 2026-08-12 four combinations
    carried byte-identical `ConfidenceScore` datapoints (the fully-qualified set, and three
    roll-ups dropping `PolicyEngine`, `Policy`/`Category`/`Filter`, or both). A total over
    "every score series" therefore counts each observation four times, which is exactly what the
    first run of this file did: it reported 98.4 against a logged 24.6 and 244 scored requests
    out of 122, an impossibility that says the aggregation is wrong rather than the data.

    Comparing per combination is also the stronger check: it asserts every roll-up agrees with
    the logs independently, so a reading cannot rest on having picked the one series that agreed
    (`feedback_label_must_match_computation`).
    """
    golden = set(recorded["golden_arms"])
    # (arm, dim_key) -> {"sum", "sample_count", "dimensions", "n_datapoints"}
    per_combo: dict[tuple[str, str], dict[str, Any]] = {}
    per_request_series: list[dict[str, Any]] = []

    for s in reread:
        if s["error"] or s["name"] != "ConfidenceScore":
            continue
        arm = s["arm"]
        buckets = set(s["our_buckets"])
        dps = [(b, d) for b, d in s["reread"].items() if b in buckets]
        key = (arm, _dim_key(s["dimensions"]))
        slot = per_combo.setdefault(key, {"arm": arm, "dimensions": s["dimensions"],
                                          "sum": 0.0, "sample_count": 0.0, "n_datapoints": 0})
        for _b, d in dps:
            if d.get("sum") is not None:
                slot["sum"] += float(d["sum"])
            if d.get("sample_count") is not None:
                slot["sample_count"] += float(d["sample_count"])
            slot["n_datapoints"] += 1
        if arm in golden and dps and all(
                (d.get("sample_count") is not None and float(d["sample_count"]) == 1.0)
                for _b, d in dps):
            per_request_series.append({"arm": arm, "name": s["name"],
                                       "dimensions": s["dimensions"]})

    logged = recorded["logged_per_arm"]
    sums_agree: dict[str, Any] = {}
    for arm, v in logged.items():
        want = float(v["score_sum"])
        # Only combinations that CARRIED a datapoint in our buckets participate. The namespace
        # holds `ConfidenceScore` series for every policy that has ever run against this gateway
        # — on 2026-08-12, 14 combinations per arm — and the ten belonging to other cases' probe
        # policies read 0.0 over our window, correctly. Counting those as disagreements would
        # make the guard fail for the one reason that is not a defect: a different policy's series
        # is quiet when that policy is not attached.
        combos = {dk: slot for (a, dk), slot in per_combo.items()
                  if a == arm and slot["n_datapoints"] > 0}
        per = {dk: {"metric_sum_on_reread": slot["sum"],
                    "sample_count_on_reread": slot["sample_count"],
                    "agree": math.isclose(want, slot["sum"], rel_tol=1e-9, abs_tol=1e-9)}
               for dk, slot in combos.items()}
        sums_agree[arm] = {
            "logged_sum_day1": want,
            "n_dimension_combinations": len(per),
            "n_agreeing": sum(1 for x in per.values() if x["agree"]),
            "disagreeing": {dk: x for dk, x in per.items() if not x["agree"]},
            "metric_sums_on_reread": sorted({round(x["metric_sum_on_reread"], 9)
                                             for x in per.values()}),
            # A zero-combination arm must not read as agreement
            # (`feedback_zero_file_scan_is_error`).
            "agree": bool(per) and all(x["agree"] for x in per.values()),
        }

    # Scored-request totals, again per combination: each combination should independently see the
    # same 61 of 122. The SET of distinct totals is published rather than one number, so a
    # combination that disagreed could not average away.
    totals: dict[str, float] = {}
    for (arm, dk), slot in per_combo.items():
        if slot["n_datapoints"] <= 0:
            continue
        totals[dk] = totals.get(dk, 0.0) + slot["sample_count"]
    distinct_totals = sorted({int(round(v)) for v in totals.values()})
    n_scored_now = distinct_totals[0] if len(distinct_totals) == 1 else -1
    return {
        "reading_1_logs_reconcile_with_metrics": {
            "per_arm": sums_agree,
            "n_dimension_combinations_per_arm": {a: v["n_dimension_combinations"]
                                                 for a, v in sums_agree.items()},
            "all_agree": all(v["agree"] for v in sums_agree.values()) and bool(sums_agree),
            "why": ("the day-1 per-request LOGGED score sums, re-compared against the metric Sum "
                    "for the same buckets after a day of settle. A late-arriving datapoint would "
                    "have broken this"),
        },
        "reading_2_no_per_request_score_series": {
            "per_request_score_series_now": per_request_series,
            "holds": not per_request_series,
            "recorded": recorded["per_request_score_series_in_golden_arms"],
            "why": ("one request per datapoint is the only shape from which a reader could "
                    "attribute a score to a labelled request, so its absence in the golden arms "
                    "IS the measured half of the FALSE verdict"),
        },
        "reading_3_scores_are_absent_for_clean_requests": {
            "n_requests_evaluated": recorded["n_requests_evaluated"],
            "n_scored_day1": recorded["n_scored_requests"],
            "n_scored_on_reread": n_scored_now,
            "n_unscored_on_reread": (recorded["n_requests_evaluated"] - n_scored_now
                                     if n_scored_now >= 0 else None),
            "holds": n_scored_now == recorded["n_scored_requests"],
            "distinct_totals_across_dimension_combinations": distinct_totals,
            "why_a_set_not_a_number": ("each dimension combination is counted independently; "
                                       "n_scored_on_reread is -1 unless they all agree, so a "
                                       "single disagreeing roll-up fails the guard instead of "
                                       "being averaged into it"),
            "absence_bound_at_record_time_s": HARVEST_SETTLE_S,
            "why": ("F3-10 measured this absence 120 s after the traffic. Re-read a day later, "
                    "the same absence is bounded by the re-read lag instead"),
        },
        "per_dimension_combination": [
            {"arm": slot["arm"], "dimension_combination": dk, "sum": slot["sum"],
             "sample_count": slot["sample_count"], "n_datapoints": slot["n_datapoints"]}
            for (a, dk), slot in sorted(per_combo.items())
        ],
    }


def _guards(*, day: str, today: str, lag_h: float, cmp_: dict[str, Any],
            readings: dict[str, Any], n_series: int) -> dict[str, bool]:
    return {
        "record_day_is_an_earlier_utc_day": day < today,
        "reread_lag_exceeds_the_floor": lag_h >= MIN_LAG_H,
        "every_score_series_was_reread": n_series > 0 and cmp_["n_series"] == n_series,
        "no_read_error": cmp_["n_series_with_an_error"] == 0,
        "every_recorded_datapoint_was_compared": (
            cmp_["n_recorded_datapoints"] > 0
            and cmp_["n_datapoints_compared"] == cmp_["n_recorded_datapoints"]
            and cmp_["n_fields_compared"] > 0),
        "no_datapoint_value_changed": not cmp_["changed"],
        "no_datapoint_vanished": not cmp_["vanished"],
        "no_late_arrival_in_a_recorded_bucket": not cmp_["late_arrivals_in_our_buckets"],
        "detection_total_is_unchanged":
            readings["reading_3_scores_are_absent_for_clean_requests"]["holds"],
        "no_score_series_is_per_request_in_the_golden_arms":
            readings["reading_2_no_per_request_score_series"]["holds"],
        "logged_sums_still_match_the_metric_sums":
            readings["reading_1_logs_reconcile_with_metrics"]["all_agree"],
    }


def _dry_run(record: Path, log_record: Path) -> int:
    print(f"{PARENT_CASE} window audit dry run — no AWS call, no mutation\n")
    if not record.is_file() or not log_record.is_file():
        print(f"  MISSING: {record if not record.is_file() else log_record}")
        return 2
    rec = _load(record, "the record")
    logrec = _load(log_record, "the log-surface record")
    day, t0, t1 = _observation_day(rec)
    series = _recorded_score_series(rec)
    readings = _recorded_readings(rec, logrec)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lag_h = (datetime.now(timezone.utc).timestamp() - t1) / 3600.0
    print(f"  record      {record.relative_to(ROOT)}")
    print(f"  log record  {log_record.relative_to(ROOT)}")
    print(f"  observation day {day} (window {t1 - t0:.1f}s), UTC today {today}, "
          f"lag {lag_h:.2f} h (floor {MIN_LAG_H:.0f} h)")
    print(f"  {len(series)} score series to re-read across "
          f"{len(sorted({s['arm'] for s in series}))} arms, "
          f"{sum(len(s['recorded']) for s in series)} recorded datapoints to compare")
    print(f"  readings to re-derive: {readings['n_scored_requests']} scored of "
          f"{readings['n_requests_evaluated']} evaluated; logged sums "
          f"{ {k: v['score_sum'] for k, v in readings['logged_per_arm'].items()} }")
    print(f"  calls: get_metric_statistics x{len(series)}  mutations: 0  billable guardrail "
          f"traffic: none")
    print("  no verdict: F3-10's oracle names CloudWatch metrics alone and its FALSE stands; "
          "this read is provenance for the closed window, not a replication of it")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(PARENT_CASE, __doc__)
    ap.add_argument("--record", default=str(DEFAULT_RECORD),
                    help="the F3-10 analysis record whose window is re-read")
    ap.add_argument("--log-record", default=str(DEFAULT_LOG_RECORD),
                    help="the 08b log-surface record holding the per-request logged score sums")
    ap.add_argument("--out", default=OUT_NAME, help="file name under results/phase1/")
    args = ap.parse_args(argv)
    record_path = Path(args.record)
    log_path = Path(args.log_record)

    if args.dry_run:
        return _dry_run(record_path, log_path)

    record = _load(record_path, "the record")
    log_record = _load(log_path, "the log-surface record")
    day, t0, t1 = _observation_day(record)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lag_h = (datetime.now(timezone.utc).timestamp() - t1) / 3600.0
    # Refused rather than reported as a failed guard: a same-day or minutes-old re-read is not a
    # weaker version of this measurement, it is a different one, and writing it into
    # `results/phase1/` under this file name would put a number there that reads as the later
    # re-read the finding cites.
    if day >= today:
        raise ConfigError(f"the record's observation day is {day} and UTC today is {today}; a "
                          f"re-read on the same day cannot widen an absence bound")
    if lag_h < MIN_LAG_H:
        raise ConfigError(f"only {lag_h:.2f} h have passed since the last recorded bucket; the "
                          f"floor is {MIN_LAG_H:.0f} h")

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    # For the side effect: registering the account id with the masker, so `R.mask_text` below can
    # mask it outside ARN position (DEV-P1-13, DEV-P4-24).
    A.account_id(fc)
    cw = fc.client("cloudwatch")
    store = EvidenceStore(run_id, FAMILY, EVIDENCE_CASE)
    store.write_environment()

    gw = state.find("gateway", "main")
    if not gw:
        raise ConfigError("the main gateway is not in state.json")
    gateway_id = gw.ids["gateway_id"]
    if record.get("gateway_id") and record["gateway_id"] != gateway_id:
        raise ConfigError(f"{record_path.name} was written against gateway "
                          f"{record['gateway_id']} but the ledger's main gateway is {gateway_id}")

    series = _recorded_score_series(record)
    recorded = _recorded_readings(record, log_record)
    print(f"{PARENT_CASE} window audit — gateway {gateway_id}, region {region}")
    print(f"  record {record_path.name}: day {day}, {t1 - t0:.1f}s window, "
          f"{len(series)} score series, {sum(len(s['recorded']) for s in series)} datapoints")
    print(f"  UTC today {today}, lag {lag_h:.2f} h (floor {MIN_LAG_H:.0f} h, "
          f"record-time absence bound {HARVEST_SETTLE_S:.0f} s)")

    got = _reread(cw, store, series)
    cmp_ = _compare(got)
    readings = _readings_now(got, recorded)
    guards = _guards(day=day, today=today, lag_h=lag_h, cmp_=cmp_, readings=readings,
                     n_series=len(series))
    failed = sorted(k for k, v in guards.items() if not v)

    payload = {
        "kind": "SUPPLEMENTARY_READ",
        "case_id": PARENT_CASE,
        "family": FAMILY,
        "run_id": run_id,
        "region": region,
        "gateway_id": gateway_id,
        "why_no_verdict": ("F3-10's sealed oracle scopes its question to CloudWatch metrics "
                           "alone and that verdict (FALSE) stands. This file re-reads the stored "
                           "form of one closed window on a later day; it is provenance for three "
                           "of the finding's readings, not a replication and not a re-scoring"),
        "source_record": str(record_path.relative_to(ROOT)),
        "source_log_record": str(log_path.relative_to(ROOT)),
        "observation_day": day,
        "reread_utc_day": today,
        "reread_lag_h": round(lag_h, 3),
        "reread_lag_floor_h": MIN_LAG_H,
        "absence_bound_widened_from_s_to_h": [HARVEST_SETTLE_S, round(lag_h, 3)],
        "window": {"t0": t0, "t1": t1, "span_s": round(t1 - t0, 3), "period_s": PERIOD_S},
        "namespace": NS,
        "statistics_compared": list(STATISTICS),
        "float_tolerance": {"rel_tol": REL_TOL, "abs_tol": ABS_TOL,
                            "why": "equality is expected to be exact; n_fields_exactly_equal is "
                                   "reported separately so a tolerance can never hide a change"},
        "recorded_readings": recorded,
        "comparison": cmp_,
        "readings_on_reread": readings,
        "guards": guards,
        "guard_names": list(GUARDS),
        "failed_guards": failed,
        "probe": {"category": GUARDRAIL_CATEGORY, "threshold": GUARDRAIL_THRESHOLD},
        "what_this_does_not_prove": [
            "no verdict: F3-10's oracle names CloudWatch metrics alone and the FALSE stands",
            "not a replication: re-reading a closed window cannot re-run the pipeline, so it "
            "cannot distinguish 'never published' from 'lost before publication'. The fresh "
            "window on a later day is what replicates; this widens the bound on the absence",
            "nothing about any other day, region, policy or filter function",
            "no traffic and no mutation: GetMetricStatistics only, so nothing here can have "
            "changed what it measured",
        ],
    }
    text = json.dumps(payload, indent=2, sort_keys=True, default=str, ensure_ascii=False) + "\n"
    out_path = ROOT / "results" / "phase1" / args.out
    # Masked in `results/`, unmasked in `evidence/` — the same split `P.emit` makes (DEV-P1-13).
    # `P.emit` is not used because it would write `results/phase1/F3-10.json` and overwrite a
    # recorded verdict with a read.
    out_path.write_text(R.mask_text(text), encoding="utf-8")
    (store.dir / "analysis.json").write_text(text, encoding="utf-8")
    store.write_summary({"analysis_file": "analysis.json", "case_id": PARENT_CASE,
                         "kind": "SUPPLEMENTARY_READ"})

    r1 = readings["reading_1_logs_reconcile_with_metrics"]
    r2 = readings["reading_2_no_per_request_score_series"]
    r3 = readings["reading_3_scores_are_absent_for_clean_requests"]
    print(f"  compared {cmp_['n_datapoints_compared']}/{cmp_['n_recorded_datapoints']} datapoints,"
          f" {cmp_['n_fields_exactly_equal']}/{cmp_['n_fields_compared']} fields exactly equal")
    print(f"  changed={len(cmp_['changed'])} vanished={len(cmp_['vanished'])} "
          f"late_arrivals={len(cmp_['late_arrivals_in_our_buckets'])} "
          f"(outside our buckets, not judged: {cmp_['n_datapoints_outside_our_buckets']})")
    shown = {k: (v["logged_sum_day1"], v["metric_sums_on_reread"],
                 "{}/{} combos".format(v["n_agreeing"], v["n_dimension_combinations"]))
             for k, v in r1["per_arm"].items()}
    print(f"  reading 1 logs<->metrics: all_agree={r1['all_agree']}  {shown}")
    print(f"  reading 2 no per-request score series in the golden arms: holds={r2['holds']}")
    print(f"  reading 3 {r3['n_scored_on_reread']} scored of {r3['n_requests_evaluated']} "
          f"evaluated (day 1: {r3['n_scored_day1']}), holds={r3['holds']}; absence bound "
          f"{HARVEST_SETTLE_S:.0f}s -> {lag_h:.1f}h")
    print(f"  guards: {len(GUARDS) - len(failed)}/{len(GUARDS)} pass"
          + (f"  FAILED: {', '.join(failed)}" if failed else ""))
    print(f"  wrote {out_path.relative_to(ROOT)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
