"""Mutation tests for check_amendment_readiness.py — the 2-separate-days gate.

A gate is only worth its green light if the failures it names can actually happen. The
central arm here is `test_kills_a_single_day_amendment`: it writes the status I would
have written had I forgotten the sealed rule -- which is exactly what happened, since
the rule sat in PREREGISTRATION.yaml enforced by nothing while 8 gates passed.

Per feedback_vacuous_test_check, each arm asserts on the *reason* in stderr, not merely
on a non-zero exit: a mutant killed via the wrong branch is not a tested mutant. The
corpus-gate suite already produced one of those (suppressing writes crashed the builder,
so the empty-tree guard was never reached), so the needle check is not hypothetical.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from evidence_subset import BLOCK_RE, GATE, ROOT, copy_evidence_subset


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of the repo the mutants may edit freely.

    The gate itself, the sealed pre-registration, the findings, and the SUBSET of
    `evidence/` the gate's result can depend on — see `evidence_subset.py` for what that
    is and why it is derived from the findings rather than listed here.

    This fixture used to copy `evidence/` whole, 198,452 KB in 28,716 files, once per arm:
    about 4.9 GB per run, and its docstring claimed "only what the gate reads is copied"
    while taking the largest tree in the repo. That is DEV-P4-36's defect at a second site.
    Now 25,577 KB in 4,600 files, ~0.65 GB per run, bounded by
    `test_amendment_evidence_subset.py` above and below.
    """
    dst = tmp_path / "repo"
    (dst / "results").mkdir(parents=True)
    shutil.copy2(GATE, dst / GATE.name)
    shutil.copy2(ROOT / "PREREGISTRATION.yaml", dst / "PREREGISTRATION.yaml")
    for f in (ROOT / "results").glob("FINDING-*.md"):
        shutil.copy2(f, dst / "results" / f.name)
    copy_evidence_subset(dst)
    return dst


def run(tree: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(tree / GATE.name)],
                          capture_output=True, text=True, cwd=tree)


def read_meta(f: Path) -> dict:
    m = BLOCK_RE.search(f.read_text(encoding="utf-8"))
    assert m, f"{f.name} has no provenance block"
    return json.loads(m.group(1))


# Day 1 of F5-7a, named here because most arms below need a finding that rests on ONE
# day. F5-7A itself no longer does — it was replicated on 2026-08-10 and promoted to
# READY_TO_AMEND — and that is precisely why the arms must set the run list explicitly.
# Written as `meta["evidence_runs"] = [DAY1]` rather than left implicit, because an arm
# that gets its single-day-ness from whatever the real finding happens to declare stops
# testing the gate the moment the finding is replicated: three of the arms here were
# passing only because F5-7A had one run, and would have gone green against a gate that
# had stopped counting days at all.
DAY1 = "r20260809T094500Z"
# Read from the verdict file rather than typed: two day-2 runs exist (a scheduled one and
# a manual one that raced it, DEV-SEAL-13) and the canonical one is the scheduled run.
# test_behavior_changes.py owns the cross-artifact agreement check; here DAY2 only needs to
# be whichever run the finding actually declares, or the control arm below tests nothing.
DAY2 = json.loads((ROOT / "results" / "f5_7a_replication.json")
                  .read_text(encoding="utf-8"))["day2"]


def single_day(f: Path, **over) -> dict:
    """Rewrite a finding's provenance to rest on day 1 alone, plus any overrides."""
    meta = read_meta(f)
    meta["evidence_runs"] = [DAY1]
    meta.pop("blocked_on", None)
    meta.pop("was_blocked_on", None)
    meta.update(over)
    write_meta(f, meta)
    return meta


def write_meta(f: Path, meta: dict) -> None:
    text = f.read_text(encoding="utf-8")
    new = "<!-- provenance\n" + json.dumps(meta, indent=2) + "\n-->"
    f.write_text(BLOCK_RE.sub(lambda _m: new, text, count=1), encoding="utf-8")


