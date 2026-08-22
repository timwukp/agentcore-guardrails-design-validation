# Site review, 2026-08-22 — making the evidence legible without weakening a claim

Two halves, kept separate on purpose:

- **A cited-literature pass** (workflow `wf_0cce59f1-553`, 108 agents, 0 errors, 54 min): 5 search
  angles, 26 sources fetched, 129 candidate claims extracted, 25 taken to three-vote adversarial
  verification, **12 confirmed / 13 killed**, merged to 7 findings.
- **A first-hand browser walk** of the built site under the production CSP (`csp_preview.py`, en and
  zh-TW), where every number below was measured in the rendered DOM rather than read off source.

Every recommendation is labelled **[C]** cited to a verified primary source, **[I]** our inference
from a cited source, **[U]** unsourced judgement, or **[M]** measured here (reproducible command
given). Quantitative claims carry their denominator.

---

## 0. The single most important result of the research pass

**Three of the five search angles produced zero surviving sources.** Nothing on ISO 24495-1 plain
language, the Plain Writing Act, Nielsen Norman scannability, standards-body practice for a normative
text plus an explanatory companion, WCAG 2.2 (1.4.1, 1.4.3, 1.4.11, 2.4.x, 3.1.1, 3.1.2, 1.3.1),
colour-vision-deficiency-safe ordered 5-value palettes, zh-TW typography or line length, W3C PROV,
FAIR, ACM artifact badging, machine-readable claim-to-evidence linkage, publish-gating practice, or
visualization-defect / deceptive-chart taxonomies survived verification.

Consequence, stated before any recommendation is read: **the rigour-audit checklist in §6 has no
citation base and is written [I]/[U] throughout.** So is most of the landing-screen design (§4) and
all of the accessibility encoding advice. A second research pass aimed directly at W3C normative
documents, the ACM badging vocabulary and the deceptive-visualization literature is required before
any of §6 may be relabelled [C]. Angle 1 (uncertainty and negative results) is well sourced; angle 2
rests on a single 2002 experiment that returned a **null**.

This is not a failure of the pass. It is the pass declining to dress inference as citation — the same
discipline the site exists to demonstrate.

---

## 1. What the sources do establish

**1.1 A three-plus-state verdict encoding is statistically mandatory, not stylistic. [C] high**
Greenland, Senn, Rothman, Carlin, Poole, Goodman, Altman, *Eur J Epidemiol* 31:337-350 (2016),
verified verbatim in the OA PMC full text, item **#6 of 25** enumerated misinterpretations: *"A
null-hypothesis P value greater than 0.05 means that no effect was observed, or that absence of an
effect was shown or demonstrated. No!"* Item **#4**: *"It is simply false to claim that statistically
nonsignificant results support a test hypothesis."* Restated normatively in Amrhein, Greenland &
McShane, *Nature* 567:305-307 (2019), verified from the publisher's own OA PDF: *"we should never
conclude there is 'no difference' or 'no association' just because a P value is larger than a
threshold such as 0.05 or, equivalently, because a confidence interval includes zero."*

So keeping INCONCLUSIVE in its own third colour, never merged with TRUE, and drawing `not_measured`
loudly, is **required by the inference, not a house style** — that much is [C]. The step from the
prohibition to a UI encoding is [I].

**The prohibition aims most sharply at INCONCLUSIVE, not at FALSE.** An earlier revision of this
document concluded from that premise that the site's caveat mechanism is mis-aimed. It is not: the
site covers INCONCLUSIVE by a **rule** rather than by a per-case field, which is the stronger
construction, because a rule cannot drift from the verdict and 20 hand-written sentences can. See the
corrected §3.1 and the withdrawal of R1.

**1.2 Interval bounds are not refuted/not-refuted boundaries. [C] high**
Greenland et al. item **#20 of 25**, verbatim: *"An effect size outside the 95 % confidence interval
has been refuted (or excluded) by the data. No!"* Same paper, the UI-relevant reason: *"two
hypotheses may have nearly equal P values even though one of the hypotheses is inside the interval
and the other is outside."* Rafi & Greenland, *BMC Med Res Methodol* 20:244 (2020): such declarations
*"perpetuate the fallacy that information changes abruptly across decision boundaries"*.

**Audited on this site, and clean [M].** A scan of the whole payload finds 22 occurrences of
"refuted", every one of them about a *document claim* being contradicted, plus `findings.json`'s
*"INCONCLUSIVE licenses no amendment. The claim is not refuted."* There is no instance of an interval
boundary being described as refuting or excluding a value. Reproduce with:
`cd site/dist/data && grep -ric 'refuted\|excluded by the data\|ruled out' *.json cases/*.json`.
What #20 forbids is not present. **Do not "fix" this.** A pre-registered threshold decision is
explicitly still legitimate — Greenland et al. note alpha *"is supposed to be fixed in advance and is
thus part of the study design"* — so "p90 CI upper bound below the pre-registered threshold at
pre-registered alpha" states a supported decision. Two wording traps to keep out of future copy:
"compatibility interval" is one group's proposal and must be attributed, not presented as convention;
and the site's `p50/p90/p99` are percentiles of the latency distribution, **not** the nested
confidence levels Rafi & Greenland mean by "different percentile levels".

