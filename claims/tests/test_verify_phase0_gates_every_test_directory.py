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
"""

from __future__ import annotations

import re
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
