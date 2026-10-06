# F10-1 measurement design — input block avoids the model charge, output block does not

Status: **measured 2026-10-05: FALSE. The input-blocked arm was billed nothing, and so was the output-blocked arm.**
The sections below the title are the 2026-09-28 design. The execution log at the end records where the
pre-flight refuted it and what replaced it. Written 2026-09-28. The user
authorized all three steps in the last section on 2026-09-29. Progress is in "Execution log" at the end.

## The sealed case, verbatim (`claims/triage_rules.py:460`)

- claim: "Input block avoids model inference charge; output block does not" (class S)
- oracle: "TRUE if a Cost-Explorer/tagged delta shows zero inference charge for input-blocked requests
  and full charge for output-blocked ones; FALSE if either differs"
- method: "n paired requests per arm, cost attributed by resource tag"

The method is sealed, so the design follows it: attribution is by **resource tag**, not by guessing
which part of a daily aggregate belongs to which arm.

## How the tag method answers obstacle 3

`results/CENSUS-NOT-MEASURED.md` left three obstacles. The first (a ~24 h Cost Explorer lag) is only a
wait. The second (the runner role could not call `ce:GetCostAndUsage`) goes away because the runner
instance is gone and the read would run from the MacBook. The third was the real one: in an account that
runs other workloads, can a daily Cost Explorer aggregate separate an input-blocked request's charge from
an output-blocked one's?

A bare on-demand `Converse` call carries no resource, so no tag can reach its line item. That is why
`COST.md` found the stated tag method could only ever return $0.00. An **application inference
profile** is a taggable resource, and Bedrock is understood to report its usage under that profile's
tags. **That sentence is not yet verified.** The documentation lookup failed on 2026-09-28 (no network
from the docs tool), and the output-blocked arm below is the measurement that would prove or refute it.
So:

- create two profiles over the same foundation model, tagged `grx-f10-1-arm=input-blocked` and
  `grx-f10-1-arm=output-blocked`, and nothing else in the account uses either profile;
- activate `grx-f10-1-arm` as a cost allocation tag **before** any request. Activation applies only to
  usage after it, and can take up to 24 h to take effect;
- read Cost Explorer grouped by `TAG:grx-f10-1-arm` and by `USAGE_TYPE`, over the days the requests
  ran. Filter on the tag only, and match model usage by usage-type pattern (`*NovaMicro-input-tokens`,
  `*NovaMicro-output-tokens`), not by one exact name. The `us.` profile routes across us-east-1,
  us-east-2 and us-west-2, and the usage-type prefix (`USE1-`) names the region.
  A SERVICE filter is not needed. It was also briefly misjudged here. On 2026-09-29 this section said
  model inference bills under `Amazon Bedrock Service`, because September read $4,986.57 there and $0
  under `Amazon Bedrock`. That was wrong. Grouping by usage type (2026-09-30) shows
  `Amazon Bedrock Service` holds the Anthropic models, while Nova Micro bills under `Amazon Bedrock`
  (`USE1-NovaMicro-input-tokens` $0.0069 and `-output-tokens` $0.0206 in August 2026, matching
  `cost_model.yaml`). September's $0 there only means nothing called Nova in September.

Each arm then has its own line items, whatever else the account does that day.

## The two arms: one guardrail, one model, one manipulated variable

- guardrail: `words` (`bb8eo7hr35og`), whose list is `moonquake`, `zorbify`, `quaxlinate`
  (`lib/phase1.configured_words()`). It is used read-only and is not modified. Word-policy units bill
  at $0.0000 (`COST.md`), so the guardrail's own charge cannot be confused with the model's.
- model: `us.amazon.nova-micro-v1:0`, the model this repo already prices (`cost_model.yaml:852-864`).
- **input-blocked:** the user turn contains `zorbify`. The guardrail should intervene before the model
  runs, and `usage` should report zero model tokens.
- **output-blocked:** the user turn is clean and asks the model to repeat a listed word, which the
  output check should catch. Before any counted request, one pre-flight call must show the model actually
  emits the word. If it refuses or misspells it, the arm is not output-blocked and the run stops.
- n = 20 per arm, interleaved. For every request the script records `stopReason`,
  `trace.guardrail`, and `usage.{inputTokens,outputTokens}`, so each request's own record says which
  arm it really landed in.

