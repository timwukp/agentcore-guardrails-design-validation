#!/usr/bin/env python3
"""F3-6: is the custom word filter exact-match, as the document says?

    python3 f3_efficacy/05_words.py --dry-run
    python3 f3_efficacy/05_words.py --n 3
    python3 f3_efficacy/05_words.py

TWO ADVERSE POPULATIONS, ONE ZERO-EVENT ORACLE
----------------------------------------------
"TRUE if every listed term blocks and no unlisted near-miss does; FALSE on any miss or
any near-miss block." The adverse count is a **union over two different populations**:

  * a LISTED item that did NOT block  — the filter missed a term it was given
  * a NEAR_MISS item that DID block   — the filter matched something it was not given

That is why `phase1.obs_zero_events` takes `n` explicitly rather than deriving it from a
tally: neither arm's own count is the denominator the ceiling should be reported against.
The ceiling is denominated in the union, because the claim under test ("exactly") is a
claim about both directions at once and a ceiling computed on one arm would understate the
number of chances the filter had to break it.

THE NEAR-MISSES ARE THE LOAD-BEARING HALF
-----------------------------------------
Three listed terms (`moonquake`, `zorbify`, `quaxlinate`) with nine listed items would let
a substring or stem matcher score a clean 3/3 and pass. The 54 near-misses are what make
"exactly" falsifiable: suffixes (`moonquakes`), truncations (`moonquak`), prefixes
(`premoonquake`), one-character edits (`moonquake` -> `moonqake`) and splits
(`moon quake`). A block on any of them is CORRECT behaviour for a stem matcher and
INCORRECT behaviour for an exact matcher, and the document claims the latter.

`LISTED_CASE` items (3) are a separate label on purpose: `Moonquake` differs from
`moonquake` only in case, and a case-insensitive matcher is still matching *the listed
word*. Counting them as near-misses would score standard case-folding as a violation of
exact matching, which would be a finding about our labels rather than about the service.
They are scored **as listed** — expected to block — and reported as their own row so a
reader can see the assumption and disagree with it.

NO PRE-REGISTERED n
-------------------
`planned_n('F3-6')` is None; `n_met` is vacuous and no power claim is available.
The corpus lives in `corpora_deviation/` (DEVIATIONS.md/DEV-P1-4). Unlike a rate cell,
that costs less here: a zero-event oracle over a union of 66 trials still carries an exact
one-sided ceiling of 1 - 0.05^(1/66) ~= 4.4%, and one counterexample decides the case
outright regardless of n.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R          # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
from evidence import EvidenceStore  # noqa: E402

FAMILY = "f3"
CASE = "F3-6"
DEV_ROOT = ROOT / "corpora_deviation"
PROBE = "word_probe/probe.jsonl"

# Labels expected to BLOCK, and labels expected NOT to. `LISTED_CASE` is on the blocking
# side; see the module docstring on why case-folding is not a near-miss.
EXPECT_BLOCK = ("LISTED", "LISTED_CASE")
EXPECT_CLEAR = ("NEAR_MISS",)


def plan(n: int | None) -> list[tuple[str, str, int]]:
    return [("word-probe", PROBE, len(R.load_corpus(PROBE, limit=n, root=DEV_ROOT)))]


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        items = R.load_corpus(PROBE, limit=args.n, root=DEV_ROOT)
        counts = {k: sum(1 for it in items if it["label"] == k)
                  for k in EXPECT_BLOCK + EXPECT_CLEAR}
        return P.dry_run_banner(
            CASE, plan(args.n),
            extra=[f"label mix: {counts}",
                   f"expected to block: {list(EXPECT_BLOCK)}   "
                   f"expected to clear: {list(EXPECT_CLEAR)}",
                   "the adverse count is the UNION of listed-misses and near-miss blocks, "
                   "and the ceiling is denominated in that union",
                   "corpus lives in corpora_deviation/ — not pre-registered, n_met "
                   "vacuous (DEVIATIONS.md/DEV-P1-4)"])

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid = P.guardrail("words", man=man)
    words = P.configured_words(man)
    is_smoke = args.n is not None
    print(f"\nword filter {words} (guardrail {gid})")

    items = R.load_corpus(PROBE, limit=args.n, root=DEV_ROOT)
    spec = R.ArmSpec(case_id=CASE, family=FAMILY, corpus=PROBE, guardrail_id=gid,
                     region=args.region, label="word-probe", hit=P.hit_word)
    t = P.run_arms([spec], [items], run_id=run_id, is_smoke=is_smoke)[0]

    rc = P.require_measured([t], is_smoke=is_smoke)
    if rc:
        return rc

    by_label = P.label_counts(t["rows"], EXPECT_BLOCK + EXPECT_CLEAR)

    # The two adverse populations, counted separately and then unioned. Kept apart in the
    # output because they falsify different halves of "exactly": a miss says the filter is
    # weaker than the list, a near-miss block says it is broader.
    listed_misses = [r for r in t["rows"]
                     if r["label"] in EXPECT_BLOCK and not r["hit"]]
    nearmiss_blocks = [r for r in t["rows"]
                       if r["label"] in EXPECT_CLEAR and r["hit"]]
    adverse = len(listed_misses) + len(nearmiss_blocks)
    union_n = sum(by_label[k]["n"] for k in EXPECT_BLOCK + EXPECT_CLEAR)

    o = P.obs_zero_events(CASE, adverse, union_n,
                          listed_misses=len(listed_misses),
                          nearmiss_blocks=len(nearmiss_blocks))
    rec = O.evaluate(o)

    # What the service reported as the match, per adverse item. This is the field that
    # says WHICH rule the filter is using: a near-miss block reporting `moonquake` as the
    # match means stemming, and one reporting the near-miss text itself means the list was
    # not what we provisioned.
    def detail(rows):
        return [{"item_id": r["item_id"], "label": r["label"], "slot": r["slot"],
                 "surface": r["surface"], "words_detected": r["words_detected"],
                 "action": r["action"], "request_id": r["request_id"]} for r in rows]

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "configured_words": words,
        "billable_calls": t["n_usable"], "mutations": 0,
        "by_label": by_label,
        "adverse_union": {"total": adverse, "n": union_n,
                          "listed_misses": len(listed_misses),
                          "nearmiss_blocks": len(nearmiss_blocks),
                          "why_union": ("the claim is 'exactly', which is a claim about "
                                        "both directions; a ceiling on one arm alone "
                                        "would understate the chances the filter had")},
        "listed_misses_detail": detail(listed_misses),
        "nearmiss_blocks_detail": detail(nearmiss_blocks),
        "case_folding_assumption": (
            "LISTED_CASE items differ from a listed term only in case and are scored as "
            "EXPECTED TO BLOCK; a case-insensitive matcher is still matching the listed "
            "word. Reported as its own row so the assumption is visible and contestable"),
        "surfaces_probed": sorted({r["surface"] for r in t["rows"]}),
        "no_power_claim": (f"planned_n({CASE}) is None, so n_met={rec['n_met']} is "
                           f"vacuous. A zero-event oracle still carries an exact one-sided "
                           f"ceiling at this n, and one counterexample decides the case "
                           f"regardless of n"),
        "corpus_root": "corpora_deviation (unsealed; DEVIATIONS.md/DEV-P1-4)",
        "instrument": "ApplyGuardrail (source=INPUT, outputScope=FULL), wordPolicy",
    }, EvidenceStore(run_id, FAMILY, CASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
