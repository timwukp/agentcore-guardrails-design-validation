#!/usr/bin/env python3
"""No by-path module loader may register a name that `lib/` already owns.

Why this gate exists
--------------------
Top-level scripts (`check_redaction.py`, `f3_efficacy/01_content_filter.py`, …) are not
importable package members, so the test suites load them by path with
`importlib.util.spec_from_file_location(name, path)` and register them in `sys.modules`
under `name`. That name is free-form, and for a long time nothing in the tree competed for
it.

Then `lib/redact.py` was added, and `claims/tests/test_redaction_gate.py` was already
loading `check_redaction.py` under the name `"redact"`. Two failures followed from one
line:

1. Consumers of the real module — `lib/checkpoint.py`, `lib/phase1.py`,
   `lib/tests/test_redact.py` — resolved `import redact` to the by-path stub, because
   `sys.modules` is consulted before `sys.path`.
2. `check_redaction.py` itself does `import redact as _redact`, and the loader registers
   the module *before* calling `exec_module`, so that import bound the half-initialized
   module that was mid-load — a module importing a stub of a different file under its own
   subject's name.

Each suite passed in isolation. The combined run failed with `AttributeError: module
'redact' has no attribute 'mask_text'` about twenty times, and the eventual symptom named
neither file responsible. That is the signature of a defect that a per-directory test run
structurally cannot see, which is why it gets a static gate rather than a promise to
remember.

Why static rather than dynamic
------------------------------
The dynamic version of this check is "run every suite in one process", which the verify
script already does — but it only detects a collision that has *already* been introduced
and that happens to produce an AttributeError. A loader squatting `stats` or `oracle`
under a name whose attributes happen not to be touched would pass a combined run and
silently substitute a different module's behaviour into whatever read it. The name space
is a property of the source, so it is asserted against the source.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIB = ROOT / "lib"

# Registered names that are allowed to equal an importable module name — currently none.
# Kept as an explicit empty set rather than omitted, so a future genuine exception is a
# visible edit with a reason beside it instead of a relaxed assertion.
ALLOWED_COLLISIONS: dict[str, str] = {}


def _py_files() -> list[Path]:
    # `p.parts` never equals ".venv": the venvs are `.venv-oracle` and `.venv-baseline`, so an
    # equality test let site-packages in and the scan read 1,272 files instead of 78 — which
    # made the non-empty floor below pass on the wrong tree entirely. Prefix match, and the
    # floor is now tight enough to notice if it ever widens again.
    return sorted(
        p for p in ROOT.rglob("*.py")
        if not any(part.startswith(".venv") for part in p.parts)
        and "__pycache__" not in p.parts
    )


def importable_names() -> set[str]:
    """Every top-level module name reachable by `import <name>` under pytest.

    Two directories, for two different reasons.

    `lib/` is inserted onto `sys.path` by every case script and every conftest, so its stems
    are owned names for the whole process — not just for the module that inserted them.

    The repo root joined that set when `conftest.py` was added there. pytest inserts the
    rootdir of a conftest into `sys.path` under the default `prepend` import mode, so
    `check_redaction`, `verify_prereg`, `estimate_cost`, `build_v13_candidates` and
    `check_amendment_readiness` became importable top-level names — and therefore squattable
    — without any of them moving. That is exactly the mechanism this gate was written
    against: `lib/redact.py` did not collide with anything on the day it was written either.
    The root's stems are checked here rather than after the next collision.

    (Verified at the time: no registered loader name matched a root stem, and no root stem
    matched a lib stem. This function widens what a FUTURE loader may not claim.)
    """
    lib = {p.stem for p in LIB.glob("*.py") if p.stem != "__init__"}
    root = {p.stem for p in ROOT.glob("*.py") if p.stem not in {"__init__", "conftest"}}
    return lib | root


def _loader_calls(tree: ast.AST) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        nm = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if nm == "spec_from_file_location" and node.args:
            out.append(node)
    return out


def _string_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, so a name held in a constant is still visible.

    Without this, hoisting the name into a well-documented constant — which is exactly what
    the fix to the original collision did — would make the loader invisible to this gate and
    silently reduce its coverage. A gate that rewards inlining over documenting is the wrong
    incentive, so the resolution is done here instead.
    """
    out: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            val = node.value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                for t in targets:
                    if isinstance(t, ast.Name):
                        out[t.id] = val.value
    return out


# Files whose loader name cannot be resolved statically, each with the reason. Listed rather
# than absorbed into a tolerance count: "3 unresolvable" says nothing about whether the third
# one is a new blind spot, and per feedback_prose_is_not_verified the count is derived from
# this table rather than written beside it.
UNRESOLVABLE = {
    "f3_efficacy/tests/test_f3_helpers.py":
        "_load(stem, name) helper — the literal is at each call site, not at the loader",
    "f8_regional/tests/test_f8_helpers.py":
        "_load(stem, name) helper — same shape as the f3 one",
    "lib/tests/test_stats_mutation.py":
        "f'_mutant_{name}' — generated per mutant, and prefixed so it cannot collide",
    "infra/tests/conftest.py":
        "f'_infra_{stem}' — the infra scripts start with a digit so they cannot be imported "
        "by name at all; the prefix is asserted to be collision-proof by "
        "test_the_infra_loader_prefix_cannot_collide below, so this entry's reason is checked "
        "rather than merely written",
}

