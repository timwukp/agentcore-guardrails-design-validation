"""The scratch evidence subset the amendment gate's mutation arms run against.

Why this module exists
---------------------
`check_amendment_readiness.py` derives observation dates from the evidence records rather than
from prose, so its mutation arms need an `evidence/` tree they may write into. The `tree` fixture
in `test_amendment_gate.py` used to build one with `shutil.copytree(ROOT / "evidence", …)` — the
whole archive, once per arm. Its docstring said "only what the gate reads is copied"; that
sentence was false in the one direction that costs anything, because `evidence/` is the largest
tree in the repo.

This is DEV-P4-36 again, at a second site, found while writing DEV-P4-36's own guards. Its
lesson applies to it: ask what produced the volume, not what failed to remove it. Its AST scan
did not look here on the stated reasoning that "a subtree copy names what it takes" — true about
inheriting caches by accident, and wrong about size.

What the subset is
------------------
Under `evidence/`, the gate's result depends on exactly three things:

* whether `evidence/<run_id>/` exists, for each run a finding declares;
* whether that directory holds any `*.json` other than `environment.json`;
* the `t_start_utc` of the records whose `case_id` a finding declares.

So the subset is DERIVED from the findings' provenance blocks — the same producers the gate
itself reads (`feedback_derive_from_every_producer`), parsed with the gate's own `BLOCK_RE`
rather than a second copy of it — and holds, under each declared run:

* every record whose `case_id` is one some finding declares;
* every `environment.json`. The gate skips it by name; it is kept because it is small and
  keeps the copy shaped like the original;
* every `*.json` this module could not parse as a JSON object. Those are kept deliberately:
  the gate reports an unreadable record as a problem, and a fixture that dropped one would
  launder a real failure into a green control arm.

Every declared run directory that exists is created in the copy even when nothing under it is
kept, because "not under evidence/" and "holds no evidence records" are two different gate
failures and two different arms.

What the subset deliberately keeps that it could have dropped
-------------------------------------------------------------
Records of OTHER declared cases in the same run. `observation_days()` scopes days to `case_id`
precisely because this project adopts one run id for nearly everything, and a run-wide count
was once satisfied by a sibling case that happened to run on another day. Keeping the sibling
declared cases means a gate that stopped filtering by `case_id` still over-counts days against
this subset, and is still caught. A subset trimmed to one case per finding would have made that
regression invisible — the fixture would have done the scoping the gate is supposed to do.

Bounds, not just a smaller number
---------------------------------
`EVIDENCE_SUBSET_CEILING_KB` and `EVIDENCE_SUBSET_FLOOR_KB` are asserted by
`test_amendment_evidence_subset.py` against a real copy. A ceiling alone is satisfied by an
empty tree (`feedback_zero_file_scan_is_error`), and an unbounded copy that is merely smaller
today is the defect this module exists about, one growth spurt later.
"""

from __future__ import annotations

import json
import shutil
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The gate is IMPORTED, not loaded by path.
#
# The point of reaching for it at all is `BLOCK_RE`: the provenance block's shape is the gate's to
# define, and a second copy of that regex here would be the "a duplicated constant is a defect
# with a delay" half of DEV-P4-36, committed while fixing the other half.
#
# The first version did that with `spec_from_file_location("check_amendment_readiness", …)`,
# following the by-path idiom the rest of this directory uses, and
# `lib/tests/test_module_name_collisions.py` red on the first combined run: the repo root is on
# `sys.path` under pytest — its `conftest.py` puts it there — so `check_amendment_readiness` is an
# importable top-level name, and a loader registering it would make every later
# `import check_amendment_readiness` in the process resolve to this one. That gate is right, and
# it caught this in the only kind of run that can see it; a per-directory run cannot.
#
# The `sys.path` line is for callers OUTSIDE pytest (a one-off measurement script), where nothing
# has inserted the root yet. Under pytest it is already there and the insert does nothing.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import check_amendment_readiness as _GATE   # noqa: E402  (must follow the sys.path line)

BLOCK_RE = _GATE.BLOCK_RE
# Read off the imported module rather than rebuilt from ROOT, so the path this copies and the
# module this parses with cannot come to disagree.
GATE = Path(_GATE.__file__).resolve()

# Measured on the tree that produced DEV-P4-36's sibling: the full `evidence/` archive is
# 198,452 KB in 28,716 files, of which the three declared runs are 84,535 KB in 17,515. The
# ceiling is set above the subset and far below either, so it bites long before a disk does; the
# floor is against a derivation that quietly reads nothing.
EVIDENCE_SUBSET_CEILING_KB = 40_000
EVIDENCE_SUBSET_FLOOR_KB = 8_000


def declared_provenance(root: Path = ROOT) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The run_ids and case_ids every `FINDING-*.md` under `root/results` declares.

    Findings whose block is missing or unparseable are skipped rather than raised on: those are
    states the GATE reports, and several arms manufacture them. A fixture that crashed on them
    would replace the gate's diagnosis with a fixture error.
    """
    runs: list[str] = []
    cases: list[str] = []
    for f in sorted((root / "results").glob("FINDING-*.md")):
        m = BLOCK_RE.search(f.read_text(encoding="utf-8"))
        if not m:
            continue
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(meta, dict):
            continue
        for r in meta.get("evidence_runs") or []:
            if isinstance(r, str) and r not in runs:
                runs.append(r)
        for c in meta.get("cases") or []:
            if isinstance(c, str) and c not in cases:
                cases.append(c)
    return tuple(runs), tuple(cases)


@lru_cache(maxsize=8)
def _manifest(root: Path, runs: tuple[str, ...],
              cases: tuple[str, ...]) -> tuple[Path, ...]:
    """Cached because it parses every JSON under the declared runs — 17,515 files.

    Uncached this ran once per mutation arm, which would have traded 5 GB of disk for a couple
    of minutes of CPU: a different bill for the same defect.
    """
    wanted = set(cases)
    out: list[Path] = []
    for rid in runs:
        d = root / "evidence" / rid
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.json")):
            rel = p.relative_to(root)
            if p.name == "environment.json":
                out.append(rel)
                continue
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                out.append(rel)          # the gate reports this; do not launder it
                continue
            if not isinstance(rec, dict) or rec.get("case_id") in wanted:
                out.append(rel)
    return tuple(out)


def subset_manifest(root: Path = ROOT, runs: tuple[str, ...] | None = None,
                    cases: tuple[str, ...] | None = None) -> tuple[Path, ...]:
    """Repo-relative paths of the evidence files a scratch copy of `root` needs.

    `runs`/`cases` are overridable so a gate can narrow them and watch the manifest move —
    a derivation that ignored its inputs would otherwise be indistinguishable from a
    hand-written list.
    """
    d_runs, d_cases = declared_provenance(root)
    return _manifest(root,
                     d_runs if runs is None else tuple(runs),
                     d_cases if cases is None else tuple(cases))


def copy_evidence_subset(dst_root: Path, root: Path = ROOT,
                         manifest: tuple[Path, ...] | None = None) -> Path:
    """Copy the subset into `dst_root`, at the same relative paths, and return its `evidence/`.

    `evidence/` itself is created unconditionally: arms that manufacture a second observation
    day write a NEW run directory under it, and one arm makes an empty one.
    """
    (dst_root / "evidence").mkdir(parents=True, exist_ok=True)
    for rid in declared_provenance(root)[0]:
        if (root / "evidence" / rid).is_dir():
            (dst_root / "evidence" / rid).mkdir(exist_ok=True)
    for rel in (subset_manifest(root) if manifest is None else manifest):
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    return dst_root / "evidence"
