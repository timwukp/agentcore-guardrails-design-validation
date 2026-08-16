#!/usr/bin/env python3
"""Run one producer a second time on a later UTC day, and prove that it actually did.

Why this exists as a driver rather than a command per case
---------------------------------------------------------
`PREREGISTRATION.yaml`'s `reproduction_before_amendment` bar, under the strict reading the
user chose on 2026-08-15 ("從嚴"), needs observations on two separate **UTC** calendar days
before an amendment stands. Twelve cases were amended on one day's data and each owes a
second day. Doing that by hand is three separate ways to publish a replication that never
happened:

1.  **Checkpoint resume.** `lib.checkpoint.Checkpoint` names its file `<case>__<cell>.json`
    under `results/checkpoints/` — the run id is deliberately **not** in the path, because
    varying the run id is how this project re-emits an analysis without re-billing. So a
    second run of a checkpointed case finds every trial already recorded, skips all of
    them, re-derives the same verdict from day-1 rows, and **exits 0**. Nothing in the
    output says the API was never called. This driver moves the day-1 checkpoints aside
    first, and then requires fresh evidence records dated today before it will call
    anything a replication.
2.  **A same-UTC-day repeat.** The local calendar rolls hours before UTC does; a run at
    2026-08-15T22:00 local can be 2026-08-15T14:00Z, the same UTC day as day 1
    (`f5_redteam/07a_run_day2.sh` was written after exactly that mistake). This refuses to
    run when today's UTC date equals a target case's day-1 date.
3.  **A silent overwrite.** `lib.phase1.emit` rewrites `results/phase1/<case>.json`
    unconditionally, so the day-1 verdict file is *replaced* by the day-2 one. Without an
    archive there is nothing left to compare against, and a disagreement between the two
    days — which is a finding in its own right, not a fix-up — would simply vanish.
    The whole of `results/phase1/` is snapshotted to a local-only staging directory
    **before** the producer runs, and the archive copies are written from that snapshot.
    The first version of this driver archived *after* its own post-run guards passed, and a
    guard that fired therefore left sixteen rewritten verdict files with no day-1 copy
    anywhere in the tree — recoverable only because the handover bundle happened to hold
    them. A recovery path that depends on luck is not one.

    The snapshot is deleted again on a clean run, and only then — see `drop_snapshot`. It is
    98 verdict files (~5 MB) per run, `runner/.staging/` has a written 80,000 KB ceiling it
    has breached once already (DEV-P4-36), and once the day-1 copies are in
    `results/phase1/archive/` the staging copy is redundant. Deletion is refused unless every
    changed case's archive file exists and matches byte-for-byte, and a run that disagreed
    with day 1 keeps its snapshot: that run's evidence is the point of it.

A producer typically rewrites more cases than the ones being replicated — the F1 surface
script decides sixteen. Every changed case is archived and compared, not just the named
ones, because the alternative is a file whose provenance silently moved to a run nobody
adjudicated.

What it does NOT do
-------------------
It does not touch `results/phase1/*.json` itself, does not edit any FINDING doc, and does
not decide anything about amendment readiness. A disagreement is reported and returns
rc 1; it is for a human to adjudicate, because per the pre-registration a day-2 that
contradicts day 1 is evidence, not an error to be corrected.

It also cannot fix a case whose day 2 needs day-1 *infrastructure*: `lib.testbed.State`
refuses to load a state file written under a different run id. Gateway-dependent producers
(F6-1/3/4, F4-6, F2-1) therefore need `--state` or a rebuilt testbed, which is the calling
script's problem, not this one's.

Exit codes: 0 every changed case agrees with day 1 · 1 at least one disagrees (a finding —
do not amend) · 2 the run could not complete, or completed without observing anything.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHASE1 = ROOT / "results" / "phase1"
ARCHIVE = PHASE1 / "archive"
CP_ROOT = ROOT / "results" / "checkpoints"
EVIDENCE = ROOT / "evidence"

sys.path.insert(0, str(ROOT))
from lib import evidence as E  # noqa: E402
from lib import redact as _redact  # noqa: E402


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def mint_run_id() -> str:
    return datetime.now(timezone.utc).strftime("r%Y%m%dT%H%M%SZ")


def run_id_date(run_id: str) -> str | None:
    """The UTC date a run id names, or None if it is not a dated run id.

    Deliberately does not fall back to a file mtime: an mtime is the date the analysis was
    *written*, which a re-emit moves, and this is used to decide whether a replication is
    legitimate.
    """
    m = E.RUN_ID_RE.match(run_id or "")
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def snapshot_phase1() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(PHASE1.glob("*.json"))}


def _scoped(parts: tuple[str, ...], case: str | None) -> bool:
    """Does an evidence path belong to `case`? `None` means "every case in the run".

    A path component must BE the case id or start `<case>-` (stratum directories such as
    `F8-4-classic-benign`). Substring matching would credit F8-5's records to F8-50, and an
    unscoped match would let the busiest case in a run date or contaminate every other one.
    """
    return case is None or any(p == case or p.startswith(case + "-") for p in parts)


def evidence_date(case: str, run_id: str) -> tuple[str | None, str]:
    """The UTC day `case` was actually observed under `run_id`, read from the records.

    Why a second source exists at all
    ---------------------------------
    Two published verdicts — F8-5 (FALSE) and F8-8 (TRUE) — carry `run_id`
    `smoke20260810T0305Z`, which `lib.evidence.RUN_ID_RE` does not match, so `run_id_date`
    returns None and the day-1 guard refuses the case outright. That refusal is correct about
    the *string* and wrong about the *evidence*: F8-5's five call records under
    `evidence/smoke20260810T0305Z/f8/F8-5/` are stamped 2026-08-10T02:45:52Z–02:45:56Z, and a
    timestamp inside the record is a stronger warrant for "which day this was observed" than a
    filename an operator typed. (The run id even disagrees with them — it says 03:05.)

    This is NOT the mtime fallback `run_id_date` refuses. An mtime moves when a file is
    rewritten; `t_start_utc` is written by the call that made the observation and a re-emit
    cannot move it. The conditions are deliberately strict, because the value of this function
    is that a replication claim rests on it:

    * the records must be under `evidence/<run_id>/` and under a path component that is the
      case id or a `<case>-<stratum>` directory — not merely somewhere in the run;
    * every dated record must agree on ONE UTC day. Records spanning two days mean the run
      itself straddled a boundary, and "day 1" is then not a single day — refused, not
      averaged;
    * `captured_utc` from `summary.json`/`analysis.json` is used only when no call record
      carries `t_start_utc`, and it is reported as the weaker source, because a summary is
      written on every run whether or not anything was observed.

    Returns `(date, source)`, or `(None, reason)` when no date can be established.
    """
    base = EVIDENCE / run_id
    if not base.is_dir():
        return None, f"evidence/{run_id}/ does not exist"
    call_days: set[str] = set()
    meta_days: set[str] = set()
    for f in base.rglob("*.json"):
        if not _scoped(f.relative_to(base).parts, case):
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001 - an unreadable record contributes no date
            continue
        if f.name in META:
            if d.get("captured_utc"):
                meta_days.add(str(d["captured_utc"])[:10])
        elif d.get("t_start_utc"):
            call_days.add(str(d["t_start_utc"])[:10])
    days, src = (call_days, "call records' t_start_utc") if call_days \
        else (meta_days, "summary/analysis captured_utc (weaker: written every run)")
    if not days:
        return None, f"no dated record for {case} under evidence/{run_id}/"
    if len(days) > 1:
        return None, (f"{case}'s records under evidence/{run_id}/ span {sorted(days)} — "
                      f"more than one UTC day, so day 1 is not a single day")
    return days.pop(), src


def verdict_of(raw: bytes) -> str:
    try:
        return str(json.loads(raw).get("verdict"))
    except Exception:  # noqa: BLE001 - a corrupt verdict file is reported, not raised past
        return "<unparseable>"


def record_of(raw: bytes) -> dict:
    """The sealed oracle's decision record, or `{}` if the file has none."""
    try:
        r = json.loads(raw).get("record")
    except Exception:  # noqa: BLE001
        return {}
    return r if isinstance(r, dict) else {}


