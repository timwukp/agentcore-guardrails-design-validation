#!/usr/bin/env python3
"""F6-6, F6-7, F6-8 — the §6.1 total, its additivity, and the per-extra-tool-call increment.

The three claims, all from §6.1:

    F6-6  | — | **Total (single tool call)** | — | **~800ms–31s+** | End-to-end trace duration |
    F6-7  the six hops decompose that total: the table is presented as a budget whose rows add up
    F6-8  "Note: For agents making multiple tool calls (e.g., 3–5 calls), Hop #4 and #5 repeat
           for each call, adding 165–750ms per additional tool invocation."

Sealed oracles: F6-6 `BAND_CONTAINS (800, 31000)` ms — and `band_upper_is_open("F6-6")` is TRUE,
because the document writes "31s+", so **only the 800 ms floor is falsifiable**. F6-7
`NONNEG_RESIDUAL`, TRUE iff the additivity residual's CI lower bound is >= 0. F6-8 `CI_OVERLAPS
(165, 750)` ms on a slope in ms per additional tool invocation.

WHAT ONE TRIAL IS, AND WHY IT IS SCRIPTED RATHER THAN MODEL-DIRECTED
--------------------------------------------------------------------
§6.1's total is "a typical agent invocation": input guardrail, model inference, tool auth, tool
guardrail, output guardrail. This testbed has no agent runtime — `state.json` carries a gateway
and a policy engine, and the pre-existing `harness_*` runtimes are on the do-not-touch list. So
one trial here is a **scripted turn**: the same hops in the same order, driven by this script
instead of by a model's tool-use loop.

    hop 2  Bedrock guardrail (input)   ) one Converse call with `guardrailConfig` and
    hop 3  model inference             ) `trace=enabled`, which reports all three separately
    hop 6  Bedrock guardrail (output)  )
    hop 4  tool auth (Cedar)           ) N `tools/call` through the gateway with a
    hop 5  tool guardrails (per call)  ) guardrail-bearing ENFORCE policy active
    hop 1  gateway guardrail (input)   — see below: not separable from hop 5 in this service

Two consequences, both recorded in the payload rather than left for a reader to notice:

*   **A scripted turn omits the model round-trips a real agent adds.** A tool-using agent calls
    the model again to consume each tool result; we do not. That makes our total SMALLER than a
    real agent's, so it biases the measurement AGAINST the 800 ms floor. A TRUE on the floor is
    therefore conservative; a FALSE has to be read as "even the fastest path clears/misses it",
    and the amendment it supports is about the floor's applicability, not about agents.
*   **The model is `us.amazon.nova-micro-v1:0`,** for the reason 01_model_hops.py registered:
    every Claude model id in this account returns `ResourceNotFoundException`. Nova Micro is the
    FASTEST model available, so hop 3 sits at the very bottom of the document's own 500ms–30s
    range. That biases the total DOWN as well. A FALSE on the 800 ms floor with this model does
    not generalise to a large model, and the record says so in `what_false_does_not_prove`.

Hop 1 and hop 5 are one evaluation here, for the reason DEV-P4-07 registered and F4 measured: the
service will only evaluate an ACTION-SCOPED gateway guardrail, which is hop 5's shape. The
document's 800 ms floor budgets 50 ms for hop 1 and 50 ms for hop 5; our single evaluation is
measured in the hundreds of ms, so it more than covers both, and the conflation cannot make the
floor easier to clear than the table's own arithmetic allows.

THE TWO TOTALS, AND THE PRE-DECLARED RULE FOR WHEN THEY DISAGREE
----------------------------------------------------------------
The document's named instrument is "end-to-end trace duration" — a single trace spanning the whole
turn. That trace does not exist for a client-orchestrated turn: Bedrock Runtime and the gateway
emit into different traces, and nothing joins them. So the total is read two ways:

    client_total_ms   wall clock across the whole turn, from this laptop. INCLUDES our network
                      round trips, which an in-AWS trace would not, so it is biased UP.
    server_total_ms   Converse's own `metrics.latencyMs` + the gateway's server-side hop cost
                      x N. Excludes all network, so it is biased DOWN.

The truth the document's instrument would report lies between them. `client_total_ms` is the
PRIMARY, declared here before the data, because it is the only per-turn end-to-end reading
available. But a verdict that depends on which side of the floor we picked is not a verdict, so:

    if the two totals straddle 800 ms, F6-6 publishes INCONCLUSIVE with both numbers.

WHAT F6-7's RESIDUAL IS, AND WHY IT IS NOT NON-NEGATIVE BY CONSTRUCTION
-----------------------------------------------------------------------
A residual computed as "my stopwatch for the turn minus my stopwatches for its parts" is >= 0 by
construction whenever the parts run in sequence, and would be a vacuous instrument. So the parts
are read from the SERVICES' clocks and the total from ours:

    residual = client_total_ms - converse_server_ms - N * gateway_server_ms_per_call

`converse_server_ms` is `metrics.latencyMs`, which the service reports and which contains hops 2,
3 and 6. `gateway_server_ms_per_call` comes from CloudWatch over this run's own window, and is a
constant rather than a per-turn reading because the gateway publishes at 1-minute grain (F7-6
measured the publish lag at ~11.4 s and F7-7 confirmed the 60 s bucket).

That residual is the part of the end-to-end total the document's table does NOT account for. A
significantly negative one would mean the hops overlap — that the table's rows cannot be added —
and would falsify the decomposition model behind §6.1, §6.3 and §6.4. It is reported as a
fraction of the total too, because "the table accounts for 55% of the end-to-end time" is the
amendment-relevant number even when the sign check passes.

`Latency` and `GuardrailLatency` may or may not nest at the gateway; the service does not say.
Both readings are computed:

    conservative (PRIMARY)   hops 4+5 = Latency_p50 + GuardrailLatency_p50   (assumes disjoint;
                             if they in fact nest this DOUBLE-COUNTS, making the hop sum larger
                             and the residual smaller — so a non-negative residual is robust)
    alternative              hops 4+5 = Latency_p50                          (assumes nesting)

If the two readings disagree in SIGN, F6-7 publishes INCONCLUSIVE. The conservative one is primary
precisely because its failure mode is a false FALSE, not a false TRUE.

HOW F6-8's SLOPE IS ESTIMATED, WITHOUT WRITING A REGRESSION
------------------------------------------------------------
The claim is a per-additional-call increment, so the estimator is a difference, not a fit. Levels
N in {1, 2, 3, 5} — the document's own "(e.g., 3–5 calls)" plus the 1-call baseline. For each turn
i at level N > 1:

    s_i = (client_total_ms[N, i] - client_total_ms[1, i]) / (N - 1)

pooled across all levels into ONE array, and `stats.bootstrap_ci(s, statistic=np.median)` gives
the CI. Median, declared here: the rest of this family is p50-based and the claim states a typical
range. Per-level slopes are recorded as SECONDARY and cannot change the verdict — publishing the
level whose CI overlaps best would be choosing the answer after seeing it.

The whole-turn difference isolates hops 4 and 5 without assuming anything: the Converse half of a
turn happens exactly once regardless of N, so it cancels. The gateway-only increment is recorded
beside it as a cross-check.

Turns at level N are paired by index with turns at level 1, and every level sends the SAME text in
the same order (one deterministic draw, `CORPUS_SEED`), so a pair differs only in N.

N PER CELL
----------
F6-6's cell is `latency_arm_p99` (n=1000): a p99 needs the order statistic interior to the sample.
F6-7's and F6-8's cell is `latency_arm_p50_p90_only` (n=200). The N=1 arm is collected at 1000 and
serves all three cases; levels 2, 3 and 5 are collected at 200 each. That sharing is deliberate
and declared: F6-7's residual and F6-8's level-1 baseline are the same physical trials as F6-6's
total, so a reader comparing the three payloads is looking at one experiment, not three. Exceeding
a pre-registered n (F6-7 gets 1000 where 200 was required) is recorded, not silently enjoyed.

COST
----
1000 + 200*3 = 1600 turns. 1600 Converse calls on Nova Micro with a 40-token cap, 3200 guardrail
text-unit evaluations (input + output), and 1000*1 + 200*(2+3+5) = 3000 `tools/call`. One policy
created in ENFORCE on the shared engine and deleted in a `finally`. Under $1 in total.

MUTATION AND RESTORE
--------------------
The probe policy is registered in `state.json` BEFORE its first status poll, so a crash between
create and poll still leaves a deletable record. It is deleted in a `finally`, and the Phase-2
blocking assertion is then RE-RUN, so the testbed the remaining cases depend on is proven intact
rather than assumed. This script MUST NOT run while 02_gateway_hops.py is running: both mutate the
same policy engine, and either one's probe would appear in the other's timings.
"""

