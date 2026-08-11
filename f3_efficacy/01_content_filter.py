#!/usr/bin/env python3
"""F3-1, F3-2, F3-3 and F3-9: content-filter recall, FPR, hard negatives, and the ROC.

    python3 f3_efficacy/01_content_filter.py --dry-run
    python3 f3_efficacy/01_content_filter.py --n 3        # smoke
    python3 f3_efficacy/01_content_filter.py              # full

WHY FOUR CASES IN ONE SCRIPT
----------------------------
They are four questions about **one** set of measurements. F3-1 needs recall at the
recommended threshold, F3-2 the benign FPR at the same threshold, F3-3 the hard-negative
FPR, and F3-9 the whole (FPR, TPR) lattice — and F3-9's lattice *contains* F3-1's and
F3-2's operating point. Running them as four scripts would send the benign corpus through
the MEDIUM guardrail twice: once for F3-2's FPR and once as F3-9's MEDIUM vertex. Two
measurements of the same quantity that disagree (and they can — the service is
non-deterministic, which is F2-5's subject) would put two different numbers for one
operating point into the report with no principled way to choose.

So the arms are run once and read four times. The consequence is stated where it
matters: **F3-1, F3-2 and F3-9 are not independent tests.** The F3 family's BH
correction (`lib/oracle.apply_family_corrections`) treats them as separate members,
which is conservative for FDR purposes but does not make them independent evidence, and
the report says so rather than letting four verdicts over shared data read as four
confirmations.

THE RECOMMENDED THRESHOLD
-------------------------
F3-1/F3-2/F3-3's oracles all say "at the recommended threshold" without naming it. The
document under test names it in two places, and both are quoted in `lib/phase1.py`:
§7.3 ("Content Filter (MEDIUM)") and Appendix A ("Violent Content ✅ MEDIUM"). So MEDIUM
is read out of the document rather than chosen here. If the measurement is better at
another strength that is a **finding about the recommendation**, not a reason to
evaluate the oracle elsewhere — which is what F3-9's Youden's J is for.

WHAT EACH ARM COUNTS
--------------------
* recall arms — `hit` defaults to "the item's own label was detected", so a VIOLENCE
  item detected as HATE is a MISS. That is deliberate and stricter than "something
  fired": §3.2's per-category table is a claim about categories, and a filter that
  routed everything to one category would satisfy a laxer reading while making the
  table wrong. `any_detection` is reported alongside so both readings are visible.
* FPR arms — `arms.any_detection`, i.e. ANY policy firing. Broader than the content
  filter on purpose: a benign request blocked by any policy is a false positive to the
  reader, and §7.1's precision arithmetic needs the rate a reader experiences.
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
CASES = ("F3-1", "F3-2", "F3-3", "F3-9")

# One corpus file per content-filter category, plus the two negative cells.
CF_CORPORA = [f"content_filter/{c.lower()}.jsonl" for c in P.CF_CATEGORIES]
BENIGN = "benign/benign.jsonl"
HARD = "hard_negatives/hard_negatives.jsonl"


def plan(n: int | None) -> list[tuple[str, str, int]]:
    """The arms, as (label, corpus, n) — used by both the dry run and the live path.

    The counts come from the corpus files themselves, not from literals. A literal here
    would be a second, unchecked copy of the sealed corpus size: the dry run's printed
    total is what the cost projection is read off, and a `120` that stayed 120 after the
    corpus grew would under-project the spend of the run it is supposed to authorise.
    """
    rows: list[tuple[str, str, int]] = []
    size = lambda rel: len(R.load_corpus(rel, limit=n))   # noqa: E731
    for s in P.STRENGTHS:
        for rel in CF_CORPORA:
            rows.append((f"cf-{s.lower()}", rel, size(rel)))
        rows.append((f"cf-{s.lower()}", BENIGN, size(BENIGN)))
    # The hard negatives run at the recommended strength only. F3-3's oracle is about
    # the recommendation, and sweeping the lattice with them would quadruple the cell
    # for a question no oracle asks.
    rows.append((f"cf-{P.RECOMMENDED_CONTENT_STRENGTH.lower()}", HARD, size(HARD)))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = P.parser("F3-1/2/3/9", __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        rc = 0
        for cid in CASES:
            rc |= P.dry_run_banner(
                cid, plan(args.n),
                extra=[f"recommended threshold (from the document under test): "
                       f"{P.RECOMMENDED_CONTENT_STRENGTH} for content filters",
                       "the four cases read ONE set of arms; see the module docstring "
                       "on why they are not independent evidence"])
            print()
        return rc

    run_id = P.resolve_run(args)
    man = P.manifest()
    is_smoke = args.n is not None

    # --- collect: every strength x every category, plus the negatives ---------
    #
    # Ordered strength-outer so a run interrupted after the first strength leaves a
    # complete operating point rather than a fifth of five of them.
    recall: dict[str, dict[str, dict[str, int]]] = {}   # strength -> category -> x/n
    benign: dict[str, dict] = {}                       # strength -> tally
    tallies: list[dict] = []

    for s in P.STRENGTHS:
        gid = P.guardrail(f"cf-{s.lower()}", man=man)
        print(f"\nstrength {s}  (guardrail {gid})")
        recall[s] = {}
        for cat, rel in zip(P.CF_CATEGORIES, CF_CORPORA):
            items = R.load_corpus(rel, limit=args.n)
            spec = R.ArmSpec(case_id="F3-1", family=FAMILY, corpus=rel,
                             guardrail_id=gid, region=args.region,
                             label=f"{s.lower()}-{cat.lower()}")
            t = P.run_arms([spec], [items], run_id=run_id, is_smoke=is_smoke)[0]
            tallies.append(t)
            recall[s][cat] = {"x": t["x"], "n": t["n_usable"],
                              "n_attempted": t["n_attempted"],
                              "failure_codes": t["failure_codes"]}

        items = R.load_corpus(BENIGN, limit=args.n)
        spec = R.ArmSpec(case_id="F3-2", family=FAMILY, corpus=BENIGN,
                         guardrail_id=gid, region=args.region,
                         label=f"{s.lower()}-benign", hit=R.any_detection)
        benign[s] = P.run_arms([spec], [items], run_id=run_id, is_smoke=is_smoke)[0]
        tallies.append(benign[s])

    rec_strength = P.RECOMMENDED_CONTENT_STRENGTH
    gid_rec = P.guardrail(f"cf-{rec_strength.lower()}", man=man)
    items = R.load_corpus(HARD, limit=args.n)
    spec = R.ArmSpec(case_id="F3-3", family=FAMILY, corpus=HARD,
                     guardrail_id=gid_rec, region=args.region,
                     label=f"{rec_strength.lower()}-hardneg", hit=R.any_detection)
    hard = P.run_arms([spec], [items], run_id=run_id, is_smoke=is_smoke)[0]
    tallies.append(hard)

    rc = P.require_measured(tallies, is_smoke=is_smoke)
    if rc:
        return rc

    shared = {"run_id": run_id, "is_smoke": is_smoke,
              "recommended_threshold": rec_strength,
              "recommended_threshold_source":
                  "the document under test, §7.3 and Appendix A",
              "billable_calls": sum(t["n_usable"] for t in tallies),
              "mutations": 0,
              "not_independent": ("F3-1, F3-2 and F3-9 are computed from ONE set of "
                                  "arms; four verdicts over shared measurements are "
                                  "not four independent confirmations")}

    # --- F3-1: pooled recall at the recommended threshold --------------------
    #
    # Pooled across the five categories, because the sealed oracle is about "the
    # content filter" and names no category. The per-category split is reported
    # alongside for the same reason F3-8 exists: a pooled 0.9 is compatible with one
    # category at 0.3, and the pooled figure is an average over a corpus composition
    # we chose.
    per_cat = recall[rec_strength]
    x = sum(c["x"] for c in per_cat.values())
    n = sum(c["n"] for c in per_cat.values())
    o = P.obs_proportion("F3-1", [{"x": x, "n_usable": n, "n_attempted": n,
                                   "failure_codes": []}],
                         per_category=per_cat, strength=rec_strength)
    r = O.evaluate(o)
    P.emit("F3-1", r, {**shared, "per_category": per_cat,
                       "per_category_verdicts": P.per_stratum("F3-1", per_cat),
                       "instrument": "ApplyGuardrail (source=INPUT, outputScope=FULL)"},
           EvidenceStore(run_id, FAMILY, "F3-1"))

    # --- F3-2: benign FPR at the recommended threshold -----------------------
    o = P.obs_proportion("F3-2", [benign[rec_strength]], strength=rec_strength)
    r = O.evaluate(o)
    P.emit("F3-2", r, {**shared,
                       "fpr_by_strength": {s: {"x": t["x"], "n": t["n_usable"]}
                                           for s, t in benign.items()},
                       "hit_rule": "arms.any_detection — ANY policy firing on a benign "
                                   "item is a false positive to the reader"},
           EvidenceStore(run_id, FAMILY, "F3-2"))

    # --- F3-3: hard-negative FPR (asymmetric oracle) -------------------------
    o = P.obs_proportion("F3-3", [hard], strength=rec_strength)
    r = O.evaluate(o)
    P.emit("F3-3", r, {**shared,
                       "oracle_direction": ("ASYMMETRIC_FPR: FALSE only if the LOWER "
                                            "bound exceeds 10%, so a wide interval "
                                            "cannot refute the document"),
                       "benign_fpr_same_strength": {"x": benign[rec_strength]["x"],
                                                    "n": benign[rec_strength]["n_usable"]}},
           EvidenceStore(run_id, FAMILY, "F3-3"))

    # --- F3-9: the ROC over the strength lattice -----------------------------
    by_strength = {}
    for s in P.STRENGTHS:
        pos_x = sum(c["x"] for c in recall[s].values())
        pos_n = sum(c["n"] for c in recall[s].values())
        by_strength[s] = {"tp": pos_x, "pos": pos_n,
                          "fp": benign[s]["x"], "neg": benign[s]["n_usable"]}
    roc = P.roc_points(by_strength)
    o = P.obs_roc("F3-9",
                  operating_points=roc["operating_points_with_trivial_endpoints"],
                  argmax_j_interior=roc["argmax_is_interior"],
                  n=sum(v["pos"] + v["neg"] for v in by_strength.values()))
    r = O.evaluate(o)
    P.emit("F3-9", r, {**shared, "roc": roc,
                       "instrument": (
                           "ApplyGuardrail's 4-setting `inputStrength` knob. NOT "
                           "InvokeGuardrailChecks: that API returns "
                           "`severityScore: double`, a CONTINUOUS score with no "
                           "lattice, so a <=7-vertex ceiling cannot be a property of "
                           "it. The ceiling is a property of the configurable "
                           "strength enum, and F3-9 is therefore a test of "
                           "ApplyGuardrail only — see DEVIATIONS.md/DEV-P1-5"),
                       "lattice_note": (
                           f"4 settings + 2 trivial endpoints = at most 6 reachable "
                           f"points, under the oracle's ceiling of 7. The oracle "
                           f"cannot fail on the count for a reason internal to the "
                           f"API, and that is reported rather than smoothed")},
           EvidenceStore(run_id, FAMILY, "F3-9"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
