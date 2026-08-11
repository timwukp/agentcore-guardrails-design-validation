#!/usr/bin/env python3
"""Statistical primitives for the guardrails validation platform.

Every function here is pure: no I/O, no AWS, no global state. The accompanying
test suite runs offline under an autouse fixture that nulls credentials and
blocks ``socket.connect``, so this layer provably cannot touch AWS.

Scope discipline
----------------
Nothing in this module decides whether a claim passed. It computes intervals and
p-values; the decision rule lives in ``PREREGISTRATION.yaml``. That separation is
what makes the pre-registration meaningful — otherwise a threshold could be
adjusted here after seeing the data.

Interval choices, and why not the obvious alternative
-----------------------------------------------------
* **Wilson**, not Wald, for every proportion. Wald is ``p̂ ± z·√(p̂(1-p̂)/n)``;
  at ``p̂ = 0`` it degenerates to ``[0, 0]``, which would license the sentence
  "0% false positives, 95% CI [0%, 0%]" from n=20. Our results live at the
  boundaries (recall near 1, FPR near 0), which is exactly where Wald's coverage
  collapses.
* **Clopper–Pearson** for zero/full cells, where guaranteed (conservative)
  coverage matters more than short intervals, and because it closes to the
  rule of three at ``X = 0``.
* **Distribution-free order-statistic** CIs for quantiles. Latency is
  right-skewed with retry tails; a normal-theory interval around a p99 is not
  defensible, and the mean is tail-dominated and is not what an SLA is written
  against.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats as sps

__all__ = [
    "CI", "wilson_ci", "clopper_pearson_ci", "rule_of_three", "exact_binom_test",
    "required_n_for_zero_events", "power_for_zero_events", "mcnemar_test",
    "wilcoxon_signed_rank", "hodges_lehmann", "quantile", "quantile_ci",
    "bootstrap_ci", "paired_bootstrap_diff_ci", "mann_whitney_u",
    "benjamini_hochberg", "bonferroni", "cohens_kappa", "variance_decomposition",
    "confusion", "operating_point", "ppv_at_prevalence", "youden_j", "f_beta",
]

Z_95 = 1.959963984540054  # scipy.stats.norm.ppf(0.975); pinned for reproducibility


# ---------------------------------------------------------------------------
# proportions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CI:
    """A point estimate with an interval and the method that produced it."""
    point: float
    lo: float
    hi: float
    n: int
    method: str
    level: float = 0.95

    def __str__(self) -> str:
        return (f"{self.point:.4g} [{self.lo:.4g}, {self.hi:.4g}] "
                f"(n={self.n}, {self.method}, {self.level:.0%})")

    @property
    def width(self) -> float:
        return self.hi - self.lo


def _check_counts(x: int, n: int) -> None:
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if not (0 <= x <= n):
        raise ValueError(f"x must satisfy 0 <= x <= n, got x={x}, n={n}")
    if int(x) != x or int(n) != n:
        raise ValueError(f"x and n must be integers, got x={x!r}, n={n!r}")


def wilson_ci(x: int, n: int, level: float = 0.95) -> CI:
    """Wilson score interval for a binomial proportion.

        CI = [ p̂ + z²/2n ± z·√( p̂(1-p̂)/n + z²/4n² ) ] / (1 + z²/n)

    The interval is the set of p not rejected by the score test, so it never
    leaves [0, 1] and stays non-degenerate at p̂ = 0 or 1 — the two places our
    safety results actually land.
    """
    _check_counts(x, n)
    z = sps.norm.ppf(0.5 + level / 2)
    p = x / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) * z / denom
    # At x=0, centre and half are analytically EQUAL, so the lower bound is
    # exactly 0 — but in floating point the subtraction leaves ~5.6e-17, which
    # would make lo > point and print as "0.0000 [0.0000, 0.5615]" while
    # silently violating lo <= point. Same at x=n for the upper bound. Clamp
    # the two boundary cases to their exact analytic values.
    lo = 0.0 if x == 0 else max(0.0, centre - half)
    hi = 1.0 if x == n else min(1.0, centre + half)
    return CI(p, lo, hi, n, "wilson", level)


def clopper_pearson_ci(x: int, n: int, level: float = 0.95) -> CI:
    """Exact (Clopper–Pearson) interval via the Beta quantile relationship.

        p_L = Beta⁻¹(α/2;   x,   n-x+1)
        p_U = Beta⁻¹(1-α/2; x+1, n-x  )

    Guaranteed ≥ nominal coverage — conservative, and the right choice when a
    safety bound is being asserted. Degenerate tails are handled explicitly:
    at x=0 the lower bound is exactly 0, at x=n the upper bound is exactly 1.
    """
    _check_counts(x, n)
    alpha = 1 - level
    lo = 0.0 if x == 0 else float(sps.beta.ppf(alpha / 2, x, n - x + 1))
    hi = 1.0 if x == n else float(sps.beta.ppf(1 - alpha / 2, x + 1, n - x))
    return CI(x / n, lo, hi, n, "clopper-pearson", level)


def rule_of_three(n: int, level: float = 0.95, one_sided: bool = True) -> float:
    """Upper bound on an event rate after observing ZERO events in n trials.

    Exact form: ``1 - α^(1/n)`` one-sided (``1 - (α/2)^(1/n)`` two-sided), which
    is what Clopper–Pearson collapses to at x=0. The familiar ``3/n`` is the
    first-order approximation, since ``-ln(0.05) ≈ 2.996``.

    This is the function that fixes our corpus sizes: n=20 buys only "under 14%",
    which is not a publishable safety claim, while n=60 buys "under 5%".
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    alpha = 1 - level
    tail = alpha if one_sided else alpha / 2
    return 1 - tail ** (1 / n)


