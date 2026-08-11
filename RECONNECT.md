# Reconnect note — updated 2026-08-11

Read this first if the session dropped. It is the shortest path back to the live state.

## ⇢ RESUME HERE (2026-08-11, evening): F4 smoke is GREEN (rc=0); next is the full n=120 run

The section below this one is HISTORICAL — F4 was finished later the same day. Current state:

- `f4_modes/01_truth_table.py` runs end to end: `--n 3` smoke exits 0, all 8 cells complete,
  testbed restores cleanly, verdicts F4-1..F4-5 TRUE and F4-6 FALSE (the pre-registered
  expected refutation: denials arrive as HTTP 200 + JSON-RPC error -32002, not the documented
  403 + policy id). n=3 does not clear the amendment bar; the full run needs n=120/cell.
- Three measured fixes landed on the way (each carries a MEASURED comment at the site):
  1. The narrow Cedar permit needs `action ==` scoping, a `has` guard, and
     `.lessThan(decimal(...))` — an unscoped `context.input.*` condition must type-check
     against every action in the schema (see `build_policies`).
  2. The guardrail policy needs the same `action ==` scope AT RUNTIME: unscoped, it denies
     everything with "guardrail policy could not be evaluated - missing an attribute", even
     though `IGNORE_ALL_FINDINGS` let it create (see the guardrail statement comment).
  3. `amount` must be sent as `100.0`, not `100` — the engine refuses to bind an integral
     JSON literal to Cedar `decimal` ("Parameter format error"), and both narrow cells then
     deny for the wrong reason (see `BENIGN_ARGS` comment).
- `lib/mcp.classify` now recognises the JSON-RPC -32002 denial shape as `policy_denied`
  (both wire shapes kept; see the MEASURED comment in the error branch).
- Stale checkpoints from the two defective smokes are quarantined under
  `results/checkpoints/_stale_20260811_*` — do not resume from them; the current
  `F4-cells__*.json` checkpoints (post-fix) are the live ones.
- Next: Phase 4 — F2 determinism (4 arms × n=300) + gateway-side F3 + F3-10 + F7.

## HISTORICAL (2026-08-11, morning): F4 is half-written and does not run yet

Task #8 (Phase 3). F1-3 is complete and READY_TO_AMEND; **F4 is mid-write**.

`f4_modes/01_truth_table.py` — **279 lines, syntax-valid, NOT runnable.** It currently holds the
module docstring (the full six-case design), imports, constants, and the classification helpers. Not
yet written: `_f4_6_row`, the arm runners, the two axis switchers, `main()`, teardown.

**One known defect to fix first.** `_classify_f4_6` ends with a placeholder line:

```python
return False, "", detail       # the real decision needs the policy ids; see `_f4_6_row`
```

`_f4_6_row` does not exist. As it stands the function returns "not adverse" for **every** denial,
which would make F4-6 report agreement with the document by construction — the exact
`feedback_vacuous_test_check` shape. Either finish `_f4_6_row` (it needs the created policy ids, so
it has to be a closure or take them as an argument) or fold the classification into the arm runner.
**Do not run F4-6 until this is closed.**

Order of work after that: `--dry-run` (all six banners) → `--n 3` smoke → full n=120 × 6 cells →
`f4_modes/tests/{conftest.py,test_f4_offline_mutations.py}` mirroring `f1_config/tests/` exactly →
then `f1_config/04_policy_grammar.py` and `05_live_boundaries.py` → then wire both test dirs into
`verify_phase0.sh`'s `run_tests()` and raise `compile_all()`'s floor → then update `V13_CANDIDATES.md`.

### Design decisions already closed — do not re-derive

- **Six cases in ONE script.** All six read the same 2×2 and differ only in which cell they
  interrogate. Six files would mean six mode switches on one shared gateway and six restore paths.
- **`billable=False`** in every dry-run banner: F4 sends no `ApplyGuardrail` and no
  `InvokeGuardrailChecks`, so text units are 0. Billable surface is Lambda invocations only.
