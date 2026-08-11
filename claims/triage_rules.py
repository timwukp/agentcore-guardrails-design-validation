#!/usr/bin/env python3
"""Curated triage rules: the classification layer over claims_raw.csv.

Why rules and not 535 hand-typed rows
-------------------------------------
Large blocks of the document are genuinely homogeneous — the 24 rows of §10 are
all documentation pointers, the 25 mermaid labels of §9 are all restatements of
claims made in prose elsewhere. Hand-typing a row for each would produce 535
opportunities for a transcription error and would hide the *reasoning*, which is
what a reviewer needs to audit.

So classification lives here as data: rules keyed by (anchor, unit_type,
ordinals), with exact-claim_id OVERRIDES wherever a rule would be wrong. The
resolution order is strict and every claim records which rule assigned it, so any
row can be traced back to a stated reason.

Class definitions (exactly one per claim)
----------------------------------------
E  empirical-deterministic  — a single well-designed trial settles it
S  statistical              — requires n, a CI, and a pre-registered decision rule
C  config-surface / API truth — settled by the service model or a control-plane call
O  observability-truth      — settled by what CloudWatch/spans actually emit
D  definitional             — the document's own framework. NOT falsifiable, and
                              saying so is the correct scientific answer, not a dodge
N  normative                — a value judgement ("use least privilege"). Either
                              operationalized into an S-claim with a stated
                              assumption, or excluded with a reason. NEVER silently
                              scored "passed"
X  excluded-but-testable-in-principle — mandatory reason + what would be needed

The asymmetry that governs the defaults: an unclassified claim is invisible, an
over-included one just gets triaged with a written reason. So the fallthrough is
X-with-reason, never silent omission.
"""

from __future__ import annotations

# ===========================================================================
# CASE REGISTRY
# ===========================================================================
# Each case: (family, title, cls, oracle, method)
# `oracle` states what observation would make the claim TRUE and what would make
# it FALSE. A case without a falsifying observation is not a test, and
# check_coverage.py rejects it.

