# FINDING F1-3 — The `permit` statement our own document tells readers to write does not create

**Status:** REPLICATED ON TWO CALENDAR DAYS · **READY TO AMEND** (see §8)
**Dates:** day 1 **2026-08-10** (4 runs), day 2 **2026-08-11** (1 run) — UTC, derived from `t_start_utc` in the records, never asserted here
**Script:** `f1_config/03_permit_trap.py` · offline mutation suite `f1_config/tests/test_f1_3_offline_mutations.py`
**Run id:** `r20260810T130945Z` (adopted from the ledger, not minted — see §6)
**Raw evidence:** `evidence/r20260810T130945Z/f1/F1-3/` (57 records, all 57 carrying `x-amzn-requestid`; 25 create mutations, 32 deletes)
**Analysis record:** `results/phase1/F1-3.json`
**Pre-registration seal in force:** `6eb1ba6e09d4…3923e8e4`
**Cost: $0.00.** Control-plane only: 5 × (1 `CreatePolicyEngine` + 4 `CreatePolicy` + polls + 4 `DeletePolicy` + `DeletePolicyEngine`), the `DeletePolicyEngine` retried 1–2 times per run (§4.2). No text units, no model invocation. Every resource created was deleted in the same run's `finally`.
**Document under test:** §3.1, §7.2, §8 — all three instruct the reader to add the same statement.
**Class:** C (config-surface). Family `descriptive_no_test` — a deterministic validator outcome, no p-value, no multiplicity correction (pre-registered; `planned_n` is null).

<!-- provenance
{
  "status": "READY_TO_AMEND",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F1-3"],
  "was_blocked_on": "A replication of 03_permit_trap.py on a UTC calendar day after 2026-08-10. The conflict-resolution protocol requires >=2 separate days before the document is amended, and the first four runs all fell on 2026-08-10Z. What one day cannot exclude is a transient state of the service-side policy validator: the finding rests on a validator VERDICT (two Overly Permissive findings) and a validator is exactly the kind of component whose ruleset can change or be rolled out regionally between days. n was never the issue — the arms agreed perfectly four times over — the issue was that all four observations shared a single opportunity to have been wrong together. DISCHARGED 2026-08-11T00:08:18Z: a fifth run on the following UTC day reproduced all four arms bit for bit (request ids in §4), so the gate now derives ['2026-08-10', '2026-08-11'] from t_start_utc across the run directory.",
  "amends": ["S3.1", "S7.2", "S8"]
}
-->
<!-- The block above is what check_amendment_readiness.py reads. It declares the run, not
     the date: dates are derived from t_start_utc in the records, so this finding cannot
     assert its own replication. Promoting this to READY_TO_AMEND without a second day's
     records under a declared run id makes the gate FAIL, which is the intended behaviour —
     the status is not a knob for getting the amendment through. The promotion made here is
     therefore safe to write by hand: the gate re-derives 2026-08-10 and 2026-08-11 from the
     records under this run id and would refuse the status if either day were absent.

     `was_blocked_on`, not `blocked_on`, for the same reason as FINDING-F5-7A: the key is
     renamed rather than deleted so the condition that gated the amendment stays legible
     beside the evidence that discharged it, while the gate's DEFERRED_STATUSES branch —
     which requires a live `blocked_on` — no longer matches a finding that is no longer
     deferred.

     One thing this run id does NOT record, and it is worth stating: both days' records live
     under the SAME directory, because the run id is adopted from the ledger (§6). The two
     days are separable only because `lib/evidence._highest_seq` resumes the sequence above
     the highest number on disk instead of restarting at 0001 — the platform fix §6 describes.
     Without it the day-2 run would have overwritten day 1 and this promotion would have been
     unearnable. -->

---

## 1. What the document says

Three sections give the reader the same instruction. §3.1 (Gateway policy setup), §7.2
(the worked example) and §8 (the deployment checklist) each tell them to add:

```cedar
permit(principal, action, resource is AgentCore::Gateway);
```

