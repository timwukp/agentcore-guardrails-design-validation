"""Every date and count in AWS-BEHAVIOR-CHANGES.md re-derived from the evidence.

Why this file exists
--------------------
`AWS-BEHAVIOR-CHANGES.md` is the one deliverable whose entire content is **dates**, and a
date in prose is the exact artefact this project screens the document under test for
(`feedback_prose_is_not_verified`). It would be absurd to correct v1.2 for carrying an
undated support claim and then ship a file of undated support claims about the correction.

So every figure in it is re-derived here from `evidence/<run>/f5/F5-7a/analysis.json`:
the four archived snapshots that read "Not yet supported", the two live reads that read
"Supported", the seven-row tables that never mention Optimization, and the replication's
compared-field count.

The load-bearing arm is `test_abc02_records_no_change_date`. ABC-01 has dated observations
on both sides of the transition; ABC-02 has a live contradiction and **silence** before it.
The file's own stated rule is that silence is not a transition, and the way that rule fails
is by someone later "tidying" ABC-02 into a dated entry to match ABC-01's shape. That arm
asserts, against the archived pages themselves, that no such date is derivable.

Offline, $0: reads two analysis.json files and one markdown file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "AWS-BEHAVIOR-CHANGES.md"
DAY1 = "r20260809T094500Z"
# The canonical day-2 run is the one DEV-SEAL-10 scheduled BEFORE any day-2 result
# existed, not the (equally replicating) manual run that raced it — see DEV-SEAL-13 and
# FINDING-F5-7A §7 "Two day-2 runs". Read from the comparator's verdict rather than typed,
# so this file cannot drift from the artifact the way three artifacts just did.
REPLICATION = ROOT / "results" / "f5_7a_replication.json"
DAY2 = json.loads(REPLICATION.read_text(encoding="utf-8"))["day2"]
DAY2_LOSER = "r20260810T001115Z"

# The row AWS renamed. Both spellings appear across the archive, and the entry's whole
# claim is that the cells behind them changed, so neither name is hardcoded as "the" row.
OLD_ROW = "Evaluations"
NEW_ROW = "Evaluations and Optimizations"


def analysis(run_id: str) -> dict:
    p = ROOT / "evidence" / run_id / "f5" / "F5-7a" / "analysis.json"
    assert p.is_file(), f"{p} is missing — the entry rests on evidence that is not here"
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def doc() -> str:
    """The file, whitespace-normalized to one line.

    Every assertion here is about *what the file states*, never about how it is wrapped.
    Markdown hard-wraps at ~88 columns, so a raw-substring assertion on a sentence is
    partly an assertion about where the line break falls: it passes, then a later reflow
    of an untouched paragraph fails it, and the diagnosis ("the file no longer states X")
    is wrong. Two arms here failed that way before this normalization existed.

    Normalizing is safe precisely because nothing below depends on layout — no arm asserts
    a table renders, only that a table *cell* contains a figure.
    """
    assert DOC.is_file(), "AWS-BEHAVIOR-CHANGES.md does not exist"
    return " ".join(DOC.read_text(encoding="utf-8").split())


@pytest.fixture(scope="module")
def a1() -> dict:
    return analysis(DAY1)


@pytest.fixture(scope="module")
def a2() -> dict:
    return analysis(DAY2)


def wayback(a: dict) -> dict[str, dict]:
    return {w["timestamp"]: w for w in a["instrument_B"]["wayback"]}


def pin(doc: str, needle: str) -> None:
    assert needle in doc, f"AWS-BEHAVIOR-CHANGES.md no longer states {needle!r}"


# --------------------------------------------------------------- ABC-01, the dated entry

def test_abc01_old_value_is_what_the_archive_says(doc: str, a1: dict) -> None:
    """"Not yet supported" is quoted; the archived pages must actually say it."""
    olds = {ts: w["rows"][OLD_ROW] for ts, w in wayback(a1).items()
            if OLD_ROW in w["rows"]}
    assert olds, "no archived snapshot carries an Evaluations row at all"
    for ts, cells in olds.items():
        assert cells["data_plane"] == "Not yet supported", (
            f"snapshot {ts} reads {cells['data_plane']!r}, but the entry quotes "
            f"'Not yet supported'")
        assert cells["control_plane"] == "Supported"
    pin(doc, "`Evaluations · Not yet supported · Supported`")


def test_abc01_change_window_bounds_come_from_the_snapshots(doc: str, a1: dict) -> None:
    """The window is `after 2026-07-14, at or before 2026-08-09`, both re-derived.

    The lower bound is the LATEST snapshot still reading the old value — not the earliest,
    which would state a window three months too wide and would be the conservative-looking
    error that is actually a weaker claim.
    """
    olds = sorted(ts for ts, w in wayback(a1).items()
                  if w["rows"].get(OLD_ROW, {}).get("data_plane") == "Not yet supported")
    assert olds, "no snapshot reads the old value, so no lower bound exists"
    latest_old = olds[-1]
    assert latest_old == "20260714091042", (
        f"the latest snapshot reading 'Not yet supported' is {latest_old}, so the entry's "
        f"lower bound of 2026-07-14 is wrong")
    pin(doc, "after **2026-07-14**, at or before **2026-08-09**")


def test_abc01_new_value_is_what_both_live_reads_say(doc: str, a1: dict, a2: dict) -> None:
    for label, a in (("day 1", a1), ("day 2", a2)):
        rows = a["instrument_B"]["live"]["rows"]
        assert NEW_ROW in rows, f"{label}'s live page has no {NEW_ROW!r} row"
        assert rows[NEW_ROW] == {"data_plane": "Supported",
                                 "control_plane": "Supported"}, \
            f"{label}: {rows[NEW_ROW]}"
        assert OLD_ROW not in rows, (
            f"{label}: the live page still carries a separate {OLD_ROW!r} row, so "
            f"'row renamed and merged' is wrong")
    pin(doc, "`Evaluations and Optimizations · Supported · Supported`")


def test_abc01_counts_the_agreeing_snapshots_on_both_days(doc: str,
                                                          a1: dict, a2: dict) -> None:
    """The count is derived, and the two days legitimately differ — so both are stated.

    My first version of this arm said "Four archived snapshots" and pinned four dates. Day
    1 returned **five** (2026-06-23 was the one I dropped), and the finding's own §5 table
    and prose both list five, so the new file was the outlier and the arm agreed with the
    outlier. Fixed by deriving the number instead of transcribing it.

    Day 2's CDX query returned only four of the five. That is a third-party index queried
    twice, not an observation about AWS, so it is not a disagreement — but the entry has to
    state which number the window rests on, or a reader recomputing from day 2 alone finds
    four and cannot tell whether the fifth was lost or invented.
    """
    def agreeing(a: dict) -> set[str]:
        return {ts for ts, w in wayback(a).items()
                if w["rows"].get(OLD_ROW, {}).get("data_plane") == "Not yet supported"}

    d1, d2 = agreeing(a1), agreeing(a2)
    assert len(d1) == 5, f"day 1 has {len(d1)} snapshots reading the old value: {sorted(d1)}"
    assert d2 < d1, (
        f"day 2's agreeing set {sorted(d2)} is not a subset of day 1's {sorted(d1)} — a "
        f"snapshot reading the old value on day 2 but not day 1 would mean the archive "
        f"itself changed, which is fatal to instrument B rather than a note")
    assert len(d2) == 4, f"day 2 has {len(d2)}: {sorted(d2)}"

    pin(doc, "**Five** archived snapshots")
    for ts in sorted(d1):                      # 20260412130410 -> 2026-04-12
        pin(doc, f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}")
    # The day-2 shortfall must be disclosed, not silently absorbed into "five".
    missing = sorted(d1 - d2)
    assert len(missing) == 1, missing
    pin(doc, f"`{missing[0]}` was not")
    pin(doc, "the window rests on the five")


def test_abc01_is_marked_documentation_not_api(doc: str) -> None:
    """The entry must not read as an API observation. Instrument B is a web page."""
    assert "**Not** an API observation" in doc
    assert "Instrument** | B" in doc or "**Instrument** | B" in doc


# --------------------------------- ABC-02, the entry that deliberately carries NO date

def test_abc02_records_no_change_date(doc: str, a1: dict, a2: dict) -> None:
    """THE arm: no archived page mentions Optimization, so no date is derivable.

    If a future edit gives ABC-02 a change window to match ABC-01's shape, this fails
    against the archive itself rather than against my memory of it. The failure mode is
    tidiness, not malice: two adjacent table rows where one has a date and one says
    "cannot be established" look inconsistent, and the inconsistency is the finding.
    """
    for label, a in (("day 1", a1), ("day 2", a2)):
        for ts, w in wayback(a).items():
            hit = [r for r in w["rows"] if "ptimi" in r]
            assert not hit, (
                f"{label}: archived snapshot {ts} DOES carry an Optimization row {hit} — "
                f"AWS was not silent, so ABC-02's 'change date cannot be established' is "
                f"no longer the honest reading and the entry must be reclassified")
    pin(doc, "**cannot be established**")
    assert "inferring a transition from the **absence** of evidence" in doc

    # And the file's rule must still forbid it, or the entry is merely unfilled.
    assert "Absence of evidence is not a transition." in doc


def test_abc02_live_row_is_shared_with_evaluations(doc: str, a1: dict) -> None:
    """The two entries describe one row on AWS's page; the file says so."""
    f = a1["analysis"]["findings"]["optimization_no_privatelink"]
    assert f["row_is_shared_with_evaluations"] is True
    assert f["verdict"] == "DOC_REFUTED_CHANGE_DATE_UNDETERMINED"
    assert f["aws_page_history"] == [], (
        "the analysis now carries page history for Optimization, so a change window may "
        "be derivable and ABC-02 needs revisiting")
    pin(doc, "the two rows are now one row on AWS's page")


