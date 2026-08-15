# Research: how to structure and evidence an AgentCore security whitepaper

- **Date:** 2026-08-15
- **Method:** adversarial multi-source research. 16 primary sources fetched, 80 falsifiable claims
  extracted, 25 verified by 3-vote adversarial panels (a claim dies on 2 of 3 refutations).
  **13 survived, 12 were killed.** Run `wf_84df0f9c-465`, 96 agents.
- **Source quality:** every surviving claim rests on a primary source — `docs.aws.amazon.com`,
  an OWASP PDF verified by download and machine-parsed, or the NIST AI RMF Playbook. No blog or
  vendor-marketing dependencies.
- **Purpose:** decide the whitepaper's chapters and evidence conventions from verified fact rather
  than from an impression of what AWS whitepapers look like. See `WHITEPAPER-DESIGN.md` for what
  was built on top of it and `FUTURE-WORK.md` for the deficiencies it exposed.

**The headline is a negative result.** Of five research angles, only three were actually executed
and only two are answered well. The three angles that matter most for this project's own
requirements — how rigorous papers present validated claims, scientific chart practice, and
published criticisms of guardrail evaluation — produced **zero** surviving claims. They are
**unresearched, not answered**, and a second scoped pass is running (`wf_3762680e-846`). Until it
lands, any figure or validity convention in the whitepaper is authorial judgment, and must be
labelled as such rather than dressed as a standard.

---

## 1. What is verified about AWS whitepaper convention

### 1.1 Versioning is dated revisions, never MAJOR.MINOR.PATCH — CONFIRMED (high)

AWS stamps a publication date on the abstract page and cross-links a **Document revisions**
section rendered as a three-column table whose `<th>` cells are literally
`Change | Description | Date`, every row individually dated, preceded by an RSS-subscription
sentence. The Security Pillar log holds **23 data rows** (24 `<tr>` minus the header) from
2016-11-01 through 2024-11-06. A raw scan for `version`/`v0.0` patterns returns only RSS hits —
zero numeric version strings.

Two corrections the verifiers forced, and both matter for us:

- The revisions table is **not terminal**. The systematic order is
  `… Conclusion → Contributors → Further reading → Document revisions → Notices → AWS Glossary`.
