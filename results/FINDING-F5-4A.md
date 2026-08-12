# FINDING F5-4a — A policy that cannot evaluate is not "maybe not protecting you". In ACTIVE it denies everything; in LOG_ONLY it is invisible to every instrument the document names

**Status:** **READY TO AMEND** — replicated on two UTC calendar days, every arm and every metric reading identical (see §8)
**Dates:** **2026-08-11** and **2026-08-12** (UTC, derived from `t_start_utc` on the evidence records, never asserted here: 194 + 210 call records under `case_id` `F5-4a`, and 128 + 64 under `F5-4a-logonly-read`)
**Scripts:** `f5_redteam/04_policy_failure_modes.py` (the five arms) · `f5_redteam/04b_logonly_flip_read.py` (the later read-only LOG_ONLY metric query) · offline suite `f5_redteam/tests/test_policy_failure_modes.py`
**Run id:** `r20260810T130945Z` (adopted from the ledger, not minted)
**Raw evidence:** `evidence/r20260810T130945Z/f5/F5-4a/` — 404 call records across the two days, **all 404 carrying `request_id`**: 200 `mcp:tools/call`, 134 `get_metric_statistics`, 46 `list_metrics`, 8 `create_policy`, 8 `delete_policy`, 4 `mcp:initialize`, 4 `mcp:notifications/initialized` (200+134+46+8+8+4+4 = 404), plus the day-1 `analysis.json` set aside as `analysis__day1_2026-08-11.json` — an aggregate, not a call, and it carries no `t_start_utc` so it contributes no observation day. And `evidence/r20260810T130945Z/f5/F5-4a-logonly-read/` — 192 records, 174 `get_metric_statistics` + 18 `list_metrics`, from **three** runs of `04b`: two on day 1 (the first before `_inference_holds` was fixed — see `DEVIATIONS.md` DEV-P4-19 — reading the same window to the same values both times) and one on day 2
**Analysis records:** day 2 at `results/phase1/F5-4a.json` (verdict `RECORDED`) and `results/phase1/F5-4a_logonly_read.json` (`kind: SUPPLEMENTARY_READ`, no verdict) · day 1 at `results/phase1/archive/F5-4a__day1_2026-08-11.json` and `results/phase1/archive/F5-4a_logonly_read__day1_2026-08-11.json`, archived before the replicate so day 2's overwrite could not destroy it
**Pre-registration seal in force:** `a2136a9d3dbb…fa74cf1a`
**Cost: under $0.02 for both days combined.** 200 gateway `tools/call` requests, of which at most 120 reached a content filter (≤ 120 text units at `guardrail_checks_content_text_unit` = $0.00007 → ≤ $0.0084), 180 + 192 = 372 CloudWatch API requests (≈ $0.0037), 16 policy control-plane mutations, 120 echo-Lambda executions. All four probe policies were deleted in a `finally` on **both** days; `deletions` records 4/4 with zero errors each time.
**Document under test:** §6.2 line 661 (the mismatch-metric row), §6.2 line 660 (the LOG_ONLY metric row), §6.4 line 730 (the `LogOnlyEvalIncomplete` alarm row), §7.1 line 737 and the line-743 diagram node (the LOG_ONLY→ENFORCE promotion workflow), §8 line 801 (the alarm checklist item). `validationMode` and `FAIL_ON_ANY_FINDINGS` appear **nowhere** in v1.2, which is itself part of the finding (§6).
**Class:** E (mechanism). The sealed oracle is `RECORDED`: *"OUTCOME UNKNOWN — that is the experiment. Records DENY or ALLOW and whether MismatchErrors/PolicyMismatch fire. Either result is a finding."* No p-value: each arm is all-or-nothing at n=20 and every arm was unanimous, so a split arm would have been the finding rather than an average.

