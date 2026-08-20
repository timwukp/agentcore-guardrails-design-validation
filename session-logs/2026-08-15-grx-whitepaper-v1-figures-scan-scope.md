# 2026-08-15 — GRX validation: whitepaper v1, the eight figures, and two scope defects

Session: `fd230f67-029c-480f-a070-54c1670fc4e4` (resume with
`claude --resume fd230f67-029c-480f-a070-54c1670fc4e4` from `/Users/tmwu/Downloads`).
Working tree: `/Users/tmwu/Downloads/grx-validation` (not a git repo — Git Data API pushes only).
Repo: `github.com/timwukp/agentcore-guardrails-design-validation`, main at `e6534f0f`.

## What the user asked for

`/deep-research`: an AWS-official-style **whitepaper** of the results so far, in which every
viewpoint and method has been validated, with test results and test methods cited in appendices,
results shown as rigorous scientific charts, chapters designed on purpose, and practical enough
that a reader can use it to guide **end-to-end AgentCore security design**. Separately: research
objectively where the report and the tests are still deficient, and write that into a future-work
to-do list.

Controlling instruction: `先開始做第一版本，然後再繼續不斷迭代，不用完美的，只是如實地紀錄哪些仍要繼續測試`
— draft v1 now, iterate after, it need not be perfect, and it must honestly record what still
needs testing. Then `carry-on` twice, and finally: `carry-on, at the same time, log everything,
and be ready shutdown the laptop, you can resume from the session`.

## Approved iteration order (stated by me, approved with `carry-on`)

1. Write the figure scripts — the paper was all tables, because a figure that cannot be
   regenerated does not ship.
2. Fix FUTURE-WORK item 22 and write DEV-P4-41.
3. Re-run the full offline suite and open a PR.
4. Continue the day-2 batch.

## 1. Figures — 7 drawn, 1 blocked, 4 defects caught only by looking

