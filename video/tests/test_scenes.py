"""The videos' numbers come from the payload — proven with a payload that lies.

The rule being enforced is `no_hardcoded_totals` extended to a soundtrack: a count typed into a
scene or into the narration keeps being shown and spoken after the register moves, and a video
travels further than any page. Scanning the sources for forbidden literals cannot hold that rule —
`45` is also a coordinate, and the scan breaks the day a real count collides with a font size. So
the test is the LYING DOUBLE (`feedback_unreachable_branch_in_fake`, inverted): render everything
from a payload whose every count is a distinctive sentinel, and assert the sentinels surface. A
hardcoded number passes a real-payload render forever; it cannot pass this one once.

Every sentinel is DISTINCT, which is what catches a swap as well as a hardcode: if the scene wires
`n_uncited` where `adj_open` belongs, two identical sentinels would shrug and two distinct ones
fail the assertion naming the scene. The three phase chapters make that stronger in the one way a
chapter can go wrong: each phase's sentinels are distinct from the other two phases', and each
chapter is asserted NOT to show its neighbours' numbers, so `before` reading `during`'s field is a
failure rather than a plausible frame.

Two derivations the fake exists to discriminate, neither of which a real-payload render can:

  * DISTINCT versus SUMMED cases. Each phase's checkpoints cite one case TWICE, so
    `sum(n_cases)` is one greater than the number of cases that exist. A verdict mix drawn beside a
    summed total adds up past it.
  * NON-COLOURING versus ANY restriction. Some cases carry `PARTIAL` (which does colour) and others
    `UNMEASURED` (which does not); an implementation counting "cases with a restriction" reads the
    wrong number here and the right-looking one against the real payload.

Run:  .venv-oracle/bin/python -m pytest video/tests/ -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scenes as scenes_mod  # noqa: E402

SCRIPT_DIR = HERE.parent / "script"

# ---------------------------------------------------------------- the lying payload

S = {  # placeholder -> sentinel; all distinct, none plausible as a coordinate or a font size
    "n_registered": 86093, "n_published": 86091,
    "v_true": 86046, "v_false": 86023, "v_inconclusive": 86020, "v_recorded": 86002,
    "before_practices": 86114, "during_practices": 86214, "after_practices": 86317,
    "n_uncited": 86006, "adj_open": 86007, "n_citations": 86324, "n_distinct": 86087,
}

# The per-phase chapter numbers. Three digits rather than five, because each one is the LENGTH of a
# case list the fake actually builds — a five-digit mix would be a quarter of a million dicts to
# assert one wiring. Every value is >= 500 and none is 820, so none collides with a coordinate, a
# font size, or the two SVG dimensions the page template writes (1560, 820, 1920, 1080). "Plausible"
# is not eyeballed: `test_the_chapter_sentinels_do_not_collide_with_the_geometry` derives the numbers
# the diagram actually emits and rejects any sentinel among them — 613 was chosen here first and is an
# arrowhead's x (620 - 7), which made every chapter look like it was showing DURING's number.
MIX = {
    "before": {"true": 503, "false": 509, "inconclusive": 521, "recorded": 523, "unpublished": 541},
    "during": {"true": 547, "false": 557, "inconclusive": 563, "recorded": 569, "unpublished": 571},
    "after": {"true": 577, "false": 587, "inconclusive": 593, "recorded": 599, "unpublished": 601},
}
RESTRICTED = {"before": 607, "during": 659, "after": 617}
OWN = {"before": 619, "during": 673, "after": 641}
INHERITED = {"before": 643, "during": 647, "after": 653}
# `_cases` is the DISTINCT total, so it is the sum of the mix — and the fake duplicates one case per
# phase, which is what makes this different from `sum(n_cases)` over the sections.
CASES = {p: sum(m.values()) for p, m in MIX.items()}

PHASE_OF = {"before": "BEFORE", "during": "DURING", "after": "AFTER"}
# Prose the payload owns and a frame must quote rather than restate.
WHY = {p: f"WHY-{p.upper()}-DERIVED-BY-THE-BUILD" for p in PHASE_OF}
HEADING = {p: f"HEADING-{p.upper()}-FROM-THE-DOCUMENT" for p in PHASE_OF}
MEANS = "MEANS-CONTESTED-FROM-THE-VOCABULARY"


def _phase_cases(prefix: str) -> list[dict]:
    """One phase's case list: the mix by sentinel count, with restrictions placed so that
    `non_colouring_restrictions` is the only filter that yields RESTRICTED[prefix]."""
    out: list[dict] = []
    verdicts = [("TRUE", "true"), ("FALSE", "false"), ("INCONCLUSIVE", "inconclusive"),
                ("RECORDED", "recorded"), (None, "unpublished")]
    i = 0
    for verdict, bucket in verdicts:
        for _ in range(MIX[prefix][bucket]):
            i += 1
            # The first RESTRICTED[prefix] cases carry a restriction that colours nothing; the next
            # ten carry one that DOES colour, so "any restriction" over-counts by exactly ten.
            if i <= RESTRICTED[prefix]:
                restrictions = ["UNMEASURED"]
            elif i <= RESTRICTED[prefix] + 10:
                restrictions = ["PARTIAL"]
            else:
                restrictions = []
            out.append({"case": f"{prefix[0].upper()}{i}", "family": prefix[0].upper(),
                        "restrictions": restrictions, "verdict": verdict,
                        "title": f"case {i} in {prefix}"})
    return out


def lying_payload() -> dict:
    def box(i: int, status: str, from_section: str | None = None, kind: str = "checkpoint") -> dict:
        # Column 1 of the fake's grid is its satellite column, mirroring the payload's own shape: a
        # satellite sits in its parent's row, to the right of the spine. Both label-anchoring branches
        # therefore render on every frame that draws the loop.
        return {"id": f"b{i}", "x": 40 + 240 * (i % 4), "y": 40 + 150 * (i // 4),
                "w": 200, "h": 96, "status": status, "kind": kind, "from_section": from_section,
                "satellite": i % 4 == 1,
                "label": {"en": f"box {i}", "zh": f"方框 {i}"}}

    # Boxes 0/4/8 carry the three phases' first sections; 1/5/9 their second. The rest belong to no
    # section at all (the caller, the model, the response) exactly as the real diagram's do, so a
    # chapter that highlighted "everything with a status" would fail the highlight test.
    owners = {0: "3.1", 1: "3.2", 4: "4.1", 5: "4.2", 8: "5.1", 9: "5.2"}
    kinds = {1: "alternative", 5: "property", 9: "stage"}
    boxes = ([box(i, "contested", owners.get(i), kinds.get(i, "checkpoint")) for i in range(7)]
             + [box(7, "validated_in_part"), box(8, "validated_in_part", owners[8])]
             + [box(i, "not_measured", owners.get(i), kinds.get(i, "checkpoint"))
                for i in (9, 10, 11)])
    edges = [{"from": f"b{i}", "to": f"b{i + 1}", "route": "spine",
              "points": [[140 + 240 * (i % 4), 88], [140 + 240 * ((i + 1) % 4), 88]]}
             for i in range(3)]
    sections, practices = [], []
    for i, prefix in enumerate(("before", "during", "after")):
        phase = PHASE_OF[prefix]
        cases = _phase_cases(prefix)
        sections += [
            # One fat section and one that re-cites a single case the fat one already cited: the
            # phase's DISTINCT total is len(cases), while sum(n_cases) is one more.
            {"id": f"{i + 3}.1", "phase": phase, "status": "contested",
             "heading": {"en": HEADING[prefix], "zh": HEADING[prefix]},
             "why_this_status": {"en": WHY[prefix], "zh": WHY[prefix]},
             "n_practices": S[f"{prefix}_practices"], "n_cases": len(cases), "cases": cases},
            {"id": f"{i + 3}.2", "phase": phase, "status": "not_measured",
             "heading": {"en": f"h2 {phase}", "zh": f"次 {phase}"},
             "why_this_status": {"en": f"why2 {phase}", "zh": f"why2 {phase}"},
             "n_practices": 0, "n_cases": 1, "cases": [cases[0]]},
        ]
        practices += (
            [{"key": f"bp:{i + 3}.1#{k}", "phase": phase, "status_basis": "practice",
              "status": "contested"} for k in range(OWN[prefix])]
            + [{"key": f"bp:{i + 3}.2#{k}", "phase": phase, "status_basis": "section",
                "status": "contested"} for k in range(INHERITED[prefix])]
            # Three practices per phase resting on nothing, so neither bucket may be derived as
            # "the practices that are not in the other one".
            + [{"key": f"bp:{i + 3}.3#{k}", "phase": phase, "status_basis": "none",
                "status": "not_measured"} for k in range(3)])
    return {
        "census": {"verdict_mix": {"TRUE": S["v_true"], "FALSE": S["v_false"],
                                   "INCONCLUSIVE": S["v_inconclusive"],
                                   "RECORDED": S["v_recorded"]}},
        "denominators": {"registered": {"n": S["n_registered"]},
                         "published": {"n": S["n_published"]}},
        "practices": {
            "n_practices": 86045, "sections": sections, "practices": practices,
            "coverage": {"n_uncited": S["n_uncited"]},
            "adjudications": {"n_open": S["adj_open"]},
            "citation_census": {"n_citations": S["n_citations"], "n_distinct": S["n_distinct"]},
            "non_colouring_restrictions": ["UNMEASURED", "UNTESTABLE", "NOT_A_VERDICT"],
            "status_labels": {"contested": {"en": MEANS, "zh": MEANS},
                              "not_measured": {"en": "never tested", "zh": "從未測試"}},
        },
        "architecture": {"diagrams": [{
            "id": "closed_loop",
            "viewbox": {"min_x": 0, "min_y": 0, "width": 1000, "height": 520},
            "boxes": boxes, "edges": edges,
            "boxes_by_status": {"contested": 7, "validated_in_part": 2, "not_measured": 3},
        }]},
    }


def script_of(video: str) -> dict:
    return yaml.safe_load((SCRIPT_DIR / f"{video}.yaml").read_text(encoding="utf-8"))


VIDEOS = sorted(p.stem for p in SCRIPT_DIR.glob("*.yaml"))
SCRIPT = script_of("overview")

# Which OVERVIEW scene must surface which sentinels, as rendered FRAMES. Not every placeholder is
# drawn — some are spoken only — so this table is the drawn subset, and the narration test covers all.
FRAME_EXPECTATIONS = {
    "claim": ["n_registered", "n_published"],
    "verdicts": ["v_true", "v_false", "v_inconclusive", "v_recorded"],
    "colours": [],  # counts appear in the legend via resolve(); asserted structurally below
    "before": [], "during": [], "after": [],  # per-section counts render, checked structurally
    "honesty": ["n_uncited", "adj_open"],
    "verify": ["n_citations", "n_distinct"],
}


def test_the_scripts_are_the_four_videos_and_each_has_a_builder():
    """The set of videos is `script/*.yaml` in three places — `render.all_videos()`,
    `derive_media()` and `arm_media` — so a script with no scene builder must fail here rather than
    render an empty chapter into a payload that expects four files for it."""
    assert VIDEOS == ["after", "before", "during", "overview"], VIDEOS
    payload = lying_payload()
    for video in VIDEOS:
        built = [sid for sid, _ in scenes_mod.scenes(payload, "en", video)]
        assert built, f"{video} builds no scenes"


def test_an_unknown_video_is_refused_rather_than_rendered_empty():
    with pytest.raises(SystemExit):
        scenes_mod.scenes(lying_payload(), "en", "phase-two-electric-boogaloo")


def test_resolve_reports_the_sentinels_not_the_reals():
    values = scenes_mod.resolve(lying_payload())
    for key, sentinel in S.items():
        assert values[key] == sentinel, f"resolve() did not derive {key} from the payload"


def test_resolve_counts_distinct_cases_not_summed_ones():
    """Each phase's second section re-cites a case the first already cited. `sum(n_cases)` is
    therefore one greater than the number of cases in the phase, and only the distinct count can sit
    beside a verdict mix without the mix adding up past it."""
    payload = lying_payload()
    values = scenes_mod.resolve(payload)
    for prefix, phase in PHASE_OF.items():
        summed = sum(s["n_cases"] for s in scenes_mod.phase_sections(payload, phase))
        assert values[f"{prefix}_cases"] == CASES[prefix]
        assert summed == CASES[prefix] + 1, "the fake no longer double-cites, so it discriminates nothing"
        mix = sum(values[f"{prefix}_{k}"] for k in
                  ("true", "false", "inconclusive", "recorded", "unpublished"))
        assert mix == values[f"{prefix}_cases"], (
            f"{prefix}: the verdict mix sums to {mix} beside a total of {values[f'{prefix}_cases']}")


def test_resolve_counts_only_the_restrictions_that_colour_nothing():
    values = scenes_mod.resolve(lying_payload())
    for prefix in PHASE_OF:
        assert values[f"{prefix}_restricted"] == RESTRICTED[prefix], (
            f"{prefix}_restricted counts something other than the payload's own "
            f"non_colouring_restrictions — ten cases here carry a restriction that DOES colour")


def test_resolve_splits_the_practice_basis_from_the_practices_list():
    values = scenes_mod.resolve(lying_payload())
    for prefix in PHASE_OF:
        assert values[f"{prefix}_own"] == OWN[prefix]
        assert values[f"{prefix}_inherited"] == INHERITED[prefix]


def test_frames_surface_the_sentinels():
    payload = lying_payload()
    for lang in ("en", "zh"):
        html_by_id = {sid: "".join(steps) for sid, steps in scenes_mod.scenes(payload, lang)}
        for sid, keys in FRAME_EXPECTATIONS.items():
            for key in keys:
                assert str(S[key]) in html_by_id[sid], (
                    f"[{lang}] scene {sid!r} does not show the payload's {key} — "
                    f"either hardcoded or wired to the wrong field")


def test_phase_scenes_show_each_sections_own_count():
    payload = lying_payload()
    for lang in ("en", "zh"):
        html_by_id = dict((sid, "".join(steps)) for sid, steps in scenes_mod.scenes(payload, lang))
        for sid, key in (("before", "before_practices"), ("during", "during_practices"),
                         ("after", "after_practices")):
            assert str(S[key]) in html_by_id[sid], (
                f"[{lang}] scene {sid!r} does not carry its phase's practice count")


# Which CHAPTER scene must surface which of its phase's numbers.
CHAPTER_EXPECTATIONS = {
    "title": ("practices", "cases"),
    "checkpoints": ("practices",),
    "evidence": ("cases", "true", "false", "inconclusive", "recorded", "unpublished", "restricted"),
    "basis": ("own", "inherited"),
}


def _chapter_numbers(prefix: str) -> dict[str, int]:
    return {"practices": S[f"{prefix}_practices"], "cases": CASES[prefix],
            "restricted": RESTRICTED[prefix], "own": OWN[prefix], "inherited": INHERITED[prefix],
            **{k: v for k, v in MIX[prefix].items()}}


@pytest.mark.parametrize("prefix", sorted(PHASE_OF))
@pytest.mark.parametrize("lang", ("en", "zh"))
def test_chapter_frames_surface_their_own_phases_numbers(prefix: str, lang: str):
    frames = dict(scenes_mod.scenes(lying_payload(), lang, prefix))
    numbers = _chapter_numbers(prefix)
    for sid, keys in CHAPTER_EXPECTATIONS.items():
        html = "".join(frames[sid])
        for key in keys:
            assert str(numbers[key]) in html, (
                f"[{lang}] {prefix} chapter scene {sid!r} does not show its phase's {key}")


def test_no_sentinel_is_a_substring_of_another_sentinel():
    """Every assertion in this file is `str(sentinel) in html` or its negation, so a sentinel that is
    a substring of another one is satisfied by the wrong number. `631` was DURING's own-citation count
    and sits inside `86317`, AFTER's practice count, which made the AFTER chapter look cross-wired."""
    everything = {f"S.{k}": v for k, v in S.items()}
    for prefix in PHASE_OF:
        # `practices` is deliberately the same quantity as `S.{prefix}_practices` — the overview and
        # the chapter show one number, and the chapter test reads it back out of S.
        everything.update({f"{prefix}.{k}": v for k, v in _chapter_numbers(prefix).items()
                          if k != "practices"})
    assert len(set(everything.values())) == len(everything), "two sentinels share a value"
    for name, value in everything.items():
        for other, ov in everything.items():
            if name != other:
                assert str(value) not in str(ov), f"{name} ({value}) hides inside {other} ({ov})"


