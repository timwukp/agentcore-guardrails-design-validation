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
figure is a deficiency with a name, not a blank space. **29** was added on 2026-08-16 by dry-running
`runner/merge_evidence.py` over all twelve staging trees — the first audit of them as a set, and the
first thing anyone had done to that directory other than read one of them. **30** and **31** were added
on 2026-08-16 by writing `claims/tests/test_future_work_register.py`, which derives this register's size
from its own headings: 30 is Tier 5, which had held four fixes with **no item number** and was therefore
outside every count in the repo, and 31 is the run-book's own gate runtime, which the run-book stated
three different ways. Both were found by making a number checkable, not by re-reading the file — and 31
was then found to be **wrong itself** on 2026-08-17 and rewritten from a timed run, which is recorded in
the item rather than quietly replaced. All are placed in the tier
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

### 32. Two sealed oracle kinds adjudicate a threshold with no decisiveness requirement, and three verdicts flipped on it

**Evidence.** `results/FINDING-F6-DAY2-DECISIVENESS.md`, from the 2026-08-19 day-2 replication of all
nine F6 cases. `BAND_CONTAINS` computes and publishes an order-statistic CI for each percentile and then
adjudicates on the **point estimate**; `CI_OVERLAPS` treats any non-empty intersection as TRUE regardless
of how small it is. Neither can express "the interval spans the threshold, so this measurement decides
nothing", even though `INCONCLUSIVE` exists elsewhere in the study.

Three cases flipped FALSE → TRUE on replication, and in all three the day-1 CI lay wholly on the
refuting side of the threshold while the day-2 CI straddles it:

| Case | day-1 interval vs threshold | day-2 interval vs threshold |
|---|---|---|
| F6-2 | p99 CI [551, 689], wholly above 500 | p99 CI [317, 752], **straddles** 500; scored TRUE on p99 = 375 |
| F6-5 | p99 CI [541, 858], wholly above 500 | p99 CI [347, 722], **straddles** 500; scored TRUE on p99 = 466 |
| F6-8 | slope CI [838.7, 862.7], disjoint above [165, 750] | slope CI [736.4, 757.5], overlaps by **13.6 ms**; 36% still above 750 |

The day-2 p99 CIs are 435 ms and 375 ms wide — each about as wide as the 400 ms band being adjudicated.
Every day-2 verdict is a **faithful** application of its sealed oracle; all five guards pass and F6-2's
second condition holds on both days. Nothing was mis-scored. The `kind` is underpowered for the
threshold it is asked to decide.

**Why this is Tier 1.** The paper's Chapter 10 table cites F6-2 and F6-5 as **FALSE — p99 outside**, and
§10.1 argues explicitly that failing on the tail is "the correct thing to fail on". That argument needs
a tail estimate precise enough to fail on, and at n = 1,000 it is not. As written the paper asserts a
refutation its own confidence intervals cannot carry on a second day.

**Closes when.** (a) a citation qualification is recorded — **not** in `results/ERRATA.md`, whose
opening paragraphs scope it to "factual errors in what a sealed file says … and not for verdicts,
which live in `results/` and the findings"; nothing here is a wrong statement inside a sealed file, so
an entry there would be the first violation of that file's own charter. The two existing citation
restrictions (F5-3b non-publishable, F1-19 not a verdict) live as prose in
`results/CENSUS-NOT-MEASURED.md` and this register respectively, which means there is **no single place
a reader can check before citing a case** — so the closing condition is a `results/CITATION-POLICY.md`
holding all three restrictions plus this one, derived-checked against the case list the way the census
is, and it is the same artifact the GRX Live plan calls `citation_policy.json`. The statement it must
record for F6-2, F6-5 and F6-8: neither TRUE nor FALSE may be cited on the tail comparison, because
n = 1,000 cannot adjudicate a 500 ms p99 threshold at this dispersion. (b) Chapter 10's table and Figure 3 carry the qualification, and
the "correct thing to fail on" paragraph is rewritten to distinguish the p50/p90 claims (decisive on
both days, inside the band on both days) from the p99 claim (not established either way); and (c) a
successor `kind` with a decisiveness requirement is specified for any **future** pre-registration —
`PREREGISTRATION.yaml` is sealed, so these cases cannot be re-scored and must not be.

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

`RECONNECT.md` records, in its open-items list, that `pull` exits 0 after an
`EndpointConnectionError` (grep the exception name — this anchor was a line number until 2026-08-17
and had already drifted by two lines). A static read of
`cmd_pull` (lines 573-604) and `main()` (643-664) found **no swallow path** — the whole file has
exactly one `except` clause (line 395, `InvocationDoesNotExist`). The one reproduction attempt was
**invalidated**: its traceback proved the failure came from `_state()`'s instance-profile repair
racing a concurrent `provision.py`, not from the S3 path. **Verify before fixing**; if it cannot be
reproduced, correct that `RECONNECT.md` entry rather than "fix" a non-bug.

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

**CLOSED 2026-08-19 — pulled and verified.** Manifest: `results/ITEM24-PULL-MANIFEST.json`. The premise
that the records were "spread across four `out/<ts>/` prefixes" was wrong in a way that made the job
smaller: the prefixes are **cumulative re-publishes**, not increments. Each run id's object set was
compared across every prefix holding it and found to have exactly **one** signature — 14 objects for
`r20260813T145248Z` (in 9 prefixes) and 310 for `r20260814T031052Z` (in 5) — so the latest prefix alone
is complete. Pulled `out/20260815T061609Z/evidence/{r20260813T145248Z,r20260814T031052Z}/` with
`aws s3 cp --recursive`: **324 objects, 1,721,352 bytes**. The `runner/sync.py pull` path was not used,
so item 16 stays open. Verified three ways — every object's local MD5 equals its S3 ETag (all 324 are
single-part, so the ETag *is* an MD5); every local size equals the listed size; and the local file set
equals the listed key set **in both directions**, so nothing extra arrived and nothing is missing. A
sha256 per object is recorded in the manifest as the durable digest, because an ETag is S3's own and
would not outlive the objects. F10-3's and F3-11_snapshot's day-1 call records now exist outside the
expiring bucket. The `expire-90d` lifecycle is deliberately left in place: extending retention of
unredacted evidence would be a liability, not a safeguard.

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

