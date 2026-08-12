# FINDING F5-1/R — Removing the IAM grant does not close the path, and observing the denial does not mean it has closed

**Status:** **READY TO AMEND** — replicated on two UTC calendar days; the post-restore executions reproduced, and the second day added an observation in the opposite direction (see §7)
**Dates:** **2026-08-11** and **2026-08-12** (UTC, derived from `t_start_utc` across the 557 stamped evidence records — 354 on the first day, 203 on the second — never asserted here)
**Script:** `f5_redteam/01_route1_direct_invoke.py` (`_wait_for_effect`, `data_plane_reconvergence`) · offline suite `f5_redteam/tests/test_route1_direct_invoke.py` (43 tests)
**Run id:** `r20260810T130945Z` (adopted from the ledger, not minted)
**Raw evidence:** `evidence/r20260810T130945Z/f5/F5-1/` — 559 files, of which **557 are call records and all 557 carry a `request_id`**: 518 `lambda:Invoke`, 21 `ListRolePolicies`, 6 `PutRolePolicy`, 6 `DeleteRolePolicy`, 6 `GetPolicy`. The two remaining files are the directory's own `analysis.json` and `summary.json`, which carry no `t_start_utc` and so contribute no observation day.
**Set-aside arms:** `results/checkpoints/F5-1__restored_reassert__flapped_revoke_archive.json`, `…__earlier_replicate_archive.json`, and the three `…__day1_2026-08-11_archive.json` checkpoints set aside so the second day's arms were actually re-sent — index files; every row's request and response stays in the evidence tree
**Analysis record:** `results/phase1/F5-1.json` (`data_plane_reconvergence`), day 1 archived byte-identical at `results/phase1/archive/F5-1__day1_2026-08-11.json`
**Pre-registration seal in force:** `a2136a9d3dbb…fa74cf1a`
**Cost: under $0.02 for both days combined.** 518 Lambda invocations and 39 IAM control-plane calls. No model invocation, no `ApplyGuardrail`, zero text units. Twelve inline-policy mutations across six runs, two per run, each recorded in the ledger before creation; the role was verified back to its shipped configuration after every run, on both days.
**Document under test:** §4.4 route table row 3 (line 404, *"the execution role must NOT include … Least privilege here IS the anti-jailbreak control"*) and row 4 (*"This holds even if route #3's role hygiene regresses"*).
**Class:** C (config-surface), reported as a **descriptive measurement** alongside F5-1's confirmatory verdict. No p-value, no multiplicity correction: four replicates of a propagation window, not a rate against a threshold.

<!-- provenance
{
  "status": "READY_TO_AMEND",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F5-1"],
  "replication": "Discharged 2026-08-12T01:23:01Z..01:35:14Z (the first and last t_start_utc among the 203 records the second day added): a full re-run reproduced the confirmatory verdict (TRUE, 0 of 120, identical Wilson interval and identical exact ceiling) and reproduced the phenomenon this finding is about — 8 of 20 invocations sent after three consecutive AccessDeniedException responses still executed and ran the tool. The second day also moved the one thing §3 said three observations could not settle, and it moved it AGAINST the asymmetry reading: the GRANT direction failed to converge inside its own 300s bound, flapping executed/executed/denied at the end of 29 probes, and the 20-invocation arm sent immediately afterwards executed 20/20. The original condition was: a replication on a UTC calendar day after 2026-08-11.",
  "amends": ["S4.4"]
}
-->
<!-- `blocked_on` is gone because the condition it named was met, not because the status was
     raised past it. `replication` records what discharged it, in the same shape FINDING-F1-3 and
     FINDING-F5-7A use. The gate derives the two days from `t_start_utc` on the evidence records
     whose case_id is F5-1 — this file cannot assert its own replication. -->

## 1. The claim, and what this finding does and does not touch

