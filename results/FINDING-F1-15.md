# FINDING F1-15 — Policy evaluates on both target types that can exist; the third cannot be built

**Status:** **AMENDMENT_DEFERRED** — measured live on EC2 in us-east-1, and the sealed verdict is
INCONCLUSIVE, which licenses no change to the document (see the provenance block and §8)
**Date:** 2026-08-14
**Verdict:** INCONCLUSIVE — and the INCONCLUSIVE is the finding, not a gap in effort
**Script:** `f1_config/07_target_type_coverage.py`
**Diagnostics:** `f1_config/diag_target_types.py`, `f1_config/diag_inference_body.py` (2 rounds)
**Raw data:** `results/phase1/F1-15.json`, `results/DIAG-target-types-20260814T054243Z.json`,
`results/DIAG-inference-body-20260814T060945Z.json`, `results/DIAG-inference-body-20260814T061554Z.json`
**Claim under test:** `C-s4-1-bullet-007` (`claims/triage.csv:147`)
**Class:** B (document overstates a surface) + a platform lesson that nearly cost a false verdict

<!-- provenance
{
  "status": "AMENDMENT_DEFERRED",
  "status_note": "The first draft said MEASURED, which is not a token check_amendment_readiness.py recognises, and it broke four of that gate's own CONTROL arms — the tests whose job is to prove the gate can still pass on an unmutated tree. The word was wrong on the merits too: `MEASURED` describes what was done to AWS, while every token in that vocabulary describes what the DOCUMENT may now do. Nothing here licenses an amendment (the sealed verdict is INCONCLUSIVE and one arm was unconstructible), and observations are not complete either, so the token is AMENDMENT_DEFERRED rather than OBSERVATIONS_COMPLETE.",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F1-15"],
  "cases_note": "The two diagnostics are deliberately absent. `diag_target_types.py` and `diag_inference_body.py` are instrument checks, not sealed cases; listing them would let the gate count an instrument round as an observation day for the claim.",
  "amendment_licensed": false,
  "blocked_on": "TWO conditions, and the first is not one a re-run can meet. (1) The sealed verdict is INCONCLUSIVE because the case cannot cover the surface its oracle names: `http.agentcoreRuntime` targets are UNCONSTRUCTIBLE — `protocolType` admits only `MCP`, so the third target type cannot be created at all and its policy behaviour cannot be observed by any number of days. That arm is blocked on the API admitting the type, i.e. on an AWS change, not on more measurement here; until then INCONCLUSIVE is the correct verdict and it licenses no amendment. Substituting `http.passthrough` for it would be the substitution defect this repo names twice. (2) For the two target types that DO exist, the measured policy behaviour (both deny) rests on records from a single UTC calendar day, 2026-08-14, so PREREGISTRATION.yaml's reproduction_before_amendment rule owes a day-2 replication of f1_config/07_target_type_coverage.py before any positive claim rests on it. Separately citable and NOT blocked: that `protocolType` admits only `MCP`, which is read from the botocore service model and is immutable per SDK version rather than an observation of a running service.",
  "note": "The sealed verdict is INCONCLUSIVE, which licenses no amendment. Two sub-results are separately citable because they are direct API-shape observations rather than oracle outputs: protocolType admits only MCP, and the inference wire path is /inference/v1/messages. Both were observed on a single calendar day and are marked accordingly; the protocolType one is read from the service model, which is immutable per SDK version, so it needs no replication. The measured POLICY behaviour (both live target types deny) is one-day and would need a day-2 replication before any positive claim rests on it."
}
-->

## 1. The claim and the sealed oracle

`C-s4-1-bullet-007` says a gateway policy engine governs three wire surfaces, "not MCP tools only":

| # | Claim's description | Claim's path |
|---|---|---|
| 1 | MCP targets | `POST /mcp`, JSON-RPC `tools/call` |
| 2 | HTTP runtime targets | `POST /<target>/invocations` |
| 3 | HTTP inference targets | `POST /inference` |

The seal (`lib/oracle.py`, `Binding(kind='EXISTENCE', unit='count')`):

> TRUE if a policy engine attaches and evaluates on all three target types;
> FALSE if any target type bypasses policy evaluation

`CreateGatewayTarget`'s `targetConfiguration` union has exactly three arms — `mcp`, `http`,
`inference` — and they line up with the claim one for one.

## 2. Result

