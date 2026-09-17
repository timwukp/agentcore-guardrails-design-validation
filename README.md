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
| `platform/` | Everything that turns the record into something readable. `build/` derives the site payload and gates it (`build_site_data.py`, `check_site_invariants.py`, `publish_web.py`); `curation/` holds only the facts no script can derive — control vocabulary, citation policy, diagram topology — and never a verdict or a number; `audit/`, `census/`, `infra/` (CDK). |
| `site/` | The published bilingual reader (`en` / `zh-TW`). Contains no measured number anywhere in its source: every count, verdict and interval it shows is read from the payload at runtime, so a stale figure is a build failure rather than a typo. |
| `video/` | The narrated explainer embedded on `/design`. Amazon Polly → Chromium → three ffmpeg calls, rendered twice and required to be byte-identical. See `video/README.md`. |
| `tools/` | Off-platform instruments: `deckgen/` (the bilingual document reader the practice extractor is built on), `whitepaper_figures.py`, `api_push_incremental.py` / `api_push_pr.py` (this repo is pushed through the GitHub Git Data API), `repo_diff.py`, `sync_handover_bundle.py`, `day2_replicate.py`. |
| `WHITEPAPER.md`, `WHITEPAPER-DESIGN.md` | The long-form write-up of what was measured, and the design rationale for how it is presented. |
| `agentcore_guardrails_best_practices_v1.4[.zh-TW].md` | The design document as it now stands, in both languages. The site's `/design` page reads its 45 numbered practices, its 28-entry checklist and its inline case citations **out of these files** — no practice prose is authored in this repo, so if the document changes the page changes and the recorded hash says so. Note the pre-registration was sealed against **v1.2**: the register measures v1.2's claims, and v1.4 is what the design page publishes. |
| `COST.md`, `SECURITY.md`, `AWS-BEHAVIOR-CHANGES.md`, `V13_CANDIDATES.md`, `FUTURE-WORK.md` | Spend, disclosure posture, service behaviour that changed under us mid-study, candidate amendments, and the standing deficiency register. |

## What the site publishes, and the one rule holding it up

The reader gets two things: the **evidence** (a page per case, each carrying its verdict, its interval
and its raw parameters) and the **design** (`/design` — the 45 practices, grouped by the six normative
hops, with a topology diagram and a narrated explainer). The only reason to publish the design here
rather than anywhere else is the sentence *these practices were measured on this platform, and you can
check* — so that sentence is a program, not a claim:

- **The link is derived, never authored.** `practices_source.py` parses the practices and the document's
  own inline case references out of the two v1.4 editions; `check_practices.py` then compares every
  asserted `(case, verdict)` pair against `results/phase1/<case>.json` and against the citation policy,
  importing both readers rather than reimplementing them. A document that says TRUE where the register
  says INCONCLUSIVE fails the build.
- **Disagreements are adjudicated in a ledger, not suppressed.** Each entry quotes the sentence in both
  editions and the gate re-reads the quotation; an unexplained occurrence fails, and so does an excuse
  whose occurrence no longer exists.
- **Both directions of coverage are counted.** The document cites **87** cases; the register carries
  **93**; the **6** it never mentions are published as their own list, because "measured, and the design
  document says nothing about it" is a finding too.
- **`not_measured` never reads as clean.** It renders as *this study never looked* — the state an
  architecture page usually leaves blank.
- **No pass rate, score, grade or percentage anywhere**, including in the video: one frame with a
  percentage would travel further than every caveat attached to it.
- **The narration is disclosed as synthesized** (Amazon Polly; English Ruth on the generative engine,
  Chinese Zhiyu on neural in `cmn-CN` because Polly ships no Taiwanese Mandarin voice at all). Claiming
  a human voice over a synthetic track would be this repo contradicting its own editorial rule.

Parity is a gate, not an intention: the two editions must carry the same practice ids and the same
citation multiset, so a Chinese reader is never shown fewer links than an English one.

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

The site is a separate toolchain and reads no AWS API at all; the explainer reads exactly one,
Amazon Polly. Both want the interpreter that has `playwright` and `yaml`, which is not the oracle venv:

```bash
PY=/opt/homebrew/opt/python@3.12/bin/python3.12
$PY platform/build/build_site_data.py --clean --render-rc <rc>  # derive the payload
$PY platform/build/check_site_invariants.py --verbose           # the invariant harness
$PY platform/build/csp_preview.py                              # serve dist/ under the real CSP
$PY video/render.py --verify                                   # render twice, require identical bytes
```

`--render-rc` and `--figure-check-rc` have **no default in any layer**: they are the exit code measured
by whoever ran the renderer, and a missing one means *not verified*, never 0. `--verify` re-synthesizes
from Polly deliberately — it deletes its own audio cache between the two renders — so each run bills two
full passes and costs real money; `video/README.md` carries the measured spend.
