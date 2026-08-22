# FINDING F6-DAY2 — Three F6 verdicts flip on replication, and every flip rests on a measurement that cannot exclude the day-1 value

**Status:** OPEN — a disagreement, not a fix-up. No amendment is licensed by this document.
**Date:** 2026-08-19
**Class:** oracle design (a property of our own `kind` definitions) **plus** one service-side change
**Artifacts:** `results/day2_replication_2026-08-19.json`, `results/phase1/archive/F6-*__day1_2026-08-10.json`,
`session-logs/f6-day2-REAL-20260819.log`, `evidence/r20260810T130945Z/f6_latency/` (records dated 2026-08-19),
`tools/day2_adjudicate_offline.py`

<!-- provenance
{
  "status": "AMENDMENT_DEFERRED",
  "cases": ["F6-1", "F6-2", "F6-3", "F6-4", "F6-5", "F6-6", "F6-7", "F6-8", "F6-9"],
  "cases_note": "The nine verdict ids this finding is about, declared as themselves. Until 2026-08-22 this field could not say that: it read [\"F6-1_3_4_9\", \"F6-2_5\", \"F6-6_7_8\"] -- PRODUCER GROUP ids, not case ids -- because one F6 producer serves several cases and stamps every record with the group's name, and check_amendment_readiness.observation_days() compared case_id for equality, so declaring 'F6-6' matched zero of its own 9,287 records and the gate reported a nine-case finding as resting on records that were never written. That defect is FUTURE-WORK item 34's second reason and is now fixed: the gate resolves both sides through lib/case_ids.py, so F6-6 reaches F6-6_7_8's records. Re-measured after the change (results/ITEM34-GATE-DELTA.json): the day set is unchanged at ['2026-08-11', '2026-08-19'], i.e. this edit buys honesty in the declaration and moves no number the finding rests on. WHAT THE FIX DOES NOT BUY, stated because the old note claimed it as the price and a reader could now think it was paid: the gate's day scoping is STILL per-producer for these nine cases, and no matcher can change that, because the granularity is in the data -- F6-6's second day is established by a record stamped F6-6_7_8, which is equally F6-7's and F6-8's record. A day credited to one member is credited to its whole group. That is tolerable here only because a group's members are always observed in one producer invocation, so there is no day a member did not in fact run; it would stop being tolerable the moment a producer wrote a group directory for a subset of its cases. Per-case day scoping for F6 requires the producer to stamp per-case case_ids, which is a producer change and not a gate change. Mapping, for a reader checking the counts: F6-1_3_4_9 -> {F6-1, F6-3, F6-4, F6-9} (4,033 records), F6-2_5 -> {F6-2, F6-5} (5,631), F6-6_7_8 -> {F6-6, F6-7, F6-8} (9,287).",
  "evidence_runs": ["r20260810T130945Z"],
  "utc_days": ["2026-08-10", "2026-08-11", "2026-08-19"],
  "blocked_on": "Nothing that a further run can supply, and the status is the closest the gate's vocabulary comes to that. Three cases DISAGREE across days (F6-2, F6-5, F6-8), which PREREGISTRATION.yaml makes a finding rather than a fix-up, so no amendment is licensed for them on this data at all -- not deferred pending more days. For the six that agree, F6-6's n_met went true->false (n_usable 999 < planned_n 1000, traced in section 4 to two TCP resets), so it does not clear the bar either. Any future amendment resting on an F6 tail comparison additionally needs a successor oracle kind with a decisiveness requirement, which PREREGISTRATION.yaml is sealed against -- FUTURE-WORK item 32(c) scopes that to future pre-registrations only. Recorded here because the gate has no DISAGREEMENT status: an earlier draft of this block used 'OBSERVED' and the gate correctly refused it, which is itself the register item.",
  "note": "The day-2 records share the day-1 run id because the producers adopt state.json's run id; they are distinguished by their own t_start_utc, which is the warrant this project already uses in evidence_date(). 9,503 records dated 2026-08-11 (day 1) and 9,448 dated 2026-08-19 (day 2). Consequence to watch: this directory now carries two distinct UTC days for all nine cases, which is the signal check_amendment_readiness.py looks for -- a disagreement must not be allowed to read as readiness."
}
-->