`tools/whitepaper_figures.py`, run under `.venv-figs` (matplotlib 3.11.1 — a separate venv so the
sealed oracle's pinned botocore is not disturbed). Outputs 7 PNGs plus
`results/figures/MANIFEST.json`. `--check` re-derives the numbers and compares them to the
manifest — **numbers, never PNG bytes**, so a matplotlib bump cannot red the gate while a
genuinely stale figure does.

| # | Figure | State |
|---|--------|-------|
| 1 | Verdict distribution over 91 published cases | drawn |
| 2 | Evidence by document section | drawn |
| 3 | Measured latency vs documented bands (F6) | drawn |
| 4 | Censored score lattice (F3-10), both days | drawn |
| 5 | Detection recall by arm (F5-6) | drawn |
| 6 | Coverage matrix vs OWASP Agentic v1.1 | **BLOCKED** |
| 7 | Mode-flip and reconvergence intervals (F5-2), both days | drawn |
| 8 | Metric/log agreement (DEV-P4-27), both days | drawn |

Figure 6 stays blocked rather than fabricated: `results/CROSSMAP-ACG-THREATS.json` grounds only
**5 of the 17** OWASP Agentic v1.1 threat titles; the other 12 are TID-only. Shading 12 columns
"not established" would report *our* missing source as *AgentCore's* missing coverage. Blocked
state recorded three ways — in the manifest (machine-visible), in §2.3 (the argument), and as
FUTURE-WORK item 28 (with its closing condition).

### The four defects, all of which survived a clean script run

- **Titles silently clipped.** After dropping `bbox_inches="tight"`, two of seven figures shipped a
  truncated sentence. Cause: `ax.set_title(loc="left")` anchors at the **axes**, and the axes' left
  edge sits wherever the longest y tick label pushes it — 40% across the canvas on figure 3. Fixed
  at the producer with a canvas-anchored, width-wrapping `headline()` helper, not by tuning seven
  figsizes.
- **Figure 4 drew censored lattice points as bars 44.2 tall** — readable straight off the y-axis as
  a count of 44, four away from the real 0.8 bar at 48. Now a full-height hatched `axvspan`, which
  carries no magnitude.
- **Figure 5's x-axis ran to 1.28** on a proportion axis (to fit annotation text), showing recall
  above 1.0, plus an unexplained `axvline(0.5)`. Clamped to [0, 1.02]; annotation moves left when
  `hi >= 0.55`; line removed.
- **Figure 7 was wrong three ways.** (a) It plotted the restore at `allowed_at + restored_at` =
  26.5 s while labelling it "+13.3 s" — F5-2's two timing blocks have **different origins** and the
  record holds no shared clock, so no single timeline can honestly exist. (b) It labelled the
  accept **HTTP 200**, copied from the record's `why_it_is_recorded` *prose*; the measured
  `chain.flip.http_status` is **202**. (c) It showed only day 2, dropping day 1 — the same quantity
  is 14.2 s on day 1 and 13.2 s on day 2, and one day alone reads as a coincidence. Rebuilt as two
  panels with per-call origins, both days plotted, every label read from the record, and the
  panel-B scale ratio derived from the axes (renders 22x) instead of asserted.

Lesson recorded in FUTURE-WORK item 9 and WHITEPAPER Appendix D: **a generated figure is not
verified until the rendered image is inspected.** All four passed the script.

Byproduct: F5-2's `data_plane_reconvergence` appeared **nowhere** in the paper before this session
— first denial 305.8 s (day 2) / 325.0 s (day 1), three consecutive denials 326.4 / 345.6 s,
`n_that_were_still_authorized: 0`. §11.4 now states it and draws the conclusion: *an alarm fires
after the interval; a denial removes the interval.*

## 2. DEV-P4-41 — 607 evidence records unmerged, two gates called it clean

`runner/.state/incoming/20260814T162515Z/` held 607 records while two gates reported clean. General
form: **a gate whose scope is expressed as a list of names cannot notice a new name.**
`check_redaction.py`'s venv skip became a directory-name **prefix** predicate (699 files before the
refactor, 699 after — the refactor changed the rule, not the coverage). `runner/merge_evidence.py`
plus its test is the missing merge step. `results/DIAG-vpc-runtime-20260814T092455Z.json` was
recovered by it. The item-22 correction rides along: "4 problems in 92 assertions" was a
test-suite number that I attributed to the gate from memory.

## 3. Full offline suite — and DEV-P4-42, the same defect a second time

`./verify_phase0.sh` → **2 failed / 3143 passed / 9 skipped in 1:14:23**. (Previous full run: 8
failed / 3117 passed; those three causes are fixed and confirmed.) Both new failures were caused by
this session's own additions, and both are worth more than their fixes:

**(a) `lib/tests/test_property_not_called.py`** reported 16 property-called-as-method findings, all
16 inside `.venv-figs/.../matplotlib` and `PIL`. Its scope rule was a **set of venv names**
`{".venv", ".venv-oracle", ".venv-baseline"}`, which cannot see `.venv-figs`. This is DEV-P4-41's
defect again, four days later, in a different gate — and the lesson had *already* been learned once
in `test_module_name_collisions.py`, whose comment records an equality test letting site-packages in
so a scan read 1,272 files instead of 78. Fixed in one scanner, never propagated
(`feedback_fix_producer_not_janitor`).

Census of the 11 repo-wide `rglob("*.py")` scanners: **7 already prefix-safe**, **4 defective**
(`test_property_not_called`, `test_results_writes_are_masked`, `test_account_id_choke_point`,
`test_probe_guardrail`). Two went red; the other two passed **by luck**, because matplotlib's
source happens to contain no `get_caller_identity()[...]` and no `create_probe_guardrail(...)`.

Fix: one shared `lib/tests/scan_scope.py` — `SKIP_DIR_PREFIXES = (".venv",)`, exact
`SKIP_DIR_NAMES` for non-family trees, `out_of_scope()`, and `py_files()` which owns the
zero-file floor so every caller inherits it. All four scanners import it.

