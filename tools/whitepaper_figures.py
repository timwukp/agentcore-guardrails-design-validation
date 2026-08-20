#!/usr/bin/env python3
"""Generate the whitepaper's figures from the evidence tree. Nothing here is hand-drawn.

Why this file exists
--------------------
`WHITEPAPER-DESIGN.md` §5 ends with a rule: *every figure must be generated from the evidence tree by
a script in the repo, never hand-drawn, so that Appendix G's reproduction claim is true. Any figure
whose numbers cannot be regenerated does not ship.* This is that script. A figure that reproduces a
number the evidence does not contain is worse than a missing figure, because a chart reads as measured
whether or not it is.

What `--check` compares, and what it deliberately does not
---------------------------------------------------------
`--check` re-derives every figure's NUMBERS and compares them to `results/figures/MANIFEST.json`. It
does **not** compare PNG bytes. Rendered bytes move with matplotlib, freetype and libpng versions, so
a byte comparison would red on a dependency bump while the measurements were untouched — the same
defect class as a formatter version showing up as a diff. The numbers are the claim; the pixels are a
rendering of it.

Environment
-----------
Run under `.venv-figs`, not `.venv-oracle`:

    ./.venv-figs/bin/python tools/whitepaper_figures.py

`.venv-oracle` is the interpreter the seals are verified in and it deliberately has no plotting
dependency, so that installing one cannot perturb the environment a verdict was computed in. Both
venvs are excluded from `check_redaction.py` by prefix.

Why the outputs are safe to distribute
--------------------------------------
Every number and label drawn here is read from `results/`, which is the distributable tree and passes
`check_redaction.py`. No figure reads `evidence/`. So a label cannot carry an unredacted account id,
ARN or bucket name unless one had already survived the gate in its source file.

Figure 6 is BLOCKED and says so
-------------------------------
The control x threat matrix needs all seventeen OWASP Agentic threat titles from the pinned v1.1 PDF.
Five are grounded in this project's notes (T1, T3, T9, T15, T16); twelve are not. Rendering twelve
columns from memory is fabrication, and rendering them as an empty state would misreport a
sourcing gap as a coverage finding. So the manifest records figure 6 as blocked, with the reason, and
no PNG is written. That is the same rule the paper applies to Appendix D.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402
matplotlib.use("Agg")  # no display in this environment, and determinism matters more than interactivity
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

import whitepaper_data  # noqa: E402  sibling in tools/; ROOT is on the path

sys.path.insert(0, str(ROOT / "lib"))
from redact import mask_text  # noqa: E402  the choke point every results/ write goes through

PHASE1 = ROOT / "results" / "phase1"
FIGDIR = ROOT / "results" / "figures"
MANIFEST = FIGDIR / "MANIFEST.json"

# --- palette -------------------------------------------------------------------------------------
# INCONCLUSIVE is drawn in a neutral grey with a hatch, never in a red or a warning colour. The
# paper's own rule is that an INCONCLUSIVE verdict is not a weaker FALSE, and a figure that colours
# it like a failure teaches the opposite of the text next to it. Hatching carries the distinction as
# well as hue so that the three states remain separable without colour.
VERDICT_STYLE = {
    "TRUE":         {"color": "#2b7a4b", "hatch": None},
    "FALSE":        {"color": "#a8322d", "hatch": None},
    "INCONCLUSIVE": {"color": "#9a9a9a", "hatch": "//"},
    "RECORDED":     {"color": "#3a6ea5", "hatch": ".."},
}
ORDER = ("TRUE", "FALSE", "INCONCLUSIVE", "RECORDED")


def load(name: str) -> dict:
    p = PHASE1 / name
    if not p.exists():
        raise SystemExit(f"missing evidence file: {p.relative_to(ROOT)}")
    return json.loads(p.read_text(encoding="utf-8"))


def dig(d: dict, path: str):
    """Fetch a dotted path, and name the path in the error when it is absent.

    A KeyError here means the verdict-file shape moved. Saying which path was wanted is the
    difference between a five-minute fix and re-deriving the schema.
    """
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise SystemExit(f"figure data path absent: {path!r} (stopped at {part!r})")
        cur = cur[part]
    return cur


TITLE_PT = 10.0
_LINE_IN = 0.20          # rendered height of one TITLE_PT line, plus leading
_CHAR_IN = 0.0685        # mean advance width of one TITLE_PT character in this font
_TITLE_MAX_FRAC = 0.34   # the most of a canvas's height a title may claim before headline() refuses
_PER_LINE_FLOOR = 24     # the narrowest wrap headline() will try before it refuses on width


def headline(fig, text: str) -> int:
    """Set the figure title against the LEFT EDGE OF THE CANVAS, wrapped to the canvas width.

    `ax.set_title(..., loc="left")` anchors at the axes, and the axes' left edge sits wherever the
    longest y tick label pushes it — on figure 3 that is 40% of the way across the canvas, so the
    title ran off the right edge and matplotlib cropped it silently. Two of the seven figures
    shipped a truncated sentence on their first render for exactly this reason. Anchoring on the
    figure and wrapping to the figure's width makes the room available to a title independent of the
    tick labels, so a longer y label can no longer eat a title.

    Explicit line breaks in `text` are preserved; each resulting line is wrapped independently.
    Returns the number of rendered lines, which `finish` needs in order to reserve the top strip.

    `_CHAR_IN` is a MEAN advance width, so the character budget it yields is an estimate, and on
    2026-08-20 figure 3's rewritten title overran it: the wrap put 123 characters on a line the canvas
    fits about 112 of, and matplotlib cropped the remainder mid-word — "…and th" followed by the next
    line, with "e arrow" simply gone. Nothing failed. That is the same silent-crop failure this
    function was written to end, one level down: the anchor was fixed and the WIDTH was still guessed.
    So the estimate is now only a starting point. The rendered extent is measured and the wrap
    tightened until it fits.

    **Both ways of not fitting are refused, because the first fix only closed one of them.** Writing
    the width check produced a `SystemExit` that could not fire and a silent failure in the other
    axis, and a test written for that raise is what found them:

    * `textwrap.fill` breaks long words by default, so narrowing `per_line` fits ANY text eventually —
      a 200-character unbreakable token wrapped to six lines and returned normally. The documented
      "a title that cannot be made to fit raises" was unreachable code (`feedback_unreachable_branch_in_fake`).
      A narrow canvas made it worse than unreachable: `per_line` started at its 40 floor, went negative
      after ten iterations, and `textwrap.fill(width=-12)` raises `ValueError` — a traceback in place
      of the message written to explain the problem.
    * `max(0.45, 1.0 - reserved)` meant a title that fit only by growing tall silently ate the axes
      down to 45% of the canvas. Measuring the width and then clamping the height is half a fix; the
      clamp is where the next cropped figure would have hidden.

    So a title must fit BOTH bounds — the canvas width after re-wrapping, and `_TITLE_MAX_FRAC` of the
    canvas height — and failing either raises with which one failed. There is no clamp left to absorb
    an oversized title, which is the point: the fix for a title too big for its figure is to shorten
    it or widen the figure, and only a human can choose.
    """
    per_line = max(40, int(fig.get_figwidth() / _CHAR_IN))
    limit = fig.get_window_extent().x1 - 3          # device px; 3 px of right-hand air
    while True:
        wrapped = "\n".join(textwrap.fill(line, per_line) for line in text.split("\n"))
        n_lines = wrapped.count("\n") + 1
        reserved = (n_lines * _LINE_IN + 0.14) / fig.get_figheight()
        artist = fig.text(0.008, 1.0 - 0.02 / fig.get_figheight(), wrapped,
                          fontsize=TITLE_PT, ha="left", va="top")
        overrun = artist.get_window_extent(fig.canvas.get_renderer()).x1 - limit
        if overrun <= 0 and reserved <= _TITLE_MAX_FRAC:
            fig._wp_top = 1.0 - reserved
            return n_lines
        artist.remove()
        if overrun > 0 and per_line > _PER_LINE_FLOOR:
            per_line -= 4
            continue
        why = (f"it is {overrun:.0f} device px too wide at the narrowest wrap this function will "
               f"try ({_PER_LINE_FLOOR} characters)" if overrun > 0 else
               f"wrapping it to {n_lines} lines would claim {reserved:.0%} of the "
               f"{fig.get_figheight()}in canvas height, over the {_TITLE_MAX_FRAC:.0%} a title may "
               f"take, and squashing the axes to fit is how a figure gets published unreadable")
        raise SystemExit(
            f"the title does not fit the {fig.get_figwidth()}x{fig.get_figheight()}in canvas: {why}. "
            f"Cropping or squashing it silently is what this function exists to prevent, so shorten "
            f"it or widen the figure:\n  {text!r}")


def footer(ax, sources: list[str]) -> None:
    ax.figure.text(0.006, 0.012, "generated by tools/whitepaper_figures.py from " + ", ".join(sources),
                   fontsize=5.2, color="#666666", ha="left", va="bottom")


# Does `finish()` put bytes on disk? False under `--check`, and the reason is not tidiness.
#
# `--check` calls `build()`, which calls every `figNN()`, which called `finish()`, which called
# `savefig` unconditionally — so the read-only freshness check OVERWROTE all seven PNGs it was
# checking, and then reported STALE about the manifest describing the files it had just replaced.
# Two consequences, both measured on 2026-08-20:
#
#   1. There is no state in which a PNG on disk can be found to disagree with the manifest, because
#      the act of looking rewrites it. `--check` can detect a stale MANIFEST and never a stale
#      figure, and its help text ("re-derive the numbers") did not say so.
#   2. It corrupts other measurements. The full suite's concurrent-writer detector reported
#      `7 change(s) under results/ ... made by ANOTHER PROCESS` and declared its own tree-diff
#      channel VOID for the session — a `--check` run in a neighbouring shell cost a 1 h 28 m test
#      run half its coverage.
#
# The figures are still RENDERED under `--check`, into a discarded buffer, because that is real
# coverage worth keeping: a NaN axis or an empty series raises in `savefig`, and dropping the draw
# entirely would trade one silent gap for another.
WRITE_PNGS = True


def finish(fig, out: str) -> None:
    """Save with a reserved footer strip instead of `bbox_inches="tight"`.

    `tight` sizes the canvas to the artists, which pulls the provenance footer up until it collides
    with the x-axis label — measured on the first render of figure 3, where the two overlapped
    outright. Reserving the bottom 6% and laying out into the remainder puts the footer somewhere
    deterministic on every figure, at the cost of a little whitespace.
    """
    bottom = (0.18 + 0.04) / fig.get_figheight()   # provenance footer strip
    fig.tight_layout(rect=(0, bottom, 1, getattr(fig, "_wp_top", 1.0)))
    if WRITE_PNGS:
        FIGDIR.mkdir(parents=True, exist_ok=True)
        fig.savefig(FIGDIR / out, dpi=200)
    else:
        fig.savefig(io.BytesIO(), format="png", dpi=200)  # rendered, then dropped: see WRITE_PNGS
    plt.close(fig)


# --- figure 1 ------------------------------------------------------------------------------------

def fig01(D: dict) -> dict:
    mix = D["totals"]["verdict_mix"]
    counts = [mix[v] for v in ORDER]
    total = sum(counts)

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    for i, v in enumerate(ORDER):
        s = VERDICT_STYLE[v]
        ax.barh(i, mix[v], color=s["color"], hatch=s["hatch"], edgecolor="white", height=0.62)
        ax.text(mix[v] + 0.6, i, f"{mix[v]}  ({mix[v]/total:.0%})", va="center", fontsize=9)
    ax.set_yticks(range(len(ORDER)))
    ax.set_yticklabels(ORDER, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(counts) * 1.22)
    ax.set_xlabel("published verdicts", fontsize=9)
    headline(fig,f"Figure 1 — Verdict distribution over {total} published verdicts\n"
                 "INCONCLUSIVE is hatched grey: it is not a weaker FALSE, and licenses no amendment",
                 )
    ax.spines[["top", "right"]].set_visible(False)
    footer(ax, ["claims/triage_rules.py (sealed)", "results/phase1/*.json"])
    finish(fig, "fig-01-verdict-distribution.png")
    return {"verdict_mix": mix, "total": total}


# --- figure 2 ------------------------------------------------------------------------------------

def fig02(D: dict, top: int = 14) -> dict:
    secs = [s for s in D["sections"] if s["mix"]][:top]
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    labels = []
    for i, s in enumerate(secs):
        left = 0
        for v in ORDER:
            n = s["mix"].get(v, 0)
            if not n:
                continue
            st = VERDICT_STYLE[v]
            ax.barh(i, n, left=left, color=st["color"], hatch=st["hatch"],
                    edgecolor="white", height=0.66)
            left += n
        labels.append(f"{s['anchor']}  ({s['claims']} claims)")
    ax.set_yticks(range(len(secs)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("verdict outcomes, counted claim x case", fontsize=9)
    headline(fig,"Figure 2 — Evidence strength by section of the document under test\n"
                 "s5-1 and s4-5-5 are predominantly INCONCLUSIVE: weakly evidenced, not refuted",
                 )
    ax.spines[["top", "right"]].set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=VERDICT_STYLE[v]["color"],
                             hatch=VERDICT_STYLE[v]["hatch"]) for v in ORDER]
    ax.legend(handles, ORDER, fontsize=8, ncol=4, loc="lower right", frameon=False)
    footer(ax, ["claims/triage.csv (sealed)", "results/phase1/*.json"])
    finish(fig, "fig-02-evidence-by-section.png")
    return {"sections": [{"anchor": s["anchor"], "claims": s["claims"], "mix": s["mix"]}
                         for s in secs]}


# --- figure 3 ------------------------------------------------------------------------------------

F6_BANDS = {  # short y labels: a long label pushes the axes right and steals plot width
    "F6-1": "gateway guardrail",
    "F6-2": "Bedrock input guardrail",
    "F6-3": "Cedar policy evaluation",
    "F6-5": "Bedrock output guardrail",
    "F6-6": "end-to-end total",
}


def _quantiles(d: dict) -> dict:
    """p50/p90/p99 for a latency case, taken from `record.evidence`.

    `record.evidence` is used rather than the richer sibling blocks (`guardrail_hop_ms`,
    `arms.*.authz_ms`, `distribution`, `client_total`) for one reason: it is the block the sealed
    oracle actually judged. Every case carries several plausible latency distributions — F6-1's file
    alone holds five — and picking a different one per case is how a figure ends up disagreeing with
    the verdict printed next to it. Which sibling fed `record.evidence` varies by case and is
    recorded in each case's own file; the figure does not need to know.
    """
    ev = dig(d, "record.evidence")
    if "p50" not in ev:
        raise SystemExit(f"{d.get('case_id')}: record.evidence carries no p50")
    return {"block": "record.evidence", "p50": ev["p50"], "p90": ev.get("p90"),
            "p99": ev.get("p99"), "ci_p50": ev.get("ci_p50"), "n": ev.get("n")}


FIG03_CASES = ("F6-1", "F6-2", "F6-3", "F6-5", "F6-6")


def _f6_day_dates() -> dict[str, str]:
    """`{"day1": "2026-08-10", "day2": "2026-08-19"}`, read off the F6 archive filenames.

    The archive filenames are the ONLY day stamps this study has for F6. Both days' verdict files
    carry `run_id: r20260810T130945Z` and neither carries a `t_start_utc`, so nothing inside a file
    distinguishes them — a defect filed 2026-08-20, and the reason this helper reads names instead of
    contents. Each day label must resolve to exactly one date across the family, so a second date
    appearing under one label fails here rather than mislabelling a row.
    """
    dates: dict[str, set[str]] = {}
    for path in sorted((PHASE1 / "archive").glob("F6-*__day*.json")):
        stem = path.name.split("__", 1)[1][: -len(".json")]      # "day2_indecisive_2026-08-19"
        dates.setdefault(stem.split("_", 1)[0], set()).add(stem.rsplit("_", 1)[-1])
    conflicting = {d: sorted(v) for d, v in dates.items() if len(v) != 1}
    if conflicting:
        raise SystemExit(f"an F6 day label maps to more than one date: {conflicting}")
    return {day: v.pop() for day, v in dates.items()}


def _f6_days(cid: str, family_dates: dict[str, str]) -> list[dict]:
    """Every calendar day this case was measured on, and which one is the verdict of record.

    Figure 3 draws BOTH days per row — decided 2026-08-20 — because the alternative was a row set
    that silently mixed them. F6-1/F6-3/F6-6 replicated on 2026-08-19 and their live verdict files
    hold day 2; F6-2/F6-5 *disagreed* on replication, so `results/phase1/` deliberately keeps day 1
    as the verdict of record (`results/FINDING-F6-DAY2-DECISIVENESS.md`). Drawn identically, five
    rows in one figure showed two instruments as one, across a difference that same finding measures
    at 8.7-38.3%.

    Which day is the record is **derived, never listed**: the record is whichever day carries the
    same `record.evidence` quantiles as the live `results/phase1/<cid>.json`. Exactly one may, and
    the assertion is the point — a hand-kept list of which cases were re-pinned goes stale in
    silence, whereas re-pinning F6-2 to day 2 must move the label on this figure without anyone
    remembering that it should.

    A case whose live file matches no ARCHIVED day is itself an unarchived day: the agreeing cases
    were re-pinned to day 2 and no `__day2_` copy was written for them, because the live file already
    was it. That day is identified as the family day label this case has no archive for, and it must
    resolve to exactly one — inferring "the other day" is only sound while there are two.
    """
    live_q = _quantiles(load(f"{cid}.json"))
    days = []
    for path in sorted((PHASE1 / "archive").glob(f"{cid}__day*.json")):
        stem = path.name.split("__", 1)[1][: -len(".json")]
        label, date = stem.split("_", 1)[0], stem.rsplit("_", 1)[-1]
        middle = stem.split("_", 1)[1].rsplit("_", 1)[0] if stem.count("_") > 1 else None
        d = json.loads(path.read_text(encoding="utf-8"))
        q = _quantiles(d)
        days.append({"day": label, "date": date, "archived_as": middle,
                     "source": str(path.relative_to(ROOT)), "verdict": d["verdict"],
                     "quantiles": q, "is_record": q == live_q})

    if not any(day["is_record"] for day in days):
        unarchived = sorted(set(family_dates) - {day["day"] for day in days})
        if len(unarchived) != 1:
            raise SystemExit(
                f"{cid}: the live verdict file matches no archived day, and {len(unarchived)} day "
                f"label(s) {unarchived} have no archive for this case — which day the live file "
                f"holds cannot be derived. Archive it under its own day before drawing figure 3.")
        live = load(f"{cid}.json")
        days.append({"day": unarchived[0], "date": family_dates[unarchived[0]],
                     "archived_as": None, "source": f"results/phase1/{cid}.json",
                     "verdict": live["verdict"], "quantiles": live_q, "is_record": True})

    records = [day["day"] for day in days if day["is_record"]]
    if len(records) != 1:
        raise SystemExit(
            f"{cid}: {len(records)} day(s) {records} carry the live file's quantiles. Exactly one "
            f"must, or the figure cannot say which day is the verdict of record.")
    return sorted(days, key=lambda day: day["day"])


def fig03() -> dict:
    family_dates = _f6_day_dates()
    rows, data = [], {"day_dates": family_dates}
    for cid in FIG03_CASES:
        live = load(f"{cid}.json")
        band = dig(live, "record.thresholds")
        days = _f6_days(cid, family_dates)
        rows.append((cid, F6_BANDS[cid], band, days))
        data[cid] = {"verdict": live["verdict"], "thresholds": band,
                     "record_day": next(d["day"] for d in days if d["is_record"]),
                     "days": days}

    # Day 1 above the row centre and day 2 below it, both inside the grey band's height, so a row
    # reads as one comparison against one documented band rather than as two rows.
    OFFSET = 0.19
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    for i, (cid, label, band, days) in enumerate(rows):
        lo, hi = _band_bounds(band)
        ax.barh(i, hi - lo, left=lo, height=2 * OFFSET + 0.26, color="#cfd8e3", zorder=1)
        for day in days:
            q = day["quantiles"]
            y = i + (-OFFSET if day["day"] == "day1" else OFFSET)
            colour = VERDICT_STYLE.get(day["verdict"], VERDICT_STYLE["INCONCLUSIVE"])["color"]
            # Day 1 dashed and hollow, day 2 solid and filled: the two days must stay separable in
            # greyscale and for a red-green-blind reader, because the colour already carries the
            # verdict and cannot also carry the day. The DATE rides the legend rather than each of
            # the ten row tags — repeating it per tag is what pushed the axis out to 10^5 and shrank
            # every measurement into the left third of the canvas.
            dashed = day["day"] == "day1"
            ax.plot([q["p50"], q["p99"]], [y, y], lw=2.2, color=colour, zorder=3,
                    ls=(0, (3, 1.6)) if dashed else "-")
            ax.plot([q["p50"]], [y], "o", ms=5.6, color=colour, zorder=4,
                    mfc="white" if dashed else colour)
            ax.plot([q["p90"]], [y], "|", ms=10, color=colour, zorder=4)
            ax.plot([q["p99"]], [y], "s", ms=4.2, color=colour, zorder=4,
                    mfc="white" if dashed else colour)
            tag = day["verdict"] + ("  ← record" if day["is_record"] else "")
            ax.text(q["p99"] * 1.06, y, tag, va="center", fontsize=7,
                    color=colour, fontweight="bold" if day["is_record"] else "normal")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{cid}  {lab}" for cid, lab, *_ in rows], fontsize=8)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("milliseconds (log scale) — dot p50, tick p90, square p99; "
                  "dashed hollow = day 1, solid filled = day 2", fontsize=8.5)
    headline(fig, "Figure 3 — Measured enforcement latency against the stated bands, both days\n"
                  "colour is that day's own verdict; the arrow marks the day results/phase1/ keeps "
                  "as the verdict of record")
    ax.set_xlim(right=ax.get_xlim()[1] * 1.45)  # room for the right-hand verdict tags
    ax.set_ylim(len(rows) - 0.35, -0.95)        # invert, and leave a strip at the top for the legend
    # Neutral proxy handles, not the drawn artists. Labelling a real line would put the FIRST row's
    # verdict colour on a swatch that means "day 1", and a red swatch labelled with a date teaches
    # that the day is the thing the colour encodes. Here hue means verdict and nothing else.
    ax.legend(handles=[
        Patch(facecolor="#cfd8e3", label="documented band"),
        Line2D([], [], color="#555555", lw=2.0, ls=(0, (3, 1.6)), marker="o", ms=5.6, mfc="white",
               label=f"day 1 · {family_dates['day1']}"),
        Line2D([], [], color="#555555", lw=2.0, marker="o", ms=5.6,
               label=f"day 2 · {family_dates['day2']}"),
    ], fontsize=8, loc="upper left", frameon=False, ncol=3)
    ax.spines[["top", "right"]].set_visible(False)
    footer(ax, ["results/phase1/F6-*.json", "results/phase1/archive/F6-*__day*.json"])
    finish(fig, "fig-03-latency-vs-bands.png")
    return data


def _band_bounds(band):
    """The documented (lo, hi) out of a case's sealed `record.thresholds`.

    For the BAND_CONTAINS cases the sealed thresholds are a two-element list — F6-1 carries
    `[50.0, 200.0]`, which is the document's own illustrative band. Anything else is refused rather
    than coerced: a band silently derived from the wrong field would draw a grey stripe the document
    never stated, and the whole point of figure 3 is the comparison against what was published.
    """
    if isinstance(band, (list, tuple)) and len(band) == 2:
        return float(band[0]), float(band[1])
    raise SystemExit(f"record.thresholds is not a two-element band: {band!r}")


# --- figure 4 ------------------------------------------------------------------------------------

def fig04() -> dict:
    d = load("F3-10_log_surface_join__day1_rederived.json")
    per_arm = dig(d, "per_arm")
    hist: dict[str, int] = {}
    for arm in per_arm.values():
        for k, v in (arm.get("score_histogram") or {}).items():
            hist[k] = hist.get(k, 0) + v
    n_scored = dig(d, "sweep_direction.n_requests_with_a_score")
    n_unscored = dig(d, "sweep_direction.n_requests_with_no_score")
    observed_min = dig(d, "sweep_direction.min_logged_score")
    if sum(hist.values()) != n_scored:
        raise SystemExit(f"histogram sums to {sum(hist.values())}, but n_scored is {n_scored}")

    lattice = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    counts = [hist.get(f"{p:.4f}", 0) for p in lattice]
    censored = [p for p, c in zip(lattice, counts) if c == 0 and p < observed_min]

    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    top = max(counts) * 1.14
    ax.set_ylim(0, top)
    for p, c in zip(lattice, counts):
        if c:
            ax.bar(p, c, width=0.11, color="#2b7a4b", edgecolor="white")
            ax.text(p, c + top * 0.02, str(c), ha="center", fontsize=9)
        else:
            # A FULL-HEIGHT span, never a bar. The first render drew the censored columns as bars of
            # height max(counts)*0.92 = 44.2, which a reader can read straight off the y-axis as a
            # count of 44 — four away from the real 0.8 bar at 48. A censored point has no count to
            # show; a span that runs off the top of the axis cannot be misread as one.
            ax.axvspan(p - 0.055, p + 0.055, facecolor="#ececec", hatch="xx", edgecolor="#c4c4c4",
                       lw=0.6, zorder=0)
            ax.text(p, top * 0.5, "unobservable\nbelow the\nthreshold", rotation=90,
                    ha="center", va="center", fontsize=6.6, color="#555555")
    ax.set_xticks(lattice)
    ax.set_xticklabels([f"{p:.1f}" for p in lattice], fontsize=9)
    ax.set_ylabel(f"requests (n={n_scored} scored)", fontsize=9)
    ax.set_xlabel("logged confidence / severity score — the observed lattice", fontsize=9)
    headline(fig,"Figure 4 — The score distribution is censored by your own threshold\n"
                 f"{n_scored} of {n_scored + n_unscored} requests published a score; "
                 f"the {len(censored)} hatched points are structurally unobservable",
                 )
    ax.spines[["top", "right"]].set_visible(False)
    footer(ax, ["results/phase1/F3-10_log_surface_join__day1_rederived.json"])
    finish(fig, "fig-04-censored-score-lattice.png")
    return {"histogram": hist, "lattice": lattice, "counts": counts,
            "n_scored": n_scored, "n_unscored": n_unscored,
            "observed_min": observed_min, "censored_points": censored}


# --- figure 5 ------------------------------------------------------------------------------------

def _hits(block) -> tuple[int, int]:
    """(x, n) out of an arm's recall/fpr block, whichever per-trial shape it used."""
    if not isinstance(block, dict):
        raise SystemExit("arm block is not a dict")
    if "hits_by_id" in block:
        h = block["hits_by_id"]
        return sum(1 for v in h.values() if v), len(h)
    for xk, nk in (("x", "n"), ("hits", "trials"), ("detected", "total")):
        if xk in block and nk in block:
            return block[xk], block[nk]
    raise SystemExit(f"no per-trial counts in arm block: {sorted(block)[:8]}")