| Target type | Constructible | Baseline (no policy) | Under an ACTIVE gateway-scoped `forbid` |
|---|---|---|---|
| `mcp.lambda` | yes, READY in 5.2 s | `allowed`, 3 tools advertised | **denied** — JSON-RPC `-32002`, and `tools/list` filtered to 0 tools |
| `http.agentcoreRuntime` | **no** | — | — |
| `inference.provider` | yes, READY in 5.2 s | HTTP 200, forwarded to bedrock-runtime | **denied** — HTTP 403 `permission_error` |

**Both target types that can exist are evaluated, and denied. Neither bypasses policy.** The third
cannot be constructed at this API version, so the oracle's "all three" cannot be satisfied and its
"any target type bypasses" cannot be triggered. Verdict: INCONCLUSIVE.

That is not a hedge. It is the only reading the seal permits, and the reasoning is worth stating
because the two decisive alternatives are both wrong:

- **Not FALSE.** FALSE requires a target type that carries a request past the engine. A target type
  that cannot be created never carries a request, so nothing bypasses anything.
- **Not TRUE.** TRUE requires all three. Two is not three. Reading "all three" as "all that exist"
  substitutes a different quantity for the sealed one — the same defect
  `f3_efficacy/07_model_drift.py:724` names when it cites answering F1-15 with an `http.passthrough`
  target as the archetype. Because a verdict is one word, that substitution would be invisible in
  the published record.

**INCONCLUSIVE licenses no amendment.** The claim is not refuted. What is established is narrower:
the document names a target type this service will not create, and gives the wrong path for one it
will.

## 3. Why the HTTP runtime target cannot exist

`CreateGatewayTarget` refuses the entire `http` arm on the only kind of gateway this API can create:

```
ValidationException: HTTP target configuration is not supported for gateways with MCP protocol
type. Provide an MCP-compatible target configuration and retry the request.
```

The cause is in the service model, not in permissions, quotas, or Region availability.
`CreateGateway`'s `protocolType` is an enum with **exactly one member**:

```
protocolType  enum: ['MCP']
protocolConfiguration  union members: ['mcp']
```

(botocore 1.43.67.) There is no value that produces a non-MCP gateway, so there is no gateway on
which an `http.*` target is accepted. The `http` arm exists in the union and is unreachable.

This also disposes of a substitution the dependency audit had flagged as a risk
(`results/DEPENDENCY-AUDIT-2026-08-13.md:121-124`): using `http.passthrough` in place of
`http.agentcoreRuntime`. The refusal names the whole `http` arm, so passthrough would have failed
identically — the shortcut was never available, and taking it would have decided a different claim
than the sealed one.

**Cost avoided.** The diagnostic probed this arm with a pattern-valid ARN for a runtime that does
not exist, precisely so the answer would arrive before anyone built a runtime. The refusal happens
on the arm and the gateway's protocol type, upstream of ARN resolution — so a role, a zip, an S3
upload and a ~10 s create were all avoided, and they would have bought nothing.

## 4. The inference surface is real, and the document's path for it is wrong

The claim says `POST /inference`. Measured on a live gateway:

| Path | Response |
|---|---|
| `/inference` | `{"success":false,"error":"Http operation is not supported for gateway protocol type MCP"}` |
| `/v1/messages` | same |
| **`/inference/v1/messages`** | **served** — the gateway routes, validates, and enforces policy here |
| `/mcp` *(positive control)* | `-32600 Missing required Mcp-Session-Id header` — the signer works |

The control matters: without it, four HTTP 400s would have read as "no inference path exists at all"
rather than "three wrong paths and one right one".

The real path is a composition. `inference.provider.operations[].path` is the **client-facing** path
(`/v1/messages`), which the gateway serves beneath its own `/inference` prefix. So the document's
`/inference` is the prefix mistaken for the whole route.

### 4.1 Two walls stand in front of that surface, and both look like the same 400

Reaching it required getting past two independent gateway-side rejections that a casual reading
would merge:

**Wall 1 — charset.** A Bedrock model id such as `anthropic.claude-3-5-haiku-20241022-v1:0` returns
`400 Model ID contains invalid characters`. The colon. Confirmed against the API shape rather than
inferred from the message: `operations[].models[].model` has pattern
`[a-zA-Z0-9\-\._\*\?@]+(/[a-zA-Z0-9\-\._\*\?@]+)*`, which admits `*` and `?` globs and no colon at
all. **Bedrock's own canonical model-id form cannot be spelled in this field.** Corroborated both
ways: the two colon-bearing candidates were rejected, every colon-free candidate passed.

