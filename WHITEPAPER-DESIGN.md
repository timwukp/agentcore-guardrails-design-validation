# Whitepaper design — structure, evidence conventions, and figures

**Status (updated 2026-08-15, after pass 2 landed):** design approved for drafting throughout.
**Chapter 12 is unblocked**; **Appendix D is not**, and its blocker changed shape — pass
`wf_3762680e-846` returned only two citable figure anchors and left censoring, binomial intervals at
zero successes, and three-state encoding unsourced. Appendix D now waits on a **scoped verification
pass over eight already-located URLs** (`results/RESEARCH-evidence-presentation-20260815.md` §5), which
is a verification, not a search. Nothing else depends on it.

**Three amendments pass 2 forces on this design, before drafting starts:**

1. **§2 Part IV chapter 12** — write all four validity parts, but attribute them to the
   Cook-Campbell / Wohlin-Runeson lineage, **not** to a SIGSOFT Essential. That Essential is scoped to
   human-participant experiments; `Benchmarking.md` requires only **construct** validity. See
   `RESEARCH-evidence-presentation-20260815.md` §3.2.
2. **A new methods subsection — `reproduction_before_amendment` delivers repeatability, not
   reproduction.** ACM's vocabulary reserves *Reproduced* and *Replicated* for non-authors; a
   self-executed second-day run is **Repeatability (same team, same setup)**, which has no badge. One
   sentence saying so, one sentence on what a second day does buy (it caught DEV-P4-35), and one
   sentence stating that no independent party has re-run anything here. §1.2 there; FUTURE-WORK item 19.
3. **The evidence appendix becomes a C↔E table** on the USENIX artifact-appendix pattern — each major
   claim **C1, C2 …** cross-referenced to the experiment **E1, E2 …** that establishes it, because
   *"Linking the claims of the paper to the artifact is a necessary step"*. Our
   `claims/triage.csv` → case-id → `results/phase1/*.json` chain already is that mapping and has simply
   never been presented in that form. Their bolded 3-page recommendation is a useful discipline. §1.5.

And one thing the paper must **stop** implying: the `TRUE / FALSE / INCONCLUSIVE / RECORDED` taxonomy
has **no located precedent** — pass 2 searched for one across 26 primary sources and found none. Define
it operationally in the methods chapter; do not cite it. FUTURE-WORK item 20.

**Provenance tags used throughout.** Every structural decision below carries one:

- **[C]** — CONFIRMED by adversarial research against a primary source. Cite it.
- **[I]** — INFERENCE. Defensible, but ours. The paper must label it as inference, not attribute it.
- **[U]** — UNSOURCED authorial judgment. Do not dress it as a standard. Pass 2 has now landed, so a
  remaining **[U]** means *nothing verified supports this*, not *not yet looked at* — except in
  Appendix D, where the eight sources of §5 are located but unadjudicated.

Research basis: `results/RESEARCH-whitepaper-conventions-20260815.md` (pass 1 — AWS document
conventions, threat-model cross-map) and `results/RESEARCH-evidence-presentation-20260815.md`
(pass 2 — artifact badging, pre-registration, validity structure, negative results, effect sizes).
Evidence basis: `census.py` (regenerate, never quote) and `claims/triage.csv`.

---

## 0. The two decisions that shape everything else

**Decision 1 — this is a new artifact with a dated envelope, not v1.5.** [C]
AWS whitepapers do not carry MAJOR.MINOR.PATCH. They carry a publication-date stamp and an
appended `Change | Description | Date` revisions table. `agentcore_guardrails_best_practices_v1.x`
stays as the *internal design document under test* — it is what `PREREGISTRATION.yaml` seals and
what the 546 triaged claims quote. The whitepaper is a **derived publication** with its own dated
revision log. Conflating them would put the sealed document under test into the same version line
as the report about it.

**Decision 2 — two tiers of claim, and the tier decides the verb.** [C, from OWASP LLM01 + NIST
AI RMF MANAGE 1.4]

| Tier | Controls | Permitted verb | Required companion |
|---|---|---|---|
| Deterministic | IAM deny, egress deny, Cedar authorization, resource policy, SCP | *prevents* — scoped to a stated threat model | the scope statement itself |
| Probabilistic | guardrail content filters, PII detection, prompt-attack detection | *reduces / detects*, with measured efficacy | **residual risk statement** |