## 0. What was run, and the false negative that hid it

Three F6 producers ran through `tools/day2_replicate.py` on 2026-08-19, sequentially, for 52 min,
36 min and 2 h 41 min. All three returned **rc 2 — "did not observe"**. That return code is wrong,
and the reason is a defect in the driver rather than a property of the run.

The driver mints a fresh `run_id`, passes it to the producer as `--run-id`, and afterwards counts
evidence records under `evidence/<minted_id>/` as its proof that something was observed today. The
producers do not honour the flag: `lib.testbed.State.load_or_new` reads `state.json` and adopts the
run id recorded there. Every one of the three printed `run_id=r20260810T130945Z` under a command line
that said `--run-id r20260819T030137Z`. So:

| quantity | value |
|---|---|
| `fresh_records("r20260819T030137Z", "2026-08-19")` — what the driver measured | **0** |
| `fresh_records("r20260810T130945Z", "2026-08-19")` — the run id the producers used | **9,448** |
| call-record day histogram under `evidence/r20260810T130945Z/f6_latency/` | `{2026-08-11: 9503, 2026-08-19: 9448}` |
| `evidence/r20260819*` directories on disk | **none** |

The early `return 2` fires *before* the per-case comparison loop, so `results/day2_replication_2026-08-19.json`
was never written either. It has since been reconstructed by `tools/day2_adjudicate_offline.py` from
the driver's own pre-run snapshots (`runner/.staging/day2_pre_*`, 98 verdict files each) calling the
driver's own comparison functions, with `provenance.derived_offline: true` on every entry.

**This is the second time in one week that a stale `run_id` in `state.json` has broken an F6 day-2
run, in opposite directions.** On the morning of 2026-08-19 a hand-run replayed day-1 checkpoints and
produced a confident result from no measurement. This run did real measurement and produced a
confident "nothing was observed". Both have the same root cause and neither was caught by a gate.

## 1. The result

Nine cases, one UTC day apart from day 1 (2026-08-10/11 → 2026-08-19). **No sealed field moved in any
case**, so both days evaluated the same sealed test. Six agree, three disagree.

| Case | day 1 | day 2 | | note |
|---|---|---|---|---|
| F6-1 | FALSE | FALSE | agree | |
| F6-3 | FALSE | FALSE | agree | |
| F6-4 | FALSE | FALSE | agree | |
| F6-7 | TRUE | TRUE | agree | `n_usable` 1600 → 1599 |
| F6-6 | TRUE | TRUE | agree | **`n_met` true → false** (`n_usable` 1000 → 999); day 2 no longer clears the amendment bar, and §4 traces the missing observation to a TCP reset |
| F6-9 | TRUE | TRUE | agree | `n_usable` 455 → 457, both far below the pre-registered 1000 |
| **F6-2** | FALSE | **TRUE** | **disagree** | §2 |
| **F6-5** | FALSE | **TRUE** | **disagree** | §2 |
| **F6-8** | FALSE | **TRUE** | **disagree** | §2 |

Per `PREREGISTRATION.yaml` a disagreement is a **finding, not a fix-up**. Nothing here licenses an
amendment, and the four agreeing FALSE/TRUE verdicts that now rest on two calendar days
(F6-1, F6-3, F6-4, F6-7) are the only replication progress this run bought.

## 2. Every flip is faithful to its sealed oracle, and every flip is indecisive

The three day-2 verdicts are **correct applications of the pre-registered oracles**. All five guards
(`arms_are_paired`, `guardrail_ran`, `no_intervention`, `output_side_complete`, `trace_is_enabled`)
pass on both days, `blockers` is empty on both days, and F6-2's second condition (the paired shift
must exclude 0) holds on both days. Nothing was mis-scored. The oracles are weak.