def test_abc02_seven_row_tables_are_seven_rows(doc: str, a1: dict) -> None:
    counts = {ts: len(w["rows"]) for ts, w in wayback(a1).items() if w["has_support_table"]}
    assert counts, "no archived snapshot has a support table"
    assert set(counts.values()) == {7}, f"row counts are {counts}, not uniformly 7"
    pin(doc, "seven rows")


# ------------------------------------------------------------------ the replication claim

def test_the_replication_figures_match_the_comparator(doc: str) -> None:
    body = json.loads(REPLICATION.read_text(encoding="utf-8"))
    assert body["replicated"] is True, (
        "the comparator does not report a replication, so no entry here may claim one")
    pin(doc, f"{body['n_fields_compared']} fields compared, 0 disagreements")
    assert not body["disagreements"]
    assert body["day1"] == DAY1


def test_every_artifact_names_the_same_canonical_day2_run() -> None:
    """The defect DEV-SEAL-13 records: three artifacts naming three different runs.

    `DAY2` above is *read from* the verdict file, so asserting `body["day2"] == DAY2` would
    be true by construction — the vacuous shape this suite exists to catch. The property
    that actually failed is cross-artifact agreement, so that is what is asserted: the
    comparator's verdict, the finding's provenance block, and the amendment gate's view of
    the finding must name one run, and it must be the run DEV-SEAL-10 fixed in advance.

    Both day-2 runs replicate, so this is not about which evidence is better. It is about
    the selection rule predating the data — with two runs on disk and no pinned choice,
    "the canonical one" silently becomes "whichever an artifact happened to be edited to".
    """
    body = json.loads(REPLICATION.read_text(encoding="utf-8"))
    finding = (ROOT / "results" / "FINDING-F5-7A.md").read_text(encoding="utf-8")
    m = re.search(r"<!--\s*provenance\s*\n(.*?)^-->", finding, re.S | re.M)
    assert m, "FINDING-F5-7A has no provenance block"
    runs = json.loads(m.group(1))["evidence_runs"]

    assert body["day2"] in runs, (
        f"the comparator's verdict rests on {body['day2']}, which the finding does not "
        f"declare (it declares {runs}) — this is exactly the three-way disagreement "
        f"DEV-SEAL-13 records")
    assert sorted(runs) == sorted([DAY1, body["day2"]]), runs

    # Both runs exist on disk; the loser is kept, not deleted (DEV-SEAL-10's rule).
    assert (ROOT / "evidence" / DAY2_LOSER / "f5" / "F5-7a").is_dir(), (
        f"{DAY2_LOSER} has been deleted; a repeat that agrees must be kept, or the record "
        f"shows a single clean replication that is not what happened")
    assert DAY2_LOSER not in runs, (
        f"{DAY2_LOSER} is declared as evidence alongside the canonical run — two same-day "
        f"runs cannot both count toward a two-calendar-day requirement")

    # And the choice must be justified in prose by precedence, not by preference.
    dev = (ROOT / "DEVIATIONS.md").read_text(encoding="utf-8")
    assert "before any\nday-2 result existed" in dev or \
           "before any day-2 result existed" in dev.replace("\n", " "), (
        "DEV-SEAL-13 no longer states WHY the scheduled run is canonical; without the "
        "pre-registration ground, naming one of two agreeing runs is an unexplained pick")


