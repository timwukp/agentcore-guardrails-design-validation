#!/usr/bin/env python3
"""Instrument feasibility probe: what does a policy span for OUR gateway actually contain?

    python3 f7_observability/00_span_shape_probe.py --dry-run
    python3 f7_observability/00_span_shape_probe.py --minutes 60

THIS PROBE SCORES NOTHING, AND THAT IS THE POINT
------------------------------------------------
No `results/phase1/*.json` is written and `lib/oracle.py` is never called. Four sealed cases
are blocked on one unanswered question about the INSTRUMENT, not about the document, and
answering it by reading a real span is cheaper and more honest than asserting it in a comment:

  * F2-2 "harvest per-trial ConfidenceScore" — n=300 identical inputs, >=2 distinct scores.
  * F2-3 stratify F2-2's trials by observed score; a mixed stratum falsifies.
  * F2-4 place tau inside vs outside the observed score support.
  * F1-18 "every observed ConfidenceScore across >=500 evaluations lies on the lattice
    {0,.2,.4,.6,.8,1.0}"; its method says "harvest scores from F2/F3 runs".

Every one of those needs a PER-TRIAL NUMERIC SCORE. `f2_determinism/01_repeat.py` measured
(F2-5, verdict FALSE) that the ApplyGuardrail response surface does not carry one: its content
filters expose `confidence` and `filterStrength` as four-value enums (NONE/LOW/MEDIUM/HIGH),
and the numeric fields on that API belong to a different policy block. So if a numeric score
is observable anywhere, it is on the POLICY path — a guardrail-bearing Cedar policy evaluated
by the gateway — and the only place a per-request value from that path could surface is the
span. This probe looks.

The three outcomes are all useful, which is why it is worth running before any of the four
scripts is written:

  * a numeric score appears per span -> F2-2/F2-3/F2-4/F1-18 are feasible as pre-registered,
    with the span as the harvest surface, and F1-18's ">=500 evaluations" can be pooled from
    F2 and F3 traffic exactly as its method says.
  * only an enum appears -> the pre-registered method is not executable on this service. That
    is a DEVIATIONS entry and probably an amendment candidate against the document's own
    six-value lattice, not a case to quietly skip. It also makes F2-3's strata coarse rather
    than absent, so the case survives in weakened form.
  * no span at all -> the blocker is upstream (F7-4/F7-5, tracing) and the F2 sub-cases are
    ordered AFTER F7, not before. That reordering is the reason this runs now.

WHY IT READS OLD TRAFFIC INSTEAD OF SENDING ANY
-----------------------------------------------
`aws/spans` retains 30 days, and the F4 truth-table run (n=120 x 8 cells, 2026-08-11) already
pushed real requests through guardrail-bearing policies in ENFORCE. Those spans are the exact
population the four cases would harvest from. Sending fresh traffic to ask a question already
answered by traffic on disk would spend text units to learn nothing extra — and, while the
F2-1 run holds the gateway in a driven configuration, it would also be a second writer on a
shared testbed.

So this is READ-ONLY: `logs:StartQuery` and `logs:GetQueryResults` against a pre-existing log
group, plus one control-plane read to confirm the delivery is live. It mutates nothing, it can
run beside another experiment, and its only cost is Logs Insights bytes scanned over a bounded
window.

TWO WAYS THIS PROBE COULD LIE, AND WHAT STOPS THEM
--------------------------------------------------
`aws/spans` is a PRE-EXISTING SHARED group carrying other systems' spans, so an unfiltered
query returns rows that would read as our evidence. Every read goes through
`infra/07_traces.query_spans`, which filters to one gateway ARN and treats that filter as
mandatory — this script does not open its own query path.

And "no score found" is only informative if spans were being emitted at all: with the TRACES
delivery down, an empty result set means "tracing off", not "the service publishes no score".
`traces_delivery_live` is therefore checked FIRST, and a down delivery makes the probe report
`delivery_down` instead of `absent` — the same distinction F7-5 exists to establish, borrowed
here so a missing precondition cannot be read as a measurement.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                              # noqa: E402
import redact                                                       # noqa: E402
import testbed as T                                                 # noqa: E402

# By-path load with a module-level name constant, for the reason
# `lib/tests/test_module_name_collisions.py` enforces: it reads loader calls STATICALLY, so a
# name built from a variable is invisible to it. `07_traces` is not a legal identifier.
TRACES_MODULE_NAME = "grx_infra_07_traces"
_spec = importlib.util.spec_from_file_location(
    TRACES_MODULE_NAME, ROOT / "infra" / "07_traces.py")
_tr = importlib.util.module_from_spec(_spec)
sys.modules[TRACES_MODULE_NAME] = _tr
_spec.loader.exec_module(_tr)

query_spans = _tr.query_spans
traces_delivery_live = _tr.traces_delivery_live
SPANS_LOG_GROUP = _tr.SPANS_LOG_GROUP

OUT = ROOT / "results" / "span_shape_probe.json"

# Key names worth reporting separately, because each answers a different one of the four
# blocked cases. Matched case-insensitively against the FLATTENED attribute paths of every
# span, so a score nested three levels down is still found.
#
# `score` and `confidence` are the F2-2/F1-18 harvest targets. `threshold` matters because a
# guardrail-in-policy condition carries one, and a span that echoes the configured threshold
# without the observed score would look like a hit while being useless for stratification —
# F2-3 needs the value that VARIES, not the one the policy author typed.
PATTERNS: dict[str, str] = {
    "score": r"score",
    "confidence": r"confidence",
    "threshold": r"threshold",
    "guardrail": r"guardrail",
    "policy": r"polic(y|ies)",
    "action": r"action",
    "decision": r"decision|allow|deny|denied",
    "filter_strength": r"filter.?strength",
    "category": r"categor",
}

# The plan named this span-attribute prefix as the place per-category scores would appear.
# It is a PREDICTION being checked, not an assumption: if it is absent while some other path
# carries the score, the finding is that the plan's attribute name was wrong, and the harvest
# code must be written against what the service actually emits.
PREDICTED_SCORE_PREFIX = "aws.agentcore.policy.guardrails"

# Enum values F2-5 measured on the ApplyGuardrail surface. If the span carries these strings
# where a number was wanted, the answer is "enum, not numeric" and the four cases need a
# registered deviation rather than a harvest.
ENUM_VALUES = {"NONE", "LOW", "MEDIUM", "HIGH"}

NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


def _mask_bare_account(obj: Any, account_id: str) -> Any:
    """Replace the caller's own account id wherever it stands alone as a value.

    `redact.mask` handles the account field of an ARN and, by explicit design, nothing else:
    its comment says a bare `\\b\\d{12}\\b` substitution would corrupt the PII corpus rows that
    are *authored* as 12-digit account fixtures. That reasoning is right and this function does
    not broaden it. Instead it removes exactly one known literal — the account this run is
    executing in, read from STS moments earlier — so there is no pattern to over-match.

    It exists because telemetry publishes a shape nothing else in this project produced:
    `attributes.aws.account.id` carries the account id as a standalone value, outside any ARN.
    The redaction gate caught it (5 findings, then 1 after ARN masking), which is the gate
    working; this is the fix rather than a waiver, because a waiver would have to name a real
    account id in a distributed file to describe what it was waiving.
    """
    if isinstance(obj, str):
        return obj.replace(account_id, redact.ACCOUNT_PLACEHOLDER) if account_id else obj
    if isinstance(obj, dict):
        return {_mask_bare_account(k, account_id) if isinstance(k, str) else k:
                _mask_bare_account(v, account_id) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_bare_account(v, account_id) for v in obj]
    return obj


def _write(out: dict[str, Any], account_id: str = "") -> None:
    """Write the probe's record to `results/`, MASKED.

    Every write goes through here, because the first version of this script wrote raw span
    values and the redaction gate caught five identifiers in one file: spans carry
    `aws.account.id` verbatim plus the full gateway ARN in three separate attributes. Any read
    of live telemetry is a leak surface by default — the values are AWS's, not ours, and they
    arrive unmasked no matter how carefully the script was written.

    `results/` is the distributable record, so masking runs over the whole structure rather
    than over a list of fields believed to hold identifiers: an attribute inventory is exactly
    the kind of payload whose interesting keys are not known in advance. The unmasked values
    stay reachable through the ordinary channel — `evidence/`, which is local-only by written
    policy — and nothing here needs them, since the question is which attribute PATHS exist,
    not which account they belong to.

    Two passes, because one is not enough: `redact.mask` for ARNs, then the bare-literal pass
    for the standalone account attribute.
    """
    OUT.write_text(json.dumps(_mask_bare_account(redact.mask(out), account_id),
                              indent=2, sort_keys=True) + "\n")


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Every leaf of a span, keyed by dotted path.

    Spans arrive as JSON whose attributes may be nested, may be a list of {key, value} pairs,
    or may already be dotted strings — three shapes for the same thing. Flattening once here
    means the pattern search below cannot miss a score merely because of how deeply the
    service chose to nest it.
    """
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _parse_row(row: list[dict]) -> dict[str, Any]:
    """One Logs Insights row -> the span's flattened leaves, plus what could not be parsed.

    A row whose `@message` is not JSON is recorded rather than dropped: "the span exists but
    this probe could not read it" is a different fact from "no span", and only one of them is
    a reason to write the harvest against a different surface.
    """
    cells = {c.get("field", ""): c.get("value", "") for c in row}
    msg = cells.get("@message", "")
    try:
        return {"ok": True, "ts": cells.get("@timestamp", ""),
                "leaves": _flatten(json.loads(msg))}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "ts": cells.get("@timestamp", ""),
                "parse_error": f"{type(exc).__name__}: {exc}",
                "raw_head": msg[:600]}


