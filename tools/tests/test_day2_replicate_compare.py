#!/usr/bin/env python3
"""An agreeing verdict is not a replication on its own — the decision record is compared too.

Why this file exists
--------------------
`tools/day2_replicate.py` originally reported AGREE on verdict equality alone. F3-4's day 2
agreed on FALSE, and the part worth publishing was underneath it: the same 9 of 31 entity strata
refuted, with identical success counts in 31 of 31 strata. That was established by hand, so the
next case would not have got it, and a day 2 whose verdict agreed while its counts moved would
have printed exactly the same word.

Two behaviours are pinned here:

* `record_diff` reports every path at which two sealed decision records differ, and — the arm that
  matters — reports nothing when they are equal, since a differ-always function would make the
  driver's new output meaningless while looking informative;
* a difference in a **sealed** field (`kind`, `thresholds`, `planned_n`) is an error rather than a
  note, because those come from `PREREGISTRATION.yaml` and not from the observation. Two days that
  disagree there did not run the same test, and their matching verdict is a coincidence.

The third function tested is `evidence_date`, the narrow fallback that lets a case whose day-1
`run_id` is not a dated string (F8-5 and F8-8 carry `smoke20260810T0305Z`) be replicated anyway,
by reading the day off the observation records themselves.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SUBJECT_MODULE_NAME = "_compare_day2_replicate"


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


# ------------------------------------------------------------------ record_diff

def test_identical_records_report_no_difference(mod):
    """The anti-vacuous arm: silence has to be possible, or every AGREE reads as drift."""
    rec = {"kind": "LOWER_ABOVE", "n_attempted": 341, "thresholds": [0.5],
           "evidence": {"n": 341, "per_stratum": [{"e": "ssn", "x": 11}, {"e": "pwd", "x": 0}]}}
    assert mod.record_diff(rec, json.loads(json.dumps(rec))) == []


def test_a_moved_success_count_is_reported_with_its_path(mod):
    """The case the whole function exists for: same verdict, one stratum's count moved."""
    a = {"evidence": {"per_stratum": [{"e": "ssn", "x": 11}, {"e": "pwd", "x": 0}]}}
    b = {"evidence": {"per_stratum": [{"e": "ssn", "x": 11}, {"e": "pwd", "x": 3}]}}
    diffs = mod.record_diff(a, b)
    assert diffs == ["evidence.per_stratum[1].x: 0 -> 3"], diffs


def test_added_and_removed_keys_are_both_named(mod):
    """A stratum that vanished on day 2 must not compare equal to one that was never there."""
    diffs = mod.record_diff({"a": 1, "gone": 2}, {"a": 1, "new": 3})
    assert diffs == ["gone (absent day 2)", "new (absent day 1)"], diffs


def test_a_shorter_list_is_reported_as_a_length_change_not_element_wise(mod):
    """31 strata becoming 30 is one fact, not thirty; zip() would hide the missing tail.

    `feedback_codegen_ate_the_tail` in comparison form — pairing element-wise over a truncated
    list silently drops everything past the shorter length, so the one difference that matters
    (a stratum is missing) would be the one difference not printed.
    """
    diffs = mod.record_diff({"s": [1, 2, 3]}, {"s": [1, 2]})
    assert diffs == ["s (length 3 -> 2)"], diffs


def test_it_matches_the_real_archived_day1_records(mod):
    """Run against every real day-1 archive file, not fixtures.

    22 of the 23 archived records compared identical to their live counterpart when this was
    written, and the one that drifted (F5-4a) drifted only at CloudWatch metric window bounds.
    The assertion is deliberately loose — new replications will add files — but it pins the two
    properties that make the driver's output trustworthy: the comparison is quiet on real
    unchanged records, and no archived case has a sealed field that moved.
    """
    archive = REPO / "results" / "phase1" / "archive"
    files = sorted(archive.glob("*__day1_*.json"))
    assert len(files) >= 17, f"only {len(files)} archived day-1 files; this arm needs real ones"

    identical, sealed_moved = 0, {}
    for a in files:
        case = a.name.split("__day1_")[0]
        live = REPO / "results" / "phase1" / f"{case}.json"
        if not live.is_file():
            continue
        d = mod.record_diff(mod.record_of(a.read_bytes()), mod.record_of(live.read_bytes()))
        if not d:
            identical += 1
        broke = sorted({p.split(".")[0].split("[")[0].split(" ")[0]
                        for p in d} & set(mod.SEALED_FIELDS))
        if broke:
            sealed_moved[case] = broke

    assert not sealed_moved, (
        f"a sealed field moved between day 1 and the live verdict: {sealed_moved}. Either a "
        f"replication ran a different test, or the seal changed under a published verdict.")
    assert identical >= 15, (
        f"only {identical}/{len(files)} archived records match their live file. Either many "
        f"replications drifted, or record_diff has started reporting spurious differences — "
        f"check the paths before assuming the first.")


