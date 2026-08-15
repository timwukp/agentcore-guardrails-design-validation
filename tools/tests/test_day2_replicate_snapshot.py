#!/usr/bin/env python3
"""`drop_snapshot` may only delete the pre-run snapshot when day 1 survives without it.

Why this file exists
--------------------
`tools/day2_replicate.py` exists because a day-2 replication can destroy day 1: `lib.phase1.emit`
rewrites `results/phase1/<case>.json` unconditionally, so the day-1 verdict is *replaced*. The
driver's answer is a snapshot taken before the producer runs, and that snapshot is the only copy
during the window between the producer's write and the archive step. `drop_snapshot` deletes it.

That makes it the one function in the driver that can lose evidence, and it does so with
`shutil.rmtree`. The failure is silent by construction: a run where the archive step wrote nothing
still prints REPLICATED, and deleting the snapshot then leaves the day-1 verdict recoverable from
nowhere. So the precondition is tested rather than reasoned about, in both directions — the delete
happens when it should, and each way it can be unsafe blocks it.

Every arm below patches `ROOT` and `ARCHIVE` onto a tmp tree. Nothing here reads or writes the real
`results/phase1/archive/`, which holds the only copies of seventeen day-1 verdicts.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SUBJECT_MODULE_NAME = "_snapshot_day2_replicate"


def _subject():
    """Load `tools/day2_replicate.py` under a private name.

    Not `day2_replicate`: that stem is importable top-level under pytest (the root conftest puts
    the repo root and `tools/` in play), and a module registered twice under two names is the
    collision `lib/tests/test_module_name_collisions.py` gates against.
    """
    spec = importlib.util.spec_from_file_location(
        SUBJECT_MODULE_NAME, REPO / "tools" / "day2_replicate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


RUN_ID = "r20260815T084022Z"
DAY1_RUN_ID = "r20260810T080412Z"
DAY1_DATE = "2026-08-10"


def _day1_bytes(case: str, verdict: str = "FALSE") -> bytes:
    return json.dumps({"case_id": case, "verdict": verdict, "run_id": DAY1_RUN_ID}).encode()


@pytest.fixture()
def bed(tmp_path, monkeypatch):
    """A driver whose ROOT/ARCHIVE are a throwaway tree, with the snapshot already written."""
    mod = _subject()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ARCHIVE", tmp_path / "results" / "phase1" / "archive")
    (tmp_path / "results" / "phase1" / "archive").mkdir(parents=True)

    pre_dir = tmp_path / "runner" / ".staging" / f"day2_pre_{RUN_ID}"
    pre_dir.mkdir(parents=True)
    before = {"F3-4.json": _day1_bytes("F3-4")}
    for name, raw in before.items():
        (pre_dir / name).write_bytes(raw)
    return mod, pre_dir, before


def _archive_ok(mod, before):
    for name, raw in before.items():
        (mod.ARCHIVE / f"{name[:-len('.json')]}__day1_{DAY1_DATE}.json").write_bytes(raw)


# ------------------------------------------------------------------ the safe path

def test_deletes_when_every_changed_case_is_archived_byte_for_byte(bed):
    mod, pre_dir, before = bed
    _archive_ok(mod, before)

    assert mod.drop_snapshot(pre_dir, before, list(before), RUN_ID) == []
    assert not pre_dir.exists(), "snapshot survived a run where day 1 was fully archived"
    # And the thing it was protecting is still there — the point of the whole exercise.
    kept = mod.ARCHIVE / f"F3-4__day1_{DAY1_DATE}.json"
    assert kept.read_bytes() == before["F3-4.json"]


def test_a_case_with_no_day1_content_does_not_block(bed):
    """A NEW case has nothing to lose, so it must not hold the snapshot hostage forever.

    Without this, the first case a producer emits for the first time would keep every future
    snapshot on disk — the leak the delete exists to stop, re-entering through the guard.
    """
    mod, pre_dir, before = bed
    _archive_ok(mod, before)
    changed = [*before, "F9-9.json"]          # F9-9 is absent from `before`

    assert mod.drop_snapshot(pre_dir, before, changed, RUN_ID) == []
    assert not pre_dir.exists()


def test_a_resolved_day1_date_is_used_instead_of_the_run_id(bed):
    """The label comes from what `main()` resolved, not from re-parsing the run id.

    F8-5's day-1 run id is `smoke20260810T0305Z`, which `run_id_date` cannot parse. Before
    `day1_label` existed this function re-derived "unknown", looked for
    `F8-5__day1_unknown.json`, and would have kept the snapshot forever for any case whose
    archive had been filed under its real date. Both halves are asserted: the resolved name is
    the one checked, and the run-id-derived name is NOT accepted as a substitute.
    """
    mod, pre_dir, _ = bed
    raw = json.dumps({"case_id": "F8-5", "verdict": "FALSE",
                      "run_id": "smoke20260810T0305Z"}).encode()
    (pre_dir / "F8-5.json").write_bytes(raw)
    before = {"F8-5.json": raw}
    (mod.ARCHIVE / "F8-5__day1_unknown.json").write_bytes(raw)

    assert mod.drop_snapshot(pre_dir, before, list(before), RUN_ID) == [], "fallback broke"
    assert mod.drop_snapshot(pre_dir, before, list(before), RUN_ID,
                             {"F8-5": "2026-08-10"}) == ["F8-5"], (
        "the resolved date was ignored and the run-id-derived archive name was accepted")

    (mod.ARCHIVE / "F8-5__day1_2026-08-10.json").write_bytes(raw)
    assert mod.drop_snapshot(pre_dir, before, list(before), RUN_ID,
                             {"F8-5": "2026-08-10"}) == []
    assert not pre_dir.exists()


# ------------------------------------------------------------------ each unsafe path

def test_missing_archive_file_blocks_the_delete(bed):
    """The archive loop ran but wrote nothing — the exact state a mid-run abort leaves."""
    mod, pre_dir, before = bed
    # deliberately no _archive_ok()

    blocked = mod.drop_snapshot(pre_dir, before, list(before), RUN_ID)
    assert blocked == ["F3-4"]
    assert (pre_dir / "F3-4.json").read_bytes() == before["F3-4.json"], (
        "the snapshot was deleted, or damaged, while day 1 had no other copy")


def test_archive_file_with_different_bytes_blocks_the_delete(bed):
    """Right path, wrong content: an archive from an EARLIER day is not this day's day 1.

    This is the arm that makes the check a byte comparison rather than an `exists()`. A driver
    that only tested existence would delete a snapshot whose content appears nowhere, because the
    archive path is keyed by date and two runs can share a date.
    """
    mod, pre_dir, before = bed
    (mod.ARCHIVE / f"F3-4__day1_{DAY1_DATE}.json").write_bytes(_day1_bytes("F3-4", "TRUE"))

    blocked = mod.drop_snapshot(pre_dir, before, list(before), RUN_ID)
    assert blocked == ["F3-4"]
    assert (pre_dir / "F3-4.json").exists()


def test_one_unarchived_case_keeps_the_whole_snapshot(bed):
    """Partial deletion is worse than either alternative, so the block is all-or-nothing."""
    mod, pre_dir, before = bed
    before = {**before, "F1-14.json": _day1_bytes("F1-14", "TRUE")}
    (pre_dir / "F1-14.json").write_bytes(before["F1-14.json"])
    (mod.ARCHIVE / f"F3-4__day1_{DAY1_DATE}.json").write_bytes(before["F3-4.json"])  # only one

    blocked = mod.drop_snapshot(pre_dir, before, list(before), RUN_ID)
    assert blocked == ["F1-14"]
    assert {p.name for p in pre_dir.iterdir()} == {"F3-4.json", "F1-14.json"}, (
        "the archived case's snapshot copy was removed individually; the next abort would find "
        "a half-populated snapshot and no way to tell which half")


def test_it_refuses_to_delete_a_directory_it_did_not_create(bed):
    """The path guard: `rmtree` on an operator-supplied path is one typo from a real directory.

    `results/` is passed here because that is the worst realistic mistake — a caller that built
    `pre_dir` from the wrong join and handed over the distributable tree. It must raise, and the
    directory must still be there afterwards.
    """
    mod, pre_dir, before = bed
    _archive_ok(mod, before)
    victim = mod.ROOT / "results"

    with pytest.raises(SystemExit) as e:
        mod.drop_snapshot(victim, before, list(before), RUN_ID)
    assert "refusing to delete" in str(e.value)
    assert victim.is_dir() and (victim / "phase1" / "archive").is_dir()
    assert pre_dir.exists(), "the real snapshot was removed by a call that named another path"


def test_a_snapshot_from_another_run_id_is_not_deleted_by_this_one(bed):
    """Run ids scope the guard, so a stale snapshot is never collateral of the next run.

    Two day-2 runs on the same date produce two snapshot directories. Deleting the other one
    would remove the only day-1 copy for a run still in its unprotected window.
    """
    mod, pre_dir, before = bed
    _archive_ok(mod, before)
    other = mod.ROOT / "runner" / ".staging" / "day2_pre_r20260815T082524Z"
    other.mkdir(parents=True)
    (other / "F1-14.json").write_bytes(_day1_bytes("F1-14", "TRUE"))

    with pytest.raises(SystemExit):
        mod.drop_snapshot(other, before, list(before), RUN_ID)
    assert (other / "F1-14.json").exists()


# ------------------------------------------------------------------ the caller still calls it

def test_the_success_path_still_reaches_drop_snapshot():
    """A guard that stops being called is `feedback_missing_check_is_not_pass` in reverse.

    The arms above test the function in isolation; nothing in them notices if the REPLICATED
    branch stops invoking it, which would silently restore the leak. `main()` cannot be exercised
    here — it shells out to a live producer — so the wiring is asserted on the source, and on the
    ordering that matters: the cleanup must come after the disagreement check, or a run that found
    a real day-1/day-2 contradiction would tidy away its own primary evidence.
    """
    src = (REPO / "tools" / "day2_replicate.py").read_text(encoding="utf-8")
    assert "drop_snapshot(pre_dir, before, changed, run_id" in src, (
        "main() no longer calls drop_snapshot; runner/.staging/ grows without bound again")
    i_disagree = src.index('if disagreed:')
    i_drop = src.index("unarchived = drop_snapshot(")
    i_replicated = src.index('print(f"REPLICATED')
    assert i_disagree < i_drop < i_replicated, (
        "drop_snapshot must run after the disagreement return and before the REPLICATED line")