<!-- provenance
{
  "status": "READY_TO_AMEND",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F5-4a"],
  "replication": "Discharged 2026-08-12T00:00:48Z..00:19:10Z: the full five-arm run and the supplementary read were repeated on a second UTC calendar day and reproduced every arm decision, both failure mechanisms, all four mismatch-metric sums and all three LOG_ONLY readings exactly. The original condition was: a replication on a UTC calendar day after 2026-08-11. Both the arm outcomes and the metric readings were taken on 2026-08-11Z. n is not the issue — all five arms were unanimous at n=20 and the metric attribution is exact — but three of the four claims below rest on the ABSENCE of a CloudWatch metric, and absence measured on one day cannot be distinguished from a publishing pipeline that was degraded on that day. The replicate is cheap (100 gateway calls, 8 policy mutations, under $0.01, no new infrastructure) and re-running it also re-tests whether `validationMode=FAIL_ON_ANY_FINDINGS` still accepts both broken policies.",
  "amends": ["S6.2", "S6.4", "S7.1"]
}
-->

## 1. The experiment

Five arms, 20 identical HATE-corpus requests each, to the same action (`grxecho___echo`) on the same gateway (`grx-gw-r20260810t130945z-zpkfmpwo9n`) through the same policy engine (`grx_pe_r20260810T130945Z-t6hqadrspf`). Only the policy differs. The engine carried nothing but `baseline` at start (`interlock.policies_on_engine_at_start: ["baseline"]`), and all five guards held with `guards_failed: []`.

| arm | policy | mode | `CreatePolicy` | settled status | decision at the gateway |
|---|---|---|---|---|---|
| `control_no_probe` | none (baseline permit only) | — | — | — | **ALLOW 20/20** |
| `guardrail_valid_path` | ContentFilter/HATE on `context.input.text` | ACTIVE | 202, `lint: []` | `ACTIVE` | **DENY 20/20** |
| `guardrail_missing_path` | ContentFilter/HATE on `context.input.doesNotExist` | ACTIVE | 202, `lint: []` | `ACTIVE` | **DENY 20/20** |
| `cedar_missing_attr` | plain Cedar `when { context.input.doesNotExist == … }` | ACTIVE | 202, `lint: []` | **`CREATE_FAILED`** | ALLOW 20/20 (no policy ever enforced) |
| `guardrail_missing_logonly` | **the byte-identical statement** of `guardrail_missing_path` | LOG_ONLY | 202, `lint: []` | `ACTIVE` | **ALLOW 20/20** |

The first two arms are not results; they are the bracket that makes the third and fifth attributable. Control ALLOWs, so an ALLOW is not the gateway failing. The valid path DENIes, so a DENY is not the gateway denying everything on principle.

`guardrail_missing_path` and `guardrail_missing_logonly` ship the **same string** — verified as such by `contrast.same_statement` in `results/phase1/F5-4a_logonly_read.json`, compared field-to-field rather than asserted. One denies every request. The other allows every request. The only difference is `PolicyEnforcementMode`.

## 2. The two failure modes are different mechanisms, and neither is fail-open

The pre-registration allowed `FAIL_OPEN`, `FAIL_CLOSED`, `REFUSED_AT_CREATION` and `SPLIT_OR_UNUSABLE`. Measured:

- **A guardrail data path that does not exist → `FAIL_CLOSED`.** The policy reaches `ACTIVE`, reports no error anywhere in its own status, and denies 100% of traffic. Nothing in the resource's state says it is broken.
- **A plain Cedar condition on a missing attribute → `CREATE_FAILED`.** Accepted with HTTP 202, then settled asynchronously into `CREATE_FAILED` with a precise diagnostic naming the attribute, the line and the column, and ending ``did you mean `text`?``

So the service *can* detect this class of mistake at authoring time — it does so for the Cedar condition — and does not do so for the guardrail data path. That asymmetry is the whole finding: the same author error is a compile error in one clause type and a silent total outage in the other.

`SPLIT_OR_UNUSABLE` did not occur: every arm was unanimous, so there is no mixed-decision behaviour to report.

## 3. What the mismatch metrics said, and the arithmetic that is easy to get wrong

Three of the four mismatch metrics fired and are exactly attributable. Every window is recorded in `results/phase1/F5-4a.json`; the 60-minute baseline window ending before the first probe was created has `sum: 0.0` for all four, so every datapoint below is absent-then-present.