F5-1's confirmatory question — *can the AgentCore Runtime execution role reach the tool Lambda directly, bypassing the Gateway and its policy engine, in the role's shipped configuration?* — is answered and **not** what this document is about. That answer is **TRUE (no bypass)**: 0 of 120 direct invocations executed, Wilson 99% interval `[0, 0.05865]`, exact one-sided ceiling `0.0414` at α=0.00625, with a mandatory mutation that inverted (20/20 executed once `lambda:InvokeFunction` was granted, all 20 echoing our marker). The document's route-3 advice is confirmed on that point.

This finding is about the **remedy**, which the document states as a property (*"Least privilege here IS the anti-jailbreak control"*) and which an operator necessarily reads as an action: if the role has too much, take it away. Measured here: taking it away does not close the path when the API call returns, and — the part that is not obvious and is the reason this is a finding rather than a footnote — **it does not close the path when you check and see a denial either.**

## 2. What was measured

Four replicates over two UTC days. Each: grant `lambda:InvokeFunction` as an inline policy on the runtime execution role, confirm the grant is effective by polling, invoke 20 times (all 20 executed, every replicate), `DeleteRolePolicy`, poll until the denial is observed, then send 20 more invocations.

| # | day | rule that ended the revoke wait | denial observed after | of the next 20 invocations, **executed** |
|---|---|---|---|---|
| 1 | 2026-08-11 | 1 confirming probe | 31.2s | **9** |
| 2 | 2026-08-11 | 3 consecutive probes | 248.5s | **4** |
| 3 | 2026-08-11 | 3 consecutive probes | 41.4s | **11** |
| 4 | **2026-08-12** | 3 consecutive probes | 62.8s (first denial at 41.7s) | **8** |

**32 of 80 invocations sent after a denial had been observed still executed and ran the tool.** In the third replicate — three consecutive `AccessDeniedException` responses spanning 20 seconds — **11 of 20** subsequent invocations executed; in the fourth, on a different UTC day, three consecutive denials held for 21.1s and **8 of 20** subsequent invocations executed.

Two runs are absent from the table because they sent nothing: `restored_reassert` was already checkpointed and a checkpointed arm is served from disk. That is also why replicates 1 and 2 had to be set aside for 3 to be taken, and why all three of the first day's checkpoints were set aside before the second day's run; every one is archived with its provenance, and replicate 2 is archived as a **valid replicate**, not a defect (see §6).

The **grant** direction is no longer a clean contrast, and that is the second day's own contribution — see §4.1. Across the first day's five attempts it converged every time: 288.3s and 21.6s under the one-probe rule, then 114.5s, 32.1s and 31.9s under three consecutive confirmations. On the second day it did not converge at all.

## 3. What is NOT claimed

- **No dose-response.** 31.2s→9, 248.5s→4, 41.4s→11, 62.8s→8 is not a monotone relationship, and with four points it would be dishonest to draw one. The waiting rule that ended each replicate is a property of *our instrument*, not of the fleet's state, and the fleet state at the moment of each probe is unobservable to us.
- **No asymmetry between grant and revoke** — and the second day is now the strongest evidence *for* that refusal rather than merely an absence of evidence. §4.1 records a grant that never converged inside 300s while the path was in fact open. Four-and-six observations do not separate two distributions, and the one day that tested the grant direction hardest put it on the wrong side of the reading a cautious operator would have drawn from day 1 alone.
- **No between-day effect either.** 8 of 20 on the second day sits inside the first day's 4–11 spread, so nothing here supports "IAM was slow on 2026-08-11". Two days is enough to say the phenomenon is not one day's weather; it is not enough to model a distribution over days.
- **No number to design against.** Nothing here supports "wait N seconds after revoking". The one thing the data does rule out is the rule an engineer would most naturally write: *poll until you see the deny, then proceed.*

## 4. The fourth run: not reached inside 300s, and yet converged

