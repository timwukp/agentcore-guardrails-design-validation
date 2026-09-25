"""Arms for the instrument that reads this project's spend off the meter.

Every arm runs against a fake census — a plain dict of daily readings — and the fake is written so it
CAN LIE: it will report spend on days the ledger does not mention, a quantity that disagrees with the
project's own count, two instances' worth of hours on one day, a usage type under the wrong service, a
step that is not flat, and a resource that is still billing. A double that can only supply agreeing
numbers proves the caller compiles, not that the check discriminates
(`feedback_unreachable_branch_in_fake`).

The first arm is the no-mutant control. Without it, twenty failing-input arms cannot distinguish "the
check catches every defect" from "the check fails on everything it is given".

The repo-reading halves — `derive_project_days` and `counted_polly_characters` — are exercised against
a PLANTED tree rather than against this repository, because an arm pinned to the real
`session-logs/` would change meaning every time a session runs.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import read_actual_spend as ras  # noqa: E402

GUARD = "USE1-Guardrail-ContentPolicyUnitsConsumed"
POLLY_GEN = "USE1-SynthesizeSpeechGenerative-Characters"
BEDROCK = "Amazon Bedrock"
POLLY = "Amazon Polly"
EBS = "EC2 - Other"
DAYS = ["2026-08-10", "2026-08-11"]


def series(service: str, ut: str, readings: dict[str, tuple[float, float]]) -> ras.Series:
    return ras.Series(ut, service, dict(readings))


def census(*items: ras.Series) -> dict[str, ras.Series]:
    return {ras.key_of(s.service, s.usage_type): s for s in items}


def base_census() -> dict[str, ras.Series]:
    return census(
        series(BEDROCK, GUARD, {"2026-08-10": (1.0, 100.0), "2026-08-11": (2.0, 200.0)}),
        series(POLLY, POLLY_GEN, {"2026-08-10": (0.5, 1000.0), "2026-08-11": (0.5, 234.0)}),
    )


def base_model(**over) -> dict:
    """A two-line ledger that agrees with `base_census()` exactly."""
    model = {
        "prices": {"ebs_gp3_gb_month": {"usd": 0.08, "verified": True}},
        "actuals": {
            "window": {"start": "2026-08-01", "end": "2026-08-31"},
            "measured_usd": 4.0,
            "project_days": list(DAYS),
            "services_touched": [BEDROCK, POLLY],
            "ledger": [
                {"usage_type": GUARD, "service": BEDROCK, "attributed": True, "basis": "day_set",
                 "usd": 3.0, "qty": 300.0, "days": list(DAYS), "reason": "ours"},
                {"usage_type": POLLY_GEN, "service": POLLY, "attributed": True,
                 "basis": "quantity_match", "usd": 1.0, "qty": 1234.0, "days": list(DAYS),
                 "reason": "ours"},
            ],
        },
    }
    model["actuals"].update(over)
    return model


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A planted repo: one artifact per project day, and one Polly log counting 1,234 characters."""
    logs = tmp_path / "session-logs"
    logs.mkdir()
    for d in DAYS:
        (logs / f"something-{d.replace('-', '')}.log").write_text("x", encoding="utf-8")
    (logs / "polly-spend-20260810-one.log").write_text(
        "synthesized 3 tracks\nTOTAL 1,234 characters over 9 SynthesizeSpeech requests\n",
        encoding="utf-8")
    return tmp_path


def run(census_in, model, root_in, estimated=(), days_read=2) -> ras.Report:
    # `None` is passed straight through: it is the third state, not an absent argument.
    return ras.check(census_in, model, root_in,
                     None if estimated is None else list(estimated), days_read)


# ------------------------------------------------------------------------- the no-mutant control
def test_a_ledger_that_agrees_with_the_meter_in_every_respect_passes(root):
    """The control. If this fails, no other arm in this file means anything."""
    rep = run(base_census(), base_model(), root)
    assert rep.problems == [], rep.problems
    assert rep.rc == 0
    assert rep.attributed_entries == 2
    assert rep.measured_usd == 4.0


def test_the_rejected_day_rule_is_still_computed_and_reported(root):
    """The argument against the naive rule is only an argument while the number is re-derived.

    Here both lines fall entirely on project days, so the rule claims everything — including the
    Polly line, whose real basis is a quantity match. The rule's total exceeding the ledger's is the
    whole point, and a run that stopped computing it would quietly turn a measured finding into a
    remembered one.
    """
    rep = run(base_census(), base_model(), root)
    assert rep.naive_count == 2
    assert rep.naive_total == 4.0


