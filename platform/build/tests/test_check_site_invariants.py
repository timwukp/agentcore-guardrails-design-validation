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

A fourth group was added on 2026-08-20 with the Chinese edition: the pass-rate denial in both languages
and `both_languages_shipped`. Those are here rather than in the one-off exercise because the properties
are about a BUILD STEP rather than about a claim in a payload file — a tree-shaken dictionary or a stale
`dist/` is invisible to every check that reads the source — and because the one guard that reads bytes
is the one that keeps finding the phrase in places that are not sentences.

A fifth group arrived on 2026-08-22 with the authored caveats and the translation ratchet, and a sixth
with the palette (arm 18). The palette group is here for the sharpest version of the reason: that
property was false in served bytes for the whole life of the site while every structural check passed.
`--v-inconclusive` had a class token, a rule that reached the badge and a contrast ratio clearing AA,
and it was still this stylesheet's own de-emphasis colour — a defect measurable only in the colour
itself, and invisible to anything reading the source, because the source is where the wrong colour is
written.

The remaining arms (typed totals, figure bytes, seals) are left to the one-off exercise recorded in the
gate's own docstring. That is a stated limit, not an oversight — and the limit is where the next
extension goes, not a line to stop reading at.

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
import re
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


def run_gate(payload: Path, dist: Path = DIST,
             census_dir: Path | None = None) -> subprocess.CompletedProcess:
    # `census_dir` is passed only by the tests that mutate the LEDGER rather than the payload. The
    # untranslated ceiling counts payload paths a browser census listed, and a payload mutation can only
    # ever translate one of those, never add one — so without a second census directory the upward half
    # of that ratchet would be asserted in the gate and demonstrated nowhere.
    cmd = [sys.executable, str(GATE), "--payload", str(payload), "--dist", str(dist), "--verbose"]
    if census_dir is not None:
        cmd += ["--census-dir", str(census_dir)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)


def copy_of(payload: Path, tmp_path: Path, tag: str) -> Path:
    dest = tmp_path / f"payload-{tag}"
    shutil.copytree(payload, dest)
    return dest


def copy_dist(dist: Path, out: Path) -> Path:
    """Copy a built `dist/` for mutation, WITHOUT `data`.

    `data` is a symlink to the payload that `csp_preview.py` expects a developer to create, and
    `copytree` follows symlinks by default. Following it copied the whole ~7 MB payload into every
    dist mutant's temp directory — and raised `shutil.Error` outright the moment the link dangled,
    which is a test that fails without reaching the gate at all. The gate reads only `assets/*.js` and
    `assets/*.css` from `--dist`, so the payload has no business in the copy: it arrives by
    `--payload`.
    """
    shutil.copytree(dist, out, ignore=shutil.ignore_patterns("data"))
    return out


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


def expect_killed(payload: Path, arm: str, phrase: str, census_dir: Path | None = None) -> None:
    proc = run_gate(payload, census_dir=census_dir)
    assert proc.returncode == 1, (f"the gate exited {proc.returncode}, so the mutant survived"
                                  f"\n{(proc.stdout + proc.stderr)[-2000:]}")
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
    dist = copy_dist(DIST, tmp_path / "dist")
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
    dist = copy_dist(DIST, tmp_path / "dist")
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


def _mutate_css(dist: Path, tag: str, tmp_path: Path, old: str, new: str) -> Path:
    """Copy `dist` and rewrite one substring in every stylesheet, asserting the edit landed.

    Separate from `_mutate` because a stylesheet is not JSON and is not in `MANIFEST.json`'s
    `outputs_sha256` — the manifest covers the payload, and `dist/` is checked as served bytes.
    """
    out = copy_dist(dist, tmp_path / f"dist-{tag}")
    sheets = sorted((out / "assets").glob("*.css"))
    assert sheets, "the built dist carries no stylesheet, so this arm would be vacuous"
    changed = 0
    for sheet in sheets:
        before = sheet.read_text(encoding="utf-8")
        after = before.replace(old, new)
        if after != before:
            sheet.write_text(after, encoding="utf-8")
            changed += 1
    assert changed, f"{old!r} is not in the built stylesheet, so this arm would prove nothing"
    return out


def test_a_box_status_with_no_stylesheet_rule_fails_the_publish(payload, tmp_path):
    """`contested` is the token whose unstyled reading is wrong in the dangerous direction, and it is
    the one status word this vocabulary does not share with the audit page's — so a kill here is
    attributable to the diagram arm rather than to the control inventory's.

    Renamed, not deleted: the rule stays visible in the file, so only a whole-token match kills it."""
    dist = _mutate_css(DIST, "arch", tmp_path, ".st-contested", ".st-contested-box")
    proc = run_gate(payload, dist)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert f"[{ARCH_ARM}]" in body, body[-2000:]
    assert "st-contested" in body


# The two arms below are the ones the 2026-08-20 defect got past. Every status token WAS in the
# stylesheet; the boxes were slate anyway, because `.archbox` is a later single-class rule that set
# `border` outright. The property that had to become checkable is not "the rule exists" but "the rule
# reaches the box", and it is asserted as two halves — each half alone permits a monochrome diagram.

