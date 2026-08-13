# FINDING F9-2 — The mismatch metrics do fire when a policy cannot evaluate. The document's detector works; what it detects is a *disagreement between two policies*, not a broken policy

**Status:** **CONFIRMS_DOCUMENT** — the sealed oracle's verdict is **TRUE**. The amendments this
touches are already carried elsewhere (§6, and `V13-11` / `V13-13`); nothing new is proposed here.
**Sealed-oracle verdict:** `results/phase1/F9-2.json` — **TRUE** (EXISTENCE), `n_usable: 200`
**Oracle (verbatim, from `claims/triage_rules.py`):** *"MismatchErrors/PolicyMismatch fire on
unevaluable policies"* — *"TRUE if the metrics increment when a policy cannot evaluate; FALSE if
silent"*. Registered instrument note: *"paired with F5-4a"*. `planned_n: None`, mutation arm not
mandatory (one was written anyway — see §7).
**Script:** `f9_failsecure/00_mismatch_verdict.py` · offline suite
`f9_failsecure/tests/test_mismatch_verdict.py` (31 arms) · mutation harness
`f9_failsecure/tests/test_mismatch_verdict_mutation.py` (12 mutants, 12 killed)
**Dates:** the observations are F5-4a's, on **2026-08-11** and **2026-08-12** (UTC). This analysis
was written on 2026-08-13 and made **no observation of its own**.
**Run id:** `r20260810T130945Z` (F5-4a's, adopted — not minted)
**Raw evidence:** `evidence/r20260810T130945Z/f5/F5-4a/` and
`evidence/r20260810T130945Z/f5/F5-4a-logonly-read/` — **308 `get_metric_statistics` call records**
read here (134 + 174), plus the 200 `mcp:tools/call`, 8 `create_policy` and 8 `delete_policy`
records that establish the exercise basis. Counted on disk by the script, not read out of any
summary.
**Cost: $0.00.** Zero AWS calls, zero mutations, zero resources touched. The record carries
`aws_calls: 0`, `billable_calls: 0`, `mutations: 0`, `analysis_only: true`.
**Pre-registration seal in force:** `a2136a9d3dbb…fa74cf1a`
**Document under test:** §6.2 line 661 (the mismatch-metric row) and §6.4 line 730, reached
through claim `C-s6-4-trow-006`; the §6.4 alarm row's premise is that these metrics fire.
**Class:** O (observability). Family `descriptive_no_test` — an existence observation, no p-value.

<!-- provenance
{
  "status": "CONFIRMS_DOCUMENT",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F5-4a", "F5-4a-logonly-read"],
  "replication": "Not owed, and the reason is directional. The verdict rests on PRESENCE — two disjoint firings of both named metrics, at 2026-08-11T22:47:00Z and 2026-08-12T00:02:00Z, each over a measured zero. A day on which a publishing pipeline was degraded could hide a datapoint; it cannot manufacture one, so the hazard that forces a second calendar day on an absence claim does not apply to this direction. The sub-result that IS an absence claim (`LogOnlyEvalIncomplete`, §5) is not scored here and is discharged in FINDING-F5-4A.md §8 across two days plus F7-1's independent namespace inventory.",
  "cases_note": "F9-2's own case id is deliberately absent from `cases`. This case made no AWS call, so it has no call records and no observation day of its own; the days that count are the days F5-4a's records were written. Declaring F9-2 here would make the gate count an analysis artifact as an observation.",
  "amends": []
}
-->

## 1. What was asked, and why it needed no new AWS call

The sealed oracle asks whether the mismatch metrics increment when a policy cannot evaluate. F5-4a
had already created that condition — four deliberately broken policies, 200 `mcp:tools/call`
requests against them across two UTC days — and had polled CloudWatch throughout. **The
measurement already existed in the archive.** What did not exist was a verdict derived from it
under this oracle, which is a different question from F5-4a's (*"records DENY or ALLOW and whether
MismatchErrors/PolicyMismatch fire"* — `RECORDED`, deliberately no pass/fail).

So `f9_failsecure/00_mismatch_verdict.py` is an analysis, and it recomputes every figure from the
per-call records — `params.MetricName`, `params.StartTime`, `params.EndTime`,
`response.Datapoints[].Timestamp/Sum/SampleCount` — rather than reading `mismatch_metrics` out of
`results/phase1/F5-4a.json`. Reading that block would be this record vouching for a number
computed by the artifact it is derived from. The two agree, which is worth stating precisely
because agreement was not assumed.

## 2. The verdict

**TRUE.** Both metrics the oracle names fired, twice each, and each firing sits over reads that
returned zero for the same metric in the interval immediately before it.

| metric | role | reads | episodes | 2026-08-11T22:47:00Z | 2026-08-12T00:02:00Z | baseline reads (ep1 / ep2) |
|---|---|---|---|---|---|---|
| `MismatchErrors` | **oracle's conjunction** | 60 | 2 | Sum 20, SampleCount 20 | Sum 20, SampleCount 20 | 8 / 16 |
| `PolicyMismatch` | **oracle's conjunction** | 24 | 2 | Sum 20, SampleCount 20 | Sum 20, SampleCount 20 | 4 / 6 |
| `TotalMismatchedPolicies` | corroborating | 16 | 2 | Sum 20, SampleCount 47 | Sum 20, SampleCount 36 | 4 / 4 |
| `LogOnlyEvalIncomplete` | sub-result, **not scored** | 40 | 0 | — | — | — |
| `LogOnlyMatches` | context | 84 | 0 | — | — | — |
| `LogOnlyDecisionFlips` | context | 84 | 0 | — | — | — |

`TotalMismatchedPolicies` corroborates and is deliberately **not** in the conjunction: the oracle
names two metrics, and widening a sealed conjunction after seeing which metrics fired is choosing
a result rather than measuring one. Its `SampleCount` of 47 and 36 against a `Sum` of 20 is worth
one line on its own — the metric publishes **zero-valued samples**, so an operator's zero from it
is a real zero from a live instrument rather than an instrument that is not there. That is the
distinction `f5_redteam/04b_logonly_flip_read.py` draws as `PUBLISHED_AND_ZERO` vs
`NEVER_PUBLISHED`, arriving here from a different direction.

## 3. What an "episode" is, and why it is not the window the script asked for

Nothing in a call record says *"this is the before window"*. A reader who sorts reads by
`StartTime` and calls the first one "before" is labelling, not measuring, and would mislabel a
re-read of an old window as a new baseline.

So an **episode** is a cluster of datapoints that actually carry a positive `Sum`, keyed by the
minute CloudWatch stamped them with, and a read counts as that episode's **baseline** only if
(a) its window closes at or before the firing, (b) its window opens after the *previous* firing,
and (c) it returned no positive datapoint. All three come from recorded fields, so a mislabelled
window cannot promote itself. Both of the following were caught by the script's own refusals while
it was being written, and both are now pinned by tests that fail without the fix:

* **The two clocks.** The request windows were sent as `+00:00`; CloudWatch stamped the datapoints
  it returned `+07:00`. `'2026-08-11T22:48:36+00:00' <= '2026-08-12T05:47:00+07:00'` is
  lexicographically true while the instants are the other way round, so a first version comparing
  ISO strings offered **twelve** reads that closed **96 seconds after** the firing as that
  firing's baseline. Every comparison is now between instants, and a timestamp with no offset is
  refused rather than assumed to be UTC — assuming UTC is the assumption that produced the bug.
* **The interval, not just the direction.** Written as "any window that closed before this
  firing", every day-1 read is a candidate baseline for day 2 — and day 1 fired, so those reads
  are positive and the contamination guard rejected a second episode that was perfectly clean on
  its own interval. An earlier firing is not contamination of a later one; a firing inside the
  later one's baseline is.

`seen_in_reads` is the third derived figure and it lands on a number F5-4a reported independently:
the 22:47Z `MismatchErrors` firing was returned by **6** reads, `TotalMismatchedPolicies` by **4**,
`PolicyMismatch` by **2** — one read per dimension combination. 6 × 20 = 120, 4 × 20 = 80,
2 × 20 = 40, which is exactly FINDING-F5-4A.md §3's table. Two computations that could disagree,
from opposite ends (a maximum per firing here, a sum across combinations there), and they do not.
That arithmetic is the substance of `V13-13`: **an operator summing a mismatch metric across
dimensions on a dashboard reads six times the request count.**

## 4. What this verdict does NOT say

The oracle's TRUE is narrow, and the record says so in `what_this_does_not_prove` rather than
leaving a reader to take the stronger reading:

1. **It is a twin disagreement that fires, not a broken policy.** F5-4a's 20 mismatches per
   episode come from a pair: the ACTIVE twin denied all 20 while the byte-identical statement in
   LOG_ONLY allowed all 20 (`results/phase1/F5-4a_logonly_read.json`: `active_twin_denied_all`,
   `logonly_allowed_all`, `same_statement`). What is measured is that the mismatch family fires
   **when one twin cannot evaluate**. It is *not* measured that a lone unevaluable policy with no
   disagreeing twin increments anything.

   **And the firing names only the ACTIVE side.** This was read per dimension rather than assumed,
   because the direction matters: for `MismatchErrors`, which is the only one of the three whose
   reads carry `PolicyEnforcementMode` at all,

   | reads pinned to | n reads | returned the firing |
   |---|---|---|
   | `PolicyEnforcementMode=ACTIVE` | 40 | **12** |
   | `PolicyEnforcementMode=LOG_ONLY` | 20 | **0** |
   | `Policy=` the LOG_ONLY twin's own policy id | 8 | **0** |

   The LOG_ONLY direction is therefore **exercised and silent**, not unmeasured — the reads were
   made, against the twin that held the byte-identical statement and was half of the disagreement
   being counted, and they came back empty. Every positive datapoint carried
   `Policy=grx_f54a_misss_…` (the ACTIVE twin, one id per day) and `PolicyEnforcementMode=ACTIVE`.
   For `PolicyMismatch` and `TotalMismatchedPolicies` the mode dimension was **never queried**, so
   for those two this says nothing either way — their silence in that direction would be our
   omission, and is not claimed here.

   The consequence is §4.4 route #5's own remedy: *alarm on the `Mode`/`PolicyEnforcementMode`
   dimensions*. Two of the three metrics cannot be filtered by mode at all, and the third returns
   nothing when it is. So the detector confirmed here answers *"two policies disagree"*, attributed
   to the ACTIVE policy. An operator who reads it as *"a policy of mine cannot evaluate"* is right
   only while an ACTIVE policy is on the other side of the comparison — which is precisely what
   §7.1's LOG_ONLY-first rollout does not have. That consequence is registered under F5-4a as
   `V13-12` (route #5's dimension advice) and `V13-13` (the row's consequence by mode), both of
   which now cite this recount; it is restated here because a TRUE published without it would be
   read as a broader endorsement than it is.
2. **Nothing about the mechanism inside the evaluator.** These are CloudWatch reads of windows
   that have closed.
3. **Nothing about magnitude as a request count.** The episode figure is 20 per dimension
   combination, which is F5-4a's `n_per_arm`; see §3.

## 5. The sub-result that is reported and never scored

`LogOnlyEvalIncomplete` — the metric §6.2, §6.4 and the §8 checklist all make the detector for a
partial LOG_ONLY calibration — returned **0 positive datapoints in all 40 reads**, across the
exact windows in which a LOG_ONLY policy that could not evaluate served 20 requests. F7-1
independently recorded `name_in_namespace_inventory: false`.

It is kept out of this verdict on purpose. It is a different claim (`C-s6-4-trow-006`'s other
half) with a different oracle, F7-1 had already swept it with the full instrument and
**deliberately declined to score it** (`exercise_basis: NOT_EXERCISED`, on the stated grounds that
reproducing the condition would need a deliberately broken policy — which F5-4a then shipped), and
folding an absence into a conjunction about presence would let one direction's evidence stand in
for the other's. The amendment it supports is `V13-11`, and it is discharged there across two
calendar days.

## 6. Why this is `CONFIRMS_DOCUMENT` and proposes no amendment of its own

§6.4's alarm row rests on the premise that these metrics fire. They do, in the condition the row
is named for, twice, over measured zeros. That premise is confirmed — and a register that only
collects refutations reads as an indictment rather than a review, so the confirmation is published
with the same machinery as a refutation.

The two caveats a reader needs (§3's dimension multiplication and §4's twin-disagreement scope) are
already registered as `V13-13` and `V13-12` under FINDING-F5-4A.md, which measured them. Filing
them again here would claim the same document sites twice. What this case contributed was folded
into those two entries rather than raised as new ones: §4's mode-filtered recount now appears in
`V13-12`'s `observed` and its `proposed` correction to route #5, §3's 6/4/2 re-read count in
`V13-13`'s `evidence` as an independent derivation of the same multiplier, and §5's 40-read
recount in `V13-11`'s `evidence`. `F9-2` is named in all three `planned_cases`, which is also what
the triage requires — `C-s6-4-trow-006` maps to `("F9-2","F7-1")`.

## 7. Tests, and the mutation run that found a real gap

`f9_failsecure/tests/test_mismatch_verdict.py` — **31 arms**, offline, no AWS, no write into
`results/`. They cover the two timestamp regressions above, the disjointness of the two episodes,
the refusals (no `mcp:tools/call` → refuse rather than publish FALSE; no `create_policy` → refuse;
a named metric never read → refuse; an unclassified metric name → fatal), and the asymmetry that
matters most: **read, exercised and silent is the oracle's FALSE, not an error.**

`f9_failsecure/tests/test_mismatch_verdict_mutation.py` — **12 mutants, 12 killed**, each applied
to a copy outside the tree with the live script's sha256 re-checked at the end of the run. It
earned its place immediately: `M12-sum-accumulates-across-reads` — adding the Sums of two reads of
one firing instead of taking the maximum — showed that **no arm asserted an episode's magnitude at
all**, so a verdict reporting 40 mismatches from 20 requests would have passed. Measured, not
argued: with the two `== 20.0` assertions removed and M12 in place, the arms file reports 29
passed, 2 skipped, **0 failed**. The assertions exist because of the mutant.

The mutation arm is **not** mandatory for this case under the seal (`mutation_is_mandatory:
False`). It was written because a green suite over a TRUE is the weakest evidence in the project:
every guard could be a no-op and the output would look identical.

## 8. Cross-references

* `results/phase1/F9-2.json` — the sealed-oracle record (TRUE, EXISTENCE, `n_usable: 200`).
* `FINDING-F5-4A.md` — the paired case: the experiment, the two failure mechanisms, the dimension
  arithmetic (§3), the LOG_ONLY read (§4), and the two-day replication (§8).
* `results/phase1/F5-4a.json`, `results/phase1/F5-4a_logonly_read.json` — the recorded verdict and
  the supplementary read this analysis deliberately does *not* read its numbers from.
* `F7-1` — the namespace inventory that recorded `LogOnlyEvalIncomplete` as absent and
  NOT_EXERCISED, and whose exclusion F5-4a's broken policy discharged.
* `V13-11`, `V13-12`, `V13-13` — the three amendment candidates this finding's caveats belong to.
* `F9-3` — the remaining fail-secure question in this family, and a different shape: whether a
  throttled `ApplyGuardrail` request is denied or passes unevaluated. Not answerable from any
  archive; it needs a bounded burst past the 100 rps quota.
