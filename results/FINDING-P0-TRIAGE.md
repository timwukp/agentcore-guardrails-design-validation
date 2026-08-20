# FINDING-P0-TRIAGE — What the coverage gate caught

**Phase** 0 (offline) · **Cost** $0 · **Date** 2026-08-09
**Artifacts** `claims/triage.csv` (546 rows) · `EXCLUSION_REGISTER.md` (437 lines) ·
`results/FINDING-F0-1-references.json` · `claims/tests/` (381 tests)

<!-- provenance
{
  "status": "INTERNAL",
  "evidence_runs": [],
  "note": "The subject is the document's own text and our triage of it, both static files. Re-parsing the same bytes tomorrow is not an independent observation."
}
-->

---

## 1. Why this document exists

Phase 0 produced no measurement of AWS. Its deliverable is a different thing: a
**provable denominator**. Before any experiment runs, the project has to be able
to say how many claims the document makes, which of them an experiment can reach,
and — for the rest — why not. Everything downstream is conditional on that number
being honest.

The interesting content of Phase 0 is therefore not the artifacts but **what the
gate rejected while they were being built**. A gate that passes on the first run
has not been tested; it has been satisfied. This one failed with 131 problems, and
every category was informative. Four of the defects were in the document's favour
(my checks were wrong), and those are recorded here with equal weight, because a
validation project that only reports findings against its subject is not
measuring — it is prosecuting.

---

## 2. Result summary

| | Value |
|:---|---:|
| Structural units extracted from the `.md` | 650 |
| Claimable units (headings and marked non-claims dropped) | 535 |
| Atomic claims after 7 splits (7 parents → 18 parts, +11 net) and 25 merge groups | **546** |
| Carrying an experiment (E+S+C+O) | **385 (70.5%)** |
| Definitional (D) — the document's own framework | 94 (17.2%) |
| Normative (N) — value judgements | 57 (10.4%) |
| Excluded, testable in principle (X) — **the real gaps** | **10 (1.8%)** |
| Test cases designed | 93 (90 cited, 3 declared platform prerequisites) |
| Coverage-gate checks | 15/15 pass |
| Gate self-test | 14/14 mutations killed, control arm clean |
| §10 documentation references verified | **24/24** |

The headline is **70.5%, not 100%**, and the 29.5% is itemized rather than
rounded away. Of that remainder, only 1.8% is a gap a reviewer should attack; the
rest has no truth value an experiment could reach, which `EXCLUSION_REGISTER.md`
states claim by claim.

---

## 3. Defects the gate found in my own work

### 3.1 Twelve oracles described a measurement, not a falsification

CHK-06 requires every case to state what observation would make the claim
**FALSE**. Twelve did not — F3-3, F3-5, F3-7, F3-8, F3-9, F5-5, F6-2, F6-3, F6-4,
F6-5, F6-6, F7-6. Each read like a plan ("measure p50/p90/p99 at n=1000") rather
than a test.

This is the single most consequential Phase 0 finding about *methodology*, because
a case with no falsifying condition **cannot fail**. Run it, write down the
number, and it "passes" — which means the experiment carries no information. The
rewrite forced a decision in each case about what result would count against the
document:

| Case | Before | After |
|:--|:--|:--|
| F3-5 | "measure score separation by topic" | "FALSE if the intervals overlap, which would mean the topic definition carries no discriminating power" |
| F7-6 | "measure metric publish lag" | "FALSE for every §6.4 alarm whose evaluation period is below the measured p90 lag" |
| F6-3 | "measure Cedar authorization latency" | "FALSE if the measured p50–p99 band lies outside the documented 5–50ms" |

F7-6's rewrite changed what the experiment is *for*. As a measurement it produces
a lag figure. As a falsification it tests every §6.4 alarm recommendation against
that figure — and the document does not mention that its alarms have a floor set
by publish lag at all.

### 3.2 Six claims were classified as needing evidence no case produces

CHK-07 requires a claim's class to match at least one case it cites. Six were
mismatched, and each would have been published with the wrong kind of statement
attached:

`C-s2-1-mermaid-014` E→C · `C-s2-1-mermaid-019` E→S · `C-s3-2-bullet-014` C→S ·
`C-s4-4-prose-005` E→S · `C-appB-trow-001` C→S · `C-s4-4-bullet-002` E→S

Five of the six were E or C claims that are actually **statistical** (the sixth,
`C-s2-1-mermaid-014`, went E→C). Left alone, each of those five would have been
reported as a deterministic yes/no when the underlying evidence is a rate with a
confidence interval — the exact overclaim the class system exists to prevent.

### 3.3 Fifteen merge groups disagreed internally about class

A merge group models one proposition restated across sections; per
`feedback_grep_the_claim_not_the_phrasing`, a claim amended at 1 of 4 sites is not
amended. Fifteen groups had members carrying different classes from their
canonical site, because coarse `(anchor, unit_type)` rules were overriding the
specific classification.

