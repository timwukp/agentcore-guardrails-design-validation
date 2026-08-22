#!/usr/bin/env python3
"""Which case ids a name denotes — because some names denote more than one.

F6's and F7's latency producers write one evidence directory per **timing group**, not per
case, because the cases in a group share a single measured sweep: `F6-2_5` holds F6-2's and
F6-5's records, `F6-6_7_8` holds three cases', `F6-1_3_4_9` four. The record's own `case_id`
field carries the same joined string, so the ambiguity is not a path-naming detail that a
reader can route around — it is in the data. Measured over `evidence/` on 2026-08-22:

| name           | records |
|----------------|---------|
| `F6-6_7_8`     |   9,287 |
| `F6-2_5`       |   5,631 |
| `F6-1_3_4_9`   |   4,033 |
| `F7-1_2_3`     |     547 |
| `F7-6_7`       |     199 |

Every consumer that asks "is this record F6-6's?" therefore has to expand the name, and the
two consumers that did not each failed in its own direction:

* `day2_replicate._scoped` requires a path component to *be* the case id or to start
  `<case>-`, so it matched neither `F6-2_5` nor `F6-6_7_8`. On 2026-08-19 that made
  `transient_failures` report a clean observation for all nine F6 cases over a run holding
  **eight** failed calls (FUTURE-WORK item 34).
* `check_amendment_readiness.observation_days` compares `case_id` for equality, so a finding
  that declares `F6-6` — the id the document and the verdict file use — matches **none** of
  its own 9,287 records, and the replication gate reports it as resting on records that were
  never written.

WHY THIS IS A RULE AND NOT A LIST
---------------------------------
The larger half of the `_`-bearing population must NOT expand, so a list of the five known
group names would be a list that the next producer defeats ([[feedback_scope_as_namelist]]).
`_` is also the ordinary separator for a **qualifier** that narrows one case, and the first
attempt at this file enumerated the qualifier shapes it knew — `F3-10_audit_2026-08-12` (63
records), `F5-2_smoke_n2_2026-08-12` — and was immediately failed by its own real-tree arm on a
third shape nobody had listed: `F3-4-pii-us_social_security_number` and
`F3-8-tagged-prompt_injection`, 22 and 4 names, where the `_` sits inside a *stratum* rather
than after the case. That is the enumeration defect one level up, so the rule reads the shape
instead:

* **a joined timing group** — the head is a complete case id and *every* remaining
  `_`-separated token is a bare number. The name denotes all of them, head included:
  `F6-6_7_8` -> F6-6, F6-7, F6-8.
* **otherwise the name QUALIFIES one case**: the shortest prefix that is a complete case id
  and is followed by a separator (`-` or `_`). `F3-4-pii-ip_address` -> F3-4,
  `F3-10_audit_2026-08-12` -> F3-10, `F3-11-20260811T164120Z__content_filter` -> F3-11,
  `F8-4-classic-benign` -> F8-4.
* **otherwise nothing.** `f6_latency` is not a case.

Requiring the separator is what keeps it narrow: `F6-2_5` never resolves to `F6-25`, `F6-25`
never matches `F6-2_5`, and `F8-50` is never credited to F8-5 — the failure the original
`_scoped` comment was written to prevent, and which this file must not reintroduce while
widening.

WHAT THIS DELIBERATELY DOES NOT RESOLVE
---------------------------------------
Stated rather than left to be discovered, because the docstring excusing where a guard need
not look is where the next instance hides ([[feedback_guard_scope_is_a_claim]]).

* A **qualified joined group** — `F6-2_5-something` — resolves to F6-2 alone and loses F6-5,
  because the joined-group arm requires the numeric tail to run to the end of the name. No such
  name exists on disk today; a test pins the behaviour so that the day one appears, the loss is
  a failing assertion rather than a quiet under-count.
* A **case id with a non-`[a-z]` variant** (`F5-7B`, `F5_7b`) is not a case id here. The
  records use the id the producer passed to `lib/evidence`, and `check_amendment_readiness`
  already reports the `F5-7A`-vs-`F5-7a` mismatch by name; making this resolver case-insensitive
  would hide that report rather than fix it.
"""

from __future__ import annotations

import re

# A complete case id: family, number, optional lowercase variant letter. `F5-7b`, `F10-3`,
# `F6-2`. Anchored at both ends so a stamped name (`F3-11-20260811T164120Z`) does not match.
CASE_ID_RE = re.compile(r"^(F\d+)-(\d+)([a-z]?)$")


SEPARATORS = "-_"


def case_ids_in(name: object) -> tuple[str, ...]:
    """Every case id `name` denotes, head first; `()` when it denotes none.

    One element for a plain id (`F6-2`) or a qualified one (`F3-4-pii-ip_address`), several for
    a joined timing group (`F6-6_7_8`). `()` for a name that qualifies no case, which is the
    answer that lets a caller fall back to its own rules rather than receiving a guess.
    """
    if not isinstance(name, str) or not name:
        return ()
    # A joined timing group, checked first because its tail LOOKS like a qualifier: the head is
    # a case id and every `_`-separated token after it is a bare number.
    head, *tail = name.split("_")
    m = CASE_ID_RE.match(head)
    if m and tail and all(t.isdigit() for t in tail):
        family = m.group(1)
        return (head, *(f"{family}-{t}" for t in tail))
    # Otherwise the name qualifies at most one case: itself, or the shortest case-id prefix
    # standing before a separator. The separator is load-bearing — without it `F6-2` would be a
    # prefix of `F6-25` and one case would be credited with another's records.
    if CASE_ID_RE.match(name):
        return (name,)
    for i in range(1, len(name)):
        if name[i] in SEPARATORS and CASE_ID_RE.match(name[:i]):
            return (name[:i],)
    return ()


def names_the_case(name: object, case: str) -> bool:
    """Does `name` denote `case`? The question both broken consumers were really asking."""
    return case in case_ids_in(name)
