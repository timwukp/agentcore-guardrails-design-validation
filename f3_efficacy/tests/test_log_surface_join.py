"""F3-10's log-surface supplementary read: the join, the sweep direction, and the guards.

Why this file exists
--------------------
F3-10 recorded the gateway's APPLICATION_LOGS surface as carrying no score and no identity.
Both readings were artefacts of the checks, not of the surface:

  * the numeric census that existed so that half (a) could not be a word game collected `int`
    and `float` values only, and the score is published as a JSON **string** — `"0.8000"`. A
    guard blind by its own type filter is `feedback_vacuous_test_check` exactly.
  * identity was measured as "does an event contain one of our CORPUS ids". The corpus id is
    not on that surface; `request_id` is, on every policy event and every harness row.

`08b_log_surface_join.py` is the read those two defects cost, and it makes claims a reader
will act on: that §7.1 step 3's confusion matrix IS buildable from the logs, that it is
buildable only for detections, and that the threshold sweep therefore only runs upwards. Each
of those has to fail here when the data says otherwise, or it is prose.

What each group of arms holds
-----------------------------
* `_looks_numeric` / `_numeric_keys` — the string-score census. The parametrised arm plants a
  literal `"0.8000"` at the real key path the gateway uses and asserts the walker finds it;
  the mutation arm asserts the OLD behaviour (no `str_acc`) does not, so the fix is pinned by
  a test that can distinguish the two.
* `_join` — totality. Unmatched events, duplicate request_ids and label rows missing from the
  logs each have an arm, because a join that silently drops rows would let a coincidence look
  like a linkage.
* `_per_arm` — the confusion matrix and `decision_agrees_with_score`, including an arm where
  they DISAGREE, since that is the case where a reader's answer depends on which field they
  used.
* `_sweep_direction` — the claim with the most leverage. Candidates below the configured
  threshold must land in `not_evaluable` and the boundary (`t == threshold`) must be
  evaluable, because an off-by-one there is the difference between "you can reproduce your
  current operating point" and "you cannot".
* `_shadow` — a shadow denial must be established per request (log DENY **and** the same
  request allowed), never from two counts over disjoint sets.
* `_reconcile` — must return False when the metric Sum and the logged sum disagree, and must
  not silently pass when there is nothing to compare.
* `_guards` — every guard flipped false one at a time, plus the guard-name set itself, so a
  guard that is dropped from the dict is a failure rather than a vacuous `all()`.
* the source arms — that this file writes no `verdict` key, mutates nothing, and does not
  print F3-10's sealed oracle.

Offline, $0. No AWS client is constructed; `conftest.no_aws` blocks the network.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(stem: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "f3_efficacy" / stem)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load("08b_log_surface_join.py", "f3_log_surface_join_under_test")

SCORE_PATH = ("body.policy.guardrailFindings"
              ".grx_f3_10_scored_r20260810T130945Z-ystne00vhh.contentFilter[].score")


# ---------------------------------------------------------------------------
# helpers: the smallest thing shaped like a real gateway policy event
# ---------------------------------------------------------------------------

def _event(*, rid: str, decision: str, score: str | None = None, filt: str = "HATE",
           policy_id: str = "grx_f3_10_scored_r20260810T130945Z-ystne00vhh",
           policy_mode: str = "ENFORCE", severity: str = "ERROR",
           is_error: bool | None = None, latency_ms: int = 400) -> dict:
    """One decoded APPLICATION_LOGS event, shaped like the ones in `evidence/`.

    `score` is a STRING because that is what the service publishes. Passing a float here would
    make every arm below pass against a record the gateway never emits
    (`feedback_verify_against_real_artifact`).
    """
    policy: dict = {"decision": decision, "latencyMs": latency_ms,
                    "determiningPolicies": [policy_id]}
    if score is not None:
        policy["guardrailFindings"] = {policy_id: {
            "effect": "FORBID", "policyMode": policy_mode,
            "contentFilter": [{"score": score, "filter": filt}]}}
    return {"request_id": rid, "severityText": severity,
            "body": {"isError": (decision == "DENY") if is_error is None else is_error,
                     "log": "Policy evaluation denied request" if decision == "DENY"
                            else "Policy evaluation completed",
                     "policy": policy}}


def _label(*, arm: str, truth: str, outcome: str, denied: bool, bucket: int = 1786504380) -> dict:
    return {"arm": arm, "trial": "t0000", "truth": truth, "corpus_label": truth.upper(),
            "corpus_id": "deadbeef", "outcome": outcome, "denied": denied, "evaluated": True,
            "bucket_s": bucket}


def _log_only_pair() -> tuple[list[dict], dict[str, dict]]:
    """One shadow-denied positive and one allowed negative: the minimum §7.1 step 3 needs."""
    events = [_event(rid="r-pos", decision="DENY", score="0.8000"),
              _event(rid="r-neg", decision="ALLOW")]
    labels = {"r-pos": _label(arm="log_only_golden_set", truth="positive", outcome="allowed",
                              denied=False),
              "r-neg": _label(arm="log_only_golden_set", truth="negative", outcome="allowed",
                              denied=False)}
    return events, labels


# ---------------------------------------------------------------------------
# the census: a number in a string is still a number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("0.8000", True), ("1.0000", True), ("0", True), ("-3e2", True), ("  0.4 ", True),
    ("HATE", False), ("", False), ("0.8 (high)", False), ("None", False),
])
def test_looks_numeric_uses_float_not_a_regex(value, expected):
    assert B._looks_numeric(value) is expected


def test_the_census_finds_a_score_published_as_a_string():
    """The exact defect: the score lives at a real key path, as a string, and must be seen."""
    ev, _ = _log_only_pair()
    numeric: dict = {}
    strings: dict = {}
    B._numeric_keys(ev[0], acc=numeric, str_acc=strings)
    assert SCORE_PATH in strings, strings
    assert strings[SCORE_PATH] == "0.8000"
    # And it is NOT a number, which is itself the finding a reader needs: Logs Insights
    # arithmetic on this field needs a cast.
    assert SCORE_PATH not in numeric
    assert "body.policy.latencyMs" in numeric


def test_without_str_acc_the_census_is_blind_to_it():
    """The mutation that pins the fix: the old call shape must still miss the score.

    If this passed with the score present, the arm above would prove nothing — it would be
    green under both the broken and the fixed walker.
    """
    ev, _ = _log_only_pair()
    numeric = B._numeric_keys(ev[0])
    assert SCORE_PATH not in numeric
    assert [k for k in numeric if B.SCORE_NAME_RE.search(k)] == []


def test_the_decoder_reports_the_score_path_as_a_string_path():
    ev, _ = _log_only_pair()
    decoded = B._decode([{"message": json.dumps(e)} for e in ev])
    assert decoded["score_valued_key_paths"] == [SCORE_PATH]
    assert decoded["score_key_paths_are_strings"] == [SCORE_PATH]
    assert decoded["score_key_paths_are_numbers"] == []
    assert len(decoded["policy_events"]) == 2
    assert decoded["n_unparsed"] == 0


def test_the_decoder_counts_an_unparsable_event_instead_of_crashing():
    decoded = B._decode([{"message": "not json"}, {"message": json.dumps(_event(
        rid="r", decision="ALLOW"))}])
    assert decoded["n_unparsed"] == 1
    assert len(decoded["policy_events"]) == 1


def test_scores_in_returns_empty_for_a_clean_request_rather_than_a_zero():
    """`[]` and `[{"score": 0.0}]` are different facts and the sweep claim rests on which."""
    ev = _event(rid="r", decision="ALLOW")
    assert B._scores_in(ev["body"]["policy"]) == []


def test_scores_in_records_an_unparsable_score_as_none_not_as_zero():
    ev = _event(rid="r", decision="DENY", score="high")
    got = B._scores_in(ev["body"]["policy"])
    assert len(got) == 1
    assert got[0]["score"] is None
    assert got[0]["raw_score"] == "high"
    assert got[0]["raw_score_type"] == "str"


# ---------------------------------------------------------------------------
# the join has to be total
# ---------------------------------------------------------------------------

def test_the_join_matches_every_event_to_its_label():
    ev, labels = _log_only_pair()
    join = B._join(ev, labels)
    assert join["n_matched"] == 2
    assert join["n_unmatched"] == 0
    assert join["duplicate_request_ids"] == []
    assert join["n_label_rows_not_seen_in_the_logs"] == 0
    pos = next(r for r in join["rows"] if r["truth"] == "positive")
    assert pos["log_decision"] == "DENY"
    assert pos["client_outcome"] == "allowed"
    assert pos["n_scores"] == 1


def test_an_event_with_no_label_is_reported_unmatched_not_dropped():
    ev, labels = _log_only_pair()
    ev.append(_event(rid="r-stranger", decision="DENY", score="1.0000"))
    join = B._join(ev, labels)
    assert join["n_unmatched"] == 1
    assert join["unmatched"][0]["request_id"] == "r-stranger"
    assert B._guards(join=join, decoded={"score_valued_key_paths": [SCORE_PATH]},
                     per_arm={"a": {"decision_agrees_with_score": True}},
                     reconcile={"all_agree": True}, labels={"n": 2},
                     window={"n_arms": 3})["join_is_total"] is False


def test_a_label_row_absent_from_the_logs_fails_its_own_guard():
    ev, labels = _log_only_pair()
    labels["r-never-logged"] = _label(arm="log_only_golden_set", truth="positive",
                                      outcome="allowed", denied=False)
    join = B._join(ev, labels)
    assert join["n_label_rows_not_seen_in_the_logs"] == 1
    guards = B._guards(join=join, decoded={"score_valued_key_paths": [SCORE_PATH]},
                       per_arm={"a": {"decision_agrees_with_score": True}},
                       reconcile={"all_agree": True}, labels={"n": 3}, window={"n_arms": 3})
    assert guards["every_label_row_appears_in_the_logs"] is False
    assert guards["join_is_total"] is True


def test_two_events_for_one_request_id_are_reported_as_a_duplicate():
    ev, labels = _log_only_pair()
    ev.append(_event(rid="r-pos", decision="DENY", score="0.6000"))
    join = B._join(ev, labels)
    assert join["duplicate_request_ids"] == ["r-pos"]
    assert B._guards(join=join, decoded={"score_valued_key_paths": [SCORE_PATH]},
                     per_arm={"a": {"decision_agrees_with_score": True}},
                     reconcile={"all_agree": True}, labels={"n": 2},
                     window={"n_arms": 3})["join_key_is_unique"] is False


def test_an_empty_join_is_never_reported_as_total():
    """A read that matched nothing must not look clean (`feedback_zero_file_scan_is_error`)."""
    join = B._join([], {})
    assert join["n_matched"] == 0
    assert B._guards(join=join, decoded={"score_valued_key_paths": [SCORE_PATH]}, per_arm={},
                     reconcile={"all_agree": True}, labels={"n": 0},
                     window={"n_arms": 3})["join_is_total"] is False


# ---------------------------------------------------------------------------
# the confusion matrix
# ---------------------------------------------------------------------------

def test_the_confusion_matrix_is_built_from_whether_a_score_was_logged():
    ev, labels = _log_only_pair()
    per_arm = B._per_arm(B._join(ev, labels)["rows"])
    got = per_arm["log_only_golden_set"]
    assert got["confusion_at_configured_threshold"] == {"tp": 1, "fp": 0, "fn": 0, "tn": 1}
    assert got["precision"] == 1.0
    assert got["recall"] == 1.0
    assert got["scores_by_truth"] == {"negative": 0, "positive": 1}
    assert got["score_sum"] == 0.8
    assert got["decision_agrees_with_score"] is True
    # The mode the LOG carries is the POLICY's, and it says ENFORCE for a LOG_ONLY pass.
    assert got["policy_modes_logged"] == ["ENFORCE"]


def test_a_false_positive_is_counted_when_a_clean_request_is_scored():
    ev = [_event(rid="r-neg", decision="DENY", score="0.4000")]
    labels = {"r-neg": _label(arm="log_only_golden_set", truth="negative", outcome="allowed",
                              denied=False)}
    got = B._per_arm(B._join(ev, labels)["rows"])["log_only_golden_set"]
    assert got["confusion_at_configured_threshold"] == {"tp": 0, "fp": 1, "fn": 0, "tn": 0}
    assert got["precision"] == 0.0
    assert got["recall"] is None      # no positive was sent: not 0.0, which would be a claim


def test_a_disagreement_between_the_decision_and_the_score_is_reported():
    """If DENY and 'a score was logged' ever came apart, the matrix would depend on the choice.

    Not hypothetical hygiene: a reader following §7.1 would naturally count denials, and this
    read counts scores. The guard exists so that the two being the same thing is measured.
    """
    ev = [_event(rid="r-pos", decision="DENY", score=None)]
    labels = {"r-pos": _label(arm="log_only_golden_set", truth="positive", outcome="allowed",
                              denied=False)}
    per_arm = B._per_arm(B._join(ev, labels)["rows"])
    assert per_arm["log_only_golden_set"]["decision_agrees_with_score"] is False
    assert B._guards(join={"n_matched": 1, "n_unmatched": 0, "duplicate_request_ids": [],
                           "n_label_rows_not_seen_in_the_logs": 0},
                     decoded={"score_valued_key_paths": [SCORE_PATH]}, per_arm=per_arm,
                     reconcile={"all_agree": True}, labels={"n": 1},
                     window={"n_arms": 3})["decision_agrees_with_score_in_every_arm"] is False


def test_each_arm_is_summarised_separately():
    ev, labels = _log_only_pair()
    ev.append(_event(rid="r-spaced", decision="DENY", score="0.8000"))
    labels["r-spaced"] = _label(arm="active_one_per_minute", truth="positive",
                                outcome="policy_denied", denied=True, bucket=1786504320)
    per_arm = B._per_arm(B._join(ev, labels)["rows"])
    assert set(per_arm) == {"log_only_golden_set", "active_one_per_minute"}
    assert per_arm["active_one_per_minute"]["buckets"] == [1786504320]
    assert per_arm["active_one_per_minute"]["client_outcomes"] == {"policy_denied": 1}


# ---------------------------------------------------------------------------
# the sweep only runs upwards — the claim with the most leverage
# ---------------------------------------------------------------------------

def test_candidate_thresholds_below_the_configured_one_are_not_evaluable():
    ev, labels = _log_only_pair()
    sweep = B._sweep_direction(B._join(ev, labels)["rows"], 0.2)
    assert sweep["not_evaluable"] == [0.05, 0.1, 0.15]
    assert sweep["evaluable"][0] == 0.2, "the configured threshold itself must be reproducible"
    assert set(sweep["evaluable"]) | set(sweep["not_evaluable"]) == set(B.CANDIDATE_THRESHOLDS)
    assert not set(sweep["evaluable"]) & set(sweep["not_evaluable"])
    assert sweep["n_requests_with_no_score"] == 1
    assert sweep["n_requests_with_a_score"] == 1


@pytest.mark.parametrize("threshold,n_blocked", [(0.05, 0), (0.2, 3), (0.5, 9), (1.0, 19)])
def test_the_evaluable_set_tracks_the_configured_threshold(threshold, n_blocked):
    """The partition is a function of the CONFIGURED threshold, not of the scores observed.

    A permissive configuration leaves the whole sweep open; a strict one closes most of it.
    That is the actionable half of the finding, so it is pinned at four points rather than one.
    """
    ev, labels = _log_only_pair()
    sweep = B._sweep_direction(B._join(ev, labels)["rows"], threshold)
    assert len(sweep["not_evaluable"]) == n_blocked
    assert sweep["configured_threshold"] == threshold


def test_the_candidate_grid_is_fixed_before_the_scores_are_read():
    """Pinned so that no future edit can let the observed values choose the question."""
    assert B.CANDIDATE_THRESHOLDS[0] == 0.05
    assert B.CANDIDATE_THRESHOLDS[-1] == 1.0
    assert len(B.CANDIDATE_THRESHOLDS) == 20
    src = Path(B.__file__).read_text(encoding="utf-8")
    grid = src.split("CANDIDATE_THRESHOLDS = ")[1].split("\n")[0]
    assert "score" not in grid and "row" not in grid, grid


# ---------------------------------------------------------------------------
# a shadow denial is established per request, not from two counts
# ---------------------------------------------------------------------------

def test_a_shadow_denial_needs_the_same_request_to_be_logged_deny_and_allowed():
    ev, labels = _log_only_pair()
    got = B._shadow(B._join(ev, labels)["rows"])
    assert got["n_shadow_denials"] == 1
    assert got["n_real_denials"] == 0
    assert got["shadow_arms"] == {"log_only_golden_set": 1}
    assert got["shadow_severity_texts"] == {"ERROR": 1}
    assert got["shadow_is_error_flag"] == {True: 1}
    assert got["shadow_policy_modes_logged"] == {"ENFORCE": 1}


def test_a_real_denial_is_not_counted_as_a_shadow_one():
    ev = [_event(rid="r-spaced", decision="DENY", score="0.8000")]
    labels = {"r-spaced": _label(arm="active_one_per_minute", truth="positive",
                                 outcome="policy_denied", denied=True)}
    got = B._shadow(B._join(ev, labels)["rows"])
    assert got["n_shadow_denials"] == 0
    assert got["n_real_denials"] == 1


def test_a_denied_client_and_a_separate_allowed_client_do_not_make_a_shadow_denial():
    """Two counts over disjoint request sets must not add up to a per-request claim."""
    ev = [_event(rid="r-a", decision="DENY", score="0.8000"),
          _event(rid="r-b", decision="ALLOW")]
    labels = {"r-a": _label(arm="x", truth="positive", outcome="policy_denied", denied=True),
              "r-b": _label(arm="x", truth="negative", outcome="allowed", denied=False)}
    assert B._shadow(B._join(ev, labels)["rows"])["n_shadow_denials"] == 0


# ---------------------------------------------------------------------------
# the cross-surface reconciliation
# ---------------------------------------------------------------------------

def _result_with_metric(*, arm: str, bucket: int, total: float, sample_count: float) -> dict:
    return {"arms": {arm: {
        "window": {"t0": 1.0, "t1": 2.0},
        "identity_half": {"per_series": [
            {"name": "ConfidenceScore",
             "datapoints": [{"bucket_s": bucket, "sum": total, "sample_count": sample_count}]},
            {"name": "DenyDecisions",
             "datapoints": [{"bucket_s": bucket, "sum": 99.0, "sample_count": 99.0}]},
        ]}}}}


def test_the_reconciliation_agrees_when_the_two_surfaces_agree():
    per_arm = {"log_only_golden_set": {"buckets": [1786504380], "score_sum": 24.2,
                                       "n_score_values": 30}}
    got = B._reconcile(_result_with_metric(arm="log_only_golden_set", bucket=1786504380,
                                           total=24.200000000000010, sample_count=30.0), per_arm)
    assert got["all_agree"] is True
    assert got["checked"] == 1
    assert got["per_arm"]["log_only_golden_set"]["metric_sum"] == 24.2


@pytest.mark.parametrize("log_sum,log_n", [(24.3, 30), (24.2, 29)])
def test_the_reconciliation_disagrees_when_either_number_moves(log_sum, log_n):
    per_arm = {"log_only_golden_set": {"buckets": [1786504380], "score_sum": log_sum,
                                       "n_score_values": log_n}}
    got = B._reconcile(_result_with_metric(arm="log_only_golden_set", bucket=1786504380,
                                           total=24.2, sample_count=30.0), per_arm)
    assert got["all_agree"] is False
    assert got["per_arm"]["log_only_golden_set"]["agrees"] is False


def test_the_reconciliation_ignores_datapoints_from_buckets_this_arm_did_not_own():
    """A neighbouring case's traffic in another bucket must not be summed into this arm."""
    per_arm = {"a": {"buckets": [1786504380], "score_sum": 0.8, "n_score_values": 1}}
    result = _result_with_metric(arm="a", bucket=1786504380, total=0.8, sample_count=1.0)
    result["arms"]["a"]["identity_half"]["per_series"][0]["datapoints"].append(
        {"bucket_s": 1786500000, "sum": 500.0, "sample_count": 500.0})
    got = B._reconcile(result, per_arm)
    assert got["all_agree"] is True
    assert got["per_arm"]["a"]["buckets_compared"] == [1786504380]


