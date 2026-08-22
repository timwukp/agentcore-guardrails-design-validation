#!/usr/bin/env python3
"""The two guards that reported clean over a run they could not see (FUTURE-WORK items 33, 34).

On 2026-08-19 `tools/day2_replicate.py` drove three F6 producers through 52 min, 36 min and
2 h 41 min of real measurement and scored the result twice wrong:

* it returned **rc 2 "the producer wrote no evidence record dated today"** while 9,448 records
  sat on disk, because the producer had ignored `--run-id` and adopted `state.json`'s id, and
  the driver counted records under the directory it had asked for (item 33);
* and, when the run was adjudicated offline instead, it reported `clean_observation: true` for
  **all nine** F6 cases over a run holding **eight** failed calls, because the check gated on a
  closed tuple of error-code names and scoped by a path rule that could not match a directory
  named for two cases at once (item 34).

Both fixes are behavioural, so both are tested behaviourally. The important arms are the
CONTROLS, because each fix widens something:

* `test_the_old_name_keyed_rule_would_miss_most_of_these` is the mutation control for item 34.
  Without it, every `failure_reason` assertion below would pass just as well on a classifier
  that returned a reason for literally any record.
* `test_a_producer_that_honours_the_flag_still_passes_under_the_old_derivation` is the mutation
  control for item 33. An **echoing** double — one that writes under the id it was given — never
  reaches the derived-run-id path at all, so a test built on one would pass before and after the
  fix. The double here therefore LIES: it writes under the day-1 id, exactly as the real
  producers did, and the pre-fix derivation is re-created to show it fails on that double.

The record shapes in `SHAPES` are not invented. Each was read off
`evidence/r20260810T130945Z/f6_latency/` on 2026-08-22 and reduced to the fields the classifier
touches; the fourth is the one that matters most, since `ok: false` and `http_status: 404` are
the *only* things it carries — no code, no class, no message, no metadata — so no list of error
names, however long, could ever have reached it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SUBJECT_MODULE_NAME = "_failures_day2_replicate"

# The run and day whose numbers item 34 states. Used only by the real-tree arms, which skip
# where `evidence/` is absent (it is local-only by written policy).
REAL_RUN = "r20260810T130945Z"
REAL_DAY = "2026-08-19"
REAL_FAILED_CALLS = 8


def _subject():
    spec = importlib.util.spec_from_file_location(
        SUBJECT_MODULE_NAME, REPO / "tools" / "day2_replicate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _subject()


# --------------------------------------------------------------- item 34: the four real shapes

def _record(**over) -> dict:
    """A call record with the fields `lib/evidence.py` writes on a successful call."""
    base = {"case_id": "F6-2_5", "ok": True, "error_code": "", "error_class": "",
            "error_message": "", "error_metadata": {}, "http_status": 200,
            "t_start_utc": "2026-08-19T03:01:37Z"}
    base.update(over)
    return base


# name -> (record, the reason the classifier must return)
SHAPES = {
    # 1 of 8. botocore's read timeout: a class name, no status at all. The 70-second timeout
    # that item 34 was filed for.
    "read_timeout": (_record(
        ok=False, error_class="ReadTimeoutError", http_status=None,
        error_message='Read timeout on endpoint URL: "https://bedrock-runtime.us-east-1.'
                      'amazonaws.com/model/us.amazon.nova-micro-v1%3A0/converse"',
    ), "ReadTimeoutError"),
    # 3 of 8. A bare HTTP 500 surfaced as a ClientError whose "code" is the status string. No
    # entry in any error-name list, and `error_code == "500"` is not a name to list.
    "bare_500": (_record(
        ok=False, error_class="ClientError", error_code="500",
        error_message="Internal Server Error", http_status=500,
        error_metadata={"Error": {"Code": "500", "Message": "Internal Server Error"}},
    ), "http_500"),
    # 3 of 8. The connection was closed mid-call. NOTHING carries the class except the message's
    # own leading token, which is why the classifier reads that token.
    "protocol_error": (_record(
        ok=False, http_status=None,
        error_message="ProtocolError: ('Connection aborted.', RemoteDisconnected('Remote end "
                      "closed connection without response'))",
    ), "ProtocolError"),
    # 1 of 8, and the reason the rule cannot be "5xx only". An MCP session expiry: JSON-RPC
    # -32004, transient in effect, 4xx in shape, and every error field empty.
    "bare_404": (_record(ok=False, http_status=404), "http_404"),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_every_failed_call_of_the_real_run_is_classified(mod, shape):
    """All four shapes are reported, and each gets the label the run's own records support."""
    rec, expected = SHAPES[shape]
    assert mod.failure_reason(rec) == expected


