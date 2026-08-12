#!/usr/bin/env python3
"""`runner/run.py`'s detach guards — the disk precondition, the scratch lifecycle, and the report.

Why this file exists
--------------------
Two lies and one wedge, all on 2026-08-12, all from the detach path.

The lies were printed together. `run.py --detach --label suite-06` emitted
`document process failed unexpectedly: ipc messaging received timeout signal` and, on the next
line, `detached as 'suite-06'`. A reader acts on the second one. The launch invocation's own
status answers "did SSM deliver and return cleanly", which is a different question from "is there
a job", and the old code answered the second question with the first one's silence.

The wedge was the instance going unreachable entirely: `PingStatus: ConnectionLost`,
`StatusDetails: Undeliverable`, `ResponseCode: -1`, EC2 status checks still `ok`. Cause, from the
console output rather than inference: `OSError: [Errno 28] No space left on device` inside
cloud-init, three boots in a row, 20 KB free on a 20 GiB volume. It could not self-heal because
growing the filesystem is `growpart`'s job and `growpart` runs from cloud-init. What filled it was
17 GB of pytest basetemps under `/opt/grx/tmp` that no job ever removed — `suite-05` 10 GB,
`suite-06` 6.2 GB — and `suite-06` died of that ENOSPC mid-run, leaving a 6371-byte log with zero
`FAILED` lines: a suite's worth of API calls spent to learn nothing.

Why these tests RUN the shell instead of reading it
--------------------------------------------------
Both guards are shell fragments assembled in Python, and asserting that a fragment contains
`-mtime` proves the string was written, not that the decision is right (feedback_vacuous_test_check).
So `disk_guard_commands()` and `detach_script()` are module-level builders taking their paths as
arguments, and every test below generates them against a `tmp_path` and executes them with `bash`.
The three decisions that matter — prune only what has FINISHED, refuse below the floor, keep a
failed job's scratch — are each checked by running the fragment in both states and comparing what
survived on disk.

Two of the three fragments only work on the platform they were written for, and this file says
which rather than quietly passing. `df -m --output=avail` is GNU coreutils, and `setsid` is a
util-linux binary macOS does not ship at all — without it the detach line fails into
`> /dev/null 2>&1` and writes no rc file, which is how the skip was discovered rather than
assumed. Those arms skip on the laptop and RUN on the runner, which is AL2023 and is where the
script executes for real; the file is therefore part of the runner suite's value, not only the
laptop suite's. The prune decision and the report logic are portable and run everywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner"))

import run as RUN          # noqa: E402

_GNU_DF = subprocess.run(["df", "-m", "--output=avail", "."],
                         capture_output=True).returncode == 0
_NEEDS_GNU_DF = pytest.mark.skipif(
    not _GNU_DF,
    reason="`df -m --output=avail` is GNU coreutils; the guard runs on AL2023, and this arm "
           "executes there. The prune and report arms in this file are portable and always run.")
# `setsid` is util-linux. macOS has no equivalent, and the detach line sends its own stderr to
# /dev/null by design, so on a laptop the job simply never starts and no rc file appears. Skipping
# is the honest report of that; the arm runs on the runner.
_NEEDS_SETSID = pytest.mark.skipif(
    shutil.which("setsid") is None,
    reason="`setsid` is util-linux and absent on macOS; the detached job cannot start at all here. "
           "This arm executes on the AL2023 runner, which is where detach_script() runs for real.")


def _bash(commands: list[str] | str) -> subprocess.CompletedProcess:
    """Run a generated fragment the way SSM does: one shell, commands joined by newlines.

    No `set -e`: `AWS-RunShellScript` does not use it either, and adding it here would make these
    tests pass on a script that only works under a stricter shell than the real one
    (feedback_verify_against_real_artifact).
    """
    script = commands if isinstance(commands, str) else "\n".join(commands)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def _aged(path: Path, days: int) -> None:
    """Backdate a directory so `find -mtime +N` sees it, without waiting N days."""
    when = time.time() - days * 86400
    os.utime(path, (when, when))


# --------------------------------------------------------------- the prune decision

def _scratch_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Five scratch dirs covering every state a job can leave one in.

    `old-running` gets a log written NOW: a five-day-old basetemp belonging to a job that is still
    printing is the case the guard must not touch, and `pytest --basetemp` only stamps that
    directory when it creates it, so scratch age says nothing about liveness. `orphan` has neither
    an rc file nor a log, which is what a job that died before it produced a line looks like.
    """
    tmpdir, logs = tmp_path / "tmp", tmp_path / "logs"
    for d in (tmpdir, logs):
        d.mkdir()
    for label, days, rc, log in (("old-done", 5, "0", True), ("old-failed", 5, "1", True),
                                 ("old-running", 5, None, True), ("new-done", 0, "0", True),
                                 ("orphan", 5, None, False)):
        s = tmpdir / label
        s.mkdir()
        (s / "basetemp.bin").write_bytes(b"x" * 4096)
        if rc is not None:
            (logs / f"{label}.rc").write_text(rc + "\n", encoding="utf-8")
        if log:
            (logs / f"{label}.log").write_text("....\n", encoding="utf-8")
        if days:
            _aged(s, days)
    return tmpdir, logs