def kills(res: subprocess.CompletedProcess, needle: str, rc: int = 1) -> None:
    """Assert the mutant died, and died for the stated reason."""
    assert res.returncode == rc, (
        f"expected rc={rc}, got {res.returncode}\nstdout:\n{res.stdout}\n"
        f"stderr:\n{res.stderr}")
    assert needle in res.stderr, (
        f"killed, but not by the intended check — {needle!r} absent from:\n{res.stderr}")


# --------------------------------------------------------------------------- controls

def test_control_arm_the_unmutated_tree_passes(tree: Path) -> None:
    res = run(tree)
    assert res.returncode == 0, f"clean tree must pass:\n{res.stderr}"
    assert "OK —" in res.stdout


def test_control_arm_every_finding_is_actually_read(tree: Path) -> None:
    """A gate that silently skipped a finding would still print OK.

    Pins the count in the summary against the files on disk, so a `continue` added in
    the wrong place cannot shrink the scan unnoticed.
    """
    res = run(tree)
    n = len(list((tree / "results").glob("FINDING-*.md")))
    assert f"over {n} findings" in res.stdout, res.stdout
    for f in (tree / "results").glob("FINDING-*.md"):
        assert f.name in res.stdout, f"{f.name} never appeared in the summary"


# ------------------------------------------------------- the arm this file exists for

def test_kills_a_single_day_amendment(tree: Path) -> None:
    """THE central arm: READY_TO_AMEND on one day's evidence.

    This is the exact text I would have written had I relied on memory. Before this
    gate existed, nothing in 358 tests and 8 gates would have objected.

    F5-7A is now legitimately two-day, so the mutation is to strip it back to day 1 and
    keep the amendment status — which is the state the rule forbids, whether it arises by
    forgetting to run day 2 or by promoting before it finished.
    """
    f = tree / "results" / "FINDING-F5-7A.md"
    single_day(f, status="READY_TO_AMEND")
    res = run(tree)
    kills(res, "spans 1 calendar day(s)")
    assert "do not relax the status" in res.stderr


def test_control_arm_the_real_finding_is_two_day_and_passes_as_amendable(tree: Path) -> None:
    """The complement of the arm above, on the artifact as it actually stands.

    Without this, every arm here could be satisfied by a gate that refuses ALL
    amendments — and the mutations above deliberately manufacture single-day states, so
    none of them would notice. This pins that F5-7A's real, unmutated provenance
    (2026-08-09 + 2026-08-10) is what lets READY_TO_AMEND through.
    """
    f = tree / "results" / "FINDING-F5-7A.md"
    meta = read_meta(f)
    assert meta["status"] == "READY_TO_AMEND", (
        f"this arm describes the finding's real state; it now reads {meta['status']!r}")
    assert sorted(meta["evidence_runs"]) == sorted([DAY1, DAY2])
    res = run(tree)
    assert res.returncode == 0, res.stderr
    assert "READY_TO_AMEND" in res.stdout
    assert "2 day(s) ['2026-08-09', '2026-08-10']" in res.stdout, res.stdout


def test_a_second_day_of_evidence_lifts_the_block(tree: Path) -> None:
    """The complement: with two days of records the same status passes.

    Without this the suite would prove only that the gate says no. A gate that can
    never say yes is not a gate, it is a wall -- and the reason task #3 is deferred
    rather than abandoned is that the block is liftable by evidence.
    """
    f = tree / "results" / "FINDING-F5-7A.md"
    single_day(f, status="READY_TO_AMEND",
               evidence_runs=[DAY1, "r20260810T090000Z"])

    # A synthetic day-2 run, shaped like a real record: the gate reads t_start_utc. Kept
    # synthetic even though a real day-2 run now exists, so the arm still measures "a
    # second day of records lifts the block" rather than "the tree happens to contain
    # one" — the two stop being distinguishable if this reuses r20260810T001115Z.
    src = next((tree / "evidence" / DAY1).rglob("0001_*.json"))
    dst = tree / "evidence" / "r20260810T090000Z" / "f5" / "F5-7A"
    dst.mkdir(parents=True)
    rec = json.loads(src.read_text(encoding="utf-8"))
    rec["t_start_utc"] = "2026-08-10T09:00:00.000000+00:00"
    (dst / "0001_replication.json").write_text(json.dumps(rec), encoding="utf-8")

    res = run(tree)
    assert res.returncode == 0, f"two days of evidence must satisfy the rule:\n{res.stderr}"
    assert "2 day(s)" in res.stdout


