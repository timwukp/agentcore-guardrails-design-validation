#!/usr/bin/env python3
"""Mutation run for lib/stats.py — proof that test_stats.py can actually fail.

Why this file exists
--------------------
A passing test suite is evidence of nothing until you show its assertions are
load-bearing. A Wilson implementation that returned ``[0, 1]`` unconditionally
would satisfy every "is the interval inside [0,1]" check; a McNemar that ignored
the continuity correction would satisfy "p is about 0.1". The same principle the
experimental design uses on AWS controls — remove the control, prove the attack
succeeds — is applied here to our own analysis code.

How it works
------------
Each ``MUTANTS`` entry is a textual substitution applied to a copy of
``stats.py``. The mutated module is imported under a private name and the
*specific* assertions that should catch it are re-executed against it. A mutant
that survives (no assertion fires) is a **test-suite defect**, and this file
fails, naming it.

This is deliberately a separate file from ``test_stats.py``: it must never share
the module object that suite imports, or one mutation would corrupt every
subsequent test.

Run directly for a report:
    python3 tests/test_stats_mutation.py
"""

from __future__ import annotations

import importlib.util
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

STATS_SRC = Path(__file__).resolve().parents[1] / "stats.py"


@dataclass(frozen=True)
class Mutant:
    """One deliberate defect and the property that must detect it."""
    mid: str
    target: str            # the exact source substring to replace
    replacement: str
    rationale: str         # the real-world error this mutation impersonates
    check: str             # name of the detector function below


