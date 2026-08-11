#!/usr/bin/env python3
"""Compare two F5-7a runs and decide whether the second one replicates the first.

Why this is a script and not a paragraph of my judgement
-------------------------------------------------------
F5-7a's amendment to §4.5.3 rests on the content of a **web page**, and the thing that
changed IS that content. §7's alternative-explanation register lists two readings a
single read cannot separate:

  * AWS shipped PrivateLink support for Evaluations and Optimization (durable), or
  * the page we read was a stale CDN variant, an A/B-tested render, or a mid-deploy
    state (transient).

A second read on a later calendar day excludes a gross transient. But "I looked again
and it said the same thing" is exactly the class of claim this project does not accept
from prose, so the comparison is mechanical and its criteria are fixed **before** the
second run's data is consulted.

The load-bearing design decision: two disjoint field sets
---------------------------------------------------------
Not everything in an F5-7a run should be expected to match, and a comparator that
demanded byte-identity would fail on the first run for reasons that say nothing about
AWS — which would make it useless and, worse, would train me to override it.

  * **MUST_MATCH** — the observations the amendment quotes. If any of these differs, the
    two days disagree and no amendment is licensed. Encoded as explicit extractors so
    each one is a named assertion rather than a whole-object comparison.
  * **MAY_VARY** — instrument-side facts with no bearing on the claim: request IDs, fetch
    timestamps, and the Internet Archive's CDX result set, which is a *query against a
    third-party index* and returns different snapshot sets on different days. Differences
    here are reported, never fatal.

The set a difference falls into is decided by this file, which is why the third check
below exists: a comparator can be defeated by moving a field from MUST_MATCH to
MAY_VARY, so the count of must-match assertions has a floor.

Wayback deserves its own rule. Snapshots that appear in both runs must agree on
**content** — an archived page is immutable, so a differing archived row would mean one
of the two parses is wrong and would discredit instrument B entirely. Snapshots present
in only one run are an availability difference and are reported as such.

Exit codes: 0 replicated · 1 the two runs disagree · 2 the comparison could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"
CASE = "f5/F5-7a"

# A floor on the number of must-match assertions, for the same reason verify_phase0.sh
# pins a collected-test count per directory: a comparator that quietly stops comparing
# reports "replicated" and is indistinguishable from one that works.
MIN_ASSERTIONS = 20


def fatal(msg: str) -> int:
    print(f"FATAL: {msg}", file=sys.stderr)
    return 2


def load(run_id: str) -> dict:
    p = EVIDENCE / run_id / CASE / "analysis.json"
    if not p.is_file():
        raise FileNotFoundError(f"{p} does not exist")
    return json.loads(p.read_text(encoding="utf-8"))


def observation_day(run_id: str) -> str:
    """The calendar day of a run, from the evidence records — never from the run id.

    Same rule as check_amendment_readiness.py: a run id is a label a person chooses, so
    trusting it would let `r20260810T…` claim a second day while its records all carry
    the first day's timestamps.
    """
    days = set()
    base = EVIDENCE / run_id / CASE
    for f in sorted(base.glob("*.json")):
        if f.name in ("environment.json", "analysis.json", "summary.json"):
            continue
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        ts = rec.get("t_start_utc")
        if ts:
            days.add(str(ts)[:10])
    return sorted(days)[0] if days else ""


def must_match(a: dict) -> dict[str, object]:
    """Every observation the §4.5.3 amendment quotes, flattened into named assertions.

    Flattened deliberately: comparing `a["analysis"] == b["analysis"]` would be one
    assertion whose failure message is "the analysis differs", and locating the field
    would then be my job rather than the tool's.
    """
    out: dict[str, object] = {}
    an = a["analysis"]

    # -- the six verdicts. These are the finding.
    for name, f in sorted(an["findings"].items()):
        out[f"verdict:{name}"] = f["verdict"]

    # -- the endpoint-service enumeration (instrument A)
    out["endpoint_prefixes"] = sorted(an["endpoint_prefixes"])
    out["endpoint_set_identical_across_regions"] = an["endpoint_set_identical_across_regions"]
    out["regions_reachable"] = sorted(an["regions_reachable"])
    out["regions_unreachable"] = sorted(an["regions_unreachable"])

    for reg in a["instrument_A"]:
        r = reg["region"]
        out[f"A:{r}:n_agentcore"] = reg["n_agentcore"]
        out[f"A:{r}:reachable"] = reg["reachable"]
        out[f"A:{r}:services"] = sorted(reg["agentcore_services"])
        # The keyword hits are the negative result: no endpoint service is NAMED for
        # Evaluations or Optimization. A hit appearing on day 2 would change the finding.
        out[f"A:{r}:primitive_keyword_hits"] = {
            k: sorted(v) for k, v in sorted(reg["primitive_keyword_hits"].items())}
        # private_dns and policy support are what make an endpoint usable; the caveat-b
        # verdict rests on the third prefix existing with its own DNS name.
        out[f"A:{r}:private_dns"] = sorted(
            d["private_dns"] for d in reg["agentcore_service_details"])
        out[f"A:{r}:policy_supported"] = sorted(
            (d["service_name"], d["vpc_endpoint_policy_supported"])
            for d in reg["agentcore_service_details"])

    # -- the live AWS page (instrument B). The heart of the replication.
    live = a["instrument_B"]["live"]
    out["B:live:ok"] = live["ok"]
    out["B:live:has_support_table"] = live["has_support_table"]
    out["B:live:n_endpoints_stated"] = live["n_endpoints_stated"]
    out["B:live:endpoint_names_stated"] = sorted(live["endpoint_names_stated"])
    for row, cells in sorted(live["rows"].items()):
        out[f"B:live:row:{row}"] = cells
    return out


def wayback_rows(a: dict) -> dict[str, dict]:
    return {w["timestamp"]: {"ok": w["ok"],
                             "has_support_table": w["has_support_table"],
                             "n_endpoints_stated": w["n_endpoints_stated"],
                             "rows": w["rows"]}
            for w in a["instrument_B"]["wayback"]}


def compare(day1: str, day2: str) -> tuple[list[str], list[str], int]:
    """Returns (disagreements, notes, n_assertions)."""
    a, b = load(day1), load(day2)
    bad: list[str] = []
    notes: list[str] = []

    d1, d2 = observation_day(day1), observation_day(day2)
    if not d1 or not d2:
        bad.append(f"a run has no dated evidence records ({day1}={d1!r}, {day2}={d2!r}); "
                   f"without a date from the records themselves there is nothing to "
                   f"establish that these are two separate days")
    elif d1 == d2:
        bad.append(f"both runs were collected on {d1}. A same-day repeat cannot "
                   f"distinguish a durable change from a transient publication state, "
                   f"which is the only thing this comparison exists to do")
    else:
        notes.append(f"day 1 = {d1} ({day1}), day 2 = {d2} ({day2})")

    ma, mb = must_match(a), must_match(b)
    only_a, only_b = sorted(set(ma) - set(mb)), sorted(set(mb) - set(ma))
    for k in only_a:
        bad.append(f"{k} was observed on day 1 and is absent on day 2")
    for k in only_b:
        bad.append(f"{k} appeared on day 2 and was absent on day 1")
    shared = sorted(set(ma) & set(mb))
    for k in shared:
        if ma[k] != mb[k]:
            bad.append(f"{k}: day 1 = {ma[k]!r}, day 2 = {mb[k]!r}")

    # Wayback: immutable where present in both, availability-variant otherwise.
    wa, wb = wayback_rows(a), wayback_rows(b)
    both = sorted(set(wa) & set(wb))
    for ts in both:
        if wa[ts] != wb[ts]:
            bad.append(f"archived snapshot {ts} parsed differently on the two days — an "
                       f"archived page is immutable, so one of the two parses is wrong "
                       f"and instrument B cannot be relied on until that is explained")
    dropped, added = sorted(set(wa) - set(wb)), sorted(set(wb) - set(wa))
    if dropped:
        notes.append(f"{len(dropped)} snapshot(s) returned on day 1 and not day 2: "
                     f"{', '.join(dropped)} — the CDX index is a third-party query, and "
                     f"its result set is not an observation about AWS")
    if added:
        notes.append(f"{len(added)} snapshot(s) new on day 2: {', '.join(added)}")
    notes.append(f"{len(both)} archived snapshot(s) present both days, all parsing "
                 f"identically")

    n = len(shared) + len(both)
    if n < MIN_ASSERTIONS:
        bad.append(f"only {n} field(s) were compared, below the floor of "
                   f"{MIN_ASSERTIONS}. A comparison this thin cannot license an "
                   f"amendment regardless of whether it found a difference")
    return bad, notes, n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("day1")
    ap.add_argument("day2")
    ap.add_argument("--json", metavar="PATH", help="write the verdict as JSON")
    args = ap.parse_args(argv)

    try:
        bad, notes, n = compare(args.day1, args.day2)
    except FileNotFoundError as e:
        return fatal(str(e))
    except KeyError as e:
        return fatal(f"a run is missing field {e} — the schema changed between runs, so "
                     f"the two are not comparable")

    for note in notes:
        print(f"  note: {note}")
    print(f"\n{n} field(s) compared")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "day1": args.day1, "day2": args.day2,
            "n_fields_compared": n,
            "replicated": not bad,
            "disagreements": bad,
            "notes": notes,
        }, indent=2) + "\n", encoding="utf-8")

    if bad:
        print(f"\nNOT REPLICATED — {len(bad)} disagreement(s):", file=sys.stderr)
        for x in bad:
            print(f"  - {x}", file=sys.stderr)
        return 1
    print("REPLICATED — every observation the §4.5.3 amendment quotes was identical on "
          "two separate calendar days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
