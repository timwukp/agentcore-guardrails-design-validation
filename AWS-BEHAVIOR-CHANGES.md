# AWS-BEHAVIOR-CHANGES.md — dated drift in AWS behaviour or documentation

## Why this file exists, and what it is *not*

`agentcore_guardrails_best_practices_v1.2.md` is being validated against measurement, and
the governing principle is that facts win. But "the document is wrong" and "the document
has expired" are **different findings with different amendments**, and a reader two years
from now cannot tell them apart from a corrected sentence alone.

| Classification | What the reader needs |
|:---|:---|
| **doc wrong** | the correction, and no date — it was never true |
| **doc expired** (this file) | the correction, **the date it stopped being true**, and a pointer to the live source |
| **doc imprecise** | the missing qualifier, not a changed value |
| **test invalid** | nothing in the document changes |

Only the second class belongs here. An entry records what AWS said, what AWS says now,
**how the transition date was established**, and — where it could not be established —
says so rather than inferring one.

**The rule that makes this file honest:** a change date may only be recorded when it rests
on **dated observations on both sides of the transition**. **Absence of evidence is not a
transition.** F5-7a produced one entry of each kind, which is why both appear below: the
Evaluations row has archived pages saying the old thing and a live page saying the new
one; the Optimization row has a live page contradicting our document and **silence**
before it, so its date is `undetermined` and stays that way.

**What this file does not do:** it does not certify that AWS's *service* changed. Every
entry below is sourced from a documentation page, and a page is a statement about a
service, not the service. Where the distinction matters the entry says which instrument
established what.

*Every entry is derived from a finding under `results/`, which holds the request IDs and
raw archived HTML. Nothing here is a summary written from memory.*

---

## ABC-01 — PrivateLink for AgentCore Evaluations: data plane went from "Not yet supported" to "Supported"

| | |
|:---|:---|
| **Primitive** | Evaluations (`bedrock-agentcore` endpoint prefix) |
| **What v1.2 §4.5.3 says** | Evaluations: data plane ❌, control plane ✅ (control plane only) — cited to Accelerator v2.9 |
| **What AWS documented, ≤ 2026-07-14** | `Evaluations · Not yet supported · Supported` |
| **What AWS documents now** | `Evaluations and Optimizations · Supported · Supported` (row renamed and merged) |
| **Classification** | **AWS behaviour changed.** Our document agreed with AWS's own public page for at least the three months preceding it. |
| **Change window** | after **2026-07-14**, at or before **2026-08-09** |
| **How the window was established** | **Five** archived snapshots of `vpc-interface-endpoints.html` (2026-04-12, 2026-06-19, 2026-06-23, 2026-06-30, 2026-07-14) all read `Not yet supported`; the live page read `Supported` on **2026-08-09 and again on 2026-08-10**. Wayback CDX was queried with `collapse=digest`, so the snapshot timestamps are dates the page *changed*, not dates a crawler visited — the five agreeing snapshots therefore span distinct content hashes. Only **four** of the five were re-returned on day 2 (`20260623161005` was not); the CDX index is a third-party query and its result set is not an observation about AWS, so the window rests on the five, and the four re-fetched parsed identically. |
| **Instrument** | B (public documentation, live + Internet Archive). **Not** an API observation. |
| **Replicated** | Yes — 2026-08-09 and 2026-08-10, 75 fields compared, 0 disagreements (`results/f5_7a_replication.json`) |
| **Finding** | [`results/FINDING-F5-7A.md`](results/FINDING-F5-7A.md) findings 4 |
| **Amendment** | V13-03 → §4.5.3, plus §5.3 BP#6, which turns the matrix into an instruction to **defer** the closed loop's AFTER phase |
| **Residual, stated** | That AWS *documents* support. Whether PrivateLink is functionally present for this primitive is untested here and is F5-7b's job; no read-only instrument can settle it. |