### 29. A second run into one run_id overwrites the first day's per-case roll-up, and the survivor lives only in a gitignored staging directory

**Evidence.** `runner/merge_evidence.py` was run in dry-run over all twelve
`runner/.state/incoming/<stamp>/` trees on 2026-08-16 — the first time anything has audited them as a
set. Eleven are fully merged (`to copy 0`, `conflicts 0`; e.g. `20260814T062501Z` = 25,174 identical
files, `20260813T174237Z` = 3,168, `20260815T061609Z` = 259). One is not:
**`20260812T130844Z` reports `to copy 0` but `conflicts 8`** — eight staged evidence files whose bytes
differ from the live published copy, so the tool refuses and copies nothing.

The eight are exactly the per-case *aggregates*, never the call records:
`f3_efficacy/F3-10/{analysis,environment,summary}.json`,
`f3_efficacy/F3-10-log-surface/{analysis,environment,summary}.json`, and
`infra/P2-01-iam/{environment,summary}.json`. They differ substantively, not cosmetically: the staged
`environment.json` is stamped `2026-08-12T03:07:54Z` and the live one `2026-08-13T02:28:49Z`; the staged
`summary.json` names `0510_get_gateway_ok.json` with `duration_ms 948.4` and request_id
`dfaad8d6-…`, the live one `1492_get_gateway_ok.json` with `892.9` and `ab01c08c-…`; staged
`analysis.json` has `arms.active_golden_set.score_datapoints.n_score_series_this_gateway: 28`
against the live **48**, and the live one carries a
`application_logs.numeric_strings_seen…contentFilter[].score: "0.8000"` key the staged one does not.

**Root cause.** F3-10 was replicated by running the producer a second time **into the same run_id**
(`r20260810T130945Z`). Call records are sequence-numbered, so both days coexist — the live directory
holds **2,696** files and day-1's `0510_get_gateway_ok.json` is still there, against **1,494** staged.
But `analysis.json` / `environment.json` / `summary.json` are one-per-case-directory, so day 2 wrote
over day 1's. This is the shared-output-file shape of a second-instance defect: the artifact that is
appended survives replication and the artifact that is rewritten does not.

**Why it does NOT touch a published number, and why that is a fact rather than a hope.**
`results/FINDING-F3-10.md:7` states the roll-ups "are aggregates rather than calls and carry no
`t_start_utc`, so they contribute no observation day" — day attribution and every published figure are
re-derived from the 1,491 day-1 call records, which are live and complete. So the overwrite costs the
audit trail, not the verdict.

**Why it still matters.** The surviving day-1 roll-up exists in exactly one place:
`runner/.state/incoming/20260812T130844Z/`, which is **local-only and `.gitignore`d**. That directory
is also the largest single candidate in the standing "reclaim 1.6 GB from `runner/.state/incoming/`"
housekeeping idea — **so that cleanup, executed as stated, destroys the only copy of a published
case's day-1 aggregates.** Nobody would have noticed: the live tree looks complete, and the gate reads
call records.

**Closes when.** (a) The eight conflicts are resolved by hand — the honest resolution is to keep both
under day-distinguished names rather than to pick a winner, since both are real observations of
different days; (b) the producer stops writing a per-case aggregate to a path a re-run reuses (stamp
it with the day, as the call records effectively are); and (c) the `incoming/` cleanup carries a guard
that refuses to delete a tree `merge_evidence.py` reports conflicts for. Until (c) exists, **do not
delete `runner/.state/incoming/20260812T130844Z/`**.

---

### 31. The run-book stated three different runtimes for its own gate, and the one it advertised was an extrapolation from the slowest slice

The full gate takes **1 h 24 min 16 s**. That is measured, not extrapolated: `./verify_phase0.sh` on
2026-08-17, laptop, `PYTHON=.venv-oracle/bin/python`, **14/14 gates passed, rc 0**, 51% CPU
(1641.87 s user + 971.99 s system). Its pytest leg alone was **3,187 passed / 16 skipped in 1 h 04 min
17 s** over the twelve test directories. The 2026-08-15 run recorded at the top of `RECONNECT.md`
agrees — 3,143 passed / 9 skipped / 2 failed in **1 h 14 min 23 s** — so there are two runs two days
apart agreeing to within ten minutes, on a suite that grew by 49 collected tests in between
(3,154 → 3,203).

**The "≈ 6 hours" this item was filed with on 2026-08-16 is withdrawn.** It was not measured. It was
`claims/tests`'s per-test rate (438 tests / 37 min 30 s) multiplied by the 3,171 tests the suite
collects, and that multiplication assumes per-test cost is uniform while the paragraph it sat in
explained that it is not: the expensive tests are the ones that walk every file of `evidence/`, and
almost all of them are in `claims/tests`, which is the directory pytest runs **first**. The aborted
run that "reached 11%" had therefore not left the slowest prefix, so the sample was the worst-case
slice of the job and the estimate inherited its rate. Recording it here rather than deleting it,
because the error is the useful part: a rate from an ordered job's first slice is a biased sample by
construction.

