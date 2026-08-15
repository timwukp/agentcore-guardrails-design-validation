# Research pass 2 — how peer-reviewed venues present validated claims

Run `wf_3762680e-846` (`wskk4k3up`), 2026-08-15. 108 agents, 5 angles, 26 primary sources fetched,
**129 claims extracted, 25 verified by 3-vote adversarial panels, 23 survived, 2 killed**, 14 after
synthesis. This file records what the pass established, what it *failed* to establish, and — the part
that matters most for the next step — the difference between the two.

Companion to `RESEARCH-whitepaper-conventions-20260815.md` (pass 1, AWS document conventions and
threat-model cross-map). Pass 2 was scoped to deliberately exclude both of those topics.

---

## 0. The negative result, stated first — and corrected

The pass reported its own biggest caveat as: *only sub-question (1), presentation conventions, is
actually evidenced; sub-questions (2) statistics/visualization and (3) published criticism of
guardrail evaluation produced zero surviving claims.*

**That framing is too pessimistic, and the distinction is load-bearing.** The run's own statistics
say `sourcesFetched: 26`, `claimsExtracted: 129`, `claimsVerified: 25`. Only **25 of 129 extracted
claims ever entered verification** — the other 104 were never adjudicated. The sources for angles (2)
and (3) *were* located and fetched; their claims simply never reached a verification panel. So:

| status | meaning | what to do |
|:---|:---|:---|
| **Verified** (23 claims, §1–§3 below) | 3-vote panel, ≥2 must refute to kill | citable now, with the retrieval caveats in §4 |
| **Located but unverified** (§5) | primary source identified and fetched, claim never adjudicated | **scoped verification pass over 8 named URLs** — not a fresh search |
| **Absent** (§6) | no source found at all | genuinely open |

Writing §5 up as "unresearched" would waste eight identified primary sources; writing it up as
"researched" would publish unverified claims in a paper about verification. It is neither.

---

## 1. Artifact badging — the vocabulary, and why we can claim none of it

### 1.1 ACM: five badges in three independent families [verified 3-0]

`acm.org/publications/policies/artifact-review-and-badging-current`, policy **v1.1 dated
2020-08-24**. Verbatim: *"We recommend that three separate badges related to artifact review be
associated with research articles in ACM publications: Artifacts Evaluated, Artifacts Available and
Results Validated. These badges are considered independent and any one, two or all three can be
applied to any given paper"*.

The five exact names: **Artifacts Evaluated – Functional v1.1**, **Artifacts Evaluated – Reusable
v1.1**, **Artifacts Available v1.1**, **Results Reproduced v1.1**, **Results Replicated v1.1**.
Under Artifacts Evaluated, *"Two levels are distinguished, only one of which should be applied in any
instance"* — that exclusivity clause is **absent** from Results Validated.

Functional's criteria are four enumerated terms plus a V&V clause: artifacts must be *"documented,
consistent, complete, exercisable, and include appropriate evidence of verification and validation"*.
*Documented* = *"At minimum, an inventory of artifacts is included, and sufficient description
provided to enable the artifacts to be exercised"*. *Complete* permits omitting proprietary
artifacts.

### 1.2 The finding that constrains our own claims [verified 3-0]

**Reproduced** = main results obtained *"in a subsequent study by a person or team other than the
authors, using, in part, artifacts provided by the author"*. **Replicated** = the same *"without the
use of author-supplied artifacts"*. The family preamble forecloses author self-runs outright:
*"This badge is applied to papers in which the main results of the paper have been successfully
obtained by a person or team other than the author."*

An author re-running their own harness is, in ACM's VIM-derived terminology, only **Repeatability
(same team, same experimental setup)** — *"a researcher can reliably repeat her own computation"* —
a terminology category with **no corresponding badge**.

> **This applies directly to us and must be written into the paper.** `PREREGISTRATION.yaml`'s
> `reproduction_before_amendment` gate is satisfied by a second-calendar-day run of *our own* harness
> by *us*. In ACM's vocabulary that is **repeatability, not reproduction and not replication** — and
> the rule's own name therefore overstates what it delivers. The gate is still worth having: it
> catches instrument nondeterminism and vendor drift between days, which is exactly what it caught in
> F3-10 (DEV-P4-35, the publish-lag bug that a single day passed with zero slack). But the paper may
> not present a two-day self-run as third-party reproduction, and should say in one sentence that no
> independent party has re-run anything here.