def test_the_reconciliation_does_not_pass_on_an_empty_comparison():
    """`all([])` is True, so an arm whose buckets are unknown must not vote."""
    got = B._reconcile(_result_with_metric(arm="a", bucket=1, total=1.0, sample_count=1.0),
                       {"a": {"buckets": [], "score_sum": 0.0, "n_score_values": 0}})
    assert got["checked"] == 0
    assert got["all_agree"] is False


def test_a_dimension_combination_that_disagrees_with_its_siblings_is_reported():
    per_arm = {"a": {"buckets": [7], "score_sum": 1.0, "n_score_values": 1}}
    result = _result_with_metric(arm="a", bucket=7, total=1.0, sample_count=1.0)
    result["arms"]["a"]["identity_half"]["per_series"].append(
        {"name": "ConfidenceScore",
         "datapoints": [{"bucket_s": 7, "sum": 2.0, "sample_count": 1.0}]})
    got = B._reconcile(result, per_arm)
    assert got["per_arm"]["a"]["dimension_combinations_disagreeing"] == [7]


# ---------------------------------------------------------------------------
# the guards, one at a time
# ---------------------------------------------------------------------------

_OK_ARGS = {
    "join": {"n_matched": 61, "n_unmatched": 0, "duplicate_request_ids": [],
             "n_label_rows_not_seen_in_the_logs": 0},
    "decoded": {"score_valued_key_paths": [SCORE_PATH]},
    "per_arm": {"a": {"decision_agrees_with_score": True}},
    "reconcile": {"all_agree": True},
    "labels": {"n": 122},
    "window": {"n_arms": 3},
}