**1.3 Showing a CI does not convey it, and "expert audience" is not grounds to omit a gloss. [C]
medium (negative form only)**
Hoekstra, Morey, Rouder & Wagenmakers, *Psychon Bull Rev* 21(5):1157-1164 (2014). Denominators: **6**
deliberately false CI statements per respondent; n = **442** first-year students with no inferential
statistics, **34** masters, **120** post-master researchers. Mean false statements endorsed:
first-years **3.51** (99% CI [3.35, 3.68]), researchers **3.45** (99% CI [3.08, 3.82]); only **3 of
120** researchers (3%) marked all six false; self-declared experience correlation **r = 0.04, 99% CI
[-0.20, 0.27]**.

Two disciplines this imposes on our own writing. **Never write "uncorrelated"** — [-0.20, 0.27] does
not exclude a modest helpful relation, and collapsing it would be the exact error this site exists to
avoid. And the strong reading is **contested in print**: García-Pérez & Alcalá-Quintana (*Front
Psychol* 2016) criticise the one-directional item set and absent "don't know" option and conclude
misinterpretation *"is not as prevalent and widespread as Hoekstra et al. (2014) purported"*; in that
replication trained students **did** discriminate. So this licenses only the negative claim — an
expert readership is not a reason to drop an operational gloss — and **not** the positive claim that
adding a gloss improves reading, which no located source tests. That step is [I].

**1.4 A citable human-review checklist for trustworthy (not persuasive) presentation. [C] high**
Blastland, Freeman, van der Linden, Marteau & Spiegelhalter, "Five rules for evidence communication",
*Nature* 587:362-364 (2020), anchored on O'Neill's *accessible, comprehensible, usable, assessable*
and the instruction to *"inform but not persuade"*, with a ten-item tips box including *"unapologetic
uncertainty"*, *"say when you don't know … and by when"*, do not cherry-pick, and same-format
presentation of benefits and harms.

**Two hard limits.** It is a Nature **Comment** — opinion genre, no effect sizes — so it supports a
*human*-review checklist and **cannot** be cited to justify a mechanical gate. And Nature 303-redirects
to an IdP with `oa_status: closed`, so the tips box was verified against two independent verbatim
reposts. Those reposts are the weakest link in this whole document: **re-verify the box against the
Nature text before quoting it on screen.**

**1.5 Do not claim that showing uncertainty builds trust. [C] high, and it cuts against us**
van der Bles, van der Linden, Freeman, Mitchell, Galvao, Zaval & Spiegelhalter, *PNAS* 117 (2020),
5 experiments including a preregistered national replication and a BBC News field experiment, total
n = **5,780** UK/US general public: *"we observed only a small decrease in trust in numbers and
trustworthiness of the source, and mostly for verbal uncertainty communication."* The "transparency
might build trust" line in the 2019 *R Soc Open Sci* framework paper is **O'Neill's normative
argument, not a measured effect**; no located study measured a trust increase.

Directionally useful for us: because the measured penalty concentrates in **verbal** uncertainty, the
site's numeric form (counts, CIs, four denominators) is the better-supported presentation [I]. And
van der Bles et al. instruct communicators to *"test the effect of your communication with your
audience"* — that clause is [C] and this site has never done it (§7 open question).

**1.6 Verbal qualifiers are decoded at values their publisher never intended. [C] medium**
The IPCC defines "very likely" as ≥90%; the median lay reading is about **65-75%** (van der Bles et
al. 2019 reporting Budescu et al.; note the framework paper is **not primary** for this number and
the Budescu primaries are paywalled, so their N and country denominators are unverified and must not
be asserted). This supports co-rendering an operational definition **in line** beside a label rather
than only in a glossary [I] — the IPCC already published a translation table and the gap persisted.
It establishes **nothing** about how categorical labels like INCONCLUSIVE or "TRUE but non-citable"
are decoded; "decoded at a value" is not even well defined for them. No located source tests verdict
or badge vocabularies.

**1.7 Publishing all four denominators is an interpretability requirement. [C] high**
Wasserstein & Lazar, *The American Statistician* 70(2):129-133 (2016), **Principle 4 of 6**, "Proper
inference requires full reporting and transparency", specifying the disclosure set as *the number of
hypotheses explored, all data collection decisions, all statistical analyses conducted, and all
p-values computed*; selective reporting *"renders the reported p-values essentially
uninterpretable"*. Quote it exactly on screen: the third item is *"all statistical analyses
conducted"*, not "all analyses conducted".