# ------------------------------------------------------------------- the meter moved under a figure
def test_a_recorded_cost_that_no_longer_matches_the_meter_fails_and_prints_both(root):
    c = base_census()
    c[ras.key_of(BEDROCK, GUARD)].days["2026-08-11"] = (2.5, 200.0)
    rep = run(c, base_model(), root)
    assert rep.rc == 1
    assert any("the meter now says $3.5" in p for p in rep.problems), rep.problems


def test_a_recorded_quantity_that_no_longer_matches_the_meter_fails(root):
    c = base_census()
    c[ras.key_of(BEDROCK, GUARD)].days["2026-08-10"] = (1.0, 150.0)
    rep = run(c, base_model(), root)
    assert any("ledger records qty 300.000" in p for p in rep.problems), rep.problems


def test_a_total_that_is_not_the_sum_of_the_entries_fails(root):
    rep = run(base_census(), base_model(measured_usd=99.0), root)
    assert any("measured_usd says $99.0000" in p and "sum to $4.0000" in p for p in rep.problems)


# ---------------------------------------------------------------- the partition: nothing unmentioned
def test_a_metered_day_the_ledger_neither_claims_nor_excludes_fails(root):
    """The refusal that keeps a line's inconvenient days from being quietly dropped.

    Without it, an entry could claim the two days that reconcile and say nothing about a third.
    """
    c = base_census()
    c[ras.key_of(BEDROCK, GUARD)].days["2026-08-21"] = (0.0054, 36.0)
    rep = run(c, base_model(), root)
    assert rep.rc == 1
    assert any("2026-08-21" in p and "neither claims nor excludes" in p for p in rep.problems)


def test_an_excluded_day_is_accepted_only_with_a_reason(root):
    c = base_census()
    c[ras.key_of(BEDROCK, GUARD)].days["2026-08-21"] = (0.0054, 36.0)
    m = base_model()
    m["actuals"]["ledger"][0]["excluded_days"] = {"2026-08-21": "not ours; no artifact that day"}
    assert run(c, m, root).problems == []
    m["actuals"]["ledger"][0]["excluded_days"] = {"2026-08-21": "   "}
    assert any("excluded 2026-08-21 with no reason" in p for p in run(c, m, root).problems)


def test_a_claimed_day_the_meter_shows_nothing_on_fails(root):
    m = base_model()
    m["actuals"]["ledger"][0]["days"] = DAYS + ["2026-08-12"]
    m["actuals"]["project_days"] = DAYS + ["2026-08-12"]
    (root / "session-logs" / "x-20260812.log").write_text("x", encoding="utf-8")
    rep = run(base_census(), m, root)
    assert any("claims ['2026-08-12'] and the meter shows nothing" in p for p in rep.problems)


# ------------------------------------------------------------------------ the day set stays bounded
def test_a_claimed_day_outside_the_project_days_fails_unless_it_is_declared_unexplained(root):
    """The clause that keeps `day_set` from meaning "any day we like"."""
    c = base_census()
    c[ras.key_of(BEDROCK, GUARD)].days["2026-08-14"] = (0.25, 25.0)
    m = base_model()
    m["actuals"]["ledger"][0]["days"] = DAYS + ["2026-08-14"]
    m["actuals"]["ledger"][0]["usd"] = 3.25
    m["actuals"]["ledger"][0]["qty"] = 325.0
    m["actuals"]["measured_usd"] = 4.25
    rep = run(c, m, root)
    assert any("claims 2026-08-14, which is neither a recorded project day" in p
               for p in rep.problems)
    m["actuals"]["ledger"][0]["unexplained_days"] = ["2026-08-14"]
    m["actuals"]["ledger"][0]["unexplained_reason"] = "UTC/local boundary; the log is dated 08-15"
    assert run(c, m, root).problems == []


def test_declaring_a_day_unexplained_without_saying_why_fails(root):
    c = base_census()
    c[ras.key_of(BEDROCK, GUARD)].days["2026-08-14"] = (0.25, 25.0)
    m = base_model()
    m["actuals"]["ledger"][0].update(days=DAYS + ["2026-08-14"], usd=3.25, qty=325.0,
                                     unexplained_days=["2026-08-14"])
    assert any("no unexplained_reason" in p for p in run(c, m, root).problems)


