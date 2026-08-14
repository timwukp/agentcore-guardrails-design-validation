"""`f1_config/06_eval_scope.py` — F1-26 / F1-27 / F1-28, every guard exercised offline.

WHY THIS FILE EXISTS
--------------------
All three cases in that script are confirmed by observing that NOTHING happened, and four
different failures produce the same nothing: a guardrail that was never created, a filter
that matches nothing, a request the service refused, and a genuine evaluation-scope boundary.
The script's whole design is a set of guards that separate those four. A guard proven only by
reasoning is not a guard (`feedback_vacuous_test_check`), and discovering a broken one from a
live run would cost four sacrificial guardrails, ~60 billable calls and — much worse — a
published TRUE that was really a misconfiguration.

So `main()` is driven end to end here, against fake `bedrock` and `bedrock-runtime` clients
that model the SERVICE's evaluation scope rather than the script's expectations, and the
verdict is read out of the emitted record.

WHY THE FAKE RUNTIME IS WRITTEN THE WAY IT IS
---------------------------------------------
`FakeRuntime` does not decide what the script should conclude. It is given a `scope` — the set
of placements this pretend guardrail evaluates — and a set of `langs_effective`, and it then
extracts the text from exactly those placements of the request the script actually sent and
matches it against the configuration the script actually created on `FakeBedrock`. Three
consequences, all deliberate:

  * a script that sent the payload to the wrong guardrail, or built the tool turn wrongly,
    gets no detection and the test fails — the fake cannot flatter it;
  * `scope={"text"}` and `scope={"text", "reasoning"}` are the TRUE and FALSE worlds of
    F1-27, and both are asserted, so the script is shown to distinguish them;
  * `langs_effective=frozenset()` is the LYING double: every call returns HTTP 200 with a
    well-formed body reporting no detection at all. That is the world where the guardrail is
    broken, and it must NOT produce TRUE. A double that only ever succeeds never reaches that
    branch (`feedback_unreachable_branch_in_fake`), which is the branch the whole design
    exists for.

There is a second lying double, `silent=True`, which returns 200 with an EMPTY body — no
`action`, no `assessments`, no `trace`. It is the shape a real endpoint takes when the trace
was not enabled or a response field was renamed, and it is the one that would make every arm
look un-evaluated at once.

THE MUTATION ARMS ARE NAMED FOR WHAT THEY KILL
----------------------------------------------
Each guard in the script has an arm here named after it, so a mutation run can report which
mutant died where. The mutants applied while writing this file, and the arm each was killed
by, are recorded in the report accompanying it — the point of the naming is that the next
person can repeat the run.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import awsclients as A                                               # noqa: E402
import evidence as E                                                # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "grx_f1_eval_scope", ROOT / "f1_config" / "06_eval_scope.py")
es = importlib.util.module_from_spec(_spec)
sys.modules["grx_f1_eval_scope"] = es
_spec.loader.exec_module(es)


# ===========================================================================
# doubles
# ===========================================================================

class Limiter:
    """Records what it was asked to pace. Not a no-op double.

    `create_probe_guardrail` and `apply_once` must throttle their own operations; a silent
    no-op would let a script that forgot `lim.wait` pass, and an unthrottled create loop earns
    a ThrottlingException that reads as a rejection.
    """

    def __init__(self) -> None:
        self.waited: list[str] = []

    def wait(self, operation: str, **_: object) -> float:
        self.waited.append(operation)
        return 0.0


TERM_LANG = {s["term"]: s["lang"] for s in es.LISTED}
SUPPORTED_LANGS = frozenset(s["lang"] for s in es.LISTED if s["supported"])
ALL_LANGS = frozenset(s["lang"] for s in es.LISTED)


class FakeBedrock:
    """The control plane. Remembers what was configured, because the runtime reads it."""

    def __init__(self, plan: dict, meta) -> None:                    # noqa: ANN001
        self.plan = plan
        self.meta = meta
        self.guardrails: dict[str, dict] = {}
        self.creates: list[dict] = []
        self.deletes: list[str] = []

    def create_guardrail(self, **kw):
        self.creates.append(kw)
        for frag in self.plan.get("create_reject", ()):
            if frag in kw["name"]:
                raise ClientError(
                    {"Error": {"Code": "ValidationException",
                               "Message": f"word policy rejected: {frag}"},
                     "ResponseMetadata": {"HTTPStatusCode": 400,
                                          "RequestId": f"rq-cr-{len(self.creates)}"}},
                    "CreateGuardrail")
        gid = f"gr-{len(self.guardrails) + 1:03d}"
        self.guardrails[gid] = kw
        return {"guardrailId": gid,
                "guardrailArn": f"arn:aws:bedrock:us-east-1:111122223333:guardrail/{gid}",
                "version": "DRAFT", "status": "CREATING",
                "ResponseMetadata": {"HTTPStatusCode": 202, "RequestId": f"rq-{gid}"}}

    def get_guardrail(self, **kw):
        gid = kw["guardrailIdentifier"]
        cfg = self.guardrails[gid]
        wp = cfg.get("wordPolicyConfig") or {}
        cp = cfg.get("contentPolicyConfig") or {}
        sip = cfg.get("sensitiveInformationPolicyConfig") or {}
        body: dict = {
            "guardrailId": gid, "name": cfg["name"],
            "status": self.plan.get("status", "READY"),
            "statusReasons": self.plan.get("status_reasons", []),
            "ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": f"rq-get-{gid}"},
        }
        if wp:
            body["wordPolicy"] = {
                "words": [{"text": w["text"]} for w in (wp.get("wordsConfig") or [])]}
        if cp:
            tier = (cp.get("tierConfig") or {}).get("tierName")
            # `tier_read_back_override` exists so the tier-confirmation guard has a mutant to
            # be killed by: a script that never compared requested against read-back would
            # pass with the two disagreeing.
            body["contentPolicy"] = {"tier": {
                "tierName": self.plan.get("tier_read_back_override") or tier}}
        if sip:
            body["sensitiveInformationPolicy"] = {"piiEntities": [
                {"type": p["type"], "action": p["action"]}
                for p in (sip.get("piiEntitiesConfig") or [])]}
        if "crossRegionConfig" in cfg:
            body["crossRegionDetails"] = {
                "guardrailProfileId": cfg["crossRegionConfig"]["guardrailProfileIdentifier"]}
        return body

    def delete_guardrail(self, **kw):
        gid = kw["guardrailIdentifier"]
        self.deletes.append(gid)
        if gid in self.plan.get("delete_fail", ()):
            raise ClientError(
                {"Error": {"Code": "ConflictException", "Message": "in use"},
                 "ResponseMetadata": {"HTTPStatusCode": 409, "RequestId": f"rq-del-{gid}"}},
                "DeleteGuardrail")
        self.guardrails.pop(gid, None)
        return {"ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": f"rq-del-{gid}"}}


def _guarded_texts(messages: list[dict], scope: frozenset[str]) -> list[str]:
    """Extract exactly the text a guardrail with this SCOPE would see.

    The whole point of the fake. `scope` is the set of placements the pretend service
    evaluates; anything outside it is invisible to matching, which is what an evaluation-scope
    boundary IS. The extraction walks the request the script actually sent, so a script that
    put its payload somewhere else gets no detection.
    """
    out: list[str] = []
    for m in messages:
        for c in m.get("content") or []:
            if "text" in c and "text" in scope:
                out.append(c["text"])
            if "guardContent" in c and "guardContent" in scope:
                out.append(c["guardContent"]["text"]["text"])
            if "reasoningContent" in c and "reasoning" in scope:
                rt = (c["reasoningContent"] or {}).get("reasoningText") or {}
                if "text" in rt:
                    out.append(rt["text"])
            if "toolUse" in c and "tool" in scope:
                out.append(json.dumps(c["toolUse"]["input"], sort_keys=True))
            if "toolResult" in c and "tool" in scope:
                for b in c["toolResult"].get("content") or []:
                    if "json" in b:
                        out.append(json.dumps(b["json"], sort_keys=True))
                    if "text" in b:
                        out.append(b["text"])
    return out


class FakeRuntime:
    """`ApplyGuardrail` and `Converse`, matching against what FakeBedrock was told to create.

    `langs_effective` models the language boundary F1-26 is about: a configured term matches
    only if its language is in that set. `frozenset()` is the broken-guardrail world — every
    response is a well-formed 200 reporting nothing — and it must not yield TRUE anywhere.
    """

    def __init__(self, bedrock: FakeBedrock, plan: dict, meta=None) -> None:  # noqa: ANN001
        self.bd = bedrock
        self.plan = plan
        # A genuine `bedrock-runtime` meta, not `bedrock`'s: `evidence.capture` reads
        # `client.meta.service_model.service_name` for the record's `service` field, so
        # borrowing the control plane's meta would file every ApplyGuardrail and Converse
        # record under the wrong service in the evidence tree.
        self.meta = meta if meta is not None else A.factory("us-east-1") \
            .bedrock_runtime().meta
        self.applies: list[dict] = []
        self.converses: list[dict] = []

    # -- helpers -------------------------------------------------------------
    def _words_for(self, gid: str) -> list[str]:
        cfg = self.bd.guardrails[gid]
        return [w["text"] for w in
                ((cfg.get("wordPolicyConfig") or {}).get("wordsConfig") or [])]

    def _pii_for(self, gid: str) -> list[str]:
        cfg = self.bd.guardrails[gid]
        return [p["type"] for p in
                ((cfg.get("sensitiveInformationPolicyConfig") or {})
                 .get("piiEntitiesConfig") or [])]

    def _word_matches(self, gid: str, texts: list[str]) -> list[str]:
        langs = self.plan.get("langs_effective", SUPPORTED_LANGS)
        hits = []
        for term in self._words_for(gid):
            lang = TERM_LANG.get(term, "en")
            if lang in langs and any(term in t for t in texts):
                hits.append(term)
        return sorted(set(hits))

    def _pii_matches(self, gid: str, texts: list[str]) -> list[str]:
        # `pii_dead` is the PII half of the lying double: the entity is configured, every call
        # returns 200 with a well-formed body, and nothing is ever detected. It exists because
        # the scope-based double cannot reach it — `ApplyGuardrail` has no placement to be
        # outside of, so silencing the scope leaves F1-28's ApplyGuardrail control firing.
        if self.plan.get("pii_dead") or not self._pii_for(gid):
            return []
        return sorted({e for e in self._pii_for(gid)
                       if e == "EMAIL" and any("@" in t for t in texts)})

    @staticmethod
    def _mask(text: str) -> str:
        return re.sub(r"\S+@\S+", "{EMAIL}", text)

    # -- operations ----------------------------------------------------------
    def apply_guardrail(self, **kw):
        self.applies.append(kw)
        gid = kw["guardrailIdentifier"]
        if self.plan.get("silent"):
            return {"ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": "rq-ag-silent"}}
        texts = [b["text"]["text"] for b in kw["content"] if "text" in b]
        words = self._word_matches(gid, texts)
        pii = self._pii_matches(gid, texts)
        total = sum(len(t) for t in texts)
        resp: dict = {
            "action": "GUARDRAIL_INTERVENED" if (words or pii) else "NONE",
            "assessments": [],
            "guardrailCoverage": {"textCharacters": {"guarded": total, "total": total}},
            "usage": {"wordPolicyUnits": 1 if words else 0,
                      "sensitiveInformationPolicyUnits": 1 if pii else 0},
            "outputs": [],
            "ResponseMetadata": {"HTTPStatusCode": 200,
                                 "RequestId": f"rq-ag-{len(self.applies)}"},
        }
        assessment: dict = {}
        if words:
            assessment["wordPolicy"] = {"customWords": [
                {"match": w, "action": "BLOCKED", "detected": True} for w in words]}
            resp["outputs"] = [{"text": es.BLOCKED_INPUT_MESSAGE}]
            resp["actionReason"] = "Custom word matched."
        if pii:
            assessment["sensitiveInformationPolicy"] = {"piiEntities": [
                {"match": "grx.probe.f128@example.com", "type": e,
                 "action": "ANONYMIZED", "detected": True} for e in pii]}
            resp["outputs"] = [{"text": self._mask(texts[0])}]
        if assessment:
            resp["assessments"] = [assessment]
        return resp

    def converse(self, **kw):
        self.converses.append(kw)
        arm = classify_converse_request(kw)
        if arm in self.plan.get("converse_reject", ()):
            raise ClientError(
                {"Error": {"Code": "ValidationException",
                           "Message": f"this model does not accept {arm}"},
                 "ResponseMetadata": {"HTTPStatusCode": 400,
                                      "RequestId": f"rq-cv-{len(self.converses)}"}},
                "Converse")
        if self.plan.get("silent"):
            return {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
                    "stopReason": "end_turn",
                    "ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": "rq-cv-silent"}}
        gid = kw["guardrailConfig"]["guardrailIdentifier"]
        scope = self.plan.get("scope", frozenset({"text", "guardContent"}))
        texts = _guarded_texts(kw["messages"], scope)
        all_texts = _guarded_texts(
            kw["messages"], frozenset({"text", "guardContent", "reasoning", "tool"}))
        words = self._word_matches(gid, texts)
        pii = self._pii_matches(gid, texts)
        assessment: dict = {"invocationMetrics": {"guardrailCoverage": {"textCharacters": {
            "guarded": sum(len(t) for t in texts),
            "total": sum(len(t) for t in all_texts)}}}}
        if words:
            assessment["wordPolicy"] = {"customWords": [
                {"match": w, "action": "BLOCKED", "detected": True} for w in words]}
        if pii:
            assessment["sensitiveInformationPolicy"] = {"piiEntities": [
                {"match": "grx.probe.f128@example.com", "type": e,
                 "action": "ANONYMIZED", "detected": True} for e in pii]}
        # A word BLOCK stops the turn. A PII ANONYMIZE does NOT — the turn completes with the
        # entity replaced. Modelled faithfully, because the script reading only `stopReason`
        # would have recorded a working PII control as an inactive guardrail.
        if words:
            out_text = es.BLOCKED_INPUT_MESSAGE
            stop = "guardrail_intervened"
        else:
            out_text = "Acknowledged."
            stop = "end_turn"
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": out_text}]}},
            "stopReason": stop,
            "usage": {"inputTokens": 20, "outputTokens": 5, "totalTokens": 25},
            "trace": {"guardrail": {
                "actionReason": "Custom word matched." if words else None,
                "inputAssessment": {gid: assessment}}},
            "ResponseMetadata": {"HTTPStatusCode": 200,
                                 "RequestId": f"rq-cv-{len(self.converses)}"},
        }


def classify_converse_request(kw: dict) -> str:
    """Name the arm a `Converse` request came from, by reading the request.

    Used by the fake to reject a specific placement, and asserted directly below. Derived from
    the request rather than passed in as a label: a label would let the script send anything
    and still have the fake behave as though the placement were correct, which is the
    `feedback_probe_must_reach_the_code` failure inside a test double.
    """
    kinds: list[tuple[str, str]] = []
    for m in kw.get("messages") or []:
        for c in m.get("content") or []:
            for k in ("text", "guardContent", "reasoningContent", "toolUse", "toolResult"):
                if k in c:
                    kinds.append((m["role"], k))
    if any(k == "reasoningContent" for _, k in kinds):
        role = next(r for r, k in kinds if k == "reasoningContent")
        return f"reasoning_{role}"
    if any(k == "toolResult" for _, k in kinds):
        for m in kw["messages"]:
            for c in m["content"]:
                if "toolResult" in c and any("json" in b
                                             for b in c["toolResult"]["content"]):
                    return "tool_result_json"
        return "tool_use_input"
    if any(k == "guardContent" for _, k in kinds):
        return "text_guarded"
    return "text_plain"


# ===========================================================================
# fixtures
# ===========================================================================

@pytest.fixture
def ledger(tmp_path):
    """A SYNTHETIC ledger, written into tmp_path.

    Synthetic rather than a copy of the live `state.json`, and that is safe here for a reason
    worth stating: this script reads exactly two things from the ledger — `run_id` and
    `expires_at`, both used for tagging — and no resource, ARN or role. F1-3's harness copies
    the real ledger because its control is BUILT from a real gateway ARN; nothing here is.
    Writing our own also keeps the live ledger unwritten, which a `State.load` + `write` cycle
    would not.
    """
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "run_id": "r20260810T130945Z", "region": "us-east-1",
        "expires_at": "2026-08-13T23:00:00+00:00",
        "account_masked": True, "n_resources": 0, "resources": [],
    }, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def real_meta():
    """A genuine `bedrock` service-model meta for the fake to borrow.

    Client construction is offline (botocore resolves credentials lazily), so this runs under
    the autouse `no_aws` socket block. Borrowed for the same reason F1-3's harness borrows
    one: it is why `capture`'s provenance guard tests `isinstance(client, BaseClient)` and not
    the type of `client.meta`.
    """
    return A.factory("us-east-1").bedrock().meta


def run_main(plan, *, ledger, real_meta, tmp_path, monkeypatch, argv=None):
    """Drive `main()` once against the fakes. Returns (rc, {case_id: (record, payload)})."""
    bd = FakeBedrock(plan, real_meta)
    rt = FakeRuntime(bd, plan)
    lim = Limiter()
    monkeypatch.setattr(es.A, "factory", lambda *a, **k: type(
        "F", (), {"bedrock": staticmethod(lambda: bd),
                  "bedrock_runtime": staticmethod(lambda: rt)})())
    monkeypatch.setattr(es.A, "limiter", lambda: lim)
    # Not a speed hack: the real spacing is 1.0s per Converse and a scenario sends 21 of them.
    # Zeroing the constant leaves the call site (`sleep(CONVERSE_SPACING_S)`) intact, so a
    # script that dropped the pacing call entirely would still be caught by the arm that
    # asserts it is there.
    monkeypatch.setattr(es, "CONVERSE_SPACING_S", 0.0)

    emitted: dict[str, tuple[dict, dict]] = {}

    def _emit(case_id, record, payload, store=None, **kw):            # noqa: ANN001
        emitted[case_id] = (record, payload)
        return tmp_path / f"{case_id}.json"
    monkeypatch.setattr(es.P, "emit", _emit)

    rc = es.main((argv or []) + ["--state", str(ledger),
                                 "--evidence-root", str(tmp_path / "evidence")])
    return rc, emitted, bd, rt, lim


BASELINE_PLAN: dict = {}          # every default: scope excludes reasoning and tool,
                                  # langs_effective is EN/FR/ES, nothing is rejected


# ===========================================================================
# offline preconditions
# ===========================================================================

def test_the_shipped_vocabulary_satisfies_every_property_the_design_claims():
    v = es.vocabulary_check()
    assert v["ok"], v["problems"]
    assert v["positive_control"] == es.CONTROL_TERM
    assert es.CONTROL_TERM in v["listed"]
    assert v["n_listed_supported"] >= 1 and v["n_listed_unsupported"] >= 1
    assert v["max_term_len"] <= v["sdk_max_term_len"] == 100


@pytest.mark.parametrize("mutate,expect", [
    ("control_off_list", "positive control"),
    ("duplicate_terms", "not distinct"),
    ("unlisted_is_listed", "on the configured list"),
    ("shared_ideograph", "character-level matcher"),
    ("containment", "contain one another"),
    ("too_long", "maximum is 100"),
    ("carrier_missing_term", "own carrier sentence"),
    ("no_unsupported", "nothing to measure"),
])
def test_vocabulary_check_catches_each_property_it_claims(monkeypatch, mutate, expect):
    """One arm per property, because a check that only ever passes reports nothing.

    Each mutation breaks exactly one of `vocabulary_check`'s stated properties and asserts
    the message names it. The load-bearing one is `control_off_list`: with the positive
    control absent, `provably_inert` becomes unreachable and every tier would report
    `indeterminate` for a reason a reader could not see from the data.
    """
    listed = list(copy.deepcopy(es.LISTED))
    unlisted = list(copy.deepcopy(es.UNLISTED))
    if mutate == "control_off_list":
        listed = [s for s in listed if s["term"] != es.CONTROL_TERM]
    elif mutate == "duplicate_terms":
        listed[1] = {**listed[1], "term": listed[0]["term"],
                     "carrier": listed[0]["carrier"]}
    elif mutate == "unlisted_is_listed":
        unlisted[0] = {**unlisted[0], "term": es.CONTROL_TERM,
                       "carrier": "a {t} b"}
    elif mutate == "shared_ideograph":
        unlisted[1] = {**unlisted[1], "term": "月食観察", "carrier": "昨晚的{t}。"}
    elif mutate == "containment":
        unlisted[0] = {**unlisted[0], "term": es.CONTROL_TERM + "x",
                       "carrier": "a {t} b"}
    elif mutate == "too_long":
        listed[1] = {**listed[1], "term": "z" * 101, "carrier": "a {t} b"}
    elif mutate == "carrier_missing_term":
        listed[1] = {**listed[1], "carrier": "no placeholder here"}
    elif mutate == "no_unsupported":
        listed = [s for s in listed if s["supported"]]
    monkeypatch.setattr(es, "LISTED", tuple(listed))
    monkeypatch.setattr(es, "UNLISTED", tuple(unlisted))
    v = es.vocabulary_check()
    assert not v["ok"], f"{mutate} was not caught at all"
    assert any(expect in p for p in v["problems"]), (
        f"{mutate}: expected a problem naming {expect!r}, got {v['problems']}")


def test_the_filler_turns_carry_neither_payload():
    f = es.filler_check()
    assert f["ok"], f["problems"]
    assert es.SENTINEL_27 not in es.FILLER_USER
    assert "@" not in es.FILLER_FOLLOWUP


def test_filler_check_catches_a_filler_that_carries_the_sentinel(monkeypatch):
    monkeypatch.setattr(es, "FILLER_USER", f"Please {es.SENTINEL_27} the log.")
    f = es.filler_check()
    assert not f["ok"]
    assert any("sentinel" in p for p in f["problems"])


def test_filler_check_catches_a_filler_that_could_carry_pii(monkeypatch):
    monkeypatch.setattr(es, "FILLER_FOLLOWUP", "cc me at ops@example.com")
    f = es.filler_check()
    assert not f["ok"]
    assert any("EMAIL" in p or "'@'" in p for p in f["problems"])


# ===========================================================================
# byte-identity: the guard F1-27 and F1-28 rest on
# ===========================================================================

def test_payload_identity_returns_one_digest_and_records_it_per_arm():
    out = es.payload_identity("F1-27", {"a": "x", "b": "x", "c": "x"})
    assert out["n_arms_compared"] == 3
    assert set(out["per_arm_sha256"]) == {"a", "b", "c"}
    assert len(set(out["per_arm_sha256"].values())) == 1
    assert out["payload_sha256"] == es.sha("x")
    assert out["payload_len_chars"] == 1


def test_payload_identity_refuses_arms_that_differ_by_one_character():
    with pytest.raises(ValueError) as ei:
        es.payload_identity("F1-27", {"text": "attack the reactor",
                                      "reasoning": "attack the reactor "})
    msg = str(ei.value)
    assert "F1-27" in msg
    assert "byte-identical" in msg
    assert "2 distinct sha256" in msg


def test_payload_identity_refuses_a_single_arm_because_the_check_would_be_vacuous():
    """A one-arm identity assertion cannot fail, so it must not be allowed to report clean."""
    with pytest.raises(ValueError) as ei:
        es.payload_identity("F1-28", {"only": "x"})
    assert "at least two arms" in str(ei.value)
    assert "vacuously true" in str(ei.value)


def _find_payload_occurrences(obj, needle: str) -> list[str]:
    """Every JSON path in `obj` whose string value equals `needle`, exactly."""
    found: list[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and node == needle:
            found.append(path)
    walk(obj, "")
    return found


@pytest.mark.parametrize("case_id,builder,payload", [
    ("F1-27", es.converse_arms_27, es.PAYLOAD_27),
    ("F1-28", es.converse_arms_28, es.PAYLOAD_28),
])
def test_every_arm_carries_the_payload_exactly_once_in_the_request_it_will_send(
        case_id, builder, payload):
    """Read out of the REQUEST BODY, not out of the arm's label.

    `payload_identity` compares the strings a caller hands it, which proves the caller passed
    identical strings — not that the requests contain them. This walks each arm's actual
    request dict and asserts the payload appears exactly once, so an arm whose builder
    interpolated a label, truncated, or put the payload in two places fails here.
    """
    arms = builder("model-x")
    assert arms, f"{case_id}: zero arms built — a zero-arm plan is an error, not a pass"
    for name, spec in arms.items():
        paths = _find_payload_occurrences(spec["request"], payload)
        assert len(paths) == 1, (
            f"{case_id}/{name}: the payload appears at {paths} in the request; exactly one "
            f"placement is the entire content of this case")
        assert es.PAYLOAD_27 != es.PAYLOAD_28


def test_the_two_cases_do_not_share_a_payload_or_a_sentinel():
    """Otherwise one case's evidence would match the other's and neither is attributable."""
    assert es.PAYLOAD_27 != es.PAYLOAD_28
    assert es.SENTINEL_27 not in es.PAYLOAD_28
    assert es.SENTINEL_27 != es.CONTROL_TERM, (
        "F1-26's positive control and F1-27's sentinel must differ, or a match in the "
        "evidence tree cannot be attributed to a case")


def test_the_reasoning_and_tool_arms_place_the_payload_where_the_case_says_they_do():
    """The placement itself, asserted — not merely the arm's name."""
    a27 = es.converse_arms_27("m")
    assert a27["text_plain"]["request"]["messages"][0]["content"][0]["text"] == es.PAYLOAD_27
    assert (a27["text_guarded"]["request"]["messages"][0]["content"][0]
            ["guardContent"]["text"]["text"]) == es.PAYLOAD_27
    assert (a27["reasoning_user"]["request"]["messages"][0]["content"][0]
            ["reasoningContent"]["reasoningText"]["text"]) == es.PAYLOAD_27
    ra = a27["reasoning_assistant"]["request"]["messages"]
    assert [m["role"] for m in ra] == ["user", "assistant", "user"]
    assert (ra[1]["content"][0]["reasoningContent"]["reasoningText"]["text"]
            == es.PAYLOAD_27)

    a28 = es.converse_arms_28("m")
    assert a28["text_converse"]["request"]["messages"][0]["content"][0]["text"] \
        == es.PAYLOAD_28
    tu = a28["tool_use_input"]["request"]
    assert tu["toolConfig"]["tools"] == [es.TOOL_SPEC_28], (
        "a toolUse block referring to an undeclared tool is malformed, and its rejection "
        "would say nothing about PII")
    assert tu["messages"][1]["content"][0]["toolUse"]["input"]["note"] == es.PAYLOAD_28
    trj = a28["tool_result_json"]["request"]
    assert (trj["messages"][2]["content"][0]["toolResult"]["content"][0]["json"]["note"]
            == es.PAYLOAD_28)
    assert (trj["messages"][1]["content"][0]["toolUse"]["toolUseId"]
            == trj["messages"][2]["content"][0]["toolResult"]["toolUseId"]), (
        "the toolResult must answer the toolUse it follows, or the turn is malformed")


