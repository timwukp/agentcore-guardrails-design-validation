# Measured Guardrails for Amazon Bedrock AgentCore

## An evidence-based guide to end-to-end enforcement design

**Publication date:** 2026-08-15
**Edition:** first draft (v1). This document carries a publication date and a revisions table, not a
semantic version. The internal design document it examines —
`agentcore_guardrails_best_practices_v1.x` — keeps its own version line and is referred to throughout
as *the document under test*.

**Regenerate, do not quote.** Every count, proportion and interval in this paper is derived by a
script in the accompanying repository. Two commands reproduce them all:

```
./.venv-oracle/bin/python census.py                    # the case census
./.venv-oracle/bin/python tools/whitepaper_data.py     # every number this paper quotes
```

---

## §0. Draft status and open testing debt

This section is first on purpose. A paper whose evidence is still being collected should say so before
it says anything else, and should say exactly what is missing rather than gesturing at future work.

**What is finished.** 93 propositions were registered against a sealed oracle before any data existed.
92 are verdict-eligible; **91 carry a published verdict** on disk. The verdict mix is **TRUE 46,
FALSE 23, INCONCLUSIVE 20, RECORDED 2**. 546 claims were extracted from the document under test and
triaged; 385 map to at least one case; 161 do not, and **all 161 carry a written exclusion reason —
zero are unexplained**.

**What is not finished, itemised.**

| # | Open item | State | Consequence for this paper |
|---|---|---|---|
| 1 | **Seven day-2 replications** — F6-1, F6-2, F6-3, F6-4, F6-5, F6-8, F4-6 | queued; 5 of the original 12 discharged 2026-08-15 | Chapter 10's latency numbers and ACG-01-BP05 rest on **one calendar day** of data. The replication gate exists, is executable, and currently blocks the corresponding amendments. |
| 2 | **F10-1 — NOT MEASURED** | needs a decision, not a run | The billing-asymmetry question (does an input block avoid the model inference charge?) is unanswered. Cost Explorer's daily granularity cannot supply the delta the sealed oracle requires. §10.4 states the gap and nothing more. |
| 3 | **F9-1 — untestable by its own sealed oracle** | closed as untestable | Whether policy-evaluation timeout yields automatic DENY cannot be decided: AgentCore exposes no fault-injection surface for policy evaluation. Chapter 11 is explicit that only the *missing-permission* failure mode was observed. |
| 4 | **Appendix D — figure and statistical conventions** | BLOCKED | Eight sources are located but unadjudicated (censoring, binomial intervals at zero successes, colour-blind-safe three-state encoding). Until they are verified, Appendix D states conventions as **authorial judgment**, not as citations. |
| 5 | **Figures: 7 of 8 drawn; figure 6 blocked** | drawn 2026-08-15 | All seven are generated from the evidence tree by `tools/whitepaper_figures.py`, and `--check` re-derives their numbers against `results/figures/MANIFEST.json`. **Figure 6 (control × threat matrix) is not drawn and states why:** only 5 of the 17 OWASP Agentic v1.1 threat titles are grounded in a source we hold, so 12 columns would be authored from memory. Its blocking reason and closing condition are recorded in the manifest, not in prose alone. |
| 6 | **F8-5 — an open Tier-1 erratum** | awaiting a decision | The document under test publishes a correction to denied-topic length limits that rests on a rejection that was about a different precondition. §8.4 of this paper marks the passage **contested** rather than restating either reading. See Chapter 13 and `FUTURE-WORK.md` item 27. |
| 7 | **F5-3b — TRUE but non-publishable** | excluded from all conclusions | Its `every_boundary_transition_was_observed_to_settle` guard failed. It appears in Appendix C for completeness and is cited nowhere as confirmation. |
| 8 | **F3-11 — hard-gated on calendar time** | re-runs due 2026-08-18 and 2026-09-10 | Vendor drift is INCONCLUSIVE by construction until those dates pass. |
| 9 | **F2-3 and F2-4 have no evidence records carrying their own `case_id`** | engineering debt | Their verdicts are traceable through a sibling case's records rather than their own. Weaker than every other case's chain. |
| 10 | **Two published verdicts' call records exist only in S3, under a 90-day expiry** | expires ~2026-11-11 | F10-3 and F3-11_snapshot. Archived copies are required before then or the evidence chain breaks. |
| 11 | **No independent party has re-run anything** | structural | See Chapter 12. Our second-day runs are *repeatability*, not reproduction. |
| 12 | **A zh-TW edition** | not started | Follows once this English edition stabilises. |

**How to read a draft.** Nothing in §0 weakens the 91 published verdicts; each was decided by an
oracle sealed before data collection, and each is traceable in Appendix C. What §0 bounds is how far
those verdicts may be read — which is the same discipline the rest of the paper applies to the
document under test.

---

## Abstract

A production design document for Amazon Bedrock AgentCore guardrails was treated as a set of testable
propositions rather than as guidance. 546 claims were extracted and triaged; 93 became experiments
with falsifying conditions sealed by sha256 before any AWS call was made; **91 of the 92
verdict-eligible propositions were decided against live service behaviour in `us-east-1`**, with
n up to 1,000 per case, Wilson or order-statistic intervals on every proportion and quantile, and a
pre-committed cross-instrument rule for disagreement.

The result is not a validation. **23 propositions were refuted and 20 could not be decided.** Several
refutations change design decisions: documented PII detection fails its own threshold for 9 of 31
entity types (`DRIVER_ID` 0 of 11); prompt-leakage recall is 0.3611 [0.2767, 0.455] at n=108 where
the document implies parity with jailbreak detection at 0.8917 [0.8234, 0.9356]; four measured
enforcement-latency hops lie **outside** the document's stated bands, one by a factor of two; and a
denial carries no policy identifier in 120 of 120 observations, so an alarm cannot attribute a block
to a rule.

This paper reorganises what survived into a numbered control catalogue (`ACG-nn-BPnn`) in which every
control states the evidence behind it, its residual risk, and — mandatorily — **what it does not
establish**. It is written for readers who need to make AgentCore enforcement decisions and who need
to know which of those decisions are backed by measurement and which are not.

---

## Intended audience

| Role | What to read first |
|---|---|
| **Security architects** owning the AgentCore control plane | Chapter 1 (where a request can actually be stopped), Chapter 2 (threat cross-map), then ACG-01 through ACG-03. |
| **Platform engineers** owning execution roles, gateways and network paths | ACG-02, ACG-03, Chapter 9 (what is visible), Chapter 10 (what enforcement costs). |
| **Risk and compliance readers** who need to know what is *not* established | §0, "How to read the evidence", every control's `Not established` line, and Chapters 12–13. |
| **Reviewers and auditors** | Appendix A (seals), Appendix C (the full register), Appendix G (reproduction and its reach). |

---

## Scope and non-goals

**In scope.** One AWS Region (`us-east-1`), one account, one document under test, one SDK generation,
guardrails and policy behaviour as observed between 2026-08-09 and 2026-08-15. Region availability
(ACG-06-BP02) was probed across nine Regions by mutation.

**Explicit non-goals.**

1. **Not a product manual.** Where AWS documentation is correct, this paper cites it and moves on.
2. **Not an end-to-end safety claim.** 91 independent verdicts do not compose. No case tests two
   controls interacting. See Chapter 12, construct validity.
3. **Not a conformance statement.** No claim of the form "satisfies OWASP agentic mitigations" appears
   here, and Chapter 2 explains why such a claim would be unmeasurable in principle.
4. **Not durable.** The system under test changed during the study; `AWS-BEHAVIOR-CHANGES.md` exists
   because of it. Every verdict is dated.
5. **Not a substitute for your own threat model.** The controls are ordered by measured evidence
   strength, not by your risk.

---

## Shared responsibility for AgentCore guardrails

AWS's own scoping factor comes first: **your responsibility is determined by the AWS service that you
use.** For a managed guardrail evaluation, AWS operates the classifier, the tier behaviour and the
Region routing; you own the configuration, the thresholds, the identities that may change them, and
the decision your application takes when evaluation fails. Data sensitivity, company requirements and
applicable law then modulate that split.

This framing is service-agnostic and buys no AgentCore-specific content, so it stays short. What it
does establish is the boundary this paper measures across: **everything on the customer side of the
line was configurable by us, and therefore testable; everything on the AWS side was observable only
through its outputs.** Two findings in this paper exist purely because of that asymmetry — the absent
`ConfidenceScore` metric (§9.1) and the undocumented fail-open/fail-closed posture (Chapter 11).

---

## How to read the evidence in this paper

This is the load-bearing section. It is what separates this document from a prescriptive guardrails
guide.

### The verdict taxonomy

Five states are used. The taxonomy is **operational and ours** — a search across 26 primary sources
in software-engineering methodology found no precedent for it, so it is defined here and cited
nowhere.

| State | Meaning | What it licenses |
|---|---|---|
| **TRUE** | The sealed oracle's TRUE branch fired on live data. | The claim may be relied on, within its stated scope. |
| **FALSE** | The sealed oracle's FALSE branch fired. | The claim is refuted. An amendment to the document under test is warranted. |
| **INCONCLUSIVE** | Neither branch fired: the instrument could not decide. | **Nothing.** An INCONCLUSIVE verdict is *not* evidence against the claim it tests, and it licenses no amendment in either direction. |
| **RECORDED** | The pre-registration declared the outcome unknown; every outcome is a finding. | The observation stands as a finding; it is neither confirmation nor refutation. |
| **NOT MEASURED** | No usable instrument exists. | Nothing. Listed in Appendix F. |

The single most common misreading of a register like this one is to treat INCONCLUSIVE as a soft
FALSE. Twenty of the 91 verdicts are INCONCLUSIVE. Two document sections (§5.1 and §4.5.5 of the
document under test) are **predominantly** INCONCLUSIVE and are labelled weakly evidenced wherever
they appear.

![Figure 1 — the 91 published verdicts by state. INCONCLUSIVE is a neutral hatched grey, never a
warning colour.](results/figures/fig-01-verdict-distribution.png)

Figure 1 and figure 2 encode that rule rather than restating it: INCONCLUSIVE is drawn in a neutral
hatched grey, never in red or amber, so a reader skimming the charts is not taught the opposite of what
this section says. The hatch, not the hue, carries the distinction — which also keeps the three states
separable for a reader who cannot distinguish the colours.

![Figure 2 — verdict outcomes per section of the document under test, counted claim × case. §5-1 and
§4-5-5 are visibly dominated by the hatched
state.](results/figures/fig-02-evidence-by-section.png)

Figure 2 is the same 91 verdicts projected onto the document under test, so a reader who cares about one
section can see how well evidenced that section is before relying on it. It counts claim × case rather
than cases, which is why its total exceeds 91: one case can decide several claims, and one claim can
require several cases.

### Pre-registration

Falsifying conditions were written and hashed before any data existed:

- the **oracle registry** — sha256 over `{case_id: oracle_text}` for all 93 cases —
  `fc4216ca1eb470cc17abe77308570c6426f12f9532ec2bf9ac34759c33ee27a9`;
