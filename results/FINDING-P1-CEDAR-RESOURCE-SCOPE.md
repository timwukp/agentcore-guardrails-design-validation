# FINDING P1 — six instrument defects across seven live rounds, and a retracted inference about the first

<!-- provenance
{
  "status": "RESOLVED",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F1-19", "F1-24", "F1-25"],
  "amends": [],
  "note": "An instrument finding, not a document finding. It asserts nothing about the guardrails document and licenses no amendment to it; the measurements it unblocked are written up separately in FINDING-F1-GRAMMAR-PERMISSIVENESS.md, which carries its own provenance and its own replication debt. RESOLVED because all six defects are repaired AND the cases they blocked were subsequently measured in rounds 4-7 (2026-08-13 UTC) — a repair whose subject never ran again would be OBSERVATIONS_COMPLETE at best."
}
-->

**Date:** 2026-08-14 (third version; supersedes the two-defect version of the same day. §3 of the
first version is RETRACTED in place below rather than deleted)
**Run:** `r20260810T130945Z`, seven live rounds on EC2 `i-0f90ac6377bba523b`, `us-east-1`
**Cases affected:** F1-19, F1-24, F1-25 (INCONCLUSIVE in rounds 1-3, all arms) — and separately F5-5
**Status:** all six defects diagnosed and repaired; four service constraints established as
mechanism observations; **F1-24 and F1-25 measured in round 4 and replicated in rounds 5-7**;
F1-19 still not measured, now for a reason that is the service's rather than the instrument's
**Registers:** this is the traceable source for the deviation notes a future
`PREREGISTRATION.yaml` successor should carry. That file is sealed and is not edited here.

---

## 0. The shape of this document, and the one number that matters

Six defects, seven rounds, three of them wasted entirely. Every defect was in the *instrument*, and
every one of them presented as a service refusal — which is why they are written up here at length
instead of fixed quietly: the failure mode that cost the most was not any individual bug but the
repeated act of reading an accurate error message as an answer to the question I meant to ask.

The number that matters: **rounds 1, 2 and 3 produced nothing, round 4 measured two of the three
cases, and rounds 5-7 replicated them.** The three lost rounds are the cost of not having the
head-lint, the identity wait and the argument-level scans that now exist.

## 1. What happened, round by round

**Round 1 (2026-08-13).** Eight arms across three cases returned no measurement. Every one failed
with HTTP 400 `ValidationException`. Seven reported `unexpected token guardrails`; one — F1-24's
`split_when_only`, the only arm with no guardrails block — reported a wildcard-resource message.

| case | arms | verdict | the case's own reading |
|:--|:--|:--|:--|
| F1-19 | `A_no_threshold`, `A_control_with_threshold` | INCONCLUSIVE | "the control … did not reach a usable state; without it, 'rejected' is uninformative" |
| F1-24 | `mixed_both_forms`, `split_when_only`, `split_guardrails_only` | INCONCLUSIVE | "the split arms did not both reach a usable state … a rejection of the mixed policy is then attributable to an individually-invalid condition rather than to the mixing" |
| F1-25 | `pattern_like_on_path`, `pattern_regex_shaped_category`, `control_no_pattern` | INCONCLUSIVE | "the control … did not reach a usable state; a pattern arm's rejection is then uninformative" |

**Round 2 (2026-08-14), after the resource repair.** Still INCONCLUSIVE, still all arms. Seven
still `unexpected token guardrails`; `split_when_only` moved to
`AccessDeniedException: bedrock-agentcore:ManageAdminPolicy`.

**Round 3 (2026-08-14), after the union-member repair.** Still INCONCLUSIVE, still all eight arms,
now with a *new* message:

> unexpected token ':', expected name at line 1, column 30

