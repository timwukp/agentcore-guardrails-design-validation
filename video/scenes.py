"""Scene builders for the explainer videos: payload in, HTML/SVG frames out.

WHAT A SCENE IS ALLOWED TO KNOW

Every number, label, status, coordinate and colour a frame shows comes from one of two places:

  * the PAYLOAD — the same JSON files the site serves. The closed-loop picture is drawn from
    `architecture.json`'s own derived geometry (the one `test_architecture_layout.py` proves
    crossing-free), not from a re-drawing of it; the verdict counts come from `census.json` and
    `denominators.json`; the phase tables from `practices.json`. A frame showing a number the
    payload does not hold is the video equivalent of `no_hardcoded_totals`, and
    `video/tests/test_scenes.py` holds it the strong way: scenes rendered from a SENTINEL payload
    must surface the sentinel values, which no hardcoded literal can survive.

  * the SITE'S OWN STYLESHEET — the palette and the status→colour mapping are PARSED out of
    `site/src/styles.css` (`:root` variables and the `.st-*` rules) rather than copied into
    constants here. Two files each declaring what `contested` looks like is two readers of one
    format; the video would keep rendering last year's amber after the site moved
    (`feedback_two_readers_one_format`).

Text layout is HTML/CSS inside the 1920×1080 page — a browser wraps and ellipsizes text, hand-placed
SVG `<text>` does not — and the diagram is an inline `<svg>` whose polylines and boxes are the
payload's coordinates verbatim, scaled by the CSS transform only. Chromium screenshots of this page
were measured byte-deterministic across launches on this machine (2026-09-15), which is what lets
`render.py --verify` demand identical sha256 from two full renders.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STYLES = REPO / "site" / "src" / "styles.css"

WIDTH, HEIGHT = 1920, 1080

# Latin first, then the Traditional Chinese family, same ordering and same reason as the site's
# `--sans`: a Simplified face renders 為/説 in the wrong tradition for a platform that says it is zh-TW.
SANS = "Helvetica, 'Helvetica Neue', 'PingFang TC', sans-serif"
MONO = "Menlo, 'PingFang TC', monospace"


def css_vars() -> dict[str, str]:
    """The `:root` custom properties of the site's stylesheet, by name (no leading `--`)."""
    text = STYLES.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\n\}", text, re.S)
    if not root:
        raise SystemExit(f"no :root block found in {STYLES}; the palette cannot be derived")
    out = dict(re.findall(r"--([\w-]+):\s*([^;]+);", root.group(1)))
    for needed in ("bg", "fg", "fg-dim", "accent", "v-true", "v-false", "v-inconclusive",
                   "v-recorded", "border-strong", "bg-raised", "warn", "seal"):
        if needed not in out:
            raise SystemExit(f"styles.css :root no longer declares --{needed}")
    return out


def status_colours(palette: dict[str, str]) -> dict[str, str]:
    """status token -> resolved hex, parsed from the `.st-*` rules' `--st: var(--x)` declarations."""
    text = STYLES.read_text(encoding="utf-8")
    pairs = re.findall(r"\.st-([\w]+)\s*\{[^}]*?--st:\s*var\(--([\w-]+)\)", text)
    if len(pairs) < 5:
        raise SystemExit(f"only {len(pairs)} .st-* rules with --st parsed from styles.css; "
                         f"the mapping shape has changed and this parser can no longer read it")
    return {status: palette[var] for status, var in pairs}


PHASES = ("BEFORE", "DURING", "AFTER")

# video name -> the phase its chapter is about. `overview` is the fourth video and covers all three.
CHAPTERS = {"before": "BEFORE", "during": "DURING", "after": "AFTER"}


def phase_sections(payload: dict, phase: str) -> list[dict]:
    return [s for s in payload["practices"]["sections"] if s["phase"] == phase]


def phase_cases(payload: dict, phase: str) -> dict[str, dict]:
    """The DISTINCT cases the phase's checkpoints cite, keyed by case id.

    Distinct, not summed: a case may be cited by two checkpoints inside one phase (F2-2 is, in
    BEFORE), so `sum(n_cases)` exceeds the number of cases that exist. A verdict mix drawn beside a
    total has to be over the same set as that total, or the four values add up past it and the frame
    is arithmetically wrong in a way no reader can check against anything.
    """
    out: dict[str, dict] = {}
    for s in phase_sections(payload, phase):
        for c in s["cases"]:
            out.setdefault(c["case"], c)
    return out


