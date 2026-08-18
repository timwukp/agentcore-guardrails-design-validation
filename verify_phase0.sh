#!/usr/bin/env bash
# Every Phase 0 gate, in one command. Exit 0 only if all of them pass.
#
# Why a script rather than a remembered list of commands: the list has already
# grown from three items to six, and a gate that nobody remembers to run is
# indistinguishable from a gate that does not exist. Running them together also
# catches cross-artifact staleness — the register can only match the triage if
# both were regenerated from the same rules.
#
# `set -u` and explicit rc capture, not `set -e`: a bare `set -e` would abort at
# the first failure and hide how many gates are broken, and per
# feedback_batch_loop_exit_code a loop's exit status is only its last iteration.
# Each gate's status is recorded individually and the summary is the AND of all.

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 2
ROOT="$PWD"
PY="${PYTHON:-python3}"

# A gate whose tool is missing must not be reported as passing
# (feedback_guard_tool_exit_codes: a bare command can exit 127 non-interactively).
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "FATAL: $PY not found — gates cannot run, so nothing is verified" >&2
  exit 2
fi
if ! "$PY" -c 'import pytest' >/dev/null 2>&1; then
  echo "FATAL: pytest not importable — the test gate cannot run" >&2
  exit 2
fi

names=()
codes=()

gate() {
  local name="$1"; shift
  printf '\n\033[1m=== %s ===\033[0m\n' "$name"
  "$@"
  local rc=$?
  names+=("$name")
  codes+=("$rc")
  if [ "$rc" -eq 0 ]; then
    printf '\033[32mPASS\033[0m  %s\n' "$name"
  else
    printf '\033[31mFAIL (rc=%d)\033[0m  %s\n' "$rc" "$name"
  fi
  return 0
}

# The test gate runs every directory in TEST_SPECS (defined just above run_tests, so the
# gate's own label can count it instead of stating a number). pytest exits 5 when it
# collects nothing, so a wholesale disappearance already fails — but one directory quietly
# contributing zero tests would not, and that is the same defect as an assertion floor set
# below the current total. So the collected count is pinned per directory.
#
# This comment used to open "The test gate runs SEVEN directories" and the gate's label read
# "all 11 test directories", while the loop ran TWELVE — three hand-typed statements of one
# quantity the list already holds, all three wrong, none of them checked by anything. Both
# are derived now (feedback_prose_is_not_verified). Found 2026-08-17 by reading the output of
# a green run: every gate passed and the label was still false.
#
# Floors are the yield at the time of writing, rounded down. They are a tripwire for
# a directory that stops being collected (a renamed file, a broken import, a path
# that moved), not a target: adding tests must never require editing this list.
#
# But a floor far below the current yield is the defect it was written against, only
# quieter: `lib/tests` sat at a floor of 100 while collecting 350, so deleting
# test_oracle.py, test_awsclients.py and test_checkpoint.py outright — 197 arms, the
# entire oracle and client layer — would have passed this gate. Same reasoning as
# lib/oracle.py's MIN_BOUND_CASES. Floors are therefore raised whenever a suite grows
# by a file, which is a deliberate edit and leaves a diff; they are NOT raised for
# individual arms, so adding a test still never requires touching this list.
#
# The four family directories were added when Phase 1's case scripts landed. They are
# listed here rather than left to a glob for the same reason the floors exist: a glob
# over `*/tests` would silently cover a directory that was deleted, and "no directory,
# no tests, no failure" is the defect this whole function is written against. A new
# family therefore requires one line here, which is a deliberate edit and leaves a diff.
#
# The list lives at file scope so that the gate's label can count it (`${#TEST_SPECS[@]}`)
# rather than restate it. The per-floor rationale — one entry per bump, deliberately kept as
# a record — is inside run_tests, immediately above the loop that reads this.
TEST_SPECS=("claims/tests:423" "lib/tests:882" "f5_redteam/tests:720" \
            "f2_determinism/tests:34" "f3_efficacy/tests:268" \
            "f8_regional/tests:152" "f10_billing/tests:80" "infra/tests:79" \
            "runner/tests:94" "f9_failsecure/tests:106" "f1_config/tests:170" \
            "tools/tests:48")

