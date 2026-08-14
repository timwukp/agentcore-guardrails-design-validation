"""`f9_failsecure/01_throttle_burst.py` — F9-3, the throttle-burst trichotomy.

WHY THIS FILE EXISTS, AND WHY THREE DOUBLES INSTEAD OF ONE

F9-3's oracle is about a bucket that has NO LIVE REPRESENTATIVE we can rely on. The whole
claim is that bucket (c) — HTTP 200, no intervention, no policy block, i.e. content that
went through unevaluated — is empty. If the service is well behaved, no live run will ever
produce one, so the code path that RECOGNISES a silent pass would never execute, and a test
suite built on a success-only double would report green over a classifier that could not
tell a silent pass from a verdict. That is `feedback_unreachable_branch_in_fake` aimed at
the one branch that matters, so this file writes:

  * the SUCCESS double — a 200 carrying the configured word and GUARDRAIL_INTERVENED;
  * the THROTTLING double — `rec.ok` False, `ThrottlingException`, HTTP 429. This is the
    setup condition of the experiment, not an error, and no test that only ever succeeds
    reaches the branch that counts it;
  * the SILENT-PASS double — a 200 with `action=NONE` and no `wordPolicy` block. The FALSE
    branch. It exists here because it may never exist anywhere else.
  * and an UNCLASSIFIED double, because a response in no bucket must be loud rather than
    rounded into a neighbour.

All four are built from `evidence.Record` itself rather than from a stand-in class, so a
field renamed on `Record` breaks these arms instead of silently passing.

WHY THE RETRY CONFIGURATION IS ASSERTED HERE AND NOT ONLY IN THE SCRIPT

botocore's `standard` and `adaptive` retry modes re-drive a throttled request until it
succeeds. Under either, this case observes zero throttles, reports an unthrottled burst and
concludes nothing — while every number in the record looks right. A passing test suite
would never see it, because the defect produces a *clean* run. So the retry contract is a
first-class arm: lib's own `Config` must satisfy it, and a config allowing more than one
attempt must be REFUSED before any request is sent.

WHY THERE IS A STATIC ARM OVER THE LIMITER

The burst arm's correctness is an ABSENCE: it must not call `lim.wait`. An absence cannot be
asserted by observing a passing run — a paced burst still returns rows, still classifies
them, and simply never throttles, which reads as a service result rather than a harness
edit. Two arms cover it: a behavioural one (the limiter double records nothing during the
burst) and a static one (the AST of `run_burst` contains no `lim.wait` call, and
`run_control`'s does).
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                               # noqa: E402
import evidence as E                                                 # noqa: E402
import oracle as O                                                   # noqa: E402
import phase1 as P                                                   # noqa: E402
import stats as S                                                    # noqa: E402

SCRIPT = ROOT / "f9_failsecure" / "01_throttle_burst.py"


def _load():
    """Import the case script by path — its filename starts with a digit."""
    spec = importlib.util.spec_from_file_location("f9_01_throttle_burst", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


M = _load()
WORD = "moonquake"


# ---------------------------------------------------------------------------
# the four doubles
# ---------------------------------------------------------------------------

def _record(*, ok: bool, response: dict | None = None, error_code: str = "",
            http_status: int | None = 200, request_id: str = "rid-0001") -> E.Record:
    return E.Record(
        case_id=M.CASE, operation="apply_guardrail", service="bedrock-runtime",
        region="us-east-1", params={}, ok=ok, http_status=http_status,
        request_id=request_id, response=response, error_code=error_code,
        error_message="" if ok else f"{error_code} on ApplyGuardrail",
        error_class="" if ok else "ClientError",
        duration_ms=42.0, path="evidence/x/0001_apply_guardrail.json")


def rec_evaluated(word: str = WORD) -> E.Record:
    """SUCCESS: a 200 carrying a real verdict — the word reported, the guardrail intervened."""
    return _record(ok=True, response={
        "action": "GUARDRAIL_INTERVENED",
        "actionReason": "Custom word match",
        "assessments": [{
            "wordPolicy": {"customWords": [{"match": word, "detected": True}]},
            "invocationMetrics": {"guardrailProcessingLatency": 31,
                                  "usage": {"wordPolicyUnits": 1}},
            "appliedGuardrailDetails": {"guardrailArn": "arn:aws:bedrock:::guardrail/x"},
        }],
        "usage": {"wordPolicyUnits": 1},
    })


def rec_throttled() -> E.Record:
    """THROTTLING: the setup condition of the experiment, not an error to retry."""
    return _record(ok=False, error_code="ThrottlingException", http_status=429,
                   request_id="rid-throttle")


def rec_silent_pass() -> E.Record:
    """SILENT PASS: 200, action NONE, no wordPolicy block. The oracle's FALSE.

    Note the assessments list is NOT empty — the service returns
    `appliedGuardrailDetails` and `invocationMetrics` whatever happens. A classifier that
    tested for an empty list would file this as an evaluation.
    """
    return _record(ok=True, response={
        "action": "NONE",
        "assessments": [{
            "invocationMetrics": {"usage": {"wordPolicyUnits": 1}},
            "appliedGuardrailDetails": {"guardrailArn": "arn:aws:bedrock:::guardrail/x"},
        }],
        "usage": {"wordPolicyUnits": 1},
    })


def rec_unclassified() -> E.Record:
    """A 200 that intervened but reported no custom word: in no bucket, and must be loud."""
    return _record(ok=True, response={
        "action": "GUARDRAIL_INTERVENED",
        "assessments": [{"invocationMetrics": {"usage": {"wordPolicyUnits": 1}}}],
    })


DOUBLES = {"ok": rec_evaluated, "throttle": rec_throttled,
           "silent": rec_silent_pass, "weird": rec_unclassified,
           "denied": lambda: _record(ok=False, error_code="AccessDeniedException",
                                     http_status=403)}


class CaptureScript:
    """A `capture` double driven by a token list, safe to call from many threads.

    Records every request's params so the arms can assert what was SENT — the
    guardrail id, the version, the output scope — not merely what came back.
    """

    def __init__(self, outcomes: list[str]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, store, operation, client, **params):          # noqa: ANN001
        with self._lock:
            i = len(self.calls)
            self.calls.append({"operation": operation, "params": params})
            token = self.outcomes[i] if i < len(self.outcomes) else self.outcomes[-1]
        return DOUBLES[token]()

    @property
    def n(self) -> int:
        return len(self.calls)


class Limiter:
    """A limiter that records what it was asked to pace. Never a silent no-op.

    A no-op double would let a burst that accidentally called `lim.wait` pass the bypass
    arm, and the bypass is the thing that makes this case able to reach the quota at all.
    """

    def __init__(self) -> None:
        self.waited: list[str] = []
        self.waits: dict[str, float] = {}

    def wait(self, operation: str, **_: object) -> float:
        self.waited.append(operation)
        self.waits[operation] = self.waits.get(operation, 0.0) + 0.01
        return 0.01


# ---------------------------------------------------------------------------
# bucket (c) and its neighbours: the trichotomy, one bucket per response
# ---------------------------------------------------------------------------

def test_a_real_verdict_is_bucket_evaluated():
    row = M.classify(rec_evaluated(), expect_word=WORD)
    assert row["bucket"] == M.EVALUATED
    assert row["throttled"] is False
    assert row["expected_word_reported"] is True
    assert row["policy_block_present"] is True


def test_a_throttle_is_an_observable_failure_and_is_counted_as_a_throttle():
    row = M.classify(rec_throttled(), expect_word=WORD)
    assert row["bucket"] == M.OBSERVABLE_FAILURE
    assert row["throttled"] is True
    assert row["error_code"] == "ThrottlingException"
    assert row["request_id"] == "rid-throttle", (
        "the request id is what makes a throttle quotable to AWS Support; a bucket count "
        "without it is not evidence")


def test_a_200_with_no_intervention_and_no_word_policy_is_a_silent_pass():
    """The FALSE branch, and the reason this file exists.

    The double is the only representative of this bucket anywhere in the project: a
    well-behaved service never produces one, so without it the branch that recognises a
    silent pass would never execute.
    """
    row = M.classify(rec_silent_pass(), expect_word=WORD)
    assert row["bucket"] == M.SILENT_PASS
    assert row["throttled"] is False
    assert row["blocks_present"] == ["appliedGuardrailDetails", "invocationMetrics"], (
        "the assessments list is NOT empty on a silent pass — it carries the bookkeeping "
        "blocks. A classifier testing for an empty list would file this as an evaluation")


def test_a_response_in_no_bucket_is_unclassified_and_not_rounded_into_a_neighbour():
    row = M.classify(rec_unclassified(), expect_word=WORD)
    assert row["bucket"] == M.UNCLASSIFIED


def test_a_non_throttle_error_is_observable_but_is_not_a_throttle():
    """The distinction the no-throttle guard rests on.

    480 AccessDenied responses are observable failures that also never reached the quota.
    Counting them as throttles would let the guard pass on a run that measured our IAM.
    """
    row = M.classify(DOUBLES["denied"](), expect_word=WORD)
    assert row["bucket"] == M.OBSERVABLE_FAILURE
    assert row["throttled"] is False


def test_a_429_under_an_unfamiliar_code_is_still_a_throttle():
    rec = _record(ok=False, error_code="SomeNewQuotaError", http_status=429)
    assert M.is_throttle(rec) is True
    rec500 = _record(ok=False, error_code="InternalServerException", http_status=500)
    assert M.is_throttle(rec500) is False


def test_the_expected_word_is_matched_case_insensitively_but_a_different_word_is_not():
    row = M.classify(rec_evaluated("MoonQuake"), expect_word=WORD)
    assert row["bucket"] == M.EVALUATED
    other = M.classify(rec_evaluated("zorbify"), expect_word=WORD)
    assert other["bucket"] == M.UNCLASSIFIED, (
        "a match on a term the probe text does not contain is not this text being "
        "evaluated; it is a response nobody has read")


# ---------------------------------------------------------------------------
# the retry configuration — the defect a passing suite would never see
# ---------------------------------------------------------------------------

def test_the_platforms_own_config_satisfies_the_retry_contract():
    """lib/awsclients.py must already disable retries, and this arm is where we find out.

    Read from `ClientFactory._config` rather than from a constructed client on purpose:
    building a client resolves credentials and can reach the instance metadata service,
    and this suite makes no call of any kind.
    """
    cfg = A.ClientFactory(region="us-east-1")._config("bedrock-runtime")
    v = M.assert_retries_disabled(cfg, where="test")
    assert v["effective_total_attempts"] == 1, (
        "lib/awsclients.ClientFactory._config sets total_max_attempts=1. If this ever "
        "changes, F9-3 must STOP rather than publish a run whose throttles botocore "
        "retried away")


@pytest.mark.parametrize("retries", [
    {"mode": "standard", "total_max_attempts": 3},
    {"mode": "standard", "max_attempts": 5},
    {"mode": "adaptive", "total_max_attempts": 2},
])
def test_a_retrying_config_is_refused_before_any_request(retries):
    with pytest.raises(M.RetryConfigError) as ei:
        M.assert_retries_disabled(Config(retries=retries), where="test")
    assert "retried" in str(ei.value) or "re-drives" in str(ei.value)


def test_a_config_with_no_retry_setting_at_all_is_refused():
    """The default is the dangerous case: botocore's own default mode retries throttles."""
    with pytest.raises(M.RetryConfigError):
        M.assert_retries_disabled(Config(), where="test")


