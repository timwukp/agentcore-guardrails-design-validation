#!/usr/bin/env python3
"""F6-1, F6-3, F6-4, F6-9 — the gateway-side hops of §6.1, measured on the gateway.

    F6-1  BAND_CONTAINS (50, 200) ms   Hop #1, "Gateway Guardrail (Input)", enforced by
                                       "AgentCore Gateway Policy". Instrument named by the
                                       document: "Gateway Latency + GuardrailLatency
                                       (`AWS/Bedrock-AgentCore`)".
    F6-3  BAND_CONTAINS (5, 50) ms     Hop #4, "Tool Auth (Cedar Policy)". Instrument named by
                                       the document: "Policy invocation spans".
    F6-4  BAND_CONTAINS (50, 200) ms   Hop #5, "Tool Guardrails (per call)", "50–200ms × N
                                       calls". Instrument named by the document:
                                       "GuardrailLatency (ToolName dimension)".
    F6-9  SHIFT_EXCLUDES_ZERO          §7.1 / Appendix B: "Block obviously harmful content at
                                       the Gateway (Hop #1) to avoid unnecessary downstream
                                       processing"; "Block at Hop#1 to skip Hops #2–6 entirely".

Three arms. Two of them are one configuration each, and the third is a subset of the second.

    cedar_only   the engine's steady state: `permit(principal, action, resource is
                 AgentCore::Gateway);` and nothing else. PURE Cedar — `definition.cedar`, no
                 guardrail block anywhere on the engine. Per-request instrument: the
                 `AgentCore.Policy.AuthorizeAction` span's `durationNano`. This is F6-3.

    guardrail    the same baseline permit PLUS one probe policy carrying a guardrail block, in
                 ENFORCE. Created at the start of the arm and deleted at the end. Per-request
                 instruments: the same span, and CloudWatch `GuardrailLatency`. This is F6-1
                 and F6-4.

    blocked/passed   within the `guardrail` arm, half the trials send benign text and half send
                 text from `corpora/content_filter/hate.jsonl`. The guardrail is a `forbid`, so
                 the violating half is denied at the gateway and the tool is never invoked.
                 This is F6-9.

WHY F6-1 AND F6-4 CANNOT BE SEPARATED HERE, AND WHY IT DOES NOT CHANGE EITHER VERDICT
-------------------------------------------------------------------------------------
§6.1 row 1 (Hop #1) and row 5 (Hop #5) are two different rows naming the same enforcement
point — "AgentCore Gateway Policy" — and the document distinguishes them by *when* the
evaluation happens: row 1 on the way in, row 5 per tool call. In this testbed there is no
agent runtime, so a `tools/call` is the only way in: the same policy evaluation is both.

That is not merely a gap in our testbed. It is what the service allows. F4 MEASURED
(2026-08-11, run r20260810T130945Z) that a guardrail statement whose action scope is
unconstrained denies EVERY request at this gateway with

    Authorization denied: a guardrail policy could not be evaluated - missing an attribute.
    Please retry.

because the guardrail's data path `context.input.text` does not exist on requests that are not
a `tools/call` carrying a `text` argument, and an unevaluable guardrail fails closed. So the
only guardrail policy an AgentCore gateway will actually evaluate is one scoped to a specific
tool action — which is row 5's "Tool Guardrails (per call)". **There is no configuration of
this service that produces row 1 as something distinct from row 5.** F7-1's inventory adds the
telemetry half of the same fact: `GuardrailLatency` publishes under `[OperationName,
TargetResource]` and carries no dimension that would tell an input-side evaluation from a
per-tool one.

The conflation is therefore recorded as a deviation, and it is harmless for the verdicts
because **both rows claim the same band**: 50–200 ms. One measurement decides both, and no
reading of which hop it belongs to can move it into or out of a band it shares. If the two rows
had claimed different bands this script could not have run at all.

Row 5's instrument claim is a separate, falsifiable matter and is checked separately:
"GuardrailLatency (ToolName dimension)". F7-1's inventory recorded `GuardrailLatency` with
dimensions `OperationName` and `TargetResource` only, while its sibling `AllowDecisions` — same
namespace, same operation, same requests — does carry `ToolName`. This script re-reads the
dimension list live, under a guardrail policy scoped to one tool action, which is the exact
configuration under which a `ToolName` dimension would have to appear if it existed.

WHAT THE GUARDRAIL HOP'S PER-REQUEST SERIES IS, DECIDED BEFORE THE DATA
-----------------------------------------------------------------------
`BAND_CONTAINS` computes p50/p90/p99 from a per-request series. `GuardrailLatency` is a
CloudWatch metric, and CloudWatch returns aggregates: at the 60-second grid one datapoint
covers every request in that minute, so its Average is not a per-request value. The per-request
instrument that does exist is the span, and the span carries the whole policy evaluation rather
than the guardrail portion of it. So:

    PRIMARY (F6-1, F6-4)   guardrail_hop_i = durationNano_i(guardrail arm, ms)
                                             - p50(durationNano, cedar_only arm)

    CROSS-INSTRUMENT CHECK CloudWatch `GuardrailLatency` p50/p90/p99 over the guardrail arm's
                           window, read with `ExtendedStatistics` — the document's own named
                           instrument, computed by the service over every request in the arm.

Subtracting a CONSTANT (the baseline arm's median) is exact on order statistics: p(X - c) =
p(X) - c. What it does not do is propagate the uncertainty in c, so the baseline's own CI is
recorded beside it; at n=1000 that interval is a couple of milliseconds against a band 150 ms
wide. Negative values are kept if they occur — a guardrail arm request faster than the median
baseline request is a real observation, and dropping the left tail would raise every quantile.

Pre-committed both ways, before any number was seen: if the primary series and the
cross-instrument check disagree about whether the distribution lies inside 50–200 ms, the
verdict is INCONCLUSIVE. Two instruments for one quantity is only worth having if disagreement
costs something.

F6-9'S DIRECTION IS CHECKED EXPLICITLY
--------------------------------------
The sealed kind is `SHIFT_EXCLUDES_ZERO`, which is symmetric: it returns TRUE for a confidence
interval that excludes 0 in either direction. The claim is not symmetric — it says blocking
early *saves* work. The shift is computed as `passed - blocked` and its sign is asserted
separately, so a world in which blocked requests were reliably SLOWER cannot be published as
support for "fail fast". Same tightening as F6-2's second condition: it can only turn a TRUE
into a FALSE.

What F6-9 can and cannot reach here: "skip Hops #2–6 entirely" is a claim about a pipeline with
a model in it, and this gateway's downstream is a Lambda echo target. The *direction* — a
request blocked at the gateway costs less than one that runs the tool — is exactly what this
testbed can measure, and it is what the sealed kind encodes. The MAGNITUDE ("up to 100% of
downstream hops") is not scored, and the recorded reason is that our downstream is one Lambda
invocation rather than five hops.

MUTATION, AND THE RESTORE
-------------------------
This script creates one policy on the shared engine `grx_pe_...-t6hqadrspf` and deletes it.
That is a mutation of a shared resource, so it follows F4's pattern exactly: registered in
`state.json` the moment `CreatePolicy` returns and before any status poll, deleted in a
`finally`, and then the Phase-2 blocking assertion is RE-RUN rather than assumed. The probe
policy is created in ENFORCE — unlike F4's stage policies, which are created LOG_ONLY — because
F6-1's quantity is the cost of an enforcing guardrail evaluation, and a LOG_ONLY guardrail is a
different code path whose cost is not what §6.1 row 1 is about.

COST
----
3,000 gateway requests (2 arms x n=1000, plus the MCP handshakes), 1 Lambda invocation per
allowed request, 2 policy mutations, and roughly 80 Logs Insights queries to join the spans.
Gateway invocations and Cedar evaluations are not separately billed; the Lambda time is
~1.5 s total at 128 MB. Under $0.10 in total, dominated by the Logs Insights scan.
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                   # noqa: E402
import cedar                                             # noqa: E402
import mcp as M                                          # noqa: E402
import oracle as O                                       # noqa: E402
import phase1 as P                                       # noqa: E402
import stats as S                                        # noqa: E402
import testbed as T                                      # noqa: E402
from checkpoint import Checkpoint                        # noqa: E402
from evidence import EvidenceStore, capture              # noqa: E402

CASES = ("F6-1", "F6-3", "F6-4", "F6-9")
FAMILY = "f6_latency"
PLANNED_N = 1000                      # latency_arm_p99, sealed

# One definition of "terminal" for a policy, and one for a span log group, both borrowed rather
# than restated. `lib/tests/test_module_name_collisions.py` reads these literals statically, so
# the sys.modules keys are module-level constants and are distinct from every other loader's.
PE_MODULE_NAME = "grx_f6_infra_03_policy_engine"
TRACES_MODULE_NAME = "grx_f6_infra_07_traces"
VERIFY_MODULE_NAME = "grx_f6_infra_06_verify"


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
_tr = _register(importlib.util.spec_from_file_location(
    TRACES_MODULE_NAME, ROOT / "infra" / "07_traces.py"))
_vf = _register(importlib.util.spec_from_file_location(
    VERIFY_MODULE_NAME, ROOT / "infra" / "06_verify.py"))

wait_status = _pe.wait_status
PE_TERMINAL_OK = _pe.TERMINAL_OK
POLICY_TERMINAL_FOR_MUTATION = ("ACTIVE", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED")

NS = "AWS/Bedrock-AgentCore"
TOOL = "echo"
ARM_CEDAR = "cedar_only"
ARM_GUARDRAIL = "guardrail"

# The guardrail statement. Identical in shape to F4's, and for the reason F4 recorded: an
# authorization effect takes a `context.input.*` path (an output path is rejected outright by
# `definition.policy`), and the action scope is required at RUNTIME, not merely at validation.
GUARDRAIL_FUNCTION = "ContentFilter"
GUARDRAIL_CATEGORY = "HATE"
GUARDRAIL_PATH = "context.input.text"
GUARDRAIL_THRESHOLD = "0.2"
VALIDATION_MODE = "IGNORE_ALL_FINDINGS"
POLICY_ENFORCE = "ACTIVE"             # EnforcementMode: an ACTIVE policy enforces
DELETE_ATTEMPTS = 5
DELETE_SLEEP_S = 3.0
POLICY_SETTLE_S = 20.0                # after a mutation lands, before the first timed request

# Clock-skew allowance on each end of an arm's CloudWatch read range. Small on purpose: the
# window now comes from the SERVICE's own clock (span timestamps), the same clock CloudWatch
# buckets by, so there is nothing to reconcile. It is not a publish-lag allowance — lag decides
# when a datapoint is readable, not which bucket it lands in, and applying it here is what let
# the Cedar arm's read reach into the guardrail arm on 2026-08-12.
WINDOW_SKEW_S = 5.0

# Pacing. A gateway request costs ~30 ms when Cedar-only and ~400 ms under a guardrail, so the
# arms are not paced to a CloudWatch grid — the per-request instrument is the span. The small
# gap keeps a single MCP session from pipelining requests, which would put queueing time inside
# a hop measurement.
INTER_CALL_S = 0.02

# Spans publish through a delivery to `aws/spans` with a lag F7 measured at ~115 s. The join
# waits longer than that before the first query and re-queries any id it did not find.
SPAN_SETTLE_S = 300.0
SPAN_BATCH = 40                       # request ids per Logs Insights query
SPAN_QUERY_LIMIT = 400
SPAN_LOOKBACK_MIN = 240
SPAN_RETRY_ROUNDS = 3
SPAN_RETRY_SLEEP_S = 90.0
AUTHZ_SPAN = "AgentCore.Policy.AuthorizeAction"

# The minimum join rate an arm needs before its span series can carry a verdict. Not 100%:
# `aws/spans` is a best-effort delivery and one dropped span in a thousand is not a fact about
# latency. A rate this high also cannot hide a systematic loss — a guardrail arm that dropped
# every slow span would fail it by a mile.
MIN_JOIN_RATE = 0.90

# F6-9's two halves, and the corpus they come from. `verify_corpora.py` pins these files.
HATE_CORPUS = ROOT / "corpora" / "content_filter" / "hate.jsonl"
BENIGN_CORPUS = ROOT / "corpora" / "benign" / "benign.jsonl"
CORPUS_SEED = 20260809                # the project's fixed seed, as in lib/stats.py

GUARDS = ("calls_reached_gateway", "spans_joined", "arm_windows_recovered",
          "guardrail_ran_only_where_intended", "probe_policy_removed",
          "testbed_intact_after_restore")
# F6-1/F6-4 carry one more, and F6-9 carries one of its own.
GUARD_AGREE = "two_instruments_agree"
GUARD_BOTH_HALVES = "blocked_and_passed_both_occurred"


class ConfigError(RuntimeError):
    """The testbed is not in a state whose latency means what a case says it means."""


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------

def _corpus(path: Path, n: int) -> list[dict[str, str]]:
    """`n` rows drawn deterministically from a corpus file, cycling if it is shorter.

    Deterministic because a latency arm re-run from a checkpoint has to send the same text: a
    resumed trial that drew a different row would put text-length variance into a hop
    measurement, and the trial ids would no longer name the same experiment.
    """
    if not path.is_file():
        raise ConfigError(f"corpus {path} is missing; F6-9 has no traffic without it")
    rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    if not rows:
        raise ConfigError(f"corpus {path} is empty")
    rng = random.Random(CORPUS_SEED)
    order = list(range(len(rows)))
    rng.shuffle(order)
    out = []
    for i in range(n):
        r = rows[order[i % len(order)]]
        out.append({"id": r["id"], "text": r["text"], "label": r.get("label", "")})
    return out


# ---------------------------------------------------------------------------
# one trial
# ---------------------------------------------------------------------------

def _call(client, tool_name: str, item: dict[str, str]) -> dict[str, Any]:
    """One `tools/call`, recorded as an observation. No verdict here.

    `t_send` is stamped BEFORE the POST and kept on the row. It is not used to time anything —
    `perf_counter` does that — it exists so an arm's CloudWatch window can be derived from the
    trials themselves rather than from the loop that ran them. See `_arm_window`: a loop-derived
    window is wrong whenever the arm resumes from a checkpoint, and this run's first attempt
    published four INCONCLUSIVE verdicts because of it.
    """
    t_send = time.time()
    t0 = time.perf_counter()
    try:
        d = client.call_tool(tool_name, {"text": item["text"]})
    except M.McpTransportError as exc:
        return {"outcome": "transport_error", "error": str(exc), "t_send": t_send,
                "corpus_id": item["id"], "corpus_label": item["label"]}
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "outcome": d.outcome,
        "request_id": d.request_id,
        "denied": bool(d.denied),
        "default_deny": bool(d.default_deny),
        "client_ms": round(elapsed_ms, 3),
        "gateway_ms": round(d.duration_ms, 3),
        "t_send": t_send,
        "corpus_id": item["id"],
        "corpus_label": item["label"],
        "text_len": len(item["text"]),
    }


def _run_arm(store: EvidenceStore, client, tool_name: str, *, cell: str, items: list[dict],
             is_smoke: bool, arm: str, policy_shape: str) -> Checkpoint:
    """Collect one arm, resumable. The checkpoint's design keys pin what the arm WAS."""
    cp = Checkpoint(case_id=CASES[0], cell=cell).load()
    cp.set_meta(arm=arm, policy_shape=policy_shape, is_smoke=is_smoke,
                n_planned=len(items), corpus_seed=CORPUS_SEED, tool=tool_name)
    for i, item in enumerate(items):
        tid = f"t{i:04d}"
        if cp.is_done(tid):
            continue
        client.refresh_if_stale()
        cp.run_trial(tid, lambda it=item: _call(client, tool_name, it))
        if INTER_CALL_S:
            time.sleep(INTER_CALL_S)
    return cp


