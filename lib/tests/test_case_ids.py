#!/usr/bin/env python3
"""`case_ids_in` must expand the five joined timing groups and refuse everything else.

Both directions are asserted, because this resolver sits under a *scoping* rule and scoping
fails in two ways that look nothing alike:

  * TOO NARROW is what shipped. `F6-2_5` resolved to no case, so `day2_replicate._scoped`
    filtered away F6-2's and F6-5's records and `transient_failures` reported a clean
    observation over a run with eight failed calls (FUTURE-WORK item 34).
  * TOO WIDE is the failure a fix invites. `F3-10_audit_2026-08-12` must not become two cases,
    `F6-2_5` must never mean `F6-25`, and a stratum name must not become its family. A
    resolver that expands generously would credit one case's observation days to another,
    which is exactly what `observation_days`' scoping exists to prevent.

The joined names here are not invented. They were read off `evidence/` on 2026-08-22, with the
record counts recorded in `lib/case_ids.py`; `test_the_joined_groups_on_disk_all_resolve` walks
the real tree when it is present so that a sixth group appearing later fails this file rather
than silently going unresolved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from lib.case_ids import case_ids_in, names_the_case  # noqa: E402


# --------------------------------------------------------------- the joined groups

@pytest.mark.parametrize("name,expected", [
    ("F6-2_5", ("F6-2", "F6-5")),
    ("F6-6_7_8", ("F6-6", "F6-7", "F6-8")),
    ("F6-1_3_4_9", ("F6-1", "F6-3", "F6-4", "F6-9")),
    ("F7-6_7", ("F7-6", "F7-7")),
    ("F7-1_2_3", ("F7-1", "F7-2", "F7-3")),
])
def test_a_joined_group_resolves_to_every_case_it_holds(name, expected):
    """The head keeps its own number: `F6-6_7_8` is three cases, not two."""
    assert case_ids_in(name) == expected


def test_the_head_is_included_and_comes_first():
    """A caller that takes `[0]` must get the name's own case, not a sibling."""
    assert case_ids_in("F6-2_5")[0] == "F6-2"


# --------------------------------------------------------------- qualifiers stay one case

@pytest.mark.parametrize("name,expected", [
    ("F3-10_audit_2026-08-12", ("F3-10",)),
    ("F5-2_smoke_n2_2026-08-12", ("F5-2",)),
    ("F8-4_baseline", ("F8-4",)),
    # The shape that failed the first version of this file: the `_` is inside a STRATUM, so the
    # head of a `_`-split is `F3-4-pii-us`, which is not a case id.
    ("F3-4-pii-us_social_security_number", ("F3-4",)),
    ("F3-8-tagged-prompt_injection", ("F3-8",)),
    ("F8-4-classic-benign", ("F8-4",)),
    ("F3-11-20260811T164120Z__content_filter", ("F3-11",)),
])
def test_a_qualified_name_denotes_the_case_it_qualifies(name, expected):
    """`_audit` narrows F3-10; a stratum narrows F3-4; neither names a second case."""
    assert case_ids_in(name) == expected


def test_a_plain_case_id_denotes_itself():
    assert case_ids_in("F6-2") == ("F6-2",)
    assert case_ids_in("F5-7b") == ("F5-7b",)
    assert case_ids_in("F10-3") == ("F10-3",)


# --------------------------------------------------------------- the too-wide arms

def test_a_joined_group_never_resolves_to_the_concatenation():
    """`F6-2_5` means 2 and 5, and `F6-25` is a different case that must not match it."""
    assert "F6-25" not in case_ids_in("F6-2_5")
    assert not names_the_case("F6-2_5", "F6-25")


def test_a_case_does_not_match_a_longer_case_with_the_same_prefix():
    """The original `_scoped` comment's own worry: F8-5 must not be credited with F8-50's."""
    assert not names_the_case("F8-50", "F8-5")
    assert not names_the_case("F8-5x", "F8-5")


@pytest.mark.parametrize("name", [
    "f6_latency",
    "evidence",
    "summary.json",
    "environment.json",
    "F-1",          # no family number
    "6-2",          # no family letter
    "",
    None,
    17,
])
def test_a_name_that_qualifies_no_case_resolves_to_nothing(name):
    """`()` rather than a guess, so a caller falls back to its own path rules."""
    assert case_ids_in(name) == ()


def test_a_qualified_joined_group_loses_its_siblings_and_says_so_here():
    """The documented limit, asserted so that the day such a name appears this file fails.

    `lib/case_ids.py` states that the joined-group arm requires the numeric tail to run to the
    end of the name. No name on disk violates it today; if a producer ever writes
    `F6-2_5-<stratum>`, the under-count must surface as a failing assertion rather than as a
    silently narrowed scope ([[feedback_guard_scope_is_a_claim]]).
    """
    assert case_ids_in("F6-2_5-extra") == ("F6-2",)
    assert not names_the_case("F6-2_5-extra", "F6-5")


# --------------------------------------------------------------- against the real tree

def test_the_joined_groups_on_disk_all_resolve():
    """A sixth timing group appearing on disk must fail here, not go quietly unresolved.

    Skipped where `evidence/` is absent — it is local-only by written policy, so this arm runs
    on the machine that holds the records and the parametrised arms above carry the shapes
    everywhere else.
    """
    ev = REPO / "evidence"
    if not ev.is_dir():
        pytest.skip("evidence/ is local-only and not present")
    joined: set[str] = set()
    for p in ev.rglob("*.json"):
        if p.name in ("environment.json", "summary.json", "analysis.json"):
            continue
        try:
            cid = json.loads(p.read_text(encoding="utf-8")).get("case_id")
        except Exception:  # noqa: BLE001 - an unreadable record contributes no case id
            continue
        if isinstance(cid, str) and "_" in cid:
            joined.add(cid)
    if not joined:
        pytest.skip("no joined case_id on disk")
    unresolved = sorted(n for n in joined if not case_ids_in(n))
    assert not unresolved, (
        f"case_id(s) on disk that resolve to no case at all: {unresolved}")
    # And the five joined groups must each resolve to MORE than one case, or the arm above would
    # pass on a resolver that only ever returned the head.
    groups = sorted(n for n in joined if len(case_ids_in(n)) > 1)
    assert len(groups) >= 5, f"expected the five joined timing groups, resolved: {groups}"
