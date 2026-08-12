"""Arms for lib/oracle.py — the layer that turns sealed prose into verdicts.

What is worth testing here is not "does EXISTENCE return TRUE when observed_bool is True".
It is the set of ways this module could publish a verdict the sealed pre-registration did
not license:

1. **A binding could disagree with its prose.** `prose_support_problems()` is the screen for
   that, so the screen itself is tested by mutation: a gate that cannot fail is the defect
   it exists to catch (`feedback_vacuous_test_check`). Eight arms below inject a wrong
   threshold, a fabricated prose token, an undeclared unit, a borrowed sample-size cell and
   a class/kind mismatch, and assert the gate objects to each.
2. **A verdict could be forced.** RECORDED, INCONCLUSIVE and NOT_TESTABLE exist because
   TRUE/FALSE cannot express the seal. Each is asserted reachable, and asserted to stay out
   of `DECISIVE`.
3. **A direction could be inverted.** F8-2's oracle claims CLASSIC gives *no* protection for
   zh/ja/ko, so interval *overlap* confirms the document. That is the one place where the
   obvious implementation is backwards, and it gets a paired arm with DISJOINT_INTERVALS on
   identical numbers to prove the two kinds genuinely disagree.
4. **A correction could be weakened silently.** BH over one p-value is not BH over twelve;
   a confirmatory family that grew past 8 changes alpha for its other members after the
   fact. Both are asserted to surface in the output rather than in nobody's notes.
5. **A case could be unevaluable.** `family_of` used to raise for 11 of the 93 sealed cases,
   so `evaluate()` crashed on 12% of the suite. The sweep arm runs every case through
   `evaluate()` with a minimal observation for its kind, which is what found that.
"""

from __future__ import annotations

import math

import pytest

import oracle as O
import phase1 as P


# ---------------------------------------------------------------------------
# the gate is real: each mutation of a binding must make it object
# ---------------------------------------------------------------------------

def _swap(monkeypatch, cid: str, **kw):
    """Replace one binding with a mutated copy, in-place, for one test."""
    old = O.BINDINGS[cid]
    fields = {"kind": old.kind, "thresholds": old.thresholds, "prose": old.prose,
              "unit": old.unit, "transform": old.transform, "cell": old.cell,
              "limits_by_reference": old.limits_by_reference, "note": old.note}
    fields.update(kw)
    monkeypatch.setitem(O.BINDINGS, cid, O.Binding(**fields))


def test_the_gate_is_green_before_any_mutation():
    """The control arm. Every mutation below is meaningless if the gate starts red."""
    assert O.prose_support_problems() == []


def test_a_threshold_that_does_not_match_its_prose_is_caught(monkeypatch):
    """The `feedback_prose_is_not_verified` case: F3-2's oracle says <5%, bind it to 10%."""
    _swap(monkeypatch, "F3-2", thresholds=(0.10,))
    probs = O.prose_support_problems()
    assert any("F3-2" in p and "yields 0.05" in p for p in probs), probs


def test_a_prose_token_absent_from_the_sealed_text_is_caught(monkeypatch):
    _swap(monkeypatch, "F3-1", thresholds=(0.99,), prose=("0.99",))
    assert any("F3-1" in p and "does not appear in the sealed oracle" in p
               for p in O.prose_support_problems())


def test_a_threshold_with_no_prose_token_is_caught(monkeypatch):
    """A number with no sentence behind it is an unverified constant, however right it is."""
    _swap(monkeypatch, "F3-1", prose=())
    assert any("F3-1" in p and "threshold(s) but 0 prose" in p
               for p in O.prose_support_problems())


def test_the_ms_from_s_inference_that_broke_f7_7_is_caught(monkeypatch):
    """The real defect: "60s" read as milliseconds made the threshold 60000.

    Every observed timestamp offset would have been under it, so the case would have been
    confirmed by construction — a factor of 1000 in the direction that passes.
    """
    _swap(monkeypatch, "F7-7", thresholds=(60000.0,), unit="ms")
    probs = O.prose_support_problems()
    assert any("F7-7" in p and "still the wrong comparison" in p for p in probs), probs


def test_a_consistent_conversion_into_the_wrong_unit_is_still_caught(monkeypatch):
    """The hole this arm was written to find, and did.

    Declaring F7-7's unit as "ms" and its threshold as 60000 is internally *consistent* —
    "60s" really is 60000 ms — so the prose-token check passed it. The comparison is against
    `timestamps_s`, in seconds, so a 60000 threshold is never exceeded and the case is
    confirmed by construction. Consistency with the sentence is not enough; the unit has to
    match the field being compared, which is what KIND_UNITS pins.
    """
    b = O.Binding("QUANTIZATION", thresholds=(60000.0,), prose=("60s",), unit="ms",
                  cell="publish_lag_cell")
    # The derivation is self-consistent, which is exactly why it slipped through before.
    assert math.isclose(O.parse_prose_number("60s", "ms"), 60000.0)
    monkeypatch.setitem(O.BINDINGS, "F7-7", b)
    assert any("kind QUANTIZATION compares in 's'" in p
               for p in O.prose_support_problems())


@pytest.mark.parametrize("cid,wrong", [
    ("F6-1", "s"), ("F3-1", "count"), ("F3-2", "count"), ("F2-2", "proportion"),
    ("F3-9", "ms"), ("F6-8", "s"),
])
def test_every_unit_constrained_kind_rejects_a_wrong_unit(monkeypatch, cid, wrong):
    """Swept rather than spot-checked: a per-kind table with one tested entry is one entry."""
    _swap(monkeypatch, cid, unit=wrong)
    assert any(cid in p and "the wrong comparison" in p
               for p in O.prose_support_problems())


def test_the_kind_unit_table_agrees_with_every_sealed_binding():
    """The table is an assertion about the module, so it must hold unmutated."""
    for cid, b in O.BINDINGS.items():
        want = O.KIND_UNITS.get(b.kind)
        if want is not None:
            assert b.unit == want, f"{cid}: {b.kind} declares {b.unit!r}, table says {want!r}"


def test_an_undeclared_unit_is_refused_at_construction():
    with pytest.raises(ValueError, match="unknown unit"):
        O.Binding("ZERO_EVENTS", unit="minutes")


def test_an_unnamed_transform_is_refused_at_construction():
    """An arithmetic step between the sentence and the comparison must have a name."""
    with pytest.raises(ValueError, match="unknown transform"):
        O.Binding("ZERO_EVENTS", transform="times_1000")


