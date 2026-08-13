"""Tests for F9-2's verdict emitter. Offline; no AWS, no network, and no write into results/.

Why these exist
---------------
F9-2's verdict is `observed: True` — the mismatch metrics DID increment when a policy could
not evaluate. A TRUE built from archived reads has three distinct ways to be a lie, and none
of them shows up in the output:

1. **An increment measured against nothing.** "It incremented" is a claim about two readings:
   a zero before and a positive after. If the "before" read is not actually before, the
   before/after structure is decoration. Two bugs of exactly this shape were caught by the
   script's own guards while it was being written, and both are pinned below:
   `test_a_window_that_closes_after_the_firing_is_not_its_baseline` (the offsets) and
   `test_an_earlier_firing_does_not_contaminate_a_later_episode` (the interval).
2. **A conjunction that shrank to fit.** The sealed oracle names two metrics. If a silent
   `PolicyMismatch` could be absorbed as "context" while `MismatchErrors` carried the verdict
   alone, TRUE would mean less than it says.
3. **A zero that measures our test plan.** If nothing was ever asked of a broken policy, a
   silent metric says nothing about the service. That is what `basis()` is for, and it must
   refuse rather than publish FALSE.

Two arms are built from RECORDS THAT LIE — a datapoint stamped outside the window that
returned it. That shape does not occur in the archived evidence, and the tests say so where
they use it: the guards it exercises are defences against a record that misdescribes itself,
not reconstructions of something CloudWatch did (`feedback_unreachable_branch_in_fake` — an
honest double never reaches the dishonest branch).

Where a fixture stands in for the real tree it is written in the real record shape, and the
happy path is asserted against the real evidence and skips loudly if it is absent
(`feedback_verify_against_real_artifact`).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# The subject. Overridable by env for ONE caller only: `test_mismatch_verdict_mutation.py`
# copies this file into a sandbox and points it at a deliberately broken COPY of the script,
# so the arms below can be shown to fail. The live script is never mutated in place — the same
# safety argument `lib/tests/test_write_guard_mutation.py` makes through `GRX_CONFTEST`.
SCRIPT = Path(os.environ.get("GRX_F92_SCRIPT")
              or ROOT / "f9_failsecure" / "00_mismatch_verdict.py")

# Loaded by path because the filename starts with a digit. The registered name is a literal
# here so lib/tests/test_module_name_collisions.py can read it statically.
_spec = importlib.util.spec_from_file_location("f9_mismatch_verdict", SCRIPT)
f92 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f92)


# --------------------------------------------------------------------------- fixtures

def _dp(t: str, sum_: float, samples: float = 0.0) -> dict:
    return {"Timestamp": t, "Sum": sum_, "SampleCount": samples or sum_,
            "Unit": "Count"}


def _read(root: Path, idx: int, metric: str, start: str, end: str,
          datapoints: list[dict] | None = None, *, sub: bool = False) -> Path:
    """One archived `get_metric_statistics` record, in the shape the real ones carry."""
    d = root / "evidence" / f92.SOURCE_RUN
    d = d.joinpath(*(f92.SUPPLEMENTARY_DIR if sub else f92.SOURCE_CASE_DIR))
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{idx:04d}_get_metric_statistics_ok.json"
    p.write_text(json.dumps({
        "case_id": "F5-4a", "operation": "get_metric_statistics", "ok": True,
        "service": "cloudwatch", "http_status": 200, "retry_attempts": 0,
        "params": {"Namespace": "AWS/Bedrock-AgentCore", "MetricName": metric,
                   "StartTime": start, "EndTime": end, "Period": 60,
                   "Statistics": ["Sum", "SampleCount"],
                   "Dimensions": [{"Name": "OperationName", "Value": "AuthorizeAction"}]},
        "response": {"Label": metric, "Datapoints": datapoints or []},
    }), encoding="utf-8")
    return p


def _basis(root: Path, *, tools_call: int = 20, create: int = 1, delete: int = 1) -> None:
    """The exercise basis, as files on disk — `basis()` counts them and reads no summary.

    Clears any records a previous call left, so a test that asks for 7 gets 7. Writing over
    the same filenames is what made the first version of the counting arm read 20: the
    fixture, not the code, and a fixture that silently keeps stale files is the same defect
    as a stale bytecode cache (`feedback_pyc_serves_the_mutant`).
    """
    d = root / "evidence" / f92.SOURCE_RUN
    d = d.joinpath(*f92.SOURCE_CASE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    for pat in ("*_mcp-tools-call_ok.json", "*_create_policy_ok.json",
                "*_delete_policy_ok.json"):
        for stale in d.glob(pat):
            stale.unlink()
    for i in range(tools_call):
        (d / f"{100 + i:04d}_mcp-tools-call_ok.json").write_text("{}", encoding="utf-8")
    for i in range(create):
        (d / f"{200 + i:04d}_create_policy_ok.json").write_text("{}", encoding="utf-8")
    for i in range(delete):
        (d / f"{300 + i:04d}_delete_policy_ok.json").write_text("{}", encoding="utf-8")


# Two firings 75 minutes apart across a UTC day boundary — the real shape of F5-4a's two
# runs. The clean baseline for each sits in the quiet interval immediately before it.
T1 = "2026-08-11T22:47:00+00:00"
T2 = "2026-08-12T00:02:00+00:00"


def _two_episode_tree(root: Path, metrics: tuple[str, ...] | None = None,
                      *, idx0: int = 1) -> Path:
    """`idx0` keeps two calls on one tree from writing over each other's filenames.

    Without it, a second call for a different metric silently REPLACED the first metric's
    records — the tree looked complete and the verdict was computed from half of it.
    """
    idx = idx0
    for metric in (metrics if metrics is not None else f92.REQUIRED):
        _read(root, idx, metric, "2026-08-11T21:47:00+00:00", "2026-08-11T22:46:33+00:00")
        _read(root, idx + 1, metric, "2026-08-11T21:47:00+00:00",
              "2026-08-11T22:48:36+00:00", [_dp(T1, 20.0, 20.0)])
        _read(root, idx + 2, metric, "2026-08-11T23:00:00+00:00",
              "2026-08-12T00:01:00+00:00")
        _read(root, idx + 3, metric, "2026-08-11T23:00:00+00:00",
              "2026-08-12T00:03:00+00:00", [_dp(T2, 20.0, 20.0)])
        idx += 10
    _basis(root)
    return root


def _clean_pair(root: Path, metric: str, *, idx0: int = 60) -> None:
    """One quiet baseline and one firing for `metric` — a metric that raises no guard.

    `decide()` walks every metric the oracle names, so an arm about ONE metric's guard has to
    give the other a clean history or the refusal it observes is the missing-read refusal
    wearing the same exception type.
    """
    _read(root, idx0, metric, "2026-08-11T21:47:00+00:00", "2026-08-11T22:46:33+00:00")
    _read(root, idx0 + 1, metric, "2026-08-11T21:47:00+00:00",
          "2026-08-11T22:48:36+00:00", [_dp(T1, 20.0, 20.0)])


# --------------------------------------------------------------------------- 1. timestamps

def test_a_naive_timestamp_is_refused_rather_than_assumed_utc():
    """Assuming UTC here is the assumption that produced the offset bug."""
    with pytest.raises(f92.Refusal):
        f92._utc("2026-08-11T22:47:00")


def test_an_unparseable_timestamp_is_refused():
    with pytest.raises(f92.Refusal):
        f92._utc("last tuesday")


def test_two_spellings_of_one_instant_compare_equal():
    assert f92._utc("2026-08-12T05:47:00+07:00") == f92._utc("2026-08-11T22:47:00+00:00")


def test_the_offset_spelling_orders_the_other_way_as_a_string():
    """The premise of the arm below, stated so it cannot silently stop being true.

    If these ever compared the same way lexicographically and as instants, the regression
    test that follows would pass for the wrong reason.
    """
    assert "2026-08-11T22:48:36+00:00" <= "2026-08-12T05:47:00+07:00"
    assert f92._utc("2026-08-11T22:48:36+00:00") > f92._utc("2026-08-12T05:47:00+07:00")


def test_a_window_that_closes_after_the_firing_is_not_its_baseline(tmp_path):
    """The regression, pinned. CloudWatch stamped the datapoints +07:00; the windows were
    sent +00:00. Comparing the two as strings offered a read that closed 96 seconds AFTER the
    firing as that firing's baseline — twelve of them, in the first version of this file.
    """
    _read(tmp_path, 1, "MismatchErrors", "2026-08-11T21:47:00+00:00",
          "2026-08-11T22:48:36+00:00", [_dp("2026-08-12T05:47:00+07:00", 20.0, 20.0)])
    late = _read(tmp_path, 2, "MismatchErrors", "2026-08-11T22:48:00+00:00",
                 "2026-08-11T22:48:36+00:00")
    _basis(tmp_path)

    reads = f92.load_reads(tmp_path)
    eps = f92.episodes_for("MismatchErrors", reads, required=True)
    assert len(eps) == 1
    assert eps[0]["n_baseline_reads"] == 0, (
        "a window that closed after the firing was counted as its baseline, which is the "
        "string-comparison bug back again")
    assert late.name not in json.dumps(eps[0])

    # And with no measured zero, the verdict is refused rather than computed. The other named
    # metric is given a clean history so the refusal below is this guard's and not the
    # missing-read guard's.
    _clean_pair(tmp_path, "PolicyMismatch")
    reads = f92.load_reads(tmp_path)
    with pytest.raises(f92.Refusal, match="no measured zero"):
        f92.decide(reads)


def test_that_regression_arm_is_not_vacuous(tmp_path):
    """A genuinely earlier window IS a baseline, so the arm above fails for the right reason."""
    _read(tmp_path, 1, "MismatchErrors", "2026-08-11T21:47:00+00:00",
          "2026-08-11T22:48:36+00:00", [_dp("2026-08-12T05:47:00+07:00", 20.0, 20.0)])
    _read(tmp_path, 2, "MismatchErrors", "2026-08-11T21:47:00+00:00",
          "2026-08-11T22:46:33+00:00")
    _basis(tmp_path)
    eps = f92.episodes_for("MismatchErrors", f92.load_reads(tmp_path), required=True)
    assert eps[0]["n_baseline_reads"] == 1


# --------------------------------------------------------------------------- 2. intervals

def test_an_earlier_firing_does_not_contaminate_a_later_episode(tmp_path):
    """The second regression. Written as "any window that closed before this firing", every
    day-1 read is a candidate baseline for day 2 — and day 1 fired, so those reads are
    positive and the contamination guard rejected an episode that was clean on its own
    interval. The baseline is the QUIET INTERVAL between consecutive firings.
    """
    _two_episode_tree(tmp_path, ("MismatchErrors",))
    eps = f92.episodes_for("MismatchErrors", f92.load_reads(tmp_path), required=True)
    assert [e["t"] for e in eps] == [T1, T2]
    for e in eps:
        assert not e["reads_before_the_firing_that_were_already_positive"], (
            f"the firing at {e['t']} was called contaminated by a DIFFERENT firing")
        assert e["n_baseline_reads"] == 1
    assert eps[0]["baseline_interval_opens_after"] is None
    assert eps[1]["baseline_interval_opens_after"] == f92._utc(T1).isoformat()


def test_the_two_episodes_have_disjoint_baselines(tmp_path):
    """Sharing one baseline read between two episodes would be one measurement counted twice."""
    _two_episode_tree(tmp_path, ("MismatchErrors",))
    eps = f92.episodes_for("MismatchErrors", f92.load_reads(tmp_path), required=True)
    a = {tuple(w) for w in eps[0]["baseline_windows"]}
    b = {tuple(w) for w in eps[1]["baseline_windows"]}
    assert a and b and not (a & b)


def test_two_reads_of_one_firing_are_one_episode_not_two(tmp_path):
    """Keyed by the stamped minute, so a re-read of an old window cannot become a new episode."""
    _read(tmp_path, 1, "MismatchErrors", "2026-08-11T21:47:00+00:00",
          "2026-08-11T22:46:33+00:00")
    _read(tmp_path, 2, "MismatchErrors", "2026-08-11T21:47:00+00:00",
          "2026-08-11T22:48:36+00:00", [_dp(T1, 20.0, 20.0)])
    _read(tmp_path, 3, "MismatchErrors", "2026-08-11T21:50:00+00:00",
          "2026-08-11T23:30:00+00:00", [_dp(T1, 20.0, 20.0)])
    _basis(tmp_path)
    eps = f92.episodes_for("MismatchErrors", f92.load_reads(tmp_path), required=True)
    assert len(eps) == 1
    assert eps[0]["seen_in_reads"] == 2
    # And reading one firing twice does not make it twice as large. These two lines exist
    # because of M12 in test_mismatch_verdict_mutation.py: accumulating instead of taking the
    # maximum passes every OTHER arm in this file (measured — 29 passed, 0 failed) and would
    # have reported 40 mismatches from 20 requests.
    assert eps[0]["sum"] == 20.0
    assert eps[0]["samples"] == 20.0


def test_an_already_positive_baseline_interval_is_refused(tmp_path):
    """A record that misdescribes its own window, and the guard that will not score it.

    This shape does NOT occur in the archived evidence and cannot arise while CloudWatch
    returns datapoints inside the window that was asked for: a positive datapoint inside the
    quiet interval would itself be the previous firing, which moves the interval. It is built
    here from a LYING record — a datapoint stamped after the window that returned it — because
    a guard nobody can make fire is a guard nobody has checked. What it defends is the case
    where the recorded window and the recorded datapoints disagree; then no increment is
    attributable in either direction, and refusing beats picking one.
    """
    _read(tmp_path, 1, "MismatchErrors", "2026-08-11T23:00:00+00:00",
          "2026-08-12T00:01:00+00:00", [_dp("2026-08-12T09:00:00+00:00", 7.0, 7.0)])
    _read(tmp_path, 2, "MismatchErrors", "2026-08-11T23:00:00+00:00",
          "2026-08-12T00:03:00+00:00", [_dp(T2, 20.0, 20.0)])
    _clean_pair(tmp_path, "PolicyMismatch")
    _basis(tmp_path)
    with pytest.raises(f92.Refusal, match="already positive"):
        f92.decide(f92.load_reads(tmp_path))


# --------------------------------------------------------------------------- 3. the verdict

def test_both_named_metrics_firing_is_the_true_verdict(tmp_path):
    _two_episode_tree(tmp_path)
    b = f92.build(tmp_path)
    assert b["decision"]["observed"] is True
    assert b["decision"]["fired"] == {m: True for m in f92.REQUIRED}
    assert b["decision"]["n_episodes"] == 2


def test_a_silent_metric_makes_it_false_and_not_a_refusal(tmp_path):
    """The oracle's FALSE: read, exercised, and nothing published. Not an error."""
    for i, metric in enumerate(f92.REQUIRED):
        _read(tmp_path, 1 + i * 10, metric, "2026-08-11T21:47:00+00:00",
              "2026-08-11T22:46:33+00:00")
        _read(tmp_path, 2 + i * 10, metric, "2026-08-11T21:47:00+00:00",
              "2026-08-11T22:48:36+00:00")
    _basis(tmp_path)
    d = f92.build(tmp_path)["decision"]
    assert d["observed"] is False
    assert d["fired"] == {m: False for m in f92.REQUIRED}
    assert d["n_episodes"] == 0