def test_a_status_that_does_not_publish_its_colour_fails_the_publish(payload, tmp_path):
    """`--st` removed from one status rule: the rule still declares a colour, and the token check above
    still passes, so a kill here is attributable to the cascade check and to nothing else."""
    dist = _mutate_css(DIST, "novar", tmp_path,
                       ".st-contested{--st:var(--v-false);", ".st-contested{")
    proc = run_gate(payload, dist)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert f"[{ARCH_ARM}]" in body, body[-2000:]
    assert "without publishing it as `--st`" in body, body[-2000:]
    assert "st-contested" in body, body[-2000:]


def test_a_box_border_not_taken_from_the_status_fails_the_publish(payload, tmp_path):
    """The other half: every status publishes `--st` and the box ignores it. This is the exact shape of
    the defect that shipped — a hardcoded border on the surface rule — so it must not survive."""
    dist = _mutate_css(DIST, "hardborder", tmp_path,
                       "border:2px var(--st-style,solid) var(--st,var(--border-strong))",
                       "border:2px solid var(--border-strong)")
    proc = run_gate(payload, dist)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert f"[{ARCH_ARM}]" in body, body[-2000:]
    assert "does not take its border colour from `--st`" in body, body[-2000:]


def test_a_dist_with_no_stylesheet_cannot_report_clean(payload, tmp_path):
    """A missing check is not a pass (`feedback_guard_exit_codes`): rc 2, not rc 0."""
    dist = copy_dist(DIST, tmp_path / "dist-nocss")
    removed = [p for p in sorted((dist / "assets").glob("*.css"))]
    assert removed
    for p in removed:
        p.unlink()
    proc = run_gate(payload, dist)
    assert proc.returncode == 2, f"exited {proc.returncode}; a gate that cannot run must not pass"


# --------------------------------------------------------------------------- the two languages
#
# The Chinese edition is checked here rather than left to the one-off exercise for one reason: the
# properties are about a BUILD STEP, not about a claim in a payload file. `strings.ts` makes a missing
# translation a type error and `i18n.test.ts` asserts what a type cannot see, so a defect in this area
# arrives between the source and the reader — a tree-shaken dictionary, a half-landed translation pass,
# a `dist/` from before the feature existed. Nothing in the source can notice any of those, and a
# hand-run check of a bundle is a memory of one bundle.
#
# `dist/` is mutated, not the payload: the arm reads served bytes, and the manifest does not cover them.

LOCALE_ARM = "both_languages_shipped"
RATE_ARM = "no_pass_rate"


def _mutate_js(dist: Path, tag: str, tmp_path: Path, edit) -> Path:
    """Copy `dist` and rewrite every JS bundle through `edit`, asserting the edit landed.

    `edit` takes and returns text rather than being an (old, new) pair because two of the mutants below
    are not substring swaps: thinning the dictionary has to keep the sentences the OTHER arm checks, or
    it would be killed by `no_pass_rate` and prove nothing about the floor it is aimed at
    (`feedback_probe_must_reach_the_code` applies to which arm the probe reaches, not only to whether
    the bytes changed).
    """
    out = copy_dist(dist, tmp_path / f"dist-{tag}")
    bundles = sorted((out / "assets").glob("*.js"))
    assert bundles, "the built dist carries no bundle, so this arm would be vacuous"
    changed = 0
    for bundle in bundles:
        before = bundle.read_text(encoding="utf-8")
        after = edit(before)
        if after != before:
            bundle.write_text(after, encoding="utf-8")
            changed += 1
    assert changed, f"the {tag} mutation changed no bytes, so the gate never saw it"
    return out


def expect_dist_killed(payload: Path, dist: Path, arm: str, phrase: str) -> None:
    proc = run_gate(payload, dist)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert f"[{arm}]" in body, f"killed by some other arm, not {arm}:\n{body[-2000:]}"
    assert phrase in body, f"{arm} fired but not for the reason under test:\n{body[-2000:]}"


def test_a_chinese_page_that_states_a_pass_rate_fails_the_publish(payload, tmp_path):
    """The negation removed and the term left standing: 沒有通過率 -> 通過率.

    This is the mutant that matters most, because the English half of the arm still passes — all four
    English sentences remain denials — so the page would ship asserting in Chinese exactly what it
    denies in English, and only the Chinese half of the rule can see it."""
    dist = _mutate_js(DIST, "zh-asserts", tmp_path, lambda s: s.replace("沒有通過率", "通過率"))
    expect_dist_killed(payload, dist, RATE_ARM, "are not immediately preceded by")


def test_the_chinese_denial_deleted_altogether_fails_the_publish(payload, tmp_path):
    """The likelier accident, and the one a per-occurrence check cannot catch: the term removed rather
    than un-negated, so there is no occurrence left to test and every assertion about occurrences
    passes vacuously. Only the COUNT, derived once per language, notices
    (`feedback_two_numbers_two_claims`)."""
    dist = _mutate_js(DIST, "zh-silent", tmp_path, lambda s: s.replace("沒有通過率", "沒有"))
    expect_dist_killed(payload, dist, RATE_ARM, "English denial(s) but 0 Chinese")


