"""Tests for build_v13_candidates.py — the amendment register. Offline, $0.

What is at stake
---------------
This register decides which sentences of v1.2 get rewritten in v1.3. Two failure
directions, and they are not symmetric:

  * **Missing a site** is the failure the register exists to prevent, and it is silent. A
    claim amended at 1 of 9 sites reads as amended; the other 8 keep asserting the refuted
    thing. The measured version of this mistake is on the record — remembered wording once
    located 6 of 10 sites (`feedback_grep_the_claim_not_the_phrasing`). So the arms below
    require the generator to *refuse* every way a site list can quietly shrink: an empty
    expansion, a typo'd case ID, a truncated triage, a merge group that lost members.
  * **Over-including** is loud but corrosive: it hands an editor sentences nobody decided
    to change, and the register's counts stop meaning anything. That failure was real —
    the first version resolved V13-01 to 19 sites, 9 of them §3.1 bullets about the
    gateway hop in general, pulled in because F1-3 happens to test them too.

`test_promotion_cannot_invent_a_site` and `test_named_claim_ids_need_a_rationale` are the
arms that keep the fix to the second failure from reopening the first: the narrowing rule
comes with two documented overrides (`claim_ids`, `also_sites`), and an override with no
checks is just the hand-written list again.

Every arm mutates the real `claims/triage.csv` (copied to tmp) rather than a synthetic
one, per `feedback_verify_against_real_artifact`: the triage's shape — which columns are
empty for which classes — is exactly what the expanders depend on.
"""

from __future__ import annotations

import csv
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_v13_candidates.py"
TRIAGE = ROOT / "claims" / "triage.csv"

_spec = importlib.util.spec_from_file_location("v13", SCRIPT)
v13 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v13)

# Snapshot the committed register at import time, before any test can regenerate it.
# Reading it inside the staleness test instead would make that test pass whenever an
# earlier test in the session had already rewritten the file — a green result that depends
# on execution order is not a check. (Found by mutation: every mutant below left the
# staleness arm passing.)
_ON_DISK_AT_IMPORT = v13.OUT.read_text(encoding="utf-8") if v13.OUT.is_file() else None


@pytest.fixture
def rows() -> list[dict]:
    return v13.load_triage()


def expand(cand: dict, rows: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    problems: list[str] = []
    sites, related = v13.expand(cand, rows, problems)
    return sites, related, problems


def base(**over) -> dict:
    """A minimal well-formed candidate; arms override one field at a time."""
    c = {
        "id": "T-01", "title": "t", "severity": v13.MISINFORMS,
        "status": "AWAITING_EXPERIMENT",
        "test_cases": [], "merge_groups": [], "claim_ids": [],
        "claim_id_rationale": "",
        "evidence": "none-yet", "finding": None, "planned_cases": ["F1-1"],
        "doc_says": "d", "observed": "o", "proposed": "p",
    }
    c.update(over)
    return c


# ---------------------------------------------------------------------------
# the register must reproduce, and must match the real triage
# ---------------------------------------------------------------------------

def test_the_generator_runs_clean_on_the_real_triage():
    """The baseline. If the shipped register is malformed, no arm below means anything."""
    p = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                       cwd=ROOT)
    assert p.returncode == 0, p.stdout + p.stderr


def test_the_register_on_disk_matches_a_fresh_generation(tmp_path):
    """A stale V13_CANDIDATES.md is worse than none: it reports counts for a triage that
    has since changed.

    Compared against the import-time snapshot and generated into a **separate directory**,
    so neither this test's own regeneration nor any earlier test's can make it pass —
    `feedback_provenance_stamp_liveness`: prove regenerability by rebuilding elsewhere.
    """
    assert _ON_DISK_AT_IMPORT is not None, "V13_CANDIDATES.md has not been generated"
    work = tmp_path / "grx"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
        ".venv*", "__pycache__", "evidence", ".git"))
    (work / "V13_CANDIDATES.md").unlink()
    p = subprocess.run([sys.executable, "build_v13_candidates.py"],
                       capture_output=True, text=True, cwd=work)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (work / "V13_CANDIDATES.md").read_text(encoding="utf-8") \
        == _ON_DISK_AT_IMPORT, (
        "V13_CANDIDATES.md is out of date with claims/triage.csv — run "
        "build_v13_candidates.py and commit the result")


