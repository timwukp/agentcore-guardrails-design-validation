#!/usr/bin/env python3
"""F3-10: can §7.1's threshold-tuning workflow actually be executed?

    python3 f3_efficacy/08_score_label_join.py --dry-run
    python3 f3_efficacy/08_score_label_join.py --n 6        # smoke
    python3 f3_efficacy/08_score_label_join.py             # the derived n=60 golden set

THE CLAIM, AND THE ONE SENTENCE THAT DECIDES IT
-----------------------------------------------
§7.1 gives a four-step calibration loop, and the sealed triage assigns six of its units to
this case. The two that carry the measurement:

    "1. Engine = LOG_ONLY (nothing blocked, scores logged)"
    "3. Build confusion matrix from logged ConfidenceScores; compare candidate thresholds"

The sealed oracle is narrower than the prose, and the narrowing is the whole design:

    TRUE if a per-request score<->label join is recoverable from CloudWatch metrics alone;
    FALSE if 1-minute aggregation destroys the linkage, in which case a reader following
    7.1 cannot compute precision at all

So the SCORED surface is CloudWatch metrics. Application logs and spans are read too, and
recorded, and they cannot move the verdict — they are the amendment material for "is there
any surface on which the workflow could be rewritten to work". Mixing them into the verdict
would answer a question the seal does not ask, and the seal was written before the data.

WHAT A CONFUSION MATRIX NEEDS, STATED BEFORE THE MEASUREMENT
-----------------------------------------------------------
A confusion matrix over candidate thresholds needs, for each request, TWO things:

  (a) a NUMERIC SCORE. Without a number there is no threshold to sweep.
  (b) an IDENTIFIER tying that number to a request whose ground-truth label we know.
      Without it the numbers cannot be sorted into TP/FP/TN/FN.

Both are necessary. Either one missing makes the workflow unexecutable, so this script
measures both halves separately and reports which one failed. That distinction is not
cosmetic: the two failures have different characters, and `feedback_constraints_are_choices`
says to label them.

  (a) is ABSOLUTE. A metric that does not exist cannot be made to exist by sending traffic
      differently. If no metric in the namespace carries a confidence score, no request rate,
      no window and no dimension filter recovers one.
  (b) is CONDITIONAL on request rate. CloudWatch aggregates per period; a reader who sent one
      request per minute and never retried would have SampleCount == 1 in every bucket and
      could attribute it. That is not what §7.1 describes — it says "a golden test set or real
      production traffic" — but it is a real escape hatch and is recorded as one rather than
      argued away.

WHY THE MODE HAS TO BE DRIVEN
-----------------------------
The claim is about what LOG_ONLY logs. Reading ENFORCE-mode telemetry and generalising would
be assuming the answer: the whole point of step 1 is that LOG_ONLY is the mode in which the
service is supposed to emit would-have-blocked information, and the namespace does carry
three metrics that exist only for that comparison (`LogOnlyMatches`, `LogOnlyDecisionFlips`,
`PolicyMismatch` — F7-1's inventory). If a score is published anywhere, that mode is where.

The mode is driven with F4's `_set_engine_mode`, IMPORTED rather than re-implemented.
`UpdateGateway` is a REPLACE, so a member the live gateway carries and the caller omits is a
member reset to its default; `exceptionLevel` is DEBUG on this testbed and resetting it would
change the body of every error message every later phase reads. F4 already derives the
passthrough member list from the loaded SDK model and fails FATALLY before any mutation if
that model grew a member it does not re-send. A second copy of that list here would be a
second answer to "which members must be re-sent", and the wrong one would silently win.

THE GOLDEN SET, AND WHY IT IS DELIBERATELY FAST
----------------------------------------------
n = 60: 30 HATE items and 30 benign items, interleaved, sent serially with no added delay.
The label is the ground truth a confusion matrix would be built against — HATE = a request
the guardrail should score high and ENFORCE would deny, benign = one it should not.

The rate is not incidental. Sending them fast puts SEVERAL differently-labelled requests in
one 60-second CloudWatch bucket, which is precisely the condition half (b) is about: a bucket
whose SampleCount is 2 or more and whose contributing requests do not share a label cannot be
attributed to either. Slowing the traffic down to one request per minute would make (b) look
recoverable and would be measuring a rate no reader following §7.1 would use.

n is NOT a pre-registered cell. `oracle.BINDINGS["F3-10"].cell` is None, so `planned_n` is
None and this case has no sealed sample size. 60 is derived here, before the run, and the
derivation is recorded in the payload as `n_derivation`: a single differently-labelled pair in
one bucket is enough to refute (b), so any n >= 2 would do for the refutation; 60 is chosen so
that the enumeration of half (a) covers every metric the namespace publishes for this gateway
with enough samples that an absent score cannot be blamed on an idle window, and so that the
LOG_ONLY-specific metrics have something to count.

A guardrail-bearing policy is created for the window. Without one there is nothing to score,
and "no ConfidenceScore metric" would be a statement about our configuration instead of about
the service. It is scoped to one tool action for the reason F4 measured: the service refuses to
evaluate an unscoped gateway guardrail at all.

WHAT THIS SCRIPT CANNOT DECIDE
-----------------------------
That a reader could recover the join by some means outside AWS-native telemetry — proxying
every request through their own middleware, calling ApplyGuardrail directly and keeping the
scores themselves — is true, is not what §7.1 says, and is not tested. It belongs in the
amendment, and `what_true_does_not_prove` says so in the payload rather than in a comment.

GUARDS, all INCONCLUSIVE-on-failure, because each one would make the reading mean something
else if it did not hold:
  log_only_mode_verified      the window really was LOG_ONLY, from two independent reads
  golden_set_landed           every request reached the gateway and none failed
  nothing_blocked_in_log_only no request was denied, which is what LOG_ONLY means (F4-2/F4-3
                              measured this at n=120); a block would mean the mode never took
                              and every reading here would be ENFORCE telemetry wearing a
                              LOG_ONLY label
  labels_share_a_bucket       at least one 60s bucket holds both labels (half (b)'s premise)
  metrics_enumerated          ListMetrics was paginated to exhaustion, not truncated
  publish_lag_respected       the harvest waited more than F7-6's measured p90 lag
  mode_restored               ENFORCE is back, verified by re-running the Phase-2 assertion
  probe_policy_removed        the guardrail policy this script created is gone
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R                                                    # noqa: E402
import awsclients as A                                              # noqa: E402
import cedar                                                        # noqa: E402
import mcp as M                                                     # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402
import testbed as T                                                 # noqa: E402
from checkpoint import Checkpoint                                    # noqa: E402
from evidence import EvidenceStore, capture                          # noqa: E402

CASE = "F3-10"
CASES = (CASE,)
FAMILY = "f3_efficacy"

# Every by-path loader key is a module-level CONSTANT and unique across the repo:
# `lib/tests/test_module_name_collisions.py` reads these statically, and a name built from a
# parameter is invisible to it. Two scripts registering one key would hand the loser the
# winner's module object under the same name.
PE_MODULE_NAME = "grx_f3_10_infra_03_policy_engine"
VERIFY_MODULE_NAME = "grx_f3_10_infra_06_verify"
TRACES_MODULE_NAME = "grx_f3_10_infra_07_traces"
F4_MODULE_NAME = "grx_f3_10_f4_truth_table"


def _register(spec):
    """Register and execute a by-path module. The NAME is passed at the call site, not here.

    The obvious shape — `_load(NAME, rel)` doing the `spec_from_file_location` inside — makes the
    sys.modules key invisible to `lib/tests/test_module_name_collisions.py`, which resolves the
    FIRST ARGUMENT of that call statically and cannot follow a parameter. Building the spec at
    the call site keeps the guard able to see every key, which is the only reason the constants
    above are constants.
    """
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_pe = _register(importlib.util.spec_from_file_location(
    PE_MODULE_NAME, ROOT / "infra" / "03_policy_engine.py"))
_vf = _register(importlib.util.spec_from_file_location(
    VERIFY_MODULE_NAME, ROOT / "infra" / "06_verify.py"))
_tr = _register(importlib.util.spec_from_file_location(
    TRACES_MODULE_NAME, ROOT / "infra" / "07_traces.py"))
# F4 owns the engine axis. Imported, not restated — see the docstring.
_f4 = _register(importlib.util.spec_from_file_location(
    F4_MODULE_NAME, ROOT / "f4_modes" / "01_truth_table.py"))

wait_status = _pe.wait_status
PE_TERMINAL_OK = _pe.TERMINAL_OK
set_engine_mode = _f4._set_engine_mode
check_update_gateway_shape = _f4._check_update_gateway_shape
ENGINE_ENFORCE = _f4.ENGINE_ENFORCE
ENGINE_LOG_ONLY = _f4.ENGINE_LOG_ONLY
SETTLE_DWELL_S = _f4.SETTLE_DWELL_S

NS = "AWS/Bedrock-AgentCore"
TOOL = "echo"
CELL_KEY = "log_only_golden_set"      # a checkpoint file key, NOT a pre-registered cell

N_DERIVED = 60                        # 30 HATE + 30 benign; see `n_derivation` in the payload
GUARDRAIL_FUNCTION = "ContentFilter"
GUARDRAIL_CATEGORY = "HATE"
GUARDRAIL_PATH = "context.input.text"
GUARDRAIL_THRESHOLD = "0.2"
VALIDATION_MODE = "IGNORE_ALL_FINDINGS"
POLICY_ENFORCE = "ACTIVE"             # EnforcementMode: an ACTIVE policy enforces
POLICY_SETTLE_S = 20.0
DELETE_ATTEMPTS = 5
DELETE_SLEEP_S = 3.0

# The harvest waits this long after the last request before reading metrics. F7-6 MEASURED the
# publish lag on this gateway at p90 = 11.485 s (n=30, serial, dimensioned to our gateway), so
# this is ~10x the measured p90 rather than a guess. It is not conditioned on the data: a settle
# loop that polled until a score metric appeared could never observe its absence.
HARVEST_SETTLE_S = 120.0
F7_6_RESULT = ROOT / "results" / "phase1" / "F7-6.json"
PERIOD_S = 60                         # the aggregation §7.1's workflow would be reading through


def _f7_6_lag_p90_s() -> dict[str, Any]:
    """Read F7-6's measured lag from its own result file rather than restating the number.

    A settle constant justified by "F7-6 measured 11.485 s" in a comment is a number nobody
    checks: if F7-6 were re-run and the lag moved, the prose would go on claiming the old value
    while `HARVEST_SETTLE_S` went on being whatever it was. So the value is loaded, compared,
    and the comparison is recorded in the payload — and a missing or unreadable F7-6 says so
    instead of falling back to a remembered figure.
    """
    out: dict[str, Any] = {"source": str(F7_6_RESULT.relative_to(ROOT)), "p90_s": None}
    try:
        body = json.loads(F7_6_RESULT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["reading"] = ("F7-6's result is unreadable, so the settle below is an unbacked "
                          "constant; it is still 120 s, and this note is what makes that visible")
        return out
    out["p90_s"] = ((body.get("record") or {}).get("evidence") or {}).get("lag_p90_s")
    out["f7_6_verdict"] = body.get("verdict")
    if isinstance(out["p90_s"], (int, float)):
        out["settle_over_p90_ratio"] = round(HARVEST_SETTLE_S / float(out["p90_s"]), 2)
        out["settle_exceeds_p90"] = HARVEST_SETTLE_S > float(out["p90_s"])
    return out

# Half (a)'s criterion, fixed BEFORE the enumeration. A name test alone would miss a score
# published under a word neither of these covers, so every numeric-valued field found on every
# surface is also recorded in full (`numeric_keys_seen`) and printed, which is what makes the
# absence checkable by a reader instead of trusted.
SCORE_NAME_RE = re.compile(r"(confidence|score)", re.IGNORECASE)

SPAN_LOOKBACK_MIN = 60
SPAN_QUERY_LIMIT = 200
LOG_EVENT_LIMIT = 500

HATE_CORPUS = ROOT / "corpora" / "content_filter" / "hate.jsonl"
BENIGN_CORPUS = ROOT / "corpora" / "benign" / "benign.jsonl"
CORPUS_SEED = 20260809

GUARDS = ("log_only_mode_verified", "golden_set_landed", "nothing_blocked_in_log_only",
          "labels_share_a_bucket", "metrics_enumerated", "publish_lag_respected",
          "mode_restored", "probe_policy_removed")


class ConfigError(RuntimeError):
    """The testbed is not in a state in which this window measures §7.1's workflow."""