- AWS **does** classify changes semantically in the Change column (`Initial publication`,
  `Minor update`, `Major update`, `Updates for new Framework`, `Updated best practice guidance`)
  and publishes date-pinned CalVer snapshots for some documents (the Framework pins
  2024-06-27 / 2023-10-03 / 2023-04-10 / 2022-03-31; the Security Pillar's equivalents 404).
  The accurate statement is **"no MAJOR.MINOR.PATCH"**, not "unversioned".

Cite the count as *"23 entries as of the 2024-11-06 revision"* — AWS appends rows.

Sources: `wellarchitected/latest/security-pillar/document-revisions.html`,
`…/security-pillar/welcome.html`, `…/framework/document-revisions.html`,
`…/generative-ai-lens/document-revisions.html`,
`whitepapers/latest/aws-best-practices-ddos-resiliency/`.

### 1.2 Controls get dotted, question-parented IDs — CONFIRMED (high)

AWS's canonical scheme is **pillar → numbered question → numbered best practice**: Security →
`SEC 1. How do you securely operate your workload?` → `SEC01-BP01 … BP08`, rendered
character-for-character on `framework/sec-01.html`.

The directly analogous artifact already exists. The **Well-Architected Generative AI Lens**
security pillar is six numbered focus areas **GENSEC01–GENSEC06** (Endpoint security, Response
validation, Event monitoring, Prompt security, Excessive agency, Data poisoning), each rendering
exactly one single-column-table question header — verbatim
`| GENSEC05: How do you avoid excessive agency for models? |` — decomposing into `GENSECnn-BPnn`
controls. Two are on our exact topic:

- **GENSEC02-BP01** "Implement guardrails to mitigate harmful or incorrect model responses"
- **GENSEC05-BP01** "Implement least privilege access and permissions boundaries for agentic
  workflows"

`gensec05` grounds excessive agency in the OWASP LLM Top 10 itself, which gives an
**AWS-sanctioned hook** for our OWASP cross-map rather than an invented one.

Precision notes: the navigated depth is four levels (pillar → unnumbered best-practice area →
question → BP); AWS's nav label is "Focus areas", not "questions"; and IDs are **not** stable —
AWS's own log records SEC 1's BPs "reordered and consolidated" on 2024-06-27, so a bare
`SEC01-BPxx` citation must carry a framework revision date.

Sources: `framework/sec-01.html`, `framework/appendix.html`,
`generative-ai-lens/security.html`, `…/gensec02.html`, `…/gensec05.html`.

### 1.3 A service security chapter opens on shared responsibility — CONFIRMED (high)

The framing is "security **of** the cloud" (AWS-owned infrastructure, effectiveness verified by
third-party auditors under AWS Compliance Programs) versus "security **in** the cloud" (customer-
owned, determined **first by which AWS service you use**, then by data sensitivity, company
requirements, and applicable laws) — positioned **before any control discussion**. The AgentCore
Developer Guide's own security page does exactly this, ahead of its Topics list.

Fetched twice by two independent paths, byte-consistent. A verifier deliberately hunted a
counter-example: the Security Pillar whitepaper does *not* open on shared responsibility (it opens
on pillars/audience → Design principles → Definition) but carries it as dedicated front matter of
Security foundations before the six control areas — corroborating "explicit before controls".

Two honest caveats: "expected to inherit" is a normative judgment from convention across two
primary sources, not a stated AWS requirement; and the framing is service-agnostic boilerplate, so
inheriting it buys structural conformance and **zero AgentCore-specific security content**.

Sources: `bedrock-agentcore/latest/devguide/security.html`, `…/data-protection.html`,
`wellarchitected/latest/security-pillar/shared-responsibility.html`.

### 1.4 The seven security best-practice areas — CONFIRMED (medium, 2-1)

The Well-Architected **security pillar** defines seven areas: Security foundations, Identity and
access management, Detection, Infrastructure protection, Data protection, Incident response,
Application security. Confirmed verbatim on two independent primary pages.

Three corrections drove the split vote, and they are the reason this is a weak skeleton for us:

1. The quote is **not** on `welcome.html` (which carries only the six *pillars*) — cite
   `security-pillar/security.html` or `framework/sec-def.html`, or a reviewer following the
   footnote reads the quote as fabricated.
2. Scope overreach: AWS CAF's Security Perspective "comprises **nine** capabilities", a different
   taxonomy. Say "the Well-Architected security pillar defines seven best-practice areas".
3. The taxonomy is not stable (6→7 when Application Security was added 2023-04-10) and the
   pillar's own assessment grain is eleven questions SEC 1–SEC 11, which do **not** map 1:1 onto
   the seven areas.

**For an AgentCore guardrails paper the topical artifact is the GenAI Lens**, organized by GENSEC
question — prefer that, or do both.

### 1.5 NEGATIVE: there is no verifiable "AWS whitepaper template" — CONFIRMED by refutation

Four separate claims that AWS best-practice pages follow a rigid ordered block structure
(one-line statement → Desired outcome → Common anti-patterns → Benefits hyperlinked to design
principles → "Level of risk exposed if this best practice is not established" → Implementation
guidance → numbered Implementation steps → Resources split into Related best practices /
documents / videos / examples) went to **0-3 refutation**; the per-page risk-level callout survived
only 1-2; and "AWS cites evidence in typed buckets" died 1-2.

Individual blocks demonstrably exist where independently confirmed — `gensec05-bp01.html` carries
a `High` risk level, Implementation steps 1–4, and a Resources block with Related documents. So the
only safe sentence is: *"several AWS best-practice pages include a risk-level line, implementation
guidance, numbered steps and typed resource lists"* — an observed pattern with per-page citations,
**never a normative AWS template**.

Also refuted 0-3: that the AgentCore devguide security chapter's seven-topic order is a fixed
prescriptive order a whitepaper can mirror 1:1, and that that page's silence on guardrails and
prompt injection proves a documented gap.

> **The transferable lesson.** AWS's **identifier and versioning** conventions are real and
> machine-verifiable; its **prose-block templates** are not. Make structural claims about IDs,
> revision tables and front matter — never about a section template.

---

## 2. What is verified about the framework cross-map

### 2.1 AWS's own least-privilege control set for agent workloads — CONFIRMED (high)

`gensec05-bp01.html` (risk level **High**) prescribes, and every clause maps to literal source
text: Bedrock **Agents** use execution roles and Bedrock **Flows** use service roles; scope both to
intended resource ARNs; "Consider defining conditions … such as requests coming from a specific
VPC"; apply **IAM permissions boundaries** at the role level as a ceiling; create separate
duty-specific roles (prompt engineer building the workflow vs security engineer authoring the
service role); and as the **fourth and final ordered implementation step**, require **user
confirmation** of agent actions to mitigate excessive agency — live in Bedrock as
`confirmationState` CONFIRM/DENY, framed by AWS as a prompt-injection safeguard.

The Lens is current: two revisions only (2025-04-15 initial, 2025-11-19 adding agentic AI).

**Two scope corrections we must carry.** "Mitigation of last resort" is a gloss — write "final
implementation step / human-in-the-loop backstop". And the page names Bedrock **Agents and Flows
only**; the Lens scope is Amazon Q, Bedrock and SageMaker AI, and its `agentic-ai.html` **never
mentions Bedrock AgentCore**. Mapping this BP onto AgentCore is a defensible extrapolation
(AgentCore Runtime also uses execution roles) but must be **labelled inference**, and "user
confirmation" has no identically named AgentCore equivalent.

### 2.2 Prompt injection: measured impact reduction, never prevention — CONFIRMED (high)

OWASP **LLM01:2025** states it is unclear whether fool-proof prevention methods exist and
immediately pivots — "However, the following measures can **mitigate the impact** of prompt
injections:" + 7 measures — so impact-reduction is OWASP's own framing, not our inference. AWS's
page is titled "**Detect** prompt attacks…" and uses only detect/filter/block language, and
corroborates with an explicit coverage hole: "You must always use input tags… If there are no
tags, prompt attacks for those use cases will not be filtered." NIST AI RMF Playbook **MANAGE 1.4**
requires documenting and disclosing **residual risk**.

The strongest counter-evidence found does not refute it: **CaMeL** (arXiv 2503.18813, "Defeating
Prompt Injections by Design") achieves 77% of tasks with provable security, not 100%, and is a
control/data-flow interpreter, not a content guardrail.

**The honest structure is a two-tier split.** Deterministic controls (IAM deny, egress deny, Cedar
authorization) may carry **scoped prevention claims** because they prevent the *consequence*
regardless of whether injection succeeds. Probabilistic guardrail filters get **measured detection
efficacy plus stated residual risk**.

Citation fix: the quote lives at `genai.owasp.org/llmrisk/llm01-prompt-injection/`, not the
`/llm-top-10/` landing page.

**Directly actionable against our own document, re-measured 2026-08-15:** `v1.4.md:850` claims Tool
I/O Guardrails "**Prevent** data leakage and indirect prompt injection from tool outputs" — the
exact wording this finding forbids — and `:368` says "**Prevents** sensitive data leakage through
tool interactions", while `grep -ic 'residual risk'` over the file returns **0**. Line 199 already
documents the input-tagging coverage gap correctly, so **the document contradicts itself.**

### 2.3 Excessive Agency has three named root causes and prescribes complete mediation — CONFIRMED (high)

Verified against the authoritative versioned markdown behind the published list: "The root cause of
Excessive Agency is typically one or more of: **excessive functionality; excessive permissions;
excessive autonomy**" (exact names, exact order), and prevention item 7, labelled **Complete
mediation**, contains verbatim: "**Implement authorization in downstream systems rather than
relying on an LLM to decide if an action is allowed or not.**"

Three precision notes: OWASP says "typically one or more of", so write "three distinct
(often co-occurring) root causes"; the 2023-24 edition numbered this **LLM08**, so cite LLM06:2025
and flag the renumbering; and the AgentCore implication (evidence least-privilege execution roles
and gateway-side authorization as controls **distinct from any prompt-level guardrail**) follows
from item 7 plus "excessive permissions" being independent of model-level filtering, but is our
inference and must be labelled.

2025 is the current edition — translations dated 2025-03-12 and 2025-07-22, no 2026 edition or RC
found as of 2026-08-15.

### 2.4 The OWASP agentic taxonomy is our coverage-matrix target — CONFIRMED (high)

**OWASP Agentic AI — Threats and Mitigations v1.1, December 2025**
(`Agentic-AI-Threats-and-Mitigations-1.1.pdf`, 2,398,898 bytes, sha256
`65e3bd59f99c411b055c6caf2bac96ab361dff8c010e4bef532a593ce10345ff`). Numbers regenerated from the
downloaded artifact, not quoted: the "Detailed Threat Model:" header row is literally
`TID Threat Name Threat Description Mitigations`; distinct IDs **T1 … T17** with zero hits for
T18+; T1 and T17 rows match word-for-word. **Six** numbered mitigation playbooks exist by heading
with a "Playbook and Threat Mapping Overview" table, and a grep of `(Proactive|Reactive|Detective)`
returns exactly **6/6/6** — one of each per playbook, a 6×3 grid. Cross-playbook overlap is
acknowledged verbatim with three named examples.

The newer **OWASP Top 10 for Agentic Applications 2026** (2025-12-09) calls the T&M guide "our
foundational and detailed taxonomy" and performs exactly this row-by-row mapping ("maps one-to-one
to T3: Privilege Compromise", "maps to T17 Supply Chain Compromise", plus an ASI/LLM/T crosswalk
table) — the searched-for counter-evidence became confirming evidence.

**Four usage rules.**

1. It is **not fixed** — the doc plans revision and the landing page still banners v1.0/2025-02-17
   while serving v1.1. Pin "v1.1, December 2025" **plus the sha256**. v1.0 stops at T15; T16 and
   T17 are v1.1 additions.
2. It is a **descriptive reference table, not an AWS-style decision table** — use it as a coverage
   matrix, not a decision aid.
3. **Map by TID, never by name.** OWASP's own 2026 doc calls T4/T6/T12 "Memory Overload / Broken
   Goals / Shared Memory Poisoning" while v1.1 names them "Resource Overload / Intent Breaking &
   Goal Manipulation / Agent Communication Poisoning".
4. "Pass/fail control matrix" is our design inference; OWASP never frames playbooks as pass/fail.

One citation defect to route around: v1.1's own prose still says "five playbooks",
self-contradicted two paragraphs later by a "Playbook 6" example. Anchor to the mapping table and
the six headings; **never quote the "five" sentence next to a claim of six.**

### 2.5 Conversational-path guardrails are structurally insufficient — CONFIRMED (medium, 2-1)

Both quotes are verbatim in the v1.1 PDF. **T9** (Identity Spoofing / Agent Identity Compromise):
theft or misuse of a persistent agent identity enables "privileged, long-term API access that
**bypasses the agent's conversational interface and its guardrails**". **T16** (Insecure Inter-Agent
Protocol Abuse): with MCP and A2A, loose spec enforcement or missing input validation and strong
identity binding lets attackers "**bypass guardrails entirely**". Both remedial controls are
sourced, not invented — T16 prescribes "Sanitize and validate all protocol-level data, including
context payloads and tool metadata"; T9 prescribes identity validation frameworks, trust boundaries
and least privilege ("identity binding" is OWASP's own term).

Required hedges, which are why this is 2-1: pin v1.1 + sha256 (the landing page banners v1.0,
which contains neither T16 nor the relevant sentence); **phrase T9 conditionally** — "a
*compromised* persistent agent identity yields an API path on which conversational guardrails are
not enforced", not an inherent property of having agent identity; and OWASP never mentions
AgentCore, so "structurally insufficient as an AgentCore claim" is our application. One verifier
could not fetch the AWS-side enforcement-surface docs, so the AgentCore-side rebuttal (per-path
ApplyGuardrail, AgentCore Identity/Gateway inbound-outbound auth) is **reasoned, not cited**.

### 2.6 The standard we map onto publishes zero measurements — CONFIRMED (high)

Across the full v1.1 text there are **zero** occurrences of `benchmark`, `efficacy`,
`confidence interval`, `experiment` or `latency`; the only two percentages in the document are a
Gartner market forecast; no p-value, sample size, ablation or results table appears anywhere; and
the mitigation column is uniformly imperative prose. The document self-labels areas as
pre-evidence (T7: "This threat is at an early stage…") and acknowledges a needed primitive does not
exist (T13: "While cryptographic attestation mechanisms for LLMs do not yet exist…", substituting
procedural controls).

The verifier reproduced the 2,459-line count exactly with default `pdftotext`, re-tested the five
absences under `pdftotext` default, `pdftotext -layout` (1,985 lines) and PyMuPDF (2,322 lines),
then **defeated hyphenation and page-break splitting by stripping all whitespace and re-searching
substrings**: all still zero, as were `quantitative` and `empirical`. The only `confidenc` hit is
"based on risk, confidence," in human-in-the-loop prose. The five arXiv citations are
technique/threat pointers, none cited for measured mitigation effectiveness.

**Two consequences.** An empirically validated AgentCore guardrails paper is a **genuine
contribution rather than a restatement** — this is the strongest argument for publishing ours. And
the sentence "**satisfies OWASP agentic mitigations**" is forbidden: conformance to an unmeasured
prescriptive standard is an assertion, not a validated result. Stamp the count as "2,459 lines,
default pdftotext, v1.1 Dec 2025", and check whether the 2026 flagship adds measurement before
repeating this absence claim about the whole OWASP corpus.

---

## 3. Where our own document stands against this — measured, not estimated

Re-verified independently on 2026-08-15 against
`agentcore_guardrails_best_practices_v1.4.md` (**1,073 lines**, 161,264 bytes).

**Already present, and matching the empirical-rigor norms the research could confirm:** a sibling
`PREREGISTRATION.yaml` + `PREREGISTRATION.sha256`; an explicit verdict taxonomy in use with the
stated rule "An INCONCLUSIVE verdict is not evidence against a claim"; a marker vocabulary
(`[verified …]`, `[corrected per …]`, `(test pending …)`, `(measured — amendment deferred …)`); a
two-calendar-day reproduction gate that visibly blocks amendments on single-day TRUE verdicts;
interval reporting (bracket-style CIs such as "recall 0 [0, 0.031] at n=120"), 57 `n=`
occurrences, 17 p50 and 8 p99 references; and an explicit **not-measured register** for the billing
claim (F10-1, Cost Explorer daily granularity) instead of an open-ended claim.

**Absent — every count reproduced by me today, all zero:**

| Grep (case-insensitive) | Hits |
|---|---|
| `residual risk` | 0 |
| `OWASP` | 0 |
| `GENSEC` | 0 |
| `ATLAS` | 0 |
| `42001` | 0 |
| `shared responsibility` | 0 |
| `Document revisions` | 0 |
| `Intended audience` | 0 |
| `Contributors` | 0 |
| `threats to validity` | 0 |
| `construct validity` | 0 |

Change history exists only as Appendix C/D change logs, not an AWS-style `Change | Description |
Date` table. Threats-to-validity content **is** in the document but dispersed into per-item "What
the TRUE verdict does not prove" prose rather than a named section.

**One grep trap, worth recording so nobody repeats it:** `grep -c NIST` returns 16 hits, but every
one is the substring inside `deterministic` / `non-deterministic`. The real NIST-framework count is
**0**.

Current section order is Executive Summary → Architecture → Phase 1/2/3 → latency → best practices
→ checklist → reference architecture → references → appendices: an operational Before/During/After
narrative, **not** the AWS envelope.

---

## 4. Open questions this research could not close

1. Does the **OWASP Top 10 for Agentic Applications 2026** (2025-12-09) supersede T1–T17 as the
   expected mapping target, does it introduce ASI-prefixed IDs to cite alongside TIDs, and does it
   publish any measurement that would soften §2.6's absence finding?
2. What are the actual conventions for presenting validated claims and threats to validity in
   peer-reviewed security venues (USENIX/ACM artifact-evaluation badging, empirical-SE reporting
   guidelines, pre-registration practice), and what do reviewers say guardrail evaluations
   systematically fail to establish?
3. Which chart forms are defensible for our three result types — latency distributions with
   p50/p99 and censored client-side timeouts; small-n detection efficacy such as
   "recall 0 [0, 0.031] at n=120"; and a pass/fail matrix with **INCONCLUSIVE as a third state** —
   and how should INCONCLUSIVE and not-measured cells be rendered so they cannot be misread as
   failures?
4. Does AWS publish any guidance mapping **AgentCore specifically** (not Bedrock Agents/Flows) onto
   GENSEC01–GENSEC06, and is there an AgentCore equivalent of Bedrock Agents' user confirmation?

Questions 2 and 3 are the subject of the running second pass `wf_3762680e-846`.

---

## 5. Citation defects found in the research itself — fix before publication

The research's own anchors were wrong at least four times. Every one must be re-pointed:

| Assertion | Wrong anchor | Correct anchor |
|---|---|---|
| Seven security best-practice areas | `security-pillar/welcome.html` | `security-pillar/security.html` or `framework/sec-def.html` |
| AWS agentic least-privilege controls | GenAI Lens landing page | `generative-ai-lens/gensec05-bp01.html` |
| "No fool-proof prevention" | `genai.owasp.org/llm-top-10/` | `genai.owasp.org/llmrisk/llm01-prompt-injection/` |
| OWASP agentic T1–T17 | landing page (banners v1.0/Feb-2025) | the v1.1/Dec-2025 PDF, **pinned by sha256** |

**Time sensitivity runs in three directions.** The Security Pillar revision log's newest entry is
2024-11-06, roughly 21 months stale — quote "23 entries as of the 2024-11-06 revision", never a
live number. The GenAI Lens agentic section is 2025-11-19 and is the newest AWS artifact, so
anything written against the older Lens is out of date. And OWASP shipped a newer flagship
(2025-12-09) that was only sampled here for cross-mapping evidence and was **not itself
researched**.

**Three claims rest on inference and must be labelled, not attributed to a source:** that OWASP's
playbook structure is a pass/fail control matrix; that T9/T16 make conversational guardrail
coverage "structurally insufficient for AgentCore" (OWASP never mentions AgentCore); and that AWS's
Bedrock Agents/Flows least-privilege BP transfers to AgentCore.