New `lib/tests/test_scan_scope.py` guards **both directions**:
- every venv actually on disk is out of scope (with a ≥2 precondition so the test cannot pass by
  having nothing to check);
- a venv that does not exist yet is out of scope (fixture name assembled from pieces, so the guard
  is not its own match — `feedback_self_scanning_guard`);
- the repo's own named files are *in* scope, each asserted to exist so the assertion is not vacuous;
- `py_files()` reads no `.venv*` and no `site-packages`, with a **ceiling as well as a floor**
  (100 < n < 900) — a floor cannot see a scan that reads too much, which is the direction that
  failed here;
- **no scanner enumerates the venv family by name.** Threshold is **two or more** venv-prefixed
  strings in one literal: one name is a legitimate probe (four sites name `.venv-oracle` as their
  test subject), two or more is an enumeration of a family a prefix already covers.

Mutation-checked: dropping a three-name set into `lib/_mutant_scope_probe.py` fails the guard;
probe removed afterwards.

**(b) `lib/tests/test_results_writes_are_masked.py`** flagged three real violations, all mine:
`tools/whitepaper_data.py:248,249` and `tools/whitepaper_figures.py:633` wrote into `results/`
without masking. `results/` is the distributable record. Fixed by masking through
`lib/redact.mask_text` **before the `--check` comparison**, not only before the write, so both
paths compare the same bytes. On clean input the mask is a no-op — which is the point: a guarantee
that holds because the inputs happen to be clean is not a guarantee. Not waived: the WAIVED
inventory's argument ("masking five other families' scripts is a change to working code for a
latent risk") does not apply to code written today by me.

## Verified end state

- `tools/whitepaper_figures.py --check` → `FRESH — every figure's numbers match MANIFEST.json`, rc 0
- `check_redaction.py` → **703** files, PASSED, rc 0 (701 before the scope-fix files were added)
- `tools/whitepaper_data.py --check` → FRESH, rc 0
- re-verified after the two fixes: **84 passed** across the eight affected scanner tests, **72
  passed** across the deviation-structure tests
- all 7 embedded image paths resolve; no stale figure wording in `WHITEPAPER.md`
- `FUTURE-WORK.md` is a **28-item** register (was 21)
- CENSUS unchanged: 93 registered → 92 verdict-eligible → **91 published**; TRUE 46 / FALSE 23 /
  INCONCLUSIVE 20 / RECORDED 2; 546 claims triaged, 385 with a case, 161 caseless, 0 caseless
  without a written exclusion reason
- cost added this session: **$0** — every action was a local file read/write

## Still open at shutdown

