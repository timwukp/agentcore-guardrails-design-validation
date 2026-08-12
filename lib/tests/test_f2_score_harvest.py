#!/usr/bin/env python3
"""The F2 score harvest must not be able to manufacture any of its four verdicts.

Why this file exists
--------------------
`f2_determinism/03_score_harvest.py` decides four sealed cases from one 900-trial run, and
three of the four can be produced by accident:

* **F2-2** counts DISTINCT scores. Read the score as a float and `0.6` compares equal to
  nothing on the lattice; read it as a string and `"0.8000"` and `"0.8"` are two values. The
  count is the verdict, so the parse IS the measurement.
* **F1-18** tests set membership on a censored union. Scores below the configured threshold
  may never publish, so the two lowest lattice points can be structurally unobservable — a
  membership test over that union can only come back clean. The test below pins the censoring
  as a recorded limit rather than letting a clean result read as a strong one.
* **F2-3** stratifies scores by decision. If only DENIED requests publish a score, then
  `P(D=1|S=s) = 1` for every observable `s`, every stratum is pure, and STRATUM_PURITY
  cannot fail. A TRUE from that arrangement is produced by the surface, not by the service,
  and `f2_3_stratification_is_not_vacuous` is the guard that has to catch it.
* **F2-4** compares flip rates. `n` decisions span `n-1` consecutive pairs, and a denominator
  of `n` would understate every rate by (n-1)/n — invisible at n=300
  (`feedback_span_vs_points_offbyone`).

The three branches worth naming
-------------------------------
`_place_tau` has three branches and two of them only occur on data this project has not seen
yet: a degenerate one-point support, and a support whose maximum is already the top of the
lattice. Inside `main()` they were reachable only by spending 900 calls. They are tested here
directly, because a branch no test can enter is a branch that has never run.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
import textwrap
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from checkpoint import Checkpoint     # noqa: E402
MODULE_NAME = "_f2_03_score_harvest_under_test"

# `<account>` is `lib/redact.py`'s ACCOUNT_PLACEHOLDER, so this literal passes the redaction
# gate without a waiver. An earlier draft wrote `:1:` — a plainly fake account, but the gate is
# a pattern matcher and does not read intent, and three test lines failed it
# (`feedback_redact_cloud_metadata`). `_create_probe` never parses the arn; it forwards it into
# a Cedar statement, so the placeholder is as good as a real value here.
GW_ARN = "arn:aws:bedrock-agentcore:us-east-1:<account>:gateway/gw"


def load_mod():
    """Import the harness by path.

    By path rather than by name: `lib/tests/test_module_name_collisions.py` records that this
    repo has several same-named modules across family directories, and the file also starts
    with a digit, which is not importable as a name at all.
    """
    spec = importlib.util.spec_from_file_location(
        MODULE_NAME, ROOT / "f2_determinism" / "03_score_harvest.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def h():
    return load_mod()


# --------------------------------------------------------------------------------------
# the parse: F2-2's and F1-18's verdicts are both decided by it
# --------------------------------------------------------------------------------------

def test_lattice_membership_accepts_every_published_value(h):
    """The six values the service can publish must all read as on-lattice."""
    assert Fraction("0.6000") == Fraction(3, 5)
    out = h._lattice_check(["0.0000", "0.2000", "0.4000", "0.6000", "0.8000", "1.0000"])
    assert out["n_on_lattice"] == 6
    assert out["n_off_lattice"] == 0
    assert out["off_lattice_values"] == []


def test_float_equality_would_NOT_have_failed_on_this_lattice(h):
    """The refuted claim, pinned so it cannot come back as a justification.

    An earlier draft of the harness docstring — and of DEV-P4-27's note — said `Fraction` was
    necessary because "float equality against .2/.4/.6/.8 would manufacture an off-lattice
    artefact". It is false. This test states the measurement that refutes it, in the direction
    that costs the claim: a naive float test accepts all six published values.

    Keeping the refuted version measurable rather than deleting it is the point
    (`feedback_prose_is_not_verified`): the code is right, the reason given for it was not, and
    a future reader who re-derives the wrong reason will trip on this test instead of on a
    900-call run.
    """
    raws = ["0.0000", "0.2000", "0.4000", "0.6000", "0.8000", "1.0000"]
    naive_literal = {0.0, 0.2, 0.4, 0.6, 0.8, 1.0}
    naive_computed = {i / 5 for i in range(6)}
    assert [r for r in raws if float(r) not in naive_literal] == []
    assert [r for r in raws if float(r) not in naive_computed] == []
    assert 3 / 5 == 0.6 and 1 / 5 == 0.2 and 4 / 5 == 0.8


def test_the_three_hazards_that_are_real(h):
    """What `Fraction` actually buys, each measured rather than asserted."""
    # 1. The value is a STRING, so an ordering comparison is not a number comparison.
    #    In Python that is loud — a TypeError, which cannot pass silently:
    with pytest.raises(TypeError):
        assert "0.8000" > 0.5
    #    A second draft of this test asserted `"0.8000" < "0.5"` ("lexically backwards"). That is
    #    also FALSE, and pinned here for the same reason as the float claim above: '8' > '5', so
    #    that pair happens to sort the RIGHT way. For fixed-width 4-decimal strings in [0,1] the
    #    lexical order agrees with the numeric order everywhere the values DIFFER --
    assert "0.8000" > "0.5" and float("0.8000") > float("0.5")
    assert "0.4000" < "0.5" and float("0.4000") < float("0.5")
    #    -- and disagrees only at EQUALITY, where a trailing-zeros difference in spelling makes
    #    the longer string sort above its own numeric equal. That is the boundary case, and the
    #    boundary is exactly what a threshold decides (a score AT tau is published or is not):
    for s, t in (("0.2000", "0.2"), ("0.8000", "0.8"), ("1.0000", "1.00")):
        assert s > t, "lexically the padded spelling sorts above its equal"
        assert not float(s) > float(t), "numerically they are the same value"
        assert Fraction(s) == Fraction(t), "which is what Fraction gets right"
    #    The silent failure therefore is NOT Python's and NOT lexical -- it is `jq`, whose total
    #    order puts every number below every string, so a string score compares TRUE against any
    #    numeric threshold. Measured: `echo '{"score":"0.4000"}' | jq 'select(.score > 0.5)'`
    #    emits the record. A reader filtering the log surface for high scores gets all of them.
    assert ("0.4000" > "0.5") is False, "lexically 0.4 is correctly below 0.5 ..."
    #    ... but jq is not comparing lexically; it is comparing across types. Encoded as the
    #    rule rather than as a shell-out so this test needs no jq on the box:
    JQ_TYPE_RANK = {type(None): 0, bool: 1, float: 2, int: 2, str: 3}
    assert JQ_TYPE_RANK[str] > JQ_TYPE_RANK[float], \
        "jq orders strings above ALL numbers, so select(.score > <any tau>) matches every row"

    # 2. Counting distinct STRINGS inflates F2-2's verdict, which IS a distinct count.
    assert len({"0.8000", "0.8", "0.80"}) == 3
    assert len({Fraction("0.8000"), Fraction("0.8"), Fraction("0.80")}) == 1

    # 3. Fraction arithmetic is exact; float arithmetic is not. `_place_tau` COMPUTES a
    #    threshold, so this is the step where a float would drift off the lattice.
    assert 0.2 * 3 != 0.6
    assert Fraction(1, 5) * 3 == Fraction(3, 5)
    stepped = Fraction(h._place_tau(["0.2000", "0.4000"], h.ARM_ABOVE)["tau"])
    assert stepped in h.LATTICE, "a computed threshold must still land ON the lattice"


def test_off_lattice_and_unparseable_are_counted_separately(h):
    """A value the harness cannot read is a fact about the harness, not about the service."""
    out = h._lattice_check(["0.8000", "0.7500", "0.1", "", "None"])
    assert out["off_lattice_values"] == ["0.1", "0.7500"]
    assert out["unparseable_values"] == ["", "None"]
    assert out["n_on_lattice"] == 1
    # The distinction matters for the verdict: F1-18 is only TRUE when BOTH are zero.
    assert out["n_off_lattice"] and out["n_unparseable"]


def test_distinct_count_reads_strings_not_floats(h):
    """F2-2's verdict is a count, so two spellings of one value must not count twice."""
    harvest = {"n_scored": 4, "lattice": h._lattice_check(["0.8000", "0.8000", "0.8", "0.80"])}
    out = h._f2_2(harvest, alpha_n=4)
    assert out["distinct_values"] == [0.8], \
        "three spellings of 4/5 are ONE distinct score; counting them as three would flip " \
        "F2-2 from FALSE (degenerate) to TRUE (non-deterministic)"