run_tests() {
  local rc=0
  local dir floor got
  # claims/tests 270 -> 286: test_behavior_changes.py added 16 arms pinning every date and
  # count in AWS-BEHAVIOR-CHANGES.md to the evidence. Raised because the suite grew by a
  # FILE, per the rule above; the arms the same change added to test_amendment_gate.py and
  # test_v13_candidates.py deliberately do not move the floor.
  #
  # f3_efficacy/tests 55 -> 71: test_roc_lattice.py added 16 arms over roc_points() and the
  # strength lattice. That code had ZERO coverage, which is how the lattice went from four
  # settings to three — and `interior`'s definition with it — without one test objecting.
  # F3-9's published vertex count now has arms behind it (11/11 mutants killed).
  # lib/tests 455 -> 501: test_require_measured.py added 15 arms over the completion gate,
  # plus 9 in test_checkpoint.py (the code-less transport wrapper, built through the real
  # capture() path) and 4 in test_oracle.py (the roll-up n_met basis). The gate those cover
  # was `n_usable > 0` and nothing else, which is how a run published verdicts from 3% of
  # its designed sample at rc=0 (DEV-P1-11, DEV-P1-12).
  #
  # lib/tests 501 -> 518: test_redact.py added 17 arms over lib/redact.py and the two
  # writers into results/. The first live run wrote the account id into 82 files and 1,122
  # lines (DEV-P1-13); these arms hold both halves of the fix, including the deliberate
  # asymmetry that evidence/ keeps the full ARN.
  #
  # lib/tests 518 -> 522: test_module_name_collisions.py added 4 arms. Adding lib/redact.py
  # made an existing by-path loader in claims/tests a name-squatter, which broke the COMBINED
  # suite while every directory still passed alone — a defect the per-directory floors above
  # structurally cannot see. That file is the only gate over the sys.modules name space.
  # lib/tests 522 -> 530: test_observation_n.py added 8 arms. `obs_existence` accepted no
  # trial count, so F8-6 — the ONLY one of 46 EXISTENCE cases whose seal names an n —
  # published `n_usable: 0, n_met: false` and an amendment-blocking shortfall note from a
  # run that collected 60 usable trials. The arms gate the BUILDER SET against the SEALED
  # SET, so a re-seal that gives another case an n fails here rather than in a result file.
  # lib/tests 530 -> 531: the root conftest.py made every root script an importable
  # top-level name (pytest prepends a conftest's rootdir to sys.path), widening the space a
  # by-path loader must not squat. test_module_name_collisions.py gained the arm that says so.
  # lib/tests 531 -> 543: test_policy_liveness.py added 11 arms + 1 skip = 12 COLLECTED
  # (pytest collects a skip; the floor is read off the collected count, so the skip counts). F3-7 published a
  # FALSE — a refutation of the document — from 120 trials in which the contextual-grounding
  # filter never ran: `ArmSpec.source` defaults to INPUT, grounding scores a RESPONSE, and at
  # INPUT the service returns 200 / action=NONE and OMITS the policy block entirely. Every
  # existing gate passed, including outputScope=FULL, which was written against this exact
  # blindness. The arms hold the liveness channel and the per-policy asymmetry that makes it
  # sound. test_checkpoint.py gained 8 more (resume across a design change) that deliberately
  # do NOT move the floor, per the file-not-arms rule (DEVIATIONS.md/DEV-P1-18).
  # lib/tests 543 -> 555: test_write_guard.py added 13 arms. The root conftest's write guard
  # had ONE channel — snapshot, run, diff — and failed 147 tests plus the session on a run
  # where every test was innocent: a live Phase 1 script was writing evidence/ from another
  # process. A diff sees change, not authorship. The guard now pairs `sys.addaudithook`
  # (authorship, immune to other processes) with the diff (the only channel that can see the
  # 10 test files that spawn subprocesses), and these 13 arms are the truth table between
  # them — including the two rows where each channel is the only one that works
  # (DEVIATIONS.md/DEV-P1-19).
  # lib/tests 555 -> 587: test_write_guard.py grew to 15 arms (the two tree-scope directions),
  # and test_write_guard_mutation.py added 16 — the 12-mutant run over the guard, plus a
  # control arm, moved out of /tmp and into the tree. It was a shell script whose result
  # ("8 killed, 2 survived") was written into DEV-P1-19 as a measured number that nothing in
  # the repository could reproduce (feedback_prose_is_not_verified), and which mutated the live
  # conftest.py in place under an EXIT trap — a crash would have left a deliberately broken
  # guard in the tree. Under pytest it is now behind this gate, and each mutant is applied to a
  # sandbox copy.
  # infra/tests:44 is the EIGHTH directory, added with Phase 2's testbed scripts. It is the only
  # suite covering code that DELETES, and its floor is the one most worth having: two of the four
  # gates in 99_teardown.py were found defective by measurement, and 0 of the 84 pre-existing
  # CloudWatch delivery resources in this account were protected by the original deny-list. A
  # directory that stopped being collected would take that whole argument with it silently.
  # f5_redteam/tests 35 -> 325. The floor was set when the directory held one file and was never
  # raised as F5-1 (43), F5-6 (19), F5-7a (18) and F5-2 (92) landed, so for several cases it was
  # a floor a single surviving file could clear — the check was live but had stopped being able
  # to see a whole suite vanish. 327 is the collected count with F5-2's two new files:
  # test_finding_f52_figures.py (33 arms pinning every figure in FINDING-F5-2.md to the two
  # analysis records) and test_finding_f52_mutation.py (26: 19 mutants over those arms, plus the
  # control, the five static checks and the live-document sha256). Both belong behind this gate for
  # the reason lib/tests' floor comment gives: their first run had two survivors, and a
  # mutation result that no gate re-runs is a number in prose.
  # f3_efficacy/tests 71 -> 268. Same failure as f5_redteam's: the floor was set when the
  # directory held one file and was never raised, so by the time F3-10 landed four files it was a
  # floor that test_f3_helpers.py alone could clear. 268 is the collected count including F3-10's
  # two new files: test_publish_slack.py (14 arms, of which 3 are mutants pinning each half of
  # DEV-P4-35's bucket-attribution fix against BOTH days' published records) and
  # test_window_audit.py (38: the closed-window re-read's aggregation, one arm per comparison
  # failure mode, the two dimension-roll-up regressions that instrument found in itself, and 11
  # break arms — one per guard). The mutation arms are the reason these belong behind a gate: a
  # mutation result nothing re-runs is a number in prose.
  # claims/tests was likewise stale at 286 against 384 collected. 395 included
  # test_repo_copy_exclusions.py (11 arms: the .gitignore-derived scratch-copy exclusion list,
  # both bounds on a real copy, and the AST scan that stops a fourth hand-written list —
  # DEV-P4-36, the 11.3 GB wedge that killed a full-gate run mid-flight). 411 adds DEV-P4-36's
  # SECOND site: test_amendment_evidence_subset.py (10 arms bounding the amendment gate's
  # per-arm evidence copy, of which the load-bearing one runs the real gate against the archive
  # and against the subset and compares row by row) and 6 more in
  # test_repo_copy_exclusions.py — the subtree-copy budget, which is the scan the first fix
  # deliberately did not write and is therefore how `copytree(ROOT / "evidence", …)` survived it.
  # runner/tests:55, f9_failsecure/tests:48, f1_config/tests:11 — the THREE directories this list
  # had drifted past, found 2026-08-13 by listing `*/tests` on disk against it: 11 exist, 8 were
  # here, and one of the 114 ungated arms was RED
  # (test_every_api_the_validation_has_called_is_mapped_to_an_action — delete_gateway had entered
  # evidence/ with no MAPPING entry, exactly the 2am-AccessDenied its docstring promises to catch
  # at desk). The comment above argues why a `*/tests` glob would be worse than this list, and the
  # argument is right — but a hand-written list is a CLAIM about what exists, and nothing checked
  # it. claims/tests/test_verify_phase0_gates_every_test_directory.py now does: a 12th directory
  # fails there, not silently here.
  # Re-baselined against the measured counts on 2026-08-14. Every floor here had drifted below what
  # its directory actually collects, and the gap had stopped being a rounding error: the f5_redteam
  # floor of 327 sat under 720 collected, so more than half that directory could have been deleted
  # and this gate would have printed a pass. f1_config was 11 against 170, lib 587 against 882,
  # f9_failsecure 48 against 106, f10_billing 35 against 80.
  #
  # That is the failure this list exists to prevent, arriving through the list itself. A floor is
  # only a floor while it is close to the count; each bump above is recorded one file at a time,
  # which is the right discipline and is also why they fell behind — arms were added faster than
  # the floors were raised (test_runner_trust.py 17, test_rate_limits.py 8, test_probe_guardrail.py
  # 17, and the four tagged-create arms in runner/tests, over two days).
  # runner/tests 80 -> 94 with test_merge_evidence.py (13 arms over runner/merge_evidence.py, the
  # promote-a-staged-pull step that did not exist until 2026-08-15 — its absence left 607 evidence
  # records, across fifteen case and diagnostic directories, staged for a day and invisible to
  # check_amendment_readiness.py). It is the second tool in the repo that can damage the audit
  # archive, and the only one that damages it by WRITING, so its all-or-nothing conflict abort and
  # its refusal to touch results/ belong behind this gate.
  # tools/tests:48 is the TWELFTH directory, and it arrived exactly the way the three of
  # 2026-08-13 did: the day-2 replication driver got a test suite, the suite was run directly
  # (`pytest tools/tests`) and reported green, and nothing added it here — so for two days its
  # arms were passing outside the gate that is supposed to be the reason to believe them. Found
  # 2026-08-15 by claims/tests/test_verify_phase0_gates_every_test_directory.py, which is the
  # check written for precisely this, doing its job on the first directory added after it existed.
  # The floor matters more than most: these arms bound `tools/day2_replicate.py`, the only script
  # in the repo that can DESTROY a day-1 verdict (`lib.phase1.emit` overwrites
  # results/phase1/<case>.json unconditionally, so the driver's pre-run snapshot is the only copy
  # during the window before the archive step), and `drop_snapshot` deletes that snapshot with
  # shutil.rmtree. A directory that silently stopped collecting would take the whole
  # snapshot-safety argument with it.
  for spec in "${TEST_SPECS[@]}"; do
    dir="${spec%%:*}"; floor="${spec##*:}"
    if [ ! -d "$dir" ]; then
      echo "FATAL: $dir does not exist — its tests cannot be reported as passing" >&2
      return 2
    fi
    got=$("$PY" -m pytest "$dir" -q --collect-only -p no:cacheprovider 2>/dev/null \
          | sed -n 's/^\([0-9]\{1,\}\) tests\{0,1\} collected.*/\1/p' | head -1)
    if [ -z "$got" ]; then
      echo "FATAL: could not read a collected count for $dir" >&2
      return 2
    fi
    if [ "$got" -lt "$floor" ]; then
      echo "FATAL: $dir collected $got test(s), expected >= $floor — a directory that" >&2
      echo "       stops contributing tests is indistinguishable from one that passes" >&2
      return 2
    fi
    printf '  %-18s %s tests collected (floor %s)\n' "$dir" "$got" "$floor"
  done
  "$PY" -m pytest claims/tests/ lib/tests/ f5_redteam/tests/ \
                  f2_determinism/tests/ f3_efficacy/tests/ \
                  f8_regional/tests/ f10_billing/tests/ infra/tests/ \
                  runner/tests/ f9_failsecure/tests/ f1_config/tests/ \
                  tools/tests/ -q || rc=$?
  return $rc
}