Two riders. The source says nothing about "prose definitions and a named source each" — that rider is
ours. And disclosure is **necessary, not sufficient**: publishing four denominators does not license
naive per-case reading of 91 p-values without multiplicity treatment, so the site may not claim that
transparency alone validates the case-by-case p-values.

**1.8 An overview-first landing screen cannot be justified on comprehension. [C] medium**
Hornbæk, Bederson & Plaisant, *ACM TOCHI* 9(4):362-389 (2002), n = **32** subjects, **2** maps:
*"no difference between interfaces in subjects' ability to solve tasks correctly"*; subjects were
**faster without** the overview on one map, and that condition **improved object recall** — the
measure closest to comprehension favoured *no* overview. Yet **80%** (~26 of 32) preferred the
overview.

Two scope guards. The paper's own opening sentence says the literature *establishes* overview
usability and that results are mixed *for zoomable UIs specifically*, so this must never be cited for
"overview-first is folklore". And the abstract reports **no detected** difference with no power
analysis or effect size — "no benefit established", not "no benefit exists". Practical consequence: a
newcomer landing screen is justifiable as an **orientation and accessibility affordance**, and reader
approval of it **must not be reported as validation**.

---

## 2. Material that must never be reused

Thirteen candidate claims were killed. Several look load-bearing:

| Killed claim | Vote | Why it matters |
|---|---|---|
| "791 articles across 5 journals, 51% wrongly assumed non-significance means no effect" | 0-3 | Must not appear anywhere. |
| **All five** claims from the one progressive-disclosure/transparency paper searched (ACM `10.1145/3374218`) | 0-3 / 1-2 | That paper **cannot be cited at all, in either direction** — including to *reject* an error-hiding first layer. |
| Several ASA Principle 3/6 and Conclusion claims | 0-3 | The surviving ASA warrant is **Principle 4 only**. There is **no citable ASA warrant for "no pass rate"** or for a three-state encoding — that warrant comes from Greenland/Amrhein. |
| "Four unsolicited comments about n=100"; the COVID test-wording trial | 0-3 | From the Nature Comment; only the ten-item tips box and the O'Neill anchoring survive. |

Also killed by inspection of the surviving sources: **"absence can never be shown."** Lakens 2017
(`10.1177/1948550617697177`) documents the one legitimate route — prespecified equivalence bounds
(SESOI) with both one-sided TOST tests rejecting, *"not mere nonsignificance"*. Which raises a real
question for us, in §7.

---

## 3. First-hand findings from the browser walk

### 3.1 CORRECTED — the caveat gap was already derived, counted and disclosed; what is missing is prose [M]

**This section replaces a wrong one, and one of its replacements was wrong too.** The original 3.1
reported a 42/49 split by verdict, claimed the schema has no slot for INCONCLUSIVE, and claimed
"39 of 91" does not reproduce. The first two were errors of mine and are withdrawn below. The third was
a real defect, which I then **wrongly withdrew** on a false premise before grepping for it; it is
reinstated in corrected form in §3.1b. A correction inherits no credibility from the error it replaces,
so each number below names the producer it was derived from.

**The measurement was of the wrong property.** My scan matched `'does_not_prove' in k` recursively over
each case file, so a FALSE case was credited for carrying `what_true_does_not_prove`. The site does not
present that as the case's caveat — `CaseDetail.tsx:180-189` files the opposite verdict's sentence in a
**collapsed `<details>`**, correctly, because a bound on a reading the case did not make is not that
case's caveat. So the 42/49 table measures "any caveat field present anywhere", which is not a
reader-facing property. It is withdrawn.

**"39 of 91" — my withdrawal of this was itself wrong, twice over.** After withdrawing it on the
grounds that "39 was never a claim of this repo", I grepped: it **is** a claim, in
`platform/audit/report.py:107` and repeated in `platform/audit/tests/test_report.py:396`. The
correct finding is different from both of my earlier ones, and is in §3.1b.

**The authoritative numbers, from the producer that computes them**
(`platform/build/build_site_data.py:462-502`, published at `site/dist/data/method.json` → `caveats`):

| verdict | owed a per-case caveat | record carries one | record carries none |
|---|---|---|---|
| TRUE (46) | yes | **19** | **27** |
| FALSE (23) | yes | **1** | **22** |
| INCONCLUSIVE (20) | no — covered by rule | — | — |
| RECORDED (2) | no — covered by rule | — | — |
| **owed (69)** | | **20** | **49** |

The builder states the scoping rule in its own comment — *"A caveat is only owed where the verdict has
a direction to over-read"* (line 462) — and publishes the **exact case lists**,
`true_verdicts_without_the_caveat` (27) and `false_verdicts_without_the_caveat` (22). So the gap is
derived, counted, and named case by case. Nothing was hidden.