CASES: dict[str, tuple[str, str, str, str, str]] = {
    # ---------------- F0 the document's own referential integrity ----------------
    "F0-1": ("F0", "Section 10's documentation references resolve", "O",
             "TRUE if every §10 URL returns HTTP 200 AND its page title shares a content "
             "word with the row's stated title; FALSE for any non-200, or any page whose "
             "title is unrelated to what the row says lives there — a link that resolves "
             "to the wrong page is worse than a 404, because the reader believes they "
             "have been handed a source",
             "claims/02_check_references.py — HTTP GET + title comparison, $0, no AWS; "
             "no-network exits 3 (SKIP) so an offline run cannot read as green"),

    # ---------------- F1 config surface / API truth ----------------
    "F1-1": ("F1", "enforcementMode exists in the policy API", "C",
             "TRUE if CreatePolicy models enforcementMode with enum {ACTIVE,LOG_ONLY}; "
             "FALSE if absent from every released botocore model",
             "offline service-model bisect over pip-downloaded wheels [DONE: first at 1.43.32]"),
    "F1-2": ("F1", "InvokeGuardrailChecks exists in bedrock-runtime", "C",
             "TRUE if the operation is present in the service model; FALSE if absent",
             "offline service-model bisect [DONE: first at 1.43.30]"),
    "F1-3": ("F1", "The bare permit policy fails creation under default validationMode", "C",
             "TRUE if CreatePolicy with 'permit(principal, action, resource is "
             "AgentCore::Gateway);' and no validationMode reaches CREATE_FAILED with an "
             "Overly Permissive finding; FALSE if it reaches a usable state",
             "paired CreatePolicy: default vs IGNORE_ALL_FINDINGS; read status + statusReasons"),
    "F1-4": ("F1", "PolicyDefinition union accepts cedar and/or policy", "C",
             "TRUE if exactly one arm is accepted per call; FALSE if both-at-once succeeds "
             "or if either single arm is rejected",
             "three arms: cedar-only, policy-only, both (third expected rejected)"),
    "F1-5": ("F1", "Engine mode enum is LOG_ONLY|ENFORCE", "C",
             "TRUE if GatewayPolicyEngineMode enumerates exactly these two; FALSE otherwise",
             "service model read + CreatePolicyEngine round-trip"),
    "F1-6": ("F1", "Tier fields: Standard requires crossRegionConfig", "C",
             "TRUE if CreateGuardrail with tier=STANDARD and no crossRegionConfig is "
             "rejected and CLASSIC is accepted without it; FALSE if either succeeds anyway",
             "paired CreateGuardrail across tier x crossRegionConfig"),
    "F1-7": ("F1", "Content filter categories", "C",
             "TRUE if the enum is exactly {VIOLENCE,HATE,SEXUAL,MISCONDUCT,INSULTS,"
             "PROMPT_ATTACK}; FALSE if the set differs from the document's list",
             "service model enum read + CreateGuardrail acceptance per category"),
    "F1-8": ("F1", "Prompt-attack subtypes JAILBREAK/PROMPT_INJECTION/PROMPT_LEAKAGE", "C",
             "TRUE if all three are accepted by the guardrails-in-policy PromptAttack "
             "constructor; FALSE if any is rejected",
             "CreatePolicy per subtype; PROMPT_LEAKAGE expected Standard-tier only"),
    "F1-9": ("F1", "Sensitive-information entity types", "C",
             "TRUE if the SDK enumerates the entity set the corpus targets; FALSE if the "
             "documented set and the model disagree",
             "service model enum read, cross-checked against the 108-case PII corpus"),
    "F1-10": ("F1", "Denied topics and word filters exist with documented limits", "C",
              "TRUE if topic definition accepts 200 chars on CLASSIC and 1000 on STANDARD "
              "and rejects 201/1001; FALSE if the boundary differs",
              "boundary probe at limit and limit+1 per tier"),
    "F1-11": ("F1", "Input and output settings are independent within one guardrail", "C",
              "TRUE if inputStrength != outputStrength and inputAction != outputAction "
              "are accepted and read back distinct; FALSE if one overwrites the other",
              "CreateGuardrail with asymmetric settings, then GetGuardrail"),
    "F1-12": ("F1", "streamProcessingMode SYNCHRONOUS|ASYNCHRONOUS", "C",
              "TRUE if both values are accepted and SYNCHRONOUS is the default when "
              "omitted; FALSE if the default differs",
              "service model default + omitted-field round-trip"),
    "F1-13": ("F1", "Contextual grounding character limits 100000/1000/5000", "C",
              "TRUE if calls at each limit succeed and at limit+1 are rejected; FALSE if "
              "any boundary differs from the documented number",
              "ApplyGuardrail boundary probe on each of the three fields"),
    "F1-14": ("F1", "Automated Reasoning: detect-only, en-US, no streaming", "C",
              "TRUE if the SDK exposes no enforce mode, rejects non-en-US, and rejects "
              "streaming; FALSE if any is permitted",
              "service model read + rejection probes"),
    "F1-15": ("F1", "Policy applies to MCP, HTTP runtime, and HTTP inference targets", "C",
              "TRUE if a policy engine attaches and evaluates on all three target types; "
              "FALSE if any target type bypasses policy evaluation",
              "one gateway target per type, same policy, compare decisions"),
    "F1-16": ("F1", "REQUEST/RESPONSE Lambda interceptors exist", "C",
              "TRUE if both interceptor types are configurable on a gateway and fire; "
              "FALSE if absent from the API",
              "service-model read + echo-Lambda interceptor invocation"),
    "F1-17": ("F1", "suppressOutput is a valid policy effect", "C",
              "TRUE if a policy using suppressOutput is accepted and suppresses tool "
              "output; FALSE if the effect is rejected",
              "CreatePolicy + end-to-end tool call through the echo Lambda"),
    "F1-18": ("F1", "Confidence scores are the discrete lattice {0,.2,.4,.6,.8,1.0}", "C",
              "TRUE if every observed ConfidenceScore across >=500 evaluations lies on "
              "the lattice; FALSE if any intermediate value appears",
              "harvest scores from F2/F3 runs; set-membership test on the union"),
    "F1-19": ("F1", "Threshold defaults 0.2/0.4/0.6 apply only via NL authoring", "C",
              "TRUE if hand-written Cedar omitting a threshold is REJECTED while NL "
              "authoring fills the documented defaults; FALSE if hand-written policies "
              "silently receive defaults",
              "paired CreatePolicy (hand-written, no threshold) vs StartPolicyGeneration"),
    "F1-20": ("F1", "InvokeGuardrailChecks caps at 10 content blocks per message", "C",
              "TRUE if 10 blocks succeed and 11 are rejected; FALSE if the boundary differs",
              "boundary probe at 10 and 11"),
    "F1-21": ("F1", "PutEnforcedGuardrailConfiguration surface and required fields", "C",
              "TRUE if guardrailVersion and modelEnforcement.includedModels are required "
              "as modelled; FALSE if either is optional in practice",
              "service-model read + omitted-field rejection probes (no enforcement applied)"),
    "F1-22": ("F1", "Optimization exposes Recommendations/ConfigBundles/A-B Testing", "C",
              "TRUE if all three API groups exist and Batch Evaluation belongs to "
              "Evaluations; FALSE if the capability split differs",
              "service-model operation enumeration for both services"),
    "F1-23": ("F1", "Evaluations exposes on-demand, batch, and online modes", "C",
              "TRUE if all three are configurable; FALSE if any is absent",
              "service-model operation enumeration"),
    "F1-24": ("F1", "when {} cannot be mixed with when guardrails {} in one policy", "C",
              "TRUE if a policy mixing both condition forms is rejected; FALSE if accepted",
              "CreatePolicy mutation: mixed policy vs two separate policies"),
    "F1-25": ("F1", "Guardrails-in-policy has no regex/pattern matching", "C",
              "TRUE if the policy grammar rejects a regex construct in a guardrails "
              "condition; FALSE if any pattern-matching form is accepted",
              "CreatePolicy with a regex-shaped condition, expect rejection"),
    "F1-26": ("F1", "Word filters support EN/FR/ES only, on either tier", "C",
              "TRUE if a non-EN/FR/ES word filter is rejected or provably inert on both "
              "tiers; FALSE if it blocks correctly",
              "word filter x language x tier matrix via ApplyGuardrail"),
    "F1-27": ("F1", "Reasoning/CoT content blocks are excluded from guardrail evaluation", "C",
              "TRUE if identical violating text placed in a reasoning block is not "
              "intervened while the same text in a normal block is; FALSE if both block",
              "paired Converse with violating text in reasoningContent vs text block"),
    "F1-28": ("F1", "PII is not detected inside tool_use output parameters", "C",
              "TRUE if PII in a tool_use parameter passes while identical PII in message "
              "text is masked; FALSE if both are handled",
              "paired ApplyGuardrail/Converse with PII in tool_use vs text"),

    # ---------------- F2 policy determinism ----------------
    "F2-1": ("F2", "Pure-Cedar policies are deterministic", "S",
             "TRUE if 0 decision flips in n=300 identical calls to a policy with no "
             "guardrail term; FALSE if >=1 flip (H0: p_flip=0, one counterexample suffices)",
             "n=300 identical calls, Clopper-Pearson upper bound reported either way"),
    "F2-2": ("F2", "Guardrail scores are non-degenerate across identical inputs", "S",
             "TRUE (non-deterministic) if >=2 distinct scores appear for one fixed input "
             "in n=300; FALSE (degenerate) if exactly one value appears",
             "n=300 identical inputs, harvest per-trial ConfidenceScore, estimate pmf"),
    "F2-3": ("F2", "The decision is a deterministic function of the score", "S",
             "TRUE if every score stratum is pure (P(D=1|S=s) in {0,1}); FALSE if any "
             "stratum is mixed — one mixed stratum falsifies outright, probability 0 under H0",
             "stratify F2-2 trials by observed score; variance_decomposition()"),
    "F2-4": ("F2", "Flip rate tracks threshold placement as 2p(1-p)", "S",
             "TRUE if flip rate rises to the predicted 2p(1-p) with tau inside the score "
             "support and returns to ~0 outside it; FALSE if flip rate is insensitive to tau",
             "mutation arm: tau inside vs outside observed support, n=300 each"),
    "F2-5": ("F2", "ApplyGuardrail is non-deterministic for a fixed input", "S",
             "TRUE if >=1 differing verdict or score in n=300 identical ApplyGuardrail "
             "calls; FALSE if all 300 are byte-identical in verdict and score",
             "n=300 identical ApplyGuardrail calls (Phase 1, no gateway needed)"),

    # ---------------- F3 detection efficacy ----------------
    "F3-1": ("F3", "Content filters detect their categories above threshold", "S",
             "Per category: recall point estimate with Wilson CI at each of 7 operating "
             "points; FALSE for the document's implied efficacy if the CI lower bound at "
             "the recommended threshold is below 0.5",
             "corpus per category x 7 thresholds, ApplyGuardrail"),
    "F3-2": ("F3", "Benign content is not blocked (FPR)", "S",
             "TRUE if the Wilson upper bound on FPR at the recommended threshold is "
             "<5% (n>=60 per the rule-of-three table); FALSE otherwise",
             "benign corpus n>=60 per category"),
    "F3-3": ("F3", "Hard negatives do not trigger filters", "S",
             "TRUE if the Wilson upper bound on FPR over benign text that superficially "
             "resembles attacks is <10% at the recommended threshold; FALSE if the "
             "LOWER bound exceeds 10%, which would mean the recommended configuration "
             "blocks legitimate traffic at a rate the document never warns about",
             "hard-negative corpus n>=60"),
    "F3-4": ("F3", "PII entities are detected per documented entity type", "S",
             "Per-entity recall with Wilson CI; FALSE for any entity whose CI upper bound "
             "is below 0.5 despite being documented as supported",
             "reuse the 108-case PII corpus, extended to the SDK entity list"),
    "F3-5": ("F3", "Denied topics block in-topic content", "S",
             "TRUE if in-topic recall's Wilson lower bound exceeds the off-topic FPR's "
             "Wilson upper bound (the intervals are disjoint, so the filter "
             "discriminates); FALSE if the intervals overlap, which would mean the "
             "topic definition carries no discriminating power",
             "topic corpus + off-topic controls, n>=60 each"),
    "F3-6": ("F3", "Word filters block listed terms exactly", "E",
             "TRUE if every listed term blocks and no unlisted near-miss does; FALSE on "
             "any miss or any near-miss block",
             "exact-match probe: listed terms, casings, substrings, unlisted near-misses"),
    "F3-7": ("F3", "Contextual grounding detects ungrounded responses", "S",
             "TRUE if the ungrounded-detection rate's Wilson lower bound exceeds the "
             "grounded-pair FPR's upper bound; FALSE if the intervals overlap, i.e. the "
             "check cannot tell grounded from ungrounded within the documented limits",
             "grounded vs ungrounded pairs, n>=60"),
    "F3-8": ("F3", "Prompt-attack detection recall by subtype", "S",
             "TRUE if every subtype's recall Wilson lower bound exceeds 0.5 at the "
             "recommended threshold; FALSE for any subtype whose UPPER bound is below "
             "0.5 despite the document listing it as supported. Between-subtype "
             "differences by BH-adjusted McNemar are secondary",
             "prompt-attack corpus split by JAILBREAK/INJECTION/LEAKAGE, n>=60 each"),
    "F3-9": ("F3", "The 7-vertex ROC and the selected operating point", "S",
             "TRUE if the reachable operating points number <=7 and Youden's J is "
             "maximized at an interior threshold, so the document's recommended "
             "threshold is defensible; FALSE if J is maximized at tau=0 or tau=1 (the "
             "score carries no usable signal) or if more than 7 distinct points appear "
             "(the lattice claim F1-18 is wrong). Every point reported with PPV at "
             "pi in {.001,.01,.1}",
             "sweep tau over the score lattice on the pooled corpus"),
    "F3-10": ("F3", "Section 7.1's workflow is executable from LOG_ONLY telemetry", "O",
              "TRUE if a per-request score<->label join is recoverable from CloudWatch "
              "metrics alone; FALSE if 1-minute aggregation destroys the linkage, in which "
              "case a reader following 7.1 cannot compute precision at all",
              "attempt reconstruction from metrics only, then from aws/spans; compare to "
              "the ground-truth join from the evidence store"),
    "F3-11": ("F3", "Guardrail behaviour drifts under AWS auto-updates", "S",
              "TRUE if the +7d or +30d re-run differs from baseline by more than the "
              "paired-bootstrap CI; FALSE if within CI",
              "re-run the fixed corpus at +7d and +30d, McNemar on paired verdicts"),

    # ---------------- F4 enforcement-mode semantics ----------------
    "F4-1": ("F4", "Engine ENFORCE + no permit policy denies all traffic", "E",
             "TRUE if a benign request is denied when only guardrail policies exist; "
             "FALSE if it passes",
             "confirmatory (Bonferroni family); mutation: add baseline permit -> passes"),
    "F4-2": ("F4", "Engine LOG_ONLY blocks nothing even with ACTIVE policies", "E",
             "TRUE if a request that ENFORCE denies passes under LOG_ONLY; FALSE if blocked",
             "paired request under both engine modes, same policy set"),
    "F4-3": ("F4", "Engine mode takes precedence over per-policy enforcementMode", "E",
             "Full 2x2: {engine ENFORCE,LOG_ONLY} x {policy ACTIVE,LOG_ONLY}. TRUE if "
             "engine LOG_ONLY + policy ACTIVE does not block; FALSE if it blocks",
             "confirmatory (Bonferroni family), 4 cells, mutation-paired"),
    "F4-4": ("F4", "Cedar default-deny: no matching policy means deny", "E",
             "TRUE if a request matching no policy is denied; FALSE if allowed",
             "request outside every policy scope"),
    "F4-5": ("F4", "forbid overrides permit", "E",
             "TRUE if a request matching both a permit and a forbid is denied; FALSE otherwise",
             "overlapping permit+forbid pair"),
    "F4-6": ("F4", "Denied requests return HTTP 403 naming the denying policy ID", "E",
             "TRUE if the response is 403 AND the body/headers identify the policy ID; "
             "FALSE if the status differs or the policy ID is absent",
             "capture full response + headers on a denied request"),

    # ---------------- F5 non-bypassability red team ----------------
    "F5-1": ("F5", "Route 1: direct tool invocation bypassing the gateway", "E",
             "TRUE (closed) if the runtime role cannot invoke the tool directly; FALSE "
             "(open) if it can. Mutation: grant lambda:InvokeFunction -> succeeds with no "
             "AuthorizeAction span, proving the deny was load-bearing",
             "assume grx-runtime-exec, direct lambda:InvokeFunction; watchdog active"),
    "F5-2": ("F5", "Route 3: execution-role credentials disable the policy engine", "E",
             "TRUE (closed) if UpdateGateway is denied to the runtime role; FALSE if it "
             "succeeds. Full chain: grant -> LOG_ONLY set -> previously-blocked request "
             "passes -> restore -> re-assert blocking",
             "confirmatory (Bonferroni family); also tests nulling policyEngineConfiguration"),
    "F5-3a": ("F5", "Route 4: SCP authoring and propagation", "E",
              "TRUE if DescribeEffectivePolicy shows the deny on a fresh child OU with a "
              "break-glass exception; FALSE if the policy does not propagate",
              "fresh child OU + SCP; enforcement from inside a member account is F5-3c"),
    "F5-3b": ("F5", "Route 4: IAM permissions boundary blocks UpdateGateway", "E",
              "TRUE if UpdateGateway is denied despite an identity policy granting it; "
              "FALSE if the boundary is ineffective. Mutation: remove boundary -> succeeds",
              "permissions boundary on grx-attacker, re-run the F5-2 attack"),
    "F5-4a": ("F5", "Route 5: policy referencing a nonexistent context path", "E",
              "OUTCOME UNKNOWN — that is the experiment. Records DENY or ALLOW and whether "
              "MismatchErrors/PolicyMismatch fire. Either result is a finding",
              "policy on context.input.doesNotExist; observe decision + metrics"),
    "F5-4b": ("F5", "Route 5: guardrail evaluation cannot run (permission removed)", "E",
              "OUTCOME UNKNOWN. Removing bedrock:InvokeGuardrailChecks from the gateway "
              "role makes guardrail evaluation impossible: DENY (fail-closed) or ALLOW "
              "(fail-open)? Directly interrogates what AWS does not document",
              "remove the permission 3.1 requires, send a violating request; restore + re-verify"),
    "F5-5": ("F5", "Indirect prompt injection via tool response", "S",
             "TRUE if injected tool responses are suppressed at a rate whose Wilson "
             "lower bound exceeds the benign FPR upper bound, AND removing the "
             "suppressOutput policy drops suppression to ~0; FALSE if detection is "
             "indistinguishable from the benign rate, or if the mutation does NOT "
             "invert (the policy was never load-bearing)",
             "echo Lambda returns the payload; suppressOutput + PromptAttack on context.output"),
    "F5-6": ("F5", "Prompt-attack filtering without input tagging (DC-2)", "S",
             "Per-arm recall with Wilson CIs across 4 arms x (60 attacks + 60 benign): "
             "InvokeModel untagged / tagged / Converse without guardContent / Converse with "
             "guardContent on a different block. TRUE for 3.2 if untagged recall CI upper "
             "bound is near 0; FALSE if untagged detection is substantial",
             "pairwise McNemar (BH family); resolves the n=5 finding at adequate power"),
    "F5-7a": ("F5", "PrivateLink endpoint services actually exist", "C",
              "TRUE if describe-vpc-endpoint-services matches the document's coverage "
              "matrix including the claimed Optimization gap; FALSE on any mismatch",
              "read-only enumeration filtered to *bedrock-agentcore* ($0)"),
    "F5-7b": ("F5", "Route 2: VPC egress containment", "E",
              "TRUE if a VPC-mode runtime without a NAT route fails image pull and "
              "succeeds with one; FALSE if egress is reachable either way",
              "mutation must invert in both directions"),
    "F5-8": ("F5", "Execution-role credentials are readable from inside a tool session", "E",
             "TRUE if sts:GetCallerIdentity from inside the session returns the execution "
             "role; FALSE if credentials are unreachable. Confirms 4.4's premise from "
             "PUBLIC evidence, removing an NDA citation",
             "minimal runtime whose handler calls GetCallerIdentity"),
    "F5-9": ("F5", "Account-level enforced guardrail cannot be declined by the agent", "E",
             "TRUE if a model call omitting guardrailConfiguration is still evaluated; "
             "FALSE if the agent can opt out. HARD GATE: requires a model provably unused "
             "by any other system in the account",
             "PutEnforcedGuardrailConfiguration, includedModels=1 unused model, <=5 min, "
             "automatic restore + ListEnforcedGuardrailsConfiguration verification"),

    # ---------------- F6 latency ----------------
    "F6-1": ("F6", "Hop #1 gateway guardrail latency", "S",
             "Measured p50/p90/p99 with distribution-free CIs at n=1000, replacing the "
             "ILLUSTRATIVE 50-200ms. FALSE if the measured p50-p99 band lies outside it",
             "paired grx-gw vs grx-gw-nopolicy, interleaved A,B,A,B"),
    "F6-2": ("F6", "Hop #2 Bedrock input guardrail latency", "S",
             "Measured p50/p90/p99 with distribution-free CIs at n=1000. FALSE for the "
             "ILLUSTRATIVE 100-500ms if the measured p50-p99 band lies outside it; the "
             "paired shift must also exclude 0, or the hop has no measurable cost and "
             "6.1 overstates it",
             "paired ApplyGuardrail on vs off, n=1000"),
    "F6-3": ("F6", "Hop #4 Cedar policy latency", "S",
             "Measured p50/p90/p99 + CI at n=1000. FALSE for the ILLUSTRATIVE 5-50ms if "
             "the measured band lies outside it",
             "pure-Cedar policy, no guardrail term, n=1000"),
    "F6-4": ("F6", "Hop #5 per-tool-call guardrail latency", "S",
             "Measured p50/p90/p99 + CI at n=1000. FALSE for the ILLUSTRATIVE 50-200ms "
             "per call if the measured band lies outside it",
             "n=1000 tool calls through the deterministic echo target"),
    "F6-5": ("F6", "Hop #6 output guardrail latency", "S",
             "Measured p50/p90/p99 + CI at n=1000. FALSE for the ILLUSTRATIVE 100-500ms "
             "if the measured band lies outside it. Also settles whether output "
             "evaluation is parallel: 5.1 makes no parallelism claim, so a per-policy "
             "linear scaling would be a new finding",
             "paired output evaluation on vs off, n=1000"),
    "F6-6": ("F6", "End-to-end total vs the ~800ms-31s+ figure", "S",
             "Measured end-to-end p50/p90/p99 + CI at n=1000. FALSE for the "
             "~800ms-31s+ total if the measured band lies outside it",
             "full path, n=1000"),
    "F6-7": ("F6", "Additivity: Duration = GuardrailLatency + TargetExecutionTime + eps", "S",
             "TRUE if the residual eps >= 0 within CI; FALSE if significantly negative, "
             "which means hops overlap and falsifies the decomposition model underlying "
             "6.1, 6.3 AND 6.4 — a structural finding, not a number tweak",
             "delay-mode echo target gives a ground-truth TargetExecutionTime term"),
    "F6-8": ("F6", "165-750ms per additional tool invocation", "S",
             "TRUE if the regression slope b's bootstrap CI overlaps [165,750]; FALSE if "
             "disjoint",
             "regress Duration = a + bN over N in {1,2,3,5}, paired bootstrap on b"),
    "F6-9": ("F6", "Early blocking at Hop #1 saves downstream latency", "S",
             "TRUE if blocked-request latency is significantly below passed-request "
             "latency (Wilcoxon + Hodges-Lehmann shift); FALSE if not",
             "paired blocked vs passed, n=1000"),

    # ---------------- F7 observability truth ----------------
    "F7-1": ("F7", "The 19 documented policy metrics are actually published", "O",
             "Per metric: TRUE if datapoints appear for our dimensions after traffic that "
             "should produce them; FALSE if absent. A documented-but-absent metric is a "
             "document defect",
             "GetMetricData over all documented metrics x 9 dimensions"),
    "F7-2": ("F7", "Gateway metrics exist under AWS/Bedrock-AgentCore", "O",
             "TRUE if Latency/Duration/Invocations/TargetExecutionTime/Throttles/"
             "SystemErrors/UserErrors all publish; FALSE for any absentee",
             "GetMetricData filtered to our gateway ARN"),
    "F7-3": ("F7", "Guardrails metrics exist under AWS/Bedrock/Guardrails", "O",
             "TRUE if the namespace (not AWS/Bedrock) carries the 7 documented metrics; "
             "FALSE if the namespace or names differ",
             "baseline is clean (0 metrics observed pre-test), so appearance is decisive"),
    "F7-4": ("F7", "Policy spans land in aws/spans with the documented operations", "O",
             "TRUE if AuthorizeAction-style spans appear for our gateway ARN; FALSE if absent",
             "Logs Insights over aws/spans filtered to our ARN, joined per request ID"),
    "F7-5": ("F7", "Tracing must be explicitly enabled or spans are absent", "O",
             "TRUE if spans are absent with tracing off and present with it on; FALSE if "
             "spans appear either way. This is the mutation that removes 'did we enable it' "
             "as a confound for every other O-claim",
             "tracing off -> assert absent; on -> assert present"),
    "F7-6": ("F7", "Metric publish lag sets a floor on every alarm in 6.4", "O",
             "Measured p50/p90/max lag from request to queryable datapoint, n=30. FALSE "
             "for every 6.4 alarm whose evaluation period is below the measured p90 lag: "
             "such an alarm cannot fire reliably, and 6.4 does not say so. A lag at or "
             "below 60s leaves the 1-minute alarms defensible",
             "timestamped request -> poll GetMetricData until the datapoint appears"),
    "F7-7": ("F7", "Metrics are batched at 1-minute intervals", "O",
             "TRUE if datapoint timestamps quantize to 60s; FALSE if finer or coarser",
             "inspect timestamp spacing across n=30 requests"),

    # ---------------- F8 regional / tier / language ----------------
    "F8-1": ("F8", "Guardrails-in-policy is available in exactly 5 Regions", "C",
             "TRUE if a policy-engine MUTATION succeeds in the 5 listed Regions and fails "
             "in the others with a distinguishable error; FALSE on any mismatch. Control-"
             "plane List* returns 200 everywhere, so only mutations can settle this",
             "9-region probe with explicit region_name, mutation not List"),
    "F8-2": ("F8", "Classic tier is ineffective for zh/ja/ko", "S",
             "TRUE if CLASSIC recall on zh-TW/zh-CN/ja/ko is statistically "
             "indistinguishable from the benign FPR (i.e. no protection) while EN/FR/ES "
             "recall is high; FALSE if CLASSIC detects non-EN/FR/ES content",
             "language x tier matrix, n>=60 per cell; the strongest test of a safety-"
             "critical claim in the document"),
    "F8-3": ("F8", "Standard tier adds broad multi-language support", "S",
             "TRUE if STANDARD recall on zh/ja/ko is significantly above CLASSIC "
             "(McNemar, paired on the same corpus); FALSE if no improvement",
             "same corpus, both tiers, paired"),
    "F8-4": ("F8", "Prompt-leakage detection is Standard-tier only", "E",
             "TRUE if PROMPT_LEAKAGE is rejected or inert on CLASSIC and works on "
             "STANDARD; FALSE if it works on CLASSIC",
             "paired tier probe"),
    "F8-5": ("F8", "Denied-topic length limits differ by tier (200 vs 1000)", "E",
             "TRUE if each tier accepts its limit and rejects limit+1; FALSE otherwise",
             "boundary probe per tier"),
    "F8-6": ("F8", "Standard tier's cross-Region inference stays in-geography", "O",
             "TRUE if all inference for a US-Region request is served from US Regions per "
             "CloudTrail/response metadata; FALSE if any out-of-geography Region appears",
             "inspect response metadata + CloudTrail across n=60 requests"),
    "F8-7": ("F8", "Word filters are EN/FR/ES only on either tier", "E",
             "TRUE if non-EN/FR/ES word filters are inert on both tiers; FALSE if effective",
             "word filter x language x tier matrix"),
    "F8-8": ("F8", "Automated Reasoning is en-US only and detect-only", "C",
             "TRUE if non-en-US and enforce-mode requests are rejected; FALSE if accepted",
             "rejection probes"),

    # ---------------- F9 fail-secure posture ----------------
    "F9-1": ("F9", "Policy evaluation timeout yields automatic DENY", "X",
             "Would be TRUE if an induced service-side evaluation timeout produced DENY. "
             "NOT TESTABLE: AgentCore exposes no fault-injection surface for policy "
             "evaluation. Nearest proxies are F5-4a (unevaluable policy) and F5-4b "
             "(guardrail evaluation impossible)",
             "EXCLUDED — remedy: an AWS-provided fault-injection or a documented timeout "
             "guarantee. Accelerator remains the sole source; release gate applies"),
    "F9-2": ("F9", "MismatchErrors/PolicyMismatch fire on unevaluable policies", "O",
             "TRUE if the metrics increment when a policy cannot evaluate; FALSE if silent",
             "paired with F5-4a"),
    "F9-3": ("F9", "Guardrail throttling produces observable failures, not silent passes", "E",
             "TRUE if throttled requests are denied or error rather than passing "
             "unevaluated; FALSE if a throttle silently allows content through",
             "drive ApplyGuardrail past its 100 rps quota, inspect verdicts"),

    # ---------------- F10 billing asymmetry ----------------
    "F10-1": ("F10", "Input block avoids model inference charge; output block does not", "S",
              "TRUE if a Cost-Explorer/tagged delta shows zero inference charge for "
              "input-blocked requests and full charge for output-blocked ones; FALSE if "
              "either differs",
              "n paired requests per arm, cost attributed by resource tag"),
    "F10-2": ("F10", "Guardrail billing is per text unit (TextUnitCount)", "O",
              "TRUE if TextUnitCount scales with content length as documented and matches "
              "the billed quantity; FALSE if the relationship differs",
              "content-length sweep, compare TextUnitCount to billed units"),
    "F10-3": ("F10", "Input tagging reduces text units billed", "S",
              "TRUE if tagged evaluation of a RAG-shaped prompt bills fewer text units "
              "than untagged; FALSE if identical",
              "paired tagged vs untagged on the same prompt, compare TextUnitCount"),
}