def resolve(payload: dict) -> dict[str, int]:
    """Every placeholder the narration and the frames may use — derived, one place."""
    mix = payload["census"]["verdict_mix"]
    den = payload["denominators"]
    pr = payload["practices"]
    cl = next(d for d in payload["architecture"]["diagrams"] if d["id"] == "closed_loop")
    by_phase_sections: dict[str, int] = {}
    by_phase_practices: dict[str, int] = {}
    for s in pr["sections"]:
        by_phase_sections[s["phase"]] = by_phase_sections.get(s["phase"], 0) + 1
        by_phase_practices[s["phase"]] = by_phase_practices.get(s["phase"], 0) + s["n_practices"]
    # The per-phase chapter numbers. Every one of them is derived from the same payload the overview
    # reads, and each is a SEPARATE derivation from a separate field: the practice split reads
    # `status_basis` on the practices list, the verdict mix reads the checkpoints' case lists, and the
    # two are not inferred from each other (`feedback_two_numbers_two_claims`).
    per_phase: dict[str, int] = {}
    non_colouring = set(pr["non_colouring_restrictions"])
    for phase in PHASES:
        p = phase.lower()
        cases = phase_cases(payload, phase)
        practices = [x for x in pr["practices"] if x["phase"] == phase]
        verdicts = [c["verdict"] for c in cases.values()]
        per_phase |= {
            f"{p}_cases": len(cases),
            f"{p}_true": verdicts.count("TRUE"),
            f"{p}_false": verdicts.count("FALSE"),
            f"{p}_inconclusive": verdicts.count("INCONCLUSIVE"),
            f"{p}_recorded": verdicts.count("RECORDED"),
            f"{p}_unpublished": sum(1 for v in verdicts if v is None),
            # Restrictions that colour nothing — the case was examined and still licenses no verdict
            # about the practice citing it. Read from the payload's own list rather than from a
            # literal set here: two files declaring which tokens are non-colouring is two readers of
            # one vocabulary, and the video is the reader nobody re-checks.
            f"{p}_restricted": sum(1 for c in cases.values()
                                   if set(c["restrictions"]) & non_colouring),
            f"{p}_own": sum(1 for x in practices if x["status_basis"] == "practice"),
            f"{p}_inherited": sum(1 for x in practices if x["status_basis"] == "section"),
        }
    return per_phase | {
        "n_registered": den["registered"]["n"],
        "n_published": den["published"]["n"],
        "v_true": mix.get("TRUE", 0),
        "v_false": mix.get("FALSE", 0),
        "v_inconclusive": mix.get("INCONCLUSIVE", 0),
        "v_recorded": mix.get("RECORDED", 0),
        "cl_boxes": len(cl["boxes"]),
        "cl_contested": cl["boxes_by_status"].get("contested", 0),
        "cl_vip": cl["boxes_by_status"].get("validated_in_part", 0),
        "cl_nm": cl["boxes_by_status"].get("not_measured", 0),
        "before_sections": by_phase_sections.get("BEFORE", 0),
        "before_practices": by_phase_practices.get("BEFORE", 0),
        "during_sections": by_phase_sections.get("DURING", 0),
        "during_practices": by_phase_practices.get("DURING", 0),
        "after_sections": by_phase_sections.get("AFTER", 0),
        "after_practices": by_phase_practices.get("AFTER", 0),
        "n_uncited": pr["coverage"]["n_uncited"],
        "adj_open": pr["adjudications"]["n_open"],
        "n_citations": pr["citation_census"]["n_citations"],
        "n_distinct": pr["citation_census"]["n_distinct"],
        "n_practices": pr["n_practices"],
    }


def _t(v, lang: str) -> str:
    """A payload value that may be authored `{en, zh}` or a bare (quoted-English) string."""
    if isinstance(v, dict):
        return v["zh" if lang == "zh" else "en"]
    return v


