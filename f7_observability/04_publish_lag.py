#!/usr/bin/env python3
"""F7-6 and F7-7: how long until a metric is queryable, and what grid are its timestamps on?

    python3 f7_observability/04_publish_lag.py --dry-run
    python3 f7_observability/04_publish_lag.py --n 3     # smoke, ~10 min
    python3 f7_observability/04_publish_lag.py           # n=30, ~75-120 min

Two sealed oracles, one cell, one script:

    F7-6  LAG_FLOOR      "Measured p50/p90/max lag from request to queryable datapoint, n=30.
                          FALSE for every 6.4 alarm whose evaluation period is below the
                          measured p90 lag: such an alarm cannot fire reliably, and 6.4 does
                          not say so. A lag at or below 60s leaves the 1-minute alarms
                          defensible."
    F7-7  QUANTIZATION   "TRUE if datapoint timestamps quantize to 60s; FALSE if finer or
                          coarser."  (thresholds=(60.0,), unit='s')

They share `publish_lag_cell` (n=30), and the sealed cell rule is explicit that n=30 "supports
p50 and p90; it does NOT support a p99 lag claim and none is made". So no p99 appears in the
output, not even as a courtesy figure — a number printed beside a verdict gets quoted.

WHY THE SAME 30 REQUESTS SERVE BOTH
-----------------------------------
The two cases are two questions about one event: a datapoint becoming visible. F7-6 asks
*when*, F7-7 asks *where on the clock*. Measuring them from separate traffic would mean two
n=30 cells drawn at different times of day against a service whose batching we are trying to
characterise. The 30 trials here each contribute one lag and one datapoint timestamp.

THE TRIALS MUST LAND IN THIRTY DISTINCT MINUTE BUCKETS, AND THAT IS A GUARD
--------------------------------------------------------------------------
CloudWatch aggregates per period. Fire 30 requests inside one minute and they produce ONE
datapoint: the second request's "time to visible" would be measured against a datapoint the
first request had already made visible, so 29 of the 30 lags would be near zero and the p90
would be an artifact of the send pattern. So trials run strictly serially — send, poll until
visible, record, next — and `distinct_minute_buckets` asserts that no two trials share a
bucket. That is also why this script takes an hour or more: the measurement's resolution is
one minute, and there is no way to buy it back with concurrency.

THE DATAPOINT MUST BE OURS
--------------------------
This account holds six pre-existing READY gateways and several harness runtimes publishing
into `AWS/Bedrock-AgentCore`. A namespace-wide `SEARCH` would stop the clock the moment
*anybody's* datapoint appeared in our bucket, which biases the lag **downwards** — the same
defect as reading the shared `aws/spans` group without an ARN filter, and in the same
self-flattering direction. So the query is pinned to the exact dimension set whose values
identify our gateway, discovered from F7-1/2/3's inventory rather than guessed, and
`datapoint_is_ours` is a guard. If no dimension distinguishes our gateway, that is not a
detail to work around: it would mean per-gateway alarming is impossible, the case goes
INCONCLUSIVE, and the fact is recorded as amendment material in its own right.

WHY THE QUANTIZATION READ USES A SUB-MINUTE PERIOD
--------------------------------------------------
This is the trap the sealed binding's own note warns about in a different form ("unit='s' is
load-bearing: ... an inferred ms conversion made this threshold 60000, which every observation
would have satisfied"). The metric-timestamp version is worse, because it looks correct:

    ask CloudWatch for Period=60  ->  every timestamp returned is a multiple of 60
    ->  "quantizes to 60s"  ->  TRUE, always, for any service behaviour whatsoever.

The 60-second grid would be an artifact of our own query parameter. So the quantization read
uses `QUANT_PERIOD_S = 1`, within CloudWatch's 3-hour window for sub-minute periods, and the
verdict is taken on those timestamps. If the API refuses the sub-minute period or coerces it,
that is detected and the case goes INCONCLUSIVE rather than publishing a TRUE that our own
query manufactured. The guard is `quant_period_is_subminute`.

A GAP BETWEEN THE SEALED ORACLE TEXT AND THE SEALED DECISION CODE, REPORTED NOT PATCHED
---------------------------------------------------------------------------------------
F7-7's oracle text says "FALSE if finer **or coarser**". The sealed code in `lib/oracle.py`
decides on `abs(math.remainder(t, 60)) < 1e-6` for every timestamp — which detects *finer*
(an off-grid timestamp) but **cannot** detect coarser: timestamps on a 300-second grid are all
multiples of 60, so 5-minute batching would satisfy the check and publish TRUE. `lib/oracle.py`
is a sealed bound artifact and is not edited. So the coarser direction is measured here
separately, as the minimum positive gap between consecutive datapoint timestamps, reported in
the payload under `coarser_check`, and flagged loudly if it exceeds 60s. The verdict remains
whatever the sealed code says; the payload states plainly when the sealed code would have
missed something. Amending the decision rule after seeing data would be the worse error.

WHICH ALARM PERIODS ARE SCORED, AND THE ONE THE ORACLE MENTIONS BUT §6.4 DOES NOT
--------------------------------------------------------------------------------
`alarm_periods_s` is the list of evaluation periods **§6.4 actually states**. Of its seven
alarm rows, exactly one states a period — "Block rate > 20% in 5 min" = 300s. The other six
state a condition and no evaluation window at all, which means they cannot be checked here and
cannot be implemented as written either; that is recorded as amendment material.

The oracle's closing sentence — "A lag at or below 60s leaves the 1-minute alarms defensible"
— refers to the document's separate claim that gateway metrics are "batched at 1-minute
intervals". No §6.4 row states a 60-second period, so 60.0 is **not** put into the scored
`alarm_periods_s`: adding an alarm the document does not state, in order to fail it, would be
manufacturing a FALSE. The 60s comparison is computed and reported beside the verdict instead.

COST
----
n gateway `tools/call` (n=30 by default) plus polling `GetMetricData`. **Zero text units.** No
mutation, no resource created or changed. Wall clock, not dollars, is the expense: at least one
minute of forced serialisation per trial.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                   # noqa: E402
import mcp as M                                          # noqa: E402
import oracle as O                                       # noqa: E402
import phase1 as P                                       # noqa: E402
import stats as S                                        # noqa: E402
import testbed as T                                      # noqa: E402
from evidence import EvidenceStore, capture              # noqa: E402

FAMILY = "f7"
CASES = ("F7-6", "F7-7")
NS = "AWS/Bedrock-AgentCore"

TOOL = "echo"
TEXT = "f7-6/7 publish lag"
ARM = "lag"
PLANNED_N = 30                       # publish_lag_cell, sealed

# Which metric's visibility is timed. PRE-COMMITTED ORDER, chosen before any lag was seen: the
# first entry that F7-2/F7-1 measured as published is used. Ordered by how directly a single
# gateway request should produce a datapoint, so the lag is a property of publishing rather
# than of some condition that also has to be met.
METRIC_PREFERENCE = ("Invocations", "Latency", "Duration", "TargetExecutionTime")

# Substrings that make a dimension VALUE identifiable as our gateway. Checked against the
# values F7-1/2/3's inventory recorded, so the dimension NAME never has to be guessed.
POLL_PERIOD_S = 60                   # for the lag read: the standard grid
QUANT_PERIOD_S = 1                   # for the quantization read: MUST be sub-minute
QUANT_MAX_LOOKBACK_H = 3             # CloudWatch allows sub-minute periods only within 3h
POLL_EVERY_S = 10.0
PER_TRIAL_TIMEOUT_S = 600.0
PREFLIGHT_LOOKBACK_H = 6             # the chosen series must have data here before it is timed
INTER_TRIAL_GAP_S = 5.0              # margin PAST the next bucket edge; distinctness still asserted

# §6.4's alarm rows. `period_s=None` means the row states a condition and no evaluation window.
# Transcribed from the sealed claim rows, and the None entries are the point of the table.
S64_ALARMS = (
    ("Gateway guardrail latency spike", "Latency > P99 + 50%", None),
    ("Bedrock guardrail latency spike", "InvocationLatency > P99 + 50%", None),
    ("End-to-end session latency", "Total duration > SLA threshold", None),
    ("Policy evaluation errors", "MismatchErrors > 0", None),
    ("High rejection rate", "Block rate > 20% in 5 min", 300.0),
    ("Guardrail invocation failures", "InvocationServerErrors > 0", None),
    ("Throttling", "InvocationThrottles > 0", None),
)

# The oracle's aside, computed and reported but NOT scored — see the module docstring.
DEFENSIBILITY_NOTE_PERIOD_S = 60.0

GUARDS = ("calls_reached_gateway", "distinct_minute_buckets", "datapoint_is_ours",
          "all_trials_became_visible", "quant_period_is_subminute", "n_met")


class ConfigError(RuntimeError):
    """The testbed or the reading is not in a state that can carry a verdict."""


def _bucket(epoch_s: float, period_s: int = POLL_PERIOD_S) -> int:
    """The period-aligned bucket start a timestamp falls in."""
    return int(epoch_s // period_s * period_s)


def _pick_metric_and_dimensions(gateway_id: str) -> dict[str, Any]:
    """Choose the metric to time, and the dimension set that makes a datapoint ours.

    Both are read off F7-1/2/3's recorded inventory rather than guessed. Reading them from disk
    is deliberate: `list_metrics` is a live call whose answer could differ from the one the
    published F7-1/F7-2 verdicts were taken on, and then this script would be timing a metric
    whose existence no verdict covers.
    """
    out: dict[str, Any] = {"metric": "", "dimensions": [], "source": "", "why": "",
                           "candidates_considered": list(METRIC_PREFERENCE), "problems": []}
    published: dict[str, bool] = {}
    dim_values: dict[str, dict[str, list[str]]] = {}
    for case in ("F7-2", "F7-1"):
        p = ROOT / "results" / "phase1" / f"{case}.json"
        if not p.is_file():
            out["problems"].append(f"{case}.json is absent")
            continue
        rec = json.loads(p.read_text())
        out.setdefault("precondition_verdicts", {})[case] = rec.get("verdict")
        for row in rec.get("per_metric") or []:
            published.setdefault(row["metric"], bool(row.get("published")))
        for nm, dims in (rec.get("inventory_dimension_values") or {}).items():
            dim_values.setdefault(nm, {}).update(dims)

    out["published_per_metric"] = published
    for cand in METRIC_PREFERENCE:
        if published.get(cand):
            out["metric"] = cand
            out["source"] = "F7-2/F7-1 recorded inventory"
            out["why"] = (f"{cand} is the first entry of the pre-committed preference order "
                          f"that F7-2/F7-1 measured as published; the order was fixed before "
                          f"any lag was observed")
            break
    if not out["metric"]:
        out["problems"].append(
            "no metric in the pre-committed preference order was measured as published, so "
            "there is nothing whose publish lag could be timed")
        return out

    # The dimension NAMES that carry our gateway id, recorded for the evidence. The VALUES are
    # not assembled into a query here — see `_published_combinations` for why.
    dims = dim_values.get(out["metric"], {})
    out["dimension_names_available"] = sorted(dims)
    out["dimension_names_carrying_our_gateway"] = sorted(
        dname for dname, values in dims.items()
        if gateway_id and any(gateway_id in v for v in values))
    if not out["dimension_names_carrying_our_gateway"]:
        out["problems"].append(
            f"no dimension of {out['metric']} carries a value containing our gateway id "
            f"{gateway_id!r}. A lag timed on a namespace-wide read would stop the clock on "
            f"another gateway's datapoint, so this is not worked around. It is also a finding: "
            f"an alarm cannot be scoped to one gateway on a dimension that does not exist")
    return out


def _published_combinations(cw, store, metric: str, gateway_id: str) -> dict[str, Any]:
    """The dimension COMBINATIONS this metric is actually published under, for our gateway.

    Why this exists, and why the previous version of this step was wrong
    -------------------------------------------------------------------
    `ListMetrics` publishes *combinations* — an ordered `Dimensions` list of name/value pairs,
    one entry per series that exists. F7-1/2/3 record a flattening of those: `dimension_values`
    maps each NAME to every VALUE seen under it, across all combinations. Taking one value from
    each name that mentions our gateway therefore builds a set that may never have been
    published at all.

    MEASURED 2026-08-11, and it cost the first run of this script: `Invocations` is published
    at our gateway under `[OperationName, TargetResource]`, and elsewhere in the namespace
    under `[Operation, Resource]` and fifteen other combinations. Our gateway id appears in a
    `TargetResource` value **and** in a `Resource` value, so the flattening produced

        [{Resource: arn:...:gateway/grx-gw-...}, {TargetResource: grx-gw-...}]

    a two-dimension set that no series carries. `GetMetricData` answers such a query with
    `Complete` and zero values — not an error — so trial 1 polled for the full 600s timeout and
    would have been followed by twenty-nine more. F7-6 would then have published "a gateway
    request's datapoint never becomes visible" as a property of the SERVICE, off a query that
    could not have returned anything whatever the service did. Same shape as DEV-P4-04: a read
    built from a guess about the shape of the telemetry, scored as a fact about the telemetry.

    So the combination is read live and whole, then *proved* to carry data before it is timed.
    The recorded inventory still gates WHICH metric name may be timed — that part is unchanged,
    because a metric no published verdict covers should not be the instrument here. This call
    only decides which of that metric's real series is ours.
    """
    out: dict[str, Any] = {"metric": metric, "candidates": [], "chosen": None,
                           "why": "", "problems": []}
    combos: list[list[dict[str, str]]] = []
    token = None
    while True:
        kw = {"Namespace": NS, "MetricName": metric}
        if token:
            kw["NextToken"] = token
        rec = capture(store, "list_metrics", cw, **kw)
        if not rec.ok:
            out["problems"].append(f"ListMetrics({metric}) failed: {rec.error_code}")
            return out
        for m in rec.response.get("Metrics") or []:
            combos.append([{"Name": d["Name"], "Value": d["Value"]}
                           for d in (m.get("Dimensions") or [])])
        token = rec.response.get("NextToken")
        if not token:
            break

    out["n_series_in_namespace"] = len(combos)
    ours = [c for c in combos if gateway_id and any(gateway_id in d["Value"] for d in c)]
    # Most specific first: a combination naming more dimensions is a narrower filter, and a
    # narrower filter is less likely to stop the clock on someone else's datapoint.
    ours.sort(key=lambda c: (-len(c), [d["Name"] for d in c]))
    if not ours:
        out["problems"].append(
            f"no published series of {metric} names gateway {gateway_id!r}")
        return out
    out["candidates"] = ours
    return out


def _combination_carries_data(cw, store, metric: str, dimensions: list[dict[str, str]], *,
                              hours: int, now: datetime) -> dict[str, Any]:
    """Pre-flight: does this exact combination have datapoints in the recent past?

    A combination `ListMetrics` returns has existed at some point in the retention window; that
    is not the same as having data in the window this script is about to poll. The check is
    cheap, it is the guard that makes a 600s-per-trial timeout mean something, and its result is
    recorded either way — a chosen combination with a stated recent bucket count is auditable,
    while "we polled and saw nothing" is not.
    """
    rec = capture(store, "get_metric_statistics", cw,
                  Namespace=NS, MetricName=metric, Dimensions=dimensions,
                  StartTime=now - timedelta(hours=hours), EndTime=now,
                  Period=POLL_PERIOD_S, Statistics=["Sum", "SampleCount"])
    if not rec.ok:
        return {"ok": False, "n_buckets": 0, "error": rec.error_code}
    dps = rec.response.get("Datapoints") or []
    return {"ok": bool(dps), "n_buckets": len(dps),
            "latest": max((str(d["Timestamp"]) for d in dps), default=""),
            "hours_looked_back": hours}


def _datapoints(cw, store, metric: str, dimensions: list[dict[str, str]], *,
                start: datetime, end: datetime, period: int) -> dict[str, Any]:
    """One dimensioned GetMetricData read. Returns timestamps as epoch seconds.

    Dimensioned rather than SEARCH-based on purpose: here an exact dimension match is what
    makes the datapoint attributable to our gateway, which is the opposite of F7-1's situation,
    where an exact match would have manufactured absences. The two scripts differ because the
    questions differ — F7-1 asks "does this name publish at all", this asks "is this datapoint
    ours".
    """
    q = {"Id": "d0", "MetricStat": {
        "Metric": {"Namespace": NS, "MetricName": metric, "Dimensions": dimensions},
        "Period": period, "Stat": "Sum"}, "ReturnData": True}
    rec = capture(store, "get_metric_data", cw, MetricDataQueries=[q],
                  StartTime=start, EndTime=end, ScanBy="TimestampAscending")
    rec.raise_for_status()
    resp = rec.response or {}
    res = (resp.get("MetricDataResults") or [{}])[0]
    ts = [t.timestamp() for t in (res.get("Timestamps") or [])]
    return {"timestamps_s": ts, "values": list(res.get("Values") or []),
            "label": res.get("Label", ""),
            "status": res.get("StatusCode", ""),
            "messages": resp.get("Messages") or []}


def _quant_read(cw, store, metric: str, dimensions: list[dict[str, str]],
                *, minutes: int) -> dict[str, Any]:
    """The quantization read, at a SUB-MINUTE period. See the module docstring.

    Returns `period_honoured=False` if CloudWatch would not answer at a sub-minute period, in
    which case the case must go INCONCLUSIVE: a 60s grid observed through a 60s query is an
    artifact of the query.
    """
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(minutes=min(minutes, QUANT_MAX_LOOKBACK_H * 60 - 5))
    out: dict[str, Any] = {"period_requested_s": QUANT_PERIOD_S,
                           "start": start.isoformat(), "end": end.isoformat(),
                           "period_honoured": False, "error": ""}
    try:
        r = _datapoints(cw, store, metric, dimensions, start=start, end=end,
                        period=QUANT_PERIOD_S)
    except Exception as exc:                              # noqa: BLE001 - recorded, not hidden
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["why_it_matters"] = (
            "a sub-minute period was refused, so the only available read is at 60s, and a 60s "
            "grid seen through a 60s query says nothing about the service. F7-7 cannot be "
            "decided from that")
        return out
    ts = sorted(r["timestamps_s"])
    gaps = [round(b - a, 6) for a, b in zip(ts, ts[1:])]
    positive = [g for g in gaps if g > 0]
    out.update({
        "period_honoured": True,
        "n_datapoints": len(ts), "timestamps_s": ts,
        "offsets_from_60s_grid_s": [round(abs(math.remainder(t, 60.0)), 6) for t in ts],
        "seconds_field_all_zero": all(int(t) % 60 == 0 for t in ts),
        "gaps_s": gaps,
        "min_positive_gap_s": min(positive) if positive else None,
        "distinct_gaps_s": sorted(set(positive)),
    })
    return out


def main(argv: list[str] | None = None) -> int:                     # noqa: C901, PLR0915
    ap = P.parser(CASES[0], __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else PLANNED_N
    is_smoke = args.n is not None

    stated = [a for a in S64_ALARMS if a[2] is not None]
    unstated = [a for a in S64_ALARMS if a[2] is None]

    if args.dry_run:
        for case in CASES:
            P.dry_run_banner(
                case, [(ARM, "serial trials: send, poll until the datapoint is queryable", n)],
                operations={"tools/call": n}, mutations=0, billable=False, text_units=0,
                text_units_why="no ApplyGuardrail and no guardrail is created",
                extra=[
                    f"both cases share the sealed `publish_lag_cell` (n={PLANNED_N}), so ONE "
                    f"set of {PLANNED_N} trials contributes one lag and one datapoint "
                    f"timestamp each; separate traffic would mean two cells drawn at "
                    f"different times against the batching we are trying to characterise",
                    "the sealed cell rule states n=30 supports p50 and p90 and does NOT "
                    "support a p99 lag claim, so no p99 is printed — a number beside a verdict "
                    "gets quoted",
                    "trials run STRICTLY SERIALLY and must land in distinct minute buckets: 30 "
                    "requests inside one minute produce ONE datapoint, so 29 lags would be "
                    "measured against a datapoint the first request already made visible. "
                    "`distinct_minute_buckets` is a guard, and it is why this takes over an hour",
                    "the polled query is pinned to the dimension set whose VALUE contains our "
                    "gateway id, discovered from F7-1/2/3's recorded inventory rather than "
                    "guessed. A namespace-wide SEARCH would stop the clock on one of the six "
                    "pre-existing gateways' datapoints and bias the lag DOWNWARDS",
                    f"the metric timed is the first of {list(METRIC_PREFERENCE)} that F7-2/F7-1 "
                    f"measured as published — an order fixed before any lag was seen",
                    f"F7-7's read uses Period={QUANT_PERIOD_S}s, NOT 60s. Asking CloudWatch "
                    f"for Period=60 returns timestamps that are multiples of 60 by "
                    f"construction, which would publish TRUE for any service behaviour "
                    f"whatsoever. If the sub-minute period is refused, F7-7 is INCONCLUSIVE",
                    "the sealed F7-7 code checks remainder(t, 60) < 1e-6, which detects a FINER "
                    "grid but cannot detect a COARSER one (300s timestamps are also multiples "
                    "of 60). lib/oracle.py is sealed and is NOT edited; the coarser direction "
                    "is measured separately and reported under `coarser_check`",
                    f"scored alarm periods are the ones §6.4 STATES: {len(stated)} of "
                    f"{len(S64_ALARMS)} rows ({[a[1] for a in stated]}). The other "
                    f"{len(unstated)} state a condition and no evaluation window, so they "
                    f"cannot be checked — and cannot be implemented as written either, which "
                    f"is recorded as amendment material",
                    f"the oracle's aside about {DEFENSIBILITY_NOTE_PERIOD_S:.0f}s is computed "
                    f"and reported but NOT added to the scored periods: no §6.4 row states a "
                    f"60s window, and adding an alarm the document does not state in order to "
                    f"fail it would manufacture a FALSE",
                    f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}",
                ])
            print()
        return 0

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    cw = fc.client("cloudwatch")
    store = EvidenceStore(run_id, FAMILY, "F7-6_7")
    store.write_environment()

    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    gateway_id = (gw.ids.get("gateway_id") or gw.name or "") if gw else ""
    tool_name = ""
    if tgt:
        tool_name = next((a for a in (tgt.ids.get("cedar_action_ids") or [])
                          if a.endswith(f"___{TOOL}")), "")

    pick = _pick_metric_and_dimensions(gateway_id)
    # The combination, read live and whole, then proved to carry data. `_pick_...` decides only
    # WHICH metric name may be timed; assembling a query out of its per-name value lists is the
    # error this pre-flight exists to make impossible (see `_published_combinations`).
    now_pre = datetime.now(timezone.utc).replace(microsecond=0)
    combos = _published_combinations(cw, store, pick["metric"], gateway_id) \
        if pick["metric"] else {"candidates": [], "problems": ["no metric was chosen"]}
    tried: list[dict[str, Any]] = []
    for cand in combos.get("candidates") or []:
        chk = _combination_carries_data(cw, store, pick["metric"], cand,
                                        hours=PREFLIGHT_LOOKBACK_H, now=now_pre)
        tried.append({"dimensions": cand, **chk})
        if chk["ok"]:
            combos["chosen"] = cand
            combos["why"] = (
                f"the most specific published series of {pick['metric']} naming this gateway "
                f"that also has datapoints in the last {PREFLIGHT_LOOKBACK_H}h "
                f"({chk['n_buckets']} buckets, latest {chk['latest']})")
            break
    combos["preflight"] = tried
    if not combos.get("chosen"):
        combos["problems"].append(
            f"none of the {len(combos.get('candidates') or [])} published series naming this "
            f"gateway has a datapoint in the last {PREFLIGHT_LOOKBACK_H}h. Polling one for "
            f"{PER_TRIAL_TIMEOUT_S:.0f}s per trial would time out {n} times and the run would "
            f"report the timeout as a publish lag")
    pick["dimensions"] = combos.get("chosen") or []
    pick["combinations"] = combos
    pick["problems"].extend(combos.get("problems") or [])
    common: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(), "namespace": NS,
        "gateway_id": gateway_id, "tool_name": tool_name,
        "cell": "publish_lag_cell", "planned_n_cell": PLANNED_N, "n_requested": n,
        "metric_choice": pick,
        "instrument": {
            "lag": (f"serial trials; per trial, send one tool call at t_send and poll "
                    f"GetMetricData every {POLL_EVERY_S:.0f}s until a datapoint exists at the "
                    f"{POLL_PERIOD_S}s bucket containing t_send. lag = t_visible - t_send"),
            "why_serial": ("CloudWatch aggregates per period, so concurrent trials in one "
                           "bucket share a datapoint and 29 of 30 lags would be near zero"),
            "quantization": (f"a separate read at Period={QUANT_PERIOD_S}s, because a 60s grid "
                             f"observed through a 60s query is an artifact of the query"),
            "attribution": ("the polled query is dimensioned to our gateway; a namespace-wide "
                            "read would stop the clock on another gateway's datapoint and bias "
                            "the lag downwards"),
        },
        "s6_4_alarms": {
            "rows": [{"name": a[0], "condition": a[1], "stated_period_s": a[2]}
                     for a in S64_ALARMS],
            "n_rows": len(S64_ALARMS), "n_with_stated_period": len(stated),
            "scored_periods_s": [a[2] for a in stated],
            "amendment_material": (
                f"{len(unstated)} of {len(S64_ALARMS)} §6.4 alarm rows state a condition and no "
                f"evaluation period. F7-6 cannot check them, and an operator cannot implement "
                f"them as written: 'MismatchErrors > 0' is not an alarm until a window is "
                f"named. That omission is a document defect independent of whatever lag is "
                f"measured here"),
            "why_60s_is_not_scored": (
                "the oracle's closing sentence mentions 1-minute alarms because the document "
                "elsewhere claims gateway metrics are batched at 1-minute intervals. No §6.4 "
                "row states a 60s window, so 60s is reported beside the verdict and not added "
                "to the scored periods — adding an alarm the document does not state, in order "
                "to fail it, would manufacture a FALSE"),
        },
        "no_p99": ("the sealed publish_lag_cell rule states n=30 supports p50 and p90 and does "
                   "NOT support a p99 lag claim. None is computed"),
        "guard_names": list(GUARDS),
    }

    def bail(reason: str, **extra: Any) -> int:
        for case in CASES:
            rec = O.not_measured(case, reason)
            P.emit(case, rec, {**common, **extra}, store)
        print(f"  INCONCLUSIVE (both cases): {reason}")
        return 2

    if pick["problems"] or not pick["metric"] or not pick["dimensions"]:
        return bail("the lag could not be attributed to our own gateway's datapoints: "
                    + "; ".join(pick["problems"] or ["no metric or dimension resolved"]))
    if not tool_name or not gw:
        return bail("no gateway/main or no ___echo action id in the ledger, so no request "
                    "could be sent whose datapoint's visibility could be timed")

    metric, dimensions = pick["metric"], pick["dimensions"]
    print(f"F7-6/7 — publish lag, run_id={run_id}, region={region}")
    print(f"  timing {NS}/{metric} dimensioned to {dimensions}")
    print(f"  {n} serial trials, poll every {POLL_EVERY_S:.0f}s, "
          f"timeout {PER_TRIAL_TIMEOUT_S:.0f}s per trial")

    client = M.client_for(gw.ids["gateway_url"], fc, store=store,
                          policy_session_id=M.policy_session_id(run_id, ARM),
                          session_timeout_s=int(gw.ids.get("session_timeout_s", 900)))
    try:
        client.initialize()
    except M.McpTransportError as exc:
        return bail(f"the MCP client could not be established, so no request was made: {exc}")

    trials: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        # Baseline first: which buckets already hold a datapoint BEFORE this trial's request.
        # Without it, a datapoint left over from a previous trial in the same bucket would read
        # as "instantly visible" — the very confound the distinctness guard also defends.
        t_send_probe = time.time()
        pre_start = datetime.fromtimestamp(_bucket(t_send_probe) - 2 * POLL_PERIOD_S,
                                           timezone.utc)
        pre = _datapoints(cw, store, metric, dimensions,
                          start=pre_start,
                          end=datetime.fromtimestamp(t_send_probe + 1, timezone.utc),
                          period=POLL_PERIOD_S)
        pre_buckets = {_bucket(t) for t in pre["timestamps_s"]}

        try:
            client.refresh_if_stale()
            t_send = time.time()
            d = client.call_tool(tool_name, {"text": f"{TEXT} {i}"})
        except M.McpTransportError as exc:
            trials.append({"i": i, "outcome": "transport_error", "error": str(exc)})
            continue

        bucket = _bucket(t_send)
        already = bucket in pre_buckets
        t0 = time.monotonic()
        visible_at: float | None = None
        n_polls = 0
        while time.monotonic() - t0 < PER_TRIAL_TIMEOUT_S:
            time.sleep(POLL_EVERY_S)
            n_polls += 1
            r = _datapoints(cw, store, metric, dimensions,
                            start=datetime.fromtimestamp(bucket, timezone.utc),
                            end=datetime.fromtimestamp(bucket + POLL_PERIOD_S, timezone.utc),
                            period=POLL_PERIOD_S)
            if r["timestamps_s"]:
                visible_at = time.time()
                break

        lag = None if visible_at is None else round(visible_at - t_send, 3)
        trials.append({
            "i": i, "outcome": d.outcome, "request_id": d.request_id,
            "t_send_epoch_s": round(t_send, 3), "bucket_epoch_s": bucket,
            "bucket_already_had_a_datapoint": already,
            "lag_s": lag, "n_polls": n_polls,
            "timed_out": visible_at is None,
        })
        print(f"  [{i:>2}/{n}] bucket={bucket} lag="
              f"{'TIMEOUT' if lag is None else f'{lag:.1f}s'} polls={n_polls}"
              + ("  (bucket was pre-populated)" if already else ""))
        if i < n:
            # Wait out the rest of THIS trial's bucket, not a fixed gap. The datapoint a request
            # produces is stamped at the bucket containing t_send, so two trials sharing a
            # bucket share a datapoint: the second one's clock stops on the first one's
            # publication and its lag reads near zero. MEASURED at n=2 on 2026-08-11 — a 5s gap
            # against an ~11s lag put both trials in bucket 1786465140 and the
            # `distinct_minute_buckets` guard correctly withheld both verdicts. Sleeping to the
            # next boundary is what makes the guard satisfiable rather than merely honest.
            gap = _bucket(time.time()) + POLL_PERIOD_S + INTER_TRIAL_GAP_S - time.time()
            if gap > 0:
                time.sleep(gap)

    real = [t for t in trials if t.get("outcome") in ("allowed", "policy_denied")]
    usable = [t for t in real if t.get("lag_s") is not None
              and not t.get("bucket_already_had_a_datapoint")]
    lags = sorted(float(t["lag_s"]) for t in usable)
    buckets = [t["bucket_epoch_s"] for t in usable]

    quant = _quant_read(cw, store, metric, dimensions,
                        minutes=QUANT_MAX_LOOKBACK_H * 60 - 10)

    guards = {
        "calls_reached_gateway": len(real) == n,
        "distinct_minute_buckets": len(set(buckets)) == len(buckets) and bool(buckets),
        "datapoint_is_ours": bool(dimensions),
        "all_trials_became_visible": all(not t.get("timed_out") for t in real),
        "quant_period_is_subminute": bool(quant.get("period_honoured")),
        "n_met": len(lags) >= (n if is_smoke else PLANNED_N),
    }
    guard_detail = {
        "calls_reached_gateway": {"n_sent": len(trials), "n_real": len(real),
                                 "outcomes": sorted({t.get("outcome", "") for t in trials})},
        "distinct_minute_buckets": {
            "n_usable": len(buckets), "n_distinct": len(set(buckets)),
            "n_excluded_prepopulated": sum(1 for t in real
                                           if t.get("bucket_already_had_a_datapoint")),
            "why": ("two trials in one bucket share a datapoint, so the second's lag would be "
                    "measured against visibility the first had already produced")},
        "datapoint_is_ours": {"dimensions": dimensions,
                              "why": ("six pre-existing gateways publish into this namespace; "
                                      "an unattributed read biases the lag downwards")},
        "all_trials_became_visible": {
            "n_timed_out": sum(1 for t in real if t.get("timed_out")),
            "per_trial_timeout_s": PER_TRIAL_TIMEOUT_S,
            "why": ("a censored lag is not a large lag — a timeout means the distribution's "
                    "upper tail is unmeasured, and p90 would be computed on the observed "
                    "subset while claiming to describe all of them")},
        "quant_period_is_subminute": {
            "period_requested_s": QUANT_PERIOD_S, "honoured": quant.get("period_honoured"),
            "error": quant.get("error", ""),
            "why": ("a 60s grid observed through a 60s query is an artifact of the query, not "
                    "a property of the service")},
        "n_met": {"n_usable": len(lags), "planned": PLANNED_N, "is_smoke": is_smoke},
    }

    summary: dict[str, Any] = {}
    if lags:
        summary = {
            "n": len(lags),
            "p50_s": round(statistics.median(lags), 3),
            "p90_s": round(lags[max(0, math.ceil(0.90 * len(lags)) - 1)], 3),
            "max_s": round(lags[-1], 3), "min_s": round(lags[0], 3),
            "all_s": lags,
            "note": ("p90 is the order statistic at ceil(0.90*n) on the sorted lags — the "
                     "sealed cell's own instrument, computed inline rather than through "
                     "lib/stats.quantile, which is a type-7 INTERPOLATED estimator and would "
                     "return a value between two observations. Both are reported so the "
                     "difference is visible instead of being an unstated convention; the "
                     "verdict uses the order statistic. No p99 is reported because the sealed "
                     "cell states n=30 does not support one"),
            "p90_s_type7_interpolated": round(S.quantile(lags, 0.90), 3),
        }
    common["lag_summary"] = summary
    common["quantization_read"] = quant
    common["trials"] = trials
    common["guards"] = guards
    common["guard_detail"] = guard_detail

    failed = [k for k, v in guards.items() if not v]
    if failed:
        return bail("guard(s) " + ", ".join(failed) + " did not hold, so neither a lag "
                    "distribution nor a timestamp grid measured here would be about this "
                    "gateway's own publishing behaviour")

    rc = 0

    # ---- F7-6 --------------------------------------------------------------------
    p90 = summary["p90_s"]
    o6 = O.Observation(case_id="F7-6", lag_p90_s=p90,
                       alarm_periods_s=[a[2] for a in stated],
                       n_attempted=len(trials), n_usable=len(lags),
                       detail={"p50_s": summary["p50_s"], "max_s": summary["max_s"],
                               "metric": metric})
    rec6 = O.evaluate(o6)
    below_60 = p90 <= DEFENSIBILITY_NOTE_PERIOD_S
    P.emit("F7-6", rec6, {
        **common,
        "verdict_rule": ("FALSE if any §6.4-STATED evaluation period is below the measured p90 "
                         "lag, TRUE otherwise. Only stated periods are scored"),
        "one_minute_defensibility_note": {
            "p90_s": p90, "compared_against_s": DEFENSIBILITY_NOTE_PERIOD_S,
            "p90_at_or_below_60s": below_60,
            "reading": (
                "the p90 publish lag is at or below 60s, so the document's 1-minute batching "
                "claim leaves a 1-minute alarm defensible"
                if below_60 else
                f"the p90 publish lag is {p90:.1f}s, above 60s. A 1-minute alarm on this "
                f"metric would evaluate a period whose data is not yet queryable — but note "
                f"that NO §6.4 row states a 60s window, so this is reported and NOT scored"),
            "why_not_scored": common["s6_4_alarms"]["why_60s_is_not_scored"],
        },
        "verdict_reading": (
            f"{rec6['verdict']} against the {len(stated)} of {len(S64_ALARMS)} §6.4 alarms that "
            f"state an evaluation period. It is NOT a statement about the other "
            f"{len(unstated)}, which state no window and are unimplementable as written"),
        "what_true_does_not_prove": (
            "that the metric is complete, that the 1-minute claim holds (see the note above "
            "and F7-7), or anything about a p99 lag, which n=30 does not support"),
    }, store)
    print(f"  F7-6: {rec6['verdict']}  p50={summary['p50_s']:.1f}s "
          f"p90={p90:.1f}s max={summary['max_s']:.1f}s  n={len(lags)}")
    if rec6["verdict"] not in O.DECISIVE:
        rc = 2

    # ---- F7-7 --------------------------------------------------------------------
    ts = quant["timestamps_s"]
    if not ts:
        rec7 = O.not_measured("F7-7", "the sub-minute read returned no datapoint, so there is "
                                      "no timestamp whose grid could be measured")
        P.emit("F7-7", rec7, common, store)
        print("  F7-7: INCONCLUSIVE (no datapoints in the sub-minute read)")
        return 2

    o7 = O.Observation(case_id="F7-7", timestamps_s=ts,
                       n_attempted=len(trials), n_usable=len(ts),
                       detail={"period_requested_s": QUANT_PERIOD_S, "metric": metric})
    rec7 = O.evaluate(o7)
    min_gap = quant.get("min_positive_gap_s")
    coarser = bool(min_gap is not None and min_gap > 60.0)
    P.emit("F7-7", rec7, {
        **common,
        "verdict_rule": ("TRUE iff every datapoint timestamp sits on the 60s grid, decided by "
                         "the sealed code in lib/oracle.py"),
        "why_the_period_matters": (
            f"this read used Period={QUANT_PERIOD_S}s. At Period=60 every returned timestamp is "
            f"a multiple of 60 by construction, so the verdict would have been TRUE for any "
            f"service behaviour whatsoever — the same defect as the sealed note's inferred ms "
            f"conversion, which made the threshold 60000 and would have been satisfied by every "
            f"observation"),
        "coarser_check": {
            "min_positive_gap_s": min_gap,
            "distinct_gaps_s": quant.get("distinct_gaps_s"),
            "grid_appears_coarser_than_60s": coarser,
            "why_measured_separately": (
                "F7-7's oracle text says 'FALSE if finer OR coarser', but the sealed decision "
                "code checks abs(remainder(t, 60)) < 1e-6, which cannot detect coarser: 300s "
                "timestamps are also multiples of 60 and would publish TRUE. lib/oracle.py is a "
                "sealed bound artifact and is NOT edited, so the coarser direction is measured "
                "here and reported. The verdict remains what the sealed code says"),
            "reading": (
                f"the smallest positive gap between consecutive datapoint timestamps is "
                f"{min_gap}s"
                + (", which is COARSER than the documented 60s batching interval. The sealed "
                   "decision code cannot see this, so the verdict above understates the finding "
                   "— this belongs in the v1.3 pass"
                   if coarser else
                   ", consistent with the documented 60s batching interval")),
        },
        "verdict_reading": (
            f"{rec7['verdict']}: {len(ts)} datapoint timestamps read at Period="
            f"{QUANT_PERIOD_S}s, maximum offset from the 60s grid "
            f"{max(quant['offsets_from_60s_grid_s']):g}s"),
        "what_true_does_not_prove": (
            "that a datapoint is queryable at its own timestamp — the grid is where the "
            "aggregation window starts, and F7-6 measures how long after that the datapoint "
            "can actually be read"),
    }, store)
    print(f"  F7-7: {rec7['verdict']}  n_timestamps={len(ts)} "
          f"min_gap={min_gap}s coarser={coarser}")
    if rec7["verdict"] not in O.DECISIVE:
        rc = 2

    return rc


if __name__ == "__main__":
    sys.exit(main())