**None of the three mentions `validationMode`.** The AWS getting-started page for the same
statement passes `--validation-mode IGNORE_ALL_FINDINGS`; our document does not mention that
the parameter exists.

## 2. What the sealed oracle asks

Fixed in `PREREGISTRATION.yaml` before any data:

> TRUE if `CreatePolicy` with `permit(principal, action, resource is AgentCore::Gateway);`
> and no `validationMode` reaches `CREATE_FAILED` with an Overly Permissive finding;
> FALSE if it reaches a usable state.

Two conditions, checked separately: the arm must fail **and** its `statusReasons` must be
about over-permissiveness. A `CREATE_FAILED` from a syntax error or a throttle would satisfy
a bare "did it fail?" test while measuring nothing about the claim — that path exits 1 as
INCONCLUSIVE with the reason text recorded, and it is exercised offline (scenario M4).

## 3. Design: one independent variable, four arms, one fresh engine

| arm | `validationMode` | statement | role |
|:--|:--|:--|:--|
| **A** `default` | *omitted* | bare permit | **the claim** — the document executed literally |
| **B** `failfind` | `FAIL_ON_ANY_FINDINGS` | bare permit | the documented default, stated |
| **C** `ignorefind` | `IGNORE_ALL_FINDINGS` | bare permit | **the mutation** — is the finding gate the cause? |
| **D** `narrow` | *omitted* | scoped principal + real gateway ARN | **the control** |

A is omitted rather than set to `FAIL_ON_ANY_FINDINGS` because "omitted" and "explicitly
defaulted" are different requests, and only the first is what a reader following §3.1
produces. B decides whether they are the same request in effect.

**D is part of the verdict rule, not a sanity check.** Without it, A's failure is equally
consistent with "this engine rejects everything" — the alternative explanation a paired
design eliminates by construction. The script therefore **refuses to run** without a real
gateway ARN and caller role: `cedar.gateway_resource(None)` returns
`resource is AgentCore::Gateway`, which *is* the baseline, so a permissive fallback would
silently make the control a second copy of the treatment, both arms would fail, and the pair
would read as "even the narrow policy is rejected" — the exact wrong conclusion, reached by a
design that looked complete.

A **fresh** engine each run. Phase 2 saw this once while provisioning (`dc1_reproduced: true`
in the ledger), and that sighting is deliberately **not** the result: it was uncontrolled,
has no comparison arm, and the engine it ran on now holds a live baseline policy — the
validator is documented to reason about the policy *set*, so policy count is an uncontrolled
variable there.

## 4. Result — verdict TRUE, five times, on two calendar days

| arm | mode | HTTP | `status` at accept | settled | Overly Permissive | usable |
|:--|:--|:--:|:--|:--|:--:|:--:|
| A `default` | *omitted* | **202** | `CREATING` | **`CREATE_FAILED`** | **yes** (2 reasons) | no |
| B `failfind` | `FAIL_ON_ANY_FINDINGS` | 202 | `CREATING` | `CREATE_FAILED` | yes (2 reasons) | no |
| C `ignorefind` | `IGNORE_ALL_FINDINGS` | 202 | `CREATING` | **`ACTIVE`** | — | yes |
| D `narrow` | *omitted* | 202 | `CREATING` | **`ACTIVE`** | — | yes |

- **Mutation inverted** (C reached `ACTIVE` on the *identical* statement) → the finding gate
  is established as the cause, which is what licenses the remedy in §7.
- **A and B agree** → the service default *is* fail-on-findings. The document's silence is a
  documentation gap, not surprising service behaviour. That distinction sets the shape of the
  amendment: *state the default and the remedy*, rather than *describe a trap*.
- **D reached `ACTIVE` under A's exact condition** → A's failure is attributable to
  over-permissiveness, not to the engine, the account, the region or the day.
- `local_amendment_blockers` is **empty**.

The two verbatim reasons, identical on A and B and on all five runs, across both days:

