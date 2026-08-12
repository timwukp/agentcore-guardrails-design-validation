#!/usr/bin/env python3
"""F5-1's interlock must be able to refuse, and a missing target must not read as a boundary.

F5-1 is the one case in this project where a *mistake* and a *perfect security result* look
identical on the wire. `grx-runtime-exec` holds no lambda permission at all, so
`AccessDeniedException` comes back whether or not the function it names exists. Every
mis-assembled function name, every wrong region, every deleted target produces 120 clean
denials — and ZERO_EVENTS would read them as TRUE at a 4.98% ceiling.

So the properties tested here are the ones under which the script would publish a confident
falsehood in either direction:

* the startup interlock passing while a crashed run's grant is still attached — which makes the
  closed arm succeed 120 times and publishes "route #1 is OPEN" about an intact boundary;
* `ResourceNotFoundException` counted as a denial, which is how an unreachable target becomes a
  security property;
* `granted_arm_proved_the_target_real` satisfied by an execution that returned something other
  than our text from the echo tool;
* an invocation the service ran but the handler errored on, dropped from `adverse` — a bypass
  retired by a handler-level detail;
* the span positive control counted inside the window it is supposed to validate;
* an unparseable Insights timestamp dropped instead of counted, which loosens an absence claim.

None of these raise. Nothing in this file makes an AWS call: `capture` is replaced wholesale,
which is also what keeps a synthetic client out of the published evidence tree.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

_spec = importlib.util.spec_from_file_location(
    "grx_f5_01_route1_direct_invoke", ROOT / "f5_redteam" / "01_route1_direct_invoke.py")
M = importlib.util.module_from_spec(_spec)
sys.modules["grx_f5_01_route1_direct_invoke"] = M
_spec.loader.exec_module(M)

import oracle as O    # noqa: E402

FN = "grx-echo-r20260810T130945Z"
FN_ARN = f"arn:aws:lambda:us-east-1:111122223333:function:{FN}"
ACTION = "grxecho___echo"
ROLE = "grx-runtime-exec-r20260810T130945Z"


# ---- a stand-in for evidence.capture ---------------------------------------

class _Rec:
    """The three fields `_attempt` and `_assert_role_is_pristine` read off a Record."""

    def __init__(self, ok=True, response=None, error_code=""):
        self.ok, self.response, self.error_code = ok, response or {}, error_code


class _Cap:
    """Scripted `capture` replacement. Records the call order, which two tests assert on."""

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


def _ok_invoke(text=None, *, tool="echo", status=200, function_error=""):
    body = {"tool": tool, "mode": "echo", "context": {}}
    if text is not None:
        body["text"] = text
    return _Rec(response={"StatusCode": status, "FunctionError": function_error,
                          # a str, not a stream: evidence._drain_streams already read it
                          "Payload": json.dumps(body)})


DENIED = _Rec(ok=False, error_code="AccessDeniedException")


# ---- the sealed oracle this design assumes ---------------------------------

def test_the_binding_is_zero_events_with_a_mandatory_mutation():
    """The whole two-arm design exists because the mutation is mandatory.

    If a re-seal made it optional, the granted arm would become decoration and the docstring's
    argument about an unreachable target would no longer be enforced anywhere.
    """
    b = O.BINDINGS["F5-1"]
    assert b.kind == "ZERO_EVENTS"
    assert b.cell == "confirmatory_e_cell"
    assert O.mutation_is_mandatory("F5-1") is True


def test_the_preregistered_n_is_read_from_the_oracle_and_not_typed():
    assert M.PLANNED_N == O.planned_n("F5-1") == 120
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    assert "PLANNED_N = O.planned_n(CASE)" in src, (
        "a literal 120 would be a second home for the pre-registered n; PREREGISTRATION.yaml "
        "is the one that counts")
    assert M.MAX_INVOKES == M.PLANNED_N + M.N_GRANTED + M.N_RESTORED + 1
    assert M.N_GRANTED > 0 and M.N_RESTORED > 0


# ---- the interlock ---------------------------------------------------------

def test_the_interlock_refuses_when_a_crashed_runs_grant_is_still_attached():
    """Mutation-checked in both directions (feedback_vacuous_test_check).

    This is the guard that stops F5-1 from refuting a security property with our own litter.
    """
    grant = f"grx-f51-grant-{'r20260810T130945Z'}"

    # Pristine.
    cap = _Cap([_Rec(response={"PolicyNames": [M.BASELINE_INLINE]})])
    M.capture = cap
    out = M._assert_role_is_pristine(None, None, role_name=ROLE, grant_name=grant)
    assert out["inline_policies_at_start"] == [M.BASELINE_INLINE]
    assert "live" in out["read_from"], "the baseline must be read from IAM, not from the ledger"

    # The grant is already there.
    M.capture = _Cap([_Rec(response={"PolicyNames": [M.BASELINE_INLINE, grant]})])
    with pytest.raises(M.ConfigError) as exc:
        M._assert_role_is_pristine(None, None, role_name=ROLE, grant_name=grant)
    msg = str(exc.value)
    assert grant in msg and "open" in msg, (
        "the refusal must name the leftover and say what publishing over it would claim")
    assert "delete-role-policy" in msg, "it must tell the operator how to clear it"

    # Someone else has changed the role.
    M.capture = _Cap([_Rec(response={"PolicyNames": [M.BASELINE_INLINE, "someone-elses"]})])
    with pytest.raises(M.ConfigError):
        M._assert_role_is_pristine(None, None, role_name=ROLE, grant_name=grant)

    # The baseline policy is missing entirely — also not the shipped configuration.
    M.capture = _Cap([_Rec(response={"PolicyNames": []})])
    with pytest.raises(M.ConfigError):
        M._assert_role_is_pristine(None, None, role_name=ROLE, grant_name=grant)

    # And a failed read is a refusal, not a pass: a guard that cannot run must not report clean
    # (feedback_guard_tool_exit_codes).
    M.capture = _Cap([_Rec(ok=False, error_code="AccessDenied")])
    with pytest.raises(M.ConfigError) as exc2:
        M._assert_role_is_pristine(None, None, role_name=ROLE, grant_name=grant)
    assert "never measured" in str(exc2.value)


def test_the_interlock_runs_before_the_grant_and_the_ledger_entry_precedes_the_create():
    """Two orderings that only exist correctly in the source (feedback_no_deploy_path_no_component).

    1. The interlock must precede `put_role_policy`, or the litter check happens after the
       litter is added to.
    2. `state.record(...)` must precede `put_role_policy`, so a SIGKILL between them leaves a
       sweepable ledger entry rather than a silent permanent grant on the role.
    """
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    body = src.split("def main(", 1)[1]
    i_lock = body.index("_assert_role_is_pristine(")
    i_record = body.index("state.record(")
    i_put = body.index('"put_role_policy"')
    assert i_lock < i_put, "the role is mutated before its baseline is checked"
    assert i_record < i_put, (
        "the grant is created before it is recorded; a SIGKILL in that gap leaves an "
        "unattended lambda:InvokeFunction grant with nothing to sweep it")


def test_the_ledger_entry_is_deletable_by_teardown_without_this_script():
    """`infra/99_teardown.py` dispatches `getattr(client(service), delete_op)(**params)`.

    A watchdog that teardown cannot execute is not a watchdog, so the four fields it needs are
    asserted against the source rather than trusted.
    """
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    blk = src.split("state.record(T.Resource(", 1)[1].split("state.write()", 1)[0]
    assert 'service="iam"' in blk
    assert 'delete_op="delete_role_policy"' in blk
    assert '"RoleName": role_name' in blk and '"PolicyName": grant_name' in blk


# ---- classifying one attempt ----------------------------------------------

def test_a_missing_target_is_unusable_and_never_a_denial():
    """The failure mode that would turn an unreachable target into a security property.

    `ResourceNotFoundException` and `AccessDeniedException` are both "the invoke did not
    happen", and only one is evidence about authorization.
    """
    M.capture = _Cap([_Rec(ok=False, error_code="ResourceNotFoundException")])
    r = M._attempt(None, None, function_name=FN, action_id=ACTION, marker="m", trial_id="t")
    assert r["outcome"] == "unusable"

    for code in ("TooManyRequestsException", "ExpiredTokenException", "ValidationException",
                 "ServiceException", ""):
        M.capture = _Cap([_Rec(ok=False, error_code=code)])
        assert M._attempt(None, None, function_name=FN, action_id=ACTION,
                          marker="m", trial_id="t")["outcome"] == "unusable", code

    for code in M.DENIED_CODES:
        M.capture = _Cap([_Rec(ok=False, error_code=code)])
        assert M._attempt(None, None, function_name=FN, action_id=ACTION,
                          marker="m", trial_id="t")["outcome"] == "denied_by_iam", code


def test_an_invocation_the_handler_errored_on_is_still_a_bypass():
    """adverse is about crossing the authorization boundary, not about the handler's opinion.

    If the ClientContext convention ever changes and the handler answers `unknown_tool`, the
    boundary was still crossed — and that is what §4 claims cannot happen.
    """
    M.capture = _Cap([_ok_invoke(text=None, tool="", function_error="Unhandled")])
    r = M._attempt(None, None, function_name=FN, action_id=ACTION, marker="m", trial_id="t")
    assert r["outcome"] == "executed", "a function error retired an authorization bypass"
    assert r["function_error"] == "Unhandled"
    assert r["echoed_our_marker"] is False, (
        "but it must NOT count as proof the target is reachable as the echo tool")


def test_only_our_own_text_from_the_echo_tool_proves_the_target_real():
    """`echoed_our_marker` is the hinge of the whole case; it must be strict on both fields."""
    M.capture = _Cap([_ok_invoke(text="MARK")])
    assert M._attempt(None, None, function_name=FN, action_id=ACTION,
                      marker="MARK", trial_id="t")["echoed_our_marker"] is True

    M.capture = _Cap([_ok_invoke(text="SOMEONE-ELSES")])
    assert M._attempt(None, None, function_name=FN, action_id=ACTION,
                      marker="MARK", trial_id="t")["echoed_our_marker"] is False, (
        "an execution returning text we did not send does not prove OUR request reached the "
        "tool")

    M.capture = _Cap([_ok_invoke(text="MARK", tool="delay")])
    assert M._attempt(None, None, function_name=FN, action_id=ACTION,
                      marker="MARK", trial_id="t")["echoed_our_marker"] is False, (
        "a different tool answered; the action id under test was not the one exercised")

    # An empty marker must not match an absent field by accident.
    M.capture = _Cap([_ok_invoke(text=None)])
    assert M._attempt(None, None, function_name=FN, action_id=ACTION,
                      marker="", trial_id="t")["echoed_our_marker"] is False


def test_a_non_200_status_is_unusable_rather_than_executed():
    M.capture = _Cap([_ok_invoke(text="MARK", status=202)])
    assert M._attempt(None, None, function_name=FN, action_id=ACTION,
                      marker="MARK", trial_id="t")["outcome"] == "unusable"


def test_an_undecodable_payload_is_recorded_and_does_not_crash():
    """`evidence._drain_streams` substitutes a length marker for non-utf8 bodies."""
    M.capture = _Cap([_Rec(response={"StatusCode": 200, "Payload": "<41 bytes, not utf-8>"})])
    r = M._attempt(None, None, function_name=FN, action_id=ACTION, marker="M", trial_id="t")
    assert r["outcome"] == "executed"
    assert "payload_parse_error" in r and r["echoed_our_marker"] is False


def test_the_payload_is_read_from_the_record_and_not_re_read_from_a_stream():
    """A second `.read()` returns "" -> parses to {} -> reads as "the tool returned nothing"."""
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    seg = src.split("def _attempt(", 1)[1].split("\ndef ", 1)[0]
    # Comment lines are stripped: the function explains this hazard in prose, and the first
    # version of this test matched its own explanation (feedback_grep_the_claim_not_the_phrasing).
    code = "\n".join(ln for ln in seg.splitlines() if not ln.strip().startswith("#"))
    assert ".read()" not in code, (
        "_attempt calls .read() on a payload evidence.capture has already drained")


def test_the_client_context_reproduces_the_gateways_own_dispatch_key():
    blob = json.loads(base64.b64decode(M._client_context(ACTION)).decode("utf-8"))
    assert blob == {"custom": {"bedrockAgentCoreToolName": ACTION}}
    assert M.CLIENT_CONTEXT_KEY == "bedrockAgentCoreToolName"

    # And it is what `_attempt` actually sends, not merely what the helper can build.
    cap = _Cap([_ok_invoke(text="M")])
    M.capture = cap
    M._attempt(None, None, function_name=FN, action_id=ACTION, marker="M", trial_id="t")
    op, params = cap.calls[0]
    assert op == "invoke"
    assert params["FunctionName"] == FN
    assert params["InvocationType"] == "RequestResponse"
    assert json.loads(base64.b64decode(params["ClientContext"]))["custom"][
        M.CLIENT_CONTEXT_KEY] == ACTION
    assert json.loads(params["Payload"]) == {"text": "M"}


# ---- the grant document ---------------------------------------------------

def test_the_grant_is_scoped_to_one_function_and_one_action():
    doc = M._grant_document(FN_ARN)
    st = doc["Statement"]
    assert len(st) == 1
    assert st[0]["Action"] == "lambda:InvokeFunction"
    assert st[0]["Resource"] == FN_ARN, (
        "a wildcard resource would grant invoke on every function in the account, answering "
        "questions the mutation was not asked")
    assert st[0]["Effect"] == "Allow"
    assert "*" not in json.dumps(doc)


# ---- tallies -------------------------------------------------------------

class _CP:
    def __init__(self, seed=None):
        self._r = dict(seed or {})

    def is_done(self, tid):
        return tid in self._r

    def results(self):
        return self._r

    def run_trial(self, tid, fn):
        self._r[tid] = fn()

    def save(self):
        pass


def test_n_usable_excludes_unusable_and_the_arms_do_not_leak():
    seed = {
        f"{M.ARM_CLOSED}__0001": {"arm": M.ARM_CLOSED, "outcome": "denied_by_iam"},
        f"{M.ARM_CLOSED}__0002": {"arm": M.ARM_CLOSED, "outcome": "unusable",
                                  "error_code": "ResourceNotFoundException"},
        f"{M.ARM_CLOSED}__0003": {"arm": M.ARM_CLOSED, "outcome": "executed"},
        f"{M.ARM_GRANTED}__0001": {"arm": M.ARM_GRANTED, "outcome": "executed",
                                   "echoed_our_marker": True},
    }
    t = M._run_arm(None, _CP(seed), None, arm=M.ARM_CLOSED, function_name=FN,
                   action_id=ACTION, n=0, run_id="r1")
    assert (t["n_attempted"], t["n_denied"], t["n_executed"], t["n_unusable"]) == (3, 1, 1, 1)
    assert t["n_usable"] == 2, "an unusable attempt was denominated as evidence"
    assert t["error_codes"] == ["ResourceNotFoundException"]
    assert t["n_echoed_marker"] == 0, "the granted arm's row leaked into the closed arm"

    g = M._run_arm(None, _CP(seed), None, arm=M.ARM_GRANTED, function_name=FN,
                   action_id=ACTION, n=0, run_id="r1")
    assert (g["n_attempted"], g["n_echoed_marker"]) == (1, 1)


def test_a_resumed_arm_does_not_re_send_a_completed_trial():
    seed = {f"{M.ARM_CLOSED}__0001": {"arm": M.ARM_CLOSED, "outcome": "denied_by_iam"}}
    cap = _Cap([DENIED])
    M.capture = cap
    M._run_arm(None, _CP(seed), None, arm=M.ARM_CLOSED, function_name=FN,
               action_id=ACTION, n=2, run_id="r1")
    assert len(cap.calls) == 1, "trial 1 was already done and was re-sent (and re-billed)"


def test_each_trial_carries_a_distinct_marker():
    """Markers are what join a response to its request; a shared one makes `echoed_our_marker`
    satisfiable by any earlier trial's output."""
    cp = _CP()
    M.capture = _Cap([lambda op, p: _ok_invoke(text=json.loads(p["Payload"])["text"])])
    M._run_arm(None, cp, None, arm=M.ARM_CLOSED, function_name=FN, action_id=ACTION,
               n=5, run_id="r20260810T130945Z")
    markers = [r["marker"] for r in cp.results().values()]
    assert len(set(markers)) == 5
    assert all(M.ARM_CLOSED in m for m in markers), "the arm must be legible in the marker"


