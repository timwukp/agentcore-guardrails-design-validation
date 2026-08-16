#!/usr/bin/env python3
"""Promote a staged `pull` into the live `evidence/` tree — additively, and never over anything.

Why this file exists
--------------------
`runner/sync.py pull` deliberately writes into `runner/.state/incoming/<stamp>/` and never over the
working tree; its own docstring gives the reasons and they are right. What it does not have is the
other half: nothing in the repo moves a staged tree *into* `evidence/`. That step was left to be
done by hand, and on 2026-08-14 it was not done at all.

The cost of that omission, measured 2026-08-15: `runner/.state/incoming/20260814T162515Z/` holds
**38** evidence records carrying `case_id` `F1-15` and **124** carrying `F5-7b`, and the live tree
holds **zero** for either. So `check_amendment_readiness.py` — the only executable statement of the
study's sealed two-day rule — reported "4 problem(s) in 92 assertions" saying those two findings
rest on records that were never written, and **six** arms of `claims/tests/test_amendment_gate.py`
and `test_amendment_evidence_subset.py` failed with it, including the CONTROL arms whose whole job
is to prove the gate can still pass on an unmutated tree. The records existed the entire time, one
directory away. A gate that cannot pass because of a missing copy step is indistinguishable, from
the outside, from a study that lost its evidence.

Why the rules below are the rules
---------------------------------
* **Additive only, never overwrite.** `git checkout -- file` is unusable in this repo (the working
  tree runs ahead of git HEAD), so an overwrite here is not recoverable. A staged file whose live
  counterpart has different bytes is a CONFLICT, not an update.
* **All-or-nothing on conflict.** One differing file aborts the whole merge before anything is
  copied. A half-merged evidence tree is worse than an unmerged one, because the unmerged one is
  obviously unmerged.
* **`evidence/` only.** `results/` is the distributable tree and everything in it must pass
  `check_redaction.py` before it lands; a tool that copied staged `results/` files in bulk would put
  unreviewed artifacts into the published tree, which is the exact defeat `sync.py` staged to avoid.
  Staged non-`evidence/` paths are reported and refused, never copied.
* **Copy, never hardlink.** A hardlink into `evidence/` makes the audit archive mutable through the
  staging path.
* **Dry run by default.** `--apply` is required to write. The report is the same in both modes, so
  what you approve is what runs.

Usage
-----
    ./.venv-oracle/bin/python runner/merge_evidence.py runner/.state/incoming/<stamp>
    ./.venv-oracle/bin/python runner/merge_evidence.py runner/.state/incoming/<stamp> --apply

Exit codes: 0 nothing to do or merge completed; 1 conflicts (nothing copied); 2 bad arguments or a
path outside the staging root.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING_ROOT = ROOT / "runner" / ".state" / "incoming"
LIVE_SUBTREE = "evidence"


def classify(staged: Path) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    """Sort every file under `staged` into (to_copy, identical, conflicts, refused).

    Paths returned are RELATIVE to `staged`, which is what makes the report readable and the
    destination unambiguous: the live path is always `ROOT / rel`.
    """
    to_copy: list[Path] = []
    identical: list[Path] = []
    conflicts: list[Path] = []
    refused: list[Path] = []

    for f in sorted(staged.rglob("*")):
        if not f.is_file() or f.is_symlink():
            continue
        rel = f.relative_to(staged)
        if rel.parts[0] != LIVE_SUBTREE:
            refused.append(rel)
            continue
        live = ROOT / rel
        if not live.exists():
            to_copy.append(rel)
        elif filecmp.cmp(f, live, shallow=False):
            identical.append(rel)
        else:
            conflicts.append(rel)
    return to_copy, identical, conflicts, refused


def merge(staged: Path, apply: bool) -> int:
    if not staged.is_dir():
        print(f"FATAL: not a directory: {staged}", file=sys.stderr)
        return 2
    staged = staged.resolve()
    if staged.parent != STAGING_ROOT.resolve():
        print(f"FATAL: {staged} is not an immediate child of {STAGING_ROOT} — refusing to merge a "
              "tree this tool did not receive from `sync.py pull`", file=sys.stderr)
        return 2

    to_copy, identical, conflicts, refused = classify(staged)

    print(f"staged tree   {staged.relative_to(ROOT)}")
    print(f"  identical   {len(identical)} file(s) already in evidence/ with the same bytes")
    print(f"  to copy     {len(to_copy)} file(s) absent from evidence/")
    print(f"  conflicts   {len(conflicts)} file(s) present with DIFFERENT bytes")
    print(f"  refused     {len(refused)} file(s) outside evidence/ (results/ goes through the "
          "redaction gate, not through here)")

    for rel in refused[:10]:
        print(f"    refused: {rel}")
    for rel in conflicts[:20]:
        print(f"    CONFLICT: {rel}")

    if conflicts:
        print(f"REFUSED — {len(conflicts)} staged file(s) differ from the live copy. Nothing was "
              "copied. Resolve each by hand: the live copy is the published one and this tool will "
              "not decide which of two evidence records is the real observation.", file=sys.stderr)
        return 1

    if not to_copy:
        print("NOTHING TO DO — every staged evidence record is already in the live tree.")
        return 0

    if not apply:
        by_case: dict[str, int] = {}
        for rel in to_copy:
            key = "/".join(rel.parts[1:3]) if len(rel.parts) > 2 else str(rel)
            by_case[key] = by_case.get(key, 0) + 1
        for key, n in sorted(by_case.items(), key=lambda kv: (-kv[1], kv[0]))[:25]:
            print(f"    would copy {n:5d}  {key}")
        print(f"DRY RUN — {len(to_copy)} file(s) would be copied. Re-run with --apply.")
        return 0

    copied = 0
    for rel in to_copy:
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():                       # a race, or a bug in classify(); either way stop
            print(f"FATAL: {rel} appeared under evidence/ after classification — aborting after "
                  f"{copied} file(s)", file=sys.stderr)
            return 1
        shutil.copy2(staged / rel, dest)        # copy2, not link: the archive stays immutable
        copied += 1

    print(f"MERGED — {copied} file(s) copied into evidence/. The staged tree is untouched; delete "
          "it by hand once the gates pass.")
    return 0 if copied == len(to_copy) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("staged", type=Path, help="a directory under runner/.state/incoming/")
    ap.add_argument("--apply", action="store_true",
                    help="actually copy; without it nothing is written")
    args = ap.parse_args(argv)
    return merge(args.staged, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
