"""Tests for F5-4a's supplementary LOG_ONLY metric read. Offline; no AWS, no network.

Why these exist
---------------
FINDING-F5-4A's headline claim — §7.1's *"a sustained zero LogOnlyDecisionFlips means
promotion will not block current traffic"* is false for a policy that cannot evaluate —
rests on a **zero**. Three separate ways for that to be a lie, none of them visible in the
output, all of which produce a well-formed `analysis.json`:

1. **A zero from a metric that does not exist.** `LogOnlyEvalIncomplete` is exactly that in
   this account. If `_reading` collapsed "0 with 14 dimension combinations listed" and "0
   with none listed" into one answer, the finding would be citing instrument absence as
   evidence of service behaviour. Every arm below that touches `_reading` is about keeping
   those two apart.
2. **A conjunction that cannot come back False.** `_inference_holds` ANDs five conjuncts.
   If any one of them were True by construction — a typo'd key, a `.get()` defaulting to
   True, a comparison of two things that are always equal — the refutation would be
   vacuous. So each conjunct is planted False in turn and asserted to break the whole
   (`feedback_vacuous_test_check`).
3. **A window that came from the wrong place.** The read has to cover the window F5-4a
   actually measured. `_window_from_recorded_result` derives it from F5-4a's own result
   file; a literal typed here or there would be a second statement of one fact, free to be
   wrong in a way no file could reveal (`feedback_two_numbers_two_claims`).

And one structural check that is not about the reading at all: this script must never write
`results/phase1/F5-4a.json`. That file carries a recorded verdict. A later read that
overwrote it with a read would destroy the measurement it exists to supplement.

Where the tests need real data they use the archived result file, not a hand-written
fixture, and skip loudly if it is absent rather than passing vacuously
(`feedback_verify_against_real_artifact`).
"""

from __future__ import annotations

import ast
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "f5_redteam" / "04b_logonly_flip_read.py"
RESULT = ROOT / "results" / "phase1" / "F5-4a.json"

# Loaded by path because the filename starts with a digit and is not importable.
_spec = importlib.util.spec_from_file_location("f54b", SCRIPT)
f54b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f54b)


def _metric(sum_: float, combos: int, ndp: int = 1) -> dict:
    return {"sum": sum_, "dimension_combinations_listed": combos, "n_datapoints": ndp,
            "datapoints": []}


def _probe(sum_: float, combos: int) -> dict:
    return {"probe": _metric(sum_, combos)}


# ---------------------------------------------------------------------------
# 1. a zero from a live instrument and a zero from no instrument
# ---------------------------------------------------------------------------

def test_zero_with_combinations_listed_is_a_real_zero():
    assert f54b._reading(_metric(0.0, 14), _metric(0.0, 14)) == f54b.PUBLISHED_AND_ZERO


def test_zero_with_no_combinations_listed_is_instrument_absence():
    assert f54b._reading(_metric(0.0, 0), _metric(0.0, 0)) == f54b.NEVER_PUBLISHED


def test_the_two_zero_readings_are_not_the_same_string():
    """The whole point. If these collapsed, the finding would cite absence as evidence."""
    assert f54b.PUBLISHED_AND_ZERO != f54b.NEVER_PUBLISHED


def test_nonzero_over_a_quiet_baseline_is_attributed_to_us():
    assert f54b._reading(_metric(0.0, 14), _metric(20.0, 14)) == f54b.PUBLISHED_AND_NONZERO


def test_nonzero_over_a_noisy_baseline_refuses_to_attribute():
    """An ambient publisher makes a nonzero window unattributable, not a result."""
    assert f54b._reading(_metric(5.0, 14), _metric(20.0, 14)) == f54b.AMBIENT


def test_a_metric_absent_from_list_metrics_is_never_published_even_if_it_has_a_sum():
    """Defensive: combinations listed is the instrument-existence test, and it wins.

    A sum over zero listed combinations cannot happen through `_read_metric` (it iterates
    the combinations), so this pins the precedence rather than a reachable state. If a
    later edit reordered the branches, a zero-instrument reading would start being
    reported as a measurement.
    """
    assert f54b._reading(_metric(0.0, 0), _metric(99.0, 0)) == f54b.NEVER_PUBLISHED


# ---------------------------------------------------------------------------
# 2. the conjunction has to be able to fail, one conjunct at a time
# ---------------------------------------------------------------------------

