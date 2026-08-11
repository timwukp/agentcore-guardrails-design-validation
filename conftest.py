"""Repo-root conftest: no test may write into the live evidence or checkpoint trees.

Why this exists
---------------
`results/checkpoints/T__main.json` was found in the live checkpoint directory. Its contents
name their own author:

    {"case_id": "T", "cell": "main", "run_id": "r1", "corpus": "c",
     "failed": {"i0": {"error_message": "stub exhausted: more calls than queued responses"}}}

"stub exhausted" is raised by `StubClient` in `lib/tests/test_arms.py`. A unit test had
written a checkpoint into the tree that live runs resume from.

Why that is not merely untidy
-----------------------------
`lib/checkpoint.py` exists so a killed run resumes instead of re-billing, and
`Checkpoint.load` treats a file whose `case_id`/`cell` disagree with the opened cell as
**fatal** — because "resuming would attribute one arm's trials to another". Those guards are
keyed on `case_id` and `cell`. A test that writes under a *real* case id and cell would slip
past every one of them and make a live run skip trials it never ran: fewer usable trials than
the seal asked for, a checkpoint that says otherwise, and no error anywhere. `T` is not a real
case id, which is the only reason this instance was harmless.

The tests already have the fix available — `lib/tests/test_arms.py` has a `roots` fixture
handing every call a `tmp_path` root — so this is a discipline defect, not a design one, and
discipline that depends on remembering to pass a fixture is what an assertion is for. One
call site (`test_an_unmodelled_operation_fails_before_any_item_is_sent`) deliberately omits
`**roots` and is safe only because a `RuntimeError` fires before the first write; that safety
is a property of the code under test, one edit away from changing.

TWO CHANNELS, BECAUSE A TREE DIFF CANNOT NAME AN AUTHOR
-------------------------------------------------------
The first version of this file had one channel: snapshot the tree, run, diff. That channel
convicted **147 tests and the session** on a run where every test was innocent. A live Phase 1
script (`f8_regional/03_prompt_leakage.py`, 690 calls) was in flight in another process,
writing `evidence/r20260810T0345Z/f8/F8-4-checks-leakage/*.json` and its own checkpoints while
the suite ran. The diff saw new files under a watched root and blamed whoever was running.

That is not a cosmetic misattribution. A guard that convicts the innocent gets switched off —
this file's own docstring already said as much about *cost*, and false accusation is the other
way the same thing happens. Worse, it inverts the signal: the operator learns to read a red
from this guard as "a live run must be going", which is precisely how the real leak would be
waved through the next time it happens.

So authorship is established by **`sys.addaudithook`**, not by inference from a diff:

* **the audit channel** records every `open(..., 'w'|'a'|'x'|'+')`, `os.rename`/`os.replace`,
  `os.mkdir` and `os.remove` performed *by this process* under a watched root, with the test
  that was running at the time. It answers the guard's actual question — "did a test write
  here?" — directly, and it is immune to anything another process does.
* **the diff channel** is kept, because the audit channel has one blind spot that matters
  here: a hook sees only its own interpreter. Ten test files spawn subprocesses
  (`claims/tests/test_prereg_verifier.py`, `test_corpus_gate.py`, `test_v13_candidates.py`,
  `test_redaction_gate.py`, `test_cost_gate.py`, `test_amendment_gate.py`,
  `test_finding_numbers.py`, `test_prereg_finding_numbers.py`, `lib/tests/test_checkpoint.py`,
  `f5_redteam/tests/test_compare_runs.py`), and a child's writes are invisible to the parent's
  hook — verified, not assumed. The diff is the only thing that can see those.

The two are combined so that each covers the other's blind spot without either one's failure
mode leaking through:

| diff shows a change | this test wrote in-process | this test spawned a child | verdict |
|:---|:---|:---|:---|
| yes | yes | — | **FAIL**, naming the write the hook recorded |
| yes | no | **yes** | **FAIL** — the child is a write this session caused and cannot rule out |
| yes | no | no | **not this test** — reported as concurrency, once, and not charged to any test |
| no  | yes | — | **FAIL** — an in-place rewrite to identical (size, mtime_ns), which the diff would miss |

The last row is not hypothetical padding: it is the case where the audit channel is strictly
stronger than the diff, and a checkpoint overwritten with stub trials is the worse of the two
failures.

Cost, measured on this machine rather than feared: the hook adds nothing detectable —
30,000 write-opens took 4.92 s without it and 4.52 s with it, 30,000 read-opens 3.92 s vs
3.60 s (both differences are noise, and the hook filters on a string prefix before doing any
work). The reason to keep the diff cheap still stands, so its scopes are unchanged:
`results/` is 111 files and snapshots in 1.7 ms; `evidence/` is 4,548 files and takes 61 ms,
which per-test would add ~120 s to a 187 s suite — a guard costing two thirds of the run it
guards is a guard that gets switched off.

* **`results/` is checked per test.** That is where the incident happened and where the
  checkpoints live.
* **`evidence/` is checked once per session**, and the audit channel is what names the test.

The diff compares (size, mtime_ns) rather than existence, so an in-place rewrite of an
existing file is caught as well as a new one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# Checked per test: cheap to walk, and holds the checkpoints a live run resumes from.
#
# `results/figures` and `results/tables` are regenerated by the analysis phase and are not
# evidence of a call, but they are still not a test's business to touch, so no exception is
# carved out. If Phase 9 ever needs one, it gets a named entry here with a reason rather than
# a relaxed comparison.
PER_TEST = ("results",)

# Checked once per session: 4,548 files, 61 ms a walk.
PER_SESSION = ("evidence",)

# Both trees, for the audit channel — it is per-write and does not care about walk cost, so
# it watches everything the diff watches at the finer scope.
WATCHED = PER_TEST + PER_SESSION


# ---------------------------------------------------------------------------
# the audit channel: who wrote, not what changed
# ---------------------------------------------------------------------------

# Appended to by the hook, sliced by the fixtures. A list rather than a per-test reset because
# `sys.addaudithook` cannot be removed once installed, so the hook outlives every fixture and
# must never assume one is active.
_WRITES: list[tuple[str, str, str]] = []          # (nodeid, event, path)
_SPAWNS: list[tuple[str, str]] = []               # (nodeid, argv0)

# Set by a hookwrapper below. `None` means "no test is running" — collection, session
# setup/teardown, or the hook firing from pytest's own internals.
_CURRENT: str | None = None

_WRITE_MODES = frozenset("wxa+")
_PREFIXES = tuple(str(ROOT / name) + os.sep for name in WATCHED)


def _under_watch(path: object) -> str:
    """The absolute path if it is inside a watched tree, else `""`.

    `os.path.abspath` because `lib/checkpoint.py`'s default root is the RELATIVE
    `results/checkpoints`, so a prefix test against an absolute root would match nothing —
    the exact shape of blindness this file exists to remove. `abspath` raises no audit event
    of its own, which matters: anything in here that did would recurse.
    """
    if not isinstance(path, (str, bytes, os.PathLike)):
        return ""
    try:
        full = os.path.abspath(os.fsdecode(path))
    except (ValueError, TypeError):
        return ""
    return full if full.startswith(_PREFIXES) else ""


def _audit(event: str, args: tuple) -> None:
    if event == "open":
        mode = args[1]
        if not isinstance(mode, str) or not (_WRITE_MODES & set(mode)):
            return
        target = args[0]
    elif event in ("os.rename", "os.replace", "os.link", "os.symlink"):
        # args = (src, dst). The DESTINATION is the write; `Checkpoint.save` writes a
        # `.json.tmp` and then `os.replace`s it onto the real path, so charging only the
        # source would credit a checkpoint overwrite to a temp file nobody watches.
        target = args[1] if len(args) > 1 else args[0]
    elif event in ("os.mkdir", "os.rmdir", "os.remove", "os.unlink", "os.truncate"):
        target = args[0]
    else:
        return
    full = _under_watch(target)
    if full:
        _WRITES.append((_CURRENT or "<no test running>", event, full))


def _audit_spawn(event: str, args: tuple) -> None:
    if event == "subprocess.Popen":
        argv0 = args[0]
        try:
            argv0 = os.fsdecode(argv0) if argv0 is not None else "?"
        except (ValueError, TypeError):
            argv0 = "?"
        _SPAWNS.append((_CURRENT or "<no test running>", str(argv0)))


def _hook(event: str, args: tuple) -> None:
    # One hook, two concerns, wrapped so a bug in either cannot abort the interpreter: an
    # exception raised inside an audit hook propagates into whatever innocent call triggered
    # it, which would turn this guard into the flakiest thing in the suite.
    try:
        _audit(event, args)
        _audit_spawn(event, args)
    except Exception:                                                  # noqa: BLE001
        pass


sys.addaudithook(_hook)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """Attribute writes to the running test, setup and teardown included.

    Wraps the whole protocol rather than the call phase: the incident write came from a
    fixture, and a window covering only `call` would leave every fixture's writes filed
    under `<no test running>` — attributed to nobody, which is where they were before.
    """
    global _CURRENT
    _CURRENT = item.nodeid
    try:
        yield
    finally:
        _CURRENT = None


def _writes_since(mark: int, nodeid: str, trees: tuple[str, ...] | None = None) -> list[str]:
    """Formatted writes charged to `nodeid` since `mark`, optionally within given trees.

    `trees` matters and its absence was a defect. The per-test fixture guards `results/` but
    the hook watches BOTH trees, so an unfiltered call made an `evidence/` write fail with
    "this test wrote into the live results tree" and the path `evidence/ext.json` underneath
    it — a message that contradicts itself and sends the reader to the wrong root cause
    (`feedback_label_must_match_computation`).
    """
    pref = tuple(str(ROOT / t) + os.sep for t in (trees or WATCHED))
    return [f"  {ev:<12} {p[len(str(ROOT)) + 1:]}"
            for who, ev, p in _WRITES[mark:] if who == nodeid and p.startswith(pref)]


def _spawned_since(mark: int, nodeid: str) -> list[str]:
    return [argv0 for who, argv0 in _SPAWNS[mark:] if who == nodeid]


def _snapshot(names) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for name in names:
        base = ROOT / name
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file():
                st = p.stat()
                out[str(p.relative_to(ROOT))] = (st.st_size, st.st_mtime_ns)
    return out


def _diff(before: dict, after: dict) -> list[str]:
    added = sorted(set(after) - set(before))
    changed = sorted(k for k in set(after) & set(before) if after[k] != before[k])
    removed = sorted(set(before) - set(after))
    return ([f"  ADDED    {k}" for k in added]
            + [f"  MODIFIED {k}" for k in changed]
            + [f"  REMOVED  {k}" for k in removed])


_WHY = (
    "\n\nA checkpoint written by a test makes a live run resume trials it never ran, and "
    "`Checkpoint.load`'s case_id/cell guard cannot see it because the test chose those "
    "values. Pass a `tmp_path`-based root — `lib/tests/test_arms.py` has a `roots` fixture "
    "that does exactly this — rather than letting the default "
    "`Path('results')/'checkpoints'` apply.\n"
    "This guard was added after results/checkpoints/T__main.json was found in the live tree "
    "carrying a StubClient's 'stub exhausted' failure."
)

# Diffs this session saw but could not charge to any test, because the test running at the
# time neither wrote in-process nor spawned a child. Collected so the session can report
# concurrency once, as information, instead of 147 times as an accusation.
_UNATTRIBUTED: list[str] = []


@pytest.fixture(autouse=True)
def _no_writes_to_results(request):
    """Fail the individual test that wrote into `results/`.

    Autouse and unconditional. An opt-in marker would be granted by whoever forgot the
    tmp_path fixture in the first place.
    """
    nodeid = request.node.nodeid
    mark_w, mark_s = len(_WRITES), len(_SPAWNS)
    before = _snapshot(PER_TEST)
    yield
    lines = _diff(before, _snapshot(PER_TEST))
    # PER_TEST only. The hook watches both trees, so an unfiltered read made an `evidence/`
    # write fail as "this test wrote into the live RESULTS tree" — the wrong tree named above
    # the right path. `evidence/` is the session fixture's business, below.
    mine = _writes_since(mark_w, nodeid, PER_TEST)
    spawned = _spawned_since(mark_s, nodeid)

    if mine:
        pytest.fail("this test wrote into the live results tree:\n" + "\n".join(mine)
                    + ("\n\nthe tree also changed:\n" + "\n".join(lines) if lines else "")
                    + _WHY, pytrace=False)
    if lines and spawned:
        pytest.fail(
            "the live results tree changed while this test ran:\n" + "\n".join(lines)
            + f"\n\nThis test made no such write in-process, but it spawned "
              f"{len(spawned)} subprocess(es) ({', '.join(sorted(set(spawned))[:3])}), whose "
              f"writes an audit hook in THIS interpreter cannot see. A child process is a "
              f"write this test caused, so it is charged here rather than excused: pass the "
              f"child a tmp_path root, or assert on its output without letting it write into "
              f"the live tree." + _WHY, pytrace=False)
    if lines:
        # Provably not this test: no in-process write under a watched root, and no child that
        # could have made one. Another process is writing — a live Phase 1 run, typically.
        # Recorded for one session-level notice, NOT charged to this test.
        _UNATTRIBUTED.extend(lines)


@pytest.fixture(scope="session", autouse=True)
def _no_writes_to_evidence(request):
    """Fail the session if a test wrote into `evidence/`. Too big to walk per test (61 ms).

    Raises from the fixture's teardown rather than calling `pytest.fail`, so the message
    reaches the report as an error on the session rather than being attributed to whichever
    test happened to run last. The audit channel supplies the name the diff cannot.
    """
    mark_w, mark_s = len(_WRITES), len(_SPAWNS)
    before = _snapshot(PER_SESSION)
    yield
    lines = _diff(before, _snapshot(PER_SESSION))

    ev_root = str(ROOT / "evidence") + os.sep
    culprits = sorted({(who, p[len(str(ROOT)) + 1:])
                       for who, _ev, p in _WRITES[mark_w:] if p.startswith(ev_root)})
    spawners = sorted({who for who, _a in _SPAWNS[mark_s:]})

    if culprits:
        detail = "\n".join(f"  {who}\n      wrote {p}" for who, p in culprits)
        raise AssertionError(
            "tests wrote into the live evidence tree:\n" + detail
            + ("\n\nthe tree also changed:\n" + "\n".join(lines) if lines else "")
            + _WHY)

    if lines and spawners:
        raise AssertionError(
            "the live evidence tree changed while the suite ran:\n" + "\n".join(lines)
            + f"\n\nNo test wrote there in this interpreter, but {len(spawners)} test(s) "
              f"spawned subprocesses, whose writes an audit hook here cannot see — so this "
              f"cannot be attributed to a concurrent run and is charged to the suite. "
              f"Spawning tests: {', '.join(spawners[:5])}" + _WHY)

    # Not a failure. The audit channel — which cannot be confounded by another process — says
    # no test in this interpreter wrote to a watched tree, and no test spawned a child that
    # could have. Something ELSE is writing, almost always a live Phase 1 script. The first
    # version of this file raised here and convicted 147 innocent tests of a live run's 690
    # calls (DEVIATIONS.md/DEV-P1-19).
    #
    # Reported rather than swallowed, and not for tidiness: while another process writes into
    # these trees the DIFF channel is void for the whole session, so the suite ran with one of
    # its two guards effectively disabled. That is a fact about the run's evidentiary value.
    #
    # Handed to `pytest_terminal_summary` rather than printed here. A `print` inside a fixture
    # teardown goes through pytest's capture and is shown only for a failing test — so on the
    # green run this notice describes, it would be captured and discarded. A notice that is
    # invisible in exactly the case it exists for is not a notice.
    _UNATTRIBUTED.extend(lines)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Report unattributable changes once, in the summary, where capture cannot eat them.

    Written to the terminal reporter rather than to stdout because the session fixture's
    teardown is inside pytest's capture: on a green run — which is precisely the run this
    notice describes — a `print` there is discarded and the operator learns nothing.
    """
    if not _UNATTRIBUTED:
        return
    n = len(set(_UNATTRIBUTED))
    tr = terminalreporter
    tr.write_sep("=", "concurrent writer", yellow=True)
    tr.write_line(
        f"{n} change(s) under results/ or evidence/ during this session were made by ANOTHER "
        f"PROCESS.", yellow=True)
    tr.write_line(
        "  No test wrote to a watched tree in this interpreter (audit hook: 0 charged writes) "
        "and no test spawned a child that could have. A live run is almost certainly in "
        "flight. Not charged to any test.")
    tr.write_line(
        "  But the tree-diff channel is VOID for this session — only the audit channel was in "
        "force. Re-run with no live run active for full two-channel coverage.")
    for line in sorted(set(_UNATTRIBUTED))[:10]:
        tr.write_line(f"  {line.strip()}")
    if n > 10:
        tr.write_line(f"  ... and {n - 10} more")
