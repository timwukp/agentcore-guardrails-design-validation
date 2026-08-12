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
  arms_own_their_buckets      no two arms' requests share a 60s bucket, checked from the rows;
                              otherwise the spaced arm's one-request-per-bucket premise is read
                              off a datapoint aggregating the fast arm's 60
  metrics_enumerated          ListMetrics was paginated to exhaustion, not truncated
  publish_lag_respected       the harvest waited more than F7-6's measured p90 lag
  mode_restored               ENFORCE is back, verified by re-running the Phase-2 assertion
  probe_policy_removed        the guardrail policy this script created is gone
"""

from __future__ import annotations

import csv
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
import redact as _redact                                            # noqa: E402
import testbed as T                                                 # noqa: E402
from checkpoint import Checkpoint                                    # noqa: E402
from evidence import EvidenceStore, capture                          # noqa: E402

CASE = "F3-10"
TRIAGE = Path(__file__).resolve().parent.parent / "claims" / "triage.csv"
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
# The BARE tool name. It is the suffix of the Cedar action id and it is NOT what goes over
# the wire: `McpClient.call_tool` documents its `name` as `<TargetName>___<ToolName>`, and on
# 2026-08-12 this script sent the bare name to it. All 60 calls came back as JSON-RPC errors
# reading `Unknown tool: echo` (gateway APPLICATION_LOGS, severityText ERROR) — rejected at
# MCP dispatch BEFORE any policy evaluation, which is why every policy-engine metric in the
# window had zero datapoints and the case published a TRUE it had not measured. The qualified
# name is `action_id`, resolved from the target's own `cedar_action_ids`, and
# `_preflight_tool_name` now asserts the gateway advertises it. See DEVIATIONS/DEV-P4-22.
TOOL = "echo"
# Outcomes that mean the policy engine ACTUALLY EVALUATED the request. A `jsonrpc_error` is a
# protocol-level rejection: the call never reached the engine, so it can neither be blocked nor
# scored, and counting one as a landed trial is what let the defect above pass every guard.
EVALUATED_OUTCOMES = ("allowed", "policy_denied")

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

# Every arm starts on a FRESH minute bucket, and a margin past the boundary absorbs the skew
# between our `t_send` and the service's own timestamping.
#
# Without this, `our_buckets` does not mean what the two halves read it as meaning. The arms run
# back to back: `active_golden_set` finishes its 60 fast calls and `active_one_per_minute` sends
# its first request immediately, so the two share a minute — and a datapoint aggregating 61
# requests would be attributed to the arm whose entire purpose is one request per bucket. The
# spaced arm would have measured, and refuted, its own premise. `SETTLE_DWELL_S` (15 s, F4's mode
# dwell) is shorter than a period, so the flip between arms does not provide this separation
# either.
#
# It also separates the FIRST arm from the MCP handshake and the `tools/list` preflight. Those
# calls are the origin of the 12 single-sample "per-request" series that half (b) read on
# 2026-08-12; a request-level claim must not be answerable by a protocol call that happened
# before the traffic (`feedback_label_must_match_computation`).
BUCKET_MARGIN_S = 5.0

# THE ARMS
# --------
# §7.1's workflow is a LOG_ONLY shadow evaluation, so `log_only_golden_set` is the arm the
# sealed oracle is about and it was the only arm this case originally had. The other two exist
# because of what the 2026-08-12 defect taught: the case reported "no score datapoint in the
# window" from a window in which the guardrail had never run, and an absence is only evidence
# once it is shown to be the absence OF SOMETHING. So:
#
# * `active_golden_set` sends the same 60 items with the engine left in ENFORCE. If a score
#   publishes here and not under LOG_ONLY, the difference is a fact about the mode §7.1 names,
#   which is a stronger finding than either arm alone. It needs no mutation — the testbed
#   already starts in ENFORCE — so it runs first, before the mode is touched.
# * `active_one_per_minute` sends ONE positive and ONE negative more than a period apart. Half
#   (b)'s failure was always labelled "conditional on request rate" on the argument that a
#   reader sending 1 req/min would see SampleCount == 1; this arm MEASURES that escape hatch
#   instead of asserting it. It is NOT scored: 2 requests a minute apart is not the traffic
#   §7.1 describes ("a golden test set or real production traffic"), so letting it move the
#   verdict would answer an easier question than the one asked.
ARM_ACTIVE_GOLDEN = "active_golden_set"
ARM_ACTIVE_SPACED = "active_one_per_minute"
ARM_LOG_ONLY_GOLDEN = "log_only_golden_set"
ARMS: tuple[dict[str, Any], ...] = (
    {"key": ARM_ACTIVE_GOLDEN, "engine_mode": ENGINE_ENFORCE, "n": None, "spacing_s": 0.0,
     "scored": True,
     "why": "the same golden set with the engine in ENFORCE, so a score's absence under "
            "LOG_ONLY can be attributed to the mode rather than to the traffic"},
    {"key": ARM_ACTIVE_SPACED, "engine_mode": ENGINE_ENFORCE, "n": 2,
     "spacing_s": float(PERIOD_S) + 10.0, "scored": False,
     "why": "one positive and one negative more than a period apart: the measured form of half "
            "(b)'s 'conditional on request rate' escape hatch"},
    {"key": ARM_LOG_ONLY_GOLDEN, "engine_mode": ENGINE_LOG_ONLY, "n": None, "spacing_s": 0.0,
     "scored": True,
     "why": "§7.1's own mode — a shadow evaluation that blocks nothing, which is the whole "
            "point of calibrating in LOG_ONLY before enforcing"},
)
SCORED_ARMS = tuple(a["key"] for a in ARMS if a["scored"])


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

HATE_CORPUS = "content_filter/hate.jsonl"
BENIGN_CORPUS = "benign/benign.jsonl"
# There is no seed, and that is the loader's design rather than an omission here:
# `arms.load_corpus` returns the file in file order and takes `limit`, so the subset is a
# *stated* one ("the first n of the file") that is identical between a dry run and the real
# run. An earlier revision of this script called it with `n=`/`seed=` — neither parameter
# exists — and the dry run could not catch it because `_dry_run` never built the golden set.
# See DEVIATIONS/DEV-P4-21.
CORPUS_SELECTION = "the first n items of each file, in file order (arms.load_corpus limit=)"

GUARDS = ("tool_name_advertised", "log_only_mode_verified", "golden_set_landed",
          "golden_set_was_evaluated", "nothing_blocked_in_log_only",
          "labels_share_a_bucket", "arms_own_their_buckets", "metrics_enumerated",
          "publish_lag_respected", "mode_restored", "probe_policy_removed")
# `golden_set_was_evaluated` and `tool_name_advertised` are the two guards the 2026-08-12
# defect walked through untouched. `golden_set_landed` asked only whether the trials COMPLETED,
# and 60 completed JSON-RPC errors satisfy that; `nothing_blocked_in_log_only` asked whether
# anything was blocked, and nothing can be blocked if nothing is evaluated. Both read as
# healthy while the measurement was empty — a guard that cannot fail is not a guard
# (`feedback_vacuous_test_check`).


class ConfigError(RuntimeError):
    """The testbed is not in a state in which this window measures §7.1's workflow."""


