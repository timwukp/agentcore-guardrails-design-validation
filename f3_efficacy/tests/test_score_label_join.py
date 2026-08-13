"""F3-10's golden set and its dry run, tested against the real corpus loader.

Why this file exists
--------------------
F3-10's dry run printed `total calls: 60`, exited 0, and the live run then died three AWS
reads later at `_golden_set`: it called `arms.load_corpus(path, n=..., seed=...)` and the
loader has neither parameter — it takes `limit=` and is deterministic by design, which is
why there is no seed to pass. Nine other scripts call it correctly; this one never had its
call executed by anything, because `_dry_run` described the golden set in prose instead of
building it (`feedback_dry_run_before_expensive_run`).

So the arms here execute the two paths a dry run is standing in for, with the REAL loader
and the REAL sealed corpora — no fake corpus object, because a double would have accepted
`n=`/`seed=` exactly as happily as the prose did
(`feedback_verify_against_real_artifact`).

What each arm holds
-------------------
* the signature: `_corpus` must reach the loader as the other callers do, and calling it
  must not raise. `test_the_dry_run_builds_the_golden_set` is the arm that fails on the
  original bug.
* the shape: 30/30, alternating, and `truth` derived from which FILE an item came from
  rather than from anything a service said — the F3-family's characteristic defect is a
  clean-looking rate computed against the wrong ground truth.
* `--n`: a smoke cap must shrink the set and keep both strata present, since the join this
  case measures is between a positive and a negative label sharing a CloudWatch bucket. A
  cap that returned 3 HATE and 0 CLEAN is DEV-P1-10's failure, one file over.

Offline, $0. The corpora are local sealed files; `conftest.no_aws` blocks the network.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import arms as R
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(stem: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "f3_efficacy" / stem)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load("08_score_label_join.py", "f3_score_label_join")


def test_the_corpus_helper_calls_the_loader_the_way_every_other_caller_does():
    """The bug in one line: `load_corpus` has no `n` and no `seed`.

    Asserted against the loader's actual signature rather than against a remembered
    parameter name, so a future rename fails here instead of at the first live call.
    """
    import inspect

    params = inspect.signature(R.load_corpus).parameters
    assert "limit" in params, f"loader parameters are {sorted(params)}"
    assert "n" not in params and "seed" not in params, (
        "the loader grew an `n` or `seed` parameter; F3-10's helper and this arm both "
        "assume the deterministic file-order contract")

    items = M._corpus(M.HATE_CORPUS, 4)
    assert len(items) == 4
    assert [i["label"] for i in items] == ["HATE"] * 4


def test_the_corpus_paths_are_loader_relative_not_absolute():
    """`load_corpus` joins onto `corpora/`. An absolute path happens to survive that join,
    so this is a convention arm, not a crash arm — and the convention is what makes the
    sealed-tree root swap in `root=` meaningful for the three unsealed cases."""
    for rel in (M.HATE_CORPUS, M.BENIGN_CORPUS):
        assert isinstance(rel, str), f"{rel!r} is not a relative string"
        assert not rel.startswith("/"), rel
        assert (ROOT / "corpora" / rel).is_file(), rel


def test_the_golden_set_is_thirty_positive_thirty_negative_and_alternates():
    items = M._golden_set(M.N_DERIVED)
    assert len(items) == 60
    assert sum(1 for i in items if i["truth"] == "positive") == 30
    assert sum(1 for i in items if i["truth"] == "negative") == 30
    assert len({i["id"] for i in items}) == 60, "an item was sent twice"
    # Alternating, because half (b) of the oracle is whether two labels landing in the same
    # one-minute bucket can still be told apart. Sending all 30 positives first would let a
    # bucket hold one label and the case would answer an easier question.
    assert [i["truth"] for i in items[:4]] == \
        ["negative", "positive", "negative", "positive"]


def test_ground_truth_comes_from_the_file_not_from_the_corpus_label_field():
    """`truth` and `corpus_label` must agree here — and they are computed from different
    things on purpose. If `truth` were ever derived from a service response, the confusion
    matrix would compare the service with itself."""
    for it in M._golden_set(M.N_DERIVED):
        expect = "HATE" if it["truth"] == "positive" else "CLEAN"
        assert it["corpus_label"] == expect, it


@pytest.mark.parametrize("n", [2, 6, 21, 60])
def test_a_smoke_cap_keeps_both_strata(n: int):
    items = M._golden_set(n)
    assert len(items) == n
    truths = {i["truth"] for i in items}
    assert truths == {"positive", "negative"}, (
        f"n={n} produced only {truths}; a window with one label cannot exercise the "
        f"score<->label join this case measures")


def test_the_dry_run_builds_the_golden_set(capsys):
    """The arm that fails on the original defect.

    `_dry_run` is called directly, so nothing here touches AWS or the ledger — and it must
    print evidence that the set was constructed, not that it was planned.
    """
    assert M._dry_run(M.N_DERIVED) == 0
    out = capsys.readouterr().out
    assert "golden set built offline: 60 items, 30 positive / 30 negative" in out, out[:400]
    # 60 + 2 + 60. The banner checks the operation breakdown against the arm plan itself, so a
    # plan row added without its calls would raise inside `dry_run_banner` rather than here.
    assert "total calls: 122" in out, out[-800:]
    for arm in M.ARMS:
        assert arm["key"] in out, f"the plan does not name {arm['key']}"


# ================================ the restore's Phase-2 assertion

def test_the_phase2_assertion_calls_verify_gateways_with_the_signature_it_has():
    """The second live defect: `verify_gateways(ac, state, checks)` — three arguments to a
    five-parameter function. It raised, the `except` swallowed it, and the run went on.

    Checked against the real function's signature, not a remembered argument list.
    """
    import importlib.util
    import inspect

    spec = importlib.util.spec_from_file_location("infra_verify",
                                                  ROOT / "infra" / "06_verify.py")
    vf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vf)
    params = list(inspect.signature(vf.verify_gateways).parameters)
    assert params == ["ac", "state", "account_id", "region", "c"], params

    # And the call site passes exactly those, in that order.
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert "_vf.verify_gateways(ac, state, account_id, region, checks)" in src, (
        "the call site no longer matches the signature above")


class _FakeChecks:
    """The real `Checks` contract: `ok` is all() over rows, `failures` is a METHOD."""

    def __init__(self, rows):
        self.rows = list(rows)

    def add(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        return bool(ok)

    @property
    def ok(self):
        return all(o for _n, o, _d in self.rows)

    def failures(self):
        return [r for r in self.rows if not r[1]]

    def print(self):
        pass

    def to_json(self):
        return {"ok": self.ok,
                "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in self.rows],
                "n_pass": sum(1 for _n, o, _d in self.rows if o),
                "n_fail": sum(1 for _n, o, _d in self.rows if not o)}


def _run_assertion(monkeypatch, *, rows=(), raise_on_gateways=None):
    """Drive `_phase2_assertion` with the verify functions stubbed. No AWS, no ledger."""
    def _engine(ac, state, c):
        for r in rows:
            c.add(*r)

    def _gateways(ac, state, account_id, region, c):
        if raise_on_gateways:
            raise raise_on_gateways
        return {}

    monkeypatch.setattr(M._vf, "Checks", lambda: _FakeChecks([]))
    monkeypatch.setattr(M._vf, "verify_engine", _engine)
    monkeypatch.setattr(M._vf, "verify_gateways", _gateways)
    # The mask placeholder, not a 12-digit literal: `_phase2_assertion` never parses the account
    # ID, it only forwards it to `verify_gateways` (monkeypatched above), so a real-shaped value
    # would add nothing except a permanent finding for the redaction gate, which matches on
    # shape and cannot know a literal is synthetic.
    return M._phase2_assertion(object(), object(), M._redact.ACCOUNT_PLACEHOLDER, "us-east-1")


def test_all_checks_passing_reads_ok(monkeypatch):
    out = _run_assertion(monkeypatch, rows=[("engine ACTIVE", True, ""),
                                            ("gateway READY", True, "")])
    assert out["ok"] is True
    assert (out["n_checks"], out["n_pass"], out["n_fail"]) == (2, 2, 0)
    assert out["raised"] is None and out["failures"] == []


def test_a_failing_check_reads_not_ok_and_names_it(monkeypatch):
    out = _run_assertion(monkeypatch, rows=[("engine ACTIVE", True, ""),
                                            ("gateway mode", False, "LOG_ONLY")])
    assert out["ok"] is False
    assert out["n_fail"] == 1
    assert [c["name"] for c in out["failures"]] == ["gateway mode"]


def test_an_assertion_that_raised_before_any_check_is_not_ok(monkeypatch):
    """The vacuous pass. `Checks.ok` is `all()` over an empty list — True — so a raise that
    happens before the first `add` would otherwise publish a verified restore that was never
    verified."""
    out = _run_assertion(monkeypatch, raise_on_gateways=TypeError(
        "verify_gateways() missing 2 required positional arguments: 'region' and 'c'"))
    assert out["ok"] is False, "an empty check list read as a passing restore"
    assert out["n_checks"] == 0
    assert "missing 2 required positional arguments" in out["raised"]


def test_a_raise_after_some_checks_passed_is_still_not_ok(monkeypatch):
    out = _run_assertion(monkeypatch, rows=[("engine ACTIVE", True, "")],
                         raise_on_gateways=RuntimeError("boom"))
    assert out["ok"] is False, "a partial assertion read as a complete one"
    assert out["n_checks"] == 1 and out["n_pass"] == 1 and out["n_fail"] == 0
    assert out["raised"] == "RuntimeError: boom"


def test_failures_is_read_as_a_method_not_a_value():
    """`list(getattr(checks, 'failures', []))` on the real object raises
    `TypeError: 'method' object is not iterable` — the exact crash of 2026-08-12."""
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert "getattr(checks, \"failures\"" not in src
    assert 'c for c in cj["checks"] if not c["ok"]' in src, (
        "failures are derived from to_json()'s rows, which are data")


def test_no_seed_is_recorded_because_the_selection_has_none():
    """A `corpus_seed` in the checkpoint metadata would be a number describing a shuffle
    that does not happen. The replacement states the actual selection rule."""
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert "corpus_seed" not in src, "a seed reappeared in the metadata"
    assert "CORPUS_SELECTION" in src
    assert "file order" in M.CORPUS_SELECTION


# ============================================================ the vacuous TRUE of 2026-08-12
#
# The run published TRUE and measured nothing. One wrong string caused it and three guards
# let it through, so there are four arms below, one per defect, each of them checked by
# MUTATION: the arm is confirmed to fail against the old behaviour, not merely to pass
# against the new one (`feedback_vacuous_test_check`).
#
#   1. `client.call_tool(TOOL, ...)` sent the BARE name. `lib/mcp.call_tool` documents its
#      `name` as `<TargetName>___<ToolName>`; the gateway answered all 60 calls with
#      `Unknown tool: echo` (isError=True, severityText ERROR in APPLICATION_LOGS), which is
#      a rejection at MCP dispatch BEFORE any policy evaluation.
#   2. `golden_set_landed` asked only whether the trials COMPLETED — and 60 completed
#      JSON-RPC errors satisfy it — while `n_usable` counted those errors as usable trials.
#   3. half (a) read metric NAMES out of `ListMetrics`, which indexes ~2 weeks of
#      account-wide publishing. `ConfidenceScore` was listed because EARLIER cases' traffic
#      published it; all 24 listed score series had zero datapoints in this window.
#   4. half (b) accepted ANY series at one request per datapoint. The 12 it named were all
#      `Latency`/`Invocations`/... on `Method: initialize` — the MCP handshake, called once,
#      so SampleCount==1 was a fact about a one-off protocol call.

class _FakeDecision:
    """The real `lib.mcp.Decision` is used where possible; this stands in only where a test
    needs an outcome the dataclass would have to be constructed to produce anyway."""


def _decision(outcome: str, *, text: str = "", request_id: str = "rq-x"):
    """A REAL `Decision`, not a double — `denied` is a property derived from `outcome` and a
    stub that set `denied` directly would let a wrong outcome string pass
    (`feedback_verify_against_real_artifact`)."""
    return M.M.Decision(outcome=outcome, http_status=200, request_id=request_id,
                        is_error=(outcome != "allowed"), text=text)


class _FakeClient:
    """Records the tool name it was asked for. Nothing here reaches a socket."""

    def __init__(self, *, advertised=("grxecho___echo",), outcome="allowed", text=""):
        self.advertised = list(advertised)
        self.outcome, self.text = outcome, text
        self.called_with: list[str] = []

    def list_tools(self):
        return ([{"name": n} for n in self.advertised],
                _decision("allowed"))

    def call_tool(self, name, arguments=None, **kw):
        self.called_with.append(name)
        return _decision(self.outcome, text=self.text)

    def refresh_if_stale(self):
        pass


# ---------------------------------------------------------------- defect 1: the tool name

def test_the_preflight_accepts_the_qualified_name_the_gateway_advertises():
    c = _FakeClient(advertised=["grxecho___echo"])
    out = M._preflight_tool_name(c, "grxecho___echo")
    assert out["ok"] is True
    assert out["sending"] == "grxecho___echo"
    assert "not that the call is permitted" in out["why_not_authorization"]


def test_the_preflight_raises_on_the_bare_name_that_cost_the_2026_08_12_run():
    """The mutation. `TOOL` is the exact string that was sent, so this arm reproduces the
    defect rather than a paraphrase of it — and the preflight must refuse BEFORE the probe
    policy is created or the engine is flipped, which is why it raises instead of returning."""
    c = _FakeClient(advertised=["grxecho___echo"])
    with pytest.raises(Exception) as ei:                       # ConfigError
        M._preflight_tool_name(c, M.TOOL)
    msg = str(ei.value)
    assert "does not advertise" in msg and "'echo'" in msg
    assert "BEFORE policy evaluation" in msg, msg
    assert "DEV-P4-22" in msg


def test_the_arm_sends_the_qualified_name_not_the_bare_one(tmp_path, monkeypatch):
    """The defect in one line, at the call site. `_run_arm` takes the name as an argument and
    must pass THAT to the client — the old `_run_golden` closed over the module constant."""
    monkeypatch.chdir(tmp_path)                       # the checkpoint writes under cwd
    c = _FakeClient()
    items = M._golden_set(2)
    cp = M._run_arm(c, "grxecho___echo", arm=dict(M.ARMS[0], spacing_s=0.0),
                    items=items, is_smoke=True)
    assert c.called_with == ["grxecho___echo", "grxecho___echo"], c.called_with
    assert M.TOOL not in c.called_with, "the bare name reached the wire again"
    assert cp.n_failed == 0
    assert all(r["evaluated"] for r in M._rows(cp))


def test_the_source_no_longer_passes_the_module_constant_to_call_tool():
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert "client.call_tool(TOOL" not in src, "the bare-name call site is back"
    assert "_call(client, tool_name, it)" in src
    assert "d = client.call_tool(tool_name," in src


# --------------------------------------------- defect 2: a completed error is not a trial

@pytest.mark.parametrize(("outcome", "evaluated"), [
    ("allowed", True),
    ("policy_denied", True),
    ("jsonrpc_error", False),      # the 2026-08-12 outcome, 60 of 60
    ("tool_error", False),
    ("http_error", False),
])
def test_only_an_evaluated_outcome_counts_as_a_trial(outcome, evaluated):
    """`EVALUATED_OUTCOMES` is the whole repair for `n_usable`. A `jsonrpc_error` is a
    protocol rejection: the engine never saw the request, so it can be neither blocked nor
    scored."""
    c = _FakeClient(outcome=outcome, text="Unknown tool: echo")
    row = M._call(c, "grxecho___echo", M._golden_set(2)[0])
    assert row["outcome"] == outcome
    assert row["evaluated"] is evaluated
    # The diagnosis is kept on the row, so 60 identical failures need no second query
    # against a 7-day log retention to explain.
    assert (row["error_text"] == "") is evaluated


def test_the_guard_list_names_the_two_guards_the_defect_walked_through():
    assert "golden_set_was_evaluated" in M.GUARDS
    assert "tool_name_advertised" in M.GUARDS
    # And the guards that passed vacuously are still there — they were not wrong, they were
    # insufficient, and deleting them would lose the checks they do make.
    assert "golden_set_landed" in M.GUARDS
    assert "nothing_blocked_in_log_only" in M.GUARDS


def test_the_blocked_guard_is_no_longer_satisfiable_by_zero_evaluations():
    """`n_blocked == 0` is true of a window in which nothing was evaluated at all. The
    conjunction with a positive evaluated count is what makes it falsifiable."""
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert 'n_blocked == 0 and n_evaluated_primary > 0' in src
    assert "n_usable=n_evaluated_primary" in src, "n_usable counts responses again"


# ------------------------------------------- defect 3: a metric NAME is not a metric VALUE

def _series(name, *, dps, our_buckets):
    """One `per_series` entry in the shape `_identity_half_from_metrics` emits."""
    return {"name": name, "dimensions": [], "n_datapoints": len(dps),
            "datapoints": dps,
            "datapoints_in_our_buckets": sum(1 for d in dps
                                             if d["bucket_s"] in set(our_buckets))}


def test_a_score_name_with_no_datapoint_in_our_buckets_is_not_readable():
    """The exact 2026-08-12 shape: `ConfidenceScore` is published by the namespace and named
    in the index, and it carried nothing in this window."""
    half = {"our_buckets": [1000, 1060],
            "per_series": [_series("ConfidenceScore", dps=[], our_buckets=[1000, 1060])]}
    out = M._score_datapoints(half)
    assert out["n_score_series_this_gateway"] == 1, "the name was not even recognised"
    assert out["n_score_series_with_any_datapoint"] == 0
    assert out["readable"] is False, "a name with no value read as a readable score"


def test_a_score_datapoint_from_another_windows_traffic_is_not_readable():
    """The mutation between the two readings that matter. Same series, same non-zero datapoint
    count — but the datapoint is in a bucket none of our requests fell in, which is what a
    score published by an EARLIER case's traffic looks like."""
    dp = {"t": "x", "bucket_s": 940, "sample_count": 3.0, "sum": 2.4, "min": 0.4, "max": 0.9}
    half = {"our_buckets": [1000, 1060],
            "per_series": [_series("ConfidenceScore", dps=[dp], our_buckets=[1000, 1060])]}
    out = M._score_datapoints(half)
    assert out["n_score_series_with_any_datapoint"] == 1
    assert out["n_score_series_with_a_datapoint_in_our_buckets"] == 0
    assert out["readable"] is False


