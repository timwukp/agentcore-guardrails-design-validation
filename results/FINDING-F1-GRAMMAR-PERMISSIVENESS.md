# FINDING F1-GRAMMAR — the guardrails-in-policy grammar accepts two constructs the document says it forbids

<!-- provenance
{
  "status": "READY_TO_AMEND",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F1-19", "F1-24", "F1-25"],
  "amends": ["S4.1"],
  "note": "Replicated: the day-2 round ran 2026-08-14T00:54:25Z-00:55:19Z UTC and reproduced both acceptances arm for arm (section 6.1), so the evidence now spans 2026-08-13 and 2026-08-14 UTC and the deferral recorded here until then is discharged. `amends` names S4.1 only: that is the sole section whose CLAIMS change. Section 3.1 receives an annotation and Appendix D a change-log entry, neither of which alters a claim -- F1-19 is INCONCLUSIVE and INCONCLUSIVE licenses no amendment. The instrument defects that cost rounds 1-3 are written up separately in FINDING-P1-CEDAR-RESOURCE-SCOPE.md, which is where the repair history lives and which asserts nothing about the document."
}
-->

**Date:** 2026-08-14 (written after round 7; measurements dated 2026-08-13 **and** 2026-08-14 UTC)
**Run:** `r20260810T130945Z`, EC2 `i-0f90ac6377bba523b`, `us-east-1`, engine `grx_pe_r20260810T130945Z-t6hqadrspf`
**Producer:** `f1_config/04_policy_grammar.py` (rounds 4-7 on day 1; round 8 on day 2 — §6.1)
**Verdicts:** F1-24 **FALSE**, F1-25 **FALSE**, F1-19 **INCONCLUSIVE**
**Document under test:** `agentcore_guardrails_best_practices_v1.2.md` — the claims at the
"Limitations of guardrails in policy" list (items 1 and 2) and the threshold-defaults paragraph
**Billable model calls:** 0. Every arm is a `CreatePolicy` against the validator; nothing was
evaluated and no model was invoked.

---

## 0. What was measured

Three cases, one instrument, one 32-minute window. Two of the three now have verdicts, and both
verdicts are **FALSE** — the service accepted a construct the document describes as unsupported:

| Case | Sealed claim | Verdict | The observation that decided it |
|---|---|---|---|
| F1-24 | a policy mixing `when {…}` with `when guardrails {…}` is rejected | **FALSE** | the mixed policy settled **ACTIVE** |
| F1-25 | the grammar rejects regex/pattern constructs in a guardrails condition | **FALSE** | `context.input.text like "*jailbreak*"` inside the guardrails block settled **ACTIVE** |
| F1-19 | hand-written Cedar without a threshold is rejected, while NL authoring supplies the documented defaults | **INCONCLUSIVE** | first half holds exactly as documented; the second half is refused by the authoring service itself |

Each accepted arm was created four times, in four separate live rounds:
**20:11:43Z, 20:33:28Z, 20:39:05Z and 20:43:25Z** for F1-24's mixed policy, and
**20:12:03Z, 20:33:51Z, 20:39:24Z and 20:43:44Z** for F1-25's `like` arm. Four for four, ACTIVE
every time. What that buys and what it does not is §6 — and it was not enough on its own: the
amendment waited for a **second UTC calendar day**, which arrived on 2026-08-14 at 00:54Z and
reproduced every arm (§6.1).

## 1. F1-24 — the mix is accepted

**Sealed rule, quoted from the payload:**

> TRUE iff the mixed policy is REJECTED_GRAMMAR while BOTH split policies — the SAME two condition
> strings, one per policy — are ACCEPTED. FALSE iff the mixed policy is ACCEPTED. Any other
> combination is not-measured: a split arm rejected means the condition itself was invalid and the
> mixed rejection is confounded.

The FALSE branch is a single condition, and it fired. The mixed statement — hand-assembled, because
`cedar.statement()` refuses to build it, the local guard being an encoding of the very rule under
test:

```
forbid (principal, action == AgentCore::Action::"grxecho___echo",
        resource == AgentCore::Gateway::"arn:…:<account>:gateway/grx-gw-…-zpkfmpwo9n")
when { context.input.text == "grx-value-that-is-never-equal" }
when guardrails {
    BedrockGuardrails::ContentFilter(["HATE"], [context.input.text])["HATE"].confidenceScore.greaterThan(decimal("0.2"))
};
```

