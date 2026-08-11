# GRX — Empirical validation of the AgentCore guardrails design doc

This repository is a pre-registered validation platform for
`agentcore_guardrails_best_practices_v1.2.md`: every testable claim in that
document is extracted, triaged, bound to a sealed decision rule, and then
measured against the live AWS Bedrock AgentCore service. Facts win over the
document — in both directions, which is why the analysis is committed before
the data exists.

## How to read this repo

| Path | What it is |
|---|---|
| `PREREGISTRATION.yaml` + `.sha256` | Sealed hypotheses, sample sizes, decision rules — fixed before any data. `verify_prereg.py` re-derives every number and fails on drift. |
| `claims/` | Claim extraction and triage from the document under test. |
| `corpora/`, `corpora_deviation/` | Test corpora (synthetic fixtures only; see redaction note below). |
| `f1_config/` … `f10_billing/` | One directory per claim family; each script is a self-contained experiment. |
| `lib/` | Shared instrument: MCP client/classifier, Cedar statement builder, testbed ledger, stats (intervals only — no decision rules). |
| `results/` | The distributable record: per-case JSON verdicts, checkpoints, findings. |
| `DEVIATIONS.md`, `EXCLUSION_REGISTER.md` | Anything that departed from the pre-registration, dated and reasoned. |
| `RECONNECT.md` | Live state; read first when resuming work. |
| `check_redaction.py` | Release gate: no cloud identifiers in anything distributed. |

## What is deliberately not here

`evidence/` (raw API request/response archives keyed by request id and full ARN)
is **local-only by policy, not by oversight** — its purpose is that a claim can be
taken to AWS Support and looked up verbatim, and masking it would defeat that.
The distributable record is `results/`. See `check_redaction.py`'s docstring.

All identifiers in the corpora are synthetic or AWS-published documentation
examples (`AKIA…EXAMPLE` keys, alphabet-ordered fake tokens, fabricated 12-digit
account numbers authored as PII fixtures). The redaction gate scans every
distributed file and fails on a scan that reads zero files.

## Running

Experiments assume a live testbed recorded in `state.json` (built by `infra/`)
and credentials for the target account. Each `f*/`-family script is standalone:

```bash
.venv-oracle/bin/python f4_modes/01_truth_table.py --n 3   # smoke
.venv-oracle/bin/python verify_prereg.py                    # seal check
python3 check_redaction.py                                  # release gate
```