def test_one_silent_named_metric_is_enough_to_make_it_false(tmp_path):
    """The conjunction is over both names the sealed oracle gives, not over whichever fired."""
    _two_episode_tree(tmp_path, ("MismatchErrors",))
    _read(tmp_path, 50, "PolicyMismatch", "2026-08-11T21:47:00+00:00",
          "2026-08-11T22:48:36+00:00")
    d = f92.build(tmp_path)["decision"]
    assert d["fired"] == {"MismatchErrors": True, "PolicyMismatch": False}
    assert d["observed"] is False


def test_a_corroborating_metric_cannot_carry_the_verdict(tmp_path):
    """Widening a sealed conjunction after seeing the data is choosing a result."""
    _two_episode_tree(tmp_path, f92.CORROBORATING)
    for i, metric in enumerate(f92.REQUIRED):
        _read(tmp_path, 50 + i, metric, "2026-08-11T21:47:00+00:00",
              "2026-08-11T22:48:36+00:00")
    d = f92.build(tmp_path)["decision"]
    assert d["per_metric"][f92.CORROBORATING[0]]["fired"] is True
    assert d["observed"] is False


def test_the_sub_result_metric_is_reported_and_never_scored(tmp_path):
    """`LogOnlyEvalIncomplete` belongs to C-s6-4-trow-006, not to this oracle."""
    _two_episode_tree(tmp_path)
    _two_episode_tree(tmp_path, f92.SUB_RESULT, idx0=41)
    d = f92.build(tmp_path)["decision"]
    assert d["per_metric"][f92.SUB_RESULT[0]]["fired"] is True
    assert set(d["fired"]) == set(f92.REQUIRED)
    assert d["observed"] is True
    for name in f92.SUB_RESULT:
        assert name not in d["fired"]