HTTP 202, then terminal `ACTIVE`. No `statusReasons`, no findings, no warning of any kind. Both
split controls — the same two condition strings sent as two separate policies — also reached ACTIVE,
which is what makes the mixed acceptance readable as being *about the mixing* and not about either
condition being independently fine or independently broken.

**What FALSE means here, precisely.** It means the *authoring-time* claim is refuted: the service's
validator does not reject the mix. It does **not** mean the mix works. The document's sentence has
two clauses — "you cannot mix standard Cedar `when {…}` with `when guardrails {…}` — the guardrails
block replaces the standard condition" — and this run tests only the first. The second clause is an
**evaluation-time** claim, and every arm here is `LOG_ONLY` and never evaluated.

That distinction is the operationally important part, and it runs the opposite way from what a
"FALSE" usually implies. **If the second clause is true, then acceptance is worse than rejection.**
A reader writes both conditions, the service accepts the policy without comment, and the business
condition is silently discarded — a policy that looks like a conjunction and behaves like one of its
halves. A rejection would at least be a message. So this verdict does not weaken the document's
advice to split the conditions into two statements; if anything it strengthens the reason for it,
while removing the mechanism the document offers as the enforcement of that advice. **The advice is
right and the stated reason for trusting it is not there.**

`when { … }` beside `when guardrails { … }` is the one shape probed. `unless guardrails`, two
guardrails blocks, and an `unless`-mixed form are unprobed, and the payload says so.

## 2. F1-25 — a Cedar pattern operator is accepted inside a guardrails block

**Sealed rule:**

> TRUE iff EVERY probed pattern form is REJECTED_GRAMMAR while the pattern-free control is ACCEPTED.
> FALSE iff ANY probed form is ACCEPTED — the sealed FALSE branch is existential.

Two forms were probed, and they split:

**Form 1 — `like` glob on the data path: ACCEPTED (ACTIVE).**

```
when guardrails {
    BedrockGuardrails::ContentFilter(["HATE"], [context.input.text])["HATE"].confidenceScore.greaterThan(decimal("0.2"))
      && context.input.text like "*jailbreak*"
};
```

This is the form that decides the case. It is also the form a reader who knows standard Cedar
reaches for first, which is why it was pre-registered as the primary probe rather than as a
supplement.

**Form 2 — regex-shaped literal in the category slot: REJECTED, synchronously.**

> ValidationException: Invalid category 'HATE.*' for guardrail
> 'BedrockGuardrails::ContentFilter'. Valid categories: VIOLENCE, HATE, SEXUAL, MISCONDUCT, INSULTS.

The payload's pre-registered reading of this rejection declines to over-claim it: the message is
consistent with "no pattern matching" *and* with "the category must be one of five literals", and
those are the same operational fact told as two different sentences. This form alone could not have
carried the case in either direction — which is exactly why two forms were probed.

**Control — the same statement with no pattern: ACCEPTED (ACTIVE).** Required by the rule, not a
courtesy.

**What FALSE means here, precisely.** One pattern-matching construct is accepted by the validator.
Whether `like` is *evaluated* — whether the glob actually filters anything at request time — is
untested and is the more consequential question. The document's own recommendation elsewhere, that
regex-style checks belong in a Gateway REQUEST Lambda interceptor rather than in Cedar, is
untouched by this and remains the right advice: an accepted-but-unevaluated `like` is precisely the
trap that recommendation avoids. What is refuted is the flat "no regex or pattern matching" as a
statement about what you can author.

The sealed FALSE branch being existential means one accepted form settles it, and it also means a
TRUE here would never have been an exhaustion proof. Unprobed: `like` inside `unless guardrails`, a
pattern in the path list, a pattern against the aggregation.

## 3. F1-19 — one half confirms the document; the other half the service refuses to answer

**Sealed rule (abridged):** TRUE iff *both* (1) the hand-written no-threshold arm is
REJECTED_GRAMMAR while its explicit-threshold control is ACCEPTED, **and** (2) the Cedar generated
by `StartPolicyGeneration` carries exactly the documented defaults. And, decisively for this run:
**"A generation that cannot be driven to a terminal, readable state is NOT-MEASURED — a missing half
is not a refutation."**

**Half 1 behaves exactly as the document says.** The hand-written condition with no comparator and
no threshold reached `CREATE_FAILED`:

> for policy `grx_f119_omit_…`, unexpected type: expected Bool but saw
> `{HATE: {confidenceScore: decimal,}, INSULTS: {…}, MISCONDUCT: {…}, SEXUAL: {…}, VIOLENCE: {…}}`
> at line 3, column 5

