"""DEV-P4-36: the scratch-copy exclusion list, and the bound it exists to hold.

What went wrong
---------------
Three gates copy the whole repo into a scratch tree and mutate the copy. Each carried its own
hand-written `shutil.ignore_patterns(...)`, the three disagreed, and `f1_config/.wheel_cache/`
— 214 MB of pip cache, `.gitignore`d, read by nothing under test — was in none of them. One
full-gate run on 2026-08-13 wrote 11.3 GB of scratch (48 arms × 236 MB), filled the disk, and
died: pytest emitted mass `E`s from tmp_path creation and the shell could not write its own
output file. The suite's failure mode was indistinguishable from a wedged machine.

What this file pins
-------------------
* the list is DERIVED from `.gitignore`, not restated — so the next local-only tree is excluded
  on the day it is added to `.gitignore` rather than on the day a disk fills;
* the two trees that actually caused the wedge are in it, named;
* a real copy is bounded ABOVE (far below the 236 MB that broke) and BELOW (a copy that
  silently became empty would satisfy any ceiling — `feedback_zero_file_scan_is_error`);
* the ceiling is load-bearing: `.wheel_cache`'s measured size on disk alone would breach it, so
  the bound would have caught the defect rather than merely describing it;
* no whole-repo copy anywhere in the repo writes its own exclusion list again — an AST scan,
  because the defect was three lists drifting, and a fixed list is exactly what looks fine in
  review (`feedback_derive_from_every_producer`).

Offline, $0. The one real copy this file makes is ~34 MB and is removed with `tmp_path`.
"""

from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path

import pytest

from repo_copy import (COPY_CEILING_KB, COPY_EXCLUDE_NAMES, COPY_FLOOR_KB,
                       DYNAMIC_COPY_SOURCES, EXTRA_EXCLUDE_NAMES, LOCAL_ONLY_NAMES, ROOT,
                       SUBTREE_COPY_BUDGET_KB, SUBTREE_RUN_BUDGET_KB, copy_exclude)

# The two the wedge was made of, named rather than counted. `.wheel_cache` is the 214 MB, and
# `.state` is the runner's local bookkeeping — local-only by policy, and holding vpc/subnet ids
# that are redaction targets, so a scratch copy of it is a second-order hazard as well as a
# large one.
WEDGE_TREES = (".wheel_cache", ".state")

# Where the 214 MB lived. Read at run time, not pinned as a number: the cache is a cache and may
# legitimately be smaller or absent.
WHEEL_CACHE = ROOT / "f1_config" / ".wheel_cache"


def _kb(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) // 1024


def _py_files() -> list[Path]:
    skip = {".venv", ".venv-oracle", ".venv-baseline", "__pycache__", "evidence",
            "node_modules", ".pytest_cache", ".wheel_cache"}
    return sorted(p for p in ROOT.rglob("*.py")
                  if not any(part in skip for part in p.relative_to(ROOT).parts))


# ---------------------------------------------------------------------------
# the list
# ---------------------------------------------------------------------------