def test_both_days_are_derived_from_the_records_not_the_run_ids(doc: str) -> None:
    """The two dates the file prints must come from t_start_utc, as everywhere else."""
    days = {}
    for rid in (DAY1, DAY2):
        base = ROOT / "evidence" / rid / "f5" / "F5-7a"
        found = set()
        for p in base.glob("*.json"):
            if p.name in ("environment.json", "analysis.json", "summary.json"):
                continue
            ts = json.loads(p.read_text(encoding="utf-8")).get("t_start_utc")
            if ts:
                found.add(str(ts)[:10])
        assert len(found) == 1, f"{rid} spans {sorted(found)}; a run straddling midnight " \
                                f"makes 'two calendar days' ambiguous"
        days[rid] = found.pop()
    assert days[DAY1] == "2026-08-09" and days[DAY2] == "2026-08-10", days
    pin(doc, "2026-08-09 and again on 2026-08-10")


# ---------------------------------------------------------------- structure and hygiene

def test_every_entry_names_a_finding_that_exists(doc: str) -> None:
    refs = set(re.findall(r"results/(FINDING-[A-Z0-9-]+\.md)", doc))
    assert refs, "no entry cites a finding file, so nothing here is traceable"
    for r in refs:
        assert (ROOT / "results" / r).is_file(), f"cited {r} does not exist"


