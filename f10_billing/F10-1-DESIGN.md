# F10-1 measurement design — input block avoids the model charge, output block does not

Status: **design only, nothing sent.** Written 2026-09-28. Everything below that touches the account
waits on the three authorizations in the last section.

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
- read Cost Explorer grouped by `TAG:grx-f10-1-arm` and by `USAGE_TYPE`, filtered to Amazon Bedrock,
  over the days the requests ran.

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
