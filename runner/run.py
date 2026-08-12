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
        return _wait(ssm, _send(ssm, iid, [
            f"mkdir -p {LOGS}",
            f"for f in {LOGS}/*.log; do [ -e \"$f\" ] || continue; "
            f'b=$(basename "$f" .log); '
            f'rc=$(cat {LOGS}/$b.rc 2>/dev/null || echo RUNNING); '
            f'printf "%-44s %-8s %8s lines  %s\\n" "$b" "$rc" "$(wc -l < "$f")" '
            f'"$(stat -c %y "$f" | cut -d. -f1)"; done',
        ]), iid)

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
    if not args.force:
        q = shlex.quote(label)
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
    # `setsid` detaches from the SSM agent's session, so the job is not killed when the invocation
    # ends. The rc file is written by the same subshell that runs the command, so it cannot be
    # written by a wrapper that exited for a different reason.
    #
    # TMPDIR is per LABEL, overriding the shared PREAMBLE. Two jobs sharing scratch is not a
    # tidiness question: `pytest --basetemp=DIR` REMOVES DIR at startup, so a second suite run
    # deleted the first one's `tmp_path` trees mid-flight and both runs became unreportable — one
    # measured, at 05:33 UTC on 2026-08-12, from a label collision that should not have been
    # possible either (see the --force guard above). A job's scratch is its own, and the job is what
    # cleans it, so a per-label directory is both the isolation and the bound.
    scratch = f"{TMPDIR}/{label}"
    script = (f"mkdir -p {LOGS} {scratch} && "
              f"setsid nohup env TMPDIR={scratch} bash -c "
              f"'{{ {cmd} ; }} > {LOGS}/{label}.log 2>&1; "
              f"echo $? > {LOGS}/{label}.rc' < /dev/null > /dev/null 2>&1 & "
              f"sleep 2; echo started {label} with TMPDIR={scratch}; "
              f"pgrep -fa {shlex.quote(cmd.split()[0])} | head -3")
    rc = _wait(ssm, _send(ssm, iid, pre + [script]), iid)
    print(f"\ndetached as {label!r}. Follow with:\n"
          f"  runner/run.py --tail {label}\n"
          f"  runner/run.py --jobs")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