def test_a_failure_with_nothing_to_go_on_is_still_reported(mod):
    """The gate is `ok is False`; an unnameable failure is the one an operator most needs."""
    assert mod.failure_reason(_record(ok=False, http_status=None)) == "unclassified_failure"


def test_a_named_transient_code_keeps_its_precise_label(mod):
    """F8-5's original defect must not regress: the throttle is still named a throttle."""
    assert mod.failure_reason(_record(
        ok=False, error_code="ThrottlingException", error_class="ClientError",
        error_message="Rate exceeded", http_status=429)) == "ThrottlingException"


def test_a_successful_call_is_never_a_failure(mod):
    """Including one carrying a stale error field, since `ok` is the gate and not the fields."""
    assert mod.failure_reason(_record()) is None
    assert mod.failure_reason(_record(error_code="ThrottlingException")) is None


def test_a_record_with_no_ok_flag_and_no_error_is_not_evidence_of_a_failure(mod):
    """`ok` missing is treated as failure only when an error field is set."""
    rec = _record()
    rec.pop("ok")
    assert mod.failure_reason(rec) is None
    rec["error_class"] = "ReadTimeoutError"
    assert mod.failure_reason(rec) == "ReadTimeoutError"


def test_the_old_name_keyed_rule_would_miss_most_of_these(mod):
    """THE MUTATION CONTROL for item 34, without which every arm above is vacuous.

    Re-creates the shipped rule — a failure is a record whose error code or class appears in
    `TRANSIENT_ERRORS` — and asserts it sees none of the four real shapes. If a future edit made
    `failure_reason` fire on everything, this arm would still pass, so it is paired with
    `test_a_successful_call_is_never_a_failure` above, which fails on such an edit.
    """
    missed = [name for name, (rec, _) in SHAPES.items()
              if rec.get("error_code") not in mod.TRANSIENT_ERRORS
              and rec.get("error_class") not in mod.TRANSIENT_ERRORS]
    assert sorted(missed) == sorted(SHAPES), (
        f"the name-keyed rule was expected to miss all {len(SHAPES)} real shapes; it missed "
        f"{missed}")
    # And the new rule sees every one of them — the two halves of item 34's claim, derived
    # separately rather than one inferred from the other.
    assert all(mod.failure_reason(rec) for rec, _ in SHAPES.values())


# ------------------------------------------- a failed call is not always a hole (F8-5, both ways)

# The three real F8-5 records, read off `evidence/smoke20260810T0305Z/f8/F8-5/` on 2026-08-22.
# Two are the case's own evidence and one is the service refusing to look, and they differ in
# nothing a name list can see except the name: all three are `ok: false`, `retry_attempts: 0`.
F8_5 = {
    "validation_400": (_record(case_id="F8-5", ok=False, error_code="ValidationException",
                               error_class="ClientError", http_status=400,
                               error_message="Topics may not exceed the tier limit",
                               error_metadata={"Error": {"Code": "ValidationException"}}), True),
    "throttle_429": (_record(case_id="F8-5", ok=False, error_code="ThrottlingException",
                             error_class="ClientError", http_status=429,
                             error_message="Rate exceeded",
                             error_metadata={"Error": {"Code": "ThrottlingException"}}), False),
}


@pytest.mark.parametrize("shape", sorted(F8_5))
def test_a_service_answer_is_not_a_hole_but_a_refusal_is(mod, shape):
    """F8-5's whole design: the rejection IS the observation, the throttle is its absence.

    A guard that treats them alike is wrong in one direction or the other — counting the throttle
    as data is the original F8-5 bug, and counting the validation error as a hole would put a
    permanent false caveat on the case and teach an operator to ignore the caveat line.
    """
    rec, answered = F8_5[shape]
    assert mod.failure_reason(rec) is not None, "both are failed calls"
    assert mod.service_answered(rec) is answered


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_none_of_the_eight_is_a_service_answer(mod, shape):
    """The other side of the same predicate: every failure of 2026-08-19 is a genuine hole.

    Three of the four cannot be answers for a reason no list is needed for — two never received
    an HTTP status at all and one is a 500 — and the fourth, the bare 404, is reached because an
    answer names itself and that record names nothing.
    """
    rec, _ = SHAPES[shape]
    assert mod.service_answered(rec) is False


