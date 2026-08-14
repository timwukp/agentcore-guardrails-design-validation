#!/usr/bin/env python3
"""Run a command on the runner — waiting for it, or detaching it so it outlives the laptop.

Two modes, because the two jobs are different
---------------------------------------------
`--wait` is for checks: refresh the code, run the offline suite, print a `--help`. It blocks and
returns the instance's exit code, so a failed check fails here.

`--detach` is the reason the instance exists. The command is started under `setsid nohup`, its
output goes to `/opt/grx/logs/<label>.log`, and its exit code is written to
`/opt/grx/logs/<label>.rc` **when it finishes**. Nothing is streamed, nothing is waited on, and
closing the laptop has no effect. `--label` names the job so `--tail` and `--jobs` can find it.

Why the exit code is a FILE rather than a return value
------------------------------------------------------
A detached command's exit status has nowhere to go — the SSM invocation that started it has
already returned. Writing it to `<label>.rc` means "did it finish, and how" is a fact on disk that
survives a disconnect, which is exactly the property a batch loop's exit code does not have
(feedback_batch_loop_exit_code: a loop's status is only its last iteration). `--jobs` reads those
files rather than inferring completion from a process listing, so a job that died between two
polls is still reported as finished-with-a-code and not as "no longer running".

Why a detach is confirmed from the instance rather than from its own launch invocation
-------------------------------------------------------------------------------------
On 2026-08-12 this script printed `document process failed unexpectedly: ipc messaging received
timeout signal` and, on the next line, `detached as 'suite-06'`. Both cannot be true of the same
run, and the second one is the one a reader acts on. The launch invocation's status answers "did
SSM deliver and return cleanly", which is not the question; the question is "is there a job".
So the launch is followed by a second command that looks for `<label>.log` on the instance, and
the message a caller reads is built from what that found — not from the launch's own exit code
(`feedback_build_reported_success_built_nothing`).

Why a disk precondition, and why scratch is pruned before a launch
------------------------------------------------------------------
The same day, the instance became unreachable entirely: `PingStatus: ConnectionLost`,
`StatusDetails: Undeliverable`, `ResponseCode: -1`, EC2 status checks still `ok`. The console
output named the cause — `OSError: [Errno 28] No space left on device` in cloud-init, three boots
in a row with 20 KB free on a 20 GiB volume — and the reason it could not self-heal: growing the
filesystem is `growpart`'s job, `growpart` runs from cloud-init, and cloud-init needs disk to
start. What filled it was 17 GB of pytest basetemps under `/opt/grx/tmp` that no job removed:
`suite-05` 10 GB and `suite-06` 6.2 GB. `suite-06` died of ENOSPC mid-run and left a 6371-byte
log with zero `FAILED` lines, i.e. no result at all — a nine-minute suite spent to learn nothing.
So a launch now (a) removes the scratch of jobs that have finished and are older than
`PRUNE_DAYS`, (b) refuses to start when less than `MIN_FREE_MB` remains, and (c) has each job
delete its own scratch when it exits zero. A job that fails keeps its scratch, because that is
the one time the trees are worth reading; `PRUNE_DAYS` is what bounds it.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runner"))
import provision as PV           # noqa: E402

REPO = "/opt/grx/grx-validation"
LOGS = "/opt/grx/logs"
PY = f"{REPO}/.venv-oracle/bin/python -u"

# Every command runs with TMPDIR on the ROOT VOLUME, not in /tmp.
#
# Measured on the first instance: AL2023 mounts /tmp as a tmpfs sized at half of RAM — 957 MB on a
# t3.small — and the offline suite fills it. 26 test modules copy the evidence tree into their
# `tmp_path`, so one suite run wrote 954 MB of pytest scratch and the NEXT command failed with
# `[Errno 28] No space left on device` while `df` on the repo still showed 18 GB free. The error
# names the wrong thing (it looks like a full disk; the disk is 15% used), which is the shape
# feedback_cryptic_error_is_missing_guard describes: assert the precondition rather than widen a
# retry. Here the precondition is "scratch space is on the 20 GiB volume".
TMPDIR = "/opt/grx/tmp"
PREAMBLE = [f"export TMPDIR={TMPDIR}", f"mkdir -p {TMPDIR}"]

# One offline suite's measured high-water mark, plus a little. 26 test modules copy the evidence
# tree into their `tmp_path`, and the measurements agree with each other: `suite-05` left 10 GB of
# basetemps behind, and `suite-07` was at 9,882 MB while still running. So the floor is that number
# rounded up, not a round guess — a floor BELOW what a suite consumes would admit exactly the
# launch it exists to refuse, and refusing is far cheaper than the rescue a full root volume costs
# (a stop, a volume detach, a helper instance, `growpart`, `xfs_growfs`, a reattach).
MIN_FREE_MB = 12288
# Long enough that yesterday's failure is still readable, short enough that two failures cannot
# add up to a wedged instance before anyone looks.
PRUNE_DAYS = 2
# How long the identity guard waits for IMDS to stop serving the role the hourly association had
# attached. Measured: the profile re-attachment is immediate, and a fresh `sts:GetCallerIdentity` on
# the instance reported the correct role within about 100 seconds of the repair on 2026-08-13. Twelve
# attempts at ten seconds is ~120 s, which is that observation plus headroom rather than a round
# guess. Erring long costs a launch two minutes; erring short spends a case's run.
IDENTITY_TRIES = 12
IDENTITY_SLEEP_S = 10
# How long a job's log may go unwritten before `--jobs` stops calling it RUNNING. The offline suite
# finishes in about sixteen minutes and prints as it goes; the longest single case measured is an
# F4 cell at roughly nine. 45 minutes is therefore silence no live job of this project produces,
# and erring long is deliberate: a false `LOST?` would send someone to relaunch a job that is
# working, which is the more expensive mistake.
STALE_MINUTES = 45


def _client():
    """The SSM client and instance id, plus a profile check on every command — including `--tail`.

    Checking on the polling path looks like overkill and is the opposite. An account-wide SSM
    association re-attaches a broader profile to every instance in this Region hourly
    (`PV.ensure_instance_profile()` has the CloudTrail evidence), and a detached suite run outlives
    that interval: it downloads nothing after bootstrap but it DOES `aws s3 sync` its results at the
    end, with whatever identity it has by then. So a `--tail` that repairs while it polls is the
    mechanism that gets a long run's output uploaded at all. One `describe` per poll is free next to
    losing a nine-minute run's results.
    """
    st = json.loads(PV.STATE_PATH.read_text(encoding="utf-8")) \
        if PV.STATE_PATH.is_file() else None
    if not st:
        raise SystemExit("runner/.state/runner.json is missing — run runner/provision.py first")
    if repaired := PV.ensure_instance_profile(
            boto3.client("ec2", region_name=st["region"]), st["instance_id"]):
        print(f"! {repaired}")
    return boto3.client("ssm", region_name=st["region"]), st["instance_id"]


def _send(ssm, iid: str, commands: list[str], timeout: int = 3600) -> str:
    return ssm.send_command(
        InstanceIds=[iid], DocumentName="AWS-RunShellScript",
        TimeoutSeconds=600,
        Parameters={"commands": PREAMBLE + commands, "executionTimeout": [str(timeout)],
                    "workingDirectory": [REPO]})["Command"]["CommandId"]


def _wait(ssm, cid: str, iid: str, poll: int = 5, limit: int = 720) -> int:
    for _ in range(limit):
        inv = ssm.get_command_invocation(CommandId=cid, InstanceId=iid)
        if inv["Status"] not in ("Pending", "InProgress", "Delayed"):
            out = (inv["StandardOutputContent"] or "").rstrip()
            err = (inv["StandardErrorContent"] or "").rstrip()
            if out:
                print(out)
            if err:
                print("--- stderr", file=sys.stderr)
                print(err, file=sys.stderr)
            # SSM truncates each stream at 24 KB. Say so rather than let a reader assume the
            # output they got is all of it.
            if len(inv.get("StandardOutputContent") or "") >= 24_000:
                print("\n[output truncated by SSM at 24 KB — use --detach and --tail for more]")
            return inv.get("ResponseCode", 1) if inv["Status"] != "Success" else 0
        time.sleep(poll)
    raise SystemExit(f"still running after {poll * limit}s; use --detach for long work")


def identity_guard_commands(role_name: str, *, tries: int, sleep_s: int) -> list[str]:
    """Wait until the instance actually presents `role_name`, and refuse the launch if it never does.

    `PV.ensure_instance_profile()` re-attaches the least-privilege profile that the hourly
    account-wide `AWS-AttachIAMToInstance` association keeps replacing. Re-attaching is not the same
    as taking effect: the profile association changes immediately, but IMDS keeps serving the OLD
    role's credentials for a while afterwards, and every `aws` and `boto3` call on the instance is a
    fresh process reading IMDS. So a job launched in the seconds after a repair runs as the role that
    was just removed.

    That is not a hypothetical. F1-6 ran on 2026-08-13 at 14:17 UTC, one second after `sync.py push`
    printed the re-attachment, and all eight of its `CreateGuardrail` probes came back
    `AccessDeniedException` — on a role whose inline policy grants `bedrock:CreateGuardrail` on `*`
    with no condition. The case's own confound classifier caught it and correctly recorded
    INCONCLUSIVE rather than scoring an access error as the claim holding, so no false verdict was
    published. But the run was still spent, and a suite of cases launched the same way would each
    have burned a run to discover the same thing.

    Why this WAITS rather than merely refusing: refusing would be correct and useless. The condition
    clears by itself within a minute or two, and every launch path on this runner is initiated by a
    laptop command that has just called `ensure_instance_profile` — so the moment a repair happens is
    exactly the moment a launch is about to happen. Polling here makes the runner self-healing on the
    only path that matters, which is the same argument `ensure_instance_profile` makes for repairing
    rather than refusing.

    The match requires a TRAILING SLASH after the role name (`assumed-role/grx-runner-ec2/`) because
    an assumed-role ARN ends with the session name. Without it, a differently-privileged role whose
    name merely begins with the expected one — `grx-runner-ec2-readonly` is the kind of thing that
    gets created next to it — would satisfy the guard, and the guard exists precisely to catch a
    substituted identity.

    A failed `sts` call is treated as a non-match rather than an error to propagate, because the
    reason it fails is usually that there are no credentials yet, which is the very state being
    waited out. It must never read as a pass: a guard that cannot run must not report clean
    (feedback_guard_tool_exit_codes).

    Returned as a list of separate SSM commands, and the refusal is `exit 6` — the invocation's exit
    status rather than a line of output a caller may not read, matching `disk_guard_commands`'s
    `exit 4`. Built here rather than inline in `main()` so a test can RUN the generated shell against
    a stub `aws`; asserting on the text of a shell fragment proves only that the text was written.
    """
    return [
        f'seen=""; ok=""',
        f"for i in $(seq 1 {tries}); do "
        f'arn=$(aws sts get-caller-identity --query Arn --output text 2>/dev/null) || arn=""; '
        f'[ -n "$arn" ] || arn="NO-CREDENTIALS"; '
        f'seen="$arn"; '
        f'case "$arn" in *assumed-role/{role_name}/*) ok="$arn"; break ;; esac; '
        f'echo "identity is $arn, waiting for {role_name} '
        f'(attempt $i/{tries})"; sleep {sleep_s}; done',
        f'if [ -z "$ok" ]; then '
        f'echo "REFUSING to start: the instance presents $seen, not {role_name}, after '
        f'{tries} attempt(s) over ~{tries * sleep_s}s. An hourly account-wide '
        f'AWS-AttachIAMToInstance association replaces this instance profile, and IMDS serves the '
        f'old role for a short while after it is re-attached. A case run under the wrong role gets '
        f'AccessDeniedException on calls its own role permits, which its confound classifier will '
        f'record as INCONCLUSIVE — a spent run, not a verdict. Re-run the laptop command to repair '
        f'the profile, then launch again."; exit 6; fi',
        f'echo "identity confirmed: $ok"',
    ]


def disk_guard_commands(tmpdir: str, logs: str, label: str,
                        min_free_mb: int, prune_days: int) -> list[str]:
    """Prune finished scratch, then refuse the launch if the volume is still too tight.

    Prune first, THEN measure — so a launch that only needs yesterday's finished scratch removed
    succeeds instead of refusing on a number it could have improved.

    `<label>.rc` present is the first test for "finished". A directory whose job is still running
    is never touched, however old it is, because `pytest --basetemp=DIR` deletes DIR at startup and
    pruning a live run's scratch is the same corruption from the other end (measured at 05:33 UTC
    on 2026-08-12 from a label collision).

    There is a second test, because the first one alone reopens the hole it was written to close. A
    job killed by an instance STOP never writes its `.rc` — `suite-06` is exactly that: a log, no
    rc file, no process, and `--jobs` calling it RUNNING hours after the instance was rebooted
    under it. Scratch in that state would be kept forever, which is unbounded growth again. So an
    aged directory whose LOG has also not been touched for `prune_days` is treated as dead. The
    suite it guards takes sixteen minutes; a log silent for two days is not a running job by any
    reading, and the alternative is a volume that fills on somebody else's timetable.

    Taken as a list of separate SSM commands rather than one string so the refusal is the
    invocation's exit status (4), not a line of output a caller may not read. Built here, and not
    inline in `main()`, so a test can generate it against a temporary directory and RUN it —
    asserting on the text of a shell fragment proves only that the text was written.
    """
    return [
        f"mkdir -p {tmpdir} {logs}",
        f"for d in $(find {tmpdir} -mindepth 1 -maxdepth 1 -type d -mtime +{prune_days}); do "
        f'b=$(basename "$d"); why=""; '
        f"if [ -f {logs}/$b.rc ]; then "
        f'why="job finished rc=$(cat {logs}/$b.rc)"; '
        # An absent log counts as untouched, which is why the test is "not modified recently"
        # rather than "modified long ago": `find` on a missing path prints nothing either way.
        f'elif [ -z "$(find {logs}/$b.log -mtime -{prune_days} 2>/dev/null)" ]; then '
        f'why="no .rc, and {logs}/$b.log has not been written for {prune_days} day(s) — '
        f'the job died without recording an exit code (an instance stop does this)"; fi; '
        f'if [ -n "$why" ]; then sz=$(du -sm "$d" | cut -f1); rm -rf "$d" && '
        f'echo "pruned scratch $b: ${{sz}} MB, $why"; '
        f'else echo "kept scratch $b: no .rc file and its log is still being written"; fi; done',
        f"free=$(df -m --output=avail {tmpdir} | tail -1 | tr -d ' ')",
        f'echo "free under {tmpdir}: ${{free}} MB (minimum {min_free_mb} MB)"',
        f'if [ "$free" -lt {min_free_mb} ]; then '
        f'echo "REFUSING to start {label}: ${{free}} MB free is below the {min_free_mb} MB a suite '
        f"needs. A run that fills this volume does not merely fail — it takes cloud-init down with "
        f"it and the instance stops answering SSM at all, which costs a stop, a volume detach, a "
        f"helper instance and a growpart to undo (DEV-P4-31). Free space first: "
        f'runner/run.py \\"du -sm {tmpdir}/*\\"."; exit 4; fi',
    ]


def jobs_commands(logs: str, stale_minutes: int) -> list[str]:
    """One line per job: label, exit code, log size, last write.

    Why a job with no `.rc` is not simply called RUNNING
    ---------------------------------------------------
    It was, and it was wrong. `suite-06` was reported as `RUNNING` with 84 lines for an hour after
    the instance it was on had been stopped, its volume detached and grown, and the instance
    started again — there was no process, and there never would be an rc file. "RUNNING" is an
    inference from a missing file; the only local evidence about liveness is whether the log is
    still being written. So a job whose log has been silent for `stale_minutes` is reported as
    `LOST?`, with the question mark meaning exactly what it says: a genuinely quiet job (a long
    single test, a `sleep`) would read the same way, and the way to settle it is `--tail`.
    """
    return [
        f"mkdir -p {logs}",
        f"for f in {logs}/*.log; do "
        f'[ -e "$f" ] || continue; '
        f'b=$(basename "$f" .log); '
        f"rc=$(cat {logs}/$b.rc 2>/dev/null || echo RUNNING); "
        f'if [ "$rc" = RUNNING ] && [ -n "$(find "$f" -mmin +{stale_minutes})" ]; '
        f'then rc="LOST?"; fi; '
        # `stat -c` is GNU and `date -r FILE +FMT` is the BSD spelling; taking whichever answers
        # keeps this line readable on a laptop as well as on the instance, in one format.
        f't=$(stat -c %y "$f" 2>/dev/null | cut -d. -f1); '
        f'[ -n "$t" ] || t=$(date -r "$f" "+%Y-%m-%d %H:%M:%S"); '
        f'printf "%-44s %-8s %8s lines  %s\\n" "$b" "$rc" "$(wc -l < "$f")" "$t"; done',
        f'echo "(LOST? = no exit code recorded and no log write for {stale_minutes} min; '
        f'confirm with --tail)"',
    ]


def detach_script(cmd: str, label: str, tmpdir: str, logs: str) -> str:
    """The one-liner that starts a job, records its exit code, and cleans up after itself.

    `setsid` detaches from the SSM agent's session, so the job is not killed when the invocation
    ends. The rc file is written by the same subshell that runs the command, so it cannot be
    written by a wrapper that exited for a different reason, and `rc=$?` is taken on the line
    immediately after the command — before `du` or `df` can overwrite `$?`.

    TMPDIR is per LABEL, overriding the shared PREAMBLE, and the job removes its own scratch when
    it exits zero. A job that FAILS keeps its scratch, because that is the one time the `tmp_path`
    trees are worth reading; `prune_days` in `disk_guard_commands` is what bounds the keeping. The
    combination is what was missing when 17 GB of `suite-05` and `suite-06` basetemps filled the
    root volume (this module's docstring).
    """
    scratch = f"{tmpdir}/{label}"
    return (f"mkdir -p {logs} {scratch} && "
            f"setsid nohup env TMPDIR={scratch} bash -c "
            # A SUBSHELL, not a brace group. `{ exit 42 ; }` exits the wrapper itself, so the rc
            # file is never written and `--jobs` reports the job as RUNNING forever — measured on
            # the runner, not reasoned about. A subshell's `exit` ends only the subshell, which is
            # what makes the claim above ("the rc file is written by the same subshell") true for
            # any command and not just for external programs. It also contains a `cd`.
            f"'( {cmd} ) > {logs}/{label}.log 2>&1; "
            f"rc=$?; echo $rc > {logs}/{label}.rc; "
            f"sz=$(du -sm {scratch} 2>/dev/null | cut -f1); "
            # `df | tail -1` and no `tr`: this whole script is inside `bash -c '...'`, where a
            # backslash is literal, so an escaped quote would reach `tr` as an argument to delete
            # rather than as quoting. The leading whitespace in the number is cosmetic.
            f'echo "--- scratch {scratch}: ${{sz}} MB; free after:'
            f'$(df -m --output=avail {tmpdir} 2>/dev/null | tail -1) MB" '
            f">> {logs}/{label}.log; "
            f'if [ "$rc" = 0 ]; then rm -rf {scratch}; '
            f'else echo "--- scratch kept for post-mortem (rc=$rc)" >> {logs}/{label}.log; fi'
            f"' < /dev/null > /dev/null 2>&1 & "
            f"sleep 2; echo started {label} with TMPDIR={scratch}; "
            f"pgrep -fa {shlex.quote(cmd.split()[0])} | head -3")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="*", help="shell command to run in the repo root")
    ap.add_argument("--detach", action="store_true", help="start it and return immediately")
    ap.add_argument("--label", help="job name for --detach (default: derived from the command)")
    ap.add_argument("--force", action="store_true",
                    help="reuse a label that already has a log (truncates it; see --detach above)")
    ap.add_argument("--tail", metavar="LABEL", help="print the last 200 lines of a job's log")
    ap.add_argument("--jobs", action="store_true", help="list detached jobs and their exit codes")
    ap.add_argument("--refresh", action="store_true",
                    help="run grx-refresh first, so the instance has the current tree")
    args = ap.parse_args()

    ssm, iid = _client()

    if args.jobs:
        return _wait(ssm, _send(ssm, iid, jobs_commands(LOGS, STALE_MINUTES)), iid)

    if args.tail:
        return _wait(ssm, _send(ssm, iid, [
            f"tail -n 200 {LOGS}/{shlex.quote(args.tail)}.log",
            f"echo '--- rc:' $(cat {LOGS}/{shlex.quote(args.tail)}.rc 2>/dev/null || echo RUNNING)",
        ]), iid)

    if not args.command:
        ap.error("give a command, or use --jobs / --tail")
    cmd = " ".join(args.command)
    pre = ["grx-refresh"] if args.refresh else []

    if not args.detach:
        return _wait(ssm, _send(ssm, iid, pre + [cmd]), iid)

    label = args.label or "".join(
        c if c.isalnum() or c in "-_." else "_" for c in cmd)[:60]
    # A label already in use is refused, because reusing one is silent and destructive on both
    # sides: `> <label>.log` truncates the running job's output, and both jobs then race to write
    # `<label>.rc`. Measured once — a flaky network made a retry loop fire `--detach --label
    # suite-03` twice ten seconds apart, and `--jobs` afterwards reported `suite-03  rc 1  0 lines`,
    # which is not what happened to either job. An empty log beside a failing exit code is a lie
    # about the run, and a lie that reads like a fast failure is worse than an error
    # (feedback_cryptic_error_is_missing_guard). --force is the escape hatch, and it says so.
    q = shlex.quote(label)
    if not args.force:
        # Exits NON-ZERO when the label is taken, so the refusal is the command's status and not a
        # line of output the caller may or may not read.
        rc = _wait(ssm, _send(ssm, iid, [
            f"if [ -e {LOGS}/{q}.log ]; then "
            f"echo \"label {label} is already in use (rc: "
            f"$(cat {LOGS}/{q}.rc 2>/dev/null || echo STILL-RUNNING), "
            f"$(wc -l < {LOGS}/{q}.log) lines). Pick another --label, or --force to overwrite.\"; "
            f"exit 3; fi; echo \"label {label} is free\""]), iid)
        if rc:
            return rc

    # Identity BEFORE disk: both refuse the launch, but a wrong-role launch spends a case's run and
    # publishes an INCONCLUSIVE that says nothing about the document, whereas a full volume refuses
    # before anything runs. Check the one that can waste measurement first.
    rc = _wait(ssm, _send(ssm, iid,
                          identity_guard_commands(PV.ROLE_NAME,
                                                  tries=IDENTITY_TRIES,
                                                  sleep_s=IDENTITY_SLEEP_S)), iid)
    if rc:
        return rc

    rc = _wait(ssm, _send(ssm, iid,
                          disk_guard_commands(TMPDIR, LOGS, label,
                                              MIN_FREE_MB, PRUNE_DAYS)), iid)
    if rc:
        return rc

    launch_rc = _wait(ssm, _send(ssm, iid, pre + [
        detach_script(cmd, label, TMPDIR, LOGS)]), iid)

    # Ground truth, asked of the instance. See the docstring: the launch invocation's own status
    # answered a different question, and answering it out loud is how `detached as 'suite-06'` got
    # printed under `document process failed unexpectedly`.
    started = _wait(ssm, _send(ssm, iid, [
        f"if [ -e {LOGS}/{q}.log ]; then "
        f'echo "confirmed on the instance: {LOGS}/{label}.log exists '
        f"(rc: $(cat {LOGS}/{q}.rc 2>/dev/null || echo RUNNING), "
        f'$(wc -l < {LOGS}/{q}.log) lines)"; else '
        f'echo "NOT STARTED: {LOGS}/{label}.log does not exist"; exit 5; fi']), iid)

    if started:
        print(f"\ndetach FAILED — nothing is running under {label!r}. The launch invocation exited "
              f"{launch_rc} and the confirmation exited {started}; neither found a log on the "
              f"instance. Re-run it, or check `runner/run.py --jobs`.", file=sys.stderr)
        return started or 1
    if launch_rc:
        # Confirmed running, but the launch reported an error — say both and fail. Returning 0 here
        # would make an SSM fault invisible to any caller that only checks the exit code, and the
        # honest state is "it is running AND something went wrong".
        print(f"\ndetached as {label!r} — CONFIRMED on the instance, but the launch invocation "
              f"exited {launch_rc}, so something in the SSM path also failed. Read that error "
              f"before trusting the run:\n"
              f"  runner/run.py --tail {label}\n"
              f"  runner/run.py --jobs", file=sys.stderr)
        return launch_rc
    print(f"\ndetached as {label!r}. Follow with:\n"
          f"  runner/run.py --tail {label}\n"
          f"  runner/run.py --jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