# ---- span corroboration --------------------------------------------------

def test_an_unparseable_timestamp_is_counted_rather_than_dropped():
    """The conservative direction: extra counted rows can only make absence harder to claim."""
    assert M._parse_insights_ts("2026-08-12 01:02:03.456") is not None
    assert M._parse_insights_ts("2026-08-12 01:02:03") is not None
    assert M._parse_insights_ts("not-a-timestamp") is None

    rows = [[{"field": "@timestamp", "value": "not-a-timestamp"},
             {"field": "@message", "value": M.SPAN_NAME}]]
    M.query_spans = lambda *a, **k: rows
    out = M._count_authorize_spans(None, "arn:gw", since=1000.0, until=2000.0)
    assert out["in_window"] == 1 and out["timestamps_unparseable_and_counted"] == 1, (
        "an unparseable row was dropped, which loosens the absence claim")


def test_rows_outside_the_window_are_not_counted():
    def row(ts):
        return [{"field": "@timestamp", "value": ts}]
    M.query_spans = lambda *a, **k: [row("2026-08-12 00:00:00.000"),
                                     row("2026-08-12 12:00:00.000")]
    # 2026-08-12 00:00:00Z .. 01:00:00Z
    out = M._count_authorize_spans(None, "arn:gw", since=1786492800.0, until=1786496400.0)
    assert out["rows_returned"] == 2 and out["in_window"] == 1