- the **register** `claims/triage_rules.py` — `f5d0fb1748572a68b458257cb7002e78e6b15b8a24c0c3b1e795d05040ad63fd`;
- the **claim set** `claims/triage.csv` (546 rows) — `daf23f9c124d07de30765991e8435517cd78ef046c5accc968a16849a65b677a`;
- the **analysis layer** `lib/stats.py` — `882e44edae32b1df4f5bcc5554c16331deb116c1e0b7922cf8ed2bd36c46b888`;
- the **document under test** — `4664495882263c6f07607a150c27c9537fe6d275e332088e6a784a8b9f2c20af`.

`census.py` recomputes the oracle-registry hash on every run and compares it to the declared value.
Editing an oracle after data collection is the most effective way to make a failed prediction look
like a passed one, which is why the falsifying conditions carry a hash independent of the file that
contains them.

**Where pre-registration sits in accepted practice.** In software-engineering venue terms,
pre-registration of hypotheses and design is a **Desirable** attribute for experiments, not an
Essential, and it is required by none of the standards covering benchmarking or data science. It is
adopted here voluntarily. Chapter 12 states this alongside the corresponding weakness: sealed design,
**self-run** replication.

### The reproduction gate — and what it actually delivers

No verdict amends the document under test until the case has produced the same verdict on **two
different calendar days**, compared at four levels: verdict, then the whole verdict record, then the
quantitative payload, then transient-failure detection. The gate is executable
(`check_amendment_readiness.py`) and it currently blocks seven cases (§0, item 1).

**This is repeatability, not reproduction.** In ACM's vocabulary, *Reproduced* and *Replicated* are
reserved for parties other than the authors; a second-day run of our own harness by us is
**Repeatability (same team, same setup)**, which carries no badge. What a second day did buy is
concrete: it caught DEV-P4-35, where day 1 had passed with zero slack. **No independent party has
re-run anything in this paper.**

### Two tiers of claim, and the tier decides the verb

| Tier | Controls | Permitted verb | Required companion |
|---|---|---|---|
| **Deterministic** | IAM deny, network egress deny, Cedar authorization, resource policy, SCP | *prevents* — scoped to a stated threat model | the scope statement itself |
| **Probabilistic** | content filters, PII detection, prompt-attack detection, contextual grounding | *reduces* / *detects*, with measured efficacy | a **residual risk statement** |

This is not a style rule. The document under test says Tool I/O Guardrails "**Prevent** data leakage
and indirect prompt injection from tool outputs" and "**Prevents** sensitive data leakage through tool
interactions", while its own line 199 correctly records that untagged `InvokeModel` input is not
scanned at all — measured at recall **0 [0, 0.031]**, n=120 (F5-6). A case-insensitive grep for
"residual risk" over that document returns **0**. Every control in Part II of this paper carries one.

### Inline markers

`[verified …]` a claim decided TRUE; `[corrected per …]` a claim decided FALSE, with the correction;
`(test pending …)` a claim whose case is queued; `(measured — amendment deferred …)` a decided claim
whose amendment awaits the two-day gate.

---

# Part I — What is actually enforced, and where

## Chapter 1. The enforcement surfaces of an AgentCore deployment

This chapter is not a product tour. It enumerates the places a request can be **stopped**, and for
each one states the measured evidence that it does or does not stop things.

The organising insight is itself a measurement, and it is worth leading with:

> **The surfaces a document names are not the surfaces a service has.**

Three surveyed telemetry surfaces published **no numeric guardrail score at all** (DEV-P4-01,
corroborated across all three in F7-1). The score existed — in the gateway's own application logs, at
`body.policy.guardrailFindings.<policyId>.contentFilter[].score` — and the per-arm sums of those
logged scores equal the `ConfidenceScore` metric sums exactly, on **both** measurement days:
**24.6/24.6, 0.8/0.8, 24.2/24.2** on 2026-08-12 and **24.4/24.4, 0.8/0.8, 24.8/24.8** on 2026-08-13,
`all_agree: true` with zero disagreeing dimension combinations each day (DEV-P4-27). The sums differ
between days because the scores do, and reconcile within each day — which is a stronger result than
one day's agreement, because it rules out a coincidence. A design that assumes a documented metric
exists will build an alarm on nothing.

### 1.1 The six surfaces

| # | Surface | What it can stop | Tier | Key evidence |
|---|---|---|---|---|
| 1 | **Gateway policy engine (Cedar)** | any tool invocation routed through the gateway | deterministic | F4-1…F4-5 all TRUE, n=120 each, 0 events, 99% CI [0, 0.0587] |
| 2 | **Guardrail evaluation** (`ApplyGuardrail` / `InvokeGuardrailChecks` / in-policy) | content, by classification | probabilistic | F3-1 recall 0.93 [0.9067, 0.9478] n=600; F3-4 FALSE; F3-8 FALSE |
| 3 | **IAM execution role** | direct calls that bypass surfaces 1 and 2 | deterministic | F5-1 TRUE, 0 of 120; F5-2 TRUE, 0 of 120 |
| 4 | **Network egress (VPC)** | outbound reachability from a runtime | deterministic | F5-7b INCONCLUSIVE — see §5.3 |
| 5 | **Organizational controls (SCP, permissions boundary)** | configuration changes at the account boundary | deterministic | F5-3a INCONCLUSIVE (authoring half only); F5-3b excluded (guard failed) |
| 6 | **Observability** | nothing — it *reports* | n/a | F7-1 FALSE: 10 of 15 documented metrics publish |

Surface 6 is in the table precisely because it stops nothing. A detection-only design that treats
telemetry as a control is relying on surface 6 to do surface 1's job, and Chapter 9 measures how far
that fails.

### 1.2 The single most consequential structural finding

Surfaces 1 and 2 sit on the *conversational* path. Surface 3 does not. Execution-role credentials are
**readable from inside a tool session** — `sts:GetCallerIdentity` from within the session returns the
execution role (F5-8, TRUE). That is not a vulnerability by itself; it is the premise that makes
surface 3 load-bearing rather than defence-in-depth. Any control whose enforcement lives only on the
conversational path is bypassed by anything holding those credentials.

---

## Chapter 2. Threat model and framework cross-map

### 2.1 What this chapter maps to

- **OWASP Top 10 for LLM Applications 2025** — LLM01 Prompt Injection and LLM06 Excessive Agency.
  (The 2023–24 edition numbered Excessive Agency LLM08; cite the 2025 risk page.)
- **OWASP Agentic AI — Threats and Mitigations v1.1, December 2025** — mapped **by threat ID only**,
  T1–T17, pinned by sha256 `65e3bd59f99c…0345ff`. The pin matters: OWASP's own 2026 document renames
  T4, T6 and T12, so a map by title would silently rot.
- **AWS Well-Architected Generative AI Lens** — GENSEC01–GENSEC06, in particular GENSEC02-BP01
  (guardrails) and GENSEC05-BP01 (least privilege and permissions boundaries for agentic workflows).

### 2.2 Three things this chapter must say out loud

**1. "Satisfies OWASP agentic mitigations" is a forbidden sentence.** The referent standard publishes
zero measurements: no occurrence of `benchmark`, `efficacy`, `confidence interval`, `experiment` or
`latency` anywhere in v1.1, verified under three independent PDF extractors plus a
whitespace-stripped substring pass. Conformance to an unmeasured prescriptive standard is an
assertion, not a finding. This is also this paper's clearest claim to contribution: **the standards
prescribe; we measured.**

**2. The GENSEC map is extrapolation, and is labelled as such.** `gensec05-bp01` names Bedrock
**Agents and Flows** only, and the Lens's agentic-AI page never mentions Bedrock AgentCore. There is
no AgentCore equivalent of Bedrock Agents' `confirmationState` user confirmation. Every GENSEC
cross-map in Part II is therefore **inference — ours**, not AWS attribution.

**3. Conversational-path coverage is not the whole story, and OWASP says so.** T9: a *compromised*
persistent agent identity yields "privileged, long-term API access that bypasses the agent's
conversational interface and its guardrails". T16: loose MCP/A2A specification enforcement lets
attackers "bypass guardrails entirely". T9 is phrased conditionally here because it presupposes
credential theft — and §1.2 measured the precondition for that presupposition (F5-8, TRUE). The
AgentCore-specific application of both threats is ours.

### 2.3 Coverage matrix — figure 6, and why it is blocked

The control × threat matrix is a **three-state** matrix: covered by measured evidence / covered by
inference / not established. The third state must be visually distinct from the second, and distinct
by more than hue — colour alone must not carry the distinction.

**Figure 6 is not drawn, and the reason is a sourcing gap rather than a scheduling one.** Of the
seventeen threat titles in OWASP Agentic AI v1.1, five are grounded in a source we hold (T1, T3, T9,
T15, T16) and twelve are not. Drawing seventeen columns would mean authoring twelve of them from
memory, and drawing the twelve as an empty state would misreport *our* missing source as *AgentCore's*
missing coverage — a strictly worse error than a missing figure, because a matrix reads as a finding.
`tools/whitepaper_figures.py` therefore records figure 6 as `BLOCKED` in
`results/figures/MANIFEST.json` with its reason and its closing condition (re-read the pinned v1.1 PDF,
then author `results/CROSSMAP-ACG-THREATS.json`), and writes no image. Until then the matrix is the
`Cross-map` line on every control header in Part II, which carries the same information in a less
legible form.

---

# Part II — The controls, as numbered best practices

**On the ID scheme.** Controls use the namespace **`ACG-nn-BPnn`** (AgentCore Guardrails). The
question → numbered best practice structure is the one thing about AWS best-practice pages that is
machine-verifiable across documents, so it is adopted. `GENSEC…` is deliberately **not** reused:
GENSEC does not cover AgentCore, and borrowing the prefix would imply AWS authorship.

**On the layout.** Several AWS best-practice pages include a risk-level line, implementation guidance,
numbered steps and typed resource lists. That is an observed pattern, cited per page — **not** "the
AWS best-practice template". Four separate claims that AWS maintains a fixed prose template were
refuted; the risk-level callout survived only weakly.

**The `Not established` line is mandatory on every control.** It is where the per-item "what the TRUE
verdict does not prove" prose that exists dispersed through the document under test becomes
structured.

**Chapter order follows evidence strength, not narrative.** Sections of the document under test rank
as follows (claims × case, from `tools/whitepaper_data.py`):

| Document section | Claims | Verdict mix (claim × case) | Presentation |
|---|---|---|---|
| s4-4 | 37 | TRUE 51, INCONCLUSIVE 8, RECORDED 2 | flagship |
| s10 | 25 | TRUE 24 | flagship |
| s4-1 | 30 | TRUE 30, FALSE 6, INCONCLUSIVE 5, RECORDED 2 | strong |
| s3-4 | 21 | TRUE 30, FALSE 7, INCONCLUSIVE 5 | strong |
| s6-3 | 15 | TRUE 14 | strong, narrow |
| s7-1 | 22 | **FALSE 13**, TRUE 7, INCONCLUSIVE 1 | corrections |
| s9 | 29 | **FALSE 7**, TRUE 4, INCONCLUSIVE 1 | corrections |
| **s5-1** | **27** | **INCONCLUSIVE 17**, FALSE 6, TRUE 5 | **weakly evidenced** |
| **s4-5-5** | **16** | **INCONCLUSIVE 14**, TRUE 1 | **weakly evidenced** |

---

## Chapter 3. ACG-01 — How do you establish that enforcement is actually on the request path?

### ACG-01-BP01 — Run the policy engine in ENFORCE; treat LOG_ONLY as observation only

