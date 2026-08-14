#!/usr/bin/env python3
"""F5-3b's denial must be about a BOUNDARY, and the boundary must not survive the run.

Two hazards define this case, and every arm below sits on one of them.

THE FIRST IS THAT A DENIAL PROVES NOTHING BY ITSELF
`grx-attacker` holds no `bedrock-agentcore:UpdateGateway` in its shipped configuration
(infra/01_iam.py: "Note the absence of UpdateGateway"). A permissions boundary denies by
INTERSECTION, so a script that attached a boundary and observed `AccessDeniedException` would have
measured the role's shipped configuration and published it as a property of the boundary — and the
two responses are byte-for-byte identical. The positive control (grant first, attack ACCEPTED,
only then attach) is what separates them, so the heaviest arms here are on that control, on the
guard that gates the verdict against it, and on the classification that decides what "accepted"
means. This is F5-1's hazard and F5-2's hazard in a third costume.

THE SECOND IS THAT A SURVIVING BOUNDARY CORRUPTS OTHER CASES SILENTLY
A permissions boundary left attached to `grx-attacker` over-determines every future F5-1 and F5-2
replication: their denials would then have two causes, and neither script reads the boundary, so
both would keep publishing clean results about a role that is no longer in its shipped
configuration. Nothing in this repo would notice. So the teardown gets as much weight as the
measurement: the detach is verified by READING THE ROLE BACK rather than by trusting a 200, the
residue is computed from a created list and a removed list rather than from the removals alone,
and `rc=0` is unreachable while anything survives.

The properties tested are the ones under which the script would publish a confident falsehood or
leave the account changed:

* an existing boundary at start, or a leftover grant, accepted rather than refused — either makes
  the arms uninterpretable and one of them manufactures the sealed TRUE from our own litter;
* a `GetRole` that FAILED read as "no boundary attached";
* `ValidationException` counted as a denial, which is how our own malformed request becomes a
  security property;
* `ConflictException` counted as a denial, which is how an AUTHORIZED call becomes evidence of a
  boundary — it is returned after authorization;
* the positive control never authorized, yet a verdict published;
* the sealed mutation (detach -> succeeds) not inverting, published as TRUE rather than reported
  as unmeasured;
* a propagation wait satisfied by an ALTERNATING sequence, which is the state that has NOT
  converged;
* the omit-form boundary withholding `iam:PassRole` as well as `UpdateGateway`, which would make
  its denial attributable to either;
* the deny-form boundary written without its `Allow *`, which would reduce the role's effective
  permissions to nothing and pass every arm for the wrong reason;
* the in-boundary control missing, so a broken credential reads as the boundary working;
* a detach whose delete returned 200 while the role still carries the boundary — the LYING
  DOUBLE, and the branch that protects the whole testbed;
* residue computed from the removals alone, which reports zero survivors for exactly the case
  where one exists;
* `mutation_inverted` passed as a keyword instead of set as an attribute — the F5-1 defect that
  published INCONCLUSIVE over a clean 120-trial run;
* the attack body silently resetting a gateway field, or gaining a `mode` parameter this case has
  no business owning.

Nothing here makes an AWS call: `capture` is replaced wholesale and `M.time` is replaced with a
fake clock so the bounded poll loops run their real iteration counts in no wall-clock time. The
service model IS real, read from botocore, because "UpdateGateway is a full replacement over these
members" is the claim under test and a hand-typed member list here would be the second source of
truth the script exists to avoid.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

SCRIPT = ROOT / "f5_redteam" / "03_route4_permissions_boundary.py"
_spec = importlib.util.spec_from_file_location("grx_f5_03_route4_permissions_boundary", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules["grx_f5_03_route4_permissions_boundary"] = M
_spec.loader.exec_module(M)

import awsclients as A   # noqa: E402
import evidence as E     # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
import testbed as T      # noqa: E402

SRC = SCRIPT.read_text(encoding="utf-8")
PY = str(ROOT / ".venv-oracle" / "bin" / "python")


def _code_without_docstring() -> str:
    """The script's source with its module docstring removed.

    Several arms below assert that a token appears NOWHERE, and the module docstring of every case
    script in this project discusses at length the things the script deliberately does not do. A
    scan of the whole file would report the explanation as the offence — the same reason
    `lib/tests/test_account_id_choke_point.py` refuses to grep for the expression it forbids.
    """
    doc = ast.get_docstring(ast.parse(SRC)) or ""
    return SRC.replace(doc, "", 1) if doc else SRC

RUN = "r20260810T130945Z"
GW_ID = "grx-gw-r20260810t130945z-zpkfmpwo9n"
# The account-masked placeholder `lib/redact.py` writes into state.json, not a 12-digit literal.
# Nothing here is sent to an API, so a real-shaped account would buy nothing and would need a
# reviewed exception in `check_redaction.ALLOW` — a per-file waiver for a fixture is a worse
# trade than using the shape the ledger already stores.
ACCOUNT = "<account>"
GW_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:gateway/{GW_ID}"
ENGINE_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:policy-engine/grx_pe_{RUN}-t6hq"
GW_EXEC_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/grx-gw-exec-{RUN}"
ATTACKER_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/grx-attacker-{RUN}"
ROLE = f"grx-attacker-{RUN}"
GRANT = f"grx-f53b-grant-{RUN}"
BOUNDARY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/grx-f53b-boundary-deny-{RUN}"

_SM = A.service_model("bedrock-agentcore-control")
_UPD = _SM.operation_model("UpdateGateway").input_shape
ALLOWED = frozenset(_UPD.members)
REQUIRED = frozenset(_UPD.required_members)


class _AC:
    """A client stand-in carrying the REAL service model and nothing that can reach AWS.

    `_update_shape` reads `ac.meta.service_model`, and faking the model would turn every shape
    assertion below into a statement about the fake.
    """

    class _Meta:
        service_model = _SM

    meta = _Meta()


def _live(**over):
    """A `GetGateway` response shaped like the live one, carrying every member the model accepts."""
    d = {
        "gatewayId": GW_ID, "gatewayArn": GW_ARN, "name": f"grxgw{RUN}",
        "gatewayUrl": f"https://{GW_ID}.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        "status": "READY", "createdAt": "2026-08-10T13:09:45Z", "updatedAt": "x",
        "roleArn": GW_EXEC_ROLE_ARN, "authorizerType": "AWS_IAM", "protocolType": "MCP",
        "exceptionLevel": "DEBUG", "description": "grx main gateway",
        "protocolConfiguration": {"mcp": {"sessionConfiguration":
                                          {"sessionTimeoutInSeconds": 900}}},
        "policyEngineConfiguration": {"arn": ENGINE_ARN, "mode": "ENFORCE"},
    }
    d.update(over)
    return d


# ---- stand-ins -------------------------------------------------------------

def _rec(op="update_gateway", *, ok=True, response=None, error_code="", error_message="",
         http_status=200):
    """A real `evidence.Record`, so a field renamed on Record breaks these arms.

    The alternative — a local stand-in class — passes forever against a Record whose fields have
    moved, which is the shape `lib/tests/test_probe_guardrail.py` calls out for its own doubles.
    """
    return E.Record(case_id="F5-3b", operation=op, service="iam", region="us-east-1",
                    params={}, ok=ok, http_status=http_status if ok else 400,
                    request_id="rid-0001", response=response or {},
                    error_code=error_code, error_message=error_message,
                    path="evidence/x/0001_op_ok.json")


DENIED = _rec(ok=False, error_code="AccessDeniedException", error_message="not authorized")
DENIED_SHORT = _rec(ok=False, error_code="AccessDenied")
CONFLICT = _rec(ok=False, error_code="ConflictException", error_message="gateway is UPDATING")
INVALID = _rec(ok=False, error_code="ValidationException", error_message="bad member")
THROTTLED = _rec(ok=False, error_code="ThrottlingException")
ACCEPTED = _rec(response={"gatewayId": GW_ID, "status": "UPDATING"})


class _Cap:
    """Scripted `capture` replacement.

    Accepts a list (consumed in order, last entry repeats so a poll loop cannot exhaust it) or a
    dict keyed by operation name. The repeat matters: a bounded poll loop that ran out of script
    would fail with `TestScriptExhausted` rather than exercising the timeout branch the loop
    exists for.
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
    """A fake `time`, so a 300s poll bound costs no wall clock and runs its real loop count.

    Installed by replacing `M.time` rather than the real module: a no-op `sleep` against a real
    `monotonic` would spin these loops for their full wall-clock bound, and shrinking the bound
    instead would test a different loop than the one that ships.
    """

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += max(float(s), 0.001)