| metric | dimension combinations listed, before → after | datapoints | **sum** | value in EVERY datapoint group |
|---|---|---|---|---|
| `MismatchErrors` | 8 → 16 | 6 | 120.0 | 20 |
| `TotalMismatchedPolicies` | 4 → 4 | 8 | 80.0 | 20 |
| `PolicyMismatch` | 4 → 6 | 2 | 40.0 | 20 |
| `LogOnlyEvalIncomplete` | **0 → 0** | 0 | 0.0 | — |

**120, 80 and 40 are not request counts.** Each metric is published under several overlapping dimension combinations that describe the *same* 20 requests at different granularities, and the read sums across all of them. `MismatchErrors` reports 20 under six combinations (`{OperationName, PolicyEnforcementMode}` alone, plus `PolicyEngine`, plus `TargetResource`, plus both, plus the two that add `Policy`) = 120. `TotalMismatchedPolicies` reports 20 under four = 80. `PolicyMismatch` reports 20 under two = 40. The underlying event count is **20 — one per request of the ACTIVE missing-path arm.** An operator summing a mismatch metric across dimensions on a dashboard will read six times the true number.

Attribution is exact and leaves no room for a second explanation:

- the only value the `Policy` dimension ever carries is `grx_f54a_misss_r20260810T130945Z-z776p_sn3i` — the ACTIVE missing-path probe;
- the only value `PolicyEnforcementMode` ever carries is `ACTIVE`;
- `PolicyEngine` and `TargetResource` name this run's engine and gateway only;
- `OperationName` is always `AuthorizeAction`.

**No datapoint on any of the three metrics names the LOG_ONLY policy or the LOG_ONLY mode.** Only `MismatchErrors` carries `PolicyEnforcementMode` as a dimension at all, so for `PolicyMismatch` and `TotalMismatchedPolicies` an operator cannot even filter by mode.

First appearance was inside 123 s of the probe window opening, absent in the two preceding poll rounds. `LogOnlyEvalIncomplete` was polled for the full 900 s bound and its own `list_metrics` returned **zero dimension combinations** — the metric is not named in this namespace in this account at all, which matches F7-1's independent `name_in_namespace_inventory: false`.

## 4. The LOG_ONLY read: the instrument was alive and it reported zero

The strongest claim here is about §7.1's promotion signal, and it needed a read F5-4a did not do. `f5_redteam/04b_logonly_flip_read.py` queried the two LOG_ONLY metrics F5-4a skipped, over the window F5-4a itself recorded (taken from the result file, not re-typed):

| metric | `list_metrics` combinations | baseline sum | probe-window sum | reading |
|---|---|---|---|---|
| `LogOnlyMatches` | **14** | 0.0 | **0.0** | `PUBLISHED_AND_ZERO` |
| `LogOnlyDecisionFlips` | **14** | 0.0 | **0.0** | `PUBLISHED_AND_ZERO` |
| `LogOnlyEvalIncomplete` | 0 | 0.0 | 0.0 | `NEVER_PUBLISHED` |

The distinction between those last two readings is the hinge, and it is why the script makes it structurally rather than in prose: **a zero from a metric that does not exist proves nothing.** `LogOnlyMatches` and `LogOnlyDecisionFlips` exist here — 14 dimension combinations each — and F7-1 measured them publishing 4708 and 3372 over F4's LOG_ONLY cells on this same gateway. So their zero is a real zero from a working instrument, not an instrument absence.

Therefore, over the window in which a broken LOG_ONLY policy served 20 requests:

> `LogOnlyDecisionFlips` was **sustained at zero** — and the byte-identical statement, promoted to ACTIVE, denied **20 of 20**.

§7.1 states the inference this refutes verbatim: *"Watch LogOnlyDecisionFlips: a sustained zero means promotion will not block current traffic."* The line-743 diagram makes it a gate: `LogOnlyDecisionFlips sustained at zero?` → promote. Both are measured false for this defect class.

## 5. Why the document's own recommended rollout is the path that hides this

Put the four readings together from an operator's seat, following v1.2 as written:

1. §7.1 step (1): set the policy engine to LOG_ONLY. The broken policy is accepted — HTTP 202, `lint: []`, settles `ACTIVE`.
2. §7.1 steps (2)–(3): run traffic through it and calibrate. Every request is allowed. `LogOnlyMatches` = 0. `LogOnlyDecisionFlips` = 0.
3. §6.2 and §6.4 and the §8 checklist: alarm on `LogOnlyEvalIncomplete`. The alarm never fires, because the metric is never published — an alarm on it sits in `INSUFFICIENT_DATA` indefinitely, which most alarm configurations do not treat as a problem.
4. §7.1 step (4): "a sustained zero means promotion will not block current traffic." Promote to ENFORCE. **100% of traffic is now denied.**

Every instrument the document names reads clean, at every step, for a policy that is one mode-change away from a full outage. §6.4's remedy for the one signal that is supposed to catch it — *"Calibration data is partial — extend the observation window"* — misdescribes the condition twice over: a policy that cannot evaluate is not partial data, and extending the window produces more of the same nothing.

And §6.2's characterisation of the mismatch family is inverted for ACTIVE mode. It reads: *"a policy that cannot evaluate is a policy that **may not be protecting you** — alarm on it."* Measured, in ACTIVE, the policy protects **absolutely**: it denies everything, including all legitimate traffic. The advice to alarm is right and now demonstrably actionable (three metrics fire within 123 s, correctly labelled with the policy id). What the alarm means is the opposite of what the sentence says: it is an availability page, not an exposure warning. An operator who has read §6.2 will route that alarm to a security queue for review rather than to on-call as an outage.

## 6. `validationMode=FAIL_ON_ANY_FINDINGS` is not a gate, and v1.2 does not mention it

Each broken arm was offered to `CreatePolicy` under `validationMode=FAIL_ON_ANY_FINDINGS` **first**, so "the service refuses it at authoring time" was a reachable outcome. It was not reached: `strict_validation_caught_it` is `false` for all three broken arms. Every one returned **HTTP 202 with an empty `lint` array** under the strictest validation mode the API offers — including the Cedar policy that the service itself diagnosed minutes later with an exact line-and-column error.

So a CI check that creates the policy under `FAIL_ON_ANY_FINDINGS` and gates on the response catches neither mistake. Catching the Cedar one requires polling the policy's status until it settles; the guardrail one is not detectable from the control plane at all and needs a post-deployment request whose expected decision is known.

`validationMode` and `FAIL_ON_ANY_FINDINGS` appear nowhere in v1.2. This is therefore an **addition**, not a contradiction — but an operator reading §7.1's rollout would reasonably assume authoring-time validation exists and works, and it is precisely the assumption that fails.

## 7. What is NOT claimed

- **No mechanism inside the evaluator.** That a policy which cannot evaluate produces no comparison, hence no flip to report, is the natural reading of the zero. It is not measured. `04b`'s `what_this_does_not_prove` says so on the record.
- **No proof of non-publication.** `LogOnlyEvalIncomplete`'s absence is bounded by two 900 s polls and two windows on two days. A metric absent at a bound may publish later. The `NEVER_PUBLISHED` reading is about `list_metrics` not naming it in this account, which is a stronger observation than a zero sum but is still scoped to one account and one region on two days.
- **No claim about other unevaluable conditions.** One missing guardrail data path and one missing Cedar attribute were tested. A malformed regex, a deleted referenced guardrail, an evaluation timeout, a PII policy with a bad entity type — all untested, and the ACTIVE/LOG_ONLY asymmetry may not generalise to them.
- **No claim that F7-1's or F7-3's verdicts change.** Their sealed verdicts stand as recorded. This finding retires the *exclusion reasons* (§9), which is a different act.
- **No rate, no interval.** Five unanimous arms at n=20 are reported as unanimous. `paths` records exactly which two strings were used, so "unevaluable" is never a category standing in for an untested input.
- **Nothing about a working LOG_ONLY policy.** The 4708 matches and 3372 flips are F7-1's measurement over F4's cells, cited as the reason this zero is informative — not re-measured here.