# Cases that no claim cites, and why that is correct rather than an oversight.
# check_coverage.py fails on any orphan case NOT listed here: an experiment in the
# registry answering no claim is either dead weight or a claim I failed to triage,
# and both need to be visible.
PLATFORM_CASES: dict[str, str] = {
    "F1-4":
        "Prerequisite, not a claim. FINDING-F1-1 discovered that PolicyDefinition is a "
        "union with non-deprecated `cedar` AND `policy` arms. The document predates "
        "that surface and says nothing about it, so no claim maps here. But the harness "
        "must know which arm to send or every F1-F5 gateway test fails for an unrelated "
        "reason. Run in Phase 3 as a platform pre-flight.",
    "F1-21":
        "Prerequisite for F5-9. Establishes the PutEnforcedGuardrailConfiguration "
        "surface and its required fields WITHOUT applying enforcement, so the 5c "
        "blast-radius controls are validated before the <=5-minute live window opens. "
        "The document does not describe this API; only its consequence (an agent cannot "
        "decline an account-level guardrail) is claimed, and that is F5-9.",
    "F9-1":
        "Cited by no claim BY CONSTRUCTION: every claim it would serve is class X "
        "(C-s3-1-bullet-014-a, C-s4-1-bullet-008-a, C-s9-mermaid-011-c), and X claims "
        "carry an exclusion reason instead of a case. The case is retained in the "
        "registry so the exclusion register can point at a designed-but-unrunnable "
        "experiment rather than at nothing.",
}