Cause: a scope slot must be a **clause**, not an entity reference. `cedar.gateway_resource()`
returns `resource == AgentCore::Gateway::"<arn>"`, a full clause; `cedar.action_ref()` returns the
bare `AgentCore::Action::"grxecho___echo"`. The diagnostic probe that established the authorable
shape had written `f"action == {C.action_ref(...)}"` at its own call site, and when I lifted that
shape into the production `scope_for()` I dropped the `action == ` prefix. The parser then read
`AgentCore` as a scope variable name and stopped at the first `:`. Column 30 is exactly where the
prefix should have been.

That is three consecutive rounds lost to a malformed statement HEAD — a bare `resource` token, then
a type-form resource, then a prefix-less action. Three instances of one class, which is why the
repair is a head lint rather than a third correct string (§6).

**Round 4 (2026-08-13 UTC / late 2026-08-14 local), after the action-clause repair.** Every control
reached `ACTIVE`. **F1-24 and F1-25 were measured, and both returned FALSE.** F1-19's hand-written
half behaved exactly as predicted and its NL half died on an IAM denial (defect E, §4b).

**Rounds 5, 6 and 7.** Round 5 fixed the IAM denial and the generation reached `GENERATED`; round 6
regressed to `NOT_STARTED` on `ConflictException` (defect F, §4c); round 7 fixed that and replicated
round 5. F1-24 and F1-25 returned FALSE in all four rounds, 4 through 7.

| round | F1-19 | F1-24 | F1-25 | what it cost / bought |
|:--|:--|:--|:--|:--|
| 1 | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | lost — resource clause + union member |
| 2 | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | lost — union member still |
| 3 | INCONCLUSIVE | INCONCLUSIVE | INCONCLUSIVE | lost — action clause |
| 4 | INCONCLUSIVE (IAM) | **FALSE** | **FALSE** | first measurement |
| 5 | INCONCLUSIVE (service) | FALSE | FALSE | NL generation reached GENERATED |
| 6 | INCONCLUSIVE (name conflict) | FALSE | FALSE | lost B arm — undeletable name |
| 7 | INCONCLUSIVE (service) | FALSE | FALSE | B arm replicated |

In rounds 1-3 the pre-registered rule returned INCONCLUSIVE because the CONTROL failed alongside
the treatment arm, and the rule refuses to read a rejection whose control also rejected. **That
rule did its job three times, against three different defects, and it is the only reason none of
those rounds published a false FALSE.** Nothing in rounds 1-3 is a finding about the document. All
of it is findings about the instrument, and the instrument's own guard is what caught them.

Worth stating without hedging: had that guard been absent, round 1 would have published "the
guardrails-in-policy grammar rejects mixed conditions and pattern operators" — with eight
rejections as evidence, and the opposite of what round 4 measured.

## 2. Defect A — the resource clause (real, repaired in round 1)

`lib/cedar.py`'s `statement()` defaulted `resource` to the bare token `resource`, and
`f1_config/04_policy_grammar.py` was the only module in the repo that took the default — three
helper call sites plus four hand-assembled f-strings with the same bare head. The API refuses an
unconstrained resource outright:

> When parsing the policy statement, a wildcard resource was detected. To avoid unexpected
> behavior changes, please constrain the resource either to a specific `AgentCore::Gateway`
> resource or to the `AgentCore::Gateway` resource type.

A default that cannot ever produce a valid value is worse than a required parameter: it converts a
`TypeError` at a developer's desk into a 400 five minutes into a live round, after IAM
propagation, on an instance. `resource` is now required and keyword-only.

## 3. RETRACTED — "the grammar error was the wildcard defect wearing a mask"

**The first version of this document said this, and it was wrong.** Preserved verbatim so the
error is auditable rather than quietly overwritten:

> The grammar error was the wildcard defect wearing a more alarming mask. **A parser reports its
> first failure, not its only one**, and a semantic check on the resource evidently runs after the
> grammar stage — so the eight guardrails arms never reached the check that would have named the
> real problem.

It was supported by a correlation that is entirely real:

| observation set | resource clause | outcome |
|:--|:--|:--|
| accepted `when guardrails` statements (F5-4a ×6, F5-4b, F5-5) | constrained (`resource ==` a gateway ARN) | ACTIVE / created |
| rejected arms (F1-19, F1-24, F1-25) | unconstrained (bare `resource`) | 400 |