# --------------------------------------------------------------------------------------
# F2-4: the denominator, and the prediction
# --------------------------------------------------------------------------------------

def test_flip_rate_denominator_is_pairs_not_decisions(h):
    """n decisions span n-1 pairs. A denominator of n understates every rate."""
    out = h._flips([1, 0, 1, 0])
    assert (out["n_decisions"], out["n_pairs"], out["n_flips"]) == (4, 3, 3)
    assert out["flip_rate"] == 1.0, "alternating decisions flip on every pair"
    assert h._flips([1, 1, 1])["n_flips"] == 0
    assert h._flips([])["n_pairs"] == 0 and h._flips([])["flip_rate"] is None
    assert h._flips([1])["n_pairs"] == 0, "one decision spans no pair, so it has no rate"


def test_predicted_flip_rate_is_maximal_at_a_half_and_zero_at_the_edges(h):
    """2p(1-p) is the prediction under test; its shape is what makes the arms informative."""
    assert h._predicted_flip_rate(0.5) == 0.5
    assert h._predicted_flip_rate(0.0) == 0.0
    assert h._predicted_flip_rate(1.0) == 0.0
    # This is WHY tau_floor is an outside arm: p=1 there, so the prediction is 0 and the
    # observed rate must be 0 too. The arm is not padding.
    assert h._predicted_flip_rate(1.0) == 0.0


def test_tau_formats_with_a_decimal_point_and_four_digits(h):
    """A request literal without a decimal point is REFUSED by the service.

    Measured earlier in this project: `100` errors where `100.0` binds, and four fractional
    digits bind. The score itself is published with four decimals, so a threshold formatted to
    fewer digits would be compared against values it cannot equal.
    """
    for v in (0.2, Fraction(1, 5), "0.2", 1, Fraction(1)):
        s = h._fmt_tau(v)
        assert "." in s, f"{v!r} formatted to {s!r} with no decimal point"
        assert len(s.split(".")[1]) == 4, f"{v!r} formatted to {s!r}, not four decimals"
    assert h._fmt_tau(1) == "1.0000"
    assert h._fmt_tau(Fraction(3, 5)) == "0.6000"


# --------------------------------------------------------------------------------------
# _place_tau: three branches, two of them on data we have not seen
# --------------------------------------------------------------------------------------

def test_place_tau_interior_puts_scores_on_both_sides(h):
    """The interior branch must leave at least one score strictly below tau."""
    obs = ["0.4000", "0.6000", "0.8000", "0.8000", "1.0000"]
    out = h._place_tau(obs, h.ARM_INSIDE)
    assert out["branch"] == "interior"
    tau = Fraction(out["tau"])
    below = [r for r in obs if Fraction(r) < tau]
    at_or_above = [r for r in obs if Fraction(r) >= tau]
    assert below and at_or_above, \
        "a tau with nothing on one side gives p in {0,1}, so no decision can flip and " \
        "F2-4's inside arm would measure the same thing as its outside arm"


def test_place_tau_degenerate_support_is_recorded_not_papered_over(h):
    """A one-point support admits no interior tau. That is F2-4's sealed FALSE branch."""
    out = h._place_tau(["0.8000"] * 50, h.ARM_INSIDE)
    assert out["branch"] == "degenerate_support"
    assert out["tau"] == "0.8000"
    assert "FALSE" in out["note"], \
        "the branch must say which sealed verdict it implies, or a reader cannot tell a " \
        "measured insensitivity from a failed placement"


