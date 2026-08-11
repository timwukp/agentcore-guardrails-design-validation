# FINDING F1-1 / F1-2 — The policy API surface exists; the installed SDK was stale

**Status:** RESOLVED (offline, deterministic, $0)
**Date:** 2026-08-09
**Script:** `f1_config/01_sdk_bisect.py --bisect --verify-monotone`
**Raw data:** `results/f1_sdk_bisect.json` (14 probed versions, full surface per version)
**Class:** C (config-surface). Blocker for every live phase; not a document defect.

<!-- provenance
{
  "status": "RESOLVED",
  "evidence_runs": [],
  "note": "Offline and deterministic: the observations are the contents of 14 published wheels, which are immutable once released. The 2-separate-days rule exists to exclude transient state, and a released wheel has none — re-reading the same sdist tomorrow is not an independent observation. This finding therefore asserts nothing about live AWS behaviour and requires no replication."
}
-->

## Question

The installed botocore **1.42.79** models `CreatePolicy` **without** `enforcementMode`
and with `PolicyDefinition = {cedar, policyGeneration}`, while AWS documentation
shows `--enforcement-mode ACTIVE|LOG_ONLY` and `definition.policy.statement`. Two
mutually exclusive explanations:

- **H1** — the SDK is stale; a newer release models both fields.
- **H2** — the documentation describes a surface the service does not expose.

This had to be settled before any harness code could be written, because §4.1
BP#6 of the document under test instructs readers to rely on per-policy
`enforcementMode`. Under H2 that instruction would be unfollowable.

## Method

`pip download botocore==X --no-deps` fetches the wheel; the service model is read
directly out of it at `botocore/data/<service>/<api-version>/service-2.json.gz`.
That is the same artifact the runtime client is built from, so reading it answers
the question exactly — with no install, no credentials, and no AWS API call.

Binary search over the 249 releases ≥ 1.40.0 (range 1.40.0 … 1.43.67) instead of
a linear scan: **14 wheels downloaded, not 249.** Monotonicity — the assumption
binary search depends on — was verified rather than assumed: `--verify-monotone`
re-probes the versions bracketing each boundary plus a sample well below it and
asserts false-below / true-at-and-above. All three predicates returned
`monotone: true`.

## Result: H1 confirmed

| Predicate | First botocore version | Monotone verified |
|:---|:---|:---|
| `CreatePolicy.enforcementMode` | **1.43.32** | ✅ |
| `definition.policy` (`PolicyStatement`) | **1.43.32** | ✅ |
| `bedrock-runtime.InvokeGuardrailChecks` | **1.43.30** | ✅ |

Installed 1.42.79 predates all three. The documentation was right; the SDK was
old. **No document amendment is warranted from this finding** — but three
consequences for the platform, and one for the document's audience.

### Surface as modelled at 1.43.67

```
CreatePolicyRequest = {name, definition, description, validationMode,
                       enforcementMode, policyEngineId, clientToken}

PolicyDefinition  (union: true)
  ├── cedar             -> CedarPolicy      {statement}   required: statement
  ├── policy            -> PolicyStatement  {statement}   required: statement
  └── policyGeneration  -> PolicyGenerationDetails {policyGenerationId,
                                                    policyGenerationAssetId}

enforcementMode : ACTIVE | LOG_ONLY          "Defaults to ACTIVE."
validationMode  : FAIL_ON_ANY_FINDINGS | IGNORE_ALL_FINDINGS
GatewayPolicyEngineMode : LOG_ONLY | ENFORCE
InvokeGuardrailChecks request = {messages, checks}
```

`enforcementMode` appears on 9 shapes — `CreatePolicyRequest`,
`UpdatePolicyRequest`, and the `Get`/`Delete`/`Policy`/`PolicySummary` responses
— which independently corroborates §4.1 BP#6's claim that the field is both
settable and readable back.

## Consequences

1. **`.venv-oracle` pins `botocore>=1.43.32`** (plan said 1.43.67 — that remains
   the pin, and 1.43.32 is now the documented floor with a reason attached).
   1.43.30/.31 model `InvokeGuardrailChecks` but *not* `enforcementMode`, so a pin
   in that two-release window would silently produce an F4 truth table missing
   half its axis.
2. **No compat shim is needed, and `cedar` must not be assumed dead.**
   `PolicyDefinition` is a genuine `union: true` with `cedar` and `policy` as
   sibling members; neither carries a `deprecated` marker. `policy` is the
   documented spelling and the harness will use it, but because a union permits
   exactly one member, *which* spelling the service accepts is a live question the
   model cannot answer. **F1-4 (new, Phase 3) tests all three arms** — `cedar`
   only, `policy` only, both at once — and expects the third to be rejected.
3. **`validationMode` documentation confirms DC-1's mechanism.** Verbatim from the
   model: `FAIL_ON_ANY_FINDINGS` *"(default) runs the Cedar analyzer … failing
   creation if the analyzer detects any validation issues"*. That is precisely why
   the pre-existing `permit(principal, action, resource is AgentCore::Gateway);`
   policy sits in `CREATE_FAILED`. DC-1 is now supported by two independent
   sources — the observed failed policy and the SDK's own field documentation —
   before a single API call is made.

## Carry-forward for the v1.3 amendment

Not a factual error in the document, but a real trap for its readers: the fields
§4.1 BP#6 and §7.1 depend on require **botocore ≥ 1.43.32 / boto3 ≥ 1.43.32**, and
a reader on an older SDK gets a `ParamValidationError` rather than a message
explaining that their SDK is too old. A one-line minimum-version note belongs in
§3.1 or §8 Phase 1. Filed against claim sites in §4.1 BP#6 and §7.1.
