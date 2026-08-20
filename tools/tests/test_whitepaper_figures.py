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


# --------------------------------------------------------------- 3. the flag reaches the gate

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