def test_the_query_is_filtered_to_our_gateway_and_to_the_observed_span_name():
    """`aws/spans` is a shared group. An unfiltered read returns other systems' rows."""
    seen = {}

    def fake(logs, gateway_arn, **kw):
        seen.update({"arn": gateway_arn, **kw})
        return []
    M.query_spans = fake
    M._count_authorize_spans(None, "arn:aws:bedrock-agentcore:us-east-1:1:gateway/g",
                             since=0.0, until=1.0)
    assert seen["arn"].endswith("gateway/g")
    assert M.SPAN_NAME in seen["extra_filter"]
    assert M.SPAN_NAME == "AgentCore.Policy.AuthorizeAction", (
        "the span name must stay the one F7-2/F7-5 observed live, not a guess")


def test_a_dead_span_channel_reads_as_instrument_unavailable_not_as_a_bypass():
    """Absence proves nothing unless presence is observable in the same window."""
    M.query_spans = lambda *a, **k: []
    M.wait_for_span = lambda *a, **k: (False, 300.0, [])

    class _C:
        def call_tool(self, *a, **k):
            return type("D", (), {"ran": True, "denied": False, "http_status": 200})()

    out = M._span_corroboration(None, _C(), None, gateway_arn="arn:gw", action_id=ACTION,
                                granted_window=(0.0, 1.0), n_invokes_in_window=20,
                                run_id="r1")
    assert out["reading"] == "INSTRUMENT_UNAVAILABLE"
    assert "absence_is_bounded_not_proven" not in out, (
        "a bounded-absence claim was published for a channel that never demonstrated delivery")
    assert out["is_corroboration_only"] is True

    # With a live channel and an empty window, the reading is the absence — bounded, and with
    # the confound direction stated.
    M.wait_for_span = lambda *a, **k: (True, 42.0, [[{"field": "@message", "value": "x"}]])
    out2 = M._span_corroboration(None, _C(), None, gateway_arn="arn:gw", action_id=ACTION,
                                 granted_window=(0.0, 1.0), n_invokes_in_window=20,
                                run_id="r1")
    assert out2["reading"] == "NO_AUTHORIZE_SPAN_FOR_DIRECT_INVOKES"
    assert out2["absence_is_bounded_not_proven"]["bound_s"] == M.CONTROL_SPAN_TIMEOUT_S
    assert "cannot" in out2["confound_direction_is_conservative"], (
        "the recorded confound note must state the DIRECTION — that other traffic can only "
        "push this to SPANS_PRESENT_IN_WINDOW — not merely be named 'conservative'")