# The three fields of `record` that come from the SEAL rather than from the observation.
# `kind` is the oracle form, `thresholds` the pinned numbers it compares against, `planned_n`
# the pre-registered per-stratum n. None of them can legitimately differ between two days of
# the same case: if they do, the two runs did not evaluate the same test, and a matching
# verdict is a coincidence rather than a replication.
SEALED_FIELDS = ("kind", "thresholds", "planned_n")


def record_diff(old: object, new: object, path: str = "") -> list[str]:
    """Dotted paths at which two decision records differ, deepest-first.

    Why the driver compares this and not just `verdict`
    ---------------------------------------------------
    F3-4's replication agreed on FALSE, and the interesting part was not the verdict: the same
    9 of 31 entity strata were refuted with **identical success counts in 31 of 31 strata**.
    That comparison was done by hand, and a hand comparison is one that the next case does not
    get. A day 2 whose verdict agrees while its counts have moved is a different finding from a
    day 2 that reproduces the numbers, and with a verdict-only check the difference between
    those two outcomes is invisible — the driver prints AGREE either way.

    `record` is the right object to compare because it is the one part of a verdict file with
    the same shape for every case (`lib.oracle` writes `kind`, `n_attempted`, `n_usable`,
    `n_met`, `p_value`, `thresholds`, `evidence`), so this works for F3-4's 31 strata and
    F8-5's four boundary probes without knowing anything about either.

    What a difference here does and does not mean
    --------------------------------------------
    `record` carries no run id, so a drift is not merely a re-label. It is NOT free of
    timestamps, though: run against the 23 day-1 files already in `results/phase1/archive/`,
    22 compared identical and the one that drifted was **F5-4a**, at 61 paths that are all
    CloudWatch metric window bounds inside `record.evidence` — values that must move on a
    second day. So drift is reported and recorded, never fatal on its own. Only
    `SEALED_FIELDS` moving is treated as an error, because those three come from the seal
    rather than from the observation.

    (An earlier version of this docstring asserted the record held no timestamps at all. That
    was wrong, and F5-4a is how it was found — which is the reason the comparison was run
    against every real archived file before being trusted.)
    """
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in sorted(set(old) | set(new)):
            p = f"{path}.{k}" if path else k
            if k not in old:
                out.append(f"{p} (absent day 1)")
            elif k not in new:
                out.append(f"{p} (absent day 2)")
            else:
                out.extend(record_diff(old[k], new[k], p))
        return out
    if isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            return [f"{path} (length {len(old)} -> {len(new)})"]
        out = []
        for i, (a, b) in enumerate(zip(old, new)):
            out.extend(record_diff(a, b, f"{path}[{i}]"))
        return out
    return [] if old == new else [f"{path}: {json.dumps(old)} -> {json.dumps(new)}"]