## 8. Replication — two UTC calendar days

The deferral asked for one thing: three of the four claims rest on a metric being ABSENT, and one day cannot separate *"this metric is not published"* from *"the publishing pipeline was degraded on 2026-08-11"*. So the whole case was re-run.

| | day 1 | day 2 |
|---|---|---|
| probe window (derived from the result file, not declared) | 2026-08-11 22:46:33Z .. 23:04:03Z | **2026-08-12 00:00:48Z .. 00:19:10Z** |
| `control_no_probe` | ALLOW 0/20 | ALLOW 0/20 |
| `guardrail_valid_path` (ACTIVE) | DENY 20/20 | DENY 20/20 |
| `guardrail_missing_path` (ACTIVE) | **DENY 20/20** → `FAIL_CLOSED` | **DENY 20/20** → `FAIL_CLOSED` |
| `cedar_missing_attr` (ACTIVE) | 202 → **`CREATE_FAILED`** | 202 → **`CREATE_FAILED`** |
| `guardrail_missing_logonly` (LOG_ONLY) | **ALLOW 0/20** | **ALLOW 0/20** |
| `strict_validation_caught_it`, all three broken arms | false | false |
| `MismatchErrors` sum / datapoints | 120.0 / 6 | 120.0 / 6 |
| `TotalMismatchedPolicies` | 80.0 / 8 | 80.0 / 8 |
| `PolicyMismatch` | 40.0 / 2 | 40.0 / 2 |
| `LogOnlyMatches` | `PUBLISHED_AND_ZERO`, 14 combinations | `PUBLISHED_AND_ZERO`, 14 combinations |
| `LogOnlyDecisionFlips` | `PUBLISHED_AND_ZERO`, 14 combinations | `PUBLISHED_AND_ZERO`, 14 combinations |
| `LogOnlyEvalIncomplete` | `NEVER_PUBLISHED`, **0** combinations | `NEVER_PUBLISHED`, **0** combinations |
| `s7_1_inference_is_refuted` | true (5/5 conjuncts) | true (5/5 conjuncts) |
| guards failed / deletions | `[]` · 4/4, no errors | `[]` · 4/4, no errors |

Day 1 is archived at `results/phase1/archive/F5-4a__day1_2026-08-11.json` and `…/F5-4a_logonly_read__day1_2026-08-11.json`; day 2 overwrote the live filenames, which is why the archive exists. The comparison above is machine-derived from those four files, not transcribed. Days are counted by `check_amendment_readiness.py` from `t_start_utc` on the evidence records whose `case_id` is `F5-4a` — the finding cannot assert its own replication.

Two things the second day added rather than merely repeated:

- **The absence survived a fresh instrument query.** `LogOnlyEvalIncomplete` returned **0** dimension combinations in the 23:00Z–00:00Z baseline query *and* across the day-2 probe window — a second independent `list_metrics` call, 77 minutes after the first, on a day boundary. That is what a degraded-pipeline explanation had to survive, and it did not.
- **The dimension count grows, so the over-count multiplier is not even stable.** `MismatchErrors` listed 8 combinations before day 1 and 16 after; before day 2 it listed 16 and after, **20**. `PolicyMismatch` went 4 → 6 → 8. Each broken policy that ever mismatches leaves its own `Policy`-dimensioned series behind. The day-2 *window* sum was still exactly 120 (the stale series carry no datapoints in it), but a reader whose dashboard sums a mismatch metric across dimensions is summing a set that grows every time somebody ships a broken policy.

What remains not discharged is §7's list, none of which a second day touches: no mechanism inside the evaluator, and no proof that `LogOnlyEvalIncomplete` is absent in other accounts or regions. Two days in one account is what is claimed.

## 9. What this retires elsewhere in the project

Both are recorded as *published readings*, and neither rewrites a sealed verdict.