def test_a_window_with_no_invokes_in_it_is_not_read_as_an_absent_span():
    """The resume case, which is where a wall-clock window silently stops being a measurement.

    On a re-run after a crash the granted arm is served entirely from its checkpoint and sends
    NOTHING, so `granted_window` brackets a few milliseconds of idle time. Zero AuthorizeAction
    rows over that window is "no direct invoke happened here", not "the direct invokes produced
    no span" — and the second reading is corroboration for the document's non-bypassable claim.
    Sharing one reading between them would let a resume manufacture evidence.
    """
    M.query_spans = lambda *a, **k: []
    M.wait_for_span = lambda *a, **k: (True, 1.0, [["x"]])   # a LIVE channel: the strong case

    class _C:
        def call_tool(self, *a, **k):
            return type("D", (), {"ran": True, "denied": False, "http_status": 200})()

    out = M._span_corroboration(None, _C(), None, gateway_arn="arn:gw", action_id=ACTION,
                                granted_window=(0.0, 0.01), n_invokes_in_window=0, run_id="r1")
    assert out["reading"] == "NO_INVOKES_IN_WINDOW"
    assert out["n_invokes_in_window"] == 0
    assert "absence_is_bounded_not_proven" not in out, (
        "a bounded-absence claim was published over a window in which nothing was sent")
    assert "checkpoint" in out["why_reading"], (
        "the reading must say WHY the window is empty, or a reader cannot tell it from a "
        "genuine absence")

    # And the same channel state with invokes present still reaches the real reading, so the
    # branch above is a guard and not a blanket suppression.
    out2 = M._span_corroboration(None, _C(), None, gateway_arn="arn:gw", action_id=ACTION,
                                 granted_window=(0.0, 1.0), n_invokes_in_window=20, run_id="r1")
    assert out2["reading"] == "NO_AUTHORIZE_SPAN_FOR_DIRECT_INVOKES"


