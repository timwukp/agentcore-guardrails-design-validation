# DEVIATIONS

Every change to `PREREGISTRATION.yaml` after its first sealing, and every
departure at analysis time from what it specifies.

**Why this file is append-only and dated.** The value of a pre-registration is
entirely in the fact that it was fixed before the outcome was known. A change
that is invisible destroys that value; a change that is visible, dated, and
labelled with whether data already existed does not. So the rule is not "never
change it" — that would be unrealistic and would encourage hiding changes — but
**every change is recorded here with the one fact that determines how much it
matters: had data been collected yet?**

`verify_prereg.py` enforces the mechanical half: it refuses to pass if the file's
hash no longer matches `PREREGISTRATION.sha256`, and refuses to re-seal an
already-sealed file. Re-sealing therefore requires deliberately removing the
stamp, which is exactly the kind of act that should leave a written trace.

| Field | Meaning |
|:---|:---|
| **Data existed** | Whether any AWS measurement had been collected when the change was made. `no` means the change cannot have been outcome-driven. |
| **Class** | `editorial` (no effect on any decision rule) · `design` (changes an n, threshold, family or oracle) · `analysis` (a departure at analysis time) |

---

## DEV-SEAL-1 — `stamp_prereg.py` named in a comment does not exist

- **Date:** 2026-08-09
- **Data existed:** **no** — cumulative AWS spend at the time of this change was
  **$0**; no experiment beyond F0-1 (read-only HTTP) and the offline SDK bisect
  had run, and no measurement of the document under test existed.
- **Class:** editorial
- **Hash before:** `d21b51ecd6095afbe41bf7c3ee663e01619db9fb08c6d23b8b394a9628785bf6`
- **Hash after:** `195e792f9a02dc2b3d35151e894942cd882f6463e34335c442be1c125185c250`

**What changed.** One inline comment on `meta.status`, which read:

```yaml
status: SEALED     # stamp_prereg.py sets this to SEALED and fills sha256
```

There is no `stamp_prereg.py` in this project. The sealing is performed by
`verify_prereg.py --seal`. The comment was written before the sealer was folded
into the verifier and was not updated.

**Why it was fixed rather than left.** The comment tells a reader to run a script
that does not exist, in the one file whose whole purpose is to be trustworthy
about procedure. Leaving a false instruction in a sealed artifact to preserve a
hash would be optimising for the appearance of rigour over the substance of it.

**What it did not change.** No hypothesis, sample size, significance level,
family membership, oracle, corpus size or decision rule. The `derived` and
`sample_sizes` sections are byte-identical, and `verify_prereg.py` re-derives all
112 assertions from `lib/stats.py` either way — the verification result is
unchanged before and after.

**Procedure followed, and what it demonstrated.** Re-sealing required overriding
**two independent guards**, which is the point of having them:

1. With the stamp present, `verify_prereg.py` failed with
   `PREREGISTRATION.yaml has been modified since sealing: stamp d21b51ecd609… vs
   file 195e792f9a02… — this requires a DEVIATIONS.md entry`. So an undocumented
   edit to a sealed pre-registration cannot pass the Phase 0 gate.
2. After deleting the stamp, `--seal` **still refused**, because `meta.status` had
   already been set to `SEALED` and the sealer only accepts
   `SEALED_PENDING_STAMP`. Editing that field back is a second deliberate act.

Both refusals are exercised as tests (`test_editing_a_sealed_prereg_is_detected`,
`test_resealing_is_refused`), so this is a demonstrated property rather than an
observed one-off. Only after both overrides did sealing proceed, and this entry is
the trace they were designed to force.

---

## DEV-SEAL-2 — a false figure in DEV-P0-4's justification, and the gap that let it through

- **Date:** 2026-08-09
- **Data existed:** **no** — cumulative AWS spend **$0**; no measurement of the
  document under test existed.
- **Class:** editorial (no n, threshold, family, oracle or decision rule changed)
- **Hash before:** `195e792f9a02dc2b3d35151e894942cd882f6463e34335c442be1c125185c250`
- **Hash after:** `d321218a47fda162e9deb59d71679b64d034ba6199c1f9307180d472bb5090f9`

**What was wrong.** `attack_recall_cell.rule` and `deviations_from_plan[DEV-P0-4].why`
both stated that the F3 oracles' "recall's Wilson lower bound > 0.5" threshold is

> satisfied at n=10 by an 80% observed recall

`wilson_ci(8, 10).lo = 0.4902`. It is **not** satisfied — 0.4902 < 0.5. The claim
was false as written.

**Was DEV-P0-4 itself wrong?** No, and this is the part worth being precise about.
The deviation's *conclusion* — that the oracle threshold cannot double as a sample
size — is correct and in fact **understated**. Recomputed:

| Observation | n | Wilson lower bound | Clears 0.5? |
|:---|---:|---:|:---|
| 8/10 (the figure as written) | 10 | 0.4902 | **no** |
| 4/4 (smallest satisfying n at all) | **4** | 0.5101 | yes |
| 7/8 (smallest without perfect recall) | **8** | 0.5291 | yes |

So the oracle is satisfiable at n=4, and at n=8 without requiring a flawless run —
weaker than the n=10 the text claimed. `n=87` for the attack cells is unchanged,
because it was never derived from this figure: it comes from the half-width rule.
No sample size, oracle or decision rule moves.

**Why it survived sealing — the actual defect.** The figure lived inside a prose
`rule:` string. `verify_prereg.py` recomputed every value in `derived` and every
`bound_*` field in `sample_sizes`, but nothing parses English. **A justification
that is not machine-checkable is not verified, however many assertions run
alongside it.** The verifier reported 112 green assertions over a file containing a
false statement, and would have gone on doing so.

**What changed, therefore, is not just the number:**

1. The three figures were hoisted out of prose into a checked data block,
   `attack_recall_cell.oracle_is_weak_at`, with the bound at each n pinned.
2. Six assertions were added: each claimed n satisfies the oracle, each claimed
   *smallest* n is genuinely smallest (n−1 must fail), and
   `wilson_ci(8,10).lo > 0.5` must remain **false** — so the deleted claim cannot
   return without the gate failing.
3. `lower_bound_at_n_10_x_8: 0.4902…` is retained deliberately. The refuted figure
   stays in the file as a pinned counterexample rather than being erased.
4. Assertion count 112 → **120**.
5. A **precondition pass** (`missing_required_fields`) now runs before any
   arithmetic, listing all 27 fields the checks consume. Deleting a field was
   easier than falsifying it: before this, removing `oracle_is_weak_at` raised a
   bare `KeyError` — rc=1 by luck, reported as a crash, and one stray `.get()`
   away from silently skipping eight assertions. A missing field is now rc=2, and
   the check is parametrised over six sections so it fixes the class rather than
   the instance. `missing_required_fields()` is itself mutation-checked, because a
   version returning `[]` unconditionally would pass every test around it.
6. This file's **hash chain** is now asserted: each entry's *hash before* must
   equal the previous entry's *hash after*, and the last must equal the live
   stamp. An unrecorded re-seal breaks the chain, which is the only event this
   file exists to make impossible to omit.

**A second defect found while fixing the first.** The helper asserting each cell
satisfies its rule was named `minimal()` and its docstring read "Assert n satisfies
the rule AND that n-1 does not" — it never checked n−1 at any of its four call
sites. Renamed `satisfies_rule()`, with the docstring now stating what it does and
why minimality is *not* asserted generally (several cells are deliberately rounded
up above their minimum for corpus reuse, so asserting n−1 fails would be false).
The two cells that do claim a minimum keep their own explicit n−1 checks. A name
that overstates a check is worse than no check, because it stops anyone adding the
real one.

**The verifier caught my correction being wrong too.** The first replacement
claimed n=11 via 9/11 as the smallest non-perfect case. The new minimality
assertion rejected it (`9/11` is not the strongest non-perfect observation at
n=11, and n=8 clears the bar), and the correct value 7/8 was substituted. This is
the intended behaviour of a check written against a claim rather than against my
own arithmetic.

---

## DEV-SEAL-3 — the PII corpus (DEV-P0-6): the first `design`-class amendment

- **Date:** 2026-08-09
- **Data existed:** **no** — cumulative AWS spend **$0**; no measurement of the
  document under test existed.
- **Class:** **design** — this is the first entry in this file that changes a
  corpus size and adds a `sample_sizes` cell. DEV-SEAL-1 and -2 were `editorial`
  and said so; labelling this one the same way would be the easier and dishonest
  choice, because `design` is the class that invites the question "was it
  outcome-driven?" That question is answerable here, which is the whole reason the
  **Data existed** field exists: **no**, at $0 spend.
- **Hash before:** `d321218a47fda162e9deb59d71679b64d034ba6199c1f9307180d472bb5090f9`
- **Hash after:** `d5f4790f138e32d03fb7465ee7e888411d2395731365fb7f52b992e28a2b5e6a`

**What changed.** `corpora.pii` went from a flat `total: 108` to a per-entity plan
(`per_entity: 11` × 31 SDK entity types = 341 positives + 27 negatives = 368), a
new `sample_sizes.pii_per_entity_cell` was added, and a
`corpora.pii.source_corpus_audit` block records the audit of the source corpus as
data. `DEV-P0-6` in `deviations_from_plan` states the substance. Full argument:
`results/FINDING-P0-PII-CORPUS.md`.

**Why.** The approved plan says *"reuse the existing 108-case corpus, **extended to
align with the 31 SDK entity types**"*. The first sealing kept the reuse clause and
dropped the extension clause. Inspecting the corpus instead of citing it showed the
recorded `108` was wrong in two independent ways: it is a **secrets/credential**
corpus (8 of its 15 labels name no `GuardrailPiiEntityType` at all, and 24 of the
SDK's 31 types have zero coverage), and a **flat total cannot satisfy a per-entity
oracle** — F3-4's condition quantifies over entities, and an entity at n=0 has no
interval, so the oracle is undefined rather than unfalsified. A harness reporting
"not falsified" for a cell it never populated produces a pass that looks like
evidence.

**What it did not change.** No other corpus, cell, family, oracle, threshold or
significance level. Cost impact is +260 `ApplyGuardrail` text units inside Phase 1.

**The same defect recurred inside this amendment.** The first draft of `DEV-P0-6`
put two counts into a YAML comment and a `why:` string — "4 more map after
relabelling" and "25 of the SDK's 31 entity types". Both were wrong (**5** and
**24**). They were found by recomputing the mapping table while writing the
finding, not by any check, because they were in prose — which is precisely
DEV-SEAL-2's lesson, recurring one screen further down the same file, in the
amendment that recorded it. Being able to say that is more useful than a clean
narrative: the rule did not fail to be learned, it failed to be *applied*, and the
only defence against that is machinery rather than intention.

**So the counts became machinery.** `check_pii_source_audit()` recomputes all nine
audit figures from the corpus `.jsonl` files and the **live SDK enumeration**;
every mapping target must be a name the SDK actually enumerates (`CREDIT_CARD` as
its own target now fails the gate — 13 of the 15 source labels are plausible names
the SDK does not use); and the mapping must cover exactly the labels present on
disk, so deleting a key cannot shrink the label set into self-consistency. The
mapping itself is **pre-registered**: relabelling after seeing which entities fire
would tune the corpus to the outcome and be undetectable afterwards. Assertions
130 → **144**; 21 new mutation tests, including a parametrised arm that falsifies
each audit count individually — parametrised because the defect was *two* wrong
numbers in one paragraph, and killing one would have left the other as unverified
as before.

**One of the new tests exists to stop the others being vacuous.**
`check_pii_source_audit` **skips** its item-count assertions when the sibling
corpus is absent, which is correct for a reader who does not have that repository
and fatal for a mutation suite: every item-count mutation would have "passed" via
the skip branch. The fixture now copies the corpus into the mutant tree, and
`test_the_source_corpus_audit_assertions_are_live_not_skipped` asserts the skip
message did **not** appear.

---

## DEV-SEAL-4 — a reuse split that summed correctly and was impossible (DEV-P0-7)

- **Date:** 2026-08-09
- **Data existed:** **no** — cumulative AWS spend **$0**.
- **Class:** **design** — it removes the plan's stated reuse of the PII corpus for
  positives, which is a change to the instrument, not to its prose.
- **Hash before:** `d5f4790f138e32d03fb7465ee7e888411d2395731365fb7f52b992e28a2b5e6a`
- **Hash after:** `fcf02c22da3fce506c4ebad1d4c5f91081cfa9d4cd38fb4f49301b963d9ed341`

**What changed.** `corpora.pii.reused_from_108_case_corpus: 39` /
`authored_new: 302` were replaced by `positive_items_reused_verbatim: 0`,
`positive_items_authored: 341`, `reused_test_values: 4`, and a
`reuse_feasibility` block that keeps the refuted 39 pinned beside the 35 that
would actually fit.

**How it was found.** Not by a check — by *writing the builder*. `build.py`'s size
gate passed on the first dry run, all 19 cells matching the sealed figures, and the
defect was in a field the gate did not consult: the file said 39 positives were
reused and the builder had authored all 341. Counts agreed; provenance did not.

**Two independent defects, one field.**

1. **It was arithmetically infeasible.** 39 was copied from
   `source_corpus_audit.reusable_items`, which counts items whose *label* maps to
   an SDK entity type. That count ignored the per-entity cap introduced by
   DEV-P0-6 in the same amendment: the source corpus holds 15 credit-card items
   and `CREDIT_DEBIT_CARD_NUMBER` holds `per_entity = 11`, so 4 of them have
   nowhere to go. Summing `min(distinct reusable, 11)` per entity gives **35**.
   39 was not merely wrong — it was unachievable.
2. **It pointed the wrong way.** Reusing an item brings its own sentence. Every
   entity is embedded in the *same* 11 carriers precisely so that a per-entity
   detection difference is attributable to the entity; reusing those 35 items
   would give 7 of the 31 entities carriers no other entity has, confounding
   entity identity with carrier text in the one comparison F3-4 makes. So the
   feasible 35 is rejected too, on design grounds. Verbatim positive reuse is
   **0**, and what remains is value-level: 4 published test constants this corpus
   needs anyway also appear in the source corpus.

**Why the existing check could not see it.** `verify_prereg.py` asserted
`reused + authored == positives`, and 39 + 302 = 341 exactly. **A partition that
sums is not a partition that is feasible** — the arithmetic identity a total gives
you is orthogonal to whether the parts can be realised. This is a new failure mode
in this file: DEV-SEAL-2 and DEV-P0-6 were figures *no* check read, whereas this
figure was read by a check that was true and uninformative. Per
`feedback_vacuous_test_check`, an assertion true by construction is not evidence,
and a sum over a partition is true by construction whenever the partition was
authored as a sum.

