"""Every `args.<name>` a script reads must be a flag its parser actually defines.

Why this file exists
--------------------
`f5_redteam/04_policy_failure_modes.py` shipped with two reads of flags that do not exist:

    state = T.State.load(Path(args.state) if args.state else None)
    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)

`P.parser` defines exactly `--dry-run`, `--n`, `--run-id` and `--region`. There is no `--state`
and no `--evidence-root` anywhere in the project. The script's offline suite passed, and
`--dry-run` passed and printed a correct plan — and then the first live launch died on
`AttributeError: 'Namespace' object has no attribute 'state'` after the interlock had already
been cleared by hand.

Both gates were vacuous for this class of bug, for the same structural reason: **the dry-run
banner RETURNS from `main()` above those lines.** Everything a case does with AWS lives below the
`if args.dry_run:` block, so no amount of dry-running can reach an attribute error down there.
That is not a property of this one script — it is the shape of every case script in the project,
which means every one of them can carry the same defect and report clean under both gates.

So the check has to be static, and it has to run over the whole tree rather than the one script
that happened to fail. For each script this test:

1. collects every `args.<name>` read, via AST (a string search would trip over prose in the
   module docstrings, which discuss flags at length);
2. computes the flags actually available to it: the real `P.parser` dests, read from argparse
   rather than hardcoded, plus any `add_argument` the script itself makes;
3. asserts (1) is a subset of (2).

The parser dests are taken from a live `P.parser` call so that adding a flag to `lib/phase1.py`
does not require editing a list here — otherwise this test becomes the thing that goes stale.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import phase1 as P  # noqa: E402

# Case scripts and provisioners: everything that takes a command line and talks to AWS. Helper
# modules under lib/ are excluded because they do not own a parser; the ad-hoc analysis scripts
# (07a_compare_runs, 02b_bisect_verdict, ...) are INCLUDED — they take a command line too, and a
# nonexistent flag is exactly as fatal there.
GLOBS = ("f*/[0-9]*_*.py", "infra/[0-9]*_*.py")


def scripts() -> list[Path]:
    out: list[Path] = []
    for g in GLOBS:
        out.extend(sorted(ROOT.glob(g)))
    assert out, f"no scripts matched {GLOBS} under {ROOT} — this test would pass vacuously"
    return out


def base_dests() -> set[str]:
    """The flags `P.parser` gives every script, read from argparse itself."""
    ap = P.parser("TEST-CASE", "docstring for the parser under test")
    dests = {a.dest for a in ap._actions if a.dest != "help"}
    # A canary: if P.parser is ever refactored into something that returns an empty parser, this
    # test must fail loudly rather than silently allow nothing and flag every script.
    assert "dry_run" in dests and "n" in dests, f"P.parser looks wrong: {sorted(dests)}"
    return dests


def args_reads(tree: ast.AST) -> dict[str, int]:
    """`args.<name>` reads, mapped to the first line each appears on.

    Only `Name(id="args")` is followed. `self.args.x` or `other.args.x` would be a different
    object; none exist in this tree today, and treating them as parser flags would be wrong.
    """
    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "args"):
            found.setdefault(node.attr, node.lineno)
    return found


def local_dests(tree: ast.AST) -> set[str]:
    """Flags the script adds itself, by `dest=` or derived from the longest option string."""
    dests: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        explicit = next((kw.value.value for kw in node.keywords
                         if kw.arg == "dest" and isinstance(kw.value, ast.Constant)), None)
        if explicit:
            dests.add(str(explicit))
            continue
        opts = [a.value for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        for o in opts:
            dests.add(o.lstrip("-").replace("-", "_"))
    return dests


@pytest.mark.parametrize("path", scripts(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_args_attribute_is_a_flag_the_parser_defines(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    reads = args_reads(tree)
    if not reads:
        pytest.skip(f"{path.name} never reads args.<name>")
    allowed = base_dests() | local_dests(tree)
    unknown = {k: v for k, v in reads.items() if k not in allowed}
    assert not unknown, (
        f"{path.relative_to(ROOT)} reads flags that no parser defines: "
        + ", ".join(f"args.{k} (line {v})" for k, v in sorted(unknown.items()))
        + f"\navailable: {sorted(allowed)}"
        + "\nThis is fatal at runtime and INVISIBLE to --dry-run when the read sits below the"
          " dry-run banner's return.")


def test_the_check_is_not_vacuous_on_a_planted_bad_read() -> None:
    """Mutation check: a script reading a nonexistent flag must be caught.

    Without this, `args_reads` returning `{}` for every file — one bad `isinstance` away — would
    make the whole parametrised sweep pass while checking nothing.
    """
    src = (
        "import sys\n"
        "sys.path.insert(0, 'lib')\n"
        "import phase1 as P\n"
        "def main():\n"
        "    args = P.parser('X', 'd').parse_args()\n"
        "    if args.dry_run:\n"
        "        return 0\n"
        "    return open(args.no_such_flag)\n"
    )
    tree = ast.parse(src)
    reads = args_reads(tree)
    assert "no_such_flag" in reads, "the AST walk missed a planted args.<name> read"
    assert "dry_run" in reads, "the AST walk missed the legitimate read beside it"
    assert "no_such_flag" not in (base_dests() | local_dests(tree))
    assert "dry_run" in base_dests()


def test_a_locally_added_flag_is_accepted() -> None:
    """The allow-set must include the script's own add_argument calls, or every analysis script
    that defines a flag would be reported as broken and the sweep would be un-runnable."""
    tree = ast.parse(
        "ap.add_argument('--compare', action='store_true')\n"
        "ap.add_argument('-o', '--out-file', dest='outfile')\n"
        "x = args.compare\n"
        "y = args.outfile\n")
    assert {"compare", "outfile"} <= local_dests(tree)
    assert not (set(args_reads(tree)) - (base_dests() | local_dests(tree)))


def test_the_defect_that_motivated_this_file_would_now_be_caught() -> None:
    """Runs the real check against a copy of the fixed script with the old lines put back.

    Pins the actual regression rather than a paraphrase of it. A copy in a tmpdir is used because
    this repo is pushed by API and its working tree is ahead of git HEAD — nothing here may
    mutate a tracked file, even transiently.
    """
    real = ROOT / "f5_redteam" / "04_policy_failure_modes.py"
    src = real.read_text()
    # Asserted through the AST, not `"args.state" not in src`. The first draft of this line did
    # the text search and failed on the fix's own explanatory comment, which names the two flags
    # in prose. A comment is not a read; only the parse tree distinguishes them.
    assert "state" not in args_reads(ast.parse(src)), "the defect is back in the live file"
    broken = src.replace(
        "    state = T.State.load()\n",
        "    state = T.State.load(Path(args.state) if args.state else None)\n", 1)
    assert broken != src, "the anchor line moved; update this mutation check"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "04_policy_failure_modes.py"
        p.write_text(broken)
        tree = ast.parse(broken, filename=str(p))
        unknown = set(args_reads(tree)) - (base_dests() | local_dests(tree))
    assert unknown == {"state"}, f"expected the planted flag to be the only finding: {unknown}"


def test_the_live_script_actually_parses_and_imports() -> None:
    """`--dry-run` is not enough, but it must at least still work after the fix."""
    r = subprocess.run(
        [str(ROOT / ".venv-oracle" / "bin" / "python"),
         str(ROOT / "f5_redteam" / "04_policy_failure_modes.py"), "--dry-run"],
        cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "F5-4a dry run" in r.stdout