def test_the_chapter_sentinels_do_not_collide_with_the_geometry():
    """The cross-phase test below reads "another phase's number is absent from this chapter's HTML",
    which is only a claim about wiring while no sentinel is also a coordinate. Layout numbers are
    DERIVED from the fake's boxes — arrowheads are `x - 7`, text baselines are `y + 57` — so the
    collision check is derived too, rather than a list of dimensions someone remembered."""
    payload = lying_payload()
    palette = scenes_mod.css_vars()
    cl = payload["architecture"]["diagrams"][0]
    svg = scenes_mod._diagram_svg(cl, palette, scenes_mod.status_colours(palette), "en",
                                  boxes_shown=len(cl["boxes"]), coloured=True)
    for prefix in PHASE_OF:
        for key, value in _chapter_numbers(prefix).items():
            assert str(value) not in svg, (
                f"the {prefix} {key} sentinel ({value}) is also a number the diagram draws; pick "
                f"another one, or the cross-phase assertion is testing the layout")


@pytest.mark.parametrize("prefix", sorted(PHASE_OF))
def test_a_chapter_never_shows_another_phases_numbers(prefix: str):
    """The failure a chapter is uniquely exposed to: reading the right field for the wrong phase.
    Every phase's sentinels are distinct, so the neighbours' values must be absent entirely."""
    html = "".join(h for _, steps in scenes_mod.scenes(lying_payload(), "en", prefix)
                   for h in steps)
    for other in PHASE_OF:
        if other == prefix:
            continue
        for key, value in _chapter_numbers(other).items():
            assert str(value) not in html, (
                f"the {prefix} chapter shows {other}'s {key} ({value}) — a chapter wired to the "
                f"wrong phase renders perfectly and says the wrong thing")


