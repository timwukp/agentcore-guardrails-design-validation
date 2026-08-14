#!/usr/bin/env python3
"""F10-3: does tagging only the user query of a RAG-shaped prompt bill fewer text units?

    python3 f10_billing/02_input_tagging.py --dry-run
    python3 f10_billing/02_input_tagging.py --n 2
    python3 f10_billing/02_input_tagging.py

THE SEALED ORACLE, VERBATIM (claims/triage_rules.CASES["F10-3"])
----------------------------------------------------------------
"TRUE if tagged evaluation of a RAG-shaped prompt bills fewer text units than untagged;
FALSE if identical" — method "paired tagged vs untagged on the same prompt, compare
TextUnitCount". Class S.

THE DESIGN: ONE PROMPT, TWO ARMS, ONE MANIPULATED VARIABLE
----------------------------------------------------------
Each trial pair sends the SAME two content blocks — a large retrieved-context block
(`filler(CONTEXT_CHARS)` characters of benign prose) and a small user query — through
`ApplyGuardrail` twice:

  * **tagged**   — the query block carries `qualifiers: ["guard_content"]`; the context
                   block carries no qualifiers.
  * **untagged** — neither block carries qualifiers.

The text is byte-identical across arms; the ONLY difference between the two requests is
the presence of the `qualifiers` list on the query block. `manipulation_check()` asserts
that property from the builders themselves before any call is made, because if the text
differed between arms this script would be measuring text length, not tagging.
Verified against the shipped botocore model (1.43.67): `GuardrailTextBlock` has members
`text` and `qualifiers` (`GuardrailContentQualifierList`), whose member enum is exactly
['grounding_source', 'query', 'guard_content'] — `sdk_qualifier_check()` reads that enum
from the model at runtime rather than trusting this sentence, and refuses to run if
`guard_content` is not in it.

THE QUANTUM ARITHMETIC THAT KEEPS A ROUNDING ARTIFACT OUT OF THE VERDICT
------------------------------------------------------------------------
A text unit is <= CHARS_PER_UNIT characters (reused from the sibling, which pins it to
cost_model.yaml:47's Pricing-API-verified figure), so unit counts are quantised and a
1-unit difference could be a rounding boundary rather than tagging. Two guards, both in
`rounding_guard()` and asserted before anything runs:

  * the predicted delta must be wide: with CONTEXT_CHARS=6500 and a ~150-character
    query, `units_if_identical = ceil((6500+|Q|)/1000) = 7` and
    `units_if_tagging_works = ceil(|Q|/1000) = 1`, a predicted delta of 6 units,
    required to be >= MIN_DELTA_UNITS (3 — a rounding artifact is worth at most 1 unit
    per reading and there are two readings per pair).
  * neither denominator may sit near a step boundary: both the total and the guarded
    character counts must be >= BOUNDARY_MARGIN_CHARS (100) away from the nearest
    multiple of CHARS_PER_UNIT, so a few characters of service-side block-joining or
    separator accounting cannot move either unit count by one.

USAGE IS THE CLAIM, COVERAGE IS THE MECHANISM — RECONCILED, NEVER COLLAPSED
---------------------------------------------------------------------------
The sealed oracle is about the BILLED quantity, so the verdict is decided on `usage`
(`contentPolicyUnits`, the only counter this guardrail can move). But
`guardrailCoverage.textCharacters{guarded,total}` is the mechanism: if tagging works,
the tagged arm shows `guarded < total` and the untagged arm shows `guarded == total`.
`reconcile()` records both surfaces per pair and compares them explicitly:

  * units drop AND coverage narrows      -> the surfaces agree; the drop is tagging.
  * units drop, coverage unchanged       -> the surfaces DISAGREE. The verdict still
    follows usage (the seal names the billed quantity), and the disagreement is a
    first-class finding in the payload and on stdout, never averaged away.
  * coverage narrows, units do not drop  -> same: FALSE on usage, disagreement recorded.
  * per arm, `units == ceil(guarded/CHARS_PER_UNIT)` is checked — a unit count that does
    not reconcile to its own coverage breakdown is the breakdown-vs-parent defect this
    repo has been bitten by, and it is recorded per pair as `breakdown_reconciles`.

WHICH obs_* HELPER, AND THE SEALED EVIDENCE FOR THE CHOICE
----------------------------------------------------------
F10-3's sealed binding is `Binding("EXISTENCE")` (lib/oracle.py BINDINGS), so
`oracle._decide` dispatches to the EXISTENCE branch and `_need`s `observed_bool` — an
`obs_paired` observation (improved/p_value, no observed_bool) would make `evaluate`
raise. So the constructor is `phase1.obs_existence`, exactly as F10-2 used, with
`observed = (tagged billed fewer units than untagged on every usable pair)`. The
offline suite pins both facts (the binding's kind, and that obs_paired crashes it).

Class S, but: `O.family_of("F10-3")` is `unassigned_by_seal`, F10-3 is in
`O.DECLARED_SEAL_GAPS`, `O.alpha_for` is the nominal 0.05, `O.planned_n` is None and
`O.mutation_is_mandatory` is False. The seal gives this statistical case no family, no
correction, no n and no p-value-consuming kind. Accordingly NO p-value is placed on the
Observation — it would arrive at `apply_family_corrections` as an uncorrected p under no
declared correction and be reported as a seal gap. A descriptive exact sign test over
the pair directions (lib/stats.exact_binom_test — not hand-rolled, not scipy-direct) is
carried in the payload only, clearly labelled a descriptor, because a class-S case
should show its arithmetic even when its sealed kind consumes a boolean.

With no sealed n, N_PAIRS=5 is a replicate choice, not a power claim: the relationship
under test is a deterministic unit count with an engineered >=3-unit separation, so one
disagreeing pair refutes "fewer on every pair"; the replicates exist to catch a
transient. `phase1.require_measured` still gates completion (rc=2 on shortfall).

WHAT IS REUSED FROM THE SIBLING, AND WHAT DELIBERATELY IS NOT
-------------------------------------------------------------
Reused by import from `01_text_units.py` (never re-derived): `filler` (deterministic,
exact-length benign prose — the same reasons hold: a resumed run must re-send identical
bytes, and repeated-character padding would measure a normaliser), `CHARS_PER_UNIT`
(single pinned source), `COUNTER` (`contentPolicyUnits` — same `billing` guardrail, same
reason: it has a content policy and nothing else), and `counter_of` (None-vs-0 kept
distinct). Deliberately NOT reused: `ladder_items`/`scaling`/`matching`/
`instrument_faults` — those are the length-ladder design, and their fault taxonomy is
wrong here: `guarded < total` is a FAULT for the ladder and is the PREDICTION for this
case's tagged arm, so this file has its own paired fault screen in which only the
UNTAGGED arm's partial coverage is a fault.

THIS SCRIPT SAYS NOTHING ABOUT F10-1
------------------------------------
F10-1 (input-block avoids the model-inference charge) is a Cost-Explorer question about
`Converse`/`InvokeModel` with a ~24h billing-data lag. This script reads only what
`ApplyGuardrail` reports consuming, invokes no model, reads no invoice, and its verdict
carries no claim about F10-1 in either direction.

EXIT CODES (the phase1 convention): rc reports whether the test RAN, never whether the
document was right. 0 = ran and the planned pairs were measured; 2 = nothing measured,
completion shortfall, or an unsound instrument (INCONCLUSIVE emitted); 1 = unclassified
(a design-guard or SDK-model refusal — a bug in this script or its SDK, not an outcome).
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R          # noqa: E402
import awsclients as A    # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
import stats as S         # noqa: E402


def _sibling():
    """Import `01_text_units.py`, whose name is not a Python identifier.

    Imported rather than re-derived so there is exactly one definition of the filler and
    of the text-unit quantum in this family; a second copy would be a second source of
    truth that no test compares.
    """
    path = Path(__file__).resolve().parent / "01_text_units.py"
    spec = importlib.util.spec_from_file_location("f10_text_units_sibling", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_S = _sibling()

FAMILY = "f10"
CASE = "F10-3"
GUARDRAIL_KEY = "billing"

# Reused from the sibling — see the module docstring for the list and the reasons.
CHARS_PER_UNIT: int = _S.CHARS_PER_UNIT
COUNTER: str = _S.COUNTER
filler = _S.filler

# The qualifier that marks a block as the content to evaluate. The value is checked
# against the shipped botocore model by `sdk_qualifier_check()`, not trusted from here.
GUARD_QUALIFIER = "guard_content"

# The RAG shape: a large retrieved-context block and a small user query. 6500 is chosen
# so the untagged prediction is 7 units, the tagged prediction is 1, and both character
# totals sit hundreds of characters from a step boundary — see `rounding_guard()`.
CONTEXT_CHARS = 6500
QUERY = ("Given the retrieved context above, did shipping volumes rise across every "
         "regional warehouse during the winter period while staffing levels remained "
         "unchanged?")

# Replicate pairs. NOT a sealed n — planned_n("F10-3") is None — and not a power claim:
# the quantity is a deterministic unit count with an engineered multi-unit separation,
# so one disagreeing pair refutes "fewer on every pair". Replicates catch a transient.
N_PAIRS = 5

# The rounding guards. A rounding artifact is worth at most 1 unit per reading and a
# pair takes two readings, so the predicted separation must exceed 2; and a handful of
# characters of block-joining/separator accounting must not be able to move either
# denominator across a step.
MIN_DELTA_UNITS = 3
BOUNDARY_MARGIN_CHARS = 100

LABEL_TAGGED = "tagged"
LABEL_UNTAGGED = "untagged"


# ---------------------------------------------------------------------------
# the pair: one prompt, two block lists
# ---------------------------------------------------------------------------

def context_text() -> str:
    """The retrieved-context block: deterministic, exactly CONTEXT_CHARS characters."""
    return filler(CONTEXT_CHARS)


def pair_id(rep: int) -> str:
    """A distinct id per replicate, bound to the text it will send.

    Same reasoning as the sibling's `item_id`: `arms.run_arm` resumes by trial id, so
    replicates sharing an id would be manufactured by the resume logic, and an id that
    did not hash the text could reuse a checkpoint written under different bytes.
    """
    h = sha256(f"{context_text()}\x00{QUERY}\x00{rep}".encode("utf-8")).hexdigest()
    return f"pair-r{rep}-{h[:12]}"


def pair_items(n_pairs: int = N_PAIRS) -> list[dict[str, Any]]:
    """The pairs as corpus-shaped items. `context` and `query` travel on the item so the
    analysis reads the sent lengths off the item rather than re-deriving them."""
    return [{
        "id": pair_id(rep),
        "label": "rag-pair",
        "context": context_text(),
        "query": QUERY,
        "rep": rep,
        "surface": f"rag-{CONTEXT_CHARS}+{len(QUERY)}",
        "slot": f"rep{rep}",
    } for rep in range(n_pairs)]


def blocks_tagged(item: dict) -> list[dict]:
    """The tagged arm's request body: qualifiers on the QUERY block and nowhere else."""
    return [
        {"text": {"text": item["context"]}},
        {"text": {"text": item["query"], "qualifiers": [GUARD_QUALIFIER]}},
    ]