def test_a_binding_may_not_both_reference_a_limit_and_pin_it():
    with pytest.raises(ValueError, match="stated by reference"):
        O.Binding("BOUNDARY", thresholds=(20.0,), prose=("20",),
                  limits_by_reference="the document's own limit table")


def test_borrowing_another_cases_sample_size_cell_is_caught(monkeypatch):
    """F3-11's cell is None because regression_cell.applies_to lists only F6-8.

    Pointing it at that cell anyway would credit F3-11 with an n designed for another case.
    """
    _swap(monkeypatch, "F3-11", cell="regression_cell")
    assert any("F3-11" in p and "applies_to does not list" in p
               for p in O.prose_support_problems())


def test_a_nonexistent_sample_size_cell_is_caught(monkeypatch):
    _swap(monkeypatch, "F3-1", cell="cell_that_does_not_exist")
    assert any("not in the pre-registration" in p for p in O.prose_support_problems())


def test_an_excluded_case_bound_to_a_verdict_producing_kind_is_caught(monkeypatch):
    """Class X must never enter a pass count. F9-1 has no fault-injection surface."""
    _swap(monkeypatch, "F9-1", kind="EXISTENCE")
    probs = O.prose_support_problems()
    assert any("F9-1" in p and "class X" in p for p in probs), probs


def test_a_testable_case_bound_not_testable_is_caught(monkeypatch):
    """The reverse: reporting a case with an instrument as untestable hides a real result."""
    _swap(monkeypatch, "F3-6", kind="NOT_TESTABLE")
    assert any("F3-6" in p and "NOT_TESTABLE but class" in p
               for p in O.prose_support_problems())


def test_a_mandatory_mutation_case_bound_not_testable_is_caught(monkeypatch):
    _swap(monkeypatch, "F5-1", kind="NOT_TESTABLE")
    probs = O.prose_support_problems()
    assert any("F5-1" in p for p in probs)


def test_a_deleted_binding_is_caught(monkeypatch):
    """The floor exists so a removed binding cannot pass as a smaller suite."""
    b = dict(O.BINDINGS)
    b.pop("F4-1")
    monkeypatch.setattr(O, "BINDINGS", b)
    probs = O.prose_support_problems()
    assert any("F4-1 is in CASES with no binding" in p for p in probs)
    assert any(f"the floor is {O.MIN_BOUND_CASES}" in p for p in probs)


def test_a_binding_for_a_nonexistent_case_is_caught(monkeypatch):
    b = dict(O.BINDINGS)
    b["F99-1"] = O.Binding("EXISTENCE")
    monkeypatch.setattr(O, "BINDINGS", b)
    assert any("F99-1 names a case that is not in CASES" in p
               for p in O.prose_support_problems())


def test_an_operationalisation_must_state_its_rule(monkeypatch):
    """F5-6's "near 0" -> <5% is the one legitimate substitution, and it must be readable."""
    _swap(monkeypatch, "F5-6", note="operationalised somehow, trust me")
    assert any("F5-6" in p and "gestures at an operationalisation" in p
               for p in O.prose_support_problems())


def test_band_contains_requires_exactly_two_thresholds(monkeypatch):
    _swap(monkeypatch, "F6-1", thresholds=(50.0,), prose=("50",))
    assert any("F6-1" in p and "needs exactly 2 thresholds" in p
               for p in O.prose_support_problems())


# ---------------------------------------------------------------------------
# prose parsing: units are declared, never inferred
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token,unit,want", [
    ("5%", "proportion", 0.05),
    ("0.5", "proportion", 0.5),      # a bare decimal is already in the target unit
    ("60s", "s", 60.0),
    ("60s", "ms", 60000.0),          # the same token, two units, a factor of 1000 apart
    ("800ms", "ms", 800.0),
    ("800ms", "s", 0.8),
    ("19", "count", 19.0),
])
def test_prose_numbers_parse_into_the_declared_unit(token, unit, want):
    assert math.isclose(O.parse_prose_number(token, unit), want)


def test_a_percentage_cannot_be_read_as_a_duration():
    with pytest.raises(ValueError, match="cannot be compared against a duration"):
        O.parse_prose_number("5%", "ms")


def test_a_duration_cannot_be_read_as_a_count():
    with pytest.raises(ValueError, match="is a duration"):
        O.parse_prose_number("60s", "count")


def test_an_unknown_unit_is_refused():
    with pytest.raises(ValueError, match="unknown unit"):
        O.parse_prose_number("5", "furlongs")


def test_a_prose_token_match_is_digit_anchored():
    """Matching "50" as evidence for a "5" threshold is how a check becomes decorative."""
    assert O._prose_contains("5", "5 percent") is True
    assert O._prose_contains("0", "50 items") is False
    assert O._prose_contains("5", "0.85 recall") is False


def test_the_named_transforms_do_what_their_names_say():
    assert O.TRANSFORMS["identity"](7.0) == 7.0
    # ">=1 differing observation" and ">=2 distinct values" are one condition.
    assert O.TRANSFORMS["differing_to_distinct"](1.0) == 2.0
    # "near 0" is not a number; 5% is supplied, and the name says it was supplied.
    assert O.TRANSFORMS["near_zero_as_5pct"](0.0) == 0.05


# ---------------------------------------------------------------------------
# all five verdicts are reachable, and only two are decisive
# ---------------------------------------------------------------------------

def test_true_and_false_are_reachable():
    assert O.evaluate(O.Observation("F2-1", n_attempted=300, n_usable=300, adverse=0)
                      )["verdict"] == O.TRUE
    assert O.evaluate(O.Observation("F2-1", n_attempted=300, n_usable=300, adverse=1)
                      )["verdict"] == O.FALSE


def test_recorded_is_reachable_and_carries_no_prediction():
    """F5-4a/F5-4b are sealed "OUTCOME UNKNOWN — that is the experiment"."""
    rec = O.evaluate(O.Observation("F5-4a", n_attempted=1, n_usable=1,
                                   detail={"decision": "DENY"}))
    assert rec["verdict"] == O.RECORDED
    assert rec["verdict"] not in O.DECISIVE
    # The opposite observation is equally a finding, not a failure.
    other = O.evaluate(O.Observation("F5-4a", n_attempted=1, n_usable=1,
                                     detail={"decision": "ALLOW"}))
    assert other["verdict"] == O.RECORDED


