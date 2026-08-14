"""The identity guard: does the instance actually present the least-privilege role?

WHY THIS FILE EXISTS

`runner/provision.py:ensure_instance_profile()` re-attaches the `grx-runner-ec2` profile that an
hourly account-wide `AWS-AttachIAMToInstance` association keeps replacing. Re-attaching is not the
same as taking effect. The association changes immediately; IMDS keeps serving the OLD role's
credentials for a while afterwards, and every `aws`/`boto3` call on the instance is a fresh process
that reads IMDS. So a job launched in the seconds after a repair runs as the role that was just
removed.

Measured, not imagined: F1-6 launched on 2026-08-13 at 14:17:05 UTC, one second after `sync.py push`
printed the re-attachment, and all eight of its `CreateGuardrail` probes returned
`AccessDeniedException` — against a role whose inline policy grants `bedrock:CreateGuardrail` on `*`
with no condition at all. The case's confound classifier did its job and recorded INCONCLUSIVE rather
than scoring an access error as the claim holding, so nothing false was published. The run was still
spent, and fifteen cases launched the same way would each have spent one.

WHAT THESE ARMS ACTUALLY EXERCISE

The generated shell is RUN, against a stub `aws` on PATH whose answers this file controls. Asserting
on the text of a shell fragment proves only that the text was written — the same argument
`disk_guard_commands`' own tests make, and the reason the stub returns a real ARN string rather than
a sentinel: the guard's match is a `case` pattern against ARN syntax, so a stub that returned
`"WRONG"` would exercise a shape the real caller never produces.

The stub also lets the WAIT be tested, which is the half that matters most. A guard that only refused
would be correct and useless: the condition clears by itself in a minute or two, and the moment a
repair happens is exactly the moment a launch is about to happen. `test_..._settles_on_a_later_attempt`
is the arm that pins the polling, using a counter file so the stub can answer differently per call.

MUTANT / KILL TABLE (each mutant applied to `runner/run.py`, restored by `cp` from a backup that was
diffed byte-identical afterwards, `__pycache__` cleared every cycle):

  M1  drop the trailing slash from the `assumed-role/{role}/` pattern
      -> test_a_role_whose_name_merely_starts_with_the_expected_one_is_refused
  M2  `exit 6` -> `exit 0` on the refusal path
      -> test_the_refusal_is_the_exit_status_and_not_only_a_message
  M3  treat an empty `sts` answer as a match (drop the NO-CREDENTIALS substitution)
      -> test_a_failing_sts_call_is_not_a_pass
  M4  `break` on first mismatch instead of looping (i.e. refuse without waiting)
      -> test_an_identity_that_settles_on_a_later_attempt_is_accepted
  M5  remove the identity guard's call from the detach path in `main()`
      -> test_the_identity_guard_is_wired_into_the_detach_path_and_not_merely_defined
  M6  run the identity guard AFTER the disk guard
      -> test_identity_is_checked_before_disk
  M7  `IDENTITY_TRIES = 1`
      -> test_the_wired_constants_leave_room_for_imds_to_settle
  M8  move `sleep {sleep_s}` ABOVE the `case` match, so every healthy launch pays a wait
      -> test_the_first_attempt_costs_no_wait_when_it_is_already_correct

M8 SURVIVED TWICE BEFORE IT DIED, and both failures are worth keeping written down because they are
the same mistake at two different depths. First the arm asserted that the "waiting for" line was
absent — but the mutant's `break` still fires before that echo, so the output was byte-identical and
the test was watching the wrong quantity (feedback_identical_output_wrong_assertion). Then it asserted
elapsed time "under 6 s of a 24 s budget" — but a sleep moved above the match is paid ONCE and then
the loop breaks, so the mutant cost one interval rather than the budget. The threshold that works is
not "well under the total wait" but "less than a single sleep". A bound derived from the wrong model of
the failure passes for the same reason the code is wrong.

EXPECTED SURVIVOR, named rather than hidden: `test_the_guard_names_the_role_from_provision_and_does_
not_hard_code_it` pins a wiring constant, not a branch. Mutating `PV.ROLE_NAME` to a literal of the
same value produces identical behaviour by construction, so no mutant can kill it. It is here because
a hard-coded `"grx-runner-ec2"` in `run.py` would silently stop tracking `provision.py` the day the
role is renamed, and that is a real failure this arm makes visible in review even though it cannot
make it red.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner"))

import provision as PV      # noqa: E402
import run as RUN           # noqa: E402

ROLE = "grx-runner-ec2"
GOOD = f"arn:aws:sts::123456789012:assumed-role/{ROLE}/i-0f90ac6377bba523b"
# The role the hourly association actually attaches, taken from the observed CloudTrail event rather
# than invented, so the arm exercises the identity this guard was written to catch.
BAD = "arn:aws:sts::123456789012:assumed-role/AmazonSSMRoleForInstancesQuickSetup/i-0f90ac6377bba523b"


def _stub_aws(tmp_path: Path, answers: list[str]) -> Path:
    """A stub `aws` that returns `answers[n]` on its n-th call, and the last one thereafter.

    A counter file rather than an environment variable, because each command in an SSM invocation is
    a separate `aws` process and there is nowhere for in-process state to live. That is also what
    makes the polling arm possible: the guard calls `aws` once per attempt, so a list of answers is a
    script for how the identity changes over time.

    An answer of `""` means "exit non-zero and print nothing" — a credential fetch that failed, which
    is the state the guard is waiting out and the one it must never read as a pass.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    counter = tmp_path / "calls"
    counter.write_text("0\n", encoding="utf-8")
    lines = "\n".join(
        f'  {i}) {"exit 1" if a == "" else f"echo {a!r}"} ;;' for i, a in enumerate(answers))
    last = answers[-1]
    script = f"""#!/bin/bash
n=$(cat {counter})
echo $((n + 1)) > {counter}
case "$n" in
{lines}
  *) {"exit 1" if last == "" else f"echo {last!r}"} ;;
esac
"""
    p = bin_dir / "aws"
    p.write_text(script, encoding="utf-8")
    p.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, answers: list[str], *, tries: int = 3,
         role: str = ROLE) -> subprocess.CompletedProcess:
    """Run the generated fragment the way SSM does: one bash, commands joined by newlines.

    No `set -e` — `AWS-RunShellScript` does not use it, and adding it here would let these arms pass
    on a script that only works under a stricter shell than the real one.

    `sleep_s=0` so the wait is exercised without spending it. The sleep duration is a cost decision,
    not a behaviour: what these arms are about is whether a later attempt is consulted at all.
    """
    bin_dir = _stub_aws(tmp_path, answers)
    cmds = RUN.identity_guard_commands(role, tries=tries, sleep_s=0)
    return subprocess.run(
        ["bash", "-c", "\n".join(cmds)], capture_output=True, text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)})


