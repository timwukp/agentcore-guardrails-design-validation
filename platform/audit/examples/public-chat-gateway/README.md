# Example submission — a B2C public chat gateway

**This is a synthetic template. Nothing here was ever deployed, and no resource in it exists.** It is
the worked example the platform renders on `/report`, so that a reader can see what an audit output
looks like before pointing the tools at their own repository.

It is authored, not captured, for one reason: a captured template from the study's own runs would
carry real resource identifiers, and the honest way to show a report is with a submission whose every
identifier is one of the documentation-reserved account ids (`111122223333`). The redaction gate
enforces that; this file states the intent so nobody "improves" the example by pasting a real one.

## The defects are deliberate, and each one is a state the report must be able to say out loud

| File | What it declares | Why it is here |
|---|---|---|
| `gateway.yaml` | policy engine `LOG_ONLY`, `exceptionLevel: DEBUG`, an ACTIVE Cedar policy, an MCP Lambda target with no private endpoint, one alarm | the commonest shape of a "protected" gateway that enforces nothing |
| `guardrail.yaml` | PROMPT_ATTACK filter enabled on input only, PII `ANONYMIZE`, one denied topic, `CLASSIC` tier | exercises input/output checkpoint asymmetry and the tier finding |
| `staging-gateway.yaml` | the engine mode as `!Ref EngineMode` | an **unresolved** site: a parameterised value the parser must report as unresolved rather than guess |
| `memory.tfplan.json` | a managed memory with `SEMANTIC` in its strategies | a control this study **never measured**, so the report must read NOT MEASURED and not "no problem found" |

No private endpoint is declared anywhere in these files, so the example also shows the `NOT_DECLARED`
state — which means "not seen in the files that were parsed", never "absent from your system". The
exact split is not restated here: it is derived by the tools and rendered in the report, and a count
copied into this paragraph would be a second, unchecked source for it.