- **F7-3** recorded all four mismatch metrics `NOT_EXERCISED` because reproducing them "would also perturb the axis F4 measures". F4 is complete, so the objection expired; three of the four are now exercised and attributed (§3).
- **F7-1** excluded `LogOnlyEvalIncomplete` as `NOT_EXERCISED` on the grounds that the condition was *"not reproducible on demand without deliberately shipping a broken policy, which would also change the axis F4 measured"*. F5-4a shipped exactly that broken policy, in LOG_ONLY, for 20 requests. The exclusion is discharged and the measured reading is `NEVER_PUBLISHED`. F7-1's verdict was already FALSE for the 13 of 15 metrics whose publishing condition the project's traffic creates; this adds a 14th to the exercised set and it is absent.

## 10. Amendment candidates (drafted, not yet applied)

Registered in `V13_CANDIDATES.md` (regenerated from `build_v13_candidates.py`; the register is generated, so nothing below is hand-edited into it). All four new candidates carry status `MEASURED_READY`, which is this finding's status after the §8 replication, not a separate judgement:

| Register id | Severity | Sites | Drafted below |
|:--|:--|--:|:--|
| `V13-10` | breaks-the-reader | 3 | §10.3 — §7.1's promotion gate (prose 737, diagram node 739, §6.2 row 660) |
| `V13-11` | misinforms | 3 | §10.2 + §10.5 — `LogOnlyEvalIncomplete` (660, 730, 801) |
| `V13-12` | misinforms | 3 | §10.6 — the fail-secure guarantee per mode (140, 294, 406) |
| `V13-13` | misinforms | 1 | §10.1 — §6.2's mismatch-metric row (661) |
| `V13-01` (extended) | breaks-the-reader | 9 | §10.4 — `validationMode`; this finding measures the converse direction and does **not** discharge V13-01's own sites |

### 10.1 §6.2 — the mismatch-metric row → `V13-13`

Replace *"Fail-secure signal … a policy that cannot evaluate is a policy that may not be protecting you — alarm on it"* with:

> **Fail-secure signal — page it as an outage, not as an exposure.** Measured on 2026-08-11 and reproduced on 2026-08-12 in us-east-1: a guardrail policy whose data path does not exist reaches `ACTIVE` with no error in its own status and then denies **100%** of traffic (20/20), while `MismatchErrors`, `PolicyMismatch` and `TotalMismatchedPolicies` all begin publishing within 123 s, labelled with the offending `Policy` id. A policy that cannot evaluate is not "maybe not protecting you" — in ACTIVE it is protecting you from everything. Route this alarm to on-call availability, and note that these metrics are published under several overlapping dimension combinations describing the same requests: 20 events appeared as a summed 120 on `MismatchErrors` (six combinations), 80 on `TotalMismatchedPolicies` (four) and 40 on `PolicyMismatch` (two). Do not read a dimension-wide sum as a request count. Only `MismatchErrors` carries `PolicyEnforcementMode`, so the other two cannot be filtered by mode.

### 10.2 §6.2 and §6.4 — `LogOnlyEvalIncomplete` → `V13-11`

Both rows tell the reader to alarm on this metric; §6.4's row adds a remedy. Amend to:

> **`LogOnlyEvalIncomplete` was not published in `AWS/Bedrock-AgentCore` in us-east-1 on either 2026-08-11 or 2026-08-12**, under the exact condition it names: `list_metrics` returned zero dimension combinations for it while a LOG_ONLY policy that could not evaluate served 20 requests, and it stayed absent across a 900 s poll. An alarm on it will sit in `INSUFFICIENT_DATA` rather than firing. Verify the metric exists in your account and region before relying on it, and do not treat an alarm in `INSUFFICIENT_DATA` as "no incomplete evaluations". The stated remedy — *extend the observation window* — does not apply to the condition: a policy that cannot evaluate is not partial calibration data, and a longer window yields the same silence.

### 10.3 §7.1 — the promotion gate (the material change) → `V13-10`

After step (4) and beside the line-743 diagram node:

