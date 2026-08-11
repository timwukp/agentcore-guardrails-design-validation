#!/usr/bin/env python3
"""Apply triage_rules.py to claims_raw.csv -> triage.csv.

Every row records WHICH rule assigned it (`rule` column), so a reviewer can trace
any classification back to a stated reason instead of taking the class on trust.

The script is deliberately intolerant:

  * a rule or merge group naming a claim_id that does not exist is a FATAL error,
    not a warning. A dangling reference means the claim I thought I had classified
    is actually unclassified — silently, which is the exact failure mode the
    coverage gate exists to prevent.
  * any claim reaching the fallthrough is written with cls=UNCLASSIFIED, which
    check_coverage.py rejects. Unclassified rows are visible, never omitted.

Usage:  python3 01_triage.py [--check]
        --check re-derives triage.csv and diffs against the committed file.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import triage_rules as R  # noqa: E402

RAW = HERE / "claims_raw.csv"
OUT = HERE / "triage.csv"

# Units the extractor already marked as non-claims. Kept in claims_raw.csv so the
# extraction is auditable, dropped here with the extractor's own reason.
NON_CLAIM_NOTES = ("navigational", "runin-label", "leadin-stem", "fragment")

FIELDS = [
    "claim_id", "anchor", "unit_type", "ordinal", "doc_line", "sha1",
    "cls", "cases", "merge_group", "canonical", "merged_into",
    "exclusion_reason", "rule", "note", "text",
]


def load_raw() -> list[dict]:
    with RAW.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def resolve(row: dict) -> tuple[str, tuple[str, ...], str, str]:
    """Return (cls, cases, exclusion_reason, rule_name)."""
    cid, anchor, utype = row["claim_id"], row["anchor"], row["unit_type"]

    if cid in R.SPLIT_X_REASONS:
        return "X", (), R.SPLIT_X_REASONS[cid], f"SPLIT_X:{cid}"

    if cid in R.OVERRIDES:
        cls, cases, reason, _note = R.OVERRIDES[cid]
        # X_CLAIMS supplies the reason for override rows that declared none.
        if cls == "X" and not reason:
            reason = R.X_CLAIMS.get(cid, "")
        return cls, cases, reason, f"OVERRIDE:{cid}"

    if cid in R.X_CLAIMS:
        return "X", (), R.X_CLAIMS[cid], f"X_CLAIM:{cid}"

    for key in ((anchor, utype), ("*", utype)):
        if key in R.TYPE_RULES:
            cls, cases, reason, _note = R.TYPE_RULES[key]
            return cls, cases, reason, f"TYPE:{key[0]}/{key[1]}"

    if anchor in R.ANCHOR_RULES:
        cls, cases, reason, _note = R.ANCHOR_RULES[anchor]
        return cls, cases, reason, f"ANCHOR:{anchor}"

    return "UNCLASSIFIED", (), "", "FALLTHROUGH"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="re-derive and diff against the committed triage.csv")
    args = ap.parse_args()

    raw = load_raw()

    # ---- apply SPLITS before anything else --------------------------------
    # A split parent is replaced by its parts, in place, so ordering still
    # follows the document. Parts inherit doc_line and sha1: an edit to the
    # source line invalidates every part, forcing re-triage of all of them.
    split_errors: list[str] = []
    raw_ids = {r["claim_id"] for r in raw}
    for parent in R.SPLITS:
        if parent not in raw_ids:
            split_errors.append(f"SPLITS references nonexistent claim_id {parent!r}")

    expanded: list[dict] = []
    split_parts: dict[str, tuple[str, tuple[str, ...], str]] = {}
    for row in raw:
        cid = row["claim_id"]
        if cid not in R.SPLITS:
            expanded.append(row)
            continue
        for letter, conjunct, cls, cases, reason in R.SPLITS[cid]:
            part_id = f"{cid}-{letter}"
            part = dict(row)
            part["claim_id"] = part_id
            # Keep the parent's verbatim text alongside the conjunct so a reviewer
            # can check the split against the source without opening the .md.
            part["text"] = f"{conjunct}  [split of: {row['text']}]"
            part["note"] = (row["note"] + " " if row["note"] else "") + \
                           f"split-part {letter} of {cid}"
            expanded.append(part)
            split_parts[part_id] = (cls, cases, reason)
    raw = expanded
    by_id = {r["claim_id"]: r for r in raw}

    # Split parts are classified inline in SPLITS, so register them as overrides.
    for part_id, (cls, cases, reason) in split_parts.items():
        if cls == "X" and not reason:
            reason = R.SPLIT_X_REASONS.get(part_id, "")
        R.OVERRIDES[part_id] = (cls, cases, reason, "split part")

    # ---- fatal: dangling references ---------------------------------------
    fatal: list[str] = list(split_errors)
    # A split parent no longer exists as a row, so any reference to it is dead.
    for group, members in R.MERGE_GROUPS.items():
        for cid in members:
            if cid in R.SPLITS:
                fatal.append(
                    f"MERGE_GROUPS[{group!r}] references {cid!r}, which is split — "
                    f"point at a specific part (e.g. {cid}-a) so the merge names one "
                    f"proposition, not a conjunction")
    for cid in R.OVERRIDES:
        if cid not in by_id:
            fatal.append(f"OVERRIDES references nonexistent claim_id {cid!r}"
                         + (" (it was split — move the rule into SPLITS)"
                            if cid in R.SPLITS else ""))
    for cid in R.X_CLAIMS:
        if cid not in by_id:
            fatal.append(f"X_CLAIMS references nonexistent claim_id {cid!r}"
                         + (" (it was split — move the reason into SPLIT_X_REASONS)"
                            if cid in R.SPLITS else ""))
    for cid in R.SPLIT_X_REASONS:
        if cid not in by_id:
            fatal.append(f"SPLIT_X_REASONS references nonexistent part {cid!r}")
    for group, members in R.MERGE_GROUPS.items():
        for cid in members:
            if cid not in by_id:
                fatal.append(f"MERGE_GROUPS[{group!r}] references nonexistent {cid!r}")

    # A claim in two merge groups has two canonical sites, so "amend every site"
    # becomes ambiguous. Reject it.
    seen_member: dict[str, str] = {}
    for group, members in R.MERGE_GROUPS.items():
        for cid in members:
            if cid in seen_member:
                fatal.append(f"{cid!r} is in two merge groups: "
                             f"{seen_member[cid]!r} and {group!r}")
            seen_member[cid] = group

    # Every case referenced by a rule must exist in the case registry, or the
    # coverage matrix would cite a test that was never designed.
    for src, table in (("OVERRIDES", R.OVERRIDES), ("TYPE_RULES", R.TYPE_RULES),
                       ("ANCHOR_RULES", R.ANCHOR_RULES)):
        for key, (cls, cases, _reason, _note) in table.items():
            for case in cases:
                if case not in R.CASES:
                    fatal.append(f"{src}[{key!r}] cites unknown case {case!r}")
            if cases and cls in ("D", "N", "X"):
                fatal.append(f"{src}[{key!r}] is class {cls} but cites cases {cases}")
            if not cases and cls in ("E", "S", "C", "O"):
                fatal.append(f"{src}[{key!r}] is class {cls} with no cases")

    if fatal:
        print("FATAL — triage rules are inconsistent with claims_raw.csv:\n",
              file=sys.stderr)
        for msg in fatal:
            print(f"  {msg}", file=sys.stderr)
        print(f"\n{len(fatal)} error(s). No output written.", file=sys.stderr)
        return 2

    # ---- membership lookups ----------------------------------------------
    member_of: dict[str, tuple[str, str]] = {}   # cid -> (group, canonical)
    for group, members in R.MERGE_GROUPS.items():
        canon = members[0]
        for cid in members:
            member_of[cid] = (group, canon)

    out_rows: list[dict] = []
    stats = Counter()
    dropped = Counter()

    for row in raw:
        cid = row["claim_id"]
        if row["unit_type"] == "heading":
            dropped["heading (scope anchor)"] += 1
            continue
        if row["note"].startswith(NON_CLAIM_NOTES):
            dropped[row["note"].split()[0]] += 1
            continue

        cls, cases, reason, rule = resolve(row)
        group, canon = member_of.get(cid, ("", ""))

        # A merge group is one proposition restated. A restatement cannot need a
        # different class of evidence than the proposition itself, so a member
        # classified by a coarse anchor/type rule INHERITS the canonical site's
        # class and cases. Without this, s9's mermaid labels would be scored D
        # while the prose they restate is scored S — and the D rows would then be
        # invisible to the v1.3 amendment pass, which is exactly the "amended at
        # 1 of 4 sites" failure the merge groups exist to prevent.
        #
        # An explicit OVERRIDE or SPLIT for a member still wins: those were
        # written after reading the specific wording.
        if group and canon != cid and rule.startswith(("TYPE:", "ANCHOR:")):
            ccls, ccases, creason, _ = resolve(by_id[canon])
            cls, cases, reason = ccls, ccases, creason
            rule = f"INHERIT:{canon} (via {group})"

        out_rows.append({
            "claim_id": cid,
            "anchor": row["anchor"],
            "unit_type": row["unit_type"],
            "ordinal": row["ordinal"],
            "doc_line": row["doc_line"],
            "sha1": row["sha1"],
            "cls": cls,
            "cases": " ".join(cases),
            "merge_group": group,
            "canonical": "yes" if group and canon == cid else ("no" if group else ""),
            "merged_into": canon if group and canon != cid else "",
            "exclusion_reason": reason,
            "rule": rule,
            "note": row["note"],
            "text": row["text"],
        })
        stats[cls] += 1

    if args.check:
        if not OUT.exists():
            print(f"--check: {OUT.name} does not exist", file=sys.stderr)
            return 1
        with OUT.open(encoding="utf-8") as fh:
            committed = list(csv.DictReader(fh))
        derived = out_rows
        if len(committed) != len(derived):
            print(f"--check: row count differs (committed {len(committed)}, "
                  f"derived {len(derived)})", file=sys.stderr)
            return 1
        diffs = 0
        for c, d in zip(committed, derived):
            for f in FIELDS:
                if (c.get(f) or "") != (d.get(f) or ""):
                    if diffs < 10:
                        print(f"--check: {d['claim_id']} field {f!r} differs",
                              file=sys.stderr)
                    diffs += 1
        if diffs:
            print(f"--check: {diffs} field difference(s) — "
                  f"triage.csv is stale, re-run 01_triage.py", file=sys.stderr)
            return 1
        print(f"--check: triage.csv matches the rules ({len(derived)} rows)")
        return 0

    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out_rows)

    # ---- summary ----------------------------------------------------------
    print(f"wrote {OUT.relative_to(HERE.parent)}  ({len(out_rows)} claims)")
    print("\ndropped as non-claims by the extractor's own marking:")
    for k, v in dropped.most_common():
        print(f"  {v:>4}  {k}")

    print("\nclass distribution:")
    total = sum(stats.values())
    for cls in ("E", "S", "C", "O", "D", "N", "X", "UNCLASSIFIED"):
        if stats[cls]:
            print(f"  {cls:<13} {stats[cls]:>4}  ({stats[cls] / total:5.1%})")

    tested = sum(stats[c] for c in "ESCO")
    print(f"\n  directly tested (E+S+C+O) : {tested}/{total} = {tested / total:.1%}")
    print(f"  definitional / normative  : {stats['D'] + stats['N']}")
    print(f"  excluded with reason      : {stats['X']}")

    # Cases with no claim pointing at them are dead weight in the registry.
    cited = Counter()
    for r in out_rows:
        for case in r["cases"].split():
            cited[case] += 1
    orphan = sorted(set(R.CASES) - set(cited))
    print(f"\ncase registry: {len(R.CASES)} cases, {len(cited)} cited")
    if orphan:
        declared = [c for c in orphan if c in R.PLATFORM_CASES]
        undeclared = [c for c in orphan if c not in R.PLATFORM_CASES]
        if declared:
            print(f"  platform/prerequisite cases, declared in PLATFORM_CASES "
                  f"({len(declared)}): {', '.join(declared)}")
        if undeclared:
            print(f"  *** {len(undeclared)} case(s) cited by no claim and NOT declared "
                  f"in PLATFORM_CASES: {', '.join(undeclared)} ***")
            print(f"      Either a claim was missed in triage or the case is dead "
                  f"weight. check_coverage.py will fail.")

    by_family = defaultdict(int)
    for case, n in cited.items():
        by_family[R.CASES[case][0]] += n
    print("  claims per family: " +
          ", ".join(f"{f}={by_family[f]}" for f in sorted(by_family)))

    print(f"\nmerge groups: {len(R.MERGE_GROUPS)} covering "
          f"{len(member_of)} claims "
          f"({len(member_of) - len(R.MERGE_GROUPS)} restatements collapsed)")

    if stats["UNCLASSIFIED"]:
        print(f"\n*** {stats['UNCLASSIFIED']} UNCLASSIFIED claims — "
              f"check_coverage.py will fail. ***")
        for r in out_rows:
            if r["cls"] == "UNCLASSIFIED":
                print(f"    {r['claim_id']}  [{r['anchor']}/{r['unit_type']}]  "
                      f"{r['text'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