# The defects below are not arbitrary: each is a mistake that is easy to make and
# that would silently change a published number.
MUTANTS = [
    Mutant(
        "M1-wilson-becomes-wald",
        "centre = (p + z * z / (2 * n)) / denom",
        "centre = p",
        "The single most likely error: reverting to the Wald centre. Passes any "
        "'interval contains p-hat' test but degenerates to [0,0] at x=0.",
        "detect_wilson",
    ),
    Mutant(
        "M2-wilson-drops-continuity-term",
        "math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))",
        "math.sqrt(p * (1 - p) / n)",
        "Dropping z^2/4n^2 collapses the half-width to zero at x=0, "
        "reintroducing the degenerate '0% CI [0%,0%]' claim.",
        "detect_wilson",
    ),
    Mutant(
        "M3-wilson-unconditional-unit-interval",
        "return CI(p, lo, hi, n, \"wilson\", level)",
        "return CI(p, 0.0, 1.0, n, \"wilson\", level)",
        "The vacuous implementation. Satisfies every bounds check and every "
        "'contains the truth' coverage check by construction.",
        "detect_wilson",
    ),
    Mutant(
        "M4-clopper-pearson-off-by-one-shape",
        "sps.beta.ppf(1 - alpha / 2, x + 1, n - x)",
        "sps.beta.ppf(1 - alpha / 2, x, n - x)",
        "The classic Clopper-Pearson shape-parameter slip; breaks the identity "
        "with the exact rule-of-three at x=0.",
        "detect_clopper_pearson",
    ),
    Mutant(
        "M5-rule-of-three-uses-approximation",
        "return 1 - tail ** (1 / n)",
        "return 3.0 / n",
        "Using 3/n as if it were exact. Small, but it inflates every published "
        "safety bound and breaks the Clopper-Pearson identity.",
        "detect_rule_of_three",
    ),
    Mutant(
        "M6-rule-of-three-ignores-sidedness",
        "tail = alpha if one_sided else alpha / 2",
        "tail = alpha",
        "Silently reporting a one-sided bound where a two-sided one was asked "
        "for — an understatement of uncertainty.",
        "detect_rule_of_three_sidedness",
    ),
    Mutant(
        "M7-required-n-floors-instead-of-ceils",
        "return int(math.ceil(math.log(1 - power) / math.log(1 - p1)))",
        "return int(math.log(1 - power) / math.log(1 - p1))",
        "floor() instead of ceil() returns an n that is one trial UNDERpowered "
        "— the pre-registered sample size would be wrong.",
        "detect_required_n",
    ),
    Mutant(
        "M8-mcnemar-drops-continuity-correction",
        "stat = (abs(b - c) - 1) ** 2 / nd",
        "stat = (b - c) ** 2 / nd",
        "Dropping Yates makes the test anti-conservative: p falls from 0.1206 "
        "to 0.1059 on the reference table.",
        "detect_mcnemar",
    ),
    Mutant(
        "M9-mcnemar-uses-concordant-cells",
        "nd = b + c",
        "nd = b + c + 1",
        "Any contamination of the discordant-pair denominator; McNemar's whole "
        "premise is that concordant pairs carry no information.",
        "detect_mcnemar",
    ),
    Mutant(
        "M10-mcnemar-always-chi-square",
        "exact = nd < 25",
        "exact = False",
        "Applying the chi-square approximation to tiny discordance counts, "
        "where it is known to be unreliable.",
        "detect_mcnemar_exact_branch",
    ),
    Mutant(
        "M11-hodges-lehmann-becomes-mean",
        "return float(np.median((d[i] + d[j]) / 2))",
        "return float(np.mean((d[i] + d[j]) / 2))",
        "The exact failure the estimator was chosen to avoid: a mean of Walsh "
        "averages is dragged by one 30-second retry tail.",
        "detect_hodges_lehmann",
    ),
    Mutant(
        "M12-hodges-lehmann-excludes-diagonal",
        "i, j = np.triu_indices(d.size, k=0)",
        "i, j = np.triu_indices(d.size, k=1)",
        "k=1 drops the (i,i) pairs, so it is no longer the median of Walsh "
        "averages and no longer pairs with the signed-rank test.",
        "detect_hodges_lehmann_walsh",
    ),
    Mutant(
        "M13-bh-loses-monotonicity-pass",
        "adj = np.minimum.accumulate(adj[::-1])[::-1]",
        "adj = adj",
        "Without the cumulative-min pass, adjusted p-values can be "
        "non-monotone in the raw p-values — incoherent to publish.",
        "detect_bh_monotone",
    ),
    Mutant(
        "M14-bh-becomes-bonferroni",
        "adj = ranked * n / np.arange(1, n + 1)",
        "adj = ranked * n",
        "Collapsing the step-up rule to Bonferroni. Over-conservative: it would "
        "hide real findings in the exploratory families.",
        "detect_bh_vs_bonferroni",
    ),
    Mutant(
        "M15-bh-loses-input-order",
        "out_adj[order] = adj",
        "out_adj[:] = adj",
        "Returning adjusted values in sorted rather than input order silently "
        "misattributes every p-value to the wrong hypothesis.",
        "detect_bh_order",
    ),
    Mutant(
        "M16-kappa-becomes-raw-agreement",
        "return (po - pe) / (1 - pe)",
        "return po",
        "Reporting raw agreement as kappa. Inflates the Phase-0 gate: the 0.6 "
        "reference table would read 0.8 and pass a kappa >= 0.80 gate.",
        "detect_kappa",
    ),
    Mutant(
        "M17-variance-decomposition-unweighted",
        "within += w * v",
        "within += v",
        "Unweighted stratum aggregation breaks the law-of-total-variance "
        "identity, so the F2 headline split would not reconcile.",
        "detect_variance_identity",
    ),
    Mutant(
        "M18-impure-strata-never-flagged",
        "if v > 0:",
        "if v > 1.0:",
        "The F2-3 falsification criterion silently disabled: a mixed stratum "
        "would be reported as conditional determinism CONFIRMED.",
        "detect_impure_strata",
    ),
    Mutant(
        "M19-f-beta-ignores-beta",
        "b2 = beta * beta",
        "b2 = 1.0",
        "F2 silently computed as F1, discarding the pre-registered "
        "recall-weighting that reflects asymmetric cost.",
        "detect_f_beta",
    ),
    Mutant(
        "M20-ppv-ignores-prevalence",
        "num = tpr * prevalence",
        "num = tpr",
        "The Bayes re-expression neutered; corpus PPV would be reported as if "
        "it were operational PPV, which is the error section 7.1 makes.",
        "detect_ppv",
    ),
    Mutant(
        "M21-quantile-ci-not-truncation-aware",
        "truncated = (k_hi - 1) >= n",
        "truncated = False",
        "A p99 at n=100 whose upper bound IS the sample max would be presented "
        "as a two-sided interval.",
        "detect_quantile_truncation",
    ),
    Mutant(
        "M22-paired-bootstrap-resamples-independently",
        "reps = np.array([statistic(a[i]) - statistic(c[i]) for i in idx])",
        "reps = np.array([statistic(a[i]) - statistic(c[j]) "
        "for i, j in zip(idx, rng.integers(0, a.size, size=(b, a.size)))])",
        "Destroying the pairing — the single most consequential silent error in "
        "the latency analysis. It discards the ~3.3x efficiency the design buys "
        "while still returning a plausible-looking interval.",
        "detect_paired_bootstrap",
    ),
]


