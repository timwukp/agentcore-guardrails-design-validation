"""Every `help=` string in this repo must survive the `%`-expansion argparse performs on it.

WHY THIS EXISTS
---------------
`tools/sync_handover_bundle.py` shipped this line on 2026-08-17 and carried it through four bundle
syncs, two pull requests and a 32-arm test file of its own:

    help=f"permit deleting more than {PRUNE_FRACTION:.0%} of the mirror"

The format spec `.0%` puts a literal percent into the string, so the help text reads
`permit deleting more than 5% of the mirror` — and argparse renders every help string by doing
`help % params` with a dict. `5% of` therefore parses as the conversion `% o`, octal, which wants an
integer and is handed the params dict:

    TypeError: %o format: an integer is required, not dict

On Python 3.12 that fires only inside `--help`, so it stayed invisible: nothing in this repo had ever
asked this tool for help. **Python 3.14 validates help strings inside `add_argument` itself**, so on
2026-09-17, when `python3` on this machine became 3.14.7, every invocation of the tool — including the
`--apply` the hand-over bundle re-sync depends on — died before parsing its arguments. A latent defect
in a string nobody reads was promoted to a hard blocker by an interpreter upgrade, and the tool's own
tests could not see it because they call `main(argv)` with real arguments.

WHAT THIS CHECKS, AND WHY IT IS NOT A REGEX ABOUT PERCENTS
----------------------------------------------------------
A lone percent is not the defect. `%(default)s` and `%(prog)s` are argparse's own documented
substitutions and are *supposed* to appear in help text. The property that matters is narrower and
exactly checkable: **the string must survive the operation argparse performs on it**. So this test
does that operation — `text % params`, with `params` built the way `HelpFormatter._expand_help`
builds it, from a real `argparse.Action`'s attributes plus `prog` — and fails on the exception rather
than on a character. `%(default)s` passes because argparse would render it; `5% of` fails because
argparse would crash.

WHAT IT CANNOT SEE, ON THE RECORD
---------------------------------
The scan is static, so it reads what the source states and nothing a value carries at runtime:

  * `help=f"{some_string}"` — an interpolated *value* containing a percent is invisible here. The
    format SPEC is read (that is where the original defect lived: `{X:.0%}`), the value is not.
  * A help string assembled by a call or a concatenation cannot be read at all. Rather than exempt
    those quietly, the second arm asserts there are **none** today (measured: 0 of 162), so the first
    one to appear fails this file and forces a decision instead of opening a blind spot.
  * `description=` and `epilog=` are deliberately out of scope: argparse does not `%`-expand them.
    Only `help=` goes through `_expand_help`, which is why only `help=` can crash this way.

The sweep covers every `help=` keyword in every in-scope `.py` file, not just calls whose receiver is
named `add_argument` — a scope written as a list of call names cannot notice a new one
(`feedback_scope_as_namelist`), and a non-argparse `help=` that happens to hold a bare percent costs
one deliberate widening here, which is the cheap direction to be wrong in.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_scope import ROOT, py_files  # noqa: E402  the one definition of "this repo's own source"

# Measured 2026-09-17: 162 `help=` keywords in scope. The floor is a `ran` flag, not a target — a
# scan that reads almost nothing reports clean over the whole repo, and this project has paid for
# that shape often enough to name it (`feedback_zero_file_scan_is_error`).
MIN_HELP_STRINGS = 120

# The tool the defect shipped in, and the only one whose rendered help text is asserted verbatim.
DEFECT_SITE = Path("tools/sync_handover_bundle.py")
DEFECT_SITE_RENDERS = "permit deleting more than 5% of the mirror"


def _argparse_params() -> dict:
    """The dict `HelpFormatter._expand_help` expands a help string against.

    Built from a real `argparse.Action` rather than hand-listed, so it holds whatever attributes this
    interpreter's argparse gives an action — the point is to reproduce argparse's operation, and a
    hand-written stand-in would be a second, drifting definition of it.
    """
    action = argparse.Action(option_strings=[], dest="dest")
    return dict(vars(action), prog="prog")


def percent_expansion_failure(text: str) -> str | None:
    """Return the error argparse would raise rendering `text`, or None if it renders."""
    try:
        text % _argparse_params()
    except Exception as exc:                                   # noqa: BLE001  the exception IS the finding
        return f"{type(exc).__name__}: {exc}"
    return None


def _static_text(node: ast.expr) -> str | None:
    """Flatten a `help=` value to the text a reader would see, or None if it is not readable.

    An f-string contributes its literal parts AND each field's format spec, because a spec emits
    characters into the result — `{x:.0%}` is precisely how the original defect entered a string whose
    source contains no percent sign at all. A field's *value* contributes nothing, which is stated in
    this module's docstring as a limit rather than left to be discovered.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue) and part.format_spec is not None:
                spec = _static_text(part.format_spec)
                if spec is None:
                    return None
                out.append(spec)
        return "".join(out)
    return None