def exact_binom_test(x: int, n: int, p0: float, alternative: str = "two-sided") -> float:
    """Exact binomial test p-value. `alternative` in {two-sided, less, greater}."""
    _check_counts(x, n)
    if not 0 <= p0 <= 1:
        raise ValueError(f"p0 must be in [0, 1], got {p0}")
    return float(sps.binomtest(x, n, p0, alternative=alternative).pvalue)


def power_for_zero_events(n: int, p1: float) -> float:
    """Power of "observe ≥1 event in n trials" against a true rate p1.

        power = 1 - (1 - p1)^n

    This is the determinism design: H₀ is p_flip = 0, and the only evidence
    against it is a single observed flip.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if not 0 < p1 <= 1:
        raise ValueError(f"p1 must be in (0, 1], got {p1}")
    return 1 - (1 - p1) ** n


def required_n_for_zero_events(p1: float, power: float = 0.95) -> int:
    """Smallest n with power ≥ `power` to see ≥1 event when the true rate is p1.

        n ≥ ln(1 - power) / ln(1 - p1)

    p1=0.05, power=0.95 -> 59.  p1=0.01, power=0.95 -> 298.
    The plan's pre-registered n=300 per determinism cell comes from the second.
    """
    if not 0 < p1 < 1:
        raise ValueError(f"p1 must be in (0, 1), got {p1}")
    if not 0 < power < 1:
        raise ValueError(f"power must be in (0, 1), got {power}")
    return int(math.ceil(math.log(1 - power) / math.log(1 - p1)))


# ---------------------------------------------------------------------------
# paired categorical
# ---------------------------------------------------------------------------


def mcnemar_test(b: int, c: int, exact: bool | None = None) -> tuple[float, float]:
    """McNemar's test on the two discordant cells of a paired 2x2 table.

    `b` and `c` are the counts where the two arms disagree; the concordant cells
    carry no information about a difference and are correctly ignored. Returns
    ``(statistic, p_value)``.

    Exact binomial is used when ``b + c < 25`` (default), where the chi-square
    approximation is unreliable. With ``b + c == 0`` the arms never disagreed:
    p = 1.0, and the statistic is reported as 0.0 rather than raising, since
    "identical behaviour" is a legitimate and expected F5-6 outcome.
    """
    if b < 0 or c < 0:
        raise ValueError(f"counts must be non-negative, got b={b}, c={c}")
    nd = b + c
    if nd == 0:
        return 0.0, 1.0
    if exact is None:
        exact = nd < 25
    if exact:
        return float(min(b, c)), float(sps.binomtest(min(b, c), nd, 0.5,
                                                     alternative="two-sided").pvalue)
    stat = (abs(b - c) - 1) ** 2 / nd          # Yates continuity correction
    return float(stat), float(sps.chi2.sf(stat, df=1))


# ---------------------------------------------------------------------------
# paired continuous (latency)
# ---------------------------------------------------------------------------


def wilcoxon_signed_rank(a, b=None) -> tuple[float, float]:
    """Wilcoxon signed-rank test on paired samples (or one sample of diffs).

    Distribution-free: appropriate for latency, which is right-skewed. Returns
    ``(statistic, p_value)``. All-zero differences give p = 1.0 rather than a
    scipy error, since identical latency is a meaningful result.
    """
    d = np.asarray(a, float) - (0 if b is None else np.asarray(b, float))
    if d.size == 0:
        raise ValueError("empty sample")
    if np.allclose(d, 0):
        return 0.0, 1.0
    res = sps.wilcoxon(d, zero_method="wilcox", alternative="two-sided")
    return float(res.statistic), float(res.pvalue)


def hodges_lehmann(a, b=None) -> float:
    """Hodges–Lehmann estimator: median of Walsh averages of paired diffs.

    The location shift that pairs with the signed-rank test. Unlike a mean
    difference it is not dragged by a single retry-tail outlier.
    """
    d = np.asarray(a, float) - (0 if b is None else np.asarray(b, float))
    if d.size == 0:
        raise ValueError("empty sample")
    i, j = np.triu_indices(d.size, k=0)         # k=0 includes (i,i): Walsh averages
    return float(np.median((d[i] + d[j]) / 2))


def mann_whitney_u(a, b, alternative: str = "two-sided") -> tuple[float, float]:
    """Mann–Whitney U for two independent samples (the cold-start check)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if a.size == 0 or b.size == 0:
        raise ValueError("both samples must be non-empty")
    res = sps.mannwhitneyu(a, b, alternative=alternative)
    return float(res.statistic), float(res.pvalue)