def test_entry_ids_are_sequential_and_unique() -> None:
    # The only arm that is genuinely about layout — `## ABC-NN` must be a heading, not a
    # mention in prose — so it reads the raw text rather than the normalized fixture.
    ids = re.findall(r"^## (ABC-\d+)", DOC.read_text(encoding="utf-8"), re.M)
    assert ids, "no ABC-NN entries"
    assert len(ids) == len(set(ids)), f"duplicate entry ids: {ids}"
    assert ids == [f"ABC-{i:02d}" for i in range(1, len(ids) + 1)], ids


def test_the_watch_list_scripts_all_exist(doc: str) -> None:
    """A detector that is not a file cannot detect (feedback_no_deploy_path_no_component)."""
    scripts = set(re.findall(r"`((?:f\d+_\w+|lib|claims)/[\w/]+\.py)`", doc))
    assert scripts, "the watch list names no detector script"
    for s in scripts:
        assert (ROOT / s).is_file(), f"watch-list detector {s} does not exist"


def test_no_account_identifier_or_arn(doc: str) -> None:
    """Published artifact; the redaction gate treats 12 digits and arn: as findings."""
    assert not re.search(r"\b\d{12}\b", doc)
    assert "arn:aws" not in doc


def test_the_file_distinguishes_documentation_from_service(doc: str) -> None:
    """The whole file's honesty rests on this distinction being stated, not implied.

    Whitespace-normalized before matching: markdown hard-wraps at ~88 columns, so a
    sentence-level assertion that greps the raw text is really asserting where the line
    break falls. Same normalization as test_amendment_gate.py's `"which is not\\nthe same
    as passing".replace("\\n", " ")`.
    """
    flat = " ".join(doc.split())
    assert "it does not certify that AWS's *service* changed" in flat
    assert "a page is a statement about a service, not the service" in flat
