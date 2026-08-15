"""Tests for the deck generator — the parts where a silent failure looks like a slide.

Three defects found by hand while building the v1.4 decks are pinned here, because each
one produced a *plausible* slide rather than an error: a code span inside bold printed
its own backticks, an abridged cell left a ``**`` unclosed, and ``<a:cs>`` was written
before ``<a:ea>`` (out of schema order, which makes PowerPoint offer to repair the file).

The renderer needs python-pptx, which is installed on the system interpreter and NOT in
``.venv-oracle``; those tests skip rather than fail there, so the oracle suite stays green
on a machine that will never build a deck.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from deckgen import mdsource  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


# -- mdsource: no python-pptx needed --------------------------------------- #


def test_abridge_keeps_whole_sentences():
    text = "First sentence here. Second sentence is longer than the budget allows."
    out = mdsource.abridge(text, 30)
    assert out == "First sentence here."
    assert "Second" not in out


def test_abridge_returns_original_when_one_sentence_exceeds_budget():
    # Truncating mid-clause can invert a meaning, so the whole sentence is kept and
    # the table's own fit loop shrinks the type instead.
    text = "A single unbroken sentence that is far longer than the budget given to it"
    assert mdsource.abridge(text, 20) == text


def test_abridge_measures_cjk_as_double_width():
    zh = "第一句話。第二句話比預算允許的長度更長,所以應該被丟掉。"
    # 5 CJK glyphs + the full stop = 12 columns, so a 14-column budget fits sentence 1 only
    assert mdsource.abridge(zh, 14) == "第一句話。"


def test_abridge_closes_a_bold_span_it_cut():
    # The bug: the closing ** lived in the dropped sentence, so the slide showed "**".
    text = "Measured absent. **Do not point calibration here. Use the application log.**"
    out = mdsource.abridge(text, 24)
    assert out.count("**") % 2 == 0, out


def test_abridge_closes_a_code_span_it_cut():
    text = "Absent at every dimension. Use `LogOnlyMatches > 0` as the positive gate."
    out = mdsource.abridge(text, 30)
    assert out.count("`") % 2 == 0, out


def test_rebalance_is_a_noop_on_balanced_text():
    assert mdsource.rebalance("**bold** and `code`") == "**bold** and `code`"


def test_strip_citations_removes_verdict_brackets_but_keeps_urls():
    assert "F8-2" not in mdsource.strip_citations("Works [verified F8-2, TRUE, n=240, 2026-08-10]")
    kept = mdsource.strip_citations("See <https://docs.aws.amazon.com/x.html>")
    assert "docs.aws.amazon.com" in kept


def test_the_two_v14_documents_are_table_parallel():
    """The whole two-deck design rests on this, so it is asserted, not assumed."""
    en = ROOT / "agentcore_guardrails_best_practices_v1.4.md"
    zh = ROOT / "agentcore_guardrails_best_practices_v1.4.zh-TW.md"
    if not (en.exists() and zh.exists()):
        pytest.skip("v1.4 documents not present in this tree")
    src = mdsource.Source(str(en), str(zh))  # raises SystemExit if they diverge
    assert len(src.tables["en"]) == len(src.tables["zh"]) >= 21


# -- renderer: needs python-pptx ------------------------------------------- #


@pytest.fixture(scope="module")
def render():
    return pytest.importorskip("deckgen.render", reason="python-pptx is not installed here")


def test_code_span_nested_in_bold_is_not_printed_literally(render):
    runs = render.inline_runs("**Pin `boto3` at 1.43.32**")
    assert not any("`" in r["t"] for r in runs), runs
    code = [r for r in runs if r["code"]]
    assert len(code) == 1 and code[0]["t"] == "boto3"
    assert all(r["bold"] for r in runs), "bold must survive the nested code span"


def test_plain_strips_markers_for_width_measurement(render):
    assert render.plain("**a** `b`") == "a b"


def test_font_children_are_written_in_schema_order(render):
    """latin → ea → cs. Any other order makes PowerPoint offer to repair the deck."""
    deck = render.Deck("zh", "t")
    sl = deck.bullets("標題", [(0, "中文與 `code` 混排")])
    seen = 0
    for shape in sl.shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                rPr = run._r.find(render.qn("a:rPr"))
                if rPr is None:
                    continue
                order = [c.tag.split("}")[-1] for c in rPr if c.tag.split("}")[-1] in ("latin", "ea", "cs")]
                if order:
                    seen += 1
                    assert order == ["latin", "ea", "cs"], order
    assert seen, "no styled runs were produced, so nothing was actually checked"


def test_chinese_runs_get_an_east_asian_typeface(render):
    deck = render.Deck("zh", "t")
    sl = deck.bullets("標題", [(0, "純中文一行")])
    faces = set()
    for shape in sl.shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                rPr = run._r.find(render.qn("a:rPr"))
                ea = None if rPr is None else rPr.find(render.qn("a:ea"))
                if ea is not None:
                    faces.add(ea.get("typeface"))
    assert faces and all(f for f in faces), faces
    assert "PingFang TC" in faces


def test_newline_becomes_a_break_element(render):
    """A raw \\n inside <a:t> is not a line break in DrawingML."""
    deck = render.Deck("en", "t")
    sl = deck.bullets("T", [(0, "line one\nline two")])
    brs = sum(len(shape.text_frame._txBody.findall(f".//{render.qn('a:br')}"))
              for shape in sl.shapes if shape.has_text_frame)
    assert brs >= 1


def test_a_long_edge_label_is_clamped_onto_the_slide(render):
    """The EN wording of a feedback edge is wider than the ZH one; it must not hang off."""
    deck = render.Deck("en", "t")
    sl = deck.diagram(
        "T",
        nodes={"a": {"x": 0.2, "y": 0.2, "w": 1.0, "h": 0.6, "text": "a"},
               "b": {"x": 10.5, "y": 0.2, "w": 1.0, "h": 0.6, "text": "b"}},
        edges=[{"a": "b", "b": "a", "side": "bb",
                "waypoint": [(11.4, 4.1), (1.1, 4.1)],
                "label": "re-tune as traffic and models change — AWS auto-updates the guardrail models"}],
    )
    for shape in sl.shapes:
        if shape.left is None:
            continue
        assert shape.left >= 0, (shape.left, getattr(shape, "text", ""))
        assert shape.left + shape.width <= render.Inches(render.SLIDE_W)


def test_bullet_overflow_is_reported_rather_than_silently_clipped(render):
    deck = render.Deck("en", "t")
    deck.bullets("T", [(0, "word " * 400)] * 6)
    assert deck.warnings, "an unfittable slide must warn; silence reads as 'it fits'"
    assert "overflow" in deck.warnings[0]