**What became machinery.** `check_pii_reuse_feasibility()` recomputes the feasible
maximum from the corpus on disk under the live `per_entity`, pins the refuted 39 to
the audit figure it was copied from, and asserts `refuted > placeable` — so if a
future edit ever made 39 achievable, this deviation's reasoning is flagged for
revisiting rather than silently inherited. `build.py` recomputes
`reused_test_values` by substring search instead of trusting it, and asserts the
**carrier control itself**: all 31 entities must share one carrier set, which is
the reason 0 was chosen over 35. Mutation-checked in four directions (35→39, 4→5,
39→30, and shifting one entity's carriers), all four killed.

**The generalisable lesson.** The three prose defects in this file were all caught
by *recomputing a number*. This one was caught by *building the thing the numbers
describe* — the first defect in the pre-registration that no amount of re-reading
would have surfaced, because both halves were internally consistent. An
implementation is a check that a specification cannot perform on itself.

---

## DEV-SEAL-5 — a negative control that was not negative (DEV-P0-8)

- **Date:** 2026-08-09
- **Data existed:** **no** — cumulative AWS spend **$0**.
- **Class:** **design** — two corpus sizes change and 10 items leave the corpus.
- **Hash before:** `fcf02c22da3fce506c4ebad1d4c5f91081cfa9d4cd38fb4f49301b963d9ed341`
- **Hash after:** `6eb1ba6e09d474e6310aff0010d77fc4d7dcfeed56905b37e4e895043923e8e4`

**What changed.** `corpora.hard_negatives.total` 69 → 60 and
`corpora.pii.negatives` 27 → 26. A new `corpora.pii.entity_screen_exclusions`
pins both exclusion counts, and `sample_sizes.hard_negative_cell` gains
`corpus_n` and `falsifying_x_at_corpus_n`.

**How it was found.** By the **κ audit's disagreements**, not by a check. κ came
out at 0.9530 and passed the 0.80 gate; the gate was satisfied and the 13
disagreements were the informative part. Twelve were `hard_negatives` items I
rated `CLEAN` or `PII` — and one of those, `NRIC: S1234567D`, I had rated `PII`
against a label asserting the item contains no documented entity type. Reading why
I disagreed with my own label found the defect. **A passing gate is not a reason to
stop reading; the residual is where the information is.**

**The defect.** Both cells were populated from `source_corpus_audit.mapping`, where
`DB_CONNECTION_STRING: null` means *no `GuardrailPiiEntityType` names that
concept*. That is true of the **label** and false of nine of the **items**:

| item | label asserts | actually contains |
|:---|:---|:---|
| `postgres://user:pass@db.host:5432/app` | no documented entity | `USERNAME`, `PASSWORD`, `URL` |
| `mysql://root:rootpw@127.0.0.1:3306/mydb` | no documented entity | + `IP_ADDRESS` |
| `mssql://sa:Pa$$w0rd@sql.host:1433/db` | no documented entity | + `EMAIL` |
| `name: John\nnric: S1234567D` | no documented entity | `NAME` |
| `http://example.com is just a placeholder` | `CLEAN` vs the PII filter | `URL` |

`USERNAME`, `PASSWORD`, `URL`, `IP_ADDRESS`, `EMAIL` and `NAME` are all among the
31 entity types under test. **This is DEV-P0-7's root cause exactly — a label-level
fact read as an item-level property — recurring inside the cell that amendment
created.** DEV-P0-7's `39` was `reusable_items`, a count of *labels* that map;
DEV-P0-8's `42` was a count of *labels* that do not. The same mistake, both signs.

**Why it was not cosmetic.** F3-3 is falsified when the hard-negative FPR's lower
bound exceeds 0.10. At n=69 that needs **12** detections
(`wilson_ci(12,69).lo = 0.1024`). A PII filter that works at all on
`USERNAME`/`PASSWORD`/`URL` would have detected those nine **correctly**, and the
arm would have scored every one as a false positive:

| | n | x needed to falsify F3-3 | supplied by the confound |
|:---|---:|---:|---:|
| before | 69 | 12 | **9 (75%)** |
| after | 60 | 11 | 0 |

Three-quarters of the falsification threshold would have come from a labelling
error rather than from the filter's behaviour — and it would have been reported as
the document being wrong about hard negatives.

**A negative control is a property of a (text, filter) pair, not of a text.** The
27 negatives were justified in the sealed file as "label-agnostic, so reuse costs
nothing". That was true of the question the source corpus was built for — are these
*secrets*? — and false of the question this project asks it: does the **PII filter**
fire? `http://example.com` is clean with respect to secrets and is a `URL`.

**What became machinery.** `build.py` gains `ENTITY_SCREEN` and
`entities_present()`, a structural screen (URI scheme, dotted quad, RFC 3986
userinfo, MAC, AKIA/ASIA, one `name:` assignment) plus a guard over both cells;
`verify_prereg.py` gains `check_entity_screen_exclusions()`, which **imports the
screen from the builder** rather than restating it — two copies would drift and each
file would then be checking its own copy. Assertions 147 → **156**.

**The exclusion count is pre-registered, and that is the load-bearing part.** The
builder drops whatever the screen flags, so the builder's own guard passes *by
construction* whatever the screen does. Mutation-checked in both directions: a
screen returning `[]` (nothing excluded) and a screen returning `["URL"]`
(everything excluded) are **both** killed, by the pinned counts rather than by the
guard. Six mutations total, all killed.

**What is NOT claimed.** The screen is structural and deliberately incomplete:
`NAME`, `ADDRESS` and `AGE` are not decidable from surface form and are not
screened for beyond one explicit `name:` assignment. So a clean screen means *no
structurally obvious documented entity*, **not** *no documented entity*, and F3-3's
finding must state that bound. The instrument that found this defect was a human
reading 309 items, and it remains the only instrument that can find the general
case.

**The generalisable lesson.** DEV-SEAL-4's was "an implementation is a check a
specification cannot perform on itself". This one goes one step further: the
implementation was clean, the size gate passed, the κ gate passed, and the defect
was still there. It was found in the **residual of a passing test** — the 13
disagreements a 0.9530 κ leaves behind. A gate answers the question it was built to
ask; the items it disagreed with answer questions nobody thought to ask.

---

## DEV-SEAL-6 — a published count derived from a proxy, and a mutation that had stopped mutating

- **Date:** 2026-08-09
- **Data existed:** **no** — cumulative AWS spend **$0**.
- **Class:** **process** — no size, corpus, family, oracle or threshold changes. What
  changes is how one published figure is derived, and two tests that were not testing.
- **Hash before:** `6eb1ba6e09d474e6310aff0010d77fc4d7dcfeed56905b37e4e895043923e8e4`
- **Hash after:** `a2136a9d3dbb22888fc57bdf6c0002d5f0c33279d07bddd6a86f9006fa74cf1a`

**What changed.** Every `deviations_from_plan` entry gains `corrects:` (one of
`plan_size` · `prereg_size` · `provenance` · `convention`) and `corrects_why:`.
`verify_prereg.py` gains `check_deviation_classes()` and two list-aware precondition
entries. Assertions 156 → **189**.

**How it was found.** By the Phase-0 gate failing after DEV-SEAL-5 — but the useful
part is *which* five tests failed and why they are not one problem. Three were
ordinary staleness: pinned counts that DEV-SEAL-5 moved. Two were instrument
defects that had been present and invisible.

### Defect 1 — a published figure inferred from a field that does not mean it

`FINDING-P0-PREREG.md`'s summary row **"Plan sizes corrected"** was computed by
`test_every_deviation_from_plan_is_recorded` as *the number of entries carrying a
`design_impact` field*. Its own docstring claimed the split was "asserted from each
entry's own fields rather than from a hardcoded list" — and it was, but from the
**wrong** field. The proxy was accurate for the first six entries and wrong for both
that followed:

| entry | proxy says | truth | why |
|:---|:---|:---|:---|
| DEV-P0-7 | size correction | **provenance** | its own `design_impact` reads *"no size, cell, oracle or threshold changes -- corpora.pii.positives is still 341"* |
| DEV-P0-8 | plan size corrected | **prereg_size** | `hard_negatives` 69 → 60 corrects the **69 this file set** in DEV-P0-2. The plan said 60. |

So the proxy would have published **7** where the answer is **5**, and it would have
been wrong in two different ways at once: counting an entry that changes no size, and
crediting the plan with a size this file introduced. `prereg_size` is kept as a class
of its own precisely so this file's own defects cannot inflate a figure that is a
statement about the approved plan.

This is `feedback_prose_is_not_verified` one level up. That lesson was about a number
inside a justification string; this is a number that no field stated at all — it was
**re-derived at test time from a structural accident**. A count with no field behind
it is not more verified than prose; it is less, because it looks computed. The fix is
the same shape as DEV-SEAL-2's: hoist the claim into data a check can read, then
check it. `check_deviation_classes()` also asserts the label agrees with the entry it
labels — a `provenance` entry whose `design_impact` states a `->` transition fails —
so the new field cannot itself become decorative.

### Defect 2 — a mutation that mutated a field nothing reads

`test_kills_reused_plus_authored_not_equal_to_positives` set
`corpora.pii.authored_new = 300` and asserted rc=1. It passed. **`authored_new` does
not exist**: DEV-SEAL-4 renamed it `positive_items_authored`. The test was adding an
unread key to the YAML, and the verifier was failing for an unrelated reason that
happened to be present in the same run.

This is the vacuous-test failure mode with an extra twist: the test was written
correctly, verified as killing, and then **decayed silently when the field it named
was renamed one amendment later**. Nothing in the suite tied the mutation's target to
a field the verifier reads, so the rename broke the test without breaking it visibly.
The fix asserts the target exists before mutating it, which converts the whole class
from "silently vacuous" into "fails loudly on the next rename".

**Why both were worth a re-seal rather than a quiet fix.** Neither changes a number
this project will publish about AWS. Both change how much the published numbers are
worth: one figure was being derived by accident, and one control had stopped being a
control. Recording them keeps the ratio honest — of the six seal entries so far,
**four** were found by an instrument built to check something else.

---

## DEV-SEAL-7 — the corpus gate, and what a provenance stamp means

**Class:** `process` — no size, no item and no analysis changed. A gate that did not
exist now exists, and an ambiguity in a recorded field was resolved by decision.
**Hash before:** `a2136a9d3dbb22888fc57bdf6c0002d5f0c33279d07bddd6a86f9006fa74cf1a`
**Hash after:** `a2136a9d3dbb22888fc57bdf6c0002d5f0c33279d07bddd6a86f9006fa74cf1a`
*(no re-seal: `PREREGISTRATION.yaml` is unchanged. Recorded here because the chain
must show that this change did **not** touch the sealed file, which is a fact about
the change and not an absence of one.)*
**Data existed:** no — cumulative AWS spend **$0**.

### The ambiguity

`corpora/irr_report.json` and `corpora/MANIFEST.json` each record a `prereg_sha256`.
After the DEV-SEAL-6 re-seal, both pinned `6eb1ba6e…` while the live seal was
`a2136a9d…`. Two readings, with opposite remedies:

- **Correct as recorded.** The field is the same provenance stamp `lib/evidence.py`
  writes into every API record, and evidence records are *never* rewritten. Under this
  reading the stamp says "the seal in force when this artefact was generated", and
  overwriting it would be falsification.
- **Silently stale.** The artefact describes a corpus whose sizes come from the sealed
  file; if the seal moved, nothing had checked that the artefact still follows from it.

Both readings are defensible, and that is the problem: **a field with two readings
verifies nothing**, because either state can be explained. The reading cannot be fixed
by choosing a preferred sentence about it.

### The resolution, and why it is not a matter of preference

The re-seal was reproduced instead of argued about. Re-running both generators against
the new seal produced output that differs from the committed artefacts **in the stamp
and nowhere else** — κ = 0.9593 and all 300 ratings byte-identical, all 49 corpus files
byte-identical. So the DEV-SEAL-6 amendment provably changed nothing either artefact
depends on.

That result is what licenses the decision now recorded in `corpora/verify_corpora.py`:
the stamp must equal the **live** seal, and the remedy for a mismatch is to re-run the
generator, never to edit the field. This keeps the honest half of the first reading — a
number is never hand-written into a derived artefact — while removing the ambiguity,
because the requirement is now about *content*: the artefact must be **regenerable**
from the seal in force. `test_kills_a_stale_provenance_stamp` pins it in both files.

The distinction from `lib/evidence.py` is real and worth stating: an API response
cannot be regenerated (the service may answer differently tomorrow), so its stamp is
history and must be immutable. A corpus **can** be regenerated. The rule is therefore
"immutable where regeneration is impossible, live where it is not", which is a property
of the artefact rather than a convention chosen per file.

### The gate itself

`corpora/verify_corpora.py` (213 assertions) checks three properties that no one of the
others implies:

| # | Property | What only this one catches |
|:--|:---|:---|
| 1 | The manifest describes the files on disk | a hand-edited `.jsonl`, a deleted file, and — in the other direction — a `.jsonl` on disk that the manifest never names, which a checksum sweep cannot see |
| 2 | `build.py --out <tmp>` reproduces `corpora/` byte for byte | an edit whose checksum **was** updated to match; property 1 is satisfied and only a rebuild knows the text is not what the templates emit |
| 3 | κ ≥ gate, about this corpus and this seal | a report that passes its own gate while describing a corpus that has since changed, or that carries a gate value lower than the sealed one |

Property 3's gate value is read from `PREREGISTRATION.yaml`, not from the report: a
report carrying its own copy of the threshold could relax it after seeing the data,
which is the single failure mode pre-registration exists to prevent.

`build.py` gained `--out DIR` for property 2. Rebuilding **in place** would overwrite
the very difference the check exists to detect — if the builder were non-deterministic,
the second run would destroy the evidence of the first before anything compared them.

### Three defects the gate found in its own construction

1. **A floor above the true yield fails in service.** `kappa_gate`'s floor was written
   as 11; the check yields 10, so the gate's first run exited 2 against a corpus that
   was entirely correct. The floor was lowered to the measured yield. This is the
   mirror image of DEV-SEAL-6's defect — there a floor was too *low* to localise
   anything; here one was too high to let a good artefact through.
2. **Floor precedence hid an accurate diagnosis.** With floors reported before
   problems, a genuinely broken builder was announced as "the check stopped asserting"
   — because `check_reproducible` correctly short-circuits when there is no tree to
   compare. Problems are now reported first, and the floor is applied only when a check
   found *nothing*, which is the silent case it was built for.
3. **A mutation was killed through the wrong branch.** `test_kills_a_builder_that_
   writes_nothing` suppressed the writes, which crashes the builder (it reads each file
   back to checksum it), so the test passed via the build-failure branch and the
   empty-tree guard was never exercised. It now makes the builder write a complete
   corpus to the *wrong directory* and exit 0. Its sibling, an extra emitted file,
   covers the membership branch — comparing only the intersection of the two trees
   would have passed, since every shared file was identical.

Defect 3 is the same lesson as DEV-SEAL-6's §4.6 hand-check, arrived at independently:
**a mutation that dies is not thereby a mutation that tested what its name says.**

### Also landed with the gate

`verify_phase0.sh` now runs `lib/tests/` and `f5_redteam/tests/` alongside
`claims/tests/` — 358 tests, up from 176. The two directories existed and passed but
were never in the gate, and per `feedback_no_deploy_path_no_component` a test suite no
gate runs is not a gate. Each directory carries a **collected-count floor**, because
pytest exits 5 only when it collects nothing *at all*: one directory silently
contributing zero tests — a renamed file, a broken import, a moved path — would
otherwise have been invisible in a green run. Both floors were mutation-checked.

---

## DEV-SEAL-8 — the amendment gate: a sealed rule that nothing enforced

**Class** `process` · **Date** 2026-08-09 · **Cost** $0
**Hash before** `a2136a9d3dbb2288…` · **Hash after** `a2136a9d3dbb2288…` (unchanged)

`PREREGISTRATION.yaml` is unmodified by this entry. It is recorded anyway, for the
reason established in DEV-SEAL-7: "this change did not touch the sealed file" is a fact
*about the change*, and omitting the entry would make the seal chain's silence
ambiguous between "nothing happened" and "nothing was written down".

### What was wrong

`validity_checks.reproduction_before_amendment` has been sealed since the
pre-registration was stamped:

> No claim in the document is amended on a single day's data. Required: pre-registered
> n met, reproduced on >= 2 separate calendar days, raw evidence with x-amzn-requestid
> archived, and an alternative-explanation register showing what else could produce the
> observation.

A grep for `reproduction_before_amendment`, `calendar` and `replicat` across every `.py`
and `.sh` in the tree returned **the YAML and nothing else**. The rule was enforced by
no gate, no test and no script, while 8 gates and 358 tests reported green. It held on
2026-08-09 only because I remembered it when writing FINDING-F5-7A — and per
`feedback_prose_is_not_verified`, *a rule that depends on being recalled at the moment
of writing is an intention, not a control*. This is that memory's own lesson one level
up: a rule instead of a number.

The defect was surfaced by the user asking what the Day-2 blocker had to do with the
testing, not by any instrument in the repository.

### The gate

`check_amendment_readiness.py` (30 assertions, 25 mutation tests, 2 control arms). Each
`FINDING-*.md` now carries a machine-readable `<!-- provenance -->` block declaring a
status and the `evidence_runs` its claims rest on.

**Dates are derived, not declared.** The gate reads `t_start_utc` from every evidence
record under the declared runs and counts distinct UTC calendar days. A finding cannot
assert its own replication. Had the gate parsed the `**Date:**` line instead, it would
have been checking a number inside a sentence — precisely the defect this project
screens the document for. Three mutation arms hold that line:

| Arm | What it forbids |
|:---|:---|
| `test_the_run_id_is_not_trusted_for_the_date` | a run directory named `r20260810T…` whose records still carry an 08-09 timestamp |
| `test_two_runs_on_the_same_day_do_not_count_as_replication` | a second `run_id` minted the same day — the cheapest way to fake replication, since ids are per-invocation |
| `test_kills_a_relaxed_seal` | editing the YAML down to `>= 1` day, which makes the gate report a **disagreement** rather than pass |

The last one matters most: `MIN_DAYS` is checked against the sealed rule's own wording,
so the only way to lift a block is evidence. `test_a_second_day_of_evidence_lifts_the_block`
proves it *is* liftable — a gate that can never say yes is a wall, not a control.

**Scope.** The rule binds statuses `AMENDED` and `READY_TO_AMEND`. Offline findings
declare `evidence_runs: []` with a note stating why replication is not an independent
observation for them: a published wheel, a static document and a corpus on disk have no
transient state for a second day to exclude. Requiring two days of those would make the
gate noise, and a gate that fires where it should not is one people learn to bypass.
`OBSERVATIONS_COMPLETE` requires a non-empty `blocked_on`, so a deferral is a decision
on the record rather than an omission.

### A vacuous test, caught by measuring instead of asserting

`test_problems_are_reported_before_floors` was **empty on its first version**. I chose a
single-day amendment as the mutation and asserted only that `stops asserting` was absent
from stderr. Running an order-inverted copy of the gate against that mutant showed it
yields 17 assertions and starves no floor — **both orderings printed the same thing**,
so the test distinguished nothing while carrying a name that claimed it did. That is
DEV-SEAL-7 defect 3 recurring in the very file written to apply its lesson.

Replaced with the deleted-rule mutation, which trips both conditions (1 assertion
against a floor of 3, plus a real problem); the inverted copy exits 2 where the correct
order exits 1. A companion arm, `test_the_precedence_mutation_would_starve_a_floor`,
asserts the mutation *still* starves a floor by counting assertions before the early
return — otherwise a later edit to `check_rule_is_still_sealed` would silently return
the precedence test to vacuity.

### Effect on the record

- Phase 0 gates: **9/9**; tests **384**, up from 358.
- FINDING-F5-7A's amendment of §4.5.3 is now blocked by machinery rather than memory,
  and the block is visible in the gate's own output rather than only in the finding's §7.
- No finding's verdict changed. Findings 1, 2, 3 and 6 of F5-7a never depended on the
  replication and still stand.

---

## DEV-SEAL-9 — the cost model, and a price that was wrong by 5×

**Class** `provenance` · **Date** 2026-08-09 · **Cost** $0
**Hash before** `a2136a9d3dbb2288…` · **Hash after** `a2136a9d3dbb2288…` (unchanged)
**design_impact** projection `$55–95 (prose)` -> `$6.67 (computed from verified prices)`

### What was wrong

The approved plan specifies an `estimate_cost.py` that *"refuses to run if the projection
exceeds the pre-registered ceiling"*. Neither half existed. There was no script, and
there was **no pre-registered ceiling** — the `$55–95` figure appears only in the plan's
prose, and `PREREGISTRATION.yaml` has no cost section at all (`grep` for `ceiling`,
`budget`, `spend` returns a rate-limit note and nothing about money). The control the
plan describes could not have run, because the number it was to enforce was not readable
by a program.

This is DEV-SEAL-8 again, one domain across: a rule sealed in prose, enforced by memory.

### The 5× price

`cost_model.yaml` began with five unit prices written from recollection of the pricing
pages. Four were wrong:

| Price | I wrote | Live Pricing API | |
|:---|---:|---:|:---|
| `guardrail_text_unit` | 0.00075 | **0.00015** | **5× too high** |
| `spans_ingest_gb` | 0.50 | 0.50 | right figure, **wrong usagetype** |
| `logs_storage_gb_month` | — | 0.03 | **omitted entirely** |
| `lambda_gb_second` | — | 0.0000133334 | **omitted entirely** |
| `guardrail_pii_text_unit` | 0.00010 | 0.00010 | correct |

The first would have inflated the projection by roughly $13 — a *cost disclosure*
misreporting its dominant line item by 5× while displaying five decimal places. The
second is subtler and worth naming: **a price that is right for a reason I had wrong is
not verified, it is a coincidence.** The usagetype I assumed
(`USE1-Application-Signals-TransactionSearch-Bytes`) returns **no products**; spans are
billed as ingested log data under `DataProcessing-Bytes`. Had the quantity later needed
revising, there was no anchor to revise it against.

`verified: true` therefore requires a `pricing_api` block naming service code and
usagetype. Without it the flag could only mean "a number was fetched from somewhere",
and a lookup aimed at the wrong usagetype **stamps a guess as confirmed** — worse than
no lookup. `--verify-prices` re-reads all nine and prints recorded-vs-live rather than
editing the file, for the same reason `check_reproducible` writes to a separate
directory: a check that repairs what it measures has measured nothing.

### Three refusals, and what each one is for

| Refusal | Catches |
|:---|:---|
| over ceiling | the obvious case, now with a ceiling a program can read |
| unverified price | a projection whose inputs nobody looked up certifying itself as affordable — `feedback_vacuous_test_check` applied to money |
| **unfunded replication** | a phase that may amend the document while declaring one day of observation |

The third is the one that ties spend to validity, and it did not exist in the plan. A
one-day Phase 6 costs $3.55 and buys evidence `check_amendment_readiness.py` will refuse
to let into the document: cheap and worthless, which no ceiling check would ever flag.

### What the 2-day rule actually costs: $0 in eight of ten live phases

The obvious reading of "reproduce on two separate days" is *run it twice*, which would
have doubled Phase 6 — the most expensive phase — and was the basis of my earlier
warning that Phase 6 might go from ~$15 to ~$30 and push the total past the plan's
ceiling. **That warning was wrong, in two independent ways.**

First, the arithmetic. Where *n* counts repeated trials of one condition (latency,
determinism) or exchangeable corpus items (detection), the pre-registered *n* is **dealt
across the two days** rather than run twice. The pooled estimator keeps the full *n*, so
the primary analysis is unchanged and the marginal cost is zero; what the split buys is a
between-day comparison the single-day design could not make at any *n*. Doubling would be
right only if day 2 had to *re-estimate* the quantity. It does not — it has to test the
quantity's **durability**, a different and cheaper question. Phase 6 pays only for
repeating its 20-call warm-up per night per arm: +320 calls against 16,640.

Second, the premise. The $15 figure I was reasoning about was itself prose. Phase 6 costs
**$3.55** at verified prices, and the whole project **$6.67** against a $95 ceiling.

Two phases are exceptions, and both are stated in `COST.md` rather than smoothed over:
**Phase 7** genuinely doubles (each region contributes one existence observation, so
there is no *n* to deal) at $0, because control-plane calls are unmetered; **Phase 8**
already spanned three days by design, at +7d and +30d, which makes it the strongest
replication in the project and means Phase 1's split is a screen rather than the
load-bearing evidence for §3.2.

And the split's limitation is recorded, not buried: a between-day comparison at *n*/2 per
day is a **screen**, detecting roughly a 0.2σ median shift at 2×500 latency trials and
usually missing a 5% recall shift at 2×60 corpus items. It excludes a *gross* transient —
an outage, a throttled window, a mid-deploy service state — which is what the rule is
for. It does not license "the two days are statistically indistinguishable".

### A defect the mutation suite found in the gate

`test_the_replication_threshold_comes_from_the_sealed_prereg` relaxes the sealed rule to
1 day and expects one complaint. It got **seven**: the converse check (`days >= min_days`
with no `amends:` target) fired on every confirm-only phase, because at `min_days = 1`
every phase satisfies the threshold. The check was reading the wrong quantity — baseline
observation is **one** day by definition, so replication is `days > 1`, independent of
what the sealed rule requires. A check whose meaning shifts when an unrelated constant
moves is a check that was never asking its own question. Fixed; the mutation now reports
exactly the one problem it should.

### Effect on the record

- Phase 0 gates: **10/10**; tests **405**, up from 384. `cost_model.yaml` (9 verified
  prices, 11 phases), `estimate_cost.py`, generated `COST.md`, 21 mutation tests.
- **Projection $6.67**, contingency $29.00 (four named triggers), worst case $35.67
  against a $95 ceiling. The plan's $55–95 was high by roughly an order of magnitude.
- Actual spend to date: **$0.00**.

### A free finding, from the price list

The Pricing API exposes `GuardrailChecks-*` usagetypes **separate from and cheaper than**
`Guardrail-*`: content filtering costs $0.00007 per text unit through
`InvokeGuardrailChecks` versus $0.00015 through `ApplyGuardrail`. **AWS meters the two
APIs as distinct evaluation paths.** That is billing-side evidence for exactly the
distinction F5-6/DC-2 was built to test behaviourally and that §3.2 blurs — obtained at
$0, before any live phase, from an instrument built to check money. Four of the
pre-registration's six self-found defects came from instruments built to check something
else; this is the fifth such case, and it is now the second-cheapest finding in the
project.

Recorded as `results/FINDING-P0-PRICING.md`. It does **not** amend §3.2 on its own —
separate metering does not entail different detection behaviour — so its status is
`INTERNAL` and the amendment still waits on F5-6's measurement.

---

## DEV-SEAL-10 — local midnight is not UTC midnight: a same-day repeat labelled Day 2

**Class** `provenance` · **Date** 2026-08-09 · **Cost** $0
**Hash before** `a2136a9d3dbb2288…` · **Hash after** `a2136a9d3dbb2288…` (unchanged)
**design_impact** none — the sealed rule was correct and held; the operator was wrong

### What happened

DEV-SEAL-8 sealed the rule that no claim in v1.2 may be amended on fewer than **two
separate calendar days** of observation, and built `check_amendment_readiness.py` to
enforce it. V13-03 (§4.5.3's PrivateLink matrix) is the first candidate to reach that
gate, so F5-7a needed a second day.

I collected one and named it `r20260810T0930Z`, because the system clock reported the date
as 2026-08-10. `date -u` at that moment read **2026-08-09T16:22:26Z**. The local calendar
had rolled; UTC had not. Every evidence record in that run carries
`t_start_utc: 2026-08-09T16:19…` — **6.8 hours** after Day 1's `09:28`.

`07a_compare_runs.py` refused it:

```
both runs were collected on 2026-08-09. A same-day repeat cannot distinguish a durable
change from a transient publication state, which is the only thing this comparison
exists to do
```

That is not a technicality. §7's alternative-explanation register lists *"the live page is
a stale or A/B-tested CDN variant"* as **not excluded**, and two reads 6.8 hours apart on
one UTC day exclude it no better than one read does. Had the comparator not existed, I
would have filed the pair as Day 1 + Day 2 and amended a documented AWS statement on a
single day's evidence — while every gate reported green, because the run **id** said
`20260810`.

### Why the gates were right to distrust the run id

`check_amendment_readiness.py` and `07a_compare_runs.py` both derive the observation day
from `t_start_utc` inside the evidence records and never from the directory name. That
design decision, made for a different reason, is the only reason this was caught. The run
id is a label a person chooses; the timestamp is written by the instrument.

### Three fixes, at three different distances from the mistake

1. **The record.** The directory is renamed `r20260809T162000Z` and the run id corrected
   inside all 18 JSON files. It is a valid **same-day repeat** — its verdicts are identical
   to Day 1's across all 75 compared fields — and it is retained as such, not deleted. A
   repeat that agrees is weak evidence; a repeat that is *relabelled as a replication* is
   false evidence.
2. **The source.** `lib/evidence.new_run_id` accepted **any** string, which is how the
   misleading name came to exist. It now parses the stamp and refuses one whose date
   disagrees with the current UTC date, in either direction. The authoritative check is
   downstream — but nothing downstream *renames a directory*, so a mislabelled name would
   have misled every later reader forever. `rFIXED`, which the old test asserted was
   acceptable, is now refused too: a run id whose date cannot be read cannot be checked
   against the clock, and accepting one reintroduces the whole failure mode through
   another door.
3. **The waiting.** `f5_redteam/07a_run_day2.sh` computes the sleep to **00:20Z** from UTC
   (not 00:00Z — a run straddling midnight writes records on both sides, and
   `observation_day` takes the earliest), and **re-asserts the day separation after the
   sleep returns**, because a sleep can return early (SIGCONT, a suspended laptop
   resuming) and the clock is the one input that changed while nothing was watching.

### The comparator, and why it is 230 lines instead of a paragraph

The thing under replication is the content of a **web page**, and the disagreement being
adjudicated *is* that content. So the criteria were fixed before Day 2's data was
consulted, as two disjoint sets:

- **MUST_MATCH** — 75 named assertions covering every observation the §4.5.3 amendment
  quotes: the six verdicts, the endpoint-service enumeration per region (count,
  reachability, service names, private DNS, policy support, and the *negative* keyword
  result), and the live page's support table row by row. Flattened into named fields
  rather than one object comparison, so a failure says `B:live:row:Evaluations` instead of
  "the analysis differs".
- **MAY_VARY** — request IDs, fetch timestamps, and the Internet Archive's CDX result set,
  which is a query against a third-party index and legitimately returned 8 snapshots on
  Day 1 and 6 on Day 2. A comparator that failed on these could never say yes, which is a
  wall, not a control — and a wall trains the operator to override it.

Wayback gets a third rule: snapshots present in **both** runs must agree on content,
because an archived page is immutable. A differing archived row would not mean AWS
changed; it would mean one of the two parses is wrong and **no** verdict from instrument B
could be trusted. Distinct in kind from every other disagreement, so it says so.

`MIN_ASSERTIONS = 20` is a floor on the compared-field count, for the same reason
`verify_phase0.sh` pins a collected-test count: a comparator that quietly stops comparing
reports "replicated" and is indistinguishable from one that works. The floor is itself
mutation-tested — `must_match` is monkeypatched down to one field and the run must fail
**on the floor**, not on a difference, or `MIN_ASSERTIONS` is decorative
(`feedback_prose_is_not_verified`).

### Mutation results

23 tests over `07a_compare_runs.py`, then three mutants of the comparator itself:

| Mutant | Arms failed |
|:---|---:|
| `always-replicated` (compare a run to itself) | 12 |
| `day-check-removed` | 2 |
| `wayback-fatal` (notes become disagreements) | 4 |

Two arms are **controls in the opposite direction**, asserting against the real artifacts
that the two runs *do* differ in request IDs and *do* differ in their snapshot sets, so
the tolerance is exercised rather than assumed. Without them, "REPLICATED" could mean the
comparator compares nothing.

### Effect on the record

- V13-03 remained `BLOCKED_ON_REPLICATION` at the time of writing. §4.5.3 was **not**
  amended. **Discharged 2026-08-10 — see DEV-SEAL-13.**
- Day 2 was scheduled unattended for 2026-08-10T00:20Z; its verdict lands in
  `results/f5_7a_replication.json` and `results/f5_7a_day2.log`.
- Tests: 23 new arms over the comparator, 4 over `new_run_id` (replacing one that asserted
  the permissive behaviour). Suite total **463**.
- Cost: **$0**. `DescribeVpcEndpointServices` is unmetered and creates nothing; the doc
  reads are HTTP GETs. Cumulative project spend remains **$0.00**.

> The generalizable lesson is not "check the clock". It is that **the local calendar day
> and the UTC day differ for most of the world for several hours a day**, and any rule that
> counts days is really a rule about a timezone it usually forgets to name. Ours names UTC
> because the evidence records do.

---

## DEV-SEAL-11 — the v1.3 amendment register: sites derived, not remembered

**Class** `provenance` · **Date** 2026-08-09 · **Cost** $0
**Hash before** `a2136a9d3dbb2288…` · **Hash after** `a2136a9d3dbb2288…` (unchanged)
**design_impact** none — no hypothesis, n, threshold or oracle changed

### The failure this exists to prevent, with a measurement behind it

The document restates its load-bearing propositions across sections: the default-deny
gotcha appears in **9 places across 7 sections**, guardrail non-determinism in 8, the
billing asymmetry in 7, the latency table in 2 plus Appendix B. A claim corrected at one
site and left standing at eight others is **not corrected** — and the measured version of
this mistake is already on this project's record: remembered wording once located **6 of
10** sites (`feedback_grep_the_claim_not_the_phrasing`).

So `V13_CANDIDATES.md` is **generated**. No candidate lists its own sites. Each declares
*what it is about* — test cases, merge groups — and sites are expanded from
`claims/triage.csv`. Adding a claim to a test case adds it to the register; the register
cannot fall behind the triage, because it is a view of it.

Anchors are deliberately **not** an expander, and a test asserts they never become one.
`s4-4` holds 37 claims and `s3-2` holds 35, so an anchor-level site list would say *review
this section* rather than naming the sentence — the coarse form of the same defect.

### Two defects in the generator, both found by checking its output against the triage

**First: anchors as granularity.** The initial version used anchors, which made V13-06's
site list "§6.1 and §9" — 64 claims. Deleted and rewritten around the `cases` column.

**Second, and more interesting: a test case tests many claims, only some of which a given
candidate amends.** V13-01 (§3.1's missing `validationMode`) resolved to **19** sites
because F1-3 touches 19 claims — 9 of them the default-deny merge group, and 10 of them
§3.1 bullets like *"Prompt Attack detection (JAILBREAK, PROMPT_INJECTION,
PROMPT_LEAKAGE)"*. Tested by the same experiment; nothing to do with the missing
parameter. V13-06 resolved to 28 for the same reason. **Sharing an experiment is not
sharing a fate:** one test can confirm one claim and refute another.

The narrowing rule: when a candidate declares merge groups, a case-derived hit outside
those groups is `related, not amended` — reported, with its derivation, so the reader can
see the experiment bears on it. V13-01 went 19 → 9, V13-06 28 → 18.

### The two overrides, and why an override without checks is just the hand-written list

No derived rule gets this right alone. §6.1's own **Total ~800ms–31s+** row carries no
merge group and is arithmetic over the six hop rows above it — replacing those with
measured quantiles and leaving the total as an estimate would print a table that does not
add up (`feedback_label_must_match_computation`, in the document this project exists to
correct). So there are two documented doors, each checked:

| Override | For | Check |
|:---|:---|:---|
| `claim_ids` | a site **no** expander reaches (class-D rows: the ILLUSTRATIVE disclaimer, the §4.5.3 `Service` column header) | requires `claim_id_rationale`; a named claim is **always** a site, or declaring a merge group would silently nullify the hatch |
| `also_sites` | **re**classifying a derived claim from related to site | requires `also_sites_rationale`, and the claim must already appear in the derivation — a promotion **cannot introduce** a site |

That second check is the load-bearing one. Without it the override degenerates into the
hand-written site list this file exists to replace, one individually-defensible exception
at a time.

The `claim_ids`-are-always-sites rule was itself a defect found by reading output:
V13-06 named the §6.1 disclaimer with a written rationale, and the first run of the
narrowed rule **demoted it to related** — because it has no merge group, which is exactly
the property that made it need the hatch.

### Mutation results

32 tests, then seven mutants of the generator. All caught:

| Mutant | Arms failed |
|:---|---:|
| `no-narrowing` (every case hit becomes a site) | 2 |
| `named-ids-demotable` (escape hatch subject to the split) | 1 |
| `also-sites-noop` | 1 |
| `promotion-unchecked` (a promotion may invent a site) | 1 |
| `no-truncation-guard` (a short triage generates a smaller register) | 1 |
| `mergegroup-expander-off` (one member per group instead of all) | 1 |
| `empty-sites-ok` (a candidate amending nothing passes) | 1 |

The mutation run also found a defect in the **tests**: the staleness arm
(`V13_CANDIDATES.md` on disk must equal a fresh build) passed under **every** mutant,
because an earlier test in the same session had already regenerated the file. It now
compares against a snapshot taken at import time and builds into a **separate directory**
(`feedback_provenance_stamp_liveness` — prove regenerability by rebuilding elsewhere). A
green result that depends on test execution order is not a check.

### The register as it stands

**9 candidates over 62 distinct document sites.** Two break a reader who follows the
document verbatim; four state something false or unsupported; three omit something
load-bearing. Nothing has been applied — amendment is Phase 9, and every candidate is
gated on `check_amendment_readiness.py`.

| ID | Sites | Status | What it is |
|:---|---:|:---|:---|
| V13-01 | 9 | `AWAITING_EXPERIMENT` | §3.1's permit instruction omits `validationMode` (DC-1) |
| V13-02 | 4 | `MEASURED_READY` | botocore ≥ 1.43.32, and the **1.43.30–.31 trap window** |
| V13-03 | 6 | `BLOCKED_ON_REPLICATION` | §4.5.3's PrivateLink matrix vs the live AWS page |
| V13-04 | 3 | `AWAITING_EXPERIMENT` | §9 asserts `fail-secure`; §3.3 BP#4 concedes the opposite |
| V13-05 | 10 | `AWAITING_EXPERIMENT` | §7.1's LOG_ONLY workflow may not be executable |
| V13-06 | 18 | `AWAITING_EXPERIMENT` | the ILLUSTRATIVE §6.1 latency table |
| V13-07 | 4 | `AWAITING_EXPERIMENT` | §6.4's alarm floor set by unstated publish lag |
| V13-08 | 4 | `PARTIALLY_DISCHARGED` | the NDA Accelerator release gate |
| V13-09 | 4 | `AWAITING_EXPERIMENT` | §3.2 conflates `ApplyGuardrail` and `InvokeGuardrailChecks` |

V13-02 is the only `MEASURED_READY` entry, and it is ready for a reason that generalises:
its evidence is an **offline** bisect over 14 botocore wheels, so "two separate calendar
days" has nothing to add — a wheel's contents do not change. The 2-day rule exists to
exclude transient service state, and there is none. That distinction is recorded in the
finding rather than left as an exemption someone has to remember.

### Effect on the record

- Phase 0 gates **11/11** (the register's own generation is now gate 8); tests **463**.
- `verify_phase0.sh` runs `build_v13_candidates.py`, so a triage edit that changes a site
  list can never leave a stale count in the deliverable.
- Cost **$0**; cumulative project spend **$0.00**.

---

## DEV-SEAL-12 — the oracle module: three defects in code written to prevent them

**Class** `provenance` · **Date** 2026-08-10 · **Cost** $0
**Hash before** `a2136a9d3dbb2288…` · **Hash after** `a2136a9d3dbb2288…` (unchanged)
**design_impact** none — no hypothesis, n, threshold, family or oracle changed. Three
thresholds and one family assignment were **corrected to match the seal**; none was chosen.

`lib/oracle.py` turns each of the 93 sealed oracle sentences into a decision function, so
that no verdict is reached by reading prose at analysis time. Its own gate
(`prose_support_problems`, now Phase 0 gate 5b) requires every threshold to be derivable
from the sealed sentence that names it. Three defects were found in it — each by asserting
against `PREREGISTRATION.yaml` rather than against what I remembered it saying, and each of
exactly the class the module exists to prevent.

### First: the gate accepted the defect it was written for

F7-7's binding declared `unit="ms"` with `thresholds=(60000.0,)` against the prose `"60s"`.
The gate passed it, because the derivation *is* internally consistent: 60s under a
millisecond unit really is 60000. But `QUANTIZATION` compares against the `Observation`
field `timestamps_s`, which is **seconds by the field's own name**, so every offset would
have compared as ~1000× too small and every alarm-period case would have passed regardless
of the data.

The unit is not a free choice per binding — it is fixed by which field the kind reads. So
`KIND_UNITS` is a closed **kind → unit** table (8 kinds) that the gate now checks
independently of the prose derivation:

> a consistent conversion into the wrong unit is still the wrong comparison

**Internal consistency is not verification.** A check that only asks whether two of my own
statements agree will pass whenever I am wrong in both — which is the ordinary case, since
one was derived from the other.

### Second: a sealed rule restated from memory agreed with it only in the part remembered

`family_of` decided the class rule with a hardcoded `if cls in ("C", "O")`. That matches
`descriptive_no_test.members_by_class` exactly — and ignores the very next key,
`excluded_from_this_rule: [F3-10, F7-6, F7-7]`. So all three cases the seal **names to
withhold the rule from** were receiving it. F7-7, above, is one of them.

The function now reads both keys from the prereg. `feedback_grep_the_claim_not_the_phrasing`
records the measured version of this: remembered wording once located 6 of 10 sites. This is
the same failure with a smaller surface — the remembered half of a two-part rule.

### Third: raising was not the safe default

`family_of` raised `KeyError` for any case the seal places nowhere. Measured: **11 of 93
cases** (11.8%) hit it — F5-3a/3b, F5-4a/4b, F5-7b, F5-8, F5-9, F9-1, F9-3, F10-1, F10-3 —
so `evaluate()` crashed on an eighth of the suite, **including both `RECORDED` cases** whose
entire purpose is to be evaluable without a prediction (F5-4a/4b: DENY or ALLOW, either is
the finding). The crash would have arrived in Phase 5, after the red-team data was collected.

It now returns a named `UNASSIGNED = "unassigned_by_seal"`. The three candidates and why
this one:

| Behaviour | Effect |
|:---|:---|
| `raise` | 11/93 cases unrunnable; failure arrives after collection |
| silently return `descriptive_no_test` | removes a correction with **no record** — the seal's gap becomes invisible |
| named `UNASSIGNED` | the gap stays visible: reported by `apply_family_corrections`, checked by the gate every run |

A gap that is **reported** is a finding. A gap that is **absorbed** is a quietly adjusted
interval.

### The two real seal gaps, and why the exemption list cannot rot

With `family_of` fixed, the gate found what it was for: **14 of 93** cases are placed in no
family (8 E, 3 O, 2 S, 1 X). For E/O/X that is correct — they have oracles and no p-values.
For the two **class-S** cases it is a genuine gap in the seal: **F10-1** (zero inference
charge when input is blocked, full charge when output is blocked) and **F10-3** (tagged RAG
prompts bill fewer text units than untagged) are statistical, and no correction is defined
for them.

This cannot be repaired. `meta.status: SEALED`, and `verify_prereg.py --seal` refuses to
re-stamp (DEV-SEAL-1). More to the point, it **should not** be: adding F10-1 to a BH family
*after discovering the gap* would be choosing a multiplicity rule in light of the data's
existence. So the gap is declared:

```python
DECLARED_SEAL_GAPS = frozenset({"F10-1", "F10-3"})
```

checked in **both directions**. An undeclared class-S gap fails the gate; a declared gap
that *closes* — the seal now places it, or its class changed — **also** fails the gate. That
second direction is the load-bearing one. A permanently-red gate gets worked around within a
week; a list that can only be added to becomes a blanket exemption. One that goes red the
moment a **twelfth** case joins the gap, or a listed one leaves it, still means something.

Carried into the report as **DEV-P1-3**: F10-1 and F10-3 are single hypotheses at the
nominal α = 0.05, uncorrected, and are reported as such rather than silently corrected.

### The honest limit in `lib/checkpoint.py`, recorded rather than papered over

One checkpoint mutant — deleting the `os.fsync` call — survived 46 arms, including a real
`SIGKILL` mid-write. It survived because **fsync's effect is not observable from
userspace**: SIGKILL does not drop the page cache, so a killed process loses nothing and the
file the kernel serves is already the new one. `fsync` protects against power loss or a
kernel panic between the write and the rename — neither of which a test can produce.

Two ways to reach 15/15 were available. Monkeypatching the write path to "prove durability"
would confirm the patch, not the code. So the arm asserts the **call order** —
`events == ["fsync", "replace"]` — and its own docstring states that this is weaker than
durability and why. A 15/15 obtained by weakening the claim is worth less than a 14/15 with
the fifteenth explained.

### Effect on the record

- `lib/oracle.py` gate: green, 93/93 cases placeable and each given an α.
- New tests: `test_oracle.py` **99** arms, `test_awsclients.py` **55**, `test_checkpoint.py`
  **47**. `lib/tests` collects **350** (was 149); suite total **664**
  (claims 276 + lib 350 + f5_redteam 38).
- Mutation runs, all clean: oracle **55/55**, awsclients **34/34**, checkpoint **15/15**.
- `verify_phase0.sh`: gate count **11 → 12** (the oracle gate). The `lib/tests` floor was
  **100 against 350 collected** — deleting all three new files, 201 arms, would have passed.
  Floors raised to 270/345/35, and the rule written into the script: raised per **file**, never
  per arm, so adding a test still never requires editing the list.
- Cost **$0** — every action offline. Cumulative project spend **$0.00**.

> Three defects, one shape: each was a place where the code and the seal agreed *in the part
> I had remembered*. The gate found none of them while its checks compared my derivations to
> each other; it found all three once they compared against the sealed file.

---

## DEV-P1-1 — F3-11 has no pre-registered n, and does not borrow one

**Class** `provenance` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** none — no n was set; the absence is recorded as a finding

`regression_cell.applies_to` names **only F6-8**. F3-11 (detection-drift re-runs at +7d and
+30d) therefore has **no pre-registered sample size**, and its binding carries `cell=None`
with the reason inline.

The tempting repair is to use F6-8's n = 200. It would be wrong: 200 was chosen for a
**latency** re-run, where the quantity is a p50/p90 shift, and applying it to a **detection**
re-run would attribute a latency design decision to a detection experiment. That is the same
label-vs-computation defect the document under test contains
(`feedback_label_must_match_computation`).

Consequence, pre-committed here rather than decided at analysis time: F3-11's `n_met` is
`True` by vacuity (there is no floor to miss), so a shortfall **cannot** block its amendment
the way it blocks others. F3-11 is therefore reported with its observed n stated and **no
claim that a pre-registered power target was met**. `PAIRED_IMPROVEMENT` also predicts only
that drift is detectable, not its direction — the direction is descriptive either way.

---

## DEV-P1-2 — "near 0" is not a number: F5-6's one operationalisation

**Class** `design` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** one threshold **supplied** where the seal supplies none. Documented here
because it is the only such threshold in the module.

F5-6's sealed oracle (DC-2, §3.2's untagged-detection claim) reads: §3.2 is TRUE only if the
untagged arm's recall upper bound is **"near 0"**, FALSE if untagged detection is
**"substantial"**. Neither is a number, and `UPPER_BELOW` needs one.

**Operationalisation:** one-sided upper bound **< 0.05** — the same 5% the pre-registration
already uses throughout for a negligible rate (`corpora` rule-of-three table: n = 60 buys
"under 5%"). It is implemented as a **named transform**, `near_zero_as_5pct`, rather than a
literal `0.05` in the threshold tuple, so that:

- the pinned prose token remains the sentence's own `0` — the gate still checks the binding
  against the seal, not against my choice;
- the substitution appears in the gate's output, where a literal would look like a number
  read out of the document;
- `prose_support_problems` **requires** any binding carrying a non-identity transform to say
  `OPERATIONALISATION` in its note, so this cannot be done silently again.

**Direction and prior.** `UPPER_BELOW`, because the document's claim is that detection does
**not** happen without tagging. The existing n=5 observation (5/5 detected untagged) predicts
this will be **REFUTED** — which is why the threshold is fixed now, in writing, before the
n≥60 arm runs. A 5% bound chosen after seeing the recall would be a threshold chosen from the
data.

---

## DEV-P1-3 — F10-1 and F10-3 are uncorrected single hypotheses

**Class** `analysis` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** none — no correction was applied, removed or changed; the seal defines none

The sealed `families` block places every case except fourteen. Eleven of those fourteen are
class E, O or X — correct, since they have oracles and no p-values. The remaining two are
class **S**:

| Case | Claim under test | Family in the seal |
|:---|:---|:---|
| F10-1 | input blocked → zero inference charge; output blocked → full charge (§7.1 principle 2) | none |
| F10-3 | tagged RAG prompts bill fewer text units than untagged | none |

Neither `members` nor `members_by_class` reaches them, so **no multiplicity correction is
defined**. The seal is SEALED and re-stamping is refused (DEV-SEAL-1); assigning a family now
would choose a multiplicity rule after the gap was known.

**What is done instead, stated before the data exists:** each is analysed as a **single
hypothesis at the nominal α = 0.05, uncorrected**, and the report says so in the same
sentence as the result. Two uncorrected tests at 0.05 carry a family-wise error rate of at
most 1 − 0.95² ≈ **9.75%**, and that figure is published with them rather than left for a
reader to compute.

Enforced, not remembered: `DECLARED_SEAL_GAPS` in `lib/oracle.py` fails Phase 0 if a
**twelfth** unplaced class-S case appears, and also if either of these two ever becomes
placeable — so the declaration cannot decay into a general exemption.
`apply_family_corrections` emits `uncorrected_p_values` and a `seal_gap` string for them, so
the gap travels with the results table instead of living only in this file.

---

## DEV-P1-4 — three Phase 1 rate cases have sealed oracles and no pre-registered n

**Class** `provenance` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** none — no n was set, borrowed or inferred; the absence is recorded and its
consequence for `n_met` is pre-committed here

The sealed `corpora` block has exactly eight keys — `content_filter`, `prompt_attack`, `pii`,
`benign`, `hard_negatives`, `multilingual`, `labelling`, `safety_handling` — and each Phase 1
case's `planned_n` is resolved through the sample-size **cell** its binding names.
Of the **18** Phase 1 cases, **9** resolve `planned_n` to `None` (project-wide the figure is 59
of 105, which is why the count alone diagnoses nothing). That set conflates two very different
situations and only one of them is a deviation:

**Not a deviation — the oracle takes no rate.** F8-4, F8-7, F8-8, F10-2 are `EXISTENCE`; F8-5 is
`BOUNDARY`; F3-9 is `ROC_LATTICE`. A trial count is the wrong instrument for all six: an
existence oracle is decided by one qualifying observation, a boundary oracle by the
accept/reject pair at the limit, and a vertex ceiling by the enum's cardinality (see
**DEV-P1-5**). There is no rate to power, so no power calculation was omitted. Note that the
sealed kind alone does **not** predict this — **F8-6 is `EXISTENCE` and carries n = 60** from
`multilingual_cell`, because its existence claim is about a *difference between two measured
rates*. So the classification below is per case, from what its oracle actually consumes, not
from its kind.

**The actual deviation — three cases estimate rates with no sealed floor:**

| Case | Kind | Sealed oracle subject | Why no cell reaches it |
|:---|:---|:---|:---|
| F3-5 | `DISJOINT_INTERVALS` | denied-topic recall vs off-topic FPR | no `topic` corpus key exists in the seal |
| F3-6 | `ZERO_EVENTS` | custom word filter is exact-match | no `word` corpus key exists in the seal |
| F3-7 | `DISJOINT_INTERVALS` | contextual grounding + relevance at 0.7 | no `grounding` corpus key exists in the seal |

All three compare or bound **proportions**, so for all three an n *would* have been meaningful
and none was sealed. F3-6 is the sharpest of the three: `ZERO_EVENTS` is decided by observing
no events, and a zero-count verdict is worth exactly what its n is worth — at n = 20 the
one-sided 95% ceiling is 13.9%, at n = 66 it is 4.4%. Reporting "no near-miss ever matched"
without its n would be the rule-of-three error the pre-registration's own §2 table exists to
prevent.

**Consequence, pre-committed:** for these three `n_met` is `True` **by vacuity** — there is no
floor to miss — so a shortfall cannot block their amendment the way it blocks a cell-bound case
such as F3-8 (n = 87 from `attack_recall_cell`). Each is therefore reported with its **observed
n stated** and **no claim that a pre-registered power target was met**. Intervals are still
computed and published (Wilson for F3-5/F3-7's rates, the one-sided exact ceiling for F3-6's
zero count); what is absent is the pre-commitment that the interval would be narrow enough, and
that absence is stated beside the number rather than left for a reader to infer from its width.

**Corpora provenance.** All three need test data the sealed corpora do not contain, so it lives
in a separate tree, `corpora_deviation/`, built by `corpora_deviation/build_deviation.py` and
never mixed into `corpora/`:

| Path | Items | Consumer |
|:---|---:|:---|
| `corpora_deviation/topic/{in_topic,off_topic}.jsonl` | 60 + 60 | F3-5 |
| `corpora_deviation/word_probe/probe.jsonl` | 66 | F3-6 |
| `corpora_deviation/grounding/{grounded,ungrounded}.jsonl` | 60 + 60 | F3-7 |

Separate trees rather than new files under `corpora/`, for one reason: `corpora/verify_corpora.py`
is a Phase 0 gate over the **sealed** corpora and `PREREGISTRATION.yaml` pins their counts. A
non-pre-registered file dropped into that tree would either break the gate or, worse, be
absorbed by it and thereafter look pre-registered. `corpora_deviation/` gets its own
reproducibility gate (`corpora_deviation/verify_deviation.py`) so it is rebuildable and
hash-checked without ever being able to claim the seal's authority.

F10-2 needs no corpus at all: its ladder is nine deterministic filler strings constructed in
the script from a fixed word pool, so the data is the code and is covered by the code's own
mutation tests.

---

## DEV-P1-5 — F3-9's ROC ceiling comes from the strength enum, not from the score lattice

**Class** `design` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** the sealed ceiling is **not** relaxed. The reachable maximum is *lower* than
the seal permits, and the reason is a property of the API

The pre-registration's worked example derives "at most 7 operating points" from a **6-point
score lattice** `𝒮 = {0, 0.2, 0.4, 0.6, 0.8, 1.0}` with a decision `D = 1[S > τ]`: six score
values admit seven placements of τ. F3-9's binding inherits the resulting `thresholds=(7.0,)`.

Bedrock content filters expose **no numeric score and no numeric threshold**. Verified against
the botocore 1.43.67 model rather than assumed:

- `contentPolicyConfig.filtersConfig[].inputStrength` / `outputStrength` are enums with **four**
  values — `NONE`, `LOW`, `MEDIUM`, `HIGH`.
- On the response side, `assessments[].contentPolicy.filters[]` exposes `confidence` and
  `filterStrength`, and **both are the same four-value enum**, not continuous scores.

So the operating points are not placements of a threshold on a score lattice; they are **four
configurations**, one guardrail per strength, evaluated over the same corpus. With the two
trivial endpoints (0,0) and (1,1) the polyline has at most **6** vertices.

**What this does and does not change.** The sealed oracle asks for ≤ 7 vertices; 6 satisfies
it, so no threshold is relaxed, moved or reinterpreted, and the verdict is computed against the
sealed number unchanged. What changes is the **meaning** of a passing verdict, and that is
reported with it: the ceiling holds because the API offers four knob settings, not because a
score distribution turned out to be coarse. A reader told only "≤ 7 vertices, satisfied" would
draw the second conclusion.

Two consequences carried into the analysis: the same corpus must be used at every strength (an
ROC assembled from different items per point measures the items), and trapezoidal AUC over
four interior points is downward-biased and stays a **secondary descriptor**, as the
pre-registration already requires.

---

## DEV-P1-6 — F3-8's sealed between-subtype comparison is not computable over disjoint corpora

**Class** `analysis` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** one sealed **secondary** analysis is replaced by a stated alternative; the
primary per-subtype oracle is computed exactly as sealed

F3-8's primary oracle is per-subtype recall — `LOWER_ABOVE` at 0.5, n = 87 per subtype from
`attack_recall_cell` — over JAILBREAK, PROMPT_INJECTION and PROMPT_LEAKAGE. That is computed
unchanged.

The pre-registration additionally names **pairwise McNemar** for between-subtype comparison.
McNemar is a **paired** test: it reads the discordant cells `b` and `c` of a 2×2 table over the
*same units* measured twice. The three subtypes are **disjoint corpora** — a JAILBREAK item and
a PROMPT_INJECTION item are different texts, not one text under two treatments — so there are
no matched pairs, and no pairing rule over them would be anything but an arbitrary alignment of
unrelated items. Running McNemar on the counts anyway would produce a p-value from a table
whose off-diagonal cells have no referent.

**What is done instead, pre-committed:** subtype recalls are compared by **non-overlap of
Wilson intervals** at the sealed α, reported as a descriptive comparison and explicitly **not**
as a hypothesis test. Where the intervals overlap, the finding is stated as "not distinguished
at this n" rather than as equality.

**Where McNemar is correct and IS used:** F5-6, whose four arms send the **same** attack items
untagged, with `guard_content`, via Converse without `guardContent`, and via Converse with
`guardContent` on a different block. Same units, four treatments, genuine pairs. The seal's
choice of test was right for the design it was written beside and was carried to F3-8, where
the corpora differ.

---

## DEV-P1-7 — F8-4's operationalisation is the script's, not the seal's

**Class** `design` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** one EXISTENCE oracle given a concrete decision procedure the seal does not
supply. No threshold is invented; the procedure is recorded before the data

F8-4's sealed binding is `EXISTENCE` with `thresholds=()` and `planned_n=None`: prompt-leakage
detection is a STANDARD-tier capability, absent on CLASSIC. An EXISTENCE oracle takes one
boolean and the seal does not say which observation produces it — so the script decides, and
the decision is written here rather than left implicit in code.

**Operationalisation.** TRUE iff, over the same `prompt_attack/prompt_leakage.jsonl` items:

1. the STANDARD-tier arm detects PROMPT_LEAKAGE on at least one item, **and**
2. the CLASSIC-tier arm detects it on **none**, **and**
3. both arms actually ran — each with `n_usable > 0` and the tier read back from
   `GetGuardrail.contentPolicy.tier.tierName`, not assumed from the manifest key.

Condition 3 is the load-bearing one. Without it, "CLASSIC detected nothing" is produced
equally by a capability gap and by an arm that never reached the service, and those have
opposite conclusions. A failure of 3 routes to INCONCLUSIVE via `O.not_measured`, never to
TRUE.

**What TRUE does not license:** a one-sided existence claim. Detection on one item establishes
the capability exists on STANDARD; **zero** detections on CLASSIC across n items bounds the
CLASSIC rate at the one-sided exact ceiling for that n and does **not** establish absence. The
payload reports the ceiling with the verdict, and the report says "not observed at this n"
rather than "cannot".

The `InvokeGuardrailChecks` half of the same doc sentence is a separate surface with its own
`promptAttack` safeguard, counted separately in F8-4's operation breakdown for the reason
`dry_run_banner` now enforces: a total spanning two operations must not be labelled with one.

---

## DEV-P1-8 — `obs_recorded` on an EXISTENCE or BOUNDARY case crashes on the path it exists to protect

**Class** `design` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** a repair to `lib/oracle.py` (an **addition**, `not_measured`; no existing
verdict logic changed) plus a corrected branch in four case scripts

**The defect.** `oracle._decide` dispatches on `BINDINGS[case_id].kind` — the **sealed** kind —
and never on the shape of the observation handed to it. That is correct and deliberate: it is
what stops a script choosing its own oracle. But three case scripts had a legitimate need for
which they reached for `phase1.obs_recorded(...)`: a **precondition failure discovered before
any data exists**.

- **F8-5** discovers that botocore now enforces the topic-definition maximum client-side, so an
  over-length probe never reaches the service and "rejected" would mean "the SDK refused".
- **F8-6** discovers that `crossRegionDetails` is absent, so the guardrail under test is not
  cross-Region at all.
- **F8-7** discovers that a probe guardrail never reached READY, or that the tier did not read
  back.

Each passed an observation carrying only a `detail` dict into a case sealed as EXISTENCE or
BOUNDARY. `_decide` therefore reached that kind's `_need(observed_bool)` /
`_need(at_limit_ok, over_limit_rejected)` and raised `ValueError`. `_need` was working
correctly — it was refusing to manufacture a verdict from absent observations. The bug was the
call site: **two shipped branches would have crashed on exactly the path they were written to
protect**, and they would have crashed *after* the money was spent.

**Why it was invisible.** The branches are the unlikely ones. Every dry run, every `--n 3`
smoke and every honest full run takes the other path, so no amount of ordinary exercise reaches
them. They were found by re-reading the code, not by running it.

**The repair.** `O.not_measured(case_id, reason, **detail)` builds an **INCONCLUSIVE** record
in `evaluate`'s shape, so `emit` and `amendment_blockers` — which both read `verdict`, `n_met`,
`planned_n` and `mutation_required` — receive every field they consume. It:

- **refuses an empty reason** (`ValueError`), because an INCONCLUSIVE with no stated cause is
  indistinguishable from a straddling interval and the two have opposite remedies — one is
  fixed by collecting more data, the other by repairing the instrument;
- sets `n_met = (planned_n is None)`, so a case with a sealed n cannot be recorded as having
  met it while measuring nothing;
- sets `mutation_inverted = None` where mutation is mandatory, so the mutation requirement
  stays unsatisfied rather than being vacuously passed.

**Why not RECORDED.** RECORDED means *the pre-registration declared this outcome unknown and
both answers are findings*. It is a property of the **seal** — `F10-1` and `F10-3` carry it via
`unassigned_by_seal`, and `O.DECLARED_SEAL_GAPS` pins them. A script cannot grant itself
RECORDED any more than it can grant itself a threshold; that would let any case downgrade its
own falsifiability at run time by discovering an inconvenience.

**Citing sites** (four, all on the precondition branch): `f8_regional/04_topic_limits.py`,
`f8_regional/05_xregion.py`, `f8_regional/06_word_language.py`, `f10_billing/01_text_units.py`.
Gated, not remembered: `lib/tests/test_oracle.py` asserts that `not_measured` refuses an empty
reason and returns INCONCLUSIVE — not RECORDED — for a BOUNDARY and an EXISTENCE case, and that
the ValueError the old call site would have raised is still raised by
`evaluate(obs_recorded(...))` on those kinds. The trap remains; only the call sites moved.

---

## DEV-P1-9 — the managed PROFANITY list is out of scope for F8-7, and why that is not a corpus gap

**Class** `design` · **Date** 2026-08-10 · **Data existed** no · **Cost** $0
**design_impact** one mechanism excluded from one case's scope, with the scope stated in the
verdict rather than left to a reader to infer

`wordPolicyConfig` has exactly two members — `wordsConfig` (custom terms) and
`managedWordListsConfig`, whose `type` enum holds exactly one value, `PROFANITY`. F8-7 asks
whether word filtering is inert in non-EN/FR/ES languages. It tests **`wordsConfig` only**.

**Why the managed list is excluded.** Testing it requires profanity in each of six unsupported
languages, and that corpus could only be **self-authored and self-labelled**. Every other
corpus in this project carries a written labelling protocol and Cohen's κ ≥ 0.80 over two
annotators (κ = 0.9593 measured across 1,917 items). A single-annotator profanity list has **no
κ by construction** — there is no second annotator, so inter-rater reliability is undefined,
not merely low. Its "unsupported-language" labels would rest entirely on my own judgement about
languages, and a null result would then be unattributable between three explanations: the
filter is inert, my terms are not actually profane in that language, or AWS's list simply does
not contain the specific terms I chose. The third alone makes the arm uninformative even if it
runs perfectly.

There is a second, independent reason to leave it: a managed-list null is unfalsifiable without
a positive control, and a positive control requires knowing AWS's list membership, which is not
published. F8-7's custom-word arm has a positive control by construction — we provisioned the
list, so `moonquake` in English is a term we know is on it, and its blocking proves the
instrument works before any non-detection is interpreted.

**What is claimed instead.** F8-7's verdict is scoped in its own oracle text and payload to
**custom word filters**, and the payload names the managed list as untested with this reason.
`mechanism_under_test` is a payload key, not a comment, so the scope travels with the result.
A reader who needs the managed-list answer is told it is absent and why, which per
`EXCLUSION_REGISTER.md`'s standing argument is more credible than a κ-less arm reported as
coverage.

Related surfaces recorded while F8-7 was built, none of them deviations from the seal but all
of them absences the document does not mention:

- **`wordPolicyConfig` has no `tierConfig`.** The tier knob exists on `contentPolicyConfig` and
  `topicPolicyConfig` and nowhere else, and `GetGuardrail.wordPolicy` has members
  `['words', 'managedWordLists']` with no `tier`. So a word-filter × tier comparison cannot set
  the tier on the policy under test. F8-7 carries the tier on a `contentPolicyConfig` holding a
  single deliberately inert `VIOLENCE` filter (all strengths and actions `NONE`, both
  `Enabled` false) and reads it back off `contentPolicy.tier.tierName`. A **tier-only** content
  policy is rejected client-side because `filtersConfig` has `min=1`, which is why the carrier
  filter exists at all. Recorded because §3.4's tier discussion reads as though the tier were a
  guardrail-level setting.
- **F8-8 has no request surface to test.** No field in any of the 24 AutomatedReasoning
  operations names a language, locale or mode (251 input members swept, 4 regex matches, all
  four being `addRuleFromNaturalLanguage` authoring parameters), and no enum in either service
  model carries a `DETECT`/`ENFORCE` value (**120** enums swept — 75 in `bedrock`, 45 in
  `bedrock-runtime`; the per-model 75 is what the version comparison below is denominated
  in, and quoting it as the sweep total would understate the sweep by 45). FALSE is
  therefore unreachable
  **by construction** — acceptance would require a request, and there is no field in which to
  build one — so TRUE records the honest reading "refused by the SDK before serialisation: we
  sent nothing." The sweep runs under the **pinned** interpreter (`.venv-oracle`, botocore
  1.43.67) because the case's whole content is which fields *that* SDK exposes; since
  `.venv-oracle` has no scipy and cannot import `lib/oracle.py`, the sweep was extracted into
  `lib/ar_surface.py` (stdlib + botocore only) and is run as a subprocess. The difference is
  measured, not assumed: 108 vs 98 bedrock operations, 251 vs 244 members, 75 vs 72 enums
  between 1.43.67 and the ambient 1.42.79. Deciding from whatever botocore happened to be
  ambient would answer a question about pip and report it as a fact about AWS.