def test_a_recorded_project_day_with_no_artifact_behind_it_fails(root):
    """The day list is a claim about this repository, checked against it
    (`feedback_derive_both_sides_of_a_gate`)."""
    m = base_model(project_days=DAYS + ["2026-08-30"])
    rep = run(base_census(), m, root)
    assert any("lists 2026-08-30, and no artifact in this repo" in p for p in rep.problems)


# ------------------------------------------------------------------- the identification still holds
def test_a_day_busier_than_one_instance_could_be_breaks_the_identification(root):
    """`BoxUsage:t3.small` is identified as ours by the daily curve never exceeding 24 hours. A day
    with 31 hours means a second instance ran, and the entry's whole argument is gone."""
    c = census(series("Amazon Elastic Compute Cloud - Compute", "BoxUsage:t3.small",
                      {"2026-08-10": (0.4992, 24.0), "2026-08-11": (0.6448, 31.0)}))
    m = base_model(
        measured_usd=1.144, services_touched=["Amazon Elastic Compute Cloud - Compute"],
        ledger=[{"usage_type": "BoxUsage:t3.small",
                 "service": "Amazon Elastic Compute Cloud - Compute", "attributed": True,
                 "basis": "day_set", "usd": 1.144, "qty": 55.0, "days": list(DAYS),
                 "max_daily_qty": 24.0, "reason": "the runner"}])
    rep = run(c, m, root)
    assert any("31.000 against a declared ceiling of 24.000" in p for p in rep.problems)


def test_the_same_usage_type_under_a_different_service_is_not_a_match(root):
    """`TimedStorage-ByteHrs` is metered under S3, ECR and DynamoDB in this account. A census keyed on
    the name alone would have summed all three, and a ledger entry naming S3 would have reconciled
    against the wrong number."""
    c = census(series("Amazon DynamoDB", "TimedStorage-ByteHrs", {"2026-08-10": (5.0, 1.0)}))
    m = base_model(measured_usd=5.0, services_touched=["Amazon DynamoDB"],
                   ledger=[{"usage_type": "TimedStorage-ByteHrs",
                            "service": "Amazon Simple Storage Service", "attributed": True,
                            "basis": "day_set", "usd": 5.0, "days": ["2026-08-10"],
                            "reason": "ours"}])
    rep = run(c, m, root)
    assert any("the meter has no such line" in p for p in rep.problems)


def test_collisions_are_reported_so_the_ambiguity_is_visible(root):
    c = base_census()
    c[ras.key_of("Amazon DynamoDB", "TimedStorage-ByteHrs")] = series(
        "Amazon DynamoDB", "TimedStorage-ByteHrs", {"2026-08-10": (0.0, 1.0)})
    c[ras.key_of("Amazon Simple Storage Service", "TimedStorage-ByteHrs")] = series(
        "Amazon Simple Storage Service", "TimedStorage-ByteHrs", {"2026-08-10": (9.0, 1.0)})
    rep = run(c, base_model(), root)
    assert rep.collisions == {"TimedStorage-ByteHrs": ["Amazon DynamoDB",
                                                      "Amazon Simple Storage Service"]}


# ----------------------------------------------------------------------------- the quantity match
def test_a_quantity_match_that_does_not_match_the_project_s_own_count_fails(root):
    """The Polly basis is two meters agreeing. Break one and the entry loses its authority."""
    c = base_census()
    c[ras.key_of(POLLY, POLLY_GEN)].days["2026-08-11"] = (0.5, 999.0)
    m = base_model()
    m["actuals"]["ledger"][1]["qty"] = 1999.0
    rep = run(c, m, root)
    assert any("this project counted 1234" in p for p in rep.problems), rep.problems


def test_a_quantity_match_with_no_log_to_count_from_fails_rather_than_reading_as_zero(tmp_path):
    """`feedback_zero_file_scan_is_error`: a regex that matched nothing is not a count of nothing."""
    (tmp_path / "session-logs").mkdir()
    for d in DAYS:
        (tmp_path / "session-logs" / f"x-{d.replace('-', '')}.log").write_text("x", encoding="utf-8")
    rep = run(base_census(), base_model(), tmp_path)
    assert any("the independent count they rest on was never read" in p for p in rep.problems)