So the run-book carried **three** figures for one quantity — the "~6 min" in `RECONNECT.md`'s
run-book section, the measured 1:14:23 in its own session notes, and this item's 6 hours — and the
last one was the one a reader would have believed, because it was the only one that named a method.
(No line number is cited here on purpose: this correction moved those lines, and a stale line-number
anchor is Tier 5's subject.)

**What survives, and is the actual finding.** The cost is real and it is concentrated: `claims/tests`
is **13.7%** of the tests and **58%** of the pytest leg (37 min 30 s of 64 min 17 s). It is I/O-bound,
not CPU-bound — 51% CPU with *more system than user* time — and the slowest tests are the ones that
walk all 32,018 evidence files:

| Test (durations from the `claims/tests` run of 2026-08-16) | Duration |
|---|---|
| `test_amendment_evidence_subset.py::test_the_subset_yields_the_same_observation_days_as_the_full_tree` | 218.8 s |
| `test_redaction_gate.py::test_gate_passes_on_the_real_tree` | 88.1 s |
| `test_redaction_gate.py::test_the_gate_fails_if_a_waived_fixture_is_removed_from_its_file` | 85.2 s |
| `test_finding_numbers.py::test_redaction_figures_in_the_finding_are_lower_bounds_and_hold` | 83.2 s |
| `test_amendment_gate.py::test_control_arm_the_unmutated_tree_passes` | 63.9 s |

`pytest-xdist` is **not installed** (`ModuleNotFoundError: No module named 'xdist'`), so there is no
`-n auto` to fall back on.

**Why this is still a deficiency, in a smaller and more precise way than it was filed.** At 85 minutes
the full gate is affordable before a push — which is the opposite of what this item originally claimed,
and it means the recommendation changes: **run it**, and budget an hour and a half, rather than treat it
as out of reach and fall back to a blast-radius run by default. What remains wrong is the run-book, in
both directions: "~15 min" then "~6 min" understated it by an order of magnitude, and this item
overstated it by a factor of four. A figure that is wrong in either direction produces the same outcome
— a resuming session that does not know what running the gate costs, and therefore cannot decide
honestly whether it ran one.

The concentration matters more than the total, because it is what will grow: the expensive tests are
exactly the ones that verify the **evidence tree** and the **redaction gate**, the two things whose
failure is unrecoverable once published, and their cost scales with `evidence/`, which only ever grows.
This is not a regression — the same tests were affordable when `evidence/` was a third of its present
size — so any fix must not be a one-off speed-up. The direction is already visible over two days:
3,171 tests collected on 2026-08-16 against **3,203** on 2026-08-17, and the gate itself went from
1 h 14 min 23 s on 2026-08-15 to 1 h 24 min 16 s on 2026-08-17.

**Closes when** (a) ~~`RECONNECT.md`'s figure is re-measured and corrected, and states the measurement
date~~ **DONE 2026-08-17** — one dated figure, `1:24:16`, replacing three undated inconsistent ones;
(b) there is a documented **tiered** gate — a
blast-radius tier that is honest about what it does *not* cover, and a full tier with its real cost — so
that "I ran the gate" names which one; and (c) either `pytest-xdist` is added to the figures/oracle venv
policy deliberately (it changes nothing the sealed oracle imports) or the evidence-walking tests are
given a derived subset in the manner of `claims/tests/evidence_subset.py`, whose whole purpose was this
problem one size ago. **Do not close it by deleting evidence.**

### 33. The day-2 driver's `--run-id` is not honoured, so its observation proof reads an empty directory and reports "did not observe"

**Evidence.** `session-logs/f6-day2-REAL-20260819.log`. `tools/day2_replicate.py` mints a fresh run id,
appends `--run-id <new>` to the producer command, and afterwards calls
`fresh_records(<new>, today)` as its proof that the producer observed something. State-loading producers
ignore the flag: `lib.testbed.State.load_or_new` reads `state.json` and adopts the run id recorded
there. All three F6 producers on 2026-08-19 printed `run_id=r20260810T130945Z` under a command line
reading `--run-id r20260819T030137Z`. Measured:

| | |
|---|---|
| `fresh_records("r20260819T030137Z", "2026-08-19")` — what the driver proved on | **0** |
| `fresh_records("r20260810T130945Z", "2026-08-19")` — where the records went | **9,448** |
| `evidence/r20260819*` directories | **none** |

So three producers that ran 52 min, 36 min and 2 h 41 min of real measurement each returned **rc 2 —
"did not observe"**. The early `return 2` fires before the per-case comparison loop, so
`results/day2_replication_<day>.json` was never written either; it was reconstructed afterwards by
`tools/day2_adjudicate_offline.py` from the driver's own pre-run snapshots.

**Why it matters beyond one wasted signal.** This is the *second* failure in one week caused by a stale
run id in `state.json`, in the opposite direction: on the morning of 2026-08-19 a hand-run replayed
day-1 checkpoints and produced a confident verdict from no measurement. The driver exists to prevent
that one; this defect makes it produce a confident "nothing happened" over a real observation. Both
sit in the same place and neither is caught by a gate. It also **blocks the remaining day-2 work** —
F4-6 and F2-1 are gateway-dependent and will adopt their day-1 run id the same way.

**Closes when.** (a) the driver determines the **effective** run id after the producer returns — from
the run id recorded in the verdict files the producer re-emitted, the way `evidence_date()` already
prefers a record's own timestamp over a name — and scopes `fresh_records`, `zero_call_capture` and
`transient_failures` to that; (b) it prints loudly when the effective id differs from the one it
asked for, because "the producer ignored `--run-id`" is itself a fact worth publishing, and refuses if
the effective id is neither the minted one nor a known day-1 one; (c) the `run_id` guard at the top
(which refuses a minted id naming a day-1 date, and refuses if `evidence/<minted>` exists) is
re-examined, since it protects a directory the producer may never write to; and (d) a test drives a
double producer that writes under a *different* run id than the flag it was given and requires the
driver to adjudicate rather than return 2 — an echoing double would never reach this path.

**CLOSED 2026-08-22.** All four conditions met, and the one that took the work is (d).

(a) `recorded_run_ids(before, after)` reads the run id out of the verdict files the producer
**re-emitted** — `run_id` at the top level or inside `record`, changed files only, since an unchanged
file is not evidence of anything this run did. `main()` computes `after`/`changed` first, derives
`effective = recorded or [run_id]`, and sums `fresh_records`, `zero_call_capture` and
`transient_failures` over `effective` rather than over the minted id. The warrant is the one this
project already uses: `evidence_date()` prefers a record's own timestamp to the name of the file
holding it, and a flag is a **request** where a record is a fact.

(b) The mismatch is printed as `!! THE PRODUCER IGNORED --run-id`, published in the results JSON as
`run_ids_effective` and `producer_honoured_run_id` alongside the asked-for `run_id` — two fields
because they are two claims, and a reader who finds nothing under `run_id` alone must be able to tell
"the flag was ignored" from "the run never happened". An effective id that is neither the minted one
nor any named case's day-1 id is **rc 2**, unadjudicated: without that floor the derivation would
accept a producer resuming a *third* run's state and count its old records as today's observation.
When the adopted id **is** a day-1 id — the real case — the run is adjudicated and the driver says so,
noting that only records dated today are counted and that item 29 tracks the roll-up a re-run
overwrites.

(c) Re-examined and **kept, with its scope written down in the code**. Both pre-run guards reason about
the id the driver *asks for*, so neither can see the directory that actually receives the records; they
are correct for a producer that honours the flag and cost nothing, so they stay, but the comment now
says plainly that the check which matters is `recorded_run_ids` after the producer returns — because
for five days the pre-run pair *looked* like the protection (`feedback_guard_scope_is_a_claim`), and
`main()` prints the same caveat at runtime so it reaches an operator reading the log rather than only a
reader of the source.

(d) `tools/tests/test_day2_replicate_failures.py`, **17 arms**, drives the real `main()` against a
temp repo tree with a producer double that **lies**: it writes its evidence and stamps its verdict file
with the day-1 run id whatever `--run-id` it is handed, exactly as the three F6 producers did. Rc 0,
`run_ids_effective == ["r20260810T000000Z"]`, `producer_honoured_run_id: false`, 3 fresh records. The
arm that makes it a test rather than a demonstration is its pair: with `recorded_run_ids` stubbed to
`[]` — the pre-fix behaviour — the *same* double returns **rc 2**, while an **echoing** double returns
rc 0 under both versions. That last arm is kept in the file, named
`test_a_producer_that_honours_the_flag_still_passes_under_the_old_derivation`, as the record of the
test that would have been written instead and would have shipped the bug
(`feedback_unreachable_branch_in_fake`). Two further arms keep the rc-2 path reachable when it is
genuinely true: a producer that writes nothing, and one whose recorded id is unplaceable.

### 34. The guard against counting a failed probe as an observation missed all eight of a run's failed calls, for three independent reasons

**Evidence.** `transient_failures()` was written after F8-5 (2026-08-15) precisely so a throttled probe
cannot be scored as evidence. On 2026-08-19 it reported `clean_observation: true` for **all nine** F6
cases over a run with **8 failed calls in 9,448** — derived by a predicate over each record's own `ok`
flag, un-scoped, in `tools/day2_adjudicate_offline.py::failed_calls_run_wide`:

| directory | failures |
|---|---|
| `f6_latency/F6-2_5/` | 1 × `ReadTimeoutError` @ **70,003 ms**; 3 × `ClientError` / HTTP **500** |
| `f6_latency/F6-6_7_8/` | 3 × `ProtocolError` (`RemoteDisconnected`, `ConnectionResetError(54)` ×2); 1 × HTTP **404** on `mcp:tools/call` with an empty message |

Plus one *successful* `converse` at **59,722 ms**. The F6-2/F6-5 bare arm went from `n_done 1000,
n_failed 0` to `998 / 2`, and `bare_total_ms.max` from 942 ms to 37,234 ms. Three independent causes,
any one sufficient alone:

1. **`TRANSIENT_ERRORS` is a name list.** It holds `RequestTimeout`, `RequestTimeoutException` and
   `ModelTimeoutException` but not botocore's actual read-timeout class `ReadTimeoutError`, and has no
   entry for a bare HTTP `500`. Third instance this month of a name list failing to cover the next
   member of a family a predicate would have caught.
2. **`_scoped()` cannot match a shared per-producer directory.** It requires a path component to *be*
   the case id or start `<case>-`. These records live under `F6-2_5` and `F6-6_7_8`, because one
   producer serves several cases, so no case id matches and the scan is empty whatever the error codes
   are. Note this silently narrows `evidence_date()` and `fresh_records()` for the same directories.
   A **third** consumer is affected in the opposite direction: the records themselves stamp `case_id`
   with the *producer group's* name (`F6-1_3_4_9`, `F6-2_5`, `F6-6_7_8` — 4,033 / 5,631 / 9,287
   records), so `check_amendment_readiness.observation_days()`, whose whole purpose is to scope
   replication days to the case under test, can only be satisfied by declaring a group id. Its scoping
   then degrades from per-case to per-producer, which is safe for these producers only because a
   group's members are always observed in one invocation. Declaring a real verdict id such as `F6-6`
   matches zero records and the gate fails loudly — the right direction for the wrong reason, and the
   reason `FINDING-F6-DAY2-DECISIVENESS.md` has to carry a `cases_note` explaining a nine-case finding
   whose `cases` list holds three strings, none of which is a case.
