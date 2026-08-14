#!/usr/bin/env python3
"""F5-4b has no "pass", and its restore must be able to FAIL.

The sealed kind is RECORDED: fail-closed and fail-open are both findings and neither is a
prediction this project made. Two consequences shape every arm below.

THE FAIL-OPEN BRANCH HAS NO LIVE REPRESENTATIVE WE CAN COUNT ON
If the service turns out to be fail-closed, the fail-open path never executes on this account —
and a branch first executed on the day it fires is a branch nobody has read. It is also the branch
with security consequences: it is the one that says an IAM permission an operator can remove in
one call silently disables enforcement. So it is tested here explicitly and in the same detail as
the other, together with the ORDER of the decision rule, because "the controls never bracketed the
measurement" and "the engine allowed a violating request" are both ALLOW at the gateway and only
the order keeps them apart. Getting that order wrong publishes a fail-open produced by a probe
that never tested anything — DEV-P1-18's exact shape, where a filter that never ran was published
as a filter that found nothing.

THE RESTORE PROTECTS THE WHOLE TESTBED
This case removes a statement from the ONE inline policy that IS the gateway execution role's
entire permission set, and that document also carries `lambda:InvokeFunction` on the echo Lambda.
A restore that returns 200 without putting the document back leaves every guardrail-in-policy case
in the repo broken, and the symptom at the gateway — a tool error — is one a careless reading would
file as a fail-open. So the LYING DOUBLE is here: a `PutRolePolicy` that succeeds while
`GetRolePolicy` hands back something else. A double that always restores correctly never reaches
that branch, which is the branch the testbed depends on.

The properties tested are the ones under which the script would publish a confident falsehood, or
leave the account broken:

* the finding decided from the decision before the controls, so a probe that tested nothing reads
  as fail-open;
* a violating DENY beside a benign ALLOW read as fail-closed — the engine was still
  discriminating by content, so evaluation still RAN and nothing was measured;
* the two post-removal violating legs disagreeing, averaged instead of reported — which is what a
  content cache looks like;
* a transport error counted as an ALLOW or a DENY;
* the reduced document dropping the wrong statement, or emptying the document;
* the restore compared with a normalisation that would also hide a reordered document;
* a restore verified from the `PutRolePolicy` status code rather than a fresh read;
* an IAM propagation wait satisfied by the stored document alone, while IAM's own evaluation still
  says allowed;
* a stabilisation loop that waits for a NAMED decision, which manufactures the answer by patience;
* `mutation_inverted` set False on a RECORDED case, which `oracle.evaluate` turns into a
  published FALSE — a refutation of a claim the seal does not make;
* the window bound unenforced, or wider than the docstring promises;
* residue reported clean because the window never opened — or reported dirty for the same reason;
* the SIGKILL fallback carrying an ARN, which `state.json`'s masking would corrupt.

Nothing here makes an AWS call and nothing opens an MCP session: `capture` and `client_for_leg`
are replaced wholesale and `M.time` is replaced with a fake clock, so the bounded poll loops run
their real iteration counts in no wall-clock time.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import inspect
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

SCRIPT = ROOT / "f5_redteam" / "08_route5_eval_permission_removed.py"
_spec = importlib.util.spec_from_file_location("grx_f5_08_route5_eval_permission_removed", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules["grx_f5_08_route5_eval_permission_removed"] = M
_spec.loader.exec_module(M)

import cedar as C        # noqa: E402
import evidence as E     # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
import testbed as T      # noqa: E402

SRC = SCRIPT.read_text(encoding="utf-8")
PY = str(ROOT / ".venv-oracle" / "bin" / "python")

RUN = "r20260810T130945Z"
ROLE = f"grx-gw-exec-{RUN}"
# The account-masked placeholder `lib/redact.py` writes into state.json, not a 12-digit literal:
# nothing here is sent to an API, and a real-shaped account would need a reviewed exception in
# `check_redaction.ALLOW` for a fixture.
ACCOUNT = "<account>"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
ECHO_ARN = f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:grx-echo-{RUN}"
GW_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:gateway/grx-gw-{RUN}"
ACTION = "grxecho___echo"


def _shipped_doc():
    """The document infra/01_iam.py writes on the gateway execution role, in its live shape.

    Three statements, one of them the target, and the third carrying TWO ARNs — which is the fact
    that makes the ledger fallback's shape a real design constraint rather than a preference.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "AgentCoreAsDocumented", "Effect": "Allow",
             "Action": "bedrock-agentcore:*", "Resource": "*"},
            {"Sid": "InvokeGuardrailChecks", "Effect": "Allow",
             "Action": "bedrock:InvokeGuardrailChecks", "Resource": "*"},
            {"Sid": "HarnessLambdaTargetNotFromTheDocument", "Effect": "Allow",
             "Action": "lambda:InvokeFunction", "Resource": [ECHO_ARN, f"{ECHO_ARN}:*"]},
        ],
    }


# ---- stand-ins -------------------------------------------------------------

def _rec(op="get_role_policy", *, ok=True, response=None, error_code="", error_message="",
         http_status=200):
    """A real `evidence.Record`, so a field renamed on Record breaks these arms."""
    return E.Record(case_id="F5-4b", operation=op, service="iam", region="us-east-1",
                    params={}, ok=ok, http_status=http_status if ok else 400,
                    request_id="rid-0001", response=response or {},
                    error_code=error_code, error_message=error_message,
                    path="evidence/x/0001_op_ok.json")


class _Cap:
    """Scripted `capture` replacement: a dict keyed by operation, or a list consumed in order.

    In list form the last entry repeats, so a bounded poll loop cannot exhaust the script and
    fail with a scripting error instead of exercising its timeout branch.
    """

    def __init__(self, script):
        self._list = list(script) if isinstance(script, list) else None
        self._byop = dict(script) if isinstance(script, dict) else None
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, store, operation, client, **params):
        self.calls.append((operation, params))
        if self._byop is not None:
            got = self._byop.get(operation, _rec(operation))
            return got(operation, params) if callable(got) else got
        if not self._list:
            return _rec(ok=False, error_code="TestScriptExhausted")
        nxt = self._list[0]
        if len(self._list) > 1:
            self._list.pop(0)
        return nxt(operation, params) if callable(nxt) else nxt

    @property
    def ops(self):
        return [op for op, _ in self.calls]

    def params_for(self, operation):
        return [p for op, p in self.calls if op == operation]


