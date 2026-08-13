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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "verify_phase0.sh"

# One (dir, floor) pair per spec string. Anchored to the quoted "path:digits" shape used in the
# for-loop, which nothing else in the script shares.
SPEC_RE = re.compile(r'"([a-z0-9_/]+/tests):(\d+)"')


def _on_disk() -> set[str]:
    """Every */tests directory that holds at least one collectable test module.

    Depth-limited to direct children of ROOT, matching the project layout the gate encodes
    (`<family>/tests`). A tests directory holding no test_*.py contributes no arms and is not
    the gate's business.
    """
    return {
        f"{d.parent.name}/tests"
        for d in ROOT.glob("*/tests")
        if d.is_dir() and any(d.glob("test_*.py"))
    }


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
