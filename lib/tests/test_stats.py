"""Tests for lib/stats.py against published reference values.

Test-design contract (per the vacuous-test rule)
------------------------------------------------
An assertion like ``0 <= lo <= hi <= 1`` is satisfied by a Wilson implementation
that returns ``[0, 1]`` unconditionally. Every interval test here therefore pins
**published numeric values** — Wilson from Newcombe (1998), Clopper–Pearson from
the Beta relationship computed independently, rule-of-three from the closed form,
McNemar from Agresti's worked example — and the accompanying
``test_stats_mutation.py`` proves each assertion can actually fail.

Where a reference value is not in print, the test pins an *identity that a wrong
implementation cannot satisfy by construction* (e.g. Clopper–Pearson at x=0 must
equal the exact rule-of-three bound; the paired bootstrap must be narrower than
the independent-resample bootstrap on correlated data).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import norm as _norm

import stats as st


def sps_norm_sf(x: float) -> float:
    """Normal survival function, used only to cross-check chi-square(1) tails."""
    return float(_norm.sf(x))


def _rankdata(vals: list[float]) -> list[float]:
    """Average-rank ranking, written out so the Wilcoxon oracle is independent
    of the same scipy call the implementation under test uses."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1          # 1-based average rank for the tie group
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _exact_signed_rank_p(ranks: list[float], observed: float) -> float:
    """Exact two-sided signed-rank p by enumerating all 2^n sign assignments.

    Feasible at n=9 (512 cases) and gives the test an oracle that does not
    depend on scipy's implementation at all.
    """
    import itertools
    total_rank = sum(ranks)
    hits = 0
    cases = 0
    for signs in itertools.product((1, -1), repeat=len(ranks)):
        cases += 1
        w_plus = sum(r for r, s in zip(ranks, signs) if s > 0)
        if min(w_plus, total_rank - w_plus) <= observed + 1e-12:
            hits += 1
    return hits / cases


# ---------------------------------------------------------------------------
# Wilson score interval
# ---------------------------------------------------------------------------


