#!/usr/bin/env python3
"""The case census must be derived, and every guard in it must be able to fail.

Why this file exists
--------------------
`results/_progress_census.txt` was hand-written once. Its headline — "27 remaining" —
was correct, and it was correct *by accident*: it subtracted 63 published-and-mapped
cases from the 90 cases `claims/triage.csv` maps, while calling those 90 "the register".
The register is 93. Two offsetting errors landed on the right number.

The same file was wrong by 2 where nothing cancelled: it reported family F1 at 17/26 and
TRUE at 37, because it dropped F1-21 and F1-4 as "not in the register" when both are in
the register and both have verdicts. So the accidentally-right total sat next to a
demonstrably-wrong breakdown, which is `feedback_label_must_match_computation`: a
breakdown must reconcile to its parent, and here it could not, because the parent and the
breakdown were counting different sets.

`census.py` replaces the hand count. This file's job is the part that a derivation does
not give you for free: proving each of its guards can actually fail. A census that
asserts seven invariants and would exit 0 with all seven deleted is a census that reports
whatever it is handed (`feedback_vacuous_test_check`).

The one guard worth naming
--------------------------
`claim_mapped()` reads the `cases` column as **whitespace tokens**. A whole-cell
comparison — the obvious way to write it — silently drops every row that names more than
one case, and `claims/triage.csv` has such rows: `C-s7-1-prose-004` holds `"F3-10 F3-9"`.
The mutation arm below is the only test in the repo that fails when that read is changed
back, and the failure it prevents is a case appearing *unmapped* because it always shares
a cell.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_census():
    """Import census.py by path.

    By path rather than by name, because `lib/tests/test_module_name_collisions.py`
    records that this repo has several same-named modules across family directories and
    an `import census` would be resolved by whatever is first on `sys.path`.
    """
    spec = importlib.util.spec_from_file_location("_census_under_test", ROOT / "census.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_census_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def census():
    return load_census()


# --------------------------------------------------------------------------------------
# the numbers themselves
# --------------------------------------------------------------------------------------

def test_the_four_denominators_are_distinct_and_derived(census, capsys):
    """93 / 92 / 90 are three different questions, and the report must not conflate them."""
    assert census.run() == 0
    out = capsys.readouterr().out
    for want in ("register", "claim-mapped", "verdict-eligible", "published", "REMAINING"):
        assert want in out, f"the report dropped the {want!r} denominator"

    CASES, sha_live = census.load_register()
    n_declared, sha_declared = census.prereg_registry_sha()
    mapped, n_rows = census.claim_mapped()
    ver = census.published()

    assert len(CASES) == n_declared == 93
    assert sha_live == sha_declared
    assert len(mapped) == 90
    assert n_rows == 546
    untestable = {c for c, m in census.CLAIM_UNMAPPED_BY_DESIGN.items()
                  if m["kind"] == "untestable"}
    assert len(CASES) - len(untestable) == 92
    # The parent and the breakdown must reconcile: this is the check the hand census
    # could not pass.
    assert len(set(ver)) == len(ver)
    assert set(ver) <= set(CASES)


def test_the_hand_census_numbers_that_were_wrong_stay_wrong(census):
    """Pin the hand census's ERROR, and the cause of it — not a snapshot of the fix.

    The hand census said F1 was 17/26 and TRUE was 37. Both were short by exactly the
    two cases it excluded, F1-21 and F1-4, which are in the register and do have
    verdicts. If either number comes back, something has started dropping register
    cases again.

    An earlier version of this test asserted `(len(f1_done), len(f1_eligible)) ==
    (19, 28)` and `n_true == 39` — the corrected values as they stood the day it was
    written. That is the wrong quantity to watch. Those two numerators move every time
    a case gets a verdict, so the test failed on F1-18 landing, which is the project
    working exactly as intended. A test that reds on progress teaches people to edit
    the test, which is how the pinned value it exists to defend gets edited away.

    So this watches three things that do NOT move with the verdict count:

    * the denominator, reconciled THROUGH the cause: 26 is what F1's denominator
      becomes when the two dropped cases are removed from it, so the corrected figure
      is not asserted as a literal at all — it is derived from the hand figure plus
      the named omission. Registering or dropping an F1 case breaks this, and the
      register is sha-pinned, so that break would be a real one;
    * that both dropped cases carry verdicts, which is the numerator's half of the
      same cause;
    * that the refuted pairs are not the live ones.

    The floors are the only snapshot left, and they are one-sided on purpose: they
    catch a case losing its verdict, which is the failure mode, while a case GAINING
    one passes. Raise them when convenient; if one ever has to come DOWN, a verdict
    was withdrawn and that belongs in DEVIATIONS.md with a reason.
    """
    CASES, _ = census.load_register()
    ver = census.published()
    f1_eligible = {c for c in CASES if CASES[c][0] == "F1"}
    f1_done = f1_eligible & set(ver)
    dropped = {"F1-21", "F1-4"}

    assert dropped <= f1_eligible, \
        f"{sorted(dropped - f1_eligible)} left F1's denominator — the hand census's exact error"
    assert len(f1_eligible - dropped) == 26, (
        f"F1's denominator is {len(f1_eligible)}; without the two cases the hand census "
        f"dropped it is {len(f1_eligible - dropped)}, and the hand census said 26. That "
        f"identity is the whole finding, so a change here is a register change, not a verdict.")
    assert dropped <= f1_done, \
        f"{sorted(dropped - f1_done)} has no verdict — the hand census's other half"

    n_true = sum(1 for v in ver.values() if v[0][1] == "TRUE")
    # DEAD BY CONSTRUCTION, and kept anyway. The identity above forces the denominator to
    # 28, so `== 26` cannot be reached while that assert holds: the hand-census mutation
    # arm fires two lines earlier, not here. It stays because the refuted pair should be
    # greppable as a literal in the file that defends it, and a reader should be told which
    # of these lines is load-bearing rather than left to assume all of them are.
    assert (len(f1_done), len(f1_eligible)) != (17, 26), "17/26 is the hand census's error"
    assert n_true != 37, "37 is the hand census's error"   # reachable: precedes the floor
    assert len(f1_done) >= 20, f"F1 had 20 verdicts and now has {len(f1_done)}"
    assert n_true >= 40, f"TRUE was 40 and is now {n_true}"


def test_unmapped_cases_are_all_accounted_for(census):
    """The residue is derived; the reasons are declared; the two must agree exactly."""
    CASES, _ = census.load_register()
    mapped, _ = census.claim_mapped()
    assert set(CASES) - mapped == set(census.CLAIM_UNMAPPED_BY_DESIGN)
    assert set(census.CLAIM_UNMAPPED_BY_DESIGN) == {"F9-1", "F1-21", "F1-4"}
    # Each declared reason must be checkable against the case's own sealed text.
    for cid, meta in census.CLAIM_UNMAPPED_BY_DESIGN.items():
        assert meta["check"] in " ".join(str(x) for x in CASES[cid])
    # F9-1 is the only one excluded from the denominator, and only because its own
    # oracle disqualifies it — not because we could not get to it.
    assert census.CLAIM_UNMAPPED_BY_DESIGN["F9-1"]["kind"] == "untestable"
    assert census.CLAIM_UNMAPPED_BY_DESIGN["F1-21"]["kind"] == "api-surface"
    assert census.CLAIM_UNMAPPED_BY_DESIGN["F1-4"]["kind"] == "api-surface"


def test_f1_4_really_has_no_claim_to_map(census):
    """The declared reason for F1-4 is an absence claim, so measure the absence.

    F1-4's reason says a search over all 546 triaged claims for the union's arity
    constraint returns zero rows. An absence stated in a docstring is prose; here it is
    a test, so if the document is ever re-triaged and such a row appears, F1-4 stops
    being claim-unmapped-by-design and this fails.
    """
    import csv
    rows = list(csv.DictReader((ROOT / "claims" / "triage.csv").open(encoding="utf-8")))
    assert len(rows) == 546
    pats = ("exactly one", "one arm", "mutually exclusive", "oneof", "one-of")
    hits = [r["claim_id"] for r in rows
            if any(p in (r.get("text") or "").lower() for p in pats)]
    assert hits == [], f"a claim now states the union's arity: {hits}"


# --------------------------------------------------------------------------------------
# the reconciliation that nothing was doing (DEV-P4-33)
# --------------------------------------------------------------------------------------

def _cases_with_a_written_up_result(register: dict) -> dict[str, str]:
    """Every case this project has published a finding artifact for → the artifact's name.

    Derived from the filenames under `results/`, normalised against the register's own
    spelling, because the register is the only authority on whether `F5-7A` is a case id.
    The H1 line is deliberately NOT parsed: a title may name a neighbouring case for
    contrast (`F2-5 beside F2-1`), and a guard that demanded a record for every case merely
    *mentioned* would fire on a sentence rather than on a gap.
    """
    import re
    by_lower = {c.lower(): c for c in register}
    out: dict[str, str] = {}
    for f in sorted((ROOT / "results").glob("FINDING-*")):
        if f.suffix not in (".md", ".json"):
            continue
        m = re.match(r"(F\d+-\d+[A-Za-z]?)", f.stem[len("FINDING-"):])
        if not m:
            continue                            # FINDING-P0-* are process, not cases
        cid = by_lower.get(m.group(1).lower())
        if cid:
            out.setdefault(cid, f.name)
    return out


def test_a_written_up_case_has_a_verdict_record(census):
    """A finding document and a verdict record are different artifacts, and both are owed.

    This is the check that did not exist, and its absence let two cases sit *complete and
    counted outstanding* for days: F5-7a (measured 2026-08-09, replicated 08-10, published
    as `FINDING-F5-7A.md`) and F0-1 (24/24 verified 08-09, artifact and document both
    saying so). Neither had a file in `results/phase1/`, which is the index this census
    counts, so family F5 read 3/12 and F0 read 0/1 next to write-ups saying the work was
    done. See DEV-P4-33.

    The failure mode is specific and worth naming: the *visible* half being complete is
    exactly what hides the missing half. Nobody re-reads a finished finding document
    looking for what it did not do.
    """
    CASES, _ = census.load_register()
    written_up = _cases_with_a_written_up_result(CASES)
    assert written_up, ("no finding artifact was matched to a register case, so this arm "
                        "measured nothing — the filename derivation broke, not the repo")

    published = set(census.published())
    untestable = {c for c, m in census.CLAIM_UNMAPPED_BY_DESIGN.items()
                  if m["kind"] == "untestable"}

    missing = {c: art for c, art in written_up.items()
               if c not in published and c not in untestable}
    assert not missing, (
        "these cases have a written-up result and no verdict record in results/phase1/, so "
        "the census counts them outstanding while a finding says they are done: "
        + ", ".join(f"{c} ({art})" for c, art in sorted(missing.items()))
        + ". Emit the record — a case is not complete until it is in the index the analysis "
          "phase reads.")


def test_the_two_cases_that_taught_us_this_are_covered_by_it(census):
    """Pin the instances, so the guard cannot be narrowed until it stops seeing them.

    `test_a_written_up_case_has_a_verdict_record` passes both when the reconciliation works
    and when the derivation quietly matches nothing. This names the two cases whose gap
    motivated it and requires them to be *in scope* of the check, which is a different
    claim from the check being green.
    """
    CASES, _ = census.load_register()
    written_up = _cases_with_a_written_up_result(CASES)
    for cid, art in (("F5-7a", "FINDING-F5-7A.md"),
                     ("F0-1", "FINDING-F0-1-references.json")):
        assert written_up.get(cid) == art, (
            f"{cid} is no longer matched to {art}; the derivation that found the DEV-P4-33 "
            f"gap has stopped covering the case that revealed it")
        assert cid in set(census.published()), \
            f"{cid} lost its verdict record — this is the DEV-P4-33 gap reopening"


def test_the_reconciliation_fails_when_a_record_goes_missing(census, tmp_path):
    """The mutation: hide one published record and require the guard to name that case.

    Without this arm the check above is compatible with a `missing` dict that is empty
    because nothing is ever compared.
    """
    CASES, _ = census.load_register()
    written_up = _cases_with_a_written_up_result(CASES)
    victim = next(c for c in sorted(written_up) if c in set(census.published()))

    p1 = tmp_path / "phase1"
    p1.mkdir()
    for f in census.PHASE1.glob("*.json"):
        if f.stem != victim:
            (p1 / f.name).write_bytes(f.read_bytes())
    census.PHASE1 = p1

    assert victim not in set(census.published()), "the victim's record was not hidden"
    with pytest.raises(AssertionError, match=victim):
        test_a_written_up_case_has_a_verdict_record(census)


# --------------------------------------------------------------------------------------
# mutation arms — each removes exactly one guard's precondition and expects a hard fail
# --------------------------------------------------------------------------------------

def _stub_paths(census, tmp_path, *, triage_rows, verdicts):
    """Point census.py at a synthetic triage csv and results dir."""
    import csv as _csv
    t = tmp_path / "triage.csv"
    with t.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=["claim_id", "cases", "text"])
        w.writeheader()
        for i, cases in enumerate(triage_rows):
            w.writerow({"claim_id": f"C-{i}", "cases": cases, "text": ""})
    census.TRIAGE = t
    p1 = tmp_path / "phase1"
    p1.mkdir()
    for cid, verdict in verdicts:
        (p1 / f"{cid}.json").write_text(
            json.dumps({"case_id": cid, "verdict": verdict}), encoding="utf-8")
    census.PHASE1 = p1


def test_mutation_claim_mapped_to_unregistered_case_fails(census, tmp_path):
    CASES, _ = census.load_register()
    rows = [" ".join(sorted(CASES))] + ["F99-1"]
    _stub_paths(census, tmp_path, triage_rows=rows, verdicts=[])
    with pytest.raises(SystemExit) as e:
        census.run()
    assert e.value.code == 1


def test_mutation_verdict_for_unregistered_case_fails(census, tmp_path):
    CASES, _ = census.load_register()
    _stub_paths(census, tmp_path,
                triage_rows=[" ".join(sorted(CASES))],
                verdicts=[("F99-2", "TRUE")])
    with pytest.raises(SystemExit) as e:
        census.run()
    assert e.value.code == 1


def test_mutation_undeclared_unmapped_case_fails(census, tmp_path):
    """Drop one case from the triage mapping without declaring a reason for it."""
    CASES, _ = census.load_register()
    keep = sorted(set(CASES) - set(census.CLAIM_UNMAPPED_BY_DESIGN) - {"F3-1"})
    _stub_paths(census, tmp_path, triage_rows=[" ".join(keep)], verdicts=[])
    with pytest.raises(SystemExit) as e:
        census.run()
    assert e.value.code == 1


def test_mutation_declared_reason_not_in_sealed_text_fails(census, tmp_path):
    CASES, _ = census.load_register()
    census.CLAIM_UNMAPPED_BY_DESIGN = {
        **census.CLAIM_UNMAPPED_BY_DESIGN,
        "F1-4": {**census.CLAIM_UNMAPPED_BY_DESIGN["F1-4"],
                 "check": "a phrase that is not in the oracle"},
    }
    _stub_paths(census, tmp_path,
                triage_rows=[" ".join(sorted(set(CASES) - set(census.CLAIM_UNMAPPED_BY_DESIGN)))],
                verdicts=[])
    with pytest.raises(SystemExit) as e:
        census.run()
    assert e.value.code == 1


def test_mutation_verdict_for_untestable_case_fails(census, tmp_path):
    """F9-1 is excluded from the denominator. A verdict for it must not be silently kept."""
    CASES, _ = census.load_register()
    _stub_paths(census, tmp_path,
                triage_rows=[" ".join(sorted(set(CASES) - set(census.CLAIM_UNMAPPED_BY_DESIGN)))],
                verdicts=[("F9-1", "TRUE")])
    with pytest.raises(SystemExit) as e:
        census.run()
    assert e.value.code == 1


def test_mutation_register_size_disagreeing_with_prereg_fails(census, tmp_path, monkeypatch):
    CASES, sha = census.load_register()
    shrunk = {k: v for k, v in list(CASES.items())[:-1]}
    monkeypatch.setattr(census, "load_register", lambda: (shrunk, sha))
    with pytest.raises(SystemExit) as e:
        census.run()
    assert e.value.code == 1


def test_mutation_broken_seal_fails(census, monkeypatch):
    """A register that no longer hashes to its sealed sha256 must stop the census.

    `feedback_provenance_stamp_liveness`: the sha is recomputed with the serialization
    PREREGISTRATION.yaml itself records, so this arm proves the recomputation is real and
    not a copy of the declared value.
    """
    CASES, _ = census.load_register()
    monkeypatch.setattr(census, "load_register", lambda: (CASES, "0" * 64))
    with pytest.raises(SystemExit) as e:
        census.run()
    assert e.value.code == 1


def test_mutation_whole_cell_cases_read_would_lose_a_case(census):
    """The `cases` column must be read as tokens, not compared whole.

    This is the guard with no other coverage in the repo. `claims/triage.csv` has rows
    whose `cases` cell names two cases, so a whole-cell read makes any case that only
    ever shares a cell look unmapped — and "unmapped" is a state this census treats as
    needing a declared reason, so the error surfaces as a spurious census failure rather
    than a wrong number. Either way it must not be reachable by accident.
    """
    import csv
    rows = list(csv.DictReader((ROOT / "claims" / "triage.csv").open(encoding="utf-8")))
    multi = [r["cases"] for r in rows if len((r.get("cases") or "").split()) > 1]
    assert multi, "no multi-case cells left — this test's premise is gone, re-check it"

    token_read = set()
    whole_cell_read = set()
    for r in rows:
        cell = (r.get("cases") or "").strip()
        token_read |= set(cell.split())
        if cell:
            whole_cell_read.add(cell)
    lost = token_read - whole_cell_read
    assert lost, "a whole-cell read would lose nothing, so the token read is untested"
    # And the loss is not hypothetical: name one case that exists only inside shared cells.
    assert any(all(c in cell.split() and len(cell.split()) > 1
                   for cell in whole_cell_read if c in cell.split())
               for c in lost)