def test_the_span_window_invoke_count_is_measured_not_assumed():
    """`n_invokes_in_window` must come from the checkpoint delta, not from the planned n.

    Passing `n_granted` would report 20 on a resume that sent zero, which is the exact
    substitution the guard above exists to prevent (DEV-P4-11's class).
    """
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    body = src.split("def main(", 1)[1]
    assert "granted_done_before = cps[ARM_GRANTED].n_done" in body
    assert "granted_sent_here = cps[ARM_GRANTED].n_done - granted_done_before" in body
    assert "n_invokes_in_window=granted_sent_here" in body, (
        "the span window's invoke count is not the measured delta")
    assert body.index("granted_done_before =") < body.index("granted_t0 = time.time()"), (
        "the before-count must be taken before the window opens")


def test_the_control_call_happens_after_the_window_is_counted():
    """Otherwise the control's own span lands in the window it exists to validate."""
    order: list[str] = []

    def fake_query(*a, **k):
        order.append("count")
        return []

    class _C:
        def call_tool(self, *a, **k):
            order.append("control")
            return type("D", (), {"ran": True, "denied": False, "http_status": 200})()

    M.query_spans = fake_query
    M.wait_for_span = lambda *a, **k: (True, 1.0, [["x"]])
    M._span_corroboration(None, _C(), None, gateway_arn="arn:gw", action_id=ACTION,
                          granted_window=(0.0, 1.0), n_invokes_in_window=20,
                                run_id="r1")
    assert order[0] == "count" and "control" in order, order


def test_a_control_call_that_raises_does_not_abort_the_case():
    """The span half is corroboration; a transport error in it must not lose the 120 trials."""
    M.query_spans = lambda *a, **k: []
    M.wait_for_span = lambda *a, **k: (False, 1.0, [])

    class _Boom:
        def call_tool(self, *a, **k):
            raise RuntimeError("transport")

    out = M._span_corroboration(None, _Boom(), None, gateway_arn="arn:gw", action_id=ACTION,
                                granted_window=(0.0, 1.0), n_invokes_in_window=20,
                                run_id="r1")
    assert out["control_call"]["ran"] is False and "transport" in out["control_call"]["error"]
    assert out["reading"] == "INSTRUMENT_UNAVAILABLE"


# ---- propagation ---------------------------------------------------------

def test_propagation_is_polled_in_both_directions_and_reports_a_timeout_as_data(monkeypatch):
    # Both the sleep AND the bound are shortened. Stubbing only `sleep` leaves `time.monotonic`
    # real, so the timeout branch busy-waits the full PROP_MAX_S — the first version of this
    # file hung pytest for 300 seconds proving nothing.
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)
    monkeypatch.setattr(M, "PROP_MAX_S", 0.2)
    monkeypatch.setattr(M, "PROP_EVERY_S", 0.0)

    M.capture = _Cap([DENIED, DENIED, _ok_invoke(text="x")])
    got = M._wait_for_effect(None, None, function_name=FN, action_id=ACTION, want="executed",
                             run_id="r1", phase="grant")
    assert got["reached"] is True and got["outcomes_seen"][-1] == "executed"

    M.capture = _Cap([DENIED])
    never = M._wait_for_effect(None, None, function_name=FN, action_id=ACTION, want="executed",
                               run_id="r1", phase="grant")
    assert never["reached"] is False
    assert "unknown configuration" in never["why_it_matters"], (
        "a timed-out propagation wait must say what it invalidates, not just fail quietly")