# ---------------------------------------------------------------------------
# DECLINED ARMS — designed, named in the plan, deliberately NOT run.
# ---------------------------------------------------------------------------
# These are NOT in CASES, and that distinction is load-bearing. An exclusion
# reason saying "same structural limit as F5-3c" is only honest if F5-3c is
# identifiable; but if F5-3c were minted into CASES, the exclusion register would
# print it under "nearest proxy RUN" and offer comfort that does not exist. So a
# declined arm gets its own table: nameable in prose, never citable as evidence.
#
# 03_exclusion_register.py resolves case-shaped tokens in reasons against CASES
# first and this table second, and renders the two differently.
DECLINED_ARMS: dict[str, str] = {
    "F5-3c":
        "SCP enforcement observed from INSIDE a constrained member account. "
        "Structurally unreachable here — this is the Organizations management "
        "account, where SCPs never apply, and AssumeRole into both member accounts "
        "returns AccessDenied. (Account IDs are deliberately omitted: this file is "
        "generated into a report destined for external distribution, and per the "
        "redaction gate no account identifier belongs in prose that adds nothing by "
        "carrying it.) Decision 5b also "
        "declined it on engagement grounds: creating a test principal in a member "
        "account is a 90-day irreversible Organizations change whose subject is "
        "generic SCP behaviour, not an AgentCore property. F5-3a (authoring + "
        "propagation via DescribeEffectivePolicy) and F5-3b (IAM permissions "
        "boundary, a control the document itself recommends) are run instead and "
        "ARE evidence; F5-3c is not.",
}


# ===========================================================================
# SPLITS  (one unit carrying independently falsifiable conjuncts)
# ===========================================================================
# The extractor emits structural units. A unit can carry several propositions
# that are independently true or false, and each needs its own class, its own
# test, and its own merge group — a diagram label reading
# "Hop #4 ... ~5-50ms · default-deny · fail-secure" is wrong if ANY of the three
# is wrong, and each is settled by a different experiment.
#
# Splitting is done only where the conjuncts are genuinely independent. Each
# part gets a suffixed claim_id (`...-a`, `...-b`) and the parent row is replaced
# by its parts, so no text is lost and the ordinals stay traceable to the source
# line. Parts inherit the parent's sha1: editing the source line invalidates
# every part, which is the behaviour we want.
#
# entry: parent_claim_id -> [(letter, conjunct, cls, cases, exclusion_reason)]

SPLITS: dict[str, list[tuple[str, str, str, tuple[str, ...], str]]] = {
    # "Hop #4: Cedar Tool Auth (AgentCore Policy) ~5-50ms · default-deny · fail-secure"
    "C-s9-mermaid-011": [
        ("a", "Hop #4 Cedar tool authorization costs ~5-50ms",
         "S", ("F6-3",), ""),
        ("b", "Cedar authorization is default-deny",
         "E", ("F4-4",), ""),
        ("c", "Cedar authorization is fail-secure",
         "X", (), ""),   # reason supplied from X_CLAIMS
    ],
    # "Hop #5: Tool Guardrails x N calls (Gateway Policy: permit/forbid +
    #  suppressOutput) ~50-200ms per call"
    "C-s9-mermaid-012": [
        ("a", "Hop #5 tool guardrails cost ~50-200ms per call",
         "S", ("F6-4",), ""),
        ("b", "Hop #5 supports permit/forbid and suppressOutput effects",
         "C", ("F1-17",), ""),
        ("c", "Hop #5 evaluation repeats for each of N tool calls",
         "S", ("F6-8",), ""),
    ],
    # The 3.2 prompt-attack bullet: the plan flagged this one as carrying five
    # separable claims. Four survive as independent propositions.
    "C-s3-2-bullet-008": [
        ("a", "PROMPT_ATTACK detection requires input tagging on InvokeModel",
         "S", ("F5-6",), ""),
        ("b", "Converse requires guardContent on the block to be evaluated",
         "S", ("F5-6",), ""),
        ("c", "Tagging scope is limited to the tagged block only",
         "S", ("F5-6",), ""),
        ("d", "The three prompt-attack subtypes are separately configurable",
         "C", ("F1-8",), ""),
    ],
    # "Guardrails are ineffective with languages outside the tier's support"
    # carries both a capability claim and a safety-consequence claim.
    "C-s3-4-bullet-001": [
        ("a", "CLASSIC tier does not detect violations in zh/ja/ko",
         "S", ("F8-2",), ""),
        ("b", "The failure is SILENT: no error, no signal that evaluation was inert",
         "O", ("F8-2", "F7-3"), ""),
    ],
    # The billing bullet asserts two opposite-signed facts.
    "C-s3-2-bullet-002": [
        ("a", "An input-blocked request incurs no model-inference charge",
         "S", ("F10-1",), ""),
        ("b", "An output-blocked request IS charged for model inference",
         "S", ("F10-1",), ""),
    ],
    # Policy-evaluation fail-secure: the timeout half is excluded, the
    # default-deny half is testable. Splitting keeps the exclusion honest
    # instead of letting default-deny's PASS cover for an untested timeout.
    "C-s3-1-bullet-014": [
        ("a", "Policy evaluation TIMEOUTS result in DENY",
         "X", (), ""),
        ("b", "A policy that cannot be evaluated results in DENY",
         "E", ("F5-4a", "F5-4b"), ""),
    ],
    "C-s4-1-bullet-008": [
        ("a", "Fail-secure: evaluation timeouts result in DENY",
         "X", (), ""),
        ("b", "Fail-secure: unevaluable conditions result in DENY",
         "E", ("F5-4a", "F5-4b"), ""),
    ],
}

# Reasons for X-classed split parts, keyed by the SUFFIXED id.
SPLIT_X_REASONS: dict[str, str] = {
    "C-s9-mermaid-011-c":
        "'fail-secure' as a blanket property of Hop #4. The evaluable half is "
        "tested (F4-4 default-deny, F5-4a unevaluable policy, F5-4b guardrail "
        "evaluation impossible); the TIMEOUT half is not inducible — see "
        "C-s3-1-bullet-014-a. A label asserting the blanket property inherits the "
        "same exclusion: proxies covering three failure modes do not establish a "
        "universal, and a diagram label that reads as a guarantee should not be "
        "scored as one. Remedy: the same as the claim it restates — an "
        "AWS-documented timeout guarantee, or a fault-injection surface. Until "
        "then v1.3 should narrow the label to the modes actually measured.",
    "C-s3-1-bullet-014-a":
        "Fail-secure on policy-evaluation TIMEOUT. AgentCore exposes no "
        "fault-injection surface to induce a service-side evaluation timeout, so "
        "the claim cannot be tested directly. Nearest proxies ARE run: F5-4a "
        "(policy that cannot evaluate) and F5-4b (guardrail evaluation "
        "impossible). Source remains Accelerator v2.9 -> release gate applies. "
        "Remedy: an AWS-documented timeout guarantee or a fault-injection "
        "capability.",
    "C-s4-1-bullet-008-a":
        "Restatement of the timeout-DENY claim in 3.1, merged via "
        "M-fail-secure-timeout-deny; the same absence of a fault-injection surface "
        "applies. Proxies F5-4a/F5-4b are run. Remedy: identical to the canonical "
        "site C-s3-1-bullet-014-a — an AWS-documented timeout guarantee or a "
        "fault-injection capability. Recorded here rather than deferred to the "
        "canonical row so that this site is independently visible to the v1.3 "
        "amendment pass; a claim amended at one of its sites is not amended.",
}


# ===========================================================================
# MERGE GROUPS  (sites[] — one proposition restated across sections)
# ===========================================================================
# Per feedback_grep_the_claim_not_the_phrasing: a claim amended at 1 of 4 sites
# is NOT amended. The canonical claim is listed first; the rest carry
# merged_into pointing at it. check_coverage.py requires that a v1.3 amendment
# touching a canonical claim also touches every site.