# ---------------------------------------------------------------------------
# spans
# ---------------------------------------------------------------------------

def _span_epoch(value: str | None) -> float | None:
    """Logs Insights `@timestamp` as epoch seconds. UTC, always — the field has no zone.

    `%f` is optional because Insights drops a trailing all-zero millisecond field on some rows,
    and a window that silently lost those rows would be narrower than the arm it describes.
    Returns None rather than raising: an unparsable stamp must reduce the evidence for a window,
    not abort a run that has already spent its trials.
    """
    if not value:
        return None
    from datetime import datetime, timezone
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _arm_window(cp: Checkpoint, span_times: dict[str, float], *, label: str,
                n_real: int) -> dict[str, Any]:
    """One arm's true window, derived from its TRIALS rather than from the loop that ran them.

    Why this function exists
    -----------------------
    Measured 2026-08-12. The first full run of this file completed cleanly — 1000/1000 trials in
    both arms, 0 failures, spans joined 1000/1000 — and published F6-1, F6-3, F6-4 and F6-9 as
    INCONCLUSIVE on `guardrail_ran_only_where_intended`, with `cedar_arm_datapoints: 2` and
    `guardrail_arm_datapoints: 0`. Exactly backwards, and both halves were this harness:

      1. The window was `t0 = time.time()` before the arm's loop and `t1 = time.time()` after
         it. The `cedar_only` arm resumed every trial from its checkpoint after an earlier
         crash, so the loop ran nothing and the window was **5 ms wide** (t0=…148.2112,
         t1=…148.2166). Its read span then reached ~92 s past the arm into the guardrail arm and
         harvested 2 of that arm's datapoints. A wall-clock window does not describe an arm; it
         describes a loop, and the two coincide only on a run that resumes nothing.
      2. Separately, the read asked for `Period = int(t1 - t0) + 120 ≈ 1011`, and CloudWatch
         requires a multiple of 60 above 60 s, so the guardrail arm's own read returned nothing.

    Three sources, in decreasing order of authority, and every one of them derived from the
    trials so a resume cannot change the answer:

      * `spans`   — the `AuthorizeAction` span timestamps. The SERVICE's clock, which is the one
                    CloudWatch buckets by, so this needs no skew allowance at all.
      * `t_send`  — the per-trial stamp `_call` now writes. Survives a resume because it is on
                    the checkpoint row.
      * `none`    — neither is available (rows written before `t_send` existed, and no span
                    times). Then this arm has NO window and the caller must report its
                    CloudWatch cross-check as unavailable. Not a wall-clock fallback: that is
                    the value that produced the defect, and a wrong window is worse than a
                    missing one because it answers.

    `plausible` is the tripwire for the specific failure above: an arm of `n_real` trials paced
    at `INTER_CALL_S` cannot occupy less than that. A window that fails it is not this arm's.
    """
    out: dict[str, Any] = {"arm": label, "n_real": n_real}
    rows = cp.results()
    span_pts = sorted(span_times.values())
    send_pts = sorted(float(r["t_send"]) for r in rows.values()
                      if isinstance(r.get("t_send"), (int, float)))
    out["n_span_times"] = len(span_pts)
    out["n_t_send"] = len(send_pts)

    if len(span_pts) >= max(2, int(0.5 * n_real)):
        pts, source = span_pts, "spans"
    elif len(send_pts) >= max(2, int(0.5 * n_real)):
        pts, source = send_pts, "t_send"
    else:
        out.update({
            "source": "none", "usable": False, "t0": None, "t1": None,
            "reason": (f"{len(span_pts)} span timestamps and {len(send_pts)} t_send stamps for "
                       f"{n_real} trials: fewer than half of this arm's trials can place "
                       f"themselves in time, so the arm has no window. Rows collected before "
                       f"`t_send` was added carry no stamp, which is the state a resumed "
                       f"checkpoint from an earlier run is in."),
        })
        return out

    t0, t1 = pts[0], pts[-1]
    # A span's timestamp is when the span was emitted, i.e. at the END of the evaluation it
    # measures; the request began up to one span-duration earlier. Widening by the largest
    # observed duration keeps the first request inside the window without guessing.
    floor_s = max(1.0, n_real * INTER_CALL_S)
    out.update({
        "source": source, "usable": True, "t0": t0, "t1": t1,
        "duration_s": round(t1 - t0, 3),
        "floor_s": round(floor_s, 3),
        "plausible": (t1 - t0) >= floor_s,
        "why_floor": (f"{n_real} trials paced at INTER_CALL_S={INTER_CALL_S}s cannot occupy "
                      f"less than {floor_s:.1f}s; a narrower window belongs to something other "
                      f"than this arm (the 5 ms window of 2026-08-12)"),
    })
    if not out["plausible"]:
        out["usable"] = False
        out["reason"] = (f"the derived window is {t1 - t0:.3f}s wide for {n_real} trials, below "
                         f"the {floor_s:.1f}s floor")
    return out


