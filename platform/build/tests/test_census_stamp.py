"""The census's file name is its only timestamp, so the validator on that name gets a harness.

WHY THIS FILE EXISTS
--------------------
`census_rendered_surfaces.py` writes the ledger that `check_site_invariants.py`'s untranslated-surface
ceiling counts against, and `build_site_data.py` chooses that ledger with
`sorted(CENSUS_DIR.glob("rendered-surfaces-*.json"))[-1]` — the newest **by name**. The name is therefore
a field of the measurement, and until 2026-09-18 it had no producer and no validator: whoever ran the
command typed it.

It failed the way an unvalidated mandatory field always fails. Two ledgers were written that afternoon
with LOCAL time labelled `Z` — `…T151900Z.json` written at 07:33:59 UTC and `…T155900Z.json` at
07:48:25 UTC, on a UTC+8 machine — so both sorted ahead of every correctly stamped ledger for the next
eight hours. A later run measured the changed tree at `…T095804Z`, the build kept selecting the stale
file, and the gate printed a pass **naming the stale file**: the census had been re-run and its number
discarded. `check_out_stamp()` is the refusal that stops the third occurrence, and this file is what
stops the refusal from being quietly weakened.

WHAT EACH ARM HOLDS, AND WHY THE CLOCK IS INJECTED
--------------------------------------------------
Every arm passes `now` and `existing` explicitly. A validator that reads the machine's clock inside its
own test measures the machine (`feedback_harness_test_measures_the_machine`), and worse, an arm about
"eight hours in the future" written against `datetime.now()` would pass or fail depending on the
timezone of whoever runs it — which is the very defect under test.

The control comes first and must not raise: an arm that only ever asserts refusals passes just as
happily against a function that refuses everything.
"""

from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BUILD = REPO / "platform" / "build"
SUBJECT_MODULE_NAME = "census_rendered_surfaces"