def test_a_dictionary_key_spelling_the_phrase_fails_the_publish(payload, tmp_path):
    """The real 2026-08-20 collision, pinned. `ovw.noPassRate` was a KEY, not a sentence, and the arm
    reads bytes — so the gate failed on a name. It was renamed rather than the rule widened to excuse a
    camelCase shape, and the diagnostic that says which of the two happened is asserted here, because a
    confusing failure message is how a guard gets a `# noqa` instead of a fix."""
    dist = _mutate_js(DIST, "keyname", tmp_path, lambda s: s.replace("ovw.noRatio", "ovw.noPassRate"))
    expect_dist_killed(payload, dist, RATE_ARM, "camelCase identifiers")


def test_a_bundle_with_no_locale_tag_fails_the_publish(payload, tmp_path):
    """Renamed, not deleted: `zh-Hant` is a real tag and the toggle would still render two buttons, so
    a kill here is attributable to the tag this platform actually ships under and to nothing else."""
    dist = _mutate_js(DIST, "notag", tmp_path, lambda s: s.replace("zh-TW", "zh-Hant"))
    expect_dist_killed(payload, dist, LOCALE_ARM, "does not appear as a string literal")


def test_a_bundle_with_no_language_toggle_label_fails_the_publish(payload, tmp_path):
    """The whole dictionary can be present and unreachable. The toggle's label is written in the
    language it switches TO, so it is the one string a reader who cannot read the page must find."""
    dist = _mutate_js(DIST, "nolabel", tmp_path, lambda s: s.replace("中文", "ZH"))
    expect_dist_killed(payload, dist, LOCALE_ARM, "language toggle's own label")


CJK_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿0-9A-Za-z，。、：；「」『』（）？！—…·　\s]*"
                     r"[㐀-䶿一-鿿豈-﫿]"
                     r"[㐀-䶿一-鿿豈-﫿0-9A-Za-z，。、：；「」『』（）？！—…·　\s]*")


def test_a_half_shipped_dictionary_fails_the_publish(payload, tmp_path):
    """The failure this floor exists for: a bundle carrying SOME Chinese.

    Every other check in the arm still passes — the tag is there, the toggle label is there, both
    pass-rate denials are there — and the page renders a button saying 中文 above English headings,
    which is the state in which a reader cannot tell a missing translation from a block quoted verbatim
    on purpose. The sentences the other arm counts are preserved deliberately: a mutant killed by
    `no_pass_rate` would prove nothing about this floor."""
    keep = 100

    def thin(text: str) -> str:
        seen: dict[str, int] = {}

        def sub(m) -> str:
            run = m.group(0)
            if "通過率" in run or "中文" in run:
                return run
            key = run.strip()
            if key not in seen:
                seen[key] = len(seen)
            return run if seen[key] < keep else "x"

        return CJK_RUN.sub(sub, text)

    dist = _mutate_js(DIST, "thin", tmp_path, thin)
    expect_dist_killed(payload, dist, LOCALE_ARM, "under the floor of")


def test_a_bundle_that_stopped_marking_verbatim_english_fails_the_publish(payload, tmp_path):
    """`lang="en"` is the verbatim rule where it has effects rather than where it is described: it picks
    the Latin font stack over the CJK one and tells a screen reader which phonology to use. Stripped of
    it, an artifact's own sealed sentence is pronounced as Chinese. The prop is RENAMED so the values
    stay in the bundle — only the marking is gone, which is the defect. `xlang` rather than a deleted
    prop for the reason the CSS mutants are renames too: it is the mutant a substring match survives,
    and it is what made the arm match a whole property name."""
    dist = _mutate_js(DIST, "nolang", tmp_path, lambda s: s.replace("lang:`en`", "xlang:`en`"))
    expect_dist_killed(payload, dist, LOCALE_ARM, 'carry lang="en"')


def test_a_stylesheet_with_no_verbatim_rule_fails_the_publish(payload, tmp_path):
    """Renamed rather than deleted, like the status-token mutant above: the rule stays in the file and
    only a whole-token match kills it. Without it a quoted English block is styled as this platform's
    own prose, and a sealed quotation reads as a translation somebody forgot."""
    dist = _mutate_css(DIST, "noverbatim", tmp_path, ".verbatim", ".verbatim-block")
    expect_dist_killed(payload, dist, LOCALE_ARM, "no `.verbatim` rule")


# --------------------------------------------------------------------------- the authored caveats
#
# 49 case pages carry a bound that no run produced: `platform/curation/caveats.yaml` was written against
# each case's own record, because the record itself states no limits. Publishing that is defensible;
# publishing it UNMARKED is the substitution this platform exists to refuse, because a later reader's
# reasoning would then reach the reader at the evidentiary strength of a measurement.
#
# `check_caveats.py` and its own test file cover the authored FILE. These mutants cover what happens
# after that gate passes — and the reason they are committed rather than left to a one-off exercise is
# that this harness has already demonstrated the failure mode: on 2026-08-22 three tests in this file
# went red because `site/dist` predated the feature while the freshly-built payload carried the prose.
# That is precisely a stale-`dist/` defect, arriving by accident, caught by the arm. A one-off exercise
# would have recorded a memory of one bundle instead (`feedback_test_suite_over_memory`).
#
# Both layers get mutated: the payload for the provenance and shadowing rules, `dist/` for the two that
# are about served bytes.