# ---------------------------------------------------------------------------
# quantiles
# ---------------------------------------------------------------------------


def quantile(x, q: float) -> float:
    """Type-7 (numpy default) empirical quantile — stated so it is reproducible.

    Quantile estimators differ; naming ours means a reader can reproduce the
    number to the digit rather than to within an interpolation convention.
    """
    x = np.asarray(x, float)
    if x.size == 0:
        raise ValueError("empty sample")
    if not 0 <= q <= 1:
        raise ValueError(f"q must be in [0, 1], got {q}")
    return float(np.quantile(x, q, method="linear"))


def quantile_ci(x, q: float, level: float = 0.95) -> CI:
    """Distribution-free CI for a quantile from order statistics.

    The number of observations below the true q-quantile is Binomial(n, q), so
    the interval is ``[x_(k_lo), x_(k_hi)]`` with k from the binomial quantiles.
    No distributional assumption — which is the point, for latency.

    Reports how many observations the estimate rests on. A p99 needs n ≥ 100 to
    exist at all, and at n = 100 its upper bound IS the sample maximum: the
    interval is truncated, and the ``method`` string says so rather than letting
    a reader mistake it for a two-sided bound.
    """
    x = np.sort(np.asarray(x, float))
    n = x.size
    if n == 0:
        raise ValueError("empty sample")
    if not 0 < q < 1:
        raise ValueError(f"q must be in (0, 1), got {q}")
    alpha = 1 - level
    k_lo = int(sps.binom.ppf(alpha / 2, n, q))
    k_hi = int(sps.binom.ppf(1 - alpha / 2, n, q)) + 1
    lo_i = max(0, min(k_lo - 1, n - 1))
    hi_i = max(0, min(k_hi - 1, n - 1))
    truncated = (k_hi - 1) >= n
    method = "order-statistic" + (" (upper bound truncated at sample max)"
                                  if truncated else "")
    return CI(quantile(x, q), float(x[lo_i]), float(x[hi_i]), n, method, level)


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def bootstrap_ci(x, statistic=np.median, b: int = 10_000, level: float = 0.95,
                 seed: int = 20260809) -> CI:
    """Percentile bootstrap CI. `seed` is explicit so every figure is reproducible."""
    x = np.asarray(x, float)
    if x.size == 0:
        raise ValueError("empty sample")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(b, x.size))
    reps = np.apply_along_axis(statistic, 1, x[idx])
    alpha = 1 - level
    return CI(float(statistic(x)),
              float(np.quantile(reps, alpha / 2)),
              float(np.quantile(reps, 1 - alpha / 2)),
              x.size, f"bootstrap-percentile(B={b},seed={seed})", level)