A fourth run held the revoke wait for **308.8s** and never observed three consecutive denials (it stopped at two). It re-sent no invocations, so it contributes no row to §2 — but its published record carries the honest `reached: false` and the note that any arm below it describes an unsettled configuration.

An **independent 12-probe check**, run after that process had exited and before the next run was launched — between roughly 20 and 40 minutes after its `DeleteRolePolicy` returned — came back **12/12 denied**. So the state does converge; 300s was the wrong ruler for this direction, not evidence of a permanent hole.

That check has a defect worth naming: it did not stamp its own start time, so the interval above is bounded from the surrounding logs' mtimes rather than measured. The day-2 replicate (§7) records its own timestamps.

### 4.1 The second day, in the other direction: a poll that reported "not effective" about a path that was open

The second day's run reproduced the revoke-side observation and then produced its mirror image, which the first day's five grant-direction attempts had given no hint of.

`PutRolePolicy` returned 200. The grant poll then ran **29 probes over 300.6s** and its recorded `outcomes_seen` is:

> 26 × `denied_by_iam`, then `executed`, `executed`, `denied_by_iam` — and the 300s bound expired.

So the grant took roughly 270s to have any effect at all, and then **went back to denied**: the boundary served three different answers inside the last 30 seconds of the wait. The poll therefore recorded `reached: false` and the honest note that *"the arm below ran against an IAM state that was never confirmed to have settled within 300s"*.

The arm below it — sent immediately, with no further waiting — **executed 20 of 20 and echoed our marker on all 20.**

Two things follow, and only the second is new:

1. The mandatory mutation still inverted, so the closed arm's 120 denials are about a reachable target on the second day as well. Nothing about the verdict is weakened by an unconverged poll in the permissive direction.
2. **The instrument misleads in both directions, symmetrically.** An operator who removes a permission and polls until denied can conclude *closed* while the path is intermittently open — that is §2. An operator who adds a permission and polls until it works can conclude *not effective* while the path is already open — that is this. Both errors come from the same fact: IAM authorization is evaluated per request against an eventually-consistent view, and any finite number of probes samples that view rather than establishing it. `flapped_before_converging` is recorded as `null` rather than `false` for this poll, because the field is only computed on the branch that converges; the flap is in `outcomes_seen`, which is why the whole probe sequence is published and not just a summary.

This is also why §3's second bullet is written as a refusal rather than a hedge. Read from the first day alone, the natural conclusion is *"the revoke direction is the dangerous one and the grant direction settles in about 30 seconds"*. The second day contradicts the second half of that sentence.

### 4.2 The instrument change

The instrument was changed once as a result, and in the strict direction only: the revoke wait now has its own bound, `PROP_MAX_REVOKE_S = 1800`, separate from the grant's `PROP_MAX_S = 300`. A grant that has not landed costs the run an arm; a revoke that has not landed is a hole in the boundary the testbed is supposed to have restored, so its wait is a safety check and must not be bounded by what a confirmatory arm can afford. `test_the_revoke_direction_gets_a_strictly_longer_bound_than_the_grant` and `test_the_revoke_wait_is_actually_called_with_the_longer_bound` fail if either half of that regresses.

## 5. Why the strict form is published and not required as a guard

F5-1 originally carried one guard, `grant_was_removed_and_denial_reasserted`, that required both the control-plane removal *and* zero executions among the 20 post-restore invocations. That guard was false in every run, which would make F5-1 permanently unpublishable — while the boundary it actually tests is measured cleanly at n=120.

Those are two different questions and are now two guards:

- `grant_was_removed_from_the_role` — **required.** Reads the role's inline policy set back from IAM and compares it to the shipped baseline. This is "was the testbed left as we found it", it is definitive, and it is what the sealed `restore_verification` rule states. A failed read records `None`, which can never equal the baseline, so an unreadable role fails rather than passes.
- `denial_was_reasserted_in_the_data_plane` — **required.** The deny must be observed again at all.
- `strict_form_all_post_restore_invocations_denied` — **published, not required**, under `data_plane_reconvergence` in the record, together with the counts, the probe sequence, the bound in force, and the reason it is not required.

