#!/usr/bin/env python3
"""F0-1: turn the archived §10 reference check into the SEALED oracle's verdict.

Analysis only, **$0, offline**. This script makes no HTTP request. It reads the artifact
`02_check_references.py` archived at `results/FINDING-F0-1-references.json` and emits
`results/phase1/F0-1.json` through `lib/phase1.emit`.

Why this exists
---------------
Same gap as F5-7a, and found by the same reconciliation: F0-1 was fully measured on
2026-08-09 — 24 rows, 24 HTTP 200s, 24 title matches — and `results/phase1/` had no record
for it, so `census.py` counted family F0 at 0/1 while the artifact and the document's
"**Result: 24/24 verified.**" both said it was done. `02_check_references.py` predates the
phase-1 record discipline: its docstring calls its own output "the evidence store", which
was true and was not the whole job. See DEV-P4-33.

What this script refuses to launder
-----------------------------------
The archived artifact is trusted for its *observations* and for nothing else. Three
properties of the producer make a naive read unsafe, and each has a refusal here:

1. **`--limit` writes a partial artifact that looks complete.** `n_checked` is
   `len(results)` after truncation, and nothing in the file records that a smoke run
   produced it. So `n` is checked against the §10 row count derived independently from
   `claims/triage.csv` — 24 — and a short artifact is refused rather than published with a
   quietly smaller denominator.

2. **A single unreachable URL scores as a document failure.** In the producer,
   `status is None` gives `ok=False`, so one DNS hiccup among 24 would publish FALSE
   against the document. "Our network failed" and "the document's link is dead" are
   different facts and only the second is the document's problem, so `unreachable > 0` is a
   refusal, not a FALSE. (The archived run has 0, which is why this has never bitten.)

3. **`pass` is the artifact's own opinion.** It is recomputed here from `http_status` and
   `title_match`, and a disagreement with the stored boolean is fatal. A verdict that reads
   a summary field is the artifact vouching for itself.

An unrecognised `title_match` string is also fatal, for the reason it is fatal in
`f5_redteam/07a_verdict.py`: a new outcome folded into "pass" by default would turn a
weakening of the instrument into a stronger-looking verdict.

Two branches counted as passes, and why the record says how many rode them
-------------------------------------------------------------------------
The producer treats `unverifiable (title is all stopwords)` and
`unverifiable (page has no title)` as passes: a row it cannot check for content match is
scored on the HTTP 200 alone. That is defensible — it does not invent a match — but it is
strictly weaker than a real title overlap, so the record reports the per-branch counts. All
24 rows are on the strong branch, and stating that is what makes "24/24" mean 24 checked
titles rather than 24 rows of which some were waved through.

One dated observation, of a property that can change
----------------------------------------------------
Link liveness is time-varying, so this record is a verdict about 2026-08-09 and says so.
A re-check must not overwrite the archived artifact — it is the only observation of that
date, and `claims/tests/test_finding_numbers.py` pins its numbers against the document's
"24/24" — so replication belongs in a second dated file rather than in place.

Usage
-----
    python3 claims/02_references_verdict.py --dry-run
    python3 claims/02_references_verdict.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import oracle as O                                                   # noqa: E402
import phase1 as P                                                   # noqa: E402

CASE = "F0-1"
ARTIFACT = ROOT / "results" / "FINDING-F0-1-references.json"
TRIAGE = ROOT / "claims" / "triage.csv"

# The observation date of the archived artifact. Written down because the artifact itself
# records no timestamp and a file mtime is not provenance — it survives a copy, a checkout
# and a `touch`, none of which are observations.
OBSERVED_ON = "2026-08-09"

# Every `title_match` string `02_check_references.py` can write, and whether the row it
# describes counts as the document's claim holding. `strong` marks the branch where the
# page title was actually compared and overlapped; the two `unverifiable` branches are
# passes on the HTTP 200 alone.
TITLE_MATCH: dict[str, tuple[bool, bool, str]] = {
    # token: (counts_as_pass, is_strong, why)
    "yes": (
        True, True,
        "the page title shares at least one content word with the row's stated title, "
        "which is the whole of the oracle's second clause"),
    "NO": (
        False, True,
        "the page resolved and is about something else — the failure the oracle calls "
        "worse than a 404, because the reader believes they were handed a source"),
    "unverifiable (title is all stopwords)": (
        True, False,
        "the row title reduces to nothing under the stopword list, so there is no content "
        "word to match on. Scored on the HTTP 200 alone: weaker than a match, but it does "
        "not invent one"),
    "unverifiable (page has no title)": (
        True, False,
        "the page served 200 with no <title> element, so the row's claim about what lives "
        "there cannot be checked. Scored on the HTTP 200 alone"),
}


class Refusal(RuntimeError):
    """A precondition that makes the verdict unsafe to compute. Never a verdict."""


def expected_rows(triage: Path = TRIAGE) -> int:
    """How many §10 reference rows exist, derived from the triage table.

    Derived rather than pinned at 24, so that adding a reference to §10 makes the artifact
    short — and therefore refused — instead of making a stale denominator look full.
    """
    with triage.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["anchor"] == "s10" and r["unit_type"] == "trow"]
    if not rows:
        raise Refusal(
            f"{triage} holds no §10 table rows, so the denominator cannot be derived. "
            f"A count of 0 here would make any artifact look complete")
    return len(rows)


def load_artifact(path: Path = ARTIFACT) -> dict[str, Any]:
    if not path.is_file():
        raise Refusal(
            f"{path} does not exist. This script analyses an ARCHIVED observation and "
            f"collects none of its own; run `python3 claims/02_check_references.py` first "
            f"($0, read-only HTTP)")
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("case") != CASE:
        raise Refusal(f"{path} declares case {body.get('case')!r}, not {CASE!r}")
    rows = body.get("results") or []
    if not rows:
        raise Refusal(f"{path} records no per-URL rows; a summary is not evidence a reader "
                      f"can re-check")
    return body


def recompute(row: dict[str, Any]) -> tuple[bool, bool]:
    """Re-derive (passes, is_strong) for one row from its recorded observations."""
    match = str(row.get("title_match", ""))
    if match not in TITLE_MATCH:
        raise Refusal(
            f"row {row.get('claim_id')!r} carries title_match {match!r}, which "
            f"{Path(__file__).name} does not classify. A string this file has never seen "
            f"may not be folded into 'pass' by default: classify it deliberately, with the "
            f"reason, and add an arm to tests/test_references_verdict.py. Known: "
            f"{sorted(TITLE_MATCH)}")
    counts_as_pass, is_strong, _why = TITLE_MATCH[match]
    return (row.get("http_status") == 200 and counts_as_pass), is_strong


def build(path: Path = ARTIFACT, triage: Path = TRIAGE) -> dict[str, Any]:
    """Everything except the writing, so a test can assert on it without touching results/."""
    body = load_artifact(path)
    rows = body["results"]
    want = expected_rows(triage)

    if len(rows) != want:
        raise Refusal(
            f"the artifact holds {len(rows)} row(s) and §10 has {want} reference row(s). A "
            f"short artifact is what `02_check_references.py --limit` writes, and it "
            f"records nothing to distinguish itself from a full run — so it cannot be "
            f"published with {len(rows)} as the denominator")
    if body.get("n_checked") != len(rows):
        raise Refusal(f"the artifact's n_checked is {body.get('n_checked')} and it holds "
                      f"{len(rows)} rows; the summary disagrees with the evidence")

    unreachable = int(body.get("unreachable") or 0)
    if unreachable:
        raise Refusal(
            f"{unreachable} of {len(rows)} URL(s) were unreachable. In the producer an "
            f"unreachable URL scores as a row failure, which would publish FALSE against "
            f"the document for what may be OUR network — the same discipline as exiting 3 "
            f"on a total network failure, applied to a partial one. Re-run the check from a "
            f"working network before a verdict is derived")

    failures, weak = [], []
    for row in rows:
        passes, is_strong = recompute(row)
        if passes != bool(row.get("pass")):
            raise Refusal(
                f"row {row.get('claim_id')!r} records pass={row.get('pass')!r} and its own "
                f"observations (HTTP {row.get('http_status')!r}, "
                f"title_match {row.get('title_match')!r}) give {passes}. The artifact "
                f"disagrees with itself; do not publish either reading")
        if not passes:
            failures.append({"claim_id": row.get("claim_id"), "url": row.get("url"),
                             "http_status": row.get("http_status"),
                             "title_match": row.get("title_match")})
        elif not is_strong:
            weak.append({"claim_id": row.get("claim_id"),
                         "title_match": row.get("title_match")})

    if body.get("n_failed") != len(failures):
        raise Refusal(f"the artifact's n_failed is {body.get('n_failed')} and "
                      f"{len(failures)} row(s) fail on recomputation")

    return {
        "n": len(rows),
        "expected_rows": want,
        "observed_all_resolve_and_describe": not failures,
        "failures": failures,
        "rows_on_the_strong_branch": len(rows) - len(weak),
        "rows_passed_on_http_200_alone": weak,
        "unreachable": unreachable,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the oracle and what would be read; write nothing")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(f"{CASE} dry run — no HTTP request, no write, $0\n")
        print(f"oracle ({O.BINDINGS[CASE].kind}): {O.oracle_text(CASE)}\n")
        print(f"pre-registered n: {O.planned_n(CASE) or 'none'}   "
              f"mandatory mutation arm: {O.mutation_is_mandatory(CASE)}")
        print(f"\nreads (analysis only):")
        print(f"  {ARTIFACT.relative_to(ROOT)}  "
              f"{'present' if ARTIFACT.is_file() else 'MISSING'}")
        print(f"  {TRIAGE.relative_to(ROOT)}  (denominator, derived)")
        print(f"\ntitle_match classification — {len(TITLE_MATCH)} token(s):")
        for tok, (ok, strong, _why) in sorted(TITLE_MATCH.items()):
            print(f"  {'pass' if ok else 'FAIL':<5} "
                  f"{'strong' if strong else 'http-200-only':<14} {tok}")
        print(f"\nwould write results/phase1/{CASE}.json")
        return 0

    try:
        b = build()
    except Refusal as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    o = P.obs_existence(
        CASE, b["observed_all_resolve_and_describe"], n=b["n"],
        observed_on=OBSERVED_ON,
        single_observation=("link liveness can change, so this is a verdict about "
                            f"{OBSERVED_ON}. A re-check belongs in a second dated file: "
                            "overwriting the artifact would destroy the only observation of "
                            "that date, which the document's '24/24' is pinned against"),
        failures=b["failures"],
        n_basis=(f"{b['n']} §10 reference rows, matching the {b['expected_rows']} derived "
                 f"from claims/triage.csv rather than a count read out of the artifact"),
        rows_on_the_strong_branch=b["rows_on_the_strong_branch"],
        rows_passed_on_http_200_alone=b["rows_passed_on_http_200_alone"],
        pass_recomputed=("every row's pass/fail was re-derived from its recorded "
                         "http_status and title_match and compared to the stored boolean; "
                         "a disagreement is a refusal, not a verdict"),
        unreachable_policy=("an unreachable URL is a refusal rather than a FALSE, because "
                            "in the producer it scores as a row failure and our network is "
                            "not the document's defect"),
        artifact="results/FINDING-F0-1-references.json")
    rec = O.evaluate(o)

    payload = {"billable_calls": 0, "mutations": 0, "aws_calls": 0, "http_requests": 0,
               "analysis_only": True,
               "reads": [str(ARTIFACT.relative_to(ROOT)), str(TRIAGE.relative_to(ROOT))],
               "observed_on": OBSERVED_ON,
               "title_match_classification": {
                   k: {"counts_as_pass": v[0], "is_strong": v[1], "why": v[2]}
                   for k, v in sorted(TITLE_MATCH.items())},
               "rows_on_the_strong_branch": b["rows_on_the_strong_branch"],
               "rows_passed_on_http_200_alone": b["rows_passed_on_http_200_alone"],
               "failures": b["failures"]}

    print(f"  {b['n']} rows, {b['rows_on_the_strong_branch']} on the strong branch, "
          f"{len(b['failures'])} failure(s), {b['unreachable']} unreachable")
    P.emit(CASE, rec, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