class _State:
    """A ledger stand-in recording the ORDER of its calls, which several arms assert on."""

    run_id = RUN
    expires_at = "2026-08-13T13:09:45+00:00"

    def __init__(self, policies=()):
        self._p = list(policies)
        self.order: list[str] = []
        self.recorded: list[T.Resource] = []

    def of_kind(self, kind):
        return [r for r in self.recorded if r.kind == kind]

    def record(self, r):
        self.order.append(f"record:{r.logical}")
        self.recorded.append(r)

    def write(self):
        self.order.append("write")

    def drop(self, kind, logical):
        self.order.append(f"drop:{kind}/{logical}")
        self.recorded = [r for r in self.recorded
                         if not (r.kind == kind and r.logical == logical)]


@pytest.fixture(autouse=True)
def _sealed(monkeypatch):
    """No AWS, no real limiter sleep, no real clock — for every test in the file."""
    monkeypatch.setattr(M, "capture", _Cap([]))
    monkeypatch.setattr(M, "time", _Clock())
    monkeypatch.setattr(M.A, "limiter",
                        lambda: type("L", (), {"wait": staticmethod(lambda *a, **k: None)})())
    yield


# ===========================================================================
# the sealed oracle this design is built against
# ===========================================================================

def test_the_binding_is_existence_with_a_mandatory_mutation():
    """The positive control and the detach arm exist because the mutation is MANDATORY.

    If a re-seal made it optional, `removing_the_boundary_reopened_the_route` would become
    decoration and the argument that a denial must be attributable would stop being enforced
    anywhere.
    """
    b = O.BINDINGS["F5-3b"]
    assert b.kind == "EXISTENCE"
    assert O.mutation_is_mandatory("F5-3b") is True
    assert O.alpha_for("F5-3b") == pytest.approx(0.05)
    assert O.planned_n("F5-3b") is None, (
        "a sealed n would have to gate the verdict; this case has none, so `n` in the "
        "observation is a denominator a reader can check and not a floor")


def test_the_oracle_text_names_both_halves_this_script_implements():
    text = O.oracle_text("F5-3b")
    assert "identity policy granting it" in text, (
        "the oracle's 'despite an identity policy granting it' IS the positive control; if that "
        "clause is gone, re-read whether the grant is still required")
    assert "remove boundary" in text and "succeeds" in text, (
        "the sealed mutation is the detach; if the seal no longer names it, the detach arm's "
        "status changes")
    assert "boundary is ineffective" in text, "the FALSE branch must still be the sealed one"


def test_update_gateway_is_rate_limited_so_the_limiter_call_is_not_decoration():
    assert A.rate_limit_for("UpdateGateway"), "UpdateGateway has no rate in RATE_LIMITS"
    assert 'A.limiter().wait("UpdateGateway")' in SRC


def _limiter_operations() -> list[str]:
    """Every string literal passed to a `.wait(...)` call in the script, read by AST.

    By AST and not by grep, because the script's own comment QUOTES the expression it is arguing
    against — the same reason `lib/tests/test_account_id_choke_point.py` gives for not grepping
    for the text of the call it forbids. A textual scan would report the explanation as the
    offence.
    """
    tree = ast.parse(SRC)
    out: list[str] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "wait" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            out.append(node.args[0].value)
    return out


def test_iam_writes_are_spaced_by_the_explicit_sleep_and_not_by_a_no_op_limiter():
    """The script spaces IAM writes with `time.sleep(INTER_IAM_S)`, not with `lim.wait(...)`.

    This arm's premise changed on 2026-08-13, and that it changed loudly is the reason it is
    written as a pin. It used to assert that `RATE_LIMITS` held no IAM entry at all — true when the
    script was written, and the reason the script chose an explicit sleep: `RateLimiter.wait`
    returns 0.0 for an unknown operation, so `lim.wait("PutRolePolicy")` would have read as rate
    limiting while doing nothing, the defect `awsclients.SELF_IMPOSED_LIMITS`'s comment describes.
    The repo-wide cross-check on 2026-08-13 then gave the three IAM writes real, self-imposed
    rates; this arm fired, and the sentence was re-read instead of quietly becoming false.

    What is asserted now, and why the script is NOT rewritten to route these through the limiter:
    the explicit sleep is still the BINDING spacing — 0.5 s is at least the limiter's interval for
    every one of these operations — so the addition changed nothing about how this case behaves,
    and re-plumbing the pacing of a script whose evidence is already published would be an unforced
    edit to a measured instrument. The inequality is the new pin: drop `INTER_IAM_S` below a
    limiter interval and the two mechanisms disagree about which one is the ceiling, and it is
    reported here rather than discovered in a rerun.
    """
    for op in ("PutRolePolicy", "PutRolePermissionsBoundary", "DeleteRolePermissionsBoundary"):
        rate = A.rate_limit_for(op)
        assert rate is not None, (
            f"{op} no longer has a rate in RATE_LIMITS, so `lim.wait({op!r})` would be a no-op "
            f"again; the explicit INTER_IAM_S sleep is then the only spacing there is")
        assert op in A.SELF_IMPOSED_LIMITS, (
            f"{op}'s rate is no longer marked as ours. No per-second IAM control-plane ceiling was "
            f"found for it, and an evidence record must not be able to cite our caution as a fact "
            f"about the service")
        assert M.INTER_IAM_S >= 1.0 / rate, (
            f"INTER_IAM_S={M.INTER_IAM_S}s is shorter than the limiter's {1.0 / rate}s interval "
            f"for {op}, so the explicit sleep is no longer the binding spacing and the script "
            f"should ask the limiter to wait instead of sleeping under its ceiling")
    assert A.rate_limit_for("GetRole") is None, (
        "GetRole gained a rate, so the boundary read-back is now paced by the limiter as well as "
        "by INTER_IAM_S; this arm's account of which call is spaced by what is stale")
    waited = _limiter_operations()
    assert waited == ["UpdateGateway"], (
        f"the only operation this case paces through the limiter is UpdateGateway, which IS in "
        f"RATE_LIMITS; got {waited}")
    assert M.INTER_IAM_S > 0, "the IAM writes have to be spaced by something real"


# ===========================================================================
# the attack body
# ===========================================================================

def test_the_shape_is_read_from_the_service_model():
    allowed, required = M._update_shape(_AC())
    assert allowed == ALLOWED
    assert required == REQUIRED
    assert set(required) == {"gatewayIdentifier", "roleArn", "name", "authorizerType"}
    assert "roleArn" in required, (
        "roleArn being required is WHY iam:PassRole is granted alongside UpdateGateway and why "
        "the omit-form ceiling has to include PassRole; if it stops being required, that whole "
        "argument needs re-reading")


def test_the_body_carries_every_live_member_the_model_accepts():
    """The silent-reset failure: UpdateGateway REPLACES, so an omitted member is an unset."""
    live = _live()
    body = M._noop_body(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED)
    for key in ("protocolConfiguration", "exceptionLevel", "description", "roleArn",
                "authorizerType", "protocolType", "policyEngineConfiguration", "name"):
        assert body[key] == live[key], f"{key} was dropped; UpdateGateway would unset it"
    assert body["gatewayIdentifier"] == GW_ID
    assert set(body) - {"gatewayIdentifier"} <= set(live), "nothing may be invented"


def test_a_member_the_model_does_not_accept_is_not_sent():
    """`GetGateway` returns fields UpdateGateway rejects; sending one is a ValidationException."""
    body = M._noop_body(_live(), gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED)
    for junk in ("gatewayId", "createdAt", "updatedAt", "status", "gatewayUrl", "gatewayArn"):
        assert junk not in body
    assert set(body) <= ALLOWED


def test_the_body_does_not_share_nested_state_with_the_live_read():
    """The comparison that cannot fail.

    The caller keeps `live_before` for the end-of-run diff. If the body shared the nested dicts,
    any later mutation of the body would also mutate the record the end state is compared
    against, and `gateway_was_left_field_for_field_identical` would compare a value with itself.
    """
    live = _live()
    before = copy.deepcopy(live)
    body = M._noop_body(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED)
    body["policyEngineConfiguration"]["mode"] = "LOG_ONLY"
    body["protocolConfiguration"]["mcp"]["sessionConfiguration"]["sessionTimeoutInSeconds"] = 1
    assert live == before, "building the body mutated the record the end state is checked against"
    assert body["policyEngineConfiguration"] is not live["policyEngineConfiguration"]
    assert body["protocolConfiguration"] is not live["protocolConfiguration"]