from __future__ import annotations

import importlib.util
import json
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                    # noqa: E402
import cedar                                              # noqa: E402
import mcp as M                                           # noqa: E402
import oracle as O                                        # noqa: E402
import phase1 as P                                        # noqa: E402
import stats as S                                         # noqa: E402
import testbed as T                                       # noqa: E402
from checkpoint import Checkpoint                          # noqa: E402
from evidence import EvidenceStore, capture                # noqa: E402

CASES = ("F6-6", "F6-7", "F6-8")
FAMILY = "f6_latency"

PE_MODULE_NAME = "grx_f6c_infra_03_policy_engine"
VERIFY_MODULE_NAME = "grx_f6c_infra_06_verify"


def _register(spec):
    """Register and execute a by-path module. The NAME is passed at the call site, not here.

    The obvious shape — `_load(NAME, rel)` doing the `spec_from_file_location` inside — makes the
    sys.modules key invisible to `lib/tests/test_module_name_collisions.py`, which resolves the
    FIRST ARGUMENT of that call statically and cannot follow a parameter. Measured 2026-08-12:
    the gate failed with this file listed as unresolvable, contradicting the comment that used to
    sit above claiming the constants were read. Building the spec at the call site keeps the
    guard able to see every key, which is the only reason the constants are constants.
    """
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_pe = _register(importlib.util.spec_from_file_location(
    PE_MODULE_NAME, ROOT / "infra" / "03_policy_engine.py"))
_vf = _register(importlib.util.spec_from_file_location(
    VERIFY_MODULE_NAME, ROOT / "infra" / "06_verify.py"))

# --- the turn ---------------------------------------------------------------
MODEL_ID = "us.amazon.nova-micro-v1:0"
MAX_TOKENS = 40
PROMPT = ("You are a helpful assistant. In one short sentence, say what a guardrail does "
          "before a tool call.")
GUARDRAIL_KEY = "cf-medium"          # the same guardrail 01_model_hops.py used for its hops
GUARDRAIL_VERSION = "DRAFT"

TOOL = "echo"
NS = "AWS/Bedrock-AgentCore"

# --- the arms --------------------------------------------------------------
LEVEL_BASELINE = 1
LEVELS_EXTRA = (2, 3, 5)             # "(e.g., 3-5 calls)" plus one intermediate
PLANNED_N_BASELINE = 1000            # latency_arm_p99
PLANNED_N_EXTRA = 200                # latency_arm_p50_p90_only
CELL_BASELINE = "latency_arm_p99"
CELL_EXTRA = "latency_arm_p50_p90_only"

# --- the probe policy (shape identical to 02's, for the reason F4 measured) --
GUARDRAIL_FUNCTION = "ContentFilter"
GUARDRAIL_CATEGORY = "HATE"
GUARDRAIL_PATH = "context.input.text"
GUARDRAIL_THRESHOLD = "0.2"
VALIDATION_MODE = "IGNORE_ALL_FINDINGS"
POLICY_ENFORCE = "ACTIVE"
DELETE_ATTEMPTS = 5
DELETE_SLEEP_S = 3.0
POLICY_SETTLE_S = 20.0

# --- corpora ---------------------------------------------------------------
BENIGN_CORPUS = ROOT / "corpora" / "benign" / "benign.jsonl"
HATE_CORPUS = ROOT / "corpora" / "content_filter" / "hate.jsonl"
CORPUS_SEED = 20260809

# --- CloudWatch ------------------------------------------------------------
CW_SETTLE_S = 90.0                   # F7-6 measured the publish lag at ~11.4 s; 90 s is ~8x
CW_MIN_SAMPLES = 100

# Hops 4 and 5 are read from CloudWatch over the window in which the turns were SENT, so that
# window is part of the measurement — as much as the turns themselves — and it therefore has to
# survive a resume for the same reason the trials do. It did not, and that is not a hypothetical
# defect: the first full run collected all 1,600 turns, read this window successfully, then
# crashed in its analysis (an empty-sample quantile, fixed in `_p50_or_none`). A re-run would have
# skipped every checkpointed trial in seconds, timed a window containing no traffic, read 0
# samples, failed `gateway_hop_measured`, and published NOT_MEASURED for all three cases — with
# 1,600 paid-for turns sitting on disk.
#
# So each process that sends turns APPENDS its window here, and the analysis queries every
# recorded window. See `_cw_p50` for why they are queried separately rather than merged.
WINDOWS_PATH = ROOT / "results" / "checkpoints" / "F6-6__cw_windows.json"

# --- the 800 ms floor and the straddle rule -------------------------------
FLOOR_MS = 800.0

GUARDS = ("turns_completed", "guardrail_ran_on_every_turn", "gateway_hop_measured",
          "guardrail_live_before_and_after", "probe_policy_removed",
          "testbed_intact_after_restore")
GUARD_STRADDLE = "totals_agree_about_the_floor"       # F6-6
GUARD_RESIDUAL_SIGN = "both_hop_readings_agree_in_sign"   # F6-7


class ConfigError(RuntimeError):
    """The testbed is not in the state this case needs. Never a verdict."""


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------