def test_all_seven_guards_pass_on_a_clean_read():
    guards = B._guards(**_OK_ARGS)
    assert set(guards) == set(B.GUARDS)
    assert all(guards.values()), guards


@pytest.mark.parametrize("guard,patch", [
    ("join_is_total", {"join": {**_OK_ARGS["join"], "n_unmatched": 1}}),
    ("join_key_is_unique", {"join": {**_OK_ARGS["join"], "duplicate_request_ids": ["r"]}}),
    ("every_label_row_appears_in_the_logs",
     {"join": {**_OK_ARGS["join"], "n_label_rows_not_seen_in_the_logs": 4}}),
    ("score_key_path_found", {"decoded": {"score_valued_key_paths": []}}),
    ("decision_agrees_with_score_in_every_arm",
     {"per_arm": {"a": {"decision_agrees_with_score": False}}}),
    ("logs_reconcile_with_metrics", {"reconcile": {"all_agree": False}}),
    ("window_covers_every_arm", {"window": {"n_arms": 2}}),
])
def test_each_guard_can_come_back_false(guard, patch):
    guards = B._guards(**{**_OK_ARGS, **patch})
    assert guards[guard] is False
    assert [k for k, v in guards.items() if not v] == [guard]


def test_an_empty_per_arm_map_fails_the_agreement_guard_rather_than_passing_vacuously():
    assert B._guards(**{**_OK_ARGS, "per_arm": {}})[
        "decision_agrees_with_score_in_every_arm"] is False