# ===========================================================================
# the SDK facts the two paired cases hinge on
# ===========================================================================

def test_sdk_shape_facts_reads_the_qualifier_enum_and_the_two_unions():
    """The four facts the pre-registered methods stand or fall on, read from botocore."""
    f = es.sdk_shape_facts()
    assert f["apply_guardrail_content_block_members"] == ["image", "text"], (
        "if ApplyGuardrail ever gains a reasoning or tool block, F1-27 and F1-28 become "
        "answerable there and this script's INCONCLUSIVE reasons go stale")
    assert f["guardrail_content_qualifier_enum"] == [
        "grounding_source", "query", "guard_content"], (
        "the `qualifiers` member is what F1-28's method hinges on; a fourth value naming tool "
        "content would make the ApplyGuardrail half executable")
    assert f["converse_guard_content_qualifier_enum"] == \
        f["guardrail_content_qualifier_enum"]
    assert "reasoningContent" in f["converse_content_block_members"]
    assert "toolUse" in f["converse_content_block_members"]
    assert "toolResult" in f["converse_content_block_members"]
    assert f["converse_content_block_is_union"] is True
    assert f["converse_reasoning_content_members"] == ["reasoningText", "redactedContent"]
    assert f["converse_reasoning_text_members"] == ["signature", "text"]
    assert set(f["converse_tool_use_members"]) >= {"toolUseId", "name", "input"}
    assert "json" in f["converse_tool_result_content_members"]


