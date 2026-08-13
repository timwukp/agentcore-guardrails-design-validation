# Reconnect note — updated 2026-08-13

Read this first if the session dropped. It is the shortest path back to the live state.

## ⇢ RESUME HERE (2026-08-13): **71 of 92 published; F5 is the whole remaining bulk**

Do not read the case counts out of this file. Regenerate them:

```
.venv-oracle/bin/python census.py --write     # rewrites results/_progress_census.txt
```

Every number in that file is derived from `claims/triage_rules.py` + what is on disk under
`results/phase1/`; nothing in it is remembered, which is why it is the artifact and this section is
only a pointer. As of this writing it reads **71 published / 21 outstanding** of **92
verdict-eligible** (93 registered minus F9-1, the one case untestable by its own sealed oracle), and
**TRUE 41 / FALSE 18 / INCONCLUSIVE 11 / RECORDED 1**. `RECORDED` is a verdict value, not an
exemption: that case (F5-4a) has a file like every other.

| family | state |
|:---|:---|
| **F0, F2, F3, F4, F6, F7** | **complete** — 1/1, 5/5, 11/11, 6/6, 9/9, 7/7 |
| F1 | 20/28 — outstanding F1-6, F1-15, F1-19, F1-24…F1-28 |
| **F5** | **4/12** — outstanding F5-2, F5-3a, F5-3b, F5-4b, F5-5, F5-7b, F5-8, F5-9 |
| F8 | 7/8 — F8-1 |
| F9 | 0/2 — F9-2, F9-3 (F9-1 is untestable, not outstanding) |
| F10 | 1/3 — F10-1, F10-3 |

**Do F5 next.** It is 8 of the 21 outstanding cases and the only family with a large block left; the
rest are singletons.

**F5-7a and F0-1 were not work — they were bookkeeping.** Both were measured, written up and
guarded, and neither had a `results/phase1/` record, so the census counted them outstanding while
their finding documents said they were done (DEV-P4-33). F0-1 was found by
`test_a_written_up_case_has_a_verdict_record`, the guard written after F5-7a, on its first run. That
guard now exists, so this specific way of being wrong is closed — but the general shape is worth
carrying: **a family line reading `F5 4/12` is indistinguishable from honest remaining work.** If a
case looks stuck, check whether it is actually finished before planning a run for it.

### Two things below this line are now WITHDRAWN — do not resume from them

- **The τ-sweep is dead.** The section below plans F2-2/F2-3/F2-4 as a τ-sweep because "no numeric
  guardrail score is published anywhere" (DEV-P4-01). **DEV-P4-27 refuted that**: the score is in the
  *application* logs, at `body.policy.guardrailFindings.<policy>.contentFilter[].score`, as a
  **string**. F2-2/F2-3/F2-4 and F1-18 were measured directly against it and are sealed. The
  original absence probes were not sloppy — they surveyed the surfaces the *document* named, and the
  value was somewhere the document never mentions (`feedback_surfaces_a_doc_names`).
- **"Do F7 next, not F2-2" is spent.** F7 is 7/7.

### Owed write-ups, tracked because a verdict on disk is not a finding