# Compile EVERY .py before any suite runs. This is not redundant with the test gate.
#
# Three times in this project I inserted prose after a docstring's closing `"""` and left an
# unterminated string literal behind. Each time the damage was not the typo but what it did
# to the signal: pytest reports a collection error, and a mutation harness that only reads
# the exit code then scored 13/13 kills against a tree where no test ran at all. A SyntaxError
# in a module that no suite happens to import — a case script, say — would not surface here
# until a live run had already spent money on it.
#
# So the tree must compile before anything claims to have tested it, and the file list must
# be non-empty (feedback_zero_file_scan_is_error): a compile gate that found no files would
# pass loudest of all.
compile_all() {
  local n
  n=$(find . -name '*.py' -not -path './.venv*/*' -not -path '*/__pycache__/*' | wc -l | tr -d ' ')
  # 100, which is EXACTLY the tree (77 when first written; +test_module_name_collisions.py,
  # +test_observation_n.py, +conftest.py, +test_policy_liveness.py, +test_write_guard.py,
  # +test_write_guard_mutation.py, +3 others; then 85 -> 100 when Phase 2 landed the 12
  # infra/ files and 3 more). A
  # tripwire for a truncated or mis-rooted file list, not a target. Same rule as the
  # per-directory test floors — it rises only when the tree grows by a deliberate, diffable
  # amount. Pinned exactly rather than left slack: the floor's unit here IS the file, so
  # unlike the test floors (whose unit is the arm, and which therefore sit below their
  # yield) there is no legitimate growth this number should absorb silently. It sat at 78
  # against 82 present, which already let four files vanish and still report clean.
  #
  # Raising it with Phase 2 matters more than the earlier raises did: infra/ is the only
  # directory whose modules create and delete AWS resources, so a truncated file list here
  # would skip the compile check on exactly the scripts whose SyntaxError costs money.
  if [ "$n" -lt 100 ]; then
    echo "FATAL: compile gate found only $n .py files; expected >= 100. A gate that scans" >&2
    echo "       nothing reports clean, so an empty or truncated file list is an error." >&2
    return 2
  fi
  printf '  %s .py files\n' "$n"
  find . -name '*.py' -not -path './.venv*/*' -not -path '*/__pycache__/*' -print0 \
    | xargs -0 "$PY" -m py_compile
}

