# FINDING F5-7a — The PrivateLink coverage matrix (§4.5.3): one claim confirmed, one caveat confirmed, two support marks now contradicted by AWS's own page

**Status:** REPLICATED ON TWO CALENDAR DAYS · **READY TO AMEND** (see §7)
**Dates:** day 1 **2026-08-09**, day 2 **2026-08-10** (UTC, derived from `t_start_utc` in the records)
**Script:** `f5_redteam/07a_privatelink_enum.py` · replication driver `f5_redteam/07a_run_day2.sh` · comparator `f5_redteam/07a_compare_runs.py`
**Run ids:** `r20260809T094500Z` (day 1), `r20260810T002001Z` (day 2, canonical — see §7 "Two day-2 runs")
**Raw evidence:** `evidence/r20260809T094500Z/f5/F5-7a/`, `evidence/r20260810T002001Z/f5/F5-7a/`
**Replication verdict:** `results/f5_7a_replication.json` — **75 fields compared, 0 disagreements**
**Pre-registration seal in force:** `6eb1ba6e09d4…3923e8e4`
**Cost: $0.** 32 `ec2:DescribeVpcEndpointServices` calls across the two days (not billed), 0 mutations, 0 resources created.
**Document under test:** §4.5.3 (PrivateLink coverage matrix + caveats a/b), with a
consequence for §5.3 BP#6 and §8 Phase 1 / Phase 3 checklists.
**Class:** C (config-surface). Family `descriptive_no_test` — deterministic existence
observations, no p-values, no multiplicity correction (pre-registered).

<!-- provenance
{
  "status": "READY_TO_AMEND",
  "evidence_runs": ["r20260809T094500Z", "r20260810T002001Z"],
  "cases": ["F5-7a"],
  "was_blocked_on": "A replication of 07a_privatelink_enum.py on a calendar day after the one the day-1 evidence was collected on. Findings 4 and 5 amend the document on the strength of a web page's content, and the thing observed to have changed IS that content; one read cannot separate a durable change from a transient publication state or a CDN-cached variant, which §7's alternative-explanation register lists as NOT excluded. Findings 1, 2, 3 and 6 never depended on this. DISCHARGED 2026-08-10: 07a_compare_runs.py compared 75 fields across the two runs and found 0 disagreements (results/f5_7a_replication.json).",
  "amends": ["S4.5.3"]
}
-->
<!-- The block above is read by check_amendment_readiness.py. It declares the runs, not
     the dates: dates are derived from t_start_utc in the evidence records, so this
     finding cannot assert its own replication. That is why the promotion to
     READY_TO_AMEND is safe to make by editing this block: the gate re-derives 2026-08-09
     and 2026-08-10 from the records under both run ids and would refuse the status if
     either day's records were absent.

     `was_blocked_on`, not `blocked_on`: the key is renamed rather than deleted so the
     condition that gated the amendment stays legible next to the evidence that
     discharged it, while the gate's DEFERRED_STATUSES branch — which requires a live
     `blocked_on` — no longer matches a finding that is no longer deferred. -->


---

## 1. What the document claims

§4.5.3, cited to **Accelerator v2.9 (Service Controls table)**:

| Service | Data plane | Control plane |
|:---|:---:|:---:|
| Runtime, Memory, Built-in Tools, Identity, Gateway, Policy | ✅ | ✅ |
| Evaluations | ❌ | ✅ (control plane only) |
| **Optimization** | ❌ | ❌ (**no PrivateLink today**) |

plus two caveats: **(a)** VPC endpoint policies restrict by IAM principal only, so
OAuth-authenticated callers require `Principal: *`; **(b)** the Gateway has a
**third, separate** PrivateLink endpoint distinct from the data and control planes.

§5.3 BP#6 turns the matrix into an instruction: *"Optimization does not support
PrivateLink today, and Evaluations supports PrivateLink for the control plane only
… the closed loop's AFTER phase needs a network exception or must wait for support."*
So this is not a decorative table — a reader in a PrivateLink-mandated environment
is being told to **defer a capability**.

## 2. What is observable, decided before collecting data

This determines what the test can conclude, so it is stated up front and is
reproduced verbatim in the script's module docstring.

PrivateLink attaches to an **endpoint service name** — `com.amazonaws.<region>.<prefix>`
— not to a primitive. AgentCore has **three** prefixes; the document's matrix has
three rows naming **eight** primitives. The mapping is many-to-one. Therefore:

- **Directly observable (instrument A).** Which endpoint services exist, in which
  regions, with which private DNS names, AZ coverage, IP address types and whether
  each supports an endpoint policy. Decisive for caveat (b), and decisive for
  "does a dedicated Evaluations or Optimization endpoint service exist".
