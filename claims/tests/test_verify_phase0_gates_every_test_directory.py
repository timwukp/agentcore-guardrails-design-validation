"""The gate's directory list is a claim about the tree, and this arm is what checks it.

`verify_phase0.sh` runs a hand-written list of test directories, and the comment above that list
argues — correctly — why a `*/tests` glob would be worse: a glob silently covers a directory that
was deleted, and "no directory, no tests, no failure" is the defect the floors exist against.

What that argument does not do is keep the list current. On 2026-08-13 the tree held ELEVEN
`*/tests` directories and the list held eight; the 114 uncollected arms included one that was RED
(`runner/tests/test_runner_policy.py::test_every_api_the_validation_has_called_is_mapped_to_an_action`
— `delete_gateway` had entered `evidence/` with no MAPPING entry, which is precisely the
2am-on-the-instance AccessDenied that arm exists to catch at desk). A guard that exists, is red,
and is run by nothing is the same defect as DEV-P4-36's narrowed AST scan, one artifact over
(feedback_guard_scope_is_a_claim): the justification for not looking was written down and true,
and nothing bounded what it excluded.

So: the list stays hand-written, per its own argument — and THIS arm holds the two sides equal.
A new `*/tests` directory now fails here, with instructions, rather than joining the suite's
blind spot. A deleted one fails in the gate itself (`[ ! -d "$dir" ]` is FATAL there).

Both sides are DERIVED — the disk side from a glob, the script side from the spec strings — so
neither is a second hand-written list that could drift in sympathy with the first.

A spec has TWO halves, and for a year only one of them was checked here. The floor is also a claim
about the tree — "at least this much of this suite still has to exist" — and it is the half that has
gone wrong twice: `lib/tests` at a floor of 100 against 350 collected (2026-08-14), then five floors
and 306 arms of slack (2026-09-17), with `tools/tests` at 48 against 122. Both times every directory
was correctly LISTED. So the floors are now compared against what their directories actually collect,
with a bounded slack calibrated on that drift; see `allowed_slack` below.
"""

from __future__ import annotations

import functools
import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "verify_phase0.sh"

sys.path.insert(0, str(ROOT / "lib" / "tests"))
from scan_scope import out_of_scope  # noqa: E402  the one definition of "this repo's own source"

# One (dir, floor) pair per spec string. Anchored to the quoted "path:digits" shape used in the
# for-loop, which nothing else in the script shares.
SPEC_RE = re.compile(r'"([a-z0-9_/]+/tests):(\d+)"')


def _on_disk() -> set[str]:
    """Every tests directory that holds at least one collectable test module.

    A tests directory holding no `test_*.py` contributes no arms and is not the gate's business.

    THE DEPTH IS THE PART THAT WAS WRONG. This globbed `*/tests` only, "matching the project layout
    the gate encodes (`<family>/tests`)" — a justification that was true of the families and false
    of the tree. `platform/build/tests` (378 arms) and `platform/audit/tests` (57) sit one level
    deeper, so on 2026-09-17 they were invisible to *this* check for the whole time they were
    missing from `TEST_SPECS`: 435 arms outside the gate, including every mutation-checked refusal
    of `gate_payload.py` and `build_site_data.py` — the arms the publish path's credibility rests
    on. This file's own docstring argues that a hand-written list is a claim about the tree; a
    depth-limited glob is the same kind of claim, one indirection further in
    (`feedback_guard_scope_is_a_claim`, `feedback_discovery_pattern_is_a_claim`).

    Two depths, not `rglob`: `rglob("tests")` would read third-party trees, and the scope predicate
    that excludes them is shared rather than restated (`scan_scope.out_of_scope`). Two is not a
    principle either — `test_the_depth_limit_is_bounded_by_the_tree` below fails if the tree ever
    grows a `tests` directory deeper than this walk reaches, which is the only way a depth limit
    gets to stay.
    """
    found = set()
    for pattern in ("*/tests", "*/*/tests"):
        for d in ROOT.glob(pattern):
            rel = d.relative_to(ROOT)
            if not d.is_dir() or out_of_scope(rel) or not any(d.glob("test_*.py")):
                continue
            found.add(rel.as_posix())
    return found