```
Parent question  ACG-01 How do you establish that enforcement is on the request path?
Cross-map        GENSEC02-BP01 (inference) | OWASP LLM06 | T3
Tier             deterministic (Cedar authorization at the gateway)
Risk if absent   High
Evidence         F4-2 TRUE, n=120, x=0, 99% Wilson CI [0, 0.0587], us-east-1
Residual risk    LOG_ONLY is quiet on the metrics and loud in the logs: all 30 shadow evaluations
                 wrote decision: DENY / effect: FORBID / isError: true / severityText: ERROR — the
                 same four fields real denials wrote. Nothing in the record distinguishes them.
Not established  no measurement of the transition window between a mode change and its first
                 effective request; the engine-mode axis was tested at steady state only.
```

**Implementation.** Set the engine to `ENFORCE`. In `LOG_ONLY`, **nothing is blocked** even with
ACTIVE policies attached (F4-2, TRUE, 0 of 120). If you use `LOG_ONLY` to stage a policy, understand
that `policyMode` in the record reads `ENFORCE` throughout, because it is the *policy's* mode, not the
engine's — see §9.2.

### ACG-01-BP02 — Rely on Cedar default-deny; do not author explicit catch-all denies

```
Cross-map        GENSEC05-BP01 (inference) | OWASP LLM06 | T3
Tier             deterministic
Risk if absent   Medium
Evidence         F4-4 TRUE (no matching policy means deny), n=120, x=0, 99% CI [0, 0.0587]
                 F4-1 TRUE (ENFORCE with no permit policy denies all traffic), n=120, x=0
Residual risk    none measured for this mechanism
Not established  behaviour under a policy set large enough to hit any service-side evaluation limit;
                 all arms used small policy sets.
```

A bare permissive policy does not even reach a usable state: `CreatePolicy` with
`permit(principal, action, resource is AgentCore::Gateway);` and no `validationMode` reaches
`CREATE_FAILED` with an *Overly Permissive* finding (F1-3, TRUE). The validator is a control surface
in its own right.

### ACG-01-BP03 — Express exceptions as `forbid`, and expect `forbid` to win

```
Tier             deterministic
Risk if absent   Medium
Evidence         F4-5 TRUE (forbid overrides permit), n=120, x=0, 99% CI [0, 0.0587]
Residual risk    none measured
Not established  precedence among multiple conflicting forbid statements.
```

### ACG-01-BP04 — Do not rely on per-policy `enforcementMode` when the engine disagrees

```
Tier             deterministic
Risk if absent   High
Evidence         F4-3 TRUE (engine mode takes precedence over per-policy enforcementMode), n=120,
                 x=0, 99% CI [0, 0.0587]
Residual risk    a per-policy ENFORCE on a LOG_ONLY engine reads as enforcing in the configuration
                 and enforces nothing.
Not established  whether the precedence holds during a mode transition.
```

### ACG-01-BP05 — Do not build attribution on the denial response `[corrected per F4-6]`

```
Tier             deterministic (observation of a deterministic control)
Risk if absent   Medium — this is a detection and forensics gap, not an enforcement gap
Evidence         F4-6 FALSE. The sealed oracle required 403 AND a policy identifier in body or
                 headers. Measured: 120 of 120 (proportion 1, 99% Wilson CI [0.9413, 1]).
Residual risk    an operator sees that a request was denied and cannot tell which rule denied it,
                 so a bad policy and a correct policy produce identical incident evidence.
Not established  **(test pending — day-2 replication owed)**. This verdict rests on one calendar
                 day. It is reported, and no amendment to the document under test has been made.
```

**Implementation.** Recover attribution from the gateway application logs
(`body.policy…`), not from the client-visible response. `DeterminingPolicies` and
`NoDeterminingPolicies` are published metrics (F7-1 inventory) but are per-period aggregates and
cannot join a decision to a request — see §9.3.

---

## Chapter 4. ACG-02 — How do you protect the enforcement configuration itself?

The threat here is not the prompt. It is the identity that can turn enforcement off.

### ACG-02-BP01 — Deny `UpdateGateway` to every runtime identity

```
Parent question  ACG-02 How do you protect the enforcement configuration itself?
Cross-map        GENSEC05-BP01 (inference) | OWASP LLM06 | T3, T9
Tier             deterministic (IAM / resource policy)
Risk if absent   High
Evidence         F5-2 TRUE, n=120, x=0, 99% Wilson CI [0, 0.0587]. Full chain exercised: grant ->
                 LOG_ONLY set -> a previously blocked request passes -> restore -> blocking
                 re-asserted. Replicated 2026-08-12 and 2026-08-13.
Residual risk    on the mutation arm, the mode flip was accepted in 602.8 / 931.7 ms and a
                 previously blocked request was served 13.2-14.2 s later, on both days. A
                 detection-only posture has roughly that window to act, and CloudTrail delivery
                 latency was not measured.
Not established  no CloudTrail detection latency was measured — the attack side only.
```

### ACG-02-BP02 — Assume execution-role credentials are readable inside the tool session

```
Tier             deterministic (a premise, not a control)
Risk if absent   High — this is the assumption that makes BP01 necessary
Evidence         F5-8 TRUE. sts:GetCallerIdentity from inside the session returns the execution role.
                 Establishes the premise from public evidence, removing the need to cite anything
                 under NDA.
Residual risk    any code running in the tool session inherits the role's full permission set;
                 guardrails on the conversational path do not constrain it.
Not established  day-2 replication carries an undiagnosed instrument fault (a session-2 INVOKE
                 failure); the verdict stands on day 1 plus a partial day 2. See FUTURE-WORK item 3.
```

### ACG-02-BP03 — Author organizational controls, but do not assume you can verify propagation

```
Tier             deterministic
Risk if absent   Medium
Evidence         F5-3a INCONCLUSIVE. What IS established: an SCP denying the configuration-change
                 actions with a break-glass exception was accepted by CreatePolicy and attached to a
                 fresh empty OU. The propagation half needs an instrument the API does not offer
                 for this policy type.
Residual risk    you can author the control and cannot demonstrate, from the API, when it is in
                 force.
Not established  propagation time, and effective-policy evaluation at the target. INCONCLUSIVE is
                 not evidence that SCPs fail to propagate.
```

**A permissions-boundary result is deliberately absent here.** F5-3b returned TRUE but its
`every_boundary_transition_was_observed_to_settle` guard failed, so it is non-publishable and is
cited nowhere as confirmation. It appears in Appendix C with that status attached.

### ACG-02-BP04 — Account-level enforced guardrail configuration: unresolved

```
Tier             deterministic (control-plane)
Risk if absent   unknown — the measurement did not resolve
Evidence         F5-9 INCONCLUSIVE. TRUE would have meant an agent cannot opt out (omitting
                 guardrailConfiguration does not avoid evaluation); FALSE would have meant a bare
                 Converse can decline an account-level control. Measured on
                 meta.llama3-8b-instruct-v1:0 only; the arm was aborted for scope.
Not established  everything the control question asks. Do not read this as either posture.
```

If your design depends on non-bypassability at this layer, **this paper does not support it**, and it
does not contradict it either.

---

## Chapter 5. ACG-03 — How do you close paths that never reach the enforcement point?

### ACG-03-BP01 — Deny direct tool invocation to the runtime role

```
Parent question  ACG-03 How do you close paths that bypass the enforcement point?
Cross-map        GENSEC05-BP01 (inference) | OWASP LLM06 | T3, T9, T16
Tier             deterministic (IAM)
Risk if absent   High
Evidence         F5-1 TRUE (route closed), n=120, x=0, 99% Wilson CI [0, 0.0587]. Mutation control:
                 granting lambda:InvokeFunction makes the call succeed with NO AuthorizeAction span,
                 proving the deny was load-bearing rather than incidental.
Residual risk    the mutation arm is the finding: with one extra IAM grant, the tool executes and
                 the policy engine leaves no trace that it was skipped. Absence of a deny span is
                 not an alarmable event.
Not established  no equivalent test for non-Lambda target types.
```

The mutation control is what makes this control credible. A closed route with no mutation arm is
indistinguishable from a test that never reached the service.

### ACG-03-BP02 — Verify PrivateLink coverage against the API, not against a table `[corrected per F5-7a]`

```
Tier             deterministic (network)
Risk if absent   Medium
Evidence         F5-7a FALSE. describe-vpc-endpoint-services does not match the documented coverage
                 matrix, including the claimed Optimization gap. The sealed oracle fires FALSE on
                 any mismatch.
Residual risk    a design that assumes an endpoint service exists will provision a path that does
                 not terminate privately.
Not established  which direction each individual mismatch runs is recorded in the evidence file,
                 not aggregated into a claim.
```

### ACG-03-BP03 — VPC egress containment: not established

```
Tier             deterministic (network)
Risk if absent   High if you rely on it
Evidence         F5-7b INCONCLUSIVE. The oracle required a VPC-mode runtime without a NAT route to
                 fail image pull and to succeed with one. The invoke channel could not be read.
Not established  the whole control question. 124 evidence records exist and none decides it.
```

### ACG-03-BP04 — Policy attachment across target types: partially unconstructible

```
Tier             deterministic
Risk if absent   High
Evidence         F1-15 INCONCLUSIVE, and the reason is structural rather than instrumental:
                 CreateGatewayTarget refuses every http.* configuration on a gateway whose
                 protocolType is MCP, and MCP is the only member of CreateGateway's protocolType
                 enum at this API version. Evaluated on ['mcp', 'inference']; unconstructible:
                 ['http_runtime'].
Residual risk    none for the two target types that could be built — the engine attached and
                 evaluated on both.
Not established  the conjunction the document claims. A target type that cannot carry a request
                 cannot bypass evaluation of one, so this is not FALSE; but it is not the
                 conjunction the seal names, so it is not TRUE either.
```

This is the cleanest example in the study of an INCONCLUSIVE that is *informative*: the claim is not
wrong, it is currently unaskable.

---

## Chapter 6. ACG-04 — How much protection do content-based controls actually provide?

Every control in this chapter is **probabilistic**. Each therefore states measured efficacy and a
residual-risk line, and none uses the verb *prevents*.

### ACG-04-BP01 — Content filters: strong, and measured

```
Parent question  ACG-04 How much protection do content-based controls provide?
Cross-map        GENSEC02-BP01 (inference) | OWASP LLM01 | T1, T15
Tier             probabilistic
Risk if absent   High
Evidence         F3-1 TRUE  recall 0.93 [0.9067, 0.9478] (n=600, Wilson, 95%), 558 of 600, at the
                            recommended threshold; 7 operating points measured
                 F3-2 TRUE  benign FPR 0.009091 [0.001607, 0.04971] (n=110), 1 of 110
                 F3-3 TRUE  hard-negative FPR 0 [0, 0.06017] (n=60), 0 of 60
                 F3-9 TRUE  <=7 reachable operating points; Youden's J maximised at an INTERIOR
                            threshold, so the recommended threshold is defensible
Residual risk    7% of category-positive content passed at the recommended threshold, and the
                 interval's lower bound is 0.9067. At scale that is a rate, not an exception.
Not established  recall for categories or languages outside the tested corpus; see ACG-06-BP01 for
                 the language dimension, which is a different control entirely.
```