# ------------------------------------------------------------------ the decision

def test_the_expected_role_is_accepted(tmp_path):
    r = _run(tmp_path, [GOOD])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "identity confirmed" in r.stdout
    assert GOOD in r.stdout


def test_the_replacing_role_is_refused(tmp_path):
    """The association's own role must not pass. This is the case that cost F1-6 a run."""
    r = _run(tmp_path, [BAD])
    assert r.returncode == 6, r.stdout + r.stderr
    assert "REFUSING to start" in r.stdout
    # The refusal must name what it FOUND, not only what it wanted: a message that says
    # "not grx-runner-ec2" without saying what is there sends the reader to look it up by hand.
    assert "AmazonSSMRoleForInstancesQuickSetup" in r.stdout


def test_a_role_whose_name_merely_starts_with_the_expected_one_is_refused(tmp_path):
    """`assumed-role/grx-runner-ec2-readonly/...` is a DIFFERENT role.

    An assumed-role ARN ends with the session name, so the match needs the trailing slash. Without
    it, any role whose name begins with the expected one satisfies a guard whose entire purpose is
    catching a substituted identity — and a `-readonly` sibling is exactly the kind of role that gets
    created next to a runner role.
    """
    other = f"arn:aws:sts::123456789012:assumed-role/{ROLE}-readonly/i-0f90ac6377bba523b"
    r = _run(tmp_path, [other])
    assert r.returncode == 6, r.stdout + r.stderr
    assert f"{ROLE}-readonly" in r.stdout


def test_a_failing_sts_call_is_not_a_pass(tmp_path):
    """No credentials yet is the state being waited out, and it must never read as clean.

    A guard that cannot run must not report success (feedback_guard_tool_exit_codes). The empty
    answer makes the stub exit non-zero with no output, which is what an IMDS credential fetch looks
    like in the window this guard exists for.
    """
    r = _run(tmp_path, [""])
    assert r.returncode == 6, r.stdout + r.stderr
    assert "NO-CREDENTIALS" in r.stdout