**F6-2** — `BAND_CONTAINS` over the p50–p99 band against the document's illustrative 100–500 ms.

| | p50 [95% CI] | p90 [95% CI] | p99 [95% CI] | verdict |
|---|---|---|---|---|
| day 1 | 231 [226, 235] | 374.2 [363, 391] | **622.0 [551, 689]** | FALSE — p99 outside |
| day 2 | 203 [203, 204] | 231 [227, 235] | **375.0 [317, 752]** | TRUE |

**F6-5** — same oracle, same band.

| | p50 [95% CI] | p90 [95% CI] | p99 [95% CI] | verdict |
|---|---|---|---|---|
| day 1 | 234 [228, 238] | 366.1 [348, 384] | **662.2 [541, 858]** | FALSE — p99 outside |
| day 2 | 202 [202, 203] | 233 [228, 240] | **466.4 [347, 722]** | TRUE |

**F6-8** — `CI_OVERLAPS`: "TRUE if the regression slope's bootstrap CI overlaps [165, 750]; FALSE if
disjoint."

| | slope CI | vs stated [165, 750] | verdict |
|---|---|---|---|
| day 1 | [838.73, 862.68] | disjoint, wholly above | FALSE |
| day 2 | [736.40, 757.54] | overlaps by **13.6 ms**; 36% of the CI is still above 750 | TRUE |

The pattern is identical in all three, and it is the finding:

> **On day 1 the confidence interval lay wholly on the refuting side of the threshold — a decisive
> FALSE. On day 2 the confidence interval straddles the threshold — the measurement decides nothing —
> and the oracle scored TRUE anyway, because `BAND_CONTAINS` compares point estimates and
> `CI_OVERLAPS` asks only whether two intervals touch.**

Day 2 does not refute day 1. Day 2 failed to establish anything about the upper bound, and the sealed
`kind` has no way to say so. `BAND_CONTAINS` computes and publishes `ci_p99` and then adjudicates on
`p99`; `CI_OVERLAPS` treats a 13.6 ms overlap and a total containment as the same outcome. There is no
third value for "the interval spans the threshold", even though `INCONCLUSIVE` exists elsewhere in
this study and is the honest answer here.

The imprecision is not marginal. The day-2 p99 confidence intervals are **435 ms wide** (F6-2) and
**375 ms wide** (F6-5) — each roughly as wide as the entire 400 ms band being adjudicated. Day 1's were
138 ms and 317 ms, which is why day 1 could decide and day 2 could not.

**Consequence for citation.** F6-2, F6-5 and F6-8 must not be cited as TRUE (the document's band
holds) *or* as FALSE (it does not) on the strength of the p99 / slope comparison. The defensible
statement is: **n = 1,000 is too small to adjudicate a 500 ms p99 threshold against a distribution
whose p99 CI is as wide as the band itself.** The p50 and p90 comparisons for F6-2 and F6-5 remain decisive on both
days — both are inside 100–500 ms on both days — so what fails is only the tail claim.

`PREREGISTRATION.yaml` is sealed, so the oracles cannot be retrofitted and these verdicts cannot be
re-scored. The remedy is a citation qualification recorded in `results/CITATION-POLICY.md` and the
register — **not** `ERRATA.md`, whose own charter excludes verdicts (§6.2) — and no edit to any case
artifact.

## 3. What *is* established: the input/output guardrail got measurably faster

Separately from the verdicts, one thing replicated cleanly in the strong direction. F6-2 and F6-5
measure `measured_field = trace.guardrail.{input,output}Assessment[...].invocationMetrics.guardrailProcessingLatency`
— **the service's own reported processing time, read out of the Bedrock trace**. It is not a client
wall clock and not a paired difference, so neither the client OS bump (§4) nor network position can
move it.

At p50 and p90 the two days' order-statistic CIs are **disjoint**:

