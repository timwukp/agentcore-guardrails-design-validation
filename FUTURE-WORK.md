# Future work — where this study and its report are still deficient

Written 2026-08-15. Every count below is derived from `census.py`, `claims/triage.csv`,
`results/phase1/*.json` or a grep over `agentcore_guardrails_best_practices_v1.4.md`, and is dated
because the system under test moves. **Regenerate, never quote.**

The purpose of this file is to be uncomfortable. A study that publishes 46 TRUE verdicts and lists
no deficiencies is not more rigorous than one that lists them; it is less trustworthy, because a
reviewer will find them anyway and will then also distrust the 46.

Ordered by how badly each one would embarrass the paper if a reviewer found it first.

**Item numbers are stable identifiers, not positions.** Items 1–18 were written in this file's first
pass; 19–21 were added on 2026-08-15 from research pass `wf_3762680e-846` and are placed in the tier
they belong to rather than appended, so the numbering is out of order on purpose. Nothing is renumbered
once written, because other files cite these numbers.

---

## Tier 1 — the paper is wrong or self-contradictory until these are fixed

### 1. The document overclaims prevention where it measured detection — and contradicts itself

**CLOSED 2026-08-15.** Both sites rewritten in both editions, each carrying a named residual risk;
`grep -ic 'residual risk'` = 4 in `v1.4.md` and `grep -c '殘餘風險'` = 5 in `v1.4.zh-TW.md`. The
change is recorded as Appendix D **correction item 23** plus a **sixth-batch** sentence in the
Appendix D header, and as a **second editorial rule** in the Validation Status section. It amends no
claim and moves no count, because its warrant is external standards plus the *absence* of evidence,
not a verdict — F1-17 is INCONCLUSIVE from a static botocore service-model read with no operation
invoked, and `lib/oracle.py` contains **zero** occurrences of `suppressOutput` and **zero** of
`indirect`. Three legitimate uses of the verb were audited and deliberately left alone: `v1.4.md:170`
(§3.1, detect-versus-prevent, naming SCP / permission boundary / resource policy), `:201` (§3.2,
random `tagSuffix` against tag injection), `:258` (§3.3, timeouts and circuit breakers). The
`.zh-TW.md` counterparts do not use 「防止」 at all — they use 「預防」, 「以防」 and 「避免」 at
lines 172, 203 and 260 — so a `防止`-only scan of the Chinese edition would have reported them
missing; the audit was re-run over 「預防/避免/阻止」 as well and found nothing else to fix.

**Line numbers below are the pre-fix ones and have since shifted by +2.**

**Evidence.** `v1.4.md:850` says Tool I/O Guardrails "**Prevent** data leakage and indirect prompt
injection from tool outputs"; `:368` says "**Prevents** sensitive data leakage through tool
interactions". Line 199 of the same file records that untagged `InvokeModel` input is **not scanned
at all** — F5-6, prompt-attack recall **0 [0, 0.031]** at n=120. `grep -ic 'residual risk'` over
the whole file returns **0**.

**Why it matters.** OWASP LLM01:2025 states it is unclear whether fool-proof prompt-injection
prevention exists and pivots to "mitigate the **impact**"; AWS's own page is titled "**Detect**
prompt attacks" and uses only detect/filter/block language; NIST AI RMF Playbook MANAGE 1.4 requires
documenting and disclosing **residual risk**. A prevention verb on a probabilistic filter is the
single most common defect in vendor guardrails documentation, and we currently have it in two
places while having measured the counter-example ourselves.

**Closes when.** Every `prevent` on a probabilistic control is rewritten as measured reduction, and
each carries a residual-risk sentence. Two sites confirmed (`:368`, `:850`); `:168`, `:199` and
`:256` already use the word correctly (contrasting detect vs prevent, tag-injection, timeouts) and
must not be "fixed". Both the `.md` and `.zh-TW.md` change together.

### 2. Twelve amendments rest on one calendar day of data

**Evidence.** `PREREGISTRATION.yaml`'s `reproduction_before_amendment` requires a second UTC day.
Twelve cases were amended on day-1 data alone: F6-1…F6-5, F6-8, F4-6, F3-4, F8-4, F8-5, F1-14,
F10-3. The user's ruling on 2026-08-15 was **strict**, queued rather than urgent.