def test_the_counted_total_is_parsed_out_of_the_log_and_not_retyped(root):
    total, per_log = ras.counted_polly_characters(root)
    assert total == 1234, "the comma in `TOTAL 1,234 characters` must not truncate the number"
    assert list(per_log) == ["polly-spend-20260810-one.log"]


# --------------------------------------------------------------------------------- completeness
def test_a_metered_line_only_on_project_days_that_the_ledger_never_mentions_fails(root):
    """A ledger is a name list and a name list cannot notice a new name
    (`feedback_scope_as_namelist`). This is the arm that makes a NEW guardrail usage type a failure
    rather than an omission."""
    c = base_census()
    c[ras.key_of(BEDROCK, "USE1-Guardrail-BrandNewPolicyUnitsConsumed")] = series(
        BEDROCK, "USE1-Guardrail-BrandNewPolicyUnitsConsumed", {"2026-08-10": (0.42, 42.0)})
    rep = run(c, base_model(), root)
    assert any("BrandNewPolicy" in p and "not by omission" in p for p in rep.problems)


def test_a_line_below_the_tolerance_is_exempt_but_counted_and_bounded(root):
    """The 38 cross-region `AWS-In-Bytes` meters from the first live run.

    An exemption that is not counted is a silence. This one publishes both the number of lines and the
    total they could possibly hide, and that total is the guarantee (`feedback_no_silent_caps`).
    """
    c = base_census()
    for i, name in enumerate(("APS1-SAE1-AWS-In-Bytes", "USE1-EUN1-AWS-Out-Bytes")):
        c[ras.key_of(BEDROCK, name)] = series(BEDROCK, name, {"2026-08-10": (0.0001 * (i + 1), 1.0)})
    rep = run(c, base_model(), root)
    assert rep.problems == [], rep.problems
    assert rep.immaterial_lines == 2
    assert abs(rep.immaterial_usd - 0.0003) < 1e-9
    assert any("0.000300" in n and "whole amount this exemption can hide" in n for n in rep.notes)


def test_the_exemption_stops_exactly_at_the_tolerance_every_other_check_uses(root):
    """The boundary. An exemption whose edge nobody pinned is an exemption that grows."""
    c = base_census()
    c[ras.key_of(BEDROCK, "USE1-SomethingSmall")] = series(
        BEDROCK, "USE1-SomethingSmall", {"2026-08-10": (ras.TOL_USD, 1.0)})
    rep = run(c, base_model(), root)
    assert rep.immaterial_lines == 0, "at the tolerance is not below it"
    assert any("USE1-SomethingSmall" in p and "not by omission" in p for p in rep.problems)


def test_the_generous_day_rule_is_measured_too_because_the_two_rules_fail_opposite_ways(root):
    """The rule a person actually reaches for when a cost allocation tag turns out to be inactive:
    claim the whole line if any of its spend touches a project day. Here a huge shared line billed
    every day is swept in whole, while the strict rule ignores it — which is why neither number alone
    is an argument."""
    c = base_census()
    c[ras.key_of("Amazon Simple Storage Service", "TimedStorage-ByteHrs")] = series(
        "Amazon Simple Storage Service", "TimedStorage-ByteHrs",
        {"2026-08-02": (1000.0, 1.0), "2026-08-10": (1000.0, 1.0)})
    rep = run(c, base_model(), root)
    assert rep.naive_any_total == 4.0 + 2000.0
    assert rep.naive_any_count == 3
    assert rep.naive_total == 4.0, "the strict rule refuses the same line for starting before us"
    assert rep.naive_count == 2


def test_a_shared_line_spanning_days_before_the_project_does_not_trip_completeness(root):
    """The other direction: the check must not demand an entry for every account-wide line, or it
    would fire on all 1,024 of them and be turned off within a day."""
    c = base_census()
    c[ras.key_of(BEDROCK, "USE1-SomeoneElsesModelTokens")] = series(
        BEDROCK, "USE1-SomeoneElsesModelTokens", {"2026-08-02": (500.0, 1e6),
                                                  "2026-08-10": (500.0, 1e6)})
    assert run(c, base_model(), root).problems == []


def test_a_service_name_the_meter_does_not_know_fails_instead_of_silently_checking_nothing(root):
    """A typo in `services_touched` would switch the completeness check off for that service and leave
    every other arm green — the vacuous-guard pattern (`feedback_vacuous_test_check`)."""
    rep = run(base_census(), base_model(services_touched=[BEDROCK, "Amazon Pollly"]), root)
    assert any("Amazon Pollly" in p and "silently switch the completeness check off" in p
               for p in rep.problems)