def test_a_score_datapoint_in_one_of_our_buckets_is_readable_and_its_values_are_published():
    dp = {"t": "x", "bucket_s": 1060, "sample_count": 1.0, "sum": 0.8, "min": 0.8, "max": 0.8}
    half = {"our_buckets": [1000, 1060],
            "per_series": [_series("ConfidenceScore", dps=[dp], our_buckets=[1000, 1060])]}
    out = M._score_datapoints(half)
    assert out["readable"] is True
    assert out["score_series_readable"] == ["ConfidenceScore"]
    assert out["sample_counts_in_our_buckets"] == [1.0]
    assert out["value_range_in_our_buckets"] == {"min": 0.8, "max": 0.8}


def test_the_verdict_reads_datapoints_and_publishes_the_name_reading_separately():
    """Both readings are recorded — the index reading is real information about the namespace
    — but only the datapoint reading can move the verdict."""
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert 'joinable = any(h["joinable"]' in src
    assert "score_metric_name_exists" in src, "the renamed name-reading key is gone"
    assert 'bool(score_half["score_metric_exists"]) and' not in src, (
        "the verdict conjoins the ListMetrics name reading again")


# ------------------------------------------ defect 4: which series half (b) is allowed to be about

def test_the_identity_half_reports_score_series_separately_from_any_series():
    """Reproduced from the published result: 12 handshake series at one request per datapoint,
    none of them a score. `identity_recoverable_for_a_score` must be False on that input."""
    handshake = [
        {"name": n, "all_datapoints_are_single_request": True,
         "is_a_score_series": bool(M.SCORE_NAME_RE.search(n))}
        for n in ("Latency", "Invocations", "Duration", "Throttles",
                  "UserErrors", "SystemErrors")]
    per_request_score = [e for e in handshake if e["is_a_score_series"]]
    assert per_request_score == [], (
        "one of the six handshake metric names now matches the score criterion, so the "
        "criterion — not this arm — is what needs changing")


