# Practice → evidence map — what the design document claims about its own testing, checked

**Purpose.** The v1.4 design document carries 45 numbered best practices and cites this study's cases
inline, 324 times. That inline citation is the whole basis of the claim *this design was measured, it
is not asserted* — and until now nothing checked it. A citation could name a case the register does
not carry, assert a verdict the register contradicts, or rest on a comparison
`results/CITATION-POLICY.md` withholds, and the document would still read as evidence-backed.

`platform/build/practices_source.py` extracts the design from both editions and
`platform/build/check_practices.py` adjudicates every citation against the register and the citation
policy. This file is what the gate found on its first run.

**Nothing in the map is authored.** Not a practice sentence, not a phase name, not a hop number, not a
case id. Both editions are parsed; the payload records their sha256. The one authored file is
`platform/curation/practices.yaml`, which holds only the human rulings on citations the platform's own
rules will not let stand unexamined — 11 of the 294 verdict assertions.

**Standing.** This file is not sealed and it is not evidence. It reports a derivation and the rulings
made on it. Where it and a sealed artifact disagree, the sealed artifact wins and this file is wrong.
Every number below is re-derived by `platform/build/tests/test_practice_evidence_map.py` from the
machine block at the foot of this file; a stale number here fails the build rather than reading as a
finding.

---

## 1. What the two editions actually contain

| quantity | value | how it is obtained |
|---|--:|---|
| numbered best practices | **45** | numbered list items under the practices heading of each of §3.1–§5.3 |
| sections carrying practices | **9** | the headings themselves, grouped by chapter |
| phases | **3** | BEFORE / DURING / AFTER, from the chapter headings |
| checkpoint hops | **6** | `Hop #1`, `#2`, `#2-ALT`, `#4`, `#5`, `#6` — as the section headings name them |
| sections with no hop | **3** | §4.3, §5.2, §5.3 — observability, continuous evaluation and the optimization loop run alongside the hops, not as checkpoints |
| design principles | **7** | §7.1's table |
| anti-patterns | **9** | §7.2's table |
| checklist items | **28** in 4 groups | §8's labelled lists |
| case citations | **324** over **87** distinct cases | bracket spans containing a case id, in both editions |
| citations inside a practice sentence | **15**, across **9** of the 45 practices | the rest sit in the surrounding notes, tables and change log |
| assertions of a verdict | **294** over **28** locations | a citation that also carries `TRUE` / `FALSE` / `INCONCLUSIVE` / `RECORDED` |
| busiest location | **95** in Appendix D | the change log, which cites a case for every amendment |

**The practices heading is derived, not written down.** `Best Practices` occurs 9 times in the English
edition against a runner-up at 1, and `最佳實踐` 9 times against 1 in the Chinese — so the marker is
picked by frequency in each edition separately. A locator typed into this repo would be a translation
of the document, and it would go stale silently the first time a heading changed.

**Both editions carry the same evidence base, and that is checked rather than assumed.** The 324
citations, the 87 cases, and all 294 assertions form byte-identical multisets keyed by
`(case, verdict, location)`, in the same order. A Chinese reader is therefore never shown fewer links,
or different ones, than an English reader. The editions differ by 348 lines, which is exactly why the
assertion ledger is keyed by section id and never by line number.

## 2. Six numbers this round corrected before writing anything

Each of these was believed on a first reading of the documents and is wrong. They are recorded because
the same reading is what a reader does, and four of the six would have shipped as page copy.

| believed | measured | what the difference was |
|---|---|---|
| 338 citations | **324** | the first count included bracket spans in fenced code and diagram blocks |
| 88 distinct cases | **87** | same cause |
| 3 cited ids resolve to no verdict file | **0** | `F5-7B` is not a typo for `F5-7b`: it is the real filename `results/FINDING-F5-7B.md`, and a filename reference is not a citation. 9 such references are excluded by rule, not by name |
| 13 registered cases the document never cites | **6** | `F1-4`, `F1-9`, `F1-10`, `F1-21`, `F2-3`, `F3-9` |
| 6 design principles | **7** | §7.1 gained one in the v1.3 amendment pass |
| 8 anti-patterns | **9** | §7.2 likewise |

