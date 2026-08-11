"""Every number in FINDING-P0-TRIAGE.md must still be true of the artifacts.

Per feedback_quantify_qualifiers and feedback_verify_against_real_artifact: a
write-up's figures decay the moment the triage rules change, and they decay
silently in the flattering direction. This suite re-derives each figure from
triage.csv / triage_rules.py / the F0-1 evidence and requires the document to
match, so a reclassification that moves coverage from 70.5% to 66% breaks a test
instead of leaving a stale percentage in a report.

It also catches the specific error this file was written after making: the first
draft said "7 splits (-> 21 parts)" when SPLITS actually produces 18.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CLAIMS = HERE.parent
ROOT = CLAIMS.parent
sys.path.insert(0, str(CLAIMS))

import triage_rules as R  # noqa: E402

FINDING = ROOT / "results" / "FINDING-P0-TRIAGE.md"
REGISTER = ROOT / "EXCLUSION_REGISTER.md"


@pytest.fixture(scope="module")
def doc() -> str:
    assert FINDING.exists(), f"{FINDING.name} not generated"
    return FINDING.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    with (CLAIMS / "triage.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def counts(rows) -> Counter:
    return Counter(r["cls"] for r in rows)


def _pin(doc: str, needle: str) -> None:
    assert needle in doc, f"FINDING-P0-TRIAGE.md no longer states {needle!r}"


# ---- claim counts ------------------------------------------------------------

def test_total_claim_count(doc, rows):
    assert len(rows) == 546
    _pin(doc, "**546**")


def test_raw_unit_count(doc):
    with (CLAIMS / "claims_raw.csv").open(encoding="utf-8") as fh:
        raw = list(csv.DictReader(fh))
    assert len(raw) == 650
    _pin(doc, "| 650 |")


def test_claimable_before_splits_reconciles(doc, rows):
    """535 claimable + 11 net new from splits = 546. The arithmetic must close."""
    net_new = sum(len(v) for v in R.SPLITS.values()) - len(R.SPLITS)
    assert len(rows) - net_new == 535
    _pin(doc, "| 535 |")


def test_split_parent_and_part_counts(doc):
    parents = len(R.SPLITS)
    parts = sum(len(v) for v in R.SPLITS.values())
    assert (parents, parts) == (7, 18)
    _pin(doc, "7 parents → 18 parts")


def test_merge_group_count(doc):
    assert len(R.MERGE_GROUPS) == 25
    _pin(doc, "25 merge groups")


# ---- class distribution ------------------------------------------------------

def test_tested_share(doc, rows, counts):
    tested = sum(counts[c] for c in "ESCO")
    assert tested == 385
    assert f"{tested / len(rows):.1%}" == "70.5%"
    _pin(doc, "**385 (70.5%)**")
    _pin(doc, "**70.5%, not 100%**")


def test_definitional_share(doc, rows, counts):
    assert counts["D"] == 94
    assert f"{counts['D'] / len(rows):.1%}" == "17.2%"
    _pin(doc, "94 (17.2%)")


def test_normative_share(doc, rows, counts):
    assert counts["N"] == 57
    assert f"{counts['N'] / len(rows):.1%}" == "10.4%"
    _pin(doc, "57 (10.4%)")


def test_excluded_share(doc, rows, counts):
    assert counts["X"] == 10
    assert f"{counts['X'] / len(rows):.1%}" == "1.8%"
    _pin(doc, "**10 (1.8%)**")


def test_untested_share_is_the_complement(doc, rows, counts):
    untested = sum(counts[c] for c in "DNX")
    assert untested + sum(counts[c] for c in "ESCO") == len(rows)
    assert f"{untested / len(rows):.1%}" == "29.5%"
    _pin(doc, "29.5%")


def test_no_unclassified_rows(counts):
    assert counts["UNCLASSIFIED"] == 0


# ---- case registry -----------------------------------------------------------

def test_case_counts(doc, rows):
    cited = {c for r in rows for c in r["cases"].split()}
    assert len(R.CASES) == 93
    assert len(cited) == 90
    assert len(R.PLATFORM_CASES) == 3
    _pin(doc, "93 (90 cited, 3 declared platform prerequisites)")


def test_declined_arm_count(doc):
    assert len(R.DECLINED_ARMS) == 1
    _pin(doc, "`DECLINED_ARMS`")


# ---- the twelve rewritten oracles -------------------------------------------

REWRITTEN = ["F3-3", "F3-5", "F3-7", "F3-8", "F3-9", "F5-5",
             "F6-2", "F6-3", "F6-4", "F6-5", "F6-6", "F7-6"]


def test_twelve_oracles_named_in_the_finding_exist(doc):
    assert len(REWRITTEN) == 12
    for case in REWRITTEN:
        assert case in R.CASES, f"{case} named in the finding but not in the registry"
    _pin(doc, "Twelve oracles")


def test_every_rewritten_oracle_now_states_a_falsifying_condition():
    """The defect the finding reports must actually be fixed, not just described."""
    for case in REWRITTEN:
        oracle = R.CASES[case][3]
        assert "FALSE" in oracle or "OUTCOME UNKNOWN" in oracle, (
            f"{case}'s oracle still describes a measurement, not a falsification: "
            f"{oracle[:80]}")


def test_all_cited_oracles_state_a_falsifying_condition(rows):
    """Not just the twelve. This is CHK-06's scope, restated independently.

    Scoped to CITED cases, matching the gate. F9-1 is deliberately outside that
    scope: it is cited by no claim by construction (every claim it would serve is
    class X), and its 'oracle' honestly records NOT TESTABLE rather than inventing
    a falsifying condition it does not have. That exemption is asserted below
    rather than left implicit — an untestable case must be reachable only through
    PLATFORM_CASES, never by citation.
    """
    cited = {c for r in rows for c in r["cases"].split()}
    weak = [c for c in sorted(cited)
            if "FALSE" not in R.CASES[c][3] and "UNKNOWN" not in R.CASES[c][3]]
    assert weak == [], f"{len(weak)} cited case(s) cannot fail: {weak}"


def test_the_only_uncited_case_without_a_falsifier_is_declared_untestable(rows):
    """The exemption CHK-06's scoping creates must be exactly one known case.

    If a second case ever slips out of CHK-06's reach with no falsifying
    condition, it would be a designed experiment that cannot fail AND that no
    check looks at — the worst of both. This test is the tripwire.
    """
    cited = {c for r in rows for c in r["cases"].split()}
    exempt = [c for c in sorted(set(R.CASES) - cited)
              if "FALSE" not in R.CASES[c][3] and "UNKNOWN" not in R.CASES[c][3]]
    assert exempt == ["F9-1"], f"unexpected uncited case(s) with no falsifier: {exempt}"
    assert "NOT TESTABLE" in R.CASES["F9-1"][3], (
        "F9-1 must say so outright rather than reading like a runnable oracle")
    assert "F9-1" in R.PLATFORM_CASES, (
        "an untestable case must be declared, not merely uncited")


# ---- the six reclassified claims --------------------------------------------

RECLASSIFIED = {
    "C-s2-1-mermaid-014": "C",
    "C-s2-1-mermaid-019": "S",
    "C-s3-2-bullet-014": "S",
    "C-s4-4-prose-005": "S",
    "C-appB-trow-001": "S",
    "C-s4-4-bullet-002": "S",
}


def test_the_six_reclassified_claims_carry_their_corrected_class(rows, doc):
    by_id = {r["claim_id"]: r for r in rows}
    for cid, cls in RECLASSIFIED.items():
        assert cid in by_id, f"{cid} named in the finding but absent from the triage"
        assert by_id[cid]["cls"] == cls, (
            f"{cid} is {by_id[cid]['cls']}, finding says it was corrected to {cls}")
    assert len(RECLASSIFIED) == 6
    _pin(doc, "Six claims were classified as needing evidence no case produces")


def test_five_of_the_six_were_corrected_to_statistical(doc):
    """The first draft of the finding said 'four'. It was five.

    A miscount here is not cosmetic: the sentence's point is how many claims
    would have been published as deterministic yes/no answers when the evidence
    is a rate with a confidence interval.
    """
    n_stat = sum(1 for c in RECLASSIFIED.values() if c == "S")
    assert n_stat == 5
    _pin(doc, "Five of the six")
    _pin(doc, "`C-s2-1-mermaid-014`, went E→C")


# ---- the split that started as a conjunction --------------------------------

def test_the_three_way_split_exists_with_three_distinct_classes(rows, doc):
    parts = {r["claim_id"]: r["cls"] for r in rows
             if r["claim_id"].startswith("C-s9-mermaid-011-")}
    assert set(parts) == {"C-s9-mermaid-011-a", "C-s9-mermaid-011-b",
                          "C-s9-mermaid-011-c"}
    assert sorted(parts.values()) == ["E", "S", "X"], (
        f"the point of the split was that the classes differ: {parts}")
    _pin(doc, "Split into `-a` (latency, S), `-b` (default-deny, E), `-c` "
              "(fail-secure, X)")


def test_no_split_parent_survives_in_the_triage(rows):
    ids = {r["claim_id"] for r in rows}
    assert not (ids & set(R.SPLITS)), "a split parent is still present as a row"


# ---- F0-1 evidence -----------------------------------------------------------

def test_f0_1_result_matches_the_finding(doc):
    ev = json.loads((ROOT / "results" / "FINDING-F0-1-references.json")
                    .read_text(encoding="utf-8"))
    assert ev["n_checked"] == 24
    assert ev["n_failed"] == 0
    assert ev["unreachable"] == 0
    _pin(doc, "**Result: 24/24 verified.**")
    _pin(doc, "| **24/24** |")


def test_f0_1_evidence_is_per_url_not_a_summary():
    """A count without per-URL rows is not evidence a reader can re-check."""
    ev = json.loads((ROOT / "results" / "FINDING-F0-1-references.json")
                    .read_text(encoding="utf-8"))
    assert len(ev["results"]) == 24
    for r in ev["results"]:
        assert r["url"].startswith("http")
        assert r["http_status"] == 200
        assert r["page_title"], f"{r['claim_id']} has no page title recorded"


# ---- gate results ------------------------------------------------------------

def test_gate_and_selftest_counts(doc):
    src = (CLAIMS / "check_coverage.py").read_text(encoding="utf-8")
    n_checks = len(re.findall(r'"CHK-\d\d ', src))
    n_muts = len(re.findall(r"def m_[a-z_]+\(", src))
    assert n_checks >= 15, f"only {n_checks} checks found"
    assert n_muts == 14, f"{n_muts} mutations defined, finding says 14"
    _pin(doc, "15/15 pass")
    _pin(doc, "14/14 mutations killed")


def test_test_count_in_the_finding_is_not_below_reality(doc):
    """The finding cites a test count; it may grow, but must not be overstated.

    Counts COLLECTED tests, not `def test_` lines. Those diverge as soon as
    anything is parametrised, and the number the finding quotes is the one
    verify_phase0.sh prints, which is the collected count. Counting defs here made
    a truthful figure look overstated. No figure is quoted in this docstring on
    purpose: it would be a prose number, and this file is where the collected
    count is recomputed.
    """
    m = re.search(r"`claims/tests/` \((\d+) tests\)", doc)
    assert m, "the finding no longer states a test count"
    claimed = int(m.group(1))
    r = subprocess.run([sys.executable, "-m", "pytest", str(HERE), "-q",
                        "--collect-only", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, cwd=str(ROOT))
    got = re.search(r"(\d+) tests? collected", r.stdout)
    assert got, f"could not read a collected count from pytest:\n{r.stdout[-500:]}"
    actual = int(got.group(1))
    assert actual > 0, "collecting zero tests must not read as agreement"
    assert claimed <= actual, (
        f"finding claims {claimed} tests, pytest collects {actual}")


def test_redaction_figures_in_the_finding_are_lower_bounds_and_hold(doc):
    """The finding quotes a file count and a byte volume for the redaction gate.

    Both grow with every file added, so they are stated as `>=` and checked
    against a real run rather than pinned to a snapshot — a pinned exact figure
    would go stale on the next commit and be edited rather than re-measured, which
    is how a number stops being a measurement. Per
    feedback_zero_file_scan_is_error, a scan reading zero files must not agree with
    anything.
    """
    m = re.search(r"check_redaction\.py\s+# >=(\d+) files, >=(\d+)KB", doc)
    assert m, "the finding no longer states redaction-gate figures"
    claimed_files, claimed_kb = int(m.group(1)), int(m.group(2))
    r = subprocess.run([sys.executable, "check_redaction.py"],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"the redaction gate does not pass:\n{r.stdout}"
    files = re.search(r"(\d+) file\(s\) under", r.stdout)
    read = re.search(r"([\d,]+) bytes read", r.stdout)
    assert files and read, f"could not parse the gate's own output:\n{r.stdout}"
    actual_files = int(files.group(1))
    actual_kb = int(read.group(1).replace(",", "")) // 1000
    assert actual_files > 0, "a zero-file scan must not read as agreement"
    assert claimed_files <= actual_files, (
        f"finding claims >={claimed_files} files, the gate scanned {actual_files}")
    assert claimed_kb <= actual_kb, (
        f"finding claims >={claimed_kb}KB, the gate read {actual_kb}KB")


def test_register_line_count(doc):
    n = len(REGISTER.read_text(encoding="utf-8").splitlines())
    assert n == 437
    _pin(doc, "437 lines")


# ---- honesty properties, not counts ------------------------------------------

def test_finding_records_defects_in_its_own_instrument():
    """Section 4 is the calibration section; its absence would make §3 prosecution."""
    text = FINDING.read_text(encoding="utf-8")
    assert "four false accusations" in text
    for defect in ("CHK-07 flagged 56 claims", "four false positives",
                   "cited an experiment that does not exist",
                   "ALLOW list was entirely dead"):
        assert defect in text, f"self-caught defect no longer recorded: {defect!r}"


def test_finding_states_zero_spend():
    text = FINDING.read_text(encoding="utf-8")
    assert "**$0**" in text
    assert "$55–95" in text, "the projection must stay disclosed alongside the actual"


def test_finding_carries_no_cloud_identifiers():
    text = FINDING.read_text(encoding="utf-8")
    assert re.findall(r"\b\d{12}\b", text) == []
    assert "arn:aws:" not in text
