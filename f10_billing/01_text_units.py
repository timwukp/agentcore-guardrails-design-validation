#!/usr/bin/env python3
"""F10-2: does TextUnitCount scale with content length, and does the service agree with
itself about how many units it charged?

    python3 f10_billing/01_text_units.py --dry-run
    python3 f10_billing/01_text_units.py --n 3
    python3 f10_billing/01_text_units.py

WHAT THE SEALED ORACLE ASKS, AND THE TWO HALVES IT CONTAINS
-----------------------------------------------------------
"TRUE if TextUnitCount scales with content length as documented and matches the billed
quantity; FALSE if the relationship differs." That is a conjunction of two independent
questions, and they are measured separately and reported separately, because a FALSE on
one is a different finding from a FALSE on the other and a bare FALSE distinguishes
neither:

  * **SCALING.** A text unit is `<= 1000 characters` (cost_model.yaml:47, read from the
    Pricing API on 2026-08-09). The prediction is therefore not "units rise with length"
    — that is unfalsifiable arithmetic — but the exact step function
    `units(L) = ceil(L / 1000)`, with `units(1) = units(999) = units(1000) = 1` and
    `units(1001) = 2`. The ladder below straddles every step boundary in the range it
    covers, so a per-character or per-token model, a 500-character unit, a 4000-character
    unit and an off-by-one at the boundary each produce a DIFFERENT observed vector. The
    predicted vector is computed in code from `CHARS_PER_UNIT`, never written out as a
    literal list — a hand-written expectation is the thing this project screens for.

  * **MATCHING.** The service reports the same nine usage counters in two places:
    top-level `usage` and, per assessment, `assessments[].invocationMetrics.usage`
    (verified against the 1.43.67 model: both are the same `usage` shape). "Matches the
    billed quantity" is operationalised as *these two agree*, per trial, counter by
    counter. See the honesty note below on what this does and does not license.

Both halves must hold for TRUE. `obs_existence` takes one boolean, so the conjunction is
formed here and both conjuncts travel in the payload with their own counts.

WHAT "THE BILLED QUANTITY" MEANS HERE — AND WHAT IT DOES NOT
-----------------------------------------------------------
It means **the quantity the API reports having consumed**, in the two places the API
reports it. It does **not** mean an invoice. No Cost Explorer figure, no CUR row and no
Pricing API call is read by this script, and the verdict makes no claim about dollars.

That limit is not a shortcut; it is forced. Cost Explorer's smallest granularity is a day
and its data lands hours late, this account carries ~$27k/mo of unrelated spend, and
Phase 1's total projected guardrail spend is a few dollars — so the ladder's contribution
is far below the noise floor of any billing-side instrument available to us. A verdict
that claimed to have checked an invoice would be claiming a resolution the instrument
does not have. What we can say precisely is what the service told us it charged us for,
twice, and whether those two statements agree. The payload says so in
`what_true_does_not_prove`, and the CloudWatch half is named as future work for F7 (the
`TextUnitCount` metric F7-3 counts is the same quantity aggregated per minute; joining it
to per-trial rows is F3-10's reconstruction problem, not this case's).

THE SIBLINGS THIS CASE MUST NOT ABSORB
--------------------------------------
Line 677's table row is triaged to `F10-2 F7-3` and line 802's checklist item to
`F7-3 F10-2` — so this case owns exactly the TextUnitCount *quantity*, and F7-3 owns
whether the namespace carries the seven metrics. Two neighbouring billing claims are
`unassigned_by_seal` and are in `O.DECLARED_SEAL_GAPS`'s sibling register, NOT decided
here (DEVIATIONS.md/DEV-P1-3):

  * **F10-1** — doc lines 160 and 752: an input-blocked request incurs no model-inference
    charge, an output-blocked one does. That is a claim about *model inference* under
    `Converse`/`InvokeModel` with an attached guardrail. `ApplyGuardrail` invokes no
    model at all, so no ladder run here can bear on it.
  * **F10-3** — doc line 236: tagging only the user-supplied portion of a RAG prompt bills
    fewer text units than not tagging it. That needs a tagged-vs-untagged PAIR, which is a
    different design from a length ladder; `qualifiers=['guard_content']` would be the
    instrument.

A single billing arm that reported on all three would be reporting a quantifier three
times wider than it measured.

THE LADDER, AND WHY THE FILLER IS WHAT IT IS
--------------------------------------------
Nine lengths, three trials each. Lengths straddle 1000 and 2000 from both sides
(1, 500, 999, 1000, 1001, 1500, 2000, 2001, 3000) so the step is located to within one
character at two different boundaries — one boundary could be a coincidence of the filler.

The filler is generated from a fixed lorem-style word pool with a seeded, deterministic
rotation, so:

  * it is **benign prose**, not repeated punctuation. A 3000-character run of `x` is not
    obviously a text at all, and if the service normalises or collapses whitespace or
    repeats, the ladder would measure the normaliser.
  * it is **exactly** the requested length, verified with an assertion before the call.
    A ladder whose 1001-character item is 1000 characters long tests nothing at the
    boundary, and the boundary is the whole design.
  * it is **deterministic** — the same length always yields the same string, so a resumed
    run re-sends the identical text (and `Date.now`-style entropy cannot leak in).

Three trials per length is not a power claim and is not pretending to be one. The
relationship under test is an exact step function, so a single disagreeing trial refutes
it; the replicates exist to catch a transient (a truncated request, a retry that
re-billed) rather than to estimate a rate. `planned_n('F10-2')` is None — the seal names
no n for this case (DEVIATIONS.md/DEV-P1-4's class of gap), so `n_met` is vacuous and no
power statement is available or claimed.

THE INSTRUMENT'S OWN FAILURE MODES, CHECKED BEFORE THE VERDICT
--------------------------------------------------------------
Three ways this could produce a confident wrong answer, each screened explicitly:

  1. **An intervention.** A blocked request is a different treatment from an evaluated
     one. The provisioner's `billing` guardrail sets every action to NONE while leaving
     every filter ENABLED, so evaluation happens and intervention cannot. Any trial whose
     `action` is not `NONE` is counted as an instrument fault and routes the case to
     INCONCLUSIVE rather than into the scaling fit.
  2. **Partial coverage.** `guardrailCoverage.textCharacters` reports `guarded` and
     `total`. If `guarded < total` the service evaluated less than we sent, and the unit
     count is then correct for what it evaluated while our predictor is denominated in
     what we sent. Checked per trial; a shortfall is a fault, not a FALSE.
  3. **A zero counter.** If `contentPolicyUnits` is absent or 0 on every trial there is
     nothing to fit, and a "scaling holds" verdict over an all-zero vector would be
     vacuous in the precise sense of `feedback_vacuous_test_check`. Checked as a
     precondition.

WHICH COUNTER IS READ
---------------------
`contentPolicyUnits` — the guardrail here has a content policy and nothing else, so it is
the only counter that can be non-zero, and it is the one the $0.15/1K price is denominated
in (`USE1-Guardrail-ContentPolicyUnitsConsumed`). All nine counters are recorded per trial
regardless; the sum across counters is reported beside the single counter so a reader can
see that no other policy contributed.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R          # noqa: E402
import awsclients as A    # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402

FAMILY = "f10"
CASE = "F10-2"
GUARDRAIL_KEY = "billing"

# The documented text-unit size, from the verified cost model rather than from memory:
# cost_model.yaml:47, "1 text unit (<= 1000 characters)", sourced from the Pricing API
# usagetype USE1-Guardrail-ContentPolicyUnitsConsumed. The predictor below is built from
# this constant, so a wrong constant produces a wrong PREDICTION and a visible mismatch
# rather than a silently adjusted expectation.
CHARS_PER_UNIT = 1000

# The counter the ladder is denominated in. See the docstring: this guardrail has only a
# content policy, so it is the only counter that can move.
COUNTER = "contentPolicyUnits"

# The ladder. Straddles the 1000 and 2000 boundaries from both sides so the step is
# located twice, and includes 1 so a per-call floor (any request costs at least one unit)
# is distinguishable from a per-character rate.
LENGTHS = (1, 500, 999, 1000, 1001, 1500, 2000, 2001, 3000)
TRIALS_PER_LENGTH = 3

# Benign filler words. Ordinary English prose: see the docstring on why not `"x" * n`.
FILLER_WORDS = (
    "the", "quarterly", "report", "notes", "that", "shipping", "volumes", "rose",
    "across", "every", "regional", "warehouse", "during", "the", "winter", "period",
    "while", "staffing", "levels", "remained", "unchanged", "and", "maintenance",
    "windows", "were", "scheduled", "for", "the", "following", "month",
)

LABEL = "ladder"


def filler(length: int) -> str:
    """A benign string of EXACTLY `length` characters, deterministic in `length`.

    Deterministic and exact are both load-bearing. Exact, because the boundary items are
    the design: a 1001-character item that is actually 1000 characters long moves the
    observation to the other side of the step being located. Deterministic, because
    `arms.run_arm` resumes by trial id — a resumed run must re-send the same bytes, or the
    resumed trials would be a different treatment silently pooled with the first ones.

    Built by rotating the word pool rather than repeating one word, and closed by
    truncation followed by an assertion. The truncation can cut a word; that is fine and
    is preferable to padding with a character the pool does not contain, which would make
    the tail of every long item a run of the same byte.
    """
    if length < 1:
        raise ValueError(f"length must be >= 1, got {length}")
    # `joined` is the length `" ".join(parts)` will actually have: k words contribute
    # sum(len) + (k-1) separators, NOT sum(len) + k. Accumulating len(w)+1 per word
    # overcounts by exactly one, so the loop could exit one character short whenever the
    # true joined length landed on `length - 1`, and the assertion below would fire. The
    # current 30-word pool never lands there for the nine ladder lengths, which is why
    # only a shortened pool exposed it — a latent trap that would have surfaced the first
    # time a length or a word was changed.
    parts: list[str] = []
    joined = 0
    i = 0
    while joined < length:
        w = FILLER_WORDS[i % len(FILLER_WORDS)]
        joined += len(w) + (1 if parts else 0)   # separator only between words
        parts.append(w)
        i += 1
    s = " ".join(parts)[:length]
    if len(s) != length:
        raise AssertionError(
            f"filler({length}) produced {len(s)} characters. The ladder's boundary items "
            f"are the whole design; an off-by-one here would move an observation to the "
            f"other side of the step it exists to locate")
    return s


def predicted_units(length: int) -> int:
    """`ceil(length / CHARS_PER_UNIT)` — the documented step function.

    Computed, not tabulated. A literal expectation list would be a second label over this
    same computation, and the first thing to go stale if `CHARS_PER_UNIT` were ever
    corrected (`feedback_label_must_match_computation`).
    """
    return math.ceil(length / CHARS_PER_UNIT)


def item_id(length: int, rep: int) -> str:
    """A distinct id per (length, replicate).

    `arms.run_arm` skips any trial id the checkpoint already holds, so three replicates
    sharing an id would send ONE call and report three done — replicates manufactured by
    the resume logic. The id includes the text's own hash so an edit to `filler` or to
    `CHARS_PER_UNIT` cannot silently reuse a checkpoint written under the old text.
    """
    h = sha256(f"{length}\x00{rep}\x00{filler(length)}".encode("utf-8")).hexdigest()
    return f"L{length:05d}-r{rep}-{h[:12]}"


def ladder_items(lengths: tuple[int, ...] = LENGTHS,
                 reps: int = TRIALS_PER_LENGTH) -> list[dict[str, Any]]:
    """The full ladder as corpus-shaped items.

    Ordered by replicate and then by length — r0 across all nine lengths, then r1, then r2
    — rather than by length. Grouping the three replicates of one length together would
    put them adjacent in time, so a transient service-side change part-way through the run
    would hit one length entirely and look like a length effect. Interleaving means a drift
    shows up across replicates, where it is visible as a drift.
    """
    out: list[dict[str, Any]] = []
    for rep in range(reps):
        for L in lengths:
            out.append({
                "id": item_id(L, rep),
                "label": LABEL,
                "text": filler(L),
                # Carried on the item so the analysis reads the intended length off the
                # row instead of recomputing it from the text, which would agree with
                # itself by construction even if the wrong text were sent.
                "length": L,
                "rep": rep,
                "predicted_units": predicted_units(L),
                "surface": f"filler-{L}",
                "slot": f"rep{rep}",
            })
    return out


def plan(n: int | None) -> list[tuple[str, str, int]]:
    items = ladder_items()
    return [(LABEL, f"constructed ladder, {len(LENGTHS)} lengths x "
                    f"{TRIALS_PER_LENGTH} reps", len(items[:n] if n else items))]


def projected_text_units(items: list[dict[str, Any]]) -> int:
    """The ladder's true text-unit cost, summed from the predictor.

    `dry_run_banner`'s default projection is one unit per content block, which is right
    for every case whose items are short and wrong here by construction: this case's items
    deliberately cross the 1000-character step, so the default would understate the
    dominant cost line of the one case whose subject IS that cost line.
    """
    return sum(predicted_units(it["length"]) for it in items)


def counter_of(row: dict[str, Any], counter: str = COUNTER) -> int | None:
    """`usage[counter]` off a trial row, or None if the counter is absent.

    None and 0 are kept distinct. "The service reported zero units" and "the service did
    not report this counter" have different remedies — the first is a finding about
    billing, the second means we are reading the wrong field — and collapsing them with
    `.get(counter, 0)` would report the second as the first.
    """
    u = row.get("text_units") or {}
    v = u.get(counter)
    return int(v) if isinstance(v, (int, float)) else None


def scaling(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Observed vs predicted units per length, and where they part company.

    Per length rather than pooled: a pooled "mean units per 1000 characters" would be a
    ratio that a per-character model and a step function can both produce, so it cannot
    distinguish the hypotheses the ladder was built to distinguish. The per-length vector
    can.
    """
    by_len: dict[int, dict[str, Any]] = {}
    for r in rows:
        L = int(r.get("length") or 0)
        cell = by_len.setdefault(L, {"length": L, "predicted": predicted_units(L),
                                     "observed": [], "missing_counter": 0,
                                     "chars_sent": len(r.get("text") or "") or None,
                                     "item_ids": [], "request_ids": []})
        v = counter_of(r)
        if v is None:
            cell["missing_counter"] += 1
        else:
            cell["observed"].append(v)
        cell["item_ids"].append(r["item_id"])
        cell["request_ids"].append(r.get("request_id", ""))
    cells = []
    for L in sorted(by_len):
        c = by_len[L]
        obs = c["observed"]
        distinct = sorted(set(obs))
        c["observed_distinct"] = distinct
        c["n_trials"] = len(obs) + c["missing_counter"]
        # Agreement requires that EVERY replicate matched, not that the mean or the modal
        # value did. One replicate off by one at a boundary is the observation that
        # falsifies an exact step function, and an average would absorb it.
        c["all_match_predicted"] = bool(obs) and distinct == [c["predicted"]]
        c["replicates_agree"] = len(distinct) <= 1
        cells.append(c)
    mismatched = [c for c in cells if not c["all_match_predicted"]]
    return {
        "chars_per_unit_assumed": CHARS_PER_UNIT,
        "chars_per_unit_source": ("cost_model.yaml:47, verified against the Pricing API "
                                  "usagetype USE1-Guardrail-ContentPolicyUnitsConsumed"),
        "counter_read": COUNTER,
        "cells": cells,
        "n_lengths": len(cells),
        "n_lengths_matching": len(cells) - len(mismatched),
        "mismatched_lengths": [c["length"] for c in mismatched],
        "holds": bool(cells) and not mismatched,
        "predicted_vector": {str(c["length"]): c["predicted"] for c in cells},
        "observed_vector": {str(c["length"]): c["observed_distinct"] for c in cells},
        "why_per_length": ("a pooled units-per-1000-characters ratio is producible by "
                           "both a per-character model and a step function, so it cannot "
                           "distinguish the hypotheses this ladder was built to separate"),
    }