def test_sdk_shape_facts_records_which_preregistered_half_is_executable():
    f = es.sdk_shape_facts()
    assert f["f1_27_reasoning_is_sendable"]["method_executable"] is True, (
        "reasoningContent IS reachable on ConverseRequest.messages[].content[], so F1-27's "
        "method is constructible and an INCONCLUSIVE must not claim otherwise")
    assert f["f1_28_tool_use_is_sendable"]["method_executable_on_converse"] is True
    assert f["f1_28_tool_use_is_sendable"]["method_executable_on_apply_guardrail"] is False, (
        "the sealed method names ApplyGuardrail and ApplyGuardrail cannot carry a tool block; "
        "recording that is the difference between an honest gap and a substituted mechanism")
    assert "CANNOT BE CONSTRUCTED" in \
        f["f1_28_tool_use_is_sendable"]["why_not_on_apply_guardrail"]


def test_sdk_shape_facts_confirms_where_the_tier_and_the_cross_region_config_live():
    f = es.sdk_shape_facts()
    assert "tierConfig" not in f["create_guardrail_word_policy_members"], (
        "wordPolicyConfig has no tier, which is why 'on either tier' has to be carried by "
        "contentPolicyConfig")
    assert "tierConfig" in f["create_guardrail_content_policy_members"]
    assert f["cross_region_config_is_top_level"] is True
    assert f["cross_region_config_members"] == ["guardrailProfileIdentifier"]


def test_main_refuses_a_zero_length_shape_read(monkeypatch, ledger, tmp_path, capsys):
    """A zero-length read is a broken accessor, not an absent surface.

    Without this, an accessor change that returned `[]` would let the script publish "no
    qualifier names tool content" from a list it never read
    (`feedback_zero_file_scan_is_error`).
    """
    real = es.sdk_shape_facts()
    broken = {**real, "guardrail_content_qualifier_enum": []}
    monkeypatch.setattr(es, "sdk_shape_facts", lambda: broken)
    rc = es.main(["--dry-run", "--state", str(ledger)])
    assert rc == 2
    assert "zero-length read" in capsys.readouterr().err


def test_the_tier_config_carries_only_inert_filters():
    """The tier-bearing content filter must not be able to contribute a detection."""
    cfg = es.tier_config("CLASSIC")
    assert cfg["tierConfig"] == {"tierName": "CLASSIC"}
    f = cfg["filtersConfig"][0]
    assert f["inputStrength"] == f["outputStrength"] == "NONE"
    assert f["inputAction"] == f["outputAction"] == "NONE"
    assert f["inputEnabled"] is False and f["outputEnabled"] is False


def test_the_word_and_pii_configs_state_every_action_explicitly():
    """A term configured with action NONE reports detected=True and blocks nothing."""
    for w in es.word_config()["wordsConfig"]:
        assert w["inputAction"] == w["outputAction"] == "BLOCK"
        assert w["inputEnabled"] is True and w["outputEnabled"] is True
    supported = {w["text"] for w in es.word_config(supported_only=True)["wordsConfig"]}
    assert supported == {s["term"] for s in es.LISTED if s["supported"]}
    assert es.CONTROL_TERM in supported, (
        "the attribution control must still carry the positive control, or a rejected create "
        "cannot be attributed to the unsupported-language words")
    p = es.pii_config()["piiEntitiesConfig"][0]
    assert p["type"] == es.PII_ENTITY_28
    assert p["action"] == p["inputAction"] == p["outputAction"] == "ANONYMIZE", (
        "the sealed oracle's word is 'masked'; BLOCK would replace the whole turn and is a "
        "different observation")


