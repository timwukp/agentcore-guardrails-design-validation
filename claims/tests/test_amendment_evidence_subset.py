"""DEV-P4-36, second site: the amendment gate's per-arm copy of `evidence/`, and its bound.

What went wrong
---------------
`test_amendment_gate.py`'s `tree` fixture copied `evidence/` **whole** — 198,452 KB in 28,716
files — once per mutation arm, 26 arms, about 4.9 GB per run. Its docstring said "only what the
gate reads is copied". That was the same unbounded per-arm copy DEV-P4-36 was written about, and
DEV-P4-36's AST scan was written to skip it: a subtree copy, it reasoned, "names what it takes".
It does name it. It does not bound it, and `evidence/` is the largest tree in the repo.

Found while writing DEV-P4-36's guards, and killed the 14-gate re-run that was supposed to
confirm them: the run was stopped by hand at 2.4 GB of scratch to avoid a second ENOSPC wedge.

What this file pins
-------------------
* the subset is DERIVED from the findings' provenance blocks, and moves when they do;
* it yields the **same observation days, per finding, as the full tree** — the one property the
  gate's result depends on, asserted by running the real gate both ways rather than reasoned
  about;
* it is bounded ABOVE and BELOW against a real copy, and the ceiling is load-bearing: the full
  tree breaches it, so the bound would have caught the defect rather than describing it;
* the things individual arms silently depend on are named — every declared run directory
  exists even when empty, and each keeps the `0001_*.json` record three arms template from;
* it keeps the sibling declared cases, so a gate that lost its `case_id` scoping is still
  caught here (a subset trimmed to one case per finding would have hidden that);
* an unreadable record is KEPT, because the gate reports one and a fixture that dropped it
  would turn a real failure into a green control arm.

Offline, $0. One real subset copy (~25 MB) and two gate runs.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from evidence_subset import (BLOCK_RE, EVIDENCE_SUBSET_CEILING_KB, GATE, RECORDS_PER_CASE_DAY,
                             ROOT, _GATE, case_days, copy_evidence_subset, copy_gate_code,
                             declared_provenance, subset_manifest)

EVIDENCE = ROOT / "evidence"

# The gate prints one line per finding: name, status, then either "N day(s) [...]" or
# "offline (no evidence runs)". Parsed rather than eyeballed, because the equivalence arm below
# compares two of these listings field by field.
ROW_RE = re.compile(r"^\s+(FINDING-\S+)\s+(\S+)\s+(.*?)\s*$", re.M)


def _kb(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) // 1024


def _rows(stdout: str) -> dict[str, tuple[str, str]]:
    rows = {m.group(1): (m.group(2), m.group(3)) for m in ROW_RE.finditer(stdout)}
    assert rows, f"the gate printed no per-finding rows:\n{stdout[-600:]}"
    return rows


def _run_gate(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(cwd / GATE.name)],
                          capture_output=True, text=True, cwd=cwd)


def _fake_root(base: Path, records: dict[str, str], *, run: str = "rFAKE",
               cases: list[str] | None = None) -> Path:
    """A minimal tree the derivation can read: one finding, one run, `records` under it.

    Hand-built rather than copied, so an arm about which records are KEPT is not also an arm
    about the real archive's contents.
    """
    (base / "results").mkdir(parents=True, exist_ok=True)
    meta = {"status": "RESOLVED", "evidence_runs": [run],
            "cases": cases if cases is not None else ["C-1"]}
    (base / "results" / "FINDING-FAKE.md").write_text(
        "# fake\n\n<!-- provenance\n" + json.dumps(meta, indent=2) + "\n-->\n",
        encoding="utf-8")
    d = base / "evidence" / run
    d.mkdir(parents=True, exist_ok=True)
    for name, body in records.items():
        (d / name).write_text(body, encoding="utf-8")
    return base


# --------------------------------------------------------------------------- the derivation

def test_the_declared_provenance_is_read_from_the_findings():
    runs, cases = declared_provenance()
    assert runs and cases, (
        "no run_ids or case_ids were derived from results/FINDING-*.md; the subset would then "
        "be empty and every amendment arm would fail for the wrong reason")
    # Whether a declared run is on disk is the GATE's finding, not this module's, so it is not
    # asserted here — `test_kills_a_declared_run_that_is_not_on_disk` owns that direction.
    # The blocks the derivation reads are the ones the gate reads, not a second regex.
    assert BLOCK_RE is _GATE.BLOCK_RE, (
        "evidence_subset has stopped parsing provenance with the gate's own BLOCK_RE; a "
        "restated copy is DEV-P4-36's 'duplicated constant is a defect with a delay'")
    sample = sorted((ROOT / "results").glob("FINDING-*.md"))[0]
    assert BLOCK_RE.search(sample.read_text(encoding="utf-8")), (
        f"the shared BLOCK_RE no longer matches {sample.name}, so the derivation reads nothing")


def test_the_manifest_moves_when_the_declared_cases_do():
    """A derivation that ignored its inputs would look exactly like a hand-written list."""
    full = subset_manifest()
    runs, cases = declared_provenance()
    one = subset_manifest(cases=(cases[0],))
    none = subset_manifest(cases=())
    assert len(one) < len(full), (
        f"narrowing the declared cases to {cases[0]!r} left the manifest at {len(full)} files; "
        "the case_id filter is not reaching the manifest")
    assert len(none) < len(one), (
        "declaring no cases at all did not shrink the manifest below one case; what remains is "
        "not being selected by case_id")
    assert len(none) > 0, (
        "with no declared cases the manifest is empty — environment.json and any unreadable "
        "record must still be kept, or those two arms below test nothing")
    narrower_runs = subset_manifest(runs=(runs[0],))
    assert len(narrower_runs) < len(full), (
        "narrowing the declared runs did not shrink the manifest; the run list is not reaching it")


def test_a_record_of_an_undeclared_case_is_dropped(tmp_path):
    root = _fake_root(tmp_path, {
        "0001_kept.json": json.dumps({"case_id": "C-1", "t_start_utc": "2026-01-01T00:00:00Z"}),
        "0002_dropped.json": json.dumps({"case_id": "C-9",
                                         "t_start_utc": "2026-01-02T00:00:00Z"}),
    })
    names = {p.name for p in subset_manifest(root=root)}
    assert names == {"0001_kept.json"}, (
        f"expected only the declared case's record, got {sorted(names)} — if the dropped record "
        "is still here the subset is not a subset, and if the kept one is gone the gate would "
        "lose the day it is supposed to derive")


def test_an_unreadable_record_is_kept_not_dropped(tmp_path):
    """The gate reports an unparseable record. A fixture that dropped it would launder that.

    The complement of the arm above, and the reason both exist: "drops what the gate ignores"
    and "drops what the gate would complain about" are one line apart in the builder.
    """
    root = _fake_root(tmp_path, {
        "0001_kept.json": json.dumps({"case_id": "C-1", "t_start_utc": "2026-01-01T00:00:00Z"}),
        "0002_broken.json": "{not json,}",
        "0003_not_an_object.json": "[1, 2, 3]",
        "environment.json": json.dumps({"region": "us-west-2"}),
    })
    names = {p.name for p in subset_manifest(root=root)}
    assert {"0002_broken.json", "0003_not_an_object.json"} <= names, (
        f"an unreadable record was dropped from the subset ({sorted(names)}); the gate reports "
        "one as a problem, so dropping it hides a real failure behind a green control arm")
    assert "environment.json" in names, (
        "environment.json is skipped by the gate but is part of a run's shape; keeping it is "
        "what makes the copy look like the original")


def test_redundant_records_of_one_case_day_are_capped(tmp_path):
    """The cap, checked where the real archive cannot check it: at the boundary.

    The real tree has thousands of records per F6 case-day, so an arm over it can only say "fewer
    than before". This says the exact number, which is the only way a cap that quietly kept three
    or dropped to one would be visible.
    """
    n = RECORDS_PER_CASE_DAY + 3
    recs = {f"{i:04d}_call.json": json.dumps({"case_id": "C-1",
                                              "t_start_utc": f"2026-01-01T0{i}:00:00Z"})
            for i in range(1, n + 1)}
    root = _fake_root(tmp_path, recs)
    kept = sorted(p.name for p in subset_manifest(root=root))
    assert len(kept) == RECORDS_PER_CASE_DAY, (
        f"{n} records of one (case, day) produced {len(kept)} kept: {kept}. Each one after the "
        f"first cannot change the day SET the gate derives, so keeping them is scratch copied "
        f"once per mutation arm")
    assert kept[0].startswith("0001_"), (
        f"the kept records are {kept}; the arms that template a synthetic day-2 record do "
        f"`next(rglob('0001_*.json'))`")


def test_the_cap_never_costs_a_day(tmp_path):
    """Two days of one case, more records per day than the cap: both days must survive.

    This is the property the whole cap rests on, stated at the boundary rather than only over the
    real archive. If the cap were counted per CASE instead of per (case, day) — one plausible
    slip — this reds and `test_a_subset_copy_is_bounded_above_and_below` might not, because the
    real tree's F6 case-days are far apart in sort order.
    """
    recs = {}
    for day in ("2026-01-01", "2026-01-02"):
        for i in range(1, RECORDS_PER_CASE_DAY + 3):
            recs[f"{day}_{i:04d}.json"] = json.dumps(
                {"case_id": "C-1", "t_start_utc": f"{day}T0{i}:00:00Z"})
    root = _fake_root(tmp_path, recs)
    assert case_days(root=root) == {("C-1", "2026-01-01"), ("C-1", "2026-01-02")}
    got = {json.loads((root / p).read_text())["t_start_utc"][:10]
           for p in subset_manifest(root=root)}
    assert got == {"2026-01-01", "2026-01-02"}, (
        f"the cap kept records from {sorted(got)} only; a dropped day is a dropped gate answer")


def test_a_declared_cases_record_with_no_timestamp_is_kept(tmp_path):
    """A `summary.json`-shaped aggregate contributes no day but does contribute `n_matched`.

    The gate has two distinct failures — "no record carries a declared case_id" and "no day could
    be established" — and a cap keyed on the day would have nowhere to put a record with none.
    Dropping it would move a mutant from one message to the other.
    """
    root = _fake_root(tmp_path, {
        "0001_call.json": json.dumps({"case_id": "C-1", "t_start_utc": "2026-01-01T00:00:00Z"}),
        "summary.json": json.dumps({"case_id": "C-1", "n_trials": 300}),
    })
    assert "summary.json" in {p.name for p in subset_manifest(root=root)}


# --------------------------------------------------------------------------- the equivalence

def test_the_subset_yields_the_same_observation_days_as_the_full_tree(tmp_path):
    """THE load-bearing arm: the gate must not be able to tell the subset from the archive.

    Run against the real repo (read-only, no copy) and against a subset tree, then compared
    row by row. Everything else in this file is about size; this is the arm that says the
    saving cost nothing. Asserted by running the gate rather than by re-deriving the days
    here, because a re-derivation in the test would share the very filter under test.
    """
    real = _run_gate(ROOT)
    assert real.returncode == 0, (
        f"the gate does not pass against the real tree, so there is no reference to compare "
        f"the subset against:\n{real.stderr[-800:]}")

    dst = tmp_path / "repo"
    (dst / "results").mkdir(parents=True)
    # `copy_gate_code` rather than a copy of the gate alone: the gate imports `lib.case_ids`, and
    # this arm spent a commit reporting "the gate fails against the subset tree" when what it had
    # built was a tree the gate could not import in. The same omission was fixed in
    # `test_amendment_gate.py`'s fixture first and was still red here
    # (`feedback_fix_producer_not_janitor`), which is why the copy has one home now.
    copy_gate_code(dst)
    (dst / "PREREGISTRATION.yaml").write_bytes((ROOT / "PREREGISTRATION.yaml").read_bytes())
    for f in (ROOT / "results").glob("FINDING-*.md"):
        (dst / "results" / f.name).write_bytes(f.read_bytes())
    copy_evidence_subset(dst)

    sub = _run_gate(dst)
    assert sub.returncode == 0, f"the gate fails against the subset tree:\n{sub.stderr[-800:]}"
    assert _rows(sub.stdout) == _rows(real.stdout), (
        "the subset changes what the gate concludes.\nreal:\n" + real.stdout +
        "\nsubset:\n" + sub.stdout)
    # And the assertion COUNT, or a subset that silently starved a check would still match rows.
    n_real = re.search(r"OK — (\d+) assertions", real.stdout)
    n_sub = re.search(r"OK — (\d+) assertions", sub.stdout)
    assert n_real and n_sub and n_real.group(1) == n_sub.group(1), (
        f"assertion counts differ: real {n_real and n_real.group(1)} vs "
        f"subset {n_sub and n_sub.group(1)}")


def test_the_subset_keeps_the_sibling_cases_that_make_a_lost_case_filter_visible():
    """`observation_days()` scopes to `case_id` because a run-wide count cannot fail here.

    A subset trimmed to one case per finding would have done that scoping in the fixture, and
    a gate that stopped filtering would have passed against it. So at least one declared run
    must still hold two declared cases whose day sets differ.
    """
    runs, cases = declared_provenance()
    per_run: dict[str, dict[str, set[str]]] = {}
    for rel in subset_manifest():
        parts = rel.parts
        rid = parts[1]
        if rel.name == "environment.json":
            continue
        try:
            rec = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(rec, dict):
            continue
        ts = rec.get("t_start_utc")
        if not ts:
            continue
        per_run.setdefault(rid, {}).setdefault(str(rec.get("case_id")), set()).add(str(ts)[:10])
    contaminating = {rid: c for rid, c in per_run.items()
                     if len({frozenset(v) for v in c.values()}) > 1}
    assert contaminating, (
        f"no run in the subset holds two declared cases with different day sets (per run: "
        f"{ {k: sorted(v) for k, v in per_run.items()} }). A gate that lost its case_id "
        f"scoping would now pass against this fixture")


# --------------------------------------------------------------------------- the bound

def test_a_subset_copy_is_bounded_above_and_below(tmp_path):
    """Above by size; below by COVERAGE — every (case, day) pair the archive holds.

    The floor used to be `EVIDENCE_SUBSET_FLOOR_KB = 8_000`, and it was the wrong instrument in
    both directions: one large record satisfies it, and it reds the moment the subset legitimately
    shrinks. On 2026-08-20 `RECORDS_PER_CASE_DAY` made the subset shrink on purpose — the ceiling
    had fired at 77,130 KB after an authorized F6 day-2 added 9,448 records that could not move any
    gate answer — so a size floor would have had to be lowered in the same commit that lowered the
    size, which is a floor that only ever agrees with whatever was measured last.

    What the arms actually depend on is that no observation day was lost, and that is derivable:
    `case_days()` reads the archive before the cap has any say. Re-derived here from the COPIED
    bytes rather than from the manifest, so a cap that kept the right paths in the manifest and a
    copy loop that dropped them are still two different outcomes.
    """
    dst = copy_evidence_subset(tmp_path / "repo")
    size = _kb(dst)
    assert size <= EVIDENCE_SUBSET_CEILING_KB, (
        f"the evidence subset is {size} KB; the ceiling is {EVIDENCE_SUBSET_CEILING_KB} KB. "
        f"26 arms at this size is how the whole-tree copy reached ~4.9 GB — find what got "
        f"copied, do not raise the bound")

    expected = case_days()
    assert expected, (
        "case_days() is empty, so the floor below asserts nothing — the derivation has stopped "
        "reading the archive (`feedback_zero_file_scan_is_error`)")
    copied: set[tuple[str, str]] = set()
    for p in dst.rglob("*.json"):
        if p.name == "environment.json":
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(rec, dict) or not rec.get("t_start_utc"):
            continue
        copied.add((str(rec.get("case_id")), str(rec["t_start_utc"])[:10]))
    assert copied == expected, (
        f"the copy does not reproduce the archive's observation days.\n"
        f"lost: {sorted(expected - copied)}\ninvented: {sorted(copied - expected)}\n"
        f"A lost pair means RECORDS_PER_CASE_DAY or the copy loop dropped a day the gate reads; "
        f"an invented one means the copy is not a subset.")


def test_the_ceiling_would_have_caught_the_whole_tree_copy():
    """The bound is load-bearing, and proving it does not require copying 198 MB again."""
    if not EVIDENCE.is_dir():
        pytest.skip("evidence/ is local-only and absent here; there is nothing honest to "
                    "measure the ceiling against")
    full = _kb(EVIDENCE)
    assert full > EVIDENCE_SUBSET_CEILING_KB, (
        f"evidence/ measures {full} KB, which fits under the {EVIDENCE_SUBSET_CEILING_KB} KB "
        f"ceiling — the bound would not have caught the copy it was written for, so it is "
        f"decoration")


def test_every_declared_run_directory_exists_in_the_copy(tmp_path):
    """"not under evidence/" and "holds no evidence records" are two arms and two messages.

    A run directory that exists in the repo but not in the copy would move a mutant from one
    to the other, killing it via a branch the arm did not name.

    Measured on the real tree this arm is VACUOUS, and the fake root below is why it is not
    left that way: all three declared runs hold records of declared cases, so their directories
    are created by the copy loop whether or not `copy_evidence_subset` creates them itself, and
    deleting that loop leaves this green (`feedback_identical_output_wrong_assertion`). The
    fake root has a declared run whose every record belongs to an UNdeclared case, so nothing
    under it is kept and only the explicit mkdir can put the directory there.
    """
    dst = copy_evidence_subset(tmp_path / "real")
    runs, _ = declared_provenance()
    for rid in runs:
        if (EVIDENCE / rid).is_dir():
            assert (dst / rid).is_dir(), (
                f"{rid} exists under evidence/ but not in the copy; the gate would report it "
                f"as absent rather than as empty")

    src = _fake_root(tmp_path / "src", {
        "0001_other_case.json": json.dumps({"case_id": "C-9",
                                            "t_start_utc": "2026-01-01T00:00:00Z"}),
    })
    assert not subset_manifest(root=src), (
        "this arm needs a declared run from which nothing is kept; the manifest is not empty")
    out = copy_evidence_subset(tmp_path / "empty_run", root=src)
    assert (out / "rFAKE").is_dir(), (
        "a declared run directory that contributes no records is missing from the copy; the "
        "gate would report it as absent rather than as holding no records, and the mutant that "
        "test_kills_an_empty_evidence_directory aims at would die by the wrong branch")


def test_each_declared_run_keeps_a_0001_record_the_arms_template_from(tmp_path):
    """Three arms do `next(rglob("0001_*.json"))` to build a synthetic second day.

    Nothing else states that dependency, and a subset that dropped those files would fail
    those arms with a StopIteration whose message names none of this.
    """
    dst = copy_evidence_subset(tmp_path / "repo")
    runs, _ = declared_provenance()
    for rid in runs:
        if not (EVIDENCE / rid).is_dir():
            continue
        assert list((dst / rid).rglob("0001_*.json")), (
            f"{rid} kept no 0001_*.json; the arms that template a synthetic day-2 record from "
            f"one would raise StopIteration inside the fixture")
