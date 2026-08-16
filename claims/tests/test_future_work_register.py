#!/usr/bin/env python3
"""The deficiency register's size and shape are DERIVED, and every prose claim about them is checked.

Why this file exists
--------------------
`FUTURE-WORK.md` grew 18 -> 21 -> 22 -> 28 -> 29 items over two days. Each time, the number was
restated by hand in prose somewhere else: `WHITEPAPER.md` ("the full N-item deficiency register"),
`RECONNECT.md` twice, and the handover bundle's README. On 2026-08-16 the register had 29 items while
the whitepaper said 28 and RECONNECT said 28 in two places — nothing failed, because **a number
inside a sentence is not checked by anything** (`feedback_prose_is_not_verified`). The bundle's README
still said 21, six items and one day behind, and that is how it was found: by reading, which is the
method that does not scale.

So the count is derived here from the headings, and the prose is compared against it.

What is checked, and why each one
---------------------------------
* **Item numbers are unique and contiguous 1..N.** The file's own header says numbers are "stable
  identifiers, not positions" and that items are placed in the tier they belong to "so the numbering
  is out of order on purpose". Out of order is fine; a gap means an item was deleted (the file says
  nothing is renumbered, so a gap is a lost item) and a duplicate means two items answer to one
  citation. Both are silent today.
* **Every prose count matches a derived one.** A sentence that mentions the register and contains
  "<number> item(s)" must state either the total or, if it also says "Tier", that tier's derived size.
  Tier counts are derived too, so "Tier 1 currently holds 5 items" is checked rather than trusted.
* **A cited membership list matches the tier's real membership.** `WHITEPAPER.md` names Tier 1's items
  explicitly (`holds 5 items (1, 2, 3, 19, 27)`). Adding a Tier-1 item without touching the paper is
  exactly the mistake this catches, and it is the one that matters most: Tier 1 is defined as "the
  paper is wrong or self-contradictory until these are fixed".
* **The number of prose sites is asserted exactly, not as a floor.** This is the part that survives a
  rewording. The regexes below are phrasing-shaped, so a rephrased sentence stops being recognised —
  and then the site count drops and the test fails, which is the intended behaviour: it forces a look
  rather than silently narrowing coverage (`feedback_grep_the_claim_not_the_phrasing`,
  `feedback_scope_as_namelist`). A NEW site likewise fails until it is checked once by hand.

Scope comes from `lib/tests/scan_scope.py`, the same predicate the repo-wide `*.py` scanners use, so a
new virtualenv cannot make this test read a dependency's markdown (DEV-P4-42).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "tests"))
from scan_scope import out_of_scope  # noqa: E402  shared scope predicate; see its docstring

REGISTER = ROOT / "FUTURE-WORK.md"

# `### 12. Title` — the heading form every item uses.
ITEM_RE = re.compile(r"^### (\d+)\. ", re.M)
TIER_RE = re.compile(r"^## (Tier \d+)\b", re.M)

# A prose claim about a count: a number immediately followed by "item"/"items". The lookbehind rejects
# `Tier-1 item 1`, where the "1 item" is a REFERENCE to one item, not a count of one — without it the
# guard read that sentence as claiming the register holds a single item.
COUNT_RE = re.compile(r"(?<![\w-])(\d{1,3})[-\s]items?\b")
# `holds 5 items (1, 2, 3, 19, 27)` — a count AND its membership.
MEMBERSHIP_RE = re.compile(r"(?<![\w-])(\d{1,3})[-\s]items?\s*\(([\d,\s]+)\)")

# Sentences that are talking about this register at all.
ABOUT_RE = re.compile(r"FUTURE-WORK|deficiency register", re.I)

# Exactly this many prose sites currently state a register count. Not a floor: see the docstring.
# 2026-08-16: RECONNECT.md x2 (the total), WHITEPAPER.md x2 (the total, and Tier 1's size + membership).
EXPECTED_PROSE_SITES = 4


def _register_text() -> str:
    return REGISTER.read_text(encoding="utf-8")


def _items() -> list[int]:
    return [int(m.group(1)) for m in ITEM_RE.finditer(_register_text())]


def _tiers() -> dict[str, list[int]]:
    """Item numbers per tier heading, in document order."""
    text = _register_text()
    bounds = [(m.group(1), m.start()) for m in TIER_RE.finditer(text)]
    assert bounds, "no `## Tier N` headings found — the register's structure changed"
    out: dict[str, list[int]] = {}
    for i, (title, start) in enumerate(bounds):
        end = bounds[i + 1][1] if i + 1 < len(bounds) else len(text)
        out[title] = [int(m.group(1)) for m in ITEM_RE.finditer(text[start:end])]
    return out


def _md_files() -> list[Path]:
    files = sorted(p for p in ROOT.rglob("*.md")
                   if not out_of_scope(p.relative_to(ROOT)))
    assert len(files) > 20, (
        f"only {len(files)} markdown file(s) in scope — a near-empty scan would report clean over the "
        f"whole repo, so this is an error and not a pass")
    return files


def _sentences(text: str) -> list[str]:
    """Coarse sentence split, also breaking at list-item starts so two bullets are never one sentence."""
    return re.split(r"(?<=[.!?])\s+|\n\n+|\n(?=[|*\-\d] )", text)


def _claim_sites() -> list[tuple[Path, str]]:
    """Every (file, sentence) where prose states a count of register items.

    Gating is at PARAGRAPH level, qualification at SENTENCE level, and the split matters: the
    whitepaper writes "…is `FUTURE-WORK.md`. Its Tier 1 … currently holds 5 items (1, 2, 3, 19, 27)".
    The words that identify the register and the count that must be checked are in DIFFERENT sentences,
    so a sentence-scoped gate found zero sites and passed — a guard that reads nothing
    (`feedback_zero_file_scan_is_error`). Sentences still decide whether "Tier" qualifies a count,
    because a neighbouring sentence's tier must not license a wrong total.
    """
    out = []
    for path in _md_files():
        for para in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
            if not ABOUT_RE.search(para):
                continue
            for sentence in _sentences(para):
                if COUNT_RE.search(sentence) or MEMBERSHIP_RE.search(sentence):
                    out.append((path, sentence))
    return out


def test_item_numbers_are_unique():
    items = _items()
    dupes = sorted({n for n in items if items.count(n) > 1})
    assert not dupes, (
        f"duplicate item number(s) {dupes} in FUTURE-WORK.md — other files cite these numbers, so two "
        f"items answering to one citation makes every reference to it ambiguous")


def test_item_numbers_are_contiguous_from_one():
    items = sorted(_items())
    assert items, "no `### N.` items parsed — the heading format changed and every count below is void"
    missing = sorted(set(range(1, max(items) + 1)) - set(items))
    assert not missing, (
        f"item number(s) {missing} are absent while {max(items)} exists. The register states that "
        f"nothing is renumbered once written, so a gap is a DELETED item, not a spare number")


def test_every_item_belongs_to_exactly_one_tier():
    tiered = [n for nums in _tiers().values() for n in nums]
    assert sorted(tiered) == sorted(_items()), (
        f"{len(_items())} items parsed but {len(tiered)} sit under a tier heading — an item outside "
        f"every tier is unranked, and this register's whole ordering claim is by severity")


def test_every_tier_has_at_least_one_item():
    """A tier with no `### N.` item is work nothing can cite, count, or test.

    Tier 5 was exactly this on 2026-08-15: four wrong citation anchors written as a table under a
    heading that says "before anything is published", carrying no item number — so `WHITEPAPER.md`'s
    "the full 29-item deficiency register" excluded the most schedule-critical tier in the file and was
    wrong about the word "full". It is item 30 now. This assertion is what stops the next one."""
    empty = [k for k, v in _tiers().items() if not v]
    assert not empty, (
        f"tier(s) {empty} contain no numbered item. Unnumbered work is uncitable and uncountable, so it "
        f"silently sits outside every 'N-item register' claim in the repo")


def test_every_prose_count_matches_a_derived_count():
    total = len(_items())
    tiers = _tiers()
    tier_sizes = {len(v) for v in tiers.values()}
    sites, bad = [], []
    for path, sentence in _claim_sites():
        for m in COUNT_RE.finditer(sentence):
            claimed = int(m.group(1))
            where = f"{path.relative_to(ROOT)}: …{' '.join(sentence.split())[:110]}…"
            sites.append(where)
            # A sentence naming a tier may legitimately state that tier's size instead.
            allowed = {total} | (tier_sizes if re.search(r"\btier\b", sentence, re.I) else set())
            if claimed not in allowed:
                bad.append(f"{where}\n      claims {claimed}, derived {sorted(allowed)}")
    assert not bad, (
        "prose states a register count that no derivation supports:\n    " + "\n    ".join(bad))
    assert len(sites) == EXPECTED_PROSE_SITES, (
        f"found {len(sites)} prose site(s) stating a register count, expected "
        f"{EXPECTED_PROSE_SITES}:\n    " + "\n    ".join(sites) +
        "\n  A DROP means a sentence was reworded past these regexes, so it is no longer checked; a "
        "RISE means a new unchecked claim. Either way, read it and update EXPECTED_PROSE_SITES.")


def test_a_cited_tier_membership_list_matches_the_tier():
    tiers = _tiers()
    checked = 0
    for path, sentence in _claim_sites():
        tier = re.search(r"Tier (\d+)", sentence, re.I)
        if not tier:
            continue
        for m in MEMBERSHIP_RE.finditer(sentence):
            cited = sorted(int(x) for x in re.findall(r"\d+", m.group(2)))
            key = f"Tier {tier.group(1)}"
            assert key in tiers, f"{path.relative_to(ROOT)} cites {key}, which the register lacks"
            assert cited == sorted(tiers[key]), (
                f"{path.relative_to(ROOT)} says {key} holds {cited}; the register says "
                f"{sorted(tiers[key])}. Tier 1 is defined as the items that make the paper wrong "
                f"until fixed, so a stale list there is a stale claim about the paper")
            assert int(m.group(1)) == len(tiers[key]), (
                f"{path.relative_to(ROOT)} says {key} holds {m.group(1)} items but lists {len(cited)}")
            checked += 1
    assert checked >= 1, (
        "no cited tier-membership list was found to check. WHITEPAPER.md carried one; if it was "
        "reworded this assertion is the only thing that notices")


# --- mutation arms: each one proves the corresponding check can fail -------------------------------

def _patched(monkeypatch, text: str):
    monkeypatch.setattr(sys.modules[__name__], "_register_text", lambda: text)


def test_mutation_a_duplicate_item_number_fails(monkeypatch):
    _patched(monkeypatch, "## Tier 1\n### 1. a\n### 1. b\n")
    with pytest.raises(AssertionError, match="duplicate item number"):
        test_item_numbers_are_unique()


def test_mutation_a_missing_item_number_fails(monkeypatch):
    _patched(monkeypatch, "## Tier 1\n### 1. a\n### 3. c\n")
    with pytest.raises(AssertionError, match="are absent while"):
        test_item_numbers_are_contiguous_from_one()


def test_mutation_an_item_outside_every_tier_fails(monkeypatch):
    _patched(monkeypatch, "### 1. before any tier\n## Tier 1\n### 2. b\n")
    with pytest.raises(AssertionError, match="sit under a tier heading"):
        test_every_item_belongs_to_exactly_one_tier()


def test_mutation_an_empty_tier_fails(monkeypatch):
    _patched(monkeypatch, "## Tier 1\n### 1. a\n## Tier 2\nprose only, no numbered item\n")
    with pytest.raises(AssertionError, match="contain no numbered item"):
        test_every_tier_has_at_least_one_item()


def test_mutation_a_tier_reference_is_not_read_as_a_count():
    """`Tier-1 item 1` must not be mistaken for a count; `29 items` and `29-item` must still be."""
    assert not COUNT_RE.search("Tier-1 item 1 is CLOSED")
    assert not COUNT_RE.search("see item 29 and item 30")
    assert [m.group(1) for m in COUNT_RE.finditer("29 items in 5 tiers")] == ["29"]
    assert [m.group(1) for m in COUNT_RE.finditer("the full 29-item register")] == ["29"]


def test_mutation_a_prose_count_that_disagrees_fails(monkeypatch, tmp_path):
    """The real check reads the repo, so the mutation shrinks the DERIVED count instead of editing a
    file: a register of 2 items makes every true prose claim false, which is the same asymmetry."""
    _patched(monkeypatch, "## Tier 1\n### 1. a\n### 2. b\n")
    with pytest.raises(AssertionError, match="no derivation supports"):
        test_every_prose_count_matches_a_derived_count()