# ===========================================================================
# reading a response
# ===========================================================================

def _rec(op, *, ok, response=None, error_code="", http=200):
    return E.Record(case_id="F1-28", operation=op, service="bedrock-runtime",
                    region="us-east-1", params={}, ok=ok, http_status=http,
                    request_id="rid-1", response=response, error_code=error_code,
                    error_message="" if ok else "nope", path="evidence/x/0001.json")


def test_read_apply_keeps_a_failure_as_data_and_never_as_a_non_detection():
    """The distinction the whole design rests on: refused is not un-evaluated."""
    out = es.read_apply(_rec("apply_guardrail", ok=False, error_code="ValidationException",
                             http=400))
    assert out["sendable"] is False
    assert out["error_code"] == "ValidationException"
    assert out["intervened"] is False
    assert out["words_matched"] == [] and out["pii_detected"] == []
    assert out["request_id"] == "rid-1"


def test_read_apply_reports_masking_coverage_and_the_matched_entity():
    resp = {"action": "GUARDRAIL_INTERVENED",
            "outputs": [{"text": "Send it to {EMAIL} before Friday."}],
            "guardrailCoverage": {"textCharacters": {"guarded": 40, "total": 66}},
            "assessments": [{"sensitiveInformationPolicy": {"piiEntities": [
                {"match": "a@b.com", "type": "EMAIL", "action": "ANONYMIZED",
                 "detected": True}]}}]}
    out = es.read_apply(_rec("apply_guardrail", ok=True, response=resp))
    assert out["intervened"] is True
    assert out["pii_detected"] == ["EMAIL"]
    assert out["coverage_guarded"] == 40 and out["coverage_total"] == 66, (
        "guarded < total is what 'part of this request was not evaluated' looks like on the "
        "wire, and it is the mechanism evidence for a scope claim")


def test_read_apply_ignores_an_entity_the_service_reported_as_not_detected():
    resp = {"action": "NONE", "outputs": [], "assessments": [
        {"sensitiveInformationPolicy": {"piiEntities": [
            {"match": "", "type": "EMAIL", "action": "NONE", "detected": False}]}}]}
    out = es.read_apply(_rec("apply_guardrail", ok=True, response=resp))
    assert out["pii_detected"] == [], (
        "a filter that was evaluated and found nothing reports detected=False; counting it "
        "would make every configured entity a detection")
    assert out["intervened"] is False


def test_read_converse_separates_masking_from_intervention():
    """The asymmetry a single boolean would have destroyed.

    ANONYMIZE does not stop the turn, so F1-28's working text control has no
    `guardrail_intervened` stop reason at all. A script reading only `intervened` would have
    recorded it as an inactive guardrail and published INCONCLUSIVE over a good run.
    """
    assessment = {
        "sensitiveInformationPolicy": {"piiEntities": [
            {"type": "EMAIL", "action": "ANONYMIZED", "detected": True}]},
        "invocationMetrics": {"guardrailCoverage": {
            "textCharacters": {"guarded": 10, "total": 90}}},
    }
    resp = {"stopReason": "end_turn",
            "output": {"message": {"content": [{"text": "Acknowledged."}]}},
            "trace": {"guardrail": {"inputAssessment": {"gr-1": assessment}}}}
    out = es.read_converse(_rec("converse", ok=True, response=resp),
                           blocked_message=es.BLOCKED_INPUT_MESSAGE)
    assert out["handled"] is True
    assert out["intervened"] is False
    assert out["stop_reason_is_intervention"] is False
    assert out["pii_detected"] == ["EMAIL"]
    assert out["coverage_guarded"] == 10 and out["coverage_total"] == 90


def test_read_converse_recognises_an_intervention_by_three_independent_signals():
    assessment = {"wordPolicy": {"customWords": [
        {"match": es.SENTINEL_27, "action": "BLOCKED", "detected": True}]}}
    resp = {"stopReason": "guardrail_intervened",
            "output": {"message": {"content": [{"text": es.BLOCKED_INPUT_MESSAGE}]}},
            "trace": {"guardrail": {"inputAssessment": {"gr-1": assessment}}}}
    out = es.read_converse(_rec("converse", ok=True, response=resp),
                           blocked_message=es.BLOCKED_INPUT_MESSAGE)
    assert out["intervened"] is True and out["handled"] is True
    assert out["stop_reason_is_intervention"] is True
    assert out["blocked_message_echoed"] is True
    assert out["words_matched"] == [es.SENTINEL_27]


def test_read_converse_treats_a_refusal_as_unsendable():
    out = es.read_converse(_rec("converse", ok=False, error_code="ValidationException",
                                http=400),
                           blocked_message=es.BLOCKED_INPUT_MESSAGE)
    assert out["sendable"] is False
    assert out["intervened"] is False and out["handled"] is False
    assert out["error_code"] == "ValidationException"


def test_read_converse_on_an_empty_body_reports_nothing_rather_than_guessing():
    """The silent double's shape: 200, no trace, no stop reason."""
    out = es.read_converse(_rec("converse", ok=True, response={}),
                           blocked_message=es.BLOCKED_INPUT_MESSAGE)
    assert out["sendable"] is True
    assert out["trace_present"] is False
    assert out["handled"] is False and out["intervened"] is False


# ===========================================================================
# F1-26's per-tier disposition — the rejected / provably-inert split
# ===========================================================================

READY_CELL = {
    "tier": "CLASSIC", "create_accepted": True, "ready": True, "status": "READY",
    "tier_read_back": "CLASSIC", "unlisted_blocked": [], "unsupported_blocked": [],
    "control_blocked": ["alone", "embedded"], "n_unsupported_cells": 8,
}


def test_a_tier_that_sent_no_unsupported_cell_at_all_is_indeterminate():
    """The `--n` smoke trap, and it was a live defect before this arm existed.

    `--n` is a PREFIX, not a sample, and the first entries of the item list are the SUPPORTED
    languages — so `--n 1` sends the EN control and nothing else. The control fires, nothing
    unsupported blocks because nothing unsupported was sent, and `provably_inert` (hence TRUE)
    was the result: a verdict from a run that never probed the claim.
    """
    d = es.tier_disposition({**READY_CELL, "n_unsupported_cells": 0})
    assert d["disposition"] == es.DISPOSITION_INDETERMINATE
    assert d["satisfies_claim"] is False
    assert "never probed" in d["why"]


def test_provably_inert_requires_the_positive_control_to_have_fired():
    """The single most important assertion in this file.

    Same data in both calls except whether the EN control blocked. With it, the disposition is
    `provably_inert` and F1-26 can be TRUE. Without it, NOTHING blocked — which is exactly
    what a dropped term, a typo or the wrong assessment field produces — and the disposition
    must be `indeterminate`. An implementation that returned `provably_inert` for "no
    unsupported term blocked" would return it for a guardrail that fires for nothing at all.
    """
    good = es.tier_disposition(READY_CELL)
    assert good["disposition"] == es.DISPOSITION_INERT
    assert good["satisfies_claim"] is True

    dead = es.tier_disposition({**READY_CELL, "control_blocked": []})
    assert dead["disposition"] == es.DISPOSITION_INDETERMINATE
    assert dead["satisfies_claim"] is False
    assert "POSITIVE CONTROL" in dead["why"]
    assert es.CONTROL_TERM in dead["why"]


def test_a_rejected_create_is_the_first_disjunct_only_when_attributable():
    attributable = es.tier_disposition({"tier": "STANDARD", "create_accepted": False,
                                        "control_only_accepted": True})
    assert attributable["disposition"] == es.DISPOSITION_REJECTED
    assert attributable["satisfies_claim"] is True

    both_refused = es.tier_disposition({"tier": "STANDARD", "create_accepted": False,
                                        "control_only_accepted": False})
    assert both_refused["disposition"] == es.DISPOSITION_INDETERMINATE
    assert "also refused" in both_refused["why"]

    never_tried = es.tier_disposition({"tier": "STANDARD", "create_accepted": False,
                                       "control_only_accepted": None})
    assert never_tried["disposition"] == es.DISPOSITION_INDETERMINATE
    assert "not attempted" in never_tried["why"]


def test_one_blocking_unsupported_cell_outranks_a_working_control():
    d = es.tier_disposition({**READY_CELL, "unsupported_blocked": ["ja/alone"]})
    assert d["disposition"] == es.DISPOSITION_BLOCKS
    assert d["satisfies_claim"] is False


def test_an_unlisted_block_makes_every_reading_unattributable():
    """Checked BEFORE the blocking test: if something else is matching, neither reading holds."""
    d = es.tier_disposition({**READY_CELL, "unlisted_blocked": ["en/alone"],
                             "unsupported_blocked": ["ja/alone"]})
    assert d["disposition"] == es.DISPOSITION_INDETERMINATE
    assert "never configured" in d["why"]


def test_a_guardrail_that_never_became_ready_is_indeterminate():
    d = es.tier_disposition({**READY_CELL, "ready": False, "status": "CREATING"})
    assert d["disposition"] == es.DISPOSITION_INDETERMINATE
    assert "READY" in d["why"]


def test_an_unconfirmed_tier_is_indeterminate():
    d = es.tier_disposition({**READY_CELL, "tier_read_back": "STANDARD"})
    assert d["disposition"] == es.DISPOSITION_INDETERMINATE
    assert "tier could not be confirmed" in d["why"]


def test_only_two_dispositions_satisfy_the_sealed_disjunction():
    assert set(es.DISPOSITION_SATISFIES_CLAIM) == {
        es.DISPOSITION_REJECTED, es.DISPOSITION_INERT}
    assert es.DISPOSITION_BLOCKS not in es.DISPOSITION_SATISFIES_CLAIM
    assert es.DISPOSITION_INDETERMINATE not in es.DISPOSITION_SATISFIES_CLAIM


def _cell(disposition, satisfies, why="w"):
    return {"disposition": disposition, "satisfies_claim": satisfies, "why": why}


