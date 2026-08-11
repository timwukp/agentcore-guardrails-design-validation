#!/usr/bin/env python3
"""Mutation run for the root `conftest.py` write guard — proof that the arms can fail.

Why this file exists
--------------------
`test_write_guard.py` has 15 passing arms over a guard that had just published a false
accusation against 147 innocent tests (DEVIATIONS.md/DEV-P1-19). A passing suite over a guard
with that history is worth nothing until each arm is shown to be load-bearing, and the first
run of this harness proved the point: **two mutants survived**. One was a real gap — the
per-test fixture's tree scope, which is the exact defect fixed that same session and which no
arm pinned — and one was inert.

Why it lives in the tree rather than in /tmp
--------------------------------------------
The first version of this harness was a shell script in `/tmp`. Its result — "8 killed, 2
survived" — was written into DEV-P1-19 as a measured number, and nothing in the repository
could reproduce it. That is `feedback_prose_is_not_verified` exactly: a number in a rationale
is unchecked. Running it under pytest also puts it behind `verify_phase0.sh`, so an edit to
the guard that neuters an arm reds a gate rather than waiting for someone to remember a
script.

Why the live conftest.py is never touched
-----------------------------------------
The shell version mutated `conftest.py` in place and restored it from a backup on an `EXIT`
trap. A kill -9, a full disk, or a crash inside the trap would have left a deliberately
broken guard in the tree, and the guard is the thing that protects the live evidence trees
from the test suite. Here each mutant is applied to a **copy** written into the sandbox, so
the real file is opened read-only and the failure mode does not exist.

Reading the table
-----------------
* `Mutant` — a real mutation. Surviving is a test-suite defect and this file fails, naming it.
* `Inert` — a mutation that provably cannot change any verdict. It is still applied and run,
  because "provably inert" is a claim about the code that can expire; if it ever DIES, that
  claim has to be re-argued rather than banked as a kill. Scoring inert mutants as kills is
  how a mutation table gets a number that is not evidence in either direction (the same class
  as DEV-P1-18's M3).

Run directly for the report:
    python3 -m pytest lib/tests/test_write_guard_mutation.py -q
"""

from __future__ import annotations

import hashlib
import shutil
import site
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[2]
CONFTEST = ROOT / "conftest.py"
ARMS = Path(__file__).resolve().parent / "test_write_guard.py"