- **F8-5 depends on a botocore internal.** `botocore.validate.range_check` has only a `min`
  branch and `_validate_string` performs no length check, which is *why* an over-length topic
  definition reaches the service and the boundary verdict is the server's. F8-5 re-runs that
  check live each time and routes to INCONCLUSIVE if a future botocore adds the `max` branch —
  otherwise every "rejected" would become a client-side rejection reported as a service
  boundary.

---

## DEV-SEAL-13 — the first block lifted by evidence, and two vacuous tests it exposed

**Class** `provenance` · **Date** 2026-08-10 · **Cost** $0
**Hash before** `a2136a9d3dbb2288…` · **Hash after** `a2136a9d3dbb2288…` (unchanged)
**design_impact** none — no hypothesis, n, threshold, family or oracle changed. One
finding's status moved from `OBSERVATIONS_COMPLETE` to `READY_TO_AMEND` because the
condition it declared was met.

### What happened

DEV-SEAL-8 sealed the two-calendar-day rule; DEV-SEAL-10 recorded a same-day repeat being
caught by it. `f5_redteam/07a_run_day2.sh` ran at **2026-08-10T00:11:15Z**, took its
"UTC today already differs from day 1" branch (no sleep needed — the wait had already
elapsed), collected `r20260810T001115Z`, and `07a_compare_runs.py` compared it to
`r20260809T094500Z`:

```
75 field(s) compared
REPLICATED — every observation the §4.5.3 amendment quotes was identical on two
separate calendar days
```

So `FINDING-F5-7A` is now `READY_TO_AMEND` and `V13-03` is `MEASURED_READY`. **This is the
first time in the project that a gate said no and was later satisfied rather than
relaxed.** That distinction is the point of DEV-SEAL-8: a rule whose only outcome is
refusal gets bypassed, and one whose refusal can be discharged by work does not need to be.

### A scheduled job raced my manual one, and the tie-break rule matters more than the tie

DEV-SEAL-10 had **pre-registered an unattended day-2 run for 2026-08-10T00:20Z**. I ran
the driver by hand at 00:11:15Z; the scheduled job then fired at **00:20:01Z** on its own
timer, 8 min 46 s later, collected `r20260810T002001Z`, replicated 75/75 independently,
and — being the later writer — **overwrote `results/f5_7a_replication.json`** so the
verdict file named the scheduled run while the finding, this entry and
`test_behavior_changes.py` all still named mine. Three artifacts disagreeing about which
run a claim rests on is not cosmetic: it is the provenance defect
`feedback_provenance_stamp_liveness` names, a recorded input with two defensible readings.

Both runs are kept. Deleting the loser would leave a tidy record of a thing that did not
happen, and DEV-SEAL-10's own rule is that *a repeat which agrees is weak evidence, but a
repeat relabelled as a replication is false evidence.* Every field agrees across the two
(16 calls × 200, the same 6 CDX snapshots, the same 4 reading `Not yet supported`), so no
finding turns on the choice.

**`r20260810T002001Z` is canonical on one ground: it was fixed in DEV-SEAL-10 before any
day-2 result existed.** The selection rule therefore predates the data. Choosing my own
run instead would have been defensible on the merits and indefensible in form — the
selection would have been made with both results already in hand, and nothing in the
artifact would let a reader tell the difference between "the earlier run" and "the run I
preferred once I saw it". This is the same asymmetry as pre-registration itself, applied
to a two-element choice.

Comparing the two day-2 runs **to each other** returns NOT REPLICATED — *"both runs were
collected on 2026-08-10"* — while still reporting 75 fields compared and 0 substantive
disagreements. The comparator is right: they are a same-day repeat of one another, which
is precisely the state the sealed rule exists to reject. `atq`, `crontab -l`,
`launchctl list`, `CronList` and `ps` all show nothing further pending, so the job has
completed and will not recur.

**The generalizable defect is in the driver, not the record.** `07a_run_day2.sh` has no
"a day-2 run already exists" guard, so a manual invocation and a scheduled one can both
satisfy the same requirement and then compete to write one verdict file. Logged as W-06 on
the watch list; the fix is for the driver to refuse when a run for the target UTC day is
already on disk unless `--force` is passed, which keeps a deliberate repeat possible while
making an accidental one loud.

### Two differences the comparator tolerated, and why that is not laxity

(These held identically for both day-2 runs.) The Internet Archive returned **8**
snapshots on day 1 and **6** on day 2
(`20251230114157` and `20260623161005` absent the second time). That is a query against a
third-party index returning a different result set — not an observation about AWS — so it
is a *note*. What the comparator does insist on is that the **6 snapshots present both
days parse identically**, because an archived page is immutable: a differing archived row
would mean one of the two parses is wrong and would discredit instrument B entirely,
which is a strictly worse outcome than a disagreement about AWS.

### What replication did NOT establish, stated in the finding

Two reads of a documentation page cannot test the service behind it. The
alternative-explanation register's row *"'Supported' on AWS's page overstates reality"*
remains **not excluded**, and replication does not touch it. So the amendment wording was
changed from *supports* to **documents**:

> as of 2026-08-10 AWS **documents** all primitives as supported on both planes, verified
> on two calendar days; verify against the live table before designing a closed loop

Getting this wrong would have been the DEV-P0-8 shape again — using evidence about one
level (what the page says) to license a claim at another (what the service does).

### Two vacuous tests the promotion exposed

Promoting the status made two existing arms stop testing what their names claim. Both were
green throughout, and both would have stayed green through a broken gate.

1. **`test_no_candidate_may_be_measured_ready_before_two_days`** accepted
   `"REPLICATION" in f.upper() or "offline" in f or "$0" in f`. **Every** finding in the
   tree contains `$0` — the cost line is in the header of all seven — so the assertion was
   true by construction and would have waved through a `MEASURED_READY` promoted on one
   day's data. It now re-derives the calendar days from `t_start_utc` in the declared
   runs, the same way the gate does, and asserts that at least one candidate is
   `MEASURED_READY` so the loop cannot pass by iterating over nothing
   (`feedback_vacuous_test_check`, `feedback_prose_is_not_verified`).
2. **Three arms in `test_amendment_gate.py`** got their single-day-ness from whatever
   F5-7A happened to declare, rather than setting it. The moment the finding became
   two-day, `test_kills_a_single_day_amendment` — the arm that file exists for — would
   have been asserting against a two-day finding and could have passed against a gate that
   had stopped counting days altogether. They now pin `evidence_runs` explicitly via a
   `single_day()` helper, and a new control arm asserts the *complement*: that the real,
   unmutated provenance passes as amendable with `2 day(s) ['2026-08-09', '2026-08-10']`.
   Without that control, every arm in the file could be satisfied by a gate that refuses
   all amendments unconditionally.

The generalizable form: **a mutation test whose mutation is "leave the artifact as it is"
expires when the artifact changes**, and it expires silently, in the direction of passing.

### Effect on the record

- `results/FINDING-F5-7A.md` → `READY_TO_AMEND`; §7 rewritten from "why no amendment yet"
  to the replication table plus what it does and does not license. `blocked_on` renamed
  `was_blocked_on` so the discharged condition stays legible while the gate's
  deferred-status branch no longer matches it.
- `V13-03` → `MEASURED_READY`; `V13_CANDIDATES.md` regenerated (9 candidates, 62 sites).
- §4.5.3 itself is still **not** edited: amendment is Phase 9, and it lands in both
  `.md` and `.zh-TW.md` in the same change.
- Cost **$0**. 16 unmetered `DescribeVpcEndpointServices` calls and 9 HTTP GETs.
  Cumulative project spend remains **$0.00**.

---

## DEV-P1-10 — a `--n` head is the wrong sample for a case that splits strata afterwards

**Class** `harness-defect` · **Date** 2026-08-10 · **Data existed** partially (24 smoke
calls, discarded) · **Cost** $0 (ApplyGuardrail on 24 short items; the smoke run was
re-executed after the fix and no measured result rests on either)
**design_impact** none on any full run — the sampler's behaviour at `limit=None` is
unchanged and byte-identical, verified by a dedicated arm and a mutant

### What happened

F8-2/F8-3's `--n 3` smoke aborted with `ValueError: n must be positive, got 0`, raised
inside `lib/stats.wilson_ci` by way of `lib/oracle._decide`'s `INDISTINGUISHABLE` branch —
**after** 24 billable `ApplyGuardrail` calls had been made, and with every collected row
lost to the traceback.

The cause was not in the statistics. `lib/arms.load_corpus(limit=n)` returned a **head** of
the file, and `corpora/multilingual/<lang>.jsonl` lists its 54 labelled attacks first and
its 6 `CLEAN` items **last, at positions 54-59**. So `limit=3` returned three `JAILBREAK`
items and no `CLEAN` one. F8-2 then splits that arm's rows into attacks and CLEAN and
compares the two rates — its FPR side was `0/0`.

### Why nothing upstream caught it

`obs_intervals` sets `n_usable = detect_n + fpr_n`. With `detect_n=60, fpr_n=0` the
observation reports `n_usable=60`: `require_measured` sees a healthy run, and `n_met` would
be **satisfied** against the sealed `multilingual_cell` n of 60. Every check phrased on the
total is blind to an empty stratum by construction, which is why the guard could not live
upstream and is now in the branch that consumes the two denominators.

### Two fixes, at two different levels, deliberately

1. **The sampler (prevention).** `load_corpus` gained `stratify_by`. With
   `stratify_by="label"` the head is taken within each stratum in first-appearance order,
   so any label present in the file is present in the subset. The properties that made a
   head correct in the first place are preserved: deterministic, no seed, identical between
   `--dry-run` and the real run, and a *stated* subset ("the first n of each label"). A
   stratum smaller than `limit` contributes all of itself and does **not** borrow from
   another to reach n — borrowing would silently reweight the very comparison the case
   makes. `limit=None` returns the file untouched, so **no full run's item set or order
   changes**; a smoke-path fix that altered published rates would be a worse defect than
   the one it fixed, and there is an arm and a mutant for exactly that.
2. **The oracle (backstop).** `DISJOINT_INTERVALS` and `INDISTINGUISHABLE` now return
   INCONCLUSIVE, naming the empty side, when either denominator is zero. The stats layer's
   refusal is *correct* — a Wilson interval on n=0 does not exist, and returning one would
   be the vacuous-value defect one level down — but a traceback is not a record. This is
   the same reasoning as `not_measured` (DEV-P1-8): an unsound instrument yields no
   verdict, not a convenient one. Both kinds are guarded, not just the one that failed, so
   F3-5, F3-7 and F5-5 are covered too.

The sampler alone would have sufficed to make the smoke run pass, and that is precisely why
the oracle guard is also there: the assumption that failed was "the corpus is laid out the
way I expect", and a fix resting on a second layout assumption would be the same bet.

### Effect on the record

- No verdict, rate or interval changes. The only affected data was a smoke run, which by
  the pre-registration is never reported as a result (`is_smoke` travels in the checkpoint
  metadata for this reason).
- `f8_regional/02_multilingual.py`'s `plan()` was updated in the same change, so the dry
  run projects the sampling the real run performs — an unstratified projection would have
  under-reported the smoke call count by a factor of the label count (8n, not n).
- Coverage added: 5 arms in `lib/tests/test_arms.py` (including one against the **sealed**
  corpora, not a fixture, asserting all 7 multilingual files need stratification at every
  plausible smoke n) and 8 in `lib/tests/test_oracle.py` (both kinds × three empty-stratum
  shapes, plus the arm that pins *why* `n_usable` cannot catch it). **11/11 mutants
  killed**, including "stratify_by silently ignored" and "guard returns TRUE".
- Cost **$0.00** — the 24 discarded calls were on short items and unbilled at this scale;
  cumulative project spend remains **$0.00**.

---

## DEV-P1-11 — a 74-second network outage published verdicts from 3% of the sample at rc=0

**Class** `harness-defect` · **Date** 2026-08-10 · **Data existed** yes (one full Phase 1
run, **invalidated by this entry**) · **Cost** $0.00 (the lost calls never reached the
service; cumulative project spend remains **$0.00**)
**design_impact** none — no n, threshold, family or oracle changes. What changes is the exit
code a run produces when it fails to collect its designed sample, and one published run is
withdrawn.

### What happened

The first full Phase 1 run (`r20260810T0345Z`) exited **rc=0** for all six F3 scripts and
wrote verdicts. `results/phase1/F3-1.json` records **TRUE** — computed from **15 usable
trials against a pre-registered 87**, three per category. F3-2 and F3-3 reached INCONCLUSIVE
from **3** apiece, and F3-8 from **9** against 87.

The cause was environmental. From the evidence tree (4,040 records carrying `t_start_utc`):

| | count |
|:---|---:|
| `EndpointConnectionError` | **3,388** |
| successes | 636 |
| `ValidationException` (oracle answers, expected) | 8 |
| `ThrottlingException` | 6 |
| `ReadTimeoutError` | 2 |

**3,378 of those 3,388 connection failures fall inside one 74.2-second window**
(03:02:15.474Z – 03:03:29.657Z), and that window contains **zero** successes. Their median
duration is **4.04 ms** (p99 17.65 ms, max 215.83 ms) — a socket that never connected, not a
service that answered slowly. 569 successes precede the window and 67 follow it; a
40-call burst issued afterwards returned ok=40/err=0 in 20.5 s and DNS resolved normally.
A separate 10-error episode at 01:26 has the same signature. So: **local network, not the
service** — and 74 s is well inside what the existing 3-attempt / 5 s-linear retry policy
absorbs.

### Why the retries did not run

`lib/checkpoint.is_retryable` is an allowlist, deliberately: an unrecognised exception is
classified permanent so a harness bug surfaces as a failure rather than as three slow
failures reading like service flakiness. **An allowlist only works if every live failure mode
is on it, and a mode that arrives stripped of its identity is off the list by construction.**

`lib/evidence.capture` absorbs the exception by design — errors are *data* here, since half
this project's oracles are `AccessDenied` — so what arms actually raise is
`CapturedCallError` from `raise_for_status`. A connection-level failure never got an HTTP
response, so it carries **no AWS error code**: `error_code=""`. `is_retryable`'s `wrapped`
branch tests `if isinstance(wrapped, str) and wrapped:`, which an empty string fails, so the
function fell through to `return False`. Measured directly at the time: the wrapper → `False`,
a raw botocore `EndpointConnectionError` → `True`, and `error_code()` → `"CapturedCallError"`
— the cause was lost as well as the retry.

This is the **second** instance of exactly the seam the `CapturedCallError` docstring already
documents: the first was a `ThrottlingException` reaching the same function as a wrapper,
repaired by adding the `wrapped` branch. That repair honoured a code that *existed*; it did
not consider a wrapper with no code at all.

### Why rc=0 is the more serious of the two defects

The outage is environmental and would recur under any harness. **A run that publishes
verdicts from 3% of its designed sample and exits clean is a defect that would recur on
every future phase.**

Nothing lied. `n_usable=15`, `n_met=False`, `failure_codes` and a note saying the interval
was wider than the design promised were all recorded faithfully, and `amendment_blockers`
listed the shortfall. But **a shortfall reported beside a verdict is a verdict**: `rc=0` is
the signal a batch driver reads, and a downstream analysis keyed on the exit code would have
consumed those numbers as finished work. `require_measured`'s only condition was
`n_usable > 0`, which catches the case where *nothing at all* survived and nothing else —
and the pre-registered n is a **precision commitment**, so a run keeping 3% of it has not
produced a measurement with a wide interval, it has failed.

### Three fixes

1. **`error_code()` consults `error_class`** between the wrapped code and the class-name
   fallback, so `failure_codes` names `EndpointConnectionError` rather than
   `CapturedCallError`. It is the transport-level name the same wrapper already carries, and
   the only place the cause survives.
2. **`is_retryable` judges a code-less wrapper on its `error_class`**, against a hoisted
   `RETRYABLE_TRANSPORT` set shared by the raw-botocore and wrapper paths — one set, because
   two sets for the same event reaching one module by two paths is a pair that will diverge.
   The allowlist discipline is unchanged: `ValidationException` and unknown classes stay
   permanent.
3. **`require_measured` gained a completion floor.** `MIN_COMPLETION = 0.90`, checked **per
   arm**, returning rc=2 with the offending arms named, their failure codes, and the resume
   command. 0.90 rather than 1.00 because a handful of throttles is a normal cost of a
   2,190-call arm and aborting on one would make every long run hostage to a hiccup; rather
   than 0.50 because at 0.90 an 87-item cell keeps ≥ 79, holding the rule-of-three bound near
   where the seal put it. `--n` smoke runs are exempt from the *floor* (a 3-item arm losing
   one trial is 67% and smoke exists to prove plumbing) but **not** from the original zero
   check.

### Effect on the record

- **`r20260810T0345Z` is withdrawn.** No verdict from it is reported. Its checkpoints are
  intact, so re-running the same `--run-id` resumes only the missing trials and re-bills
  nothing.
- Under the new gate that run exits **rc=2**: F3-1 at 15/87 = 17%, F3-2 at 3/110 = 3%.
- Coverage added: **9 arms** in `lib/tests/test_checkpoint.py` (the transport wrapper built by
  pushing a real botocore `EndpointConnectionError` through the real `capture()` /
  `raise_for_status()` path, per `feedback_verify_against_real_artifact` — a stand-in with the
  attributes I *expected* would have confirmed the assumption that was wrong) and **15** in
  the new `lib/tests/test_require_measured.py`. **7/7** and **13/13** mutants killed.
- A **`pooled < min_completion` guard was written and then removed as vacuous.** The mutation
  run found it: deleting it changed no result. With `f_i = u_i/a_i` and weights `a_i`,
  `pooled = Σ(a_i·f_i)/Σa_i` is a weighted mean of the per-arm fractions, so
  `all(f_i ≥ t) ⇒ pooled ≥ t` — it could only fire where the per-arm loop had already fired.
  Confirmed by exhaustive search over arm compositions (minimum pooled fraction found:
  exactly 0.900, never below). The pooled figure stays in the message as *reporting*, and an
  arm now pins the implication so weakening the per-arm loop fails there and says the pooled
  guard must come back (`feedback_vacuous_test_check`).
- **The mutation harness itself gained a baseline assert.** Twice in this project a mutation
  run reported a perfect kill score while the tree was broken: a collection error fails every
  mutant, so "killed" measured nothing. A run whose unmutated suite does not pass now aborts.
- **`verify_phase0.sh` gained a compile gate** running before every suite: three times I
  inserted prose after a docstring's closing `"""`, and a `SyntaxError` in a module no suite
  imports — a case script — would not have surfaced until a live run had spent money on it.
  The file count is floored at 70 (77 present) because a compile gate that finds no files
  passes loudest of all (`feedback_zero_file_scan_is_error`).

---

## DEV-P1-12 — a published shortfall sentence whose numbers were right and whose claim was false

**Class** `harness-defect` · **Date** 2026-08-10 · **Data existed** yes (the same withdrawn
run) · **Cost** $0.00
**design_impact** none — reporting only; no verdict, `n_met` value, rate or interval changes.

### What happened

`results/phase1/F3-4.json` published this amendment blocker:

> `n_usable=93 is below the pre-registered 11`

Every number in it is correct. The sentence it forms is false: 93 is not below 11.

F3-4's and F3-8's sealed n is **per stratum** — 11 per PII entity, 120 per prompt-attack
subtype — because both oracles are universally quantified over strata. Both scripts therefore
override the case-level `n_met` with the AND over strata, correctly. What they did not do was
tell the rest of the record: `oracle.amendment_blockers` composes its text from
`rec["n_usable"]` and `rec["planned_n"]`, joining a **pooled** numerator to a **per-stratum**
denominator. `evaluate`'s own shortfall note has the same origin and is written *before* any
override runs, so F3-8's record carried it too — two incompatible statements about one field,
leaving a reader to pick.

This is `feedback_label_must_match_computation` at the blocker layer: a figure labelled with
a computation that did not produce it.

### Why it matters more than a wording slip

**The shortfall was real.** Some strata genuinely had n=3 against a sealed 11. A reader who
checks 93 against 11, finds nonsense, and concludes the blocker is a bug has dismissed a true
blocker — and this is the layer that stands between a verdict and an amendment to the document
under test. A message a reader can disprove by arithmetic is worse than no message.

### The fix

`phase1.apply_rollup_n_met(rec, roll, unit=...)` performs the override **and records its
basis**: `n_met_basis` (the sentence a reader should see, naming the per-unit n, the stratum
count and which strata are short), `n_met_strata_short` (the list), and it **removes**
`evaluate`'s stale pooled note rather than leaving it alongside. `amendment_blockers` prefers
`n_met_basis` when present and falls back to the plain sentence otherwise, so ordinary
per-case shortfalls — F3-1's `n_usable=15 is below the pre-registered 87` — are unchanged.

### Effect on the record

- No verdict, `n_met` value, rate or interval changes. F3-4 was `n_met=False` before and
  after; only the sentence explaining it changed.
- Coverage added: **4 arms** in `lib/tests/test_oracle.py`, including one reproducing the
  exact published shape (31 entities, 2 short, 93 pooled) and asserting the false sentence is
  **not reconstructible** from the message; one pinning that the stale note is removed rather
  than supplemented; the satisfied branch, so `n_met_basis` cannot be a constant refusal
  string; and one pinning that a non-roll-up case still gets the plain sentence.

---

## DEV-P1-13 — the account ID reached `results/` in 82 files, because nothing masked it on the way out

**Class** `harness-defect` · **Date** 2026-08-10 · **Data existed** yes (the withdrawn run
`r20260810T0345Z` and the smoke runs before it) · **Cost** $0.00
**design_impact** none — no verdict, `n_met` value, rate, interval or Region reading changes.
Verified by test that the fields F8-6 measures are bit-identical before and after masking.

### What happened

The redaction gate failed with **1,148 findings across 82 files** under `results/`. The
management account ID appeared in **1,122** of them. Two shapes carried it:

| Source | Field | Reaches |
|:---|:---|:---|
| `ApplyGuardrail` → `assessments[].appliedGuardrailDetails` | `guardrailArn` | every row of every arm |
| `GetGuardrail` → `crossRegionDetails` | `guardrailProfileArn` | F8-6's record |

The remaining 26 findings were shape collisions, and each was verified rather than assumed:
**13** corpus item ids that are 12 hex characters and happen to be all digits (observed 13 of
2,823 = 0.46%, against `(10/16)^12` expected), **4** UUID `request_id`s whose last group is
all digits, **3** AWS-published example access keys echoed from the PII corpus as `slot`, and
**6** synthetic 12-digit PII fixtures. Zero findings were unexplained.

### Why the obvious fix was the wrong one

The two named files could have been hand-edited in a minute. That is precisely
`feedback_second_instance_bugs`: the leak is not *in* the files, it is in the **path that
writes them**, and every future run — Phases 2 through 8 — re-creates it. It would also have
been invisible, since a hand edit leaves no gate behind.

Nor could the answer be "stop recording the ARN". `appliedGuardrailDetails.guardrailArn` **is
F8-6's entire instrument**: the Region that served the evaluation is read out of the ARN's
4th field. Dropping it would delete a measurement to satisfy a redaction rule.

### The fix

`lib/redact.py` masks the **account field only**, in place, preserving field positions:
partition, service, Region, resource type and resource id all survive and only field 4 becomes
`<account>`. Applied at the **two writers into `results/`** — `Checkpoint.save()` and
`phase1.emit()` — not at the call sites that read an ARN today, so a case added later inherits
it without knowing it exists.

Three properties make this safe to do to evidence, and all three are asserted:

1. **Positions do not move.** A mask that *deleted* the field would shift the Region into the
   account slot and silently re-label every trial's serving Region — a redaction fix that
   corrupts the measurement it protects. Asserted through F8-6's own `region_of`/
   `partition_of`, not a local copy of them.
2. **Only ARN account fields change.** A blanket `\b\d{12}\b` substitution would rewrite PII
   corpus fixtures on their way into a checkpoint — a US_BANK_ACCOUNT_NUMBER *is* a 12-digit
   number — changing results rather than redacting them.
3. **`evidence/` is deliberately NOT masked.** It is the local audit archive whose purpose is
   that a claim can be quoted to AWS Support by request id and full ARN. `results/` is the
   distributable copy. Both directions are asserted, so a later "consistency" cleanup cannot
   quietly mask the audit trail.

The in-memory record also keeps the true ARN — masking happens on the way to disk — so the
analysis still reads what the service actually returned.

### Two gate defects found while fixing this, both real

