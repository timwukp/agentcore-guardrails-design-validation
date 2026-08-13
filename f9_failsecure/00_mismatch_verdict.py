#!/usr/bin/env python3
"""F9-2: did the mismatch metrics increment when a policy could not evaluate?

Analysis only, **$0, offline**. This script makes no AWS call. It reads the RAW
`get_metric_statistics` records F5-4a archived and emits `results/phase1/F9-2.json` through
`lib/phase1.emit`, so the case lands in the same index as every other Phase 1 case.

The sealed oracle is one sentence:

    TRUE if the metrics increment when a policy cannot evaluate; FALSE if silent

and the registered instrument note is "paired with F5-4a". F5-4a shipped four deliberately
broken policies and recorded 200 `mcp:tools/call` requests against them across two UTC days;
this file turns those recorded CloudWatch reads into F9-2's verdict.

WHY IT READS THE EVIDENCE TREE AND NOT F5-4a's RESULT FILE
---------------------------------------------------------
`results/phase1/F5-4a.json` already carries a `mismatch_metrics` block with the sums. Reading
it would be this record vouching for a number computed by the artifact it is derived from
(`feedback_prose_is_not_verified`), and it would inherit that block's window labelling
wholesale. So every figure here is recomputed from the per-call records:

  * `params.MetricName`, `params.StartTime`, `params.EndTime`, `params.Dimensions` — what was
    asked for, as sent;
  * `response.Datapoints[].Timestamp/Sum/SampleCount` — what CloudWatch answered.

The two files agree, which is worth stating precisely because agreement was not assumed.

EPISODES ARE DERIVED FROM DATAPOINT TIMESTAMPS, NOT FROM WINDOW LABELS
---------------------------------------------------------------------
F5-4a ran its arms twice. Nothing in a record says "this is the before window" — a reader
who sorts by `StartTime` and calls the first one "before" is labelling, not measuring, and
would silently mislabel a re-read of an old window as a new baseline.

So an EPISODE is a cluster of datapoints that actually carry a positive `Sum`, keyed by the
minute CloudWatch stamped them with. A read counts as that episode's BASELINE only if its
window **ends at or before** the episode's first positive datapoint and it returned no
positive datapoint for that metric. Both halves are derived from the same field, so a
mislabelled window cannot promote itself.

WHAT "SILENT" WOULD HAVE LOOKED LIKE, AND WHY NO-DATAPOINTS IS NOT A REFUSAL
---------------------------------------------------------------------------
If the mismatch metrics had stayed at zero while the broken policies were live, that is the
oracle's FALSE — the document's observability story would be missing its detector — and this
script publishes FALSE rather than refusing. A refusal is reserved for the cases where the
*question* was not put to the service:

  * no `mcp:tools/call` record — nothing was asked of the broken policy, so nothing could
    have been counted;
  * no `create_policy` record — no broken policy existed to fail to evaluate;
  * a metric with no read at all — its silence is our omission, not the service's;
  * a BASELINE that is already positive — then an increment cannot be attributed to the
    episode, whichever way the numbers fall.

That is the same asymmetry `f7_observability/03_metrics_existence.py` settled on: the
exercise basis gates the ABSENT direction only, and truncation or omission can never
manufacture a datapoint that was returned.

WHAT THIS VERDICT DOES NOT SAY
------------------------------
The 20 mismatches per episode are a **twin disagreement**: F5-4a's ACTIVE twin denied all 20
requests while the identical statement in LOG_ONLY allowed all 20
(`results/phase1/F5-4a_logonly_read.json`: `active_twin_denied_all`, `logonly_allowed_all`,
`same_statement`). So what is measured is that the mismatch family fires when one twin cannot
evaluate. It is NOT measured that a lone unevaluable policy with no disagreeing twin
increments anything, and the record says so in `what_this_does_not_prove` rather than leaving
a reader to assume the stronger reading.

Separately and never folded into the verdict: `LogOnlyEvalIncomplete` — the metric §6.4's
runbook makes the detector for a partial LOG_ONLY calibration — returned **0** datapoints in
every window read, and F7-1 recorded `name_in_namespace_inventory: false`. It is reported
here as a sub-result because it is a different claim (`C-s6-4-trow-006`) with a different
oracle, and because F7-1 excluded it as NOT_EXERCISED on the grounds that reproducing the
condition would need a deliberately broken policy — which F5-4a then shipped.

Usage
-----
    python3 f9_failsecure/00_mismatch_verdict.py --dry-run
    python3 f9_failsecure/00_mismatch_verdict.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import oracle as O                                                   # noqa: E402
import phase1 as P                                                   # noqa: E402

CASE = "F9-2"
FAMILY = "f9"

# F5-4a's evidence lives under the f5 family; F9-2 is the case that reads it. Both are named
# so a reader of either tree can find the other.
SOURCE_RUN = "r20260810T130945Z"
SOURCE_CASE_DIR = ("f5", "F5-4a")
SUPPLEMENTARY_DIR = ("f5", "F5-4a-logonly-read")

# The oracle says "MismatchErrors/PolicyMismatch". Those two are the conjunction; a third
# metric F5-4a happened to read corroborates but may not join it, because widening a sealed
# oracle's conjunction after seeing the data is how a result gets chosen instead of measured.
REQUIRED = ("MismatchErrors", "PolicyMismatch")
CORROBORATING = ("TotalMismatchedPolicies",)

# Read and reported, never scored. `LogOnlyEvalIncomplete` belongs to C-s6-4-trow-006 and
# F7-1, not to this oracle.
SUB_RESULT = ("LogOnlyEvalIncomplete",)

# Every metric name these evidence dirs contain must appear above. An unclassified name is
# fatal rather than ignored: F5-4a growing a fifth metric read must be a deliberate decision
# here, not a silent omission from a conjunction that then still says TRUE.
CONTEXT = ("LogOnlyMatches", "LogOnlyDecisionFlips")


class Refusal(RuntimeError):
    """A precondition that makes the verdict unsafe to compute. Never a verdict."""


def _utc(value: Any) -> datetime:
    """Parse a recorded timestamp to an aware UTC datetime, or refuse.

    Not cosmetic, and not optional. The request windows were sent as `+00:00` while
    CloudWatch stamped the datapoints it returned `+07:00` — the same instant written two
    ways. The first version of this file compared those ISO strings directly, and
    `'2026-08-11T22:48:36+00:00' <= '2026-08-12T05:47:00+07:00'` is lexicographically true
    while the instants are the other way round, so a read whose window closed 96 seconds
    AFTER the firing was offered as that firing's baseline. Twelve of them were, and the
    already-positive guard is what caught it. Comparisons are between instants from here on.
    """
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise Refusal(f"cannot parse timestamp {value!r} recorded in the evidence: {exc}")
    if dt.tzinfo is None:
        raise Refusal(
            f"timestamp {value!r} carries no offset. A naive timestamp cannot be ordered "
            f"against the offsets CloudWatch returns, and assuming UTC here is the "
            f"assumption that produced the bug this function exists to stop")
    return dt.astimezone(timezone.utc)


def _dirs(root: Path = ROOT) -> tuple[Path, Path]:
    ev = root / "evidence" / SOURCE_RUN
    return ev.joinpath(*SOURCE_CASE_DIR), ev.joinpath(*SUPPLEMENTARY_DIR)


def load_reads(root: Path = ROOT) -> list[dict[str, Any]]:
    """Every archived `get_metric_statistics` call, as sent and as answered."""
    out: list[dict[str, Any]] = []
    for d in _dirs(root):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*_get_metric_statistics_ok.json")):
            body = json.loads(f.read_text(encoding="utf-8"))
            params = body.get("params") or {}
            resp = body.get("response") or {}
            out.append({
                "file": str(f.relative_to(root)),
                "metric": params.get("MetricName"),
                "start": str(params.get("StartTime")),
                "end": str(params.get("EndTime")),
                "start_utc": _utc(params.get("StartTime")),
                "end_utc": _utc(params.get("EndTime")),
                "dimensions": [(x.get("Name"), x.get("Value"))
                               for x in (params.get("Dimensions") or [])],
                "datapoints": [{"t": str(p.get("Timestamp")),
                                "t_utc": _utc(p.get("Timestamp")),
                                "sum": float(p.get("Sum") or 0.0),
                                "samples": float(p.get("SampleCount") or 0.0)}
                               for p in (resp.get("Datapoints") or [])],
            })
    if not out:
        raise Refusal(
            f"no get_metric_statistics records under {[str(d) for d in _dirs(root)]}. This "
            f"script analyses F5-4a's ARCHIVED reads and collects none of its own")
    unknown = sorted({r["metric"] for r in out}
                     - set(REQUIRED) - set(CORROBORATING) - set(SUB_RESULT) - set(CONTEXT))
    if unknown:
        raise Refusal(
            f"metric(s) {unknown} were read by F5-4a and this file classifies none of them. "
            f"A name it has never seen may not be dropped from the conjunction by default: "
            f"add it to REQUIRED, CORROBORATING, SUB_RESULT or CONTEXT with the reason, and "
            f"add an arm to tests/test_mismatch_verdict.py")
    return out


def basis(root: Path = ROOT) -> dict[str, int]:
    """What F5-4a actually did, counted on disk rather than read out of its summary."""
    d, _ = _dirs(root)
    if not d.is_dir():
        raise Refusal(f"{d} does not exist, so the exercise basis cannot be established")
    counts = {
        "mcp_tools_call": len(list(d.glob("*_mcp-tools-call_ok.json"))),
        "create_policy": len(list(d.glob("*_create_policy_ok.json"))),
        "delete_policy": len(list(d.glob("*_delete_policy_ok.json"))),
    }
    if counts["mcp_tools_call"] <= 0:
        raise Refusal(
            "0 `mcp:tools/call` records: nothing was asked of the broken policies, so a zero "
            "mismatch count would measure our test plan and not the service")
    if counts["create_policy"] <= 0:
        raise Refusal(
            "0 `create_policy` records: no policy that cannot evaluate was ever shipped, "
            "which is the premise the oracle's 'when a policy cannot evaluate' rests on")
    return counts


def episodes_for(metric: str, reads: list[dict[str, Any]], *,
                 required: bool = False) -> list[dict[str, Any]]:
    """Positive-datapoint clusters for one metric, each with the baseline that precedes it.

    Keyed by the datapoint timestamp CloudWatch stamped, so two reads of the same firing
    collapse into one episode and two separate firings never do.

    `required` distinguishes the two metrics the oracle names from the ones read for context:
    for a named metric, no read at all is a refusal, because its silence would be our
    omission rather than the service's. For a context metric it is simply nothing to report.
    """
    mine = [r for r in reads if r["metric"] == metric]
    if not mine:
        if required:
            raise Refusal(
                f"{metric} is named by the sealed oracle and F5-4a's evidence holds no read "
                f"of it. Its silence here would be our omission, not the service's")
        return []

    positive: dict[datetime, dict[str, Any]] = {}
    for r in mine:
        for dp in r["datapoints"]:
            if dp["sum"] > 0:
                slot = positive.setdefault(dp["t_utc"],
                                           {"t": dp["t"],
                                            "t_utc": dp["t_utc"].isoformat(),
                                            "sum": dp["sum"], "samples": dp["samples"],
                                            "seen_in_reads": 0})
                slot["seen_in_reads"] += 1
                slot["sum"] = max(slot["sum"], dp["sum"])
                slot["samples"] = max(slot["samples"], dp["samples"])

    out = []
    firings = sorted(positive)
    for i, t in enumerate(firings):
        # An episode's baseline is the QUIET INTERVAL immediately before it: a read whose
        # window opens after the previous firing and closes at or before this one. Both
        # bounds come from recorded fields, so a window label cannot make itself a baseline.
        #
        # The interval matters as much as the direction. Written as "any window that closed
        # before this firing", every day-1 read is a candidate baseline for day 2 — and since
        # day 1 fired, those reads are positive, so the contamination guard below rejected a
        # second episode that was perfectly clean on its own interval. An earlier firing is
        # not contamination of a later one; a firing inside the later one's baseline is.
        prev = firings[i - 1] if i else None
        window = [r for r in mine
                  if r["end_utc"] <= t and (prev is None or r["start_utc"] > prev)]
        baselines = [r for r in window if not any(d["sum"] > 0 for d in r["datapoints"])]
        dirty = [r["file"] for r in window if any(d["sum"] > 0 for d in r["datapoints"])]
        out.append({**positive[t], "metric": metric,
                    "baseline_interval_opens_after": prev.isoformat() if prev else None,
                    "n_baseline_reads": len(baselines),
                    "baseline_windows": sorted({(r["start"], r["end"]) for r in baselines}),
                    "reads_before_the_firing_that_were_already_positive": dirty})
    return out


def decide(reads: list[dict[str, Any]]) -> dict[str, Any]:
    per_metric: dict[str, Any] = {}
    for metric in REQUIRED + CORROBORATING + SUB_RESULT + CONTEXT:
        eps = episodes_for(metric, reads, required=metric in REQUIRED)
        per_metric[metric] = {
            "n_reads": sum(1 for r in reads if r["metric"] == metric),
            "episodes": eps,
            "n_episodes": len(eps),
            "fired": bool(eps),
        }

    for metric in REQUIRED:
        for ep in per_metric[metric]["episodes"]:
            if ep["reads_before_the_firing_that_were_already_positive"]:
                raise Refusal(
                    f"{metric} was already positive in "
                    f"{ep['reads_before_the_firing_that_were_already_positive']} before the "
                    f"firing at {ep['t']}, so this episode's increment cannot be attributed "
                    f"to the unevaluable policy in either direction")
            if ep["n_baseline_reads"] <= 0:
                raise Refusal(
                    f"{metric} fired at {ep['t']} with no read whose window closed before "
                    f"it, so there is no measured zero to increment FROM")

    fired = {m: per_metric[m]["fired"] for m in REQUIRED}
    return {"per_metric": per_metric, "fired": fired, "observed": all(fired.values()),
            "n_episodes": min(per_metric[m]["n_episodes"] for m in REQUIRED)}


def build(root: Path = ROOT) -> dict[str, Any]:
    """Everything except the writing, so a test can assert on it without touching results/."""
    reads = load_reads(root)
    b = basis(root)
    d = decide(reads)
    return {"reads": reads, "basis": b, "decision": d, "n_reads": len(reads)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the oracle, the source records and the metric roles; write "
                         "nothing")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(f"{CASE} dry run — no AWS call, no write, $0\n")
        print(f"oracle ({O.BINDINGS[CASE].kind}): {O.oracle_text(CASE)}\n")
        print(f"pre-registered n: {O.planned_n(CASE) or 'none'}   "
              f"mandatory mutation arm: {O.mutation_is_mandatory(CASE)}")
        for d in _dirs():
            n = len(list(d.glob("*_get_metric_statistics_ok.json"))) if d.is_dir() else 0
            print(f"  {'present' if d.is_dir() else 'MISSING':8} {n:4} metric read(s)  "
                  f"{d.relative_to(ROOT)}")
        print("\nmetric roles:")
        for role, names in (("REQUIRED (the oracle's conjunction)", REQUIRED),
                            ("CORROBORATING", CORROBORATING),
                            ("SUB-RESULT, never scored", SUB_RESULT),
                            ("CONTEXT", CONTEXT)):
            print(f"  {role:38} {', '.join(names)}")
        print("\nwould write results/phase1/F9-2.json")
        return 0

    try:
        b = build()
    except Refusal as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    d = b["decision"]
    pm = d["per_metric"]
    for metric in REQUIRED + CORROBORATING + SUB_RESULT:
        row = pm[metric]
        # `t_utc`, not the raw `t`. CloudWatch stamped these +07:00 and every window in the
        # evidence is +00:00; printing the raw stamp next to a UTC window is the misreading
        # that `_utc` exists to stop, and a console line is where a reader would form it.
        eps = ", ".join(f"{e['t_utc']} sum={e['sum']:g} samples={e['samples']:g}"
                        for e in row["episodes"]) or "no positive datapoint in any read"
        print(f"  {'FIRED  ' if row['fired'] else 'SILENT '} {metric:26} "
              f"{row['n_reads']:3} read(s)  {eps}")

    o = P.obs_existence(
        CASE, d["observed"], n=b["basis"]["mcp_tools_call"],
        reading=("the two metrics the sealed oracle names, each required to have at least one "
                 "positive datapoint that a read with an earlier-closing window recorded as "
                 "zero"),
        fired_per_metric=d["fired"],
        n_episodes_min_across_required_metrics=d["n_episodes"],
        per_metric={m: {k: v for k, v in row.items() if k != "episodes"}
                    for m, row in pm.items()},
        episodes={m: pm[m]["episodes"] for m in REQUIRED + CORROBORATING},
        n_basis=(f"{b['basis']['mcp_tools_call']} `mcp:tools/call` records against F5-4a's "
                 f"broken policies, counted on disk; {b['basis']['create_policy']} "
                 f"create_policy and {b['basis']['delete_policy']} delete_policy records "
                 f"establish that the policies existed and were removed"),
        source=(f"raw get_metric_statistics records under evidence/{SOURCE_RUN}/, "
                f"{b['n_reads']} of them, recomputed rather than read out of "
                f"results/phase1/F5-4a.json"),
        replication=("F5-4a ran the arms twice, 2026-08-11 22:47Z and 2026-08-12 00:02Z, and "
                     "both episodes are derived here from their own datapoint timestamps. "
                     "The two are 75 minutes apart across a UTC day boundary, which is two "
                     "calendar days by the project's counting rule and NOT two days' worth "
                     "of separation; FINDING-F5-4A.md §8 states the same gap as 77 minutes "
                     "between the instrument queries"),
        what_this_does_not_prove=[
            "that a lone unevaluable policy increments anything. The 20 mismatches per "
            "episode are a twin DISAGREEMENT — F5-4a's ACTIVE twin denied all 20 while the "
            "identical statement in LOG_ONLY allowed all 20 — so what is measured is that "
            "the mismatch family fires when one twin cannot evaluate",
            "anything about the mechanism inside the evaluator; these are CloudWatch reads "
            "of a window that has closed",
        ],
        sub_result_not_scored={
            "LogOnlyEvalIncomplete": (
                "0 positive datapoints in every window F5-4a and its supplementary read "
                "queried, and F7-1 recorded name_in_namespace_inventory false. That is "
                "C-s6-4-trow-006's ground and F7-1's excluded metric, not this oracle's: "
                "F7-1 excluded it as NOT_EXERCISED because reproducing the condition needed "
                "a deliberately broken policy, which F5-4a then shipped"),
        },
        paired_case="F5-4a",
        finding="results/FINDING-F9-2.md")
    rec = O.evaluate(o)

    payload = {"billable_calls": 0, "mutations": 0, "aws_calls": 0, "analysis_only": True,
               "source_run": SOURCE_RUN,
               "reads": sorted({r["file"] for r in b["reads"]}),
               "basis": b["basis"],
               "metric_roles": {"required": list(REQUIRED),
                                "corroborating": list(CORROBORATING),
                                "sub_result_not_scored": list(SUB_RESULT),
                                "context": list(CONTEXT)}}
    P.emit(CASE, rec, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