# Taken at import, before any mutant is applied, and compared again at the end. This is the
# whole of the safety argument for mutating a file that guards the live evidence trees.
_LIVE_SHA = hashlib.sha256(CONFTEST.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Mutant:
    """One deliberate defect in the guard, and the claim it attacks."""
    mid: str
    target: str                 # exact source substring, must appear exactly once
    replacement: str
    claim: str                  # the DEV-P1-19 claim this mutation falsifies
    inert: bool = False
    # Arms that MUST fail under this mutation. Empty means "at least one, any arm" — used where
    # naming arms would just restate the suite. Where it is populated, the harness checks the
    # named arm specifically, so a mutant killed only by an unrelated arm is not banked as a
    # kill for the claim it was written against.
    killers: tuple[str, ...] = field(default=())


MUTANTS: list[Mutant] = [
    Mutant(
        "M1-no-audit-channel",
        '        _WRITES.append((_CURRENT or "<no test running>", event, full))',
        "        pass",
        "Authorship is established by an audit hook, not inferred from a diff. Deleting the "
        "recording leaves the single-channel guard that convicted 147 innocent tests.",
        killers=("test_an_in_place_rewrite_to_identical_size_and_mtime_is_still_caught",
                 "test_a_rewrite_of_a_preexisting_file_is_invisible_to_the_diff_alone"),
    ),
    Mutant(
        "M2-window-is-call-phase-only",
        "    _CURRENT = item.nodeid",
        "    _CURRENT = None if True else item.nodeid",
        "The attribution window wraps the whole runtest protocol. Narrowing it to `call` files "
        "every FIXTURE write under `<no test running>` — and the incident write came from a "
        "fixture, so that is attribution to nobody, which is where it started.",
        killers=("test_a_fixtures_write_is_charged_to_the_test_not_to_nobody",),
    ),
    Mutant(
        "M3-no-abspath",
        "        full = os.path.abspath(os.fsdecode(path))",
        "        full = os.fsdecode(path)",
        "`lib/checkpoint.py`'s default root is the RELATIVE `results/checkpoints`, so a prefix "
        "test without abspath matches nothing and reports clean on the exact write that caused "
        "DEV-P1-17 — the guard's own blindness, reintroduced inside the guard.",
        killers=("test_the_relative_default_checkpoint_root_is_watched",),
    ),
    Mutant(
        "M4-replace-charged-to-source",
        "        target = args[1] if len(args) > 1 else args[0]",
        "        target = args[0]",
        "`Checkpoint.save` writes `<x>.json.tmp` and `os.replace`s it, so charging the source "
        "names a temp file nobody resumes from.",
        killers=("test_the_destination_of_an_atomic_replace_is_charged_not_the_temp_file",),
    ),
    # M5 is TWO mutants because `_UNATTRIBUTED.extend(lines)` appears twice — once in the
    # per-test fixture and once in the session fixture — and they are different failures. The
    # shell version had one M5 whose target matched both and applied to whichever came first,
    # so exactly one of the two regressions was ever measured. Targets carry a leading newline
    # and their full indent so each matches exactly once (the 4-space session line is a
    # substring of the 8-space per-test line otherwise).
    Mutant(
        "M5a-per-test-unattributed-raises",
        "\n        _UNATTRIBUTED.extend(lines)\n",
        '\n        raise AssertionError("tree changed: " + "\\n".join(lines))\n',
        "The regression itself, per test: an unattributable diff convicts whichever test "
        "happened to be running. This is the line-for-line behaviour that produced 147 errors.",
        killers=("test_a_concurrent_external_writer_fails_nobody",),
    ),
    Mutant(
        "M5b-session-unattributed-raises",
        "\n    _UNATTRIBUTED.extend(lines)\n",
        '\n    if lines:\n        raise AssertionError("tree changed: " + "\\n".join(lines))\n',
        "The same regression at session scope: a concurrent writer fails the whole run instead "
        "of being reported as concurrency. Worse than the per-test case, not better — it "
        "condemns every test at once and names none.",
        killers=("test_a_concurrent_external_writer_fails_nobody",),
    ),
    Mutant(
        "M6-spawning-tests-excused",
        "    if lines and spawned:",
        "    if lines and spawned and False:",
        "A child process is a write the test caused, so it is charged rather than excused. Ten "
        "test files spawn subprocesses and a hook cannot see into any of them; excusing them "
        "is the largest real hole this guard could have.",
        killers=("test_a_test_that_spawns_a_writing_child_is_failed",),
    ),
    Mutant(
        "M7-notice-suppressed",
        "    if not _UNATTRIBUTED:\n        return",
        "    if True:\n        return",
        "While another process writes into a watched tree the DIFF channel is void for the "
        "whole session, so the suite ran on one guard. Suppressing the notice hides that from "
        "the operator on a green run.",
    ),
    Mutant(
        "M8-per-test-reads-both-trees",
        "    mine = _writes_since(mark_w, nodeid, PER_TEST)",
        "    mine = _writes_since(mark_w, nodeid)",
        "The per-test fixture guards `results/` only. Unscoped, an `evidence/` write fails with "
        "'this test wrote into the live RESULTS tree' above an `evidence/` path — the wrong "
        "root cause over the right file (feedback_label_must_match_computation). THIS MUTANT "
        "SURVIVED the first 13 arms; it is the reason this harness exists in the tree.",
        killers=("test_a_write_into_evidence_fails_the_session_and_names_the_test",),
    ),
    Mutant(
        "M9-evidence-culprits-ignored",
        "    if culprits:",
        "    if culprits and False:",
        "The session diff cannot name a test (one snapshot for the whole run); the audit "
        "channel is the only thing that can. Ignoring culprits returns the guard to 'bisect by "
        "directory'.",
        killers=("test_a_write_into_evidence_fails_the_session_and_names_the_test",),
    ),
    Mutant(
        "M10-recording-scope-widened",
        "_PREFIXES = tuple(str(ROOT / name) + os.sep for name in WATCHED)",
        '_PREFIXES = ("/",)',
        "Widening the RECORDING scope to every path in the interpreter changes no verdict: both "
        "conviction paths re-filter by tree (`_writes_since(..., PER_TEST)` and the `ev_root` "
        "prefix). Declared inert. If this ever dies, either a conviction path stopped "
        "re-filtering or an arm started asserting on the recording scope — both need arguing, "
        "not banking.",
        inert=True,
    ),
    Mutant(
        "M11-session-reads-all-trees",
        "                       for who, _ev, p in _WRITES[mark_w:] if p.startswith(ev_root)})",
        "                       for who, _ev, p in _WRITES[mark_w:]})",
        "The mirror of M8. Unscoped, a `results/`-only write also fails the SESSION — and a "
        "session failure names the whole run, so it is the widest misattribution available.",
        killers=("test_the_session_guard_stays_silent_about_a_results_only_write",),
    ),
]


def test_every_mutant_target_appears_exactly_once():
    """A mutation that does not apply is not a survivor and must never be counted as a kill.

    The shell version printed `MUTANT-NOT-APPLIED` and moved on, which is the right behaviour
    for a report and the wrong behaviour for a gate: the row simply vanished from the table.
    Checked here as its own arm so a refactor of `conftest.py` that renames a line reds
    immediately, instead of silently shrinking the mutation set.
    """
    src = CONFTEST.read_text(encoding="utf-8")
    ids = [m.mid for m in MUTANTS]
    assert len(ids) == len(set(ids)), f"duplicate mutant ids: {ids}"
    bad = [(m.mid, src.count(m.target)) for m in MUTANTS if src.count(m.target) != 1]
    assert not bad, (
        "these mutation targets no longer appear exactly once in conftest.py, so the mutants "
        "would not apply and their claims would be unmeasured:\n"
        + "\n".join(f"  {mid}: found {n} occurrence(s)" for mid, n in bad))


def test_every_named_killer_arm_exists():
    """A `killers` entry naming an arm that does not exist would assert nothing.

    Same defect class as a mutation target that stopped matching: the check passes because the
    thing it checks is gone. Names are resolved against the arms file's source rather than by
    import, since importing it would register a second `pytester` plugin in this process.
    """
    arms_src = ARMS.read_text(encoding="utf-8")
    missing = sorted({k for m in MUTANTS for k in m.killers
                      if f"def {k}(" not in arms_src})
    assert not missing, (
        f"these arms are named as killers but do not exist in {ARMS.name}: {missing}")


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def _apply(mutant: Mutant, dst: Path) -> None:
    src = CONFTEST.read_text(encoding="utf-8")
    assert src.count(mutant.target) == 1, mutant.mid       # belt and braces; arm above too
    dst.write_text(src.replace(mutant.target, mutant.replacement, 1), encoding="utf-8")


def _sandbox(pytester: pytest.Pytester, monkeypatch, guard_src: Path) -> pytest.Pytester:
    """Point the real arms file at `guard_src` and stage it in the sandbox."""
    paths = [p for p in (site.getusersitepackages(), *sys.path) if p]
    monkeypatch.setenv("PYTHONPATH", ":".join(dict.fromkeys(paths)))
    monkeypatch.setenv("GRX_CONFTEST", str(guard_src))
    shutil.copyfile(ARMS, pytester.path / "test_arms_under_mutation.py")
    return pytester


def test_control_arm_unmutated_guard_passes_every_arm(pytester: pytest.Pytester, monkeypatch):
    """The control. Every kill below is worthless without it.

    An unmutated COPY of the guard, reached through exactly the same `GRX_CONFTEST` machinery
    the mutants use. If this reds, the harness is broken and its 11 kills are kills of the
    harness, not of the mutations — the failure mode where a mutation run scored 13/13 against
    a tree in which no test ran at all (`verify_phase0.sh`'s compile gate exists for the same
    reason).

    It also pins the one thing that would make every non-inert mutant a false kill: a
    collection error in the sandbox counts as an error, so `dead > 0` would be satisfied by a
    sandbox that never executed a single arm.
    """
    copy = pytester.path / "unmutated_conftest.py"
    shutil.copyfile(CONFTEST, copy)
    p = _sandbox(pytester, monkeypatch, copy)
    r = p.runpytest_subprocess("-p", "no:cacheprovider", "-q")
    out = r.parseoutcomes()
    assert out.get("failed", 0) == 0 and out.get("errors", 0) == 0, (
        f"the arms do not pass against an UNMUTATED guard, so no kill below is attributable to "
        f"its mutation: {out}\n{r.stdout.str()[-4000:]}")
    # A floor, not an equality: adding an arm must not require editing this file. But zero
    # passed would satisfy the assertion above, which is the vacuous shape.
    assert out.get("passed", 0) >= 15, (
        f"only {out.get('passed', 0)} arm(s) ran in the sandbox; the harness is measuring "
        f"almost nothing and every 'kill' below could come from a collection error")


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.mid)
def test_mutant(mutant: Mutant, pytester: pytest.Pytester, monkeypatch):
    """Run the real arms file against a mutated copy of the guard.

    The arms are copied into the sandbox and their `ROOT`/`CONFTEST` are redirected there by
    `GRX_CONFTEST` (see `test_write_guard.py`'s `guarded` fixture), so the arms exercise the
    MUTATED guard while the live `conftest.py` is only ever read. `runpytest_subprocess` for
    the same reason the arms themselves use it: `sys.addaudithook` cannot be uninstalled, so
    an in-process run would leave a mutated hook alive in this interpreter.
    """
    mutated = pytester.path / "mutated_conftest.py"
    _apply(mutant, mutated)
    p = _sandbox(pytester, monkeypatch, mutated)

    r = p.runpytest_subprocess("-p", "no:cacheprovider", "-q")
    out = r.parseoutcomes()
    dead = out.get("failed", 0) + out.get("errors", 0)
    text = r.stdout.str()

    # A mutant that stops the arms from RUNNING is not a kill. Guarded explicitly because the
    # cheapest way to break a guard is a SyntaxError, which reds every arm and would otherwise
    # be banked as the strongest kill in the table.
    assert out.get("passed", 0) > 0 or mutant.inert, (
        f"{mutant.mid}: not one arm passed, so the sandbox probably failed to collect rather "
        f"than the mutation being caught. This is not a kill.\n{text[-3000:]}")

    if mutant.inert:
        assert dead == 0, (
            f"{mutant.mid} is declared INERT but killed {dead} arm(s). That claim no longer "
            f"holds and must be re-argued before this mutant counts either way — see the "
            f"reasoning on the Mutant entry.\n{mutant.claim}\n"
            + "\n".join(line for line in text.splitlines() if "FAILED" in line or
                        "ERROR" in line))
        return

    assert dead > 0, (
        f"{mutant.mid} SURVIVED: every arm passed against a guard with this defect, so the "
        f"claim below has no assertion behind it.\n  claim: {mutant.claim}\n"
        f"  mutation: {mutant.target.strip()!r}\n         -> {mutant.replacement.strip()!r}")

    for arm in mutant.killers:
        assert arm in text and (f"FAILED test_arms_under_mutation.py::{arm}" in text
                                or f"ERROR test_arms_under_mutation.py::{arm}" in text), (
            f"{mutant.mid} was killed, but NOT by {arm}, which is the arm written for this "
            f"claim. A kill by an unrelated arm leaves the claim's own coverage unproven.\n"
            f"  claim: {mutant.claim}")


def test_the_real_conftest_was_never_written_to():
    """The harness must not be able to leave a broken guard in the tree.

    The shell version mutated `conftest.py` in place and relied on an EXIT trap to restore it.
    A kill -9, a full disk, or a crash inside the trap would have left a deliberately broken
    guard in the tree — and the guard is what keeps the test suite out of the live evidence
    trees. This arm asserts the property the rewrite bought.

    By SHA over the whole file, taken at import time and re-read here. My first version of this
    arm searched the live source for each mutant's replacement text, which is unsound in both
    directions: `"        pass"` occurs legitimately in the real guard's `except Exception`
    handler, so it reported a phantom in-place mutation, and a replacement that happened not to
    appear would have proved nothing about whether the file had been rewritten and restored.
    A hash comparison has neither hole.
    """
    now = hashlib.sha256(CONFTEST.read_bytes()).hexdigest()
    assert now == _LIVE_SHA, (
        f"conftest.py changed during this session ({_LIVE_SHA[:12]} -> {now[:12]}). A mutation "
        f"reached the real guard; every mutant must be applied to a sandbox copy.")
    src = CONFTEST.read_text(encoding="utf-8")
    assert "sys.addaudithook(_hook)" in src, "the live guard no longer installs its hook"