def test_the_shipped_propagation_bounds_allow_more_than_one_poll():
    """Asserted outside the test above, which patches these to run fast — an assertion on a
    patched constant is true by construction (feedback_vacuous_test_check)."""
    assert 0 < M.PROP_EVERY_S < M.PROP_MAX_S
    assert M.PROP_MAX_S >= 60, "IAM propagation has been seen to take tens of seconds"
    assert M.PROP_CONFIRM_N >= 2, (
        "one confirming probe is not convergence: the first live run ended the revoke wait on a "
        "single denial and then 9 of 20 post-restore invocations executed")
    assert M.PROP_CONFIRM_N * M.PROP_EVERY_S < M.PROP_MAX_S, (
        "the confirmation streak cannot fit inside the bound, so the wait can never succeed")


def test_the_revoke_direction_gets_a_strictly_longer_bound_than_the_grant():
    """Measured, not cautious.

    Three runs bounded the revoke at 300s: 31.2s under the one-probe rule (a flap — 9 of the next
    20 invocations executed), 248.5s to three consecutive denials, and NOT REACHED inside 300s on
    the third. An independent 12-probe check minutes after that third run returned 12/12 denied,
    so the state does converge and 300s was simply the wrong ruler for this direction.

    A grant that has not propagated costs the run an arm. A revoke that has not propagated is a
    hole in the boundary the testbed is supposed to have restored, so its wait is a safety check
    and is not cost-bound by the confirmatory n.
    """
    assert M.PROP_MAX_REVOKE_S > M.PROP_MAX_S, (
        "the revoke wait must not inherit the grant's bound: the grant direction converged in "
        "32.1s while the revoke direction was still unconverged at 300s")
    assert M.PROP_MAX_REVOKE_S >= 900, (
        "measured: three consecutive denials were not reached within 300s, so a bound in the "
        "same order of magnitude just reproduces the timeout")
    assert M.PROP_CONFIRM_N * M.PROP_EVERY_S < M.PROP_MAX_REVOKE_S


def test_the_revoke_wait_is_actually_called_with_the_longer_bound():
    """The constant existing is not the constant being used. Read from the source, because the
    call sits in a `finally` block reached only after two live IAM mutations."""
    body = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    src = body.split('want="denied_by_iam", run_id=run_id, phase="revoke"', 1)
    assert len(src) == 2, "the revoke propagation call site moved; this test is now blind"
    assert "max_s=PROP_MAX_REVOKE_S" in src[1][:200], (
        "the revoke wait is still using the default bound, so the longer constant is decoration")


def test_the_bound_that_produced_a_number_is_published_with_it(monkeypatch):
    """A propagation time is only readable next to how long the wait was allowed to run: 'not
    reached' means nothing without the ceiling it did not reach."""
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)
    M.capture = _Cap([DENIED, DENIED, DENIED])
    reached = M._wait_for_effect(None, None, function_name=FN, action_id=ACTION,
                                want="denied_by_iam", run_id="r1", phase="revoke",
                                max_s=M.PROP_MAX_REVOKE_S)
    assert reached["reached"] is True and reached["max_wait_s"] == M.PROP_MAX_REVOKE_S

    M.capture = _Cap([_ok_invoke(text="x")])
    timed_out = M._wait_for_effect(None, None, function_name=FN, action_id=ACTION,
                                   want="denied_by_iam", run_id="r1", phase="revoke", max_s=0.05)
    assert timed_out["reached"] is False and timed_out["max_wait_s"] == 0.05
    assert "0.05" in timed_out["why_it_matters"], (
        "the invalidation note must name the bound it timed out against")


def test_the_shortened_bound_in_the_fast_tests_is_not_frozen_by_a_default_argument(monkeypatch):
    """`max_s: float = PROP_MAX_S` would bind 300s once at def time, so the two tests that patch
    PROP_MAX_S to keep pytest fast would poll for five real minutes and pass regardless."""
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)
    monkeypatch.setattr(M, "PROP_MAX_S", 0.05)
    M.capture = _Cap([_ok_invoke(text="x")])
    t0 = time.monotonic()
    out = M._wait_for_effect(None, None, function_name=FN, action_id=ACTION,
                             want="denied_by_iam", run_id="r1", phase="grant")
    assert out["reached"] is False and out["max_wait_s"] == 0.05
    assert time.monotonic() - t0 < 5, "the patched bound was ignored — the default is early-bound"


