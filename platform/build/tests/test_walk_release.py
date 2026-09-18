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