def test_every_declared_reference_resolves(rows):
    """No candidate may name a case, merge group or claim id the triage does not have.

    A typo'd reference yields an empty *contribution*, which is invisible whenever some
    other expander happens to supply sites — the count still looks plausible.
    """
    for cand in v13.CANDIDATES:
        _s, _r, problems = expand(cand, rows)
        assert not problems, f"{cand['id']}: {problems}"


def test_every_candidate_resolves_to_at_least_one_site(rows):
    for cand in v13.CANDIDATES:
        sites, _r, _p = expand(cand, rows)
        assert sites, f"{cand['id']} resolves to zero sites"


# ---------------------------------------------------------------------------
# the silent-shrink failures
# ---------------------------------------------------------------------------

def test_a_candidate_cannot_list_fewer_sites_than_its_merge_group_holds(rows):
    """The central arm. A merge group IS the set of places one proposition is restated.

    If a candidate claims a merge group, every member is a site by construction — that is
    what a merge group means. Anything less is the 6-of-10 failure with a data structure
    in front of it.
    """
    for cand in v13.CANDIDATES:
        sites, _r, _p = expand(cand, rows)
        got = {r["claim_id"] for r in sites}
        for mg in cand["merge_groups"]:
            members = {r["claim_id"] for r in rows if r["merge_group"] == mg}
            assert members, f"{cand['id']}: merge group {mg} has no members"
            missing = members - got
            assert not missing, (
                f"{cand['id']} declares merge group {mg} ({len(members)} sites) but omits "
                f"{sorted(missing)} — amending the rest would leave those asserting the "
                f"refuted claim")


def test_a_truncated_triage_is_fatal_not_a_smaller_register(tmp_path):
    """A short triage.csv must abort, never generate a register with shrunken counts.

    This is `feedback_zero_file_scan_is_error` applied to rows instead of files: a scan
    that read less than it should must not report success.
    """
    work = tmp_path / "grx"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
        ".venv*", "__pycache__", "evidence", ".git"))
    tri = work / "claims" / "triage.csv"
    lines = tri.read_text(encoding="utf-8").splitlines(keepends=True)
    tri.write_text("".join(lines[:200]), encoding="utf-8")
    p = subprocess.run([sys.executable, "build_v13_candidates.py"],
                       capture_output=True, text=True, cwd=work)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "truncated triage" in p.stderr


def test_a_case_id_assigned_to_nothing_is_reported(rows):
    _s, _r, problems = expand(base(test_cases=["F99-NOPE"]), rows)
    assert any("assigned to no triage row" in x for x in problems), problems


def test_a_merge_group_that_lost_its_members_is_reported(rows):
    _s, _r, problems = expand(base(merge_groups=["M-does-not-exist"]), rows)
    assert any("matches no triage row" in x for x in problems), problems


def test_an_unknown_claim_id_is_reported(rows):
    _s, _r, problems = expand(base(claim_ids=["C-invented-001"]), rows)
    assert any("not in the triage" in x for x in problems), problems


def test_a_candidate_with_no_expander_at_all_is_reported(rows):
    problems: list[str] = []
    v13.check(base(), [], problems)
    assert any("not derived from anything" in x for x in problems), problems
    assert any("zero sites" in x for x in problems), problems


# ---------------------------------------------------------------------------
# the over-inclusion fix, and the two doors it leaves open
# ---------------------------------------------------------------------------

def test_a_shared_test_case_alone_does_not_make_a_site(rows):
    """The over-inclusion that was real.

    F1-3 touches 19 claims. V13-01 amends the missing `validationMode`, which is the
    9-member default-deny merge group; the other 10 are §3.1 bullets like "Prompt Attack
    detection (JAILBREAK, PROMPT_INJECTION, PROMPT_LEAKAGE)". Sharing an experiment is not
    sharing a fate — one test can confirm one claim and refute another.
    """
    cand = next(c for c in v13.CANDIDATES if c["id"] == "V13-01")
    sites, related, _p = expand(cand, rows)
    assert related, "the demotion path is not exercised; this arm is vacuous"
    site_ids = {r["claim_id"] for r in sites}
    for cid in ("C-s3-1-bullet-004", "C-s3-1-bullet-006", "C-s3-1-bullet-001"):
        assert cid in {r["claim_id"] for r in related}, f"{cid} should be related-only"
        assert cid not in site_ids
    # and the claim it IS about is present
    assert "C-s3-1-quote-001" in site_ids