# Leaf keys whose value is *expected* to move between two runs of the same test: identifiers the
# service mints, paths that embed a run id, clocks. Listing them is what lets the rest of a verdict
# file be compared at all — without the split, every case would report dozens of differences and the
# one that matters would be indistinguishable from the noise.
VOLATILE_KEYS = (
    "run_id", "request_id", "request_ids", "guardrail_id", "guardrail_arn", "arn", "name",
    "evidence", "evidence_path", "t_start_utc", "t_end_utc", "captured_utc", "created_at",
    "createdAt", "updatedAt", "version", "duration_ms", "latency_ms", "elapsed_ms", "trace_id",
    "sdk", "sdk_version", "boto3", "botocore", "request_ids",
)


def payload_diff(old: bytes, new: bytes,
                 run_ids: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Differences OUTSIDE `record`, split into `(quantitative, run-scoped)`.

    Why comparing `record` is not enough — F8-4, 2026-08-15
    ------------------------------------------------------
    F8-4's day 2 agreed on FALSE and its decision record was identical **at every path**, because
    that record is two booleans and a proxy string (`classic_works`, `standard_works`,
    `observed`). The numbers the document reasons about live one level up, in `tier_proxy` and
    `checks_arms`, and they had moved: STANDARD's PROMPT_ATTACK recall went 119/120 -> 118/120,
    and the `InvokeGuardrailChecks` threshold sweep moved at three thresholds, by as much as
    44/120 -> 51/120. None of it changes the verdict — CLASSIC, the tier the verdict turns on,
    reproduced byte-for-byte at 49/120 and 4/110 — but "identical" was the wrong word for it, and
    `record_diff` alone would have printed exactly that.

    This is the same lesson as F3-4 (whose 31 strata were compared by hand) arriving through a
    different door, and it generalises: how coarse a case's `record` is has nothing to do with how
    precise the claims built on it are.

    The split is the whole design. A raw whole-file comparison reports the run id, every AWS
    request id, every `evidence/<run_id>/…` path and every SDK version, which is noise by
    construction — so a path is called run-scoped when its leaf key is in `VOLATILE_KEYS` or when
    either day's run id appears anywhere in the rendered difference, and quantitative otherwise.
    Quantitative drift is a **note, not an error**: two days of a stochastic measurement are
    allowed to differ, and the point is that a reader is told rather than reassured.
    """
    def payload(raw: bytes) -> dict:
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
        return {k: v for k, v in d.items() if k != "record"} if isinstance(d, dict) else {}

    quant, vol = [], []
    for p in record_diff(payload(old), payload(new)):
        # EVERY segment is checked, not only the leaf. F10-3 files its AWS request ids under
        # `reconciliation.pairs[i].request_ids.tagged`, whose leaf is `tagged` — so a leaf-only
        # test reported ten freshly-minted uuids as quantitative drift, which is the same class of
        # noise the split exists to remove, one level up.
        segs = {s.split("[")[0] for s in p.split(":")[0].split(" ")[0].split(".")}
        if segs & set(VOLATILE_KEYS) or any(r and r in p for r in run_ids):
            vol.append(p)
        else:
            quant.append(p)
    return quant, vol


def run_id_of(raw: bytes) -> str:
    try:
        return str(json.loads(raw).get("run_id") or json.loads(raw).get("record", {}).get("run_id") or "")
    except Exception:  # noqa: BLE001
        return ""


META = ("environment.json", "analysis.json", "summary.json")


def fresh_records(run_id: str, day: str) -> int:
    """Evidence records written under `run_id` whose own timestamp is `day`.

    The count is over the record's `t_start_utc`, not the directory's mtime, for the same
    reason `run_id_date` refuses mtimes: this number is the whole warrant for the word
    "replication", so it has to come from the observation itself.
    """
    base = EVIDENCE / run_id
    if not base.is_dir():
        return 0
    n = 0
    for f in base.rglob("*.json"):
        if f.name in META:
            continue
        try:
            ts = json.loads(f.read_text()).get("t_start_utc")
        except Exception:  # noqa: BLE001
            continue
        if ts and str(ts)[:10] == day:
            n += 1
    return n


# Errors that are the service declining to LOOK at the request, as opposed to answering it.
# A call that ends in one of these carries no information about the thing under test.
TRANSIENT_ERRORS = (
    "ThrottlingException", "ThrottledException", "TooManyRequestsException",
    "ServiceUnavailableException", "ServiceQuotaExceededException", "InternalServerException",
    "InternalFailure", "RequestTimeout", "RequestTimeoutException", "ModelTimeoutException",
    "ModelNotReadyException", "SlowDown",
)


def transient_failures(run_id: str, day: str, case: str | None = None) -> list[tuple[str, str]]:
    """Fresh call records whose error is transient — `(evidence path, error code)` pairs.

    Why this guard exists: F8-5, 2026-08-15
    ---------------------------------------
    F8-5 sends four `CreateGuardrail` probes and *the error IS the data*: a topic definition at
    the tier limit should be accepted and one over it rejected. On day 2 the STANDARD-1000 probe
    came back `ThrottlingException`. The producer scored that as `observed: "rejected"`, which
    made `matches_expected` false, which set `record.evidence.at_limit_accepted: false` — the
    one field the FALSE verdict rests on. So the refutation was carried by a call in which the
    service never inspected the definition at all.

    Everything upstream said the replication was clean. The verdict agreed (FALSE -> FALSE),
    `record_diff` reported the decision record IDENTICAL, and no sealed field moved — because
    `record.evidence` is three coarse booleans that cannot distinguish "the service rejected
    this content" from "the service rejected this request". Reading the day-1 archive is what
    exposed it, and it cut both ways: day 1 was throttled too, on `standard-1001`, whose
    expectation was "rejected" anyway, so day 1's *confirming* half was equally unwarranted and
    the published verdict had recorded `matches_expected: true` for it.

    That is a class of defect, not one case's bad luck: any producer that classifies an
    exception without excluding transient ones can convert a throttle into evidence, and no
    verdict-level or record-level comparison can see it. So the check is deliberately placed
    here — case-agnostic, over the raw call records the run actually wrote, keyed on nothing but
    the error code — and it is a CAVEAT rather than a failure: a throttled probe does not
    contradict day 1, it just is not a second observation of that probe.
    """
    base = EVIDENCE / run_id
    if not base.is_dir():
        return []
    out = []
    for f in sorted(base.rglob("*.json")):
        if f.name in META or not _scoped(f.relative_to(base).parts, case):
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if str(d.get("t_start_utc") or "")[:10] != day:
            continue
        # `lib.evidence` writes error_code and error_class; error_metadata.Error.Code is
        # botocore's own copy. All three are read so that a record written by a producer that
        # fills only one of them still counts — a guard that misses the field reports clean.
        meta_code = ((d.get("error_metadata") or {}).get("Error") or {}).get("Code")
        for code in (d.get("error_code"), d.get("error_class"), meta_code):
            if isinstance(code, str) and code in TRANSIENT_ERRORS:
                # repo-relative where possible (that is the form the operator can cite); the
                # absolute path when EVIDENCE has been pointed outside the tree, rather than
                # raising ValueError and losing a real finding to a formatting detail.
                rel = str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f)
                out.append((rel, code))
                break
    return out


def zero_call_capture(run_id: str, day: str) -> tuple[int, int]:
    """`(summaries captured today, calls those summaries report)` under `run_id`.

    The weaker proof, for the cases that make no API call by design — F1's surface sweep
    reads four botocore service models off disk, so it has no call record to date and its
    only timestamp is `summary.json`'s `captured_utc`.

    It is weak because `EvidenceStore` writes `environment.json` and `summary.json` on
    *every* run, whether or not any trial executed. A checkpointed case that resumed all of
    its day-1 trials would produce a summary stamped today and observe nothing — which is
    why accepting this proof needs `--no-call-case` **and** a reported call count of zero.
    A summary claiming calls but holding no dated record is an anomaly, not a replication.
    """
    base = EVIDENCE / run_id
    if not base.is_dir():
        return 0, 0
    caps = calls = 0
    for f in base.rglob("summary.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        if str(d.get("captured_utc", ""))[:10] == day:
            caps += 1
            calls += int(d.get("n_calls") or 0)
    return caps, calls


def move_checkpoints(cases: list[str], day1: str, *, dry: bool) -> list[str]:
    """Move day-1 checkpoints out of the way so the producer cannot resume them."""
    moved = []
    dest = CP_ROOT / f"day1_{day1}"
    for case in cases:
        for p in sorted(CP_ROOT.glob(f"{case}__*.json")):
            moved.append(p.name)
            if not dry:
                dest.mkdir(parents=True, exist_ok=True)
                target = dest / p.name
                if target.exists():
                    raise SystemExit(
                        f"FATAL: {target.relative_to(ROOT)} already exists. A previous day-2 "
                        f"already archived this checkpoint; refusing to overwrite it, because "
                        f"that would discard trials already paid for.")
                shutil.move(str(p), str(target))
    return moved


def day1_label(case: str, old: bytes, day1_dates: dict[str, str] | None = None) -> str:
    """The date day 1 is filed and printed under, from the ONE place it was resolved.

    `main()` resolves each case's day-1 date up front, and for a run id `RUN_ID_RE` cannot parse
    it resolves it from the observation records (`evidence_date`). Three later sites re-derived
    the label from the run id instead of reading that result, so F8-5's fallback worked and the
    output still disagreed with itself: the comparison row printed `unknown FALSE -> 2026-08-15
    FALSE` and the archive was written as `F8-5__day1_unknown.json`, i.e. the driver had the
    date and threw it away twice. The run-id derivation is kept only as the fallback for a
    caller that has no resolved map (`drop_snapshot`'s unit arms).
    """
    return (day1_dates or {}).get(case) or run_id_date(run_id_of(old)) or "unknown"


def drop_snapshot(pre_dir: Path, before: dict[str, bytes], changed: list[str],
                  run_id: str, day1_dates: dict[str, str] | None = None) -> list[str]:
    """Delete the pre-run snapshot, but only once day 1 is recoverable WITHOUT it.

    The snapshot exists for the run that fails: an abort between the producer's write and
    the archive step would otherwise leave a rewritten verdict file with no day-1 copy. On a
    clean run every day-1 file that was overwritten is in `results/phase1/archive/`, which is
    distributable and published, so the staging copy is redundant bytes in a directory with a
    written ceiling — `runner/.staging/` was removed once already after a 90,562 KB scratch
    breach of an 80,000 KB limit (DEV-P4-36), and two runs of this driver had already put
    10,072 KB back. `feedback_fix_producer_not_janitor`: the producer cleans up after itself
    rather than leaving a prune for whoever notices the disk.

    "Recoverable" is re-derived from disk, not assumed from the fact that the archive loop
    ran: for every changed case the archive file must exist AND its bytes must equal the
    day-1 content being discarded. Any case that fails that keeps the whole snapshot and is
    returned, because a partial delete is the worst of both.

    Returns the cases blocking deletion — empty means the snapshot was removed.
    """
    blocked = []
    for name in sorted(changed):
        old = before.get(name)
        if old is None:                      # NEW case: no day-1 content exists to lose
            continue
        d1 = day1_label(name[:-len(".json")], old, day1_dates)
        dest = ARCHIVE / f"{name[:-len('.json')]}__day1_{d1}.json"
        if not dest.is_file() or dest.read_bytes() != old:
            blocked.append(name[:-len(".json")])
    if blocked:
        return blocked
    # Belt and braces on the path itself: this function deletes a tree, and the only tree it
    # may ever delete is the one this run created under the local-only staging root.
    expected = ROOT / "runner" / ".staging" / f"day2_pre_{run_id}"
    if pre_dir.resolve() != expected.resolve():
        raise SystemExit(f"FATAL: refusing to delete {pre_dir}; expected {expected}")
    if pre_dir.is_dir():
        shutil.rmtree(pre_dir)
        print(f"  pre-run snapshot removed ({pre_dir.relative_to(ROOT)}) — day 1 is in "
              f"{ARCHIVE.relative_to(ROOT)}, verified byte-for-byte")
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="day2_replicate", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True,
                    help="comma-separated case ids this producer is being replicated FOR. "
                         "Used for the same-day guard, the checkpoint sweep and the "
                         "freshness floor — not to filter what the producer writes")
    ap.add_argument("--run-id", default=None, help="default: minted from UTC now")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan, the guards and what would move; run nothing")
    ap.add_argument("--allow-no-checkpoints", action="store_true",
                    help="proceed when the named cases have no day-1 checkpoints (true of "
                         "cases whose instrument is a single observation, e.g. F1-14)")
    ap.add_argument("--no-call-case", action="store_true",
                    help="this producer makes NO API call by design, so accept a summary "
                         "captured today as the observation proof instead of a dated call "
                         "record. Only valid when the run reports zero calls")
    ap.add_argument("producer", nargs=argparse.REMAINDER,
                    help="the producer command, after --. `--run-id <new>` is appended")
    args = ap.parse_args(argv)

    cmd = [a for a in args.producer if a != "--"]
    if not cmd:
        ap.error("no producer command given (put it after --)")
    cases = [c.strip() for c in args.cases.split(",") if c.strip()]
    if not cases:
        ap.error("--cases is empty")

    today = utc_today()
    before = snapshot_phase1()

    # --- guard 1: every named case must have a day-1 verdict on an EARLIER UTC day.
    day1_dates: dict[str, str] = {}
    day1_sources: dict[str, str] = {}   # how each day-1 date was established, for the record
    for case in cases:
        raw = before.get(f"{case}.json")
        if raw is None:
            print(f"FATAL: results/phase1/{case}.json does not exist — there is no day 1 "
                  f"to replicate", file=sys.stderr)
            return 2
        rid = run_id_of(raw)
        d = run_id_date(rid)
        if d is not None:
            day1_sources[case] = f"run id {rid}"
        else:
            d, why = evidence_date(case, rid)
            if d is None:
                print(f"FATAL: {case}'s run id {rid!r} is not a dated run id, and its own "
                      f"evidence cannot supply the day either ({why}). A replication cannot "
                      f"be asserted against an undated day 1.", file=sys.stderr)
                return 2
            day1_sources[case] = f"evidence under run id {rid}: {why}"
            print(f"  NOTE {case}: run id {rid!r} is not a dated run id; day 1 taken as {d} "
                  f"from {why}")
        day1_dates[case] = d
        if d == today:
            print(f"FATAL: {case}'s day 1 is {d} and UTC today is also {today}. A same-UTC-day "
                  f"repeat is not a replication (see f5_redteam/07a_run_day2.sh)",
                  file=sys.stderr)
            return 2

    run_id = args.run_id or mint_run_id()
    if run_id_date(run_id) in day1_dates.values():
        print(f"FATAL: run id {run_id} names a day that is already a day-1 date "
              f"({sorted(set(day1_dates.values()))})", file=sys.stderr)
        return 2
    if (EVIDENCE / run_id).exists():
        print(f"FATAL: evidence/{run_id} already exists; pick another run id rather than "
              f"mixing two runs' records", file=sys.stderr)
        return 2

    print(f"day-2 replication — UTC today {today}, new run_id {run_id}")
    for case in cases:
        print(f"  {case:8} day 1 {day1_dates[case]}   verdict "
              f"{verdict_of(before[f'{case}.json'])}")

    cps = move_checkpoints(cases, "-".join(sorted({d for d in day1_dates.values()})[:1]),
                           dry=True)
    print(f"  day-1 checkpoints found: {len(cps)}"
          + (f" -> {cps[:4]}{'…' if len(cps) > 4 else ''}" if cps else ""))
    if not cps and not args.allow_no_checkpoints:
        print("FATAL: none of the named cases has a day-1 checkpoint. Either the case is not "
              "checkpointed — pass --allow-no-checkpoints and say so — or the case ids are "
              "wrong, in which case the producer would resume day-1 trials and this would "
              "report a replication that never ran.", file=sys.stderr)
        return 2

    full = [*cmd, "--run-id", run_id]
    print(f"  command: {' '.join(full)}")
    if args.dry_run:
        print("  (dry run — nothing moved, nothing executed)")
        return 0

    day1_tag = sorted({d for d in day1_dates.values()})[0]

    # Snapshot BEFORE anything is moved or run. Every later archive copy is written from
    # this dict, so an abort at any point below still leaves day 1 recoverable from
    # `pre_dir` without depending on a copy existing somewhere else.
    pre_dir = ROOT / "runner" / ".staging" / f"day2_pre_{run_id}"
    pre_dir.mkdir(parents=True, exist_ok=True)
    for name, raw in before.items():
        (pre_dir / name).write_bytes(raw)
    print(f"  pre-run snapshot: {len(before)} verdict file(s) -> "
          f"{pre_dir.relative_to(ROOT)} (local-only)")

    moved = move_checkpoints(cases, day1_tag, dry=False)
    if moved:
        print(f"  moved {len(moved)} checkpoint(s) to "
              f"{(CP_ROOT / f'day1_{day1_tag}').relative_to(ROOT)}")

    proc = subprocess.run(full, cwd=ROOT)  # noqa: S603 - the command is an operator argument
    prc = proc.returncode
    print(f"  producer rc: {prc}")

    # --- guard 2: did it actually observe anything today?
    n_fresh = fresh_records(run_id, today)
    caps, n_calls = zero_call_capture(run_id, today)
    proof = f"{n_fresh} call record(s) dated {today}"
    if n_fresh == 0 and args.no_call_case and caps > 0 and n_calls == 0:
        proof = (f"{caps} summary/summaries captured {today}, reporting 0 calls "
                 f"(--no-call-case: this producer sends none)")
    print(f"  observation proof: {proof}")

    after = snapshot_phase1()
    changed = [k for k, v in after.items() if before.get(k) != v]
    print(f"  verdict files changed: {len(changed)} {sorted(changed)}")

    # Archive first, adjudicate second — a post-run guard must not be able to leave a
    # rewritten verdict file with no day-1 copy in the tree.
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    archived = []
    for name in sorted(changed):
        old = before.get(name)
        if old is None:
            continue
        d1 = day1_label(name[:-len(".json")], old, day1_dates)
        dest = ARCHIVE / f"{name[:-len('.json')]}__day1_{d1}.json"
        if dest.exists():
            if dest.read_bytes() != old:
                print(f"FATAL: {dest.relative_to(ROOT)} exists with different content; "
                      f"refusing to overwrite an earlier day's archive", file=sys.stderr)
                return 2
        else:
            dest.write_bytes(old)
            archived.append(dest.name)
    print(f"  archived {len(archived)} day-1 verdict file(s) to "
          f"{ARCHIVE.relative_to(ROOT)}")

    if prc != 0:
        print(f"NOT REPLICATED — the producer exited {prc}; nothing is claimed", file=sys.stderr)
        return 2
    if n_fresh == 0 and not (args.no_call_case and caps > 0 and n_calls == 0):
        print("NOT REPLICATED — the producer exited 0 but wrote no evidence record dated "
              "today. That is the checkpoint-resume failure mode this driver exists to "
              "catch: a re-derived verdict is not a second observation."
              + (f" ({caps} summary/summaries were captured today but report {n_calls} "
                 f"call(s), so --no-call-case does not apply)" if caps else ""),
              file=sys.stderr)
        return 2
    if not changed:
        print("NOT REPLICATED — no verdict file changed, so nothing was re-emitted",
              file=sys.stderr)
        return 2

    # --- archive day 1 and compare, per changed case.
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    rows = []
    disagreed = []
    not_same_test = []
    caveats = []
    for name in sorted(changed):
        case = name[:-len(".json")]
        old, new = before.get(name), after[name]
        if old is None:
            rows.append({"case_id": case, "status": "NEW", "day1": None,
                         "day2_verdict": verdict_of(new), "day2_run_id": run_id_of(new)})
            print(f"  [NEW]      {case}: no day-1 file; {verdict_of(new)}")
            continue
        d1 = day1_label(case, old, day1_dates)
        dest = ARCHIVE / f"{case}__day1_{d1}.json"
        if dest.exists():
            if dest.read_bytes() != old:
                print(f"FATAL: {dest.relative_to(ROOT)} exists with different content; "
                      f"refusing to overwrite an earlier day's archive", file=sys.stderr)
                return 2
        else:
            dest.write_bytes(old)
        v1, v2 = verdict_of(old), verdict_of(new)
        agree = v1 == v2

        # Beyond the verdict: what the sealed oracle recorded. `record_diff` is what makes an
        # agreeing verdict over drifted counts visible instead of silently AGREE.
        r1, r2 = record_of(old), record_of(new)
        diffs = record_diff(r1, r2)
        broke_seal = sorted({p.split(".")[0].split("[")[0].split(" ")[0]
                             for p in diffs} & set(SEALED_FIELDS))

        # Beyond `record`: the per-arm counts and intervals the document actually cites, which for
        # a coarse-record case (F8-4) are the only place drift is visible at all.
        pquant, pvol = payload_diff(old, new, (run_id_of(old), run_id_of(new)))

        # Did every call this case made today actually reach the thing under test?
        trans = transient_failures(run_id, today, case)
        if trans:
            caveats.append(case)

        rows.append({"case_id": case, "status": "AGREE" if agree else "DISAGREE",
                     "day1_date": d1, "day1_run_id": run_id_of(old), "day1_verdict": v1,
                     "day2_date": today, "day2_run_id": run_id_of(new), "day2_verdict": v2,
                     "day1_archived_to": str(dest.relative_to(ROOT)),
                     "record_identical": not diffs,
                     "record_fields_differing": diffs[:40],
                     "record_fields_differing_total": len(diffs),
                     "sealed_fields_differing": broke_seal,
                     "payload_fields_differing": pquant[:40],
                     "payload_fields_differing_total": len(pquant),
                     "payload_run_scoped_differences": len(pvol),
                     "clean_observation": not trans,
                     "transient_error_calls": [{"evidence": p, "error_code": c} for p, c in trans]})
        print(f"  [{'AGREE' if agree else 'DISAGREE'}]{'  ' if agree else ''} {case}: "
              f"{d1} {v1} -> {today} {v2}")
        if diffs:
            print(f"     decision record differs at {len(diffs)} path(s): {diffs[:4]}"
                  f"{' …' if len(diffs) > 4 else ''}")
        elif pquant:
            print("     decision record identical, BUT the record is coarser than the file: "
                  f"{len(pquant)} figure(s) outside it moved")
        else:
            print("     decision record IDENTICAL — every count, interval and per-stratum "
                  "figure reproduced")
        if pquant:
            print(f"     payload drift at {len(pquant)} path(s) outside `record` "
                  f"({len(pvol)} further difference(s) are run-scoped and ignored):")
            for p in pquant[:8]:
                print(f"       {p}")
            if len(pquant) > 8:
                print(f"       … and {len(pquant) - 8} more (all in "
                      f"{ROOT / 'results' / f'day2_replication_{today}.json'})")
        if trans:
            print(f"     CAVEAT — {len(trans)} of today's call(s) failed transiently "
                  f"({sorted({c for _, c in trans})}); those probes did not reach the service's "
                  f"decision, so this is not a clean second observation of them:", file=sys.stderr)
            for p, c in trans[:6]:
                print(f"       {c}  {p}", file=sys.stderr)
        if broke_seal:
            print(f"     SEALED FIELDS MOVED: {broke_seal} — the two days did not evaluate the "
                  f"same sealed test", file=sys.stderr)
        if not agree:
            disagreed.append(case)
        if broke_seal:
            not_same_test.append(case)

    out = ROOT / "results" / f"day2_replication_{today}.json"
    prior = json.loads(out.read_text()) if out.is_file() else {"runs": []}
    prior["runs"].append({"run_id": run_id, "utc_date": today, "cases_requested": cases,
                          "producer": full, "fresh_records": n_fresh,
                          "observation_proof": proof,
                          "day1_date_source": day1_sources,
                          "summaries_captured_today": caps, "calls_reported": n_calls,
                          "checkpoints_archived": moved,
                          "day1_files_archived": archived,
                          "cases_with_transient_failures": caveats, "results": rows})
    out.write_text(_redact.mask_text(
        json.dumps(prior, indent=2, sort_keys=True, ensure_ascii=False) + "\n"),
        encoding="utf-8")
    print(f"  wrote {out.relative_to(ROOT)}")

    if disagreed:
        print(f"NOT REPLICATED — {len(disagreed)} case(s) disagree with day 1: {disagreed}. "
              f"Per the pre-registration this is a FINDING, not a fix-up: do not amend, "
              f"record it and take it back to the user.", file=sys.stderr)
        return 1
    if not_same_test:
        print(f"NOT REPLICATED — {not_same_test} agree on the verdict, but a sealed field "
              f"({SEALED_FIELDS}) moved between the two days. An agreeing verdict over a "
              f"different test is not a replication; find out why the seal-derived value "
              f"changed before claiming either day.", file=sys.stderr)
        return 1

    unarchived = drop_snapshot(pre_dir, before, changed, run_id, day1_dates)
    if unarchived:
        print(f"  pre-run snapshot KEPT at {pre_dir.relative_to(ROOT)} — day 1 is not "
              f"independently recoverable for {unarchived}", file=sys.stderr)

    if caveats:
        # rc stays 0: a throttle is not a contradiction of day 1, and the operator's next step
        # is to re-run the affected case, not to investigate a disagreement. But the word
        # REPLICATED does not appear unqualified over an observation with a hole in it.
        print(f"REPLICATED WITH CAVEAT — {len(rows)} case(s) agree across {day1_tag} and "
              f"{today}, but {caveats} had transiently-failed call(s) today. Those probes are "
              f"not replicated; re-run the case on a later UTC day before citing them.")
        return 0
    print(f"REPLICATED — {len(rows)} case(s) agree across {day1_tag} and {today}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
