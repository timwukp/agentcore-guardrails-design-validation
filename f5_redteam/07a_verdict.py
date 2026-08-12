#!/usr/bin/env python3
"""F5-7a: turn the archived PrivateLink observations into the SEALED oracle's verdict.

Analysis only, **$0, offline**. This script makes no AWS call and no HTTP request. It reads
the `analysis.json` that `07a_privatelink_enum.py` archived under two run ids and emits
`results/phase1/F5-7a.json` through `lib/phase1.emit`, so the case's verdict lands in the
same shape and in the same index as every other Phase 1 case.

Why this is a separate script, and why the case needed one at all
----------------------------------------------------------------
F5-7a was fully measured on 2026-08-09, replicated on 2026-08-10 (75 fields compared, 0
disagreements) and written up in `results/FINDING-F5-7A.md`. What it never had was a
verdict in the **sealed oracle's** vocabulary. `07a_privatelink_enum.py` classifies each
document claim in a vocabulary of its own — `CONFIRMED`, `DOC_IMPRECISE`,
`AWS_BEHAVIOR_CHANGED`, `DOC_REFUTED_CHANGE_DATE_UNDETERMINED` — which is the right
vocabulary for a finding and is not a vocabulary `lib/oracle.evaluate` knows. So the case
was measured, replicated, published as a finding, and **absent from
`results/phase1/`** — which is the index `census.py` counts and the analysis phase reads.
It counted as outstanding while being complete.

The sealed oracle is one sentence:

    TRUE if describe-vpc-endpoint-services matches the document's coverage matrix
    including the claimed Optimization gap; FALSE on any mismatch

so the whole job of this file is the map from eleven per-claim tokens to one boolean, and
that map is the part worth being careful about. It is written as data (`CLASSIFICATION`),
every entry carries the reason it reads the way it does, and an **unrecognised token is
fatal** rather than defaulted — a new outcome added to the producer must be classified
deliberately, not silently absorbed as agreement.

The reading that would have been vacuous, and why both readings are computed
---------------------------------------------------------------------------
The oracle names `describe-vpc-endpoint-services` — instrument A. Read as "instrument A
alone", every A-borne claim is CONFIRMED and the verdict would be TRUE.

That reading is vacuous, and the case's own control arm is what proves it: all three
endpoint services exist in all three regions the document lists as **not** supporting
guardrails-in-policy, so endpoint-service existence carries **no information** about
feature availability (finding 6). An instrument that cannot see the property the matrix
asserts cannot confirm the matrix. Instrument B — AWS's own documentation page, live and
at dated Internet Archive snapshots — exists for exactly that reason, and it is what
refutes the Optimization row the oracle names by name.

So the primary reading admits both instruments, and the strict reading (which additionally
counts the document's imprecision as a mismatch) is computed and recorded beside it. Both
give FALSE here, and the record says so: a verdict that survives both readings does not
depend on which one a reader prefers, and stating that is cheaper than arguing for one.

What FALSE does and does not mean here
--------------------------------------
FALSE is the oracle's answer to "does the matrix match", and it must not be read as "the
document was careless". Finding 4 is the opposite: AWS's page said "Not yet supported" on
five dated snapshots spanning 2026-04-12 to 2026-07-14, so §4.5.3 agreed with AWS's public
documentation for at least three months and the claim **expired**. A binary oracle cannot
carry that distinction, which is precisely why `results/FINDING-F5-7A.md` is the
deliverable and this record points at it.

Usage
-----
    python3 f5_redteam/07a_verdict.py --dry-run
    python3 f5_redteam/07a_verdict.py
    python3 f5_redteam/07a_verdict.py --runs r20260809T094500Z r20260810T002001Z
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import oracle as O                                                   # noqa: E402
import phase1 as P                                                   # noqa: E402

CASE = "F5-7a"
FAMILY = "f5"

# The two archived runs the finding declares, in order. Day 2 is the canonical one — see
# FINDING-F5-7A.md §7 "Two day-2 runs, and which one is canonical".
DEFAULT_RUNS = ("r20260809T094500Z", "r20260810T002001Z")

# Files inside an evidence directory that are not per-call records. Kept as a set rather
# than a prefix test because `n` below is a COUNT of records: including the three
# bookkeeping files would inflate the denominator of every run by exactly three, which is
# the kind of error that looks like data.
NOT_A_RECORD = {"environment.json", "analysis.json", "summary.json"}

# Every verdict token `07a_privatelink_enum.classify` can produce, and what each one means
# for the sealed oracle. Three buckets:
#
#   MATCH            the document's claim held, on the instrument that can settle it
#   MISMATCH         the document's claim did not hold — the oracle's "any mismatch"
#   NOT_A_DOC_CLAIM  the row says something about our INSTRUMENT or our PROSE, not about
#                    whether the coverage matrix is factually right
#
# `tests/test_07a_verdict.py` derives the token set from the producer's source and fails if
# this table is missing one, so the table cannot drift behind the script that feeds it
# (feedback_derive_from_every_producer). Six of the eleven never appear in the two archived
# runs; they are the branches that would fire if the world were different, and leaving them
# out would make this a transcript of one result rather than a decision rule.
CLASSIFICATION: dict[str, tuple[str, str]] = {
    "CONFIRMED": (
        "MATCH",
        "the claim held on the instrument named for it"),
    "NOT_CONFIRMED": (
        "MISMATCH",
        "an existence claim the enumeration was able to settle, and did not find — "
        "unobserved in both archived runs, and the branch caveat (b) would take if the "
        "third gateway endpoint were absent in any region"),
    "REFUTED": (
        "MISMATCH",
        "a keyword hit for `evaluat` or `agentcore-optimi` among the unfiltered service "
        "list would mean a dedicated endpoint service does exist — unobserved"),
    "DOC_IMPRECISE": (
        "NOT_A_DOC_CLAIM",
        "finding 3 is about the matrix's COLUMN HEADER, not its facts: the rows name "
        "primitives while PrivateLink attaches to prefixes, so a reader cannot check the "
        "matrix the way BP#6 invites. That makes the table unusable, not false — the "
        "document's own words are DC-1's shape, right and unusable. Counted as a mismatch "
        "under the strict reading, which is reported beside the primary one"),
    "AWS_BEHAVIOR_CHANGED": (
        "MISMATCH",
        "the matrix does not match reality TODAY, which is what the oracle asks. That the "
        "row was accurate when written — five dated snapshots agreeing with it — is a "
        "fact about blame, not about the match, and it lives in the finding"),
    "DOC_REFUTED_CHANGE_DATE_UNDETERMINED": (
        "MISMATCH",
        "the live page contradicts the row and the archive is SILENT rather than "
        "contradictory, so the date it became false cannot be established. The mismatch "
        "is nonetheless established: AWS's page and our matrix disagree now"),
    "DOC_CONTRADICTED_BY_AWS_DOCS": (
        "MISMATCH",
        "the live page contradicts the row with no dated history in either direction — "
        "unobserved in both runs"),
    "DOC_CONFIRMED": (
        "MATCH",
        "the live page still says what the matrix says — unobserved in both runs, and the "
        "branch findings 4 and 5 would have taken had AWS not shipped"),
    "CONFIRMED_AS_LIMITATION": (
        "NOT_A_DOC_CLAIM",
        "finding 6 is a statement about OUR instrument: the three endpoint services exist "
        "in all three control regions the document lists as unsupported, so existence "
        "carries no information about availability. It bounds what instrument A can "
        "conclude and asserts nothing about the matrix"),
    "INCONCLUSIVE": (
        "NOT_A_DOC_CLAIM",
        "the control arm did not settle its own premise; it still asserts nothing about "
        "the matrix — unobserved in both runs"),
    "NOT_TESTED_BY_THIS_INSTRUMENT": (
        "NOT_A_DOC_CLAIM",
        "a first-class outcome in the producer, used where the instrument is silent. "
        "Silence is not agreement, so it may not be counted as a match"),
}

MATCH, MISMATCH, NOT_A_CLAIM = "MATCH", "MISMATCH", "NOT_A_DOC_CLAIM"


class Refusal(RuntimeError):
    """A precondition that makes the verdict unsafe to compute. Never a verdict."""


def analysis_path(run_id: str, root: Path = ROOT) -> Path:
    return root / "evidence" / run_id / FAMILY / CASE / "analysis.json"


def load_findings(run_id: str, root: Path = ROOT) -> dict[str, dict]:
    """The per-claim table one archived run recorded, or a refusal naming what is missing."""
    p = analysis_path(run_id, root)
    if not p.is_file():
        raise Refusal(
            f"{p} does not exist. This script analyses ARCHIVED observations and collects "
            f"none of its own; run `python3 f5_redteam/07a_privatelink_enum.py "
            f"--run-id {run_id}` first ($0, read-only)")
    body = json.loads(p.read_text(encoding="utf-8"))
    findings = ((body.get("analysis") or {}).get("findings") or {})
    if not findings:
        raise Refusal(f"{p} records no `analysis.findings`; it was written by an older "
                      f"producer than this reader expects")
    return findings


def count_records(run_id: str, root: Path = ROOT) -> int:
    """How many per-call evidence records this run archived.

    Derived by counting files rather than read out of the analysis body, because the point
    of `n` is to say how much observation the verdict rests on and a self-reported count
    would be the analysis vouching for itself.
    """
    d = analysis_path(run_id, root).parent
    return sum(1 for f in d.glob("*.json") if f.name not in NOT_A_RECORD)


def classify_tokens(findings: dict[str, dict]) -> dict[str, dict[str, str]]:
    """Map each claim's recorded token into the sealed oracle's three buckets.

    An unrecognised token raises. The alternative — treating it as `NOT_A_DOC_CLAIM` — is
    what makes a guard vacuous: a producer that grew a new refutation branch would publish
    TRUE because its new token was not in this table, and the record would look complete.
    """
    out: dict[str, dict[str, str]] = {}
    for claim, row in sorted(findings.items()):
        tok = str(row.get("verdict", ""))
        if tok not in CLASSIFICATION:
            raise Refusal(
                f"claim {claim!r} carries verdict {tok!r}, which "
                f"{Path(__file__).name}'s CLASSIFICATION table does not classify. A token "
                f"this file has never seen may not be folded into 'no mismatch' by "
                f"default: classify it deliberately, with the reason, and add an arm to "
                f"tests/test_07a_verdict.py. Known tokens: {sorted(CLASSIFICATION)}")
        bucket, why = CLASSIFICATION[tok]
        out[claim] = {"token": tok, "bucket": bucket, "why": why,
                      "instrument": str(row.get("instrument", "") or "unrecorded")}
    return out


def require_agreement(per_run: dict[str, dict[str, dict[str, str]]]) -> None:
    """Both days must agree on the tokens the verdict is computed from.

    `07a_compare_runs.py` already compares 75 fields, and this is deliberately narrower
    and not a substitute: it checks the exact quantity THIS record rests on. A comparator
    can be green while the specific field a later reader turned into a verdict differs,
    and the reverse — a request id differing — is not a reason to refuse.
    """
    runs = sorted(per_run)
    if len(runs) < 2:
        raise Refusal(
            f"only {len(runs)} run supplied; the finding rests on two calendar days and a "
            f"record derived from one of them would assert a replication that was not "
            f"checked here")
    base = runs[0]
    for other in runs[1:]:
        a = {k: v["token"] for k, v in per_run[base].items()}
        b = {k: v["token"] for k, v in per_run[other].items()}
        if a != b:
            diff = sorted(set(a) | set(b))
            rows = [f"    {k:<52} {a.get(k, '(absent)')} vs {b.get(k, '(absent)')}"
                    for k in diff if a.get(k) != b.get(k)]
            raise Refusal(
                f"{base} and {other} disagree on the per-claim verdicts this record is "
                f"computed from, so there is no single result to publish. The "
                f"disagreement is itself the finding — do NOT amend:\n"
                + "\n".join(rows))


def decide(per_claim: dict[str, dict[str, str]]) -> dict[str, Any]:
    """The two readings, both computed, neither hidden."""
    mismatches = sorted(k for k, v in per_claim.items() if v["bucket"] == MISMATCH)
    matches = sorted(k for k, v in per_claim.items() if v["bucket"] == MATCH)
    imprecise = sorted(k for k, v in per_claim.items()
                       if v["token"] == "DOC_IMPRECISE")
    bearing = mismatches + matches
    if not bearing:
        raise Refusal(
            f"none of the {len(per_claim)} recorded claims bears on the sealed oracle — "
            f"every one classified as {NOT_A_CLAIM}. A boolean derived from an empty "
            f"conjunction would be TRUE by vacuity")
    return {
        "matched_claims": matches,
        "mismatched_claims": mismatches,
        "claims_bearing_on_the_oracle": len(bearing),
        "claims_about_our_instrument_or_prose": sorted(
            k for k, v in per_claim.items() if v["bucket"] == NOT_A_CLAIM),
        "observed_matrix_matches": not mismatches,
        "observed_matrix_matches_strict": not (mismatches or imprecise),
        "strict_reading_adds": imprecise,
        "readings_agree": (not mismatches) == (not (mismatches or imprecise)),
    }


def build(runs: tuple[str, ...] | list[str], root: Path = ROOT) -> dict[str, Any]:
    """Everything except the writing, so a test can assert on it without touching results/."""
    per_run = {r: classify_tokens(load_findings(r, root)) for r in runs}
    require_agreement(per_run)
    canonical = list(runs)[-1]
    per_claim = per_run[canonical]
    d = decide(per_claim)
    records = {r: count_records(r, root) for r in runs}
    n = sum(records.values())
    if n <= 0:
        raise Refusal(
            f"the archived runs {list(runs)} hold zero per-call evidence records between "
            f"them, so nothing was observed. A verdict here would rest on an analysis file "
            f"with no calls behind it")
    return {"per_run": per_run, "canonical_run": canonical, "decision": d,
            "records_per_run": records, "n": n}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the oracle, the runs and the classification table; write "
                         "nothing")
    ap.add_argument("--runs", nargs="+", default=list(DEFAULT_RUNS),
                    metavar="RUN_ID",
                    help="archived run ids, oldest first; the last is canonical")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(f"{CASE} dry run — no AWS call, no HTTP request, no write, $0\n")
        print(f"oracle ({O.BINDINGS[CASE].kind}): {O.oracle_text(CASE)}\n")
        print(f"pre-registered n: {O.planned_n(CASE) or 'none'}   "
              f"mandatory mutation arm: {O.mutation_is_mandatory(CASE)}")
        print(f"\nreads (analysis only):")
        for r in args.runs:
            p = analysis_path(r)
            print(f"  {r}  {'present' if p.is_file() else 'MISSING'}  "
                  f"{count_records(r)} record(s)")
        print(f"\nclassification table — {len(CLASSIFICATION)} token(s):")
        for tok, (bucket, _why) in sorted(CLASSIFICATION.items()):
            print(f"  {bucket:<16} {tok}")
        print("\nwould write results/phase1/F5-7a.json")
        return 0

    try:
        b = build(tuple(args.runs))
    except Refusal as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    d = b["decision"]
    o = P.obs_existence(
        CASE, d["observed_matrix_matches"], n=b["n"],
        reading=("both instruments, because the case's own control arm (finding 6) shows "
                 "instrument A cannot see feature availability and so cannot confirm the "
                 "matrix on its own"),
        strict_reading_also_counts_doc_imprecision_as_a_mismatch=(
            d["observed_matrix_matches_strict"]),
        readings_agree=d["readings_agree"],
        matched_claims=d["matched_claims"],
        mismatched_claims=d["mismatched_claims"],
        claims_about_our_instrument_or_prose=d["claims_about_our_instrument_or_prose"],
        per_claim=b["per_run"][b["canonical_run"]],
        n_basis=(f"{b['n']} per-call evidence records across "
                 f"{len(b['records_per_run'])} archived run(s) "
                 f"{b['records_per_run']}, counted on disk rather than read out of the "
                 f"analysis body"),
        canonical_run=b["canonical_run"],
        replication=("the runs agree on every per-claim verdict this record is computed "
                     "from; the 75-field comparison is results/f5_7a_replication.json"),
        finding="results/FINDING-F5-7A.md",
        what_false_does_not_mean=(
            "not 'the document was careless'. Finding 4 is the opposite: AWS's own page "
            "said 'Not yet supported' on five dated snapshots spanning 2026-04-12 to "
            "2026-07-14, so §4.5.3 agreed with AWS for at least three months and the claim "
            "EXPIRED. The oracle is binary and cannot carry that; the finding can"))
    rec = O.evaluate(o)

    payload = {"billable_calls": 0, "mutations": 0, "aws_calls": 0,
               "analysis_only": True,
               "reads": [str(analysis_path(r).relative_to(ROOT)) for r in args.runs],
               "records_per_run": b["records_per_run"],
               "classification_table": {k: {"bucket": v[0], "why": v[1]}
                                        for k, v in sorted(CLASSIFICATION.items())},
               "per_run_tokens": {r: {k: v["token"] for k, v in rows.items()}
                                  for r, rows in b["per_run"].items()}}

    for claim, row in sorted(b["per_run"][b["canonical_run"]].items()):
        print(f"  {row['bucket']:<16} {row['token']:<38} {claim}")
    P.emit(CASE, rec, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