def test_the_score_criterion_matches_the_names_the_namespace_actually_publishes():
    """`ConfidenceScore` and `ConfidenceThreshold` are what `AWS/Bedrock-AgentCore` publishes
    (measured 2026-08-11..12: ConfidenceScore 21 datapoints, Average 0.77..0.84, Minimum
    0.4..0.6; ConfidenceThreshold 21 datapoints, all 0.0). A criterion that missed them would
    make half (a) unfalsifiable."""
    for name in ("ConfidenceScore", "ConfidenceThreshold", "GuardrailScore"):
        assert M.SCORE_NAME_RE.search(name), name
    for name in ("Latency", "Invocations", "Throttles", "SystemErrors"):
        assert not M.SCORE_NAME_RE.search(name), name


def test_the_identity_half_scopes_datapoints_to_our_own_buckets():
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert 'entry["datapoints_in_our_buckets"] = len(ours)' in src
    assert 'all((d["sample_count"] or 0) <= 1 for d in ours))' in src, (
        "single-request is computed over the whole read range again, which is what let the "
        "pre-arm MCP handshake answer a question about our requests")


# ------------------------------------------------------------------ the arms themselves

def test_the_arms_can_tell_the_two_hypotheses_apart():
    """One arm could not distinguish 'the service publishes no score' from 'the guardrail
    never ran'. Two modes and two rates is the minimum that can."""
    keys = [a["key"] for a in M.ARMS]
    assert len(set(keys)) == len(keys) == 3, keys
    modes = {a["engine_mode"] for a in M.ARMS}
    assert modes == {M.ENGINE_ENFORCE, M.ENGINE_LOG_ONLY}, modes
    # The spaced arm is the measured form of half (b)'s escape hatch, so its spacing must
    # exceed one CloudWatch period or it is just a slower golden set.
    spaced = next(a for a in M.ARMS if a["key"] == M.ARM_ACTIVE_SPACED)
    assert spaced["spacing_s"] > M.PERIOD_S, spaced
    assert spaced["scored"] is False, "an arm sent below one request per period cannot be "\
                                      "evidence that the join needs no low rate"
    assert set(M.SCORED_ARMS) == {M.ARM_ACTIVE_GOLDEN, M.ARM_LOG_ONLY_GOLDEN}
    for a in M.ARMS:
        assert a["why"], f"{a['key']} has no stated reason to exist"