def _sealed_units() -> dict[str, Any]:
    """The sealed claim units that cite F3-10, DERIVED from `claims/triage.csv`.

    This file's first version published the list as a hand-written tuple of nine ids, and the list
    was wrong: it omitted `C-s7-1-prose-004`, which is §7.1 step 3's own sentence — *"Label results
    and use the confidence scores in the logs to build a confusion matrix"* — and therefore the
    unit this case exists to answer for. The reason it was omitted is visible once the register is
    read as data rather than recalled: `prose-004`'s `cases` cell is `"F3-10 F3-9"`, so it is the
    one F3-10 row that a whole-cell comparison misses. A list typed into a payload is a claim
    nothing checks (`feedback_prose_is_not_verified`), and how many units a finding says it touches
    decides how much of the document an amendment has to reach.

    `triage.csv` is a sealed bound artifact, so this only ever reads it. Membership is by
    whitespace token, which is how `claims/check_coverage.py` reads the same column — one reader
    for the join, not two that can disagree. A group of zero is an error rather than an empty list:
    it would mean the case id no longer appears in the register at all.
    """
    if not TRIAGE.is_file():
        raise ConfigError(f"{TRIAGE} is missing — the sealed claim register is the authority on "
                          "which units this case answers for")
    units, shared = [], {}
    with TRIAGE.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cases = (row.get("cases") or "").split()
            if CASE not in cases:
                continue
            units.append(row["claim_id"])
            others = [c for c in cases if c != CASE]
            if others:
                shared[row["claim_id"]] = others
    if not units:
        raise ConfigError(f"no row in {TRIAGE.name} cites {CASE}")
    return {
        "source": "claims/triage.csv (sealed), rows whose `cases` column contains the case id "
                  "as a whitespace token — the same read claims/check_coverage.py performs",
        "n": len(units),
        "unit_ids": sorted(units),
        "doc_lines": sorted({int(r) for r in _triage_lines(units)}),
        "shared_with_other_cases": shared,
    }


def _triage_lines(unit_ids: list[str]) -> list[str]:
    """`doc_line` for each unit, so the finding cites lines it read rather than lines it recalls."""
    want = set(unit_ids)
    with TRIAGE.open(encoding="utf-8", newline="") as fh:
        return [row["doc_line"] for row in csv.DictReader(fh)
                if row["claim_id"] in want and (row.get("doc_line") or "").strip()]


# ---------------------------------------------------------------------------
# the golden set
# ---------------------------------------------------------------------------

def _corpus(rel: str, n: int) -> list[dict[str, str]]:
    """The first `n` items of a sealed corpus, in file order.

    `stratify_by` is deliberately not passed: both files are single-label (hate.jsonl is 120
    × HATE, benign.jsonl is 110 × CLEAN), so a head cannot drop a stratum here — the failure
    DEV-P1-10 records for the multilingual file. The ground truth this script joins against
    comes from `truth` in `_golden_set`, which is the file the item came from, not its
    `label` field.
    """
    return R.load_corpus(rel, limit=n)


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


def _preflight_tool_name(client, action_id: str) -> dict[str, Any]:
    """Assert the gateway ADVERTISES the name we are about to send, before anything mutates.

    This is the guard that would have cost 2026-08-12's run nothing and saved all of it. The
    script had the qualified `action_id` in hand and sent the bare `echo`; the gateway answered
    every one of the 60 calls with `Unknown tool: echo` and the case scored a window in which
    the policy engine had never run.

    `tools/list` is used here as a NAME check and nothing else. Its own docstring in `lib/mcp`
    is explicit that visibility is not authorization — a tool listed may still be denied — so a
    name found here proves only that the string will dispatch, which is exactly the failure
    being ruled out. Whether the call is then allowed or denied is the measurement.
    """
    tools, dec = client.list_tools()
    names = sorted(t.get("name", "") for t in tools)
    out = {"advertised": names, "sending": action_id, "ok": action_id in names,
           "list_outcome": dec.outcome,
           "why_not_authorization": ("tools/list is a meta action: a name here says the string "
                                     "dispatches, not that the call is permitted")}
    if not out["ok"]:
        raise ConfigError(
            f"the gateway does not advertise {action_id!r}; it advertises {names}. Sending a "
            f"name the gateway does not know returns a JSON-RPC error BEFORE policy evaluation, "
            f"so every metric in the window would be of traffic the engine never saw "
            f"(DEV-P4-22)")
    return out


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
        "evaluated": d.outcome in EVALUATED_OUTCOMES,
        # Kept for every outcome the engine did not evaluate. The rows from 2026-08-12 recorded
        # `outcome: jsonrpc_error` and nothing else, so diagnosing 60 identical failures needed a
        # separate CloudWatch Logs query against a 7-day retention. The message is the diagnosis:
        # `Unknown tool: echo`.
        "error_text": ("" if d.outcome in EVALUATED_OUTCOMES else str(d.text or "")[:300]),
    }