def _prune_only(tmpdir: Path, logs: Path, prune_days: int = 2) -> subprocess.CompletedProcess:
    """The guard minus its free-space arm, so the prune decision can be read on any platform."""
    cmds = RUN.disk_guard_commands(str(tmpdir), str(logs), "probe", RUN.MIN_FREE_MB, prune_days)
    return _bash(cmds[:2])


def test_finished_scratch_older_than_the_window_is_removed(tmp_path):
    """Both finished labels go, whatever their exit code — a failed job is not exempt forever.

    `old-failed` is the interesting one. Keeping a failure's scratch is deliberate (see the
    lifecycle tests below), but keeping it *indefinitely* is exactly how 17 GB accumulated, so
    the keeping has to expire.
    """
    tmpdir, logs = _scratch_fixture(tmp_path)
    r = _prune_only(tmpdir, logs)
    assert r.returncode == 0, r.stderr
    assert not (tmpdir / "old-done").exists(), f"aged finished scratch survived:\n{r.stdout}"
    assert not (tmpdir / "old-failed").exists(), (
        f"an aged FAILED job's scratch was kept past the window; that is unbounded growth, which "
        f"is the wedge this guard exists for:\n{r.stdout}")
    assert "pruned scratch old-done" in r.stdout, r.stdout
    assert "rc=0" in r.stdout and "rc=1" in r.stdout, (
        f"the prune report must say what it removed and how that job ended:\n{r.stdout}")


def test_a_running_jobs_scratch_is_never_pruned_however_old(tmp_path):
    """No `.rc` file means the job may still be writing into that tree.

    This is the same corruption as the label collision of 05:33 UTC, approached from the other
    side: there, a second `pytest --basetemp` deleted a live run's `tmp_path` trees; here, a
    housekeeping sweep would. Age is not evidence a job finished — a nine-hour suite is older
    than the window while it runs.
    """
    tmpdir, logs = _scratch_fixture(tmp_path)
    r = _prune_only(tmpdir, logs)
    assert (tmpdir / "old-running").exists(), (
        f"scratch with no .rc file was deleted; a live run's basetemp went with it:\n{r.stdout}")
    assert "kept scratch old-running" in r.stdout, (
        f"a kept directory must say why it was kept:\n{r.stdout}")


def test_fresh_scratch_is_left_alone(tmp_path):
    """The just-finished job's trees are what a post-mortem reads first."""
    tmpdir, logs = _scratch_fixture(tmp_path)
    r = _prune_only(tmpdir, logs)
    assert (tmpdir / "new-done").exists(), (
        f"today's scratch was pruned, so a failure could not be inspected at all:\n{r.stdout}")


