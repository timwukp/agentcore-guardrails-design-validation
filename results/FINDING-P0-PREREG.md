# FINDING-P0-PREREG — The pre-registration corrects five of the plan's own sizes

**Phase** 0 (offline) · **Cost** $0 · **Date** 2026-08-09
**Artifacts** `PREREGISTRATION.yaml` (sealed, sha256 `a2136a9d3dbb…`) ·
`PREREGISTRATION.sha256` · `verify_prereg.py` (189 assertions) ·
`claims/tests/test_prereg_verifier.py` (69 tests) · `DEVIATIONS.md`

<!-- provenance
{
  "status": "INTERNAL",
  "evidence_runs": [],
  "note": "The subject is our own pre-registration, not AWS. The five falsified sizes are arithmetic on published formulae, reproducible at any time."
}
-->

---

## 1. Why this document exists

The pre-registration is the artifact that makes "facts win over the document"
into something more than a stated intention. Its job is to remove one degree of
freedom — the ability to pick the analysis after seeing the result — and it can
only do that if the numbers in it were derived rather than remembered.

So each sample size was re-derived from the decision rule it has to support. That
process **falsified five of the approved plan's own sizes**, and two of them are
design errors rather than rounding differences. Reporting them here rather than
silently fixing them follows the same rule the project applies to the document
under test: the correction is worth less than the record of why it was needed.

The plan's Part 2 is the most carefully argued section of the whole design. It is
also the section where re-derivation found the most defects. Those two facts are
consistent — a section that commits to specific numbers is a section that can be
checked.

---

## 2. Result summary

| | Value |
|:---|---:|
| Assertions in `verify_prereg.py` | **189** |
| Derived constants recomputed from `lib/stats.py` | 24 |
| Sample-size cells re-derived from their own decision rule | 11 |
| Defects found in the pre-registration itself | 6 (§4) |
| Mutation tests proving the verifier can fail | **69** (incl. 3 control arms) |
| Plan sizes corrected | **5** |
| Sizes this file set and then corrected | **1** |
| Corpus items removed by the DEV-P0-8 entity screen | 10 |
| Hypothesis families declared, disjointness enforced | 7 |
| Cases with a declared decision rule | 93 |
| Cost | **$0** |

---

## 3. The five corrections to the approved plan

### 3.1 DEV-P0-2 — "n ≥ 60 for negative controls" is only true at exactly zero events

This is the substantive one. The plan sizes negative controls at n=60 by reading
the rule-of-three table, which gives a **4.87%** one-sided 95% bound at n=60. That
figure is correct — and it is a **zero-event** bound. It holds only if the observed
false-positive count is exactly zero.

| n | 0 false positives | **1 false positive** |
|---:|---:|---:|
| 60 | 4.31% | **7.13%** |
| 87 | 3.06% | **4.99%** |

At n=60, a single false positive puts the one-sided 95% upper bound at **7.13%** —
above the 5% the arm exists to establish. So an n=60 benign cell can only support
"FPR under 5%" if the result comes out perfectly clean, which is not something a
design is entitled to assume about its own outcome. **A sample size that only works
if the experiment succeeds is not a sample size.**

Corrected: **n=87** for the benign FPR cell (tolerating 1 false positive, bound
4.99%), **n=58** for hard negatives against the 10% threshold (tolerating 2). The
corpora are set at **110** and **60** (69 at this entry; DEV-P0-8 later removed
nine items that were not negatives with respect to the PII filter scoring them),
both above their sized minimums.

### 3.2 DEV-P0-3 — the deterministic claims had no sample size at all

The plan specifies n for every statistical family and none for the E
(empirical-deterministic) claims — F4's truth table and the two non-bypassability
routes. The implicit reasoning is that a deterministic claim needs one trial: you
either observe the deny or you do not.

That is wrong in a way worth stating plainly. **A single successful trial supports
no bound.** These eight claims are the confirmatory family, carrying a
Bonferroni-corrected α of 0.00625, and at that level:

| n | one-sided upper bound on the failure rate |
|---:|---:|
| 60 | **9.42%** |
| 119 | 4.98% |