def test_two_runs_on_the_same_day_do_not_count_as_replication(tree: Path) -> None:
    """Running the script twice on one day must not satisfy the rule.

    The cheapest way to fake replication is a second run_id, since the id is minted
    per invocation. The gate counts distinct *calendar days* from the records, so a
    same-day rerun changes nothing -- which is the whole point: a transient
    publication state or a cached CDN variant would survive both reads.
    """
    f = tree / "results" / "FINDING-F5-7A.md"
    single_day(f, status="READY_TO_AMEND",
               evidence_runs=[DAY1, "r20260809T230000Z"])

    src = next((tree / "evidence" / DAY1).rglob("0001_*.json"))
    dst = tree / "evidence" / "r20260809T230000Z" / "f5" / "F5-7A"
    dst.mkdir(parents=True)
    rec = json.loads(src.read_text(encoding="utf-8"))
    rec["t_start_utc"] = "2026-08-09T23:00:00.000000+00:00"   # later, same UTC day
    (dst / "0001_rerun.json").write_text(json.dumps(rec), encoding="utf-8")

    res = run(tree)
    kills(res, "spans 1 calendar day(s)")


def test_the_run_id_is_not_trusted_for_the_date(tree: Path) -> None:
    """A run_id spelling a second day cannot substitute for records on that day.

    `r20260810T…` looks like day 2 to a human and to any check that parses ids. The
    dates must come from t_start_utc, or the gate is reading a number out of a string
    -- the defect this project screens the document for.
    """
    f = tree / "results" / "FINDING-F5-7A.md"
    single_day(f, status="READY_TO_AMEND",
               evidence_runs=[DAY1, "r20260810T090000Z"])

    src = next((tree / "evidence" / DAY1).rglob("0001_*.json"))
    dst = tree / "evidence" / "r20260810T090000Z" / "f5" / "F5-7A"
    dst.mkdir(parents=True)
    rec = json.loads(src.read_text(encoding="utf-8"))          # t_start_utc left on 08-09
    (dst / "0001_mislabelled.json").write_text(json.dumps(rec), encoding="utf-8")

    res = run(tree)
    kills(res, "spans 1 calendar day(s)")


def test_kills_an_amendment_resting_on_no_evidence_at_all(tree: Path) -> None:
    f = tree / "results" / "FINDING-F1-1.md"
    meta = read_meta(f)
    meta["status"] = "AMENDED"
    write_meta(f, meta)
    kills(run(tree), "with NO evidence runs")


def test_kills_a_declared_run_that_is_not_on_disk(tree: Path) -> None:
    f = tree / "results" / "FINDING-F5-7A.md"
    meta = read_meta(f)
    meta["evidence_runs"] = ["r20260810T090000Z"]
    write_meta(f, meta)
    kills(run(tree), "which is not under evidence/")


def test_kills_an_empty_evidence_directory(tree: Path) -> None:
    """A run directory with no records must not read as "no dates, therefore fine"."""
    f = tree / "results" / "FINDING-F5-7A.md"
    meta = read_meta(f)
    meta["evidence_runs"] = ["r20260810T090000Z"]
    write_meta(f, meta)
    (tree / "evidence" / "r20260810T090000Z").mkdir()
    kills(run(tree), "holds no evidence records")


def test_kills_a_deferral_with_no_stated_condition(tree: Path) -> None:
    """OBSERVATIONS_COMPLETE without blocked_on is indistinguishable from forgetting.

    F5-7A carries `was_blocked_on` now, past tense, because its block was discharged. That
    rename is what this arm tests the other side of: rolling the status back to a deferred
    one while leaving only the past-tense key must fail, or a finding could sit in
    OBSERVATIONS_COMPLETE forever with nothing stating what it waits for and a key that
    merely *looks* like the required one.
    """
    f = tree / "results" / "FINDING-F5-7A.md"
    meta = read_meta(f)
    meta["status"] = "OBSERVATIONS_COMPLETE"
    meta.pop("blocked_on", None)
    assert "was_blocked_on" in meta, (
        "this arm relies on the past-tense key being present but not counted")
    write_meta(f, meta)
    kills(run(tree), "no `blocked_on`")