> `Overly Permissive: Policy Engine will allow every request for the specified principal (AgentCore::IamEntity), action (Any Future Tools) and resource (gateway/*) combination if the policy is added or updated`
> `Overly Permissive: Policy Engine will appear for the specified principal (AgentCore::OAuthUser) …`

— the second differs from the first only in the principal type. **The validator reports one
finding per principal type it can enumerate** (`AgentCore::IamEntity`, `AgentCore::OAuthUser`),
which is why an unconstrained `principal` produces exactly two.

Sample request ids (all in `summary.json`): `8adf3af9-a050-432e-b0a8-4814252c49ea` (A, run 1),
`6770f85e-6d1d-4656-9666-fd52aaf84ec1` (B), `5d8b881e-ea44-440e-bf3e-e351dc768d3d` (C),
`91dba0e4-4de6-40ba-9572-cf0d4e68f975` (D); run 3's A is `7b019c9d-0c9a-41ac-bac5-b6a0fa1bb69d`.

**Day 2 (run 5), the four arms in order** — `2026-08-11T00:08:18Z` engine
`5ae45823-88bb-4f7a-b963-3a4d746acad1`, then A `3295a104-c42a-4edf-9e12-38d14328236d`,
B `8ce5feec-6cdd-42df-8598-54be2546ae1a`, C `21aa50ea-99fe-448a-baa9-236b704ebb07`,
D `90e36e47-efbb-4da8-9593-8fb8228828fd`. The table above is the day-2 table unchanged: same
HTTP 202, same `CREATING` at accept, same settled `CREATE_FAILED` on A and B with the same two
reasons byte for byte, same `ACTIVE` on C and D. Records `0262`–`0273` in the run directory.

**What day 2 excludes, precisely.** Only the alternative §5's last row names: a one-off state
of the service-side validator. It adds nothing to the sample-size argument (there was never a
rate to estimate) and it does not extend the finding to another region or another account —
every one of the five runs is `us-east-1` in one account. A validator ruleset that changed
*between* the two days would have shown as a disagreement on A; it did not.

### 4.1 A second, unplanned finding: `CreatePolicy` returns **202**, not 200

The plan and the first draft of the harness both assumed HTTP 200. The measurement is **202
Accepted**, on every `CreatePolicy` and `CreatePolicyEngine` across all five runs — 25 create
calls, 25 × 202, zero 200s. `DeletePolicy` and `DeletePolicyEngine` also return **202**
(20 + 5 successes); the only non-2xx in the whole run directory is the `409 ConflictException`
of §4.2. So no call this case makes returns 200 at all, and a harness asserting `== 200` would
have failed on every one of the 57 records rather than on some.

This *strengthens* the operational point rather than weakening it. 202 is the correct
semantics for an asynchronously-settled create, and it is a machine-readable signal that the
work is not finished — but it is still a **2xx**: a reader who checks `response.ok`, or who
simply gets no exception, sees success. The policy is in `CREATE_FAILED` and nothing at the
call site says so. The failure is visible only in a `status` field the document never tells
them to read.

The record's field names were renamed `status_at_http_200` → **`status_at_accept`** rather
than left as-is: a field named for a status code that the service does not return is a label
that disagrees with its own value.

### 4.2 Recorded, not tested here

`enforcementMode` settled `ACTIVE` on **all four** arms of **all five** runs — including the
two that failed validation. It is a *second* parameter §3.1 never mentions, and what the
service defaults it to is F4's subject, not this case's. Recorded for F4 as a same-engine
reference point.

Also, and **re-measured after this section first over-claimed it**: `DeletePolicyEngine`
returned `409 ConflictException` on the **first** attempt in **all five** runs, seconds after
every `DeletePolicy` had returned 202, and needed **1–2 retries** to succeed — one retry in
runs 1–3, **two** in runs 4 and 5. Twelve `DeletePolicyEngine` calls in total: 7 × 409,
5 × 202. The earlier text here read "succeeded on the retry" on the strength of three runs,
which the fourth falsified; the claim is now stated as the measured range and the per-run
counts are derivable from `t_start_utc` in records `0010`/`0011`, `0237`/`0238`,
`0248`/`0249`, `0259`–`0261`, `0271`–`0273`.