- **F4-6's `thresholds == (403.0,)` is decorative to its kind.** `oracle._decide`'s `ZERO_EVENTS`
  branch reads only `obs.adverse` and `n` and never consults `thresholds`, so the script must do the
  403/policy-id classification itself. `limits_by_reference` is **empty for all six** — verified
  against the sealed bindings 2026-08-11, correcting an earlier note that claimed F4-6 carried
  `("403",)` there. The banner prints `thresholds: (403.0,)` for F4-6 and
  `(none — kind is not thresholded)` for the other five; the `limits by REFERENCE` line never prints.
- **Only F4-1 and F4-3 are mandatory-mutation cases**, so only they must set `o.mutation_inverted`
  explicitly. `evaluate()` overrides a TRUE verdict to INCONCLUSIVE when the mutation is mandatory
  and `mutation_inverted is None`.
- **F4 owns restore on BOTH axes.** `infra/06_verify.py` pins the engine ARN but **neither mode**,
  with a comment saying F4 legitimately drives the mode to LOG_ONLY. Nothing outside this script will
  notice a mode left switched. Restore to values **measured at startup**, not assumed from the
  ledger, and re-run the blocking assertion (PREREGISTRATION `restore_verification`).
- **`UpdateGateway` is a REPLACE.** Resend the four required members **and** the full live config; a
  field omitted is a field reset, and resetting `exceptionLevel` would change every later error body.
  Readback from both the Update response and an independent `GetGateway` (their OUT shapes are
  identical), plus `04_gateway.wait_ready`.
- **`UpdatePolicy` must NOT resend `definition`.** Re-sending the Cedar body re-runs validation, and
  DC-1 is the finding that this exact statement fails validation without `IGNORE_ALL_FINDINGS`. Send
  `policyEngineId` + `policyId` + `enforcementMode`; read back `GetPolicy.enforcementMode`.
- **`policy` is structurally untaggable**, so the tag sweep cannot catch a leaked policy. F4's own
  `finally` is the only teardown channel for policies it creates.
- **F4-5's forbid arm must be an unconstrained `forbid` against the concrete gateway ARN** —
  `cedar.check_statement`'s lint refuses a scope naming a concrete action without
  `resource == AgentCore::Gateway::"<arn>"`.
- **Prediction on the record, before the run: F4-6 will REFUTE the document.** A gateway policy denial
  arrives as **HTTP 200** with `result.isError: true` and an `AuthorizeActionException`, not the
  HTTP 403 that doc L141 claims. Written down in advance so a confirmation cannot be presented as a
  discovery. Sites to amend if it holds: `C-s3-1-bullet-015` (L141), `C-s2-1-mermaid-002` (L56),
  `C-s9-mermaid-006` (L827).

### Two library fixes landed this session (both mutation-checked)

Written up as **DEV-P3-01**. Both were guards that reported clean while doing nothing, found before
F4's first call:

1. `"InvokeGateway": 10.0` added to `RATE_LIMITS` + `SELF_IMPOSED_LIMITS`. Service Quotas publishes
   **only concurrency** for this path (1000 connections, 1000 per gateway, 6 MB payload) and **no
   per-second rate**; the nearest published rate (25/s) is tool *search*, a different operation. 10/s
   is ours and is labelled as ours. Without the entry `wait("InvokeGateway")` returned 0.0.
2. `McpTransportError` now carries `error_class`, and `RETRYABLE_TRANSPORT` gained the **measured**
   urllib3 names (`NameResolutionError`, `NewConnectionError`, `ProtocolError`, `SSLError`). This was
   DEV-P1-11 on the data plane: the raise site computed the class name and threw it away, so every
   transport failure was classified permanent — and the pool is `retries=False` by design, so nothing
   else would retry either. New `lib/tests/test_mcp_retryability.py` (11 arms); `lib/mcp.py` had had
   **no test module at all**.

Library suite after both: **639 passed, 1 skipped**. `verify_prereg.py` green (`a2136a9d…`, 189
assertions) — neither file is a sealed bound artifact.

### Two gates fired on the new work — both fixed, both worth knowing about

- **`check_redaction.py` was at rc=1** (6 findings). Now **rc=0, 280 files, PASSED**. One was mine (a
  private-range IP literal in the new test → RFC 5737 TEST-NET-1); five were pre-existing false
  positives in offline fakes, now narrowly waived in `ALLOW` with per-entry written reasons. The
  waivers are **mutation-checked**: a real account id planted on a different line of a waived file
  still fails. ⚠️ Read the gate's exit code directly — `check_redaction.py | tail` reports `tail`'s
  rc and will read as a pass while the gate is failing.