def _corpus(path: Path, n: int) -> list[dict[str, str]]:
    """`n` rows drawn deterministically, cycling if the file is shorter.

    Deterministic so that level 2 sends the same text as level 1 in the same order — the pairing
    F6-8's increment depends on — and so a resumed checkpoint re-sends its own text.
    """
    if not path.is_file():
        raise ConfigError(f"corpus {path} is missing")
    rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    if not rows:
        raise ConfigError(f"corpus {path} is empty")
    rng = random.Random(CORPUS_SEED)
    order = list(range(len(rows)))
    rng.shuffle(order)
    return [{"id": rows[order[i % len(order)]]["id"],
             "text": rows[order[i % len(order)]]["text"],
             "label": rows[order[i % len(order)]].get("label", "")} for i in range(n)]


# ---------------------------------------------------------------------------
# one turn
# ---------------------------------------------------------------------------

def _converse(store: EvidenceStore, brt, *, gid: str) -> dict[str, Any]:
    """The model half of a turn: hops 2, 3 and 6 in one call, each reported separately."""
    t0 = time.perf_counter()
    rec = capture(store, "converse", brt,
                  modelId=MODEL_ID,
                  messages=[{"role": "user", "content": [{"text": PROMPT}]}],
                  inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
                  guardrailConfig={"guardrailIdentifier": gid,
                                   "guardrailVersion": GUARDRAIL_VERSION,
                                   "trace": "enabled"})
    client_ms = (time.perf_counter() - t0) * 1000.0
    rec.raise_for_status()
    resp = rec.response or {}

    gr = (resp.get("trace") or {}).get("guardrail") or {}
    ia = (gr.get("inputAssessment") or {}).get(gid) or {}
    hop2 = (ia.get("invocationMetrics") or {}).get("guardrailProcessingLatency")
    oas = (gr.get("outputAssessments") or {}).get(gid) or []
    # SUMMED over assessments, and the COUNT travels with the number: a streamed response is
    # assessed in pieces, and taking only the first would report a fraction of hop 6 as hop 6.
    parts = [float((a.get("invocationMetrics") or {}).get("guardrailProcessingLatency"))
             for a in oas
             if (a.get("invocationMetrics") or {}).get("guardrailProcessingLatency") is not None]
    server_ms = (resp.get("metrics") or {}).get("latencyMs")

    return {
        "client_ms": round(client_ms, 3),
        "server_ms": None if server_ms is None else float(server_ms),
        "hop2_ms": None if hop2 is None else float(hop2),
        "hop6_ms": sum(parts) if parts else None,
        "hop6_parts": parts,
        "n_output_assessments": len(oas),
        "trace_present": bool(gr),
        "stop_reason": resp.get("stopReason"),
        "action": (gr.get("actionReason") or "") if gr else "",
        "usage": {k: v for k, v in (resp.get("usage") or {}).items()
                  if k in ("inputTokens", "outputTokens", "totalTokens")},
    }