class _Clock:
    """A fake `time`, so a 90s poll bound costs no wall clock and runs its real loop count."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += max(float(s), 0.001)


class _Decision:
    """A `lib/mcp.Decision`-shaped double.

    `denied` and `ran` are the two properties the script reads, and they are mutually exclusive on
    the real class (`outcome` is one value). Modelled that way here so a script that treated a
    tool error as an ALLOW could not pass.
    """

    def __init__(self, outcome, http_status=200):
        self.outcome = outcome
        self.http_status = http_status
        self.unclassified = outcome not in ("allowed", "policy_denied")
        self.default_deny = False

    @property
    def denied(self):
        return self.outcome == "policy_denied"

    @property
    def ran(self):
        return self.outcome == "allowed"

    def to_json(self):
        return {"outcome": self.outcome, "http_status": self.http_status}


class _Client:
    """An MCP client double that records the arguments of every tool call."""

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[tuple[str, dict]] = []
        self.closed = 0

    def call_tool(self, name, arguments=None, **kw):
        self.calls.append((name, dict(arguments or {})))
        nxt = self._script[0]
        if len(self._script) > 1:
            self._script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def close(self):
        self.closed += 1


def _alternating(cycle):
    """A `client_for_leg` replacement whose sequence survives the fresh session per probe.

    `wait_for_stable_decision` opens a NEW client for every probe — deliberately, because a
    long-lived session is a cache with our name on it. A double rebuilt per client would restart
    at the first entry of its script and answer the same thing every time, so an alternating
    sequence could not be expressed at all and the arm would pass for the wrong reason
    (`feedback_unreachable_branch_in_fake`). The state therefore lives in the closure.
    """
    box = {"i": 0}

    def _factory(*a, **k):
        i = box["i"]
        box["i"] += 1
        return _Client([cycle[i % len(cycle)]])
    return _factory


class _StubPolicyClient:
    """A control-plane client stand-in with the ONE attribute `create_forbid` reads.

    The script passes `ac.get_policy` to `wait_status` as a bound method, so the attribute has to
    exist before `wait_status` is ever called — patching `wait_status` alone is not enough, and a
    bare `object()` fails with an AttributeError that says nothing about the case.
    """

    def get_policy(self, **kwargs):
        raise AssertionError("get_policy must never be invoked in a test")


class _State:
    """A ledger stand-in recording the ORDER of its calls."""

    run_id = RUN
    expires_at = "2026-08-13T13:09:45+00:00"

    def __init__(self, policies=("baseline",)):
        self._p = list(policies)
        self.order: list[str] = []
        self.recorded: list[T.Resource] = []

    def of_kind(self, kind):
        if kind == "policy":
            return [T.Resource(kind="policy", logical=lg, name=lg, service="s",
                               delete_op="delete_policy", delete_params={},
                               ids={"policy_id": f"pid-{lg}"}) for lg in self._p]
        return [r for r in self.recorded if r.kind == kind]

    def record(self, r):
        self.order.append(f"record:{r.logical}")
        self.recorded.append(r)

    def write(self):
        self.order.append("write")

    def drop(self, kind, logical):
        self.order.append(f"drop:{kind}/{logical}")


DENY = _Decision("policy_denied")
ALLOW = _Decision("allowed")
TOOL_ERROR = _Decision("tool_error", http_status=200)
HTTP_404 = _Decision("http_error", http_status=404)


@pytest.fixture(autouse=True)
def _sealed(monkeypatch):
    """No AWS, no MCP session, no real clock — for every test in the file."""
    monkeypatch.setattr(M, "capture", _Cap([]))
    monkeypatch.setattr(M, "time", _Clock())
    monkeypatch.setattr(M.A, "limiter",
                        lambda: type("L", (), {"wait": staticmethod(lambda *a, **k: None)})())
    yield


def _code_without_docstring() -> str:
    """The script's source minus its module docstring.

    The docstring discusses at length the things the script must not do, so a whole-file scan
    would report the explanation as the offence — the reason
    `lib/tests/test_account_id_choke_point.py` gives for not grepping for the call it forbids.
    """
    doc = ast.get_docstring(ast.parse(SRC)) or ""
    return SRC.replace(doc, "", 1) if doc else SRC


# ===========================================================================
# the sealed oracle: RECORDED means there is no pass
# ===========================================================================

def test_the_binding_is_recorded_with_a_mandatory_mutation():
    b = O.BINDINGS["F5-4b"]
    assert b.kind == "RECORDED"
    assert "fail-closed or fail-open" in (b.note or "")
    assert O.mutation_is_mandatory("F5-4b") is True, (
        "the mutation is mandatory, which is why `mutation_inverted` has to be set at all — and "
        "why setting it False on a RECORDED case is the hazard this file pins")
    assert O.planned_n("F5-4b") is None


def test_the_oracle_text_declares_the_outcome_unknown_and_names_the_permission():
    text = O.oracle_text("F5-4b")
    assert "OUTCOME UNKNOWN" in text
    assert M.TARGET_ACTION in text
    assert "fail-closed" in text and "fail-open" in text
    assert "does not document" in text


def test_a_recorded_case_evaluates_to_recorded_for_either_finding():
    """Both answers must survive `evaluate` identically. Neither is a verdict about the document."""
    for f in M.PUBLISHABLE_FINDINGS:
        o = P.obs_recorded("F5-4b", finding=f)
        o.mutation_inverted = True
        rec = O.evaluate(o)
        assert rec["verdict"] == O.RECORDED
        assert rec["mutation_required"] is True and rec["mutation_inverted"] is True
        assert O.amendment_blockers(rec)["clear_here"] is False, (
            "RECORDED supports no amendment, and the record should say so rather than reading as "
            "a finding that clears the bar")


def test_setting_mutation_inverted_false_on_a_recorded_case_would_publish_a_false():
    """The reason the script NEVER passes False, pinned against the real oracle.

    `evaluate` maps `mutation_inverted is False` to verdict FALSE. For a case whose seal declares
    the outcome unknown that is a refutation of a claim the seal does not make — so the branch
    where nothing changed is routed through `O.not_measured` instead, and this arm is what stops a
    later edit from "simplifying" that away.
    """
    o = P.obs_recorded("F5-4b")
    o.mutation_inverted = False
    assert O.evaluate(o)["verdict"] == O.FALSE, (
        "if this stops being true the script's argument for never passing False needs rewriting, "
        "not deleting")
    assert "mutation_inverted = False" not in SRC
    assert "obs.mutation_inverted = bool(" in SRC, (
        "the flag is computed from a difference between legs, and bool() of a comparison can "
        "never be None — which is what keeps the None branch (an unrecorded mutation) out of the "
        "published path")


def test_mutation_inverted_is_set_as_an_attribute_not_passed_as_a_keyword():
    assert "obs.mutation_inverted = " in SRC
    assert "mutation_inverted=" not in SRC, "the keyword spelling is the F5-1 bug"
    with pytest.raises(TypeError) as exc:
        P.obs_recorded("F5-4b", mutation_inverted=True)
    assert "not free-form detail" in str(exc.value)


def test_the_inversion_flag_is_symmetric_between_the_two_findings():
    """Fail-open inverts the violating leg; fail-closed inverts the benign leg.

    Read out of the source because the expression is what has to be symmetric: a flag computed
    from the violating leg alone would be True for fail-open and False for fail-closed, and
    `evaluate` would then publish FALSE for one of the two answers the seal calls a finding.
    """
    expr = SRC[SRC.index("obs.mutation_inverted = bool("):]
    expr = expr[:expr.index("# `evaluate` takes")]
    # The CONSTANT names, which is what the expression is written in: asserting on their values
    # would pass against an expression that had inlined a different leg's string.
    assert "LEG_POST_VIOLATING_SAME" in expr and "LEG_PRE_VIOLATING" in expr
    assert "LEG_POST_BENIGN" in expr and "LEG_PRE_BENIGN" in expr, (
        "without the benign comparison the fail-closed finding would report a mutation that did "
        "not invert, and evaluate() would turn it into a published FALSE")
    assert " or " in expr, "either leg changing is an inversion"


def test_no_branch_in_the_decision_or_the_narrative_is_phrased_as_an_expectation():
    """`RECORDED` is not a prediction, so the code that decides and reports must not read as one."""
    for fn in (M.finding, M.narrative):
        # The docstring is stripped first: both functions ARGUE against the word, and a scan of
        # the whole source would report the explanation as the offence — the reason
        # `lib/tests/test_account_id_choke_point.py` refuses to grep for the call it forbids.
        whole = inspect.getsource(fn)
        doc = inspect.getdoc(fn) or ""
        src = whole
        for line in doc.splitlines():
            src = src.replace(line.strip(), "", 1) if line.strip() else src
        src = src.lower()
        for word in ("expected", "as we expected", "unfortunately", "correctly denied",
                     "should deny", "should allow"):
            assert word not in src, (
                f"{fn.__name__} contains {word!r}; for a case whose seal declares the outcome "
                f"unknown, that is a prediction dressed as a comment")


# ===========================================================================
# the decision rule: the whole truth table, in order
# ===========================================================================

def _legs(**decisions):
    """Leg tallies carrying only what `finding` reads, plus a plausible reach count."""
    return {leg: {"leg": leg, "decision": d, "n_reached_gateway": 5, "n_usable": 5}
            for leg, d in decisions.items()}


CLEAN_CONTROLS = {M.LEG_PRE_VIOLATING: "DENY", M.LEG_PRE_BENIGN: "ALLOW"}


def test_fail_open_is_a_finding_and_says_what_it_means():
    """THE branch with security consequences, and the one with no live representative.

    Both post-removal violating legs ALLOW — the repeated item and the item never sent before, so
    a content cache cannot explain it.
    """
    f = M.finding(_legs(**CLEAN_CONTROLS,
                        post_violating_same="ALLOW", post_violating_new="ALLOW",
                        post_benign="ALLOW"))
    assert f["finding"] == M.FINDING_FAIL_OPEN
    assert f["publishable"] is True
    assert "never sent before" in f["why"], (
        "the reason has to name the cache-breaking leg, or a reader cannot tell this from a "
        "cached ALLOW")

    narr = M.narrative(found=f, window={"seconds_without_the_permission": 141.0}, sdk="1.43.32")
    text = narr["verdict_reading"]
    assert "FAIL-OPEN" in text
    assert "silently disables enforcement" in text
    assert "does not hold" in text, (
        "a fail-open refutes §4.1/§9's fail-secure label for this mode; the record must not read "
        "as a neutral observation")
    assert "undocumented" in text, "§3.3 BP#4's warning is the reason this case exists"


def test_fail_closed_is_a_finding_and_needs_the_benign_leg_to_be_denied_too():
    f = M.finding(_legs(**CLEAN_CONTROLS,
                        post_violating_same="DENY", post_violating_new="DENY",
                        post_benign="DENY"))
    assert f["finding"] == M.FINDING_FAIL_CLOSED
    assert f["publishable"] is True
    assert "stopped discriminating by content" in f["why"]

    narr = M.narrative(found=f, window={"seconds_without_the_permission": 92.0}, sdk="x")
    assert "FAIL-CLOSED" in narr["verdict_reading"]
    assert "corroborated" in narr["verdict_reading"]
    assert "not for the timeout mode" in narr["verdict_reading"], (
        "the timeout claim is the one §3.1 actually makes and it is NOT what this measures; a "
        "fail-closed reading that did not say so would be quoted as covering it")


def test_a_violating_deny_beside_a_benign_allow_is_not_fail_closed():
    """The mirror hazard, and the arm most likely to be got wrong.

    The engine denied the violating request and allowed the benign one, so it was still
    DISCRIMINATING BY CONTENT — which means guardrail evaluation still ran and the removal was not
    observable at the request path. It is also exactly what a content cache produces. Publishing
    it as fail-closed would credit the service with a property this run did not observe.
    """
    f = M.finding(_legs(**CLEAN_CONTROLS,
                        post_violating_same="DENY", post_violating_new="DENY",
                        post_benign="ALLOW"))
    assert f["finding"] == M.FINDING_NOT_OBSERVABLE
    assert f["publishable"] is False
    assert "still ran" in f["why"] or "still evaluating" in f["why"]
    assert "cache" in f["why"] and "Forward Access Session" in f["why"], (
        "the two alternative explanations belong in the record, not in a comment")


def test_the_controls_are_consulted_before_the_decision():
    """Order matters: a probe that tested nothing must not read as fail-open.

    The legs below look exactly like a fail-open — both violating legs ALLOW — and the controls
    say the instrument never worked. DEV-P1-18's shape is a filter that never ran published as a
    filter that found nothing; this is the same shape with a permission in place of a filter.
    """
    for controls in ({M.LEG_PRE_VIOLATING: "ALLOW", M.LEG_PRE_BENIGN: "ALLOW"},
                     {M.LEG_PRE_VIOLATING: "DENY", M.LEG_PRE_BENIGN: "DENY"},
                     {M.LEG_PRE_VIOLATING: "SPLIT", M.LEG_PRE_BENIGN: "ALLOW"},
                     {M.LEG_PRE_VIOLATING: "NOTHING_USABLE", M.LEG_PRE_BENIGN: "ALLOW"},
                     {}):
        f = M.finding(_legs(**controls, post_violating_same="ALLOW",
                            post_violating_new="ALLOW", post_benign="ALLOW"))
        assert f["finding"] == M.FINDING_NO_BRACKET, controls
        assert f["publishable"] is False
        assert "never tested anything" in f["why"]


def test_the_pre_benign_control_is_required_because_a_blanket_forbid_proves_nothing():
    """A forbid that denied everything would make the benign leg's post-removal DENY meaningless.

    So `pre_benign` must be ALLOW before the window opens, and that is a control on the POLICY,
    not on the permission.
    """
    f = M.finding(_legs(pre_violating="DENY", pre_benign="DENY",
                        post_violating_same="DENY", post_violating_new="DENY",
                        post_benign="DENY"))
    assert f["finding"] == M.FINDING_NO_BRACKET, (
        "with the permission intact a benign request that was DENIED means the forbid denies "
        "everything, and the fail-closed reading would be about our own policy")


@pytest.mark.parametrize("same,new", [("ALLOW", "DENY"), ("DENY", "ALLOW"),
                                      ("DENY", "SPLIT"), ("ALLOW", "NOTHING_USABLE")])
def test_disagreeing_violating_legs_are_reported_and_not_averaged(same, new):
    """They differ only in WHICH violating item they carry, so a disagreement is a cache or noise."""
    f = M.finding(_legs(**CLEAN_CONTROLS, post_violating_same=same,
                        post_violating_new=new, post_benign="ALLOW"))
    assert f["finding"] == M.FINDING_INCOHERENT
    assert f["publishable"] is False
    assert "content-keyed cache" in f["why"] or "not deterministic" in f["why"]


@pytest.mark.parametrize("same", ["SPLIT", "NOTHING_USABLE", None])
def test_a_split_or_empty_measurement_leg_is_never_a_finding(same):
    f = M.finding(_legs(**CLEAN_CONTROLS, post_violating_same=same,
                        post_violating_new=same, post_benign="ALLOW"))
    assert f["publishable"] is False
    assert f["finding"] in (M.FINDING_INCOHERENT, M.FINDING_NO_BRACKET)


def test_exactly_two_findings_are_publishable():
    assert set(M.PUBLISHABLE_FINDINGS) == {M.FINDING_FAIL_CLOSED, M.FINDING_FAIL_OPEN}
    assert len(M.FINDINGS) == 5 and set(M.PUBLISHABLE_FINDINGS) <= set(M.FINDINGS)
    # And every name the decision rule can return is declared, so a new branch cannot appear
    # without joining the enumeration the payload publishes.
    returned = {n.value for n in ast.walk(ast.parse(inspect.getsource(M.finding)))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for f in M.FINDINGS:
        assert f in SRC
    assert all(v in SRC for v in returned if v.startswith(("FAIL_", "REMOVAL_", "SPLIT_",
                                                           "CONTROLS_")))


def test_every_narrative_branch_carries_the_five_required_sentences():
    keys = ("verdict_rule", "verdict_reading", "what_true_does_not_prove",
            "why_this_matters_operationally", "expiry")
    for name in M.FINDINGS:
        found = {"finding": name, "publishable": name in M.PUBLISHABLE_FINDINGS,
                 "why": "because", "per_leg": {}}
        narr = M.narrative(found=found, window={"seconds_without_the_permission": 1.0}, sdk="x")
        assert set(narr) == set(keys), name
        for k, v in narr.items():
            assert isinstance(v, str) and len(v) > 40, f"{name}/{k} is not a sentence"


def test_the_limits_paragraph_names_the_timeout_mode_this_case_cannot_reach():
    """The claim §3.1 makes is about TIMEOUTS, which no fault-injection surface can induce.

    A result quoted as covering it would over-claim in whichever direction it fell, so the
    exclusion has to travel with the record.
    """
    found = {"finding": M.FINDING_FAIL_OPEN, "publishable": True, "why": "x", "per_leg": {}}
    narr = M.narrative(found=found, window={}, sdk="x")
    text = narr["what_true_does_not_prove"]
    for needle in ("TIMEOUT", "C-s3-1-bullet-014-a", "F5-4a", "ApplyGuardrail"):
        assert needle in text, f"the limits paragraph does not mention {needle!r}"


def test_the_operational_paragraph_gives_both_runbooks_and_the_measured_window():
    found = {"finding": M.FINDING_FAIL_CLOSED, "publishable": True, "why": "x", "per_leg": {}}
    narr = M.narrative(found=found, window={"seconds_without_the_permission": 123.4}, sdk="x")
    text = narr["why_this_matters_operationally"]
    assert "123.4" in text and str(M.WINDOW_BOUND_S) in text
    assert "availability alarm" in text and "config-drift alarm" in text, (
        "the two answers have opposite runbooks, which is the whole operational point")


# ===========================================================================
# the document capture and the surgery
# ===========================================================================

def _capture_script(*, doc=None, inline=(M.GW_EXEC_INLINE,), managed=(), get_ok=True,
                    doc_as_str=False):
    body = _shipped_doc() if doc is None else doc
    return {
        "list_role_policies": _rec("list_role_policies",
                                   response={"PolicyNames": list(inline)}),
        "list_attached_role_policies": _rec(
            "list_attached_role_policies",
            response={"AttachedPolicies": [{"PolicyArn": m} for m in managed]}),
        "get_role_policy": (
            _rec("get_role_policy",
                 response={"PolicyDocument": json.dumps(body) if doc_as_str else body})
            if get_ok else _rec("get_role_policy", ok=False, error_code="NoSuchEntity")),
    }


def test_the_shipped_document_is_captured_whole_with_a_hash(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_capture_script()))
    out = M.capture_document(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE)
    assert out["sids"] == list(M.EXPECTED_SIDS)
    assert out["n_statements"] == 3
    assert out["document"] == _shipped_doc()
    assert out["sha256"] == sha256(M.normalised(_shipped_doc()).encode()).hexdigest()
    assert out["target_statement"]["Sid"] == M.TARGET_SID


def test_the_expected_sids_match_the_provisioner():
    """`EXPECTED_SIDS` is a claim about infra/01_iam.py, so it is checked against it.

    A drifted copy would make `role_carried_exactly_its_shipped_document` pass over a role
    somebody else had edited.
    """
    iam_src = (ROOT / "infra" / "01_iam.py").read_text(encoding="utf-8")
    block = iam_src[iam_src.index('specs["gw-exec"]'):iam_src.index('specs["caller"]')]
    for sid in M.EXPECTED_SIDS:
        assert f'"Sid": "{sid}"' in block, f"{sid} is not in infra/01_iam.py's gw-exec policy"
    assert f'"{M.TARGET_ACTION}"' in block
    assert M.GW_EXEC_INLINE in block


@pytest.mark.parametrize("kwargs,needle", [
    ({"inline": (M.GW_EXEC_INLINE, "other")}, "not exactly"),
    ({"managed": (f"arn:aws:iam::{ACCOUNT}:policy/x",)}, "attached managed policies"),
    ({"get_ok": False}, "never captured"),
    ({"doc_as_str": True}, "as a str"),
])
def test_the_capture_refuses_every_state_it_cannot_account_for(monkeypatch, kwargs, needle):
    monkeypatch.setattr(M, "capture", _Cap(_capture_script(**kwargs)))
    with pytest.raises(M.ConfigError) as exc:
        M.capture_document(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE)
    assert needle in str(exc.value)


def test_a_document_already_missing_the_statement_refuses(monkeypatch):
    """Zero target Sids means an earlier run did not restore it. That is not a starting state."""
    doc = _shipped_doc()
    doc["Statement"] = [s for s in doc["Statement"] if s["Sid"] != M.TARGET_SID]
    monkeypatch.setattr(M, "capture", _Cap(_capture_script(doc=doc)))
    with pytest.raises(M.ConfigError) as exc:
        M.capture_document(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE)
    assert "already absent" in str(exc.value)


def test_a_duplicated_target_sid_refuses(monkeypatch):
    doc = _shipped_doc()
    doc["Statement"].append(copy.deepcopy(doc["Statement"][1]))
    monkeypatch.setattr(M, "capture", _Cap(_capture_script(doc=doc)))
    with pytest.raises(M.ConfigError) as exc:
        M.capture_document(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE)
    assert "removes exactly one" in str(exc.value)


def test_a_target_statement_granting_more_than_the_action_refuses(monkeypatch):
    """Removing it would withdraw permissions beyond the one under test.

    An observed change could then not be attributed to guardrail evaluation being impossible.
    """
    doc = _shipped_doc()
    doc["Statement"][1]["Action"] = [M.TARGET_ACTION, "bedrock:ApplyGuardrail"]
    monkeypatch.setattr(M, "capture", _Cap(_capture_script(doc=doc)))
    with pytest.raises(M.ConfigError) as exc:
        M.capture_document(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE)
    assert "more than" in str(exc.value)


def test_a_target_statement_not_granting_the_action_refuses(monkeypatch):
    doc = _shipped_doc()
    doc["Statement"][1]["Action"] = "bedrock:ApplyGuardrail"
    monkeypatch.setattr(M, "capture", _Cap(_capture_script(doc=doc)))
    with pytest.raises(M.ConfigError) as exc:
        M.capture_document(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE)
    assert "does not include" in str(exc.value)


def test_a_document_whose_statement_is_not_a_list_refuses(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_capture_script(
        doc={"Version": "2012-10-17", "Statement": {"Sid": M.TARGET_SID}})))
    with pytest.raises(M.ConfigError) as exc:
        M.capture_document(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE)
    assert "Statement LIST" in str(exc.value)


def test_the_reduction_removes_exactly_one_statement_and_keeps_the_lambda_grant():
    """The catastrophic case: dropping `lambda:InvokeFunction` breaks the echo target repo-wide.

    And the symptom at the gateway would be a tool error, which a careless reading would file as
    a fail-open.
    """
    doc = _shipped_doc()
    reduced = M.document_without_sid(doc, M.TARGET_SID)
    assert [s["Sid"] for s in reduced["Statement"]] == [
        "AgentCoreAsDocumented", "HarnessLambdaTargetNotFromTheDocument"]
    assert reduced["Version"] == doc["Version"], "the Version member must survive"
    lam = next(s for s in reduced["Statement"] if "lambda:InvokeFunction" in str(s["Action"]))
    assert lam["Resource"] == [ECHO_ARN, f"{ECHO_ARN}:*"], (
        "the echo Lambda grant must come through untouched, both ARNs")
    assert doc == _shipped_doc(), "the captured document must not be mutated by the reduction"


def test_the_reduction_refuses_when_it_would_remove_nothing_or_everything():
    with pytest.raises(M.ConfigError) as exc:
        M.document_without_sid(_shipped_doc(), "NoSuchSid")
    assert "not exactly 1" in str(exc.value)

    single = {"Version": "2012-10-17",
              "Statement": [{"Sid": M.TARGET_SID, "Effect": "Allow",
                             "Action": M.TARGET_ACTION, "Resource": "*"}]}
    with pytest.raises(M.ConfigError) as exc:
        M.document_without_sid(single, M.TARGET_SID)
    assert "no statements at all" in str(exc.value)


# ===========================================================================
# normalisation: what it is safe to ignore, and what it is not
# ===========================================================================

def test_normalisation_ignores_key_order_because_json_objects_have_none():
    a = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Sid": "X",
                                                 "Action": "a", "Resource": "*"}]}
    b = {"Statement": [{"Sid": "X", "Action": "a", "Resource": "*", "Effect": "Allow"}],
         "Version": "2012-10-17"}
    assert M.normalised(a) == M.normalised(b)


def test_normalisation_does_not_hide_a_reordered_statement_list():
    """The documented choice, pinned in the direction that makes it a choice.

    IAM evaluates statements order-insensitively, so a reordering is semantically harmless — and
    it is still evidence that the restore path did not return the object that was captured, which
    is exactly what this comparison verifies. `infra/01_iam.py._canon` sorts lists because its
    question ("does the live role match its spec") is a different one.
    """
    doc = _shipped_doc()
    swapped = copy.deepcopy(doc)
    swapped["Statement"] = list(reversed(swapped["Statement"]))
    assert M.normalised(doc) != M.normalised(swapped), (
        "a normalisation that sorted the statement list would make the restore check blind to a "
        "restore that reordered the document")
    # And the looser form in the provisioner IS insensitive to it, which is why the two exist.
    infra = importlib.util.module_from_spec(importlib.util.spec_from_file_location(
        "_grx_iam_for_f54b_tests", ROOT / "infra" / "01_iam.py"))
    infra.__spec__.loader.exec_module(infra)
    assert infra._canon(doc) == infra._canon(swapped), (
        "if the provisioner's canon stopped being order-insensitive, the reason given for having "
        "two normalisations no longer holds")


def test_normalisation_notices_a_missing_statement():
    doc = _shipped_doc()
    assert M.normalised(doc) != M.normalised(M.document_without_sid(doc, M.TARGET_SID))


# ===========================================================================
# THE LYING DOUBLE: a restore whose read-back differs from the capture
# ===========================================================================

def _captured():
    doc = _shipped_doc()
    return {"role_name": ROLE, "policy_name": M.GW_EXEC_INLINE, "document": doc,
            "normalised": M.normalised(doc),
            "sha256": sha256(M.normalised(doc).encode()).hexdigest(),
            "sids": list(M.EXPECTED_SIDS), "n_statements": 3,
            "target_statement": doc["Statement"][1]}


def _restore_script(read_back):
    """`PutRolePolicy` always succeeds; `GetRolePolicy` returns whatever the arm dictates."""
    seq = list(read_back)

    def _get(op, params):
        nxt = seq[0]
        if len(seq) > 1:
            seq.pop(0)
        if nxt is None:
            return _rec("get_role_policy", ok=False, error_code="ServiceFailure")
        return _rec("get_role_policy", response={"PolicyDocument": nxt})
    return {"put_role_policy": _rec("put_role_policy"), "get_role_policy": _get}


def test_an_honest_restore_is_verified_by_a_fresh_read(monkeypatch):
    cap = _Cap(_restore_script([_shipped_doc()]))
    monkeypatch.setattr(M, "capture", cap)
    out = M.restore_document(None, None, captured=_captured())
    assert out["restored"] is True
    assert out["sha256_read_back"] == out["sha256_expected"]
    assert cap.ops == ["put_role_policy", "get_role_policy"], (
        "the verification must be a fresh GetRolePolicy, not the put's own status code")
    assert "list order preserved" in out["comparison"]


def test_the_lying_double_a_put_that_returns_200_while_the_document_is_wrong(monkeypatch):
    """The branch that protects the whole testbed.

    `PutRolePolicy` answers 200 and `GetRolePolicy` hands back a document that is still missing
    the guardrail permission. A script trusting the status code would report a clean run and leave
    every guardrail-in-policy case in the repo broken — and the gateway's symptom would be a tool
    error that reads like a fail-open. A double that always restores correctly never reaches here.
    """
    wrong = M.document_without_sid(_shipped_doc(), M.TARGET_SID)
    monkeypatch.setattr(M, "capture", _Cap(_restore_script([wrong])))
    out = M.restore_document(None, None, captured=_captured())
    assert out["restored"] is False, (
        "the put succeeded and the document is wrong; trusting the 200 is the failure this "
        "read-back exists for")
    assert out["sha256_read_back"] != out["sha256_expected"]
    assert len(out["attempts"]) == M.DELETE_ATTEMPTS, "it must try again before giving up"
    remedy = out["manual_remedy"]
    assert ROLE in remedy and M.GW_EXEC_INLINE in remedy, (
        "the message must NAME the role and the policy: it is the only thing standing between a "
        "killed run and a repo-wide breakage")
    assert M.TARGET_ACTION in remedy and "--fix-drift" in remedy
    assert "breaks every guardrail-in-policy case" in remedy


def test_a_restore_that_lies_once_and_then_tells_the_truth_is_accepted(monkeypatch):
    """Each attempt re-reads, so a transient read failure does not report a failed restore."""
    monkeypatch.setattr(M, "capture", _Cap(_restore_script(
        [M.document_without_sid(_shipped_doc(), M.TARGET_SID), _shipped_doc()])))
    out = M.restore_document(None, None, captured=_captured())
    assert out["restored"] is True
    assert len(out["attempts"]) == 2


def test_a_read_back_that_failed_is_not_a_successful_restore(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_restore_script([None])))
    out = M.restore_document(None, None, captured=_captured())
    assert out["restored"] is False
    assert out["attempts"][0]["read_back_ok"] is False


def test_the_restore_puts_back_the_captured_object_and_not_a_rebuilt_one(monkeypatch):
    cap = _Cap(_restore_script([_shipped_doc()]))
    monkeypatch.setattr(M, "capture", cap)
    M.restore_document(None, None, captured=_captured())
    sent = json.loads(cap.params_for("put_role_policy")[0]["PolicyDocument"])
    assert sent == _shipped_doc()
    assert 'PolicyDocument=json.dumps(captured["document"])' in SRC, (
        "a restore assembled from infra/01_iam.py's spec would write what the spec says rather "
        "than what was there, and the two differ exactly when something else changed the role")


def test_a_failed_restore_is_rc_two_and_names_the_role_and_the_policy():
    tail = SRC[SRC.index('if statement_removed and not restore["restored"]:'):]
    assert "THE RESTORE FAILED" in tail
    assert "role_name!r" in tail and "GW_EXEC_INLINE!r" in tail
    assert tail.index("return 2") < tail.index("return 0"), (
        "the restore check must precede every success path")
    assert "--fix-drift" in tail


def test_a_failed_removal_write_is_a_refusal_and_not_a_broken_role(monkeypatch):
    """A failed PutRolePolicy leaves the previous document in place, so nothing is broken."""
    monkeypatch.setattr(M, "capture", _Cap({"put_role_policy": _rec(
        "put_role_policy", ok=False, error_code="MalformedPolicyDocument")}))
    with pytest.raises(M.ConfigError) as exc:
        M.remove_statement(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE,
                           reduced=_shipped_doc())
    assert "Nothing was changed" in str(exc.value)


# ===========================================================================
# the SIGKILL fallback
# ===========================================================================

def test_the_restore_intent_is_replayable_by_teardown():
    """`infra/99_teardown.py` replays `delete_op` with `delete_params` on a client for `service`.

    So the entry has to be a real, complete `put_role_policy` call — and it has to sort first.
    """
    st = _State()
    name = M.register_restore_intent(st, role_name=ROLE, run_id=RUN,
                                     target_statement=_shipped_doc()["Statement"][1])
    assert st.order[:2] == ["record:f54b_restore_intent", "write"]
    res = st.recorded[0]
    assert res.service == "iam" and res.delete_op == "put_role_policy"
    assert set(res.delete_params) == {"RoleName", "PolicyName", "PolicyDocument"}
    assert res.delete_params["RoleName"] == ROLE
    assert res.delete_params["PolicyName"] == name
    assert res.delete_priority == 1, "the restore must run before anything else at teardown"
    doc = json.loads(res.delete_params["PolicyDocument"])
    assert doc["Statement"][0]["Action"] == M.TARGET_ACTION


def test_the_fallback_document_carries_no_arn_so_the_ledger_mask_cannot_corrupt_it():
    """`state.json` is account-masked and `unmask_arn` restores only the FIRST masked field.

    The real document carries two ARNs (the echo Lambda and its version wildcard), so storing it
    in the ledger would come back with the second still masked — a restore that returns 200 and
    writes an invalid ARN. The single statement stored instead names `Resource: "*"`.
    """
    st = _State()
    M.register_restore_intent(st, role_name=ROLE, run_id=RUN,
                              target_statement=_shipped_doc()["Statement"][1])
    body = st.recorded[0].delete_params["PolicyDocument"]
    assert "arn:aws" not in body, (
        "an ARN here would be masked on the way into state.json and only partially restored on "
        "the way out")
    # And the round trip through the ledger's own masking is a no-op on it.
    masked = st.recorded[0].to_json()
    assert masked["delete_params"]["PolicyDocument"] == body
    assert T.unmask_arn(body, "") == body


def test_the_fallback_announces_itself_as_drift_rather_than_healing_silently():
    """It restores the permission in a DIFFERENT SHAPE, on purpose.

    `infra/01_iam.py.verify_role` reports an unexpected inline policy as drift ("a leftover
    mutation?"), so a fallback that fired is visible on the next verify instead of hiding that a
    run was killed inside its window.
    """
    st = _State()
    name = M.register_restore_intent(st, role_name=ROLE, run_id=RUN,
                                     target_statement=_shipped_doc()["Statement"][1])
    assert name != M.GW_EXEC_INLINE, (
        "writing the fallback into the SAME policy name would overwrite the document with a "
        "single statement — a restore worse than none")
    iam_src = (ROOT / "infra" / "01_iam.py").read_text(encoding="utf-8")
    assert "unexpected inline policies present" in iam_src, (
        "the fallback's self-announcement depends on verify_role reporting an extra inline policy "
        "as drift; if that changed, the fallback is now silent")
    assert "--fix-drift" in st.recorded[0].notes


def test_the_intent_is_registered_before_the_removal_and_dropped_only_after_verification():
    body = SRC[SRC.index("restore_intent_name = register_restore_intent"):]
    assert body.index("remove_statement(") < body.index("restore_document("), (
        "the intent must be recorded BEFORE the write it undoes")
    drop = SRC[SRC.index('if restore["restored"]:'):]
    assert 'state.drop("iam-inline-policy", "f54b_restore_intent")' in drop, (
        "the ledger entry must survive a FAILED restore — it is the channel another process uses "
        "to try again")


# ===========================================================================
# IAM propagation: two channels, both of IAM's
# ===========================================================================

def _iam_script(rounds):
    """`rounds` is a list of (sid_present, simulated_allowed) pairs, the last repeating."""
    seq = list(rounds)

    def _pop():
        nxt = seq[0]
        if len(seq) > 1:
            seq.pop(0)
        return nxt

    state = {"pending": None}

    def _doc(op, params):
        state["pending"] = _pop()
        present, _ = state["pending"]
        stmts = _shipped_doc()["Statement"]
        if not present:
            stmts = [s for s in stmts if s["Sid"] != M.TARGET_SID]
        return _rec("get_role_policy", response={"PolicyDocument": {"Statement": stmts}})

    def _sim(op, params):
        _, allowed = state["pending"]
        return _rec("simulate_principal_policy", response={"EvaluationResults": [
            {"EvalDecision": "allowed" if allowed else "implicitDeny"}]})
    return {"get_role_policy": _doc, "simulate_principal_policy": _sim}


def test_the_removal_wait_needs_both_channels_to_agree(monkeypatch):
    """The document changes on the write; the EVALUATION is the eventually-consistent half.

    Reading only the document would report the removal as complete while the FAS path still had
    the permission — confound (a), the one that turns a stale ALLOW into a published fail-open.
    """
    monkeypatch.setattr(M, "capture", _Cap(_iam_script([(False, True)])))
    out = M.wait_for_iam(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE,
                         role_arn=ROLE_ARN, want_present=False, phase="removal", max_s=30)
    assert out["reached"] is False, (
        "the statement is out of the document and IAM still evaluates the action as allowed; "
        "that is not a removal that has landed")
    assert "never agreed" in out["why_it_matters"]


def test_the_removal_wait_converges_when_both_channels_agree(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_iam_script([(False, True), (False, False)])))
    out = M.wait_for_iam(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE,
                         role_arn=ROLE_ARN, want_present=False, phase="removal", max_s=90)
    assert out["reached"] is True
    assert out["consecutive_confirmations"] == M.PROP_CONFIRM_N
    assert out["seconds"] > 0
    assert "GetRolePolicy" in out["channels"] and "SimulatePrincipalPolicy" in out["channels"]
    assert "not an authorization event" in out["simulation_caveat"]


def test_the_removal_wait_is_not_satisfied_by_an_alternating_sequence(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_iam_script(
        [(False, False), (False, True), (False, False), (False, True),
         (False, False), (False, True)])))
    out = M.wait_for_iam(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE,
                         role_arn=ROLE_ARN, want_present=False, phase="removal", max_s=40)
    assert out["reached"] is False, (
        "three alternating confirmations are not three CONSECUTIVE ones, and an alternating "
        "sequence is exactly the state that has not converged")
    assert out["consecutive_confirmations"] < M.PROP_CONFIRM_N


def test_the_restore_direction_reuses_the_same_wait_with_the_other_polarity(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_iam_script([(True, True)])))
    out = M.wait_for_iam(None, None, role_name=ROLE, policy_name=M.GW_EXEC_INLINE,
                         role_arn=ROLE_ARN, want_present=True, phase="restore",
                         max_s=M.RESTORE_PROP_MAX_S)
    assert out["reached"] is True and out["wanted_present"] is True


def test_the_removal_bound_is_tighter_than_the_restore_bound():
    """Every second of the removal is exposure; the restore direction costs none."""
    assert M.REMOVE_PROP_MAX_S < M.RESTORE_PROP_MAX_S
    assert M.REMOVE_PROP_MAX_S <= M.WINDOW_BOUND_S, (
        "a propagation bound wider than the window bound could not fit inside it")


# ===========================================================================
# the data plane
# ===========================================================================

def test_the_stabilisation_loop_is_symmetric_between_the_two_answers(monkeypatch):
    """A loop waiting for a NAMED decision would manufacture the answer by patience.

    So the same loop, with the same bound, must settle on ALLOW and on DENY alike.
    """
    for outcome, want in ((ALLOW, "ALLOW"), (DENY, "DENY")):
        monkeypatch.setattr(M, "client_for_leg",
                            lambda *a, **k: _Client([outcome]))
        out = M.wait_for_stable_decision(None, None, None, action_id=ACTION, text="t",
                                         run_id=RUN, phase="p")
        assert out["stabilised"] is True and out["decision"] == want
        assert out["consecutive_confirmations"] == M.STABILISE_CONFIRM_N
    assert "manufacture fail-closed" in out["why_symmetric"]


def test_an_alternating_data_plane_never_stabilises(monkeypatch):
    # The alternation has to survive the fresh session the loop opens for every probe. A double
    # rebuilt per client would restart at the first entry and answer the same thing every time —
    # a fake whose state resets is a fake that cannot express the sequence under test
    # (`feedback_unreachable_branch_in_fake`).
    monkeypatch.setattr(M, "client_for_leg", _alternating([DENY, ALLOW]))
    out = M.wait_for_stable_decision(None, None, None, action_id=ACTION, text="t",
                                     run_id=RUN, phase="p", max_s=40)
    assert out["stabilised"] is False and out["decision"] is None
    assert "non-deterministic" in out["why_it_matters"]


def test_a_tool_error_or_transport_error_is_not_a_stable_decision(monkeypatch):
    for bad in (TOOL_ERROR, HTTP_404, RuntimeError("boom")):
        monkeypatch.setattr(M, "client_for_leg", lambda *a, **k: _Client([bad]))
        out = M.wait_for_stable_decision(None, None, None, action_id=ACTION, text="t",
                                         run_id=RUN, phase="p", max_s=40)
        assert out["stabilised"] is False, (
            "a repeated error is stable and is still not one of the two answers")
        assert out["decisions_seen"], "the series is the evidence"


def test_every_stabilisation_probe_opens_and_closes_its_own_session(monkeypatch):
    """A long-lived session is a cache with our name on it — confound (b)."""
    made: list[_Client] = []

    def _factory(*a, **k):
        c = _Client([DENY])
        made.append(c)
        return c
    monkeypatch.setattr(M, "client_for_leg", _factory)
    M.wait_for_stable_decision(None, None, None, action_id=ACTION, text="t", run_id=RUN,
                              phase="p")
    assert len(made) >= M.STABILISE_CONFIRM_N
    assert all(c.closed == 1 for c in made), "every probe session must be closed"


def test_a_leg_is_all_or_nothing_and_reports_a_split_rather_than_a_rate():
    for script, decision in (([DENY], "DENY"), ([ALLOW], "ALLOW"),
                             ([DENY, ALLOW, ALLOW], "SPLIT"),
                             ([TOOL_ERROR], "NOTHING_USABLE")):
        out = M.probe_leg(_Client(script), leg="l", action_id=ACTION, text="t", item_id="i", n=3)
        assert out["decision"] == decision, script
        assert out["unanimous"] is (decision in ("DENY", "ALLOW"))


def test_a_transport_error_in_a_leg_is_neither_a_deny_nor_an_allow():
    out = M.probe_leg(_Client([RuntimeError("socket")]), leg="l", action_id=ACTION, text="t",
                      item_id="i", n=2)
    assert out["n_denied"] == 0 and out["n_allowed"] == 0
    assert out["n_usable"] == 0 and out["decision"] == "NOTHING_USABLE"
    assert out["n_reached_gateway"] == 0, (
        "a leg that never reached the policy path is confound (c) and must not read as an ALLOW")
    assert out["rows"][0]["outcome"].startswith("ERROR:")


def test_a_leg_that_did_not_reach_the_gateway_is_visible_in_its_own_count():
    out = M.probe_leg(_Client([HTTP_404]), leg="l", action_id=ACTION, text="t", item_id="i", n=2)
    assert out["n_reached_gateway"] == 2, "a 404 DID reach the gateway; it is not a transport loss"
    assert out["decision"] == "NOTHING_USABLE", "and it is still neither a DENY nor an ALLOW"


def test_the_request_text_is_sent_undecorated():
    """A marker appended to a violating item could change the score the guardrail assigns it.

    That score is the one property the leg depends on, so cache-breaking is done with a leg whose
    CONTENT differs instead — which is what `post_violating_new` is for.
    """
    client = _Client([DENY])
    text = "people of a particular religion are inherently less intelligent"
    M.probe_leg(client, leg="l", action_id=ACTION, text=text, item_id="i", n=3)
    assert {args["text"] for _, args in client.calls} == {text}, (
        "every request must carry exactly the corpus text")
    assert all(set(args) == {"text"} for _, args in client.calls), (
        "no extra argument may ride along; the echo tool's `amount` is F5-2's variable")


def test_the_two_violating_legs_are_the_cache_control_and_are_named_as_such():
    assert M.LEG_POST_VIOLATING_SAME in M.WINDOW_LEGS
    assert M.LEG_POST_VIOLATING_NEW in M.WINDOW_LEGS
    assert M.LEG_POST_BENIGN in M.WINDOW_LEGS
    assert set(M.WINDOW_LEGS) < set(M.LEGS)
    assert M.LEG_PRE_VIOLATING not in M.WINDOW_LEGS, (
        "the controls run BEFORE the window opens; putting one inside it would extend the "
        "exposure for a measurement that does not need it")
    assert M.LEG_RESTORED_VIOLATING not in M.WINDOW_LEGS


# ===========================================================================
# the forbid
# ===========================================================================

def test_the_forbid_is_f5_4a_s_proven_statement_form():
    """Reusing a proven statement keeps the post-removal reading interpretable.

    A new statement would fold "does this match at all" into the arm whose subject is what
    happens when it cannot be evaluated — and a statement that quietly failed to match would
    produce ALLOW everywhere and read as fail-open.
    """
    stmt = M.forbid_statement(GW_ARN, ACTION)
    assert stmt.startswith("forbid")
    assert "BedrockGuardrails::ContentFilter" in stmt, (
        "it must be a GUARDRAILS block: the bracketed data paths are what get handed to Bedrock "
        "Guardrails, and that hand-off is what the removed permission authorises")
    assert C.guardrail_condition("ContentFilter", ["HATE"], ["context.input.text"],
                                 threshold="0.2") in stmt
    assert ACTION in stmt and GW_ARN in stmt
    assert C.check_statement(stmt) == [], "the offline lint must pass on our own control"


def test_a_plain_cedar_condition_would_not_need_the_permission_at_all():
    """Why the forbid is a guardrails block and not a `when` clause.

    A plain condition is evaluated by Cedar itself and never calls Bedrock, so removing
    `bedrock:InvokeGuardrailChecks` would change nothing — the case would measure an unrelated
    path (which is F5-4a's `cedar_missing_attr` arm).
    """
    assert "when_guardrails=" in SRC
    assert "when=" not in _code_without_docstring()


def test_the_forbid_is_recorded_in_the_ledger_before_status_is_awaited(monkeypatch):
    st = _State()
    monkeypatch.setattr(M, "capture", _Cap({"create_policy": _rec(
        "create_policy", response={"policyId": "pid-1"})}))
    monkeypatch.setattr(M, "wait_status", lambda *a, **k: {"status": "ACTIVE"})
    monkeypatch.setattr(M.T, "check_name", lambda ac, op, name: name)
    out = M.create_forbid(_StubPolicyClient(), None, st, engine_id="eng", run_id=RUN,
                          statement=M.forbid_statement(GW_ARN, ACTION))
    assert out["policy_id"] == "pid-1" and out["status"] == "ACTIVE"
    assert st.order[:2] == ["record:f54b_block", "write"], (
        "a crash inside the status wait must still leave something teardown can find; `policy` "
        "resources are structurally untaggable, so the ledger is the only channel")


def test_a_forbid_that_never_became_active_refuses(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap({"create_policy": _rec(
        "create_policy", response={"policyId": "pid-1"})}))
    monkeypatch.setattr(M, "wait_status",
                        lambda *a, **k: {"status": "CREATE_FAILED", "statusReasons": ["no"]})
    monkeypatch.setattr(M.T, "check_name", lambda ac, op, name: name)
    with pytest.raises(M.ConfigError) as exc:
        M.create_forbid(_StubPolicyClient(), None, _State(), engine_id="e", run_id=RUN,
                        statement=M.forbid_statement(GW_ARN, ACTION))
    assert "fail-open of nothing" in str(exc.value), (
        "a policy that never enforced would make every leg ALLOW, which must not be reported as "
        "a finding")


def test_the_engine_interlock_refuses_a_concurrent_probe_policy():
    with pytest.raises(M.ConfigError) as exc:
        M.assert_engine_is_quiet(_State(policies=("baseline", "f52_block")))
    assert "not quiet" in str(exc.value) and "f52_block" in str(exc.value)
    out = M.assert_engine_is_quiet(_State())
    assert out["policies_on_engine_at_start"] == ["baseline"]


def test_deleting_the_forbid_never_raises_and_retries(monkeypatch):
    calls = {"n": 0}

    def _fail(op, params):
        calls["n"] += 1
        return _rec(op, ok=False, error_code="ConflictException")
    monkeypatch.setattr(M, "capture", _Cap([_fail]))
    out = M.delete_forbid(_StubPolicyClient(), None, _State(), engine_id="e", policy_id="p")
    assert out["deleted"] is False and calls["n"] == M.DELETE_ATTEMPTS
    assert "delete_policy" in out["manual_remedy"]

    monkeypatch.setattr(M, "capture", _Cap({"delete_policy": _rec(
        "delete_policy", ok=False, error_code="ResourceNotFoundException")}))
    assert M.delete_forbid(_StubPolicyClient(), None, _State(), engine_id="e",
                           policy_id="p")["deleted"] is True


# ===========================================================================
# the window
# ===========================================================================

def test_the_window_is_single_digit_minutes_and_the_bound_is_enforced_in_the_loop():
    assert M.WINDOW_BOUND_S <= 540, "the docstring promises single-digit minutes"
    assert M.WINDOW_BOUND_S == 300
    loop = SRC[SRC.index("for leg, item in (("):]
    assert "time.monotonic() - t_removed >= WINDOW_BOUND_S" in loop, (
        "the bound has to be checked INSIDE the leg loop; a bound only stated in a docstring is "
        "not a bound")
    assert loop.index("break") < loop.index("_leg(leg,"), (
        "the check must precede the leg it would abandon")
    assert "abandoned_legs" in loop


def test_the_measured_window_is_recorded_even_when_the_bound_was_respected():
    assert '"seconds_without_the_permission"' in SRC
    assert "window[\"within_bound\"] = False" in SRC


def test_the_window_guard_fails_when_the_bound_was_exceeded():
    g = M.guards(**_clean_guard_kwargs(window={"within_bound": False}))
    assert g["window_stayed_within_its_bound"] is False


def test_the_window_only_opens_after_the_controls_bracketed_the_measurement():
    """Removing a permission to collect legs nobody could interpret is exposure bought for nothing."""
    body = SRC[SRC.index('if not (legs[LEG_PRE_VIOLATING]["decision"] == "DENY"'):]
    assert "the permission will NOT be " in body, (
        "the operator has to be told the window did not open; the string is split across two "
        "source lines, so the assertion is on the part that carries the meaning")
    assert body.index("else:") < body.index("register_restore_intent"), (
        "the removal must sit in the else branch of the control check")


# ===========================================================================
# the guards
# ===========================================================================

def _clean_guard_kwargs(**over):
    kw = dict(
        interlock_engine={"policies_on_engine_at_start": ["baseline"]},
        captured={"sids": list(M.EXPECTED_SIDS)},
        forbid={"status": "ACTIVE"},
        legs=_legs(**CLEAN_CONTROLS, post_violating_same="DENY", post_violating_new="DENY",
                   post_benign="DENY", restored_violating="DENY"),
        removal_wait={"reached": True},
        window={"within_bound": True},
        restore={"restored": True},
        deletion={"deleted": True})
    kw.update(over)
    return kw


def test_a_clean_run_passes_every_guard():
    g = M.guards(**_clean_guard_kwargs())
    assert all(g.values()), [k for k, v in g.items() if not v]
    assert set(g) == set(M.GUARDS)


def test_the_guard_names_match_the_shipped_tuple_and_are_all_computed():
    for name in M.GUARDS:
        assert f'"{name}":' in SRC, f"{name} is declared in GUARDS but never computed"
    assert set(M.guards(**_clean_guard_kwargs())) == set(M.GUARDS)


def test_a_clean_run_passes_every_guard_under_fail_open_too():
    """The guards must not encode an outcome. A fail-open run is as clean as a fail-closed one."""
    g = M.guards(**_clean_guard_kwargs(
        legs=_legs(**CLEAN_CONTROLS, post_violating_same="ALLOW", post_violating_new="ALLOW",
                   post_benign="ALLOW", restored_violating="DENY")))
    assert all(g.values()), [k for k, v in g.items() if not v]


@pytest.mark.parametrize("over,failing", [
    ({"interlock_engine": {"policies_on_engine_at_start": ["baseline", "x"]}},
     "engine_was_quiet_at_start"),
    ({"captured": {"sids": ["AgentCoreAsDocumented"]}},
     "role_carried_exactly_its_shipped_document"),
    ({"forbid": {"status": "CREATE_FAILED"}}, "forbid_was_active_before_any_leg_ran"),
    ({"removal_wait": {"reached": False}},
     "removal_was_confirmed_by_iam_before_the_window_legs"),
    ({"restore": {"restored": False}},
     "document_was_restored_and_verified_byte_for_byte_after_normalisation"),
    ({"deletion": {"deleted": False}}, "probe_policy_was_deleted"),
    ({"window": {"within_bound": False}}, "window_stayed_within_its_bound"),
])
def test_each_guard_fails_for_its_own_reason(over, failing):
    g = M.guards(**_clean_guard_kwargs(**over))
    assert g[failing] is False
    assert not all(g.values())


def test_the_bracket_guard_needs_both_controls():
    for controls in ({M.LEG_PRE_VIOLATING: "ALLOW", M.LEG_PRE_BENIGN: "ALLOW"},
                     {M.LEG_PRE_VIOLATING: "DENY", M.LEG_PRE_BENIGN: "DENY"}):
        g = M.guards(**_clean_guard_kwargs(
            legs=_legs(**controls, post_violating_same="DENY", post_violating_new="DENY",
                       post_benign="DENY", restored_violating="DENY")))
        assert g["controls_bracketed_the_measurement"] is False


def test_a_missing_leg_is_a_failure_and_not_an_absent_pass():
    """`all([])` over legs that never ran would pass. Enumerated keys prevent that."""
    g = M.guards(**_clean_guard_kwargs(legs={}))
    assert g["controls_bracketed_the_measurement"] is False
    assert g["every_window_leg_reached_the_gateway"] is False
    assert g["post_removal_violating_legs_agreed"] is False
    assert g["blocking_was_reasserted_after_the_restore"] is False


def test_the_reassertion_guard_is_the_preregistered_restore_verification():
    """PREREGISTRATION's rule: restore, then RE-RUN the blocking assertion."""
    g = M.guards(**_clean_guard_kwargs(
        legs=_legs(**CLEAN_CONTROLS, post_violating_same="DENY", post_violating_new="DENY",
                   post_benign="DENY", restored_violating="ALLOW")))
    assert g["blocking_was_reasserted_after_the_restore"] is False
    prereg = (ROOT / "PREREGISTRATION.yaml").read_text(encoding="utf-8")
    assert "RE-RUN the blocking assertion" in prereg, (
        "this guard implements a sealed rule; if the rule is gone, the guard needs a new "
        "justification rather than deletion")


# ===========================================================================
# residue
# ===========================================================================

def test_a_run_that_never_opened_the_window_leaves_no_statement_residue():
    """The branch a constant created-list would get wrong.

    The controls failed, so the statement was never removed — and a residue that assumed the
    removal happened would exit 2 over a run that mutated nothing but its own probe policy.
    """
    res = M.residue(forbid_created=True, statement_removed=False, intent_registered=False,
                    restore={"restored": False}, deletion={"deleted": True},
                    restore_intent_dropped=True, sids_at_end=list(M.EXPECTED_SIDS))
    assert res["clean"] is True
    assert res["window_opened"] is False
    assert res["surviving"] == []


def test_a_statement_still_missing_at_the_end_is_residue():
    res = M.residue(forbid_created=True, statement_removed=True, intent_registered=True,
                    restore={"restored": False}, deletion={"deleted": True},
                    restore_intent_dropped=False,
                    sids_at_end=["AgentCoreAsDocumented",
                                 "HarnessLambdaTargetNotFromTheDocument"])
    assert res["statement_present_at_end"] is False
    assert res["clean"] is False
    assert f"statement_removed:{M.TARGET_SID}" in res["surviving"]
    assert "ledger:f54b_restore_intent" in res["surviving"]


def test_a_failed_read_back_is_residue_and_not_cleanliness():
    res = M.residue(forbid_created=False, statement_removed=True, intent_registered=True,
                    restore={"restored": True}, deletion={"deleted": True},
                    restore_intent_dropped=True, sids_at_end=None)
    assert res["statement_present_at_end"] is None
    assert res["clean"] is False, (
        "a permission we could not look at is not a permission we know is there")


def test_a_surviving_probe_policy_is_residue():
    res = M.residue(forbid_created=True, statement_removed=True, intent_registered=True,
                    restore={"restored": True}, deletion={"deleted": False},
                    restore_intent_dropped=True, sids_at_end=list(M.EXPECTED_SIDS))
    assert res["surviving"] == ["policy:forbid"]
    assert res["clean"] is False


def test_residue_is_clean_only_when_every_channel_agrees():
    res = M.residue(forbid_created=True, statement_removed=True, intent_registered=True,
                    restore={"restored": True}, deletion={"deleted": True},
                    restore_intent_dropped=True, sids_at_end=list(M.EXPECTED_SIDS))
    assert res["clean"] is True
    assert res["n_created"] == 3 and res["n_removed"] == 3
    assert "never ATTEMPTED" in res["why_two_lists"]


def test_the_script_cannot_exit_zero_while_residue_remains():
    tail = SRC[SRC.index('if not res["clean"]:'):]
    assert "return 2" in tail
    assert tail.index("return 2") < tail.index("return 0")
    assert SRC.count("    return 0\n") == 1, (
        "one success return, so no other path can reach it")


def test_every_refusal_path_returns_two_and_emits_a_record():
    assert SRC.count("O.not_measured(") == 6, (
        "the not-measured paths are: incomplete ledger, no engine, no action id, a failed "
        "restore, a ConfigError, and an unpublishable finding. A new one needs an arm here — a "
        "count is the only way to notice a refusal path that was added without being reasoned "
        "about")
    for reason in ("incomplete ledger", "no engine", "no action id", "THE RESTORE FAILED"):
        assert reason in SRC


def test_the_script_never_deletes_or_reconfigures_something_it_borrows():
    for forbidden in ("delete_gateway", "update_gateway", "delete_role", "delete_role_policy",
                      "delete_policy_engine", "put_role_permissions_boundary"):
        assert f'capture(store, "{forbidden}"' not in SRC, (
            f"{forbidden} must never appear: this case edits ONE statement in ONE inline policy "
            f"and creates ONE policy on a borrowed engine")


def test_the_nopolicy_gateway_is_never_used():
    code = _code_without_docstring()
    assert "nopolicy" not in code, "F6's paired baseline is out of scope"


# ===========================================================================
# the dry run, as a subprocess
# ===========================================================================

_DRY_RUNS: dict[tuple[str, ...], str] = {}


def _dry_run(*extra):
    """The shipped file's own `--dry-run`, memoised per argument set.

    A subprocess rather than a call into `main()`: the claim is that the file imports and reaches
    its arms without opening a socket, and an in-process call would inherit this file's
    monkeypatches — the state the dry run must not need.
    """
    key = tuple(extra)
    if key not in _DRY_RUNS:
        r = subprocess.run([PY, str(SCRIPT), "--dry-run", *extra], cwd=ROOT,
                           capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr
        _DRY_RUNS[key] = r.stdout
    return _DRY_RUNS[key]


def test_the_dry_run_prints_the_sealed_oracle_and_both_findings():
    out = _dry_run()
    assert "F5-4b dry run — no AWS call, no mutation" in out
    assert "OUTCOME UNKNOWN" in out
    assert M.FINDING_FAIL_CLOSED in out and M.FINDING_FAIL_OPEN in out
    assert "There is no pass condition" in out, (
        "a reader deciding whether to spend the window has to see that neither answer is a pass")
    for leg in M.LEGS:
        assert leg in out


def test_the_dry_run_declares_the_window_and_the_restore_contract():
    out = _dry_run()
    assert f"absent from {M.GW_EXEC_INLINE}" in out
    assert f"at most {M.WINDOW_BOUND_S}s" in out
    assert "put_role_policy" in out, "the SIGKILL channel belongs in the plan"
    assert "normalised JSON" in out and "sha256" in out
    assert f"mutations: {M.MAX_MUTATIONS}" in out


def test_the_dry_run_total_matches_the_arms_it_prints():
    out = _dry_run()
    total = M.N_PER_LEG * len(M.LEGS)
    assert f"total calls: {total}" in out
    assert f"mcp:tools/call x{total}" in out
    assert "billable text-unit sources" in out, (
        "these requests DO bill: a violating request makes the engine call "
        "InvokeGuardrailChecks when it can")


def test_a_smoke_run_shrinks_every_leg():
    out = _dry_run("--n", "2")
    assert "n=2" in out
    assert f"n={M.N_PER_LEG}" not in out