MERGE_GROUPS: dict[str, list[str]] = {
    "M-default-deny-permit-gotcha": [
        "C-s3-1-quote-001",          # the Critical setup gotcha blockquote
        "C-s7-1-prose-005",          # "(4) ... verify an explicit permit policy exists first"
        "C-s7-2-trow-003",           # anti-pattern: guardrail-only set in ENFORCE
        "C-s8-checkitem-004",        # checklist: write explicit baseline permit
        "C-s7-1-mermaid-006",        # "4. Verify explicit permit policy exists"
        "C-s4-1-bullet-005",         # "Default-deny: if no policy matches, denied"
        "C-s2-1-mermaid-011",        # "Hop #4 - Cedar authorization (deterministic, default-deny)"
        "C-s9-mermaid-011-b",       # "default-deny" in the reference architecture label
        "C-s9-mermaid-015",          # "no matching permit"
    ],
    "M-tier-language-ineffective": [
        "C-s3-4-bullet-001-a",       # 'Guardrails are ineffective with languages...'
        "C-s1-quote-002",            # Executive Summary language-support callout
        "C-s7-2-trow-008",           # anti-pattern: Classic on non-EN/FR/ES
        "C-s8-checkitem-002",        # checklist: verify tier vs traffic language
        "C-s3-4-trow-001",           # tier table language row
        "C-s3-4-mermaid-011",        # 'Classic would be silently ineffective'
    ],
    "M-guardrails-nondeterministic": [
        "C-s3-1-bullet-013",         # 'per AWS: same input can result in different outputs'
        "C-s4-1-bullet-004",         # 'Deterministic (not probabilistic like guardrails)'
        "C-s7-1-trow-003",           # principle 3
        "C-s3-3-numitem-001",        # caching is high-risk because non-deterministic
        "C-appB-quote-001",          # caching removed from Appendix B
        "C-s4-1-bullet-002",         # 'Makes deterministic allow/deny decisions'
        "C-s4-4-bullet-001",         # 'only the Cedar layer is deterministic'
        "C-s7-2-trow-002",           # anti-pattern: guardrails for tool authorization
    ],
    "M-billing-asymmetry": [
        "C-s3-2-bullet-002-a",       # 'not charged for model inference' (input-block half)
        "C-s3-2-mermaid-003",        # BLOCKED at input: model inference $0
        "C-s3-2-mermaid-008",        # BLOCKED at output: inference NOT refunded
        "C-s7-1-trow-002",           # principle 2
        "C-s2-1-mermaid-005",        # 'model inference skipped (no inference charge)'
        "C-s9-mermaid-008",          # 'Block (no model inference, no inference charge)'
        "C-appB-trow-002",           # early blocking 'avoids model-inference charges'
    ],
    "M-latency-hop1": [
        "C-s6-1-trow-001",           # 50-200ms
        "C-s9-mermaid-003",          # ~50-200ms
    ],
    "M-latency-hop2": [
        "C-s6-1-trow-002",           # 100-500ms
        "C-s9-mermaid-004",
    ],
    "M-latency-hop3": [
        "C-s6-1-trow-003",           # 500ms-30s
        "C-s9-mermaid-010",
    ],
    "M-latency-hop4": [
        "C-s6-1-trow-004",           # 5-50ms
        "C-s9-mermaid-011-a",
    ],
    "M-latency-hop5": [
        "C-s6-1-trow-005",           # 50-200ms x N
        "C-s9-mermaid-012-a",
    ],
    "M-latency-hop6": [
        "C-s6-1-trow-006",           # 100-500ms
        "C-s9-mermaid-018",
    ],
    "M-prompt-attack-input-tagging": [
        "C-s3-2-bullet-008-a",       # requires input tagging on InvokeModel
        "C-s7-3-trow-002",           # 'Prompt Attack (with input tagging)'
        "C-s8-checkitem-007",        # checklist: configure input tagging
        "C-appA-trow-001",           # 'requires input tagging'
    ],
    "M-parallel-input-evaluation": [
        "C-s3-2-bullet-014",         # officially documented parallel input evaluation
        "C-appB-trow-001",           # Appendix B parallel policy evaluation
        "C-s5-1-bullet-007",         # no equivalent statement for output
    ],
    "M-fail-secure-timeout-deny": [
        "C-s3-1-bullet-014-a",       # 'Policy evaluation timeouts result in DENY'
        "C-s4-1-bullet-008-a",       # 'Fail-secure: evaluation timeouts result in DENY'
        "C-s9-mermaid-011-c",        # 'fail-secure' in the reference architecture label
    ],
    "M-update-gateway-risk": [
        "C-s3-1-numitem-005",        # any principal with UpdateGateway can switch LOG_ONLY
        "C-s4-4-trow-009",           # bypass route 3
        "C-s4-4-trow-010",           # bypass route 4 SCP backstop
        "C-s6-4-trow-007",           # alert on UpdateGateway
        "C-s8-checkitem-012",        # alarms incl. UpdateGateway changes
    ],
    "M-two-level-log-only": [
        "C-s4-1-numitem-006",        # engine mode takes precedence
        "C-s4-1-mermaid-003",        # 'NOTHING is blocked (even ACTIVE policies)'
    ],
    "M-cedar-immune-to-injection": [
        "C-s4-1-bullet-003",         # 'Immune to prompt injection'
        "C-s4-4-prose-005",          # 'operates outside the model's reasoning'
    ],
    "M-pii-not-in-tool-use": [
        "C-s4-2-numitem-004",        # PII caveat on tool_use output parameters
        "C-appA-trow-005",           # 'tool_use parameters are not scanned'
    ],
    "M-guardrails-namespace": [
        "C-bedrock-guardrails-metrics-prose-001",   # AWS/Bedrock/Guardrails not AWS/Bedrock
        "C-s3-2-numitem-003",                        # InvocationLatency namespace
        "C-appC-numitem-001",                        # change log: namespace corrected
    ],
    "M-optimization-no-privatelink": [
        "C-s4-5-3-trow-003",         # Optimization: no PrivateLink today
        "C-s5-3-numitem-009",        # BP: Optimization does not support PrivateLink
        "C-s4-5-3-trow-002",         # Evaluations: control plane only
    ],
    "M-async-streaming-leak": [
        "C-s5-1-numitem-001",        # streaming mode choice
        "C-s5-1-mermaid-011",        # 'already-sent content has leaked; no PII masking'
        "C-appB-trow-007",           # async streaming technique + trade-off
    ],
    "M-auto-model-updates": [
        "C-s3-2-numitem-005",        # AWS auto-updates guardrail models
        "C-s8-checkitem-026",        # re-run regression set periodically
    ],
    "M-transaction-search-prereq": [
        "C-s4-3-numitem-002",        # Transaction Search is a prerequisite
        "C-s8-checkitem-009",        # checklist: enable Transaction Search then tracing
    ],
    "M-ecr-public-egress": [
        "C-s4-5-4-numitem-002",      # Harness VPC mode must allow public.ecr.aws
        "C-s4-5-5-mermaid-008",      # public.ecr.aws — no VPC endpoint
    ],
    "M-gateway-only-path": [
        "C-s4-4-trow-007",           # bypass route 1 closure: no direct tool credentials
        "C-s4-5-1-bullet-001",       # Gateway endpoint is the ONLY path to tools
        "C-s4-4-mermaid-009",        # 'ONLY path to tools'
        "C-s4-5-5-mermaid-006",      # 'unavoidable because it is the only route'
    ],
    "M-http-403-policy-id": [
        "C-s3-1-bullet-015",         # HTTP 403 with denying policy ID
        "C-s2-1-mermaid-002",        # 'block, HTTP 403, agent never invoked'
        "C-s9-mermaid-006",          # 'Block (HTTP 403)'
    ],
}


# ===========================================================================
# RULES
# ===========================================================================
# Resolution order (first match wins):
#   1. OVERRIDES        exact claim_id
#   2. ORDINAL_RULES    (anchor, unit_type, frozenset(ordinals))
#   3. TYPE_RULES       (anchor, unit_type)
#   4. ANCHOR_RULES     anchor
#   5. FALLTHROUGH      X with an explicit "unclassified" reason -> gate FAILS
#
# Assignment tuple: (cls, cases, exclusion_reason, note)
#   - cases: tuple of case IDs, or () when the class is D/N/X
#   - exclusion_reason: required and non-empty when cases is ()

A = tuple  # readability alias for assignment tuples