def test_the_enforce_arms_run_before_the_flip():
    """Order is not cosmetic: the testbed's steady state is ENFORCE, so putting both ENFORCE
    arms first keeps the mutation count at one flip plus one restore. The dry run's
    `mutations: 3` is derived from that order."""
    modes = [a["engine_mode"] for a in M.ARMS]
    assert modes.index(M.ENGINE_LOG_ONLY) == len(modes) - 1, modes
    assert M.ARMS[-1]["key"] == M.ARM_LOG_ONLY_GOLDEN


@pytest.mark.parametrize("now", [1786501200.0, 1786501259.9, 1786501230.5, 1786501200.001])
def test_the_bucket_isolation_always_lands_in_a_later_bucket(now):
    """No sleep: the arithmetic is checked directly, at the boundary values that would break it.

    A `now` exactly on a boundary is the dangerous case — a naive `sleep(PERIOD_S)` from there
    lands on the NEXT boundary and the first request of the arm falls in the bucket the previous
    arm's last request could still be in."""
    out = M._isolate_bucket(now=now, sleep=False)
    assert out["bucket_after"] > out["bucket_before"], out
    assert out["bucket_after"] - out["bucket_before"] == M.PERIOD_S, out
    assert 0 < out["slept_s"] <= M.PERIOD_S + M.BUCKET_MARGIN_S, out
    assert out["margin_s"] == M.BUCKET_MARGIN_S