**Why it matters.** The gate is the study's own rule. Publishing amendments that violate it while
printing the rule in the methods section is the worst available combination.

**Closes when.** One runner session replicates all twelve plus the already-owed F4-6 and F2-1.
Until then every one of those amendments carries a one-day-data caveat **in the body, not only in
an appendix**. A contradicting day-2 is a finding, not a fix-up.

**Blocker RESOLVED 2026-08-15 — see DEV-P4-37.** All twelve are now classified from their
producers, not from prose. **Eleven ride the runner**; F6-2 and F6-5 turned out to read
`invocationMetrics.guardrailProcessingLatency`, a service-reported number, so they are as
position-independent as F6-1/F6-3/F6-4's `AgentCore.Policy.AuthorizeAction.durationNano` span.
**F6-8 must run on the laptop**: its estimator is a paired difference of *client-measured*
whole-turn wall clocks, and pairing cancels the shared offset but not the per-additional-call
network round trip — which is the very quantity the case reports. The producer says so in the
cross-check it declines to score (`f6_latency/03_composition.py:1051-1053`).

The test that decides this is **not** the family name and **not** the presence of a timer: F4-6 and
F5-8 both call `monotonic()` and are position-free because their timers are poll deadlines. It is
whether a clock reading appears **in the quantity the oracle evaluates**.

### 3. F5-8's day-2 replication has an undiagnosed instrument fault

**Evidence.** The 2026-08-15 replication returned verdict TRUE, but `session 2: INVOKE FAILED` with
an **empty reason** — 2 of 3 sessions succeeded against day 1's 3 of 3. The EXISTENCE binding still
yields TRUE.

**Why it matters.** A TRUE verdict reached with a third of the instrument silently broken is a TRUE
verdict nobody should trust, and the empty reason means we cannot currently say whether the failure
was ours or the service's. It must be recorded, not absorbed.

**Closes when.** The failure is diagnosed and written into the finding, or the replication is
re-run clean. The output is still only on the instance and in S3 — it has not been pulled into
`results/`.

### 19. We call it reproduction; the accepted vocabulary calls it repeatability

**Evidence.** ACM's Artifact Review and Badging policy v1.1 (2020-08-24) defines **Reproduced** as
main results obtained *"by a person or team other than the authors, using, in part, artifacts provided
by the author"* and **Replicated** as the same *"without the use of author-supplied artifacts"*; the
family preamble forecloses author self-runs outright — *"This badge is applied to papers in which the
main results of the paper have been successfully obtained by a person or team other than the author."*
An author re-running their own harness is, in ACM's VIM-derived terminology, **Repeatability (same
team, same experimental setup)** — a category with **no corresponding badge**. USENIX Security's
Results Reproduced likewise requires the *committee* to run it.

**Why it matters.** `PREREGISTRATION.yaml`'s gate is named `reproduction_before_amendment`, and both
editions of v1.4 already use the word for self-runs — e.g. *"round 8 on 2026-08-14 UTC reproduced both
acceptances arm for arm"*. Every one of those is us, running our own harness, on our own instance, a
day later. **No independent party has re-run anything in this study.** A reviewer who knows the badge
vocabulary reads "reproduced" as a third-party result and will treat the mismatch as inflation rather
than as a naming accident.

The gate is still worth having, and the paper should say why in the same breath: a second calendar day
is what catches instrument nondeterminism and vendor drift, and it is exactly what caught DEV-P4-35 —
F3-10's bucket set was taken from log rows stamped at request-processing time while CloudWatch buckets
at *emit* time, one publish lag later (23.6 + 0.8 = 24.4 exactly), and day 1 passed with **zero
slack**, so one day could not have found it.

