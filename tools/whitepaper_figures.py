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
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402
matplotlib.use("Agg")  # no display in this environment, and determinism matters more than interactivity
import matplotlib.pyplot as plt  # noqa: E402

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
    """
    per_line = max(40, int(fig.get_figwidth() / _CHAR_IN))
    wrapped = "\n".join(textwrap.fill(line, per_line) for line in text.split("\n"))
    n_lines = wrapped.count("\n") + 1
    reserved = (n_lines * _LINE_IN + 0.14) / fig.get_figheight()
    fig.text(0.008, 1.0 - 0.02 / fig.get_figheight(), wrapped,
             fontsize=TITLE_PT, ha="left", va="top")
    fig._wp_top = max(0.45, 1.0 - reserved)
    return n_lines


def footer(ax, sources: list[str]) -> None:
    ax.figure.text(0.006, 0.012, "generated by tools/whitepaper_figures.py from " + ", ".join(sources),
                   fontsize=5.2, color="#666666", ha="left", va="bottom")


def finish(fig, out: str) -> None:
    """Save with a reserved footer strip instead of `bbox_inches="tight"`.

    `tight` sizes the canvas to the artists, which pulls the provenance footer up until it collides
    with the x-axis label — measured on the first render of figure 3, where the two overlapped
    outright. Reserving the bottom 6% and laying out into the remainder puts the footer somewhere
    deterministic on every figure, at the cost of a little whitespace.
    """
    FIGDIR.mkdir(parents=True, exist_ok=True)
    bottom = (0.18 + 0.04) / fig.get_figheight()   # provenance footer strip
    fig.tight_layout(rect=(0, bottom, 1, getattr(fig, "_wp_top", 1.0)))
    fig.savefig(FIGDIR / out, dpi=200)
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


def fig03() -> dict:
    rows, data = [], {}
    for cid in ("F6-1", "F6-2", "F6-3", "F6-5", "F6-6"):
        d = load(f"{cid}.json")
        q = _quantiles(d)
        band = dig(d, "record.thresholds")
        rows.append((cid, F6_BANDS[cid], q, band, d["verdict"]))
        data[cid] = {"verdict": d["verdict"], "quantiles": q, "thresholds": band}

    fig, ax = plt.subplots(figsize=(8.6, 3.0))
    for i, (cid, label, q, band, verdict) in enumerate(rows):
        lo, hi = _band_bounds(band)
        if lo is not None:
            ax.plot([lo, hi], [i, i], lw=9, color="#cfd8e3", solid_capstyle="butt",
                    zorder=1, label="documented band" if i == 0 else None)
        colour = "#a8322d" if verdict == "FALSE" else "#2b7a4b"
        ax.plot([q["p50"], q["p99"]], [i, i], lw=2.4, color=colour, zorder=3,
                label="measured p50-p99" if i == 0 else None)
        ax.plot([q["p50"]], [i], "o", ms=6, color=colour, zorder=4)
        ax.plot([q["p90"]], [i], "|", ms=11, color=colour, zorder=4)
        ax.plot([q["p99"]], [i], "s", ms=4.5, color=colour, zorder=4)
        ax.text(q["p99"] * 1.04, i, f"{verdict}", va="center", fontsize=8, color=colour)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{cid}  {lab}" for cid, lab, *_ in rows], fontsize=8)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("milliseconds (log scale) — dot p50, tick p90, square p99", fontsize=9)
    headline(fig,"Figure 3 — Measured enforcement latency against the document's stated bands\n"
                 "the oracle is BAND_CONTAINS over the p50-p99 band, not over the median alone",
                 )
    ax.set_ylim(len(rows) - 0.45, -0.9)  # invert, and leave a strip at the top for the legend
    ax.legend(fontsize=8, loc="upper left", frameon=False, ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    footer(ax, ["results/phase1/F6-*.json"])
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="re-derive the numbers and exit 1 if they differ from MANIFEST.json")
    a = ap.parse_args(argv)

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
        if MANIFEST.read_text(encoding="utf-8") != text:
            print("STALE — the figures' numbers no longer match MANIFEST.json", file=sys.stderr)
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