gate "every .py compiles (no broken tree can reach the suites)" \
     compile_all
gate "triage reproduces from the rules" \
     "$PY" claims/01_triage.py --check
gate "coverage gate (15 checks over 546 claims)" \
     "$PY" claims/check_coverage.py
gate "coverage gate self-test (14 mutations + control arm)" \
     "$PY" claims/check_coverage.py --self-test
gate "exclusion register matches the triage" \
     "$PY" claims/03_exclusion_register.py --check
gate "pre-registration verifies against lib/stats.py" \
     "$PY" verify_prereg.py
# The oracle's own gate: every threshold in lib/oracle.py's binding table must be derivable
# from the sealed oracle text that names it, every case must be placeable in a family and
# given an alpha (evaluate() raises otherwise), and every kind must compare in the unit its
# Observation field is actually denominated in. Run here rather than only under pytest
# because it reads PREREGISTRATION.yaml: a resealed or edited prereg breaks the bindings
# without any test file changing.
gate "oracle bindings trace to the sealed oracle text" \
     "$PY" lib/oracle.py
gate "corpora (sizes sealed, build reproducible, κ ≥ gate)" \
     "$PY" corpora/verify_corpora.py
# The unsealed corpora F3-5/F3-6/F3-7 read, gated separately and deliberately not by the
# same script. Its novel check is `not_sealed`: three of the eighteen Phase 1 cases have a
# vacuous `n_met` precisely because these files are not in the seal, so a `sealed: true`
# appearing in corpora_deviation/MANIFEST.json — by hand edit, by copy-paste, or by a
# refactor that shares the manifest writer — would silently convert three vacuous values
# into three that read as met floors. It also re-checks `oracle.planned_n` live, so a
# future re-seal that adds an n fails HERE rather than leaving DEV-P1-4 quietly wrong.
gate "deviation corpora (unsealed by design, build reproducible, promotion refused)" \
     "$PY" corpora_deviation/verify_deviation.py