This is not stylistic. `v1.4.md:850` currently says Tool I/O Guardrails "**Prevent** data leakage
and indirect prompt injection from tool outputs" and `:368` says "**Prevents** sensitive data
leakage through tool interactions", while the document's own line 199 correctly records that
untagged InvokeModel input is not scanned at all (F5-6: recall **0 [0, 0.031]**, n=120). Those two
lines contradict line 199. `grep -ic 'residual risk'` over the file returns **0**. Fixing this is
item 1 of `FUTURE-WORK.md`.

---

## 1. Front matter

Order and content, all **[C]** except where marked.

1. **Title + publication date stamp.** No semantic version.
2. **Abstract.** One paragraph: what was measured, on what, and the headline that 91 of 92
   verdict-eligible propositions in a production AgentCore guardrails design document were decided
   against pre-registered oracles.
3. **Intended audience, by role.** Security architects owning the AgentCore control plane;
   platform engineers owning execution roles and gateways; risk/compliance readers who need to know
   what is *not* established. Currently absent — `grep -ic 'Intended audience'` = 0.
4. **Scope and non-goals.** One region (us-east-1), one account, one document under test, dated
   service behavior. Non-goals stated explicitly so a reader cannot over-read the paper.
5. **Shared responsibility for AgentCore guardrails.** Security **of** the cloud vs **in** the
   cloud, with AWS's primary scoping factor stated first — "your responsibility is determined by
   the AWS service that you use" — then data sensitivity, company requirements, applicable laws.
   Positioned **before any control discussion**, matching both the AgentCore Developer Guide's own
   security page and the Security Pillar's front matter. Currently absent (`grep` = 0). **Caveat to
   write into the section itself:** this framing is service-agnostic boilerplate; it buys structural
   conformance and zero AgentCore-specific content, so keep it short.
6. **How to read the evidence in this paper.** The load-bearing section, and the one that
   distinguishes this from every prescriptive guardrails document in the market:
   - the verdict taxonomy actually in use — **TRUE / FALSE / INCONCLUSIVE / RECORDED / NOT
     MEASURED** — with the rule stated in the document already: *an INCONCLUSIVE verdict is not
     evidence against a claim*;
   - the **pre-registration** posture: oracles sealed by sha256 in `lib/oracle.py` before any data
     arrived, register sealed at `claims/triage.csv`;
   - the **two-calendar-day reproduction gate** before any amendment;
   - the two-tier claim policy from §0 Decision 2;
   - the marker vocabulary readers will meet inline (`[verified …]`, `[corrected per …]`,
     `(test pending …)`, `(measured — amendment deferred …)`).

---

## 2. Body

### Part I — What is actually enforced, and where

**Chapter 1. The enforcement surfaces of an AgentCore deployment.** [I]
Not a product tour: an enumeration of the places a request can be stopped, each with the measured
evidence that it does or does not stop things — gateway policy engine, `ApplyGuardrail`, Cedar
authorization, IAM execution role, network egress, and the observability surfaces that report on
them. The organizing insight is already measured and worth leading with: **the surfaces a document
names are not the surfaces a service has** (DEV-P4-27 — three surveyed surfaces published no
numeric guardrail score; the gateway's own application logs did, at
`body.policy.guardrailFindings.<policyId>.contentFilter[].score`, and the logged per-arm sums equal
the `ConfidenceScore` metric sums exactly: 24.6/24.6, 0.8/0.8, 24.2/24.2).

**Chapter 2. Threat model and framework cross-map.** [C for the frameworks, I for the mapping]
The coverage matrix, and the chapter that makes the paper legible to an external reviewer:

- **OWASP LLM Top 10 2025** — LLM01 Prompt Injection, LLM06 Excessive Agency (cite the
  `llmrisk/llm06…` risk page, and flag that the 2023-24 edition numbered it LLM08).
- **OWASP Agentic AI Threats and Mitigations v1.1, December 2025** — map **by TID only**, T1–T17,
  pinned by sha256 `65e3bd59f99c…0345ff`, because OWASP's own 2026 document renames T4/T6/T12.
- **AWS Well-Architected GenAI Lens** — GENSEC01–GENSEC06, in particular **GENSEC02-BP01**
  (guardrails) and **GENSEC05-BP01** (least privilege and permissions boundaries for agentic
  workflows).