# ------------------------------------------------------------------------------- the ran flags
def test_an_empty_census_cannot_report_clean(root):
    """`feedback_zero_needs_a_ran_flag`. Cost Explorer returning nothing must not look like a ledger
    that agrees with it."""
    rep = run({}, base_model(ledger=[], measured_usd=0.0, project_days=[], services_touched=[]),
              root, days_read=0)
    assert rep.problems == [], "nothing is WRONG here; the point is that nothing was read"
    assert rep.rc == 2


def test_a_ledger_of_pure_rejections_cannot_report_clean(root):
    """Every entry `attributed: false` reconciles trivially — and has measured nothing.

    The census here is real and the entries are well-argued, so there is nothing to REPORT; the rc has
    to carry the fact that no attribution was actually made.
    """
    m = base_model(measured_usd=0.0, services_touched=[],
                   ledger=[{"usage_type": GUARD, "service": BEDROCK, "attributed": False,
                            "reason": "not ours"},
                           {"usage_type": POLLY_GEN, "service": POLLY, "attributed": False,
                            "reason": "not ours either"}])
    rep = run(base_census(), m, root)
    assert rep.problems == [], rep.problems
    assert rep.ledger_checked == 2 and rep.attributed_entries == 0
    assert rep.rc == 2, "a rejection-only ledger has measured nothing and must not exit 0"


def test_a_rejection_with_no_argument_fails(root):
    m = base_model(measured_usd=0.0,
                   ledger=[{"usage_type": GUARD, "service": BEDROCK, "attributed": False},
                           {"usage_type": POLLY_GEN, "service": POLLY, "attributed": True,
                            "basis": "quantity_match", "usd": 1.0, "qty": 1234.0,
                            "days": list(DAYS), "reason": "ours"}])
    m["actuals"]["measured_usd"] = 1.0
    assert any("attributed: false with no reason" in p for p in run(base_census(), m, root).problems)


def test_an_unnamed_basis_fails(root):
    m = base_model()
    m["actuals"]["ledger"][0]["basis"] = "it seems right"
    assert any("is not one of" in p for p in run(base_census(), m, root).problems)


def test_an_absent_actuals_block_is_not_a_clean_ledger(root):
    rep = run(base_census(), {"prices": {}}, root)
    assert rep.rc == 1
    assert any("no `actuals:` block" in p for p in rep.problems)


# --------------------------------------------------------------------------- the resource match
def volume_census(step_qty: float = 1.290323, *, noise: float = 0.0,
                  through: str = "2026-09-19") -> dict[str, ras.Series]:
    """A shared account-wide line with a step in it on 2026-08-12, like the real gp3 line."""
    readings: dict[str, tuple[float, float]] = {}
    for dd in range(1, 12):
        readings[f"2026-08-{dd:02d}"] = (0.387097, 4.83871)
    for dd in range(12, 32):
        q = 4.83871 + step_qty + (noise if dd % 2 else 0.0)
        readings[f"2026-08-{dd:02d}"] = (q * 0.08, q)
    dd = 1
    while f"2026-09-{dd:02d}" <= through:
        readings[f"2026-09-{dd:02d}"] = (0.6, 7.5)
        dd += 1
    return census(series(EBS, "EBS:VolumeUsage.gp3", readings))


def volume_model(**over) -> dict:
    entry = {
        "usage_type": "EBS:VolumeUsage.gp3", "service": EBS, "attributed": True,
        "basis": "resource_match", "shared_line": True, "usd": 4.091183, "qty": None,
        "resource_monthly_qty": 40.0, "price_key": "ebs_gp3_gb_month",
        "first_billed_day": "2026-08-12",
        "step_measurement": {"baseline_days": ["2026-08-01", "2026-08-11"],
                             "step_days": ["2026-08-14", "2026-08-31"],
                             "days_in_step_month": 31},
        "prorata": [{"month": "2026-08", "days_held": 20, "days_in_month": 31},
                    {"month": "2026-09", "days_held": 19, "days_in_month": 30}],
        "reason": "the volume nobody deleted",
    }
    entry.update(over)
    model = base_model(measured_usd=4.091183, services_touched=[EBS], ledger=[entry])
    return model