- **FINDING docs owed** for F1-18, F2-2, F2-3, F2-4 (one doc, DEV-P4-27's surface is the story);
  for §3.1's determinism contrast (F2-5 FALSE beside F2-1 TRUE — neither surface varied at all);
  and for F4-6's pre-registered refutation. Format reference: `results/FINDING-F3-10.md`.
- **Day-2 replications owed**: F4-6, F2-1. *(F5-7a's is done — `r20260810T002001Z`, 75 fields, 0
  disagreements, `results/f5_7a_replication.json`; it was listed here in error.)*
- **F0-1 rests on one dated observation** (2026-08-09) of a property that can change — link
  liveness. A re-check must write a **second dated file**, not overwrite
  `results/FINDING-F0-1-references.json`: that artifact is the only observation of that date and
  `claims/tests/test_finding_numbers.py` pins the document's "24/24" against it.
- `FINDING-F3-10.md` is `OBSERVATIONS_COMPLETE`, blocked on a UTC day after 2026-08-12.
  `V13-05` is `BLOCKED_ON_REPLICATION`. `F3-11` needs `--compare` on **2026-08-18** and
  **2026-09-10**.

### The repo state that matters more than any of the above

**`main` is missing 42 files, including the entire `runner/` tree.** PRs #6–#11 were merged in
ascending number order, which for a stack is *top-down*: #6 put `feat/f5-redteam` into `main` first,
then #7–#11 merged upward into branches that `main` had already stopped tracking. Nothing
propagated (`feedback_merged_pr_is_not_landed`, now the third occurrence).

**PR #12** (`feat/write-guard-column-width` → `main`) lands all of it in one merge — 539 blobs
verified byte-for-byte against the trees API, `MERGEABLE`/`CLEAN`. **Push further work onto that same
branch so #12 updates in place. Do not open a new stack** — restacking is what caused this.

```
/tmp/api_push3.sh feat/write-guard-column-width feat/write-guard-column-width <msg-file> <file-list>
```

### There is an EC2 runner, and it is the reason the suites are green on two kernels

`t3.small` in us-east-1, `runner/provision.py` → `runner/sync.py push` → `runner/run.py --detach`.
It exists because five test arms need `setsid` / GNU `df --output=avail` and one needs a `ps` that
truncates — all Linux-only. The laptop suite skips those arms and the runner runs them, so the two
pass counts differ by design and neither is quoted here — regenerate them. Every skip states its
reason and three state a measured number. Two things stay on the laptop by design: **F6 latency** (one network position) and **every
publication** (the instance holds no GitHub credential).

Its disk is the hazard — see **DEV-P4-31**. One suite's `--basetemp` scratch is a measured 10.6 GB,
`run.py` refuses a launch below a **12 GB** floor, and pruning also reclaims a job killed without an
rc file. `--jobs` says `LOST?` rather than inferring `RUNNING`.

## HISTORICAL (2026-08-11, late): F4 full + F2-1 landed; F7 was then the critical path

Kept for the reasoning, not the plan. Its case counts ("44 of 93") and its τ-sweep design are both
superseded above — F7 is 7/7 and DEV-P4-27 found the score. What survives intact is the span
inventory, the request-id join, and the F7-4 correction, all of which were re-measured.

- **F4 full run: DONE at n=120/cell.** F4-1..F4-5 TRUE, F4-6 FALSE (the pre-registered
  refutation). Every cell 120/120 usable, 0 failed, 0 unclassified.
- **F2-1: DONE and TRUE.** `f2_determinism/02_policy_determinism.py`, 3 arms under ONE
  configuration (engine ENFORCE / baseline LOG_ONLY / narrow permit ACTIVE):
  `boundary_below` amount=499.9 → 300/300 **allowed**; `boundary_at` amount=500.0 → 300/300
  **policy_denied**; `far_outside` amount=4242.0 → 30/30 denied. **630/630 usable, 0 flips, 0
  failures**, one-sided flip-rate ceiling **0.00474**. All four subject guards passed, so the
  constancy is not the constancy of an inert policy. Testbed restored, 15/15 blocking checks
  PASS.
  - New config-surface fact from its unscored probe: **four-fractional-digit request literals DO
    bind** (`amount=499.9999` → allowed). The scored arms use one digit anyway, because that was
    unmeasured when the arms were chosen and a wrong guess would have cost the run.
  - Read alongside F2-5 (FALSE, guardrail ceiling 0.00994), **the document's determinism
    contrast in §3.1 did not appear**: neither surface produced any observable variation. That is
    v1.3 material and needs its own finding doc before the amendment pass.
- **DEV-P4-01 registered — no numeric guardrail score is published anywhere.**
  `f7_observability/00_span_shape_probe.py` (read-only, scores nothing) read 60 real spans for
  our gateway from `aws/spans`: **58 distinct attribute paths, zero matches for
  `score`/`confidence`/`threshold`/`guardrail`**, and the plan's predicted
  `aws.agentcore.policy.guardrails.<category>.scores` is **ABSENT**. Full inventory:
  `results/span_shape_probe.json`.
  - **Consequence for ordering: F7 is upstream of F2-2/F2-3/F2-4 and of F3-10.** All four were
    scheduled before F7 on the assumption the score came from the response; it comes from
    telemetry or nowhere, and F7-5 is what makes any span-derived reading non-vacuous.
  - F2-2/F2-3/F2-4 move to a **τ-sweep** instrument (mixed decisions at fixed τ over a fixed
    input prove ≥2 distinct latent scores without observing one — conservative, can only
    under-report). F2-3's strata become τ-bands, which can only *hide* a mixed stratum, so a
    TRUE there must be reported as weakened **in the verdict**, not a footnote.
  - **F1-18 is not rescued and must not be.** It claims a six-value numeric lattice no surface
    exposes → v1.3 amendment material, not a manufactured verdict.
  - What the spans DO carry, per request: `aws.request.id`,
    `aws.agentcore.policy.authorization_decision`, `authorization_reason`,
    `determining_policies[]`, `log_only_matched_policies[]`,
    `log_only_decision_flipping_policies[]`, `gateway.policy.mode`, `jsonrpc.error.code`,
    `tool.name`, and **`latency_ms` / `overhead_latency_ms` / `execute_tool_latency_ms`**.
  - F3-10's FALSE direction is now indicated (decision is joinable per request; the score §7.1
    needs has no left-hand side) but is **not scored** — it gets its own script, including the
    metrics-only arm its sealed method requires.
  - F6 gains a better instrument: server-side per-request latency attributes, which exclude the
    client's own network variance from the policy-overhead number. Register that separately when
    F6 is written.
  - **F7-4: `AgentCore.Policy.AuthorizeAction` spans DO exist** — 246 of them over 48 h, paired
    1:1 with `AgentCore.Gateway.InvokeTool`, and **27 were already inside the probe's original
    60-row sample**. An earlier draft of this file claimed the opposite. That claim was written
    in prose from the *one* sample span the probe serialises into `sample_span_leaves` (an
    InvokeTool row); the probe tallies leaf **paths** and never tallied span `name` at all, so
    nothing checked it — `feedback_prose_is_not_verified` exactly. Re-measured at three
    window/limit settings (120 min × 60, 120 min × 500, 48 h × 500): AuthorizeAction present in
    all three. **The document is right here and F7-4 has no amendment material.** The full span
    inventory is 5 operations: `AgentCore.Gateway.InvokeTool`,
    `AgentCore.Gateway.InvokeTool.grxecho___echo`, `AgentCore.Policy.AuthorizeAction`,
    `AgentCore.Gateway.Initialize`, `AgentCore.Gateway.NotificationsInitialized`.
  - **The request-id join is real and measured: 242 of 250 span `attributes.aws.request.id`
    values (96.8%) match a client-observed `x-amzn-requestid` recorded in an F4/F2-1 checkpoint.**
    One request id carries two spans (InvokeTool + AuthorizeAction), which is the join F7-4's
    sealed method asks for and the left-hand side F3-10 needs. The 8 non-joining ids are the
    `Initialize` / `NotificationsInitialized` spans, whose request ids we never recorded as
    trials. This also gives F7-5 a **specific** absent-arm marker: not "no spans in a window"
    but "no span carries any of *these* request ids".