That is a better error than the claim required. It does not merely refuse; it names the type the
bare guardrail call returns — a per-category record of confidence scores — and thereby explains
*why* a threshold is structurally mandatory rather than stylistically expected: the expression's
type is a record, the condition slot wants a `Bool`, and nothing in the grammar bridges the two
implicitly. The same statement with `.greaterThan(decimal("0.2"))` reached ACTIVE. So the
document's "**you MUST provide the threshold value explicitly — there is no automatic default**" is
confirmed for hand-written policies, and the confirmation is mechanistic, not just behavioural.

**Half 2 cannot be read, and the reason belongs to the service.** `StartPolicyGeneration` accepted
the natural-language prompt and settled at terminal `GENERATED` — success, by the generation's own
alphabet — having emitted **zero statements**. `ListPolicyGenerationAssets` returned two assets, and
both carried the same per-fragment finding:

> `{"type": "INVALID", "description": "Non-translatable: cannot be expressed in Dogwood"}`

for the fragments "Block any tool call whose input attempts a prompt attack." and "Block any tool
call whose output contains hate speech." Two of two fragments, both guardrail intents, both refused.

So there is no generated threshold to compare against `0.2 / 0.4 / 0.2`, and per the sealed rule
that is NOT-MEASURED. **The verdict is INCONCLUSIVE and stays there.** A missing half is not a
refutation; the document is not wrong about the NL defaults on this evidence, it is untested about
them.

**But the refusal is itself an observation, and a load-bearing one.** Recorded as a **mechanism
observation, not a verdict**: on this date, in this region, the natural-language authoring service
declined to express *guardrail* intents at all — the terminal state was `GENERATED` rather than any
failure state, and the refusal was visible only in the per-asset findings. Two consequences worth
writing down:

1. **Operationally.** A reader who follows the document's threshold guidance — hand-written Cedar
   requires explicit thresholds, the defaults come from the authoring service — may find the
   authoring path unavailable for exactly the intents that would have supplied those defaults. On
   this evidence the defaults paragraph describes a path this account could not walk. `n=1` prompt,
   phrased to name no number; that is thin and is not offered as more.
2. **Methodologically.** A terminal state named `GENERATED` with an empty statement list is a
   success by every field a caller is likely to check. The producer originally reported this as "the
   generation produced no BedrockGuardrails call" — *our inference about an absence*. The service's
   own words were sitting one API call away in the asset findings. **An absence and a documented
   refusal are different observations**, and only the second one attributes the failure. The
   producer now reads `findings` alongside every asset and, when the service declines, substitutes
   the service's sentence for ours and sets `service_declined_to_translate`. The `type` string is
   recorded verbatim: normalising an alphabet seen once invents a taxonomy.

## 4. Why the controls are the finding underneath the finding

In rounds 1, 2 and 3 the arms that are now ACCEPTED were rejected — three times, with three
accurate `ValidationException`s that had nothing to do with the claims under test (a bare resource
token, the wrong `definition` union member, a bare action reference; all in
`FINDING-P1-CEDAR-RESOURCE-SCOPE.md`). For F1-24 and F1-25 the sealed rules require the *controls*
to be ACCEPTED before any rejection may be read as evidence, and in all three rounds the controls
were rejected too.

Both cases therefore returned INCONCLUSIVE rather than TRUE.

**A rule written before the data prevented publishing the exact opposite of what was later
measured — three times.** Not "a possibly-wrong TRUE": the specific TRUE those rounds would have
produced is the negation of rounds 4-7. The rule cost three rounds of latency and bought the
correct sign on two verdicts. That is the single most valuable thing in this run's methodology, and
it is worth stating that the temptation each round was real — the rejections were exactly what the
document predicted, and a rejection that confirms the doc feels like a result rather than a bug.

## 5. Instrument and discipline, in brief

- Arms predicted REJECTED are **hand-assembled**, bypassing `cedar.statement()` and
  `cedar.guardrail_condition()`, whose guards encode the rules under test; every arm predicted
  ACCEPTED is helper-built and passed `check_statement()` before a call was spent.
  `bypass_partition_problems()` aborts the run if that partition is violated. A sacrificial subject
  must be sacrificial **in the property under test**, not merely disposable.
- Every `CreatePolicy` sends `validationMode=IGNORE_ALL_FINDINGS`: a grammar probe asks whether the
  body parses, and an "Overly Permissive" finding is a semantic judgement about a body that already
  parsed. A failure carrying finding vocabulary is scored `VALIDATION_FINDING`, never as a
  rejection; an unmatched failure is `UNCLASSIFIED`, never TRUE.