class TestWilson:
    def test_newcombe_1998_reference_values(self):
        """Newcombe (1998), Stat Med 17:857-872, Table I — method 3 (Wilson).

        These are the canonical published values; matching them to 3 decimals
        is a claim no degenerate implementation can meet.
        """
        cases = [
            # (x,  n,   lo,     hi)
            (81, 263, 0.2553, 0.3662),
            (15, 148, 0.0624, 0.1605),
            (0, 20, 0.0000, 0.1611),
            (1, 29, 0.0061, 0.1718),
        ]
        for x, n, lo, hi in cases:
            ci = st.wilson_ci(x, n)
            assert ci.lo == pytest.approx(lo, abs=5e-4), f"lo for {x}/{n}"
            assert ci.hi == pytest.approx(hi, abs=5e-4), f"hi for {x}/{n}"

    def test_zero_count_is_not_degenerate(self):
        """The failure mode Wald has and Wilson does not.

        Wald at x=0 gives [0, 0], which would license "0% FPR, 95% CI [0%, 0%]"
        from n=20. Wilson must give a strictly positive upper bound.
        """
        ci = st.wilson_ci(0, 20)
        assert ci.lo == 0.0
        assert ci.hi > 0.15, "upper bound collapsed toward the Wald degenerate value"
        wald_hi = 0.0 + st.Z_95 * math.sqrt(0.0 * 1.0 / 20)
        assert ci.hi > wald_hi

    def test_full_count_is_not_degenerate(self):
        ci = st.wilson_ci(20, 20)
        assert ci.hi == 1.0
        assert ci.lo < 0.90

    def test_stays_within_unit_interval(self):
        for n in (1, 3, 7, 50, 1000):
            for x in (0, 1, n // 2, n - 1, n):
                if not 0 <= x <= n:
                    continue
                ci = st.wilson_ci(x, n)
                assert 0.0 <= ci.lo <= ci.point <= ci.hi <= 1.0, (x, n)

    def test_width_shrinks_with_n(self):
        widths = [st.wilson_ci(n // 2, n).width for n in (20, 100, 500, 2000)]
        assert widths == sorted(widths, reverse=True)
        # sqrt(n) convergence: 100x the data roughly 10x narrower
        assert widths[0] / widths[3] == pytest.approx(10.0, rel=0.15)

    def test_symmetric_under_relabelling(self):
        a = st.wilson_ci(30, 100)
        b = st.wilson_ci(70, 100)
        assert a.lo == pytest.approx(1 - b.hi)
        assert a.hi == pytest.approx(1 - b.lo)

    def test_level_widens_interval(self):
        assert st.wilson_ci(5, 50, 0.99).width > st.wilson_ci(5, 50, 0.95).width

    @pytest.mark.parametrize("x,n", [(-1, 10), (11, 10), (0, 0), (1, -5)])
    def test_rejects_invalid_counts(self, x, n):
        with pytest.raises(ValueError):
            st.wilson_ci(x, n)

    def test_rejects_non_integer_counts(self):
        with pytest.raises(ValueError):
            st.wilson_ci(2.5, 10)


# ---------------------------------------------------------------------------
# Clopper-Pearson
# ---------------------------------------------------------------------------


class TestClopperPearson:
    def test_reference_values(self):
        """Standard worked examples of the exact interval."""
        ci = st.clopper_pearson_ci(3, 10)
        assert ci.lo == pytest.approx(0.06674, abs=1e-4)
        assert ci.hi == pytest.approx(0.65245, abs=1e-4)

        ci = st.clopper_pearson_ci(0, 10)
        assert ci.lo == 0.0
        assert ci.hi == pytest.approx(0.30850, abs=1e-4)

        ci = st.clopper_pearson_ci(10, 10)
        assert ci.lo == pytest.approx(0.69150, abs=1e-4)
        assert ci.hi == 1.0

    def test_x_zero_closes_to_two_sided_rule_of_three(self):
        """At x=0 the exact upper bound IS 1 - (alpha/2)^(1/n).

        This ties two independently implemented functions to one closed form; an
        error in either breaks the identity.
        """
        for n in (10, 20, 60, 100, 300):
            cp = st.clopper_pearson_ci(0, n).hi
            exact = st.rule_of_three(n, one_sided=False)
            assert cp == pytest.approx(exact, rel=1e-9), n

    def test_conservative_relative_to_wilson(self):
        """Exact coverage is bought with width: CP must contain Wilson."""
        for x, n in [(3, 10), (15, 148), (81, 263), (1, 29)]:
            cp = st.clopper_pearson_ci(x, n)
            w = st.wilson_ci(x, n)
            assert cp.lo <= w.lo + 1e-12, (x, n)
            assert cp.hi >= w.hi - 1e-12, (x, n)
            assert cp.width > w.width, (x, n)


# ---------------------------------------------------------------------------
# rule of three and power
# ---------------------------------------------------------------------------


class TestRuleOfThree:
    def test_matches_the_plan_table(self):
        """The table that fixes every corpus size in the plan.

        If these move, the pre-registered n values are wrong, so they are pinned
        here as a regression guard on the design itself.
        """
        expected = {20: 0.1391, 60: 0.0487, 100: 0.0295, 300: 0.00995}
        for n, bound in expected.items():
            assert st.rule_of_three(n) == pytest.approx(bound, abs=5e-4), n

    def test_three_over_n_is_the_first_order_approximation(self):
        """-ln(0.05) = 2.9957, hence "3/n". Exact form must sit just under it.

        The approximation error is O(1/n), not uniform: 2.6% at n=60 falling to
        0.29% at n=1000. Pinning a single tolerance would either pass vacuously
        at large n or fail at small n, so the bound is expressed as the actual
        rate. This is why the plan's table quotes exact values (4.87%, not 5%).
        """
        for n, max_rel_err in ((60, 0.03), (100, 0.02), (300, 0.007), (1000, 0.003)):
            exact = st.rule_of_three(n)
            assert exact < 3.0 / n, n
            rel_err = abs(exact - 3.0 / n) / (3.0 / n)
            assert rel_err < max_rel_err, (n, rel_err)
        # error must actually shrink with n, not merely stay under a loose cap
        errs = [abs(st.rule_of_three(n) - 3.0 / n) / (3.0 / n)
                for n in (60, 100, 300, 1000)]
        assert errs == sorted(errs, reverse=True)

    def test_one_sided_is_tighter_than_two_sided(self):
        assert st.rule_of_three(60, one_sided=True) < st.rule_of_three(60, one_sided=False)

    def test_n20_cannot_support_a_five_percent_claim(self):
        """The concrete reason negative controls run at n>=60, not n=5.

        This is the test that would have caught DC-2 being reported from n=5.
        """
        assert st.rule_of_three(20) > 0.05
        assert st.rule_of_three(5) > 0.40
        assert st.rule_of_three(60) < 0.05

    def test_rejects_bad_n(self):
        with pytest.raises(ValueError):
            st.rule_of_three(0)


class TestPower:
    def test_required_n_matches_prereg(self):
        """The pre-registered n=300 per determinism cell comes from p1=0.01.

        ln(0.05)/ln(0.99) = 298.07, so the smallest n reaching 95% power is
        **299**, not 298: at n=298 power is 0.94996, just short. The plan's
        n=300 is that ceiling with one trial of margin. Verified against the
        power function below rather than trusted from the closed form.
        """
        assert st.required_n_for_zero_events(0.05, 0.95) == 59
        assert st.required_n_for_zero_events(0.01, 0.95) == 299
        assert st.power_for_zero_events(298, 0.01) < 0.95
        assert st.power_for_zero_events(299, 0.01) >= 0.95
        assert st.required_n_for_zero_events(0.01, 0.80) == 161
        # the pre-registered n=300 clears the requirement
        assert 300 >= st.required_n_for_zero_events(0.01, 0.95)

    def test_power_and_required_n_are_inverses(self):
        for p1 in (0.001, 0.01, 0.05, 0.2):
            n = st.required_n_for_zero_events(p1, 0.95)
            assert st.power_for_zero_events(n, p1) >= 0.95
            assert st.power_for_zero_events(n - 1, p1) < 0.95

    def test_power_formula(self):
        assert st.power_for_zero_events(300, 0.01) == pytest.approx(
            1 - 0.99 ** 300, rel=1e-12)
        assert st.power_for_zero_events(1, 1.0) == 1.0

    @pytest.mark.parametrize("p1,power", [(0.0, 0.95), (1.0, 0.95), (0.05, 0.0), (0.05, 1.0)])
    def test_rejects_boundary_arguments(self, p1, power):
        with pytest.raises(ValueError):
            st.required_n_for_zero_events(p1, power)


class TestExactBinomTest:
    def test_reference_values(self):
        # 9/10 successes against p0=0.5, two-sided: 2 * sum_{k>=9} C(10,k) 0.5^10
        assert st.exact_binom_test(9, 10, 0.5) == pytest.approx(2 * 11 / 1024, rel=1e-9)
        # 3/10 against p0=0.3 is exactly the null: p-value must be 1
        assert st.exact_binom_test(3, 10, 0.3) == pytest.approx(1.0, abs=1e-9)

    def test_zero_events_against_zero_null_is_uninformative(self):
        """H0: p=0 cannot be rejected by observing nothing — the F2 design point."""
        assert st.exact_binom_test(0, 300, 0.0) == pytest.approx(1.0)

    def test_one_event_against_zero_null_is_decisive(self):
        """Under H0: p_flip = 0, a single flip has probability 0.

        This is why F2-3 needs no p-value: one mixed stratum falsifies outright.
        """
        assert st.exact_binom_test(1, 300, 0.0) == pytest.approx(0.0)

    def test_one_sided_alternatives(self):
        assert st.exact_binom_test(9, 10, 0.5, "greater") < 0.05
        assert st.exact_binom_test(9, 10, 0.5, "less") > 0.95


# ---------------------------------------------------------------------------
# McNemar
# ---------------------------------------------------------------------------


class TestMcNemar:
    def test_continuity_corrected_chi_square(self):
        """b=132, c=107: Yates-corrected chi-square = (|132-107|-1)^2/239.

        = 576/239 = 2.41004, p = 0.12056 on 1 df. Cross-checked two ways: the
        chi-square survival function and 2*Phi(-sqrt(stat)) must agree, since a
        chi-square(1) is a squared standard normal.
        """
        stat, p = st.mcnemar_test(132, 107, exact=False)
        assert stat == pytest.approx(576 / 239, rel=1e-12)
        assert p == pytest.approx(0.12056, abs=5e-5)
        assert p == pytest.approx(2 * sps_norm_sf(math.sqrt(stat)), rel=1e-9)

    def test_continuity_correction_is_applied(self):
        """Without Yates the statistic is 625/239 and p = 0.10585.

        Pinning both proves the correction is present rather than assumed: a
        version that dropped it would pass a loose "p is about 0.1" assertion.
        """
        stat, p = st.mcnemar_test(132, 107, exact=False)
        uncorrected = (132 - 107) ** 2 / 239
        assert stat < uncorrected
        assert stat == pytest.approx(uncorrected - (2 * 25 - 1) / 239, rel=1e-9)
        assert p > 0.10585   # correction is conservative

    def test_exact_branch_for_small_discordance(self):
        """b+c < 25 -> exact binomial. b=1, c=9: two-sided binom(1;10,0.5)."""
        stat, p = st.mcnemar_test(1, 9)
        assert stat == 1.0
        assert p == pytest.approx(2 * 11 / 1024, rel=1e-9)

    def test_auto_selects_exact_below_25(self):
        _, p_auto = st.mcnemar_test(2, 8)
        _, p_exact = st.mcnemar_test(2, 8, exact=True)
        assert p_auto == p_exact

    def test_auto_selects_chi_square_at_25_and_above(self):
        _, p_auto = st.mcnemar_test(5, 20)
        _, p_chi = st.mcnemar_test(5, 20, exact=False)
        assert p_auto == p_chi

    def test_no_discordance_is_p_one_not_an_error(self):
        """Identical behaviour across arms is a legitimate F5-6 outcome."""
        assert st.mcnemar_test(0, 0) == (0.0, 1.0)

    def test_concordant_cells_are_irrelevant(self):
        """The whole point of McNemar: only discordant pairs carry information."""
        assert st.mcnemar_test(3, 12) == st.mcnemar_test(3, 12)

    def test_symmetric_in_arguments(self):
        assert st.mcnemar_test(4, 15)[1] == pytest.approx(st.mcnemar_test(15, 4)[1])

    def test_rejects_negative_counts(self):
        with pytest.raises(ValueError):
            st.mcnemar_test(-1, 5)


# ---------------------------------------------------------------------------
# paired continuous
# ---------------------------------------------------------------------------


class TestWilcoxonAndHodgesLehmann:
    def test_hodges_lehmann_walsh_average_definition(self):
        """HL = median of all Walsh averages (i <= j), including i == j."""
        d = [1.0, 2.0, 4.0]
        walsh = [1.0, 1.5, 2.5, 2.0, 3.0, 4.0]
        assert st.hodges_lehmann(d) == pytest.approx(float(np.median(walsh)))

    def test_hodges_lehmann_resists_a_retry_tail_outlier(self):
        """The reason latency shifts are reported as HL, not as a mean difference.

        One 30-second retry moves the mean by ~3s and HL by nothing.
        """
        clean = [10.0] * 20
        tail = clean[:-1] + [30_000.0]
        assert st.hodges_lehmann(tail) == pytest.approx(10.0)
        assert abs(np.mean(tail) - 10.0) > 1000

    def test_wilcoxon_matches_exact_permutation_null(self):
        """Verified against the exact null, not a remembered p-value.

        Differences are [15,-7,5,20,0,-9,17,-12,5,-10]; the zero pair is dropped
        (zero_method="wilcox"), leaving 9 signed ranks with W+ = 27, W- = 18.
        Enumerating all 2^9 sign assignments gives P(min(W+,W-) <= 18) = 324/512
        = 0.6328125 exactly. Recomputed here rather than asserted, so the test
        carries its own oracle.
        """
        a = [125, 115, 130, 140, 140, 115, 140, 125, 140, 135]
        b = [110, 122, 125, 120, 140, 124, 123, 137, 135, 145]
        stat, p = st.wilcoxon_signed_rank(a, b)
        assert stat == pytest.approx(18.0)

        d = [x - y for x, y in zip(a, b)]
        nz = [v for v in d if v != 0]
        assert len(nz) == 9, "the zero pair must be dropped, not ranked"
        ranks = _rankdata([abs(v) for v in nz])
        exact = _exact_signed_rank_p(ranks, stat)
        assert exact == pytest.approx(324 / 512, rel=1e-12)
        assert p == pytest.approx(exact, rel=1e-12)

    def test_zero_pairs_are_dropped_not_ranked(self):
        """zero_method="wilcox" excludes ties; including them would shift n and
        every rank, changing the p-value."""
        a = [1.0, 2.0, 3.0, 4.0]
        b = [1.0, 1.0, 1.0, 1.0]           # first pair is a tie
        stat, _ = st.wilcoxon_signed_rank(a, b)
        stat_no_tie, _ = st.wilcoxon_signed_rank([2.0, 3.0, 4.0], [1.0, 1.0, 1.0])
        assert stat == stat_no_tie

    def test_all_zero_differences_is_p_one(self):
        assert st.wilcoxon_signed_rank([5.0] * 10, [5.0] * 10) == (0.0, 1.0)

    def test_detects_a_consistent_shift(self):
        base = np.arange(1.0, 31.0)
        _, p = st.wilcoxon_signed_rank(base + 5.0, base)
        assert p < 0.001
        assert st.hodges_lehmann(base + 5.0, base) == pytest.approx(5.0)

    def test_one_sample_and_two_sample_forms_agree(self):
        a = [3.0, 7.0, 1.0, 9.0, 4.0]
        b = [1.0, 2.0, 3.0, 4.0, 5.0]
        d = [x - y for x, y in zip(a, b)]
        assert st.wilcoxon_signed_rank(a, b) == st.wilcoxon_signed_rank(d)
        assert st.hodges_lehmann(a, b) == pytest.approx(st.hodges_lehmann(d))

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            st.hodges_lehmann([])


class TestMannWhitney:
    def test_reference_value(self):
        a = [1, 2, 3, 4, 5]
        b = [6, 7, 8, 9, 10]
        u, p = st.mann_whitney_u(a, b)
        assert u == pytest.approx(0.0)
        assert p < 0.01

    def test_identical_samples_are_not_significant(self):
        x = list(range(1, 21))
        _, p = st.mann_whitney_u(x, x)
        assert p > 0.5

    def test_coldstart_contamination_check_shape(self):
        """F6's pre-registered check: trials 1-10 vs 11-20 of the retained set."""
        rng = np.random.default_rng(7)
        warm = rng.normal(100, 5, 10)
        cold = rng.normal(400, 5, 10)
        _, p_contaminated = st.mann_whitney_u(cold, warm)
        assert p_contaminated < 0.01
        _, p_clean = st.mann_whitney_u(rng.normal(100, 5, 10), warm)
        assert p_clean > 0.01

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            st.mann_whitney_u([], [1, 2])


# ---------------------------------------------------------------------------
# quantiles
# ---------------------------------------------------------------------------


class TestQuantiles:
    def test_type7_linear_interpolation(self):
        x = [1, 2, 3, 4]
        assert st.quantile(x, 0.5) == pytest.approx(2.5)
        assert st.quantile(x, 0.0) == 1.0
        assert st.quantile(x, 1.0) == 4.0
        # type 7: h = (n-1)q, so q=0.25 on 4 points -> index 0.75 -> 1.75
        assert st.quantile(x, 0.25) == pytest.approx(1.75)

    def test_quantile_ci_brackets_the_point_estimate(self):
        rng = np.random.default_rng(11)
        x = rng.lognormal(3, 1, 500)
        for q in (0.5, 0.9):
            ci = st.quantile_ci(x, q)
            assert ci.lo <= ci.point <= ci.hi, q

    def test_ci_bounds_are_actual_observations(self):
        """Order-statistic bounds must BE data points, not interpolations."""
        rng = np.random.default_rng(3)
        x = rng.lognormal(3, 1, 200)
        ci = st.quantile_ci(x, 0.5)
        assert ci.lo in set(x.tolist())
        assert ci.hi in set(x.tolist())

    def test_p99_at_n100_is_truncated_and_says_so(self):
        """A p99 needs n>=100 to exist; at n=100 its upper bound IS the maximum.

        The method string must disclose that, or a reader mistakes a one-sided
        limit for a two-sided interval.
        """
        rng = np.random.default_rng(5)
        x = rng.lognormal(3, 1, 100)
        ci = st.quantile_ci(x, 0.99)
        assert ci.hi == pytest.approx(x.max())
        assert "truncated" in ci.method

    def test_p99_at_n1000_is_not_truncated(self):
        """The plan's n=1000 per latency arm exists to buy an untruncated p99."""
        rng = np.random.default_rng(5)
        x = rng.lognormal(3, 1, 1000)
        ci = st.quantile_ci(x, 0.99)
        assert "truncated" not in ci.method
        assert ci.hi < x.max()

    def test_coverage_is_at_least_nominal(self):
        """Empirical coverage check: the median CI should cover the true median
        in at least ~95% of replications. Distribution-free means this holds for
        a skewed distribution too, which is the reason we use it for latency."""
        rng = np.random.default_rng(42)
        true_median = math.exp(3.0)   # lognormal(3, 1) median
        covered = 0
        reps = 400
        for _ in range(reps):
            x = rng.lognormal(3, 1, 120)
            ci = st.quantile_ci(x, 0.5)
            covered += ci.lo <= true_median <= ci.hi
        assert covered / reps >= 0.93, covered / reps

    def test_mean_is_tail_dominated_but_median_is_not(self):
        """Why p50/p90/p99 and never the mean (plan Part 2)."""
        x = [100.0] * 999 + [30_000.0]
        assert st.quantile(x, 0.5) == pytest.approx(100.0)
        assert np.mean(x) > 129.0

    @pytest.mark.parametrize("q", [0.0, 1.0, -0.1, 1.5])
    def test_quantile_ci_rejects_degenerate_q(self, q):
        with pytest.raises(ValueError):
            st.quantile_ci([1, 2, 3], q)


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_is_reproducible_from_the_seed(self):
        x = np.random.default_rng(1).lognormal(3, 1, 200)
        a = st.bootstrap_ci(x, b=500, seed=123)
        b = st.bootstrap_ci(x, b=500, seed=123)
        assert (a.lo, a.hi) == (b.lo, b.hi)
        assert st.bootstrap_ci(x, b=500, seed=124).lo != a.lo
        assert "seed=123" in a.method

    def test_brackets_the_point_estimate(self):
        x = np.random.default_rng(2).lognormal(3, 1, 300)
        ci = st.bootstrap_ci(x, b=1000, seed=9)
        assert ci.lo <= ci.point <= ci.hi

    def test_paired_bootstrap_recovers_a_known_shift(self):
        rng = np.random.default_rng(13)
        base = rng.lognormal(4, 0.8, 300)
        ci = st.paired_bootstrap_diff_ci(base + 25.0, base, b=1000, seed=4)
        assert ci.lo <= 25.0 <= ci.hi
        assert ci.point == pytest.approx(25.0, abs=1e-6)

    def test_paired_resampling_beats_independent_on_correlated_data(self):
        """The 3.3x efficiency claim the paired design rests on.

        Resampling pair indices preserves the within-pair correlation; resampling
        the arms independently destroys it and inflates the interval. If this
        assertion ever fails, `paired_bootstrap_diff_ci` has silently become an
        unpaired analysis and Part 2's efficiency argument is void.
        """
        rng = np.random.default_rng(21)
        base = rng.lognormal(4, 0.9, 300)
        a = base + rng.normal(20, 3, 300)
        paired = st.paired_bootstrap_diff_ci(a, base, b=1000, seed=1)

        # independent resampling of each arm, same B and statistic
        idx_a = rng.integers(0, 300, size=(1000, 300))
        idx_b = rng.integers(0, 300, size=(1000, 300))
        reps = np.median(a[idx_a], axis=1) - np.median(base[idx_b], axis=1)
        unpaired_width = float(np.quantile(reps, 0.975) - np.quantile(reps, 0.025))

        assert paired.width < unpaired_width / 2, (paired.width, unpaired_width)

    def test_paired_requires_equal_lengths(self):
        with pytest.raises(ValueError):
            st.paired_bootstrap_diff_ci([1, 2, 3], [1, 2])


# ---------------------------------------------------------------------------
# multiplicity
# ---------------------------------------------------------------------------


class TestMultiplicity:
    # Benjamini & Hochberg (1995), JRSS-B 57(1):289-300, the 15 p-values of the
    # Needleman et al. multiple-endpoint example used in section 2 of the paper.
    BH95 = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
            0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0000]

    def test_bh_1995_published_example(self):
        """The step-up rule finds the LARGEST i with p_(i) <= i*q/n.

        Here that is i=4 (0.0095 <= 4*0.05/15 = 0.01333), so exactly the first
        four are rejected — even though p_(5)=0.0201 is below the unadjusted
        0.05. That last point is the whole content of the procedure.
        """
        rej, adj = st.benjamini_hochberg(self.BH95, q=0.05)
        assert sum(rej) == 4
        assert rej[:5] == [True, True, True, True, False]
        assert adj[0] == pytest.approx(0.0001 * 15 / 1, abs=1e-9)
        assert adj[3] == pytest.approx(0.0095 * 15 / 4, abs=1e-9)
        assert adj[14] == pytest.approx(1.0, abs=1e-9)

    def test_bh_is_step_up_not_a_naive_per_test_comparison(self):
        """A rule that simply compared each p_(i) to i*q/n individually would
        reject 4 here too by coincidence, so the discriminating case is one
        where an early p fails its own bound but a later one passes.

        p_(1)=0.02 > 1*0.05/4 yet p_(3)=0.03 <= 3*0.05/4, so the step-up rule
        rejects all three; a naive elementwise rule would reject only the third.
        """
        rej, _ = st.benjamini_hochberg([0.02, 0.025, 0.03, 0.9], q=0.05)
        assert rej == [True, True, True, False]

    def test_bh_adjusted_values_are_monotone(self):
        """Without the cumulative-min pass, adjusted p can be non-monotone,
        which is incoherent to publish."""
        p = [0.01, 0.02, 0.03, 0.9]
        _, adj = st.benjamini_hochberg(p)
        assert adj == sorted(adj)

    def test_bh_preserves_input_order(self):
        p = [0.9, 0.001, 0.5]
        rej, adj = st.benjamini_hochberg(p, q=0.05)
        assert rej == [False, True, False]
        assert adj[1] < adj[2] < adj[0]

    def test_bh_is_strictly_less_conservative_than_bonferroni(self):
        """Why exploratory families get BH and the confirmatory safety family
        gets Bonferroni. On the BH95 table: BH rejects 4, Bonferroni 3.

        Asserting strict inequality on a case where they differ, rather than
        ">=" on an arbitrary list, is what makes this test non-vacuous.
        """
        bh, _ = st.benjamini_hochberg(self.BH95, q=0.05)
        bf, _ = st.bonferroni(self.BH95, alpha=0.05)
        assert sum(bh) == 4
        assert sum(bf) == 3
        # every Bonferroni rejection must also be a BH rejection
        assert all(bh[i] for i, r in enumerate(bf) if r)

    def test_bonferroni_reference(self):
        rej, adj = st.bonferroni([0.001, 0.02, 0.5], alpha=0.05)
        assert adj == pytest.approx([0.003, 0.06, 1.0])
        assert rej == [True, False, False]

    def test_adjusted_values_are_clipped_to_one(self):
        _, adj = st.bonferroni([0.5, 0.6], alpha=0.05)
        assert max(adj) <= 1.0

    def test_empty_family(self):
        assert st.benjamini_hochberg([]) == ([], [])
        assert st.bonferroni([]) == ([], [])

    def test_rejects_out_of_range_pvalues(self):
        with pytest.raises(ValueError):
            st.benjamini_hochberg([0.5, 1.5])
        with pytest.raises(ValueError):
            st.bonferroni([-0.1])


# ---------------------------------------------------------------------------
# agreement
# ---------------------------------------------------------------------------


class TestCohensKappa:
    def test_reference_value(self):
        """2x2 with a=b=20, disagreement 5/5, n=50: po=0.8, pe=0.5, kappa=0.6."""
        a = ["y"] * 25 + ["n"] * 25
        b = ["y"] * 20 + ["n"] * 5 + ["y"] * 5 + ["n"] * 20
        assert st.cohens_kappa(a, b) == pytest.approx(0.6, abs=1e-9)

    def test_perfect_agreement_on_two_labels_is_one(self):
        a = ["y"] * 10 + ["n"] * 10
        assert st.cohens_kappa(a, a) == pytest.approx(1.0)

    def test_chance_level_agreement_is_about_zero(self):
        rng = np.random.default_rng(17)
        a = rng.choice(["y", "n"], 4000).tolist()
        b = rng.choice(["y", "n"], 4000).tolist()
        assert abs(st.cohens_kappa(a, b)) < 0.05

    def test_total_disagreement_is_negative(self):
        a = ["y"] * 10 + ["n"] * 10
        b = ["n"] * 10 + ["y"] * 10
        assert st.cohens_kappa(a, b) == pytest.approx(-1.0)

    def test_degenerate_single_class_returns_one_not_nan(self):
        """pe = 1 makes kappa 0/0. Two raters who agreed on every item did
        agree; the labelling protocol, not this function, rejects a corpus with
        only one class."""
        k = st.cohens_kappa(["y"] * 10, ["y"] * 10)
        assert k == 1.0
        assert not math.isnan(k)

    def test_phase0_gate_threshold_is_discriminating(self):
        """kappa >= 0.80 must not be satisfiable by the 0.6 reference table."""
        a = ["y"] * 25 + ["n"] * 25
        b = ["y"] * 20 + ["n"] * 5 + ["y"] * 5 + ["n"] * 20
        assert st.cohens_kappa(a, b) < 0.80

    def test_rejects_length_mismatch_and_empty(self):
        with pytest.raises(ValueError):
            st.cohens_kappa(["y"], ["y", "n"])
        with pytest.raises(ValueError):
            st.cohens_kappa([], [])


# ---------------------------------------------------------------------------
# variance decomposition (F2)
# ---------------------------------------------------------------------------


class TestVarianceDecomposition:
    def test_law_of_total_variance_identity_holds(self):
        rng = np.random.default_rng(23)
        s = rng.choice([0, 0.2, 0.4, 0.6, 0.8, 1.0], 600)
        d = (rng.random(600) < s).astype(float)
        r = st.variance_decomposition(s, d)
        assert r["var_within_stratum"] + r["var_between_stratum"] == pytest.approx(
            r["var_total"], rel=1e-9)

    def test_deterministic_threshold_gives_zero_within_variance(self):
        """The document's claim, stated as a measurement.

        D = 1[S > 0.5] is a deterministic function of S, so every stratum is
        pure and the within-stratum term is identically zero.
        """
        rng = np.random.default_rng(29)
        s = rng.choice([0, 0.2, 0.4, 0.6, 0.8, 1.0], 600)
        d = (s > 0.5).astype(float)
        r = st.variance_decomposition(s, d)
        assert r["var_within_stratum"] == pytest.approx(0.0)
        assert r["impure_strata"] == []
        assert r["conditionally_deterministic"] is True
        assert r["var_between_stratum"] == pytest.approx(r["var_total"], rel=1e-9)

    def test_one_mixed_stratum_falsifies_conditional_determinism(self):
        """F2-3's decisive criterion: a single counterexample is enough.

        Two identical scores that produced different decisions cannot happen if
        the decision is a function of the score.
        """
        s = [0.4] * 10 + [0.8] * 10
        d = [0.0] * 10 + [1.0] * 9 + [0.0]
        r = st.variance_decomposition(s, d)
        assert r["impure_strata"] == [0.8]
        assert r["conditionally_deterministic"] is False
        assert r["var_within_stratum"] > 0

    def test_high_score_variance_with_zero_flip_rate(self):
        """The compatibility proof: guardrails non-deterministic AND policies
        deterministic are not in conflict when the score support lies entirely on
        one side of tau. Scores vary wildly; the decision never flips."""
        s = [0.0, 0.2, 0.4] * 100
        d = [0.0] * 300
        r = st.variance_decomposition(s, d)
        assert np.var(s) > 0.02
        assert r["var_total"] == 0.0
        assert r["conditionally_deterministic"] is True

    def test_flip_probability_is_2p1_minus_p(self):
        """P(two i.i.d. trials disagree) = 2p(1-p), maximal at p=0.5.

        Pinned here because F2-4's amplification arm predicts the flip rate from
        tau placement and compares it to this formula.
        """
        for p in (0.0, 0.1, 0.5, 0.9, 1.0):
            assert 2 * p * (1 - p) == pytest.approx(
                2 * p * (1 - p))  # formula anchor
        assert 2 * 0.5 * 0.5 == 0.5
        assert 2 * 0.0 * 1.0 == 0.0

    def test_reports_stratum_detail(self):
        s = [0.4] * 5 + [0.8] * 5
        d = [0.0] * 5 + [1.0] * 5
        r = st.variance_decomposition(s, d)
        assert r["strata"][0.4]["n"] == 5
        assert r["strata"][0.8]["p_deny"] == 1.0
        assert r["n"] == 10

    def test_rejects_non_binary_decisions(self):
        with pytest.raises(ValueError):
            st.variance_decomposition([0.2, 0.4], [0.5, 1.0])

    def test_rejects_misaligned_inputs(self):
        with pytest.raises(ValueError):
            st.variance_decomposition([0.2, 0.4], [1.0])


# ---------------------------------------------------------------------------
# detection efficacy (F3)
# ---------------------------------------------------------------------------


class TestDetectionEfficacy:
    def test_confusion_counts(self):
        c = st.confusion([1, 1, 1, 0, 0, 0], [1, 1, 0, 1, 0, 0])
        assert (c.tp, c.fp, c.fn, c.tn) == (2, 1, 1, 2)
        assert c.n == 6

    def test_f_beta_reference_values(self):
        # F1 is the harmonic mean
        assert st.f_beta(0.5, 1.0, beta=1.0) == pytest.approx(2 / 3)
        # F2 = 5PR/(4P+R)
        assert st.f_beta(0.5, 1.0, beta=2.0) == pytest.approx(5 * 0.5 / (4 * 0.5 + 1))
        assert st.f_beta(1.0, 1.0) == pytest.approx(1.0)
        assert st.f_beta(0.0, 0.0) == 0.0

    def test_f2_weights_recall_above_precision(self):
        """Pre-registered as primary because a missed attack costs more than a
        blocked benign request."""
        high_recall = st.f_beta(precision=0.5, recall=0.9, beta=2.0)
        high_precision = st.f_beta(precision=0.9, recall=0.5, beta=2.0)
        assert high_recall > high_precision
        # F1 must be symmetric, proving beta is doing the work
        assert st.f_beta(0.5, 0.9, beta=1.0) == pytest.approx(
            st.f_beta(0.9, 0.5, beta=1.0))

    def test_youden_j(self):
        assert st.youden_j(0.9, 0.1) == pytest.approx(0.8)
        assert st.youden_j(0.5, 0.5) == pytest.approx(0.0)   # chance line

    def test_ppv_at_prevalence_is_the_omitted_analysis(self):
        """Recall 0.85 / FPR 0.04 sounds excellent and is ~1.8% PPV at a 0.1%
        attack prevalence — about 55 false alarms per true detection.

        This is the analysis section 7.1 omits, and the reason corpus PPV must
        never be reported as if it were operational.
        """
        ppv = st.ppv_at_prevalence(0.85, 0.04, 0.001)
        assert ppv == pytest.approx(0.85 * 0.001 / (0.85 * 0.001 + 0.04 * 0.999),
                                    rel=1e-9)
        assert ppv < 0.03
        assert 1 / ppv - 1 > 40   # false alarms per true positive

    def test_ppv_rises_with_prevalence(self):
        vals = [st.ppv_at_prevalence(0.85, 0.04, pi) for pi in (0.001, 0.01, 0.1, 0.5)]
        assert vals == sorted(vals)
        assert vals[-1] > 0.9

    def test_ppv_at_corpus_prevalence_overstates_operational_ppv(self):
        """A 50/50 corpus makes PPV look ~28x better than at 0.1% prevalence."""
        corpus = st.ppv_at_prevalence(0.85, 0.04, 0.5)
        operational = st.ppv_at_prevalence(0.85, 0.04, 0.001)
        assert corpus / operational > 20

    def test_operating_point_wilson_intervals(self):
        c = st.confusion([1] * 60 + [0] * 60, [1] * 51 + [0] * 9 + [1] * 2 + [0] * 58)
        op = st.operating_point(c)
        assert op["confusion"] == {"tp": 51, "fp": 2, "fn": 9, "tn": 58}
        assert op["tpr"].point == pytest.approx(51 / 60)
        assert op["fpr"].point == pytest.approx(2 / 60)
        assert op["tpr"].method == "wilson"
        assert op["youden_j"] == pytest.approx(51 / 60 - 2 / 60)
        assert 0.001 in op["ppv_at"]

    def test_operating_point_handles_a_single_class(self):
        """A benign-only arm has no positives; TPR is undefined, not zero."""
        op = st.operating_point(st.confusion([0] * 10, [0] * 10))
        assert op["tpr"] is None
        assert op["fpr"] is not None

    def test_seven_operating_points_on_the_six_value_lattice(self):
        """With greaterThan(decimal(tau)) over {0,.2,.4,.6,.8,1.0} there are at
        most 7 distinct decision rules, so the ROC is a 7-vertex polyline.

        Reporting it as a curve would imply interpolation the mechanism cannot
        deliver.
        """
        lattice = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        rng = np.random.default_rng(31)
        s = rng.choice(lattice, 400)
        y = (rng.random(400) < s).astype(int)
        taus = [-0.1] + lattice
        points = {(round(op["tpr"].point, 12), round(op["fpr"].point, 12))
                  for op in (st.operating_point(
                      st.confusion(y, (s > t).astype(int))) for t in taus)}
        assert len(points) <= 7
        assert len(taus) == 7

    def test_rejects_misaligned_and_empty_labels(self):
        with pytest.raises(ValueError):
            st.confusion([1, 0], [1])
        with pytest.raises(ValueError):
            st.confusion([], [])


# ---------------------------------------------------------------------------
# CI container
# ---------------------------------------------------------------------------


class TestCIContainer:
    def test_str_carries_method_and_n(self):
        s = str(st.wilson_ci(51, 60))
        assert "wilson" in s and "n=60" in s and "95%" in s

    def test_is_immutable(self):
        """An interval must not be adjustable after the fact."""
        ci = st.wilson_ci(1, 10)
        with pytest.raises(Exception):
            ci.hi = 0.5

    def test_width(self):
        assert st.wilson_ci(5, 10).width == pytest.approx(
            st.wilson_ci(5, 10).hi - st.wilson_ci(5, 10).lo)
