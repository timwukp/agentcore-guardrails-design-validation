# FINDING F5-2 — Route #3 is closed in the shipped configuration: 0 of 120 `UpdateGateway` calls from the runtime role were authorized, on each of two UTC days. What needs amending is the remedy — switching the gateway to LOG_ONLY takes one sub-second call and 13 seconds, the denial an operator checks after revoking the grant keeps lying for more than five minutes, and an update body that simply omits `policyEngineConfiguration` detaches the engine without naming it

**Status:** **READY_TO_AMEND** — the sealed oracle's verdict is **TRUE** on both days, so §4.4 row #3's mechanism is confirmed rather than refuted. What §10 sends to the register is the remedy written around that mechanism: four candidates, none of which weakens the row.
**Dates:** **2026-08-12** and **2026-08-13** (UTC, derived from `t_start_utc` on the evidence records, never asserted here: 244 + 263 call records under `case_id` `F5-2`)
**Scripts:** `f5_redteam/02_route3_updategateway.py` (four arms, the staged grant, the full chain, the verdict), sha256 `182cc9da81121e976a514222e1867ffdb4be2fce65a886bfbaec036b4af5f11e` · offline suite `f5_redteam/tests/test_route3_updategateway.py`, **92 tests**, mutation-checked **20 of 20 killed, 0 survived**, control clean, script sha256 identical before and after the harness ran
**Run id:** `r20260810T130945Z` (adopted from the ledger, not minted)
**Raw evidence:** `evidence/r20260810T130945Z/f5/F5-2/` — 507 call records, **all carrying `request_id`**. Day 1: **244 records** — 200 `update_gateway`, 16 `mcp:tools/call`, 8 `mcp:initialize`, 8 `mcp:notifications/initialized`, 3 `get_gateway`, 3 `list_role_policies`, 2 `put_role_policy`, 2 `delete_role_policy`, 1 `create_policy`, 1 `delete_policy` (200+16+8+8+3+3+2+2+1+1 = 244), plus `environment.json`, `summary.json` and the day-1 `analysis.json` set aside as `analysis__day1_2026-08-12.json` — aggregates, not calls, carrying no `t_start_utc`, so they contribute no observation day. Day 2: **263 records** — 217 `update_gateway` (216 against the gateway under test, 1 against the throwaway gateway of §7), 16 `mcp:tools/call`, 8 `mcp:initialize`, 8 `mcp:notifications/initialized`, 3 `get_gateway`, 3 `list_role_policies`, 2 `put_role_policy`, 2 `delete_role_policy`, 1 `create_policy`, 1 `delete_policy`, 1 `create_gateway`, 1 `delete_gateway` (217+16+8+8+3+3+2+2+1+1+1+1 = 263). The 216 reconcile to the run exactly: 148 arm calls (120+3+5+20), 66 propagation probes (30+26+10) and the chain's flip and restore. The n=2 smoke that preceded day 1 is archived whole, records and all, under `evidence/r20260810T130945Z/f5/F5-2_smoke_n2_2026-08-12/`, so no smoke call is counted in any census here. Two things about it are worth stating rather than leaving to be discovered: its 101 dated records **do** carry `case_id: F5-2`, so `check_amendment_readiness.py` — which `rglob`s the whole run directory and filters on the case id, not on the directory — counts them; and they all fall on **2026-08-12**, the day day 1 already establishes, so they add no calendar day to the replication rule. Had the smoke run on its own day it would have credited this case with a day on n=2, which is the failure mode that scoping check exists to prevent one level up.
**Figures in this document are pinned, not typed:** `f5_redteam/tests/test_finding_f52_figures.py` re-derives every number below from the two analysis records and the evidence tree and fails if this document disagrees — **33 arms**, of which the four census arms read `evidence/` and skip where it is absent. That suite is itself mutation-checked by `f5_redteam/tests/test_finding_f52_mutation.py`: **19 of 19 killed, 0 survived**, control clean, this document's sha256 identical before and after. The first run of that harness had **2 survivors**, both the same shape — almost every figure here appears twice (once in §3–§7, once in §9's table), so editing one copy left a `needle in doc` assertion green on the other. **Ten of the nineteen mutants are five pairs**: the same figure falsified in §3–§7 and again in §9, so both staleness directions are measured rather than one.
**Analysis records:** day 1 at `results/phase1/archive/F5-2__day1_2026-08-12.json`, archived before the replicate so day 2's overwrite could not destroy it · day 2 at `results/phase1/F5-2.json` · the smoke at `results/phase1/archive/F5-2__smoke_n2_2026-08-12.json` (`is_smoke: true`, `n_required: 2`, no standing)
**Pre-registration seal in force:** `a2136a9d3dbb…fa74cf1a`
**Cost: under $0.01.** No billable text units at all: the probe policy is a pure Cedar `forbid` with a decimal comparison and reaches no content filter, which the dry-run banner declares in advance as `billable text-unit sources: ~0`. Everything else is control plane and unpriced, and the totals below are for **both** days together: 417 `UpdateGateway` (200 + 217), 6 `GetGateway`, 6 `ListRolePolicies`, 4 `PutRolePolicy`, 4 `DeleteRolePolicy`, 2 `CreatePolicy`, 2 `DeletePolicy`, plus the single `CreateGateway` / `DeleteGateway` pair §7's throwaway gateway cost on day 2 — and 32 gateway `tools/call` with the 32 echo-Lambda executions behind them. The probe policy was deleted in a `finally` — `forbid_deletion` records `deleted: true`, 1 attempt, zero errors — and both IAM grants were deleted with `ok: true` and an empty `error_code`.
**Document under test:** §3.1 **line 149**, best practice #5 — *"Protect the enforcement mode: any principal with `bedrock-agentcore:UpdateGateway` can switch the gateway to LOG_ONLY or detach the policy engine entirely — AWS documents no separate condition key protecting this field. Grant UpdateGateway only to trusted principals and alarm on gateway configuration changes via CloudTrail."* — and §4.4 **line 404**, threat-model row #3 — *"the execution role must NOT include `bedrock-agentcore:UpdateGateway`, policy/policy-engine mutation actions, or interceptor management — because `UpdateGateway` can switch the engine to LOG_ONLY or detach it entirely … Least privilege here IS the anti-jailbreak control."* Also §6.4 **line 731** (*"Policy engine mode change || CloudTrail UpdateGateway event || Verify the change was authorized (Section 3.1 BP#5)"*), §8 **line 801**'s checklist item (*"plus LogOnlyEvalIncomplete and UpdateGateway configuration changes"*), and the §4.4 architecture-diagram nodes at **line 408** — `CloudTrail + CloudWatch alarms (UpdateGateway, policy changes, DenyDecisions, Mode dimension)` and `❌ UpdateGateway / policy mutation (execution role denied + SCP backstop)`.
**Class:** E (mechanism), confirmatory cell. Sealed oracle: *"TRUE (closed) if UpdateGateway is denied to the runtime role; FALSE if it succeeds. Full chain: grant -> LOG_ONLY set -> previously-blocked request passes -> restore -> re-assert blocking."* `kind: ZERO_EVENTS`, `planned_n: 120`, `alpha: 0.00625` (0.05/8), mutation **mandatory**.