| | F6-2 p50 | F6-2 p90 | F6-5 p50 | F6-5 p90 |
|---|---|---|---|---|
| day 1 | 231 [226, 235] | 374.2 [363, 391] | 234 [228, 238] | 366.1 [348, 384] |
| day 2 | 203 [203, 204] | 231 [227, 235] | 202 [202, 203] | 233 [228, 240] |

Independent client-side corroboration, same direction and comparable proportion: the guarded arm's
total wall clock fell from p50 861 / p90 1093.1 / p99 1473.1 / max 5771 ms to p50 786 / p90 877 /
p99 1211.3 / max 1511 ms, and the paired shift `median(guarded) − median(bare)` fell from a
Hodges–Lehmann 505 ms (bootstrap CI [483, 503]) to 418.5 ms (CI [410, 421]) — also disjoint.

Two independent instruments, one of them server-side by construction, agree that guardrail evaluation
cost dropped between 2026-08-10 and 2026-08-19, by 8.7% (client-side guarded p50), 12.1% and 13.7%
(server-reported p50), 17.1% (paired shift), and 36.4% and 38.3% (server-reported p90). The most
parsimonious explanation is a change on the AWS side. **This is exactly the class of drift a
one-calendar-day study cannot see**, and it is the strongest available argument for continuous
re-validation: the numbers in Chapter 10 have a shelf life measured in days, not quarters.

## 4. Caveats, including one the driver's own guard should have raised

**The driver reported `clean_observation: true` for all nine cases over a run that contained eight
failed calls.** Derived by a predicate over each record's own `ok` flag across the whole run id, with
no case scoping and no error-name list — 9,448 call records dated 2026-08-19, of which **8 have
`ok: false`**:

| directory | failure | duration |
|---|---|---|
| `f6_latency/F6-2_5/` | `ReadTimeoutError` (botocore) | 70,003 ms |
| `f6_latency/F6-2_5/` | `ClientError` / HTTP `500` "Internal Server Error" ×3 | 1,543 / 231 / 652 ms |
| `f6_latency/F6-6_7_8/` | `ProtocolError` — `RemoteDisconnected` | 5,102 ms |
| `f6_latency/F6-6_7_8/` | `ProtocolError` — `ConnectionResetError(54)` ×2 | 1,348 / 5,467 ms |
| `f6_latency/F6-6_7_8/` | HTTP `404` on `mcp:tools/call`, empty error message | 1,040 ms |

Plus one *successful* `converse` that took 59,722 ms. The F6-2/F6-5 bare arm records `n_done: 998,
n_failed: 2` where day 1 had 1000/0, and `bare_total_ms.max` went from 942 ms to 37,234 ms.

`transient_failures()` — the guard written after F8-5 precisely so that a throttled probe cannot be
counted as an observation — missed all eight, for **three independent reasons**, any one of which
alone suffices:

1. `TRANSIENT_ERRORS` enumerates *names*: it lists `RequestTimeout`, `RequestTimeoutException` and
   `ModelTimeoutException` but not botocore's actual read-timeout class `ReadTimeoutError`, and it has
   no entry for a bare HTTP `500`. This is the name-list-versus-prefix failure mode again — a guard
   that enumerates members of a family misses the next member.
2. `_scoped()` requires a path component to *be* the case id or start `<case>-`. These records live in
   directories named `F6-2_5` and `F6-6_7_8`, because one producer serves several cases. No case id
   matches either, so the scan is empty regardless of the error codes.
3. **The four `F6-6_7_8` records carry no `error_code` and no `error_class` at all** — the failure is
   recorded only in `error_message` (`ProtocolError: ('Connection aborted.', …)`) or, for the 404, in
   `http_status` with an empty message. A guard keyed on error *codes* is blind to them whatever names
   its list holds, which is why the closing condition for this defect has to be a predicate over the
   record's success flag rather than a longer list.