def test_no_label_at_all_fails_the_coverage_guard():
    assert B._guards(**{**_OK_ARGS, "labels": {"n": 0}})[
        "every_label_row_appears_in_the_logs"] is False


# ---------------------------------------------------------------------------
# inputs read from files, not restated
# ---------------------------------------------------------------------------

def test_the_window_is_the_union_of_every_arm_window():
    got = B._window_from_recorded_result({"arms": {
        "a": {"window": {"t0": 100.0, "t1": 200.0}},
        "b": {"window": {"t0": 300.0, "t1": 400.0}},
        "c": {"window": {"t0": 50.0, "t1": 60.0}}}})
    assert got == {"t0": 50.0, "t1": 400.0, "n_arms": 3}


@pytest.mark.parametrize("result", [
    {},
    {"arms": {}},
    {"arms": {"a": {"window": {}}}},
    {"arms": {"a": {"window": {"t0": "not a number", "t1": 2.0}}}},
])
def test_an_unusable_result_file_raises_instead_of_reading_a_default_window(result):
    with pytest.raises(B.ConfigError):
        B._window_from_recorded_result(result)


def test_a_duplicate_request_id_across_checkpoints_raises(tmp_path, monkeypatch):
    """The join key has to be unique across ARMS, not just within one.

    Two arms sharing a request_id would silently attribute one arm's score to the other's
    label, and the arms are the whole comparison.
    """
    ck = tmp_path / "results" / "checkpoints"
    ck.mkdir(parents=True)
    for key in B.ARM_KEYS:
        (ck / f"F3-10__{key}.json").write_text(json.dumps({"done": {
            "t0000": {"request_id": "same-for-every-arm", "truth": "positive"}}}))
    monkeypatch.setattr(B, "CHECKPOINTS", ck)
    monkeypatch.setattr(B, "ROOT", tmp_path)
    with pytest.raises(B.ConfigError, match="not unique"):
        B._labels_from_checkpoints()


