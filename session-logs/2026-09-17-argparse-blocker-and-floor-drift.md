# 2026-09-17 — an interpreter upgrade turned a help string into a blocker, and five floors had drifted

Session: `fd230f67-029c-480f-a070-54c1670fc4e4` (resume with
`claude --resume fd230f67-029c-480f-a070-54c1670fc4e4` from `/Users/tmwu/Downloads`).
Working tree: `/Users/tmwu/Downloads/grx-validation` (not a git repo — Git Data API pushes only).
Repo: `github.com/timwukp/agentcore-guardrails-design-validation`, main at `eae5afbf3806`
(PR #56, the publish-and-probe documentation, merged by the user).

This round has no plan step of its own. Step 5 of `~/.claude/plans/lovely-whistling-sphinx.md` is
complete and merged; the two things I had said I would do next were (a) verify that main actually
landed and (b) re-sync the hand-over bundle. (a) passed. (b) could not start, and why it could not is
the whole content of this round.

## First, the thing that was supposed to be routine

Main was verified **blob by blob** rather than by reading the merge's own word for it: 1040 remote
blobs against 1040 local files, 0 differing / 0 remote-only / 0 local-only at
`eae5afbf3806`, and the head branch confirmed auto-deleted (`delete_branch_on_merge` — merged is not
landed, `feedback_merged_pr_is_not_landed`).

## Then the bundle re-sync did not run at all

```
$ python3 tools/sync_handover_bundle.py ~/Downloads/AgentCore-guardrails-closed-loop-practices
ValueError: badly formed help string
  TypeError: %o format: an integer is required, not dict
```

Raised inside `add_argument`, before a single argument was parsed. The line, shipped 2026-08-17:

```python
help=f"permit deleting more than {PRUNE_FRACTION:.0%} of the mirror"
```

The percent is not in the source. The **format spec** `.0%` puts one there, so the rendered help reads
`permit deleting more than 5% of the mirror` — and argparse renders every help string by doing
`help % params` with a dict (`HelpFormatter._expand_help`). `5% of` therefore parses as the conversion
`% o`: octal, space flag, handed the params dict.

Two facts made this a blocker rather than a bug report:

1. **On Python 3.12 it fires only inside `--help`.** Nothing in this repo had ever asked this tool for
   help, so the defect rode through four bundle syncs, two pull requests and a 32-arm test file of the
   tool's own — those tests call `main(argv)` with real arguments, which never reaches the formatter.
2. **Python 3.14 validates help strings inside `add_argument` itself.** When `python3` on this machine
   became 3.14.7, every invocation died at parser construction — including the `--apply` the re-sync
   needs. The defect did not change; the interpreter started reading it.

That is the interesting shape here. A latent defect in a string nobody reads was promoted to a hard
blocker by a dependency upgrade nobody in this repo made, and the only guard that could have caught it
early is one that performs the operation argparse performs.

### The fix, and why the comment is long

```python
ap.add_argument("--allow-prune", action="store_true",
                help=f"permit deleting more than {PRUNE_FRACTION * 100:.0f}%% of the mirror")
```

The doubled `%%` is load-bearing and looks like a typo, so the reason is in the file next to it. Under
both interpreters `--help` is now rc 0 and renders `permit deleting more than 5% of the mirror`.

### The guard: `lib/tests/test_argparse_help_strings.py` (new, 8 arms, 47.10 s)

The check is **not** a rule about percent characters — `%(default)s` and `%(prog)s` are argparse's own
substitutions and belong in help text. What is checkable is narrower: *the string must survive the
operation argparse performs on it*. So the arm does that operation, with `params` built from a real
`argparse.Action`'s attributes plus `prog`, and fails on the **exception**, not on a character.

| arm | what it holds |
|:---|:---|
| `test_every_help_string_survives_the_expansion_argparse_performs` | every `help=` in scope, floor `MIN_HELP_STRINGS = 120` against 162 measured — a scan that reads almost nothing reports clean over the whole repo |
| `test_no_help_string_is_assembled_out_of_reach_of_this_check` | dynamically assembled help strings must number **zero** (measured 0 of 162); the first one to appear fails this file instead of opening a blind spot |
| `test_the_expansion_check_discriminates` | `5%` convicted, `5%%` acquitted, `%(default)s` / `%(prog)s` acquitted |
| `test_the_scan_reads_a_format_spec_not_just_the_literal_parts` | the mutation arm over the shape the real defect had — a flattener that read only an f-string's literal parts would have seen `permit deleting more than  of the mirror` and reported clean on the exact line this file exists for |
| `test_the_repaired_tool_actually_prints_its_help` | subprocess `--help`, rc 0, rendered text asserted — the static check corresponds to what an interpreter does |
| `test_shapes_that_must_be_convicted` (×3) | `100% of the tree`, `%d files`, `% o` |

The scope is **every `help=` keyword in every in-scope `.py`**, not calls whose receiver is named
`add_argument`: a scope written as a list of call names cannot notice a new one
(`feedback_scope_as_namelist`). The limits are in the module docstring rather than left to be
discovered — an interpolated *value* containing a percent is invisible (the format spec is read, the
value is not), and `description=` / `epilog=` are deliberately out of scope because argparse does not
`%`-expand them.

### Mutation-checked against the real file, not a fixture

A synthetic mutant proves the flattener; it does not prove the sweep *reaches* the shipped tool. So a
one-off harness (`/tmp/grx_help_mutation.py`, deliberately outside the repo) wrote the pre-fix line
back into `tools/sync_handover_bundle.py`, ran only the sweep arm, and restored from a pristine copy
under `try/finally` **and** `atexit` **and** SIGTERM/SIGINT/SIGHUP, asserting sha256 equality
(`feedback_killed_harness_races_next`):

```
mutant installed: f2a4b1cfab50 (was a6510682c854)
sweep under the mutant: rc=1
  tools/sync_handover_bundle.py:378  TypeError: %o format: an integer is required, not dict
restored: sha256 MATCHES the pre-mutation file
```

Repo-wide grep confirms one instance of the defect class, now fixed.

## The second finding: five of fifteen floors had drifted

Adding a test file meant raising one floor in `verify_phase0.sh`'s `TEST_SPECS`, and the honest way to
raise one is to measure all fifteen. Five sat **below** their directory's yield — 306 arms of slack,
**298 of it older than this change**:

| directory | floor | collected |
|:---|---:|---:|
| `claims/tests` | 423 | 471 |
| `lib/tests` | 882 | 992 |
| `f5_redteam/tests` | 720 | 789 |
| `f1_config/tests` | 170 | 175 |
| `tools/tests` | **48** | **122** |

`tools/tests` is the one to read twice. Its floor was the count on the day the directory was added, so
`test_sync_handover_bundle.py` — 32 arms over the only tool in this repo that **deletes outside it** —
plus two more files could have been removed whole and the gate would have printed `PASS  test suite`.
All five re-baselined to measured yields, with the measurement and its cause recorded above the loop as
**"SECOND RE-BASELINE, 2026-09-17"**.

The cause is written into the script itself: floors are bumped one file at a time, deliberately, which
is the right discipline and is also exactly why they fall behind. This is the **third** instance in the
same list (`lib/tests` 100-vs-350 on 2026-08-14 was the first).

### So the discipline got a detector instead of a register entry

Three new arms in `claims/tests/test_verify_phase0_gates_every_test_directory.py`. A spec has two
halves; that file has checked *membership* since it was written, and membership is not the half that has
cost anything. Both times a floor went stale, every directory was correctly listed.

- `test_the_floors_do_not_drift_far_below_what_their_directories_collect` — collects all fifteen gated
  directories in **one** subprocess and buckets the collected ids by directory, then requires
  `collected - floor <= max(12, 8% of collected)` per directory. One invocation, not fifteen, because
  fifteen interpreter starts would put minutes into an arm the sweep runs every round; verified against
  the per-directory method the gate itself uses — the combined buckets equalled the fifteen separate
  counts exactly, and their sum equals the run's own `N tests collected` line, which is the arm's
  cross-check (a parse that reads no ids and a directory that collects nothing look identical from a
  total, `feedback_zero_needs_a_ran_flag`).
- `test_the_slack_bound_convicts_the_drift_this_repo_actually_had` — the control, over the five real
  pairs above. **8% is calibrated, not round**: it convicts four of the five and acquits `f1_config`,
  whose gap was five arms and where forcing an edit would be noise. The `max(12, …)` floor is what keeps
  the script's other written rule true — *adding tests must never require editing this list* — since
  twelve is about one new test file's worth of arms.
- `test_mutation_the_floor_tools_tests_actually_shipped_with_fails_the_drift_arm` — puts `"tools/tests:48"`
  back into a **tmp_path copy** of the script and runs the whole arm, measurement and report included,
  so the mutated floor is never written into the tree.

I chose this over filing it as FUTURE-WORK item 42, and the reason is worth recording because it is a
constraint the repo imposes on itself: the register's size is derived, and adding an item ripples an
exact count across four prose sites in three documents. That cost is right for a deficiency being
*carried*; it is the wrong shape for one being *closed in the same change*.

## Verification

| gate | result |
|:---|:---|
| `claims/tests/test_verify_phase0_gates_every_test_directory.py` | 9 passed, 63.33 s (was 6 arms) |
| `lib/tests/test_argparse_help_strings.py` | 8 passed, 47.10 s |
| blast radius: `tools/tests` + the membership arm | 121 passed, 7 skipped, rc 0, 3:39 |
| six-directory sweep (final tree) | **4 failed, 2017 passed, 10 skipped, 4265.28 s (1:11:05), rc 1** — `session-logs/tests-20260917-argparse-floors.{log,rc}` |

The sweep's rc came from pytest directly, and the arithmetic reconciles in both directions:
`4 + 2017 + 10 = 2031`, which is the sum of the six directories' collected counts
(474 + 992 + 122 + 8 + 378 + 57). A total that does not decompose is a total that could be hiding a
directory that collected nothing.

**The red set diffed by NAME** against FUTURE-WORK item 37's table — the arithmetic that item says
nobody performs:

| red | in item 37's table |
|:---|:---|
| `claims/tests/test_cited_paths_exist.py::test_every_cited_repo_path_exists` | yes |
| `claims/tests/test_hash_citations.py::test_every_elided_hash_citation_resolves_to_a_derivable_hash` | yes |
| `claims/tests/test_repo_copy_exclusions.py::test_every_dynamic_copy_source_is_declared_and_still_there` | yes |
| `lib/tests/test_results_writes_are_masked.py::test_a_write_in_a_results_module_is_masked_or_placed_outside_results` | yes |

Set-equal: no new red, and none of the four closed. They remain item 37's business.

Two process notes:

- The background harness reported **"exit code 0"** for this sweep. The wrapper's last command was
  `echo`, so that 0 is the wrapper's, not pytest's — which is why the rc was written to a file from
  `$?` immediately after pytest and read from there (`1`). Third instance of
  `feedback_task_exit_code_annotation` in this project's logs.
- The sweep's log was written to `/tmp` during the run and copied into `session-logs/` afterwards,
  because the suite's write guard voids its tree-diff channel if another process writes into the tree
  while it runs.
- One earlier sweep was **killed on purpose** (`TaskStop`) when I decided to add the drift arm before
  measuring, and its `/tmp/grx_sweep.log` and `.rc` were deleted rather than kept — a stale rc that a
  later reader takes for this round's result is the failure mode item 37 already documents.

`check_redaction.py --verbose` ran **last**, after the log above and this file were in the tree, with
its rc read directly and never through a pipe: **rc 0, `PASSED — no unredacted cloud identifiers in
1116 scanned files`**, with a second pass after this file's last edit agreeing at the same count. Both
passes' output went to `/tmp`, so running the gate did not change its own subject.

## Deliberately not done

- **The four standing reds are still red.** Each needs one ledger entry and one sentence; that is item
  37's close condition and it is not this round's subject.
- **The bundle re-sync itself** is the next action, now that its tool runs. Its README carries two
  numbers `check_claims()` does not cover — the commit line at `README.md:101`
  (`a4d836dd91f3`, 776 blobs, a month stale) — plus a deficiency count of 40 against a register of 41,
  which `check_claims()` **does** cover. The bundle carries unredacted identifiers and is never
  uploaded.
- **No new FUTURE-WORK item**, for the reason given above: the defect this round found was closed in
  it, not carried.
- **No floor was raised for the arms added here.** `claims/tests` collects 474 against a floor of 471,
  which is inside the slack the new arm allows, and the script's own rule is that floors move when a
  suite grows by a **file**.