**All three are fixed as of 2026-08-22, and the fix was verified against these same records rather
than against a fixture.** `transient_failures()` now gates on `ok is False` and uses the error names
only to choose a label, and `_scoped()` resolves a path component through `lib/case_ids.py`. Re-run
over `evidence/r20260810T130945Z` for 2026-08-19 it finds **8 of 8**: `ReadTimeoutError`, `http_500`
×3, `ProtocolError` ×3, `http_404` — and attributes four to each of F6-2 and F6-5 and four to each of
F6-6, F6-7 and F6-8, so those five cases now report `clean_observation: false` where the driver
reported `true`. F6-1, F6-3, F6-4 and F6-9 stay clean, which is correct: their group had no failed
call. The numbers in this section are therefore no longer things only this document knows —
`tools/tests/test_day2_replicate_failures.py` asserts the count and the five affected cases over the
real tree, and carries a mutation arm showing the old name-keyed rule sees none of the four shapes.
Note what does **not** change: this finding's verdicts, its disagreements, and F6-6's lost bar are all
unaffected. A guard that now fires does not re-adjudicate a run; it means the caveat is recorded by the
instrument instead of by hand in this paragraph.

**Two of those four aborts cost F6-6 its amendment bar.** The denominators, derived from the verdict
files rather than read off a summary:

| case | day 1 | day 2 |
|---|---|---|
| F6-6 | `n_attempted` 1600, `n_usable` **1000**, `n_met` **true** | 1600, **999**, **false** (`planned_n` 1000) |
| F6-7 | 1600, `n_usable` **1600**, `n_met` true | 1600, **1599**, true (`planned_n` 200) |
| F6-8 | 1600, `n_usable` **600**, `n_met` true | 1600, **600**, true — *identical* |

So F6-6 fell one usable observation short of its pre-registered 1,000 and lost `n_met`, and F6-7 lost
one it could afford — exactly two of the four connection aborts, in the producer those two cases share.
F6-6's agreement therefore does not clear the amendment bar for a reason that has nothing to do with
guardrails: two TCP resets.

**The failures still do not explain the three flips.** F6-8's `n_attempted` and `n_usable` are
byte-identical across the two days, so no data loss touched its slope estimate. For F6-2 and F6-5 none
of the four failures falls in the p99 order statistic's neighbourhood at n = 998 (p99 is the ~988th
value). "Clean observation" is not true of this run, and the emitted record now carries the eight
failures under `provenance.failed_calls_run_wide` beside the field that claims otherwise.

**Client OS changed between the two days:** macOS 26.6 (build 25G72) → 26.6.1. Day-1
`environment.json` records `platform: macOS-26.6-arm64-arm-64bit`, and `SEALED_FIELDS` does not include
`platform`, so no gate would have refused the run. This confounds every client-measured case —
F6-1, F6-3, F6-4, F6-6, F6-7, F6-9 and **F6-8** (whose estimator is a median over pooled per-turn
client increments). It does **not** confound F6-2's and F6-5's verdict quantity, which is
server-reported; it is one of the few places in this study where the instrument's location rescues a
measurement.

**Day-2 evidence is commingled with day 1's run directory**, since the producers adopted the day-1 run
id. The two days are separable only by each record's own `t_start_utc`. That is the warrant
`evidence_date()` already prefers over a run-id string, so the separation is sound — but every
consumer that assumes one run id means one observation day is now wrong about this directory. Note the
side effect: `check_amendment_readiness.py` looks for ≥ 2 distinct UTC days under a run id, and this
directory now satisfies that test for all nine F6 cases, including the three in disagreement. **A
disagreement must not be allowed to read as readiness.**

## 5. Cost

Approximately 9,448 billable calls (Nova Micro `Converse` with guardrail trace enabled, plus gateway
and `ApplyGuardrail` invocations). Small in absolute terms against the `cost_model.yaml` ceiling of
$95, and to be reconciled against Cost Explorer rather than estimated here.

## 6. What this finding asks for

1. **No amendment.** Three disagreeing cases; `reproduction_before_amendment` is not satisfied for any
   of them, and F6-6's `n_met` went false, so its agreement does not clear the bar either.