def test_one_attempt_under_legacy_mode_is_accepted_because_the_mode_is_not_the_point():
    v = M.assert_retries_disabled(
        Config(retries={"mode": "legacy", "total_max_attempts": 1}), where="test")
    assert v["mode"] == "legacy"


def test_retry_view_reads_both_spellings_of_the_attempt_limit():
    """botocore accepts `max_attempts` and `total_max_attempts` for the same thing.

    A view that read only one key would call a retrying client retry-free — which is the
    exact shape of the defect this whole arm group exists for.
    """
    assert M.retry_view(Config(retries={"mode": "standard", "max_attempts": 4})
                        )["effective_total_attempts"] == 4
    assert M.retry_view(Config(retries={"mode": "standard", "total_max_attempts": 1})
                        )["effective_total_attempts"] == 1


class FakeFactory:
    """A factory double: no session, no credentials, no socket."""

    def __init__(self, cfg: Config, region: str = "us-east-1") -> None:
        self.region = region
        self._cfg = cfg
        self.built: list[Config] = []

    def bedrock_runtime(self):
        return type("C", (), {"meta": type("M", (), {"config": self._cfg})()})()

    def session(self):
        factory = self

        class Sess:
            def client(self, service, region_name=None, config=None):  # noqa: ANN001
                factory.built.append(config)
                return type("C", (), {"meta": type("M", (), {"config": config})()})()
        return Sess()