# ------------------------------------------------------------------- payload_diff
#
# F8-4 forced this one. Its day 2 agreed on FALSE with a decision record identical at every path —
# and its `record.evidence` is two booleans and a proxy string, while the counts the document cites
# live in `tier_proxy` and `checks_arms`. Those had moved.

def _f(**kw) -> bytes:
    return json.dumps(kw).encode()


def test_a_moved_count_outside_the_record_is_quantitative(mod):
    a = _f(record={"verdict": "FALSE"}, tier_proxy={"standard": {"recall": {"x": 119, "n": 120}}})
    b = _f(record={"verdict": "FALSE"}, tier_proxy={"standard": {"recall": {"x": 118, "n": 120}}})
    quant, vol = mod.payload_diff(a, b)
    assert quant == ["tier_proxy.standard.recall.x: 119 -> 118"], quant
    assert vol == []


def test_identifiers_and_clocks_are_run_scoped_not_drift(mod):
    """The anti-noise arm. Without the split every case reports drift and the word means nothing."""
    a = _f(run_id="r1", probes=[{"request_id": "aaa", "guardrail_id": "g1", "length": 1000}])
    b = _f(run_id="r2", probes=[{"request_id": "bbb", "guardrail_id": "g2", "length": 1000}])
    quant, vol = mod.payload_diff(a, b, ("r1", "r2"))
    assert quant == [], quant
    assert len(vol) == 3, vol


def test_a_volatile_parent_key_covers_its_children(mod):
    """F10-3 files request ids under `request_ids.tagged`, whose LEAF is `tagged`.

    A leaf-only classifier reported ten freshly-minted uuids as quantitative drift. Every path
    segment is therefore checked — while a sibling count under a non-volatile parent must still
    come through, or the fix would suppress the signal along with the noise.
    """
    a = _f(reconciliation={"pairs": [{"request_ids": {"tagged": "aaa", "untagged": "bbb"},
                                      "units": {"tagged": 7}}]})
    b = _f(reconciliation={"pairs": [{"request_ids": {"tagged": "ccc", "untagged": "ddd"},
                                      "units": {"tagged": 9}}]})
    quant, vol = mod.payload_diff(a, b)
    assert quant == ["reconciliation.pairs[0].units.tagged: 7 -> 9"], quant
    assert len(vol) == 2, vol


def test_a_value_containing_either_run_id_is_run_scoped(mod):
    """Catches the paths `VOLATILE_KEYS` cannot name, e.g. a prose note that cites its own run."""
    a = _f(note="see evidence/r20260810T130945Z/f8/F8-5")
    b = _f(note="see evidence/r20260815T092557Z/f8/F8-5")
    quant, vol = mod.payload_diff(a, b, ("r20260810T130945Z", "r20260815T092557Z"))
    assert (quant, len(vol)) == ([], 1), (quant, vol)


def test_the_record_block_is_excluded_because_record_diff_owns_it(mod):
    """Otherwise every record difference is reported twice, in two different vocabularies."""
    a = _f(record={"n_met": 3}, x=1)
    b = _f(record={"n_met": 9}, x=1)
    assert mod.payload_diff(a, b) == ([], [])