## What decides the verdict

- **Zero, but proven reachable.** The input-blocked profile must show $0 of model usage types
  (`*-input-tokens`, `*-output-tokens`). A $0 alone could also mean "the tag never flowed". The
  output-blocked profile is the positive control. It must show a non-zero model charge in the same
  window, or the run is **inconclusive**, not TRUE.
- **"Full charge" is a number.** For the output-blocked profile, Cost Explorer's model charge must equal
  Σ(`usage` tokens) × the Pricing-API price, within Cost Explorer's own rounding (to be recorded from
  the response, not assumed). Guardrail usage types are reported separately, never netted in.
- TRUE only if both hold. FALSE if the input arm is billed model tokens, or the output arm is billed
  measurably less than its own `usage`.

## Cost

Forty Nova Micro requests of about 100 tokens each come to well under $0.01 in model charges. The word
filter bills $0. Cost Explorer API reads cost $0.01 each, and about 5 are expected. Total: **under
$0.10**, against the repo ceiling of $95.

## What needs authorization, in order

1. A read-only Cost Explorer query, to confirm neither profile name nor tag already has usage. This was
   denied by the permission classifier on 2026-09-28.
2. Creating the two `grx-` tagged inference profiles and **activating a cost allocation tag**. Activation
   is an account-level billing setting, which is why it is listed separately.
3. The 40 `Converse` calls, then the Cost Explorer read about 24-48 h later. Afterwards, deleting both
   profiles (the tag's activation can stay; it bills nothing).

## Execution log

**2026-09-29, step 1: done.** These are read-only Cost Explorer and Bedrock reads. The raw responses
are in `evidence/f10-1/`, which is local-only.
- `list-cost-allocation-tags --tag-keys grx-f10-1-arm` returns `[]`.
- Grouped by `TAG:grx-f10-1-arm` over 2026-06-01 to 2026-09-29, with no service filter, all spend falls
  in the empty-value group `grx-f10-1-arm$`. Neither arm value has any usage.
- No application inference profile named `grx-f10-1-*` existed.
- The first query filtered on `SERVICE = Amazon Bedrock` and read $0 for every window in the last 30
  days. That $0 is real: nothing called Nova in that window. An intermediate reading, which blamed the
  service name, is corrected under "How the tag method answers obstacle 3".

**2026-09-29, step 2: half done.**
- Two application inference profiles were created with `copyFrom` =
  `us.amazon.nova-micro-v1:0`, both ACTIVE: `grx-f10-1-input-blocked` (`12jjg23nnft1`) and
  `grx-f10-1-output-blocked` (`wn91zu880oo3`).
- Each was created with tags `grx-f10-1-arm=<arm>` and `grx-project=grx-validation`. The create call
  returned rc 0, but the tags were not read back.
- The description field rejects `(`, `)` and `;`. The first attempt failed validation and created
  nothing.
- **The cost allocation tag is not activated.** The session's permission layer refused
  `ce update-cost-allocation-tags-status` as a shared-resource change, and then also refused the tag
  read-back. Both are left to the user.

**2026-09-30, step 2: done.**
- The user ran the activation. It returned `"Errors": []`.
- `list-cost-allocation-tags` then read `Status: Active` with
  `LastUpdatedDate 2026-09-30T09:04:56Z`. Activation can take up to 24 h to take effect, so no request
  is sent before 2026-10-01T09:05Z.

**2026-09-30: the pre-flight changed the design. There are now three arms.**
- Both prompts were sent once through the untagged system profile. Each landed in its named
  treatment: input-blocked on `zorbify`, and output-blocked on `zorbify` in the model's own output.
- **Both guardrail-intervened responses reported `usage` 0 input / 0 output tokens.** The same output
  prompt sent with no guardrail reported 29 / 4 tokens and the text `zorbify`, identically on 3 calls
  (`evidence/f10-1/reference-unguarded-20260930.json`).
- That refutes two parts of the design above:
  - "Full charge" cannot be priced against the blocked response's own `usage`, because that reads 0.
  - The output arm cannot be its own positive control. A $0 bill on it would be ambiguous between
    "output-blocked requests are not billed" (FALSE) and "the tag never reached the bill" (no reading).
- The fix is a **control arm**: the output prompt with no guardrail, sent through a third profile,
  `grx-f10-1-control` (`pj21d310s69b`), tagged `grx-f10-1-arm=control` and created 2026-09-30.
  - Its truthful `usage` supplies the per-request reference.
  - Its bill must match that `usage` within one token per request. If it does not, the run is an
    instrument fault. If it is unbilled, the run is undecided.
  - Once the control is billed, a $0 output arm is a FALSE reading, not a missing one.
- Cost of the change: 20 more Nova Micro calls, about $0.0001.
- The script is `f10_billing/03_block_billing.py`, in two phases, `send` and `read`. Its offline suite
  is `f10_billing/tests/test_block_billing.py`: 19 tests, and all 11 guard mutants tried are killed.
- The `usage` 0/0 reading is a finding in its own right. A caller that meters guardrail-blocked
  traffic from `Converse`'s `usage` field would count zero model tokens, whatever the bill says.

**2026-10-02, step 3 send: done.** The send ran from 01:32:02Z to 01:33:05Z with rc 0
(`session-logs/f10-1-send-20261001.{log,rc}`).
- The pre-flight through the untagged system profile was output-blocked on `zorbify`.
- 60 rows were sent, 20 per arm, and **0 landed in the wrong arm**.
- Reported `usage`: input-blocked 0/0 ×20, output-blocked 0/0 ×20, control 29/4 ×20.
- The rows file is `results/f10_billing/F10-1-sends.json`, masked.
- `read` is due no earlier than 2026-10-03T01:34Z.

**2026-10-05, step 3 read: done. Verdict FALSE.** The read ran at 01:21:53Z, 71.8 h after the last
send, with rc 0 (`session-logs/f10-1-read-20261005T012153Z.{log,rc}`). The record is
`results/phase1/F10-1.json`.
- Billed model tokens by tag, in input/output: input-blocked 0/0, output-blocked 0/0, control 580/80.
- The control's reported `usage` was 20 × 29/4 = 580/80, so the bill matches it exactly. The unit check
  passed at $0.000035 per 1K input tokens. The tag demonstrably reached the bill.
- The output-blocked arm's expected charge, taken from the control, was 580/80. It was billed 0/0.
  The claim's second half ("output block does not avoid the charge") is refuted, and the sealed
  oracle reads FALSE ("FALSE if either differs").
- **Alternative excluded: the charge landed untagged.** A second read of every Nova Micro usage type
  in USE1, USE2 and USW2, over 2026-10-01 to 2026-10-05 and grouped by the tag with untagged kept,
  shows exactly two groups account-wide, both the control's (0.58 and 0.08 thousand tokens on
  2026-10-02). The pre-flight call, which went through the untagged system profile and was
  output-blocked, is not billed either. So no untagged bucket holds the blocked arms' tokens
  (`evidence/f10-1/ce-novamicro-alltags-20261005.json`, local-only).
