"""The one definition of "which files are this repo's own source", for repo-wide AST scanners.

Not a test module — pytest collects `test_*.py`, and this file is imported by name from the
scanners that share it (`lib/tests` is on `sys.path` under pytest's default prepend import mode,
which is also how `test_property_not_called.py` reaches `checkpoint` and friends).

WHY THIS EXISTS
---------------
Eleven tests in this repo walk `ROOT.rglob("*.py")` and assert something about every file they
find. Each one had to decide what "every file" means, and each one decided separately. On
2026-08-15 a third virtualenv — `.venv-figs`, created so the figure generator could hold
matplotlib without disturbing the sealed oracle's pinned botocore — was added to the tree, and
two of those eleven went red on third-party code:

    .venv-figs/lib/python3.12/site-packages/matplotlib/backends/backend_qt.py:607  .width()

Sixteen findings, none of them ours, in a check whose whole value is that its findings are ours.
The cause was that the skip rule was spelled as a SET OF NAMES —
`{".venv", ".venv-oracle", ".venv-baseline", ...}` — and a set of names cannot notice a new name.
This is the same defect, in the same week, as the redaction gate's exact-name venv skip
(DEV-P4-41): *a gate whose scope is expressed as a list of names cannot notice a new name.*

The lesson was already available. `test_module_name_collisions.py` carries it in a comment from an
earlier instance where an equality test let site-packages in and its scan read 1,272 files instead
of 78 — and that fix was applied to one scanner and never propagated to the other four
(`feedback_fix_producer_not_janitor`). Hence one module, imported, rather than a fifth copy.

WHY PREFIX AND NOT A GLOB FROM .gitignore
-----------------------------------------
`.gitignore` line 26 is `.venv-*/`, and it is the authoritative statement; both pushers
(`tools/repo_diff.py`, `claims/tests/repo_copy.py`) already derive their exclusions from it via
`fnmatch`, which is why neither tried to publish the new venv. Deriving here too was considered
and rejected for now: `.gitignore` also names things a source scan SHOULD read (nothing today, but
the coupling runs the wrong way — an entry added there to keep a file out of git would silently
remove it from every static check). The prefix rule is narrower and states its own scope, and
`test_scan_scope.py` asserts a `.venv-<anything>` is out of scope, so the next venv is covered
before it is created.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Directory-name PREFIXES. `.venv` covers `.venv`, `.venv-oracle`, `.venv-baseline`, `.venv-figs`
# and whatever the next one is called; that last clause is the entire point.
SKIP_DIR_PREFIXES: tuple[str, ...] = (".venv",)

# Exact names, for trees whose identity is not a family: build caches, VCS metadata, the local-only
# evidence store and the runner's local bookkeeping. These are safe as names because a new one of
# these is a new KIND of directory, which arrives with a human deciding where it goes — unlike a
# second virtualenv, which arrives as a variation on a name already in the list.
SKIP_DIR_NAMES: frozenset[str] = frozenset({
    ".git", "__pycache__", ".pytest_cache", "node_modules",
    "evidence", ".state", ".staging", ".wheel_cache",
})


def out_of_scope(rel: Path, extra_names: frozenset[str] | set[str] = frozenset()) -> bool:
    """Is `rel` (repo-relative) inside a tree that is not this repo's own source?"""
    for part in rel.parts:
        if part in SKIP_DIR_NAMES or part in extra_names:
            return True
        if any(part.startswith(p) for p in SKIP_DIR_PREFIXES):
            return True
    return False


# A DATED RECORD IS NOT A LIVE CLAIM.
#
# `session-logs/` holds append-only session records. They state what was true on their own date —
# "`FUTURE-WORK.md` is a 28-item register" was correct on 2026-08-15 — and two guards check live
# prose against today's derivation (`claims/tests/test_future_work_register.py`,
# `claims/tests/test_cited_paths_exist.py`). Editing a log to agree with today would falsify the
# record, and a log whose numbers track the present is worth nothing as evidence.
#
# The predicate is over the EVIDENCE of being a dated record — a date in the filename — and not over
# the directory name alone, so a live document dropped into `session-logs/` under an undated name is
# still checked. A bare directory skip is the shape `check_redaction.py` spent 2026-08-20 removing
# (`feedback_scope_as_namelist`); repeating it here would be the same mistake in a second place.
#
# It lives in this module, beside `out_of_scope`, because two test files need it and a regex copied
# into both is a regex that drifts in one of them (`feedback_second_instance_bugs`).
_DATED = "(?:\\d{4}-\\d{2}-\\d{2}|\\d{8})"


def is_dated_record(rel: Path) -> bool:
    """Is `rel` (repo-relative) an append-only session record stamped with its own date?"""
    posix = rel.as_posix()
    return bool(re.match(rf"^session-logs/.*{_DATED}", posix))


def walk_in_scope(extra_names: frozenset[str] | set[str] = frozenset()):
    """Yield every in-scope file under ROOT, PRUNING out-of-scope directories as it descends.

    `ROOT.rglob("*")` filtered by `out_of_scope` gives the same answer and is unusable: rglob walks
    into `evidence/` and every `.venv-*` before the filter ever sees a path, so a scan of the ~800
    files this repo owns pays for the ~200k it does not. A caller that needs one cheap property of
    every file (its suffix, its size) uses this; a caller matching a narrow glob can keep rglob.
    """
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = Path(dirpath).relative_to(ROOT)
        dirnames[:] = [d for d in dirnames
                       if not out_of_scope(rel_dir / d, extra_names)]
        for name in filenames:
            yield Path(dirpath) / name


def py_files(extra_names: frozenset[str] | set[str] = frozenset(), floor: int = 50) -> list[Path]:
    """Every `.py` file that is this repo's own source, sorted.

    `floor` is not decoration. A scan that reads almost nothing passes over the whole repo and
    reports clean, which is the failure mode this project has hit often enough to have a name for
    (`feedback_zero_file_scan_is_error`): a scan reading zero files is an error, not a pass. The
    assertion lives here so every caller inherits it instead of remembering it.
    """
    out = sorted(p for p in ROOT.rglob("*.py")
                 if not out_of_scope(p.relative_to(ROOT), extra_names))
    assert len(out) > floor, (
        f"only {len(out)} python file(s) in scope, floor {floor} — a near-empty scan reports "
        f"clean over the whole repo, so this is an error and not a pass")
    return out