def _help_arguments() -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """Every `help=` keyword in scope, as (readable, unreadable) lists of (path, line, detail)."""
    readable: list[tuple[str, int, str]] = []
    unreadable: list[tuple[str, int, str]] = []
    for path in py_files():
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "help":
                    continue
                text = _static_text(kw.value)
                if text is None:
                    unreadable.append((rel, kw.value.lineno, type(kw.value).__name__))
                else:
                    readable.append((rel, kw.value.lineno, text))
    return readable, unreadable


def test_every_help_string_survives_the_expansion_argparse_performs() -> None:
    readable, _ = _help_arguments()
    assert len(readable) >= MIN_HELP_STRINGS, (
        f"only {len(readable)} readable help string(s) in scope, floor {MIN_HELP_STRINGS} — a scan "
        f"that reads almost nothing passes over the whole repo and reports clean")

    broken = [(rel, line, text, err)
              for rel, line, text in readable
              if (err := percent_expansion_failure(text)) is not None]
    assert not broken, "help string(s) argparse cannot render:\n" + "\n".join(
        f"  {rel}:{line}  {err}\n      help = {text!r}\n"
        f"      double the percent (`%%`) — argparse expands every help string with `help % params`"
        for rel, line, text, err in broken)


def test_no_help_string_is_assembled_out_of_reach_of_this_check() -> None:
    _, unreadable = _help_arguments()
    assert not unreadable, (
        "help= value(s) this static check cannot read, so nothing checks whether argparse can "
        "render them:\n" + "\n".join(f"  {rel}:{line}  {kind}" for rel, line, kind in unreadable)
        + "\n  Either write the help text as a literal or an f-string, or widen _static_text() "
          "deliberately — a blind spot is not a place to add an entry to.")


def test_the_expansion_check_discriminates() -> None:
    """The control. A checker that says 'renders' to everything would pass the sweep vacuously."""
    assert percent_expansion_failure("permit deleting more than 5% of the mirror") is not None
    assert percent_expansion_failure("permit deleting more than 5%% of the mirror") is None
    # argparse's own substitutions must NOT be flagged — that is why this is an expansion check and
    # not a rule about percent characters.
    assert percent_expansion_failure("default: %(default)s") is None
    assert percent_expansion_failure("run %(prog)s again") is None


def test_the_scan_reads_a_format_spec_not_just_the_literal_parts(tmp_path: Path) -> None:
    """The mutation arm, over the shape the real defect had.

    The percent that broke `sync_handover_bundle.py` is not in its source: it is produced by the
    format spec `.0%`. A scan that flattened only an f-string's literal parts would have read
    `permit deleting more than  of the mirror`, found nothing, and reported clean on the exact line
    this file exists for.
    """
    mutant = tmp_path / "mutant.py"
    mutant.write_text(
        "import argparse\n"
        "FRACTION = 0.05\n"
        "p = argparse.ArgumentParser()\n"
        'p.add_argument("--allow-prune", action="store_true",\n'
        '               help=f"permit deleting more than {FRACTION:.0%} of the mirror")\n',
        encoding="utf-8")
    tree = ast.parse(mutant.read_text(encoding="utf-8"))
    texts = [_static_text(kw.value)
             for node in ast.walk(tree) if isinstance(node, ast.Call)
             for kw in node.keywords if kw.arg == "help"]
    assert texts == ["permit deleting more than .0% of the mirror"], texts
    assert percent_expansion_failure(texts[0]) is not None, (
        "the pre-fix line must be convicted; if this passes, the scan cannot see the defect it was "
        "written for")


def test_the_repaired_tool_actually_prints_its_help() -> None:
    """The end-to-end control: the static check corresponds to what an interpreter does.

    `--help` is safe to run here and is not a discovery pattern over the repo — this repo has at
    least one script that acts at import time, so sweeping every module with `--help` would be a
    scan with side effects (`feedback_discovery_pattern_is_a_claim`).
    """
    script = ROOT / DEFECT_SITE
    assert script.exists(), f"{DEFECT_SITE} — the guard's subject moved; point it at the new path"
    proc = subprocess.run([sys.executable, str(script), "--help"],
                          capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert proc.returncode == 0, f"rc {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert DEFECT_SITE_RENDERS in proc.stdout, (
        f"expected {DEFECT_SITE_RENDERS!r} in the rendered help; got:\n{proc.stdout}")


@pytest.mark.parametrize("bad", ["100% of the tree", "%d files", "% o"])
def test_shapes_that_must_be_convicted(bad: str) -> None:
    assert percent_expansion_failure(bad) is not None, f"{bad!r} was not convicted"
