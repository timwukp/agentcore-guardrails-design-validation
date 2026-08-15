# Future work — where this study and its report are still deficient

Written 2026-08-15. Every count below is derived from `census.py`, `claims/triage.csv`,
`results/phase1/*.json` or a grep over `agentcore_guardrails_best_practices_v1.4.md`, and is dated
because the system under test moves. **Regenerate, never quote.**

The purpose of this file is to be uncomfortable. A study that publishes 46 TRUE verdicts and lists
no deficiencies is not more rigorous than one that lists them; it is less trustworthy, because a
reviewer will find them anyway and will then also distrust the 46.

Ordered by how badly each one would embarrass the paper if a reviewer found it first.

**Item numbers are stable identifiers, not positions.** Items 1–18 were written in this file's first
pass; 19–21 were added on 2026-08-15 from research pass `wf_3762680e-846`, **22** on the same day from
running the first replication in item 2's queue, and **23–27** later that day from the third, fourth and
fifth (F10-3, F8-5, F8-4) — four of those five were found by *doing* the replications, not by reviewing
them, and item 27 is the first Tier-1 item any of this work produced, which is the argument for finishing
the remaining eight. **28** was added on 2026-08-15 from drawing the whitepaper's figures: a blocked
figure is a deficiency with a name, not a blank space. All are placed in the tier
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

**The document edit is deliberately batched, not incremental.** v1.4 already has a convention for a
replicated citation — "F5-1, TRUE, n=120, **replicated 2026-08-11/12**" — and each discharged case
earns that form. Rewriting citations one case at a time would mean a seventh, eighth, ninth amendment
batch, each dragging both editions, both decks and an Appendix D item, for a change that adds a date.
The pass happens **once**, when the batch is done or is declared closed, and it is a citation-dating
pass that amends no claim. Nothing published is wrong in the meantime: v1.4 carries no per-case
one-day caveat for these twelve to be stale — the only one-day caveat in the body is F5-8's, which is
a different case with a different problem (item 3).

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

**5 of 12 discharged 2026-08-15 — F1-14, F3-4 (DEV-P4-38), F10-3, F8-5 and F8-4 (DEV-P4-39).** F8-5's discharge is **qualified**: it replicated with a caveat and then turned out to owe an erratum (item 27), so it is discharged as a *replication* and reopened as a *finding*.

**F3-4** ran under `r20260815T084022Z` against the same guardrail at the same version (`wwjmltbo1dt5`,
READY, `updatedAt` 2026-08-10T01:15:08Z, checked live first): **367 fresh call records** dated
2026-08-15, 32 day-1 checkpoints moved aside first, FALSE → FALSE. It also replicates the *number* the
document cites rather than only the verdict — the same **9 of 31** entity types refuted, the same 2
inconclusive, and identical success counts in **31 of 31** strata. Cost **$0.037** upper bound.

**F1-14**, and fifteen sibling cases with it —
`tools/day2_replicate.py` ran `f1_config/02_model_surface.py` under `r20260815T082524Z`; the producer
decides sixteen cases, so sixteen were compared and **all sixteen agree** with 2026-08-10. $0, zero
AWS calls, on the laptop — legitimate here only because a producer that makes no network call is
position-free by construction. Day-1 verdicts are archived under `results/phase1/archive/`; the
comparison is in `results/day2_replication_2026-08-15.json`.

**F10-3** ran under `r20260815T092538Z` against the same guardrail (`s5vk53hdnahz`): **10 fresh call
records**, both day-1 checkpoints isolated first — and both were *complete*, so an unguarded re-run
would have made zero calls and exited 0 — FALSE → FALSE with the decision record identical at every
path and 5 of 5 tagged/untagged pairs billing 7 units each. ≈**$0.0105**.

**F8-5** ran under `r20260815T092557Z`, **$0** (control-plane probes), and is **REPLICATED WITH
CAVEAT**: one of its four probes came back `ThrottlingException`, so that probe is not a second
observation. It is also the case that produced items **23** and **25** in this file. See DEV-P4-39.