The consequence was concrete and bad: §9's mermaid labels would have been scored
**D (definitional)** while the prose they restate was scored **S (statistical)**.
D rows are invisible to the v1.3 amendment pass. So a measurement contradicting
the document would have amended the prose and silently left the diagram asserting
the falsified claim — which is precisely the failure the merge groups exist to
prevent, reintroduced by the classification layer.

Fixed structurally rather than row by row: a member classified by a coarse rule
now **inherits** the canonical's class and cases, on the reasoning that a
restatement cannot require a different *kind* of evidence than the proposition
itself. Explicit overrides still win, because those were written after reading the
specific wording.

### 3.4 A conjunction was being scored as a single claim

`C-s9-mermaid-011` — "Hop #4: Cedar Tool Auth ~5–50ms · default-deny ·
fail-secure" — appeared in two merge groups, which the triage script treats as
fatal (two canonical sites make "amend every site" ambiguous). The cause was not
the merge groups: the label carries **three independently falsifiable
propositions** and belonged in neither group as a unit.

Split into `-a` (latency, S), `-b` (default-deny, E), `-c` (fail-secure, X). The
classes differ across the parts, which is the point — scoring the label as one
unit would have let a confirmed default-deny result vouch for an untestable
fail-secure assertion. A new fatal check now rejects any merge group pointing at a
split parent.

### 3.5 Twenty-three exclusion reasons were placeholders

CHK-04 requires ≥80 characters of substantive reason. Nineteen rows read
"Best-practice recommendation; see OVERRIDES." — a label, not a reason. Rewritten
to name the obstacle and, where one exists, the remedy.

### 3.6 Twenty-four rows were excluded that were not actually untestable

§10's 24 documentation-reference rows were classed X. Writing their exclusions
made the classification obviously wrong: a URL either resolves or it does not.
Reclassified to **O** with a new case **F0-1**, and the result is in §5 below.

---

## 4. Defects the gate found in *my checks* — four false accusations

Recorded at equal length, because they are the cases where the document was right
and my instrument was wrong. A project that only catches errors in its subject is
not calibrated.

### 4.1 CHK-07 flagged 56 claims; only 6 were real

The check originally required **every** cited case to match the claim's class. An
independent recount showed 50 of the 56 were legitimate: a claim commonly has one
primary case plus supporting ones of a different class — an E claim about
default-deny properly cites the C case establishing that the field exists.

Requiring every case to match would have forced either dropping the primary
evidence or misstating the class. Relaxed to "at least one", with the rationale
written into the docstring so the relaxation is auditable rather than a quiet
loosening. What must still not happen is a claim whose class matches *nothing* it
cites — a claim classed S with only C cases would be published with a confidence
interval no experiment produces. That is what the 6 real errors were.

### 4.2 The reference matcher produced four false positives

The first run of `02_check_references.py` reported 4 of 24 §10 references as
pointing at the wrong page. All four were correct references. Three bugs, all
mine:

1. **`guardrails` and `policy` were on the stopword list** — the two words that
   most distinguish "Guardrails in policies" from "Understanding Cedar policies".
2. **No stemming**, so `policy`/`policies` and `test`/`testing` compared unequal.
3. **Parentheticals were stripped**, and in this document the parenthetical often
   carries the identifying words: "Policy Conditions (when guardrails)" and
   "Testing Policies (LOG_ONLY workflow)" are each matched *only* by their
   parenthetical.

After fixing all three: 24/24. Because loosening a matcher three times is exactly
how a matcher stops being able to say no, a 6-case adversarial probe followed
(wrong page, 404, sibling page, two previously-flagged real pages, all-boilerplate
guard) — 6/6 correct. That probe is now `tests/test_reference_matcher.py`, 18
assertions including 6 negatives, so the 24/24 is not vacuous.

### 4.3 The exclusion register cited an experiment that does not exist

`03_exclusion_register.py` checks that every case ID named in an exclusion reason
exists in the case registry. On its first run it caught `C-s4-5-5-prose-002`
citing **F5-3c** as the reason its claim is untestable — but F5-3c is the arm the
plan explicitly **declined**. The register would have told a reader that a limit
was established by a test that never runs.

The fix required a distinction that had been missing: `DECLINED_ARMS`, separate
from `CASES`. A declined arm is nameable in prose so a limit can be identified
precisely, but it is not in the case registry, so the register cannot render it
under "nearest proxy run". Naming without crediting.

Two X rows also lacked a `Remedy:` sentence and were rejected. Both now carry one,
and `C-s4-1-bullet-008-a` records its remedy explicitly rather than deferring to
its canonical site — so that site stays independently visible to the v1.3
amendment pass.

### 4.4 The redaction gate's own ALLOW list was entirely dead

`check_redaction.py` shipped with 8 reviewed exceptions waiving its own source and
the test suite for "their own pattern definitions". A `--verbose` run reported **0
waived**: every entry was dead, because a regex written as *source* does not match
itself (`\b\d{12}\b` contains no twelve digits).

Dead exceptions are worse than none — they advertise waivers that do not exist, so
a reviewer reading ALLOW concludes the gate was argued down when nothing was
waived. ALLOW is now empty by design, with the reason recorded, and the waiver
*mechanism* is exercised by two synthetic tests: one proving a matching entry
waives, one proving it does **not** silence a second leak in the same file.