# ---------------------------------------------------------------------------
# the golden set
# ---------------------------------------------------------------------------

def _corpus(path: Path, n: int) -> list[dict[str, str]]:
    return R.load_corpus(path, n=n, seed=CORPUS_SEED)


def _golden_set(n: int) -> list[dict[str, Any]]:
    """`n` items, alternating HATE and benign, each carrying the label a matrix would use."""
    half = n // 2
    hate = _corpus(HATE_CORPUS, half)
    benign = _corpus(BENIGN_CORPUS, n - half)
    out: list[dict[str, Any]] = []
    for i in range(n):
        src = benign[i // 2] if i % 2 == 0 else hate[i // 2]
        out.append({"id": src["id"], "text": src["text"],
                    # `truth` is the ground truth a confusion matrix is built against, and it is
                    # the CORPUS's label, not anything the service said. Deriving it from a
                    # service response would make the matrix a comparison of the service with
                    # itself.
                    "truth": "positive" if (i % 2 == 1) else "negative",
                    "corpus_label": src["label"]})
    return out[:n]


def _call(client, tool_name: str, item: dict[str, Any]) -> dict[str, Any]:
    """One `tools/call` in the LOG_ONLY window. Transport errors are recorded, not raised.

    The wall-clock stamps are UTC seconds and they are what pins each request to a CloudWatch
    minute bucket. `t_send` is taken immediately before the POST: a stamp taken after would
    attribute a request to the bucket its RESPONSE landed in, which is the wrong bucket
    whenever a call straddles a minute edge, and straddling is exactly what a fast arm does.
    """
    t_send = time.time()
    try:
        d = client.call_tool(tool_name, {"text": item["text"]})
    except M.McpTransportError as exc:
        return {"outcome": "transport_error", "error": str(exc), "t_send": t_send,
                "t_done": time.time(), "corpus_id": item["id"], "truth": item["truth"],
                "corpus_label": item["corpus_label"]}
    return {
        "outcome": d.outcome,
        "request_id": d.request_id,
        "denied": bool(d.denied),
        "default_deny": bool(d.default_deny),
        "t_send": t_send,
        "t_done": time.time(),
        "bucket_s": int(t_send // PERIOD_S) * PERIOD_S,
        "corpus_id": item["id"],
        "truth": item["truth"],
        "corpus_label": item["corpus_label"],
        "text_len": len(item["text"]),
    }


def _run_golden(client, *, items: list[dict[str, Any]], is_smoke: bool) -> Checkpoint:
    """Send the golden set, resumably. No delay between calls — the rate is the instrument."""
    cp = Checkpoint(case_id=CASE, cell=CELL_KEY).load()
    cp.set_meta(is_smoke=is_smoke, n_planned=len(items), corpus_seed=CORPUS_SEED, tool=TOOL,
                engine_mode=ENGINE_LOG_ONLY, period_s=PERIOD_S,
                why_no_inter_call_delay=("the aggregation collision IS half (b) of the "
                                         "measurement; spacing the calls one per minute would "
                                         "measure a request rate no reader of 7.1 would use"))
    for i, item in enumerate(items):
        tid = f"t{i:04d}"
        if cp.is_done(tid):
            continue
        client.refresh_if_stale()
        cp.run_trial(tid, lambda it=item: _call(client, TOOL, it))
    return cp


# ---------------------------------------------------------------------------
# the probe policy: something for a score to be a score OF
# ---------------------------------------------------------------------------

def _create_probe(ac, store, state: T.State, *, engine_id: str, run_id: str,
                  gateway_arn: str, action_id: str) -> str:
    """A guardrail-bearing policy, ACTIVE, scoped to one action. Registered before any poll."""
    stmt = cedar.statement(
        "forbid", resource=cedar.gateway_resource(gateway_arn),
        action=f'action == {cedar.ENTITY_ACTION}::"{action_id}"',
        when_guardrails=cedar.guardrail_condition(
            GUARDRAIL_FUNCTION, [GUARDRAIL_CATEGORY], [GUARDRAIL_PATH],
            threshold=GUARDRAIL_THRESHOLD))
    problems = cedar.check_statement(stmt)
    if problems:
        raise ConfigError(f"the probe statement fails the local lint: {problems}")

    name = f"grx_f3_10_scored_{run_id}"
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac, name=name, policyEngineId=engine_id,
                  # `policy`, not `cedar`: F4-0 measured that `definition.cedar` rejects
                  # `when guardrails` as an unexpected token.
                  definition={"policy": {"statement": stmt}},
                  description="F3-10: a guardrail whose scores 7.1 says are logged",
                  validationMode=VALIDATION_MODE,
                  enforcementMode=POLICY_ENFORCE)
    if not rec.ok:
        raise ConfigError(f"CreatePolicy failed: {rec.error_code}: {rec.error_message}")
    pid = rec.response.get("policyId")
    if not pid:
        raise ConfigError("CreatePolicy returned no policyId")
    state.record(T.Resource(
        kind="policy", logical="f3_10_scored_probe", name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid, "statement": stmt,
             "enforcement_mode_at_create": POLICY_ENFORCE,
             "validation_mode_sent": VALIDATION_MODE},
        arn=rec.response.get("policyArn", ""), delete_priority=40,
        notes=("F3-10 scored probe. A policy takes no tags, so this ledger entry and this "
               "script's finally are the only channels that can find it")))
    live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
    if live.get("status") not in PE_TERMINAL_OK:
        raise ConfigError(
            f"the probe policy settled {live.get('status')} "
            f"(reasons={live.get('statusReasons')}); with no live guardrail there is nothing for "
            f"a ConfidenceScore to be a score of, and its absence would be a fact about this "
            f"configuration rather than about the service")
    print(f"    probe policy {pid} ACTIVE ({POLICY_ENFORCE})")
    return pid


