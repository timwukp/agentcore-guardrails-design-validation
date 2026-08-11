#!/usr/bin/env python3
"""F3-7: can contextual grounding tell a grounded response from an ungrounded one?

    python3 f3_efficacy/06_grounding.py --dry-run
    python3 f3_efficacy/06_grounding.py --n 3
    python3 f3_efficacy/06_grounding.py

THREE BLOCKS IN ONE REQUEST, AND WHY A QUALIFIER TUPLE CANNOT EXPRESS IT
-----------------------------------------------------------------------
Verified against the 1.43.67 service model (and 1.42.79 — both agree): `content` is a list
of blocks, each `{text: {text: <required string>, qualifiers: [...]}}`, with the qualifier
enum `['grounding_source', 'query', 'guard_content']`. The grounding filter scores the
**untagged** block against the tagged source and query, so one request must carry three
blocks:

    grounding_source : the passage
    query            : the question
    (untagged)       : the candidate response — the thing being scored

`ArmSpec.qualifiers` tags a single block and cannot express that. Worse, it fails
*quietly*: an arm that sent only the source would get `action=NONE` with nothing scored,
which is byte-indistinguishable in the response from "the response was grounded". So
`ArmSpec.multi_block` builds the list from the item's own fields, and `arms.run_arm` raises
if an arm sets both — the first tags one block, the second builds the whole list, and
honouring both would silently drop one.

AND `source="OUTPUT"`, WHICH THE THREE BLOCKS DO NOT IMPLY
---------------------------------------------------------
Getting the block list right is necessary and not sufficient. Grounding scores a *response*,
so the request must also be addressed to the OUTPUT side. Measured on the live service
(2026-08-10, us-east-1) with the same three blocks and the same guardrail, only `source`
differing:

    source=INPUT   -> 200, action=NONE,                 no contextualGroundingPolicy block
    source=OUTPUT  -> 200, action=GUARDRAIL_INTERVENED,  GROUNDING score=0.0 BLOCKED

The first live run of this case used the `ArmSpec` default, `INPUT`. All 120 trials
succeeded, `blocks_per_trial` read `[3]`, both arms reported x=0, and the case published
`FALSE` — "contextual grounding cannot tell grounded from ungrounded" — as a refutation of
the document, from a filter that had never executed. Nothing in the response said so: the
absence of a policy block is how the API reports "this guardrail has no such policy", which
is a legitimate configuration, so the flattener was right to tolerate it and the *reader*
was wrong to score it (DEVIATIONS.md/DEV-P1-18).

Both arms therefore set `require_policy="contextualGroundingPolicy"`. That is sound only
because the block is returned even when the filter does not fire — verified on a grounded
item: `GROUNDING score=1.0 detected=false`, block present. So absence means "did not run",
never "did not fire", and an absent block is recorded as a failed trial rather than a
negative.

GROUNDING AND RELEVANCE ARE READ SEPARATELY
-------------------------------------------
The guardrail configures both filters at 0.7. They answer different questions: GROUNDING
scores the response against the source, RELEVANCE scores it against the query. F3-7's
oracle is about grounding, so `phase1.hit_grounding('GROUNDING')` names the filter — and
the RELEVANCE rate is reported beside it. Without that split, an ungrounded response that
happened to be off-topic could be counted as grounding detection when the block actually
came from relevance, and the case would report discrimination the grounding filter never
performed.

WHAT THE PAIRING BUYS, AND WHAT IT DOES NOT
-------------------------------------------
Every item carries a `pair_id`: the two arms share the same source and the same query and
differ **only** in the response. The ungrounded responses contradict or add to the source
(`-40C to 85C` where the source says `-10C to 45C`) rather than being nonsense, because
garbled text would trip RELEVANCE and the arm would report grounding detection it never
measured.

The limitation is real and is on the face of the output: the 60 items per cell are built
from 12 source/query units x 5 response surfaces, so they are **12 content units, not 60
independent observations**. The Wilson intervals the oracle compares are computed at n=60
and are therefore narrower than 12 independent units would justify. That is one more reason
this case carries no power claim — `planned_n('F3-7')` is None (DEVIATIONS.md/DEV-P1-4).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R          # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
import stats as S         # noqa: E402
from evidence import EvidenceStore  # noqa: E402

FAMILY = "f3"
CASE = "F3-7"
DEV_ROOT = ROOT / "corpora_deviation"
GROUNDED = "grounding/grounded.jsonl"
UNGROUNDED = "grounding/ungrounded.jsonl"


def three_blocks(item: dict) -> list[dict]:
    """source (tagged grounding_source) + query (tagged query) + response (untagged).

    Indexes the item's fields directly rather than using `.get`, so an item missing
    `grounding_source` or `query` raises here instead of producing a request the service
    accepts and scores against nothing.
    """
    return [
        {"text": {"text": item["grounding_source"], "qualifiers": ["grounding_source"]}},
        {"text": {"text": item["query"], "qualifiers": ["query"]}},
        {"text": {"text": item["text"]}},
    ]


def plan(n: int | None) -> list[tuple[str, str, int]]:
    return [("ungrounded", UNGROUNDED,
             len(R.load_corpus(UNGROUNDED, limit=n, root=DEV_ROOT))),
            ("grounded", GROUNDED,
             len(R.load_corpus(GROUNDED, limit=n, root=DEV_ROOT)))]


def content_units(items) -> int:
    """Distinct (source, query) pairs — the number of independent stimuli, not items."""
    return len({(it["grounding_source"], it["query"]) for it in items})


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        ung = R.load_corpus(UNGROUNDED, limit=args.n, root=DEV_ROOT)
        return P.dry_run_banner(
            CASE, plan(args.n), blocks_per_call=3,
            extra=[f"each trial sends 3 content blocks (source, query, response)",
                   f"{len(ung)} ungrounded items are built from {content_units(ung)} "
                   f"(source, query) units — the interval at n={len(ung)} is narrower "
                   f"than independent units would justify",
                   "GROUNDING and RELEVANCE are read separately; the oracle is about "
                   "GROUNDING",
                   "corpus lives in corpora_deviation/ — not pre-registered, n_met "
                   "vacuous (DEVIATIONS.md/DEV-P1-4)"])

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid = P.guardrail("grounding", man=man)
    is_smoke = args.n is not None
    print(f"\ncontextual grounding at 0.7 (guardrail {gid})")

    hit = P.hit_grounding("GROUNDING")
    # `source="OUTPUT"`, and it is not a detail. Contextual grounding scores a RESPONSE, and
    # at `source="INPUT"` — the ArmSpec default — the service accepts the three-block
    # request, bills it, returns 200 with `action="NONE"`, and simply omits
    # `contextualGroundingPolicy` from the assessment. No error. The first live run of this
    # case did exactly that for all 120 trials and published `FALSE` — a refutation of the
    # document — from a filter that had never executed (DEVIATIONS.md/DEV-P1-18).
    #
    # `require_policy` is the guard that makes the mistake un-repeatable: the block is
    # returned on a grounded response too (score 1.0, detected false, measured), so its
    # absence means the filter did not run and the trial is a FAILURE rather than a negative.
    specs = [
        R.ArmSpec(case_id=CASE, family=FAMILY, corpus=UNGROUNDED, guardrail_id=gid,
                  region=args.region, label="ungrounded", source="OUTPUT",
                  require_policy="contextualGroundingPolicy",
                  multi_block=three_blocks, hit=hit),
        R.ArmSpec(case_id=CASE, family=FAMILY, corpus=GROUNDED, guardrail_id=gid,
                  region=args.region, label="grounded", source="OUTPUT",
                  require_policy="contextualGroundingPolicy",
                  multi_block=three_blocks, hit=hit),
    ]
    ung_items = R.load_corpus(UNGROUNDED, limit=args.n, root=DEV_ROOT)
    gr_items = R.load_corpus(GROUNDED, limit=args.n, root=DEV_ROOT)
    t_ung, t_gr = P.run_arms(specs, [ung_items, gr_items],
                             run_id=run_id, is_smoke=is_smoke)

    rc = P.require_measured([t_ung, t_gr], is_smoke=is_smoke)
    if rc:
        return rc

    # Detection is on the UNGROUNDED arm; the false-positive term is the grounded arm.
    # Keyword-only by design — see phase1.obs_intervals on why a transposition here would
    # publish an inverted verdict that still reads correctly.
    o = P.obs_intervals(CASE,
                        detect_x=t_ung["x"], detect_n=t_ung["n_usable"],
                        fpr_x=t_gr["x"], fpr_n=t_gr["n_usable"])
    rec = O.evaluate(o)

    def relevance_rate(t):
        return sum(1 for r in t["rows"]
                   if any(g.get("detected") and g.get("type") == "RELEVANCE"
                          for g in (r.get("grounding") or [])))

    def scores(t, kind):
        return [g["score"] for r in t["rows"] for g in (r.get("grounding") or [])
                if g.get("type") == kind and g.get("score") is not None]

    ung_scores = scores(t_ung, "GROUNDING")
    gr_scores = scores(t_gr, "GROUNDING")

    # The per-trial block count, asserted rather than assumed. `arms.run_arm` records
    # `n_blocks` per row precisely so a three-block request cannot be reported as a
    # one-block one; if the multi_block hook were bypassed the scores above would be
    # empty and the rates would both read 0, which is a passing-looking FALSE.
    blocks_seen = sorted({r.get("n_blocks") for r in t_ung["rows"] + t_gr["rows"]})

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "billable_calls": t_ung["n_usable"] + t_gr["n_usable"],
        "text_units_note": ("each trial sends 3 blocks; `text_units` on each row is the "
                            "service's own count and is what F10-2 cross-checks"),
        "mutations": 0,
        "ungrounded": {"x": t_ung["x"], "n": t_ung["n_usable"],
                       "ci": str(S.wilson_ci(t_ung["x"], t_ung["n_usable"])),
                       "failure_codes": t_ung["failure_codes"]},
        "grounded": {"x": t_gr["x"], "n": t_gr["n_usable"],
                     "ci": str(S.wilson_ci(t_gr["x"], t_gr["n_usable"])),
                     "failure_codes": t_gr["failure_codes"]},
        "relevance_detections": {"ungrounded": relevance_rate(t_ung),
                                 "grounded": relevance_rate(t_gr),
                                 "why_separate": ("RELEVANCE scores the response against "
                                                  "the QUERY, GROUNDING against the "
                                                  "SOURCE; pooling them would let a "
                                                  "relevance block be reported as "
                                                  "grounding discrimination")},
        "grounding_score_summary": {
            "ungrounded": {"n": len(ung_scores),
                           "p50": S.quantile(ung_scores, 0.5) if ung_scores else None,
                           "min": min(ung_scores) if ung_scores else None,
                           "max": max(ung_scores) if ung_scores else None},
            "grounded": {"n": len(gr_scores),
                         "p50": S.quantile(gr_scores, 0.5) if gr_scores else None,
                         "min": min(gr_scores) if gr_scores else None,
                         "max": max(gr_scores) if gr_scores else None},
            "threshold": 0.7,
            "why": ("the scores are the continuous quantity behind the 0.7 threshold; a "
                    "verdict pair with overlapping score ranges says something different "
                    "from one with separated ranges and the same block/no-block counts")},
        "blocks_per_trial": blocks_seen,
        "correlated_observations": {
            "items_per_cell": {"ungrounded": t_ung["n_usable"], "grounded": t_gr["n_usable"]},
            "content_units": {"ungrounded": content_units(ung_items),
                              "grounded": content_units(gr_items)},
            "consequence": ("the items are built from (source, query) units x response "
                            "surfaces, so they are NOT independent observations; the "
                            "Wilson intervals the oracle compares are computed at the "
                            "item count and are narrower than the unit count would "
                            "justify")},
        "pairing": ("the two arms share pair_id, source and query and differ only in the "
                    "response; ungrounded responses CONTRADICT the source rather than "
                    "being nonsense, since garbled text would trip RELEVANCE and this arm "
                    "would report grounding detection it never measured"),
        "no_power_claim": (f"planned_n({CASE}) is None, so n_met={rec['n_met']} is "
                           f"vacuous; combined with the correlated observations above, no "
                           f"power claim is available"),
        "corpus_root": "corpora_deviation (unsealed; DEVIATIONS.md/DEV-P1-4)",
        "instrument": ("ApplyGuardrail (source=OUTPUT, outputScope=FULL), 3 content blocks: "
                       "grounding_source + query + untagged response"),
        "source_is_output": ("contextual grounding scores a RESPONSE. At source=INPUT the "
                             "service returns 200 / action=NONE and OMITS "
                             "contextualGroundingPolicy entirely — no error — so the first "
                             "run of this case published FALSE from 120 trials in which the "
                             "filter never executed (DEVIATIONS.md/DEV-P1-18). Every trial "
                             "here carries require_policy=contextualGroundingPolicy, so an "
                             "absent block is a failed trial and not a negative"),
    }, EvidenceStore(run_id, FAMILY, CASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
