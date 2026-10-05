"""Offline enforcement for F10-1's analysis half (`f10_billing/03_block_billing.py`).

Every test here builds its Converse responses and Cost Explorer pages by hand. The case's
verdict must be a function of recorded rows and a recorded bill, so nothing here may reach
the network (the autouse `no_aws` fixture in conftest.py fails a stray socket loudly).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
WORDS = ["moonquake", "zorbify", "quaxlinate"]


def _load():
    path = HERE.parent / "03_block_billing.py"
    spec = importlib.util.spec_from_file_location("f10_block_billing", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


def resp(*, stop="guardrail_intervened", in_words=(), out_words=(), tin=0, tout=0):
    def assess(ws):
        return {"g": {"wordPolicy": {"customWords": [
            {"match": w, "action": "BLOCKED", "detected": True} for w in ws]}}}
    trace = {"guardrail": {}}
    if in_words:
        trace["guardrail"]["inputAssessment"] = assess(in_words)
    if out_words:
        trace["guardrail"]["outputAssessments"] = {"g": [assess(out_words)["g"]]}
    return {"stopReason": stop, "trace": trace,
            "usage": {"inputTokens": tin, "outputTokens": tout},
            "ResponseMetadata": {"RequestId": "req"}}


def rows_ok(n=3, tin=30, tout=4):
    """What the pre-flight measured: blocked responses report 0/0, the control reports truth."""
    at = "2026-10-01T10:00:00+00:00"
    rows = []
    for rep in range(n):
        rows.append(M.summarize(resp(in_words=["zorbify"]), arm=M.ARM_INPUT, rep=rep, sent_at=at))
        rows.append(M.summarize(resp(out_words=["zorbify"]), arm=M.ARM_OUTPUT, rep=rep,
                                sent_at=at))
        rows.append(M.summarize(resp(stop="end_turn", tin=tin, tout=tout), arm=M.ARM_CONTROL,
                                rep=rep, sent_at=at))
    return rows


def page(groups):
    return {"ResultsByTime": [{"Groups": [
        {"Keys": [f"{M.TAG_KEY}${arm}", ut],
         "Metrics": {"UsageQuantity": {"Amount": str(q)}, "UnblendedCost": {"Amount": str(usd)}}}
        for arm, ut, q, usd in groups]}]}


def _pair(arm, tin, tout, prefix="USE1"):
    return [(arm, f"{prefix}-NovaMicro-input-tokens", tin / 1000,
             tin / 1000 * M.PRICE_PER_1K["input"]),
            (arm, f"{prefix}-NovaMicro-output-tokens", tout / 1000,
             tout / 1000 * M.PRICE_PER_1K["output"])]


def bill_for(tin_total, tout_total, *, input_arm=(0, 0), control=(90, 12)):
    """Output arm billed (tin_total, tout_total); the control billed `control`."""
    g = _pair(M.ARM_OUTPUT, tin_total, tout_total)
    if any(control):
        g += _pair(M.ARM_CONTROL, *control)
    if any(input_arm):
        g += _pair(M.ARM_INPUT, *input_arm)
    return M.billed([page([x for x in g if x[2]])])


# --- prompts --------------------------------------------------------------

def test_the_arms_differ_only_in_where_the_word_appears():
    m = M.manipulation_check(WORDS)
    assert m["ok"], m
    assert m["input_prompt_words"] == ["zorbify"]
    assert m["output_prompt_words"] == []
    assert m["control_prompt_is_output_prompt"]
    assert "".join(m["fragments"]) == "zorbify"


def test_a_fragment_that_is_itself_listed_fails_the_check():
    # "zorbify" split in half is "zor" + "bify". List "zor" too and the output prompt
    # would be input-blocked, so it would be a second input arm.
    assert not M.manipulation_check(["moonquake", "zorbify", "zor"])["ok"]


def test_a_control_prompt_that_differs_from_the_output_prompt_fails_the_check(monkeypatch):
    # The control supplies the output arm's reference tokens, so it must send the same text.
    real = M.prompts

    def drifted(words):
        p = real(words)
        p[M.ARM_CONTROL] = p[M.ARM_CONTROL] + " Thanks."
        return p
    monkeypatch.setattr(M, "prompts", drifted)
    assert not M.manipulation_check(WORDS)["ok"]


def test_whole_word_matching_ignores_a_word_inside_another():
    assert M.contains_word("say zorbify now", "zorbify")
    assert not M.contains_word("say zorbifying now", "zorbify")


# --- one response -----------------------------------------------------------

def test_landed_arm_reads_the_trace_not_the_label():
    assert M.landed_arm(M.summarize(resp(in_words=["zorbify"]), arm=M.ARM_OUTPUT,
                                    rep=0, sent_at="")) == M.ARM_INPUT
    assert M.landed_arm(M.summarize(resp(out_words=["zorbify"]), arm=M.ARM_INPUT,
                                    rep=0, sent_at="")) == M.ARM_OUTPUT
    assert M.landed_arm(M.summarize(resp(stop="end_turn", tout=4), arm=M.ARM_OUTPUT,
                                    rep=0, sent_at="")) == M.ARM_CONTROL
    # An empty unguarded answer is no treatment at all.
    assert M.landed_arm(M.summarize(resp(stop="end_turn"), arm=M.ARM_CONTROL,
                                    rep=0, sent_at="")) is None


# --- the bill -----------------------------------------------------------------

def test_untagged_spend_and_other_usage_types_are_not_counted():
    b = M.billed([page([
        ("", "USE1-NovaMicro-input-tokens", 5.0, 1.0),
        (M.ARM_OUTPUT, "USE1-Guardrail-ContentPolicyUnitsConsumed", 9.0, 1.0),
        (M.ARM_OUTPUT, "USW2-NovaMicro-output-tokens", 0.004, 0.00000056)])])
    assert b[M.ARM_OUTPUT]["output"]["qty"] == pytest.approx(0.004)
    assert b[M.ARM_OUTPUT]["input"]["qty"] == 0
    assert b[M.ARM_INPUT]["input"]["qty"] == 0


def test_true_when_the_input_arm_is_unbilled_and_the_output_arm_is_billed_in_full():
    rows = rows_ok()
    d = M.decide(rows, bill_for(90, 12))
    assert d["status"] == "decided" and d["observed"] is True, d


def test_false_when_the_input_arm_is_billed():
    d = M.decide(rows_ok(), bill_for(90, 12, input_arm=(40, 0)))
    assert d["status"] == "decided" and d["observed"] is False


def test_false_when_the_output_arm_is_billed_short():
    d = M.decide(rows_ok(), bill_for(90, 8))  # 12 reported, 8 billed, tolerance 3
    assert d["status"] == "decided" and d["observed"] is False
    assert d["output_arm_full"] == {"input": True, "output": False}


def test_within_one_token_per_request_is_full():
    d = M.decide(rows_ok(), bill_for(93, 9))  # n = 3 output rows
    assert d["observed"] is True


def test_an_unbilled_control_is_undecided_never_true():
    d = M.decide(rows_ok(), M.billed([page([])]))
    assert d["status"] == "undecided"
    assert "observed" not in d


def test_a_zero_output_bill_with_a_billed_control_is_false_not_undecided():
    # The ambiguity the control arm exists to remove: the tag demonstrably reached the
    # bill, so an unbilled output arm is a reading ("not charged"), not a missing one.
    d = M.decide(rows_ok(), bill_for(0, 0))
    assert d["status"] == "decided" and d["observed"] is False


def test_a_control_billed_differently_from_its_own_usage_is_a_fault():
    d = M.decide(rows_ok(), bill_for(90, 12, control=(90, 30)))
    assert d["status"] == "fault"


def test_the_expected_output_charge_comes_from_the_control_not_the_blocked_response():
    d = M.decide(rows_ok(), bill_for(90, 12))
    assert d["reported_tokens"][M.ARM_OUTPUT] == {"input": 0, "output": 0, "n": 3}
    assert d["expected_output_arm_tokens"] == {"input": 90, "output": 12}


def test_an_unguarded_row_in_a_guarded_arm_is_a_fault():
    rows = rows_ok()
    rows[1] = M.summarize(resp(stop="end_turn", tin=30, tout=4), arm=M.ARM_OUTPUT, rep=0,
                          sent_at="2026-10-01T10:00:00+00:00")
    assert M.decide(rows, bill_for(90, 12))["status"] == "fault"


def test_a_row_in_the_wrong_arm_is_a_fault():
    rows = rows_ok()
    rows[0] = M.summarize(resp(stop="end_turn"), arm=M.ARM_INPUT, rep=0, sent_at="x")
    assert M.decide(rows, bill_for(90, 12))["status"] == "fault"


def test_a_bill_whose_unit_is_not_thousands_of_tokens_is_a_fault():
    b = bill_for(90, 12)
    b[M.ARM_OUTPUT]["input"]["usd"] *= 1000  # quantity would then be in tokens, not 1K
    assert M.decide(rows_ok(), b)["status"] == "fault"


# --- the clocks -----------------------------------------------------------------

def test_send_refuses_before_the_tag_can_apply(capsys):
    early = M.NOT_BEFORE - timedelta(minutes=1)
    rc = M.cmd_send(argparse.Namespace(dry_run=False), now=lambda: early)
    assert rc == 1
    assert "REFUSED" in capsys.readouterr().err


def test_read_refuses_inside_the_billing_lag(tmp_path, monkeypatch, capsys):
    sends = tmp_path / "sends.json"
    sends.write_text(json.dumps({"rows": rows_ok()}))
    monkeypatch.setattr(M, "SENDS_PATH", sends)
    sent = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    rc = M.cmd_read(argparse.Namespace(final=False),
                    now=lambda: sent + M.READ_LAG - timedelta(minutes=1))
    assert rc == 1
    assert "REFUSED" in capsys.readouterr().err


def test_the_record_dates_the_sends_not_the_read(tmp_path, monkeypatch):
    # One day of sends read three days later is still one day of observation. A record stamped
    # with the read's date would read as two calendar days to the replication rule.
    sends = tmp_path / "sends.json"
    rows = rows_ok()
    for r in rows:
        r["sent_at"] = "2026-10-02T01:32:00+00:00"
    rows[-1]["sent_at"] = "2026-10-02T01:33:05+00:00"
    sends.write_text(json.dumps({"rows": rows}))
    monkeypatch.setattr(M, "SENDS_PATH", sends)
    monkeypatch.setattr(M, "EVIDENCE_DIR", tmp_path / "ev")
    monkeypatch.setattr(M, "ROOT", tmp_path)

    class CE:
        def get_cost_and_usage(self, **_):
            return page(_pair(M.ARM_CONTROL, 90, 12) + _pair(M.ARM_OUTPUT, 90, 12))

    class FC:
        def client(self, _name):
            return CE()
    monkeypatch.setattr(M.A, "factory", lambda _r: FC())
    monkeypatch.setattr(M.A, "sdk_versions", lambda: {})
    seen = {}
    monkeypatch.setattr(M.P, "emit", lambda case, rec, extra: seen.update(extra))
    read_at = datetime(2026, 10, 5, 1, 21, tzinfo=timezone.utc)
    assert M.cmd_read(argparse.Namespace(final=False), now=lambda: read_at) == 0
    days = {seen["t0_iso"][:10], seen["t1_iso"][:10]}
    assert days == {"2026-10-02"}
    assert "2026-10-05" not in json.dumps({k: v for k, v in seen.items()
                                           if k != "cost_explorer_request"})