- **NOT observable this way.** Whether a *primitive* is reachable over an existing
  endpoint. `Evaluate` is an operation on endpoint prefix `bedrock-agentcore` —
  which **does** have an endpoint service. So "Evaluations data plane ❌" **cannot
  be refuted** by the absence of a `bedrock-agentcore-evaluations` service, because
  the matrix never claimed such a service existed.

> **The trap this test was built to avoid.** An earlier pass of this analysis
> nearly recorded "the matrix is wrong, because `Evaluate` lives on a prefix that
> has an endpoint service." That does not follow. It confuses *the endpoint a call
> is signed against* with *whether the service accepts that call over PrivateLink*.
> Recording it would have amended a correct document row on the strength of a
> category error — the same shape of mistake as DEV-P0-8, where a label-level fact
> was used to license an item-level claim.

Because instrument A is structurally incapable of settling the support marks, a
second, independent instrument is required.

- **Instrument B.** The AWS public documentation page the document already cites
  (`vpc-interface-endpoints.html`), read **live** and read from the **Internet
  Archive at earlier timestamps**. A support matrix is a statement about service
  state, and service state has a date. Reading the same page across time is what
  separates *"our document was wrong"* from *"our document was right and AWS
  shipped the feature afterwards"* — and per the plan's Part 6 those two classes
  lead to different amendments and different change-log entries.

## 3. Method

**Instrument A** — `ec2:DescribeVpcEndpointServices`, run twice per region:
filtered on `com.amazonaws.*.bedrock-agentcore*`, and **unfiltered**. The
unfiltered call supplies the denominator, and the difference matters: "3 of 3
services match" and "3 of 617 services match" support different sentences. The
unfiltered list is then keyword-searched for `evaluat` and `agentcore-optimi`, so
"no such endpoint service" is a statement about *all* of PrivateLink in that
region rather than about our filter string.

**Regions: 5 supported + 3 controls.** The three control regions (`us-west-2`,
`eu-central-1`, `sa-east-1`) are regions the document lists as **not** supporting
guardrails-in-policy. They are not padding — see finding 6, which is the reason
instrument A's conclusions are bounded.

**Instrument B** — live GET, plus Wayback CDX with `collapse=digest` so the
returned timestamps are the dates the page **changed** rather than the dates a
crawler happened to visit. Every fetched page is written verbatim into
`evidence/` so the comparison remains checkable after the pages change again.

Every call — success or failure — is recorded through `lib/evidence.py` with
`x-amzn-requestid`, HTTP status, all headers, wall-clock timing, region, SDK
version and the pre-registration hash in force. **16 calls, 16 OK, 0 errors.**

## 4. Results — instrument A

Exactly **three** AgentCore endpoint services exist, and the set is **identical in
all 8 regions** (`endpoint_set_identical_across_regions: true`):

| Endpoint service | Private DNS | Interface | Endpoint policy | IP types | AZs (us-east-1) |
|:---|:---|:---:|:---:|:---|---:|
| `com.amazonaws.<region>.bedrock-agentcore` | `bedrock-agentcore.<region>.amazonaws.com` | ✅ | ✅ | ipv4, ipv6 | 6 |
| `com.amazonaws.<region>.bedrock-agentcore-control` | `bedrock-agentcore-control.<region>.amazonaws.com` | ✅ | ✅ | ipv4, ipv6 | 6 |
| `com.amazonaws.<region>.bedrock-agentcore.gateway` | `*.gateway.bedrock-agentcore.<region>.amazonaws.com` | ✅ | ✅ | ipv4, ipv6 | 6 |

All three are `Owner: amazon`, `AcceptanceRequired: false`.

Per-region totals, and keyword hits over the **whole** unfiltered service list:

| Region | Status per doc | AgentCore services | All services | `evaluat` hits | `agentcore-optimi` hits |
|:---|:---|---:|---:|---:|---:|
| us-east-1 | supported | 3 | 617 | 0 | 0 |
| eu-west-2 | supported | 3 | 362 | 0 | 0 |
| eu-north-1 | supported | 3 | 300 | 0 | 0 |
| ap-southeast-2 | supported | 3 | 385 | 0 | 0 |
| ap-northeast-1 | supported | 3 | 380 | 0 | 0 |
| us-west-2 | **control (unsupported)** | 3 | 567 | 0 | 0 |
| eu-central-1 | **control (unsupported)** | 3 | 391 | 0 | 0 |
| sa-east-1 | **control (unsupported)** | 3 | 307 | 0 | 0 |