CAVEAT_ARM = "authored_caveats_are_marked"


def _case_with_authored(payload: Path) -> tuple[str, dict]:
    """A case page carrying an authored caveat, chosen from the payload rather than named here.

    Named victims go vacuous the day that case's record acquires its own sentence and the builder stops
    emitting an authored one for it (`feedback_scope_as_namelist`), and a vacuous mutant is a test that
    passes by mutating nothing.
    """
    files = sorted((payload / "cases").glob("*.json"))
    assert files, "the payload holds no case pages"
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(d.get("authored_caveat"), dict):
            return f"cases/{f.name}", d
    pytest.fail("no case page carries an authored caveat, so every mutant below would be vacuous")


def test_a_published_authored_count_no_page_supports_fails_the_publish(payload, tmp_path):
    """The count and the pages are two claims (`feedback_two_numbers_two_claims`). A figure a reader can
    quote — "49 cases carry an authored bound" — must be the number of pages that actually do, and the
    two are derived from the same build precisely so that a drift between them is a publish failure
    rather than a discrepancy nobody recomputes."""
    mutant = copy_of(payload, tmp_path, "caveat-count")
    _mutate(mutant, "method.json",
            lambda d: d["caveats"].__setitem__("cases_with_an_authored_caveat",
                                               d["caveats"]["cases_with_an_authored_caveat"] - 1))
    expect_killed(mutant, CAVEAT_ARM, "case page(s) actually carry one")


def test_an_authored_caveat_moved_inside_the_record_fails_the_publish(payload, tmp_path):
    """`record` is meant to be byte-identical to `results/phase1/<case>.json`, so a reader diffing the two
    finds nothing added. An authored sentence inside it makes a producer-written artifact partly
    hand-written — invisibly, and to every downstream consumer that trusts `record` at once.

    The mutant KEEPS the top-level copy, so the count arm still passes and the kill is attributable to
    the placement rule alone."""
    rel, _ = _case_with_authored(payload)
    mutant = copy_of(payload, tmp_path, "caveat-inrecord")
    _mutate(mutant, rel, lambda d: d["record"].__setitem__("authored_caveat", d["authored_caveat"]))
    expect_killed(mutant, CAVEAT_ARM, "INSIDE `record`")


def test_an_authored_caveat_standing_where_the_record_speaks_fails_the_publish(payload, tmp_path):
    """The ceiling, and the more dangerous direction of it. `check_caveats.py` refuses this against the
    census; this arm refuses it against what SHIPPED, because the two disagree exactly when the payload
    was built from a different verdict set than the gate read — and in that state the platform's
    paraphrase would stand in the slot holding the study's own sentence."""
    rel, doc = _case_with_authored(payload)
    field = {"TRUE": "what_true_does_not_prove",
             "FALSE": "what_false_does_not_prove"}[doc["verdict"]]
    mutant = copy_of(payload, tmp_path, "caveat-shadow")
    _mutate(mutant, rel, lambda d: d["record"].__setitem__(
        field, "The record's own sentence, arriving after the authored one was already written."))
    expect_killed(mutant, CAVEAT_ARM, "carry BOTH an authored caveat")


def test_an_authored_caveat_with_no_review_status_fails_the_publish(payload, tmp_path):
    """Blanked rather than deleted, because a blank is what a half-finished authoring pass leaves. Without
    it the box renders the bound and the byline and says nothing about whether a human has ever read the
    sentence — and unreviewed prose presented without that word is prose presented as reviewed."""
    rel, _ = _case_with_authored(payload)
    mutant = copy_of(payload, tmp_path, "caveat-noreview")
    _mutate(mutant, rel, lambda d: d["authored_caveat"].__setitem__("review_status", ""))
    expect_killed(mutant, CAVEAT_ARM, "with a field missing")