def test_the_burst_client_inherits_the_retry_setting_and_widens_only_the_pool():
    """Inherited, not restated. A copy of the retry dict could not detect a drift in lib's."""
    base = A.ClientFactory(region="us-east-1")._config("bedrock-runtime")
    fc = FakeFactory(base)
    client = M.burst_client(fc, pool=96)
    built = fc.built[-1]
    assert built.retries == base.retries, "the retry config must be INHERITED"
    assert built.max_pool_connections == 96
    assert base.max_pool_connections == 10, (
        "the factory's own config is untouched at botocore's default of 10 — which is "
        "exactly the trap: 96 threads on a 10-connection pool offer a quarter of the "
        "ceiling and the burst would never throttle")
    assert client.meta.config is built


def test_the_burst_client_refuses_to_be_built_on_a_retrying_config():
    """The assertion runs BEFORE the client is handed back, not after the first request."""
    fc = FakeFactory(Config(retries={"mode": "standard", "total_max_attempts": 3}))
    with pytest.raises(M.RetryConfigError):
        M.burst_client(fc, pool=8)
    assert fc.built == [], "no client may be returned from a config that retries"


# ---------------------------------------------------------------------------
# the arms: what is sent, what is paced, and what is bounded
# ---------------------------------------------------------------------------

def test_the_control_arm_is_paced_through_the_limiter_and_sends_what_it_claims(monkeypatch):
    cap = CaptureScript(["ok"])
    monkeypatch.setattr(M, "capture", cap)
    lim = Limiter()
    out = M.run_control(object(), None, lim, gid="gr-1", text="the moonquake note is filed",
                        expect_word=WORD, n=5)
    assert cap.n == 5
    assert lim.waited == ["ApplyGuardrail"] * 5, (
        "the control is the arm that must NOT exceed the ceiling it is the control for")
    assert out["tally"]["buckets"][M.EVALUATED] == 5
    assert out["tally"]["n_throttled"] == 0
    assert out["limiter_waits_delta"] == {"ApplyGuardrail": 0.05}
    sent = cap.calls[0]["params"]
    assert sent["guardrailIdentifier"] == "gr-1"
    assert sent["guardrailVersion"] == M.GUARDRAIL_VERSION
    assert sent["outputScope"] == "FULL", (
        "outputScope=FULL is what makes a non-detection observable; under the INTERVENTIONS "
        "default a silent pass and an evaluated negative are byte-identical")
    assert sent["source"] == "INPUT"
    assert sent["content"] == [{"text": {"text": "the moonquake note is filed"}}]