def test_kills_a_missing_provenance_block(tree: Path) -> None:
    f = tree / "results" / "FINDING-P0-STATS.md"
    text = f.read_text(encoding="utf-8")
    f.write_text(BLOCK_RE.sub("", text, count=1), encoding="utf-8")
    kills(run(tree), "no `<!-- provenance ... -->` block")


def test_kills_an_unparseable_provenance_block(tree: Path) -> None:
    f = tree / "results" / "FINDING-P0-STATS.md"
    text = f.read_text(encoding="utf-8")
    f.write_text(BLOCK_RE.sub("<!-- provenance\n{not json,}\n-->", text, count=1),
                 encoding="utf-8")
    kills(run(tree), "not valid JSON")


def test_kills_an_invented_status(tree: Path) -> None:
    """A status outside the vocabulary must fail, not be treated as harmless.

    Otherwise "PARTIALLY_AMENDED" would sail through: unrecognised, therefore never
    matched against AMENDMENT_STATUSES, therefore never checked for replication.
    """
    f = tree / "results" / "FINDING-F5-7A.md"
    meta = read_meta(f)
    meta["status"] = "PARTIALLY_AMENDED"
    write_meta(f, meta)
    kills(run(tree), "is not one of")


def test_kills_evidence_runs_given_as_a_bare_string(tree: Path) -> None:
    """`"evidence_runs": "r2026…"` would otherwise iterate character by character."""
    f = tree / "results" / "FINDING-F5-7A.md"
    meta = read_meta(f)
    meta["evidence_runs"] = "r20260809T094500Z"
    write_meta(f, meta)
    kills(run(tree), "must be a list")


# ------------------------------------------------- the gate must enforce a SEALED rule

def test_kills_a_relaxed_seal(tree: Path) -> None:
    """Editing the pre-registration down to 1 day must break the gate, not license it.

    The failure direction matters: loosening the sealed rule makes the gate report a
    disagreement, so the only way to lift a block is evidence.
    """
    p = tree / "PREREGISTRATION.yaml"
    p.write_text(p.read_text(encoding="utf-8")
                 .replace(">= 2 separate calendar days", ">= 1 separate calendar days"),
                 encoding="utf-8")
    kills(run(tree), "requires >= 1 calendar days but")


def test_kills_a_deleted_rule(tree: Path) -> None:
    """If the sealed rule is gone the gate is enforcing something unregistered."""
    p = tree / "PREREGISTRATION.yaml"
    p.write_text(p.read_text(encoding="utf-8")
                 .replace("reproduction_before_amendment:",
                          "reproduction_before_amendment_DISABLED:"),
                 encoding="utf-8")
    kills(run(tree), "no longer carries")


def test_kills_a_rule_whose_wording_no_longer_states_the_threshold(tree: Path) -> None:
    p = tree / "PREREGISTRATION.yaml"
    p.write_text(p.read_text(encoding="utf-8")
                 .replace(">= 2 separate calendar days", "on more than one occasion"),
                 encoding="utf-8")
    kills(run(tree), "no longer states")


# ------------------------------------------------------- absence must not read as pass

def test_a_missing_prereg_is_rc2_not_a_pass(tree: Path) -> None:
    (tree / "PREREGISTRATION.yaml").unlink()
    kills(run(tree), "cannot be confirmed", rc=2)


def test_a_missing_results_dir_is_rc2_not_a_pass(tree: Path) -> None:
    shutil.rmtree(tree / "results")
    kills(run(tree), "which is not\nthe same as passing".replace("\n", " "), rc=2)


def test_an_almost_empty_results_dir_does_not_report_clean(tree: Path) -> None:
    """Deleting findings must not make the gate greener.

    feedback_zero_file_scan_is_error: a scan that reads almost nothing and prints OK
    is worse than no scan, because it certifies.
    """
    for f in sorted((tree / "results").glob("FINDING-*.md"))[1:]:
        f.unlink()
    kills(run(tree), "must not report clean")