def test_a_payload_that_carries_no_authored_caveat_at_all_cannot_report_clean(payload, tmp_path):
    """The vacuity guard, and the one mutant here that is not about a wrong value. Strip the prose from
    every page AND fix the published count to match, and every other check in this arm passes over an
    empty set — the state in which a feature was removed while its gate stayed green
    (`feedback_zero_file_scan_is_error`). The arm must fail on having nothing to check."""
    mutant = copy_of(payload, tmp_path, "caveat-none")
    for f in sorted((mutant / "cases").glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        if "authored_caveat" in doc:
            _mutate(mutant, f"cases/{f.name}", lambda d: d.pop("authored_caveat"))
    _mutate(mutant, "method.json",
            lambda d: d["caveats"].__setitem__("cases_with_an_authored_caveat", 0))
    expect_killed(mutant, CAVEAT_ARM, "no case payload carries an `authored_caveat`")


def test_a_stylesheet_with_no_authored_rule_fails_the_publish(payload, tmp_path):
    """Renamed, not deleted, like the other stylesheet mutants: the rule stays visible in the file and
    only a whole-token match kills it. Without it a sentence this platform wrote is styled exactly like a
    sentence the run wrote, which is the whole distinction the box exists to draw."""
    dist = _mutate_css(DIST, "noauthored", tmp_path, ".note.authored", ".note.authored-box")
    expect_dist_killed(payload, dist, CAVEAT_ARM, "no `.note.authored` rule")


def test_an_authored_rule_that_changes_nothing_visible_fails_the_publish(payload, tmp_path):
    """The mutant that matters most here, and the one the 2026-08-20 defect proves is not hypothetical:
    the class token stays in the stylesheet, the rule stays, the selector still matches — and the box
    looks identical to the record's (`feedback_class_token_is_not_a_colour`). `dashed` swapped for
    `solid` leaves a rule that declares a border colour and nothing that distinguishes the box in
    greyscale or for a reader with a colour vision deficiency, so hue is the only cue left and for some
    readers there is no cue at all."""
    dist = _mutate_css(DIST, "notdashed", tmp_path,
                       ".note.authored{border-left-style:dashed", ".note.authored{border-left-style:solid")
    expect_dist_killed(payload, dist, CAVEAT_ARM, "no rule in it declares `dashed`")


def test_a_bundle_with_no_chinese_head_sentence_fails_the_publish(payload, tmp_path):
    """The zh half, for the same reason the pass-rate denial is checked in both languages: an English-only
    marking makes the Chinese edition a different platform. A zh-TW reader would see the dashed box and
    the byline with no sentence saying the bound was not written by the run — and the English head is
    still present, so the kill is attributable to the Chinese half alone."""
    dist = _mutate_js(DIST, "nozhhead", tmp_path,
                      lambda s: s.replace("後來的讀者", "另一位讀者"))
    expect_dist_killed(payload, dist, CAVEAT_ARM, "後來的讀者")


# --------------------------------------------------------------- arm 17: authored prose is bilingual
#
# Added 2026-08-22, the day the site's one rule about payload prose turned out to be false for a third of
# it. Every payload string rendered `lang="en"` under a banner telling a Chinese reader that the English
# was quoted evidence; a browser census of both locales over every route measured 1,946 strings a reader
# reached that morning, of which 310 were this platform's own sentences — the denominator definitions, the
# promises about the reader's AWS account, the sentences saying what each diagram colour means. Those two
# numbers are the falsifying run (`rendered-surfaces-20260822T081918Z.json`); the newest run says 1,958
# and 316, and neither pair is asserted anywhere — see `arm_authored_prose_is_bilingual`'s docstring for
# why the ceiling is the only one a gate reads.
#
# The repair is a SHAPE (`{en, zh}` for authored, a bare string for a sealed quotation), so the mutants
# here are shape mutants: a half blanked, a half copied, the shape deleted wholesale. The last two are
# ledger mutants, and they are why the gate takes `--census-dir` at all: the ceiling counts strings a
# browser census listed, and no payload edit can add one.

PROSE_ARM = "authored_prose_is_bilingual"


def _authored_paths(payload: Path) -> list[tuple[str, list]]:
    """Every `{en, zh}` value in the payload, as (file, key path) pairs."""
    found: list[tuple[str, list]] = []

    def walk(node, rel: str, keys: list) -> None:
        if isinstance(node, dict):
            if set(node) == {"en", "zh"} and all(isinstance(v, str) for v in node.values()):
                found.append((rel, keys))
                return
            for k, v in node.items():
                walk(v, rel, keys + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, rel, keys + [i])

    for f in sorted(payload.rglob("*.json")):
        walk(json.loads(f.read_text(encoding="utf-8")), f.relative_to(payload).as_posix(), [])
    return found


def _at(doc, keys: list):
    for k in keys[:-1]:
        doc = doc[k]
    return doc, keys[-1]


def _newest_census() -> Path:
    files = sorted((REPO / "platform" / "census").glob("rendered-surfaces-*.json"))
    assert files, "no rendered-surface census in the repo; the ceiling has no ledger"
    return files[-1]


def _census_dir_with(tmp_path: Path, tag: str, edit) -> Path:
    """A census directory holding one mutated copy of the repo's newest measurement.

    Written under a LATER stamp than any real census, because the gate reads the newest by name and a
    fixture that sorted earlier would leave the real measurement in force and the mutant unread — a green
    test proving nothing (`feedback_probe_must_reach_the_code`).
    """
    out = tmp_path / f"census-{tag}"
    out.mkdir()
    doc = json.loads(_newest_census().read_text(encoding="utf-8"))
    edit(doc)
    (out / "rendered-surfaces-29991231T235959Z.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return out


def _first_bare_backlog_row(payload: Path) -> tuple[dict, str, list]:
    """A census backlog row whose first payload path still resolves to a bare string, with that path
    split into (file, keys). The mutants below need a real untranslated surface rather than a made-up
    one: a path this payload does not have would be killed by the unresolved check instead."""
    doc = json.loads(_newest_census().read_text(encoding="utf-8"))
    for row in doc.get("backlog") or []:
        for path in row.get("payload_paths") or []:
            segs = path.split("/")
            for i in range(len(segs), 0, -1):
                if payload.joinpath(*segs[:i]).is_file():
                    rel = "/".join(segs[:i])
                    keys: list = []
                    for seg in re.findall(r"[^/\[\]]+|\[\d+\]", "/".join(segs[i:])):
                        keys.append(int(seg[1:-1]) if seg.startswith("[") else seg)
                    node = json.loads((payload / rel).read_text(encoding="utf-8"))
                    try:
                        holder, last = _at(node, keys)
                        if isinstance(holder[last], str):
                            return row, rel, keys
                    except (KeyError, IndexError, TypeError):
                        pass
                    break
    raise AssertionError("no backlog row resolves to a bare string in this payload")


def test_the_bilingual_arm_no_mutant_control(payload: Path):
    """The control for the five mutants below, and it asserts more than rc 0: it asserts the arm LOOKED.
    An arm whose census went missing exits 2, and an arm whose payload happened to carry no `{en, zh}`
    value at all would report zero malformed ones — both of which are what a passing run looks like from
    the outside."""
    proc = run_gate(payload)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:]
    assert f"[{PROSE_ARM}]" in proc.stdout, "the arm produced no note, so it may not have run at all"
    assert "backlog string(s)" in proc.stdout and "value(s) translated" in proc.stdout
    assert len(_authored_paths(payload)) >= 40, "the payload carries almost no authored prose objects"


def test_a_blank_chinese_half_fails_the_publish(payload, tmp_path):
    """The defect the shape exists to prevent. A blank `zh` renders as a gap, and a gap reads as a
    finished sentence saying something else — which is worse than the English it replaced, because the
    reader cannot tell that anything is missing."""
    mutant = copy_of(payload, tmp_path, "prose-blank")
    rel, keys = next((r, k) for r, k in _authored_paths(mutant) if r == "audit.json")

    def edit(doc):
        holder, last = _at(doc, keys)
        holder[last]["zh"] = "   "

    _mutate(mutant, rel, edit)
    # The phrase names the LANGUAGE, not just the state: "is blank" alone would also match a
    # message about a missing English half, i.e. a kill for the mirror-image defect.
    expect_killed(mutant, PROSE_ARM, "zh is blank")


def test_english_copied_into_the_chinese_half_fails_the_publish(payload, tmp_path):
    """The subtler mutant, and the one a structural check alone would pass: both halves present, both
    non-blank, both strings. The reader gets English, and the string leaves the backlog — so the
    published number improves by exactly the amount of work not done."""
    mutant = copy_of(payload, tmp_path, "prose-copied")
    rel, keys = next((r, k) for r, k in _authored_paths(mutant) if r == "audit.json")

    def edit(doc):
        holder, last = _at(doc, keys)
        holder[last]["zh"] = holder[last]["en"]

    _mutate(mutant, rel, edit)
    expect_killed(mutant, PROSE_ARM, "both halves are the same text")


def test_deleting_the_shape_everywhere_cannot_report_clean(payload, tmp_path):
    """The vacuity guard. Collapse every `{en, zh}` in `architecture.json` back to its English half and
    the malformed count is zero, because there is nothing left to be malformed
    (`feedback_zero_file_scan_is_error`). The count is asserted against a floor rather than assumed to be
    non-trivial."""
    mutant = copy_of(payload, tmp_path, "prose-deleted")
    keyed = [k for r, k in _authored_paths(mutant) if r == "architecture.json"]
    assert len(keyed) >= 16, f"only {len(keyed)} objects in architecture.json; the floor cannot be crossed"

    def edit(doc):
        for keys in keyed:
            holder, last = _at(doc, keys)
            holder[last] = holder[last]["en"]

    _mutate(mutant, "architecture.json", edit)
    expect_killed(mutant, PROSE_ARM, "below the floor of")


def test_a_translation_written_without_lowering_the_ceiling_fails(payload, tmp_path):
    """The downward half of the ratchet, which exists because slack is where the next regression hides.
    Translate one string the census listed and the count falls below the published ceiling; the gate
    fails and names the number to write. A ceiling left above the measurement would absorb the next
    untranslated surface silently."""
    mutant = copy_of(payload, tmp_path, "prose-below")
    _row, rel, keys = _first_bare_backlog_row(mutant)

    def edit(doc):
        holder, last = _at(doc, keys)
        holder[last] = {"en": holder[last], "zh": "這是一個為了測試而寫的中文句子，內容與英文不同。"}

    _mutate(mutant, rel, edit)
    expect_killed(mutant, PROSE_ARM, "without lowering it")


def test_a_new_untranslated_surface_fails_the_publish(payload, tmp_path):
    """The upward half, mutated through the LEDGER because nothing else can produce it: the count is over
    paths a census listed, so a payload edit can only ever translate one. A census listing one more
    untranslated string than the ceiling allows is exactly what a new authored surface looks like the
    next time somebody runs the browser walk."""
    row, rel, keys = _first_bare_backlog_row(payload)
    twin = dict(row)
    twin["text"] = "a second untranslated sentence the census found on this build"
    twin["payload_paths"] = list(row.get("payload_paths") or [])
    census = _census_dir_with(tmp_path, "over", lambda d: d["backlog"].append(twin))
    # Same payload, unmutated: the mutation is entirely in the measurement, so the kill is attributable
    # to the ceiling rather than to anything the builder emitted.
    expect_killed(payload, PROSE_ARM, "above the ceiling of", census_dir=census)


def test_a_ledger_naming_a_path_this_payload_does_not_have_fails(payload, tmp_path):
    """A stale ledger must not be counted as progress. The ceiling is a count over the census's own
    paths, so a census taken against a different payload measures a different thing and reads as
    improvement (`feedback_abort_hides_coverage` — count the lines, do not drop them). The arm fails
    rather than skipping the paths it cannot follow."""
    def edit(doc):
        doc["backlog"][0]["payload_paths"] = ["denominators.json/registered/a_field_that_never_existed"]

    census = _census_dir_with(tmp_path, "stale", edit)
    expect_killed(payload, PROSE_ARM, "do not exist in this payload", census_dir=census)


# --- arm 18: the verdict palette
#
# Here rather than in the one-off exercise for the reason the two arms above it are: the property is
# about SERVED BYTES, and it was already false in served bytes for the whole life of the site. Every
# structural check passed while `--v-inconclusive` was drawn in this stylesheet's own de-emphasis colour
# — the class token was present, the rule reached the badge, the contrast cleared AA at 4.66:1 — and the
# defect was visible only as a measurement of the colour itself. Nothing that reads the source can see
# it either, because the source is where the wrong colour is written.
#
# All six mutants are edits to a COPIED `dist/`, like arms 14/15's, since a stylesheet is not in the
# payload manifest.

PALETTE_ARM = "verdict_palette_is_readable"


def expect_css_killed(payload: Path, dist: Path, phrase: str) -> None:
    proc = run_gate(payload, dist)
    assert proc.returncode == 1, f"the gate exited {proc.returncode}, so the mutant survived"
    body = proc.stdout + proc.stderr
    assert f"[{PALETTE_ARM}]" in body, body[-2000:]
    assert phrase in body, body[-2000:]


def test_the_palette_arm_no_mutant_control(payload: Path):
    """An unmutated `dist/` passes, and the arm produced its measurements rather than skipping — a
    control that only checks rc 0 cannot tell a passing arm from an absent one."""
    proc = run_gate(payload)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:]
    notes = [line for line in proc.stdout.splitlines() if f"[{PALETTE_ARM}]" in line]
    assert len(notes) >= 6, notes
    assert any("contrast" in n for n in notes), notes
    assert any("chroma" in n for n in notes), notes
    assert any("ΔE" in n for n in notes), notes