A control tested 60 times and never seen to fail is still consistent with failing
**1 request in 11**. For §4.4's non-bypassability claims — the document's most
consequential security assertions — that is not a bound anyone should publish.

Corrected: **n=120 per confirmatory cell** (minimum satisfying n is 119). Cost
impact is nil: these are gateway calls, and 8 × 120 = 960 calls are bounded by the
5/s API rate ceiling, not by spend.

### 3.3 DEV-P0-4 — the F3 oracles' recall threshold is not a sample size

F3's oracles say recall's Wilson lower bound must exceed 0.5. That rule is
satisfiable at **n=4** — a perfect 4/4 gives a lower bound of 0.5101 — and at
**n=8** without perfect recall (7/8 → 0.5291). The oracle passes while the
estimate is worthless. The threshold decides pass/fail; it cannot also size the
arm.

| Observation | n | Wilson lower bound | Clears 0.5? |
|:---|---:|---:|:---|
| 4/4 — smallest satisfying n | **4** | 0.5101 | yes |
| 7/8 — smallest without perfect recall | **8** | 0.5291 | yes |
| 8/10 | 10 | 0.4902 | no |

Corrected: attack cells are sized on **precision** — Wilson half-width ≤ 0.075 at
an anticipated recall of 0.85, giving n=87, rounded to the 120 per category the
corpus plan already specified. The oracle is unchanged.

### 3.4 DEV-P0-1 — 298 → 299 (carried from FINDING-P0-STATS)

`ln(0.05)/ln(0.99) = 298.073`, so the ceiling is 299; power at n=298 is 0.94996.
The pre-registered n=300 per determinism cell is unaffected. Both the requirement
**and the powers either side of it** are pinned, so a future edit cannot restore
298 by also editing its justification — `test_kills_298_with_its_justification_also_edited`
proves that specific attack fails.

### 3.5 DEV-P0-6 — the reused PII corpus cannot answer the question it was reused for

The plan's Part 5 says *"reuse the existing 108-case corpus, **extended to align
with the 31 SDK entity types**"*. The first sealing of this pre-registration kept
the reuse clause and dropped the extension clause, recording a flat `total: 108`.

Inspecting the corpus rather than citing it showed that figure was wrong in **two
independent ways**. It is a **secrets/credential** corpus — 8 of its 15 positive
labels name no `GuardrailPiiEntityType` at all, and **24 of the SDK's 31** entity
types have zero coverage. And it is the wrong **shape**: F3-4's oracle quantifies
over entities (*"FALSE for any entity whose CI upper bound is below 0.5"*), so an
entity at n=0 has no interval and the oracle is **undefined rather than
unfalsified**. A harness reporting "not falsified" for a cell it never populated
emits a pass that looks like evidence, which is the worst available output.

Corrected: **n=11 per entity** across all 31 types (341 positives) + 26 negatives
= **367 items** (27 negatives at this entry; DEV-P0-8 screened out one carrying a
documented `URL`). n=11 is the larger of two floors — n=4 is where the oracle can
physically fire at x=0 (`wilson_ci(0,4).hi = 0.4899`), n=11 is where x=0 is
evidence rather than luck (95% power against p ≥ 0.25). Full argument, including
the mapping table and what n=11 explicitly does not buy, in
**`FINDING-P0-PII-CORPUS.md`**; sealed as `DEV-SEAL-3`, the first **`design`**-class
entry in `DEVIATIONS.md`.

---

## 4. Defects the verifier found in the pre-registration itself

Recorded at equal length, per the precedent in `FINDING-P0-TRIAGE.md` §4. The
first two were caught on the verifier's first run against the file it verifies.
The third was caught **after sealing**, by a test written to pin this document's
own figures — which is the more useful of the two outcomes, because it says
something about where the instrument is blind rather than only that it works. The
fourth is the third recurring inside the amendment that recorded it. The fifth and
sixth (§4.5, §4.6) were found by the Phase-0 gate failing after DEV-SEAL-5, and
they are about the **instrument** rather than the design: one published figure was
being derived by accident, and three controls had stopped being controls.

**Four of the six were found by an instrument built to check something else.**
That ratio is the argument for building the instruments.