def test_the_gate_lists_every_test_directory_on_disk_and_runs_it():
    text = SCRIPT.read_text(encoding="utf-8")
    listed = {m.group(1) for m in SPEC_RE.finditer(text)}
    disk = _on_disk()

    assert listed, "read no dir:floor specs out of verify_phase0.sh — the regex or the script moved"

    missing = sorted(disk - listed)
    assert missing == [], (
        "these test directories exist on disk but verify_phase0.sh does not gate them:\n"
        + "\n".join(f"  {d}" for d in missing)
        + "\nAdd each to the spec list with its current collected count as the floor, and to the"
          " combined pytest invocation below the loop. 114 arms and one RED guard sat in exactly"
          " this gap on 2026-08-13."
    )
    ghosts = sorted(listed - disk)
    assert ghosts == [], (
        "these directories are gated but hold no test modules on disk:\n"
        + "\n".join(f"  {d}" for d in ghosts)
        + "\nA floor over nothing FATALs in the gate; fix the tree or the list."
    )

    # A directory whose floor passes but which the combined run omits would collect-count green
    # and then never execute. The combined invocation trails the loop; every listed dir must be in it.
    not_run = sorted(d for d in listed if f"{d}/" not in text.split("for spec in", 1)[1])
    assert not_run == [], (
        "gated but absent from the combined pytest invocation:\n"
        + "\n".join(f"  {d}" for d in not_run)
    )


def _tests_dirs_at_any_depth() -> set[str]:
    """The unbounded answer: every in-scope directory named `tests` that holds a test module."""
    return {
        d.relative_to(ROOT).as_posix()
        for d in ROOT.rglob("tests")
        if d.is_dir()
        and not out_of_scope(d.relative_to(ROOT))
        and any(d.glob("test_*.py"))
    }


def test_the_depth_limit_is_bounded_by_the_tree():
    """`_on_disk()` walks two depths; this arm is what keeps that number honest.

    A depth limit is exactly the shape of claim this whole file exists to check, and the first one
    cost 435 ungated arms. So the bounded walk is compared against an unbounded one: if a `tests`
    directory ever appears three levels down, this fails with instructions rather than the gate
    quietly not covering it. Both sides are derived from the tree; neither is a list.
    """
    bounded, unbounded = _on_disk(), _tests_dirs_at_any_depth()
    assert bounded == unbounded, (
        "the two-depth glob in _on_disk() no longer sees every tests directory in the tree:\n"
        f"  deeper than it looks: {sorted(unbounded - bounded)}\n"
        f"  seen only by it:      {sorted(bounded - unbounded)}\n"
        "Widen the pattern list in _on_disk() and add the directory to TEST_SPECS. A directory this "
        "arm cannot see is a directory the gate cannot be checked against.")


def test_the_extra_depth_is_load_bearing_today():
    """The control for the arm above: a depth-1-only glob must still MISS something.

    Without this, the widening could be reverted — or the nested suites deleted — and every arm here
    would stay green while the check silently went back to the scope that hid `platform/build/tests`.
    If this fails because the two are equal, the nested directories are gone; drop the extra depth
    deliberately, in a diff, rather than leaving a pattern that covers nothing
    (`feedback_vacuous_test_check`).
    """
    depth_one = {d.relative_to(ROOT).as_posix() for d in ROOT.glob("*/tests")
                 if d.is_dir() and not out_of_scope(d.relative_to(ROOT))
                 and any(d.glob("test_*.py"))}
    nested = _on_disk() - depth_one
    assert nested, (
        "no tests directory below depth 1 was found, so the `*/*/tests` pattern is now dead. "
        "Either the nested suites were removed — in which case remove the pattern in the same "
        "change — or the scope predicate started excluding them.")
    assert all(d.count("/") == 2 for d in nested), sorted(nested)


# --- the other half of the claim: a floor is also a number about the tree ----------------------------
#
# Membership was the half this file started with, and it is not the half that has cost the most. Twice
# now — 2026-08-14 (`lib/tests` at a floor of 100 against 350 collected) and 2026-09-17 (five floors,
# 306 arms of slack, `tools/tests` at 48 against 122) — every directory was LISTED and the gate still
# would have printed a pass over the deletion of whole test files. The cause is written into the script
# itself: floors are bumped one file at a time, deliberately, which is the right discipline and is also
# exactly why they fall behind. A discipline nothing measures is a plan, so this measures it.

# Slack allowed between a floor and its directory's collected count, per directory.
#
# CALIBRATED AGAINST THE DRIFT THAT ACTUALLY HAPPENED, not chosen for roundness. The five stale floors
# of 2026-09-17 sat (floor -> collected, slack): claims 423->471 (48), lib 882->992 (110),
# f5_redteam 720->789 (69), f1_config 170->175 (5), tools 48->122 (74). At 8% this convicts four of the
# five and acquits `f1_config`, whose gap was five arms — the one case where forcing an edit would be
# noise. `test_the_slack_bound_convicts_the_drift_this_repo_actually_had` pins that, so lowering the
# bound to something vacuous fails here rather than passing quietly.
#
# The floor of 12 is what keeps the script's other written rule true — "adding tests must never require
# editing this list". Twelve is about one new test file's worth of arms, so a file lands free; three of
# them do not, and by then the script's own rule says the floor should have been raised anyway.
SLACK_FRACTION = 0.08
MIN_SLACK_ARMS = 12


