#!/usr/bin/env python3
"""F5-2's denials must be about a boundary, and its restore must be able to fail.

F5-2 carries the same hazard as F5-1, and a second one of its own.

The shared one: `grx-runtime-exec` holds no `bedrock-agentcore` control-plane permission, so IAM
answers `AccessDeniedException` **before it looks at the request**. A wrong gateway identifier, a
member the model does not accept, a stale region — every one of them produces 120 clean denials,
and ZERO_EVENTS reads them as TRUE at a 4.98% ceiling. Only the granted arm distinguishes a
boundary from a request the service refused to parse, which is why most of the weight below sits
on that arm and on the guard that gates the verdict against it.

The new one: this case sends `UpdateGateway`, which is a FULL REPLACEMENT. A body assembled by
hand would omit `protocolConfiguration` and `exceptionLevel` and so reset the live configuration
of the gateway F4's truth table and every F6 latency verdict are published against. The body has
to be derived from `GetGateway`, and the restore check has to be able to notice if it were not.

The properties tested here are the ones under which the script would publish a confident
falsehood, or damage a published resource:

* the two terminal-status sets confused — a gateway settles in `READY` and a policy in `ACTIVE`,
  and one shared name makes the startup interlock refuse every healthy gateway;
* `wait_ready` returning on `UPDATE_UNSUCCESSFUL` read as the new configuration;
* `_replacement_kwargs` sharing nested state with `live`, which makes the end-of-run restore diff
  a comparison that CANNOT fail;
* a body missing a member the gateway currently carries — a silent reset dressed as an attack;
* `ValidationException` counted as a denial, which is how a malformed request of ours becomes a
  security property;
* `ConflictException` counted as a denial, which is how an AUTHORIZED call becomes evidence of a
  boundary — it is returned after authorization;
* the granted arm never authorized, yet the verdict published — the F5-1 hazard, verbatim;
* the chain's `forbid` blocking nothing, or blocking everything, either of which makes the
  LOG_ONLY leg's ALLOW attributable to the mode only by assumption;
* a propagation wait satisfied by an ALTERNATING sequence, which is the state that has NOT
  converged;
* the restore verified against an ignore list that ignores the one field this case moves;
* a FAILED end-state read reported as a clean role;
* the n floor gating away a DEMONSTRATED bypass;
* `mutation_inverted` passed as a keyword instead of set as an attribute — the F5-1 defect that
  published INCONCLUSIVE over a clean 120-trial run;
* the `--also-null-pec` probe touching the main gateway.

Nothing here makes an AWS call: `capture` is replaced wholesale, and `M.time` is replaced with a
fake clock so the bounded poll loops run their real iteration counts in no wall-clock time. The
service model IS real, read from botocore, because "UpdateGateway is a full replacement over these
members" is the claim under test, and a hand-typed member list here would be the second source of
truth the script exists to avoid.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

SCRIPT = ROOT / "f5_redteam" / "02_route3_updategateway.py"
_spec = importlib.util.spec_from_file_location("grx_f5_02_route3_updategateway", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules["grx_f5_02_route3_updategateway"] = M
_spec.loader.exec_module(M)

import awsclients as A   # noqa: E402
import cedar as C        # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
import testbed as T      # noqa: E402

SRC = SCRIPT.read_text(encoding="utf-8")
PY = str(ROOT / ".venv-oracle" / "bin" / "python")

RUN = "r20260810T130945Z"
GW_ID = "grx-gw-r20260810T130945Z-abc123"
# AWS's published documentation-example account, on ONE line. The fixtures need a well-formed
# 12-digit account field: `_pass_role_grant` builds an IAM policy `Resource` that is asserted on
# for shape, and `redact.ACCOUNT_PLACEHOLDER` (`<account>`) is a value IAM would reject, so a
# redacted fixture would assert against a request that cannot be made.
#
# Every ARN below then interpolates it, which is not cosmetic: `check_redaction.py` structurally
# excuses an ARN whose account field is a `{template}` placeholder, so this file needs exactly ONE
# reviewed exception (for the digits on the next line) instead of one per ARN-bearing line. The
# ARNs are written out in full rather than assembled from a shared prefix for the same reason —
# the gate fails CLOSED on a truncated ARN whose account field it cannot decompose.
EXAMPLE_ACCOUNT = "111122223333"
GW_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{EXAMPLE_ACCOUNT}:gateway/{GW_ID}"
ENGINE_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{EXAMPLE_ACCOUNT}:policy-engine/grx_pe_{RUN}"
GW_EXEC_ROLE_ARN = f"arn:aws:iam::{EXAMPLE_ACCOUNT}:role/grx-gw-exec-{RUN}"
ROLE = f"grx-runtime-exec-{RUN}"
ACTION = "grxecho___echo"

_SM = A.service_model("bedrock-agentcore-control")
_UPD = _SM.operation_model("UpdateGateway").input_shape
ALLOWED = frozenset(_UPD.members)
REQUIRED = frozenset(_UPD.required_members)


class _AC:
    """A client stand-in carrying the REAL service model, and nothing that can reach AWS.

    `_update_shape` and `_null_pec_probe` both read `ac.meta.service_model`, and `T.check_name`
    derives its name grammar from it. Faking the model would turn every shape assertion below
    into a statement about the fake.
    """

    class _Meta:
        service_model = _SM

    meta = _Meta()

    @staticmethod
    def get_policy(**kwargs):                     # `_create_forbid` hands this to `wait_status`
        raise AssertionError("get_policy must never be invoked in a test")


def _live(**over):
    """A `GetGateway` response shaped like the live one, carrying every member the model accepts."""
    d = {
        "gatewayId": GW_ID, "gatewayArn": GW_ARN, "name": f"grxgw{RUN}",
        "gatewayUrl": f"https://{GW_ID}.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        "status": "READY", "createdAt": "2026-08-10T13:09:45Z", "updatedAt": "x",
        "roleArn": GW_EXEC_ROLE_ARN,
        "authorizerType": "AWS_IAM", "protocolType": "MCP", "exceptionLevel": "DEBUG",
        "description": "grx main gateway",
        "protocolConfiguration": {"mcp": {"sessionConfiguration":
                                          {"sessionTimeoutInSeconds": 900}}},
        "policyEngineConfiguration": {"arn": ENGINE_ARN, "mode": "ENFORCE"},
    }
    d.update(over)
    return d


# ---- stand-ins -------------------------------------------------------------

class _Rec:
    def __init__(self, ok=True, response=None, error_code="", error_message="", http_status=200):
        self.ok, self.response, self.error_code = ok, response or {}, error_code
        self.error_message, self.http_status = error_message, http_status


class _Cap:
    """Scripted `capture` replacement. The last entry repeats, so a poll loop cannot exhaust it."""

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, store, operation, client, **params):
        self.calls.append((operation, params))
        if not self._script:
            return _Rec(ok=False, error_code="TestScriptExhausted")
        nxt = self._script[0]
        if len(self._script) > 1:
            self._script.pop(0)
        return nxt(operation, params) if callable(nxt) else nxt

    @property
    def ops(self):
        return [op for op, _ in self.calls]


class _Clock:
    """A fake `time`, so a 300s poll bound costs no wall clock and runs its real loop count.

    Installed by replacing `M.time` rather than by patching the real module: a no-op `sleep`
    against a real `monotonic` would spin these loops for their full wall-clock bound, and
    shrinking the bound instead would test a different loop than the one that ships. The module
    uses exactly `monotonic` and `sleep`.
    """

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += max(float(s), 0.001)


DENIED = _Rec(ok=False, error_code="AccessDeniedException")
CONFLICT = _Rec(ok=False, error_code="ConflictException", error_message="gateway is UPDATING")
INVALID = _Rec(ok=False, error_code="ValidationException", error_message="bad member")
ACCEPTED = _Rec(response={"gatewayId": GW_ID, "status": "UPDATING"})


@pytest.fixture(autouse=True)
def _sealed(monkeypatch):
    """No AWS, no real limiter sleep, no real clock — for every test in the file."""
    monkeypatch.setattr(M, "capture", _Cap([]))
    monkeypatch.setattr(M, "time", _Clock())
    monkeypatch.setattr(M.A, "limiter",
                        lambda: type("L", (), {"wait": staticmethod(lambda *a, **k: None)})())
    yield


class _State:
    """A ledger stand-in that records the ORDER of its calls, which several tests assert on."""

    run_id = RUN

    def __init__(self, policies=("baseline",)):
        self._p = list(policies)
        self.order: list[str] = []
        self.recorded: list[T.Resource] = []

    def of_kind(self, kind):
        if kind != "policy":
            return []
        return [T.Resource(kind="policy", logical=lg, name=lg, service="s",
                           delete_op="delete_policy", delete_params={},
                           ids={"policy_id": f"pid-{lg}"}) for lg in self._p]

    def record(self, r):
        self.order.append(f"record:{r.logical}")
        self.recorded.append(r)

    def write(self):
        self.order.append("write")

    def drop(self, kind, logical):
        self.order.append(f"drop:{kind}/{logical}")


# ---- the sealed oracle this design is built against ------------------------

def test_the_binding_is_zero_events_with_a_mandatory_mutation():
    """The staged-grant design exists because the mutation is MANDATORY.

    If a re-seal made it optional, the granted arms would become decoration and the argument about
    IAM denying before it parses the request would stop being enforced anywhere.
    """
    b = O.BINDINGS["F5-2"]
    assert b.kind == "ZERO_EVENTS"
    assert b.cell == "confirmatory_e_cell"
    assert O.mutation_is_mandatory("F5-2") is True
    assert O.alpha_for("F5-2") == pytest.approx(0.05 / 8)


def test_the_preregistered_n_is_read_from_the_oracle_and_not_typed():
    assert M.PLANNED_N == O.planned_n("F5-2") == 120
    assert "PLANNED_N = O.planned_n(CASE)" in SRC, (
        "a literal 120 would be a second home for the pre-registered n; PREREGISTRATION.yaml is "
        "the one that counts")


def test_the_oracle_text_names_the_chain_this_script_implements():
    """The four legs are not our invention; they are what the sealed oracle asks for."""
    text = O.oracle_text("F5-2")
    for phrase in ("LOG_ONLY", "previously-blocked", "restore", "re-assert"):
        assert phrase in text, f"the oracle no longer asks for {phrase!r}; re-read the chain"
    assert len(M.LEGS) == 4


def test_update_gateway_is_rate_limited_so_the_limiter_call_is_not_decoration():
    """A no-op limiter would let 120 UpdateGateway calls go out back to back."""
    assert A.rate_limit_for("UpdateGateway"), "UpdateGateway has no rate in RATE_LIMITS"
    assert 'A.limiter().wait("UpdateGateway")' in SRC


# ---- the two terminal-status sets -----------------------------------------

def test_gateway_and_policy_terminal_sets_are_imported_under_distinct_names():
    """A gateway settles in READY, a policy in ACTIVE. One shared name is a real bug.

    Importing `TERMINAL_OK` from the policy-engine module and using it for both makes
    `_assert_gateway_is_provisioned` reject every healthy gateway — a refusal indistinguishable,
    in the log, from the gateway genuinely not being provisioned.
    """
    assert M.GATEWAY_OK == {"READY"}
    assert M.POLICY_OK == {"ACTIVE"}
    assert M.GATEWAY_OK != M.POLICY_OK
    assert "UPDATE_UNSUCCESSFUL" in M.GATEWAY_BAD
    assert not hasattr(M, "TERMINAL_OK"), (
        "a bare TERMINAL_OK is exactly the name that would make a gateway status compare against "
        "{'ACTIVE'}")


def test_settle_reports_the_status_it_settled_into_not_merely_that_it_finished(monkeypatch):
    """`wait_ready` returns on ANY terminal status, UPDATE_UNSUCCESSFUL included.

    Reading `policyEngineConfiguration.mode` off that result and calling it the new configuration
    would report a flip the service rejected.
    """
    monkeypatch.setattr(M, "wait_ready", lambda *a, **k: _live(status="READY"))
    ok = M._settle(_AC(), GW_ID)
    assert ok["settled_ok"] is True and ok["status"] == "READY"
    assert ok["status_reasons"] is None

    monkeypatch.setattr(M, "wait_ready",
                        lambda *a, **k: _live(status="UPDATE_UNSUCCESSFUL", statusReasons=["no"]))
    bad = M._settle(_AC(), GW_ID)
    assert bad["settled_ok"] is False, (
        "a gateway that failed its update must not read as settled; the mode it still carries is "
        "the OLD one")
    assert bad["status_reasons"] == ["no"]


# ---- the request body -----------------------------------------------------

def test_the_shape_is_read_from_the_service_model():
    allowed, required = M._update_shape(_AC())
    assert allowed == ALLOWED
    assert required == REQUIRED
    assert set(required) == {"gatewayIdentifier", "roleArn", "name", "authorizerType"}
    assert "roleArn" in required, (
        "roleArn being required is why iam:PassRole is staged separately; if it stops being "
        "required, the staged-grant design needs re-reading")
    assert "policyEngineConfiguration" in allowed
    assert "policyEngineConfiguration" not in required, (
        "an optional member is what makes the omission probe a real question")


def test_the_body_carries_every_live_member_the_model_accepts():
    """The silent-reset failure: UpdateGateway REPLACES, so an omitted member is an unset.

    A body missing `protocolConfiguration` would drop the gateway's 900s session timeout, and one
    missing `exceptionLevel` would drop DEBUG — both live configuration that F4 and F6 are
    published against. This is what keeps the attack a no-op rather than damage.
    """
    live = _live()
    body = M._replacement_kwargs(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED)
    for key in ("protocolConfiguration", "exceptionLevel", "description", "roleArn",
                "authorizerType", "protocolType", "policyEngineConfiguration", "name"):
        assert body[key] == live[key], f"{key} was dropped; UpdateGateway would unset it"
    assert body["gatewayIdentifier"] == GW_ID
    # And nothing invented: every key came from the live read, or is the identifier.
    assert set(body) - {"gatewayIdentifier"} <= set(live)


def test_a_member_the_model_does_not_accept_is_not_sent():
    """`GetGateway` returns fields UpdateGateway rejects — gatewayId, createdAt, status.

    Sending one is a ValidationException, which this script classifies `unusable`; 120 of those
    report NOT_MEASURED for a reason that is our bug rather than a boundary.
    """
    body = M._replacement_kwargs(_live(), gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED)
    for junk in ("gatewayId", "createdAt", "updatedAt", "status", "gatewayUrl", "gatewayArn"):
        assert junk not in body
    assert set(body) <= ALLOWED


def test_the_body_does_not_share_nested_state_with_the_live_read():
    """The comparison that cannot fail.

    The caller keeps `live` for the end-of-run restore diff. If the flip body shared the nested
    `policyEngineConfiguration` dict, setting `mode = LOG_ONLY` on the body would ALSO set it on
    the record the restore is verified against, and `pec_restored_exactly` would compare LOG_ONLY
    to LOG_ONLY and pass while the gateway sat unenforced.
    """
    live = _live()
    before = copy.deepcopy(live)
    body = M._replacement_kwargs(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED,
                                 mode="LOG_ONLY")
    assert body["policyEngineConfiguration"]["mode"] == "LOG_ONLY"
    assert live == before, "building the flip body mutated the record the restore is checked against"
    assert live["policyEngineConfiguration"]["mode"] == "ENFORCE"
    # Distinct objects, not merely equal right now.
    assert body["policyEngineConfiguration"] is not live["policyEngineConfiguration"]
    assert body["protocolConfiguration"] is not live["protocolConfiguration"]


def test_mode_change_touches_nothing_but_the_mode():
    live = _live()
    noop = M._replacement_kwargs(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED)
    flip = M._replacement_kwargs(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED,
                                 mode="LOG_ONLY")
    differ = [k for k in set(noop) | set(flip) if noop.get(k) != flip.get(k)]
    assert differ == ["policyEngineConfiguration"]
    assert flip["policyEngineConfiguration"]["arn"] == noop["policyEngineConfiguration"]["arn"], (
        "the flip must keep the same engine attached; changing the arn is a different experiment")


def test_drop_pec_removes_only_that_member():
    live = _live()
    body = M._replacement_kwargs(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED,
                                 drop_pec=True)
    assert "policyEngineConfiguration" not in body
    assert body["protocolConfiguration"] == live["protocolConfiguration"]
    assert set(REQUIRED) <= set(body)


def test_a_missing_required_member_refuses_rather_than_sending_a_doomed_body():
    live = _live()
    del live["roleArn"]
    with pytest.raises(M.ConfigError) as exc:
        M._replacement_kwargs(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED)
    assert "roleArn" in str(exc.value)
    assert "NOT_MEASURED" in str(exc.value), (
        "the refusal must say what publishing over it would look like")


def test_setting_a_mode_on_a_gateway_with_no_engine_refuses():
    """`nopolicy` is F6's baseline. Asking for a mode on it is a category error, not a mutation."""
    live = _live()
    del live["policyEngineConfiguration"]
    with pytest.raises(M.ConfigError) as exc:
        M._replacement_kwargs(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED,
                              mode="LOG_ONLY")
    assert "nopolicy" in str(exc.value)


