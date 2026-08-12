#!/usr/bin/env python3
"""One-off: reconstruct F6-6/7/8's sending window from the crashed run's own evidence records.

    python3 f6_latency/recover_cw_window.py --check     # print what it would write
    python3 f6_latency/recover_cw_window.py             # write results/checkpoints/F6-6__cw_windows.json

WHY THIS EXISTS
---------------
The first full run of `f6_latency/03_composition.py` collected all 1,600 turns, read its
CloudWatch window successfully, and then crashed in the analysis on an empty-sample quantile
(`hop6_ms` is absent from every benign Converse trace; fixed by `_p50_or_none`). The turns are
safe in the checkpoints, but the SENDING WINDOW — which is what hops 4 and 5 are read over — was
wall-clock state in that process and was never persisted. That gap is now closed for every future
run by `WINDOWS_PATH`, and this script back-fills the one window that predates the fix.

Re-running the arm instead would re-send 1,600 turns (~$0.60 and ~an hour) to re-derive a number
already recorded. Publishing NOT_MEASURED instead would discard 1,600 paid-for turns over a
missing timestamp.

WHY THE RECOVERED WINDOW IS EVIDENCE AND NOT A GUESS
----------------------------------------------------
`lib/evidence.capture` archived the two `GetMetricStatistics` requests that run issued, with the
`StartTime`/`EndTime` it computed. `_cw_p50` pads by exactly 60 s on each side
(`start = t0 - 60s`, `end = t1 + 60s`), so the window is recovered by inverting that pad — read
from the archived request parameters, never typed in. The script asserts that every archived
request agrees on the same span; a disagreement means more than one window is in that directory
and the inversion would be ambiguous, so it refuses.

The recovered entry is marked `recorded_by: recover_cw_window.py (RECONSTRUCTED)` in the ledger's
provenance list, and `03_composition.py` publishes that provenance in every one of the three
cases' payloads. A reader can therefore see, in the result itself, that this window was
reconstructed from request records rather than timed live. Recorded as a deviation in
DEVIATIONS.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import testbed as T                                                   # noqa: E402

CASE_DIR = "f6_latency/F6-6_7_8"
PAD_S = 60.0          # the pad `_cw_p50` applies on each side; inverted here
METRICS = ("Latency", "GuardrailLatency")
WINDOWS_PATH = ROOT / "results" / "checkpoints" / "F6-6__cw_windows.json"


def _spans(evidence_dir: Path) -> dict[tuple[str, str], list[str]]:
    """Every distinct (StartTime, EndTime) pair in the archived GetMetricStatistics requests."""
    spans: dict[tuple[str, str], list[str]] = {}
    for path in sorted(evidence_dir.glob("*_get_metric_statistics_*.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        params = body.get("params") or {}
        if params.get("MetricName") not in METRICS:
            continue
        start, end = params.get("StartTime"), params.get("EndTime")
        if not (start and end):
            continue
        spans.setdefault((start, end), []).append(path.name)
    return spans


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="print the recovered window and write nothing")
    args = ap.parse_args()

    state = T.State.load()
    evidence_dir = ROOT / "evidence" / state.run_id / CASE_DIR
    if not evidence_dir.is_dir():
        print(f"FAIL: {evidence_dir} does not exist, so there is nothing to recover from")
        return 2

    spans = _spans(evidence_dir)
    if not spans:
        print(f"FAIL: no archived GetMetricStatistics request in {evidence_dir} carries a "
              f"StartTime/EndTime for {METRICS}")
        return 2
    if len(spans) > 1:
        print(f"FAIL: {len(spans)} DIFFERENT windows are archived in {evidence_dir}:")
        for (s, e), files in sorted(spans.items()):
            print(f"  {s} .. {e}   ({len(files)} request(s), e.g. {files[0]})")
        print("Inverting the pad would be ambiguous. Resolve by hand rather than guessing which "
              "window the 1,600 turns were sent in.")
        return 2

    (start_iso, end_iso), files = next(iter(spans.items()))
    # Invert the pad `_cw_p50` applied. The pad is a constant in that module, and the two are
    # deliberately not shared: this script must fail loudly if it ever stops matching, and it
    # states the arithmetic it performed in the provenance below.
    t0 = datetime.fromisoformat(start_iso).timestamp() + PAD_S
    t1 = datetime.fromisoformat(end_iso).timestamp() - PAD_S
    if t1 <= t0:
        print(f"FAIL: the archived span {start_iso}..{end_iso} is shorter than the 2x{PAD_S:.0f}s "
              f"pad, so it cannot be the window of a 1,600-turn run")
        return 2

    # The RECOVERED window, not the archived padded span. Reporting the padded span under these
    # keys would put a 63.6-minute label on a 61.6-minute measurement — the same value under two
    # names, which is how a number stops meaning what its label says.
    entry = {
        "t0_iso": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
        "t1_iso": datetime.fromtimestamp(t1, tz=timezone.utc).isoformat(),
        "recorded_by": "recover_cw_window.py (RECONSTRUCTED)",
        "reconstructed_from": {
            "evidence_dir": CASE_DIR,
            "requests_read": sorted(files),
            "archived_StartTime": start_iso,
            "archived_EndTime": end_iso,
            "arithmetic": (f"t0 = StartTime + {PAD_S:.0f}s and t1 = EndTime - {PAD_S:.0f}s, "
                           f"inverting the pad _cw_p50 applies to each side"),
            "why": ("the run that sent these 1,600 turns crashed in its analysis before the "
                    "window was persisted; the window is recovered from that run's own archived "
                    "CloudWatch requests rather than re-sending the arm"),
        },
    }
    body = {"windows": [[t0, t1]], "provenance": [entry]}

    print(f"recovered window: {entry['t0_iso']} .. {entry['t1_iso']}  "
          f"({(t1 - t0) / 60:.1f} minutes of sending)")
    print(f"  from {len(files)} archived request(s), e.g. {sorted(files)[0]}")
    if args.check:
        print(f"  --check: nothing written. Target would be {WINDOWS_PATH}")
        return 0
    if WINDOWS_PATH.is_file():
        print(f"FAIL: {WINDOWS_PATH} already exists. Refusing to overwrite a window ledger — a "
              f"live run may have appended to it since. Inspect it, then move it aside "
              f"deliberately if this reconstruction really should replace it.")
        return 2
    WINDOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WINDOWS_PATH.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  wrote {WINDOWS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