The distinction matters because the weaker-looking move here would have been to relax the *second* guard when it too came back false. It was not relaxed; the bound was lengthened instead, and it then passed on its own terms. Requiring the strict form would be requiring a guarantee IAM does not offer on this timescale, and it would hide the finding inside a failed guard instead of publishing it.

## 6. The label that was wrong, and the correction

Replicate 2's rows were first archived under the label `timed_out_revoke`, attributing them to the fourth run's 308.8s timeout. That was false: the fourth run re-sent nothing. The rows were sent by the third process, whose revoke wait converged legitimately at 248.5s — so they are a **valid measurement** of the arm, in which 4 of 20 invocations executed *after* the arm's precondition was properly established.

Filing a valid replicate as an instrument defect is the same class of error as the defects it was filing: a record whose label does not describe what produced it. It would have cost a real observation, cited nowhere. `f5_redteam/fix_restore_arm_archive_labels.py` corrects it to `earlier_replicate`, carries a `label_correction` block naming the wrong label and how the truth was established, and asserts the trial rows are byte-identical before and after. The archiver now distinguishes two `kind`s — `defect` and `replicate` — and refuses to move any arm with zero executions under either, since a clean arm satisfies the strict form and has nothing left to re-measure.

## 7. Replication — two UTC calendar days

The condition this finding was deferred on, stated on the first day before the second day's data existed, was: *one run on a UTC day after 2026-08-11, with the `restored_reassert` checkpoint set aside first so the arm is actually re-sent.* Run on **2026-08-12T01:23:01Z..01:35:14Z**, with all three of the first day's checkpoints set aside and the first day's analysis record archived byte-identical beforehand.

| | 2026-08-11 | 2026-08-12 | same? |
|---|---|---|---|
| confirmatory verdict | TRUE | TRUE | ✔ |
| closed arm: executed / usable | 0 / 120 | 0 / 120 | ✔ |
| Wilson 99% interval | `[0, 0.05865]` | `[0, 0.05865]` | ✔ |
| exact one-sided ceiling at α=0.00625 | 0.041411 | 0.041411 | ✔ |
| granted arm: executed / marker echoed | 20 / 20 | 20 / 20 | ✔ |
| all five guards | pass | pass | ✔ |
| role restored to its shipped inline set | yes | yes | ✔ |
| seconds to the first denial after revoke | 20.8 | 41.7 | reproduced, ~2× |
| seconds to three consecutive denials | 41.4 | 62.8 | reproduced, ~1.5× |
| post-restore invocations that still executed | **11 / 20** | **8 / 20** | reproduced |
| strict form (all post-restore denied) | false | false | ✔ |
| grant direction: converged inside 300s? | yes, 31.9s | **no** — flapped at the bound | **differs (§4.1)** |
| span corroboration | `NO_INVOKES_IN_WINDOW` | `INSTRUMENT_UNAVAILABLE` | neither is a measurement (§7.1) |

The comparison is derived by reading the two result files, not transcribed: `results/phase1/F5-1.json` against `results/phase1/archive/F5-1__day1_2026-08-11.json`.

What the second day settles: the post-restore executions are not one day's weather, and the revoke window is not a property of 2026-08-11 in us-east-1. What it adds is §4.1 — the same eventual consistency misleads a poll in the permissive direction too, which no amount of repeating the first day's measurement would have found.

### 7.1 What the second day did *not* measure, and why the finding says so

The span corroboration leg produced nothing on either day, for two unrelated reasons, and its record says so both times rather than reporting an absence. On the first day the granted arm was served from a crashed run's checkpoint, so the window bracketed idle time and the leg read `NO_INVOKES_IN_WINDOW`. On the second day 20 invokes really were in the window — and the positive control never ran, because the control's `tools/call` was issued without an MCP session on a gateway that requires one, so the leg read `INSTRUMENT_UNAVAILABLE` after a 303.1s wait.