- **`lib/tests/test_module_name_collisions.py` failed on `f4_modes/01_truth_table.py`.** The `_load`
  helper built its `sys.modules` key from a parameter, which that guard cannot read statically.
  Fixed by hoisting the key to a module-level constant `GW_MODULE_NAME`, **not** by adding an
  `UNRESOLVABLE` exemption. Any new script in this tree that loads `infra/NN_*.py` by path must pass
  a literal or module-level constant as the module name.

**Not yet done:** `./verify_phase0.sh` has not been re-run since these edits (it was 14/14 before).
`f4_modes/tests/` does not exist, so nothing in `f4_modes/` is under the gate yet.

## Where the work is

- Tree: `/Users/tmwu/Downloads/grx-validation/` (**not** a git repo — do not look for a branch)
- Approved plan: `/Users/tmwu/.claude/plans/melodic-hatching-seal.md`
- Python: `.venv-oracle/bin/python` (botocore 1.43.67). `.venv-baseline` is 1.42.79 and is **data**, not a fallback.
- Full gate: `./verify_phase0.sh` — ~6 min, 14 gates. Last **full** run was 14/14 PASS (1253 tests,
  3 skips) and that was **before** this session's `lib/mcp.py` + `lib/checkpoint.py` edits. The
  library suite alone is green since (`.venv-oracle/bin/python -m pytest lib/tests/ -q` → 639 passed,
  1 skipped), but re-run the full gate before treating 14/14 as current.

## There is live AWS state right now

**run_id `r20260810T130945Z`**, us-east-1, 25 resources in `state.json`:

| kind | n | kind | n |
|:---|--:|:---|--:|
| iam-role | 5 | delivery | 4 |
| delivery-source | 4 | delivery-destination | 3 |
| gateway | 2 | gateway-target | 2 |
| log-group | 2 | policy-engine | 1 |
| policy | 1 | lambda | 1 |

`ExpiresAt` on every tag is a **72 h TTL from creation**. If a reconnect happens after that window
and the work is not continuing, run `infra/99_teardown.py --run` and confirm zero survivors.

## Money spent so far

**≈$0.00**, and the first billable request has now been sent. Everything created is control plane
(free) plus CloudWatch Logs delivery objects (free to define). `08_smoke.py --run` sent 2 billable
`tools/call` requests to a Lambda-backed gateway target plus span ingestion — under $0.01 in total,
below the resolution of Cost Explorer. Phases 3–8 are projected at **$5.86** combined.

## Task state

| # | Task | State |
|--:|:---|:---|
| 1–6 | Phase 0 + Phase 1 foundations | done |
| **7** | **Phase 2 testbed** | **DONE — gate satisfied, see below** |
| 8 | Phase 3: F1 config surface + F4 truth table | **in progress**, $0.06 — F1-3 done; F4 half-written, see top of this note |
| 9 | Phase 4: F2 determinism 4×300 + gateway F3 + F3-10 + F7 | pending, $1.17 |
| 10 | Phase 5 + 5c: F5 red team, watchdog, account-level gate | pending, $0.06 |
| 11 | Phase 6 + 6b: latency n=1000 × ~8 arm pairs | pending, $3.60 |
| 12 | Phase 7 + 8: nine-region probe, F3-11 at +7d/+30d | pending, $0.97 |
| 13 | Phase 9: analysis, figures, bilingual v1.3, NDA release gate | pending, $0 |
| 14 | Phase 99: teardown + tag sweep, zero survivors | pending, $0 |

## Task #7 — closed, with the evidence

The Phase 2 gate as pre-registered was "both gateways READY, benign call allowed on both, a span
carrying each gateway's ARN visible in `aws/spans`". All three hold:

- `06_verify.py` → **42/42 PASS**, rc=0. Re-runnable at any time; it is the precondition every
  later phase checks and Phase 5 re-runs after every restore.
- `07_traces.py --verify-only` → both gateways have a live TRACES delivery, symmetric.
- `08_smoke.py --run` → `tools/call` allowed end to end on both gateways (**831 ms** main,
  **432 ms** nopolicy, request ids archived), echo round trip confirms `context.output.*` is
  drivable, spans visible after 3 s (main) and 90 s (nopolicy).