def wilson(x: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return 0.0, 0.0, 0.0
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return p, max(0.0, c - hw), min(1.0, c + hw)


def fig05() -> dict:
    d = load("F5-6.json")
    arms = dig(d, "arms")
    out, rows = {}, []
    for name in sorted(arms):
        arm = arms[name]
        for metric in ("recall", "fpr"):
            if metric not in arm:
                continue
            x, n = _hits(arm[metric])
            p, lo, hi = wilson(x, n)
            out[f"{name}.{metric}"] = {"x": x, "n": n, "point": p, "ci": [lo, hi]}
            if metric == "recall":
                rows.append((name, x, n, p, lo, hi))

    fig, ax = plt.subplots(figsize=(8.0, 2.7))
    for i, (name, x, n, p, lo, hi) in enumerate(rows):
        colour = "#a8322d" if hi < 0.05 else "#2b7a4b"
        ax.plot([lo, hi], [i, i], lw=2.2, color=colour)
        ax.plot([p], [i], "o", ms=7, color=colour)
        # Annotate INSIDE the 0..1 axis: on the right of the interval when there is room, otherwise
        # on its left. The first render extended xlim to 1.28 to fit the text, putting recall values
        # above 1.0 on a proportion axis, which is a region no measurement can occupy.
        label = f"{x}/{n}   {p:.3f} [{lo:.3f}, {hi:.3f}]"
        if hi < 0.55:
            ax.text(hi + 0.015, i, label, va="center", ha="left", fontsize=8)
        else:
            ax.text(lo - 0.015, i, label, va="center", ha="right", fontsize=8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows], fontsize=8)
    ax.set_ylim(len(rows) - 0.5, -0.5)   # inverted, tight — no empty rows top or bottom
    ax.set_xlim(-0.02, 1.02)
    ax.set_xticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_xlabel("attack recall, Wilson 95% CI", fontsize=9)
    headline(fig,"Figure 5 — Untagged input is not evaluated at all (F5-6)\n"
                 "an interval pinned at zero is a measurement, not a missing bar",
                 )
    ax.spines[["top", "right"]].set_visible(False)
    footer(ax, ["results/phase1/F5-6.json"])
    finish(fig, "fig-05-detection-by-arm.png")
    return out


