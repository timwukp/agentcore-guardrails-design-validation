"""The scratch-copy exclusion list for the claims/ gates, derived from `.gitignore`.

Why this is one module instead of three lists
---------------------------------------------
Three gates copy the repo into a scratch tree and mutate the copy: `test_corpus_gate.py`'s
`tree` fixture (one copy per mutation arm, ~48 arms) and two arms of
`test_v13_candidates.py`. Each carried its OWN hand-written `shutil.ignore_patterns(...)`, and
the three disagreed.

`f1_config/.wheel_cache/` — 214 MB of pip cache, ignored by git, read by nothing under test —
was in none of them. On 2026-08-13 a single full-gate run therefore wrote 11.3 GB of scratch
(48 copies × 236 MB), filled the disk and killed itself: pytest emitted mass `E`s from tmp_path
creation, and the shell could not write its own output file. See DEV-P4-36.

So the list is DERIVED from `.gitignore` in one place rather than restated in three
(`feedback_derive_from_every_producer`): a tree git will not carry is a tree a scratch copy does
not need, and the next such directory is excluded on the day it is added to `.gitignore` rather
than on the day a disk fills.

A plain module rather than the conftest, so `test_repo_copy_exclusions.py` can import the same
object the fixture uses. Importing `conftest` by name would be ambiguous — this repo has three
of them (root, `claims/tests`, `infra/tests`) and `sys.modules` holds whichever pytest reached
first, which is exactly the collision `lib/tests/test_module_name_collisions.py` exists about.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GITIGNORE = ROOT / ".gitignore"

# Not derivable from `.gitignore`, and deliberately short.
#
# `*.pyc`: `__pycache__/` covers the directory, but a stray bytecode file beside a source file is
# not covered, and a stale one has already served a mutant in this repo
# (`feedback_pyc_serves_the_mutant`).
#
# `results/` is deliberately NOT here. It is distributable, the redaction gate scans it, and
# `build_v13_candidates.py` runs against it — a caller that does not need it says so per call
# (`copy_repo(dst, "results")`), which is what `test_corpus_gate.py` does and what takes its ~48
# arms from 34 MB each to 7 MB each.
EXTRA_EXCLUDE_NAMES: tuple[str, ...] = ("*.pyc",)

# The copy must stay far below the 236 MB that caused DEV-P4-36, and must not silently become
# nothing: an empty copy satisfies any ceiling. Both bounds are asserted by
# `test_repo_copy_exclusions.py`; they live here so the fixture's contract and its gate read the
# same numbers.
COPY_CEILING_KB = 80_000
COPY_FLOOR_KB = 5_000

# ---------------------------------------------------------------------------------------------
# Subtree copies — `copytree(ROOT / "X", …)`
#
# DEV-P4-36's scan looked only at `copytree(ROOT, …)`, on the stated reasoning that a subtree
# copy "names what it takes". It does name it. Naming is not bounding: `test_amendment_gate.py`
# named `ROOT / "evidence"` and took 198,452 KB, 26 times a run, and that site was found by hand
# a day later rather than by the guard written to prevent exactly this.
#
# So every subtree source is registered here with the ceiling it must stay under, and a new or
# grown one is a red test instead of a full disk. Ceilings sit just above the measured size
# rather than at a round comfortable number, because the room in a bound is the room a defect
# grows into: the three below are copied TOGETHER, once per arm, by a file with 56 arms.
SUBTREE_COPY_BUDGET_KB: dict[str, int] = {
    "lib": 10_000,        # 5,756 KB measured
    "claims": 8_000,      # 2,768 KB measured
    "corpora": 4_000,     # 804 KB measured
}

# What one pytest run may write in per-arm subtree copies from a single file, before the guard
# says the arithmetic no longer fits on a laptop. 11.3 GB is what DEV-P4-36 actually wrote; this
# is an order of magnitude under it, and the whole point is that the sum is asserted rather than
# assumed from three individually reasonable ceilings.
SUBTREE_RUN_BUDGET_KB = 1_500_000

# Copy sites whose source is not a literal path under ROOT, so its size cannot be read from the
# source text. Each is named with WHAT the source is, so the exemption is a stated fact rather
# than a silence, and `test_repo_copy_exclusions.py` asserts each declared file still holds such
# a call — a stale entry reds instead of quietly exempting nothing.
DYNAMIC_COPY_SOURCES: dict[str, str] = {
    "claims/tests/test_prereg_verifier.py":
        "`src_corpus` — a SIBLING repository's PII corpus, addressed through PREREGISTRATION's "
        "source_corpus path. Not in this tree, guarded by is_dir(), and skipped on any machine "
        "that does not have it.",
    "f5_redteam/tests/test_07a_verdict.py":
        "`src` — one archived evidence CASE directory per run in v57a.DEFAULT_RUNS, i.e. a "
        "single case's records, not a family and not the archive.",
}


def _local_only_names(text: str) -> tuple[str, ...]:
    """The basename patterns `.gitignore` names, in file order, de-duplicated.

    Basenames, because that is what `shutil.ignore_patterns` matches. This is WIDER than the
    `.gitignore` entry it comes from: `runner/.state/` becomes `.state` anywhere in the tree.
    That is the safe direction for a scratch copy — over-excluding costs one test a file it can
    name and say so about, under-excluding costs the disk.
    """
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        base = line.rstrip("/").rsplit("/", 1)[-1]
        if base and base not in names:
            names.append(base)
    return tuple(names)


assert GITIGNORE.is_file(), (
    f"PRECONDITION: {GITIGNORE} is missing, so the copy-exclusion list would be derived from "
    "nothing and every scratch copy would carry the local-only trees again (DEV-P4-36)")

LOCAL_ONLY_NAMES: tuple[str, ...] = _local_only_names(GITIGNORE.read_text(encoding="utf-8"))
COPY_EXCLUDE_NAMES: tuple[str, ...] = LOCAL_ONLY_NAMES + EXTRA_EXCLUDE_NAMES


def copy_exclude(*extra: str):
    """The `ignore=` callable for a scratch copy of the repo, plus any per-call extras."""
    return shutil.ignore_patterns(*COPY_EXCLUDE_NAMES, *extra)


def copy_repo_tree(dst: Path, *extra: str) -> Path:
    """Copy the repo into `dst` without the trees `.gitignore` says are local-only."""
    shutil.copytree(ROOT, dst, ignore=copy_exclude(*extra))
    return dst