def test_the_isolation_margin_is_smaller_than_a_period():
    """A margin at or above a period would push the arm two buckets on, which is harmless but
    means the recorded `bucket_after` no longer describes where the traffic went."""
    assert 0 < M.BUCKET_MARGIN_S < M.PERIOD_S


def test_the_bucket_guard_is_computed_from_the_rows_not_from_the_sleep():
    """The guard must not read `_isolate_bucket`'s own return value — that would assert the
    harness's intention, which is the shape of every defect DEV-P4-22 records."""
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert '"arms_own_their_buckets": _arms_own_their_buckets(harvests)["ok"]' in src
    # The CODE, not the docstring — the docstring names `_isolate_bucket` on purpose, to say
    # which function this one exists to distrust.
    body = src.split("def _arms_own_their_buckets")[1].split("\ndef ")[0]
    code = body.split('"""')[2]
    assert "_isolate_bucket" not in code and "slept_s" not in code, code[:400]
    assert "arms_own_their_buckets" in M.GUARDS


def _h(*buckets):
    return {"identity_half": {"our_buckets": list(buckets)}}


def test_the_arms_own_their_buckets_guard_passes_on_disjoint_buckets():
    out = M._arms_own_their_buckets(
        {"a": _h(1000, 1060), "b": _h(1120), "c": _h(1180, 1240)})
    assert out["ok"] is True
    assert out["shared_buckets"] == {}
    assert out["buckets_per_arm"]["b"] == [1120]