def test_the_burst_arm_never_calls_the_limiter(monkeypatch):
    """The bypass, observed. This is the arm that makes the burst able to reach the quota."""
    cap = CaptureScript(["ok", "ok", "throttle"])
    monkeypatch.setattr(M, "capture", cap)
    lim = Limiter()
    out = M.run_burst(object(), None, lim, gid="gr-1", text="t", expect_word=WORD,
                      n=9, workers=4, deadline_s=30.0)
    assert cap.n == 9
    assert lim.waited == [], (
        "a paced burst still returns rows and simply never throttles, which reads as a "
        "service result rather than as a harness edit — so the absence is asserted")
    assert out["limiter_waits_delta"] == {}
    assert out["paced_through_limiter"] is False


def test_the_burst_is_bounded_by_its_request_count_and_not_by_an_outcome(monkeypatch):
    """`N_BURST` requests, exactly. Never "until a throttle appears"."""
    cap = CaptureScript(["ok"])
    monkeypatch.setattr(M, "capture", cap)
    out = M.run_burst(object(), None, Limiter(), gid="g", text="t", expect_word=WORD,
                      n=37, workers=8, deadline_s=30.0)
    assert cap.n == 37
    assert out["tally"]["n"] == 37
    assert out["n_skipped_after_deadline"] == 0


def test_the_deadline_stops_the_offered_load_and_sends_nothing_after_it(monkeypatch):
    """The blast-radius bound. Every task checks the clock BEFORE calling AWS.

    Driven by an injected clock rather than by sleeping, so the arm is deterministic and
    the assertion is that the check exists at all — not that a real 5 s elapsed.
    """
    cap = CaptureScript(["ok"])
    monkeypatch.setattr(M, "capture", cap)
    ticks = iter([0.0] + [99.0] * 500)

    out = M.run_burst(object(), None, Limiter(), gid="g", text="t", expect_word=WORD,
                      n=25, workers=4, deadline_s=5.0, now=lambda: next(ticks))
    assert cap.n == 0, (
        "past the deadline not one further request may reach AWS: the 100 rps ceiling is "
        "account-level and this account carries unrelated traffic")
    assert out["n_skipped_after_deadline"] == 25
    assert out["tally"]["n"] == 0


def test_the_achieved_rate_is_measured_and_never_the_intended_one(monkeypatch):
    cap = CaptureScript(["ok"])
    monkeypatch.setattr(M, "capture", cap)
    out = M.run_burst(object(), None, Limiter(), gid="g", text="t", expect_word=WORD,
                      n=12, workers=6, deadline_s=30.0)
    rate = out["rate"]
    assert rate["n_sent"] == 12
    assert rate["achieved_rps"] > 0
    assert rate["documented_rps_ceiling"] == A.rate_limit_for("ApplyGuardrail") == 100.0
    assert "measured" in rate["basis"]
    assert rate["achieved_rps"] == pytest.approx(12 / rate["wall_s"]), (
        "requests / wall clock. An intended 300 rps that achieved 40 is why a burst comes "
        "back with zero throttles, and the payload has to make that diagnosable")


# ---------------------------------------------------------------------------
# the control is mandatory: it validates the classifier, not just the guardrail
# ---------------------------------------------------------------------------

def _control(tokens: list[str], monkeypatch) -> dict:
    cap = CaptureScript(tokens)
    monkeypatch.setattr(M, "capture", cap)
    return M.run_control(object(), None, Limiter(), gid="g", text="t",
                         expect_word=WORD, n=len(tokens))


def test_a_control_that_intervenes_on_every_trial_is_accepted(monkeypatch):
    M.check_control(_control(["ok"] * 4, monkeypatch))


def test_a_control_that_does_not_intervene_refuses_the_case(monkeypatch):
    """Without this, every unthrottled 200 in the burst looks like a silent pass."""
    with pytest.raises(M.Refusal) as ei:
        M.check_control(_control(["ok", "ok", "silent", "ok"], monkeypatch))
    assert "provably intervenes" in str(ei.value)


def test_a_control_that_is_already_throttled_refuses_the_case(monkeypatch):
    """A baseline already at the ceiling cannot attribute the burst's throttles to us."""
    with pytest.raises(M.Refusal) as ei:
        M.check_control(_control(["ok", "throttle"], monkeypatch))
    assert "throttled" in str(ei.value)


def test_an_empty_control_refuses_rather_than_passing_vacuously():
    with pytest.raises(M.Refusal):
        M.check_control({"tally": M.tally([]), "rows": []})


# ---------------------------------------------------------------------------
# the verdict rule, including the two guards that may not be relaxed
# ---------------------------------------------------------------------------

def _arm(tokens: list[str], *, arm: str) -> dict:
    rows = [{**M.classify(DOUBLES[t](), expect_word=WORD), "arm": arm} for t in tokens]
    return {"arm": arm, "rows": rows, "tally": M.tally(rows),
            "rate": M._rate([(0.0, 0.1)] * len(rows), len(rows)),
            "workers": 8}