def test_a_named_metric_with_no_read_at_all_is_refused(tmp_path):
    """Its silence would be our omission, not the service's."""
    _two_episode_tree(tmp_path, ("MismatchErrors",))
    with pytest.raises(f92.Refusal, match="PolicyMismatch"):
        f92.build(tmp_path)


def test_a_context_metric_with_no_read_is_simply_nothing_to_report(tmp_path):
    _two_episode_tree(tmp_path)
    d = f92.build(tmp_path)["decision"]
    for name in f92.CONTEXT:
        assert d["per_metric"][name] == {"n_reads": 0, "episodes": [], "n_episodes": 0,
                                         "fired": False}


# --------------------------------------------------------------------------- 4. the basis

def test_no_tools_call_record_is_refused_rather_than_published_as_false(tmp_path):
    """A zero that measures our test plan is not a verdict about the service."""
    _two_episode_tree(tmp_path)
    for p in (tmp_path / "evidence" / f92.SOURCE_RUN).joinpath(
            *f92.SOURCE_CASE_DIR).glob("*_mcp-tools-call_ok.json"):
        p.unlink()
    with pytest.raises(f92.Refusal, match="tools/call"):
        f92.build(tmp_path)


def test_no_create_policy_record_is_refused(tmp_path):
    """"when a policy cannot evaluate" presupposes such a policy existed."""
    _two_episode_tree(tmp_path)
    for p in (tmp_path / "evidence" / f92.SOURCE_RUN).joinpath(
            *f92.SOURCE_CASE_DIR).glob("*_create_policy_ok.json"):
        p.unlink()
    with pytest.raises(f92.Refusal, match="create_policy"):
        f92.build(tmp_path)


