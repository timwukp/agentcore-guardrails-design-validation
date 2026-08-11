"""Arms for lib/checkpoint.py.

The two properties worth testing here are the two that the reference implementation this
module is derived from gets wrong, because both fail *silently*:

1. A trial that could not be completed must never appear as a result. The reference
   harness records a 3-attempt failure as a zero score, which in a recall measurement is a
   fabricated observation rather than a missing one.
2. A checkpoint write must survive a kill. `json.dump` to an opened path truncates first, so
   an interrupt during trial 900's write destroys trials 1-899 — and the plan's Phase-4 gate
   ("kill a run mid-flight and resume; assert zero duplicated and zero missing trials")
   would have been passing against a file a kill could erase.

`test_a_kill_during_a_write_cannot_destroy_completed_trials` is the second one, and it does
not simulate the kill with a mock: it runs a real subprocess, SIGKILLs it while it is
writing, and then reads the file from disk. A monkeypatched `os.replace` would prove only
that this test's own patch behaves as this test expects.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

import checkpoint as C


def _client_error(code: str, op: str = "ApplyGuardrail") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": f"{code} for test"}}, op)


class _StubClient:
    """Enough of a boto3 client for `evidence.capture` to record a call.

    Only the transport-error arms use this: they need a *real* `CapturedCallError` built by
    the real `capture()` path, because which attributes survive that path is precisely what
    DEV-P1-11 got wrong.
    """

    def __init__(self, *, result=None, raises=None):
        meta = type("meta", (), {})()
        meta.service_model = type("sm", (), {"service_name": "bedrock-runtime"})()
        meta.region_name = "us-east-1"
        self.meta = meta
        self._result = result
        self._raises = raises

    def __getattr__(self, name):
        def _call(**params):
            if self._raises is not None:
                raise self._raises
            return self._result
        return _call


@pytest.fixture()
def cp(tmp_path):
    return C.Checkpoint(case_id="F3-1", cell="VIOLENCE_t0.6", root=tmp_path).load()


# ---------------------------------------------------------------------------
# a failure is not a result
# ---------------------------------------------------------------------------

def test_a_failed_trial_never_appears_in_results(cp):
    """The central arm. A ThrottlingException must not become a data point.

    If it did, an F3 recall denominator would contain a trial where the guardrail was never
    asked — recorded as a guardrail that failed to detect an attack.
    """
    def always_throttles():
        raise _client_error("ThrottlingException")

    got = cp.run_trial("t1", always_throttles, base_delay=0, sleep=lambda _s: None)
    assert got is None
    assert cp.results() == {}
    assert cp.n_done == 0
    assert "t1" in cp.failures()
    assert cp.failures()["t1"]["error_code"] == "ThrottlingException"
    assert cp.failures()["t1"]["attempts"] == C.MAX_ATTEMPTS


def test_the_failure_is_kept_not_dropped(cp):
    """Kept so a resumed run retries it AND so the analysis can state n_attempted."""
    cp.run_trial("t1", lambda: (_ for _ in ()).throw(_client_error("ThrottlingException")),
                 base_delay=0, sleep=lambda _s: None)
    reloaded = C.Checkpoint(case_id=cp.case_id, cell=cp.cell, root=cp.root).load()
    assert reloaded.n_failed == 1
    assert reloaded.n_done == 0


def test_resume_summary_shows_the_shortfall_rather_than_hiding_it(cp):
    for i in range(240):
        cp.record(f"t{i}", {"blocked": True})
    s = C.resume_summary(cp, planned_n=300)
    assert s["n_done"] == 240
    assert s["n_remaining"] == 60
    assert s["usable_fraction"] == 0.8
    assert s["complete"] is False


def test_resume_summary_rejects_a_zero_planned_n(cp):
    """A zero denominator would make every shortfall read as 100% complete."""
    with pytest.raises(ValueError, match="sealed pre-registration"):
        C.resume_summary(cp, planned_n=0)


# ---------------------------------------------------------------------------
# retry classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", sorted(C.RETRY_CODES))
def test_transient_codes_are_retried(code):
    assert C.is_retryable(_client_error(code)) is True


@pytest.mark.parametrize("code", sorted(C.ORACLE_CODES))
def test_oracle_codes_are_not_retried(code):
    """AccessDenied IS the answer for F5-1/F5-2/F5-3b, not an obstacle."""
    assert C.is_retryable(_client_error(code)) is False


def test_an_unknown_code_is_not_retried():
    """The default must be 'do not retry': an unknown error is usually our own bug, and
    three slow failures would read as service flakiness instead of a harness defect."""
    assert C.is_retryable(_client_error("SomeCodeNobodyHasSeen")) is False


def test_a_connection_error_is_retried():
    assert C.is_retryable(EndpointConnectionError(endpoint_url="https://x.invalid")) is True


def test_an_oracle_error_costs_exactly_one_attempt(cp):
    calls = []

    def denied():
        calls.append(1)
        raise _client_error("AccessDeniedException", "UpdateGateway")

    assert cp.run_trial("f5-2", denied, base_delay=0, sleep=lambda _s: None) is None
    assert len(calls) == 1, ("retrying an AccessDenied oracle wastes 15s re-proving a "
                             "permission is absent and implies we doubted the result")
    assert cp.failures()["f5-2"]["attempts"] == 1


def test_the_recorded_attempt_count_equals_the_calls_actually_made(cp):
    """The arm that found the real defect in this module.

    `run_trial` used to write `attempts=max_attempts` on every terminal failure, so an
    AccessDenied that broke out after ONE call was recorded as three. Asserting the
    observable call count alone would not have caught it — the call count was already
    correct; the number written into the evidence was not. Both are checked here, and the
    parametrisation covers the retried path too, where the two happen to agree.
    """
    for code, want in (("AccessDeniedException", 1), ("ThrottlingException", 3)):
        cell = C.Checkpoint(case_id="F5-2", cell=code, root=cp.root).load()
        calls = []

        def boom():
            calls.append(1)
            raise _client_error(code)

        cell.run_trial("t", boom, base_delay=0, sleep=lambda _s: None)
        rec = cell.failures()["t"]
        assert len(calls) == want, code
        assert rec["attempts"] == len(calls), (
            f"{code}: recorded {rec['attempts']} attempts but made {len(calls)} calls; a "
            f"count no call produced is a fabricated number in the evidence")


def test_a_failure_record_cannot_claim_zero_attempts(cp):
    with pytest.raises(ValueError, match="at least 1"):
        cp.record_failure("t", _client_error("ThrottlingException"), attempts=0)


def test_a_retry_that_eventually_succeeds_is_recorded_with_its_attempt_count(cp):
    """The attempt count is what tells a reader whether a latency figure has a retry tail."""
    state = {"n": 0}
    slept = []

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise _client_error("ThrottlingException")
        return {"blocked": True, "latency_ms": 42.0}

    got = cp.run_trial("t1", flaky, base_delay=5.0, sleep=slept.append)
    assert got["attempts"] == 3
    assert slept == [5.0, 10.0], "linear backoff: base * attempt"
    assert got["retry_delay_s"] == 15.0
    assert cp.n_failed == 0


def test_a_wrapped_error_is_judged_on_its_code_not_its_class(cp):
    """The retry policy must see through a wrapper that carries the AWS code.

    `lib/evidence.capture` absorbs the `ClientError` on purpose (an error is data; half
    this project's oracles are `AccessDenied`), so the only exception `lib/arms.run_arm`
    can raise is `evidence.CapturedCallError`. Judged on its class alone it is unknown,
    and unknown means permanent here — which silently disabled retries for every Phase 1
    arm and recorded every failure as `error_code="RuntimeError"`, collapsing throttling,
    an expired token and a malformed request into one indistinguishable bucket in
    `tally()`'s `failure_codes`.

    The check is structural (`getattr(exc, "error_code", "")`) rather than an isinstance
    against `evidence`: `checkpoint` sits *below* `evidence` for the scripts that import
    both, and importing upward to recognise one exception type would make the retry policy
    depend on the evidence writer. A stand-in class is used here for the same reason — the
    contract is the attribute, not the identity.
    """

    class _Wrapped(RuntimeError):
        def __init__(self, code):
            super().__init__(f"wrapped: {code}")
            self.error_code = code

    assert C.error_code(_Wrapped("ThrottlingException")) == "ThrottlingException"
    assert C.is_retryable(_Wrapped("ThrottlingException")) is True
    # And an oracle code stays permanent: retrying an AccessDenied would spend 15 s
    # re-proving a permission is absent and leave a record implying we doubted it.
    assert C.is_retryable(_Wrapped("AccessDeniedException")) is False
    # An empty attribute must not shadow the class-name fallback.
    empty = _Wrapped("")
    assert C.error_code(empty) == "_Wrapped"
    assert C.is_retryable(empty) is False
    # A non-string attribute must not be trusted either.
    weird = RuntimeError("x")
    weird.error_code = 429            # type: ignore[attr-defined]
    assert C.error_code(weird) == "RuntimeError"


def test_a_wrapped_throttle_actually_gets_retried_end_to_end(cp):
    """The observable consequence, asserted on the call count rather than the classifier.

    `is_retryable` returning True is a claim about a predicate; this asserts that
    `run_trial` acts on it. Both were broken by the same defect, and only this one would
    have caught a version where the predicate was fixed and the loop still bailed out.
    """

    class _Wrapped(RuntimeError):
        error_code = "ThrottlingException"

    calls, slept = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _Wrapped("throttled")
        return {"ok": True}

    got = cp.run_trial("t1", flaky, base_delay=5.0, sleep=slept.append)
    assert len(calls) == 3 and got["attempts"] == 3
    assert slept == [5.0, 10.0]
    assert cp.n_failed == 0


def test_a_wrapped_transport_error_is_judged_on_its_class_when_it_has_no_code(cp):
    """The second instance of the same seam — and the one that cost a Phase 1 run.

    A `ThrottlingException` reaching this module as the `capture()` wrapper carries a
    *code*, and the arm above pins that. A connection-level failure never got an HTTP
    response, so there is no AWS error code to carry: `error_code` is the empty string, the
    `wrapped` branch is skipped, and the classifier fell through to `return False`. The
    retry policy was therefore unreachable for exactly the failures retrying exists to
    absorb (DEVIATIONS.md/DEV-P1-11).

    This is asserted against the REAL wrapper, built by pushing a real botocore
    `EndpointConnectionError` through `capture()` and `raise_for_status()`, per
    `feedback_verify_against_real_artifact`: a stand-in class with the attributes I
    *expect* would confirm my own assumption about which attributes survive that path,
    which is the assumption that was wrong. `evidence` imports fine here even though
    `checkpoint` sits below it in the arm scripts' import order — what must not depend on
    `evidence` is `checkpoint` itself, not its test.
    """
    import evidence as ev

    store = ev.EvidenceStore(run_id="rTEST", family="f3", case_id="F3-1",
                             root=cp.root / "ev")
    client = _StubClient(raises=EndpointConnectionError(endpoint_url="https://x.invalid"))
    rec = ev.capture(store, "apply_guardrail", client)

    assert rec.ok is False
    assert rec.error_code == "", "no HTTP response means no AWS error code"
    assert rec.error_class == "EndpointConnectionError"

    with pytest.raises(ev.CapturedCallError) as ei:
        rec.raise_for_status()
    wrapper = ei.value

    # 1. The cause survives into `failure_codes` instead of reading "CapturedCallError",
    #    which is what 3,378 lost trials were labelled during the outage.
    assert C.error_code(wrapper) == "EndpointConnectionError"
    # 2. And it is retryable, so the 3-attempt policy actually runs.
    assert C.is_retryable(wrapper) is True, (
        "a code-less transport wrapper must be judged on the transport class it does "
        "carry; without this the retry policy is dead on the only path arms use")
    # The raw botocore exception was always retryable — the wrapper was the gap, so both
    # paths are asserted together to keep them from diverging.
    assert C.is_retryable(EndpointConnectionError(endpoint_url="https://x.invalid")) is True

    # An oracle wrapper must NOT become retryable by this route: AccessDenied carries a
    # code, and its `error_class` ("ClientError") is not in RETRYABLE_TRANSPORT either.
    denied = ev.CapturedCallError("denied", error_code="AccessDeniedException",
                                  error_class="ClientError")
    assert C.is_retryable(denied) is False


def test_a_wrapped_transport_error_is_actually_retried_end_to_end(cp):
    """The observable consequence: `run_trial` spends its 3 attempts on this failure.

    The predicate and the loop were broken by one defect the first time round, so the
    same pair of arms is kept here. This one is what makes the ~80 s outage survivable:
    at base 5 s the three attempts span 15 s of backoff, which covers a gap of that
    length only when the trial is *inside* the window — the arms that were killed were
    killed because they got zero attempts, not because 15 s was too short.
    """
    import evidence as ev

    calls, slept = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ev.CapturedCallError("connection failed", error_code="",
                                       error_class="EndpointConnectionError")
        return {"blocked": True}

    got = cp.run_trial("t1", flaky, base_delay=5.0, sleep=slept.append)
    assert len(calls) == 3 and got is not None and got["attempts"] == 3
    assert slept == [5.0, 10.0]
    assert cp.n_failed == 0


@pytest.mark.parametrize("klass", sorted(C.RETRYABLE_TRANSPORT))
def test_every_transport_class_is_retryable_by_both_paths(klass):
    """The set is used for the raw exception and the wrapper; one set, one behaviour.

    Parametrized over the set itself rather than a hand-copied list, so adding a class to
    `RETRYABLE_TRANSPORT` without teaching both paths about it fails here.
    """
    import evidence as ev
    assert C.is_retryable(ev.CapturedCallError("x", error_class=klass)) is True


def test_a_non_transport_class_on_a_codeless_wrapper_stays_permanent():
    """The new branch must not turn the allowlist into a denylist.

    `ValidationException` means the request was malformed — a harness bug that no number
    of retries fixes — and an unknown class must stay permanent so our own defects surface
    as failures rather than as three slow failures reading like service flakiness.
    """
    import evidence as ev
    for klass in ("ValidationException", "ParamValidationError", "SomethingNew"):
        assert C.is_retryable(ev.CapturedCallError("x", error_class=klass)) is False


def test_backoff_is_linear_not_exponential():
    assert [C.backoff_delay(i, base=5.0) for i in (1, 2, 3)] == [5.0, 10.0, 15.0]
    with pytest.raises(ValueError, match="1-based"):
        C.backoff_delay(0)


def test_error_code_falls_back_to_the_class_name():
    assert C.error_code(ValueError("x")) == "ValueError"
    assert C.error_code(_client_error("ThrottlingException")) == "ThrottlingException"


# ---------------------------------------------------------------------------
# resume: zero duplicated, zero missing
# ---------------------------------------------------------------------------

def test_a_completed_trial_is_skipped_on_resume(cp):
    calls = []
    cp.run_trial("t1", lambda: (calls.append(1), {"blocked": True})[1])
    again = C.Checkpoint(case_id=cp.case_id, cell=cp.cell, root=cp.root).load()
    again.run_trial("t1", lambda: (calls.append(1), {"blocked": False})[1])
    assert len(calls) == 1
    assert again.results()["t1"]["blocked"] is True


def test_re_recording_a_trial_is_an_error_not_an_overwrite(cp):
    """An overwrite keeps the count right while changing which trials the count is over."""
    cp.record("t1", {"blocked": True})
    with pytest.raises(RuntimeError, match="already recorded"):
        cp.record("t1", {"blocked": False})


def test_two_arms_of_one_case_do_not_share_a_checkpoint(tmp_path):
    on = C.Checkpoint(case_id="F6-1", cell="guardrail_on", root=tmp_path).load()
    off = C.Checkpoint(case_id="F6-1", cell="guardrail_off", root=tmp_path).load()
    on.record("t1", {"ms": 10})
    assert off.load().n_done == 0
    assert on.path != off.path


def test_opening_a_checkpoint_under_the_wrong_identity_is_fatal(tmp_path):
    """Resuming across arms would attribute one arm's trials to another."""
    a = C.Checkpoint(case_id="F6-1", cell="on", root=tmp_path).load()
    a.record("t1", {"ms": 10})
    mislabelled = C.Checkpoint(case_id="F6-1", cell="on", root=tmp_path)
    mislabelled.path.rename(tmp_path / "F6-1__off.json")
    with pytest.raises(RuntimeError, match="resuming"):
        C.Checkpoint(case_id="F6-1", cell="off", root=tmp_path).load()


def test_a_corrupt_checkpoint_is_fatal_rather_than_silently_restarted(tmp_path):
    cp = C.Checkpoint(case_id="F2-1", cell="pure_cedar", root=tmp_path)
    cp.root.mkdir(parents=True, exist_ok=True)
    cp.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Refusing to start fresh"):
        cp.load()


def test_a_retried_failure_that_later_succeeds_leaves_no_failure_record(cp):
    cp.record_failure("t1", _client_error("ThrottlingException"), attempts=3)
    assert cp.n_failed == 1
    cp.record("t1", {"blocked": True}, attempts=1)
    assert cp.n_failed == 0
    assert cp.n_done == 1


# ---------------------------------------------------------------------------
# atomicity, proven against a real SIGKILL
# ---------------------------------------------------------------------------

_KILL_SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {lib!r})
    import checkpoint as C
    from pathlib import Path
    cp = C.Checkpoint(case_id="F6-1", cell="on", root=Path({root!r})).load()
    for i in range(100):
        cp.record("t%03d" % i, {{"ms": i}})
    Path({flag!r}).write_text("ready")
    # Keep writing until killed. Each save rewrites the whole 100-trial body, so a kill
    # lands inside a write with high probability.
    i = 100
    while True:
        cp.record("t%03d" % i, {{"ms": i}})
        i += 1
