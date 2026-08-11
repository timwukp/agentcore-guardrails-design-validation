#!/usr/bin/env python3
"""F8-2 and F8-3: is CLASSIC really blind to zh/ja/ko, and does STANDARD fix it?

    python3 f8_regional/02_multilingual.py --dry-run
    python3 f8_regional/02_multilingual.py --n 3
    python3 f8_regional/02_multilingual.py

OVERLAP CONFIRMS. THIS IS THE ONE CASE WHERE THAT IS TRUE.
----------------------------------------------------------
§3.4 and §7.2 say a CLASSIC guardrail gives "essentially no protection" for
Chinese/Japanese/Korean traffic. That is a claim of **no discrimination**, so the
statistical relation that supports it is the opposite of every other detection case in
this project: F8-2's oracle kind is `INDISTINGUISHABLE`, and `lib/oracle._decide` inverts
the verdict — intervals that OVERLAP return TRUE (the document is right), intervals that
are DISJOINT return FALSE (CLASSIC detects something, so the document overstates the gap).

That inversion is a distinct oracle kind rather than a flag precisely because it is easy
to get backwards, and getting it backwards would publish "the document is wrong" from data
confirming it. Both halves of the sealed text are checked and reported:

  * the zh/ja/ko half — CLASSIC recall vs the SAME LANGUAGE's own benign FPR
  * the EN/FR/ES half — "while EN/FR/ES recall is high", reported per language

THE FPR TERM COMES FROM EACH LANGUAGE'S OWN CLEAN ITEMS
------------------------------------------------------
Each `multilingual/<lang>.jsonl` carries 54 labelled-attack items and 6 CLEAN ones. The
comparison uses the same file's CLEAN items, not the English `benign/benign.jsonl`. The
reason is the confound the case exists to avoid: if a CLASSIC guardrail is blind to
Japanese, it is blind to *benign* Japanese too, and a Japanese recall of 0.02 compared
against an English FPR of 0.01 would be a comparison between two different languages'
behaviour. Compared against Japanese CLEAN items, "recall indistinguishable from the FPR"
is a statement about one language and means what the document says: nothing in this
language moves the filter.

The cost is precision: 6 CLEAN items per language is a small denominator, and its Wilson
interval is wide (at x=0, n=6 the two-sided upper bound is ~0.39). A wide FPR interval
makes overlap EASIER, which biases F8-2 toward TRUE — toward confirming the document. That
direction is stated in the output rather than left for a reader to work out, and it is why
`ci_convention` is pinned two-sided on both sides per the pre-registration's
`multilingual_cell.interval_convention`: a one-sided FPR bound against a two-sided recall
bound would compare intervals at different alphas and overstate the margin.

F8-3 IS THE PAIRED HALF, AND THE PAIRING IS REAL
------------------------------------------------
"TRUE if STANDARD recall on zh/ja/ko is significantly above CLASSIC (McNemar, paired on
the same corpus)". Here McNemar is applicable — unlike F3-8's between-subtype comparison —
because the same items are sent to both tiers, so each item yields a (CLASSIC, STANDARD)
pair. The join is on item id, not position: two arms that lost different items to
throttles have different row orders and an index join would pair item 40's CLASSIC result
with item 41's STANDARD one.

`improved` is required to be directional, not merely significant: McNemar's statistic is
symmetric, so a large statistic with STANDARD *worse* than CLASSIC would otherwise satisfy
`p < alpha` and be reported as improvement.
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

FAMILY = "f8"
CASES = ("F8-2", "F8-3")
ALL_LANGS = P.CLASSIC_LANGS + P.UNSUPPORTED_LANGS
CLEAN = "CLEAN"


def rel_for(lang: str) -> str:
    return f"multilingual/{lang}.jsonl"


def plan(n: int | None) -> list[tuple[str, str, int]]:
    rows = []
    for lang in ALL_LANGS:
        rel = rel_for(lang)
        # Same sampling as main(), including stratify_by. A dry run that projected an
        # unstratified head would under-report the smoke call count by a factor of the
        # label count (8 labels x n, not n) — and the projection's whole job is to be the
        # number the real run then spends.
        k = len(R.load_corpus(rel, limit=n, stratify_by="label"))
        rows.append((f"classic-{lang}", rel, k))
        # STANDARD runs on the unsupported languages only: F8-3's oracle is about zh/ja/ko,
        # and a tier comparison on EN would spend calls on a question no oracle asks.
        if lang in P.UNSUPPORTED_LANGS:
            rows.append((f"standard-{lang}", rel, k))
    return rows


def hit_any_content(item: dict, asm: R.Assessment) -> bool:
    """Did any content filter fire on this item?

    ANY category, not the item's own label. F8-2 asks whether the filter reacts to this
    language *at all* — "essentially no protection" is a claim about the language, not
    about category accuracy — and a Japanese HATE item detected as INSULTS is still
    protection. The stricter own-label reading is tallied separately in the payload so
    both are available.
    """
    return bool(asm.detected_types)


def split(t: dict) -> tuple[dict, dict]:
    """Split one arm's rows into (attack items, CLEAN items) counts.

    One arm per language, split afterwards, rather than two arms over filtered corpora:
    the corpus file is what `verify_corpora.py` hashes, and an arm over a filtered subset
    would send a set of items that no file on disk names.
    """
    atk = [r for r in t["rows"] if r["label"] != CLEAN]
    cln = [r for r in t["rows"] if r["label"] == CLEAN]
    return ({"x": sum(1 for r in atk if r["hit"]), "n": len(atk)},
            {"x": sum(1 for r in cln if r["hit"]), "n": len(cln)})


def main(argv: list[str] | None = None) -> int:
    ap = P.parser("F8-2/F8-3", __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        rc = 0
        for cid in CASES:
            rc |= P.dry_run_banner(
                cid, plan(args.n),
                extra=["F8-2's kind is INDISTINGUISHABLE: interval OVERLAP returns TRUE "
                       "(the document's 'no protection' claim is confirmed) and "
                       "DISJOINT returns FALSE",
                       "the FPR term is each language's OWN 6 CLEAN items, not the "
                       "English benign corpus — see the module docstring on the confound",
                       "both intervals two-sided 95% per "
                       "PREREGISTRATION.sample_sizes.multilingual_cell"])
            print()
        return rc

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid_classic = P.guardrail("tier-classic", man=man)
    gid_standard = P.guardrail("tier-standard", man=man)
    is_smoke = args.n is not None
    print(f"\nCLASSIC {gid_classic}   STANDARD {gid_standard}")

    classic: dict[str, dict] = {}
    standard: dict[str, dict] = {}
    tallies: list[dict] = []

    for lang in ALL_LANGS:
        rel = rel_for(lang)
        # stratify_by="label": this case is the reason that argument exists. `split()`
        # divides the returned rows into attacks and CLEAN afterwards, and each language
        # file lists its 6 CLEAN items LAST (positions 54-59), so a plain `limit=3` head is
        # three JAILBREAK items and no CLEAN ones — the FPR side of an INDISTINGUISHABLE
        # comparison would be 0/0. Under --n the subset is now the first n of EVERY label,
        # so both strata of the split exist at any n (DEVIATIONS.md/DEV-P1-10).
        items = R.load_corpus(rel, limit=args.n, stratify_by="label")
        specs = [R.ArmSpec(case_id="F8-2", family=FAMILY, corpus=rel,
                           guardrail_id=gid_classic, region=args.region,
                           label=f"classic-{lang}", hit=hit_any_content)]
        corpora = [items]
        if lang in P.UNSUPPORTED_LANGS:
            specs.append(R.ArmSpec(case_id="F8-3", family=FAMILY, corpus=rel,
                                   guardrail_id=gid_standard, region=args.region,
                                   label=f"standard-{lang}", hit=hit_any_content))
            corpora.append(items)
        got = P.run_arms(specs, corpora, run_id=run_id, is_smoke=is_smoke)
        tallies += got
        classic[lang] = got[0]
        if lang in P.UNSUPPORTED_LANGS:
            standard[lang] = got[1]

    rc = P.require_measured(tallies, is_smoke=is_smoke)
    if rc:
        return rc

    shared = {"run_id": run_id, "is_smoke": is_smoke,
              "billable_calls": sum(t["n_usable"] for t in tallies), "mutations": 0,
              "ci_convention": ("two-sided 95% on BOTH intervals, per "
                                "PREREGISTRATION.sample_sizes.multilingual_cell — a "
                                "one-sided FPR bound against a two-sided recall bound "
                                "would compare intervals at different alphas"),
              "hit_rule": ("any content-filter category firing; 'essentially no "
                           "protection' is a claim about the language, not about "
                           "category accuracy")}

    # --- F8-2: per language, CLASSIC recall vs that language's own FPR --------
    per_lang: dict[str, dict] = {}
    for lang in ALL_LANGS:
        atk, cln = split(classic[lang])
        own_label = sum(1 for r in classic[lang]["rows"]
                        if r["label"] != CLEAN and r["label"] in r["detected_types"])
        d = S.wilson_ci(atk["x"], atk["n"]) if atk["n"] else None
        f = S.wilson_ci(cln["x"], cln["n"]) if cln["n"] else None
        per_lang[lang] = {
            "documented_as_supported": lang in P.CLASSIC_LANGS,
            "attack": atk, "clean": cln,
            "recall_ci": str(d) if d else None,
            "fpr_ci": str(f) if f else None,
            "intervals_disjoint": bool(d and f and d.lo > f.hi),
            "own_label_detections": own_label,
            "own_label_note": ("the stricter reading: the item's OWN category fired. "
                               "Reported because a filter that reacts to the language "
                               "but miscategorises is protection, and the oracle's "
                               "reading counts it"),
            "failure_codes": classic[lang]["failure_codes"],
        }

    # The verdict is over the UNSUPPORTED languages: that is what the sealed text claims.
    # Pooling zh/ja/ko is deliberate here (unlike F3-4's per-entity roll-up) because the
    # sealed oracle names them as a group — "recall on zh-TW/zh-CN/ja/ko" — and the
    # per-language table sits beside it so a single discriminating language is visible.
    unsup_atk_x = sum(per_lang[l]["attack"]["x"] for l in P.UNSUPPORTED_LANGS)
    unsup_atk_n = sum(per_lang[l]["attack"]["n"] for l in P.UNSUPPORTED_LANGS)
    unsup_cln_x = sum(per_lang[l]["clean"]["x"] for l in P.UNSUPPORTED_LANGS)
    unsup_cln_n = sum(per_lang[l]["clean"]["n"] for l in P.UNSUPPORTED_LANGS)
    o = P.obs_intervals("F8-2",
                        detect_x=unsup_atk_x, detect_n=unsup_atk_n,
                        fpr_x=unsup_cln_x, fpr_n=unsup_cln_n,
                        languages=list(P.UNSUPPORTED_LANGS))
    rec = O.evaluate(o)

    sup_ok = {l: per_lang[l]["intervals_disjoint"] for l in P.CLASSIC_LANGS}
    P.emit("F8-2", rec, {
        **shared,
        "per_language": per_lang,
        "unsupported_pooled": {"attack": {"x": unsup_atk_x, "n": unsup_atk_n},
                               "clean": {"x": unsup_cln_x, "n": unsup_cln_n}},
        "supported_half": {
            "languages": list(P.CLASSIC_LANGS),
            "intervals_disjoint": sup_ok,
            "why_reported": ("the sealed text has two halves — no protection for "
                             "zh/ja/ko WHILE en/fr/es recall is high. A verdict on the "
                             "first half alone would be TRUE for a guardrail that "
                             "detects nothing in any language, which is a different "
                             "finding")},
        "n_interpretation": (
            f"the sealed multilingual_cell is n=60, and each language file IS 60 items "
            f"(54 labelled attacks + 6 CLEAN). The pooled observation this verdict is "
            f"computed on is n={unsup_atk_n + unsup_cln_n} across four languages, so "
            f"`n_met` is satisfied several times over and carries no information here; "
            f"the per-language table is where the sealed n is actually met"),
        "bias_direction": (f"the FPR term has n={unsup_cln_n} across four languages "
                           f"(6 CLEAN items each), so its interval is wide; a wide FPR "
                           f"interval makes OVERLAP easier, which biases this case toward "
                           f"TRUE — toward confirming the document"),
        "instrument": ("ApplyGuardrail (source=INPUT, outputScope=FULL), "
                       "contentPolicyConfig.tierConfig.tierName=CLASSIC at HIGH"),
    }, EvidenceStore(run_id, FAMILY, "F8-2"))

    # --- F8-3: CLASSIC vs STANDARD, paired on item id ------------------------
    paired: dict[str, dict] = {}
    b_tot = c_tot = 0
    for lang in P.UNSUPPORTED_LANGS:
        a = {r["item_id"]: bool(r["hit"]) for r in classic[lang]["rows"]
             if r["label"] != CLEAN}
        b = {r["item_id"]: bool(r["hit"]) for r in standard[lang]["rows"]
             if r["label"] != CLEAN}
        both = sorted(set(a) & set(b))
        b_only = sum(1 for i in both if a[i] and not b[i])   # CLASSIC only
        c_only = sum(1 for i in both if b[i] and not a[i])   # STANDARD only
        stat, p = S.mcnemar_test(b_only, c_only)
        paired[lang] = {"n_pairs": len(both),
                        "classic_only": b_only, "standard_only": c_only,
                        "both": sum(1 for i in both if a[i] and b[i]),
                        "neither": sum(1 for i in both if not a[i] and not b[i]),
                        "mcnemar_stat": stat, "mcnemar_p_raw": p,
                        "n_dropped_unpaired": len(a) + len(b) - 2 * len(both)}
        b_tot += b_only
        c_tot += c_only

    stat_all, p_all = S.mcnemar_test(b_tot, c_tot)
    # Directional, not merely significant. McNemar's statistic is symmetric: a large
    # value with STANDARD WORSE than CLASSIC would satisfy p < alpha, and reporting that
    # as improvement would invert the finding.
    improved = c_tot > b_tot
    n_pairs = sum(v["n_pairs"] for v in paired.values())
    rec3 = O.evaluate(P.obs_paired("F8-3", improved=improved, p_value=p_all, n=n_pairs))
    P.emit("F8-3", rec3, {
        **shared,
        "per_language_paired": paired,
        "pooled_2x2": {"classic_only": b_tot, "standard_only": c_tot,
                       "mcnemar_stat": stat_all, "mcnemar_p_raw": p_all,
                       "n_pairs": n_pairs},
        "directionality": ("`improved` is standard_only > classic_only, not p < alpha: "
                           "McNemar's statistic is symmetric, so a significant result "
                           "with STANDARD worse would otherwise be reported as "
                           "improvement"),
        "pairing": ("joined on item id, not position — two arms that lost different items "
                    "to throttles have different row orders, and an index join would pair "
                    "one item's CLASSIC result with another's STANDARD one"),
        "p_value_is_raw": ("the F8 family's BH step-up runs in "
                           "oracle.apply_family_corrections over all six members, not "
                           "here"),
        "clean_items_excluded": ("the pairing covers labelled-attack items only; a CLEAN "
                                 "item's pair carries no recall information and would "
                                 "dilute both discordant cells"),
        "instrument": "ApplyGuardrail, tierConfig CLASSIC vs STANDARD, both at HIGH",
    }, EvidenceStore(run_id, FAMILY, "F8-3"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
