# Exclusion Register

**Generated** by `claims/03_exclusion_register.py` from `claims/triage.csv`. Do not edit by hand — edit the rules in `claims/triage_rules.py` and regenerate. `--check` fails if this file and the triage disagree.

Scope: `agentcore_guardrails_best_practices_v1.2.md`, 546 atomic claims after splits and merges.

## 1. Why this register exists

A report claiming 100% validation of a 961-line document would be false, and detectably so. This register is the honest denominator: it names every claim that receives **no experiment**, states why, and — where one exists — names the nearest test that *is* run. An accurate exclusion register is more credible than a false 100%.

Three kinds of "not tested" are recorded separately, because collapsing them would hide the only one that is a real gap:

| Class | Meaning | Is it a gap? |
|:--|:--|:--|
| **D** | Definitional — the document's own framework (hop numbering, diagram labels, change log, metadata) | **No.** A naming convention has no truth value. Manufacturing a test for it would be theatre. |
| **N** | Normative — value judgements and prescriptions addressed to the reader | **No, but they must never be scored "passed."** The *capability* each recommendation presumes is tested; whether the recommendation is advisable is not an empirical question. |
| **X** | Excluded, testable in principle | **Yes.** Each row below carries a reason and a remedy. These are the rows to attack. |

## 2. Arithmetic

| | Claims | Share |
|:--|--:|--:|
| E — empirical-deterministic | 96 | 17.6% |
| S — statistical | 77 | 14.1% |
| C — config-surface / API-truth | 106 | 19.4% |
| O — observability-truth | 106 | 19.4% |
| **Directly tested (E+S+C+O)** | **385** | **70.5%** |
| X — excluded, testable in principle | 10 | 1.8% |
| N — normative | 57 | 10.4% |
| D — definitional | 94 | 17.2% |
| **Not tested (D+N+X)** | **161** | **29.5%** |
| **Total** | **546** | **100.0%** |

The headline number is therefore **385/546 = 70.5% of claims carry an experiment**, and **10 claims (1.8%) are genuine gaps**. The 151 D and N rows are accounted for, not omitted: every one is listed in §4 and §5 with the reason it has no truth value an experiment could reach.

## 3. Class X — the real gaps

10 claims. Each is testable in principle and is not being tested here. Ordered as they appear in the document.

### C-s3-1-bullet-014-a  ·  §3.1

> Policy evaluation TIMEOUTS result in DENY [split of: Fail-secure: Policy evaluation timeouts result in an automatic DENY decision (AgentCore Service Approval Accelerator v2.9, Policy section).]

- **Doc line** 140 · `sha1:75b90ee42b92` · rule `SPLIT_X:C-s3-1-bullet-014-a`
- **Merge group** `M-fail-secure-timeout-deny` (canonical site)
- **Why excluded** Fail-secure on policy-evaluation TIMEOUT. AgentCore exposes no fault-injection surface to induce a service-side evaluation timeout, so the claim cannot be tested directly. Nearest proxies ARE run: F5-4a (policy that cannot evaluate) and F5-4b (guardrail evaluation impossible). Source remains Accelerator v2.9 -> release gate applies.
- **Nearest proxy run** `F5-4a` (Route 5: policy referencing a nonexistent context path), `F5-4b` (Route 5: guardrail evaluation cannot run (permission removed))
- **Remedy** an AWS-documented timeout guarantee or a fault-injection capability.

### C-s3-3-numitem-004  ·  §3.3

> Set timeouts and circuit breakers for the API call to prevent latency spikes from blocking the entire request. **Decide your failure posture explicitly**: AWS does not document fail-open vs. fail-closed behavior for Bedrock Guardrails errors during model invocation — your application owns this decision when calling ApplyGuardrail (fail-closed is the safe default for regulated workloads).

- **Doc line** 237 · `sha1:fa61c8efb545` · rule `OVERRIDE:C-s3-3-numitem-004`
- **Why excluded** 'AWS does not document fail-open vs fail-closed' is a claim about the ABSENCE of documentation. Not falsifiable by experiment: finding the behaviour empirically (F5-4b does) would not show that AWS documents it. The testable half — what the actual posture is — is covered by F5-4b.
- **Nearest proxy run** `F5-4b` (Route 5: guardrail evaluation cannot run (permission removed))
- **Remedy** none; this is a correctly-scoped statement about the documentation record, verifiable only by review of AWS docs at a stated date.

### C-s4-1-bullet-008-a  ·  §4.1

> Fail-secure: evaluation timeouts result in DENY [split of: Fail-secure: evaluation timeouts result in automatic DENY]

- **Doc line** 294 · `sha1:b121bde0816c` · rule `SPLIT_X:C-s4-1-bullet-008-a`
- **Merge group** `M-fail-secure-timeout-deny` → canonical `C-s3-1-bullet-014-a`
- **Why excluded** Restatement of the timeout-DENY claim in 3.1, merged via M-fail-secure-timeout-deny; the same absence of a fault-injection surface applies. Proxies F5-4a/F5-4b are run.
- **Nearest proxy run** `F5-4a` (Route 5: policy referencing a nonexistent context path), `F5-4b` (Route 5: guardrail evaluation cannot run (permission removed))
- **Remedy** identical to the canonical site C-s3-1-bullet-014-a — an AWS-documented timeout guarantee or a fault-injection capability. Recorded here rather than deferred to the canonical row so that this site is independently visible to the v1.3 amendment pass; a claim amended at one of its sites is not amended.