def blocks_untagged(item: dict) -> list[dict]:
    """The untagged arm's request body: the same two blocks, no qualifiers anywhere."""
    return [
        {"text": {"text": item["context"]}},
        {"text": {"text": item["query"]}},
    ]


def block_texts(blocks: list[dict]) -> tuple[str, ...]:
    return tuple(b["text"]["text"] for b in blocks)


def block_qualifiers(blocks: list[dict]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(b["text"].get("qualifiers") or ()) for b in blocks)


def manipulation_check(item: dict) -> dict[str, Any]:
    """Is the presence of `qualifiers` genuinely the ONLY difference between the arms?

    Checked from the builders themselves, not from a comment: the texts must be
    byte-identical tuple-for-tuple, the untagged arm must carry no qualifiers on any
    block, and the tagged arm must qualify exactly one block — the query block — with
    exactly [GUARD_QUALIFIER]. If the text changed between arms, the experiment would be
    measuring text length, and no downstream statistic could notice.
    """
    t, u = blocks_tagged(item), blocks_untagged(item)
    texts_identical = block_texts(t) == block_texts(u)
    tq, uq = block_qualifiers(t), block_qualifiers(u)
    untagged_has_no_qualifiers = all(q == () for q in uq)
    tagged_qualified_blocks = [i for i, q in enumerate(tq) if q]
    tagged_exactly_one = (len(tagged_qualified_blocks) == 1
                          and tq[tagged_qualified_blocks[0]] == (GUARD_QUALIFIER,)
                          if tagged_qualified_blocks else False)
    qualified_block_is_query = bool(
        tagged_qualified_blocks
        and t[tagged_qualified_blocks[0]]["text"]["text"] == item["query"])
    return {
        "texts_identical": texts_identical,
        "untagged_has_no_qualifiers": untagged_has_no_qualifiers,
        "tagged_qualifies_exactly_one_block": tagged_exactly_one,
        "qualified_block_is_the_query": qualified_block_is_query,
        "tagged_qualifiers": [list(q) for q in tq],
        "untagged_qualifiers": [list(q) for q in uq],
        "ok": (texts_identical and untagged_has_no_qualifiers
               and tagged_exactly_one and qualified_block_is_query),
    }