def test_the_basis_is_counted_on_disk_and_not_read_from_a_summary(tmp_path):
    _two_episode_tree(tmp_path)
    _basis(tmp_path, tools_call=7, create=2, delete=3)
    b = f92.basis(tmp_path)
    assert b == {"mcp_tools_call": 7, "create_policy": 2, "delete_policy": 3}


def test_an_empty_evidence_tree_is_refused_not_reported_as_silence(tmp_path):
    """A read of zero records must never look like a metric that did not fire."""
    with pytest.raises(f92.Refusal, match="no get_metric_statistics records"):
        f92.load_reads(tmp_path)


def test_an_unclassified_metric_name_is_fatal(tmp_path):
    """F5-4a growing a fifth metric must be a decision here, not a silent omission."""
    _two_episode_tree(tmp_path)
    _read(tmp_path, 90, "SomeNewMismatchSignal", "2026-08-11T21:47:00+00:00",
          "2026-08-11T22:48:36+00:00", [_dp(T1, 20.0, 20.0)])
    with pytest.raises(f92.Refusal, match="SomeNewMismatchSignal"):
        f92.load_reads(tmp_path)


def test_the_supplementary_directory_is_read_too(tmp_path):
    """F5-4a's later read lives in its own evidence dir; dropping it would shrink the basis."""
    _two_episode_tree(tmp_path)
    _read(tmp_path, 1, "LogOnlyMatches", "2026-08-11T23:00:00+00:00",
          "2026-08-12T00:03:00+00:00", sub=True)
    reads = f92.load_reads(tmp_path)
    assert any(str(Path(*f92.SUPPLEMENTARY_DIR)) in r["file"] for r in reads)


