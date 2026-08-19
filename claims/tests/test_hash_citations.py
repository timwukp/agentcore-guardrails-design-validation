#!/usr/bin/env python3
"""Every elided sha256 cited in prose must resolve to a hash this repository can derive.

Why this file exists
--------------------
On 2026-08-20 `results/FINDING-F6-DAY2-DECISIVENESS.md` §6.3 carried six elided hashes under a
sentence saying they are "the **only** way to tell which day a live F6 file holds" — both days' F6
files carry the same `run_id`, so the hash is the identifier of last resort. One of the six was
`2e4220dc…9f32df51`: the eight characters at positions −9 to −2 of the real hash, one place short of
the end. It matched no sha256 in existence. The table's load-bearing row could not identify the file
it named, and the reason it looked unremarkable is that the six elisions were 7, 8 and 9 characters
long — with no stated rule, an off-by-one reads as just another length.

It surfaced by hand, while verifying a claim before publishing it, which is the method that does not
scale: there are 21 elided-hash citations in scope and nothing had ever checked one
(`feedback_prose_is_not_verified` — a number inside a sentence is checked by nobody; a hash is the
same defect with more digits and less chance a reader notices).

What is checked, and why this particular invariant
--------------------------------------------------
**A cited hash must be a prefix-and-suffix of some hash the repository can derive.** Deriving *which*
file a prose hash refers to is not mechanically possible — the sentence around it carries that, and
some cite evidence outside the tree — so this does not attempt it. Resolution against a *universe* is
the strongest check that needs no authoring, and it catches the whole failure mode that matters here:
a mangled, mistyped or stale truncation resolves to nothing.

The universe is two derived sets, never a list:

* the sha256 of **every in-scope file**, so a hash of a repository artefact resolves the day it lands;
* every 64-hex string **recorded** in an in-scope text file — `PREREGISTRATION.sha256`, a verdict
  file's `meta.oracle_registry`, a manifest. A document may legitimately cite the hash of something
  that is not a file here (an evidence record, a service response), and if the study recorded that
  hash anywhere, the citation is checkable against the record.

Measured 2026-08-20: 1,217 distinct hashes, 21 citations, **18 resolve**. The three that do not are
one real defect (above) and two sites citing one deliberately-unretained value — see
`SUPERSEDED_HASHES`. Precision matters more than reach for a guard nobody asked for: a gate with ten
false positives gets deleted rather than repaired (`feedback_audit_agent_caveats` is the same lesson
one layer up), and that is why the F6 table gets its own stricter arm below rather than every document
being forced into one elision rule.

What this deliberately does NOT check
-------------------------------------
* **That a citation names the right file.** `` `5e9d2ec6…e91ac257` `` resolving proves the hash is
  real, not that the sentence attributes it correctly. Only the F6 table below is checked that far,
  because there the pairing *is* the claim.
* **A full 64-character hash quoted in prose.** Those are already exact and a wrong one is a wrong
  hash, not a wrong truncation; they enter the universe rather than being cited from it.
* **Anything under a dated record.** A `session-logs/` file states what was true on its date, and a
  hash that has since been superseded is correct history. That exclusion removes zero citations today
  and the count is asserted rather than assumed (`feedback_vacuous_test_check`).
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "tests"))
from scan_scope import is_dated_record, out_of_scope, walk_in_scope  # noqa: E402  shared predicates

# `` `5e9d2ec6…e91ac257` `` — a backticked elision joined by U+2026. The bounds are wide enough to
# accept every convention in use (6-to-32 either side) and narrow enough that a bare hex word cannot
# match: the ellipsis is what makes it a citation of a hash rather than a hex value.
ELIDED_RE = re.compile(r"`([0-9a-f]{6,32})…([0-9a-f]{6,32})`")

# Text extensions whose 64-hex contents count as RECORDED hashes. Binary and OOXML are excluded on
# purpose: a hash inside a compiled artefact was not recorded by this study for anyone to cite.
RECORDED_IN = {".json", ".jsonl", ".md", ".sha256", ".yaml", ".yml", ".csv", ".txt", ".log", ".py"}
HEX64_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")

# 21 citations across 12 documents on 2026-08-20. A floor, because a scan that suddenly reads two
# citations found the wrong files (`feedback_zero_file_scan_is_error`).
MIN_CITATIONS = 15
MIN_UNIVERSE = 400

# Hashes that CANNOT resolve, and must not, with the reason each one is cited anyway. Registered
# rather than skipped by pattern: the shape of a stale hash and the shape of a mistyped one are
# identical, so the difference has to be written down by a human once.
SUPERSEDED_HASHES: dict[str, str] = {
    "38e0ba4a…0de9635c":
        "results/phase1/F5-7b.json as it stood BEFORE the 2026-08-20 redaction fix, cited in "
        "FUTURE-WORK.md and results/FINDING-P1-REDACTION-ENCODING.md as the 'before' side of a "
        "before -> after pair. Those bytes carried 20 unredacted account ids and are deliberately "
        "not retained anywhere in this repository, so this hash resolving would mean the leaking "
        "version had come back.",
}

# §6.3 of the F6 finding: case | live verdict | day-2 archive path | day-1 hash | day-2 hash.
F6_ROW_RE = re.compile(
    r"^\s*\|\s*(F6-\d+)\s*\|\s*(TRUE|FALSE|INCONCLUSIVE|RECORDED)\s*\|\s*"
    r"`(archive/[^`]+)`\s*\|\s*`([0-9a-f]+…[0-9a-f]+)`\s*\|\s*`([0-9a-f]+…[0-9a-f]+)`\s*\|",
    re.M)
F6_FINDING = ROOT / "results" / "FINDING-F6-DAY2-DECISIVENESS.md"
EXPECTED_F6_ROWS = 3          # F6-2, F6-5, F6-8 — the three verdicts that disagreed across days.
F6_ELISION = 8                # The finding states first-eight ... last-eight, uniformly.

# The one narrowing above, counted rather than trusted.
EXPECTED_DATED_CITATIONS = 0


@functools.lru_cache(maxsize=1)
def _universe() -> frozenset[str]:
    """Every sha256 this repository can derive, plus every one it has recorded.

    Cached and frozen: five arms below ask for it, the walk reads ~840 files, and nothing in a test
    run changes the tree — a mutable set handed to five callers is a way for one arm to alter what
    another one measures.
    """
    out: set[str] = set()
    n_files = 0
    for p in walk_in_scope():
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        n_files += 1
        out.add(hashlib.sha256(raw).hexdigest())
        if p.suffix in RECORDED_IN:
            out.update(HEX64_RE.findall(raw.decode("utf-8", "replace")))
    assert n_files > 300, (
        f"only {n_files} in-scope file(s) hashed — the walk read the wrong tree and every "
        f"'unresolved' below would be an artefact of that, not a finding")
    assert len(out) >= MIN_UNIVERSE, (
        f"universe holds {len(out)} hash(es), floor {MIN_UNIVERSE}: too small to be the real one")
    return frozenset(out)


def _docs() -> list[Path]:
    files = sorted(p for p in ROOT.rglob("*.md")
                   if not out_of_scope(p.relative_to(ROOT))
                   and not is_dated_record(p.relative_to(ROOT)))
    assert len(files) > 20, (
        f"only {len(files)} markdown file(s) in scope — a near-empty scan reports clean over the "
        f"whole repository, so this is an error and not a pass")
    return files


def _citations(paths: list[Path]) -> list[tuple[Path, str, str]]:
    out = []
    for p in paths:
        for pre, suf in ELIDED_RE.findall(p.read_text(encoding="utf-8")):
            out.append((p, pre, suf))
    return out


def _matches(universe: frozenset[str], pre: str, suf: str) -> list[str]:
    return [h for h in universe if h.startswith(pre) and h.endswith(suf)]


def test_every_elided_hash_citation_resolves_to_a_derivable_hash():
    universe = _universe()
    cites = _citations(_docs())
    assert len(cites) >= MIN_CITATIONS, (
        f"found {len(cites)} elided-hash citation(s), floor {MIN_CITATIONS}")
    bad = []
    for path, pre, suf in cites:
        if f"{pre}…{suf}" in SUPERSEDED_HASHES:
            continue
        if not _matches(universe, pre, suf):
            bad.append(f"{path.relative_to(ROOT)}: `{pre}…{suf}`")
    assert not bad, (
        "elided sha256 citation(s) match no hash this repository can derive or has recorded:\n    "
        + "\n    ".join(bad) +
        "\n  Either the truncation is wrong (check both ends — an off-by-one at the END is the "
        "defect this test was written for), the artefact is gone, or the value is genuinely "
        "superseded and belongs in SUPERSEDED_HASHES with a reason.")


def test_each_resolving_citation_identifies_exactly_one_hash():
    """A truncation short enough to match two hashes identifies neither.

    12 hex characters is 48 bits, so a collision among ~1,200 hashes would be extraordinary — which
    is exactly why this is worth asserting: the realistic way it fires is somebody eliding to four
    characters, and then a citation that "resolves" is not an identifier.
    """
    universe = _universe()
    ambiguous = []
    for path, pre, suf in _citations(_docs()):
        if f"{pre}…{suf}" in SUPERSEDED_HASHES:
            continue
        hits = _matches(universe, pre, suf)
        if len(hits) > 1:
            ambiguous.append(f"{path.relative_to(ROOT)}: `{pre}…{suf}` matches {len(hits)}")
    assert not ambiguous, (
        "elided hash(es) that do not identify a unique value:\n    " + "\n    ".join(ambiguous))


def test_every_superseded_hash_is_still_cited_and_still_unresolvable():
    """Both directions, or the register rots.

    A registered exception nobody re-checks is how a gate quietly stops covering something. If the
    citation is gone, the entry is dead weight; if it starts RESOLVING, then either the reason is
    wrong or — for this particular entry — the unredacted bytes are back in the tree, which is a
    P1 finding and not a test-maintenance chore.
    """
    universe = _universe()
    text = "\n".join(p.read_text(encoding="utf-8") for p in _docs())
    for key, reason in SUPERSEDED_HASHES.items():
        pre, suf = key.split("…")
        assert f"`{key}`" in text, (
            f"`{key}` is registered as superseded but no in-scope document cites it any more — "
            f"delete the entry rather than leaving a waiver for a citation that does not exist")
        hits = _matches(universe, pre, suf)
        assert not hits, (
            f"`{key}` is registered as UNRESOLVABLE but now resolves to {hits[0]}.\n  Registered "
            f"reason: {reason}\n  Read that reason before touching this test.")
        assert len(reason) >= 60, f"the reason for `{key}` is too short to be one"


def test_the_universe_is_derived_from_the_tree_in_both_directions():
    universe = _universe()
    known = ROOT / "PREREGISTRATION.yaml"
    assert known.is_file(), "PREREGISTRATION.yaml is missing; this arm's anchor is gone"
    assert hashlib.sha256(known.read_bytes()).hexdigest() in universe, (
        "the hash of a file that is plainly in scope is absent from the universe — the walk is not "
        "reading what it claims to")
    absent = "f" * 64
    assert absent not in universe, (
        "an all-f hash is in the universe, so it is not derived from anything")


def test_the_guard_catches_a_truncation_shifted_off_the_END_of_the_hash():
    """The real 2026-08-20 defect, verbatim, as the mutant.

    `2e4220dc…9f32df51` is F6-5's day-2 hash elided one character short of its end. It is the exact
    string the finding published, and a check that cannot tell it from `2e4220dc…f32df51c` would have
    passed the document unchanged.
    """
    universe = _universe()
    real = hashlib.sha256(
        (ROOT / "results/phase1/archive/F6-5__day2_indecisive_2026-08-19.json").read_bytes()
    ).hexdigest()
    assert _matches(universe, real[:8], real[-8:]), "the correct elision must resolve"
    assert not _matches(universe, real[:8], real[-9:-1]), (
        "an elision taken from positions -9..-2 resolved — the check is not looking at the end of "
        "the hash, and the defect it exists for would slip through")


def test_the_dated_record_exclusion_is_measured_not_assumed():
    dated = sorted(p for p in ROOT.rglob("*.md")
                   if not out_of_scope(p.relative_to(ROOT))
                   and is_dated_record(p.relative_to(ROOT)))
    assert dated, ("is_dated_record() matches no markdown file. If dated records are gone, delete "
                   "the exclusion rather than keeping one that does nothing.")
    hits = _citations(dated)
    assert len(hits) == EXPECTED_DATED_CITATIONS, (
        f"{len(hits)} elided-hash citation(s) now sit inside dated records, expected "
        f"{EXPECTED_DATED_CITATIONS}:\n    "
        + "\n    ".join(f"{p.relative_to(ROOT)}: `{a}…{b}`" for p, a, b in hits) +
        "\n  A hash in a dated log may be correct history. Confirm it was true on that date and "
        "raise EXPECTED_DATED_CITATIONS; do not edit the record to agree with today.")


# --- the F6 restore table: the one place a hash's PAIRING is the claim ------------------------------

def _f6_rows() -> list[tuple[str, str, str, str, str]]:
    rows = F6_ROW_RE.findall(F6_FINDING.read_text(encoding="utf-8"))
    assert len(rows) == EXPECTED_F6_ROWS, (
        f"parsed {len(rows)} row(s) from {F6_FINDING.name} §6.3, expected {EXPECTED_F6_ROWS}. A DROP "
        f"means the table was reformatted past F6_ROW_RE and is no longer checked at all, which is "
        f"the failure this file exists to prevent (`feedback_grep_the_claim_not_the_phrasing`).")
    return rows


def test_the_f6_restore_table_names_the_files_it_claims_to_name():
    """Case by case: the live file IS day 1, the archived file IS day 2, and each hash is that file's.

    This table is the published warrant for "a disagreement licenses no change to the published
    record". If the live F6-2 file were quietly the day-2 TRUE, `census.py` would derive
    TRUE 49 / FALSE 20 and the whitepaper's headline mix would be wrong — so the claim is worth a
    test rather than a sentence.
    """
    for case, verdict, day2_rel, cited_d1, cited_d2 in _f6_rows():
        live = ROOT / "results" / "phase1" / f"{case}.json"
        day2 = ROOT / "results" / "phase1" / day2_rel
        d1_glob = sorted((ROOT / "results" / "phase1" / "archive").glob(f"{case}__day1_*.json"))
        assert live.is_file(), f"{case}: no live verdict file at {live.relative_to(ROOT)}"
        assert day2.is_file(), f"{case}: the day-2 archive the table names is absent: {day2_rel}"
        assert len(d1_glob) == 1, f"{case}: expected exactly one __day1_ archive, found {d1_glob}"
        d1 = d1_glob[0]

        assert live.read_bytes() == d1.read_bytes(), (
            f"{case}: the live verdict file is NOT byte-identical to {d1.name}. The table says day 1 "
            f"is the verdict of record; if the live file is the day-2 one, the published verdict mix "
            f"moved on a measurement the finding itself calls indecisive.")
        got = json.loads(live.read_text(encoding="utf-8")).get("verdict")
        assert got == verdict, (
            f"{case}: the table's 'live now' column says {verdict}, the live file says {got}. Both "
            f"are claims about the same file and one of them is wrong.")
        for label, path, cited in (("day-1", d1, cited_d1), ("day-2", day2, cited_d2)):
            real = hashlib.sha256(path.read_bytes()).hexdigest()
            pre, suf = cited.split("…")
            assert (pre, suf) == (real[:F6_ELISION], real[-F6_ELISION:]), (
                f"{case} {label}: table cites `{cited}`, but {path.name} hashes to {real}.\n  §6.3 "
                f"states the elision is first-{F6_ELISION} ... last-{F6_ELISION}; check the END of "
                f"the string first.")


def test_mutation_the_f6_arm_fails_when_a_cited_hash_is_shifted(monkeypatch, tmp_path):
    """Proof the arm above can fail, using the historical defect as the mutation.

    The table is read through `_f6_rows`, so the mutation replaces the parsed rows rather than
    rewriting a live document — the same reason `test_deviation_register.py` patches its reader.
    """
    case, verdict, day2_rel, _, _ = _f6_rows()[0]
    d1 = sorted((ROOT / "results/phase1/archive").glob(f"{case}__day1_*.json"))[0]
    real = hashlib.sha256(d1.read_bytes()).hexdigest()
    shifted = f"{real[:8]}…{real[-9:-1]}"
    d2 = hashlib.sha256((ROOT / "results/phase1" / day2_rel).read_bytes()).hexdigest()
    monkeypatch.setattr(sys.modules[__name__], "_f6_rows",
                        lambda: [(case, verdict, day2_rel, shifted, f"{d2[:8]}…{d2[-8:]}")])
    with pytest.raises(AssertionError, match="check the END of"):
        test_the_f6_restore_table_names_the_files_it_claims_to_name()


def test_mutation_the_f6_arm_fails_when_the_live_file_is_not_day_one(monkeypatch, tmp_path):
    """The strongest claim in the table, mutated: a live file holding the day-2 verdict.

    Built by copying the real day-2 archive over a scratch tree rather than touching
    `results/phase1/`, because a mutation that edits a published verdict file and then fails to
    restore it is a worse outcome than an unchecked claim (`feedback_killed_harness_races_next`).
    """
    case, verdict, day2_rel, cited_d1, cited_d2 = _f6_rows()[0]
    fake_root = tmp_path / "results" / "phase1"        # mirrors the real layout the arm walks
    (fake_root / "archive").mkdir(parents=True)
    d1 = sorted((ROOT / "results/phase1/archive").glob(f"{case}__day1_*.json"))[0]
    d2_src = ROOT / "results/phase1" / day2_rel
    (fake_root / "archive" / d1.name).write_bytes(d1.read_bytes())
    (fake_root / day2_rel).write_bytes(d2_src.read_bytes())
    (fake_root / f"{case}.json").write_bytes(d2_src.read_bytes())      # <- the mutation
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    with pytest.raises(AssertionError, match="NOT byte-identical"):
        test_the_f6_restore_table_names_the_files_it_claims_to_name()
