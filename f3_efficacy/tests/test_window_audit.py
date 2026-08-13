"""F3-10's closed-window re-read: the aggregation, the comparison, and the eleven guards.

Why this file exists
--------------------
`08c_window_audit.py` is the instrument §11 of `FINDING-F3-10.md` prescribes: re-read one closed
observation window on a LATER UTC day and check that the stored form of the three readings has not
moved. It exists because that check previously ran as a throwaway script whose output was 63
evidence records and no analysis record — a reading nobody could reproduce.

The instrument caught two of its author's own aggregation mistakes before anything was published,
and both are pinned here rather than left in a docstring:

  * **the quadruple count.** CloudWatch publishes the same observation once per dimension SUBSET it
    rolls up over. On 2026-08-12 four `ConfidenceScore` combinations carried byte-identical
    datapoints (the fully-qualified set, and roll-ups dropping `PolicyEngine`,
    `Policy`/`Category`/`Filter`, or both). Summing across "every score series" therefore reported
    **98.4** against a logged 24.6, and **244** scored requests out of 122 — an impossibility that
    says the aggregation is wrong, not the data.
  * **the quiet foreign series.** Fourteen combinations exist per arm; the ten belonging to other
    cases' probe policies correctly read 0.0 over our window. Counting those as disagreements fails
    the guard for the one reason that is not a defect.

What each group of arms holds
-----------------------------
* `_observation_day` — the day must come from the recorded `t0`/`t1` epochs, never from a date
  STRING in the record. The arm plants a record whose date string disagrees with its epochs and
  asserts the epochs win, because it is the epochs that decide which buckets get re-read.
* `_dim_key` — order-independence, and that a roll-up subset is a DIFFERENT key from the full set.
  If it were not, the quadruple count would be undetectable.
* `_compare` — one arm per failure mode: a changed value, a vanished datapoint, a late arrival
  inside one of our buckets, a datapoint outside them (counted, not judged), and a value within
  tolerance but not identical, which must appear in `within_tolerance_but_not_identical` with its
  delta rather than inside `n_fields_exactly_equal`.
* `_readings_now` — the two regression arms above, plus: a zero-combination arm must NOT read as
  agreement (`feedback_zero_file_scan_is_error`), and one disagreeing roll-up must drive
  `n_scored_on_reread` to -1 instead of being averaged away.
* `_guards` — every guard flipped false one at a time, and the guard-name set itself, so a guard
  dropped from the dict is a failure rather than a vacuous `all()`.
* the published-record arms — the shape and figures actually written on 2026-08-13, read from
  `results/phase1/F3-10_window_audit.json`, including that it carries no `verdict` key.

Offline, $0. No AWS client is constructed; `conftest.no_aws` blocks the network.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "results" / "phase1" / "F3-10_window_audit.json"


# The `sys.modules` key 08c is registered under, as a module-level constant rather than a literal
# at the call site. `lib/tests/test_module_name_collisions.py` reads loader names statically and
# checks them against the names `lib/` owns; a name it cannot read is a blind spot in that gate,
# and this file has exactly one subject, so there is nothing to trade for the parameter.
SUBJECT_MODULE = "f3_window_audit_under_test"


def _load(stem: str):
    spec = importlib.util.spec_from_file_location(SUBJECT_MODULE, ROOT / "f3_efficacy" / stem)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load("08c_window_audit.py")

# The four dimension combinations that carried byte-identical ConfidenceScore datapoints on
# 2026-08-12: the fully-qualified set and three roll-ups over subsets of it.
FULL = [{"Name": "Policy", "Value": "p1"}, {"Name": "Category", "Value": "HATE"},
        {"Name": "Filter", "Value": "ContentFilter"}, {"Name": "PolicyEngine", "Value": "e1"}]
ROLLUPS = [
    FULL,
    [d for d in FULL if d["Name"] != "PolicyEngine"],
    [d for d in FULL if d["Name"] in ("PolicyEngine",)],
    [{"Name": "Filter", "Value": "ContentFilter"}],
]


def _series(*, arm: str, name: str = "ConfidenceScore", dimensions=None,
            recorded=None, reread=None, our_buckets=None, error=None) -> dict:
    """One re-read series slot, shaped like `_reread` returns them."""
    recorded = recorded or {}
    return {
        "arm": arm, "name": name, "dimensions": list(dimensions if dimensions is not None
                                                     else FULL),
        "recorded": recorded,
        "reread": recorded if reread is None else reread,
        "our_buckets": list(our_buckets if our_buckets is not None else recorded),
        "error": error,
    }


def _dp(sum_: float, n: float, lo: float = 0.8, hi: float = 0.8) -> dict:
    """One datapoint. `min`/`max` default to a FIXED 0.8 rather than being derived from `sum`.

    Deriving them made the first version of the changed-value arms assert 1 and measure 3: moving
    `sum` moved three fields at once, so the arm could not tell "one field changed" from "the whole
    datapoint changed" (`feedback_label_must_match_computation`). The real scores do all sit on a
    0.2 grid, so 0.8 is a value the service actually publishes.
    """
    return {"sum": sum_, "sample_count": n, "min": lo, "max": hi}


def _recorded(*, golden=("a",), logged=None, evaluated=122, scored=61,
              per_request=None) -> dict:
    return {
        "golden_arms": list(golden),
        "logged_per_arm": logged if logged is not None else {"a": {"score_sum": 24.6}},
        "n_requests_evaluated": evaluated,
        "n_scored_requests": scored,
        "per_request_score_series_in_golden_arms": per_request or [],
    }


# ---------------------------------------------------------------------------
# the day comes from the epochs
# ---------------------------------------------------------------------------

def test_the_day_is_derived_from_the_epochs_not_from_a_date_string():
    """A date string in a record is prose; the epochs decide which buckets are re-read."""
    record = {
        "date": "1999-01-01", "observation_day": "1999-01-01", "t_start_utc": "1999-01-01T00:00:00Z",
        "arms": {"a": {"window": {"t0": 1786504145.0, "t1": 1786504200.0}}},
    }
    day, t0, t1 = C._observation_day(record)
    assert day == "2026-08-12", "the epochs say 2026-08-12; three date strings say otherwise"
    assert (t0, t1) == (1786504145.0, 1786504200.0)


def test_a_record_with_no_arms_is_a_config_error_not_a_reading():
    with pytest.raises(C.ConfigError):
        C._observation_day({"arms": {}})


def test_the_window_spans_every_arm():
    record = {"arms": {
        "a": {"window": {"t0": 1786504145.0, "t1": 1786504200.0}},
        "b": {"window": {"t0": 1786504260.0, "t1": 1786504330.0}},
        "c": {"window": {"t0": 1786504380.0, "t1": 1786504410.0}}}}
    day, t0, t1 = C._observation_day(record)
    assert (day, t0, t1) == ("2026-08-12", 1786504145.0, 1786504410.0)


# ---------------------------------------------------------------------------
# the dimension key — the thing that makes the quadruple count visible
# ---------------------------------------------------------------------------

def test_dim_key_is_order_independent():
    assert C._dim_key(FULL) == C._dim_key(list(reversed(FULL)))


def test_a_rollup_is_a_different_key_from_the_full_set():
    keys = {C._dim_key(d) for d in ROLLUPS}
    assert len(keys) == 4, (
        "if a roll-up collapsed onto the fully-qualified key, the four byte-identical series would "
        "be indistinguishable and the quadruple count could not be detected")


# ---------------------------------------------------------------------------
# the comparison — one arm per failure mode
# ---------------------------------------------------------------------------

def test_an_unchanged_reread_is_exactly_equal():
    rec = {1786504140: _dp(23.8, 29.0), 1786504200: _dp(0.8, 1.0)}
    cmp_ = C._compare([_series(arm="a", recorded=rec)])
    assert cmp_["n_datapoints_compared"] == 2
    assert cmp_["n_fields_compared"] == 8 and cmp_["n_fields_exactly_equal"] == 8
    assert cmp_["changed"] == [] and cmp_["vanished"] == []
    assert cmp_["within_tolerance_but_not_identical"] == []


def test_a_changed_value_is_reported():
    rec = {1786504140: _dp(23.8, 29.0)}
    got = {1786504140: _dp(24.0, 29.0)}
    cmp_ = C._compare([_series(arm="a", recorded=rec, reread=got)])
    assert len(cmp_["changed"]) == 1
    assert cmp_["changed"][0]["field"] == "sum"
    assert (cmp_["changed"][0]["recorded"], cmp_["changed"][0]["reread"]) == (23.8, 24.0)


def test_a_vanished_datapoint_is_its_own_failure_mode():
    cmp_ = C._compare([_series(arm="a", recorded={1786504140: _dp(23.8, 29.0)}, reread={})])
    assert len(cmp_["vanished"]) == 1 and cmp_["changed"] == []
    assert cmp_["n_datapoints_compared"] == 0


def test_a_late_arrival_inside_our_buckets_is_reported():
    """The failure mode that would refute reading (3): a score published after the fact."""
    cmp_ = C._compare([_series(
        arm="a", recorded={1786504140: _dp(23.8, 29.0)},
        reread={1786504140: _dp(23.8, 29.0), 1786504200: _dp(0.8, 1.0)},
        our_buckets=[1786504140, 1786504200])])
    assert len(cmp_["late_arrivals_in_our_buckets"]) == 1
    assert cmp_["late_arrivals_in_our_buckets"][0]["bucket_s"] == 1786504200
    assert cmp_["n_datapoints_outside_our_buckets"] == 0


def test_a_datapoint_outside_our_buckets_is_counted_not_judged():
    """The recorded read window is not reconstructable from the record, so this cannot be a verdict."""
    cmp_ = C._compare([_series(
        arm="a", recorded={1786504140: _dp(23.8, 29.0)},
        reread={1786504140: _dp(23.8, 29.0), 1786509999: _dp(0.8, 1.0)},
        our_buckets=[1786504140])])
    assert cmp_["late_arrivals_in_our_buckets"] == []
    assert cmp_["n_datapoints_outside_our_buckets"] == 1
    assert cmp_["changed"] == [] and cmp_["vanished"] == []


def test_within_tolerance_but_not_identical_is_published_with_its_delta():
    """The real 2026-08-13 anomaly: 23.800000000000015 re-reading as 23.8.

    It must not land in `n_fields_exactly_equal`, and it must not land in `changed` either. A
    passing guard that hides a formatting difference between two readers is the failure
    `feedback_identical_output_wrong_assertion` describes.
    """
    rec = {1786504140: _dp(23.800000000000015, 29.0)}
    got = {1786504140: _dp(23.8, 29.0)}
    cmp_ = C._compare([_series(arm="a", recorded=rec, reread=got)])
    near = cmp_["within_tolerance_but_not_identical"]
    assert cmp_["changed"] == []
    assert len(near) == 1 and near[0]["field"] == "sum"
    assert near[0]["delta"] == pytest.approx(-1.42e-14, abs=1e-16)
    assert cmp_["n_fields_exactly_equal"] == cmp_["n_fields_compared"] - 1


def test_a_difference_above_the_tolerance_is_a_change_not_a_near_miss():
    rec = {1786504140: _dp(23.8, 29.0)}
    got = {1786504140: _dp(23.8000001, 29.0)}
    cmp_ = C._compare([_series(arm="a", recorded=rec, reread=got)])
    assert len(cmp_["changed"]) == 1
    assert cmp_["within_tolerance_but_not_identical"] == []


def test_an_errored_series_is_counted_and_skipped():
    cmp_ = C._compare([_series(arm="a", recorded={1786504140: _dp(23.8, 29.0)},
                               error="Throttling")])
    assert cmp_["n_series"] == 1 and cmp_["n_series_with_an_error"] == 1
    assert cmp_["n_datapoints_compared"] == 0
    assert cmp_["errors"][0]["error"] == "Throttling"


# ---------------------------------------------------------------------------
# the readings — the two aggregation regressions
# ---------------------------------------------------------------------------

def test_four_identical_rollups_do_not_quadruple_the_sum():
    """The first run of `08c` reported 98.4 against a logged 24.6. That is this arm."""
    rec = {1786504140: _dp(23.8, 29.0), 1786504200: _dp(0.8, 1.0)}
    reread = [_series(arm="a", dimensions=d, recorded=rec) for d in ROLLUPS]
    out = C._readings_now(reread, _recorded())
    r1 = out["reading_1_logs_reconcile_with_metrics"]
    assert r1["all_agree"] is True
    assert r1["per_arm"]["a"]["n_dimension_combinations"] == 4, "all four must participate"
    assert r1["per_arm"]["a"]["metric_sums_on_reread"] == [24.6], (
        "one distinct total across four byte-identical roll-ups — not 98.4")
    r3 = out["reading_3_scores_are_absent_for_clean_requests"]
    assert r3["distinct_totals_across_dimension_combinations"] == [30]
    assert r3["n_scored_on_reread"] == 30, "not 120; each roll-up counts the same 30 samples"


def test_a_quiet_foreign_combination_is_not_a_disagreement():
    """Ten of fourteen combinations belong to other cases' probe policies and read 0.0."""
    rec = {1786504140: _dp(23.8, 29.0), 1786504200: _dp(0.8, 1.0)}
    reread = [_series(arm="a", recorded=rec)]
    for i in range(10):
        reread.append(_series(arm="a", dimensions=[{"Name": "Policy", "Value": f"other{i}"}],
                              recorded={}, reread={}, our_buckets=[1786504140, 1786504200]))
    out = C._readings_now(reread, _recorded())
    r1 = out["reading_1_logs_reconcile_with_metrics"]
    assert r1["all_agree"] is True, r1["per_arm"]["a"]["disagreeing"]
    assert r1["per_arm"]["a"]["n_dimension_combinations"] == 1, (
        "only the combination that carried a datapoint participates")