# ---- classification of one attempt ---------------------------------------

def test_access_denied_is_the_closed_reading(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([DENIED]))
    row = M._attempt(_AC(), None, kwargs={"gatewayIdentifier": GW_ID}, trial_id="t")
    assert row["outcome"] == "denied_by_iam"
    assert row["error_code"] == "AccessDeniedException"
    assert "AccessDenied" in M.DENIED_CODES, "the short form is what IAM returns on some APIs"


def test_a_validation_exception_is_unusable_and_never_a_denial(monkeypatch):
    """Mutation-checked in the direction that matters.

    A malformed body classified `denied_by_iam` publishes our own bug as a security boundary at a
    4.98% ceiling — the F5-1 hazard in a new shape, and the reason `n_usable` excludes this
    bucket instead of counting it.
    """
    monkeypatch.setattr(M, "capture", _Cap([INVALID]))
    row = M._attempt(_AC(), None, kwargs={}, trial_id="t")
    assert row["outcome"] == "unusable"
    assert row["outcome"] != "denied_by_iam"
    assert "ValidationException" not in M.DENIED_CODES
    assert "ValidationException" not in M.CONFLICT_CODES


def test_a_conflict_is_an_authorized_call_not_a_denial(monkeypatch):
    """`ConflictException` is returned AFTER authorization: the caller was allowed.

    Classifying it as a denial would retire a demonstrated bypass on a serialization detail.
    """
    monkeypatch.setattr(M, "capture", _Cap([CONFLICT]))
    row = M._attempt(_AC(), None, kwargs={}, trial_id="t")
    assert row["outcome"] == "conflict"
    assert row["outcome"] != "denied_by_iam"