- **The gate's docstring contradicted its own `SKIP_DIRS`**, claiming to scan "JSON evidence"
  while excluding `evidence/`. A contradiction like that gets resolved later in whichever
  direction is cheaper at the time. The exclusion is now written down as a *decision* with its
  reason.
- **The `corpora/banks.py` waiver was scoped to one site of a value that legitimately reaches
  many.** A PII corpus exists to be *sent*, so its fixtures come back on every result row. The
  excuse is now **derived** from verbatim membership in a sha256-sealed corpus file rather than
  listed by hand: the set of excusable values cannot be widened by editing the gate, only by
  committing a value into a sealed corpus and re-sealing — a visible, gated act. A token in an
  ARN's account field is never excused, whatever else it matches.

### Effect on the record

- No verdict, rate, interval or Region reading changes; 82 files were re-written through the
  same masking function and re-validated as JSON.
- **The 589 waivers did not blind the gate**, which is the risk a waiver count that size
  carries. Verified by 8 probe mutations — raw account ID in an ARN, bare account ID, a real
  ARN beside a masked one, an unsealed 12-digit, a member account ID, an S3 URI, a
  non-corpus access key, a private IP — **8/8 caught**, clean baseline before and after.
- Coverage added: **17 arms** in `lib/tests/test_redact.py`, **6/6 mutants killed** (delete
  the field instead of replacing it; broaden to any 12-digit run; either writer stops masking;
  the evidence copy gets masked too; the structural walk mutates its input).
- `verify_phase0.sh`'s `lib/tests` floor raised 501 → 518.

---

## DEV-P1-14 — adding a module made an existing test a name-squatter, and only the combined suite could see it

**Class:** infrastructure defect (test harness) · **design_impact:** none · **Found:** 2026-08-10
**Cost:** $0.00 (offline)

### What happened

DEV-P1-13 added `lib/redact.py`. The tree's per-directory suites all still passed. The
**combined** suite — the one `verify_phase0.sh` actually gates on — failed with

```
AttributeError: module 'redact' has no attribute 'mask_text'
AttributeError: module 'redact' has no attribute 'ACCOUNT_PLACEHOLDER'
```

repeated about twenty times, naming neither file responsible.

### Root cause

`claims/tests/test_redaction_gate.py` loads `check_redaction.py` by path, because a
top-level script is not an importable package member:

```python
spec = importlib.util.spec_from_file_location("redact", SRC)   # the defect
mod  = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod                                   # registered BEFORE exec
spec.loader.exec_module(mod)
```

The registered name was free when it was written; nothing owned `redact`. `lib/redact.py`
then took it, and two distinct failures followed from that one string:

1. **Shadowing.** `sys.modules` is consulted before `sys.path`, so every consumer of the
   real module in the same process — `lib/checkpoint.py`, `lib/phase1.py`,
   `lib/tests/test_redact.py` — resolved `import redact` to a by-path copy of
   *check_redaction.py*.
2. **A half-initialized import.** `check_redaction.py` itself now does
   `import redact as _redact`. Because the loader registers the module *before* calling
   `exec_module`, that import bound the module that was mid-load — a module importing an
   unfinished stub of a different file, under its own subject's name.

The masking work was correct. What was wrong was a name chosen in a namespace that had since
acquired an occupant.

### Fix

The registered name is now the subject's own filename, `check_redaction_under_test`, which no
importable module can claim. `lib/redact.py` was not renamed: it is the module the rest of the
tree imports, and renaming the real module to accommodate a test loader inverts the dependency.

### Why a one-file fix was not enough

Twelve by-path loaders exist in this tree, each registering a free-form `sys.modules` name.
Every one of them is a latent squatter the moment `lib/` gains a module with that stem — which
is exactly what just happened. Auditing the other eleven by hand (none collide today) fixes
this instance and leaves the *class* in place.

The per-directory floors in `verify_phase0.sh` structurally cannot see this defect: each
directory passes alone, and the collision only exists when two suites share a process. Nor
would a combined run reliably catch the next one — a loader squatting `stats` or `oracle`
under a name whose attributes happened not to be touched would pass green while silently
substituting one module's behaviour for another's.

So the name space is asserted against the source: `lib/tests/test_module_name_collisions.py`
parses every `.py` with `ast`, resolves each `spec_from_file_location` name (string literal or
module-level string constant), and fails if any equals a `lib/*.py` stem.

### Two defects found in the new gate while mutation-testing it

Both were in the gate itself, and both are the failure mode a gate is written against:

| Defect | Why it mattered |
|:---|:---|
| `".venv" not in p.parts` never matches `.venv-oracle` / `.venv-baseline` | The scan read **1,272** files of site-packages instead of 78, so its own non-empty floor of 70 was satisfied by *dependencies* — a scan passing on the wrong tree entirely (`feedback_zero_file_scan_is_error`, and its inverse) |
| a tolerance of "≤ 2 unresolvable loaders" | Three loaders build their name at run time. A count says nothing about whether the third is the known helper or a new blind spot, so the set is now an explicit `UNRESOLVABLE` table with a reason per entry and the count is **derived** from it (`feedback_prose_is_not_verified`) |

The file-count assertion is now two-sided — a floor against a truncated glob **and** a ceiling
against the venvs leaking back in.

Resolution of names held in module-level constants is deliberate: the fix to this very
deviation hoisted the name into a documented `_MODNAME` constant, and a literal-only scan
would have rewarded inlining over documenting by going blind to it.

### Effect on the record

- No measurement, verdict, rate or interval changes. This was a test-harness namespace
  collision; no case script's behaviour was affected.
- `verify_phase0.sh` now reports **14/14 gates, PHASE 0 VERIFIED** — 1,088 tests in one
  process, up from 13/14.
- Coverage added: **4 arms**, **6/6 mutants killed** (revert the name to `redact`; reintroduce
  it via a constant so a literal-only scan would miss it; a new collision on a different name
  in a different file; a new unresolvable f-string name; the venv exclusion broken back to the
  `== ".venv"` bug; an entry dropped from `UNRESOLVABLE`). Clean baseline verified before and
  after every mutant.
- `verify_phase0.sh`'s `lib/tests` floor raised 518 → 522.

---

## DEV-P1-15 — a structural finding printed a botocore version the process had never loaded

**Class:** measurement-integrity defect (instrument provenance) · **design_impact:** none
**Found:** 2026-08-10 · **Cost:** $0.00 (offline)

### What happened

F8-4's central structural finding is that the sealed conjunction is **inexpressible**: the seal
asks for PROMPT_LEAKAGE behaviour *per tier*, and the two halves live on two different APIs.
The script stated it like this:

```
the sealed conjunction is INEXPRESSIBLE at botocore 1.43.67: ApplyGuardrail carries the
tier and has no PROMPT_LEAKAGE category; InvokeGuardrailChecks has the category and no
tier parameter
```

Every element of that sentence was a **hardcoded string**: the filter enum was typed out as a
literal list, "no tier parameter" was English, and `1.43.67` appeared in four places. The
script printed it while running under botocore **1.42.79** — a version claim about a service
model the interpreter had never loaded.

### How it surfaced, and the second finding underneath

The plan requires all live tests to run in `.venv-oracle` (botocore 1.43.67); F1-1 established
that `InvokeGuardrailChecks` first appears at 1.43.30 and is **absent** below it. But
`.venv-oracle` had only boto3/botocore installed — **no numpy, no scipy, no pyyaml** — so
`lib/stats.py` could not import there and **no case script could run in it at all**. Every
live Phase 1 result was therefore collected under the *baseline* SDK. `F10-2.json` records
`{"boto3": "1.42.79", "botocore": "1.42.79"}` in `instrument.sdk`, which is what made this
visible.

Consequence for F8-4 specifically: its `checks-*` arms address an operation the SDK **did not
model**, and its record carries `"error": "botocore 1.42.79 does not model
InvokeGuardrailChecks"`. Its `FALSE` came from `classic_works=false, standard_works=false` —
a state matching *neither* branch of the sealed oracle — decided on an aggregate PROMPT_ATTACK
proxy. That result is invalid and the case is being re-run.

### The claim was true — which is the dangerous case

Verified against the real 1.43.67 model: `CreateGuardrail.contentPolicyConfig.filtersConfig.type`
= `[SEXUAL, VIOLENCE, HATE, INSULTS, MISCONDUCT, PROMPT_ATTACK]` (no PROMPT_LEAKAGE);
`tierConfig.tierName` = `[CLASSIC, STANDARD]` and lives on the **guardrail**;
`ApplyGuardrail` input members = `[content, guardrailIdentifier, guardrailVersion, outputScope,
source]` — no tier; `InvokeGuardrailChecks` input members = `[checks, messages]` — no tier and
no guardrailIdentifier.

Prose that happens to be right teaches nothing about whether the next reader's SDK still
agrees. If AWS adds PROMPT_LEAKAGE to `filtersConfig.type`, the script would go on printing a
falsehood with full confidence (`feedback_prose_is_not_verified`).

### Fix

Every member of the finding is now read off the service model at run time by
`inexpressibility()`, and the version is `A.sdk_versions()`. The two SDKs now report their own
truth and reach the same verdict for **two different documented reasons**:

| botocore | what the banner now says |
|:--|:---|
| 1.42.79 | `INEXPRESSIBLE at botocore 1.42.79 … InvokeGuardrailChecks is not modelled by this SDK at all, so the category is unreachable here` |
| 1.43.67 | `INEXPRESSIBLE at botocore 1.43.67 … InvokeGuardrailChecks HAS PROMPT_LEAKAGE but its input members ['checks', 'messages'] carry neither a tier nor a guardrailIdentifier` |

### Three defects found while making it live

| Defect | Why it mattered |
|:---|:---|
| a one-level `members` walk reported "PROMPT_LEAKAGE absent" | It is present, nested as `GuardrailChecksPromptAttackCategory = [JAILBREAK, PROMPT_INJECTION, PROMPT_LEAKAGE]` — a list of structures. `inexpressible` would have come out True because the category was findable **nowhere**, rather than because it is not beside the tier: **the right verdict for a false reason**. The record now asserts `category_exists_but_not_beside_the_tier` so the weaker reading cannot silently replace the real one |
| `A.ClientFactory(...).bedrock_runtime()` resolves credentials | With none on the box the walk reaches EC2 instance metadata and opens a socket — **a network call inside `--dry-run`**, whose contract is that there is none. Added `A.service_model()`, which reads the JSON botocore ships off a bare session: free, offline, no account |
| `assert inx["sdk"] == A.sdk_versions()` was vacuous | The mutation restoring the `1.43.67` literal **survived** it, because the oracle venv *is* 1.43.67 and the assertion compared the literal to itself. Whether the test worked depended on which interpreter ran it. It now monkeypatches `sdk_versions()` to a sentinel and requires the field to follow — killed under **both** venvs |

`.venv-oracle` was provisioned with numpy 2.5.2, scipy 1.18.0, pyyaml and pytest. The sealed
stats layer is **version-stable**: all **1,088** tests pass identically under numpy 2.4.4/scipy
1.17.1 and numpy 2.5.2/scipy 1.18.0.

### Effect on the record

- **F8-4's smoke result is invalid** and is superseded by the re-run; the seven smoke-only
  cases (F10-2, F2-5, F8-2, F8-3, F8-4, F8-6, F8-7) all re-run under 1.43.67.
- All eleven `r20260810T0345Z` F3 results were collected under 1.42.79. F3 addresses no
  1.43.30+ operation, and every case dry-run plan is **byte-identical** across the two SDKs
  (diffed, 18/18), so their samples stand; the SDK version is recorded with them.
- Coverage added: **4 arms** in `f8_regional/tests/test_f8_helpers.py`, **5/5 mutants killed**
  (hardcode the version back; one-level enum walk; restate inexpressibility as "category
  missing anywhere"; rebuild a client and re-introduce the network call; drop the
  `category_exists_but_not_beside_the_tier` assertion). Clean baseline verified either side,
  under both venvs.

---

## DEV-P1-16 — a verdict published an amendment-blocking shortfall against data the run had collected

**Class:** measurement-integrity defect (label/computation mismatch) · **design_impact:** none
**Found:** 2026-08-10 · **Cost:** $0.00 (offline; the affected live run is re-used, not re-billed)

### What happened

F8-6's full run (60 ApplyGuardrail calls under botocore 1.43.67) reported, in the same output:

```
  arm xregion                 60 items  multilingual/en.jsonl
    xregion: 60/60
    -> x=60 n_usable=60

  verdict: TRUE   (EXISTENCE)
    note: n_usable=0 is below the pre-registered 60; the verdict stands on the data
          collected but its interval is wider than the design promised, so it does not
          clear the amendment bar
```

Sixty usable trials, and a note saying zero. The record agreed with the note:
`{"verdict": "TRUE", "n_usable": 0, "n_attempted": 0, "planned_n": 60, "n_met": false}`.

### Root cause

`lib/phase1.obs_existence` constructed its `Observation` from one boolean:

```python
def obs_existence(case_id, observed, **detail):
    return O.Observation(case_id=case_id, observed_bool=bool(observed), detail=dict(detail))
```

`Observation.n_usable` and `n_attempted` default to `0`. `evaluate` then computed
`n_met = (planned_n is None) or (n_usable >= planned_n)` — **correctly** — from a count no
caller had ever supplied. F8-6's call site did pass the number, as `n_trials=len(rows)`, but
that is a `**detail` kwarg: it landed in the payload, not in the field the oracle reads.

Every number in the published note was arithmetically right. The shortfall itself was
manufactured by the builder rather than measured by the run — `feedback_label_must_match_computation`,
in the form where the label is a whole sentence and the computation had **no input**.

### Why one case, and why that is the dangerous part

Of the **46** EXISTENCE cases, exactly **one** — F8-6 — carries a sealed `planned_n` (60). The
other 45 are `None`, for which the `n_met` rule short-circuits to True and the zero is
invisible. So a defect in a builder shared by **five** call sites was observable through
precisely one of them, and would become observable through another the moment a re-seal gives
some other EXISTENCE case an n.

That is the same shape as **DEV-P1-4**: a case's sealed **kind does not predict whether the
seal gives it an n**. A builder may therefore not assume its kind is n-less.

### Fix

`n` is now a **required, keyword-only** parameter of `obs_existence`, exactly as
`obs_zero_events` already had it and for the reason its docstring already gave — an EXISTENCE
verdict is a conjunction over cells, so the count is not derivable from a tally the builder
can see. Required rather than defaulted to 0, because **a default is what caused this**: with
no default, each of the five call sites must state its own denominator, and a sixth call site
fails at the point of writing instead of at the point of publishing.

| call site | `n` | why that count |
|:---|:--|:---|
| `f8_regional/05_xregion.py` (F8-6) | `t["n_usable"]` | the count the sealed 60 is checked against must be the **checkpoint's** usable count, not a `len(rows)` this script measures for itself; they agree on a clean run and diverge exactly when trials failed |
| `f8_regional/03_prompt_leakage.py` (F8-4) | sum over the **4 proxy arms** | the two `InvokeGuardrailChecks` arms are descriptive and the verdict does not read them; folding them in would back the conjunction with trials that did not participate. `billable_calls` stays the wider figure |
| `f8_regional/06_word_language.py` (F8-7) | sum over **both tiers** | the conjunction is over every cell on every tier, so the denominator is the whole grid |
| `f10_billing/01_text_units.py` (F10-2) | `t["n_usable"]` | no sealed n, so `n_met` cannot change — passed because a record reporting `n_usable: 0` beside 27 billed calls is wrong on its face whether or not a gate reads it |
| `f8_regional/07_absent_surface.py` (F8-8) | `0` | reads the service model botocore ships and makes **no call**: there are no trials. A **stated** zero is a different fact from a defaulted one — which is the whole reason `n` is required |

### Coverage

`lib/tests/test_observation_n.py`, **8 arms**, and deliberately not written about F8-6. It
pairs the **builder set** (enumerated from `lib/phase1.py` by prefix) against the **sealed set**
(read live from `PREREGISTRATION.yaml`):

- every builder either accepts a trial count or is named in `NO_N_BY_DESIGN` with the reason
  its kind has no sample (`obs_recorded`, `obs_boundary`) — a tolerance count would not
  distinguish a documented exception from a new one (`feedback_prose_is_not_verified`);
- no case whose kind is countless may acquire a sealed n — so a re-seal that gives one to a
  BOUNDARY or RECORDED case fails **here**, not in a result file;
- the EXISTENCE-with-sealed-n set is pinned to `{F8-6: 60}` as a tripwire: it may legitimately
  grow, and when it does the new call site needs the same check;
- `n`'s absence of a default is asserted **on the signature**, because a default of 0 would
  satisfy every call site and every behavioural arm while restoring the defect exactly.

**6/6 mutants killed**, clean baseline verified either side: restore the `n=0` default; make
`n` positional; accept `n` and ignore it; drop the negative-count guard; and both of the
*wrong* fixes — delete the shortfall note from `evaluate`, and make `n_met` always True. The
last two matter because deleting the note would have silenced this symptom while re-creating
DEV-P1-11/DEV-P1-12 in the opposite direction: a run publishing verdicts from 3% of its
designed sample at rc=0. A paired arm therefore asserts that a **genuine** shortfall (`n=7`)
still reports one.

Floor raised: `lib/tests` 522 → 530.

### Effect on the record

F8-6's `TRUE` verdict is unchanged — the oracle's EXISTENCE branch reads `observed_bool`, and
the data behind it (60/60 trials, 60 disclosed Regions, all in-geography) was correctly
collected. What was wrong was the shortfall note and `n_met: false` published beside it, which
would have barred an amendment the data supports. The case is re-emitted from the same run id
so the checkpoint resumes rather than re-billing 60 calls.

*(Aside, recorded because it was checked: the "10 builders" floor in the new gate's first arm
was written from memory and the module refuted it at 9. The count belongs to the enumeration.)*

---

## DEV-P1-17 — a unit test had written a checkpoint into the tree live runs resume from

**Class:** evidence-integrity defect (test/production isolation) · **design_impact:** none
**Found:** 2026-08-10 · **Cost:** $0.00 (offline)

### What happened

While auditing all 18 Phase 1 results, a checkpoint appeared whose case id belongs to no case:

```json
{"case_id": "T", "cell": "main", "meta": {"run_id": "r1", "corpus": "c", "planned_n": 1},
 "failed": {"i0": {"error_class": "AssertionError",
                   "error_message": "stub exhausted: more calls than queued responses"}}}
```

`results/checkpoints/T__main.json`. "stub exhausted" is raised by `StubClient` in
`lib/tests/test_arms.py`; `T`, `r1` and `c` are that suite's placeholders. A unit test had
written into the directory live runs resume from.

### Why it is an integrity defect and not untidiness

`lib/checkpoint.py` exists so a killed run resumes rather than re-billing, and `Checkpoint.load`
already treats a file whose `case_id`/`cell` disagree with the opened cell as **fatal** —
"resuming would attribute one arm's trials to another". Every one of those guards is keyed on
`case_id` and `cell`, both of which a test chooses freely. A test writing under a **real** case
id and cell would pass all of them and make a live run skip trials it never ran: fewer usable
trials than the seal asked for, a checkpoint asserting otherwise, no error anywhere, and a
published `n_met` computed from it. `T` is not a real case id, which is the only reason this
instance was harmless.

The fix was already available in the suite — `test_arms.py` has a `roots` fixture handing every
call a `tmp_path` root — so this is a discipline defect. **Not reproducible from the current
suite**: the full 1,100-test run leaves no residue, so the write came from an earlier revision.
One call site (`test_an_unmodelled_operation_fails_before_any_item_is_sent`) still omits
`**roots` and is safe only because a `RuntimeError` fires before the first write — a property
of the code under test, one edit away from changing. Discipline that depends on remembering a
fixture is what an assertion is for.

### Fix

A repo-root `conftest.py` snapshots the protected trees and fails on any change, comparing
`(size, mtime_ns)` rather than existence so an **in-place rewrite** of an existing checkpoint —
the worse of the two failures — is caught alongside a new file.

Two scopes, because the trees differ by 40×. Measured here: `results/` is 111 files and **1.7 ms**
a walk; `evidence/` is 4,548 files and **61 ms**. Per-test on both would add ~120 s to a 187 s
suite — a guard costing two thirds of the run it guards is a guard that gets switched off. So
`results/` (where the incident happened, and where checkpoints live) is checked **per test** and
names the offender; `evidence/` is checked **once per session**. Measured after: **169 s**, i.e.
free.

**3/3 probes fire**, verified with a temporary test file and every artifact removed afterwards:
a new checkpoint, an in-place modification of `results/phase1/F8-6.json`, and an `evidence/`
write.

### A second finding, from the same file

Adding `conftest.py` at the root **widened the module name space**: pytest prepends a conftest's
rootdir to `sys.path` under the default `prepend` import mode, so `check_redaction`,
`verify_prereg`, `estimate_cost`, `build_v13_candidates` and `check_amendment_readiness` became
importable — and therefore squattable — top-level names without any of them moving.

This is DEV-P1-14's mechanism exactly: `lib/redact.py` collided with nothing on the day it was
written either. Checked immediately (no registered loader name matches a root stem; no root stem
matches a lib stem), and `test_module_name_collisions.importable_names()` now returns
`lib ∪ root` so a **future** loader cannot claim one. **2/2 mutants killed** (revert to
lib-only; remove the root conftest).

Floors raised: `lib/tests` 530 → 531; compile-gate file count 70 → 78 (82 present — a floor
twelve files below the tree would let a whole directory vanish and still report clean, which is
the defect the per-directory floors are written against).

### Effect on the record

None. The stray checkpoint's case id `T` matches no case in the seal, so no result read it and
no verdict depended on it. It is removed, and the guard means the class cannot recur silently.

---

## DEV-P1-18 — a case published a refutation of the document from a filter that never ran

**Class:** measurement-validity defect (instrument mis-addressed) · **design_impact:** F3-7 verdict inverted
**Found:** 2026-08-10 · **Cost:** $0.00 to find, 120 calls to re-measure

### What happened

F3-7 asks whether contextual grounding can tell a grounded response from an ungrounded one. Its
first full run completed cleanly and published:

```
verdict: FALSE   (DISJOINT_INTERVALS)
  ungrounded: x=0 n=60   ci 0 [0, 0.06017]
  grounded:   x=0 n=60   ci 0 [0, 0.06017]
```

read as *"the check cannot tell grounded from ungrounded within the documented limits"* — a
refutation of the document. 120/120 trials usable, `failure_codes: []`, `blockers: []`,
`blocks_per_trial: [3]`, rc=0.

The filter had never executed. `ArmSpec.source` defaults to `"INPUT"`; contextual grounding
scores a **response**. Measured live (us-east-1), same three content blocks, same guardrail
`j30orj6hdh1a`, only `source` differing:

| `source` | HTTP | `action` | `assessments[]` keys | GROUNDING |
|:---|---:|:---|:---|:---|
| `INPUT` | 200 | `NONE` | `appliedGuardrailDetails`, `invocationMetrics` | *(no block at all)* |
| `OUTPUT` | 200 | `GUARDRAIL_INTERVENED` | + `contextualGroundingPolicy` | `score=0.0 BLOCKED` |

The service accepts the INPUT-side request, bills it, returns 200, and omits the policy block.
No error, no warning, no empty-filters list — the key is simply absent.

### Why every existing gate passed

This is the part worth recording, because the project has a lot of gates and all of them were
satisfied:

* **`outputScope="FULL"` was set.** That was the guard written against exactly this shape of
  blindness (`lib/arms.py` decision 1) — but `FULL` governs which *evaluated* policies get
  reported. It cannot report a policy that never ran.
* **`require_measured` saw 120/120 usable.** Every trial genuinely completed.
* **`n_met` was vacuous by design.** F3-7's corpus is unsealed, so `planned_n` is `None`
  (DEV-P1-4) — the one check that might have asked about sample adequacy had nothing to say.
* **The oracle was correct.** Two Wilson intervals, `[0, 0.06017]` twice, correctly not
  disjoint, correctly FALSE *for the data it was given*.
* **The three-block construction was right, and its docstring anticipated this exact failure
  mode** — "an arm that sent only the source would get `action=NONE` with nothing scored, which
  is byte-indistinguishable from *the response was grounded*". It guarded the block list and
  missed the addressing. Being one field away from a hazard you have already written down is
  the ordinary case, not an unusual one.

The defect sits in a seam: **tolerance is correct in a flattener and wrong in a reader.**
`read_assessment` is deliberately tolerant of an absent policy block, because absence is also
how the API says "this guardrail has no such policy configured" — a legitimate configuration
F3-1 depends on. `hit_grounding` then reduced `grounding == []` to `False`, and that single
`False` conflates *ran and did not fire* with *did not run*.

### What made it findable at all

Not a gate — an anomaly. Both arms read exactly `x=0`, and a discrimination case in which
neither cell ever fires is a stronger statement about the instrument than about the subject
(`feedback_design_methodology`: investigate anomalies first). The payload's own
`grounding_score_summary` then said it outright: `n: 0` scores harvested from 120 trials, on a
guardrail configured with two filters at 0.7. A run that measured nothing had reported it,
faithfully, in a field beside the verdict — the DEV-P1-11 shape again (*a shortfall reported
beside a verdict is a verdict*).

### The fix, in three parts

**1. `source="OUTPUT"` on both F3-7 arms.** The one-word cause.

**2. `Assessment.blocks_present` + `ArmSpec.require_policy` — a liveness channel.** The union of
`assessments[]` keys is recorded on every row, and an arm may name one block that MUST be
present; its absence raises `PolicyNotEvaluated`, which is recorded as a **failed trial** rather
than a negative. That reuses machinery already built for this concept: the trial stays out of
`n_usable`, lands in `failed` with a self-naming code, is retried by a resume, and drives
`require_measured` below its 90% floor. `PolicyNotEvaluated` is in neither retry set — a
mis-addressed request fails identically on all 3 attempts.

**Which blocks are safe to require was measured, not assumed.** Benign input that fires nothing,
one guardrail per policy:

| block | on a non-detection | requirable? |
|:---|:---|:---|
| `contentPolicy` | **present** | yes |
| `sensitiveInformationPolicy` | **present** | yes |
| `topicPolicy` | **present** | yes |
| `wordPolicy` | **absent** | **no** — would fail every true negative |
| `contextualGroundingPolicy` | **present** (`score=1.0 detected=false`) | yes — absent only when it did not RUN |

So `require_policy` is a per-arm opt-in naming one block, not a blanket "require whatever the
guardrail configures" rule. That rule would have converted all 54 of F3-6's true negatives into
failed trials — a guard eating the data it protects. `test_policy_liveness.py` pins the
asymmetry in both directions.

**3. `Checkpoint.set_meta` refuses a resume across a design change.** This is the half that
would have made the fix invisible. `load` already treats a disagreeing `case_id`/`cell` as fatal
because "resuming would attribute one arm's trials to another"; the same argument covers every
field that determines what a trial *is*, and those were recorded in `meta` and **never
compared**. Correcting `source` and re-running would have found 120 completed trial ids, skipped
every one, and re-published the identical wrong verdict — with the corrected `source` now sitting
in the meta beside rows never collected that way. *The fix would have looked applied and changed
nothing.*

`DESIGN_KEYS = (source, qualifiers, output_scope, guardrail_version, region, corpus, is_smoke,
operation)`. Deliberately excluded: `run_id` (varying it is how this project re-emits at $0 —
F8-6 and F10-2 both), `planned_n` (a `--n 3` smoke legitimately grows it, and `is_smoke` catches
the direction that matters), `sdk`. The guard fires only when completed trials exist, so a first
run and an all-failed arm both still resume — and the remedy is stated, not automated, because
discarding paid-for trials is the operator's call.

### Mutation results — 8/8, against a verified-clean baseline (86 passed, 1 skipped)

| # | mutant | result |
|:--|:---|:---|
| M1 | `require_policy` check → `if False` (the original defect) | **killed** (1) |
| M2 | `blocks_present` always `[]` | **killed** (3) |
| M3b | `PolicyNotEvaluated` added to `RETRY_CODES` | **killed** (2) |
| M4b | `error_code` class attribute deleted | **killed** (2) |
| M5 | design-drift guard → `if False` | **killed** (11) |
| M6b | drift guard drops the `self._done` condition | **killed** (2) |
| M6c | drift guard keyed on `_loaded_meta` instead of `_done` | **killed** (2) |
| M7 | `run_id` promoted into `DESIGN_KEYS` | **killed** (2) |
| M8 | `_loaded_meta` never populated from disk | **killed** (11) |

Three of those mutants survived their **first** attempt, and each survival was a real gap in my
own tests rather than a mis-aimed mutation:

* **M3** targeted `RETRYABLE_TRANSPORT`, which `is_retryable` only consults for a
  `BotoCoreError`. The mutation could not have had an effect; re-aimed at `RETRY_CODES` (M3b) it
  kills. A mutant that cannot change behaviour scores a false kill.
* **M4** survived because the class is *named* `PolicyNotEvaluated`, so `checkpoint.error_code`'s
  class-name fallback returns the identical string whether or not the attribute exists. The arm
  was asserting a coincidence. Now asserted on the attribute directly, plus an arm using a
  differently-named subclass to isolate it from the fallback.
* **M6** survived because no checkpoint in the suite was non-empty in `failed` and empty in
  `done` — so nothing distinguished "no completed trials" from "no checkpoint". That state is not
  hypothetical: the 2026-08-10 outage (DEV-P1-11) left arms in exactly it, and those are the arms
  most likely to be re-run with a fix applied. Arm added.

Also fixed in my own test: the F3-7 pinning arm first counted `require_policy=` occurrences in
the source text and failed at `3 == 2`, because the script's docstring *quotes the argument it
documents*. A text count cannot tell a call site from prose about a call site
(`feedback_prose_is_not_verified`), so the arm now counts `ArmSpec(...)` keywords through the AST
— which makes documenting the fix impossible to confuse with applying it.

### Effect on the record — the verdict inverts

F3-7 re-run at the same n, `source="OUTPUT"`, both arms guarded:

| | first run (`source=INPUT`) | re-run (`source=OUTPUT`) |
|:---|:---|:---|
| ungrounded detection | **0/60** — `0 [0, 0.06017]` | **56/60** — `0.9333 [0.8407, 0.9738]` |
| grounded FPR | **0/60** — `0 [0, 0.06017]` | **2/60** — `0.03333 [0.009189, 0.1136]` |
| GROUNDING scores harvested | **0** | 60 per arm; median **0.0** vs **0.99** |
| intervals disjoint | no (gap 0) | **yes**, gap **0.727** |
| **verdict** | **FALSE** | **TRUE** |

**So the document was right and the harness was wrong.** The governing principle is that facts
win, and this is the case where the facts favour the document — which is the same rule, applied
in the direction that is easier to forget. A published FALSE here would have been a claimed
refutation of AWS's contextual-grounding filter built on 120 requests that never reached it.

The 120 INPUT-side trials are not deleted. They are moved to `results/quarantine/` as
`F3-7__{arm}.source-INPUT.json` — they cost real money, and they are the primary evidence for
this entry.

Floors raised, **measured rather than predicted**: `lib/tests` 531 → **543** (12 collected arms:
11 plus a skip, which `--collect-only` counts) and the compile-gate file count 78 → **83**. My
first draft of this line wrote 542 and 79 — the arithmetic of "11 arms plus 1 skip" and "one new
file" applied to the *old floors* instead of to the *current tree*. Both were wrong in the
direction that matters, because a floor is only a tripwire for what is there now: `lib/tests`
collected 560 at that moment, so 542 would have permitted 18 arms to vanish silently, and the tree
held 83 `.py` files, so 79 would have permitted four. Read off `pytest --collect-only` and
`find | wc -l` instead (`feedback_quantify_qualifiers`: the number behind the adjective has to be
measured, and a floor is exactly such a number). Both floors rose twice more in the same session for
DEV-P1-19 below — `lib/tests` to 555 and then 587, the file count to 84 and then 85 — which is the
ordinary case and why this convention records the *delta and its cause* per entry rather than a
running total. A running total in prose here would have been stale within the hour, three times.

---

## DEV-P1-19 — a guard failed 147 innocent tests, because a tree diff cannot see who wrote

**Class:** measurement-validity defect (guard specificity; false accusation) · **design_impact:**
none on any verdict — the guard is infrastructure, and no result was published from a run it
misjudged · **Found:** 2026-08-10 · **Cost:** $0.00 (offline)

### What happened

`./verify_phase0.sh` reported **13/14 gates passed**, the failure being the combined test suite:

```
1128 passed, 2 skipped, 147 errors in 266.72s
AssertionError: the test session wrote into the live evidence tree:
  ADDED    evidence/r20260810T0345Z/f8/F8-4-checks-leakage/0068_invoke_guardrail_checks_ok.json
  ... 8 more
```

Every one of the 147 was innocent. `f8_regional/03_prompt_leakage.py` — 690 live calls, launched
minutes earlier — was writing that directory *from another process* the whole time the suite ran.
`ps` confirmed it (`PID 53103`, started 5:41 PM), and it went on to finish at rc=0 with F8-4's
verdict intact.

The root `conftest.py` guard (added in DEV-P1-17) had exactly one channel: snapshot `results/` and
`evidence/`, run, diff. **A tree diff observes change; it cannot observe authorship.** It supplied
the missing half by assuming that whatever changed during a test session was written by the test
session.

### Why a false accusation is the same defect as a missing guard

DEV-P1-17's own reasoning was that a guard costing two thirds of the run it guards "is how guards
come to be switched off". False conviction switches a guard off just as surely — and it does
something worse first: it **inverts the signal**. After one such run, the operator learns to read
this guard's red as *"a live run must be going"*. That is precisely the reading under which the
real leak — a unit test writing `results/checkpoints/F3-1__pii-ssn.json`, the incident DEV-P1-17
was written about — gets waved through the next time it happens. A guard whose red means "probably
nothing" is a guard with no red.

Two second-order facts made it worse than a cosmetic misattribution:

* **147 errors, not 147 failures.** The guard convicts from an autouse fixture's *teardown*, and
  pytest reports a teardown raise as an *error* on a test whose body passed. So the summary line
  said "errors", nothing said "assertion", and `-x` could not stop at the first offender.
* **It was the loudest thing in the run.** 147 identical blocks of text buried the two genuinely
  interesting lines (`1128 passed, 2 skipped`).

### Root cause

One channel, answering the wrong question. The guard asked *"did anything under these paths
change?"* when the question it exists to answer is *"did a **test** write under these paths?"*

### Fix — two channels, each covering the other's blind spot

**1. An audit channel establishes authorship.** `sys.addaudithook` records every
`open(..., 'w'|'a'|'x'|'+')`, `os.rename`/`os.replace`, `os.mkdir`, `os.remove` and `os.truncate`
performed *by this interpreter* under a watched root, tagged with the nodeid of the test running at
the time. It is structurally immune to anything another process does. Three details that are not
incidental:

* The attribution window wraps the whole `pytest_runtest_protocol`, not the `call` phase — the
  DEV-P1-17 write came from a **fixture**, and a `call`-only window files fixture writes under
  `<no test running>`, i.e. attributed to nobody, which is where they were before the guard existed.
* `_under_watch` calls `os.path.abspath`, because `lib/checkpoint.py`'s default root is the
  **relative** `results/checkpoints`. A prefix test against an absolute root would have matched
  nothing and reported clean on the exact write that caused DEV-P1-17 — the guard's own blindness,
  reintroduced inside the guard.
