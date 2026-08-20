"""The scope rule that eleven repo-wide scanners depend on, and the guard that it stays one rule.

Two directions of failure, and this project has now hit both:

  * TOO NARROW — a scan that reads almost nothing reports clean over the whole repo. Every
    scanner already guarded this with a floor, and `scan_scope.py_files` now owns the floor.
  * TOO WIDE — a scan that reads a virtualenv reports findings in third-party code. Nothing
    guarded this. On 2026-08-15 a third virtualenv (`.venv-figs`, matplotlib for the whitepaper
    figures) appeared and two scanners reported 16 property-called-as-method findings in
    matplotlib and PIL. A floor cannot see this, because reading more files never trips a floor.

The second direction is what this file is mainly for.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_scope import (ROOT, SKIP_DIR_NAMES, SKIP_DIR_PREFIXES,  # noqa: E402
                        out_of_scope, py_files, walk_in_scope)


def test_every_virtualenv_actually_on_this_disk_is_out_of_scope():
    """Not a hypothetical: the real directories, whatever they are called today.

    `.gitignore` line 26 spells the family as `.venv-*/`, which is how both pushers already
    exclude them. This asserts the SCANNERS agree with the pushers, which is precisely what was
    untrue on 2026-08-15.
    """
    venvs = [p for p in ROOT.iterdir() if p.is_dir() and p.name.startswith(".venv")]
    assert len(venvs) >= 2, (
        f"only {len(venvs)} virtualenv(s) found at the repo root — this test would pass by having "
        f"nothing to check. The repo has carried at least .venv-oracle and .venv-baseline since "
        f"2026-08-10.")
    for v in venvs:
        assert out_of_scope(Path(v.name) / "lib" / "python3.12" / "site-packages" / "x.py"), \
            f"{v.name} is IN scope — a scanner will report findings in third-party source"


def test_a_virtualenv_that_does_not_exist_yet_is_out_of_scope():
    """The next venv, whatever it is called.

    The name is assembled from pieces rather than written out, so this file cannot be found by a
    scan looking for its own fixture, and so the assertion is about the RULE rather than about a
    string someone remembered to add (`feedback_self_scanning_guard`).
    """
    future = ".venv" + "-" + "somethingnobodyhaschosenyet"
    assert future not in SKIP_DIR_NAMES, \
        "the fixture accidentally names a real skip entry, so this test proves nothing"
    assert out_of_scope(Path(future) / "lib" / "mod.py"), \
        "a new virtualenv is in scope — the rule has stopped being a prefix rule"


def test_the_repos_own_source_is_in_scope():
    """The other direction, on named files. A rule that excludes everything also passes the
    two tests above."""
    for rel in ("lib/phase1.py", "census.py", "tools/whitepaper_figures.py",
                "runner/merge_evidence.py", "f3_efficacy/00_guardrails.py"):
        assert not out_of_scope(Path(rel)), f"{rel} is out of scope — the rule is too wide"
        assert (ROOT / rel).is_file(), \
            f"{rel} does not exist, so its in-scope assertion above is vacuous"


def test_py_files_reads_the_repo_and_nothing_else():
    files = py_files()
    rels = [p.relative_to(ROOT) for p in files]
    assert not [r for r in rels if any(part.startswith(".venv") for part in r.parts)]
    assert not [r for r in rels if "site-packages" in r.parts]
    # A ceiling as well as a floor. 773 files were in the tree on 2026-08-15 and roughly 400 of
    # them are .py; `.venv-figs` alone holds over 1,000, so any accidental venv read blows past
    # this long before it could be mistaken for growth.
    assert 100 < len(files) < 900, \
        f"{len(files)} python files in scope — outside the band this repo has ever occupied"


def test_walk_in_scope_prunes_rather_than_filters_and_agrees_with_py_files():
    """`walk_in_scope` exists only to be cheap, so its correctness is asserted against the slow path.

    It prunes directories as it descends instead of filtering afterwards, and pruning is the kind of
    optimisation that changes the answer: prune with the wrong relative path and the whole tree comes
    back, including every `.venv-*`. That failure is quiet in its first caller — the derived suffix set
    in `claims/tests/test_cited_paths_exist.py` would simply widen, admitting `.pyi`/`.so`/`.dist-info`
    and with them whatever those make look like a citable path. So the walk is cross-checked against
    `py_files()`, which reaches the same files by the filtered route, and the two must agree exactly.
    """
    walked = {p for p in walk_in_scope() if p.suffix == ".py"}
    assert walked == set(py_files()), (
        "walk_in_scope() and py_files() disagree on this repo's own python files; "
        f"walk-only={sorted(str(p.relative_to(ROOT)) for p in walked - set(py_files()))[:5]}, "
        f"filter-only={sorted(str(p.relative_to(ROOT)) for p in set(py_files()) - walked)[:5]}")

    # And the direction the equality above cannot see: py_files() is itself pruned by nothing, so if
    # both routes broke together this is what still notices.
    for p in walk_in_scope():
        rel = p.relative_to(ROOT)
        assert not out_of_scope(rel), f"walk_in_scope yielded an out-of-scope path: {rel}"


def test_no_scanner_carries_its_own_virtualenv_name_list():
    """The producer-side guard. Four scanners each kept a private set of venv names; the lesson
    had been learned once, in `test_module_name_collisions.py`, and never propagated
    (`feedback_fix_producer_not_janitor`). This fails if a fifth copy appears.

    Read from the AST: a set/list/tuple/dict literal holding TWO OR MORE strings from the venv
    family. Two is the threshold and it is the whole discrimination — one name is a probe (a test
    asserting that `.venv-oracle` specifically is excluded from a scratch copy is naming a real
    directory as its subject, which is correct and which four sites legitimately do), while two or
    more is an attempt to enumerate a family that a prefix already covers, and it is the
    enumeration that goes stale when the third member arrives.

    `scan_scope.py` is excluded by path because it is where the family is defined.
    """
    prefix = SKIP_DIR_PREFIXES[0]
    offenders = []
    for path in py_files():
        if path.name in ("scan_scope.py", Path(__file__).name):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            elts = []
            if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                elts = node.elts
            elif isinstance(node, ast.Dict):
                elts = [k for k in node.keys if k is not None]
            named = sorted({e.value for e in elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                            and e.value.startswith(prefix)})
            if len(named) >= 2:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}  {named}")
    assert not offenders, (
        "a scanner enumerates the virtualenv family by name instead of importing scan_scope. A "
        "list of names cannot notice a new name — that is DEV-P4-41 and DEV-P4-42, twice in one "
        "week:\n  " + "\n  ".join(offenders))