def test_the_list_is_derived_from_gitignore_and_nothing_is_dropped():
    """Every non-comment `.gitignore` entry contributes a pattern, and there are enough of them.

    The floor is against the derivation quietly reading nothing: an empty list makes
    `ignore_patterns()` exclude nothing at all, which is the defect this file is about, and it
    would raise no error anywhere.
    """
    lines = [l.strip() for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    entries = [l for l in lines if l and not l.startswith("#")]
    assert len(entries) >= 6, (
        f".gitignore names only {len(entries)} entries; the derivation has stopped reading the "
        "file it is derived from")
    for entry in entries:
        base = entry.rstrip("/").rsplit("/", 1)[-1]
        assert base in LOCAL_ONLY_NAMES, (
            f"{entry!r} is ignored by git but is not excluded from the scratch copy")
    assert set(COPY_EXCLUDE_NAMES) == set(LOCAL_ONLY_NAMES) | set(EXTRA_EXCLUDE_NAMES), (
        "COPY_EXCLUDE_NAMES has grown a member that is neither derived from .gitignore nor "
        "declared in EXTRA_EXCLUDE_NAMES with a reason")


@pytest.mark.parametrize("name", WEDGE_TREES)
def test_the_trees_that_caused_the_wedge_are_excluded(name):
    assert name in COPY_EXCLUDE_NAMES, (
        f"{name!r} is what DEV-P4-36 was made of; excluding it is the fix, not a nicety")


def test_the_patterns_match_the_real_directory_names_and_spare_the_sources():
    """Call the `ignore=` callable directly on a listing, so no copy is needed to know.

    `shutil.ignore_patterns` matches basenames with fnmatch, so a pattern that is right in
    spirit and wrong in shape (`f1_config/.wheel_cache` instead of `.wheel_cache`) excludes
    nothing. This arm is the difference between the list saying the right words and the list
    matching the right directories.
    """
    listing = [".wheel_cache", ".state", "evidence", ".venv-oracle", "__pycache__",
               "triage.csv", "oracle.py", "PREREGISTRATION.yaml", "results", "runner"]
    ignored = copy_exclude()(str(ROOT), listing)
    assert {".wheel_cache", ".state", "evidence", ".venv-oracle", "__pycache__"} <= ignored
    # And nothing a gate reads. `results` is only ever excluded per call, by the one caller
    # that does not read it.
    assert not ({"triage.csv", "oracle.py", "PREREGISTRATION.yaml", "results", "runner"}
                & ignored)
    assert "results" in copy_exclude("results")(str(ROOT), listing), \
        "the per-call extra must reach the callable, or test_corpus_gate's arms get 34 MB each"


# ---------------------------------------------------------------------------
# the bound
# ---------------------------------------------------------------------------

def test_a_scratch_copy_is_bounded_above_and_below(tmp_path, copy_repo):
    dst = copy_repo(tmp_path / "grx")
    size = _kb(dst)
    assert size <= COPY_CEILING_KB, (
        f"a scratch copy is {size} KB; the ceiling is {COPY_CEILING_KB} KB. 48 arms at this "
        "size is how DEV-P4-36 filled the disk — find what got copied, do not raise the bound")
    assert size >= COPY_FLOOR_KB, (
        f"a scratch copy is only {size} KB; an over-wide exclusion has emptied the tree, and "
        "every mutation arm would now fail for the wrong reason")
    # Named landmarks, because a size range is satisfiable by the wrong 34 MB.
    for rel in ("PREREGISTRATION.yaml", "lib/oracle.py", "claims/triage.csv",
                "corpora/verify_corpora.py", "build_v13_candidates.py"):
        assert (dst / rel).exists(), f"{rel} is missing from the scratch copy"
    for rel in ("f1_config/.wheel_cache", "evidence", "runner/.state", ".venv-oracle"):
        assert not (dst / rel).exists(), f"{rel} was copied into the scratch tree"


def test_the_ceiling_would_have_caught_the_defect():
    """The ceiling is load-bearing, and the proof does not require copying 214 MB again.

    `.wheel_cache`'s size is measured on disk and added to the bounded copy; if that sum does
    not breach the ceiling then the ceiling is decoration, not a guard.
    """
    if not WHEEL_CACHE.is_dir():
        pytest.skip(f"{WHEEL_CACHE.relative_to(ROOT)} has been cleaned; the arm's premise is "
                    "a real 214 MB cache on disk, and there is nothing honest to assert "
                    "without one")
    cache_kb = _kb(WHEEL_CACHE)
    assert cache_kb > 100_000, (
        f"{WHEEL_CACHE.relative_to(ROOT)} is {cache_kb} KB — smaller than the 214 MB that "
        "caused DEV-P4-36, so this arm no longer demonstrates the ceiling bites")
    assert COPY_FLOOR_KB + cache_kb > COPY_CEILING_KB, (
        "the wheel cache would fit under the ceiling, so the bound would not have caught the "
        "defect it was written for")


# ---------------------------------------------------------------------------
# the anti-drift arm
# ---------------------------------------------------------------------------

def _whole_repo_copy_lines(source: str) -> list[int]:
    """Line numbers of every `copytree(ROOT, …)` call, shared exclusion list or not."""
    out: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        if (fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")) != "copytree":
            continue
        if isinstance(node.args[0], ast.Name) and node.args[0].id == "ROOT":
            out.append(node.lineno)
    return out


def _hand_written_whole_repo_copies(source: str) -> list[int]:
    """Line numbers of `copytree(ROOT, …)` calls that do NOT get their `ignore=` from here.

    Two narrowings, each deliberate:

    * the first argument must be the bare name `ROOT`. A subtree copy — `copytree(ROOT / "lib",
      …)`, as `test_prereg_verifier.py` makes — cannot inherit the whole tree's caches by
      accident, which is what THIS rule is about.

      The first version of this docstring went on to say a subtree copy "names what it takes",
      as though naming settled it. It does not settle size: `test_amendment_gate.py` named
      `ROOT / "evidence"` and took 198,452 KB per arm, 26 arms, and this scan was written not to
      look. Subtree sources are bounded instead by `SUBTREE_COPY_BUDGET_KB` and the arms under
      "the subtree budget" below.
    * the offence is the `ignore=` expression, not the file it sits in. Keying on `copy_exclude`
      rather than exempting `repo_copy.py` by path means this guard reads its own source with the
      same rule as everyone else's (`feedback_self_scanning_guard`); the legitimate call passes
      the shared callable and is therefore not a hit for a reason, not by exception.
    """
    out: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        if (fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")) != "copytree":
            continue
        if not (isinstance(node.args[0], ast.Name) and node.args[0].id == "ROOT"):
            continue
        ignore = next((kw.value for kw in node.keywords if kw.arg == "ignore"), None)
        shared = (isinstance(ignore, ast.Call)
                  and (ignore.func.attr if isinstance(ignore.func, ast.Attribute)
                       else getattr(ignore.func, "id", "")) == "copy_exclude")
        if not shared:
            out.append(node.lineno)
    return out


def test_no_whole_repo_copy_writes_its_own_exclusion_list():
    offenders = [f"{p.relative_to(ROOT)}:{ln}" for p in _py_files()
                 for ln in _hand_written_whole_repo_copies(p.read_text(encoding="utf-8"))]
    assert not offenders, (
        "these copy the whole repo without the shared, .gitignore-derived exclusion list; use "
        "the `copy_repo` fixture:\n  " + "\n  ".join(offenders))


def test_the_scan_can_see_a_whole_repo_copy_at_all():
    """`feedback_vacuous_test_check`: the arm above passes trivially if the scan matches nothing.

    The samples are assembled here, so the detector is exercised on the exact source shapes it
    has to separate rather than on the hope that it can.
    """
    hand_written = ('shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns("evidence"))\n')
    assert _hand_written_whole_repo_copies(hand_written) == [1], \
        "the detector no longer matches a hand-written `copytree(ROOT, …, ignore=…)`"
    # No `ignore=` at all is the worst case of the same defect, and must also be a hit.
    assert _hand_written_whole_repo_copies("shutil.copytree(ROOT, dst)\n") == [1]
    # The shared callable is the one shape that is not a hit …
    assert _hand_written_whole_repo_copies(
        'shutil.copytree(ROOT, dst, ignore=copy_exclude("results"))\n') == []
    # … and a subtree copy is out of scope for THIS rule — it is bounded by the budget scan
    # below instead, which is the half that was missing when `ROOT / "evidence"` slipped past.
    assert _hand_written_whole_repo_copies('shutil.copytree(ROOT / "lib", dst)\n') == []
    assert _subtree_copy_sites('shutil.copytree(ROOT / "lib", dst)\n') == [(1, "lib")]


def test_the_one_legitimate_whole_repo_copy_is_where_it_is_supposed_to_be():
    """The converse of the scan: exactly one place makes the copy, and it is `repo_copy.py`.

    Without this, deleting the real call would make the scan above pass loudest of all.
    """
    sites = [p.relative_to(ROOT) for p in _py_files()
             if _whole_repo_copy_lines(p.read_text(encoding="utf-8"))]
    assert sites == [Path("claims") / "tests" / "repo_copy.py"], (
        f"the whole-repo copy should be made in exactly one module; found {sites}")


# ---------------------------------------------------------------------------
# the subtree budget — the half of the scan that `ROOT / "evidence"` slipped past
# ---------------------------------------------------------------------------

def _rel_under_root(node: ast.AST) -> str | None:
    """`"lib"` for `ROOT / "lib"`, `"a/b"` for `ROOT / "a" / "b"`, `None` for anything else.

    `None` covers both "not rooted at ROOT" and "not a literal", which the caller separates: a
    non-literal source cannot be measured from the source text and has to be declared instead.
    """
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
        if not (isinstance(cur.right, ast.Constant) and isinstance(cur.right.value, str)):
            return None
        parts.append(cur.right.value)
        cur = cur.left
    if isinstance(cur, ast.Name) and cur.id == "ROOT" and parts:
        return "/".join(reversed(parts))
    return None


def _subtree_copy_sites(source: str) -> list[tuple[int, str | None]]:
    """Every `copytree` whose first argument is NOT the bare `ROOT`, as (line, rel-or-None).

    The bare-`ROOT` case is the other scan's; everything else is a subtree copy whose source
    needs a bound, whether it is spelled as a literal or reached through a variable.
    """
    out: list[tuple[int, str | None]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        if (fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")) != "copytree":
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Name) and arg.id == "ROOT":
            continue
        out.append((node.lineno, _rel_under_root(arg)))
    return out


def _arms(source: str) -> int:
    """A lower bound on the arms in a file: its `def test_` count.

    A lower bound is the honest reading — parametrisation only multiplies it — and a bound that
    understates the arm count understates the scratch, so the budget arm below is conservative in
    the direction that matters.
    """
    return len(re.findall(r"^def test_", source, re.M))


def test_every_subtree_copy_source_is_registered_and_bounded():
    """A subtree copy must name a source someone has measured, and it must still fit.

    This is the guard that was missing. `copytree(ROOT / "evidence", …)` would fail here twice:
    `evidence` is not in the budget, and its 198,452 KB exceeds every ceiling in it.
    """
    unregistered: list[str] = []
    over: list[str] = []
    for p in _py_files():
        src = p.read_text(encoding="utf-8")
        for line, rel in _subtree_copy_sites(src):
            if rel is None:
                continue                      # declared instead; the next arm owns those
            where = f"{p.relative_to(ROOT)}:{line}"
            if rel not in SUBTREE_COPY_BUDGET_KB:
                unregistered.append(f"{where} copies {rel!r}")
                continue
            src_dir = ROOT / rel
            if not src_dir.is_dir():
                continue
            size = _kb(src_dir)
            if size > SUBTREE_COPY_BUDGET_KB[rel]:
                over.append(f"{where}: {rel} is {size} KB, ceiling "
                            f"{SUBTREE_COPY_BUDGET_KB[rel]} KB")
    assert not unregistered, (
        "these copy a subtree with no registered ceiling; add it to SUBTREE_COPY_BUDGET_KB with "
        "its measured size, or copy less:\n  " + "\n  ".join(unregistered))
    assert not over, (
        "these subtree sources have outgrown their ceiling; the copy is per arm, so this is how "
        "a disk fills:\n  " + "\n  ".join(over))


def test_the_per_file_scratch_arithmetic_still_fits():
    """Three individually reasonable ceilings, copied together, 56 times, is not reasonable.

    The ceilings above bound one source. This bounds what one FILE can write in a run, which is
    the number that actually filled the volume — 48 arms × 236 MB was every individual figure
    looking fine.
    """
    worst: list[str] = []
    for p in _py_files():
        src = p.read_text(encoding="utf-8")
        rels = {rel for _line, rel in _subtree_copy_sites(src) if rel}
        if not rels:
            continue
        per_arm = sum(SUBTREE_COPY_BUDGET_KB[r] for r in rels if r in SUBTREE_COPY_BUDGET_KB)
        total = per_arm * max(_arms(src), 1)
        if total > SUBTREE_RUN_BUDGET_KB:
            worst.append(f"{p.relative_to(ROOT)}: {sorted(rels)} × {_arms(src)} arms = "
                         f"{total} KB at the ceilings, budget {SUBTREE_RUN_BUDGET_KB} KB")
    assert not worst, (
        "at their registered ceilings these files would write more scratch in one run than the "
        "budget allows:\n  " + "\n  ".join(worst))


def test_the_budget_would_have_caught_the_evidence_copy():
    """The bound is load-bearing, and the proof does not require copying 198 MB again."""
    ev = ROOT / "evidence"
    if not ev.is_dir():
        pytest.skip("evidence/ is local-only and absent here; there is nothing honest to "
                    "measure the budget against")
    size = _kb(ev)
    assert "evidence" not in SUBTREE_COPY_BUDGET_KB, (
        "`evidence` has been given a ceiling; it is 198 MB of local-only archive and no arm "
        "should be copying it — the subset in claims/tests/evidence_subset.py is the way")
    assert size > max(SUBTREE_COPY_BUDGET_KB.values()), (
        f"evidence/ measures {size} KB, which fits under the largest registered ceiling "
        f"({max(SUBTREE_COPY_BUDGET_KB.values())} KB) — the budget would not have caught the "
        f"copy it was written for")


def test_nothing_copies_the_whole_evidence_tree_again():
    """The regression pin, named rather than implied by a size bound.

    `test_amendment_gate.py` did this for 26 arms behind a docstring that said it did not.
    """
    offenders = [f"{p.relative_to(ROOT)}:{line}" for p in _py_files()
                 for line, rel in _subtree_copy_sites(p.read_text(encoding="utf-8"))
                 if rel == "evidence" or (rel or "").startswith("evidence/")]
    assert not offenders, (
        "these copy the evidence archive into scratch; use copy_evidence_subset() from "
        "claims/tests/evidence_subset.py:\n  " + "\n  ".join(offenders))


def test_every_dynamic_copy_source_is_declared_and_still_there():
    """A source reached through a variable cannot be measured, so it is declared with a reason.

    Both directions: an undeclared dynamic copy is a hit, and a declaration whose file no longer
    holds one is stale — an exemption that exempts nothing reads as diligence.
    """
    found: set[str] = set()
    undeclared: list[str] = []
    for p in _py_files():
        rel_p = str(p.relative_to(ROOT))
        for line, rel in _subtree_copy_sites(p.read_text(encoding="utf-8")):
            if rel is not None:
                continue
            found.add(rel_p)
            if rel_p not in DYNAMIC_COPY_SOURCES:
                undeclared.append(f"{rel_p}:{line}")
    assert not undeclared, (
        "these copy a tree whose source is not a literal under ROOT, so nothing can measure it; "
        "declare it in DYNAMIC_COPY_SOURCES with what the source is:\n  "
        + "\n  ".join(undeclared))
    assert found == set(DYNAMIC_COPY_SOURCES), (
        f"DYNAMIC_COPY_SOURCES and the tree disagree:\n"
        f"  copies with a dynamic source: {sorted(found)}\n"
        f"  declared:                     {sorted(DYNAMIC_COPY_SOURCES)}")
    for path, reason in DYNAMIC_COPY_SOURCES.items():
        assert len(reason) > 40, f"{path}'s declaration says too little to be a reason: {reason!r}"


def test_the_subtree_scan_can_see_the_shapes_it_has_to_separate():
    """`feedback_vacuous_test_check`, again: the samples are assembled, not hoped for."""
    assert _subtree_copy_sites('shutil.copytree(ROOT / "evidence", dst)\n') == [(1, "evidence")]
    assert _subtree_copy_sites('shutil.copytree(ROOT / "a" / "b", dst)\n') == [(1, "a/b")]
    # A variable source is a hit with no measurable path, not a miss.
    assert _subtree_copy_sites("shutil.copytree(src, dst)\n") == [(1, None)]
    assert _subtree_copy_sites("shutil.copytree(ROOT / name, dst)\n") == [(1, None)]
    # The whole-repo copy belongs to the other scan and must not be double-counted here.
    assert _subtree_copy_sites("shutil.copytree(ROOT, dst)\n") == []
    # And the budget must be read from the same object the scan asserts against.
    assert SUBTREE_COPY_BUDGET_KB and all(v > 0 for v in SUBTREE_COPY_BUDGET_KB.values())


def test_the_python_scan_reads_this_project_and_not_a_venv():
    files = _py_files()
    assert 70 <= len(files) <= 200, (
        f"{len(files)} .py files scanned; expected the project tree. Far outside that range "
        "means a venv leaked in or the glob is mis-rooted")
    assert Path(__file__) in files, "the scan cannot see its own directory"
    assert not [p for p in files if "site-packages" in p.parts]


def test_shutil_is_still_the_thing_being_constrained():
    """If `ignore_patterns` ever stops returning a callable, every arm above is testing air."""
    fn = shutil.ignore_patterns("x")
    assert callable(fn) and fn("dir", ["x", "y"]) == {"x"}