gate "amendment readiness (>= 2 calendar days before any doc change)" \
     "$PY" check_amendment_readiness.py
# Regenerating the register is the gate: rc=1 means a candidate resolves to zero sites,
# names a case the triage does not have, or claims a finding file that is missing. It also
# rewrites V13_CANDIDATES.md, so a triage edit that changes a site list can never leave a
# stale count in the deliverable — and claims/tests/test_v13_candidates.py fails if the
# committed file disagrees with a fresh build.
gate "v1.3 amendment register (sites derived from the triage, not listed by hand)" \
     "$PY" build_v13_candidates.py
gate "cost projection within the sealed ceiling" \
     "$PY" estimate_cost.py
gate "test suite (all ${#TEST_SPECS[@]} test directories)" \
     run_tests
gate "redaction gate" \
     "$PY" check_redaction.py

# F0-1 hits the network, so it is opt-in: a no-network run exits 3 (SKIP) and
# must not be silently folded into a green summary.
if [ "${WITH_NETWORK:-0}" = "1" ]; then
  gate "F0-1 documentation references (live HTTP)" \
       "$PY" claims/02_check_references.py
else
  printf '\n\033[33mSKIP\033[0m  F0-1 live reference check — set WITH_NETWORK=1 to include\n'
fi

printf '\n\033[1m=== summary ===\033[0m\n'
failed=0
for i in "${!names[@]}"; do
  if [ "${codes[$i]}" -eq 0 ]; then
    printf '  \033[32mpass\033[0m  %s\n' "${names[$i]}"
  else
    printf '  \033[31mFAIL\033[0m  %s  (rc=%d)\n' "${names[$i]}" "${codes[$i]}"
    failed=$((failed + 1))
  fi
done

# A run that executed no gates is a failure, not a pass.
if [ "${#names[@]}" -eq 0 ]; then
  echo "FATAL: no gates ran" >&2
  exit 2
fi

printf '\n%d/%d gates passed\n' "$(( ${#names[@]} - failed ))" "${#names[@]}"
[ "$failed" -eq 0 ] || exit 1
echo "PHASE 0 VERIFIED"