That is a teardown-reliability fact worth stating, and the correction sharpens it rather than
softening it: `DeletePolicy` releases its hold asynchronously with **no bounded delay we have
observed a ceiling for**, so a teardown that treats the first `ConflictException` as fatal
leaks engines, and one that retries exactly once would have leaked on 2 of 5 runs. The harness
retries up to 5 times at 3.3 s spacing; the largest observed requirement is 2.

## 5. Alternative explanations, and what excludes each

| alternative | excluded by |
|:---|:---|
| the engine rejects every policy | **arm D** reached `ACTIVE` on the same engine, same day, mode also omitted |
| the statement is malformed Cedar | **arm C** reached `ACTIVE` on the byte-identical statement |
| a throttle or transport error misread as a validation failure | the classifier requires over-permissiveness in `statusReasons`; an unmatched failure exits 1 as INCONCLUSIVE (M4) |
| the harness mislabelled which arm ran under which mode | `validationMode` is on exactly 2 member paths in the whole API (`CreatePolicy:in`, `UpdatePolicy:in`) and in **no** output shape, so it cannot be read back — see §7 limitation |
| policy-set contamination from a prior policy | a **fresh** engine per run; A is the first policy created on it |
| a one-off validator state | **excluded 2026-08-11**: run 5 on the next UTC day reproduced all four arms and both reason strings byte for byte (§4, §8) |
| the finding is specific to this region or account | **NOT excluded**, and not claimed: all five runs are `us-east-1` in one account (§7) |

## 6. Why this joins the ledger's run id

The run id and `ExpiresAt` are adopted from `state.json`. One testbed must be one ledger:
`State.load_or_new` raises on a run-id mismatch precisely so two ids cannot split the `RunId`
tag across resources and leave half of them invisible to a teardown sweep. Adopting the id
costs nothing for the replication rule, which counts days from `t_start_utc` in the records
rather than from a directory name.

That adoption is also what forced a platform fix this session: `EvidenceStore` restarted its
sequence at `0001` per run, so a Day-2 replication into the adopted directory would have
**overwritten Day 1's records** — deleting the very evidence the replication gate derives its
day count from, so the run that earned the amendment would have revoked it. The sequence now
resumes above the highest number on disk (`lib/evidence._highest_seq`), with the regression
mutation-checked in `lib/tests/test_evidence.py`.

## 7. What TRUE does and does not license

**Does.** All three sites — §3.1, §7.2, §8 — need amending, together. Per
`feedback_grep_the_claim_not_the_phrasing` a claim corrected at one of three sites is not
corrected; the `sites` column of `claims/triage.csv` is the checklist. The remedy, supported by the inverting
mutation:

> The statement as written will be rejected as Overly Permissive under the service default
> (`FAIL_ON_ANY_FINDINGS`). Either scope it to a concrete principal and gateway, or pass
> `validationMode=IGNORE_ALL_FINDINGS` deliberately and record why. Note that `CreatePolicy`
> returns **202 Accepted** with a `policyId` either way: the rejection appears only in the
> policy's settled `status`, which must be polled.

**Does not.** This is not a finding that the statement is invalid Cedar, nor that AWS is
wrong to reject it — refusing an unconstrained `permit` is defensible service behaviour, and
arguably good. The defect is **documentary**: our document tells readers to send it and does
not tell them what happens. Nor does it license any claim about `enforcementMode` (§4.2), or
about behaviour in another region: every observation is `us-east-1`.

**A provenance limitation, recorded rather than papered over.** `GetPolicy`'s output shape is
`policyId, name, policyEngineId, createdAt, updatedAt, policyArn, status, enforcementMode,
definition, description, statusReasons` — no `validationMode`. No response can confirm which
mode an arm ran under; the label is carried by the harness and by the request parameters in
the evidence store.