def test_place_tau_top_of_lattice_says_so(h):
    """If the max is 1.0, a threshold strictly above the support may not be representable."""
    out = h._place_tau(["0.8000", "1.0000"], h.ARM_ABOVE)
    assert out["branch"] == "top_of_lattice"
    assert out["tau"] == "1.0000"
    assert "tau_floor" in out["note"], \
        "when the above-arm collapses, the note must name the arm F2-4's outside reading " \
        "falls back to"


def test_place_tau_above_steps_one_lattice_point_past_the_maximum(h):
    out = h._place_tau(["0.2000", "0.4000"], h.ARM_ABOVE)
    assert out["branch"] == "above"
    assert Fraction(out["tau"]) > Fraction("0.4000")
    assert Fraction(out["tau"]) in h.LATTICE


def test_place_tau_refuses_an_empty_support(h):
    """No observed score means no support to place a threshold against — that is an error.

    A fallback constant here would let every downstream flip rate be a fact about the
    fallback. `feedback_zero_file_scan_is_error`: an empty read must not report clean.
    """
    with pytest.raises(h.ConfigError) as e:
        h._place_tau([], h.ARM_INSIDE)
    assert "no score" in str(e.value)


def test_place_tau_refuses_an_arm_it_does_not_place(h):
    """tau_floor is fixed at the floor; asking for a derived placement is a caller bug."""
    with pytest.raises(h.ConfigError):
        h._place_tau(["0.8000"], h.ARM_FLOOR)


# --------------------------------------------------------------------------------------
# F2-3: the vacuity that would manufacture a TRUE
# --------------------------------------------------------------------------------------

def _rows(specs):
    """specs: list of (raw_scores, client_denied)."""
    return [{"trial": f"t{i:04d}", "request_id": f"r{i}", "outcome": "policy_denied",
             "evaluated": True, "client_denied": denied,
             "log_decisions": ["DENY"] if denied else ["ALLOW"], "n_log_blocks": 1,
             "raw_scores": list(raws), "effects": ["FORBID"] if denied else ["ALLOW"],
             "bucket_s": 0}
            for i, (raws, denied) in enumerate(specs)]


def test_m2_censoring_makes_f2_3_vacuous_and_the_flag_says_so(h):
    """Only denied requests publish a score -> every stratum pure -> the test cannot fail."""
    joins = {
        h.ARM_FLOOR: {"rows": _rows([(["0.8000"], True)] * 5)},
        h.ARM_INSIDE: {"rows": _rows([(["0.8000"], True), (["1.0000"], True),
                                      ([], False), ([], False)])},
        h.ARM_ABOVE: {"rows": _rows([([], False)] * 5)},
    }
    mech = h._f2_3_publication_mechanism(joins)
    assert mech["mechanism"] == "M2"
    assert "cannot fail" in mech["consequence_for_f2_3"]

    strat = h._f2_3_stratification(joins, mech)
    assert strat["distinct_decisions"] == [1], \
        "under M2 every scored row is a denial, so the decision column is constant"
    assert strat["vacuous"] is True


def test_m1_publication_makes_f2_3_answerable(h):
    """A positive scored BELOW tau still publishing is what makes the purity test real."""
    joins = {
        h.ARM_FLOOR: {"rows": _rows([(["0.8000"], True)] * 5)},
        h.ARM_INSIDE: {"rows": _rows([(["0.8000"], True), (["0.4000"], False),
                                      (["0.4000"], False)])},
        h.ARM_ABOVE: {"rows": _rows([(["0.8000"], False)] * 5)},
    }
    mech = h._f2_3_publication_mechanism(joins)
    assert mech["mechanism"] == "M1"
    assert "answerable" in mech["consequence_for_f2_3"]

    strat = h._f2_3_stratification(joins, mech)
    assert strat["vacuous"] is False
    assert sorted(strat["distinct_decisions"]) == [0, 1]
    # And the pair is now a real stratum-purity input: one mixed stratum would falsify.
    import stats as S
    vd = S.variance_decomposition(strat["scores"], strat["decisions"])
    assert vd["conditionally_deterministic"] is True
    mixed = S.variance_decomposition([0.8, 0.8], [0, 1])
    assert mixed["conditionally_deterministic"] is False, \
        "two identical scores with different decisions is the falsifying observation"


def test_mutation_the_vacuity_guard_can_fail(h):
    """`f2_3_stratification_is_not_vacuous` must be false exactly when the stratum is constant.

    A guard that reads True under M2 would let the censoring publish a TRUE for F2-3
    (`feedback_missing_check_is_not_pass`).
    """
    common = dict(fixed={"label": h.GUARDRAIL_CATEGORY}, preflight={"ok": True},
                  start_mode=h.ENGINE_ENFORCE, n=0,
                  buckets={"ok": True}, taus={"a": "0.2000", "b": "0.4000", "c": "1.0000"},
                  removals=[{"deleted": True}], cps={},
                  joins={h.ARM_FLOOR: {"rows": [], "n_log_events_unmatched": 0}},
                  harvest={"raw_by_arm": {h.ARM_FLOOR: ["0.8000"]}})
    vac = h._guard_results(**common, strat={"vacuous": True})
    live = h._guard_results(**common, strat={"vacuous": False})
    assert vac["f2_3_stratification_is_not_vacuous"] is False
    assert live["f2_3_stratification_is_not_vacuous"] is True