@pytest.mark.parametrize("prefix", sorted(PHASE_OF))
@pytest.mark.parametrize("lang", ("en", "zh"))
def test_chapter_quotes_the_payloads_prose_rather_than_restating_it(prefix: str, lang: str):
    """The status scene's job is to show the BUILD's own reason for a colour, and the vocabulary's own
    sentence for what the colour means. Both are payload prose; a chapter that summarised them would
    be a second wording with no provenance but the wording."""
    frames = dict(scenes_mod.scenes(lying_payload(), lang, prefix))
    status = "".join(frames["status"])
    assert WHY[prefix] in status, f"{prefix}/{lang}: the derived reason is not quoted"
    assert HEADING[prefix] in status, f"{prefix}/{lang}: the document's heading is not quoted"
    assert MEANS in status, f"{prefix}/{lang}: the status vocabulary's own sentence is not shown"
    assert len(frames["status"]) == 2, "one frame per checkpoint in the phase"


@pytest.mark.parametrize("prefix", sorted(PHASE_OF))
def test_chapter_highlights_exactly_the_boxes_its_own_sections_own(prefix: str):
    """`where` fades the rest of the loop instead of dropping it. Both halves are asserted: the
    phase's own boxes must NOT be faded, and every other box must be — a chapter that faded nothing
    would look like the overview and one that faded everything like a bug in a screenshot."""
    payload = lying_payload()
    cl = payload["architecture"]["diagrams"][0]
    sec_ids = {s["id"] for s in scenes_mod.phase_sections(payload, PHASE_OF[prefix])}
    mine = [b for b in cl["boxes"] if b.get("from_section") in sec_ids]
    assert len(mine) == 2, "the fake gives each phase two owned boxes"
    html = "".join(dict(scenes_mod.scenes(payload, "en", prefix))["where"])
    for b in cl["boxes"]:
        rect = re.search(rf'<rect x="{b["x"]}" y="{b["y"]}"[^>]*>', html)
        assert rect, f"box {b['id']} is not drawn at all"
        faded = 'opacity="0.3"' in rect.group(0)
        assert faded == (b not in mine), (
            f"box {b['id']} fade={faded}; it {'does' if b in mine else 'does not'} belong to "
            f"{prefix}")
    # And the kind chips name what the payload declares each of them to be, because the narration
    # says one of these boxes is a property rather than a gate.
    for b in mine:
        assert f'§{b["from_section"]} {b["kind"]}' in html