def test_the_prune_is_not_vacuous(tmp_path):
    """A mutation check: widen the window and nothing may be removed.

    Without this, a fragment whose `find` matched nothing would pass every assertion above by
    deleting nothing and being asked only about survivors.
    """
    tmpdir, logs = _scratch_fixture(tmp_path)
    r = _prune_only(tmpdir, logs, prune_days=99)
    assert r.returncode == 0, r.stderr
    for label in ("old-done", "old-failed", "old-running", "new-done"):
        assert (tmpdir / label).exists(), (
            f"{label} was pruned with a 99-day window, so the window is not what decides — "
            f"the earlier passes were measuring something else:\n{r.stdout}")
    assert "pruned scratch" not in r.stdout, r.stdout


def test_scratch_whose_job_died_without_an_rc_file_is_reclaimed(tmp_path):
    """The hole the `.rc` test alone leaves open, and the reason `suite-06` is in the docstring.

    An instance stop kills a job before it can record an exit code. Keeping that scratch on the
    "it may still be running" rule keeps it forever, which is the unbounded growth the guard was
    written against. An aged directory whose LOG is also aged is dead.
    """
    tmpdir, logs = _scratch_fixture(tmp_path)
    log = logs / "old-running.log"
    log.write_text("....\n", encoding="utf-8")
    _aged(log, 5)
    r = _prune_only(tmpdir, logs)
    assert not (tmpdir / "old-running").exists(), (
        f"scratch for a job with no rc file and a log untouched for 5 days was kept; that state is "
        f"permanent, so the volume fills:\n{r.stdout}")
    assert "died without recording an exit code" in r.stdout, r.stdout


def test_scratch_with_no_log_at_all_is_reclaimed(tmp_path):
    """A job that died before printing a line leaves neither an rc file nor a log.

    `find` on a missing path prints nothing, which is the same answer it gives for a log nobody has
    touched — so the two cases collapse into one rule, and this arm is what proves the missing-file
    branch is reached rather than erroring out of the loop.
    """
    tmpdir, logs = _scratch_fixture(tmp_path)
    r = _prune_only(tmpdir, logs)
    assert not (tmpdir / "orphan").exists(), (
        f"scratch with no rc file and no log was kept; nothing will ever create either, so that "
        f"is permanent:\n{r.stdout}")


# --------------------------------------------------------------- what --jobs claims

def test_a_job_with_no_exit_code_and_a_silent_log_is_not_called_running(tmp_path):
    """`suite-06` was reported RUNNING for an hour after its instance had been stopped.

    There was no process and there never would be an rc file. `RUNNING` is an inference from a
    missing file; the only local evidence is whether the log is still being written.
    """
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "wedged.log").write_text("....\n" * 84, encoding="utf-8")
    _aged(logs / "wedged.log", 1)
    r = _bash(RUN.jobs_commands(str(logs), RUN.STALE_MINUTES))
    assert r.returncode == 0, r.stderr
    assert "LOST?" in r.stdout, (
        f"a job with no rc file and a day-old log was reported as running:\n{r.stdout}")
    assert "RUNNING" not in r.stdout.split("(LOST?")[0], r.stdout


def test_a_job_written_to_just_now_is_still_called_running(tmp_path):
    """The distinguishing arm — otherwise every unfinished job would read as lost."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "live.log").write_text("....\n", encoding="utf-8")
    r = _bash(RUN.jobs_commands(str(logs), RUN.STALE_MINUTES))
    assert "RUNNING" in r.stdout, r.stdout
    assert "LOST?" not in r.stdout.split("(LOST?")[0], (
        f"a log written this second was called lost:\n{r.stdout}")


def test_a_finished_job_reports_its_code_and_is_never_guessed_about(tmp_path):
    """An rc file is fact and outranks any liveness heuristic, however old the log is."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "done.log").write_text("....\n", encoding="utf-8")
    (logs / "done.rc").write_text("143\n", encoding="utf-8")
    _aged(logs / "done.log", 30)
    r = _bash(RUN.jobs_commands(str(logs), RUN.STALE_MINUTES))
    assert "143" in r.stdout, r.stdout
    assert "LOST?" not in r.stdout.split("(LOST?")[0], (
        f"a recorded exit code was overridden by the staleness heuristic:\n{r.stdout}")