def test_the_verdict_colour_that_shipped_as_a_grey_fails_the_publish(payload, tmp_path):
    """The exact colour this site served until 2026-08-22, restored. It clears AA on all three
    backgrounds, so contrast cannot be what kills it: at Lab chroma 10.4 it is the chroma of `--fg-dim`
    and ΔE 5 from `--fg-faint`, i.e. the verdict for 20 of 91 outcomes drawn in the colour that means
    "this matters less"."""
    dist = _mutate_css(DIST, "grey-inconclusive", tmp_path,
                       "--v-inconclusive:#d086ab", "--v-inconclusive:#7c8798")
    expect_css_killed(payload, dist, "Lab chroma 10.4")


def test_a_verdict_colour_under_aa_fails_the_publish(payload, tmp_path):
    """Contrast, held against the worst of the three page backgrounds rather than the best. #6d5fa8 is
    the same violet at a lower lightness: measured chroma 43.9 and ΔE 37 or more from every other colour
    in the sheet, so the chroma and separation halves stay green and the kill (3.11:1, worst background)
    is attributable to SC 1.4.3 alone."""
    dist = _mutate_css(DIST, "dim-recorded", tmp_path, "--v-recorded:#8a7bd0", "--v-recorded:#6d5fa8")
    expect_css_killed(payload, dist, "WCAG 2.1 SC 1.4.3")