Also verbatim, including ACM's own typo: *"In each cases, exact replication or reproduction of
results is not required, or even expected. Instead, the results must be in agreement within a
tolerance appropriate for the type of experiment"* — and differences *"should not"* change the main
claims. **Not "must not"** — do not tighten the quote.

### 1.3 USENIX Security: three badges, cumulative in practice [verified 3-0]

`secartifacts.github.io/usenixsec2025/{badges,instructions}`. *"The artifact evaluation program
recognizes three distinct badges"*: **Artifacts Available**, **Artifacts Functional**, **Results
Reproduced**. Available is **mandatory** Phase-1 under the venue's Open-Science policy — *"Phase-1 AE
is mandatory for all papers that get accepted"* and non-compliant papers *"will have their acceptance
rescinded"*; Functional and Reproduced are optional Phase-2. Available *"does not mandate any further
requirements on functionality, correctness, or documentation"*.

Measured nesting across 394 badged papers: 394 Available, 204 Functional, 150 Reproduced; observed
combinations Available-only 190, Available+Functional 54, all three 150, and **zero papers held
Reproduced without Functional**.

Functional is judged on three named dimensions — **Documentation, Completeness, Exercisability** —
against the criterion that artifacts *"conform to the expectations set by the paper in terms of
functionality, usability, and relevance"*. Reproduced asks *"could the AEC independently repeat the
experiments and obtain results that support the main claims made by the paper?"*, explicitly *"not to
reproduce the results exactly but instead to generate results independently within an allowed
tolerance such that the main claims of the paper are validated"*.

**Two vocabularies, never blended.** ACM's five names and USENIX's three are different registers.
USENIX's own site is internally inconsistent: its badge alt text reads ACM-style *"Artifacts
Evaluated - Functional (v1.1)"*, its instructions prose says *"Results Reproducible"*, while the
LaTeX option and badges page say *"Results Reproduced"*. Cite the badges page and the
`usenixbadges` LaTeX options (`available`, `functional`, `reproduced` — no fourth option).

### 1.4 Archival hosting — a 2025 policy change, not a property of the badge [verified 2-1]

USENIX Security **2025 and 2026**: *"we recommend Zenodo, but other valid hosting options include
institutional and third-party digital repositories (e.g., FigShare, Dryad, or Software Heritage).
Unlike previous iterations, software development repositories such as GitHub, GitLab, or personal web
pages are not acceptable for this badge."*

**2024 said the opposite** — GitHub/GitLab were explicitly allowed with *"a stable reference to the
evaluated version (e.g., a URL pointing to a commit hash or tag)"*. ACM's policy names only personal
web pages as unacceptable. The 2-1 vote reflects scope, not quote accuracy.

> **Applies to us.** This project's evidence lives in a GitHub repository pinned by commit. Under
> USENIX 2024 rules that is acceptable with a commit hash; under 2025/2026 rules it is not, and a
> DOI-bearing archival deposit would be required. Worth one sentence in the paper and one line in
> future work — it is a cheap gap to close (Zenodo deposit of the tagged tree) and an expensive one
> to be caught on.

### 1.5 The Artifact Appendix — a directly adoptable structure [verified 3-0]

*"The artifact appendix is a self-contained document that describes a roadmap for evaluators. This
includes a description of the hardware, software, and configuration requirements, as well as the
major claims made by the paper and how to reproduce each claim through your artifact. Linking the
claims of the paper to the artifact is a necessary step that ultimately allows artifact evaluators to
reproduce your results. It is of foremost importance that you state your paper's key results and
claims clearly."*

Mandatory for Functional/Reproduced. Its own bolded line: *"Artifact Appendices are recommended to be
at most 3 pages."* The official template fixes the skeleton with `[Mandatory]` tags — Abstract;
Description & Requirements; Set-up; Evaluation workflow — and cross-references each major claim
**C1, C2 …** to the specific experiment **E1, E2 …** that establishes it.

> **Adopt this.** Our `claims/triage.csv` → case-id → `results/phase1/*.json` chain already *is* a
> C↔E mapping; it has simply never been presented in that form. The whitepaper's evidence appendix
> should be a C↔E table, and the 3-page recommendation is a useful discipline against our tendency to
> write appendices longer than the body.

---

## 2. Sealing a design before data — and how much credit it earns

### 2.1 Registered Reports [verified 3-0]