2. **A citation qualification** for F6-2, F6-5 and F6-8: the tail comparison against the documented
   band is not established in either direction at n = 1,000. It does **not** belong in
   `results/ERRATA.md` — that file is scoped by its own opening to factual errors inside *sealed*
   artifacts and explicitly "not for verdicts". A weak oracle is not a wrong statement in a sealed
   file. Register item 32 therefore asks for `results/CITATION-POLICY.md`, collecting this restriction
   beside the two that exist today only as prose in two different documents (F5-3b non-publishable,
   F1-19 not a verdict), so that there is one place to check before citing a case.
3. **`results/phase1/` keeps day 1 as the verdict of record for the three disagreeing cases** —
   decided 2026-08-19 and already applied. The rule being applied is not "prefer the FALSE": it is
   that **a disagreement licenses no change to the published record**, and the published record is
   day 1. The same rule would have kept a day-1 TRUE against a day-2 FALSE. The day-2 files are
   retained in full under a label that states why they were set aside:

   | case | live now (day 1) | day-2 file archived to | day-1 sha256 | day-2 sha256 |
   |---|---|---|---|---|
   | F6-2 | FALSE | `archive/F6-2__day2_indecisive_2026-08-19.json` | `5e9d2ec6…e91ac257` | `ec083553…a9fb65ed` |
   | F6-5 | FALSE | `archive/F6-5__day2_indecisive_2026-08-19.json` | `7bc0bece…d49d4c91` | `2e4220dc…f32df51c` |
   | F6-8 | FALSE | `archive/F6-8__day2_indecisive_2026-08-19.json` | `bf582406…88dcc791` | `8f895a2f…ffae71c8` |

   Every elision above is **first eight … last eight** hex characters, uniformly, so a reader can
   check any row with one `shasum -a 256`. That rule is stated because the table did not follow one:
   until 2026-08-20 the six entries were elided to 7, 8 and 9 trailing characters, and F6-5's day-2
   entry ended in the eight characters `9f32df51` where the file's hash ends `f32df51c` — the
   positions −9 to −2, one place short of the end, so the row matched no sha256 in existence. A table
   whose stated purpose is to identify a file by its hash had one row that could not identify
   anything, and a varying elision length is what let the off-by-one look like just another row.
   `claims/tests/test_hash_citations.py` now resolves every elided hash cited anywhere in this
   repository against the hashes it can derive, so the next one fails a test instead of being read
   past. (This paragraph originally reproduced the bad value in full citation shape and the new test
   convicted the explanation along with the defect — `feedback_self_scanning_guard`, and the reason
   the two halves are quoted separately above.)

   The hashes are recorded because they are the **only** way to tell which day a live F6 file holds:
   both days' files carry `run_id: r20260810T130945Z` (§0), so the run id cannot distinguish them and
   the archive filename is a label, not evidence. Each restored live file is byte-identical to its
   `__day1_` archive — asserted, not stated, by the same test file; `census.py` re-derives
   **TRUE 46 / FALSE 23 / INCONCLUSIVE 20 / RECORDED 2**,
   which is what published `main` states. Before the restore the same script derived **TRUE 49 /
   FALSE 20** — three verdicts, and the headline number the whitepaper cites, would have moved on
   measurements that established nothing.

   The **six agreeing cases keep their day-2 files live**, which is the driver's designed end state:
   their verdicts did not move, and for F6-6 the day-2 record is the more conservative of the two
   (`n_met` false), so publishing it removes an amendment eligibility rather than creating one.
4. **Driver and oracle defects** filed in `FUTURE-WORK.md` (see the items added alongside this
   document): the `--run-id` adoption defect, the freshness proof's scope, `TRANSIENT_ERRORS` as a name
   list, `_scoped` versus shared per-producer directories, and the absence of a decisiveness
   requirement in `BAND_CONTAINS` / `CI_OVERLAPS`.