def test_an_accepted_call_records_the_status_it_returned(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([ACCEPTED]))
    row = M._attempt(_AC(), None, kwargs={}, trial_id="t")
    assert row["outcome"] == "accepted"
    assert row["gateway_status_after"] == "UPDATING"
    assert row["elapsed_ms"] >= 0


def test_attempt_never_raises_because_the_error_is_the_measurement(monkeypatch):
    for rec in (DENIED, CONFLICT, INVALID, _Rec(ok=False, error_code="ThrottlingException")):
        monkeypatch.setattr(M, "capture", _Cap([rec]))
        assert M._attempt(_AC(), None, kwargs={}, trial_id="t")["outcome"] in (
            "denied_by_iam", "conflict", "unusable")


# ---- the tally ------------------------------------------------------------

class _CP:
    """A Checkpoint stand-in: the three methods `_run_arm` uses, and no disk."""

    def __init__(self):
        self._r: dict[str, dict] = {}

    def is_done(self, tid):
        return tid in self._r

    def run_trial(self, tid, fn):
        self._r[tid] = fn()
        return self._r[tid]

    def results(self):
        return self._r

    def save(self):
        pass


def _arm(monkeypatch, script, n, **kw):
    cap = _Cap(script)
    monkeypatch.setattr(M, "capture", cap)
    cp = _CP()
    return M._run_arm(_AC(), cp, None, arm="a", kwargs={}, n=n, **kw), cp, cap


def test_n_usable_excludes_unusable_and_n_authorized_folds_in_conflicts(monkeypatch):
    tally, _, _ = _arm(monkeypatch, [DENIED, DENIED, INVALID, CONFLICT, ACCEPTED], 5)
    assert tally["n_attempted"] == 5
    assert tally["n_denied"] == 2
    assert tally["n_unusable"] == 1
    assert tally["n_conflict"] == 1
    assert tally["n_accepted"] == 1
    assert tally["n_authorized"] == 2, "accepted + conflict"
    assert tally["n_usable"] == 4, "the ValidationException must not be denominated"
    assert tally["n_usable"] == tally["n_authorized"] + tally["n_denied"]
    assert tally["error_codes"] == ["AccessDeniedException", "ConflictException",
                                    "ValidationException"]


def test_an_all_unusable_arm_reports_zero_usable_rather_than_zero_adverse(monkeypatch):
    """The difference between 'nothing got through' and 'nothing was measured'."""
    tally, _, _ = _arm(monkeypatch, [INVALID], 10)
    assert tally["n_usable"] == 0
    assert tally["n_authorized"] == 0
    assert tally["n_unusable"] == 10


def test_a_completed_trial_is_never_re_sent(monkeypatch):
    """A resumed arm that re-sent trials would report a denominator it did not measure once."""
    cap = _Cap([DENIED])
    monkeypatch.setattr(M, "capture", cap)
    cp = _CP()
    M._run_arm(_AC(), cp, None, arm="a", kwargs={}, n=3)
    n_before = len(cap.calls)
    tally = M._run_arm(_AC(), cp, None, arm="a", kwargs={}, n=3)
    assert len(cap.calls) == n_before, "a resumed arm re-sent trials it had already completed"
    assert tally["n_attempted"] == 3


def test_the_closed_arm_does_not_poll_the_gateway_after_every_denial(monkeypatch):
    """A denial changes no state; 120 GetGateway polls would measure a status that cannot move."""
    seen: list[int] = []
    monkeypatch.setattr(M, "wait_ready", lambda *a, **k: (seen.append(1), _live())[1])
    _arm(monkeypatch, [DENIED], 5, settle=True, gateway_id=GW_ID)
    assert seen == [], "a denied attempt was followed by a settle poll"
    # ...but an ACCEPTED attempt in an arm that expects acceptance must settle, or the next
    # attempt races the UPDATING window and comes back ConflictException.
    _arm(monkeypatch, [ACCEPTED], 2, settle=True, gateway_id=GW_ID)
    assert len(seen) == 2