**Wall 2 — routing.** Past the charset check, every colon-free id returned
`404 Model '<id>' not found on any target`. The cause is that an `inference.provider` target
declaring only `endpoint` advertises **no models**, so the gateway's routing layer can never select
it. `operations` and `models` are marked optional in the API and are in practice load-bearing: a
target without them is created, reaches READY, and is unreachable.

Declaring `operations: [{path: "/v1/messages", models: [{model: "anthropic.claude-*"}, {model: "claude-*"}]}]`
made it routable. Round 2 then measured HTTP 200 carrying:

```json
{"Output":{"__type":"com.amazon.coral.service#UnknownOperationException"},"Version":"1.0"}
```

That is bedrock-runtime's own Coral front end saying it does not serve `/v1/messages` — i.e. **the
gateway forwarded the request upstream.** Which is exactly what this case needs: not a successful
completion, but proof the request travelled far enough that a policy denial would have to intervene
to stop it.

A control separates that from blanket forwarding: `openai.gpt-4o-mini`, colon-free but matching
neither declared glob, still returned `404 not found on any target`. So the `models` declaration is
what routes — the target does not simply forward everything.

## 5. Two policy-denial wire shapes, one previously undocumented here

The instrument was a single unconditional, gateway-scoped statement:

```
forbid (principal, action, resource == AgentCore::Gateway::"<disposable gateway arn>");
```

`enforcementMode=ACTIVE`, `validationMode=IGNORE_ALL_FINDINGS`, on the shared policy engine.

The action is deliberately unconstrained, and that is what makes the case answerable. The Cedar
action id for an MCP tool is `<TargetName>___<ToolName>`, but the action id of an *inference* request
is unknown — and whether the engine sees such a request at all is the question. A policy that had to
name its action could only be written for the target type whose grammar is already known. An
unconstrained action asks both uniformly. No `when` clause either: round 3 of
`f1_config/diag_resource_form.py` measured that a conditional statement requires a *specific* action,
because the attribute the condition reads must exist in that action's context.

The two surfaces then denied in **different shapes**:

| Surface | Status | Body |
|---|---|---|
| MCP | JSON-RPC | `-32002` — `Tool Execution Denied: Tool call not allowed due to policy enforcement [Policy evaluation denied due to <policyId>]` |
| Inference | **HTTP 403** | `{"error":{"type":"permission_error","message":"Request Denied: Gateway Target request not allowed due to policy enforcement [Policy evaluation denied due to <policyId>]"}}` |

Only the first was previously known in this project (`lib/mcp.py:343-349`). The inference shape —
HTTP 403, `permission_error`, and the wording *Gateway Target request not allowed* — is new here, and
any detection built only on the `-32002` marker would miss a denial on the inference surface
entirely.

The MCP arm also denied through a **second, independent channel**: under the forbid, `tools/list`
*succeeded* and returned zero tools, against three in the baseline. The engine filtered the listing
rather than failing the request. That is a distinct observable from the call denial and worth knowing
for anyone building on tool discovery.

## 6. The near-miss: a FALSE that was published for 24 minutes and was entirely an artifact

The first run of this producer returned **FALSE — the inference target type bypasses policy
evaluation.** That is a security claim about someone else's product, and it was wrong. How it
happened is the most transferable part of this finding.

The inference arm was invoked before and after the forbid. Both times it answered HTTP 400 with a
byte-identical 107-byte body, in 38 ms and 59 ms:

```json
{"error":{"type":"invalid_request_error","message":"Model ID contains invalid characters."},"type":"error"}
```