def test_true_needs_zero_silent_passes_and_at_least_one_throttle():
    d = M.decide(_arm(["ok"] * 6, arm="control"),
                 _arm(["ok"] * 50 + ["throttle"] * 30, arm="burst"))
    assert d["verdict_path"] == "true"
    assert d["observed"] is True
    assert d["mutation_inverted"] is True
    assert d["n_throttled"] == 30 and d["n_silent_pass"] == 0
    assert O.evaluate(_obs(d, n=80))["verdict"] == O.TRUE


def test_one_silent_pass_makes_it_false():
    d = M.decide(_arm(["ok"] * 6, arm="control"),
                 _arm(["ok"] * 49 + ["silent"] + ["throttle"] * 30, arm="burst"))
    assert d["verdict_path"] == "false"
    assert d["observed"] is False
    assert d["n_silent_pass"] == 1
    assert O.evaluate(_obs(d, n=80))["verdict"] == O.FALSE


def test_a_silent_pass_is_still_false_when_the_burst_never_reached_the_quota():
    """FALSE outranks the guards in ONE direction only.

    Content that went through unevaluated did so regardless of why the burst was slow, and
    downgrading that to INCONCLUSIVE would suppress the one outcome this case exists to be
    able to report.
    """
    d = M.decide(_arm(["ok"] * 6, arm="control"),
                 _arm(["ok"] * 20 + ["silent"], arm="burst"))
    assert d["verdict_path"] == "false"
    assert d["n_throttled"] == 0


def test_zero_throttles_is_inconclusive_and_never_true():
    """The mandatory guard. '0 silent passes' over an unthrottled burst is vacuous."""
    d = M.decide(_arm(["ok"] * 6, arm="control"), _arm(["ok"] * 200, arm="burst"))
    assert d["verdict_path"] == "inconclusive"
    assert d["observed"] is False
    assert any("never throttled" in w for w in d["inconclusive_because"])
    assert any("rps" in w for w in d["inconclusive_because"]), (
        "the reason must name the ACHIEVED rate — that is the diagnosis of why no throttle "
        "arrived")


def test_observable_failures_that_are_not_throttles_do_not_satisfy_the_guard():
    """480 AccessDenied responses are observable, and reached no quota.

    The assertion is on the REASON and not only on the verdict. A mutant that made the
    guard read bucket (b) instead of its throttle subset still produced INCONCLUSIVE here —
    because the mutation-inversion guard fired instead — so an arm that checked the verdict
    alone passed for a reason unrelated to what it is named for, and the mutant survived.
    """
    d = M.decide(_arm(["ok"] * 6, arm="control"),
                 _arm(["denied"] * 100, arm="burst"))
    assert d["verdict_path"] == "inconclusive"
    assert d["n_observable_failures"] == 100
    assert d["n_throttled"] == 0
    assert any("never throttled" in w for w in d["inconclusive_because"]), (
        f"the no-throttle guard must fire on its own account: 100 observable failures that "
        f"are not throttles reached no quota. Reasons given: "
        f"{d['inconclusive_because']}")


def test_an_unclassified_response_is_fatal_to_the_verdict():
    d = M.decide(_arm(["ok"] * 6, arm="control"),
                 _arm(["ok"] * 40 + ["throttle"] * 20 + ["weird"], arm="burst"))
    assert d["verdict_path"] == "inconclusive"
    assert d["n_unclassified"] == 1
    assert any("no bucket" in w for w in d["inconclusive_because"])


def test_a_mutation_that_did_not_invert_is_inconclusive():
    """Both arms throttling means the rate manipulation is not what changed anything."""
    d = M.decide(_arm(["ok"] * 5 + ["throttle"], arm="control"),
                 _arm(["ok"] * 40 + ["throttle"] * 20, arm="burst"))
    assert d["mutation_inverted"] is False
    assert d["verdict_path"] == "inconclusive"
    assert any("did not invert" in w for w in d["inconclusive_because"])


def test_an_empty_burst_measured_nothing():
    d = M.decide(_arm(["ok"] * 6, arm="control"), _arm([], arm="burst"))
    assert d["verdict_path"] == "inconclusive"
    assert any("0 requests" in w for w in d["inconclusive_because"])


def _obs(d: dict, *, n: int):
    o = P.obs_existence(M.CASE, d["observed"], n=n)
    o.mutation_inverted = d["mutation_inverted"]
    return o


# ---------------------------------------------------------------------------
# the Wilson interval comes from lib/stats.py
# ---------------------------------------------------------------------------

