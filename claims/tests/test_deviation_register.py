#!/usr/bin/env python3
"""`DEVIATIONS.md`'s entry ids are DERIVED, and every prose claim about how many there are is checked.

Why this file exists
--------------------
On 2026-08-20 `RECONNECT.md` said `DEVIATIONS.md` held "**42** `DEV-P4-*` entries". It held 43. The
sentence had been correct when written and went stale the moment the next entry landed, which is the
same defect `claims/tests/test_future_work_register.py` was written for one file over — **a number
inside a sentence is not checked by anything** (`feedback_prose_is_not_verified`). It surfaced by
reading, which is the method that does not scale, and it surfaced only because the entry being added
was itself about unchecked prose.

Two files now derive their own size. This one covers the second.

What is checked, and why each one
---------------------------------
* **Ids are unique and contiguous 1..N within each family.** `DEVIATIONS.md` carries five families
  (`P1`, `P2`, `P3`, `P4`, `SEAL`), and every other document in this repo cites entries by id — a
  duplicate makes two incidents answer to one citation, and a gap means an entry was removed, since
  nothing here is ever renumbered. Both are silent today. Families are DERIVED from the headings, not
  listed, so a new phase's entries are counted the day the first one is written rather than the day
  somebody remembers to add the letter (`feedback_scope_as_namelist`).
* **Every prose count matches the derived one.** A sentence that names a family and states "N
  `DEV-<family>-*` entries" must state that family's real size.
* **The number of prose sites is asserted exactly, not as a floor.** The regex below is
  phrasing-shaped, so a reworded sentence stops being recognised — and then the site count drops and
  this test fails, which is the intended behaviour: it forces a look rather than silently narrowing
  coverage (`feedback_grep_the_claim_not_the_phrasing`). A NEW site fails until it is read once by hand.

Scope, and the one narrowing: `lib/tests/scan_scope.py`'s `out_of_scope` keeps a virtualenv's markdown
out, and `is_dated_record` keeps dated `session-logs/` records out — a log saying "42 entries" was
correct on its date, and editing it to agree with today would falsify the record. **That narrowing
excludes no site today**, and rather than leave it as an inert waiver nobody measures
(`feedback_vacuous_test_check`) the excluded sites are counted and the count asserted at
`EXPECTED_DATED_SITES = 0`. The day a session log does state a count, this test says so and names it,
instead of quietly not reading it.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "tests"))
from scan_scope import is_dated_record, out_of_scope  # noqa: E402  shared predicates

REGISTER = ROOT / "DEVIATIONS.md"

# `## DEV-P4-42 — title`. The family is captured rather than enumerated: see the docstring.
ENTRY_RE = re.compile(r"^## DEV-([A-Z0-9]+)-(\d+)\b", re.M)

# `42 \`DEV-P4-*\` entries` — a count bound to the family it counts, so a sentence stating one
# family's size can never be validated against another's.
CLAIM_RE = re.compile(r"(?<![\w-])(\d{1,3})\s+`DEV-([A-Z0-9]+)-\*`\s+entries")

# Exactly this many prose sites currently state a family's entry count. Not a floor: see the docstring.
# 2026-08-20: RECONNECT.md x1 ("`DEVIATIONS.md` gained DEV-P4-42 and DEV-P4-43 — 43 `DEV-P4-*` entries").
EXPECTED_PROSE_SITES = 1

# How many count-claims sit inside DATED session records, which are excluded from the check above.
# Zero today. Asserted rather than assumed, so the exclusion is a measured scope and not a waiver
# whose effect nobody knows.
EXPECTED_DATED_SITES = 0


def _register_text() -> str:
    return REGISTER.read_text(encoding="utf-8")


def _families() -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(list)
    for m in ENTRY_RE.finditer(_register_text()):
        out[m.group(1)].append(int(m.group(2)))
    assert out, "no `## DEV-<family>-<n>` headings parsed — the heading format changed and every " \
                "count below is void"
    return dict(out)


def _md_files() -> list[Path]:
    files = sorted(p for p in ROOT.rglob("*.md")
                   if not out_of_scope(p.relative_to(ROOT))
                   and not is_dated_record(p.relative_to(ROOT)))
    assert len(files) > 20, (
        f"only {len(files)} markdown file(s) in scope — a near-empty scan would report clean over the "
        f"whole repo, so this is an error and not a pass")
    return files


def test_entry_ids_are_unique_within_each_family():
    for fam, nums in sorted(_families().items()):
        dupes = sorted({n for n in nums if nums.count(n) > 1})
        assert not dupes, (
            f"duplicate id(s) {dupes} in the DEV-{fam} family — other documents cite these ids, so two "
            f"incidents answering to one citation makes every reference to it ambiguous")


def test_entry_ids_are_contiguous_from_one_within_each_family():
    for fam, nums in sorted(_families().items()):
        missing = sorted(set(range(1, max(nums) + 1)) - set(nums))
        assert not missing, (
            f"DEV-{fam} id(s) {missing} are absent while DEV-{fam}-{max(nums)} exists. Nothing in this "
            f"file is renumbered once written, so a gap is a DELETED entry, not a spare number")


def test_every_prose_count_matches_the_derived_count():
    fams = _families()
    sites, bad = [], []
    for path in _md_files():
        for m in CLAIM_RE.finditer(path.read_text(encoding="utf-8")):
            claimed, fam = int(m.group(1)), m.group(2)
            where = f"{path.relative_to(ROOT)}: …{m.group(0)}…"
            sites.append(where)
            if fam not in fams:
                bad.append(f"{where}\n      names family DEV-{fam}, which has no entries")
            elif claimed != len(fams[fam]):
                bad.append(f"{where}\n      claims {claimed}, derived {len(fams[fam])}")
    assert not bad, (
        "prose states a DEVIATIONS count that no derivation supports:\n    " + "\n    ".join(bad))
    assert len(sites) == EXPECTED_PROSE_SITES, (
        f"found {len(sites)} prose site(s) stating a DEV family's entry count, expected "
        f"{EXPECTED_PROSE_SITES}:\n    " + "\n    ".join(sites) +
        "\n  A DROP means a sentence was reworded past CLAIM_RE, so it is no longer checked; a RISE "
        "means a new unchecked claim. Either way, read it and update EXPECTED_PROSE_SITES.")


def test_the_dated_record_exclusion_is_measured_not_assumed():
    """What the scope narrowing above actually removes, counted.

    The exclusion is right — a dated log states what was true on its date — but "right" and "doing
    something" are different claims, and only one of them was checked. Today it removes nothing; if
    that changes, the message names the file so a human can confirm the number was true when written
    rather than reflexively editing a record.
    """
    dated = sorted(p for p in ROOT.rglob("*.md")
                   if not out_of_scope(p.relative_to(ROOT))
                   and is_dated_record(p.relative_to(ROOT)))
    assert dated, ("is_dated_record() now matches no markdown file. If `session-logs/` no longer holds "
                   "dated records, delete the exclusion rather than leaving one that does nothing.")
    hits = [f"{p.relative_to(ROOT)}: …{m.group(0)}…"
            for p in dated for m in CLAIM_RE.finditer(p.read_text(encoding="utf-8"))]
    assert len(hits) == EXPECTED_DATED_SITES, (
        f"{len(hits)} count-claim(s) now sit inside dated records, expected {EXPECTED_DATED_SITES}:\n    "
        + "\n    ".join(hits) +
        "\n  Do NOT edit the log to agree with today. Confirm the number was true on that date and "
        "raise EXPECTED_DATED_SITES; if it was wrong when written, that is a finding, not a typo.")


# --- mutation arms: each one proves the corresponding check can fail -------------------------------

def _patched(monkeypatch, text: str):
    monkeypatch.setattr(sys.modules[__name__], "_register_text", lambda: text)


def test_mutation_a_duplicate_id_fails(monkeypatch):
    _patched(monkeypatch, "## DEV-P4-1 a\n## DEV-P4-1 b\n")
    with pytest.raises(AssertionError, match="duplicate id"):
        test_entry_ids_are_unique_within_each_family()


def test_mutation_a_missing_id_fails(monkeypatch):
    _patched(monkeypatch, "## DEV-P4-1 a\n## DEV-P4-3 c\n")
    with pytest.raises(AssertionError, match="are absent while"):
        test_entry_ids_are_contiguous_from_one_within_each_family()


def test_mutation_a_prose_count_that_disagrees_fails(monkeypatch):
    """The real check reads the repo, so the mutation shrinks the DERIVED count instead of editing a
    document: two entries in the P4 family makes every true prose claim about it false."""
    _patched(monkeypatch, "## DEV-P4-1 a\n## DEV-P4-2 b\n")
    with pytest.raises(AssertionError, match="no derivation supports"):
        test_every_prose_count_matches_the_derived_count()


def test_mutation_the_claim_regex_binds_the_count_to_its_own_family():
    """A count and a family name in one sentence must travel together.

    Without the binding, "43 `DEV-P4-*` entries and 13 `DEV-SEAL-*` entries" offers two numbers and two
    families, and any pairing validates (`feedback_two_numbers_two_claims`). Also asserted: a bare id
    reference is not a count, or every citation of `DEV-P4-42` would read as a claim of 42 entries.
    """
    both = "43 `DEV-P4-*` entries and 13 `DEV-SEAL-*` entries"
    assert [(m.group(1), m.group(2)) for m in CLAIM_RE.finditer(both)] == [("43", "P4"), ("13", "SEAL")]
    assert not CLAIM_RE.search("see DEV-P4-42 and DEV-P4-43")
    assert not CLAIM_RE.search("43 entries")