3. **Four of the eight records carry no `error_code` and no `error_class` at all.** The `F6-6_7_8`
   aborts record their failure only in `error_message`, and the 404 only in `http_status` with an empty
   message. Any classifier keyed on an error *code* is blind to them regardless of how long its list
   grows — which is why (a) below cannot be satisfied by extending the list.

**Why this is not only bookkeeping.** Two of those four aborts are the whole reason **F6-6 lost its
amendment bar**: `n_usable` 1000 → **999** against `planned_n` 1000, so `n_met` went true → false,
while F6-7 lost one it could afford (1600 → 1599). F6-8's `n_attempted` and `n_usable` are identical
across the two days, so the aborts did **not** touch the case that flipped. A guard reporting "clean"
is therefore hiding the difference between "the platform behaved differently" and "two TCP connections
were reset".

**Closes when.** (a) transient classification is a predicate over the record's own success flag first
(`ok is False`) and only then refined by shape — botocore connection/timeout exception classes, any 5xx
`http_status`/`ResponseMetadata.HTTPStatusCode` — with `TRANSIENT_ERRORS` kept only as an explicit
extra rather than as the gate; (b) `_scoped` also matches a component that names the case as one of
several joined by `_` (`F6-2_5` → F6-2, F6-5; `F6-6_7_8` → F6-6, F6-7, F6-8), and a test asserts the F6
directories resolve to the cases whose records they hold, and the same resolution is applied to a
record's `case_id` so that `check_amendment_readiness.observation_days()` can be given real verdict ids
and still match — a finding about F6-6 should not have to name F6-7's records to be checkable;
(c) a mutation check confirms the guard fires
on **this run's** records — all eight, not just the named ones — since a guard that reported clean over
a 70-second timeout is indistinguishable from no guard at all until it is shown to fail on the real
data.

**CLOSED 2026-08-22.**