**Closes when.** The paper states plainly that its replication is **repeatability, not reproduction or
replication**, in one sentence, next to one sentence on what repeatability does buy. The sealed key
name is **not** changed — `PREREGISTRATION.yaml` is sealed, and renaming it would be exactly the
post-hoc edit the seal exists to prevent; it is annotated instead, in the manner of erratum E-1.
Separately, the strongest honest badge-equivalent claim for a self-executed re-run is an **open
question** (`RESEARCH-evidence-presentation-20260815.md` §6.4) — Artifacts Available and Artifacts
Evaluated remain earnable on their own terms even when Results Validated is not.

---

## Tier 2 — structural gaps that make the paper unreviewable as science

### 4. There is no named threats-to-validity section

**Evidence.** `grep -ic 'threats to validity'` = 0; `grep -ic 'construct validity'` = 0. The
content exists but is dispersed into per-item "What the TRUE verdict does not prove" prose.

**Why it matters.** A reviewer looks for this section by name. Dispersed honesty reads as absent
honesty, and it also prevents the *aggregate* limitations from ever being stated — single-day
measurement, one region, one account, a hosted moving target, and coverage-versus-conjunction are
properties of the study, not of any one case.

**Closes when.** Chapter 12 exists per `WHITEPAPER-DESIGN.md`.

**UNBLOCKED 2026-08-15** — pass `wf_3762680e-846` landed, and it found a trap rather than a template.
The four-part structure is real and citable: ACM SIGSOFT `Experiments.md` **L56 Essential**, verbatim
*"discusses construct, conclusion, internal, and external validity"*, with **L108**'s antipattern
*"validity threats are simply listed without linking them to results"* — which is precisely the defect
our dispersed per-case prose has today. **But that Essential is scoped to studies involving human
participants**; `Benchmarking.md` requires only **construct** validity and Engineering Research
requires none, and a hosted-guardrail latency-and-efficacy study is a Benchmarking / Data Science
study. So write all four parts, attribute them to the Cook-Campbell / Wohlin-Runeson lineage, and
state that the standard actually governing this work requires only construct validity — the other
three are voluntary rigor. Citing the four-part Essential **as binding on us** is the single most
likely reviewer objection to the write-up. Detail in
`results/RESEARCH-evidence-presentation-20260815.md` §3.2.

### 5. Coverage is claimed; conjunction is not established, and the paper does not say so

**Evidence.** 91 published verdicts across 10 families, each decided independently against its own
sealed oracle.

**Why it matters.** 91 independent passes do **not** compose into "AgentCore guardrails are secure
end-to-end". No case tests two controls' interaction, and the study never attempted an end-to-end
adversary with a full attack chain. OWASP T9 and T16 name exactly this failure mode — a compromised
persistent agent identity, or loose MCP/A2A enforcement, gives "privileged, long-term API access
that bypasses the agent's conversational interface and its guardrails" and lets an attacker
"bypass guardrails entirely". Our per-control verdicts cannot see it.

**Closes when.** The paper states the limitation explicitly, **and** the future-work section
proposes the chain experiment rather than implying it was done.

### 6. 10.4% of the document's claims were never measurable in principle

**Evidence.** 57 of 546 triaged claims are excluded as prescriptions rather than propositions —
24 best-practice recommendations, 17 implementation-checklist steps, 7 decision-matrix
recommendations, 5 design principles, 4 recommended guardrail distributions. Concentrated in s8
(17), appA (7), s4-1 (5) and s7-1 (5).

**Why it matters.** These are the parts that tell a reader **what to do** — precisely the parts the
whole apparatus cannot decide. The user's requirement is that "every viewpoint and method in the
whitepaper must have been validated"; taken literally, 57 claims cannot meet it, and the paper must
say which ones rather than let the 91 verdicts imply blanket validation.

Two mitigating facts worth stating alongside it: **every one of the 161 caseless claims carries a
written exclusion reason and zero are unexplained**, so the exclusions are auditable rather than
selective; and OWASP's own agentic guide has the identical property — zero occurrences of
`benchmark`, `efficacy`, `confidence interval`, `experiment` or `latency` across v1.1, verified
under three PDF extractors plus a whitespace-stripped substring pass. This is a structural problem
in the genre, not a local failure.

**Closes when.** The paper distinguishes **measured propositions** from **reasoned prescriptions**
in its own typography, and either derives each prescription from a measured proposition or labels it
as engineering judgment.