""")


def test_a_kill_during_a_write_cannot_destroy_completed_trials(tmp_path):
    """A real SIGKILL against a real writer, then read the file back from disk.

    Not monkeypatched: patching os.replace would only prove the patch behaves as this test
    expects. The property under test is that a kill at any instant leaves the file either
    fully at version N or fully at version N+1 — never truncated.
    """
    lib_dir = str(Path(C.__file__).resolve().parent)
    flag = tmp_path / "ready"
    script = tmp_path / "writer.py"
    script.write_text(_KILL_SCRIPT.format(lib=lib_dir, root=str(tmp_path), flag=str(flag)),
                      encoding="utf-8")

    proc = subprocess.Popen([sys.executable, str(script)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while not flag.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                out, err = proc.communicate()
                pytest.fail(f"writer died early: {err.decode()[:2000]}")
            time.sleep(0.01)
        assert flag.exists(), "writer never reached the steady-write phase"
        time.sleep(0.15)                      # land inside the write loop
        proc.send_signal(signal.SIGKILL)
    finally:
        proc.wait(timeout=10)

    path = tmp_path / "F6-1__on.json"
    assert path.is_file()
    body = json.loads(path.read_text(encoding="utf-8"))   # must parse: the whole point
    assert body["n_done"] >= 100, "trials completed before the kill must all survive"
    assert body["n_done"] == len(body["done"])
    # And the file is resumable, with no duplicates and no gaps below the recorded high mark.
    cp = C.Checkpoint(case_id="F6-1", cell="on", root=tmp_path).load()
    ids = sorted(cp.results())
    assert len(ids) == len(set(ids))
    assert ids[:100] == [f"t{i:03d}" for i in range(100)]


def test_the_write_path_calls_fsync_before_replace(cp, monkeypatch):
    """A structural check, and the honest limit of what this suite can prove.

    `os.replace` alone survives the SIGKILL above: a killed process loses nothing from the
    page cache, so the file the kernel serves is already the new one. `fsync` protects
    against something a userspace test cannot produce — power loss or a kernel panic
    between the write and the rename, where the rename is durable and the contents are not.

    So this arm asserts the *call*, in order, rather than the durability. It is a weaker
    proposition than "trials survive a crash", and saying which one is being checked is the
    point: a mutation run over this module found that removing the fsync is caught by
    nothing else, and a test claiming to prove durability by monkeypatching the syscall
    would be confirming its own patch.
    """
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd))[0])
    monkeypatch.setattr(os, "replace",
                        lambda a, b: (events.append("replace"), real_replace(a, b))[0])
    cp.record("t1", {"ms": 1})
    assert events == ["fsync", "replace"], (
        "the buffer must reach the disk before the rename makes it the live file; the "
        "reverse order leaves a durable rename pointing at unflushed contents")


def test_no_temp_file_is_left_behind_on_a_normal_write(cp):
    cp.record("t1", {"ms": 1})
    assert not list(cp.root.glob("*.tmp")), ("a stray .tmp would be picked up by nothing "
                                             "and would make the directory's contents lie "
                                             "about what completed")


def test_the_temp_file_shares_the_directory_so_replace_is_atomic(cp):
    """os.replace is only atomic within one filesystem."""
    cp.record("t1", {"ms": 1})
    tmp = cp.path.with_suffix(".json.tmp")
    assert tmp.parent == cp.path.parent


# ---------------------------------------------------------------------------
# kill-and-resume, end to end: the Phase-4 gate the plan names
# ---------------------------------------------------------------------------

def test_kill_and_resume_yields_zero_duplicated_and_zero_missing_trials(tmp_path):
    """The plan's Verification item, executed rather than asserted.

    Two runs over one 300-trial plan, the first stopped at 137. The union must be exactly
    the plan, each trial run exactly once, with the second run's function refusing to be
    called for anything the first completed — so a duplicate would be caught by the counter
    even if the ids happened to match.
    """
    plan = [f"trial{i:04d}" for i in range(300)]
    executed: list[str] = []

    first = C.Checkpoint(case_id="F2-1", cell="pure_cedar", root=tmp_path).load()
    for tid in plan:
        if first.n_done >= 137:
            break                                  # the "kill"
        first.run_trial(tid, lambda t=tid: (executed.append(t), {"deny": True})[1])
    assert first.n_done == 137

    second = C.Checkpoint(case_id="F2-1", cell="pure_cedar", root=tmp_path).load()
    assert second.n_done == 137, "the resumed run must see every completed trial"
    for tid in plan:
        second.run_trial(tid, lambda t=tid: (executed.append(t), {"deny": True})[1])

    assert second.n_done == 300
    assert sorted(second.results()) == plan          # zero missing
    assert len(executed) == len(set(executed)) == 300  # zero duplicated
    s = C.resume_summary(second, planned_n=300)
    assert s["complete"] is True and s["n_failed"] == 0


def test_a_resumed_run_retries_a_previously_failed_trial(tmp_path):
    """A failure is not terminal for the trial, only for that attempt sequence."""
    cp = C.Checkpoint(case_id="F3-1", cell="HATE", root=tmp_path).load()
    cp.run_trial("t1", lambda: (_ for _ in ()).throw(_client_error("ThrottlingException")),
                 base_delay=0, sleep=lambda _s: None)
    assert cp.n_done == 0 and cp.n_failed == 1

    resumed = C.Checkpoint(case_id="F3-1", cell="HATE", root=tmp_path).load()
    assert resumed.is_done("t1") is False
    got = resumed.run_trial("t1", lambda: {"blocked": True})
    assert got["blocked"] is True
    assert resumed.n_failed == 0


def test_meta_survives_a_resume(tmp_path):
    cp = C.Checkpoint(case_id="F6-1", cell="on", root=tmp_path).load()
    cp.set_meta(region="us-east-1", prereg_sha="deadbeef")
    cp.record("t1", {"ms": 1})
    again = C.Checkpoint(case_id="F6-1", cell="on", root=tmp_path).load()
    assert again._meta["region"] == "us-east-1"


# ---------------------------------------------------------------------------
# a resume across a design change: the fix that would have looked applied
# ---------------------------------------------------------------------------
#
# `load` refuses a checkpoint whose case_id/cell disagree, because "resuming would attribute
# one arm's trials to another". The same argument covers every field that determines what a
# trial IS — and those were recorded in `meta` and never compared.
#
# F3-7 made that concrete. It collected 120 trials at `source="INPUT"`, where the
# contextual-grounding filter is silently skipped, and published a FALSE from them
# (DEVIATIONS.md/DEV-P1-18). Correcting the arm to `source="OUTPUT"` and re-running would
# have found 120 completed ids, skipped every one, and re-published the identical wrong
# verdict — with the corrected source now sitting in the meta beside rows never collected
# that way. The fix would have looked applied and changed nothing.

def test_a_resume_that_changed_the_request_shape_is_refused(tmp_path):
    cp = C.Checkpoint(case_id="F3-7", cell="ungrounded", root=tmp_path).load()
    cp.set_meta(source="INPUT", region="us-east-1", corpus="grounding/ungrounded.jsonl")
    cp.record("t1", {"hit": False})

    resumed = C.Checkpoint(case_id="F3-7", cell="ungrounded", root=tmp_path).load()
    with pytest.raises(RuntimeError, match="DIFFERENT arm design"):
        resumed.set_meta(source="OUTPUT", region="us-east-1",
                         corpus="grounding/ungrounded.jsonl")


def test_the_refusal_names_the_field_and_both_values(tmp_path):
    """A message saying only "design changed" sends the operator back to the diff.

    The remedy is deliberately NOT automated: deleting a checkpoint discards trials already
    paid for, which is the operator's call.
    """
    cp = C.Checkpoint(case_id="F3-7", cell="g", root=tmp_path).load()
    cp.set_meta(source="INPUT")
    cp.record("t1", {"hit": False})
    resumed = C.Checkpoint(case_id="F3-7", cell="g", root=tmp_path).load()
    with pytest.raises(RuntimeError) as ei:
        resumed.set_meta(source="OUTPUT")
    msg = str(ei.value)
    assert "source" in msg and "'INPUT'" in msg and "'OUTPUT'" in msg, msg
    assert "1 completed trial" in msg, msg
    assert "F3-7__g.json" in msg, msg


def test_a_design_change_on_an_EMPTY_checkpoint_is_allowed(tmp_path):
    """Nothing has been collected, so there is nothing to mis-attribute.

    This is the ordinary case — the first `set_meta` of every arm that has never run — and
    a guard that refused it would make the first run of every case impossible.
    """
    cp = C.Checkpoint(case_id="F3-7", cell="g", root=tmp_path).load()
    cp.set_meta(source="INPUT")
    cp.save()                                  # meta on disk, zero completed trials
    resumed = C.Checkpoint(case_id="F3-7", cell="g", root=tmp_path).load()
    assert resumed._loaded_meta["source"] == "INPUT", (
        "premise: the OLD design must actually be on disk, or this arm proves nothing about "
        "the guard — it would just be comparing against an empty dict")
    resumed.set_meta(source="OUTPUT")          # no COMPLETED trials -> allowed
    assert resumed._meta["source"] == "OUTPUT"


def test_a_design_change_is_allowed_when_every_trial_FAILED(tmp_path):
    """`and self._done`, not `and self._meta` — and the distinction is reachable.

    A guard keyed on "is there a meta on disk" would refuse this, and refusing it would be
    wrong: an arm whose trials all failed holds nothing that could be mis-attributed, and a
    resume re-sends every one of them under the new design. This is not hypothetical — the
    2026-08-10 outage left arms holding failures and almost no results (DEV-P1-11), and
    those are exactly the arms most likely to be re-run with a fix applied.

    Written because a mutation weakening the condition to `if drift:` survived the whole
    suite: no arm had a checkpoint that was non-empty in `failed` and empty in `done`.
    """
    cp = C.Checkpoint(case_id="F3-1", cell="a", root=tmp_path).load()
    cp.set_meta(source="INPUT")
    cp.record_failure("t1", RuntimeError("boom"), attempts=3)
    cp.record_failure("t2", RuntimeError("boom"), attempts=3)

    resumed = C.Checkpoint(case_id="F3-1", cell="a", root=tmp_path).load()
    assert resumed.n_failed == 2 and resumed.results() == {}, "premise"
    resumed.set_meta(source="OUTPUT")          # must NOT raise
    assert resumed._meta["source"] == "OUTPUT"


@pytest.mark.parametrize("key,old,new", [
    ("source", "INPUT", "OUTPUT"),
    ("qualifiers", [], ["guard_content"]),
    ("output_scope", "FULL", "INTERVENTIONS"),
    ("guardrail_version", "DRAFT", "1"),
    ("region", "us-east-1", "eu-west-2"),
    ("corpus", "a.jsonl", "b.jsonl"),
    ("is_smoke", True, False),
    ("operation", "ApplyGuardrail", "InvokeGuardrailChecks"),
])
def test_every_design_key_is_actually_compared(tmp_path, key, old, new):
    """Parametrised over `DESIGN_KEYS` itself, so adding a key without wiring it fails.

    Each of these changes what a trial IS. `output_scope` reverting to INTERVENTIONS empties
    every FPR cell; `is_smoke` flipping lets 3 smoke rows be counted as a full run;
    `qualifiers` is the whole of F3-8's untagged-vs-tagged pairing.
    """
    cp = C.Checkpoint(case_id="X", cell="c", root=tmp_path).load()
    cp.set_meta(**{key: old})
    cp.record("t1", {"hit": False})
    resumed = C.Checkpoint(case_id="X", cell="c", root=tmp_path).load()
    with pytest.raises(RuntimeError, match="DIFFERENT arm design"):
        resumed.set_meta(**{key: new})


def test_the_parametrisation_covers_every_declared_design_key():
    """Otherwise the arm above tests whichever keys I happened to remember.

    `feedback_prose_is_not_verified`: a list written beside a constant is not the constant.
    """
    covered = {"source", "qualifiers", "output_scope", "guardrail_version", "region",
               "corpus", "is_smoke", "operation"}
    assert set(C.DESIGN_KEYS) == covered, (
        f"DESIGN_KEYS is {C.DESIGN_KEYS} but the parametrised arm covers {sorted(covered)}; "
        f"an uncovered key is a comparison nothing proves happens")


@pytest.mark.parametrize("key,old,new", [
    ("run_id", "r1", "r2"),
    ("planned_n", 3, 60),
    ("sdk", "1.43.67", "1.43.68"),
])
def test_a_run_descriptor_change_still_resumes(tmp_path, key, old, new):
    """These describe the RUN, not the trial, and varying them is how this project works.

    Re-running the same arm under a new `run_id` is exactly how F8-6 and F10-2 were
    re-emitted at $0 — the checkpoints resumed instead of re-billing 87 calls. `planned_n`
    grows legitimately from a `--n 3` smoke to a full run, and `is_smoke` (which IS a design
    key) catches the direction that matters: smoke rows silently counted as a full run.
    """
    cp = C.Checkpoint(case_id="X", cell="c", root=tmp_path).load()
    cp.set_meta(**{key: old})
    cp.record("t1", {"hit": False})
    resumed = C.Checkpoint(case_id="X", cell="c", root=tmp_path).load()
    resumed.set_meta(**{key: new})             # must NOT raise
    assert resumed._meta[key] == new
    assert resumed.is_done("t1"), "the completed trial must still be resumable"


def test_the_guard_would_have_caught_the_f3_7_repair(tmp_path):
    """The incident end to end, through `arms.run_arm`'s own meta call.

    Written against the real recorded keys rather than a hand-made subset: `run_arm` is what
    populates the meta, so a future change to WHICH keys it records is what this arm is
    watching. Reproduced with `Checkpoint` directly because `run_arm` needs a client.
    """
    live = dict(case_id="F3-7", arm="ungrounded", corpus="grounding/ungrounded.jsonl",
                guardrail_version="DRAFT", region="us-east-1", source="INPUT",
                qualifiers=[], output_scope="FULL", planned_n=60, is_smoke=False,
                run_id="r20260810T0345Z", sdk="1.43.67")
    cp = C.Checkpoint(case_id="F3-7", cell="ungrounded", root=tmp_path).load()
    cp.set_meta(**live)
    for i in range(60):
        cp.record(f"t{i}", {"hit": False, "grounding": []})

    fixed = dict(live, source="OUTPUT", run_id="r20260810T2100Z")
    resumed = C.Checkpoint(case_id="F3-7", cell="ungrounded", root=tmp_path).load()
    assert len(resumed.results()) == 60, "premise: the wrong-source trials are all resumable"
    with pytest.raises(RuntimeError, match="DIFFERENT arm design"):
        resumed.set_meta(**fixed)


# ---------------------------------------------------------------------------
# mutation control: each arm above must be able to fail
# ---------------------------------------------------------------------------

def test_the_failure_isolation_arm_would_catch_the_reference_implementations_behaviour(cp):
    """Mutation control for the module's central property.

    The reference harness's behaviour — record a failure as a result with zeroed fields — is
    reproduced here directly. `results()` then contains it, which is what the arms above
    assert cannot happen. This proves those arms are load-bearing rather than passing
    because failures happen never to be written anywhere.
    """
    cp._done["t1"] = {"blocked": False, "error": "ThrottlingException"}   # the mutant
    assert "t1" in cp.results()
    assert cp.n_done == 1
    # The real code path never does this:
    fresh = C.Checkpoint(case_id="F3-1", cell="other", root=cp.root).load()
    fresh.run_trial("t1", lambda: (_ for _ in ()).throw(_client_error("ThrottlingException")),
                    base_delay=0, sleep=lambda _s: None)
    assert fresh.results() == {}