def test_the_two_disjuncts_may_be_satisfied_by_different_tiers():
    """A service that refuses the words on one tier and ignores them on the other.

    Both halves of the sealed sentence are satisfied, by different mechanisms, and the
    per-tier dispositions must survive the roll-up: a boolean would have erased the
    distinction the oracle's own wording draws.
    """
    r = es.f1_26_reading({
        "CLASSIC": _cell(es.DISPOSITION_INERT, True),
        "STANDARD": _cell(es.DISPOSITION_REJECTED, True)})
    assert r["observed"] is True
    assert r["n_rejected"] == 1 and r["n_provably_inert"] == 1
    assert r["dispositions"] == {"CLASSIC": es.DISPOSITION_INERT,
                                 "STANDARD": es.DISPOSITION_REJECTED}


def test_one_blocking_tier_makes_the_case_false():
    r = es.f1_26_reading({
        "CLASSIC": _cell(es.DISPOSITION_INERT, True),
        "STANDARD": _cell(es.DISPOSITION_BLOCKS, False)})
    assert r["observed"] is False
    assert r["tiers_blocking"] == ["STANDARD"]


def test_one_indeterminate_tier_blocks_a_true_verdict():
    r = es.f1_26_reading({
        "CLASSIC": _cell(es.DISPOSITION_INERT, True),
        "STANDARD": _cell(es.DISPOSITION_INDETERMINATE, False, why="control dead")})
    assert r["observed"] is None
    assert r["tiers_indeterminate"] == ["STANDARD"]
    assert "control dead" in r["why"]


def test_no_tiers_at_all_is_not_a_true_verdict():
    r = es.f1_26_reading({})
    assert r["observed"] is None
    assert r["n_tiers"] == 0


# ===========================================================================
# the paired decision rule
# ===========================================================================

def _arm(name, *, control=False, trials=3, sendable=3, fired=0, errors=()):
    return {"arm": name, "placement": name, "is_control": control,
            "n_trials": trials, "n_sendable": sendable,
            "n_unsendable": trials - sendable, "n_fired": fired,
            "error_codes": list(errors),
            "sendable_all": sendable == trials, "sendable_none": sendable == 0,
            "fired_all": bool(sendable) and fired == sendable,
            "fired_none": bool(sendable) and fired == 0,
            "consistent": bool(sendable) and fired in (0, sendable)}


def test_paired_true_needs_a_control_that_fired_and_a_placement_that_did_not():
    r = es.paired_reading(
        controls={"text_plain": _arm("text_plain", control=True, fired=3)},
        placements={"reasoning_user": _arm("reasoning_user", fired=0)},
        signal="intervened", control_required="text_plain")
    assert r["observed"] is True
    assert r["placement_arms_that_fired"] == []


def test_paired_false_when_the_placement_arm_also_fired():
    r = es.paired_reading(
        controls={"text_plain": _arm("text_plain", control=True, fired=3)},
        placements={"reasoning_user": _arm("reasoning_user", fired=3)},
        signal="intervened", control_required="text_plain")
    assert r["observed"] is False
    assert r["placement_arms_that_fired"] == ["reasoning_user"]


def test_paired_inconclusive_when_the_control_never_fired():
    """'Nothing fired anywhere' must not read as TRUE. The mandated control."""
    r = es.paired_reading(
        controls={"text_plain": _arm("text_plain", control=True, fired=0)},
        placements={"reasoning_user": _arm("reasoning_user", fired=0)},
        signal="intervened", control_required="text_plain")
    assert r["observed"] is None
    assert "control arm" in r["why"]
    assert "misconfiguration" in r["why"]


def test_paired_inconclusive_when_the_control_arm_is_absent_entirely():
    r = es.paired_reading(controls={}, placements={"x": _arm("x")},
                          signal="intervened", control_required="text_plain")
    assert r["observed"] is None


def test_paired_inconclusive_when_no_placement_arm_was_sendable():
    """The design point the whole SDK-fact table exists for.

    A request the service refused is not a request whose content went un-evaluated. Both
    produce zero interventions, and the oracle's TRUE branch requires the second.
    """
    r = es.paired_reading(
        controls={"text_plain": _arm("text_plain", control=True, fired=3)},
        placements={"reasoning_user": _arm("reasoning_user", sendable=0,
                                           errors=["ValidationException"])},
        signal="intervened", control_required="text_plain")
    assert r["observed"] is None
    assert "not be exercised" in r["why"]
    assert r["placement_arms_unsendable"] == {
        "reasoning_user": ["ValidationException"]}


def test_paired_uses_the_arms_that_were_sendable_when_only_some_were():
    """One rejected placement must not veto a decision the other placement supports."""
    r = es.paired_reading(
        controls={"text_plain": _arm("text_plain", control=True, fired=3)},
        placements={"reasoning_user": _arm("reasoning_user", sendable=0,
                                           errors=["ValidationException"]),
                    "reasoning_assistant": _arm("reasoning_assistant", fired=0)},
        signal="intervened", control_required="text_plain")
    assert r["observed"] is True
    assert r["placement_arms_sendable"] == ["reasoning_assistant"]
    assert "reasoning_user" in r["placement_arms_unsendable"]


def test_a_split_placement_arm_is_undecided_and_not_rounded():
    r = es.paired_reading(
        controls={"text_plain": _arm("text_plain", control=True, fired=3)},
        placements={"reasoning_user": _arm("reasoning_user", fired=1)},
        signal="intervened", control_required="text_plain")
    assert r["observed"] is None
    assert r["placement_arms_split"] == ["reasoning_user"]
    assert "split" in r["why"]


def test_arm_summary_reports_a_split_and_counts_unsendable_trials_separately():
    rows = [{"sendable": True, "intervened": True, "error_code": None,
             "coverage_guarded": 1, "coverage_total": 1, "request_id": "a",
             "stop_reason": "guardrail_intervened"},
            {"sendable": True, "intervened": False, "error_code": None,
             "coverage_guarded": 1, "coverage_total": 2, "request_id": "b",
             "stop_reason": "end_turn"},
            {"sendable": False, "intervened": False, "error_code": "ThrottlingException",
             "coverage_guarded": None, "coverage_total": None, "request_id": "c",
             "stop_reason": None}]
    s = es.arm_summary("x", {"placement": "p", "is_control": False}, rows,
                       key="intervened")
    assert (s["n_trials"], s["n_sendable"], s["n_unsendable"], s["n_fired"]) == (3, 2, 1, 1)
    assert s["consistent"] is False
    assert s["error_codes"] == ["ThrottlingException"]
    assert s["signal_read"] == "intervened"


def test_arm_summary_reads_the_key_it_was_given_and_not_the_other_one():
    """F1-27 reads `intervened` and F1-28 reads `handled`; neither may borrow the other's."""
    rows = [{"sendable": True, "intervened": False, "handled": True, "error_code": None,
             "coverage_guarded": None, "coverage_total": None, "request_id": "a",
             "stop_reason": "end_turn"}]
    assert es.arm_summary("x", {}, rows, key="handled")["n_fired"] == 1
    assert es.arm_summary("x", {}, rows, key="intervened")["n_fired"] == 0


# ===========================================================================
# end to end, against the fakes
# ===========================================================================

def test_the_baseline_world_confirms_all_three_claims(ledger, real_meta, tmp_path,
                                                      monkeypatch):
    """Scope excludes reasoning and tool; the word filter works only for EN/FR/ES.

    That is the world in which all three document claims are true, and it is the world where
    a broken harness is hardest to notice — so every verdict, every count and the teardown are
    all asserted here.
    """
    rc, emitted, bd, rt, lim = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                                        tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rc == 0, "rc reports whether the test RAN; a clean run with a clean teardown is 0"
    assert set(emitted) == set(es.CASES)
    for cid in es.CASES:
        rec, payload = emitted[cid]
        assert rec["verdict"] == O.TRUE, (cid, rec.get("notes"))
        assert payload["n_trials"] > 0, f"{cid} published a verdict off zero trials"
    # F1-26's TRUE is the PROVABLY-INERT disjunct on both tiers, with the control firing.
    r26 = emitted["F1-26"][1]["reading"]
    assert r26["dispositions"] == {t: es.DISPOSITION_INERT for t in es.TIERS}
    assert r26["n_rejected"] == 0 and r26["n_provably_inert"] == 2
    for tier in es.TIERS:
        cell = emitted["F1-26"][1]["per_tier"][tier]
        assert cell["control_blocked"], f"{tier}: the positive control did not fire"
        assert cell["unsupported_blocked"] == []
        assert cell["unlisted_blocked"] == []
    # Every probe guardrail deleted.
    assert len(bd.deletes) == 4, bd.deletes
    for cid in es.CASES:
        assert emitted[cid][1]["residue"]["clean"] is True
    assert "CreateGuardrail" in lim.waited and "ApplyGuardrail" in lim.waited


def test_a_service_that_evaluates_reasoning_blocks_refutes_f1_27(ledger, real_meta, tmp_path,
                                                                monkeypatch):
    """The FALSE world, and the arm that proves the TRUE above was not structural."""
    plan = {"scope": frozenset({"text", "guardContent", "reasoning"})}
    rc, emitted, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rc == 0, "refuting the document is a successful test"
    assert emitted["F1-27"][0]["verdict"] == O.FALSE
    assert emitted["F1-27"][1]["reading"]["placement_arms_that_fired"] == [
        "reasoning_assistant", "reasoning_user"]
    assert emitted["F1-28"][0]["verdict"] == O.TRUE, (
        "F1-28's scope is unchanged, so it must be unaffected")


def test_a_service_that_scans_tool_blocks_refutes_f1_28(ledger, real_meta, tmp_path,
                                                        monkeypatch):
    plan = {"scope": frozenset({"text", "guardContent", "tool"})}
    rc, emitted, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rc == 0
    assert emitted["F1-28"][0]["verdict"] == O.FALSE
    assert emitted["F1-28"][1]["reading"]["placement_arms_that_fired"] == [
        "tool_result_json", "tool_use_input"], (
        "both readings of 'tool_use output parameter' must be reported, not just one")
    assert emitted["F1-27"][0]["verdict"] == O.TRUE


def test_a_word_filter_effective_in_every_language_refutes_f1_26(ledger, real_meta, tmp_path,
                                                                 monkeypatch):
    plan = {"langs_effective": ALL_LANGS}
    rc, emitted, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rc == 0
    rec, payload = emitted["F1-26"]
    assert rec["verdict"] == O.FALSE
    assert payload["reading"]["tiers_blocking"] == list(es.TIERS)
    assert payload["mutation"]["inverted"] is False, (
        "the language mutation did not invert: the filter fires for every language, so "
        "language is not the variable it depends on")