Three things this chapter must say out loud, or it becomes the paper's weakest link:

1. **"Satisfies OWASP agentic mitigations" is forbidden.** The referent standard publishes zero
   measurements — no `benchmark`, `efficacy`, `confidence interval`, `experiment` or `latency`
   anywhere in v1.1 (verified under three PDF extractors and a whitespace-stripped substring pass).
   Conformance to an unmeasured prescriptive standard is an assertion. This is also the paper's
   strongest claim to contribution: **the standards prescribe, we measured.**
2. **The GENSEC map is extrapolation.** `gensec05-bp01.html` names Bedrock **Agents and Flows**
   only; the Lens `agentic-ai.html` never mentions Bedrock AgentCore. Label it inference. There is
   no AgentCore equivalent of Bedrock Agents' `confirmationState` user confirmation.
3. **Conversational-path coverage is not the whole story**, and OWASP says so: T9 — a *compromised*
   persistent agent identity yields "privileged, long-term API access that bypasses the agent's
   conversational interface and its guardrails"; T16 — loose MCP/A2A spec enforcement lets attackers
   "bypass guardrails entirely". Phrase T9 conditionally (it presupposes credential theft), and
   label the AgentCore application as ours.

### Part II — The controls, as numbered best practices

**Chapter 3–8**, one per control question. **[C] for the ID scheme, [I] for our specific questions.**

The ID scheme is the one structural thing about AWS convention that is machine-verifiable, so use
it: **question → numbered best practice**, dotted, stable, and cross-mapped. Proposed namespace
**`ACG-nn-BPnn`** (AgentCore Guardrails), *not* `GENSEC…`, precisely because GENSEC does not cover
AgentCore and borrowing the prefix would imply AWS authorship. Every control carries a header row:

```
ACG-04-BP02  Deny the enforcement-mode flip at the policy boundary, not the alarm
  Parent question  ACG-04 How do you protect the enforcement configuration itself?
  Cross-map        GENSEC02-BP01 (Well-Architected GenAI Lens, rev. 2025-11-19) | OWASP LLM06 | T3
  Tier             deterministic (SCP / permission boundary / resource policy)
  Risk if absent   High
  Evidence         F5-2 TRUE, n=120, us-east-1, replicated 2026-08-12 and 2026-08-13
  Residual risk    detection-only configurations: mode flip accepted in 602.8 / 931.7 ms, a
                   previously blocked request served 13.2-14.2 s later (both days)
  Not established  no CloudTrail detection latency was measured — attack side only
```

The `Not established` line is mandatory on every control. It is where the per-item "What the TRUE
verdict does not prove" prose that already exists in v1.4 becomes structured instead of dispersed.

**Do not claim this layout is "the AWS best-practice template."** Four separate claims that AWS has
a fixed prose template were refuted 0-3, and the risk-level callout survived only 1-2. The
defensible sentence is that *several* AWS best-practice pages include a risk-level line,
implementation guidance, numbered steps and typed resource lists — an observed pattern, cited
per page.

**Chapter ordering by evidence strength, not by narrative.** [I] Derived from
`claims/triage.csv` × `results/phase1/`:

| Document section | Claims | Verdict mix (claim × case) | Use in the whitepaper |
|---|---|---|---|
| s4-4 | 37 | TRUE 51, INCONCLUSIVE 8, RECORDED 2 | flagship chapter |
| s10 | 25 | TRUE 24 | flagship chapter |
| s3-4 | 21 | TRUE 30, FALSE 7, INCONCLUSIVE 5 | strong |
| s4-1 | 30 | TRUE 30, FALSE 6, INCONCLUSIVE 5, RECORDED 2 | strong |
| s6-3 | 15 | TRUE 14 | strong, narrow |
| s4-3 | 12 | TRUE 17 | strong, narrow |
| s7-1 | 22 | FALSE 13, TRUE 7, INCONCLUSIVE 1 | corrections chapter |
| s9 | 29 | FALSE 7, TRUE 4, INCONCLUSIVE 1 | corrections chapter |
| **s5-1** | **27** | **INCONCLUSIVE 17, FALSE 6, TRUE 5** | **must be labelled weakly evidenced** |
| **s4-5-5** | **16** | **INCONCLUSIVE 14, TRUE 1** | **must be labelled weakly evidenced** |