def test_the_body_builder_has_no_way_to_change_a_gateway_field():
    """F5-3b must not be able to move the gateway; that is F5-2's job.

    F5-2's `_replacement_kwargs` carries `mode=` and `drop_pec=` because its subject is the
    mode. A parameter this case does not need is a parameter a later edit could use to move the
    gateway F4's truth table and every F6 latency verdict are published against — from a file
    whose docstring promises it changes nothing.
    """
    import inspect
    params = set(inspect.signature(M._noop_body).parameters)
    assert params == {"live", "gateway_id", "allowed", "required"}
    assert "mode" not in params and "drop_pec" not in params
    # And no mode value is written anywhere in the CODE. The docstring discusses F5-2's LOG_ONLY
    # chain at length, so the scan is over the code with the module docstring removed — a textual
    # scan of the whole file would report the explanation as the offence.
    assert "LOG_ONLY" not in _code_without_docstring(), (
        "this script has no business naming a mode it does not set")
    # Reading the mode is fine and necessary — the startup interlock reports it. WRITING one is
    # what this case must not be able to do, so the scan is for an assignment.
    assert '["mode"] =' not in SRC, (
        "an assignment into a policyEngineConfiguration is how this case would acquire the "
        "ability to move the gateway F4 and F6 are published against")


def test_a_missing_required_member_refuses_rather_than_sending_a_doomed_body():
    live = _live()
    del live["roleArn"]
    with pytest.raises(M.ConfigError) as exc:
        M._noop_body(live, gateway_id=GW_ID, allowed=ALLOWED, required=REQUIRED)
    assert "roleArn" in str(exc.value)
    assert "NOT_MEASURED" in str(exc.value), (
        "the refusal must say what publishing over it would look like")


# ===========================================================================
# the three documents
# ===========================================================================

def test_the_grant_actually_grants_the_action_under_test():
    """"despite an identity policy granting it" is a claim about THIS document."""
    doc = M.grant_document(GW_ARN, GW_EXEC_ROLE_ARN)
    actions = {s["Action"]: s["Resource"] for s in doc["Statement"]}
    assert actions["bedrock-agentcore:UpdateGateway"] == GW_ARN, (
        "if the grant does not name UpdateGateway on THIS gateway, the boundary arms measure the "
        "role's shipped configuration and the sealed TRUE is manufactured from it")
    assert actions["iam:PassRole"] == GW_EXEC_ROLE_ARN, (
        "roleArn is a required member of UpdateGateway, so PassRole is in play; without it the "
        "positive control would be denied and the case would report NOT_MEASURED")
    assert actions["bedrock-agentcore:GetGateway"] == GW_ARN, (
        "the in-boundary control needs an action the attacker may take")
    for stmt in doc["Statement"]:
        assert stmt["Effect"] == "Allow"
        assert stmt["Resource"] != "*", (
            "a wildcard would reach the six pre-existing READY gateways this project must not "
            "touch, even read-only")


def test_the_deny_form_boundary_keeps_an_allow_ceiling():
    """A Deny-only boundary reduces effective permissions to NOTHING.

    Every arm would then fail — including the in-boundary control — and the case would read as
    the boundary blocking UpdateGateway specifically. This is the mutation-checked half of that
    document: drop the `Allow *` statement and this arm dies.
    """
    doc = M.boundary_deny_document(GW_ARN)
    effects = [s["Effect"] for s in doc["Statement"]]
    assert "Allow" in effects, (
        "a boundary is a CEILING: with no Allow the role's effective permissions are empty and "
        "the in-boundary control cannot distinguish that from the Deny working")
    assert "Deny" in effects
    allow = next(s for s in doc["Statement"] if s["Effect"] == "Allow")
    deny = next(s for s in doc["Statement"] if s["Effect"] == "Deny")
    assert allow["Action"] == "*" and allow["Resource"] == "*"
    assert deny["Action"] == M.ACTION_UPDATE
    assert deny["Resource"] == GW_ARN, (
        "a wildcard Deny would change how this identity relates to gateways outside the testbed")


def test_the_omit_form_boundary_withholds_exactly_one_action():
    """The one-variable property, in both directions.

    UpdateGateway must be absent from the ceiling — that is the experiment — and `iam:PassRole`
    must be PRESENT, because `roleArn` is a required member of UpdateGateway and a ceiling
    withholding both would deny for either reason. The AccessDeniedException names neither, so
    the distinction has to be built into the document.
    """
    doc = M.boundary_omit_document(GW_ARN, GW_EXEC_ROLE_ARN)
    text = json.dumps(doc)
    assert M.ACTION_UPDATE not in text, (
        "UpdateGateway must be absent from the ceiling; naming it — even to Deny it — turns this "
        "arm into a second copy of the deny form and the intersection rule goes untested")
    assert M.ACTION_PASSROLE in text, (
        "a ceiling omitting PassRole as well would deny for either reason, and this arm would "
        "stop being a one-variable experiment")
    assert all(s["Effect"] == "Allow" for s in doc["Statement"]), (
        "the omit form must contain NO Deny at all: its whole point is that only the "
        "intersection rule can produce a denial")
    # And the ceiling covers what the role already had, so nothing else it could do is newly
    # blocked — otherwise the in-boundary control might fail for an unrelated reason.
    covered = {a for s in doc["Statement"]
               for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    assert set(M.SHIPPED_ACTIONS) <= covered, (
        f"the ceiling omits {sorted(set(M.SHIPPED_ACTIONS) - covered)}, which the role's shipped "
        f"identity policy already allows; a denial there is a second variable")


def test_the_shipped_action_list_matches_the_provisioner():
    """`SHIPPED_ACTIONS` is a claim about infra/01_iam.py, so it is checked against it.

    A drifted copy would make the omit-form ceiling narrower than the role's own policy, and the
    in-boundary control could then fail for a reason unrelated to the boundary under test.
    """
    iam_src = (ROOT / "infra" / "01_iam.py").read_text(encoding="utf-8")
    start = iam_src.index('specs["attacker"]')
    end = iam_src.index('specs["runtime-exec"]')
    block = iam_src[start:end]
    for action in M.SHIPPED_ACTIONS:
        assert f'"{action}"' in block, (
            f"{action} is in SHIPPED_ACTIONS but not in infra/01_iam.py's attacker policy; the "
            f"omit-form ceiling would then grant something the role never had")


def test_boundary_form_for_refuses_an_arm_that_is_not_a_boundary_arm():
    for arm in M.BOUNDARY_ARMS:
        assert M.boundary_form_for(arm, gateway_arn=GW_ARN, gw_role_arn=GW_EXEC_ROLE_ARN)
    with pytest.raises(ValueError):
        M.boundary_form_for(M.ARM_GRANTED, gateway_arn=GW_ARN, gw_role_arn=GW_EXEC_ROLE_ARN)


# ===========================================================================
# the interlocks
# ===========================================================================

def _pristine_script(*, inline=(M.BASELINE_INLINE,), managed=(), boundary=None,
                     get_role_ok=True, list_ok=True):
    return {
        "list_role_policies": (_rec("list_role_policies",
                                    response={"PolicyNames": list(inline)}) if list_ok
                               else _rec("list_role_policies", ok=False,
                                         error_code="ServiceFailure")),
        "list_attached_role_policies": _rec(
            "list_attached_role_policies",
            response={"AttachedPolicies": [{"PolicyArn": m} for m in managed]}),
        "get_role": (_rec("get_role", response={"Role": {
            "RoleName": ROLE,
            **({"PermissionsBoundary": {"PermissionsBoundaryArn": boundary,
                                        "PermissionsBoundaryType": "Policy"}}
               if boundary else {})}}) if get_role_ok
                     else _rec("get_role", ok=False, error_code="ServiceFailure")),
    }


def test_a_pristine_role_passes_the_interlock(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_pristine_script()))
    out = M.assert_role_is_pristine(None, None, role_name=ROLE, grant_name=GRANT)
    assert out["inline_policies_at_start"] == [M.BASELINE_INLINE]
    assert out["attached_managed_policies_at_start"] == []
    assert out["permissions_boundary_at_start"] is None


def test_an_existing_boundary_refuses_because_it_is_the_required_pre_state(monkeypatch):
    """This case's pre-state is NO boundary, and the audit on 2026-08-13 confirmed it.

    With one already in force the positive control cannot establish that the attack is otherwise
    accepted, and a denial under OUR boundary is attributable to either — including to a Deny
    somebody else wrote, which would produce the sealed TRUE from litter.
    """
    monkeypatch.setattr(M, "capture", _Cap(_pristine_script(boundary=BOUNDARY_ARN)))
    with pytest.raises(M.ConfigError) as exc:
        M.assert_role_is_pristine(None, None, role_name=ROLE, grant_name=GRANT)
    assert "already carries a permissions boundary" in str(exc.value)
    assert "delete-role-permissions-boundary" in str(exc.value), (
        "the refusal must name the command that fixes it")


def test_a_failed_get_role_is_not_a_role_with_no_boundary(monkeypatch):
    """`feedback_guard_tool_exit_codes`: a read that failed must not report the clean answer."""
    monkeypatch.setattr(M, "capture", _Cap(_pristine_script(get_role_ok=False)))
    with pytest.raises(M.ConfigError) as exc:
        M.assert_role_is_pristine(None, None, role_name=ROLE, grant_name=GRANT)
    assert "GetRole" in str(exc.value) and "unknown" in str(exc.value)