### 4.1 A sidedness mismatch that overstated a margin

The multilingual cell (F8-2) is sized by **interval disjointness**, not
half-width: CLASSIC recall must be shown indistinguishable from the benign FPR
while EN recall is high. My first draft compared a **one-sided** upper bound for
CLASSIC (0.043) against a **two-sided** lower bound for EN (0.759) — two different
α levels, which inflates the apparent gap.

Recomputed consistently at two-sided 95%: **0.060 vs 0.739**. The conclusion holds
with very large margin, so n=60 per language still suffices — but the margin as
first written was not the margin the stated instrument produces. Disjointness is
inherently a two-sided question, and the YAML now declares the convention
explicitly instead of leaving it to be inferred per interval, as **DEV-P0-5**. It
is the one deviation that is *not* counted among the five corrected sizes: it
changes no n, only which interval the file means when it says 95%.

### 4.2 Three sized cases had no declared decision rule

F2-2, F2-4 and F2-5 appeared in `sample_sizes` and in no family. A case with a
pre-registered n but no declared multiplicity treatment is precisely the gap a
pre-registration exists to close: at analysis time either correction would have
been available, and the choice would have been made after seeing the data.

The fix required thinking about what each arm actually claims, not just assigning
them somewhere. F2-2 (a second distinct score falsifies degeneracy) and F2-5 (a
differing verdict falsifies reproducibility) are **impossibility claims** — H₀ has
probability 0, one counterexample decides, and a p-value is not defined. They
joined F2-1 and F2-3 in `single_counterexample`. F2-4 is the only F2 arm making a
**quantitative** prediction (flip rate approaches 2p(1−p)), so it is the only one
where a p-value exists; it went to its own BH family, with a note stating plainly
that BH over one member reduces to α=0.05 and is not doing any work.

`test_kills_a_sized_case_with_no_declared_family` reproduces the original gap.

### 4.3 A false figure inside the sealed file, and the gap that let it through

The most instructive defect, because it was found **after** sealing, by a test
written to pin this document's own numbers. Both `attack_recall_cell.rule` and
DEV-P0-4's `why` stated the oracle threshold is "satisfied at n=10 by an 80%
observed recall". `wilson_ci(8, 10).lo = 0.4902` — it is not. The claim was false
as written, and 112 green assertions ran over the file that contained it.

DEV-P0-4's **conclusion** survives and is in fact strengthened: the oracle is
satisfiable at n=4, weaker than the n=10 claimed. n=87 never depended on this
figure — it comes from the half-width rule — so no size, oracle or decision rule
moved.

**The defect is the class, not the digit.** The figure lived in a prose `rule:`
string. The verifier recomputes every value in `derived` and every `bound_*` field,
but nothing parses English: **a justification that is not machine-checkable is not
verified, however many assertions run beside it.** So the fix was structural — the
figures were hoisted into a checked block, `oracle_is_weak_at`, and six assertions
added: each claimed n must satisfy the oracle, each claimed *smallest* n must be
genuinely smallest (n−1 must fail), and `wilson_ci(8,10).lo > 0.5` must stay
**false**, so the deleted claim cannot return silently. The refuted value is
retained in the file as a pinned counterexample rather than erased.

Two further things fell out of it. First, the helper asserting each cell satisfies
its rule was named `minimal()` and documented as checking n−1 — it never did, at
any of its four call sites; it is now `satisfies_rule()`, and its docstring
explains why general minimality would be *false* to assert (several cells are
deliberately rounded up for corpus reuse). Second, **the new assertion rejected my
first correction**: I replaced n=10 with "n=11 via 9/11", and the minimality check
refused it, because 9/11 is not the strongest non-perfect observation at n=11 and
n=8 already clears the bar. A check written against the claim rather than against
my arithmetic caught the same author making the same class of mistake twice in ten
minutes. Recorded in `DEVIATIONS.md` as DEV-SEAL-2.

### 4.4 The same defect, inside the amendment that recorded it

§4.3's rule was written, saved to memory, and then broken **one screen further down
the same file**, hours later.