def test_the_arms_own_their_buckets_guard_fails_on_the_back_to_back_overlap():
    """The overlap back-to-back arms produced before the isolation existed: the spaced arm's
    only bucket is the fast arm's last one, so its `SampleCount` would be 61."""
    out = M._arms_own_their_buckets(
        {"active_golden_set": _h(1000, 1060), "active_one_per_minute": _h(1060, 1180)})
    assert out["ok"] is False, "an arm sharing the previous arm's last bucket read as isolated"
    assert out["shared_buckets"] == {"active_golden_set|active_one_per_minute": [1060]}


def test_the_wall_clock_estimate_counts_gaps_not_points():
    """`feedback_span_vs_points_offbyone`: a spaced arm of k items sleeps k-1 times. The banner
    first said "2 gaps" for a 2-item arm, which is a number the script never sleeps."""
    est = M._wall_clock_estimate(M.N_DERIVED)
    spaced = next(a for a in M.ARMS if a["key"] == M.ARM_ACTIVE_SPACED)
    assert est["n_spaced_gaps"] == spaced["n"] - 1 == 1
    # One flip out and one restore; the two ENFORCE arms need none because ENFORCE is the start.
    assert est["n_flips"] == 1
    assert est["n_calls"] == 122
    assert est["total_s"] == pytest.approx(sum(est["terms"].values()))
    # A --n cap shrinks the calls and cannot shrink the fixed waits below zero.
    small = M._wall_clock_estimate(2)
    assert small["n_calls"] == 6 and small["total_s"] < est["total_s"]


def test_each_arm_checkpoints_under_its_own_cell():
    """Three arms sharing one checkpoint cell would resume into each other's rows — and the
    60 rows already on disk from the vacuous run are exactly what a shared cell would
    replay."""
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert 'Checkpoint(case_id=CASE, cell=arm["key"])' in src
    assert "CELL_KEY" not in src, "the single-cell constant is back"


# ================================= the two instrument defects of the 2026-08-12 run
#
# The run's verdict (FALSE, metrics only) is right and is not touched by any of this. What was
# wrong is what it RECORDED about the other two surfaces: `application_logs` and `spans` were
# published with `score_present` read off a message-text regex and `identity_present: false`.
# Both readings were properties of the checks:
#
#   5. `_numeric_keys` collected `int` and `float` values only, and the gateway publishes the
#      score as a JSON STRING — `body.policy.guardrailFindings.<id>.contentFilter[].score` is
#      `"0.8000"`. The census that existed so half (a) could not be a word game was blind, by
#      its own type filter, to the one field it was looking for.
#   6. `identity_present` asked "does an event's text contain one of our CORPUS ids". The
#      corpus id is not on that surface. `request_id` is — on every policy event and every
#      harness row — and it was never joined.
#
# Each arm below is a MUTATION arm: it also asserts what the OLD behaviour would have produced,
# so it can distinguish the fix from the defect rather than merely being green beside it.

