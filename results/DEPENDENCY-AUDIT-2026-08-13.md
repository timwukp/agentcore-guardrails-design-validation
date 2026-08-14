# Dependency audit of the 19 outstanding cases — 2026-08-13

Read-only investigation. **No account state was changed by this audit.** The one exception is
disclosed below under F5-9: three `converse()` calls of ≤20 tokens each, made deliberately to prove
invokability, and attributable to this audit.

Purpose: the user asked for every remaining case to run on EC2 tonight, with the calendar gate
removed "and all the dependence". This file settles, per case, whether the dependency is *work*
(so it can be done) or *physics* (so it cannot). The distinction matters because an honest "not
tonight, here is the physical reason" is worth more than a case that runs and measures the wrong
thing.

## Summary

| Group | Cases | Count |
|---|---|---|
| Executable tonight, no new infrastructure | F1-6, F1-19, F1-24, F1-25, F1-26, F1-27, F1-28, F5-3a, F5-3b, F5-4b, F5-5, F5-9, F8-1, F9-3, F10-3 | 15 |
| Blocked on an arm64 container build | F1-15, F5-7b, F5-8 | 3 |
| Blocked on physics | F10-1 | 1 |

15 + 3 + 1 = 19, which reconciles against `census.py`'s outstanding count. The arithmetic is stated
because two numbers in one sentence move independently and a total that is asserted rather than
derived is unverified.

## Gates that turned out to be CLOSED (four cases unblocked)

### F5-9 — account-level enforced guardrail

The seal's HARD GATE is "requires a model provably unused by any other system in the account."

**Chosen model: `meta.llama3-8b-instruct-v1:0`.**

The proof is a 455-day CloudWatch `Invocations` query (the full retention window,
2025-05-15 .. 2026-08-13) returning **0 datapoints** for *all three* identifier forms — bare,
`us.`-prefixed and `global.`-prefixed — and the model has **no inference profile** in this account,
so the bare id is the only invocation surface that exists. Coverage is therefore complete rather
than sampled.

Two things make this proof trustworthy rather than merely reassuring:

- **A positive control.** `us.amazon.nova-micro-v1:0` returns 5402 invocations over the same query.
  Without it, a broken query returning zero for everything would read exactly like an unused model.
- **It disqualified three candidates that a cheaper method called clean.** CloudWatch `ListMetrics`
  only reports metrics with data in the trailing **14 days**, and on that basis 45 models looked
  unused. The 455-day query then found `amazon.nova-pro-v1:0` (11 invocations) and
  `qwen.qwen3-32b-v1:0` (807). Worse, `amazon.nova-lite-v1:0` was clean on its *base* id while its
  inference profile `us.amazon.nova-lite-v1:0` carried **240** invocations — a real workload,
  invisible to a base-id-only check. Enforcing a guardrail on it would have hit someone else's
  traffic. This is why the profile variants are queried and not just the base id.

Invokability confirmed 2026-08-13: `converse()` returned 20 tokens. **That invocation is mine** and
is the first ever recorded for this id; anyone auditing the CloudWatch history later should attribute
it here and not to a third party. `mistral.ministral-3-3b-instruct` and `openai.gpt-oss-20b-1:0`
also passed both the 455-day check and the invoke probe, and stand as alternates.

Blast radius: **0 pre-existing enforced-guardrail configurations in us-east-1**, so
`PutEnforcedGuardrailConfiguration` cannot overwrite another workload's config and the matching
`Delete` restores the account exactly.

One SDK trap to carry into the script: `modelEnforcement` is **optional** on the input shape, and
omitting it is presumably account-wide. It must therefore *always* be sent, scoped to
`includedModels=[the one model]`. The case runs ≤5 minutes with restore in a `finally` and
`ListEnforcedGuardrailsConfiguration` verification after.

### F5-3a — SCP authoring and propagation

Verified 2026-08-13: this **is** the Organizations management account, `FeatureSet=ALL`, and on root
`r-sztp` `SERVICE_CONTROL_POLICY` is `ENABLED`.

The case is also lighter than assumed, because enforcement *from inside* a member account is a
separate sealed case (F5-3c). F5-3a needs only a fresh **empty** child OU, one new SCP attached to
that OU alone, and `DescribeEffectivePolicy`. An empty OU contains no member accounts, so no live
principal can be affected by the deny.