The confidence score is not continuous: every observed `ConfidenceScore` across ≥500 evaluations lies
on the discrete lattice {0, 0.2, 0.4, 0.6, 0.8, 1.0} (F1-18, TRUE). **A threshold between lattice
points is the same configuration as the lattice point below it.** Design your thresholds on the
lattice.

### ACG-04-BP02 — Do not rely on documented PII entity coverage `[corrected per F3-4]`

```
Tier             probabilistic
Risk if absent   High — and the failure is silent
Evidence         F3-4 FALSE. Per-entity recall, 31 strata, n=11 per stratum (sealed), 341 trials.
                 9 strata fail the sealed threshold despite being documented as supported:
                   DRIVER_ID                              0 of 11
                   US_PASSPORT_NUMBER                     2 of 11
                   LICENSE_PLATE                          3 of 11
                   US_BANK_ACCOUNT_NUMBER                 3 of 11
                   US_BANK_ROUTING_NUMBER                 3 of 11
                   UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER    4 of 11
                   CA_SOCIAL_INSURANCE_NUMBER             5 of 11
                   CA_HEALTH_NUMBER                       8 of 11
                   UK_NATIONAL_HEALTH_SERVICE_NUMBER      8 of 11
                 2 strata INCONCLUSIVE: PHONE (8 of 11), UK_NATIONAL_INSURANCE_NUMBER (9 of 11).
                 Pooled 0.6686 [0.617, 0.7165] (n=341) is DESCRIPTIVE ONLY — it averages over a
                 corpus composition we chose (uniform, 11 per entity) and is a statement about no
                 entity.
Residual risk    a design that lists a supported entity type in its data-protection statement is
                 making a claim this measurement does not support for 9 of 31 types. DRIVER_ID
                 detected nothing at all.
Not established  n=11 per stratum is the sealed minimum and gives wide intervals; these are
                 screening results, not precise recall estimates. No claim is made about entity
                 types outside the 31, or about non-US/UK/CA formats.
```

**Implementation.** Treat documented entity coverage as a hypothesis about your own data. Measure the
entity types you actually carry, with your own formats, before writing them into a control statement.

### ACG-04-BP03 — Prompt-attack detection is strong for two subtypes and weak for the third `[corrected per F3-8]`

```
Tier             probabilistic
Risk if absent   High
Evidence         F3-8 FALSE, strength HIGH. Per-subtype recall at the recommended threshold:
                   PROMPT_INJECTION   0.9167 [0.8534, 0.9541]  (110 of 120)
                   JAILBREAK          0.8917 [0.8234, 0.9356]  (107 of 120)
                   PROMPT_LEAKAGE     0.3611 [0.2767, 0.4550]  (39 of 108)  <- CI upper < 0.5
                 The sealed oracle fires FALSE on any subtype whose Wilson UPPER bound is below 0.5
                 while the document lists it as supported. PROMPT_LEAKAGE meets that condition.
                 Pooled 0.7356 [0.6869, 0.7792] (n=348) is descriptive only.
Residual risk    roughly two of three prompt-leakage attempts pass. If your threat model includes
                 system-prompt extraction, this filter is not the control for it.
Not established  whether a lower threshold recovers PROMPT_LEAKAGE recall at acceptable FPR; the
                 sealed design measured the recommended operating point.
```

This is the single most actionable correction in the paper: three subtypes are presented as one
capability, and they differ by a factor of 2.5 in measured recall.

### ACG-04-BP04 — Tag your input, or nothing is scanned `[verified F5-6]`

```
Tier             probabilistic (with a deterministic precondition)
Risk if absent   Critical
Evidence         F5-6 TRUE, strength HIGH. Four arms x (60 attacks + 60 benign):
                 InvokeModel untagged / tagged / Converse without guardContent / Converse with
                 guardContent on a different block. Untagged recall 0 [0, 0.03102] (n=120, x=0).
Residual risk    none for this mechanism — the finding IS the risk. Untagged input is not evaluated
                 at all, so a guardrail can be attached, configured, billed and completely inert.
Not established  whether any SDK path tags implicitly; all four arms were explicit.
```

**This is the control that most often fails in practice, and it fails silently.** A guardrail with no
input tag produces no findings, which is indistinguishable from a guardrail finding nothing wrong.

![Figure 5 — attack recall by arm with Wilson 95% intervals. The two untagged arms are pinned at
0/120; the two tagged arms are 99/120. The intervals do not
overlap.](results/figures/fig-05-detection-by-arm.png)

Figure 5 renders the two zero arms as intervals **pinned at zero**, not as absent bars. A bar chart of
recall would draw nothing there, and nothing is what a missing measurement also looks like. `0/120,
0.000 [0.000, 0.031]` is a measurement with a stated ceiling: at n=120 the data are consistent with a
true recall as high as 3.1%, and no higher. The tagged arms' intervals — 0.825 [0.747, 0.883] — do not
come close to touching it, which is the whole finding: the difference is the tag, not the guardrail.

### ACG-04-BP05 — Word filters, denied topics and contextual grounding discriminate as documented

```
Tier             probabilistic (F3-5, F3-7) / deterministic-in-effect (F3-6)
Risk if absent   Medium
Evidence         F3-6 TRUE  every listed term blocked, no unlisted near-miss blocked, 0 [0, 0.055]
                            (n=66, x=0)
                 F3-5 TRUE  in-topic recall's Wilson lower bound exceeds off-topic FPR's upper
                            bound — the intervals are DISJOINT, so the topic definition carries
                            discriminating power
                 F3-7 TRUE  ungrounded-detection rate's lower bound exceeds the grounded-pair FPR's
                            upper bound, within the documented character limits
Residual risk    word filters match exactly: they are a denylist, and a denylist is bypassed by
                 spelling. Denied topics and grounding are classifiers with real FPR.
Not established  denied-topic and grounding behaviour outside the documented character limits; and
                 the tier/language dimension (see ACG-06).
```

### ACG-04-BP06 — PII inside tool-use parameters IS handled `[corrected per F1-28 — in your favour]`

```
Tier             probabilistic
Risk if absent   n/a — this corrects a pessimistic claim
Evidence         F1-28 FALSE. The document claims PII is NOT detected inside tool_use output
                 parameters. Measured: the identical payload was handled on EVERY trial of the
                 placement arm (tool_result_json) as well as of the control arm — the sealed FALSE
                 branch is "both placements are handled".
                 Controls fired on every trial (text_applyguardrail 3 of 3, text_converse 3 of 3).
Residual risk    n=6 placement trials. This refutes a categorical claim (which one counterexample
                 does) but supports no efficacy estimate.
Not established  any recall figure for this placement. The case is explicit that it makes no power
                 claim, and that half the pre-registered method was unexecutable.
```

A refutation of "never" needs one counterexample. A claim that this placement is *reliably* covered
would need the measurement this case did not perform.

### ACG-04-BP07 — Indirect prompt injection via tool responses: not established

```
Tier             probabilistic
Risk if absent   High if you rely on it
Evidence         F5-5 INCONCLUSIVE. Not measured: echo_round_trip_observed,
                 probe_policy_became_active. The mutation arm therefore could not demonstrate the
                 suppressOutput policy was load-bearing.
Not established  the entire control question, including whether suppressOutput has any effect on
                 injected tool responses.
```

Compare with the document under test, which says Tool I/O Guardrails "Prevent … indirect prompt
injection from tool outputs". **The case designed to measure that returned INCONCLUSIVE.** That
sentence is unsupported here — which is not the same as refuted.

---

## Chapter 7. ACG-05 — How repeatable is an enforcement decision?

Repeatability is a security property. A control that blocks 999 of 1,000 identical requests is not a
control; it is a sampler.

### ACG-05-BP01 — Cedar decisions are repeatable `[verified F2-1]`

```
Parent question  ACG-05 How repeatable is an enforcement decision?
Cross-map        GENSEC02-BP01 (inference) | T3
Tier             deterministic
Risk if absent   High
Evidence         F2-1 TRUE. 0 decision flips, 0 [0, 0.006061] (n=630, Wilson, 95%) — n exceeded the
                 sealed 300. H0 was p_flip = 0 and one counterexample would have sufficed.
Residual risk    none measured for pure-Cedar policies.
Not established  repeatability of a policy containing a guardrail term; that is BP02.
```

### ACG-05-BP02 — Guardrail scores were observed to be degenerate, not noisy `[corrected per F2-2, F2-5]`

```
Tier             probabilistic (measured deterministic in this configuration)
Risk if absent   Medium — the correction removes a worry rather than adding one
Evidence         F2-2 FALSE (n=300): the oracle called >=2 distinct scores for one fixed input
                 "non-deterministic"; exactly one value appeared, which is the sealed FALSE branch.
                 F2-5 FALSE (n=300): all 300 identical ApplyGuardrail calls were byte-identical in
                 verdict and score.
Residual risk    "degenerate at n=300 for these inputs" is not "deterministic for all inputs". A
                 hosted classifier can change behaviour between model revisions (see BP04).
Not established  score stability across model or tier revisions; the calls were within one window.
```

### ACG-05-BP03 — Do not model flip rate as a function of threshold placement `[corrected per F2-4]`

```
Tier             analytic
Risk if absent   Low — this corrects an analytical claim, not a control
Evidence         F2-4 FALSE: flip rate is insensitive to tau. The predicted 2p(1-p) behaviour, with
                 flips rising when tau sits inside the score support and falling to ~0 outside it,
                 did not appear.
                 F2-3 INCONCLUSIVE: whether the decision is a deterministic function of the score
                 could not be decided.
Not established  the score -> decision function. F2-3's INCONCLUSIVE is a real gap: BP02 shows the
                 SCORE is stable, and F2-3 would have shown the MAPPING is stable. It does not.
```

**Together these three are the honest version of a determinism story.** The score was stable; the
mapping from score to decision was not established; and the analytical model of threshold-induced
flipping was refuted. A design that needs decision stability should assert it by measurement on its
own traffic.

### ACG-05-BP04 — Vendor drift: instrumented, not yet decided

```
Tier             external
Risk if absent   Medium
Evidence         F3-11 INCONCLUSIVE. The oracle compares a +7d or +30d re-run against baseline by
                 paired bootstrap CI. The calendar gate has not passed: re-runs are due 2026-08-18
                 and 2026-09-10.
Not established  whether guardrail behaviour drifts under AWS auto-updates. The instrument exists
                 and the answer does not.
```

`AWS-BEHAVIOR-CHANGES.md` exists because the system under test changed during the study, so the
question is not hypothetical. It is simply not yet answered.

---

## Chapter 8. ACG-06 — How do you choose tier and Region?

### ACG-06-BP01 — Classic tier gives no protection outside EN/FR/ES; Standard tier does `[verified F8-2, F8-3]`

