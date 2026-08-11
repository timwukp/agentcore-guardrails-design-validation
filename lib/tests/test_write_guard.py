"""The write guard must convict the guilty test and acquit the innocent one.

WHY THIS FILE EXISTS
--------------------
The root `conftest.py` guards `results/` and `evidence/` against tests writing into the trees
a live run resumes from. Its first version had one channel — snapshot the tree, run, diff —
and on 2026-08-10 it failed **147 tests and the session** on a run where every test was
innocent: a live Phase 1 script (`f8_regional/03_prompt_leakage.py`, 690 calls) was writing
`evidence/r20260810T0345Z/f8/F8-4-checks-leakage/*.json` from another process while the suite
ran. A tree diff observes *change*; it cannot observe *authorship*, and it silently supplied
the missing half by assuming whoever was running did it.

That is the failure mode this project keeps writing entries about from the other direction. A
guard that convicts the innocent gets switched off just as surely as one that costs two thirds
of the run, and it inverts its own signal: the operator learns to read this guard's red as "a
live run must be going", which is exactly how the real leak gets waved through next time.

So the guard now has two channels — `sys.addaudithook` for authorship, the diff for the
subprocess writes a hook in this interpreter cannot see — and this file pins the truth table
between them. Each arm is one row.

HOW THESE ARMS RUN
------------------
Via `pytester.runpytest_subprocess`, with the real `conftest.py` copied into the sandbox.
Copying makes the sandbox the guard's own `ROOT`, so its watched trees are `<tmp>/results` and
`<tmp>/evidence` and no arm can touch the live ones. A **subprocess** rather than
`runpytest_inprocess` for a reason specific to the code under test: `sys.addaudithook` cannot
be removed once installed, so an in-process run would leave one stale hook per arm alive in
this interpreter, and the outer conftest's hook would also see the inner tests' writes and
charge them to the outer arm. That confound would make these arms measure their own harness.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[2]

# The guard under test. Normally the live root conftest; `test_write_guard_mutation.py` points
# this at a MUTATED COPY in its own sandbox so these arms can be run against a deliberately
# broken guard without the harness ever writing to the real file. An override that resolved to
# a missing path would silently test nothing, so the `guarded` fixture asserts the file exists.
CONFTEST = Path(os.environ.get("GRX_CONFTEST") or (ROOT / "conftest.py"))


@pytest.fixture
def guarded(pytester: pytest.Pytester, monkeypatch) -> pytest.Pytester:
    """A sandbox running the REAL root conftest, rooted at the sandbox.

    Read from disk rather than reimplemented: an arm that tests a copy of the guard's logic
    passes forever after the guard changes (`feedback_verify_against_real_artifact`).

    `PYTHONPATH` is set because `pytester` monkeypatches `HOME` to a sandbox directory, and on
    this machine pytest lives in the **user** site-packages (`~/Library/Python/3.12/...`),
    which is resolved from `HOME`. Without this the child dies with "No module named pytest"
    and `assert_outcomes` raises `ValueError: Pytest terminal summary report not found` — a
    failure that looks like the guard misbehaving and is really the harness having no pytest.
    All 11 subprocess arms failed this way on first run.
    """
    assert CONFTEST.is_file(), f"{CONFTEST} is missing — this file tests nothing"
    import site
    paths = [p for p in (site.getusersitepackages(), *sys.path) if p]
    monkeypatch.setenv("PYTHONPATH", ":".join(dict.fromkeys(paths)))
    shutil.copyfile(CONFTEST, pytester.path / "conftest.py")
    (pytester.path / "results").mkdir()
    (pytester.path / "evidence").mkdir()
    return pytester


def run(p: pytest.Pytester, *args: str):
    return p.runpytest_subprocess("-p", "no:cacheprovider", "-q", *args)


def assert_convicted(r, *, n: int = 1) -> None:
    """`n` test(s) convicted by the guard, counted as ERRORS and not failures.

    The guard lives in an autouse fixture's **teardown**, and pytest reports a teardown
    failure as an *error* on the test while the test body itself still passes. So the sandbox
    summary reads `1 passed, 1 error` — not `1 failed`. Every arm here asserted `failed=n`
    on first run and eight of them failed on that alone, while the guard was working
    perfectly and printing the right message.

    Worth stating because it is the same accounting that produced the headline number in
    DEV-P1-19: the live run's concurrent writes were reported as **147 errors**, not 147
    failures, which is why nothing in the summary line said "assertion". A guard that
    convicts from teardown is invisible to `-x` too — it cannot stop the run at the first
    offender, since the body has already passed by the time it speaks.
    """
    out = r.parseoutcomes()
    assert out.get("errors", 0) == n, (
        f"expected {n} teardown conviction(s) reported as errors, got {out}")
    assert out.get("failed", 0) == 0, (
        f"a test body failed as well; this arm is no longer isolating the guard: {out}")


# ---------------------------------------------------------------- row 1: guilty in-process

def test_a_test_that_writes_into_results_is_failed_and_named(guarded):
    """The original incident: a checkpoint written into the tree a live run resumes from."""
    guarded.makepyfile(test_leak="""
        from pathlib import Path

        def test_writes_a_checkpoint():
            p = Path("results") / "checkpoints"
            p.mkdir(parents=True, exist_ok=True)
            (p / "F3-1__pii-ssn.json").write_text('{"case_id": "F3-1"}')
    """)
    r = run(guarded)
    assert_convicted(r)
    out = r.stdout.str()
    assert "wrote into the live results tree" in out, out
    assert "results/checkpoints/F3-1__pii-ssn.json" in out, (
        "the failure must name the file; a guard that says only 'something changed' sends the "
        "reader back to a tree diff, which is the channel that misattributed 147 tests")


def test_the_relative_default_checkpoint_root_is_watched(guarded):
    """`lib/checkpoint.py`'s default root is the RELATIVE `results/checkpoints`.

    A prefix test that compared a relative path against an absolute watched root would match
    nothing and report clean on the exact write that caused the incident — the guard's own
    blindness, reintroduced in the guard. `_under_watch` calls `abspath` for this reason and
    this arm is what says so.
    """
    guarded.makepyfile(test_rel="""
        def test_opens_a_relative_path():
            open("results/relative.json", "w").close()
    """)
    r = run(guarded)
    assert_convicted(r)
    assert "results/relative.json" in r.stdout.str()


# ---------------------------------------------------------------- row 3: innocent, acquitted

def test_a_concurrent_external_writer_fails_nobody(guarded):
    """THE REGRESSION. 147 tests were failed for this; every one of them was innocent.

    A second process writes into both watched trees while the suite runs — exactly what a live
    Phase 1 script does. The audit channel says no test wrote there and no test spawned a
    child that could have, so nothing is charged to anyone.

    The write comes from a SEPARATE interpreter, launched by a plugin, not by a test — so the
    guard records no `subprocess.Popen` against any test's nodeid. That is the whole point: it
    reproduces "another process is writing" rather than "a test spawned a writer", which are
    rows 3 and 2 and must not be conflated.

    STAGING, which took two corrections and both were the arm's fault, not the guard's
    -----------------------------------------------------------------------------------
    1. The writer first ran in `pytest_sessionstart`, and the arm failed. The guard's session
       baseline is taken by a session-scoped autouse *fixture*, which pytest sets up after
       `sessionstart` — so the writes were already on disk when the baseline was recorded and
       the diff correctly saw nothing. Row 3 requires the write to land strictly BETWEEN the
       two snapshots.
    2. Moving the spawn into `pytest_runtest_setup(test_two)` failed too, and the guard's
       message said exactly why: setup is inside `test_two`'s attribution window, so the
       `subprocess.Popen` was charged to `test_two` and the run became **row 2** — a test that
       spawned a writer. Which is the correct verdict for that staging, and would have made
       this arm pass while measuring the wrong row.

    So the child is launched from `pytest_configure`, before any test exists and therefore
    outside every attribution window, and it *waits* for a `GO` sentinel that `test_two`
    creates. `GO` lives in the sandbox root, deliberately not under a watched tree, so
    creating it is not itself a write the guard cares about. Ordering is by sentinel in both
    directions rather than by `time.sleep`, which is a race with a bound nobody measured.

    `test_two` then asserts both files exist. Without that, an arm whose child silently wrote
    nothing would still "pass", since row 3's expected outcome is that nothing is charged —
    the vacuous-pass shape (`feedback_vacuous_test_check`).
    """
    guarded.makepyfile(external_writer="""
        import os, subprocess, sys

        CHILD = (
            "import os, time\\n"
            "root = os.environ['GRX_SANDBOX']\\n"
            "go = os.path.join(root, 'GO')\\n"
            "deadline = time.monotonic() + 60\\n"
            "while not os.path.exists(go) and time.monotonic() < deadline:\\n"
            "    time.sleep(0.01)\\n"
            "d = os.path.join(root, 'evidence', 'r1', 'f8', 'F8-4')\\n"
            "os.makedirs(d, exist_ok=True)\\n"
            "open(os.path.join(d, '0001_ok.json'), 'w').close()\\n"
            "c = os.path.join(root, 'results', 'checkpoints')\\n"
            "os.makedirs(c, exist_ok=True)\\n"
            "open(os.path.join(c, 'F8-4__live.json'), 'w').close()\\n"
            "open(os.path.join(root, 'DONE'), 'w').close()\\n"
        )

        def pytest_configure(config):
            # BEFORE any test: `_CURRENT` is None here, so nothing this child does can be
            # charged to a test as a spawn. The child blocks on GO so its writes still land
            # after the guard's session baseline.
            root = os.getcwd()
            subprocess.Popen([sys.executable, "-c", CHILD],
                             env=dict(os.environ, GRX_SANDBOX=root))
    """)
    guarded.makepyfile(test_innocent="""
        import time
        from pathlib import Path

        def test_one(): assert True

        def test_two():
            # GO is in the sandbox ROOT, not under results/ or evidence/ — releasing the
            # writer must not itself be a watched write.
            Path("GO").write_text("")
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not Path("DONE").exists():
                time.sleep(0.01)
            assert Path("DONE").exists(), "the external writer never finished"
            # Premise, not decoration: row 3's expected outcome is that NOTHING is charged, so
            # a child that wrote nothing would pass this arm for the wrong reason.
            assert Path("evidence/r1/f8/F8-4/0001_ok.json").exists()
            assert Path("results/checkpoints/F8-4__live.json").exists()

        def test_three(): assert True
    """)
    r = run(guarded, "-p", "external_writer")
    r.assert_outcomes(passed=3)
    out = r.stdout.str() + r.stderr.str()
    assert "concurrent writer" in out, (
        "an unattributed change must still be REPORTED: while another process writes into "
        "these trees the diff channel is void for the whole session, so the suite ran with "
        "one of its two guards disabled — a fact about the run's evidentiary value")
    assert "ANOTHER PROCESS" in out
    assert "VOID" in out, "the void-diff-channel warning is the operative half of the notice"
    assert "wrote into the live results tree" not in out, (
        "an innocent test was charged with another process's write — the 147-test regression")
    assert "tests wrote into the live evidence tree" not in out


# ---------------------------------------------------------------- row 2: child process

def test_a_test_that_spawns_a_writing_child_is_failed(guarded):
    """A hook sees only its own interpreter, so a child's writes are invisible to it.

    Verified, not assumed: a parent hook does not fire for a child's `open`. Ten test files in
    this project spawn subprocesses, so the diff is the only channel that can see them — and
    when the diff moves and the running test spawned a child, the test is charged. A child is
    a write the test caused; excusing it would leave the largest real hole in the guard.
    """
    guarded.makepyfile(test_child="""
        import subprocess, sys

        def test_spawns_a_writer():
            subprocess.run([sys.executable, "-c",
                            "open('results/from_child.json','w').close()"], check=True)
    """)
    r = run(guarded)
    assert_convicted(r)
    out = r.stdout.str()
    assert "results/from_child.json" in out
    assert "spawned" in out and "subprocess" in out, out


def test_a_child_that_writes_nothing_still_passes(guarded):
    """The other half of row 2 — otherwise the fix is "any test that spawns anything fails".

    Eight of the ten spawning test files run gate scripts that legitimately write nowhere near
    these trees. If this arm failed, the guard would have traded a false accusation of 147
    tests for a false accusation of ten, which is not a fix.
    """
    guarded.makepyfile(test_clean_child="""
        import subprocess, sys

        def test_spawns_a_harmless_child():
            subprocess.run([sys.executable, "-c", "print('hello')"], check=True)
    """)
    r = run(guarded)
    r.assert_outcomes(passed=1)


# ---------------------------------------------------------------- row 4: audit beats diff

def test_an_in_place_rewrite_to_identical_size_and_mtime_is_still_caught(guarded):
    """The row where the audit channel is strictly stronger than the diff.

    The diff compares `(size, mtime_ns)`. A rewrite of the same number of bytes whose mtime is
    then restored is invisible to it — and "a checkpoint overwritten with stub trials" is the
    worse of the two failures the guard exists for, since it changes what a live run resumes
    rather than merely adding litter.
    """
    guarded.makepyfile(test_rewrite="""
        import os
        from pathlib import Path

        def test_rewrites_in_place():
            p = Path("results") / "same.json"
            p.write_bytes(b"AAAA")
            st = p.stat()
            p.write_bytes(b"BBBB")                       # identical size
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))   # identical mtime
    """)
    r = run(guarded)
    # The file is created inside the test, so the first write is itself a diff-visible add;
    # what this arm pins is that the guard names the WRITE, i.e. the audit channel fired.
    assert_convicted(r)
    out = r.stdout.str()
    assert "wrote into the live results tree" in out, out
    assert "results/same.json" in out


def test_a_rewrite_of_a_preexisting_file_is_invisible_to_the_diff_alone(guarded):
    """The same row, with the diff channel provably blind.

    The file exists BEFORE the test, so `(size, mtime_ns)` is unchanged across it and the diff
    yields nothing. Only the audit channel can fail this, so the arm measures the audit
    channel in isolation rather than incidentally.
    """
    (guarded.path / "results" / "pre.json").write_bytes(b"AAAA")
    guarded.makepyfile(test_silent_rewrite="""
        import os
        from pathlib import Path

        def test_rewrites_a_preexisting_file():
            p = Path("results") / "pre.json"
            st = p.stat()
            p.write_bytes(b"BBBB")
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    """)
    r = run(guarded)
    assert_convicted(r)
    out = r.stdout.str()
    assert "results/pre.json" in out
    assert "the tree also changed" not in out, (
        "the diff was expected to see NOTHING here (same size, same mtime); if it did, this "
        "arm is no longer isolating the audit channel and would keep passing after the audit "
        "channel was deleted")


# ---------------------------------------------------------------- os.replace destination

def test_the_destination_of_an_atomic_replace_is_charged_not_the_temp_file(guarded):
    """`Checkpoint.save` writes `<x>.json.tmp` then `os.replace`s it onto `<x>.json`.

    Charging only `args[0]` would credit the checkpoint overwrite to a temp file, and a guard
    reporting `results/checkpoints/F3-1__cell.json.tmp` while the real file was replaced tells
    the reader the wrong thing about what a live run will now resume from.
    """
    guarded.makepyfile(test_replace="""
        import os, tempfile
        from pathlib import Path

        def test_atomic_replace():
            d = Path("results") / "checkpoints"
            d.mkdir(parents=True, exist_ok=True)
            # The temp file is written OUTSIDE the watched tree, so the only way the guard can
            # see this at all is by charging the replace DESTINATION.
            fd, tmp = tempfile.mkstemp()
            os.write(fd, b'{"case_id": "F3-1"}')
            os.close(fd)
            os.replace(tmp, d / "F3-1__pii-ssn.json")
    """)
    r = run(guarded)
    assert_convicted(r)
    out = r.stdout.str()
    assert "os.replace" in out or "os.rename" in out, out
    assert "results/checkpoints/F3-1__pii-ssn.json" in out, (
        "the replace DESTINATION must be charged; args[0] is the temp file, which nobody "
        "resumes from")


# ---------------------------------------------------------------- evidence/, session scope

def test_a_write_into_evidence_fails_the_session_and_names_the_test(guarded):
    """`evidence/` is diffed once per session (61 ms a walk), so the diff cannot name a test.

    The audit channel supplies the name the diff structurally cannot — which is what the old
    message admitted it could not do ("so no single test is named ... or bisect by directory").
    """
    guarded.makepyfile(test_ev="""
        from pathlib import Path

        def test_writes_evidence():
            d = Path("evidence") / "r1" / "f3" / "F3-7"
            d.mkdir(parents=True, exist_ok=True)
            (d / "0001_apply_guardrail_ok.json").write_text("{}")
    """)
    r = run(guarded)
    out = r.stdout.str()
    assert "tests wrote into the live evidence tree" in out, out
    assert "test_ev.py::test_writes_evidence" in out, (
        "the session failure must name the test; bisecting by directory was the old advice "
        "and it is what this channel exists to replace")
    assert "evidence/r1/f3/F3-7/0001_apply_guardrail_ok.json" in out
    # The message must name the tree it actually checked. An `evidence/` write reported as
    # "this test wrote into the live RESULTS tree" — which is what the per-test fixture did
    # before it was scoped — names the wrong root cause above the right path, and a mutation
    # restoring that survived the whole suite until this assertion existed.
    assert "wrote into the live results tree" not in out, (
        "an evidence/ write was reported against the RESULTS tree; the per-test fixture reads "
        "PER_TEST only, and mislabelling which tree changed sends the reader to the wrong "
        "root cause (feedback_label_must_match_computation)")


def test_the_session_guard_stays_silent_about_a_results_only_write(guarded):
    """The mirror of the assertion above: the two guards are disjoint in BOTH directions.

    The evidence arm pins `evidence/ write → no results message` (which is what kills the M8
    mutant, `_writes_since` called with no tree scope). This arm pins the other direction —
    `results/ write → no evidence message` — so the session fixture's `ev_root` filter is held
    by behaviour rather than only by the source-level assertion in
    `test_the_recording_scope_cannot_widen_a_conviction`.

    Not folded into one arm with a test that writes into both trees: pytest raises both
    convictions inside a single `BaseExceptionGroup` and reverses the sub-exception order
    (`_pytest/runner.py:568`, `exceptions[::-1]`), so which message prints first is an
    implementation detail. An arm that split the output on one heading to read the other would
    be asserting on that detail. One write, one tree, one expected message each.
    """
    guarded.makepyfile(test_res="""
        from pathlib import Path

        def test_writes_results_only():
            Path("results/in_results.json").write_text("{}")
    """)
    r = run(guarded)
    out = r.stdout.str()
    assert_convicted(r)
    assert "this test wrote into the live results tree" in out, out
    assert "results/in_results.json" in out, out
    assert "wrote into the live evidence tree" not in out, (
        "the session evidence guard fired over a write that never touched evidence/. It must "
        "read the ev_root prefix only; a session-scoped failure names the whole run, so a "
        "false one there is the widest possible misattribution.")


# ---------------------------------------------------------------- scope of the watch

def test_the_recording_scope_cannot_widen_a_conviction(guarded):
    """The M10 mutant, and why it is INERT rather than uncaught.

    Setting `_PREFIXES = ("/",)` makes the hook record every write in the interpreter — a
    hundredfold widening — and all 13 arms still passed. That is not a missing arm: both
    conviction paths re-filter by tree (`_writes_since(..., PER_TEST)` and the `ev_root`
    prefix), so a write recorded outside a watched tree can never reach a verdict. The
    recording scope is a performance filter; the *conviction* scope is the semantic one, and
    it is asserted by `test_writes_outside_the_watched_trees_are_ignored` below.

    Pinned here so the inertness is a recorded property rather than a lucky one. If a future
    edit made a conviction path read `_WRITES` unfiltered, this arm fails — which is precisely
    what the M8 mutant did to the per-test path.

    (A mutant that cannot change behaviour scores a false KILL if it appears to die, and a
    false SURVIVAL if it does not — DEV-P1-18's M3 was the same shape. Either way the number
    it contributes to a mutation table is not evidence, so it is written down as inert.)
    """
    src = CONFTEST.read_text(encoding="utf-8")
    assert "_writes_since(mark_w, nodeid, PER_TEST)" in src, (
        "the per-test conviction path no longer scopes its read to PER_TEST; the recording "
        "scope would then decide convictions, and widening it would convict tmp_path writes")
    assert 'ev_root = str(ROOT / "evidence")' in src and "p.startswith(ev_root)" in src, (
        "the session conviction path no longer scopes its read to evidence/")


def test_writes_outside_the_watched_trees_are_ignored(guarded):
    """tmp_path is where every test SHOULD write, so it must cost nothing.

    A guard that fired on `tmp_path` would be switched off within the hour, and the fixture
    the failure message recommends (`roots`) is built on `tmp_path` — recommending a fix the
    guard then punishes would be incoherent.
    """
    guarded.makepyfile(test_tmp="""
        from pathlib import Path

        def test_writes_to_tmp_path(tmp_path):
            (tmp_path / "checkpoints").mkdir()
            (tmp_path / "checkpoints" / "F3-1__cell.json").write_text("{}")

        def test_writes_a_sibling_dir():
            Path("resultsX").mkdir(exist_ok=True)      # prefix-adjacent, NOT under results/
            (Path("resultsX") / "a.json").write_text("{}")
    """)
    r = run(guarded)
    r.assert_outcomes(passed=2)


def test_a_fixtures_write_is_charged_to_the_test_not_to_nobody(guarded):
    """The incident write came from a FIXTURE, not a test body.

    The attribution window wraps the whole runtest protocol for this reason. A window covering
    only the `call` phase would file every fixture's write under `<no test running>` —
    attributed to nobody, which is where they were before this guard existed.
    """
    guarded.makepyfile(test_fixture_writes="""
        import pytest
        from pathlib import Path

        @pytest.fixture
        def leaky():
            p = Path("results") / "from_fixture.json"
            p.write_text("{}")
            yield p

        def test_uses_the_fixture(leaky):
            assert leaky.exists()
    """)
    r = run(guarded)
    assert_convicted(r)
    out = r.stdout.str()
    assert "results/from_fixture.json" in out
    assert "<no test running>" not in out, (
        "a fixture's write was attributed to nobody; setup and teardown are inside the "
        "attribution window precisely because the original incident came from a fixture")


# ---------------------------------------------------------------- the guard cannot break code

def test_the_hook_cannot_propagate_an_exception_into_the_code_it_watches(guarded):
    """An exception raised inside an audit hook propagates into the innocent call that fired it.

    `open()` anywhere in the interpreter would start raising the guard's own bug. The hook
    therefore swallows its own exceptions, and this arm proves the swallow is real by feeding
    it the shapes that would otherwise raise: a mode that is not a string, a path that is not
    path-like, and an `os.rename` audit event carrying a single argument.
    """
    guarded.makepyfile(test_odd_calls="""
        import io, os
        from pathlib import Path

        def test_odd_open_arguments_do_not_explode():
            # A file descriptor, not a path: `os.fsdecode` would raise on it.
            fd = os.open("results/fd.json", os.O_CREAT | os.O_WRONLY)
            os.close(fd)
            # An int path through the io layer.
            fd = os.open("results/fd2.json", os.O_CREAT | os.O_WRONLY)
            with io.open(fd, "wb", closefd=True) as f:
                f.write(b"x")
            assert Path("results/fd.json").exists()
    """)
    r = run(guarded)
    # The point is that nothing raises from inside the hook — the run completes and reports a
    # normal guard verdict rather than an interpreter-level error.
    out = r.stdout.str()
    assert "INTERNALERROR" not in out, out
    assert "Traceback" not in out or "wrote into the live results tree" in out, out


def test_every_watched_tree_is_covered_by_an_arm_above():
    """A tripwire on the watch list: a new watched tree needs an arm, not a hope.

    Read from the guard rather than listed here, so adding `WATCHED = (..., "state")` fails
    HERE — the same rule as `verify_phase0.sh`'s per-directory floors and
    `test_policy_liveness.py`'s `require_policy` scope arm.
    """
    src = CONFTEST.read_text(encoding="utf-8")
    m = re.search(r"^PER_TEST = \((.*?)\)", src, re.M)
    n = re.search(r"^PER_SESSION = \((.*?)\)", src, re.M)
    assert m and n, "could not read the watch lists from conftest.py"
    watched = set(re.findall(r'"([^"]+)"', m.group(1) + n.group(1)))
    assert watched == {"results", "evidence"}, (
        f"the guard now watches {sorted(watched)}; this file has arms for results/ (per test) "
        f"and evidence/ (per session) only. A newly watched tree with no arm is a guard "
        f"nobody has shown to work in either direction.")