def test_the_narrowing_did_not_demote_any_merge_group_member(rows):
    """Guards the fix against the failure it could cause.

    The demotion rule keys on merge group, so a bug in it would push real sites into
    `related`, where they read as out of scope. Nothing in any candidate's own merge
    groups may appear in its related list.
    """
    for cand in v13.CANDIDATES:
        sites, related, _p = expand(cand, rows)
        own = set(cand["merge_groups"])
        for r in related:
            assert r["merge_group"] not in own, (
                f"{cand['id']}: {r['claim_id']} is in declared merge group "
                f"{r['merge_group']} yet was filed as related-not-amended")
        assert {r["claim_id"] for r in sites}.isdisjoint(
            {r["claim_id"] for r in related}), f"{cand['id']}: a claim is in both lists"


def test_promotion_cannot_invent_a_site(rows):
    """`also_sites` reclassifies; it does not add.

    Without this, the override degenerates into the hand-written site list the whole file
    exists to replace — one exception at a time, each individually defensible.
    """
    cand = base(test_cases=["F5-7a"], merge_groups=["M-optimization-no-privatelink"],
                also_sites=["C-s1-prose-001"],
                also_sites_rationale="r")
    _s, _r, problems = expand(cand, rows)
    assert any("expanders reach" in x for x in problems), problems


def test_promotion_needs_a_written_reason(rows):
    cand = base(test_cases=["F5-7a"], merge_groups=["M-optimization-no-privatelink"],
                also_sites=["C-s4-5-3-prose-001"])
    _s, _r, problems = expand(cand, rows)
    assert any("no also_sites_rationale" in x for x in problems), problems


def test_promotion_actually_promotes(rows):
    """Mutation-check the override itself: if it were a no-op, every arm above still
    passes and V13-03 would quietly amend 4 of the 6 sites it names."""
    kw = dict(test_cases=["F5-7a"], merge_groups=["M-optimization-no-privatelink"])
    without, related, _p = expand(base(**kw), rows)
    with_, _r2, _p2 = expand(base(**kw, also_sites=["C-s4-5-3-prose-001"],
                                  also_sites_rationale="r"), rows)
    assert "C-s4-5-3-prose-001" in {r["claim_id"] for r in related}
    assert "C-s4-5-3-prose-001" not in {r["claim_id"] for r in without}
    assert "C-s4-5-3-prose-001" in {r["claim_id"] for r in with_}
    assert any("promoted" in r["_why"] for r in with_), \
        "a promoted site must say so in its derivation column"


def test_a_claim_in_both_claim_ids_and_also_sites_is_reported(rows):
    """Dead configuration that reads as a second safeguard."""
    cand = base(test_cases=["F5-7a"], merge_groups=["M-optimization-no-privatelink"],
                claim_ids=["C-s4-5-3-prose-001"], claim_id_rationale="r",
                also_sites=["C-s4-5-3-prose-001"], also_sites_rationale="r")
    _s, _r, problems = expand(cand, rows)
    assert any("both claim_ids and also_sites" in x for x in problems), problems


def test_a_named_claim_id_is_a_site_even_under_a_merge_group(rows):
    """The escape hatch must survive declaring a merge group.

    It exists for claims *no expander reaches*, which in practice means class-D rows with
    no merge group — precisely what the demotion rule would eat. V13-06 named the §6.1
    ILLUSTRATIVE disclaimer with a written rationale and it was demoted on the first run
    of the narrowed rule.
    """
    cand = next(c for c in v13.CANDIDATES if c["id"] == "V13-06")
    sites, related, _p = expand(cand, rows)
    site_ids = {r["claim_id"] for r in sites}
    for cid in cand["claim_ids"]:
        assert cid in site_ids, f"{cid} was named explicitly and is not a site"
        assert cid not in {r["claim_id"] for r in related}


def test_named_claim_ids_need_a_rationale(rows):
    problems: list[str] = []
    cand = base(claim_ids=["C-s6-1-quote-001"])
    sites, _r = v13.expand(cand, rows, problems)
    v13.check(cand, sites, problems)
    assert any("with no rationale" in x for x in problems), problems