```
Parent question  ACG-06 How do you choose guardrail tier and Region?
Cross-map        GENSEC02-BP01 (inference) | OWASP LLM01 | T1
Tier             probabilistic
Risk if absent   Critical for any non-EN/FR/ES workload
Evidence         F8-2 TRUE. CLASSIC tier, pooled over zh-TW / zh-CN / ja / ko: 0 of 216 attacks
                 detected, 0 of 24 clean items flagged. Detection is indistinguishable from the
                 benign rate — i.e. no protection. On the supported half, CLASSIC recall is high
                 and the intervals are disjoint from FPR for all three of en/fr/es
                 (en 47 of 54, recall 0.8704 [0.7558, 0.9358]; es 32 of 54).
                 F8-3 TRUE. STANDARD vs CLASSIC, McNemar paired on the same corpus:
                   zh-CN  53 standard-only, 0 classic-only, n=54 pairs, p = 9.1e-13
                   ko     51 standard-only, 0 classic-only, n=54 pairs, p = 2.5e-12
                   zh-TW  51 standard-only, 0 classic-only, n=54 pairs, p = 2.5e-12
                   ja     50 standard-only, 0 classic-only, n=54 pairs, p = 4.2e-12
                   pooled 205 standard-only, 0 classic-only, n=216 pairs, p = 4.6e-46
Residual risk    STANDARD improves on CLASSIC by a very large margin, but "standard_only = 205 of
                 216" is still 11 pairs neither tier caught.
Not established  languages outside {en, fr, es, zh-TW, zh-CN, ja, ko}; and recall for the same
                 corpus at other thresholds.
```

**This is the paper's largest measured effect and the clearest single design decision in it.** If any
non-EN/FR/ES content reaches a Classic-tier guardrail, that guardrail is decoration. Zero of 216.

### ACG-06-BP02 — Establish Region availability by mutation, never by `List*` `[corrected per F8-1]`

```
Tier             deterministic (control-plane)
Risk if absent   High
Evidence         F8-1 FALSE. The document lists exactly 5 Regions. Policy-engine CREATION succeeded
                 in 4 Regions the list excludes: us-west-2, eu-central-1, sa-east-1, ap-south-1
                 (all HTTP-accepted, engine created). Decided by mutations because a control-plane
                 List* returns 200 in a Region where nothing exists — "a 200 about nothing", which
                 is the sealed oracle's own second sentence.
Residual risk    availability is wider than documented, which sounds harmless and is not: a Region
                 that accepts a creation is a Region in which an operator can create an
                 unmonitored enforcement point.
Not established  whether creation succeeding implies the data plane enforces there. Only the
                 mutation was measured.
```

### ACG-06-BP03 — Prompt-leakage detection is not Standard-tier-only `[corrected per F8-4]`

```
Tier             probabilistic
Risk if absent   Low for security, High for planning accuracy
Evidence         F8-4 FALSE. The oracle required PROMPT_LEAKAGE to be rejected or inert on CLASSIC
                 and functional on STANDARD; it works on CLASSIC. The CLASSIC half is exact and
                 byte-identical across both measurement days.
Residual risk    do not confuse "available on CLASSIC" with "effective": ACG-04-BP03 measured
                 prompt-leakage recall at 0.3611 [0.2767, 0.455]. It is available on both tiers and
                 weak on the tier measured.
Not established  per-tier prompt-leakage recall. F8-4 settled availability; F3-8 measured efficacy
                 on one tier. Nobody measured the cross.
```

### ACG-06-BP04 — Denied-topic length limits: **contested, decision pending**

```
Tier             deterministic (API validation)
Risk if absent   Low
Evidence         F8-5 FALSE on the sealed boundary oracle, and the erratum is OPEN. The rejection
                 the document's correction cites was a TIER precondition error ("Can't configure
                 guardrail policy tier. Enable cross-Region inference..."), not a length-constraint
                 error. Length is validated BEFORE the tier gate, so the two measurement days
                 together SUPPORT the documented 1,000-character limit — the opposite of what the
                 document's current correction publishes.
Not established  the corrected limit itself. A $0 re-test with crossRegionConfig and backoff on a
                 third UTC day is designed and not yet run. Until it runs, this paper restates
                 neither reading. See FUTURE-WORK item 27.
```

This control is included **because** it is contested. Removing it would hide the one place where the
study's own published correction is under revision.

### ACG-06-BP05 — Standard-tier cross-Region inference stayed in-geography `[verified F8-6]`

```
Tier             deterministic (data residency)
Risk if absent   High where residency is a legal requirement
Evidence         F8-6 TRUE. All inference for a US-Region request was served from US Regions per
                 CloudTrail and response metadata; no out-of-geography Region appeared.
Residual risk    "in-geography" is not "in-Region". If your requirement is Region-pinned rather
                 than geography-pinned, Standard tier's cross-Region inference does not meet it.
Not established  behaviour for non-US geographies; only the US case was measured.
```

### ACG-06-BP06 — Word-filter language support: not established

```
Evidence         F8-7 INCONCLUSIVE, and F1-26 INCONCLUSIVE for the same underlying reason:
                 CreateGuardrail refused the word policy on both CLASSIC and STANDARD, and the
                 supported-language-only CONTROL was refused too — so the refusal is not
                 attributable to the non-EN/FR/ES words. A rejection of unknown cause establishes
                 neither disjunct.
Not established  whether word filters are EN/FR/ES-only. The control arm failing is what makes this
                 INCONCLUSIVE rather than FALSE, and that distinction is the point.
```

### ACG-06-BP07 — Automated Reasoning: en-US and detect-only, but streaming is NOT rejected `[corrected per F1-14]`

```
Evidence         F8-8 TRUE   Automated Reasoning is en-US only and detect-only.
                 F1-14 FALSE for the three-part conjunction that ADDS "no streaming":
                   ConverseStream accepts guardrailConfig.guardrailIdentifier and models 132
                   Automated-Reasoning paths under stream.metadata.trace.guardrail.*, the same
                   GuardrailTraceAssessment shape Converse carries 239 of. The SDK does not reject
                   streaming; it models it.
Residual risk    a design that assumes streaming cannot carry an Automated Reasoning policy will
                 not notice one attached to a streaming operation.
Not established  whether the streaming assessment is POPULATED at runtime. F1-14 is an SDK-shape
                 finding: the slot exists. Whether it fills was not measured.
```

The pair F8-8/F1-14 is worth studying as a method example: the same subject yields TRUE for the
two-part claim and FALSE for the three-part one. Conjunctions must be sealed at the granularity you
intend to defend.

---

# Part III — Operating it

## Chapter 9. Observability and detection

### 9.1 Five of fifteen documented metrics do not publish `[corrected per F7-1]`

The document under test names policy metrics; once `/`-joined table cells are split into individual
metric names, **15** are named. Measured: **10 publish**, 13 were scored (2 were excluded as
NOT_EXERCISED because their publishing condition is an error or a deliberately broken policy — a
deviation, DEV-P4-03, whose bias runs *towards* the document under test and is labelled for that
reason).

**Three metrics were exercised and never appeared:** `ConfidenceScore`, `ConfidenceThreshold`,
`TemporalLatency`.

Two documented *dimensions* also do not publish: `Category` and `Filter`. And `GuardrailLatency`,
documented as carrying a `ToolName` dimension, publishes under `[OperationName, TargetResource]` — it
has no `ToolName`. The sibling control that makes this a property of the metric rather than of our
traffic: `AllowDecisions` is published by the same operation on the same requests and **does** carry
`ToolName`.

**Design consequence.** Every alarm in a guardrails runbook must be built against the *published*
inventory, not the documented one. Appendix B carries the full 31-name published inventory.

### 9.2 LOG_ONLY is quiet on the metrics and loud in the logs

All 30 shadow evaluations wrote `decision: DENY`, `effect: FORBID`, `isError: true` and
`severityText: ERROR` — the same four fields real denials wrote. `policyMode` read `ENFORCE` in both,
because it is the *policy's* mode, not the engine's. **Nothing in the record distinguishes a shadow
evaluation from a real block.** If you stage policies in LOG_ONLY, you must carry the engine mode
out-of-band or your incident review will count shadow denials as blocks.

### 9.3 The precision workflow in the document is not executable `[corrected per F3-10]`

The document's §7.1 gives a workflow for computing detection precision from LOG_ONLY telemetry. It
cannot be followed: **no score series holds one request per datapoint**, so the per-request
score ↔ label join the confusion matrix needs is destroyed by 1-minute aggregation (F3-10, FALSE).

A reader following those steps produces no precision figure at all.

### 9.4 The censoring trap, and why a calibration window can only tighten

Requests scoring below the configured threshold publish **no score at all**: 61 of 122 evaluations
produced a datapoint, and **all 61 that published were positives**. The distribution you can observe
is truncated at your own threshold.

The operational consequence is asymmetric and important: **a closed calibration window can justify
raising a threshold and can never justify lowering one**, because the evidence you would need to lower
it is exactly the evidence the current threshold suppresses.

![Figure 4 — the observed score lattice is censored below the configured threshold. Two lattice
points, 0.0 and 0.2, are hatched full-height rather than drawn as bars, because a censored point has
no count to show.](results/figures/fig-04-censored-score-lattice.png)

Figure 4 renders the censoring rather than the sample. The two unobservable lattice points are drawn
as full-height hatched spans, deliberately not as bars: an earlier draft drew them as bars of height
44, which a reader could read straight off the y-axis as a count and compare against the real 48 at
0.8. A censored point has no count.

### 9.5 Cross-instrument agreement, when it exists, is worth stating

Where two instruments could be compared, they agreed. The per-arm sums of logged
`contentFilter[].score` equal the `ConfidenceScore` metric sums exactly on both days — **24.6/0.8/24.2
on 2026-08-12 and 24.4/0.8/24.8 on 2026-08-13**, each day's logged sum matching that day's metric sum
(DEV-P4-27, figure 8). Reaching that agreement on day 2 required repairing a reader-side
bucket-attribution defect (DEV-P4-35) that day 1's arrangement of the clock had concealed: a metric
datapoint is bucketed by the service's own emit time, which follows the log event by up to the publish
lag, so a bucket set taken from the log rows alone under-counted the metric by exactly one sample.
**The agreement is therefore a repaired result, not a lucky one.** For F6-1/F6-4, span-derived and CloudWatch-derived
distributions agreed on the verdict-relevant question (CloudWatch p50 397.7 ms vs span-derived
401 ms; `agree: true`), under a rule **pre-committed before any number was seen**: if the two
instruments disagreed about whether the distribution lay inside the band, the verdict would be
INCONCLUSIVE.

![Figure 8 — paired sums of the logged score and the ConfidenceScore metric, over the same buckets,
for three arms on each of two measurement days. Every pair is
equal.](results/figures/fig-08-metric-log-agreement.png)

Stating the agreement rule before the data is what makes the agreement meaningful. Figure 8 plots both
days deliberately: one day's exact agreement is indistinguishable from a coincidence, and the sums
differ *between* days (because the scores do) while reconciling *within* each day. That pattern is the
result — not the equality of any single pair.

### 9.6 What observability does not give you

- **No attribution on the denial response** (ACG-01-BP05, F4-6 FALSE, 120 of 120).
- **No per-request join** from metrics (F3-10 FALSE).
- **No numeric guardrail score on three surveyed surfaces** (DEV-P4-01, corroborated in F7-1).
- **Metric publish lag sets a floor on every alarm** (F7-6, TRUE), and metrics are batched at
  1-minute intervals (F7-7, TRUE). No alarm in a guardrails runbook can be faster than that floor.
- **Tracing must be explicitly enabled or spans are absent** (F7-5, TRUE). A design that assumes
  spans exist by default has no forensic record.

What it does give you: gateway metrics under `AWS/Bedrock-AgentCore` (F7-2, TRUE), guardrail metrics
under `AWS/Bedrock/Guardrails` (F7-3, TRUE), and policy spans in `aws/spans` with the documented
operations (F7-4, TRUE).

---

## Chapter 10. Latency and the cost of enforcement