# The prefix `infra/tests/conftest.py` builds its module names with. Duplicated here on purpose:
# the assertion below is only meaningful if this test states the invariant independently of the
# code under test, so a change to the prefix fails here instead of silently redefining the claim.
INFRA_LOADER_PREFIX = "_infra_"


def loader_registrations() -> list[tuple[Path, int, str]]:
    """Every statically-resolvable `spec_from_file_location(<name>, …)`, with file and line.

    Names given as a string literal or as a module-level string constant are resolved. A name
    that is a parameter or an f-string cannot be; those files are enumerated in
    `UNRESOLVABLE` and asserted against, so the unresolvable case is reported rather than
    quietly skipped.
    """
    out: list[tuple[Path, int, str]] = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        consts = _string_constants(tree)
        for node in _loader_calls(tree):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append((path, node.lineno, arg.value))
            elif isinstance(arg, ast.Name) and arg.id in consts:
                out.append((path, node.lineno, consts[arg.id]))
    return out


# ------------------------------------------------------------------ the gate itself

def test_no_by_path_loader_registers_a_name_that_lib_owns():
    owned = importable_names()
    bad = [
        (p.relative_to(ROOT), ln, nm)
        for p, ln, nm in loader_registrations()
        if nm in owned and nm not in ALLOWED_COLLISIONS
    ]
    assert not bad, (
        "these loaders register a sys.modules name that also names a real module in lib/, "
        "so `import <name>` resolves to the by-path module for the rest of the process:\n"
        + "\n".join(f"  {p}:{ln} registers {nm!r} (lib/{nm}.py exists)" for p, ln, nm in bad)
        + "\nRename the registered name (the subject's filename is a safe choice); do not "
          "rename lib/."
    )


def test_the_scan_reads_the_project_tree_and_not_the_venvs():
    """A scan that reads the wrong tree passes loudest of all.

    The first version of this file tested `".venv" not in p.parts`, which never matches
    `.venv-oracle` / `.venv-baseline`, so it read 1,272 files of site-packages and the
    non-empty floor below was satisfied by dependencies rather than by this project. Both
    bounds are therefore asserted: a floor against a truncated or mis-rooted glob, and a
    CEILING against the venvs leaking back in (feedback_zero_file_scan_is_error, and its
    inverse — a scan that reads too much is just as blind).
    """
    files = _py_files()
    assert 70 <= len(files) <= 200, (
        f"{len(files)} .py files scanned; expected the project tree (78 at the time of "
        "writing). Far above that range means a venv or vendored tree is being read.")
    assert not [p for p in files if "site-packages" in p.parts], \
        "site-packages reached the scan; the venv exclusion is broken again"


def test_every_loader_call_is_either_resolvable_or_listed_as_unresolvable():
    """A gate that silently skips what it cannot parse is the vacuous-test defect.

    Three loaders build their `sys.modules` name at run time: two `_load(stem, name)`
    helpers whose literals sit at the call sites, and the stats mutation harness's
    `f"_mutant_{name}"`. Each is named in `UNRESOLVABLE` with its reason, and the count is
    DERIVED from that table rather than written as a tolerance — per
    feedback_prose_is_not_verified, "at most 3 unresolvable" would not say whether the third
    is the known helper or a new blind spot.
    """
    resolvable = len(loader_registrations())
    total = 0
    unresolved_files: set[str] = set()
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        consts = _string_constants(tree)
        for node in _loader_calls(tree):
            total += 1
            arg = node.args[0]
            ok = (isinstance(arg, ast.Constant) and isinstance(arg.value, str)) or (
                isinstance(arg, ast.Name) and arg.id in consts)
            if not ok:
                unresolved_files.add(str(path.relative_to(ROOT)))

    assert total >= 12, (
        f"found only {total} by-path loader call(s); the gate has stopped matching the call "
        "shape it is written against, so it is no longer checking anything")
    assert unresolved_files == set(UNRESOLVABLE), (
        "the set of loaders whose registered name cannot be read statically has changed.\n"
        f"  now unresolvable: {sorted(unresolved_files)}\n"
        f"  documented:       {sorted(UNRESOLVABLE)}\n"
        "Pass a literal or a module-level string constant, or add the file to UNRESOLVABLE "
        "with a reason why its name cannot collide.")
    assert total - resolvable == len(UNRESOLVABLE), (total, resolvable, len(UNRESOLVABLE))
    assert "redact" in importable_names(), (
        "lib/redact.py is the module the original collision was against; if it is gone "
        "this gate's own premise needs re-checking")