def test_a_row_without_a_request_id_raises_rather_than_shrinking_the_label_set(tmp_path,
                                                                              monkeypatch):
    ck = tmp_path / "results" / "checkpoints"
    ck.mkdir(parents=True)
    for i, key in enumerate(B.ARM_KEYS):
        (ck / f"F3-10__{key}.json").write_text(json.dumps({"done": {
            "t0000": {"request_id": f"rid-{i}", "truth": "positive"},
            "t0001": {"truth": "negative"}}}))
    monkeypatch.setattr(B, "CHECKPOINTS", ck)
    monkeypatch.setattr(B, "ROOT", tmp_path)
    with pytest.raises(B.ConfigError, match="no request_id"):
        B._labels_from_checkpoints()


def test_a_missing_checkpoint_raises(tmp_path, monkeypatch):
    ck = tmp_path / "results" / "checkpoints"
    ck.mkdir(parents=True)
    monkeypatch.setattr(B, "CHECKPOINTS", ck)
    monkeypatch.setattr(B, "ROOT", tmp_path)
    with pytest.raises(B.ConfigError, match="does not exist"):
        B._labels_from_checkpoints()


def test_the_configured_threshold_comes_from_the_parent_case_not_from_a_literal_here():
    """One statement of the threshold. A copy could not be wrong in a way the file reveals."""
    assert B.GUARDRAIL_THRESHOLD == B._parent.GUARDRAIL_THRESHOLD
    src = Path(B.__file__).read_text(encoding="utf-8")
    assert 'GUARDRAIL_THRESHOLD = "' not in src, "the threshold must be imported, not restated"