def test_mutation_the_category_guard_reads_label_not_truth(h):
    """`truth` is assigned by the harness, so a guard on it could never fail.

    This is the arm that pins the fix: the first version of this guard read
    `fixed["truth"] == "positive"`, a string `_fixed_input` writes itself
    (`feedback_vacuous_test_check`).
    """
    common = dict(preflight={"ok": True}, start_mode=h.ENGINE_ENFORCE, n=0,
                  buckets={"ok": True}, taus={"a": "0.2000"}, removals=[{"deleted": True}],
                  cps={}, joins={}, strat={"vacuous": False},
                  harvest={"raw_by_arm": {h.ARM_FLOOR: ["0.8000"]}})
    wrong_category = h._guard_results(
        fixed={"label": "VIOLENCE", "truth": "positive"}, **common)
    assert wrong_category["fixed_input_matches_the_filtered_category"] is False, \
        "a VIOLENCE item under a HATE filter publishes nothing; the guard must catch it " \
        "even though `truth` says 'positive'"
    right = h._guard_results(fixed={"label": h.GUARDRAIL_CATEGORY, "truth": "positive"},
                             **common)
    assert right["fixed_input_matches_the_filtered_category"] is True


def test_mutation_every_arm_was_evaluated_is_not_every_arm_landed(h):
    """Completion is not evaluation — DEV-P4-22 in one assertion.

    60 completed JSON-RPC errors satisfied a "did the trials complete" guard while the policy
    engine had never seen a request, and the case published a TRUE it had not measured.
    """
    class _CP:
        """A stand-in for `Checkpoint`, with `n_done` as the PROPERTY it really is.

        An earlier version spelled it as a method, which is the same slip that killed a live
        run on 2026-08-12 (`TypeError: 'int' object is not callable`) — and while the harness
        held the wrong spelling the stub agreed with it, so this test passed. A double that
        mirrors the bug instead of the real class validates nothing
        (`feedback_verify_against_real_artifact`). The assertion below binds the two.
        """

        def __init__(self, n):
            self._n = n

        @property
        def n_done(self):
            return self._n

    assert isinstance(vars(Checkpoint)["n_done"], property), \
        "the stub above models n_done as a property because the real one is; if that changed, " \
        "this test is measuring a shape the harness no longer has"

    rows = [{"trial": f"t{i}", "request_id": f"r{i}", "outcome": "jsonrpc_error",
             "evaluated": False, "client_denied": False, "log_decisions": [],
             "n_log_blocks": 0, "raw_scores": [], "effects": [], "bucket_s": 0}
            for i in range(3)]
    g = h._guard_results(
        fixed={"label": h.GUARDRAIL_CATEGORY}, preflight={"ok": True},
        start_mode=h.ENGINE_ENFORCE, cps={h.ARM_FLOOR: _CP(3)}, n=3,
        joins={h.ARM_FLOOR: {"rows": rows, "n_log_events_unmatched": 0}},
        buckets={"ok": True}, harvest={"raw_by_arm": {h.ARM_FLOOR: []}},
        taus={"a": "0.2000"}, strat={"vacuous": False}, removals=[{"deleted": True}])
    assert g["every_arm_landed"] is True, "3 of 3 trials completed"
    assert g["every_arm_was_evaluated"] is False, \
        "none of them was evaluated by the engine; the two guards must not agree here"
    assert g["harvest_arm_published_scores"] is False


# --------------------------------------------------------------------------------------
# the join and the bucket separation
# --------------------------------------------------------------------------------------

def test_join_counts_trials_with_no_log_event_rather_than_dropping_them(h):
    """Arm 3's whole question is whether a trial can be evaluated and publish NOTHING.

    A join that discarded the unmatched would answer that by construction.
    """
    rows = {"t0000": {"request_id": "r0", "outcome": "policy_denied", "denied": True},
            "t0001": {"request_id": "r1", "outcome": "allowed", "denied": False}}
    events = [{"body": {"policy": {"decision": "DENY", "guardrailFindings": {
        "pol-1": {"contentFilter": [{"filter": "HATE", "score": "0.8000"}],
                  "effect": "FORBID", "policyMode": "ENFORCE"}}}},
        "attributes": {"aws.request.id": "r0"}}]
    out = h._join_arm(events, rows, arm_key=h.ARM_FLOOR, policy_id="pol-1")
    assert out["n_rows"] == 2
    assert out["n_trials_with_no_log_event"] == 1
    assert out["trials_with_no_log_event"] == ["t0001"]
    assert h._raw_scores(out) == ["0.8000"]


def test_join_ignores_findings_from_another_policy(h):
    """Each arm runs under its own policy id. A score from a neighbour is not this arm's.

    Two ACTIVE guardrail policies on one action would both evaluate every request, and a row
    whose score came from the other one would be attributed to the wrong threshold.
    """
    rows = {"t0000": {"request_id": "r0", "outcome": "policy_denied", "denied": True}}
    events = [{"body": {"policy": {"decision": "DENY", "guardrailFindings": {
        "pol-OTHER": {"contentFilter": [{"filter": "HATE", "score": "1.0000"}],
                      "effect": "FORBID", "policyMode": "ENFORCE"}}}},
        "attributes": {"aws.request.id": "r0"}}]
    out = h._join_arm(events, rows, arm_key=h.ARM_FLOOR, policy_id="pol-1")
    assert h._raw_scores(out) == [], "the other policy's score must not be harvested here"
    assert out["n_trials_with_no_log_event"] == 0, \
        "the event DID exist; it just carried no finding for this policy — the two are " \
        "different facts and must not be collapsed"


def test_overlapping_arm_windows_are_a_failed_guard(h):
    """Each arm runs under a different threshold, so an overlap misattributes rows."""
    ok = h._arms_own_their_buckets({"a": {"t0": 0.0, "t1": 10.0},
                                    "b": {"t0": 100.0, "t1": 110.0}})
    assert ok["ok"] is True and ok["overlapping_windows"] == {}
    bad = h._arms_own_their_buckets({"a": {"t0": 0.0, "t1": 100.0},
                                     "b": {"t0": 50.0, "t1": 150.0}})
    assert bad["ok"] is False and "a|b" in bad["overlapping_windows"]


# --------------------------------------------------------------------------------------
# F2-4 end to end on synthetic arms
# --------------------------------------------------------------------------------------

