# Session log — 2026-08-11 (late): F2-1 green, and the span probe that reordered Phase 4

Continuation of `2026-08-11-f4-green-and-publish.md`. Object under test throughout:
`~/Downloads/agentcore_guardrails_best_practices_v1.2.md`.

## What happened, in order

1. **Wrote `f2_determinism/02_policy_determinism.py` for F2-1** (pure-Cedar determinism),
   modelled on `f4_modes/01_truth_table.py` rather than on `f2_determinism/01_repeat.py`:
   F2-1 lives on the gateway/MCP path, not on ApplyGuardrail, so F2-5's `P.run_arms` /
   `R.ArmSpec` machinery is the wrong instrument. Every axis driver, terminal-state
   definition and blocking assertion is **imported** from F4 under a module-level name
   constant (`F4_MODULE_NAME`), because two definitions of "the mode landed" or "the testbed
   is intact" can disagree, and then which one ran decides whether a broken shared testbed
   gets reported.

2. **Design decisions worth keeping.** One configuration for all arms (engine `ENFORCE`,
   baseline permit `LOG_ONLY`, F2's narrow permit `ACTIVE`), applied once and never switched:
   F2-1 asks whether an unchanged configuration returns an unchanged answer, so a
   reconfiguration mid-run would be an event that could explain a flip. Arms differ in **one
   number**. A flip is defined **per arm against that arm's own modal decision** — pooling the
   arms would report the experiment's independent variable as non-determinism, and comparing
   against the *expected* decision would conflate "the arm went the wrong way" with "the arm
   was inconsistent".

3. **The vacuity trap, and the four guards that close it.** Determinism is the easiest claim
   in this project to confirm by accident: an inert policy, a non-enforcing engine, or a
   wrong tool name each produce a perfectly constant column and would publish TRUE. So
   `boundary_below` (499.9) must be **allowed**, `boundary_at` (500.0) must be **denied**, the
   two must reach **opposite** modal decisions, and no trial may be unclassified. Any
   violation is INCONCLUSIVE, never a verdict.

4. **Smoke green, then full green.** `--n 3` rc=0. Full run: `boundary_below` 300/300
   allowed, `boundary_at` 300/300 policy_denied, `far_outside` (4242.0, n=30) 30/30 denied.
   **630/630 usable, 0 flips, 0 failures, 0 unclassified.** Verdict **TRUE**, one-sided
   flip-rate ceiling **0.00474**. Testbed restored; 15/15 blocking checks PASS.

5. **A config-surface fact from the unscored probe.** The scored arms use one fractional
   digit because whether the engine binds Cedar's full four-digit `decimal` precision was
   unmeasured, and a wrong guess would have cost the whole run for a reason unrelated to
   determinism. Four unscored calls at `amount=499.9999` answered it: **four-fractional-digit
   request literals DO bind** (allowed). Recorded in the payload, excluded from `adverse` and
   from n, because four calls of a different request shape are not among the "identical
   calls" F2-1's oracle counts.

6. **The span shape probe, and what it cost.** `f7_observability/00_span_shape_probe.py`
   scores nothing and writes no phase-1 record. It reads 60 real spans for our gateway from
   `aws/spans` — traffic the F4 run already produced through guardrail-bearing policies in
   ENFORCE — so it spends no text units and can run beside a live experiment. **Result: 58
   distinct attribute paths, zero matches for `score` / `confidence` / `threshold` /
   `guardrail`.** The approved plan's predicted `aws.agentcore.policy.guardrails.<category>
   .scores` is **absent**. Registered as **DEV-P4-01**.

7. **The redaction gate caught the probe, twice, and both catches were real.** First run:
   **5 findings** — spans carry the account id and the full gateway ARN in three separate
   attributes. Routed every write through a masking writer; the gate then reported **1**,
   because `redact.mask` handles the account field of an ARN and, by explicit design, nothing
   else (its own comment says a bare 12-digit substitution would corrupt the PII corpus rows
   authored *as* 12-digit account fixtures — correct, and not broadened). Telemetry publishes
   a shape nothing else in this project produced: `attributes.aws.account.id` standing alone,
   outside any ARN. Fixed in the probe by replacing **one known literal** — the account read
   from STS moments earlier — so there is no pattern to over-match. Gate now **rc=0, 336
   files**, and 0 occurrences of the account id. The 5→1→0 sequence is the mutation check.

## The finding that changes the plan

Four sealed cases name the same instrument in their methods, and it does not exist:

| Case | Sealed method, verbatim |
|:--|:--|
| F2-2 | "harvest per-trial ConfidenceScore" |
| F2-3 | "stratify F2-2 trials **by observed score**" |
| F2-4 | "tau inside vs outside **observed support**" |
| F1-18 | "**harvest scores** from F2/F3 runs" vs the lattice `{0,.2,.4,.6,.8,1.0}` |

Two independent measurements say no numeric score is published: F2-5 on the ApplyGuardrail
response (four-value enums only) and this probe on the span path (nothing score-shaped at
all). **The assumption came from the document under test** — which asserts the six-value
lattice — and was carried into our own method sections without a check. That is a provenance
defect in the plan, not a sample-size error.

**Ordering consequence: F7 is upstream of F2-2/F2-3/F2-4 and of F3-10**, all four of which
were scheduled before it. F7-5 (tracing off → spans absent) is what makes any span-derived
reading non-vacuous.

## Amendment material harvested (for the v1.3 pass)

- **§3.1's determinism contrast did not appear.** F2-5 FALSE (guardrail showed no variation,
  ceiling 0.00994) and F2-1 TRUE (policy showed none, ceiling 0.00474). The document's
  claimed distinction between non-deterministic guardrails and deterministic policies is not
  observable on either published surface. Needs its own finding doc before amending.
- **The six-value confidence lattice is not exposed anywhere.** Not on ApplyGuardrail (a
  four-value enum) and not in telemetry (absent). F1-18 is therefore not measurable on either
  surface, which is a finding about the document rather than a case to skip.
- ~~**F7-4's oracle wording anticipates the wrong span name.**~~ **RETRACTED, same day.**
  `AgentCore.Policy.AuthorizeAction` spans **do** exist — 246 over 48 h, paired 1:1 with
  `InvokeTool`, 27 of them already inside the probe's own 60-row sample. The retracted claim
  was written from the single sample span the probe serialises (an InvokeTool row); the probe
  tallies leaf **paths** and never tallied span `name`, so no assertion covered the sentence.
  Re-measured at 120 min × 60, 120 min × 500 and 48 h × 500 — present in all three. The
  document is correct on this point and F7-4 yields no amendment material.
- **Four-fractional-digit request literals bind**, while integral literals are refused — the
  second half was already known from F4, the first is new.
- Spans corroborate F4-6 from an independent channel: `jsonrpc.error.code = -32002` sits
  beside `authorization_decision = DENY` with `status.code = ERROR` and no 403 anywhere.

## Instruments gained for later phases

- **F6** — spans publish `latency_ms`, `overhead_latency_ms` and `execute_tool_latency_ms`
  **per request, server-side**, which measures policy overhead without the client's own
  network variance in the number. Better than the planned client-side timing; register as its
  own instrument change when F6 is written.
- **F3-10** — spans carry `aws.request.id` per row, so the *decision* is joinable per
  request; the *score* §7.1's precision calculation needs has no left-hand side. FALSE
  direction indicated, deliberately **not scored** from the probe.
- **F4/LOG_ONLY** — `log_only_matched_policies[]` and
  `log_only_decision_flipping_policies[]` exist as first-class attributes.

## Gates re-run after everything above

- `verify_prereg.py` — **rc=0**, seal `a2136a9d…` intact, 189 assertions.
- `lib/tests/` — **672 passed, 2 skipped**, including the static module-name-collision test
  both new by-path loaders had to satisfy.
- `check_redaction.py` — **rc=0**, 336 files scanned (non-zero count verified).

## Open items

- **F7-1..F7-7 next** — `f7_observability/` holds only the probe. `infra/07_traces.py`
  already provides `query_spans`, `wait_for_span`, `traces_delivery_live` and
  `SPANS_LOG_GROUP`, and documents F7-5's mutation (`DeleteDelivery`/`CreateDelivery`, which
  leaves the gateway config byte-identical).
- Then F2-2/F2-3/F2-4 by τ-sweep, F3-10, F6, F5, and the singletons F8-1 / F1-18-as-amendment.
- F3-11 is hard-gated on calendar time: +7d = **2026-08-18**, +30d = **2026-09-10**.
- F5-7a day-2 replication still open. F4-6's refutation still needs a FINDING doc plus day-2
  replication before READY_TO_AMEND; F2-1 likewise needs a second calendar day.
- PR #1 review/merge is the user's call. Nothing from this session is pushed yet.
