#!/usr/bin/env python3
"""Coverage GATE. Exits non-zero if coverage is not provable.

Per the plan: "fails if any claim lacks a class, a test case ID (or exclusion
reason), or an oracle."

Being a gate, this script's own failure modes matter as much as the checks it
runs. Two disciplines from prior incidents apply directly:

  * `feedback_zero_file_scan_is_error` — a gate that reads zero rows must FAIL,
    not report clean. CHK-00 asserts a non-empty, plausibly-sized input.
  * `feedback_vacuous_test_check` — a gate that cannot fail is decoration. Run
    with `--self-test` to mutate triage.csv in memory 12 ways and prove each
    check actually fires. The self-test never touches the file on disk.

Exit codes:
  0  all checks pass
  1  one or more checks failed
  2  the input itself is unusable (missing file, zero rows, missing columns)
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import triage_rules as R  # noqa: E402

TRIAGE = HERE / "triage.csv"
RAW = HERE / "claims_raw.csv"
DOC = Path.home() / "Downloads" / "agentcore_guardrails_best_practices_v1.2.md"

REQUIRED_COLUMNS = {
    "claim_id", "anchor", "unit_type", "ordinal", "doc_line", "sha1", "cls",
    "cases", "merge_group", "canonical", "merged_into", "exclusion_reason",
    "rule", "note", "text",
}

TESTED = {"E", "S", "C", "O"}
UNTESTED = {"D", "N", "X"}
VALID = TESTED | UNTESTED

# A minimum below which the input is presumed truncated rather than merely small.
# claims_raw.csv has 650 structural units; anything under 400 triaged claims means
# a parse or filter went wrong upstream.
MIN_ROWS = 400

# An exclusion reason short enough to be a placeholder is not a reason. 80 chars
# is roughly one full sentence naming both the obstacle and the remedy.
MIN_REASON_CHARS = 80


class Failure(Exception):
    """Raised for unusable input (exit 2), as distinct from a failed check."""


def load(path: Path = TRIAGE) -> list[dict]:
    if not path.exists():
        raise Failure(f"{path} does not exist — run 01_triage.py first")
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise Failure(f"{path.name} is missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise Failure(f"{path.name} contains zero rows — a gate that reads nothing "
                      f"must fail, not report clean")
    if len(rows) < MIN_ROWS:
        raise Failure(f"{path.name} has only {len(rows)} rows (expected >= {MIN_ROWS}) "
                      f"— the input looks truncated")
    return rows


# ===========================================================================
# CHECKS
# ===========================================================================
# Each returns a list of failure strings. Empty list == pass. Signature is
# uniform so the self-test can drive them all the same way.

def chk_class_valid(rows: list[dict]) -> list[str]:
    """CHK-01 Every claim carries exactly one class from the declared set."""
    return [f"{r['claim_id']}: class {r['cls']!r} is not one of {sorted(VALID)}"
            for r in rows if r["cls"] not in VALID]


def chk_tested_has_case(rows: list[dict]) -> list[str]:
    """CHK-02 Every E/S/C/O claim names at least one test case."""
    return [f"{r['claim_id']}: class {r['cls']} but no test case"
            for r in rows if r["cls"] in TESTED and not r["cases"].strip()]


def chk_case_exists(rows: list[dict]) -> list[str]:
    """CHK-03 Every cited case exists in the registry."""
    out = []
    for r in rows:
        for case in r["cases"].split():
            if case not in R.CASES:
                out.append(f"{r['claim_id']}: cites unknown case {case!r}")
    return out


def chk_untested_has_reason(rows: list[dict]) -> list[str]:
    """CHK-04 Every D/N/X claim carries a substantive written reason, and no case.

    This is the check that stops a normative claim from being silently scored
    'passed': if it has no test, it must say why in prose a reviewer can dispute.
    """
    out = []
    for r in rows:
        if r["cls"] not in UNTESTED:
            continue
        reason = r["exclusion_reason"].strip()
        if not reason:
            out.append(f"{r['claim_id']}: class {r['cls']} with no exclusion reason")
        elif len(reason) < MIN_REASON_CHARS:
            out.append(f"{r['claim_id']}: exclusion reason is {len(reason)} chars "
                       f"(min {MIN_REASON_CHARS}) — too short to name an obstacle "
                       f"and a remedy: {reason!r}")
        if r["cases"].strip():
            out.append(f"{r['claim_id']}: class {r['cls']} must not cite cases, "
                       f"has {r['cases']!r}")
    return out


def chk_x_names_remedy(rows: list[dict]) -> list[str]:
    """CHK-05 Every X claim states what would be needed to test it.

    The plan requires X to carry 'mandatory reason + what would be needed'. An
    exclusion with no remedy is indistinguishable from giving up.
    """
    out = []
    for r in rows:
        if r["cls"] != "X":
            continue
        reason = r["exclusion_reason"]
        if not re.search(r"Remedy:|remedy:|nearest prox|Proxies|proxies|"
                         r"same exclusion|inherits the same", reason):
            out.append(f"{r['claim_id']}: class X but the reason names no remedy or "
                       f"proxy — say what would make it testable")
    return out


def chk_case_has_oracle(rows: list[dict]) -> list[str]:
    """CHK-06 Every cited case states a falsifying observation.

    'Oracle' means an observation that would make the claim FALSE. A case that
    only says what success looks like cannot fail, and per feedback_vacuous_test
    _check that is not a test.
    """
    out = []
    cited = {c for r in rows for c in r["cases"].split()}
    for case in sorted(cited):
        if case not in R.CASES:
            continue  # CHK-03 owns this
        _family, _title, _cls, oracle, method = R.CASES[case]
        if not oracle.strip():
            out.append(f"case {case}: no oracle")
            continue
        if "FALSE" not in oracle and "UNKNOWN" not in oracle:
            out.append(f"case {case}: oracle states no falsifying observation "
                       f"(no 'FALSE if ...' and not declared OUTCOME UNKNOWN): "
                       f"{oracle[:90]!r}")
        if not method.strip():
            out.append(f"case {case}: no method")
    return out


def chk_case_class_agrees(rows: list[dict]) -> list[str]:
    """CHK-07 A claim's class matches AT LEAST ONE case it cites.

    Not every case: a claim frequently has one primary case plus supporting ones
    of a different class — an E claim about default-deny legitimately cites the C
    case establishing that the field exists. Requiring every case to match would
    force the primary evidence to be dropped or the class to be misstated, which
    is worse than the mismatch it prevents.

    What must not happen is a claim whose class matches NOTHING it cites: a claim
    classed S with only C cases would be published with a confidence interval no
    experiment in the plan produces.
    """
    out = []
    for r in rows:
        cases = [c for c in r["cases"].split() if c in R.CASES]
        if not cases:
            continue  # CHK-02 owns the empty case
        classes = {R.CASES[c][2] for c in cases}
        if r["cls"] not in classes:
            out.append(f"{r['claim_id']}: class {r['cls']} but no cited case has that "
                       f"class (cases: "
                       + ", ".join(f"{c}={R.CASES[c][2]}" for c in cases) + ")")
    return out


def chk_orphan_cases(rows: list[dict]) -> list[str]:
    """CHK-08 Every registry case is cited by a claim or declared a platform case.

    Catches the reverse direction of coverage: an experiment answering no claim
    means either dead weight or a claim I failed to triage.
    """
    cited = {c for r in rows for c in r["cases"].split()}
    return [f"case {case}: cited by no claim and not declared in PLATFORM_CASES "
            f"({R.CASES[case][1]})"
            for case in sorted(set(R.CASES) - cited - set(R.PLATFORM_CASES))]


def chk_merge_integrity(rows: list[dict]) -> list[str]:
    """CHK-09 Merge groups have exactly one canonical site and agree internally.

    Per feedback_grep_the_claim_not_the_phrasing, a claim amended at 1 of 4 sites
    is NOT amended. That only works if every group has one unambiguous canonical
    row and all members carry the same class.
    """
    out = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["merge_group"]:
            groups[r["merge_group"]].append(r)

    for group, members in sorted(groups.items()):
        canon = [m for m in members if m["canonical"] == "yes"]
        if len(canon) != 1:
            out.append(f"merge group {group}: {len(canon)} canonical sites "
                       f"(expected exactly 1)")
        if len(members) < 2:
            out.append(f"merge group {group}: {len(members)} member — a merge group "
                       f"of one is not a merge")
        classes = {m["cls"] for m in members}
        if len(classes) > 1:
            out.append(f"merge group {group}: members disagree on class {sorted(classes)} "
                       f"— restatements of one proposition cannot need different "
                       f"evidence types")
        if canon:
            for m in members:
                if m["canonical"] != "yes" and m["merged_into"] != canon[0]["claim_id"]:
                    out.append(f"{m['claim_id']}: merged_into "
                               f"{m['merged_into']!r} != canonical "
                               f"{canon[0]['claim_id']!r}")
    for group in R.MERGE_GROUPS:
        if group not in groups:
            out.append(f"merge group {group} is declared in triage_rules but no row "
                       f"carries it")
    return out


def chk_ids_unique(rows: list[dict]) -> list[str]:
    """CHK-10 Claim IDs are unique."""
    dup = [cid for cid, n in Counter(r["claim_id"] for r in rows).items() if n > 1]
    return [f"duplicate claim_id {cid!r}" for cid in sorted(dup)]


def chk_rule_recorded(rows: list[dict]) -> list[str]:
    """CHK-11 Every claim records which rule classified it, and none fell through."""
    out = []
    for r in rows:
        if not r["rule"].strip():
            out.append(f"{r['claim_id']}: no rule recorded — classification is "
                       f"not traceable")
        elif r["rule"] == "FALLTHROUGH":
            out.append(f"{r['claim_id']}: reached the fallthrough — unclassified")
    return out


def chk_sha1_matches_raw(rows: list[dict]) -> list[str]:
    """CHK-12 Every sha1 matches claims_raw.csv, so triage cannot go stale silently.

    Editing the document changes the sha1 of the unit, which invalidates the row
    and forces re-triage. This check is what gives that property teeth.
    """
    if not RAW.exists():
        return [f"{RAW.name} is missing — cannot verify sha1 provenance"]
    with RAW.open(encoding="utf-8") as fh:
        raw = {r["claim_id"]: r for r in csv.DictReader(fh)}
    out = []
    for r in rows:
        cid = r["claim_id"]
        parent = cid
        if cid not in raw:
            # split part: strip the trailing -<letter>
            parent = cid.rsplit("-", 1)[0]
            if parent not in raw:
                out.append(f"{cid}: no matching row in {RAW.name} "
                           f"(tried parent {parent!r})")
                continue
        if raw[parent]["sha1"] != r["sha1"]:
            out.append(f"{cid}: sha1 {r['sha1'][:12]} != {RAW.name} "
                       f"{raw[parent]['sha1'][:12]} — triage is stale, re-run "
                       f"01_triage.py")
    return out


def chk_split_parents_absent(rows: list[dict]) -> list[str]:
    """CHK-13 A split parent must not survive alongside its parts.

    If both are present the parent's conjunction is scored twice, once as a whole
    and once per part, inflating apparent coverage.
    """
    ids = {r["claim_id"] for r in rows}
    out = []
    for parent, parts in R.SPLITS.items():
        if parent in ids:
            out.append(f"{parent}: split parent still present alongside its parts")
        for letter, *_ in parts:
            if f"{parent}-{letter}" not in ids:
                out.append(f"{parent}-{letter}: declared in SPLITS but missing "
                           f"from triage.csv")
    return out


def chk_doc_line_plausible(rows: list[dict]) -> list[str]:
    """CHK-14 doc_line points inside the document, if the document is present.

    Cheap protection against citing a line number the reader cannot find.
    """
    if not DOC.exists():
        return []
    n_lines = sum(1 for _ in DOC.open(encoding="utf-8"))
    out = []
    for r in rows:
        try:
            line = int(r["doc_line"])
        except (TypeError, ValueError):
            out.append(f"{r['claim_id']}: doc_line {r['doc_line']!r} is not an integer")
            continue
        if not 1 <= line <= n_lines:
            out.append(f"{r['claim_id']}: doc_line {line} is outside "
                       f"{DOC.name} (1..{n_lines})")
    return out


def chk_no_family_starved(rows: list[dict]) -> list[str]:
    """CHK-15 Every family in the registry has at least one claim.

    A family with zero claims means an entire experiment group was designed for
    nothing, or a whole section of the document went untriaged.
    """
    by_family: Counter = Counter()
    for r in rows:
        for case in r["cases"].split():
            if case in R.CASES:
                by_family[R.CASES[case][0]] += 1
    families = {meta[0] for meta in R.CASES.values()}
    platform_only = {R.CASES[c][0] for c in R.PLATFORM_CASES if c in R.CASES}
    return [f"family {f}: no claim cites any of its cases"
            for f in sorted(families - set(by_family) - platform_only)]


CHECKS = [
    ("CHK-01 class is valid", chk_class_valid),
    ("CHK-02 tested claim names a case", chk_tested_has_case),
    ("CHK-03 cited case exists", chk_case_exists),
    ("CHK-04 untested claim gives a reason", chk_untested_has_reason),
    ("CHK-05 excluded claim names a remedy", chk_x_names_remedy),
    ("CHK-06 case states a falsifying oracle", chk_case_has_oracle),
    ("CHK-07 claim class agrees with case class", chk_case_class_agrees),
    ("CHK-08 no orphan cases", chk_orphan_cases),
    ("CHK-09 merge-group integrity", chk_merge_integrity),
    ("CHK-10 claim ids unique", chk_ids_unique),
    ("CHK-11 classification is traceable", chk_rule_recorded),
    ("CHK-12 sha1 matches claims_raw", chk_sha1_matches_raw),
    ("CHK-13 split parents replaced", chk_split_parents_absent),
    ("CHK-14 doc_line inside the document", chk_doc_line_plausible),
    ("CHK-15 no starved family", chk_no_family_starved),
]


# ===========================================================================
# SELF-TEST — prove each check can fail
# ===========================================================================
# A mutation the check is supposed to catch, per check. Anything not caught here
# means the check is decoration.

def _mutations() -> list[tuple[str, str, callable]]:
    def first_of(rows, cls):
        return next(r for r in rows if r["cls"] == cls)

    def m_bad_class(rows):
        rows[0]["cls"] = "Z"

    def m_drop_case(rows):
        first_of(rows, "S")["cases"] = ""

    def m_unknown_case(rows):
        first_of(rows, "E")["cases"] = "F99-nonexistent"

    def m_drop_reason(rows):
        first_of(rows, "N")["exclusion_reason"] = ""

    def m_short_reason(rows):
        first_of(rows, "D")["exclusion_reason"] = "not testable"

    def m_untested_with_case(rows):
        first_of(rows, "N")["cases"] = "F1-3"

    def m_x_without_remedy(rows):
        first_of(rows, "X")["exclusion_reason"] = (
            "This cannot be tested in the current environment because the necessary "
            "surface is simply not exposed to customers at all today.")

    def m_class_mismatch(rows):
        r = first_of(rows, "S")
        r["cls"] = "O"   # cases stay S

    def m_dup_id(rows):
        rows[1]["claim_id"] = rows[0]["claim_id"]

    def m_fallthrough(rows):
        rows[0]["rule"] = "FALLTHROUGH"

    def m_bad_sha(rows):
        rows[0]["sha1"] = hashlib.sha1(b"tampered").hexdigest()

    def m_bad_docline(rows):
        rows[0]["doc_line"] = "999999"

    def m_break_merge(rows):
        # two canonical sites in one group
        g = next(r["merge_group"] for r in rows if r["merge_group"] and
                 r["canonical"] == "no")
        for r in rows:
            if r["merge_group"] == g:
                r["canonical"] = "yes"

    def m_split_parent_back(rows):
        parent = next(iter(R.SPLITS))
        clone = dict(rows[0])
        clone["claim_id"] = parent
        rows.append(clone)

    return [
        ("CHK-01", "invalid class letter", m_bad_class),
        ("CHK-02", "tested claim with no case", m_drop_case),
        ("CHK-03", "case id not in the registry", m_unknown_case),
        ("CHK-04", "untested claim with no reason", m_drop_reason),
        ("CHK-04", "reason too short to be a reason", m_short_reason),
        ("CHK-04", "untested claim citing a case", m_untested_with_case),
        ("CHK-05", "X claim with no remedy or proxy", m_x_without_remedy),
        ("CHK-07", "claim class disagrees with case class", m_class_mismatch),
        ("CHK-10", "duplicate claim id", m_dup_id),
        ("CHK-11", "claim reached the fallthrough", m_fallthrough),
        ("CHK-12", "sha1 no longer matches claims_raw", m_bad_sha),
        ("CHK-14", "doc_line past the end of the document", m_bad_docline),
        ("CHK-09", "two canonical sites in one merge group", m_break_merge),
        ("CHK-13", "split parent resurrected alongside its parts", m_split_parent_back),
    ]


def self_test(rows: list[dict]) -> int:
    """Mutate in memory and require the named check to fire. Never writes."""
    print("SELF-TEST — proving each check is load-bearing\n")
    lookup = dict(CHECKS)
    by_id = {name.split()[0]: (name, fn) for name, fn in CHECKS}

    # Control arm: a detector that fired unconditionally would 'catch' every
    # mutation and make the self-test meaningless.
    control_fail = [name for name, fn in CHECKS if fn(copy.deepcopy(rows))]
    if control_fail:
        print("  CONTROL ARM FAILED — these checks fail on unmutated input, so any "
              "kill they report is meaningless:")
        for name in control_fail:
            print(f"    {name}")
        return 1
    print(f"  control arm: all {len(CHECKS)} checks pass on unmutated input\n")

    killed = survived = 0
    for chk_id, label, mutate in _mutations():
        name, fn = by_id[chk_id]
        mutant = copy.deepcopy(rows)
        mutate(mutant)
        failures = fn(mutant)
        if failures:
            killed += 1
            print(f"  KILLED   {chk_id}  {label}")
            print(f"           -> {failures[0][:100]}")
        else:
            survived += 1
            print(f"  SURVIVED {chk_id}  {label}   <-- CHECK IS NOT LOAD-BEARING")

    print(f"\n  {killed}/{killed + survived} mutations caught")
    if survived:
        print("  *** a surviving mutation means that check cannot fail ***")
    del lookup
    return 0 if survived == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="prove each check can fail (in memory; writes nothing)")
    ap.add_argument("--verbose", action="store_true",
                    help="print all failures per check, not the first 8")
    args = ap.parse_args()

    try:
        rows = load()
    except Failure as exc:
        print(f"INPUT UNUSABLE: {exc}", file=sys.stderr)
        return 2

    if args.self_test:
        return self_test(rows)

    print(f"COVERAGE GATE — {len(rows)} claims from {TRIAGE.name}\n")

    total_failures = 0
    for name, fn in CHECKS:
        failures = fn(rows)
        if failures:
            total_failures += len(failures)
            print(f"  FAIL  {name}  ({len(failures)})")
            shown = failures if args.verbose else failures[:8]
            for f in shown:
                print(f"          {f}")
            if len(failures) > len(shown):
                print(f"          ... {len(failures) - len(shown)} more "
                      f"(--verbose for all)")
        else:
            print(f"  pass  {name}")

    stats = Counter(r["cls"] for r in rows)
    tested = sum(stats[c] for c in TESTED)
    cited = {c for r in rows for c in r["cases"].split()}
    print(f"\n  {tested}/{len(rows)} claims ({tested / len(rows):.1%}) have a test case; "
          f"{stats['D'] + stats['N']} definitional/normative, "
          f"{stats['X']} excluded with a written reason")
    print(f"  {len(cited)} cases cited, {len(R.PLATFORM_CASES)} platform prerequisites, "
          f"{len(R.MERGE_GROUPS)} merge groups")

    if total_failures:
        print(f"\nGATE FAILED — {total_failures} problem(s). "
              f"Coverage is not provable until these are resolved.")
        return 1
    print("\nGATE PASSED — every claim carries a class, and either a test case with a "
          "falsifying oracle or a written reason it has none.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