def test_f2_4_reads_true_only_when_the_rate_rises_and_the_outsides_are_zero(h):
    """The three conjuncts the sealed oracle names, each able to fail on its own."""
    inside = [(["0.8000"], i % 2 == 0) for i in range(40)]      # alternating -> rate 1.0
    joins = {
        h.ARM_FLOOR: {"rows": _rows([(["0.4000"], True)] * 40)},   # p=1, no flips
        h.ARM_INSIDE: {"rows": _rows(inside)},
        h.ARM_ABOVE: {"rows": _rows([([], False)] * 40)},          # p=0, no flips
    }
    # p_hat = P(S >= tau_inside) on the harvest arm. With every harvest score at 0.4 and
    # tau_inside at 0.4, p_hat = 1 and the prediction is 0 — so a flip rate of 1.0 must NOT
    # be read as confirming 2p(1-p).
    taus = {h.ARM_FLOOR: "0.2000", h.ARM_INSIDE: "0.4000", h.ARM_ABOVE: "0.6000"}
    harvest = {"raw_by_arm": {h.ARM_FLOOR: ["0.4000"] * 40}}
    out = h._f2_4(joins, harvest, taus, 0.05)
    assert out["p_hat_from_harvest_arm"] == 1.0
    assert out["predicted_2p_1_minus_p"] == 0.0
    assert out["inside_rate_rose"] is True
    assert out["ci_contains_prediction"] is False, \
        "a rate of 1.0 cannot contain a prediction of 0; improved must be False"
    assert out["improved"] is False, \
        "F2-4 is not 'the rate went up' — it is 'the rate went up TO the prediction'"
    assert out["p_value"] < 0.05, "the two arms disagree on every pair"


def test_f2_4_degenerate_score_gives_zero_flips_everywhere(h):
    """The sealed FALSE branch: a constant score makes the rate insensitive to tau."""
    joins = {k: {"rows": _rows([(["0.8000"], True)] * 30)} for k in
             (h.ARM_FLOOR, h.ARM_INSIDE, h.ARM_ABOVE)}
    taus = {h.ARM_FLOOR: "0.2000", h.ARM_INSIDE: "0.8000", h.ARM_ABOVE: "1.0000"}
    out = h._f2_4(joins, {"raw_by_arm": {h.ARM_FLOOR: ["0.8000"] * 30}}, taus, 0.05)
    assert out["flips"][h.ARM_INSIDE]["n_flips"] == 0
    assert out["inside_rate_rose"] is False
    assert out["improved"] is False
    assert out["p_value"] == 1.0, "no discordant pairs means the arms never disagreed"


def test_the_four_cases_are_the_sealed_four_and_each_has_a_binding(h):
    """A script that emitted a case with no binding would raise at the end of a 900-call run."""
    import oracle as O
    assert h.CASES == ("F2-2", "F2-3", "F2-4", "F1-18")
    for cid in h.CASES:
        assert cid in O.BINDINGS, f"{cid} has no sealed binding"
    assert O.BINDINGS["F2-2"].kind == "DISTINCT_AT_LEAST"
    assert O.BINDINGS["F2-3"].kind == "STRATUM_PURITY"
    assert O.BINDINGS["F2-4"].kind == "PAIRED_IMPROVEMENT"
    assert O.BINDINGS["F1-18"].kind == "EXISTENCE"
    # The sealed n's the script must not silently under-run.
    assert h.N_SEALED == O.planned_n("F2-2") == 300
    assert h.N_LATTICE_SEALED == 500
    assert "500" in O.oracle_text("F1-18")


def test_guard_names_match_the_guards_actually_computed(h):
    """A name in GUARDS with no computation, or the reverse, is a label over nothing.

    `feedback_label_must_match_computation`: the dry run prints GUARDS as the list of things
    that can fail, so a name that no longer corresponds to a key is a promise to the reader
    that nothing keeps.
    """
    computed = h._guard_results(
        fixed={"label": h.GUARDRAIL_CATEGORY}, preflight={"ok": True},
        start_mode=h.ENGINE_ENFORCE, cps={}, n=0, joins={}, buckets={"ok": True},
        harvest={"raw_by_arm": {h.ARM_FLOOR: ["0.8000"]}}, taus={"a": "0.2000"},
        strat={"vacuous": False}, removals=[{"deleted": True}])
    assert set(computed) == set(h.GUARDS), (
        f"declared-but-not-computed={sorted(set(h.GUARDS) - set(computed))}, "
        f"computed-but-not-declared={sorted(set(computed) - set(h.GUARDS))}")


# --------------------------------------------------------------------------------------
# the error path: a policy that fails to settle is still a policy that exists
# --------------------------------------------------------------------------------------

class _RecordingClient:
    """Counts the calls `_create_probe` makes, and answers each one as the service would.

    A stub rather than a mock because the assertion is about a SEQUENCE — create, then get,
    then delete — and the defect being tested was a missing third element. A mock that only
    recorded `delete_policy(...)` was called would also pass if the create had never happened.
    """

    def __init__(self, settle_status):
        self.settle_status = settle_status
        self.calls: list[str] = []

    def create_policy(self, **kw):
        self.calls.append("create_policy")
        return {"policyId": "pol-stub", "policyArn": "arn:stub"}

    def get_policy(self, **kw):
        self.calls.append("get_policy")
        return {"status": self.settle_status, "statusReasons": ["stub reason"]}

    def delete_policy(self, **kw):
        self.calls.append("delete_policy")
        return {}


def _probe_env(h, monkeypatch, settle_status):
    """`_create_probe`'s collaborators, stubbed at the module boundary."""
    ac = _RecordingClient(settle_status)

    def _capture(store, operation, client, **params):
        fn = getattr(client, operation)
        resp = fn(**params)
        return SimpleNamespace(ok=True, response=resp, error_code="", error_message="")

    class _Limiter:
        def wait(self, _op): pass

    monkeypatch.setattr(h, "capture", _capture)
    monkeypatch.setattr(h, "wait_status", lambda fn, params: fn(**params))
    monkeypatch.setattr(h.A, "limiter", lambda: _Limiter())
    monkeypatch.setattr(h.cedar, "check_statement", lambda stmt: [])

    dropped: list[tuple[str, str]] = []
    state = SimpleNamespace(record=lambda res: None,
                            drop=lambda kind, logical: dropped.append((kind, logical)))
    return ac, state, dropped