> **A sustained zero `LogOnlyDecisionFlips` does not mean promotion is safe.** Measured on 2026-08-11 and reproduced on 2026-08-12 in us-east-1 with a working instrument (`LogOnlyMatches` and `LogOnlyDecisionFlips` each published 14 dimension combinations in the account and both read exactly 0 over the window): a guardrail policy whose data path does not exist produced **zero matches, zero flips and no `LogOnlyEvalIncomplete`** over 20 requests in LOG_ONLY, and the byte-identical statement in ACTIVE denied **20 of 20**. A zero from a policy that never evaluates is indistinguishable, on these metrics, from a zero from a policy that evaluates and never disagrees. Before promoting, establish that the policy evaluated at all — require a non-zero `LogOnlyMatches` on a deliberately-violating canary request, or promote behind a request whose expected decision is known and roll back on mismatch. `validationMode=FAIL_ON_ANY_FINDINGS` does not substitute for this: it accepted both broken policies with HTTP 202 and an empty `lint` array.

### 10.4 New material for §7.1 or §6.1 — authoring-time validation → extends `V13-01`

> **`CreatePolicy` acceptance is not validation, and `validationMode` is not a CI gate.** Under `FAIL_ON_ANY_FINDINGS`, both a guardrail clause on a non-existent data path and a plain Cedar condition on a missing context attribute returned HTTP 202 with an empty `lint` array. The Cedar one then settled **asynchronously** into `CREATE_FAILED`, carrying an exact diagnostic (``attribute `input.doesNotExist` … not found at line 2, column 8 … did you mean `text`?``); the guardrail one settled `ACTIVE` and denied everything. A pipeline that gates on the `CreatePolicy` response catches neither. Poll the policy to a terminal status before declaring a deployment successful, and follow it with a request whose expected decision is known.

### 10.5 §8 — the checklist item → `V13-11`

Line 801's *"plus `LogOnlyEvalIncomplete` and `UpdateGateway` configuration changes"* needs the §10.2 caveat attached, or it instructs the reader to build an alarm that cannot fire.

### 10.6 §3.1, §4.1 and §4.4 — what "cannot be evaluated" covers → `V13-12`

The three fail-secure claims are the strongest statements in v1.2 that this experiment **confirms**, and the amendment sharpens them rather than retracting them:

> **Fail-secure, stated per clause type and per mode.** Measured on 2026-08-11 and reproduced on 2026-08-12 in us-east-1. In ACTIVE, a guardrail condition on a data path that does not exist denies **every** request (20/20), not some — it is a total outage, not a per-request timeout fallback, and it arrives with the policy reporting `ACTIVE` and `lint: []`. In LOG_ONLY the byte-identical statement denies nothing and publishes nothing. And "cannot be evaluated" covers two mechanisms that behave differently: a missing guardrail data path compiles and reaches `ACTIVE`, while a plain Cedar condition on a missing context attribute is rejected asynchronously into `CREATE_FAILED` with an exact diagnostic. Section 4.4's route #5 remedy needs one correction: of the three mismatch metrics, only `MismatchErrors` carries `PolicyEnforcementMode`, so alarming "on the `Mode`/`PolicyEnforcementMode` metric dimensions" is possible for one of the three and not the other two.

## 11. Cross-references

- `DEVIATIONS.md` → the two instrument defects found while getting this run green: a `--dry-run` gate that is structurally blind to every attribute read below its own `return` (fixed, plus `claims/tests/test_parser_attrs.py`, a tree-wide AST sweep of every `args.<name>` against the real parser, 51 tests), and the root `conftest.py` write guard charging 49 innocent tests for a concurrent live run's writes (fixed with a process-table third channel; the spawners are reported `UNCLEARED`, not cleared).
- `V13_CANDIDATES.md` → `V13-10`, `V13-11`, `V13-12`, `V13-13`, all held at this finding's deferred status, plus the measured paragraph added to `V13-01`. The register resolves them to 10 sites (3+3+3+1), each named explicitly with a written rationale rather than derived from a test case: F7-1 reaches 17 rows and F3-10 reaches 10, and this finding touches three of the 27.
- `results/phase1/F7-1.json`, `results/phase1/F7-3.json` for the exclusions §9 discharges.
- `FINDING-F5-1-REVOCATION.md` — the same deferral shape, for the same reason, on a different mechanism.