### 7. Two document sections are weakly evidenced and would currently be presented as if they were not

**Evidence**, derived from `claims/triage.csv` × `results/phase1/`:

| Section | Claims | Verdict mix (claim × case) |
|---|---|---|
| s5-1 | 27 | **INCONCLUSIVE 17**, FALSE 6, TRUE 5 |
| s4-5-5 | 16 | **INCONCLUSIVE 14**, TRUE 1 |

Compare s4-4 (37 claims, TRUE 51 / INCONCLUSIVE 8 / RECORDED 2) and s10 (25 claims, TRUE 24).

**Why it matters.** Uniform presentation of non-uniform evidence is misleading by omission, and it
is trivially detectable by anyone who compares the body against Appendix C.

**Closes when.** Every chapter carries its own evidence-strength header, and s5-1 and s4-5-5 are
explicitly labelled weakly evidenced. Separately: the *reason* 17 of 28 s5-1 verdicts are
INCONCLUSIVE has not been analysed as a pattern, only case by case. It may indicate a
representation problem in the oracles rather than a measurement failure.

### 8. Framework cross-map is entirely absent

**Evidence.** All zero in `v1.4.md`: `OWASP` 0, `GENSEC` 0, `ATLAS` 0, `42001` 0. (`NIST` returns 16
hits, but **every one is the substring inside `deterministic`/`non-deterministic`** — the real
framework count is 0.)

**Why it matters.** A security architect cannot place our findings against anything they already
use. The mapping targets are verified and enumerable: OWASP LLM01/LLM06, the 17-threat T1–T17
taxonomy, and GENSEC01–GENSEC06.

**Closes when.** Chapter 2 exists. **Three constraints:** map by **TID only** (OWASP's own 2026
document renames T4/T6/T12); pin v1.1 + sha256 (the landing page still banners v1.0, which stops at
T15); and label the GENSEC map as **extrapolation** — `gensec05-bp01.html` names Bedrock Agents and
Flows only, and the Lens never mentions AgentCore.

### 9. Chart and statistical conventions are unsourced

**Evidence.** Research pass 1 produced **zero** surviving claims on data-visualization practice.
The paper reports three awkward result types: latency with p50/p99 and **censored** client-side
timeouts; small-n binomial efficacy (`recall 0 [0, 0.031]` at n=120); and a three-state control
matrix where INCONCLUSIVE must not read as failure. The guardrail confidence-score figure is
**censored below τ** — two low lattice points are unobserved because requests below the threshold
publish no score at all.

**STILL OPEN after pass `wf_3762680e-846` (2026-08-15) — but the shape of the gap changed.** The pass
landed and returned **two** citable anchors and nothing else: ACM SIGSOFT's Information Visualization
Supplement maps the Distribution intent to *"Histogram, Frequency polygon, Cumulative density,
Quantile-quantile plot, Boxplot, Violin plot"* and names *"using truncated bars to exaggerate
differences"* as an antipattern; and `DataScience.md` L42 makes it **Essential** to go *"beyond
single-dimensional summaries of performance (e.g., average; median) to include measures of variation,
confidence, or other distributional information"*, with L87/L88 forbidding effect sizes without
intervals and medians without a spread. That justifies a CDF or quantile plot over a bar-of-means and
gives one named axis antipattern. It covers **none** of: censoring, binomial-interval choice at zero
successes, or three-state matrix encoding.

**The correction that matters: this is not unresearched, it is unverified.** The run fetched 26 sources
and extracted 129 claims but adjudicated only 25 — the statistics and figure-design angles' sources
*were* located and never voted on. Eight are named in
`results/RESEARCH-evidence-presentation-20260815.md` §5, including Hoefler & Belli on benchmarking,
Brown-Cai-DasGupta on binomial intervals, the BMJ rule-of-three, Rougier's *Ten Simple Rules for
Better Figures*, Okabe-Ito, and **W3C WCAG 2.2 Use of Color** — which would replace authorial judgment
with a standards citation for exactly our problem, since colour must not be the only means of
conveying information and that is why INCONCLUSIVE needs hatching rather than a third hue.