def test_a_leftover_grant_refuses_rather_than_being_overwritten(monkeypatch):
    monkeypatch.setattr(M, "capture",
                        _Cap(_pristine_script(inline=(M.BASELINE_INLINE, GRANT))))
    with pytest.raises(M.ConfigError) as exc:
        M.assert_role_is_pristine(None, None, role_name=ROLE, grant_name=GRANT)
    assert GRANT in str(exc.value)
    assert "crashed" in str(exc.value)


def test_an_unexpected_inline_policy_refuses(monkeypatch):
    monkeypatch.setattr(M, "capture",
                        _Cap(_pristine_script(inline=(M.BASELINE_INLINE, "somebody-elses"))))
    with pytest.raises(M.ConfigError) as exc:
        M.assert_role_is_pristine(None, None, role_name=ROLE, grant_name=GRANT)
    assert "not exactly" in str(exc.value)


def test_an_attached_managed_policy_refuses_because_it_could_grant_the_action(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_pristine_script(
        managed=(f"arn:aws:iam::{ACCOUNT}:policy/somebody-elses",))))
    with pytest.raises(M.ConfigError) as exc:
        M.assert_role_is_pristine(None, None, role_name=ROLE, grant_name=GRANT)
    assert "attached managed policies" in str(exc.value)


def test_a_failed_list_role_policies_refuses(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_pristine_script(list_ok=False)))
    with pytest.raises(M.ConfigError):
        M.assert_role_is_pristine(None, None, role_name=ROLE, grant_name=GRANT)


@pytest.mark.parametrize("over,needle", [
    ({"status": "UPDATING"}, "not READY"),
    ({"policyEngineConfiguration": {"arn": ENGINE_ARN, "mode": "LOG_ONLY"}}, "not 'ENFORCE'"),
    ({"policyEngineConfiguration": {"arn": "arn:aws:x:::policy-engine/other",
                                    "mode": "ENFORCE"}}, "not the ledger's"),
])
def test_the_gateway_interlock_refuses_each_wrong_start(over, needle):
    with pytest.raises(M.ConfigError) as exc:
        M.assert_gateway_is_provisioned(_live(**over), engine_arn=ENGINE_ARN)
    assert needle in str(exc.value)


def test_a_provisioned_gateway_passes_the_interlock():
    out = M.assert_gateway_is_provisioned(_live(), engine_arn=ENGINE_ARN)
    assert out["engine_arn_matches_ledger"] is True
    assert out["mode"] == "ENFORCE" and out["status"] == "READY"


# ===========================================================================
# classification of one attempt
# ===========================================================================

@pytest.mark.parametrize("rec,outcome", [
    (DENIED, "denied_by_iam"),
    (DENIED_SHORT, "denied_by_iam"),
    (CONFLICT, "conflict"),
    (INVALID, "unusable"),
    (THROTTLED, "unusable"),
    (ACCEPTED, "accepted"),
])
def test_every_response_lands_in_exactly_one_bucket(monkeypatch, rec, outcome):
    """The two that are NOT denials are the ones that matter.

    A `ValidationException` counted as a denial is how our own malformed request becomes a
    security property; a `ConflictException` counted as a denial is how an AUTHORIZED call becomes
    evidence of a boundary — it is returned after authorization.
    """
    monkeypatch.setattr(M, "capture", _Cap([rec]))
    row = M._attempt(_AC(), None, kwargs={"gatewayIdentifier": GW_ID}, trial_id="t")
    assert row["outcome"] == outcome
    assert "AccessDenied" in M.DENIED_CODES, "the short form is what IAM returns on some APIs"


def test_a_conflict_is_counted_as_authorized_and_tallied_separately():
    t = M.tally("a", [{"outcome": "conflict"}, {"outcome": "accepted"},
                      {"outcome": "denied_by_iam"}, {"outcome": "unusable"}])
    assert t["n_authorized"] == 2, "a ConflictException follows authorization: IAM said yes"
    assert t["n_conflict"] == 1 and t["n_accepted"] == 1
    assert t["n_usable"] == 3, "the unusable attempt must not be denominated as a denial"
    assert t["reading"] == "SPLIT"


@pytest.mark.parametrize("rows,reading", [
    ([{"outcome": "denied_by_iam"}] * 5, "DENIED"),
    ([{"outcome": "accepted"}] * 3, "AUTHORIZED"),
    ([{"outcome": "conflict"}] * 3, "AUTHORIZED"),
    ([{"outcome": "accepted"}, {"outcome": "denied_by_iam"}], "SPLIT"),
    ([{"outcome": "unusable"}] * 4, "NOTHING_USABLE"),
    ([], "NOTHING_USABLE"),
])
def test_an_arm_is_all_or_nothing_and_a_split_is_reported_not_averaged(rows, reading):
    t = M.tally("a", rows)
    assert t["reading"] == reading
    assert t["unanimous"] is (reading in ("DENIED", "AUTHORIZED"))


def test_an_arm_that_collected_nothing_usable_is_not_a_denial():
    """4 ValidationExceptions are not a boundary; they are our bug."""
    t = M.tally(M.ARM_BOUNDARY_DENY, [{"outcome": "unusable", "error_code": "ValidationException"}]
                * 4)
    assert t["reading"] == "NOTHING_USABLE"
    r = M.boundary_reading({M.ARM_BOUNDARY_DENY: t,
                            M.ARM_BOUNDARY_OMIT: M.tally(M.ARM_BOUNDARY_OMIT,
                                                         [{"outcome": "denied_by_iam"}])})
    assert r["all_forms_blocked"] is False, (
        "an arm that measured nothing must not count as a block")


def test_the_arm_loop_settles_only_after_an_accepted_attempt(monkeypatch):
    """Polling GetGateway after a denial would add calls to watch a status that cannot move."""
    seen: list[str] = []
    monkeypatch.setattr(M, "wait_ready", lambda ac, gid, **k: seen.append(gid) or _live())
    monkeypatch.setattr(M, "capture", _Cap([DENIED]))
    M.run_arm(_AC(), None, arm="a", kwargs={}, n=2, settle=True, gateway_id=GW_ID)
    assert seen == [], "a denied attempt changed no state"
    monkeypatch.setattr(M, "capture", _Cap([ACCEPTED]))
    M.run_arm(_AC(), None, arm="a", kwargs={}, n=2, settle=True, gateway_id=GW_ID)
    assert seen == [GW_ID, GW_ID]