_POLICY_ID = "grx_f3_10_scored_r20260810T130945Z-ystne00vhh"
# The real key path, not a paraphrase of it (`feedback_verify_against_real_artifact`).
_LOG_SCORE_PATH = f"body.policy.guardrailFindings.{_POLICY_ID}.contentFilter[].score"


def _log_event(*, rid: str, score: str | None = "0.8000") -> str:
    """One APPLICATION_LOGS message, shaped like the ones in `evidence/.../F3-10/`.

    `score` is a string because that is what the service writes. A float here would make the
    arm below pass under both the broken and the fixed census.
    """
    policy: dict = {"decision": "DENY" if score else "ALLOW", "latencyMs": 412,
                    "determiningPolicies": [_POLICY_ID]}
    if score is not None:
        policy["guardrailFindings"] = {_POLICY_ID: {
            "effect": "FORBID", "policyMode": "ENFORCE",
            "contentFilter": [{"score": score, "filter": "HATE"}]}}
    return M.json.dumps({"request_id": rid, "severityText": "ERROR",
                         "body": {"isError": bool(score), "id": "b-1",
                                  "log": "Policy evaluation denied request", "policy": policy}})


def _app_logs_with(monkeypatch, events, *, rows=None, trial_ids=frozenset()):
    """Run `_app_logs` against a canned `filter_log_events` page. No client, no socket."""
    class _Rec:
        ok = True
        error_code = error_message = ""

        def __init__(self, response):
            self.response = response

    def fake_capture(_store, operation, _client, **params):
        if operation == "describe_log_groups":
            return _Rec({"logGroups": [{"logGroupName": params["logGroupNamePrefix"],
                                        "storedBytes": 4096, "retentionInDays": 7}]})
        assert operation == "filter_log_events", operation
        return _Rec({"events": [{"message": m} for m in events]})

    monkeypatch.setattr(M, "capture", fake_capture)
    return M._app_logs(None, None, gateway_id="grx-gw-test-abc", t0=1000.0, t1=1060.0,
                       trial_ids=set(trial_ids), rows=rows)


# ------------------------------------------- defect 5: a number in a string is still a number

def test_the_census_collects_a_numeric_valued_string_under_its_own_key():
    numeric = M._numeric_keys(M.json.loads(_log_event(rid="r-1")), acc={}, str_acc=(s := {}))
    assert _LOG_SCORE_PATH in s, s
    assert s[_LOG_SCORE_PATH] == "0.8000"
    # It is reported as a string, which is itself the finding: Logs Insights arithmetic on this
    # field needs a cast, and a reader who assumed a number would get no rows.
    assert _LOG_SCORE_PATH not in numeric
    assert numeric["body.policy.latencyMs"] == 412


def test_the_old_census_would_have_missed_it():
    """The mutation. Called the way it was called before `str_acc` existed, it must still miss.

    Without this arm the one above is green under both versions of the walker and proves
    nothing about the fix.
    """
    numeric = M._numeric_keys(M.json.loads(_log_event(rid="r-1")))
    assert _LOG_SCORE_PATH not in numeric
    assert [k for k in numeric if M.SCORE_NAME_RE.search(k)] == [], \
        "the old census had no score-valued key to find, which is why it reported none"


@pytest.mark.parametrize(("value", "numeric"), [
    ("0.8000", True), ("1.0000", True), ("0", True), ("-1.5e-3", True), (" 0.4 ", True),
    ("HATE", False), ("", False), ("0.8 (high)", False), ("nan", True),
])
def test_looks_numeric_is_float_not_a_regex(value, numeric):
    """`float()` is the test. A regex would have to decide about exponents, signs and spaces,
    and every one of those decisions would be a guess about a format nobody documented."""
    assert M._looks_numeric(value) is numeric


def test_a_boolean_is_not_collected_as_a_number():
    """`isinstance(True, int)` is True in Python, and `body.isError` is a bool on every event.
    Counting it would put a field that is not a measurement into the score census."""
    numeric = M._numeric_keys({"body": {"isError": True, "n": 3}}, acc={}, str_acc={})
    assert "body.isError" not in numeric
    assert numeric == {"body.n": 3}


def test_the_log_surface_now_reports_the_score_key_path_it_actually_carries():
    got = _app_logs_with(pytest.MonkeyPatch(), [_log_event(rid="r-1")])
    assert got["score_valued_key_paths"] == [_LOG_SCORE_PATH]
    assert got["numeric_strings_seen"][_LOG_SCORE_PATH] == "0.8000"
    assert got["score_present"] is True


