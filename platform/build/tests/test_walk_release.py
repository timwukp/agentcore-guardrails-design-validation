"""`walk_release.playable_track_count` — the number the browser walk holds the DOM to.

Why this file exists
--------------------
The walk's video arm used to compare what it found against a constant, `MIN_VIDEOS_TOTAL = 2`, whose
comment read "one per locale on /design; a second chapter raises this". That is a name list wearing a
number's clothes (`feedback_scope_as_namelist`): the three phase chapters could land, only the overview
could actually render into the payload, and the walk would clear its floor and print OK. The floor
cannot notice work it was never told about.

So the expectation is now derived from `media.json` — one player per playable video per locale — and
the floor is demoted to what a floor is good for: refusing to walk a payload that ships nothing. This
file pins the derivation, because a derived number that is wrong is worse than a constant that is
honest about being one.

What each arm is for
--------------------
Every arm below is a payload state that has actually been reachable in this project: the full render,
the overview-only payload that was live from 2026-09-17, the half-rendered video (an mp4 whose captions
did not ship — `derive_media` counts that video as unrendered and `Design.tsx` shows no player), a
manifest declaring a script that has not been rendered at all, and the empty payload the builder
writes when `RENDER.json` is absent.

There is no browser here on purpose. `playwright` is imported lazily inside `walk()`, so this module
imports under `.venv-oracle` and the derivation is testable without a Chromium launch — the DOM half
is measured by running the instrument, which is a different claim and cannot be faked into a unit test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import census_rendered_surfaces as census  # noqa: E402
import walk_release as wr  # noqa: E402

VIDEOS = ["after", "before", "during", "overview"]


def media(videos, present):
    return {"videos": list(videos), "present": [{"file": f} for f in present]}


def files(*videos, langs=("en", "zh"), exts=("mp4", "vtt")):
    return [f"{v}.{lang}.{ext}" for v in videos for lang in langs for ext in exts]


def test_the_locale_count_is_read_from_the_census_not_assumed():
    # Two locales is the multiplier every number below rests on. If the site ever gains a third, this
    # arm fails first and says so, instead of the expectation quietly under-counting by a third.
    assert tuple(census.LOCALES) == ("en", "zh-TW")


def test_a_full_render_expects_one_player_per_video_per_locale():
    assert wr.playable_track_count(media(VIDEOS, files(*VIDEOS))) == 8


def test_the_overview_only_payload_expects_two_not_eight():
    # The state the site was published in on 2026-09-17: four scripts existed in the repo, one had been
    # rendered. The page shows one player; the walk must expect exactly one player per locale.
    assert wr.playable_track_count(media(VIDEOS, files("overview"))) == 2


def test_an_mp4_whose_captions_did_not_ship_is_not_playable():
    # `Design.tsx` requires the mp4 to render a player and the vtt to attach a caption track; the
    # build counts a video as rendered only with all four files. A walk expecting a player here would
    # report the missing captions as a missing video, which is the wrong defect.
    present = files("overview") + ["before.en.mp4", "before.zh.mp4"]
    assert wr.playable_track_count(media(VIDEOS, present)) == 2


def test_one_language_of_a_chapter_counts_only_in_that_locale():
    present = files("overview") + files("before", langs=("en",))
    assert wr.playable_track_count(media(VIDEOS, present)) == 3


def test_a_declared_script_with_no_bytes_contributes_nothing():
    # `videos` is every script in the repo, so it names videos that were never rendered. Counting a
    # declaration would make the walk demand a player the payload does not carry.
    assert wr.playable_track_count(media(VIDEOS, [])) == 0


def test_a_payload_with_no_manifest_expects_nothing_and_trips_the_floor():
    # What `derive_media` returns when `video/out/media/RENDER.json` is absent. Zero is the honest
    # expectation, and it is below `MIN_VIDEOS_TOTAL`, which is what makes the walk refuse to run
    # rather than pass over a page with no video on it (`feedback_zero_file_scan_is_error`).
    empty = {"videos": VIDEOS, "present": []}
    assert wr.playable_track_count(empty) == 0
    assert wr.playable_track_count(empty) < wr.MIN_VIDEOS_TOTAL


def test_files_present_for_a_video_the_manifest_does_not_declare_are_not_counted():
    # The opposite asymmetry: bytes in the payload for a script that is gone. They are counted by
    # nothing here, and `derive_media` refuses such a payload outright — this arm pins that this
    # function does not quietly resurrect the video.
    assert wr.playable_track_count(media(["overview"], files("overview", "before"))) == 2


def test_a_present_entry_without_a_file_key_does_not_crash_the_derivation():
    # `present` is payload-shaped input read off disk. A malformed entry must not take the walk out
    # with a KeyError before it has said anything about the release.
    bad = {"videos": ["overview"], "present": [{"bytes": 1}] + [{"file": f}
                                                                for f in files("overview")]}
    assert wr.playable_track_count(bad) == 2


def test_the_floor_is_no_longer_the_expectation():
    # The regression this file was written for: the constant must not be what the DOM is compared
    # against. If someone re-couples them, the overview-only case and the full case would both have to
    # equal the floor, which they do not.
    full = wr.playable_track_count(media(VIDEOS, files(*VIDEOS)))
    one = wr.playable_track_count(media(VIDEOS, files("overview")))
    assert full != one
    assert full > wr.MIN_VIDEOS_TOTAL


# --------------------------------------------------------------- what the walk demands of the mark
#
# `undecided_from_payload` is the other derived expectation in the walk, and the same argument applies to
# it: a constant `3` would be the three case ids a human adjudicated in issue #37, written down where
# nothing can notice a fourth. These arms pin the derivation over payload shapes that have all been
# reachable — three marked cases, none at all, a case whose verdict file is missing, and a control whose
# cited case is undecided in a finding rather than in `measured_by`.
#
# No browser here, deliberately, exactly as above: the DOM half is measured by running the instrument.

def payload_with(tmp_path, rows, controls=None, report=None):
    (tmp_path / "census.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    (tmp_path / "controls.json").write_text(
        json.dumps({"controls": controls if controls is not None else []}), encoding="utf-8")
    (tmp_path / "audit.json").write_text(
        json.dumps({"report": report if report is not None else {}}), encoding="utf-8")
    return tmp_path


def row(case, verdict, undecided=()):
    return {"case": case, "verdict": verdict, "undecided_subquestions": list(undecided)}


def test_the_marked_cases_are_read_from_the_census_row_the_lists_render_from(tmp_path):
    p = payload_with(tmp_path, [row("F6-2", "FALSE", ["the p99 tail"]),
                                row("F6-8", "FALSE", ["slope in [165,750]"]),
                                row("F1-1", "TRUE")])
    marked, verdicts, register_badges, audit_chips, report_chips = wr.undecided_from_payload(p)
    assert marked == {"F6-2": ["the p99 tail"], "F6-8": ["slope in [165,750]"]}
    assert verdicts["F6-2"] == "FALSE"
    assert register_badges == 3
    assert audit_chips == 0
    assert report_chips == 0


def test_a_payload_marking_nothing_returns_an_empty_mapping_for_main_to_refuse(tmp_path):
    # Not an exception: `main()` turns this into `CANNOT RUN`, because "no case is marked" is a claim
    # about the citation policy and the walk must say so rather than pass over an empty set
    # (`feedback_zero_needs_a_ran_flag`).
    marked, _, register_badges, _, _ = wr.undecided_from_payload(
        payload_with(tmp_path, [row("F1-1", "TRUE")]))
    assert marked == {}
    assert register_badges == 1


def test_the_register_badge_count_excludes_the_rows_with_no_verdict(tmp_path):
    # Two of the 93 registered cases carry no verdict file, and `VerdictBadge` renders those as
    # `v-none` — a lowercase token the probe's `^v-[A-Z]+$` filter does not collect. Counting them
    # would make the walk demand 93 badges where the DOM holds 91, and the arm would fail on a correct
    # page.
    p = payload_with(tmp_path, [row("F1-1", "TRUE"), row("F9-1", None), row("F10-1", None)])
    assert wr.undecided_from_payload(p)[2] == 1


def test_the_sub_questions_come_back_sorted_so_the_panels_can_be_compared_in_order(tmp_path):
    # The walk zips the panels it found against this list. Payload order is JSON order, which is not
    # guaranteed to be stable across builds, so the comparison would be flaky if either side were
    # unsorted.
    p = payload_with(tmp_path, [row("F6-2", "FALSE", ["the p99 tail", "a second sub-question"])])
    assert wr.undecided_from_payload(p)[0]["F6-2"] == ["a second sub-question", "the p99 tail"]


def test_only_the_cited_rows_the_audit_page_renders_are_counted(tmp_path):
    # `Audit.tsx` renders `measured_by` and never `findings[].cites`, and the real payload has F6-2 in
    # both. Counting the finding's copy would make the walk demand two daggers on a page that draws
    # one, which is a failure on a correct release — the other half of the same mistake as missing one.
    controls = [{
        "id": "enforcement_latency_budget",
        "measured_by": [{"case": "F6-2", "undecided": ["the p99 tail"]},
                        {"case": "F1-1", "undecided": []}],
        "findings": [{"cites": [{"case": "F6-2", "undecided": ["the p99 tail"]}]}],
    }]
    p = payload_with(tmp_path, [row("F6-2", "FALSE", ["the p99 tail"])], controls)
    assert wr.undecided_from_payload(p)[3] == 1


def test_a_control_with_no_cited_rows_at_all_contributes_no_expected_dagger(tmp_path):
    p = payload_with(tmp_path, [row("F6-2", "FALSE", ["the p99 tail"])],
                     [{"id": "c1"}, {"id": "c2", "measured_by": None}])
    assert wr.undecided_from_payload(p)[3] == 0


def test_the_report_page_expects_a_dagger_per_cited_row_and_per_licence(tmp_path):
    # `/report` draws a case beside a verdict in two places, and the producer is the audit CLI rather
    # than the site builder. Both were unmarked until the payload-wide sweep found them, so both are
    # counted here: a measurement's cited case, and the licence under a recommendation.
    report = {
        "controls": [{"measurements": [{"cases": [{"case": "F6-2", "verdict": "FALSE",
                                                  "undecided": ["the p99 tail"]},
                                                 {"case": "F1-1", "verdict": "TRUE",
                                                  "undecided": []}]}]}],
        "recommendations": [{"licensed_by": [{"case": "F6-2", "verdict": "FALSE",
                                              "undecided": ["the p99 tail"]}]}],
    }
    p = payload_with(tmp_path, [row("F6-2", "FALSE", ["the p99 tail"])], report=report)
    assert wr.undecided_from_payload(p)[4] == 2


def test_a_report_with_no_recommendation_at_all_counts_only_its_measurements(tmp_path):
    # The state the example submission would be in if no control it declares were in a measured state:
    # `recommendations` is empty and the page says so in prose. Counting a licence there would make the
    # walk demand a dagger on a page that draws none.
    report = {"controls": [{"measurements": [{"cases": [{"case": "F6-8", "verdict": "FALSE",
                                                         "undecided": ["slope in [165,750]"]}]}]}],
              "recommendations": []}
    p = payload_with(tmp_path, [row("F6-8", "FALSE", ["slope in [165,750]"])], report=report)
    assert wr.undecided_from_payload(p)[4] == 1