def test_a_single_confirming_probe_does_not_end_the_propagation_wait(monkeypatch):
    """The measured defect, reproduced from the real probe sequence.

    The first live revoke wait saw `executed x5 -> denied_by_iam` and stopped there, reporting
    "denial re-asserted after 31.2s". The next 20 invocations included 9 that executed. So the
    single denial was a flap in a fleet that had not converged, and the arm whose purpose is to
    show the boundary came back instead recorded the boundary being crossed.
    """
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)

    # Exactly the observed sequence, then a lasting denial. Under the old one-probe rule the wait
    # would return at index 5; under the streak rule it must keep going.
    seq = ["executed"] * 5 + ["denied_by_iam"] + ["executed"] * 2 + ["denied_by_iam"] * 8
    calls = {"i": 0}

    def _scripted(*_a, **_k):
        i = calls["i"]
        calls["i"] += 1
        return DENIED if seq[min(i, len(seq) - 1)] == "denied_by_iam" else _ok_invoke(text="x")

    M.capture = _scripted
    out = M._wait_for_effect(None, None, function_name=FN, action_id=ACTION,
                             want="denied_by_iam", run_id="r1", phase="revoke")
    assert out["reached"] is True
    assert out["consecutive_confirmations"] >= M.PROP_CONFIRM_N
    assert calls["i"] > 6, (
        f"the wait ended after {calls['i']} probes; the 6th probe was the lone flapping denial "
        f"that the old rule accepted as convergence")
    # The flap is not merely survived, it is REPORTED: a run whose revoke flapped is a different
    # object from one that converged immediately, and §4's "remove the permission" remedy is
    # about exactly that difference.
    assert out["flapped_before_converging"] is True
    assert out["n_wanted_outcomes_before_the_final_streak"] == 1
    assert out["held_for_s"] >= 0

    # A clean, non-flapping convergence must report so — otherwise the field is a constant.
    calls["i"] = 0
    seq[:] = ["denied_by_iam"] * 12
    out2 = M._wait_for_effect(None, None, function_name=FN, action_id=ACTION,
                              want="denied_by_iam", run_id="r1", phase="revoke")
    assert out2["reached"] is True and out2["flapped_before_converging"] is False
    assert out2["n_wanted_outcomes_before_the_final_streak"] == 0


def test_an_alternating_sequence_never_reports_convergence(monkeypatch):
    """Consecutive, not cumulative. An alternating fleet IS the unconverged state, so a
    cumulative counter would end the wait on the very evidence that should extend it."""
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)
    monkeypatch.setattr(M, "PROP_MAX_S", 0.5)
    monkeypatch.setattr(M, "PROP_EVERY_S", 0.01)
    calls = {"i": 0}

    def _alternating(*_a, **_k):
        calls["i"] += 1
        return DENIED if calls["i"] % 2 == 0 else _ok_invoke(text="x")

    M.capture = _alternating
    out = M._wait_for_effect(None, None, function_name=FN, action_id=ACTION,
                             want="denied_by_iam", run_id="r1", phase="revoke")
    assert out["reached"] is False
    assert out["outcomes_seen"].count("denied_by_iam") >= M.PROP_CONFIRM_N, (
        "the sequence must contain enough denials that a CUMULATIVE counter would have "
        "reported convergence — otherwise this test does not distinguish the two rules")
    assert "unknown configuration" in out["why_it_matters"]


def test_the_propagation_probes_are_not_counted_in_any_arm(monkeypatch):
    """They share the target and the call shape with real trials; only the marker separates
    them, so a probe row landing in a tally would inflate `adverse` or `n_denied`."""
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)
    cp = _CP()
    M.capture = _Cap([_ok_invoke(text="x")])
    M._wait_for_effect(None, None, function_name=FN, action_id=ACTION, want="executed",
                       run_id="r1", phase="grant")
    assert cp.results() == {}, "a propagation probe was written into a checkpoint"
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    seg = src.split("def _wait_for_effect(", 1)[1].split("\ndef ", 1)[0]
    assert "run_trial" not in seg and "probe__" in seg


# ---- guards --------------------------------------------------------------

def test_guard_names_match_what_main_computes():
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    body = src.split("    guards = {", 1)[1]
    for g in M.GUARDS:
        assert f'"{g}"' in body, f"{g} is declared in GUARDS but never computed"
    assert len(set(M.GUARDS)) == len(M.GUARDS)
    assert "granted_arm_proved_the_target_real" in M.GUARDS
    assert "usable_trials_met_the_preregistered_n" in M.GUARDS


def test_the_restore_guard_reads_the_role_back_and_does_not_trust_delete_ok():
    """`delete_ok` says the call returned, not that the role is clean.

    A `DeleteRolePolicy` that returns 200 for a policy name that was never the one created, or a
    sweep in `finally` that silently failed, both leave `delete_ok` true. The control-plane guard
    is only definitive if it compares the role's inline policy set, read back from IAM, to the
    shipped baseline — and a FAILED read must not read as a clean role.
    """
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    dct = src.split("    guards = {", 1)[1].split("\n    }", 1)[0]
    blk = dct.split('"grant_was_removed_from_the_role":', 1)[1]
    assert "inline_policies_at_end" in blk and "BASELINE_INLINE" in blk, (
        "the restore guard does not compare the role's end state to the shipped baseline")

    body = src.split("def main(", 1)[1]
    # A failed ListRolePolicies must record None, which can never equal [BASELINE_INLINE].
    assert 'mutation_log["inline_policies_at_end"] = (' in body
    assert "if end.ok else None" in body, (
        "a failed end-state read must not be recorded as an empty or clean policy list "
        "(feedback_guard_tool_exit_codes)")