(a) `failure_reason(record)` gates on **`ok is False`** and everything after the gate only chooses the
*label*. `TRANSIENT_ERRORS` survives as a label-supplier and carries a comment saying in as many words
that it is no longer the gate. Refinement order: a known service code, then a botocore/urllib3
transport class — matched against `error_class` *and* against the leading `ClassName:` token of
`error_message`, because that is the only place the three `ProtocolError` records put it — then a 5xx
status from `http_status` or `ResponseMetadata.HTTPStatusCode`, then any code, then any status, then
`unclassified_failure`. **An unrecognised failure is still reported**, which is the design decision
worth naming: one of the eight is a bare **404** (an MCP session expiry, JSON-RPC `-32004`), transient
in effect and 4xx in shape, so a rule admitting only 5xx would have dropped it. A failed call whose
reason we cannot name is precisely the one an operator needs to see. `ok` *missing* counts as a failure
only when some error field is set, so a producer that omits the flag cannot hide a raised call while a
record carrying neither is left alone.

**The first fix for (a) was too wide, and two pre-existing arms caught it — that is the part of this
closure worth reading.** Gating on `ok is False` alone made F8-5's two `ValidationException` probes
into holes in its observation. They are the opposite: F8-5 exists to check that a topic definition at
the tier limit is accepted and one over it rejected, so **the rejection is the data**, and a guard that
caveated it would put a permanent false alarm on the case — the failure mode this very item warns about
("a gate that fires on things it should not is one people learn to bypass"). `ok is False` cannot tell
"the service refused to look" from "the service looked and said no", and both of F8-5's outcomes are
`ok: false` with `retry_attempts: 0`.

So the classification is three-valued, in two functions composed by `transient_failures`:
`failure_reason` reports **every** failed call, and `service_answered` decides whether that failure is
the service's answer *about the request*. It reads the **HTTP status first**, with the error code only
as a presence test: no status at all (the call never got an answer — `ReadTimeoutError`,
`ProtocolError`), any 5xx, or 408/425/429 is a refusal; a failure that names nothing is a refusal,
which is what reaches the bare 404 whose every error field is empty; a `TRANSIENT_ERRORS` code is a
refusal by override; and only an explicit service exception on a 4xx the service *chose* is an answer.
Status-first matters because it takes the two common refusals off any name list — throttling carries
429 and server-side failure carries 5xx — so `TRANSIENT_ERRORS` is load-bearing **only** for a service
that returns a refusal as a plain 400. That residual is in the dangerous direction, so it is asserted
by an arm rather than left to be discovered, and it is the one place in the file where a name still
decides anything.

Two arms of `tools/tests/test_day2_replicate_compare.py` — written for F8-5 in August and untouched
since — went red on the too-wide version. One of them was also, on inspection, asserting behaviour
over a record shape `lib/evidence.py` **cannot produce**: it planted `error_code` with no
`http_status`, and `error_code` is set only in the `ClientError` branch (`lib/evidence.py:498-501`),
which always carries `ResponseMetadata.HTTPStatusCode` (:512). The fixture now plants the real
F8-5 shapes (`ValidationException`/400 and `ThrottlingException`/429) and the claim it tests is
unchanged; a new arm pins the safe default in the other direction, that a failure with no status is a
hole whatever it is called, since mis-reading a refusal as an answer is what corrupted F8-5's verdict
while mis-reading an answer as a hole only costs a caveat.

(b) The resolver is its own module, `lib/case_ids.py`, because two consumers needed it in **opposite**
directions and a second copy would have drifted. It is a **rule, not a list** — a joined numeric group
expands (`F6-6_7_8` → F6-6, F6-7, F6-8), otherwise the shortest case-id prefix standing before a
separator qualifies one case (`F3-4-pii-us_social_security_number` → F3-4), otherwise nothing — and the
separator is load-bearing: `F6-2_5` never means `F6-25` and `F8-50` is never credited to F8-5. Writing
it as an enumeration was tried first and **its own real-tree test failed it** on 22 `F3-4-pii-*` and 4
`F3-8-tagged-*` names where the `_` sits inside a *stratum*; `lib/tests/test_case_ids.py` (**27 arms**)
now walks `evidence/` and fails if any on-disk `case_id` resolves to nothing, or if fewer than five
names resolve to more than one case — so a resolver that only ever returned the head cannot pass it.
`day2_replicate._scoped` and `check_amendment_readiness.observation_days` both go through it.

The widening of a **replication** gate was measured before being trusted, since handing a finding a
second calendar day it did not earn turns the gate into a rubber stamp. `tools/item34_gate_delta.py`
runs both matching rules over the same records and writes `results/ITEM34-GATE-DELTA.json`; it exits
non-zero if any finding crosses `MIN_DAYS` on the rule change alone, and it runs each arm against the
`cases` declaration **that arm was written for** — its first run exited 1 because it did not, comparing
the old rule against the new nine-case F6 declaration and attributing to the resolver a change the
declaration edit had caused. A comparison that moves two variables cannot attribute what it finds.
Measured over 12 evidence-bearing
findings / 24,880 matched records: **three findings match more records and not one day set moves** —
FINDING-F3-10 2,701 → 3,040 (its own PII strata), FINDING-F5-4A 409 → 601, FINDING-F6-DAY2 18,951 →
18,957 — and `check_amendment_readiness.py`'s full output is **byte-identical** before and after. So the
change bought the ability to declare a real case id and moved no number any finding rests on.

`FINDING-F6-DAY2-DECISIVENESS.md` was then rewritten to declare the nine real verdict ids instead of
the three producer-group strings, which is what (b) existed for — and its `cases_note` now states the
part the fix does **not** buy, because the old note claimed it as the price and a reader could think it
had been paid: day scoping for those nine cases is **still per-producer**, and no matcher can change
that. The granularity is in the data — F6-6's second day is established by a record stamped
`F6-6_7_8`, which is equally F6-7's — so per-case scoping needs the *producer* to stamp per-case ids.
Tolerable only because a group's members are always observed in one invocation.