# --- figure 7 ------------------------------------------------------------------------------------

DAY_MARK = {0: ("o", 7.5), 1: ("D", 5.6)}   # day 1 is a circle, day 2 a diamond

F5_2_DAYS = {"2026-08-12": "archive/F5-2__day1_2026-08-12.json",
             "2026-08-13": "F5-2.json"}


def _track(ax, y: float, points: list[tuple[str, float]], label: str, colour: str,
           note: str) -> None:
    """One measured interval, with EVERY measurement day on it.

    Both replication days are plotted because one day's number cannot be told apart from a
    coincidence. F5-2's two days disagree by a second on the same quantity (14.2 s then 13.2 s),
    which is itself the result: the interval is not a constant, so a single-day figure would have
    published a precision the measurement does not have.
    """
    reach = max(t for _, t in points)
    ax.annotate("", xy=(reach, y), xytext=(0, y),
                arrowprops=dict(arrowstyle="-|>", color=colour, lw=2.0, shrinkA=0, shrinkB=0))
    ax.plot([0], [y], "|", ms=13, color="#555555", mew=2.0)
    ax.annotate(f"{label}\n{note}", (0, y), textcoords="offset points", xytext=(2, 13),
                ha="left", va="bottom", fontsize=7.4, color="#333333")
    for i, (_, t) in enumerate(points):
        marker, size = DAY_MARK[i % len(DAY_MARK)]
        ax.plot([t], [y], marker, ms=size, color=colour, zorder=3)
    # One annotation for both days, placed past the arrowhead. Labelling each marker individually
    # put "13.2 s / 08-13" on top of "13.4 s / 08-12": the two days differ by 0.2 s on a 20 s axis,
    # so their labels cannot be separated by position. The markers still show the spread; the text
    # carries the values.
    ax.annotate("   ".join(f"{day[5:]}: {t} s" for day, t in points), (reach, y),
                textcoords="offset points", xytext=(11, 0), ha="left", va="center",
                fontsize=7.8, color=colour, weight="bold")