def test_two_verdicts_a_reader_cannot_tell_apart_fail_the_publish(payload, tmp_path):
    """Separation. RECORDED moved next to INCONCLUSIVE: both stay bright, both stay chromatic, both clear
    AA — and two of the four outcomes become one category on screen."""
    dist = _mutate_css(DIST, "collided", tmp_path, "--v-recorded:#8a7bd0", "--v-recorded:#d18cae")
    expect_css_killed(payload, dist, "under 15")


def test_a_verdict_with_no_stylesheet_rule_fails_the_publish(payload, tmp_path):
    """Renamed, not deleted, so only a whole-token match kills it: `.v-INCONCLUSIVE` is still in the file
    as `.v-INCONCLUSIVE-badge`, and a substring test would call the renamed-away rule present."""
    dist = _mutate_css(DIST, "unstyled-verdict", tmp_path, ".v-INCONCLUSIVE", ".v-INCONCLUSIVE-badge")
    expect_css_killed(payload, dist, "INCONCLUSIVE")


def test_a_verdict_colour_the_arm_cannot_parse_is_not_a_pass(payload, tmp_path):
    """A colour rewritten in a form this arm does not read must FAIL, not drop silently out of every
    floor. `rgb()` is legal CSS and renders identically, which is what makes the silent version of this
    the dangerous one: the gate would report clean over a palette it never measured."""
    dist = _mutate_css(DIST, "rgb-verdict", tmp_path,
                       "--v-inconclusive:#d086ab", "--v-inconclusive:rgb(208,134,171)")
    expect_css_killed(payload, dist, "is not declared as a hex colour")