# ---------------------------------------------------------------------------
# predictions and the rounding guard
# ---------------------------------------------------------------------------

def sent_chars(item: dict) -> int:
    return len(item["context"]) + len(item["query"])


def predicted_units_if_identical(item: dict) -> int:
    """If tagging changes nothing, both arms bill the whole prompt."""
    return math.ceil(sent_chars(item) / CHARS_PER_UNIT)


def predicted_units_if_tagging_works(item: dict) -> int:
    """If tagging works, the tagged arm bills only the guarded (query) characters."""
    return math.ceil(len(item["query"]) / CHARS_PER_UNIT)


def predicted_delta_units(item: dict) -> int:
    return predicted_units_if_identical(item) - predicted_units_if_tagging_works(item)


def distance_to_step_boundary(chars: int) -> int:
    """Distance in characters from the nearest multiple of CHARS_PER_UNIT (0 = exactly on
    a boundary, the most dangerous place a denominator can sit)."""
    r = chars % CHARS_PER_UNIT
    return min(r, CHARS_PER_UNIT - r)


def rounding_guard(context_chars: int | None = None,
                   query: str | None = None) -> dict[str, Any]:
    """Can a rounding boundary explain away — or manufacture — the predicted effect?

    Three conditions, all required, all stated as arithmetic in the output:

      * `delta_ok`: the predicted separation between the two hypotheses' unit counts is
        at least MIN_DELTA_UNITS. A 1-unit observed delta at a boundary is the most
        likely wrong TRUE this script could produce; a >=3-unit engineered delta cannot
        be quantisation (each reading is quantised by at most 1 unit).
      * `total_margin_ok` / `guarded_margin_ok`: both denominators (total characters
        sent; guarded query characters) are >= BOUNDARY_MARGIN_CHARS from the nearest
        step boundary, so service-side block-joining or separator accounting worth a few
        characters cannot move either unit count by one.
    """
    c = CONTEXT_CHARS if context_chars is None else context_chars
    q = QUERY if query is None else query
    total = c + len(q)
    guarded = len(q)
    units_identical = math.ceil(total / CHARS_PER_UNIT)
    units_tagging = math.ceil(guarded / CHARS_PER_UNIT)
    delta = units_identical - units_tagging
    d_total = distance_to_step_boundary(total)
    d_guarded = distance_to_step_boundary(guarded)
    delta_ok = delta >= MIN_DELTA_UNITS
    total_margin_ok = d_total >= BOUNDARY_MARGIN_CHARS
    guarded_margin_ok = d_guarded >= BOUNDARY_MARGIN_CHARS
    return {
        "chars_per_unit": CHARS_PER_UNIT,
        "context_chars": c,
        "query_chars": guarded,
        "sent_chars_total": total,
        "units_if_identical": units_identical,
        "units_if_tagging_works": units_tagging,
        "predicted_delta_units": delta,
        "min_delta_units": MIN_DELTA_UNITS,
        "delta_ok": delta_ok,
        "boundary_margin_chars": BOUNDARY_MARGIN_CHARS,
        "distance_total_to_boundary": d_total,
        "distance_guarded_to_boundary": d_guarded,
        "total_margin_ok": total_margin_ok,
        "guarded_margin_ok": guarded_margin_ok,
        "ok": delta_ok and total_margin_ok and guarded_margin_ok,
        "arithmetic": (f"units_if_identical = ceil({total}/{CHARS_PER_UNIT}) = "
                       f"{units_identical}; units_if_tagging_works = ceil({guarded}/"
                       f"{CHARS_PER_UNIT}) = {units_tagging}; predicted delta = {delta} "
                       f"units >= {MIN_DELTA_UNITS}; boundary distances {d_total} and "
                       f"{d_guarded} chars >= {BOUNDARY_MARGIN_CHARS}"),
    }