OVERRIDES: dict[str, tuple] = {
    # ---- front matter ----
    "C-aws-bedrock-agentcore-before-during-afte-trow-005": (
        "D", (), "Provenance statement about the document's own sources, not a claim "
        "about AWS behaviour. Verified by the release gate (NDA downgrade pass), not "
        "by experiment.", "release-gate tracked"),

    # ---- s1 Executive Summary ----
    "C-s1-prose-001": ("S", ("F6-1", "F6-2", "F6-4", "F6-5"), "",
                       "'multiple checkpoint hops' — the hop count is D, but the "
                       "existence of a measurable cost at each is S"),
    "C-s1-prose-002": ("S", ("F6-1", "F6-2", "F6-4", "F6-5", "F6-6"), "",
                       "'measurable latency at each hop' — falsified if any hop's "
                       "paired shift CI includes 0"),
    "C-s1-quote-001": ("C", ("F8-1",), "", "regional availability list"),
    "C-s1-quote-002": ("S", ("F8-2", "F8-3"), "", "tier/language support"),

    # ---- s2-1 hop numbering: mermaid labels that carry testable content ----
    "C-s2-1-mermaid-002": ("E", ("F4-6", "F5-1"), "",
                           "403 + 'agent never invoked' is testable even though the hop "
                           "number is definitional"),
    "C-s2-1-mermaid-005": ("S", ("F10-1",), "", "no inference charge on input block"),
    "C-s2-1-mermaid-011": ("E", ("F4-4",), "", "default-deny half of a definitional label"),
    "C-s2-1-mermaid-014": ("C", ("F1-17",), "", "suppressOutput on tool response"),
    "C-s2-1-mermaid-019": ("S", ("F3-1",), "", "output block/mask before user sees it"),
    "C-s2-1-quote-001": ("C", ("F1-15",), "",
                         "where Hop #2/#6 execute when attached via guardrailConfiguration"),

    # ---- s3-1 ----
    "C-s3-1-bullet-005": ("C", ("F1-7", "F1-18"), "", "categories + discrete score lattice"),
    "C-s3-1-bullet-015": ("E", ("F4-6",), "",
                          "HTTP 403 naming the denying policy ID — a response-shape "
                          "claim settled by one denied request"),
    "C-s3-1-bullet-009": ("C", ("F1-3", "F5-4b"), "",
                          "the required bedrock:InvokeGuardrailChecks permission; "
                          "F5-4b is the mutation that proves it load-bearing"),
    "C-s3-1-bullet-012": ("O", ("F6-1", "F7-1"), "",
                          "'AWS publishes no parallelism characteristics — measure your "
                          "own baseline'. The instruction is testable: can GuardrailLatency "
                          "actually produce that baseline?"),
    "C-s3-1-numitem-005": ("E", ("F5-2",), "", "UpdateGateway risk — the F5-2 attack"),
    "C-s3-1-quote-001": ("E", ("F4-1", "F1-3"), "",
                         "the ENFORCE + default-deny gotcha; DC-1 says it is also "
                         "INCOMPLETE (omits validationMode)"),

    # ---- s3-2 ----
    "C-s3-2-bullet-010": ("C", ("F1-14",), "", "Automated Reasoning constraints"),
    "C-s3-2-bullet-014": ("S", ("F6-2",), "",
                          "parallel input evaluation is officially documented; the "
                          "testable content is that latency scales sub-linearly in "
                          "policy count, which is a measurement, not an API fact"),
    "C-s3-2-numitem-001": ("C", ("F1-11",), "", "independent input/output settings"),
    "C-s3-2-numitem-005": ("S", ("F3-11",), "", "auto-updates -> regression testing"),

    # ---- s3-3 ApplyGuardrail ----
    "C-s3-3-code-001": ("C", ("F1-2",), "",
                        "the ApplyGuardrail call shape — executed verbatim in Phase 1"),
    "C-s3-3-numitem-001": ("S", ("F2-5",), "",
                           "caching is high-risk BECAUSE evaluation is non-deterministic; "
                           "F2-5 measures the premise"),
    "C-s3-3-numitem-004": ("X", (), "", ""),   # fail-open/closed, see below

    # ---- s4-1 Cedar ----
    "C-s4-1-bullet-003": ("S", ("F5-5", "F2-1"), "",
                          "'Immune to prompt injection' — same proposition as 4.4's, so "
                          "the same evidence: n=60 injected payloads must not shift the "
                          "Cedar decision. Stated here as a capability bullet and there "
                          "as a rationale; both are the canonical group's claim"),
    "C-s4-1-bullet-007": ("C", ("F1-15",), "", "three gateway target types"),
    "C-s4-1-bullet-011": ("O", ("F7-4", "F7-5"), "", "spans emitted when tracing enabled"),
    "C-s4-1-numitem-006": ("E", ("F4-3",), "", "two-level LOG_ONLY precedence"),
    "C-s4-1-prose-007": ("C", ("F1-24", "F1-25"), "",
                         "limitations of guardrails in policy: no regex, cannot mix "
                         "when{} with when guardrails{}"),
    "C-s4-1-quote-001": ("C", ("F1-16",), "", "Lambda interceptors"),

    # ---- s4-2 tool I/O ----
    "C-s4-2-bullet-001": ("C", ("F1-17",), "", "permit/forbid vs suppressOutput effects"),
    "C-s4-2-bullet-005": ("S", ("F6-8",), "", "N tool calls -> N x evaluation time"),
    "C-s4-2-numitem-004": ("C", ("F1-28",), "", "PII not detected in tool_use parameters"),

    # ---- s4-3 observability ----
    "C-s4-3-numitem-002": ("O", ("F7-5",), "", "Transaction Search is a prerequisite"),
    "C-s4-3-numitem-004": ("O", ("F7-4",), "", "policy spans go to aws/spans"),

    # ---- s4-4 non-bypassable hooks ----
    "C-s4-4-prose-003": ("E", ("F5-1", "F5-8"), "",
                         "'enforcement must live OUTSIDE the agent's environment' — "
                         "F5-8 confirms the premise from public evidence"),
    "C-s4-4-prose-004": ("E", ("F5-1",), "",
                         "Accelerator quote: policies intercept all agent traffic at the "
                         "gateway boundary. NDA-sourced -> release gate"),
    "C-s4-4-prose-005": ("S", ("F5-5", "F2-1"), "",
                         "'immune to prompt injection' is a rate claim, not a single "
                         "trial: n=60 injected tool responses must not shift the Cedar "
                         "decision"),
    "C-s4-4-trow-007": ("E", ("F5-1",), "", "bypass route 1"),
    "C-s4-4-trow-008": ("E", ("F5-7b",), "", "bypass route 2"),
    "C-s4-4-trow-009": ("E", ("F5-2", "F5-8"), "", "bypass route 3 — highest value"),
    "C-s4-4-trow-010": ("E", ("F5-3a", "F5-3b"), "", "bypass route 4"),
    "C-s4-4-trow-011": ("E", ("F5-4a", "F5-4b"), "", "bypass route 5"),
    "C-s4-4-bullet-001": ("S", ("F2-1", "F2-3"), "",
                          "only the Cedar layer is deterministic"),
    "C-s4-4-bullet-002": ("S", ("F3-1", "F5-5"), "",
                          "'hooks fire on tool USE; tool-free harm is Hop #2/#6's job' — "
                          "testable as a coverage boundary: violating text generated "
                          "without a tool call must be caught by the output guardrail "
                          "(F3-1) and NOT by the gateway policy (F5-5's benign arm)"),
    "C-s4-4-bullet-003": ("C", ("F1-16",), "", "interceptors receive bearer tokens"),

    # ---- s4-5 network containment ----
    "C-s4-5-1-bullet-001": ("E", ("F5-1", "F5-7b"), "", "Gateway is the only path to tools"),
    "C-s4-5-1-prose-003": ("E", ("F5-7b",), "",
                           "'cannot exfiltrate regardless of what the model decides'"),
    "C-s4-5-3-trow-001": ("C", ("F5-7a",), "", "PrivateLink coverage row"),
    "C-s4-5-3-trow-002": ("C", ("F5-7a",), "", "Evaluations: control plane only"),
    "C-s4-5-3-trow-003": ("C", ("F5-7a",), "", "Optimization: no PrivateLink"),
    "C-s4-5-4-numitem-002": ("E", ("F5-7b",), "", "public.ecr.aws egress requirement"),

    # ---- s5-1 output evaluation ----
    "C-s5-1-bullet-004": ("C", ("F1-27",), "", "reasoning blocks excluded from evaluation"),
    "C-s5-1-bullet-007": ("S", ("F6-5",), "",
                          "no documented parallelism for output — measure it"),
    "C-s5-1-numitem-001": ("C", ("F1-12",), "", "streaming modes"),
    "C-s5-1-numitem-005": ("C", ("F1-13",), "", "contextual grounding limits"),

    # ---- s6-1 latency table ----
    "C-s6-1-quote-001": ("D", (), "The document's own disclaimer that the table is "
                         "illustrative. Not a claim about AWS; it is the statement this "
                         "entire project exists to render unnecessary.",
                         "v1.3 replaces the disclaimer with measured values"),
    "C-s6-1-prose-002": ("S", ("F6-8",), "", "165-750ms per additional tool invocation"),

    # ---- s6-2 metrics ----
    "C-agentcore-gateway-metrics-prose-001": ("O", ("F7-2", "F7-7"), "",
                                              "namespace + 1-minute batching"),
    "C-agentcore-gateway-metrics-prose-002": ("O", ("F7-2",), "",
                                              "FirstByteLatency is not a valid metric name"),
    "C-agentcore-policy-metrics-prose-001": ("O", ("F7-1",), "", "namespace + dimensions"),
    "C-agentcore-policy-metrics-prose-003": ("O", ("F7-1",), "",
                                             "table is not exhaustive — we enumerate what "
                                             "actually publishes"),
    "C-agentcore-policy-metrics-prose-004": ("O", ("F7-1",), "",
                                             "severity vs confidence score terminology"),
    "C-bedrock-guardrails-metrics-prose-001": ("O", ("F7-3",), "",
                                               "AWS/Bedrock/Guardrails, not AWS/Bedrock"),
    "C-bedrock-guardrails-metrics-prose-002": ("O", ("F7-3",), "", "dimensions"),
    "C-bedrock-guardrails-metrics-prose-003": ("O", ("F7-3", "F6-5"), "",
                                               "guardrailProcessingLatency from the trace"),

    # ---- s7-1 design principles ----
    "C-s7-1-prose-001": ("O", ("F3-10",), "", "AWS recommends calibrating before enforcing"),
    "C-s7-1-prose-002": ("E", ("F4-2",), "", "LOG_ONLY logs but blocks nothing"),
    "C-s7-1-prose-003": ("O", ("F3-10",), "", "run a golden set through the gateway"),
    "C-s7-1-prose-004": ("O", ("F3-10", "F3-9"), "",
                         "build a confusion matrix from logged confidence scores — "
                         "F3-10 tests whether this is even possible"),
    "C-s7-1-prose-005": ("E", ("F4-1",), "", "verify an explicit permit exists before ENFORCE"),
    "C-s7-1-prose-006": ("O", ("F7-1",), "", "LogOnlyDecisionFlips sustained zero"),
    "C-s7-1-trow-002": ("S", ("F10-1", "F6-9"), "", "principle 2: fail fast + billing"),
    "C-s7-1-trow-003": ("S", ("F2-1", "F2-2", "F2-3"), "",
                        "principle 3: deterministic controls for authorization — the "
                        "document's most load-bearing distinction"),

    # ---- s8 checklist items that are testable rather than procedural ----
    "C-s8-checkitem-002": ("S", ("F8-2", "F8-3"), "", "tier vs traffic language"),
    "C-s8-checkitem-003": ("C", ("F8-1",), "", "confirm regional availability"),
    "C-s8-checkitem-004": ("E", ("F4-1", "F1-3"), "", "baseline permit before ENFORCE"),
    "C-s8-checkitem-006": ("C", ("F1-19",), "",
                           "thresholds are mandatory in hand-written policies"),
    "C-s8-checkitem-007": ("S", ("F5-6",), "", "input tagging with random tagSuffix"),
    "C-s8-checkitem-009": ("O", ("F7-5",), "", "Transaction Search then tracing"),
    "C-s8-checkitem-026": ("S", ("F3-11",), "", "re-run the regression set periodically"),

    # ---- per-safeguard bullets: the coarse s3-2 rule would leave the specific
    # detection cases (F3-4..F3-8) attached to nothing, which would let a designed
    # experiment sit in the registry with no claim it answers.
    "C-s3-2-bullet-004": ("S", ("F3-1", "F3-2"), "", "content filter categories"),
    "C-s3-2-bullet-005": ("S", ("F3-5",), "", "denied topics"),
    "C-s3-2-bullet-006": ("E", ("F3-6", "F1-26"), "", "word filters incl. language limits"),
    "C-s3-2-bullet-007": ("S", ("F3-4", "F1-9"), "", "PII detection/redaction"),
    "C-s3-2-bullet-009": ("S", ("F3-7", "F1-13"), "", "contextual grounding + limits"),
    "C-s3-2-bullet-003": ("S", ("F3-3",), "",
                          "'more comprehensive than Gateway-level' — the hard-negative "
                          "arm bounds what 'comprehensive' costs in false positives"),
    "C-s3-3-bullet-005": ("C", ("F1-20",), "", "content-array batching, 10-block cap"),
    "C-s3-3-numitem-003": ("S", ("F10-3",), "",
                           "input tagging enables evaluating only user-supplied content — "
                           "measured as text units billed"),
    "C-s3-4-bullet-002": ("O", ("F8-6",), "", "cross-Region inference stays in-geography"),
    "C-s3-4-bullet-003": ("E", ("F1-26", "F8-7"), "", "word filters EN/FR/ES only"),
    "C-s3-4-bullet-004": ("C", ("F1-14", "F8-8"), "", "Automated Reasoning en-US only"),
    "C-s6-1-trow-001": ("S", ("F6-1",), "", "hop 1: 50-200ms"),
    "C-s6-1-trow-002": ("S", ("F6-2",), "", "hop 2: 100-500ms"),
    "C-s6-1-trow-003": ("S", ("F6-6",), "",
                        "hop 3 model inference 500ms-30s: not a guardrail hop, so it is "
                        "measured only as part of the end-to-end total"),
    "C-s6-1-trow-004": ("S", ("F6-3",), "", "hop 4: 5-50ms"),
    "C-s6-1-trow-005": ("S", ("F6-4", "F6-8"), "", "hop 5: 50-200ms x N calls"),
    "C-s6-1-trow-006": ("S", ("F6-5",), "", "hop 6: 100-500ms"),
    "C-s6-1-trow-007": ("S", ("F6-6", "F6-7"), "",
                        "the TOTAL row — F6-7 tests whether the rows are additive at all"),
    "C-s6-4-trow-004": ("E", ("F9-3", "F7-3"), "", "guardrail throttling alarm"),
    "C-s6-4-trow-006": ("O", ("F9-2", "F7-1"), "",
                        "LogOnlyEvalIncomplete — an incomplete-evaluation signal"),
    "C-appA-trow-001": ("S", ("F3-8", "F5-5"), "",
                        "prompt injection row: recall by subtype + the indirect-injection "
                        "case the row itself recommends"),
    "C-appA-trow-005": ("C", ("F1-28", "F3-4"), "",
                        "PII row incl. 'tool_use parameters are not scanned'"),
    "C-s3-2-numitem-002": ("S", ("F3-3", "F6-2"), "",
                           "'avoid redundant policies' makes a measurable prediction: "
                           "removing a duplicate check must not reduce recall"),

    # The two-level LOG_ONLY numitem also asserts the field EXISTS with the
    # documented default, which is F1-1's bisect result, not F4-3's behaviour.
    "C-s4-1-numitem-006": ("E", ("F4-3", "F1-1"), "",
                           "engine-mode precedence AND the enforcementMode field's "
                           "existence + ACTIVE default"),
    "C-s4-1-mermaid-005": ("C", ("F1-1",), "",
                           "the decision diagram branches on enforcementMode, which "
                           "presupposes the field exists"),
    "C-bedrock-guardrails-metrics-trow-004": ("O", ("F10-2", "F7-3"), "",
                                              "TextUnitCount: billing is per text unit"),
    "C-s8-checkitem-013": ("O", ("F7-3", "F10-2"), "",
                           "the metrics the checklist tells the reader to monitor must "
                           "actually publish"),
    # Route 4's account-level backstop is what 5c tests from the other direction:
    # F5-3a/3b test denying the WEAKENING, F5-9 tests an account-level control the
    # agent cannot decline at all.
    "C-s4-4-trow-010": ("E", ("F5-3a", "F5-3b", "F5-9"), "",
                        "bypass route 4: account-level backstop"),
    "C-s4-4-prose-003": ("E", ("F5-1", "F5-8", "F5-9"), "",
                         "'enforcement must live OUTSIDE the agent's environment' — "
                         "F5-9 is the only case that tests a control the agent cannot "
                         "decline, so it belongs to this premise"),
    # F2-4 is the mutation arm for the determinism model: the claim that guardrails
    # are non-deterministic and policies deterministic is exactly what it controls.
    "C-s3-1-bullet-013": ("S", ("F2-2", "F2-3", "F2-4"), "",
                          "AWS's own paired statement; F2-4 proves flip rate tracks "
                          "threshold placement, without which the model is unfalsified"),
    "C-s7-1-trow-003": ("S", ("F2-1", "F2-2", "F2-3", "F2-4"), "",
                        "principle 3, the document's most load-bearing distinction"),

    # ---- appB ----
    "C-appB-trow-001": ("S", ("F6-2",), "", "parallel policy evaluation"),
    "C-appB-trow-002": ("S", ("F6-9", "F10-1"), "", "early blocking saves downstream hops"),
    "C-appB-trow-003": ("C", ("F1-20",), "", "content batching; 10-block cap"),
    "C-appB-trow-007": ("C", ("F1-12",), "", "asynchronous streaming mode"),
}