def test_an_arm_with_no_participating_combination_is_not_agreement():
    """`feedback_zero_file_scan_is_error`: nothing compared must not read as a pass."""
    reread = [_series(arm="a", dimensions=[{"Name": "Policy", "Value": "other"}],
                      recorded={}, reread={}, our_buckets=[1786504140])]
    out = C._readings_now(reread, _recorded())
    assert out["reading_1_logs_reconcile_with_metrics"]["per_arm"]["a"]["agree"] is False
    assert out["reading_1_logs_reconcile_with_metrics"]["all_agree"] is False


def test_one_disagreeing_rollup_fails_instead_of_averaging_in():
    rec = {1786504140: _dp(23.8, 29.0), 1786504200: _dp(0.8, 1.0)}
    reread = [_series(arm="a", dimensions=ROLLUPS[0], recorded=rec),
              _series(arm="a", dimensions=ROLLUPS[1],
                      recorded={1786504140: _dp(12.0, 15.0)})]
    out = C._readings_now(reread, _recorded())
    r1 = out["reading_1_logs_reconcile_with_metrics"]
    assert r1["all_agree"] is False
    assert len(r1["per_arm"]["a"]["disagreeing"]) == 1
    r3 = out["reading_3_scores_are_absent_for_clean_requests"]
    assert r3["n_scored_on_reread"] == -1, "a set of totals, so one dissenter cannot be averaged"
    assert r3["holds"] is False


