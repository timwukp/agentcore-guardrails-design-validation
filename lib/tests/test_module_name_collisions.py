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


def _expr_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level `NAME = <expression>` bindings, rendered as source text.

    The sibling of `_string_constants`, for the loader's SECOND argument. Three F7 scripts hold
    their target in `TRACES_PATH = ROOT / "infra" / "07_traces.py"` and pass the constant, while a
    fourth passes the expression inline; comparing the two spellings textually reported a
    conflict where there is none. Resolving one level of module-level binding is enough for every
    shape in the tree and keeps the comparison exact — an unresolvable target still compares as
    its own text, so the failure mode stays "told about a spelling" rather than "silently
    treated as equal".
    """
    out: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    out[t.id] = ast.unparse(node.value)
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
    "f3_efficacy/tests/test_score_label_join.py":
        "_load(stem, name) helper — the same shape as test_f3_helpers.py, adopted here when the "
        "file grew a second subject (08b's parent module) and one literal per call site became "
        "clearer than two hand-rolled loaders. Its OTHER loader call passes the literal "
        "'infra_verify' and is resolved by the registration scan above",
    "f3_efficacy/tests/test_log_surface_join.py":
        "_load(stem, name) helper — same shape again. The names it registers are the ones the "
        "08b subject itself uses, and 08b's own loader passes the module-level constant "
        "PARENT_MODULE_NAME, which the registration scan above does resolve and does check for "
        "collisions against lib/",
    "f5_redteam/tests/test_injection_tool_response.py":
        "_load(path, name) helper — same shape as the f3 and f8 ones, with the literal at each of "
        "its two call sites. The two keys it registers, 'grx_f5_05_injection_tool_response' and "
        "'grx_echo_handler_under_test', were grepped repo-wide on 2026-08-14 and each appears in "
        "this file only, so neither can be the name another script means",
    "f8_regional/tests/test_policy_engine_regions.py":
        "_load(stem, name) helper — the same shape as test_f8_helpers.py in the same directory. Its "
        "one key, 'f8_pe_regions', was grepped repo-wide on 2026-08-14 and appears in this file "
        "only. Note it does NOT carry the grx_ prefix the f5 keys use; that is a naming "
        "inconsistency and not a collision, since no other loader registers it",
    "lib/tests/test_stats_mutation.py":
        "f'_mutant_{name}' — generated per mutant, and prefixed so it cannot collide",
    "lib/tests/test_f7_metric_tables.py":
        "f'_mutant_{abs(hash(label))}' and '_control_metrics_module' — the same mutation-harness "
        "shape as test_stats_mutation.py: the names are generated per mutant, prefixed, and "
        "popped from sys.modules in a finally, so they cannot collide with a phase script's key. "
        "Its ONE fixed key, METRICS_MODULE_NAME, is a module-level constant and is resolved by "
        "the registration scan above; only the mutant call sites are unresolvable",
    "infra/tests/infra_by_path.py":
        "f'_infra_{stem}' — the infra scripts start with a digit so they cannot be imported "
        "by name at all; the prefix is asserted to be collision-proof by "
        "test_the_infra_loader_prefix_cannot_collide below, so this entry's reason is checked "
        "rather than merely written. Moved out of infra/tests/conftest.py on 2026-08-13: two "
        "test modules imported the loader with `from conftest import load_infra`, and the first "
        "combined run to collect f1_config/tests in the same process bound `conftest` to the "
        "WRONG directory's file — the per-directory-green/combined-red blindness this file "
        "documents, through the one basename every tests directory shares",
}

# How many unresolvable loader calls each of those files holds. Every entry of UNRESOLVABLE
# appears here exactly once; a file gaining a second by-path loader has to say so.
UNRESOLVABLE_CALLS = {
    "f3_efficacy/tests/test_f3_helpers.py": 1,
    "f8_regional/tests/test_f8_helpers.py": 1,
    "f3_efficacy/tests/test_score_label_join.py": 1,
    "f3_efficacy/tests/test_log_surface_join.py": 1,
    # 1, not 2: this file loads two subjects (the script and the echo handler), but both go through
    # the single `spec_from_file_location` inside `_load`, and it is LOADER CALLS that are counted
    # here. The f7 entry below is 2 because its mutation harness calls the loader directly twice.
    "f5_redteam/tests/test_injection_tool_response.py": 1,
    "f8_regional/tests/test_policy_engine_regions.py": 1,
    "lib/tests/test_stats_mutation.py": 1,
    "lib/tests/test_f7_metric_tables.py": 2,      # one per mutation call site
    "infra/tests/infra_by_path.py": 1,
}
assert set(UNRESOLVABLE_CALLS) == set(UNRESOLVABLE), (
    "UNRESOLVABLE and UNRESOLVABLE_CALLS name different files; a reason without a count, or a "
    "count without a reason, is half a record")

# The prefix `infra/tests/infra_by_path.py` builds its module names with. Duplicated here on purpose:
# the assertion below is only meaningful if this test states the invariant independently of the
# code under test, so a change to the prefix fails here instead of silently redefining the claim.
INFRA_LOADER_PREFIX = "_infra_"


def _unresolvable_calls_by_file() -> dict[str, int]:
    """How many loader calls per file register a name this scan cannot read. Counted, not capped.

    Separate from the file SET asserted above: a file can hold more than one such call, and the
    count is the thing that must not drift. `test_f7_metric_tables.py` holds two (one per
    mutation call site) and every other listed file holds one.
    """
    out: dict[str, int] = {}
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        consts = _string_constants(tree)
        for node in _loader_calls(tree):
            arg = node.args[0]
            ok = (isinstance(arg, ast.Constant) and isinstance(arg.value, str)) or (
                isinstance(arg, ast.Name) and arg.id in consts)
            if not ok:
                key = str(path.relative_to(ROOT))
                out[key] = out.get(key, 0) + 1
    return out


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
    # The ceiling exists to catch ONE failure: a venv or vendored tree leaking back into the scan.
    # `.venv-oracle` alone holds 2,466 .py files, so any ceiling well under a thousand detects that
    # with room to spare. It was 200 against a tree of 78, and on 2026-08-14 the project reached 206
    # and the gate went red — on legitimate growth, having caught nothing. A bound set just above the
    # current count goes red every time a test file is added, which teaches whoever hits it to raise
    # the number without reading why it is there; that is strictly worse than a loose bound, because
    # the tripwire is eventually bumped past the leak it was meant to catch. Set with a real margin
    # instead, and it fails only for the reason in the docstring.
    assert 70 <= len(files) <= 900, (
        f"{len(files)} .py files scanned; the project tree held 206 on 2026-08-14 and a venv holds "
        f"~2,466. A count in the thousands means a venv or vendored tree is being read.")
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
    # The blind spots are counted PER CALL, not per file. `len(UNRESOLVABLE)` was the earlier
    # form and it silently assumed one unresolvable call per listed file; when
    # `test_f7_metric_tables.py` grew a second mutation call site that assumption became a
    # tolerance one call wide, which is exactly the "at most N" shape this test's own docstring
    # rejects. `UNRESOLVABLE_CALLS` states the number for each file and the total is derived.
    per_file = _unresolvable_calls_by_file()
    assert per_file == UNRESOLVABLE_CALLS, (
        "the number of statically-unreadable loader calls per file has changed.\n"
        f"  now:        {per_file}\n"
        f"  documented: {UNRESOLVABLE_CALLS}")
    assert total - resolvable == sum(UNRESOLVABLE_CALLS.values()), (
        total, resolvable, sum(UNRESOLVABLE_CALLS.values()))
    assert "redact" in importable_names(), (
        "lib/redact.py is the module the original collision was against; if it is gone "
        "this gate's own premise needs re-checking")


def test_a_shared_loader_name_always_points_at_the_same_source():
    """Two scripts may share a `sys.modules` key only if they load the SAME file under it.

    The hazard this whole gate is about is a name resolving to someone else's module. A name
    registered twice for one path is harmless — `grx_infra_06_verify` is deliberately shared by
    `f1_config/04_update_revalidation.py` and `f4_modes/01_truth_table.py`, and both mean
    `infra/06_verify.py`, so the second loader finds the first's object and that is the point of
    borrowing one definition of "the testbed is intact". A name registered twice for two
    DIFFERENT paths is the original defect wearing a different file name, and until this test
    existed the gate could not tell the two cases apart: it only compared registered names with
    `importable_names()`, so a duplicate among the loaders themselves passed unread.

    The comparison is on the unparsed target expression rather than a resolved filesystem path.
    That is deliberate: rendering `ROOT / "infra" / "06_verify.py"` requires interpreting the
    expression, and an interpreter that silently failed on a shape it did not know would report
    "no duplicates" for the wrong reason. Textual equality can only err by flagging one file
    spelled two ways, which is a thing worth being told about.
    """
    by_name: dict[str, set[str]] = {}
    sites: dict[str, list[str]] = {}
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        consts = _string_constants(tree)
        for node in _loader_calls(tree):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                name = arg.value
            elif isinstance(arg, ast.Name) and arg.id in consts:
                name = consts[arg.id]
            else:
                continue                     # counted as a blind spot by the test above
            if len(node.args) > 1:
                raw = node.args[1]
                paths = _expr_constants(tree)
                target = (paths.get(raw.id, raw.id) if isinstance(raw, ast.Name)
                          else ast.unparse(raw))
            else:
                target = "<no target arg>"
            by_name.setdefault(name, set()).add(target)
            sites.setdefault(name, []).append(
                f"{path.relative_to(ROOT)}:{node.lineno} -> {target}")

    conflicting = {n: sorted(t) for n, t in by_name.items() if len(t) > 1}
    assert not conflicting, (
        "one sys.modules key is used for more than one source file; whichever script loads "
        "second silently gets the first one's module object.\n"
        + "\n".join(f"  {n}:\n    " + "\n    ".join(sites[n]) for n in sorted(conflicting)))

    # The premise: at least one name IS shared, so the test is exercising the shared-key path
    # rather than passing because every key happens to be unique.
    shared = sorted(n for n, v in sites.items() if len(v) > 1)
    assert shared, (
        "no loader name is registered by two files any more, so this test no longer covers the "
        "case it was written for; drop it or re-derive the premise")


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
    """`infra/tests/infra_by_path.py`'s reason in UNRESOLVABLE, checked instead of trusted.

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
        f"which is the prefix infra/tests/infra_by_path.py registers its by-path modules under. "
        f"Its UNRESOLVABLE entry claims the prefix cannot collide, and it now can.")

    src = (ROOT / "infra" / "tests" / "infra_by_path.py").read_text(encoding="utf-8")
    assert f'f"{INFRA_LOADER_PREFIX}{{stem}}"' in src, (
        f"infra/tests/infra_by_path.py no longer builds its module name as "
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