# --------------------------------------------------------------------------- 5. structural

def test_the_script_makes_no_aws_call_and_bills_nothing():
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {n.names[0].name.split(".")[0]
                for n in ast.walk(tree) if isinstance(n, ast.Import)} | {
        (n.module or "").split(".")[0]
        for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "boto3" not in imported
    assert "awsclient" not in imported, (
        "this case is discharged from archived reads; a client here would make it a live run")
    assert '"billable_calls": 0' in src
    assert '"aws_calls": 0' in src


def test_it_emits_under_its_own_case_id_and_does_not_touch_f5_4a(tmp_path):
    """F5-4a's result file carries a recorded verdict; F9-2 reads it and must not write it."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    emits = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "emit"]
    assert len(emits) == 1
    assert isinstance(emits[0].args[0], ast.Name) and emits[0].args[0].id == "CASE"
    assert f92.CASE == "F9-2"


def test_the_paired_case_is_named_in_the_record_not_only_in_prose():
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'paired_case="F5-4a"' in src


def test_n_is_passed_to_obs_existence_as_the_exercise_basis():
    """`n` is keyword-only and required; its absence once published a manufactured shortfall."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "obs_existence"]
    assert len(calls) == 1
    kw = {k.arg for k in calls[0].keywords}
    assert "n" in kw
    assert {"reading", "source", "what_this_does_not_prove"} <= kw


def test_the_replication_note_does_not_sell_75_minutes_as_two_days():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "75 minutes" in src
    assert "NOT two days" in src


def test_dry_run_returns_zero_and_writes_nothing(capsys):
    before = sorted(p.name for p in (ROOT / "results" / "phase1").glob("*.json"))
    assert f92.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "no AWS call" in out
    for metric in f92.REQUIRED:
        assert metric in out
    after = sorted(p.name for p in (ROOT / "results" / "phase1").glob("*.json"))
    assert before == after


# --------------------------------------------------------------------------- 6. real evidence

def test_the_real_evidence_yields_two_episodes_for_each_named_metric():
    """The happy path against the archive, skipping loudly rather than passing vacuously."""
    if not (ROOT / "evidence" / f92.SOURCE_RUN).joinpath(*f92.SOURCE_CASE_DIR).is_dir():
        pytest.skip("F5-4a's evidence is absent in this checkout (evidence/ is local-only)")
    b = f92.build()
    assert b["decision"]["observed"] is True
    for metric in f92.REQUIRED:
        row = b["decision"]["per_metric"][metric]
        assert row["n_episodes"] == 2, (metric, row["n_episodes"])
        for ep in row["episodes"]:
            assert ep["n_baseline_reads"] > 0
            # 20 per episode, which is F5-4a's n_per_arm: every request against the twin that
            # could not evaluate is counted once. Pinned rather than asserted as `> 0`, because
            # a double-counted re-read would also be `> 0`.
            assert ep["sum"] == 20.0, (metric, ep["t"], ep["sum"])
            assert ep["samples"] == 20.0, (metric, ep["t"], ep["samples"])
    assert b["basis"]["mcp_tools_call"] >= 200


def test_the_real_episodes_straddle_the_utc_day_boundary():
    """What "two days" means here, read off the datapoints rather than asserted in prose."""
    if not (ROOT / "evidence" / f92.SOURCE_RUN).joinpath(*f92.SOURCE_CASE_DIR).is_dir():
        pytest.skip("F5-4a's evidence is absent in this checkout")
    eps = f92.build()["decision"]["per_metric"][f92.REQUIRED[0]]["episodes"]
    days = {datetime.fromisoformat(e["t_utc"]).astimezone(timezone.utc).date() for e in eps}
    assert len(days) == 2, f"both episodes fall on one UTC day: {days}"
    gap = abs(datetime.fromisoformat(eps[1]["t_utc"])
              - datetime.fromisoformat(eps[0]["t_utc"])).total_seconds()
    assert 3600 < gap < 3 * 3600, (
        f"{gap}s between the episodes; FINDING-F5-4A.md §8 and this script's replication note "
        f"both describe roughly 75 minutes, and a different gap means one of them is stale")