- Gates re-run after all of the above: `verify_prereg.py` **rc=0, seal `a2136a9d…` intact, 189
  assertions**; `lib/tests/` **672 passed, 2 skipped** (this includes the static
  module-name-collision test that both new by-path loaders had to satisfy).
- Stale checkpoints: the F2-1 n=3 smoke is quarantined under
  `results/checkpoints/_stale_20260811_f2smoke/`. Never resume from a quarantine directory.

## HISTORICAL (2026-08-11, evening): F4 smoke is GREEN (rc=0); next is the full n=120 run

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

- Tree: `/Users/tmwu/Downloads/grx-validation/` (**not** a git repo — do not look for a branch, and
  never `git checkout -- <file>`: the working tree is ahead of anything git here knows about, so a
  mutation harness restores with `cp` only)
- Published to `github.com/timwukp/agentcore-guardrails-design-validation` **by API push only** — see
  the PR #12 note at the top of this file before pushing anything.
- Approved plan: `/Users/tmwu/.claude/plans/melodic-hatching-seal.md`
- Python: `.venv-oracle/bin/python` (botocore 1.43.67). `.venv-baseline` is 1.42.79 and is **data**, not a fallback.
- Full gate: `./verify_phase0.sh` — ~6 min, 14 gates.
- Full suite: `.venv-oracle/bin/python -m pytest -q --basetemp=<scratch>` → ~15 min. Pass
  `--basetemp`; the default location is what wedged the runner's disk (DEV-P4-31). Regenerate the
  pass count rather than trusting one written here.
- **Do not edit the tree while the suite runs.** The write guard watches `results/` and charges a
  concurrent modification to whichever test last spawned a subprocess, so an interactive edit
  surfaces as `ERROR at teardown of test_mutant[...]` naming a file that test never touched. Seen
  2026-08-13: editing `results/FINDING-P0-TRIAGE.md` mid-run errored
  `test_write_guard_mutation.py::test_mutant[M3-no-abspath]`, which passes 20/20 when the tree is
  quiescent. The guard is right — a write into the live results tree must not be excused — so the
  fix is to finish editing first, not to loosen it.
