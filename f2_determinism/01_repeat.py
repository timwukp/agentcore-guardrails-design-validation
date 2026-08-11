#!/usr/bin/env python3
"""F2-5: is guardrail evaluation non-deterministic, as §3.3 tells readers to assume?

    python3 f2_determinism/01_repeat.py --dry-run
    python3 f2_determinism/01_repeat.py --n 3        # smoke
    python3 f2_determinism/01_repeat.py             # full, n=300

§3.3 item 1 (line 234) tells readers that caching guardrail decisions is high-risk because
"guardrail evaluation is non-deterministic, AWS auto-updates the underlying models, and
'similar' inputs can differ exactly in the attack payload". The sealed oracle is
DISTINCT_AT_LEAST with threshold 2:

    TRUE if >=1 differing verdict or score in n=300 identical ApplyGuardrail calls;
    FALSE if all 300 are byte-identical in verdict and score.

Note which way round this is. TRUE — the document is right — is the **easy** direction: one
differing response out of 300 confirms it and no interval is needed. FALSE requires 300
identical responses, and that is the claim needing the power. This asymmetry is why n=300
is sealed and why the seal's `transform` is named `differing_to_distinct`: the prose says
">=1 differing", one differing observation means **two distinct** values, and the threshold
is 2 rather than 1 because it counts distinct values, not differences.

WHY THIS TESTS ONE SIXTH OF THE SENTENCE, AND SAYS SO
----------------------------------------------------
The §3.3 sentence bundles several claims and this case's oracle takes exactly one:

  * "guardrail evaluation is non-deterministic" — **this case**, directly.
  * "AWS auto-updates the underlying models" — a claim about AWS's release process over
    months. Unfalsifiable in a 300-call window; F3-11's +7d/+30d regression re-runs in
    Phase 8 are the nearest instrument, and even they cannot attribute a change to a model
    update rather than to a config or infrastructure change.
  * "'similar' inputs can differ exactly in the attack payload" — a property of *inputs*,
    not of the service. F3-3's hard negatives (benign text superficially resembling
    attacks) are where that lives.
  * the cache advice itself ("exact-match only, short TTL, never for prompt-attack") is
    **normative**. It does not follow from non-determinism alone — a deterministic service
    with auto-updated models would justify the same advice — and no experiment makes a
    recommendation true. Recorded in the payload, not scored.

A TRUE verdict here must therefore not be quoted as validating §3.3's advice. It validates
the single premise the oracle names. `what_true_does_not_prove` says so in the payload.

WHY 300 IDENTICAL CALLS, AND WHAT n=300 BUYS
--------------------------------------------
From the pre-registration's power argument: for H0: p_flip = 0 against H1: p_flip >= p1, the
probability of seeing at least one flip in n trials is 1 - (1 - p1)^n, so
n >= ln(beta) / ln(1 - p1). At 95% power that is 59 trials for a 5% flip rate and 298 for
1%. n=300 is the sealed choice: it gives 95% power against a 1%-per-call flip rate.

So a FALSE verdict (300 identical) is not "the service is deterministic" — it is "any
non-determinism is below roughly 1% per call, at 95% power". The one-sided rule-of-three
ceiling for 300 zero events is reported in the payload for exactly that reading. Getting
this direction wrong is the difference between a measured bound and an overclaim.

WHAT COUNTS AS "DIFFERING" — AND WHY `filterStrength` IS NOT A SCORE
-------------------------------------------------------------------
The oracle says "verdict or score". Measured against the 1.43.67 model rather than assumed:
`ApplyGuardrail`'s `assessments[].contentPolicy.filters[]` members are
`['type','confidence','filterStrength','action','detected']`, and **`confidence` and
`filterStrength` are both 4-value enums `['NONE','LOW','MEDIUM','HIGH']`** — not continuous
scores. Content filters expose no numeric score on this API at all. (Contextual grounding
does, on a different policy block, which is why F3-7's rows carry `grounding[].score`; this
guardrail has no grounding policy.)

That matters two ways, and both are recorded rather than glossed:

  * A 4-level enum is **coarse**. Real per-call score variation that stays inside one
    confidence band is invisible here, so a FALSE verdict is a bound on *reported* variation
    and the underlying score could still wobble. The honest statement is in
    `false_means_what`.
  * "byte-identical in verdict and score" therefore has to be operationalised over what the
    API actually returns. The fingerprint below is that operationalisation, and it is
    deliberately **wider** than the oracle's minimum so a difference cannot hide in a field
    nobody thought to compare.

THE FINGERPRINT, AND THE FIELDS DELIBERATELY EXCLUDED FROM IT
-------------------------------------------------------------
Each trial's decision surface is canonicalised to a sorted JSON string over: the top-level
`action` and `actionReason`, per detected filter `(type, detected, blocked, confidence)`, and
the detected topic / word / PII lists. Included because each is part of "the verdict or the
score".

`filterStrength` is **not** in it, and that is a limit of the arm runner rather than a
judgement: `arms.read_assessment` records `confidences` per detected type but does not carry
`filterStrength` onto the row, so it is not available here. It is also the *configured*
strength echoed back — a constant for a fixed guardrail — so its absence cannot hide a
per-call flip. It is named in `not_fingerprinted_and_why` rather than left as a silent gap,
because the docstring would otherwise claim a comparison the code does not make.

Excluded, each for a stated reason, because a fingerprint that varied for a reason unrelated
to the decision would make TRUE **certain by construction** — the vacuous-test defect this
project screens documents for, pointing at us:

  * `usage` / text-unit counts — identical input, so a difference would be a billing finding
    (F10-2's subject), not a verdict difference. Recorded per trial and compared separately.
  * `guardrailProcessingLatency` — continuous and never repeats. Including it would make
    every run TRUE. Recorded per trial and summarised as a distribution instead.
  * `x-amzn-requestid` — unique by definition.

Every excluded field is still on every row, so the exclusions are auditable and the
comparison can be re-done differently by a reader who disagrees with them.

DISTINCT_AT_LEAST NEEDS FLOATS, SO FINGERPRINTS ARE CODED
---------------------------------------------------------
`oracle._decide`'s DISTINCT_AT_LEAST branch computes `sorted({float(v) for v in
obs.distinct_values})`, so the observation must be numeric. Each unique fingerprint is
assigned a code in first-appearance order (0.0, 1.0, ...) and the codes are what the oracle
counts. The count of distinct codes equals the count of distinct fingerprints exactly — a
bijection, not a hash — and `fingerprint_codebook` in the payload maps every code back to
its full fingerprint so the numbers are traceable to the responses that produced them.

THE INSTRUMENT: A DEDICATED GUARDRAIL AND A SEQUENTIAL ARM
----------------------------------------------------------
The provisioner (`f3_efficacy/00_guardrails.py`) builds a `determinism` guardrail for this
case alone: all five content-filter categories at MEDIUM, actions BLOCK, tier CLASSIC. Its
own guardrail rather than reusing `cf-medium` so that 300 identical calls do not interleave
with the recall arms' traffic — otherwise concurrent load becomes an alternative explanation
for exactly the variation this case attributes to the service. `phase1.run_arms` is
sequential for the same reason.

The probe text must be **near the decision boundary** to have any chance of flipping. An
unambiguously benign string returns NONE every time trivially, and an unambiguously violent
one returns HIGH every time; neither exercises the classifier's uncertainty. The item is
drawn from the sealed `hard_negatives` corpus — benign text that superficially resembles an
attack — because that corpus was built to sit on the boundary and is labelled and κ-scored.
Which item is used is recorded by id and content hash, and a **second** near-boundary item
runs as a small companion arm so a FALSE verdict cannot rest on one text that happened to
land deep inside one band.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R          # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
import stats as S         # noqa: E402
from evidence import EvidenceStore  # noqa: E402

FAMILY = "f2"
CASE = "F2-5"
GUARDRAIL_KEY = "determinism"

# The boundary corpus. Hard negatives are benign texts that superficially resemble attacks,
# so they sit where the classifier is least certain — which is the only place a flip can be
# observed at all.
PROBE_CORPUS = "hard_negatives/hard_negatives.jsonl"

# The main arm repeats ONE item n times; the companion arm repeats a second item a smaller
# number of times. The companion exists so a FALSE verdict is not a statement about one
# string: a single probe that happens to sit deep inside a confidence band would return 300
# identical responses for a reason about that text, not about the service. It is a
# robustness check, NOT part of the sealed n — the oracle is evaluated on the main arm alone,
# and the companion is reported beside it.
COMPANION_N = 30

# Response fields excluded from the fingerprint, each with the reason. Data, not prose, so
# the exclusions travel into the result file and can be checked by a reader.
FINGERPRINT_EXCLUSIONS = {
    "usage / text_units": (
        "identical input, so a difference here is a BILLING finding (F10-2's subject), not "
        "a differing verdict. Recorded per trial and compared separately"),
    "guardrailProcessingLatency": (
        "continuous and essentially never repeats. Including it would make the verdict TRUE "
        "by construction — the vacuous-test defect this project screens for. Recorded per "
        "trial and summarised as a distribution"),
    "x-amzn-requestid": "unique by definition",
    "guardrailCoverage": (
        "a character count over identical input; a difference would be an instrument fault, "
        "and it is checked as one rather than counted as a verdict difference"),
}


def fingerprint(row: dict) -> str:
    """The decision surface of one trial, canonicalised.

    Deliberately WIDER than the oracle's minimum ("verdict or score"): the top-level action
    and reason, plus every detected filter with its action, confidence and filterStrength.
    A narrower fingerprint could miss a difference that is real; a wider one cannot invent
    one, because every field in it is part of the decision.

    `sort_keys` and a sorted filter list because neither the response's key order nor its
    filter order is documented as stable, and an ordering difference is not a verdict
    difference. Sorting is what keeps this from reporting a TRUE about JSON serialisation.
    """
    # Built in sorted-TYPE order rather than by sorting the dicts: dicts do not compare, so
    # `sorted(<generator of dicts>)` raises TypeError on any response with two detected
    # filters — i.e. exactly on the interesting responses, and never on the trivial ones a
    # smoke run would produce.
    filters = [
        {"type": t,
         "detected": True,
         "confidence": row.get("confidences", {}).get(t, ""),
         "blocked": t in (row.get("blocked_types") or [])}
        for t in sorted(row.get("detected_types") or [])
    ]
    payload = {
        "action": row.get("action", ""),
        "action_reason": row.get("action_reason", ""),
        "filters": filters,
        "topics": sorted(row.get("topics_detected") or []),
        "words": sorted(row.get("words_detected") or []),
        "pii": sorted(row.get("pii_detected") or []),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def repeated_items(item: dict, n: int, *, tag: str) -> list[dict]:
    """`n` copies of one item, each with a distinct id.

    The ids must differ even though the texts are identical: `arms.run_arm` skips any trial
    whose id the checkpoint already holds, so 300 copies sharing one id would send **one**
    call and report 300 as done. The case would then confirm determinism from a single
    observation — a FALSE verdict manufactured by the resume logic.

    The id is a content hash over (text, tag, trial index) rather than a bare counter so it
    is stable across resumes and cannot collide with the companion arm's.
    """
    out = []
    for i in range(n):
        seed = f"{item['text']}\x00{tag}\x00{i}"
        out.append({**item,
                    "id": hashlib.sha256(seed.encode()).hexdigest()[:16],
                    "trial_index": i,
                    "arm_tag": tag,
                    "source_item_id": item["id"]})
    return out


def probe_items(n: int | None) -> tuple[dict, dict, int, int]:
    """The two probe texts and the two arm sizes.

    Chosen by position in the sealed corpus, not by content: picking the text that looked
    most likely to flip would be choosing the observation, and the corpus is already
    labelled and kappa-scored for exactly this property.
    """
    corpus = R.load_corpus(PROBE_CORPUS)
    if len(corpus) < 2:
        raise RuntimeError(
            f"{PROBE_CORPUS} holds {len(corpus)} item(s); this case needs two distinct "
            f"near-boundary probes so a FALSE verdict is not a statement about one string")
    want = O.planned_n(CASE) or 300
    main_n = min(n, want) if n else want
    comp_n = min(n, COMPANION_N) if n else COMPANION_N
    return corpus[0], corpus[1], main_n, comp_n


def summarise(rows: list[dict]) -> dict[str, Any]:
    """Fingerprints, codes, and the fields deliberately kept OUT of the fingerprint."""
    fps = [fingerprint(r) for r in rows]
    order: dict[str, float] = {}
    for fp in fps:
        if fp not in order:
            order[fp] = float(len(order))
    codes = [order[fp] for fp in fps]
    counts = Counter(fps)
    lat = [r["guardrail_latency_ms"] for r in rows
           if r.get("guardrail_latency_ms") is not None]
    units = Counter(json.dumps(r.get("text_units") or {}, sort_keys=True) for r in rows)
    cov = Counter(json.dumps(r.get("coverage") or {}, sort_keys=True) for r in rows)
    return {
        "n_rows": len(rows),
        "codes": codes,
        "n_distinct_fingerprints": len(order),
        "fingerprint_codebook": {str(v): k for k, v in order.items()},
        "fingerprint_counts": {str(order[fp]): c for fp, c in counts.items()},
        "bijection_check": {
            "n_distinct_codes": len(set(codes)),
            "n_distinct_fingerprints": len(order),
            "equal": len(set(codes)) == len(order),
            "why": ("the oracle counts distinct FLOATS, so the code assignment must be a "
                    "bijection with the fingerprints — if these differ, the verdict is "
                    "about the coding and not about the service"),
        },
        # The excluded fields, reported so the exclusions are auditable rather than asserted.
        "excluded_from_fingerprint": FINGERPRINT_EXCLUSIONS,
        "latency_ms": {
            "n": len(lat),
            "distinct": len(set(lat)),
            "min": min(lat) if lat else None,
            "p50": statistics.median(lat) if lat else None,
            "max": max(lat) if lat else None,
            "why_excluded": FINGERPRINT_EXCLUSIONS["guardrailProcessingLatency"],
        },
        "text_units_distinct": len(units),
        "text_units_values": dict(units),
        "coverage_distinct": len(cov),
        "instrument_faults": {
            "text_units_varied": len(units) > 1,
            "coverage_varied": len(cov) > 1,
            "why_a_fault": ("the input is byte-identical on every trial, so a varying "
                            "text-unit or coverage count is either a billing finding for "
                            "F10-2 or an instrument fault here — it is NOT a differing "
                            "verdict, and counting it as one would confirm the document "
                            "from an artefact"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    main_item, comp_item, main_n, comp_n = probe_items(args.n)
    want = O.planned_n(CASE)

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            [("repeat-main", f"{PROBE_CORPUS} item 1, repeated", main_n),
             ("repeat-companion", f"{PROBE_CORPUS} item 2, repeated", comp_n)],
            extra=[
                f"guardrail: the provisioner's {GUARDRAIL_KEY!r} key — all five content "
                f"filters at MEDIUM, actions BLOCK, tier CLASSIC. Its OWN guardrail so 300 "
                f"identical calls do not interleave with the recall arms, which would make "
                f"concurrent load an alternative explanation for the variation this case "
                f"attributes to the service",
                f"n={want} is sealed for power, not convenience: P(>=1 flip) = 1-(1-p)^n, so "
                f"n >= ln(beta)/ln(1-p) is 59 for a 5% flip rate and 298 for 1% at 95% "
                f"power. FALSE therefore means 'below ~1% per call', NOT 'deterministic'",
                "TRUE is the EASY direction — one differing response confirms the document "
                "and needs no interval. FALSE requires all 300 identical, and that is the "
                "claim carrying the power argument",
                "verdict/score is operationalised as a canonical fingerprint over action, "
                "actionReason and per-filter (type, detected, action, confidence). "
                "`confidence` and `filterStrength` are 4-VALUE ENUMS (NONE/LOW/MEDIUM/HIGH) "
                "on this API, not continuous scores — content filters expose no numeric "
                "score, so a FALSE verdict bounds REPORTED variation only",
                "latency, usage/text units, coverage and the request id are deliberately "
                "EXCLUDED from the fingerprint and recorded separately: latency never "
                "repeats, so including it would make TRUE certain by construction",
                f"the companion arm ({comp_n} calls on a second near-boundary text) is a "
                f"robustness check reported BESIDE the verdict, not part of the sealed n — "
                f"the oracle is evaluated on the main arm alone",
                "probes come from the sealed hard_negatives corpus by POSITION, not by "
                "content: choosing the text most likely to flip would be choosing the "
                "observation",
                "this case tests ONE premise of the §3.3 sentence. Auto-updated models, "
                "'similar inputs', and the cache advice itself are not measured here and "
                "are named in the payload",
            ])

    run_id = P.resolve_run(args)
    man = P.manifest()
    is_smoke = args.n is not None
    gid = P.guardrail(GUARDRAIL_KEY, man=man)

    specs = [
        R.ArmSpec(case_id=CASE, family=FAMILY, corpus=f"{PROBE_CORPUS}#1",
                  guardrail_id=gid, region=args.region, label="repeat-main",
                  # `hit` is irrelevant to this case's oracle — it counts DISTINCT
                  # responses, not detections — but a tally with a meaningless `x` invites
                  # misreading, so it is set to the item's own label and named in the
                  # payload as unused.
                  hit=R.any_detection),
        R.ArmSpec(case_id=CASE, family=FAMILY, corpus=f"{PROBE_CORPUS}#2",
                  guardrail_id=gid, region=args.region, label="repeat-companion",
                  hit=R.any_detection),
    ]
    corpora = [repeated_items(main_item, main_n, tag="main"),
               repeated_items(comp_item, comp_n, tag="companion")]

    tallies = P.run_arms(specs, corpora, run_id=run_id, is_smoke=is_smoke)
    rc = P.require_measured(tallies, is_smoke=is_smoke)
    if rc:
        return rc

    main_t, comp_t = tallies[0], tallies[1]
    main_s = summarise(main_t["rows"])
    comp_s = summarise(comp_t["rows"])

    if not main_s["bijection_check"]["equal"]:
        # Cannot happen with first-appearance coding, and asserted anyway: if it ever did,
        # the verdict would be about the coding rather than about the service.
        rec = O.not_measured(
            CASE,
            "the fingerprint-to-code mapping is not a bijection, so the oracle's distinct "
            "count would be a property of the coding rather than of the responses",
            bijection=main_s["bijection_check"])
        P.emit(CASE, rec, {"run_id": run_id, "is_smoke": is_smoke,
                           "main_arm": main_s,
                           "billable_calls": sum(t["n_usable"] for t in tallies),
                           "mutations": 0}, EvidenceStore(run_id, FAMILY, CASE))
        return 2

    o = P.obs_distinct(
        CASE, main_s["codes"], main_t["n_usable"],
        n_distinct=main_s["n_distinct_fingerprints"],
        fingerprint_counts=main_s["fingerprint_counts"],
        probe_item_id=main_item["id"],
        probe_sha256=hashlib.sha256(main_item["text"].encode()).hexdigest(),
        companion_n_distinct=comp_s["n_distinct_fingerprints"])
    rec = O.evaluate(o)

    # The bound a FALSE verdict is entitled to, computed rather than described. Reported in
    # BOTH directions so the number is present whichever way the verdict lands.
    ceiling = O.ceiling_at_zero(main_t["n_usable"], O.alpha_for(CASE)) \
        if main_t["n_usable"] else None
    # The sealed n, recomputed from the power formula rather than quoted. If `stats` and the
    # pre-registration ever disagreed about what 300 buys, this is where it would show.
    n_for_1pct = S.required_n_for_zero_events(0.01, 0.95)
    n_for_5pct = S.required_n_for_zero_events(0.05, 0.95)

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "billable_calls": sum(t["n_usable"] for t in tallies),
        "mutations": 0,
        "guardrail": {"key": GUARDRAIL_KEY, "id": gid,
                      "config": ("all five content filters at MEDIUM, actions BLOCK, tier "
                                 "CLASSIC — the provisioner's dedicated determinism "
                                 "guardrail"),
                      "why_dedicated": ("300 identical calls against a shared guardrail "
                                        "would interleave with the recall arms' traffic, "
                                        "and concurrent load would become an alternative "
                                        "explanation for the variation this case "
                                        "attributes to the service")},
        "probe": {"corpus": PROBE_CORPUS,
                  "main_item_id": main_item["id"],
                  "main_label": main_item.get("label", ""),
                  "main_sha256": hashlib.sha256(main_item["text"].encode()).hexdigest(),
                  "companion_item_id": comp_item["id"],
                  "companion_sha256":
                      hashlib.sha256(comp_item["text"].encode()).hexdigest(),
                  "why_hard_negatives": ("benign text that superficially resembles an "
                                         "attack sits where the classifier is least "
                                         "certain, which is the only place a flip can be "
                                         "observed. An unambiguous input returns the same "
                                         "answer trivially and would confirm determinism "
                                         "from a property of the text"),
                  "selection_rule": ("by POSITION in the sealed corpus, not by content: "
                                     "picking the text most likely to flip would be "
                                     "choosing the observation")},
        "main_arm": main_s,
        "companion_arm": {**comp_s, "role": (
            f"robustness check on a SECOND near-boundary text, n={comp_n}. Reported beside "
            f"the verdict and NOT part of the sealed n — the oracle is evaluated on the "
            f"main arm alone. Its purpose is that a FALSE verdict not rest on one string "
            f"that happened to sit deep inside a confidence band")},
        "arm_tallies": [{k: v for k, v in t.items() if k != "rows"} for t in tallies],
        "x_is_unused": ("the tallies' `x` counts detections, which this case's oracle does "
                        "not read — it counts DISTINCT responses. Reported for completeness "
                        "and not used in the verdict"),
        "verdict_rule": (
            f"TRUE iff the main arm produced >= 2 distinct fingerprints in "
            f"{main_t['n_usable']} identical calls. One differing response suffices, so no "
            f"interval is computed for TRUE"),
        "false_means_what": (
            f"a FALSE verdict means all {main_t['n_usable']} responses were identical, which "
            f"bounds the per-call flip rate at approximately "
            f"{ceiling if ceiling is None else round(ceiling, 5)} (one-sided "
            f"{1 - O.alpha_for(CASE):.0%} rule-of-three ceiling at zero events). It does "
            f"NOT mean the service is deterministic, and it bounds only REPORTED variation: "
            f"`confidence` and `filterStrength` are 4-value enums, so score movement inside "
            f"one band is invisible to this instrument"),
        "flip_rate_ceiling_at_zero": ceiling,
        "power_argument": {
            "form": "P(>=1 flip in n) = 1 - (1 - p)^n, so n >= ln(beta) / ln(1 - p)",
            "sealed_n": want,
            "n_for_1pct_at_95pct_power": n_for_1pct,
            "n_for_5pct_at_95pct_power": n_for_5pct,
            "sealed_n_suffices_for_1pct": want is not None and want >= n_for_1pct,
            "recomputed_not_quoted": (
                "these come from stats.required_n_for_zero_events, not from the "
                "pre-registration's prose. A number in a justification string is unchecked "
                "(feedback_prose_is_not_verified), so the claim 'n=300 gives 95% power "
                "against 1%' is recomputed here and would disagree visibly if it were "
                "wrong"),
            "reading": (f"n={want} gives 95% power against a 1%-per-call flip rate "
                        f"(n>={n_for_1pct} required); the sealed n is the reason a FALSE "
                        f"verdict is a BOUND rather than an absence"),
        },
        "not_fingerprinted_and_why": {
            "filterStrength": (
                "arms.read_assessment does not carry it onto the row, so it is not available "
                "here. It is also the CONFIGURED strength echoed back — a constant for a "
                "fixed guardrail — so its absence cannot hide a per-call flip. Named rather "
                "than left silent, because a docstring claiming a comparison the code does "
                "not make is the label-vs-computation defect this project screens for"),
            "grounding scores": (
                "the only numeric per-call score ApplyGuardrail returns, and this guardrail "
                "has no contextual-grounding policy, so there is none to compare. F3-7 is "
                "where that surface is measured"),
        },
        "score_surface_caveat": (
            "measured against the 1.43.67 model: ApplyGuardrail's contentPolicy filters "
            "expose ['type','confidence','filterStrength','action','detected'], and both "
            "`confidence` and `filterStrength` are 4-value enums NONE/LOW/MEDIUM/HIGH. "
            "Content filters return no numeric score on this API. Contextual grounding "
            "does, on a different policy block, and this guardrail has no grounding policy"),
        "what_true_does_not_prove": (
            "§3.3 item 1 bundles several claims and this oracle takes one — that guardrail "
            "evaluation is non-deterministic. It does NOT establish that AWS auto-updates "
            "the underlying models (unfalsifiable in a 300-call window; F3-11's +7d/+30d "
            "re-runs are the nearest instrument), nor that 'similar' inputs differ exactly "
            "in the attack payload (a property of inputs — F3-3's subject), nor the cache "
            "advice itself, which is NORMATIVE: a deterministic service with auto-updated "
            "models would justify the same recommendation, and no experiment makes a "
            "recommendation true"),
        "relation_to_f2_1_to_f2_4": (
            "F2-1..F2-4 (Phase 4) ask the harder question this case does not: whether the "
            "POLICY is a deterministic function of a non-deterministic guardrail score, via "
            "stratum purity and the variance decomposition. F2-5 measures only the input "
            "side of that model — whether the guardrail's own output varies at all"),
        "instrument": "ApplyGuardrail (source=INPUT, outputScope=FULL), sequential",
    }, EvidenceStore(run_id, FAMILY, CASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