def _join_spans(logs, gateway_arn: str, want: list[str]) -> dict[str, Any]:
    """`AuthorizeAction` durations for these request ids, keyed by request id.

    Queried in batches with the ids in the filter, so a batch cannot silently truncate the way
    an unfiltered `limit`-bounded query would: every batch asks for at most `SPAN_BATCH` ids and
    the limit is an order of magnitude above that. Ids not found are retried, because the span
    delivery's lag is a distribution and the tail of it is longer than the settle.
    """
    found: dict[str, float] = {}
    times: dict[str, float] = {}
    n_queries = 0
    truncated = False
    pending = list(dict.fromkeys(i for i in want if i))
    for rnd in range(SPAN_RETRY_ROUNDS):
        if not pending:
            break
        if rnd:
            time.sleep(SPAN_RETRY_SLEEP_S)
        still: list[str] = []
        for start in range(0, len(pending), SPAN_BATCH):
            batch = pending[start:start + SPAN_BATCH]
            clause = " or ".join(f'@message like "{i}"' for i in batch)
            rows = _tr.query_spans(logs, gateway_arn, minutes=SPAN_LOOKBACK_MIN,
                                  limit=SPAN_QUERY_LIMIT, extra_filter=f"filter {clause}")
            n_queries += 1
            if len(rows) >= SPAN_QUERY_LIMIT:
                truncated = True
            for row in rows:
                msg = next((f["value"] for f in row if f.get("field") == "@message"), None)
                if not msg:
                    continue
                try:
                    obj = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                if obj.get("name") != AUTHZ_SPAN:
                    continue
                rid = (obj.get("attributes") or {}).get("aws.request.id")
                dur = obj.get("durationNano")
                if rid in batch and dur is not None:
                    # One span per request id. A duplicate would mean two policy evaluations for
                    # one request, which is a finding rather than something to average away.
                    if rid not in found:
                        found[rid] = float(dur) / 1e6
                        ts = _span_epoch(next((f["value"] for f in row
                                               if f.get("field") == "@timestamp"), None))
                        if ts is not None:
                            times[rid] = ts
            still.extend(i for i in batch if i not in found)
        pending = still
    return {"durations_ms": found, "times_s": times, "n_queries": n_queries,
            "truncated": truncated, "missing": pending, "n_found": len(found),
            "n_wanted": len(want), "n_timed": len(times)}