To re-establish confidence after a drop, in order:
`06_verify.py` → `07_traces.py --verify-only`. Both are read-only and free. Do **not** re-run
`01`–`05`; they are `--ensure`-idempotent but there is nothing to fix.

### Five defects Phase 2's live run found, all written up in `DEVIATIONS.md`

Recorded because each was a real fault in our own harness, not in AWS, and three of them were
guards that would have reported clean while checking nothing:

- **DEV-P2-04** — the tag channel cannot see `iam-role` or `policy`; the fix moves the assertion
  to `list_role_tags`/`get_policy` and re-tests each exemption's premise every run.
- **DEV-P2-05** — the F6 pairing ignore list existed in two copies; `PAIR_IGNORE` is now shared and
  its justification is *checked* by `workload_identity_is_pure_identity()`, not written in a comment.
- **DEV-P2-06** — `put_delivery_*` accepts `tags` only on the create path, so `--ensure` was
  non-idempotent for every delivery resource; and the collision guard decided ownership by **name**,
  so it refused our own leftovers. Ownership is now by `Project`+`RunId` tag, fail-closed.
- **DEV-P2-07** — `SWEEP_TYPE_FILTERS` was a constant nothing applied, and three files reasoned
  from it to the opposite of the measured truth. Replaced by `TAG_INDEX_BLIND_KINDS`, whose values
  are the measurements.
- **DEV-P2-08** — the **evidence writer** broke the first billable call: an MCP `operation` contains
  a `/`, so the filename was a path. `evidence.safe_component()` + 10 test arms including a mutation
  arm. The aborted attempt's record is preserved under `P2-08-smoke-aborted-attempt-01/`.

## Constraints that must survive a reconnect

- **NEVER `git push`.** GitHub Git Data API only (`gh api`, 6-step flow); ref `~/Desktop/github-git-data-api-push.md`.
- Redact the management account id, both member account ids, all ARNs and all bucket names before
  **any** public push. Run `.venv-oracle/bin/python check_redaction.py`; it must read a non-zero
  file count and exit 0. (The ids are deliberately not written here — the first draft of this note
  spelled all three out and the gate reported it, which is the rule working.)
- Spend: act freely under $1000/mo project spend, but **always disclose**. Running total: <$0.01.
- **Never touch**: the 6 pre-existing READY gateways, the 3 DRAFT guardrails (`demo`, `test`,
  `demo123`), the 2 abandoned policy engines (read-only evidence for F1-3), any `harness_*` /
  `uitestagent_*` runtime or Memory resource.
- `lib/stats.py`, `claims/triage.csv`, `claims/triage_rules.py` are **sealed bound artifacts**
  pinned by sha256 in `PREREGISTRATION.yaml`. Do not edit them.
- Chinese for discussion, English for deliverables. `.md` and `.zh-TW.md` change together.

## Three things worth remembering about the testbed

1. **Gateway tracing is not a `CreateGateway`/`UpdateGateway` field** — `bedrock-agentcore-control`
   has zero operations matching Trac/Observ/Telem. It is a CloudWatch Logs **vended delivery**:
   `PutDeliverySource(resourceArn=<gateway arn>, logType="TRACES")` →
   `PutDeliveryDestination(deliveryDestinationType="XRAY")` → `CreateDelivery`. This makes F7-5 a
   *better* experiment: the mutation is `DeleteDelivery`/`CreateDelivery`, which flips one object and
   leaves the gateway config byte-identical, so "spans absent" cannot be confounded with "the gateway
   changed". Those `logs` describe calls take `{limit, nextToken}`, **not** `maxResults`.
2. **DC-1 is confirmed live, twice.** The baseline policy is ACTIVE with `enforcementMode=ACTIVE`
   only under `validationMode=IGNORE_ALL_FINDINGS` — which v1.2 never mentions. A reader following
   §3.1/§7.2/§8 verbatim gets a `CREATE_FAILED` policy.
3. **`state.json`'s `resources` is a LIST, not a dict.** Any ad-hoc inspection script needs
   `rows = res if isinstance(res, list) else list(res.values())`. This has cost time twice.
