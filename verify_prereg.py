#!/usr/bin/env python3
"""Pre-registration verifier and sealer.

A pre-registration that nothing checks is a document, not a commitment. This
script is what makes PREREGISTRATION.yaml binding, in three modes:

  --seal     compute the file's own sha256, write it into PREREGISTRATION.sha256,
             and flip meta.status to SEALED. Refuses to re-seal a sealed file.
  (default)  verify: re-derive every number in `derived` from lib/stats.py, check
             the bound-artifact hashes and the oracle registry, and check the
             internal consistency of the design (families are disjoint, every
             case named exists, every sized claim is claimed by some case).
  --check-analysis RESULTS.json
             at analysis time, assert that every case, threshold and family the
             analysis reports was declared here before data existed.

WHY RE-DERIVE RATHER THAN COMPARE STRINGS

The failure this guards against is specific and has already happened once in
this project: the approved plan carried "298" where its own power function
requires 299. A verifier that merely re-read the number from the YAML would have
confirmed 298 forever. So every value in `derived` is recomputed by CALLING
lib/stats.py, and the YAML is the thing being tested — not the oracle.

Exit codes:
  0  verified (or sealed successfully)
  1  a check failed — the pre-registration and the code disagree
  2  the input itself is unusable (missing file, unparseable YAML, missing deps)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "claims"))

PREREG = ROOT / "PREREGISTRATION.yaml"
STAMP = ROOT / "PREREGISTRATION.sha256"

# Tolerance for re-derived floating point values. Tight on purpose: these are
# deterministic function calls, not measurements, so anything beyond float noise
# means the YAML and the code genuinely disagree.
TOL = 1e-9


def _fail(problems: list[str], msg: str) -> None:
    problems.append(msg)


# ---------------------------------------------------------------------------
# hashing
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def oracle_registry_sha256() -> tuple[str, int]:
    """Hash {case_id: oracle} for all cases, sorted.

    Hashed separately from triage_rules.py because the FALSIFYING CONDITIONS are
    what a pre-registration exists to freeze. triage_rules.py also contains
    titles, methods and exclusion prose, all of which may legitimately be
    reworded after sealing; an oracle may not. Hashing the whole file would
    conflate the two and force a deviation entry for a typo fix.
    """
    import triage_rules as R

    canon = json.dumps({cid: R.CASES[cid][3] for cid in sorted(R.CASES)},
                       sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest(), len(R.CASES)


# ---------------------------------------------------------------------------
# the derived-constant checks — each one CALLS stats.py
# ---------------------------------------------------------------------------

def check_derived(pr: dict, problems: list[str]) -> int:
    from lib import stats as S
    import numpy as np

    d = pr["derived"]
    n_checked = 0

    def eq(label: str, got, want, tol: float = TOL) -> None:
        nonlocal n_checked
        n_checked += 1
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            ok = abs(float(got) - float(want)) <= tol
        else:
            ok = got == want
        if not ok:
            _fail(problems, f"derived.{label}: yaml says {want!r}, "
                            f"lib/stats.py gives {got!r}")

    eq("z_95_two_sided", S.Z_95, d["z_95_two_sided"])

    # The correction this project already had to make once. Both the required n
    # AND the powers either side of it are pinned, so a future edit cannot quietly
    # restore 298 by also editing the justification.
    dz = d["determinism_zero_event_n"]
    eq("determinism_zero_event_n.value",
       S.required_n_for_zero_events(0.01, 0.95), dz["value"])
    eq("determinism_zero_event_n.power_at_298",
       S.power_for_zero_events(298, 0.01), dz["power_at_298"])
    eq("determinism_zero_event_n.power_at_299",
       S.power_for_zero_events(299, 0.01), dz["power_at_299"])
    n_checked += 1
    if not dz["power_at_298"] < 0.95 <= dz["power_at_299"]:
        _fail(problems, "derived.determinism_zero_event_n: the pinned powers do "
                        "not bracket 0.95, so 299 is not the ceiling they claim")

    eq("determinism_zero_event_n_5pct.value",
       S.required_n_for_zero_events(0.05, 0.95),
       d["determinism_zero_event_n_5pct"]["value"])

    for n, want in d["rule_of_three_one_sided_95"]["values"].items():
        eq(f"rule_of_three[{n}]", round(S.rule_of_three(int(n)), 6), want)

    bf = d["bonferroni_per_hypothesis_alpha"]
    eq("bonferroni_per_hypothesis_alpha.value",
       0.05 / bf["confirmatory_family_size"], bf["value"])

    # Order statistics for the latency quantile CIs. Computed on a synthetic
    # 1..n vector so the returned bounds ARE the order-statistic indices.
    for key, q in (("latency_p99_order_statistics", 0.99),
                   ("latency_p90_order_statistics", 0.90),
                   ("latency_p50_order_statistics", 0.50)):
        spec = d[key]
        if "lower_order_stat" in spec:
            ci = S.quantile_ci(np.arange(1, 1001), q)
            eq(f"{key}.lower_order_stat", int(ci.lo), spec["lower_order_stat"])
            eq(f"{key}.upper_order_stat", int(ci.hi), spec["upper_order_stat"])
        for label, n in (("at_n_1000", 1000), ("at_n_200", 200)):
            if label in spec:
                ci = S.quantile_ci(np.arange(1, n + 1), q)
                eq(f"{key}.{label}", [int(ci.lo), int(ci.hi)], spec[label])

    eq("max_flip_rate.value", 2 * 0.5 * (1 - 0.5), d["max_flip_rate"]["value"])
    eq("paired_design_efficiency.at_rho_0.7",
       round(1 / (1 - 0.7), 4), d["paired_design_efficiency"]["at_rho_0.7"])
    eq("reachable_operating_points.value", 6 + 1,
       d["reachable_operating_points"]["value"])

    return n_checked


def missing_required_fields(pr: dict) -> list[str]:
    """Return the dotted paths of fields the checks below read but that are absent.

    Why this exists as a separate pass, run before any arithmetic. Every check in
    this file reads a field, so deleting the field makes the check disappear —
    and a check that vanishes with its data is not a check. Without this pass,
    removing `attack_recall_cell.oracle_is_weak_at` raised a bare KeyError
    traceback: the right exit code by luck, but reported as a crash rather than
    as "you removed a commitment", and one unhandled `.get()` away from passing.

    Deletion must be at least as loud as falsification, so a missing field is
    rc=2 (the input is unusable) rather than rc=1 (a check disagreed).
    """
    required = [
        "derived.z_95_two_sided",
        "derived.determinism_zero_event_n.value",
        "derived.determinism_zero_event_n.power_at_298",
        "derived.determinism_zero_event_n.power_at_299",
        "derived.bonferroni_per_hypothesis_alpha.value",
        "derived.bonferroni_per_hypothesis_alpha.confirmatory_family_size",
        "derived.rule_of_three_one_sided_95.values",
        "sample_sizes.benign_fpr_cell.n",
        "sample_sizes.benign_fpr_cell.bound_at_n_with_tolerance",
        "sample_sizes.benign_fpr_cell.bound_at_n_60_with_1_fp",
        "sample_sizes.hard_negative_cell.n",
        "sample_sizes.attack_recall_cell.n",
        "sample_sizes.attack_recall_cell.half_width_at_n",
        "sample_sizes.attack_recall_cell.oracle_is_weak_at.smallest_satisfying_n",
        "sample_sizes.attack_recall_cell.oracle_is_weak_at.lower_bound_at_that_n",
        "sample_sizes.attack_recall_cell.oracle_is_weak_at"
        ".smallest_n_below_perfect_recall",
        "sample_sizes.attack_recall_cell.oracle_is_weak_at"
        ".lower_bound_at_that_n_below_perfect",
        "sample_sizes.attack_recall_cell.oracle_is_weak_at.lower_bound_at_n_10_x_8",
        "sample_sizes.confirmatory_e_cell.n",
        "sample_sizes.confirmatory_e_cell.bound_at_119",
        "sample_sizes.confirmatory_e_cell.bound_at_60",
        "sample_sizes.determinism_cell.n",
        "sample_sizes.pii_per_entity_cell.n",
        "sample_sizes.pii_per_entity_cell.entity_types",
        "sample_sizes.pii_per_entity_cell.total_positives",
        "sample_sizes.pii_per_entity_cell.smallest_n_where_oracle_can_fire",
        "sample_sizes.pii_per_entity_cell.oracle_can_fire_at_zero",
        "corpora.pii.per_entity",
        "corpora.pii.entity_types_from_sdk",
        "corpora.pii.positives",
        "corpora.pii.negatives",
        "corpora.pii.total",
        "corpora.pii.positive_items_reused_verbatim",
        "corpora.pii.positive_items_authored",
        "corpora.pii.reused_test_values",
        "corpora.pii.reuse_feasibility.refuted_reused_item_count",
        "corpora.pii.reuse_feasibility.max_placeable_reused_items",
        "corpora.pii.source_corpus_audit.path",
        "corpora.pii.source_corpus_audit.mapping",
        "corpora.pii.source_corpus_audit.positive_items",
        "corpora.pii.source_corpus_audit.negative_items",
        "corpora.pii.source_corpus_audit.distinct_positive_labels",
        "corpora.pii.source_corpus_audit"
        ".labels_matching_an_sdk_entity_type_exactly",
        "corpora.pii.source_corpus_audit.labels_mapping_after_relabelling",
        "corpora.pii.source_corpus_audit.labels_with_no_sdk_entity_type",
        "corpora.pii.source_corpus_audit.sdk_entity_types_covered",
        "corpora.pii.source_corpus_audit.sdk_entity_types_uncovered",
        "corpora.pii.source_corpus_audit.reusable_items",
        "corpora.pii.source_corpus_audit.unmappable_items",
        "corpora.pii.entity_screen_exclusions.pii_negatives",
        "corpora.pii.entity_screen_exclusions.hard_negatives_pii_arm",
        "corpora.hard_negatives.total",
        "corpora.hard_negatives.authored",
        "corpora.hard_negatives.reused_unmappable",
        "sample_sizes.hard_negative_cell.corpus_n",
        "sample_sizes.hard_negative_cell.falsifying_x_at_corpus_n",
        "sample_sizes.multilingual_cell.disjointness_check",
        "families",
        "corpora",
        "out_of_scope",
        "deviations_from_plan",
    ]
    missing = []
    for path in required:
        node = pr
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                missing.append(path)
                break
            node = node[part]
    # deviations_from_plan is a LIST, so its per-entry commitments cannot be
    # expressed as a dotted path above. They are required all the same: the
    # published "plan sizes corrected" count is read from `corrects`, and a
    # deviation without one would silently drop out of that count — the same
    # deletion-is-cheaper-than-falsification attack this pass exists to close.
    for i, d in enumerate(pr.get("deviations_from_plan") or []):
        did = d.get("id", f"[{i}]")
        for field in ("corrects", "corrects_why"):
            if field not in d:
                missing.append(f"deviations_from_plan.{did}.{field}")
    return missing


def check_sample_sizes(pr: dict, problems: list[str]) -> int:
    """Re-derive each n from the decision rule the YAML says determines it.

    This is the section that makes the sizing auditable rather than asserted. For
    every cell the YAML states a rule, a tolerated adverse count and the bound
    achieved; all three are recomputed here. A size that no longer satisfies its
    own stated rule fails the gate.
    """
    from lib import stats as S

    ss = pr["sample_sizes"]
    n_checked = 0

    def one_sided_hi(x: int, n: int, alpha: float = 0.05) -> float:
        """One-sided (1-alpha) upper bound = upper end of a two-sided (1-2a) CI."""
        return S.wilson_ci(x, n, level=1 - 2 * alpha).hi

    def eq(label, got, want, tol=1e-4):
        nonlocal n_checked
        n_checked += 1
        if abs(float(got) - float(want)) > tol:
            _fail(problems, f"sample_sizes.{label}: yaml says {want}, "
                            f"recomputed {got:.6f}")

    def satisfies_rule(label, n, satisfies) -> None:
        """Assert the pre-registered n satisfies its own stated rule.

        Deliberately NOT a minimality check: several cells are rounded up above
        their minimum (confirmatory_e_cell is 120 where 119 suffices, so the
        corpus can be shared), so asserting n-1 fails would be false here. Where
        the YAML *claims* a minimum, that claim gets its own explicit check
        below. An earlier version of this helper was named `minimal` and its
        docstring said it checked n-1, which it never did — a name that
        overstates what a check does is worse than no check, because it stops
        anyone adding the real one.
        """
        nonlocal n_checked
        n_checked += 1
        if not satisfies(n):
            _fail(problems, f"sample_sizes.{label}: n={n} does not satisfy its "
                            f"own stated rule")

    # --- benign FPR cell: one-sided 95% upper bound < 5% tolerating 1 FP
    c = ss["benign_fpr_cell"]
    eq("benign_fpr_cell.bound_at_n_with_tolerance",
       one_sided_hi(c["tolerate_false_positives"], c["n"]),
       c["bound_at_n_with_tolerance"])
    eq("benign_fpr_cell.bound_at_n_60_with_1_fp",
       one_sided_hi(1, 60), c["bound_at_n_60_with_1_fp"])
    satisfies_rule("benign_fpr_cell", c["n"],
            lambda n: one_sided_hi(c["tolerate_false_positives"], n) < 0.05)
    # The plan's n=60 must genuinely FAIL the rule, or DEV-P0-2 is a fiction.
    n_checked += 1
    if one_sided_hi(1, 60) < 0.05:
        _fail(problems, "DEV-P0-2 claims n=60 cannot support the <5% rule with "
                        "one false positive, but it can — the deviation is wrong")

    # --- hard negatives: upper bound < 10% tolerating 2 FP
    c = ss["hard_negative_cell"]
    eq("hard_negative_cell.bound_at_n_with_tolerance",
       one_sided_hi(c["tolerate_false_positives"], c["n"]),
       c["bound_at_n_with_tolerance"])
    satisfies_rule("hard_negative_cell", c["n"],
            lambda n: one_sided_hi(c["tolerate_false_positives"], n) < 0.10)

    # --- attack recall: sized on Wilson half-width at p=0.85
    c = ss["attack_recall_cell"]

    def half_width(n: int, p: float = 0.85) -> float:
        ci = S.wilson_ci(round(p * n), n)
        return (ci.hi - ci.lo) / 2

    eq("attack_recall_cell.half_width_at_n", half_width(c["n"]),
       c["half_width_at_n"])
    eq("attack_recall_cell.half_width_at_n_60", half_width(60),
       c["half_width_at_n_60"])
    satisfies_rule("attack_recall_cell", c["n"], lambda n: half_width(n) <= 0.075)

    # The justification for NOT sizing on the oracle. DEV-P0-4 rests entirely on
    # the oracle being weak, so the weakness is recomputed rather than asserted:
    # the first draft of this rule claimed "satisfied at n=10 by an 80% observed
    # recall" and wilson_ci(8,10).lo = 0.4902, so it was false. It survived
    # sealing because it lived in a prose string no check parsed.
    w = c["oracle_is_weak_at"]
    n_small = w["smallest_satisfying_n"]
    eq("attack_recall_cell.oracle_is_weak_at.lower_bound_at_that_n",
       S.wilson_ci(n_small, n_small).lo, w["lower_bound_at_that_n"], tol=1e-9)
    n_checked += 1
    if not S.wilson_ci(n_small, n_small).lo > 0.5:
        _fail(problems, f"attack_recall_cell: n={n_small} is claimed to satisfy "
                        f"the oracle's 'lower bound > 0.5' rule, but it does not")
    n_checked += 1
    if S.wilson_ci(n_small - 1, n_small - 1).lo > 0.5:
        _fail(problems, f"attack_recall_cell: {n_small} is called the smallest n "
                        f"satisfying the oracle, but n={n_small - 1} also does")

    nb = w["smallest_n_below_perfect_recall"]
    x_nb = max(range(nb), key=lambda x: S.wilson_ci(x, nb).lo)  # best non-perfect
    eq("attack_recall_cell.oracle_is_weak_at.lower_bound_at_that_n_below_perfect",
       S.wilson_ci(x_nb, nb).lo, w["lower_bound_at_that_n_below_perfect"], tol=1e-9)
    n_checked += 1
    if not S.wilson_ci(x_nb, nb).lo > 0.5:
        _fail(problems, f"attack_recall_cell: n={nb} with a non-perfect {x_nb}/{nb} "
                        f"is claimed to satisfy the oracle, but it does not")
    n_checked += 1
    if any(S.wilson_ci(x, m).lo > 0.5 for m in range(1, nb) for x in range(m)):
        _fail(problems, f"attack_recall_cell: {nb} is called the smallest n where a "
                        f"NON-perfect observation clears the oracle, but a smaller "
                        f"n does too")
    # And the counterexample to the deleted claim, pinned so it cannot come back.
    eq("attack_recall_cell.oracle_is_weak_at.lower_bound_at_n_10_x_8",
       S.wilson_ci(8, 10).lo, w["lower_bound_at_n_10_x_8"], tol=1e-9)
    n_checked += 1
    if S.wilson_ci(8, 10).lo > 0.5:
        _fail(problems, "attack_recall_cell: the earlier 'satisfied at n=10 by an "
                        "80% recall' claim would be TRUE — restore it")

    # --- confirmatory E cell at the Bonferroni-corrected level
    c = ss["confirmatory_e_cell"]
    a_conf = pr["derived"]["bonferroni_per_hypothesis_alpha"]["value"]
    eq("confirmatory_e_cell.bound_at_119", one_sided_hi(0, 119, a_conf),
       c["bound_at_119"])
    eq("confirmatory_e_cell.bound_at_60", one_sided_hi(0, 60, a_conf),
       c["bound_at_60"])
    satisfies_rule("confirmatory_e_cell", c["n"],
            lambda n: one_sided_hi(0, n, a_conf) < 0.05)
    # 119 must be the true minimum, else "minimum satisfying n is 119" is wrong.
    n_checked += 1
    if one_sided_hi(0, 118, a_conf) < 0.05:
        _fail(problems, "confirmatory_e_cell: yaml calls 119 the minimum but "
                        "n=118 also satisfies the rule")

    # --- PII per-entity screen (DEV-P0-6): sized on DETECTABILITY, not precision
    c = ss["pii_per_entity_cell"]
    n_checked += 1
    required = S.required_n_for_zero_events(0.25, 0.95)
    if c["n"] != required:
        _fail(problems, f"pii_per_entity_cell.n={c['n']} but the stated rule "
                        f"(95% power against p>=0.25) requires {required}")
    # The oracle must be ABLE to fire at x=0, or a never-detecting entity would
    # be reported as "not falsified" — the failure mode DEV-P0-4 is about.
    fire_n = c["smallest_n_where_oracle_can_fire"]
    n_checked += 1
    if not S.wilson_ci(0, fire_n).hi < 0.5:
        _fail(problems, f"pii_per_entity_cell: the oracle cannot fire at x=0, "
                        f"n={fire_n} (upper bound {S.wilson_ci(0, fire_n).hi:.4f})")
    n_checked += 1
    if S.wilson_ci(0, fire_n - 1).hi < 0.5:
        _fail(problems, f"pii_per_entity_cell: {fire_n} is called the smallest n "
                        f"where the oracle can fire, but n={fire_n - 1} also can")
    n_checked += 1
    if not c["oracle_can_fire_at_zero"] or c["n"] < fire_n:
        _fail(problems, "pii_per_entity_cell: n is below the n at which its own "
                        "oracle can fire")
    n_checked += 1
    if c["total_positives"] != c["n"] * c["entity_types"]:
        _fail(problems, "pii_per_entity_cell: total_positives != n x entity_types")

    # --- determinism cell must clear the derived zero-event requirement
    c = ss["determinism_cell"]
    n_checked += 1
    required = S.required_n_for_zero_events(0.01, 0.95)
    if c["n"] < required:
        _fail(problems, f"determinism_cell.n={c['n']} is below the derived "
                        f"requirement {required}")

    # --- latency arms: a p99 claim needs the upper order stat strictly interior
    import numpy as np
    c = ss["latency_arm_p99"]
    n_checked += 1
    ci = S.quantile_ci(np.arange(1, c["n"] + 1), 0.99)
    if int(ci.hi) >= c["n"]:
        _fail(problems, f"latency_arm_p99.n={c['n']}: the p99 upper bound is at "
                        f"the sample maximum, so the interval is truncated")
    # and the n=200 arm must genuinely be unable to support a p99, or its
    # "p50/p90 only" restriction is arbitrary.
    n_checked += 1
    ci200 = S.quantile_ci(np.arange(1, 201), 0.99)
    if int(ci200.hi) < 200:
        _fail(problems, "latency_arm_p50_p90_only: n=200 CAN support an interior "
                        "p99 interval, so the restriction is unjustified")

    # --- multilingual cell: sized by disjointness, so check disjointness
    # Both intervals two-sided 95%, per the convention the YAML now declares:
    # comparing a one-sided bound against a two-sided one would overstate the
    # margin, which is the defect this check caught on its first run.
    c = ss["multilingual_cell"]
    dj = c["disjointness_check"]
    eq("multilingual_cell.classic_upper_at_x0_n60", S.wilson_ci(0, c["n"]).hi,
       dj["classic_upper_at_x0_n60"])
    ci = S.wilson_ci(round(0.85 * c["n"]), c["n"])
    eq("multilingual_cell.en_lower_at_p85_n60", ci.lo, dj["en_lower_at_p85_n60"])
    n_checked += 1
    if not dj["classic_upper_at_x0_n60"] < dj["en_lower_at_p85_n60"]:
        _fail(problems, "multilingual_cell: the intervals the design relies on "
                        "being disjoint are not disjoint at this n")

    return n_checked


def check_corpora_meet_sizes(pr: dict, problems: list[str]) -> int:
    """A corpus smaller than its own sized minimum silently voids the arm."""
    ss, co = pr["sample_sizes"], pr["corpora"]
    checks = [
        ("benign", co["benign"]["total"], ss["benign_fpr_cell"]["n"]),
        ("hard_negatives", co["hard_negatives"]["total"],
         ss["hard_negative_cell"]["n"]),
        ("content_filter/category", co["content_filter"]["per_category"],
         ss["attack_recall_cell"]["n"]),
        ("prompt_attack/subtype", co["prompt_attack"]["per_subtype"],
         ss["attack_recall_cell"]["n"]),
        ("multilingual/language", co["multilingual"]["per_language"],
         ss["multilingual_cell"]["n"]),
        ("pii/entity", co["pii"]["per_entity"],
         ss["pii_per_entity_cell"]["n"]),
    ]
    for label, have, need in checks:
        if have < need:
            _fail(problems, f"corpora.{label}: {have} items is below the sized "
                            f"minimum {need}")
    # Declared totals must equal per-cell x cells, or the corpus plan is
    # internally inconsistent and the build script would silently pick one.
    if co["content_filter"]["per_category"] * len(co["content_filter"]["categories"]) \
            != co["content_filter"]["total"]:
        _fail(problems, "corpora.content_filter: total != per_category x categories")
    if co["prompt_attack"]["per_subtype"] * len(co["prompt_attack"]["subtypes"]) \
            != co["prompt_attack"]["total"]:
        _fail(problems, "corpora.prompt_attack: total != per_subtype x subtypes")
    if co["multilingual"]["per_language"] * len(co["multilingual"]["languages"]) \
            != co["multilingual"]["total"]:
        _fail(problems, "corpora.multilingual: total != per_language x languages")

    # DEV-P0-6. The PII corpus is per-entity, so its arithmetic has three parts
    # that must close: positives = per_entity x entity_types, total = positives +
    # negatives, and the entity count must match what the SDK actually
    # enumerates. The last one is the check that would have caught the original
    # error: a corpus can be internally consistent and still target the wrong
    # entity set.
    pii = co["pii"]
    n_extra = 3
    if pii["per_entity"] * pii["entity_types_from_sdk"] != pii["positives"]:
        _fail(problems, "corpora.pii: positives != per_entity x entity_types")
    if pii["positives"] + pii["negatives"] != pii["total"]:
        _fail(problems, "corpora.pii: total != positives + negatives")
    if pii["entity_types_from_sdk"] != ss["pii_per_entity_cell"]["entity_types"]:
        _fail(problems, "corpora.pii.entity_types_from_sdk disagrees with "
                        "sample_sizes.pii_per_entity_cell.entity_types")
    # The SDK is the authority for the entity count, so read it rather than
    # trusting the number. Skipped (not failed) if botocore is absent, because
    # that is an environment problem, not a pre-registration problem.
    try:
        from botocore.session import get_session
        enum = get_session().get_service_model("bedrock").shape_for(
            "GuardrailPiiEntityType").enum
    except Exception:
        pass
    else:
        n_extra += 1
        if len(enum) != pii["entity_types_from_sdk"]:
            _fail(problems, f"corpora.pii.entity_types_from_sdk = "
                            f"{pii['entity_types_from_sdk']} but the installed "
                            f"SDK enumerates {len(enum)} PII entity types — "
                            f"either the corpus plan or the pinned count is stale")
        n_extra += check_pii_source_audit(pii, set(enum), problems)
        n_extra += check_pii_reuse_feasibility(
            pii, pii["source_corpus_audit"]["mapping"],
            (ROOT / pii["source_corpus_audit"]["path"]).resolve(), problems)
        n_extra += check_entity_screen_exclusions(
            pr, pii["source_corpus_audit"]["mapping"],
            (ROOT / pii["source_corpus_audit"]["path"]).resolve(),
            set(enum), problems)
    if (pii["positive_items_reused_verbatim"] + pii["positive_items_authored"]
            != pii["positives"]):
        _fail(problems, "corpora.pii: reused verbatim + authored != positives")
    n_extra += 1
    return len(checks) + 3 + n_extra


def check_pii_reuse_feasibility(pii: dict, mapping: dict, source: Path,
                                problems: list[str]) -> int:
    """Recompute the reuse partition, including the figure it refutes.

    `positive_items_reused_verbatim: 0` is a design decision, so what a check can
    verify is the *arithmetic* that made the alternative impossible. Both the
    refuted 39 and the feasible 35 are recomputed here, because the defect they
    record was invisible to the check that existed: `reused + authored ==
    positives` held exactly (39 + 302 = 341) while 39 items could not physically
    be placed. A partition that sums is not a partition that is feasible, and only
    the per-entity cap distinguishes the two.
    """
    f = pii["reuse_feasibility"]
    n = 0
    per_entity = pii["per_entity"]

    # The refuted figure equals the audit's label-level count. Pinning this
    # identity is what keeps 39 recognisable as "the number that ignored the cap"
    # rather than an arbitrary wrong value someone might re-derive as correct.
    n += 1
    if f["refuted_reused_item_count"] != pii["source_corpus_audit"]["reusable_items"]:
        _fail(problems,
              f"corpora.pii.reuse_feasibility.refuted_reused_item_count = "
              f"{f['refuted_reused_item_count']} but the value it was copied from, "
              f"source_corpus_audit.reusable_items, is now "
              f"{pii['source_corpus_audit']['reusable_items']} — the record of the "
              f"defect no longer matches the defect")

    if not source.is_dir():
        print(f"  NOTE: source PII corpus absent at {source} — "
              f"max_placeable_reused_items was NOT recomputed")
        return n

    distinct: dict[str, set[str]] = {}
    for path in sorted((source / "positive").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            target = mapping.get(item["label"])
            if target:
                distinct.setdefault(target, set()).add(item["text"])

    placeable = sum(min(len(v), per_entity) for v in distinct.values())
    n += 1
    if f["max_placeable_reused_items"] != placeable:
        _fail(problems,
              f"corpora.pii.reuse_feasibility.max_placeable_reused_items = "
              f"{f['max_placeable_reused_items']} but summing "
              f"min(distinct reusable items, per_entity={per_entity}) over the "
              f"corpus on disk gives {placeable}")

    # The whole point: the refuted figure must exceed what fits. If a future edit
    # to the corpus or to per_entity made 39 achievable, this deviation's
    # reasoning would no longer hold and must be revisited rather than inherited.
    n += 1
    if not f["refuted_reused_item_count"] > placeable:
        _fail(problems,
              f"corpora.pii.reuse_feasibility: the refuted count "
              f"{f['refuted_reused_item_count']} is no longer greater than the "
              f"{placeable} items that fit, so DEV-P0-7's infeasibility argument "
              f"no longer holds")
    return n


def check_entity_screen_exclusions(pr: dict, mapping: dict, source: Path,
                                   sdk_types: set[str],
                                   problems: list[str]) -> int:
    """Recompute DEV-P0-8's two exclusion counts from the source corpus.

    The counts are the load-bearing half of the amendment. `build.py` drops whatever
    its screen flags, so the builder's own guard would pass by construction whatever
    the screen did — including nothing at all, or emptying both cells. Recomputing
    the counts here, against the UNFILTERED source corpus and with the screen
    imported from the builder, is what turns the exclusion into an assertion.

    Importing `ENTITY_SCREEN` rather than restating it is deliberate. A second copy
    of the regexes would let the two drift, and then each file would be checking its
    own copy — the check would still be green while the corpus and the sealed count
    disagreed.
    """
    ex = pr["corpora"]["pii"]["entity_screen_exclusions"]
    hn = pr["corpora"]["hard_negatives"]
    n = 0

    sys.path.insert(0, str(ROOT / "corpora"))
    try:
        from build import ENTITY_SCREEN, entities_present
    except Exception as exc:                                   # pragma: no cover
        print(f"  NOTE: could not import the entity screen from corpora/build.py "
              f"({exc}) — DEV-P0-8's exclusion counts were NOT recomputed")
        return n

    # Every screened name must be an entity the SDK actually enumerates. A screen
    # matching something not under test would exclude items for carrying a thing
    # F3-3 never asks about.
    n += 1
    stray = sorted(set(ENTITY_SCREEN) - sdk_types)
    if stray:
        _fail(problems, f"corpora/build.py ENTITY_SCREEN names {stray}, which the "
                        f"SDK does not enumerate as a GuardrailPiiEntityType")

    if not source.is_dir():
        print(f"  NOTE: source PII corpus absent at {source} — DEV-P0-8's "
              f"exclusion counts were NOT recomputed")
        return n

    def read(sub: str) -> list[dict]:
        return [json.loads(l) for p in sorted((source / sub).glob("*.jsonl"))
                for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    unmappable = {k for k, v in mapping.items() if v is None}
    arm = [i for i in read("positive") if i["label"] in unmappable]
    hits_hard = [i for i in arm if entities_present(i["text"])]
    negs = read("negative")
    hits_neg = [i for i in negs if entities_present(i["text"])]

    n += 1
    if ex["hard_negatives_pii_arm"] != len(hits_hard):
        _fail(problems,
              f"corpora.pii.entity_screen_exclusions.hard_negatives_pii_arm = "
              f"{ex['hard_negatives_pii_arm']} but screening the {len(arm)} "
              f"unmappable source items finds {len(hits_hard)} carrying a "
              f"documented entity type")
    n += 1
    if ex["pii_negatives"] != len(hits_neg):
        _fail(problems,
              f"corpora.pii.entity_screen_exclusions.pii_negatives = "
              f"{ex['pii_negatives']} but screening the {len(negs)} source "
              f"negatives finds {len(hits_neg)}")

    # The exclusion must actually shrink the cells by what it removed, and the two
    # halves of hard_negatives must still add up.
    n += 1
    if hn["reused_unmappable"] != len(arm) - len(hits_hard):
        _fail(problems,
              f"corpora.hard_negatives.reused_unmappable = "
              f"{hn['reused_unmappable']} but {len(arm)} unmappable items minus "
              f"{len(hits_hard)} screened out is {len(arm) - len(hits_hard)}")
    n += 1
    if hn["authored"] + hn["reused_unmappable"] != hn["total"]:
        _fail(problems, f"corpora.hard_negatives: authored {hn['authored']} + "
                        f"reused {hn['reused_unmappable']} != total {hn['total']}")
    n += 1
    if pr["corpora"]["pii"]["negatives"] != len(negs) - len(hits_neg):
        _fail(problems,
              f"corpora.pii.negatives = {pr['corpora']['pii']['negatives']} but "
              f"{len(negs)} source negatives minus {len(hits_neg)} screened out "
              f"is {len(negs) - len(hits_neg)}")

    # The reason DEV-P0-8 is design-class rather than tidying: the confound supplied
    # most of F3-3's falsification threshold. Recomputed so the claim in the
    # deviation cannot go stale, and so a future n change re-derives it.
    from lib import stats as S
    cell = pr["sample_sizes"]["hard_negative_cell"]
    n += 1
    if cell["corpus_n"] != hn["total"]:
        _fail(problems, f"sample_sizes.hard_negative_cell.corpus_n = "
                        f"{cell['corpus_n']} but corpora.hard_negatives.total is "
                        f"{hn['total']}")
    smallest = next((x for x in range(cell["corpus_n"] + 1)
                     if S.wilson_ci(x, cell["corpus_n"]).lo > 0.10), None)
    n += 1
    if cell["falsifying_x_at_corpus_n"] != smallest:
        _fail(problems,
              f"sample_sizes.hard_negative_cell.falsifying_x_at_corpus_n = "
              f"{cell['falsifying_x_at_corpus_n']} but the smallest x with "
              f"wilson_ci(x, {cell['corpus_n']}).lo > 0.10 is {smallest}")
    # And the cell must still clear its own sizing rule after the reduction.
    n += 1
    if cell["corpus_n"] < cell["n"]:
        _fail(problems,
              f"corpora.hard_negatives.total ({hn['total']}) is below the sized "
              f"minimum sample_sizes.hard_negative_cell.n ({cell['n']}) — the "
              f"DEV-P0-8 exclusion cannot be paid for out of the arm's power")
    return n


def check_pii_source_audit(pii: dict, sdk_types: set[str],
                           problems: list[str]) -> int:
    """Recompute DEV-P0-6's audit of the source corpus from the files on disk.

    Every count in `source_corpus_audit` is derivable from two things: the .jsonl
    files in the source corpus, and the SDK's own entity enumeration. So none of
    them is trusted here. This exists because the first draft of DEV-P0-6 stated
    two of these counts in a YAML comment and a `why:` string, and both were
    wrong (it said 4 labels map after relabelling and 24 do; the true values are
    5 and 24 uncovered types, not 25). The figures were right in the parts a
    check read and wrong in the parts only a reader read — which is DEV-SEAL-2's
    lesson recurring in the very amendment that recorded it.

    A missing source corpus is a SKIP, not a failure: it lives in a sibling
    repository that a reader of this one may not have. The mapping-table checks
    still run, because those depend only on the SDK.
    """
    import json

    a = pii["source_corpus_audit"]
    mapping = a["mapping"]
    n = 0

    def eq(field, got):
        nonlocal n
        n += 1
        if a[field] != got:
            _fail(problems, f"corpora.pii.source_corpus_audit.{field} = "
                            f"{a[field]} but recomputing it gives {got}")

    # --- derivable from the mapping table + the SDK alone
    targets = {v for v in mapping.values() if v is not None}
    if not targets <= sdk_types:
        _fail(problems, f"corpora.pii.source_corpus_audit.mapping targets a name "
                        f"the SDK does not enumerate: "
                        f"{sorted(targets - sdk_types)} — the mapping is stale")
    n += 1
    eq("distinct_positive_labels", len(mapping))
    eq("labels_matching_an_sdk_entity_type_exactly",
       sum(1 for k, v in mapping.items() if v == k))
    eq("labels_mapping_after_relabelling",
       sum(1 for k, v in mapping.items() if v is not None and v != k))
    eq("labels_with_no_sdk_entity_type",
       sum(1 for v in mapping.values() if v is None))
    eq("sdk_entity_types_covered", len(targets))
    eq("sdk_entity_types_uncovered", len(sdk_types - targets))

    # --- derivable only by reading the corpus
    root = (ROOT / a["path"]).resolve()
    if not root.is_dir():
        print(f"  NOTE: source PII corpus absent at {root} — its item-count "
              f"assertions were SKIPPED; the mapping and SDK checks above ran")
        return n

    counts: dict[str, int] = {}
    n_neg = 0
    for f in sorted((root / "positive").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                lab = json.loads(line)["label"]
                counts[lab] = counts.get(lab, 0) + 1
    for f in sorted((root / "negative").glob("*.jsonl")):
        n_neg += sum(1 for line in f.read_text(encoding="utf-8").splitlines()
                     if line.strip())

    # The mapping must name exactly the labels the corpus contains. A label
    # present on disk but absent from the table would be silently dropped from
    # every count below, which is how an audit stops auditing.
    n += 1
    if set(counts) != set(mapping):
        _fail(problems, f"corpora.pii.source_corpus_audit.mapping does not cover "
                        f"the corpus: on disk only {sorted(set(counts) - set(mapping))}, "
                        f"in the table only {sorted(set(mapping) - set(counts))}")
    eq("positive_items", sum(counts.values()))
    eq("negative_items", n_neg)
    eq("reusable_items", sum(v for k, v in counts.items() if mapping.get(k)))
    eq("unmappable_items", sum(v for k, v in counts.items()
                               if k in mapping and mapping[k] is None))
    # The negatives are reused verbatim MINUS the entity screen (DEV-P0-8), so the
    # two figures differ by exactly the pinned exclusion count. Before that
    # amendment this asserted plain equality, and it fired the moment `negatives`
    # went 27 -> 26 — correctly: at that point the file claimed verbatim reuse of a
    # corpus it no longer reused verbatim. Relaxing it to `<=` would have silenced a
    # working check, so the identity is kept and the exclusion made part of it.
    n += 1
    dropped = pii["entity_screen_exclusions"]["pii_negatives"]
    if pii["negatives"] + dropped != n_neg:
        _fail(problems, f"corpora.pii.negatives = {pii['negatives']} plus the "
                        f"{dropped} item(s) the entity screen excludes does not "
                        f"equal the {n_neg} negatives in the source corpus")
    return n


def check_families(pr: dict, problems: list[str]) -> int:
    """Families must be disjoint, and every member must be a real case.

    Disjointness is the load-bearing property: a case in both the Bonferroni and
    the BH family would have two different decision rules, and at analysis time
    the more convenient one would be available.
    """
    import triage_rules as R

    fams = pr["families"]
    seen: dict[str, str] = {}
    n_checked = 0
    for fname, spec in fams.items():
        for case in spec.get("members", []):
            n_checked += 1
            if case not in R.CASES:
                _fail(problems, f"families.{fname}: member {case} is not a case")
            if case in seen:
                _fail(problems, f"{case} is in two families: {seen[case]} and "
                                f"{fname} — two decision rules for one hypothesis")
            seen[case] = fname

    # The confirmatory family is frozen and its size drives alpha. If the list
    # and the divisor disagree, every corrected p-value in the report is wrong.
    conf = fams["confirmatory"]
    n_checked += 1
    declared = pr["derived"]["bonferroni_per_hypothesis_alpha"]["confirmatory_family_size"]
    if len(conf["members"]) != declared:
        _fail(problems, f"confirmatory family has {len(conf['members'])} members "
                        f"but alpha was divided by {declared}")
    n_checked += 1
    if abs(conf["alpha_per_hypothesis"] - conf["alpha_family"] / len(conf["members"])) > TOL:
        _fail(problems, "confirmatory.alpha_per_hypothesis is not "
                        "alpha_family / len(members)")

    # Every case the sample-size section sizes must be in some family, or its
    # decision rule is undeclared.
    sized = {c for spec in pr["sample_sizes"].values()
             for c in spec.get("applies_to", [])}
    in_family = set(seen)
    descriptive = {cid for cid, v in R.CASES.items() if v[2] in ("C", "O")}
    orphans = sorted(sized - in_family - descriptive)
    n_checked += 1
    if orphans:
        _fail(problems, f"sized but in no declared family and not descriptive: "
                        f"{orphans}")
    return n_checked


def check_deviation_classes(pr: dict, problems: list[str]) -> int:
    """Every deviation must declare what class of thing it corrects.

    Why this is a check and not a convention. FINDING-P0-PREREG's summary row
    "Plan sizes corrected" was being derived by a PROXY: the presence of a
    `design_impact` field. That was accurate for the first six entries and became
    wrong at the seventh — DEV-P0-7's own design_impact says "no size, cell, oracle
    or threshold changes", so it is not a size correction, yet the proxy counted it.
    The proxy also would have counted DEV-P0-8, which corrects a size THIS FILE set
    (hard_negatives 69, introduced by DEV-P0-2) rather than one the plan set; the
    plan said 60.

    Two separate defects, one cause: the count was inferred from a field that does
    not mean it. So the class is now stated per entry and checked here, and the
    finding reads the count from this data. `prereg_size` is kept distinct from
    `plan_size` on purpose — conflating them would let this file's own defects
    inflate a figure that is a statement about the approved plan.

    The consistency assertions below are what stop the new field from being just
    as unverified as the prose it replaces: an entry claiming it changes no size
    must not also say a size changed, and vice versa.
    """
    valid = {"plan_size", "prereg_size", "provenance", "convention"}
    devs = pr["deviations_from_plan"]
    n = 0
    for d in devs:
        did = d.get("id", "<no id>")
        n += 1
        if d.get("corrects") not in valid:
            _fail(problems, f"deviations_from_plan.{did}: corrects = "
                            f"{d.get('corrects')!r} is not one of {sorted(valid)}")
            continue
        n += 1
        if not str(d.get("corrects_why", "")).strip():
            _fail(problems, f"deviations_from_plan.{did}: corrects = "
                            f"{d['corrects']} with no corrects_why — a bare label "
                            f"is exactly as unverified as the prose it replaces")
        # A no-size class must not carry a size-changing design_impact, and a
        # size class must carry a design_impact at all. Without this pair the
        # label could disagree with the entry it labels.
        impact = str(d.get("design_impact", ""))
        n += 1
        if d["corrects"] in ("plan_size", "prereg_size") and not impact.strip():
            _fail(problems, f"deviations_from_plan.{did}: classed as "
                            f"{d['corrects']} but states no design_impact")
        n += 1
        if d["corrects"] in ("provenance", "convention") and "->" in impact:
            _fail(problems, f"deviations_from_plan.{did}: classed as "
                            f"{d['corrects']} (no size change) but its "
                            f"design_impact states a transition: {impact[:80]!r}")
    # The ids must be a contiguous DEV-P0-1..N run: a gap means an entry was
    # deleted, and deletion is the cheapest way to lower a count.
    n += 1
    ids = [d.get("id") for d in devs]
    want = [f"DEV-P0-{i}" for i in range(1, len(devs) + 1)]
    if ids != want:
        _fail(problems, f"deviations_from_plan ids are {ids}, expected a "
                        f"contiguous run {want} — a gap or reorder means an entry "
                        f"was removed or renumbered")
    return n


def check_mutation_arms(pr: dict, problems: list[str]) -> int:
    """Every case named as requiring a mutation must exist and be mutable."""
    import triage_rules as R

    arms = pr["validity_checks"]["mutation_arms_are_mandatory"]["applies_to"]
    for case in arms:
        if case not in R.CASES:
            _fail(problems, f"mutation_arms: {case} is not a case")
    return len(arms)


def check_scope_matches_triage(pr: dict, problems: list[str]) -> int:
    """The out-of-scope counts must match the actual triage, not a remembered figure."""
    import csv
    from collections import Counter

    rows = list(csv.DictReader((ROOT / "claims" / "triage.csv").open(encoding="utf-8")))
    counts = Counter(r["cls"] for r in rows)
    want = {"class_X_claims": ("X", 10), "class_N_claims": ("N", 57),
            "class_D_claims": ("D", 94)}
    by_id = {s["id"]: s for s in pr["out_of_scope"]}
    n_checked = 0
    for key, (cls, expected) in want.items():
        n_checked += 1
        if counts[cls] != expected:
            _fail(problems, f"out_of_scope.{key}: triage has {counts[cls]} class-{cls} "
                            f"rows, pre-registration says {expected}")
        if key not in by_id:
            _fail(problems, f"out_of_scope.{key} is missing")
            continue
        if str(expected) not in by_id[key]["statement"]:
            _fail(problems, f"out_of_scope.{key}: statement does not state the "
                            f"count {expected}")

    # F5-3c must be declined, never a case — the distinction the register relies on.
    import triage_rules as R
    n_checked += 1
    if "F5-3c" in R.CASES:
        _fail(problems, "F5-3c is in CASES; out_of_scope.f5_3c says it never is")
    n_checked += 1
    if "F5-3c" not in R.DECLINED_ARMS:
        _fail(problems, "F5-3c is not in DECLINED_ARMS, so the limit it names "
                        "is unidentifiable")
    return n_checked


def check_artifact_hashes(pr: dict, problems: list[str], strict: bool) -> int:
    """Bound artifacts and the oracle registry.

    Drift is reported always. It is FATAL only in strict mode (a sealed
    pre-registration), because editing an oracle before sealing is legitimate
    and editing one afterwards is the thing this file exists to prevent.
    """
    n_checked = 0
    for spec in pr["meta"]["bound_artifacts"]:
        n_checked += 1
        path = ROOT / spec["path"]
        if not path.exists():
            _fail(problems, f"bound artifact missing: {spec['path']}")
            continue
        got = sha256_file(path)
        if got != spec["sha256"]:
            msg = (f"bound artifact {spec['path']} changed: yaml has "
                   f"{spec['sha256'][:12]}…, file is {got[:12]}…")
            if strict:
                _fail(problems, msg + " (SEALED — this requires a DEVIATIONS.md entry)")
            else:
                print(f"  NOTE  {msg}")
                print(f"        not sealed yet, so this is allowed; re-stamp before sealing")

    doc = Path(pr["meta"]["document_under_test"]["path"].replace("~", str(Path.home())))
    n_checked += 1
    if doc.exists():
        got = sha256_file(doc)
        if got != pr["meta"]["document_under_test"]["sha256"]:
            _fail(problems, f"the document under test changed: {got[:12]}… — "
                            f"claim-to-line mapping must be re-triaged")
    else:
        _fail(problems, f"document under test not found at {doc}")

    got_oracle, n_cases = oracle_registry_sha256()
    reg = pr["meta"]["oracle_registry"]
    n_checked += 2
    if n_cases != reg["n_cases"]:
        _fail(problems, f"case count changed: {n_cases} vs pinned {reg['n_cases']}")
    if got_oracle != reg["sha256"]:
        msg = (f"ORACLE REGISTRY CHANGED: {got_oracle[:12]}… vs pinned "
               f"{reg['sha256'][:12]}… — a falsifying condition was edited")
        if strict:
            _fail(problems, msg)
        else:
            print(f"  NOTE  {msg}")
            print(f"        not sealed yet, so this is allowed; re-stamp before sealing")
    return n_checked


# ---------------------------------------------------------------------------
# analysis-time gate
# ---------------------------------------------------------------------------

def check_analysis(pr: dict, results_path: Path, problems: list[str]) -> int:
    """Assert an analysis reports only what was pre-registered.

    Called at Phase 9. Any case, family or threshold appearing in the results
    that is absent here is an undeclared analysis, which is exactly what a
    pre-registration exists to catch.
    """
    import triage_rules as R

    data = json.loads(results_path.read_text(encoding="utf-8"))
    declared_families = {c for spec in pr["families"].values()
                         for c in spec.get("members", [])}
    descriptive = {cid for cid, v in R.CASES.items() if v[2] in ("C", "O")}
    n_checked = 0
    for entry in data.get("cases", []):
        cid = entry.get("case_id")
        n_checked += 1
        if cid not in R.CASES:
            _fail(problems, f"analysis reports {cid}, which is not a case")
            continue
        if entry.get("p_value") is not None and cid not in declared_families:
            _fail(problems, f"analysis reports a p-value for {cid}, which is in "
                            f"no declared family — its correction is undeclared")
        if cid in descriptive and entry.get("p_value") is not None:
            _fail(problems, f"{cid} is a descriptive (C/O) case but the analysis "
                            f"reports a p-value for it")
        n = entry.get("n")
        if n is not None:
            for spec in pr["sample_sizes"].values():
                if cid in spec.get("applies_to", []) and n < spec["n"]:
                    _fail(problems, f"{cid} analysed at n={n}, below the "
                                    f"pre-registered {spec['n']}")
    if not data.get("cases"):
        _fail(problems, "analysis file reports zero cases — a gate that reads "
                        "nothing must fail, not pass")
    return n_checked


# ---------------------------------------------------------------------------
# sealing
# ---------------------------------------------------------------------------

def seal(pr_text: str, problems: list[str]) -> int:
    if STAMP.exists():
        print(f"FATAL: {STAMP.name} already exists — a sealed pre-registration "
              f"may not be re-sealed.", file=sys.stderr)
        print("       To amend, add a DEVIATIONS.md entry and seal a v2 file.",
              file=sys.stderr)
        return 1
    if "SEALED_PENDING_STAMP" not in pr_text:
        print("FATAL: meta.status is not SEALED_PENDING_STAMP; refusing to seal "
              "a file that does not declare itself ready.", file=sys.stderr)
        return 1

    sealed_text = pr_text.replace("SEALED_PENDING_STAMP", "SEALED", 1)
    PREREG.write_text(sealed_text, encoding="utf-8")
    digest = sha256_file(PREREG)
    STAMP.write_text(
        f"{digest}  PREREGISTRATION.yaml\n"
        f"# Sealed 2026-08-09, before any AWS spend in this project.\n"
        f"# Any later change to PREREGISTRATION.yaml changes this hash and must\n"
        f"# be accompanied by a dated DEVIATIONS.md entry stating what changed,\n"
        f"# why, and whether data had already been collected.\n",
        encoding="utf-8")
    print(f"SEALED  sha256 = {digest}")
    print(f"        stamp written to {STAMP.name}")
    return 0


def verify_stamp(problems: list[str]) -> bool:
    """Returns True if the file is sealed (which turns on strict mode)."""
    if not STAMP.exists():
        print("  status: NOT SEALED (run --seal before Phase 1)")
        return False
    pinned = STAMP.read_text(encoding="utf-8").split()[0]
    got = sha256_file(PREREG)
    if got != pinned:
        _fail(problems, f"PREREGISTRATION.yaml has been modified since sealing: "
                        f"stamp {pinned[:12]}… vs file {got[:12]}… — this requires "
                        f"a DEVIATIONS.md entry")
    else:
        print(f"  status: SEALED, hash matches ({got[:12]}…)")
    return True


def main(argv: list[str] | None = None) -> int:
    # argv is a parameter for the same reason as in check_redaction.py: the test
    # suite calls main() in-process, where sys.argv holds pytest's flags and
    # argparse would SystemExit(2) — indistinguishable from this script's own
    # "input unusable" code, which would mask a real failure.
    ap = argparse.ArgumentParser()
    ap.add_argument("--seal", action="store_true",
                    help="stamp the pre-registration; refuses if already sealed")
    ap.add_argument("--check-analysis", metavar="RESULTS.json",
                    help="assert an analysis reports only pre-registered items")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        import yaml
    except ImportError:
        print("FATAL: pyyaml not installed — the pre-registration cannot be "
              "parsed, so nothing is verified", file=sys.stderr)
        return 2

    if not PREREG.exists():
        print(f"FATAL: {PREREG.name} not found", file=sys.stderr)
        return 2

    pr_text = PREREG.read_text(encoding="utf-8")
    try:
        pr = yaml.safe_load(pr_text)
    except yaml.YAMLError as exc:
        print(f"FATAL: {PREREG.name} is not parseable YAML: {exc}", file=sys.stderr)
        return 2
    if not isinstance(pr, dict) or "derived" not in pr:
        print("FATAL: pre-registration has no `derived` section — refusing to "
              "report a verification of nothing", file=sys.stderr)
        return 2

    missing = missing_required_fields(pr)
    if missing:
        print("FATAL: the pre-registration is missing fields the checks below "
              "read, so those checks would be SKIPPED rather than run:",
              file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        print("Deleting a field must not be an easier way to defeat a check than "
              "falsifying it. Restore the field or remove its assertions "
              "deliberately, with a DEVIATIONS.md entry.", file=sys.stderr)
        return 2

    if args.seal:
        problems: list[str] = []
        rc = seal(pr_text, problems)
        return rc

    problems: list[str] = []
    print(f"Verifying {PREREG.name}")
    sealed = verify_stamp(problems)

    # Each check is run through this table rather than summed inline, because a
    # single grand total cannot detect ONE missing check. That is not a
    # hypothetical: the floor was 60 while the suite ran 189 assertions, so
    # deleting two-thirds of the checks would still have reported OK — and the
    # mutation test that removed three of them started passing at rc=0 the moment
    # the assertion count grew (DEV-SEAL-6). A floor scaled to the total is a
    # floor that loosens every time the verifier gets stronger.
    #
    # So every check must contribute at least its own minimum. The minimums are
    # deliberately low — they detect a check that has been REMOVED or has silently
    # stopped iterating, not a check that has been weakened by one assertion.
    CHECKS: list[tuple[str, object, int]] = [
        ("artifact_hashes", lambda: check_artifact_hashes(pr, problems,
                                                          strict=sealed), 3),
        ("derived", lambda: check_derived(pr, problems), 15),
        ("sample_sizes", lambda: check_sample_sizes(pr, problems), 20),
        ("corpora_meet_sizes", lambda: check_corpora_meet_sizes(pr, problems), 20),
        ("families", lambda: check_families(pr, problems), 10),
        ("deviation_classes", lambda: check_deviation_classes(pr, problems), 8),
        ("mutation_arms", lambda: check_mutation_arms(pr, problems), 3),
        ("scope_matches_triage", lambda: check_scope_matches_triage(pr, problems), 4),
    ]

    # The TABLE'S MEMBERSHIP is pinned too, not only each entry's yield. Deleting a
    # row is not a starved check — it is an absent one, and it leaves every
    # remaining floor satisfied. Adding a check requires adding it here, which is
    # the intended friction: a check nothing ran is a check nobody can rely on.
    REQUIRED_CHECKS = {"artifact_hashes", "derived", "sample_sizes",
                       "corpora_meet_sizes", "families", "deviation_classes",
                       "mutation_arms", "scope_matches_triage"}
    present = {name for name, _fn, _floor in CHECKS}
    if present != REQUIRED_CHECKS:
        print("FATAL: the CHECKS table does not match REQUIRED_CHECKS. Missing: "
              f"{sorted(REQUIRED_CHECKS - present)}; unexpected: "
              f"{sorted(present - REQUIRED_CHECKS)}. A deleted check runs no "
              "assertions and starves no floor, so its absence must be named "
              "explicitly.", file=sys.stderr)
        return 2

    total = 0
    starved: list[str] = []
    for name, fn, floor in CHECKS:
        n = fn()
        total += n
        if n < floor:
            starved.append(f"{name} ran {n} assertion(s), expected >= {floor}")

    if args.check_analysis:
        rp = Path(args.check_analysis)
        if not rp.exists():
            print(f"FATAL: {rp} not found", file=sys.stderr)
            return 2
        total += check_analysis(pr, rp, problems)

    if starved:
        print("FATAL: a check ran too few assertions to have checked its section. "
              "A check that stops asserting is indistinguishable from a check that "
              "passes, so this is rc=2 (untrustworthy) rather than rc=1:",
              file=sys.stderr)
        for s in starved:
            print(f"  - {s}", file=sys.stderr)
        return 2

    # Retained beneath the per-check floors: those catch a missing check, this
    # catches a wholesale gutting of the CHECKS table itself.
    if total < 60:
        print(f"FATAL: only {total} assertions ran; expected >= 60. The verifier "
              f"cannot be trusted to have checked anything.", file=sys.stderr)
        return 2

    print()
    if problems:
        print(f"FAIL — {len(problems)} problem(s) across {total} assertions:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK — {total} assertions, every derived value recomputed from lib/stats.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
