#!/usr/bin/env python3
"""Recover the adjudication `day2_replicate.py` skipped when its freshness proof false-negatived.

Why this exists
---------------
`day2_replicate.py` mints a fresh `run_id`, passes it to the producer as `--run-id`, and afterwards
counts evidence records under `evidence/<minted_id>/` to prove the producer observed something today.
Gateway- and state-dependent producers do not honour that flag: `lib.testbed.State.load_or_new` loads
`state.json` and adopts the run id recorded there, so the records land under the *day-1* run id. The
proof then reads an empty (in fact non-existent) directory, prints `0 call record(s) dated <today>`,
and returns 2 — "did not observe" — over a run that observed a great deal.

The early `return 2` happens *before* the per-case comparison loop, so the run's
`results/day2_replication_<day>.json` is never written. Everything needed to write it still exists:
the pre-run snapshot of `results/phase1/` under `runner/.staging/day2_pre_<minted_id>/`, and the
post-run tree. This tool recomputes the comparison from those two, calling `day2_replicate`'s own
functions so the comparison logic is the driver's and not a second implementation of it.

It is deliberately incapable of executing a producer, moving a checkpoint, or writing a verdict file.
It reads two snapshots and writes one record. `provenance.derived_offline` is set on every run it
appends so no reader can mistake this for the driver's own output.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_driver():
    """Import `tools/day2_replicate.py` as a module so its comparison functions are reused."""
    path = ROOT / "tools" / "day2_replicate.py"
    spec = importlib.util.spec_from_file_location("day2_replicate", path)
    if spec is None or spec.loader is None:  # pragma: no cover - import machinery
        raise SystemExit(f"FATAL: cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["day2_replicate"] = mod
    spec.loader.exec_module(mod)
    return mod


def effective_run_id(d2r, before: dict[str, bytes], after: dict[str, bytes],
                     changed: list[str]) -> tuple[str, str]:
    """The run id the producer actually wrote under, read from the verdict files it re-emitted.

    Returns `(run_id, how_it_was_determined)`. This is the value the driver should have used for its
    freshness proof: a producer's own output is a stronger warrant for "which run id this was" than
    the flag we asked it to use, exactly as `evidence_date` prefers a record timestamp over a name.
    """
    ids = {d2r.run_id_of(after[n]) for n in changed if after.get(n)}
    ids.discard("")
    if len(ids) == 1:
        return ids.pop(), "run_id recorded in the re-emitted verdict files (unanimous)"
    if not ids:
        raise SystemExit("FATAL: no changed verdict file records a run id; cannot adjudicate")
    raise SystemExit(f"FATAL: changed verdict files disagree on run id {sorted(ids)}; a single "
                     f"producer invocation must write one run id — adjudicate by hand")


def failed_calls_run_wide(d2r, run_id: str, day: str) -> dict:
    """Every call record dated `day` under `run_id` that the SDK did not consider successful.

    Deliberately not a second copy of `day2_replicate.transient_failures()`. That function answers a
    narrower question — "was this specific case's observation invalidated by the service declining to
    look?" — and when this function was written it answered it through two filters that both failed on
    the 2026-08-19 run: a closed tuple of error *names* (`TRANSIENT_ERRORS`, which had no entry for
    botocore's `ReadTimeoutError` or a bare HTTP 500) and `_scoped()`, which could not match a
    directory named for two cases at once (`F6-2_5`). So it reported a clean observation over a run
    containing a 70-second read timeout, and `clean_observation: true` went into the record with
    nothing beside it to contradict it.

    BOTH OF THOSE FILTERS ARE FIXED (FUTURE-WORK items 33/34, 2026-08-22). `transient_failures()` now
    gates on the record's own `ok is False` — the same predicate as here — and scopes through
    `lib.case_ids`, and on this run's records it finds all eight failures and attributes four to each
    of F6-2/F6-5 and four to each of F6-6/F6-7/F6-8. Convergence is deliberate and this function is
    still not redundant, for a reason the fix does not remove: it is **un-scoped**. A case-scoped
    check can only ever report failures in the cases someone asked about, so a failure in a producer
    nobody requested that day stays invisible to it. The run-wide count is what makes "clean for every
    case I asked about" and "this run degraded" distinguishable in the emitted JSON.

    So: a predicate over the record's own `ok` flag rather than over a list of names, across the whole
    run id, with no case filter and no threshold. It cannot adjudicate anything and is not used to.
    """
    base = d2r.EVIDENCE / run_id
    if not base.is_dir():
        return {"scanned": 0}
    n = n_bad = 0
    codes: dict[str, int] = {}
    worst = 0.0
    for f in sorted(base.rglob("*.json")):
        if f.name in d2r.META:
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if str(d.get("t_start_utc") or "")[:10] != day:
            continue
        n += 1
        dur = d.get("duration_ms")
        if isinstance(dur, (int, float)):
            worst = max(worst, float(dur))
        if d.get("ok") is False:
            n_bad += 1
            code = d.get("error_code") or d.get("error_class") or "unrecorded"
            codes[str(code)] = codes.get(str(code), 0) + 1
    return {"scanned": n, "not_ok": n_bad, "error_codes": codes,
            "max_duration_ms": round(worst, 3),
            # This sentence is a claim about the OTHER function, so it expires when that
            # function changes ([[feedback_prose_is_not_verified]]). It read "no error-name
            # list and no case scoping" until 2026-08-22, when items 33/34 removed the name
            # list from `transient_failures()`; only the scoping difference survives, and
            # `error_codes` buckets a failure carrying no service code as "unrecorded"
            # rather than resolving it, which is why the two views can disagree on labels
            # while agreeing on the count.
            "basis": "the record's own `ok` flag over every case under this run id, with no "
                     "case filter — the one thing transient_failures() cannot see, because a "
                     "case-scoped check reports only on cases someone asked about"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pre-dir", required=True,
                    help="runner/.staging/day2_pre_<minted_run_id> written by the driver")
    ap.add_argument("--after-dir",
                    help="the state of results/phase1/ immediately AFTER this producer ran. When "
                         "several producers ran in sequence, that is the NEXT sub-run's pre-dir; "
                         "omit it only for the last sub-run, where the live tree is the after state. "
                         "Comparing an early sub-run against the live tree would attribute every "
                         "later sub-run's changes to this one.")
    ap.add_argument("--day", required=True, help="the UTC day the producer ran, YYYY-MM-DD")
    ap.add_argument("--cases", nargs="+", required=True, help="cases the producer was asked for")
    ap.add_argument("--reason", required=True,
                    help="why the driver's own adjudication did not run (recorded in the file)")
    ap.add_argument("--caveat", action="append", default=[],
                    help="a caveat this tool cannot derive, recorded verbatim under "
                         "provenance.caveats and marked as caller-supplied. Repeatable. Use it for "
                         "anything a reader of the emitted rows would otherwise have to know from "
                         "outside the file.")
    ap.add_argument("--write", action="store_true",
                    help="append to results/day2_replication_<day>.json (default: print only)")
    args = ap.parse_args()

    d2r = _load_driver()
    pre = Path(args.pre_dir)
    if not pre.is_absolute():
        pre = ROOT / pre
    if not pre.is_dir():
        print(f"FATAL: {pre} is not a directory", file=sys.stderr)
        return 2

    before = {p.name: p.read_bytes() for p in sorted(pre.glob("*.json"))}
    if len(before) < 10:
        # The same reasoning as check_redaction.py's MIN_FILES: a snapshot that reads almost nothing
        # produces "no case changed", which reads as agreement. An under-reading snapshot is an
        # error, not a clean result.
        print(f"FATAL: snapshot holds {len(before)} verdict file(s); that is too few to be a "
              f"snapshot of results/phase1/ — refusing to adjudicate against it", file=sys.stderr)
        return 2

    if args.after_dir:
        adir = Path(args.after_dir)
        if not adir.is_absolute():
            adir = ROOT / adir
        if not adir.is_dir():
            print(f"FATAL: {adir} is not a directory", file=sys.stderr)
            return 2
        after = {p.name: p.read_bytes() for p in sorted(adir.glob("*.json"))}
        if len(after) != len(before):
            print(f"FATAL: snapshot sizes differ ({len(before)} before, {len(after)} after); the "
                  f"two must be snapshots of the same directory", file=sys.stderr)
            return 2
        after_src = str(adir.relative_to(ROOT))
    else:
        after = d2r.snapshot_phase1()
        after_src = "results/phase1/ (live tree)"
    print(f"before: {pre.relative_to(ROOT)} ({len(before)} files)")
    print(f"after:  {after_src} ({len(after)} files)")
    changed = sorted(k for k, v in after.items() if before.get(k) != v)
    if not changed:
        print("NOTHING TO ADJUDICATE — no verdict file differs from the snapshot", file=sys.stderr)
        return 2

    requested = {f"{c}.json" for c in args.cases}
    outside = [c for c in changed if c not in requested]
    if outside:
        # A producer that rewrote a case nobody asked for is a finding in its own right, and it must
        # not be quietly folded into this run's row set.
        print(f"FATAL: {outside} changed but were not among --cases; a producer that writes outside "
              f"the requested case set must be investigated, not adjudicated", file=sys.stderr)
        return 2

    run_id, how = effective_run_id(d2r, before, after, changed)
    # The driver builds its `day1_dates` map inline in `main()`, so it is not importable. Passing an
    # empty map makes `day1_label` fall back to `run_id_date(run_id_of(old))` — the day named by the
    # day-1 run id in the archived file itself, which is the same value the driver's own archive
    # filenames were built from, so the two agree by construction rather than by coincidence.
    day1_dates: dict[str, str] = {}
    day1_sources: dict[str, str] = {
        c: "run_id_date(day-1 verdict file's own run_id)" for c in args.cases}

    n_fresh = d2r.fresh_records(run_id, args.day)
    caps, n_calls = d2r.zero_call_capture(run_id, args.day)
    print(f"effective run id: {run_id}  ({how})")
    print(f"observation proof under that id: {n_fresh} call record(s) dated {args.day}")
    if n_fresh == 0:
        print("FATAL: even under the effective run id nothing was observed today; this is a genuine "
              "rc=2 and there is nothing to adjudicate", file=sys.stderr)
        return 2

    rows, disagreed, not_same_test, caveats = [], [], [], []
    for name in changed:
        case = name[: -len(".json")]
        old, new = before[name], after[name]
        v1, v2 = d2r.verdict_of(old), d2r.verdict_of(new)
        diffs = d2r.record_diff(d2r.record_of(old), d2r.record_of(new))
        broke = sorted({p.split(".")[0].split("[")[0].split(" ")[0] for p in diffs}
                       & set(d2r.SEALED_FIELDS))
        pquant, pvol = d2r.payload_diff(old, new, (d2r.run_id_of(old), d2r.run_id_of(new)))
        trans = d2r.transient_failures(run_id, args.day, case)
        d1 = d2r.day1_label(case, old, day1_dates)
        if trans:
            caveats.append(case)
        if v1 != v2:
            disagreed.append(case)
        if broke:
            not_same_test.append(case)
        rows.append({"case_id": case, "status": "AGREE" if v1 == v2 else "DISAGREE",
                     "day1_date": d1, "day1_run_id": d2r.run_id_of(old), "day1_verdict": v1,
                     "day2_date": args.day, "day2_run_id": d2r.run_id_of(new), "day2_verdict": v2,
                     "day1_archived_to": f"results/phase1/archive/{case}__day1_{d1}.json",
                     "record_identical": not diffs,
                     "record_fields_differing": diffs[:40],
                     "record_fields_differing_total": len(diffs),
                     "sealed_fields_differing": broke,
                     "payload_fields_differing": pquant[:40],
                     "payload_fields_differing_total": len(pquant),
                     "payload_run_scoped_differences": len(pvol),
                     "clean_observation": not trans,
                     # Key names follow day2_replicate.py's; see its `schema_change` block.
                     "failed_calls": [{"evidence": p, "reason": c} for p, c in trans]})
        print(f"  [{'AGREE' if v1 == v2 else 'DISAGREE'}] {case}: {d1} {v1} -> {args.day} {v2}"
              f"  | record paths differing: {len(diffs)} | sealed moved: {broke or 'none'}")

    failed = failed_calls_run_wide(d2r, run_id, args.day)
    print(f"run-wide calls dated {args.day}: {failed.get('scanned')} records, "
          f"{failed.get('not_ok')} not ok {failed.get('error_codes') or ''}")
    if failed.get("not_ok") and not caveats:
        # Not fatal: `clean_observation` is the driver's own function and this tool must not
        # overwrite it. But a row saying "clean" beside a run with failed calls is the shape that
        # let F8-5's throttled probe be counted as an observation, so it is printed loudly and
        # carried into the record rather than left for a reader to discover.
        print("  NOTE: every requested case reports clean_observation, yet this run id has failed "
              "calls today — see provenance.failed_calls_run_wide and FUTURE-WORK item 34")

    entry = {"run_id": run_id, "utc_date": args.day, "cases_requested": args.cases,
             "producer": None, "fresh_records": n_fresh,
             "observation_proof": f"{n_fresh} call record(s) dated {args.day}",
             "day1_date_source": day1_sources,
             "summaries_captured_today": caps, "calls_reported": n_calls,
             "checkpoints_archived": None, "day1_files_archived": None,
             "cases_with_failed_calls": caveats, "results": rows,
             "provenance": {"derived_offline": True,
                            "tool": "tools/day2_adjudicate_offline.py",
                            "reason": args.reason,
                            "caveats_caller_supplied": args.caveat,
                            "failed_calls_run_wide": failed,
                            "snapshot": str(pre.relative_to(ROOT)),
                            "after_state": after_src,
                            "effective_run_id_determined_by": how,
                            "note": "The comparison is day2_replicate.py's own functions applied to "
                                    "its own pre-run snapshot. The producer command line, the "
                                    "checkpoint moves and the archive writes were performed by the "
                                    "driver in the original run and are recorded in its stdout log, "
                                    "not here."}}

    if args.write:
        out = ROOT / "results" / f"day2_replication_{args.day}.json"
        prior = json.loads(out.read_text()) if out.is_file() else {"runs": []}
        prior["runs"].append(entry)
        import lib.redact as _redact  # noqa: PLC0415 - only needed on the write path
        out.write_text(_redact.mask_text(
            json.dumps(prior, indent=2, sort_keys=True, ensure_ascii=False) + "\n"),
            encoding="utf-8")
        print(f"  wrote {out.relative_to(ROOT)}")
    else:
        print("  (not written — pass --write to append the record)")

    if disagreed:
        print(f"DISAGREEMENT — {len(disagreed)} case(s) disagree with day 1: {disagreed}. Per the "
              f"pre-registration this is a FINDING, not a fix-up: do not amend.", file=sys.stderr)
        return 1
    if not_same_test:
        print(f"NOT REPLICATED — {not_same_test} agree on the verdict but a sealed field moved",
              file=sys.stderr)
        return 1
    print(f"REPLICATED — {len(rows)} case(s) agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