def test_the_repo_root_is_part_of_the_owned_name_space():
    """Adding `conftest.py` at the root made every root script an importable top-level name.

    pytest prepends a conftest's rootdir to `sys.path` under the default `prepend` import
    mode. Before the root conftest existed, `check_redaction` and its four siblings were
    plain scripts that nothing could `import` — so a by-path loader registering the name
    `estimate_cost` would have been harmless. It no longer is.

    Asserted as a property of the mechanism rather than left implicit in
    `importable_names()`, because the widening is invisible: nothing failed on the day the
    conftest landed, and nothing would fail on the day a loader claimed one of these names
    either — until two suites shared a process, which is precisely how the original
    `redact` collision hid.
    """
    owned = importable_names()
    assert (ROOT / "conftest.py").is_file(), (
        "the root conftest is gone; if it was removed deliberately, the root's stems are no "
        "longer on sys.path under pytest and this arm's premise needs re-checking")
    root_stems = {p.stem for p in ROOT.glob("*.py")} - {"conftest"}
    assert root_stems <= owned, sorted(root_stems - owned)
    # The five that existed when this was written. A tripwire, not a constraint: a new root
    # script is fine and simply widens the set — but it should widen it visibly, since the
    # whole point is that the name space grew once without anyone noticing.
    assert {"check_redaction", "verify_prereg", "estimate_cost", "build_v13_candidates",
            "check_amendment_readiness"} <= root_stems, sorted(root_stems)


def test_the_check_redaction_loader_no_longer_squats_the_redact_name():
    """The specific regression, pinned by name.

    The general assertion above would catch a re-introduction, but only while `lib/redact.py`
    exists. This arm states the historical fact directly so the reason survives even if the
    general gate is ever narrowed.
    """
    src = (ROOT / "claims" / "tests" / "test_redaction_gate.py").read_text(encoding="utf-8")
    names = [
        nm for p, _ln, nm in loader_registrations()
        if p.name == "test_redaction_gate.py"
    ]
    assert names, "the loader in test_redaction_gate.py disappeared; this arm is now blind"
    assert "redact" not in names, (
        "test_redaction_gate.py is again registering check_redaction.py as 'redact', which "
        "shadows lib/redact.py for every consumer in the process")
    assert "check_redaction" in src, "the loader no longer names its subject"


def test_the_infra_loader_prefix_cannot_collide():
    """`infra/tests/conftest.py`'s reason in UNRESOLVABLE, checked instead of trusted.

    That entry claims the `_infra_` prefix "cannot collide". A reason written in a table is
    prose, and prose is not verified (feedback_prose_is_not_verified) — so the claim is
    discharged here in both directions:

    1. No importable name in the owned space starts with the prefix, and none could: `lib/` and
       the repo root are globbed for `*.py`, and a module whose stem began with an underscore
       would be a private module nothing imports by that name. Asserted over the REAL name set,
       so a future `lib/_infra_foo.py` fails here rather than shadowing a test's module.
    2. The prefix is actually the one the loader uses. Read out of the source, because an
       invariant asserted against a constant this file defines alone would hold no matter what
       the conftest did — the vacuous-test shape (feedback_vacuous_test_check).

    The prefix matters because these are the only by-path loads of modules that CREATE AND
    DELETE AWS resources. A name collision there does not produce a wrong number; it produces a
    `99_teardown` that is some other module.
    """
    owned = importable_names()
    squatters = sorted(n for n in owned if n.startswith(INFRA_LOADER_PREFIX))
    assert not squatters, (
        f"{squatters} are importable top-level names beginning with {INFRA_LOADER_PREFIX!r}, "
        f"which is the prefix infra/tests/conftest.py registers its by-path modules under. Its "
        f"UNRESOLVABLE entry claims the prefix cannot collide, and it now can.")

    src = (ROOT / "infra" / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert f'f"{INFRA_LOADER_PREFIX}{{stem}}"' in src, (
        f"infra/tests/conftest.py no longer builds its module name as "
        f"f'{INFRA_LOADER_PREFIX}{{stem}}'. Either the prefix changed — in which case "
        f"INFRA_LOADER_PREFIX here and the UNRESOLVABLE reason must change with it — or the "
        f"name became statically resolvable, in which case remove the UNRESOLVABLE entry so "
        f"the general gate covers it.")

    # And the loads are real: infra/ holds the digit-prefixed scripts that make by-path loading
    # unavoidable in the first place. If that stopped being true the exemption should go.
    digit_led = sorted(p.name for p in (ROOT / "infra").glob("*.py")
                       if p.name[0].isdigit())
    assert len(digit_led) >= 8, (
        f"only {digit_led} in infra/ start with a digit; by-path loading is the workaround for "
        f"exactly that, so an exemption for it needs the premise to still hold")
