# FINDING P0-STATS — Analysis layer verified; one pre-registered sample size was off by one

**Status:** RESOLVED (offline, deterministic, $0)
**Date:** 2026-08-09
**Artifacts:** `lib/stats.py`, `lib/tests/test_stats.py` (106 tests),
`lib/tests/test_stats_mutation.py` (22 mutants), `lib/tests/conftest.py`
**Class:** platform (not a claim about the document under test)

<!-- provenance
{
  "status": "INTERNAL",
  "evidence_runs": [],
  "note": "A property of our own analysis layer, established by 106 tests and 22 mutants against textbook values. Nothing here is a claim about AWS, so there is no external state whose durability replication would test."
}
-->

## Why this is a finding and not just "tests pass"

`lib/stats.py` is the layer that converts evidence into the numbers that will go
into v1.3. If it is wrong, every downstream claim inherits the error while looking
fully rigorous. So it is validated the same way the AWS controls are: an oracle of
published reference values, plus a mutation run proving the assertions are
load-bearing.

## Result

| Gate | Outcome |
|:---|:---|
| Reference-value tests | **106 passed** |
| Mutation score | **22/22 killed (100%)** |
| Mutation control arm | 19/19 detectors pass on unmutated source |
| Offline enforcement | verified — `boto3.get_caller_identity()` raises before any socket |

Every kill is attributed to the specific assertion that fired, so "killed" is
auditable rather than asserted. The control arm exists because a detector that
raised unconditionally would "kill" all 22 mutants and make the score meaningless.

## What the verification actually caught

**1. A real bug in `wilson_ci` (fixed).** At x=0 the centre and half-width are
analytically equal, but in floating point the subtraction leaves 5.55e-17, so the
interval violated `lo <= point` and printed as `0.0000 [0.0000, 0.5615]` while
carrying a positive lower bound. Symmetric issue at x=n. Both boundary cases are
now clamped to their exact analytic values. Only reachable at exactly the
zero-count cells — which is precisely where every safety claim in this project
lives.

**2. `required_n_for_zero_events(0.01, 0.95) = 299`, not 298.** The plan's Part 2
states *"59 for 5% at 95% power; 298 for 1%"*. `ln(0.05)/ln(0.99) = 298.073`, so
the ceiling is **299**; at n=298 power is 0.94996 — short of 95%. Verified against
the power function directly, not just the closed form.

> **Consequence:** the pre-registered **n = 300 per determinism cell is unaffected**
> (300 ≥ 299), so no experimental design changes. But `PREREGISTRATION.yaml` must
> carry 299 as the derived requirement, not 298, or `verify_prereg.py` will pin a
> number that its own power function contradicts.

**3. Four reference values in my first draft of the test suite were wrong**, and
each was replaced with an independently computed oracle rather than a remembered
figure:

| Test | Wrong value | Correct | Fix |
|:---|:---|:---|:---|
| McNemar b=132, c=107 | p = 0.1150 | **p = 0.12056** | pinned both the Yates-corrected and uncorrected statistics, plus a chi-square(1) ↔ squared-normal cross-check |
| Wilcoxon 10-pair example | p ∈ (0.15, 0.35) | **p = 324/512 = 0.6328125** | test now enumerates all 2⁹ sign assignments itself, so it no longer depends on the same scipy call it is testing |
| BH worked example | an 8-value list, "rejects 4" | replaced with the **BH (1995) 15-value table**, which rejects exactly 4 | added a second case where a naive elementwise rule would reject only 1 of 3, so the step-up logic is actually exercised |
| rule of three ≈ 3/n | uniform 2% tolerance | error is **O(1/n)**: 2.6% at n=60 → 0.29% at n=1000 | asserts the per-n rate *and* that the error shrinks monotonically |

The plan's rule-of-three table is confirmed correct as written (4.87% / 2.95% /
0.995% at n = 60/100/300) — it quotes exact values, not the 3/n approximation.

## Mutations that matter most

Three of the 22 impersonate errors that would have produced publishable-looking
but wrong results:

- **M3** — `wilson_ci` returning `[0, 1]` unconditionally. This passes every
  "interval is inside [0,1]" and "interval contains the truth" check ever written.
  Killed only because the suite pins Newcombe's published digits.
- **M22** — `paired_bootstrap_diff_ci` resampling the two arms independently.
  Silently discards the ~3.3× efficiency the paired latency design is built on
  while still returning a plausible interval. Killed by asserting the paired
  interval is less than half the width of the independent-resample interval on
  correlated data.
- **M18** — the F2-3 falsification criterion disabled (`if v > 1.0` instead of
  `v > 0`). A mixed stratum would have been reported as *conditional determinism
  confirmed* — i.e. the mutation makes the platform agree with the document
  regardless of the evidence.

## Design decisions recorded in the module

- Wilson for all proportions, never Wald; Clopper–Pearson for zero/full cells,
  where the exact bound closes to the rule of three (tested as an identity linking
  two independently implemented functions).
- Distribution-free order-statistic CIs for latency quantiles, with the truncation
  at n=100 for a p99 disclosed in the `method` string rather than left for the
  reader to infer.
- Hodges–Lehmann rather than a mean difference: tested against a 30-second retry
  tail that moves the mean by >1000 and HL by nothing.
- **No decision rule lives in `stats.py`.** It returns intervals and p-values; the
  thresholds live in `PREREGISTRATION.yaml`. If a threshold could be edited here
  after seeing data, the pre-registration would be decorative.

## Phase 0 gate status

`stats fixtures match textbook values` — **green**, with the mutation run as
supporting evidence. Remaining Phase 0 items: `claims/triage.csv` +
`check_coverage.py`, `EXCLUSION_REGISTER.md`, `PREREGISTRATION.yaml` (carrying
n=299 per above), corpora + κ ≥ 0.80, F5-7a PrivateLink enumeration.