def test_inconclusive_is_reachable_from_the_gap_in_f3_8s_own_oracle():
    """F3-8 is TRUE if the lower bound exceeds 0.5 and FALSE if the upper is below 0.5.

    Those do not partition. An interval spanning 0.5 satisfies neither, and the gap is in
    the sealed text — assigning it to a side would invent a decision the design declined.
    """
    rec = O.evaluate(O.Observation("F3-8", n_attempted=87, n_usable=87, adverse=44))
    assert rec["verdict"] == O.INCONCLUSIVE
    assert "do not partition" in rec["evidence"]["gap"]
    assert rec["verdict"] not in O.DECISIVE


def test_not_testable_is_reachable_and_never_counts():
    rec = O.evaluate(O.Observation("F9-1"))
    assert rec["verdict"] == O.NOT_TESTABLE
    assert rec["verdict"] not in O.DECISIVE


def test_decisive_is_exactly_true_and_false():
    assert set(O.DECISIVE) == {O.TRUE, O.FALSE}
    assert set(O.VERDICTS) - set(O.DECISIVE) == {
        O.INCONCLUSIVE, O.RECORDED, O.NOT_TESTABLE}


# ---------------------------------------------------------------------------
# the asymmetries, which are the substance
# ---------------------------------------------------------------------------

def test_f3_3_falsifies_only_on_the_lower_bound():
    """Three-way split. Comparing the point estimate to 0.10 gets it wrong both ways.

    n=58 against a 10% threshold: 0 adverse confirms, a large count refutes, and a middling
    count leaves an interval straddling 10% that supports neither statement.
    """
    conf = O.evaluate(O.Observation("F3-3", n_attempted=58, n_usable=58, adverse=0))
    assert conf["verdict"] == O.TRUE

    mid = O.evaluate(O.Observation("F3-3", n_attempted=58, n_usable=58, adverse=6))
    assert mid["verdict"] == O.INCONCLUSIVE, mid["evidence"]
    assert mid["evidence"]["one_sided_lo"] < 0.10 < mid["evidence"]["one_sided_hi"]

    ref = O.evaluate(O.Observation("F3-3", n_attempted=58, n_usable=58, adverse=20))
    assert ref["verdict"] == O.FALSE
    assert ref["evidence"]["one_sided_lo"] > 0.10


def test_a_point_estimate_over_the_threshold_is_not_enough_to_refute_f3_3():
    """p̂ = 7/58 = 12.1% is above 10%, yet the interval reaches below it.

    This is the arm that distinguishes ASYMMETRIC_FPR from `p_hat > t`: the naive
    implementation would publish "the document is wrong" from data that cannot resolve it.
    """
    rec = O.evaluate(O.Observation("F3-3", n_attempted=58, n_usable=58, adverse=7))
    assert rec["evidence"]["point"] > 0.10
    assert rec["verdict"] == O.INCONCLUSIVE


def test_f8_2_inverts_because_the_document_claims_no_protection():
    """CLASSIC is claimed to give NO discrimination for zh/ja/ko, so overlap CONFIRMS it."""
    overlapping = O.Observation("F8-2", n_attempted=60, n_usable=60,
                                detect_x=30, detect_n=60, fpr_x=28, fpr_n=60)
    separated = O.Observation("F8-2", n_attempted=60, n_usable=60,
                              detect_x=58, detect_n=60, fpr_x=1, fpr_n=60)
    assert O.evaluate(overlapping)["verdict"] == O.TRUE
    assert O.evaluate(separated)["verdict"] == O.FALSE


def test_the_inversion_is_a_real_disagreement_not_a_relabelling(monkeypatch):
    """The same numbers through DISJOINT_INTERVALS must give the opposite verdict.

    Asserting F8-2's direction alone would pass even if INDISTINGUISHABLE were a copy of
    DISJOINT_INTERVALS under another name.
    """
    obs = O.Observation("F8-2", n_attempted=60, n_usable=60,
                        detect_x=58, detect_n=60, fpr_x=1, fpr_n=60)
    as_indistinguishable = O.evaluate(obs)["verdict"]
    _swap(monkeypatch, "F8-2", kind="DISJOINT_INTERVALS")
    as_disjoint = O.evaluate(obs)["verdict"]
    assert {as_indistinguishable, as_disjoint} == {O.TRUE, O.FALSE}


@pytest.mark.parametrize("kind", ["INDISTINGUISHABLE", "DISJOINT_INTERVALS"])
@pytest.mark.parametrize("detect_n,fpr_n,which", [
    (60, 0, "false_positive"),
    (0, 60, "detection"),
    (0, 0, "detection and false_positive"),
])
def test_an_empty_stratum_is_inconclusive_not_a_crash(monkeypatch, kind, detect_n,
                                                      fpr_n, which):
    """A two-interval kind with one denominator at zero has nothing to compare.

    Both kinds, because the guard sits above the branch and a fix that only covered the
    INDISTINGUISHABLE half would leave F3-5/F3-7/F5-5 exposed to the same crash.

    Discovered live: F8-2's `--n 3` smoke took a 3-item head of a corpus whose 6 CLEAN
    items sit at positions 54-59, so the FPR arm was 0/0 and `wilson_ci` raised
    `ValueError: n must be positive` — *after* 24 billable ApplyGuardrail calls, with the
    collected rows discarded by the traceback. The stats layer is right to refuse (a Wilson
    interval on n=0 does not exist), so the fix belongs here: the oracle records that the
    comparison was not measured, which is the same reasoning as `not_measured`.

    `lib/arms.load_corpus(stratify_by=...)` stops it happening at the source; this arm is
    the backstop, because "the corpus is laid out the way I expect" is exactly the
    assumption that failed.
    """
    if kind != "INDISTINGUISHABLE":
        _swap(monkeypatch, "F8-2", kind=kind)
    rec = O.evaluate(O.Observation("F8-2", n_attempted=detect_n + fpr_n,
                                  n_usable=detect_n + fpr_n,
                                  detect_x=0, detect_n=detect_n,
                                  fpr_x=0, fpr_n=fpr_n))
    assert rec["verdict"] == O.INCONCLUSIVE
    assert which in rec["evidence"]["reason"]
    assert "n=0" in rec["evidence"]["reason"]


