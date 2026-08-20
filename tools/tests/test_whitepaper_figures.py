#!/usr/bin/env python3
"""`tools/whitepaper_figures.py --check` is a gate in the publish chain and had no test at all.

Why this file exists
--------------------
Two defects, both found on 2026-08-20 by running the gate and then looking at what it had done.

1. **`--check` wrote the files it was checking.** `build()` calls every `figNN()`, each of which
   calls `finish()`, which called `savefig` unconditionally. So the read-only freshness check
   overwrote all seven PNGs and then reported `STALE` about the manifest describing the bytes it had
   just replaced. Two things follow. No stale PNG is detectable, because looking rewrites it. And
   the write escapes the process: the full suite's concurrent-writer detector reported
   `7 change(s) under results/ ... made by ANOTHER PROCESS` and declared its own tree-diff channel
   VOID for the session, so a `--check` in a neighbouring shell cost a 1 h 28 m run half its
   coverage. `test_check_writes_no_png` is the arm; `test_finish_writes_when_asked` is its control,
   because an assertion that no PNG appeared would also pass if `finish()` had stopped drawing.

2. **`--check` named no number.** It printed `STALE — the figures' numbers no longer match
   MANIFEST.json` and exited 1, and diagnosing which number had moved took a hand-written
   flattening script. The answer mattered: five F6 percentiles and one denominator, all of figure 3,
   because the 2026-08-19 day-2 replication landed after the manifest was last written — a
   legitimate re-derivation, not a defect. "Regenerate the manifest" and "a figure is wrong" are
   opposite dispositions and the gate said nothing that separated them.

Why a subprocess against `.venv-figs`
-------------------------------------
`whitepaper_figures.py` imports matplotlib, which by design lives only in `.venv-figs`: the sealed
oracle's venv pins botocore as a measurement instrument and must not acquire a plotting stack. The
suite runs under `.venv-oracle`, so an in-process import would fail there for a correct reason. These
tests therefore drive the real interpreter the tool is run with, and skip — loudly, naming the path —
when it is not on the machine, which is the same condition under which the figures cannot be built
at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
FIGS_PYTHON = REPO / ".venv-figs" / "bin" / "python"
SUBJECT = REPO / "tools" / "whitepaper_figures.py"


def _figs_python() -> Path:
    if not FIGS_PYTHON.exists():
        pytest.skip(f"{FIGS_PYTHON.relative_to(REPO)} is not on this machine, so the figure "
                    f"toolchain cannot run here either")
    return FIGS_PYTHON


def _drive(body: str) -> subprocess.CompletedProcess:
    """Run `body` under `.venv-figs` with `tools/` importable, and return the completed process."""
    script = "import sys; sys.path.insert(0, %r)\nimport whitepaper_figures as wf\n%s" % (
        str(REPO / "tools"), textwrap.dedent(body))
    return subprocess.run([str(_figs_python()), "-c", script], cwd=REPO,
                          capture_output=True, text=True, check=False)


# --------------------------------------------------------------- 1. --check must not write

def test_check_writes_no_png(tmp_path):
    """The real `main(["--check"])`, with `FIGDIR` pointed at an empty directory.

    Patching `FIGDIR` and not `MANIFEST` is deliberate: the check still reads the repository's real
    manifest, so its return code is whatever the tree says today and is not what this asserts. What
    is asserted is that a full build under `--check` puts nothing on disk.
    """
    proc = _drive(f"""
        from pathlib import Path
        wf.FIGDIR = Path({str(tmp_path)!r})
        rc = wf.main(["--check"])
        print("rc=%d" % rc)
        print("wrote=%d" % len(list(Path({str(tmp_path)!r}).rglob("*"))))
    """)
    assert proc.returncode == 0, f"the driver itself failed:\n{proc.stderr}"
    assert "wrote=0" in proc.stdout, (
        "--check put files in FIGDIR. It renders every figure on purpose — a NaN axis raises in "
        f"savefig — but it must render into a discarded buffer:\n{proc.stdout}\n{proc.stderr}")
    assert "rc=" in proc.stdout


def test_finish_writes_when_asked(tmp_path):
    """The control for the arm above: with `WRITE_PNGS` true, one PNG appears.

    Without this, `test_check_writes_no_png` would pass just as happily if `finish()` had stopped
    saving under every condition, or if the figure functions had stopped being called at all.
    """
    proc = _drive(f"""
        from pathlib import Path
        import matplotlib.pyplot as plt
        out = Path({str(tmp_path)!r})
        wf.FIGDIR = out
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        wf.WRITE_PNGS = True
        wf.finish(fig, "control.png")
        print("wrote=%s" % sorted(p.name for p in out.rglob("*.png")))
    """)
    assert proc.returncode == 0, proc.stderr
    assert "wrote=['control.png']" in proc.stdout, proc.stdout + proc.stderr


def test_finish_is_silent_when_told_not_to_write(tmp_path):
    """And the same call with the flag off writes nothing, so the flag is what decides."""
    proc = _drive(f"""
        from pathlib import Path
        import matplotlib.pyplot as plt
        out = Path({str(tmp_path)!r})
        wf.FIGDIR = out
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        wf.WRITE_PNGS = False
        wf.finish(fig, "control.png")
        print("wrote=%s" % sorted(p.name for p in out.rglob("*.png")))
    """)
    assert proc.returncode == 0, proc.stderr
    assert "wrote=[]" in proc.stdout, proc.stdout + proc.stderr


# --------------------------------------------------------------- 2. --check must name the numbers

DRIFT_CASES = [
    # (label, manifest, fresh, must appear in stderr)
    ("one leaf moved", {"a": {"b": 1}}, {"a": {"b": 2}}, "a.b: 1 -> 2"),
    ("leaf appeared", {"l": [1]}, {"l": [1, 2]}, "l[1]: <absent> -> 2"),
    ("leaf vanished", {"a": 1, "b": 2}, {"a": 1}, "b: 2 -> <absent>"),
]


@pytest.mark.parametrize("label,old,new,expected", DRIFT_CASES, ids=[c[0] for c in DRIFT_CASES])
def test_report_drift_names_the_value_that_moved(label, old, new, expected):
    proc = _drive(f"""
        wf.report_drift({json.dumps(json.dumps(old))}, {json.dumps(json.dumps(new))})
    """)
    assert proc.returncode == 0, proc.stderr
    assert expected in proc.stderr, f"{label}: expected {expected!r} in:\n{proc.stderr}"


def test_report_drift_says_so_when_only_the_formatting_moved():
    """`STALE` with an empty diff is the same uselessness one level down."""
    same = {"a": {"b": 1}, "l": [1, 2]}
    proc = _drive(f"""
        import json
        m = {json.dumps(same)}
        wf.report_drift(json.dumps(m, indent=2), json.dumps(m))
    """)
    assert proc.returncode == 0, proc.stderr
    assert "formatting" in proc.stderr, proc.stderr
    assert "value(s) moved" not in proc.stderr, (
        "a formatting-only difference was reported as moved values:\n" + proc.stderr)


def test_report_drift_reports_an_unparseable_manifest_rather_than_crashing():
    """A corrupt manifest must not turn a red gate into a traceback with no finding in it."""
    proc = _drive("""
        wf.report_drift("{not json", '{"a": 1}')
    """)
    assert proc.returncode == 0, f"report_drift raised instead of reporting:\n{proc.stderr}"
    assert "not valid JSON" in proc.stderr, proc.stderr


def test_report_drift_truncates_but_still_states_the_total():
    """One percentile moving and every figure moving are opposite situations; print the count."""
    old = {str(i): i for i in range(9)}
    new = {str(i): i + 1 for i in range(9)}
    proc = _drive(f"""
        wf.DRIFT_LINES = 3
        wf.report_drift({json.dumps(json.dumps(old))}, {json.dumps(json.dumps(new))})
    """)
    assert proc.returncode == 0, proc.stderr
    assert "9 of 9 value(s) moved" in proc.stderr, proc.stderr
    assert "and 6 more" in proc.stderr, proc.stderr


# --------------------------------------------------------------- 3. headline() must not crop

# Figure 3's two title lines as of 2026-08-20, joined into ONE paragraph. That is the shape that
# cropped: `headline()` wraps each input line independently, so what overflowed was a line the WRAP
# produced at the naive budget of `int(8.6 / _CHAR_IN)` = 125 characters, on a canvas that fits about
# 112 at TITLE_PT. The published PNG ended a line "…and th" and resumed the next at "marks", with
# "e arrow" simply gone. Nothing failed: `savefig` returned, `--check` was green, and the defect was
# visible only by looking at the image.
#
# The exact pre-fix string is NOT reproduced here, because it was replaced before it was recorded and
# a test that claimed to be it would be asserting something unverified. What is reproduced is the
# condition, which is the part that generalises: a mean advance width over-budgets any line whose
# letters run wider than average, so a filled 125-character line of ordinary prose overruns. The
# control below proves this input really does trip that, so the regression cannot go vacuous quietly.
LONG_TITLE = ("Figure 3 — Measured enforcement latency against the stated bands, both days "
              "colour is that day's own verdict; the arrow marks the day results/phase1/ keeps "
              "as the verdict of record")


def _headline_extent(size, text: str) -> subprocess.CompletedProcess:
    """Render `text` as a headline on a `size` canvas; print its line count and overrun in px."""
    return _drive(f"""
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize={tuple(size)!r})
        n = wf.headline(fig, {text!r})
        limit = fig.get_window_extent().x1 - 3
        widest = max(a.get_window_extent(fig.canvas.get_renderer()).x1 for a in fig.texts)
        print("lines=%d overrun=%.1f top=%.12f" % (n, widest - limit, fig._wp_top))
    """)


def test_headline_fits_a_title_long_enough_to_have_cropped():
    """The regression, asserted on the RENDERED extent rather than on a character count.

    A character count is the thing that was broken, so a test written in characters would agree with
    the defect. `overrun` is how far the drawn glyphs exceed the canvas: at or below zero is the whole
    correctness condition, and it is measured from the same renderer `savefig` uses.
    """
    proc = _headline_extent((8.6, 4.2), LONG_TITLE)
    assert proc.returncode == 0, f"headline() raised on a title that can be made to fit:\n{proc.stderr}"
    overrun = float(proc.stdout.split("overrun=")[1].split()[0])
    assert overrun <= 0, (
        f"the title overruns the canvas by {overrun:.1f} device px, so matplotlib will crop it and "
        f"the figure will publish a truncated sentence:\n{proc.stdout}")


def test_the_naive_character_estimate_would_have_cropped_it():
    """The control: without this, the arm above could pass because the title got shorter.

    Reproduces `headline()`'s FIRST guess — `int(figwidth / _CHAR_IN)` characters per line, the value
    the function used to commit to — and asserts that guess really does overrun on this input. If a
    font or a constant changes such that the naive estimate stops overflowing, this fails and says so
    rather than leaving the regression above quietly testing nothing.
    """
    proc = _drive(f"""
        import textwrap
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(8.6, 4.2))
        per_line = max(40, int(fig.get_figwidth() / wf._CHAR_IN))
        wrapped = textwrap.fill({LONG_TITLE!r}, per_line)
        a = fig.text(0.008, 0.99, wrapped, fontsize=wf.TITLE_PT, ha="left", va="top")
        limit = fig.get_window_extent().x1 - 3
        print("per_line=%d overrun=%.1f" % (
            per_line, a.get_window_extent(fig.canvas.get_renderer()).x1 - limit))
    """)
    assert proc.returncode == 0, proc.stderr
    overrun = float(proc.stdout.split("overrun=")[1])
    assert overrun > 0, (
        "the naive mean-advance-width estimate no longer overflows on this input, so "
        f"test_headline_fits_a_title_long_enough_to_have_cropped is now vacuous:\n{proc.stdout}")


def test_headline_refuses_a_title_that_would_squash_the_axes():
    """The height bound, and the arm that found the width fix was only half a fix.

    A 200-character unbreakable token is the case that showed `SystemExit` was unreachable:
    `textwrap.fill` breaks long words, so narrowing the wrap fits anything, and the old code returned
    normally after wrapping it to six lines — then clamped `_wp_top` to 0.45 and handed back a figure
    whose axes had been silently reduced to under half the canvas. Refusing is the only honest
    outcome, because choosing between a shorter title and a taller figure is a human's call.
    """
    proc = _headline_extent((3.0, 1.6), "x" * 200)
    assert proc.returncode != 0, (
        f"headline() returned on a title that cannot fit — the axes were silently squashed to make "
        f"room:\n{proc.stdout}")
    assert "does not fit" in proc.stderr, proc.stderr
    assert "canvas height" in proc.stderr, (
        "the refusal does not name the bound that failed, so an operator cannot tell whether to "
        "shorten the title or make the figure wider:\n" + proc.stderr)
    assert "shorten" in proc.stderr, (
        "the failure does not tell the operator what to do about it:\n" + proc.stderr)


def test_headline_reserves_exactly_what_it_wrapped_and_never_clamps():
    """`_wp_top` must be the complement of the space the title actually took.

    The old `max(0.45, …)` made `_wp_top` disagree with `n_lines` for any tall title, so `finish()`
    reserved a strip the title did not fit inside. Asserted as an identity against the returned line
    count, which is the only other output, so the two cannot drift apart (`feedback_two_numbers_two_claims`).
    """
    proc = _headline_extent((8.6, 4.2), LONG_TITLE)
    assert proc.returncode == 0, proc.stderr
    out = dict(kv.split("=") for kv in proc.stdout.split())
    n_lines, top = int(out["lines"]), float(out["top"])
    expected = 1.0 - (n_lines * 0.20 + 0.14) / 4.2
    assert abs(top - expected) < 1e-9, (
        f"_wp_top {top:.4f} is not the complement of the {n_lines} lines drawn "
        f"(expected {expected:.4f}) — something clamped or rounded it")


# --------------------------------------------------------------- 4. the flag reaches the gate

def test_check_sets_the_flag_before_building():
    """`WRITE_PNGS` is read inside `finish()`, so an assignment after `build()` would be a no-op.

    Ordering bugs of this shape are invisible in a passing `--check`: the return code is identical
    either way and only the tree differs. Asserted on the source rather than by observing the tree,
    because the arms above already observe the tree and this one names the reason they pass.
    """
    src = SUBJECT.read_text(encoding="utf-8")
    body = src[src.index("def main("):]
    assign = body.index("WRITE_PNGS = not a.check")
    build = body.index("m = build()")
    assert assign < build, "WRITE_PNGS is assigned after build(); every figure is already written"