### 10.1 The measured hops against the document's stated bands

All figures are p50/p90/p99 at n=1,000 with order-statistic confidence intervals; the F6-1/F6-4
figures are baseline-subtracted against a paired no-policy arm. **Six of the nine cases in this family
are FALSE**, and four of those are the enforcement-latency bands.

| Case | Document band | Measured p50 [95% CI] | p90 | p99 | Verdict |
|---|---|---|---|---|---|
| F6-1 / F6-4 (gateway guardrail evaluation) | 50–200 ms | **401 [396, 406]** | 528.1 | 779.1 | **FALSE** |
| F6-2 (Bedrock input guardrail) | 100–500 ms | 231 [226, 235] | 374.2 | 622.0 | **FALSE** — p99 outside |
| F6-3 (Cedar policy) | 5–50 ms | **55 [54, 56]** | 70.0 | 94.0 | **FALSE** |
| F6-5 (output guardrail) | 100–500 ms | 234 [228, 238] | 366.1 | 662.2 | **FALSE** — p99 outside |
| F6-6 (end-to-end total) | ~800 ms – 31 s+ | 1483 [1474, 1491] | 1721.6 | 2107.2 | **TRUE** |

The oracles are `BAND_CONTAINS` over the **p50–p99 band**, not over the median alone. F6-2 and F6-5
have medians inside their bands and p99s outside them, and that is the correct thing to fail on: an
enforcement budget that holds at the median and breaks at the tail is a budget that breaks under load.

![Figure 3 — measured p50–p99 against each documented band, log scale. The grey block is the band the
document states; the coloured segment is what was measured. F6-2 and F6-5 start inside their bands and
end outside them.](results/figures/fig-03-latency-vs-bands.png)

Figure 3 is drawn on a log axis for a reason that matters to the reading: the four bands span 5 ms to
31 s, and on a linear axis the Cedar band (5–50 ms) collapses to a hairline next to the end-to-end one.
It also shows why F6-6's TRUE is the weak verdict of the five — its band is so wide that the measured
segment sits comfortably inside it wherever it fell.

**Two honesty notes that belong with this table, not in an appendix.**

1. **F6-1 and F6-4 are one measurement, not two.** The document's Hop #1 (gateway input guardrail) and
   Hop #5 (per-tool-call guardrail) name the same enforcement point, separated only by *when*
   evaluation happens, and `GuardrailLatency` carries no dimension separating an input-side evaluation
   from a per-tool one. Both rows claim the same 50–200 ms band, so one measurement decides both. This
   is recorded in the verdict file as `hop_conflation` rather than being presented as independent
   corroboration.
2. **F6-6's TRUE is weaker than it looks.** The document writes an open-ended upper bound
   ("~800 ms – 31 s+"), so **no measured value could exceed it**; only the floor was falsifiable. A
   band with an open end is not a prediction. The measured 1,483 ms p50 is the useful number here, not
   the verdict.

### 10.2 The decomposition model survives; the per-tool-call slope does not

- **F6-7 TRUE.** The additivity model (`Duration = GuardrailLatency + TargetExecutionTime + ε`) holds:
  the residual ε is non-negative within its CI, **[258.8, 273.0] ms**. A significantly negative
  residual would have meant the hops overlap and would have falsified the decomposition behind three
  of the document's sections at once. It did not.
  *But* the residual is 259–273 ms of **unattributed** time at the median, so the model is
  structurally sound and not tight.
- **F6-8 FALSE.** The per-additional-tool-invocation slope's bootstrap CI is **[838.7, 862.7] ms**,
  disjoint from the documented 165–750 ms — high by roughly 100 ms at the lower end and by more than
  the width of the documented range at the upper. **(test pending — day-2 replication owed, and this
  case must run on the laptop rather than the runner, per DEV-P4-37.)**

### 10.3 Early blocking is cheaper, and by how much

**F6-9 TRUE.** Blocked-request latency is significantly below passed-request latency; the
Hodges-Lehmann shift is **[30.2, 57.0] ms** (95% CI, Wilcoxon). Blocking at the first enforcement
point saves that much downstream latency — a real effect, and a small one relative to the 401 ms the
gateway evaluation itself costs. **Do not design for early blocking as a performance optimisation.**
Design for it as a containment property, and take the 30–57 ms as a bonus.

### 10.4 Cost

- **F10-2 TRUE.** Guardrail billing is per text unit; `TextUnitCount` scales with content length as
  documented and matches the billed quantity.
- **F10-3 FALSE.** Input tagging does **not** reduce text units billed: tagged and untagged were
  **identical on every usable pair**, which is the sealed FALSE branch. Tagging is required for
  detection to happen at all (ACG-04-BP04) and buys nothing on cost.
- **F10-1 NOT MEASURED.** Whether an input block avoids the model inference charge while an output
  block does not is unresolved. Cost Explorer's daily granularity cannot supply the per-request delta
  the sealed oracle requires. **This is a real gap in cost modelling and it is listed in Appendix F
  rather than estimated.**

The whole measurement programme behind this paper cost **under $2.15** in AWS charges against a
pre-registered ceiling of $95.

---

## Chapter 11. Failure posture and change control

### 11.1 What AWS does not document, and what we observed

AWS does not document fail-open versus fail-closed behaviour for guardrail errors during model
invocation. The document under test states this correctly, and therefore correctly concludes that the
**application owns the decision**.

Two cases interrogated it directly, both pre-registered as `RECORDED` — outcome declared unknown, so
that every result would be a finding and none a confirmation:

- **F5-4b RECORDED — FAIL-CLOSED, for one specific failure mode.** With
  `bedrock:InvokeGuardrailChecks` removed from the gateway execution role, the engine denied both the
  violating request and the benign one:
  `pre_violating DENY, pre_benign ALLOW → post_violating DENY, post_benign DENY → restored_violating DENY`.
  It **stopped discriminating by content**, which is what an evaluation that cannot run should look
  like. The document's "fail-secure" label is corroborated **for the missing-permission mode
  specifically**.
- **F5-4a RECORDED.** A policy referencing a nonexistent context path: the outcome was declared
  unknown in advance and the observation stands as a finding, neither confirming nor refuting the
  document.

**The mode that matters most is untestable.** F9-1 — whether policy-evaluation *timeout* yields
automatic DENY — is closed as **untestable by its own sealed oracle**: AgentCore exposes no
fault-injection surface for policy evaluation. So "fail-secure" is corroborated for a permission
failure and **unknown for a timeout**, and those are different failure modes with different
probabilities in production.

### 11.2 Unevaluable policies do announce themselves

**F9-2 TRUE.** `MismatchErrors` and `PolicyMismatch` fire on unevaluable policies. That is a genuine
detection surface — and note it is a *detection* surface, so §9.6's publish-lag floor applies to any
alarm built on it.

### 11.3 Throttling: the question was never put

**F9-3 INCONCLUSIVE**, and the reason is worth reading in full because it is a model of what an honest
INCONCLUSIVE looks like:

> 480 of 480 burst responses carried a real verdict, 0 were observable failures, 0 were throttles, and
> 0 were silent passes — at an **achieved 182.2 rps against a documented 100 rps ceiling** (pool 96,
> p50 latency 262 ms). A run that was never throttled proves nothing about throttling: "0 silent
> passes" is vacuously true of a question that was never put. The rate mutation did not invert
> (control throttles 0, burst throttles 0), so both arms behaved identically.

The tempting write-up — "we sent 480 requests at 1.8× the documented ceiling and saw zero silent
passes" — would be true, impressive, and worthless. The verdict is INCONCLUSIVE.

### 11.4 Change control: the interval you have to detect a mode flip

From ACG-02-BP01's mutation arm: the enforcement-mode flip was **accepted in 602.8 / 931.7 ms** and a
previously blocked request was **served 13.2–14.2 s later**, on both measurement days. That interval
is what a detection-only posture has to work with, and **CloudTrail detection latency was not
measured**, so the paper cannot tell you whether it fits.

![Figure 7 — panel A: each mode flip, timed from its own control-plane call, on both measurement days.
Panel B: the same case's IAM grant revocation, on a scale twenty-two times
wider.](results/figures/fig-07-mode-flip-timeline.png)

Figure 7 draws each interval from **its own** control-plane call, because F5-2 records
`seconds_until_blocked_request_was_allowed` from the LOG_ONLY flip and
`seconds_until_blocking_returned` from the ENFORCE restore, and **records no clock shared between
them**. There is no single timeline to draw; a chart that supplied one would be inventing the gap.

Panel B adds a second interval from the same case that belongs beside the first, because it is the same
phenomenon at twenty-two times the scale. When the runtime role's gateway grant is **revoked**, the
first call is not denied for **305.8 s (day 2) / 325.0 s (day 1)**, and three consecutive denials take
**326.4 s / 345.6 s**. Every one of the 20 later attempts was denied
(`n_that_were_still_authorized: 0`). So the same asymmetry runs in both directions: **a permission you
grant and a permission you take away both take effect on the data plane later than the API call that
changed them returns.** F5-2's own record is explicit that the strict form of this — every
post-revocation attempt denied immediately — "asks IAM for a guarantee it does not offer on this
timescale", and F5-1 measured the same asymmetry on `lambda:Invoke`.

The design consequence is the same in both panels, and it is not "wait longer": **if the flip matters
to you, deny it at the policy boundary (ACG-02-BP01). Do not alarm on it.** An alarm fires after the
interval; a denial removes the interval.

---

# Part IV — Limits

## Chapter 12. Threats to validity

Four named categories — **construct, conclusion, internal, external** — with every threat naming the
**specific result it threatens**. A validity section that lists threats without linking them to
results is a known antipattern, and it is precisely the defect the dispersed per-item prose in the
document under test has today.

**Attribution, stated first because it is the most likely citation error a reviewer would catch.** The
four-part structure is attributed to the **Cook-Campbell / Wohlin-Runeson** lineage and adopted
**voluntarily**. It is *not* claimed as a binding methodological Essential: the standard that makes
that four-part list Essential is scoped to **experiments with human participants** and explicitly
redirects other work elsewhere. A hosted-guardrail latency-and-efficacy study is a benchmarking /
data-science study, and the applicable benchmarking standard requires only **construct** validity.
Wohlin et al. (2012) is cited for chapter structure and for the fact that *Presentation and Package*
is a distinct methodological phase (ch. 11, pp. 153–157); its prose is **not** quoted here, because
only Crossref/OpenAlex metadata was verifiable — the publisher redirects to an identity provider.

For context: a case-insensitive grep for "threats to validity" and for "construct validity" over the
document under test both return **0**.

### 12.1 Construct validity

**Coverage is not conjunction.** 91 independent verdicts do not compose into an end-to-end safety
claim. **No case tests two controls interacting.** ACG-01 measures that the engine denies; ACG-04
measures that a filter detects; nothing measures a request that must pass both. *Threatens:* any
aggregate reading of the verdict count, and every "defence in depth" reading of Chapter 1's table.
This is the one category the applicable benchmarking standard actually requires, and it gets the most
space here for that reason.

**57 of 546 claims are prescriptions, not propositions.** 10.4% of the triaged claims are
best-practice recommendations, checklist steps, design principles and decision-matrix
recommendations. The apparatus cannot decide them **in principle** — a prescription has no truth
value. *Threatens:* the implication that 91 verdicts validate the document. The parts of a guardrails
document that tell you what to do are exactly the parts an oracle cannot decide, and this is the same
structural limitation Chapter 2 found in OWASP's own standard, which makes it a shared problem rather
than a local failure.