<!-- provenance
{
  "status": "READY_TO_AMEND",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F5-2"],
  "amends": ["S3.1", "S4.4", "S6.4", "S8"]
}
-->

## 1. Why a denial is not evidence on its own, and what the mutation had to prove

The runtime execution role holds no `bedrock-agentcore` control-plane permission at all. IAM therefore answers `AccessDeniedException` **before** the request body is examined. A wrong gateway identifier, a malformed body, a member the API does not accept — every one of those produces the same 403 as a genuine authorization boundary, and 120 of them would read as a perfect security result while measuring nothing but a typo.

So the case is built around a mandatory inversion, and the inversion is what the verdict rests on:

> **The identical body, sent by the identical principal, must be ACCEPTED once — and only once — the permission exists.** Only then is the closed arm's 403 about a boundary rather than about the request.

That requirement is a machine-checked guard, not a paragraph: `granted_arm_proved_the_call_is_otherwise_accepted` reads `granted.n_authorized > 0`, and the script asks for `n_authorized` — not `n_usable` — in both the guard and the `mutation_inverted` flag, because an arm that *ran* proves nothing; an arm that was *authorized* does.

Two further hazards shaped the instrument.

**`UpdateGateway` is a full replacement, not a patch.** Read from the live botocore service model rather than typed into the script: **14** accepted members (`authorizerConfiguration`, `authorizerType`, `customTransformConfiguration`, `description`, `exceptionLevel`, `gatewayIdentifier`, `interceptorConfigurations`, `kmsKeyArn`, `name`, `policyEngineConfiguration`, `protocolConfiguration`, `protocolType`, `roleArn`, `wafConfiguration`) of which exactly **4** are required (`authorizerType`, `gatewayIdentifier`, `name`, `roleArn`). Every attempt therefore sends back what `GetGateway` returned, member for member. This is why an unexpectedly-accepted call in the closed arm would have been a no-op on the gateway's configuration and still counted as adverse: authorization is decided before the body takes effect, so sending a faithful copy protects the F4 truth table and the F6 latency verdicts published against this gateway without weakening what `adverse` counts.