Do not touch: the 2 existing child OUs (`production`, `DevOps`) or the 3 existing SCPs
(`FullAWSAccess`, `devOpsOnly`, `productionOnly`).

### F5-3b — IAM permissions boundary blocks UpdateGateway

`grx-attacker-r20260810T130945Z` already exists **with no permissions boundary attached** — which is
precisely the pre-state the case needs. It is a role this project created, so attaching a boundary,
re-running the F5-2 attack, and detaching touches nothing outside the testbed. The seal's mutation
("remove boundary → succeeds") is the F5-2 result already on file.

### F5-4b — guardrail evaluation cannot run (permission removed)

The premise holds exactly as the seal assumes. `grx-gw-exec-r20260810T130945Z` carries a single
inline policy whose statement `Sid=InvokeGuardrailChecks` grants `bedrock:InvokeGuardrailChecks`,
with **no attached managed policies**. Removing and restoring one named `Sid` in one inline policy on
a role this project owns is surgical and reversible, which is what makes this case runnable at all.

This is the case whose sealed oracle says **OUTCOME UNKNOWN** — fail-closed (DENY) or fail-open
(ALLOW) — so it interrogates something AWS does not document. It is the highest-value case in the
outstanding set and it needs no new infrastructure.

### F5-5 — indirect prompt injection via tool response (also already unblocked)

No new infrastructure needed: the echo Lambda `grx-echo-r20260810T130945Z` (python3.12, created
2026-08-10) exists and is already wired to `gateway/main` as target `grxecho`, status `READY`. The
case needs only the `suppressOutput` + `PromptAttack` policy on `context.output` plus the mutation
that removes it.

## Blocked on an arm64 container build — F1-15, F5-8, F5-7b

These three share one dependency: **an AgentCore Runtime, and this account has none belonging to
this project.** All 19 existing runtimes are `harness_*` or `uitestagent_*`, every one of which is on
the do-not-touch list.

The testbed clearly intended to create one — `grx-runtime-exec-r20260810T130945Z` already exists as
an execution role — so this is in-plan work rather than new design. What blocks it tonight is
narrower and mechanical: an AgentCore Runtime needs a **linux/arm64** container image, and the runner
instance is a **t3.small / x86_64 with 2 vCPU**. A qemu cross-build on 2 shared vCPU is impractical
inside tonight's window.

The fix is cheap and reversible rather than clever: a Graviton builder (`t4g.small`, ~$0.02/hr) or
CodeBuild ARM produces the image natively. That is well inside the project's spend authority, so
this group is *deferred by sequencing*, not refused.

Case-specific extra beyond the shared runtime:

- **F1-15** needs one gateway target per type. `gateway/main` currently has **1** target (`grxecho`,
  an `mcp.lambda`). The claim names MCP / HTTP-runtime / HTTP-inference, and `http.agentcoreRuntime`
  requires a Runtime ARN. `http.passthrough` needs no runtime but is *not* the "HTTP runtime" the
  claim names, so substituting it would decide a different claim than the sealed one.
- **F5-7b** additionally needs subnets plus a **toggleable** NAT route, and the mutation must invert
  in *both* directions. The account has 9 VPCs and 2 `available` NAT gateways, all belonging to other
  workloads — so this case must build its own VPC rather than borrow a route table, or it risks
  someone else's egress. Heaviest of the three.

## Blocked on physics — F10-1

F10-1 attributes cost by resource tag via Cost Explorer, and Cost Explorer data for tonight's
requests lags roughly **24 hours**. No amount of effort tonight produces the delta the oracle reads.
This is a fact about AWS billing pipelines, not about scheduling, so it is reported rather than
worked around.

Worth separating clearly: its sibling **F10-3 is unaffected and runs tonight.** F10-3 reads
`usage.*Units` and `guardrailCoverage.textCharacters` directly off the `ApplyGuardrail` *response*,
so it needs no billing data at all.

## What this audit deliberately does not claim

That the 15 "executable tonight" cases will produce verdicts. It claims only that no *dependency*
stands between them and a run. A case can still land INCONCLUSIVE on its own merits — a mutation
that fails to invert, a control that fails to fire, or an SDK shape that makes the pre-registered
method unexecutable — and per the platform's own rule that outcome gets recorded with its reason
rather than repaired into a verdict.