**Absence is a rendered state, not a skipped one.** `CaseDetail.tsx:164-178` draws a `note warn` naming
the missing field and the verdict; `CaseDetail.tsx:148-157` renders a rule-derived caveat for every
INCONCLUSIVE case. The component's own header comment says so: *"`absent` is a rendered state, not a
skipped one"*.

**What is actually owed is 49 sentences of prose** — 27 TRUE + 22 FALSE. Note that this total coincides
with the wrong number above; the compositions differ, and **the coincidence is not corroboration**.

### 3.1a NEW DEFECT — a RECORDED case's caveat is dropped, and the page asserts it does not exist [M]

`CaseDetail.tsx:140-142` branches on FALSE and TRUE only, so for a **RECORDED** verdict:

- `mine` is `null` regardless of what the record carries;
- `key` falls through to `"what_true_does_not_prove"` — a field name that is wrong for the verdict;
- `other` falls through to `what_false_does_not_prove`, so the `<details>` escape hatch is empty too.

Consequence, on the 2 RECORDED cases:

- **F5-4b** carries a 750-character caveat authored for exactly this verdict — it opens *"nothing here
  is a TRUE"* and names the TIMEOUT failure mode, the CEDAR-evaluator arm, an in-Guardrails failure and
  the standalone `ApplyGuardrail` path as uncovered. The caveat section **does not show it**, and
  displays instead the warn box saying the record carries no such statement. **That warn box is a false
  statement about an artifact the site is holding**, and it is the load-bearing half of this finding.
  (Scope check, run before filing: the text is not absent from the page — `CaseDetail.tsx:830` dumps the
  whole record in a collapsed `RawJson`. So the accurate claim is "not shown where it is owed, and
  contradicted where it is owed", not "dropped".)
- **F5-4a** carries none, and its warn box names `what_true_does_not_prove` — the wrong field for a
  RECORDED verdict.

**The same fall-through hits 8 INCONCLUSIVE cases, more mildly.** For any non-FALSE verdict,
`other` resolves to `what_false_does_not_prove`, which no INCONCLUSIVE case carries — so the 8
INCONCLUSIVE cases that carry a `what_true_does_not_prove` sentence get neither the caveat slot (the
rule box takes it) nor the `<details>` hatch, and their case-specific prose is reachable only by
expanding the raw verdict file. No false statement is made there, because the rule box asserts nothing
about the record; it is a visibility loss, not a correctness defect. Ranked below the RECORDED one.

Also uncounted: because the builder scopes the census to TRUE and FALSE, F5-4b's caveat appears in **no
published number** — the "unnumbered is uncounted" shape. Fix is a verdict-keyed lookup rather than a
two-way ternary, plus a census line for carried caveats outside the owed set.

### 3.1b R2 REINSTATED — "39 of 91" is real, is prose-only, and is wrong; the true value is 33 [M]

`platform/audit/report.py:107` states *"39 of the 91 published cases carry no such statement"*, and
`test_report.py:396` repeats it as a test docstring. Derived under **that file's own definition**
(`read_case_caveats()`, `CAVEAT_FIELDS` = 9 field names, all of `results/phase1/*.json`):

| | count |
|---|---|
| published cases the report sees | **91** |
| carry a statement | **58** |
| carry none | **33** (TRUE 22, FALSE 9, INCONCLUSIVE 1, no verdict 1) |

So the direction is inverted as well as the value: **39 is nearer the count that do carry one than the
count that do not**, and the true figure is 33. Reproduce with the snippet in §8.

Two things keep this small. The **rendered** report is correct — it derives `f"{n_with} of
{len(caveats)}"` at runtime and `test_the_caveat_counts_the_cases_that_state_no_limits` asserts the
derived string appears. The wrong number lives **only in a docstring and a test docstring**: prose,
therefore unchecked. This is the "a number in a justification string is unchecked" shape (§6 item 4),
and the fix is to delete the number from the prose rather than to correct it, since the derivation
already exists ten lines away.

**A likely provenance, labelled as inference [I].** `build_site_data.py:433` initialises
`caveats = {"what_true_does_not_prove": 0, "what_false_does_not_prove": 0}` and lines 456-458 increment
it, but **nothing ever reads it** — the published block at 491 is built from `have_true`/`have_false`
instead. That dead counter is unscoped by verdict, and its value is **39 and 2**: 39 is exactly the
docstring's number. So the repo contains **three** definitions of caveat coverage — the site payload's
(TRUE/FALSE-scoped, one field each: 20 carry, 49 owed-and-missing), the audit report's (9 fields, all
91: 58 / 33), and a dead one that computes 39 — and the only wrong published number matches the dead
one. I did not establish the history; the coincidence is what licenses the inference, and nothing more.
Delete the dead counter with the docstring number.