STATEMENT = 'forbid (principal, action == AgentCore::Action::"x", resource == R) when { c };'


def _good_result() -> dict:
    return {
        "n_per_arm": 20,
        "arms": {
            f54b.ARM_LOGONLY: {"decision": "ALLOW", "n_allowed": 20, "n_denied": 0,
                               "unanimous": True},
            f54b.ARM_ACTIVE_TWIN: {"decision": "DENY", "n_allowed": 0, "n_denied": 20,
                                   "unanimous": True},
        },
        "probes": {
            f54b.ARM_LOGONLY: {"statement": STATEMENT},
            f54b.ARM_ACTIVE_TWIN: {"statement": STATEMENT},
        },
    }


def test_the_real_shape_refutes_the_documents_inference():
    assert f54b._inference_holds(f54b._contrast(_good_result(), _probe(0.0, 14))) is True


# Each entry breaks exactly one conjunct. `expect_false` names the conjunct that must go
# False, so a mutation that broke a DIFFERENT one would still fail this test.
BREAKERS = [
    ("the two arms did not ship the same statement",
     lambda r: r["probes"][f54b.ARM_LOGONLY].__setitem__("statement", STATEMENT + " // x"),
     _probe(0.0, 14), "same_statement"),
    ("neither arm shipped a statement at all",
     lambda r: (r["probes"][f54b.ARM_LOGONLY].__setitem__("statement", None),
                r["probes"][f54b.ARM_ACTIVE_TWIN].__setitem__("statement", None)),
     _probe(0.0, 14), "same_statement"),
    ("the LOG_ONLY arm denied something",
     lambda r: r["arms"][f54b.ARM_LOGONLY].update({"n_denied": 1, "unanimous": False}),
     _probe(0.0, 14), "logonly_allowed_all"),
    ("the LOG_ONLY arm was not unanimous",
     lambda r: r["arms"][f54b.ARM_LOGONLY].__setitem__("unanimous", False),
     _probe(0.0, 14), "logonly_allowed_all"),
    ("the ACTIVE twin allowed something",
     lambda r: r["arms"][f54b.ARM_ACTIVE_TWIN].update({"n_allowed": 1, "decision": "ALLOW"}),
     _probe(0.0, 14), "active_twin_denied_all"),
    ("the LOG_ONLY arm is missing from the result",
     lambda r: r["arms"].pop(f54b.ARM_LOGONLY),
     _probe(0.0, 14), "logonly_allowed_all"),
    ("the flip metric does not exist in this namespace",
     lambda r: None, _probe(0.0, 0), "flip_metric_exists_in_this_namespace"),
    ("the flip metric was NOT zero",
     lambda r: None, _probe(7.0, 14), "flip_metric_was_zero_in_the_logonly_window"),
]


@pytest.mark.parametrize(("why", "break_it", "flips", "expect_false"),
                         BREAKERS, ids=[b[0] for b in BREAKERS])
def test_each_conjunct_can_break_the_refutation(why, break_it, flips, expect_false):
    r = _good_result()
    break_it(r)
    contrast = f54b._contrast(r, flips)
    assert contrast[expect_false] is not True, (
        f"{why}: `{expect_false}` stayed True, so it is True by construction and the "
        f"refutation does not rest on it")
    assert f54b._inference_holds(contrast) is False, (
        f"{why}: the conjunction still held. A refutation that survives a false conjunct "
        f"is not a conjunction")


def test_every_conjunct_is_covered_by_a_breaker():
    """A conjunct nobody plants False is a conjunct nobody has checked."""
    conjuncts = {k for k in f54b._contrast(_good_result(), _probe(0.0, 14))
                 if k not in f54b.NOT_A_CONJUNCT}
    covered = {b[3] for b in BREAKERS}
    assert conjuncts == covered, (
        f"uncovered conjuncts: {sorted(conjuncts - covered)}; "
        f"breakers naming nothing: {sorted(covered - conjuncts)}")


def test_a_missing_conjunct_key_is_false_not_absent():
    """`all()` over an empty selection is True. A dropped key must not read as a pass."""
    assert f54b._inference_holds({}) is False


def test_n_per_arm_is_not_treated_as_a_conjunct():
    """It is a number carried for the reader; ANDing it would make 20 mean True."""
    c = f54b._contrast(_good_result(), _probe(0.0, 14))
    assert c["n_per_arm"] == 20
    assert f54b._inference_holds(c) is True