def test_a_settle_timeout_is_recorded_and_does_not_lose_the_authorization_outcome(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("waiter timed out")
    monkeypatch.setattr(M, "wait_ready", _boom)
    monkeypatch.setattr(M, "capture", _Cap([ACCEPTED]))
    t = M.run_arm(_AC(), None, arm="a", kwargs={}, n=1, settle=True, gateway_id=GW_ID)
    assert t["n_authorized"] == 1, "the authorization happened; the waiter is a separate fact"
    assert "settle_error" in t["rows"][0]


# ===========================================================================
# propagation
# ===========================================================================

def test_the_propagation_wait_is_not_satisfied_by_an_alternating_sequence(monkeypatch):
    """A cumulative count would end the wait on the very evidence that should extend it.

    F5-2 measured this: a wait ended on a single confirmation and 9 of the next 20 calls
    disagreed with it.

    THE BOUND HERE IS DELIBERATELY GENEROUS, and the first version of this arm was not — it used
    `max_s=30`, which with a 10s interval is three probes and only ONE wanted outcome among them.
    A `wait_for_effect` that counted CUMULATIVELY would also have returned `reached: False` on
    that sequence, because it ran out of time rather than because the rule held. The arm passed
    and tested nothing (`feedback_vacuous_test_check`); mutation-checking it is what found that.
    With 200s the alternating series delivers ten wanted outcomes, so a cumulative count reaches
    its three long before the deadline and only the CONSECUTIVE rule can still refuse.
    """
    seq = [DENIED, ACCEPTED]
    n_probes = int(200 // M.PROP_EVERY_S)
    monkeypatch.setattr(M, "capture", _Cap([seq[i % 2] for i in range(n_probes)]))
    monkeypatch.setattr(M, "wait_ready", lambda *a, **k: _live())
    out = M.wait_for_effect(_AC(), None, kwargs={}, want="denied_by_iam", phase="p", max_s=200)
    assert out["outcomes_seen"].count("denied_by_iam") >= M.PROP_CONFIRM_N, (
        "the series has to contain MORE wanted outcomes than the confirmation count, or this arm "
        "cannot distinguish a consecutive rule from a cumulative one")
    assert out["reached"] is False, (
        "ten alternating denials are not three CONSECUTIVE denials, and an alternating fleet is "
        "exactly the state that has not converged")
    assert out["consecutive_confirmations"] < M.PROP_CONFIRM_N
    assert "never confirmed" in out["why_it_matters"]


def test_the_propagation_wait_converges_on_consecutive_agreement(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([ACCEPTED, ACCEPTED, DENIED]))
    monkeypatch.setattr(M, "wait_ready", lambda *a, **k: _live())
    out = M.wait_for_effect(_AC(), None, kwargs={}, want="denied_by_iam", phase="p", max_s=300)
    assert out["reached"] is True
    assert out["consecutive_confirmations"] == M.PROP_CONFIRM_N
    assert out["seconds"] > 0, "the delay is a finding, so it has to be measured"
    assert out["flapped_before_converging"] is False


def test_the_propagation_wait_records_a_flap_it_converged_through(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([DENIED, ACCEPTED, DENIED]))
    monkeypatch.setattr(M, "wait_ready", lambda *a, **k: _live())
    out = M.wait_for_effect(_AC(), None, kwargs={}, want="denied_by_iam", phase="p", max_s=300)
    assert out["reached"] is True
    assert out["flapped_before_converging"] is True, (
        "a wanted outcome before the final streak is a fact about convergence and belongs in the "
        "record, not smoothed away")
    assert out["n_wanted_outcomes_before_the_final_streak"] == 1


def test_the_propagation_wait_returns_rather_than_raising_on_a_timeout(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([ACCEPTED]))
    monkeypatch.setattr(M, "wait_ready", lambda *a, **k: _live())
    out = M.wait_for_effect(_AC(), None, kwargs={}, want="denied_by_iam", phase="p", max_s=20)
    assert out["reached"] is False
    assert out["max_wait_s"] == 20
    assert out["outcomes_seen"], "the series is the evidence about what IAM was doing"


def test_the_probe_trials_cannot_be_confused_with_an_arm(monkeypatch):
    """A converging sequence must never be counted as evidence about the boundary."""
    cap = _Cap([DENIED])
    monkeypatch.setattr(M, "capture", cap)
    monkeypatch.setattr(M, "wait_ready", lambda *a, **k: _live())
    M.wait_for_effect(_AC(), None, kwargs={}, want="denied_by_iam", phase="attach_x", max_s=300)
    assert 'trial_id=f"probe__{phase}"' in SRC
    for arm in M.ARMS:
        assert f"probe__{arm}" not in SRC


def test_the_detach_wait_gets_a_longer_bound_than_an_attach():
    """A ceiling that has not lifted is not a hole, so patience there is the cheap direction."""
    assert M.PROP_MAX_REMOVE_S > M.PROP_MAX_S
    assert "max_s=PROP_MAX_REMOVE_S" in SRC


def test_simulate_reads_each_action_separately(monkeypatch):
    """One call per action, because the point is to tell WHICH one is outside the ceiling."""
    cap = _Cap({"simulate_principal_policy": _rec(
        "simulate_principal_policy",
        response={"EvaluationResults": [{"EvalDecision": "implicitDeny",
                                         "MatchedStatements": [],
                                         "PermissionsBoundaryDecisionDetail":
                                             {"AllowedByPermissionsBoundary": False}}]})})
    monkeypatch.setattr(M, "capture", cap)
    out = M.simulate(None, None, role_arn=ATTACKER_ROLE_ARN,
                     actions=(M.ACTION_UPDATE, M.ACTION_PASSROLE), resource_arns=[GW_ARN],
                     phase="x")
    sent = [p["ActionNames"] for p in cap.params_for("simulate_principal_policy")]
    assert sent == [[M.ACTION_UPDATE], [M.ACTION_PASSROLE]], (
        "batching the actions into one call would return one aggregate decision and lose the "
        "distinction the arm exists for")
    assert out["per_action"][M.ACTION_UPDATE]["allowed"] is False
    assert "not an authorization event" in out["is_corroborating_not_decisive"]


def test_a_failed_simulation_is_recorded_as_a_failed_read(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap({"simulate_principal_policy": _rec(
        "simulate_principal_policy", ok=False, error_code="AccessDenied")}))
    out = M.simulate(None, None, role_arn=ATTACKER_ROLE_ARN, actions=(M.ACTION_UPDATE,),
                     resource_arns=[GW_ARN], phase="x")
    assert out["read_ok"] is False
    assert out["per_action"][M.ACTION_UPDATE]["error_code"] == "AccessDenied"


# ===========================================================================
# the mutations: ledger first
# ===========================================================================

def test_the_grant_is_recorded_in_the_ledger_before_it_is_created(monkeypatch):
    """`finally` is not a watchdog — SIGKILL skips it.

    A stale ledger entry costs one NoSuchEntity at teardown; a created grant with no entry is a
    permanent unattended UpdateGateway on the identity whose whole purpose is to lack it.
    """
    st = _State()
    order: list[str] = []

    def _script(op, params):
        order.append(op)
        return _rec(op)
    monkeypatch.setattr(M, "capture", _Cap([_script]))
    M.put_grant(None, None, st, role_name=ROLE, policy_name=GRANT, document={"x": 1})
    assert st.order[:2] == ["record:f53b_grant", "write"]
    assert order == ["put_role_policy"]
    res = st.recorded[0]
    assert res.delete_op == "delete_role_policy"
    assert res.delete_params == {"RoleName": ROLE, "PolicyName": GRANT}


def test_a_failed_grant_refuses_because_the_oracle_needs_the_identity_policy(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap([_rec("put_role_policy", ok=False,
                                                 error_code="MalformedPolicyDocument")]))
    with pytest.raises(M.ConfigError) as exc:
        M.put_grant(None, None, _State(), role_name=ROLE, policy_name=GRANT, document={})
    assert "despite an identity policy granting it" in str(exc.value)


def test_the_boundary_policy_is_recorded_with_its_arn_and_tagged(monkeypatch):
    st = _State()
    monkeypatch.setattr(M, "capture", _Cap({"create_policy": _rec(
        "create_policy", response={"Policy": {"Arn": BOUNDARY_ARN}})}))
    tags = [{"Key": "Project", "Value": "guardrails-doc-validation"}]
    out = M.create_boundary_policy(None, None, st, name="n", logical="f53b_x",
                                  document={"Statement": []}, tag_list=tags, description="d")
    assert out["policy_arn"] == BOUNDARY_ARN
    res = st.recorded[0]
    assert res.kind == "iam-policy" and res.arn == BOUNDARY_ARN
    assert res.delete_params == {"PolicyArn": BOUNDARY_ARN}


def test_a_create_policy_that_returns_no_arn_refuses_loudly(monkeypatch):
    """The worst case: a managed policy may exist that this run cannot name to delete."""
    monkeypatch.setattr(M, "capture", _Cap({"create_policy": _rec("create_policy",
                                                                  response={"Policy": {}})}))
    with pytest.raises(M.ConfigError) as exc:
        M.create_boundary_policy(None, None, _State(), name="n", logical="l",
                                 document={}, tag_list=[], description="d")
    assert "cannot name to delete" in str(exc.value)


def test_the_attachment_is_recorded_before_it_is_made_and_runs_first_at_teardown(monkeypatch):
    """A policy still serving as a boundary cannot be deleted, so the detach must run first.

    `infra/99_teardown.py` orders by `delete_priority` ascending, so the attachment's entry has
    to sort BEFORE the managed policy's or teardown deadlocks on its own ordering.
    """
    st = _State()
    order: list[str] = []

    def _script(op, params):
        order.append(op)
        return _rec(op)
    monkeypatch.setattr(M, "capture", _Cap([_script]))
    M.attach_boundary(None, None, st, role_name=ROLE, policy_arn=BOUNDARY_ARN, logical="f53b_x")
    assert st.order[:2] == ["record:f53b_x", "write"]
    assert order == ["put_role_permissions_boundary"]
    attach = st.recorded[0]
    assert attach.delete_op == "delete_role_permissions_boundary"
    assert attach.delete_params == {"RoleName": ROLE}

    st2 = _State()
    monkeypatch.setattr(M, "capture", _Cap({"create_policy": _rec(
        "create_policy", response={"Policy": {"Arn": BOUNDARY_ARN}})}))
    M.create_boundary_policy(None, None, st2, name="n", logical="f53b_x", document={},
                             tag_list=[], description="d")
    assert attach.delete_priority < st2.recorded[0].delete_priority, (
        "the detach must sort before the policy delete; otherwise teardown tries to delete a "
        "policy that is still in use and reports FAILED on its own ordering")


def test_a_failed_attach_refuses_rather_than_measuring_an_absent_boundary(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap({"put_role_permissions_boundary": _rec(
        "put_role_permissions_boundary", ok=False, error_code="NoSuchEntity")}))
    with pytest.raises(M.ConfigError) as exc:
        M.attach_boundary(None, None, _State(), role_name=ROLE, policy_arn=BOUNDARY_ARN,
                          logical="l")
    assert "no boundary is in force" in str(exc.value)


# ===========================================================================
# teardown — including THE LYING DOUBLE
# ===========================================================================

def _detach_script(*, delete_ok=True, delete_code="", boundary_after=None):
    return {
        "delete_role_permissions_boundary": (
            _rec("delete_role_permissions_boundary") if delete_ok
            else _rec("delete_role_permissions_boundary", ok=False, error_code=delete_code)),
        "get_role": _rec("get_role", response={"Role": {
            "RoleName": ROLE,
            **({"PermissionsBoundary": {"PermissionsBoundaryArn": boundary_after,
                                        "PermissionsBoundaryType": "Policy"}}
               if boundary_after else {})}}),
    }


def test_a_detach_is_verified_by_reading_the_role_back(monkeypatch):
    st = _State()
    st.record(T.Resource(kind="iam-permissions-boundary", logical="f53b_x", name=ROLE,
                         service="iam", delete_op="delete_role_permissions_boundary",
                         delete_params={"RoleName": ROLE}))
    cap = _Cap(_detach_script())
    monkeypatch.setattr(M, "capture", cap)
    out = M.detach_boundary(None, None, st, role_name=ROLE, logical="f53b_x")
    assert out["detached"] is True
    assert "get_role" in cap.ops, (
        "DeleteRolePermissionsBoundary returning 200 is an acknowledgement; the answer to 'is it "
        "gone' has to come from GetRole")
    assert "drop:iam-permissions-boundary/f53b_x" in st.order


def test_the_lying_double_a_detach_that_returns_200_while_the_boundary_is_still_there(monkeypatch):
    """THE branch that protects the whole testbed, and a double that always tells the truth
    never reaches it.

    `DeleteRolePermissionsBoundary` answers 200 and `GetRole` still reports the boundary. That is
    the one shape under which a script trusting the status code leaves `grx-attacker` with an
    altered ceiling and reports a clean run — after which every F5-1 and F5-2 replication is
    over-determined and nothing in the repo reads the boundary to notice.
    """
    st = _State()
    monkeypatch.setattr(M, "capture", _Cap(_detach_script(boundary_after=BOUNDARY_ARN)))
    out = M.detach_boundary(None, None, st, role_name=ROLE, logical="f53b_x")
    assert out["detached"] is False, (
        "the delete succeeded and the boundary is still attached; trusting the 200 is exactly the "
        "failure this read-back exists for")
    assert out["read_back"]["attached"] is True
    assert "delete-role-permissions-boundary" in out["manual_remedy"]
    assert "every future F5-1/F5-2 replication" in out["manual_remedy"], (
        "the remedy has to say why it matters, or nobody acts on it")
    assert "drop:iam-permissions-boundary/f53b_x" not in st.order, (
        "the ledger entry must SURVIVE a failed detach: it is the channel teardown uses to try "
        "again from another process")


def test_a_get_role_that_failed_during_teardown_is_not_a_clean_detach(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap({
        "delete_role_permissions_boundary": _rec("delete_role_permissions_boundary"),
        "get_role": _rec("get_role", ok=False, error_code="ServiceFailure")}))
    out = M.detach_boundary(None, None, _State(), role_name=ROLE, logical="f53b_x")
    assert out["detached"] is False, (
        "a boundary we could not look at is not a boundary we know is gone")


def test_no_such_entity_on_the_detach_is_the_state_we_wanted(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap(_detach_script(delete_ok=False,
                                                          delete_code="NoSuchEntity")))
    out = M.detach_boundary(None, None, _State(), role_name=ROLE, logical="f53b_x")
    assert out["detached"] is True, "a role with no boundary is the goal, however it got there"


def test_the_detach_retries_before_giving_up(monkeypatch):
    calls = {"n": 0}

    def _script(op, params):
        if op == "delete_role_permissions_boundary":
            calls["n"] += 1
            return _rec(op, ok=False, error_code="ServiceFailure")
        return _rec("get_role", response={"Role": {"RoleName": ROLE}})
    monkeypatch.setattr(M, "capture", _Cap([_script]))
    M.detach_boundary(None, None, _State(), role_name=ROLE, logical="l")
    assert calls["n"] == M.DELETE_ATTEMPTS


def test_deleting_the_boundary_policy_retries_and_treats_absence_as_success(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap({"delete_policy": _rec(
        "delete_policy", ok=False, error_code="NoSuchEntity")}))
    out = M.delete_boundary_policy(None, None, _State(), policy_arn=BOUNDARY_ARN, logical="l")
    assert out["deleted"] is True

    calls = {"n": 0}

    def _fail(op, params):
        calls["n"] += 1
        return _rec(op, ok=False, error_code="DeleteConflict")
    monkeypatch.setattr(M, "capture", _Cap([_fail]))
    out = M.delete_boundary_policy(None, None, _State(), policy_arn=BOUNDARY_ARN, logical="l")
    assert out["deleted"] is False and calls["n"] == M.DELETE_ATTEMPTS
    assert BOUNDARY_ARN in out["manual_remedy"]


def test_deleting_the_grant_retries_and_names_the_remedy(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap({"delete_role_policy": _rec(
        "delete_role_policy", ok=False, error_code="ServiceFailure")}))
    out = M.delete_grant(None, None, _State(), role_name=ROLE, policy_name=GRANT)
    assert out["deleted"] is False
    assert ROLE in out["manual_remedy"] and GRANT in out["manual_remedy"]


def test_the_in_boundary_control_is_a_real_call_whose_failure_is_data(monkeypatch):
    monkeypatch.setattr(M, "capture", _Cap({"get_gateway": _rec("get_gateway", ok=False,
                                                                error_code="AccessDenied")}))
    out = M.in_boundary_control(None, None, gateway_id=GW_ID, arm="x")
    assert out["ok"] is False and out["error_code"] == "AccessDenied"
    assert "inside the ceiling" in out["why"]


# ===========================================================================
# residue, from two lists plus the read-back state
# ===========================================================================

CLEAN_BOUNDARY = {"read_ok": True, "attached": False, "boundary_arn": None}


def test_residue_reports_a_survivor_whose_removal_was_never_attempted():
    """The circularity the two-list form exists to avoid.

    The process was killed between the attach and the `finally`, so the boundary contributes no
    row to the removals — and a residue computed from that list alone would call this clean while
    `grx-attacker`'s ceiling is still altered.
    """
    created = [{"id": "boundary:deny"}, {"id": f"policy:{BOUNDARY_ARN}"}]
    removed = [{"id": f"policy:{BOUNDARY_ARN}", "removed": True}]
    res = M.residue(created, removed, boundary_at_end=CLEAN_BOUNDARY,
                    inline_at_end=[M.BASELINE_INLINE])
    assert res["surviving"] == ["boundary:deny"]
    assert res["never_attempted"] == ["boundary:deny"]
    assert res["clean"] is False


def test_residue_is_not_clean_while_the_role_still_carries_a_boundary():
    """The read-back STATE is decisive, not the bookkeeping.

    Both lists can balance — every removal attempted and reported successful — and the role can
    still carry a boundary, because a successful-looking API call is not a state.
    """
    created = [{"id": "boundary:deny"}]
    removed = [{"id": "boundary:deny", "removed": True}]
    res = M.residue(created, removed,
                    boundary_at_end={"read_ok": True, "attached": True,
                                     "boundary_arn": BOUNDARY_ARN},
                    inline_at_end=[M.BASELINE_INLINE])
    assert res["surviving"] == []
    assert res["boundary_still_attached"] is True
    assert res["clean"] is False


def test_a_failed_read_back_is_residue_and_not_cleanliness():
    res = M.residue([], [], boundary_at_end={"read_ok": False, "attached": None},
                    inline_at_end=None)
    assert res["boundary_still_attached"] is None
    assert res["unexpected_inline_policies"] is None
    assert res["clean"] is False, (
        "a boundary we could not look at is not a boundary we know is gone")


def test_a_surviving_grant_is_residue():
    res = M.residue([], [], boundary_at_end=CLEAN_BOUNDARY,
                    inline_at_end=[M.BASELINE_INLINE, GRANT])
    assert res["unexpected_inline_policies"] == [GRANT]
    assert res["clean"] is False


def test_residue_is_clean_only_when_every_channel_agrees():
    created = [{"id": "boundary:deny"}, {"id": f"policy:{BOUNDARY_ARN}"},
               {"id": f"inline:{GRANT}"}]
    removed = [{"id": i["id"], "removed": True} for i in created]
    res = M.residue(created, removed, boundary_at_end=CLEAN_BOUNDARY,
                    inline_at_end=[M.BASELINE_INLINE])
    assert res["clean"] is True
    assert res["n_created"] == 3 and res["n_removed"] == 3


# ===========================================================================
# the guards
# ===========================================================================

def _arm(reading, *, n=5):
    rows = {"DENIED": [{"outcome": "denied_by_iam"}] * n,
            "AUTHORIZED": [{"outcome": "accepted"}] * n,
            "SPLIT": [{"outcome": "accepted"}, {"outcome": "denied_by_iam"}],
            "NOTHING_USABLE": [{"outcome": "unusable"}] * n}[reading]
    return M.tally("a", rows)


def _clean_arms():
    return {M.ARM_PRE_GRANT: _arm("DENIED", n=2),
            M.ARM_GRANTED: _arm("AUTHORIZED", n=3),
            M.ARM_BOUNDARY_DENY: _arm("DENIED"),
            M.ARM_BOUNDARY_OMIT: _arm("DENIED"),
            M.ARM_REMOVED: _arm("AUTHORIZED", n=3)}


def _clean_kwargs(**over):
    kw = dict(
        interlock_role={"inline_policies_at_start": [M.BASELINE_INLINE],
                        "attached_managed_policies_at_start": [],
                        "permissions_boundary_at_start": None},
        interlock_gateway={"engine_arn_matches_ledger": True},
        arms=_clean_arms(),
        propagation={"grant": {"reached": True},
                     f"attach_{M.ARM_BOUNDARY_DENY}": {"reached": True},
                     f"attach_{M.ARM_BOUNDARY_OMIT}": {"reached": True},
                     "detach": {"reached": True}},
        controls={a: {"ok": True} for a in M.BOUNDARY_ARMS},
        res={"boundary_still_attached": False, "surviving": [],
             "unexpected_inline_policies": []},
        gateway_read_ok=True, gateway_diff=[], pec_identical=True)
    kw.update(over)
    return kw


def test_a_clean_run_passes_every_guard():
    g = M.guards(**_clean_kwargs())
    assert all(g.values()), [k for k, v in g.items() if not v]
    assert set(g) == set(M.GUARDS)


def test_the_guard_names_here_match_the_shipped_tuple_and_are_all_computed():
    g = M.guards(**_clean_kwargs())
    assert set(M.GUARDS) == set(g)
    for name in M.GUARDS:
        assert f'"{name}":' in SRC, f"{name} is declared in GUARDS but never computed"


def test_the_positive_control_gate_is_what_stops_the_intersection_hazard():
    """A boundary arm full of denials with no accepted control must NOT publish.

    Without this gate, a role that simply never had UpdateGateway produces a perfect-looking
    TRUE — which is a statement about infra/01_iam.py, not about the boundary.
    """
    arms = {**_clean_arms(), M.ARM_GRANTED: _arm("DENIED", n=3)}
    g = M.guards(**_clean_kwargs(arms=arms))
    assert g["the_attack_succeeded_before_any_boundary_existed"] is False
    assert 'if not g["the_attack_succeeded_before_any_boundary_existed"]:' in SRC
    assert "consistent with a request IAM refused to look at" in SRC, (
        "the NOT_MEASURED reason must say which way the instrument failed")


def test_a_conflict_alone_satisfies_the_positive_control():
    """A ConflictException means IAM said yes; the gate asks about authorization, not effect."""
    arms = {**_clean_arms(), M.ARM_GRANTED: M.tally("a", [{"outcome": "conflict"}])}
    g = M.guards(**_clean_kwargs(arms=arms))
    assert g["the_attack_succeeded_before_any_boundary_existed"] is True


def test_the_sealed_mutation_gate_fails_when_detaching_did_not_reopen_the_route():
    arms = {**_clean_arms(), M.ARM_REMOVED: _arm("DENIED", n=3)}
    g = M.guards(**_clean_kwargs(arms=arms))
    assert g["removing_the_boundary_reopened_the_route"] is False
    assert 'if not g["removing_the_boundary_reopened_the_route"]' in SRC
    assert "not attributable to the boundary" in SRC


def test_a_missing_arm_is_a_failure_and_not_an_absent_pass():
    """`all([])` over arms that never ran would pass. Enumerated keys prevent that."""
    g = M.guards(**_clean_kwargs(arms={}))
    assert g["the_attack_succeeded_before_any_boundary_existed"] is False
    assert g["removing_the_boundary_reopened_the_route"] is False


@pytest.mark.parametrize("prop", [
    {},
    {"grant": {"reached": True}, "detach": {"reached": False}},
    {"grant": {"reached": False}},
])
def test_an_unconfirmed_transition_fails_its_own_guard(prop):
    g = M.guards(**_clean_kwargs(propagation=prop))
    assert g["every_boundary_transition_was_observed_to_settle"] is False


@pytest.mark.parametrize("controls", [
    {},
    {M.ARM_BOUNDARY_DENY: {"ok": True}},
    {M.ARM_BOUNDARY_DENY: {"ok": True}, M.ARM_BOUNDARY_OMIT: {"ok": False}},
])
def test_a_missing_or_failed_in_boundary_control_fails_its_guard(controls):
    """A broken credential must not read as the boundary working."""
    g = M.guards(**_clean_kwargs(controls=controls))
    assert g["an_in_boundary_action_still_worked_under_each_boundary"] is False


@pytest.mark.parametrize("over", [
    {"gateway_read_ok": False},
    {"gateway_diff": ["exceptionLevel"]},
    {"pec_identical": False},
    {"gateway_diff": None},
])
def test_the_gateway_guard_fails_each_way_the_gateway_could_have_been_left_wrong(over):
    g = M.guards(**_clean_kwargs(**over))
    assert g["gateway_was_left_field_for_field_identical"] is False


def test_the_restore_ignore_list_is_the_pairing_rule_minus_the_field_this_case_watches():
    """`policyEngineConfiguration` must be compared, not ignored.

    `PAIR_IGNORE` exists to answer "does anything ELSE differ" for F6's pair. Here the claim is
    that NOTHING differs, and the engine configuration is the field a no-op full-replacement body
    could most plausibly have dropped.
    """
    assert "policyEngineConfiguration" in M.PAIR_IGNORE
    assert "policyEngineConfiguration" not in M.RESTORE_IGNORE
    assert set(M.RESTORE_IGNORE) | {"policyEngineConfiguration"} == set(M.PAIR_IGNORE)
    # And the diff actually notices, in both directions: a changed field is reported, and the
    # engine configuration is not exempt from it.
    before, after = _live(), _live(exceptionLevel="DEFAULT")
    diff = M.diff_configs(before, after, ignore=M.RESTORE_IGNORE)
    assert len(diff) == 1 and diff[0].startswith("exceptionLevel"), diff
    moved = _live(policyEngineConfiguration={"arn": ENGINE_ARN, "mode": "LOG_ONLY"})
    pec_diff = M.diff_configs(_live(), moved, ignore=M.RESTORE_IGNORE)
    assert any(d.startswith("policyEngineConfiguration") for d in pec_diff), (
        "with policyEngineConfiguration left in the ignore list this comparison would be blind "
        "to a gateway left in the wrong mode — the one field a no-op replacement body could most "
        "plausibly have dropped")
    assert M.diff_configs(_live(), _live(), ignore=M.RESTORE_IGNORE) == [], (
        "two identical reads must diff to nothing, or the guard can never pass")


def test_the_boundary_guard_fails_while_the_role_still_carries_one():
    g = M.guards(**_clean_kwargs(res={"boundary_still_attached": True, "surviving": [],
                                      "unexpected_inline_policies": []}))
    assert g["boundary_was_detached_and_the_role_read_back_clean"] is False


# ===========================================================================
# the verdict
# ===========================================================================

def test_observed_bool_is_the_and_over_both_boundary_forms():
    both = M.boundary_reading({M.ARM_BOUNDARY_DENY: _arm("DENIED"),
                               M.ARM_BOUNDARY_OMIT: _arm("DENIED")})
    assert both["all_forms_blocked"] is True and both["any_form_ineffective"] is False

    only_deny = M.boundary_reading({M.ARM_BOUNDARY_DENY: _arm("DENIED"),
                                    M.ARM_BOUNDARY_OMIT: _arm("AUTHORIZED")})
    assert only_deny["all_forms_blocked"] is False, (
        "an explicit Deny holding while the intersection rule does not is the most interesting "
        "outcome this case can produce, and it is the sealed FALSE — not a pass")
    assert only_deny["any_form_ineffective"] is True
    assert only_deny["per_form"][M.ARM_BOUNDARY_OMIT] == "AUTHORIZED"


def test_a_missing_boundary_arm_is_not_a_block():
    r = M.boundary_reading({M.ARM_BOUNDARY_DENY: _arm("DENIED")})
    assert r["per_form"][M.ARM_BOUNDARY_OMIT] == "MISSING"
    assert r["all_forms_blocked"] is False


def test_existence_evaluate_reads_both_directions_through_the_sealed_oracle():
    ok = P.obs_existence("F5-3b", True, n=10)
    ok.mutation_inverted = True
    assert O.evaluate(ok)["verdict"] == O.TRUE

    bad = P.obs_existence("F5-3b", False, n=10)
    bad.mutation_inverted = False
    rec = O.evaluate(bad)
    assert rec["verdict"] == O.FALSE, "an ineffective boundary is the sealed FALSE"
    assert any("not load-bearing" in n for n in rec["notes"]), (
        "when the boundary was ineffective its removal changed nothing, and `evaluate` should say "
        "so rather than leaving a reader to work it out")


def test_mutation_inverted_is_set_as_an_attribute_not_passed_as_a_keyword():
    """The F5-1 defect, pinned: as a keyword the value lands where the rule never looks."""
    assert "obs.mutation_inverted = " in SRC
    assert "mutation_inverted=" not in SRC, "the keyword spelling is the F5-1 bug"
    with pytest.raises(TypeError) as exc:
        P.obs_existence("F5-3b", True, n=1, mutation_inverted=True)
    assert "not free-form detail" in str(exc.value)


def test_the_inversion_flag_needs_both_halves():
    """It is a DIFFERENCE between arms, not a property of one."""
    assert 'reading["all_forms_blocked"]' in SRC
    assert 'arms.get(ARM_REMOVED, {}).get("n_authorized", 0) > 0' in SRC


def test_the_denominator_comes_from_the_boundary_arms_alone():
    """`feedback_two_numbers_two_claims`.

    The control arms are DESIGNED to be authorized; folding them into `n` would denominate a
    security claim with calls whose purpose was to succeed.
    """
    assert 'n=sum(arms.get(a, {}).get("n_usable", 0) for a in BOUNDARY_ARMS)' in SRC
    for other in (M.ARM_GRANTED, M.ARM_REMOVED, M.ARM_PRE_GRANT):
        assert f'n=arms["{other}"]' not in SRC


def test_evaluate_is_called_with_the_observation_alone():
    assert "O.evaluate(obs)" in SRC
    assert "O.evaluate(CASE" not in SRC


# ===========================================================================
# the narrative, both branches
# ===========================================================================

REQUIRED_KEYS = ("verdict_rule", "verdict_reading", "what_true_does_not_prove",
                 "why_this_matters_operationally", "expiry")


def test_the_payload_carries_the_five_required_sentences_in_both_directions():
    prop = {"attach_x": {"seconds": 41.0}}
    for arms in ({M.ARM_BOUNDARY_DENY: _arm("DENIED"), M.ARM_BOUNDARY_OMIT: _arm("DENIED")},
                 {M.ARM_BOUNDARY_DENY: _arm("DENIED"), M.ARM_BOUNDARY_OMIT: _arm("AUTHORIZED")},
                 {M.ARM_BOUNDARY_DENY: _arm("SPLIT"), M.ARM_BOUNDARY_OMIT: _arm("SPLIT")}):
        narr = M.narrative(reading=M.boundary_reading(arms), arms=arms, propagation=prop,
                           sdk="1.43.32")
        assert set(narr) == set(REQUIRED_KEYS)
        for k, v in narr.items():
            assert isinstance(v, str) and len(v) > 40, f"{k} is not a sentence"


def test_the_false_branch_of_the_narrative_is_written_and_says_what_it_means():
    arms = {M.ARM_BOUNDARY_DENY: _arm("AUTHORIZED"), M.ARM_BOUNDARY_OMIT: _arm("AUTHORIZED")}
    narr = M.narrative(reading=M.boundary_reading(arms), arms=arms, propagation={}, sdk="x")
    assert "did NOT stop the call" in narr["verdict_reading"]
    assert "sealed FALSE" in narr["verdict_reading"], (
        "a FALSE here refutes §4's backstop; the record must not read as a neutral observation")


def test_what_true_does_not_prove_names_the_limits_a_reader_would_otherwise_assume():
    arms = {a: _arm("DENIED") for a in M.BOUNDARY_ARMS}
    narr = M.narrative(reading=M.boundary_reading(arms), arms=arms, propagation={}, sdk="x")
    text = narr["what_true_does_not_prove"]
    for needle in ("F5-3c", "policy-engine mutations", "break-glass"):
        assert needle in text, f"the limits paragraph does not mention {needle!r}"


def test_the_operational_paragraph_reports_the_measured_settle_delays():
    """The delay is one of this case's findings, so it has to reach the payload."""
    arms = {a: _arm("DENIED") for a in M.BOUNDARY_ARMS}
    narr = M.narrative(reading=M.boundary_reading(arms), arms=arms,
                       propagation={"attach_boundary_denies": {"seconds": 37.5}}, sdk="x")
    assert "37.5" in narr["why_this_matters_operationally"]
    assert "200" in narr["why_this_matters_operationally"], (
        "the point is that the API returning 200 is not the ceiling being in force")


# ===========================================================================
# exit codes and the shape of main()
# ===========================================================================

def test_the_script_cannot_exit_zero_while_residue_remains():
    """`rc` is about whether the run left the account as it found it, not about the verdict."""
    tail = SRC[SRC.index('if not res["clean"]:'):]
    assert "return 2" in tail
    assert tail.index("return 2") < tail.index("return 0"), (
        "the residue check must come BEFORE the success return, or a surviving boundary exits 0")
    # And there is exactly one `return 0`, so no other path can reach it.
    assert SRC.count("    return 0\n") == 1


def test_every_refusal_path_returns_two_and_emits_a_record():
    """A case with no file in results/phase1/ is indistinguishable from a case nobody ran."""
    assert SRC.count("O.not_measured(") == 5, (
        "the not-measured paths are: incomplete ledger, no engine, a ConfigError, a failed "
        "positive control, and a mutation that did not invert. A new one needs an arm here")
    for reason in ("incomplete ledger", "no engine", "config_error",
                   "the positive control did not succeed",
                   "the sealed mutation did not invert"):
        assert reason in SRC


def test_the_script_never_deletes_the_gateway_the_engine_or_a_role():
    for forbidden in ("delete_gateway", "delete_policy_engine", "delete_role",
                      "update_gateway_target", "delete_gateway_target"):
        # `delete_role_policy` and `delete_role_permissions_boundary` are ours and start with
        # `delete_role`, so the check is on the exact call spelling.
        assert f'capture(store, "{forbidden}"' not in SRC, (
            f"{forbidden} must never appear: this case borrows the gateway and the engine and "
            f"owns neither")


def test_the_nopolicy_gateway_is_never_named():
    assert "nopolicy" not in SRC.replace("`nopolicy`", ""), (
        "F6's paired baseline is out of scope; the only mention allowed is prose")


# ===========================================================================
# the dry run, as a subprocess
# ===========================================================================

_DRY_RUNS: dict[tuple[str, ...], str] = {}


def _dry_run(*extra):
    """The script's own `--dry-run`, in a subprocess, memoised per argument set.

    A subprocess rather than a call into `main()`: the claim is that the shipped file reaches its
    arms and prints its plan without importing anything that opens a socket, and an in-process
    call would inherit this file's monkeypatches — which is precisely the state the dry run must
    not need. Memoised because each launch loads botocore's service models and parses the sealed
    pre-registration, and three arms asking the same question should not pay for it three times.
    """
    key = tuple(extra)
    if key not in _DRY_RUNS:
        r = subprocess.run([PY, str(SCRIPT), "--dry-run", *extra], cwd=ROOT,
                           capture_output=True, text=True, check=False)
        assert r.returncode == 0, r.stderr
        _DRY_RUNS[key] = r.stdout
    return _DRY_RUNS[key]


def test_the_dry_run_makes_no_aws_call_and_declares_its_mutations():
    out = _dry_run()
    assert "F5-3b dry run — no AWS call, no mutation" in out
    assert f"mutations: {M.MAX_MUTATIONS}" in out
    assert "billable text units: 0" in out or "billable text-unit sources: ~0" in out
    assert "TRUE if UpdateGateway is denied despite an identity policy granting it" in out
    for arm in M.ARMS:
        assert arm in out


def test_the_dry_run_total_matches_the_arms_it_prints():
    """`dry_run_banner` raises if `operations` does not sum to the arm plan.

    So this pins that the operation breakdown is derived from the same numbers the arms are —
    a label naming one operation over a total spanning two is the defect that argument exists
    for.
    """
    out = _dry_run()
    total = sum(M.N_PER_ARM.values())
    assert f"total calls: {total}" in out
    assert f"bedrock-agentcore:UpdateGateway x{total}" in out


def test_a_smoke_run_shrinks_every_arm():
    out = _dry_run("--n", "1")
    assert "n=1" in out
    assert f"n={M.N_BOUNDARY}" not in out, (
        "--n must shrink the boundary arms too; a smoke run that still sent 5 attempts per "
        "boundary would not be a smoke run")


def test_the_dry_run_states_the_teardown_contract():
    out = _dry_run()
    assert "rc=2 if anything survives" in out
    assert "MANAGED POLICY ARN" in out, (
        "a reader needs to know this case creates two managed policies, which the sealed method "
        "('permissions boundary on grx-attacker') does not imply")