(c) Verified against the run itself, not a fixture. Over `evidence/r20260810T130945Z` for 2026-08-19
the rewritten guard reports **8 of 8** — `ReadTimeoutError`, `http_500` ×3, `ProtocolError` ×3,
`http_404` — and attributes four to each of F6-2/F6-5 and four to each of F6-6/F6-7/F6-8, so five cases
flip to `clean_observation: false` while F6-1/F6-3/F6-4/F6-9 stay clean because their group had no
failed call. Controls: a case with no records in the run and a day with no records both report clean,
so the widening did not simply make everything dirty. `tools/tests/test_day2_replicate_failures.py`,
**24 arms**, pins all of it — the four real record shapes as fixtures reduced from the actual files,
the real-tree count and the five affected cases, F8-5's two real shapes on both sides of
`service_answered`, an invented 429/408/5xx whose code appears in no list of ours still not an answer,
the documented 400 residual asserted rather than inferred, a successful call carrying a stale error
field still not a failure, and the **mutation arm**: the shipped name-keyed rule is re-created and
asserted to see **none** of the four shapes, so every other assertion in the file is non-vacuous.

**One naming change ships with this.** `results[].transient_error_calls` → `failed_calls`, its
`error_code` → `reason`, and `cases_with_transient_failures` → `cases_with_failed_calls`, with a
`schema_change` block in the run entry. The set now holds every failed call and `reason` can be
`http_404` or `unclassified_failure`, neither of which is a service error code, so the old keys claimed
something narrower than the data supports (`feedback_label_must_match_computation`). Every value under
the old keys in every earlier file in `results/` is `[]`, so nothing published changes meaning.

**A residual this closure does not remove.** `tools/day2_adjudicate_offline.py` emitted a `basis`
sentence justifying the run-wide view as seeing what `transient_failures()` cannot "because no
error-name list and no case scoping" — a claim about the *other* function, and half of it expired the
moment the name list did. The producer's literal is corrected to name the one surviving reason (no case
filter). `results/day2_replication_2026-08-19.json` still carries the **pre-fix** sentence, because it
is a dated derived artifact and hand-editing one to agree with today's code is how a record stops being
evidence; it was true when written and is superseded here. Re-running the adjudicator over the archived
snapshot would refresh it without moving a number, and is deliberately not done in the same change that
altered the code it describes.

### 35. The redaction gate read every published byte for five days and could not see the account ID in twenty of them, because both guards anchored the identifier on `\b`

**Severity: this one got past the gate and into a commit.** The live AWS account ID was present
**twenty times** in `results/phase1/F5-7b.json`, from the only commit that ever touched that path
(`3f3c398b`, 2026-08-14T17:02:41Z) until it was masked on 2026-08-19 — so it was in the pushed tree
for the file's entire life, not introduced by a later edit. The repository is **private** (verified by
API on 2026-08-19: `private: true`, 0 forks, 0 watchers, 0 subscribers, one collaborator), so no
third-party read is evidenced; the severity is unchanged all the same, because what failed is a
**pre-publication** gate whose whole job is to be correct *before* visibility is ever widened. Full
write-up in
`results/FINDING-P1-REDACTION-ENCODING.md`; recorded here because the defect is a property of the
guards, not of the case.

**What happened.** F5-7b's instrument invokes an AgentCore runtime whose ARN is a **path segment of
the invoke URL**, so every colon in it arrives percent-escaped. A botocore read-timeout message quotes
that URL verbatim, and the record keeps the message. `check_redaction.py`'s account pattern is
`\b\d{12}\b`; the character before those digits was the trailing letter of an escape, so **the word
boundary could not exist** and the pattern did not fire. The same one-character property defeats
`arn`, `private-ip`, `vpc-or-subnet-id` and `s3-uri` — five of the gate's patterns and both of
`lib/redact.py`'s ARN passes, from a single cause.

**Why neither of the two layers caught it, which is the part worth keeping.** This project's stated
defence is that a masker (`lib/redact.py`) and a gate that reads the bytes (`check_redaction.py`) are
independent, so what lives in the gap is only "an identifier shape the masker does not cover". Here
they were **not independent**: both anchored the account ID on `\b`, and both broke on the same input
for the same reason. Two layers with a shared assumption are one layer. The gate also *did* fire on
this exact file for `private-ip` and carried a reviewed ALLOW for it — so the file was known to the
gate, reviewed by a human, and still shipped the account ID.

**Fixed 2026-08-19** (both root causes, not the instance): `check_redaction.scan_forms()` applies
every pattern to each line as written **and** URL-decoded, so the whole class closes in one place and
each pattern keeps being written against the identifier's real shape; `lib/redact._ARN_ACCOUNT_PCT`
masks the encoded ARN registry-free; and the registered-token pass moved from `\b…\b` to
`(?<!\d)…(?!\d)`, because the property that actually matters is "not part of a longer *number*" — the
`US_BANK_ACCOUNT_NUMBER` corpus and 12-digit epochs are digit runs — and letters around an account ID
never make it less of a disclosure. **24 arms** in `lib/tests/test_redaction_gate_encoding.py`,
including two that assert the OLD anchors were structurally blind (so the suite distinguishes a fix
from a claim), a no-mutant control, a mutant that restores the identifier and requires conviction, and
two that assert the widening did **not** start masking 12-digit corpus values or epochs. Measured
2026-08-20 over the six redaction-related suites: 114 arms pass, 90 of them pre-existing and unchanged.
`results/phase1/F5-7b.json` `38e0ba4a…0de9635c` → `1d45454a…069a3414b7`, 20 occurrences → 0, verdict
and every other field byte-identical.

**The `%3A` fix was not the whole cause — a second instance, 2026-08-20.** `\b` was left in place and
`%3A` was only one way to break it. Mutation-testing the new payload gate
(`platform/build/gate_payload.py`, 22 arms) produced an arm that puts the account ID inside a file that
will not decode as UTF-8, and it **failed**: Python's `\w` is Unicode-aware, so a latin-1 high byte is a
word character and `\b\d{12}\b` has no leading boundary — exactly `%3A`'s property. The general case is
worse here than the binary one, because this repository ships zh-TW prose and two 61-slide zh-TW decks:
CJK either side of twelve digits with no separator is equally invisible. Adopting `lib/redact.py`'s
`(?<!\d)…(?!\d)` was **measured before being rejected**: of **11,679** hex digests in scanned files,
**281** hold a run of exactly twelve digits, so that boundary would raise 281 findings that are sha256
characters. `\b` is load-bearing there; the asymmetry is that the masker matches a *known literal*
account while the gate matches any 12-digit *shape*. Fixed as a **form, not a pattern**: `scan_forms()`
also yields each form with every non-ASCII character replaced by a space (one character for one, so
reported columns still line up), which restores the boundary around CJK and high bytes while leaving
ASCII-flanked digests protected. `scan_forms()` now returns `(form, note)` pairs rather than a list
whose label a caller derived from its index, because two independent reasons to add a form now exist.
New labels: `(non-ASCII blanked)` and the composed `(url-decoded ×1 + non-ASCII blanked)`.
**Zero new findings on the current tree** — rc 0 over 745 files / 48,061,072 bytes, 67.4 s, that
denominator being what the then-current nine-extension allowlist admitted (see the third instance
below, which replaced it). **Still blind, knowingly:** an account ID flanked by ASCII letters on both
sides, asserted by an arm so the limit is visible rather than inferred.