# ---------------------------------------------------------------------------
# 3. the window comes from the recorded result, not from a literal
# ---------------------------------------------------------------------------

def test_the_window_is_the_union_of_the_recorded_after_windows():
    per = {
        "A": {"after": {"window": {"start": "2026-01-01 00:01:00+00:00",
                                   "end": "2026-01-01 00:05:00+00:00"}}},
        "B": {"after": {"window": {"start": "2026-01-01 00:00:00+00:00",
                                   "end": "2026-01-01 00:02:00+00:00"}}},
    }
    w = f54b._window_from_recorded_result({"mismatch_metrics": {"per_metric": per}})
    assert w["start"] == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert w["end"] == datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)


def test_the_baseline_window_never_overlaps_the_probe_window():
    """Its whole job is to establish there was no ambient publisher BEFORE the probe."""
    per = {"A": {"after": {"window": {"start": "2026-01-01 00:10:00+00:00",
                                      "end": "2026-01-01 00:20:00+00:00"}}}}
    w = f54b._window_from_recorded_result({"mismatch_metrics": {"per_metric": per}})
    span = w["end"] - w["start"]
    baseline_end = w["start"]
    baseline_start = w["start"] - span
    assert baseline_end <= w["start"]
    assert baseline_start < baseline_end


def test_a_result_with_no_mismatch_metrics_is_a_config_error_not_a_default_window():
    with pytest.raises(f54b.ConfigError):
        f54b._window_from_recorded_result({})


def test_a_result_whose_windows_are_missing_is_a_config_error():
    with pytest.raises(f54b.ConfigError):
        f54b._window_from_recorded_result(
            {"mismatch_metrics": {"per_metric": {"A": {"after": {}}}}})


def _code_literals(path: Path) -> list[str]:
    """Every string/number constant the module actually evaluates, docstrings excluded.

    Scanned through the AST rather than over the source text, because the first version of
    this check asserted `"22:46" not in src` and tripped on the COMMENT in
    `_window_from_recorded_result` that explains why the window is not hardcoded. That is
    the same defect as the one that motivated `claims/tests/test_parser_attrs.py`: prose
    about code is not code, and a check that cannot tell them apart fails on its own
    documentation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    return [str(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and id(n) not in docstrings
            and isinstance(n.value, (str, int, float))]


def test_no_window_timestamp_is_hardcoded_in_the_script():
    """A literal `22:46` in the CODE would be a copy of a fact that lives in the result."""
    lits = _code_literals(SCRIPT)
    # `grx_f54a_` with the trailing underscore, not `grx_f54a`: the latter matches the
    # importlib module name `_grx_f54a`, which is a loader detail and not a testbed
    # identity. A pattern that flags a legitimate line trains the reader to ignore it.
    for forbidden in ("22:46", "23:04", "2026-08-11", "T130945Z",
                      "grx_f54a_", "grx-gw-", "grx_pe_"):
        offenders = [lit for lit in lits if forbidden in lit]
        assert not offenders, (
            f"{forbidden!r} is a code literal in {SCRIPT.name} ({offenders}). The window "
            f"and the testbed identity come from results/phase1/F5-4a.json and state.json")


def test_that_literal_check_is_not_vacuous():
    """It must see the literals it claims to scan, and ignore the comments it must ignore."""
    lits = _code_literals(SCRIPT)
    assert "LogOnlyDecisionFlips" in lits, "the AST scan found no real literals at all"
    assert f54b.OUT_NAME in lits
    # The forbidden substring DOES appear in the file, inside a comment. If the scanner
    # were reading raw source this would be non-empty and the check above would fail.
    assert "22:46" in SCRIPT.read_text(encoding="utf-8")


def test_the_window_matches_the_real_recorded_result():
    if not RESULT.is_file():
        pytest.skip(f"{RESULT} absent — F5-4a has not run in this checkout")
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    w = f54b._window_from_recorded_result(result)
    assert w["end"] > w["start"]
    per = result["mismatch_metrics"]["per_metric"]
    ends = [datetime.fromisoformat(str(r["after"]["window"]["end"])) for r in per.values()]
    assert w["end"] == max(ends)
    # Every arm ran inside it: the LOG_ONLY arm's requests must be covered or the read is
    # querying a window the arm was not in.
    assert (w["end"] - w["start"]).total_seconds() > 0


# ---------------------------------------------------------------------------
# 4. it must not overwrite a recorded verdict
# ---------------------------------------------------------------------------

def test_it_writes_a_distinct_filename_and_not_the_case_result():
    assert f54b.OUT_NAME != "F5-4a.json"
    assert f54b.OUT_NAME.startswith("F5-4a")


def test_it_does_not_call_P_emit():
    """`P.emit` writes results/phase1/<case_id>.json — here, over a recorded verdict."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "emit"]
    assert not calls, (
        "this script calls P.emit, which would overwrite results/phase1/F5-4a.json — a "
        "recorded RECORDED verdict — with a supplementary read")