> The phrase "no PrivateLink **today**" in §4.5.3 was doing real work — the row was always
> time-bounded — but the document never gave the reader a date to bound it with. That is
> the defect this file is the remedy for, and the amendment adds the date rather than
> silently flipping two glyphs.

---

## ABC-02 — PrivateLink for AgentCore Optimization: refuted, transition date **undetermined**

| | |
|:---|:---|
| **Primitive** | Optimization |
| **What v1.2 §4.5.3 says** | Optimization: ❌ / ❌ — "no PrivateLink today", cited to Accelerator v2.9 |
| **What AWS documented before** | **nothing.** The 2026-04-12 → 07-14 snapshots carry seven rows and **none** mentions Optimization. |
| **What AWS documents now** | `Evaluations and Optimizations · Supported · Supported` |
| **Classification** | **Document refuted; change date undetermined.** Deliberately weaker than ABC-01. |
| **Change window** | **cannot be established** |
| **Why not** | AWS was *silent*, not contradictory. Silence is compatible with both "unsupported then, supported now" and "supported all along, merely undocumented", and instrument B cannot separate them. Recording a date here would be inferring a transition from the **absence** of evidence — the failure mode this file's own rule forbids. |
| **Instrument** | B |
| **Replicated** | Yes — the live row was identical on both days |
| **Finding** | [`results/FINDING-F5-7A.md`](results/FINDING-F5-7A.md) finding 5 |
| **Amendment** | V13-03, same sites as ABC-01 — the two rows are now one row on AWS's page |
| **Open** | Whether Accelerator v2.9 and AWS's public page describe the same scope. The Accelerator has an Optimization row; AWS's page never did. Unresolvable without the Accelerator's own date. |

---

## Watch list — claims that will expire, with the instrument that detects it

Not drift yet. Each of these is a measurement whose subject is versioned or dated, so
re-running the named script is how expiry is noticed rather than discovered by a reader.

| # | Claim | What would expire it | Detector |
|--:|:---|:---|:---|
| W-01 | F8-8: no `language` or detection-mode field exists anywhere in the guardrail create/apply surface (**120** enums swept across both service models, 251 AR input members, 0 hits) | a later botocore exposing one | re-run `f8_regional/07_absent_surface.py` under a newer pin; it is dated by botocore **1.43.67** |
| W-02 | F1-1: `CreatePolicy.enforcementMode` and `definition.policy` first appear at botocore **1.43.32**; `InvokeGuardrailChecks` at **1.43.30** | nothing — released wheels are immutable | none needed, and this is why `FINDING-F1-1` is `RESOLVED` with no replication requirement |
| W-03 | F8-5's boundary verdict is the *service's* because `botocore.validate.range_check` has no `max` branch | a botocore adding client-side max-length validation | F8-5 re-checks the branch live each run and routes to INCONCLUSIVE rather than reporting a client-side rejection as a service boundary |
| W-04 | The 31 PII entity types F3-4 enumerates from the `CreateGuardrail` model | AWS adding an entity type | `entity_types()` raises on **either** direction of mismatch — a type with no corpus, or a corpus with no type |
| W-05 | §4.5.3's three endpoint prefixes, identical across 8 regions | a fourth prefix, or regional divergence | `f5_redteam/07a_privatelink_enum.py`, $0 and unmetered |
| W-06 | *(not a claim — an open defect)* `07a_run_day2.sh` has no "a run for this UTC day already exists" guard, so a manual and a scheduled invocation both satisfied the day-2 requirement and competed to write one verdict file (DEV-SEAL-13) | nothing expires it; it is fixed by adding the guard with a `--force` escape | until then, `07a_compare_runs.py` naming both run ids in `results/f5_7a_replication.json` is what makes a race visible rather than silent |

---

*Format note: entries are `ABC-NN`, appended in observation order and never renumbered — a
citation to `ABC-01` in the v1.3 change log must not move. An entry is only added when a
finding under `results/` supports it with dated raw evidence.*