**Closes when.** (a) the fix is in `main` — a PR, since the published blob is what a reader fetches;
(b) it is stated plainly, in the PR and here, that **rewriting history is not part of the remedy**:
the pre-fix blob stays reachable by SHA for as long as the repository exists, so masking forward does
not un-write it. Because the repository is private, that is a **decision point before any future flip
to public** — not a completed disclosure — and it belongs in whatever checklist governs that flip.
Masking forward is proportionate rather than sufficient precisely because an account ID **is not a
credential**;
(c) a test asserts the gate's patterns are applied to more than one form of each line, so a future
performance-minded simplification that drops the decoded form reds the suite; (d) the **encoding
family is enumerated rather than assumed closed** — URL escaping is the one that shipped, but JSON
`:`, HTML entities and base64 are the same defect wearing a different alphabet, and the register
should say which of them the gate does *not* cover rather than leave a reader to infer it. As of
2026-08-19 the gate covers URL escaping only, to two decode rounds; (e) the **neighbour-character
family** is enumerated the same way, now that `\b`'s claim is written down — *a pattern anchored on `\b`
asserts something about every character class that can neighbour the identifier*. As of 2026-08-20 the
gate covers non-ASCII neighbours (blanked form) and does **not** cover ASCII letters touching both ends
of a 12-digit run, which is the 281-of-11,679-digest trade recorded above and asserted by an arm. This
item does not close on that residual being closed — it closes on it being *stated*, because closing it
would cost 281 false findings, and a gate whose output is mostly noise is a gate nobody reads.

**A third instance, and it was about the denominator rather than the pattern — FIXED 2026-08-20.**
The first two instances are both about which *forms* of a line the patterns see. This one is about
which *files* the gate opens at all. `SCAN_EXT` covered `.csv .json .md .py .sh .sql .txt .yaml .yml`
and nothing else, which is a floor with no ceiling (`feedback_scope_as_namelist`), and the version of
this paragraph written on 2026-08-19 said only that `.log` was missing and that the 7 local logs
"happen to be clean, which is luck". Measured before anything was changed, the gap was far wider than
that and the luck had already run out. The allowlist was skipping **87 files / 701,558 bytes**: **56
`.jsonl`** corpora under `corpora/` and `corpora_deviation/` — the PII, prompt-attack and multilingual
fixtures, i.e. the files that hold identifier shapes *by design*; **22 `.log` + 3 `.rc`** under
`session-logs/`; **4 renamed checkpoints** (`F2-2__tau_floor.json.smoke-20260812` and siblings), JSON
that left the scan the instant a suffix was appended to its name; and `PREREGISTRATION.sha256` plus
`.gitignore`. Scanning them: **44 hits in the corpora, every one already excused by a pre-existing
path-independent rule (zero new waivers), and 7 unwaived identifiers in 2 session logs.** So the
allowlist was not sparing the gate any noise — it was simply not looking.

**Fixed as a predicate, not a tenth extension.** `SCAN_EXT` is gone; there is no filename test of any
kind, and a file that will not decode as UTF-8 is read as **latin-1** rather than skipped, because
skipping what does not decode is the same defect wearing a different hat. This is the shape
`platform/build/gate_payload.py` was built with from birth — and it was *that module's docstring*,
written as an explicit scope claim about the repo gate, that got the gap measured
(`feedback_guard_scope_is_a_claim`). `f1_config/.wheel_cache/` became an honest directory skip: 15
gitignored third-party `.whl` zips, unreachable by a reader, whose compressed bytes read as latin-1
can match a shape-based pattern by chance. Verified **rc 0 over 838 files / 49,393,045 bytes / 10,952
reviewed exceptions**, against 745 files / 48,085,034 bytes / 10,912 for the last allowlisted run of
the same day — **+93 files and +1,308,011 bytes the gate had never read**.

**And the gate was itself a leak channel, which is the part that generalises.** The first run with the
new predicate returned 11 findings, **10 of them inside the redaction machinery's own diagnostic
output**: 4 in `session-logs/redaction-gate-20260819-pctfix.log` — this gate's own earlier output,
convicted on identifiers it had printed itself, because a finding was reported as
`form.strip()[:120]` — and 6 in a `pytest -v` log that were nothing but **test ids**, because
`parametrize` stringifies its arguments and the canary suite had assembled its fixtures at runtime to
keep shapes out of its *source* while putting them straight into its *output*. Waiving those 10 would
have moved the gap rather than closed it, so each was fixed at its producer
(`feedback_fix_producer_not_janitor`): `_snippet()` now masks every occurrence of **every** pattern
(not only the one that fired — `arn` stops before the account field, so it was printing the digits
that the `aws-account-id` finding one line below was masking); the three `parametrize` sites take the
dict key and look the fixture up inside the test; and `runner/teardown.py` stopped printing the runner
bucket name, which lives in gitignored `runner/.state/` precisely because it is a redaction target.
The two historical logs were retro-masked with a stamp naming the date, the reason and the producer
fix — they are cited evidence, so the file/line/pattern/count columns are untouched.