# --------------------------------------------------------------- the free-space floor

@_NEEDS_GNU_DF
def test_a_launch_is_refused_when_the_floor_is_not_met(tmp_path):
    """Exit 4, and a message that names the cost of ignoring it.

    The floor is set impossibly high here rather than by filling a disk: the decision under test
    is the comparison, and no test should need 6 GB of scratch to exercise it.
    """
    tmpdir, logs = tmp_path / "tmp", tmp_path / "logs"
    r = _bash(RUN.disk_guard_commands(str(tmpdir), str(logs), "suite-99",
                                      min_free_mb=10 ** 9, prune_days=2))
    assert r.returncode == 4, (
        f"a launch below the floor exited {r.returncode}, so `main()` would have gone on to start "
        f"the suite:\n{r.stdout}\n{r.stderr}")
    assert "REFUSING to start suite-99" in r.stdout, r.stdout
    assert "DEV-P4-31" in r.stdout, (
        f"the refusal must point at the deviation entry — a bare 'not enough space' does not tell "
        f"the next reader that the alternative is a wedged instance:\n{r.stdout}")


@_NEEDS_GNU_DF
def test_a_launch_with_room_is_allowed_and_says_the_numbers(tmp_path):
    """The other arm of the same comparison, so the guard is not simply always-refuse."""
    tmpdir, logs = tmp_path / "tmp", tmp_path / "logs"
    r = _bash(RUN.disk_guard_commands(str(tmpdir), str(logs), "suite-99",
                                      min_free_mb=1, prune_days=2))
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "free under" in r.stdout and "minimum 1 MB" in r.stdout, (
        f"the guard must print what it measured against what it required, so a later reader of a "
        f"job log can tell how much headroom that run actually had:\n{r.stdout}")
    assert "REFUSING" not in r.stdout, r.stdout


# --------------------------------------------------------------- the scratch lifecycle

def _run_detached(tmp_path, cmd: str, label: str = "job") -> tuple[Path, Path, Path]:
    """Execute the real `detach_script()` and wait for its `.rc` to appear.

    `setsid nohup ... &` means the fragment returns before the job does, which is the whole point
    of it, so the test polls for the rc file the same way `--jobs` does.
    """
    tmpdir, logs = tmp_path / "tmp", tmp_path / "logs"
    r = _bash(RUN.detach_script(cmd, label, str(tmpdir), str(logs)))
    assert "started " + label in r.stdout, f"{r.stdout}\n{r.stderr}"
    rc_file = logs / f"{label}.rc"
    for _ in range(100):
        if rc_file.is_file():
            break
        time.sleep(0.1)
    assert rc_file.is_file(), f"no rc file after 10s:\n{r.stdout}\n{r.stderr}"
    return tmpdir / label, logs / f"{label}.log", rc_file


@_NEEDS_SETSID
def test_a_job_that_succeeds_removes_its_own_scratch(tmp_path):
    """The missing half of the lifecycle: nothing cleaned up after a green run."""
    scratch, log, rc = _run_detached(tmp_path, "true", "green")
    assert rc.read_text().strip() == "0", rc.read_text()
    assert not scratch.exists(), (
        f"a successful job left its scratch behind; 26 modules copy the evidence tree into "
        f"`tmp_path`, so this is how 10 GB appears from one run. log:\n{log.read_text()}")
    assert "--- scratch" in log.read_text(), (
        "the job must record what its scratch cost, so growth is visible in the log rather than "
        "only in a df six days later")