def _isolate_bucket(*, now: float | None = None, sleep: bool = True) -> dict[str, Any]:
    """Wait until the next minute boundary plus a margin, so this arm owns its first bucket.

    Returns what it did rather than nothing, because the separation is a premise of both halves
    and a premise that is not recorded cannot be checked by a reader. `now`/`sleep` exist so the
    arithmetic can be tested without waiting (`feedback_vacuous_test_check`).
    """
    t = time.time() if now is None else now
    boundary = (int(t // PERIOD_S) + 1) * PERIOD_S
    target = boundary + BUCKET_MARGIN_S
    gap = max(0.0, target - t)
    out = {"slept_s": round(gap, 3), "bucket_before": int(t // PERIOD_S) * PERIOD_S,
           "bucket_after": int(target // PERIOD_S) * PERIOD_S,
           "margin_s": BUCKET_MARGIN_S,
           "why": ("the previous arm's requests and this arm's must not share a minute bucket, "
                   "or `our_buckets` names both arms' traffic")}
    assert out["bucket_after"] > out["bucket_before"], out
    if sleep and gap:
        time.sleep(gap)
    return out


def _arms_own_their_buckets(harvests: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """No two arms' requests share a 60 s bucket — read off the ROWS, not off the sleep.

    `_isolate_bucket` is what tries to produce this property; this is what checks it happened. A
    guard computed from the helper's own return value would assert the harness's intention, which
    is the shape of every defect DEV-P4-22 records. Two arms sharing a bucket would make
    `our_buckets` name both arms' traffic, and `active_one_per_minute` — 2 requests, whole purpose
    one request per bucket — would then be reading a datapoint that aggregated the fast arm's 60.
    """
    keys = list(harvests)
    shared: dict[str, list[int]] = {}
    for i, ka in enumerate(keys):
        for kb in keys[i + 1:]:
            both = sorted(set(harvests[ka]["identity_half"]["our_buckets"])
                          & set(harvests[kb]["identity_half"]["our_buckets"]))
            if both:
                shared[f"{ka}|{kb}"] = both
    return {"ok": not shared, "shared_buckets": shared,
            "buckets_per_arm": {k: h["identity_half"]["our_buckets"]
                                for k, h in harvests.items()}}


def _run_arm(client, tool_name: str, *, arm: dict[str, Any], items: list[dict[str, Any]],
             is_smoke: bool) -> Checkpoint:
    """Send one arm's items, resumably, at the arm's own spacing.

    For the golden-set arms the spacing is zero and the rate IS the instrument. For
    `active_one_per_minute` it is a period plus a margin, which is the point of that arm.
    """
    cp = Checkpoint(case_id=CASE, cell=arm["key"]).load()
    cp.set_meta(is_smoke=is_smoke, n_planned=len(items), corpus_selection=CORPUS_SELECTION,
                tool=TOOL, mcp_tool_name=tool_name, arm=arm["key"],
                engine_mode=arm["engine_mode"], spacing_s=arm["spacing_s"],
                scored=arm["scored"], why_this_arm=arm["why"], period_s=PERIOD_S,
                why_no_inter_call_delay=("the aggregation collision IS half (b) of the "
                                         "measurement; spacing the calls one per minute would "
                                         "measure a request rate no reader of 7.1 would use"))
    for i, item in enumerate(items):
        tid = f"t{i:04d}"
        if cp.is_done(tid):
            continue
        if i and arm["spacing_s"]:
            time.sleep(arm["spacing_s"])
        client.refresh_if_stale()
        # `tool_name`, NOT `TOOL`. See the comment on TOOL: the bare name does not dispatch.
        cp.run_trial(tid, lambda it=item: _call(client, tool_name, it))
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
    """Half (a): does a metric carry a confidence score — as a NAME, and as a VALUE?

    THE NAME AND THE VALUE ARE TWO DIFFERENT FACTS, AND ONLY ONE OF THEM CAN SCORE
    ------------------------------------------------------------------------------
    `ListMetrics` answers the first. It is an INDEX: it returns any series the account has
    published in roughly the last two weeks, by any traffic, under any configuration. On
    2026-08-12 this function returned `score_metric_exists: True` on the strength of
    `ConfidenceScore` appearing in that index — and every one of the 24 listed score series had
    ZERO datapoints in the window, because the golden set had been rejected at MCP dispatch and
    the policy engine had never run. A name in an index is not a number a reader can read
    (DEV-P4-22, and `feedback_prose_is_not_verified` one layer down: an unchecked fact inside a
    justification).

    So the name reading is kept — it is what makes the failure ABSOLUTE when it fails, since a
    metric the namespace does not publish cannot be produced by any request rate — but it no
    longer scores. `score_readable` is filled in by `_score_datapoints`, from datapoints in this
    arm's own window, and that is what the verdict reads.
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
        "score_metric_name_exists": bool(ns_hits),
        "name_source": ("ListMetrics, which is an index over ~2 weeks of account-wide "
                        "publishing and says nothing about this window"),
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


def _score_datapoints(identity_half: dict[str, Any]) -> dict[str, Any]:
    """Half (a), the part that scores: did a score series publish a VALUE in this window?

    Read off the per-series harvest rather than by re-querying, so the datapoints scored here
    are the same ones the identity half read. A score series is one whose NAME matches the
    criterion fixed above; `readable` requires at least one datapoint whose bucket is a bucket
    one of our own requests fell in — a datapoint two hours earlier from another case's traffic
    is not a score of anything this arm sent.
    """
    series = [e for e in (identity_half.get("per_series") or [])
              if SCORE_NAME_RE.search(e.get("name", ""))]
    with_dps = [e for e in series if (e.get("n_datapoints") or 0) > 0]
    in_our_buckets = [e for e in series if (e.get("datapoints_in_our_buckets") or 0) > 0]
    vals = [d for e in in_our_buckets for d in (e.get("datapoints") or [])
            if d.get("bucket_s") in set(identity_half.get("our_buckets") or [])]
    return {
        "n_score_series_this_gateway": len(series),
        "n_score_series_with_any_datapoint": len(with_dps),
        "n_score_series_with_a_datapoint_in_our_buckets": len(in_our_buckets),
        "score_series_readable": sorted({e["name"] for e in in_our_buckets}),
        "readable": bool(in_our_buckets),
        "sample_counts_in_our_buckets": sorted({d.get("sample_count") for d in vals}),
        "value_range_in_our_buckets": (
            {"min": min(d["min"] for d in vals if d.get("min") is not None),
             "max": max(d["max"] for d in vals if d.get("max") is not None)}
            if any(d.get("min") is not None for d in vals) else None),
        "why_buckets_not_just_datapoints": (
            "a score series can hold datapoints from another case's traffic minutes earlier; "
            "only a datapoint in a bucket one of OUR requests landed in can be a score of "
            "something this arm sent"),
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

    WHICH SERIES THIS HALF IS ABOUT
    -------------------------------
    The score series, and — for the record — the rest. On 2026-08-12 `any_series_per_request`
    named 12 series and the verdict conjoined that with half (a) to reach TRUE. All 12 were
    `Latency`/`Invocations`/`Duration`/`Throttles`/`UserErrors`/`SystemErrors` on
    `Method: initialize` and `Method: notifications/initialized` — the MCP handshake, called
    once each, so their SampleCount of 1 was a fact about a one-off protocol call and not about
    request-level granularity. None of them was a score series. The conjunction therefore joined
    the existence of a score to the granularity of six OTHER series, which is not a join at all
    (`feedback_label_must_match_computation`).

    Two changes follow. A series only counts as per-request if its datapoints land in buckets
    OUR requests fell in — which excludes a handshake that happened before the arm and any other
    case's traffic. And `per_request_score_series` is reported separately, because that is the
    set the oracle is actually about: a score you cannot attribute is not a score you can
    calibrate against.
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
        # OUR buckets, not any bucket in the read range. A datapoint from the MCP handshake or
        # from another case's traffic is in the range but is not one of our requests.
        ours = [d for d in entry["datapoints"] if d["bucket_s"] in set(buckets)]
        entry["datapoints_in_our_buckets"] = len(ours)
        entry["all_datapoints_are_single_request"] = (
            bool(ours) and all((d["sample_count"] or 0) <= 1 for d in ours))
        entry["is_a_score_series"] = bool(SCORE_NAME_RE.search(entry["name"]))
        entry["carries_a_request_identifier"] = False   # see `why_no_identifier_dimension`
        per_series.append(entry)

    collided = [e for e in per_series
                if (e.get("max_sample_count_in_mixed_bucket") or 0) > 1]
    per_request = [e for e in per_series if e.get("all_datapoints_are_single_request")]
    per_request_score = [e for e in per_request if e["is_a_score_series"]]
    return {
        "period_s": PERIOD_S,
        "buckets_covered": {str(b): c for b, c in sorted(buckets.items())},
        "our_buckets": sorted(buckets),
        "n_buckets": len(buckets),
        "mixed_label_buckets": [str(b) for b in mixed],
        "multi_request_buckets": [str(b) for b in multi],
        "n_series_read": len(per_series),
        "per_series": per_series,
        "n_series_colliding_in_a_mixed_bucket": len(collided),
        "series_colliding": sorted({e["name"] for e in collided}),
        "any_series_per_request": [e["name"] for e in per_request],
        # The set the oracle is about: a score series whose every datapoint in our buckets holds
        # exactly one request. This — not `any_series_per_request` — is half (b).
        "per_request_score_series": [e["name"] for e in per_request_score],
        "identity_recoverable_for_a_score": bool(per_request_score),
        "why_score_series_only": (
            "half (b) asks whether a SCORE can be tied to a label. The granularity of Latency "
            "or of an MCP handshake call cannot answer that, however clean it looks"),
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

def _looks_numeric(s: str) -> bool:
    """Does this string hold a number? `float()` is the test, not a regex.

    `"0.8000"`, `"1"`, `"-3e2"` are numbers wearing quotes. `"HATE"`, `""` and `"0.8 (high)"`
    are not. `float()` also accepts `"nan"`, `"inf"` and `"  4 "`, which is fine here: the
    census is looking for anything a reader could plausibly threshold on.
    """
    try:
        float(s)
    except (TypeError, ValueError):
        return False
    return True


def _numeric_keys(obj: Any, prefix: str = "", acc: dict[str, Any] | None = None,
                  str_acc: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every numeric-valued key path in a decoded record, with one example value each.

    This is the check that keeps half (a) from being a word game. A score published as
    `severity` or `sensitivity` would not match the name pattern, so the full set of numeric
    fields any surface carries is enumerated and printed; a reader can then see for themselves
    that nothing score-shaped was passed over, instead of trusting a regex.

    A NUMBER IN A STRING IS STILL A NUMBER
    --------------------------------------
    The version of this walker that ran on 2026-08-12 collected `int` and `float` values only,
    and the gateway publishes the guardrail score as a JSON **string**:

        body.policy.guardrailFindings.<policyId>.contentFilter[].score == "0.8000"

    So the census whose whole purpose was to keep half (a) honest was blind, BY ITS OWN TYPE
    FILTER, to the single field it existed to find — a guard true by construction
    (`feedback_vacuous_test_check`). `numeric_keys_seen` on that run listed
    `body.policy.latencyMs` and nothing else from the policy block, and the published
    `application_logs` half consequently understated the surface. `str_acc`, when passed,
    collects every string value that parses as a float under the same key path; callers record
    it as `numeric_strings_seen` and it is reported beside the numbers, not merged into them —
    the type is itself a finding, because Logs Insights arithmetic on `score` needs a cast.
    See DEVIATIONS/DEV-P4-23 and `f3_efficacy/08b_log_surface_join.py`.
    """
    acc = {} if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            _numeric_keys(v, f"{prefix}.{k}" if prefix else str(k), acc, str_acc)
    elif isinstance(obj, list):
        for v in obj[:5]:
            _numeric_keys(v, f"{prefix}[]", acc, str_acc)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)) and prefix:
        acc.setdefault(prefix, obj)
    elif isinstance(obj, str) and prefix and str_acc is not None and _looks_numeric(obj):
        str_acc.setdefault(prefix, obj)
    return acc


def _app_logs(logs, store, *, gateway_id: str, t0: float, t1: float,
              trial_ids: set[str], rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The gateway's APPLICATION_LOGS group over the window. 'Logged' is §7.1's own word.

    `storedBytes` is deliberately NOT the instrument: it is an approximate, lagging field, and
    reading zero from it would be a claim about CloudWatch's bookkeeping rather than about
    whether anything was written. The events are fetched.

    `identity_present` USED TO ASK THE WRONG QUESTION
    -------------------------------------------------
    Until 2026-08-12 this function measured identity as "does an event's text contain one of our
    CORPUS ids", and reported `identity_present: false` — from a surface on which every policy
    event carries `request_id`, which is the field the harness records on every row and the field
    `_spans` already joins on. A needle that is not on the surface is a fact about the needle
    (`feedback_label_must_match_computation`). `rows` is now joined by `request_id` and the join
    is reported separately from the corpus-id count, which is kept because its absence is also
    true and worth stating: the request TEXT is logged verbatim, the corpus id is not.

    This surface stays `scored: False` — the sealed oracle says "from CloudWatch metrics alone"
    and that is not renegotiable here. The correction changes what is RECORDED about it, not what
    the verdict is computed from. `f3_efficacy/08b_log_surface_join.py` is where the log surface
    is read properly, as a supplementary read with no verdict.
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
    numeric_strings: dict[str, Any] = {}
    id_hits, score_hits, rid_hits = 0, 0, 0
    samples: list[str] = []
    want_rid = {str(r.get("request_id")) for r in (rows or []) if r.get("request_id")}
    for ev in events:
        msg = ev.get("message") or ""
        if len(samples) < 3:
            # Mask BEFORE truncating. A 400-character slice of a raw log message knows nothing
            # about what it is cutting, and on 2026-08-12 it cut the live account ID in half
            # inside a `policyEngineArn` — leaving 11 of 12 digits, which neither the ARN
            # pattern nor the 12-digit bare-token pass could then see. Masking first means the
            # slice can only ever land inside `<account>` (DEV-P4-24).
            samples.append(_redact.mask_text(msg)[:400])
        try:
            body = json.loads(msg)
        except (ValueError, TypeError):
            body = {"_unparsed": msg}
        _numeric_keys(body, acc=numeric, str_acc=numeric_strings)
        if any(t in msg for t in trial_ids):
            id_hits += 1
        if isinstance(body, dict) and str(body.get("request_id")) in want_rid:
            rid_hits += 1
        if SCORE_NAME_RE.search(msg):
            score_hits += 1
    # Half (a) on this surface, asked of the CENSUS rather than of the message text: a name
    # pattern matching somewhere in a JSON blob says a word appeared, not that a number did.
    score_keys = sorted(k for k in (numeric | numeric_strings) if SCORE_NAME_RE.search(k))
    out.update({
        "numeric_keys_seen": dict(sorted(numeric.items())),
        "numeric_strings_seen": dict(sorted(numeric_strings.items())),
        "score_valued_key_paths": score_keys,
        "n_events_naming_one_of_our_corpus_ids": id_hits,
        "n_events_naming_one_of_our_request_ids": rid_hits,
        "n_events_matching_the_score_pattern": score_hits,
        "sample_messages": samples,
        "score_present": bool(score_keys),
        "identity_present": rid_hits > 0,
        "join_key_available": "request_id" if rid_hits else "",
        "why_identity_is_request_id": ("the corpus id is not on this surface and the request text "
                                       "is; `request_id` is what both the rows and the events "
                                       "carry, so it is the join key. The corpus-id count is kept "
                                       "beside it because it is also true"),
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
    numeric_strings: dict[str, Any] = {}
    id_hits, score_hits = 0, 0
    want = set(r for r in request_ids if r)
    for row in rows:
        msg = next((f["value"] for f in row if f.get("field") == "@message"), "")
        try:
            body = json.loads(msg)
        except (ValueError, TypeError):
            body = {"_unparsed": msg}
        _numeric_keys(body, acc=numeric, str_acc=numeric_strings)
        if any(rid in msg for rid in want):
            id_hits += 1
        if SCORE_NAME_RE.search(msg):
            score_hits += 1
    # Same correction as `_app_logs`: a score published as a JSON string was invisible to the
    # numeric census, so a span carrying `"score": "0.8000"` would have been reported as
    # score-free. See `_numeric_keys`.
    score_keys = sorted(k for k in (numeric | numeric_strings) if SCORE_NAME_RE.search(k))
    out.update({
        "numeric_keys_seen": dict(sorted(numeric.items())),
        "numeric_strings_seen": dict(sorted(numeric_strings.items())),
        "score_valued_key_paths": score_keys,
        "n_spans_naming_one_of_our_request_ids": id_hits,
        "n_spans_matching_the_score_pattern": score_hits,
        "score_present": bool(score_keys),
        "identity_present": id_hits > 0,
        "join_key_available": "request_id" if id_hits else "",
    })
    return out


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def _rows(cp: Checkpoint) -> list[dict[str, Any]]:
    return [v for v in cp.results().values() if v.get("outcome") != "transport_error"]


def _window_from_rows(rows: list[dict[str, Any]], wall_t0: float,
                      wall_t1: float) -> dict[str, Any]:
    """One arm's harvest window, taken from the ROWS rather than the wall clock around the send.

    A checkpointed arm is served from disk in ~0 s, so on a resumed run the wall clock would
    bracket the resume rather than the traffic and every metric read against it would be of an
    idle minute. F5-1 lost a whole leg to exactly that (DEV-P4-15, `NO_INVOKES_IN_WINDOW` from a
    window that contained no invocations because the arm was replayed). On a fresh run these
    values differ from the wall clock only by the microseconds between the stamps.
    """
    t_sends = [float(r["t_send"]) for r in rows if isinstance(r.get("t_send"), (int, float))]
    t_dones = [float(r["t_done"]) for r in rows if isinstance(r.get("t_done"), (int, float))]
    w = {"from": "rows" if t_sends and t_dones else "wall_clock",
         "wall_t0": wall_t0, "wall_t1": wall_t1,
         "resumed_from_checkpoint": bool(t_sends) and (wall_t1 - wall_t0) < min(
             1.0, max(t_dones or [0]) - min(t_sends or [0]))}
    t0, t1 = ((min(t_sends), max(t_dones)) if t_sends and t_dones else (wall_t0, wall_t1))
    w["t0"], w["t1"] = t0, t1
    w["span_s"] = round(t1 - t0, 3)
    return w


def _phase2_assertion(ac, state, account_id: str, region: str) -> dict[str, Any]:
    """Re-run the BLOCKING Phase-2 checks after the restore, and report them honestly.

    PREREGISTRATION's `restore_verification` rule: a restore is not assumed to have worked
    because `UpdateGateway` returned 200. These are the same two functions `infra/06_verify.py`
    runs as the Phase-2 gate.

    Two defects this shape exists to prevent, both found live on 2026-08-12
    (DEVIATIONS/DEV-P4-21):

    * `verify_gateways` takes `(ac, state, account_id, region, c)`. Called with three arguments
      it raises `TypeError`, the `except` below swallows it, and the run continues as if the
      restore had been verified. The arity is now pinned by an offline test.
    * `Checks.failures` is a **method** and `Checks.ok` is `all(...)` over the rows, so it is
      `True` on an EMPTY list. An assertion that raised before adding a single row would
      publish `ok: true` about checks that never ran
      (`feedback_missing_check_is_not_pass`). `n_checks` and `raised` are ANDed in for exactly
      that reason, and both are published.
    """
    checks = _vf.Checks()
    raised = ""
    try:
        _vf.verify_engine(ac, state, checks)
        _vf.verify_gateways(ac, state, account_id, region, checks)
    except Exception as exc:                                        # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
        print(f"    WARN the Phase-2 assertion raised: {raised}", file=sys.stderr)
    cj = checks.to_json()
    out = {
        "ok": bool(cj["ok"]) and cj["n_fail"] == 0 and len(cj["checks"]) > 0 and not raised,
        "n_checks": len(cj["checks"]), "n_pass": cj["n_pass"], "n_fail": cj["n_fail"],
        "raised": raised or None,
        "failures": [c for c in cj["checks"] if not c["ok"]],
    }
    print(f"    restore: blocking checks {cj['n_pass']} pass / {cj['n_fail']} fail"
          f"{' — ASSERTION RAISED' if raised else ''}")
    if cj["n_fail"]:
        checks.print()
    return out


def _wall_clock_estimate(n: int) -> dict[str, Any]:
    """What the run will spend waiting, term by term, derived from the same constants it sleeps on.

    A spaced arm of k items has k-1 gaps. The traffic term is the only guess here (~0.35 s per
    `tools/call`, from F6's measured gateway latency) and it is the smallest term.
    """
    n_spaced_gaps = sum(max(0, min(a["n"], n) - 1) for a in ARMS if a["n"] is not None)
    n_flips = sum(1 for i, a in enumerate(ARMS)
                  if a["engine_mode"] != (ARMS[i - 1]["engine_mode"] if i else ENGINE_ENFORCE))
    n_calls = sum(n if a["n"] is None else min(a["n"], n) for a in ARMS)
    terms = {
        f"{len(ARMS)} bucket waits": len(ARMS) * (PERIOD_S + BUCKET_MARGIN_S),
        f"{n_spaced_gaps} spaced gap(s)": n_spaced_gaps * float(PERIOD_S) + n_spaced_gaps * 10.0,
        f"{n_flips + 1} mode dwell(s)": (n_flips + 1) * SETTLE_DWELL_S,
        "policy settle": POLICY_SETTLE_S,
        "harvest settle": HARVEST_SETTLE_S,
        f"~{n_calls} calls": n_calls * 0.35,
    }
    return {"terms": terms, "total_s": sum(terms.values()),
            "n_spaced_gaps": n_spaced_gaps, "n_flips": n_flips, "n_calls": n_calls}


def _dry_run(n: int) -> int:
    # Build the golden set here, not just describe it. On 2026-08-12 the live run died at
    # `_golden_set` — `load_corpus` has no `n=` or `seed=` parameter — AFTER it had opened four
    # clients, read the gateway and run F4's UpdateGateway preflight, and a dry run that had
    # just printed "total calls: 60" reported rc=0. A dry run that does not execute the code
    # path it is standing in for confirms only its own prose
    # (`feedback_dry_run_before_expensive_run`). Nothing here touches AWS: the corpora are
    # local sealed files.
    items = _golden_set(n)
    pos = sum(1 for i in items if i["truth"] == "positive")
    ids = {i["id"] for i in items}
    print(f"golden set built offline: {len(items)} items, {pos} positive / {len(items) - pos} "
          f"negative, {len(ids)} distinct corpus ids, labels "
          f"{sorted({i['corpus_label'] for i in items})}")
    print(f"  selection: {CORPUS_SELECTION}")
    print()
    # One plan row per arm, and the row's n is the size the arm will actually send. The
    # single-row version of this banner described "one LOG_ONLY window" and was accurate
    # for the instrument that produced the vacuous TRUE of 2026-08-12; three arms is the
    # repair, so the plan has to show three (`feedback_label_must_match_computation`).
    planned = [(a["key"],
                (f"{n // 2} HATE + {n - n // 2} benign, interleaved"
                 if a["n"] is None else f"{min(a['n'], n)} items, {a['spacing_s']:.0f}s apart")
                + f", engine {a['engine_mode']}",
                n if a["n"] is None else min(a["n"], n))
               for a in ARMS]
    total = sum(row[2] for row in planned)
    P.dry_run_banner(
        CASE,
        planned,
        operations={"mcp_tools_call": total},
        mutations=3, billable=True,
        extra=[
            "n is NOT sealed: BINDINGS['F3-10'].cell is None so planned_n is None. 60 is "
            "derived in the docstring and recorded as `n_derivation`",
            f"the arms exist because one arm could not tell 'the service publishes no score' "
            f"from 'the guardrail never ran'. SCORED arms (the ones the verdict reads): "
            f"{', '.join(SCORED_ARMS)}; {ARM_ACTIVE_SPACED} is excluded from the verdict by "
            f"construction because its whole purpose is a request rate below one per period",
            "3 mutations: create the guardrail probe policy, engine ENFORCE->LOG_ONLY for the "
            "third arm, and the restore back to ENFORCE. The first two arms need no flip "
            "because the testbed's steady state IS ENFORCE, which is why they run first. The "
            "probe delete and the restore both run in a finally and the Phase-2 blocking "
            "assertion is RE-RUN after",
            f"ancillary, NOT trials: 1 MCP tools/list PREFLIGHT (it asserts the gateway "
            f"advertises the qualified name before anything is created — on 2026-08-12 the "
            f"bare name {TOOL!r} went over the wire and all 60 calls came back "
            f"'Unknown tool', rejected before policy evaluation, see DEV-P4-22), "
            f"list_metrics x~2 (paginated to exhaustion), "
            f"get_metric_statistics x~40 per arm (one per published series plus the LOG_ONLY "
            f"set), describe_log_groups x1, filter_log_events x1, 1 Logs Insights span query, "
            f"get_gateway x~8, and 1 MCP initialize",
            "SCORED surface: CloudWatch metrics alone, because that is what the sealed oracle "
            "says. Application logs and spans are read and recorded as amendment material and "
            "cannot move the verdict",
            "half (a) is read TWICE and the readings are published separately: whether a score "
            "metric NAME exists in the namespace index (ListMetrics indexes ~2 weeks of "
            "account-wide publishing, so a name there may be another case's traffic) and "
            "whether a score series carried a DATAPOINT in a bucket one of our requests fell "
            "in. Only the second can move the verdict; half (b) identity is CONDITIONAL on "
            "request rate, and the escape hatch is now MEASURED by the spaced arm rather than "
            "argued",
            f"the harvest waits {HARVEST_SETTLE_S:.0f}s, against F7-6's measured publish-lag "
            f"p90 of {_f7_6_lag_p90_s().get('p90_s')}s read from its own result file "
            f"(ratio {_f7_6_lag_p90_s().get('settle_over_p90_ratio')}x), and the wait is fixed "
            f"rather than polled: a loop that waited until a score appeared could never "
            f"observe its absence",
            f"each arm waits for a FRESH minute bucket before its first request (up to "
            f"{PERIOD_S + BUCKET_MARGIN_S:.0f}s, margin {BUCKET_MARGIN_S:.0f}s past the "
            f"boundary), so no two arms share a bucket and neither does the MCP handshake — the "
            f"handshake is where 2026-08-12's 12 bogus 'per-request' series came from. The "
            f"property is then GUARDED from the rows, not trusted from the sleep",
            # Spelled out term by term so the number cannot drift from what the script sleeps.
            # A spaced arm of k items has k-1 gaps, not k (`feedback_span_vs_points_offbyone`).
            f"wall clock ~{_wall_clock_estimate(n)['total_s']:.0f}s "
            f"~= {_wall_clock_estimate(n)['total_s'] / 60:.0f} min: "
            + ", ".join(f"{k} {v:.0f}s" for k, v in _wall_clock_estimate(n)["terms"].items()),
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
    preflight: dict[str, Any] = {}
    arm_out: dict[str, dict[str, Any]] = {}
    engine_mode_now = start_mode
    try:
        # Before the probe policy and before any mode switch: does the gateway know the name?
        preflight = _preflight_tool_name(client, action_id)
        print(f"  preflight: gateway advertises {preflight['advertised']}; sending "
              f"{action_id!r}")

        probe_id = _create_probe(ac, store, state, engine_id=engine_id, run_id=run_id,
                                 gateway_arn=gateway_arn, action_id=action_id)
        time.sleep(POLICY_SETTLE_S)

        for arm in ARMS:
            arm_items = items if arm["n"] is None else _golden_set(min(arm["n"], n))
            if arm["engine_mode"] != engine_mode_now:
                print(f"  engine {engine_mode_now} -> {arm['engine_mode']}")
                flip = set_engine_mode(ac, store, gateway_id=gateway_id,
                                       engine_arn=engine_arn, mode=arm["engine_mode"])
                if arm["engine_mode"] == ENGINE_LOG_ONLY:
                    to_log_only = flip
                engine_mode_now = arm["engine_mode"]
                time.sleep(SETTLE_DWELL_S)

            iso = _isolate_bucket()
            print(f"  [{arm['key']}] engine {engine_mode_now}, n={len(arm_items)}, spacing "
                  f"{arm['spacing_s']:.0f}s, {'SCORED' if arm['scored'] else 'recorded only'}"
                  f"  (waited {iso['slept_s']:.1f}s for a fresh bucket)")
            w0 = time.time()
            acp = _run_arm(client, action_id, arm=arm, items=arm_items, is_smoke=is_smoke)
            w1 = time.time()
            arows = _rows(acp)
            n_eval = sum(1 for r in arows if r.get("evaluated"))
            print(f"    done: {acp.n_done} trials, {acp.n_failed} failures, "
                  f"{n_eval}/{len(arows)} evaluated by the engine, {w1 - w0:.1f}s wall clock")
            if n_eval < len(arows):
                bad = sorted({r.get("error_text", "")[:80] for r in arows
                              if not r.get("evaluated")})
                print(f"    WARN {len(arows) - n_eval} request(s) never reached the policy "
                      f"engine: {bad}", file=sys.stderr)
            arm_out[arm["key"]] = {"arm": arm, "cp": acp, "rows": arows, "wall": (w0, w1),
                                   "items": arm_items, "engine_mode": engine_mode_now,
                                   "bucket_isolation": iso}
            if arm["key"] == ARM_LOG_ONLY_GOLDEN:
                cp, t0, t1 = acp, w0, w1
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
        restore["phase2_assertion"] = _phase2_assertion(ac, state, account_id, region)

    if cp is None or ARM_LOG_ONLY_GOLDEN not in arm_out:
        raise ConfigError("the LOG_ONLY golden set never ran; there is nothing to harvest")

    # One settle covers every arm: it follows the LAST arm's traffic, and the earlier arms
    # published even longer ago. Fixed, not polled — a loop that waited until a score appeared
    # could never observe its absence.
    lag = _f7_6_lag_p90_s()
    print(f"  settling {HARVEST_SETTLE_S:.0f}s before the harvest "
          f"(F7-6 p90 lag {lag.get('p90_s')}s)")
    time.sleep(HARVEST_SETTLE_S)

    inv = _enumerate_series(cw, store, gateway_id=gateway_id)
    score_half = _score_half_from_metrics(inv)

    # Each arm is harvested over ITS OWN window. The arms are separated by a settle and a mode
    # switch, so no minute bucket holds two arms' requests — which is what lets `our_buckets`
    # mean "this arm's requests" in the two halves below.
    harvests: dict[str, dict[str, Any]] = {}
    for key, a in arm_out.items():
        w = _window_from_rows(a["rows"], *a["wall"])
        ih = _identity_half_from_metrics(cw, store, inv=inv, rows=a["rows"],
                                        t0=w["t0"], t1=w["t1"])
        sd = _score_datapoints(ih)
        n_eval = sum(1 for r in a["rows"] if r.get("evaluated"))
        harvests[key] = {
            "arm": {k: v for k, v in a["arm"].items()},
            "engine_mode": a["engine_mode"],
            "bucket_isolation": a["bucket_isolation"],
            "window": w,
            "identity_half": ih,
            "score_datapoints": sd,
            "traffic": {
                "n_attempted": len(a["items"]), "n_rows": len(a["rows"]),
                "n_evaluated": n_eval, "n_failed": a["cp"].n_failed,
                "n_transport_errors": len(a["cp"].results()) - len(a["rows"]),
                "n_blocked": sum(1 for r in a["rows"] if r.get("denied")),
                "outcomes": {o: sum(1 for r in a["rows"] if r.get("outcome") == o)
                             for o in sorted({r.get("outcome", "") for r in a["rows"]})},
                "not_evaluated_texts": sorted({r.get("error_text", "") for r in a["rows"]
                                               if not r.get("evaluated")} - {""}),
            },
            "joinable": bool(sd["readable"]
                             and ih["identity_recoverable_for_a_score"]),
        }
        print(f"    [{key}] window {w['span_s']}s ({w['from']}), "
              f"{n_eval}/{len(a['rows'])} evaluated, "
              f"score readable: {sd['readable']} "
              f"({sd['n_score_series_with_a_datapoint_in_our_buckets']} of "
              f"{sd['n_score_series_this_gateway']} score series in our buckets), "
              f"per-request score series: {ih['per_request_score_series'] or 'none'}")

    # The pre-registered arm — §7.1's own mode — is the one whose guards gate the case.
    primary = harvests[ARM_LOG_ONLY_GOLDEN]
    rows = arm_out[ARM_LOG_ONLY_GOLDEN]["rows"]
    window = primary["window"]
    t0, t1 = window["t0"], window["t1"]
    identity_half = primary["identity_half"]
    log_only = _log_only_metrics(cw, store, inv=inv, t0=t0, t1=t1)
    app_logs = _app_logs(logs, store, gateway_id=gateway_id, t0=t0, t1=t1, trial_ids=trial_ids,
                         rows=rows)
    spans = _spans(logs, store, gateway_arn=gateway_arn,
                   request_ids=[r.get("request_id", "") for r in rows])

    # -------- the verdict: metrics alone, both halves necessary -------------
    # BOTH halves, and both ABOUT THE SAME SERIES. Half (a) is now "a score series published a
    # value in a bucket one of our requests fell in" — not "a score name exists somewhere in the
    # index" — and half (b) is "that score series holds one request per datapoint". Any SCORED
    # arm satisfying both makes the join recoverable; the spaced arm is excluded by construction.
    joinable = any(h["joinable"] for k, h in harvests.items() if h["arm"]["scored"])

    n_blocked = sum(1 for r in rows if r.get("denied"))
    n_evaluated_primary = primary["traffic"]["n_evaluated"]
    guard_detail = {
        "tool_name_advertised": bool(preflight.get("ok")),
        "log_only_mode_verified": bool(to_log_only.get("verified"))
                                  and to_log_only.get("readback_mode") == ENGINE_LOG_ONLY,
        "golden_set_landed": len(rows) == n and cp.n_failed == 0,
        # The guard the 2026-08-12 defect needed. "Landed" above asks only whether the trials
        # completed, and 60 completed `Unknown tool` errors satisfy it. This one asks whether the
        # policy engine actually saw them, in EVERY scored arm — an unevaluated request can be
        # neither blocked nor scored, so a window full of them measures nothing.
        "golden_set_was_evaluated": all(
            h["traffic"]["n_evaluated"] == h["traffic"]["n_rows"] > 0
            for k, h in harvests.items() if h["arm"]["scored"]),
        # LOG_ONLY means nothing is blocked (F4-2/F4-3 measured this at n=120). A block inside
        # the window would mean the mode did not take, and every reading here would be of
        # ENFORCE telemetry wearing a LOG_ONLY label. It is only meaningful now that the
        # requests above are known to have been evaluated.
        "nothing_blocked_in_log_only": n_blocked == 0 and n_evaluated_primary > 0,
        "labels_share_a_bucket": bool(identity_half["mixed_label_buckets"]),
        "arms_own_their_buckets": _arms_own_their_buckets(harvests)["ok"],
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

    # `n_usable` counts requests the ENGINE EVALUATED, not requests that got an HTTP response.
    # It was `len(rows)` and reported 60 usable trials out of 60 protocol errors.
    rec = O.evaluate(O.Observation(
        case_id=CASE, n_attempted=n, n_usable=n_evaluated_primary, observed_bool=joinable,
        detail={"score_half_readable": primary["score_datapoints"]["readable"],
                "score_metric_name_exists": score_half["score_metric_name_exists"],
                "identity_half": identity_half["identity_recoverable_for_a_score"],
                "joinable_by_arm": {k: h["joinable"] for k, h in harvests.items()},
                "failed_guards": failed_guards}))
    if failed_guards:
        rec["verdict"] = "INCONCLUSIVE"
        rec.setdefault("notes", []).append(
            f"guard(s) failed: {', '.join(failed_guards)}; each one would make this window "
            f"mean something other than 'a LOG_ONLY calibration pass'")

    which = ([] if primary["score_datapoints"]["readable"]
             else ["no score series published a value for these requests"]) + \
            ([] if identity_half["identity_recoverable_for_a_score"]
             else ["no score series holds one request per datapoint"])
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
            "arms": [{"key": a["key"], "engine_mode": a["engine_mode"], "n": a["n"],
                      "spacing_s": a["spacing_s"], "scored": a["scored"], "why": a["why"]}
                     for a in ARMS],
            "scored_arms": list(SCORED_ARMS),
            "why_the_extra_arms": (
                "the original single LOG_ONLY arm could not tell 'the service publishes no score' "
                "from 'the guardrail never ran' — which is exactly the mistake it made on "
                "2026-08-12. The ENFORCE arm makes the absence an absence OF something, and the "
                "spaced arm turns half (b)'s 'conditional on request rate' from an argument into "
                "a measurement"),
            "evaluated_outcomes": list(EVALUATED_OUTCOMES),
            "why_evaluated_matters": (
                "a request the policy engine never saw can be neither blocked nor scored. "
                "Counting one as usable is what let a window with zero policy evaluations "
                "publish a TRUE (DEV-P4-22)"),
        },
        "tool_name_preflight": preflight,
        "ambient_sdk": A.sdk_versions(),
        "gateway_id": gateway_id, "policy_engine_id": engine_id, "action_id": action_id,
        "update_gateway_shape_check": shape,
        # The engine visits ENFORCE (twice, no flip needed — it is the steady state), then
        # LOG_ONLY, then back. `per_arm` is the mode each arm's traffic was ACTUALLY sent
        # under, read back from the flip rather than assumed from the arm spec, because the
        # attribution the extra arms exist to make rests entirely on it.
        "mode_axis": {"start": start_mode, "to_log_only": to_log_only, "restore": restore,
                      "per_arm": {k: h["engine_mode"] for k, h in harvests.items()},
                      "planned_per_arm": {a["key"]: a["engine_mode"] for a in ARMS}},
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
                   "derivation": window,
                   "harvest_settle_s": HARVEST_SETTLE_S,
                   "f7_6_lag": lag,
                   "why_fixed_not_polled": ("a loop that waited until a score metric appeared "
                                            "could never observe its absence")},
        # `n_usable` is the EVALUATED count. The two are equal on a healthy run and differ by
        # exactly the failure mode DEV-P4-22 records, so both are published.
        "traffic": {"n_attempted": n, "n_usable": n_evaluated_primary,
                    "n_rows": len(rows),
                    "n_transport_errors": len(cp.results()) - len(rows),
                    "n_failed": cp.n_failed, "n_blocked": n_blocked,
                    "outcomes": {o: sum(1 for r in rows if r.get("outcome") == o)
                                 for o in sorted({r.get("outcome", "") for r in rows})},
                    "which_arm": ARM_LOG_ONLY_GOLDEN,
                    "not_evaluated_texts": primary["traffic"]["not_evaluated_texts"]},
        "arms": harvests,
        "metric_inventory": inv,
        "score_half": score_half,
        "score_datapoints": primary["score_datapoints"],
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
            "sealed_units_in_this_claim_group": _sealed_units(),
            "decision_diamond_readable": log_only["per_metric"].get(
                "LogOnlyDecisionFlips", {}).get("published_for_this_gateway"),
            "other_surfaces_restore_the_join": {
                "application_logs": bool(app_logs.get("score_present")
                                         and app_logs.get("identity_present")),
                "spans": bool(spans.get("score_present") and spans.get("identity_present")),
            },
            "relation_to_dev_p4_01": (
                "DEV-P4-01 recorded that no surface publishes a numeric guardrail score. Its "
                "ABSOLUTE reading is REFUTED and the refutation is measured, not argued: "
                "`AWS/Bedrock-AgentCore` publishes `ConfidenceScore` with real values (over "
                "2026-08-11..12, read by get_metric_statistics over the full day rather than "
                "through the ListMetrics index: 21 datapoints, Average 0.77..0.84, Minimum "
                "0.4..0.6, Maximum 0.8..1.0, SampleCount 11..34) and `ConfidenceThreshold` "
                "alongside it. What survives of DEV-P4-01 is the CONDITIONAL reading, which "
                "is what this case measures: a published score is a one-minute AGGREGATE, so "
                "whether a reader can attribute it to the labelled request that produced it "
                "depends on the request rate. That is half (b), and the spaced arm measures "
                "the rate at which the attribution becomes possible "
                "(`feedback_constraints_are_choices`: label the failure conditional and name "
                "the condition). DEV-P4-01 is amended, not deleted — and F1-18's "
                "'not measurable' framing inherits the same correction"),
        },
    }

    out = P.emit(CASE, rec, payload, store)
    print(f"\n{CASE}: {rec['verdict']}  ->  {out}")
    for key, h in harvests.items():
        sd, ih = h["score_datapoints"], h["identity_half"]
        print(f"  {key:22s} [{h['engine_mode']:8s}] "
              f"evaluated {h['traffic']['n_evaluated']}/{h['traffic']['n_rows']}  "
              f"score series with a datapoint in our buckets: "
              f"{sd['n_score_series_with_a_datapoint_in_our_buckets']}"
              f"/{sd['n_score_series_this_gateway']}  "
              f"score series at one request per datapoint: "
              f"{len(ih['per_request_score_series'])}  "
              f"joinable={h['joinable']}"
              + ("   (not scored — excluded from the verdict)" if not h["arm"]["scored"] else ""))
    print(f"  score half:    "
          f"{'a score series published a VALUE in our buckets' if primary['score_datapoints']['readable'] else 'NO score series carried a datapoint in our buckets'}"
          f"; name in the namespace index: {score_half['score_metric_name_exists']}"
          f"  ({score_half['failure_character'] or 'n/a'})")
    print(f"  identity half: {len(identity_half['per_request_score_series'])} SCORE series of "
          f"{len(identity_half['any_series_per_request'])} per-request series "
          f"({identity_half['n_series_read']} read) reach one request per datapoint"
          f"  ({identity_half['failure_character'] or 'n/a'})")
    print(f"  app logs: {app_logs.get('n_events_in_window', 'n/a')} events, "
          f"spans: {spans.get('n_rows', 'n/a')} rows, "
          f"span join by request id: {spans.get('n_spans_naming_one_of_our_request_ids', 'n/a')}")
    if failed_guards:
        print(f"  FAILED GUARDS: {', '.join(failed_guards)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
