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
    return {
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
                 boxes_shown: int | None, coloured: bool) -> str:
    """The closed loop, from the payload's own coordinates. `boxes_shown` truncates the reveal
    in document order (the builder emits boxes in layout order, top row first); `coloured=False`
    draws every border in the neutral slate so the colour scene can be the one that introduces
    colour rather than the fourth repetition of it."""
    v = cl["viewbox"]
    boxes = cl["boxes"] if boxes_shown is None else cl["boxes"][:boxes_shown]
    shown = {b["id"] for b in boxes}
    parts = []
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
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="3"{dash}/>'
                     f'<polygon points="{head}" fill="{col}"/>')
    for b in boxes:
        col = st.get(b["status"], palette["border-strong"]) if coloured else palette["border-strong"]
        dash = ' stroke-dasharray="8 6"' if coloured and b["status"] == "not_measured" else ""
        label = _t(b["label"], lang)
        parts.append(
            f'<rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" rx="8" '
            f'fill="{palette["bg-raised"]}" stroke="{col}" stroke-width="4"{dash}/>'
            f'<text x="{b["x"] + b["w"] / 2}" y="{b["y"] + b["h"] / 2 + 9}" fill="{palette["fg"]}" '
            f'font-family="{SANS}" font-size="26" font-weight="600" '
            f'text-anchor="middle">{label}</text>')
    return (f'<svg viewBox="{v["min_x"]} {v["min_y"]} {v["width"]} {v["height"]}" '
            f'width="1560" style="max-height:820px" xmlns="http://www.w3.org/2000/svg">'
            + "".join(parts) + "</svg>")


def scenes(payload: dict, lang: str) -> list[tuple[str, list[str]]]:
    """(scene id, [frame html, …]) in playback order — ids must equal the script's scene ids."""
    palette = css_vars()
    st = status_colours(palette)
    n = resolve(payload)
    pr = payload["practices"]
    cl = next(d for d in payload["architecture"]["diagrams"] if d["id"] == "closed_loop")
    z = lang == "zh"

    def phase_scene(phase: str, heading: str) -> str:
        rows = []
        for s in pr["sections"]:
            if s["phase"] != phase:
                continue
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
                + (f'右欄為各檢查點的實踐數;顏色即網站上的實測狀態。' if z else
                   f'The right column is each checkpoint&#8217;s practice count; '
                   f'the colour is the measured status the site shows.') + "</p>")

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