def test_every_reported_proportion_is_a_wilson_interval_from_lib_stats():
    rows = [{**M.classify(DOUBLES[t](), expect_word=WORD)}
            for t in (["ok"] * 70 + ["throttle"] * 30)]
    t = M.tally(rows)
    want = S.wilson_ci(30, 100)
    assert t["throttle_rate"] == {"x": 30, "n": 100, "point": want.point,
                                  "lo": want.lo, "hi": want.hi,
                                  "method": "wilson", "level": 0.95}
    # For a count that must be ZERO the CEILING is the result, and Wilson stays
    # non-degenerate at x=0 where a normal approximation collapses to [0, 0].
    assert t["silent_pass_rate"]["x"] == 0
    assert t["silent_pass_rate"]["lo"] == 0.0
    assert t["silent_pass_rate"]["hi"] == S.wilson_ci(0, 100).hi > 0.0


def test_the_script_does_not_hand_roll_an_interval():
    """A second implementation of Wilson would be a copy no test compares to lib's."""
    src = SCRIPT.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "S.wilson_ci" in body
    for token in ("1.96", "norm.ppf", "math.sqrt"):
        assert token not in body, (
            f"{token!r} suggests a hand-rolled interval; lib/stats.py is sealed and is the "
            f"one place a proportion becomes an interval")


def test_no_interval_is_computed_over_an_empty_arm():
    """`stats._check_counts` raises on n=0; an arm with no rows must not reach it."""
    t = M.tally([])
    assert t["n"] == 0 and "throttle_rate" not in t


# ---------------------------------------------------------------------------
# the evidence store, made safe for the one case that is concurrent
# ---------------------------------------------------------------------------

def test_the_store_subclass_locks_around_the_write(tmp_path):
    """Deterministic: the lock must be ENTERED, once per add.

    A race is probabilistic and a test that relied on losing it would pass over an
    unlocked `add` most of the time.
    """
    store = M.ConcurrentEvidenceStore("rTEST", "f9", M.CASE, root=tmp_path)

    class RecordingLock:
        def __init__(self) -> None:
            self.entered = 0

        def __enter__(self):
            self.entered += 1
            return self

        def __exit__(self, *_a):
            return False

    lock = RecordingLock()
    store._add_lock = lock
    store.add(rec_evaluated())
    store.add(rec_throttled())
    assert lock.entered == 2, (
        "EvidenceStore.add does a non-atomic `self._seq += 1` and then writes "
        "<seq>_<op>.json; two threads taking the same sequence number means one record "
        "silently overwrites the other")


def test_concurrent_adds_produce_one_file_per_record(tmp_path):
    store = M.ConcurrentEvidenceStore("rTEST", "f9", M.CASE, root=tmp_path)
    n = 120

    def add(_i):
        store.add(rec_evaluated())

    with __import__("concurrent.futures").futures.ThreadPoolExecutor(24) as ex:
        list(ex.map(add, range(n)))
    files = sorted(p.name for p in store.dir.glob("*_apply_guardrail_*.json"))
    assert len(files) == n == len(set(files))
    assert len({r.path for r in store.records}) == n, (
        "two records claiming the same path is the silent form of this failure")


def test_it_is_a_subclass_and_does_not_patch_the_shared_class():
    assert issubclass(M.ConcurrentEvidenceStore, E.EvidenceStore)
    assert E.EvidenceStore.add is not M.ConcurrentEvidenceStore.add
    assert "_add_lock" not in inspect.getsource(E.EvidenceStore.add), (
        "the lock belongs to the local subclass; patching the shared class would change "
        "every store in the process to fix a problem only this case has")


# ---------------------------------------------------------------------------
# static arms: absences, and the things that must not become literals
# ---------------------------------------------------------------------------

def _func_ast(name: str) -> ast.FunctionDef:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {SCRIPT.name}")


def _limiter_calls(node: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "wait"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "lim"):
            out.append(ast.unparse(n))
    return out


def test_run_burst_contains_no_call_to_the_limiter_and_run_control_does():
    """The bypass is an ABSENCE, and an absence needs a static arm.

    A future edit that added pacing to the burst would still produce rows, still classify
    them, and simply never throttle — which reads as a service result.
    """
    assert _limiter_calls(_func_ast("run_burst")) == []
    assert _limiter_calls(_func_ast("run_control")), (
        "the control arm must still be paced: it is the control for the ceiling")


def test_nothing_mutates_the_shared_limiter_or_its_table():
    """No monkeypatch of a shared object. The bypass is by omission or it is not honest.

    Read from the AST rather than by grepping the text, because the script *discusses*
    `awsclients._LIMITER` and monkeypatching at length in its docstring — explaining why it
    does neither. A textual scan would fire on the explanation
    (`feedback_grep_the_claim_not_the_phrasing`); the AST sees only executable statements.
    """
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    writes: list[str] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for t in targets:
            # `A.anything = ...`, `A.RATE_LIMITS[...] = ...`, `lim.waits[...] = ...`.
            # A bare `lim = A.limiter()` is not a mutation — it is how the limiter is
            # obtained — so only Attribute and Subscript targets count.
            if not isinstance(t, (ast.Subscript, ast.Attribute)):
                continue
            base = t
            while isinstance(base, (ast.Subscript, ast.Attribute)):
                base = base.value
            if isinstance(base, ast.Name) and base.id in {"A", "lim"}:
                writes.append(ast.unparse(t))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "setattr" and node.args
                and ast.unparse(node.args[0]) in {"A", "lim", "A.RATE_LIMITS"}):
            writes.append(ast.unparse(node))
    assert writes == [], (
        f"{writes} mutate the shared rate-limit table or the process-global limiter. "
        f"awsclients._LIMITER is shared across every client in the process, so patching it "
        f"would unpace every other call site — including this script's own control arm")