Sample request IDs (all 16 are in `summary.json`):
`6b8ea770-cde6-4b75-a998-5a1cf43ce11c`, `1be050b6-27b1-4193-9b3a-f2012dded477`,
`747898cb-4cdb-45db-9468-c14b8589c96a`.

## 5. Results — instrument B: the AWS page, dated

The page carried **no support table at all** until spring 2026, then carried one
saying **"Evaluations · Not yet supported · Supported"** through at least
2026-07-14, and today says **"Evaluations and Optimizations · Supported · Supported"**.

| Snapshot (UTC) | Support table? | Evaluations data plane | Optimization row |
|:---|:---:|:---|:---|
| 2025-09-25 | ✗ absent | — | — |
| 2025-11-12 | ✗ absent | — | — |
| 2025-12-30 | ✗ absent | — | — |
| **2026-04-12** | ✓ | **Not yet supported** | **no such row** |
| 2026-06-19 | ✓ | Not yet supported | no such row |
| 2026-06-23 | ✓ | Not yet supported | no such row |
| 2026-06-30 | ✓ | Not yet supported | no such row |
| **2026-07-14** | ✓ | **Not yet supported** | **no such row** |
| **live, 2026-08-09** | ✓ | **Supported** *(row renamed `Evaluations and Optimizations`)* | merged into the Evaluations row |
| **live, 2026-08-10** *(replication)* | ✓ | **Supported** *(identical row set, identical cells)* | merged into the Evaluations row |

The live page also states "AgentCore provides **three** AWS PrivateLink endpoints"
and names exactly the three prefixes instrument A enumerated, with the header
**`Primitive`** — not `Service`.

## 6. Findings and classifications

| # | Claim under test | Verdict | Instrument |
|--:|:---|:---|:---|
| 1 | §4.5.3 caveat (b): Gateway has a third, separate PrivateLink endpoint | **CONFIRMED** | A (8/8 regions) |
| 2 | No dedicated Evaluations/Optimization endpoint service exists | **CONFIRMED** (but see the scope note) | A |
| 3 | Matrix rows name *services*; PrivateLink attaches to *prefixes* | **DOC IMPRECISE** | A + B |
| 4 | Evaluations data plane: ❌ no PrivateLink | **AWS BEHAVIOR CHANGED** | B (dated) |
| 5 | Optimization: ❌/❌ no PrivateLink either plane | **DOC REFUTED, change date undetermined** | B |
| 6 | Endpoint-service existence ⇒ feature availability | **CONFIRMED AS A LIMITATION** (of our own instrument) | A (control arm) |

**Finding 1 — caveat (b) confirmed.** A third endpoint service
`com.amazonaws.<region>.bedrock-agentcore.gateway` exists in every region tested,
with a *wildcard* private DNS name (`*.gateway.…`) distinguishing it structurally
from the two plane endpoints. This is the one §4.5 claim that instrument A settles
outright, and it now rests on **public evidence with request IDs** rather than on
the Accelerator. It is a direct **release-gate win** for that caveat.

**Finding 2 — confirmed, with its scope stated.** Zero services matching `evaluat`
or `agentcore-optimi` exist among 300–617 services per region. But this shows only
that no endpoint service is **named** for these primitives. It does **not** show
they are unreachable over PrivateLink, for the reason given in §2. Reachability is
F5-7b (Phase 6b), which requires a VPC and an endpoint.

**Finding 3 — the matrix is imprecise, not wrong.** Our column header is `Service`
while our rows name primitives, and there is no `Policy` or `Memory` endpoint
service to find. A reader who checks the matrix by enumerating endpoint services —
exactly what §5.3 BP#6 invites — finds three names that match none of the eight
row labels and cannot tell whether that means "unsupported" or "shares an
endpoint". AWS's own page avoids this by heading the column **`Primitive`** and
listing the three prefixes immediately above the table. **This is DC-1's shape
again: the statement is right, and the omission is what makes it unusable.**

**Finding 4 — AWS behavior changed; our document was accurate when written.** This
is the substantive result. On five dated snapshots spanning 2026-04-12 to
2026-07-14, AWS's own page said Evaluations' data plane was **"Not yet supported"**
— the same claim our §4.5.3 makes and attributes to the Accelerator. Today the
same URL says **"Supported"**. So:

- our document is **not** a doc-error: it agreed with AWS's public documentation
  for at least the three months preceding it;
- the claim has **expired**, and the phrase "no PrivateLink **today**" in §4.5.3
  was doing real work — the row was always time-bounded, and the document never
  gave the reader a date to bound it with;