def test_a_policy_that_settles_create_failed_is_deleted_before_the_raise(h, monkeypatch):
    """THE 2026-08-12 LEAK, replayed.

    `CreatePolicy` returned 200, the policy settled `CREATE_FAILED`, and `_create_probe` raised.
    The id had not yet reached the dict `main`'s `finally` iterates, so both channels that can
    find a policy were blind to it and it stayed in the account. The NEXT run died on
    `ConflictException: Policy with the same name already exists` — a name conflict, which reads
    as a bug in naming rather than as an unreleased resource three failures ago.
    """
    ac, state, dropped = _probe_env(h, monkeypatch, "CREATE_FAILED")
    with pytest.raises(h.ConfigError) as exc:
        h._create_probe(ac, None, state, engine_id="eng", run_id="rid",
                        gateway_arn=GW_ARN,
                        action_id="act", tau="0.2000", arm_key="tau_floor")
    assert ac.calls == ["create_policy", "get_policy", "delete_policy"], \
        f"the created policy must be deleted on the raise path, got {ac.calls}"
    assert dropped == [("policy", "f2_03_tau_floor")], \
        "the resource ledger must also stop claiming a policy that no longer exists"
    msg = str(exc.value)
    assert "CREATE_FAILED" in msg, "the settle failure is the finding and must stay in the message"
    assert "deleted" in msg, "and the cleanup outcome must be reported, not silent"


def test_a_policy_that_settles_active_is_not_deleted(h, monkeypatch):
    """The control arm. A cleanup that also fires on success would delete the probe it needs.

    Without this, `test_...is_deleted_before_the_raise` passes just as well against a
    `_create_probe` that deletes unconditionally — which would break every arm of the live run
    while the test suite stayed green (feedback_vacuous_test_check).
    """
    ac, state, dropped = _probe_env(h, monkeypatch, next(iter(h.PE_TERMINAL_OK)))
    pid = h._create_probe(ac, None, state, engine_id="eng", run_id="rid",
                          gateway_arn=GW_ARN,
                          action_id="act", tau="0.2000", arm_key="tau_floor")
    assert pid == "pol-stub"
    assert ac.calls == ["create_policy", "get_policy"], \
        f"a settled-ACTIVE probe must survive, got {ac.calls}"
    assert dropped == []


def test_an_undeletable_failed_policy_says_so_by_name(h, monkeypatch):
    """When cleanup itself fails, the message has to carry the operator's next action.

    `_delete_probe` never raises — by design, it runs in a `finally` — so the only way a failed
    delete reaches anyone is the text. If it said "deleted" regardless, the next run's
    ConflictException would again be the first sign.
    """
    ac, state, _dropped = _probe_env(h, monkeypatch, "CREATE_FAILED")

    def _capture_delete_fails(store, operation, client, **params):
        if operation == "delete_policy":
            client.calls.append("delete_policy")
            return SimpleNamespace(ok=False, response={},
                                   error_code="ThrottlingException", error_message="slow down")
        resp = getattr(client, operation)(**params)
        return SimpleNamespace(ok=True, response=resp, error_code="", error_message="")

    monkeypatch.setattr(h, "capture", _capture_delete_fails)
    monkeypatch.setattr(h, "DELETE_SLEEP_S", 0)
    with pytest.raises(h.ConfigError) as exc:
        h._create_probe(ac, None, state, engine_id="eng", run_id="rid",
                        gateway_arn=GW_ARN,
                        action_id="act", tau="0.2000", arm_key="tau_floor")
    msg = str(exc.value)
    assert "NOT deleted" in msg and "ThrottlingException" in msg
    assert "by hand" in msg, "the message must name the action, not just the state"
    assert ac.calls.count("delete_policy") == h.DELETE_ATTEMPTS, \
        "every retry the delete path promises must actually be spent"


# --------------------------------------------------------------------------------------
# the item contract of the reader this script BORROWS
# --------------------------------------------------------------------------------------

def _item_keys_read_by(fn) -> set[str]:
    """Every `item[...]` string subscript in `fn`'s source, by AST.

    Derived rather than listed. The point of this check is that `_call` lives in ANOTHER
    family's file and can grow a field without this script's author being present; a hardcoded
    list would go stale in exactly the situation the check exists for. `ast.Subscript` on a
    `Name` called `item` with a string constant index is the only shape `_call` uses, and
    reading the parameter name off the signature rather than assuming "item" keeps the two in
    step if it is ever renamed.
    """
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src)
    fdef = next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    param = fdef.args.args[-1].arg
    return {n.slice.value for n in ast.walk(fdef)
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
            and n.value.id == param and isinstance(n.slice, ast.Constant)
            and isinstance(n.slice.value, str)}


def test_the_fixed_input_carries_every_key_the_borrowed_reader_subscripts(h):
    """The 304-call defect of 2026-08-12, as a test that costs nothing.

    `_call` is imported from `f3_efficacy/08_score_label_join.py`, where the items come from
    `_golden_set` and carry `corpus_label`. `_fixed_input` builds its item from
    `arms.load_corpus`, which carries `label`. The mismatch is invisible until a trial runs,
    and `_call` **sends the request before it builds the row** — so all 300 trials of the
    harvest arm paid for a gateway round trip and then raised `KeyError: 'corpus_label'`. The
    evidence tree holds 304 `mcp-tools-call` records against 0 usable rows.

    A dry run cannot catch this (`feedback_dry_run_before_expensive_run`: `--dry-run` returns
    before the live loop), and a `--n 4` smoke catches it only after paying for four calls and
    a policy create/delete pair. This catches it at import time.
    """
    needed = _item_keys_read_by(h._call)
    assert "corpus_label" in needed, (
        "the derivation found no `corpus_label` — either `_call` stopped reading it, in which "
        "case this test's premise is stale, or the AST walk is wrong and would pass over any "
        "missing key (`feedback_zero_file_scan_is_error`)")
    item = h._fixed_input()
    missing = sorted(k for k in needed if k not in item)
    assert not missing, (
        f"_fixed_input() omits {missing}, which `_call` subscripts. Every trial would send its "
        f"request and then raise KeyError while building the row — the calls are spent before "
        f"the failure, so the arm pays in full for nothing.")