def _load_subject():
    spec = importlib.util.spec_from_file_location(
        SUBJECT_MODULE_NAME, BUILD / f"{SUBJECT_MODULE_NAME}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


census = _load_subject()

NOW = datetime.datetime(2026, 9, 18, 10, 0, 0, tzinfo=datetime.timezone.utc)
DIR = Path("platform/census")


def ledger(stamp: str) -> Path:
    return DIR / f"rendered-surfaces-{stamp}.json"


def test_a_refusal_exits_2_so_a_caller_can_tell_it_from_a_failed_walk():
    """`cannot_run` is the census's CANNOT-RUN code, and a gate reading rc must not see 1 here."""
    with pytest.raises(SystemExit) as e:
        census.check_out_stamp(DIR / "not-a-ledger.json", now=NOW, existing=[])
    assert e.value.code == 2, f"a refusal must exit 2, not {e.value.code!r}"


def test_no_mutant_control_a_correct_stamp_newer_than_everything_present_is_accepted():
    census.check_out_stamp(
        ledger("20260918T095804Z"),
        now=NOW,
        existing=[ledger("20260918T064500Z"), ledger("20260918T074825Z")])


def test_a_name_outside_the_convention_is_refused_before_the_walk(capsys):
    with pytest.raises(SystemExit):
        census.check_out_stamp(DIR / "census-today.json", now=NOW, existing=[])
    assert "is not `rendered-surfaces-<YYYYMMDD>T<HHMMSS>Z.json`" in capsys.readouterr().err


def test_digits_that_are_not_a_real_instant_are_refused(capsys):
    with pytest.raises(SystemExit):
        census.check_out_stamp(ledger("20260931T000000Z"), now=NOW, existing=[])
    assert "is not a real UTC instant" in capsys.readouterr().err


def test_local_time_labelled_z_is_refused_because_it_out_sorts_every_correct_stamp(capsys):
    """The actual 2026-09-18 defect, replayed at the instant it happened.

    `now` is the real write time of the real file — 07:48:25 UTC, read from its mtime — and the name is
    the local time that was typed. 8.2 h of daylight between them is what a UTC+8 offset looks like from
    inside the program, and the message has to say so: "refused" without the distance sends the caller
    looking for a bug in their clock instead of at their timezone.
    """
    written_at = datetime.datetime(2026, 9, 18, 7, 48, 25, tzinfo=datetime.timezone.utc)
    with pytest.raises(SystemExit):
        census.check_out_stamp(ledger("20260918T155900Z"), now=written_at, existing=[])
    err = capsys.readouterr().err
    assert "AHEAD of the UTC clock" in err
    assert "8.2 h" in err, "the message must state how far ahead, so a timezone is recognisable as one"


def test_a_stamp_inside_the_tolerance_is_accepted_and_one_outside_is_not(capsys):
    """The tolerance has to discriminate, or it is either useless or a licence for a whole offset."""
    near = NOW + datetime.timedelta(seconds=census.STAMP_FUTURE_TOLERANCE_S - 30)
    census.check_out_stamp(ledger(near.strftime("%Y%m%dT%H%M%SZ")), now=NOW, existing=[])
    far = NOW + datetime.timedelta(seconds=census.STAMP_FUTURE_TOLERANCE_S + 30)
    with pytest.raises(SystemExit):
        census.check_out_stamp(ledger(far.strftime("%Y%m%dT%H%M%SZ")), now=NOW, existing=[])
    assert "AHEAD of the UTC clock" in capsys.readouterr().err


def test_a_stamp_no_newer_than_the_newest_present_ledger_is_refused(capsys):
    """A walk whose output nothing selects is four minutes spent on a number that cannot be read."""
    with pytest.raises(SystemExit):
        census.check_out_stamp(
            ledger("20260918T073359Z"), now=NOW,
            existing=[ledger("20260918T073359Z"), ledger("20260918T074825Z")])
    err = capsys.readouterr().err
    assert "is not newer than rendered-surfaces-20260918T074825Z.json" in err
    assert "reads the newest by name" in err


def test_the_same_name_already_present_does_not_count_as_something_to_beat():
    """Overwriting one's own output is a re-write of one measurement, not a stamp that lost a race."""
    census.check_out_stamp(
        ledger("20260918T095804Z"), now=NOW,
        existing=[ledger("20260918T064500Z"), ledger("20260918T095804Z")])


def test_a_stray_file_in_the_census_directory_cannot_block_a_correct_stamp():
    """Only files that match the convention order the sort, so only they can be the one to beat."""
    census.check_out_stamp(
        ledger("20260918T095804Z"), now=NOW,
        existing=[DIR / "rendered-surfaces-NOTES.json", DIR / "README.md",
                  ledger("20260918T074825Z")])


def test_the_two_files_that_caused_this_are_no_longer_in_the_tree():
    """The renamed pair, pinned. Both were renamed to their true UTC times, derived from their own
    mtime, so a reader of the 2026-09-18 logs can follow the old name to the new one — and so this
    validator's own precondition (nothing in the directory is stamped in the future) keeps holding."""
    present = {p.name for p in (REPO / "platform" / "census").glob("rendered-surfaces-*.json")}
    assert "rendered-surfaces-20260918T151900Z.json" not in present
    assert "rendered-surfaces-20260918T155900Z.json" not in present
    assert {"rendered-surfaces-20260918T073359Z.json",
            "rendered-surfaces-20260918T074825Z.json"} <= present


def test_every_ledger_in_the_tree_satisfies_the_validator():
    """The convention is a claim about the whole directory, not about the next write.

    Derived from the directory rather than from a list, so a file added by hand is included
    (`feedback_derive_both_sides_of_a_gate`). Each name is checked against the ledgers OLDER than it,
    which is the state that existed when it was written.
    """
    names = sorted(p.name for p in (REPO / "platform" / "census").glob("rendered-surfaces-*.json"))
    assert len(names) >= 9, f"only {len(names)} ledger(s); this arm would be near-vacuous"
    now = datetime.datetime.now(datetime.timezone.utc)
    for i, name in enumerate(names):
        census.check_out_stamp(DIR / name, now=now,
                               existing=[DIR / n for n in names[:i]])