def test_the_empty_stratum_guard_is_not_reachable_by_n_usable(monkeypatch):
    """Why the guard cannot live upstream: n_usable is the SUM of the two denominators.

    This is the arm that justifies the guard's existence rather than its behaviour. With
    detect_n=60 and fpr_n=0 the observation reports n_usable=60 — `require_measured` sees a
    healthy run and `n_met` can be satisfied against a pre-registered 60 — while one of the
    two rates the verdict is computed from does not exist. Any check phrased on the total
    is blind to it by construction.
    """
    obs = O.Observation("F8-2", n_attempted=60, n_usable=60,
                       detect_x=30, detect_n=60, fpr_x=0, fpr_n=0)
    rec = O.evaluate(obs)
    assert obs.n_usable == 60 and rec["verdict"] == O.INCONCLUSIVE
    assert rec["evidence"]["why_not_caught_upstream"]
    # And the healthy case still decides, so the guard is not swallowing live data.
    ok = O.evaluate(O.Observation("F8-2", n_attempted=120, n_usable=120,
                                 detect_x=30, detect_n=60, fpr_x=28, fpr_n=60))
    assert ok["verdict"] in (O.TRUE, O.FALSE)


def test_f6_6s_open_upper_bound_cannot_be_exceeded():
    """"31s+" admits any larger value, so only the 800ms floor is falsifiable.

    Reporting F6-6 as though both ends were testable would credit the document with a
    prediction it did not make.
    """
    assert O.band_upper_is_open("F6-6") is True
    assert O.band_upper_is_open("F6-1") is False
    huge = [40_000.0] * 200
    rec = O.evaluate(O.Observation("F6-6", n_attempted=200, n_usable=200,
                                   latencies_ms=huge))
    assert rec["verdict"] == O.TRUE
    assert "no measured value can exceed it" in rec["evidence"]["note_open"]
    # The floor still bites.
    tiny = [10.0] * 200
    assert O.evaluate(O.Observation("F6-6", n_attempted=200, n_usable=200,
                                    latencies_ms=tiny))["verdict"] == O.FALSE


def test_a_closed_band_is_falsifiable_at_both_ends():
    """F6-1's band is 50-200ms, checked as p50 >= 50 and p99 <= 200.

    The upper arm uses a 975/25 split, not 990/10: ten values above the band in a thousand
    do not move the p99 past the 990th order statistic, so the naive "add a few slow calls"
    mutation leaves the verdict TRUE. That is correct behaviour — a claim about the 99th
    percentile is not falsified by the top 1% — and getting it wrong the first time is why
    the split is spelled out here rather than left as a round number.
    """
    inside = [120.0] * 1000
    assert O.evaluate(O.Observation("F6-1", n_attempted=1000, n_usable=1000,
                                    latencies_ms=inside))["verdict"] == O.TRUE
    below_floor = [10.0] * 1000
    assert O.evaluate(O.Observation("F6-1", n_attempted=1000, n_usable=1000,
                                    latencies_ms=below_floor))["verdict"] == O.FALSE
    over = [120.0] * 975 + [5_000.0] * 25
    rec = O.evaluate(O.Observation("F6-1", n_attempted=1000, n_usable=1000,
                                   latencies_ms=over))
    assert rec["evidence"]["p99"] > 200.0
    assert rec["verdict"] == O.FALSE


def test_a_tail_thinner_than_the_quantile_does_not_falsify_a_band():
    """The companion to the arm above: 1% of calls over the band leaves p99 inside it."""
    over = [120.0] * 990 + [5_000.0] * 10
    rec = O.evaluate(O.Observation("F6-1", n_attempted=1000, n_usable=1000,
                                   latencies_ms=over))
    assert rec["evidence"]["p99"] <= 200.0
    assert rec["verdict"] == O.TRUE, (
        "a p99 claim is not falsified by the top 1%; reporting it as falsified would be "
        "publishing a refutation the band never exposed itself to")


def test_no_p99_is_published_below_100_observations():
    rec = O.evaluate(O.Observation("F6-1", n_attempted=40, n_usable=40,
                                   latencies_ms=[120.0] * 40))
    assert rec["evidence"]["p99"] is None
    assert "a p99 does not exist" in rec["evidence"]["note"]


def test_a_negative_latency_residual_falsifies_the_decomposition_model():
    """Structural, not a number tweak: overlapping hops break §6.1, §6.3 and §6.4 together."""
    ok = O.evaluate(O.Observation("F6-7", n_attempted=200, n_usable=200,
                                  residual_ci=(2.0, 30.0)))
    bad = O.evaluate(O.Observation("F6-7", n_attempted=200, n_usable=200,
                                   residual_ci=(-40.0, -5.0)))
    assert ok["verdict"] == O.TRUE
    assert bad["verdict"] == O.FALSE
    assert "hops overlap" in bad["evidence"]["structural"]


def test_stratum_purity_is_falsified_by_one_mixed_stratum():
    """F2-3: if the decision is a function of the score, every stratum must be pure."""
    scores = [0.2, 0.2, 0.6, 0.6, 0.8, 0.8]
    pure = O.evaluate(O.Observation("F2-3", n_attempted=6, n_usable=6,
                                    scores=scores, decisions=[0, 0, 1, 1, 1, 1]))
    mixed = O.evaluate(O.Observation("F2-3", n_attempted=6, n_usable=6,
                                     scores=scores, decisions=[0, 0, 0, 1, 1, 1]))
    assert pure["verdict"] == O.TRUE
    assert mixed["verdict"] == O.FALSE


def test_a_zero_event_result_carries_a_quantified_ceiling():
    """`single_counterexample.note` requires it: 300 clean trials and 3 must not read alike."""
    big = O.evaluate(O.Observation("F2-1", n_attempted=300, n_usable=300, adverse=0))
    small = O.evaluate(O.Observation("F2-1", n_attempted=3, n_usable=3, adverse=0))
    assert big["verdict"] == small["verdict"] == O.TRUE
    assert big["evidence"]["ceiling_one_sided"] < small["evidence"]["ceiling_one_sided"]
    assert big["evidence"]["ceiling_method"] == "exact 1-alpha^(1/n)"
    assert big["evidence"]["ceiling_one_sided"] == pytest.approx(0.00995, abs=5e-4)


def test_quantization_uses_the_declared_second_grid():
    """The arm that would have passed vacuously under the ms bug."""
    on_grid = O.evaluate(O.Observation("F7-7", n_attempted=30, n_usable=30,
                                       timestamps_s=[60.0, 120.0, 180.0]))
    off_grid = O.evaluate(O.Observation("F7-7", n_attempted=30, n_usable=30,
                                        timestamps_s=[60.0, 123.4, 180.0]))
    assert on_grid["verdict"] == O.TRUE
    assert off_grid["verdict"] == O.FALSE
    assert on_grid["evidence"]["grid_s"] == 60.0