### 3.2 The zh-TW edition serves its highest-load prose in English, and the verbatim mark is being used to excuse it [M]

The banner at the top of every zh-TW route says: 「本頁引用的產物原文一律保留英文：判定、oracle_text、
案例標題與報告內容是被封印或被推導出來的原始措辭，中文改寫會變成第二份說法，而它唯一的出處就只是這個
網站。」 — *the English on this page is quoted artifacts: verdicts, oracle_text, case titles, report
bodies.*

That is not what the reader is looking at. The five denominator card labels (`registered`,
`verdict eligible`, `published`, `claim mapped`, `claims triaged`) and their entire prose definitions
are English, and their source is `platform/build/build_site_data.py:299,305,312,320,328` — **authored
Python string literals**, the platform's own explanatory prose. Rewriting them creates no "second
version" because there is no first version anywhere else.

Blast radius, measured over top-level payload files: **1024** prose strings (6+ words, no Han, not a
path), of which **582 are traceable to the platform's own source — a floor**, because multi-line
f-strings evade substring matching; the other 442 are quoted artifacts or f-strings the match cannot
see. By file: `audit.json` 198, `architecture.json` 160, `controls.json` 149, `families.json` 33,
`pipeline.json` 29, `denominators.json` 5, `citation_policy.json` 2, `figures.json` 2, `method.json`
2, `MANIFEST.json` 1, `census.json` 1. Among them, in English on the Chinese edition:
`architecture.json.status_labels.not_measured` ("this study never examined this component"),
`status_labels.contested`, and `audit.json.boundaries[].claim` — *"This platform never connects to
your AWS account."*, which is plausibly the single most reassuring sentence on the site for a reader
about to submit a design.

**Root cause.** `site/src/lib/strings.ts` makes a missing translation a **compile error** and
`i18n.test.ts` covers what a type cannot see, but neither has jurisdiction over the payload, whose
prose is authored in Python. All three guard layers sit on the same side of the boundary.

**This finding survived a refutation attempt, unlike §3.1.** The obvious refutation is that the named
payload strings might never reach a screen, so the walk was re-run against the components:
`Architecture.tsx:263` renders `Object.entries(arch.status_labels).map(...)` and `Audit.tsx:211` renders
`a.boundaries.map(...)` — both emit the payload value **directly**, with no translation lookup between
payload and DOM. So *"this study never examined this component"* and *"This platform never connects to
your AWS account."* do reach a zh-TW reader in English. Confirmed, not inferred.

**The marking layer is not broken.** The committed treewalker probe in `csp_preview.py` returns **0**
on this route, correctly: `DIV.def` carries `lang="en"` itself. (An earlier reading of mine that said
otherwise had tested `parentElement.closest('[lang]')`, skipping the leaf's own attribute — the
false-positive shape that probe exists to avoid.) What is wrong is one level up: **`lang="en"` now
carries two incompatible meanings** — "sealed quotation, may never be translated" and "authored prose,
not yet translated" — and no gate asks which. The banner then tells the reader it is always the
first.

### 3.3 INCONCLUSIVE's encoding contradicts the prose directly above it [M]

Measured against the page background `rgb(16,20,26)`:

| verdict | colour | contrast | WCAG 1.4.3 AA (4.5) | AAA (7.0) |
|---|---|---|---|---|
| TRUE | `rgb(47,161,155)` | **5.89** | pass | no |
| FALSE | `rgb(208,138,62)` | **6.50** | pass | no |
| INCONCLUSIVE | `rgb(124,135,152)` | **5.08** | pass | no |
| RECORDED | `rgb(138,123,208)` | **5.12** | pass | no |

All four pass AA for normal text; none reaches AAA. 1.4.1 Use of Color is satisfied by redundancy —
bar segments carry their counts as in-bar text (46/23/20/2) and the legend spells the names.

The defect is semantic, not contrast. INCONCLUSIVE is drawn in **desaturated slate grey** — the
universal convention for disabled, missing, no-data — immediately above prose insisting *"INCONCLUSIVE
is a result, not a missing one … it licenses no amendment"*. This is the same defect class the project
already fixed once, by drawing `not_measured` boxes loudly. Note the research pass produced **no
surviving source** on ordered 5-value palettes, so any specific replacement colour is **[U]**.

### 3.4 The landing route front-loads the hardest content [M]

Heading order is clean (`H1 agentcore-guardrails-design-validation` → `H2 Census` → three H3s, no
skipped levels). The problem is ordering, not structure: the route opens on the word **"Census"**
(internal vocabulary), then five dense denominator cards whose prose embeds raw identifiers
(`claims/triage_rules.py::CASES`, `PREREGISTRATION.yaml`, `results/phase1/*.json`), while the honest
headline — the 46/23/20/2 mix and the "There is no pass rate on this platform" panel — sits **below
the fold**. There is no "start here" affordance, and a newcomer's best entry, "How a verdict is made",
is buried mid-nav under METHOD. 深入淺出 requires the shallow entry to come first; the current order is
its inverse.

