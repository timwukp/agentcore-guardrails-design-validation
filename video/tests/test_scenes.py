"""The video's numbers come from the payload — proven with a payload that lies.

The rule being enforced is `no_hardcoded_totals` extended to a soundtrack: a count typed into a
scene or into the narration keeps being shown and spoken after the register moves, and a video
travels further than any page. Scanning the sources for forbidden literals cannot hold that rule —
`45` is also a coordinate, and the scan breaks the day a real count collides with a font size. So
the test is the LYING DOUBLE (`feedback_unreachable_branch_in_fake`, inverted): render everything
from a payload whose every count is a distinctive sentinel, and assert the sentinels surface. A
hardcoded number passes a real-payload render forever; it cannot pass this one once.

Every sentinel is DISTINCT, which is what catches a swap as well as a hardcode: if the scene wires
`n_uncited` where `adj_open` belongs, two identical sentinels would shrug and two distinct ones
fail the assertion naming the scene.

Run:  .venv-oracle/bin/python -m pytest video/tests/ -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scenes as scenes_mod  # noqa: E402

# ---------------------------------------------------------------- the lying payload

S = {  # placeholder -> sentinel; all distinct, none plausible as a coordinate or a font size
    "n_registered": 86093, "n_published": 86091,
    "v_true": 86046, "v_false": 86023, "v_inconclusive": 86020, "v_recorded": 86002,
    "before_practices": 86114, "during_practices": 86214, "after_practices": 86317,
    "n_uncited": 86006, "adj_open": 86007, "n_citations": 86324, "n_distinct": 86087,
}


def lying_payload() -> dict:
    def box(i: int, status: str) -> dict:
        return {"id": f"b{i}", "x": 40 + 240 * (i % 4), "y": 40 + 150 * (i // 4),
                "w": 200, "h": 96, "status": status,
                "label": {"en": f"box {i}", "zh": f"方框 {i}"}}

    boxes = ([box(i, "contested") for i in range(7)]
             + [box(7, "validated_in_part"), box(8, "validated_in_part")]
             + [box(i, "not_measured") for i in (9, 10, 11)])
    edges = [{"from": f"b{i}", "to": f"b{i + 1}", "route": "spine",
              "points": [[140 + 240 * (i % 4), 88], [140 + 240 * ((i + 1) % 4), 88]]}
             for i in range(3)]
    sections = []
    for i, (phase, per) in enumerate([("BEFORE", S["before_practices"]),
                                      ("DURING", S["during_practices"]),
                                      ("AFTER", S["after_practices"])]):
        # one fat section and two empty ones per phase, so the per-phase sum equals the sentinel
        sections += [
            {"id": f"{i + 3}.1", "phase": phase, "status": "contested",
             "heading": {"en": f"heading {phase}", "zh": f"標題 {phase}"}, "n_practices": per},
            {"id": f"{i + 3}.2", "phase": phase, "status": "not_measured",
             "heading": {"en": f"h2 {phase}", "zh": f"次 {phase}"}, "n_practices": 0},
        ]
    return {
        "census": {"verdict_mix": {"TRUE": S["v_true"], "FALSE": S["v_false"],
                                   "INCONCLUSIVE": S["v_inconclusive"],
                                   "RECORDED": S["v_recorded"]}},
        "denominators": {"registered": {"n": S["n_registered"]},
                         "published": {"n": S["n_published"]}},
        "practices": {
            "n_practices": 86045, "sections": sections,
            "coverage": {"n_uncited": S["n_uncited"]},
            "adjudications": {"n_open": S["adj_open"]},
            "citation_census": {"n_citations": S["n_citations"], "n_distinct": S["n_distinct"]},
        },
        "architecture": {"diagrams": [{
            "id": "closed_loop",
            "viewbox": {"min_x": 0, "min_y": 0, "width": 1000, "height": 520},
            "boxes": boxes, "edges": edges,
            "boxes_by_status": {"contested": 7, "validated_in_part": 2, "not_measured": 3},
        }]},
    }


SCRIPT = yaml.safe_load((HERE.parent / "script" / "overview.yaml").read_text(encoding="utf-8"))

# Which scene must surface which sentinels, as rendered FRAMES. Not every placeholder is drawn —
# some are spoken only — so this table is the drawn subset, and the narration test below covers all.
FRAME_EXPECTATIONS = {
    "claim": ["n_registered", "n_published"],
    "verdicts": ["v_true", "v_false", "v_inconclusive", "v_recorded"],
    "colours": [],  # counts appear in the legend via resolve(); asserted structurally below
    "before": [], "during": [], "after": [],  # per-section counts render, checked structurally
    "honesty": ["n_uncited", "adj_open"],
    "verify": ["n_citations", "n_distinct"],
}


def test_resolve_reports_the_sentinels_not_the_reals():
    values = scenes_mod.resolve(lying_payload())
    for key, sentinel in S.items():
        assert values[key] == sentinel, f"resolve() did not derive {key} from the payload"


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


def test_every_narration_placeholder_resolves_and_every_count_is_a_placeholder():
    """Both directions. Forward: format_map over the sentinel values leaves no `{…}` behind.
    Backward: after resolution, every sentinel named by the scene's template is IN the text —
    and the template itself contains no bare digits long enough to be a smuggled count (short
    numerals like the document's own §2.1 are legitimate; a 2+-digit standalone integer is not)."""
    values = scenes_mod.resolve(lying_payload())
    for sc in SCRIPT["scenes"]:
        for lang in ("en", "zh"):
            template = sc[lang]
            resolved = template.format_map(values)
            assert not re.findall(r"\{[a-z_]+\}", resolved), f"{sc['id']}/{lang} leaves a placeholder"
            for name in re.findall(r"\{([a-z_]+)\}", template):
                assert str(values[name]) in resolved
            bare = re.findall(r"(?<![\d.\w])\d{2,}(?![\d.\w])", template)
            assert not bare, (f"{sc['id']}/{lang} carries bare number(s) {bare} — a count typed "
                              f"into the narration keeps being spoken after the register moves")


def test_script_and_scene_builder_agree_on_the_scene_list():
    built = [sid for sid, _ in scenes_mod.scenes(lying_payload(), "en")]
    scripted = [s["id"] for s in SCRIPT["scenes"]]
    assert built == scripted, (
        f"script {scripted} vs scenes.py {built}: narration and frames pair up by position, "
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


def test_zh_narration_is_chinese_and_en_is_not():
    han = re.compile(r"[一-鿿]")
    for sc in SCRIPT["scenes"]:
        assert han.search(sc["zh"]), f"{sc['id']}: zh narration carries no Han"
        assert not han.search(sc["en"]), f"{sc['id']}: en narration carries Han"


def test_palette_and_status_mapping_still_parse_from_the_stylesheet():
    """The parsers are claims about styles.css's shape (`feedback_discovery_pattern_is_a_claim`);
    zero-yield must be an error there, so here the real file must still satisfy them."""
    palette = scenes_mod.css_vars()
    st = scenes_mod.status_colours(palette)
    for status in ("contested", "validated_in_part", "not_measured", "not_established",
                   "context_only"):
        assert status in st and st[status].startswith("#"), f"no colour resolved for {status}"