# ---------------------------------------------------------------------------
# detectors: each re-runs the assertions that must catch its mutants
# ---------------------------------------------------------------------------


def detect_wilson(m) -> None:
    # Newcombe (1998) Table I reference values
    ci = m.wilson_ci(81, 263)
    assert ci.lo == pytest.approx(0.2553, abs=5e-4)
    assert ci.hi == pytest.approx(0.3662, abs=5e-4)
    # non-degenerate at the boundary, and bounds ordered
    z = m.wilson_ci(0, 20)
    assert z.lo == 0.0 and 0.15 < z.hi < 0.20
    assert z.lo <= z.point <= z.hi
    # width must shrink like 1/sqrt(n)
    w20, w2000 = m.wilson_ci(10, 20).width, m.wilson_ci(1000, 2000).width
    assert w20 / w2000 == pytest.approx(10.0, rel=0.15)


def detect_clopper_pearson(m) -> None:
    ci = m.clopper_pearson_ci(3, 10)
    assert ci.lo == pytest.approx(0.06674, abs=1e-4)
    assert ci.hi == pytest.approx(0.65245, abs=1e-4)
    for n in (10, 60, 300):
        assert m.clopper_pearson_ci(0, n).hi == pytest.approx(
            m.rule_of_three(n, one_sided=False), rel=1e-9)


def detect_rule_of_three(m) -> None:
    assert m.rule_of_three(60) == pytest.approx(0.04870, abs=5e-5)
    assert m.rule_of_three(300) == pytest.approx(0.009936, abs=5e-6)
    assert m.rule_of_three(100) < 3.0 / 100
    assert m.clopper_pearson_ci(0, 60).hi == pytest.approx(
        m.rule_of_three(60, one_sided=False), rel=1e-9)


def detect_rule_of_three_sidedness(m) -> None:
    assert m.rule_of_three(60, one_sided=True) < m.rule_of_three(60, one_sided=False)
    assert m.clopper_pearson_ci(0, 60).hi == pytest.approx(
        m.rule_of_three(60, one_sided=False), rel=1e-9)


def detect_required_n(m) -> None:
    assert m.required_n_for_zero_events(0.05, 0.95) == 59
    assert m.required_n_for_zero_events(0.01, 0.95) == 299
    for p1 in (0.001, 0.01, 0.05):
        n = m.required_n_for_zero_events(p1, 0.95)
        assert m.power_for_zero_events(n, p1) >= 0.95
        assert m.power_for_zero_events(n - 1, p1) < 0.95


def detect_mcnemar(m) -> None:
    stat, p = m.mcnemar_test(132, 107, exact=False)
    assert stat == pytest.approx(576 / 239, rel=1e-9)
    assert p == pytest.approx(0.12056, abs=5e-5)


def detect_mcnemar_exact_branch(m) -> None:
    _, p_auto = m.mcnemar_test(1, 9)
    assert p_auto == pytest.approx(2 * 11 / 1024, rel=1e-9)
    assert m.mcnemar_test(2, 8)[1] == m.mcnemar_test(2, 8, exact=True)[1]


def detect_hodges_lehmann(m) -> None:
    tail = [10.0] * 19 + [30_000.0]
    assert m.hodges_lehmann(tail) == pytest.approx(10.0)
    base = np.arange(1.0, 31.0)
    assert m.hodges_lehmann(base + 5.0, base) == pytest.approx(5.0)


def detect_hodges_lehmann_walsh(m) -> None:
    d = [1.0, 2.0, 4.0]
    walsh = [1.0, 1.5, 2.5, 2.0, 3.0, 4.0]        # includes (i,i)
    assert m.hodges_lehmann(d) == pytest.approx(float(np.median(walsh)))


def detect_bh_monotone(m) -> None:
    _, adj = m.benjamini_hochberg([0.01, 0.02, 0.03, 0.9])
    assert adj == sorted(adj)
    _, adj2 = m.benjamini_hochberg(
        [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
         0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0])
    assert adj2 == sorted(adj2)