**Closes when** (this third instance): (a) the predicate is in `main`; (b) arms exist that would have
failed before it — **`lib/tests/test_redaction_scan_predicate.py`, 24 arms**, of which 8 plant an
identifier in one of each shape the allowlist skipped and 8 more assert that shape's suffix was
absent from the nine, so the first 8 are a regression test rather than an assertion (each passed
*vacuously* before, since the gate never opened the file); one reads `files()` by AST and requires
that it consults no filename attribute, because 8 fixtures cannot notice a *deny*list or a
`MIN_SIZE`; one asserts the latin-1 path convicts rather than returning "cannot read"; and four cover
the report; (c) the guard against the gate being a leak channel is a **property, not a list of
values** — the last arm runs the gate's own patterns over the gate's own output and requires zero
unwaived hits, so a leak shape nobody has enumerated is covered the day the report grows a line;
(d) four mutations are killed by exactly the arms that claim them, with the no-mutant control run
first: restoring the nine-extension allowlist (16 red), removing the latin-1 fallback (1), masking
only the firing pattern (2), masking only the first occurrence (1). All four verified 2026-08-20 with
the subject's sha256 checked back to its pre-mutation value
(`feedback_killed_harness_races_next`). **(a)–(d) are met; this instance closes with the PR that
carries them.**

**Which residual actually keeps this item open — the two clauses above disagreed, 2026-08-22.**
This paragraph used to read "the two residuals recorded above — the unretractable pre-fix blob and
the ASCII-flanked digit run — keep the item open", and clause (e) three paragraphs earlier says the
opposite in as many words: *"This item does not close on that residual being closed — it closes on it
being stated, because closing it would cost 281 false findings."* Both sentences are in the same item
and only one can be its closing rule. (e) is the considered one — it carries the measurement (281 of
11,679 digests) that makes the trade, and an arm asserts the limit — so the ASCII-flanked digit run is
**stated, not outstanding**, and does not keep this item open. The sentence that re-opened it was
written for the third instance's paragraph and over-reached into the item's rule.

So exactly **one** thing does: clause (b)'s pre-fix blob. It is not a code fix at all — masking
forward cannot un-write a blob that stays reachable by SHA, so the remedy is a **decision recorded
before any flip to public**, and (b) says it "belongs in whatever checklist governs that flip".
Measured 2026-08-22: **no such checklist exists in this repository** — a grep for one finds only this
sentence and the same sentence quoted in `results/FINDING-P1-REDACTION-ENCODING.md`. That is the
defect one level up, and the same shape as the item this register opened at line 12: a control that
exists only as a sentence saying it ought to exist. **This item closes when that checklist is a file**
that names the pre-fix blob, the commit (`3f3c398b`), and the decision to be taken, so the flip cannot
happen without someone reading it. Nothing else about item 35 is outstanding.

---

## Tier 5 — citation hygiene, before anything is published

### 30. The research's own citation anchors were wrong at least four times

This tier's contents were written as a table and a paragraph with **no item number**, which is why it
is numbered now rather than rewritten: for its first day it was the only work in this register that no
other document could cite, no count could include, and no test could see. `WHITEPAPER.md` called the
register *full* and gave a size that excluded these fixes entirely — so "full" was false, and the tier
whose own heading says *before anything is published* was the one tier a reader could not look up.
`claims/tests/test_future_work_register.py::test_every_tier_has_at_least_one_item` now fails on a tier
with no numbered item, so a future tier cannot be added this way again.

Fix all four anchors:

| Assertion | Wrong anchor | Correct anchor |
|---|---|---|
| Seven security best-practice areas | `security-pillar/welcome.html` (carries only the six *pillars*) | `security-pillar/security.html` or `framework/sec-def.html` |
| AWS agentic least-privilege controls | GenAI Lens landing page | `generative-ai-lens/gensec05-bp01.html` |
| "No fool-proof prevention" | `genai.owasp.org/llm-top-10/` | `genai.owasp.org/llmrisk/llm01-prompt-injection/` |
| OWASP agentic T1–T17 | landing page (banners v1.0/Feb-2025) | the v1.1/Dec-2025 PDF, pinned by sha256 |

**Closes when** all four anchors are corrected in both editions of the whitepaper and in
`agentcore_guardrails_best_practices_v1.4.md`, and the three caveats below are either applied or
recorded as declined.

Plus: quote the Security Pillar revision log as "**23 entries as of the 2024-11-06 revision**", not
a live number; do not claim AWS has a fixed prose template (four such claims were refuted 0-3, one
survived only 1-2); and check whether the **OWASP Top 10 for Agentic Applications 2026**
(2025-12-09) supersedes T1–T17 as the mapping target before building Chapter 2 on v1.1 alone — it
was sampled for cross-mapping evidence but was **not itself researched**.

### 36. An elided hash cited in prose is now proven to be a *real* hash, and still not proven to be the *right* one

**Found** 2026-08-20, while verifying a table before pushing it. `results/FINDING-F6-DAY2-DECISIVENESS.md`
§6.3 records six sha256 values and says in the same breath that they are the only way to tell which
day a live F6 verdict file holds. One of the six was elided one character short of the end of the hash
and matched no sha256 in existence (DEV-P4-44). Twenty-one elided-hash citations were in scope across
twelve documents; none had ever been checked.

**Closed by** `claims/tests/test_hash_citations.py`: every elided citation must resolve against a
universe of the sha256 of every in-scope file plus every 64-hex value the study has recorded, with
deliberately-unretained values registered and asserted in both directions. 9 arms, four mutations, one
of them against the live document.

**What stays open, and it is the interesting half.** Resolution proves a cited hash is *real*. It does
not prove the sentence attributes it to the right file, because deriving which file a prose hash refers
to is not mechanically possible in general — the surrounding sentence carries that, and some citations
name evidence that is not in this tree. Exactly one table is checked that far: the F6 restore table,
where the pairing *is* the claim, so live-file/day-1-archive identity, per-file hash agreement, and the
verdict column are all asserted. The other eighteen citations could each be a real hash printed beside
the wrong filename and every gate would pass.

**Closes when** either (a) hash citations carry the path they describe in a machine-readable form — a
convention, not a rewrite: `` `<path>` `<hash-elision>` `` adjacent in one sentence is enough for a
resolver to check the pairing — and a test enforces it for every citation of a path that exists in the
tree; or (b) the class is shown to be empty by a one-time audit of all eighteen, recorded with its
date and denominator, in which case what remains open is only the *next* citation. (a) is preferable:
(b) expires the day someone writes the nineteenth.

**Why it is registered rather than left implied by a passing suite.** The gate's reach is narrower than
its name suggests, and a docstring saying so is where the next instance hides
(`feedback_guard_scope_is_a_claim`). This register is the only place a reader looks for what a green
suite does *not* cover.

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
