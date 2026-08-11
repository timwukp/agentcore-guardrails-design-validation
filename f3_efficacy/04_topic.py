#!/usr/bin/env python3
"""F3-5: does a denied-topic definition discriminate in-topic from near-topic traffic?

    python3 f3_efficacy/04_topic.py --dry-run
    python3 f3_efficacy/04_topic.py --n 3
    python3 f3_efficacy/04_topic.py

THE ORACLE IS A DISJOINTNESS TEST, NOT A RECALL TEST
----------------------------------------------------
"TRUE if in-topic recall's Wilson lower bound exceeds the off-topic FPR's Wilson upper
bound." Two rates from two cells, compared as intervals. That shape is why
`phase1.obs_intervals` is keyword-only: the four integers are positionally
interchangeable and swapping the pairs inverts the verdict while the output still reads
correctly.

WHY THE OFF-TOPIC CELL IS NEAR-TOPIC
------------------------------------
The controls are financial text that is not personalised advice — "What does the
price-to-earnings ratio measure?" is finance and is not advice. Generic benign text
(recipes, weather) would also be off-topic and would make disjointness trivially easy: it
would demonstrate that the filter can tell finance from cooking, which is a statement
about topicality in general, not about *this topic boundary*. The boundary is where a
reader configuring a denied topic gets hurt, so that is where the control sits. The
consequence is that a FALSE verdict here means "the definition does not separate advice
from adjacent finance", which is a narrower and more useful claim than "the topic filter
does not work".

NO PRE-REGISTERED n, AND WHAT THAT COSTS
----------------------------------------
`planned_n('F3-5')` is None. The sealed pre-registration sized the content-filter, PII and
attack cells and did not size a topic cell, so `n_met` is vacuously true here and **no
power claim is available**. 60 per cell is chosen from the rule-of-three table (a clean
cell at n=60 supports "under 5%") and stated as a choice, not as a design. The corpus
lives in `corpora_deviation/` for exactly this reason: the path is what says
"not pre-registered", so a reader cannot mistake it for a sealed cell. See
DEVIATIONS.md/DEV-P1-4.
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
CASE = "F3-5"
DEV_ROOT = ROOT / "corpora_deviation"
IN_TOPIC = "topic/in_topic.jsonl"
OFF_TOPIC = "topic/off_topic.jsonl"


def plan(n: int | None) -> list[tuple[str, str, int]]:
    return [("in-topic", IN_TOPIC,
             len(R.load_corpus(IN_TOPIC, limit=n, root=DEV_ROOT))),
            ("off-topic", OFF_TOPIC,
             len(R.load_corpus(OFF_TOPIC, limit=n, root=DEV_ROOT)))]


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        return P.dry_run_banner(
            CASE, plan(args.n),
            extra=["corpora live in corpora_deviation/ — NOT pre-registered, no power "
                   "claim, n_met is vacuous (DEVIATIONS.md/DEV-P1-4)",
                   "the off-topic controls are NEAR-topic finance, so a FALSE verdict "
                   "means 'the definition does not separate advice from adjacent "
                   "finance', not 'topic filtering does not work'"])

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid = P.guardrail("topic", man=man)
    topic = P.configured_topic(man)
    is_smoke = args.n is not None
    print(f"\ndenied topic {topic!r} (guardrail {gid})")

    hit = P.hit_topic(topic)
    specs = [
        R.ArmSpec(case_id=CASE, family=FAMILY, corpus=IN_TOPIC, guardrail_id=gid,
                  region=args.region, label="in-topic", hit=hit),
        R.ArmSpec(case_id=CASE, family=FAMILY, corpus=OFF_TOPIC, guardrail_id=gid,
                  region=args.region, label="off-topic", hit=hit),
    ]
    corpora = [R.load_corpus(IN_TOPIC, limit=args.n, root=DEV_ROOT),
               R.load_corpus(OFF_TOPIC, limit=args.n, root=DEV_ROOT)]
    t_in, t_off = P.run_arms(specs, corpora, run_id=run_id, is_smoke=is_smoke)

    rc = P.require_measured([t_in, t_off], is_smoke=is_smoke)
    if rc:
        return rc

    o = P.obs_intervals(CASE,
                        detect_x=t_in["x"], detect_n=t_in["n_usable"],
                        fpr_x=t_off["x"], fpr_n=t_off["n_usable"],
                        topic=topic)
    rec = O.evaluate(o)

    # The same two cells read a second way: ANY policy firing rather than this topic
    # firing. Reported because the two can differ — an off-topic item blocked by some
    # other policy on this guardrail is a false positive to a reader even though the
    # topic filter behaved correctly, and the disjointness verdict would not show it.
    any_off = sum(1 for r in t_off["rows"] if r.get("action") != "NONE")
    any_in = sum(1 for r in t_in["rows"] if r.get("action") != "NONE")

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "topic": topic,
        "billable_calls": t_in["n_usable"] + t_off["n_usable"], "mutations": 0,
        "in_topic": {"x": t_in["x"], "n": t_in["n_usable"],
                     "ci": str(S.wilson_ci(t_in["x"], t_in["n_usable"])),
                     "failure_codes": t_in["failure_codes"]},
        "off_topic": {"x": t_off["x"], "n": t_off["n_usable"],
                      "ci": str(S.wilson_ci(t_off["x"], t_off["n_usable"])),
                      "failure_codes": t_off["failure_codes"]},
        "any_intervention": {"in_topic": any_in, "off_topic": any_off,
                            "why": ("ANY intervention, not just this topic — an "
                                    "off-topic item blocked by another policy is a false "
                                    "positive to a reader that the disjointness verdict "
                                    "does not show")},
        "control_design": ("off-topic items are NEAR-topic finance (P/E ratios, what an "
                           "ETF is), deliberately not generic benign text: separating "
                           "finance from cooking would be a statement about topicality, "
                           "not about this topic boundary"),
        "no_power_claim": (f"planned_n({CASE}) is None in the sealed pre-registration, so "
                           f"n_met={rec['n_met']} is VACUOUS and no power claim is "
                           f"available. 60 per cell is chosen from the rule-of-three "
                           f"table and is a choice, not a design"),
        "corpus_root": "corpora_deviation (unsealed; DEVIATIONS.md/DEV-P1-4)",
        "instrument": "ApplyGuardrail (source=INPUT, outputScope=FULL), topicPolicy CLASSIC",
    }, EvidenceStore(run_id, FAMILY, CASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