def test_it_finds_the_real_F8_4_drift_the_record_could_not_see(mod):
    """The artifact this function was written for, both halves asserted.

    F8-4, 2026-08-10 vs 2026-08-15: `record_diff` reports nothing, and `payload_diff` reports the
    STANDARD recall moving by one item and the `InvokeGuardrailChecks` threshold sweep moving at
    three thresholds. CLASSIC — the tier the FALSE verdict actually turns on — must NOT appear:
    it reproduced exactly, and a function that flagged it too would be reporting noise.
    """
    a = REPO / "results" / "phase1" / "archive" / "F8-4__day1_2026-08-10.json"
    live = REPO / "results" / "phase1" / "F8-4.json"
    if not a.is_file():
        pytest.skip("F8-4 has not been replicated in this checkout")
    old, new = a.read_bytes(), live.read_bytes()

    assert mod.record_diff(mod.record_of(old), mod.record_of(new)) == [], (
        "F8-4's decision record now differs; this arm's premise was that it does not")
    quant, vol = mod.payload_diff(old, new, (mod.run_id_of(old), mod.run_id_of(new)))
    assert quant, "the drift outside `record` vanished — re-derive before relaxing this"
    assert any(p.startswith("tier_proxy.standard.recall.x") for p in quant), quant
    assert any(p.startswith("checks_arms.threshold_sweep") for p in quant), quant
    assert not [p for p in quant if p.startswith("tier_proxy.classic")], (
        f"CLASSIC's counts are being reported as drift; the verdict-bearing tier reproduced "
        f"exactly on 2026-08-15 (49/120 recall, 4/110 FPR): {quant}")
    assert "run_id" in " ".join(vol), "the run id must be classified run-scoped, not quantitative"


def test_no_archived_case_reports_drift_in_a_sealed_or_oracle_field(mod):
    """Swept over every replicated pair: the seal and the oracle text must never move.

    `payload_diff` reports notes rather than errors, so this arm is where a payload difference
    that WOULD be an error gets caught — a changed `oracle_text`, `kind` or `planned_h` means the
    two days did not evaluate the same question, whatever their verdicts said.
    """
    archive = REPO / "results" / "phase1" / "archive"
    checked = 0
    for a in sorted(archive.glob("*__day1_*.json")):
        live = REPO / "results" / "phase1" / f"{a.name.split('__day1_')[0]}.json"
        if not live.is_file():
            continue
        checked += 1
        quant, _ = mod.payload_diff(a.read_bytes(), live.read_bytes(),
                                   (mod.run_id_of(a.read_bytes()), mod.run_id_of(live.read_bytes())))
        bad = [p for p in quant
               if p.split(":")[0].split(" ")[0].split("[")[0].split(".")[0]
               in ("kind", "oracle_text", "planned_n", "thresholds", "case_id", "operationalisation")]
        assert not bad, f"{a.name}: a sealed/oracle field moved between the two days: {bad}"
    assert checked >= 17, f"only {checked} pairs available; this sweep needs the real archive"


# ------------------------------------------------------------------ evidence_date