@pytest.mark.parametrize("video", VIDEOS)
def test_every_narration_placeholder_resolves_and_every_count_is_a_placeholder(video: str):
    """Both directions. Forward: format_map over the sentinel values leaves no `{…}` behind.
    Backward: after resolution, every sentinel named by the scene's template is IN the text —
    and the template itself contains no bare digits long enough to be a smuggled count (short
    numerals like the document's own §2.1 are legitimate; a 2+-digit standalone integer is not)."""
    values = scenes_mod.resolve(lying_payload())
    for sc in script_of(video)["scenes"]:
        for lang in ("en", "zh"):
            template = sc[lang]
            resolved = template.format_map(values)
            assert not re.findall(r"\{[a-z_]+\}", resolved), f"{sc['id']}/{lang} leaves a placeholder"
            for name in re.findall(r"\{([a-z_]+)\}", template):
                assert str(values[name]) in resolved
            bare = re.findall(r"(?<![\d.\w])\d{2,}(?![\d.\w])", template)
            assert not bare, (f"{video}/{sc['id']}/{lang} carries bare number(s) {bare} — a count "
                              f"typed into the narration keeps being spoken after the register moves")


@pytest.mark.parametrize("video", VIDEOS)
def test_a_chapters_narration_names_only_its_own_phases_placeholders(video: str):
    """A chapter speaking `{during_cases}` in the BEFORE video would be resolved, spoken, and
    wrong. The overview is the one video allowed all three phases."""
    if video == "overview":
        return
    others = [p for p in PHASE_OF if p != video]
    for sc in script_of(video)["scenes"]:
        for lang in ("en", "zh"):
            named = set(re.findall(r"\{([a-z_]+)\}", sc[lang]))
            leaked = sorted(n for n in named if any(n.startswith(f"{o}_") for o in others))
            assert not leaked, f"{video}/{sc['id']}/{lang} speaks another phase's numbers: {leaked}"