* `os.replace` is charged to its **destination**. `Checkpoint.save` writes `<x>.json.tmp` and
  replaces it onto `<x>.json`; charging `args[0]` would name a temp file nobody resumes from.

**2. The diff channel is kept**, because a hook sees only its own interpreter and **ten test files
in this project spawn subprocesses** (`claims/tests/test_prereg_verifier.py`, `test_corpus_gate.py`,
`test_v13_candidates.py`, `test_redaction_gate.py`, `test_cost_gate.py`, `test_amendment_gate.py`,
`test_finding_numbers.py`, `test_prereg_finding_numbers.py`, `lib/tests/test_checkpoint.py`,
`f5_redteam/tests/test_compare_runs.py`). A child's writes are invisible to the parent's hook —
verified directly, not assumed.

The combination, which is what `lib/tests/test_write_guard.py` pins as a truth table:

| diff moved | wrote in-process | spawned a child | verdict |
|:---|:---|:---|:---|
| yes | yes | — | **FAIL**, naming the write and the file |
| yes | no | **yes** | **FAIL** — a child is a write the test caused, so charged, not excused |
| yes | no | no | **not this test** — reported once as concurrency, charged to nobody |
| no | yes | — | **FAIL** — an in-place rewrite to identical `(size, mtime_ns)`, invisible to the diff |

The last row is where the audit channel is strictly stronger, and it is the failure that matters
most: a checkpoint *overwritten* with stub trials changes what a live run resumes, rather than
merely adding litter.

**3. The concurrency notice is reported, not swallowed.** When the diff moves and the audit channel
exonerates everyone, the run is not failed — but it is not silent either, because while another
process writes into these trees **the diff channel is void for the whole session**, so the suite ran
with one of its two guards effectively disabled. That is a fact about the run's evidentiary value.
It is emitted from `pytest_terminal_summary`, not from the fixture: a `print` in fixture teardown
goes through pytest's capture and is shown only for a *failing* test, so on the green run this
notice describes it would have been captured and discarded — invisible in exactly the case it
exists for.

### Two defects the new tests found in the new guard

Both were mine, and both were found by an arm failing rather than by inspection:

1. **The per-test fixture read writes from both trees.** The hook watches `results/` and
   `evidence/`; the per-test fixture guards `results/` only. Unfiltered, an `evidence/` write
   failed with the message *"this test wrote into the live **results** tree"* and the path
   `evidence/ext.json` printed underneath it — the wrong tree named above the right path, which
   sends the reader to the wrong root cause (`feedback_label_must_match_computation`). Fixed by
   passing the scope to `_writes_since`.
2. **The notice was unreachable.** Written as a `print` in the session fixture's teardown, it was
   captured and dropped on green runs. Found because the arm asserting it appears failed.

### Three corrections to my own test arms, and what each revealed

| # | what failed | cause | what it says |
|:--|:---|:---|:---|
| 1 | all 11 subprocess arms, `ValueError: Pytest terminal summary report not found` | `pytester` monkeypatches `HOME`, and pytest lives in the **user** site-packages resolved from `HOME`; the child died with "No module named pytest" | a harness with no pytest fails in a shape that reads as "the guard misbehaved" |
| 2 | 8 arms, `assert {'errors': 1} == {'failed': 1}` | the guard convicts from teardown, which pytest counts as an **error** | this is the same accounting that made the incident read as "147 errors" with nothing saying "assertion" |
| 3 | the row-3 arm, twice | first the external writer ran in `pytest_sessionstart` (before the session fixture's baseline, so the diff correctly saw nothing); then it ran in `pytest_runtest_setup`, which is **inside** that test's attribution window, so the spawn was charged and the run became row 2 | the guard was right both times and said so precisely; staging row 3 requires a write that lands between the snapshots and is attributable to no test |

Correction 3 is the one worth keeping: an arm that passes because it accidentally measured a
different row of the truth table is worse than an arm that fails. The final staging launches the
writer from `pytest_configure` (before any test exists) and releases it with a `GO` sentinel
created by the middle test — sentinels in both directions, no `time.sleep`, because a sleep is a
race with a bound nobody measured. The arm also asserts both files exist: row 3's expected outcome
is that *nothing* is charged, so a child that silently wrote nothing would have passed for the
wrong reason (`feedback_vacuous_test_check`).

### The mutation run, and the two survivors it produced

Twelve mutants, each breaking one claim above. Every arm passing over a guard with this history is
worth nothing until the arms are shown to be load-bearing, and the first run said so: **two
survived.**

| id | mutation | claim attacked | first run | now |
|:--|:---|:---|:---|:---|
| M1 | hook records nothing | authorship channel exists at all | killed | killed |
| M2 | window is `call`-phase only | fixture writes are attributed | killed | killed |
| M3 | no `abspath` | the relative checkpoint root is watched | killed | killed |
| M4 | `os.replace` charged to source | the destination is the write | killed | killed |
| M5a | per-test unattributed diff raises | the 147-error regression, per test | killed | killed |
| M5b | session unattributed diff raises | the same regression at session scope | *not measured* | killed |
| M6 | spawning tests excused | a child is a write the test caused | killed | killed |
| M7 | notice suppressed | a void diff channel is reported | killed | killed |
| M8 | per-test reads both trees | each guard names its own tree | **SURVIVED** | killed |
| M9 | evidence culprits ignored | the session failure names a test | killed | killed |
| M10 | recording scope widened to `/` | — | survived | **inert, by argument** |
| M11 | session reads all trees | the mirror of M8 | *not measured* | killed |

**M8 was a real gap, and it was the exact defect fixed earlier in the same session** — the per-test
fixture naming the results tree over an `evidence/` path. Thirteen arms passed against its
reintroduction, because every one of them asserted on the *outcome* and the mutation does not change
whether a test is convicted, only **what the failure says**. A count-based arm is structurally blind
to a mislabelled conviction. Killed now by a negative assertion inside the evidence arm
(`"wrote into the live results tree" not in out`), and its mirror direction — a `results/`-only
write must not fire the session's evidence message — by a new arm, which is what M11 measures.

**M10 is inert, and that is recorded as an argument rather than as a survival.** `_PREFIXES` gates
only what the hook *records*; both conviction paths re-filter by tree
(`_writes_since(mark_w, nodeid, PER_TEST)` and the `ev_root` prefix). A write recorded outside a
watched tree therefore cannot reach a verdict, so no arm *can* observe this mutation. The harness
marks it `inert` and fails if it ever **dies**, since that would mean the inertness argument no
longer holds. This is the third instance of the same class in this project (DEV-P1-18's M3 was the
last): a mutant that cannot change behaviour contributes a number to a mutation table that is not
evidence in either direction.

**M5a/M5b and M11 did not exist in the first run, and their absence was itself a defect.** The
shell harness had one M5 whose target text `    _UNATTRIBUTED.extend(lines)` occurs **twice** in
`conftest.py` — once in the per-test fixture, once in the session fixture — and `str.replace(…, 1)`
applied it to whichever came first. Exactly one of the two regressions was ever measured, and
nothing said so. The in-tree harness has an arm asserting **every mutation target appears exactly
once**, so a target that stops matching, or starts matching twice, reds instead of silently
shrinking the mutation set.

### The harness moved into the tree, and why that is not tidiness

The first version was a shell script in `/tmp`. Two defects, both structural:

1. **Its result was prose.** "8 killed, 2 survived" went into this entry as a measured number that
   nothing in the repository could reproduce — `feedback_prose_is_not_verified` in its plainest
   form. It is now `lib/tests/test_write_guard_mutation.py`, run by `verify_phase0.sh`, so an edit
   that neuters an arm reds a gate instead of waiting for someone to remember a script.
2. **It mutated the live `conftest.py` in place**, restoring it from a backup on a bash `EXIT`
   trap. A `kill -9`, a full disk, or a raise inside the trap would have left a *deliberately
   broken* write guard in the tree — and the write guard is what keeps the test suite out of the
   live evidence trees. Each mutant is now applied to a copy in a `pytester` sandbox; the real file
   is opened read-only, and an arm compares its sha256 before and after the whole run.

The arms file resolves its subject through `GRX_CONFTEST`, defaulting to the live root conftest, so
the same 15 arms run against the real guard under pytest and against a mutated copy under the
harness. No second implementation of the guard's logic exists to drift
(`feedback_verify_against_real_artifact`).

Three further arms exist because a mutation harness fails in ways that look like success:

* **A control arm** runs the 15 arms against an *unmutated* copy through the same `GRX_CONFTEST`
  path. Without it, all 11 kills could be kills of the harness. Mutation-checked in turn: fed a
  guard with the audit channel deleted, it reds (8 failed, 7 passed).
* **`passed > 0` per mutant.** The cheapest way to break a guard is a `SyntaxError`, which reds
  every arm and would otherwise bank as the strongest kill in the table. This is the same defect
  the compile gate in `verify_phase0.sh` was written against — a mutation run that scored 13/13
  against a tree where no test ran at all.
* **`killers` per mutant.** Where a mutant has a specific arm written for its claim, the harness
  requires *that arm* to be among the dead. A kill by an unrelated arm leaves the claim's own
  coverage unproven, which is how M8 hid: eight arms failed under M1 and M2, so the table looked
  healthy while one claim had nothing behind it.

### Verification

`15/15` guard arms and `16/16` mutation arms pass (12 mutants: 11 killed by their named arms, 1
declared inert). `./verify_phase0.sh` → **14/14 gates, 1159 passed, 2 skipped in 302 s**, redaction
gate clean over 232 files, with no live run in flight. Floors raised: `lib/tests` 543 → 555 →
**587**, compile-gate file count 83 → 84 → **85**.

---

## DEV-P2-01 — the redaction gate's ARN excuse was excusing lines it had never read, and one
## of those lines could have carried a real account id

### What happened

Phase 2 added twelve files under `infra/`. On the first full `./verify_phase0.sh` after they
landed, the redaction gate reported **5 findings** across `infra/01_iam.py` (3),
`infra/02_lambda.py` (1) and `lib/cedar.py` (1). All five were source lines that *construct* an
ARN at run time — the account field is an f-string placeholder — plus one 12-digit dry-run
stand-in. **No real identifier was in the tree**, and the obvious resolution was five narrow
`ALLOW` entries.

Checking whether an exception was really needed found the actual defect. `check_redaction.allowed()`
granted a per-line excuse when every ARN on the line had its account field masked, implemented as:

```python
for m in re.finditer(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:([^:]*):", line):
    if m.group(1) != _redact.ACCOUNT_PLACEHOLDER:
        break
else:
    return "every ARN on this line has its account field masked …"
```

The service and Region fields are `[a-z0-9-]*`. A line that builds an ARN writes them as
`{region}`, which contains `{`, `}` and `_`. So the regex matched **nothing**, `finditer` yielded
an empty iterator, and a `for` loop over an empty iterator runs its `else` — returning the message
"every ARN on this line has its account field masked" about a line whose account field had never
been inspected.

This was **live, not hypothetical**. `lib/testbed.py:301`
(`arn:aws:bedrock-agentcore:{region}:{account_id}:policy-engine/{engine_id}`) was being excused by
it at the time, and so was every truncated ARN prefix appearing in a comment or a regex literal.

### Why it matters more than the five findings

The excuse is a **guard**, and this is the vacuous-guard shape (`feedback_vacuous_test_check`): it
answered "waived" for an input class it could not parse, which is the answer that hides leaks. A
mutation check against the original code quantifies the exposure:

| fixture | original code | fixed code |
|:---|:---|:---|
| `…:iam::<12 real digits>:role/admin` | not excused | not excused |
| masked ARN + real ARN on one line | not excused | not excused |
| `…:logs:*:<12 real digits>:*` | **EXCUSED** | not excused |
| a truncated ARN prefix in a regex literal | **EXCUSED** | not excused |
| partial mask (`<acc>` + 8 digits) | not excused | not excused |

Row 3 is the one that matters: a wildcard Region followed by a **real account id** was waived,
because `*` is not in `[a-z0-9-]` either, so that line also produced an empty iterator. The gate
whose entire purpose is to stop an account id reaching a public push had a path that excused one.

### The fix

`allowed()` now cross-checks its own match count against the **reporting** pattern's and returns
`None` — fail closed — whenever the two disagree, so an ARN the excuse cannot decompose can never
be waived by it. The account field is then classified explicitly: exactly the placeholder (masked),
a `{…}`/`<…>` run-time placeholder (source code, no identifier), or exactly `*` (an IAM resource
wildcard). Anything else is reported. A 12-digit account id matches none of the three shapes, so
recognising placeholders does not widen the gate.

The five original findings resolved with **zero `ALLOW` entries**: four were placeholder
construction, now correctly classified; the fifth was a `"0"×12` dry-run stand-in in
`infra/01_iam.py`, replaced with `redact.ACCOUNT_PLACEHOLDER`, which the line above it was already
using. Removing the 12-digit shape was strictly better than waiving it — the gate is shape-based on
purpose, and a waiver for a 12-digit literal is a waiver of the pattern's whole point.

### Also in this change

* **`lib/tests/test_module_name_collisions.py`** — `infra/tests/conftest.py` builds its
  `sys.modules` names as `f"_infra_{stem}"`, which cannot be resolved statically, so the collision
  gate correctly refused to skip it. Added to `UNRESOLVABLE` **with an arm that discharges its
  reason**: no importable name in the owned space begins with `_infra_`, the prefix is read out of
  the conftest's source rather than only from a constant this test defines, and the premise (≥8
  digit-led scripts in `infra/`) is asserted so the exemption cannot outlive its cause.
* **`RECONNECT.md`** — a reconnect note written this session for cross-device continuity spelled
  out the management account id and both member account ids. The gate reported all three. Rewritten
  to name them by role only. Worth recording rather than quietly fixing: the leak was in a file
  written *by* the process that knows the rule, which is exactly why the rule is a gate and not a
  habit (`feedback_redact_cloud_metadata`).

### Verification

`21` new arms in `claims/tests/test_redaction_gate.py` (7 excused fixtures × pattern-trips +
excuse-waives, 5 reported fixtures, a match-count cross-check over all 12, and a placeholder-shape
arm proving `{…}` cannot match 12 digits). Every fixture is assembled at run time, so no identifier
shape appears as a literal — the same rule the file's existing canaries follow. Mutation-checked
against the original `for/else`: **2 of the 5 reported fixtures are wrongly excused by it**, so the
arms fail against the pre-fix code and the fix is load-bearing.

`./verify_phase0.sh` → **14/14 gates, 1218 passed, 2 skipped in 300 s**, redaction gate clean over
**249** files. Floors raised: compile-gate file count 85 → **100** (the 12 `infra/` files + 3);
new per-directory floor `infra/tests:44`, the eighth directory and the only one covering code that
deletes AWS resources.

---

## DEV-P2-02 — one service, two name grammars: `grx-pe-<runid>` was rejected by a constraint the
## SDK had been carrying all along

### What happened

`infra/03_policy_engine.py --ensure` failed on its first live call:

```
ValidationException: 1 validation error detected: Value 'grx-pe-r20260810T130945Z' at 'name'
failed to satisfy constraint: Member must satisfy regular expression pattern:
^[A-Za-z][A-Za-z0-9_]*$
```

The project's naming convention is `grx-<thing>-<runid>`, applied uniformly. It works for gateways
and gateway targets and cannot work for policy engines or policies, because `bedrock-agentcore`
runs **two different name grammars in one service**:

| operation | `name` pattern | min–max | hyphen |
|:---|:---|:---:|:---:|
| `CreatePolicyEngine` | `^[A-Za-z][A-Za-z0-9_]*$` | 1–48 | **rejected** |
| `CreatePolicy` | `^[A-Za-z][A-Za-z0-9_]*$` | 1–48 | **rejected** |
| `CreateGateway` | `([0-9a-zA-Z][-]?){1,48}` | 1–48 | allowed |
| `CreateGatewayTarget` | `([0-9a-zA-Z][-]?){1,100}` | 1–100 | allowed |

All four patterns are in the botocore service model. **This was fully detectable offline**, for
$0, before any call — and it explains a detail recorded during recon that had looked like someone
else's style choice: the two abandoned June-2026 engines in this account are named
`agentcore_test_pe_*` with underscores. Whoever built them hit the same wall.

### Why it is recorded as a deviation and not a typo

Because the fix that removes the symptom is not the fix that removes the class. Renaming to
`grx_pe_<runid>` would have made this call succeed and left eight other resource names unchecked,
each one an identical ValidationException waiting for the first live call of a later phase — and
some of those phases are the expensive ones. The remedy is therefore a **model-driven** check:

```python
def check_name(client, operation, name, member="name"):
    meta = client.meta.service_model.operation_model(operation).input_shape.members[member].metadata
    # pattern / min / max read from the model, never copied into this file
```

`lib/testbed.check_name()` reads `pattern`, `min` and `max` out of the shape metadata and raises
locally with the offending pattern quoted. It is derived from the model rather than from a copy of
the regex, so it cannot drift from the service the way a hard-coded pattern would; and it is called
at every name construction site in `03_policy_engine.py`. All nine project resource names were then
swept through it **offline** before another live call was spent.

### The second-order consequence, which was the more dangerous half

The rename would have broken teardown *silently*. `99_teardown.py:not_ours()` is the allow-list
backing the deny-list — the guard that refuses to delete anything not named like ours — and it
recognised exactly one separator:

```python
_OUR_PREFIX = "grx-"
```

With the engine renamed to `grx_pe_…`, `not_ours()` would have **refused to delete our own policy
engine** while reporting a clean sweep of everything else. That is the isolation gate failing in the
inverted direction: not deleting something it shouldn't, but declining to delete something it
should, and saying "clean". Fixed by making the allow-list carry both separators, with an assertion
that the two forms stay in sync:

```python
_OUR_PREFIXES = ("grx-", "grx_")
for _p in _OUR_PREFIXES:
    if _p.replace("_", "-") != _OUR_PREFIX:
        raise AssertionError(...)
```

and by matching on the ARN/name **tail** (`rsplit("/")`/`rsplit(":")`) rather than the whole string,
since a policy ARN embeds its engine's name and the prefix is not at position 0.

### Cost

One rejected API call, $0. The reason it is written up despite costing nothing is
`feedback_design_methodology`: the ValidationException was the anomaly, and following it produced a
class-level guard plus a live teardown defect, neither of which a rename would have surfaced.

---

## DEV-P2-03 — `DeletePolicy` returns 200, the policy vanishes from `ListPolicies`, and the name
## is still taken

### What happened

`03_policy_engine.py` tries the document's baseline permit **without** `validationMode` first,
because that call existing is the DC-1 measurement. It settled `CREATE_FAILED`, as expected. The
script then deletes the failed policy and retries with `IGNORE_ALL_FINDINGS`. The retry failed:

```
ConflictException: Policy with the same name already exists
```

while `list_policies(policyEngineId=…)` on that engine returned **zero rows**. Sequence, all within
a few seconds:

| step | call | result |
|---:|:---|:---|
| 1 | `create_policy` (no `validationMode`) | 200, then `CREATE_FAILED` — DC-1 |
| 2 | `delete_policy` | **200** |
| 3 | `list_policies` | **0 rows** |
| 4 | `create_policy`, same name | **ConflictException: already exists** |

So the name outlives both the delete's own 200 **and** the policy's visibility in the list. The
resource is gone and its name is not free, and the two facts are reported by different surfaces.

### Why this is not fixable by polling

The obvious remedy — retry the same name with backoff until the conflict clears — cannot be
*verified* by any read available to us. Polling waits on a signal, and the only signal here is
`list_policies`, which already reports the name as absent at step 3. There is nothing to wait for
that we can observe; a backoff loop would be waiting on a timer while telling itself it was waiting
on a state.

The fix is to remove the coupling instead: attempt 2 uses a distinct name (`…_v2`), validated
through `T.check_name` like every other name. Three reasons that is better than a retry loop, and
they are ordered by weight:

1. **It cannot hang.** A retry loop on an unobservable condition is unbounded in principle.
2. **This is the DC-1 branch.** The code path only runs when the document's own recommended
   statement has just failed — the finding we most want recorded promptly and unambiguously. Behind
   a retry loop, a failure of the loop and the finding itself look alike in the logs.
3. **The evidence is clearer.** Two attempts become two separately addressable policy names in the
   evidence archive, rather than one name carrying two histories.

### What it means for teardown, checked rather than assumed

A name that outlives its resource is a teardown concern: a rebuild under the same `run_id` could
collide. It does not affect us, and the reason is structural rather than lucky — every project
resource name embeds the `run_id`, and `run_id` is minted from a UTC timestamp, so no two runs
construct the same policy name. `--run-id` can force a repeat, and that is the documented resume
path where the ledger's own guard already refuses a mismatched run.

### Status

Recorded as **service behaviour**, not as a document conflict: our document says nothing about
policy deletion semantics, so there is no claim to amend. It is a caveat for anyone scripting
create/delete cycles against `bedrock-agentcore` policies, and it goes to the v1.3 candidate list
under operational notes rather than as a correction.

---

## DEV-P2-04 — the tag channel cannot see IAM roles or policies, and one of those two is not a
## permission problem

### What happened

`infra/06_verify.py` — read-only, $0 — returned **34 PASS, 1 FAIL** on the built testbed. The
failure was its cross-check between the ledger and the tag channel:

```
[FAIL] tag index covers the ledger    NOT indexed: policy/baseline, iam-role/echo-exec,
       iam-role/attacker, iam-role/caller, iam-role/gw-exec, iam-role/runtime-exec
```

Six resources in the ledger, absent from `resourcegroupstaggingapi`. Two candidate causes with
opposite remedies: **our creation code failed to tag them** (a bug to fix) or **the index does not
cover those types** (a fact to record and route around). They were separated by measurement, and
the answer differs per type.

**IAM roles — tagged, not indexed.** `list_role_tags` returns all four project tags on all five
roles:

```
role gw-exec -> [('ExpiresAt', …), ('Owner', 'harness'),
                 ('Project', 'guardrails-doc-validation'), ('RunId', 'r20260810T130945Z')]
```

while `get_resources(ResourceTypeFilters=["iam:role"])` returns **0 rows account-wide** in
us-east-1. The denominator matters, because "0 rows" is also what an account with no tagged roles
returns, so the account was scanned rather than assumed:

| measurement | value |
|:---|---:|
| IAM roles in the account | **681** |
| roles carrying ≥1 tag (`list_role_tags`) | **102** |
| roles returned by `get_resources(["iam:role"])` | **0** |
| rows returned by `get_resources(["iam"])` | **3** — 2 `instance-profile`, 1 `oidc-provider` |

The last row is what makes the finding specific: the tagging API is not blind to IAM as a service,
it is blind to `iam:role`. 102 tagged roles exist and none is indexed, so this is a property of the
type in this region and not of our tagging.

**Policies — structurally untaggable.** This one is stronger than "not indexed":

* `CreatePolicy`'s input shape has **no `tags` member at all** — `['clientToken', 'definition',
  'description', 'enforcementMode', 'name', 'policyEngineId', 'validationMode']` — while
  `CreatePolicyEngine` and `CreateGateway` both have one. The policy was never taggable at create
  time, and the ledger was right to record it without tags.
* `TagResource` on the policy ARN returns `AccessDeniedException: not authorized to perform:
  bedrock-agentcore:TagResource` for an **AdministratorAccess** principal — and the *identical*
  action succeeds on a gateway ARN from the same session (`ListTagsForResource` on the gateway
  returns all four tags). An AccessDenied that an administrator cannot fix is not an authorization
  outcome; it is "this resource type does not support tagging" wearing an authorization error's
  name. Recorded because it is a trap: read alone, that message sends you to the IAM policy.

### Why the FAIL was a correct fact and a wrong verdict

The check's *statement* was accurate — those six are not in the index, and the teardown's ledger
channel is load-bearing for them. Its *verdict* was not, because `06_verify.py` is the idempotent
precondition Phase 3+ runs before every phase and Phase 5 re-runs after every restore. A check that
fails permanently, for a reason no action can change, is a check that trains its reader to ignore an
rc=1 — and the same rc=1 is what a genuine mid-phase drift will use.

`04_gateway.py` had already answered the same question for gateways in the opposite direction
(*"gateways ARE indexed (2 found by tag)"*), which is what makes this a per-type property rather
than a global one.

### The fix

The coverage question is split by type, and each half is asserted where it can actually fail:

* **Types the index covers** — gateway, gateway-target, lambda, policy-engine — remain a hard
  assertion. A ledger entry of one of these types absent from the sweep is real drift and still
  fails.
* **Types measured blind** — `iam-role`, `policy` — are checked on the channel that *can* see them
  instead of being excused: `list_role_tags` must return the four project tags for every role, and
  the policy must be present via `get_policy`. So the coverage gap costs no assertion strength; it
  moves it.
* Each exemption's **premise is re-tested on every run**, which is the part that keeps this from
  being a waiver. `TAG_INDEX_BLIND[<kind>] premise still holds` asserts that the blind type is
  *still* absent from the sweep; if AWS starts indexing `iam:role`, that check fails and says the
  exemption is obsolete and the hard assertion should be extended. An exemption whose cause has
  gone away is an assertion silently switched off, and this is what stops that.
* The role-tag replacement channel asserts **equality** on all four project tag keys, not a subset:
  a role carrying another run's `RunId` would be swept by an `--all-runs` teardown, and a wrong
  `ExpiresAt` would let one outlive the 72 h TTL the isolation rule rests on.

This is the same treatment `99_teardown.py` already gives `logs` resources — sweep them on a
channel that sees them, and state coverage per type in `teardown_log.json` rather than claiming
"zero tagged survivors", which would be true and misleading. (That sweep was originally justified
by `SWEEP_TYPE_FILTERS` supposedly omitting `logs`. It does not, and neither did the constant do
anything — DEV-P2-07. The `logs` sweep is still required, for the two reasons recorded there:
deliveries carry no ARN in the ledger, and `put_delivery_*` tags are create-time-only, so an
untagged orphan is unreachable by any tag sweep.)

### Consequence for the "zero survivors" claim

Unchanged in strength, but its wording now has to be per-type, which is the honest form. Gateways,
targets, the Lambda and the policy engine are provable on two independent channels. IAM roles are
provable on the ledger channel plus a direct `get_role`, and policies on the ledger plus
`get_policy` — for policies the ledger is not merely load-bearing, it is the **only** channel, since
the resource cannot carry a tag at all.

### Verification

`06_verify.py` → **42/42 PASS** (was 34 PASS / 1 FAIL), including the two premise arms and five
per-role tag-equality arms. The check count rose because the single failing assertion was replaced
by seven that can each fail for one identifiable reason.

---

## DEV-P2-05 — the F6 pairing assertion's ignore list existed in two copies, and the field that
## exposed it was added to only one

### What happened

`04_gateway.py --ensure` created both gateways READY and then **exited 1** on its own pairing check:

```
FAIL: the two gateways differ in more than policyEngineConfiguration, so a paired F6 difference
      would not isolate the policy hops:
       - workloadIdentityDetails: {'workloadIdentityArn': '…/workload-identity/grx-gw-…-zpkfmpwo9n'}
         != {'workloadIdentityArn': '…/workload-identity/grx-gw-nopolicy-…-x1gqmvenpz'}
```

`workloadIdentityDetails` is service-assigned per gateway, so it can never be equal across a pair.
Adding it to the ignore list is right, and "I looked at it and it seemed like identity" is not a
measurement. Two problems came out of checking properly.

**First: the grounds were verified, not assumed.** The two ARNs were compared segment by segment:

| property | result |
|:---|:---|
| prefix up to the last `/` | **byte-identical** across the pair (`…:workload-identity-directory/default/workload-identity`) |
| final segment | **exactly the gateway id** for both |

So the field is a restatement of `gatewayId` — already ignored — in ARN form, and ignoring it hides
nothing. That is now `workload_identity_is_pure_identity()`, called by `04_gateway.py` *and*
`06_verify.py` on every run, so the justification is checked rather than written: a tail that stops
matching the gateway id, prefixes that diverge (two gateways in different workload-identity
directories is a *configuration* difference wearing an identity field's name), or a **new key** in
the structure all fail it. The whole dict is checked rather than the one key I expect, because a
service-side addition is exactly the drift a `details["workloadIdentityArn"]` read would skip.

**Second, and worse: there were two ignore lists.** `04_gateway.py` and `06_verify.py` each carried
a literal copy, and `06_verify.py` re-runs `04_gateway.diff_configs` against the live pair. Adding
the field to one left the other asserting on it, so `06_verify.py` would have failed on
`workloadIdentityDetails` *immediately after* the creator's pair check passed — and the natural
reading of that ("the verifier disagrees with the script that just built the pair") is wrong and
expensive to chase. Hoisted to a single `PAIR_IGNORE` in `04_gateway.py`, which `06_verify.py` now
imports.

### Why an ignore list is the dangerous part of an assertion

An ignore list is the one component of a check that can be *widened* until the check asserts
nothing, and each widening looks locally reasonable. The admission rule is now written next to the
list and is narrow: a field belongs there only if it **cannot** be equal for two distinct gateways —
service-assigned identity or a timestamp — never one that merely happens to differ today. A field
admitted on the weaker test would let a real configuration difference through, and F6's paired
difference would then carry an unknown bias that looks internally consistent in *both* arms and is
invisible in the results.

### Verification

New `infra/tests/test_pair_ignore.py`, 17 arms, offline:

* the live pair's shape is accepted; each of the four ways the justification could stop holding is
  **rejected** (tail ≠ gateway id, divergent prefixes, an added key, a non-dict structure), plus a
  missing ledger id, which must not read as agreement;
* the negative half of the list — `authorizerType`, `exceptionLevel`, `protocolConfiguration`,
  `protocolType`, `roleArn` are asserted **absent** from `PAIR_IGNORE`, since each would move
  latency if it differed;
* the source-inspection arm pinning `06_verify.py` to `mod.PAIR_IGNORE` with no local literal —
  the divergence is invisible to any behavioural test that exercises only one of the two scripts;
* the vacuity arm (`feedback_vacuous_test_check`): both guards must be able to fail, so
  `diff_configs` is separately shown to still report a streaming-configuration mismatch under the
  ignore list. If `PAIR_IGNORE` ever swallowed `protocolConfiguration`, F6 would silently mix
  time-to-first-byte with time-to-last-byte.

`infra/tests` 44 → **61 collected**, floor raised to 61 in `verify_phase0.sh`. `04_gateway.py
--ensure` re-run: pair check passes, and the tag-index question it was written to answer came back
**gateways ARE indexed (2 found by tag)**.

---

## DEV-P2-06 — `put_delivery_source`/`put_delivery_destination` accept `tags` only on the create
## path, so `07_traces.py --ensure` was not idempotent, and its collision guard was asking the
## wrong question

### What happened

`07_traces.py --ensure` failed on the shared XRAY destination:

```
ConflictException: Tags can only be provided when a resource is being created, not updated.
```

The tempting reading is "the shared destination already exists because both gateways point at it,
so skip tagging that one". That reading is wrong, and the measurement says so. Both directions were
tried against an **existing** delivery source:

| call on an existing resource | result |
|:---|:---|
| `put_delivery_source(name=…, logType=…, resourceArn=…, tags={…})` | `ConflictException` — tags on update |
| `put_delivery_source(name=…, logType=…, resourceArn=…)` (no `tags`) | **200, accepted** |
| `tag_resource(resourceArn=<source arn>, tags={…})` | **200, accepted** |

So `put_delivery_*` is a **create-or-update** operation whose `tags` member is create-only. The
consequence is general, not specific to the shared destination: **every** delivery resource this
script makes would fail its own re-run, all four sources and all three destinations. `--ensure`
was non-idempotent by construction, and the shared destination was merely the first resource to
reach the second `put_*` of its life. This is the second-instance shape from
`feedback_second_instance_bugs`: the first pass through a templated creation path works and the
second breaks, so the bug stays invisible until exactly the situation the script exists for —
restoring state after F7-5 turns tracing off.

### The fix, and why it is not a `try/except ConflictException`

`put_tagged()` decides by **existence**, probing `get_delivery_source`/`get_delivery_destination`
(both take `{name}` only, so the probe is exact and free) and passing `tags` only when the resource
is absent. Catching the exception instead would have been shorter and worse: `create_delivery`
raises `ConflictException` too, for an entirely different cause (a delivery already joining that
source to that destination), so a handler keyed on the exception type — or worse on its message
text — would silently absorb a real conflict in a neighbouring call. An error string is not an API.

`reconcile_tags()` then calls `tag_resource` unconditionally. This is the part that matters for
teardown: a resource created by the *pre-fix* script, or by a run killed between `put_*` and its
tagging, exists **untagged**, and an untagged resource is invisible to the tag sweep that
`99_teardown.py` uses to prove zero survivors. Deciding "it exists, so nothing to do" would have
left those permanently unswept.

### The second defect the first one uncovered

With tagging fixed, `--ensure` failed again — this time the collision guard refused **5 of our own
resources**, left behind by the attempt that had just crashed, reporting them as resources that must
not be reconfigured. The guard was comparing **names**: a name that exists and was not created by
this invocation was treated as a stranger's.

That conflates two cases with opposite correct answers:

* a *pre-existing* resource belonging to one of the ten live `harness_*` deliveries — must never be
  touched, which is the hard isolation rule;
* *our own* resource from an interrupted attempt of *this same run* — must be reconciled, because
  that is what `--ensure` means.

The failure mode was the expensive one. It blocked the resume path, and the obvious way to unblock a
resume ("just skip the check") weakens the exact guard that protects ten live resources belonging to
another system. So ownership is now decided by **tag**, not by name: `collision_check` builds
`name -> arn` for everything that exists, reads each one's tags, and excuses a colliding name only
when `Project == guardrails-doc-validation` **and** `RunId == <this run>`. Unreadable tags or a
missing ARN are treated as **not ours** — fail closed, since the cost of wrongly claiming ownership
is reconfiguring another system's delivery, while the cost of wrongly disclaiming it is a printed
refusal.

Note the interaction with the first defect: ownership-by-tag only works because `reconcile_tags`
guarantees our resources actually carry the tags. The two fixes are one fix.

### Verification

`07_traces.py --ensure` completes: 4 deliveries (TRACES + APPLICATION_LOGS on both gateways), both
gateways symmetric, `--verify-only` green. Re-run immediately — **idempotent**, no conflict.
`06_verify.py` 42/42 PASS. Cost $0: delivery objects are free, ingestion is billed, and Phase 2
sends one request.

---

## DEV-P2-07 — `SWEEP_TYPE_FILTERS` was a constant nothing applied, and three files reasoned from it
## to the opposite of the truth

### What happened

The fixed `07_traces.py --ensure` printed a new line:

```
tag index     9/9 of our ARN-bearing `logs` resources are visible to the tag sweep
```

which **contradicted the docstrings of three files**, all of which stated that `logs` resources were
structurally invisible to the tag channel. Following the contradiction rather than the output:

```python
# lib/testbed.py
SWEEP_TYPE_FILTERS = ("bedrock", "bedrock-agentcore", "lambda", "iam")   # "the type filters
                                                                        #  the teardown sweep uses"
def sweep_by_tag(f, run_id):
    ... get_resources(TagFilters=[...])          # <-- no ResourceTypeFilters, ever