`cos.io/initiatives/registered-reports`. *"peer review prior to data collection"*. Stage 1 = *"an
Introduction, Methods, and the results of any pilot experiments that motivate the research proposal"*
with *"a step-by-step account of the experimental procedures and analysis plan"*. Survivors receive
in-principle acceptance *"that will not be revoked based on the outcomes, but only on failings of
quality assurance, following through on the registered protocol, or unresolvable problems in
reporting clarity or style"*. Stage 2 *"cannot be rejected because editors or reviewers find the
outcomes of hypothesis testing to be surprising, counterintuitive, or unappealing"*.

Wording caveat: COS says IPA *"virtually guarantees"* publication. **Do not write "guarantees".**

### 2.2 Machine learning's precedent is a defunct workshop pilot [verified 2-1, 2-1, 3-0]

`preregister.science` — ICCV 2019, NeurIPS 2020, NeurIPS 2021; **the series ended December 2021 and
was non-archival**. *"The emphasis of peer-review will be on whether the experiment plan can
adequately prove or disprove one (or more) hypotheses. Some results will be negative, and this is
welcomed."* Stage 1 *"must only contain a description of experiments and protocol, and what
conclusions can be drawn in different cases, without the results themselves"*. Peer-reviewed
corroboration in the PMLR v148 preface (Bertinetto et al. 2021).

**Killed 0-3:** the claim that Stage-2 review checks *execution fidelity rather than result quality*.
Do not assert it.

### 2.3 Pre-registration is a rigor upgrade, not a baseline [verified 3-0]

From the ACM SIGSOFT Empirical Standards repo (`git clone`, master last touched 2026-04-28):

- `Experiments.md` **L75, Desirable** (not Essential): *"pre-registration of hypotheses and design
  (where venue allows)"*. The 18-item Essential list L25-62 contains **no** advance-sealing item.
- `CaseStudy.md` **L85, Extraordinary**: *"published a case study protocol beforehand and made it
  publicly accessible"*.
- `GeneralStandard.md` Desirable: *"publishes the study in two phases: a plan and the results of
  executing the plan"*.
- **Eight** other method standards — Engineering Research, Benchmarking, Data Science, Optimization
  Studies, Repository Mining, Questionnaire Surveys, Replication, Quantitative Simulation — mention
  registration **zero** times.

Tier semantics from the project's own `FAQ.md`: *"All papers that meet the essential criteria are
publishable"*; *"The standards allow a rough ranking of papers based on their number of desirable and
extraordinary attributes"*.

> **This is our strongest honest claim about method, and it must be phrased as a comparison rather
> than a boast:** this study sealed its oracles, decision rules and exclusion rules by sha256 before
> any data existed, which in software-engineering venue terms is a *Desirable* attribute for
> experiments and is not required at all by the standard that actually governs benchmarking work.
> Pair it immediately with §1.2 — sealed design, self-run replication.

---

## 3. Reporting: negative results, validity, effect sizes

### 3.1 Negative results are protected — directionally [verified 3-0]

`GeneralStandard.md` **L152 "## Invalid Criticisms"**, L163 verbatim: *"Rejecting a study because it
reports negative results."* Siblings are of identical reviewer-directed form: *"Rejecting a study
because it replicates or reproduces existing work."*, *"Rejecting a study because the reviewer would
have used a different methodology or design."*, *"Setting arbitrary minimum sample sizes … based on
neither power analysis nor theoretical saturation."*

**Three things not to say.** The Standards *list* this as an invalid criticism — they do not
"forbid" it and carry no sanction (the companion `ReviewerMisconduct.md` is still marked **DRAFT**).
They are ACM SIGSOFT **community documents voluntarily adopted**, not any venue's review policy. And
protection is directional: the same corpus still names *"Unreasonably small, underpowered or limited
studies"* as an antipattern, so an underpowered null remains fairly criticizable.

> Relevant to us twice over: 23 FALSE verdicts and 20 INCONCLUSIVE are the bulk of this study's
> value, and F5-6's `recall 0 [0, 0.031]` at n=120 is precisely an "is it underpowered?" target.

### 3.2 The four-part validity structure — and the trap in citing it [verified 3-0]

`Experiments.md` **L56, Essential**: *"discusses construct, conclusion, internal, and external
validity"*. `L108` antipattern: *"validity threats are simply listed without linking them to
results"*. `L73`, separately **Desirable**: *"analyzes construct validity of dependent variable"*.
General Quality Criteria repeats *"Conclusion validity, construct validity, internal validity"*,
matching the Cook-Campbell / Wohlin-Runeson lineage.