@pytest.mark.parametrize("video", VIDEOS)
def test_script_and_scene_builder_agree_on_the_scene_list(video: str):
    built = [sid for sid, _ in scenes_mod.scenes(lying_payload(), "en", video)]
    scripted = [s["id"] for s in script_of(video)["scenes"]]
    assert built == scripted, (
        f"{video}: script {scripted} vs scenes.py {built}: narration and frames pair up by position, "
        f"so a disagreement here is scene 4's audio over scene 5's picture, not an error message")


def test_diagram_draws_only_edges_between_shown_boxes():
    """The progressive reveal must not draw an arrow into a box that has not appeared — two
    arrows meeting at nothing read as a relation to nowhere."""
    payload = lying_payload()
    palette = scenes_mod.css_vars()
    st = scenes_mod.status_colours(palette)
    cl = payload["architecture"]["diagrams"][0]
    partial = scenes_mod._diagram_svg(cl, palette, st, "en", boxes_shown=2, coloured=False)
    assert partial.count("<rect") == 2
    assert partial.count("<polyline") == 1  # only b0->b1 has both ends shown


def test_every_label_leans_away_from_the_other_column():
    """A box label is drawn OUTSIDE its box — 66 characters do not fit in 200 units — so the only
    thing keeping two labels apart is which side each leans to. Centred text shipped an unreadable
    overlap on three hops of the live overview, and no JSON assertion saw it: the picture was correct
    and the text on top of it was not. This asserts the geometry that replaced it, in both directions,
    from the payload's own `satellite` flag.
    """
    payload = lying_payload()
    palette = scenes_mod.css_vars()
    cl = payload["architecture"]["diagrams"][0]
    svg = scenes_mod._diagram_svg(cl, palette, scenes_mod.status_colours(palette), "en",
                                  boxes_shown=None, coloured=True)
    placed = {m.group(3): (float(m.group(1)), m.group(2))
              for m in re.finditer(r'<text x="([-\d.]+)"[^>]*text-anchor="(start|end)"[^>]*>'
                                   r"box (\d+)</text>", svg)}
    assert len(placed) == len(cl["boxes"]), f"only {len(placed)} of {len(cl['boxes'])} labels placed"
    kinds = {a for _, a in placed.values()}
    assert kinds == {"start", "end"}, f"only {kinds} used; one of the two branches never renders"
    for b in cl["boxes"]:
        x, anchor = placed[b["id"][1:]]
        if b["satellite"]:
            assert anchor == "start" and x >= b["x"] + b["w"], (
                f"{b['id']} is a satellite; its label must start to the RIGHT of it, not at {x}")
        else:
            assert anchor == "end" and x <= b["x"], (
                f"{b['id']} is on the spine; its label must end to the LEFT of it, not at {x}")


