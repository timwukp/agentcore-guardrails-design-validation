"""DEV-P4-35: the publish-slack bucket set, pinned against both days' real records.

Why this file exists
--------------------
F3-10's `logs_reconcile_with_metrics` guard compares two independent surfaces — the per-request
scores in APPLICATION_LOGS, and the `ConfidenceScore` datapoints F3-10 read from CloudWatch. On
2026-08-12 it agreed. On the 2026-08-13 replicate it FAILED: logged 24.4 over 30 values against a
metric Sum of 23.6 over 29 samples for `active_golden_set`.

The disagreement was in the READER, not the service. A log event is stamped when the request is
processed; the metric datapoint is bucketed by the service's own emit time, up to the publish lag
later. Day 2's `active_golden_set` window ran 1786588205.003 -> 1786588260.386, so one detection of
30 was bucketed at 1786588260 while all 60 log rows named 1786588200 — and 23.6 + 0.8 = 24.4
exactly. Day 1 agreed only because its boundary crossing was already covered by its own log rows,
which named two buckets. Same shape as `feedback_span_vs_points_offbyone`.

What each arm holds, and why an arm rather than a sentence
---------------------------------------------------------
The fix has TWO halves and each is load-bearing on real data, so each gets a mutation arm driven
by the real published records rather than a hand-built fixture (`feedback_verify_against_real_
artifact`):

* `test_both_days_reconcile_under_the_shipped_reader` — the claim the FINDING makes. Both days,
  one instrument, all three arms, exact sums.
* `test_the_grant_is_load_bearing_on_day_2` — with `SLACK_PERIODS = 0` the reader reproduces the
  measured defect: 23.6 over 29 samples, all_agree False. The expected numbers are read from the
  ARCHIVED as-run record, so this arm is checked against the reading that actually happened, not
  against my memory of it (`feedback_prose_is_not_verified`).
* `test_the_withholding_is_load_bearing_on_both_days` — the OTHER half, and it fires on a
  different arm. The three arms' metric queries overlap, so `active_one_per_minute`'s own series
  carries `log_only_golden_set`'s thirty-detection datapoint; granted its slack unconditionally it
  reads 25.0/31 on day 1 and 25.6/31 against a logged 0.8/1. Without the withholding the FIX would
  break both days.
* `test_the_grant_changes_nothing_on_day_1` — the converse, and the argument for replicating at
  all: a zero-slack reader still passes 2026-08-12 on all three arms. One day of this case could
  not have found DEV-P4-35.
* `test_the_fix_did_not_move_day_1` — the day-1 re-derivation must equal the day-1 as-run archive
  arm for arm. A reader change that repaired day 2 by moving day 1 would be measuring the fix as a
  difference between days.
* `test_slack_is_one_period_and_says_why` — `SLACK_PERIODS` is pinned to 1 against `PERIOD_S` and
  F7-6's measured p90 publish lag, and the output must carry the DEV-P4-35 rationale, because a
  bare widened window is indistinguishable from a fudge factor.

Offline, $0. No AWS client is constructed; `conftest.no_aws` blocks the network.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PHASE1 = ROOT / "results" / "phase1"
ARCHIVE = PHASE1 / "archive"


# The `sys.modules` key 08b is registered under, as a module-level constant rather than a literal
# at the call site. `lib/tests/test_module_name_collisions.py` reads loader names statically and
# checks them against the names `lib/` owns; a name it cannot read is a blind spot in that gate,
# and this file has exactly one subject, so there is nothing to trade for the parameter. The key
# differs from the one `test_log_surface_join.py` registers the same file under, which is allowed:
# the hazard is one name meaning two files, not one file under two names.
SUBJECT_MODULE = "f3_publish_slack_under_test"


def _load(stem: str):
    spec = importlib.util.spec_from_file_location(SUBJECT_MODULE, ROOT / "f3_efficacy" / stem)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load("08b_log_surface_join.py")

# (label, metric-side record, log-side record). The metric side is F3-10's own analysis record;
# the log side is 08b's output. Day 1's log side is the RE-DERIVATION, because the whole point of
# DEV-P4-35 is that both days are read by one instrument.
DAYS = {
    "2026-08-12": (ARCHIVE / "F3-10__day1_2026-08-12.json",
                   PHASE1 / "F3-10_log_surface_join__day1_rederived.json"),
    "2026-08-13": (PHASE1 / "F3-10.json",
                   PHASE1 / "F3-10_log_surface_join.json"),
}
AS_RUN = {
    "2026-08-12": ARCHIVE / "F3-10_log_surface_join__day1_2026-08-12.json",
    "2026-08-13": ARCHIVE / "F3-10_log_surface_join__day2_asrun_bucket_defect_2026-08-13.json",
}

# The measured figures, one per (day, arm): logged sum and number of logged score values. Written
# out rather than read from the record under test, so a reader that started returning zeros could
# not pass by agreeing with itself.
EXPECTED = {
    ("2026-08-12", "active_golden_set"): (24.6, 30),
    ("2026-08-12", "active_one_per_minute"): (0.8, 1),
    ("2026-08-12", "log_only_golden_set"): (24.2, 30),
    ("2026-08-13", "active_golden_set"): (24.4, 30),
    ("2026-08-13", "active_one_per_minute"): (0.8, 1),
    ("2026-08-13", "log_only_golden_set"): (24.8, 30),
}

# The buckets the fix turns on, named explicitly. Day 2 GRANTS a slack bucket to the arm that
# failed. The withholding that changes a number is on `active_one_per_minute`, whose slack bucket is
# where `log_only_golden_set` logged its thirty detections; `active_golden_set` also withholds one,
# but inertly — nobody published a datapoint there.
DAY2_GRANTED = 1786588260
WITHHELD_LOAD_BEARING = {"2026-08-12": 1786504380, "2026-08-13": 1786588440}
# `active_golden_set` withholds a bucket on day 1 only, and inertly: nobody published a datapoint
# there. On day 2 that same successor bucket is unclaimed, so it is GRANTED instead — which is
# precisely the asymmetry that made one day's pass an accident.
WITHHELD_INERT = {"2026-08-12": [1786504260], "2026-08-13": []}


def _sides(day: str) -> tuple[dict, dict]:
    result_path, join_path = DAYS[day]
    for p in (result_path, join_path):
        if not p.is_file():
            pytest.skip(f"{p.relative_to(ROOT)} is not in the tree")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    join = json.loads(join_path.read_text(encoding="utf-8"))
    return result, join["per_arm"]


# ---------------------------------------------------------------------------
# the claim
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("day", sorted(DAYS))
def test_both_days_reconcile_under_the_shipped_reader(day):
    result, per_arm = _sides(day)
    rec = B._reconcile(result, per_arm)
    assert rec["checked"] == 3, f"{day}: expected 3 arms compared, got {rec['checked']}"
    assert rec["all_agree"] is True, f"{day}: {rec['per_arm']}"
    for arm, slot in rec["per_arm"].items():
        want_sum, want_n = EXPECTED[(day, arm)]
        assert slot["log_sum"] == pytest.approx(want_sum), f"{day}/{arm} logged sum"
        assert slot["n_logged_score_values"] == want_n, f"{day}/{arm} logged count"
        # The point of the guard: the OTHER surface has to land on the same two numbers.
        assert slot["metric_sum"] == pytest.approx(want_sum), f"{day}/{arm} metric Sum"
        assert slot["metric_sample_count"] == want_n, f"{day}/{arm} metric SampleCount"
        assert slot["agrees"] is True
        # A roll-up that disagreed with its siblings would make the collapse by bucket unsafe.
        assert slot["dimension_combinations_disagreeing"] == []


def test_the_two_halves_each_fire_on_a_real_day():
    """Neither half is dead code: name the bucket each one moved, on the day it moved it."""
    _, per_arm_2 = _sides("2026-08-13")
    rec2 = B._reconcile(json.loads(DAYS["2026-08-13"][0].read_text(encoding="utf-8")), per_arm_2)
    granted = rec2["per_arm"]["active_golden_set"]["buckets_added_for_publish_slack"]
    assert granted == [DAY2_GRANTED], (
        "day 2's active_golden_set is the arm DEV-P4-35 was found on; if the grant no longer "
        f"reaches {DAY2_GRANTED} the defect is back. got {granted}")

    for day in sorted(DAYS):
        result, per_arm = _sides(day)
        rec = B._reconcile(result, per_arm)
        key = "slack_buckets_withheld_because_another_arm_owns_them"
        assert rec["per_arm"]["active_one_per_minute"][key] == [WITHHELD_LOAD_BEARING[day]], (
            f"{day}: active_one_per_minute must withhold {WITHHELD_LOAD_BEARING[day]} — "
            "log_only_golden_set's thirty detections are logged there")
        # The inert one is asserted too, so that a change collapsing the withholding to only the
        # cases where it happens to matter is visible rather than silent.
        assert rec["per_arm"]["active_golden_set"][key] == WITHHELD_INERT[day]


def test_the_fix_did_not_move_day_1():
    """Re-derivation must reproduce day 1's as-run figures, arm for arm.

    If the reader change had shifted day 1 too, the two-day agreement would be an artefact of the
    instrument rather than a replication.
    """
    as_run = json.loads(AS_RUN["2026-08-12"].read_text(encoding="utf-8"))
    rederived = json.loads(DAYS["2026-08-12"][1].read_text(encoding="utf-8"))
    a, b = as_run["reconciliation_with_metrics"], rederived["reconciliation_with_metrics"]
    assert a["all_agree"] is True and b["all_agree"] is True
    assert sorted(a["per_arm"]) == sorted(b["per_arm"])
    for arm in a["per_arm"]:
        for field in ("log_sum", "metric_sum", "metric_sample_count", "n_logged_score_values",
                      "buckets_compared"):
            assert a["per_arm"][arm][field] == b["per_arm"][arm][field], f"{arm}.{field} moved"


# ---------------------------------------------------------------------------
# the mutation arms — one per half of the fix
# ---------------------------------------------------------------------------

def test_the_grant_is_load_bearing_on_day_2(monkeypatch):
    """SLACK_PERIODS = 0 must reproduce the defect AS IT WAS MEASURED, not merely fail."""
    monkeypatch.setattr(B, "SLACK_PERIODS", 0)
    result, per_arm = _sides("2026-08-13")
    rec = B._reconcile(result, per_arm)
    assert rec["all_agree"] is False, "the zero-slack reader must not pass day 2"

    as_run = json.loads(AS_RUN["2026-08-13"].read_text(
        encoding="utf-8"))["reconciliation_with_metrics"]["per_arm"]
    for arm, was in as_run.items():
        now = rec["per_arm"][arm]
        assert now["metric_sum"] == pytest.approx(was["metric_sum"]), (
            f"{arm}: the mutant reads {now['metric_sum']}, the as-run defect read "
            f"{was['metric_sum']}")
        assert now["metric_sample_count"] == was["metric_sample_count"]
        assert now["agrees"] is was["agrees"]
    # And the specific number, so a future refactor that fails day 2 for some OTHER reason does
    # not quietly satisfy this arm.
    bad = rec["per_arm"]["active_golden_set"]
    assert (bad["metric_sum"], bad["metric_sample_count"]) == (pytest.approx(23.6), 29.0)
    assert bad["log_sum"] == pytest.approx(24.4) and bad["n_logged_score_values"] == 30


@pytest.mark.parametrize("day,metric_sum", [("2026-08-12", 25.0), ("2026-08-13", 25.6)])
def test_the_withholding_is_load_bearing_on_both_days(day, metric_sum, monkeypatch):
    """Grant the slack unconditionally and `active_one_per_minute` absorbs its successor arm.

    The arm this fires on is `active_one_per_minute`, not the one the grant fires on: its single
    logged detection sits two buckets before `log_only_golden_set`'s thirty, and its own metric
    query reaches far enough to see them. I first wrote this arm against `active_golden_set` and it
    read 24.6 unchanged — the withholding does nothing there, because that arm's successor bucket
    carries no datapoint of anyone else's.
    """
    def _no_withholding(arm_key, log_buckets):
        # The grant, with the withholding step deleted — not a call back into the real helper,
        # which would recurse through the monkeypatched name.
        from_logs = set(log_buckets.get(arm_key) or set())
        if not from_logs:
            return set(), set()
        return {max(from_logs) + i * B.PERIOD_S
                for i in range(1, B.SLACK_PERIODS + 1)}, set()

    monkeypatch.setattr(B, "_slack_buckets", _no_withholding)
    result, per_arm = _sides(day)
    rec = B._reconcile(result, per_arm)
    assert rec["all_agree"] is False, (
        f"{day}: without the withholding, active_one_per_minute reaches into "
        "log_only_golden_set's bucket, so the reconciliation must stop passing")
    bad = rec["per_arm"]["active_one_per_minute"]
    assert bad["log_sum"] == pytest.approx(0.8) and bad["n_logged_score_values"] == 1
    assert bad["metric_sum"] == pytest.approx(metric_sum), (
        "its own 0.8 plus the whole golden-set datapoint it stole")
    assert bad["metric_sample_count"] == 31.0
    assert bad["agrees"] is False
    # The arms that do not depend on the withholding must be untouched by the mutation, or this
    # arm would be pinning a blanket failure rather than one specific over-count.
    for other in ("active_golden_set", "log_only_golden_set"):
        assert rec["per_arm"][other]["agrees"] is True, f"{day}/{other} must not move"


def test_the_grant_changes_nothing_on_day_1(monkeypatch):
    """The honest converse: a zero-slack reader still PASSES 2026-08-12, all three arms.

    This is the whole argument for the replicate. Day 1's `active_golden_set` window crossed a
    minute boundary too, but its own log rows named both buckets, so the defect was invisible. A
    single day of this case could not have found DEV-P4-35, and an arm asserting that is worth more
    than the sentence saying so.
    """
    monkeypatch.setattr(B, "SLACK_PERIODS", 0)
    result, per_arm = _sides("2026-08-12")
    rec = B._reconcile(result, per_arm)
    assert rec["all_agree"] is True
    assert all(v["buckets_added_for_publish_slack"] == [] for v in rec["per_arm"].values())


def test_a_reconciliation_with_nothing_to_compare_is_not_agreement():
    """An empty arm set must not read as all_agree — `feedback_missing_check_is_not_pass`."""
    rec = B._reconcile({"arms": {}}, {})
    assert rec["checked"] == 0
    assert rec["all_agree"] is False


# ---------------------------------------------------------------------------
# the constant, and the reason it is that value
# ---------------------------------------------------------------------------

def test_slack_is_one_period_and_says_why():
    assert B.SLACK_PERIODS == 1, (
        "one period, because the offset is a publish lag whose p90 F7-6 measured at 11.485s — a "
        "fifth of a period. Two would start reaching into whatever ran next.")
    assert B.PERIOD_S == 60
    rec = B._reconcile({"arms": {}}, {})
    assert rec["publish_slack_periods"] == 1
    why = rec["why_publish_slack"]
    assert "DEV-P4-35" in why, "the widened bucket set must cite the deviation that justifies it"
    for token in ("publish lag", "2026-08-13", "under-counted"):
        assert token in why, f"the rationale must name {token!r}"


def test_the_slack_helper_grants_nothing_to_an_arm_with_no_logged_bucket():
    """No log rows means no anchor, so there is nothing to extrapolate from."""
    granted, withheld = B._slack_buckets("a", {"a": set(), "b": {1786588200}})
    assert granted == set() and withheld == set()


@pytest.mark.parametrize("periods", [1, 2, 3])
def test_the_grant_extends_from_the_last_logged_bucket(periods, monkeypatch):
    monkeypatch.setattr(B, "SLACK_PERIODS", periods)
    granted, withheld = B._slack_buckets("a", {"a": {1786588140, 1786588200}})
    assert granted == {1786588200 + i * 60 for i in range(1, periods + 1)}
    assert withheld == set()