def paired_bootstrap_diff_ci(a, b_arm, statistic=np.median, b: int = 10_000,
                             level: float = 0.95, seed: int = 20260809) -> CI:
    """Paired bootstrap CI for statistic(a) - statistic(b_arm).

    Resamples PAIR INDICES, not the two arms independently. Independent
    resampling would destroy the within-pair correlation the paired design was
    built to exploit and inflate the interval toward the unpaired width —
    silently discarding the ~3.3x efficiency gain at rho = 0.7.
    """
    a = np.asarray(a, float)
    c = np.asarray(b_arm, float)
    if a.size != c.size:
        raise ValueError(f"paired arms must have equal length, got {a.size} and {c.size}")
    if a.size == 0:
        raise ValueError("empty sample")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(b, a.size))
    reps = np.array([statistic(a[i]) - statistic(c[i]) for i in idx])
    alpha = 1 - level
    return CI(float(statistic(a) - statistic(c)),
              float(np.quantile(reps, alpha / 2)),
              float(np.quantile(reps, 1 - alpha / 2)),
              a.size, f"paired-bootstrap(B={b},seed={seed})", level)


# ---------------------------------------------------------------------------
# multiplicity
# ---------------------------------------------------------------------------


def benjamini_hochberg(pvals, q: float = 0.05) -> tuple[list[bool], list[float]]:
    """BH step-up FDR control. Returns (reject flags, adjusted p), input order.

    Adjusted p-values are made monotone by the standard cumulative-minimum pass
    from the largest p down; without it an adjusted value can exceed a larger
    raw p's adjustment, which is incoherent to report.
    """
    p = np.asarray(pvals, float)
    if p.size == 0:
        return [], []
    if np.any((p < 0) | (p > 1)):
        raise ValueError("p-values must lie in [0, 1]")
    n = p.size
    order = np.argsort(p)
    ranked = p[order]
    adj = ranked * n / np.arange(1, n + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.clip(adj, 0, 1)
    out_adj = np.empty(n)
    out_adj[order] = adj
    return list(out_adj <= q), [float(v) for v in out_adj]


def bonferroni(pvals, alpha: float = 0.05) -> tuple[list[bool], list[float]]:
    """Bonferroni FWER control — used only for the confirmatory safety family."""
    p = np.asarray(pvals, float)
    if p.size == 0:
        return [], []
    if np.any((p < 0) | (p > 1)):
        raise ValueError("p-values must lie in [0, 1]")
    adj = np.clip(p * p.size, 0, 1)
    return list(adj <= alpha), [float(v) for v in adj]


# ---------------------------------------------------------------------------
# agreement
# ---------------------------------------------------------------------------


def cohens_kappa(a, b) -> float:
    """Cohen's kappa between two label sequences (the corpus labelling gate).

    kappa = (p_o - p_e) / (1 - p_e). Perfect agreement on a single label gives
    p_e = 1, where kappa is undefined (0/0); returns 1.0 in that case, because
    two raters who agreed on every item did agree — and the labelling protocol,
    not this function, is where degenerate single-class corpora get caught.
    """
    a = list(a)
    b = list(b)
    if len(a) != len(b):
        raise ValueError(f"label sequences must be equal length, got {len(a)} and {len(b)}")
    if not a:
        raise ValueError("empty label sequence")
    n = len(a)
    labels = sorted(set(a) | set(b))
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    if math.isclose(pe, 1.0):
        return 1.0
    return (po - pe) / (1 - pe)


# ---------------------------------------------------------------------------
# determinism / variance attribution
# ---------------------------------------------------------------------------


def variance_decomposition(scores, decisions) -> dict:
    """Law of total variance for a binary decision D conditioned on score S.

        Var(D) = E_S[Var(D|S)] + Var_S[E(D|S)]
                 \\_____________/   \\____________/
                  within-stratum     between-stratum

    The first term is **identically zero** if the decision is a deterministic
    function of the score — which is exactly what the document's "guardrails are
    non-deterministic, policies are deterministic" pair asserts. So the split is
    the measurement of that claim, not a description of it: any non-zero
    within-stratum variance is a mixed stratum, i.e. two identical scores that
    produced different decisions.

    `impure_strata` lists them. One is enough to falsify (probability 0 under
    H₀), which is why no p-value is attached.
    """
    s = np.asarray(scores, float)
    d = np.asarray(decisions, float)
    if s.size != d.size:
        raise ValueError(f"scores and decisions must align, got {s.size} and {d.size}")
    if s.size == 0:
        raise ValueError("empty sample")
    if not np.all(np.isin(d, (0.0, 1.0))):
        raise ValueError("decisions must be binary 0/1")

    total = float(np.var(d))
    within = 0.0
    between = 0.0
    grand = float(np.mean(d))
    strata = {}
    impure = []
    for val in np.unique(s):
        m = s == val
        w = float(m.sum()) / s.size
        dm = d[m]
        p = float(np.mean(dm))
        v = float(np.var(dm))
        within += w * v
        between += w * (p - grand) ** 2
        strata[float(val)] = {"n": int(m.sum()), "p_deny": p, "var": v}
        if v > 0:
            impure.append(float(val))
    return {
        "n": int(s.size),
        "var_total": total,
        "var_within_stratum": within,
        "var_between_stratum": between,
        "within_fraction": (within / total) if total > 0 else 0.0,
        "strata": strata,
        "impure_strata": impure,
        "conditionally_deterministic": not impure,
    }


# ---------------------------------------------------------------------------
# detection efficacy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Confusion:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn


def confusion(y_true, y_pred) -> Confusion:
    """Build a confusion matrix from boolean-coercible label sequences."""
    yt = [bool(v) for v in y_true]
    yp = [bool(v) for v in y_pred]
    if len(yt) != len(yp):
        raise ValueError(f"label sequences must align, got {len(yt)} and {len(yp)}")
    if not yt:
        raise ValueError("empty sample")
    tp = sum(1 for t, p in zip(yt, yp) if t and p)
    fp = sum(1 for t, p in zip(yt, yp) if not t and p)
    fn = sum(1 for t, p in zip(yt, yp) if t and not p)
    tn = sum(1 for t, p in zip(yt, yp) if not t and not p)
    return Confusion(tp, fp, fn, tn)


def f_beta(precision: float, recall: float, beta: float = 2.0) -> float:
    """F_beta = (1+B²)PR / (B²P + R). beta=2 weights recall 2x — pre-registered
    as primary, because a missed attack costs more than a blocked benign request.
    """
    if beta <= 0:
        raise ValueError(f"beta must be positive, got {beta}")
    b2 = beta * beta
    denom = b2 * precision + recall
    return 0.0 if denom == 0 else (1 + b2) * precision * recall / denom


def youden_j(tpr: float, fpr: float) -> float:
    """Youden's J = TPR - FPR. Prevalence-independent, so it is the threshold
    selector: our corpus prevalence is artificial and cannot inform a
    prevalence-sensitive criterion.
    """
    return tpr - fpr


def ppv_at_prevalence(tpr: float, fpr: float, prevalence: float) -> float:
    """Bayes re-expression: PPV(pi) = TPR·pi / (TPR·pi + FPR·(1-pi)).

    Turns "recall 0.85, FPR 0.04" into an operational statement. At a realistic
    attack prevalence of 0.1% those numbers give a PPV near 2%: 50 false alarms
    per true detection. This is the analysis §7.1 omits, and the reason the
    corpus PPV must never be reported as if it were operational.
    """
    if not 0 <= prevalence <= 1:
        raise ValueError(f"prevalence must be in [0, 1], got {prevalence}")
    num = tpr * prevalence
    den = num + fpr * (1 - prevalence)
    return 0.0 if den == 0 else num / den


def operating_point(c: Confusion, level: float = 0.95) -> dict:
    """One ROC vertex with Wilson intervals on both rates.

    With a 6-value score lattice and a `greaterThan(decimal(t))` comparison there
    are at most 7 distinct operating points, so the "curve" is a 7-vertex
    polyline. Reporting it as a curve would imply interpolation the mechanism
    cannot deliver.
    """
    pos = c.tp + c.fn
    neg = c.fp + c.tn
    tpr = wilson_ci(c.tp, pos, level) if pos else None
    fpr = wilson_ci(c.fp, neg, level) if neg else None
    prec = wilson_ci(c.tp, c.tp + c.fp, level) if (c.tp + c.fp) else None
    t = tpr.point if tpr else 0.0
    f = fpr.point if fpr else 0.0
    p = prec.point if prec else 0.0
    return {
        "confusion": {"tp": c.tp, "fp": c.fp, "fn": c.fn, "tn": c.tn},
        "n": c.n,
        "tpr": tpr, "fpr": fpr, "precision": prec,
        "recall_point": t,
        "youden_j": youden_j(t, f),
        "f2": f_beta(p, t, beta=2.0),
        "f1": f_beta(p, t, beta=1.0),
        "ppv_at": {pi: ppv_at_prevalence(t, f, pi) for pi in (0.001, 0.01, 0.1)},
    }