# ---------------------------------------------------------------------------
# the SDK model check — the qualifier is read out of the shipped model
# ---------------------------------------------------------------------------

def sdk_qualifier_check() -> dict[str, Any]:
    """Does the installed botocore model this run will use actually express the arm?

    Reads the LOCAL service model (no AWS call): `GuardrailTextBlock` must carry a
    `qualifiers` member and GUARD_QUALIFIER must be in its member enum, and the `usage`
    shape must carry the counter the verdict reads. A result collected under an SDK that
    silently dropped `qualifiers` would be an untagged pair reported as tagged — the one
    wrong FALSE this script could produce with no error anywhere.
    """
    import botocore.session
    model = botocore.session.get_session().get_service_model("bedrock-runtime")
    tb = model.shape_for("GuardrailTextBlock")
    has_qualifiers = "qualifiers" in tb.members
    enum = list(tb.members["qualifiers"].member.enum) if has_qualifiers else []
    usage_members = list(model.shape_for("GuardrailUsage").members)
    cov = model.shape_for("GuardrailTextCharactersCoverage")
    return {
        "sdk": A.sdk_versions(),
        "text_block_members": list(tb.members),
        "has_qualifiers_member": has_qualifiers,
        "qualifier_enum": enum,
        "guard_content_in_enum": GUARD_QUALIFIER in enum,
        "usage_members": usage_members,
        "counter_in_usage_shape": COUNTER in usage_members,
        "coverage_members": list(cov.members),
        "ok": (has_qualifiers and GUARD_QUALIFIER in enum
               and COUNTER in usage_members
               and {"guarded", "total"} <= set(cov.members)),
    }


# ---------------------------------------------------------------------------
# reading the rows
# ---------------------------------------------------------------------------

def usage_units(row: dict) -> int | None:
    """`usage[COUNTER]` off a trial row; None if absent. None and 0 stay distinct — the
    sibling's `counter_of` is reused for exactly that property."""
    return _S.counter_of(row, COUNTER)


def coverage_chars(row: dict) -> tuple[int | None, int | None]:
    tc = ((row.get("coverage") or {}).get("textCharacters") or {})
    g, t = tc.get("guarded"), tc.get("total")
    return (int(g) if isinstance(g, int) else None,
            int(t) if isinstance(t, int) else None)


def join_pairs(items: list[dict], tagged_rows: list[dict],
               untagged_rows: list[dict]) -> dict[str, Any]:
    """Join the two arms' rows into pairs by item id — by CONTENT, never by position.

    A positional zip would silently mispair the moment one arm lost a trial, and every
    downstream delta would then compare two different prompts.
    """
    t_by = {r["item_id"]: r for r in tagged_rows}
    u_by = {r["item_id"]: r for r in untagged_rows}
    pairs = []
    for it in items:
        if it["id"] in t_by and it["id"] in u_by:
            pairs.append({"item": it, "tagged": t_by[it["id"]],
                          "untagged": u_by[it["id"]]})
    return {
        "pairs": pairs,
        "unpaired_tagged": sorted(set(t_by) - set(u_by)),
        "unpaired_untagged": sorted(set(u_by) - set(t_by)),
        "n_pairs": len(pairs),
    }


# ---------------------------------------------------------------------------
# reconciliation: usage (the claim) against coverage (the mechanism)
# ---------------------------------------------------------------------------

def reconcile_pair(item: dict, trow: dict, urow: dict) -> dict[str, Any]:
    """One pair's two surfaces, recorded side by side and compared explicitly."""
    sent = sent_chars(item)
    tu, uu = usage_units(trow), usage_units(urow)
    tg, tt = coverage_chars(trow)
    ug, ut = coverage_chars(urow)
    usage_comparable = tu is not None and uu is not None
    coverage_comparable = None not in (tg, tt, ug, ut)
    fewer = bool(usage_comparable and tu < uu)
    identical = bool(usage_comparable and tu == uu)
    inverted = bool(usage_comparable and tu > uu)
    # The mechanism claim needs BOTH halves: the tagged arm evaluated less than it was
    # sent AND the untagged arm evaluated everything. A tagged shortfall beside an
    # untagged shortfall is not tagging, it is the service under-covering both arms.
    mechanism = bool(coverage_comparable and tg < tt and ug == ut)
    return {
        "item_id": item["id"],
        "sent_chars": sent,
        "tagged_units": tu,
        "untagged_units": uu,
        "usage_delta_units": (uu - tu) if usage_comparable else None,
        "usage_comparable": usage_comparable,
        "usage_says_fewer": fewer,
        "usage_identical": identical,
        "usage_inverted": inverted,
        "tagged_coverage": {"guarded": tg, "total": tt},
        "untagged_coverage": {"guarded": ug, "total": ut},
        "coverage_comparable": coverage_comparable,
        "mechanism_says_tagging_worked": mechanism,
        "mechanism_and_usage_agree": ((fewer == mechanism)
                                      if usage_comparable and coverage_comparable
                                      else None),
        # units == ceil(guarded / quantum), per arm: the breakdown must reconcile to its
        # parent, or one of the two surfaces is not denominated in what it claims.
        "tagged_units_match_guarded": (tu == math.ceil(tg / CHARS_PER_UNIT)
                                       if usage_comparable and tg is not None else None),
        "untagged_units_match_guarded": (uu == math.ceil(ug / CHARS_PER_UNIT)
                                         if usage_comparable and ug is not None else None),
        "predicted_units_if_identical": predicted_units_if_identical(item),
        "predicted_units_if_tagging_works": predicted_units_if_tagging_works(item),
        "request_ids": {"tagged": trow.get("request_id", ""),
                        "untagged": urow.get("request_id", "")},
    }