**Closes when.** A **scoped verification pass over those eight named URLs** — not a fresh search —
lands, and Appendix D is written from it. Until then every figure convention in the paper is authorial
judgment and must be labelled as such, with the two anchors above cited where they apply.
Non-negotiable either way: **every figure is generated by a repo script from the evidence tree**, or it
does not ship.

### 20. The verdict taxonomy is our own construction and has no located precedent

**Evidence.** Research pass `wf_3762680e-846` looked for a citable venue or standards-body precedent
for a three-state verdict taxonomy — confirmed / refuted / inconclusive-indeterminate — with an
explicit statement that inconclusive is not refuted. **It found none across 23 verified claims and 26
primary sources.** The nearest verified material is ACM's tolerance standard and Registered Reports'
outcome-independence, both of which support publishing a null result but say nothing about a distinct
indeterminate state.

**Why it matters.** `TRUE / FALSE / INCONCLUSIVE / RECORDED` is load-bearing for this entire study —
20 of the 91 published verdicts are INCONCLUSIVE and the whole editorial rule *"an INCONCLUSIVE verdict
is not evidence against a claim"* rests on it. It is currently presented as if it were standard
practice. It is ours.

**Closes when.** The methods chapter **defines** the four states operationally — including RECORDED,
which is the least self-explanatory — instead of implying a citation. Worth one search first: NIST and
ISO conformance-testing vocabularies use *inconclusive* as a standard verdict, and if that holds it
converts an invention into an alignment. Until then, present it as a construction.

### 21. A GitHub commit no longer satisfies archival availability

**Evidence.** USENIX Security **2025 and 2026**: *"Unlike previous iterations, software development
repositories such as GitHub, GitLab, or personal web pages are not acceptable for this badge"* — an
archival repository with a DOI is required (Zenodo, FigShare, Dryad, Software Heritage, institutional
repositories). **2024 said the opposite**, explicitly allowing GitHub with *"a URL pointing to a commit
hash or tag"*. ACM's own policy names only personal web pages as unacceptable.

**Why it matters.** Everything in this study is cited to
`github.com/timwukp/agentcore-guardrails-design-validation` at a commit. Under the current rule that
is not an archival reference, and a paper that pins its evidence to a mutable host is one force-push
from being uncheckable — which is a real hazard here, because this repository is written to via the Git
Data API and has no protected-branch guarantee recorded.

**Closes when.** The tagged tree is deposited somewhere DOI-bearing and the paper cites the DOI
alongside the commit. Cheap to do, expensive to be caught on. Note the scope honestly: this is a
**venue-and-year-specific** policy, not a durable property of the badge name.

---

## Tier 3 — measurement debt

### 10. F10-1 is not measured, and the decision is the user's

The v1.2 claim is that an input-blocked request incurs **no** model-inference charge while an
output-blocked one **is** charged. The sealed oracle needs a tagged cost delta that **Cost
Explorer's daily granularity cannot supply**. Two options: accept the NOT-MEASURED record in
`results/CENSUS-NOT-MEASURED.md`, or authorize widening the runner policy for
`ce:GetCostAndUsage`. This is the one open item in the 92 verdict-eligible cases.

### 11. F9-1 is untestable by its own sealed oracle

AgentCore exposes no fault-injection surface for policy evaluation. Correctly excluded from the
denominator, but it means **fail-secure behavior under service fault is unestablished** — arguably
the most security-relevant property in the whole document. Worth stating as an open research
problem, not just a denominator footnote.

### 12. F5-3b is TRUE and non-publishable

Its `every_boundary_transition_was_observed_to_settle` guard failed. It must **never** be cited as
confirmation. The risk is a future reader seeing TRUE in the register and citing it.

### 13. F3-11 is hard-gated on calendar time

`--compare` runs owed on **2026-08-18** and **2026-09-10**. Nothing can accelerate this.

### 14. Vendor drift is acknowledged but not instrumented

`AWS-BEHAVIOR-CHANGES.md` exists because the system under test changed mid-study. There is no
scheduled re-measurement, so every verdict silently ages. Worth proposing a minimal recurring
canary — a handful of the highest-value cases re-run on a schedule — so the paper can state a
freshness interval rather than a single date.