def test_anchors_are_not_an_expander():
    """Deliberate omission, asserted so it cannot be added as a convenience.

    `s4-4` holds 37 claims and `s3-2` holds 35; an anchor-level site list would tell an
    editor to review a section instead of naming the sentence — the coarse form of the
    defect this register prevents.
    """
    for cand in v13.CANDIDATES:
        assert "anchors" not in cand, f"{cand['id']} declares anchors as an expander"
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'cand["anchors"]' not in src and "cand.get(\"anchors\"" not in src


# ---------------------------------------------------------------------------
# evidence discipline
# ---------------------------------------------------------------------------

def test_a_named_finding_file_must_exist(rows, tmp_path):
    problems: list[str] = []
    cand = base(test_cases=["F1-1"], evidence="measured",
                finding="FINDING-DOES-NOT-EXIST.md")
    sites, _r = v13.expand(cand, rows, problems)
    v13.check(cand, sites, problems)
    assert any("does not exist under results/" in x for x in problems), problems


def test_every_shipped_finding_reference_resolves():
    for cand in v13.CANDIDATES:
        if cand["finding"]:
            assert (v13.RESULTS / cand["finding"]).is_file(), \
                f"{cand['id']} → results/{cand['finding']} is missing"


def test_measured_ready_without_a_finding_is_reported(rows):
    problems: list[str] = []
    cand = base(test_cases=["F1-1"], status="MEASURED_READY")
    sites, _r = v13.expand(cand, rows, problems)
    v13.check(cand, sites, problems)
    assert any("MEASURED_READY with no finding" in x for x in problems), problems


def test_blocked_on_replication_without_a_finding_is_reported(rows):
    problems: list[str] = []
    cand = base(test_cases=["F1-1"], status="BLOCKED_ON_REPLICATION")
    sites, _r = v13.expand(cand, rows, problems)
    v13.check(cand, sites, problems)
    assert any("nothing to block on" in x for x in problems), problems


def test_no_evidence_and_no_planned_case_is_reported(rows):
    problems: list[str] = []
    cand = base(test_cases=["F1-1"], planned_cases=[])
    sites, _r = v13.expand(cand, rows, problems)
    v13.check(cand, sites, problems)
    assert any("opinion in a table of measurements" in x for x in problems), problems


def test_an_unknown_status_is_reported(rows):
    problems: list[str] = []
    cand = base(test_cases=["F1-1"], status="LOOKS_FINE")
    sites, _r = v13.expand(cand, rows, problems)
    v13.check(cand, sites, problems)
    assert any("unknown status" in x for x in problems), problems


def test_every_status_in_use_is_documented():
    """A status with no entry in STATUSES has no stated meaning for the amendment."""
    for cand in v13.CANDIDATES:
        assert cand["status"] in v13.STATUSES
        assert v13.STATUSES[cand["status"]].strip()