def fig07() -> dict:
    """Two panels, each with its OWN origin, because the record holds no shared clock.

    The first render put all three events on one "seconds from the accepted mode change" axis and
    placed the restore at `allowed_at + restored_at` = 26.5 s while labelling it "+13.3s". That was a
    fabrication twice over: the position contradicted its own label, and F5-2 records
    `seconds_until_blocking_returned` from the ENFORCE restore call, not from the LOG_ONLY flip. The
    wall-clock gap between the two flips is nowhere in the record, so no single axis can carry both.
    Each measurement therefore gets a track whose zero is the control-plane call it was timed from.

    The two panels are also two orders of magnitude apart (13 s against 326 s), so they do not share
    an x-axis either; each states its own scale and its own sealed bound.

    The HTTP status on the label is READ, not remembered. F5-2's `why_it_is_recorded` prose says
    "UpdateGateway returning 200", and the first render copied that into the label — but the measured
    `chain.flip.http_status` is 202. Narrative prose inside an evidence file is not a measurement.
    """
    days = {}
    for day, name in F5_2_DAYS.items():
        d = load(name)
        days[day] = (dig(d, "mode_change_latency"), dig(d, "data_plane_reconvergence"),
                     dig(d, "chain.flip"))
    order = sorted(days)                      # chronological: day 1 first
    latest = days[order[-1]]
    mcl, dpr = latest[0], latest[1]
    conf = mcl["confirmations_required"]
    statuses = sorted({days[day][2]["http_status"] for day in order})
    # Day-label the accept latencies too. "603 ms, 932 ms" leaves the reader to infer which day is
    # which from list order, and every other number on this figure states its day.
    accepts = ", ".join(f"{day[5:]} {days[day][2]['elapsed_ms']:.0f} ms" for day in order)

    off_pts = [(day, days[day][0]["seconds_until_blocked_request_was_allowed"]) for day in order]
    on_pts = [(day, days[day][0]["seconds_until_blocking_returned"]) for day in order]
    deny1_pts = [(day, days[day][1]["seconds_to_the_first_denial"]) for day in order]
    deny3_pts = [(day, days[day][1]["seconds_to_three_consecutive_denials"]) for day in order]

    fig, (axl, axr) = plt.subplots(1, 2, figsize=(9.6, 3.2), gridspec_kw={"width_ratios": [1, 1]})

    status = "/".join(str(s) for s in statuses)
    _track(axl, 1, off_pts, f"UpdateGateway sets LOG_ONLY — HTTP {status}, accepted in {accepts}",
           "#a8322d", f"→ a previously blocked request is SERVED, {conf}x "
                      f"{mcl['decisions_seen_awaiting_log_only'][0]}")
    _track(axl, 0, on_pts, "UpdateGateway restores ENFORCE",
           "#2b7a4b", f"→ blocking observed again, {conf}x "
                      f"{mcl['decisions_seen_awaiting_enforce'][0]}")
    axl.set_xlim(-0.7, max(t for _, t in off_pts) * 1.78)
    axl.set_ylim(-0.75, 2.05)
    axl.set_xlabel(f"seconds from each call — sealed bound {mcl['bound_s']} s", fontsize=8.4)

    _track(axr, 1, deny1_pts, "the role's gateway grant is revoked",
           "#a8322d", "→ the FIRST call is denied by IAM")
    _track(axr, 0, deny3_pts, "the same revocation",
           "#a8322d", f"→ 3 consecutive denials; "
                      f"{dpr['n_that_were_still_authorized']}/{dpr['n_post_restore_attempts']} "
                      f"later attempts authorized")
    axr.set_xlim(-16, max(t for _, t in deny3_pts) * 1.62)
    axr.set_ylim(-0.75, 2.05)
    axr.set_xlabel(f"seconds from the revocation — sealed bound {dpr['revoke_wait_bound_s']} s",
                   fontsize=8.4)

    # Derive the scale ratio from the axes rather than typing a round number next to them: the two
    # panels look alike and are not, and a hand-written "25x" is a claim nothing recomputes.
    span_l = axl.get_xlim()[1] - axl.get_xlim()[0]
    span_r = axr.get_xlim()[1] - axr.get_xlim()[0]
    for ax, sub in ((axl, "A — mode flips, both directions"),
                    (axr, f"B — grant revocation (note: a {span_r / span_l:.0f}x wider scale)")):
        ax.set_yticks([])
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.set_title(sub, fontsize=8.6, loc="left", color="#444444", pad=3)

    headline(fig,"Figure 7 — A control-plane call and the behaviour it governs are not simultaneous (F5-2)\n"
                 "each track is timed from its own call; the record holds no clock shared between them",
                 )
    footer(axl, [f"results/phase1/{n}" for n in F5_2_DAYS.values()])
    finish(fig, "fig-07-mode-flip-timeline.png")
    return {"per_day": {day: {
                "accept_http_status": days[day][2]["http_status"],
                "accept_elapsed_ms": days[day][2]["elapsed_ms"],
                "seconds_until_blocked_request_was_allowed":
                    days[day][0]["seconds_until_blocked_request_was_allowed"],
                "seconds_until_blocking_returned":
                    days[day][0]["seconds_until_blocking_returned"],
                "seconds_to_the_first_denial": days[day][1]["seconds_to_the_first_denial"],
                "seconds_to_three_consecutive_denials":
                    days[day][1]["seconds_to_three_consecutive_denials"],
            } for day in order},
            "bound_s": mcl.get("bound_s"),
            "confirmations_required": conf,
            "revoke_wait_bound_s": dpr.get("revoke_wait_bound_s")}