### 3.5 Audited and clean — do not "fix" these

- **No interval-boundary "refuted" language** anywhere in the payload (§1.2).
- **No horizontal overflow**: `innerWidth 1309`, `documentElement.scrollWidth 1295`,
  `clientWidth 1295`, `overflowCount 0`. A full-page screenshot *looks* clipped on the right; that is
  a capture-width artifact of the relay browser window, not a layout defect. It was measured before
  being reported, and was not reported.
- **Heading hierarchy** has no skipped levels on the landing route.

### 3.6 Minor

`favicon.ico` 404 is the only console error on the landing route.

---

## 4. Ranked change list

Ranked by reader gain × evidence strength ÷ risk of over-claiming. None of these requires the site to
state anything the artifacts do not support; the ones that would are in §5.

| # | Change | View | Reader gains | Label |
|---|---|---|---|---|
| ~~R1~~ | **WITHDRAWN — do not implement.** "Add a caveat slot named for INCONCLUSIVE." `CaseDetail.tsx:148-157` already renders a **rule-derived** caveat for every INCONCLUSIVE case. A per-case field would be strictly worse: a rule cannot drift from its verdict, 20 hand-written sentences can. The premise (that the Greenland prohibition bears hardest on non-significance) is sound; the conclusion did not follow, because it assumed per-case prose is the only way to discharge it | — | — | withdrawn |
| R1′ | **Replaces R1.** Author the **49 owed** caveats — 27 TRUE + 22 FALSE, from the builder's own published case lists — as curation, counted under a **new** name, never merged into `cases_with_what_*_does_not_prove` | case pages, census | The 49 cases the register already names as silent stop being silent, without redefining a published number | gap **[M]**; that prose helps **[I]** |
| R2 | **REINSTATED, corrected (§3.1b).** Delete "39 of the 91" from `report.py:107` and `test_report.py:396` — the true value under that file's own definition is **33 of 91 carry none / 58 carry one**, so the figure is wrong in value *and* inverted in direction. Delete the dead unscoped counter at `build_site_data.py:433` that computes 39. The rendered report already derives the number correctly and needs no change | audit report | One fewer wrong number, and one fewer definition of "caveat coverage" in the repo | **[M]**; the provenance link is **[I]** |
| R2a | Fix the verdict fall-through at `CaseDetail.tsx:140-142`: key the caveat lookup on the verdict instead of a two-way ternary, so a RECORDED case stops being told its record carries nothing when it carries 750 characters (§3.1a) | case pages | The site stops making a false statement about an artifact it is displaying | **[M]** |
| R3 | Split `lang="en"` into two marks — sealed-verbatim (may never be translated) and authored-untranslated — and gate that every authored payload string either has a zh sibling or is a **numbered, counted** gap | whole zh-TW edition, new gate | The Chinese reader can tell "English because sealed" from "English because unfinished"; ≥582 strings stop hiding behind a doctrine | **[I]**, on the site's own doctrine + O'Neill "accessible" **[C]** |
| R4 | Correct the verbatim banner to say what is actually on screen, including that some English is untranslated authored prose | zh-TW chrome | The banner stops making a claim the page contradicts | **[M]** for the contradiction; wording **[U]** |
| R5 | Translate the highest-load authored strings first: `architecture.json.status_labels.*`, `audit.json.boundaries[].claim`, the 5 denominator definitions | census, architecture, audit | The Chinese reader gets *"this study never examined this component"* and *"This platform never connects to your AWS account."* in Chinese | **[I]** |
| R6 | Re-encode INCONCLUSIVE so it does not read as no-data; keep the count-in-bar redundancy | census, DAGs | Encoding stops contradicting the adjacent sentence | contradiction **[M]**; specific palette **[U]** — no surviving source |
| R7 | Add an operational gloss in line beside each interval and each verdict label (not in a glossary) | case pages | Interval and label stop depending on the reader already knowing | negative form **[C]** (Hoekstra; IPCC 65-75%); that a gloss *helps* is **[I]** |
| R8 | Quote ASA Principle 4 verbatim beside the four denominators, and name it | census | The four-denominator display is visibly a professional-society requirement, not fastidiousness | **[C]** |
| R9 | Reorder the landing route: honest headline and "no pass rate" panel above the fold, "start here" → "How a verdict is made" promoted, denominator cards below with identifiers behind a disclosure | landing | Shallow entry precedes deep content | **[I]**, and see §5 for what may **not** be claimed about it |
| R10 | Answer "what must I check in my own service" (§7) via the scenario lens, as a checklist of cases with no score | new view | The reader's actual question gets an answer | **[I]/[U]** |
| R11 | Re-verify the Nature "Five rules" tips box against the Nature text before any of it reaches the screen | — | Removes this document's weakest evidential link | **[C]** caveat |
| R12 | Ship a favicon | all | One fewer console error | **[M]** |