def reconcile(pairs: list[dict]) -> dict[str, Any]:
    """All pairs, aggregated — with disagreements listed, never netted out."""
    per = [reconcile_pair(p["item"], p["tagged"], p["untagged"]) for p in pairs]
    n = len(per)
    n_cmp = sum(1 for r in per if r["usage_comparable"])
    n_fewer = sum(1 for r in per if r["usage_says_fewer"])
    n_identical = sum(1 for r in per if r["usage_identical"])
    n_inverted = sum(1 for r in per if r["usage_inverted"])
    disagreements = [r for r in per if r["mechanism_and_usage_agree"] is False]
    broken = [r for r in per
              if r["tagged_units_match_guarded"] is False
              or r["untagged_units_match_guarded"] is False]
    if n == 0:
        result_class = "no_pairs"
    elif n_cmp < n:
        result_class = "usage_not_comparable"
    elif n_fewer == n:
        result_class = "fewer_on_every_pair"
    elif n_identical == n:
        result_class = "identical_on_every_pair"
    else:
        result_class = "mixed"
    return {
        "pairs": per,
        "n_pairs": n,
        "n_usage_comparable": n_cmp,
        "n_fewer": n_fewer,
        "n_identical": n_identical,
        "n_inverted": n_inverted,
        "n_mechanism_worked": sum(1 for r in per if r["mechanism_says_tagging_worked"]),
        "n_disagreeing_pairs": len(disagreements),
        "disagreeing_pairs": disagreements,
        "n_breakdown_broken": len(broken),
        "breakdown_broken_pairs": broken,
        "result_class": result_class,
        "why_not_collapsed": (
            "usage is the claim (the sealed oracle names the billed quantity) and "
            "coverage is the mechanism; a pair where they point in different directions "
            "is a finding about the API's self-consistency and is listed here, not "
            "folded into either number"),
    }


def verdict(recon: dict) -> dict[str, Any]:
    """The sealed EXISTENCE boolean, plus which sealed branch the data actually landed in.

    The sealed prose names two outcomes — fewer (TRUE) and identical (FALSE). A mixed or
    inverted result is neither named branch; it still refutes "bills fewer" (observed
    False -> FALSE under the EXISTENCE binding) and the payload says the sealed prose
    did not anticipate it, rather than pretending it was the 'identical' branch.
    """
    rc = recon["result_class"]
    return {
        "observed": rc == "fewer_on_every_pair",
        "sealed_true_branch": rc == "fewer_on_every_pair",
        "sealed_false_branch_identical": rc == "identical_on_every_pair",
        "outside_sealed_branches": rc in ("mixed",),
        "result_class": rc,
        "rule": ("TRUE iff tagged < untagged on EVERY usable pair; 'identical on every "
                 "pair' is the sealed FALSE branch; a mixed/inverted outcome is FALSE "
                 "on the sealed boolean and flagged as outside the two named branches"),
    }


# ---------------------------------------------------------------------------
# instrument faults — screened BEFORE the verdict, routed to INCONCLUSIVE
# ---------------------------------------------------------------------------

def instrument_faults(items: list[dict], tagged_rows: list[dict],
                      untagged_rows: list[dict], joined: dict) -> dict[str, Any]:
    """The ways this pair could produce a confident wrong answer.

    Differs from the sibling's screen where the designs differ: `guarded < total` is a
    fault ONLY on the untagged arm (on the tagged arm it is the prediction), and a row
    that lost its partner is a fault because an unpaired reading has no delta.
    """
    by_id = {it["id"]: it for it in items}
    all_rows = ([("tagged", r) for r in tagged_rows]
                + [("untagged", r) for r in untagged_rows])
    interventions = [{"arm": arm, "item_id": r["item_id"], "action": r.get("action"),
                      "request_id": r.get("request_id", "")}
                     for arm, r in all_rows if r.get("action") not in ("NONE", "", None)]
    missing_counter = [{"arm": arm, "item_id": r["item_id"]}
                       for arm, r in all_rows if usage_units(r) is None]
    values = [usage_units(r) for _, r in all_rows if usage_units(r) is not None]
    all_zero = bool(values) and set(values) == {0}
    missing_coverage = [{"arm": arm, "item_id": r["item_id"]}
                        for arm, r in all_rows if None in coverage_chars(r)]
    wrong_blocks = [{"arm": arm, "item_id": r["item_id"], "n_blocks": r.get("n_blocks")}
                    for arm, r in all_rows if r.get("n_blocks") != 2]
    incoherent = []
    untagged_partial = []
    total_mismatch = []
    for arm, r in all_rows:
        g, t = coverage_chars(r)
        if g is not None and t is not None and g > t:
            incoherent.append({"arm": arm, "item_id": r["item_id"],
                               "guarded": g, "total": t})
        it = by_id.get(r["item_id"])
        if t is not None and it is not None and t != sent_chars(it):
            # The service counted a different number of characters than we sent, so the
            # predictor's denominator is not the service's. A few-character separator
            # difference lands here DELIBERATELY: it is a finding about block
            # accounting, and the rounding margin means it could not have moved a unit
            # — but a predictor denominated in the wrong total must not decide a case.
            total_mismatch.append({"arm": arm, "item_id": r["item_id"],
                                   "coverage_total": t, "sent_chars": sent_chars(it)})
        if arm == "untagged" and g is not None and t is not None and g < t:
            untagged_partial.append({"item_id": r["item_id"], "guarded": g, "total": t})
    unpaired = list(joined["unpaired_tagged"]) + list(joined["unpaired_untagged"])
    return {
        "interventions": interventions,
        "n_interventions": len(interventions),
        "missing_counter": missing_counter,
        "n_missing_counter": len(missing_counter),
        "all_counters_zero": all_zero,
        "missing_coverage": missing_coverage,
        "n_missing_coverage": len(missing_coverage),
        "wrong_block_count": wrong_blocks,
        "n_wrong_block_count": len(wrong_blocks),
        "incoherent_coverage": incoherent,
        "n_incoherent_coverage": len(incoherent),
        "untagged_partial_coverage": untagged_partial,
        "n_untagged_partial_coverage": len(untagged_partial),
        "why_untagged_partial_is_a_fault": (
            "an untagged request the service under-covered means the baseline arm did "
            "not evaluate everything it was sent, so a tagged-vs-untagged delta would "
            "partly measure the service's own shortfall; on the TAGGED arm guarded < "
            "total is the prediction, not a fault"),
        "coverage_total_vs_sent": total_mismatch,
        "n_coverage_total_mismatch": len(total_mismatch),
        "unpaired_rows": unpaired,
        "n_unpaired": len(unpaired),
        "sound": not (interventions or missing_counter or all_zero or missing_coverage
                      or wrong_blocks or incoherent or untagged_partial
                      or total_mismatch or unpaired),
    }


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------

