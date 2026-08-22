#!/usr/bin/env python3
"""What widening `observation_days`' case matching did to every finding's day set.

FUTURE-WORK item 34 changed `check_amendment_readiness.observation_days` from comparing
`case_id` for equality to resolving it through `lib.case_ids`. That is a WIDENING of a
replication gate, and a widening is the dangerous direction: the gate's whole job is to refuse
an amendment resting on one calendar day, so a rule that hands a finding a second day it did
not earn converts the gate into a rubber stamp. "It only matches records of the same case" is a
claim about a resolver; this file measures the consequence on the real tree instead.

For every finding under `results/`, both rules are run over the same records and the output
records matched-record count and day set for each. The number that decides whether the change
is safe is not the count of records that moved — it is whether any finding's DAY COUNT crossed
`MIN_DAYS`, because that is the only quantity the gate acts on.

ONE VARIABLE AT A TIME. Each arm runs against the `cases` declaration **it** was written for, which
is why `DECLARATION_BEFORE` exists. The F6 finding declared producer-group ids only because
equality matching could not accept a real case id, so pointing the equality arm at its new
nine-case declaration reports a boundary crossing caused entirely by the declaration edit — the
first run of this tool did exactly that and exited 1, which is the tool working and a reminder that
a comparison moving two variables cannot attribute what it finds.

Writes `results/ITEM34-GATE-DELTA.json` and exits 1 if any finding crossed the boundary, so a
future edit to `lib/case_ids.py` that over-reaches fails here rather than silently licensing an
amendment. Exits 2 if it could not read the evidence at all — a comparison over zero records
must not report "no change" ([[feedback_zero_file_scan_is_error]]).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from check_amendment_readiness import (BLOCK_RE, EVIDENCE, MIN_DAYS,  # noqa: E402
                                       RESULTS)
from lib.case_ids import case_ids_in  # noqa: E402


# A finding whose `cases` declaration changed in the SAME change as the matching rule, with what
# it declared before. Both arms must be run against the declaration each was written for, or the
# comparison moves two variables at once and its verdict means nothing: the F6 finding declared
# three producer-group ids precisely BECAUSE equality matching could not accept a real case id, so
# running the equality rule against its new nine-case declaration finds 6 records and 0 days and
# reports a boundary crossing that no change in matching caused.
#
# This map is not general bookkeeping and must not become a habit — it exists for one edit, and an
# entry may be deleted once that edit is in `main` and the two arms agree on the declaration
# again. An entry that is WRONG makes this tool report clean over a real crossing, so each one
# names its reason.
DECLARATION_BEFORE = {
    # Rewritten to the nine real verdict ids in the same change; see the finding's `cases_note`.
    "FINDING-F6-DAY2-DECISIVENESS.md": ["F6-1_3_4_9", "F6-2_5", "F6-6_7_8"],
}


def days_under(run_ids: list[str], cases: list[str], *, resolve: bool) -> tuple[set[str], int]:
    """Distinct UTC days and matched-record count, under one of the two matching rules.

    A deliberate re-implementation of `observation_days`' loop rather than a call into it: the
    point is to run the OLD rule, which no longer exists in that file. Kept to the same reads
    (`case_id`, `t_start_utc`, skipping `environment.json`) so the only difference between the
    two arms is the match test itself.
    """
    wanted = set(cases)
    if resolve:
        for c in cases:
            wanted.update(case_ids_in(c))
    days: set[str] = set()
    n = 0
    for rid in run_ids:
        d = EVIDENCE / rid
        if not d.is_dir():
            continue
        for p in d.rglob("*.json"):
            if p.name == "environment.json":
                continue
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            cid = rec.get("case_id")
            hit = cid in wanted
            if resolve and not hit:
                hit = bool(set(case_ids_in(cid)) & wanted)
            if not hit:
                continue
            n += 1
            ts = rec.get("t_start_utc")
            if ts:
                days.add(str(ts)[:10])
    return days, n


def main() -> int:
    if not EVIDENCE.is_dir():
        print("FATAL: evidence/ is absent, so nothing can be compared. evidence/ is "
              "local-only; run this on the machine that holds the records.", file=sys.stderr)
        return 2
    findings = sorted(RESULTS.glob("FINDING-*.md"))
    if not findings:
        print("FATAL: no FINDING-*.md under results/", file=sys.stderr)
        return 2

    rows = []
    n_read = 0
    for f in findings:
        m = BLOCK_RE.search(f.read_text(encoding="utf-8"))
        if not m:
            continue
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        runs = meta.get("evidence_runs") or []
        cases = meta.get("cases") or []
        if not runs or not cases:
            continue
        old_cases = DECLARATION_BEFORE.get(f.name, cases)
        old_days, old_n = days_under(runs, old_cases, resolve=False)
        new_days, new_n = days_under(runs, cases, resolve=True)
        n_read += new_n
        rows.append({
            "finding": f.name,
            "status": meta.get("status"),
            "cases_declared": cases,
            "cases_declared_before": old_cases if old_cases != cases else None,
            "evidence_runs": runs,
            "equality_rule": {"records": old_n, "days": sorted(old_days),
                              "cases": old_cases},
            "case_ids_rule": {"records": new_n, "days": sorted(new_days), "cases": cases},
            "records_gained": new_n - old_n,
            "days_gained": sorted(new_days - old_days),
            "crossed_min_days": (len(old_days) < MIN_DAYS <= len(new_days)),
        })

    if n_read == 0:
        print("FATAL: the comparison matched 0 records under either rule, so it establishes "
              "nothing", file=sys.stderr)
        return 2

    crossed = [r["finding"] for r in rows if r["crossed_min_days"]]
    out = RESULTS / "ITEM34-GATE-DELTA.json"
    out.write_text(json.dumps({
        "what": "check_amendment_readiness.observation_days, case matching by equality vs by "
                "lib.case_ids, over the same evidence records",
        "min_days": MIN_DAYS,
        "findings_compared": len(rows),
        "records_matched_by_the_new_rule": n_read,
        "findings_that_crossed_min_days": crossed,
        "rows": rows,
    }, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}: {len(rows)} finding(s), "
          f"{n_read} record(s) matched by the new rule")
    for r in rows:
        if r["records_gained"] or r["days_gained"]:
            print(f"  {r['finding']}: records {r['equality_rule']['records']} -> "
                  f"{r['case_ids_rule']['records']}, days "
                  f"{r['equality_rule']['days']} -> {r['case_ids_rule']['days']}")
    if crossed:
        print(f"FAIL: {crossed} went from under MIN_DAYS={MIN_DAYS} to at or over it purely "
              f"because the matching rule widened. A second calendar day must be earned by a "
              f"second observation, not by a resolver.", file=sys.stderr)
        return 1
    print(f"OK — no finding crossed MIN_DAYS={MIN_DAYS} on the matching change alone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