**Why a real correlation supported a false conclusion.** The two groups differ in the resource
clause. They also differ in something the table does not have a column for: the `definition` union
member. F5-4a/4b/5 send `definition={"policy": {...}}`; the F1 module sent
`definition={"cedar": {...}}`. Those two variables covary *perfectly* across the groups, so the
correlation is exactly as strong for either explanation, and no amount of re-reading it can
separate them. A comparison across groups that differ in two variables cannot attribute an effect
to one of them — only independent variation can, which is what §5's probe supplies and what round
1's diagnosis lacked.

The generalisable lesson survives the retraction, in a sharper form. The original was "an error
message is evidence about where a parser stopped, not an inventory of what was wrong with the
input" — true, and it is not what went wrong here. The message `unexpected token guardrails` was
**correct and complete for the request it answered**: under `definition.cedar` the body is parsed
as base Cedar, in which `guardrails` genuinely is an unexpected token. Nothing was masked. The
failure was reading a message as an answer to the question I meant to ask instead of the one I
actually sent.

## 4. Defect B — the `definition` union member (the actual cause of the token errors)

`CreatePolicy`'s `definition` is a union with two arms, and the arm decides which grammar parses
the body. The extended guardrails grammar — `when guardrails { … }`, `BedrockGuardrails::*`
providers, the `suppressOutput` effect — exists **only** under `definition.policy`.

Every accepted `when guardrails` policy in this account (F5-4a, F5-4b, F6, F2, F4) went through
the `policy` member. `f1_config/04_policy_grammar.py` was the only module in the repo sending
guardrails through `cedar`, which is precisely why the defect was invisible to every other case
and why no within-case comparison could have found it.

**This was already on record in-repo, three days before the round that rediscovered it.**
`f4_modes/00_syntax_probe.py`'s F4-0 calibration (2026-08-11,
`evidence/r20260810T130945Z/f4_modes/F4-0/calibration.json`) crossed seven statement variants
against both members and recorded `cedar.doc_syntax → unexpected token guardrails` alongside five
accepted `policy.*` cells. The F1 module was written without consulting it. **A fact recorded in
an evidence JSON that no test reads is a fact the next author pays for again**, which is why the
repair includes `lib/tests/test_definition_union_member.py` and not only the changed literal.

## 4a. Defect C — a scope slot is a clause, and one helper returned half of one

`cedar.gateway_resource()` and `cedar.action_ref()` looked like siblings and were not. One returns
`resource == AgentCore::Gateway::"<arn>"`; the other returns `AgentCore::Action::"grxecho___echo"`.
Two functions in the same module, named alike, at the same level of abstraction, returning values of
**different grammatical categories** — and nothing in either name or signature says so.

The repair is three parts, and only the first is the bug fix:

1. `cedar.action_eq()`, which returns the clause, so the caller does not assemble the operator.
2. `_scope_problems()` inside `check_statement()`: a head lint that reads the three scope slots and
   flags any slot that names an entity type with no operator in front of it. It catches all three of
   the round-1/2/3 head defects, including the ones that no longer exist.
3. `scope_for()` lints its own output and raises before returning, so a malformed head cannot reach
   a live call. Offline, at import, at the desk.

**Why the lint and not just the helper.** A correct helper prevents this defect; the lint prevents
the *class*. The evidence that the class is real is that three rounds died to three different
members of it, each with an accurate and unhelpful message from the same parser. `feedback_cryptic_error_is_missing_guard`.

## 4b. Defect E — a least-privilege policy derived from successes cannot grant a first success

Round 4's F1-19 B arm:

> AccessDeniedException: User: …/grx-runner-ec2/… is not authorized to perform:
> `bedrock-agentcore:StartPolicyGeneration` … because no identity-based policy allows the
> `bedrock-agentcore:StartPolicyGeneration` action