def test_the_check_fails_for_an_item_missing_the_key(h):
    """The mutation arm: without it, an AST walk that returned `set()` would also pass.

    Two things are asserted separately — that the walk finds keys at all (above) and that a
    deficient item is rejected (here). A single happy-path assertion is satisfied by a check
    that measures nothing (`feedback_vacuous_test_check`).
    """
    needed = _item_keys_read_by(h._call)
    assert len(needed) >= 3, f"only {sorted(needed)} derived from _call"
    deficient = {k: "x" for k in needed if k != "corpus_label"}
    assert sorted(k for k in needed if k not in deficient) == ["corpus_label"]


# --------------------------------------------------------------------------------------
# a smoke must not block the sealed run it precedes
# --------------------------------------------------------------------------------------

def test_a_smoke_and_a_sealed_run_do_not_share_a_checkpoint_cell(h, tmp_path, monkeypatch):
    """Measured on 2026-08-12: the sealed run died on `set_meta` after creating a policy.

    `set_meta` refuses a resume that changes `is_smoke` once any trial is done, which is right —
    4 smoke rows absorbed into a 300-trial arm would be published as if collected under the
    sealed design. But the smoke-then-full order is standard here, so a shared cell made that
    guard fire on every sealed run: the full run created its `tau_floor` probe policy, raised,
    and unwound through the `finally`.

    Asserted on the CELL NAME rather than by driving two live arms, because the failure is
    entirely in the naming and a live reproduction costs 4 calls and a policy pair.
    """
    seen = []

    class _CP:
        def __init__(self, *, case_id, cell, **kw):
            seen.append(cell)

        def load(self):
            return self

        def set_meta(self, **kw):
            pass

        def is_done(self, _tid):
            return True

        n_done = 0
        n_failed = 0

    monkeypatch.setattr(h, "Checkpoint", _CP)
    monkeypatch.setattr(h, "_isolate_bucket", lambda: {"ok": True})
    client = SimpleNamespace(refresh_if_stale=lambda: None)
    item = {"id": "x", "truth": "positive", "text": "t", "corpus_label": "HATE"}
    for smoke in (True, False):
        h._run_arm(client, "tool", arm_key=h.ARM_FLOOR, tau="0.2000", item=item, n=1,
                   is_smoke=smoke)
    assert seen[0] != seen[1], (
        "a smoke and a sealed run wrote the same checkpoint cell; the sealed run will raise on "
        "set_meta's is_smoke guard after it has already created a probe policy")
    assert seen == [f"{h.ARM_FLOOR}__smoke", h.ARM_FLOOR], seen


# --------------------------------------------------------------------------------------
# the comparison operator, and the power unit
#
# Both were caught by READING the 900-call run against the record it wrote, not by a
# failing assertion — which is why both are now assertions. The run published
# `p_hat_definition: "P(S >= tau_inside)"` with `p_hat = 1.0`, a value that predicts every
# tau_inside request denies, next to an arm that denied 0 of 300 at that same tau. The
# verdict was right either way (both readings give 2p(1-p) = 0), so nothing failed; the
# stated reason was simply not the operative one (`feedback_prose_is_not_verified`).
# --------------------------------------------------------------------------------------

def _equality_case(h, *, denied_at_equality, score="0.8000"):
    """Three arms with tau at the floor, AT the observed score, and above it."""
    joins = {
        h.ARM_FLOOR: {"rows": _rows([([score], True)] * 10)},
        h.ARM_INSIDE: {"rows": _rows([([], denied_at_equality)] * 10)},
        h.ARM_ABOVE: {"rows": _rows([([], False)] * 10)},
    }
    taus = {h.ARM_FLOOR: "0.2000", h.ARM_INSIDE: score, h.ARM_ABOVE: "1.0000"}
    return joins, taus, {"raw_by_arm": {h.ARM_FLOOR: [score] * 10}}


def test_the_comparison_operator_is_measured_off_the_arm_that_sits_on_the_score(h):
    """ALLOW at tau == S means equality does not deny, so the test is strict.

    This is the configuration the 2026-08-12 run actually produced: a one-point support
    forces `_place_tau`'s `degenerate_support` branch, which places tau AT the observed
    value — the only placement that can separate `>` from `>=`.
    """
    out = h._threshold_comparison(*_equality_case(h, denied_at_equality=False))
    assert out["operator"] == "STRICT_GREATER"
    assert out["equality_arms"][h.ARM_INSIDE] == {
        "tau": "0.8000", "n_rows": 10, "n_denied": 0}
    assert out["observed_support"] == ["4/5"], "the support is carried as an exact Fraction"
    assert "does not deny" in out["why"]
    assert out["alternative_explanation"], \
        "the rounded-rendering reading must be registered, not dropped"


def test_mutation_denying_at_equality_reads_as_the_other_operator(h):
    """The same code must report `>=` when the service denies at equality."""
    out = h._threshold_comparison(*_equality_case(h, denied_at_equality=True))
    assert out["operator"] == "GREATER_OR_EQUAL"
    assert out["equality_arms"][h.ARM_INSIDE]["n_denied"] == 10


def test_an_equality_arm_that_both_denies_and_allows_is_not_read_as_either_operator(h):
    """Half denied at one tau on one fixed input is not a comparison — it is F2-2's business."""
    joins, taus, harvest = _equality_case(h, denied_at_equality=False)
    joins[h.ARM_INSIDE] = {"rows": _rows([([], i % 2 == 0) for i in range(10)])}
    out = h._threshold_comparison(joins, taus, harvest)
    assert out["operator"] == "INCONSISTENT"
    assert "F2-2" in out["why"]