# ---------------------------------------------------------------------------
# what this file is not allowed to be
# ---------------------------------------------------------------------------

def test_the_read_writes_no_verdict_and_declares_its_kind():
    src = Path(B.__file__).read_text(encoding="utf-8")
    assert '"kind": "SUPPLEMENTARY_READ"' in src
    assert '"verdict"' not in src
    assert "O.evaluate" not in src and "import oracle" not in src


def test_the_read_mutates_nothing():
    src = Path(B.__file__).read_text(encoding="utf-8")
    for forbidden in ("create_policy", "delete_policy", "update_gateway", "set_engine_mode",
                      "call_tool", "put_metric"):
        assert forbidden not in src, forbidden


def test_the_read_does_not_print_the_parent_sealed_oracle():
    """`P.dry_run_banner` prints the oracle for the case id it is given, so it is never CALLED.

    The name still appears in a comment saying why — so the check is for the call, not the word.
    """
    src = Path(B.__file__).read_text(encoding="utf-8")
    assert "P.dry_run_banner(" not in src
    assert "dry_run_banner" in src, "the reason it is avoided should stay written down"
    assert "sealed oracle" in src


def test_the_log_field_names_are_named_once_each():
    src = Path(B.__file__).read_text(encoding="utf-8")
    body = src.split('"""', 2)[2]
    for literal in ('"guardrailFindings"', '"contentFilter"', '"policyMode"'):
        assert body.count(literal) == 1, (literal, body.count(literal))