def test_an_alarm_period_below_the_publish_lag_falsifies_f7_6():
    ok = O.evaluate(O.Observation("F7-6", n_attempted=30, n_usable=30,
                                  lag_p90_s=90.0, alarm_periods_s=[300.0, 600.0]))
    bad = O.evaluate(O.Observation("F7-6", n_attempted=30, n_usable=30,
                                   lag_p90_s=90.0, alarm_periods_s=[60.0, 300.0]))
    assert ok["verdict"] == O.TRUE
    assert bad["verdict"] == O.FALSE
    assert bad["evidence"]["periods_below_lag"] == [60.0]


def test_the_roc_lattice_cannot_exceed_seven_vertices():
    ok = O.evaluate(O.Observation("F3-9", n_attempted=87, n_usable=87,
                                  operating_points=7, argmax_j_interior=True))
    too_many = O.evaluate(O.Observation("F3-9", n_attempted=87, n_usable=87,
                                        operating_points=9, argmax_j_interior=True))
    degenerate = O.evaluate(O.Observation("F3-9", n_attempted=87, n_usable=87,
                                          operating_points=7, argmax_j_interior=False))
    assert ok["verdict"] == O.TRUE
    assert too_many["verdict"] == O.FALSE
    assert degenerate["verdict"] == O.FALSE, "a J peak at tau=0 or 1 means no usable signal"


def test_upper_below_reports_a_shortfall_as_the_reason_rather_than_a_refutation():
    """F5-6's rule is decidable at the pre-registered n, so a gap can only be a shortfall."""
    short = O.evaluate(O.Observation("F5-6", n_attempted=5, n_usable=5, adverse=0))
    assert short["verdict"] == O.INCONCLUSIVE
    assert "the shortfall is the reason, not the data" in short["evidence"]["gap"]


def test_f5_6_is_refuted_at_full_n_by_the_observation_that_prompted_it():
    """DC-2: the prior 5/5 detection without input tags predicts REFUTED, not confirmed.

    §3.2 says an untagged prompt attack is not detected; the pilot saw 5/5 detected. At the
    pre-registered n with that rate, the recall upper bound is nowhere near "near 0".
    """
    rec = O.evaluate(O.Observation("F5-6", n_attempted=87, n_usable=87, adverse=87))
    assert rec["verdict"] == O.FALSE


# ---------------------------------------------------------------------------
# a control that was never load-bearing
# ---------------------------------------------------------------------------

def test_an_unrecorded_mandatory_mutation_downgrades_true_to_inconclusive():
    rec = O.evaluate(O.Observation("F5-1", n_attempted=120, n_usable=120, adverse=0))
    assert O.mutation_is_mandatory("F5-1")
    assert rec["verdict"] == O.INCONCLUSIVE
    assert any("not evidence that it is doing work" in n for n in rec["notes"])


def test_a_mutation_that_did_not_invert_makes_the_verdict_false():
    """Removing the control changed nothing, so the control is not doing the work."""
    rec = O.evaluate(O.Observation("F5-1", n_attempted=120, n_usable=120, adverse=0,
                                   mutation_inverted=False))
    assert rec["verdict"] == O.FALSE
    assert any("not load-bearing" in n for n in rec["notes"])


def test_an_inverted_mutation_leaves_true_standing():
    rec = O.evaluate(O.Observation("F5-1", n_attempted=120, n_usable=120, adverse=0,
                                   mutation_inverted=True))
    assert rec["verdict"] == O.TRUE
    assert rec["mutation_required"] is True


def test_a_case_with_no_mandatory_mutation_is_not_downgraded():
    """Mutation control for the two arms above: the downgrade must be selective."""
    rec = O.evaluate(O.Observation("F2-1", n_attempted=300, n_usable=300, adverse=0))
    assert O.mutation_is_mandatory("F2-1") is False
    assert rec["verdict"] == O.TRUE
    assert rec["mutation_required"] is False


def test_a_false_verdict_is_not_rescued_by_a_missing_mutation():
    """The downgrade applies to TRUE only; a refutation stands on its own arm."""
    rec = O.evaluate(O.Observation("F5-1", n_attempted=120, n_usable=120, adverse=3))
    assert rec["verdict"] == O.FALSE


# ---------------------------------------------------------------------------
# n against the pre-registered cell
# ---------------------------------------------------------------------------

def test_a_shortfall_is_recorded_on_the_verdict_it_weakens():
    rec = O.evaluate(O.Observation("F2-1", n_attempted=300, n_usable=240, adverse=0))
    assert rec["n_met"] is False
    assert any("below the pre-registered 300" in n for n in rec["notes"])


def test_the_interval_is_built_on_usable_not_attempted_trials():
    """lib/checkpoint.py keeps failures out of results, so a cell can shrink silently."""
    rec = O.evaluate(O.Observation("F2-1", n_attempted=300, n_usable=240, adverse=0))
    assert rec["evidence"]["n"] == 240


def test_f3_4s_n_is_per_entity_not_the_corpus_size():
    """F3-4 is in two cells; the per-entity oracle takes the smaller n.

    Choosing 87 would make a per-entity result look ~8x better powered than it is.
    """
    assert O.planned_n("F3-4") == 11


def test_f3_11_has_no_pre_registered_n_and_says_so():
    """A structural finding about the seal, not an omission here: regression_cell.applies_to
    lists only F6-8, so no cell covers F3-11's +7d/+30d re-runs (DEV-P1-1)."""
    assert O.BINDINGS["F3-11"].cell is None
    assert O.planned_n("F3-11") is None
    rec = O.evaluate(O.Observation("F3-11", n_attempted=50, n_usable=50,
                                   improved=True, p_value=0.001))
    assert rec["n_met"] is True, "no planned n means no shortfall to report"
    assert rec["planned_n"] is None


def test_f6_7_uses_the_cell_that_actually_lists_it():
    """latency_arm_p99.applies_to omits F6-7, so its n is the p50/p90 cell's 200."""
    assert O.BINDINGS["F6-7"].cell == "latency_arm_p50_p90_only"
    assert O.planned_n("F6-7") == 200


# ---------------------------------------------------------------------------
# alpha comes from the family, and the confirmatory ceiling is not computed at 0.05
# ---------------------------------------------------------------------------

def test_the_confirmatory_family_uses_its_bonferroni_alpha():
    assert O.alpha_for("F5-1") == pytest.approx(0.00625)
    assert O.alpha_for("F3-1") == pytest.approx(0.05)