```

`sweep_by_tag()` never passed `ResourceTypeFilters`. The constant constrained nothing, was read by
nothing, and `logs` being absent from it meant nothing — yet `07_traces.py`, `99_teardown.py` and
`06_verify.py` each carried a paragraph of reasoning **derived** from it, and `99_teardown.py`'s
third sweep channel was justified entirely by it. This is `feedback_no_deploy_path_no_component` in
its purest form: a configuration nothing applies does not exist. Here it was worse than
non-existent, because it was load-bearing for prose.

### The measurement that replaced it

Every ledger row of the live run, cross-checked against the sweep by ARN, us-east-1, run
`r20260810T130945Z`:

| kind | in sweep | note |
|:---|:---|:---|
| gateway | 2/2 | |
| policy-engine | 1/1 | |
| lambda | 1/1 | |
| log-group | 2/2 | `logs` — the kind said to be invisible |
| delivery-source | 4/4 | `logs` |
| delivery-destination | 3/3 | `logs` |
| **iam-role** | **0/5** | not indexed; the old list claimed `iam` was covered |
| **policy** | **0/1** | not indexed; ditto `bedrock-agentcore` |
| delivery (4), gateway-target | — | **no ARN in the ledger**, so cross-checkable in neither direction |

The two kinds the old constant claimed were covered are precisely the two that are blind
(DEV-P2-04), and the kind it was cited as excluding is fully indexed. The constant is deleted and
replaced by `TAG_INDEX_BLIND_KINDS`, a dict whose *values are the measurements*, with the admission
rule stated: an entry needs a measurement and a named replacement channel, and `06_verify.py`
re-tests each premise on every run.

### The reporting bug inside the fix

The first version of the new coverage print filtered the ledger to rows that have an ARN and
reported `13/13`. That number is worse than the prose it replaced — it reads as a complete coverage
claim while quietly excluding the 4 deliveries, which record **no ARN** and are therefore verifiable
on no channel at all. The print now reports `9/9` cross-checked plus an explicit `4 ledger row(s)
carry no ARN, so they cannot be cross-checked`, naming them, and stating that teardown deletes them
by recorded id so the gap is in the *check's* reach and not the delete path. Per
`feedback_label_must_match_computation` a numerator and its label must describe the same set; and an
unstated exclusion reads as coverage.

### The channel that survives on different grounds

`99_teardown.py`'s third channel is still required, but for two reasons the false one was hiding:

1. **Deliveries record no ARN**, so the ARN-keyed cross-check cannot see them either way.
2. **`put_delivery_*` tags are create-time-only** (DEV-P2-06), so a resource left by a run that died
   between the `put_*` and its `tag_resource` exists **untagged** — and an untagged orphan is the one
   thing no tag sweep can find, however complete its index.

Both are properties of the resource kind, and both are now written where the channel is defined.

### Verification

All five executable sites rewritten (`lib/testbed.py`, `infra/07_traces.py` ×2,
`infra/99_teardown.py` ×2) plus the DEV-P2-04 paragraph that had cited the constant as precedent.
`grep SWEEP_TYPE_FILTERS` now matches only prose recording this correction — no executable reference
survives, which matters because the constant's deletion would otherwise have turned every remaining
`T.SWEEP_TYPE_FILTERS` into an `AttributeError` on a live path, including in `99_teardown.py`, the
one script that must never fail to run (`feedback_guard_tool_exit_codes`). `07_traces.py --ensure`,
`--verify-only` and `06_verify.py` (42/42) all re-run green.

---

## DEV-P2-08 — the evidence writer, not the AWS call, is what broke the first billable request

### What happened

`08_smoke.py --run` — the project's first billable call — succeeded against the gateway and then
died:

```
FileNotFoundError: [Errno 2] No such file or directory:
  '…/evidence/r20260810T130945Z/infra/P2-08-smoke/0002_mcp:notifications/initialized_ok.json'
```

`EvidenceStore.add()` names each file `<seq>_<operation>_<ok|err>.json`. For a control-plane call
`operation` is a boto3 method name (`create_gateway`) and is always filename-safe. For an MCP call it
is the **JSON-RPC method**, and every MCP method except `initialize` contains a `/`:
`notifications/initialized`, `tools/list`, `tools/call`, `prompts/list`. Interpolated into a path a
`/` is a directory separator, so the writer asked to create a file inside a directory that does not
exist.

This is the worst possible placement for the failure. The request had already been sent, answered and
billed; what failed was the **archive of it** — the one thing this module exists to guarantee. An
oracle reading "no evidence" cannot distinguish "the call was never made" from "the call was made and
the recorder crashed".

### Why nothing caught it earlier

`initialize` is the only MCP method with no `/` in its name. It is also the first call of every
session. So record `0001` wrote successfully on every previous exercise of the path, and the run died
on `0002` — a single passing case that passed for a reason which does not generalise, i.e.
`feedback_vacuous_test_check` seen from the other side: the test was not vacuous, the **sample** was.
`lib/tests/test_evidence.py` had 25 arms over `capture()` and not one over an MCP-shaped operation
label, because `capture()` takes a boto3 method name by construction while `lib/mcp.py` builds its
`Record` directly.

### The fix

`evidence.safe_component()` maps anything outside `[A-Za-z0-9._-]` to `-`, strips leading and
trailing `-`/`.`, and falls back to `unnamed`. Three deliberate choices:

* **Total, not targeted.** Replacing only `/` leaves the identical latent break for the next
  operation label containing a `:`, a space or a `*`. The set of characters that can appear here is
  not ours to enumerate — it comes from whatever protocol a future family speaks.
* **Applied at the writer, not at the caller.** `lib/mcp.py` is not the only thing that can build a
  `Record` by hand; the invariant belongs where the path is constructed.
* **Lossy in the name, exact in the body.** `rec.operation` keeps `mcp:tools/call` verbatim, so an
  analysis joining on operation is unaffected — the filename is navigation, not data. `rec.path` is
  set from the sanitized name so it still resolves: a writer that sanitized the name but recorded the
  raw one would leave every MCP row pointing at a nonexistent file, silently, until analysis.

Traversal falls out for free: `../../etc/passwd` becomes `etc-passwd`, and `.`/`..` cannot be
produced.

### The aborted attempt's evidence was kept, not deleted

Record `0001` from the crashed attempt documents a call really made against the live gateway, with a
real session id and request id. It was moved to
`evidence/<run>/infra/P2-08-smoke-aborted-attempt-01/` with a README explaining the crash, rather
than deleted (it is real observation) or left in place (sequence numbers restart at `0001` each run,
so two different `0001` records from two attempts under two filename schemes would have shared one
case directory).

### Verification

10 new arms in `lib/tests/test_evidence.py`, **39 passed**:

* every method the harness sends — parametrized over all 7, because `initialize` passing is exactly
  what hid the bug — is written without raising, lands **inside** its case directory, and keeps its
  exact operation in the body;
* `rec.path` resolves to a file that exists;
* `safe_component` cases including the two that must be **untouched** (`create_gateway`,
  `describe_vpc_endpoint_services` — a sanitizer that mangled the common case would rename 9,562
  existing evidence files), plus the property form: no separator, never empty, never `.`/`..`;
* the **mutation arm** — `safe_component` monkeypatched to the identity, and the write must then
  raise. Without it the arms above would also pass against a sanitizer that did nothing, since the
  failure would come from the filesystem rather than from the code under test. If that arm stops
  raising, the guard has become decoration.

`08_smoke.py --run` then completed and the **Phase 2 gate is satisfied**: benign `tools/call` allowed
end to end on both gateways (831 ms main, 432 ms nopolicy, with request ids), the echo round trip
confirms `context.output.*` is drivable, and a span carrying each gateway's ARN appears in
`aws/spans` (3 s main, 90 s nopolicy — n=1 per gateway, explicitly **not** the F7-6 publish-lag
measurement, which is n=30 with p50/p90/max).

---

## DEV-P3-01 — the gateway data plane had no rate ceiling and no retries, and both guards read as clean

Found while preparing F4, **before** the first of its ≤1,440 `tools/call` requests was sent. Two
independent holes on the same seam, each of which reports success while doing nothing.

### Hole 1: `wait("InvokeGateway")` was a no-op

`lib/awsclients.RateLimiter.wait()` returns `0.0` for an operation absent from `RATE_LIMITS`. The
gateway data plane was absent, so a call site reading `lim.wait("InvokeGateway")` would have paced
nothing while *looking* rate-limited — `feedback_guard_tool_exit_codes` in its purest form: a guard
that cannot run must not report clean.

Fixing it honestly required knowing what AWS actually publishes, so Service Quotas was queried live
(`ServiceCode=bedrock-agentcore`, us-east-1, 2026-08-11, **184 quotas**). For this path it publishes
**only concurrency**:

| quota | value |
|:---|--:|
| Tool-call/tool-list concurrent connections | 1000 |
| Tool-call/tool-list concurrent connections per gateway | 1000 |
| Tool-call/tool-list/tool-search payload size | 6 MB |

There is **no per-second rate anywhere** for it. The one rate mentioning tool calls — *"Rate of
search-based tool-call requests = 25/s"* — governs tool **search**, a different operation this
project never sends; citing it would have labelled our pacing with a ceiling belonging to something
else (`feedback_quantify_qualifiers` — the number has to be the right number).

So the entry is `"InvokeGateway": 10.0` and it is listed in `SELF_IMPOSED_LIMITS`. 10/s is a **chosen
floor, not a discovered one**: one serial client at ~10 req/s, two orders of magnitude under the
concurrency ceiling, making F4's 1,440 calls ~2.5 minutes of paced traffic rather than a burst. The
key is `InvokeGateway` because that is the real IAM action name (`infra/01_iam.py:213,261`); the wire
operation has no botocore operation name at all, since it is a signed POST rather than an SDK method.

### Hole 2: every data-plane transport failure got zero retries

`lib/mcp.py`'s pool is built `retries=False` **deliberately** — a transparently retried POST reports
one duration covering several attempts, and a policy denial that arrived on attempt 3 would be
recorded as if it arrived immediately. Consequence: every retry decision on this plane lands in
`checkpoint.is_retryable`, which works from an **allowlist** and classifies anything it cannot
identify as permanent.

`McpTransportError` carried `http_status`, `request_id` and `body` — and neither `error_code` nor
`error_class`. So it matched no branch and was permanent. Worse, `_post` **already computed** the
underlying class name and folded it into a prose message, discarding it as an attribute:

```python
except Exception as exc:
    err = f"{type(exc).__name__}: {exc}"        # identity present, then thrown away
...
raise McpTransportError(f"POST … failed before a response: {err}")
```

That is **DEV-P1-11 exactly**, on the second plane. On the control plane the same shape meant an
`EndpointConnectionError` reached `is_retryable` unidentifiable, and an ~80 s local outage burned
**3,378 Phase 1 trials with zero retries** against a policy that would have absorbed it whole — at
rc=0, because a smaller denominator is not an error.

### The fix

* `McpTransportError` gains `error_class`, and `_post` passes the class name it already had. It stays
  **empty** for the raises that are genuinely our own defect (missing session id, absent credentials,
  a gateway whose session configuration is not what the ledger recorded) — retrying a bug just spends
  the rate budget three times before failing identically.
* `RETRYABLE_TRANSPORT` gains the urllib3 names. They are **measured, not recalled** — real failing
  connections through a real `PoolManager` under urllib3 2.7.0:

  | trigger | class raised |
  |:---|:---|
  | invalid TLD (fails in DNS) | `NameResolutionError` |
  | closed loopback port | `NewConnectionError` |
  | unroutable RFC 5737 TEST-NET-1 address | `ConnectTimeoutError` |

  plus `ProtocolError` (mid-flight close) and `SSLError`. `ReadTimeoutError` and
  `ConnectTimeoutError` collide **by name** with botocore's, which is why one set serves both halves;
  the collision is a naming coincidence, not a shared class, and `error_code()` compares names.
  `MaxRetryError` and `ClosedPoolError` are deliberately **absent**: the former cannot be raised by a
  `retries=False` pool, and the latter means we closed the pool ourselves — our defect, so permanent.

### Verification

`lib/mcp.py` had **no test module at all**, so the seam being fixed had zero coverage. New:
`lib/tests/test_mcp_retryability.py`, **11 arms**, asserting both halves — a real transport failure
must arrive retryable, and our own defects must stay permanent — plus `run_trial` end-to-end (fails
twice, succeeds on the third, recorded as one usable trial with `attempts=3` and 5 s/10 s linear
backoff). `test_the_measured_urllib3_names_are_on_the_allowlist` **re-derives** the class names from
real failing connections instead of trusting the list above, so a urllib3 rename fails the test
rather than silently losing trials; it lifts `conftest.no_aws`'s socket block for itself alone, since
that block is one of the failure modes being exercised, and asserts `"RuntimeError" not in seen` so
the test cannot pass by measuring the fixture. `lib/tests/test_checkpoint.py:343` is parametrized over
`RETRYABLE_TRANSPORT` itself, so the four new names were covered on both wrapper paths automatically.

Both fixes were **mutation-checked** by reverting each and re-running: dropping `error_class=err_class`
at the raise site → 8 failures; shrinking the allowlist to botocore-only → 6 failures. Full library
suite **639 passed, 1 skipped**. `verify_prereg.py` still green (`a2136a9d…`, 189 assertions) —
neither `lib/mcp.py` nor `lib/checkpoint.py` is a sealed bound artifact.

### The redaction gate was already failing, and adding a test made it visible

Running `check_redaction.py` after the edits returned **rc=1 with 6 findings** — one of them mine,
five pre-existing. Worth recording precisely because of how nearly it was missed: the first look at
the output was through `| tail`, which reported `rc=0` — the exit code of `tail`, not of the gate.
That is `feedback_batch_loop_exit_code` in miniature, and the gate's whole value is its exit code.

The one that was mine: `test_mcp_retryability.py` used a private-range literal as its unroutable
target. Replaced with **RFC 5737 TEST-NET-1** (`192.0.2.0/24`), the block IANA reserves for
documentation — it fails with the identical `ConnectTimeoutError` (verified) and is guaranteed never
to be routed, whereas a private-range literal may name a real subnet. Then the *explanation of that
fix* tripped the gate a second time, by spelling the private range out as an example. The gate's own
source warns about exactly this ("an earlier draft spelled them out here to be helpful and thereby
created two fresh findings in this very file"); the paragraph now says which range without writing it.

The other five were pre-existing false positives in offline fakes: AWS's **published example account
ID** inside `FakeAC`'s synthetic `CreatePolicy` response and its stubbed STS, and a `gr-` guardrail
identifier whose 12-digit run has the same shape as an account ID. Waived rather than redacted, with
the reason written per entry, because these fakes stand in for real API responses — a placeholder ARN
would be a shape the service cannot return, and `testbed.unmask_arn` *requires* 12 digits and raises
otherwise, so a redacted stub would make the fake unusable. Verified before waiving that none of the
three account IDs belonging to this organization appears in any of those lines.

Loosening the patterns was rejected: it would blind the gate across all 280 files to excuse five
known fixtures. Each waiver matches a narrow substring, and that narrowness is **mutation-checked** —
planting a real account ID on a *different* line of a waived file still fails (rc=1), and removing it
returns rc=0. Without that check the waivers would be indistinguishable from silencers.

### Why this is a deviation and not just a commit

The pre-registration's cost and pacing notes say the binding constraint on Phase 3 is "the 5/s API
rate ceiling, not spend". That sentence was written about the **control** plane and silently did not
cover the plane F4 spends most of its calls on. The ceiling now exists, is labelled ours rather than
AWS's, and the retry policy that the pre-registered `tolerate_failures: 0` implicitly depends on is
reachable for the first time on this plane.

---

## DEV-P4-01 — four cases pre-registered a per-trial score harvest, and neither measured surface publishes one

**Scope, stated first because an earlier draft of this entry overreached.** Three surfaces could
carry a guardrail score. Two are measured and neither publishes one. The third — CloudWatch
**metrics**, where §6.2 explicitly lists `ConfidenceScore / ConfidenceThreshold` under
`AWS/Bedrock-AgentCore` — is **not yet measured**; it is exactly what **F7-1** tests. So this
entry justifies the instrument change on the two surfaces a per-trial harvest could plausibly
come from, and **F7-1 is the measurement that decides whether "no surface" is the right phrase
at all**. Note in advance, so the result cannot be spun either way: a CloudWatch metric is a
per-minute *aggregate*, so even a published `ConfidenceScore` metric would not restore the
**per-trial** harvest F2-2/F2-3 and F1-18 were written around — it would change this entry's
reach without changing the instrument change below.

### What happened

Four sealed cases name the same instrument in their methods:

| Case | Sealed method, verbatim |
|:--|:--|
| F2-2 | "n=300 identical inputs, **harvest per-trial ConfidenceScore**, estimate pmf" |
| F2-3 | "stratify F2-2 trials **by observed score**; `variance_decomposition()`" |
| F2-4 | "mutation arm: tau **inside vs outside observed support**, n=300 each" |
| F1-18 | "**harvest scores** from F2/F3 runs; set-membership test on the union" against the lattice `{0,.2,.4,.6,.8,1.0}` |

Two independent measurements now say that score does not exist as an observable **on the response
and telemetry surfaces**:

1. **F2-5** (verdict FALSE, `results/phase1/F2-5.json`) measured the ApplyGuardrail response
   surface: content filters expose `confidence` and `filterStrength` as **four-value enums**
   (`NONE/LOW/MEDIUM/HIGH`). There is no numeric content-filter score on that API.
2. **`f7_observability/00_span_shape_probe.py`** (2026-08-11, `results/span_shape_probe.json`)
   read 60 real spans for our gateway from `aws/spans`, produced by the F4 truth-table run's
   traffic through guardrail-bearing policies in ENFORCE. **58 distinct attribute paths, and
   zero matches for `score`, `confidence`, `threshold`, or `guardrail`.** The approved plan's
   predicted attribute prefix `aws.agentcore.policy.guardrails.<category>.scores` is **absent**.

The span path is not a poor harvest surface; it is the *only* remaining candidate, because the
policy path is where a guardrail-in-policy threshold is evaluated, and the span is the only
per-request record of that evaluation. What it publishes is the **decision**
(`aws.agentcore.policy.authorization_decision`, `authorization_reason`,
`determining_policies[]`, `log_only_matched_policies[]`,
`log_only_decision_flipping_policies[]`) — never the quantity the decision was computed from.

### It corrects a provenance, not a size

The machine-checked `corrects:` field belongs to `deviations_from_plan` inside the sealed
`PREREGISTRATION.yaml`, and only the eight `DEV-P0-*` entries — the ones that corrected the plan
*before* it was sealed — carry it. This entry is a Phase 4 entry in this file, so it is
classified in prose and is deliberately **not** given a `corrects:` line: a field that looks
machine-checked but is read by nothing is worse than no field, and `verify_prereg.py` would
never see it.

In that vocabulary it would be `provenance`. Nothing about a sample size is wrong. n=300 per `determinism_cell` is reachable and F2-1 just
reached 630. What is wrong is the **provenance of an instrument**: the plan and the
pre-registration both assumed a numeric score was observable, and neither had measured it. That
assumption came from the document under test — which asserts the six-value lattice — and was
carried into our own method sections without a check. This entry is the correction of that
lineage, not of a number.

### The instrument change, stated before the data

F2-2/F2-3/F2-4 move from a **direct harvest** to a **threshold sweep**, which observes the same
latent variable through the decision instead of reading it:

* a guardrail-bearing policy whose condition carries a numeric `threshold` τ is the only knob
  that admits a numeric value into the evaluation at all;
* for a **fixed input** repeated n times at **fixed τ**, a mixed set of decisions proves the
  latent score took ≥2 distinct values, *without ever observing one*. That satisfies F2-2's
  `DISTINCT_AT_LEAST(2)` on the same logic its oracle already uses — one counterexample to
  degeneracy suffices — and it is strictly conservative: a constant decision column is
  consistent with either a constant score or a varying score that never crossed τ, so this
  instrument can **only under-report** non-determinism.
* F2-3's strata become τ-bands rather than score values. A band is coarser than a value, and
  coarsening can only ever **hide** a mixed stratum, so a TRUE from this instrument is weaker
  than the sealed TRUE and its record must say so in the verdict, not in a footnote.
* F2-4 is the case this change *helps*: its oracle is already about τ placement, and a sweep is
  a more direct test of "flip rate tracks τ" than inferring support from harvested values.

**F1-18 cannot be rescued this way and is not being rescued.** Its claim is that observed
scores lie on a six-value numeric lattice; a sweep observes no scores. The honest outcome is
that the claim is **not measurable on either published surface**, which is itself a finding
about the document — it asserts the precision of a quantity the service does not expose — and
belongs in the v1.3 amendment pass rather than in a case file with a manufactured verdict.

### What this changes about ordering, and why that is the expensive part

The probe also settles a dependency the plan had backwards. Every one of these four cases was
scheduled in Phase 4 *before* the F7 observability family, on the assumption that the score
came from the response. It comes from telemetry or nowhere, so **F7 is upstream of F2-2/F2-3/
F2-4 and of F3-10**, and F7-5 (tracing off → spans absent) is the mutation that makes any
span-derived reading non-vacuous. The remaining Phase 4 order is therefore F7 first.

Two other cases inherit evidence from the same 60 spans, and both are now cheaper than planned:

* **F3-10** asks whether §7.1's per-request score↔label join is recoverable from telemetry. The
  spans carry `aws.request.id` per row, so the *decision* is joinable per request — and carry no
  score, so the *join §7.1 actually needs* has no left-hand side. That is F3-10's FALSE
  direction, indicated but **not scored here**: it gets its own script, which must also attempt
  the metrics-only reconstruction its sealed method names.
* **F6** was planned around client-side timing. The spans publish `latency_ms`,
  `overhead_latency_ms` and `execute_tool_latency_ms` **per request**, server-side — which
  measures policy overhead without the client's own network variance in the number. Using them
  is a second instrument change and will be registered separately once F6 is written; it is
  noted here because it came from this probe, not from the F6 work.

### Verification

The probe is mutation-checked in the only way that matters for a negative result: it refuses to
report `absent` when it cannot distinguish absence from silence. `traces_delivery_live` is
checked **first**, and a down delivery yields `delivery_down`, not `no_score_field` — the
distinction F7-5 exists to establish, borrowed so a missing precondition cannot be read as a
measurement. It found 60 spans with the delivery live, so `no_score_field` is a reading of
present-and-parsed telemetry, not of an empty query. Attribute matching runs over **flattened
leaf paths** of every span unioned together, not one span's top-level keys, so a score nested
inside a list or an attribute bag would still have been found; the full 58-path inventory is in
`results/span_shape_probe.json` and can be re-checked against any future claim that a score is
published somewhere in there.

**Re-measured against a truncation confound (2026-08-11, later).** The probe read the most recent
60 rows of a 120-minute window, and `query_spans` sorts `@timestamp desc` — so a claim of
*absence* from it is a claim about a truncated tail, which is the shape that produced
`feedback_abort_hides_coverage`. The scan was therefore repeated at three settings —
**120 min × 60, 120 min × 500, and 48 h × 500** — and returned the same 58 leaf paths and
**zero** score-ish paths at every one, widening the pattern to `score|confidence|threshold|
severity|strength`. Separately, the `AgentCore.Policy.AuthorizeAction` span — the row that
actually records the policy evaluation — was isolated and its **complete 42-path attribute
inventory** enumerated: it carries the decision, the reason, the determining and log-only policy
lists, the temporal flag, the target resource, the request id and the HTTP status, and **no
score, confidence, threshold or strength attribute of any kind.** The negative result is
therefore a property of the span schema, not of the sample size.

**One claim made from this probe was wrong and is retracted here.** A prose note in `RECONNECT.md`
and in the session log said the measured operations were `InvokeTool`/`InvokeGateway` and that
`AuthorizeAction` spans did not exist. They do: 246 over 48 h, paired 1:1 with `InvokeTool`, and
**27 of them were inside the probe's own original 60-row sample.** The sentence was written from
the single sample span the probe serialises into `sample_span_leaves`, which happens to be an
InvokeTool row; the probe tallies leaf **paths** and never tallied span `name`, so no assertion
covered the claim — `feedback_prose_is_not_verified`, in a file whose whole purpose is to record
where the plan was wrong. **The document is correct on the span name and F7-4 has no amendment
material from it.** The retraction is recorded here rather than only at the two prose sites
because the same probe run is this entry's second pillar, and a reader has to be able to see
which of its readings survived re-measurement and which did not: the score absence survived at
three settings, the span-name claim did not survive at one.

**A byproduct that upgrades two later cases.** The request-id join was measured while checking
the above: **242 of 250 span `attributes.aws.request.id` values (96.8%) match a client-observed
`x-amzn-requestid` already recorded in an F4 or F2-1 checkpoint**, at zero additional cost
because both sides were on disk. One request id carries two spans (InvokeTool + AuthorizeAction).
That is the per-request join F7-4's sealed method calls for and the left-hand side F3-10 needs,
and it gives **F7-5 a specific absent-arm marker** — not "no spans in some window", which a wrong
window would satisfy, but "no span carries any of *these* request ids".

---

## DEV-P4-02 — the two-calendar-day replication rule is waived by the project owner

### What happened

On **2026-08-11** the project owner instructed: *"解除時間日曆硬限制，自由完成，分階段 update repo，我來負責
review and merge"* — lift the calendar hard limit, finish freely, stage the repo updates, and the
owner reviews and merges. That is an explicit, authorized relaxation of a rule this project wrote
for itself, and it is recorded here because a protocol that can be relaxed silently is not a
protocol.

### What is actually waived, and what cannot be

Two different things were both being described as "the calendar limit", and only one of them is a
rule:

1. **The ≥2-separate-calendar-days replication rule** (`PREREGISTRATION.yaml`, enforced by
   `check_amendment_readiness.py`, `MIN_DAYS = 2`) is a **procedural** bar on amending the
   document. It is the owner's to waive, and it is waived. Affected as of this entry: **F4-6**,
   **F2-1**, **F5-7a**.
2. **F3-11 is not a rule and cannot be waived.** Its sealed oracle asks whether configuration
   still holds at **+7 days** and **+30 days**. There is no instrument that reads day 30 on day 0;
   the constraint is the measurement, not a gate in front of it. What the waiver *does* license is
   writing the script now, running its **day-0 baseline arm** now, and leaving the later arms as
   one command against a stored baseline. Target dates stand: **2026-08-18** and **2026-09-10**.

### How the waiver is implemented, and why the gate is left alone

`check_amendment_readiness.py` is **not modified** and `MIN_DAYS` stays at 2. The gate keeps
counting distinct UTC calendar days from evidence and keeps reporting a single-day finding as
short of the sealed rule. A waiver implemented by editing the checker would delete the evidence
that a waiver was ever needed, which is the same defect as a redaction scan that reads zero files
and reports clean.

Instead, a waived finding carries the waiver in its own front matter and in its text: the
authorizing instruction, its date, and the single-day evidence run it rests on. When the v1.3
amendment pass runs, each amended section states whether its evidence is single-day or replicated,
so a reader of the *document* — not just of this repo — can see which corrections are one-day
measurements. If a status in `AMENDMENT_STATUSES` is ever set on a single-day finding, the gate
will go red; that is the intended behaviour, and the resolution is a new status recognised as a
**named, listed exception** rather than a lower `MIN_DAYS`.

### Direction of the bias

This waiver moves risk **towards** the document under test being amended on thinner evidence than
planned, i.e. it makes false amendments more likely and false non-amendments less likely. Stated
plainly because deviations that favour the experimenter's own throughput are the ones most worth
labelling. Nothing about a verdict changes: `evaluate()` never saw the calendar rule, so every
TRUE/FALSE already recorded stands exactly as it did.

---

## DEV-P4-03 — eleven documented metrics are scored NOT_EXERCISED, because inducing them means abusing a shared service

- **Date:** 2026-08-11
- **Data existed:** **for these cases, no.** No CloudWatch metric reading for F7-1, F7-2 or
  F7-3 had been taken when this entry was written; `f7_observability/03_metrics_existence.py`
  was written with the exclusion list in it and this entry was committed **before its first
  non-dry run**. Plenty of data exists elsewhere in the project, so the honest statement is
  not "no data existed" but "no data on the question this deviation changes".
- **Class:** analysis — it changes which observations a sealed oracle is scored on.

### The sealed oracles, verbatim

| Case | Sealed oracle |
|:--|:--|
| F7-1 | "Per metric: TRUE if datapoints appear for our dimensions after traffic that should produce them; FALSE if absent. A documented-but-absent metric is a document defect." |
| F7-2 | "TRUE if Latency/Duration/Invocations/TargetExecutionTime/Throttles/SystemErrors/UserErrors all publish; **FALSE for any absentee**." |
| F7-3 | "TRUE if the namespace (not `AWS/Bedrock`) carries the 7 documented metrics; FALSE if the namespace or names differ." |

F7-1 already contains its own escape clause — "after traffic that should produce them" — so
excluding a metric whose producing condition never occurred is *inside* its oracle, not a
departure from it. **F7-2 does not.** It names seven metrics and says FALSE for any absentee.
Three of the seven cannot be exercised without an act this project refuses, so scoring F7-2
on the exercised subset is a genuine deviation and is recorded as one rather than quietly
folded into the F7-1 reasoning.

### What is excluded and why

The script iterates **29 documented (namespace, metric) pairs** — 7 gateway + 15 policy in
`AWS/Bedrock-AgentCore`, and 7 in `AWS/Bedrock/Guardrails`; 28 distinct names, because
`Invocations` is documented in both namespaces and is a different metric in each. **Eleven of
the 29 publish only when something goes wrong, and are therefore EXCLUDABLE, leaving 18
unconditionally scored.** Both counts are derived from the script's own tables rather than
transcribed, because a count written as prose is a count nothing checks. Per case the excludable
split is: F7-1 **10 of 15** unconditional, F7-2 **4 of 7**, F7-3 **4 of 7**.

**"Excludable", not "excluded" — the rule was corrected after the first read, and it is narrower
than what this entry originally described.** The first implementation applied the exercise basis
in *both* directions, so a metric with no exercise basis was dropped from the conjunction even
when it had published datapoints. That threw away positive evidence about the document: the first
run's payload recorded `MismatchErrors`, `TotalMismatchedPolicies` and `PolicyMismatch` as
`NOT_EXERCISED` while their own rows said `published: true`. An exercise basis exists to stop *an
absence* from being read as a document defect when the producing traffic never happened; it has
nothing to say about a datapoint that exists. The rule is now:

| Observation | Scored as |
|:--|:--|
| published | **TRUE**, whatever the exercise basis |
| absent, basis exercised | **FALSE** — a document defect |
| absent, basis not exercised | **NOT_EXERCISED** — excluded from the conjunction, listed in the payload |

So the eleven are excluded *only if they turn out absent*. This narrows the deviation — fewer
observations are set aside than this entry first claimed — and the direction of the bias is
unchanged, because the correction can only move a metric from excluded to satisfied, never to
absent.

**And it turned out to matter for exactly the three metrics this entry was written about.** With
the scope term fixed (DEV-P4-04), the measured reading over the 13-day project window is that
`Throttles`, `SystemErrors` and `UserErrors` **each return 8 series and 123 datapoints for our
own gateway** — the service publishes them as counters that report zero, so they exist on the
metrics surface without any error ever having occurred. Under the original both-directions rule
they would have been discarded as NOT_EXERCISED; under the corrected rule they are scored, and
they satisfy F7-2's oracle. The refusal to manufacture 429s stands and is still the right call —
but it turns out never to have been necessary for this case, and the entry is left in place
rather than deleted so that the reasoning, and the fact that it was unnecessary, are both on the
record.

The eleven, under seven distinct rationales, listed in full — a deviation whose scope is
summarised is a deviation that grows:

| Namespace | Metric | Producing condition, and why it is not induced |
|:--|:--|:--|
| `AWS/Bedrock-AgentCore` | `Throttles` | Needs HTTP 429, i.e. driving a shared AWS service past its quota. **Refused**: that is a denial-of-service shaped action against a service other systems in this account use. |
| `AWS/Bedrock-AgentCore` | `SystemErrors` | Needs a 5xx from the service. Cannot be induced from a client at all. |
| `AWS/Bedrock-AgentCore` | `UserErrors` | Needs a 4xx — and **F4-6 measured that policy denials are HTTP 200** with JSON-RPC `-32002`, while a bare tool name is HTTP 200 with `-32602`. Neither client-side error this testbed produces is a 4xx. |
| `AWS/Bedrock-AgentCore` | `SuppressOutputs` | Needs a policy with the suppress-output effect. No phase of this project created one. |
| `AWS/Bedrock-AgentCore` | `LogOnlyEvalIncomplete` | Needs an evaluation that cannot complete — the missing-attribute condition F4 hit at policy **CREATE** time, not at request time. Reproducing it means deliberately shipping a broken policy, which would also perturb the axis F4 measures. |
| `AWS/Bedrock-AgentCore` | `MismatchErrors`, `TotalMismatchedPolicies`, `PolicyMismatch` | Same condition as `LogOnlyEvalIncomplete`: a guardrail evaluation failing on missing attributes or type mismatches. |
| `AWS/Bedrock/Guardrails` | `InvocationClientErrors`, `InvocationServerErrors`, `InvocationThrottles` | A client error against `ApplyGuardrail`, a 5xx, and a quota breach respectively — the same three objections as the gateway row. |

The script asserts these counts at import time, so an edit to a metric table that changes
them fails the unit tests instead of silently making this entry wrong.

### Why the alternative was rejected rather than merely skipped

The only way to satisfy F7-2 literally is to generate throttling and errors on purpose. For
`Throttles` and `InvocationThrottles` that means deliberately exceeding a Bedrock quota in an
account that runs other workloads — a denial-of-service against a shared dependency, which no
oracle in this repo authorizes and which the project's own operating rules forbid. For
`SystemErrors` and `InvocationServerErrors` there is no client-side lever at all; a "FALSE"
scored on them would be a statement about the impossibility of the test, not about the
document. That distinction — **untested is not refuted** — is the whole content of this entry.

### How the deviation is implemented, so it cannot be mistaken for a finding

- Every excluded metric appears in each case's payload under `excluded_not_exercised`, with
  its reason, and the count is printed on stdout. Nothing is dropped silently, which is the
  same rule as "a redaction scan that reads zero files must not report clean".
- Each verdict carries `verdict_reading`, which states the verdict is about the *n* exercised
  metrics of the *m* documented and **is not a statement about the excluded ones**.
- The exercise bases themselves are counted **from this project's own evidence tree**, never
  from CloudWatch: a metric reading used to justify its own exercise basis would be circular.
  If a basis is empty, the dependent metrics become NOT_EXERCISED and the case goes
  **INCONCLUSIVE, not FALSE**.
- Two negative controls keep the sweep falsifiable, and both are the **document's own**
  negative claims: `FirstByteLatency` must be absent from `AWS/Bedrock-AgentCore` (the doc says
  outright it is not a valid name), and the seven guardrail metrics must be absent from
  `AWS/Bedrock`. A control that "finds" its target means the matcher is too loose, and the
  affected case yields INCONCLUSIVE rather than a verdict.

### Direction of the bias

**Towards TRUE, i.e. towards the document under test.** Removing candidate absentees from a
conjunction can only make the conjunction easier to satisfy. Stated plainly because a
deviation that makes the subject of the experiment look better is the one most worth
labelling. The counterfactual is on the record: had F7-2 been scored literally, its three
error metrics would almost certainly have read absent and it would have published **FALSE** —
a FALSE that would have said more about our unwillingness to attack a shared service than
about §6 of the document.

---

## DEV-P4-04 — three rounds of invalid readings in the F7 metric sweep: metrics reported absent that its own inventory listed as present (a 500-series cap, then a quoted SEARCH term), then a guard that withheld a verdict over a truncated presence

### What happened

At **2026-08-11T15:11:05Z** the first non-dry run of `f7_observability/03_metrics_existence.py`
published:

```
F7-1: FALSE  scored 2/10  absent=['GuardrailLatency', 'ConfidenceScore', 'ConfidenceThreshold',
      'DenyDecisions', 'LogOnlyMatches', 'DeterminingPolicies', 'NoDeterminingPolicies',
      'TemporalLatency']  excluded=5