def test_a_removed_check_is_rc2_not_a_pass(tree: Path) -> None:
    """A deleted CHECKS row starves no floor, so membership is pinned separately."""
    p = tree / GATE.name
    p.write_text(p.read_text(encoding="utf-8")
                 .replace('    ("rule_is_sealed", check_rule_is_still_sealed, 3),\n', ""),
                 encoding="utf-8")
    kills(run(tree), "does not match REQUIRED_CHECKS", rc=2)


def test_a_check_that_stops_asserting_is_rc2_not_a_pass(tree: Path) -> None:
    """Gutted to a no-op, the check must be reported as starved rather than clean."""
    p = tree / GATE.name
    src = p.read_text(encoding="utf-8")
    src = src.replace("def check_findings(problems: list[str]) -> int:\n    n = 0",
                      "def check_findings(problems: list[str]) -> int:\n    return 0\n    n = 0")
    p.write_text(src, encoding="utf-8")
    kills(run(tree), "stops asserting", rc=2)


def test_problems_are_reported_before_floors(tree: Path) -> None:
    """Precedence: a real failure must be named as such, not as "the check stopped".

    In the corpus gate this precedence was backwards, and a genuinely broken builder
    was announced as a starved check -- an accurate diagnosis replaced by a misleading
    one.

    The mutation has to be one that trips BOTH conditions, or the test is vacuous. My
    first attempt used a single-day amendment and asserted only that "stops asserting"
    was absent; measuring it showed that mutation yields 17 assertions and starves no
    floor, so both orderings printed the same thing and the test proved nothing. The
    deleting-the-sealed-rule mutation does trip both: `check_rule_is_still_sealed`
    returns after 1 assertion against a floor of 3 while appending a real problem.
    Verified by running an order-inverted copy of the gate: 1 vs 2.
    """
    p = tree / "PREREGISTRATION.yaml"
    p.write_text(p.read_text(encoding="utf-8")
                 .replace("reproduction_before_amendment:",
                          "reproduction_before_amendment_DISABLED:"),
                 encoding="utf-8")
    res = run(tree)
    assert res.returncode == 1, (
        f"a real problem must be rc=1, got {res.returncode} — the floor was reported "
        f"in place of the diagnosis:\n{res.stderr}")
    assert "no longer carries" in res.stderr
    assert "stops asserting" not in res.stderr, (
        "the starved floor pre-empted the problem that caused it")


def test_the_precedence_mutation_would_starve_a_floor(tree: Path) -> None:
    """Guards the test above against becoming vacuous again.

    If `check_rule_is_still_sealed` ever grows assertions before its early return, the
    deleted-rule mutation stops starving its floor and the precedence test silently
    degrades into "rc is 1", which every ordering satisfies. Asserting the starvation
    directly keeps that failure loud.
    """
    src = GATE.read_text(encoding="utf-8")
    floor = int(re.search(r'\("rule_is_sealed", check_rule_is_still_sealed, (\d+)\)',
                          src).group(1))
    head = src[src.index("def check_rule_is_still_sealed"):src.index("no longer carries")]
    before_return = head.count("n += 1")
    assert before_return < floor, (
        f"check_rule_is_still_sealed now runs {before_return} assertion(s) before its "
        f"early return, which is no longer below its floor of {floor}; "
        f"test_problems_are_reported_before_floors needs a mutation that still starves "
        f"a floor, or it no longer distinguishes the two orderings")


# ------------------------------------------------------------ the gate is actually run

def test_the_gate_is_wired_into_verify_phase0(tree: Path) -> None:
    """An unrun gate is not a control (feedback_no_deploy_path_no_component)."""
    sh = (ROOT / "verify_phase0.sh").read_text(encoding="utf-8")
    assert "check_amendment_readiness.py" in sh, (
        "check_amendment_readiness.py is not invoked by verify_phase0.sh, so nothing "
        "runs it — the sealed rule would be enforced by a file nobody executes")