def test_the_strict_post_restore_form_is_still_computed_and_published():
    """It was removed from the GUARDS gate, so it must survive as a measurement.

    The split is defensible only because nothing is hidden by it: the strict condition ("every
    post-restore invocation was denied") is the one IAM does not offer on this timescale, and its
    actual value — 4 of 20 still executing after three consecutive denials — is the finding. If a
    later edit dropped the field, the split would become a quiet weakening of a guard.
    """
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    blk = src.split("data_plane_reconvergence = {", 1)[1].split("\n    }", 1)[0]
    for k in ("strict_form_all_post_restore_invocations_denied", "n_post_restore_invocations",
              "n_that_still_executed", "seconds_to_three_consecutive_denials",
              "revoke_probe_outcomes", "why_this_is_reported_and_not_required",
              "what_is_still_required", "amendment_candidate"):
        assert f'"{k}"' in blk, f"{k} missing from the published reconvergence measurement"
    assert 'n_res_exec == 0' in blk or "n_that_still_executed" in blk
    assert src.count('"data_plane_reconvergence": data_plane_reconvergence') == \
        src.count('"guards": guards,'), (
        "a payload publishes the guards without the measurement that replaced half of one")


def test_the_split_did_not_drop_a_guard_without_replacing_it():
    """Both halves of the retired guard must still be present, one as a gate and one as data."""
    assert "grant_was_removed_and_denial_reasserted" not in M.GUARDS
    assert "grant_was_removed_from_the_role" in M.GUARDS
    assert "denial_was_reasserted_in_the_data_plane" in M.GUARDS
    # The data-plane gate still requires the deny to be OBSERVED again — the split loosened
    # "every invocation was denied", not "the deny came back at all".
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    dct = src.split("    guards = {", 1)[1].split("\n    }", 1)[0]
    blk = dct.split('"denial_was_reasserted_in_the_data_plane":', 1)[1]
    assert 'prop_revoke.get("reached")' in blk and 'restored.get("n_denied"' in blk


def test_the_real_target_guard_reads_the_marker_and_not_merely_an_execution():
    """Written as a source assertion because the guard lives inline in `main`.

    An execution count would be satisfied by an `unknown_tool` error, which is a bypass but is
    NOT proof that the closed arm's denials were about a reachable echo tool.
    """
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    blk = src.split('"granted_arm_proved_the_target_real":', 1)[1].split(",\n", 1)[0]
    assert "n_echoed_marker" in blk
    assert "n_executed" not in blk


def test_the_two_verification_arms_are_not_added_to_the_confirmatory_denominator():
    """`adverse` and `n` must come from the closed arm alone (feedback_two_numbers_two_claims)."""
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    blk = src.split("obs = P.obs_zero_events(", 1)[1].split("    )", 1)[0]
    assert "adverse=closed[" in blk and "n=closed[" in blk
    assert "granted[" not in blk.split("mutation_inverted", 1)[0], (
        "the granted arm's count entered the confirmatory denominator")


def test_the_n_floor_cannot_suppress_a_demonstrated_bypass():
    """The one direction of error this family exists to catch.

    `usable_trials_met_the_preregistered_n` is a floor on how tightly a CLOSED boundary may be
    bounded: one denial licenses no bound, so 120 are required before publishing "route #1 is
    shut". It is NOT a floor on demonstrating the route is OPEN. A single closed-arm invocation
    that Lambda accepted and ran IS the bypass §4 claims cannot happen, and it does not become
    unproven because the other 119 attempts returned ResourceNotFound or ExpiredToken.

    Without the `or`, a run with n_usable=1 and that one trial EXECUTED would publish
    NOT_MEASURED — "we could not measure this" — over a live bypass sitting in the arm tally.
    A source assertion because the guard is computed inline in `main`.
    """
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    # Bound to the guards dict FIRST. Splitting straight on the key and trusting a `,\n    }`
    # terminator read past the closing brace into `guards_detail_n` below, which mentions
    # `n_executed` for its own reasons — so the assertion below passed with the escape deleted.
    dct = src.split("    guards = {", 1)[1].split("\n    }", 1)[0]
    blk = dct.split('"usable_trials_met_the_preregistered_n":', 1)[1]
    assert "n_executed" in blk, (
        "the n floor gates on n_usable alone, so a demonstrated bypass with n_usable < 120 "
        "would be published as NOT_MEASURED instead of FALSE")
    assert " or " in blk, "the bypass escape must widen the gate, not replace the n floor"
    assert "n_usable" in blk, "the n floor itself was removed"


def test_the_reason_the_n_gate_passed_is_published():
    """A gate that can pass two different ways must say which one it took.

    Otherwise a reader of a FALSE verdict cannot tell n=120-with-a-bypass from
    n=1-with-a-bypass, and those support very different sentences about rate.
    """
    src = (ROOT / "f5_redteam" / "01_route1_direct_invoke.py").read_text(encoding="utf-8")
    blk = src.split("guards_detail_n = {", 1)[1].split("\n    }", 1)[0]
    for k in ("n_usable", "n_required", "n_executed_in_closed_arm", "gate_satisfied_by"):
        assert f'"{k}"' in blk, f"{k} missing from the n-gate detail"
    # Every emit must carry it, including the two NOT_MEASURED exits.
    assert src.count('"guards_detail_n": guards_detail_n') == src.count('"guards": guards,'), (
        "a payload publishes the guards without the detail that explains the n gate")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