### C-s4-5-2-trow-002  ·  §4.5.2

> **Sandbox** || S3 + DNS only || Better, but **DNS is a real exfiltration channel** — the Accelerator's own words: "DNS queries represent a limited data channel — organizations processing sensitive data should evaluate whether VPC Mode provides a stronger security boundary." Mitigate with Route 53 Resolver DNS Firewall

- **Doc line** 465 · `sha1:aa4dda73b35e` · rule `X_CLAIM:C-s4-5-2-trow-002`
- **Why excluded** DNS as an exfiltration channel from Code Interpreter Sandbox mode. Testing it means performing actual DNS-based data exfiltration from a sandbox; the technique is out of scope for this engagement and the finding would not change any recommendation (the document already says use VPC mode). NDA-sourced -> release gate.
- **Nearest proxy run** none — this claim has no experimental shadow at all
- **Remedy** a scoped, separately-authorized network test.

### C-s4-5-2-trow-003  ·  §4.5.2

> **VPC** || Only what your subnets/SGs allow || Strongest boundary. ENIs created via the `AWSServiceRoleForBedrockAgentCoreNetwork` service-linked role; required endpoints: ECR, S3, CloudWatch Logs; DNS Firewall still recommended against DNS exfiltration

- **Doc line** 466 · `sha1:ac57e59190ba` · rule `X_CLAIM:C-s4-5-2-trow-003`
- **Why excluded** VPC-mode ENI creation via AWSServiceRoleForBedrockAgentCoreNetwork and the required-endpoint list. Partially covered by F5-7b (egress mutation); the service-linked-role mechanism itself is an implementation detail we can observe but not falsify usefully.
- **Nearest proxy run** `F5-7b` (Route 2: VPC egress containment)
- **Remedy** covered incidentally if F5-7b's runtime creation surfaces the SLR.

### C-s4-5-3-prose-002  ·  §4.5.3

> Two policy caveats: (a) VPC endpoint policies restrict by IAM principal only — **OAuth-authenticated callers require Principal `*`** in the endpoint policy (constrain them via the resource/action instead); (b) the Gateway has a **third, separate** PrivateLink endpoint distinct from the data/control planes.

- **Doc line** 478 · `sha1:eb89954ca6a2` · rule `X_CLAIM:C-s4-5-3-prose-002`
- **Why excluded** VPC endpoint policies restrict by IAM principal only, so OAuth-authenticated callers require Principal '*'. Testing requires a working OAuth-authenticated gateway caller behind a PrivateLink endpoint — infrastructure well beyond this platform's scope, and the claim is about VPC endpoint policy semantics (an EC2/PrivateLink property) rather than an AgentCore guardrails property.
- **Nearest proxy run** none — this claim has no experimental shadow at all
- **Remedy** a dedicated PrivateLink + OIDC testbed.

### C-s4-5-5-prose-002  ·  §4.5.5

> Mandate VPC-connected deployments at the IAM layer with condition keys (Accelerator, Runtime section): `aws:SourceVpc` / `aws:SourceVpce` / `aws:SourceIp` on invocation, and `bedrock-agentcore:subnets` / `bedrock-agentcore:securityGroups` on deployment — so a runtime simply cannot be created outside the contained network.

- **Doc line** 487 · `sha1:d70728375ab3` · rule `X_CLAIM:C-s4-5-5-prose-002`
- **Why excluded** IAM condition keys aws:SourceVpc/SourceVpce and bedrock-agentcore:subnets/securityGroups for mandating VPC deployment. Authoring is testable but ENFORCEMENT requires a constrained principal in a member account, which is AccessDenied from this management account (same structural limit as F5-3c).
- **Nearest proxy run** none — this claim has no experimental shadow at all
- **Also named, but NOT run** `F5-3c` — see §3.2. Named so the limit is identifiable; not evidence.
- **Remedy** a member-account test role, which decision 5b explicitly excluded.

### C-s5-2-numitem-005  ·  §5.2

> Data-residency note: built-in evaluators run on service-owned Bedrock credentials using Geo Cross-Region Inference (CRIS), routing model invocations across Regions within the geography; custom LLM-judge evaluators invoke YOUR designated Bedrock model in your own account (you retain billing, quota, and Region control). Quotas as of the devguide snapshot at writing time (2026-08): up to 1,000 evalua