def allowed_slack(collected: int) -> int:
    """The largest gap between a floor and a directory's yield that is not yet drift."""
    return max(MIN_SLACK_ARMS, math.ceil(SLACK_FRACTION * collected))


@functools.lru_cache(maxsize=None)
def _collected_per_gated_directory(dirs: tuple[str, ...]) -> dict[str, int]:
    """Collect the gated directories in ONE subprocess and bucket the ids by directory.

    One invocation rather than fifteen, because fifteen interpreter starts and fifteen import passes
    would put minutes into an arm that the six-directory sweep runs on every round. Verified against
    the per-directory method the gate itself uses (`pytest <dir> -q --collect-only`): on 2026-09-17 the
    combined buckets equalled the fifteen separate counts exactly, and their sum equalled the run's own
    `N tests collected` line — which is the cross-check below, because a parse that reads no ids and a
    directory that collects nothing look identical from a total (`feedback_zero_needs_a_ran_flag`).

    `--collect-only` imports the modules and runs none of them, so nothing here writes to the tree and
    collecting `claims/tests` from inside `claims/tests` does not recurse.

    Cached per directory tuple so the mutation arm below re-uses this measurement instead of paying for
    a second one — the mutant is in the SCRIPT, which is what that arm is about.
    """
    cmd = [sys.executable, "-m", "pytest", *dirs, "-q", "--collect-only", "-p", "no:cacheprovider"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    assert proc.returncode == 0, (
        f"collection over the gated directories exited {proc.returncode} — the yields this arm "
        f"compares against cannot be trusted:\n{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}")

    total = re.search(r"^(\d+) tests? collected", proc.stdout, re.M)
    assert total, ("pytest printed no 'N tests collected' line, so there is no independent total to "
                   "check the buckets against")

    counts = {d: 0 for d in dirs}
    unclaimed: list[str] = []
    for line in proc.stdout.splitlines():
        if "::" not in line:
            continue
        file_id = line.split("::", 1)[0]
        if not file_id.endswith(".py"):
            continue
        owners = [d for d in dirs if file_id.startswith(f"{d}/")]
        if len(owners) == 1:
            counts[owners[0]] += 1
        else:
            unclaimed.append(line)

    assert not unclaimed, ("collected ids that no gated directory claims (or that two claim):\n"
                           + "\n".join(f"  {ln}" for ln in unclaimed[:10]))
    assert sum(counts.values()) == int(total.group(1)), (
        f"bucketed {sum(counts.values())} ids but pytest collected {total.group(1)} — the id parse is "
        f"reading a different set than the run did, so every per-directory number below is wrong")
    return counts


def test_the_floors_do_not_drift_far_below_what_their_directories_collect():
    """A floor far under its directory's yield licenses deleting test files silently.

    This is the same defect the floors exist against, one indirection quieter: `tools/tests` at a floor
    of 48 against 122 collected meant `test_sync_handover_bundle.py` — 32 arms over the only tool in
    this repo that DELETES outside it — plus two more files could have been removed whole while the
    gate printed `PASS  test suite`. Both halves of every spec are now derived from the tree: the
    directory by the glob above, the number by collecting it.
    """
    specs = {m.group(1): int(m.group(2)) for m in SPEC_RE.finditer(SCRIPT.read_text(encoding="utf-8"))}
    assert specs, "read no dir:floor specs out of verify_phase0.sh — the regex or the script moved"

    counts = _collected_per_gated_directory(tuple(sorted(specs)))
    drifted = [(d, specs[d], counts[d]) for d in sorted(specs)
               if counts[d] - specs[d] > allowed_slack(counts[d])]
    assert drifted == [], (
        "these floors in verify_phase0.sh sit further below their directory's yield than "
        f"max({MIN_SLACK_ARMS}, {SLACK_FRACTION:.0%} of the yield):\n"
        + "\n".join(f"  {d:<22} floor {floor}, collects {got} "
                    f"(slack {got - floor}, allowed {allowed_slack(got)})"
                    for d, floor, got in drifted)
        + "\nRaise each to its collected count in the same change, and record the measurement in the"
          " rationale above the loop — a floor is a claim about how much of the suite still has to"
          " exist, and this much of it no longer has to.")


def test_the_slack_bound_convicts_the_drift_this_repo_actually_had():
    """The control. A bound generous enough to permit everything is not a detector.

    The pairs are the five stale floors measured on 2026-09-17 (and one acquittal), so this arm fails
    if `SLACK_FRACTION` or `MIN_SLACK_ARMS` is ever loosened past the drift they were calibrated on —
    the deletion-sized gap, not a rounding gap.
    """
    convicted = {"claims/tests": (423, 471), "lib/tests": (882, 992),
                 "f5_redteam/tests": (720, 789), "tools/tests": (48, 122)}
    for name, (floor, got) in convicted.items():
        assert got - floor > allowed_slack(got), (
            f"{name}: the real drift of {got - floor} arms is inside an allowance of "
            f"{allowed_slack(got)} — the bound no longer catches what it was written for")

    # Acquitted deliberately: five arms is not drift, and forcing an edit for it would make the floors
    # a maintenance tax rather than a tripwire.
    assert 175 - 170 <= allowed_slack(175)
    # A floor at today's exact count must be the quietest possible state, and one new test file's worth
    # of arms must not require touching the script (`-ge` in the gate says the same thing).
    assert 0 <= allowed_slack(8) and MIN_SLACK_ARMS >= 8


def test_the_gate_counts_its_directories_instead_of_stating_a_number():
    """The label a reader sees must be derived from the list, not typed alongside it.

    The arm above holds the *set* equal to the tree, and it passed all along while the script
    said three different things about the SIZE of that set: its header comment opened "The test
    gate runs SEVEN directories", the gate's label read "all 11 test directories", and the loop
    ran TWELVE. A number inside a string is not covered by a test over the data next to it
    (feedback_prose_is_not_verified), so a fully green run printed a false label for two days —
    which is worse than a stale comment, because the label is what a resuming session reads as
    the record of what the gate covered.

    The fix was to make the label count `TEST_SPECS`, and this arm is what stops it being
    hand-typed again: no literal directory count may appear in the label, and the expansion
    must be there.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    label = re.search(r'^gate "test suite \(([^"]*)\)"', text, re.M)
    assert label, "the test-suite gate's label moved — find it and re-point this arm"

    assert "${#TEST_SPECS[@]}" in label.group(1), (
        f'the gate label is {label.group(1)!r}. It must COUNT the list rather than state a size:\n'
        '  gate "test suite (all ${#TEST_SPECS[@]} test directories)"\n'
        "A typed number here is wrong on the day the thirteenth directory is added, and every "
        "gate still passes while it is wrong.")
    assert not re.search(r"\b\d+\b", label.group(1)), (
        f"the gate label {label.group(1)!r} contains a literal number — that is the defect")


# --- mutation arms ---------------------------------------------------------------------------------
#
# Added 2026-09-17, with the control above (the unmutated tree, 4 passed) run first. The arms these
# mutate had both been *vacuous in the direction that mattered*: the set comparison passed for a month
# while two directories were missing from the gate, because the discovery pattern could not see them.
# So each mutant asks the question the green run could not: would this arm notice?
#
# Neither mutant writes to the tree. `verify_phase0.sh` is copied into tmp_path and the module's SCRIPT
# is re-pointed at the copy, and the disk side is replaced by a patched function — because a mutation
# that edits an authored file is one interrupted run away from leaving it edited.


def test_mutation_a_directory_dropped_from_the_spec_list_fails(monkeypatch, tmp_path):
    text = SCRIPT.read_text(encoding="utf-8")
    dropped = 'platform/build/tests:378'
    assert dropped in text, "the spec this mutant removes is not in the script — re-point the mutant"
    mutant = tmp_path / "verify_phase0.sh"
    mutant.write_text(text.replace(f'"{dropped}" ', "").replace(f'"{dropped}"', ""), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "SCRIPT", mutant)
    with pytest.raises(AssertionError, match="does not gate them"):
        test_the_gate_lists_every_test_directory_on_disk_and_runs_it()


def test_mutation_the_floor_tools_tests_actually_shipped_with_fails_the_drift_arm(monkeypatch, tmp_path):
    """Put the real 2026-09-17 floor back and the drift arm must convict it.

    Not a synthetic mutant: `"tools/tests:48"` is the string this script carried for a month, against
    122 collected. This runs the whole arm — the measurement, the comparison and the report — over a
    tmp_path copy of the script, so the mutated floor is never written into the tree.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"tools/tests:122"' in text, "re-point this mutant: tools/tests' floor moved"
    mutant = tmp_path / "verify_phase0.sh"
    mutant.write_text(text.replace('"tools/tests:122"', '"tools/tests:48"'), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "SCRIPT", mutant)
    with pytest.raises(AssertionError, match="sit further below their directory's yield"):
        test_the_floors_do_not_drift_far_below_what_their_directories_collect()


def test_mutation_the_original_depth_one_glob_fails_the_bound(monkeypatch):
    """The exact scope this file shipped with until 2026-09-17 must now be convicted."""
    monkeypatch.setattr(
        sys.modules[__name__], "_on_disk",
        lambda: {d.relative_to(ROOT).as_posix() for d in ROOT.glob("*/tests")
                 if d.is_dir() and any(d.glob("test_*.py"))})
    with pytest.raises(AssertionError, match="no longer sees every tests directory"):
        test_the_depth_limit_is_bounded_by_the_tree()
    with pytest.raises(AssertionError, match="pattern is now dead"):
        test_the_extra_depth_is_load_bearing_today()