def test_a_refusal_is_recognised_by_status_when_its_name_is_unknown(mod):
    """The name list must not be the only thing standing between a throttle and the evidence.

    An invented 429 whose code appears in no list of ours is still not an answer, because 429 is
    the service declining to look whatever it calls itself. Same for 408 and for any 5xx. This is
    the arm that bounds `TRANSIENT_ERRORS`' remaining role to "a refusal returned as a plain
    400", which the docstring states as the residual.
    """
    for status in (408, 425, 429, 500, 503):
        rec = _record(ok=False, error_code="SomeNewLimitException", error_class="ClientError",
                      http_status=status, error_message="never seen before")
        assert mod.service_answered(rec) is False, f"HTTP {status} is not an answer"
    # …and the residual it does NOT cover, asserted so the limit is visible rather than inferred.
    rec = _record(ok=False, error_code="SomeNewLimitException", error_class="ClientError",
                  http_status=400, error_message="a refusal wearing a 400")
    assert mod.service_answered(rec) is True, (
        "a refusal returned as a plain 400 with an unlisted code reads as an answer; this is the "
        "documented residual, and TRANSIENT_ERRORS is the only thing that can close it")


# --------------------------------------------------------------- item 34: scoping to a group

def test_scoping_reaches_a_joined_timing_group(mod):
    """`F6-6`'s records live in a directory named `F6-6_7_8`, which is why nine cases read clean."""
    assert mod._scoped(("f6_latency", "F6-6_7_8", "5368_mcp-tools-call_err.json"), "F6-6")
    assert mod._scoped(("f6_latency", "F6-2_5", "3827_converse_err.json"), "F6-5")
    # …and does not reach a case that group does not hold.
    assert not mod._scoped(("f6_latency", "F6-2_5", "3827_converse_err.json"), "F6-6")
    assert not mod._scoped(("f8_limits", "F8-50", "0001_create_err.json"), "F8-5")


def test_the_real_run_reports_its_eight_failed_calls(mod):
    """The recorded measurement, re-derived. Skipped where the records are not on this machine."""
    if not (mod.EVIDENCE / REAL_RUN).is_dir():
        pytest.skip(f"evidence/{REAL_RUN} is local-only and not present")
    run_wide = mod.transient_failures(REAL_RUN, REAL_DAY)
    # None of the eight is a service answer, so the composed guard must report all of them.
    assert len(run_wide) == REAL_FAILED_CALLS, (
        f"item 34 records 8 failed calls on {REAL_DAY}; found {len(run_wide)}")
    # Each F6 case must see its own group's failures, and only those.
    per_case = {c: len(mod.transient_failures(REAL_RUN, REAL_DAY, c))
                for c in (f"F6-{i}" for i in range(1, 10))}
    assert [c for c, n in per_case.items() if n] == ["F6-2", "F6-5", "F6-6", "F6-7", "F6-8"], (
        f"expected the five cases in the two affected groups, got {per_case}")
    # CONTROL: the widening must not make everything dirty.
    assert mod.transient_failures(REAL_RUN, REAL_DAY, "F1-14") == []
    assert mod.transient_failures(REAL_RUN, "2026-08-01") == []


# --------------------------------------------------------------- item 33: the lying producer

DAY1_RUN = "r20260810T000000Z"          # the id in the producer's state.json — what it adopts
ASKED_RUN = "r20260821T000000Z"         # the id the driver mints and passes as --run-id
CASE = "F6-2"

VERDICT = {"case_id": CASE, "verdict": "TRUE",
           "record": {"kind": "interval", "thresholds": {"p95_ms": 1200}, "planned_n": 10,
                      "evidence": {"n_usable": 10}}}


def _write_double(path: Path, *, run_id_written: str, day: str) -> None:
    """A producer double that writes under `run_id_written` WHATEVER --run-id it is handed.

    Deliberately a liar. An echoing double — one that honours the flag — never reaches the
    derived-run-id path, so a test built on one cannot tell the fix from its absence
    ([[feedback_unreachable_branch_in_fake]]).
    """
    path.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        f"RID = {run_id_written!r}\n"
        f"DAY = {day!r}\n"
        "root = Path(__file__).resolve().parent\n"
        f"ev = root / 'evidence' / RID / 'f6_latency' / {'F6-2_5'!r}\n"
        "ev.mkdir(parents=True, exist_ok=True)\n"
        "for i in range(3):\n"
        "    (ev / f'{i:04d}_converse.json').write_text(json.dumps(\n"
        "        {'case_id': 'F6-2_5', 'ok': True, 't_start_utc': DAY + 'T04:00:0%dZ' % i}))\n"
        f"v = root / 'results' / 'phase1' / '{CASE}.json'\n"
        "d = json.loads(v.read_text())\n"
        "d['run_id'] = RID\n"
        "d['day2_marker'] = True\n"
        "v.write_text(json.dumps(d))\n"
        "print('run_id=' + RID)\n",
        encoding="utf-8")