def _attach_spans(cp: Checkpoint, spans: dict[str, float]) -> dict[str, Any]:
    """Per-trial rows joined to their span duration, in trial-id order."""
    rows = cp.results()
    joined, unjoined = [], 0
    for tid in sorted(rows):
        r = rows[tid]
        rid = r.get("request_id") or ""
        if rid in spans:
            joined.append({**r, "trial": tid, "authz_ms": spans[rid]})
        else:
            unjoined += 1
    n_real = sum(1 for tid in sorted(rows)
                 if rows[tid].get("outcome") in ("allowed", "policy_denied"))
    return {"rows": joined, "n_joined": len(joined), "n_unjoined": unjoined,
            "n_real": n_real,
            "join_rate": (len(joined) / n_real) if n_real else 0.0}


# ---------------------------------------------------------------------------
# CloudWatch: the document's own named instrument
# ---------------------------------------------------------------------------

def _guardrail_latency(cw, store, gateway_id: str, *, window: dict[str, Any],
                       alpha: float, read_end_cap: float | None = None) -> dict[str, Any]:
    """`GuardrailLatency` percentiles over one arm's window, and the ToolName dimension probe.

    The dimension combination is read from `ListMetrics` rather than assembled from a per-name
    value list — the error DEV-P4-04 round 4 records against `04_publish_lag.py`, where a union
    of two names from two different published combinations produced a query no series answers.

    `window` comes from `_arm_window` and may be unusable, in which case this returns without
    querying: the two failures of 2026-08-12 were a window that described the wrong interval and
    a `Period` CloudWatch rejects, and both produced a NUMBER rather than an error. `read_end_cap`
    is the wall-clock instant after which this arm's traffic provably stopped — the probe's
    creation time, for the Cedar-only arm. Without it, the read's own tail is what reaches into
    the next arm: POLICY_SETTLE_S is 20 s and the old tail was 120 s, so the Cedar arm's query
    covered 100 s of guardrail traffic no matter how accurate its window was.
    """
    from datetime import datetime, timezone
    out: dict[str, Any] = {"metric": "GuardrailLatency", "namespace": NS,
                           "window": window}

    combos, token = [], None
    while True:
        kw: dict[str, Any] = {"Namespace": NS, "MetricName": "GuardrailLatency"}
        if token:
            kw["NextToken"] = token
        rec = capture(store, "list_metrics", cw, **kw)
        if not rec.ok:
            out["error"] = rec.error_code
            return out
        combos.extend(rec.response.get("Metrics") or [])
        token = rec.response.get("NextToken")
        if not token:
            break

    ours = [[{"Name": d["Name"], "Value": d["Value"]} for d in (m.get("Dimensions") or [])]
            for m in combos
            if any(gateway_id in d["Value"] for d in (m.get("Dimensions") or []))]
    names = sorted({d["Name"] for c in ours for d in c})
    out["published_combinations_for_this_gateway"] = ours
    out["dimension_names"] = names
    # §6.1 row 5's instrument claim, checked under the exact configuration in which the claimed
    # dimension would have to appear: a guardrail policy scoped to ONE tool action.
    out["tool_name_dimension_claim"] = {
        "documented_as": "GuardrailLatency (ToolName dimension)",
        "tool_name_dimension_exists": "ToolName" in names,
        "dimension_names_found": names,
        "sibling_control": ("AllowDecisions is published by the same operation on the same "
                            "requests and DOES carry ToolName (F7-1 inventory), so an absence "
                            "here is a property of this metric rather than of our traffic"),
    }
    if not ours:
        out["error"] = "no published GuardrailLatency series names this gateway"
        return out

    dims = max(ours, key=len)
    out["dimensions_read"] = dims

    if not window.get("usable"):
        out["error"] = "unavailable"
        out["unavailable_because"] = window.get("reason", "no usable window for this arm")
        return out

    # The read range is the arm's window plus a small skew allowance, and nothing more. There is
    # no publish-lag tail: `GetMetricStatistics` buckets a datapoint by the metric's OWN
    # timestamp, which is the request time, so lag governs when the datapoint becomes READABLE,
    # not where it sits. The old +120 s tail was a lag allowance applied to the wrong axis, and
    # on the Cedar arm it was the whole defect — see this function's docstring.
    read_t0 = window["t0"] - WINDOW_SKEW_S
    read_t1 = window["t1"] + WINDOW_SKEW_S
    if read_end_cap is not None and read_end_cap < read_t1:
        out["read_end_capped_at"] = read_end_cap
        out["read_end_cap_reason"] = ("this arm's traffic provably stopped here (the next arm's "
                                      "mutation landed), so the read must not extend past it")
        read_t1 = read_end_cap
    if read_t1 <= read_t0:
        out["error"] = "unavailable"
        out["unavailable_because"] = (f"the capped read range is empty: "
                                      f"{read_t0:.3f} .. {read_t1:.3f}")
        return out
    # Period must be a multiple of 60 above 60 s — CloudWatch returns NO datapoints otherwise,
    # which is indistinguishable from a metric that was never published. Rounded UP so one
    # period covers the whole range and the read cannot be split across period edges.
    span_s = 60 * max(1, math.ceil((read_t1 - read_t0) / 60.0))
    out["read_range_s"] = round(read_t1 - read_t0, 3)
    rec = capture(store, "get_metric_statistics", cw,
                  Namespace=NS, MetricName="GuardrailLatency", Dimensions=dims,
                  StartTime=datetime.fromtimestamp(read_t0, timezone.utc),
                  EndTime=datetime.fromtimestamp(read_t1, timezone.utc),
                  Period=span_s,
                  Statistics=["SampleCount", "Average", "Minimum", "Maximum", "Sum"],
                  ExtendedStatistics=["p50", "p90", "p99"])
    if not rec.ok:
        out["error"] = rec.error_code
        return out
    dps = rec.response.get("Datapoints") or []
    out["n_datapoints"] = len(dps)
    if not dps:
        out["error"] = "no GuardrailLatency datapoints in the arm's window"
        return out
    # One period covering the whole arm, so CloudWatch's percentiles are over every request in
    # it. More than one datapoint would mean the window straddled a period edge; the largest
    # SampleCount is the arm's, and the count is recorded so a partial read is visible.
    dp = max(dps, key=lambda d: d.get("SampleCount", 0))
    ext = dp.get("ExtendedStatistics") or {}
    out.update({
        "sample_count": dp.get("SampleCount"),
        "unit": dp.get("Unit"),
        "min": dp.get("Minimum"), "max": dp.get("Maximum"), "mean": dp.get("Average"),
        "p50": ext.get("p50"), "p90": ext.get("p90"), "p99": ext.get("p99"),
        "period_s": span_s,
        "alpha": alpha,
        "why_no_ci": ("CloudWatch returns a percentile, not an interval; the per-request "
                      "series carries the CIs and this read is the cross-instrument check"),
    })
    return out


def _in_band(p50: float | None, top: float | None, lo: float, hi: float) -> bool | None:
    """The same test `oracle.BAND_CONTAINS` applies, for the cross-instrument comparison."""
    if p50 is None or top is None:
        return None
    return bool(p50 >= lo and top <= hi)