def _classify(leaves: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Decide which of the three outcomes this probe found, and say so in one field.

    `reading` is written for the next person who has to choose a harvest surface, so it names
    the consequence for the four blocked cases rather than restating the counts above it.
    """
    numeric_scores = {p: v for p, v in leaves.items()
                      if re.search(r"score|confidence", p, re.I)
                      and NUMERIC.match(str(v).strip())}
    enum_scores = {p: v for p, v in leaves.items()
                   if re.search(r"score|confidence|filter.?strength", p, re.I)
                   and str(v).strip().upper() in ENUM_VALUES}
    if numeric_scores:
        verdict = "numeric_score_present"
        reading = (
            f"a per-span NUMERIC score is observable at {sorted(numeric_scores)[:4]}. F2-2, "
            f"F2-3, F2-4 and F1-18 are feasible as pre-registered, with the span as the "
            f"harvest surface and F1-18's >=500 evaluations pooled from F2 and F3 traffic "
            f"exactly as its sealed method says. The harvest must read these paths, and the "
            f"distinct-value count must be computed on the raw strings before any float "
            f"conversion — rounding is how a six-value lattice becomes a four-value one")
    elif enum_scores:
        verdict = "enum_only"
        reading = (
            f"the span carries a score-shaped field, but as an ENUM: {enum_scores}. This is "
            f"the same surface F2-5 measured on ApplyGuardrail, so the sealed method 'harvest "
            f"per-trial ConfidenceScore' is not executable as written on this service. "
            f"Consequences, none of which is 'skip the case': F2-2's DISTINCT_AT_LEAST(2) can "
            f"still be evaluated on the enum, and reads TRUE only if two enum levels appear; "
            f"F2-3's strata become the enum levels, which is coarser and can only ever HIDE a "
            f"mixed stratum, so a TRUE there is weak and must say so; F1-18's numeric lattice "
            f"claim is refuted on this surface and becomes amendment material rather than a "
            f"measurement. All of it needs a DEVIATIONS entry naming the instrument change")
    else:
        verdict = "no_score_field"
        reading = (
            "spans exist for this gateway but carry no score-shaped attribute at all. The four "
            "blocked cases have no harvest surface on the span path, and the next thing to try "
            "is a guardrail-bearing policy whose condition threshold is SWEPT — a mixed "
            "outcome at fixed tau across identical inputs proves >=2 distinct underlying "
            "scores without ever observing one, which would satisfy F2-2 indirectly and drive "
            "F2-4 directly. That is an instrument change and a DEVIATIONS entry, not a "
            "silently different experiment")
    return {"verdict": verdict, "reading": reading,
            "numeric_score_paths": numeric_scores, "enum_score_paths": enum_scores}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--minutes", type=int, default=60,
                    help="how far back to query. Bounded deliberately: Logs Insights bills "
                         "bytes scanned and aws/spans is a shared group, so a 30-day window "
                         "would pay for other systems' traffic to answer a question the last "
                         "hour already answers")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    args = ap.parse_args(argv)

    if args.dry_run:
        print("span shape probe — dry run, no AWS call\n")
        print(f"  reads    {SPANS_LOG_GROUP} via infra/07_traces.query_spans, filtered to our "
              f"gateway ARN (the filter is mandatory: the group is shared and pre-existing)")
        print(f"  window   last {args.minutes} min, limit {args.limit} spans")
        print("  mutates  NOTHING. logs:StartQuery + logs:GetQueryResults + one "
              "GetDelivery-class read. Safe to run beside another experiment")
        print("  scores   NOTHING. No results/phase1 record, lib/oracle.py never called")
        print(f"  asks     is a per-request numeric score observable? predicted prefix "
              f"{PREDICTED_SCORE_PREFIX}.<category>.scores")
        print("  gates    the TRACES delivery must be live first, or 'no spans' would read as "
              "'no score published' when it means 'tracing off' (F7-5's confound)")
        print("  unblocks F2-2, F2-3, F2-4, F1-18 — all four need a per-trial score, and "
              "F2-5 measured that ApplyGuardrail exposes only a 4-value enum")
        return 0

    state = T.State.load(Path(args.state) if args.state else None)
    gw = state.find("gateway", "main")
    if not gw:
        print("FATAL: the ledger has no gateway/main.", file=sys.stderr)
        return 2

    f = A.factory(args.region)
    logs = f.logs()
    account_id = A.account_id(f)
    gateway_arn = T.unmask_arn(gw.arn, account_id)

    out: dict[str, Any] = {
        "probe": "span_shape",
        "scores_nothing": ("instrument feasibility only. No results/phase1 record is written "
                           "and lib/oracle.py is never called; the four cases this informes "
                           "are F2-2, F2-3, F2-4 and F1-18"),
        "run_id": state.run_id, "region": args.region,
        "log_group": SPANS_LOG_GROUP,
        "window_minutes": args.minutes, "limit": args.limit,
        "predicted_score_prefix": PREDICTED_SCORE_PREFIX,
        "read_only": ("logs:StartQuery / logs:GetQueryResults over a pre-existing group, plus "
                      "one control-plane read of the delivery. Nothing is mutated, so this can "
                      "run beside a live experiment on the same gateway"),
        "why_old_traffic": ("aws/spans retains 30 days and the F4 truth-table run already "
                            "pushed n=120 x 8 cells through guardrail-bearing policies in "
                            "ENFORCE. Those are the spans the four cases would harvest, so "
                            "sending fresh traffic would spend text units to learn nothing"),
    }

    live = traces_delivery_live(logs, state.run_id, "main")
    out["traces_delivery_live"] = live
    print(f"TRACES delivery live for gateway/main: {live}")
    if not live:
        out["verdict"] = "delivery_down"
        out["reading"] = (
            "the TRACES delivery is not live, so this probe cannot distinguish 'the service "
            "publishes no score' from 'nothing is being published at all'. That is exactly the "
            "confound F7-5 exists to remove, and reporting an empty result as 'absent' here "
            "would be the vacuous reading. Run infra/07_traces.py --ensure, then re-probe")
        _write(out, account_id)
        print(f"\n{out['reading']}\nwrote {OUT}")
        return 1

    print(f"querying {SPANS_LOG_GROUP} for our gateway ARN, last {args.minutes} min "
          f"(filter is mandatory: shared pre-existing group)")
    try:
        rows = query_spans(logs, gateway_arn, minutes=args.minutes, limit=args.limit)
    except (RuntimeError, TimeoutError) as exc:
        out["verdict"] = "query_failed"
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["reading"] = ("the query did not complete, so nothing was observed either way. "
                          "This is an instrument failure, not a finding about spans")
        _write(out, account_id)
        print(f"\nquery failed: {out['error']}\nwrote {OUT}")
        return 1

    parsed = [_parse_row(r) for r in rows]
    ok = [p for p in parsed if p["ok"]]
    out["n_spans"] = len(rows)
    out["n_parsed"] = len(ok)
    out["n_unparseable"] = len(parsed) - len(ok)
    out["unparseable_samples"] = [p for p in parsed if not p["ok"]][:3]

    if not rows:
        out["verdict"] = "no_spans_in_window"
        out["reading"] = (
            f"the delivery is live but no span mentioning our gateway ARN appeared in the last "
            f"{args.minutes} minutes. Widen the window before concluding anything: the F4 run "
            f"is the traffic to look for, and a window shorter than the gap since it ran "
            f"measures only the gap. If a wide window is also empty, the blocker is upstream "
            f"(F7-4/F7-5) and the F2 sub-cases must be ordered after F7")
        _write(out, account_id)
        print(f"\n{out['reading']}\nwrote {OUT}")
        return 1

    # Union of every leaf across every span. The union, not one span's keys: a score attribute
    # is emitted only on requests a guardrail actually evaluated, so a single span chosen for
    # convenience could be one that never had a score to carry.
    union: dict[str, Any] = {}
    for p in ok:
        for path, val in p["leaves"].items():
            union.setdefault(path, val)
    out["n_distinct_leaf_paths"] = len(union)
    out["all_leaf_paths"] = sorted(union)
    out["matches"] = {name: sorted(p for p in union if re.search(rx, p, re.I))
                      for name, rx in PATTERNS.items()}
    out["predicted_prefix_present"] = sorted(
        p for p in union if p.lower().startswith(PREDICTED_SCORE_PREFIX.lower()))
    out["sample_span_leaves"] = ok[0]["leaves"] if ok else {}
    out.update(_classify(union))

    _write(out, account_id)

    print(f"\nspans: {out['n_spans']} returned, {out['n_parsed']} parsed, "
          f"{out['n_distinct_leaf_paths']} distinct attribute paths")
    for name in ("guardrail", "score", "confidence", "threshold", "decision"):
        hits = out["matches"][name]
        print(f"  {name:12s} {len(hits):3d} {hits[:4]}")
    print(f"  predicted prefix {PREDICTED_SCORE_PREFIX}: "
          f"{out['predicted_prefix_present'] or 'ABSENT'}")
    print(f"\nverdict: {out['verdict']}\n{out['reading']}")
    print(f"\nwrote {OUT} (full attribute inventory is in the file, not on stdout)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