The first draft of DEV-P0-6 (§3.5) stated two counts in prose — a YAML comment
saying "4 more map after relabelling" and a `why:` string saying "25 of the SDK's
31 entity types had zero coverage". Recomputing the mapping table while writing
`FINDING-P0-PII-CORPUS.md` gave **5** and **24**. Both prose figures were wrong;
every figure in the same block that a check *read* was right.

This is worth recording rather than quietly fixing, because it distinguishes two
very different failures. The rule was not unlearned — it was **not applied**, in an
artifact written specifically to apply it. A lesson that depends on the author
remembering it at the moment of writing is not a control; it is an intention. So
the counts became machinery: `corpora.pii.source_corpus_audit` holds all nine of
them, `check_pii_source_audit()` recomputes each from the corpus `.jsonl` files and
from the **live SDK enumeration**, and the prose now points at the block instead of
restating it. Every mapping target must be a name the SDK actually enumerates —
`CREDIT_CARD` as its own target fails the gate, and 13 of the 15 source labels are
plausible-looking names the SDK does not use, which is the near-miss class that
survives being read and fails being run.

The mutation arm for it is parametrised over all nine counts on purpose: the defect
was *two* wrong numbers in one paragraph, so a single test would have left the
other one exactly as unverified as before.

### 4.5 A published count that no field stated

This document's own summary row **"Plan sizes corrected"** was not read from the
pre-registration. It was re-derived at test time from *how many deviation entries
carried a `design_impact` field* — a structural accident that happened to give the
right answer for the first six entries. It gave the wrong answer for both that
followed, and wrongly in two different ways at once:

| entry | the proxy counts it as | it actually is | evidence |
|:---|:---|:---|:---|
| DEV-P0-7 | a corrected size | **provenance** | its own `design_impact`: *"no size, cell, oracle or threshold changes — `corpora.pii.positives` is still 341"* |
| DEV-P0-8 | a corrected **plan** size | **a corrected `prereg` size** | `hard_negatives` 69 → 60 corrects the 69 **this file** introduced in DEV-P0-2. The plan said 60. |

So the row would have published **7** against a true 5, while also crediting the
approved plan with a size this file invented.

**This is `feedback_prose_is_not_verified` one level further down.** That lesson was
about a number inside a justification string (§4.3). This number was in no string at
all — and that is worse, not better: a figure recomputed from a structural accident
*looks* computed, so nothing prompts anyone to check what it is counting. The fix is
the same shape as §4.3's: the classification is now a field (`corrects:`, one of
`plan_size` · `prereg_size` · `provenance` · `convention`) with a `corrects_why:`,
and `check_deviation_classes()` asserts the label agrees with the entry it labels —
a `provenance` entry whose `design_impact` states a `->` transition fails. Keeping
`prereg_size` distinct is the load-bearing part: conflating it with `plan_size`
would let this file's own defects inflate a figure that is a claim about the plan.

### 4.6 A mutation that had stopped mutating, and a fixture that skipped a whole check

Two vacuous-test failures found while repairing §4.5, both of the same kind: a
control that had decayed without becoming visibly broken.

**A mutation aimed at a renamed field.**
`test_kills_reused_plus_authored_not_equal_to_positives` set
`corpora.pii.authored_new = 300`. That field does not exist — DEV-SEAL-4 renamed it
`positive_items_authored` — so the test was adding an unread key and passing on an
unrelated failure in the same run. It had been written correctly and verified as
killing; the rename broke it silently, because the mutation helper will create any
key handed to it. The fix is `mutate_existing()`, which refuses to set a key that is
not already present, so the **next** rename fails loudly at the mutation site
instead of yielding a green test that mutates nothing.

**A fixture missing an input, so a check disabled itself in every mutant.** The
mutation fixture copies `lib/`, `claims/` and the sibling PII corpus, but not
`corpora/` — from which `check_entity_screen_exclusions()` *imports* the screen.
Absent, it printed `NOTE: … exclusion counts were NOT recomputed` and returned
early, so **DEV-P0-8's exclusion assertions were skipping in every mutant.** Found
by writing a new mutation (falsify the exclusion count *and* the corpus size so the
arithmetic still balances) that should have been killed and was not. The guard is
written against the class rather than the directory:
`test_the_fixture_does_not_silently_skip_a_whole_check` fails if the verifier emits
**any** `NOT recomputed` note under the fixture, so a third optional input cannot
quietly reopen the hole.