def test_no_candidate_may_be_measured_ready_before_two_days(rows):
    """The sealed replication rule, enforced where the amendment is *decided*.

    `check_amendment_readiness.py` is the authority, but the register is what an editor
    reads, so a MEASURED_READY here on one-day evidence would be the failure regardless
    of what the gate says.

    The days are **re-derived from `t_start_utc` in the evidence records**, exactly as the
    gate does, not looked for as a word in the finding's prose. An earlier version of this
    arm accepted `"REPLICATION" in f.upper() or "offline" in f or "$0" in f`, and every
    finding in the tree contains `$0` — so the assertion was true by construction and
    would have waved through a MEASURED_READY promoted on one day's data
    (`feedback_vacuous_test_check`, and `feedback_prose_is_not_verified` for the reason
    the substring was the wrong instrument in the first place).
    """
    import json
    import re
    BLOCK = re.compile(r"^<!--\s*provenance\s*\n(.*?)^-->", re.S | re.M)

    checked = 0
    for cand in v13.CANDIDATES:
        if cand["status"] != "MEASURED_READY":
            continue
        path = v13.RESULTS / cand["finding"]
        meta = json.loads(BLOCK.search(path.read_text(encoding="utf-8")).group(1))
        runs = meta.get("evidence_runs") or []
        checked += 1

        # An offline finding (F1-1: the contents of released wheels) asserts nothing about
        # live AWS state, so there is no transient for a second day to exclude. It must SAY
        # so in the provenance block rather than merely have an empty run list, or "I forgot
        # to record the runs" and "there is nothing to record" become the same artifact.
        if not runs:
            assert str(meta.get("note", "")).strip(), (
                f"{cand['id']} is MEASURED_READY with no evidence runs and no note "
                f"explaining why replication does not apply")
            continue

        days = set()
        for rid in runs:
            d = v13.ROOT / "evidence" / rid
            assert d.is_dir(), f"{cand['id']}: declared run {rid} is not under evidence/"
            for p in d.rglob("*.json"):
                if p.name in ("environment.json", "analysis.json", "summary.json"):
                    continue
                ts = json.loads(p.read_text(encoding="utf-8")).get("t_start_utc")
                if ts:
                    days.add(str(ts)[:10])
        assert len(days) >= 2, (
            f"{cand['id']} is MEASURED_READY but its finding's evidence spans "
            f"{len(days)} calendar day(s) ({sorted(days)}); the sealed rule requires >= 2")

    assert checked, ("no candidate is MEASURED_READY, so this arm asserted nothing — "
                     "which is indistinguishable from it passing")

    # And the comparator's own verdict binds the status: a failed replication must not be
    # reachable from a register that says the amendment can be drafted.
    rep = v13.RESULTS / "f5_7a_replication.json"
    if rep.is_file():
        body = json.loads(rep.read_text(encoding="utf-8"))
        v03 = next(c for c in v13.CANDIDATES if c["id"] == "V13-03")
        if body.get("replicated"):
            assert v03["status"] == "MEASURED_READY", (
                f"07a_compare_runs.py replicated ({body['n_fields_compared']} fields, 0 "
                f"disagreements) but V13-03 still reads {v03['status']} — the register "
                f"would keep an editor waiting on evidence that already exists")
        else:
            assert v03["status"] == "BLOCKED_ON_REPLICATION", (
                "the replication comparison did not pass, so V13-03 cannot be anything "
                "but BLOCKED_ON_REPLICATION")


# ---------------------------------------------------------------------------
# the rendered register
# ---------------------------------------------------------------------------

def test_the_rendered_counts_match_the_derivation():
    """A count in prose is unverified (`feedback_prose_is_not_verified`). Recompute."""
    rows = v13.load_triage()
    text = v13.OUT.read_text(encoding="utf-8")
    distinct = set()
    for cand in v13.CANDIDATES:
        sites, _r, _p = expand(cand, rows)
        distinct |= {r["claim_id"] for r in sites}
        assert f"**Sites to amend: {len(sites)}.**" in text, \
            f"{cand['id']}'s site count in the register disagrees with the derivation"
    assert f"**{len(distinct)} distinct document sites**" in text
    assert f"**{len(v13.CANDIDATES)} candidates**" in text


def test_every_site_appears_in_the_rendered_register():
    """The register is the deliverable; a derived site absent from it is not delivered."""
    rows = v13.load_triage()
    text = v13.OUT.read_text(encoding="utf-8")
    for cand in v13.CANDIDATES:
        sites, _r, _p = expand(cand, rows)
        for r in sites:
            assert f"`{r['claim_id']}`" in text, \
                f"{r['claim_id']} ({cand['id']}) is derived but not rendered"


def test_the_register_carries_no_account_identifier():
    """Published artifact; the redaction gate treats 12 digits as a finding."""
    import re
    text = v13.OUT.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{12}\b", text)
    assert "arn:aws" not in text


def test_severity_ordering_is_stable_and_documented():
    rows = v13.load_triage()
    resolved = []
    for cand in v13.CANDIDATES:
        sites, related, _p = expand(cand, rows)
        resolved.append((cand, sites, related))
    resolved.sort(key=lambda t: (v13.SEVERITY_ORDER.index(t[0]["severity"]), t[0]["id"]))
    order = [c["id"] for c, _s, _r in resolved]
    text = v13.OUT.read_text(encoding="utf-8")
    positions = [text.index(f"\n## {cid}\n") for cid in order]
    assert positions == sorted(positions), \
        "the register's sections are not in severity order"


def test_the_triage_columns_the_expanders_depend_on_still_exist():
    """A renamed column would make every expander silently return nothing."""
    with TRIAGE.open(encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    for col in ("claim_id", "anchor", "cls", "doc_line", "cases", "merge_group",
                "canonical", "text"):
        assert col in header, f"triage.csv lost column {col!r}"