def test_the_probe_word_is_read_from_the_manifest_and_not_typed_into_the_script():
    src = SCRIPT.read_text(encoding="utf-8")
    for word in P.configured_words():
        assert word not in src, (
            f"{word!r} is a provisioned custom word and is typed into the script. A literal "
            f"that disagreed with the guardrail would produce a control that never "
            f"intervenes, and the case would refuse for a reason unrelated to throttling")
    assert "configured_words" in src


def test_the_documented_ceiling_is_read_from_awsclients():
    assert M.DOCUMENTED_RPS == A.rate_limit_for("ApplyGuardrail")
    assert A.limit_provenance("ApplyGuardrail") == "aws_documented", (
        "bursting past a self_imposed guess would measure our own caution rather than the "
        "service")
    src = SCRIPT.read_text(encoding="utf-8")
    assert "= 100.0" not in src and "= 100 " not in src


def test_the_probe_text_is_one_text_unit_and_carries_a_configured_word():
    words = P.configured_words()
    text = M.probe_text(words)
    assert words[0] in text
    assert len(text) <= 1000, "a burst multiplies whatever one call costs by N_BURST"
    with pytest.raises(M.Refusal):
        M.probe_text([])


def test_a_probe_text_over_one_text_unit_is_refused():
    """The bound itself, exercised. The real text is short, so nothing else reaches it.

    A mutant that deleted this check survived an arm that only measured the real text's
    length: the guard was present, correct, and never run. `N_BURST` multiplies the
    per-call cost, so a term long enough to cross the 1,000-character unit doubles the bill
    of the whole case silently.
    """
    with pytest.raises(M.Refusal) as ei:
        M.probe_text(["x" * 1200])
    assert "text unit" in str(ei.value)


def test_the_offered_load_is_bounded_by_named_constants_and_stays_single_digit_seconds():
    assert M.BURST_DEADLINE_S < 10.0, (
        "the ceiling is ACCOUNT-level per Region and this account carries ~$27k/mo of "
        "unrelated traffic; a multi-minute burst throttles other people's workloads")
    assert isinstance(M.N_BURST, int) and 0 < M.N_BURST <= 1000
    assert M.N_TOTAL_MAX == M.N_CONTROL + M.N_BURST
    assert M.estimated_cost_usd(M.N_TOTAL_MAX) < 0.20, (
        "an upper bound priced at the highest verified ApplyGuardrail rate")


def test_the_mutation_field_is_set_as_an_attribute_and_never_as_detail():
    """`phase1._detail` refuses an Observation field name passed as `**detail`.

    F5-1 published INCONCLUSIVE over a successful 120-trial run whose mandatory mutation
    had inverted 20/20, because the value landed where the decision rule never looks.
    """
    with pytest.raises(TypeError) as ei:
        P.obs_existence(M.CASE, True, n=1, mutation_inverted=True)
    assert "mutation_inverted" in str(ei.value)
    src = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"^\s*o\.mutation_inverted\s*=", src, re.M), (
        "the field must be assigned as an attribute after construction")
    assert not re.search(r"mutation_inverted\s*=\s*d\[.mutation_inverted.\],\s*$", src, re.M)


def test_the_case_and_family_match_the_seal():
    assert M.CASE == "F9-3"
    assert O.BINDINGS[M.CASE].kind == "EXISTENCE"
    assert "throttled requests are denied or error" in O.oracle_text(M.CASE)
    assert M.FAMILY == "f9"


# ---------------------------------------------------------------------------
# end to end, offline: main() through every verdict path
# ---------------------------------------------------------------------------

class Emitted:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, case_id, record, payload, store=None, **_kw):  # noqa: ANN001
        self.calls.append((case_id, record, payload))
        return Path("results/phase1/F9-3.json")

    @property
    def payload(self) -> dict:
        return self.calls[-1][2]

    @property
    def record(self) -> dict:
        return self.calls[-1][1]


def _run_main(monkeypatch, tmp_path, tokens: list[str], *, n: int = 40) -> Emitted:
    """`main()` end to end with no AWS call and no write into results/ or evidence/.

    `burst_client` is doubled rather than the client alone, because the real one builds a
    session — which resolves credentials and can reach the instance metadata service. The
    store is re-rooted under tmp_path for the reason `evidence.capture`'s provenance guard
    gives: a synthetic client may not write into the published evidence tree.
    """
    cap = CaptureScript(tokens)
    emitted = Emitted()
    monkeypatch.setattr(M, "capture", cap)
    monkeypatch.setattr(M, "burst_client",
                        lambda fc, pool=0: type("C", (), {
                            "meta": type("Mt", (), {
                                "config": A.ClientFactory(region="us-east-1")
                                ._config("bedrock-runtime")})()})())
    monkeypatch.setattr(M.P, "emit", emitted)
    # The class is captured BEFORE the name is rebound, or the replacement would recurse
    # into itself. Re-rooted under tmp_path for the reason `evidence.capture`'s provenance
    # guard gives: a synthetic client may not write into the published evidence tree.
    store_cls = M.ConcurrentEvidenceStore
    monkeypatch.setattr(M, "ConcurrentEvidenceStore",
                        lambda run_id, family, case_id: store_cls(
                            run_id, family, case_id, root=tmp_path))
    monkeypatch.setattr(M, "N_CONTROL", 4)
    monkeypatch.setattr(M, "BURST_WORKERS", 4)
    rc = M.main(["--n", str(n)])
    emitted.rc = rc                                                  # type: ignore[attr-defined]
    emitted.capture = cap                                            # type: ignore[attr-defined]
    return emitted


