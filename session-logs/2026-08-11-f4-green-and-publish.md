# Session log — 2026-08-11 (evening): F4 to green, project published

Continuation of `2026-08-11-f4-prep.md`. Object under test throughout:
`~/Downloads/agentcore_guardrails_best_practices_v1.2.md`.

## What happened, in order

1. **Narrow Cedar permit rejected on three counts** (CreatePolicy → CREATE_FAILED):
   unscoped `action` must type-check against every action in the schema; `input.amount`
   is optional and needs `context.input has amount`; `number` params are Cedar `decimal`,
   which has no `<` — use `.lessThan(decimal("500.0"))`. Fixed in `build_policies`,
   action id resolved from the ledger (`gateway-target/main` → `cedar_action_ids`), not
   hardcoded. Guard added: refuse to start if the ledger carries no `___echo` action id.
2. **Policy leak on failed create**: `stage_policy_ids[key] = _create_stage_policy(...)`
   loses the id when the settle check raises → teardown missed it. The function now
   registers into the caller's dict *before* anything that can raise. Leaked
   CREATE_FAILED policy deleted; ledger cleaned; baseline verified ACTIVE and alone.
3. **Bare tool name silently measured nothing**: sending `echo` returns HTTP 200 +
   JSON-RPC -32602 "Unknown tool: echo" — not a denial, not a transport error. All 8
   cells "completed" with n_usable=0. `_one_call` now takes the full MCP name
   (`grxecho___echo`), threaded from the same ledger value the narrow permit scopes to.
   Two rounds of stale checkpoints quarantined under `results/checkpoints/_stale_20260811_*`.
4. **Denials arrive as JSON-RPC error -32002**, not `result.isError` +
   AuthorizeActionException: `lib/mcp.classify` now recognises both wire shapes as
   `policy_denied`. (This is also F4-6's refutation evidence: no 403, and only the
   forbid-path message names the policy id.)
5. **Unscoped guardrail denies everything at runtime** ("guardrail policy could not be
   evaluated - missing an attribute") even though IGNORE_ALL_FINDINGS let it create —
   same root cause as (1), surfacing at runtime. Guardrail statement now action-scoped.
6. **Integral JSON numbers break decimal binding**: `amount: 100` → "Parameter format
   error: one or more numeric parameters must include a decimal point". Args now `100.0`
   / `4242.0`.
7. **Smoke GREEN**: `--n 3` rc=0, all 8 cells, F4-1..F4-5 TRUE, F4-6 FALSE (the
   pre-registered expected refutation). n=3 does not clear the amendment bar — full run
   needs n=120/cell.
8. **Published**: repo `timwukp/agentcore-guardrails-design-validation` (private, was
   empty). Git Data API flow (no `git push`), 409-on-empty-repo handled, 376 files,
   every blob SHA verified against `git hash-object`, remote tree re-verified
   blob-by-blob. Redaction: gate PASSED (315 files) + separate scan of
   `.jsonl/.log/.sha256` (all matches synthetic/AWS-published examples) + direct scan
   for the live account id (0 hits). `evidence/` stays local by written policy.
   **PR #1**: https://github.com/timwukp/agentcore-guardrails-design-validation/pull/1

## Amendment material harvested today (for the v1.3 pass)

- L141 is wrong on both halves at the wire: denial is HTTP 200 + JSON-RPC -32002, and
  only policy-evaluation denials name the policy id (guardrail-evaluation and
  parameter-format denials do not).
- Config-surface facts the document does not state: per-action context schemas derived
  from tool input schemas; optional-attribute access needs `has`; MCP `number` →
  Cedar `decimal`; decimal needs comparator methods; **request-side literals must be
  spelled with a decimal point or the policy errors on every call**; guardrail policies
  fail closed on unevaluable attributes; IGNORE_ALL_FINDINGS defers these failures from
  create-time to per-request runtime.

## Open items

- Full F4 run at n=120/cell, then Phase 4: F2 determinism (4 arms × n=300) +
  gateway-side F3 + F3-10 + F7.
- PR #1 review/merge is the user's call.
- The document under test itself is not in the repo (lives at ~/Downloads); decide
  whether it should ride a follow-up PR.