## 8. What was blocking the amendment, and what discharged it

**A second UTC calendar day.** The first four runs were all 2026-08-10Z. The protocol's
≥2-separate-days rule was never about sample size — the arms agreed perfectly, four times — it
is about those observations sharing one opportunity to be wrong together. The finding rests on
a service-side *validator verdict*, and a validator's ruleset is exactly the kind of thing that
can change, or be rolled out regionally, between days.

**Discharged 2026-08-11T00:08:18Z.** A fifth run of `f1_config/03_permit_trap.py`, unchanged,
75 seconds, $0. It reproduced every arm (§4, day-2 request ids) and both reason strings byte
for byte. `check_amendment_readiness.py` now derives `['2026-08-10', '2026-08-11']` from
`t_start_utc` across the run directory and reports the finding `READY_TO_AMEND` — a derivation,
not a declaration: the status in the provenance block would fail the gate if either day's
records were missing.

**What remains before the text lands in v1.3** is authoring, not evidence: the amendment must
be written into **all three** sites (§3.1, §7.2, §8) in **both** language files in the same
change, per §7 and `feedback_bilingual_readme_sync`. That is Phase 9 work and is tracked there.
The one thing this finding still does not license is any statement beyond `us-east-1` and this
account (§5, §7).

## 9. Provenance of the harness itself

Nine offline scenarios drive `main()` end-to-end against a fake control-plane client before
any live call: the baseline, the document being right (M1), the control also failing (M2), the
mutation not inverting (M3), an unrelated failure cause (M4), a synchronous rejection (M5), an
engine that never becomes `ACTIVE` (M6), an engine create refused (M7), and an arm that never
settles (M8). Each asserts the verdict, the exit code and `mutation.inverted`.

Two real defects came out of that suite rather than out of a live run:

1. **M3** showed that the docstring's claim that the mutation "gates the amendment" was
   unenforced prose — `check_amendment_readiness.py` reads provenance blocks and replication
   days, never case payloads, and `O.amendment_blockers` returns `[]` for F1-3. A
   non-inverting mutation would have published as TRUE with nothing recording that the remedy
   had lost its support. Fixed by computing `local_amendment_blockers` **as data** in the
   record and printing them to stderr. The seal is *not* overridden from inside the script:
   `mutation_is_mandatory("F1-3")` is False, and a harness that overrode its own seal would
   be deciding its own question.
2. **M1** showed `mutation.inverted` was computed as "arm C succeeded" — reporting
   `inverted: true` for a run in which *every* arm succeeded and nothing was inverted.
   "Inverted" is a claim about a pair; it is now `None` when arm A did not fail.

The suite also caused one defect, recorded here because the fix is now a platform guard. As a
`/tmp` script it wrote **221 fabricated call records** (invented request ids `rq-dflt`, HTTP
200) into `evidence/r20260810T130945Z/f1/F1-3/`, because `main()` builds its own
`EvidenceStore` and the script never redirected the root. It patched the *analysis* writer, so
no fake verdict was ever published — but `check_amendment_readiness.py` derives replication
days from `t_start_utc` across **every** record in the run directory, so fabricated calls were
one calendar day away from counting toward an amendment. The pytest write guard could not see
it: a plain `python3` script is not a test.

Three things changed as a result. The 221 records are quarantined under
`evidence/quarantine/f1_3_offline_mutation_20260810/`. `lib/evidence.capture` now **refuses**
to file a non-botocore client's call into the published tree at all — testing
`isinstance(client, BaseClient)`, because the fake deliberately borrows a *real* `client.meta`
so `check_name` reads the genuine name grammar, which means a meta-type check would have
acquitted the one client known to have fabricated records. And the harness is now a pytest
module passing `--evidence-root`, so the refusal is exercised by every scenario instead of
being trusted.