def text_unit_price_usd() -> float:
    """The verified per-unit price, read from cost_model.yaml rather than remembered.

    The file's own history is the argument: the remembered figure was wrong by 5x.
    Refuses an unverified price rather than estimating with one.
    """
    import yaml
    cm = yaml.safe_load((ROOT / "cost_model.yaml").read_text(encoding="utf-8"))
    p = cm["prices"]["guardrail_text_unit"]
    if not p.get("verified"):
        raise RuntimeError("cost_model.yaml's guardrail_text_unit price is not marked "
                           "verified; a cost disclosure built on it would be a guess "
                           "stamped as a figure")
    return float(p["usd"])


def cost_estimate(n_pairs: int) -> dict[str, Any]:
    """Dollars, both hypotheses, computed from the same predictor the verdict uses."""
    item = pair_items(1)[0]
    price = text_unit_price_usd()
    per_pair_worst = 2 * predicted_units_if_identical(item)
    per_pair_if_true = (predicted_units_if_identical(item)
                        + predicted_units_if_tagging_works(item))
    worst_units = n_pairs * per_pair_worst
    expected_units = n_pairs * per_pair_if_true
    return {
        "n_pairs": n_pairs,
        "price_usd_per_unit": price,
        "price_source": "cost_model.yaml prices.guardrail_text_unit (Pricing API, "
                        "USE1-Guardrail-ContentPolicyUnitsConsumed, verified 2026-08-09)",
        "worst_case_units": worst_units,
        "worst_case_usd": worst_units * price,
        "expected_units_if_claim_true": expected_units,
        "expected_usd_if_claim_true": expected_units * price,
        "arithmetic": (f"worst case (claim FALSE, both arms bill the full prompt): "
                       f"{n_pairs} pairs x 2 x {per_pair_worst // 2} units = "
                       f"{worst_units} units x ${price} = ${worst_units * price:.4f}; "
                       f"if the claim is TRUE: {n_pairs} x {per_pair_if_true} = "
                       f"{expected_units} units = ${expected_units * price:.4f}"),
    }