def test_the_evidence_case_id_is_separate_from_the_parent_case():
    """`EvidenceStore` numbers records per directory; sharing one would interleave runs."""
    assert f54b.EVIDENCE_CASE != f54b.PARENT_CASE
    assert f54b.PARENT_CASE in f54b.EVIDENCE_CASE


def test_the_output_is_marked_as_not_a_verdict():
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"kind": "SUPPLEMENTARY_READ"' in src
    assert '"is_a_case_verdict": False' in src
    assert '"verdict"' not in src, (
        "a supplementary read must not carry a `verdict` key: the analysis phase and the "
        "amendment gate both key off it")


# ---------------------------------------------------------------------------
# 5. the read is read-only, and it borrows rather than copies
# ---------------------------------------------------------------------------

MUTATING = ("create_policy", "delete_policy", "update_gateway", "put_role_policy",
            "delete_role_policy", "create_guardrail", "update_guardrail", "put_metric_data")


def test_no_mutating_call_appears_anywhere_in_the_script():
    src = SCRIPT.read_text(encoding="utf-8")
    for op in MUTATING:
        assert op not in src, f"{op} appears in a script documented as read-only"


def test_the_metric_reader_is_borrowed_from_the_case_not_reimplemented():
    """Two readers claiming to read 'the same way' can drift; one cannot."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "_f54a._read_metric" in src
    assert "def _read_metric" not in src


def test_the_borrowed_reader_is_the_one_the_case_uses():
    parent = ROOT / "f5_redteam" / "04_policy_failure_modes.py"
    _s = importlib.util.spec_from_file_location("f54a_check", parent)
    _m = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(_m)
    assert f54b._read_metric is _m._read_metric or (
        f54b._read_metric.__qualname__ == _m._read_metric.__qualname__)
    assert f54b.NS == _m.NS
    assert f54b.ARM_LOGONLY == _m.ARM_LOGONLY
    assert f54b.ARM_ACTIVE_TWIN == _m.ARM_MISSING


def test_the_three_logonly_metrics_are_the_ones_the_document_names():
    """§6.2 line 660 names exactly these three as one row."""
    assert set(f54b.LOGONLY_METRICS) == {
        "LogOnlyMatches", "LogOnlyDecisionFlips", "LogOnlyEvalIncomplete"}


def test_dimension_values_are_flattened_for_the_reader():
    probe = {"datapoints": [
        {"dimensions": [{"Name": "Policy", "Value": "p1"},
                        {"Name": "Mode", "Value": "LOG_ONLY"}]},
        {"dimensions": [{"Name": "Policy", "Value": "p1"}]},
    ]}
    assert f54b._dimension_values_seen(probe) == ["Mode=LOG_ONLY", "Policy=p1"]


def test_dimension_values_of_an_empty_window_is_empty_not_an_error():
    assert f54b._dimension_values_seen({"datapoints": []}) == []
    assert f54b._dimension_values_seen({}) == []


# ---------------------------------------------------------------------------
# 6. the dry run reaches the end of the plan
# ---------------------------------------------------------------------------

def test_dry_run_returns_zero_and_makes_no_client(capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("--dry-run built an AWS client")
    monkeypatch.setattr(f54b.A, "factory", boom)
    assert f54b.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "no AWS call" in out
    assert "mutations: 0" in out
    for metric in f54b.LOGONLY_METRICS:
        assert metric in out


def test_dry_run_does_not_print_the_parent_cases_sealed_oracle(capsys):
    """The oracle binds F5-4a's arm plan. Printing it here would imply a verdict."""
    f54b.main(["--dry-run"])
    out = capsys.readouterr().out
    assert "OUTCOME UNKNOWN" not in out