def test_the_refusal_is_the_exit_status_and_not_only_a_message(tmp_path):
    """`main()` reads the invocation's exit code, not its text.

    A refusal printed with status 0 would let the launch proceed, which is the failure this whole
    file is about — and it would read like a passing guard in the log.
    """
    r = _run(tmp_path, [BAD])
    assert r.returncode != 0
    assert r.returncode == 6


# ------------------------------------------------------------------ the wait

def test_an_identity_that_settles_on_a_later_attempt_is_accepted(tmp_path):
    """The half that matters: IMDS serves the old role for a while, then the right one.

    A guard that refused on the first mismatch would be correct and useless — the condition clears by
    itself, and the moment a repair happens is exactly the moment a launch is about to happen. Three
    answers, correct only on the third, so a `tries` of 1 or 2 would fail this arm.
    """
    r = _run(tmp_path, [BAD, BAD, GOOD], tries=3)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "identity confirmed" in r.stdout
    # The waiting must be visible, or an operator watching a two-minute launch has no idea why.
    assert "waiting for" in r.stdout
    assert r.stdout.count("waiting for") == 2


def test_the_wait_is_bounded(tmp_path):
    """An identity that never settles must refuse, not hang.

    `tries=3` against an answer that is always wrong: exactly three attempts, then exit 6. An
    unbounded wait would hold the laptop command open forever on a genuinely misconfigured instance,
    which is indistinguishable from a hung SSM call.
    """
    r = _run(tmp_path, [BAD], tries=3)
    assert r.returncode == 6, r.stdout + r.stderr
    assert r.stdout.count("waiting for") == 3
    assert "3 attempt(s)" in r.stdout


def test_the_first_attempt_costs_no_wait_when_it_is_already_correct(tmp_path):
    """The common case is a correct profile, and it must not pay the settle time.

    Every laptop command on this runner goes through the detach path, so a guard that always slept
    would add its full budget to every launch. `break` before the sleep is what makes the healthy
    case free, and this arm is what stops a refactor from moving the sleep above the match.

    This arm measures ELAPSED TIME, not the absence of the "waiting for" line, and it does so because
    the message version SURVIVED its mutant. Moving `sleep {sleep_s}` above the `case` match keeps
    the message absent — the `break` still fires before the echo — so a guard that slept its full
    budget on every healthy launch read as clean. Under `sleep_s=0` the sleep is unobservable in any
    form, which is why this is the one arm in the file that spends real seconds
    (feedback_identical_output_wrong_assertion: a surviving mutant whose output is byte-identical means
    the test is watching the wrong quantity).

    The bound must sit BELOW A SINGLE sleep interval, and that is the second thing this arm got wrong
    before it worked. A first bound of "under 6 s of a 24 s budget" also survived the mutant, because
    a sleep moved above the match is paid ONCE and then the `break` fires — the mutant costs one
    interval, not the whole budget. So the threshold is not "much less than the budget" but "less than
    one sleep": 3 s per attempt against a 2 s ceiling, where the healthy path is a couple of hundred
    milliseconds of process startup and the mutant cannot come in under three seconds.
    """
    bin_dir = _stub_aws(tmp_path, [GOOD])
    cmds = RUN.identity_guard_commands(ROLE, tries=12, sleep_s=3)
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", "\n".join(cmds)], capture_output=True, text=True,
                       env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)})
    elapsed = time.monotonic() - t0
    assert r.returncode == 0, r.stdout + r.stderr
    assert "waiting for" not in r.stdout
    assert elapsed < 2, (f"the healthy case waited {elapsed:.1f}s, which is at least one 3s sleep "
                         f"interval — the sleep is being paid before the identity is matched")


# ------------------------------------------------------------------ wiring

class _FakeSSM:
    """Records the command lists `main()` sends, in order, and answers each as Success.

    Recording ORDER is the point: two guards that both work in isolation can still be sequenced so
    that the cheaper one runs first and the expensive-to-be-wrong one never gets reached on a
    volume that is also full.
    """

    def __init__(self, fail_on: str | None = None):
        self.sent: list[list[str]] = []
        self.fail_on = fail_on

    def send_command(self, **kw):
        self.sent.append(kw["Parameters"]["commands"])
        return {"Command": {"CommandId": f"cid-{len(self.sent)}"}}

    def get_command_invocation(self, **kw):
        idx = int(kw["CommandId"].split("-")[1]) - 1
        text = "\n".join(self.sent[idx])
        bad = self.fail_on is not None and self.fail_on in text
        return {"Status": "Failed" if bad else "Success",
                "StandardOutputContent": "", "StandardErrorContent": "",
                "ResponseCode": 6 if bad else 0}