@pytest.fixture()
def tree(tmp_path, mod, monkeypatch):
    """A whole repo-shaped tree the driver can be pointed at, with one day-1 verdict in it."""
    (tmp_path / "results" / "phase1").mkdir(parents=True)
    (tmp_path / "evidence").mkdir()
    day1 = dict(VERDICT, run_id=DAY1_RUN)
    (tmp_path / "results" / "phase1" / f"{CASE}.json").write_text(json.dumps(day1))
    for name, value in (("ROOT", tmp_path),
                        ("PHASE1", tmp_path / "results" / "phase1"),
                        ("ARCHIVE", tmp_path / "results" / "phase1" / "archive"),
                        ("CP_ROOT", tmp_path / "results" / "checkpoints"),
                        ("EVIDENCE", tmp_path / "evidence")):
        monkeypatch.setattr(mod, name, value)
    return tmp_path


def _drive(mod, tree: Path, *, run_id_written: str) -> int:
    script = tree / "producer_double.py"
    _write_double(script, run_id_written=run_id_written, day=mod.utc_today())
    return mod.main(["--cases", CASE, "--run-id", ASKED_RUN, "--allow-no-checkpoints",
                     "--", sys.executable, str(script)])


def test_a_producer_that_ignores_the_flag_is_adjudicated_not_written_off(mod, tree):
    """Item 33's closing condition: the run is scored on what the producer WROTE.

    The shipped driver returned 2 here — "the producer exited 0 but wrote no evidence record
    dated today" — because it counted records under `evidence/r20260821T000000Z`, a directory
    that was never created.
    """
    rc = _drive(mod, tree, run_id_written=DAY1_RUN)
    assert rc == 0, "a run whose records are on disk under another id must be adjudicated"

    out = json.loads((tree / "results" / f"day2_replication_{mod.utc_today()}.json").read_text())
    entry = out["runs"][-1]
    # Both ids are published, because they are two claims: what was asked for and what happened.
    assert entry["run_id"] == ASKED_RUN
    assert entry["run_ids_effective"] == [DAY1_RUN]
    assert entry["producer_honoured_run_id"] is False
    assert entry["fresh_records"] == 3, entry["observation_proof"]


def test_the_pre_fix_derivation_fails_on_this_same_double(mod, tree, monkeypatch):
    """THE MUTATION CONTROL for item 33: the old behaviour, on the identical double, returns 2.

    `recorded_run_ids` returning `[]` makes `effective` fall back to `[run_id]`, which is
    precisely what the driver did before it existed. If this arm ever passes with rc 0, the test
    above has stopped depending on the fix.
    """
    monkeypatch.setattr(mod, "recorded_run_ids", lambda before, after: [])
    assert _drive(mod, tree, run_id_written=DAY1_RUN) == 2


def test_a_producer_that_honours_the_flag_still_passes_under_the_old_derivation(mod, tree,
                                                                               monkeypatch):
    """Why the double above must LIE: an echoing one cannot distinguish the two versions.

    Same disabled derivation as the arm above, but a producer that writes under the id it was
    given — and the driver returns 0 either way. This is the arm that would have been written
    instead, and it would have shipped the bug.
    """
    monkeypatch.setattr(mod, "recorded_run_ids", lambda before, after: [])
    assert _drive(mod, tree, run_id_written=ASKED_RUN) == 0


def test_the_flag_is_honoured_case_is_recorded_as_such(mod, tree):
    """The honest-producer path publishes `producer_honoured_run_id: true` — the other claim."""
    assert _drive(mod, tree, run_id_written=ASKED_RUN) == 0
    out = json.loads((tree / "results" / f"day2_replication_{mod.utc_today()}.json").read_text())
    entry = out["runs"][-1]
    assert entry["run_ids_effective"] == [ASKED_RUN]
    assert entry["producer_honoured_run_id"] is True


def test_an_unplaceable_run_id_is_still_fatal(mod, tree):
    """The widening has a floor: an id that is neither asked-for nor any day-1 id stops the run.

    Without this the derivation would accept any id at all, and a producer resuming a THIRD
    run's state would have its old records counted as today's observation.
    """
    assert _drive(mod, tree, run_id_written="r20250101T000000Z") == 2


def test_a_producer_that_writes_nothing_still_fails(mod, tree):
    """The rc-2 path item 33 changed must remain reachable when it is actually true."""
    script = tree / "silent_double.py"
    script.write_text("print('did nothing')\n", encoding="utf-8")
    rc = mod.main(["--cases", CASE, "--run-id", ASKED_RUN, "--allow-no-checkpoints",
                   "--", sys.executable, str(script)])
    assert rc == 2