def detect_bh_vs_bonferroni(m) -> None:
    bh95 = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
            0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0]
    bh, adj = m.benjamini_hochberg(bh95, q=0.05)
    bf, _ = m.bonferroni(bh95, alpha=0.05)
    assert sum(bh) == 4
    assert sum(bf) == 3
    assert adj[3] == pytest.approx(0.0095 * 15 / 4, abs=1e-9)


def detect_bh_order(m) -> None:
    rej, adj = m.benjamini_hochberg([0.9, 0.001, 0.5], q=0.05)
    assert rej == [False, True, False]
    assert adj[1] < adj[2] < adj[0]


def detect_kappa(m) -> None:
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 5 + ["n"] * 20
    assert m.cohens_kappa(a, b) == pytest.approx(0.6, abs=1e-9)
    assert m.cohens_kappa(a, b) < 0.80          # the Phase-0 gate must not pass
    rng = np.random.default_rng(17)
    x = rng.choice(["y", "n"], 4000).tolist()
    y = rng.choice(["y", "n"], 4000).tolist()
    assert abs(m.cohens_kappa(x, y)) < 0.05     # chance agreement is ~0, not ~0.5


def detect_variance_identity(m) -> None:
    rng = np.random.default_rng(23)
    s = rng.choice([0, 0.2, 0.4, 0.6, 0.8, 1.0], 600)
    d = (rng.random(600) < s).astype(float)
    r = m.variance_decomposition(s, d)
    assert r["var_within_stratum"] + r["var_between_stratum"] == pytest.approx(
        r["var_total"], rel=1e-9)


def detect_impure_strata(m) -> None:
    s = [0.4] * 10 + [0.8] * 10
    d = [0.0] * 10 + [1.0] * 9 + [0.0]
    r = m.variance_decomposition(s, d)
    assert r["impure_strata"] == [0.8]
    assert r["conditionally_deterministic"] is False


def detect_f_beta(m) -> None:
    assert m.f_beta(0.5, 1.0, beta=2.0) == pytest.approx(5 * 0.5 / (4 * 0.5 + 1))
    assert m.f_beta(0.5, 0.9, beta=2.0) > m.f_beta(0.9, 0.5, beta=2.0)
    assert m.f_beta(0.5, 1.0, beta=2.0) != pytest.approx(m.f_beta(0.5, 1.0, beta=1.0))


def detect_ppv(m) -> None:
    assert m.ppv_at_prevalence(0.85, 0.04, 0.001) < 0.03
    vals = [m.ppv_at_prevalence(0.85, 0.04, pi) for pi in (0.001, 0.01, 0.1, 0.5)]
    assert vals == sorted(vals)
    assert vals[3] / vals[0] > 20


def detect_quantile_truncation(m) -> None:
    rng = np.random.default_rng(5)
    x = rng.lognormal(3, 1, 100)
    ci = m.quantile_ci(x, 0.99)
    assert ci.hi == pytest.approx(x.max())
    assert "truncated" in ci.method
    big = m.quantile_ci(rng.lognormal(3, 1, 1000), 0.99)
    assert "truncated" not in big.method


def detect_paired_bootstrap(m) -> None:
    rng = np.random.default_rng(21)
    base = rng.lognormal(4, 0.9, 300)
    a = base + rng.normal(20, 3, 300)
    paired = m.paired_bootstrap_diff_ci(a, base, b=1000, seed=1)
    idx_a = rng.integers(0, 300, size=(1000, 300))
    idx_b = rng.integers(0, 300, size=(1000, 300))
    reps = np.median(a[idx_a], axis=1) - np.median(base[idx_b], axis=1)
    unpaired_width = float(np.quantile(reps, 0.975) - np.quantile(reps, 0.025))
    assert paired.width < unpaired_width / 2


DETECTORS = {
    name: obj for name, obj in list(globals().items()) if name.startswith("detect_")
}


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


def _failing_assertion(exc: BaseException) -> str:
    """Recover 'line NN: <source>' for the innermost frame inside a detector.

    Kills must be attributable. Without this, every kill reports the same empty
    string and a mutant killed by an unrelated crash is indistinguishable from
    one killed by the assertion that was supposed to catch it.
    """
    import traceback
    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if f.filename == __file__]
    if not ours:
        return ""
    frame = ours[-1]
    src = (frame.line or "").strip()
    return f"line {frame.lineno}: {src[:110]}"