**F8-4** ran under `r20260815T093942Z`: **690 fresh call records** (460 `ApplyGuardrail` +
230 `InvokeGuardrailChecks`, 690 distinct request ids), 6 day-1 checkpoints moved aside, FALSE → FALSE,
≈**$0.104**. Its decision record is identical at every path — and that record is two booleans, so the
comparison was extended to the rest of the file, which is how the drift below was found (DEV-P4-39).
**CLASSIC, the tier the verdict turns on, reproduced exactly** (recall 49/120, benign FPR 4/110);
STANDARD's recall moved 119/120 → 118/120, and the `InvokeGuardrailChecks` threshold sweep moved at three
thresholds, by as much as 44/120 → 51/120. So `InvokeGuardrailChecks` confidence scoring is **not**
day-to-day deterministic, unlike ApplyGuardrail's PII matchers (F3-4) — worth stating in the paper, since
any threshold recommended from a single day's sweep inherits that movement.

**Seven remain: F6-1…F6-5, F6-8, F4-6.** Six can run live against the service;
**F6-8 must run on the laptop** (DEV-P4-37). Every branch of the driver is now exercised by use, not
only by mutation: the zero-call proof path on F1-14, checkpoint isolation plus the 367-record proof path
on F3-4, the complete-checkpoint trap on F10-3, the evidence-derived day-1 date on F8-5, and the
payload comparison on F8-4.

**F4-6** and **F2-1** are gated on infrastructure, not money:
`lib.testbed.State.load_or_new` refuses a state file written under a different run id, so each needs
`--state` or a rebuilt testbed. The six F6-* cases are next; five ride the runner and F6-8 does not.

**The driver has since been taught the comparison F3-4 got by hand** — `record_diff` reports every path
at which the two days' decision records differ, and a move in `kind`/`thresholds`/`planned_n` is an
error rather than a note. That closed the per-stratum gap and immediately opened item 23: the record can
be identical at every path and still be carrying a throttled call.

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

### 27. §3.4's Standard-tier correction cites a rejection that was about something else — and the evidence supports the documented limit