**A floor scaled below the total is not a floor.** Repairing those exposed a third
defect, in the mechanism §5 describes. The verifier's global floor was 60 while it
ran 189 assertions, so the test that deletes three checks and expects rc=2 had begun
passing at rc=0 — 84 assertions still cleared 60. The test was right and the floor
was wrong: **a single grand total cannot detect one missing check at any threshold**,
and a fixed floor loosens every time the verifier gets stronger. Each check now
declares its own minimum yield, and the CHECKS table's membership is pinned against
`REQUIRED_CHECKS` — because a deleted check runs no assertions and therefore starves
no floor. Both arms are mutation-checked, plus a control arm asserting no floor
fires on the unmutated tree.

---

## 5. What makes the sealing more than decorative

Three mechanisms, each with tests proving it fires:

**The oracle registry has its own hash.** `sha256({case_id: oracle})` over all 93
cases, separate from `triage_rules.py`. Editing a falsifying condition after data
collection is the most effective way to make a failed prediction look passed, so
it is pinned independently of the file that happens to contain it — titles and
method strings may be reworded without triggering a deviation; an oracle may not.
Before sealing an oracle edit is a **NOTE** (legitimate pre-data); after sealing it
is **fatal**. Both halves are asserted in one test.

**Re-sealing requires two deliberate overrides.** With the stamp present the
verifier fails on the hash. With the stamp deleted, `--seal` still refuses because
`meta.status` is `SEALED` rather than `SEALED_PENDING_STAMP`. This was exercised
for real: `DEV-SEAL-1` documents an actual re-seal, and both guards had to be
overridden to do it.

**The verifier re-derives rather than re-reads.** Every value in `derived` is
recomputed by *calling* `lib/stats.py`. A verifier that read 298 back out of the
YAML would have confirmed it forever. This is also why the sample-size checks
assert **minimality** where the file claims it: `confirmatory_e_cell` states 119 is
the minimum, and the verifier checks that n=118 genuinely fails.

**A floor on its own assertion count — per check, not in total.** Each check
declares a minimum yield and the CHECKS table's membership is pinned; a check that
stops asserting, or is deleted outright, exits 2 rather than 0. The global floor of
60 is retained beneath them to catch a wholesale gutting of the table.

The per-check table exists because the global floor **failed in service**: at 189
assertions a floor of 60 let two-thirds of the checks vanish undetected, and the
mutation test that removes three of them silently began passing at rc=0 (§4.6). A
floor set below the current total loosens every time the verifier gets stronger, and
no single total can localise one missing check. Same discipline as the redaction
gate's `MIN_FILES` and the coverage gate's `MIN_ROWS`, one level finer.

---

## 6. What is verifiable about this finding

```sh
python3 verify_prereg.py                                   # 189 assertions, sealed
python3 corpora/verify_corpora.py                          # 213 assertions, κ, rebuild
python3 -m pytest claims/tests/test_prereg_verifier.py -q  # 69 tests
python3 -m pytest claims/tests/test_corpus_gate.py -q      # 21 tests
shasum -c PREREGISTRATION.sha256                           # the seal
./verify_phase0.sh                                         # 8/8 gates
```

The mutation suite is the load-bearing part. It tampers with a **copy** in
`tmp_path` — never the real file, because a test that mutates the artifact it
verifies can leave the tree poisoned if it dies mid-run, which has already
happened once in this project with a redaction canary.

Three control arms, not one: an unmutated tree must pass, a no-op YAML round-trip
must pass, **and** the unpatched verifier must clear every per-check assertion
floor. Without the second, a formatting-induced failure would be indistinguishable
from a genuine kill and every mutation would look successful. Without the third,
the floor table of §4.6 could be set above what the checks actually yield, and
every run would fail for a reason unrelated to the file under test.

Two mutations were additionally hand-checked to confirm they kill for the reason
their names claim rather than via a cheaper check that happens to fire first — the
family-growth mutation now uses a **real** case ID (F5-7b) so it cannot be
satisfied by the "not a case" assertion, and asserts on the α-mismatch message
specifically.