F7-2: FALSE  scored 1/4   absent=['Latency', 'Duration', 'TargetExecutionTime']
```

**Both verdicts are retracted.** They are wrong, and the same run's own payload contains the
proof. Every record carries a `name_in_namespace_inventory` field from a *separate* instrument
(paginated `ListMetrics`), and for **eight of the eleven** names reported absent that field was
`true`:

| Case | Reported absent, yet in the inventory |
|:--|:--|
| F7-1 | `GuardrailLatency`, `DenyDecisions`, `LogOnlyMatches`, `DeterminingPolicies`, `NoDeterminingPolicies` |
| F7-2 | `Latency`, `Duration`, `TargetExecutionTime` |

A metric cannot both be absent from a namespace and be enumerated in that namespace's metric
list. The script published a self-contradiction and its guards passed.

### Root cause: a returned-series budget, spent by the first six expressions

`GetMetricData` was called with **one `SEARCH` expression per documented metric — 22 in a single
call**. Multiple expressions in one call share a cap on the number of time series the response
may return. Summing `n_series` across the 22 expressions of the project-window read:

```
278  UserErrors
154  Invocations
 46  AllowDecisions
 14  LogOnlyDecisionFlips
  4  TotalMismatchedPolicies
  4  PolicyMismatch
  0  × 16 remaining expressions
---
500  total, exactly
```

**Exactly 500.** Six expressions consumed the entire budget and the other sixteen returned
nothing. `Invocations` alone matched 154 series because this namespace also carries six
pre-existing gateways and several `harness_*` runtimes; `UserErrors` matched 278. The absences
were produced by our own call shape, and every one of them pointed at §6 of the document.

### Why the message channel did not save us

The project-window response did carry a diagnostic:

```json
{"Code": "PartialData",
 "Value": "The expression may contain partial data as one or more metrics have StatusCode 'Paginated'"}