- What this does and does not say: on this model, guardrail and day, a Converse request whose output
  the guardrail blocked was billed no model tokens, matching its own `usage` of 0/0. The guardrail's
  own usage types are outside the oracle and are not read here. One model and one word policy is the
  whole sample, so it does not generalise to streaming, to other models, or to other policy types.

**2026-10-05, second read: same bill, record re-emitted.** The first record had no observation day.
The site build and the two-day rule both need one, so `read` now writes `t0_iso` and `t1_iso`, the
first and last send. It does not write the read's own time, because a read on a later day would make one
day of sends count as two (`test_the_record_dates_the_sends_not_the_read`, and both mutants tried are
killed). `read` ran again at 05:06:56Z with rc 0
(`session-logs/f10-1-read-20261005T050656Z.{log,rc}`). The bill was identical: control 580/80 and
both blocked arms 0/0. The record's observation day is 2026-10-02 only.

**2026-10-05, cleanup: done, user-authorised.** All three profiles were deleted:
`grx-f10-1-input-blocked` (`12jjg23nnft1`), `grx-f10-1-output-blocked` (`wn91zu880oo3`) and
`grx-f10-1-control` (`pj21d310s69b`). Each delete returned rc 0, and a list of application inference
profiles named `grx-f10-1-*` then returned none. The `grx-f10-1-arm` cost allocation tag stays active,
because it bills nothing.