The gate also had a real bug found the same way: `main()` read `sys.argv`
unconditionally, so calling it in-process under pytest made argparse `SystemExit(2)`
on pytest's own flags — indistinguishable from the gate's "scan could not be
trusted" exit code, and it would have masked a genuine failure.

---

## 5. F0-1 — the one experiment Phase 0 actually ran

**Claim** §10's 24 documentation references resolve and describe what they claim.
**Oracle** TRUE if every URL returns HTTP 200 and its page title shares a content
word with the row's stated title; FALSE for any non-200 or any page whose title is
unrelated. **Cost** $0 (read-only HTTP to `docs.aws.amazon.com`).

**Result: 24/24 verified.** Evidence with per-URL status, page title and token
overlap in `results/FINDING-F0-1-references.json`. All 24 are on the **strong**
branch — a real title overlap, not a pass on the HTTP 200 alone — which is what
makes "24/24" mean 24 checked titles. **Sealed-oracle verdict:**
`results/phase1/F0-1.json`, **TRUE**, emitted by `claims/02_references_verdict.py`
from that artifact. The record existed only from 2026-08-13: F0-1 was complete,
guarded, and counted outstanding at 0/1 until then, and was found by the
reconciliation written after the same gap on F5-7a (DEV-P4-33).

This is a verdict about **2026-08-09**, the artifact's observation date; link
liveness can change. A re-check must write a second dated file rather than
overwrite the artifact, which is the only observation of that date and the thing
the three numbers above are pinned against.

Two design notes worth keeping:

- The **title** check matters more than the status check. A link resolving to the
  wrong page is worse than a 404, because the reader believes they have been
  handed a source. The 404 announces itself; the wrong page does not.
- A no-network run exits **3 (SKIP)**, not 0. Per
  `feedback_zero_file_scan_is_error`, a check that reached nothing must never read
  as green.

This case began life as 24 rows headed for the exclusion register. It found no
defect in the document — and three in my own matcher.

---

## 6. What is verifiable about this finding

```sh
python3 claims/01_triage.py --check              # triage.csv reproduces from the rules
python3 claims/check_coverage.py                 # 15 checks over 546 claims
python3 claims/check_coverage.py --self-test     # 14 mutations + control arm
python3 claims/03_exclusion_register.py --check  # register matches the triage
python3 -m pytest claims/tests/ -q               # 381 tests
python3 check_redaction.py                       # >=800 files, >=45000KB, no identifiers
python3 claims/02_check_references.py            # 24/24, live HTTP
```

The redaction floors are stated as `>=` and checked against a live run by
`claims/tests/test_finding_numbers.py`, never pinned. They were `>=32 files, >=800KB` until
2026-08-20, when `check_redaction.py` stopped selecting files by extension and the real denominator
turned out to be **838 files / 49,393 KB** — a floor 26× below actual is a floor that cannot notice
a broken file list, which is the one thing it exists to notice
(`results/FINDING-P1-REDACTION-ENCODING.md` §4c).

The self-test is the load-bearing one. It mutates the triage in memory 14 ways —
bad class, dropped case, unknown case, missing reason, short reason, untested
claim carrying a case, X claim with no remedy, class mismatch, duplicate id,
fallthrough, bad sha1, bad doc_line, broken merge group, restored split parent —
and requires **the named check** to fire on each, plus a **control arm** proving
no check fires on unmutated input. Without the control arm, a check that failed
unconditionally would score 14/14.

The same discipline applies to the other three gates: the reference matcher has 6
negative cases, the register's checks are mutation-probed 4 ways, and the
redaction gate is run against a canary carrying one instance of every pattern.
Canaries are assembled at runtime from character fragments so no identifier shape
appears as a literal anywhere in the tree — the first draft of that test spelled
out a real account ID and the redaction gate flagged its own test suite, correctly.

---

## 7. Consequences for the plan

1. **Phase 0's coverage gate is green** and so is "stats fixtures match textbook
   values" (prior session). The third Phase 0 gate condition, **κ ≥ 0.80**, is
   still open and depends on the corpora, which are not built.
2. **`PREREGISTRATION.yaml` must carry n = 299**, not 298, as the derived
   determinism requirement. Per `FINDING-P0-STATS`, pinning 298 would commit the
   pre-registration to a number its own power function contradicts.
3. **Three v1.3 candidates are already indicated by Phase 0 alone**, before any
   AWS measurement:
   - §9's Hop #4 label asserts `fail-secure` as a blanket property. Three failure
     modes will be measured; a universal will not be established. The label should
     narrow to the modes actually tested.
   - §6.4's alarm recommendations have a floor set by metric publish lag (F7-6),
     which the document does not mention.
   - §10's references are all correct — worth recording as a positive result,
     since "we checked and found nothing" is only credible from an instrument
     shown able to find something.
4. **No AWS mutation has occurred.** Cumulative project spend **$0** against a
   $55–95 projection.