**`roleArn` being required drags in a second permission.** A body that must name a role means `iam:PassRole` is evaluated alongside `bedrock-agentcore:UpdateGateway`. Granting only the first would produce an `AccessDeniedException` that is indistinguishable from "the route is closed" — a mutation that fails to invert, read as a confirmation. The grant is therefore **staged**, and the stages are separate arms.

## 2. The instrument: four control-plane arms and one data-plane chain

Same gateway (`grx-gw-r20260810t130945z-zpkfmpwo9n`), same policy engine (`grx_pe_r20260810T130945Z-t6hqadrspf`), same action (`grxecho___echo`, taken from the ledger's `cedar_action_ids` and never concatenated from parts), same principal (`grx-runtime-exec-r20260810T130945Z`). Three interlocks were read live before anything was sent: the gateway `READY` in `ENFORCE` with its engine ARN matching the ledger, the role carrying exactly its shipped `['grx-runtime-exec-policy']`, and the engine carrying nothing but `baseline`.

Each arm ran on both days at the same n. Authorized and denied are given as **day 1 / day 2**:

| arm | IAM state | n | authorized | denied | outcome |
|---|---|--:|--:|--:|---|
| `closed_baseline` | shipped role, no grant | **120** | **0 / 0** | **120 / 120** | `AccessDeniedException` on every call |
| `granted_update_only` | `+ bedrock-agentcore:UpdateGateway` | 3 | **0 / 0** | 3 / 3 | still denied — see §4 |
| `granted_mutation` | `+ iam:PassRole` as well | 5 | **2 / 5** | 3 / 0 | **the inversion** |
| `restored_reassert` | both grants deleted | 20 | **0 / 0** | 20 / 20 | denied again |

Outcomes are classified four ways, not two: `accepted`, `conflict`, `denied_by_iam`, `unusable`. A `ConflictException` is returned **after** authorization, so it counts into `adverse` and is tallied separately — "authorized then serialized away" and "authorized and applied" are different observations of the same authorization outcome. A `ValidationException` is `unusable` and is excluded from the denominator: it is not a denial and must not be denominated as one. Neither occurred on either day (`n_conflict: 0`, `n_unusable: 0` in all four arms, both runs).

The chain is the other half of the oracle, and it runs in the data plane where an operator would actually notice something:

| leg | engine mode | request | decision | n |
|---|---|---|---|--:|
| `enforce_blocked` | ENFORCE | `amount=999.0` | **DENY** | 3/3 |
| `enforce_allowed` | ENFORCE | `amount=1.0` | ALLOW | 3/3 |
| `logonly_blocked` | **LOG_ONLY** | `amount=999.0` | **ALLOW** | 3/3 |
| `reasserted_blocked` | ENFORCE (restored) | `amount=999.0` | **DENY** | 3/3 |

Every leg was unanimous on **both** days — the table is one column because the two days do not differ on it; §9 tabulates them separately anyway, since "identical" is a claim and not a formatting decision.

The blocking policy is a pure Cedar `forbid` — `lint: []`, settled `ACTIVE` — written with a method call rather than an operator because Cedar decimals have no relational operators:

```
forbid (principal, action == AgentCore::Action::"grxecho___echo", resource == AgentCore::Gateway::"…gateway/grx-gw-r20260810t130945z-zpkfmpwo9n")
unless { context.input has amount && context.input.amount.lessThan(decimal("500.0")) };
```

`enforce_allowed` is not decoration. Without it, `logonly_blocked`'s ALLOW is consistent with "the gateway stopped enforcing anything"; with it, the same policy is demonstrably still discriminating by amount at the moment the mode flips. Every data-plane confirmation required **2 consecutive** identical decisions from a **freshly created MCP session**, so a cached session cannot supply the answer.

## 3. Reading 1 — the boundary holds, at the pre-registered n

`closed_baseline` sent **120** `UpdateGateway` calls as the runtime role in its shipped configuration. **0 were authorized. 120 were denied with `AccessDeniedException`.** No conflicts, no validation errors, so `n_usable = 120` with `x = 0`.

* Wilson 99% interval: **`0 [0, 0.05865]`**
* exact one-sided ceiling at α = 0.00625: **0.0414** (`1 − α^(1/n)`)
* `mutation_inverted: true`, `mutation_required: true`, `n_met: true`, `notes: []`, `blockers: []`
* all **11** guards true, including `gateway_was_restored_field_for_field` and `grants_were_removed_from_the_role`

Day 2 reproduced the arm call for call: **120 attempted, 120 usable, 0 authorized, 120 `AccessDeniedException`**, `n_conflict: 0`, `n_unusable: 0`, the same interval and the same ceiling, all 11 guards true, `notes: []`, `blockers: []`. §9 sets the two days side by side, including the two figures that differ.

**Verdict: TRUE.** §4.4 row #3's central claim — that an execution role which does not carry `UpdateGateway` cannot use it — is confirmed, and confirmed with a mutation that shows the same call succeeding when the permission is present. The document is right about the mechanism. Everything below is about the remedy written around it.

## 4. Reading 2 — the document names one permission; two are load-bearing

`granted_update_only` held `bedrock-agentcore:UpdateGateway` scoped to this one gateway ARN, and nothing else. It was **denied 3 of 3**.

On day 1 the wait that preceded the arm polled the same call for the full **300-second** bound and recorded **29 consecutive `denied_by_iam` outcomes**, `reached: false`, 301.1 s. Then `iam:PassRole` on the gateway's execution role was added and the very next wait recorded its **first acceptance at 66.8 s** and three consecutive at **155.2 s**. The record therefore reads `staged_grant.binding_permission` = **`bedrock-agentcore:UpdateGateway` AND `iam:PassRole`** with `pass_role_was_needed: true`, and one reading of that is that `roleArn` being a required member drags `iam:PassRole` into every call, so the document's single-permission framing is incomplete.

**Day 2 ran the same sequence and made the confound worse, in the most useful way.** The update-only wait polled **30** times over **308.7 s**, recorded 30 consecutive denials and `reached: false`, and the arm behind it was again denied 3 of 3. But the wait that followed the `iam:PassRole` grant **never converged**: 24 denials, then 2 acceptances, `reached: false` at **334.1 s**, because three consecutive acceptances are required. The `granted_mutation` arm that ran immediately afterwards was authorized **5 of 5**. Day 1 is the mirror image — that wait *did* converge (first acceptance 66.8 s, three consecutive at 155.2 s) and the arm behind it was denied 3 of its 5. **The pre-arm wait's verdict predicted the arm's outcome in neither direction on either day.**

**That reading is not established by this measurement, and the reason is an ordering confound I did not design out.** The two grants were added in sequence, so "denied for 300 s with one grant, accepted 67 s after the second" is equally consistent with:

* **(a) `iam:PassRole` is co-required** — the update-only denials are permanent, and the acceptance is the second grant taking effect; or
* **(b) the `UpdateGateway` grant simply had not propagated inside its 300-second bound** — the acceptance at 66.8 s is the *first* grant landing late, and `PassRole` is incidental.

Reading (b) is not a hypothetical. This case's own §6 measures the same authorization decision still authorizing for **5.4 minutes** on day 1 and **5.1 minutes** on day 2 after a revocation, and the n=2 smoke's granted-arm wait never converged inside 311.8 s at all — so on this account, on this action, 300 seconds is demonstrably not long enough to conclude anything from a denial. **A wait that ends in `reached: false` cannot distinguish "denied" from "not yet".**

So what §4 reports is what was observed: with `UpdateGateway` alone the call was denied **32** times over 301.1 s on day 1 (29 probes plus the arm's 3) and **33** times over 308.7 s on day 2 (30 plus 3), and with both grants it was accepted on both days — 2 of 5, then 5 of 5. `pass_role_was_needed` is the script's label for that sequence, and this document does not promote it to a claim about which permission is load-bearing. Settling it needs one measurement that has not been made: **grant `UpdateGateway` alone and poll well past any plausible propagation window** — or grant in the reverse order — which is a supplementary read filed as follow-up rather than a change to the instrument between two replicates.

What *is* claimable, and does not depend on which reading is right, is narrower and still not in v1.2: **`UpdateGateway` requires `roleArn`, so this call unavoidably passes a role**, which is a fact about the API shape read from the live service model rather than an inference from timing. An operator auditing §4.4 row #3 for `bedrock-agentcore:UpdateGateway` alone is therefore auditing one condition of a call that touches two IAM surfaces, and `iam:PassRole` is the surface their permissions boundaries and SCPs already cover.

## 5. Reading 3 — the hazard is real, and it takes about thirteen seconds

With both permissions in place the full chain executed exactly as §3.1 warns, as the runtime role, in the data plane:

1. `enforce_blocked`: the `amount=999.0` request is **DENIED** 3/3, and `amount=1.0` is **ALLOWED** 3/3 — the policy is load-bearing and discriminating.
2. One `UpdateGateway` call, sent as `grx-runtime-exec-r20260810T130945Z`, HTTP **202** in **602.8 ms** on day 1 and **931.7 ms** on day 2, flips `policyEngineConfiguration.mode` to `LOG_ONLY`. The gateway settles `READY`.
3. The previously-blocked request is **ALLOWED**, confirmed twice from fresh sessions. Time from the accepted flip to the first confirmed ALLOW: **14.2 seconds** on day 1, **13.2 seconds** on day 2.
4. One more `UpdateGateway` restores `ENFORCE`, HTTP 202 in 587.2 ms (day 2: 549.9 ms), settles `READY`, and `fields_that_differ` against the pre-attack `GetGateway` read is **`[]`** — the gateway is byte-equal on every member outside the documented ignore list, and `pec_restored_exactly` is `true`.
5. Blocking returns: **13.4 seconds** to the first confirmed DENY on day 1, **13.3 seconds** on day 2.

Two things in that sequence are worth an operator's attention and are not in the document.

**The window is seconds, not minutes.** §3.1 says an attacker "can switch the gateway to LOG_ONLY". Measured end to end, the switch is one sub-second API call — 602.8 ms and 931.7 ms — and 13 to 14 seconds of propagation (14.2 s, 13.2 s), on two days. A detection path built on CloudTrail delivery (§6.4 line 731, §8 line 801) is measured against that number, and the honest reading is that CloudTrail tells you what happened, not in time to stop it. This finding does not measure CloudTrail latency and makes no claim about it — but the interval the alarm has to beat is now a number rather than an intuition.

**The attacker cannot read the gateway, and does not need to.** The runtime role was granted `UpdateGateway`, never `GetGateway`. Every accepted write was followed by a settle poll that could not succeed: the **11** `UpdateGateway` calls accepted while the caller was the runtime role — 2 in the `granted_mutation` arm, 3 in the granted-propagation wait, 6 in the revoke wait — produced **121** failed `GetGateway` attempts (11 per episode; the log prints the first 10 and the 11th raises), every one `AccessDeniedException`; the archived console log carries the 110 printed `transport error` lines that leaves (11 episodes × the 10 that print). Day 2's tally is **14** accepted as the runtime role — 5 in the arm, 2 in the granted wait, 7 in the revoke wait — and **140** printed lines, so the same 11-poll pattern puts **154** uncaptured `GetGateway` attempts behind it. None of them is confused with an authorization outcome: `_run_arm` records the failure as `settle_error` on the trial row, verified in the archived checkpoint where `granted_mutation__0002` and `__0005` carry `outcome: accepted`, `http_status: 202` and a `settle_error`, and `settle_error` enters no tally. So a principal in this position is writing blind — and it does not matter, because the data plane answers for them: a request that was blocked starts passing. Write-without-read is not a mitigation.

Those 121 and 154 polls are also the case's one instrument defect, logged as **DEV-P4-34**: `wait_ready` polls with the raw client rather than through `capture`, so no poll of any kind becomes an evidence record, and its `except Exception` retries a 403 eleven times over 30 seconds while printing `transport error`. It moves no verdict — the authorization outcome is in the checkpoint before the settle runs — but it means an evidence-derived census counts *captured* calls, and `retry_attempts: 0` on all 417 `update_gateway` records across the two days is true of the records and false of the run. The instrument was deliberately **not** changed between day 1 and day 2.

## 6. Reading 4 — revoking the grant does not close the route when `DeleteRolePolicy` returns, and does not close when you *check* either

Both inline grants were deleted, both with `ok: true` and an empty `error_code`, and `ListRolePolicies` read back exactly `['grx-runtime-exec-policy']`. Then the same `UpdateGateway` call was polled until it was denied three times in a row. What it recorded:

| | day 1 — 2026-08-12 | day 2 — 2026-08-13 |
|---|---|---|
| probes sent | 15 | 10 |
| first `denied_by_iam` | **325.0 s** after the deletions | **305.8 s** after the deletions |
| three consecutive denials | **345.6 s** | **326.4 s** |
| `accepted` outcomes before the final streak | **6** | **7** |
| `flapped_before_converging` | **true** | **false** |
| outcome sequence | `accepted, accepted, denied, denied, accepted, denied, accepted, denied, accepted, denied, denied, accepted, denied, denied, denied` | `accepted × 7, denied, denied, denied` |

For **5.4 minutes** on day 1 and **5.1 minutes** on day 2 after IAM reported the policy deleted, the call the deletion was supposed to stop was still being authorized. Six of day 1's fifteen probes and seven of day 2's ten returned `202 Accepted` in that window.

**The interval replicated; the oscillation did not, and the two deserve different weight.** Day 1 alternated, so an operator who deletes the grant, re-tests, sees `AccessDeniedException` and concludes the hole is shut had observed one sample from a sequence that went on to authorize four more calls. Day 2 was monotone — seven acceptances, then three denials, nothing authorized after the first denial — so *that* trap is a day-1 observation and is reported as one. What holds across both days is the window itself: about five minutes in which a deleted grant was still authorizing the call, first denial at 325.0 s and 305.8 s, within twenty seconds of each other.

This is the same asymmetry `FINDING-F5-1-REVOCATION.md` measured on `lambda:InvokeFunction` — where 32 of 80 invocations sent *after a denial had been observed* still executed — now reproduced on a **control-plane** action in a different service. It is reported and not required: the strict form ("every post-revocation attempt is denied") asks IAM for a guarantee it does not offer on this timescale, and requiring it would make this case permanently unpublishable while the boundary it actually tests — whether the runtime role in its **shipped** configuration can reconfigure the gateway — is measured cleanly at n=120. What *is* required, and what held, is the end state: the grants are gone from the role, and `restored_reassert` sent **20** more calls after the restore of which **0** were authorized.

## 7. Reading 5 — the document says an attacker can "detach the policy engine entirely" — the body does not have to mention the engine to do it

§3.1 BP#5 and §4.4 row #3 each name **two** hazards, not one: switch the mode to LOG_ONLY, *or detach the policy engine entirely*. §5 measures the first. The second was measured on day 2, on a **throwaway gateway** created for it and deleted in the same run (`grx-gw-f52null-r20260810t130945z-mzntbcesxb`; `ran: true`, `deleted: true`, `delete_error: ""`), attached at creation to the same policy engine in `ENFORCE`.

One `UpdateGateway` call was sent against it whose body **omitted `policyEngineConfiguration`** and changed nothing else — `omitted_members: ["policyEngineConfiguration"]`. The call was accepted, the gateway settled `READY`, and the read-back carries **`pec_after: null`** with `pec_was_cleared: true`.

**Detaching the engine is therefore not a louder operation than switching the mode; it is a quieter one.** `UpdateGateway` is a full replacement (§1), so a full replacement that simply does not mention the policy engine removes it. An operator alarming on the shape §6.4 line 731 and §8 line 801 describe — *"Policy engine mode change"*, an `UpdateGateway` event whose request body sets `mode: LOG_ONLY` — is watching for a field the more complete attack does not contain. The absence of a member is the attack, and a rule written to match a value cannot match an absence.

Two limits, stated rather than left to be inferred. **Why a throwaway gateway:** clearing the engine on `grx-gw-r20260810t130945z-zpkfmpwo9n` would leave it in a state no other case's published verdict was measured against, and `gateway_was_restored_field_for_field` diffs against a `GetGateway` read taken before the chain, not before this probe — so the isolation protects the F4 truth table and the F6 latency verdicts for the same reason §1's faithful-copy body does. **What the isolation costs:** the two gateways share a region and a policy engine, not a configuration history, so this probe says nothing about the gateway the rest of the case measures. It is one accepted call, on one gateway, on one day, with no n behind it — reported here and kept out of the verdict.

## 8. What is NOT claimed

* **No claim about CloudTrail.** Neither the delivery latency of the `UpdateGateway` event nor whether an alarm on it fires was measured. §6.4 line 731 and §8 line 801 are named as sites this finding *bears on* — because §5 quantifies the window they have to beat — not as claims it tests.
* **No claim about any principal other than this runtime role.** §3.1's sentence is about "any principal with `bedrock-agentcore:UpdateGateway`". What was measured is one execution role in one account, with the permission absent (120 trials), present alone (3 trials plus a 29-probe 300-second wait), and present with `iam:PassRole` (5 trials).
* **No claim about which of the two permissions is load-bearing.** §4 sets out the ordering confound in full: the grants were added in sequence, so the observed timing cannot separate "`iam:PassRole` is co-required" from "the `UpdateGateway` grant propagated after its 300-second bound expired". `pass_role_was_needed: true` in the record is the script's label for that sequence and is not treated here as a finding. The only permission fact this document asserts is that `roleArn` is a **required** member of `UpdateGateway`, read from the live service model on each run, so the call cannot be made without passing a role.
* **No claim that withholding `iam:PassRole` closes route #3.** That is the practical question the confound blocks, and answering it needs the long-bound single-grant read named in §4 — not another replicate of the same ordering.
* **No mechanism inside IAM.** The revocation flapping in §6 is measured as an outcome sequence with timestamps. Why the authorization decision oscillates — cached policy, per-endpoint propagation, session reuse — is not measured and is not asserted.
* **No rate on the granted arm.** `granted_mutation` was 2 authorized of 5 on day 1 and 5 of 5 on day 2, and day 1's 3 denials fall inside the same propagation window §4 measures. It is reported as an inversion (`n_authorized > 0`), which is what the guard asks, and not as a success rate for a granted principal.
* **Nothing about the interceptor or policy-mutation half of §4.4 row #3.** The row forbids three things to the execution role: `UpdateGateway`, policy/policy-engine mutation actions, and interceptor management. Only the first was tested. F5-8 carries the second.
* **No claim that the four mode-change latencies generalise.** 14.2 s and 13.2 s to the first confirmed ALLOW, 13.4 s and 13.3 s to the first confirmed DENY. Two confirmations each, one gateway, one region, on the two UTC days this case ran (2026-08-12 and 2026-08-13).
* **No n behind §7.** The detach-by-omission probe is a single accepted call on a single throwaway gateway on a single day. It establishes that the API accepts the omission and honours it — `pec_after: null`, read back — and nothing about how often, how fast, or whether the same body behaves that way on a gateway with a different configuration history. It was not repeated, and `V13-17` carries that as `BLOCKED_ON_REPLICATION` rather than as a measured remedy.
* **No claim that the revocation decision oscillates.** Day 1 flapped, day 2 did not (§6, §9). The two-day claim is the ~5-minute window, not the shape of the sequence inside it.

## 9. Replication — two UTC calendar days

The case ran twice, unchanged. Same script — sha256 `182cc9da81121e976a514222e1867ffdb4be2fce65a886bfbaec036b4af5f11e` on both days — same gateway, same policy engine, same action id, same principal, same pre-registered n. The instrument was deliberately **not** repaired between the runs: DEV-P4-34's uncaptured settle polls are present on both days, because changing the instrument between two replicates makes the second one a different experiment rather than a replication of the first.

| | day 1 — **2026-08-12** | day 2 — **2026-08-13** |
|---|---|---|
| `closed_baseline` authorized / usable | **0 / 120** | **0 / 120** |
| error code on every denial | `AccessDeniedException` | `AccessDeniedException` |
| `n_conflict`, `n_unusable` | 0, 0 | 0, 0 |
| Wilson 99% interval | `0 [0, 0.05865]` | `0 [0, 0.05865]` |
| exact ceiling, α = 0.00625 | 0.0414 | 0.0414 |
| `granted_update_only` | 0 of 3 authorized | 0 of 3 authorized |
| `granted_mutation` — **the inversion** | **2 of 5** | **5 of 5** |
| `restored_reassert` | 0 of 20 authorized | 0 of 20 authorized |
| chain `enforce_blocked` / `enforce_allowed` | DENY 3/3 · ALLOW 3/3 | DENY 3/3 · ALLOW 3/3 |
| chain `logonly_blocked` / `reasserted_blocked` | **ALLOW 3/3** · DENY 3/3 | **ALLOW 3/3** · DENY 3/3 |
| flip call (runtime role) | 202 in **602.8 ms** | 202 in **931.7 ms** |
| restore call (runtime role) | 202 in 587.2 ms | 202 in 549.9 ms |
| seconds until the blocked request was allowed | **14.2** | **13.2** |
| seconds until blocking returned | **13.4** | **13.3** |
| `fields_that_differ` after the restore | `[]` | `[]` |
| update-only propagation wait | 29 probes, `reached: false`, 301.1 s | 30 probes, `reached: false`, 308.7 s |
| granted propagation wait | `reached: true` — first 66.8 s, three consecutive 155.2 s | **`reached: false`** — 24 denials, then 2 acceptances, 334.1 s |
| revocation: first `denied_by_iam` | **325.0 s** | **305.8 s** |
| revocation: three consecutive denials | 345.6 s | 326.4 s |
| revocation: `accepted` after `DeleteRolePolicy` returned | 6 of 15 probes, `flapped_before_converging: true` | 7 of 10 probes, `flapped_before_converging: false` |
| guards true | **11 / 11** | **11 / 11** |
| `notes`, `blockers` | `[]`, `[]` | `[]`, `[]` |
| **verdict** | **TRUE** | **TRUE** |
| dated call records | 244 | 263 |

**Everything the verdict rests on reproduced.** The pre-registered arm is identical to the trial (0 of 120, same error code, no conflicts, no unusable calls), so the interval and the exact ceiling are not recomputed values that happen to agree — they are the same computation over the same counts. All four chain legs reproduced unanimously, including the leg the oracle is written for, and the restore was field-for-field on both days. The revocation window reproduced as an interval: **325.0 s and 305.8 s**, within 20 seconds of each other, which is the number §6 reports.

**Two things differed, and neither is a coin flip that landed the other way.**

1. **`granted_mutation` went from 2 of 5 to 5 of 5.** This is the arm whose *rate* this document already declines to report (§8): the guard asks `n_authorized > 0`, and it is 2 and 5. The difference sits inside the propagation window §4 measures — on day 1 the three denials arrived in the minutes after a wait that had just converged; on day 2 the wait never converged and all five calls were accepted anyway. Day 2 therefore strengthens the inversion (the identical body from the identical principal was accepted five times) while making §4's confound harder, not easier, to dismiss.
2. **The revocation flapping did not reproduce.** Day 1 alternated (`accepted, accepted, denied, denied, accepted, denied, …`, 6 acceptances scattered through 15 probes). Day 2 was monotone: 7 acceptances, then 3 denials, and nothing after the first denial was authorized. So *oscillation* is a day-1 observation and is reported as one; what is claimed across both days is the **~5-minute interval in which the deleted grant was still authorizing calls**, which held. An operator's runbook is not made safe by monotonicity here — 7 of day 2's 10 probes were accepted after IAM reported the policy deleted.

**Not replicated, and labelled as such:** §7's detach-by-omission probe ran on day 2 only, as one accepted call on one throwaway gateway. It is a possibility claim with no n behind it (§8).

## 10. Amendment candidates (drafted, not yet applied)

The register is generated from `claims/triage.csv` by `build_v13_candidates.py`, so what follows is what this finding *contributed* to it — not a second, hand-maintained list of sites. The five §4.4/§3.1 sites this case touches sit in the merge group `M-update-gateway-risk`, whose canonical claim is `C-s3-1-numitem-005` (§3.1 BP#5).

* **`V13-14` extended, not duplicated.** Its subject is that removing an IAM grant does not close a path when `DeleteRolePolicy` returns, measured on `lambda:InvokeFunction`. §6 reproduces that asymmetry on a **control-plane** action in a different service, so F5-2 joins its `planned_cases` and its `evidence` gains the two intervals (325.0 s and 305.8 s to the first denial; 6 of 15 and 7 of 10 probes accepted after the deletions). The candidate's site — row #3's own remedy clause — does not change.
* **`V13-16` (new) — the remedy is a detection path, and §5 measures what it has to beat.** §3.1 BP#5 ends with *"alarm on gateway configuration changes via CloudTrail"*, §6.4 line 731 makes that a verification step, and §8 line 801 makes it a checklist item. Measured end to end, the attack is one sub-second API call (602.8 ms, 931.7 ms) and 13–14 seconds of propagation (14.2 s, 13.2 s) before a previously-blocked request is served. The candidate does not claim CloudTrail is too slow — this case measured no CloudTrail latency (§8) — it asks the document to publish the interval so a reader chooses a control against a number, and to say that the same call passes a role, so `iam:PassRole` belongs in the audit alongside `bedrock-agentcore:UpdateGateway`.
* **`V13-17` (new) — the alarm shape the document names cannot see the detach.** §7's probe: a body that omits `policyEngineConfiguration` clears it (`pec_after: null`). A rule matching *"mode change"* or a request body containing `LOG_ONLY` matches nothing when the engine is removed by omission. Filed `BLOCKED_ON_REPLICATION` on one observation, which is what one accepted call on one day is worth.
* **Filed as a follow-up, not as a candidate: which permission is load-bearing.** §4's ordering confound is not resolvable from these two runs, and a register entry saying *"withholding `iam:PassRole` closes route #3"* would be exactly the unmeasured remedy this finding is objecting to. The supplementary read named in §4 comes first.

## 11. Cross-references

* `FINDING-F5-1-REVOCATION.md` — the same revocation asymmetry, measured first on `lambda:InvokeFunction` from the same role, four replicates over two days. §6 here is its control-plane counterpart, and the two together are why the existing register entry on `C-s4-4-trow-009` is about the remedy rather than the mechanism.
* `FINDING-F5-4A.md` — the other half of what "disable the policy engine" can mean: not switching the mode, but shipping a policy that cannot evaluate. Its LOG_ONLY arm and §5's LOG_ONLY leg are the same mode read from two directions.
* `results/phase1/F4-*.json`, `results/phase1/F6-*.json` — the verdicts published against this gateway in `ENFORCE`, which is why every attempt in every arm sends a faithful full-replacement body and why `gateway_was_restored_field_for_field` is a guard and not a note.
* `DEVIATIONS.md` — **DEV-P4-34** (§5): `wait_ready` polls outside `capture` and retries a 403 as a transport error. Logged against the instrument, deliberately not fixed between the two replicates, and the fix is filed with its own mutation arm.
* `results/phase1/F5-2.json` (day 2) and `results/phase1/archive/F5-2__day1_2026-08-12.json` (day 1) — the two analysis records every figure in §9 is derived from; the day-1 file was archived *before* the replicate ran, so day 2's write could not overwrite the comparison.
* `V13_CANDIDATES.md` — generated by `build_v13_candidates.py`; nothing in the register is hand-edited.