def test_a_per_request_series_in_a_golden_arm_refutes_reading_2():
    """One sample per datapoint in a golden arm is the shape the FALSE verdict says is absent."""
    reread = [_series(arm="a", recorded={1786504140: _dp(0.8, 1.0), 1786504200: _dp(0.8, 1.0)})]
    out = C._readings_now(reread, _recorded(logged={"a": {"score_sum": 1.6}}))
    r2 = out["reading_2_no_per_request_score_series"]
    assert r2["holds"] is False and len(r2["per_request_score_series_now"]) == 1


def test_a_per_request_series_outside_the_golden_arms_does_not_refute_reading_2():
    """`active_one_per_minute` is EXPECTED to be per-request; it is excluded from the verdict."""
    reread = [_series(arm="spaced", recorded={1786504260: _dp(0.8, 1.0)})]
    out = C._readings_now(reread, _recorded(golden=("a",), logged={"spaced": {"score_sum": 0.8}}))
    assert out["reading_2_no_per_request_score_series"]["holds"] is True


def test_a_non_score_metric_never_participates():
    """Half (b) asks whether a SCORE can be tied to a label; Latency cannot answer that."""
    reread = [_series(arm="a", name="Latency", recorded={1786504140: _dp(400.0, 1.0)})]
    out = C._readings_now(reread, _recorded())
    assert out["reading_1_logs_reconcile_with_metrics"]["per_arm"]["a"]["agree"] is False
    assert out["per_dimension_combination"] == []