def test_a_guardrail_that_fires_for_nothing_is_inconclusive_and_never_true(
        ledger, real_meta, tmp_path, monkeypatch):
    """THE LYING DOUBLE. Every call returns 200 with a well-formed body and no detection.

    This is the world in which the guardrail is broken, and it produces byte-for-byte the same
    absence of interventions as a genuine evaluation-scope boundary. Reading it as TRUE would
    publish a misconfiguration as a service property — three times over, in one run
    (`feedback_probe_must_reach_the_code`).
    """
    plan = {"langs_effective": frozenset(), "scope": frozenset(), "pii_dead": True}
    rc, emitted, bd, rt, _ = run_main(plan, ledger=ledger, real_meta=real_meta,
                                      tmp_path=tmp_path, monkeypatch=monkeypatch)
    for cid in es.CASES:
        rec, payload = emitted[cid]
        assert rec["verdict"] == O.INCONCLUSIVE, (
            f"{cid} published {rec['verdict']} from a run where NOTHING fired anywhere")
    assert emitted["F1-26"][1]["reading"]["dispositions"] == {
        t: es.DISPOSITION_INDETERMINATE for t in es.TIERS}
    for cid in ("F1-27", "F1-28"):
        assert emitted[cid][1]["reading"]["control_fired_every_trial"] is False, cid
    # The calls really were made and really came back 200 — so the INCONCLUSIVE is about the
    # data and not about a harness that failed to send anything.
    assert rt.applies and rt.converses
    assert rc == 0, "the arms ran and cleaned up; the verdicts are the finding"


def test_a_dead_scope_alone_downgrades_f1_28_through_the_transport_control(
        ledger, real_meta, tmp_path, monkeypatch):
    """The half of the lying double the scope switch cannot reach, and what catches it.

    `ApplyGuardrail` has no placement to be outside of, so silencing the CONVERSE scope leaves
    F1-28's ApplyGuardrail text control firing normally while its Converse text control goes
    quiet. The primary control therefore passes and the tool arms are silent — the exact shape
    that would read as TRUE. It is the TRANSPORT control that refuses it, and this arm is the
    only place that path is exercised.
    """
    plan = {"scope": frozenset(), "langs_effective": frozenset()}
    rc, emitted, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    rec, payload = emitted["F1-28"]
    assert payload["reading"]["control_fired_every_trial"] is True, (
        "the ApplyGuardrail control is unaffected by a Converse scope change; if this ever "
        "goes False the arm below stops testing the transport path")
    assert payload["transport_control"]["apply_guardrail_text_handled_all"] is True
    assert payload["transport_control"]["converse_text_handled_all"] is False
    assert payload["transport_control"]["matched"] is False
    assert payload["reading"]["downgraded_by"] == "transport_control"
    assert rec["verdict"] == O.INCONCLUSIVE, (
        "without the transport control this run would have published TRUE from a Converse "
        "guardrail that evaluated nothing at all")


def test_a_silent_endpoint_with_an_empty_body_is_also_inconclusive(
        ledger, real_meta, tmp_path, monkeypatch):
    """The SECOND lying double: 200 with no `action`, no `assessments`, no `trace`.

    The shape a real endpoint takes when the trace was not enabled or a response field was
    renamed. It must not be readable as a scope boundary either.
    """
    rc, emitted, bd, rt, _ = run_main({"silent": True}, ledger=ledger, real_meta=real_meta,
                                      tmp_path=tmp_path, monkeypatch=monkeypatch)
    for cid in es.CASES:
        assert emitted[cid][0]["verdict"] == O.INCONCLUSIVE, cid
    assert emitted["F1-27"][1]["arms"]["text_plain"]["n_sendable"] == 3, (
        "the calls succeeded — the INCONCLUSIVE is from an empty body, not from a refusal")


def test_a_rejected_reasoning_block_is_inconclusive_with_the_sdk_reason_recorded(
        ledger, real_meta, tmp_path, monkeypatch):
    """The outcome the pre-registered method may actually meet in production.

    If the model refuses `reasoningContent` on input, both reasoning arms are unsendable. The
    verdict must be INCONCLUSIVE with the error codes AND the SDK evidence attached — not
    TRUE, which is what reading a refusal as a non-intervention would give.
    """
    plan = {"converse_reject": ("reasoning_user", "reasoning_assistant")}
    rc, emitted, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    rec, payload = emitted["F1-27"]
    assert rec["verdict"] == O.INCONCLUSIVE
    assert "not be exercised" in payload["reading"]["why"]
    assert set(payload["reading"]["placement_arms_unsendable"]) == {
        "reasoning_user", "reasoning_assistant"}
    assert rec["evidence"]["detail"]["sdk"]["method_executable"] is True, (
        "the SDK CAN express it; the service refused it. The record has to say which")
    assert payload["reading"]["control_fired_every_trial"] is True, (
        "the control still fired, which is what makes the unsendable arms the reason")


def test_a_rejected_create_reaches_f1_26s_rejected_disjunct(ledger, real_meta, tmp_path,
                                                            monkeypatch):
    """The branch F8-7's sealed text cannot express, and the reason F1-26 exists separately."""
    plan = {"create_reject": ("f1-26-classic",)}
    rc, emitted, bd, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                                   tmp_path=tmp_path, monkeypatch=monkeypatch)
    rec, payload = emitted["F1-26"]
    assert payload["per_tier"]["CLASSIC"]["disposition"] == es.DISPOSITION_REJECTED
    assert payload["per_tier"]["CLASSIC"]["control_only_accepted"] is True
    assert payload["per_tier"]["STANDARD"]["disposition"] == es.DISPOSITION_INERT
    assert rec["verdict"] == O.TRUE
    assert payload["reading"]["n_rejected"] == 1
    assert payload["reading"]["n_provably_inert"] == 1
    assert payload["sibling_case"]["case_id"] == es.SIBLING_OF_F1_26
    # The attribution control was actually created, and torn down with everything else.
    assert any("ctl-classic" in c["name"] for c in bd.creates)
    assert payload["residue"]["clean"] is True


def test_a_create_rejected_with_its_control_also_rejected_is_not_a_disjunct(
        ledger, real_meta, tmp_path, monkeypatch):
    plan = {"create_reject": ("f1-26-",)}          # matches the full AND the control-only name
    rc, emitted, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    rec, payload = emitted["F1-26"]
    assert rec["verdict"] == O.INCONCLUSIVE
    assert set(payload["reading"]["dispositions"].values()) == {
        es.DISPOSITION_INDETERMINATE}
    assert "not attributable" in payload["reading"]["why"]


def test_an_unconfirmed_tier_read_back_stops_the_verdict(ledger, real_meta, tmp_path,
                                                        monkeypatch):
    """'On either tier' cannot be asserted from a tier that was requested and never observed."""
    plan = {"tier_read_back_override": "CLASSIC"}     # STANDARD comes back as CLASSIC
    rc, emitted, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    rec, payload = emitted["F1-26"]
    assert rec["verdict"] == O.INCONCLUSIVE
    assert payload["per_tier"]["STANDARD"]["disposition"] == es.DISPOSITION_INDETERMINATE
    assert payload["per_tier"]["CLASSIC"]["disposition"] == es.DISPOSITION_INERT


def test_a_guardrail_stuck_in_creating_measures_nothing_and_says_so(ledger, real_meta,
                                                                    tmp_path, monkeypatch):
    plan = {"status": "CREATING"}
    monkeypatch.setattr(es, "GET_GUARDRAIL_TIMEOUT_S", 0.0)
    rc, emitted, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rc & 2, "zero trials is rc=2: nothing was measured"
    for cid in es.CASES:
        rec, payload = emitted[cid]
        assert rec["verdict"] == O.INCONCLUSIVE
        assert payload["n_trials"] == 0


def test_a_probe_guardrail_that_survives_teardown_is_a_failure_and_not_a_finding(
        ledger, real_meta, tmp_path, monkeypatch, capsys):
    plan = {"delete_fail": ("gr-001",)}
    rc, emitted, bd, *_ = run_main(plan, ledger=ledger, real_meta=real_meta,
                                   tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rc & 2, "residue is rc=2"
    assert emitted["F1-26"][1]["residue"]["clean"] is False
    assert emitted["F1-26"][1]["residue"]["surviving"] == ["gr-001"]
    # Every other probe was still attempted: stopping at the first failed delete would strand
    # the rest for a reason unrelated to them.
    #
    # Asserted on the DISTINCT ids rather than on `len(bd.deletes)`, which is what this line
    # used to do. `bd.deletes` records call ATTEMPTS, and a failing delete is now retried, so
    # the raw length became 8 for four guardrails — the count moved while the property the
    # comment above describes did not. Coverage of the four probes is the invariant; how many
    # attempts the retry policy spends on the one that will not die is `lib/probe_guardrail.py`'s
    # business and is asserted in `lib/tests/test_probe_guardrail.py`, where changing the retry
    # codes is supposed to show up. Duplicating it here would give two tests one owner and make
    # a deliberate retry change look like a failure in a case script that never mentions retries.
    assert sorted(set(bd.deletes)) == ["gr-001", "gr-002", "gr-003", "gr-004"], bd.deletes
    assert "Residue is a teardown failure" in capsys.readouterr().err


def test_teardown_still_runs_when_one_case_raises_and_the_others_still_report(
        ledger, real_meta, tmp_path, monkeypatch):
    """A crash in one case must not cost the other two, nor leak the guardrails it made."""
    def _boom(**kw):
        raise RuntimeError("synthetic arm failure")
    monkeypatch.setattr(es, "run_f1_27", _boom)
    rc, emitted, bd, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                                   tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rc & 1, "an unclassified outcome is rc=1"
    assert emitted["F1-27"][0]["verdict"] == O.INCONCLUSIVE
    assert "RuntimeError" in emitted["F1-27"][1]["crashed"]["type"]
    assert emitted["F1-26"][0]["verdict"] == O.TRUE
    assert emitted["F1-28"][0]["verdict"] == O.TRUE
    # F1-26's two and F1-28's one were created and deleted; F1-27 never got that far.
    assert len(bd.deletes) == 3
    assert emitted["F1-26"][1]["residue"]["clean"] is True


def test_teardown_runs_even_when_the_exception_escapes_the_loop(ledger, real_meta, tmp_path,
                                                               monkeypatch):
    """A `finally` and an `else` are indistinguishable until something ESCAPES.

    Written because a mutation proved it: replacing the teardown's `finally:` with
    `except BaseException: raise / else:` SURVIVED the arm above, and correctly so — that arm's
    exception is caught by the per-case `except Exception` inside the loop, so the loop body
    completes normally and an `else` would run too. The `finally` only earns its keep when an
    exception leaves the loop, and the realistic one is an operator's Ctrl-C: `KeyboardInterrupt`
    is a BaseException, so the per-case handler does not catch it, and two live guardrails are
    already in the account when it arrives.
    """
    def _boom(**kw):
        raise KeyboardInterrupt("operator interrupt mid-run")
    monkeypatch.setattr(es, "run_f1_27", _boom)

    bd = FakeBedrock(BASELINE_PLAN, real_meta)
    rt = FakeRuntime(bd, BASELINE_PLAN)
    monkeypatch.setattr(es.A, "factory", lambda *a, **k: type(
        "F", (), {"bedrock": staticmethod(lambda: bd),
                  "bedrock_runtime": staticmethod(lambda: rt)})())
    monkeypatch.setattr(es.A, "limiter", lambda: Limiter())
    monkeypatch.setattr(es, "CONVERSE_SPACING_S", 0.0)
    monkeypatch.setattr(es.P, "emit", lambda *a, **k: tmp_path / "x.json")

    with pytest.raises(KeyboardInterrupt):
        es.main(["--state", str(ledger),
                 "--evidence-root", str(tmp_path / "evidence")])

    assert len(bd.creates) == 2, "F1-26's two tier probes should already exist"
    assert bd.deletes == ["gr-001", "gr-002"], (
        f"the interrupt escaped the loop and the probe guardrails were NOT deleted: "
        f"created {[c['name'] for c in bd.creates]}, deleted {bd.deletes}. Two tagged "
        f"guardrails would survive in the account for Phase 99's sweep to find days later, "
        f"with nothing to say which case left them")
    assert not bd.guardrails, "every created guardrail must be gone from the account"


def test_the_smoke_flag_shrinks_the_arms_and_marks_the_result(ledger, real_meta, tmp_path,
                                                              monkeypatch):
    rc, emitted, bd, rt, _ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                                      tmp_path=tmp_path, monkeypatch=monkeypatch,
                                      argv=["--n", "1"])
    for cid in es.CASES:
        assert emitted[cid][1]["is_smoke"] is True, (
            f"{cid}: a smoke result that did not say so could be mistaken for the "
            f"pre-registered arm")
    assert emitted["F1-27"][1]["trials_per_paired_arm"] == 1
    assert len(rt.converses) == 4 + 3, "4 F1-27 arms + 3 F1-28 Converse arms, one trial each"
    # And the smoke run must NOT be able to publish F1-26: `--n` is a prefix, so its one item
    # is the EN control and no non-EN/FR/ES term is sent at all.
    rec26, payload26 = emitted["F1-26"]
    assert rec26["verdict"] == O.INCONCLUSIVE, (
        "a --n 1 prefix sends only the EN positive control; a TRUE here would be a verdict "
        "from a run that never probed the claim")
    for tier in es.TIERS:
        assert payload26["per_tier"][tier]["n_unsupported_cells"] == 0
        assert payload26["per_tier"][tier]["disposition"] == es.DISPOSITION_INDETERMINATE