s5-1 and s4-5-5 are the honest weak spots. A whitepaper that presents them at the same confidence
as s4-4 and s10 is misleading by omission, and a reviewer comparing the appendix register against
the body would find it.

### Part III — Operating it

**Chapter 9. Observability and detection.** What is actually visible, including the two measured
traps: requests below the configured threshold publish **no score at all** (61 of 122, and all 61
that did publish were positives — so a closed calibration window can *raise* a threshold, never
lower it); and **LOG_ONLY is quiet on the metrics and loud in the logs** — all 30 shadow
evaluations wrote `decision: DENY` / `effect: FORBID` / `isError: true` / `severityText: ERROR`,
the same four fields real denials wrote, with `policyMode` reading `ENFORCE` in both because it is
the *policy's* mode, not the engine's. Nothing in the record distinguishes them.

**Chapter 10. Latency and the cost of enforcement.** p50/p99 against a paired no-policy baseline.
Figures per Appendix D — **blocked on pass 2.**

**Chapter 11. Failure posture and change control.** Fail-open vs fail-closed is undocumented by
AWS for guardrail errors during model invocation, so the application owns the decision
(`v1.4.md:256` already states this correctly). Plus the F5-2 change-control interval from §Part II.

### Part IV — Limits

**Chapter 12. Threats to validity.** **[C] — UNBLOCKED 2026-08-15**, with a caveat that is itself the
most useful thing pass 2 produced. Four named parts — **construct, conclusion, internal, external** —
because ACM SIGSOFT `Experiments.md` L56 makes exactly that list an **Essential**, and because L108
names *"validity threats are simply listed without linking them to results"* as an antipattern, which
is precisely the defect our dispersed per-item prose has today: **every threat below must name the
specific result it threatens.**

**The attribution caveat, which the chapter must state in its own first paragraph.** That Essential
lives in the **Experiments (with Human Participants)** standard, which explicitly redirects
non-human-participant work elsewhere; `Benchmarking.md` requires only **construct** validity and
Engineering Research names none. A hosted-guardrail latency-and-efficacy study is a Benchmarking /
Data Science study. So the four-part structure is attributed to the **Cook-Campbell / Wohlin-Runeson
lineage** and adopted **voluntarily** — claiming the SIGSOFT Essential as binding on us is the single
most likely citation error a reviewer will catch. Wohlin et al. (2012) is cited for the fact that
**Presentation and Package is a distinct methodological phase** (ch. 11, pp. 153-157) and for chapter
structure only; its prose is **not** quotable — Springer returns 303 to its identity provider, so only
Crossref/OpenAlex metadata was verifiable.

Still true and worth keeping as the section's motivation: `grep -ic 'threats to validity'` = 0 and
`grep -ic 'construct validity'` = 0 in `v1.4.md`.

Known content, now with its validity category attached:
- **Conclusion validity — single-day measurement.** 12 cases were amended on one calendar day's data
  and owe a replication (`RECONNECT.md`); the gate exists and visibly blocks them. *Threatens:* every
  amendment in Appendix D's fourth and fifth batches.
- **Conclusion validity — repeatability is not reproduction.** Our second-day runs are our own harness,
  run by us. In ACM's vocabulary that is **Repeatability (same team, same setup)**, which carries no
  badge; *Reproduced* and *Replicated* are reserved for non-authors. **No independent party has re-run
  anything here.** Say what a second day does buy in the same breath — it caught DEV-P4-35, where day 1
  passed with zero slack. *Threatens:* the `reproduction_before_amendment` gate's own name.
- **External validity — a hosted moving target.** `AWS-BEHAVIOR-CHANGES.md` exists because the system
  under test changed during the study. Any verdict is dated. *Threatens:* all 91.
- **Construct validity — coverage vs conjunction.** 91 independent verdicts do not compose into an
  end-to-end safety claim; no case tests two controls interacting. Stating this is the difference
  between a research paper and a marketing document. *Threatens:* any aggregate reading of the verdict
  count. This is the one category `Benchmarking.md` actually requires, so it gets the most space.