def _delete_probe(ac, store, state: T.State, *, engine_id: str, policy_id: str) -> dict:
    """Delete the probe. Never raises: this runs in a finally."""
    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac,
                      policyEngineId=engine_id, policyId=policy_id)
        if rec.ok or rec.error_code == "ResourceNotFoundException":
            state.drop("policy", "f3_10_scored_probe")
            print(f"    probe policy deleted (attempt {attempt})")
            return {"deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}")
        if attempt < DELETE_ATTEMPTS:
            time.sleep(DELETE_SLEEP_S)
    print(f"    WARN probe policy NOT deleted: {'; '.join(errors)}", file=sys.stderr)
    return {"deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors}


# ---------------------------------------------------------------------------
# surface 1 (SCORED): CloudWatch metrics alone
# ---------------------------------------------------------------------------

def _enumerate_series(cw, store, *, gateway_id: str) -> dict[str, Any]:
    """Every published series in the namespace, paginated to exhaustion.

    Namespace-wide and then filtered to this gateway, rather than a per-name query: a score
    metric would be a name this script does not know to ask for, so asking by name could only
    ever confirm names already believed in. The truncation guard matters — a NextToken dropped
    on the floor would turn "no score metric exists" into "no score metric in the first page".
    """
    out: dict[str, Any] = {"namespace": NS, "pages": 0, "exhausted": False}
    metrics: list[dict[str, Any]] = []
    token = None
    while True:
        kw: dict[str, Any] = {"Namespace": NS}
        if token:
            kw["NextToken"] = token
        rec = capture(store, "list_metrics", cw, **kw)
        if not rec.ok:
            out["error"] = f"{rec.error_code}: {rec.error_message}"
            return out
        metrics.extend(rec.response.get("Metrics") or [])
        out["pages"] += 1
        token = rec.response.get("NextToken")
        if not token:
            out["exhausted"] = True
            break
    out["n_series_namespace"] = len(metrics)
    out["all_metric_names"] = sorted({m["MetricName"] for m in metrics})
    ours = [m for m in metrics
            if any(gateway_id in d.get("Value", "") for d in (m.get("Dimensions") or []))]
    out["n_series_this_gateway"] = len(ours)
    out["metric_names_this_gateway"] = sorted({m["MetricName"] for m in ours})
    out["series_this_gateway"] = [
        {"name": m["MetricName"],
         "dimensions": [{"Name": d["Name"], "Value": d["Value"]}
                        for d in (m.get("Dimensions") or [])]}
        for m in ours]
    out["dimension_names_this_gateway"] = sorted(
        {d["Name"] for m in ours for d in (m.get("Dimensions") or [])})
    return out


def _score_half_from_metrics(inv: dict[str, Any]) -> dict[str, Any]:
    """Half (a): does ANY metric in the namespace carry a confidence score?

    Two readings, both reported. The namespace-wide one is the one that matters for an
    ABSOLUTE claim: a metric absent from the whole namespace cannot be produced by any traffic
    pattern. The per-gateway one is narrower and could in principle be a fact about our
    configuration, which is why the probe policy exists.
    """
    all_names = inv.get("all_metric_names") or []
    ours = inv.get("metric_names_this_gateway") or []
    ns_hits = sorted(n for n in all_names if SCORE_NAME_RE.search(n))
    our_hits = sorted(n for n in ours if SCORE_NAME_RE.search(n))
    return {
        "criterion": r"metric name matches (?i)(confidence|score)",
        "criterion_fixed_before_enumeration": True,
        "namespace_matches": ns_hits,
        "this_gateway_matches": our_hits,
        "score_metric_exists": bool(ns_hits),
        "documented_names_checked": {
            # The two names §7.1 and §6.4 use by hand, checked explicitly so the absence is
            # named rather than left to a reader's reading of a 31-entry list.
            "ConfidenceScore": "ConfidenceScore" in all_names,
            "ConfidenceThreshold": "ConfidenceThreshold" in all_names,
        },
        "n_metric_names_in_namespace": len(all_names),
        "failure_character": "absolute" if not ns_hits else "",
        "why_absolute": ("a metric that the namespace does not publish cannot be produced by "
                         "any request rate, window or dimension filter, so this half does not "
                         "depend on how the golden set was sent"),
    }


def _identity_half_from_metrics(cw, store, *, inv: dict[str, Any], rows: list[dict[str, Any]],
                                t0: float, t1: float) -> dict[str, Any]:
    """Half (b): does any series reach ONE request per datapoint in a mixed-label bucket?

    Read at Period=60, the grain §7.1's reader would be reading through. For every series this
    gateway publishes, every datapoint in the window is compared against the buckets our own
    requests fell in: a datapoint whose SampleCount exceeds 1 in a bucket holding both labels
    is a number that cannot be attributed to either label, and that is the linkage the oracle
    asks about.

    A series with SampleCount == 1 everywhere does NOT by itself make the join recoverable —
    it would still need half (a) — but it is recorded as `any_series_per_request` because it is
    the one way the aggregation argument could come out the other way, and pre-declaring it is
    what stops this instrument from being unfalsifiable.
    """
    buckets: dict[int, dict[str, int]] = {}
    for r in rows:
        b = r.get("bucket_s")
        if b is None:
            continue
        cell = buckets.setdefault(int(b), {"positive": 0, "negative": 0})
        cell[r["truth"]] = cell.get(r["truth"], 0) + 1
    mixed = sorted(b for b, c in buckets.items() if c["positive"] > 0 and c["negative"] > 0)
    multi = sorted(b for b, c in buckets.items() if c["positive"] + c["negative"] > 1)

    start = datetime.fromtimestamp(t0 - PERIOD_S, timezone.utc)
    end = datetime.fromtimestamp(t1 + HARVEST_SETTLE_S, timezone.utc)
    per_series: list[dict[str, Any]] = []
    for s in (inv.get("series_this_gateway") or []):
        rec = capture(store, "get_metric_statistics", cw,
                      Namespace=NS, MetricName=s["name"], Dimensions=s["dimensions"],
                      StartTime=start, EndTime=end, Period=PERIOD_S,
                      Statistics=["SampleCount", "Sum", "Average", "Minimum", "Maximum"])
        if not rec.ok:
            per_series.append({"name": s["name"], "dimensions": s["dimensions"],
                               "error": rec.error_code})
            continue
        dps = rec.response.get("Datapoints") or []
        entry: dict[str, Any] = {
            "name": s["name"],
            "dimensions": s["dimensions"],
            "unit": (dps[0].get("Unit") if dps else None),
            "n_datapoints": len(dps),
            "datapoints": [
                {"t": dp["Timestamp"].isoformat(),
                 "bucket_s": int(dp["Timestamp"].timestamp()),
                 "sample_count": dp.get("SampleCount"),
                 "sum": dp.get("Sum"), "min": dp.get("Minimum"), "max": dp.get("Maximum")}
                for dp in sorted(dps, key=lambda d: d["Timestamp"])],
        }
        in_mixed = [d for d in entry["datapoints"] if d["bucket_s"] in set(mixed)]
        entry["datapoints_in_mixed_label_buckets"] = len(in_mixed)
        entry["max_sample_count_in_mixed_bucket"] = (
            max((d["sample_count"] or 0) for d in in_mixed) if in_mixed else None)
        entry["all_datapoints_are_single_request"] = (
            bool(entry["datapoints"])
            and all((d["sample_count"] or 0) <= 1 for d in entry["datapoints"]))
        entry["carries_a_request_identifier"] = False   # see `why_no_identifier_dimension`
        per_series.append(entry)

    collided = [e for e in per_series
                if (e.get("max_sample_count_in_mixed_bucket") or 0) > 1]
    per_request = [e for e in per_series if e.get("all_datapoints_are_single_request")]
    return {
        "period_s": PERIOD_S,
        "buckets_covered": {str(b): c for b, c in sorted(buckets.items())},
        "n_buckets": len(buckets),
        "mixed_label_buckets": [str(b) for b in mixed],
        "multi_request_buckets": [str(b) for b in multi],
        "n_series_read": len(per_series),
        "per_series": per_series,
        "n_series_colliding_in_a_mixed_bucket": len(collided),
        "series_colliding": sorted({e["name"] for e in collided}),
        "any_series_per_request": [e["name"] for e in per_request],
        "dimension_names_available": inv.get("dimension_names_this_gateway") or [],
        "why_no_identifier_dimension": (
            "a per-request join needs a dimension whose value distinguishes one request from "
            "another. The dimensions this gateway publishes are configuration-scoped "
            "(OperationName, TargetResource, PolicyEngine, Policy, ToolName, Mode) — every "
            "request in the golden set shares every one of their values, so no dimension "
            "filter can separate the two labels no matter how the metric is queried"),
        "failure_character": "conditional_on_request_rate" if collided else "",
        "why_conditional": (
            "CloudWatch aggregates per period, so a reader who sent exactly one request per "
            "minute would see SampleCount == 1 and could attribute it by timestamp. That is "
            "not the traffic 7.1 describes ('a golden test set or real production traffic'), "
            "but it is a real escape hatch and is recorded rather than argued away"),
    }


def _log_only_metrics(cw, store, *, inv: dict[str, Any], t0: float, t1: float) -> dict[str, Any]:
    """§7.1's decision diamond reads `LogOnlyDecisionFlips`. Did it publish at all?

    Recorded, not scored: the oracle is about the score<->label join, and a flip counter is a
    per-period count with no score in it either way. It is here because "LogOnlyDecisionFlips
    sustained at zero?" is a sealed unit of this case's own claim group, and a metric that
    never publishes makes that diamond unreadable — which is amendment material.
    """
    wanted = ("LogOnlyMatches", "LogOnlyDecisionFlips", "PolicyMismatch",
              "TotalMismatchedPolicies", "MismatchErrors", "AllowDecisions", "DenyDecisions")
    by_name: dict[str, list[dict[str, Any]]] = {}
    for s in (inv.get("series_this_gateway") or []):
        if s["name"] in wanted:
            by_name.setdefault(s["name"], []).append(s)
    start = datetime.fromtimestamp(t0 - PERIOD_S, timezone.utc)
    end = datetime.fromtimestamp(t1 + HARVEST_SETTLE_S, timezone.utc)
    out: dict[str, Any] = {"read_at_period_s": PERIOD_S, "per_metric": {}}
    for name in wanted:
        series = by_name.get(name) or []
        if not series:
            out["per_metric"][name] = {"published_for_this_gateway": False, "sum": None,
                                       "why": "absent from ListMetrics for this gateway"}
            continue
        total, n_dp, modes = 0.0, 0, set()
        for s in series:
            for d in (s["dimensions"] or []):
                if d["Name"] == "Mode":
                    modes.add(d["Value"])
            rec = capture(store, "get_metric_statistics", cw,
                          Namespace=NS, MetricName=name, Dimensions=s["dimensions"],
                          StartTime=start, EndTime=end, Period=PERIOD_S,
                          Statistics=["Sum", "SampleCount"])
            if not rec.ok:
                continue
            for dp in (rec.response.get("Datapoints") or []):
                total += float(dp.get("Sum") or 0.0)
                n_dp += 1
        out["per_metric"][name] = {"published_for_this_gateway": True, "n_series": len(series),
                                   "n_datapoints_in_window": n_dp, "sum": total,
                                   "mode_dimension_values": sorted(modes)}
    return out


# ---------------------------------------------------------------------------
# surfaces 2 and 3 (RECORDED, NOT SCORED): application logs and spans
# ---------------------------------------------------------------------------

def _numeric_keys(obj: Any, prefix: str = "", acc: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every numeric-valued key path in a decoded record, with one example value each.

    This is the check that keeps half (a) from being a word game. A score published as
    `severity` or `sensitivity` would not match the name pattern, so the full set of numeric
    fields any surface carries is enumerated and printed; a reader can then see for themselves
    that nothing score-shaped was passed over, instead of trusting a regex.
    """
    acc = {} if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            _numeric_keys(v, f"{prefix}.{k}" if prefix else str(k), acc)
    elif isinstance(obj, list):
        for v in obj[:5]:
            _numeric_keys(v, f"{prefix}[]", acc)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)) and prefix:
        acc.setdefault(prefix, obj)
    return acc


def _app_logs(logs, store, *, gateway_id: str, t0: float, t1: float,
              trial_ids: set[str]) -> dict[str, Any]:
    """The gateway's APPLICATION_LOGS group over the window. 'Logged' is §7.1's own word.

    `storedBytes` is deliberately NOT the instrument: it is an approximate, lagging field, and
    reading zero from it would be a claim about CloudWatch's bookkeeping rather than about
    whether anything was written. The events are fetched.
    """
    name = _tr.log_group_name(gateway_id)
    out: dict[str, Any] = {"log_group": name, "scored": False,
                           "why_not_scored": ("the sealed oracle says 'from CloudWatch metrics "
                                              "alone'; this surface is amendment material")}
    grec = capture(store, "describe_log_groups", logs, logGroupNamePrefix=name)
    if not grec.ok:
        out["error"] = f"{grec.error_code}: {grec.error_message}"
        return out
    groups = [g for g in (grec.response.get("logGroups") or [])
              if g.get("logGroupName") == name]
    out["exists"] = bool(groups)
    if not groups:
        out["reading"] = "the vended application-log group for this gateway does not exist"
        return out
    out["stored_bytes_reported"] = groups[0].get("storedBytes")
    out["retention_days"] = groups[0].get("retentionInDays")

    frec = capture(store, "filter_log_events", logs, logGroupName=name,
                   startTime=int((t0 - PERIOD_S) * 1000),
                   endTime=int((t1 + HARVEST_SETTLE_S) * 1000),
                   limit=LOG_EVENT_LIMIT)
    if not frec.ok:
        out["error"] = f"{frec.error_code}: {frec.error_message}"
        return out
    events = frec.response.get("events") or []
    out["n_events_in_window"] = len(events)
    numeric: dict[str, Any] = {}
    id_hits, score_hits = 0, 0
    samples: list[str] = []
    for ev in events:
        msg = ev.get("message") or ""
        if len(samples) < 3:
            samples.append(msg[:400])
        try:
            body = json.loads(msg)
        except (ValueError, TypeError):
            body = {"_unparsed": msg}
        _numeric_keys(body, acc=numeric)
        if any(t in msg for t in trial_ids):
            id_hits += 1
        if SCORE_NAME_RE.search(msg):
            score_hits += 1
    out.update({
        "numeric_keys_seen": dict(sorted(numeric.items())),
        "n_events_naming_one_of_our_corpus_ids": id_hits,
        "n_events_matching_the_score_pattern": score_hits,
        "sample_messages": samples,
        "score_present": score_hits > 0,
        "identity_present": id_hits > 0,
    })
    return out


def _spans(logs, store, *, gateway_arn: str, request_ids: list[str]) -> dict[str, Any]:
    """AuthorizeAction spans over the window: do they carry a score, and our request ids?

    Recorded, not scored, for the same reason as the logs. Spans are the surface most likely
    to restore a per-request join — F6 joins them by request id — so if a score lives anywhere
    reachable, this is where an amendment would have to point.
    """
    out: dict[str, Any] = {"scored": False,
                           "why_not_scored": "the oracle names CloudWatch metrics alone"}
    try:
        rows = _tr.query_spans(logs, gateway_arn, minutes=SPAN_LOOKBACK_MIN,
                               limit=SPAN_QUERY_LIMIT)
    except (RuntimeError, TimeoutError) as exc:
        out["error"] = str(exc)
        return out
    out["n_rows"] = len(rows)
    numeric: dict[str, Any] = {}
    id_hits, score_hits = 0, 0
    want = set(r for r in request_ids if r)
    for row in rows:
        msg = next((f["value"] for f in row if f.get("field") == "@message"), "")
        try:
            body = json.loads(msg)
        except (ValueError, TypeError):
            body = {"_unparsed": msg}
        _numeric_keys(body, acc=numeric)
        if any(rid in msg for rid in want):
            id_hits += 1
        if SCORE_NAME_RE.search(msg):
            score_hits += 1
    out.update({
        "numeric_keys_seen": dict(sorted(numeric.items())),
        "n_spans_naming_one_of_our_request_ids": id_hits,
        "n_spans_matching_the_score_pattern": score_hits,
        "score_present": score_hits > 0,
        "identity_present": id_hits > 0,
        "join_key_available": "request_id" if id_hits else "",
    })
    return out


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def _rows(cp: Checkpoint) -> list[dict[str, Any]]:
    return [v for v in cp.results().values() if v.get("outcome") != "transport_error"]


def _dry_run(n: int) -> int:
    P.dry_run_banner(
        CASE,
        [(CELL_KEY, "one LOG_ONLY window: 30 HATE + 30 benign, interleaved, sent as fast as "
                    "the gateway accepts them", n)],
        operations={"mcp_tools_call": n},
        mutations=3, billable=True,
        extra=[
            "n is NOT sealed: BINDINGS['F3-10'].cell is None so planned_n is None. 60 is "
            "derived in the docstring and recorded as `n_derivation`",
            "3 mutations: engine ENFORCE->LOG_ONLY, create the guardrail probe policy, and "
            "the restore back to ENFORCE. The probe delete and the restore both run in a "
            "finally and the Phase-2 blocking assertion is RE-RUN after",
            f"ancillary, NOT trials: list_metrics x~2 (paginated to exhaustion), "
            f"get_metric_statistics x~40 (one per published series plus the LOG_ONLY set), "
            f"describe_log_groups x1, filter_log_events x1, 1 Logs Insights span query, "
            f"get_gateway x~6, and 1 MCP initialize",
            "SCORED surface: CloudWatch metrics alone, because that is what the sealed oracle "
            "says. Application logs and spans are read and recorded as amendment material and "
            "cannot move the verdict",
            "half (a) score existence is ABSOLUTE (a metric the namespace does not publish "
            "cannot be produced by any traffic); half (b) identity is CONDITIONAL on request "
            "rate, and the escape hatch is recorded",
            f"the harvest waits {HARVEST_SETTLE_S:.0f}s, against F7-6's measured publish-lag "
            f"p90 of {_f7_6_lag_p90_s().get('p90_s')}s read from its own result file "
            f"(ratio {_f7_6_lag_p90_s().get('settle_over_p90_ratio')}x), and the wait is fixed "
            f"rather than polled: a loop that waited until a score appeared could never "
            f"observe its absence",
            f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}",
        ])
    print()
    return 0


def main(argv: list[str] | None = None) -> int:                     # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else N_DERIVED
    is_smoke = args.n is not None

    if args.dry_run:
        return _dry_run(n)

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    cw = fc.client("cloudwatch")
    logs = fc.client("logs")
    ac = fc.client("bedrock-agentcore-control")
    account_id = A.account_id(fc)
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()

    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    if not gw or not tgt:
        raise ConfigError("the main gateway or its target is not in state.json")
    gateway_id = gw.ids["gateway_id"]
    # The ledger masks the account in every ARN, so `gw.arn` cannot reach an API: a masked
    # resource in a Cedar statement is rejected as "AWS Account ID must be exactly 12 digits".
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    engine_id = gw.ids.get("policy_engine_id") or ""
    if not engine_id:
        raise ConfigError("the main gateway has no policy engine; there is no mode to drive")
    action_id = next((a for a in (tgt.ids.get("cedar_action_ids") or [])
                      if a.endswith(f"___{TOOL}")), "")
    if not action_id:
        raise ConfigError(f"no cedar action id ends with ___{TOOL}")

    # F4's fatal preflight, run before any mutation: UpdateGateway is a REPLACE and a member
    # this SDK accepts that the passthrough list does not re-send would be wiped by the mode
    # switch. `exceptionLevel` is DEBUG here and resetting it would change every later error
    # body in this run.
    shape = check_update_gateway_shape(ac)
    if not shape["ok"]:
        raise ConfigError(
            f"UpdateGateway's model does not match the members F4 re-sends "
            f"(unhandled={shape['unhandled']}, absent={shape['absent_from_model']}); a mode "
            f"switch would silently reset a member of the shared gateway")

    start_gw = capture(store, "get_gateway", ac, gatewayIdentifier=gateway_id)
    if not start_gw.ok:
        raise ConfigError(f"GetGateway failed before any mutation: {start_gw.error_code}")
    start_cfg = dict(start_gw.response.get("policyEngineConfiguration") or {})
    start_mode = start_cfg.get("mode", "")
    engine_arn = start_cfg.get("arn", "")
    if not engine_arn:
        raise ConfigError("the gateway has no policy engine attached")
    if start_mode != ENGINE_ENFORCE:
        raise ConfigError(
            f"the gateway is in {start_mode!r}, not {ENGINE_ENFORCE!r}. This script restores "
            f"what it found, but a testbed that did not start in ENFORCE means another script "
            f"is mid-run on the same gateway and both measurements would be of the other's "
            f"configuration")

    alpha = O.alpha_for(CASE)
    items = _golden_set(n)
    trial_ids = {it["id"] for it in items}
    print(f"{CASE} — the §7.1 calibration loop, run_id={run_id}, region={region}")
    print(f"  gateway {gateway_id}  engine {engine_id}  action {action_id}")
    print(f"  golden set n={n} ({sum(1 for i in items if i['truth'] == 'positive')} positive / "
          f"{sum(1 for i in items if i['truth'] == 'negative')} negative)")

    client = M.client_for(gw.ids["gateway_url"], fc, store=store,
                          policy_session_id=M.policy_session_id(run_id, "f310"),
                          session_timeout_s=int(gw.ids.get("session_timeout_s", 900)))
    client.initialize()

    probe_id = ""
    to_log_only: dict[str, Any] = {}
    restore: dict[str, Any] = {}
    probe_removal: dict[str, Any] = {}
    t0 = t1 = 0.0
    cp: Checkpoint | None = None
    try:
        probe_id = _create_probe(ac, store, state, engine_id=engine_id, run_id=run_id,
                                 gateway_arn=gateway_arn, action_id=action_id)
        time.sleep(POLICY_SETTLE_S)

        print(f"  engine {start_mode} -> {ENGINE_LOG_ONLY}")
        to_log_only = set_engine_mode(ac, store, gateway_id=gateway_id,
                                     engine_arn=engine_arn, mode=ENGINE_LOG_ONLY)
        time.sleep(SETTLE_DWELL_S)

        print(f"  [{CELL_KEY}] sending n={n} with no inter-call delay")
        t0 = time.time()
        cp = _run_golden(client, items=items, is_smoke=is_smoke)
        t1 = time.time()
        print(f"    done: {cp.n_done} trials, {cp.n_failed} failures, "
              f"{t1 - t0:.1f}s wall clock")
    finally:
        if probe_id:
            probe_removal = _delete_probe(ac, store, state, engine_id=engine_id,
                                         policy_id=probe_id)
        try:
            restore = set_engine_mode(ac, store, gateway_id=gateway_id,
                                     engine_arn=engine_arn, mode=start_mode)
        except Exception as exc:                                    # noqa: BLE001
            restore = {"verified": False, "error": str(exc)}
            print(f"    WARN engine mode NOT restored: {exc}", file=sys.stderr)
        # PREREGISTRATION's `restore_verification` rule: re-run the BLOCKING assertion, the
        # very functions infra/06_verify.py runs as the Phase-2 gate. A restore is not assumed
        # to have worked because an API call returned 200.
        checks = _vf.Checks()
        try:
            _vf.verify_engine(ac, state, checks)
            _vf.verify_gateways(ac, state, checks)
        except Exception as exc:                                    # noqa: BLE001
            print(f"    WARN the Phase-2 assertion raised: {exc}", file=sys.stderr)
        restore["phase2_assertion"] = {"failures": list(getattr(checks, "failures", []) or []),
                                       "ok": not (getattr(checks, "failures", []) or [])}

    if cp is None:
        raise ConfigError("the golden set never ran; there is nothing to harvest")

    rows = _rows(cp)
    lag = _f7_6_lag_p90_s()
    print(f"  settling {HARVEST_SETTLE_S:.0f}s before the harvest "
          f"(F7-6 p90 lag {lag.get('p90_s')}s)")
    time.sleep(HARVEST_SETTLE_S)

    inv = _enumerate_series(cw, store, gateway_id=gateway_id)
    score_half = _score_half_from_metrics(inv)
    identity_half = _identity_half_from_metrics(cw, store, inv=inv, rows=rows, t0=t0, t1=t1)
    log_only = _log_only_metrics(cw, store, inv=inv, t0=t0, t1=t1)
    app_logs = _app_logs(logs, store, gateway_id=gateway_id, t0=t0, t1=t1, trial_ids=trial_ids)
    spans = _spans(logs, store, gateway_arn=gateway_arn,
                   request_ids=[r.get("request_id", "") for r in rows])

    # -------- the verdict: metrics alone, both halves necessary -------------
    joinable = bool(score_half["score_metric_exists"]) and bool(
        identity_half["any_series_per_request"])

    n_blocked = sum(1 for r in rows if r.get("denied"))
    guard_detail = {
        "log_only_mode_verified": bool(to_log_only.get("verified"))
                                  and to_log_only.get("readback_mode") == ENGINE_LOG_ONLY,
        "golden_set_landed": len(rows) == n and cp.n_failed == 0,
        # LOG_ONLY means nothing is blocked (F4-2/F4-3 measured this at n=120). A block inside
        # the window would mean the mode did not take, and every reading here would be of
        # ENFORCE telemetry wearing a LOG_ONLY label.
        "nothing_blocked_in_log_only": n_blocked == 0,
        "labels_share_a_bucket": bool(identity_half["mixed_label_buckets"]),
        "metrics_enumerated": bool(inv.get("exhausted")) and "error" not in inv,
        # Not `HARVEST_SETTLE_S > 11.485`: the threshold is read from F7-6's own result, so a
        # re-measured lag that exceeded this settle would fail the guard instead of being
        # outvoted by a constant someone remembered.
        "publish_lag_respected": bool(lag.get("settle_exceeds_p90")),
        "mode_restored": bool(restore.get("verified"))
                         and restore.get("phase2_assertion", {}).get("ok", False),
        "probe_policy_removed": bool(probe_removal.get("deleted")),
    }
    failed_guards = sorted(k for k, v in guard_detail.items() if not v)

    rec = O.evaluate(O.Observation(
        case_id=CASE, n_attempted=n, n_usable=len(rows), observed_bool=joinable,
        detail={"score_half": score_half["score_metric_exists"],
                "identity_half": bool(identity_half["any_series_per_request"]),
                "failed_guards": failed_guards}))
    if failed_guards:
        rec["verdict"] = "INCONCLUSIVE"
        rec.setdefault("notes", []).append(
            f"guard(s) failed: {', '.join(failed_guards)}; each one would make this window "
            f"mean something other than 'a LOG_ONLY calibration pass'")

    which = ([] if score_half["score_metric_exists"] else ["no metric carries a score"]) + \
            ([] if identity_half["any_series_per_request"]
             else ["every series aggregates more than one request per datapoint"])
    payload = {
        "family": FAMILY, "run_id": run_id, "region": region, "alpha": alpha,
        "is_smoke": is_smoke, "cell": None, "n_derivation": {
            "n": n,
            "planned_n_sealed": O.planned_n(CASE),
            "why_no_sealed_n": "BINDINGS['F3-10'].cell is None, so this case has no sealed cell",
            "why_60": ("one differently-labelled pair in one bucket refutes the identity half, "
                       "so any n>=2 would refute it; 60 is chosen so that the score half's "
                       "enumeration runs against a window busy enough that an absent metric "
                       "cannot be blamed on idleness, and so the LOG_ONLY comparison metrics "
                       "have something to count"),
            "positives": sum(1 for i in items if i["truth"] == "positive"),
            "negatives": sum(1 for i in items if i["truth"] == "negative"),
        },
        "instrument": {
            "scored_surface": "CloudWatch metrics alone, per the sealed oracle text",
            "recorded_not_scored": ["gateway APPLICATION_LOGS", "aws/spans AuthorizeAction",
                                    "the LOG_ONLY comparison metrics"],
            "two_necessary_halves": {
                "a_score": "a numeric score per request, else there is no threshold to sweep",
                "b_identity": "an identifier tying that number to a known ground-truth label",
            },
            "why_both": ("a confusion matrix is a table of labelled scores; either half "
                         "missing makes 7.1 step 3 unexecutable, and the two failures have "
                         "different characters so they are measured separately"),
            "request_rate": ("serial, no inter-call delay, so several differently-labelled "
                             "requests share a 60s bucket — the collision IS half (b)"),
        },
        "ambient_sdk": A.sdk_versions(),
        "gateway_id": gateway_id, "policy_engine_id": engine_id, "action_id": action_id,
        "update_gateway_shape_check": shape,
        "mode_axis": {"start": start_mode, "to_log_only": to_log_only, "restore": restore},
        "probe": {"policy_id": probe_id, "removal": probe_removal,
                  "statement_shape": {"effect": "forbid", "function": GUARDRAIL_FUNCTION,
                                      "category": GUARDRAIL_CATEGORY,
                                      "data_path": GUARDRAIL_PATH,
                                      "threshold": GUARDRAIL_THRESHOLD,
                                      "enforcement_mode": POLICY_ENFORCE},
                  "why_needed": ("with no live guardrail there is nothing for a score to be a "
                                 "score of, and its absence would be a fact about this "
                                 "configuration rather than about the service")},
        "window": {"t0": t0, "t1": t1, "duration_s": round(t1 - t0, 3),
                   "harvest_settle_s": HARVEST_SETTLE_S,
                   "f7_6_lag": lag,
                   "why_fixed_not_polled": ("a loop that waited until a score metric appeared "
                                            "could never observe its absence")},
        "traffic": {"n_attempted": n, "n_usable": len(rows),
                    "n_transport_errors": len(cp.results()) - len(rows),
                    "n_failed": cp.n_failed, "n_blocked": n_blocked,
                    "outcomes": {o: sum(1 for r in rows if r.get("outcome") == o)
                                 for o in sorted({r.get("outcome", "") for r in rows})}},
        "metric_inventory": inv,
        "score_half": score_half,
        "identity_half": identity_half,
        "log_only_comparison_metrics": log_only,
        "application_logs": app_logs,
        "spans": spans,
        "guards": guard_detail, "guard_names": list(GUARDS),
        "guard_detail": {"failed": failed_guards},
        "verdict_reading": (
            "the §7.1 calibration loop is executable as written"
            if joinable else
            "a reader following §7.1 cannot build the confusion matrix step 3 asks for: "
            + "; ".join(which)),
        "failure_characters": {
            "score_half": score_half.get("failure_character", ""),
            "identity_half": identity_half.get("failure_character", ""),
            "why_the_distinction": (
                "an absolute failure cannot be worked around by changing how traffic is sent; "
                "a conditional one can, and a reader deserves to know which they are facing "
                "(feedback_constraints_are_choices)"),
        },
        "what_true_does_not_prove": (
            "nothing here tests whether a reader could recover the join OUTSIDE AWS-native "
            "telemetry — by proxying every request through their own middleware, or by calling "
            "ApplyGuardrail directly and keeping the scores themselves. That is a rewrite of "
            "§7.1, not an execution of it, and it belongs in the amendment"),
        "amendment_material": {
            "sealed_units_in_this_claim_group": [
                "C-s7-1-prose-001", "C-s7-1-prose-003", "C-s7-1-mermaid-001",
                "C-s7-1-mermaid-002", "C-s7-1-mermaid-003", "C-s7-1-mermaid-004",
                "C-s7-1-mermaid-005", "C-s7-1-mermaid-007", "C-s7-1-mermaid-008"],
            "decision_diamond_readable": log_only["per_metric"].get(
                "LogOnlyDecisionFlips", {}).get("published_for_this_gateway"),
            "other_surfaces_restore_the_join": {
                "application_logs": bool(app_logs.get("score_present")
                                         and app_logs.get("identity_present")),
                "spans": bool(spans.get("score_present") and spans.get("identity_present")),
            },
            "relation_to_dev_p4_01": (
                "DEV-P4-01 recorded that no surface publishes a numeric guardrail score. This "
                "case is the per-request half of that finding, measured in the mode §7.1 names"),
        },
    }

    out = P.emit(CASE, rec, payload, store)
    print(f"\n{CASE}: {rec['verdict']}  ->  {out}")
    print(f"  score half:    {'a score metric exists' if score_half['score_metric_exists'] else 'NO metric carries a score'}"
          f"  ({score_half['failure_character'] or 'n/a'})")
    print(f"  identity half: {len(identity_half['any_series_per_request'])} of "
          f"{identity_half['n_series_read']} series reach one request per datapoint"
          f"  ({identity_half['failure_character'] or 'n/a'})")
    print(f"  app logs: {app_logs.get('n_events_in_window', 'n/a')} events, "
          f"spans: {spans.get('n_rows', 'n/a')} rows, "
          f"span join by request id: {spans.get('n_spans_naming_one_of_our_request_ids', 'n/a')}")
    if failed_guards:
        print(f"  FAILED GUARDS: {', '.join(failed_guards)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