def test_the_run_id_comes_from_the_ledger_and_a_disagreeing_one_is_refused(
        ledger, real_meta, tmp_path, monkeypatch, capsys):
    rc, emitted, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert emitted["F1-26"][1]["run_id"] == "r20260810T130945Z"
    rc2 = es.main(["--state", str(ledger), "--run-id", "r20260101T000000Z",
                   "--evidence-root", str(tmp_path / "e2")])
    assert rc2 == 2
    assert "disagrees with the ledger" in capsys.readouterr().err


def test_a_missing_ledger_stops_the_run_before_any_client_is_built(tmp_path, capsys):
    rc = es.main(["--state", str(tmp_path / "nope.json"),
                  "--evidence-root", str(tmp_path / "e")])
    assert rc == 2
    assert "does not exist" in capsys.readouterr().err


# ===========================================================================
# what the payload must always carry
# ===========================================================================

REQUIRED_PAYLOAD_KEYS = ("verdict_rule", "verdict_reading", "what_true_does_not_prove",
                         "why_this_matters_operationally", "expiry")


def test_every_emitted_payload_carries_the_five_mandatory_keys(ledger, real_meta, tmp_path,
                                                              monkeypatch):
    rc, emitted, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    for cid in es.CASES:
        payload = emitted[cid][1]
        for key in REQUIRED_PAYLOAD_KEYS:
            assert payload.get(key), f"{cid} payload is missing {key}"
            assert len(payload[key]) > 40, (
                f"{cid}/{key} is a stub; these fields are the record a later reader has")
        assert payload["instrument"] and payload["residue"] is not None
        assert payload["no_power_claim"]
        assert payload["sdk_shape_facts"]["sdk"]["botocore"]
        assert "n_trials" in payload


def test_every_emitted_payload_carries_its_arms_and_their_counts(ledger, real_meta, tmp_path,
                                                                 monkeypatch):
    """n=0 is legitimate only for a validator-shape probe; these are live trials."""
    rc, emitted, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    for cid in es.CASES:
        payload = emitted[cid][1]
        assert payload["arms"], f"{cid} reported no arms"
        for name, arm in payload["arms"].items():
            assert arm["n_trials"] > 0, f"{cid}/{name} has no trial count"
        assert payload["n_trials"] == sum(a["n_trials"] for a in payload["arms"].values())
        assert emitted[cid][0]["n_usable"] == payload["n_trials"], (
            "the Observation's n must be the trial count, not 0: these are live trials "
            "against a service and a reader checks n against it")


def test_the_paired_payloads_record_the_payload_digest_in_both_arms(ledger, real_meta,
                                                                    tmp_path, monkeypatch):
    rc, emitted, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    for cid, payload_text in (("F1-27", es.PAYLOAD_27), ("F1-28", es.PAYLOAD_28)):
        ident = emitted[cid][1]["payload_identity"]
        assert ident["payload_sha256"] == es.sha(payload_text)
        assert len(set(ident["per_arm_sha256"].values())) == 1
        for name, arm in emitted[cid][1]["arm_trials"].items():
            for row in arm:
                assert row["payload_sha256"] == ident["payload_sha256"], (
                    f"{cid}/{name}: a trial row without the digest cannot be checked against "
                    f"the identity assertion")


def test_the_mutation_is_recorded_as_an_observation_attribute_and_in_the_payload(
        ledger, real_meta, tmp_path, monkeypatch):
    """`_detail` raises for an Observation field passed as **detail, so it must be an attribute.

    And because these three cases are NOT in `mutation_arms_are_mandatory`, `evaluate` does
    not copy the field into the record — so the payload has to carry the reading too, or the
    mutation would be invisible in the published result.
    """
    rc, emitted, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    for cid in es.CASES:
        mut = emitted[cid][1]["mutation"]
        assert mut["inverted"] is True, cid
        assert mut["variable"] and mut["why"]
        assert O.mutation_is_mandatory(cid) is False, (
            "if the seal ever makes one of these mandatory, `evaluate` starts reading "
            "obs.mutation_inverted and this arm should assert the record carries it")


def test_setting_a_real_observation_field_as_detail_would_raise(ledger):
    """The trap `_detail` exists for, pinned so nobody 'simplifies' the attribute assignment."""
    with pytest.raises(TypeError) as ei:
        P.obs_existence("F1-26", True, n=1, mutation_inverted=True)
    assert "F1-26" in str(ei.value) and "mutation_inverted" in str(ei.value)


# ===========================================================================
# provenance, and the static arms
# ===========================================================================

def test_no_record_is_written_into_the_live_evidence_tree(ledger, real_meta, tmp_path,
                                                          monkeypatch):
    """Both halves: the live tree gained nothing, AND the redirect really wrote something."""
    live = E.EVIDENCE_ROOT
    before = {p for p in live.rglob("*.json")} if live.exists() else set()
    rc, emitted, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    after = {p for p in live.rglob("*.json")} if live.exists() else set()
    assert after == before, f"records leaked into the live evidence tree: {after - before}"
    written = list((tmp_path / "evidence").rglob("*.json"))
    assert written, "the redirect wrote nothing, so the leak check above proves nothing"
    bodies = [json.loads(p.read_text(encoding="utf-8")) for p in written
              if p.name[0].isdigit()]
    assert any(b.get("operation") == "create_guardrail" for b in bodies)
    assert any(b.get("operation") == "converse" for b in bodies)
    assert any(b.get("operation") == "apply_guardrail" for b in bodies)


def test_each_case_writes_into_its_own_evidence_directory(ledger, real_meta, tmp_path,
                                                          monkeypatch):
    """One EvidenceStore per case, per the harness contract."""
    rc, emitted, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    dirs = {p.parent.name for p in (tmp_path / "evidence").rglob("environment.json")}
    assert dirs == set(es.CASES), dirs


def test_a_fake_client_is_refused_without_the_evidence_root_redirect(ledger, real_meta,
                                                                     tmp_path, monkeypatch):
    """The mutation check on `capture`'s provenance guard, from this script's side.

    Without it, this whole file would write 60+ fabricated call records into
    `evidence/<ledger run id>/f1/`, where `check_amendment_readiness.py` counts them as
    observation days.
    """
    bd = FakeBedrock(BASELINE_PLAN, real_meta)
    rt = FakeRuntime(bd, BASELINE_PLAN)
    monkeypatch.setattr(es.A, "factory", lambda *a, **k: type(
        "F", (), {"bedrock": staticmethod(lambda: bd),
                  "bedrock_runtime": staticmethod(lambda: rt)})())
    monkeypatch.setattr(es.A, "limiter", lambda: Limiter())
    monkeypatch.setattr(es.P, "emit", lambda *a, **k: tmp_path / "x.json")
    monkeypatch.setattr(E, "EVIDENCE_ROOT", tmp_path / "pretend-live")
    with pytest.raises(E.EvidenceProvenanceError):
        es.main(["--state", str(ledger)])
    assert not list((tmp_path / "pretend-live").rglob("0*.json")), (
        "fabricated records were written before the refusal")


def test_the_dry_run_makes_no_aws_call_and_still_reaches_every_arm(ledger, capsys):
    """The autouse `no_aws` fixture blocks `socket.connect`, so this is not a claim.

    And it asserts the dry run REACHED the arms: every arm name of all three cases appears in
    the banner, along with the byte-identity digest and the SDK verdicts. A dry run that
    printed a plan without executing the guards would satisfy neither.
    """
    rc = es.main(["--dry-run", "--state", str(ledger)])
    assert rc == 0
    out = capsys.readouterr().out
    for cid in es.CASES:
        assert cid in out
    for name in list(es.converse_arms_27("m")) + list(es.converse_arms_28("m")):
        assert name in out, f"the dry run never named the arm {name}"
    for tier in es.TIERS:
        assert f"words-{tier.lower()}" in out
    assert es.sha(es.PAYLOAD_27)[:16] in out
    assert es.sha(es.PAYLOAD_28)[:16] in out
    assert "CANNOT BE CONSTRUCTED" in out
    assert "ZERO AWS calls" in out


