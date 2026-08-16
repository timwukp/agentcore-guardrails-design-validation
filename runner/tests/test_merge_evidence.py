#!/usr/bin/env python3
"""`runner/merge_evidence.py` may only ADD to the audit archive, and must abort on any disagreement.

Why this file exists
--------------------
The tool exists because 607 evidence records sat in `runner/.state/incoming/20260814T162515Z/` for a
day and were never copied into `evidence/`, which made `check_amendment_readiness.py` — the only
executable statement of the study's sealed two-day rule — report that two published findings rested
on records that were never written. The records existed the whole time.

That makes this the second tool in the repo that can damage evidence (the first is
`tools/day2_replicate.py`'s `drop_snapshot`), and it damages it the other way: by writing. Three
properties are load-bearing and none of them is provable by reading the code once —

* it never overwrites a live record, so a staged file that disagrees with the published one cannot
  silently replace it (`git checkout -- file` is unusable in this repo, so an overwrite is final);
* one conflict aborts the WHOLE merge before anything is copied, because a half-merged archive is
  worse than an unmerged one — the unmerged one is visibly unmerged;
* `results/` is never touched, because everything in the distributable tree must pass
  `check_redaction.py` before it lands, and a bulk copier would bypass that gate entirely.

Every arm below monkeypatches `ROOT` and `STAGING_ROOT` onto a tmp tree, except the last two, which
read the real trees without writing. Nothing here writes to the real `evidence/`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SUBJECT_MODULE_NAME = "_runner_merge_evidence"


def _subject():
    """Load `runner/merge_evidence.py` under a private name.

    Not `merge_evidence`: `lib/tests/test_module_name_collisions.py` gates against one module
    registered twice under two names, and `runner/` is importable top-level under pytest.
    """
    spec = importlib.util.spec_from_file_location(
        SUBJECT_MODULE_NAME, REPO / "runner" / "merge_evidence.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


STAMP = "20260814T162515Z"
REL = Path("evidence") / "r20260810T130945Z" / "f1_config" / "F1-15" / "0001_create_gateway_ok.json"
BODY = b'{"case_id": "F1-15", "api": "create_gateway"}\n'


@pytest.fixture()
def bed(tmp_path, monkeypatch):
    """A tool whose ROOT and staging root are a throwaway tree, with one staged record."""
    mod = _subject()
    root = tmp_path / "repo"
    staging_root = root / "runner" / ".state" / "incoming"
    staged = staging_root / STAMP
    (staged / REL.parent).mkdir(parents=True)
    (staged / REL).write_bytes(BODY)
    monkeypatch.setattr(mod, "ROOT", root)
    monkeypatch.setattr(mod, "STAGING_ROOT", staging_root)
    return mod, root, staged


def _live(root: Path) -> Path:
    return root / REL


# ------------------------------------------------------------------ the safe path

def test_apply_copies_a_record_the_live_tree_does_not_have(bed, capsys):
    mod, root, staged = bed

    assert mod.merge(staged, apply=True) == 0
    assert _live(root).read_bytes() == BODY
    assert "MERGED — 1 file(s) copied" in capsys.readouterr().out


def test_dry_run_is_the_default_and_writes_nothing(bed, capsys):
    mod, root, staged = bed

    assert mod.merge(staged, apply=False) == 0
    assert not _live(root).exists(), "a dry run created a file in the audit archive"
    out = capsys.readouterr().out
    assert "DRY RUN — 1 file(s) would be copied" in out
    # The counts a dry run reports must be the counts an --apply would act on, or approving the
    # report approves something else.
    assert "to copy     1 file(s)" in out


def test_a_byte_identical_record_is_left_alone(bed, capsys):
    """Re-running a merge must be a no-op, not 24,000 rewrites of the same bytes."""
    mod, root, staged = bed
    _live(root).parent.mkdir(parents=True)
    _live(root).write_bytes(BODY)
    before = _live(root).stat().st_mtime_ns

    assert mod.merge(staged, apply=True) == 0
    assert _live(root).stat().st_mtime_ns == before, "an identical file was rewritten"
    assert "NOTHING TO DO" in capsys.readouterr().out


def test_it_copies_rather_than_hardlinks(bed):
    """A hardlink would make the archive mutable through the staging path.

    `evidence/` is the tree whose whole purpose is that a full ARN and request id can be quoted to
    AWS Support months later. Sharing an inode with a staging directory that gets deleted by hand
    is how that stops being true.
    """
    mod, root, staged = bed

    assert mod.merge(staged, apply=True) == 0
    assert _live(root).stat().st_ino != (staged / REL).stat().st_ino
    assert _live(root).stat().st_nlink == 1


def test_the_staged_tree_survives_the_merge(bed):
    """The tool never deletes its input — that decision stays with the operator."""
    mod, root, staged = bed

    assert mod.merge(staged, apply=True) == 0
    assert (staged / REL).read_bytes() == BODY


# ------------------------------------------------------------------ each unsafe path

def test_differing_bytes_are_a_conflict_and_nothing_at_all_is_copied(bed, capsys):
    """The all-or-nothing arm: one conflict must also stop the files that were fine.

    This is the arm that distinguishes "refuses to overwrite" from "aborts the merge". A tool that
    only skipped the conflicting file would leave an archive that is neither the staged state nor
    the live one, and no output says which files are which.
    """
    mod, root, staged = bed
    _live(root).parent.mkdir(parents=True)
    _live(root).write_bytes(b'{"case_id": "F1-15", "api": "create_gateway", "differs": true}\n')
    other = Path("evidence") / "r20260810T130945Z" / "f5_redteam" / "F5-7b" / "0001_ok.json"
    (staged / other).parent.mkdir(parents=True)
    (staged / other).write_bytes(b'{"case_id": "F5-7b"}\n')

    assert mod.merge(staged, apply=True) == 1
    assert not (root / other).exists(), (
        "a non-conflicting file was copied during a run that reported REFUSED — the archive is now "
        "in a state no message describes")
    assert _live(root).read_bytes().endswith(b'"differs": true}\n'), "the live record was overwritten"
    err = capsys.readouterr().err
    assert "REFUSED" in err and "Nothing was copied" in err


def test_a_staged_path_outside_evidence_is_refused_not_copied(bed, capsys):
    """`results/` is distributable; it lands through the redaction gate or not at all."""
    mod, root, staged = bed
    diag = Path("results") / "DIAG-vpc-runtime-20260814T092455Z.json"
    (staged / diag).parent.mkdir(parents=True)
    (staged / diag).write_bytes(b"{}\n")

    assert mod.merge(staged, apply=True) == 0
    assert not (root / diag).exists(), (
        "a staged results/ file was copied into the distributable tree without the redaction gate")
    out = capsys.readouterr().out
    assert "refused     1 file(s) outside evidence/" in out
    assert str(diag) in out, "the refusal did not name the file, so it looks like nothing happened"


def test_a_directory_outside_the_staging_root_is_refused(bed, capsys):
    """The path guard. A caller that built the path from the wrong join must not be merged from.

    `evidence/` itself is passed here because that is the worst realistic mistake — merging the
    archive into itself — and because it proves the guard is about the PARENT, not about content.
    """
    mod, root, staged = bed
    victim = root / "evidence"
    victim.mkdir(parents=True, exist_ok=True)

    assert mod.merge(victim, apply=True) == 2
    assert "not an immediate child" in capsys.readouterr().err


def test_a_nested_directory_under_the_staging_root_is_also_refused(bed):
    """`incoming/<stamp>/evidence` is a child of a child; merging from it would rebase every path.

    Every relative path is joined onto ROOT, so a tree one level too deep would write
    `ROOT/r20260810T130945Z/...` — outside `evidence/` entirely, and silently, because the first
    path segment would no longer be `evidence` and every file would be reported as "refused".
    """
    mod, root, staged = bed

    assert mod.merge(staged / "evidence", apply=True) == 2


def test_a_missing_directory_is_an_error_not_an_empty_merge(bed, capsys):
    mod, root, staged = bed

    assert mod.merge(staged.parent / "20260101T000000Z", apply=True) == 2
    assert "not a directory" in capsys.readouterr().err


def test_a_symlink_in_the_staging_tree_is_not_followed(bed):
    """A symlinked record would put a path outside the staging tree into the archive as content."""
    mod, root, staged = bed
    outside = staged.parent.parent / "secret.json"
    outside.write_bytes(b'{"not": "evidence"}\n')
    link = staged / "evidence" / "r20260810T130945Z" / "f1_config" / "F1-15" / "0002_link.json"
    link.symlink_to(outside)

    assert mod.merge(staged, apply=True) == 0
    assert not (root / link.relative_to(staged)).exists(), "a symlink was materialised into evidence/"


# ------------------------------------------------------------------ against the real trees

def test_the_real_staging_tree_holds_nothing_the_live_tree_disagrees_with():
    """Read-only over the actual pull, so a future re-merge cannot quietly find a conflict.

    `classify` does not write, so this arm is safe against the real archive. It is also the arm
    that would notice if a staged record and its published counterpart ever diverged — which is
    the situation the tool refuses to resolve on its own.
    """
    mod = _subject()
    staged = mod.STAGING_ROOT / STAMP
    if not staged.is_dir():
        pytest.skip(f"{staged} is not on this machine")

    to_copy, identical, conflicts, refused = mod.classify(staged)
    assert conflicts == [], f"staged records disagree with the published ones: {conflicts[:5]}"
    assert refused == [], "the pull staged something outside evidence/"
    assert identical, "nothing matched at all — ROOT or the staging layout moved"


def test_the_2026_08_14_pull_is_merged_and_f1_15_has_its_records():
    """The repair itself, pinned. This is the state the amendment gate needs to be able to pass.

    `check_amendment_readiness.py` resolves FINDING-F1-15.md's `cases: ["F1-15"]` by scanning
    `evidence/<run>/` for records carrying that `case_id`. With none present it reported "no
    evidence record ... carries a case_id in ['F1-15']" and took six arms of
    `claims/tests/test_amendment_gate.py` down with it, control arms included. Asserting the
    records are here is cheaper than re-deriving that diagnosis a second time.
    """
    mod = _subject()
    live = mod.ROOT / "evidence" / "r20260810T130945Z"
    if not live.is_dir():
        pytest.skip("the local evidence archive is not on this machine")

    for case, path, floor in (("F1-15", live / "f1_config" / "F1-15", 38),
                              ("F5-7b", live / "f5_redteam" / "F5-7b", 124)):
        records = sorted(path.glob("*.json"))
        assert len(records) >= floor, f"{case}: {len(records)} record(s) under {path}, expected >= {floor}"
        assert any(f'"case_id": "{case}"' in r.read_text(encoding="utf-8") for r in records), (
            f"{case}: records exist but none carries its case_id — the gate reads the id, not the "
            "directory name")