One test asserts the **live** artifact rather than a copy. The fixture normalises
its copy to a pre-seal state, which means the suite could otherwise pass in full
while the real `PREREGISTRATION.yaml` was unsealed or failing —
`test_the_live_prereg_is_sealed_and_verifies` closes that hole.

**Deletion is now as loud as falsification.** Every check reads a field, so
deleting the field deletes the check — and that is the cheaper attack. A
precondition pass runs before any arithmetic, listing every field the checks
consume; a missing one exits **2** (the input is unusable) rather than 1 (a check
disagreed), and it is parametrised over six sections so the list is a fix for the
class and not for the one field that prompted it. `missing_required_fields()` is
itself mutation-checked: a version returning `[]` unconditionally would pass every
test around it, so one test removes a known field and asserts exactly one path is
reported.

**The deviation history is checked as a chain, not a set.** Each entry's *hash
before* must equal the previous entry's *hash after*, and the last must equal the
live stamp. A re-seal that happened without an entry therefore breaks the chain at
that point — which is the one event `DEVIATIONS.md` exists to make impossible to
omit. The hash is read from `PREREGISTRATION.sha256`, never hardcoded: a literal
would fail on every legitimate re-seal even when the document was updated
correctly, training the reader to edit the test instead of the artifact. The first
version of that test did hardcode it and did exactly that.

---

## 7. Consequences for the plan

1. **The Phase-1 gate condition "pre-registration sealed before first spend" is
   met.** Sealed at `a2136a9d3dbb…` with cumulative project spend **$0**.
2. **Five plan sizes changed; two corpora grew.**
   Benign 60→110, hard negatives 60→69→60, PII 108→367 (from a flat total to 31 per-entity cells),
   confirmatory cells acquire n=120 where they had none. Cost impact is negligible
   — all are `ApplyGuardrail` text units or gateway calls, inside the Phase 1 ~$5.
   The hard-negative figure moved **twice**: DEV-P0-2 raised the plan's 60 to 69,
   and DEV-P0-8 brought it back to 60 by removing nine items that were not
   negatives with respect to the filter scoring them. The end state coincides with
   the plan's number and did not come from it, which is why `corrects: prereg_size`
   is a class of its own — the second move corrected **this file**, not the plan.
3. **The κ ≥ 0.80 gate is met.** The corpora were built to the sizes fixed here
   (1,917 items) and scored **κ = 0.9593** over a 300-item audit sample. The
   pre-registration having fixed the sizes first is what made that a build against
   a specification rather than a judgement — and the gate's **residual** is where
   DEV-P0-8 came from, so the sizes it fixed were then corrected by the audit it
   enabled. What this κ does **not** license is stated in `irr_report.json` and in
   `FINDING-P0-PII-CORPUS.md`: one rater against a constructive label is a validity
   measure, not the plan's two-rater reliability κ.

   The gate is now **enforced rather than reported**: `corpora/verify_corpora.py`
   (213 assertions, 22 mutation tests) re-checks κ against the *sealed* threshold, and
   with it two properties the κ figure alone does not imply — that the manifest still
   describes the files on disk, and that `build.py --out` reproduces all 49 files byte
   for byte. Property 2 is the one that matters for reuse: a hand-edited item whose
   checksum was updated to match satisfies every other check, and only a rebuild knows
   the text is not what the templates emit. See DEVIATIONS.md/DEV-SEAL-7, which also
   records why a derived artefact's `prereg_sha256` must equal the **live** seal while
   an evidence record's must not — regenerability distinguishes them.
4. **`DEVIATIONS.md` exists and has seven real entries, two of them `design`
   class.** A deviations file whose machinery has never been exercised is an
   untested code path; this one has been used seven times, six requiring both
   seal guards to be overridden deliberately, and the hash chain is checked as a
   chain so an unrecorded re-seal breaks it at that point. DEV-SEAL-7 is the first
   entry whose before- and after-hashes are **equal**: it records that a change did
   not touch the sealed file, which is a fact about the change rather than a reason
   to omit it.