The six uncited cases are the coverage ceiling in the other direction: **measured, and the document
says nothing about them.** Four are TRUE (`F1-9`, `F1-21`, `F1-4`, `F3-9`) and two are INCONCLUSIVE
(`F1-10`, `F2-3`). A TRUE the design never mentions is not a defect, but it is not free either — it is
a place where the study established something the guidance does not use.

## 3. The 11 citations that needed a human ruling

Of 294 assertions, 283 agree with the register and are unrestricted. The remaining 11 are ruled in
`platform/curation/practices.yaml`, each with the sentence it is about quoted in both editions — and the
gate re-reads the quotation against the published span, so a ruling cannot outlive the sentence it was
granted for.

| case | asserted | where | disposition |
|---|---|---|---|
| F7-1 | TRUE | §6.2 | `LEGAL_PER_METRIC` |
| F7-1 | TRUE | §7.1 | `LEGAL_PER_METRIC` |
| F7-1 | TRUE | §7.1 | `LEGAL_PER_METRIC` |
| F5-3b | TRUE | Appendix D | `LEGAL_WITHDRAWN_IN_PLACE` |
| F6-2 | FALSE | §6.1 | `OPEN_RESTS_ON_RESTRICTED_DIMENSION` |
| F6-5 | FALSE | §6.1 | `OPEN_RESTS_ON_RESTRICTED_DIMENSION` |
| F6-8 | FALSE | §6.1 | `OPEN_RESTS_ON_RESTRICTED_DIMENSION` |
| F6-8 | FALSE | §4.2 | `OPEN_QUALIFICATION_ABSENT` |
| F6-2 | FALSE | Appendix D | `OPEN_QUALIFICATION_ABSENT` |
| F6-5 | FALSE | Appendix D | `OPEN_QUALIFICATION_ABSENT` |
| F6-8 | FALSE | Appendix D | `OPEN_QUALIFICATION_ABSENT` |

### 3.1 The four legal ones, and why a gate had to be able to say so

**F7-1 ×3 — the register's FALSE is a conjunction, and the document cites the terms.** `F7-1.json`'s
sealed `oracle_text` reads "**Per metric:** TRUE if datapoints appear for our dimensions after traffic
that should produce them; FALSE if absent", and its `verdict_rule` makes the file-level verdict "TRUE
iff **every** EXERCISED documented metric has datapoints". Ten of fifteen documented metrics published;
the FALSE is carried by the three in `absent_though_exercised`. Each of the three document sites names
a metric — `GuardrailLatency`, `LogOnlyDecisionFlips`, `LogOnlyMatches` — whose own per-metric record
says `published: true`. The scoped TRUE is **more precise** than the file-level FALSE, not in conflict
with it, and the case file says so itself: `verdict_reading` = "FALSE for the 13 of 15 documented
metrics whose publishing condition this project's traffic actually creates."

**F5-3b ×1 — cited in order to withdraw it.** The citation policy gives F5-3b `NEVER_CITE` with
`citable_as: []`. This site sits inside Appendix D's paragraph "Deliberately left unchanged (evidence
inconclusive, absent, or untestable)" and, in the same sentence, states that the TRUE **"carries NO
publishable standing, is not counted among published verdicts, and is not cited as confirming any
claim"**. A gate that could not tell disclosure from citation would forbid the document from explaining
why a case is unusable — which is the opposite of what `NEVER_CITE` is for. So `controls.yaml`'s
platform-voice rule (never mention) and the document's narrative voice differ deliberately: **naming a
case is not citing it**, and only the *asserted verdict* needs adjudication.

### 3.2 The seven open findings

These are **published findings, not exemptions.** Each names register item 32, the restriction it
crosses, the dimension that is withheld, and what it is blocked on. The page renders them as
unsettled; nothing in this round presents any of them as a result.

`results/CITATION-POLICY.md` gives F6-2 and F6-5 `PARTIAL`: the p50 and p90 comparison is citable, and
TRUE or FALSE **on the p99 tail** is not, because the day-2 p99 CIs are 435 ms and 375 ms wide against
a 400 ms band. F6-8 is `PARTIAL` on **slope in [165, 750]**, because day 2's CI overlaps the documented
range by 13.6 ms with 36 % of it still above 750.

- **Three sites in §6.1 rest on the withheld dimension in their own words.** "p50 inside the band but
  p99 622 ms above it" (F6-2) and "p50 234 ms, p99 662 ms above the band" (F6-5) place the p50 inside
  the band and carry the FALSE **entirely on the p99**. "the measured interval is disjoint from and
  above it" (F6-8) is precisely the slope-in-range comparison the policy withholds — true of day 1's CI
  `[838.7, 862.7]`, and not true of day 2's `[736.4, 757.5]`.