---

## 5. REJECTED — recommendations that would make the site claim what the artifacts do not support

1. **Any pass rate, score, grade, or composite.** Rejected on project doctrine and independently by
   §1.1: a verdict mix is not reducible to a scalar without asserting that INCONCLUSIVE resolves one
   way. Note the ASA warrant for this was **killed** (0-3); the surviving warrant is Greenland/Amrhein.
2. **Copy claiming that showing uncertainty builds trust.** The measured effect is a **small
   decrease**, n = 5,780 (§1.5). The "may build trust" line is O'Neill's normative argument, not a
   measurement.
3. **Any citation of ACM `10.1145/3374218`**, in either direction — all five candidate claims were
   refuted. In particular it may not be cited to reject an error-hiding first layer, even though that
   layer is rejected here on doctrine.
4. **The "791 articles / 51%" statistic.** Refuted 0-3.
5. **Describing the TRUE/FALSE/INCONCLUSIVE/RECORDED taxonomy as standard.** No precedent was located
   across 26 primary sources; it must stay operationally defined on screen.
6. **"Absence can never be shown."** Lakens 2017 documents the equivalence-bounds/TOST route (§2). The
   correct on-screen statement is narrower: *this study declared no equivalence margin, so no verdict
   here demonstrates absence.*
7. **Claiming the new landing screen improves comprehension**, or citing reader approval of it as
   validation. Measured null on correctness; 80% preference with no benefit (§1.8).
8. **Calling confidence intervals "compatibility intervals"** as settled usage. Attribute it or leave
   it.
9. **Writing "uncorrelated"** for r = 0.04, 99% CI [-0.20, 0.27] — the exact collapse this site exists
   to forbid.
10. **Softening interval language into "no difference"** anywhere (§1.1), or hardening it into
    "refuted/excluded" outside the interval (§1.2). The site currently does neither.
11. **A plain-language layer that paraphrases sealed oracle text.** The research pass found **no**
    standards-body practice for a normative text plus explanatory companion, so there is no cited
    basis for a paraphrase layer; the gloss in R7 must sit *beside* the sealed quotation and be
    marked as ours.
12. **A per-case caveat field for INCONCLUSIVE** (withdrawn R1, §3.1). The rule-derived box is the
    stronger construction and must not be replaced by 20 hand-written sentences that can drift from
    their verdict.
13. **Merging authored caveats into `cases_with_what_*_does_not_prove`.** That number's published
    definition is *"the record carries no such statement"*. Adding curated prose to it would silently
    redefine a number the site has already published and would erase the distinction between what the
    study recorded and what the platform later wrote about it. Authored coverage is a **second claim**
    and gets a second name and a second derivation.
14. **Quoting any of "39 of 91", "42 of 91" or "49 of 91" as a caveat-coverage figure without naming
    its producer and its definition.** Three definitions exist (§3.1b) and only two are live. A bare
    fraction here is unreadable even when arithmetically right.

---

## 6. Rigour-audit checklist for the presentation layer — [I]/[U] throughout

No citation base survived for this section (§0). It is assembled from defects this project has
actually hit. For each: whether a gate can see it, or only a browser can.

| # | Failure mode | Mechanically detectable? |
|---|---|---|
| 1 | A container attribute governing a subtree is counted in the bundle bytes | **No — browser only.** One `lang="en"` in source is one occurrence however much of the page it governs; deleting the mark on `Markdown`'s root moves the count 160→159 while un-marking the whole site. Requires a text-node treewalker; already committed in `csp_preview.py` |
| 2 | Authored payload prose has no translation | **Yes.** Compare the payload's authored-string set to the zh dictionary; fail on any string with neither a translation nor a numbered exemption. Does not exist today (§3.2) |
| 3 | A colour token is present in the CSS and the rendered colour is still wrong | **No — browser only.** Read `getComputedStyle` at the leaf |
| 4 | A number lives in a justification string rather than in data | **Yes**, once hoisted into data. Unhoisted, it is unchecked prose |
| 5 | Two numbers where one was inferred from the other | **Yes**, by deriving each independently from its own producer |
| 6 | A label that does not match its computation | **Yes** — but only if the derivation is committed. §3.1b is exactly this, twice: a docstring asserting 39 where its own function derives 33, and my own scan publishing a field-occurrence count as a case count |
| 7 | A stale `dist/`, or a half-landed pass | **Yes.** Already armed (invariants 5 and 15) |
| 8 | Figure numbers drifting from the artifacts | **Yes.** `whitepaper_figures.py --check` rc |
| 9 | A required caveat missing for a verdict class | **Yes**, per-verdict field presence — and it already is, at `build_site_data.py:462-502`, which publishes the missing case lists. What no gate catches is the *component's* verdict fall-through (§3.1a): the census can be complete while the page still names the wrong field |
| 10 | Denominator conflation in copy | **Yes.** Already armed: bare `93/92/91/90/46/23/20` as string constants outside `denominators.json` fail the build |
| 11 | A verdict rendered in a colour whose convention contradicts its meaning | **No — human judgement.** No gate can know that grey means "disabled" |
| 12 | Reading order putting the hardest content first | **No — human, and best with a reader who is not the author** |
| 13 | A screenshot that looks like a defect but is a capture artifact | **Yes, and it must be** — measure `scrollWidth` vs `clientWidth` before filing (§3.5) |
| 14 | A guard whose scope excuses the place the next instance hides | **No.** The docstring saying where a guard need not look is the thing to re-read |
| 15 | Two producers computing the same-named quantity under different definitions | **Yes, but only by naming both.** The repo has three definitions of caveat coverage (§3.1b). A gate can assert each publishes its own definition beside its number; no gate can decide which one is meant |
| 16 | Dead code that computes a rival value for a published number | **Yes.** An unread accumulator is a lint finding; `build_site_data.py:433` is one, and its value is the wrong number that reached a docstring |
| 17 | A correction that is itself unverified | **No — process only.** Both of my §3.1 replacements were wrong before the third try. The only defence is to grep for the claim before withdrawing it, not after |

