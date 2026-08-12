#!/usr/bin/env python3
"""No case script may call one of this repo's `@property` attributes as a method.

Why this file exists
--------------------
`Checkpoint.n_done` is a property. `f2_determinism/03_score_harvest.py` wrote `cp.n_done()` in
four places, and on 2026-08-12 the third live attempt at a 900-call run died with

    TypeError: 'int' object is not callable

after creating its first probe policy — the only reason it cost minutes rather than the whole run
is that the line happened to sit early in the loop. Two of the four sites were inside guard
computations and one was `alpha_n` for F2-2's own verdict, so the same slip further down would
have spent the calls first.

The reason `--dry-run` did not catch it is the general fact worth writing down: **the dry run
returns before the live loop**, so it exercises the plan and the banner and nothing that touches a
collected trial (`feedback_dry_run_before_expensive_run`). A `--n 4` smoke does reach that code,
and is now the step before any full run — but a smoke costs real calls, and this check costs none.

Scope, honestly
---------------
This is a syntactic check, not a type checker. It finds `obj.name()` where `name` is a property on
one of this repo's own classes, which is the exact shape that failed. It cannot find the same
mistake behind an alias (`f = cp.n_done` then `f()`), and it does not try: a check that promises
more than it does is worse than one whose limit is stated. The property names are DERIVED from the
classes by introspection rather than listed, so a property added tomorrow is covered without
anyone remembering this file.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

# The library modules whose classes case scripts hold instances of. Introspected, not enumerated.
LIB_MODULES = ("checkpoint", "evidence", "oracle", "testbed", "arms", "stats", "phase1")

SKIP_DIRS = {".git", ".venv", ".venv-oracle", ".venv-baseline", "__pycache__", "node_modules",
             "evidence", ".pytest_cache"}


def _properties() -> dict[str, set[str]]:
    """`{property name: {"Class.attr", ...}}` over every class in LIB_MODULES.

    Keyed by the bare attribute name because the call site is `cp.n_done()` — the AST has the
    attribute, not the type. That makes the check name-based and therefore capable of a false
    positive if an unrelated object has a same-named METHOD. Handled by reporting the owners in
    the failure message, so a genuine collision is visible rather than mysterious, and by keeping
    the property set to this repo's own classes.
    """
    out: dict[str, set[str]] = {}
    for mod_name in LIB_MODULES:
        mod = importlib.import_module(mod_name)
        for cls_name, cls in vars(mod).items():
            if not isinstance(cls, type) or getattr(cls, "__module__", "") != mod_name:
                continue
            for attr, val in vars(cls).items():
                if isinstance(val, property):
                    out.setdefault(attr, set()).add(f"{mod_name}.{cls_name}.{attr}")
    return out


def _py_files() -> list[Path]:
    return [p for p in sorted(ROOT.rglob("*.py"))
            if not (SKIP_DIRS & set(p.relative_to(ROOT).parts))]


def test_no_property_is_called_as_a_method():
    props = _properties()
    assert "n_done" in props, \
        "the derivation found no Checkpoint.n_done — LIB_MODULES or the introspection is wrong, " \
        "and a check that derived an empty target set would pass over the whole repo"

    files = _py_files()
    assert len(files) > 50, f"only {len(files)} python file(s) scanned — a near-empty scan is an " \
                            f"error, not a pass (feedback_zero_file_scan_is_error)"

    offenders: list[str] = []
    for path in files:
        # This file names the bad shapes in its own prose and in its own assertions; scanning it
        # would report itself. Excluded by path, not by a comment marker, so the exclusion is
        # one file and cannot silently widen.
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in props and not node.args and not node.keywords):
                rel = path.relative_to(ROOT)
                owners = ", ".join(sorted(props[node.func.attr]))
                offenders.append(f"{rel}:{node.func.lineno}  .{node.func.attr}()  [{owners}]")

    assert not offenders, (
        f"{len(offenders)} property/ies called as a method — each raises TypeError at run time, "
        f"and a dry run does not reach the live loop where most of these sit:\n  "
        + "\n  ".join(offenders))


def test_the_check_would_have_caught_the_2026_08_12_slip():
    """The mutation arm: the scanner must flag the exact line that failed.

    Without this, `test_no_property_is_called_as_a_method` passes just as well against a scanner
    that finds nothing at all — the repo is clean now, so a green result proves nothing about
    whether the check works (`feedback_vacuous_test_check`).
    """
    props = _properties()
    tree = ast.parse("total = sum(cp.n_done() for cp in cps.values())\n")
    hits = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in props and not n.args and not n.keywords]
    assert len(hits) == 1, "the scanner must flag `cp.n_done()`"
    # And it must NOT flag the correct spelling, or it would be unsatisfiable.
    ok = ast.parse("total = sum(cp.n_done for cp in cps.values())\n")
    assert not [n for n in ast.walk(ok)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in props], "`cp.n_done` is the correct form and must pass"