- Redaction gate: `.venv-oracle/bin/python check_redaction.py` — **>120 s**, last run rc=0 over 478
  files / 30,835,735 bytes. Read its exit code *directly*; piping it to `tail` reports `tail`'s rc.
  A run that reads **zero files is an error, not a pass.**

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

Still **under $2**, and the largest single line is now the runner rather than the experiments.
Derived, not remembered:

| item | how it is priced | to date |
|:---|:---|---:|
| control plane, CloudWatch Logs delivery objects | free to create and define | $0.00 |
| billable `tools/call` requests + span ingestion across F1–F7 | per request, all well under Cost Explorer's resolution | <$0.50 |
| EC2 runner `t3.small`, us-east-1 | $0.0208/h; provisioned 2026-08-11, ≤19 h wall-clock since | ≤$0.40 |
| runner root volume, 40 GB gp3 | $0.08/GB-month ⇒ $0.11/day | ≤$0.20 |

The `t3.small` figure is a **ceiling**: EC2's `LaunchTime` resets on stop/start (the volume was grown
from 20 GiB to 40 GB after DEV-P4-31), so uptime cannot be read off the current launch time and the
row above bills the whole window as if it never stopped. Phases 3–8 were projected at **$5.86**
combined and the measured spend is running well under that. **Stop the instance if the work pauses**
— `runner/provision.py` knows the instance id, and a stopped `t3.small` costs only its volume.

## Task state

| # | Task | State |
|--:|:---|:---|
| 1–6 | Phase 0 + Phase 1 foundations | done |
| 7 | Phase 2 testbed | done — gate satisfied, see below |
| 8 | Phase 3: F1 config surface + F4 truth table | F4 **6/6 done**; F1 **20/28** |
| 9 | Phase 4: F2 determinism + gateway F3 + F3-10 + F7 | **done** — F2 5/5, F3 11/11, F7 7/7 |
| **10** | **Phase 5 + 5c: F5 red team, watchdog, account-level gate** | **3/12 — this is the critical path** |
| 11 | Phase 6 + 6b: latency | **done** — F6 9/9, laptop-only by design |
| 12 | Phase 7 + 8: nine-region probe, F3-11 at +7d/+30d | partly done; `F3-11 --compare` owed 2026-08-18 and 2026-09-10 |
| 13 | Phase 9: analysis, figures, bilingual v1.3, NDA release gate | pending — blocked on the owed FINDING docs listed at the top |
| 14 | Phase 99: teardown + tag sweep, zero survivors | pending — **includes terminating the runner** |

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
- Spend: act freely under $1000/mo project spend, but **always disclose**. Running total: <$2 (see
  the table above for how each row is priced).
- **Never touch**: the 6 pre-existing READY gateways, the 3 DRAFT guardrails (`demo`, `test`,
  `demo123`), the 2 abandoned policy engines (read-only evidence for F1-3), any `harness_*` /
  `uitestagent_*` runtime or Memory resource, and the **`nopolicy` gateway** — it is F6's paired
  baseline, so deleting it retroactively unmakes nine verdicts.
- Do **not** modify the account-wide `AWS-AttachIAMToInstance` /
  `SystemAssociationForManagingInstances` association. It targets every instance in the account and
  three other projects depend on it.
- `lib/stats.py`, `claims/triage.csv`, `claims/triage_rules.py`, `lib/oracle.py` and
  `PREREGISTRATION.yaml` itself are **sealed bound artifacts** pinned by sha256. Reading is fine;
  editing is not. `V13_CANDIDATES.md` is **generated** — regenerate it with
  `build_v13_candidates.py`, never by hand. `assert_transaction_search` **asserts, never enables.**
- `evidence/` is local-only by written policy and `.gitignore`d, as are `runner/.state/` and
  `f1_config/.wheel_cache/`. `results/` **is** distributable and is masked by `lib/redact.py`.
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
4. **The guardrail score lives in the application logs**, at
   `body.policy.guardrailFindings.<policy>.contentFilter[].score`, and it is a **string**. Three
   rigorous probes reported it absent before DEV-P4-27 found it, because all three surveyed the
   surfaces the *document* named. Scope an absence claim to the list you actually searched.
5. **`ps` truncates rows to `$COLUMNS` even when stdout is a pipe** (procps-ng; BSD `ps` does not off
   a tty), and pytest exports `COLUMNS`. `conftest._foreign_live_run` therefore ran blind on Linux
   for two days and convicted every innocent spawner — DEV-P4-32. Two consequences worth carrying:
   `ps -ww` everywhere, and **a process-table probe must find its target by PID**, because the row
   that gets cut is precisely the row that no longer contains the name you would search for.