def test_the_fetch_follows_next_token():
    """One page was enough for 304 events; a busier window must not truncate silently."""
    body = Path(B.__file__).read_text(encoding="utf-8").split('"""', 2)[2]
    assert "nextToken" in body


# ---------------------------------------------------------------------------
# the sealed claim group: derived from claims/triage.csv, not typed into the payload
# ---------------------------------------------------------------------------

def test_the_sealed_unit_group_is_read_from_the_register_and_is_not_empty():
    got = B._sealed_units()
    assert got["n"] == len(got["unit_ids"]) >= 1
    assert got["unit_ids"] == sorted(set(got["unit_ids"])), "no duplicates, sorted"
    assert "triage.csv" in got["source"]


def test_every_derived_unit_actually_cites_the_case_in_the_register():
    """Asserted against the register itself, so the test cannot inherit the reader's bug."""
    import csv
    with (ROOT / "claims" / "triage.csv").open(encoding="utf-8", newline="") as fh:
        rows = {r["claim_id"]: (r["cases"] or "").split() for r in csv.DictReader(fh)}
    ids = set(B._sealed_units()["unit_ids"])
    for cid in ids:
        assert B.PARENT_CASE in rows[cid], cid
    missing = {cid for cid, cases in rows.items() if B.PARENT_CASE in cases} - ids
    assert not missing, f"the register cites {B.PARENT_CASE} in rows the reader dropped: {missing}"


