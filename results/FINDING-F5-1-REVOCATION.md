# FINDING F5-1/R — Removing the IAM grant does not close the path, and observing the denial does not mean it has closed

**Status:** OBSERVATIONS COMPLETE ON ONE UTC DAY · **AMENDMENT DEFERRED** pending a second calendar day (see §7)
**Date:** **2026-08-11** (UTC, derived from `t_start_utc` across the 354 stamped evidence records, never asserted here)
**Script:** `f5_redteam/01_route1_direct_invoke.py` (`_wait_for_effect`, `data_plane_reconvergence`) · offline suite `f5_redteam/tests/test_route1_direct_invoke.py` (41 tests)
**Run id:** `r20260810T130945Z` (adopted from the ledger, not minted)
**Raw evidence:** `evidence/r20260810T130945Z/f5/F5-1/` — 356 records, 354 carrying `request_id`: 322 `lambda:Invoke`, 5 `PutRolePolicy`, 5 `DeleteRolePolicy`, 17 `ListRolePolicies`, 5 `GetPolicy`
**Set-aside arms:** `results/checkpoints/F5-1__restored_reassert__flapped_revoke_archive.json`, `…__earlier_replicate_archive.json` — index files; every row's request and response stays in the evidence tree
**Analysis record:** `results/phase1/F5-1.json` (`data_plane_reconvergence`)
**Pre-registration seal in force:** `a2136a9d3dbb…fa74cf1a`
**Cost: under $0.01.** 322 Lambda invocations and 32 IAM control-plane calls. No model invocation, no `ApplyGuardrail`, zero text units. Ten inline-policy mutations across five runs, two per run, each recorded in the ledger before creation; the role was verified back to its shipped configuration after every run.
**Document under test:** §4.4 route table row 3 (line 404, *"the execution role must NOT include … Least privilege here IS the anti-jailbreak control"*) and row 4 (*"This holds even if route #3's role hygiene regresses"*).
**Class:** C (config-surface), reported as a **descriptive measurement** alongside F5-1's confirmatory verdict. No p-value, no multiplicity correction: three replicates of a propagation window, not a rate against a threshold.

<!-- provenance
{
  "status": "OBSERVATIONS_COMPLETE",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F5-1"],
  "blocked_on": "A replication on a UTC calendar day after 2026-08-11. All three replicates fell on 2026-08-11Z, and the quantity measured here is a service-side propagation window — precisely the kind of thing that can differ between days, regions, or fleet states. n is not the issue: three independent replicates agreed that the window exists and outlasts the confirmation of a denial. What one day cannot exclude is that 2026-08-11 was an unusual day for IAM in us-east-1. The replicate is cheap (20 invocations + 2 mutations, under $0.01) and needs no new infrastructure, so this deferral is a scheduling fact, not a blocker.",
  "amends": ["S4.4"]
}
-->
<!-- `blocked_on` is live, not renamed: unlike FINDING-F1-3 and FINDING-F5-7A this finding has NOT
     been replicated on a second day, and the status is the deferred one that the gate requires a
     stated condition for. Promoting it to READY_TO_AMEND while the evidence spans one day makes
     check_amendment_readiness.py FAIL, which is the intended behaviour. -->

## 1. The claim, and what this finding does and does not touch

F5-1's confirmatory question — *can the AgentCore Runtime execution role reach the tool Lambda directly, bypassing the Gateway and its policy engine, in the role's shipped configuration?* — is answered and **not** what this document is about. That answer is **TRUE (no bypass)**: 0 of 120 direct invocations executed, Wilson 99% interval `[0, 0.05865]`, exact one-sided ceiling `0.0414` at α=0.00625, with a mandatory mutation that inverted (20/20 executed once `lambda:InvokeFunction` was granted, all 20 echoing our marker). The document's route-3 advice is confirmed on that point.

This finding is about the **remedy**, which the document states as a property (*"Least privilege here IS the anti-jailbreak control"*) and which an operator necessarily reads as an action: if the role has too much, take it away. Measured here: taking it away does not close the path when the API call returns, and — the part that is not obvious and is the reason this is a finding rather than a footnote — **it does not close the path when you check and see a denial either.**

## 2. What was measured

Three replicates. Each: grant `lambda:InvokeFunction` as an inline policy on the runtime execution role, confirm the grant is effective by polling, invoke 20 times (all 20 executed, every replicate), `DeleteRolePolicy`, poll until the denial is observed, then send 20 more invocations.