def test_a_confirmatory_ceiling_is_wider_than_the_nominal_one_would_be():
    """A confirmatory bound computed at 0.05 would be narrower than the design licenses —
    the direction that flatters a safety result."""
    at_confirmatory = O.ceiling_at_zero(120, O.alpha_for("F5-1"))
    at_nominal = O.ceiling_at_zero(120, 0.05)
    assert at_confirmatory > at_nominal


def test_one_sided_bounds_are_the_two_sided_interval_at_twice_alpha():
    """The mapping the pre-registration's header asserts: level = 1 - 2*alpha."""
    import stats as S
    assert O.one_sided_hi(3, 100, 0.05) == pytest.approx(S.wilson_ci(3, 100, 0.90).hi)
    assert O.one_sided_lo(3, 100, 0.05) == pytest.approx(S.wilson_ci(3, 100, 0.90).lo)


# ---------------------------------------------------------------------------
# family placement: read from the seal, and every case placeable
# ---------------------------------------------------------------------------

def test_the_class_rule_comes_from_the_seal_not_from_a_remembered_pair():
    """The defect this replaced wrote `if cls in ("C","O")`, which matched
    members_by_class but ignored excluded_from_this_rule — so F3-10, F7-6 and F7-7 were
    handed the very rule the seal names them to withhold."""
    spec = O.prereg()["families"]["descriptive_no_test"]
    assert spec["members_by_class"] == ["C", "O"]
    for cid in spec["excluded_from_this_rule"]:
        assert O.family_of(cid) == O.UNASSIGNED, (
            f"{cid} is excluded_from_this_rule in the seal and must not receive it")


def test_a_c_class_case_still_gets_the_class_rule():
    """Mutation control for the arm above: the exclusion must be selective."""
    assert O.family_of("F1-5") == "descriptive_no_test"


def test_every_sealed_case_can_be_placed_and_given_an_alpha():
    """family_of used to raise for 11 of 93, so evaluate() crashed on 12% of the suite."""
    for cid in O.BINDINGS:
        fam = O.family_of(cid)
        assert fam in set(O.prereg()["families"]) | {O.UNASSIGNED}, cid
        assert 0 < O.alpha_for(cid) <= 0.05, cid


def test_an_unplaced_case_is_named_not_defaulted():
    """A silent descriptive_no_test would remove a correction with no record."""
    assert O.family_of("F5-4a") == O.UNASSIGNED
    assert O.UNASSIGNED not in O.prereg()["families"]


def test_the_declared_seal_gaps_are_exactly_the_unplaced_s_class_cases():
    unplaced_s = {cid for cid in O.BINDINGS
                  if O.family_of(cid) == O.UNASSIGNED and O.cases()[cid][2] == "S"}
    assert unplaced_s == set(O.DECLARED_SEAL_GAPS) == {"F10-1", "F10-3"}


def test_a_new_unplaced_s_class_case_fails_the_gate(monkeypatch):
    """The declared-gap list must not become a blanket exemption for class S."""
    b = dict(O.BINDINGS)
    b["F3-1"] = O.Binding("EXISTENCE")          # drop it out of exploratory_detection
    fams = {k: dict(v) for k, v in O.prereg()["families"].items()}
    fams["exploratory_detection"]["members"] = [
        m for m in fams["exploratory_detection"]["members"] if m != "F3-1"]
    pr = dict(O.prereg())
    pr["families"] = fams
    monkeypatch.setattr(O, "BINDINGS", b)
    monkeypatch.setattr(O, "_PREREG_CACHE", pr)
    probs = O.prose_support_problems()
    assert any("F3-1" in p and "DECLARED_SEAL_GAPS" in p for p in probs), probs


def test_a_declared_gap_that_closes_fails_the_gate(monkeypatch):
    """Checked in the closing direction too, or the list rots into a permanent excuse."""
    fams = {k: dict(v) for k, v in O.prereg()["families"].items()}
    fams["exploratory_detection"]["members"] = \
        list(fams["exploratory_detection"]["members"]) + ["F10-1"]
    pr = dict(O.prereg())
    pr["families"] = fams
    monkeypatch.setattr(O, "_PREREG_CACHE", pr)
    probs = O.prose_support_problems()
    assert any("F10-1" in p and "declaration is stale" in p for p in probs), probs


# ---------------------------------------------------------------------------
# multiplicity is a set operation
# ---------------------------------------------------------------------------

def _rec(cid, p=None, verdict=O.TRUE):
    return {"case_id": cid, "family": O.family_of(cid), "verdict": verdict,
            "p_value": p, "n_met": True, "n_usable": 1, "planned_n": 1, "kind": "EXISTENCE"}


def test_bh_runs_over_the_whole_family_not_per_case():
    """BH is a step-up over a set; running it on one p-value is a different procedure."""
    fam = "exploratory_detection"
    ps = {"F3-1": 0.001, "F3-2": 0.02, "F3-3": 0.04, "F3-5": 0.30}
    out = O.apply_family_corrections([_rec(c, p) for c, p in ps.items()])
    adj = out[fam]["adjusted"]
    assert set(adj) == set(ps)
    assert adj["F3-1"]["reject_null"] is True
    assert adj["F3-5"]["reject_null"] is False
    # Adjusted p-values are never below their raw values.
    for cid, row in adj.items():
        assert row["p_adj"] >= row["p_raw"] - 1e-12, cid


def test_a_family_whose_members_are_absent_reports_them():
    out = O.apply_family_corrections([_rec("F3-1", 0.01)])
    entry = out["exploratory_detection"]
    assert "F3-2" in entry["members_absent"]
    assert entry["records_present"] == ["F3-1"]


def test_members_without_a_p_value_are_listed_not_silently_dropped():
    """A family declared at 12 whose correction ran over 3 has been weakened."""
    out = O.apply_family_corrections([_rec("F3-1", 0.01), _rec("F3-6", None)])
    entry = out["exploratory_detection"]
    assert entry["members_without_p_value"] == ["F3-6"]
    assert set(entry["adjusted"]) == {"F3-1"}


def test_bonferroni_is_reported_as_already_applied_not_reapplied():
    out = O.apply_family_corrections([_rec("F5-1"), _rec("F5-2")])
    entry = out["confirmatory"]
    assert entry["alpha_per_hypothesis"] == pytest.approx(0.00625)
    assert "not reapplied here" in entry["applied_where"]
    assert "adjusted" not in entry


