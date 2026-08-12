#!/usr/bin/env python3
"""F3-10 supplementary read: §7.1 step 3 names the LOGS, and the logs carry a per-request score.

WHY THIS EXISTS, SEPARATELY FROM F3-10
--------------------------------------
F3-10's sealed oracle scopes the question to one surface:

    "TRUE if a per-request score<->label join is recoverable from CloudWatch METRICS ALONE;
     FALSE if 1-minute aggregation destroys the linkage, in which case a reader following 7.1
     cannot compute precision at all"

The measured answer on that surface is FALSE and stands: at 60 requests/minute a `ConfidenceScore`
datapoint aggregates 30 detections into one number, and the labels of those 30 are gone. That
verdict is not reopened here, and this file writes no verdict of its own.

But the DOCUMENT does not name metrics. §7.1 step (3) says:

    "Label results and use the confidence scores IN THE LOGS to build a confusion matrix,
     comparing precision/recall across candidate thresholds."

and the §7.1 diagram node (line 742) says "from logged ConfidenceScores". The log surface is
therefore the surface the reader is actually sent to, and F3-10 recorded it as `scored: False`
with `score_present` and `identity_present` read by two checks that both asked the wrong question:

  * `identity_present` searched each event for one of our CORPUS ids. The corpus id is not on
    this surface. `request_id` is — on every policy event, and on every harness row.
  * the numeric census that was supposed to catch a score published under an unexpected NAME
    collected `int` and `float` values only, and the gateway publishes the score as a JSON
    STRING: `body.policy.guardrailFindings.<policyId>.contentFilter[].score == "0.8000"`. The
    guard that existed to stop half (a) being a word game was blind, by its own type filter, to
    the one field it was looking for (`feedback_vacuous_test_check`).

Both are fixed in `08_score_label_join.py` and pinned by its offline suite. Fixing the instrument
does not retro-fix the reading, and re-running the case would cost 122 fresh requests and two
mode flips to re-measure a verdict that does not change. So this file does the read the log
surface deserved, over the window F3-10 already recorded, and joins it to the labels.

WHAT IT ESTABLISHES, AND WHY EACH PIECE NEEDS A READ RATHER THAN AN ARGUMENT
---------------------------------------------------------------------------
1. `score_is_per_request` — the score is logged once per detection with a `request_id`, so
   the join §7.1 step 3 needs exists. Checked by joining log events to the harness rows: the
   join must be TOTAL (no log policy event unmatched, no double-counted request_id), because a
   partial join would let a coincidence look like a linkage.
2. `score_only_for_detections` — the negatives' ALLOW events carry a policy block with
   `latencyMs` and NO `guardrailFindings`, so a clean request publishes no score at all. This is
   the piece that decides whether step 3's "comparing precision/recall across CANDIDATE
   thresholds" is executable, and in which direction.
3. `sweep_can_only_tighten` — a candidate threshold ABOVE the configured one is recomputable
   from the logged detections; one BELOW it is not, because the requests that would newly be
   caught published no number to compare. Derived from (2) and the configured threshold, and
   reported as the two sets of candidate thresholds rather than as prose.
4. `shadow_denial_is_logged_as_a_denial` — in LOG_ONLY the shadow decision is written as
   `decision: DENY`, `isError: true`, `severityText: ERROR`, `policyMode: ENFORCE`, for requests
   that were ALLOWED and whose tool executed. Established per request by the same join, not
   inferred from a count: each row must be (log DENY, client allowed).
5. `logs_reconcile_with_metrics` — the sum of the per-request logged scores must equal the
   `ConfidenceScore` bucket `Sum` that F3-10 read from CloudWatch, and the count must equal its
   `SampleCount`. Two independent surfaces agreeing to the decimal is what makes (1)-(4)
   attributable to the service rather than to a parsing mistake in either reader.

WHAT IT DOES NOT CLAIM
----------------------
* No verdict. `kind: SUPPLEMENTARY_READ`, no `verdict` key, and it does not print F3-10's sealed
  oracle: that oracle binds F3-10's arm plan and surface, and a banner quoting it would imply a
  standing this file does not have.
* No mutation and no new traffic. It reads a closed window. It cannot re-run an arm, so it cannot
  distinguish "no score is logged for a clean request" from "no score was logged for THESE 30
  clean requests" beyond n=30 in one arm and n=1 in another.
* Nothing about score CALIBRATION quality. That 30 of 30 HATE items and 0 of 30 benign items were
  detected at threshold 0.2 is this corpus at this threshold, not a measurement of the filter.
* Nothing about output filters, other guardrail functions, or other categories. One
  `ContentFilter`/`HATE` policy on `context.input.text` was live.
* The score VALUES are reported as observed. That every one of them lay on a 0.2 grid is stated as
  an observation over 31 detections, not as a claim about the service's quantisation.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
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
# A distinct evidence case id: these records are a later read, not part of F3-10's archive, and
# `EvidenceStore` numbers records per directory.
EVIDENCE_CASE = "F3-10-log-surface"
OUT_NAME = "F3-10_log_surface_join.json"

PARENT_MODULE_NAME = "grx_f3_10b_parent_08_score_label_join"

# The parent case's own helpers, imported rather than restated. `_numeric_keys`, `SCORE_NAME_RE`,
# `PERIOD_S`, `GUARDRAIL_THRESHOLD` and the arm keys all have to mean here exactly what they mean
# there; a copy beside them could drift while both claimed to be reading the same way
# (`feedback_two_numbers_two_claims`).
_parent = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location(
        PARENT_MODULE_NAME, ROOT / "f3_efficacy" / "08_score_label_join.py"))
sys.modules[PARENT_MODULE_NAME] = _parent
_parent.__spec__.loader.exec_module(_parent)

_numeric_keys = _parent._numeric_keys
_looks_numeric = _parent._looks_numeric
SCORE_NAME_RE = _parent.SCORE_NAME_RE
PERIOD_S = _parent.PERIOD_S
HARVEST_SETTLE_S = _parent.HARVEST_SETTLE_S
LOG_EVENT_LIMIT = _parent.LOG_EVENT_LIMIT
GUARDRAIL_THRESHOLD = _parent.GUARDRAIL_THRESHOLD
GUARDRAIL_CATEGORY = _parent.GUARDRAIL_CATEGORY
ARM_KEYS = tuple(a["key"] for a in _parent.ARMS)
ARM_LOG_ONLY_GOLDEN = _parent.ARM_LOG_ONLY_GOLDEN
ARM_ACTIVE_SPACED = _parent.ARM_ACTIVE_SPACED
_tr = _parent._tr
# The sealed claim group is DERIVED in the parent and imported here for the same
# reason every other helper above is: one reader of `claims/triage.csv`, so the two
# files cannot disagree about which units this case answers for.
_sealed_units = _parent._sealed_units

RESULT = ROOT / "results" / "phase1" / f"{PARENT_CASE}.json"
CHECKPOINTS = ROOT / "results" / "checkpoints"
TRIAGE = _parent.TRIAGE

# Candidate thresholds a reader following §7.1 step 3 would sweep. A 0.05 grid over the whole
# range, fixed here BEFORE the scores are read, so "which of these is evaluable" is a question the
# data answers rather than one the data shapes.
CANDIDATE_THRESHOLDS = tuple(round(0.05 * i, 2) for i in range(1, 21))

# The log fields this read depends on, named once. A schema change that renamed any of them would
# make the join silently empty, and an empty join must be an error, not a clean zero
# (`feedback_zero_file_scan_is_error`).
F_POLICY = "policy"
F_DECISION = "decision"
F_FINDINGS = "guardrailFindings"
F_CONTENT_FILTER = "contentFilter"
F_SCORE = "score"
F_FILTER = "filter"
F_EFFECT = "effect"
F_POLICY_MODE = "policyMode"


class ConfigError(RuntimeError):
    """A recorded input this read depends on is missing or unusable. Never a reading."""


# ---------------------------------------------------------------------------
# inputs: the window and the labels, both taken from what F3-10 recorded
# ---------------------------------------------------------------------------

def _window_from_recorded_result(result: dict[str, Any]) -> dict[str, float]:
    """The union of the three arms' windows, read from F3-10's own result file.

    Hardcoding the epoch seconds here would be a second statement of one fact, and the copy could
    not be wrong in a way the file would reveal. The UNION is used rather than the primary arm's
    window because the log read is the one place all three arms can be compared on one surface,
    and the spaced arm's single detection is the sharpest single-request datum in the case.
    """
    arms = result.get("arms") or {}
    if not arms:
        raise ConfigError(f"{RESULT.name} carries no arms block")
    t0s, t1s = [], []
    for key, arm in arms.items():
        w = arm.get("window") or {}
        if not isinstance(w.get("t0"), (int, float)) or not isinstance(w.get("t1"), (int, float)):
            raise ConfigError(f"{RESULT.name} arm {key} has no numeric window t0/t1")
        t0s.append(float(w["t0"]))
        t1s.append(float(w["t1"]))
    return {"t0": min(t0s), "t1": max(t1s), "n_arms": len(arms)}


def _labels_from_checkpoints() -> dict[str, dict[str, Any]]:
    """`request_id` -> ground truth, for every trial of every arm.

    The labels come from the CHECKPOINTS, not from the published result: `results/phase1/*.json`
    is masked for distribution and carries per-arm aggregates, while the checkpoints hold the
    per-trial rows with the `request_id` the log events also carry. A row without a `request_id`
    cannot participate and is counted, not dropped silently.
    """
    out: dict[str, dict[str, Any]] = {}
    missing_rid = 0
    per_arm: Counter = Counter()
    for key in ARM_KEYS:
        path = CHECKPOINTS / f"{PARENT_CASE}__{key}.json"
        if not path.is_file():
            raise ConfigError(f"{path.relative_to(ROOT)} does not exist — run {PARENT_CASE} first")
        body = json.loads(path.read_text(encoding="utf-8"))
        done = body.get("done") or {}
        if not done:
            raise ConfigError(f"{path.relative_to(ROOT)} has an empty `done` map")
        for trial_key, row in done.items():
            rid = row.get("request_id")
            if not rid:
                missing_rid += 1
                continue
            if rid in out:
                raise ConfigError(f"request_id {rid} appears in two rows "
                                  f"({out[rid]['arm']}/{out[rid]['trial']} and {key}/{trial_key}) "
                                  f"— the join key is not unique, so no join built on it means "
                                  f"anything")
            out[rid] = {"arm": key, "trial": trial_key, "truth": row.get("truth"),
                        "corpus_label": row.get("corpus_label"),
                        "corpus_id": row.get("corpus_id"),
                        "outcome": row.get("outcome"), "denied": bool(row.get("denied")),
                        "evaluated": bool(row.get("evaluated")),
                        "bucket_s": row.get("bucket_s")}
            per_arm[key] += 1
    if missing_rid:
        raise ConfigError(f"{missing_rid} checkpoint row(s) carry no request_id — a join over a "
                          f"partial label set would report a coverage it does not have")
    return {"by_request_id": out, "per_arm": dict(per_arm), "n": len(out)}


# ---------------------------------------------------------------------------
# the read
# ---------------------------------------------------------------------------

def _fetch_events(logs, store, *, gateway_id: str, t0: float, t1: float) -> list[dict[str, Any]]:
    """Every APPLICATION_LOGS event over the union window, paginated to exhaustion.

    F3-10's own read passed `limit=LOG_EVENT_LIMIT` and took one page; 304 events fit under 500 so
    nothing was lost there, but a read that would silently truncate on a busier window is a read
    whose coverage is a coincidence (`feedback_second_instance_bugs`). `nextToken` is followed.
    """
    name = _tr.log_group_name(gateway_id)
    events: list[dict[str, Any]] = []
    token = None
    pages = 0
    while True:
        kw: dict[str, Any] = {"logGroupName": name,
                              "startTime": int((t0 - PERIOD_S) * 1000),
                              "endTime": int((t1 + HARVEST_SETTLE_S) * 1000),
                              "limit": LOG_EVENT_LIMIT}
        if token:
            kw["nextToken"] = token
        rec = capture(store, "filter_log_events", logs, **kw)
        if not rec.ok:
            raise ConfigError(f"filter_log_events failed: {rec.error_code}: {rec.error_message}")
        events.extend(rec.response.get("events") or [])
        pages += 1
        token = rec.response.get("nextToken")
        if not token or pages >= 20:
            break
    return events


def _decode(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Decode the events and pull out the policy-evaluation ones, with a full scalar census.

    The census runs over EVERY event, numeric and numeric-string alike, so the claim "the only
    score-valued field on this surface is `contentFilter[].score`" is a statement about an
    enumeration a reader can check, not about a regex that happened to match.
    """
    numeric: dict[str, Any] = {}
    numeric_strings: dict[str, Any] = {}
    kinds: Counter = Counter()
    policy_events: list[dict[str, Any]] = []
    unparsed = 0
    for ev in events:
        msg = ev.get("message") or ""
        try:
            body = json.loads(msg)
        except (ValueError, TypeError):
            unparsed += 1
            continue
        _numeric_keys(body, acc=numeric, str_acc=numeric_strings)
        inner = body.get("body") or {}
        kinds[str(inner.get("log"))[:80]] += 1
        if isinstance(inner.get(F_POLICY), dict):
            policy_events.append(body)
    score_keys = sorted(k for k in (numeric | numeric_strings) if SCORE_NAME_RE.search(k))
    return {"n_events": len(events), "n_unparsed": unparsed,
            "log_line_kinds": dict(kinds.most_common()),
            "numeric_keys_seen": dict(sorted(numeric.items())),
            "numeric_strings_seen": dict(sorted(numeric_strings.items())),
            "score_valued_key_paths": score_keys,
            "score_key_paths_are_strings": sorted(k for k in score_keys if k in numeric_strings),
            "score_key_paths_are_numbers": sorted(k for k in score_keys if k in numeric),
            "policy_events": policy_events}