# ---------------------------------------------------------------------------
# the probe policy
# ---------------------------------------------------------------------------

def _create_probe(ac, store, state: T.State, *, engine_id: str, run_id: str,
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

    name = f"grx_f6_guardrail_{run_id}"
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac, name=name, policyEngineId=engine_id,
                  # `policy`, not `cedar`: F4-0 measured that `definition.cedar` rejects
                  # `when guardrails` as an unexpected token. Two members, two parsers.
                  definition={"policy": {"statement": stmt}},
                  description="F6-1/F6-4 probe: guardrail hop latency",
                  validationMode=VALIDATION_MODE,
                  enforcementMode=POLICY_ENFORCE)
    if not rec.ok:
        raise ConfigError(f"CreatePolicy failed: {rec.error_code}: {rec.error_message}")
    pid = rec.response.get("policyId")
    if not pid:
        raise ConfigError("CreatePolicy returned no policyId")
    state.record(T.Resource(
        kind="policy", logical="f6_guardrail_probe", name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid, "statement": stmt,
             "enforcement_mode_at_create": POLICY_ENFORCE,
             "validation_mode_sent": VALIDATION_MODE},
        arn=rec.response.get("policyArn", ""), delete_priority=40,
        notes=("F6 guardrail probe. `policy` takes no tags, so this ledger entry and this "
               "script's finally are the only channels that can find it")))
    live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
    if live.get("status") not in PE_TERMINAL_OK:
        raise ConfigError(
            f"the probe policy settled {live.get('status')} "
            f"(reasons={live.get('statusReasons')}); an inert policy would make the guardrail "
            f"arm a second copy of the Cedar-only arm and its 'guardrail hop' a measurement of "
            f"nothing")
    print(f"    probe policy {pid} ACTIVE ({POLICY_ENFORCE})")
    return pid