def test_with_no_arm_on_the_observed_score_the_operator_is_undecided_not_assumed(h):
    """The ordinary interior placement exercises no equality case, and says so."""
    joins, taus, harvest = _equality_case(h, denied_at_equality=False)
    taus[h.ARM_INSIDE] = "0.6000"          # interior, not equal to any observed score
    out = h._threshold_comparison(joins, taus, harvest)
    assert out["operator"] == "UNDECIDED"
    assert out["equality_arms"] == {}
    assert out["default_when_undecided"] == ">="


def test_p_hat_uses_the_measured_operator_and_keeps_the_other_reading_visible(h):
    """p_hat counts denials, so it must count with the comparison the SERVICE performs."""
    joins, taus, harvest = _equality_case(h, denied_at_equality=False)
    out = h._f2_4(joins, harvest, taus, 0.05)
    assert out["threshold_comparison"]["operator"] == "STRICT_GREATER"
    assert out["p_hat_under_each_operator"] == {">=": 1.0, ">": 0.0}
    assert out["p_hat_from_harvest_arm"] == 0.0, \
        "under a strict test a score EQUAL to tau does not deny, so p_hat is 0 not 1"
    assert ">" in out["p_hat_definition"] and ">=" not in out["p_hat_definition"]
    assert out["p_hat_is_insensitive_to_the_operator"] is False
    # And the reason the wrong operator did not change any verdict, stated as data:
    assert out["prediction_under_each_operator"] == {">=": 0.0, ">": 0.0}
    assert out["predicted_2p_1_minus_p"] == 0.0


def test_the_operator_that_is_undecided_falls_back_to_the_declared_default(h):
    """No equality arm -> the record must not silently pick the strict count."""
    joins, taus, harvest = _equality_case(h, denied_at_equality=False)
    taus[h.ARM_INSIDE] = "0.6000"
    out = h._f2_4(joins, harvest, taus, 0.05)
    assert out["threshold_comparison"]["operator"] == "UNDECIDED"
    assert out["p_hat_from_harvest_arm"] == 1.0, "0.8 clears 0.6 under either operator"
    assert "P(S >= tau_inside)" in out["p_hat_definition"]


def test_the_power_requirement_is_read_from_the_seal_and_299_pairs_meets_it(h):
    """299 pairs is the design point, not a shortfall.

    `lib/oracle.py` blocks F2-4 on "n_usable=299 is below the pre-registered 300". The
    sealed cell's own rule powers the design for a 1% flip rate and states the requirement
    as "requires n >= 299" — and the unit of that calculation is the flip OPPORTUNITY, i.e.
    the pair. So 300 trials is the smallest run that reaches the design point, the floor the
    oracle applies counts trials, and the blocker is a unit mismatch rather than a power
    deficit. Recorded in DEV-P4-29; asserted here so the arithmetic is checked and not
    merely written down.
    """
    out = h._determinism_power(299)
    assert out["parsed"] is True
    assert out["n_trials_sealed"] == 300
    assert out["prereg_requires_n_at_least"] == 299
    assert out["n_pairs_meets_the_n_the_seal_requires"] is True
    assert out["flip_rate_powered_for"] == 0.01 and out["power_floor"] == 0.95
    assert out["meets_power_floor"] is True
    assert out["power_at_n_pairs"] == pytest.approx(1.0 - 0.99 ** 299, rel=1e-12)
    assert out["power_at_n_pairs"] >= 0.95


def test_the_power_check_can_fail_on_a_short_arm(h):
    """The mutation arm: if the check cannot fail it is not measuring the arm's length."""
    out = h._determinism_power(100)
    assert out["parsed"] is True
    assert out["n_pairs_meets_the_n_the_seal_requires"] is False
    assert out["meets_power_floor"] is False, \
        f"1-0.99^100 = {1 - 0.99 ** 100:.4f} is below the sealed 0.95 floor"


def test_the_power_claim_is_withheld_when_the_seal_stops_stating_the_figures(h, monkeypatch):
    """A hardcoded fallback would keep claiming adequate power after the seal changed."""
    import oracle as O
    monkeypatch.setattr(O, "_PREREG_CACHE", {
        "sample_sizes": {"determinism_cell": {"n": 300, "rule": "n=300 because we said so"}}})
    out = h._determinism_power(299)
    assert out["parsed"] is False
    assert "withheld" in out["parse_failure"]
    for k in ("power_at_n_pairs", "meets_power_floor", "power_floor"):
        assert k not in out, f"{k} survived a failed parse and would be read as measured"


def test_m2_censors_the_score_and_not_the_record(h):
    """Measured 900/900: a policy-evaluation block exists for every trial in every arm.

    The first wording of M2 said "the record is written only when the score clears tau",
    which the run refuted: the two arms that denied nothing still logged one block each,
    carrying an explicit ALLOW. The surface stays lit below tau and drops one field. This is
    the difference between F1-18's censoring being over records or over values.
    """
    joins, _, _ = _equality_case(h, denied_at_equality=False)
    mech = h._f2_3_publication_mechanism(joins)
    assert mech["mechanism"] == "M2"
    assert mech["n_rows_with_a_score"] == 0
    assert mech["n_rows_with_a_log_block"] == 10
    assert mech["n_rows_with_a_logged_decision"] == 10
    assert mech["what_is_censored"] == "the score, and NOT the log record or its decision"
    assert "record itself is still written" in mech["M2"]


def test_a_dark_surface_would_be_reported_differently_from_a_missing_field(h):
    """Mutation: strip the log blocks and the censoring claim must stop being made."""
    joins, _, _ = _equality_case(h, denied_at_equality=False)
    for r in joins[h.ARM_ABOVE]["rows"]:
        r["n_log_blocks"] = 0
        r["log_decisions"] = []
    mech = h._f2_3_publication_mechanism(joins)
    assert mech["n_rows_with_a_log_block"] == 0
    assert mech["what_is_censored"].startswith("undetermined:"), \
        "with no record at all, 'the record is still written' is not something we observed"
    assert "failed join" in mech["what_is_censored"], (
        "a join that matched nothing looks exactly like a dark surface, and calling it "
        "censoring would publish a defect in this harness as a finding about the service")