def test_a_settle_timeout_is_recorded_and_does_not_lose_the_authorization_outcome(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("never became terminal")
    monkeypatch.setattr(M, "wait_ready", boom)
    tally, cp, _ = _arm(monkeypatch, [ACCEPTED], 1, settle=True, gateway_id=GW_ID)
    assert tally["n_accepted"] == 1, "a settle failure must not erase an accepted call"
    row = next(iter(cp.results().values()))
    assert "TimeoutError" in row["settle_error"]


# ---- the interlocks -------------------------------------------------------

def test_the_role_interlock_refuses_when_a_crashed_runs_grant_is_still_attached(monkeypatch):
    """The guard that stops F5-2 refuting a security property with our own litter.

    Mutation-checked in both directions.
    """
    grants = (f"grx-f52-update-{RUN}", f"grx-f52-passrole-{RUN}")

    monkeypatch.setattr(M, "capture", _Cap([_Rec(response={"PolicyNames": [M.BASELINE_INLINE]})]))
    out = M._assert_role_is_pristine(None, None, role_name=ROLE, grant_names=grants)
    assert out["inline_policies_at_start"] == [M.BASELINE_INLINE]
    assert "live" in out["read_from"], "the baseline must be read from IAM, not from the ledger"

    for leftover in grants:
        monkeypatch.setattr(M, "capture", _Cap([
            _Rec(response={"PolicyNames": [M.BASELINE_INLINE, leftover]})]))
        with pytest.raises(M.ConfigError) as exc:
            M._assert_role_is_pristine(None, None, role_name=ROLE, grant_names=grants)
        msg = str(exc.value)
        assert leftover in msg
        assert "intact boundary" in msg, (
            "the refusal must name the leftover and say what publishing over it would claim")


def test_the_role_interlock_refuses_an_unfamiliar_inline_policy(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([
        _Rec(response={"PolicyNames": [M.BASELINE_INLINE, "someone-elses"]})]))
    with pytest.raises(M.ConfigError) as exc:
        M._assert_role_is_pristine(None, None, role_name=ROLE, grant_names=("g",))
    assert "someone-elses" in str(exc.value)


def test_a_failed_role_read_refuses_rather_than_reading_as_pristine(monkeypatch):
    """A guard that could not run must not report clean (`feedback_guard_tool_exit_codes`)."""
    monkeypatch.setattr(M, "capture", _Cap([_Rec(ok=False, error_code="AccessDenied")]))
    with pytest.raises(M.ConfigError) as exc:
        M._assert_role_is_pristine(None, None, role_name=ROLE, grant_names=("g",))
    assert "never measured" in str(exc.value)


def test_the_engine_interlock_refuses_when_another_case_has_a_policy_live():
    """A `forbid` on the shared engine changes another case's decisions and destroys its data."""
    ok = M._assert_engine_is_quiet(_State(["baseline"]))
    assert ok["policies_on_engine_at_start"] == ["baseline"]

    with pytest.raises(M.ConfigError) as exc:
        M._assert_engine_is_quiet(_State(["baseline", "f54a_probe"]))
    assert "f54a_probe" in str(exc.value)
    assert "not quiet" in str(exc.value)


def test_the_engine_interlock_reports_what_it_saw_even_when_it_passes():
    """Scope kept visible: an engine with no baseline at all is not this guard's subject."""
    out = M._assert_engine_is_quiet(_State([]))
    assert out["policies_on_engine_at_start"] == []


@pytest.mark.parametrize("over,needle", [
    ({"status": "UPDATING"}, "not READY"),
    ({"policyEngineConfiguration": {"arn": "arn:aws:x:::policy-engine/other",
                                    "mode": "ENFORCE"}}, "not in the request path"),
    ({"policyEngineConfiguration": {}}, "None"),
])
def test_the_gateway_interlock_refuses_each_way_the_start_state_can_be_wrong(over, needle):
    with pytest.raises(M.ConfigError) as exc:
        M._assert_gateway_is_provisioned(_live(**over), engine_arn=ENGINE_ARN)
    assert needle in str(exc.value)


def test_the_gateway_interlock_passes_on_the_provisioned_shape():
    out = M._assert_gateway_is_provisioned(_live(), engine_arn=ENGINE_ARN)
    assert out["status"] == "READY" and out["mode"] == "ENFORCE"
    assert out["engine_arn_matches_ledger"] is True
    assert "live" in out["read_from"]


def test_a_gateway_already_in_log_only_is_the_case_the_interlock_exists_for():
    """Starting in LOG_ONLY makes the bypass leg pass with no mutation from us.

    Kept out of the parametrised sweep because it is the one wrong start state that produces a
    PLAUSIBLE result rather than an obvious error.
    """
    with pytest.raises(M.ConfigError) as exc:
        M._assert_gateway_is_provisioned(
            _live(policyEngineConfiguration={"arn": ENGINE_ARN, "mode": "LOG_ONLY"}),
            engine_arn=ENGINE_ARN)
    assert "no mutation from us" in str(exc.value)


# ---- the propagation wait -------------------------------------------------

def _cycle(seq):
    """A scripted `capture` body that cycles forever, so a poll loop cannot exhaust it."""
    box = {"i": 0}

    def _f(op, params):
        rec = seq[box["i"] % len(seq)]
        box["i"] += 1
        return rec
    return _f


def test_the_wait_requires_consecutive_confirmations_not_cumulative(monkeypatch):
    """An ALTERNATING sequence is the state that has NOT converged.

    A cumulative counter is satisfied by exactly that, and would end the wait on the evidence
    that should keep it going. F5-1 measured the consequence: a revoke wait ended on a single
    denial and 9 of the next 20 calls then succeeded.
    """
    monkeypatch.setattr(M, "capture", _Cap([_cycle([ACCEPTED, DENIED])]))
    out = M._wait_for_effect(_AC(), None, kwargs={}, want="denied_by_iam", phase="p", max_s=100)
    assert out["reached"] is False, "an alternating sequence must not satisfy the wait"
    assert out["consecutive_confirmations"] < M.PROP_CONFIRM_N
    assert out["outcomes_seen"].count("denied_by_iam") >= M.PROP_CONFIRM_N, (
        "the point of the test: enough CUMULATIVE confirmations to satisfy a naive counter")
    assert "never confirmed to have settled" in out["why_it_matters"]


def test_the_wait_records_that_it_flapped_before_converging(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([DENIED, ACCEPTED, DENIED, DENIED, DENIED]))
    out = M._wait_for_effect(_AC(), None, kwargs={}, want="denied_by_iam", phase="p", max_s=1000)
    assert out["reached"] is True
    assert out["consecutive_confirmations"] == M.PROP_CONFIRM_N
    assert out["flapped_before_converging"] is True, (
        "one confirmation before the final streak is exactly what a reader needs to see")
    assert out["n_wanted_outcomes_before_the_final_streak"] == 1
    assert out["seconds"] >= out["seconds_to_first_confirmation"]


def test_the_wait_returns_rather_than_asserting_so_a_timeout_is_publishable(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([DENIED]))
    out = M._wait_for_effect(_AC(), None, kwargs={}, want="accepted", phase="p", max_s=30)
    assert out["reached"] is False and out["max_wait_s"] == 30
    assert out["outcomes_seen"], "the outcomes actually seen must be kept"
    assert out["confirmations_required"] == M.PROP_CONFIRM_N


def test_the_revoke_direction_gets_the_longer_bound():
    """A revoke that has not landed is a HOLE in the boundary, and is not cost-bound by n."""
    assert M.PROP_MAX_REVOKE_S > M.PROP_MAX_S
    assert "max_s=PROP_MAX_REVOKE_S" in SRC


def test_the_propagation_probes_cannot_be_confused_with_arm_trials(monkeypatch):
    """A probe counted into an arm would inflate the confirmatory denominator."""
    cap = _Cap([DENIED])
    monkeypatch.setattr(M, "capture", cap)
    M._wait_for_effect(_AC(), None, kwargs={}, want="accepted", phase="grant_update", max_s=30)
    assert "probe__" in SRC
    assert cap.ops and set(cap.ops) == {"update_gateway"}


# ---- the chain ------------------------------------------------------------

def test_the_forbid_uses_the_only_decimal_operator_proven_on_this_engine():
    """Cedar decimal has no `>=`/`<`. F4 verified `lessThan` — it created AND it matched.

    A `context.input.amount >= 500` condition would fail to create, or create and never match,
    and every leg would then read for the wrong reason.
    """
    stmt = M._forbid_statement(GW_ARN, ACTION)
    assert "lessThan" in stmt
    assert ">=" not in stmt and " > " not in stmt and " < " not in stmt
    assert "has amount" in stmt, (
        "without the `has` guard an amount-less request raises on the attribute access, and an "
        "evaluation error is not a policy decision")
    assert 'decimal("500.0")' in stmt, "the literal must carry a decimal point"
    assert stmt.startswith("forbid")
    assert ACTION in stmt and GW_ID in stmt
    assert C.check_statement(stmt) == [], "the offline Cedar lint rejects the chain's own control"


def test_the_probe_amounts_carry_a_decimal_point_on_the_wire():
    """MEASURED on this engine: `"amount": 100` is refused for want of a decimal point.

    Both halves then deny for an evaluation error rather than a policy decision, so the payload
    has to serialise as 999.0, not 999.
    """
    for amount in (M.BLOCK_AMOUNT, M.ALLOW_AMOUNT, M.AMOUNT_LIMIT):
        assert isinstance(amount, float)
        assert "." in json.dumps({"amount": amount})
    assert M.BLOCK_AMOUNT >= M.AMOUNT_LIMIT, "the blocked amount must be on the forbidden side"
    assert M.ALLOW_AMOUNT < M.AMOUNT_LIMIT


def test_the_forbid_is_recorded_in_the_ledger_immediately_after_it_is_created(monkeypatch):
    """`policy` resources take no tags, so the ledger is the only channel that can find one."""
    st = _State()
    cap = _Cap([lambda op, p: (st.order.append(f"call:{op}"),
                               _Rec(response={"policyId": "pid-1"}))[1]])
    monkeypatch.setattr(M, "capture", cap)
    monkeypatch.setattr(M, "wait_status", lambda get, ident, **k: {"status": "ACTIVE"})
    out = M._create_forbid(_AC(), None, st, engine_id="eng", run_id=RUN,
                          statement=M._forbid_statement(GW_ARN, ACTION))
    assert out["status"] == "ACTIVE" and out["policy_id"] == "pid-1"
    assert st.order[:3] == ["call:create_policy", "record:f52_block", "write"], (
        f"the create must be followed immediately by the ledger write: {st.order}")
    rec = st.recorded[0]
    assert rec.delete_op == "delete_policy"
    assert rec.delete_params == {"policyEngineId": "eng", "policyId": "pid-1"}


def test_a_policy_that_settles_unhealthy_refuses_rather_than_running_the_chain(monkeypatch):
    st = _State()
    monkeypatch.setattr(M, "capture", _Cap([_Rec(response={"policyId": "pid-1"})]))
    monkeypatch.setattr(M, "wait_status",
                        lambda get, ident, **k: {"status": "CREATE_FAILED",
                                                 "statusReasons": ["bad"]})
    with pytest.raises(M.ConfigError) as exc:
        M._create_forbid(_AC(), None, st, engine_id="eng", run_id=RUN,
                         statement=M._forbid_statement(GW_ARN, ACTION))
    assert "never enforced" in str(exc.value)
    assert "bypass of nothing" in str(exc.value)


def test_a_failed_create_refuses_because_the_chain_would_have_no_subject(monkeypatch):
    st = _State()
    monkeypatch.setattr(M, "capture", _Cap([
        _Rec(ok=False, error_code="ValidationException", error_message="nope")]))
    with pytest.raises(M.ConfigError) as exc:
        M._create_forbid(_AC(), None, st, engine_id="eng", run_id=RUN,
                         statement=M._forbid_statement(GW_ARN, ACTION))
    assert "no subject" in str(exc.value)
    assert st.recorded == [], "nothing was created, so nothing may be recorded"


def test_delete_forbid_never_raises_and_retries(monkeypatch):
    """It runs in a `finally`; an exception there would abandon the grants still on the role."""
    st = _State()
    monkeypatch.setattr(M, "capture", _Cap([_Rec(ok=False, error_code="ThrottlingException")]))
    out = M._delete_forbid(_AC(), None, st, engine_id="eng", policy_id="pid")
    assert out["deleted"] is False
    assert out["attempts"] == M.DELETE_ATTEMPTS
    assert "pid" in out["manual_remedy"], "an undeleted policy must leave a runnable remedy"
    assert len(out["errors"]) == M.DELETE_ATTEMPTS

    monkeypatch.setattr(M, "capture", _Cap([_Rec(ok=False,
                                                 error_code="ResourceNotFoundException")]))
    gone = M._delete_forbid(_AC(), None, st, engine_id="eng", policy_id="pid")
    assert gone["deleted"] is True, "already-absent is deleted"
    assert "drop:policy/f52_block" in st.order


# ---- the data-plane legs --------------------------------------------------

class _D:
    def __init__(self, denied=False, ran=False, status=200):
        self.denied, self.ran, self.http_status = denied, ran, status

    def to_json(self):
        return {"denied": self.denied, "ran": self.ran}


class _Client:
    """An MCP client stand-in returning a scripted, cycling sequence of decisions."""

    def __init__(self, decisions):
        self._d = list(decisions)
        self.i = 0
        self.calls: list[dict] = []
        self.closed = 0

    def call_tool(self, name, arguments=None, **kw):
        self.calls.append({"name": name, "arguments": arguments})
        d = self._d[self.i % len(self._d)]
        self.i += 1
        if isinstance(d, Exception):
            raise d
        return d

    def initialize(self):
        pass

    def close(self):
        self.closed += 1


def test_a_leg_is_all_or_nothing_and_a_split_is_reported_not_averaged():
    deny = M._probe_leg(_Client([_D(denied=True)]), leg="l", action_id=ACTION,
                        amount=M.BLOCK_AMOUNT, run_id=RUN, n=3)
    assert deny["decision"] == "DENY" and deny["unanimous"] is True
    assert deny["n_denied"] == 3 and deny["n"] == 3

    allow = M._probe_leg(_Client([_D(ran=True)]), leg="l", action_id=ACTION,
                         amount=M.ALLOW_AMOUNT, run_id=RUN, n=3)
    assert allow["decision"] == "ALLOW" and allow["unanimous"] is True

    split = M._probe_leg(_Client([_D(denied=True), _D(ran=True), _D(denied=True)]),
                         leg="l", action_id=ACTION, amount=M.BLOCK_AMOUNT, run_id=RUN, n=3)
    assert split["decision"] == "SPLIT", (
        "an E-class mechanism that answers differently to identical requests is a finding, not a "
        "rate to average")
    assert split["unanimous"] is False


def test_a_leg_sends_the_amount_it_was_asked_for_and_labels_every_request():
    c = _Client([_D(denied=True)])
    M._probe_leg(c, leg="l", action_id=ACTION, amount=M.BLOCK_AMOUNT, run_id=RUN, n=3)
    assert all(call["arguments"]["amount"] == M.BLOCK_AMOUNT for call in c.calls)
    assert all(call["name"] == ACTION for call in c.calls)
    assert len({call["arguments"]["text"] for call in c.calls}) == 3, (
        "each request must be individually identifiable in the log surface")
    assert all(RUN in call["arguments"]["text"] for call in c.calls)


def test_the_data_plane_wait_needs_consecutive_confirmations_too(monkeypatch):
    """ALLOW, DENY, ALLOW, DENY is a data plane mid-flip, not a converged one.

    The alternation is driven from a counter shared ACROSS sessions, because the wait opens a
    fresh session per probe — a per-client sequence would replay its first element every time and
    the loop would converge immediately, testing nothing.
    """
    clients: list[_Client] = []
    box = {"i": 0}
    seq = [_D(ran=True), _D(denied=True)]

    def _mk(*a, **k):
        c = _Client([seq[box["i"] % len(seq)]])
        box["i"] += 1
        clients.append(c)
        return c
    monkeypatch.setattr(M, "_client_for_leg", _mk)
    out = M._wait_for_decision(None, None, None, action_id=ACTION, want="ALLOW", run_id=RUN,
                               phase="p")
    assert out["reached"] is False, (
        "treating a mid-flip data plane as converged would attribute the next leg to a mutation "
        "that had not fully taken effect")
    assert out["decisions_seen"][:4] == ["ALLOW", "DENY", "ALLOW", "DENY"]
    assert out["decisions_seen"].count("ALLOW") >= M.DATA_PLANE_CONFIRM_N, (
        "cumulatively satisfied, consecutively not — which is the distinction under test")
    assert clients and all(c.closed == 1 for c in clients), "every probe session must be closed"


def test_the_data_plane_wait_converges_on_consecutive_agreement(monkeypatch):
    monkeypatch.setattr(M, "_client_for_leg", lambda *a, **k: _Client([_D(ran=True)]))
    out = M._wait_for_decision(None, None, None, action_id=ACTION, want="ALLOW", run_id=RUN,
                               phase="p")
    assert out["reached"] is True
    assert out["consecutive_confirmations"] == M.DATA_PLANE_CONFIRM_N
    assert out["decisions_seen"] == ["ALLOW"] * M.DATA_PLANE_CONFIRM_N


def test_the_data_plane_wait_survives_a_transport_error_as_data(monkeypatch):
    monkeypatch.setattr(M, "_client_for_leg",
                        lambda *a, **k: _Client([RuntimeError("connection reset")]))
    out = M._wait_for_decision(None, None, None, action_id=ACTION, want="ALLOW", run_id=RUN,
                               phase="p")
    assert out["reached"] is False
    assert any(s.startswith("ERROR:") for s in out["decisions_seen"]), (
        "a transport error must be visible in the sequence, not silently retried into a pass")


# ---- the restore check ----------------------------------------------------

def test_the_restore_ignore_list_is_the_pairing_rule_minus_the_field_this_case_moves():
    """Imported, not retyped. The pairing rule F6 depends on has ONE definition.

    And `policyEngineConfiguration` must be REMOVED from it here: PAIR_IGNORE exists to answer
    "does anything ELSE differ" for F6's pair, but it is the subject of this case, and ignoring it
    would make the restore check blind to the only thing that could have been left wrong.
    """
    assert "policyEngineConfiguration" in M.PAIR_IGNORE
    assert "policyEngineConfiguration" not in M.RESTORE_IGNORE
    assert set(M.RESTORE_IGNORE) == set(M.PAIR_IGNORE) - {"policyEngineConfiguration"}
    assert M.diff_configs is M._gwmod.diff_configs
    assert "PAIR_IGNORE = (" not in SRC, "the pairing rule must be imported, not copied"


def _differs(before, after, field):
    """`diff_configs` returns one human-readable line per field, so match the field it names.

    A bare `field in diff` would be a substring test against a list of strings, which is False
    even when the field IS reported — the assertion would pass only by accident and would keep
    passing if the diff stopped reporting anything at all.
    """
    lines = M.diff_configs(before, after, ignore=M.RESTORE_IGNORE)
    return [ln for ln in lines if ln.split(":")[0] == field]


def test_the_restore_diff_notices_a_field_the_attack_would_have_reset():
    """The silent reset, caught by the check that is supposed to catch it."""
    before = _live()
    after = _live()
    del after["exceptionLevel"]
    assert _differs(before, after, "exceptionLevel"), "a dropped exceptionLevel went unreported"

    after2 = _live()
    after2["protocolConfiguration"] = {"mcp": {"sessionConfiguration":
                                               {"sessionTimeoutInSeconds": 60}}}
    assert _differs(before, after2, "protocolConfiguration"), (
        "a reset session timeout went unreported")

    assert M.diff_configs(before, _live(), ignore=M.RESTORE_IGNORE) == [], (
        "the control arm: an untouched gateway must diff clean, or every run reports damage")


def test_the_restore_diff_notices_a_gateway_left_in_log_only():
    after = _live(policyEngineConfiguration={"arn": ENGINE_ARN, "mode": "LOG_ONLY"})
    assert _differs(_live(), after, "policyEngineConfiguration"), (
        "a gateway left unenforced is the one outcome this diff must never miss")


# ---- the guards, evaluated as the script evaluates them -------------------

def _guards(*, closed, granted, legs, pec_equal=True, diff=None, mode_at_end="ENFORCE",
            gw_read_ok=True, role_read_ok=True, inline_at_end=None, n_required=120,
            forbid_deleted=True):
    """Re-evaluate the script's guard expressions on synthetic tallies.

    A local restatement rather than a call into `main()`: `main` is 200 lines of AWS
    orchestration, and a test that had to fake all of it would be testing the fake.
    `test_the_guard_expressions_here_match_the_script` pins this helper to the shipped names.
    """
    return {
        "granted_arm_proved_the_call_is_otherwise_accepted": granted.get("n_authorized", 0) > 0,
        "blocking_policy_was_load_bearing_before_the_mutation":
            legs.get(M.LEG_ENFORCE_BLOCKED, {}).get("decision") == "DENY"
            and legs.get(M.LEG_ENFORCE_ALLOWED, {}).get("decision") == "ALLOW",
        "log_only_flip_let_the_blocked_request_through":
            legs.get(M.LEG_LOGONLY_BLOCKED, {}).get("decision") == "ALLOW",
        "blocking_was_reasserted_in_the_data_plane":
            legs.get(M.LEG_REASSERTED, {}).get("decision") == "DENY",
        "gateway_was_restored_field_for_field":
            gw_read_ok is True and (diff if diff is not None else []) == []
            and pec_equal is True and mode_at_end == M.MODE_ENFORCE,
        "grants_were_removed_from_the_role":
            role_read_ok is True
            and (inline_at_end if inline_at_end is not None
                 else [M.BASELINE_INLINE]) == [M.BASELINE_INLINE],
        "probe_policy_was_deleted": forbid_deleted,
        "usable_trials_met_the_preregistered_n":
            closed.get("n_usable", 0) >= n_required or closed.get("n_authorized", 0) > 0,
    }


CLEAN_LEGS = {M.LEG_ENFORCE_BLOCKED: {"decision": "DENY"},
              M.LEG_ENFORCE_ALLOWED: {"decision": "ALLOW"},
              M.LEG_LOGONLY_BLOCKED: {"decision": "ALLOW"},
              M.LEG_REASSERTED: {"decision": "DENY"}}
CLOSED_CLEAN = {"n_usable": 120, "n_authorized": 0, "n_denied": 120}
GRANTED_OK = {"n_usable": 5, "n_authorized": 5}


def test_the_guard_expressions_here_match_the_script():
    """A local restatement that drifted from the script would test nothing.

    Every name in the shipped GUARDS tuple must be covered either by this helper or by an
    interlock test above, and must actually be COMPUTED in the script rather than only declared.
    """
    covered = set(_guards(closed=CLOSED_CLEAN, granted=GRANTED_OK, legs=CLEAN_LEGS))
    interlocks = {"gateway_started_in_its_provisioned_configuration",
                  "role_started_in_its_shipped_configuration",
                  "engine_was_quiet_at_start"}
    assert set(M.GUARDS) == covered | interlocks
    for name in M.GUARDS:
        assert f'"{name}":' in SRC, f"{name} is declared in GUARDS but never computed"


def test_a_clean_run_passes_every_guard():
    g = _guards(closed=CLOSED_CLEAN, granted=GRANTED_OK, legs=CLEAN_LEGS)
    assert all(g.values()), [k for k, v in g.items() if not v]


def test_the_granted_arm_gate_is_what_stops_the_f5_1_hazard():
    """120 denials with a mutation that never inverted must NOT publish.

    This is the whole reason the arms are staged. Without this gate, a wrong gateway identifier
    produces a TRUE at a 4.98% ceiling.
    """
    g = _guards(closed=CLOSED_CLEAN, granted={"n_usable": 5, "n_authorized": 0}, legs=CLEAN_LEGS)
    assert g["granted_arm_proved_the_call_is_otherwise_accepted"] is False
    assert 'if not guards["granted_arm_proved_the_call_is_otherwise_accepted"]:' in SRC
    assert "the mandatory mutation did not invert" in SRC, (
        "the NOT_MEASURED reason has to say which way the instrument failed")
    # `_guards` above is a local restatement, so it cannot notice the script weakening its own
    # expression to `n_usable > 0` — which would pass the gate on five denials. The count pins
    # both places the script must ask about AUTHORIZATION specifically: the verdict gate, and the
    # inversion flag. Two claims, counted separately (`feedback_two_numbers_two_claims`).
    assert SRC.count('granted.get("n_authorized", 0) > 0') == 2, (
        "the gate and the inversion flag must each ask whether the granted arm was AUTHORIZED, "
        "not whether it returned something")


def test_a_conflict_alone_satisfies_the_granted_arm_gate():
    """A ConflictException means IAM said yes. The gate asks about authorization, not effect."""
    g = _guards(closed=CLOSED_CLEAN,
                granted={"n_usable": 5, "n_authorized": 1, "n_accepted": 0, "n_conflict": 1},
                legs=CLEAN_LEGS)
    assert g["granted_arm_proved_the_call_is_otherwise_accepted"] is True


@pytest.mark.parametrize("legs,failing", [
    ({**CLEAN_LEGS, M.LEG_ENFORCE_BLOCKED: {"decision": "ALLOW"}},
     "blocking_policy_was_load_bearing_before_the_mutation"),
    ({**CLEAN_LEGS, M.LEG_ENFORCE_ALLOWED: {"decision": "DENY"}},
     "blocking_policy_was_load_bearing_before_the_mutation"),
    ({**CLEAN_LEGS, M.LEG_LOGONLY_BLOCKED: {"decision": "DENY"}},
     "log_only_flip_let_the_blocked_request_through"),
    ({**CLEAN_LEGS, M.LEG_LOGONLY_BLOCKED: {"decision": "SPLIT"}},
     "log_only_flip_let_the_blocked_request_through"),
    ({**CLEAN_LEGS, M.LEG_REASSERTED: {"decision": "ALLOW"}},
     "blocking_was_reasserted_in_the_data_plane"),
])
def test_each_chain_leg_is_gated_separately(legs, failing):
    """A forbid that blocked everything, or nothing, breaks a DIFFERENT guard than a failed flip.

    Collapsing them would let a control failure be reported as a bypass.
    """
    g = _guards(closed=CLOSED_CLEAN, granted=GRANTED_OK, legs=legs)
    assert g[failing] is False
    assert not all(g.values())


def test_a_missing_leg_is_a_failure_not_an_absent_pass():
    """`all([])` over legs that never ran would pass. Enumerated keys prevent that."""
    g = _guards(closed=CLOSED_CLEAN, granted=GRANTED_OK, legs={})
    assert g["blocking_policy_was_load_bearing_before_the_mutation"] is False
    assert g["log_only_flip_let_the_blocked_request_through"] is False
    assert g["blocking_was_reasserted_in_the_data_plane"] is False


@pytest.mark.parametrize("kw", [
    {"pec_equal": False},
    {"diff": ["exceptionLevel"]},
    {"mode_at_end": "LOG_ONLY"},
    {"gw_read_ok": False},
])
def test_the_restore_guard_fails_each_way_the_gateway_can_be_left_wrong(kw):
    g = _guards(closed=CLOSED_CLEAN, granted=GRANTED_OK, legs=CLEAN_LEGS, **kw)
    assert g["gateway_was_restored_field_for_field"] is False


def test_a_failed_end_state_read_is_not_a_clean_role():
    """A failed `ListRolePolicies` records `None`, and the read-ok flag is required as well.

    Both are asserted so neither can be dropped: `None == [BASELINE]` is already False, which is
    exactly the kind of accident that makes a real guard look redundant and get deleted.
    """
    g = _guards(closed=CLOSED_CLEAN, granted=GRANTED_OK, legs=CLEAN_LEGS,
                role_read_ok=False, inline_at_end=None)
    assert g["grants_were_removed_from_the_role"] is False

    g2 = _guards(closed=CLOSED_CLEAN, granted=GRANTED_OK, legs=CLEAN_LEGS,
                 role_read_ok=True, inline_at_end=[M.BASELINE_INLINE, f"grx-f52-update-{RUN}"])
    assert g2["grants_were_removed_from_the_role"] is False, (
        "a surviving grant is an unattended permission on a role whose purpose is to lack it")
    assert 'grants.get("end_state_read_ok") is True' in SRC


def test_the_n_floor_does_not_gate_away_a_demonstrated_bypass():
    """One accepted UpdateGateway IS the finding.

    A bypass does not become unproven because the other 119 attempts were unusable, and gating on
    n alone would publish NOT_MEASURED over a demonstrated bypass — the one direction of error
    this family exists to catch.
    """
    g = _guards(closed={"n_usable": 4, "n_authorized": 1}, granted=GRANTED_OK, legs=CLEAN_LEGS)
    assert g["usable_trials_met_the_preregistered_n"] is True

    # ...but a short arm with NO bypass is not publishable: that is a bound the run did not earn.
    g2 = _guards(closed={"n_usable": 4, "n_authorized": 0}, granted=GRANTED_OK, legs=CLEAN_LEGS)
    assert g2["usable_trials_met_the_preregistered_n"] is False
    assert 'or closed.get("n_authorized", 0) > 0' in SRC


def test_the_confirmatory_denominator_comes_from_the_closed_arm_alone():
    """`feedback_two_numbers_two_claims`: adverse and n must not be summed across arms.

    A denominator of 148 would report a ceiling the closed arm never earned, and the granted arm
    is DESIGNED to be authorized — folding it in would put the mutation's successes into the
    numerator of the security claim.
    """
    assert 'adverse=closed["n_authorized"]' in SRC
    assert 'n=closed["n_usable"]' in SRC
    for other in ("granted[", "update_only[", "restored["):
        assert f"adverse={other}" not in SRC


def test_zero_events_reads_one_authorized_call_as_false():
    """The verdict arithmetic, through the sealed oracle rather than paraphrased."""
    clean = P.obs_zero_events("F5-2", adverse=0, n=120)
    clean.mutation_inverted = True
    assert O.evaluate(clean)["verdict"] == O.TRUE

    one = P.obs_zero_events("F5-2", adverse=1, n=120)
    one.mutation_inverted = True
    assert O.evaluate(one)["verdict"] == O.FALSE, (
        "a single authorized UpdateGateway refutes a non-bypassable claim")


def test_mutation_inverted_is_set_as_an_attribute_not_passed_as_a_keyword():
    """The F5-1 defect, pinned.

    Passed as `**detail` the value lands where the decision rule never looks, the field keeps its
    default, and a mandatory-mutation case downgrades a clean TRUE to INCONCLUSIVE while the
    payload plainly shows the mutation inverted. `P._detail` now refuses that spelling; this
    asserts the script uses the other one.
    """
    assert "obs.mutation_inverted = " in SRC
    assert "mutation_inverted=" not in SRC, "the keyword spelling is the F5-1 bug"
    with pytest.raises(TypeError) as exc:
        P.obs_zero_events("F5-2", adverse=0, n=120, mutation_inverted=True)
    assert "not free-form detail" in str(exc.value)


def test_the_inversion_flag_requires_both_halves():
    """`mutation_inverted` is about a DIFFERENCE between the arms, not about the granted arm."""
    assert 'granted.get("n_authorized", 0) > 0' in SRC
    assert 'closed.get("n_authorized", 1) == 0' in SRC, (
        "the default must be 1, so a missing closed arm reads as NOT inverted rather than as a "
        "clean inversion")


def test_evaluate_is_called_with_the_observation_alone():
    """`O.evaluate(obs)` — passing CASE again is a TypeError, and a call site is where it hides."""
    assert "O.evaluate(obs)" in SRC
    assert "O.evaluate(CASE" not in SRC


# ---- the disposable-gateway probe ----------------------------------------

def _null_probe(monkeypatch, *, pec_after, status_after="READY", update=None):
    """Run `_null_pec_probe` against a scripted control plane. Returns (out, capture, state)."""
    st = _State()
    seen = {"n": 0}

    def _script(op, params):
        if op == "create_gateway":
            return _Rec(response={"gatewayId": "disposable-1",
                                  "gatewayArn": "arn:aws:x:::gateway/disposable-1"})
        if op == "update_gateway" and update is not None:
            return update
        return _Rec(response={})

    cap = _Cap([_script])
    monkeypatch.setattr(M, "capture", cap)

    def _wr(ac, gid, **k):
        seen["n"] += 1
        if seen["n"] == 1:                       # the disposable gateway, as created
            return _live(gatewayId=gid, status="READY")
        return _live(gatewayId=gid, status=status_after, statusReasons=["boom"],
                     policyEngineConfiguration=pec_after)
    monkeypatch.setattr(M, "wait_ready", _wr)
    out = M._null_pec_probe(_AC(), None, st, live=_live(), run_id=RUN, allowed=ALLOWED,
                            required=REQUIRED)
    return out, cap, st


def test_the_null_pec_probe_is_off_by_default():
    r = subprocess.run([PY, str(SCRIPT), "--dry-run"], cwd=ROOT, capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "--also-null-pec: off" in r.stdout


def test_the_null_pec_probe_never_names_the_main_gateway(monkeypatch):
    """An irreversible detach on `main` retroactively unmakes the F4 and F6 verdicts.

    `main` is the ENFORCE half of the pair `nopolicy` is the baseline for. The probe must create
    its own gateway, update THAT one, and delete it.
    """
    out, cap, st = _null_probe(monkeypatch, pec_after=None)
    ids = [p.get("gatewayIdentifier") for _, p in cap.calls if "gatewayIdentifier" in p]
    assert ids, "the probe made no identified call at all"
    assert GW_ID not in ids, (
        "the omission probe touched the MAIN gateway; an irreversible detach there unmakes the F4 "
        "truth table and every F6 latency verdict")
    assert set(ids) == {"disposable-1"}
    assert cap.ops.count("create_gateway") == 1
    assert out["deleted"] is True, "the disposable gateway must not outlive the probe"
    assert "drop:gateway/f52_null_probe" in st.order
    assert out["pec_was_cleared"] is True
    assert "CLEARED" in out["reading"]
    assert out["omitted_members"] == ["policyEngineConfiguration"], (
        "exactly one member may be omitted, or the probe is about more than one question")


def test_the_null_pec_probe_reports_a_surviving_field_as_a_closed_route(monkeypatch):
    out, _, _ = _null_probe(monkeypatch, pec_after={"arn": ENGINE_ARN, "mode": "ENFORCE"})
    assert out["pec_was_cleared"] is False
    assert "did NOT clear" in out["reading"]


def test_the_null_pec_probe_deletes_its_gateway_even_when_the_update_fails(monkeypatch):
    out, cap, _ = _null_probe(
        monkeypatch, pec_after=None,
        update=_Rec(ok=False, error_code="ValidationException", error_message="nope"))
    assert "delete_gateway" in cap.ops
    assert out["update_accepted"] is False
    assert out.get("pec_was_cleared") is None, (
        "a rejected update must not be read as having cleared anything")


def test_a_probe_gateway_that_settles_unhealthy_reports_nothing_rather_than_a_finding(monkeypatch):
    """The strongest version of this finding must not be derivable from a FAILED update."""
    out, cap, _ = _null_probe(monkeypatch, pec_after=None, status_after="UPDATE_UNSUCCESSFUL")
    assert out["pec_was_cleared"] is False
    assert "measured nothing" in out["reading"]
    assert "delete_gateway" in cap.ops


# ---- blast radius and the ledger -----------------------------------------

def test_the_grant_is_recorded_in_the_ledger_before_it_is_created(monkeypatch):
    """`finally` is not a watchdog — SIGKILL skips it. The ledger is the durable channel.

    A stale entry costs one `NoSuchEntity` at teardown; a created grant with no entry is a
    permanent unattended permission on a role whose entire purpose is to lack it.
    """
    st = _State()
    cap = _Cap([lambda op, p: (st.order.append(f"call:{op}"), _Rec())[1]])
    monkeypatch.setattr(M, "capture", cap)
    M._put_grant(None, None, st, role_name=ROLE, policy_name="p", logical="lg",
                 document={"Version": "2012-10-17", "Statement": []})
    assert st.order == ["record:lg", "write", "call:put_role_policy"], (
        f"the ledger must be written BEFORE the grant exists: {st.order}")
    rec = st.recorded[0]
    assert rec.delete_op == "delete_role_policy"
    assert rec.delete_params == {"RoleName": ROLE, "PolicyName": "p"}
    assert rec.delete_priority < 50, "an inline policy must be deleted before its role"


def test_a_failed_grant_refuses_because_the_mutation_could_not_be_applied(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([_Rec(ok=False, error_code="AccessDenied")]))
    with pytest.raises(M.ConfigError) as exc:
        M._put_grant(None, None, _State(), role_name=ROLE, policy_name="p", logical="lg",
                     document={})
    assert "mandatory mutation" in str(exc.value)


def test_the_grants_are_scoped_to_one_resource_each():
    """A wildcard would additionally answer questions about the six gateways we must not touch."""
    st = M._update_gateway_grant(GW_ARN)["Statement"][0]
    assert st["Resource"] == GW_ARN and st["Resource"] != "*"
    assert st["Action"] == "bedrock-agentcore:UpdateGateway"
    assert isinstance(st["Action"], str), "one action, so the arm differs by exactly one thing"

    # A DIFFERENT role name than the fixture's, so the assertion below cannot pass on a grant that
    # ignored its argument. Built from the fixture rather than written out, which keeps the ARN
    # literal on one reviewed line in this file instead of two.
    other_role = GW_EXEC_ROLE_ARN.rsplit("/", 1)[0] + "/grx-gw-exec-x"
    pr = M._pass_role_grant(other_role)["Statement"][0]
    assert pr["Action"] == "iam:PassRole"
    assert pr["Resource"].endswith("grx-gw-exec-x")
    assert pr["Resource"] != "*"


def test_the_two_grants_are_separate_named_policies():
    """So each undo is 'delete a named policy' rather than 'edit a document back', and the staged
    arms differ by exactly one statement."""
    assert M.GRANT_UPDATE_SID != M.GRANT_PASSROLE_SID
    assert "grx-f52-update-" in SRC and "grx-f52-passrole-" in SRC


def test_pass_role_is_only_granted_when_update_alone_was_denied():
    """Otherwise `binding_permission` could not distinguish the two, which is the finding."""
    assert 'needs_passrole = tallies[ARM_UPDATE_ONLY].get("n_authorized", 0) == 0' in SRC
    assert "if needs_passrole:" in SRC
    assert "binding_permission" in SRC


def test_the_arms_are_declared_and_the_granted_arms_are_deliberately_small():
    """Each accepted attempt is a real UPDATING/READY cycle on the gateway F4 and F6 use."""
    assert M.ARMS == (M.ARM_CLOSED, M.ARM_UPDATE_ONLY, M.ARM_GRANTED, M.ARM_RESTORED)
    assert 0 < M.N_UPDATE_ONLY < M.PLANNED_N
    assert 0 < M.N_GRANTED < M.PLANNED_N
    assert 0 < M.N_RESTORED < M.PLANNED_N


def test_the_script_never_deletes_the_gateway_or_the_engine_it_borrows():
    """Never touch: the six pre-existing gateways, `nopolicy`, the shared engine."""
    assert "delete_policy_engine" not in SRC
    assert SRC.count("delete_gateway") == 2, (
        "one capture call plus one ledger delete_op, both for the disposable probe; anything else "
        "is a gateway this case has no standing to remove")
    assert "nopolicy" in SRC, "the reason main must be left in ENFORCE should be written down"


def test_the_restore_is_read_back_with_admin_credentials():
    """The runtime role loses its grant in the same `finally`. `main` must still be ENFORCE."""
    assert 'capture(store, "get_gateway", ac_admin, gatewayIdentifier=gateway_id)' in SRC
    assert "restore_as_admin" in SRC and "restore_as_runtime" in SRC
    assert "_settle(ac_admin, gateway_id)" in SRC


def test_the_grants_are_swept_in_the_finally_whatever_happened_above():
    """Belt and braces: the closed arm's whole premise is a role that lacks these permissions."""
    assert 'mutation_log["grants"]["swept_in_finally"]' in SRC
    assert "stragglers" in SRC


# ---- the declared plan ----------------------------------------------------

def _dry(*extra):
    r = subprocess.run([PY, str(SCRIPT), "--dry-run", *extra], cwd=ROOT, capture_output=True,
                       text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_the_dry_run_banner_declares_the_mutations_and_bills_no_text_units():
    out = _dry()
    assert "F5-2 dry run" in out
    assert "mutations: " in out
    assert "billable text-unit sources: ~0" in out, (
        "a nonzero figure would mean a model call crept into a case about authorization")
    for phrase in ("FULL REPLACEMENT", "forbid", "interlocks", "CONSECUTIVE"):
        assert phrase in out
    assert f"pre-registered n: {M.PLANNED_N}" in out


def test_the_dry_run_declares_more_mutations_when_the_optional_probe_is_on():
    def _muts(out):
        return int(out.split("mutations: ")[1].split()[0])

    base, more = _dry(), _dry("--also-null-pec")
    assert _muts(more) > _muts(base), (
        "an extra gateway created and destroyed is extra blast radius and must be declared")
    assert "--also-null-pec: ON" in more


def test_a_smoke_run_shrinks_every_arm_not_just_the_confirmatory_one():
    """`--n 2` must not leave a 20-attempt restored arm on a smoke test."""
    out = _dry("--n", "2")
    arm_lines = [ln for ln in out.splitlines()
                 if any(ln.strip().startswith(a) for a in M.ARMS)]
    assert len(arm_lines) == len(M.ARMS)
    assert all(ln.rstrip().endswith("n=2") for ln in arm_lines), arm_lines


def test_the_dry_run_total_matches_the_arms_it_prints():
    """`dry_run_banner` raises if `operations` does not sum to the arm total, so this pins the
    declared operation mix rather than re-deriving the sum."""
    out = _dry()
    total = int(out.split("total calls: ")[1].split()[0])
    assert total == (M.PLANNED_N + M.N_UPDATE_ONLY + M.N_GRANTED + M.N_RESTORED + 2
                     + 4 * M.N_PROBE)
    assert "mcp:tools/call x" in out