def _delete_probe(ac, store, state: T.State, *, engine_id: str, policy_id: str) -> dict:
    """Delete the probe. Never raises: this runs in a finally."""
    errors = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac,
                      policyEngineId=engine_id, policyId=policy_id)
        if rec.ok or rec.error_code == "ResourceNotFoundException":
            state.drop("policy", "f6_guardrail_probe")
            print(f"    probe policy deleted (attempt {attempt})")
            return {"deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}")
        if attempt < DELETE_ATTEMPTS:
            time.sleep(DELETE_SLEEP_S)
    print(f"    WARN probe policy NOT deleted: {'; '.join(errors)}", file=sys.stderr)
    return {"deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors}


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def _describe(values: list[float], *, alpha: float, allow_p99: bool) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    out: dict[str, Any] = {
        "n": len(values), "min": round(min(values), 3), "max": round(max(values), 3),
        "p50": round(S.quantile(values, 0.50), 3),
        "p90": round(S.quantile(values, 0.90), 3),
        "ci_p50": str(S.quantile_ci(values, 0.50, level=1 - alpha)),
        "ci_p90": str(S.quantile_ci(values, 0.90, level=1 - alpha)),
    }
    if allow_p99 and len(values) >= 100:
        out["p99"] = round(S.quantile(values, 0.99), 3)
        out["ci_p99"] = str(S.quantile_ci(values, 0.99, level=1 - alpha))
    else:
        out["p99"] = None
        out["why_no_p99"] = "a p99 needs n>=100; a printed p99 gets quoted"
    return out


def main(argv: list[str] | None = None) -> int:                     # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASES[0], __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else PLANNED_N
    is_smoke = args.n is not None

    if args.dry_run:
        for case in CASES:
            P.dry_run_banner(
                case,
                [(ARM_CEDAR, "baseline permit only — pure Cedar, the F6-3 arm", n),
                 (ARM_GUARDRAIL, "baseline permit + a guardrail-bearing ENFORCE probe policy; "
                                 "half benign, half HATE corpus", n)],
                # The breakdown partitions the ARM PLAN, so only the timed trials appear here.
                # The ancillary calls are not trials and are listed below rather than folded in:
                # a breakdown that summed to more than the plan would be a second label over the
                # same quantity, which is what this argument exists to catch.
                operations={"mcp_tools_call": 2 * n},
                mutations=2, billable=True,
                extra=[
                    f"ancillary, NOT part of the arm plan: create_policy x1, delete_policy x1, "
                    f"logs_insights_query x~{2 * n // SPAN_BATCH + 8}, list_metrics x~4, "
                    f"get_metric_statistics x2, and 1 MCP initialize",
                    "F6-1 and F6-4 read ONE measurement: the service evaluates a gateway "
                    "guardrail only under an action-scoped policy, which is Hop #5's shape, "
                    "and both rows claim the same 50-200ms band. See the module docstring",
                    "the guardrail hop's per-request series is the guardrail arm's span "
                    "duration minus the Cedar-only arm's MEDIAN span duration, decided before "
                    "the data; CloudWatch GuardrailLatency percentiles are the independent "
                    "cross-instrument check and a disagreement publishes INCONCLUSIVE",
                    "F6-9's shift is passed - blocked and its SIGN is asserted separately, "
                    "because SHIFT_EXCLUDES_ZERO is direction-blind",
                    "one policy is created on the shared engine in ENFORCE and deleted in a "
                    "finally; the Phase-2 blocking assertion is then RE-RUN",
                    f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}, "
                    f"{GUARD_AGREE} (F6-1/F6-4), {GUARD_BOTH_HALVES} (F6-9)",
                ])
            print()
        return 0

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    cw = fc.client("cloudwatch")
    logs = fc.client("logs")
    ac = fc.client("bedrock-agentcore-control")
    account_id = A.account_id(fc)
    store = EvidenceStore(run_id, FAMILY, "F6-1_3_4_9")
    store.write_environment()

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
        raise ConfigError("the main gateway has no policy engine; F6-3 has nothing to time")
    action_id = next((a for a in (tgt.ids.get("cedar_action_ids") or [])
                      if a.endswith(f"___{TOOL}")), "")
    if not action_id:
        raise ConfigError(f"no cedar action id ends with ___{TOOL}")

    alpha = O.alpha_for(CASES[0])
    print(f"F6-1/3/4/9 — gateway hops, run_id={run_id}, region={region}")
    print(f"  gateway {gateway_id}  engine {engine_id}  action {action_id}")
    print(f"  arms: {ARM_CEDAR} n={n}, {ARM_GUARDRAIL} n={n} (half HATE)")

    # Half benign, half violating, interleaved so the two halves see the same conditions.
    half = n // 2
    benign = _corpus(BENIGN_CORPUS, n - half)
    hate = _corpus(HATE_CORPUS, half)
    mixed: list[dict[str, str]] = []
    for i in range(n):
        mixed.append(benign[i // 2] if i % 2 == 0 else hate[i // 2])
    mixed = mixed[:n]

    common: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke, "cell": "latency_arm_p99",
        "planned_n_cell": PLANNED_N, "n_requested": n, "alpha": alpha,
        "ambient_sdk": A.sdk_versions(), "gateway_id": gateway_id,
        "policy_engine_id": engine_id, "action_id": action_id,
        "probe_statement_shape": {
            "effect": "forbid", "function": GUARDRAIL_FUNCTION,
            "category": GUARDRAIL_CATEGORY, "data_path": GUARDRAIL_PATH,
            "threshold": GUARDRAIL_THRESHOLD, "enforcement_mode": POLICY_ENFORCE,
            "why_action_scoped": ("F4 measured that an unscoped guardrail denies every request "
                                 "with 'a guardrail policy could not be evaluated - missing an "
                                 "attribute'; an unevaluable guardrail fails closed, so the "
                                 "only guardrail an AgentCore gateway evaluates is scoped to a "
                                 "tool action"),
        },
        "hop_conflation": {
            "cases_affected": ["F6-1", "F6-4"],
            "claim": ("§6.1 row 1 (Hop #1, gateway input guardrail) and row 5 (Hop #5, tool "
                      "guardrails per call) name the same enforcement point and are separated "
                      "only by when the evaluation happens"),
            "why_not_separable": ("there is no agent runtime in this testbed, so a tools/call "
                                 "is the only way in; and the service will only evaluate an "
                                 "action-scoped guardrail, which is row 5's shape"),
            "why_it_cannot_change_a_verdict": ("both rows claim the same band, 50-200 ms, so "
                                              "one measurement decides both and no attribution "
                                              "of the hop moves it across a boundary"),
            "telemetry_half": ("GuardrailLatency publishes under [OperationName, "
                              "TargetResource] and carries no dimension separating an "
                              "input-side evaluation from a per-tool one"),
        },
    }

    client = M.client_for(gw.ids["gateway_url"], fc, store=store,
                         policy_session_id=M.policy_session_id(run_id, "f6gw"),
                         session_timeout_s=int(gw.ids.get("session_timeout_s", 900)))
    client.initialize()

    probe_id = ""
    probe_created_at: float | None = None
    restore: dict[str, Any] = {}
    wall: dict[str, dict[str, float]] = {}
    try:
        # --- arm 1: pure Cedar, the steady state. No mutation. ----------------
        print(f"  [{ARM_CEDAR}] n={n}")
        t0 = time.time()
        cp_c = _run_arm(store, client, action_id, cell=ARM_CEDAR,
                        items=_corpus(BENIGN_CORPUS, n), is_smoke=is_smoke,
                        arm=ARM_CEDAR, policy_shape="baseline_permit_only")
        # Recorded, not used as the window. `_arm_window` explains why: this pair describes the
        # LOOP, and on a resumed arm the loop runs nothing. Kept beside the derived window so the
        # two can be compared in the record.
        wall[ARM_CEDAR] = {"t0": t0, "t1": time.time()}
        print(f"    done: {cp_c.n_done} trials, {cp_c.n_failed} failures")

        # --- arm 2: the guardrail probe --------------------------------------
        probe_id = _create_probe(ac, store, state, engine_id=engine_id, run_id=run_id,
                                 gateway_arn=gateway_arn, action_id=action_id)
        probe_created_at = time.time()
        time.sleep(POLICY_SETTLE_S)
        print(f"  [{ARM_GUARDRAIL}] n={n}  ({n - half} benign / {half} HATE, interleaved)")
        t0 = time.time()
        cp_g = _run_arm(store, client, action_id, cell=ARM_GUARDRAIL, items=mixed,
                        is_smoke=is_smoke, arm=ARM_GUARDRAIL,
                        policy_shape="baseline_permit_plus_guardrail_forbid_enforce")
        wall[ARM_GUARDRAIL] = {"t0": t0, "t1": time.time()}
        print(f"    done: {cp_g.n_done} trials, {cp_g.n_failed} failures")

        # --- join the spans, INSIDE the probe's lifetime -----------------------
        # The span join has to come before the metric read for two reasons that pull the same
        # way. The spans are what the arms' windows are derived from (`_arm_window`), and
        # `GuardrailLatency` is only published while a guardrail exists — reading after the
        # delete risks a `ListMetrics` that no longer lists the arm's series. So the settle
        # happens here, with the probe still in place. It costs the probe a few extra minutes of
        # existence and no extra requests: nothing calls the gateway during the settle.
        print(f"  settling {SPAN_SETTLE_S:.0f}s for the span delivery, then joining")
        time.sleep(SPAN_SETTLE_S)
        ids_c = [r.get("request_id", "") for r in cp_c.results().values()]
        ids_g = [r.get("request_id", "") for r in cp_g.results().values()]
        sp_c = _join_spans(logs, gateway_arn, ids_c)
        sp_g = _join_spans(logs, gateway_arn, ids_g)
        jc = _attach_spans(cp_c, sp_c["durations_ms"])
        jg = _attach_spans(cp_g, sp_g["durations_ms"])
        print(f"    {ARM_CEDAR}: joined {jc['n_joined']}/{jc['n_real']} "
              f"({jc['join_rate']:.1%}, {sp_c['n_queries']} queries)")
        print(f"    {ARM_GUARDRAIL}: joined {jg['n_joined']}/{jg['n_real']} "
              f"({jg['join_rate']:.1%}, {sp_g['n_queries']} queries)")

        win_c = _arm_window(cp_c, sp_c["times_s"], label=ARM_CEDAR, n_real=jc["n_real"])
        win_g = _arm_window(cp_g, sp_g["times_s"], label=ARM_GUARDRAIL, n_real=jg["n_real"])
        for w in (win_c, win_g):
            w["wall_clock_loop"] = wall.get(w["arm"])
            print(f"    window[{w['arm']}]: source={w['source']} usable={w['usable']} "
                  f"width={w.get('duration_s')}s")
            if not w["usable"]:
                print(f"      unusable: {w.get('reason')}")

        # The Cedar arm's read is capped at the instant the probe landed. Past that point any
        # `GuardrailLatency` datapoint belongs to the other arm by construction, so without the
        # cap the guard's negative half is testing the read's tail rather than the arm.
        gl = _guardrail_latency(cw, store, gateway_id, alpha=alpha, window=win_g)
        gl_cedar = _guardrail_latency(cw, store, gateway_id, alpha=alpha, window=win_c,
                                      read_end_cap=probe_created_at)
    finally:
        if probe_id:
            restore["probe_delete"] = _delete_probe(ac, store, state, engine_id=engine_id,
                                                    policy_id=probe_id)
        client.close()

    # The restore is not assumed to have worked because an API call returned 200.
    checks = _vf.Checks()
    _vf.verify_engine(ac, state, checks)
    _vf.verify_gateways(ac, state, account_id, region, checks)
    cj = checks.to_json()
    restore["blocking_checks"] = cj
    n_fail = cj["n_fail"]
    print(f"  restore: blocking checks {cj['n_pass']} pass / {n_fail} fail")
    if n_fail:
        checks.print()

    cedar_ms = [r["authz_ms"] for r in jc["rows"]]
    guard_ms = [r["authz_ms"] for r in jg["rows"]]
    baseline_p50 = S.quantile(cedar_ms, 0.50) if cedar_ms else None
    hop_ms = ([v - baseline_p50 for v in guard_ms] if baseline_p50 is not None else [])

    lo1, hi1 = O.BINDINGS["F6-1"].thresholds
    cw_top = gl.get("p99") if gl.get("p99") is not None else gl.get("p90")
    cw_in_band = _in_band(gl.get("p50"), cw_top, lo1, hi1)
    span_top = S.quantile(hop_ms, 0.99) if len(hop_ms) >= 100 else (
        S.quantile(hop_ms, 0.90) if hop_ms else None)
    span_in_band = _in_band(S.quantile(hop_ms, 0.50) if hop_ms else None,
                            span_top, lo1, hi1)

    # --- guards -----------------------------------------------------------
    real_c = jc["n_real"]
    real_g = jg["n_real"]
    outcomes_g = [r.get("outcome") for r in cp_g.results().values()]
    blocked = [r for r in jg["rows"] if r.get("denied")]
    passed = [r for r in jg["rows"] if r.get("outcome") == "allowed"]

    guards = {
        "calls_reached_gateway": real_c >= max(1, int(0.99 * n)) and
                                 real_g >= max(1, int(0.99 * n)),
        "spans_joined": jc["join_rate"] >= MIN_JOIN_RATE and
                        jg["join_rate"] >= MIN_JOIN_RATE,
        "arm_windows_recovered": bool(win_c.get("usable")) and bool(win_g.get("usable")),
        "guardrail_ran_only_where_intended": bool(gl.get("n_datapoints")) and
                                             gl_cedar.get("error") != "unavailable" and
                                             not gl_cedar.get("n_datapoints"),
        "probe_policy_removed": bool(restore.get("probe_delete", {}).get("deleted")),
        "testbed_intact_after_restore": n_fail == 0,
    }
    guard_detail = {
        "calls_reached_gateway": {
            "test": "at least 99% of each arm's trials returned a real gateway outcome",
            "cedar_only_real": real_c, "guardrail_real": real_g, "n_planned": n},
        "spans_joined": {
            "test": f"each arm's AuthorizeAction span join rate >= {MIN_JOIN_RATE:.0%}",
            "cedar_only": jc["join_rate"], "guardrail": jg["join_rate"],
            "missing_cedar_only": len(sp_c["missing"]),
            "missing_guardrail": len(sp_g["missing"]),
            "truncated_any_query": sp_c["truncated"] or sp_g["truncated"],
            "why": ("a per-request latency series assembled from a partial join is a sample of "
                    "unknown selection; a systematically dropped slow tail would move every "
                    "quantile downwards, i.e. towards TRUE for a floor claim")},
        "arm_windows_recovered": {
            "test": ("each arm's CloudWatch window is derivable from its own trials — span "
                     "timestamps or the per-trial t_send — and is at least as wide as the "
                     "pacing floor for its trial count"),
            ARM_CEDAR: win_c, ARM_GUARDRAIL: win_g,
            "why": ("upstream of the guard below, and separate from it so the two failures are "
                    "distinguishable. On 2026-08-12 the Cedar arm resumed entirely from its "
                    "checkpoint, its loop-derived window was 5 ms wide, and the read reached "
                    "into the other arm; the guard below then failed and four cases published "
                    "INCONCLUSIVE with no way to tell a contaminated window from a service that "
                    "had evaluated the guardrail in both arms. This guard names the first cause")},
        "guardrail_ran_only_where_intended": {
            "test": ("GuardrailLatency has datapoints in the guardrail arm's window and NONE "
                     "in the Cedar-only arm's, with BOTH reads actually performed"),
            "guardrail_arm_datapoints": gl.get("n_datapoints", 0),
            "cedar_arm_datapoints": gl_cedar.get("n_datapoints", 0),
            "cedar_read_performed": gl_cedar.get("error") != "unavailable",
            "guardrail_read_performed": gl.get("error") != "unavailable",
            "why": ("this is the only evidence that the two arms differ in the way the design "
                    "says they do. A guardrail that silently evaluated in both arms would make "
                    "the paired difference an estimate of zero. A read that never happened is "
                    "NOT zero datapoints — an unperformed Cedar read fails this guard rather "
                    "than satisfying its negative half (feedback_missing_check_is_not_pass)")},
        "probe_policy_removed": restore.get("probe_delete", {}),
        "testbed_intact_after_restore": restore.get("blocking_checks", {}),
    }

    payload_common = {
        **common,
        "windows": {ARM_CEDAR: win_c, ARM_GUARDRAIL: win_g},
        "restore": restore,
        "span_join": {ARM_CEDAR: {k: v for k, v in sp_c.items() if k != "durations_ms"},
                      ARM_GUARDRAIL: {k: v for k, v in sp_g.items()
                                      if k != "durations_ms"}},
        "guardrail_latency_metric": {"guardrail_arm": gl, "cedar_only_arm": gl_cedar},
        "arms": {
            ARM_CEDAR: {"n_trials": cp_c.n_done, "n_failed": cp_c.n_failed,
                        "authz_ms": _describe(cedar_ms, alpha=alpha, allow_p99=True)},
            ARM_GUARDRAIL: {"n_trials": cp_g.n_done, "n_failed": cp_g.n_failed,
                            "authz_ms": _describe(guard_ms, alpha=alpha, allow_p99=True),
                            "outcomes": {o: outcomes_g.count(o)
                                         for o in sorted(set(outcomes_g))}},
        },
        "guards": guards,
        "guard_detail": guard_detail,
        "guard_names": list(GUARDS),
    }

    failed = [g for g, ok in guards.items() if not ok]
    rc = 0

    # ---------------- F6-3: Cedar-only policy evaluation ------------------
    p3: dict[str, Any] = {**payload_common,
                          "instrument": (f"{AUTHZ_SPAN}.durationNano in the {ARM_CEDAR} arm, "
                                         f"ms. The document names 'Policy invocation spans'"),
                          "series": "authz_ms (cedar_only)",
                          "what_true_does_not_prove": (
                              "this is the WHOLE policy evaluation for a policy that is pure "
                              "Cedar, which is what row 4 claims a band for. It is not a "
                              "measurement of Cedar's evaluator in isolation — the span covers "
                              "the service's dispatch as well, so it is an upper bound on the "
                              "evaluator and a value below the 5 ms floor would be decisive "
                              "while one inside the band cannot separate the two")}
    if failed:
        r3 = O.not_measured("F6-3", f"guard(s) {', '.join(failed)} did not hold, so a policy "
                                    f"evaluation latency measured here is not this "
                                    f"configuration's", guards=guards)
    else:
        r3 = O.evaluate(O.Observation(case_id="F6-3", n_attempted=cp_c.n_done,
                                      n_usable=len(cedar_ms), latencies_ms=cedar_ms))
    P.emit("F6-3", r3, p3, store)
    print(f"  F6-3: {r3['verdict']}  {p3['arms'][ARM_CEDAR]['authz_ms']}  "
          f"(band {O.BINDINGS['F6-3'].thresholds})")
    if r3["verdict"] not in O.DECISIVE:
        rc = 1

    # ---------------- F6-1 and F6-4: the guardrail hop --------------------
    agree = (cw_in_band is not None and span_in_band is not None and
             cw_in_band == span_in_band)
    for case in ("F6-1", "F6-4"):
        pay: dict[str, Any] = {
            **payload_common,
            "instrument": (f"primary: {AUTHZ_SPAN}.durationNano in the {ARM_GUARDRAIL} arm "
                           f"minus the {ARM_CEDAR} arm's median, ms. cross-instrument check: "
                           f"CloudWatch {NS}/GuardrailLatency percentiles over the same window"),
            "series": "guardrail_hop_ms = authz_ms(guardrail) - p50(authz_ms(cedar_only))",
            "baseline_subtracted": {
                "p50_ms": None if baseline_p50 is None else round(baseline_p50, 3),
                "ci_p50": (str(S.quantile_ci(cedar_ms, 0.50, level=1 - alpha))
                           if cedar_ms else ""),
                "why_a_constant": ("p(X - c) = p(X) - c, so subtracting a constant is exact on "
                                   "order statistics. What it does not do is propagate c's own "
                                   "uncertainty, which is why the interval is recorded here"),
                "negatives_kept": sum(1 for v in hop_ms if v < 0),
                "why_negatives_kept": ("a guardrail-arm request faster than the median "
                                       "baseline request is a real observation; dropping the "
                                       "left tail would raise every quantile"),
            },
            "guardrail_hop_ms": _describe(hop_ms, alpha=alpha, allow_p99=True),
            "cross_instrument": {
                "documented_instrument": ("Gateway Latency + GuardrailLatency" if case == "F6-1"
                                          else "GuardrailLatency (ToolName dimension)"),
                "cloudwatch_p50": gl.get("p50"), "cloudwatch_p90": gl.get("p90"),
                "cloudwatch_p99": gl.get("p99"), "cloudwatch_min": gl.get("min"),
                "cloudwatch_max": gl.get("max"),
                "cloudwatch_sample_count": gl.get("sample_count"),
                "cloudwatch_in_band": cw_in_band,
                "span_shift_in_band": span_in_band,
                "agree": agree,
                "pre_committed": ("declared before any number was seen: if the two instruments "
                                  "disagree about whether the distribution lies inside the "
                                  "band, the verdict is INCONCLUSIVE"),
            },
            "tool_name_dimension_claim": gl.get("tool_name_dimension_claim"),
            "what_true_does_not_prove": (
                "the two §6.1 rows this reading covers are not separable in this service (see "
                "hop_conflation); a TRUE would be a statement about an action-scoped gateway "
                "guardrail evaluation and not about an input-side hop distinct from it"),
        }
        pay["guards"] = {**guards, GUARD_AGREE: bool(agree)}
        pay["guard_detail"] = {**guard_detail, GUARD_AGREE: pay["cross_instrument"]}
        pay["guard_names"] = [*GUARDS, GUARD_AGREE]
        bad = [g for g, ok in pay["guards"].items() if not ok]
        if bad:
            rec = O.not_measured(case, f"guard(s) {', '.join(bad)} did not hold, so the "
                                       f"guardrail hop measured here is not the hop the row "
                                       f"claims a band for", guards=pay["guards"])
        else:
            rec = O.evaluate(O.Observation(case_id=case, n_attempted=cp_g.n_done,
                                           n_usable=len(hop_ms), latencies_ms=hop_ms))
        P.emit(case, rec, pay, store)
        print(f"  {case}: {rec['verdict']}  hop p50={pay['guardrail_hop_ms'].get('p50')} "
              f"p99={pay['guardrail_hop_ms'].get('p99')}  "
              f"cw p50={gl.get('p50')} p99={gl.get('p99')}  "
              f"(band {O.BINDINGS[case].thresholds})")
        if rec["verdict"] not in O.DECISIVE:
            rc = 1

    # ---------------- F6-9: fail fast at the outermost layer --------------
    b_ms = [r["client_ms"] for r in blocked]
    p_ms = [r["client_ms"] for r in passed]
    k = min(len(b_ms), len(p_ms))
    shift_ci = None
    hl = None
    wilcoxon = None
    if k >= 20:
        # Paired by rank within each half: the halves were interleaved, so the i-th blocked and
        # i-th passed trial are adjacent in time and share the same conditions.
        a, b = p_ms[:k], b_ms[:k]
        shift_ci = S.paired_bootstrap_diff_ci(a, b, level=1 - alpha)
        hl = S.hodges_lehmann(a, b)
        wilcoxon = S.wilcoxon_signed_rank(a, b)
    # The sealed kind unpacks `obs.shift_ci` as a two-tuple, so the CI's bounds are handed over
    # as one — `S.CI` is a frozen dataclass and is not iterable.
    shift_bounds = None if shift_ci is None else (shift_ci.lo, shift_ci.hi)
    excludes_zero = bool(shift_bounds and (shift_bounds[0] > 0 or shift_bounds[1] < 0))
    direction_ok = bool(hl is not None and hl > 0)

    p9: dict[str, Any] = {
        **payload_common,
        "instrument": ("client-side round-trip latency of a tools/call, blocked vs passed, "
                       "within the guardrail arm. shift = passed - blocked"),
        "n_blocked": len(b_ms), "n_passed": len(p_ms), "n_paired": k,
        "blocked_ms": _describe(b_ms, alpha=alpha, allow_p99=True),
        "passed_ms": _describe(p_ms, alpha=alpha, allow_p99=True),
        "shift": {
            "definition": "passed - blocked, so a POSITIVE shift means blocking is cheaper",
            "hodges_lehmann_ms": None if hl is None else round(hl, 3),
            "ci": None if shift_ci is None else str(shift_ci),
            "ci_bounds": shift_bounds,
            "excludes_zero": excludes_zero,
            "wilcoxon": None if wilcoxon is None else str(wilcoxon),
            "direction_matches_oracle_text": direction_ok,
            "why_direction_is_checked_separately": (
                "SHIFT_EXCLUDES_ZERO is symmetric and returns TRUE for an interval excluding 0 "
                "in either direction. The claim is not symmetric — it says early blocking SAVES "
                "work — so a reliably slower blocked path must not be published as support for "
                "it. This can only turn a TRUE into a FALSE"),
        },
        "magnitude_not_scored": {
            "claim": "up to 100% of downstream hops (and avoids model-inference charges)",
            "why": ("this gateway's downstream is one Lambda echo target, not Hops #2-6 with a "
                    "model in them, so the fraction of downstream work avoided here is a "
                    "property of our testbed. The DIRECTION is not, and the direction is what "
                    "the sealed kind encodes"),
        },
        "what_true_does_not_prove": (
            "that the saving is proportional to the downstream that a production pipeline "
            "would have skipped; and blocking here is a guardrail forbid at the gateway, which "
            "is the only gateway-side block this service evaluates"),
    }
    p9["guards"] = {**guards, GUARD_BOTH_HALVES: len(b_ms) >= 20 and len(p_ms) >= 20}
    p9["guard_detail"] = {**guard_detail, GUARD_BOTH_HALVES: {
        "test": "at least 20 blocked and 20 passed trials, so a shift has two halves to compare",
        "n_blocked": len(b_ms), "n_passed": len(p_ms),
        "why": ("if the HATE corpus did not trip the guardrail at threshold 0.2, every trial "
                "would be a pass and the 'shift' would be a comparison of a set with itself")}}
    p9["guard_names"] = [*GUARDS, GUARD_BOTH_HALVES]
    bad9 = [g for g, ok in p9["guards"].items() if not ok]
    if bad9:
        r9 = O.not_measured("F6-9", f"guard(s) {', '.join(bad9)} did not hold, so a shift "
                                    f"measured here is not the effect the row claims",
                            guards=p9["guards"])
    elif shift_bounds is None:
        r9 = O.not_measured("F6-9", f"only {k} pairs were usable, below the 20 a paired "
                                    f"bootstrap is reported from here",
                            guards=p9["guards"], n_paired=k)
    else:
        r9 = O.evaluate(O.Observation(case_id="F6-9", n_attempted=k, n_usable=k,
                                      shift_ci=shift_bounds))
        if r9["verdict"] == O.TRUE and not direction_ok:
            r9["verdict"] = O.FALSE
            r9.setdefault("notes", []).append(
                "the paired shift's CI excludes 0, but its sign is negative: blocked requests "
                "were SLOWER than passed ones, which refutes 'fail fast at the outermost "
                "layer' rather than supporting it")
            p9["oracle_text_direction_condition"] = {
                "applied": True, "direction": "can only turn TRUE into FALSE"}
    P.emit("F6-9", r9, p9, store)
    print(f"  F6-9: {r9['verdict']}  blocked p50={p9['blocked_ms'].get('p50')} "
          f"passed p50={p9['passed_ms'].get('p50')}  shift={p9['shift']['hodges_lehmann_ms']} "
          f"ci={p9['shift']['ci']}")
    if r9["verdict"] not in O.DECISIVE:
        rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
