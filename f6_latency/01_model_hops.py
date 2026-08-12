#!/usr/bin/env python3
"""F6-2 and F6-5: what does a Bedrock guardrail actually cost inside a model invocation?

    python3 f6_latency/01_model_hops.py --dry-run
    python3 f6_latency/01_model_hops.py --n 5      # smoke, ~1 min
    python3 f6_latency/01_model_hops.py           # n=1000/arm, ~55-75 min

Two sealed oracles, one paired experiment:

    F6-2  BAND_CONTAINS (100, 500) ms   Hop #2, the INPUT guardrail. "Measured p50/p90/p99
          with distribution-free CIs at n=1000. FALSE for the ILLUSTRATIVE 100-500ms if the
          measured p50-p99 band lies outside it; the paired shift must also exclude 0, or
          the hop has no measurable cost and 6.1 overstates it"
    F6-5  BAND_CONTAINS (100, 500) ms   Hop #6, the OUTPUT guardrail. "... Also settles
          whether output evaluation is parallel: 5.1 makes no parallelism claim, so a
          per-policy linear scaling would be a new finding"

THE INSTRUMENT IS THE DOCUMENT'S OWN, AND IT IS NOT A CLOUDWATCH METRIC
----------------------------------------------------------------------
§6.1 row 6 names `guardrailProcessingLatency (invocation trace)`, and the document says so
again in its own words: "there is no CloudWatch metric for per-invocation guardrail overhead."
That is correct, and F7-1/F7-3 measured the consequence — `AWS/Bedrock/Guardrails` publishes
per-minute aggregates only. A per-minute average cannot yield the p99 with a distribution-free
CI that both sealed cells require, so the only instrument that can carry these two verdicts is
the per-call invocation trace:

    Converse(..., guardrailConfig={"trace": "enabled"})
      -> metrics.latencyMs                                              total, this call
      -> trace.guardrail.inputAssessment[gid]
             .invocationMetrics.guardrailProcessingLatency              Hop #2  -> F6-2
      -> trace.guardrail.outputAssessments[gid][k]
             .invocationMetrics.guardrailProcessingLatency              Hop #6  -> F6-5

Both fields were confirmed present against the live API before this script was written (451 ms
input, 206 ms output on a single probe), so the design does not rest on documentation.

WHY THE OUTPUT SIDE IS A SUM AND THE INPUT SIDE IS NOT
-----------------------------------------------------
`inputAssessment` is a single object per guardrail; `outputAssessments` is a LIST per guardrail,
because a response can be evaluated in more than one piece. The hop's cost is what the response
spent in guardrail evaluation in total, so the list is SUMMED and its length is recorded. Taking
`[0]` would silently report a fraction of the hop whenever the service split the response, and
would do it in the flattering direction. If any trial carries more than one output assessment,
`n_output_assessments_max` says so in the payload.

THE PAIRED BARE ARM, AND WHY IT IS INTERLEAVED RATHER THAN BLOCKED
-----------------------------------------------------------------
F6-2's oracle requires the paired shift to exclude 0. That needs a guardrail-free arm, and the
two arms must be comparable: Bedrock latency drifts with load over an hour, so running 1000
guarded calls and then 1000 bare calls would put the whole difference at risk of being time of
day. Trials therefore alternate — guarded(i), bare(i), guarded(i+1), ... — and are paired by
index, which is what makes `paired_bootstrap_diff_ci` legitimate here.

The shift is `total_ms(guarded) - total_ms(bare)`: the whole cost of turning guardrails on,
which is Hop #2 + Hop #6 plus whatever else the service does differently. It is deliberately
NOT compared against the sum of the two reported processing latencies — that comparison is a
residual, it belongs to F6-7, and it is the thing F6-7 exists to test.

THE PRIMARY ARM'S GUARDRAIL IS THE ONE THAT NEVER INTERVENES
------------------------------------------------------------
The primary arm uses the `billing` guardrail: five content filters at MEDIUM in both
directions, every action `NONE`. Evaluation runs; nothing is ever blocked or masked. That
matters because an intervening guardrail returns a DIFFERENT response — a blocked call skips
inference entirely — and a latency distribution mixing blocked and passed calls measures the
mix, not the hop. A guardrail with BLOCK actions on benign text would usually behave the same
way, but "usually" is a property of the corpus, not of the design.

CONFIGURATION WEIGHT IS MEASURED, NOT ASSUMED AWAY
--------------------------------------------------
§6.1 states one band for Hop #2 with no mention of how much guardrail is configured, and Hop #6
likewise. That cannot be right in general: evaluation must cost something per policy. So three
secondary arms run at n=200 on the manifest's existing guardrails, giving a configuration
ladder of 1, 3, 5 and 31 configured policies:

    topic    1 denied topic
    words    3 word entries
    billing  5 content filters      <- the PRIMARY arm, n=1000
    pii     31 PII entity types

These are RECORDED AND NEVER SCORED. They cannot be, on two counts: the sealed cell for these
cases is n=1000, and no oracle in the pre-registration mentions configuration weight. What they
do is decide the *class* of any failure. If the primary arm lands below 100 ms, a band failure
that also holds at 31 policies is a defect in §6.1's number; a band failure that disappears at
31 policies is a defect in §6.1's silence about configuration. Those are different amendments,
and the pre-registration cannot tell them apart because it never asked.

THE MODEL IS NOT CLAUDE, AND THAT IS REGISTERED
-----------------------------------------------
§1 says "backend models (e.g., Claude)". This account cannot invoke Claude 3.5 Haiku —
`ResourceNotFoundException` on the model id, not a throttle — so the arms run on
`us.amazon.nova-micro-v1:0`. See DEV-P4-06. For F6-2 and F6-5 the substitution is close to
harmless: the hops being measured are the GUARDRAIL's evaluation of text, which runs in the
guardrail service and not in the model. The substitution matters for Hop #3, and §6.1 labels
that row "model-specific" itself; F6-6 carries the consequence.

GUARDS, all INCONCLUSIVE-on-failure
-----------------------------------
    guardrail_ran               every guarded trial carries an input assessment with a
                                processing latency. An absent trace field would otherwise be
                                indistinguishable from a fast hop
    no_intervention             no trial's stopReason is `guardrail_intervened`. One blocked
                                call in the arm makes the distribution a mixture
    arms_are_paired             the two arms hold the same trial ids, so the paired shift is
                                over pairs and not over two different sets of indices
    trace_is_enabled            the response carries `trace.guardrail`, i.e. we asked for the
                                instrument and got it
    output_side_complete        every guarded trial carries at least one output assessment.
                                F6-5 is the case this gates; F6-2 does not depend on it

Note that `billing` appears in the ladder as well as being the primary arm. The 200 ladder
trials are collected independently, under their own checkpoint, so they are a within-run
replication of the primary arm's p50 at one fifth the n — cheap, and the one thing that would
catch a primary arm quietly measuring something else.

COST
----
2,800 Converse calls on Nova Micro (1,000 guarded + 1,000 bare + 4 x 200 ladder). Only the
1,800 GUARDED calls are evaluated, at one input and one output text unit each: 3,600 text
units, of which 400 are the PII-priced arm. Plus roughly 0.3M Nova Micro tokens. At the
verified prices in `cost_model.yaml` that is about $0.65 in total. No resource is created,
modified or deleted; every guardrail used already exists and is left untouched.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                   # noqa: E402
import oracle as O                                       # noqa: E402
import phase1 as P                                       # noqa: E402
import stats as S                                        # noqa: E402
import testbed as T                                      # noqa: E402
from checkpoint import Checkpoint                        # noqa: E402
from evidence import EvidenceStore, capture              # noqa: E402

CASES = ("F6-2", "F6-5")
FAMILY = "f6_latency"
PLANNED_N = 1000
LADDER_N = 200

# DEV-P4-06. Claude is not invokable in this account; Nova Micro is.
MODEL_ID = "us.amazon.nova-micro-v1:0"

# The primary arm's guardrail: 5 content filters, MEDIUM both directions, every action NONE.
PRIMARY_KEY = "billing"

# The configuration ladder, recorded and never scored. Ordered by configured policy count.
LADDER = (
    ("topic", 1, "one denied topic"),
    ("words", 3, "three word-policy entries"),
    ("billing", 5, "five content filters at MEDIUM, actions NONE — the primary arm"),
    ("pii", 31, "thirty-one PII entity types"),
)

# One fixed prompt for every trial in every arm. Fixed because text units are charged per
# 1,000 characters and because a varying input length would put length variance into the
# input-side hop, which is the quantity F6-2 reports a p99 of.
PROMPT = (
    "Reply with one short sentence about how a library card catalogue is organised. "
    "Keep the answer under thirty words and do not use any lists, headings or emphasis."
)
MAX_TOKENS = 64

GUARDS = ("guardrail_ran", "no_intervention", "arms_are_paired", "trace_is_enabled",
          "output_side_complete")

# Bedrock allows a high call rate on Nova Micro, but this script is not trying to load-test
# it: a throttled arm would have retries in the middle of a latency measurement, and a
# retried trial's latency is not the hop's latency. One call at a time, with a small gap.
INTER_CALL_S = 0.05


class ConfigError(RuntimeError):
    """The testbed is not in the state this case needs. Never a verdict."""


# ---------------------------------------------------------------------------
# one trial
# ---------------------------------------------------------------------------

def _converse(store, brt, *, gid: str | None) -> dict[str, Any]:
    """One Converse call. `gid=None` is the bare arm.

    The wall-clock elapsed time is recorded alongside the service's own `metrics.latencyMs`.
    They answer different questions — ours includes the round trip and the SDK, theirs does
    not — and where §6.1's total is concerned the difference is the point, so both are kept.
    """
    kw: dict[str, Any] = {
        "modelId": MODEL_ID,
        "messages": [{"role": "user", "content": [{"text": PROMPT}]}],
        "inferenceConfig": {"maxTokens": MAX_TOKENS, "temperature": 0.0},
    }
    if gid:
        kw["guardrailConfig"] = {"guardrailIdentifier": gid, "guardrailVersion": "DRAFT",
                                 "trace": "enabled"}
    t0 = time.monotonic()
    rec = capture(store, "converse", brt, **kw)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    rec.raise_for_status()
    resp = rec.response or {}

    out: dict[str, Any] = {
        "arm_has_guardrail": bool(gid),
        "elapsed_ms": round(elapsed_ms, 3),
        "total_ms": (resp.get("metrics") or {}).get("latencyMs"),
        "stop_reason": resp.get("stopReason"),
        "usage": {k: v for k, v in (resp.get("usage") or {}).items()
                  if k in ("inputTokens", "outputTokens", "totalTokens")},
        "output_chars": sum(len(c.get("text") or "")
                            for m in [(resp.get("output") or {}).get("message") or {}]
                            for c in (m.get("content") or [])),
        "input_ms": None, "output_ms": None,
        "n_output_assessments": 0, "trace_present": False,
    }
    if not gid:
        return out

    gr = (resp.get("trace") or {}).get("guardrail") or {}
    out["trace_present"] = bool(gr)
    ia = (gr.get("inputAssessment") or {}).get(gid) or {}
    im = ia.get("invocationMetrics") or {}
    if "guardrailProcessingLatency" in im:
        out["input_ms"] = float(im["guardrailProcessingLatency"])
    oas = (gr.get("outputAssessments") or {}).get(gid) or []
    out["n_output_assessments"] = len(oas)
    lats = [float((a.get("invocationMetrics") or {}).get("guardrailProcessingLatency"))
            for a in oas
            if (a.get("invocationMetrics") or {}).get("guardrailProcessingLatency") is not None]
    # SUMMED, not [0]: see the module docstring. The count travels with the number.
    out["output_ms"] = sum(lats) if lats else None
    out["output_ms_parts"] = lats
    return out


def _run_arm(store, brt, *, case_cell: str, gid: str | None, n: int, is_smoke: bool,
             label: str) -> Checkpoint:
    """Collect one arm, resumable. `case_cell` names the checkpoint, so arms never collide."""
    cp = Checkpoint(case_id=CASES[0], cell=case_cell).load()
    cp.set_meta(model_id=MODEL_ID, guardrail_id=gid or "", prompt_len=len(PROMPT),
                max_tokens=MAX_TOKENS, is_smoke=is_smoke, arm=label)
    for i in range(n):
        tid = f"t{i:04d}"
        if cp.is_done(tid):
            continue
        cp.run_trial(tid, lambda: _converse(store, brt, gid=gid))
        if INTER_CALL_S:
            time.sleep(INTER_CALL_S)
    return cp


def _series(cp: Checkpoint, field: str) -> list[float]:
    """One arm's per-trial values for `field`, in trial-id order, skipping absent ones."""
    rows = cp.results()
    return [float(rows[k][field]) for k in sorted(rows)
            if rows[k].get(field) is not None]