def test_the_volume_step_control_passes_and_both_of_its_numbers_are_derived(root):
    """The control for the hardest basis: 1.290323 GB-Mo/day x 31 = 40.0 GB identifies the resource,
    and 40 x $0.08 prorated over 20/31 + 19/30 days reproduces the recorded dollars. Two numbers, two
    derivations (`feedback_two_numbers_two_claims`)."""
    rep = run(volume_census(), volume_model(), root)
    assert rep.problems == [], rep.problems
    assert rep.rc == 0


def test_a_step_that_does_not_match_the_resource_size_fails(root):
    """A 40 GB entry against a step worth 20 GB. This is the arm that would have caught the ledger
    trusting `provision.py`'s declared `VOLUME_GIB = 20` over the meter."""
    rep = run(volume_census(step_qty=0.645161), volume_model(), root)
    assert any("names a resource of 40.000" in p for p in rep.problems), rep.problems


def test_a_step_between_two_noisy_regions_is_refused_rather_than_reported(root):
    """`feedback_narrow_interval_is_not_stability`: the difference of two means is only a step if the
    regions are flat. Here the step region wobbles by more than half the step."""
    rep = run(volume_census(noise=0.9), volume_model(), root)
    assert any("not flat enough" in p for p in rep.problems), rep.problems


def test_prorated_dollars_that_do_not_reproduce_the_recorded_figure_fail(root):
    rep = run(volume_census(), volume_model(usd=6.0), root)
    assert any("prorated comes to $4.0912" in p and "records $6.0000" in p for p in rep.problems)


def test_a_derived_dollar_figure_refuses_to_lean_on_an_unverified_price(root):
    m = volume_model()
    m["prices"]["ebs_gp3_gb_month"] = {"usd": 0.08, "verified": False}
    assert any("verified: false" in p for p in run(volume_census(), m, root).problems)


def test_a_price_key_that_is_not_in_the_model_fails(root):
    m = volume_model(price_key="ebs_gp4_gb_month")
    assert any("is not in cost_model.yaml's prices" in p for p in run(volume_census(), m, root).problems)


def test_a_resource_still_billing_past_the_recorded_days_held_nags(root):
    """The staleness alarm. The orphaned volume keeps billing every day it is not deleted, so a
    ledger that was right yesterday is wrong today — and the fix named in the message is deletion,
    not an edit to the figure (`feedback_perishable_claim_cannot_be_checked`)."""
    rep = run(volume_census(through="2026-09-30"), volume_model(), root)
    assert any("day(s) stale" in p and "deleting it is the fix" in p for p in rep.problems), rep.problems


def test_a_resource_match_with_no_step_measurement_cannot_be_checked_at_all(root):
    m = volume_model()
    del m["actuals"]["ledger"][0]["step_measurement"]
    assert any("needs step_measurement" in p for p in run(volume_census(), m, root).problems)


def test_a_one_day_baseline_is_not_a_baseline(root):
    m = volume_model(step_measurement={"baseline_days": ["2026-08-11", "2026-08-11"],
                                       "step_days": ["2026-08-14", "2026-08-31"],
                                       "days_in_step_month": 31})
    assert any("a pair of points" in p for p in run(volume_census(), m, root).problems)


def test_a_line_that_went_down_where_a_resource_appeared_fails(root):
    rep = run(volume_census(step_qty=-1.0), volume_model(), root)
    assert any("not positive" in p for p in rep.problems)


# ------------------------------------------------------------------------- readers and small parts
def test_a_reversed_range_raises_instead_of_expanding_to_nothing(root):
    """An empty expansion would make every arithmetic check over it pass vacuously."""
    with pytest.raises(ValueError, match="ends before it starts"):
        ras.expand_range(["2026-08-11", "2026-08-01"])
    assert ras.expand_range(["2026-08-01", "2026-08-03"]) == [
        "2026-08-01", "2026-08-02", "2026-08-03"]