# Claims whose only honest classification is X, each with a written reason and
# the remedy that would make it testable. An accurate exclusion register is more
# credible than a false 100%.
X_CLAIMS: dict[str, str] = {
    "C-s3-3-numitem-004":
        "'AWS does not document fail-open vs fail-closed' is a claim about the ABSENCE of "
        "documentation. Not falsifiable by experiment: finding the behaviour empirically "
        "(F5-4b does) would not show that AWS documents it. The testable half — what the "
        "actual posture is — is covered by F5-4b. Remedy: none; this is a correctly-"
        "scoped statement about the documentation record, verifiable only by review of "
        "AWS docs at a stated date.",
    "C-s4-5-2-trow-002":
        "DNS as an exfiltration channel from Code Interpreter Sandbox mode. Testing it "
        "means performing actual DNS-based data exfiltration from a sandbox; the "
        "technique is out of scope for this engagement and the finding would not change "
        "any recommendation (the document already says use VPC mode). NDA-sourced -> "
        "release gate. Remedy: a scoped, separately-authorized network test.",
    "C-s4-5-2-trow-003":
        "VPC-mode ENI creation via AWSServiceRoleForBedrockAgentCoreNetwork and the "
        "required-endpoint list. Partially covered by F5-7b (egress mutation); the "
        "service-linked-role mechanism itself is an implementation detail we can observe "
        "but not falsify usefully. Remedy: covered incidentally if F5-7b's runtime "
        "creation surfaces the SLR.",
    "C-s4-5-3-prose-002":
        "VPC endpoint policies restrict by IAM principal only, so OAuth-authenticated "
        "callers require Principal '*'. Testing requires a working OAuth-authenticated "
        "gateway caller behind a PrivateLink endpoint — infrastructure well beyond this "
        "platform's scope, and the claim is about VPC endpoint policy semantics (an EC2/"
        "PrivateLink property) rather than an AgentCore guardrails property. Remedy: a "
        "dedicated PrivateLink + OIDC testbed.",
    "C-s4-5-5-prose-002":
        "IAM condition keys aws:SourceVpc/SourceVpce and bedrock-agentcore:subnets/"
        "securityGroups for mandating VPC deployment. Authoring is testable but "
        "ENFORCEMENT requires a constrained principal in a member account, which is "
        "AccessDenied from this management account (same structural limit as F5-3c). "
        "Remedy: a member-account test role, which decision 5b explicitly excluded.",
    "C-s5-2-numitem-005":
        "Built-in evaluators run on service-owned credentials using Geo Cross-Region "
        "Inference. Not observable from the customer side: we cannot see which credentials "
        "or Regions a service-owned evaluator uses. F8-6 tests the in-geography property "
        "for OUR OWN cross-Region inference, which is the closest reachable analogue. "
        "Remedy: AWS-side attestation.",
    "C-s5-3-numitem-003":
        "A/B testing reports statistical significance at p<0.05 with sticky traffic "
        "splitting. Testable in principle but requires a live A/B experiment with enough "
        "traffic to reach significance — cost and duration outside this project's ceiling, "
        "and it measures an AgentCore Optimization feature rather than a guardrails "
        "property. Remedy: a dedicated Optimization study.",
}

# Anchors whose content is definitional by construction: the document's own
# framework, its change log, or its bibliography.
ANCHOR_RULES: dict[str, tuple] = {
    "s2-1": ("D", (), "Hop numbering is explicitly declared as this document's own "
             "framework ('AWS documentation has no hop concept'). A naming convention "
             "cannot be false, only useful or not. Classifying it D rather than "
             "manufacturing a test is the correct scientific answer.",
             "the numbering IS the normative definition other sections depend on"),
    "s9": ("D", (), "Reference-architecture diagram labels restate claims made in prose "
           "elsewhere. Testable content is merged into the canonical claim via "
           "MERGE_GROUPS; the remaining labels are structural.",
           "structural parity is verified by the 11/11 mermaid render gate"),
    "s2": ("D", (), "Architecture-overview diagram labels: phase names and grouping, the "
           "document's own organizing frame.", "structural"),
    "s10": ("O", ("F0-1",), "",
            "documentation references: the URL resolves AND the page is about what the "
            "row says it is"),
    "appC": ("D", (), "Change log v1.1 -> v1.2: statements about the document's own edit "
             "history. Self-referential and verifiable only by diffing v1.1 against v1.2, "
             "which is a provenance check rather than a claim about AWS.",
             "diff-verifiable; not an AWS behaviour claim"),
}