def _scores_in(policy_block: dict[str, Any]) -> list[dict[str, Any]]:
    """Every content-filter finding in one policy block, flattened.

    Returns `[]` when the block carries no `guardrailFindings` — which is the measurement for a
    clean request, not a missing value, so the caller distinguishes "no finding" from "a finding
    whose score would not parse".
    """
    out = []
    for policy_id, finding in (policy_block.get(F_FINDINGS) or {}).items():
        for cf in finding.get(F_CONTENT_FILTER) or []:
            raw = cf.get(F_SCORE)
            out.append({"policy_id": policy_id, "filter": cf.get(F_FILTER), "raw_score": raw,
                        "score": float(raw) if _looks_numeric(str(raw)) else None,
                        "raw_score_type": type(raw).__name__,
                        "effect": finding.get(F_EFFECT),
                        "policy_mode": finding.get(F_POLICY_MODE)})
    return out


def _join(policy_events: list[dict[str, Any]],
          labels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One row per policy event, carrying the log's reading and the harness's ground truth.

    TOTALITY IS THE POINT. A join that quietly drops the events it cannot match would let a
    coincidence look like a linkage, so unmatched events and duplicate request_ids are collected
    and the caller treats a non-empty either as a failed guard rather than as a footnote.
    """
    rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    seen: Counter = Counter()
    for body in policy_events:
        rid = body.get("request_id")
        pol = (body.get("body") or {}).get(F_POLICY) or {}
        scores = _scores_in(pol)
        lab = labels.get(str(rid))
        base = {"request_id": rid, "log_decision": pol.get(F_DECISION),
                "is_error": bool((body.get("body") or {}).get("isError")),
                "severity_text": body.get("severityText"),
                "latency_ms": pol.get("latencyMs"),
                "determining_policies": pol.get("determiningPolicies"),
                "n_scores": len(scores), "scores": scores}
        if lab is None:
            unmatched.append(base)
            continue
        seen[str(rid)] += 1
        rows.append(base | {"arm": lab["arm"], "truth": lab["truth"],
                            "corpus_label": lab["corpus_label"],
                            "client_outcome": lab["outcome"], "client_denied": lab["denied"],
                            "bucket_s": lab["bucket_s"]})
    return {"rows": rows, "unmatched": unmatched,
            "duplicate_request_ids": sorted(k for k, v in seen.items() if v > 1),
            "n_matched": len(rows), "n_unmatched": len(unmatched),
            "n_label_rows_not_seen_in_the_logs": len(set(labels) - set(seen))}


# ---------------------------------------------------------------------------
# the five things this read establishes
# ---------------------------------------------------------------------------

def _per_arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The confusion matrix at the CONFIGURED threshold, per arm, plus the score distribution.

    "Detected" is `a score was logged for this request`, which is the only predicted-positive
    signal the log surface offers for a LOG_ONLY pass: the decision field says DENY for a shadow
    match too, so the two agree here — and the agreement is reported (`decision_agrees_with_score`)
    rather than assumed, because if they ever disagreed the confusion matrix would depend on which
    one a reader used.
    """
    out: dict[str, Any] = {}
    for arm in sorted({r["arm"] for r in rows}):
        a = [r for r in rows if r["arm"] == arm]
        tp = [r for r in a if r["truth"] == "positive" and r["n_scores"] > 0]
        fn = [r for r in a if r["truth"] == "positive" and r["n_scores"] == 0]
        fp = [r for r in a if r["truth"] == "negative" and r["n_scores"] > 0]
        tn = [r for r in a if r["truth"] == "negative" and r["n_scores"] == 0]
        vals = [s["score"] for r in a for s in r["scores"] if s["score"] is not None]
        denom_p, denom_r = len(tp) + len(fp), len(tp) + len(fn)
        out[arm] = {
            "n_requests": len(a),
            "confusion_at_configured_threshold": {"tp": len(tp), "fp": len(fp),
                                                  "fn": len(fn), "tn": len(tn)},
            "precision": round(len(tp) / denom_p, 4) if denom_p else None,
            "recall": round(len(tp) / denom_r, 4) if denom_r else None,
            "n_scored_requests": len([r for r in a if r["n_scores"] > 0]),
            "n_score_values": len(vals),
            "score_sum": round(sum(vals), 6),
            "score_min": min(vals) if vals else None,
            "score_max": max(vals) if vals else None,
            "score_histogram": {str(k): v for k, v in
                                sorted(Counter(s["raw_score"] for r in a
                                               for s in r["scores"]).items())},
            "scores_by_truth": {t: len([1 for r in a if r["truth"] == t and r["n_scores"] > 0])
                                for t in sorted({r["truth"] for r in a})},
            "decision_agrees_with_score": all((r["log_decision"] == "DENY") == (r["n_scores"] > 0)
                                              for r in a),
            "client_outcomes": dict(Counter(r["client_outcome"] for r in a).most_common()),
            "log_decisions": dict(Counter(r["log_decision"] for r in a).most_common()),
            "policy_modes_logged": sorted({s["policy_mode"] for r in a for s in r["scores"]
                                           if s["policy_mode"]}),
            "buckets": sorted({r["bucket_s"] for r in a if r["bucket_s"] is not None}),
        }
    return out


def _sweep_direction(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """Which of §7.1 step 3's "candidate thresholds" a reader can actually recompute.

    A candidate ABOVE the configured threshold is recomputable: every request that could clear it
    already published a number, so reclassifying is arithmetic on data in hand. A candidate BELOW
    it is not: the requests that would newly be caught are exactly the ones that published no
    number, and their scores are unknown and unbounded within `[0, configured)`. This is the whole
    consequence of `score_only_for_detections`, and it is reported as two sets so nobody has to
    take the sentence on trust.
    """
    scored = [s["score"] for r in rows for s in r["scores"] if s["score"] is not None]
    unscored = [r for r in rows if r["n_scores"] == 0]
    evaluable = [t for t in CANDIDATE_THRESHOLDS if t >= threshold]
    return {
        "configured_threshold": threshold,
        "candidate_thresholds_offered": list(CANDIDATE_THRESHOLDS),
        "evaluable": evaluable,
        "not_evaluable": [t for t in CANDIDATE_THRESHOLDS if t < threshold],
        "n_requests_with_a_score": len(scored),
        "n_requests_with_no_score": len(unscored),
        "min_logged_score": min(scored) if scored else None,
        "why_above_is_evaluable": ("every request whose score could clear a higher bar already "
                                   "published its number, so raising the bar only reclassifies "
                                   "detections the reader already holds"),
        "why_below_is_not": ("a request that did not clear the configured threshold published no "
                            "score at all, so a reader cannot tell which of them would clear a "
                            "lower bar; their scores are unknown within [0, configured)"),
        "consequence_for_s7_1_step_3": ("the calibration loop can only TIGHTEN. To sweep a "
                                        "threshold downwards a reader must first configure the "
                                        "guardrail at the most permissive value they are willing "
                                        "to consider, calibrate from there, and raise it"),
    }


def _shadow(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Requests the log calls DENY that the client was ALLOWED to complete.

    Per request, by request_id — not "31 DENY log lines and 60 allowed clients", which is two
    counts from disjoint sets and would not establish that any single request was both
    (`feedback_two_numbers_two_claims`).
    """
    shadow = [r for r in rows
              if r["log_decision"] == "DENY" and not r["client_denied"]
              and r["client_outcome"] == "allowed"]
    real = [r for r in rows if r["log_decision"] == "DENY" and r["client_denied"]]
    return {
        "n_shadow_denials": len(shadow),
        "n_real_denials": len(real),
        "shadow_arms": dict(Counter(r["arm"] for r in shadow).most_common()),
        "real_arms": dict(Counter(r["arm"] for r in real).most_common()),
        "shadow_severity_texts": dict(Counter(r["severity_text"] for r in shadow).most_common()),
        "shadow_is_error_flag": dict(Counter(r["is_error"] for r in shadow).most_common()),
        "shadow_policy_modes_logged": dict(Counter(s["policy_mode"] for r in shadow
                                                  for s in r["scores"]).most_common()),
        "shadow_effects_logged": dict(Counter(s["effect"] for r in shadow
                                              for s in r["scores"]).most_common()),
        "reading": ("in LOG_ONLY the shadow decision is written with the same fields a real "
                    "denial uses — decision DENY, isError true, severityText ERROR, and a "
                    "policyMode that names the POLICY's mode, not the engine's — for requests "
                    "that completed. Log-based alerting cannot tell the two apart on these "
                    "fields alone; the discriminator is that the tool-execution line follows."),
    }


def _reconcile(result: dict[str, Any], per_arm: dict[str, Any]) -> dict[str, Any]:
    """Do the per-request logged scores add up to the CloudWatch datapoints F3-10 read?

    This is the cross-surface check that makes the rest attributable. Both readers are fallible in
    different ways — one parses log JSON, the other sums CloudWatch datapoints over dimension
    combinations — so an exact agreement on Sum AND SampleCount, in every bucket, is far stronger
    evidence than either alone. The metric side is READ FROM F3-10'S RESULT FILE, not re-queried:
    the point is whether the two recorded readings agree.
    """
    arms = result.get("arms") or {}
    out: dict[str, Any] = {"per_arm": {}, "all_agree": None, "checked": 0}
    agree = []
    for arm_key, arm in arms.items():
        want_buckets = set((per_arm.get(arm_key) or {}).get("buckets") or [])
        # `ConfidenceScore` publishes the same values under several dimension combinations. Any one
        # of them is the metric's reading; they are collapsed by (bucket -> (sum, sample_count))
        # and a combination that disagreed with its siblings would show up as more than one entry.
        by_bucket: dict[int, set] = {}
        for series in ((arm.get("identity_half") or {}).get("per_series") or []):
            if series.get("name") != "ConfidenceScore":
                continue
            for dp in series.get("datapoints") or []:
                b = dp.get("bucket_s")
                if b in want_buckets:
                    by_bucket.setdefault(b, set()).add(
                        (round(float(dp.get("sum") or 0.0), 6), float(dp.get("sample_count") or 0)))
        metric_sum = round(sum(next(iter(v))[0] for v in by_bucket.values()), 6)
        metric_n = sum(next(iter(v))[1] for v in by_bucket.values())
        log_sum = round((per_arm.get(arm_key) or {}).get("score_sum") or 0.0, 6)
        log_n = (per_arm.get(arm_key) or {}).get("n_score_values") or 0
        ok = (abs(metric_sum - log_sum) < 1e-6 and metric_n == log_n
              and bool(by_bucket) == bool(log_n))
        out["per_arm"][arm_key] = {
            "buckets_compared": sorted(by_bucket),
            "dimension_combinations_disagreeing": sorted(b for b, v in by_bucket.items()
                                                         if len(v) > 1),
            "metric_sum": metric_sum, "log_sum": log_sum,
            "metric_sample_count": metric_n, "n_logged_score_values": log_n,
            "agrees": ok,
        }
        if want_buckets:
            agree.append(ok)
            out["checked"] += 1
    out["all_agree"] = bool(agree) and all(agree)
    return out


# The guards. Every one has to be capable of coming back False, and every one is about whether
# THIS READ means what it says — not about whether the service behaved well.
GUARDS = ("join_is_total", "join_key_is_unique", "every_label_row_appears_in_the_logs",
          "score_key_path_found", "decision_agrees_with_score_in_every_arm",
          "logs_reconcile_with_metrics", "window_covers_every_arm")


def _guards(*, join: dict[str, Any], decoded: dict[str, Any], per_arm: dict[str, Any],
            reconcile: dict[str, Any], labels: dict[str, Any],
            window: dict[str, float]) -> dict[str, bool]:
    return {
        "join_is_total": join["n_unmatched"] == 0 and join["n_matched"] > 0,
        "join_key_is_unique": not join["duplicate_request_ids"],
        # Every arm's rows must appear on this surface. If the log retention window had expired
        # for the earliest arm, the comparison across arms would be over a set nobody named.
        "every_label_row_appears_in_the_logs":
            join["n_label_rows_not_seen_in_the_logs"] == 0 and labels["n"] > 0,
        "score_key_path_found": bool(decoded["score_valued_key_paths"]),
        "decision_agrees_with_score_in_every_arm":
            bool(per_arm) and all(v["decision_agrees_with_score"] for v in per_arm.values()),
        "logs_reconcile_with_metrics": bool(reconcile["all_agree"]),
        "window_covers_every_arm": window["n_arms"] == len(ARM_KEYS),
    }


def _dry_run() -> int:
    # Deliberately NOT `P.dry_run_banner`: that banner prints the sealed oracle for the case id it
    # is given, and this read is not that case. See the module docstring.
    print(f"{PARENT_CASE} supplementary LOG-SURFACE read — dry run, no AWS call, no mutation\n")
    print("§7.1 step (3) says to build the confusion matrix from 'the confidence scores IN THE "
          "LOGS'.")
    print(f"{PARENT_CASE}'s verdict is about CloudWatch METRICS ALONE, per its sealed oracle, and "
          f"is not reopened here.\n")
    print("reads:")
    print(f"  the union of the {len(ARM_KEYS)} arm windows recorded in "
          f"results/phase1/{PARENT_CASE}.json")
    print(f"  the gateway APPLICATION_LOGS group over that window, paginated to exhaustion "
          f"(limit {LOG_EVENT_LIMIT}/page)")
    print(f"  the per-trial labels from results/checkpoints/{PARENT_CASE}__<arm>.json "
          f"({', '.join(ARM_KEYS)})")
    print("\njoins log policy events to labels by `request_id`, then reports:")
    print("  1. the confusion matrix per arm at the configured threshold "
          f"({GUARDRAIL_THRESHOLD}, {GUARDRAIL_CATEGORY})")
    print("  2. whether a clean request publishes a score at all")
    print(f"  3. which of {len(CANDIDATE_THRESHOLDS)} candidate thresholds a reader can recompute")
    print("  4. LOG_ONLY shadow denials, per request, against the client's own outcome")
    print("  5. whether the logged scores sum to the CloudWatch datapoints F3-10 recorded")
    print(f"\nguards ({len(GUARDS)}): {', '.join(GUARDS)}")
    print("mutations: 0 (nothing is created, changed or deleted; the probe policy is long gone)")
    print("traffic: 0 gateway requests — a closed window is re-read, not re-run")
    print("billable: CloudWatch Logs reads only, under $0.01")
    print(f"\nwrites results/phase1/{OUT_NAME} with kind SUPPLEMENTARY_READ and NO verdict key")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(PARENT_CASE, __doc__)
    args = ap.parse_args(argv)
    if args.dry_run:
        return _dry_run()

    if not RESULT.is_file():
        raise ConfigError(f"{RESULT} does not exist — run {PARENT_CASE} first")
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    window = _window_from_recorded_result(result)
    labels = _labels_from_checkpoints()

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    # Resolved for its SIDE EFFECT, not for the value: `A.account_id` is the one place the ID is
    # registered with the masker, and without it `R.mask_text` below cannot mask the ID outside
    # ARN position. This read is the first in the project whose payload carries a bare
    # `account_id` field — the log events publish one, and the numeric-string census now finds it
    # (it is a digit string, so the old census could not have). The redaction gate caught the
    # leak on the first run; this is the fix (DEV-P4-24).
    A.account_id(fc)
    logs = fc.client("logs")
    store = EvidenceStore(run_id, FAMILY, EVIDENCE_CASE)
    store.write_environment()

    # The ledger is the authority on which gateway this is, exactly as the parent case resolves it.
    # `result["gateway_id"]` is compared against it rather than trusted: the recorded window and the
    # log group have to belong to the same gateway, and a mismatch means this read would be joining
    # one gateway's logs to another gateway's labels.
    gw = state.find("gateway", "main")
    if not gw:
        raise ConfigError("the main gateway is not in state.json")
    gateway_id = gw.ids["gateway_id"]
    if result.get("gateway_id") and result["gateway_id"] != gateway_id:
        raise ConfigError(f"{RESULT.name} was written against gateway {result['gateway_id']} but "
                          f"the ledger's main gateway is {gateway_id}")

    print(f"{PARENT_CASE} log-surface read — gateway {gateway_id}, region {region}")
    print(f"  window {window['t0']:.3f}..{window['t1']:.3f} "
          f"({window['t1'] - window['t0']:.1f}s across {window['n_arms']} arms), "
          f"{labels['n']} labelled trials {labels['per_arm']}")

    events = _fetch_events(logs, store, gateway_id=gateway_id, t0=window["t0"], t1=window["t1"])
    decoded = _decode(events)
    print(f"  {decoded['n_events']} log events, {len(decoded['policy_events'])} carrying a policy "
          f"block, {decoded['n_unparsed']} unparsed")
    if not decoded["policy_events"]:
        raise ConfigError("no log event in the window carries a policy block — a join over zero "
                          "events is not a clean zero, it is a failed read")

    join = _join(decoded["policy_events"], labels["by_request_id"])
    per_arm = _per_arm(join["rows"])
    threshold = float(GUARDRAIL_THRESHOLD)
    sweep = _sweep_direction(join["rows"], threshold)
    shadow = _shadow(join["rows"])
    reconcile = _reconcile(result, per_arm)
    guards = _guards(join=join, decoded=decoded, per_arm=per_arm, reconcile=reconcile,
                     labels=labels, window=window)
    failed = sorted(k for k, v in guards.items() if not v)

    payload = {
        "kind": "SUPPLEMENTARY_READ",
        "case_id": PARENT_CASE,
        "family": FAMILY,
        "run_id": run_id,
        "region": region,
        "gateway_id": gateway_id,
        "why_no_verdict": ("F3-10's sealed oracle scopes its question to CloudWatch metrics alone "
                           "and that verdict (FALSE) stands. This read is about the surface §7.1 "
                           "step 3 actually names — the logs — and has no standing to reach a "
                           "verdict on it"),
        "document_under_test": {
            "s7_1_step_3": ("Label results and use the confidence scores in the logs to build a "
                            "confusion matrix, comparing precision/recall across candidate "
                            "thresholds."),
            "s7_1_diagram_node": "3. Build confusion matrix from logged ConfidenceScores; "
                                 "compare candidate thresholds",
            "s6_2_row": "ConfidenceScore / ConfidenceThreshold | Observed score vs. configured "
                        "threshold per evaluation | Threshold calibration (Section 7.1)",
        },
        "sealed_units_citing_this_case": _sealed_units(),
        "window": window,
        "labels": {"n": labels["n"], "per_arm": labels["per_arm"]},
        "log_surface": {k: v for k, v in decoded.items() if k != "policy_events"},
        "join": {k: v for k, v in join.items() if k != "rows"},
        "per_arm": per_arm,
        "sweep_direction": sweep,
        "shadow_denials": shadow,
        "reconciliation_with_metrics": reconcile,
        "guards": guards,
        "guard_names": list(GUARDS),
        "failed_guards": failed,
        "probe": {"category": GUARDRAIL_CATEGORY, "threshold": GUARDRAIL_THRESHOLD,
                  "policy_ids_seen": sorted({s["policy_id"] for r in join["rows"]
                                             for s in r["scores"]})},
        "what_this_does_not_prove": [
            "nothing about a verdict: F3-10's oracle names CloudWatch metrics alone",
            "no re-run: a closed window is re-read, so 'a clean request logs no score' is n=30 in "
            "one arm and n=1 in another, not a property of the service",
            "nothing about output filters, other guardrail functions or other categories — one "
            f"ContentFilter/{GUARDRAIL_CATEGORY} policy on context.input.text was live",
            "nothing about the filter's calibration quality: 30/30 positives and 0/30 negatives "
            f"detected at threshold {GUARDRAIL_THRESHOLD} is this corpus at this threshold",
            "no claim that the observed 0.2 grid of score values is the service's quantisation; "
            "it is what 31 detections showed",
        ],
    }
    text = json.dumps(payload, indent=2, sort_keys=True, default=str, ensure_ascii=False) + "\n"
    out_path = ROOT / "results" / "phase1" / OUT_NAME
    # Masked in `results/` and unmasked in `evidence/`, the same split `P.emit` makes and for the
    # same reason (DEV-P1-13). `P.emit` itself is not used: it would write
    # `results/phase1/F3-10.json` and overwrite a recorded verdict with a read.
    out_path.write_text(R.mask_text(text), encoding="utf-8")
    (store.dir / "analysis.json").write_text(text, encoding="utf-8")
    store.write_summary({"analysis_file": "analysis.json", "case_id": PARENT_CASE,
                         "kind": "SUPPLEMENTARY_READ"})

    for arm, v in per_arm.items():
        c = v["confusion_at_configured_threshold"]
        print(f"  {arm:<22} n={v['n_requests']:<3} tp={c['tp']} fp={c['fp']} fn={c['fn']} "
              f"tn={c['tn']}  scored={v['n_scored_requests']}  Sigma={v['score_sum']}  "
              f"modes_logged={v['policy_modes_logged']}")
    print(f"  score key path(s): {decoded['score_valued_key_paths']} "
          f"(as string: {decoded['score_key_paths_are_strings']})")
    print(f"  sweep: {len(sweep['evaluable'])} of {len(CANDIDATE_THRESHOLDS)} candidate thresholds "
          f"recomputable (>= {threshold}); {len(sweep['not_evaluable'])} are not")
    print(f"  shadow denials: {shadow['n_shadow_denials']} logged DENY but client allowed; "
          f"real denials: {shadow['n_real_denials']}")
    print(f"  log<->metric reconciliation: all_agree={reconcile['all_agree']} "
          f"over {reconcile['checked']} arm(s)")
    print(f"  guards: {len(GUARDS) - len(failed)}/{len(GUARDS)} pass"
          + (f"  FAILED: {', '.join(failed)}" if failed else ""))
    print(f"  wrote {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