@_NEEDS_SETSID
def test_a_job_that_fails_keeps_its_scratch_and_says_so(tmp_path):
    """The deliberate exception, and the reason `prune_days` has to exist.

    A failed suite's `tmp_path` trees are the only copy of what it was looking at. Deleting them
    on failure would make the guard tidy and the failure unreadable.
    """
    scratch, log, rc = _run_detached(tmp_path, "false", "red")
    assert rc.read_text().strip() == "1", rc.read_text()
    assert scratch.exists(), (
        f"a failed job's scratch was deleted, so there is nothing left to diagnose it with. "
        f"log:\n{log.read_text()}")
    assert "kept for post-mortem" in log.read_text(), log.read_text()


@_NEEDS_SETSID
def test_the_recorded_exit_code_is_the_commands_and_not_the_cleanups(tmp_path):
    """`rc=$?` is taken before `du`, `df` and `rm` run — each of which resets `$?`.

    Written as its own test because it is the failure that would be invisible: every job would
    report 0, `--jobs` would show a wall of green, and the logs would still hold the failures.

    `exit 42` rather than a program that exits 42, deliberately. The wrapper first used a brace
    group, `{ cmd ; }`, and a brace group does not contain an `exit` — the wrapper died with the
    command, no rc file was ever written, and `--jobs` would have shown the job as RUNNING
    indefinitely. That only reproduced on the runner, because on macOS the job could not start at
    all. The fragment now uses a subshell, and this is the case that distinguishes them.
    """
    _, _, rc = _run_detached(tmp_path, "exit 42", "coded")
    assert rc.read_text().strip() == "42", (
        f"the rc file holds {rc.read_text().strip()!r}, not 42 — a cleanup command's status was "
        f"recorded as the job's")


def test_the_scratch_is_per_label(tmp_path):
    """Two jobs must not share a basetemp, because pytest deletes the one it is given."""
    a = RUN.detach_script("pytest -q", "suite-a", "/opt/grx/tmp", "/opt/grx/logs")
    b = RUN.detach_script("pytest -q", "suite-b", "/opt/grx/tmp", "/opt/grx/logs")
    assert "TMPDIR=/opt/grx/tmp/suite-a" in a and "TMPDIR=/opt/grx/tmp/suite-b" in b
    assert "TMPDIR=/opt/grx/tmp/suite-a" not in b


# --------------------------------------------------------------- the detach report

class _Ssm:
    """A stub SSM client that records each command list and replays a scripted outcome per call.

    Deliberately positional-blind about nothing: `send_command`'s parameters are asserted, because
    a detach that lost `workingDirectory` or `executionTimeout` would still "work" in a test that
    only counted invocations, and would then run in the wrong directory on the instance.
    """

    def __init__(self, outcomes: dict[int, tuple[str, int, str]] | None = None) -> None:
        self.sent: list[list[str]] = []
        self.outcomes = outcomes or {}

    def send_command(self, InstanceIds, DocumentName, TimeoutSeconds, Parameters):
        assert DocumentName == "AWS-RunShellScript", DocumentName
        assert Parameters["workingDirectory"] == [RUN.REPO], Parameters
        self.sent.append(Parameters["commands"])
        return {"Command": {"CommandId": f"cid-{len(self.sent) - 1}"}}

    def get_command_invocation(self, CommandId, InstanceId):
        i = int(CommandId.rsplit("-", 1)[1])
        status, rc, out = self.outcomes.get(i, ("Success", 0, ""))
        return {"Status": status, "ResponseCode": rc,
                "StandardOutputContent": out, "StandardErrorContent": ""}


def _detach(monkeypatch, capsys, outcomes, argv=("--detach", "--label", "suite-07", "pytest -q")):
    ssm = _Ssm(outcomes)
    monkeypatch.setattr(RUN, "_client", lambda: (ssm, "i-0stub"))
    monkeypatch.setattr(sys, "argv", ["run.py", *argv])
    rc = RUN.main()
    return rc, ssm, capsys.readouterr()


# Invocation order on the detach path: 0 label check, 1 disk guard, 2 launch, 3 confirmation.
_LAUNCH, _CONFIRM = 2, 3