def _paired(a: Checkpoint, b: Checkpoint, field: str) -> tuple[list[float], list[float]]:
    """Values for trial ids present in BOTH arms, in the same order. Pairing is by index."""
    ra, rb = a.results(), b.results()
    ids = sorted(set(ra) & set(rb))
    xs = [(ra[i].get(field), rb[i].get(field)) for i in ids]
    keep = [(float(x), float(y)) for x, y in xs if x is not None and y is not None]
    return [x for x, _ in keep], [y for _, y in keep]


def _describe(values: list[float], *, alpha: float, allow_p99: bool) -> dict[str, Any]:
    """The reported shape of one latency distribution. p99 only where the cell earns it."""
    if not values:
        return {"n": 0}
    out: dict[str, Any] = {
        "n": len(values),
        "min": round(min(values), 3), "max": round(max(values), 3),
        "p50": round(S.quantile(values, 0.50), 3),
        "p90": round(S.quantile(values, 0.90), 3),
        "ci_p50": str(S.quantile_ci(values, 0.50, level=1 - alpha)),
        "ci_p90": str(S.quantile_ci(values, 0.90, level=1 - alpha)),
    }
    if allow_p99 and len(values) >= 100:
        out["p99"] = round(S.quantile(values, 0.99), 3)
        out["ci_p99"] = str(S.quantile_ci(values, 0.99, level=1 - alpha))
    else:
        out["p99"] = None
        out["why_no_p99"] = ("a p99 needs n>=100 and a cell that pre-registered one; this "
                            "series has neither, and a p99 printed beside a verdict gets "
                            "quoted")
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:                     # noqa: C901, PLR0915
    ap = P.parser(CASES[0], __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else PLANNED_N
    n_ladder = min(args.n, LADDER_N) if args.n else LADDER_N
    is_smoke = args.n is not None

    if args.dry_run:
        for case in CASES:
            hop = "#2 input" if case == "F6-2" else "#6 output"
            P.dry_run_banner(
                case,
                [("guarded", f"Converse + guardrailConfig(trace=enabled), hop {hop}", n),
                 ("bare", "Converse with no guardrailConfig — the paired baseline", n),
                 ("ladder", "n=200 each at 1 / 3 / 5 / 31 configured policies, RECORDED "
                            "and never scored", n_ladder * len(LADDER))],
                operations={"converse": 2 * n + n_ladder * len(LADDER)},
                mutations=0, billable=True,
                text_units=2 * (n + n_ladder * len(LADDER)),
                text_units_why=("one fixed ~200-character prompt is one input text unit, and "
                                "each response is one output text unit; only guarded arms are "
                                "evaluated, so the bare arm contributes none"),
                extra=[
                    f"the instrument is the invocation trace, not CloudWatch: the document "
                    f"itself says there is no per-invocation metric, and F7-1/F7-3 measured "
                    f"the consequence — {case} needs a p99 with a distribution-free CI and a "
                    f"per-minute aggregate cannot supply one",
                    "output-side latency is SUMMED over outputAssessments[], never [0]: the "
                    "service may split a response, and taking the first part would report a "
                    "fraction of the hop in the flattering direction",
                    "arms alternate guarded/bare and are paired by trial index, so the shift "
                    "F6-2's oracle requires is not confounded with drift in Bedrock latency "
                    "over the hour the arm takes",
                    "F6-2's oracle carries a SECOND condition beyond its sealed kind — the "
                    "paired shift must exclude 0. It is applied here and can only turn a "
                    "TRUE into a FALSE, never the reverse",
                    f"the primary guardrail is {PRIMARY_KEY!r}: content filters with every "
                    f"action NONE, so evaluation runs and nothing is ever blocked. A "
                    f"distribution mixing blocked and passed calls measures the mixture",
                    "DEVIATION DEV-P4-06: the model is Nova Micro, not Claude. Claude is not "
                    "invokable in this account (ResourceNotFoundException, not a throttle). "
                    "These two hops run in the guardrail service, not the model, so the "
                    "substitution is close to harmless here; F6-6 carries the consequence",
                    "the configuration ladder (1/3/5/31 policies) is RECORDED, NEVER SCORED. "
                    "Its job is to decide whether a band failure is a defect in §6.1's "
                    "number or in §6.1's silence about how much guardrail is configured",
                    f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}",
                ])
            print()
        return 0

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    brt = fc.bedrock_runtime()
    store = EvidenceStore(run_id, FAMILY, "F6-2_5")
    store.write_environment()

    man = P.manifest()
    primary_gid = P.guardrail(PRIMARY_KEY, man=man)
    if not primary_gid:
        raise ConfigError(f"manifest has no guardrail {PRIMARY_KEY!r}; the primary arm cannot "
                          f"run and no substitute would be the pre-committed one")

    print(f"F6-2/F6-5 — model-side guardrail hops, run_id={run_id}, region={region}")
    print(f"  model {MODEL_ID}  primary guardrail {PRIMARY_KEY!r} ({primary_gid})")
    print(f"  arms: guarded n={n}, bare n={n}, ladder {len(LADDER)}x n={n_ladder}")

    # ---- primary paired arms, interleaved ----------------------------------------
    cp_g = Checkpoint(case_id=CASES[0], cell="guarded").load()
    cp_b = Checkpoint(case_id=CASES[0], cell="bare").load()
    for cp, gid, label in ((cp_g, primary_gid, "guarded"), (cp_b, None, "bare")):
        cp.set_meta(model_id=MODEL_ID, guardrail_id=gid or "", max_tokens=MAX_TOKENS,
                    is_smoke=is_smoke, arm=label, prompt_len=len(PROMPT))
    t0 = time.monotonic()
    for i in range(n):
        tid = f"t{i:04d}"
        for cp, gid in ((cp_g, primary_gid), (cp_b, None)):
            if cp.is_done(tid):
                continue
            cp.run_trial(tid, lambda cp=cp, gid=gid: _converse(store, brt, gid=gid))
            if INTER_CALL_S:
                time.sleep(INTER_CALL_S)
        if (i + 1) % 100 == 0:
            rate = (i + 1) / max(time.monotonic() - t0, 1e-9)
            print(f"    {i + 1}/{n} pairs  ({rate * 60:.0f} pairs/min)  "
                  f"guarded={cp_g.n_done} bare={cp_b.n_done}")

    # ---- the configuration ladder ------------------------------------------------
    ladder: list[dict[str, Any]] = []
    for key, n_pol, why in LADDER:
        gid = P.guardrail(key, man=man)
        if not gid:
            ladder.append({"guardrail": key, "n_policies": n_pol, "error": "not in manifest"})
            continue
        cp = _run_arm(store, brt, case_cell=f"ladder_{key}", gid=gid, n=n_ladder,
                      is_smoke=is_smoke, label=f"ladder:{key}")
        ladder.append({
            "guardrail": key, "guardrail_id": gid, "n_policies": n_pol, "why": why,
            "is_primary": key == PRIMARY_KEY,
            "n_done": cp.n_done, "n_failed": cp.n_failed,
            "input_ms": _describe(_series(cp, "input_ms"), alpha=0.05, allow_p99=False),
            "output_ms": _describe(_series(cp, "output_ms"), alpha=0.05, allow_p99=False),
            "total_ms": _describe(_series(cp, "total_ms"), alpha=0.05, allow_p99=False),
        })
        print(f"    ladder {key:8s} ({n_pol:2d} policies): "
              f"input p50={ladder[-1]['input_ms'].get('p50')} "
              f"output p50={ladder[-1]['output_ms'].get('p50')}")

    # ---- guards -------------------------------------------------------------------
    rows_g = cp_g.results()
    rows_b = cp_b.results()
    ids_shared = sorted(set(rows_g) & set(rows_b))
    n_no_input = sum(1 for r in rows_g.values() if r.get("input_ms") is None)
    n_no_output = sum(1 for r in rows_g.values() if not r.get("n_output_assessments"))
    n_no_trace = sum(1 for r in rows_g.values() if not r.get("trace_present"))
    intervened = sorted(k for k, r in list(rows_g.items()) + list(rows_b.items())
                        if str(r.get("stop_reason") or "").lower() == "guardrail_intervened")
    max_oa = max((int(r.get("n_output_assessments") or 0) for r in rows_g.values()), default=0)

    guards = {
        "guardrail_ran": bool(rows_g) and n_no_input == 0,
        "no_intervention": not intervened,
        "arms_are_paired": bool(ids_shared) and len(ids_shared) == min(len(rows_g),
                                                                      len(rows_b)),
        "trace_is_enabled": bool(rows_g) and n_no_trace == 0,
        "output_side_complete": bool(rows_g) and n_no_output == 0,
    }
    guard_detail = {
        "guardrail_ran": {
            "n_guarded": len(rows_g), "n_missing_input_latency": n_no_input,
            "why": ("an absent trace field is indistinguishable from a fast hop, and a "
                    "missing value silently shortens the series the p99 is taken over")},
        "no_intervention": {
            "intervened_trials": intervened[:20], "n_intervened": len(intervened),
            "why": ("a blocked call skips inference, so its latency belongs to a different "
                    "population; one in the arm makes the distribution a mixture")},
        "arms_are_paired": {
            "n_guarded": len(rows_g), "n_bare": len(rows_b), "n_paired": len(ids_shared),
            "why": ("the shift is over pairs. Two arms of equal SIZE but different trial ids "
                    "would still pair index i of one against a different call of the other")},
        "trace_is_enabled": {"n_without_trace": n_no_trace,
                             "why": "we asked for the instrument; this checks we got it"},
        "output_side_complete": {
            "n_without_output_assessment": n_no_output,
            "max_output_assessments_in_one_call": max_oa,
            "gates": "F6-5 only",
            "why": ("F6-5 is a claim about output-side evaluation. A trial with no output "
                    "assessment has no Hop #6 to measure, and counting it as 0 ms would "
                    "invent a fast hop")},
    }

    common: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "model": {
            "model_id": MODEL_ID,
            "why_not_claude": ("§1 says 'e.g., Claude'. Claude 3.5 Haiku raises "
                               "ResourceNotFoundException in this account — a model-access "
                               "fact, not a throttle. DEV-P4-06"),
            "why_it_barely_matters_here": ("Hops #2 and #6 are the GUARDRAIL service "
                                           "evaluating text; the model does not run them. "
                                           "The substitution bites on Hop #3, and §6.1 "
                                           "labels that row model-specific itself")},
        "arms": {
            "guarded": {"guardrail": PRIMARY_KEY, "guardrail_id": primary_gid,
                        "guardrail_version": "DRAFT", "trace": "enabled",
                        "n_done": cp_g.n_done, "n_failed": cp_g.n_failed},
            "bare": {"guardrail": None, "n_done": cp_b.n_done, "n_failed": cp_b.n_failed},
            "interleaved": True,
            "why_interleaved": ("Bedrock latency drifts with load; blocked arms would put the "
                                "difference at risk of being time of day rather than the "
                                "guardrail")},
        "prompt": {"text": PROMPT, "chars": len(PROMPT), "max_tokens": MAX_TOKENS,
                   "why_fixed": ("length variance in the input would land inside the "
                                 "input-side hop, which is the quantity F6-2 publishes a "
                                 "p99 of; and text units are charged per 1,000 characters")},
        "guard_names": list(GUARDS),
        "guards": guards,
        "guard_detail": guard_detail,
        "configuration_ladder": {
            "arms": ladder,
            "scored": False,
            "why_recorded": ("§6.1 gives ONE band for Hop #2 and one for Hop #6, with no "
                             "mention of how much guardrail is configured. If the primary "
                             "arm misses the band, this ladder decides whether the defect is "
                             "in the number or in the silence — two different amendments"),
            "why_not_scored": ("the sealed cell is n=1000 and no oracle in the "
                               "pre-registration mentions configuration weight. Scoring it "
                               "would be answering a question we never registered")},
        "output_assessment_handling": {
            "rule": "SUM over outputAssessments[<gid>][], count recorded",
            "max_seen": max_oa,
            "why": ("the hop's cost is the total time the response spent in evaluation. "
                    "Taking [0] would report a fraction whenever the service split the "
                    "response, and would do it in the flattering direction")},
    }

    alpha = O.alpha_for("F6-2")
    g_totals, b_totals = _paired(cp_g, cp_b, "total_ms")
    shift_ci = None
    shift_hl = None
    wilcoxon = None
    if len(g_totals) >= 6:
        ci = S.paired_bootstrap_diff_ci(g_totals, b_totals, statistic=median,
                                        level=1 - alpha)
        shift_ci = (float(ci.lo), float(ci.hi))
        shift_hl = S.hodges_lehmann(g_totals, b_totals)
        wilcoxon = S.wilcoxon_signed_rank(g_totals, b_totals)

    input_series = _series(cp_g, "input_ms")
    output_series = _series(cp_g, "output_ms")

    rc = 0
    for case in CASES:
        series = input_series if case == "F6-2" else output_series
        hop = "#2 (input guardrail)" if case == "F6-2" else "#6 (output guardrail)"
        gates = dict(guards)
        if case == "F6-2":
            # F6-5's leg is not F6-2's business: an absent OUTPUT assessment says nothing
            # about the input hop, and gating F6-2 on it would couple two verdicts.
            gates.pop("output_side_complete")
        failed = sorted(k for k, v in gates.items() if not v)

        payload = {
            **common,
            "hop": hop,
            "measured_field": ("trace.guardrail.inputAssessment[gid].invocationMetrics."
                               "guardrailProcessingLatency" if case == "F6-2" else
                               "sum(trace.guardrail.outputAssessments[gid][].invocation"
                               "Metrics.guardrailProcessingLatency)"),
            "distribution": _describe(series, alpha=alpha, allow_p99=True),
            "guarded_total_ms": _describe(_series(cp_g, "total_ms"), alpha=alpha,
                                          allow_p99=True),
            "bare_total_ms": _describe(_series(cp_b, "total_ms"), alpha=alpha,
                                       allow_p99=True),
            "output_chars": _describe([float(r["output_chars"]) for r in rows_g.values()
                                       if r.get("output_chars") is not None],
                                      alpha=alpha, allow_p99=False),
            "paired_shift_total_ms": {
                "definition": "median(total_ms guarded) - median(total_ms bare)",
                "n_pairs": len(g_totals),
                "bootstrap_ci": list(shift_ci) if shift_ci else None,
                "hodges_lehmann": shift_hl,
                "wilcoxon": {"statistic": wilcoxon[0], "p_value": wilcoxon[1]}
                if wilcoxon else None,
                "why_the_total_and_not_the_sum_of_hops": (
                    "this is the whole cost of turning guardrails on. Comparing it against "
                    "input_ms + output_ms is a RESIDUAL, and that is F6-7's question, not "
                    "this one's")},
        }

        if failed:
            rec = O.not_measured(
                case,
                f"guard(s) {', '.join(failed)} did not hold, so a latency band read from "
                f"this arm would not be about hop {hop}",
                guards=guards, guard_detail=guard_detail)
            P.emit(case, rec, payload, store)
            rc = max(rc, 1)
            continue

        obs = O.Observation(case_id=case, n_attempted=n, n_usable=len(series),
                            latencies_ms=series,
                            detail={"hop": hop, "shift_ci": shift_ci})
        rec = O.evaluate(obs)

        # F6-2's oracle text carries a SECOND condition its sealed kind does not encode:
        # "the paired shift must also exclude 0, or the hop has no measurable cost and 6.1
        # overstates it". Applied here, and it can only tighten: a band that holds while the
        # shift straddles 0 becomes FALSE, never the reverse.
        if case == "F6-2":
            excludes_zero = bool(shift_ci) and (shift_ci[0] > 0 or shift_ci[1] < 0)
            payload["oracle_text_second_condition"] = {
                "text": ("the paired shift must also exclude 0, or the hop has no "
                         "measurable cost and 6.1 overstates it"),
                "shift_ci": list(shift_ci) if shift_ci else None,
                "excludes_zero": excludes_zero,
                "applied": True,
                "direction": ("can only turn TRUE into FALSE. The sealed kind checks the "
                              "band alone, so implementing the oracle's full text tightens "
                              "the test against the document")}
            if rec["verdict"] == O.TRUE and not excludes_zero:
                rec["verdict"] = O.FALSE
                rec["notes"].append(
                    "the p50-p99 band lies inside 100-500ms, but the paired shift's CI "
                    "includes 0: turning guardrails on produced no measurable change in "
                    "total latency, which is the second condition the sealed oracle text "
                    "states and which §6.1 fails")

        P.emit(case, rec, payload, store)
        d = payload["distribution"]
        print(f"  {case}: {rec['verdict']}  hop {hop}  "
              f"p50={d.get('p50')} p90={d.get('p90')} p99={d.get('p99')} ms "
              f"(band {O.BINDINGS[case].thresholds})")
        if rec["verdict"] not in O.DECISIVE:
            rc = max(rc, 1)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