- the correct amendment is a **dated** support statement plus a pointer to the
  live AWS table, not a silent flip of two glyphs.

**Finding 5 — refuted, but the change date cannot be established.** Our
Optimization row (❌/❌) has **no counterpart on AWS's page at any observed
timestamp**: the 2026-04→07 snapshots carry seven rows and none of them mentions
Optimization. AWS was *silent*, not contradictory. Silence is compatible with both
"unsupported then, supported now" and "supported all along, merely undocumented",
and instrument B cannot separate them. So the verdict is deliberately weaker than
finding 4's: **the claim is refuted by the live page; the date it became false is
undetermined.** Asserting `AWS_BEHAVIOR_CHANGED` here would be inferring a
transition from the absence of evidence.

**Finding 6 — a limitation of our own instrument, confirmed by the control arm.**
All three endpoint services exist in all three control regions — regions the
document lists as **not** supporting guardrails-in-policy. Endpoint-service
existence therefore carries **no information** about feature availability. This is
why instrument B exists, and it is a standing caveat on any future test that tries
to infer availability from `DescribeVpcEndpointServices`. Had the control arm been
omitted, findings 1 and 2 would have looked like availability evidence.

## 7. The replication, and what it does and does not license

The plan's Part 6 sets a burden of proof before the document is edited: *pre-registered
n met, **reproduced on ≥ 2 separate calendar days**, raw evidence with request IDs
archived, and an alternative-explanation register.* **All four are now met.**

The reproduction requirement was never a formality for this finding in particular:
findings 4 and 5 rest on a documentation page whose content is exactly the thing
observed to change, and a single read cannot distinguish a durable change from a
transient publication state or a CDN-cached variant.

### The replication, as run

| | Day 1 | Day 2 |
|:---|:---|:---|
| Run id | `r20260809T094500Z` | `r20260810T002001Z` |
| UTC calendar day *(from `t_start_utc`)* | 2026-08-09 | 2026-08-10 |
| `ec2:DescribeVpcEndpointServices` calls | 16, all 200 | 16, all 200 |
| AgentCore endpoint services, all 8 regions | 3 / 3 / 3 | 3 / 3 / 3 |
| `evaluat` and `agentcore-optimi` hits over the full service list | 0 in every region | 0 in every region |
| Live page support table | `Evaluations and Optimizations · Supported · Supported` | identical |