**The trap, and the single most likely reviewer objection to our write-up:** that Essential lives in
the **Experiments (with Human Participants)** standard, whose Application section scopes it to
studies that *"involve human participants"* and explicitly redirects work without them elsewhere.
**`Benchmarking.md` requires only construct validity**, and **Engineering Research contains no
validity attribute at all**. Neither Engineering Research nor Benchmarking contains any effect-size,
CI, or pre-registration attribute.

A hosted-guardrail latency-and-efficacy study is a **Benchmarking / Data Science** study.

> **Therefore:** write all four validity sections — they are the right content and the antipattern
> against unlinked threat lists is exactly the failure our dispersed per-case prose currently has —
> but attribute them to the Cook-Campbell/Wohlin lineage and state that the standard binding on
> benchmarking work requires only **construct** validity, so the other three are voluntary. Claiming
> the four-part Essential as binding on us is a citation error a reviewer will find.

### 3.3 Effect sizes with intervals; no single-number summaries [verified 3-0]

- `Experiments.md` L52, **Essential** (quoted with the source's own typo): *"reports effects sizes
  with confidence intervals (if using frequentist approach)"*.
- `DataScience.md` L42, **Essential**: *"goes beyond single-dimensional summaries of performance
  (e.g., average; median) to include measures of variation, confidence, or other distributional
  information"*.
- Antipatterns: `DataScience.md` L87 *"Significance tests without effect size tests; effect sizes
  without confidence intervals"*; L88 *"Reporting a median, without any indication of variance (e.g.,
  a boxplot)"*; `OptimizationStudies.md` L91 the same against Mann-Whitney-Wilcoxon.
- The **Information Visualization Supplement** maps the Distribution intent to *"Histogram, Frequency
  polygon, Cumulative density, Quantile-quantile plot, Boxplot, Violin plot"* and names *"using
  truncated bars to exaggerate differences"* as an antipattern.

> **This is the entire citable basis for our figure conventions** — enough to justify a CDF or
> quantile plot over a bar-of-means and to cite a named truncated-axis antipattern, and **nothing
> more**. It does not cover censoring, binomial-interval choice at zero successes, or three-state
> matrix encoding. See §5.
>
> Our own reporting already satisfies L42 and L87 in places — the Hodges-Lehmann shift with 95% CI
> [30.2, 57.0] in Appendix B is exactly an effect size with an interval — and violates the spirit of
> L88 wherever a p50 appears without a spread.

### 3.4 Presentation is a methodological phase [verified 3-0]

Wohlin et al., *Experimentation in Software Engineering* (2012), decomposes the experiment process
into five separately DOI-registered phase chapters: **Scoping** 85-88, **Planning** 89-116,
**Operation** 117-122, **Analysis and Interpretation** 123-151, **Presentation and Package** 153-157.
Edition-stable — the 2nd edition (2024) keeps the identical five names.

Two limits: Springer blocks unauthenticated fetches (**303 to the identity provider**), so the page
ranges are verified from Crossref/OpenAlex metadata only, and the placement of the validity taxonomy
inside Chapter 8 (Planning) rests on background knowledge, **not a fetched page**. One panel member
recorded exactly that as a refutation of quotability. **Cite the book for its chapter structure; do
not quote its prose.**

---

## 4. Retrieval caveats that must ride any citation

- **acm.org returns HTTP 403 to automated fetchers.** All ACM badge text here was read from Wayback
  captures (newest 200-status snapshot **2026-07-03**) or a text proxy. Two independent captures
  rendered identical text, so corruption is ruled out, but the citation should name the retrieval
  route.
- **Springer blocks the Wohlin book** (303 → `idp.springer.com`); metadata-only verification.
- Adversarial search coverage was **partial** for three claims (DuckDuckGo CAPTCHAs, Google Books
  429), so "no contradicting source found" is weaker than it sounds for §1.4, §3.2 and §3.4.
- **ACM v1.1 swapped the meanings of reproducibility and replicability versus v1.0**, per its own
  footnote. Pre-2020 badge semantics differ; never cite a pre-2020 usage as equivalent.

---

## 5. Located but unverified — the scoped pass this owes

These eight primary sources were fetched by the run's statistics/visualization and
guardrail-critique angles. **Their claims never reached a verification panel.** They are named here so
the next pass is a verification of known sources rather than a fresh search, and so that nothing from
them is cited until it is adjudicated.

| topic | source located |
|:---|:---|
| Benchmarking methodology, latency reporting | Hoefler & Belli, *Scientific Benchmarking of Parallel Computing Systems* — `htor.inf.ethz.ch/publications/img/hoefler-scientific-benchmarking.pdf` |
| Binomial interval choice (Wilson / Clopper-Pearson / why Wald fails at 0) | Brown, Cai & DasGupta, *Interval Estimation for a Binomial Proportion*, Statistical Science 16(2) |
| Rule-of-three upper bound for zero events | `bmj.com/content/311/7003/485`; `pmc.ncbi.nlm.nih.gov/articles/PMC2550668/` |
| Figure-design canon | Rougier, Droettboom & Bourne, *Ten Simple Rules for Better Figures*, PLOS Comp Biol `10.1371/journal.pcbi.1003833` |
| Figure guidance / reporting | PLOS Biology `10.1371/journal.pbio.1002128` |
| Colour-blind-safe encoding | Okabe & Ito, `jfly.uni-koeln.de/color/`; W3C **WCAG 2.2 Use of Color** `w3.org/WAI/WCAG22/Understanding/use-of-color.html` |
| Vendor model drift over time | *How is ChatGPT's behavior changing over time?* — `arxiv.org/abs/2307.09009` |
| Guardrail / jailbreak evaluation critique | `arxiv.org/abs/2506.10597`, `2503.05336`, `2407.21792`, `2406.11668`, `2411.03336` |

Two of these bear on claims the paper already needs to make. **WCAG 2.2 Use of Color** would give the
three-state control matrix a standards citation instead of authorial judgment — colour must not be the
only means of conveying information, which is exactly why INCONCLUSIVE needs hatching and not just a
third hue. And **arXiv 2307.09009** would give the vendor-drift limitation an external citation
instead of resting only on our own `AWS-BEHAVIOR-CHANGES.md`.

---

## 6. Genuinely absent — open questions

1. **No citable precedent was found for a three-state verdict taxonomy** (confirmed / refuted /
   inconclusive-indeterminate) with an explicit statement that inconclusive is not refuted. The
   nearest verified material — ACM's tolerance standard and Registered Reports' outcome-independence
   — supports publishing a null but says nothing about a distinct indeterminate state. **Our
   TRUE/FALSE/INCONCLUSIVE/RECORDED scheme is therefore our own construction and must be presented as
   such**, defined operationally in the methods chapter rather than cited. Candidate places to look
   next: NIST/ISO conformance-testing vocabulary, where "inconclusive" is a standard verdict.
2. **Which standard actually governs a hosted-service security-control validation study?** Verified
   evidence shows the SIGSOFT four-part Essential is human-participant-scoped, Benchmarking requires
   only construct validity, Engineering Research requires none. Nothing establishes what a
   hosted-moving-target study owes.
3. **Do any computer-security venues operate registered reports or any ex-ante protocol-sealing
   track?** Verified evidence covers COS/300+ journals and a defunct ML workshop only. Whether IEEE
   S&P, USENIX Security, NDSS, CCS or SOUPS has such a track is unknown, and it matters because it
   determines whether our pre-registration has a peer in our own field.
4. **What is the strongest honest badge-equivalent claim for a self-executed re-run?** ACM's
   vocabulary permits only *Repeatability*, which has no badge, while Artifacts Available and
   Artifacts Evaluated remain earnable on their own terms. The paper needs one precise sentence here.

---

## 7. What changes in `WHITEPAPER-DESIGN.md` because of this pass

1. **Chapter 12 (threats to validity)** — unblocked. Write all four parts; attribute to
   Cook-Campbell/Wohlin, **not** to a SIGSOFT Essential that does not bind benchmarking work; obey
   the L108 antipattern by linking every threat to a specific result.
2. **A new subsection in the methods chapter** — `reproduction_before_amendment` delivers
   **repeatability**, not reproduction. One sentence, stated plainly, plus the note that no
   independent party has re-run anything.
3. **The evidence appendix becomes a C↔E table** on the USENIX artifact-appendix pattern, with the
   3-page discipline as a target for the roadmap portion.
4. **Appendix D (figure conventions)** — still **not** sourced. Downgrade it from "written from pass
   2" to "authorial judgment, with two citable anchors" (§3.3's Distribution mapping and truncated-bar
   antipattern) and a named dependency on the §5 verification pass.
5. **A new future-work item** — archival deposit with a DOI, because a GitHub commit no longer
   satisfies USENIX's Artifacts Available as of 2025.
6. **The verdict taxonomy is ours** — define it, do not cite it.