- **Four sites assert a bare FALSE with no dimension named** — §4.2 and three rows of Appendix D. The
  weaker defect: a reader cannot tell the verdict is scope-bound. Appendix D's row asserts one FALSE
  across a run of five cases (`F6-1, F6-2, F6-3, F6-4, F6-5, all FALSE`); three of the five carry no
  restriction on the verdict itself, and the row gives a reader nothing to distinguish them by.

**F6-2 and F6-5 flipped FALSE → TRUE on day 2**, so these assertions are not merely unlicensed: a
second day does not support them.

### 3.3 The finding that is not about a citation

**FUTURE-WORK item 32's closing condition (b) names only the paper's Chapter 10 table and Figure 3.**
It does not enumerate the design document. So item 32 — opened because two sealed oracle kinds
adjudicate a threshold with no decisiveness requirement, and three verdicts flipped on it — could have
been **closed with all fourteen citation sites still live in the primary deliverable** (seven sites ×
two editions). Condition (a) is already satisfied by `results/CITATION-POLICY.md`.

This is a scope defect in a closing condition, and it is the reason a run of this gate was worth more
than a reading of the document: the register knew about the weak oracle, the policy published the
restriction, and the surface carrying the most readers was in neither one's scope. Item 32(b) is
amended in the same change as this file.

**None of the seven can be fixed here.** The document is a shipped artifact whose hash the payload
pins, and amending it is a v1.5 editorial pass under the amendment rules — not a build step. What this
round does instead is refuse to render any of them as a settled result, and say so on the page.

## 4. What the gate will not let happen next

The ceiling on open adjudications is **7** and it ratchets **down** only. There is deliberately no
floor: a floor would make fixing the document fail the build. The ledger is counted **both ways** — an
occurrence with no ruling fails, and a ruling whose occurrence has vanished fails — so there is no
third state in which a defect is quietly excused. `platform/build/tests/test_check_practices.py` holds
25 arms, each of which mutates the passing tree and requires the named finding; the first is a
no-mutant control, because a gate arm that has never fired is indistinguishable from one that cannot.

---

<!-- machine
{
  "schema": "grx-practice-evidence-map/1",
  "authoritative_for_tooling": false,
  "note": "Every value here is re-derived by platform/build/tests/test_practice_evidence_map.py from practices_source.extract_files() and check_practices.adjudicate(). This block exists so the prose above cannot drift: a number in a sentence is unchecked, and this project has been wrong that way before. Nothing here is evidence; the register and results/CITATION-POLICY.md are.",
  "derived_on": "2026-08-23",
  "design": {
    "n_practices": 45,
    "n_sections": 9,
    "n_phases": 3,
    "hops": ["1", "2", "2-ALT", "4", "5", "6"],
    "sections_without_hop": ["4.3", "5.2", "5.3"],
    "n_principles": 7,
    "n_anti_patterns": 9,
    "n_checklist_items": 28,
    "n_checklist_groups": 4,
    "marker_frequency": {"en": 9, "zh": 9},
    "marker_runner_up_frequency": {"en": 1, "zh": 1}
  },
  "citations": {
    "n_citations": 324,
    "n_distinct_cases": 87,
    "n_inside_a_practice": 15,
    "n_practices_carrying_one": 9,
    "n_assertions": 294,
    "n_assertion_locations": 28,
    "busiest_location": {"where": "app:D", "n": 95},
    "n_cited_outside_the_register": 0,
    "uncited_registered_cases": ["F1-10", "F1-21", "F1-4", "F1-9", "F2-3", "F3-9"]
  },
  "adjudications": {
    "n_registered": 93,
    "n_adjudicated": 11,
    "n_legal": 4,
    "n_open": 7,
    "open_ceiling": 7,
    "by_disposition": {
      "LEGAL_PER_METRIC": 3,
      "LEGAL_WITHDRAWN_IN_PLACE": 1,
      "OPEN_RESTS_ON_RESTRICTED_DIMENSION": 3,
      "OPEN_QUALIFICATION_ABSENT": 4
    },
    "open_register_items": [32]
  },
  "gate": {"mutation_arms": 25}
}
-->