def test_the_dry_run_refuses_a_broken_vocabulary_before_printing_a_plan(monkeypatch, ledger,
                                                                        capsys):
    monkeypatch.setattr(es, "LISTED", tuple(
        s for s in es.LISTED if s["term"] != es.CONTROL_TERM))
    rc = es.main(["--dry-run", "--state", str(ledger)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "offline precondition" in err and "positive control" in err


HELPER = "create_probe_guardrail"
SCRIPT = ROOT / "f1_config" / "06_eval_scope.py"


def _call_sites(path: Path) -> list[tuple[int, ast.Call]]:
    """Every `create_probe_guardrail(...)` call in `path`, by AST and not by grep.

    A call split across lines is one site, not four
    (`feedback_grep_the_claim_not_the_phrasing`).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[int, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name == HELPER:
            out.append((node.lineno, node))
    return out


def test_every_probe_create_in_this_script_passes_case_id():
    """`case_id` is keyword-only with no default, so an omission is a TypeError — LIVE.

    Zero sites is an ERROR, not a pass: either the helper was renamed or the walk is broken,
    and in both cases this arm would report clean over a guard that checked nothing
    (`feedback_zero_file_scan_is_error`).
    """
    sites = _call_sites(SCRIPT)
    assert len(sites) >= 4, (
        f"found {len(sites)} call(s) to {HELPER} in {SCRIPT.name}; the script creates four "
        f"probe guardrails (2 tiers for F1-26 + its attribution control + 1 each for F1-27 "
        f"and F1-28), so a smaller count means the walk is broken or an arm was dropped")
    missing = [ln for ln, node in sites
               if "case_id" not in {kw.arg for kw in node.keywords}]
    assert not missing, (
        f"{HELPER} calls without case_id= at lines {missing}. The parameter is keyword-only "
        f"with no default, so this raises TypeError mid-run with guardrails half-created")
    wrong = [(ln, kw.value.value) for ln, node in sites for kw in node.keywords
             if kw.arg == "case_id" and isinstance(kw.value, ast.Constant)
             and kw.value.value not in es.CASES]
    assert not wrong, (
        f"a probe is attributed to a case this script does not own: {wrong}. Its records "
        f"would land in another case's evidence directory")


def test_every_case_this_script_owns_is_bound_and_sealed_the_way_it_assumes():
    """The script's design assumes EXISTENCE, class C and no pre-registered n for all three."""
    for cid in es.CASES:
        assert O.BINDINGS[cid].kind == "EXISTENCE", (
            f"{cid} is bound {O.BINDINGS[cid].kind}; obs_existence would be the wrong builder")
        assert O.planned_n(cid) is None, (
            f"{cid} now carries a sealed n of {O.planned_n(cid)}; `no_power_claim` says there "
            f"is none and would be false")
        assert O.cases()[cid][2] == "C"


def test_the_script_quotes_the_sealed_oracle_text_and_not_a_paraphrase():
    """The three oracle sentences in the module docstring must be the sealed ones.

    A paraphrase drifting from the seal is the `feedback_prose_is_not_verified` defect, and
    here it would mean the decision rules implement a sentence nobody sealed.
    """
    doc = es.__doc__ or ""
    assert doc
    for cid in es.CASES:
        text = O.oracle_text(cid)
        # Compared on collapsed whitespace, because the docstring wraps.
        flat_doc = re.sub(r"\s+", " ", doc)
        flat = re.sub(r"\s+", " ", text)
        assert flat in flat_doc, f"{cid}'s sealed oracle text is not quoted verbatim: {text}"


def test_the_converse_pacing_is_ours_and_the_script_never_fakes_a_limiter_wait():
    """`lim.wait('Converse')` must not stand in for the script's own pacing.

    Read by AST rather than by substring, because the script's own docstring EXPLAINS the
    hazard and therefore contains the phrase — a grep would fail on the explanation and pass on
    the defect (`feedback_grep_the_claim_not_the_phrasing`). Every `*.wait(...)` call in the
    file is collected and its first argument checked, and finding zero of them is an error.

    This arm used to open with `assert A.rate_limit_for("Converse") is None`, and that
    assertion has been REPLACED rather than removed. Its premise was that `Converse` had no
    RATE_LIMITS entry, so `lim.wait("Converse")` would read as rate limiting while doing
    nothing. That premise is now false: `Converse` was one of 19 operations given an entry, so
    the no-op hazard this arm was built to catch no longer exists. **The failure of that
    assertion was evidence the fix landed, not a regression** — which is why the arm is
    re-pointed at the invariant that survives instead of being deleted along with the hazard.

    Two things still matter, and both are asserted below.

    First, the entry is `self_imposed`, not `aws_documented`. 2.0 rps is a number this harness
    invented; AWS publishes no Converse ceiling of its own. `limit_provenance` exists precisely
    so a rate the harness chose cannot be cited as a service quota, and F9's claims turn on
    that distinction.

    Second, the script must still pace Converse ITSELF and must not delegate to the limiter,
    even though delegating would now do something. `CONVERSE_SPACING_S` is 1.0s — 1 rps — which
    is STRICTER than the limiter's 2.0 rps, so the two mechanisms disagree. Using both would
    make the effective rate depend on which one a reader consults, with neither authoritative,
    and the pacing recorded in the payload would stop describing what the script actually did.
    """
    assert A.rate_limit_for("Converse") == 2.0, (
        "Converse lost its RATE_LIMITS entry; the assertions below assume it has one")
    assert A.limit_provenance("Converse") == "self_imposed", (
        "2.0 rps for Converse is a rate this harness chose, not one AWS documents — marking it "
        "aws_documented would make it citable in a claim about the service")
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    waits: list[str] = []
    sleeps = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name == "wait" and node.args and isinstance(node.args[0], ast.Constant):
            waits.append(node.args[0].value)
        if name == "sleep" and node.args and isinstance(node.args[0], ast.Name) \
                and node.args[0].id == "CONVERSE_SPACING_S":
            sleeps += 1
    assert waits, (
        "found 0 rate-limiter waits in the script; either the limiter is gone or this walk is "
        "broken, and both would make this arm report clean over nothing")
    assert "Converse" not in waits, (
        f"lim.wait('Converse') is a no-op — RATE_LIMITS has no such entry — so it would read "
        f"as rate limiting while doing nothing. Waits found: {sorted(set(waits))}")
    assert set(waits) <= set(A.RATE_LIMITS), (
        f"a wait for an operation RATE_LIMITS does not know: "
        f"{sorted(set(waits) - set(A.RATE_LIMITS))}")
    assert sleeps == 1, (
        f"expected exactly one explicit sleep(CONVERSE_SPACING_S), found {sleeps}; zeroing the "
        f"constant in a test must not be able to hide the pacing call's removal")


def test_apply_guardrail_is_sent_with_the_full_output_scope(ledger, real_meta, tmp_path,
                                                            monkeypatch):
    """INTERVENTIONS returns only what fired, so a scope claim cannot use it.

    With it, a policy that was evaluated and found nothing is indistinguishable from a policy
    that was never evaluated — which is the entire question.
    """
    rc, emitted, bd, rt, _ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                                      tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rt.applies
    for kw in rt.applies:
        assert kw["outputScope"] == "FULL"
        assert kw["source"] == "INPUT"
        assert kw["guardrailVersion"] == "DRAFT"


def test_converse_is_sent_with_the_guardrail_attached_and_the_trace_enabled(
        ledger, real_meta, tmp_path, monkeypatch):
    """Without `trace=enabled` there is no assessment, and masking has no other signal."""
    rc, emitted, bd, rt, _ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                                      tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rt.converses
    for kw in rt.converses:
        gc = kw["guardrailConfig"]
        assert gc["trace"] == "enabled"
        assert gc["guardrailIdentifier"] in bd.guardrails or gc["guardrailIdentifier"]
        assert gc["guardrailVersion"] == "DRAFT"


def test_the_standard_tier_probe_carries_the_top_level_cross_region_config(
        ledger, real_meta, tmp_path, monkeypatch):
    """F8-5's STANDARD half was confounded by omitting it; supplied rather than rediscovered."""
    rc, emitted, bd, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                                   tmp_path=tmp_path, monkeypatch=monkeypatch)
    standard = [c for c in bd.creates if "standard" in c["name"]]
    assert standard, "no STANDARD-tier probe was created"
    for c in standard:
        assert c["crossRegionConfig"] == {
            "guardrailProfileIdentifier": es.XREGION_PROFILE}
        assert (c["contentPolicyConfig"]["tierConfig"]["tierName"]) == "STANDARD"
    classic = [c for c in bd.creates if "f1-26-classic" in c["name"]]
    assert classic and "crossRegionConfig" not in classic[0], (
        "CLASSIC needs no cross-Region profile, and adding one would change a second variable")


def test_every_created_guardrail_is_tagged_for_the_teardown_sweep(ledger, real_meta,
                                                                  tmp_path, monkeypatch):
    """Teardown sweeps by TAG. An untagged probe is invisible to the only thing that finds
    orphans, and this script's own `finally` is not the last line of defence."""
    rc, emitted, bd, *_ = run_main(BASELINE_PLAN, ledger=ledger, real_meta=real_meta,
                                   tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert bd.creates
    for c in bd.creates:
        tags = {t["key"]: t["value"] for t in c["tags"]}
        assert tags["Project"] == A.PROJECT_TAG
        assert tags["RunId"] == "r20260810T130945Z"
        assert tags["ExpiresAt"]
        assert c["name"].startswith("grx-gr-f1-2"), c["name"]


def test_the_fake_runtimes_arm_classifier_agrees_with_the_scripts_arm_names():
    """The double must recognise the requests the script builds, or its rejections miss.

    A fake that misclassified a placement would reject the wrong arm and every
    `converse_reject` scenario above would be testing something else
    (`feedback_probe_must_reach_the_code`, applied to a test double).
    """
    for name, spec in es.converse_arms_27("m").items():
        kw = {**spec["request"], "guardrailConfig": {"guardrailIdentifier": "gr-1"}}
        assert classify_converse_request(kw) == name, name
    got = {classify_converse_request(
        {**spec["request"], "guardrailConfig": {"guardrailIdentifier": "gr-1"}})
        for name, spec in es.converse_arms_28("m").items()}
    assert got == {"text_plain", "tool_use_input", "tool_result_json"}, (
        "F1-28's text arm has the same wire shape as F1-27's text_plain, which is the point "
        "of a transport-matched control")