# --- figure 8 ------------------------------------------------------------------------------------

DAYS = {"2026-08-13": "F3-10_log_surface_join.json",
        "2026-08-12": "F3-10_log_surface_join__day1_rederived.json"}


def fig08() -> dict:
    data, plot = {}, []
    for day in sorted(DAYS):
        d = load(DAYS[day])
        rec = dig(d, "reconciliation_with_metrics")
        data[day] = {"all_agree": rec["all_agree"], "checked": rec["checked"], "per_arm": {}}
        for arm, blk in rec["per_arm"].items():
            data[day]["per_arm"][arm] = {"log_sum": blk["log_sum"], "metric_sum": blk["metric_sum"],
                                         "agrees": blk["agrees"],
                                         "n_logged_score_values": blk["n_logged_score_values"]}
            plot.append((f"{day}\n{arm}", blk["log_sum"], blk["metric_sum"], blk["agrees"]))

    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    idx = range(len(plot))
    w = 0.36
    for i, (label, ls, ms, agrees) in zip(idx, plot):
        ax.bar(i - w / 2, ls, width=w, color="#3a6ea5", edgecolor="white")
        ax.bar(i + w / 2, ms, width=w, color="#2b7a4b", edgecolor="white")
        ax.text(i, max(ls, ms) * 1.04, f"{ls} = {ms}" if agrees else f"{ls} != {ms}",
                ha="center", fontsize=7.4,
                color="#2b7a4b" if agrees else "#a8322d")
    ax.set_xticks(list(idx))
    ax.set_xticklabels([p[0] for p in plot], fontsize=7)
    ax.set_ylabel("sum of scores over the same buckets", fontsize=9)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in ("#3a6ea5", "#2b7a4b")]
    ax.legend(handles, ["logged contentFilter[].score", "ConfidenceScore metric"],
              fontsize=8, frameon=False, loc="upper center", ncol=2)
    ax.set_ylim(0, max(max(p[1], p[2]) for p in plot) * 1.32)
    headline(fig,"Figure 8 — The log surface and the metric surface are the same numbers (DEV-P4-27)\n"
                 "the sums differ between days because the scores do, and reconcile within each day",
                 )
    ax.spines[["top", "right"]].set_visible(False)
    footer(ax, [f"results/phase1/{v}" for v in DAYS.values()])
    finish(fig, "fig-08-metric-log-agreement.png")
    return data