---

## 7. The reader's real question, and what remains open

The reader arrives asking **"what must I check in my own service"** and the site answers "here are 93
case verdicts". Answering it without inventing a score means: a checklist derived from the **FALSE and
INCONCLUSIVE** cases — the places the guidance did not hold or nothing was established — each item
linking to the case that licenses it, each carrying its citation restriction as data, and **no
aggregate**. The scenario lens (`platform/curation/scenarios.yaml`) is the planned vehicle; its
authored justifications remain the one skipped gate. **[I]/[U]** — no source was located for this
shape.

Open questions this pass could not close:

1. **What normative sources govern the bilingual encoding and colour decisions?** Nothing on WCAG 2.2,
   CVD-safe ordered palettes, or zh-TW typography survived. Until a second pass, every accessibility
   recommendation here is [I]/[U] and the contrast numbers in §3.3 are [M] only.
2. **Is there documented practice for gating a publish on "the UI cannot claim what the artifacts do
   not support"?** None located. Our gate may be novel or the search may have missed the field; both
   readings are open.
3. **Did any sealed oracle declare an equivalence margin (SESOI) in advance?** If yes, some
   INCONCLUSIVE cases may be *under*-claiming. If no, the site must never phrase any verdict as
   demonstrating absence. This is answerable from `PREREGISTRATION.yaml` and has not been checked.
4. **Has the presentation ever been tested with a reader?** van der Bles et al. instruct exactly that,
   and the trust evidence is UK/US general public on climate and immigration — a frame that excludes
   both today's single expert reader and tomorrow's B2B/B2C security engineers.

---

## 8. Reproduction

```bash
# The recursive scan that used to sit here is DELETED, not corrected. It matched
# `'does_not_prove' in k` at any depth, so it credited a FALSE case for carrying the TRUE caveat and
# measured a property no reader can see. Read each producer's own published derivation instead.

# (§3.1) site payload — TRUE/FALSE-scoped, one field per verdict, with the missing case lists
python3 -c "
import json
c=json.load(open('site/dist/data/method.json'))['caveats']
print('TRUE  carry', c['cases_with_what_true_does_not_prove'], 'of', c['true_verdicts'],
      '| missing', len(c['true_verdicts_without_the_caveat']))
print('FALSE carry', c['cases_with_what_false_does_not_prove'], 'of', c['false_verdicts'],
      '| missing', len(c['false_verdicts_without_the_caveat']))"

# (§3.1b) audit report — 9 caveat field names, all 91 cases. This is a DIFFERENT definition, and the
# two numbers are two claims: do not infer either from the other.
python3 -c "
import sys; sys.path.insert(0,'platform/audit')
import report as R
c=R.read_case_caveats()
print('carry one', sum(1 for v in c.values() if v['present']), '| carry none',
      sum(1 for v in c.values() if not v['present']), '| of', len(c))"

# interval-boundary language audit (§1.2)
cd site/dist/data && grep -ric 'refuted\|excluded by the data\|ruled out' *.json cases/*.json

# rendered-DOM verbatim-mark probe (§3.2) — run under platform/build/csp_preview.py, zh-TW locale
```

Research provenance: workflow `wf_0cce59f1-553`; per-agent transcripts and one `{"type":"result"}`
line per agent in
`~/.claude/projects/-Users-tmwu-Downloads/fd230f67-029c-480f-a070-54c1670fc4e4/subagents/workflows/wf_0cce59f1-553/journal.jsonl`.