The classifier matched `invalid_request_error`, labelled it `routed` ("the gateway forwarded rather
than denied"), and the scorer turned *routed in both phases* into a bypass. But the request had been
refused by the gateway's own input validation and **never reached the policy engine in either
phase**. Both observations were of traffic nothing evaluated, and a verdict was drawn from the pair.

This is DEV-P4-22 (`f3_efficacy/08_score_label_join.py:425-448`) arriving on a surface the producer
had not thought to apply it to. The producer *did* guard the MCP arm against exactly this failure —
an unqualified tool name errors before policy evaluation, so the window measures traffic the engine
never saw — and then walked into the identical trap one arm over. The 38 ms was a second tell,
ignored: far too fast to have crossed an engine and an upstream provider.

**Three defects, each fixed at the level of the general form rather than the instance:**

1. `classify_inference` gained a `front_door_reject` bucket, checked before the generic envelope and
   matched on the validator's own wording. It covers the routing 404 too — a request that never
   selected a target is as pre-evaluation as one refused on charset.
2. A bypass now requires an **eligible baseline**: the request must be shown crossing the gateway
   (2xx, or an error recognisably the upstream's). The old rule accepted a bucket that included the
   gateway's own rejections.
3. The scorer returns a **justification sentence per target type** alongside each label. The wrong
   verdict was a bare word no reader could audit.

**A guard that was added and then removed, which is its own lesson.** An interim version disqualified
any byte-identical before/after pair. Round 2 showed that would suppress the real finding: the
upstream Coral error is deterministic and does not echo the prompt, so a genuine bypass — gateway
forwards in both phases — necessarily produces identical bodies. Identical-ness is now *reported* in
the justification and vetoes nothing; the eligibility rule already does the work the veto was added
for. A guard tuned to one observed failure had been about to hide the class of failure the case
exists to detect.

**What actually caught it:** not a test. Reading the raw response bodies instead of the derived
labels, because a FALSE on someone else's security behaviour warranted looking. Both diagnostics now
print the full body next to every derived bucket for that reason — and it paid off immediately, since
round 1 of `diag_inference_body.py` had a typo (`body_head` vs `body`) that made every bucket read
`other` and fired a spurious "NEGATIVE CONTROL BROKE"; the printed bodies carried the real result
regardless.

## 7. What this entitles the document to say

**Nothing new by amendment** — the verdict is INCONCLUSIVE and the standing rule holds: INCONCLUSIVE
is not FALSE and licenses no amendment.

Separately citable, because they are direct API-shape and wire observations rather than oracle
outputs:

1. **`protocolType` admits only `MCP`**, so `http.*` gateway targets cannot be created at this API
   version. Read from the service model, which is immutable per SDK version — no replication needed.
   Any guidance that tells a reader to create an HTTP runtime target is currently unfollowable.
2. **The inference wire path is `/inference/v1/messages`**, not `/inference`. `/inference` alone is
   refused.
3. **`operations[].models` is load-bearing** on an `inference.provider` target despite being optional
   in the API: without it the target reaches READY and is unroutable.
4. **Bedrock's `:`-bearing model ids cannot be expressed** in `operations[].models[].model`.
5. **A policy denial on the inference surface is HTTP 403 `permission_error`**, not JSON-RPC
   `-32002`. Detection keyed only on `-32002` misses it.

**Carry-forward.** The measured policy behaviour (both live target types deny) is single-day. Under
the two-calendar-day rule it would need a day-2 replication before any *positive* claim rests on it.
Nothing here does — the verdict is INCONCLUSIVE — so the replication is optional rather than owed.
If `protocolType` ever gains a second member, this producer starts returning a decidable verdict
without modification: it attempts the `http` arm on every run and captures the refusal as evidence,
precisely so the case does not silently stay INCONCLUSIVE after the platform changes.

## 8. Safety and residue

Run on a **disposable gateway cloned from `main`** via `CreateGateway`'s own input shape, so it
carries the same `policyEngineConfiguration` (verified: `clone_has_policy_engine: true`). Never on
`main` — extra targets there advertise extra tools on the ENFORCE half of the pair `nopolicy` is the
latency baseline for, and a `forbid` attached to the shared engine would have had to be scoped away
from the very gateway it sat on. The `resource ==` ARN form (not `resource is`) confines the forbid to
the disposable gateway, so `main` was unaffected throughout despite the engine being shared.

Teardown is retried, because the first diagnostic **measured** the hazard: every
`delete_gateway_target` returned ok, `list_gateway_targets` then returned an empty list, and
`delete_gateway` still failed `ValidationException` — the deletions had not finished propagating
service-side. A retry 15 s later succeeded. Both subsequent runs needed attempt 2. A single-attempt
`finally` would have turned a propagation delay into a leaked gateway holding a
`policyEngineConfiguration` and billing.

**Residue: none.** Ledger after the run holds only the two permanent gateways (`main`, `nopolicy`)
and the pre-existing `baseline` policy. One gateway leaked during the first diagnostic and was
deleted; its stale ledger entry was dropped.

**One IAM grant was missing and is now added.** `bedrock-agentcore:DeleteGatewayTarget` was absent
from `runner/iam_policy.py` while `unmapped_operations()` was empty, because `runner/iam_policy.py` is
*derived from captured evidence* and no run had ever replayed that operation —
`infra/05_target.py` stores it as a `delete_op` string on a ledger record and leaves the two
`grxecho` targets standing for the life of the testbed. A derivation from observed calls is blind to
a call nobody has made yet. F1-15 is the first case to create and remove its own targets.