# --- figure 6, blocked ---------------------------------------------------------------------------

FIG06_BLOCKED = {
    "state": "BLOCKED",
    "reason": (
        "The control x threat matrix needs all seventeen OWASP Agentic AI v1.1 threat titles. Five "
        "are grounded in this project's notes (T1, T3, T9, T15, T16); twelve are not. Rendering "
        "twelve columns from memory would be fabrication, and rendering them as a third state would "
        "report a sourcing gap as a coverage finding."),
    "closes_when": (
        "the pinned v1.1 PDF (sha256 65e3bd59f99c...0345ff) is re-read for T1-T17 titles and a "
        "per-control state is authored into results/CROSSMAP-ACG-THREATS.json, which this script "
        "would then read. The mapping is authorial and the data file must say so."),
    "grounded_threat_ids": ["T1", "T3", "T9", "T15", "T16"],
    "ungrounded_count": 12,
}


def build() -> dict:
    D = whitepaper_data.build()
    figs = {
        "fig-01-verdict-distribution": fig01(D),
        "fig-02-evidence-by-section": fig02(D),
        "fig-03-latency-vs-bands": fig03(),
        "fig-04-censored-score-lattice": fig04(),
        "fig-05-detection-by-arm": fig05(),
        "fig-06-control-threat-matrix": FIG06_BLOCKED,
        "fig-07-mode-flip-timeline": fig07(),
        "fig-08-metric-log-agreement": fig08(),
    }
    return {"generated_by": "tools/whitepaper_figures.py",
            "matplotlib": matplotlib.__version__,
            "note": ("--check compares these numbers, never the PNG bytes: rendered bytes move with "
                     "matplotlib/freetype versions while the measurements do not."),
            "register_sha256_recomputed": D["sources"]["register_sha256_recomputed"],
            "figures": figs}


