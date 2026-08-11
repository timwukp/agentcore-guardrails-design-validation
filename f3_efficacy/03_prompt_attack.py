#!/usr/bin/env python3
"""F3-8: PROMPT_ATTACK recall per corpus subtype, at the recommended HIGH threshold.

    python3 f3_efficacy/03_prompt_attack.py --dry-run
    python3 f3_efficacy/03_prompt_attack.py --n 3
    python3 f3_efficacy/03_prompt_attack.py

ONE FILTER, THREE SUBTYPES — AND THE SUBTYPES ARE OURS
------------------------------------------------------
`contentPolicyConfig` has exactly **one** `PROMPT_ATTACK` filter type. JAILBREAK,
PROMPT_INJECTION and PROMPT_LEAKAGE are separate categories only under
`InvokeGuardrailChecks.promptAttack`; on `ApplyGuardrail` the response carries one bit.
So "per-subtype recall" here is a property of **our stratification** of the corpus, and
what is measured is "did the single PROMPT_ATTACK filter fire on an item we labelled as
this subtype". Every number in the output is qualified that way, because the alternative
reading — that the service reported three categories — is what a reader would assume from
a three-row table with no note.

`phase1.hit_prompt_attack` therefore reads the PROMPT_ATTACK type rather than the item's
label. The default label reader would look for a content-filter type named `JAILBREAK`,
never find it, and report 0/360 recall for a filter that fired on every item.

THE McNEMAR PROBLEM IN THE SEALED ORACLE
----------------------------------------
F3-8's sealed text ends "Between-subtype differences by BH-adjusted McNemar are
secondary". McNemar's test is for **paired** binary observations — the same unit measured
twice. The three subtype cells are disjoint corpora: item 7 of `jailbreak.jsonl` is not
the same item as item 7 of `prompt_leakage.jsonl`, and there is no pairing between them
to build a 2x2 discordance table from. Running McNemar over them would require inventing
a pairing by index, which would make the discordant counts an artefact of file order.

The pre-registration is followed where it can be and the gap is recorded rather than
papered over (DEVIATIONS.md/DEV-P1-6):

* **between subtypes** — unpaired, so the comparison is reported as two-proportion
  intervals and an exact test of independent proportions, explicitly NOT as McNemar.
* **McNemar is run where a pairing genuinely exists**: the same items sent twice, once
  untagged and once with the `guard_content` qualifier. That is a paired design by
  construction, and it is also the arm that speaks to DC-2 — §3.2 claims PROMPT_ATTACK
  requires input tags, and an earlier n=5 observation contradicted it with a Wilson
  interval of roughly [56%, 100%], nowhere near enough to amend anything.

The tagged arm is a **secondary, descriptive** result here and not the resolution of DC-2.
That resolution is F5-6's, which compares four arms across `InvokeModel` and `Converse`;
this script cannot see the `Converse`-scope trap at all, because `ApplyGuardrail` takes
the qualifier directly. What this arm can establish is whether the tag changes anything on
`ApplyGuardrail`, at n=120 per subtype instead of n=5 pooled.
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
CASE = "F3-8"
STRENGTH = P.RECOMMENDED_ATTACK_STRENGTH          # HIGH, per §7.3 and Appendix A


def rel_for(subtype: str) -> str:
    return f"prompt_attack/{subtype.lower()}.jsonl"


def plan(n: int | None) -> list[tuple[str, str, int]]:
    rows = []
    for st in P.ATTACK_SUBTYPES:
        rel = rel_for(st)
        k = len(R.load_corpus(rel, limit=n))
        rows.append((f"untagged-{st.lower()}", rel, k))
        rows.append((f"tagged-{st.lower()}", rel, k))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        return P.dry_run_banner(
            CASE, plan(args.n),
            extra=[f"recommended threshold (from the document under test): {STRENGTH} "
                   f"for PROMPT_ATTACK",
                   "the API has ONE PROMPT_ATTACK filter; the three subtypes are our "
                   "corpus labels, not response categories",
                   "the tagged arm pairs item-by-item with the untagged arm, which is "
                   "the only place in this case where McNemar is applicable — see the "
                   "module docstring and DEVIATIONS.md/DEV-P1-6"])

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid = P.guardrail(f"cf-{STRENGTH.lower()}", man=man)
    is_smoke = args.n is not None
    print(f"\nPROMPT_ATTACK at {STRENGTH} (guardrail {gid})")

    strata: dict[str, dict[str, int]] = {}
    tagged: dict[str, dict[str, int]] = {}
    tallies: list[dict] = []
    paired: dict[str, dict[str, int]] = {}

    for st in P.ATTACK_SUBTYPES:
        rel = rel_for(st)
        items = R.load_corpus(rel, limit=args.n)
        specs = [
            R.ArmSpec(case_id=CASE, family=FAMILY, corpus=rel, guardrail_id=gid,
                      region=args.region, label=f"untagged-{st.lower()}",
                      hit=P.hit_prompt_attack),
            # `qualifiers=('guard_content',)` is the tag §3.2 says PROMPT_ATTACK requires.
            R.ArmSpec(case_id=CASE, family=FAMILY, corpus=rel, guardrail_id=gid,
                      region=args.region, label=f"tagged-{st.lower()}",
                      qualifiers=("guard_content",), hit=P.hit_prompt_attack),
        ]
        t_un, t_tg = P.run_arms(specs, [items, items], run_id=run_id, is_smoke=is_smoke)
        tallies += [t_un, t_tg]
        strata[st] = {"x": t_un["x"], "n": t_un["n_usable"],
                      "n_attempted": t_un["n_attempted"],
                      "failure_codes": t_un["failure_codes"]}
        tagged[st] = {"x": t_tg["x"], "n": t_tg["n_usable"]}

        # The paired 2x2, joined on the item id — not on position. Two arms that lost
        # different items to throttles have different row orders, and an index join would
        # silently pair item 40's untagged result with item 41's tagged one.
        a = {r["item_id"]: bool(r["hit"]) for r in t_un["rows"]}
        b = {r["item_id"]: bool(r["hit"]) for r in t_tg["rows"]}
        both = sorted(set(a) & set(b))
        b_disc = sum(1 for i in both if a[i] and not b[i])     # untagged only
        c_disc = sum(1 for i in both if b[i] and not a[i])     # tagged only
        stat, p = S.mcnemar_test(b_disc, c_disc)
        paired[st] = {"n_pairs": len(both),
                      "both_detected": sum(1 for i in both if a[i] and b[i]),
                      "neither": sum(1 for i in both if not a[i] and not b[i]),
                      "untagged_only": b_disc, "tagged_only": c_disc,
                      "mcnemar_stat": stat, "mcnemar_p_raw": p,
                      "n_dropped_unpaired": (len(a) + len(b) - 2 * len(both))}

    rc = P.require_measured(tallies, is_smoke=is_smoke)
    if rc:
        return rc

    roll = P.per_stratum(CASE, strata)

    # Between-subtype comparison, deliberately NOT McNemar. See the docstring.
    between = {}
    subs = list(P.ATTACK_SUBTYPES)
    for i, a_st in enumerate(subs):
        for b_st in subs[i + 1:]:
            ca, cb = strata[a_st], strata[b_st]
            between[f"{a_st}_vs_{b_st}"] = {
                "a": {"x": ca["x"], "n": ca["n"], "ci": str(S.wilson_ci(ca["x"], ca["n"]))},
                "b": {"x": cb["x"], "n": cb["n"], "ci": str(S.wilson_ci(cb["x"], cb["n"]))},
                "test": ("unpaired two-proportion comparison by CI overlap; McNemar is "
                         "NOT applicable because the two cells are disjoint corpora with "
                         "no item-level pairing"),
                "intervals_disjoint": (S.wilson_ci(ca["x"], ca["n"]).lo
                                       > S.wilson_ci(cb["x"], cb["n"]).hi)
                or (S.wilson_ci(cb["x"], cb["n"]).lo > S.wilson_ci(ca["x"], ca["n"]).hi),
            }

    pooled_x = sum(c["x"] for c in strata.values())
    pooled_n = sum(c["n"] for c in strata.values())
    rec = dict(O.evaluate(P.obs_proportion(
        CASE, [{"x": pooled_x, "n_usable": pooled_n, "n_attempted": pooled_n,
                "failure_codes": []}], pooled_description_only=True)))
    rec["verdict"] = roll["rollup_verdict"]
    # Per-subtype AND with its basis recorded — the sealed n is per subtype, so a pooled
    # n_usable compared against it produces a sentence whose numbers are each right and
    # whose claim is false (DEVIATIONS.md/DEV-P1-12).
    rec = P.apply_rollup_n_met(rec, roll, unit="subtype")
    rec["notes"] = list(rec.get("notes") or []) + [
        "the verdict is the per-subtype roll-up; the pooled interval describes an average "
        "over a corpus composition we chose (120 per subtype)",
        "the subtypes are OUR corpus labels — the API reports one PROMPT_ATTACK bit",
    ]

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "strength": STRENGTH,
        "strength_source": "the document under test, §7.3 and Appendix A",
        "billable_calls": sum(t["n_usable"] for t in tallies), "mutations": 0,
        "rollup": roll,
        "pooled_description_only": {"x": pooled_x, "n": pooled_n},
        "tagged_arm": tagged,
        "input_tag_paired_mcnemar": paired,
        "mcnemar_scope": ("run on the untagged-vs-tagged pairing of the SAME items, which "
                          "is the only paired design in this case; the sealed oracle's "
                          "between-subtype McNemar is not computable over disjoint "
                          "corpora — see DEVIATIONS.md/DEV-P1-6"),
        "between_subtypes": between,
        "dc2_scope": ("this arm speaks to DC-2 (§3.2's input-tag requirement) on "
                      "ApplyGuardrail only and at n per subtype instead of the earlier "
                      "n=5. It does NOT resolve DC-2: the Converse-scope trap needs "
                      "F5-6's four arms across InvokeModel and Converse, and "
                      "ApplyGuardrail takes the qualifier directly"),
        "instrument": "ApplyGuardrail (source=INPUT, outputScope=FULL)",
    }, EvidenceStore(run_id, FAMILY, CASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