The comparison is mechanical, not editorial: `07a_compare_runs.py` flattens every
observation the §4.5.3 amendment quotes into named fields and compares them one by
one. **75 fields compared, 0 disagreements** — 69 must-match observations (the six
verdicts, the endpoint enumeration and its per-region details, the live page's rows)
plus 6 archived snapshots present on both days and parsing identically.

Two design points in that comparator are what make the green light meaningful:

- **The dates are derived, not declared.** Both this finding and the comparator read
  `t_start_utc` out of the evidence records. A run id spelling `r20260810…` proves
  nothing; `claims/tests/test_amendment_gate.py::test_the_run_id_is_not_trusted_for_the_date`
  pins that. The first attempt at day 2 was in fact rejected as a same-day repeat —
  the local calendar had rolled to the 10th while UTC was still 2026-08-09T16:20.
- **Request IDs and CDX result sets are `MAY_VARY`, and are reported rather than
  compared.** Two snapshots the Internet Archive returned on day 1 (`20251230114157`,
  `20260623161005`) were not returned on day 2. That is a property of a third-party
  index queried twice, not an observation about AWS, so it is a note and not a
  disagreement — and the six snapshots present both days parsed identically, which is
  the check that actually bears on instrument B's reliability. Had a *shared* snapshot
  parsed differently, that would have been fatal: an archived page is immutable, so a
  differing parse would mean one of the two parses is wrong.

### Two day-2 runs, and which one is canonical

Day 2 was collected **twice**, 8 minutes 46 seconds apart, and this is recorded rather
than tidied away because the choice between them is exactly the kind of choice that can
launder a result.

| | `r20260810T001115Z` | `r20260810T002001Z` |
|:---|:---|:---|
| Started (`t_start_utc`) | 00:11:16Z | 00:20:01Z |
| Origin | manual — I ran `07a_run_day2.sh` by hand | the unattended job **pre-registered in DEV-SEAL-10 for 00:20Z** |
| `DescribeVpcEndpointServices` | 16, all 200 | 16, all 200 |
| CDX snapshots returned | 6 | 6, the same 6 |
| Snapshots reading `Not yet supported` | 4 | the same 4 |
| Compared against day 1 | 75 fields, 0 disagreements | 75 fields, 0 disagreements |

The manual run took the script's *"UTC today already differs from day 1 — running now"*
branch and so did not sleep; the scheduled job then fired on its own timer. Both
replicate independently and both are kept: **neither is deleted**, per DEV-SEAL-10's own
rule that a repeat which agrees is weak evidence but a repeat *relabelled* as a
replication is false evidence.

**`r20260810T002001Z` is canonical**, on one ground only — it was fixed in DEV-SEAL-10
**before any day-2 result existed**, so naming it cannot be a choice among outcomes. Had
I made my own later run canonical, the selection would have been made with the results
already in hand, and no reader could tell that from the artifact. The two agree on every
field, so nothing in findings 4 or 5 turns on the choice; what turns on it is whether the
selection rule was fixed in advance.

Comparing the two day-2 runs **to each other** correctly returns NOT REPLICATED —
*"both runs were collected on 2026-08-10"* — while reporting 75 fields compared and 0
substantive disagreements. That is the comparator behaving as designed: they are a
same-day repeat of one another, and a same-day repeat is what the rule exists to reject.
`atq`, `crontab -l` and `launchctl list` show nothing further pending.

### Alternative-explanation register

| Alternative explanation for findings 4/5 | Status |
|:---|:---|
| Our filter or parser missed a support row | Excluded — the parser was mutation-checked against snapshots with **no** table (correctly reported absent) and with a 7-row table (all 7 extracted); raw HTML archived for re-parse. |
| The live page is a stale or A/B-tested CDN variant | **Excluded for a gross transient** — the same rows were served on two calendar days ~14h apart, from two independent fetches. A variant persisting across both reads is not excluded, and cannot be by this instrument; that residual is what F5-7b addresses. |
| The Wayback snapshots are rewritten or incomplete | Excluded further — 5 independent timestamps across 3 months agree, `collapse=digest` returns change points so agreement spans distinct content hashes, and the 6 snapshots returned on both days parsed identically on both. |
| "Supported" on AWS's page overstates reality (doc ahead of service) | **NOT excluded by any read-only instrument, and replication does not touch it.** Two reads of a page cannot test the service behind it. Settled only by F5-7b: an actual call over an endpoint from inside a VPC. |
| The Accelerator v2.9 and the public page describe different scopes | Open. Plausible for finding 5 (Accelerator has an Optimization row, AWS's page never did); unresolvable without the Accelerator's own date. |

**What the amendment is therefore entitled to say.** That AWS's public documentation
states support, dated, with a pointer to the live table — not that PrivateLink support
is functionally present. Those are different claims, and the second one remains
unmeasured. The proposed wording in §8 is written to the first.

## 8. Carry-forward

**For the v1.3 amendment — unblocked as of 2026-08-10:**
1. §4.5.3 — retitle the column `Primitive`, list the three endpoint prefixes above
   the table, and map each primitive to its prefix. Fixes finding 3.
2. §4.5.3 — replace the Evaluations and Optimization rows with a **dated**
   statement ("as of 2026-08-10 AWS **documents** all primitives as supported on both
   planes, verified on two calendar days; verify against the live table before designing
   a closed loop") and mark *measured, see VALIDATION-F5-7a*. Fixes findings 4 and 5.
   The verb is **documents**, not *supports*: what was replicated is AWS's published
   statement, and the register above records that "the doc is ahead of the service" is
   not excluded by any read-only instrument.
3. §5.3 BP#6 — the instruction to **defer** the closed loop's AFTER phase is the
   consequential one and must be amended with the row, not left behind. Per
   `feedback_grep_the_claim_not_the_phrasing`, all `sites[]` for this claim get
   updated, not just §4.5.3.
4. `AWS-BEHAVIOR-CHANGES.md` — first entry: Evaluations data-plane PrivateLink,
   documented "Not yet supported" ≤ 2026-07-14, "Supported" ≥ 2026-08-09.
5. Both `.md` and `.zh-TW.md` in the same change.

**For the release gate.** Caveat (b) (finding 1) is now backed by our own public
evidence and no longer needs the Accelerator citation. The PrivateLink matrix rows
themselves are superseded by AWS's **public** page, which removes the NDA
dependency for that table entirely — a better outcome than downgrading it to
"confirm with your AWS account team". Caveat (a) is **untested here** and still
carries the citation; AWS's public page states the same `Principal: *` requirement,
so it can be re-cited publicly without an experiment.

**For the platform.** `lib/evidence.py` had its first live exercise here (16/16
calls captured with request IDs) and gained 17 offline unit tests. One real defect
was found and fixed by those tests: `Record.path` used `relative_to(ROOT)`, which
raised for any evidence store rooted outside the project tree.