def gutter_payload() -> dict:
    """The lying payload plus the one thing it lacks: connectors running down the LEFT margin.

    The real closed loop returns from its last hop to its first through the left gutter, and its
    feedback edge runs further out still — x = -38 and -68 in the published geometry. The fake's
    edges are all horizontal at x >= 140, so it can never show a label meeting a connector. Rather
    than move the fake (its coordinates are load-bearing for the sentinel-collision arm), this adds
    the two edges the real payload has, at the real payload's x values.
    """
    payload = lying_payload()
    cl = payload["architecture"]["diagrams"][0]
    last = cl["boxes"][-1]["id"]
    first = cl["boxes"][0]["id"]
    cl["edges"] = list(cl["edges"]) + [
        {"from": last, "to": first, "route": "gutter",
         "points": [[40, 1000], [-38, 1000], [-38, 88], [40, 88]]},
        {"from": last, "to": first, "route": "feedback",
         "points": [[40, 1040], [-68, 1040], [-68, 60], [40, 60]]},
    ]
    return payload


def test_no_spine_label_crosses_a_connector():
    """The defect one step quieter than the overlap above, and found the same way — by opening the
    PNG (`feedback_chart_encoding_defects`).

    Leaning the spine labels left of their boxes separated them from the satellites' and put them
    straight across the return path: the gutter and feedback edges run down the same left margin, so
    a 56-character label anchored 16 units left of a box at x=0 had its tail crossing two 3-unit
    strokes, and the arrowhead re-entering the first hop landed inside the label's last word. Nothing
    in the payload, the manifest or the caption file could see it.

    Both sides of this gate are DERIVED (`feedback_derive_both_sides_of_a_gate`): the clearance line
    is the minimum x over EVERY point of EVERY edge — not the edges whose `route` this test believes
    runs left, because a route vocabulary is a name list — and the label position is read back out of
    the emitted SVG. So a new left-margin edge at x = -120 fails this arm instead of silently
    re-crossing the labels.
    """
    payload = gutter_payload()
    palette = scenes_mod.css_vars()
    cl = payload["architecture"]["diagrams"][0]
    svg = scenes_mod._diagram_svg(cl, palette, scenes_mod.status_colours(palette), "en",
                                  boxes_shown=None, coloured=True)
    leftmost_stroke = min(x for e in cl["edges"] for x, _ in e["points"])
    assert leftmost_stroke < 0, (
        "this fixture exists to put connectors left of the boxes; with none there the assertion "
        "below passes without discriminating anything")
    placed = {m.group(3): (float(m.group(1)), m.group(2))
              for m in re.finditer(r'<text x="([-\d.]+)"[^>]*text-anchor="(start|end)"[^>]*>'
                                   r"box (\d+)</text>", svg)}
    spine = [b for b in cl["boxes"] if not b["satellite"]]
    assert spine, "no spine box in the fixture"
    for b in spine:
        x, anchor = placed[b["id"][1:]]
        assert anchor == "end", f"{b['id']}: a label that grows RIGHT from {x} crosses the gutter"
        # `end` means the text occupies (-inf, x], so clearing the strokes is one comparison — and
        # the margin has to exceed the 7-unit arrowhead, or the head entering a box lands on the
        # label even though the polyline itself does not.
        assert x <= leftmost_stroke - 7, (
            f"{b['id']}'s label ends at x={x} but a connector runs at x={leftmost_stroke}: the "
            f"text crosses the stroke, and the arrowhead reaches 7 units further still")