# ---------------------------------------------------------------------------
# the guards
# ---------------------------------------------------------------------------

def _clean_kwargs() -> dict:
    return {
        "day": "2026-08-12", "today": "2026-08-13", "lag_h": 23.589, "n_series": 84,
        "cmp_": {"n_series": 84, "n_series_with_an_error": 0, "n_recorded_datapoints": 56,
                 "n_datapoints_compared": 56, "n_fields_compared": 224, "changed": [],
                 "vanished": [], "late_arrivals_in_our_buckets": []},
        "readings": {
            "reading_1_logs_reconcile_with_metrics": {"all_agree": True},
            "reading_2_no_per_request_score_series": {"holds": True},
            "reading_3_scores_are_absent_for_clean_requests": {"holds": True},
        },
    }


def test_the_clean_case_passes_every_guard():
    guards = C._guards(**_clean_kwargs())
    assert set(guards) == set(C.GUARDS), "the guard dict and GUARDS must not drift apart"
    assert all(guards.values())


BREAKS = {
    "record_day_is_an_earlier_utc_day": lambda k: k.update(day="2026-08-13"),
    "reread_lag_exceeds_the_floor": lambda k: k.update(lag_h=11.9),
    "every_score_series_was_reread": lambda k: k["cmp_"].update(n_series=83),
    "no_read_error": lambda k: k["cmp_"].update(n_series_with_an_error=1),
    "every_recorded_datapoint_was_compared": lambda k: k["cmp_"].update(n_datapoints_compared=55),
    "no_datapoint_value_changed": lambda k: k["cmp_"].update(changed=[{"x": 1}]),
    "no_datapoint_vanished": lambda k: k["cmp_"].update(vanished=[{"x": 1}]),
    "no_late_arrival_in_a_recorded_bucket":
        lambda k: k["cmp_"].update(late_arrivals_in_our_buckets=[{"x": 1}]),
    "detection_total_is_unchanged":
        lambda k: k["readings"]["reading_3_scores_are_absent_for_clean_requests"].update(
            holds=False),
    "no_score_series_is_per_request_in_the_golden_arms":
        lambda k: k["readings"]["reading_2_no_per_request_score_series"].update(holds=False),
    "logged_sums_still_match_the_metric_sums":
        lambda k: k["readings"]["reading_1_logs_reconcile_with_metrics"].update(all_agree=False),
}