def _main_with(monkeypatch, fake, argv: list[str]):
    monkeypatch.setattr(RUN.PV, "ensure_instance_profile", lambda *a, **k: None)
    monkeypatch.setattr(RUN, "_client", lambda: (fake, "i-0f90ac6377bba523b"))
    monkeypatch.setattr(sys, "argv", ["run.py"] + argv)
    return RUN.main()


def test_the_identity_guard_is_wired_into_the_detach_path_and_not_merely_defined(
        monkeypatch, capsys):
    """A guard nothing calls does not exist (feedback_no_deploy_path_no_component).

    This is the arm that dies if `identity_guard_commands` is written, tested, and then never
    reached — which is the most likely way this fix regresses, because the function keeps passing
    its own arms while the launch path stops consulting it.
    """
    fake = _FakeSSM()
    _main_with(monkeypatch, fake, ["--detach", "--label", "probe", "echo hi"])
    capsys.readouterr()
    joined = ["\n".join(c) for c in fake.sent]
    assert any("identity confirmed" in t and "assumed-role" in t for t in joined), joined


def test_identity_is_checked_before_disk(monkeypatch, capsys):
    """Order is a decision, not an accident.

    Both guards refuse a launch, but they refuse different things. A full volume refuses before any
    measurement happens and costs nothing. A wrong role SPENDS a case's run and emits an INCONCLUSIVE
    that says nothing about the document under test — so on an instance that is both out of space and
    on the wrong role, the identity refusal is the one worth reading first.
    """
    fake = _FakeSSM()
    _main_with(monkeypatch, fake, ["--detach", "--label", "probe", "echo hi"])
    capsys.readouterr()
    joined = ["\n".join(c) for c in fake.sent]
    ident = next(i for i, t in enumerate(joined) if "identity confirmed" in t)
    disk = next(i for i, t in enumerate(joined) if "free under" in t)
    assert ident < disk, f"identity at {ident}, disk at {disk}: {joined}"


def test_the_identity_refusal_stops_the_launch(monkeypatch, capsys):
    """A non-zero identity guard must return before anything is started.

    The proof is that no later command was ever sent — checking only the return code would pass on a
    `main()` that launched the job and then reported the guard's code.
    """
    fake = _FakeSSM(fail_on="identity confirmed")
    rc = _main_with(monkeypatch, fake, ["--detach", "--label", "probe", "echo hi"])
    capsys.readouterr()
    assert rc == 6
    joined = ["\n".join(c) for c in fake.sent]
    assert not any("free under" in t for t in joined), "the disk guard ran after an identity refusal"
    assert not any("setsid" in t for t in joined), "the job was launched after an identity refusal"


def test_the_guard_names_the_role_from_provision_and_does_not_hard_code_it(monkeypatch, capsys):
    """EXPECTED SURVIVOR — no mutant can kill this arm, and it is here anyway.

    Replacing `PV.ROLE_NAME` with a literal of the same value is behaviourally identical, so there is
    nothing to make red. What it guards is the day the role is renamed in `provision.py`: a literal in
    `run.py` would keep passing every other arm in this file while waiting for a role that no longer
    exists, and the guard would refuse every launch for a reason nobody would look for here. Labelled
    as a survivor rather than counted as a kill (feedback_identical_output_wrong_assertion).
    """
    fake = _FakeSSM()
    _main_with(monkeypatch, fake, ["--detach", "--label", "probe", "echo hi"])
    capsys.readouterr()
    joined = "\n".join("\n".join(c) for c in fake.sent)
    assert f"assumed-role/{PV.ROLE_NAME}/" in joined


def test_the_wired_constants_leave_room_for_imds_to_settle(monkeypatch):
    """`IDENTITY_TRIES=1` would make the guard a refusal with no wait.

    The observed settle time on 2026-08-13 was about 100 seconds, so the budget has to exceed it or
    the guard converts a two-minute wait into a refused launch — turning a self-healing path back
    into a manual one. Asserted as a floor on the PRODUCT, not on either constant alone, because the
    two move independently and only their product is the wait.
    """
    assert RUN.IDENTITY_TRIES >= 2, "one attempt is a refusal, not a wait"
    assert RUN.IDENTITY_TRIES * RUN.IDENTITY_SLEEP_S >= 100