def plan(n: int | None) -> list[tuple[str, str, int]]:
    k = min(n, N_PAIRS) if n else N_PAIRS
    return [(LABEL_TAGGED, "constructed:rag-pair (2 blocks/call)", k),
            (LABEL_UNTAGGED, "constructed:rag-pair (2 blocks/call)", k)]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    ap.add_argument("--evidence-root", default=None,
                    help="root directory for evidence records (defaults to the "
                         "project's evidence store)")
    args = ap.parse_args(argv)

    guard = rounding_guard()
    if not guard["ok"]:
        print(f"FATAL: the pair's arithmetic cannot separate tagging from rounding — "
              f"{guard['arithmetic']}. This is a defect in this script's constants, "
              f"not a measurement.", file=sys.stderr)
        return 1
    check = sdk_qualifier_check()
    if not check["ok"]:
        print(f"FATAL: the installed SDK ({check['sdk']}) cannot express this arm: "
              f"qualifier enum {check['qualifier_enum']}, usage members "
              f"{check['usage_members']}. A run against it would send an untagged pair "
              f"and report it as tagged.", file=sys.stderr)
        return 1
    manip = manipulation_check(pair_items(1)[0])
    if not manip["ok"]:
        print(f"FATAL: the two arms do not differ by qualifiers alone: "
              f"{json.dumps(manip, default=str)}. The pair would measure something "
              f"other than tagging.", file=sys.stderr)
        return 1

    all_items = pair_items()
    items = all_items[:args.n] if args.n else all_items
    est = cost_estimate(len(items))

    if args.dry_run:
        return P.dry_run_banner(
            CASE, plan(args.n), blocks_per_call=2,
            text_units=est["worst_case_units"],
            text_units_why=(
                f"worst case over both hypotheses: if tagging does NOT reduce billing, "
                f"both arms bill ceil({guard['sent_chars_total']}/{CHARS_PER_UNIT}) = "
                f"{guard['units_if_identical']} units per call. The default "
                f"one-unit-per-block estimate would understate the dominant cost line"),
            extra=[
                f"THE PAIR: one RAG-shaped prompt — {guard['context_chars']} chars of "
                f"retrieved context + a {guard['query_chars']}-char user query — sent "
                f"twice with byte-identical text; the ONLY manipulated variable is "
                f"qualifiers=[{GUARD_QUALIFIER!r}] on the query block of the tagged arm",
                f"predicted units: untagged {guard['units_if_identical']}; tagged "
                f"{guard['units_if_tagging_works']} if tagging works, "
                f"{guard['units_if_identical']} if billing is identical",
                f"rounding guard: {guard['arithmetic']}",
                f"planned pairs: {len(items)} ({2 * len(items)} ApplyGuardrail calls). "
                f"planned_n({CASE}) is None — the seal names no n, so this is a "
                f"replicate choice against transients, not a power claim: the engineered "
                f">= {MIN_DELTA_UNITS}-unit separation means one disagreeing pair "
                f"refutes 'fewer on every pair'",
                f"billable: True — {est['arithmetic']}",
                f"guardrail: the provisioner's {GUARDRAIL_KEY!r} key — content filters "
                f"only, every action NONE, so {COUNTER} is the only counter that can "
                f"move and no intervention can make the two arms different treatments",
                f"qualifier verified against the shipped model (botocore "
                f"{check['sdk']['botocore']}): GuardrailTextBlock.qualifiers enum = "
                f"{check['qualifier_enum']}",
                "usage is the CLAIM and guardrailCoverage is the MECHANISM: if the "
                "units drop but coverage is unchanged, or coverage narrows but units do "
                "not, the two disagree and the disagreement is reported per pair, never "
                "collapsed; the verdict follows usage because the sealed oracle names "
                "the billed quantity",
                f"sealed binding: EXISTENCE (obs_existence, as _decide requires — an "
                f"obs_paired observation would crash the sealed branch); class S but "
                f"family {O.family_of(CASE)!r}, in DECLARED_SEAL_GAPS: an uncorrected "
                f"single hypothesis at alpha {O.alpha_for(CASE)}. No p-value is placed "
                f"on the record; a descriptive sign test travels in the payload only",
                "F10-1 is NOT touched: no model is invoked, no Cost Explorer or invoice "
                "is read (F10-1's instrument has a ~24h billing-data lag and is a "
                "different case); this verdict is about what ApplyGuardrail reports "
                "consuming",
            ])

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid = P.guardrail(GUARDRAIL_KEY, man=man)
    is_smoke = args.n is not None
    ev_root = Path(args.evidence_root) if args.evidence_root else None
    print(f"\npaired tagged-vs-untagged RAG prompt against guardrail {gid} "
          f"({len(items)} pairs, {2 * len(items)} calls)")

    specs = [
        R.ArmSpec(case_id=CASE, family=FAMILY, corpus="constructed:rag-pair",
                  guardrail_id=gid, region=args.region, label=LABEL_TAGGED,
                  multi_block=blocks_tagged, hit=R.any_detection),
        R.ArmSpec(case_id=CASE, family=FAMILY, corpus="constructed:rag-pair",
                  guardrail_id=gid, region=args.region, label=LABEL_UNTAGGED,
                  multi_block=blocks_untagged, hit=R.any_detection),
    ]
    # R.run_arm directly rather than P.run_arms: this case honours --evidence-root,
    # which run_arms does not thread through. Same shape, same progress lines.
    tallies = []
    for spec in specs:
        print(f"  arm {spec.label:20s} {len(items):>5d} items  {spec.corpus}")
        t = R.run_arm(spec, items, run_id=run_id, is_smoke=is_smoke,
                      evidence_root=ev_root)
        print(f"    -> x={t['x']} n_usable={t['n_usable']}"
              + (f"  FAILED={t['n_failed']} {t['failure_codes']}"
                 if t["n_failed"] else ""))
        tallies.append(t)

    rc = P.require_measured(tallies, is_smoke=is_smoke)
    if rc:
        return rc

    joined = join_pairs(items, tallies[0]["rows"], tallies[1]["rows"])
    faults = instrument_faults(items, tallies[0]["rows"], tallies[1]["rows"], joined)
    recon = reconcile(joined["pairs"])
    v = verdict(recon)

    if joined["n_pairs"] == 0:
        rec = O.not_measured(
            CASE, "no usable pairs: every row lost its partner, so no delta exists",
            joined={k: joined[k] for k in ("unpaired_tagged", "unpaired_untagged")})
        print("\nFATAL: zero usable pairs; the verdict is not computed.",
              file=sys.stderr)
    elif not faults["sound"]:
        why = []
        for key, label in (("n_interventions", "trial(s) intervened"),
                           ("n_missing_counter", f"row(s) had no {COUNTER}"),
                           ("n_missing_coverage", "row(s) had no coverage"),
                           ("n_wrong_block_count", "row(s) sent != 2 blocks"),
                           ("n_incoherent_coverage", "row(s) had guarded > total"),
                           ("n_untagged_partial_coverage",
                            "UNTAGGED row(s) had guarded < total"),
                           ("n_coverage_total_mismatch",
                            "row(s) reported a coverage total != characters sent"),
                           ("n_unpaired", "row(s) lost their partner")):
            if faults[key]:
                why.append(f"{faults[key]} {label}")
        if faults["all_counters_zero"]:
            why.append(f"every row reported {COUNTER}=0; a delta over an all-zero "
                       f"vector is vacuous")
        rec = O.not_measured(
            CASE, "the paired instrument was not sound: " + "; ".join(why),
            instrument_faults=faults, reconciliation_at_fault_time=recon)
        print("\nFATAL: instrument faults; the verdict is not computed. "
              + "; ".join(why), file=sys.stderr)
    else:
        o = P.obs_existence(
            CASE, v["observed"], n=recon["n_pairs"],
            result_class=recon["result_class"],
            n_pairs=recon["n_pairs"], n_fewer=recon["n_fewer"],
            n_identical=recon["n_identical"], n_inverted=recon["n_inverted"],
            n_mechanism_worked=recon["n_mechanism_worked"],
            n_disagreeing_pairs=recon["n_disagreeing_pairs"])
        rec = O.evaluate(o)

    for r in recon["pairs"]:
        print(f"  pair {r['item_id']}: tagged={r['tagged_units']} "
              f"untagged={r['untagged_units']} units; coverage tagged "
              f"{r['tagged_coverage']['guarded']}/{r['tagged_coverage']['total']}, "
              f"untagged {r['untagged_coverage']['guarded']}/"
              f"{r['untagged_coverage']['total']}"
              + ("" if r["mechanism_and_usage_agree"] else
                 "   << usage and coverage DISAGREE"))
    print(f"  result: {recon['result_class']}   "
          f"(fewer {recon['n_fewer']} / identical {recon['n_identical']} / "
          f"inverted {recon['n_inverted']} of {recon['n_pairs']} pairs)")
    if recon["n_disagreeing_pairs"]:
        print(f"  FINDING: usage and coverage disagree on "
              f"{recon['n_disagreeing_pairs']} pair(s) — recorded per pair, "
              f"verdict follows usage")
    if recon["n_breakdown_broken"]:
        print(f"  FINDING: units != ceil(guarded/{CHARS_PER_UNIT}) on "
              f"{recon['n_breakdown_broken']} pair(s) — the breakdown does not "
              f"reconcile to its parent")

    sign_test = None
    if faults["sound"] and recon["n_usage_comparable"]:
        sign_test = {
            "test": "exact binomial (sign) test over pair directions, "
                    "lib/stats.exact_binom_test",
            "x_fewer": recon["n_fewer"], "n_pairs": recon["n_pairs"],
            "p_one_sided_greater": S.exact_binom_test(
                recon["n_fewer"], recon["n_pairs"], 0.5, "greater"),
            "status": ("DESCRIPTIVE ONLY, deliberately NOT on the Observation: the "
                       "sealed kind is EXISTENCE (consumes a boolean), and "
                       f"family_of({CASE}) is {O.family_of(CASE)!r} — a p-value on the "
                       "record would arrive at apply_family_corrections as an "
                       "uncorrected p under no declared correction"),
        }

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "guardrail": {"key": GUARDRAIL_KEY, "guardrail_id": gid,
                      "purpose": (man.get("guardrails") or {})
                      .get(GUARDRAIL_KEY, {}).get("purpose", ""),
                      "why_this_guardrail": (
                          f"content filters only with every action NONE: {COUNTER} is "
                          f"the only counter that can move (usage breadth is recorded "
                          f"per row regardless), and no intervention can turn the two "
                          f"arms into different treatments")},
        "billable_calls": sum(t["n_usable"] for t in tallies),
        "cost_estimate": est,
        "mutations": 0,
        "design": {
            "manipulation_check": manip,
            "rounding_guard": guard,
            "n_pairs_planned": len(items),
            "no_power_claim": (
                f"planned_n({CASE}) is None — the seal names no n. {len(items)} pairs "
                f"catch a transient; the quantity is a deterministic unit count with an "
                f"engineered >= {MIN_DELTA_UNITS}-unit separation, so one disagreeing "
                f"pair refutes 'fewer on every pair'"),
            "arm_order": ("tagged arm fully, then untagged arm. A service-side billing "
                          "change in the minutes between the arms is a residual "
                          "confound; it is named here rather than mitigated because "
                          "the quantity is a deterministic unit count, not a latency"),
        },
        "reconciliation": recon,
        "verdict_detail": v,
        "instrument_faults": faults,
        "descriptive_sign_test": sign_test,
        "seal_notes": {
            "kind": O.BINDINGS[CASE].kind,
            "why_obs_existence": (
                "the sealed binding is EXISTENCE, so oracle._decide _need()s "
                "observed_bool; an obs_paired observation (improved/p_value) would make "
                "evaluate raise on the sealed branch. The offline suite pins both facts"),
            "family": O.family_of(CASE),
            "declared_seal_gap": CASE in O.DECLARED_SEAL_GAPS,
            "alpha": O.alpha_for(CASE),
            "consequence": ("class S with no sealed family: an uncorrected single "
                            "hypothesis at the nominal alpha, per "
                            "DEVIATIONS.md/DEV-P1-3"),
            "sealed_branches": (
                "the prose names 'fewer' (TRUE) and 'identical' (FALSE); a mixed or "
                "inverted outcome is outside both named branches — it is FALSE on the "
                "sealed boolean ('bills fewer' did not hold) and flagged as "
                "outside_sealed_branches rather than misfiled under 'identical'"),
        },
        "sibling_cases_not_decided_here": {
            "F10-1": {
                "claim": "input-blocked requests incur no model-inference charge",
                "why_not_here": (
                    "F10-1 is a Cost-Explorer/tagged-spend question about model "
                    "inference under Converse/InvokeModel, with a ~24h billing-data "
                    "lag. This script invokes no model and reads no billing-side "
                    "instrument; nothing here bears on F10-1 in either direction"),
            },
            "F10-2": {
                "claim": "TextUnitCount scales as ceil(L/1000) and matches itself",
                "why_not_here": ("published separately from a length ladder; this case "
                                 "REUSES its quantum and filler and holds the length "
                                 "fixed while manipulating only the qualifiers"),
            },
        },
        "what_true_does_not_prove": {
            "no_invoice_was_read": (
                "TRUE says the API reported consuming fewer units for the tagged "
                "request. No Cost Explorer, CUR or invoice figure is read; the dollar "
                "estimate above is a projection from the verified unit price, not a "
                "billing-side measurement (the same limit F10-2 states, for the same "
                "noise-floor reasons)"),
        },
        "instrument": {
            "operation": "ApplyGuardrail",
            "source": "INPUT",
            "output_scope": R.OUTPUT_SCOPE,
            "blocks_per_call": 2,
            "sdk_model_check": check,
            "sdk": A.sdk_versions(),
        },
    })

    if joined["n_pairs"] == 0 or not faults["sound"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
