"""`phase1.create_probe_guardrail` / `delete_probe_guardrails` / `probe_residue`.

WHY THIS FILE EXISTS

On 2026-08-13, writing F1-6 (which needs a sacrificial guardrail per tier x crossRegionConfig
cell), the first call to `phase1.create_probe_guardrail` raised

    NameError: name 'case_id' is not defined

before reaching a single AWS API. The helper's body ended in `detail=_detail(case_id, detail)`
and `case_id` was neither a parameter nor a module global, so EVERY call raised — unconditionally,
for any argument. `_detail` had been added to the return (it exists to reject a `**detail` key that
is really an `Observation` field name, after F5-1 published INCONCLUSIVE over a successful 120-trial
run whose mandatory mutation had inverted 20/20) without giving the function the `case_id` that
`_detail` reports in its message.

The regression was invisible for two compounding reasons, and both are the thing this file fixes:

  1. The two live callers, F8-5 (`f8_regional/04_topic_limits.py`) and F8-7
     (`f8_regional/06_word_language.py`), had already run. Their records — 4 `create_guardrail`
     each under `evidence/smoke20260810T0305Z/f8/` — predate the edit, so both verdicts are
     published off a code path that no longer executes. Nothing re-ran them.
  2. No test in the repo called the helper at all. `grep -rl probe_guardrail lib/tests
     f8_regional/tests` matched nothing. The 14-gate suite was green across 2176 arms with a
     shared helper that could not run.

So the load-bearing arm here is the plainest one imaginable: CALL IT. A helper whose failure mode
is "raises on every input" needs no clever fixture to catch — it needs one execution, which is
exactly what it never had (`feedback_vacuous_test_check`: a guard nothing exercises reports clean).

WHY THE CAPTURE DOUBLE IS WRITTEN TWICE

`capture` is stubbed, because the point of the helper is that a rejection is DATA: `Record.ok` is
False, `error_code` is the observation, and nothing raises. A double that only ever succeeds never
reaches the branch where `guardrail_id` must stay None, and would pass against a helper that
happily reported a guardrail id for a failed create (`feedback_unreachable_branch_in_fake`). Both
doubles are therefore built from `evidence.Record` itself rather than from a stand-in class, so a
field renamed on `Record` breaks these arms instead of silently passing.

WHY THERE IS A STATIC ARM OVER THE CALL SITES

`case_id` is now keyword-only and required, so a call site that omits it is a `TypeError` — but at
CALL time, which for these two callers means live, mid-run, after a policy engine and a gateway
already exist. The static arm reads every call to the helper in the tree and asserts each passes
`case_id=`, which moves that failure to desk (the same argument
`runner/tests/test_runner_policy.py` makes for its IAM mapping guard).

THE ONE SURVIVING MUTANT, AND WHY IT IS EXPECTED TO SURVIVE

The mutation run over these arms reported one survivor, M3: delete the early break on not-found in
`delete_probe_guardrails`,

    if rec.error_code == "ResourceNotFoundException":
        break

and every arm here still passes. That is correct, and it is recorded as an EQUIVALENT survivor
rather than as a gap, on the same rule `lib/tests/test_write_guard_mutation.py` states for its inert
rows: a mutation that provably cannot change any output is not a kill and must not be banked as one.
The proof is two lines below the mutated one — `if rec.error_code not in DELETE_RETRY_CODES or
attempt == DELETE_TRIES - 1: break` — and `ResourceNotFoundException` is not in
`DELETE_RETRY_CODES`, so the loop exits on the same iteration either way. Same call count, same
`codes` list, same row: byte-identical output, no arm can see it. An arm written to kill M3 could
only do it by asserting on the source text, which tests the spelling of a branch instead of the
behaviour of the teardown (`feedback_identical_output_wrong_assertion`).

What the survivor does mean is that the early break is load-bearing only CONDITIONALLY: it is
redundant exactly while not-found stays out of the retry list, and it becomes the thing preventing
four pointless deletes and ~30 s of backoff the moment someone adds it — a plausible edit, since
"retry the teardown until the resource is gone" reads like caution. So the real risk lives in the
retry list, not in the break, and that is where the arm went:
`test_not_found_is_not_in_the_retry_codes` asserts the code's absence from `DELETE_RETRY_CODES`
alongside the one-attempt behaviour. M3 survives; the defect M3 stands in for cannot.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence as E                                                # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_scope import ROOT, py_files                                # noqa: E402

CASE = "F8-5"


class Limiter:
    """A rate limiter that records what it was asked to wait for.

    Not a no-op: `create_probe_guardrail` must throttle `CreateGuardrail` specifically, and a
    silent no-op double would let a helper that forgot to call `lim.wait` pass.
    """

    def __init__(self) -> None:
        self.waited: list[str] = []

    def wait(self, operation: str, **_: object) -> None:
        self.waited.append(operation)


def _record(*, ok: bool, response: dict | None = None, error_code: str = "",
            error_message: str = "") -> E.Record:
    return E.Record(
        case_id=CASE, operation="create_guardrail", service="bedrock",
        region="us-west-2", params={}, ok=ok,
        http_status=200 if ok else 400, request_id="rid-0001",
        response=response, error_code=error_code, error_message=error_message,
        path="evidence/x/0001_create_guardrail_ok.json")


def _capture_ok(seen: list[dict]):
    """A double that SUCCEEDS, and keeps the params so the request can be asserted."""
    def _c(store, operation, client, **params):                     # noqa: ANN001
        seen.append({"store": store, "operation": operation, "params": params})
        return _record(ok=True, response={"guardrailId": "gr-abc123",
                                          "guardrailArn": "arn:aws:bedrock:::guardrail/gr-abc123"})
    return _c


def _capture_rejected(seen: list[dict]):
    """A double that FAILS. The branch a success-only double never reaches."""
    def _c(store, operation, client, **params):                     # noqa: ANN001
        seen.append({"store": store, "operation": operation, "params": params})
        return _record(ok=False, error_code="ValidationException",
                       error_message="topic definition exceeds the maximum length")
    return _c


# ---------------------------------------------------------------------------
# the arm the NameError died to
# ---------------------------------------------------------------------------

def test_create_probe_guardrail_can_be_called_at_all(monkeypatch):
    """One execution. This is the whole arm, and it is the one that was missing.

    Between the `_detail` edit and 2026-08-13 this raised `NameError` for every input. An
    assertion about the RETURN VALUE is secondary here; the primary claim is that the call
    completes, which is why the success assertions below are deliberately shallow.
    """
    seen: list[dict] = []
    monkeypatch.setattr(P, "capture", _capture_ok(seen))
    lim = Limiter()

    p = P.create_probe_guardrail(
        object(), None, lim,
        case_id=CASE, label="classic-200",
        name="grx-gr-f8-5-classic-200-r1",
        description="F8-5 boundary probe: CLASSIC 200 chars",
        tags=[{"key": "grx:run", "value": "r1"}],
        config={"topicPolicyConfig": {"topicsConfig": [], "tierConfig": {"tierName": "CLASSIC"}}},
        tier="CLASSIC", length=200, expect="accepted")

    assert isinstance(p, P.ProbeGuardrail)
    assert p.accepted is True
    assert p.guardrail_id == "gr-abc123"
    assert lim.waited == ["CreateGuardrail"], (
        "the helper must throttle CreateGuardrail; an unthrottled create is how a probe loop "
        "earns a ThrottlingException that reads as a rejection")


def test_the_free_form_detail_survives_and_names_its_case(monkeypatch):
    """`case_id` is not decoration — `_detail` reports it, and the detail must come through.

    A fix that satisfied the NameError by passing a literal (`_detail("", detail)`) would pass
    the arm above and leave `_detail`'s TypeError message unable to name the case it fired for.
    """
    monkeypatch.setattr(P, "capture", _capture_ok([]))
    p = P.create_probe_guardrail(
        object(), None, Limiter(), case_id="F1-6", label="standard-no-xregion",
        name="n", description="d", tags=[], config={},
        tier="STANDARD", cross_region=False, expect="rejected")
    assert p.detail == {"tier": "STANDARD", "cross_region": False, "expect": "rejected"}

    with pytest.raises(TypeError) as ei:
        P.create_probe_guardrail(
            object(), None, Limiter(), case_id="F1-6", label="l", name="n",
            description="d", tags=[], config={},
            # `observed_bool` IS an Observation field. Passed as detail it lands where the
            # decision rule never looks — the failure `_detail` exists to make loud.
            observed_bool=True)
    assert "F1-6" in str(ei.value), (
        "the TypeError must name the case; that is the only reason the helper takes a case_id "
        "rather than passing a literal to _detail")
    assert "observed_bool" in str(ei.value)


def test_a_rejection_is_data_and_carries_no_guardrail_id(monkeypatch):
    """The failure branch. Nothing raises, and `guardrail_id` must stay None.

    A helper that read `response.get("guardrailId")` unconditionally would return None here
    anyway (the double's response is None), so the assertion that matters is `accepted is False`
    together with the error code — the pair a teardown and an oracle both read.
    """
    monkeypatch.setattr(P, "capture", _capture_rejected([]))
    p = P.create_probe_guardrail(
        object(), None, Limiter(), case_id=CASE, label="standard-201",
        name="n", description="d", tags=[], config={}, expect="rejected")
    assert p.accepted is False
    assert p.guardrail_id is None
    assert p.error_code == "ValidationException"
    assert p.http_status == 400
    assert p.request_id == "rid-0001"


def test_description_is_truncated_to_the_models_maximum(monkeypatch):
    """200 characters, and the request is what gets asserted — not the return value.

    The helper's docstring gives the reason: a description over the model's maximum fails the
    create on a field unrelated to the boundary under test, and that rejection would read as
    the boundary holding.
    """
    seen: list[dict] = []
    monkeypatch.setattr(P, "capture", _capture_ok(seen))
    P.create_probe_guardrail(
        object(), None, Limiter(), case_id=CASE, label="l", name="n",
        description="x" * 500, tags=[], config={"wordPolicyConfig": {"wordsConfig": []}})
    params = seen[0]["params"]
    assert len(params["description"]) == 200
    assert params["blockedInputMessaging"] and params["blockedOutputsMessaging"], (
        "both are required members of CreateGuardrail; omitting either fails the create for a "
        "reason no probe is measuring")
    assert "wordPolicyConfig" in params, "the config dict must be splatted into the request"


# ---------------------------------------------------------------------------
# teardown, and the residue computed from two lists
# ---------------------------------------------------------------------------

def test_every_probe_is_deleted_even_after_one_delete_fails(monkeypatch):
    """Stopping at the first failed delete would strand the rest for an unrelated reason."""
    calls: list[str] = []

    def _c(store, operation, client, **params):                     # noqa: ANN001
        gid = params["guardrailIdentifier"]
        calls.append(gid)
        ok = gid != "gr-2"
        return E.Record(case_id=CASE, operation="delete_guardrail", service="bedrock",
                        region="us-west-2", params=params, ok=ok,
                        http_status=200 if ok else 409, request_id=f"rid-{gid}",
                        error_code="" if ok else "ConflictException")

    monkeypatch.setattr(P, "capture", _c)
    probes = [P.ProbeGuardrail(label=f"l{i}", name=f"n{i}", accepted=True,
                               guardrail_id=f"gr-{i}") for i in (1, 2, 3)]
    probes.append(P.ProbeGuardrail(label="rejected", name="n4", accepted=False))

    monkeypatch.setattr(P.time, "sleep", lambda _s: None)
    out = P.delete_probe_guardrails(object(), None, Limiter(), probes)
    # gr-2 fails with a RETRYABLE code, so it is attempted `DELETE_TRIES` times before the loop
    # gives up on it. What this arm is about is what happens AFTER that: gr-3 must still be
    # reached, and the rejected probe must never be attempted because it created nothing.
    assert calls == ["gr-1"] + ["gr-2"] * P.DELETE_TRIES + ["gr-3"], calls
    assert [(d["guardrail_id"], d["deleted"]) for d in out] == [
        ("gr-1", True), ("gr-2", False), ("gr-3", True)]
    assert out[1]["error_code"] == "ConflictException", (
        "a per-id error code is the difference between a one-minute fix and sweeping an "
        "account carrying unrelated resources")
    assert out[1]["attempts"] == P.DELETE_TRIES
    assert out[0]["attempts"] == 1, "a delete that worked first time must not report retries"


def _retry_probes(monkeypatch, codes: list[str]):
    """One probe whose delete answers `codes` in order, then succeeds. Returns (calls, row).

    The answers are a SCRIPT rather than a single verdict because the whole question here is how
    many times the call was made, and a fake that always answers the same thing cannot tell a
    guard that retries once from a guard that retries five times.
    """
    calls: list[str] = []

    def _c(store, operation, client, **params):                      # noqa: ANN001
        i = len(calls)
        calls.append(params["guardrailIdentifier"])
        code = codes[i] if i < len(codes) else ""
        return E.Record(case_id=CASE, operation="delete_guardrail", service="bedrock",
                        region="us-west-2", params=params, ok=not code,
                        http_status=200 if not code else 429, request_id="rid",
                        error_code=code)

    monkeypatch.setattr(P, "capture", _c)
    monkeypatch.setattr(P.time, "sleep", lambda _s: None)
    probes = [P.ProbeGuardrail(label="l", name="n", accepted=True, guardrail_id="gr-1")]
    out = P.delete_probe_guardrails(object(), None, Limiter(), probes)
    return calls, out[0]


def test_a_throttled_delete_is_retried_until_it_succeeds(monkeypatch):
    """The defect this retry exists for, measured twice on 2026-08-13.

    F1-6 and F1-26/27/28 each leaked one guardrail because `DeleteGuardrail` was throttled on the
    case's last call. `DeleteGuardrail` is paced at 2 rps and was throttled anyway — the quota is
    the account's, and this project is not its only user, so pacing can lower the probability and
    never remove it. A single-attempt delete turns somebody else's traffic into our residue.
    """
    calls, row = _retry_probes(monkeypatch, ["ThrottlingException", "ThrottlingException"])
    assert len(calls) == 3, calls
    assert row["deleted"] is True
    assert row["attempts"] == 3
    assert row["attempt_error_codes"] == ["ThrottlingException", "ThrottlingException"], (
        "the intermediate codes stay in the row: a teardown that succeeded on the third try is "
        "not the same event as one that succeeded on the first, and the difference is what "
        "predicts the next leak")
    assert row["error_code"] is None, "the final answer was a success, and the row must say so"


def test_a_delete_that_reports_the_guardrail_already_gone_is_not_retried(monkeypatch):
    """NotFound IS the desired end state, so retrying it would only spend calls.

    Reported under its own key as well as `deleted`, because a NotFound could also mean the id was
    wrong, and those two are indistinguishable from inside this function. The row says which one
    AWS actually answered rather than quietly picking one (`feedback_missing_check_is_not_pass`).
    """
    calls, row = _retry_probes(monkeypatch, ["ResourceNotFoundException"])
    assert len(calls) == 1, "a resource that does not exist does not need deleting again"
    assert row["deleted"] is True
    assert row["already_gone"] is True
    assert row["error_code"] == "ResourceNotFoundException"


def test_a_permanent_failure_is_not_retried(monkeypatch):
    """AccessDenied does not clear by waiting, and four more calls would not discover that.

    This is the arm that keeps the retry list a LIST. Retrying every failure would turn a
    misconfigured policy into a five-times-slower teardown that fails identically, and would hide
    the one error code an operator can act on behind four repetitions of it.
    """
    calls, row = _retry_probes(monkeypatch, ["AccessDeniedException"] * 6)
    assert len(calls) == 1, calls
    assert row["deleted"] is False
    assert row["error_code"] == "AccessDeniedException"
    assert "AccessDeniedException" not in P.DELETE_RETRY_CODES


def test_not_found_is_not_in_the_retry_codes(monkeypatch):
    """`ResourceNotFoundException` is the DESIRED END STATE, so retrying it would be a bug in the
    one direction that looks like caution.

    `delete_probe_guardrails` treats not-found as gone (`gone = rec.ok or ... NotFound`) and records
    it as `already_gone`. If the code were also in `DELETE_RETRY_CODES` the two rules would
    contradict: the loop would spend four more calls and `DELETE_BACKOFF_S` of backoff apiece
    re-confirming an absence it had already accepted, inside the `finally` that is the last thing
    between a detached case and its exit code. Nothing would be reported wrong — which is why this
    needs a test rather than a comment, since the defect is invisible in the result and shows up
    only as a slower teardown.

    Both halves are asserted: the code is absent from the retry list, AND one attempt is what
    actually happens when the service returns it.
    """
    assert "ResourceNotFoundException" not in P.DELETE_RETRY_CODES
    calls, row = _retry_probes(monkeypatch, ["ResourceNotFoundException"] * 6)
    assert len(calls) == 1, f"a not-found delete was attempted {len(calls)} times: {calls}"
    assert row["already_gone"] is True, row
    assert row["deleted"] is True, "not-found is the end state this teardown wants, not a failure"


def test_the_retry_is_bounded(monkeypatch):
    """A service that throttles forever must not hold the teardown open forever.

    The `finally` this runs inside is the last thing between a case and its exit code, so an
    unbounded retry here would hang a detached job with its measurement already complete.
    """
    calls, row = _retry_probes(monkeypatch, ["ThrottlingException"] * 50)
    assert len(calls) == P.DELETE_TRIES
    assert row["deleted"] is False
    assert row["attempts"] == P.DELETE_TRIES
    assert P.DELETE_TRIES >= 2, "one attempt is not a retry"


def test_every_delete_attempt_is_captured_as_evidence(monkeypatch):
    """The retry is visible in the audit rather than hidden behind its own success.

    Each try goes through `capture`, so the evidence tree holds one record per attempt. A retry
    loop that captured only the final answer would make a run that fought the service for four
    attempts indistinguishable from one that sailed through, which is precisely the signal
    somebody debugging the next leak needs.
    """
    ops: list[str] = []

    def _c(store, operation, client, **params):                      # noqa: ANN001
        ops.append(operation)
        code = "ThrottlingException" if len(ops) < 3 else ""
        return E.Record(case_id=CASE, operation=operation, service="bedrock",
                        region="us-west-2", params=params, ok=not code,
                        http_status=200 if not code else 429, request_id="rid",
                        error_code=code)

    monkeypatch.setattr(P, "capture", _c)
    monkeypatch.setattr(P.time, "sleep", lambda _s: None)
    P.delete_probe_guardrails(object(), None, Limiter(),
                              [P.ProbeGuardrail(label="l", name="n", accepted=True,
                                                guardrail_id="gr-1")])
    assert ops == ["delete_guardrail"] * 3, ops


def test_the_limiter_is_asked_before_every_attempt_not_only_the_first(monkeypatch):
    """A retry that skips the pacing would send its second call as fast as the machine allows.

    Which is the same behaviour that earned the throttle in the first place. The `lim.wait` has to
    be inside the loop, and this arm is what stops a refactor from lifting it out.
    """
    waits: list[str] = []

    class _Lim:
        def wait(self, op):                                          # noqa: ANN001
            waits.append(op)
            return 0.0

    def _c(store, operation, client, **params):                      # noqa: ANN001
        code = "ThrottlingException" if len(waits) < 3 else ""
        return E.Record(case_id=CASE, operation=operation, service="bedrock",
                        region="us-west-2", params=params, ok=not code,
                        http_status=200 if not code else 429, request_id="rid",
                        error_code=code)

    monkeypatch.setattr(P, "capture", _c)
    monkeypatch.setattr(P.time, "sleep", lambda _s: None)
    P.delete_probe_guardrails(object(), None, _Lim(),
                              [P.ProbeGuardrail(label="l", name="n", accepted=True,
                                                guardrail_id="gr-1")])
    assert waits == ["DeleteGuardrail"] * 3, waits


def test_the_backoff_grows(monkeypatch):
    """Constant retries against a throttle are four more throttles.

    Asserted on the sequence of requested sleeps rather than on elapsed time, so the arm is exact
    and costs nothing — and asserted as strictly increasing rather than against literal values,
    which would restate `DELETE_BACKOFF_S` instead of checking the shape.
    """
    slept: list[float] = []
    monkeypatch.setattr(P.time, "sleep", lambda s: slept.append(s))

    def _c(store, operation, client, **params):                      # noqa: ANN001
        return E.Record(case_id=CASE, operation=operation, service="bedrock",
                        region="us-west-2", params=params, ok=False,
                        http_status=429, request_id="rid", error_code="ThrottlingException")

    monkeypatch.setattr(P, "capture", _c)
    P.delete_probe_guardrails(object(), None, Limiter(),
                              [P.ProbeGuardrail(label="l", name="n", accepted=True,
                                                guardrail_id="gr-1")])
    assert len(slept) == P.DELETE_TRIES - 1, "no sleep is paid after the final attempt"
    assert slept == sorted(slept) and slept[0] < slept[-1], slept


def test_residue_reports_a_survivor_whose_delete_was_never_attempted():
    """The circularity `probe_residue` exists to avoid.

    A residue derived from `deletions` alone reports zero survivors for exactly the case where
    one exists: the process died between the create and the finally, so the survivor contributes
    no row to that list.
    """
    probes = [P.ProbeGuardrail(label="a", name="na", accepted=True, guardrail_id="gr-1"),
              P.ProbeGuardrail(label="b", name="nb", accepted=True, guardrail_id="gr-2")]
    deletions = [{"label": "a", "name": "na", "guardrail_id": "gr-1", "deleted": True,
                  "error_code": None, "request_id": "r"}]
    res = P.probe_residue(probes, deletions)
    assert res["n_created"] == 2
    assert res["n_delete_attempted"] == 1
    assert res["surviving"] == ["gr-2"]
    assert res["never_attempted"] == ["gr-2"]
    assert res["clean"] is False, (
        "gr-2 is live in the account and no deletion row mentions it; a residue computed from "
        "`deletions` would have called this clean")


def test_residue_is_clean_only_when_every_created_id_was_deleted():
    probes = [P.ProbeGuardrail(label="a", name="na", accepted=True, guardrail_id="gr-1"),
              P.ProbeGuardrail(label="r", name="nr", accepted=False)]
    deletions = [{"label": "a", "name": "na", "guardrail_id": "gr-1", "deleted": True,
                  "error_code": None, "request_id": "r"}]
    res = P.probe_residue(probes, deletions)
    assert res["clean"] is True
    assert res["n_created"] == 1, "a rejected probe created nothing and is not residue"


# ---------------------------------------------------------------------------
# the static arm: no call site may omit case_id
# ---------------------------------------------------------------------------

HELPER = "create_probe_guardrail"


def _call_sites() -> list[tuple[str, int, ast.Call]]:
    """Every `create_probe_guardrail(...)` call in the tree, this file excluded.

    Derived by walking the AST rather than by grep, so a call split across lines — which both
    live call sites are — is one site and not four (`feedback_grep_the_claim_not_the_phrasing`).
    """
    # Scope from `scan_scope`, not a local set of venv names — that set could not see the third
    # virtualenv `.venv-figs` (DEV-P4-42), and this scan reads matplotlib's source for free.
    out: list[tuple[str, int, ast.Call]] = []
    for path in py_files():
        if path == Path(__file__):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == HELPER and not isinstance(fn, ast.FunctionDef):
                out.append((str(path.relative_to(ROOT)), node.lineno, node))
    return out


def test_every_call_site_passes_case_id():
    """Fail at desk, not live.

    `case_id` is keyword-only and required, so an omission is a TypeError — raised mid-run,
    after a policy engine and a gateway already exist and with sacrificial guardrails possibly
    half-created. This arm reads the tree instead.
    """
    sites = _call_sites()
    assert sites, (
        f"found 0 calls to {HELPER}. A zero-site scan is an error, not a pass: either the "
        f"helper was renamed or the walk is broken (feedback_zero_file_scan_is_error)")
    missing = [(f, ln) for f, ln, node in sites
               if "case_id" not in {kw.arg for kw in node.keywords}]
    assert not missing, (
        f"{HELPER} call sites without case_id=: {missing}. Passed positionally it cannot be — "
        f"the parameter is keyword-only — so this is an omission that raises TypeError live")


def test_the_helper_does_not_read_case_id_off_the_module_globals():
    """The exact shape of the 2026-08-13 regression, pinned.

    Stated as "the parameter exists and nothing named case_id is a module global", because that
    is the pair that failed: the body read a name the module did not define. A future edit that
    silences the NameError by defining a module-level `case_id` would make every probe record
    whatever case ran last.
    """
    import inspect
    params = inspect.signature(P.create_probe_guardrail).parameters
    assert "case_id" in params, f"{HELPER} must take case_id as a parameter"
    assert params["case_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["case_id"].default is inspect.Parameter.empty, (
        "a default would let a call site silently attribute its probes to another case")
    assert not hasattr(P, "case_id"), (
        "a module-level `case_id` in phase1 would resolve the bare name the old body read and "
        "make every probe's detail carry whichever case assigned it last")


def test_case_id_reaches_detail_from_the_argument_and_not_from_a_literal(monkeypatch):
    """`_detail` must be called with the ARGUMENT.

    Read out of the source rather than inferred from behaviour: `_detail` only uses `case_id`
    in its error path, so a fix passing `_detail("F8-5", detail)` behaves identically on every
    success and differs only in the message of a TypeError — which is precisely the thing that
    was broken.
    """
    src = inspect_source(P.create_probe_guardrail)
    assert re.search(r"_detail\(\s*case_id\s*,", src), (
        "expected `_detail(case_id, detail)` in the body; a literal case id there would make "
        "the TypeError name the wrong case")


def inspect_source(fn) -> str:                                      # noqa: ANN001
    import inspect
    return inspect.getsource(fn)