def test_a_clean_detach_reports_success_once(monkeypatch, capsys):
    rc, ssm, cap = _detach(monkeypatch, capsys, {})
    assert rc == 0, cap.err
    assert "detached as 'suite-07'" in cap.out, cap.out
    assert len(ssm.sent) == 4, (
        f"expected label check, disk guard, launch and confirmation; got {len(ssm.sent)} "
        f"invocation(s). If the confirmation is gone, the detach is being reported from the "
        f"launch's own status again")


def test_a_launch_error_is_not_reported_as_a_detach(monkeypatch, capsys):
    """The exact 2026-08-12 shape: the launch invocation failed and the job did not start.

    `detached as` must not appear on stdout at all, and the exit code must be non-zero — a caller
    that only checks the status is the caller this failed for.
    """
    rc, _, cap = _detach(monkeypatch, capsys, {
        _LAUNCH: ("Failed", -1, "document process failed unexpectedly: ipc messaging received "
                                "timeout signal"),
        _CONFIRM: ("Failed", 5, "NOT STARTED: /opt/grx/logs/suite-07.log does not exist"),
    })
    assert rc != 0, "a detach that started nothing exited 0"
    assert "detached as" not in cap.out, (
        f"'detached as' was printed for a job that does not exist:\n{cap.out}")
    assert "detach FAILED" in cap.err, cap.err
    assert "nothing is running" in cap.err, cap.err


def test_a_confirmed_job_under_a_failed_launch_reports_both(monkeypatch, capsys):
    """The ambiguous case, which is the common one: SSM faulted but the job is alive.

    Reporting only "detached" hides the fault; reporting only the fault sends someone to start a
    second job under the same label. So both are printed and the status stays non-zero.
    """
    rc, _, cap = _detach(monkeypatch, capsys, {
        _LAUNCH: ("Failed", -1, "ipc messaging received timeout signal"),
    })
    assert rc != 0, "an SSM fault on the launch path exited 0, so no caller can see it"
    assert "CONFIRMED on the instance" in cap.err, cap.err
    assert "launch invocation exited" in cap.err, cap.err


def test_the_disk_guards_refusal_stops_the_launch(monkeypatch, capsys):
    """Exit 4 from the guard must mean no launch invocation is sent at all."""
    rc, ssm, cap = _detach(monkeypatch, capsys, {1: ("Failed", 4, "REFUSING to start suite-07")})
    assert rc == 4, f"{rc}: {cap.out}{cap.err}"
    assert len(ssm.sent) == 2, (
        f"the suite was launched anyway — {len(ssm.sent)} invocations sent after a refusal")
    assert "detached as" not in cap.out, cap.out


def test_a_taken_label_still_stops_before_the_disk_guard(monkeypatch, capsys):
    """The pre-existing guard, re-asserted because the new one was inserted next to it."""
    rc, ssm, cap = _detach(monkeypatch, capsys,
                           {0: ("Failed", 3, "label suite-07 is already in use")})
    assert rc == 3, f"{rc}: {cap.out}{cap.err}"
    assert len(ssm.sent) == 1, f"{len(ssm.sent)} invocations sent after a label refusal"


def test_the_guards_are_wired_into_the_detach_path_and_not_merely_defined(monkeypatch, capsys):
    """A builder nothing calls is not a guard (feedback_no_deploy_path_no_component).

    Read off the recorded invocations rather than the source, so a refactor that keeps the
    functions but stops calling them fails here.
    """
    _, ssm, _ = _detach(monkeypatch, capsys, {})
    guard = "\n".join(ssm.sent[1])
    assert "REFUSING to start suite-07" in guard and f"-mtime +{RUN.PRUNE_DAYS}" in guard, guard
    assert str(RUN.MIN_FREE_MB) in guard, guard
    launch = "\n".join(ssm.sent[_LAUNCH])
    assert f"TMPDIR={RUN.TMPDIR}/suite-07" in launch, launch
    assert "kept for post-mortem" in launch, (
        "the launch script no longer carries the scratch lifecycle, so nothing cleans up after a "
        "job again")