- **PR #32 is OPEN and awaiting the user's merge** —
  `https://github.com/timwukp/agentcore-guardrails-design-validation/pull/32`, branch
  `feat/whitepaper-v1` = `696c1b2cb470`, based on `main` `e6534f0f11d5`. Final diff **152 paths
  (82 added / 70 modified / 0 deleted)**; +88,884 / −4,241; `mergeable_state: clean`. All 152 blob
  SHAs matched a local `git hash-object` and the branch tree verified 152 present / 0 absent.
  Binary push path was verified before use: `api_push_pr.upload()` reads `"rb"`, sends
  `encoding: "base64"`, and raises on any SHA mismatch. **I did not merge** — that is the user's
  action; the next agent step after the merge lands is to verify `main`'s tree blob-by-blob, because
  `delete_branch_on_merge: false` means a merged PR is not automatically a landed one.
  Commit message `/tmp/grx_wp_msg.txt` and PR body `/tmp/grx_wp_body.md` live only in `/tmp` and
  must be rewritten from this log if the PR ever has to be rebuilt.

  **Two follow-up commits were pushed onto the same branch** (PR #32 is now **3 commits / 153
  files**, `compare main...feat/whitepaper-v1` = `ahead_by 3, behind_by 0`). The pusher could not do
  this: it only ever cut a new branch and opened a new PR, so correcting a one-line mistake inside an
  open PR meant a second PR — and with `delete_branch_on_merge: false` a PR based on another cannot
  retarget when the first merges. `tools/api_push_incremental.py` gained **`--onto`**: parents the
  commit on the *branch's* head (parenting on `main` would silently revert every other file the
  branch changed), PATCHes the ref instead of POSTing it, reads the phantom-deletion guard against
  the branch's tree rather than main's, refuses `--merge`/`--title`, and **fails loudly if no open PR
  tracks the branch**, because a commit nobody's PR contains is an invisible push. All five argument
  guards exercised: each exits 1 with its own message. Redaction gate re-run before **each** push —
  703 files, PASSED, rc 0 both times.

  Commit 2 fixed the banner. **Commit 3 fixed commit 2**: commit 2 wrote the branch head SHA and the
  file count *into* `RECONNECT.md`, and commit 3 made both wrong — the same defect as the "NOT
  OPENED" banner, one iteration later. The banner now names only the base commit (which does not
  move) and prints the `gh api` call that reads head SHA / changed-file count / mergeable state live.
  **A number a resuming session must trust does not belong in a file that changes underneath it.**
- **Seven day-2 replications**: F6-1…F6-5, F6-8, F4-6 (needs `--state` or a rebuilt testbed).

  **Measured correction, 2026-08-15: ALL of F6 must run on the LAPTOP, not just F6-8.** The plan
  said F6-1…F6-5 could ride the runner. Every F6 day-1 `environment.json` records
  `platform: "macOS-26.6-arm64-arm-64bit"` — all three groups (`F6-1_3_4_9`, `F6-2_5`, `F6-6_7_8`)
  ran here on 2026-08-11. F6 measures **latency**, and the runner is AL2023 on EC2: a different
  platform *and* a different network position, i.e. varying the instrument in precisely the
  dimension a replication exists to hold fixed. The dangerous part is that **no gate would catch
  it** — `SEALED_FIELDS` is `("kind", "thresholds", "planned_n")`, platform is not sealed — so the
  confound would land silently and any day-2 difference would be unattributable. DEV-P4-37's
  laptop-only rule for F6-8 (paired client-side wall clocks) is a *stronger* case for the same
  conclusion, not a narrower one.

  **No live run was started.** Output lands on the instance and the only merge path is
  `runner/sync.py pull`, which the user rejected twice and I must ask before retrying; launching
  more jobs would pile up unpullable output, and F6 cannot run there anyway. F6-8 and the rest of
  F6 need the laptop, which is being shut down.

  Checked so the teardown decision is not blind: **F5-8's day-2 output is not hostage to the
  instance.** `teardown.py` terminates it, but `out/20260815T061609Z/` is in the bucket —
  **31,989 objects / 177 MB**, including 54 F5-8 paths. With F6 laptop-only, only F4-6 and F2-1
  still need the runner.
- **Three user decisions**: the F8-5 / DEV-P4-40 erratum bundle (Tier-1, item 27 — length is
  validated *before* the tier gate, so both days **support** the documented 1,000-char limit, the
  opposite of what v1.4 §3.4 publishes); F10-1's disposition; whether to fix `runner/sync.py pull`.
- Handover bundle `~/Downloads/AgentCore-guardrails-closed-loop-practices/` still says "21 named
  deficiencies" in two places (now 28); then patch `MANIFEST.sha256` and `shasum -c`.
- Runner `i-0f90ac6377bba523b` is **RUNNING** (~$0.58/day). `runner/teardown.py` when the batch is
  done — with `--keep-bucket` (the default); the bucket holds the only copies of F10-3's and
  F3-11_snapshot's call records.
- zh-TW edition of the whitepaper, once the English edition stabilises.