def test_evidence_date_reads_the_day_off_the_call_records(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    d = tmp_path / "smokeXXXX" / "f8" / "F8-5"
    d.mkdir(parents=True)
    (d / "0001_create_guardrail_ok.json").write_text(
        json.dumps({"t_start_utc": "2026-08-10T02:45:52.1Z"}))
    (d / "summary.json").write_text(json.dumps({"captured_utc": "2026-08-11T00:00:00Z"}))

    date, src = mod.evidence_date("F8-5", "smokeXXXX")
    assert date == "2026-08-10"
    assert "t_start_utc" in src, (
        f"source was {src!r}; a summary's captured_utc is written on every run, so it must not "
        "be preferred over a call record — here it would have given the wrong DAY")


def test_summary_is_used_only_when_no_call_record_exists_and_is_labelled_weaker(mod, tmp_path,
                                                                               monkeypatch):
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    d = tmp_path / "smokeXXXX" / "f8" / "F8-8"
    d.mkdir(parents=True)
    (d / "summary.json").write_text(json.dumps({"captured_utc": "2026-08-10T02:46:07Z"}))

    date, src = mod.evidence_date("F8-8", "smokeXXXX")
    assert date == "2026-08-10"
    assert "weaker" in src, f"the summary source must announce that it is the weaker one: {src!r}"


def test_records_spanning_two_utc_days_are_refused(mod, tmp_path, monkeypatch):
    """"Day 1" has to be one day. A run that straddled midnight is refused, not averaged."""
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    d = tmp_path / "smokeXXXX" / "f8" / "F8-5"
    d.mkdir(parents=True)
    (d / "0001_x.json").write_text(json.dumps({"t_start_utc": "2026-08-10T23:59:59Z"}))
    (d / "0002_x.json").write_text(json.dumps({"t_start_utc": "2026-08-11T00:00:01Z"}))

    date, why = mod.evidence_date("F8-5", "smokeXXXX")
    assert date is None and "more than one UTC day" in why


def test_another_cases_records_do_not_supply_this_cases_day(mod, tmp_path, monkeypatch):
    """Scoped to the case, or the busiest run in the tree would date every case in it.

    `F8-4-classic-benign` counts as F8-4 (a stratum directory), while F8-5's records must not
    date F8-4. Without the prefix rule the fallback would answer for cases that were never run.
    """
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    root = tmp_path / "smokeXXXX" / "f8"
    (root / "F8-5").mkdir(parents=True)
    (root / "F8-5" / "0001_x.json").write_text(json.dumps({"t_start_utc": "2026-08-10T02:00:00Z"}))
    (root / "F8-4-classic-benign").mkdir(parents=True)
    (root / "F8-4-classic-benign" / "0001_x.json").write_text(
        json.dumps({"t_start_utc": "2026-08-09T02:00:00Z"}))

    assert mod.evidence_date("F8-4", "smokeXXXX")[0] == "2026-08-09", "stratum dir not credited"
    assert mod.evidence_date("F8-5", "smokeXXXX")[0] == "2026-08-10", "wrong case's day used"
    assert mod.evidence_date("F8-9", "smokeXXXX")[0] is None, "a case that never ran got a day"


def test_a_missing_evidence_directory_yields_no_date(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    date, why = mod.evidence_date("F8-5", "neverran")
    assert date is None and "does not exist" in why


# ------------------------------------------------------------- transient_failures
#
# The guard F8-5 forced. Day 2 agreed on FALSE, `record_diff` said the decision record was
# IDENTICAL, and no sealed field moved — while the probe carrying the refutation
# (`standard-1000`, the one whose acceptance the claim is about) had come back
# ThrottlingException. Verdict-level and record-level agreement cannot see that, because
# `record.evidence` is three booleans that do not distinguish "the service rejected this
# content" from "the service rejected this request".

def test_a_throttled_call_is_reported(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    d = tmp_path / "r1" / "f8" / "F8-5"
    d.mkdir(parents=True)
    (d / "0001_x.json").write_text(json.dumps(
        {"t_start_utc": "2026-08-15T09:25:00Z", "error_code": "ThrottlingException"}))

    got = mod.transient_failures("r1", "2026-08-15", "F8-5")
    assert [c for _, c in got] == ["ThrottlingException"], got
    assert got[0][0].endswith("r1/f8/F8-5/0001_x.json"), got


def test_a_validation_error_is_not_transient(mod, tmp_path, monkeypatch):
    """The anti-vacuous arm, and the whole point of the distinction.

    A ValidationException IS the observation for a boundary case — F8-5's `classic-201` probe is
    *supposed* to be rejected that way. A guard that flagged every error would caveat every
    boundary case, which is indistinguishable from having no guard.
    """
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    d = tmp_path / "r1" / "f8" / "F8-5"
    d.mkdir(parents=True)
    (d / "0001_x.json").write_text(json.dumps(
        {"t_start_utc": "2026-08-15T09:25:00Z", "error_code": "ValidationException"}))
    (d / "0002_x.json").write_text(json.dumps({"t_start_utc": "2026-08-15T09:25:01Z"}))

    assert mod.transient_failures("r1", "2026-08-15", "F8-5") == []


def test_only_todays_calls_and_only_this_case_are_reported(mod, tmp_path, monkeypatch):
    """Scoped like the observation proof: a throttle from day 1 is not day 2's caveat.

    Without the day filter, F8-5 would be caveated forever on the strength of day 1's throttle;
    without the case filter, one throttled call anywhere in a shared run id would caveat every
    case in it.
    """
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    for case, day in (("F8-5", "2026-08-14"), ("F8-8", "2026-08-15")):
        d = tmp_path / "r1" / "f8" / case
        d.mkdir(parents=True)
        (d / "0001_x.json").write_text(json.dumps(
            {"t_start_utc": f"{day}T09:25:00Z", "error_code": "ThrottlingException"}))

    assert mod.transient_failures("r1", "2026-08-15", "F8-5") == []
    assert len(mod.transient_failures("r1", "2026-08-15", "F8-8")) == 1
    assert len(mod.transient_failures("r1", "2026-08-15")) == 1, "unscoped call must see F8-8's"


def test_the_code_is_read_from_botocores_own_copy_too(mod, tmp_path, monkeypatch):
    """A producer that fills only `error_metadata` must not read as clean.

    `feedback_guard_tool_exit_codes` in field form: a check that looks at one of three places a
    value can live reports PASS when it simply failed to look.
    """
    monkeypatch.setattr(mod, "EVIDENCE", tmp_path)
    d = tmp_path / "r1" / "f8" / "F8-5"
    d.mkdir(parents=True)
    (d / "0001_x.json").write_text(json.dumps(
        {"t_start_utc": "2026-08-15T09:25:00Z",
         "error_metadata": {"Error": {"Code": "ServiceUnavailableException"}}}))

    got = mod.transient_failures("r1", "2026-08-15", "F8-5")
    assert [c for _, c in got] == ["ServiceUnavailableException"], got
    assert got[0][0].endswith("r1/f8/F8-5/0001_x.json"), got


def test_it_finds_the_real_throttled_probe_on_both_of_F8_5s_observation_days(mod):
    """Read from the real evidence trees, because this guard was written after the fact.

    Both of F8-5's observation days contain exactly one throttled `CreateGuardrail`, and they
    are DIFFERENT probes: 2026-08-10 threw it on `standard-1001` (expected "rejected", so the
    producer scored the throttle as a match and the confirming half was unwarranted), and
    2026-08-15 threw it on `standard-1000` (expected "accepted", so the throttle became the
    refutation the FALSE verdict rests on). Also asserts that today's other three replications
    are clean — a guard that fires on every run would tell an operator nothing.
    """
    if not (REPO / "evidence" / "smoke20260810T0305Z").is_dir():
        pytest.skip("evidence/ is local-only; nothing to read on this machine")

    d1 = mod.transient_failures("smoke20260810T0305Z", "2026-08-10", "F8-5")
    assert [c for _, c in d1] == ["ThrottlingException"], d1
    assert d1[0][0].endswith("0004_create_guardrail_err.json"), d1

    if (REPO / "evidence" / "r20260815T092557Z").is_dir():
        d2 = mod.transient_failures("r20260815T092557Z", "2026-08-15", "F8-5")
        assert [c for _, c in d2] == ["ThrottlingException"], d2
        assert d2[0][0].endswith("0003_create_guardrail_err.json"), (
            f"the throttle moved off probe 3; the day-2 caveat's basis changed: {d2}")
        for clean in ("r20260815T082524Z", "r20260815T084022Z", "r20260815T092538Z"):
            if (REPO / "evidence" / clean).is_dir():
                assert mod.transient_failures(clean, "2026-08-15") == [], (
                    f"{clean} now reports transient failures; if that is real the replication "
                    f"it backs needs a caveat, and if not the guard has become noisy")


# ------------------------------------------------------------------- day1_label

def test_day1_label_prefers_the_resolved_date_over_the_run_id(mod):
    raw = json.dumps({"run_id": "smoke20260810T0305Z"}).encode()
    assert mod.day1_label("F8-5", raw, {"F8-5": "2026-08-10"}) == "2026-08-10"
    assert mod.day1_label("F8-5", raw, {}) == "unknown", "undateable run id must stay honest"
    dated = json.dumps({"run_id": "r20260810T130945Z"}).encode()
    assert mod.day1_label("F1-14", dated, None) == "2026-08-10", "run-id fallback broke"
    assert mod.day1_label("F1-14", dated, {"F1-14": "2026-08-09"}) == "2026-08-09", (
        "a resolved date must win even when the run id is parseable, or the two sources can "
        "disagree and the archive filename silently picks the other one")


def test_the_real_smoke_run_dates_F8_5_to_the_day_its_probes_ran(mod):
    """The artifact this fallback was written for, read from the real evidence tree.

    F8-5's published verdict cites run id `smoke20260810T0305Z`, which `lib.evidence.RUN_ID_RE`
    does not match. Its five call records are stamped 2026-08-10T02:45Z — note that they also
    disagree with the 03:05 in the run id, which is the reason the record and not the filename
    is the source. Skips rather than fails if the local evidence tree is absent: `evidence/` is
    local-only by policy, so a checkout will not have it.
    """
    if not (REPO / "evidence" / "smoke20260810T0305Z").is_dir():
        pytest.skip("evidence/ is local-only; nothing to read on this machine")
    date, src = mod.evidence_date("F8-5", "smoke20260810T0305Z")
    assert (date, "t_start_utc" in src) == ("2026-08-10", True)
    assert mod.run_id_date("smoke20260810T0305Z") is None, (
        "RUN_ID_RE now matches the smoke run id, so this fallback is no longer the thing that "
        "unblocks F8-5 — re-derive whether it is still needed")