| # | rule that ended the revoke wait | denial observed after | of the next 20 invocations, **executed** |
|---|---|---|---|
| 1 | 1 confirming probe | 31.2s | **9** |
| 2 | 3 consecutive probes | 248.5s | **4** |
| 3 | 3 consecutive probes | 41.4s | **11** |

**24 of 60 invocations sent after a denial had been observed still executed and ran the tool.** In the third replicate — the one with the strongest instrument, three consecutive `AccessDeniedException` responses spanning 20 seconds — **11 of 20** subsequent invocations executed.

Two runs are absent from the table because they sent nothing: `restored_reassert` was already checkpointed and a checkpointed arm is served from disk. That is also why replicates 1 and 2 had to be set aside for 3 to be taken; both are archived with their provenance, and replicate 2 is archived as a **valid replicate**, not a defect (see §6).

For contrast, the same polling in the **grant** direction converged on all five attempts: 288.3s and 21.6s under the one-probe rule, then 114.5s, 32.1s and 31.9s under three consecutive confirmations.

## 3. What is NOT claimed

- **No dose-response.** 31.2s→9, 248.5s→4, 41.4s→11 is not a monotone relationship, and with three points it would be dishonest to draw one. The waiting rule that ended each replicate is a property of *our instrument*, not of the fleet's state, and the fleet state at the moment of each probe is unobservable to us.
- **No asymmetry between grant and revoke.** The revoke direction was the only one to exceed 300s (once, in the fourth run — see §4), and the grant direction's slowest observation was 288.3s. Three-and-five observations do not separate two distributions.
- **No number to design against.** Nothing here supports "wait N seconds after revoking". The one thing the data does rule out is the rule an engineer would most naturally write: *poll until you see the deny, then proceed.*

## 4. The fourth run: not reached inside 300s, and yet converged

A fourth run held the revoke wait for **308.8s** and never observed three consecutive denials (it stopped at two). It re-sent no invocations, so it contributes no row to §2 — but its published record carries the honest `reached: false` and the note that any arm below it describes an unsettled configuration.

An **independent 12-probe check**, run after that process had exited and before the next run was launched — between roughly 20 and 40 minutes after its `DeleteRolePolicy` returned — came back **12/12 denied**. So the state does converge; 300s was the wrong ruler for this direction, not evidence of a permanent hole.

That check has a defect worth naming: it did not stamp its own start time, so the interval above is bounded from the surrounding logs' mtimes rather than measured. The day-2 replicate (§7) records its own timestamps.

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

## 7. What would discharge this

One run of `f5_redteam/01_route1_direct_invoke.py` on a UTC day after 2026-08-11, with `results/checkpoints/F5-1__restored_reassert.json` set aside first so the arm is actually re-sent. 20 invocations, 2 mutations, under $0.01, no new infrastructure. If a second day reproduces post-restore executions after a confirmed denial, §4.4's amendment goes in as §8. If a second day shows zero, that is equally publishable and this finding becomes a bounded statement about 2026-08-11 in us-east-1 — which is why the status is the deferred one and not the amendment one.

## 8. Amendment candidate (§4.4, drafted, not yet applied)

Add to the route table's row 3, after *"Least privilege here IS the anti-jailbreak control"*:

> **Least privilege is a control on the steady state, not an incident-response action.** Removing an over-broad grant does not close the path when `DeleteRolePolicy` returns, and — measured on 2026-08-11 in us-east-1 — it does not close the path when a subsequent call is observed to be denied either: across three replicates, 24 of 60 direct invocations sent after a denial had been observed still executed, including 11 of 20 after three consecutive `AccessDeniedException` responses spanning 20 seconds. IAM authorization is evaluated per request against an eventually-consistent view; a single confirming probe, or several, does not establish that every endpoint has the new view. Containment during an incident therefore needs a control that fails closed at the boundary being crossed — disable the function, revoke the session, or block at the gateway — with the IAM change as the durable fix behind it. Do not write a runbook step of the form *"remove the permission, confirm the deny, then proceed"*.

Row 4's *"This holds even if route #3's role hygiene regresses"* stays as written: an SCP or permission boundary is exactly the fail-closed backstop this measurement argues for. The wording that needs care is the implied timeline of *recovering* from a regression, not the backstop itself.

## 9. Cross-references

- `DEVIATIONS.md` → **DEV-P4-15** for the four instrument defects found while getting this run green (`evaluate` arity, a field silently demoted to `detail` by a `**kwargs` sink, a span window that bracketed idle time across a resume, and the one-probe convergence rule), each with the test that now fails if it regresses.
- `V13_CANDIDATES.md` for the §4.4 amendment above, held at the same deferred status as this finding.