def test_the_unit_shared_with_another_case_is_included_and_labelled():
    """The exact row the parent case's hand-written list omitted.

    `C-s7-1-prose-004` is *"use the confidence scores in the logs to build a confusion matrix"* —
    the sentence this whole read is about — and its `cases` cell is `"F3-10 F3-9"`. A membership
    test that compares the whole cell to the case id drops precisely this row, which is why the
    reader splits on whitespace and why the sharing is reported rather than flattened away.
    """
    got = B._sealed_units()
    assert "C-s7-1-prose-004" in got["unit_ids"]
    assert got["shared_with_other_cases"]["C-s7-1-prose-004"] == ["F3-9"]


def test_a_whole_cell_comparison_would_have_dropped_a_unit():
    """Mutation check: the bug being guarded against is reproduced, so the guard is not vacuous."""
    import csv
    with (ROOT / "claims" / "triage.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    whole_cell = {r["claim_id"] for r in rows if (r["cases"] or "").strip() == B.PARENT_CASE}
    tokenised = set(B._sealed_units()["unit_ids"])
    assert whole_cell < tokenised, "the two readings must differ, or this test proves nothing"
    assert len(tokenised) - len(whole_cell) >= 1


def test_the_doc_lines_come_from_the_register_rather_than_from_the_finding():
    got = B._sealed_units()
    assert got["doc_lines"], "a unit group with no document line cannot be cited"
    assert all(isinstance(n, int) and n > 0 for n in got["doc_lines"])
    assert got["doc_lines"] == sorted(set(got["doc_lines"]))


def test_a_missing_register_raises_instead_of_publishing_an_empty_group(monkeypatch, tmp_path):
    """Patched on the PARENT module, which is where the reader and its `TRIAGE` path live.

    `B._sealed_units` is the parent's function imported by name, so patching `B.TRIAGE` would
    leave the reader looking at the real register and the test would pass for the wrong reason.
    """
    monkeypatch.setattr(B._parent, "TRIAGE", tmp_path / "absent.csv")
    with pytest.raises(B._parent.ConfigError):
        B._sealed_units()


def test_a_register_that_never_names_the_case_raises(monkeypatch, tmp_path):
    p = tmp_path / "triage.csv"
    p.write_text("claim_id,doc_line,cases\nC-x-1,10,F9-9\n", encoding="utf-8")
    monkeypatch.setattr(B._parent, "TRIAGE", p)
    with pytest.raises(B._parent.ConfigError):
        B._sealed_units()


def test_the_two_files_read_one_register_through_one_function():
    """The point of importing rather than restating: `08b.TRIAGE is 08.TRIAGE`."""
    assert B.TRIAGE is B._parent.TRIAGE
    assert B._sealed_units is B._parent._sealed_units


def test_the_group_is_not_hardcoded_anywhere_in_the_read():
    """The parent's failure mode was a literal list; this file must not grow one back."""
    body = Path(B.__file__).read_text(encoding="utf-8").split('"""', 2)[2]
    assert body.count('"C-s7-1-prose-004"') == 0
    assert "C-s7-1-mermaid-001" not in body