`runner/iam_policy.py` derives the runner's role from `measured_operations()` — the operation names
the **evidence tree records as having run**. F1-19's B arm had never completed, because it sat behind
defects A, B and C for three rounds, so no record existed and the derivation had no way to learn the
action. **The first round in which the A arms finally worked was necessarily the first round that
could surface it.**

This is a different hole from the `ManageResourceScopedPolicy` one already documented in that file.
That one was "an operation name cannot reveal an action the service checks under another name" — a
gap in the *mapping*. This one is a gap in the *premise*: a policy derived from observed successes
cannot authorise a call that has not yet had one, and no amount of care in the derivation closes it.
The bootstrap has to be broken by hand. Three mapping entries now exist
(`start_policy_generation` measured, the two reads inferred and marked so), and the reasoning is
written at the entry rather than here, where the next author will not be reading.

## 4c. Defect F — a deterministic name for an undeletable resource is a single-shot arm

Round 5 created generation `grx_f119_gen_r20260810T130945Z` and read it successfully. Round 6:

> ConflictException: Generation with the same name already exists

Every other name in this module belongs to a policy, and policies are deleted in the per-case
`finally`, so a run-id-derived name is free again next round. A policy generation has no
`DeletePolicyGeneration` in the service model — this module's own docstring calls it undeletable by
construction and treats it as named residue. So a deterministic name made the B arm **single-shot
per run id**, and this project adopts one run id, which makes it single-shot forever.

Two things make this worse than a retry bug, and both are the interesting part:

1. **It broke an arm that had just started working.** Round 5 was the first successful read in the
   case's history and round 6 was the last possible one. A defect that arrives *with* the fix is
   easy to attribute to the fix.
2. **Round 6's payload overwrote round 5's.** The successful read survived only in the
   append-numbered evidence records (`0021_start_policy_generation_ok.json` through
   `0023_list_policy_generation_assets_ok.json`). The results tree is last-write-wins; the evidence
   tree is not. That is the whole argument for having both, and it is the second time this run has
   been saved by it.

The name now carries a UTC-second suffix after the `grx_f119_gen_<run_id>_` prefix, so residue stays
attributable while each attempt is its own resource, and an offline test asserts the name is not
derived from the run id alone.

## 4d. Defect D — a repair announced before it was effective

Not an F1 defect; it blocked the round-4 deployment and belongs on the list because it was **caused
by the previous fix**.

`sync.py push` failed with `403 Forbidden` on `HeadObject` against a bucket whose policy plainly
grants the runner `s3:GetObject`. The hourly account-wide `AWS-AttachIAMToInstance` association had
replaced the instance profile with `AmazonSSMRoleForInstancesQuickSetup` (at 20:01:35Z), and
`ensure_instance_profile()` — the guard written for exactly this — detected it, called
`replace_iam_instance_profile_association`, printed the repair, and returned. That call is
**asynchronous**: it returns with the association in state `associating`, and IMDS keeps serving the
old role until the swap lands. The push then told the instance to fetch, with the credentials that
had just been replaced.

So the guard produced the identical symptom it was written to eliminate. It converted "the profile is
wrong" into "the profile is wrong for the next minute, and a line above says it was repaired", which
is a smaller window and a strictly more confusing failure. **A repair that is announced before it is
effective spends the operator's trust on a claim that is not yet true.**

`_await_instance_identity()` now blocks after any repair until the association reads `associated`
AND the instance's own `aws sts get-caller-identity` names the role — the control plane's word is
necessary and not sufficient, so the deciding assertion is the one made by the component that will
do the work. It raises rather than degrading: every caller of `_state()` is about to make the
instance touch S3.

## 5. How A and B were attributed: independent variation, not closer reading

`f1_config/diag_resource_form.py` crosses the union member × resource form × action scope × data
path — 17 cells, run live, every policy deleted in a `finally`, no verdict written and nothing
under `results/phase1/` touched. Results in `results/DIAG-P1-RESOURCE-FORM.json`. It establishes
four service constraints, each of which independently would have prevented these cases from being
measured in their round-1 shape:

1. **Union member.** Cells 1–6 and 10: `cedar` + every resource form + every data path →
   `unexpected token guardrails`. Cells 9, 14, 17: `policy` → ACTIVE.
2. **Output data paths are refused under an authorization effect.** Cells 7 and 8: "references
   'context.output' but the policy has an authorization effect. Use 'context.input.*' data
   paths". Independent of resource, action and member. Output-path guardrails are reachable only
   through the `suppressOutput` effect (F1-17's subject).
3. **The TYPE-form resource makes the statement an ADMIN policy.** Cells 11 and 16:
   `AccessDeniedException: bedrock-agentcore:ManageAdminPolicy`, which `grx-runner-ec2` does not
   hold. So `resource is AgentCore::Gateway` — the form §3.1 of the document under test writes —
   is not authorable by an ordinary caller in this account. Cell 13 adds that with a CONSTRAINED
   action it is refused outright: "a constrained action scope was encountered, please constrain
   the resource to a specific AgentCore::Gateway resource". **Action and resource scope are
   coupled and cannot be chosen independently.**
4. **Context attributes validate against every action the statement reaches.** Cell 12, with an
   unconstrained action: "argument `context.input.text` is not present in the context of action
   `AgentCore::Action::\"CallTool\"`". Cell 15: `context.input.amount` is absent from the echo
   action's context. So neither `action` nor the attribute set is free.

The one authorable shape left is `definition.policy` + `resource ==` a specific gateway ARN +
`action ==` a specific tool action + `context.input.*` paths. It reached ACTIVE three times — cell
14 deliberately replicating cell 9, because a positive control that runs once is an anecdote.

**F4-0 could not have supplied constraints 3 and 4**, and that is worth separating from the
process failure above. F4-0 recorded only *synchronous* acceptance (`accepted = bool(rec.ok)`, the
HTTP 202). Constraints 3 and 4 surface asynchronously, at terminal `CREATE_FAILED` — cell 12 was
accepted with a policy id and *then* failed. Polling every cell to a terminal state is what made
them visible, and it is a difference in probe design, not diligence.

## 6. The repair

**`lib/cedar.py`:** `resource` required and keyword-only; new `policy_definition()` /
`base_definition()` helpers so the union member is a named decision at each send site rather than
a two-character difference inside a dict literal.

**`f1_config/04_policy_grammar.py`:** sends `C.policy_definition(statement)`; every statement
carries one `Scope` object (specific gateway ARN + `grxecho___echo`) threaded through all seven
builders, hand-built and helper-built alike, so the arms still differ in exactly one property;
`GUARDRAIL_PATH` → `context.input.text`; `STD_CONDITION` → `context.input.text == "grx-value-that-is-never-equal"`.

**Registered deviation.** §6 of the first version of this document pre-registered that the data
path must **not** be "quietly switched" to `context.input.text`, because that would change what
the cases measure. The switch is made, and the register is honoured rather than evaded: the choice
the prediction imagined does not exist. It is switch-or-never-measure, not
switch-or-measure-the-stricter-thing, because constraint 2 is categorical for every
authorization-effect policy the service will accept. What the cases measure is unchanged in
substance — F1-19's threshold omission, F1-24's mixing, F1-25's pattern operators are each a
property of *both* the arm and its control, so the data path is not the variable in any of the
three. What is lost is generality: a TRUE is now evidence about input-path guardrails only. That
limitation is written into each payload's `what_true_does_not_prove` and pinned by an offline test
so it cannot be silently un-deviated later.

**Class fixes, not instance fixes.** `lib/tests/test_cedar_resource_scope.py` (8 tests) holds the
required-argument property, an AST scan proving no production `statement(...)` call omits
`resource=` (floor of 20 sites so a broken scan cannot pass vacuously), the absence of a bare
`action, resource)` head in the F1 module — which is what catches hand-assembled f-strings that no
call-graph check can see — and that every built statement carries the identical scope.
`lib/tests/test_definition_union_member.py` (5 tests) scans production for member-keyed
definition literals and requires every `cedar` send site to be allowlisted **with a written
reason**; it states plainly what it cannot see (a computed member, which is what the three
deliberate member-varying probes use, and which is by nature a module that has thought about it).

Same shape as `runner/tests/test_runner_policy.py`'s tagged-create scan, and the same lesson for
the third time: **an argument-level defect is structurally invisible to any check that enumerates
function or operation names.** The scan has to read arguments.

**The later repairs, in one place.** Defect C: `cedar.action_eq()` returns the clause,
`check_statement()` lints all three scope slots for a bare entity reference, and `scope_for()`
raises on its own malformed output (§4a). Defect E: three `bedrock-agentcore:*PolicyGeneration*`
entries in `runner/iam_policy.py`'s MAPPING, the first marked `measured` and the two reads marked
`inferred`, because the distinction between "the service told us" and "we reasoned" is the whole
value of that column (§4b). Defect F: a UTC-second suffix on the generation name plus a source-scan
test asserting the name is not derived from the run id alone (§4c). Defect D:
`_await_instance_identity()` in `runner/sync.py`, which blocks until the instance's own
`sts get-caller-identity` agrees with the control plane (§4d).

**And one repair that is only a test.** `DRY_RUN_SCOPE` — the object the `--dry-run` banner prints
so an operator can inspect the head before spending a live round — was hand-assembled from
`action_ref`, so it printed the exact malformed head the service rejects, directly above the line
`predict: control ACCEPTED`. Nothing read it, so nothing failed; it was a lie in the one place whose
entire job is to be read before the money is spent. It now routes through `scope_for()`, and a test
pins `DRY_RUN_SCOPE.action == SCOPE.action`. **A pre-flight check that builds its subject
differently from the flight is not a pre-flight check** — it is a second implementation that will
drift, and this one had.

## 7. F5-5, and what §4.2 of the document does not say

F5-5 also returned INCONCLUSIVE, and NOT for defect A, B or C — its statement was properly
scoped to a specific gateway ARN and a specific action, and it reached `CREATE_FAILED` with:

> provider `BedrockGuardrails::PromptAttack`: argument `context.output.text` is not present in
> the context of action `AgentCore::Action::"grxecho___echo"` … a provider's context field-path
> argument must be declared on every action the rule applies to.

Constraints 2 and 4 together explain it. Operationally this qualifies §4.2's tool-response
guardrail advice in a way the document does not: a reader following §4.2 against their own MCP
target can get `CREATE_FAILED` for a policy that is, by every syntactic measure, correct — and the
output-path form of it cannot be authored as a `forbid` at all.

Recorded as a **mechanism observation, not a verdict.** F5-5's sealed oracle is about indirect
prompt injection and nothing here bears on it.

## 8. What this finding does not establish

- Nothing about whether guardrails-in-policy **evaluates** correctly. Every observation here is
  `CreatePolicy` accepting or refusing a string; F4's truth table is where enforcement is
  measured.
- Nothing about the service's error-reporting order as a contract. §3's retraction removes the
  only claim that depended on it.
- **Nothing about F1-19/24/25's actual claims.** Two of the three are now measured, and this
  document is not where to read them. F1-24 and F1-25 came back FALSE in round 4 and again in rounds
  5, 6 and 7; F1-19 stays INCONCLUSIVE on a blocker that is the service's rather than the
  instrument's. All of that — the verdicts, the sealed rules they were read against, and the
  replication debt they still carry — is in `FINDING-F1-GRAMMAR-PERMISSIVENESS.md`. This document
  removed the obstacles; it is not the measurement, and citing it as one would be citing a repaired
  instrument as its own reading.
- Nothing about whether the four constraints in §5 are stable. They are 17 cells in one region on
  one date, with one replication of the positive control.
- Nothing about how many defects remain. Six were found by running, one per round for the first
  three rounds and three more in the rounds that finally worked. The honest read of that curve is
  not "we are done"; it is that this instrument's defect discovery rate was still roughly one per
  live round at the point the measurements landed, and the seventh round is the first that surfaced
  none.