def matching(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Does top-level `usage` agree with `invocationMetrics.usage`, per trial?

    Counter by counter over the union of both key sets, so a counter present in one place
    and absent from the other is a disagreement rather than being skipped. An absent
    `invocationMetrics.usage` block entirely is reported separately: that is "the service
    reports usage in one place only", which is a different fact from "the two places
    disagree", and only the second is a FALSE for this half.
    """
    agree = 0
    disagreements: list[dict[str, Any]] = []
    n_no_invocation_block = 0
    for r in rows:
        top = {k: v for k, v in (r.get("text_units") or {}).items()}
        inv = {k: v for k, v in (r.get("invocation_usage") or {}).items()}
        if not inv:
            n_no_invocation_block += 1
            continue
        keys = sorted(set(top) | set(inv))
        diff = {k: {"usage": top.get(k), "invocation_usage": inv.get(k)}
                for k in keys if top.get(k) != inv.get(k)}
        if diff:
            disagreements.append({"item_id": r["item_id"],
                                  "length": r.get("length"),
                                  "request_id": r.get("request_id", ""),
                                  "differing_counters": diff})
        else:
            agree += 1
    n_comparable = len(rows) - n_no_invocation_block
    return {
        "n_rows": len(rows),
        "n_comparable": n_comparable,
        "n_agreeing": agree,
        "n_disagreeing": len(disagreements),
        "n_no_invocation_usage_block": n_no_invocation_block,
        "disagreements": disagreements[:20],
        "n_disagreements_shown": min(20, len(disagreements)),
        # The half holds only if something was actually compared. With no
        # `invocationMetrics.usage` anywhere, `n_disagreeing == 0` is true of an empty set
        # and would license "matches the billed quantity" from zero comparisons.
        "holds": n_comparable > 0 and not disagreements,
        "comparison": ("top-level `usage` vs `assessments[].invocationMetrics.usage`, "
                       "counter by counter over the union of both key sets"),
        "why_union": ("a counter present in one place and absent from the other is a "
                      "disagreement; intersecting the key sets would skip exactly that"),
    }


def instrument_faults(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The three ways this ladder could produce a confident wrong answer. See the docstring.

    Returned as data with per-trial detail rather than as three booleans, because the
    remedy differs per fault and "the instrument was unsound" without saying which trial
    and how is not actionable.
    """
    interventions = [{"item_id": r["item_id"], "length": r.get("length"),
                      "action": r.get("action"),
                      "action_reason": r.get("action_reason"),
                      "detected_types": r.get("detected_types"),
                      "request_id": r.get("request_id", "")}
                     for r in rows if r.get("action") not in ("NONE", "", None)]
    partial = []
    for r in rows:
        tc = ((r.get("coverage") or {}).get("textCharacters") or {})
        guarded, total = tc.get("guarded"), tc.get("total")
        if isinstance(guarded, int) and isinstance(total, int) and guarded < total:
            partial.append({"item_id": r["item_id"], "length": r.get("length"),
                            "guarded": guarded, "total": total,
                            "request_id": r.get("request_id", "")})
    missing = [r["item_id"] for r in rows if counter_of(r) is None]
    values = [counter_of(r) for r in rows if counter_of(r) is not None]
    all_zero = bool(values) and set(values) == {0}
    # `coverage.total` vs the characters we sent: a service-side total that does not equal
    # our own string length means the predictor's denominator is not the quantity the
    # service measured, and every "match" below would then be a coincidence.
    length_disagreements = []
    for r in rows:
        tc = ((r.get("coverage") or {}).get("textCharacters") or {})
        total = tc.get("total")
        L = r.get("length")
        if isinstance(total, int) and isinstance(L, int) and total != L:
            length_disagreements.append({"item_id": r["item_id"], "sent_chars": L,
                                         "coverage_total": total,
                                         "request_id": r.get("request_id", "")})
    return {
        "interventions": interventions,
        "n_interventions": len(interventions),
        "why_intervention_is_a_fault": (
            "a blocked request is a different treatment from an evaluated one; the "
            "provisioner's `billing` guardrail sets every action to NONE with every "
            "filter ENABLED precisely so evaluation happens and intervention cannot"),
        "partial_coverage": partial,
        "n_partial_coverage": len(partial),
        "why_partial_is_a_fault": (
            "guarded < total means the service evaluated less than we sent, so the unit "
            "count is correct for what it evaluated while the predictor is denominated in "
            "what we sent"),
        "coverage_total_vs_sent": length_disagreements,
        "n_coverage_total_mismatch": len(length_disagreements),
        "missing_counter_items": missing,
        "n_missing_counter": len(missing),
        "all_counters_zero": all_zero,
        "why_all_zero_is_a_fault": (
            "a scaling verdict over an all-zero vector holds by construction and says "
            "nothing about scaling"),
        "sound": not (interventions or partial or length_disagreements
                      or missing or all_zero),
    }


def usage_breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every counter the service reported non-zero, across all trials.

    Reported so the choice of `contentPolicyUnits` is auditable rather than asserted: if
    another counter moved, the single-counter reading would be understating what the
    request consumed, and the reader can see it here.
    """
    totals: Counter = Counter()
    seen: set[str] = set()
    for r in rows:
        for k, v in (r.get("text_units") or {}).items():
            seen.add(k)
            if isinstance(v, (int, float)):
                totals[k] += int(v)
    return {
        "counters_seen": sorted(seen),
        "counter_totals": dict(sorted(totals.items())),
        "nonzero_counters": sorted(k for k, v in totals.items() if v),
        "counter_used_for_scaling": COUNTER,
        "why_reported": ("the guardrail has only a content policy, so no other counter "
                         "should move; showing all of them makes that auditable rather "
                         "than asserted"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    all_items = ladder_items()
    items = all_items[:args.n] if args.n else all_items

    if args.dry_run:
        pred = {str(L): predicted_units(L) for L in LENGTHS}
        return P.dry_run_banner(
            CASE, plan(args.n),
            text_units=projected_text_units(items),
            text_units_why=(
                f"sum of ceil(length/{CHARS_PER_UNIT}) over the ladder — NOT one unit per "
                f"call. This case's items deliberately cross the {CHARS_PER_UNIT}-character "
                f"step, so the default one-unit-per-block estimate would understate the "
                f"dominant cost line of the one case whose subject is that cost line"),
            extra=[
                f"guardrail: the provisioner's {GUARDRAIL_KEY!r} key — all five content "
                f"filters at MEDIUM with every action NONE and every filter ENABLED, so "
                f"evaluation happens and intervention cannot. An intervention would be a "
                f"second treatment pooled into the ladder",
                f"predicted units per length (computed from CHARS_PER_UNIT={CHARS_PER_UNIT}, "
                f"cost_model.yaml:47): {pred}",
                f"the ladder straddles {CHARS_PER_UNIT} and {2 * CHARS_PER_UNIT} from both "
                f"sides, so a per-character model, a 500-char unit, a 4000-char unit and an "
                f"off-by-one at the boundary each produce a DIFFERENT observed vector",
                "TWO halves, both required for TRUE and reported separately: SCALING "
                "(units == ceil(L/1000) at every length) and MATCHING (top-level `usage` "
                "== assessments[].invocationMetrics.usage, counter by counter)",
                "'the billed quantity' means THE QUANTITY THE API REPORTS CONSUMING, in "
                "the two places it reports it. No Cost Explorer, no CUR, no invoice is "
                "read, and the verdict makes no claim about dollars",
                "F10-1 (input-block vs output-block inference charge, doc lines 160/752) "
                "and F10-3 (tagged vs untagged RAG saving, doc line 236) are "
                "unassigned_by_seal and are NOT decided here — ApplyGuardrail invokes no "
                "model, and a length ladder is not a tagged/untagged pair",
                f"no pre-registered n: planned_n({CASE}) is None, so n_met is vacuous and "
                f"no power statement is available. {TRIALS_PER_LENGTH} replicates per "
                f"length catch a transient, they do not estimate a rate — an exact step "
                f"function is refuted by one disagreeing trial",
                "three instrument faults are screened BEFORE the verdict and route to "
                "INCONCLUSIVE, not to FALSE: an intervention, guarded<total coverage, and "
                "an absent or all-zero counter"])

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid = P.guardrail(GUARDRAIL_KEY, man=man)
    is_smoke = args.n is not None
    print(f"\ntext-unit ladder against guardrail {gid} "
          f"({len(items)} trials over {len(sorted({it['length'] for it in items}))} lengths)")

    spec = R.ArmSpec(case_id=CASE, family=FAMILY, corpus="constructed:ladder",
                     guardrail_id=gid, region=args.region, label=LABEL,
                     # The ladder counts UNITS, not detections, so no hit reader applies.
                     # `any_detection` is used so `x` at least means something auditable —
                     # it should be 0 throughout, and a non-zero x is the same signal the
                     # intervention fault check reads. The oracle does not consult it.
                     hit=R.any_detection)
    t = P.run_arms([spec], [items], run_id=run_id, is_smoke=is_smoke)[0]

    rc = P.require_measured([t], is_smoke=is_smoke)
    if rc:
        return rc

    # The intended length travels on the corpus item, not on the trial row, so it is
    # joined back here by item id. Recomputing it from the row's absent text would be
    # impossible, and recomputing it from the id would agree with itself by construction.
    by_id = {it["id"]: it for it in items}
    rows = []
    for r in t["rows"]:
        it = by_id.get(r["item_id"], {})
        rows.append({**r, "length": it.get("length"), "rep": it.get("rep"),
                     "text": it.get("text", "")})

    faults = instrument_faults(rows)
    sc = scaling(rows)
    mt = matching(rows)
    breadth = usage_breadth(rows)

    # Faults first: an unsound instrument cannot produce either half's verdict, and
    # computing one anyway would publish a number the instrument cannot support.
    # `O.not_measured`, not `evaluate(obs_recorded(...))` — F10-2's sealed kind is
    # EXISTENCE, so `_decide` would dispatch to EXISTENCE's `_need(observed_bool)` and
    # raise on an observation carrying only detail (DEVIATIONS.md/DEV-P1-8).
    if not faults["sound"]:
        why = []
        if faults["n_interventions"]:
            why.append(f"{faults['n_interventions']} trial(s) intervened")
        if faults["n_partial_coverage"]:
            why.append(f"{faults['n_partial_coverage']} trial(s) had guarded < total")
        if faults["n_coverage_total_mismatch"]:
            why.append(f"{faults['n_coverage_total_mismatch']} trial(s) reported a "
                       f"coverage total differing from the characters sent")
        if faults["n_missing_counter"]:
            why.append(f"{faults['n_missing_counter']} trial(s) reported no "
                       f"{COUNTER} counter")
        if faults["all_counters_zero"]:
            why.append(f"every trial reported {COUNTER}=0, so a scaling verdict would "
                       f"hold by construction")
        rec = O.not_measured(
            CASE,
            "the ladder's instrument was not sound: " + "; ".join(why),
            instrument_faults=faults)
        print("\nFATAL: instrument faults; the verdict is not computed. "
              + "; ".join(why), file=sys.stderr)
    else:
        # The conjunction the sealed oracle names, formed here because `obs_existence`
        # takes one boolean. Both conjuncts travel in the payload with their own counts so
        # a FALSE says WHICH half failed.
        observed = bool(sc["holds"] and mt["holds"])
        # n is the ladder's usable trial count. F10-2 has no sealed planned_n, so this
        # cannot change its `n_met` — it is passed because a published record whose
        # n_usable is 0 while the run billed 27 calls is wrong on its face, whether or not
        # any gate happens to read it.
        o = P.obs_existence(
            CASE, observed, n=t["n_usable"],
            scaling_holds=sc["holds"], matching_holds=mt["holds"],
            n_lengths=sc["n_lengths"], n_lengths_matching=sc["n_lengths_matching"],
            n_comparable=mt["n_comparable"], n_disagreeing=mt["n_disagreeing"])
        rec = O.evaluate(o)

    print(f"  scaling  : {'holds' if sc['holds'] else 'FAILS'}   "
          f"{sc['n_lengths_matching']}/{sc['n_lengths']} lengths match "
          f"ceil(L/{CHARS_PER_UNIT})")
    if sc["mismatched_lengths"]:
        print(f"    mismatched lengths: {sc['mismatched_lengths']}")
        for c in sc["cells"]:
            if not c["all_match_predicted"]:
                print(f"      L={c['length']:>5d} predicted={c['predicted']} "
                      f"observed={c['observed_distinct']}")
    print(f"  matching : {'holds' if mt['holds'] else 'FAILS'}   "
          f"{mt['n_agreeing']}/{mt['n_comparable']} trials agree between "
          f"`usage` and `invocationMetrics.usage`")

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "guardrail": {"key": GUARDRAIL_KEY, "guardrail_id": gid,
                      "purpose": (man.get("guardrails") or {})
                      .get(GUARDRAIL_KEY, {}).get("purpose", ""),
                      "why_actions_are_none": (
                          "a text unit is consumed by EVALUATION, not by intervention, so "
                          "a billing ladder wants every filter enabled and every action "
                          "NONE. Under BLOCK, a filler string that tripped a filter would "
                          "make the ladder a mixture of two treatments")},
        "billable_calls": t["n_usable"],
        "billable_text_units_predicted": projected_text_units(items),
        "mutations": 0,
        "ladder": {"lengths": list(LENGTHS), "trials_per_length": TRIALS_PER_LENGTH,
                   "n_items": len(items),
                   "order": ("replicate-major: r0 across all lengths, then r1, then r2. "
                             "Grouping a length's replicates together would make a "
                             "service-side drift part-way through the run look like a "
                             "length effect"),
                   "filler": {"pool_size": len(FILLER_WORDS),
                              "deterministic_in_length": True,
                              "why_prose_not_repeats": (
                                  "a 3000-character run of one character is not obviously "
                                  "a text; if the service collapses whitespace or repeats, "
                                  "the ladder would measure the normaliser")}},
        "scaling": sc,
        "matching": mt,
        "usage_breadth": breadth,
        "instrument_faults": faults,
        "arm_tally": {k: v for k, v in t.items() if k != "rows"},
        "x_is_unused": ("the tally's `x` counts any detection, which this case's oracle "
                        "does not read — it counts TEXT UNITS. It should be 0 throughout, "
                        "and a non-zero value is the same signal the intervention fault "
                        "check reads"),
        "verdict_rule": (
            f"TRUE iff BOTH halves hold: units == ceil(L/{CHARS_PER_UNIT}) at every one of "
            f"the {len(LENGTHS)} lengths AND top-level `usage` equals "
            f"`assessments[].invocationMetrics.usage` on every comparable trial. Either "
            f"half failing gives FALSE; an unsound instrument gives INCONCLUSIVE"),
        "false_means_what": (
            "scaling FALSE means the unit is not 1000 characters or the step is not where "
            "the price sheet puts it — a cost-model finding that changes every projection "
            "in COST.md. matching FALSE means the service reports two different consumed "
            "quantities for one request, which is a finding about the API's own "
            "self-consistency. They are separate amendments"),
        "what_true_does_not_prove": {
            "no_invoice_was_read": (
                "TRUE says the API reported the documented quantity in both of the places "
                "it reports it. It does NOT say an invoice charged that amount: no Cost "
                "Explorer, CUR or Pricing figure is read here"),
            "why_not": (
                "Cost Explorer's finest granularity is a day and it lands hours late; this "
                "account carries ~$27k/mo of unrelated spend and the ladder's own cost is "
                "cents, so the signal is far below the noise floor of any billing-side "
                "instrument available to us. A dollar claim would assert a resolution the "
                "instrument does not have"),
            "cloudwatch_half": (
                "the CloudWatch `TextUnitCount` metric is the same quantity aggregated per "
                "minute and dimensioned by GuardrailArn. Whether a per-trial row can be "
                "joined to it is F3-10's reconstruction question, and whether the "
                "namespace carries the metric at all is F7-3's"),
            "one_guardrail_one_policy": (
                f"measured on a content-filter-only guardrail, so it bounds "
                f"{COUNTER} and says nothing about the per-policy unit accounting of "
                f"topics, words, PII or grounding — usage_breadth shows those counters "
                f"stayed at zero here"),
        },
        "sibling_cases_not_decided_here": {
            "F10-1": {
                "claim": ("input-blocked requests incur no model-inference charge; "
                          "output-blocked ones do (doc lines 160, 752)"),
                "why_not_here": ("that is a claim about MODEL INFERENCE under "
                                 "Converse/InvokeModel with an attached guardrail. "
                                 "ApplyGuardrail invokes no model, so no ladder run can "
                                 "bear on it"),
                "seal": O.family_of("F10-1"),
                "in_declared_seal_gaps": "F10-1" in O.DECLARED_SEAL_GAPS,
            },
            "F10-3": {
                "claim": ("tagging only the user-supplied portion of a RAG prompt bills "
                          "fewer text units than not tagging it (doc line 236)"),
                "why_not_here": ("that needs a tagged-vs-untagged PAIR over one RAG-shaped "
                                 "prompt, using qualifiers=['guard_content']; a length "
                                 "ladder is a different design"),
                "seal": O.family_of("F10-3"),
                "in_declared_seal_gaps": "F10-3" in O.DECLARED_SEAL_GAPS,
            },
            "F7-3": {
                "claim": ("the AWS/Bedrock/Guardrails namespace carries the 7 documented "
                          "metrics, TextUnitCount among them (doc line 677)"),
                "why_not_here": ("F7-3 asks whether the METRIC exists under that "
                                 "namespace; F10-2 asks whether the QUANTITY is what the "
                                 "documentation says. Doc lines 677 and 802 are triaged to "
                                 "both cases for exactly that reason"),
                "seal": O.family_of("F7-3"),
            },
            "why_listed": ("a billing arm that reported on all of these would be "
                           "reporting a quantifier three times wider than it measured"),
        },
        "no_power_claim": (
            f"planned_n({CASE}) is None — the seal names no n, so n_met is vacuous. "
            f"{TRIALS_PER_LENGTH} replicates per length exist to catch a transient, not to "
            f"estimate a rate: the relationship under test is an exact step function, so "
            f"one disagreeing trial refutes it and no interval is required for FALSE"),
        "instrument": {
            "operation": "ApplyGuardrail",
            "source": "INPUT",
            "output_scope": R.OUTPUT_SCOPE,
            "blocks_per_call": 1,
            "counters_read": ["usage (top level)",
                              "assessments[].invocationMetrics.usage",
                              "guardrailCoverage.textCharacters{guarded,total}"],
            "shape_verified_against": ("botocore 1.43.67: both usage sites are the same "
                                       "9-counter shape, and guardrailCoverage carries "
                                       "textCharacters{guarded,total}"),
            # From `awsclients`, not from the tally: `arms.tally` has no `sdk` key, and
            # `t.get("sdk")` would have written a silent null into the field that says
            # which SDK produced every shape claim above it.
            "sdk": A.sdk_versions(),
        },
    })

    if not faults["sound"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
