# FINDING-P0-PRICING — AWS meters `InvokeGuardrailChecks` and `ApplyGuardrail` as separate, differently-priced evaluation paths

**Phase** 0 (offline w.r.t. the document; one read of the AWS Pricing API) · **Cost** $0
**Artifacts** `cost_model.yaml` (9 verified prices) · `estimate_cost.py` ·
`COST.md` (generated) · `claims/tests/test_cost_gate.py` (21 tests) ·
`DEVIATIONS.md` DEV-SEAL-9
**Class** C (config-surface), with a consequence for the F5-6/DC-2 design

<!-- provenance
{
  "status": "INTERNAL",
  "evidence_runs": [],
  "note": "A price list read from the AWS Pricing API. It does not amend the document: separate metering does not entail different detection behaviour, and the §3.2 amendment still waits on F5-6's measurement. Recorded as INTERNAL rather than READY_TO_AMEND for that reason, not because the observation is weak."
}
-->

---

## 1. Why a pricing observation is a finding

It was not meant to be. `estimate_cost.py` exists because the approved plan specifies a
script that refuses to run over a pre-registered cost ceiling, and neither the script nor
a machine-readable ceiling existed (DEV-SEAL-9). Verifying the unit prices was a
bookkeeping step.

The price list turned out to answer a question the experimental design had assigned to a
live phase.

## 2. The observation

`get_attribute_values(ServiceCode="AmazonBedrock", AttributeName="usagetype")` returns
**205 guardrail-related usage types**, in two families that do not overlap:

| Family | us-east-1 usage type | USD / text unit |
|:---|:---|---:|
| `ApplyGuardrail` | `USE1-Guardrail-ContentPolicyUnitsConsumed` | **0.00015** |
| `ApplyGuardrail` | `USE1-Guardrail-SensitiveInformationPolicyPaidUnitsConsumed` | 0.00010 |
| `ApplyGuardrail` | `USE1-Guardrail-SensitiveInformationPolicyFreeUnitsConsumed` | 0.00000 |
| `ApplyGuardrail` | `USE1-Guardrail-TopicPolicyUnitsConsumed` | *(present)* |
| `ApplyGuardrail` | `USE1-Guardrail-WordPolicyUnitsConsumed` | *(present)* |
| `InvokeGuardrailChecks` | `USE1-GuardrailChecks-ContentFilterCheckUnitsConsumed` | **0.00007** |
| `InvokeGuardrailChecks` | `USE1-GuardrailChecks-PromptAttackCheckUnitsConsumed` | 0.00008 |
| `InvokeGuardrailChecks` | `USE1-GuardrailChecks-SensitiveInformationCheckUnitsConsumed` | 0.00010 |

Two facts:

1. **The families are disjoint.** `GuardrailChecks-*` is not an alias, a discount tier or
   a sub-line of `Guardrail-*`. They are separate usage types on the bill.
2. **Content filtering costs less than half as much** through `InvokeGuardrailChecks`
   (0.00007) as through `ApplyGuardrail` (0.00015) — a factor of 2.14.

A third, structural: the `Guardrail-*` family has **five** policy dimensions (content,
sensitive-information, topic, word, contextual-grounding, plus automated-reasoning and an
image variant in us-east-1), while `GuardrailChecks-*` has **three** (contentFilter,
promptAttack, sensitiveInformation). The two surfaces do not offer the same set of checks.

## 3. What it bears on

§3.2 of the document under test discusses prompt-attack detection without separating the
two APIs. The pre-registration flags this as **DC-2** and assigns it to **F5-6**, a
4-arm × 120-item live experiment: InvokeModel untagged / InvokeModel with `guard_content`
/ Converse without `guardContent` / Converse with `guardContent` on a different block.
The pre-registration's stated rationale is that *"the doc may be right about one API and
wrong about another"*.

That rationale presupposes the two APIs *can* differ. Before this observation, the
presupposition was an inference from the shape of the SDK model. It is now supported by
AWS's own billing: **a service does not maintain disjoint usage types at different unit
prices for two front doors onto one computation.** Different price ⇒ different metered
work ⇒ the two paths are not the same evaluator.

## 4. What it does not establish

Stated explicitly, because the temptation to over-read a cheap result is exactly what the
conflict-resolution protocol exists to resist:

- **It does not amend §3.2.** Separate metering does not entail different *detection
  behaviour*. Two evaluators can be billed differently and still agree on every input in
  our corpus. Only F5-6's measurement can settle recall per arm, and its Wilson intervals
  are the evidence §3.2 needs.
- **It does not establish which path is more accurate.** A lower price is consistent with
  a cheaper model, a narrower check, a promotional rate, or a different unit definition.
  Nothing here distinguishes those.
- **It does not tell us the unit is comparable.** Both are "TextUnit", but the
  `Guardrail-*` descriptions read "per 1K text units" while `GuardrailChecks-*` read "per
  TextUnit". The per-unit USD figures above are already normalised, and the underlying
  character-count definition per family is **unverified** — an open item for F10.

The status is therefore `INTERNAL`, not `READY_TO_AMEND`.

## 5. A regional side-observation, and its limit

`GuardrailChecks-*` usage types exist in **7 regions**: us-east-1, us-east-2, us-west-2,
eu-west-2, eu-north-1, ap-northeast-1, ap-southeast-2.

The document's verified guardrails-in-policy region list has **5**: us-east-1, eu-west-2,
eu-north-1, ap-southeast-2, ap-northeast-1. The pricing list is a **superset**, adding
us-east-2 and us-west-2.

This is suggestive for **F8-1** (the nine-region probe) and it is *not* a finding about
regional availability. A usage type is a billing construct; its presence means the
metering exists, not that the API accepts calls, and F5-7a already established the
converse direction as a limitation of exactly this class of instrument — *the existence
of an endpoint service does not entail availability*. The correct use of this observation
is as a **prior for where to look**: if F8-1 finds `InvokeGuardrailChecks` working in
us-east-2 or us-west-2, the document's five-region list is incomplete; if it does not, the
pricing superset is evidence about AWS's internal rollout and nothing more. F8-1 is
unchanged either way — it probes nine regions regardless.

## 6. Instrument and reproduction

```bash
python3 estimate_cost.py --verify-prices     # 9 prices, recorded vs live, rc=1 on drift
```

Every price in `cost_model.yaml` carries a `pricing_api` block naming service code and
usage type, so each figure is re-derivable rather than asserted. `--verify-prices` prints
recorded-vs-live and **never writes** to the model: a price change is a decision a person
records, not a silent edit. Region us-east-1, read 2026-08-09.

Four of my five initial prices were wrong, one by 5× — the details are in DEV-SEAL-9,
which is where they belong, since they are a defect in my construction of the cost model
rather than a property of AWS.

## 7. Cost

**$0.** The Pricing API is not metered. 14 `get_products` / `get_attribute_values` calls.
