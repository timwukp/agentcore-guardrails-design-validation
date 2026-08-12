#!/usr/bin/env python3
"""F5-4a's arms must differ only in the policy, and its interlock must be able to refuse.

This case's oracle is `RECORDED` — no threshold, no prediction, the observation IS the finding.
That removes the usual safety net: there is no interval whose width would betray a broken
denominator, and no expected direction that a wrong reading would visibly contradict. Whatever
the script prints becomes the finding. So the properties that would silently corrupt it are
tested rather than reviewed:

* the interlock passing while another case's probe is live on the shared engine — which would
  not merely add load, it would deny that case's requests and destroy its data;
* a fail-open published for a policy the service had REFUSED to create, which reports the
  document's best outcome as its worst;
* the bracket arms sending a different payload from the unknown arms, making an ALLOW
  unattributable;
* the broken arms accidentally carrying a path that resolves;
* a metric already firing in the account credited to this run;
* a split arm rounded to whichever side had more trials.

None of these raise.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

_spec = importlib.util.spec_from_file_location(
    "grx_f5_04_policy_failure_modes", ROOT / "f5_redteam" / "04_policy_failure_modes.py")
M = importlib.util.module_from_spec(_spec)
sys.modules["grx_f5_04_policy_failure_modes"] = M
_spec.loader.exec_module(M)

import cedar as C     # noqa: E402
import oracle as O    # noqa: E402
import testbed as T   # noqa: E402

GW_ARN = "arn:aws:bedrock-agentcore:us-east-1:111122223333:gateway/gw-test"
ACTION = "grxecho___echo"


# ---- the oracle this script was written against ------------------------------

def test_the_binding_is_recorded_and_has_no_threshold():
    """A later re-seal that gave this case a threshold would invalidate the whole design.

    The five-way finding below is only legitimate because nothing was predicted. If the binding
    became thresholded, the script would have to decide TRUE/FALSE and this file's premise
    would be stale.
    """
    b = O.BINDINGS["F5-4a"]
    assert b.kind == "RECORDED"
    assert b.thresholds == ()
    assert O.mutation_is_mandatory("F5-4a") is False, (
        "a mandatory mutation would mean this case owes a restore-and-re-verify chain, which "
        "this script does not implement — F5-4b is the case that does")


# ---- the interlock ----------------------------------------------------------

class _State:
    """The two methods `_assert_engine_is_quiet` uses."""

    def __init__(self, logicals):
        self._rs = [T.Resource(kind="policy", logical=lg, name=f"n_{lg}",
                               service="bedrock-agentcore-control", delete_op="delete_policy",
                               delete_params={}, ids={"policy_id": f"pid-{lg}"}, arn="")
                    for lg in logicals]

    def of_kind(self, kind):
        return [r for r in self._rs if r.kind == kind]


def test_the_interlock_refuses_when_another_cases_probe_is_live():
    """Mutation-checked in both directions, per feedback_vacuous_test_check.

    The exact situation this exists for: F6-6/7/8 keeps `f6c_guardrail_probe` registered while
    it times 1600 turns. A `forbid` added to the same engine denies those turns. An interlock
    that could not fail would be a comment.
    """
    # Quiet: only the baseline permit.
    out = M._assert_engine_is_quiet(_State(["baseline"]))
    assert out["policies_on_engine_at_start"] == ["baseline"]

    # Another case's probe is live.
    with pytest.raises(M.ConfigError) as exc:
        M._assert_engine_is_quiet(_State(["baseline", "f6c_guardrail_probe"]))
    msg = str(exc.value)
    assert "f6c_guardrail_probe" in msg, "the refusal must name what it found"
    assert "destroy" in msg or "data" in msg, "the refusal must say why it matters"

    # A leftover of THIS case from a crashed run is also a refusal: it is a second forbid.
    with pytest.raises(M.ConfigError):
        M._assert_engine_is_quiet(_State(["baseline", "f54a_miss"]))
    # And an engine with no baseline at all is quiet by this test's definition — the baseline's
    # absence is a different problem, caught by the control arm being denied.
    M._assert_engine_is_quiet(_State([]))


def test_the_interlock_is_actually_called_before_any_policy_is_created():
    """A guard with no path that reaches it is not a guard (feedback_no_deploy_path_no_component).

    Read from the source order rather than by running `main`, which needs AWS: the refusal must
    appear before the first `_create_probe`, or the policy is already on the engine by the time
    the script decides not to run.
    """
    src = (ROOT / "f5_redteam" / "04_policy_failure_modes.py").read_text(encoding="utf-8")
    body = src.split("def main(", 1)[1]
    i_lock = body.index("_assert_engine_is_quiet(")
    i_create = body.index("_create_probe(")
    assert i_lock < i_create, (
        "the interlock is consulted AFTER the first policy is created; by then the damage to a "
        "concurrent case is done")


# ---- the arms differ only in the policy -------------------------------------

def test_each_arm_uses_the_path_its_name_claims():
    valid = M._statement_for(M.ARM_VALID, GW_ARN, ACTION)
    assert M.VALID_PATH in valid and M.MISSING_PATH not in valid

    for arm in (M.ARM_MISSING, M.ARM_LOGONLY):
        s = M._statement_for(arm, GW_ARN, ACTION)
        assert M.MISSING_PATH in s, f"{arm} does not carry the broken path"
        assert M.VALID_PATH not in s, (
            f"{arm} still carries the WORKING path — the arm would deny for the ordinary reason "
            f"and be published as a fail-closed on an unevaluable policy")

    assert M._statement_for(M.ARM_CONTROL, GW_ARN, ACTION) is None


def test_the_two_broken_mechanisms_are_actually_different_mechanisms():
    """§7.1 distinguishes a failing GUARDRAIL evaluation from an incomplete Cedar evaluation.

    If both arms sent a guardrails block, the run would report one mechanism twice under two
    names and claim to have covered both.
    """
    g = M._statement_for(M.ARM_MISSING, GW_ARN, ACTION)
    c = M._statement_for(M.ARM_CEDAR, GW_ARN, ACTION)
    assert "when guardrails" in g and "BedrockGuardrails::" in g
    assert "when guardrails" not in c and "BedrockGuardrails::" not in c, (
        "the Cedar arm must not contain a guardrails block")
    assert "when {" in c
    assert M.MISSING_PATH in c
    assert g != c


def test_the_valid_and_broken_guardrail_statements_differ_by_exactly_the_path():
    """The bracket only brackets if it is the same statement otherwise."""
    valid = M._statement_for(M.ARM_VALID, GW_ARN, ACTION)
    broken = M._statement_for(M.ARM_MISSING, GW_ARN, ACTION)
    assert valid.replace(M.VALID_PATH, M.MISSING_PATH) == broken, (
        "the working and broken forbids differ in more than the data path, so a difference in "
        "outcome is not attributable to the path")


def test_only_the_logonly_arm_is_log_only():
    assert M._mode_for(M.ARM_LOGONLY) == M.MODE_LOG_ONLY
    for arm in (M.ARM_CONTROL, M.ARM_VALID, M.ARM_MISSING, M.ARM_CEDAR):
        assert M._mode_for(arm) == M.MODE_ENFORCE, (
            f"{arm} is LOG_ONLY, so it cannot deny and its ALLOW would mean nothing")
    # And the LOG_ONLY arm's statement is the same broken one, so its metric reading is about
    # the same policy the ENFORCE arm ran.
    assert (M._statement_for(M.ARM_LOGONLY, GW_ARN, ACTION)
            == M._statement_for(M.ARM_MISSING, GW_ARN, ACTION))


def test_every_statement_passes_the_local_lint_and_names_the_gateway_and_action():
    """The broken arms are broken in ONE way only.

    A statement that also tripped a known Cedar trap could fail to create for that reason
    instead, and the run would report `REFUSED_AT_CREATION` about the wrong defect.
    """
    for arm in M.ARMS:
        s = M._statement_for(arm, GW_ARN, ACTION)
        if s is None:
            continue
        assert C.check_statement(s) == [], f"{arm}'s statement trips the local lint"
        assert GW_ARN in s and ACTION in s
        assert s.startswith("forbid ")


def test_the_unknown_arms_are_the_broken_ones_and_the_bracket_is_not_among_them():
    assert set(M.UNKNOWN_ARMS) == {M.ARM_MISSING, M.ARM_CEDAR}
    assert M.ARM_CONTROL not in M.UNKNOWN_ARMS and M.ARM_VALID not in M.UNKNOWN_ARMS
    assert set(M.UNKNOWN_ARMS) <= set(M.ARMS)
    assert set(M.BROKEN_ARMS) <= set(M.ARMS)
    assert M.ARM_LOGONLY in M.BROKEN_ARMS and M.ARM_LOGONLY not in M.UNKNOWN_ARMS, (
        "LOG_ONLY cannot deny, so its decision is not one of the unknowns; it is there for the "
        "metric")


def test_policy_names_fit_the_resource_constraint():
    """DEV-P2-02: `[A-Za-z][A-Za-z0-9_]*`, max 48 characters, no hyphens.

    Checked against a real 17-character run id, because a name that fits in a test's short
    fixture and not in the live one fails after the first arm has already run.
    """
    run_id = "r20260810T130945Z"
    pat = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
    for arm in M.ARMS:
        if arm == M.ARM_CONTROL:
            continue
        slug = M._slug(arm)
        for name in (f"grx_f54a_{slug}s_{run_id}", f"grx_f54a_{slug}_{run_id}"):
            assert pat.match(name), name
            assert len(name) <= 48, f"{name} is {len(name)} characters"
    slugs = [M._slug(a) for a in M.ARMS if a != M.ARM_CONTROL]
    assert len(set(slugs)) == len(slugs), (
        "two arms share a slug, so their policy names collide and the second create fails as a "
        "name conflict — which reads exactly like the validation catching the broken path")


# ---- the payload is identical across arms ----------------------------------

class _Decision:
    def __init__(self, denied):
        self.denied, self.ran, self.http_status = denied, True, 200 if not denied else 403

    def to_json(self):
        return {"denied": self.denied}


class _Client:
    def __init__(self, denied=False):
        self.calls = []
        self._denied = denied

    def call_tool(self, name, args):
        self.calls.append((name, args))
        return _Decision(self._denied)


class _CP:
    def __init__(self):
        self._r = {}

    def is_done(self, tid):
        return tid in self._r

    def results(self):
        return self._r

    def run_trial(self, tid, fn):
        self._r[tid] = fn()

    def save(self):
        pass


def test_every_arm_sends_the_identical_request(monkeypatch):
    """The claim the whole case rests on, and it is invisible in the results."""
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)
    items = [{"id": "h1", "text": "PAYLOAD-ONE"}, {"id": "h2", "text": "PAYLOAD-TWO"}]
    per_arm = {}
    for arm in M.ARMS:
        cl = _Client()
        M._run_arm(cl, _CP(), arm=arm, action_id=ACTION, items=items)
        per_arm[arm] = cl.calls
    first = per_arm[M.ARMS[0]]
    assert first == [(ACTION, {"text": "PAYLOAD-ONE"}), (ACTION, {"text": "PAYLOAD-TWO"})]
    for arm, calls in per_arm.items():
        assert calls == first, f"{arm} sent a different request from {M.ARMS[0]}"


def test_a_resumed_arm_pairs_by_item_id_and_does_not_resend(monkeypatch):
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)
    items = [{"id": "h1", "text": "a"}, {"id": "h2", "text": "b"}]
    cp = _CP()
    cl1 = _Client()
    M._run_arm(cl1, cp, arm=M.ARM_VALID, action_id=ACTION, items=items)
    assert len(cl1.calls) == 2
    cl2 = _Client()
    out = M._run_arm(cl2, cp, arm=M.ARM_VALID, action_id=ACTION, items=items)
    assert cl2.calls == [], "a completed trial was re-sent and re-billed on resume"
    assert out["n_usable"] == 2


# ---- the decision must not be averaged -------------------------------------

def test_a_split_arm_is_reported_as_split_and_not_rounded(monkeypatch):
    """E-class: the mechanism is deterministic or it is not a mechanism.

    A 12/20 arm is not "mostly denied"; it is a finding that something is nondeterministic, and
    reporting it as DENY would hide that.
    """
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)
    cp = _CP()
    cp._r = {
        "x__1": {"arm": M.ARM_MISSING, "denied": True, "http_status": 403},
        "x__2": {"arm": M.ARM_MISSING, "denied": False, "http_status": 200},
        "x__3": {"arm": M.ARM_MISSING, "denied": True, "http_status": 403},
    }
    out = M._run_arm(_Client(), cp, arm=M.ARM_MISSING, action_id=ACTION, items=[])
    assert out["decision"] == "SPLIT"
    assert out["unanimous"] is False
    assert (out["n_denied"], out["n_allowed"], out["n_usable"]) == (2, 1, 3)

    # Unanimity in each direction reads as it should.
    for denied, want in ((True, "DENY"), (False, "ALLOW")):
        cp2 = _CP()
        cp2._r = {f"y__{i}": {"arm": M.ARM_MISSING, "denied": denied, "http_status": 200}
                  for i in range(3)}
        assert M._run_arm(_Client(), cp2, arm=M.ARM_MISSING,
                          action_id=ACTION, items=[])["decision"] == want

    # An empty arm is neither.
    empty = M._run_arm(_Client(), _CP(), arm=M.ARM_MISSING, action_id=ACTION, items=[])
    assert empty["decision"] == "SPLIT" and empty["unanimous"] is False, (
        "a zero-trial arm must not read as ALLOW; nothing was observed")


def test_an_arms_tally_ignores_other_arms_rows(monkeypatch):
    cp = _CP()
    cp._r = {
        "a__1": {"arm": M.ARM_VALID, "denied": True, "http_status": 403},
        "b__1": {"arm": M.ARM_MISSING, "denied": False, "http_status": 200},
    }
    out = M._run_arm(_Client(), cp, arm=M.ARM_VALID, action_id=ACTION, items=[])
    assert (out["n_usable"], out["n_denied"]) == (1, 1)
    assert out["decision"] == "DENY"


# ---- the finding -----------------------------------------------------------

def test_a_policy_the_service_refused_is_never_published_as_a_fail_open():
    """The single most damaging misreading available to this case.

    "Refused at creation" is the document's BEST outcome: the trap is caught before it reaches
    production. At the gateway it looks identical to a fail-open, because in both cases the
    request is allowed. Consulting the decision first would report the best case as the worst.
    """
    refused = {"outcome": "refused_at_creation"}
    assert M._finding(refused, {"decision": "ALLOW"}) == "REFUSED_AT_CREATION"
    assert M._finding(refused, {"decision": "DENY"}) == "REFUSED_AT_CREATION"

    failed = {"outcome": "create_failed"}
    assert M._finding(failed, {"decision": "ALLOW"}) == "CREATE_FAILED"

    active = {"outcome": "active"}
    assert M._finding(active, {"decision": "ALLOW"}) == "FAIL_OPEN"
    assert M._finding(active, {"decision": "DENY"}) == "FAIL_CLOSED"
    assert M._finding(active, {"decision": "SPLIT"}) == "SPLIT_OR_UNUSABLE"
    assert M._finding({}, {}) == "SPLIT_OR_UNUSABLE", "an absent arm must not read as allowed"
    assert set(M.FINDINGS) == {
        M._finding(refused, {}), M._finding(failed, {}),
        M._finding(active, {"decision": "ALLOW"}), M._finding(active, {"decision": "DENY"}),
        M._finding(active, {"decision": "SPLIT"})}, (
        "FINDINGS enumerates a value `_finding` cannot return, or vice versa")


# ---- metric attribution ----------------------------------------------------

def test_a_metric_already_firing_in_the_account_is_not_credited_to_this_run():
    """`AWS/Bedrock-AgentCore` is account-wide and this account runs other people's agents.

    Mutation-checked in all four directions: the `ambient` branch must win over `exercised`,
    or another team's broken policy becomes our finding.
    """
    assert M._metric_verdict({"sum": 0.0}, {"sum": 0.0}) == "absent"
    assert M._metric_verdict({"sum": 0.0}, {"sum": 4.0}) == "exercised"
    assert M._metric_verdict({"sum": 2.0}, {"sum": 9.0}) == "ambient"
    assert M._metric_verdict({"sum": 2.0}, {"sum": 0.0}) == "ambient", (
        "a metric firing BEFORE the probe is ambient whatever happened after")


def test_the_metrics_read_are_the_four_f7_3_could_not_exercise():
    """The point of reading them at all. If this list drifts, the F7-3 link is a claim with no
    data behind it."""
    assert set(M.MISMATCH_METRICS) == {
        "MismatchErrors", "TotalMismatchedPolicies", "PolicyMismatch", "LogOnlyEvalIncomplete"}
    src = (ROOT / "f7_observability" / "03_metrics_existence.py").read_text(encoding="utf-8")
    for m in M.MISMATCH_METRICS:
        assert f'("{m}", EX_NONE' in src, (
            f"{m} is no longer NOT_EXERCISED in F7-3, so this case's claim to retire it is "
            f"stale — re-read F7-3 before citing it")
    assert M.NS == "AWS/Bedrock-AgentCore"


def test_metric_absence_is_reported_as_bounded_rather_than_proven():
    """A bounded poll that reported plain absence would be a claim the design cannot support."""
    src = (ROOT / "f5_redteam" / "04_policy_failure_modes.py").read_text(encoding="utf-8")
    assert "absence_is_bounded_not_proven" in src
    assert "still_absent_at_bound" in src
    assert M.METRIC_POLL_MAX_S > 0 and M.METRIC_POLL_EVERY_S > 0
    assert M.METRIC_POLL_EVERY_S < M.METRIC_POLL_MAX_S, "the poll would run exactly once"


# ---- guards ----------------------------------------------------------------

def test_guard_names_match_what_main_computes():
    src = (ROOT / "f5_redteam" / "04_policy_failure_modes.py").read_text(encoding="utf-8")
    body = src.split("    guards = {", 1)[1]
    for g in M.GUARDS:
        assert f'"{g}"' in body, f"{g} is declared in GUARDS but never computed in main"
    assert len(set(M.GUARDS)) == len(M.GUARDS)


def test_the_bracket_guards_are_the_ones_that_make_an_allow_attributable():
    """Named explicitly: these two are the reason arms 1 and 2 exist at all."""
    assert "control_arm_was_allowed" in M.GUARDS
    assert "valid_path_arm_was_denied" in M.GUARDS


def test_the_mutation_bounds_match_the_arms():
    """The dry-run banner's mutation count must be derived, not typed."""
    assert M.MAX_DELETES == len(M.ARMS) - 1
    assert M.MAX_CREATES == (len(M.ARMS) - 1) + len(M.BROKEN_ARMS)
    assert M.MAX_CREATES >= M.MAX_DELETES, (
        "more policies are deleted than can be created; one delete has no policy to delete")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