- Every arm is `enforcementMode=LOG_ONLY`. Grammar acceptance is a property of the body and the
  validator; a transiently-ACTIVE `forbid` on the shared engine would change the live ENFORCE
  gateway's deny behaviour for the seconds it exists.
- Every arm polls to a **terminal** status. Three of the four constraints that shaped this
  instrument are invisible to a probe that reads only the synchronous 202 — F1-24's mixed policy
  returns 202 in both worlds.
- Every policy is deleted in a `finally`, and residue is judged against the `state.json` ledger
  rather than a list of intentions. `survivors_in_ledger: []` for all three cases.
- All arms use `context.input.text`. Not a choice: a policy with an authorization effect that
  references `context.output.*` is refused outright ("Use 'context.input.*' data paths"), so the
  input path is the only one on which these cases were measurable at all. Output-path guardrails go
  through `suppressOutput`, which is F1-17's subject. This is a **registered deviation**, traced in
  §6 of the P1 finding, and it is the main limit on how far these verdicts generalise.

## 6. Replication debt — why this was OBSERVATIONS_COMPLETE, and what discharged it

**§6 below is preserved exactly as it was written before the day-2 run, including the target it set.
That is the point of writing the target down first: the run cannot be fitted to a prediction the
prediction can no longer be edited. The outcome is §6.1, appended after it.**

At the time of writing, every evidence record for all three cases fell on **2026-08-13 UTC**, between 14:52Z and 20:44Z.
The amendment gate requires at least two separate UTC calendar days of case-scoped evidence, and
that rule is not satisfied by four calls thirty-two minutes apart.

The distinction matters and is not bureaucratic. Four acceptances in one window establish that the
acceptance is **not a transient** — not a flapping validator, not one unlucky request. They cannot
establish that it is not a **deployment**: a validator build that reached `us-east-1` that afternoon
and rolls back tomorrow produces exactly this data. Only a different date separates those two
worlds, which is the reason the rule is written in calendar days rather than in call counts.

**The day-2 run must reproduce, on 2026-08-14 UTC or later:** F1-24's mixed policy ACTIVE with both
splits ACTIVE; F1-25's `like_on_path` ACTIVE with the control ACTIVE and the regex-shaped category
rejected. Anything else is not a tidier result — it is a **date-dependent validator**, which is a
more interesting finding than either verdict here and an `AWS-BEHAVIOR-CHANGES.md` entry.

F1-19 needs no such run for its verdict; INCONCLUSIVE licenses no amendment, and a second day of
`Non-translatable` would strengthen the mechanism observation without converting it into one.

**The amendment, pre-registered here so the day-2 run has a target it cannot be fitted to.** If the
replication holds, the two limitation items should be rewritten to separate authoring from
evaluation — item (1) from "no regex or pattern matching" to a statement that the validator accepts
Cedar's `like` inside a guardrails block while the guardrail *functions* score rather than match,
with the evaluation-time behaviour of an accepted `like` explicitly marked unverified; item (2) from
"you cannot mix" to "the validator accepts the mix without warning, and the guardrails block is
documented to replace the standard condition — so split the conditions into two statements, because
a mixed policy that is accepted is not a policy that works." The threshold paragraph gains the
service's own type error as its justification, and a note that the natural-language authoring path
declined guardrail intents in this account on 2026-08-13. Nothing else in the document is licensed
by these three cases, and the untested clauses are to be marked untested rather than quietly
inheriting the confidence of the tested ones.

### 6.1 The day-2 run: the replication holds

Round 8 ran on **2026-08-14 UTC, 00:54:25Z–00:55:19Z**, on the same instance, in the same Region,
against the same engine, with the same `boto3`/`botocore` 1.43.67 and the same
`validationMode=IGNORE_ALL_FINDINGS` — the comparison is like for like, and the sameness is read out
of both days' `analysis.json`, not assumed. Every arm reproduced the day-1 outcome:

| Case | Arm | Day 1 (2026-08-13) | Day 2 (2026-08-14) | Record |
|---|---|---|---|---|
| F1-24 | `mixed_both_forms` (hand) | ACCEPTED, terminal ACTIVE | **ACCEPTED, terminal ACTIVE** | `0034_create_policy_ok.json`, 00:54:46Z |
| F1-24 | `split_when_only` (control) | ACCEPTED, ACTIVE | **ACCEPTED, ACTIVE** | `0035_…`, 00:54:52Z |
| F1-24 | `split_guardrails_only` (control) | ACCEPTED, ACTIVE | **ACCEPTED, ACTIVE** | `0036_…`, 00:54:59Z |
| F1-25 | `pattern_like_on_path` (hand) | ACCEPTED, terminal ACTIVE | **ACCEPTED, terminal ACTIVE** | `0030_create_policy_ok.json`, 00:55:05Z |
| F1-25 | `pattern_regex_shaped_category` | REJECTED_GRAMMAR (`ValidationException`, HTTP 400) | **REJECTED_GRAMMAR (`ValidationException`, HTTP 400)** | `0031_create_policy_err.json`, 00:55:12Z |
| F1-25 | `control_no_pattern` | ACCEPTED, ACTIVE | **ACCEPTED, ACTIVE** | `0032_…`, 00:55:12Z |
| F1-19 | `A_no_threshold` | REJECTED_GRAMMAR, `CREATE_FAILED`, "expected Bool but saw {HATE: {confidenceScore: decimal,}…}" | **same message, same status** | `0041_…`, 00:54:25Z |
| F1-19 | `A_control_with_threshold` | ACCEPTED, ACTIVE | **ACCEPTED, ACTIVE** | `0042_…`, 00:54:29Z |
| F1-19 | `B_nl_authoring` | `GENERATED`, 0 statements, both fragments `Non-translatable: cannot be expressed in Dogwood` | **`GENERATED`, 0 statements, same two INVALID findings** | `0043`–`0045`, 00:54:35Z–00:54:46Z |

So the day-2 target set above is met exactly, and the alternative it was written to catch — a
validator build that reached `us-east-1` on 2026-08-13 and rolled back — is excluded. The
acceptances are **not date-dependent**, no `AWS-BEHAVIOR-CHANGES.md` entry is owed, and the status
moves to `READY_TO_AMEND` with `amends: ["S4.1"]`. What replication does **not** buy is anything
about evaluation: two days of an accepted string are still two days of the validator accepting a
string (§7 is unchanged, and every "untested" mark in the amendment stays).

Five deliberate residues of how this was recorded, so a reader is not misled by the file layout:

1. **F1-19 stays INCONCLUSIVE.** A second day of `Non-translatable` strengthens the mechanism
   observation and converts nothing. §3.1 of the document gains an annotation; its claims are
   untouched, which is why `amends` names only S4.1.
2. **The per-case `analysis.json`, `summary.json` and `environment.json` are day-2's.** The producer
   rewrites those three aggregates in place each run. Day 1's copies are not lost — they are in S3
   under `out/20260813T204454Z/`, and the day-1 figures quoted throughout §§0–5 were taken from them
   before the day-2 run — but the aggregate now in the tree describes round 8, and the table above is
   how the two are compared.
3. **The raw per-call records of both days coexist.** Day 1 is the lower-numbered files
   (F1-24 `0001`–`0033`), day 2 the higher (`0034`–`0039`), and the gate derives its two calendar
   days from their `t_start_utc` fields rather than from any sentence here.
4. **`results/phase1/F1-{19,24,25}.json` now carry day-2's policy ids and request ids**, same
   verdicts. A verdict file is the current run's record, not an archive; the archive is `evidence/`.
5. **Four-for-four became five-for-five for F1-24's mixed arm** (§0's four day-1 acceptances plus
   this one), and the same for F1-25's `like` arm. The count is not the argument — the second
   calendar day is.

## 7. What this finding does not establish

- **Nothing about evaluation.** Every observation is the validator accepting or refusing a string.
  Whether a mixed policy's standard condition is honoured, and whether an accepted `like` filters
  anything, are unmeasured — and both are the questions a reader actually has. F3/F4 are where
  evaluation is measured, and neither covers these two shapes.
- **Nothing about output-path guardrails.** See §5's last bullet. A `forbid` cannot reference
  `context.output.*` at all.
- **No exhaustion.** F1-25 probes two of many pattern forms; F1-24 probes one of several mixing
  shapes.
- **One region, one account, one date, one policy engine, one gateway, one tool action, `LOG_ONLY`
  throughout.** The `like` acceptance in particular is an undocumented behaviour, which is the class
  of behaviour most likely to change without notice — and per the payload's own expiry note, a later
  grammar that rejects it is both a behaviour-change entry and a falsification of this FALSE from
  that date forward.
- **Nothing about F1-19's sealed claim.** Half of it is confirmed mechanistically and half is
  unanswerable in this account; the case is INCONCLUSIVE and no amendment may cite it as a verdict.
- **Nothing about the six instrument defects.** They are the other document's subject, and a
  repaired instrument is not evidence for its own readings.