def test_a_census_keyed_on_the_usage_type_alone_is_refused_on_read(tmp_path):
    """The defect this file's own subject had in its first version, made unrepresentable."""
    p = tmp_path / "c.json"
    p.write_text(json.dumps({GUARD: {"2026-08-10": [1.0, 2.0]}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="merges services that share a name"):
        ras.census_from_json(p)
    p.write_text(json.dumps({ras.key_of(BEDROCK, GUARD): {"2026-08-10": [1.0, 2.0]}}),
                 encoding="utf-8")
    c, estimated, days, read_at = ras.census_from_json(p)
    assert list(c) == [f"{BEDROCK} | {GUARD}"] and days == 1


def test_every_one_of_the_five_producers_can_place_a_day(tmp_path):
    """`feedback_derive_from_every_producer`: the day list is derived from five families, and an arm
    that only plants session logs would pass while four of them were broken."""
    for rel in ("evidence/r20260801T000000Z", "runner/.state/incoming/20260802T000000Z"):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results" / "day2_replication_2026-08-03.json").write_text("{}", encoding="utf-8")
    (tmp_path / "results" / "phase1").mkdir()
    (tmp_path / "results" / "phase1" / "run-20260804T010203Z.json").write_text("{}", encoding="utf-8")
    (tmp_path / "session-logs").mkdir()
    (tmp_path / "session-logs" / "x-20260805.log").write_text("x", encoding="utf-8")
    days = ras.derive_project_days(tmp_path)
    assert sorted(days) == ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"]
    assert days["2026-08-01"] == {"evidence-run"}
    assert days["2026-08-02"] == {"runner-transport"}
    assert days["2026-08-05"] == {"session-log"}


def test_estimated_days_are_reported_because_a_figure_over_them_can_still_move(root):
    rep = run(base_census(), base_model(), root, estimated=["2026-08-11", "2026-08-10"])
    assert rep.rc == 0
    assert any("still marked Estimated" in n and "2026-08-10..2026-08-11" in n for n in rep.notes)


def test_no_estimated_days_and_cannot_tell_are_different_notes(root):
    """The tri-state. An offline replay of the first saved census printed the same clean summary as the
    live run while silently losing its loudest caveat -- twenty September days still provisional. A
    source that cannot answer must say so, not answer "none"."""
    silent = run(base_census(), base_model(), root, estimated=None)
    assert any("CANNOT say whether" in n for n in silent.notes)
    known_none = run(base_census(), base_model(), root, estimated=[])
    assert not any("CANNOT say whether" in n or "still marked Estimated" in n
                   for n in known_none.notes)


def test_a_saved_census_carries_its_estimated_days_and_a_legacy_file_admits_it_cannot(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({ras.CENSUS_ESTIMATED_KEY: ["2026-09-20"],
                             ras.CENSUS_LINES_KEY: {ras.key_of(BEDROCK, GUARD):
                                                    {"2026-08-10": [1.0, 2.0]}}}), encoding="utf-8")
    c, estimated, days, read_at = ras.census_from_json(p)
    assert estimated == ["2026-09-20"] and days == 1 and list(c) == [f"{BEDROCK} | {GUARD}"]

    p.write_text(json.dumps({ras.key_of(BEDROCK, GUARD): {"2026-08-10": [1.0, 2.0]}}),
                 encoding="utf-8")
    c, estimated, days, read_at = ras.census_from_json(p)
    assert estimated is None, "a legacy file has no field for them; None means 'cannot say'"
    assert read_at is None, "and it cannot say when the meter was read either"


# ---------------------------------------------------------------------------
# The stamp. `actuals.read_at` in cost_model.yaml first held "2026-09-21T21:49Z", typed by hand while
# the reading it described finished at 14:58:15Z -- local time on a UTC+8 machine wearing a Z, seven
# hours in the future. The only rule was "not empty", and an impossible stamp is not empty. These arms
# are over the PRODUCER; the refusal that convicts the typo lives in estimate_cost.py and has its own.
# Every arm injects its clock, because an arm about "in the future" written against datetime.now()
# would pass or fail by the timezone of whoever ran it -- the defect under test.
# ---------------------------------------------------------------------------

def test_utc_stamp_is_utc_even_when_the_clock_it_is_given_is_not():
    """The whole defect in one arm: 22:49 in Taipei is 14:49Z, and the stamp must say 14:49Z."""
    taipei = timezone(timedelta(hours=8))
    local = datetime(2026, 9, 21, 22, 49, 3, tzinfo=taipei)
    assert ras.utc_stamp(local) == "2026-09-21T14:49:03Z"
    assert ras.utc_stamp(datetime(2026, 9, 21, 14, 49, 3, tzinfo=timezone.utc)) \
        == "2026-09-21T14:49:03Z"


def test_utc_stamp_has_no_default_that_reads_the_wall_clock_in_tests():
    """Not a tautology: it asserts the two spellings of the same instant agree, so a future
    implementation that formatted the naive local fields would fail here rather than on a machine
    in another timezone eight months from now."""
    utc = datetime(2026, 9, 21, 15, 32, 19, tzinfo=timezone.utc)
    west = utc.astimezone(timezone(timedelta(hours=-7)))
    assert west.hour == 8, "sanity: the fixture really is a different wall-clock reading"
    assert ras.utc_stamp(west) == ras.utc_stamp(utc) == "2026-09-21T15:32:19Z"


def test_a_saved_census_carries_the_stamp_and_the_replay_reads_it_back(tmp_path):
    """`feedback_two_readers_one_format`: the writer is `census_to_json` and the reader is
    `census_from_json`, and the field is worth nothing unless they agree on it.

    The round trip goes through the WRITER, not through a hand-written fixture. The first version of
    this arm wrote the JSON itself, and a mutant that dropped `read_at` from the real writer left all
    48 arms green -- the arm cited this very rule in its docstring while testing only one side of it.
    """
    p = tmp_path / "sub" / "c.json"   # also proves the writer creates its parent
    c_in = census(series(BEDROCK, GUARD, {"2026-08-10": (1.0, 2.0)}))
    ras.census_to_json(p, c_in, [], "2026-09-21T15:32:19Z")
    c, estimated, days, read_at = ras.census_from_json(p)
    assert read_at == "2026-09-21T15:32:19Z"
    assert estimated == [] and days == 1 and list(c) == [f"{BEDROCK} | {GUARD}"]
    assert c[f"{BEDROCK} | {GUARD}"].days == {"2026-08-10": (1.0, 2.0)}, \
        "and the numbers survive the round trip, not just the metadata"

    # A NON-EMPTY list, because `[]` round-trips identically whether the writer wrote the field or
    # omitted it. That is not pedantry: the mutant that stopped writing `estimated_days` survived all
    # 48 arms until this line existed, and it survived for a second reason worth keeping separate --
    # the reader coerced an absent field to `[]` instead of to "cannot say".
    q = tmp_path / "with-estimated.json"
    ras.census_to_json(q, c_in, ["2026-09-19", "2026-09-20"], "2026-09-21T15:32:19Z")
    _, estimated2, _, _ = ras.census_from_json(q)
    assert estimated2 == ["2026-09-19", "2026-09-20"]


def test_a_wrapped_census_missing_the_estimated_field_cannot_say_rather_than_saying_none(tmp_path):
    """The tri-state, one level in. A wrapped file is not automatically an informed file: if the field
    is absent it must read as `None`, not as "the meter marked no day Estimated" -- which is a real
    answer this project publishes as a caveat and would have published falsely."""
    p = tmp_path / "c.json"
    p.write_text(json.dumps({ras.CENSUS_READ_AT_KEY: "2026-09-21T15:32:19Z",
                             ras.CENSUS_LINES_KEY: {ras.key_of(BEDROCK, GUARD):
                                                    {"2026-08-10": [1.0, 2.0]}}}), encoding="utf-8")
    _, estimated, _, read_at = ras.census_from_json(p)
    assert estimated is None, "absent is not empty"
    assert read_at == "2026-09-21T15:32:19Z", "and the other field is unaffected by its absence"

    p.write_text(json.dumps({ras.CENSUS_ESTIMATED_KEY: [],
                             ras.CENSUS_LINES_KEY: {ras.key_of(BEDROCK, GUARD):
                                                    {"2026-08-10": [1.0, 2.0]}}}), encoding="utf-8")
    _, estimated, _, _ = ras.census_from_json(p)
    assert estimated == [], "present-and-empty is an answer: the meter marked none"


def test_a_wrapped_census_without_a_stamp_says_it_cannot_rather_than_guessing(tmp_path):
    """A wrapped file written before the field existed is still wrapped. It must report silence, not
    substitute its own mtime -- which on this machine is when the file was last COPIED
    (`feedback_copy2_serves_the_mutant`)."""
    p = tmp_path / "c.json"
    p.write_text(json.dumps({ras.CENSUS_ESTIMATED_KEY: ["2026-09-20"],
                             ras.CENSUS_LINES_KEY: {ras.key_of(BEDROCK, GUARD):
                                                    {"2026-08-10": [1.0, 2.0]}}}), encoding="utf-8")
    _, estimated, _, read_at = ras.census_from_json(p)
    assert read_at is None and estimated == ["2026-09-20"], \
        "the two fields are independent: knowing the Estimated days does not date the reading"