def test_a_spine_label_does_not_move_as_the_reveal_adds_boxes():
    """The reveal draws the same diagram with more boxes each scene. If the clearance line were
    computed from the edges this FRAME draws, the labels would slide left as the return path
    appeared, and every earlier scene's text would sit somewhere the final scene's does not — an
    animation nobody would call a bug and nobody could read either.
    """
    payload = gutter_payload()
    palette = scenes_mod.css_vars()
    st = scenes_mod.status_colours(palette)
    cl = payload["architecture"]["diagrams"][0]

    def label_x(shown: int | None) -> dict[str, float]:
        svg = scenes_mod._diagram_svg(cl, palette, st, "en", boxes_shown=shown, coloured=True)
        return {m.group(2): float(m.group(1))
                for m in re.finditer(r'<text x="([-\d.]+)"[^>]*text-anchor="end"[^>]*>'
                                     r"box (\d+)</text>", svg)}

    full = label_x(None)
    early = label_x(2)
    assert early, "the two-box frame draws no spine label; the comparison below is vacuous"
    for box_id, x in early.items():
        assert x == full[box_id], (
            f"box {box_id}'s label sits at {x} early and {full[box_id]} at the end: the clearance "
            f"is being read from the visible edges instead of the whole edge list")


@pytest.mark.parametrize("video", VIDEOS)
def test_zh_narration_is_chinese_and_en_is_not(video: str):
    han = re.compile(r"[一-鿿]")
    for sc in script_of(video)["scenes"]:
        assert han.search(sc["zh"]), f"{video}/{sc['id']}: zh narration carries no Han"
        assert not han.search(sc["en"]), f"{video}/{sc['id']}: en narration carries Han"


@pytest.mark.parametrize("video", VIDEOS)
def test_every_script_discloses_the_synthesis_in_both_languages(video: str):
    """Each video is watched on its own, so each one has to say what it is. A disclosure that
    appeared only in the overview would leave three chapters speaking in a synthesized voice with
    nothing said about it."""
    scenes_ = script_of(video)["scenes"]
    assert any("Amazon Polly" in sc["en"] for sc in scenes_), f"{video}: no en disclosure"
    assert any("Amazon Polly" in sc["zh"] for sc in scenes_), f"{video}: no zh disclosure"


def test_palette_and_status_mapping_still_parse_from_the_stylesheet():
    """The parsers are claims about styles.css's shape (`feedback_discovery_pattern_is_a_claim`);
    zero-yield must be an error there, so here the real file must still satisfy them."""
    palette = scenes_mod.css_vars()
    st = scenes_mod.status_colours(palette)
    for status in ("contested", "validated_in_part", "not_measured", "not_established",
                   "context_only"):
        assert status in st and st[status].startswith("#"), f"no colour resolved for {status}"