**Pooled proportions describe corpora we chose.** F3-4's 0.6686 and F3-8's 0.7356 are marked
descriptive-only in their own verdict files, because they average over compositions we selected
(uniform, 11 per entity; 3 subtypes). *Threatens:* any citation of those pooled figures as service
properties.

### 12.2 Conclusion validity

**Single-day measurement on seven cases.** Seven cases owe a replication and the gate visibly blocks
them. *Threatens:* Chapter 10's entire latency table (F6-1 through F6-5, F6-8) and ACG-01-BP05
(F4-6). This is the largest open conclusion-validity threat in the paper, and it is concentrated in
one chapter.

**Repeatability is not reproduction.** Our second-day runs are our own harness, run by us — ACM's
**Repeatability (same team, same setup)**, which carries no badge; *Reproduced* and *Replicated* are
reserved for non-authors. **No independent party has re-run anything here.** What a second day did
buy: it caught DEV-P4-35, where day 1 passed with zero slack. *Threatens:* the
`reproduction_before_amendment` gate's own name.

**Small n on categorical refutations.** F1-28's refutation rests on 6 placement trials and 3 control
trials; the case explicitly makes no power claim. *Threatens:* any efficacy reading of ACG-04-BP06.

**Wide intervals on stratified screening.** n=11 per stratum in F3-4 was the sealed minimum.
`DRIVER_ID` at 0 of 11 is a strong signal; `CA_HEALTH_NUMBER` at 8 of 11 is a weak one, and both are
counted as FALSE strata by the same rule. *Threatens:* the precision, not the direction, of §6's PII
finding.

### 12.3 Internal validity

**Instrument defects were found and repaired mid-study.** Six in the Cedar resource-scope repair
alone (`FINDING-P1-CEDAR-RESOURCE-SCOPE.md`), plus F5-7b's unreadable invoke channel and F5-8's
undiagnosed `session 2: INVOKE FAILED`. *Threatens:* any case whose earlier rounds were superseded —
the superseded rounds remain in the evidence archive, and the published verdict is the post-repair
one.

**F5-3b is TRUE and non-publishable.** Its `every_boundary_transition_was_observed_to_settle` guard
failed. It must never be cited as confirmation. *Threatens:* a reader who reads TRUE out of the
register without reading the guard, which is why the guard status is a column in Appendix C.

**A producer can score a transient AWS error as an observation, and one published verdict did.** One
`ThrottlingException` probe was counted in F8-5's day-2 comparison. *Threatens:* F8-5, which is
already contested for an independent reason (ACG-06-BP04).

**F2-3 and F2-4 have no evidence records carrying their own `case_id`.** Their chain runs through a
sibling case's records. *Threatens:* the traceability claim in Appendix G, for those two cases only.

**An evidence-promotion step was missing from the tooling.** 607 records sat staged and unmerged for
a day, which made the study's only executable statement of its own two-day rule report failures for
two findings whose records existed the whole time. Repaired 2026-08-15 by `runner/merge_evidence.py`,
with the diagnosis pinned as a test. *Threatens:* nothing in the verdicts — but it is exactly the
class of defect that would threaten them silently, so it is recorded here rather than in a changelog.

### 12.4 External validity

**A hosted moving target.** `AWS-BEHAVIOR-CHANGES.md` exists because the system under test changed
during the study. Every verdict is dated. *Threatens:* **all 91.**

**One Region, one account, one document, one SDK generation.** ACG-06-BP02 is the only control probed
across Regions, and only for a control-plane mutation. *Threatens:* every latency figure (Region-local
network conditions), every availability statement, and any behaviour that varies by account
configuration.

**One model in several arms.** F5-9 measured `meta.llama3-8b-instruct-v1:0` only. *Threatens:*
ACG-02-BP04's already-INCONCLUSIVE state, further.

### 12.5 The rigor claim, phrased as a comparison

This study sealed its oracles, decision rules and exclusion rules by sha256 before any data existed.
In software-engineering venue terms that is a **Desirable** attribute for experiments, not an
Essential, and it is required **zero** times by the eight standards covering benchmarking and data
science. Set against that: **the replication was self-run.** Sealed design, self-run replication —
both halves in one sentence, or neither.

---

## Chapter 13. What this paper does not establish

The ledger, quantified. None of these is hedging; each is a number.

1. **20 INCONCLUSIVE of 91 published verdicts (22%).** An INCONCLUSIVE licenses no amendment and is
   not evidence against the claim it tests. Two document sections are predominantly INCONCLUSIVE:
   **s5-1 (17 of 28 claim×case outcomes)** and **s4-5-5 (14 of 15)**. Any reader relying on those
   sections is relying on unmeasured guidance, and this paper labels them so wherever they appear.
2. **1 NOT MEASURED** — F10-1, the billing asymmetry. Cost Explorer's daily granularity cannot supply
   the required delta.
3. **1 UNTESTABLE by its own sealed oracle** — F9-1, policy-evaluation timeout. No fault-injection
   surface exists. The failure mode most likely to occur in production is the one that cannot be
   tested.
4. **57 prescriptions (10.4% of 546 claims) were never measurable in principle.** A prescription has
   no truth value. The parts of a guardrails document that tell you what to do are precisely the parts
   an oracle cannot decide — and OWASP's agentic standard has the same property (Chapter 2), so this
   is structural rather than a local failure.
5. **7 cases owe a day-2 replication**, concentrated in Chapter 10 (F6-1…F6-5, F6-8) plus F4-6.
6. **1 published correction is contested** — F8-5 / §3.4 (ACG-06-BP04). The re-test is designed, costs
   $0, and has not run.
7. **1 TRUE verdict is non-publishable** — F5-3b, guard failure.
8. **1 of 8 figures cannot be drawn** — figure 6, the control × threat matrix, because 12 of the 17
   OWASP Agentic v1.1 threat titles are not grounded in a source we hold. The other seven are drawn
   and machine-checked; that one is blocked in the manifest with its closing condition.
9. **0 independent replications.** See Chapter 12.
10. **No control interaction was measured at all.** Not one case.

The full 36-item deficiency register, tiered by severity, is `FUTURE-WORK.md`. Its Tier 1 —
"the paper is wrong or self-contradictory until these are fixed" — currently holds 6 items (1, 2, 3,
19, 27, 32), of which the prevention/detection verb contradiction (item 1), the F8-5 erratum
(item 27) and the F6 tail-decisiveness finding (item 32) are the three that change published text.

---

# Conclusion

A guardrails design document is a set of claims about how a service behaves. Treated that way, this
one turned out to be **half right in a measurable sense**: 46 of 92 verdict-eligible propositions held
against live service behaviour, 23 were refuted, 20 could not be decided by the instruments available,
and 2 recorded outcomes that had been declared unknown in advance.

The refutations that change design decisions are few and specific. Classic-tier guardrails give **zero
protection** on 216 non-EN/FR/ES attack items. Documented PII entity coverage fails its own threshold
for **9 of 31** entity types. Prompt-leakage recall is **0.3611 [0.2767, 0.455]** where sibling
subtypes reach 0.89–0.92. Untagged input is **not evaluated at all** — recall 0 [0, 0.031]. Four
enforcement-latency hops lie outside their stated bands, the gateway evaluation by a factor of two.
And a denial identifies **no policy** in 120 of 120 observations, so attribution must come from logs
that are not the response.

The method matters more than any single result. Sealing the falsifying conditions before collecting
data is what makes 23 refutations publishable rather than negotiable; separating INCONCLUSIVE from
FALSE is what keeps 20 undecided cases from being quietly counted as either; and requiring every
control to state what it does **not** establish is what keeps a measured document from becoming a
prescriptive one.

The honest summary of this first edition is in §0 and Chapter 13: seven replications owed, one
correction contested, one figure blocked on a source we do not hold, and no independent party has
re-run any of it.

---

# Contributors

Contributors to this document include the study's author and the automated harness recorded in the
accompanying repository. All measurements were executed by that harness in a single AWS account; all
oracles were authored before data collection. No AWS service team reviewed this document.

---

# Further reading

- OWASP Top 10 for LLM Applications 2025 — LLM01 Prompt Injection, LLM06 Excessive Agency.
- OWASP Agentic AI — Threats and Mitigations v1.1 (December 2025), threat IDs T1–T17, pinned by
  sha256 `65e3bd59f99c…0345ff`.
- AWS Well-Architected Framework — Security Pillar; Generative AI Lens, GENSEC01–GENSEC06.
- Amazon Bedrock AgentCore Developer Guide — security, gateway policy engine, guardrail integration.
- Amazon Bedrock Guardrails documentation — tiers, filter categories, sensitive-information policies.
- Wohlin, Runeson, Höst, Ohlsson, Regnell, Wesslén, *Experimentation in Software Engineering* (2012) —
  ch. 11, Presentation and Package (structure only; see Chapter 12 on why its prose is not quoted).
- ACM Artifact Review and Badging, current version — for the Repeatability / Reproducibility /
  Replicability vocabulary used in Chapter 12.
- USENIX Security artifact-appendix guidance — for the claim ↔ experiment mapping adopted in
  Appendix C.

Full citation URLs with retrieval dates are in `results/RESEARCH-whitepaper-conventions-20260815.md`
and `results/RESEARCH-evidence-presentation-20260815.md`. **Two retrieval caveats carried forward
from that research and repeated here so they are not lost:** the colour-blind-safe palette source
publishes no hex values on the page consulted, and the closed-form remark about binomial intervals at
zero successes appears in a published *Comment* on the cited paper rather than in the paper's own
text.

---

# Document revisions

| Change | Description | Date |
|---|---|---|
| Initial publication (draft) | First edition. 91 of 92 verdict-eligible propositions published; 7 day-2 replications outstanding; Appendix D conventions unadjudicated; 7 of 8 figures drawn and figure 6 blocked; F8-5 erratum open. | 2026-08-15 |

---

# Notices

This document is provided for informational purposes only. It represents measurements taken in one AWS
account, in one Region, against service behaviour observed between 2026-08-09 and 2026-08-15. Service
behaviour changes; every verdict in this document is dated for that reason. Nothing here is an AWS
publication, an AWS statement, or advice about your specific environment. AWS account identifiers,
ARNs and bucket names are redacted from all distributable artifacts by an automated gate
(`check_redaction.py`), which must read a non-zero file count and exit 0 before publication.

Amazon Web Services, AWS, Amazon Bedrock and AgentCore are trademarks of Amazon.com, Inc. or its
affiliates. OWASP is a trademark of the OWASP Foundation. Other names may be trademarks of their
respective owners.

---

# Appendices