**Evidence.** F8-5's `standard-1000` probe on 2026-08-10 returned `ValidationException` with the message
"**Can't configure guardrail policy tier. Enable cross-Region inference for your guardrail to use Standard
tier.**" — a tier-configuration precondition, not a length verdict. The 2026-08-15 replication returned
the length message on the **1001**-character probe instead ("Member must have length less than or equal to
1000"), which shows length is evaluated *before* the tier gate; so day 1's 1000-character definition
**passed** length validation and day 2's 1001 did not. Both days, read with their own error messages, put
the effective maximum at exactly the documented 1000. Full probe table and derivation in DEV-P4-40.

**Why it matters.** Six published sites say the opposite of what the evidence shows:
`agentcore_guardrails_best_practices_v1.4.md` lines **274** (§3.4 tier table), **859** (checklist) and
**1047** (changelog item 7), and lines **278 / 863 / 1051** of the zh-TW edition — plus both copies in
`~/Downloads/AgentCore-guardrails-closed-loop-practices/deliverables/` and any deck slide built from §3.4.
This is the worst category in this file: not a gap, not an overclaim, but a **correction that corrects a
true statement into a false one**, published in two languages. A reader following it would avoid
1,000-character topic definitions that in fact work.

**Closes when** the user decides, because three things are entangled and only one is mine to do:

1. **The verdict.** The STANDARD half is **INCONCLUSIVE** — the sealed oracle needs an at-limit definition
   observed *accepted*, and without cross-Region inference the tier gate refuses the create whatever the
   length. It is not TRUE either: "the limit is 1000" is sound inference from two error messages, not the
   sealed criterion. `INCONCLUSIVE` licenses no amendment, so the §3.4 correction has to be **withdrawn**
   rather than reversed. The CLASSIC half (200 accepted, 201 rejected for length, byte-identical messages
   on both days) is unaffected and genuinely replicated.
2. **The erratum.** E-2, at the six sites above, both editions in the same edit, plus the bundle and decks.
3. **The re-test that would settle it, $0.** Re-run `f8_regional/04_topic_limits.py` with
   `crossRegionConfig` set on the STANDARD probes and with backoff between them, on a third UTC day. That
   makes acceptance observable and removes both throttles. It is a *new* observation of a sealed case, so
   it needs the user's go-ahead, not a quiet re-run — and if it shows 1000 accepted, F8-5's STANDARD half
   becomes TRUE and §3.4 needs no correction at all.

**Do not fix this by editing the verdict file.** The FALSE is what the sealed oracle computed from what it
was given; the defect is that it was given accept/reject and not cause (item 23).

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

**Update 2026-08-15: the generation half is now done; the sourcing half is not.**
`tools/whitepaper_figures.py` draws **7 of 8** figures from `results/` only, and `--check` re-derives
their numbers against `results/figures/MANIFEST.json` (numbers, never PNG bytes — a byte diff would red
on a matplotlib bump while the measurements were untouched). What this item still owes is unchanged: the
conventions those seven figures follow are our judgment, and the WCAG citation that would turn
"INCONCLUSIVE needs a hatch, not a third hue" into a standards requirement is still unverified.

Three things were learned by drawing them, all worth keeping:

- **A generated figure is not verified until the rendered image is inspected.** Two defects survived a
  clean script run and would have shipped a false claim. Figure 7 placed the ENFORCE restore at 26.5 s
  while labelling it "+13.3 s", because it summed two intervals that are timed from *different* control-
  plane calls — F5-2 records no clock shared between them, so the single timeline it drew could not
  exist. Figure 4 drew its two censored lattice points as bars 44 units tall, a height a reader can read
  straight off the y-axis and compare with the real 48 at score 0.8; a censored point has no count.
- **Read the measurement, not the prose beside it.** Figure 7's first label said "HTTP 200", copied from
  F5-2's `why_it_is_recorded` narrative. The measured `chain.flip.http_status` is **202**.
- **Plot every replication day.** Figure 7 initially showed day 2 only. Day 1 exists in
  `results/phase1/archive/F5-2__day1_2026-08-12.json` and disagrees — 14.2 s against 13.2 s on the same
  quantity — which is itself the result: the interval is not a constant, and a one-day figure publishes
  a precision the measurement does not have.

### 28. Figure 6 cannot be drawn: 12 of the 17 OWASP Agentic threat titles are ungrounded

**Evidence.** `tools/whitepaper_figures.py` records `fig-06-control-threat-matrix` as `BLOCKED` in
`results/figures/MANIFEST.json`, with its reason. Of the seventeen threat IDs in OWASP Agentic AI v1.1,
only **five** (T1, T3, T9, T15, T16) have a title grounded in a source this project holds; the paper's
Chapter 2 quotes exactly those. The other twelve would have to be authored from memory.

**Why it matters.** This is the one figure a security architect would use first — the control × threat
matrix is how a reader decides whether our 31 controls cover the threats they already track. It is also
the figure most dangerous to fake: drawing twelve columns from memory is fabrication, and drawing them
as an empty "not established" state would misreport **our** missing source as **AgentCore's** missing
coverage, which a matrix reads as a finding. The blocked state is the correct output, and it is recorded
where a script can see it rather than only in prose.

**Closes when.** The pinned OWASP Agentic AI v1.1 PDF (sha256 `65e3bd59f99c…0345ff`, already pinned in
Chapter 2) is re-read for all seventeen titles, `results/CROSSMAP-ACG-THREATS.json` is authored from it
with a per-cell state and a per-cell reason, and `fig06()` reads that file. The three-state encoding is
already specified: covered-by-measurement / covered-by-inference / not-established, distinct by hatch as
well as hue, which ties this item to item 9's WCAG verification.

**Constraint carried from item 8.** Map by **TID only** — OWASP's own 2026 document renames T4/T6/T12,
so a title-keyed matrix would silently mismatch across versions.

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

### 22. The replication gate does not look at the twelve cases that owe a replication

**Evidence.** `check_amendment_readiness.py` enumerates `results/FINDING-*.md`, reads
`evidence_runs` and `cases` from each provenance block, and counts distinct UTC observation days for
any finding whose status is `AMENDED` or `READY_TO_AMEND`. Eleven docs carry a non-empty
`evidence_runs`, and between them they name **twelve distinct case ids**: F1-3, F1-15, F1-19, F1-24,
F1-25, F3-10, F5-1, F5-2, F5-4a, F5-4a-logonly-read, F5-7a, F5-7b. **Not one of
the twelve cases from item 2 appears in any of them** — the two sets are the same size by coincidence
and are entirely disjoint. Those were amended through v1.4's amendment
batches, which the gate does not read.

**A correction to this item's own evidence, 2026-08-15.** It previously reported the gate as standing
at "4 problems in 92 assertions, all four about FINDING-F1-15.md and FINDING-F5-7B.md" and offered
that as the gate's fixed state. Those four problems were **not** a property of the gate: 607 evidence
records were sitting unmerged in `runner/.state/incoming/20260814T162515Z/`, so the gate was reading a
tree from which two findings' records were absent. After `runner/merge_evidence.py` promoted them,
`check_amendment_readiness.py` **exits 0**, and FINDING-F5-7B.md reports
`AMENDMENT_DEFERRED  1 day(s) ['2026-08-14']` — correctly deferred rather than erroring. The measured
figure described a transient tree state and was quoted here as if it described the tool. The
scope argument below is untouched by that correction and is why this item stays open.

**Why it matters.** The gate is the only executable statement of the study's own two-day rule, and it
is silent on exactly the population that violates it. Its failing does not mean the twelve are
unreplicated and its passing would not mean they are — so a reader who runs it, as the README invites
them to, learns nothing about the largest replication debt in the study. Worse, the gate's own
docstring describes it as enforcing the sealed rule, which reads as *the* rule rather than *the rule
over findings that happen to carry a provenance block*. Same defect class as
`FUTURE-WORK.md` item 18: a check whose scope is narrower than the claim it appears to make.

**Closes when.** Either the gate is extended to read amendment provenance from a source that covers
all twelve — `results/day2_replication_*.json` is now a machine-readable record of exactly what was
observed on which day, so the input exists — or the gate states its scope in its own output, so that
"OK" cannot be read as "the two-day rule holds everywhere". The first is better; the second is the
minimum. Do not close it by adding provenance blocks to findings that do not exist: **none** of the
twelve has a FINDING doc, and manufacturing one to satisfy a gate is the inverse of the gate's
purpose.

### 23. Producers can score a transient AWS error as an observation, and one published verdict did

**Evidence.** F8-5's oracle reads four `CreateGuardrail` outcomes, where the exception *is* the datum.
On both of its observation days one probe returned `ThrottlingException` — the service declining the
request rather than judging the topic definition — and the producer classified both as
`observed: "rejected"`. On 2026-08-10 that landed on `standard-1001` (expected rejected), so
`record.evidence.over_limit_rejected: true` over-states what was seen; on 2026-08-15 it landed on
`standard-1000` (expected accepted), so the day's entire refutation rested on a call that never reached
the boundary. See DEV-P4-39 for the probe-by-probe table. `agentcore_guardrails_best_practices_v1.4.md:274`
happens to disclose the day-1 throttle in prose, so nothing published is wrong — but that was the
author's care, not a guard.

**Why it matters.** Nothing in the evidence chain could see it. The verdict agreed, `record_diff`
reported the decision record identical at every path, and no sealed field moved, because
`record.evidence` is three booleans that cannot separate *this content was rejected* from *this request
was rejected*. `tools/day2_replicate.py` now flags transiently-failed calls at replication time
(`transient_failures`, and `clean_observation` in the run JSON), which catches the **replication**
case — it does not fix the **producer**, so a first observation can still convert a throttle into
evidence with nothing to notice.

**Closes when.** Every producer whose oracle reads an exception classifies transient codes as a third
outcome (`throttled` / `matches_expected: null`) and retries with backoff instead of scoring them, and
`lib.oracle` refuses to count a trial whose call carries a transient error. Audit target: every case
whose `record.evidence` is a boolean over error codes rather than a count — F8-5, F8-4 and the F1-*
validation-boundary family are the known population; it has not been enumerated. Until then, F8-5's
STANDARD half has **one** sound observation, not two.

### 24. Two published verdicts' call records exist only in S3, under a 90-day expiry that deletes them in November 2026

**Evidence.** Of 98 verdict files, 92 cite a run id with a local `evidence/<run_id>/` directory. Two do
not: **F10-3** (`r20260813T145248Z`) and **F3-11_snapshot** (`r20260814T031052Z`). Both ran on the EC2
runner and were never pulled, so their call records exist only in the runner's S3 bucket, spread across
four `out/<ts>/` prefixes. The bucket's lifecycle was read live: `expire-90d`, **Enabled**, prefix `""`,
`Expiration {Days: 90}` — i.e. every object, no exceptions. Those objects are therefore scheduled for
deletion **~2026-11-11 to ~2026-11-13**.

**Why it matters.** F10-3's verdict was replicated on 2026-08-15 (DEV-P4-39) and the day-2 records *are*
local, so the finding survives; but its **day-1** observation, which is the one the document cites, does
not exist anywhere else. After the expiry the study would carry two verdicts whose primary evidence is
unavailable at any level of scrutiny — which is a stronger version of item 21 (a commit is not an
archive): here there would be nothing to archive.

**Closes when.** Both prefixes are pulled into `evidence/` and the pull is verified by object count and
sha256, **or** a lifecycle exception is added for them and recorded. Blocked on a user decision: the
`runner/sync.py pull` path was declined twice and its `EndpointConnectionError` is still un-reproduced
(item 16), so the pull may have to be done with the AWS CLI instead. **This has a date on it** — unlike
every other item here, doing nothing eventually destroys evidence.

### 25. Two published run ids cannot be dated from their own name

**Evidence.** F8-5 (FALSE) and F8-8 (TRUE) carry `run_id` `smoke20260810T0305Z`, which
`lib.evidence.RUN_ID_RE` does not match, so every tool that derives an observation date from the run id
returns nothing for them. The replication driver refused F8-5 outright until a fallback was written that
reads the day off the records' own `t_start_utc` (`evidence_date`) — and those records say
**02:45:52Z–02:45:56Z**, so the string is not merely unparseable, it **disagrees** with the observation
by twenty minutes.

**Why it matters.** Any future audit that groups evidence by observation day silently drops these two,
and a reader who parses the run id gets a time that is wrong. The fallback fixes one consumer; the other
consumers of run ids have not been enumerated.

**Closes when.** Either the two verdict files gain an explicit `observed_utc_date` field derived from
their records (a *new* field, not a rewritten run id — renaming a sealed run id is what the seals
prevent), or every tool that dates a run is audited to use the record rather than the name. Prefer the
first: it is one derivation, done once, checkable.

### 26. A checkpoint labels F10-3's manipulated arm as unmanipulated

**Evidence.** F10-3's two day-1 checkpoints both record `meta.qualifiers: []`, including the *tagged*
arm — whose entire manipulation is `qualifiers=['guard_content']`. The verdict itself is sound: the
qualifier is set per content block, not on the request (`f10_billing/02_input_tagging.py:230`), the
producer's own `manipulation_check()` FATALs if the two arms differ by anything else, and the published
verdict records `tagged_qualifiers: [[], ["guard_content"]]` against `untagged_qualifiers: [[], []]`
with `texts_identical: true`.

**Why it matters.** It cost real time during the 2026-08-15 replication: the checkpoint was read as
evidence that the manipulation had not been applied, and it took reading the producer to establish that
the label, not the experiment, was wrong. A checkpoint field that contradicts the manipulation it is
meant to document is a trap for the next reader, and it is on the artifact a resumed run trusts.

**Closes when.** `meta.qualifiers` records the per-block qualifiers actually sent (or is renamed to say
it holds the request-level ones, which are always empty for this producer). Cosmetic for the verdict,
not for the audit trail.

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
