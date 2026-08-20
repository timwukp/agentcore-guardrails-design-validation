"""Mutation harness for the publish gate's replication arms.

WHY THIS FILE EXISTS, AND WHY IT IS SCOPED TO REPLICATION
--------------------------------------------------------
`check_site_invariants.py` is the gate that stops the site from stating a claim its artifacts do not
support, and the claim it exists for is the 2026-08-19 one: "a replication happened", asserted by no
artifact. That arm was mutation-checked by hand when it was written. A hand-run exercise is a memory,
not a test (`feedback_test_suite_over_memory`): it cannot notice the day someone widens a vocabulary,
renames a key, or moves the count to a different payload file, and the gate would then pass by no
longer looking. So the replication arms get a committed harness.

Two later groups of arms are here for the same reason rather than for that history: the audit report is
the only payload file that tells a reader to DO something, and a diagram box is the only one that states
a conclusion about a component in a single colour, with no words attached and every chance of being
screenshotted away from its case table. Both are claims addressed to somebody else's production system.

The remaining arms (typed totals, pass rate, figure bytes, seals) are left to the one-off exercise
recorded in the gate's own docstring. That is a stated limit, not an oversight — and the limit is where
the next extension goes, not a line to stop reading at.

HOW A MUTANT IS BUILT, AND THE TWO WAYS THIS HARNESS WOULD OTHERWISE HAVE PROVED NOTHING
---------------------------------------------------------------------------------------
* **The manifest arm masks every other arm.** Any edit to a payload file changes its sha256, so
  `manifest_liveness` fires first and the arm under test is never reached — a red run for the wrong
  reason. `_mutate` therefore re-hashes the file it edited into `MANIFEST.json`, which is also the
  realistic case: a defect that reaches publish arrives WITH a consistent manifest, because the builder
  hashes whatever it emitted, defect included.
* **A mutant that does not land.** Every mutation asserts the bytes changed before the gate runs
  (`feedback_probe_must_reach_the_code`), and every failure assertion names the arm it expects, so a
  mutant killed by an unrelated arm is a failure of this harness rather than a pass.

A no-mutant control runs first and must exit 0, so a red result below is attributable to the mutation
and not to a payload copy the gate could not read at all.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GATE = REPO / "platform" / "build" / "check_site_invariants.py"
BUILDER = REPO / "platform" / "build" / "build_site_data.py"
DIST = REPO / "site" / "dist"
ARM = "no_replication_claim_authored_by_the_build"
ARCHIVE_ARM = "replication_needs_two_days"


@pytest.fixture(scope="module")
def payload(tmp_path_factory) -> Path:
    """One real payload, built as a SUBPROCESS.

    Built rather than borrowed from `~/grx-site-payload`, so the harness cannot be satisfied by a stale
    directory somebody left behind; and as a subprocess rather than an import, so nothing this test
    holds in memory can stand in for what the builder actually wrote to disk.
    """
    out = tmp_path_factory.mktemp("gate-payload") / "payload"
    proc = subprocess.run([sys.executable, str(BUILDER), "--out", str(out),
                           "--stamp", "20260101T000000Z", "--figure-check-rc", "0"],
                          capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return out


def run_gate(payload: Path, dist: Path = DIST) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GATE), "--payload", str(payload),
                           "--dist", str(dist), "--verbose"],
                          capture_output=True, text=True, cwd=REPO)


def copy_of(payload: Path, tmp_path: Path, tag: str) -> Path:
    dest = tmp_path / f"payload-{tag}"
    shutil.copytree(payload, dest)
    return dest


def _mutate(payload: Path, rel: str, edit) -> None:
    """Apply `edit` to a payload JSON file and make MANIFEST.json consistent with the result."""
    path = payload / rel
    before = path.read_bytes()
    data = json.loads(before.decode())
    edit(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    after = path.read_bytes()
    assert after != before, f"the mutation of {rel} changed no bytes, so the gate never saw it"
    manifest_path = payload / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rel in manifest["outputs_sha256"], rel
    manifest["outputs_sha256"][rel] = hashlib.sha256(after).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def expect_killed(payload: Path, arm: str, phrase: str) -> None:
    proc = run_gate(payload)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert f"[{arm}]" in body, f"killed by some other arm, not {arm}:\n{body[-2000:]}"
    assert phrase in body, f"{arm} fired but not for the reason under test:\n{body[-2000:]}"


# --------------------------------------------------------------------------- the control

def test_no_mutant_control(payload: Path):
    proc = run_gate(payload)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    # And the arms under test must actually have looked at something. A gate that passed because the
    # payload has no replication data at all would be the worst possible green.
    assert ARM in proc.stdout and "vocabulary state(s) checked against the archive" in proc.stdout
    pipeline = json.loads((payload / "pipeline.json").read_text(encoding="utf-8"))
    assert pipeline["cases"], "the payload states no per-case replication state"


# --------------------------------------------------------------------------- the worded claim
#
# The reason this arm was extended: `pipeline.json` states replication IN WORDS, and a boolean-only
# guard reads a page saying "two_or_more_archived_days_agreeing" as containing no claim at all.

def _first_case_with(payload: Path, n: int) -> str:
    pipeline = json.loads((payload / "pipeline.json").read_text(encoding="utf-8"))
    got = sorted(c for c, row in pipeline["cases"].items() if row["n_archived_prior_days"] == n)
    assert got, f"no case in the payload has exactly {n} archived prior day(s)"
    return got[0]


def test_a_worded_replication_claim_for_an_unarchived_case_fails_the_publish(payload, tmp_path):
    case = _first_case_with(payload, 0)
    mutant = copy_of(payload, tmp_path, "worded")
    _mutate(mutant, "pipeline.json",
            lambda d: d["cases"][case].__setitem__("replication",
                                                   "two_or_more_archived_days_agreeing"))
    expect_killed(mutant, ARM, "asserts >= 2 archived day(s)")


def test_under_claiming_a_measured_case_also_fails(payload, tmp_path):
    """The other direction. An archive the payload cannot see is how an under-claim and an over-claim
    become indistinguishable from inside the payload, so both are violations."""
    case = _first_case_with(payload, 2)
    mutant = copy_of(payload, tmp_path, "underclaim")
    _mutate(mutant, "pipeline.json",
            lambda d: d["cases"][case].__setitem__("replication", "no_archived_prior_day"))
    expect_killed(mutant, ARM, "under-claims what was measured")


def test_a_new_replication_vocabulary_must_be_classified_not_ignored(payload, tmp_path):
    """The name-list defect (`feedback_scope_as_namelist`): a value nothing recognises must fail rather
    than pass, or the gate stops looking the day the vocabulary grows."""
    case = _first_case_with(payload, 0)
    mutant = copy_of(payload, tmp_path, "vocab")
    _mutate(mutant, "pipeline.json",
            lambda d: d["cases"][case].__setitem__("replication", "replicated"))
    expect_killed(mutant, ARM, "in neither CLAIMS_N_ARCHIVED_PRIOR_DAYS")


# --------------------------------------------------------------------------- the counted claim

def test_the_archived_day_count_is_cross_derived_against_the_archive(payload, tmp_path):
    case = _first_case_with(payload, 0)
    mutant = copy_of(payload, tmp_path, "count")
    _mutate(mutant, "pipeline.json",
            lambda d: d["cases"][case].__setitem__("n_archived_prior_days", 2))
    expect_killed(mutant, ARCHIVE_ARM, "disagrees with archive.json")


def test_the_headline_two_day_total_is_cross_derived(payload, tmp_path):
    mutant = copy_of(payload, tmp_path, "total")
    _mutate(mutant, "pipeline.json",
            lambda d: d["totals"].__setitem__("n_with_two_or_more_archived_days", 0))
    expect_killed(mutant, ARCHIVE_ARM, "case(s) have two or more archived days")


# --------------------------------------------------------------------------- authored prose
#
# Prose is admitted two ways and no third: verbatim from the file its document names, or naming no case
# and no calendar day. A paragraph the build composed that names a case and a date is the 2026-08-19
# sentence, and both halves of the rule have to be shown to bite.

def _finding_with_replication_prose(payload: Path) -> int:
    findings = json.loads((payload / "findings.json").read_text(encoding="utf-8"))["findings"]
    for i, f in enumerate(findings):
        text = ((f.get("provenance") or {}).get("replication") or "")
        if len(text) > 80:
            return i
    pytest.fail("no finding carries a replication paragraph, so these arms would be vacuous")


def test_prose_the_build_edited_no_longer_matches_its_source(payload, tmp_path):
    i = _finding_with_replication_prose(payload)
    mutant = copy_of(payload, tmp_path, "prose")

    def edit(d):
        prov = d["findings"][i]["provenance"]
        prov["replication"] = prov["replication"] + " It was repeated again on 2026-09-01."

    _mutate(mutant, "findings.json", edit)
    expect_killed(mutant, ARM, "does not appear in")


def test_prose_with_no_source_cannot_be_published(payload, tmp_path):
    """Strip the provenance pointer and the same paragraph becomes unattributable — which is the state
    the gate must refuse, because "the build wrote this" and "a human wrote this" are then the same
    bytes. `provenance.replication` is a key that reads as a record, so it has no rationale escape."""
    i = _finding_with_replication_prose(payload)
    mutant = copy_of(payload, tmp_path, "nosource")
    _mutate(mutant, "findings.json", lambda d: d["findings"][i].pop("source"))
    expect_killed(mutant, ARM, "does not declare itself a rationale")


def test_a_rationale_may_not_smuggle_in_an_assertion_about_a_measurement(payload, tmp_path):
    """The rationale escape is narrow by construction: a `why_…` key admits prose about counting, and
    the moment it names a case or a day it is a claim about a measurement and needs a file behind it."""
    mutant = copy_of(payload, tmp_path, "smuggle")
    case = _first_case_with(payload, 2)
    _mutate(mutant, "pipeline.json",
            lambda d: d["totals"].__setitem__(
                "why_replication_is_counted_from_the_archive_only",
                f"{case} was replicated on 2026-08-12, so the archive is not needed."))
    expect_killed(mutant, ARM, "makes it an assertion about a measurement")


def test_a_build_authored_rationale_naming_no_case_and_no_day_is_allowed(payload, tmp_path):
    """The negative control for the rule above. Without this, "all prose must be copied from a file"
    would look identical from the outside, and the only way to satisfy it would be to invent a source
    pointer for a sentence that explains how a count is taken."""
    mutant = copy_of(payload, tmp_path, "note")
    _mutate(mutant, "pipeline.json",
            lambda d: d["totals"].__setitem__(
                "why_replication_is_counted_from_the_archive_only",
                "Two timestamps inside one evidence file are one run that crossed midnight."))
    proc = run_gate(mutant)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]


# --------------------------------------------------------------------------- the unstyled state
#
# Not a payload mutant: the defect lives in the STYLESHEET, and it is invisible to the type checker and
# to every JSON assertion. The badge class is derived from the state name, so adding a state to the
# vocabulary without adding a rule produces a badge that renders as unremarkable — which for STALE is
# the one wrong reading.

def test_a_pipeline_state_with_no_stylesheet_rule_fails_the_publish(payload, tmp_path):
    dist = tmp_path / "dist"
    shutil.copytree(DIST, dist)
    sheets = sorted((dist / "assets").glob("*.css"))
    assert sheets, "the built dist carries no stylesheet, so this arm would be vacuous"
    changed = 0
    for sheet in sheets:
        before = sheet.read_text(encoding="utf-8")
        after = before.replace(".s-stale", ".s-stale-DISABLED")
        if after != before:
            sheet.write_text(after, encoding="utf-8")
            changed += 1
    assert changed, "the rule under test is not in the built stylesheet at all"
    proc = run_gate(payload, dist)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert "[pipeline_states_are_styled]" in body, body[-2000:]
    assert "STALE" in body


def test_an_audit_status_with_no_stylesheet_rule_fails_the_publish(payload, tmp_path):
    """`not_measured` is the token whose unstyled reading is wrong in the dangerous direction.

    A badge with no rule is a plain box, and a plain box beside a control reads as "nothing remarkable
    here" — where the token means this study never examined that control. So the mutant disables that
    rule specifically rather than any of the five.
    """
    dist = tmp_path / "dist"
    shutil.copytree(DIST, dist)
    sheets = sorted((dist / "assets").glob("*.css"))
    assert sheets, "the built dist carries no stylesheet, so this arm would be vacuous"
    changed = 0
    for sheet in sheets:
        before = sheet.read_text(encoding="utf-8")
        # Renamed rather than deleted, which is the realistic slip and the harder one to catch: the rule
        # is still visibly present in the file, so only a whole-token match kills this mutant.
        after = before.replace(".st-not_measured", ".st-not_measured_at_all")
        if after != before:
            sheet.write_text(after, encoding="utf-8")
            changed += 1
    assert changed, "the rule under test is not in the built stylesheet at all"
    proc = run_gate(payload, dist)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert "[audit_vocabularies_are_styled]" in body, body[-2000:]
    assert "st-not_measured" in body


# --------------------------------------------------------------------------- the audit report
#
# The audit page is the only payload file that tells a reader to DO something, so it gets the same
# treatment as the replication arms: `report.py` enforces the citation rules while composing, and a test
# that only exercised `report.py` would be that program's word for its own behaviour. These mutants edit
# the PUBLISHED bytes, which is where a refactor's slip would land.

AUDIT_ARM = "audit_report_is_licensed"


def _first_recommendation(payload) -> int:
    audit = json.loads((payload / "audit.json").read_text(encoding="utf-8"))
    recs = audit["report"]["recommendations"]
    assert recs, "the published audit report recommends nothing, so these arms would be vacuous"
    idx = next((i for i, r in enumerate(recs) if r.get("licensed_by")), None)
    assert idx is not None, "no recommendation names a licensing case"
    return idx


def test_a_recommendation_resting_on_an_inconclusive_verdict_fails_the_publish(payload, tmp_path):
    i = _first_recommendation(payload)
    mutant = copy_of(payload, tmp_path, "inconclusive")
    _mutate(mutant, "audit.json",
            lambda d: d["report"]["recommendations"][i]["licensed_by"][0]
            .__setitem__("verdict", "INCONCLUSIVE"))
    expect_killed(mutant, AUDIT_ARM, "licenses no recommendation")


def test_a_recommendation_citing_a_case_outside_the_register_fails(payload, tmp_path):
    i = _first_recommendation(payload)
    mutant = copy_of(payload, tmp_path, "unknowncase")
    _mutate(mutant, "audit.json",
            lambda d: d["report"]["recommendations"][i]["licensed_by"][0]
            .__setitem__("case", "F99-1"))
    expect_killed(mutant, AUDIT_ARM, "absent from the register")


def test_a_recommendation_citing_a_never_cite_case_fails(payload, tmp_path):
    """F5-3b's verdict on disk is TRUE and it may be cited as nothing at all. A mutant citing it WITH the
    right verdict passes every other check in this arm, which is what makes it worth committing: the
    restriction is the only thing between it and a published recommendation."""
    census = json.loads((payload / "census.json").read_text(encoding="utf-8"))
    never = [r for r in census["rows"] if "NEVER_CITE" in (r.get("citation_restrictions") or [])]
    assert never, "no case is marked NEVER_CITE, so this arm would be vacuous"
    row = never[0]
    i = _first_recommendation(payload)
    mutant = copy_of(payload, tmp_path, "nevercite")
    _mutate(mutant, "audit.json",
            lambda d: d["report"]["recommendations"][i]["licensed_by"].append(
                {"case": row["case"], "verdict": row["verdict"]}))
    expect_killed(mutant, AUDIT_ARM, "NEVER_CITE")


def test_the_reports_quoted_verdict_mix_is_re_derived_from_the_census(payload, tmp_path):
    mutant = copy_of(payload, tmp_path, "mix")
    _mutate(mutant, "audit.json",
            lambda d: d["report"]["study"]["verdict_mix"].__setitem__("FALSE", 0))
    expect_killed(mutant, AUDIT_ARM, "no longer describes the study it cites")


def test_a_percentage_on_the_audit_page_fails_the_publish(payload, tmp_path):
    """The headline a reader remembers. Adding one is a two-word edit, it reads as a summary, and it is
    arithmetic over a control this study never examined and one where the guidance did not hold."""
    mutant = copy_of(payload, tmp_path, "percent")
    _mutate(mutant, "audit.json",
            lambda d: d["report"]["headline"].__setitem__(
                "statement", "Your submission passes 84% of the controls this study covers."))
    expect_killed(mutant, AUDIT_ARM, "states the percentage")


def test_a_withheld_recommendation_with_no_reason_fails(payload, tmp_path):
    audit = json.loads((payload / "audit.json").read_text(encoding="utf-8"))
    assert audit["report"]["recommendations_withheld"], "the report withholds nothing here"
    mutant = copy_of(payload, tmp_path, "withheld")
    _mutate(mutant, "audit.json",
            lambda d: d["report"]["recommendations_withheld"][0].__setitem__("why_withheld", "  "))
    expect_killed(mutant, AUDIT_ARM, "states no reason")


# --------------------------------------------------------------------------- the design diagrams
#
# The diagrams get committed mutants for the same reason the audit report does, one step further: a box
# is the only payload artifact that states a conclusion about a COMPONENT, in one colour, with no words
# attached. It is also the artifact most likely to be screenshotted out of the site and shown without
# its case table. Two programs already read the authored topology — `derive_architecture()` draws it and
# `check_architecture.py` rules on it — and neither is a second pair of eyes on the colour that shipped.
# These mutants edit the PUBLISHED bytes, so they exercise the arm that looks at what a reader sees.

ARCH_ARM = "architecture_colours_are_licensed"


def _arch_box(payload: Path, want_status: str) -> tuple[int, int, dict]:
    """The indices of the first box with `want_status`, so a mutation can be addressed by path.

    Returned as indices rather than as the object because `_mutate` re-reads the file: an object taken
    from a different `json.loads` would be edited and then thrown away, and the mutant would not land.
    """
    arch = json.loads((payload / "architecture.json").read_text(encoding="utf-8"))
    for i, diagram in enumerate(arch["diagrams"]):
        for j, box in enumerate(diagram.get("boxes") or []):
            if box.get("status") == want_status:
                return i, j, box
    raise AssertionError(f"no box on any diagram is {want_status}, so this arm would be vacuous")


def test_a_box_with_nothing_measured_may_not_be_painted_as_validated(payload, tmp_path):
    """The cheapest wrong claim available: a component this study never examined, coloured as one it
    did. The status is one string in one authored file, the box has no cases at all, and the diagram
    carries no text that would contradict it."""
    i, j, _ = _arch_box(payload, "not_measured")
    mutant = copy_of(payload, tmp_path, "arch-unmeasured")
    _mutate(mutant, "architecture.json",
            lambda d: d["diagrams"][i]["boxes"][j].__setitem__("status", "validated_in_part"))
    expect_killed(mutant, ARCH_ARM, "no citable TRUE verdict")


def test_an_inconclusive_only_box_may_not_be_painted_as_validated(payload, tmp_path):
    """An INCONCLUSIVE verdict licenses no amendment to this study's own document, so it cannot colour
    somebody else's component green either. The mutant is the promotion a reader would never see: the
    cases behind the box do not change, only the one word that decides its colour."""
    i, j, _ = _arch_box(payload, "not_established")
    mutant = copy_of(payload, tmp_path, "arch-inconclusive")
    _mutate(mutant, "architecture.json",
            lambda d: d["diagrams"][i]["boxes"][j].__setitem__("status", "validated_in_part"))
    expect_killed(mutant, ARCH_ARM, "INCONCLUSIVE support only")


def test_a_box_citing_a_case_outside_the_register_fails_the_publish(payload, tmp_path):
    """The topology is authored by hand, so a case id is typed by a human at least once. A typo that
    lands on no register row must fail rather than render as a box with one unresolvable link."""
    i, j, box = _arch_box(payload, "contested")
    mutant = copy_of(payload, tmp_path, "arch-ghost")
    _mutate(mutant, "architecture.json",
            lambda d: d["diagrams"][i]["boxes"][j]["cases"].append(
                dict(box["cases"][0], case="F99-1")))
    expect_killed(mutant, ARCH_ARM, "absent from census.json")


def test_a_case_on_no_diagram_and_in_no_exclusion_list_fails_the_publish(payload, tmp_path):
    """Coverage in the direction that hides work: drop one exclusion entry and the case is simply not
    on the page — invisible, with nothing anywhere saying it was left out (`feedback_unnumbered_is_
    uncounted`). The count on the coverage line would still read as a total."""
    arch = json.loads((payload / "architecture.json").read_text(encoding="utf-8"))
    assert arch["unplaced_cases"], "no case is excluded, so this arm would be vacuous"
    mutant = copy_of(payload, tmp_path, "arch-coverage")
    _mutate(mutant, "architecture.json", lambda d: d["unplaced_cases"].pop(0))
    expect_killed(mutant, ARCH_ARM, "appear on no diagram and in no exclusion list")


def test_a_case_both_placed_and_excluded_fails_the_publish(payload, tmp_path):
    """The other direction, and the one a subset check would miss: a case counted twice makes the
    coverage line add up while the page says both that the case was examined and that it was left out."""
    i, j, box = _arch_box(payload, "contested")
    placed = box["cases"][0]["case"]
    mutant = copy_of(payload, tmp_path, "arch-overlap")
    _mutate(mutant, "architecture.json",
            lambda d: d["unplaced_cases"].append(
                dict(d["unplaced_cases"][0], case=placed)))
    expect_killed(mutant, ARCH_ARM, "appear in both")


def test_an_empty_non_colouring_set_cannot_report_clean(payload, tmp_path):
    """The licence checks are subtraction: a case colours a box unless a restriction withdraws it. If
    the payload stops carrying the restriction set, every check above still runs and every one of them
    passes — a NEVER_CITE case would read as ordinary support. So the emptiness is itself a failure,
    not a permissive default (`feedback_vacuous_test_check`)."""
    mutant = copy_of(payload, tmp_path, "arch-nonco")
    _mutate(mutant, "architecture.json",
            lambda d: d.__setitem__("non_colouring_restrictions", []))
    expect_killed(mutant, ARCH_ARM, "declares no non-colouring restriction set")


def test_a_box_status_with_no_stylesheet_rule_fails_the_publish(payload, tmp_path):
    """`contested` is the token whose unstyled reading is wrong in the dangerous direction, and it is
    the one status word this vocabulary does not share with the audit page's — so a kill here is
    attributable to the diagram arm rather than to the control inventory's."""
    dist = tmp_path / "dist-arch"
    shutil.copytree(DIST, dist)
    sheets = sorted((dist / "assets").glob("*.css"))
    assert sheets, "the built dist carries no stylesheet, so this arm would be vacuous"
    changed = 0
    for sheet in sheets:
        before = sheet.read_text(encoding="utf-8")
        # Renamed, not deleted: the rule stays visible in the file, so only a whole-token match kills it.
        after = before.replace(".st-contested", ".st-contested-box")
        if after != before:
            sheet.write_text(after, encoding="utf-8")
            changed += 1
    assert changed, "the rule under test is not in the built stylesheet at all"
    proc = run_gate(payload, dist)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert f"[{ARCH_ARM}]" in body, body[-2000:]
    assert "st-contested" in body


def test_a_dist_with_no_stylesheet_cannot_report_clean(payload, tmp_path):
    """A missing check is not a pass (`feedback_guard_exit_codes`): rc 2, not rc 0."""
    dist = tmp_path / "dist-nocss"
    shutil.copytree(DIST, dist)
    removed = [p for p in sorted((dist / "assets").glob("*.css"))]
    assert removed
    for p in removed:
        p.unlink()
    proc = run_gate(payload, dist)
    assert proc.returncode == 2, f"exited {proc.returncode}; a gate that cannot run must not pass"