def test_score_present_is_read_from_the_census_not_from_the_message_text():
    """The old reading. An event whose TEXT matches /score|confidence/ but which carries no
    score-valued field must read `score_present: False` — otherwise "a score is published" is
    satisfied by the word appearing anywhere in a JSON blob (`feedback_prose_is_not_verified`).
    """
    text_only = M.json.dumps({"request_id": "r-1", "body": {
        "log": "confidence score evaluation completed", "policy": {"decision": "ALLOW",
                                                                   "latencyMs": 5}}})
    got = _app_logs_with(pytest.MonkeyPatch(), [text_only])
    assert got["n_events_matching_the_score_pattern"] == 1, "the old instrument's reading"
    assert got["score_valued_key_paths"] == []
    assert got["score_present"] is False


def test_the_span_surface_got_the_same_fix(monkeypatch):
    """`_spans` ran the same blind census, so a span carrying `"score": "0.8000"` would have
    been published as score-free. F6 joins spans by request id, so this is the surface an
    amendment would most likely point at."""
    msg = _log_event(rid="rq-span-1")
    monkeypatch.setattr(M._tr, "query_spans",
                        lambda *a, **k: [[{"field": "@message", "value": msg}]])
    got = M._spans(None, None, gateway_arn="arn:x", request_ids=["rq-span-1"])
    assert got["score_valued_key_paths"] == [_LOG_SCORE_PATH]
    assert got["score_present"] is True
    assert got["identity_present"] is True
    assert got["join_key_available"] == "request_id"
    assert got["scored"] is False, "the oracle names CloudWatch metrics alone; that is unchanged"


# --------------------------------- defect 6: identity is `request_id`, and it was never joined

def test_identity_is_established_by_joining_request_ids():
    got = _app_logs_with(pytest.MonkeyPatch(), [_log_event(rid="rq-a"), _log_event(rid="rq-b")],
                         rows=[{"request_id": "rq-a"}, {"request_id": "rq-b"},
                               {"request_id": "rq-never-logged"}])
    assert got["n_events_naming_one_of_our_request_ids"] == 2
    assert got["identity_present"] is True
    assert got["join_key_available"] == "request_id"


def test_the_corpus_id_needle_is_kept_beside_it_because_its_absence_is_also_true():
    """The old check is not deleted: "the request TEXT is logged verbatim, the corpus id is
    not" is a real fact about the surface. It just is not the identity question."""
    got = _app_logs_with(pytest.MonkeyPatch(), [_log_event(rid="rq-a")],
                         rows=[{"request_id": "rq-a"}], trial_ids={"deadbeefcafe"})
    assert got["n_events_naming_one_of_our_corpus_ids"] == 0, "the old instrument's reading"
    assert got["identity_present"] is True, "which is why it must not be the discriminator"
    assert "the corpus id is not on this surface" in got["why_identity_is_request_id"]


def test_identity_stays_false_when_no_event_carries_one_of_our_request_ids():
    """The guard has to be able to come back False, or the fix is just a different constant."""
    got = _app_logs_with(pytest.MonkeyPatch(), [_log_event(rid="rq-somebody-elses")],
                         rows=[{"request_id": "rq-ours"}])
    assert got["n_events_naming_one_of_our_request_ids"] == 0
    assert got["identity_present"] is False
    assert got["join_key_available"] == ""


def test_no_rows_passed_means_no_identity_claim():
    """Called without `rows`, the join set is empty and `all([])`-style vacuity must not make
    the surface look joinable."""
    got = _app_logs_with(pytest.MonkeyPatch(), [_log_event(rid="rq-a")], rows=None)
    assert got["identity_present"] is False


def test_the_call_site_passes_the_rows_to_the_log_reader():
    """A parameter nothing supplies is a parameter that does not exist
    (`feedback_no_deploy_path_no_component`)."""
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    call = src.split("app_logs = _app_logs(")[1].split(")")[0]
    assert "rows=rows" in call, call
    assert "trial_ids=trial_ids" in call, call


def test_the_log_and_span_surfaces_stay_unscored_after_the_correction():
    """The correction changes what is RECORDED, never what the verdict is computed from. F3-10's
    sealed oracle says "from CloudWatch metrics alone" and both surfaces stay amendment
    material — the properly scoped read of the log surface is `08b_log_surface_join.py`."""
    got = _app_logs_with(pytest.MonkeyPatch(), [_log_event(rid="rq-a")],
                         rows=[{"request_id": "rq-a"}])
    assert got["scored"] is False
    assert "CloudWatch metrics" in got["why_not_scored"]
    src = (ROOT / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert "08b_log_surface_join.py" in src, "the supplementary read should be pointed at"