def _page(body: str, palette: dict[str, str]) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {WIDTH}px; height: {HEIGHT}px; background: {palette['bg']};
                    color: {palette['fg']}; font-family: {SANS}; overflow: hidden; }}
      .frame {{ width: 100%; height: 100%; padding: 96px 120px; display: flex;
                flex-direction: column; justify-content: center; }}
      h1 {{ font-size: 64px; font-weight: 700; line-height: 1.2; }}
      h2 {{ font-size: 44px; font-weight: 700; line-height: 1.25; margin-bottom: 40px; }}
      p  {{ font-size: 30px; line-height: 1.5; color: {palette['fg-dim']}; max-width: 1500px; }}
      .mono {{ font-family: {MONO}; }}
      .accent {{ color: {palette['accent']}; }}
      .big {{ font-family: {MONO}; font-size: 150px; line-height: 1; color: {palette['fg']}; }}
      .cap {{ font-size: 26px; color: {palette['fg-dim']}; margin-top: 12px; }}
      .row {{ display: flex; gap: 72px; align-items: baseline; }}
      .chip {{ display: inline-block; border: 2px solid {palette['border-strong']};
               border-radius: 8px; padding: 6px 18px; font-family: {MONO}; font-size: 24px;
               color: {palette['fg-dim']}; }}
    </style></head><body><div class="frame">{body}</div></body></html>"""


def _diagram_svg(cl: dict, palette: dict[str, str], st: dict[str, str], lang: str,
                 boxes_shown: int | None, coloured: bool,
                 highlight: set[str] | None = None) -> str:
    """The closed loop, from the payload's own coordinates. `boxes_shown` truncates the reveal
    in document order (the builder emits boxes in layout order, top row first); `coloured=False`
    draws every border in the neutral slate so the colour scene can be the one that introduces
    colour rather than the fourth repetition of it.

    `highlight` is the box-id set a phase chapter is about; the rest of the loop is drawn FADED
    rather than dropped, because a chapter that showed only its own three boxes would teach the loop
    as three disconnected pictures and lose the one property the design is named for.
    """
    v = cl["viewbox"]
    boxes = cl["boxes"] if boxes_shown is None else cl["boxes"][:boxes_shown]
    shown = {b["id"] for b in boxes}
    parts = []
    # The right edge every spine label ends at, derived from the CONNECTORS rather than from the boxes.
    # Leaning the labels left of the boxes fixed them overlapping each other and left a second defect
    # one step quieter: the feedback and gutter edges run down the same left margin (x = -38 and -68
    # here), so a 56-character label anchored 16 units left of the box ran its tail straight through
    # both of them, and one arrowhead landed inside the last word. Anchoring left of the LEFTMOST
    # gutter point clears every one of them at once, and it is computed from `cl["edges"]` — the whole
    # edge list, not the subset this frame draws, so a label does not move as the reveal adds boxes.
    # Every edge point, not the ones whose `route` this file thinks runs left: a route vocabulary is a
    # name list, and the property edges sit at x >= 200 so they cannot win a minimum anyway.
    gutter_x = min((x for e in cl["edges"] for x, _ in e["points"]), default=0)
    spine_label_right = min(0, gutter_x) - 16

    def fade(box_id: str) -> str:
        return "" if highlight is None or box_id in highlight else ' opacity="0.3"'

    for e in cl["edges"]:
        if e["from"] not in shown or e["to"] not in shown:
            continue
        pts = " ".join(f"{x},{y}" for x, y in e["points"])
        n = len(e["points"])
        (px, py), (x, y) = e["points"][n - 2], e["points"][n - 1]
        s = 7
        if x == px:
            d = 1 if y > py else -1
            head = f"{x},{y} {x - s},{y - s * d} {x + s},{y - s * d}"
        else:
            d = 1 if x > px else -1
            head = f"{x},{y} {x - s * d},{y - s} {x - s * d},{y + s}"
        col = palette["border-strong"] if e["route"] == "spine" else palette["seal"]
        dash = ' stroke-dasharray="6 5"' if e["route"] == "feedback" else ""
        # An edge is only in focus when BOTH its ends are: an arrow whose head lands in a faded box
        # reads as a relation into nothing, which is the same defect the reveal test already holds.
        dim = "" if highlight is None or {e["from"], e["to"]} <= highlight else ' opacity="0.3"'
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="3"{dash}'
                     f'{dim}/><polygon points="{head}" fill="{col}"{dim}/>')
    for b in boxes:
        col = st.get(b["status"], palette["border-strong"]) if coloured else palette["border-strong"]
        dash = ' stroke-dasharray="8 6"' if coloured and b["status"] == "not_measured" else ""
        label = _t(b["label"], lang)
        dim = fade(b["id"])
        # WHICH SIDE A LABEL LEANS TO, and why it is not centred.
        #
        # A box is 200 × 96 in a 590-wide viewbox and a label runs to 66 characters, so no legible
        # text fits INSIDE one — the site solves this by giving each box a wrapping HTML label at 1:1,
        # a frame 364 px wide cannot. Centring the text on the box was the first version and it
        # published a defect: a spine label grew right, its satellite's label grew left, and the two
        # overlapped into an unreadable smear on three of the six hops (seen on 2026-09-18 by looking
        # at the rendered PNG, which is the only thing that shows it — `feedback_chart_encoding_defects`;
        # the live overview video has it).
        #
        # So each label leans AWAY from the other column: the spine's to the left of the spine, the
        # satellites' to the right of the satellite. `satellite` is the payload's own derived flag —
        # the same one the site's `ArchDiagram` positions by, and the same one whose `kind`-based
        # predecessor `feedback_scope_as_namelist` already convicted — so a new satellite kind is
        # placed correctly without this file learning its name.
        if b.get("satellite"):
            anchor, tx = "start", b["x"] + b["w"] + 16
        else:
            anchor, tx = "end", spine_label_right
        parts.append(
            f'<rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" rx="8" '
            f'fill="{palette["bg-raised"]}" stroke="{col}" stroke-width="4"{dash}{dim}/>'
            f'<text x="{tx}" y="{b["y"] + b["h"] / 2 + 9}" fill="{palette["fg"]}" '
            f'font-family="{SANS}" font-size="26" font-weight="600" '
            f'text-anchor="{anchor}"{dim}>{label}</text>')
    return (f'<svg viewBox="{v["min_x"]} {v["min_y"]} {v["width"]} {v["height"]}" '
            f'width="1560" style="max-height:820px" xmlns="http://www.w3.org/2000/svg">'
            + "".join(parts) + "</svg>")


def _checkpoint_table(payload: dict, palette: dict[str, str], st: dict[str, str], lang: str,
                      phase: str, heading: str) -> str:
    """One phase's checkpoints as a table: status swatch, section number, the DOCUMENT's own heading,
    and that checkpoint's practice count. Shared by the overview's phase scene and by the chapter's,
    so the two cannot drift into showing a reader two different tables of the same three rows."""
    z = lang == "zh"
    rows = []
    for s in phase_sections(payload, phase):
        col = st.get(s["status"], palette["border-strong"])
        rows.append(
            f'<div style="display:flex;align-items:center;gap:28px;padding:18px 0;'
            f'border-bottom:1px solid {palette["border-strong"]}">'
            f'<span style="width:26px;height:26px;border:4px solid {col};border-radius:6px;'
            f'flex:none"></span>'
            f'<span class="mono" style="font-size:30px;flex:none">§{s["id"]}</span>'
            f'<span style="font-size:30px;flex:1">{_t(s["heading"], lang)}</span>'
            f'<span class="mono" style="font-size:26px;color:{palette["fg-dim"]}">'
            f'{s["n_practices"]}</span></div>')
    return (f"<h2>{heading}</h2>" + "".join(rows)
            + f'<p style="margin-top:36px" class="cap">'
            + ('右欄為各檢查點的實踐數;顏色即網站上的實測狀態。' if z else
               'The right column is each checkpoint&#8217;s practice count; '
               'the colour is the measured status the site shows.') + "</p>")


def _chapter(payload: dict, lang: str, phase: str) -> list[tuple[str, list[str]]]:
    """One phase chapter: where the phase sits in the loop, its checkpoints, the build's own reason
    for each colour, the evidence under it, and how much of it rests on a citation of its own.

    Nothing here paraphrases a practice. The chapter shows the checkpoint headings and the
    `why_this_status` sentences the BUILD derived, both quoted from the payload in the reader's own
    language, and otherwise talks about counts and about what a colour means — the same rule the
    overview narration follows, for the same reason: a paraphrase is a second wording whose only
    provenance is the wording.
    """
    palette = css_vars()
    st = status_colours(palette)
    n = resolve(payload)
    pr = payload["practices"]
    cl = next(d for d in payload["architecture"]["diagrams"] if d["id"] == "closed_loop")
    z = lang == "zh"
    p = phase.lower()
    secs = phase_sections(payload, phase)
    sec_ids = {s["id"] for s in secs}
    # The loop boxes this phase owns, resolved through each box's OWN `from_section` rather than
    # through a phase list written here: the diagram is where a box's checkpoint is declared, and a
    # second list would be the thing that keeps pointing at hop 5 after the document moves it.
    mine = {b["id"] for b in cl["boxes"] if b.get("from_section") in sec_ids}
    label = {"BEFORE": ("第一階段 — BEFORE:請求觸及模型之前",
                        "Phase one — BEFORE a request reaches a model"),
             "DURING": ("第二階段 — DURING:執行期間",
                        "Phase two — DURING execution"),
             "AFTER": ("第三階段 — AFTER:讓閉環閉合",
                       "Phase three — AFTER: closing the loop")}[phase]
    head = label[0] if z else label[1]

    def status_frame(s: dict) -> str:
        col = st.get(s["status"], palette["border-strong"])
        means = _t(pr["status_labels"].get(s["status"], {"en": "", "zh": ""}), lang)
        return _page(
            f'<h2><span class="mono">§{s["id"]}</span> {_t(s["heading"], lang)}</h2>'
            f'<div style="display:flex;align-items:center;gap:24px;margin-top:-16px">'
            f'<span style="width:30px;height:30px;border:5px solid {col};border-radius:7px;'
            f'flex:none"></span>'
            f'<span class="mono" style="font-size:34px;color:{col}">'
            f'{s["status"].replace("_", " ")}</span>'
            f'<span style="font-size:28px;color:{palette["fg-dim"]}">{means}</span></div>'
            f'<p style="margin-top:44px">{_t(s["why_this_status"], lang)}</p>'
            f'<p class="cap" style="margin-top:28px">'
            + ('這段理由由建置推導,原文引用於此——不是為這支影片重寫的。' if z else
               'That reason is derived by the build and quoted here verbatim — '
               'not rewritten for this video.') + "</p>", palette)

    def count_row(name: str, colour: str, count: int, note: str) -> str:
        return (f'<div style="display:flex;align-items:baseline;gap:36px;padding:14px 0">'
                f'<span class="mono" style="font-size:36px;color:{colour};width:340px">{name}</span>'
                # A fixed column, right-aligned: with the number sizing its own box, a two-digit row
                # shunts its caption further right than a one-digit row and the six captions come out
                # on six different left edges. The numbers are what a viewer compares, so they line up.
                f'<span class="mono" style="font-size:48px;width:110px;text-align:right">'
                f'{count}</span>'
                f'<span style="font-size:26px;color:{palette["fg-dim"]}">{note}</span></div>')

    return [
        ("title", [_page(
            f'<h1>{head}</h1>'
            f'<div class="row" style="margin-top:40px">'
            f'<div><div class="big">{n[f"{p}_sections"]}</div>'
            f'<div class="cap">{"個檢查點" if z else "checkpoints"}</div></div>'
            f'<div><div class="big">{n[f"{p}_practices"]}</div>'
            f'<div class="cap">{"條編號實踐" if z else "numbered practices"}</div></div>'
            f'<div><div class="big">{n[f"{p}_cases"]}</div>'
            f'<div class="cap">{"個被引用的案例" if z else "cases they cite"}</div></div></div>'
            f'<div style="margin-top:48px"><span class="chip">'
            f'{"合成語音旁白 · Amazon Polly" if z else "Synthesized narration · Amazon Polly"}'
            f'</span></div>', palette)]),
        ("where", [_page(
            f'<h2>{"這一段在閉環的哪裡" if z else "Where this phase sits in the loop"}</h2>'
            f'<div style="display:flex;justify-content:center">'
            + _diagram_svg(cl, palette, st, lang, None, coloured=True, highlight=mine)
            + "</div>"
            # Each highlighted box with the KIND the payload declares it — `checkpoint`, `property`,
            # `stage`, `alternative`. The distinction matters (a property is not a gate a request
            # passes through) and the narration names it, so it is shown from the payload rather than
            # left to a viewer to infer from where the box was drawn.
            f'<div style="display:flex;gap:24px;justify-content:center;margin-top:8px">'
            + "".join(f'<span class="chip">§{b["from_section"]} {b["kind"]}</span>'
                      for b in cl["boxes"] if b["id"] in mine)
            + "</div>"
            f'<p class="cap" style="text-align:center">'
            + ('淡出的部分屬於其他階段:閉環照原樣畫出,因為只畫三個方框會把它教成三張互不相連的圖。'
               if z else
               'The faded boxes belong to the other phases. The loop is drawn whole on purpose — '
               'three boxes alone would teach it as three disconnected pictures.')
            + "</p>", palette)]),
        ("checkpoints", [_checkpoint_table(payload, palette, st, lang, phase, head)]),
        ("status", [status_frame(s) for s in secs]),
        ("evidence", [_page(
            f'<h2>{"這一段底下的證據" if z else "The evidence under this phase"}</h2>'
            + count_row("TRUE", palette["v-true"], n[f"{p}_true"],
                        "觀察到文件所述行為" if z else "the documented behaviour was observed")
            + count_row("FALSE", palette["v-false"], n[f"{p}_false"],
                        "「發現」——不是失敗" if z else "a finding — never a failure")
            + count_row("INCONCLUSIVE", palette["v-inconclusive"], n[f"{p}_inconclusive"],
                        "一種結果,不是缺失" if z else "a result, not a missing one")
            + count_row("RECORDED", palette["v-recorded"], n[f"{p}_recorded"],
                        "純紀錄" if z else "recorded observations")
            + count_row("no verdict", palette["warn"], n[f"{p}_unpublished"],
                        "被引用,但沒有已發佈的判定" if z else "cited, with no published verdict")
            + count_row("restricted", palette["seal"], n[f"{p}_restricted"],
                        "檢驗過,但不為任何實踐上色" if z else
                        "examined, and colours no practice")
            + f'<p class="cap" style="margin-top:24px">'
            + (f'以上是這 {n[f"{p}_cases"]} 個「不重複」案例的分佈:被兩個檢查點引用的案例只算一次,'
               f'否則四個值會加總超過它旁邊的總數。' if z else
               f'Over the {n[f"{p}_cases"]} DISTINCT cases these checkpoints cite — a case cited by '
               f'two checkpoints is counted once, or the values would add up past the total beside '
               f'them.') + "</p>", palette)]),
        ("basis", [_page(
            f'<h2>{"每一句話靠的是什麼" if z else "What each sentence rests on"}</h2>'
            f'<div class="row" style="margin-top:24px">'
            f'<div><div class="big">{n[f"{p}_own"]}</div>'
            f'<div class="cap">{"帶著自己的引用" if z else "carry a citation of their own"}</div></div>'
            f'<div><div class="big">{n[f"{p}_inherited"]}</div>'
            f'<div class="cap">{"繼承所屬檢查點的證據" if z else
                                "inherit their checkpoint&#8217;s evidence"}</div></div></div>'
            f'<p style="margin-top:52px">'
            + ('這兩個數字刻意分開:繼承來的顏色,說的是「這個元件有發現」,不是「這一句話被測過」。'
               '網站在每張卡片上直說它是哪一種。' if z else
               'The two numbers are kept apart on purpose. An inherited colour says this COMPONENT '
               'has a finding, not that this SENTENCE was tested; the site says which one each card '
               'is, on the card.') + "</p>", palette)]),
        ("verify", [_page(
            f'<h2>{"請自行驗證這一段" if z else "Verify this phase yourself"}</h2>'
            f'<p><span class="mono accent">/design#s-{secs[0]["id"]}</span> — '
            + (f'每張卡片都帶著文件自己的句子、實測狀態、建置推導的理由,以及可點進去的案例。'
               if z else
               f'every card carries the document&#8217;s own sentence, its measured status, the '
               f'build&#8217;s derived reason, and the cases themselves.') + "</p>"
            f'<div style="margin-top:56px"><span class="chip">'
            f'{"旁白:Amazon Polly 合成 — 英文 Ruth(generative)· 中文 Zhiyu(neural, cmn-CN;Polly 沒有 zh-TW 語音)" if z else "Narration: synthesized with Amazon Polly — Ruth (generative) for English · Zhiyu (neural, cmn-CN; Polly ships no zh-TW voice) for Chinese"}'
            f'</span></div>', palette)]),
    ]


def scenes(payload: dict, lang: str, video: str = "overview") -> list[tuple[str, list[str]]]:
    """(scene id, [frame html, …]) in playback order — ids must equal the script's scene ids.

    Dispatches on the video name, which is the script's stem, so `video/script/*.yaml` remains the
    one place the set of videos is declared: a script with no builder fails loudly here rather than
    rendering an empty chapter."""
    if video in CHAPTERS:
        return _chapter(payload, lang, CHAPTERS[video])
    if video != "overview":
        raise SystemExit(f"no scene builder for video {video!r}; known: overview, "
                         f"{', '.join(sorted(CHAPTERS))}")
    palette = css_vars()
    st = status_colours(palette)
    n = resolve(payload)
    cl = next(d for d in payload["architecture"]["diagrams"] if d["id"] == "closed_loop")
    z = lang == "zh"

    def phase_scene(phase: str, heading: str) -> str:
        return _checkpoint_table(payload, palette, st, lang, phase, heading)

    reveal_rows = sorted({b["y"] for b in cl["boxes"]})
    reveal_steps = [sum(1 for b in cl["boxes"] if b["y"] <= y) for y in reveal_rows]

    return [
        ("title", [_page(
            f'<h1>{"實測過的建議設計" if z else "The recommended design, measured"}</h1>'
            f'<p style="margin-top:28px">{"Amazon Bedrock AgentCore guardrails — 端到端閉環設計,每一條實踐都掛鉤到測過它的案例。" if z else "Amazon Bedrock AgentCore guardrails — an end-to-end closed-loop design, every practice hooked to the case that tested it."}</p>'
            f'<div style="margin-top:56px"><span class="chip">'
            f'{"合成語音旁白 · Amazon Polly" if z else "Synthesized narration · Amazon Polly"}'
            f'</span></div>', palette)]),
        ("claim", [_page(
            f'<h2>{"斷言之前,先有登錄冊" if z else "A register before an assertion"}</h2>'
            f'<div class="row"><div><div class="big">{n["n_registered"]}</div>'
            f'<div class="cap">{"預先登錄的測試案例" if z else "pre-registered test cases"}</div></div>'
            f'<div><div class="big">{n["n_published"]}</div>'
            f'<div class="cap">{"已發佈判定" if z else "published verdicts"}</div></div></div>'
            f'<p style="margin-top:56px">{"每一個判定都帶著證據、密封的 oracle,以及引用限制。" if z else "Each verdict carries its evidence, its sealed oracle, and its citation restrictions."}</p>',
            palette)]),
        ("verdicts", [_page(
            f'<h2>{"四個值,沒有通過率" if z else "Four values, no pass rate"}</h2>'
            + "".join(
                f'<div style="display:flex;align-items:baseline;gap:36px;padding:20px 0">'
                f'<span class="mono" style="font-size:40px;color:{colour};width:340px">{name}</span>'
                f'<span class="mono" style="font-size:56px">{count}</span>'
                f'<span style="font-size:28px;color:{palette["fg-dim"]}">{note}</span></div>'
                for name, colour, count, note in [
                    ("TRUE", palette["v-true"], n["v_true"],
                     "觀察到文件所述行為" if z else "the documented behaviour was observed"),
                    ("FALSE", palette["v-false"], n["v_false"],
                     "「發現」——不是失敗" if z else "a finding — never a failure"),
                    ("INCONCLUSIVE", palette["v-inconclusive"], n["v_inconclusive"],
                     "一種結果,不是缺失" if z else "a result, not a missing one"),
                    ("RECORDED", palette["v-recorded"], n["v_recorded"],
                     "純紀錄" if z else "recorded observations"),
                ]), palette)]),
        ("loop", [_page(
            f'<h2>{"閉環——文件 §2.1,由已證明的版面繪出" if z else "The closed loop — document §2.1, drawn from the proven layout"}</h2>'
            f'<div style="display:flex;justify-content:center">'
            + _diagram_svg(cl, palette, st, lang, k, coloured=False)
            + "</div>", palette) for k in reveal_steps]),
        ("colours", [_page(
            f'<h2>{"顏色是推導的:一個 FALSE 壓過任何數量的 TRUE" if z else "Colour is derived: one FALSE outranks any number of TRUEs"}</h2>'
            f'<div style="display:flex;justify-content:center">'
            + _diagram_svg(cl, palette, st, lang, None, coloured=True)
            + "</div>"
            f'<div style="display:flex;gap:56px;justify-content:center;margin-top:24px">'
            + "".join(
                f'<span style="font-size:26px;color:{palette["fg-dim"]}">'
                f'<span style="display:inline-block;width:22px;height:22px;border:4px solid {col};'
                f'border-radius:5px;vertical-align:-4px;margin-right:12px'
                f'{";border-style:dashed" if status == "not_measured" else ""}"></span>'
                f'<span class="mono">{status.replace("_", " ")}</span> · {count}</span>'
                for status, col, count in [
                    ("contested", st["contested"], n["cl_contested"]),
                    ("validated_in_part", st["validated_in_part"], n["cl_vip"]),
                    ("not_measured", st["not_measured"], n["cl_nm"]),
                ]) + "</div>", palette)]),
        ("before", [_page(phase_scene(
            "BEFORE", ("第一階段 — BEFORE:請求觸及模型之前" if z
                       else "Phase one — BEFORE a request reaches a model")), palette)]),
        ("during", [_page(phase_scene(
            "DURING", ("第二階段 — DURING:執行期間" if z
                       else "Phase two — DURING execution")), palette)]),
        ("after", [_page(phase_scene(
            "AFTER", ("第三階段 — AFTER:讓閉環閉合" if z
                      else "Phase three — AFTER: closing the loop")), palette)]),
        ("honesty", [_page(
            f'<h2>{"刻意不主張的部分" if z else "What is deliberately not claimed"}</h2>'
            f'<div class="row" style="margin-top:20px">'
            f'<div><div class="big">{n["n_uncited"]}</div>'
            f'<div class="cap">{"測過了,而文件隻字未提" if z else "measured; the document says nothing"}</div></div>'
            f'<div><div class="big">{n["adj_open"]}</div>'
            f'<div class="cap">{"引用裁決仍懸而未決" if z else "citation rulings still open"}</div></div></div>'
            f'<p style="margin-top:56px">{"缺口和確認,用同樣的規格發佈。" if z else "The gaps are published with the same care as the confirmations."}</p>',
            palette)]),
        ("verify", [_page(
            f'<h2>{"請自行驗證" if z else "Verify it yourself"}</h2>'
            f'<p><span class="mono accent">/design</span> — '
            f'{f"{n['n_citations']} 條引用 · {n['n_distinct']} 個不同案例 · 每個數字都在建置時推導" if z else f"{n['n_citations']} citations · {n['n_distinct']} distinct cases · every count derived at build time"}</p>'
            f'<div style="margin-top:64px"><span class="chip">'
            f'{"旁白:Amazon Polly 合成 — 英文 Ruth(generative)· 中文 Zhiyu(neural, cmn-CN;Polly 沒有 zh-TW 語音)" if z else "Narration: synthesized with Amazon Polly — Ruth (generative) for English · Zhiyu (neural, cmn-CN; Polly ships no zh-TW voice) for Chinese"}'
            f'</span></div>', palette)]),
    ]