def test_every_guard_has_a_break_arm():
    assert set(BREAKS) == set(C.GUARDS), (
        "a guard with no way to fail is prose; add its arm to BREAKS or remove the guard")


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_each_guard_fails_alone(name):
    kwargs = _clean_kwargs()
    BREAKS[name](kwargs)
    guards = C._guards(**kwargs)
    assert guards[name] is False, f"{name} did not fail when its own precondition was broken"
    others = [k for k, v in guards.items() if k != name and v is False]
    # `every_recorded_datapoint_was_compared` and `every_score_series_was_reread` share the
    # comparison dict, so one extra casualty is allowed there and named rather than tolerated
    # silently.
    assert others == [] or set(others) <= {"every_recorded_datapoint_was_compared"}, others


def test_a_zero_datapoint_comparison_is_not_a_pass():
    kwargs = _clean_kwargs()
    kwargs["cmp_"].update(n_recorded_datapoints=0, n_datapoints_compared=0, n_fields_compared=0)
    assert C._guards(**kwargs)["every_recorded_datapoint_was_compared"] is False


# ---------------------------------------------------------------------------
# constants, and the record actually published
# ---------------------------------------------------------------------------

def test_average_is_not_among_the_compared_statistics():
    """Average is Sum/SampleCount, so it cannot fail independently of two checks already made."""
    assert "Average" not in C.STATISTICS
    assert set(C.STATISTICS) == {"Sum", "SampleCount", "Minimum", "Maximum"}
    assert set(C._STAT_KEY) == set(C.STATISTICS)


def test_the_lag_floor_is_far_above_the_measured_publish_lag():
    assert C.MIN_LAG_H == 12.0
    # F7-6 measured the p90 publish lag at 11.485 s; the parent's harvest settle is 120 s.
    assert C.MIN_LAG_H * 3600 > 3000 * 11.485
    assert C.MIN_LAG_H * 3600 > 300 * C.HARVEST_SETTLE_S


def test_the_published_record_is_a_supplementary_read_with_no_verdict():
    if not PUBLISHED.is_file():
        pytest.skip(f"{PUBLISHED.name} is not in the tree")
    d = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    assert d["kind"] == "SUPPLEMENTARY_READ"
    assert "verdict" not in d, "this read has no standing to score F3-10's oracle"
    assert d["case_id"] == "F3-10" and d["family"] == "f3_efficacy"
    assert d["failed_guards"] == []
    assert set(d["guards"]) == set(C.GUARDS) and all(d["guards"].values())


def test_the_published_record_holds_the_figures_the_finding_cites():
    if not PUBLISHED.is_file():
        pytest.skip(f"{PUBLISHED.name} is not in the tree")
    d = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    assert (d["observation_day"], d["reread_utc_day"]) == ("2026-08-12", "2026-08-13")
    assert d["reread_lag_h"] == pytest.approx(23.589, abs=0.001)
    assert d["reread_lag_h"] > C.MIN_LAG_H
    cmp_ = d["comparison"]
    assert cmp_["n_recorded_datapoints"] == cmp_["n_datapoints_compared"] == 56
    assert cmp_["n_fields_compared"] == 224 and cmp_["n_fields_exactly_equal"] == 212
    assert cmp_["changed"] == [] and cmp_["vanished"] == []
    assert cmp_["late_arrivals_in_our_buckets"] == []
    near = cmp_["within_tolerance_but_not_identical"]
    assert len(near) == 12, "212 + 12 = 224; the 12 are a summation-order difference, not a change"
    assert max(abs(x["delta"]) for x in near) < 1e-13