- **Construct validity — 57 of 546 claims are prescriptions, not propositions.** The apparatus cannot
  decide them in principle. *Threatens:* the implication that 91 verdicts validate the document.
- **External validity — one region, one account, one document, one SDK version.**
- **Internal validity — instrument defects found and repaired mid-study.** Six in the Cedar
  resource-scope repair alone (FINDING-P1-CEDAR-RESOURCE-SCOPE.md), plus F5-7b's unreadable invoke
  channel and F5-8's undiagnosed `session 2: INVOKE FAILED`. *Threatens:* any case whose rounds were
  superseded.
- **Internal validity — F5-3b is TRUE but non-publishable**; its
  `every_boundary_transition_was_observed_to_settle` guard failed. It must never be cited as
  confirmation. *Threatens:* a reader who reads TRUE out of the register without the guard.

**One rigor claim belongs here rather than in the introduction, and it must be phrased as a comparison,
not a boast.** This study sealed its oracles, decision rules and exclusion rules by sha256 before any
data existed. In software-engineering venue terms that is a **Desirable** attribute for experiments
(`Experiments.md` L75, *"pre-registration of hypotheses and design (where venue allows)"* — not
Essential) and it is required **zero** times by the eight standards that include Benchmarking and Data
Science. So: sealed design, self-run replication. Both halves in one sentence, or neither.

**Chapter 13. What this paper does not establish.** The honest ledger, quantified:
- **20 INCONCLUSIVE** of 91 published verdicts — and INCONCLUSIVE licenses no amendment.
- **1 NOT MEASURED** (F10-1, the billing asymmetry — Cost Explorer's daily granularity cannot
  supply the delta the oracle needs).
- **1 UNTESTABLE by its own sealed oracle** (F9-1 — AgentCore exposes no fault-injection surface).
- **57 prescriptions were never measurable in principle** — 10.4% of the 546 triaged claims are
  best-practice recommendations, checklist steps, design principles and decision-matrix
  recommendations, excluded because a prescription is not a proposition. **This is the paper's
  sharpest self-criticism and it must be in the body, not buried:** the parts of a
  guardrails document that tell you what to do are precisely the parts an oracle cannot decide.
  It is also the same limitation the research found in OWASP itself, which makes it a shared
  structural problem rather than a local failure.

---

## 3. Back matter

Order is **[C]** from `toc-contents.json` across AWS whitepapers — and note the revisions table is
**not** last:

`Conclusion → Contributors → Further reading → Document revisions → Notices`

The **Document revisions** table is three columns, `Change | Description | Date`, one dated row per
revision, with the Change cell using AWS's own semantic labels (`Initial publication`,
`Minor update`, `Major update`). Our existing Appendix C/D change logs are the raw material but are
not in this form (`grep -ic 'Document revisions'` = 0).

---

## 4. Appendices — the evidence, in the form a reviewer can check

| App. | Contents | Source of truth |
|---|---|---|
| A | Pre-registration and seals: sha256 of `claims/triage_rules.py` (register, 93 cases), `lib/oracle.py`, `PREREGISTRATION.yaml`, `lib/stats.py`; the declared-vs-recomputed comparison `census.py` prints | `census.py`, `verify_prereg.py` |
| B | **Method per family** F0–F10: what was provisioned, the sealed oracle, arms, n, dates, and the instrument | `results/FINDING-*.md` (17 documents) |
| C | **Full register**: 546 triaged claims → 93 cases → 91 verdicts, with the exclusion reason for every one of the 161 caseless claims | `claims/triage.csv`, `results/phase1/*.json` |
| D | **Figures and statistical conventions** — **still BLOCKED**, now on a scoped verification of 8 located URLs, not a search | `RESEARCH-evidence-presentation-20260815.md` §5 |
| E | Deviations and errata | `DEVIATIONS.md`, `results/ERRATA.md` (E-1) |
| F | Not-measured register | `results/CENSUS-NOT-MEASURED.md` (F10-1) |
| G | Reproduction: how to re-derive every number in the paper — **and how far that reaches** | `census.py`, `verify_phase0.sh` |

**Appendices A–C together are the artifact appendix, and they should be shaped like one.** [C]
USENIX's mandatory artifact appendix is *"a self-contained document that describes a roadmap for
evaluators"* covering hardware, software and configuration requirements, the paper's major claims, and
how to reproduce each — because *"Linking the claims of the paper to the artifact is a necessary step"*.
Its template cross-references each claim **C1, C2 …** to the experiment **E1, E2 …** that establishes
it, and its own bolded line recommends **at most 3 pages** for the roadmap.