def test_a_confirmatory_family_that_grew_past_eight_is_a_seal_violation(monkeypatch):
    """A ninth member changes alpha for the other eight — after data, that is
    outcome-dependent."""
    fams = {k: dict(v) for k, v in O.prereg()["families"].items()}
    fams["confirmatory"]["members"] = list(fams["confirmatory"]["members"]) + ["F5-5"]
    pr = dict(O.prereg())
    pr["families"] = fams
    monkeypatch.setattr(O, "_PREREG_CACHE", pr)
    out = O.apply_family_corrections([_rec("F5-1")])
    assert "seal_violation" in out["confirmatory"]
    assert "frozen at 8" in out["confirmatory"]["seal_violation"]


def test_the_frozen_confirmatory_family_passes_unmutated():
    """Mutation control: the violation check must not fire on the sealed membership."""
    out = O.apply_family_corrections([_rec("F5-1")])
    assert "seal_violation" not in out["confirmatory"]


def test_an_unassigned_case_is_reported_as_a_seal_gap():
    out = O.apply_family_corrections([_rec("F10-1", 0.01), _rec("F5-4a", None)])
    entry = out[O.UNASSIGNED]
    assert set(entry["records_present"]) == {"F10-1", "F5-4a"}
    assert entry["uncorrected_p_values"] == ["F10-1"]
    assert "no multiplicity correction is defined" in entry["seal_gap"]


def test_a_p_value_under_a_no_correction_family_is_flagged():
    """single_counterexample declares correction: none, so a p-value there is uncorrected."""
    out = O.apply_family_corrections([_rec("F2-1", 0.03)])
    assert out["single_counterexample"]["uncorrected_p_values"] == ["F2-1"]
    assert "seal_gap" in out["single_counterexample"]


def test_a_no_correction_family_without_p_values_is_not_flagged():
    """Mutation control for the arm above."""
    out = O.apply_family_corrections([_rec("F2-1", None)])
    assert "seal_gap" not in out["single_counterexample"]


def test_paired_improvement_returns_a_raw_p_value_for_the_family_step():
    rec = O.evaluate(O.Observation("F8-3", n_attempted=60, n_usable=60,
                                   improved=True, p_value=0.03))
    assert rec["p_value"] == 0.03
    assert "the p-value is raw" in rec["evidence"]["note"]


def test_paired_improvement_needs_both_direction_and_significance():
    sig_wrong_way = O.evaluate(O.Observation("F8-3", n_attempted=60, n_usable=60,
                                             improved=False, p_value=0.001))
    right_way_not_sig = O.evaluate(O.Observation("F8-3", n_attempted=60, n_usable=60,
                                                 improved=True, p_value=0.40))
    assert sig_wrong_way["verdict"] == O.FALSE
    assert right_way_not_sig["verdict"] == O.FALSE


# ---------------------------------------------------------------------------
# amendment eligibility is deliberately incomplete
# ---------------------------------------------------------------------------

def test_amendment_blockers_says_it_is_not_exhaustive():
    """A caller treating an empty blocker list as permission to amend is wrong."""
    rec = O.evaluate(O.Observation("F5-1", n_attempted=120, n_usable=120, adverse=0,
                                   mutation_inverted=True))
    b = O.amendment_blockers(rec)
    assert b["blockers"] == []
    assert b["clear_here"] is True
    assert "check_amendment_readiness.py" in b["blockers_are_not_exhaustive"]
    assert "separate-calendar-days" in b["blockers_are_not_exhaustive"]


def test_a_recorded_verdict_supports_no_amendment():
    rec = O.evaluate(O.Observation("F5-4a", n_attempted=1, n_usable=1,
                                   detail={"decision": "DENY"}))
    b = O.amendment_blockers(rec)
    assert b["clear_here"] is False
    assert any("supports no amendment" in x for x in b["blockers"])


def test_an_inconclusive_verdict_supports_no_amendment():
    rec = O.evaluate(O.Observation("F3-8", n_attempted=87, n_usable=87, adverse=44))
    assert O.amendment_blockers(rec)["clear_here"] is False


def test_a_shortfall_blocks_an_amendment_even_with_a_decisive_verdict():
    rec = O.evaluate(O.Observation("F2-1", n_attempted=300, n_usable=100, adverse=1))
    b = O.amendment_blockers(rec)
    assert rec["verdict"] == O.FALSE
    assert any("below the pre-registered" in x for x in b["blockers"])


def test_a_rollup_shortfall_message_matches_the_computation_that_produced_it():
    """The published blocker for F3-4 read "n_usable=93 is below the pre-registered 11".

    Every number in that sentence was correct and the sentence was false. F3-4's and F3-8's
    sealed n is **per stratum** (11 per PII entity, 120 per prompt-attack subtype), so both
    scripts override the case-level `n_met` with the AND over strata — but
    `amendment_blockers` composed its text from `rec["n_usable"]` and `rec["planned_n"]`,
    joining a POOLED numerator to a per-stratum denominator (DEVIATIONS.md/DEV-P1-12).

    The shortfall was real, which is what makes the wording dangerous rather than untidy: a
    reader who checks 93 against 11 finds nonsense and may dismiss a true blocker. This arm
    is the `feedback_label_must_match_computation` check for the blocker layer — a figure
    must be labelled with the computation that produced it.
    """
    # 31 PII entities, sealed n=11 each; two strata short, and 93 pooled observations —
    # the exact shape of the published record.
    strata = {f"ENT_{i:02d}": {"x": 11, "n": 11} for i in range(29)}
    strata["UK_NATIONAL_INSURANCE_NUMBER"] = {"x": 2, "n": 3}
    strata["US_PASSPORT_NUMBER"] = {"x": 0, "n": 3}
    roll = P.per_stratum("F3-4", strata)
    pooled_n = sum(c["n"] for c in strata.values())
    rec = dict(O.evaluate(P.obs_proportion(
        "F3-4", [{"x": sum(c["x"] for c in strata.values()), "n_usable": pooled_n,
                  "n_attempted": pooled_n, "failure_codes": []}])))
    rec["verdict"] = roll["rollup_verdict"]
    rec = P.apply_rollup_n_met(rec, roll, unit="entity")

    assert rec["n_met"] is False
    assert rec["n_met_strata_short"] == ["UK_NATIONAL_INSURANCE_NUMBER",
                                         "US_PASSPORT_NUMBER"]

    blockers = O.amendment_blockers(rec)["blockers"]
    shortfall = [b for b in blockers if "n_met" in b or "below the pre-registered" in b]
    assert len(shortfall) == 1, blockers
    msg = shortfall[0]

    # The false sentence must not be reconstructible from the message.
    assert f"n_usable={pooled_n} is below the pre-registered 11" not in msg, msg
    # And the message must name the basis and the strata that are actually short.
    assert "per entity" in msg
    assert "UK_NATIONAL_INSURANCE_NUMBER" in msg
    assert "AND over 31 strata" in msg