def _load_mutant(src: str, name: str):
    """Import mutated source as a fresh module under a private name."""
    path = STATS_SRC.parent / f".mutant_{name}.py"
    path.write_text(src, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(f"_mutant_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        # Register before exec: @dataclass resolves cls.__module__ via sys.modules
        # and raises AttributeError on a NoneType module otherwise.
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod, spec.name
    finally:
        path.unlink(missing_ok=True)
        # The bytecode cache outlives the source it was compiled from. Leaving
        # .mutant_*.pyc on disk means deliberately-broken statistics code sits in
        # the tree after the run, importable by anything that guesses the name.
        for pyc in (STATS_SRC.parent / "__pycache__").glob(f".mutant_{name}.*.pyc"):
            pyc.unlink(missing_ok=True)


def run_mutant(mut: Mutant) -> tuple[bool, str]:
    """Apply one mutation. Returns (killed, detail)."""
    original = STATS_SRC.read_text(encoding="utf-8")
    occurrences = original.count(mut.target)
    if occurrences != 1:
        return False, (f"target string appears {occurrences} times, expected "
                       f"exactly 1 — the mutation is not well-defined")
    mutated = original.replace(mut.target, mut.replacement)
    if mutated == original:
        return False, "mutation was a no-op"

    modname = None
    try:
        mod, modname = _load_mutant(mutated, mut.mid.replace("-", "_"))
    except Exception as exc:
        # A mutant that will not even import is killed by the compiler.
        return True, f"killed at import: {type(exc).__name__}: {exc}"

    try:
        DETECTORS[mut.check](mod)
    except AssertionError as exc:
        # A bare `assert x == approx(y)` carries no message, so str(exc) is "".
        # Recover the failing source line from the traceback instead: "killed"
        # is only auditable evidence if it names WHICH assertion fired, or a
        # coincidental unrelated failure would read the same as a real kill.
        return True, f"killed by {mut.check} at {_failing_assertion(exc) or '?'}"
    except Exception as exc:
        return True, f"killed by {mut.check} ({type(exc).__name__}): {exc}"
    finally:
        sys.modules.pop(modname, None)

    return False, f"SURVIVED {mut.check} — the test suite does not detect this"


@pytest.mark.parametrize("mut", MUTANTS, ids=[m.mid for m in MUTANTS])
def test_mutant_is_killed(mut: Mutant) -> None:
    """Every deliberate defect must be caught by the assertions that cover it.

    A surviving mutant is a defect in test_stats.py, not in this file.
    """
    killed, detail = run_mutant(mut)
    assert killed, f"{mut.mid}: {detail}\n  rationale: {mut.rationale}"


def test_unmutated_source_passes_every_detector() -> None:
    """Control arm: the detectors must all PASS on the real module.

    Without this, a detector that raised unconditionally would 'kill' every
    mutant and the whole run would be meaningless — the mutation-testing
    equivalent of a broken oracle.
    """
    import stats as real
    for name, fn in sorted(DETECTORS.items()):
        fn(real)   # must not raise


def main() -> int:
    import stats as real
    print(f"stats.py : {STATS_SRC}")
    print(f"mutants  : {len(MUTANTS)}")
    print(f"detectors: {len(DETECTORS)}\n")

    print("control arm (detectors vs unmutated source)")
    for name, fn in sorted(DETECTORS.items()):
        try:
            fn(real)
            print(f"  PASS  {name}")
        except Exception as exc:
            print(f"  BROKEN ORACLE  {name}: {exc}")
            return 1
    print()

    survivors = []
    for mut in MUTANTS:
        killed, detail = run_mutant(mut)
        print(f"  {'KILLED  ' if killed else 'SURVIVED'} {mut.mid:<42} {detail}")
        if not killed:
            survivors.append(mut)

    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed")
    if survivors:
        print("\nSURVIVING MUTANTS (test-suite defects):")
        for s in survivors:
            print(f"  {s.mid}\n    {s.rationale}")
        return 1
    print("mutation score 100% — every assertion is load-bearing")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(STATS_SRC.parent))
    raise SystemExit(main())