Two consequences. **Appendix C gains a C↔E column** so the mapping is explicit rather than implicit in
a case id; our `claims/triage.csv` → case-id → `results/phase1/*.json` chain already is a C↔E mapping
that has never been *presented* as one. And **Appendix G must state its own reach**: it explains how to
re-derive every number, which under ACM's vocabulary supports *Artifacts Available* and *Artifacts
Evaluated* on their own terms, but **not** any Results Validated claim, because that badge is by
definition earned by someone other than the authors. It should also note that a GitHub commit no longer
satisfies USENIX's Artifacts Available as of 2025 — an archival DOI is required — which is FUTURE-WORK
item 21 and is cheap to close.

**Appendix C is the paper's spine.** A reader who distrusts a body sentence must be able to walk
claim → case → oracle → verdict → evidence file without asking us anything. That every one of the
161 caseless claims carries a written exclusion reason, and **zero** are unexplained, is a fact
worth stating in the appendix header — it is what makes the register auditable rather than
selective.

---

## 5. Figures — provisional list, forms pending

**Still [U] for the most part — pass 2 landed and returned two anchors, not a convention set.**

The two things now **[C]** and usable:

- **Distribution results get a distributional form.** ACM SIGSOFT's Information Visualization
  Supplement maps the Distribution intent to *"Histogram, Frequency polygon, Cumulative density,
  Quantile-quantile plot, Boxplot, Violin plot"*, and `DataScience.md` L42 makes it **Essential** to go
  *"beyond single-dimensional summaries of performance (e.g., average; median) to include measures of
  variation, confidence, or other distributional information"*, with L87 forbidding *"effect sizes
  without confidence intervals"* and L88 *"Reporting a median, without any indication of variance"*.
  **So figure 3 is a CDF or quantile plot, not a bar of means, and every p50 in the paper carries a
  spread.** Our Appendix B Hodges-Lehmann shift with 95% CI [30.2, 57.0] already meets L87.
- **One named axis antipattern:** *"using truncated bars to exaggerate differences"*. Cite it and obey
  it; do not extrapolate a wider anti-chartjunk canon from it, because nothing else survived.

Everything else here remains **[U]** and, worse, **unadjudicated rather than unsearched**: sources for
censoring, for binomial intervals at zero successes, and for colour-blind-safe three-state encoding
were located and never voted on. **WCAG 2.2 Use of Color** in particular would convert figure 6's
third-state requirement from our judgment into a standards citation — colour must not be the only means
of conveying information, which is the actual reason INCONCLUSIVE needs hatching and not merely a third
hue. Do not cite any of those eight until the scoped verification pass runs;
`results/RESEARCH-evidence-presentation-20260815.md` §5 lists them.

| # | Figure | Result type | Known constraint |
|---|---|---|---|
| 1 | Verdict distribution over 91 published verdicts | categorical, 4 states | INCONCLUSIVE must not read as failure |
| 2 | Evidence strength by document section | stacked categorical | must reproduce the §Part II table exactly |
| 3 | Enforcement latency, policy vs paired no-policy baseline | latency distribution, p50/p99 | client-side timeouts are **censored** observations |
| 4 | Guardrail confidence-score lattice | discrete distribution, n=61 | **censored below τ** — two low lattice points unobserved |
| 5 | Detection efficacy by arm (F5-6 tagging) | small-n binomial | must render `recall 0 [0, 0.031]` at n=120 honestly |
| 6 | Control × threat coverage matrix (ACG × T1–T17) | three-state matrix | third state must be visually distinct from failure |
| 7 | Mode-flip timeline (F5-2) | event timeline | 602.8 / 931.7 ms accept → 13.2–14.2 s serve |
| 8 | Metric-vs-log agreement (DEV-P4-27) | paired sums | 24.6/24.6, 0.8/0.8, 24.2/24.2 |

Every figure must be **generated from the evidence tree by a script in the repo**, never
hand-drawn, so that Appendix G's reproduction claim is true. Any figure whose numbers cannot be
regenerated does not ship.