TYPE_RULES: dict[tuple[str, str], tuple] = {
    # Table header rows label columns; they assert nothing on their own.
    ("*", "thead"): ("D", (), "Table header row — column labels, not a proposition. The "
                     "claims live in the body rows.", "structural"),

    # ---- section-scoped defaults ----
    ("s3-1", "bullet"): ("C", ("F1-3", "F1-7", "F1-8"), "",
                         "Hop #1 capability list"),
    ("s3-1", "numitem"): ("N", (), "Best-practice recommendation: a prescription addressed to the "
                          "reader, not a proposition about AWS behaviour, so no experiment "
                          "can falsify it. The underlying capability it presumes IS tested "
                          "(see the same section's C/S claims); whether following the "
                          "recommendation is advisable remains a value judgement. "
                          "Recommendations that do make a measurable prediction are "
                          "operationalized individually in OVERRIDES.", "normative"),
    ("s3-1", "prose"): ("C", ("F1-19",), "", "service identification + thresholds"),
    ("s3-2", "bullet"): ("C", ("F1-7", "F1-10"), "", "Hop #2 capability list"),
    ("s3-2", "numitem"): ("N", (), "Best-practice recommendation: a prescription addressed to the "
                          "reader, not a proposition about AWS behaviour, so no experiment "
                          "can falsify it. The underlying capability it presumes IS tested "
                          "(see the same section's C/S claims); whether following the "
                          "recommendation is advisable remains a value judgement. "
                          "Recommendations that do make a measurable prediction are "
                          "operationalized individually in OVERRIDES.", "normative"),
    ("s3-2", "mermaid"): ("S", ("F10-1",), "", "billing-asymmetry decision diagram"),
    ("s3-2", "prose"): ("C", ("F1-2",), "", "service identification"),
    ("s3-3", "bullet"): ("C", ("F1-2",), "", "ApplyGuardrail capability list"),
    ("s3-3", "numitem"): ("N", (), "Best-practice recommendation: a prescription addressed to the "
                          "reader, not a proposition about AWS behaviour, so no experiment "
                          "can falsify it. The underlying capability it presumes IS tested "
                          "(see the same section's C/S claims); whether following the "
                          "recommendation is advisable remains a value judgement. "
                          "Recommendations that do make a measurable prediction are "
                          "operationalized individually in OVERRIDES.", "normative"),
    ("s3-3", "prose"): ("C", ("F1-2",), "", "service identification"),
    ("s3-4", "trow"): ("C", ("F1-6", "F1-10", "F8-4", "F8-5"), "", "tier comparison table"),
    ("s3-4", "bullet"): ("S", ("F8-2", "F8-7", "F8-8"), "", "tier/language consequences"),
    ("s3-4", "mermaid"): ("C", ("F1-6", "F8-2"), "", "tier-selection decision tree"),
    ("s4-1", "bullet"): ("E", ("F4-4", "F4-5", "F2-1"), "", "Cedar capability list"),
    ("s4-1", "numitem"): ("N", (), "Best-practice recommendation: a prescription addressed to the "
                          "reader, not a proposition about AWS behaviour, so no experiment "
                          "can falsify it. The underlying capability it presumes IS tested "
                          "(see the same section's C/S claims); whether following the "
                          "recommendation is advisable remains a value judgement. "
                          "Recommendations that do make a measurable prediction are "
                          "operationalized individually in OVERRIDES.", "normative"),
    ("s4-1", "mermaid"): ("E", ("F4-3",), "", "two-level enforcement-mode decision diagram"),
    ("s4-1", "prose"): ("C", ("F1-5",), "", "service identification"),
    ("s4-2", "bullet"): ("C", ("F1-17",), "", "Hop #5 capability list"),
    ("s4-2", "numitem"): ("N", (), "Best-practice recommendation: a prescription addressed to the "
                          "reader, not a proposition about AWS behaviour, so no experiment "
                          "can falsify it. The underlying capability it presumes IS tested "
                          "(see the same section's C/S claims); whether following the "
                          "recommendation is advisable remains a value judgement. "
                          "Recommendations that do make a measurable prediction are "
                          "operationalized individually in OVERRIDES.", "normative"),
    ("s4-2", "prose"): ("C", ("F1-17",), "", "service identification"),
    ("s4-3", "bullet"): ("O", ("F7-2", "F7-4"), "", "observability capability list"),
    ("s4-3", "numitem"): ("N", (), "Best-practice recommendation: a prescription addressed to the "
                          "reader, not a proposition about AWS behaviour, so no experiment "
                          "can falsify it. The underlying capability it presumes IS tested "
                          "(see the same section's C/S claims); whether following the "
                          "recommendation is advisable remains a value judgement. "
                          "Recommendations that do make a measurable prediction are "
                          "operationalized individually in OVERRIDES.", "normative"),
    ("s4-3", "prose"): ("O", ("F7-4",), "", "service identification"),
    ("s4-4", "prose"): ("E", ("F5-1", "F5-2"), "", "containment-pattern rationale"),
    ("s4-4", "trow"): ("E", ("F5-1",), "", "hook-mapping / bypass-route table"),
    ("s4-4", "mermaid"): ("E", ("F5-1", "F5-2"), "", "containment architecture diagram"),
    ("s4-4", "bullet"): ("E", ("F5-5",), "", "honest-boundary list"),
    ("s4-5", "prose"): ("E", ("F5-7b",), "", "network-containment framing"),
    ("s4-5", "quote"): ("D", (), "Source caveat about NDA provenance — a statement about "
                        "this document's sourcing, tracked by the release gate rather "
                        "than by experiment.", "release-gate tracked"),
    ("s4-5-1", "bullet"): ("E", ("F5-7b",), "", "egress allowlist"),
    ("s4-5-1", "prose"): ("E", ("F5-7b",), "", "egress lockdown consequence"),
    ("s4-5-2", "prose"): ("E", ("F5-7b",), "", "Code Interpreter risk framing"),
    ("s4-5-2", "trow"): ("E", ("F5-7b",), "", "network-mode table"),
    ("s4-5-3", "prose"): ("C", ("F5-7a",), "", "PrivateLink matrix framing"),
    ("s4-5-4", "numitem"): ("C", ("F5-7a",), "", "network traps"),
    ("s4-5-5", "prose"): ("E", ("F5-7b",), "", "IAM-enforced VPC deployment"),
    ("s4-5-5", "mermaid"): ("E", ("F5-7b",), "", "contained-network diagram"),
    ("s5-1", "bullet"): ("S", ("F3-1", "F6-5"), "", "Hop #6 capability list"),
    ("s5-1", "numitem"): ("N", (), "Best-practice recommendation: a prescription addressed to the "
                          "reader, not a proposition about AWS behaviour, so no experiment "
                          "can falsify it. The underlying capability it presumes IS tested "
                          "(see the same section's C/S claims); whether following the "
                          "recommendation is advisable remains a value judgement. "
                          "Recommendations that do make a measurable prediction are "
                          "operationalized individually in OVERRIDES.", "normative"),
    ("s5-1", "mermaid"): ("C", ("F1-12",), "", "streaming-mode diagram"),
    ("s5-1", "prose"): ("C", ("F1-12",), "", "streaming trade-off"),
    ("s5-2", "bullet"): ("C", ("F1-23",), "", "Evaluations modes"),
    ("s5-2", "numitem"): ("N", (), "Best-practice recommendation: a prescription addressed to the "
                          "reader, not a proposition about AWS behaviour, so no experiment "
                          "can falsify it. The underlying capability it presumes IS tested "
                          "(see the same section's C/S claims); whether following the "
                          "recommendation is advisable remains a value judgement. "
                          "Recommendations that do make a measurable prediction are "
                          "operationalized individually in OVERRIDES.", "normative"),
    ("s5-2", "prose"): ("C", ("F1-23",), "", "service identification"),
    ("s5-3", "bullet"): ("C", ("F1-22",), "", "Optimization capability list"),
    ("s5-3", "numitem"): ("C", ("F1-22",), "", "Optimization capability detail"),
    ("s5-3", "prose"): ("C", ("F1-22",), "", "service identification"),
    ("s6-1", "trow"): ("S", ("F6-1", "F6-2", "F6-3", "F6-4", "F6-5", "F6-6"), "",
                       "the ILLUSTRATIVE latency table — the headline deliverable"),
    ("s6-3", "mermaid"): ("O", ("F7-4",), "", "span-hierarchy diagram"),
    ("s6-3", "prose"): ("D", (), "Cross-reference to the hop numbering defined in 2.1. "
                        "A pointer to the document's own convention carries no "
                        "independent truth value. What span names actually appear IS "
                        "tested, by F7-4 over aws/spans.", "structural"),
    ("s6-3", "quote"): ("O", ("F7-4",), "",
                        "span names are illustrative; aws/spans is documented"),
    ("s6-4", "trow"): ("O", ("F7-6", "F7-1"), "",
                       "alarm table — every threshold has a floor set by publish lag"),
    ("s7-1", "trow"): ("N", (), "Design principle: a prescription, not a proposition. "
                       "Operationalized where it makes a measurable prediction "
                       "(principles 2 and 3, see OVERRIDES).", "normative"),
    ("s7-1", "mermaid"): ("O", ("F3-10",), "", "LOG_ONLY -> ENFORCE calibration workflow"),
    ("s7-2", "trow"): ("E", ("F4-1", "F3-2"), "", "anti-pattern table"),
    ("s7-3", "trow"): ("N", (), "Recommended guardrail distribution: a configuration "
                       "recommendation. The underlying capabilities are tested by F1/F3; "
                       "whether this particular distribution is 'recommended' is a value "
                       "judgement.", "normative — underlying capabilities covered by F1/F3"),
    ("s8", "checkitem"): ("N", (), "Implementation-checklist step: an instruction to the "
                          "reader. Testable checklist items are overridden individually; "
                          "the rest are procedural (create a dashboard, write a runbook) "
                          "and have no truth value.", "procedural"),
    ("s8", "prose"): ("D", (), "Checklist phase label ('Phase 1: Foundation' and "
                     "similar). An organizing heading for the checklist below it, not a "
                     "claim; the checklist items themselves are triaged individually, "
                     "and the testable ones are overridden to E/S/C/O.", "structural"),
    ("appA", "trow"): ("N", (), "Decision-matrix recommendation per content risk. The "
                       "capability behind each cell is tested by F1/F3/F8; the "
                       "recommendation itself is a value judgement.",
                       "normative — cells backed by F1/F3/F8"),
    ("appB", "trow"): ("S", ("F6-9",), "", "latency-optimization technique table"),
    ("appB", "quote"): ("S", ("F2-5",), "",
                        "caching removed because evaluation is non-deterministic"),
    ("s6-1", "prose"): ("S", ("F6-8",), "", "per-additional-tool-call figure"),
    ("s4", "prose"): ("D", (), "Cross-reference stating that Hop #3 (model inference) "
                      "is not a guardrail checkpoint. This is a consequence of the "
                      "document's own hop numbering from 2.1, which is definitional; "
                      "there is no AWS behaviour that could make it false. The latency "
                      "of Hop #3 IS measured, as part of F6-6's end-to-end total.",
                      "structural"),
    ("s4-5-1", "quote"): ("D", (), "NDA source caveat.", "release-gate tracked"),
    ("s1", "prose"): ("S", ("F6-6",), "", "executive-summary latency framing"),

    # metric tables
    ("agentcore-gateway-metrics", "trow"): ("O", ("F7-2",), "", "gateway metric rows"),
    ("agentcore-policy-metrics", "trow"): ("O", ("F7-1",), "", "policy metric rows"),
    ("bedrock-guardrails-metrics", "trow"): ("O", ("F7-3",), "", "guardrails metric rows"),
    ("bedrock-runtime-metrics", "trow"): ("O", ("F7-2",), "", "runtime metric rows"),
    ("agentcore-runtime-session-metrics", "trow"): ("O", ("F7-2",), "", "session metric rows"),

    # front matter
    ("aws-bedrock-agentcore-before-during-afte", "trow"): (
        "D", (), "Document metadata (version, date, scope, audience) — properties of the "
        "document, not of AWS.", "metadata"),
}