def _turn(store: EvidenceStore, brt, client, action_id: str, *,
          gid: str, n_calls: int, item: dict[str, str]) -> dict[str, Any]:
    """One scripted agent turn. The wall clock spans the whole turn, hop by hop within it."""
    t_turn = time.perf_counter()
    conv = _converse(store, brt, gid=gid)

    calls: list[dict[str, Any]] = []
    for _j in range(n_calls):
        t0 = time.perf_counter()
        # Transport errors are NOT caught: `Checkpoint.run_trial` owns the retry, and a turn
        # retried from its middle would have a wall clock covering two Converse calls.
        d = client.call_tool(action_id, {"text": item["text"]})
        calls.append({"outcome": d.outcome, "request_id": d.request_id,
                      "denied": bool(d.denied), "default_deny": bool(d.default_deny),
                      "client_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                      "gateway_ms": round(d.duration_ms, 3)})
    client_total_ms = (time.perf_counter() - t_turn) * 1000.0

    denied = [c for c in calls if c["denied"]]
    return {
        "outcome": "ok" if not denied else "denied",
        "n_calls": n_calls,
        "corpus_id": item["id"],
        "corpus_label": item["label"],
        "text_len": len(item["text"]),
        "client_total_ms": round(client_total_ms, 3),
        "converse": conv,
        "calls": calls,
        "gateway_client_ms": round(sum(c["client_ms"] for c in calls), 3),
        "n_denied": len(denied),
    }


def _run_level(store: EvidenceStore, brt, client, action_id: str, *, gid: str, level: int,
               items: list[dict], is_smoke: bool, cell: str) -> Checkpoint:
    """Collect one level of N, resumable. The checkpoint's design keys pin what the arm WAS."""
    cp = Checkpoint(case_id=CASES[0], cell=f"turns_n{level}").load()
    cp.set_meta(n_calls=level, model_id=MODEL_ID, guardrail_id=gid, cell=cell,
                is_smoke=is_smoke, n_planned=len(items), corpus_seed=CORPUS_SEED,
                tool=action_id, prompt_len=len(PROMPT), max_tokens=MAX_TOKENS,
                policy_shape="baseline_permit_plus_guardrail_forbid_enforce")
    for i, item in enumerate(items):
        tid = f"t{i:04d}"
        if cp.is_done(tid):
            continue
        client.refresh_if_stale()
        cp.run_trial(tid, lambda it=item: _turn(store, brt, client, action_id,
                                               gid=gid, n_calls=level, item=it))
        if i and i % 50 == 0:
            print(f"      [{level} call(s)] {cp.n_done}/{len(items)}", flush=True)
    return cp


# ---------------------------------------------------------------------------
# the gateway's server-side hop cost, from CloudWatch over this run's window
# ---------------------------------------------------------------------------

def _load_windows() -> dict[str, Any]:
    """The sending windows recorded by every process that has contributed turns to this arm.

    A corrupt file is FATAL rather than treated as absent, for the reason `Checkpoint.load`
    gives about its own file: silently starting fresh would time a window that contains no
    traffic while the checkpoints still report 1,600 completed turns, and the analysis would
    read someone else's CloudWatch datapoints — or none — under this case's name.
    """
    if not WINDOWS_PATH.is_file():
        return {"windows": []}
    try:
        body = json.loads(WINDOWS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(
            f"{WINDOWS_PATH} is not readable JSON ({exc}). Refusing to continue: the checkpoints "
            f"may hold completed turns whose sending window this file is the only record of, and "
            f"an empty window would silently turn them into NOT_MEASURED.") from exc
    wins = body.get("windows")
    if not isinstance(wins, list) or any(
            not (isinstance(w, list) and len(w) == 2 and w[0] < w[1]) for w in wins):
        raise ConfigError(f"{WINDOWS_PATH} does not hold a list of [t0, t1] pairs with t0 < t1")
    return body


def _append_window(body: dict[str, Any], t0: float, t1: float, *, n_turns: int) -> dict[str, Any]:
    """Record this process's sending window. Written only when this process sent turns."""
    body.setdefault("windows", []).append([t0, t1])
    body.setdefault("provenance", []).append({
        "t0_iso": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
        "t1_iso": datetime.fromtimestamp(t1, tz=timezone.utc).isoformat(),
        "n_turns_sent_by_this_process": n_turns,
        "recorded_by": "f6_latency/03_composition.py (live)"})
    WINDOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WINDOWS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(WINDOWS_PATH)
    return body


def _cw_p50(cw, store: EvidenceStore, *, metric: str, gateway_id: str,
            windows: list[tuple[float, float]]) -> dict[str, Any]:
    """p50 of one gateway metric over the SENDING windows, from the combinations that exist.

    `ListMetrics` publishes COMBINATIONS. DEV-P4-04 and DEV-P4-09 record four rounds of the same
    defect: assembling a dimension set from the union of names produces a query no series carries,
    which CloudWatch answers with `Complete` and no values rather than an error. So the
    combinations are read, filtered to ours, and queried whole.

    A LIST of windows rather than one, because the turns may have been sent across more than one
    process: this arm is 1,600 turns and resumes from a checkpoint (see `_load_windows`). The
    windows are queried separately and combined sample-weighted, NOT merged into one span from the
    earliest start to the latest end. Merging would sweep in whatever other cases sent to this
    gateway during the gap between the two runs, and attribute their latency to F6's hop 4/5.
    """
    combos: list[list[dict[str, str]]] = []
    token = None
    while True:
        kw: dict[str, Any] = {"Namespace": NS, "MetricName": metric}
        if token:
            kw["NextToken"] = token
        rec = capture(store, "list_metrics", cw, **kw)
        rec.raise_for_status()
        for m in (rec.response or {}).get("Metrics", []):
            dims = m.get("Dimensions") or []
            if any(gateway_id in (d.get("Value") or "") for d in dims):
                combos.append([{"Name": d["Name"], "Value": d["Value"]} for d in dims])
        token = (rec.response or {}).get("NextToken")
        if not token:
            break

    out: dict[str, Any] = {"metric": metric, "combinations_found": len(combos),
                          "series": [], "p50": None, "samples": 0,
                          "windows_queried": []}
    for t0, t1 in windows:
        start = datetime.fromtimestamp(t0, tz=timezone.utc) - timedelta(seconds=60)
        end = datetime.fromtimestamp(t1, tz=timezone.utc) + timedelta(seconds=60)
        period = max(60, int((end - start).total_seconds() // 60 + 1) * 60)
        out["windows_queried"].append({"start": start.isoformat(), "end": end.isoformat(),
                                       "period_s": period})
        for dims in combos:
            rec = capture(store, "get_metric_statistics", cw, Namespace=NS, MetricName=metric,
                          Dimensions=dims, StartTime=start, EndTime=end, Period=period,
                          Statistics=["SampleCount", "Average", "Minimum", "Maximum"],
                          ExtendedStatistics=["p50", "p90", "p99"])
            rec.raise_for_status()
            pts = (rec.response or {}).get("Datapoints") or []
            for p in pts:
                ext = p.get("ExtendedStatistics") or {}
                out["series"].append({
                    "dimensions": {d["Name"]: d["Value"] for d in dims},
                    "window_start": start.isoformat(),
                    "sample_count": p.get("SampleCount"), "average": p.get("Average"),
                    "minimum": p.get("Minimum"), "maximum": p.get("Maximum"),
                    "p50": ext.get("p50"), "p90": ext.get("p90"), "p99": ext.get("p99")})

    # The gateway-wide series, sample-weighted across whatever combinations published.
    tot = sum(float(s["sample_count"] or 0) for s in out["series"])
    if tot > 0:
        num = sum(float(s["sample_count"] or 0) * float(s["p50"] or 0.0)
                  for s in out["series"] if s["p50"] is not None)
        den = sum(float(s["sample_count"] or 0)
                  for s in out["series"] if s["p50"] is not None)
        out["p50"] = (num / den) if den else None
        out["samples"] = int(tot)
    return out


# ---------------------------------------------------------------------------
# the probe policy
# ---------------------------------------------------------------------------

def _create_probe(ac, store: EvidenceStore, state: T.State, *, engine_id: str, run_id: str,
                  gateway_arn: str, action_id: str) -> str:
    """Create the guardrail-bearing probe policy in ENFORCE. Registered before any poll."""
    stmt = cedar.statement(
        "forbid", resource=cedar.gateway_resource(gateway_arn),
        action=f'action == {cedar.ENTITY_ACTION}::"{action_id}"',
        when_guardrails=cedar.guardrail_condition(
            GUARDRAIL_FUNCTION, [GUARDRAIL_CATEGORY], [GUARDRAIL_PATH],
            threshold=GUARDRAIL_THRESHOLD))
    problems = cedar.check_statement(stmt)
    if problems:
        raise ConfigError(f"the probe statement fails the local lint: {problems}")

    name = f"grx_f6c_guardrail_{run_id}"
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac, name=name, policyEngineId=engine_id,
                  definition={"policy": {"statement": stmt}},
                  description="F6-6/F6-7/F6-8 probe: hop 4+5 present in the turn",
                  validationMode=VALIDATION_MODE, enforcementMode=POLICY_ENFORCE)
    if not rec.ok:
        raise ConfigError(f"CreatePolicy failed: {rec.error_code}: {rec.error_message}")
    pid = rec.response.get("policyId")
    if not pid:
        raise ConfigError("CreatePolicy returned no policyId")
    state.record(T.Resource(
        kind="policy", logical="f6c_guardrail_probe", name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid, "statement": stmt,
             "enforcement_mode_at_create": POLICY_ENFORCE,
             "validation_mode_sent": VALIDATION_MODE},
        arn=rec.response.get("policyArn", ""), delete_priority=40,
        notes=("F6-6/7/8 guardrail probe. `policy` takes no tags, so this ledger entry and "
               "this script's finally are the only channels that can find it")))
    live = _pe.wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
    if live.get("status") not in _pe.TERMINAL_OK:
        raise ConfigError(
            f"the probe policy settled {live.get('status')} "
            f"(reasons={live.get('statusReasons')}); an inert policy would leave hop 5 out of "
            f"every turn and hand F6-8 a slope with no guardrail in it")
    print(f"    probe policy {pid} ACTIVE ({POLICY_ENFORCE})")
    return pid


def _delete_probe(ac, store: EvidenceStore, state: T.State, *, engine_id: str,
                  policy_id: str) -> dict[str, Any]:
    """Delete the probe. Never raises: this runs in a finally."""
    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac,
                      policyEngineId=engine_id, policyId=policy_id)
        if rec.ok or rec.error_code == "ResourceNotFoundException":
            state.drop("policy", "f6c_guardrail_probe")
            return {"deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}: {rec.error_message}")
        time.sleep(DELETE_SLEEP_S)
    return {"deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors}


def _liveness(client, action_id: str, *, when: str) -> dict[str, Any]:
    """Prove the guardrail is actually evaluating: a HATE payload must be denied.

    The timed turns are all benign and all pass, so nothing in the sample itself shows the
    guardrail ran. Without this probe, a policy that silently stopped enforcing would publish
    hop 4 as hops 4+5 and hand F6-8 a slope with no guardrail in it.
    """
    item = _corpus(HATE_CORPUS, 1)[0]
    try:
        d = client.call_tool(action_id, {"text": item["text"]})
    except M.McpTransportError as exc:
        return {"when": when, "denied": False, "error": str(exc)}
    return {"when": when, "denied": bool(d.denied), "outcome": d.outcome,
            "request_id": d.request_id, "corpus_id": item["id"]}


# ---------------------------------------------------------------------------
# reading the arms
# ---------------------------------------------------------------------------

def _rows(cp: Checkpoint) -> list[dict[str, Any]]:
    """The usable turns of one level, in trial-id order.

    Trial-id order, not dict order, because F6-8 pairs level N's turn i with level 1's turn i and
    a pairing that depended on insertion order would silently mis-pair after a resume.
    """
    res = cp.results()
    return [{**res[tid], "trial_id": tid} for tid in sorted(res)
            if res[tid].get("outcome") == "ok"]


def _describe(values: list[float], *, alpha: float, allow_p99: bool) -> dict[str, Any]:
    """p50/p90 (and p99 only where n supports it), with the p50's order-statistic CI."""
    if not values:
        return {"n": 0}
    out: dict[str, Any] = {"n": len(values),
                           "p50": S.quantile(values, 0.50),
                           "p90": S.quantile(values, 0.90),
                           "mean": statistics.fmean(values),
                           "min": min(values), "max": max(values),
                           "ci_p50": str(S.quantile_ci(values, 0.50, level=1 - alpha))}
    if allow_p99 and len(values) >= 100:
        out["p99"] = S.quantile(values, 0.99)
    else:
        out["p99"] = None
        out["p99_note"] = ("withheld: this arm's n does not put the 99th order statistic "
                           "interior to the sample")
    return out


def _p50_or_none(values: list[float]) -> float | None:
    """The median, or None when nothing was sampled.

    Exists because `S.quantile([])` raises `ValueError("empty sample")` and the hop breakdown
    below guarded the WRONG list: it tested `if base else None`, i.e. "were there any baseline
    turns", while the list actually being summarised is `base` FILTERED to the turns that
    reported that hop. Those differ whenever a hop is absent from every trace, which is exactly
    what happened on the first full run — `hop6_ms` is None on a Converse response carrying no
    `outputAssessments`, and no benign turn carried one, so a 1600-turn run crashed in its
    analysis after every billed call had already been made.

    The empty case must be None rather than 0.0: a hop that was never reported did not take zero
    milliseconds, and a 0.0 in the breakdown would be summed into a total as though it had.
    """
    return S.quantile(values, 0.50) if values else None


def _slope_increments(base: list[dict], lvl: dict[int, list[dict]]) -> dict[str, Any]:
    """F6-8's pooled per-additional-call increments, and the per-level ones as secondary.

    Pairing is by trial id: level N's turn `t0007` sent the same text as level 1's `t0007`, so the
    difference between them is the cost of the extra calls and nothing else. Unpaired turns are
    dropped and counted rather than matched by position, which after a resume would pair different
    text and put corpus variance into a latency increment.
    """
    b = {r["trial_id"]: r["client_total_ms"] for r in base}
    pooled: list[float] = []
    per_level: dict[str, Any] = {}
    gw_pooled: list[float] = []
    b_gw = {r["trial_id"]: r["gateway_client_ms"] for r in base}
    n_unpaired = 0
    for n_calls in sorted(lvl):
        rows = lvl[n_calls]
        vals, gvals = [], []
        for r in rows:
            tid = r["trial_id"]
            if tid not in b:
                n_unpaired += 1
                continue
            vals.append((r["client_total_ms"] - b[tid]) / (n_calls - 1))
            gvals.append((r["gateway_client_ms"] - b_gw[tid]) / (n_calls - 1))
        pooled.extend(vals)
        gw_pooled.extend(gvals)
        per_level[str(n_calls)] = {
            "n_pairs": len(vals),
            "median_increment_ms": S.quantile(vals, 0.50) if vals else None,
            "gateway_only_median_ms": S.quantile(gvals, 0.50) if gvals else None,
            "scored": False,
            "why_not_scored": ("secondary. The verdict reads the POOLED increment declared in "
                              "the docstring; picking the level whose CI overlaps best would be "
                              "choosing the answer after seeing it"),
        }
    return {"pooled": pooled, "gateway_only_pooled": gw_pooled,
            "per_level": per_level, "n_unpaired": n_unpaired}


def main(argv: list[str] | None = None) -> int:                     # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASES[0], __doc__)
    args = ap.parse_args(argv)
    is_smoke = args.n is not None
    n_base = args.n if args.n else PLANNED_N_BASELINE
    n_extra = args.n if args.n else PLANNED_N_EXTRA
    levels = {LEVEL_BASELINE: n_base, **{k: n_extra for k in LEVELS_EXTRA}}
    n_turns = sum(levels.values())
    n_calls_total = sum(k * v for k, v in levels.items())

    if args.dry_run:
        for case in CASES:
            P.dry_run_banner(
                case,
                [(f"turns_n{k}",
                  f"scripted turns with {k} tool call(s): Converse(guardrail, trace) then "
                  f"{k} tools/call under a guardrail-bearing ENFORCE policy", v)
                 for k, v in levels.items()],
                # The breakdown PARTITIONS the arm plan, and the unit of this plan is a turn —
                # so the turn is the only entry. Listing converse and tools/call here would sum
                # to 4600 against a 1600-turn plan: two labels over one computation. The API
                # call counts a turn expands into are below, where they cannot be mistaken for
                # a second denominator.
                operations={"scripted_turn": n_turns},
                mutations=2, billable=True,
                extra=[
                    f"each turn expands into 1 converse + N tools/call, so the run makes "
                    f"{n_turns} converse calls and {n_calls_total} tools/call in total",
                    "ancillary, NOT part of the arm plan: create_policy x1, delete_policy x1, "
                    "2 liveness probes (HATE, must be denied), list_metrics x~4, "
                    "get_metric_statistics x~4, 1 MCP initialize",
                    f"one turn = hops 2,3,6 in one Converse (server-reported separately) + "
                    f"hops 4,5 in N tools/call; hop 1 is not separable from hop 5 (DEV-P4-07)",
                    f"F6-6 primary = client end-to-end p50 vs the {FLOOR_MS:.0f}ms floor; the "
                    f"upper end is OPEN ('31s+') so only the floor is falsifiable; if the "
                    f"client and server totals straddle the floor the verdict is INCONCLUSIVE",
                    "F6-7 residual = client_total - converse_server_ms - N x gateway_server_ms; "
                    "the parts come from the SERVICES' clocks so the sign is not guaranteed; "
                    "primary is the conservative hop reading (Latency + GuardrailLatency)",
                    "F6-8 slope = median over pooled (dur_N - dur_1)/(N-1), paired by trial id; "
                    "per-level slopes are recorded and never scored",
                    "the model is nova-micro (the fastest available; Claude ids are absent from "
                    "this account) and the turn is scripted, so the total is biased DOWN — a "
                    "FALSE on the floor does not generalise to a large model",
                    "one policy is created on the shared engine in ENFORCE and deleted in a "
                    "finally; the Phase-2 blocking assertion is then RE-RUN",
                    f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}, "
                    f"{GUARD_STRADDLE} (F6-6), {GUARD_RESIDUAL_SIGN} (F6-7)",
                ])
            print()
        return 0

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    brt = fc.client("bedrock-runtime")
    cw = fc.client("cloudwatch")
    ac = fc.client("bedrock-agentcore-control")
    account_id = A.account_id(fc)
    store = EvidenceStore(run_id, FAMILY, "F6-6_7_8")
    store.write_environment()

    man = P.manifest()
    gid = P.guardrail(GUARDRAIL_KEY, man=man)
    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    if not gw or not tgt:
        raise ConfigError("the main gateway or its target is not in state.json")
    gateway_id = gw.ids["gateway_id"]
    # The ledger stores ARNs with the account masked (lib/redact.py), so `gw.arn` cannot reach
    # an API. A masked resource in a Cedar statement is rejected as "AWS Account ID must be
    # exactly 12 digits" — measured, not assumed, on the first attempt of this run.
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    engine_id = gw.ids.get("policy_engine_id") or ""
    if not engine_id:
        raise ConfigError("the main gateway has no policy engine; hops 4 and 5 have no home")
    action_id = next((a for a in (tgt.ids.get("cedar_action_ids") or [])
                      if a.endswith(f"___{TOOL}")), "")
    if not action_id:
        raise ConfigError(f"no cedar action id ends with ___{TOOL}")

    alpha = O.alpha_for(CASES[0])
    print(f"F6-6/7/8 — §6.1 total, additivity, per-call increment. run_id={run_id}")
    print(f"  model {MODEL_ID}  guardrail {GUARDRAIL_KEY} ({gid})")
    print(f"  gateway {gateway_id}  engine {engine_id}  action {action_id}")
    print(f"  levels: {', '.join(f'N={k} n={v}' for k, v in levels.items())}  "
          f"({n_turns} turns, {n_calls_total} tool calls)")

    common: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke, "alpha": alpha,
        "ambient_sdk": A.sdk_versions(), "model_id": MODEL_ID, "guardrail_id": gid,
        "guardrail_key": GUARDRAIL_KEY, "guardrail_version": GUARDRAIL_VERSION,
        "gateway_id": gateway_id, "policy_engine_id": engine_id, "action_id": action_id,
        "prompt_len": len(PROMPT), "max_tokens": MAX_TOKENS,
        "turn_shape": {
            "orchestration": "scripted, not model-directed",
            "hops_per_turn": {"2": "Converse guardrailConfig inputAssessment",
                             "3": "Converse metrics.latencyMs minus hops 2 and 6 (DERIVED)",
                             "4": "gateway Cedar authorization",
                             "5": "gateway guardrail evaluation, once per tool call",
                             "6": "Converse guardrailConfig outputAssessments, SUMMED",
                             "1": "not separable from hop 5 in this service — DEV-P4-07"},
            "why_scripted": ("no agent runtime exists in this testbed and the pre-existing "
                            "harness_* runtimes are out of scope, so the turn is assembled by "
                            "this script in the document's own hop order"),
            "direction_of_bias": ("a scripted turn omits the model round-trips a tool-using "
                                 "agent adds, and nova-micro is the fastest model available, so "
                                 "the total is biased DOWN — against the 800ms floor"),
        },
        "hop3_is_derived": ("§6.1 row 3 names InvocationLatency in AWS/Bedrock, which publishes "
                           "at 1-minute grain and cannot be read per request; so hop 3 is "
                           "metrics.latencyMs minus hops 2 and 6 and is recorded as derived. "
                           "F6-7's residual does NOT depend on the split: hops 2+3+6 enter the "
                           "sum as metrics.latencyMs, which the service reports directly"),
    }

    client = M.client_for(gw.ids["gateway_url"], fc, store=store,
                         policy_session_id=M.policy_session_id(run_id, "f6comp"),
                         session_timeout_s=int(gw.ids.get("session_timeout_s", 900)))
    client.initialize()

    probe_id = ""
    restore: dict[str, Any] = {}
    live: list[dict[str, Any]] = []
    cps: dict[int, Checkpoint] = {}
    win_ledger = _load_windows()
    # Counted BEFORE the levels run, so "did this process send anything" is a measurement rather
    # than an assumption. A resume that sends nothing must not append a window: an empty window
    # would contribute a CloudWatch query over idle time and dilute the p50 with datapoints from
    # whatever else was talking to this gateway.
    done_before = sum(Checkpoint(case_id=CASES[0], cell=f"turns_n{lv}").load().n_done
                      for lv in levels)
    try:
        probe_id = _create_probe(ac, store, state, engine_id=engine_id, run_id=run_id,
                                 gateway_arn=gateway_arn, action_id=action_id)
        time.sleep(POLICY_SETTLE_S)
        live.append(_liveness(client, action_id, when="before"))
        print(f"  probe {probe_id} ACTIVE; liveness before: denied={live[0].get('denied')}")

        t_send0 = time.time()
        for lv, nn in levels.items():
            print(f"  [N={lv}] n={nn}")
            cps[lv] = _run_level(store, brt, client, action_id, gid=gid, level=lv,
                                items=_corpus(BENIGN_CORPUS, nn), is_smoke=is_smoke,
                                cell=CELL_BASELINE if lv == LEVEL_BASELINE else CELL_EXTRA)
            print(f"    done: {cps[lv].n_done} turns, {cps[lv].n_failed} failures")
        n_sent_here = sum(cps[lv].n_done for lv in levels) - done_before
        if n_sent_here > 0:
            win_ledger = _append_window(win_ledger, t_send0, time.time(),
                                        n_turns=n_sent_here)
        print(f"  sending window: {n_sent_here} turns sent by this process; "
              f"{len(win_ledger['windows'])} window(s) on record")

        live.append(_liveness(client, action_id, when="after"))
        print(f"  liveness after: denied={live[1].get('denied')}")
    finally:
        if probe_id:
            restore["probe_delete"] = _delete_probe(ac, store, state, engine_id=engine_id,
                                                   policy_id=probe_id)
            print(f"  restore: probe deleted={restore['probe_delete'].get('deleted')}")
        checks = _vf.Checks()
        _vf.verify_engine(ac, state, checks)
        _vf.verify_gateways(ac, state, account_id, region, checks)
        cj = checks.to_json()
        restore["blocking_checks"] = cj
        print(f"  restore: blocking checks {cj['n_pass']} pass / {cj['n_fail']} fail")
        if cj["n_fail"]:
            checks.print()

    # --- the gateway's server-side hop cost, over every recorded sending window ---
    cw_windows = [(float(a), float(b)) for a, b in win_ledger["windows"]]
    if not cw_windows:
        raise ConfigError(
            f"no sending window is on record in {WINDOWS_PATH} and this process sent no turns, "
            f"so hops 4 and 5 cannot be attributed to any span of time. Either the checkpoints "
            f"are empty (run the arm) or the ledger was lost (see its provenance field).")
    print(f"  settling {CW_SETTLE_S:.0f}s for the metric publish, then reading CloudWatch "
          f"over {len(cw_windows)} window(s)")
    time.sleep(CW_SETTLE_S)
    cw_lat = _cw_p50(cw, store, metric="Latency", gateway_id=gateway_id, windows=cw_windows)
    cw_gr = _cw_p50(cw, store, metric="GuardrailLatency", gateway_id=gateway_id,
                    windows=cw_windows)
    print(f"    Latency p50={cw_lat['p50']} (n={cw_lat['samples']}), "
          f"GuardrailLatency p50={cw_gr['p50']} (n={cw_gr['samples']})")

    hop45_conservative = ((cw_lat["p50"] or 0.0) + (cw_gr["p50"] or 0.0))
    hop45_nested = (cw_lat["p50"] or 0.0)
    gateway_hop_measured = bool(cw_lat["p50"] is not None and cw_gr["p50"] is not None
                                and cw_lat["samples"] >= CW_MIN_SAMPLES
                                and cw_gr["samples"] >= CW_MIN_SAMPLES)

    rows = {lv: _rows(cp) for lv, cp in cps.items()}
    base = rows.get(LEVEL_BASELINE, [])
    n_att = sum(cp.n_done + cp.n_failed for cp in cps.values())

    guards = {
        "turns_completed": all(
            cps[lv].n_done >= int(0.95 * levels[lv]) for lv in levels),
        "guardrail_ran_on_every_turn": bool(
            base and all(r["converse"].get("hop2_ms") is not None for r in base)),
        "gateway_hop_measured": gateway_hop_measured,
        "guardrail_live_before_and_after": bool(
            len(live) == 2 and all(x.get("denied") for x in live)),
        "probe_policy_removed": bool(restore.get("probe_delete", {}).get("deleted")),
        "testbed_intact_after_restore": restore.get("blocking_checks", {}).get("n_fail") == 0,
    }
    guard_detail = {
        "turns_completed": {lv: {"done": cps[lv].n_done, "failed": cps[lv].n_failed,
                                "planned": levels[lv]} for lv in levels},
        "guardrail_ran_on_every_turn": {
            "why": ("hop 2 is only reported when the guardrail actually evaluated the input; a "
                   "turn with no inputAssessment latency has no hop 2 and cannot enter a total"),
            "n_missing": sum(1 for r in base if r["converse"].get("hop2_ms") is None)},
        "gateway_hop_measured": {**{k: cw_lat[k] for k in ("p50", "samples",
                                                          "combinations_found")},
                                "guardrail_p50": cw_gr["p50"],
                                "guardrail_samples": cw_gr["samples"],
                                "min_samples": CW_MIN_SAMPLES,
                                # Where the window came from, published rather than assumed: a
                                # p50 over a window nobody can name is a number with no subject.
                                "sending_windows": win_ledger.get("provenance", []),
                                "n_sending_windows": len(cw_windows),
                                "windows_queried": cw_lat.get("windows_queried", [])},
        "guardrail_live_before_and_after": live,
        "probe_policy_removed": restore.get("probe_delete", {}),
        "testbed_intact_after_restore": restore.get("blocking_checks", {}),
    }
    failed_guards = [k for k, v in guards.items() if not v]

    # =======================================================================
    # F6-6 — the total against the 800ms floor
    # =======================================================================
    client_tot = [r["client_total_ms"] for r in base]
    server_tot = [(r["converse"].get("server_ms") or 0.0) + hop45_conservative
                  for r in base if r["converse"].get("server_ms") is not None]
    d_client = _describe(client_tot, alpha=alpha, allow_p99=True)
    d_server = _describe(server_tot, alpha=alpha, allow_p99=True)
    straddle = bool(d_client.get("p50") is not None and d_server.get("p50") is not None
                    and (d_client["p50"] >= FLOOR_MS) != (d_server["p50"] >= FLOOR_MS))
    guards_66 = {**guards, GUARD_STRADDLE: not straddle}
    p6 = {**common, "cell": CELL_BASELINE, "planned_n_cell": PLANNED_N_BASELINE,
          "n_requested": n_base, "level": LEVEL_BASELINE,
          "client_total": d_client, "server_total": d_server,
          "floor_ms": FLOOR_MS,
          "upper_end_open": O.band_upper_is_open("F6-6"),
          "which_is_primary": ("client_total — the only per-turn end-to-end reading available. "
                              "The document's named instrument, a single end-to-end trace, does "
                              "not exist for a client-orchestrated turn: Bedrock Runtime and the "
                              "gateway emit into different traces and nothing joins them"),
          "straddle_rule": {"straddled": straddle,
                           "rule": ("if the client and server totals fall on opposite sides of "
                                    "the floor the verdict is INCONCLUSIVE: a verdict that "
                                    "depends on which instrument was picked is not a verdict")},
          "hop_breakdown_p50": {
              "hop2_input_guardrail": _p50_or_none(
                  [r["converse"]["hop2_ms"] for r in base
                   if r["converse"].get("hop2_ms") is not None]),
              "hop6_output_guardrail": _p50_or_none(
                  [r["converse"]["hop6_ms"] for r in base
                   if r["converse"].get("hop6_ms") is not None]),
              # The count travels with the number, so a None above is attributable. A missing
              # hop 6 is a FINDING about the document's hop table, not a gap in this run: the
              # output guardrail is billed and configured on every one of these calls, and
              # Converse still reports no `outputAssessments` latency for them. Without this
              # count, `hop6_output_guardrail: null` reads as "we failed to measure it".
              "hop6_reporting": {
                  "n_turns": len(base),
                  "n_turns_with_an_output_assessment_latency": sum(
                      1 for r in base if r["converse"].get("hop6_ms") is not None),
                  "n_turns_with_zero_output_assessments": sum(
                      1 for r in base if not r["converse"].get("n_output_assessments")),
                  "why_it_matters": (
                      "hop 6 is one of the document's named hops. If the runtime never reports "
                      "its latency for a passing response, the hop cannot be measured per turn "
                      "at all and the §6.1 table's hop-6 row has no instrument behind it — "
                      "which is an amendment candidate, not a missing measurement")},
              "hop3_model_derived": _p50_or_none(
                  [(r["converse"]["server_ms"] or 0.0) - (r["converse"].get("hop2_ms") or 0.0)
                   - (r["converse"].get("hop6_ms") or 0.0) for r in base
                   if r["converse"].get("server_ms") is not None]),
              "hops45_gateway_conservative": hop45_conservative,
              "hops45_gateway_nested": hop45_nested,
              "converse_server_total": _p50_or_none(
                  [r["converse"]["server_ms"] for r in base
                   if r["converse"].get("server_ms") is not None])},
          "what_false_does_not_prove": (
              "a FALSE means the 800ms floor is not met by the FASTEST path this account can "
              "build: the fastest model available (nova-micro, at the bottom of the document's "
              "own 500ms-30s hop 3 range) and a scripted turn with no model round-trip per tool "
              "result. It does not show the floor is wrong for a production agent; the amendment "
              "it supports is that the total is model-dependent and the floor should be stated "
              "as a function of hop 3, not as a constant"),
          "guards": guards_66, "guard_detail": guard_detail,
          "cloudwatch": {"Latency": cw_lat, "GuardrailLatency": cw_gr}}
    bad6 = [k for k, v in guards_66.items() if not v]
    if bad6:
        r6 = O.not_measured("F6-6", f"guards failed: {', '.join(bad6)}", n_attempted=n_att)
    elif not client_tot:
        r6 = O.not_measured("F6-6", "no usable turns", n_attempted=n_att)
    else:
        r6 = O.evaluate(O.Observation(case_id="F6-6", n_attempted=n_att,
                                     n_usable=len(client_tot), latencies_ms=client_tot))
    P.emit("F6-6", r6, p6, store)
    print(f"  F6-6: {r6['verdict']}  client p50={d_client.get('p50')} "
          f"server p50={d_server.get('p50')} floor={FLOOR_MS:.0f} straddle={straddle}")

    # =======================================================================
    # F6-7 — additivity: is the end-to-end total accounted for by the table?
    # =======================================================================
    def _residuals(hop45: float) -> list[float]:
        return [r["client_total_ms"] - (r["converse"]["server_ms"] or 0.0)
                - r["n_calls"] * hop45
                for lv in sorted(rows) for r in rows[lv]
                if r["converse"].get("server_ms") is not None]

    res_c = _residuals(hop45_conservative)
    res_n = _residuals(hop45_nested)
    ci_c = S.bootstrap_ci(res_c, statistic=np.median, level=1 - alpha) if len(res_c) >= 20 \
        else None
    ci_n = S.bootstrap_ci(res_n, statistic=np.median, level=1 - alpha) if len(res_n) >= 20 \
        else None
    sign_agree = bool(ci_c is not None and ci_n is not None
                      and (ci_c.lo >= 0) == (ci_n.lo >= 0))
    guards_67 = {**guards, GUARD_RESIDUAL_SIGN: sign_agree}
    tot_p50 = S.quantile([r["client_total_ms"] for lv in sorted(rows) for r in rows[lv]], 0.50) \
        if res_c else None
    p7 = {**common, "cell": CELL_EXTRA, "planned_n_cell": PLANNED_N_EXTRA,
          "n_requested": n_turns, "n_used": len(res_c),
          "n_exceeds_planned": {"planned": PLANNED_N_EXTRA, "used": len(res_c),
                               "why": ("every level's turns enter the residual, so F6-7 gets "
                                       "more than its cell requires. Recorded rather than "
                                       "silently enjoyed: the cell is a floor, not a target")},
          "residual_definition": ("client_total_ms - converse_server_ms - N * "
                                 "gateway_server_ms_per_call. The total is OUR clock and the "
                                 "parts are the SERVICES' clocks, so the sign is not guaranteed "
                                 "by construction; a same-clock decomposition would be"),
          "conservative": {"hop45_ms": hop45_conservative,
                          "reading": "Latency + GuardrailLatency, assumed disjoint",
                          "residual_ci": None if ci_c is None else str(ci_c),
                          "why_primary": ("if the two gateway metrics in fact nest, this "
                                          "double-counts, making the hop sum larger and the "
                                          "residual smaller — so its failure mode is a false "
                                          "FALSE, never a false TRUE")},
          "alternative": {"hop45_ms": hop45_nested,
                         "reading": "Latency alone, assuming GuardrailLatency nests inside it",
                         "residual_ci": None if ci_n is None else str(ci_n),
                         "scored": False},
          "unaccounted_fraction_p50": (None if (ci_c is None or not tot_p50)
                                       else ci_c.point / tot_p50),
          "why_the_fraction_matters": ("the sign check is the sealed oracle, but the fraction is "
                                      "the amendment-relevant number: it is the share of the "
                                      "end-to-end total that §6.1's table does not name"),
          "guards": guards_67, "guard_detail": guard_detail}
    bad7 = [k for k, v in guards_67.items() if not v]
    if bad7:
        r7 = O.not_measured("F6-7", f"guards failed: {', '.join(bad7)}", n_attempted=n_att)
    elif ci_c is None:
        r7 = O.not_measured("F6-7", f"only {len(res_c)} residuals; a bootstrap CI needs 20",
                           n_attempted=n_att)
    else:
        r7 = O.evaluate(O.Observation(case_id="F6-7", n_attempted=n_att, n_usable=len(res_c),
                                     residual_ci=(ci_c.lo, ci_c.hi)))
    P.emit("F6-7", r7, p7, store)
    print(f"  F6-7: {r7['verdict']}  residual p50="
          f"{None if ci_c is None else round(ci_c.point, 1)} ms "
          f"CI=({None if ci_c is None else round(ci_c.lo, 1)}, "
          f"{None if ci_c is None else round(ci_c.hi, 1)})")

    # =======================================================================
    # F6-8 — ms per additional tool invocation
    # =======================================================================
    inc = _slope_increments(base, {lv: rows[lv] for lv in rows if lv != LEVEL_BASELINE})
    ci8 = S.bootstrap_ci(inc["pooled"], statistic=np.median, level=1 - alpha) \
        if len(inc["pooled"]) >= 20 else None
    lo8, hi8 = O.BINDINGS["F6-8"].thresholds
    p8 = {**common, "cell": CELL_EXTRA, "planned_n_cell": PLANNED_N_EXTRA,
          "n_requested": n_extra, "levels": {str(k): v for k, v in levels.items()},
          "stated_range_ms": [lo8, hi8],
          "estimator": ("median over the POOLED per-turn increments (dur_N - dur_1)/(N-1), "
                       "paired by trial id. A difference, not a fit: the claim states a "
                       "per-additional-call increment"),
          "slope_ci": None if ci8 is None else str(ci8),
          "n_pairs": len(inc["pooled"]),
          "n_unpaired_dropped": inc["n_unpaired"],
          "per_level_secondary": inc["per_level"],
          "gateway_only_cross_check": {
              "median_ms": S.quantile(inc["gateway_only_pooled"], 0.50)
              if inc["gateway_only_pooled"] else None,
              "why": ("the whole-turn increment should equal the gateway-only increment, since "
                     "the Converse half happens once per turn regardless of N. A gap between "
                     "them is client-side overhead per call, not service time"),
              "scored": False},
          "guards": guards, "guard_detail": guard_detail}
    if failed_guards:
        r8 = O.not_measured("F6-8", f"guards failed: {', '.join(failed_guards)}",
                           n_attempted=n_att)
    elif ci8 is None:
        r8 = O.not_measured("F6-8", f"only {len(inc['pooled'])} paired increments; a bootstrap "
                                    f"CI needs 20", n_attempted=n_att)
    else:
        r8 = O.evaluate(O.Observation(case_id="F6-8", n_attempted=n_att,
                                     n_usable=len(inc["pooled"]), slope_ci=(ci8.lo, ci8.hi)))
    P.emit("F6-8", r8, p8, store)
    print(f"  F6-8: {r8['verdict']}  slope p50="
          f"{None if ci8 is None else round(ci8.point, 1)} ms/call "
          f"CI=({None if ci8 is None else round(ci8.lo, 1)}, "
          f"{None if ci8 is None else round(ci8.hi, 1)}) vs stated [{lo8:.0f}, {hi8:.0f}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