| App. | Contents | Source of truth | State |
|---|---|---|---|
| A | Pre-registration and seals | `census.py`, `verify_prereg.py`, `PREREGISTRATION.yaml` | complete |
| B | Method per family F0–F10 | `results/FINDING-*.md` (17 documents) | complete for the 17 documented families |
| C | The full register: 546 claims → 93 cases → 91 verdicts, with a C↔E map and every exclusion reason | `results/WHITEPAPER-APPENDIX-C.md` (generated) | complete, regenerable |
| D | Figures and statistical conventions | `tools/whitepaper_figures.py`, `results/figures/MANIFEST.json`, `results/RESEARCH-evidence-presentation-20260815.md` §5 | figures 7 of 8 drawn and machine-checked; **conventions still BLOCKED** — 8 sources located, unadjudicated |
| E | Deviations and errata | `DEVIATIONS.md`, `results/ERRATA.md` | complete; E-2 pending the F8-5 decision |
| F | Not-measured register | `results/CENSUS-NOT-MEASURED.md` | complete (F10-1) |
| G | Reproduction, and how far it reaches | `census.py`, `verify_phase0.sh` | complete |

## Appendix A — Pre-registration and seals

Run `./.venv-oracle/bin/python census.py`. It recomputes the register's sha256 and compares it to the
value `PREREGISTRATION.yaml` declares, then prints the case census. The current output:

```
case census — every number below is derived, none is remembered
  register        claims/triage_rules.py CASES            93 case(s)
  registry sha256 recomputed                             fc4216ca1eb470cc17abe77308570c6426f12f9532ec2bf9ac34759c33ee27a9
  registry sha256 PREREGISTRATION.yaml declares          fc4216ca1eb470cc17abe77308570c6426f12f9532ec2bf9ac34759c33ee27a9
  -> seal live: the register hashes to its declared sha256 and its declared size

  claims triaged                                         546 row(s)
  claim-mapped    cases at least one claim points at      90
  untestable      by their own sealed oracle              1 ['F9-1']
  verdict-eligible register minus untestable              92
  published       verdict on disk under results/phase1/   91
  REMAINING       verdict-eligible minus published        1

  verdicts: FALSE 23, INCONCLUSIVE 20, RECORDED 2, TRUE 46

  by family (published / verdict-eligible):
    F0 1/1  F1 28/28  F2 5/5  F3 11/11  F4 6/6  F5 12/12
    F6 9/9  F7 7/7    F8 8/8  F9 2/2    F10 2/3  outstanding: F10-1
```

The oracle-registry hash is computed over `{case_id: oracle_text}` for all 93 cases, sorted by id —
deliberately separate from the hash of the file that contains them, so that the **falsifying
conditions** carry their own stamp.

Three registered cases have no claim pointing at them, and `census.py` prints why each is correct:
F1-4 and F1-21 are propositions about the service model rather than about a document sentence, and
F9-1's own sealed oracle says it is untestable.

## Appendix B — Method per family

`results/FINDING-*.md` — 17 documents covering the pre-registration itself (`FINDING-P0-PREREG.md`),
the statistical layer (`FINDING-P0-STATS.md`), the triage (`FINDING-P0-TRIAGE.md`), the PII corpus
(`FINDING-P0-PII-CORPUS.md`), pricing (`FINDING-P0-PRICING.md`), the Cedar resource-scope repair
(`FINDING-P1-CEDAR-RESOURCE-SCOPE.md`), and per-case findings for F1-1, F1-3, F1-15, F3-10,
F5-1 (revocation), F5-2, F5-4a, F5-7a, F5-7b, F9-2, plus grammar permissiveness.

Each states what was provisioned, the sealed oracle, the arms, n, the dates, and the instrument.
**Appendix B is not yet complete as a per-family narrative**: 17 documents do not cover 11 families
uniformly, and the gap is which families have a written method document versus only a verdict file.
Listed here as an honest state, not as a claim of coverage.

The published metric inventory referenced by §9.1 (31 names) is in F7-1's verdict file under
`inventory_names`.

## Appendix C — The full register

`results/WHITEPAPER-APPENDIX-C.md`, generated by `tools/whitepaper_data.py`. Three sections:

- **C.1** the C↔E map — every case with its family, verdict, n, x, interval, the claim ids that point
  at it, and its run id;
- **C.2** by document section, ordered by claim count, with the verdict mix counted claim × case;
- **C.3** why the 161 caseless claims carry no case, grouped by the sealed triage rule that excluded
  them: `TYPE` 85, `ANCHOR` 64, `X_CLAIM` 6, `OVERRIDE` 3, `SPLIT_X` 3.

**Zero of the 161 caseless claims lack a written exclusion reason.** That is the fact that makes the
register auditable rather than selective, and it is checkable by regenerating the appendix:
`tools/whitepaper_data.py --check` exits non-zero if the file on disk disagrees with the register and
the verdicts.

A reader who distrusts any sentence in the body should be able to walk claim → case → oracle →
verdict → evidence file without asking the author anything. Where that walk breaks, it is recorded:
F2-3 and F2-4 (§12.3) and Appendix B's uneven coverage.

## Appendix D — Figures and statistical conventions

**BLOCKED.** Two conventions are settled and cited:

1. **Distribution results get a distributional form.** Reporting a median without any indication of
   variance is a named antipattern, and effect sizes without confidence intervals likewise. So the
   latency figure is a CDF or quantile plot, **not** a bar of means, and every p50 in this paper
   carries an interval. Chapter 10's Hodges-Lehmann shift with 95% CI [30.2, 57.0] meets this.
2. **No truncated bars.** Using truncated bars to exaggerate differences is a named axis antipattern.

Everything else — censoring notation for §9.4, the display of binomial intervals at zero successes
(F3-3, F5-6, F4-1…F4-5 all have x=0), and colour-blind-safe three-state encoding for figure 6 — is
**authorial judgment stated as such**, pending a scoped verification of eight located sources. The
three-state requirement in particular has a likely standards basis (colour must not be the only means
of conveying information), which would convert figure 6's hatching requirement from judgment into a
citation. It is not cited until it is verified.

**The figures: 7 drawn, 1 blocked.** All are produced by `tools/whitepaper_figures.py`, reading only
`results/`, into `results/figures/`.

| # | Figure | Where | State | Constraint, and how it is met |
|---|---|---|---|---|
| 1 | Verdict distribution over 91 verdicts | "How to read the evidence" | drawn | INCONCLUSIVE must not read as failure — neutral grey **plus** a hatch, so the state survives greyscale |
| 2 | Evidence strength by document section | "How to read the evidence" | drawn | must agree with the register — both are derived from the same `whitepaper_data.build()` output |
| 3 | Enforcement latency against documented bands | §10.1 | drawn | quantile form, never a bar of means; log x-axis because the bands span 5 ms to 31 s |
| 4 | Confidence-score lattice, n=61 | §9.4 | drawn | **censored below τ** — the two unobservable points are full-height hatched spans, never bars with a readable height |
| 5 | Detection efficacy by arm (F5-6) | ACG-04-BP04 | drawn | recall 0/120 rendered as an interval pinned at zero with its ceiling, not as an absent bar; axis clamped to [0, 1] |
| 6 | Control × threat coverage (ACG × T1–T17) | §2.3 | **BLOCKED** | third state distinct by more than hue — unmet for a different reason: 12 of 17 threat titles are ungrounded, so the columns cannot be authored |
| 7 | Mode-flip and reconvergence timeline (F5-2) | §11.4 | drawn | two panels, each timed from its own control-plane call, both measurement days plotted; HTTP status read from `chain.flip.http_status` (202), not from the record's prose |
| 8 | Metric-vs-log agreement (DEV-P4-27) | §9.5 | drawn | paired sums for both days: 24.6/0.8/24.2 on 2026-08-12 and 24.4/0.8/24.8 on 2026-08-13 |

**Every figure must be generated from the evidence tree by a script in the repository.** A figure whose
numbers cannot be regenerated does not ship, and no figure here is hand-drawn. Three properties of that
script are load-bearing rather than incidental:

1. **`--check` compares numbers, never pixels.** It re-derives every figure's values and diffs them
   against `results/figures/MANIFEST.json`. A byte comparison of the PNGs would fail on a matplotlib or
   freetype upgrade while every measurement was untouched, which trains a reader to ignore the check.
2. **The latency figures read the same block the oracle judged.** F6-1's verdict file alone contains
   five plausible latency distributions; the script reads `record.evidence`, which is the block the
   sealed oracle decided on, so a figure cannot disagree with the verdict printed beside it.
3. **A blocked figure is recorded in the manifest, not just in prose.** Figure 6's entry carries its
   reason and its closing condition, so the gap is machine-visible and cannot be lost in an edit.

Two defects were found by *looking at the rendered images*, not by reading the code, and both would
have shipped a wrong claim: figure 7 originally placed the ENFORCE restore at 26.5 s while labelling it
"+13.3 s" (it summed two intervals that have different origins), and figure 4 originally drew its
censored points as bars 44 units tall. A generated figure is not verified until the image is inspected.

## Appendix E — Deviations and errata

`DEVIATIONS.md` and `results/ERRATA.md`. Deviations are numbered `DEV-*` and each records what
changed, why, and **the direction of its bias** — DEV-P4-03 is labelled as biasing towards the
document under test, which is the direction most worth labelling.

Errata: E-1 published. **E-2 is drafted and pending the F8-5 decision** (ACG-06-BP04); it would touch
six sites in two languages plus the handover bundle and the slide decks.

## Appendix F — Not-measured register

`results/CENSUS-NOT-MEASURED.md`. One entry: **F10-1**, the billing asymmetry. The register exists as
a separate document so that a not-measured case cannot be mistaken for an absent one.

## Appendix G — Reproduction, and how far it reaches

**How to re-derive every number in this paper:**

```
./.venv-oracle/bin/python census.py                            # the census in Appendix A
./.venv-oracle/bin/python tools/whitepaper_data.py              # Appendix C + every total quoted here
./.venv-oracle/bin/python tools/whitepaper_data.py --check      # fails if the generated files are stale
./.venv-figs/bin/python  tools/whitepaper_figures.py            # every figure, from results/ only
./.venv-figs/bin/python  tools/whitepaper_figures.py --check    # fails if a figure's NUMBERS moved
./verify_phase0.sh                                              # the full offline gate
./.venv-oracle/bin/python check_redaction.py                    # the publication gate
```

The figures run under a **separate** virtualenv on purpose. `.venv-oracle` is the interpreter every
verdict and every seal was computed in, and it deliberately carries no plotting dependency, so that
installing one to draw a chart cannot perturb the environment a verdict was decided in. Both venvs are
excluded from the redaction gate by prefix rather than by name — an earlier version of that gate
enumerated them, and the enumeration is what let it read 1,272 files of dependencies and pass on them.

**How far that reaches, stated precisely.** Re-deriving every number from the archived evidence
supports *artifacts available* and *artifacts evaluated* on their own terms. It supports **no**
results-validated claim, because that status is by definition earned by someone other than the
authors. See Chapter 12.

**Two further limits on reproduction:**

- The evidence archive (`evidence/`) is **local-only** and is not published, because it contains
  unredacted account identifiers, ARNs and request ids. Its purpose is *interpretability* — the
  ability to quote a full ARN and request id to AWS Support months later — not distribution. The
  distributable tree is `results/`, which passes an automated redaction gate. A reader cannot
  currently re-run the analysis over the raw records; they can re-run every derivation over the
  published verdicts.
- A GitHub commit no longer satisfies archival-availability requirements at the venues consulted; an
  archival DOI is required. That is `FUTURE-WORK.md` item 21 and is cheap to close.

Two published verdicts' underlying call records currently exist **only in S3, under a 90-day expiry
that deletes them around 2026-11-11** (F10-3 and F3-11's snapshot). Until those are archived, the
reproduction chain for those two cases has an expiry date.