def test_main_reaches_both_arms_and_publishes_true_when_throttles_appear(
        monkeypatch, tmp_path):
    e = _run_main(monkeypatch, tmp_path, ["ok"] * 4 + ["ok"] * 20 + ["throttle"] * 20)
    assert e.rc == 0                                                 # type: ignore[attr-defined]
    assert e.record["verdict"] == O.TRUE
    p = e.payload
    assert p["decision"]["verdict_path"] == "true"
    assert p["decision"]["mutation_inverted"] is True
    assert p["control_arm"]["tally"]["buckets"][M.EVALUATED] == 4
    assert p["burst_arm"]["tally"]["n_throttled"] == 20
    assert p["mutations"] == 0 and p["residue"]["clean"] is True
    assert p["residue"]["n_created"] == 0, "this case creates nothing"
    assert p["retry_config_asserted_before_first_request"][
        "effective_total_attempts"] == 1
    assert p["limiter_bypass"]["audit"]["burst_waits_delta"] == {}
    assert "ApplyGuardrail" in p["limiter_bypass"]["audit"]["control_waits_delta"]


def test_main_publishes_false_on_a_single_silent_pass(monkeypatch, tmp_path):
    e = _run_main(monkeypatch, tmp_path,
                  ["ok"] * 4 + ["ok"] * 19 + ["silent"] + ["throttle"] * 20)
    assert e.record["verdict"] == O.FALSE
    assert e.payload["decision"]["n_silent_pass"] == 1
    assert e.rc == 0, (                                              # type: ignore[attr-defined]
        "rc reports whether the test RAN, never whether the document was right")
    assert e.payload["rows_interesting"], (
        "the silent pass must be quotable from results/ without reopening the evidence tree")


def test_main_publishes_inconclusive_when_the_burst_was_never_throttled(
        monkeypatch, tmp_path):
    e = _run_main(monkeypatch, tmp_path, ["ok"] * 44)
    assert e.record["verdict"] == O.INCONCLUSIVE
    assert e.rc == 0                                                 # type: ignore[attr-defined]
    assert any("never throttled" in w
               for w in e.payload["decision"]["inconclusive_because"])


def test_main_returns_two_and_measures_nothing_when_the_control_fails(
        monkeypatch, tmp_path):
    """The control refuses before the burst spends anything."""
    e = _run_main(monkeypatch, tmp_path, ["ok", "silent", "ok", "ok"])
    assert e.rc == 2                                                 # type: ignore[attr-defined]
    assert e.record["verdict"] == O.INCONCLUSIVE
    assert e.capture.n == 4, (                                       # type: ignore[attr-defined]
        "the burst must not run: 480 unpaced requests on an unvalidated classifier would "
        "spend the money and prove nothing")
    assert "provably intervenes" in e.payload["verdict_reading"]


def test_main_returns_one_when_a_response_falls_in_no_bucket(monkeypatch, tmp_path):
    e = _run_main(monkeypatch, tmp_path,
                  ["ok"] * 4 + ["ok"] * 19 + ["weird"] + ["throttle"] * 20)
    assert e.rc == 1, "rc=1 is the unclassified exit"                # type: ignore[attr-defined]
    assert e.record["verdict"] == O.INCONCLUSIVE


@pytest.mark.parametrize("tokens", [
    ["ok"] * 4 + ["ok"] * 20 + ["throttle"] * 20,
    ["ok"] * 4 + ["ok"] * 19 + ["silent"] + ["throttle"] * 20,
    ["ok"] * 44,
    ["ok", "silent", "ok", "ok"],
])
def test_every_published_payload_carries_the_five_required_keys(
        monkeypatch, tmp_path, tokens):
    """Every payload, on every path, including the refusal path."""
    e = _run_main(monkeypatch, tmp_path, tokens)
    for key in ("verdict_rule", "verdict_reading", "what_true_does_not_prove",
                "why_this_matters_operationally", "expiry"):
        assert e.payload.get(key), f"payload is missing {key!r}"


def test_the_dry_run_makes_no_call_and_asserts_the_retry_config(capsys):
    assert M.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "RETRY CONFIG ASSERTED BEFORE ANY REQUEST" in out
    assert "effective_total_attempts=1" in out
    assert O.oracle_text(M.CASE) in out
    assert "ApplyGuardrail x492" in out, "the plan must state the bounded call count"