def test_the_stale_pooled_shortfall_note_is_removed_not_left_beside_the_override():
    """Two incompatible statements about one field let a reader pick the convenient one.

    `evaluate` writes its shortfall note before any override runs, so on a roll-up case it
    describes the pooled `n_met` that `apply_rollup_n_met` then replaces. That note reached
    the published F3-8 record alongside the corrected verdict.
    """
    strata = {"JAILBREAK": {"x": 3, "n": 3}, "PROMPT_INJECTION": {"x": 3, "n": 3},
              "PROMPT_LEAKAGE": {"x": 3, "n": 3}}
    roll = P.per_stratum("F3-8", strata)
    rec = dict(O.evaluate(P.obs_proportion(
        "F3-8", [{"x": 9, "n_usable": 9, "n_attempted": 9, "failure_codes": []}])))
    rec["verdict"] = roll["rollup_verdict"]
    assert any("below the pre-registered" in n for n in rec["notes"]), (
        "fixture must start from a record carrying evaluate's pooled note")

    fixed = P.apply_rollup_n_met(rec, roll, unit="subtype")
    assert not any("below the pre-registered" in n for n in fixed["notes"]), fixed["notes"]
    assert "per subtype" in fixed["n_met_basis"]


def test_a_rollup_that_met_every_stratum_says_so_and_blocks_nothing():
    """The satisfied branch, so `n_met_basis` cannot be a constant refusal string."""
    strata = {f"ENT_{i:02d}": {"x": 11, "n": 11} for i in range(31)}
    roll = P.per_stratum("F3-4", strata)
    rec = dict(O.evaluate(P.obs_proportion(
        "F3-4", [{"x": 341, "n_usable": 341, "n_attempted": 341, "failure_codes": []}])))
    rec["verdict"] = roll["rollup_verdict"]
    rec = P.apply_rollup_n_met(rec, roll, unit="entity")
    assert rec["n_met"] is True and rec["n_met_strata_short"] == []
    assert "every stratum reached" in rec["n_met_basis"]
    assert not any("below the pre-registered" in b
                   for b in O.amendment_blockers(rec)["blockers"])


def test_a_non_rollup_case_still_gets_the_plain_shortfall_sentence():
    """The `n_met_basis` fallback must not change the ordinary case.

    F3-1's n is per case, so `n_usable=15 below 87` is the correct sentence there and is
    what the DEV-P1-11 record shows. Pinned so the roll-up fix cannot quietly swallow it.
    """
    rec = O.evaluate(O.Observation("F3-1", n_attempted=87, n_usable=15, adverse=15))
    assert "n_met_basis" not in rec
    assert any("n_usable=15 is below the pre-registered 87" in b
               for b in O.amendment_blockers(rec)["blockers"])


def test_a_missing_mandatory_mutation_blocks_an_amendment():
    rec = O.evaluate(O.Observation("F5-2", n_attempted=120, n_usable=120, adverse=0))
    assert any("did not run, or did not invert" in x
               for x in O.amendment_blockers(rec)["blockers"])


# ---------------------------------------------------------------------------
# an absent observation must not be defaulted into a verdict
# ---------------------------------------------------------------------------

def test_an_absent_observation_raises_rather_than_manufacturing_a_verdict():
    with pytest.raises(ValueError, match="absent observations"):
        O.evaluate(O.Observation("F1-1"))          # EXISTENCE with no observed_bool


def test_zero_usable_trials_is_inconclusive_not_a_clean_result():
    """n=0 with adverse=0 satisfies "no adverse events" vacuously."""
    rec = O.evaluate(O.Observation("F2-1", n_attempted=0, n_usable=0, adverse=0))
    assert rec["verdict"] == O.INCONCLUSIVE


def test_an_unbound_case_id_raises():
    with pytest.raises(KeyError, match="no binding"):
        O.evaluate(O.Observation("F42-9"))


def test_every_kind_in_use_has_a_decision_branch():
    """`_decide` ends in `raise AssertionError`, so a kind added without a branch is fatal
    at collection time rather than at analysis time."""
    for kind in {b.kind for b in O.BINDINGS.values()}:
        assert kind in O.KINDS
    unused = set(O.KINDS) - {b.kind for b in O.BINDINGS.values()}
    assert unused == set(), f"declared but unused kinds: {unused}"


def test_the_case_and_binding_counts_match_the_floor():
    assert len(O.cases()) == len(O.BINDINGS) == O.MIN_BOUND_CASES


def test_every_evaluate_call_site_in_the_repo_passes_exactly_one_argument():
    """A static sweep, because this signature error is only reachable AFTER the money is spent.

    `evaluate` takes the Observation alone — the case id travels inside it, so a record can
    never be decided under one case's binding while carrying another's data. Writing
    `O.evaluate(CASE, obs)` is therefore not a harmless duplicate: it is a TypeError raised at
    the last line of a run's analysis, i.e. after every billed call and every IAM mutation has
    already happened. F5-1 shipped with exactly that call, and it fired after 160 invocations
    and both mutations. The cost of the mistake has nothing to do with its size, so it is
    checked across the whole repo by AST rather than trusted to review.

    Only positional arity is asserted. `evaluate(obs)` and `evaluate(obs=...)` are both fine;
    two positionals cannot be.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    offenders = []
    n_sites = 0
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or ".venv" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute) else
                    fn.id if isinstance(fn, ast.Name) else None)
            if name != "evaluate":
                continue
            # `O.evaluate` / `oracle.evaluate` / a bare `evaluate` inside this module's own tests.
            if isinstance(fn, ast.Attribute) and not isinstance(fn.value, ast.Name):
                continue
            n_sites += 1
            if len(node.args) > 1:
                offenders.append(f"{path.relative_to(root)}:{node.lineno} "
                                 f"({len(node.args)} positional args)")

    assert n_sites >= 15, (
        f"only {n_sites} evaluate() call sites were found; the sweep is not reaching the case "
        f"scripts, so it would pass with the defect present")
    assert offenders == [], (
        "evaluate() takes the Observation alone; these call sites raise TypeError at analysis "
        "time, after the run is paid for:\n  " + "\n  ".join(offenders))