def test_a_stylesheet_missing_a_page_background_cannot_report_clean(payload, tmp_path):
    """The contrast floor is meaningless without the surfaces the text is drawn on, so a sheet declaring
    fewer than three backgrounds is rc 2 — a gate that cannot run must not report clean."""
    dist = _mutate_css(DIST, "no-inset", tmp_path, "--bg-inset:#0b0e13;", "")
    proc = run_gate(payload, dist)
    assert proc.returncode == 2, f"exited {proc.returncode}; a gate that cannot run must not pass"
    assert "fewer than three page backgrounds" in (proc.stdout + proc.stderr)


def _mutate_dist_file(dist: Path, tag: str, tmp_path: Path, rel: str, edit) -> Path:
    """Copy `dist` and rewrite ONE named file through `edit`, asserting the edit landed.

    `_mutate_css` and `_mutate_js` each rewrite a whole class of files; the icon and the served markup
    are single files, and a mutant that silently missed either would leave the gate's clean exit proving
    nothing (`feedback_probe_must_reach_the_code`). `edit` may return the text unchanged only if the file
    is being removed, which the callers do themselves.
    """
    out = copy_dist(dist, tmp_path / f"dist-{tag}")
    target = out / rel
    assert target.is_file(), f"{rel} is not in the built dist, so this mutant would prove nothing"
    before = target.read_text(encoding="utf-8")
    after = edit(before)
    assert after != before, f"the mutation did not change {rel}"
    target.write_text(after, encoding="utf-8")
    return out


def test_a_verdict_colour_typed_into_a_component_fails_the_publish(payload, tmp_path):
    """Property 4, mutated into the exact shape it was repaired from: a `stroke` on the series tick,
    written as a hex. The stylesheet is unchanged and every floor above still passes, so the kill is
    attributable to the second-source check alone."""
    dist = _mutate_js(DIST, "typed-hex", tmp_path,
                      lambda text: text.replace("className:`tick`,", "className:`tick`,stroke:`#2fa19b`,", 1))
    expect_css_killed(payload, dist, "hex literal in the JS bundle")


def test_an_icon_drawn_in_a_colour_the_stylesheet_does_not_declare_fails(payload, tmp_path):
    """The icon repeats the palette, and this is the check that licenses the repetition. #7c8798 is the
    grey INCONCLUSIVE shipped as until 2026-08-22 — i.e. the mutant is an icon left behind by the change
    the rest of this arm was written for."""
    dist = _mutate_dist_file(DIST, "stale-icon", tmp_path, "favicon.svg",
                             lambda text: text.replace('fill="#d086ab"', 'fill="#7c8798"'))
    expect_css_killed(payload, dist, "which the stylesheet does not declare")


def test_a_served_page_with_no_icon_link_fails_the_publish(payload, tmp_path):
    """The original defect: no icon at all, one console error on every first page load. A console with an
    expected error in it is a console nobody reads, which is where the next real error goes unread."""
    dist = _mutate_dist_file(DIST, "no-icon", tmp_path, "index.html",
                             lambda text: re.sub(r"""<link[^>]*rel="icon"[^>]*>""", "", text))
    expect_css_killed(payload, dist, "<link rel=icon> element(s)")


def test_an_absolute_icon_href_fails_the_publish(payload, tmp_path):
    """`/favicon.svg` is the spelling every tutorial gives and it 404s under the `v/<stamp>/` prefix this
    site is actually published at. The file is present and correct; only the path is wrong, which is the
    version of this defect that looks fine in a dev server at the root."""
    dist = _mutate_dist_file(DIST, "abs-icon", tmp_path, "index.html",
                             lambda text: text.replace('href="./favicon.svg"', 'href="/favicon.svg"'))
    expect_css_killed(payload, dist, "404s under the `v/<stamp>/` prefix")


def test_an_icon_link_pointing_at_nothing_fails_the_publish(payload, tmp_path):
    """The link survives a file that does not: a `public/` cleared by a bad build, or an icon renamed
    without the markup following. The reader gets the same console error as having no link at all."""
    dist = copy_dist(DIST, tmp_path / "dist-icon-missing")
    icon = dist / "favicon.svg"
    assert icon.is_file(), "the built dist carries no favicon, so this mutant would prove nothing"
    icon.unlink()
    expect_css_killed(payload, dist, "and no such file is in")