def _leaves(obj, prefix: str = "") -> dict[str, object]:
    """Flatten to `dotted.path[i] -> scalar`, so a difference can be named instead of asserted."""
    if isinstance(obj, dict):
        out: dict[str, object] = {}
        for k, v in obj.items():
            out.update(_leaves(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    if isinstance(obj, list):
        out = {}
        for i, v in enumerate(obj):
            out.update(_leaves(v, f"{prefix}[{i}]"))
        return out
    return {prefix: obj}


def report_drift(manifest_text: str, fresh_text: str) -> None:
    """Print WHICH numbers moved, to stderr, in `path: manifest -> re-derived` form.

    A `--check` that prints only `STALE` gives the operator nothing: on 2026-08-20 this exit 1 had
    to be diagnosed by hand-writing a flattening script, and the answer — five F6 percentiles and
    one denominator, all of figure 3, because the 2026-08-19 day-2 replication landed after the
    manifest was last written — was a legitimate re-derivation rather than a defect. Those are
    opposite dispositions and the gate said nothing that separated them. A drift of one percentile
    and a drift of every figure in the file are also opposite situations; the count alone tells them
    apart, so it is printed even when the list is truncated.

    A difference the parsed leaves cannot explain is reported as such rather than as an empty diff,
    because "STALE, and here is nothing" is the same uselessness one level down.
    """
    try:
        old = _leaves(json.loads(manifest_text))
    except json.JSONDecodeError as exc:
        print(f"  MANIFEST.json is not valid JSON ({exc}); no per-number diff is possible",
              file=sys.stderr)
        return
    new = _leaves(json.loads(fresh_text))
    moved = [k for k in sorted(set(old) | set(new)) if old.get(k, _MISSING) != new.get(k, _MISSING)]
    if not moved:
        print("  every number agrees; the files differ in formatting, key order or whitespace only "
              "— regenerate to normalise it", file=sys.stderr)
        return
    print(f"  {len(moved)} of {len(set(old) | set(new))} value(s) moved:", file=sys.stderr)
    for k in moved[:DRIFT_LINES]:
        o, n = old.get(k, _MISSING), new.get(k, _MISSING)
        print(f"    {k}: {o!r} -> {n!r}", file=sys.stderr)
    if len(moved) > DRIFT_LINES:
        print(f"    … and {len(moved) - DRIFT_LINES} more", file=sys.stderr)


class _Missing:
    def __repr__(self) -> str:
        return "<absent>"


_MISSING = _Missing()
DRIFT_LINES = 40


def main(argv: list[str] | None = None) -> int:
    global WRITE_PNGS

    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="re-derive the numbers, name any that differ from MANIFEST.json, exit 1; "
                         "renders every figure but writes no PNG")
    a = ap.parse_args(argv)

    WRITE_PNGS = not a.check  # set BEFORE build(): see the WRITE_PNGS comment above finish()
    m = build()
    # Masked BEFORE the --check comparison, not only before the write, so both paths compare the
    # same bytes. `results/` is distributable and every write into it must mask
    # (lib/tests/test_results_writes_are_masked.py). The manifest holds counts, thresholds and one
    # sha256, all derived from files already under `results/`, so on clean input this is a no-op —
    # which is the point: a guarantee that holds because the inputs happen to be clean is not one.
    text = mask_text(json.dumps(m, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    if a.check:
        if not MANIFEST.exists():
            print(f"STALE — {MANIFEST.relative_to(ROOT)} does not exist", file=sys.stderr)
            return 1
        stored = MANIFEST.read_text(encoding="utf-8")
        if stored != text:
            print("STALE — the figures' numbers no longer match MANIFEST.json", file=sys.stderr)
            report_drift(stored, text)
            return 1
        print("FRESH — every figure's numbers match MANIFEST.json")
        return 0

    MANIFEST.write_text(text, encoding="utf-8")
    drawn = [k for k, v in m["figures"].items() if v.get("state") != "BLOCKED"]
    blocked = [k for k, v in m["figures"].items() if v.get("state") == "BLOCKED"]
    print(f"wrote {len(drawn)} figure(s) to {FIGDIR.relative_to(ROOT)}/ and MANIFEST.json")
    for k in drawn:
        print(f"  {k}.png")
    for k in blocked:
        print(f"  {k}  BLOCKED — {m['figures'][k]['reason'][:70]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