That defect is **DEV-P4-20**, and it is fixed in the script with two new offline tests (mutation-checked: removing the fix fails exactly those two). It is not being re-measured by re-running this case: the leg cannot move a `ZERO_EVENTS` verdict — the oracle's mention of a span is in the plan, not in the decision rule — and re-running to fill in a corroboration line costs 161 invocations and two mutations. So: **F5-1 has no span-side observation, on either day.** The reason that is tolerable rather than convenient is the direction it cuts. An absent `AuthorizeAction` span for a direct invoke would *corroborate* §4.4 row 3's non-bypassable claim, so the missing leg costs the document a supporting observation, not this finding an argument.

## 8. Amendment candidate (§4.4, drafted, not yet applied)

Add to the route table's row 3, after *"Least privilege here IS the anti-jailbreak control"*:

> **Least privilege is a control on the steady state, not an incident-response action.** Removing an over-broad grant does not close the path when `DeleteRolePolicy` returns, and — measured on 2026-08-11 and reproduced on 2026-08-12 in us-east-1 — it does not close the path when a subsequent call is observed to be denied either: across four replicates on two days, 32 of 80 direct invocations sent after a denial had been observed still executed, including 11 of 20 after three consecutive `AccessDeniedException` responses spanning 20 seconds. The same eventual consistency misleads in the permissive direction: on 2026-08-12 a freshly granted permission was still being denied 26 probes into a 300-second wait, flapped, never satisfied the poll — and the 20 invocations sent immediately afterwards all executed. IAM authorization is evaluated per request against an eventually-consistent view; a finite number of probes samples that view rather than establishing it, in **either** direction. Containment during an incident therefore needs a control that fails closed at the boundary being crossed — disable the function, revoke the session, or block at the gateway — with the IAM change as the durable fix behind it. Do not write a runbook step of the form *"remove the permission, confirm the deny, then proceed"*, and do not write its twin, *"grant the permission, confirm it works, then start"*.

Row 4's *"This holds even if route #3's role hygiene regresses"* stays as written: an SCP or permission boundary is exactly the fail-closed backstop this measurement argues for. The wording that needs care is the implied timeline of *recovering* from a regression, not the backstop itself.

## 9. Cross-references

- `DEVIATIONS.md` → **DEV-P4-15** for the four instrument defects found while getting the first run green (`evaluate` arity, a field silently demoted to `detail` by a `**kwargs` sink, a span window that bracketed idle time across a resume, and the one-probe convergence rule), each with the test that now fails if it regresses.
- `DEVIATIONS.md` → **DEV-P4-20** for the span positive control that never opened an MCP session, which is why §7.1 reports no span-side observation on either day.
- `V13_CANDIDATES.md` → **`V13-14`** for the §4.4 amendment above, at `MEASURED_READY` on two days' evidence. It resolves to **one** site — `C-s4-4-trow-009`, the row-3 cell at document line 404 — named explicitly rather than derived, because both expanders over-reach: `test_cases: [F5-1]` reaches 30 triage rows (27 of them in §4.4, 17 architecture-diagram nodes) and the row's merge group `M-update-gateway-risk` reaches 5, three of which are about alarming on `UpdateGateway` and belong to F5-2. Row 4 (`C-s4-4-trow-010`) is deliberately **not** a site, for the reason in §8.

  Until 2026-08-12 this bullet cited a candidate that did not exist: the register had no §4.4 entry, and an earlier revision of this file upgraded the citation to "now at `MEASURED_READY`" without checking. `grep -n "F5-1\|s4-4" build_v13_candidates.py` returned nothing. It is recorded here rather than quietly fixed because it is this project's own named failure mode — a number or a cross-reference inside a justification string is unverified prose (`feedback_prose_is_not_verified`) — committed in the file that argues for the distinction.