```

and the script **collected it into the payload as decoration** — a field a reader might notice —
rather than failing the read. That alone is the familiar mistake of recording a warning instead
of acting on it. But the second half is worse, and it is the reason the fix is not "check for
messages":

**the fresh-window read hit the same 500-series cap with an EMPTY `messages` list.** Its
distribution was different — `Invocations` 454, `DenyDecisions` 30, `LogOnlyMatches` 14,
`GuardrailLatency` 2, and 0 for the other eighteen — and it also summed to exactly 500. Two reads
in one run, both silently truncated, disagreeing with each other about which metrics exist, and
only one of them said so. Had the fix been "treat a `PartialData` message as fatal", the fresh
read would still have been trusted.

### The instrument change

- **One metric per `GetMetricData` call.** 22 expressions sharing one budget is the defect; 22
  calls each with one expression cannot starve each other.
- **A `scope` term in every `SEARCH`**, restricting the match to our own resource — the gateway
  id from the run ledger for `AWS/Bedrock-AgentCore`, and a guardrail identifier read from the
  project's own recorded `apply_guardrail` params for `AWS/Bedrock/Guardrails`. This is not only
  a cap workaround: F7-1's sealed oracle says *"datapoints appear **for our dimensions**"*, and
  an unscoped sweep over six other teams' gateways was never the question the oracle asked. The
  unscoped read is still issued, **recorded and never scored**, because it separates "the service
  does not publish this for our resources" from "nobody in this account publishes it".
- **A `trusted` flag per read**, computed from *three* channels, not one: every returned series'
  `StatusCode` must be `Complete`, the top-level `Messages` list must be empty, **and** no
  per-series `Messages` may be present. Any deviation marks the read untrusted.
- **A new guard, `reads_are_complete`**, which turns an untrusted read into INCONCLUSIVE rather
  than into a verdict. A read that cannot be trusted must not be allowed to publish either
  direction.
- **A refusal path.** If no scope term can be established, the script emits INCONCLUSIVE for all
  three cases rather than falling back to the unscoped multi-metric sweep that caused this entry.

### The second retraction: the scope term was quoted, and a quoted SEARCH term is an exact match

The fix above was applied and the script re-run at **2026-08-11T22:31Z**. It published:

```
F7-1: FALSE  scored 7/10  absent=['ConfidenceScore','ConfidenceThreshold','TemporalLatency']
F7-2: FALSE  scored 2/4   absent=['Duration','TargetExecutionTime']
F7-3: FALSE  scored 0/4   absent=['Invocations','InvocationLatency','InvocationsIntervened','TextUnitCount']
```

**F7-2 and F7-3 from this run are also retracted.** F7-1's is not — see below, and the reason
the two split is the whole point of the guard that came out of this.

The scope term was rendered **quoted**: `SEARCH('Namespace="..." MetricName="Latency" "grx-gw-…"')`.
A quoted term in a SEARCH expression is an **exact match against a whole dimension value**, not a
token match inside one. Measured on the live namespace over the same 13-day window:

| Metric | quoted scope | unquoted scope |
|:--|--:|--:|
| `Latency` | 2 series, 21 dp | 10 series, 144 dp |
| `Duration` | **0 series, 0 dp** | 8 series, 123 dp |
| `TargetExecutionTime` | **0 series, 0 dp** | 3 series, 51 dp |
| `Throttles` | **0 series, 0 dp** | 8 series, 123 dp |
| `SystemErrors` | **0 series, 0 dp** | 8 series, 123 dp |
| `UserErrors` | **0 series, 0 dp** | 8 series, 123 dp |

`Latency` carries a `TargetResource` dimension whose value *is* the bare gateway id, so the quoted
form matched it. `Duration` has no such dimension — its only resource dimension is
`Resource=arn:aws:bedrock-agentcore:<region>:<account>:gateway/<id>`, where the id is a substring
and never the
whole value. The guardrail namespace failed the same way and completely: its only resource
dimension is `GuardrailArn`, so all four scored metrics read absent and F7-3 published 0/4 while
its own inventory listed every one of them.

Probed directly against the API rather than reasoned about, for one metric and window: bare token
**1 series**, quoted token **0 series**, quoted full ARN **1 series**, unscoped **16 series**. The
term is now unquoted, so it matches as a token and finds the id inside an ARN.

### The guard that came out of it, and why F7-1 survived both rounds

Two rounds of manufactured absences, two different mechanisms, one shared signature: **zero
series for a metric the other instrument says is published for our own resource.** That is now a
guard, `scope_matches_inventory`, and it turns on a distinction the script had been collapsing:

| Reading | Means |
|:--|:--|
| **0 series** | the SEARCH matched no metric at all → a fact about our matcher |
| **≥1 series, 0 datapoints** | the metric exists and reported nothing in the window → an absence |

`ListMetrics` records the dimension *values* each metric publishes, so for every documented metric
the script can now ask whether our own scope token appears among them. If it does and the scoped
SEARCH returned zero series, the case goes INCONCLUSIVE instead of FALSE. Both retractions would
have been caught by this, from data that was already sitting in the emitted payload.

This is also why **F7-1's FALSE stands**: its three absentees — `ConfidenceScore`,
`ConfidenceThreshold`, `TemporalLatency` — are `name_in_namespace_inventory: false`. They are not
missing from a read; they are missing from the namespace's metric list entirely, on an instrument
with no series cap and no quoting semantics. That reading has now survived a 500-series
truncation, a quoting defect, and the guard built from both.

A third defect was found while wiring the guard, and it is the plainest of the three:
**`reads_are_complete` was declared in `GUARDS` and printed in the dry-run banner from the start,
and the first two runs never evaluated it.** It appeared in `guard_names` in every payload. An
advertised check that does not run reads exactly like a check that passed.

### Round 3: the guard, once it finally ran, failed on a presence

Run 3 — scope unquoted, one metric per call, the new guard wired — published F7-1 and F7-2 as
**INCONCLUSIVE**, on `reads_are_complete`. The single failing read:

| Metric | Window | n_series | n_datapoints | StatusCode | NextToken |
|:--|:--|--:|--:|:--|:--|
| `AllowDecisions` | project, 13 d | 40 | 200 | `Paginated` | none returned |

Every other read in both namespaces came back `Complete`. So a metric with **200 datapoints** —
that is, a metric whose publication was *established* — withheld the verdict for all nineteen
policy metrics and all seven gateway metrics.

That is the same collapse as the exercise basis, in the same script, one direction over:

> A partial read can be **missing** datapoints it should have returned. It cannot **invent**
> datapoints it did return.

Truncation is therefore evidence against an absence and irrelevant to a presence. The guard now
evaluates `untrusted_absences` — the set of metrics scored ABSENT whose read was untrusted — and
is silent about untrusted presences, which are recorded per row as `read_trusted: false` with the
CloudWatch message that made them so. Run 1's error and run 3's error are the two halves of one
misconception: run 1 read a truncated absence as a document defect; run 3 refused to read an
untruncatable presence at all.

Note what this does **not** do: it does not weaken the absence rule. `AllowDecisions` published,
so nothing in F7-1's or F7-2's absent list is affected by the change. Had `AllowDecisions` come
back paginated **and empty**, the case would still be INCONCLUSIVE.

### Class and direction of the bias

- **Class:** measurement — the observation itself was invalid, not its interpretation.
- **Data existed:** **yes, and it is what forced the change.** This is an after-the-fact
  instrument correction, which is the kind most in need of labelling. It is recorded here rather
  than quietly fixed, and the retracted verdicts are preserved verbatim in the evidence tree.
- **Direction:** the defect biased **towards FALSE, i.e. against the document under test.** It
  manufactured eleven document defects, eight of them refutable from the same run's other
  instrument. The correction removes findings from our side of the ledger, not the document's.
- **Direction, round 3:** the over-strict guard biased **towards INCONCLUSIVE**, i.e. towards
  measuring nothing. It is listed separately because it is not the same bias: rounds 1–2 invented
  document defects, round 3 suppressed a reading that had already been made. Both corrections were
  made after seeing the data, and both are recorded here for that reason.

### What actually survives from the first run

The `ListMetrics` inventory, because it is a different instrument with a different limit:
`ListMetrics` paginates cleanly (7 pages, 31 names for `AWS/Bedrock-AgentCore`) and is not
subject to the `SEARCH` series budget. So these readings stand:

- `ConfidenceScore`, `ConfidenceThreshold` and `TemporalLatency` are **absent from the
  `AWS/Bedrock-AgentCore` inventory entirely** — not merely missing from a truncated read. This
  is DEV-P4-01's third surface, and it is the reading that closes it.
- The documented dimensions `Category` and `Filter` are not published in that namespace.
- `AWS/Bedrock/Guardrails` carries 6 names, including an **undocumented `CheckInvocations`**.

### The general lesson, stated so it outlives this case

Two instruments in one payload disagreed, and nothing in the harness compared them. The
contradiction was visible in the emitted JSON before any human read it. A guard that checks a
read against *itself* — did it return, did it parse, did it warn — cannot catch a truncation that
returns successfully with fewer rows. What caught it was one instrument's `true` sitting next to
the other's `absent`. Where a case has two instruments, the check worth writing is the one that
makes them contradict.

---

## DEV-P4-05 — F7-3's negative control tested a claim the document never made, and turned the case INCONCLUSIVE about our own matcher

### What happened

F7-3's sealed oracle is *"TRUE if the namespace (**not `AWS/Bedrock`**) carries the 7 documented
metrics"*. To make "not `AWS/Bedrock`" falsifiable, the first run asserted that the seven
documented guardrail metric **names** are absent from the `AWS/Bedrock` namespace. The control
failed, and F7-3 published **INCONCLUSIVE**.

The control was invalid. Four of those names — `Invocations`, `InvocationLatency`,
`InvocationClientErrors`, `InvocationServerErrors` — are legitimate Bedrock **model-runtime**
metric names, and the document under test *says so itself*: it describes `AWS/Bedrock` as the
namespace that "holds model runtime metrics". So the control demanded the absence of something
the document asserts is present. It could only ever fail, and its failure said nothing about the
document — only that our matcher compared on the wrong field.

The document's claim is about **which namespace guardrail telemetry lands in**. Metric names
collide across namespaces routinely; what distinguishes a guardrail datapoint from a model
datapoint is its **dimensions**.

### The instrument change

The control now asserts that **no metric in `AWS/Bedrock` carries a guardrail dimension** —
`GuardrailArn`, `GuardrailId`, `GuardrailVersion` or `GuardrailName` — read from the dimension
*values* returned by the paginated `ListMetrics` inventory. The name collision is still measured
and reported, as `name_collision_recorded_not_scored`, because it is precisely why the document's
warning is worth making. It is no longer scored.

### Class and direction of the bias

- **Class:** measurement — a negative control that could not pass on the document's own terms.
- **Data existed:** **yes.** The control's failure is what exposed it, so this is an after-the-fact
  correction and is labelled as one.
- **Direction:** the defect biased towards **INCONCLUSIVE**, which is neither for nor against the
  document — it suppressed a reading rather than inverting one. The correction lets F7-3 reach a
  verdict; which verdict, the re-run decides.

### The general lesson

A negative control has to be a claim the subject actually makes. "Guardrail metrics are not in
`AWS/Bedrock`" and "these seven strings do not appear in `AWS/Bedrock`" read alike in English and
are different propositions, and the document itself contains the sentence that separates them.
The control was derived from our paraphrase of the claim instead of from the claim.

---

## DEV-P4-06 — every F6 model arm runs on Nova Micro, because Claude is not invokable in this account

### What was pre-registered, and what runs instead

§1 of the document under test says guardrails are deployed "with backend models (e.g., Claude)",
and §6.1's Hop #3 row cites `InvocationLatency (AWS/Bedrock namespace, model-specific)`. The F6
family's model arms therefore intended to invoke a Claude model. They invoke
`us.amazon.nova-micro-v1:0` instead.

### Why

`bedrock-runtime:Converse` against Claude 3.5 Haiku returns **`ResourceNotFoundException`** in
this account. That is a model-access fact, not a throttle and not a transient error: no amount of
retry or capacity racing reaches a model the account cannot invoke, and enabling model access is
an account-level change to a shared AWS account that this project has no mandate to make.
`f6_latency/03_composition.py` re-runs the Claude probe under `capture(...)` so the exception,
its request id and the exact model id sit in F6-6's own evidence rather than in a session log.

Nova Micro was chosen from the models this account CAN invoke because it is the cheapest, which
keeps a 2,800-call arm under a dollar — and, as the bias note below records, because it is the
choice least flattering to the document.

### What it does and does not affect

| Case | Hop | Does the substitution matter? |
|:--|:--|:--|
| F6-2 | #2, input guardrail | **Barely.** `guardrailProcessingLatency` is time spent in the guardrail service evaluating text. The model is not running during it. |
| F6-5 | #6, output guardrail | **Barely**, with one caveat: output evaluation reads the model's OUTPUT, and output length is model-dependent. `output_chars` is recorded per trial so the payload can say whether the hop scales with length. |
| F6-6 | #3, inference, and the §6.1 total | **Yes, decisively.** This is the row the document itself labels "model-specific". |
| F6-1, F6-3, F6-4, F6-8, F6-9 | gateway hops | **No.** No model is invoked. |

### Direction of the bias, and why any F6-6 failure is CONDITIONAL

Nova Micro is at the fast end of what Bedrock offers; Claude 3.5 Haiku is slower and Sonnet
slower again. §6.1's Hop #3 band (500 ms–30 s) and total (~800 ms–31 s+) are **floor** claims in
the only direction that is testable — the sealed binding for F6-6 notes the trailing `+` makes the
upper end unfalsifiable. A faster model can only push the measurement DOWN, i.e. **towards FALSE,
against the document.** So the substitution cannot manufacture a TRUE for F6-6; if the floor holds
on the fastest cheap model available, it holds more comfortably on the models the document names.

The converse is the part that has to be labelled honestly. If F6-6 comes out FALSE-low, that
failure is **conditional — representation-bound to the model** — not an absolute defect in §6.1,
because §6.1's own row says "model-specific". The F6-6 record must carry that label, and the
amendment it supports is "state the model the band was measured on", not "the band is wrong".

### What would remove the deviation

Model access for a Claude model in this account, then re-running `01_model_hops.py` and
`03_composition.py` with `MODEL_ID` changed — no other change. The two scripts read the model id
from one constant each, and record it in every payload, so a future reader can tell at a glance
which model any published band belongs to.

---

## DEV-P4-07 — F6-1 (Hop #1) and F6-4 (Hop #5) are measured by ONE reading, because the service will not evaluate the policy shape that would separate them

### What was pre-registered, and what runs instead

§6.1 lists Hop #1 "Gateway Guardrail (Input)" and Hop #5 "Tool Guardrails (per call)" as two
rows, both enforced by "AgentCore Gateway Policy", separated by *when* the evaluation happens:
row 1 on the way in, row 5 once per tool call. F6-1 and F6-4 were pre-registered as two cases
with two arms. `f6_latency/02_gateway_hops.py` runs **one** guardrail arm and publishes the same
per-request series to both cases.

### Why — a measured service constraint, not a testbed gap

F4 measured this on 2026-08-11 (run `r20260810T130945Z`) while collecting its truth table. A
guardrail statement whose action scope is left unconstrained is **accepted at create time** under
`validationMode=IGNORE_ALL_FINDINGS` and reaches `ACTIVE`, and then denies **every** request at
the gateway with:

    Authorization denied: a guardrail policy could not be evaluated - missing an attribute.
    Please retry.

The guardrail's data path `context.input.text` does not exist on a request that is not a
`tools/call` carrying a `text` argument, and an unevaluable guardrail **fails closed**. So the
only guardrail policy this service will actually evaluate is one scoped to a specific tool
action — which is exactly row 5's "Tool Guardrails (per call)". **There is no configuration of
this service that produces row 1 as something distinct from row 5.**

The telemetry half of the same fact is already in F7-1's inventory: `GuardrailLatency` publishes
under `[OperationName=AuthorizeAction, TargetResource=<gateway id>]` and carries no dimension
that would separate an input-side evaluation from a per-tool one, so even the document's own
named instrument cannot tell the two rows apart after the fact.

### Class and direction of the bias

- **Class:** instrument — two pre-registered cells collapse to one because the second cell is
  not constructible.
- **Data existed:** **no** for the F6 arms; the constraint was measured by F4 before
  `02_gateway_hops.py` was written, and is recorded in that script's docstring as a
  pre-commitment rather than as an explanation after the fact.
- **Direction: none, and this is the load-bearing part.** Both rows claim the **same band,
  50–200 ms**. One measurement therefore decides both, and no attribution of the reading to one
  hop or the other can move it across a boundary the two rows share. Had the rows claimed
  different bands, the collapse would have made at least one case unmeasurable and
  `02_gateway_hops.py` could not have run at all — that check is in the docstring, not left to a
  reader.

### What this costs the verdicts

A TRUE or FALSE published for F6-1 is a statement about **an action-scoped gateway guardrail
evaluation**, and not about an input-side hop distinct from it. Both records carry that sentence
in `what_true_does_not_prove`, and both carry the `hop_conflation` block naming the measured
error string above. The amendment this supports is "§6.1 rows 1 and 5 describe one enforcement
point, not two" — which is a stronger statement about the document than either band verdict.

### What would remove the deviation

Nothing in this project. It would take a service change: an evaluable guardrail data path that
exists outside a `tools/call` (so an input-side gateway guardrail can be configured at all), or
a dimension on `GuardrailLatency` that distinguishes the two evaluation points.

---

## DEV-P4-08 — §6.1 row 5 names a `ToolName` dimension on `GuardrailLatency` that does not exist, so F6-4's pre-registered instrument is not the one it is measured on

### What was pre-registered, and what runs instead

F6-4's instrument, quoted from §6.1 row 5, is **"GuardrailLatency (ToolName dimension)"**. The
case is measured on `AgentCore.Policy.AuthorizeAction.durationNano` (per request) with
`GuardrailLatency` percentiles as a cross-instrument check — read at the dimension combination
the service actually publishes, which does **not** include `ToolName`.

### Why

F7-1's paginated `ListMetrics` inventory records `GuardrailLatency` in
`AWS/Bedrock-AgentCore` with exactly two dimensions at our gateway:
`OperationName=[AuthorizeAction]` and `TargetResource=[<gateway id>]`. There is no `ToolName`.

The control that makes this a fact about the metric rather than about our traffic is the
**sibling**: `AllowDecisions`, same namespace, same `OperationName=AuthorizeAction`, published
from the *same requests*, **does** carry `ToolName=[grxecho___delay, grxecho___echo,
grxecho___fixed]`. So our traffic demonstrably exercises three distinct tool actions and the
service demonstrably knows which tool each decision belongs to — it just does not attach that
dimension to the latency metric. `02_gateway_hops.py` re-reads the dimension list live while an
**action-scoped** guardrail policy is ACTIVE, which is the exact configuration in which a
`ToolName` dimension would have to appear if it existed, and records the result in every F6-1
and F6-4 payload under `tool_name_dimension_claim`.

### Class and direction of the bias

- **Class:** instrument. Also a **finding**: this is a falsifiable, instrument-level document
  defect that is independent of the band verdict, and it is the kind a reader would act on —
  someone following §6.1 row 5 would build a per-tool guardrail-latency alarm that cannot be
  built.
- **Data existed:** **no.** The absence was inventoried by F7-1 before the F6 gateway script was
  written.
- **Direction:** **against the document, on a point the band verdict does not reach.** A missing
  dimension cannot make a latency band look better or worse; it removes the ability to scope the
  measurement per tool at all. The substitute instrument (the per-request span) is *more*
  favourable to the document than a per-tool CloudWatch read would have been, because it excludes
  none of our traffic and is measured at the request rather than the minute.

### What would remove the deviation

A `ToolName` dimension on `GuardrailLatency`, or an amendment to §6.1 row 5 naming the dimensions
the metric actually carries. The amendment text is the cheap fix and is what the finding
recommends.

---

## DEV-P4-09 — a fourth round of the DEV-P4-04 defect: `04_publish_lag.py` timed a dimension combination that no series publishes, and a 600 s timeout would have been published as the service's publish lag

### What happened

`f7_observability/04_publish_lag.py` picks the metric and dimensions it will time from F7-1/2/3's
recorded inventory. That inventory stores a **flattening** — `dimension_values`: dimension *name*
→ every *value* ever seen under it. The first version of `_pick_metric_and_dimensions` built its
query by taking one value per name that mentions our gateway id.

`ListMetrics` does not publish dimension *names*. It publishes **combinations**: an ordered
`Dimensions` list of name/value pairs, one per series. Our gateway id appears in a
`TargetResource` value **and** in a `Resource` value, from two different combinations, so the
flattening produced:

    [{Resource: arn:aws:bedrock-agentcore:<region>:<account>:gateway/grx-gw-<id>},
     {TargetResource: grx-gw-<id>}]

a two-dimension set that **no series carries**. `GetMetricData` answers such a query with
`StatusCode=Complete` and **zero values — not an error**. So trial 1 polled for its full 600 s
timeout and logged `lag=TIMEOUT polls=55`. Left alone, all 30 trials would have timed out
(~5.1 hours) and F7-6 would have published a **10-minute publish lag** as a property of
CloudWatch.

Caught by reading the first trial's log line, not by any assertion — which is itself the finding.

### The instrument change

Three parts, all in `04_publish_lag.py`:

1. `_published_combinations` queries `ListMetrics` **live** and keeps whole published
   combinations, never reassembling one from parts. Candidates are sorted **most specific
   first**, so the tightest scoping that exists is preferred over a broad one.
2. `_combination_carries_data` pre-flights each candidate with a 6-hour
   `GetMetricStatistics` and rejects any that has no recent datapoints. A query that returns
   nothing before the clock starts cannot be told from one whose datapoint has not arrived yet.
3. If no candidate survives, the run **bails** with the reason, instead of timing out `n` times.
   The bail message says so: *"would time out N times and the run would report the timeout as a
   publish lag."*

A second bug surfaced immediately after, during the `--n 2` smoke: the `distinct_minute_buckets`
guard failed with both trials in bucket `1786465140`. `INTER_TRIAL_GAP_S = 5.0` was smaller than
the measured ~11 s lag, and **the datapoint a request produces is stamped at the bucket
containing `t_send`** — so two trials in one bucket share a datapoint, the second one's clock
stops on the first one's publication, and its lag reads near zero. The gap is now a sleep to the
**next bucket boundary** plus a margin. The guard was already honest; the fix is what makes it
*satisfiable*.

### Class and direction of the bias

- **Class:** measurement — an invalid reading, caught before publication.
- **Data existed:** **yes** for the first bug (one timed-out trial), which is how it was found.
  No verdict was emitted from it.
- **Direction:** the first bug biased **towards a large publish lag**, i.e. towards the document
  (§6.4's alarm periods are easier to justify against a slow metric pipeline). The measured value
  after the fix is **≈ 11.4 s**, far below any 60 s expectation. The second bug biased towards a
  **near-zero** lag on every trial after the first — the opposite direction — which is why it had
  to be fixed rather than tolerated.

### The general lesson, stated as a rule

A name-keyed union of dimension values **is not a published dimension set**. This is the fourth
round of one shape: a CloudWatch read that returns *nothing* while reporting *success*, then gets
interpreted as a fact about the service. `Paginated` truncation (round 1), a 500-series cap
(round 2), a quoted `SEARCH` term (round 3), and now an unpublished combination — all of them
"succeeded". The rule that would have caught every one: **before timing or scoring an empty
CloudWatch read, prove the query can return something.** Rounds 1–3 needed a trust flag on the
response; round 4 needed a pre-flight against a window where data must already exist.

---

## DEV-P4-10 — the account ID reached `results/` again, in a field no ARN pattern can see, and the gate's own account-ID excuse was waiving whole lines it had never read

### What happened

The redaction gate failed on two files with the live 12-digit account ID in plaintext:

    results/phase1/F7-1.json:2938  [aws-account-id]  "ESDMCP-OAuth2-Provider-us-east-1-<account>-prod"
    results/phase1/F7-2.json:2915  [aws-account-id]  "ESDMCP-OAuth2-Provider-us-east-1-<account>-prod"

The value is a CloudWatch **dimension value** — `ProviderName` on
`ResourceAccessTokenFetchSuccess` — naming another team's OAuth2 credential provider in the same
account. `lib/redact.py` masks the account field **of ARNs**, and this is not an ARN. It is a
resource *name*, and a resource name is free text chosen by whoever created the resource.

DEV-P1-13 recorded the first version of this leak (82 files) and fixed it at the two writers into
`results/`. That fix was correct and incomplete in a way the fix itself could not see: it
anchored on ARN grammar, and F7's whole instrument is a **namespace-wide enumeration of a shared
namespace**. The general form is: *any* resource name any other team chose can arrive in our
results, and none of them has to look like an ARN.

Two more defects were found while closing it, both in the gate:

1. **The `aws-account-id` excuse read one token and waived the line.** It did
   `re.search(r"\b\d{12}\b", line)` and reasoned about that single match, so a line carrying a
   corpus fixture *and* a real account ID would have been excused by the fixture. This is
   precisely the vacuous-excuse shape DEV-P2-01 records for the `arn` branch — sitting in the
   branch immediately below it, and it survived that fix because only the ARN half was re-read.
2. **Four false positives on latency figures.** `\b\d{12}\b` treats `.` as a word boundary, so
   `"p99": 758.324053273605` — whose fractional part is exactly twelve digits — was reported as
   an account ID in `F6-1/F6-3/F6-4/F6-9.json`. A number is not an identifier, and its own
   delimiters say so.

### The instrument change

- `redact.register_account_id()` teaches the masker one account ID, which `mask_text` then masks
  as a **bare token** as well as in ARN position. Narrow on purpose: the obvious widening — mask
  every `\b\d{12}\b` — is the one `redact.py`'s docstring already refused, because a PII corpus
  fixture whose entity type **is** a 12-digit number (`US_BANK_ACCOUNT_NUMBER`) comes back on
  checkpoint rows, and masking it would destroy the record of which fixture was sent.
- Registration is a **side effect of resolving the value**. `awsclients.account_id()` is now the
  only place `get_caller_identity()["Account"]` is read; nineteen inline call sites were routed
  through it. A mask that has to be told the value is a mask that can be forgotten, so
  `lib/tests/test_account_id_choke_point.py` walks every `.py` file's AST and fails the suite if
  a twentieth inline site appears. (AST, not grep: the choke point's own docstring quotes the
  forbidden expression to explain the rule.)
- The gate's account-ID branch now requires **every** 12-digit token on the line to be
  excusable, and recognises the fractional part of a decimal number as a number.
- The two affected result files were re-masked **through the fixed masker** rather than hand
  edited, and verified structurally identical to the originals under the substitution — the
  measurement is untouched; only the placeholder moved.

### Class and direction of the bias

- **Class:** provenance — a distribution-safety defect. No verdict, oracle, threshold or
  measured value changed; `F7-1.json` and `F7-2.json` are byte-identical to their originals
  except for the masked substring.
- **Data existed:** **yes** — this was found by the gate on collected Phase-1 results, which is
  the only place it could have been found.
- **Direction:** none, on the document under test. The bias is on us: the failure mode is
  publishing an account identifier, and it fails **open** (an unregistered ID is not masked),
  which is why the gate stays the backstop rather than being replaced by the masker.

### The general lesson, stated as a rule

A redaction rule anchored on the **grammar of one identifier** cannot cover a field whose
grammar is chosen by a stranger. Where our results enumerate a shared surface, the redactable
value has to be masked by **identity** — this is the account, mask it wherever it appears as a
token — and identity has to be registered at the one place it is learned, or the rule has no
deploy path (feedback_no_deploy_path_no_component). Corollary, and the second time it has been
written down here: an excuse that inspects **one** match on a line must not waive the **line**.

---

## DEV-P4-11 — F6's CloudWatch windows described the loop rather than the arm, and a `Period` CloudWatch rejects returned zero datapoints that read as zero traffic

### What happened

`f6_latency/02_gateway_hops.py` completed cleanly — 1000/1000 trials in both arms, 0 failures,
spans joined 1000/1000 in each — and published **F6-1, F6-3, F6-4 and F6-9 as INCONCLUSIVE**, all
four on the same guard:

    "guardrail_ran_only_where_intended": {
      "cedar_arm_datapoints": 2,
      "guardrail_arm_datapoints": 0,
      "test": "GuardrailLatency has datapoints in the guardrail arm's window and NONE in the
               Cedar-only arm's"
    }

Exactly backwards: the arm with no guardrail had the datapoints and the arm with one had none.
Two independent harness bugs, neither of them a fact about the service.

1. **The window was the loop's, not the arm's.** Each arm recorded `t0 = time.time()` before its
   trial loop and `t1 = time.time()` after it. The `cedar_only` arm resumed **every** trial from
   its checkpoint, so the loop ran nothing and the recorded window was **5 milliseconds wide**
   (`t0 = 1786468148.2112288`, `t1 = 1786468148.216634`). The read span was `t0-60 .. t1+120`,
   which from a 5 ms window reaches ~92 s **into the guardrail arm** and harvested 2 of its
   datapoints. A wall-clock window around a loop describes the loop; it coincides with the arm
   only on a run that resumes nothing.
2. **`Period` was not a multiple of 60.** The guardrail arm's own read asked for
   `Period = int(t1 - t0) + 120 ≈ 1011`. CloudWatch requires a multiple of 60 above 60 s and
   returns **no datapoints** otherwise — indistinguishable from a metric never published.

A third defect was latent behind both and would have survived either fix on its own: the read's
`+120 s` tail was a **publish-lag allowance applied to the wrong axis**. `GetMetricStatistics`
buckets a datapoint by the metric's own timestamp — the request time — so lag governs when a
datapoint becomes *readable*, not which bucket it lands in. With `POLICY_SETTLE_S = 20`, a 120 s
tail on the Cedar arm's read covered 100 s of guardrail traffic **however accurate its window
was**, so the guard's negative half was testing the read's tail rather than the arm.

### The instrument change

- `_arm_window()` derives each arm's window from **its own trials**, in decreasing order of
  authority: the `AuthorizeAction` span timestamps (the *service's* clock, the one CloudWatch
  buckets by, so no skew allowance is needed), then a new per-trial `t_send` stamp that survives
  a resume on the checkpoint row, then **nothing** — in which case the arm has no window and its
  cross-instrument read is reported `unavailable`. Deliberately no wall-clock fallback: a wrong
  window is worse than a missing one, because it answers.
- `plausible`: a window narrower than `n_real × INTER_CALL_S` is not this arm's, and says so.
  This is the tripwire the 5 ms window walked past.
- The read range is the window plus a 5 s skew allowance and **nothing more**; the Cedar arm's
  read is additionally capped at the instant the probe policy landed, past which any datapoint
  belongs to the other arm by construction. `Period` is `60 × ceil(range / 60)`.
- The span join moved **inside** the probe's lifetime, because the windows are now derived from
  the spans and the metric read needs both. It costs the probe a few extra minutes of existence
  and no extra requests.
- Two guard changes. New `arm_windows_recovered`, upstream of and separate from
  `guardrail_ran_only_where_intended`, so a contaminated window is distinguishable from a
  service that evaluated the guardrail in both arms — on 2026-08-12 they were not. And a Cedar
  read that never happened now **fails** `guardrail_ran_only_where_intended` instead of
  satisfying its negative half: a missing check is not a pass
  (feedback_missing_check_is_not_pass).

### Class and direction of the bias

- **Class:** harness-defect — an invalid reading, caught before any verdict was believed.
- **Data existed:** **yes.** 2000 trials and four published records existed, all four
  INCONCLUSIVE. The re-analysis re-uses those trials; no new traffic was needed, because the
  spans carry the window the harness had failed to record.
- **Direction:** **none towards the document, and that is the point.** The guard withheld four
  verdicts rather than publishing them, and the numbers it withheld all point **against** §6.1:
  Cedar authz p50 = 55 ms against a 5–50 ms band, guardrail hop p50 = 401 ms and p99 = 779 ms
  against a 50–200 ms band. Had the same bug failed *open* it would have published refutations
  from a contaminated window — the DEV-P1-18 shape. It failed closed instead.

### The general lesson, stated as a rule

**A time window recorded around a loop is not a property of the data the loop collected.** Any
resumable harness has two clocks — when the trials happened, and when this process happened to
iterate over them — and a checkpoint makes them diverge silently, with no error and a full result
set. The window has to be derived from the trials, which means every trial must carry its own
timestamp, and where it cannot the answer is *unavailable* rather than a guess. Second rule,
narrower and now twice-learned in this project: **before reading zero datapoints as zero traffic,
prove the query was answerable** — `Period` not a multiple of 60 is the fifth member of the
DEV-P4-04 family of CloudWatch reads that return nothing while reporting success.

---

## DEV-P4-12 — the evidence writer could not record an `InvokeModel` call at all

**Class** `harness-defect` · **Date** 2026-08-12 · **Data existed** no · **Cost** 8 model calls (~$0.01)
**design_impact** none on any published number; F5-6 could not have run before this was fixed.

### What happened

`f5_redteam/06_tagging_scope.py --probe` sends one call per arm to establish response shapes
before the scored run spends 720. Both `InvokeModel` arms came back:

    {"error": "TypeError: cannot pickle 'BufferedReader' instances"}

`InvokeModel` returns its payload as a `StreamingBody` — a file object over the socket.
`evidence.capture` copied the response into the record verbatim and `store.add` then tried to
serialise it. So **the evidence tree could not record an `InvokeModel` call**, and the failure
landed *after* the call had been billed and its request id received: the money was spent, the
service had answered, and the record was lost.

That made every case needing that transport unreachable, which is
`feedback_no_deploy_path_no_component` in its plainest form — the transport was not a component
of this harness, whatever the scripts said. It is also why the defect had gone unnoticed: every
family shipped so far uses `ApplyGuardrail`, `Converse` or a control-plane API, none of which
stream.

### The fix, and the part of it that is not obvious

`_drain_streams` reads the stream once, at the single point every record passes through, and
puts the decoded text back where the payload was.

Draining rather than copying is forced, not stylistic. A `StreamingBody` read is **destructive
and one-shot**, so serialising a copy and leaving the original for the caller would hand the
caller an empty string — silently. An empty body parses to `{}`, and for F5-6 `{}` means "no
input assessment", which the tally counts as a **failed trial**. The harness would have recorded
its own read as a service failure, for reasons entirely internal to `lib/evidence.py`.

### Direction

None towards the document. This is a defect in our instrument that withheld data rather than
biasing it, and it was found by a probe that exists precisely to spend four calls before
spending 720 (feedback_dry_run_before_expensive_run, feedback_verify_against_real_artifact).

---

## DEV-P4-13 — F5-6's seal says "the untagged arm", and the four-arm design has two of them

**Class** `analysis` · **Date** 2026-08-12 · **Data existed** yes — n=1 per arm, from the probe
**design_impact** one **interpretation** recorded; no threshold, correction or n is changed.

### The ambiguity

F5-6's binding is `UPPER_BELOW` on "the **untagged** arm's recall". The sealed oracle text
enumerates four arms: *InvokeModel untagged / tagged / Converse without guardContent / Converse
with guardContent on a different block*. Two of those four send no tag — arm A (`InvokeModel`,
plain body) and arm C (`Converse`, one plain `text` block) — so "the untagged arm" has two
referents, and the verdict differs by which one is read.

### The reading, and when it was fixed

**Arm A.** Textually: the seal's own enumeration is what supplies the arm names, and it calls
arm A "untagged" while calling arm C "without guardContent". Only one arm in the sealed sentence
carries the word the binding uses.

The reading was committed as the constant `ORACLE_ARM = ARM_A` — with the comment that
`_verdict_arm` is asserted against it so no later edit can move the verdict onto a different
arm — **before** the probe ran, in the same write as the script. This entry is written after,
and says so: what is pre-data is the choice, not the paragraph defending it.

### Why the ambiguity turned out to matter

The probe's four calls, one item per arm, no rate and no verdict:

| arm | guarded / total chars | `PROMPT_ATTACK` |
|:---|:---|:---|
| A `invokemodel_untagged` | 65 / 65 | did **not** fire |
| B `invokemodel_tagged` | 65 / 162 | fired |
| C `converse_no_guardcontent` | 65 / 65 | **fired** |
| D `converse_guardcontent_other` | 101 / 166 | did **not** fire |

The two untagged arms disagree, on the same item, against the same guardrail at the same
strength. If that survives n=120 it means §3.2's claim is **transport-dependent** — true of
`InvokeModel` and false of `Converse` — and no single arm answers the question the document
asks. It also supplies the missing explanation for DC-2's original n=5 observation (5/5 detected
with no tagging): that observation was not on `InvokeModel`.

### Consequence, pre-committed here

1. The verdict is computed on **arm A**, per the reading above.
2. Arm C's recall and interval are published **in the same record and the same sentence**, with
   the disagreement stated, so no reader inherits my choice of referent without seeing the arm
   it excluded. A verdict that depends on resolving an ambiguity must show the other resolution.
3. If A and C disagree at n=120, the **finding** is the transport dependence, and it is reported
   as such rather than as a confirmation or a refutation of §3.2. The verdict field will still
   carry whatever the sealed oracle says about arm A, because that is what a verdict is for; the
   sentence next to it will say the claim is not transport-independent in the first place.

Arms B and D remain descriptive pairwise contrasts, BH-adjusted within `exploratory_detection`.

### One guard was tightened after the probe, in the strict direction

`tagging_was_honoured` originally required partial coverage on both tagged arms **and full
coverage on arm A**. Seeing the probe's coverage column made the asymmetry obvious: arm C is
untagged too, and an arm labelled untagged that in fact carried a marker would have been caught
on A and waved through on C. The guard now iterates `UNTAGGED_ARMS = (ARM_A, ARM_C)`.

Recorded because it is an edit to a pre-committed guard made with n=1 per arm already visible.
It can only make the run harder to publish, never easier: it adds a condition to a conjunction
that gates the verdict, so no configuration that previously failed can now pass. The mutation
test covers the new direction (arm C partial ⇒ guard False) alongside the three it already had.

---

## DEV-P4-14 — F6-6/7/8 crashed in its analysis after all 1,600 turns were paid for, and its CloudWatch window would not have survived the re-run

### What happened

`f6_latency/03_composition.py` completed the whole arm — 1000 + 200 + 200 + 200 turns, 0 failures,
liveness denied before and after, probe removed, 15/15 blocking checks pass — read its CloudWatch
window successfully, and then **raised `ValueError: empty sample`** in `S.quantile`, publishing
nothing. Two separate defects, one behind the other.

**1. A guard on the wrong list.** The hop breakdown computed

    "hop6_output_guardrail": S.quantile([r["converse"]["hop6_ms"] for r in base
                                         if r["converse"].get("hop6_ms") is not None],
                                        0.50) if base else None

The `if base else None` asks "were there any baseline turns". The list actually being summarised
is `base` **filtered** to the turns that reported that hop. Those differ exactly when a hop is
absent from every trace — and hop 6 is: `hop6_ms` is `None` on a Converse response carrying no
`outputAssessments`, and **0 of 1000** benign turns carried one. So the guard could never fire on
the condition that mattered. Fixed by `_p50_or_none`, which guards the list it summarises. The
empty case stays `None` rather than `0.0`: a hop that was never reported did not take zero
milliseconds, and a `0.0` would be summed into a total as though it had.

**2. The window would not have survived the resume — the DEV-P4-11 defect, in the one F6 script
that never got its fix.** Hops 4 and 5 are read from CloudWatch over the window in which the turns
were **sent**, and that window was wall-clock state in the crashed process (`windows["t0"]`,
`windows["t1"]`), persisted nowhere. Re-running would have skipped all 1,600 checkpointed trials in
seconds, timed a window containing no traffic, read **0 samples**, failed `gateway_hop_measured`
and published **NOT_MEASURED for all three cases** — with 1,600 paid-for turns sitting on disk.
This is precisely what DEV-P4-11 records for `02_gateway_hops.py`, whose remedy was to derive each
arm's window from its own trials via a per-trial `t_send` stamp. `03_composition.py`'s rows carry
no such stamp (verified: the checkpoint row keys are `attempts, calls, client_total_ms, converse,
corpus_id, corpus_label, gateway_client_ms, n_calls, n_denied, outcome, retry_delay_s, text_len`),
so the fix never reached it and the resume path was still the wall-clock one.

### The instrument change

- `WINDOWS_PATH` (`results/checkpoints/F6-6__cw_windows.json`) is a **window ledger**: every
  process that sends turns appends its own `[t0, t1]` and a provenance entry. A process that sends
  **nothing** appends nothing — `done_before` is counted from the checkpoints *before* the levels
  run, so "did this process send" is measured, not assumed. An empty window would otherwise
  contribute a CloudWatch query over idle time and dilute the p50 with whatever else was talking
  to this gateway.
- `_cw_p50` now takes a **list** of windows and queries each separately, combining sample-weighted.
  Deliberately not merged into one span from earliest start to latest end: merging would sweep in
  every other case's traffic in the gap between two runs and attribute its latency to F6's hop 4/5.
- A corrupt or malformed ledger is **fatal**, and an analysis with no window on record raises
  rather than reading `0.0` — for the reason `Checkpoint.load` gives about its own file.
- `hop6_reporting` publishes the count beside the `null`: `n_turns`,
  `n_turns_with_an_output_assessment_latency`, `n_turns_with_zero_output_assessments`. Without it,
  `hop6_output_guardrail: null` reads as "we failed to measure it" instead of the finding it is.

### The one window that predates the fix was RECONSTRUCTED, not re-sent

`f6_latency/recover_cw_window.py` recovers it from the crashed run's **own archived requests**.
`lib/evidence.capture` had already written the 11 `GetMetricStatistics` calls that run issued, and
`_cw_p50` pads by exactly 60 s on each side, so the window is recovered by inverting that pad:

    archived  StartTime 2026-08-11T18:06:54.089958Z  EndTime 2026-08-11T19:10:27.603538Z
    recovered t0        2026-08-11T18:07:54.089958Z  t1      2026-08-11T19:09:27.603538Z   (61.6 min)

The script refuses if the archived requests disagree on the span (the inversion would be
ambiguous), refuses to overwrite an existing ledger, and marks its entry
`recorded_by: "recover_cw_window.py (RECONSTRUCTED)"`. `03_composition.py` publishes that
provenance inside all three cases' `guard_detail.gateway_hop_measured.sending_windows`, so a reader
sees in the result itself that this window was reconstructed from request records rather than timed
live.

**The reconstruction is corroborated by the re-run.** Reading CloudWatch over the recovered window
reproduced the crashed run's numbers to the digit — `Latency p50 = 503.4905594071247` (n=12032),
`GuardrailLatency p50 = 386.4656532352717` (n=3002) — which is what "the same window" means
operationally. The alternative to reconstructing was re-sending 1,600 turns to re-derive a number
already archived, or discarding them.

### Direction of the effect on the document under test

Neither fix touches a verdict rule; both restore the ability to compute one. The published outcome:
**F6-6 TRUE** (client p50 1482.8 ms, server p50 1187.0 ms, both above the 800 ms floor, no
straddle), **F6-7 TRUE** (residual +265.3 ms, CI 258.8..273.0, so §6.1's table does not
over-account), **F6-8 FALSE** (851.5 ms per additional tool call, CI 838.7..862.7, against the
document's stated 165–750 ms). The hop-6 result is an amendment candidate in its own right: §6.1
names hop 6 as a measurable row, and the runtime reported **no** output-assessment latency on any
of 1,000 passing turns, so that row has no per-request instrument behind it.

---

## DEV-P4-15 — F5-1 crashed after every invocation was paid for, then published a clean 120-trial result as INCONCLUSIVE, then measured a window that no longer existed, then accepted a flap as convergence

### What happened

`f5_redteam/01_route1_direct_invoke.py` took five runs to publish. Four separate defects, each of
which let the run get *further* than the last before failing, and each of which would have been
invisible in the published record rather than loud.

**1. `evaluate() takes 1 positional argument but 2 were given`** — raised at the analysis step,
**after** all 160 invocations and both IAM mutations. `O.evaluate` takes the Observation alone: the
case id travels inside it, so a record cannot be decided under one case's binding while carrying
another's data. Passing `CASE` again is not a harmless duplicate. Guarded repo-wide, not locally:
`lib/tests/test_oracle.py::test_every_evaluate_call_site_in_the_repo_passes_exactly_one_argument`
walks every `*.py` under the root by AST and asserts `n_sites >= 15` first, so the sweep cannot pass
by matching nothing.

**2. A field silently demoted to data by a `**kwargs` sink.** The run then published

    F5-1: adverse=0 / n_usable=120 -> verdict INCONCLUSIVE   ("the mutation was not recorded")

with the inverted mutation sitting in the same payload, plainly visible. `mutation_inverted` had
been passed as a keyword to `P.obs_zero_events(...)`, and the phase-1 builders sweep surplus
keywords into `detail` — which the decision rule never reads. So the field kept its default, and for
a case whose mutation is MANDATORY that downgrades a clean 120-trial TRUE. The value was present,
published, and unread. Every other case in the suite sets it as an attribute after construction.

Root-caused in `lib/phase1.py` rather than fixed at the call site: `_detail()` now compares each
`**detail` key against `dataclasses.fields(O.Observation)` and raises with the correct spelling —

    F5-1: mutation_inverted is an Observation field, not free-form detail. Passed as **detail the
    value is stored where the decision rule never looks, so the field keeps its default and the
    verdict is decided as if it were never measured. Set it as an attribute instead:
    o = P.obs_...(...); o.mutation_inverted = <value>

— and all nine builder sites route through it. Any future case that makes this mistake fails at
construction instead of publishing a wrong verdict.

**3. A wall-clock window that bracketed idle time across a resume** — the DEV-P4-11 class, in a
different family. The span corroboration counted `AuthorizeAction` rows over the window in which
the granted arm's invocations were sent. On a resume the granted arm is served from its checkpoint
and sends **nothing**, so the window bracketed idle time and returned 0 spans. Read as "the invokes
produced no span", that is manufactured corroboration for the document's non-bypassable claim.
`_span_corroboration` now takes `n_invokes_in_window`, measured as
`cps[ARM_GRANTED].n_done` before and after the window, and reports a distinct reading:

    NO_INVOKES_IN_WINDOW — the granted arm sent nothing during this window, its trials were served
    from the checkpoint of an earlier process, so the span count says nothing about whether a direct
    invoke produces an AuthorizeAction span.

Every run since has printed exactly that, which is the honest outcome for a resumed arm.

**4. One confirming probe accepted as convergence.** `_wait_for_effect` polled until the wanted
outcome appeared **once**. The revoke direction reported `denial re-asserted after 31.2s` on the
probe sequence `executed x5 -> denied_by_iam`, and then **9 of the next 20** invocations executed:
the arm whose entire purpose is to show the boundary came back instead recorded it being crossed.
Now `PROP_CONFIRM_N = 3` **consecutive** confirmations — consecutive, not cumulative, because a
cumulative counter is satisfied by an alternating sequence and an alternating fleet *is* the
unconverged state, so it would end the wait on the very evidence that should extend it. The result
publishes `seconds_to_first_confirmation`, `held_for_s`, `flapped_before_converging` and
`n_wanted_outcomes_before_the_final_streak`, so the strength of the claim is legible instead of
implied.

That fix was not sufficient, and the insufficiency is the finding: **three consecutive denials do
not establish convergence either.** See `results/FINDING-F5-1-REVOCATION.md` — 24 of 60 invocations
sent after an observed denial still executed, 11 of 20 in the replicate with the strongest
instrument. The revoke direction now carries its own bound, `PROP_MAX_REVOKE_S = 1800`, separate
from the grant's `PROP_MAX_S = 300`: a grant that has not landed costs the run an arm, a revoke that
has not landed is a hole in the boundary the testbed is meant to have restored, so its wait is a
safety check and is not cost-bound by the confirmatory n. The default is `max_s=None` resolved
inside the function, not `max_s=PROP_MAX_S` in the signature — an early-bound default would freeze
300 s into the signature and the two tests that shorten `PROP_MAX_S` to keep pytest fast would poll
for five real minutes while asserting nothing.

### The guard that was split, and why that is not a weakened guard

F5-1 shipped with `grant_was_removed_and_denial_reasserted`, requiring **both** the control-plane
removal **and** zero executions among the 20 post-restore invocations. It was false in every run,
which would make F5-1 permanently unpublishable while the boundary it actually tests is measured
cleanly at n=120. Those are two different questions:

- `grant_was_removed_from_the_role` — **required.** Reads the role's inline policy set back from
  IAM and compares it to the shipped baseline. This is "was the testbed left as we found it", it is
  definitive, and it is what the sealed `restore_verification` rule states. `delete_ok` alone says
  the call returned, not that the role is clean; a failed read records `None`, which can never equal
  the baseline (`feedback_guard_tool_exit_codes`).
- `denial_was_reasserted_in_the_data_plane` — **required.** The deny must be observed again at all.
- `strict_form_all_post_restore_invocations_denied` — **published, not required**, under
  `data_plane_reconvergence`, with the counts, the probe sequence, the bound in force, and the
  reason it is not required.

The direction of the change matters. When the second guard *also* came back false — three
consecutive denials not reached inside 300 s — the loosening move was available and was **not
taken**: the bound was lengthened to 1800 s instead, and the guard then passed on its own terms.
Using "the platform does not offer this guarantee" once to split a guard is a judgement; using it a
second time on the next guard would be a habit.

**Published outcome, all five guards true:** F5-1 **TRUE (ZERO_EVENTS)**, 0 of 120 direct
invocations executed, Wilson 99% `[0, 0.05865]`, exact one-sided ceiling 0.0414 at α=0.00625,
mandatory mutation inverted 20/20 with every one echoing our marker. The role was verified back to
`['grx-runtime-exec-policy']` and the ledger's `f51_grant` entry to `None` after every run.

### One more escape, added deliberately

`usable_trials_met_the_preregistered_n` now passes on `n_usable >= PLANNED_N` **or**
`n_executed > 0` in the closed arm. An n-floor bounds how tightly a CLOSED boundary can be
described; it is not a floor on demonstrating the boundary is OPEN. A single closed-arm invocation
that actually ran the tool is a bypass, and a bypass does not become unproven because the other 119
attempts were unusable. Gating on n alone would publish NOT_MEASURED over a demonstrated bypass —
the one direction of error this family exists to catch. `guards_detail_n.gate_satisfied_by` records
which branch let it through. The test for this was itself **vacuous on first writing**: it split the
source on the guard name and then on `",\n    }"`, reading past the closing brace into
`guards_detail_n`, so it passed with the escape deleted. Bounded to the guards dict and
re-mutation-checked (`feedback_vacuous_test_check`).

### Two arms set aside, and one label that was wrong

`restored_reassert` rows are served from disk on the next run, so an arm measured against an
unsettled state can never be re-measured while its checkpoint stands.
`f5_redteam/archive_flapped_restore_arm.py` moves it aside with its provenance and clears the
checkpoint atomically; the evidence tree is untouched, so the archive is an index into records that
stay where they were, not a copy that can drift from them. It refuses to move an arm with zero
executions under any label — a clean arm satisfies the strict form and has nothing left to
re-measure — and refuses to overwrite an existing archive.

The second use of it was **wrong, and the correction is the point**. Replicate 2's rows were filed
under `timed_out_revoke`, attributing them to the run whose revoke wait timed out at 308.8 s. That
run re-sent nothing: its arm was already checkpointed. The rows came from the *previous* process,
whose revoke wait converged legitimately at 248.5 s — so they are a **valid measurement** in which 4
of 20 invocations executed after the arm's precondition was properly established. Filing a valid
replicate as an instrument defect is the same class of error as the defects it was filing: a record
whose label does not describe what produced it, and it would have cost a real observation, cited
nowhere. `f5_redteam/fix_restore_arm_archive_labels.py` corrects it to `earlier_replicate`, carries
a `label_correction` block naming the wrong label and how the truth was established from the two
runs' logs, and asserts the trial rows are byte-identical before and after. The archiver now
distinguishes two `kind`s, `defect` and `replicate`, because collapsing them is what allowed the
mislabelling.

### Direction of the effect on the document under test

Defects 1, 2 and 4 all pushed **against** F5-1 publishing at all; defect 3 was the only one that
pushed *for* the document, and it pushed by manufacturing corroboration — which is why it is the one
whose fix prints a refusal on every run since. The verdict itself confirms §4.4's route-3 advice.
The revocation window is a separate amendment candidate against the same section and is held at
`OBSERVATIONS_COMPLETE` pending a second calendar day.

### Test coverage added

`f5_redteam/tests/test_route1_direct_invoke.py` 30 → **41** tests. Each of the four defects, the
guard split, the n-gate escape, the per-direction bound, the late-bound default, and the strict form
still being computed and published. Every one mutation-checked: the fix was reverted in a copy and
the corresponding test observed to fail.

---

## DEV-P4-16 — the replication gate counted days across the whole run directory, so a single-day finding read as two days

### What happened

`check_amendment_readiness.py` enforces the sealed rule "an amendment requires observations on >= 2
separate calendar days", deriving the days from `t_start_utc` across every evidence record — a
deliberate design, so that a finding cannot *assert* it was replicated. The scan was scoped to the
declared **run id** and nothing narrower.

This project adopts **one run id for nearly everything** (`r20260810T130945Z`, taken from the
ledger). So every finding that declares it inherits every day that **any** case ran on. Caught on
`FINDING-F5-1-REVOCATION.md`, whose 354 records all fall on 2026-08-11:

    before:  FINDING-F5-1-REVOCATION.md  OBSERVATIONS_COMPLETE  2 day(s) ['2026-08-10', '2026-08-11']
    after:   FINDING-F5-1-REVOCATION.md  OBSERVATIONS_COMPLETE  1 day(s) ['2026-08-11']

The second day came from F1-3's and F4's records. Promoting that finding to `READY_TO_AMEND` would
have **passed the gate** on a single day's observation of the case under test — a replication check
that cannot fail once the run spans two days.

### The instrument change

`observation_days` now takes the case ids and counts only records whose `case_id` matches, and a
finding with `evidence_runs` must declare a non-empty `cases` list or the gate fails. `cases` is
declared, not derived from the filename, because the two genuinely differ: `FINDING-F5-7A.md` rests
on records whose `case_id` is `F5-7a`. A declared-but-matching-nothing `cases` is a failure with its
own message, so a misspelling cannot read as "no replication data".

Both already-published findings were re-checked against the stricter rule and **hold**: F1-3
spans 2026-08-10 and 2026-08-11 on its own records, F5-7a spans 2026-08-09 and 2026-08-10 on its
own records across the four run ids it declares. No status changed. That is the outcome to want —
the gate was wrong in a way that had not yet been *used*, and the fix is retroactive rather than
retrospective.

### Mutation-checked three ways

- status promoted to `READY_TO_AMEND` on one day → FAIL, naming the day count. **This is the case
  that passed before the fix.**
- `cases` key removed → FAIL, explaining why a run-wide count is not a replication.
- `cases` misspelled `F5-1a` → FAIL twice, once for matching no record and once for deriving no day.

### Direction of the effect on the document under test

Strictly against amending: the gate now requires more evidence for the same promotion, and no
existing amendment lost its footing. `MIN_DAYS` is still read from the sealed pre-registration text
rather than restated here, so this change cannot drift the threshold.

---

## DEV-P4-17 — a `--dry-run` gate cannot reach an attribute error that lives below its own `return`, so the offline suite and the dry run both passed and the first live launch died

### What happened

`f5_redteam/04_policy_failure_modes.py` read `args.state` and `args.evidence_root`. Neither flag exists:
`P.parser` defines `--dry-run`, `--n`, `--run-id` and `--region`, and nothing else. Both reads sat
**below** the dry-run banner:

    if args.dry_run:
        return P.dry_run_banner(...)      # <- returns here
    state = T.State.load(args.state)      # <- AttributeError, unreachable in a dry run

So `--dry-run` printed a correct five-arm plan, the 1,438-test offline suite was green, and the
**first live launch** — the one that costs money and creates policies on a shared engine — raised
`AttributeError: 'Namespace' object has no attribute 'state'` at line 599.

The near-miss is the point: it died *before* the first mutating call, so nothing was created in AWS
and nothing had to be cleaned up. Two lines later in the file and it would have crashed with a
`forbid` policy live on the engine that F6 and F2 share.

This is a structural blindness, not a typo. **Every** case script in this project has the same
shape — a dry-run banner that returns, then the live path — so `--dry-run` can never exercise an
`args.<name>` read, and the defect is invisible to the one check the project runs before every
expensive phase.

### The instrument change

`claims/tests/test_parser_attrs.py` (51 assertions) walks every phase-1 script's AST, collects every
`args.<name>` reference, and compares it against the dests `P.parser` actually defines **read live
from the parser**, plus any flag the script adds itself. Globs `f*/[0-9]*_*.py` and `infra/[0-9]*_*.py`,
so a new case is covered the moment it is named by the convention.

The sweep found **no other script affected**. That is a finding about the fleet, not a reason to skip
the test: the check now runs on every commit, and the shape that hid this defect is unchanged.

### Mutation-checked

- `args.doesNotExist` planted into a copy of a real script → FAIL, naming the flag and the file.
- `args.state` re-planted into a tmpdir copy of `04_policy_failure_modes.py` → FAIL. **This is the
  case that passed before the fix.**
- a script that adds its own `--foo` and reads `args.foo` → PASSES, so the check does not forbid
  local flags.
- the canary: `base_dests()` asserts `dry_run` and `n` are among the parser's dests, so a `P.parser`
  that returned an empty parser could not make the whole sweep vacuous.

One self-inflicted follow-on, worth recording because it is the same class: the first version of the
test asserted `"args.state" not in src` over the raw source, and **failed on the explanatory comment
I had just written above the fixed lines.** A comment about a read is not a read. The assertion now
goes through the AST.

### Direction of the effect on the document under test

Neutral. No measurement changed; a crash was converted into a test. The script's behaviour after the
fix is the behaviour its docstring and dry-run banner already described.

---

## DEV-P4-18 — the write guard charged 49 innocent tests for a concurrent live run's writes, because a tree diff observes change and not authorship

### What happened

The root `conftest.py` write guard has two channels: a `sys.addaudithook` that records in-process
authorship, and a tree diff over `results/` and `evidence/` that catches writes made by
**subprocesses**, which the audit hook cannot see. Its documented row 2 reads: *diff moved + the test
spawned a child → FAIL, charged to that test.*

While F5-4a's live run was in flight — rewriting `results/checkpoints/F5-4a__control_no_probe.json`
after each of 100 trials — the full suite was run beside it:

    1438 passed, 3 skipped, 49 errors in 637s

All 49 errors read `MODIFIED results/checkpoints/F5-4a__control_no_probe.json`. **Every charged test
was innocent.** They were charged for one property only: they spawn subprocesses, so row 2 applied.

A guard that convicts on opportunity rather than evidence is worse than no guard: 49 red teardowns on
a green suite teach the reader to disregard the guard's output, which is exactly when it will miss a
real write.

### The instrument change

A third channel: the **process table**. The honest discriminator is *"is a script from THIS tree
running in a process that is not a descendant of this pytest run?"* `_foreign_live_run()` reads
`ps -eo pid=,ppid=,command=`, computes the parent-chain closure of this pytest pid, and reports repo
scripts running outside it.

Three properties matter more than the mechanism, and each has its own arm:

- **It is not an amnesty.** When a foreign run is identified, the spawning tests are recorded
  `UNCLEARED`, not cleared, with the sentence *"These tests are neither charged nor exonerated;
  re-run with nothing live to settle them."* A child that really did write is indistinguishable from
  the foreign run's writes while that run is in flight, and the summary says so.
- **A dry run is not an excuse.** A `--dry-run` process makes no AWS call and writes nothing, so it
  cannot explain a tree change. Excluded from the foreign set.
- **Containment is checked after `resolve()`.** The first version wrote `(ROOT / script).exists()`,
  and `ROOT / "/abs/path"` **discards ROOT** — so a live run in a *different checkout* satisfied it
  and was credited to this tree. Now resolved and prefix-checked.

A residual, stated rather than papered over: a *relative*-path launch from another checkout is
indistinguishable, because the process table carries no cwd. That error can only move a charge to
`UNCLEARED`; it can never manufacture a conviction.

And the guard fails safe: any `ps` failure returns the empty set, i.e. falls back to charging the
test. A guard that cannot make its observation must not treat absence of observation as exoneration.

### Mutation-checked, four new arms and four new mutants

Arms in `lib/tests/test_write_guard.py`:

- a genuinely foreign live run (double-fork + `setsid` + `execv`, so the writer is reparented to
  init) → the spawner's charge becomes `UNCLEARED`, and the output names the pid and the script.
  **This is the case that produced the 49 errors.**
- a foreign **`--dry-run`** → still convicted.
- a live run in a sibling `other_checkout/` launched by absolute path → still convicted, and the
  foreign script's name does not appear in the output.
- the identical script `Popen`'d **by the test** (a descendant) → still convicted.

Mutants in `lib/tests/test_write_guard_mutation.py`, each with a named killer: M12 foreign channel
removed, M13 dry-run becomes an excuse, M14 descendants count as foreign, M15 scope is the machine
rather than the tree. Harness green at **39 passed**.

Two smaller fixes fell out. `cmd[:120]` was truncating to the macOS interpreter path
(`/opt/homebrew/Cellar/python@3.12/.../MacOS/P`), cutting off the script that identifies the run —
now sliced from the script token. And `pytest_terminal_summary`'s first sentence still read *"no test
spawned a child that could have"* while an `UNCLEARED` block was printed below it; two statements
about one session, and the wrong one was the reassuring one.

### Direction of the effect on the document under test

Neutral — no case measurement is touched. On the guard's own axis the change is **not** a
relaxation: the false convictions became `UNCLEARED`, which still fails to exonerate, and three of
the four new arms assert that a conviction *survives*.

---

## DEV-P4-19 — the refutation's own conjunction held on an empty dict, and its literal-scan tripped on its own comment

### What happened

Two defects in the instrument that supports FINDING-F5-4A's headline claim. Neither reached a
published number: both were caught by the tests written alongside, before the finding was filed. They
are recorded because in both cases the *first* version would have read as a pass.

**1. `all()` over nothing is True.** `f5_redteam/04b_logonly_flip_read.py` refutes §7.1 by ANDing five
conjuncts. The first version was:

    all(v is True for k, v in contrast.items() if k != "n_per_arm")

If `_contrast` ever lost a key — a renamed arm constant, a schema change in `results/phase1/F5-4a.json`,
a `.get()` returning `{}` — the selection shrinks and the conjunction gets **easier**. On an empty
dict it returns `True`: the strongest claim in the finding would have been supported by no conjuncts
at all. Fixed by enumerating `CONJUNCTS` and requiring exact key-set equality, so a missing conjunct
is a `False` and an unenumerated extra one is also a `False`.

**2. A scan that failed on its own documentation.** `test_no_window_timestamp_is_hardcoded_in_the_script`
asserts the probe window is derived from the recorded result rather than re-typed. Its first version
scanned raw source and failed on the comment in `_window_from_recorded_result` that explains *why*
hardcoding `22:46:33Z .. 23:04:03Z` would be wrong. Now it scans AST constants with docstrings
excluded, and `test_that_literal_check_is_not_vacuous` asserts both halves: that the scan finds real
literals, and that the forbidden substring **is** present in the raw file, inside a comment — so the
distinction is pinned rather than assumed.

This is the second instance of that exact mistake in this segment (see DEV-P4-17). Prose about code
is not code; a check that cannot tell them apart fails on its own explanation, and the tempting fix
is to delete the comment.

### Mutation-checked

- `_inference_holds({})` → must be `False`. **This is the case that passed before the fix.**
- each of the five conjuncts planted `False` in turn → the whole conjunction breaks, and the arm
  asserts the *named* conjunct went False, so a mutation that broke a different one still fails.
- `test_every_conjunct_is_covered_by_a_breaker` → set equality between the conjuncts and the
  breakers, so a sixth conjunct added later without a test fails immediately.
- `n_per_arm` (the one non-boolean key) present → the conjunction still holds, so a count of 20 can
  never be read as a `True`.

### Direction of the effect on the document under test

Against the finding, and deliberately: both fixes make the refutation of §7.1 **harder** to reach.
The published value is unchanged — the read was re-run under the corrected conjunction and returned
the same three readings and the same `s7_1_inference_is_refuted: true`.

---

## DEV-P4-20 — F5-1's span positive control never opened an MCP session, and two live days hid it behind two different strings

### What happened

F5-1's span corroboration leg asks whether a direct Lambda invoke produces an
`AgentCore.Policy.AuthorizeAction` span. Absence is only informative if presence is observable in
the same window, so the leg sends **one ordinary gateway `tools/call`** as a positive control and
reports `INSTRUMENT_UNAVAILABLE` if that control's own span never lands.

The control call was `mcp_client.call_tool(...)` with **no preceding `initialize()`**. This gateway
carries `sessionConfiguration`, so a `tools/call` without an MCP session id is answered HTTP 400 —
a transport refusal with no bearing on any hypothesis in this case. Every other script that talks
to this gateway (`f2_determinism/02`, `f3_efficacy/08`, `f4_modes/01`, `f6_latency/02` and `/03`,
`f7_observability/01`–`/04`) calls `initialize()` first. This one did not, and **no test asserted
the sequence**: the convention was carried by nine scripts and checked by none.

**Two live days, two different readings, the same defect.**

| | 2026-08-11 | 2026-08-12 |
|---|---|---|
| invokes inside the granted window | **0** (the arm was served from a crashed run's checkpoint) | 20 |
| leg reading | `NO_INVOKES_IN_WINDOW` | `INSTRUMENT_UNAVAILABLE` |
| control call attempted? | **no** — short-circuited before reaching it | yes, and it raised |
| control span seen? | n/a | no, after a 303.1 s wait |

Day 1 never reached the line. Day 2 reached it and the guard caught it correctly: the leg published
`control_call: {ran: false, error: "McpTransportError: no MCP session id …"}` and read
`INSTRUMENT_UNAVAILABLE`, and `absence_is_bounded_not_proven` was **not** published. So no false
claim was ever made from this — the design's fail-safe is the reason this is a deviation and not a
retraction. What it cost is the corroboration itself: **the leg has produced no measurement on
either day**, and F5-1's span half stays unmeasured while its 120-trial verdict is unaffected
(`ZERO_EVENTS` reads `obs.adverse` and `n`; the span is in the plan, not in the decision rule).

### The fix, and why it is not a re-run

`initialize()` now precedes the tool call, **inside the same `try`**, so a refused session is
recorded as `control_initialized: false` with the error rather than raised into the case. The
distinction is kept: a session that opened and a *tool call* that then failed reads
`control_initialized: true`, because collapsing the two would hide which half broke.

The leg is deliberately **not** being re-measured by re-running F5-1. It cannot move the verdict,
and re-running it costs 161 invocations and two IAM mutations to fill in a corroboration line. It
will be measured by the next run of this case that reaches the branch, whenever that is, and until
then the finding says so.

### Mutation-checked

- `initialize()` deleted from the script → **exactly the two new tests fail** (`2 failed,
  41 passed`), and re-instating it returns `43 passed`. The mutation was applied by rewriting the
  file and restored from a `cp` copy, never `git checkout` (an API-pushed tree is ahead of `git
  HEAD`).
- `initialize()` raising → the tool call must **not** be attempted (asserted on a recording fake),
  `control_initialized` is `False`, the reading is `INSTRUMENT_UNAVAILABLE`, and no bounded-absence
  claim is published.
- the order assertion is `order == ["init", "control"]`, not `"init" in order`: a call sequence that
  initialised *after* calling the tool would satisfy membership.

### Direction of the effect on the document under test

Neutral, and it removes a corroboration that would have **supported** the document. §4.4 row 3's
non-bypassable claim is what an absent `AuthorizeAction` span for a direct invoke would corroborate,
so the leg failing costs the document a supporting observation, not the project a finding.

---

## Analysis-time deviations

*(None yet — this section is populated during Phase 9. Each entry states the
pre-registered analysis, what was done instead, why, and whether the change
favoured or disfavoured the document under test.)*
