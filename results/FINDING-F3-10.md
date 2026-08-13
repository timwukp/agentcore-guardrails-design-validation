# FINDING F3-10 — §7.1's confusion matrix is buildable, but not from the surface §6.2 points at, and only in one direction. CloudWatch metrics destroy the score↔label join at any usable request rate; the logs keep it, as a string

**Status:** **READY_TO_AMEND** — replicated on two separate UTC calendar days (**2026-08-12** and **2026-08-13**), 2,693 call records across the two, every reading reproduced and every guard clean on both. The replicate did what a replicate is for: it found a reader defect a single day had hidden (§13, DEV-P4-35)
**Dates:** **2026-08-12** and **2026-08-13** (UTC, derived from `t_start_utc` on the evidence records, never asserted here). Day 1: 1,491 records under `f3_efficacy/F3-10`, 9 under `f3_efficacy/F3-10-log-surface`, 63 under `f3/F3-10_audit_2026-08-12`. Day 2: 1,202 under `f3_efficacy/F3-10`, 9 under `f3_efficacy/F3-10-log-surface`, 252 under `f3_efficacy/F3-10-window-audit`, 6 under `f3_efficacy/F3-10-log-surface-day1-rederived` — the last of these is a day-1 window re-read on day 2 with the fixed reader, so it is stamped day 2 and counted as day 2, which is what it is.
**Scripts:** `f3_efficacy/08_score_label_join.py` (the three arms, the verdict) · `f3_efficacy/08b_log_surface_join.py` (the supplementary read of the log surface; no verdict) · `f3_efficacy/08c_window_audit.py` (the closed-window re-read §11 prescribed, 11 guards, no verdict) · offline suites `f3_efficacy/tests/test_score_label_join.py`, `f3_efficacy/tests/test_log_surface_join.py` and `f3_efficacy/tests/test_publish_slack.py`
**Run id:** `r20260810T130945Z` (adopted from the ledger, not minted)
**Raw evidence:** `evidence/r20260810T130945Z/f3_efficacy/F3-10/` — **1,491 call records, all 1,491 carrying `request_id`**: 1,196 `get_metric_statistics`, 242 `mcp:tools/call`, 16 `get_gateway`, 14 `list_metrics`, 6 `update_gateway`, 3 `mcp:initialize`, 3 `mcp:notifications/initialized`, 3 `create_policy`, 3 `delete_policy`, 2 `describe_log_groups`, 2 `filter_log_events`, 1 `mcp:tools/list` (1196+242+16+14+6+3+3+3+3+2+2+1 = 1491), plus `analysis.json`, `environment.json` and `summary.json`, which are aggregates rather than calls and carry no `t_start_utc`, so they contribute no observation day. And `evidence/r20260810T130945Z/f3_efficacy/F3-10-log-surface/` — 9 `filter_log_events` records for the supplementary read. And `evidence/r20260810T130945Z/f3/F3-10_audit_2026-08-12/` — 63 records (49 `get_metric_statistics`, 14 `list_metrics`) from the separate audit that re-read the same closed window.
**Analysis records:** `results/phase1/F3-10.json` (verdict `FALSE`) and `results/phase1/F3-10_log_surface_join.json` (`kind: SUPPLEMENTARY_READ`, no verdict). Two withdrawn earlier attempts are archived rather than deleted: `results/phase1/archive/F3-10__withdrawn_unknown_tool_2026-08-12.json`, and the checkpoints `results/checkpoints/F3-10__log_only_golden_set__unknown_tool_2026-08-12_archive.json` and `…__aborted_restore_2026-08-12_archive.json`.
**Pre-registration seal in force:** `a2136a9d3dbb…fa74cf1a`
**Cost: under $0.03.** 1,245 `GetMetricStatistics` + 28 `ListMetrics` + 11 `FilterLogEvents` ≈ $0.013 at $0.01 per 1,000 CloudWatch API requests; 242 gateway `tools/call` of which **122 reached a content filter** (the log surface shows 61 `Policy evaluation completed` + 61 `Policy evaluation denied request`), so ≤ 122 text units at `guardrail_checks_content_text_unit` = $0.00007 → ≤ $0.0086; 6 `UpdateGateway` + 3 `CreatePolicy` + 3 `DeletePolicy` control-plane mutations; 91 echo-Lambda executions. The probe policy was deleted in a `finally`: `probe.removal` records `deleted: true`, 1 attempt, zero errors.
**Document under test:** §7.1 **line 737** (the LOG_ONLY→ENFORCE threshold-tuning workflow, whose step 3 is the claim under test) and the §7.1 Mermaid diagram. `claims/triage.csv` registers all 7 diagram units at **line 739**, which is the opening ```` ```mermaid ```` fence — the node this case answers for, node C, is at **line 742**: *"3. Build confusion matrix<br/>from logged ConfidenceScores;<br/>compare candidate thresholds"*. The two numbers are not a discrepancy, but a reader checking 739 will find a fence and should know why. Also §6.2 **line 657** — *"**ConfidenceScore / ConfidenceThreshold** | Observed score vs. configured threshold per evaluation | Threshold calibration (Section 7.1)"* — which is the row that sends the reader to metrics, and §6.2 **line 666**'s terminology note: *"the value surfaced as ConfidenceScore is called a severity score for content filters and prompt attacks, and a confidence score for sensitive-information filters"* — so for the HATE content filter probed here, the number swept below is a **severity** score, and §7.1's own words ("confidence scores") name it by the wrong one of the document's own two terms.
**Class:** E (mechanism), with a measured negative. Sealed oracle: *"TRUE if a per-request score↔label join is recoverable from CloudWatch metrics alone; FALSE if 1-minute aggregation destroys the linkage, in which case a reader following 7.1 cannot compute precision at all."* No p-value: one differently-labelled pair sharing one 60-second bucket refutes the identity half, so this is an existence question and not an estimate.

<!-- provenance
{
  "status": "READY_TO_AMEND",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F3-10"],
  "replicated_on": ["2026-08-12", "2026-08-13"], "replication": "Both days re-derived by ONE instrument after DEV-P4-35. Every structural figure reproduced exactly: 579 log events / 0 unparsed, 122 matched / 0 unmatched / 0 duplicate request_ids, 61 of 122 requests scored, 17 of 20 candidate thresholds evaluable, 30 shadow denials against 31 real ones, 57 series colliding in a mixed bucket, all 11 verdict guards and all 7 log-surface guards clean, verdict FALSE. The per-arm sums differ between days because the scores do (24.6/0.8/24.2 against 24.4/0.8/24.8, minimum logged score 0.4 against 0.6) and reconcile within each day. The day-2 replicate FAILED logs_reconcile_with_metrics on first reading and that failure was a reader-side bucket-attribution defect, now DEV-P4-35, whose two halves are each pinned by a mutation arm in f3_efficacy/tests/test_publish_slack.py.",
  "amends": ["S6.2", "S7.1"]
}
-->

## 1. The question, and the two surfaces that answer it differently

§7.1 tells a reader to calibrate a guardrail threshold before enforcing it, in four steps. Step 3 is the one with content: *"Label results and use the confidence scores in the logs to build a confusion matrix, comparing precision/recall across candidate thresholds."*

A confusion matrix is a table of labelled scores. Building one needs two things, and either one missing makes step 3 unexecutable:

* **(a) a score** — a number per request, or there is no threshold to sweep;
* **(b) an identity** — something tying that number to a request whose ground-truth label you know.

The sealed oracle scopes the question to **CloudWatch metrics alone**. That scoping is worth naming up front, because §7.1's own words say *"the confidence scores in the **logs**"* while §6.2 line 657 is the row that sends a calibrating reader to `ConfidenceScore`/`ConfidenceThreshold` — *metrics*. The document points at two surfaces for one step, and they do not behave the same way. So this case was run against the metrics (the sealed oracle, verdict-bearing) and then the log surface was read separately as `08b`, unscored. **The verdict is FALSE and stands. The full answer is more useful than the verdict**, which is why §4 exists.

## 2. The instrument: three arms, and what each one is for

Same gateway (`grx-gw-r20260810t130945z-zpkfmpwo9n`), same policy engine (`grx_pe_r20260810T130945Z-t6hqadrspf`), same action (`grxecho___echo`), one probe policy (`grx_f3_10_scored_r20260810T130945Z-ystne00vhh`: ContentFilter/HATE on `context.input.text`, `forbid`, `ACTIVE`, **threshold 0.2**), one golden set of 60 (30 positives, 30 negatives). All **11 guards** held with `guard_detail.failed: []`.

| arm | engine mode | traffic | outcomes at the client | joinable from metrics |
|---|---|---|---|---|
| `log_only_golden_set` | LOG_ONLY | 60 serial, no delay | allowed 60 | **no** |
| `active_golden_set` | ENFORCE | 60 serial, no delay | allowed 30, policy_denied 30 | **no** |
| `active_one_per_minute` | ENFORCE | 2, spaced 70 s | allowed 1, policy_denied 1 | **yes** |

The three arms exist because a single LOG_ONLY arm cannot distinguish *"the service publishes no score"* from *"the guardrail never ran"* — and an earlier attempt at this case made exactly that mistake, which is why `results/phase1/archive/F3-10__withdrawn_unknown_tool_2026-08-12.json` is archived rather than published. The ENFORCE arm makes an absence an absence **of** something: 30 of its 60 requests were denied by the policy, so the guardrail demonstrably ran. The spaced arm turns half (b)'s escape hatch from an argument into a measurement.

Two supporting properties, both asserted rather than assumed. Every request was **evaluated**: `n_evaluated == n_attempted == 60` in both golden arms, with `not_evaluated_texts: []` — a request the engine never saw can be neither blocked nor scored, and counting one as usable is what let an earlier window publish a TRUE on zero evaluations (DEV-P4-22). And the arms **own their buckets**: each arm sleeps past the minute boundary before starting (`bucket_isolation`, 40.6 s / 63.2 s / 26.0 s, 5 s margin), because otherwise `our_buckets` names two arms' traffic and every per-bucket reading below is contaminated.

The harvest window is **fixed, not polled** — `window.why_fixed_not_polled`: *"a loop that waited until a score metric appeared could never observe its absence."* The 120 s settle is 10.45× F7-6's measured p90 publish lag of 11.485 s, so "not there yet" is not an available explanation.

## 3. On the metrics surface, half (a) holds and half (b) fails — conditionally

**Half (a), the score, is present and readable.** This corrects the direction the case was expected to fail in. `ListMetrics` was exhausted over the namespace — 7 pages, **3,210 series**, 35 metric names, of which **233 series and 21 names belong to this gateway** — against a criterion fixed *before* the enumeration ran (`(?i)(confidence|score)`, `criterion_fixed_before_enumeration: true`). Both documented names exist and both are readable for this gateway: **`ConfidenceScore` and `ConfidenceThreshold`**, with datapoints in our own buckets and a value range of **0.0 to 1.0**.

**Half (b), the identity, is not recoverable.** A per-request join needs a dimension whose *value* distinguishes one request from another. This gateway publishes **17 dimension names** — `Category`, `Filter`, `Method`, `Mode`, `Name`, `Operation`, `OperationName`, `Policy`, `PolicyEnforcementMode`, `PolicyEngine`, `Protocol`, `Resource`, `ResourceId`, `TargetResource`, `ToolName` and two more — and every one of them is **configuration-scoped**. Every request in the golden set shares every one of their values. So at §7.1's own traffic rate, 60 differently-labelled requests land in **one** 60-second bucket, `mixed_label_buckets: ["1786504380"]`, with **57 series colliding** inside it and `per_request_score_series: []`. The score for that bucket is an aggregate over 30 positives and 30 negatives at once.

**But the failure is `conditional_on_request_rate`, not absolute, and the distinction is the finding.** `active_one_per_minute` sent one positive and one negative more than a period apart, and `joinable: true` — with `SampleCount == 1` a reader can attribute the datapoint by timestamp. That is a real escape hatch and it is recorded rather than argued away (`identity_half.why_conditional`). It is also not a workaround anyone will use: it is not the traffic §7.1 describes (*"a golden test set or real production traffic"*), and calibrating a 1,000-item golden set at one request per minute takes **16.7 hours** instead of 12 minutes.

Half (a) by contrast would have been *absolute* had it failed — `score_half.why_absolute`: a metric name the namespace does not publish cannot be produced by any request rate, window or dimension filter. Labelling the two halves differently is the point (`feedback_constraints_are_choices`): an absolute failure tells a reader to stop; a conditional one tells them what to change.

## 4. On the log surface, the join is total — and the confusion matrix computes

`08b` re-read the same closed window on the gateway's `APPLICATION_LOGS` group. It is a **supplementary read with no verdict**, because F3-10's oracle names metrics; it has no standing to overturn a verdict about a different surface. All **7 guards** passed.

* **579 log events, 0 unparsed**, across 7 line kinds — including `Started processing request` ×122, `Policy evaluation completed` ×61 and `Policy evaluation denied request` ×61.
* **The join is total and unique: 122 label rows, 122 matched, 0 unmatched, 0 duplicate `request_id`s.** Every request the client sent appears in the logs, keyed by an identifier the metrics surface does not carry.
* **The confusion matrix is computable, and at the configured threshold it is perfect on this corpus**: `tp 30, tn 30, fp 0, fn 0`, precision 1.0, recall 1.0, in both 60-request arms and in the 2-request arm. The decision in the log agrees with the score in **every** arm.
* **The two surfaces reconcile exactly.** Per-arm logged score sums versus `ConfidenceScore` metric sums over the same buckets, on **2026-08-12**: **24.6 vs 24.6** (30 values), **0.8 vs 0.8** (1 value), **24.2 vs 24.2** (30 values), `all_agree: true`, zero disagreeing dimension combinations. Day 2's own sums differ because the scores do, and reconcile the same way (§11); reaching that agreement on day 2 required fixing a reader defect this day's arrangement of the clock had concealed (DEV-P4-35). This is what makes §3's readings trustworthy: the metric is not merely present, it is the *same numbers*, aggregated.

So step 3 is executable — on the surface its own sentence names, and not on the one §6.2 line 657 points at. That is an amendment about *where a reader is sent*, not about whether the workflow works.

## 5. The score is a JSON string, not a number — and that is why a census missed it

The score lives at

```
body.policy.guardrailFindings.<policyId>.contentFilter[].score  ==  "0.8000"
```

**A quoted string.** `score_key_paths_are_numbers: []`; `score_key_paths_are_strings` has exactly one entry.

This matters twice. For a reader, `jq 'select(.score > 0.5)'` silently does the wrong thing on a string, and a four-decimal fixed-point string is a formatting contract nobody documented. For this project, it is a measured instrument defect: **DEV-P4-01's numeric census collected `int` and `float` only**, so the census built to catch an unexpectedly-named score field was structurally blind to the one field it was looking for. DEV-P4-01 recorded that *"no surface publishes a numeric guardrail score"*; its **absolute reading is now refuted, and the refutation is measured rather than argued** — `AWS/Bedrock-AgentCore` publishes `ConfidenceScore` with real values, and the logs publish per-request scores whose sums match those metrics to the decimal. What survives of DEV-P4-01 is the narrower, still-true claim it was originally built on: **no *span* attribute carries a score**, and no surface carries a score *joined to a request identity in metrics*. The span probe read 60 spans over 58 distinct attribute paths; §6's own numbers here show 16 spans matching the score pattern by name and `spans.scored: false`, and the span surface's numeric keys are all latencies and status codes.

The two guards this taught, now in the code: census **strings that look like numbers** as well as numbers, and never let a type filter stand between an instrument and the thing it exists to find.

## 6. The calibration loop can only TIGHTEN. §7.1 step 3 describes a bidirectional sweep

**61 of 122 requests published a score. The other 61 published none.** All 61 scores belong to positives (`scores_by_truth: {positive: 30, negative: 0}` in each golden arm): a request that did not clear the configured threshold of 0.2 produced no `score` field at all.

The consequence is asymmetric, and the document does not mention it:

| direction | candidate thresholds | recomputable from a closed window? |
|---|---|---|
| **at or above** the configured 0.2 | 17 of 20 offered (0.20, 0.25, … 1.00) | **yes** — every request that could clear a higher bar already published its number, so raising the bar only reclassifies detections the reader already holds |
| **below** the configured 0.2 | 3 of 20 (0.05, 0.10, 0.15) | **no** — the 61 unscored requests have scores unknown within `[0, 0.2)`, so a reader cannot tell which of them would clear a lower bar |

Observed scores ran **0.4 to 1.0** (histograms `{0.4: 1, 0.6: 2, 0.8: 22, 1.0: 5}` and `{0.6: 1, 0.8: 25, 1.0: 4}` and `{0.8: 1}`); nothing landed in `[0.2, 0.4)`.

**Operationally: to sweep a threshold downwards you must first configure the guardrail at the most permissive value you are willing to consider, calibrate from there, and raise it.** §7.1 step 3 says "comparing precision/recall across candidate thresholds" without qualification, and a reader who configures 0.8 and then wonders about 0.4 has to re-run their entire golden set — the data they already collected cannot answer it. This is the single most actionable thing in this finding.

## 7. In LOG_ONLY, a shadow denial is indistinguishable from a real one on the fields alerting uses

An incidental reading, worth recording because §7.1's whole premise is that LOG_ONLY blocks nothing. Measured: **30 shadow denials and 31 real denials.** For the 30 requests the client saw *allowed*, the log wrote `decision: DENY`, `effect: FORBID`, `isError: true`, `severityText: ERROR`, and a `policyMode` of **`ENFORCE`** — the *policy's* mode, not the engine's.

So log-based alerting keyed on `isError`, `severityText` or `decision` cannot tell a shadow evaluation from a blocked request, and the field that would disambiguate reports the wrong object. A reader following §7.1's advice to run production traffic through LOG_ONLY should expect their error dashboards to light up for requests that were served normally. This reinforces FINDING-F5-4a §4 from the opposite direction: there, LOG_ONLY was *invisible* to the metric instruments; here it is *indistinguishable from failure* in the logs.

## 8. What is NOT claimed

* **Nothing about a surface outside AWS-native telemetry.** A reader could proxy every request through their own middleware, or call `ApplyGuardrail` directly and keep the scores. That is a rewrite of §7.1, not an execution of it, and it belongs in the amendment rather than in the verdict.
* **`08b` reaches no verdict.** F3-10's sealed oracle names CloudWatch metrics alone, and the FALSE stands. §4 and §6 are amendment material, not a re-scoring.
* **"A clean request logs no score" is a re-read of one closed window**, at n=30 in one arm and n=1 in another. It is not established as a property of the service, and a second day is exactly what would establish it.
* **Nothing about output filters, other filter functions, or other categories.** One probe policy, one category (HATE), one data path (`context.input.text`), one threshold (0.2).
* **Nothing about whether 17-of-20 generalises.** That ratio is an artefact of this configured threshold and the 20 candidates offered; the *direction* is the finding, not the count.
* **The perfect confusion matrix is a property of the corpus, not of the guardrail.** precision = recall = 1.0 at τ = 0.2 on 30 constructed positives and 30 constructed negatives says the golden set is well separated. It is not an accuracy claim.

## 9. Two instrument defects found in this case (→ DEV-P4-23)

Both are recorded in `DEVIATIONS.md`; both were found by an instrument built to check something else.

1. **The numeric census was type-blind**, as §5 describes. The published score is a string and the census collected numbers.
2. **The sealed claim group was published as a hand-written list of nine ids, and the register says ten.** `claims/triage.csv` has 10 rows whose `cases` column cites F3-10. The missing one, `C-s7-1-prose-004`, is **§7.1 step 3's own sentence** — the unit this entire case exists to answer for — and it was omitted because its `cases` cell reads `"F3-10 F3-9"`, the one F3-10 row a whole-cell comparison misses. Membership is now derived by whitespace token, which is the same read `claims/check_coverage.py` performs on the same column, with the reader living in `08` and `08b` importing it by name so the two files cannot disagree. A mutation test reproduces the whole-cell comparison and asserts it drops at least one row, so the guard is not vacuous.

   **Three independent derivations agree on 10**, which is what makes this a defect in one file rather than an open question: `claims/triage.csv` itself; `V13_CANDIDATES.md`'s *generated* site table for `V13-05`, which expands the case through the coverage checker's read and lists all ten including `C-s7-1-prose-004`; and FINDING-F5-4a §11's separate count. Only the hand-typed tuple said 9. A number three instruments derive is not a number a human should be typing.

   **`results/phase1/F3-10.json` still carries the stale nine.** Re-running `08` costs 122 live requests and two engine mode flips, which would produce a second observation day's worth of traffic to fix a metadata field; the correct 10 is in `results/phase1/F3-10_log_surface_join.json` under `sealed_units_citing_this_case`, and the second-day replicate named in the provenance block will regenerate the parent record. Until then the discrepancy is a known, recorded one rather than a silent one.

## 10. Amendment candidates (drafted, not yet applied)

Candidates go into `build_v13_candidates.py`; `V13_CANDIDATES.md` is generated and is never hand-edited.

**This case discharges `V13-05`, which was the one candidate in the register whose evidence field read `none-yet` and whose subject was a *workflow* rather than a statement of fact.** Its 10 sites are exactly the claim group §9 discusses — `C-s7-1-prose-001/003/004` and `C-s7-1-mermaid-001..005/007/008` — because the generator expands the case through the same whitespace-token read `claims/check_coverage.py` performs. That is the third independent derivation of 10 and it makes §9's defect unambiguous: the register said 10, the V13 generator said 10, and only the tuple typed by hand into `08_score_label_join.py` said 9.

**And V13-05's own proposed amendment is now measured wrong, in both halves.** It reads: *"Name the instrument the reconstruction actually requires (**spans, not metrics**) or, if neither suffices, replace the prescription with one that can be carried out."* Spans do not carry a score — DEV-P4-01 read 60 spans over 58 attribute paths with zero score matches, and this case's own span read records `spans.scored: false` for 16 spans that match the score pattern by *name*. The instrument is **neither** of the two the candidate names: it is the application logs. Written in November when spans were the obvious answer, the parenthetical is the same class of defect as the one it was written to catch — a surface asserted rather than read (`feedback_prose_is_not_verified`). The corrected text below replaces it, and the wrong version stays quoted here rather than being silently overwritten.

### 10.1 §6.2 line 657 — the row that sends a calibrating reader to the wrong surface → `V13-05`

`ConfidenceScore / ConfidenceThreshold` is described as *"Observed score vs. configured threshold **per evaluation**"* and its stated use is *"Threshold calibration (Section 7.1)"*. Per-evaluation is what a 60-second aggregation is not. Proposed: keep the row, and add that these metrics are aggregated at a 60-second period with only configuration-scoped dimensions, so they support *trend* and *alarm* use but cannot be joined to a labelled request unless traffic is under one evaluation per minute — and point calibration at the application logs, where the per-request score lives.

### 10.2 §7.1 step 3 — name the surface, the type, and the direction → `V13-05`, alongside `V13-10`

Three concrete additions, each measured above: the score is in the **application logs** at `body.policy.guardrailFindings.<policyId>.contentFilter[].score` (not in metrics, at usable rates); it is a **JSON string** with four fixed decimals, not a number; and **requests below the configured threshold publish no score**, so a closed window supports raising a threshold but not lowering it — calibrate from the most permissive threshold you are willing to run.

### 10.3 §7.1 — a caution that LOG_ONLY looks like failure in the logs → NEW candidate, adjacent to `V13-12`

A shadow denial writes `isError: true`, `severityText: ERROR`, `decision: DENY` and a `policyMode` naming the policy's mode rather than the engine's. Any reader following the LOG_ONLY→ENFORCE workflow with log-based alerting will page on requests that were served. §7 above.

This is deliberately **not** filed under `V13-12`, which states that in LOG_ONLY the guarantee *"denies nothing and reports nothing"*. On the metric surface that is what F5-4a measured and it stands. On the log surface the opposite holds — LOG_ONLY reports loudly, and reports as an error — so folding the two together would produce a candidate that contradicts itself. Two surfaces, two behaviours, two candidates; `V13-12` gains a cross-reference rather than a rewrite.

### 10.4 Retire the absolute form of DEV-P4-01 wherever it is quoted → touches `V13-05`, and F1-18's framing

`AWS/Bedrock-AgentCore` **does** publish a numeric score, and the logs publish it per request. Any project text saying no surface publishes one must be narrowed to *no span attribute, and nothing joinable per request in metrics*. **This reopens F1-18's "not measurable" framing**, which was written under the absolute reading and now has a per-request numeric score available to it; F1-18 must be re-examined before it is filed as amendment-only material.

## 11. Replication — two calendar days, and the defect the second one found

`check_amendment_readiness.py` derives observation days from `t_start_utc` on the evidence records,
not from a sentence here. It now sees **two**: **2026-08-12** (1,491 call records) and
**2026-08-13** (1,202). The second day is a full re-run of the same three arms — fresh window, 122
requests, 3 policy mutations, 2 mode flips, under $0.03 — plus the closed-window re-read §11 asked
for, which is now an in-repo instrument (`08c_window_audit.py`) rather than a throwaway script.

**Every structural figure reproduced exactly.** Not "within tolerance" — identically:

| reading | 2026-08-12 | 2026-08-13 |
|---|---|---|
| verdict (`EXISTENCE`) | FALSE | FALSE |
| verdict guards | 11 / 11 | 11 / 11 |
| log-surface guards | 7 / 7 | 7 / 7 |
| log events / unparsed | 579 / 0 | 579 / 0 |
| join: label rows / matched / unmatched / duplicate ids | 122 / 122 / 0 / 0 | 122 / 122 / 0 / 0 |
| requests publishing a score | 61 of 122 | 61 of 122 |
| candidate thresholds evaluable | 17 of 20 | 17 of 20 |
| shadow denials / real denials | 30 / 31 | 30 / 31 |
| series colliding in a mixed bucket | 57 | 57 |
| confusion matrix at the configured threshold | tp 30, tn 30, fp 0, fn 0 | tp 30, tn 30, fp 0, fn 0 |
| score published as | JSON **string** `"0.8000"` | JSON **string** `"0.8000"` |

**What differs, and why each difference is expected.** The per-arm logged sums are
24.6 / 0.8 / 24.2 on day 1 and 24.4 / 0.8 / 24.8 on day 2, and the minimum logged score is 0.4
against 0.6 — the scores are a property of the text and the filter, not a constant, and each day's
sums reconcile with that day's metrics. `n_series_read` rose from 233 to 293 because other cases'
probe policies have since published series into the namespace. And `active_golden_set` spanned two
buckets on day 1 but one on day 2, which is exactly where the second day earned its keep.

### The defect a single day could not have found (→ DEV-P4-35)

On first reading, day 2 **failed** `logs_reconcile_with_metrics`: `active_golden_set` logged Σ 24.4
over 30 values against a metric Sum of **23.6 over 29 samples**. The as-run record is archived
unaltered at `results/phase1/archive/F3-10_log_surface_join__day2_asrun_bucket_defect_2026-08-13.json`.

The disagreement was in the **reader**. A log event is stamped when the request is processed; a
CloudWatch datapoint is bucketed by the service's own emit time, up to the publish lag later. Day
2's window ran `1786588205.003` → `1786588260.386`, so one detection of 30 was bucketed at
`1786588260` while all 60 log rows named `1786588200` — and **23.6 + 0.8 = 24.4**, the logged sum
exactly. Day 1's window crossed a boundary too, but its own log rows named *both* buckets, so the
omission never occurred. `test_the_grant_changes_nothing_on_day_1` asserts that: a zero-slack reader
still passes day 1 on all three arms. **The first day's pass was not evidence that the reader
attributed datapoints correctly; it was evidence that, that once, it did not need to.**

The fix (`SLACK_PERIODS = 1`) has two halves, each load-bearing on a *different* arm, each pinned by
a mutation arm driven by the published records:

| mutation | 2026-08-12 | 2026-08-13 |
|---|---|---|
| shipped | all three arms agree | all three arms agree |
| no grant | still passes | `active_golden_set` 23.6 / 29 vs 24.4 / 30 — **fails** |
| grant without withholding | `active_one_per_minute` 25.0 / 31 vs 0.8 / 1 — **fails** | 25.6 / 31 vs 0.8 / 1 — **fails** |

Both days were then re-derived by that one fixed instrument — a reader defect must not be measured
as a difference between days — and day 1 reproduced its as-run figures arm for arm, which
`test_the_fix_did_not_move_day_1` pins.

### The closed-window re-read, and what it can and cannot settle

`08c_window_audit.py` re-read day 1's closed window **23.6 hours** later: **56 of 56** datapoints
present, **212 of 224** compared fields bit-identical, **0 late arrivals**, **0 changed**, **0
vanished**, 11 / 11 guards. The 12 non-identical fields differ by ≤ **1.4e-14** (e.g. a recorded
`23.800000000000015` re-reading as `23.8`), i.e. CloudWatch's summation order differs between reads.
That is published as `within_tolerance_but_not_identical` with deltas rather than hidden behind the
tolerance.

What this changes is a **bound**, and only that. The absence in §6 — 61 of 122 requests publishing no
score — was measured 120 s after the traffic (`HARVEST_SETTLE_S`, chosen against F7-6's p90 publish
lag of 11.485 s). Re-read 23.6 h later, the same absence is bounded by the longer lag. It still
cannot distinguish "never published" from "lost before publication"; that needs the fresh window,
which day 2 supplied.

Two of my own aggregation mistakes were caught by that instrument before anything was published, and
both are recorded in its source: summing the four byte-identical `ConfidenceScore` dimension
roll-ups (which quadruple-counted, reading 98.4 against a logged 24.6), and treating 10 quiet
foreign dimension combinations — other cases' probe policies, correctly reading 0.0 — as
disagreements. Comparison is now **per dimension combination**, which is both correct and stronger:
every roll-up must agree independently, and all 4 do.

## 12. Cross-references

* **`DEVIATIONS.md` DEV-P4-01** — the span-shape probe that reordered Phase 4. Its absolute reading is refuted here (§5); its span-level claim survives.
* **`DEVIATIONS.md` DEV-P4-22** — counting un-evaluated requests as usable, which is why `n_evaluated` is a guard in this case rather than a note.
* **`DEVIATIONS.md` DEV-P4-23** — the two instrument defects in §9, including the stale nine-id list still in `results/phase1/F3-10.json`.
* **`DEVIATIONS.md` DEV-P4-35** — the bucket-attribution defect the second day exposed, its two mutation arms, and the four flags that let one instrument re-derive both days (§11).
* **`V13_CANDIDATES.md` V13-05** — the candidate this case discharges, and whose own "spans, not metrics" parenthetical it corrects (§10). Its 10 generated sites are this case's claim group.
* **`V13_CANDIDATES.md` V13-10** — amends §7.1's promotion-gate sentence at line 737, the same prose block as §10.2. The two candidates touch neighbouring clauses of one paragraph and must land in the same v1.3 pass.
* **`V13_CANDIDATES.md` V13-12** — *"in LOG_ONLY it denies nothing and reports nothing"*, measured on the metric surface. §7 here measures the log surface, where LOG_ONLY reports loudly and reports as an error. Cross-reference, not a merge (§10.3).
* **`results/FINDING-F5-4A.md` §4** — LOG_ONLY invisible to the metric instruments the document names. §7 here is the same mode failing in the opposite direction on the log surface.
* **`results/phase1/F7-6.json`** — the p90 publish lag of 11.485 s that makes this case's 120 s settle a bound rather than a hope.
* **`results/phase1/F3-10_window_audit.json`** — the closed-window re-read, 23.6 h after the fact: 56/56 datapoints, 212/224 fields bit-identical, 0 late arrivals. The same p90 lag is why its 12 non-identical fields (≤ 1.4e-14) are published as a summation-order observation rather than absorbed by a tolerance.
* **F2-2 / F2-3 / F2-4** — the τ-sweep. §6's asymmetry constrains it: the sweep can only tighten from whatever threshold was configured when the traffic ran, so a sweep design that assumes both directions from one window is unsound.
* **F1-18** — its "not measurable" framing was written under DEV-P4-01's absolute reading and must be re-examined (§10.4).
* **F3-9** — shares `C-s7-1-prose-004`, the sealed unit whose omission is §9's second defect.