- **Doc line** 582 · `sha1:28b2ebb48e76` · rule `X_CLAIM:C-s5-2-numitem-005`
- **Why excluded** Built-in evaluators run on service-owned credentials using Geo Cross-Region Inference. Not observable from the customer side: we cannot see which credentials or Regions a service-owned evaluator uses. F8-6 tests the in-geography property for OUR OWN cross-Region inference, which is the closest reachable analogue.
- **Nearest proxy run** `F8-6` (Standard tier's cross-Region inference stays in-geography)
- **Remedy** AWS-side attestation.

### C-s5-3-numitem-003  ·  §5.3

> **A/B Testing** — controlled traffic splitting between two variants through AgentCore Gateway; online evaluation scores each session; reports statistical significance (p < 0.05; traffic split is sticky by runtime session ID; variants injected via W3C baggage headers)

- **Doc line** 601 · `sha1:e7277554e84b` · rule `X_CLAIM:C-s5-3-numitem-003`
- **Why excluded** A/B testing reports statistical significance at p<0.05 with sticky traffic splitting. Testable in principle but requires a live A/B experiment with enough traffic to reach significance — cost and duration outside this project's ceiling, and it measures an AgentCore Optimization feature rather than a guardrails property.
- **Nearest proxy run** none — this claim has no experimental shadow at all
- **Remedy** a dedicated Optimization study.

### C-s9-mermaid-011-c  ·  §9

> Cedar authorization is fail-secure [split of: Hop #4: Cedar Tool Auth (AgentCore Policy) ~5–50ms · default-deny · fail-secure]

- **Doc line** 827 · `sha1:5fd710eb6f3c` · rule `SPLIT_X:C-s9-mermaid-011-c`
- **Merge group** `M-fail-secure-timeout-deny` → canonical `C-s3-1-bullet-014-a`
- **Why excluded** 'fail-secure' as a blanket property of Hop #4. The evaluable half is tested (F4-4 default-deny, F5-4a unevaluable policy, F5-4b guardrail evaluation impossible); the TIMEOUT half is not inducible — see C-s3-1-bullet-014-a. A label asserting the blanket property inherits the same exclusion: proxies covering three failure modes do not establish a universal, and a diagram label that reads as a guarantee should not be scored as one.
- **Nearest proxy run** `F4-4` (Cedar default-deny: no matching policy means deny), `F5-4a` (Route 5: policy referencing a nonexistent context path), `F5-4b` (Route 5: guardrail evaluation cannot run (permission removed))
- **Remedy** the same as the claim it restates — an AWS-documented timeout guarantee, or a fault-injection surface. Until then v1.3 should narrow the label to the modes actually measured.

### 3.1 What the X rows have in common

Four structural causes account for all of them, and naming the causes is more useful than the individual rows:

1. **No fault-injection surface.** AgentCore exposes no way to induce a service-side evaluation timeout, so every "fail-secure on timeout" claim is unreachable. The nearest proxies (`F5-4a` unevaluable policy, `F5-4b` guardrail evaluation impossible) probe the same posture through different failure modes, and they are run. They are *proxies*, not substitutes: a system can be fail-closed on a malformed policy and fail-open on a timeout.
2. **Enforcement requires a constrained principal.** Testing that an SCP or an IAM condition key *blocks* something requires a principal that the control actually binds. This is the Organizations management account, where SCPs never apply, and `AssumeRole` into both member accounts is AccessDenied. Authoring and propagation are testable (`F5-3a`, `F5-3b`); enforcement from inside a constrained account is not.
3. **The claim is about a service we cannot see inside.** Service-owned evaluator credentials and Regions are not customer-observable at all. No amount of budget changes this; it needs an AWS-side attestation.
4. **Out of engagement scope.** DNS-based exfiltration from a sandbox is an actual exfiltration technique, and a live A/B significance study measures an Optimization feature rather than a guardrails property. Both are declined deliberately, not by omission.

Cause 2 is worth one more sentence, because it is the one a reviewer will press on. Decision 5b excluded the member-account test as a matter of engagement policy: it is a 90-day irreversible Organizations change whose subject is generic SCP behaviour, not an AgentCore property. That is a scoping judgement, and it is recorded here as one rather than dressed up as an impossibility.

### 3.2 Declined arms — designed, named, not run

An exclusion reason may name one of these to identify a limit precisely. They are deliberately kept OUT of the case registry: an arm that does not run must never be citable as evidence, and if these were registry cases the tables above would list them under "nearest proxy run". Naming without crediting is the whole point of the distinction.

- **`F5-3c`** — SCP enforcement observed from INSIDE a constrained member account. Structurally unreachable here — this is the Organizations management account, where SCPs never apply, and AssumeRole into both member accounts returns AccessDenied. (Account IDs are deliberately omitted: this file is generated into a report destined for external distribution, and per the redaction gate no account identifier belongs in prose that adds nothing by carrying it.) Decision 5b also declined it on engagement grounds: creating a test principal in a member account is a 90-day irreversible Organizations change whose subject is generic SCP behaviour, not an AgentCore property. F5-3a (authoring + propagation via DescribeEffectivePolicy) and F5-3b (IAM permissions boundary, a control the document itself recommends) are run instead and ARE evidence; F5-3c is not.

## 4. Class N — normative claims (no truth value)

57 claims.

Value judgements and prescriptions addressed to the reader. Listed in full because the failure mode this class prevents is a recommendation being quietly counted as a validated fact. Grouped by the reason assigned; the reason states which experiments cover the *capability* each recommendation presumes.

A recommendation that does make a falsifiable prediction is not in this list — it was operationalized into an E/S claim in `triage_rules.py` and appears in the coverage matrix instead.

**24 claim(s)** — Best-practice recommendation: a prescription addressed to the reader, not a proposition about AWS behaviour, so no experiment can falsify it. The underlying capability it presumes IS tested (see the same section's C/S claims); whether following the recommendation is advisable remains a value judgement. Recommendations that do make a measurable prediction are operationalized individually in OVERRIDES.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s3-1-numitem-001` | §3.1 | 145 | Configure only the minimum necessary safeguards at the gateway level to reduce latency |
| `C-s3-1-numitem-002` | §3.1 | 146 | Use aggressive thresholds (closer to 0) only for high-risk categories; use moderate thresholds for general content |
| `C-s3-1-numitem-003` | §3.1 | 147 | Monitor the gateway Latency and Duration metrics (namespace `AWS/Bedrock-AgentCore`) plus the Policy metrics in Section … |
| `C-s3-1-numitem-004` | §3.1 | 148 | Leverage the gateway's early-block behavior to save downstream compute costs |
| `C-s3-2-numitem-004` | §3.2 | 201 | For latency-sensitive applications, enable only essential policies at this layer and defer comprehensive checks to async… |
| `C-s3-3-numitem-002` | §3.3 | 235 | Use content-array batching to reduce the number of API calls |
| `C-s4-1-numitem-001` | §4.1 | 304 | Use Cedar Policy for tool-level access control — it's faster and more reliable than guardrails for authorization decisio… |
| `C-s4-1-numitem-002` | §4.1 | 305 | Do NOT rely on guardrails alone for tool authorization — guardrails are probabilistic; Cedar is deterministic |
| `C-s4-1-numitem-003` | §4.1 | 306 | Follow least-privilege principle: explicitly permit only required tool actions |
| `C-s4-1-numitem-004` | §4.1 | 307 | Monitor policy evaluation latency via AgentCore Policy metrics in CloudWatch (Section 6.2) |
| `C-s4-1-numitem-005` | §4.1 | 308 | Keep policy rules focused and minimal — overly complex policies add evaluation time |
| `C-s4-2-numitem-001` | §4.2 | 344 | **Selectively apply guardrails per tool** — not all tools handle sensitive content; skip guardrails for trusted internal… |
| `C-s4-2-numitem-002` | §4.2 | 345 | **Monitor per-tool-call latency** — use the `GuardrailLatency` metric with the ToolName dimension plus distributed traci… |
| `C-s4-2-numitem-003` | §4.2 | 346 | **Set guardrail thresholds appropriately per tool type** — a database query tool may need stricter PII filtering than a … |
| `C-s4-3-numitem-001` | §4.3 | 370 | Turn on tracing across EVERY agent component, not only the outer boundary — the trace must span the request end-to-end |
| `C-s4-3-numitem-003` | §4.3 | 372 | Use AWS Distro for Open Telemetry (ADOT) SDK for custom runtime metrics (`aws-opentelemetry-distro` >= 0.10.0; note the … |
| `C-s5-1-numitem-002` | §5.1 | 554 | Configure output-specific settings (`outputStrength`, `outputAction`) within your guardrail resource if output needs dif… |
| `C-s5-1-numitem-003` | §5.1 | 555 | Monitor InvocationLatency (`AWS/Bedrock/Guardrails` namespace, GuardrailContentSource = Output dimension) separately for… |
| `C-s5-1-numitem-004` | §5.1 | 556 | Consider Automated Reasoning checks for hallucination detection on critical outputs (note: detect mode only — the app mu… |
| `C-s5-1-numitem-006` | §5.1 | 558 | PII masking caveats: masked PII still appears UNMASKED in model invocation logs (CloudWatch `input` field) and in the gu… |
| `C-s5-2-numitem-001` | §5.2 | 578 | Enable online evaluation in production to continuously monitor quality |
| `C-s5-2-numitem-002` | §5.2 | 579 | Define custom evaluators aligned with your business metrics (not just safety — also correctness, helpfulness) |
| `C-s5-2-numitem-003` | §5.2 | 580 | Set CloudWatch alarms on evaluation score thresholds to detect regressions early |
| `C-s5-2-numitem-004` | §5.2 | 581 | Use evaluation results as input to the optimization feedback loop |

**17 claim(s)** — Implementation-checklist step: an instruction to the reader. Testable checklist items are overridden individually; the rest are procedural (create a dashboard, write a runbook) and have no truth value.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s8-checkitem-001` | §8 | 787 | Create Bedrock Guardrail resources (with per-direction input/output settings) |
| `C-s8-checkitem-005` | §8 | 791 | Define Cedar policies for tool authorization |
| `C-s8-checkitem-008` | §8 | 794 | Apply network containment (Section 4.5): Runtime VPC mode with egress allowlist, Code Interpreter Sandbox/VPC mode + DNS… |
| `C-s8-checkitem-010` | §8 | 796 | Instrument agent code with ADOT SDK for custom spans |
| `C-s8-checkitem-011` | §8 | 800 | Create CloudWatch dashboard with hop-by-hop latency metrics (GuardrailLatency, InvocationLatency, guardrailProcessingLat… |
| `C-s8-checkitem-014` | §8 | 803 | Enable distributed tracing across all agent components |
| `C-s8-checkitem-015` | §8 | 804 | Create operational runbook for latency spike investigation |
| `C-s8-checkitem-016` | §8 | 808 | Enable AgentCore Evaluations (online mode) for continuous quality assessment — verify PrivateLink posture first if in a … |
| `C-s8-checkitem-017` | §8 | 809 | Establish baseline latency measurements for each hop |
| `C-s8-checkitem-018` | §8 | 810 | Run AgentCore Optimization Recommendations when quality degrades |
| `C-s8-checkitem-019` | §8 | 811 | Validate with batch evaluations before A/B testing |
| `C-s8-checkitem-020` | §8 | 812 | Implement A/B testing via Gateway traffic splitting |
| `C-s8-checkitem-021` | §8 | 813 | Document optimization cycles and threshold tuning decisions |
| `C-s8-checkitem-022` | §8 | 817 | Review guardrail policies quarterly — remove redundant checks |
| `C-s8-checkitem-023` | §8 | 818 | Monitor latency trends — adjust as model/traffic patterns change |
| `C-s8-checkitem-024` | §8 | 819 | Update Cedar policies as new tools are added |
| `C-s8-checkitem-025` | §8 | 820 | Revisit threshold values based on false positive/negative rates |

**7 claim(s)** — Decision-matrix recommendation per content risk. The capability behind each cell is tested by F1/F3/F8; the recommendation itself is a value judgement.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-appA-trow-002` | Appendix A | 906 | **Violent Content** \|\| ✅ MEDIUM \|\| ✅ LOW \|\| ❌ \|\| ✅ MEDIUM |
| `C-appA-trow-003` | Appendix A | 907 | **Sexual Content** \|\| ✅ MEDIUM \|\| ✅ LOW \|\| ❌ \|\| ✅ MEDIUM |
| `C-appA-trow-004` | Appendix A | 908 | **Hate Speech** \|\| ✅ MEDIUM \|\| ✅ LOW \|\| ❌ \|\| ✅ MEDIUM |
| `C-appA-trow-006` | Appendix A | 910 | **Denied Topics** \|\| ❌ \|\| ✅ \|\| ❌ \|\| ✅ |
| `C-appA-trow-007` | Appendix A | 911 | **Word Blocklist** \|\| ❌ \|\| ✅ \|\| ❌ \|\| ✅ |
| `C-appA-trow-008` | Appendix A | 912 | **Hallucination** \|\| ❌ \|\| ❌ \|\| ❌ \|\| ✅ (Contextual Grounding / Automated Reasoning, detect-only) |
| `C-appA-trow-009` | Appendix A | 913 | **Tool Authorization** \|\| ❌ \|\| ❌ \|\| ✅ (Cedar) \|\| ❌ |

**5 claim(s)** — Design principle: a prescription, not a proposition. Operationalized where it makes a measurable prediction (principles 2 and 3, see OVERRIDES).

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s7-1-trow-001` | §7.1 | 751 | 1 \|\| **Layer guardrails by risk, not by feature** \|\| Not every checkpoint needs every policy. Match guardrail scope … |
| `C-s7-1-trow-004` | §7.1 | 754 | 4 \|\| **Monitor every hop independently** \|\| End-to-end latency hides which hop is degrading. Use distributed tracing… |
| `C-s7-1-trow-005` | §7.1 | 755 | 5 \|\| **Deduplicate policies across layers** \|\| If Gateway Guardrails handle prompt attacks, don't repeat the same ch… |
| `C-s7-1-trow-006` | §7.1 | 756 | 6 \|\| **Batch for high-throughput** \|\| Use content-array batching for ApplyGuardrail API calls. Treat caching as a la… |
| `C-s7-1-trow-007` | §7.1 | 757 | 7 \|\| **Set latency budgets per hop** \|\| Define acceptable latency for each checkpoint and alert when exceeded. |

**4 claim(s)** — Recommended guardrail distribution: a configuration recommendation. The underlying capabilities are tested by F1/F3; whether this particular distribution is 'recommended' is a value judgement.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s7-3-trow-001` | §7.3 | 777 | **Gateway (Input)** \|\| Prompt Attack (HIGH threshold), Content Filter (MEDIUM) \|\| Fast early blocking of obvious thr… |
| `C-s7-3-trow-003` | §7.3 | 779 | **Cedar Policy (Tool Auth)** \|\| Tool-level allow/deny, parameter validation \|\| Deterministic authorization — no ML o… |
| `C-s7-3-trow-004` | §7.3 | 780 | **Tool I/O Guardrails** \|\| Sensitive Info (PII on tool responses); Prompt Attack on external/untrusted tool responses … |
| `C-s7-3-trow-005` | §7.3 | 781 | **Bedrock Guardrails (Output)** \|\| Content Filter, Sensitive Info, Contextual Grounding (within its character limits) … |

## 5. Class D — definitional claims (the document's own framework)

94 claims.

The document's own conventions, diagram labels, table headers, metadata and change log. §2.1 says outright that the hop numbering is this document's framework and that AWS documentation has no hop concept. A convention can be useful or useless but not true or false, so there is nothing to measure. Grouped by reason.

**22 claim(s)** — Hop numbering is explicitly declared as this document's own framework ('AWS documentation has no hop concept'). A naming convention cannot be false, only useful or not. Classifying it D rather than manufacturing a test is the correct scientific answer.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s2-1-prose-001` | §2.1 | 43 | The hop numbering is **this document's own framework** (AWS documentation has no "hop" concept). |
| `C-s2-1-prose-002` | §2.1 | 43 | The table and the sequence diagram below are the normative definition; every other section, table, and diagram in this d… |
| `C-s2-1-trow-001` | §2.1 | 47 | 1 \|\| AgentCore Gateway Policy Guardrails (input) \|\| BEFORE |
| `C-s2-1-trow-002` | §2.1 | 48 | 2 \|\| Bedrock Guardrails — input evaluation (or ApplyGuardrail) \|\| BEFORE |
| `C-s2-1-trow-003` | §2.1 | 49 | 3 \|\| Model inference (not a guardrail checkpoint; included for the latency budget) \|\| DURING |
| `C-s2-1-trow-004` | §2.1 | 50 | 4 \|\| Agent-to-tool authorization (Cedar Policy) \|\| DURING |
| `C-s2-1-trow-005` | §2.1 | 51 | 5 \|\| Tool request/response guardrails (Gateway Policy) \|\| DURING |
| `C-s2-1-trow-006` | §2.1 | 52 | 6 \|\| Bedrock Guardrails — output evaluation \|\| AFTER |
| `C-s2-1-mermaid-001` | §2.1 | 56 | request |
| `C-s2-1-mermaid-003` | §2.1 | 56 | forward |
| `C-s2-1-mermaid-004` | §2.1 | 56 | prompt |
| `C-s2-1-mermaid-006` | §2.1 | 56 | pass |
| `C-s2-1-mermaid-007` | §2.1 | 56 | invoke |
| `C-s2-1-mermaid-008` | §2.1 | 56 | Hop #3 — model inference (latency budget only) |
| `C-s2-1-mermaid-009` | §2.1 | 56 | tool-call decision |
| `C-s2-1-mermaid-010` | §2.1 | 56 | tool call |
| `C-s2-1-mermaid-012` | §2.1 | 56 | invoke tool |
| `C-s2-1-mermaid-013` | §2.1 | 56 | tool response |
| `C-s2-1-mermaid-015` | §2.1 | 56 | filtered result |
| `C-s2-1-mermaid-016` | §2.1 | 56 | continue inference |
| `C-s2-1-mermaid-017` | §2.1 | 56 | final answer |
| `C-s2-1-mermaid-018` | §2.1 | 56 | response |

**20 claim(s)** — Table header row — column labels, not a proposition. The claims live in the body rows.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-aws-bedrock-agentcore-before-during-afte-thead-001` | `aws-bedrock-agentcore-before-during-afte` | 5 | **Field** \|\| **Value** |
| `C-s2-1-thead-001` | §2.1 | 45 | Hop \|\| Checkpoint \|\| Phase |
| `C-s3-4-thead-001` | §3.4 | 245 | \|\| **Classic tier** \|\| **Standard tier** |
| `C-s4-4-thead-001` | §4.4 | 387 | Framework hook concept \|\| AgentCore primitive \|\| Enforcement location |
| `C-s4-4-thead-002` | §4.4 | 400 | # \|\| Bypass route \|\| Closure |
| `C-s4-5-2-thead-001` | §4.5.2 | 462 | Mode \|\| Reachability \|\| Containment verdict |
| `C-s4-5-3-thead-001` | §4.5.3 | 472 | Service \|\| Data plane \|\| Control plane |
| `C-s6-1-thead-001` | §6.1 | 622 | **Hop #** \|\| **Checkpoint** \|\| **Service** \|\| **Typical Latency Range** \|\| **Monitoring Metric** |
| `C-agentcore-gateway-metrics-thead-001` | `agentcore-gateway-metrics` | 640 | **Metric** \|\| **Description** \|\| **Use** |
| `C-agentcore-policy-metrics-thead-001` | `agentcore-policy-metrics` | 654 | **Metric** \|\| **Description** \|\| **Use** |
| `C-bedrock-guardrails-metrics-thead-001` | `bedrock-guardrails-metrics` | 672 | **Metric** \|\| **Description** \|\| **Use** |
| `C-bedrock-runtime-metrics-thead-001` | `bedrock-runtime-metrics` | 686 | **Metric** \|\| **Description** \|\| **Use** |
| `C-agentcore-runtime-session-metrics-thead-001` | `agentcore-runtime-session-metrics` | 693 | **Metric** \|\| **Description** \|\| **Use** |
| `C-s6-4-thead-001` | §6.4 | 723 | **Alert** \|\| **Condition** \|\| **Action** |
| `C-s7-1-thead-001` | §7.1 | 749 | **#** \|\| **Principle** \|\| **Rationale** |
| `C-s7-2-thead-001` | §7.2 | 761 | **Anti-Pattern** \|\| **Problem** \|\| **Recommendation** |
| `C-s7-3-thead-001` | §7.3 | 775 | **Hop** \|\| **Recommended Policies** \|\| **Rationale** |
| `C-s10-thead-001` | §10 | 872 | **Topic** \|\| **URL** |
| `C-appA-thead-001` | Appendix A | 903 | **Content Risk** \|\| **Gateway (Hop#1)** \|\| **Input Guard (Hop#2)** \|\| **Tool I/O (Hop#5)** \|\| **Output Guard (Ho… |
| `C-appB-thead-001` | Appendix B | 917 | **Technique** \|\| **Description** \|\| **Latency Reduction** |

**19 claim(s)** — Change log v1.1 -> v1.2: statements about the document's own edit history. Self-referential and verifiable only by diffing v1.1 against v1.2, which is a provenance check rather than a claim about AWS.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-appC-numitem-002` | Appendix C | 934 | Default policy thresholds clarified: applied only via the natural-language authoring service; hand-written Cedar require… |
| `C-appC-numitem-003` | Appendix C | 935 | AgentCore Optimization "(Preview)" label removed — the service is GA (Accelerator v2.9 service table). |
| `C-appC-numitem-004` | Appendix C | 936 | Optimization capabilities corrected to Recommendations / Configuration Bundles / A/B Testing; Batch Evaluation reassigne… |
| `C-appC-numitem-005` | Appendix C | 937 | Parallel-evaluation claims scoped to what AWS documents (input evaluation only); removed for Gateway policy. |
| `C-appC-numitem-006` | Appendix C | 938 | best-practices.html reference relabeled — that page covers AgentCore Memory, not guardrails. |
| `C-appC-numitem-007` | Appendix C | 939 | Unofficial "190x" / "80–90%" figures removed from Appendix B (already removed from §3.3 in v1.1). |
| `C-appC-numitem-008` | Appendix C | 940 | §6.4 alert condition corrected from FirstByteLatency to Latency. |
| `C-appC-numitem-009` | Appendix C | 941 | Hop numbering unified (1–6, Model Inference = Hop #3) across headings, Executive Summary, tables, and diagrams. |
| `C-appC-numitem-010` | Appendix C | 945 | Caching guidance rewritten with strict constraints (§3.3 BP#1). |
| `C-appC-numitem-011` | Appendix C | 946 | Async output evaluation aligned to official streaming modes with masking/leakage warnings (§5.1 BP#1). |
| `C-appC-numitem-012` | Appendix C | 947 | Appendix A now recommends prompt-attack screening on untrusted tool responses (indirect prompt injection). |
| `C-appC-prose-003` | Appendix C | 949 | **Additions:** ENFORCE default-deny permit gotcha; two-level LOG_ONLY precedence + UpdateGateway risk; prompt-attack inp… |
| `C-appC-prose-004` | Appendix C | 951 | **New section:** §4.4 Non-Bypassable Per-Tool-Use Hooks (agent containment pattern) — maps framework-style Pre/PostToolU… |
| `C-appC-prose-005` | Appendix C | 953 | **New section:** §2.1 Hop Numbering — declares the hop framework as this document's own (not an AWS concept) and anchors… |
| `C-appC-prose-006` | Appendix C | 955 | **Post-review refinements (external agent review, 2026-08-08):** §6.2 Policy table gained MismatchErrors family + non-ex… |
| `C-appC-prose-007` | Appendix C | 957 | **New section:** §4.5 Network Containment — makes bypass route #2 executable: Runtime egress lockdown (S3 Gateway-endpoi… |
| `C-appC-prose-008` | Appendix C | 957 | Connectivity design deliberately out of scope. §8 Phase 1 checklist gains a network-containment item. |
| `C-appC-prose-009` | Appendix C | 959 | **Format change (v1.2):** this Markdown file is the canonical version of the document, with Mermaid diagrams for human- … |
| `C-appC-prose-010` | Appendix C | 959 | The .docx lineage ends at v1.1; regenerate Word/PDF exports from this file if needed. |

**16 claim(s)** — Reference-architecture diagram labels restate claims made in prose elsewhere. Testable content is merged into the canonical claim via MERGE_GROUPS; the remaining labels are structural.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s9-mermaid-001` | §9 | 827 | User |
| `C-s9-mermaid-002` | §9 | 827 | BEFORE — Input Safety |
| `C-s9-mermaid-005` | §9 | 827 | pass |
| `C-s9-mermaid-007` | §9 | 827 | violation |
| `C-s9-mermaid-009` | §9 | 827 | DURING — Execution Control |
| `C-s9-mermaid-013` | §9 | 827 | Observability: Traces / Spans / Metrics → CloudWatch |
| `C-s9-mermaid-014` | §9 | 827 | DENY |
| `C-s9-mermaid-016` | §9 | 827 | traces |
| `C-s9-mermaid-017` | §9 | 827 | AFTER — Output Safety + Continuous Improvement |
| `C-s9-mermaid-019` | §9 | 827 | Response to User |
| `C-s9-mermaid-020` | §9 | 827 | AgentCore Evaluations (Online sampling / Batch jobs / On-demand spans) |
| `C-s9-mermaid-021` | §9 | 827 | AgentCore Optimization · Recommendations (analyze traces) · Batch Evaluation via Evaluations (offline validation) · A/B … |
| `C-s9-mermaid-022` | §9 | 827 | Configuration Bundles (versioned, immutable) → updated system prompts → updated tool descriptions → adjusted guardrail t… |
| `C-s9-mermaid-023` | §9 | 827 | Block / Mask |
| `C-s9-mermaid-024` | §9 | 827 | spans feed evaluation |
| `C-s9-mermaid-025` | §9 | 827 | CLOSED LOOP: deploy updated config |

**7 claim(s)** — Architecture-overview diagram labels: phase names and grouping, the document's own organizing frame.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s2-mermaid-001` | §2 | 25 | BEFORE — Input Safety |
| `C-s2-mermaid-002` | §2 | 25 | Gateway Guardrail + Input Guardrail |
| `C-s2-mermaid-003` | §2 | 25 | DURING — Execution Control |
| `C-s2-mermaid-004` | §2 | 25 | Agent Runtime + Tool Auth (Cedar) + Observability |
| `C-s2-mermaid-005` | §2 | 25 | AFTER — Output Safety + Continuous Improvement |
| `C-s2-mermaid-006` | §2 | 25 | Output Guardrail + Evaluation + Optimization |
| `C-s2-mermaid-007` | §2 | 25 | FEEDBACK LOOP (updated prompts, policies, thresholds) |

**4 claim(s)** — Document metadata (version, date, scope, audience) — properties of the document, not of AWS.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-aws-bedrock-agentcore-before-during-afte-trow-001` | `aws-bedrock-agentcore-before-during-afte` | 7 | **Version** \|\| 1.2 |
| `C-aws-bedrock-agentcore-before-during-afte-trow-002` | `aws-bedrock-agentcore-before-during-afte` | 8 | **Date** \|\| August 8, 2026 |
| `C-aws-bedrock-agentcore-before-during-afte-trow-003` | `aws-bedrock-agentcore-before-during-afte` | 9 | **Scope** \|\| End-to-end guardrails architecture for agents deployed on Amazon Bedrock AgentCore Runtime |
| `C-aws-bedrock-agentcore-before-during-afte-trow-004` | `aws-bedrock-agentcore-before-during-afte` | 10 | **Audience** \|\| Solutions Architects, Technical Account Managers, Builder Community |

**1 claim(s)** — Provenance statement about the document's own sources, not a claim about AWS behaviour. Verified by the release gate (NDA downgrade pass), not by experiment.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-aws-bedrock-agentcore-before-during-afte-trow-005` | `aws-bedrock-agentcore-before-during-afte` | 11 | **References** \|\| AWS Official Documentation; Amazon Bedrock AgentCore Service Approval Accelerator v2.9 (2026-07-13) |

**1 claim(s)** — Cross-reference stating that Hop #3 (model inference) is not a guardrail checkpoint. This is a consequence of the document's own hop numbering from 2.1, which is definitional; there is no AWS behaviour that could make it false. The latency of Hop #3 IS measured, as part of F6-6's end-to-end total.

Capability covered by: `F6-6`

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s4-prose-001` | §4 | 276 | (Hop #3 — model inference — is not a guardrail checkpoint; it appears in the latency budget in Section 6.1.) |

**1 claim(s)** — Source caveat about NDA provenance — a statement about this document's sourcing, tracked by the release gate rather than by experiment.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s4-5-quote-001` | §4.5 | 446 | Source caveat: most facts in this section come from the Accelerator v2.9 (NDA document); public AWS documentation covers… |

**1 claim(s)** — The document's own disclaimer that the table is illustrative. Not a claim about AWS; it is the statement this entire project exists to render unnecessary.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s6-1-quote-001` | §6.1 | 620 | **Disclaimer:** The latency figures in the table below are illustrative estimates for capacity-planning purposes only — … |

**1 claim(s)** — Cross-reference to the hop numbering defined in 2.1. A pointer to the document's own convention carries no independent truth value. What span names actually appear IS tested, by F7-4 over aws/spans.

Capability covered by: `F7-4`

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s6-3-prose-002` | §6.3 | 701 | Hop labels follow the normative numbering in Section 2.1. |

**1 claim(s)** — Checklist phase label ('Phase 1: Foundation' and similar). An organizing heading for the checklist below it, not a claim; the checklist items themselves are triaged individually, and the testable ones are overridden to E/S/C/O.

| Claim | §  | Line | Text |
|:--|:--|--:|:--|
| `C-s8-prose-003` | §8 | 806 | **Phase 3: Optimization** |

## 6. Designed experiments with no claim to serve

The inverse bookkeeping: cases that exist in the registry but that no claim cites. Left in deliberately, each with a written justification, so the exclusion story points at a designed-but-unrunnable experiment rather than at nothing.

### `F1-21` — PutEnforcedGuardrailConfiguration surface and required fields

- **Family** F1 · **class** C
- **Oracle** TRUE if guardrailVersion and modelEnforcement.includedModels are required as modelled; FALSE if either is optional in practice
- **Why no claim cites it** Prerequisite for F5-9. Establishes the PutEnforcedGuardrailConfiguration surface and its required fields WITHOUT applying enforcement, so the 5c blast-radius controls are validated before the <=5-minute live window opens. The document does not describe this API; only its consequence (an agent cannot decline an account-level guardrail) is claimed, and that is F5-9.

### `F1-4` — PolicyDefinition union accepts cedar and/or policy

- **Family** F1 · **class** C
- **Oracle** TRUE if exactly one arm is accepted per call; FALSE if both-at-once succeeds or if either single arm is rejected
- **Why no claim cites it** Prerequisite, not a claim. FINDING-F1-1 discovered that PolicyDefinition is a union with non-deprecated `cedar` AND `policy` arms. The document predates that surface and says nothing about it, so no claim maps here. But the harness must know which arm to send or every F1-F5 gateway test fails for an unrelated reason. Run in Phase 3 as a platform pre-flight.

### `F9-1` — Policy evaluation timeout yields automatic DENY

- **Family** F9 · **class** X
- **Oracle** Would be TRUE if an induced service-side evaluation timeout produced DENY. NOT TESTABLE: AgentCore exposes no fault-injection surface for policy evaluation. Nearest proxies are F5-4a (unevaluable policy) and F5-4b (guardrail evaluation impossible)
- **Why no claim cites it** Cited by no claim BY CONSTRUCTION: every claim it would serve is class X (C-s3-1-bullet-014-a, C-s4-1-bullet-008-a, C-s9-mermaid-011-c), and X claims carry an exclusion reason instead of a case. The case is retained in the registry so the exclusion register can point at a designed-but-unrunnable experiment rather than at nothing.

## 7. How to audit this register

```sh
python3 claims/01_triage.py --check           # triage.csv reproduces from the rules
python3 claims/check_coverage.py              # 15 checks over every claim
python3 claims/check_coverage.py --self-test  # the checks can still fail
python3 claims/03_exclusion_register.py --check   # this file matches the triage
```

The second and third commands matter together. `check_coverage.py` enforces that an untested claim carries a substantive reason and that an X claim names a remedy; `--self-test` mutates the triage 14 ways and requires the named check to fire on each, with a control arm proving no check fires on clean input. A gate that passed unconditionally would certify this register without reading it.