---

## Tier 4 — engineering debt that weakens the evidence chain

### 15. F5-8 has no test file

`f5_redteam/tests/test_route_credential_reachability.py` does not exist. It must pin, at minimum:
the agreement between `CODE_BUCKET_STEM` in `f5_redteam/11_route_credential_reachability.py` and
`runner/iam_policy.py`'s `code_bucket` ARN pattern (`iam_policy.py:55`, `223-225`, `764-767`) —
the producer's own comment notes the failure mode is a mid-run `AccessDenied` on the instance,
invisible at desk; and `_returned_the_execution_role`'s rule that `sts_http_status == 200` alone is
**necessary but not sufficient**, because a leaked instance-profile credential also answers 200.

### 16. `runner/sync.py pull` bug — the premise itself is unverified

`RECONNECT.md:140` records that `pull` exits 0 after an `EndpointConnectionError`. A static read of
`cmd_pull` (lines 573-604) and `main()` (643-664) found **no swallow path** — the whole file has
exactly one `except` clause (line 395, `InvocationDoesNotExist`). The one reproduction attempt was
**invalidated**: its traceback proved the failure came from `_state()`'s instance-profile repair
racing a concurrent `provision.py`, not from the S3 path. **Verify before fixing**; if it cannot be
reproduced, correct `RECONNECT.md:140` rather than "fix" a non-bug.

### 17. Stale test floors, deliberately untouched

`lib/tests` 587 vs **839** collected; `f8_regional` 80 vs 91; `f2_determinism` 30 vs 34;
`f5_redteam` 327 vs 328. The project convention is exact-to-current, so raising them is safe only
after confirming the same files collect on the runner.

### 18. F2-3 and F2-4 have no evidence records carrying their own case_id

One script serves four cases, so their records are filed under F2-2. An open design question for
the owed F1-18/F2-2/F2-3/F2-4 finding document — **not** a silent fix, because renaming records
after the fact is exactly what the seals exist to prevent.

---

## Tier 5 — citation hygiene, before anything is published

The research's own anchors were wrong at least four times. Fix all four:

| Assertion | Wrong anchor | Correct anchor |
|---|---|---|
| Seven security best-practice areas | `security-pillar/welcome.html` (carries only the six *pillars*) | `security-pillar/security.html` or `framework/sec-def.html` |
| AWS agentic least-privilege controls | GenAI Lens landing page | `generative-ai-lens/gensec05-bp01.html` |
| "No fool-proof prevention" | `genai.owasp.org/llm-top-10/` | `genai.owasp.org/llmrisk/llm01-prompt-injection/` |
| OWASP agentic T1–T17 | landing page (banners v1.0/Feb-2025) | the v1.1/Dec-2025 PDF, pinned by sha256 |

Plus: quote the Security Pillar revision log as "**23 entries as of the 2024-11-06 revision**", not
a live number; do not claim AWS has a fixed prose template (four such claims were refuted 0-3, one
survived only 1-2); and check whether the **OWASP Top 10 for Agentic Applications 2026**
(2025-12-09) supersedes T1–T17 as the mapping target before building Chapter 2 on v1.1 alone — it
was sampled for cross-mapping evidence but was **not itself researched**.

---

## Operational, not deficiencies — but they gate the above

- The **EC2 runner is running** and billing (~$0.58/day). `runner/teardown.py` for $0 once the
  day-2 batch is done. Do **not** run `runner/sync.py` while a live case runs: `_state()` repairs
  the instance profile on every subcommand and would rotate credentials mid-job.
- The day-2 output `20260815T061609Z` has **not** been pulled into staging.
- **Nothing is blocked on `wf_3762680e-846` any more — it landed 2026-08-15.** Chapter 12 is
  unblocked (item 4). **Appendix D is not**: the pass returned two citable figure anchors and left
  censoring, binomial intervals at zero successes, and three-state encoding unsourced, so Appendix D
  now waits on a **scoped verification pass over the eight URLs named in
  `results/RESEARCH-evidence-presentation-20260815.md` §5** — a verification, not a search. Everything
  else is draftable now.
