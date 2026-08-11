"""F10-2's analysis functions, tested by mutation rather than by example.

The question these tests answer is not "does `scaling()` return a dict" — it does, and so
would a stub that always reported `holds: True`. It is: **for each way the ladder could
produce a confident wrong answer, does the analysis notice?** So almost every test here
builds a row set that a specific defect would produce, and asserts the verdict flips.

The defect classes covered, and why each one matters:

* **Alternative billing models.** The ladder's nine lengths exist to make competing models
  produce *different* observed vectors. That is a design claim, and it is checked here
  rather than argued: a per-character model, an exclusive-boundary off-by-one, and a
  4000-character unit each produce a vector this suite asserts is detected. If any of them
  were indistinguishable from the ceil-per-1000 prediction, the ladder would not be an
  experiment.
* **Vacuity.** Two verdicts could hold over an empty or degenerate set — MATCHING with
  nothing comparable, SCALING over an all-zero counter vector. Both are asserted to refuse.
  Per feedback_vacuous_test_check, a guard that cannot fail is not a guard.
* **Averaging.** One replicate deviating at one length is the observation that falsifies an
  exact step function. A mean or modal reading absorbs it, so there is a test that a single
  deviating replicate out of three is caught and that the other eight lengths are untouched.
* **Instrument soundness.** Interventions, partial coverage, a service-side character total
  that disagrees with what we sent, an absent counter — each is asserted to route the case
  to INCONCLUSIVE rather than to a verdict.

Every builder here constructs rows in the shape `arms.run_arm` produces, so a change to
that shape breaks these tests loudly instead of leaving them passing against a shape the
harness no longer emits.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    """Import `01_text_units.py`, whose name is not a Python identifier."""
    path = ROOT / "f10_billing" / "01_text_units.py"
    spec = importlib.util.spec_from_file_location("f10_text_units", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


# --------------------------------------------------------------------------- helpers

def row(length: int, units: int | None, rep: int = 0, *, inv: dict | None = None,
        action: str = "NONE", guarded: int | None = None,
        total: int | None = None) -> dict:
    """One trial row in `arms.run_arm`'s shape.

    `guarded`/`total` default to `length`, i.e. full coverage of exactly what was sent,
    which is the sound case. `inv` defaults to a copy of the top-level usage, i.e. the two
    places agree — so a test that wants disagreement has to ask for it explicitly and
    cannot get it by omission.
    """
    usage = {} if units is None else {M.COUNTER: units}
    return {
        "item_id": M.item_id(length, rep),
        "length": length,
        "text": M.filler(length),
        "text_units": dict(usage),
        "invocation_usage": dict(usage) if inv is None else inv,
        "coverage": {"textCharacters": {
            "guarded": length if guarded is None else guarded,
            "total": length if total is None else total}},
        "action": action,
        "action_reason": "",
        "detected_types": [],
        "request_id": f"req-{length}-{rep}",
        "x": 0,
    }


def honest_rows() -> list[dict]:
    """The row set a correctly-behaving service would produce over the full ladder."""
    return [row(L, M.predicted_units(L), r)
            for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]


# ------------------------------------------------------------------ the predictor

def test_predicted_units_is_ceil_not_a_table():
    """The prediction is computed from CHARS_PER_UNIT, so a corrected constant shows up.

    A tabulated expectation would silently follow an edited constant and the mismatch this
    case exists to detect would never appear.
    """
    for L in M.LENGTHS:
        assert M.predicted_units(L) == math.ceil(L / M.CHARS_PER_UNIT)


def test_chars_per_unit_is_the_pricing_api_figure():
    """1000, not 1 and not 4000 — the sole authority is cost_model.yaml:47.

    Pinned because the whole ladder's boundary placement is derived from it: at 4000 the
    lengths 1000/1001/2000/2001 stop being boundaries at all and the design's
    discriminating power is gone without any test failing.
    """
    assert M.CHARS_PER_UNIT == 1000


def test_ladder_straddles_the_boundary_in_both_directions():
    """999/1000/1001 and 2000/2001 must be present, or no boundary is probed.

    A ladder of round numbers alone (500, 1000, 2000, 3000) cannot separate an inclusive
    from an exclusive boundary, which is one of the alternative models tested below.
    """
    for L in (999, 1000, 1001, 2000, 2001):
        assert L in M.LENGTHS
    assert M.TRIALS_PER_LENGTH >= 2, "one trial per length cannot show replicate agreement"


def test_predicted_vector_has_a_step_at_every_boundary():
    p = {L: M.predicted_units(L) for L in M.LENGTHS}
    assert p[999] == 1 and p[1000] == 1 and p[1001] == 2
    assert p[2000] == 2 and p[2001] == 3


# ----------------------------------------------------------------------- the filler

def test_filler_is_exactly_the_requested_length():
    for L in (1, 7, 500, 999, 1000, 1001, 1500, 2000, 2001, 3000):
        assert len(M.filler(L)) == L


def test_filler_is_exact_for_every_length_under_a_short_word_pool(monkeypatch):
    """Regression: the separator off-by-one that the 30-word pool happened to hide.

    `" ".join` of k words is `sum(len) + (k-1)`, not `sum(len) + k`. The original loop
    accumulated `len(w)+1` per word, so it could exit one character short whenever the true
    joined length landed on `length - 1` — and `filler` would then raise on its own
    assertion. The nine ladder lengths never hit that with the real pool, so the trap was
    latent and would have fired the first time a length or a word changed. Swept over a
    small pool AND over every length 1..400, because the failure is arithmetic in
    (word lengths, target) and one example proves nothing about the next.
    """
    for pool in (("a",), ("ab", "cde"), ("x", "yy", "zzz"), M.FILLER_WORDS):
        monkeypatch.setattr(M, "FILLER_WORDS", pool)
        for L in list(range(1, 401)) + list(M.LENGTHS):
            assert len(M.filler(L)) == L, f"pool={pool} length={L}"


def test_filler_is_deterministic():
    """Two builds of the same length are byte-identical, or the item id lies about content."""
    assert M.filler(1500) == M.filler(1500)


def test_filler_is_prose_not_a_repeated_character():
    """A run of one character could be normalised or compressed before counting.

    If the service collapsed runs, `"x" * 3000` would measure the normaliser rather than
    the unit boundary, and the result would look like a per-character model.
    """
    text = M.filler(3000)
    assert len(set(text)) > 5
    assert " " in text


# --------------------------------------------------------------------- item identity

def test_replicates_have_distinct_ids():
    """`arms.run_arm` skips ids the checkpoint already holds.

    Identical ids across replicates would make the resume logic manufacture the replicates
    instead of the service producing them — three "agreeing" trials from one call.
    """
    ids = [M.item_id(L, r) for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]
    assert len(set(ids)) == len(ids)


def test_item_id_changes_when_the_text_changes(monkeypatch):
    """The id includes a hash of the text, so a stale checkpoint cannot be reused.

    Editing `filler` or `CHARS_PER_UNIT` must invalidate every id; otherwise a resumed run
    would return rows measured against the old strings and report them as new evidence.
    """
    before = M.item_id(1500, 0)
    monkeypatch.setattr(M, "FILLER_WORDS", ("different", "words", "entirely"))
    assert M.item_id(1500, 0) != before


def test_ladder_is_replicate_major():
    """r0 across all lengths, then r1, then r2.

    Length-major ordering would send all three replicates of L=1 before any of L=3000, so a
    mid-run service-side change would appear as a length effect. Replicate-major makes the
    same drift appear as a drift.
    """
    items = M.ladder_items()
    first_block = items[:len(M.LENGTHS)]
    assert [it["length"] for it in first_block] == list(M.LENGTHS)
    assert len({it["rep"] for it in first_block}) == 1


def test_projected_units_exceeds_the_one_unit_per_block_default():
    """The reason `dry_run_banner` needed a text-unit override at all.

    If this ever equalled the trial count, the default projection would be right and the
    override would be dead weight — so the assertion is inequality, not a magic number.
    """
    items = M.ladder_items()
    assert M.projected_text_units(items) > len(items)


# ----------------------------------------------------------------- SCALING: honest

def test_scaling_holds_on_an_honest_ladder():
    sc = M.scaling(honest_rows())
    assert sc["holds"] is True
    assert sc["n_lengths"] == len(M.LENGTHS)
    assert sc["n_lengths_matching"] == len(M.LENGTHS)
    assert sc["mismatched_lengths"] == []


def test_scaling_refuses_an_empty_row_set():
    """No rows is not agreement. `holds` over zero cells would be true of nothing."""
    assert M.scaling([])["holds"] is False


# ------------------------------------------- SCALING: alternative billing models

def test_detects_exclusive_boundary_off_by_one():
    """A service billing `floor(L/1000)+1` only for L>1000 exclusive.

    Observed vector would be 1 at 1000 but also 1 at 1001 — this is the model the
    999/1000/1001 triple exists to separate.
    """
    rows = [row(L, (L // M.CHARS_PER_UNIT) + (1 if L % M.CHARS_PER_UNIT else 0)
                if L % M.CHARS_PER_UNIT else L // M.CHARS_PER_UNIT + 1, r)
            for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]
    sc = M.scaling(rows)
    assert sc["holds"] is False
    # The exact-multiple lengths are where the two models differ.
    assert set(sc["mismatched_lengths"]) & {1000, 2000, 3000}


def test_detects_a_per_character_model():
    """Units == characters. Every length except L=1 disagrees with the step prediction."""
    rows = [row(L, L, r) for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]
    sc = M.scaling(rows)
    assert sc["holds"] is False
    assert len(sc["mismatched_lengths"]) == len(M.LENGTHS) - 1
    assert 1 not in sc["mismatched_lengths"], "L=1 agrees under both models, by arithmetic"


def test_detects_a_4000_character_unit():
    """Every ladder length would then cost exactly 1 unit.

    This is the model that would make the whole ladder look flat, and it must not be
    mistaken for agreement just because the low lengths match.
    """
    rows = [row(L, 1, r) for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]
    sc = M.scaling(rows)
    assert sc["holds"] is False
    assert set(sc["mismatched_lengths"]) == {1001, 1500, 2000, 2001, 3000}


def test_detects_a_single_deviating_replicate():
    """Two of three replicates right at one length is still a falsification.

    A mean (2.33) or a mode (2) would absorb it. The other eight lengths must stay clean, or
    the check is flagging the ladder rather than the length.
    """
    rows = honest_rows()
    tgt = [i for i, r in enumerate(rows) if r["length"] == 1001][1]
    rows[tgt]["text_units"] = {M.COUNTER: 3}
    rows[tgt]["invocation_usage"] = {M.COUNTER: 3}
    sc = M.scaling(rows)
    assert sc["holds"] is False
    assert sc["mismatched_lengths"] == [1001]
    cell = next(c for c in sc["cells"] if c["length"] == 1001)
    assert cell["observed_distinct"] == [2, 3]
    assert cell["replicates_agree"] is False
    assert sc["n_lengths_matching"] == len(M.LENGTHS) - 1


def test_replicates_agree_is_reported_separately_from_matching():
    """Three replicates can agree with each other and all be wrong.

    Collapsing the two would let unanimous-but-wrong read as agreement.
    """
    rows = [row(L, 1, r) for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]
    sc = M.scaling(rows)
    cell = next(c for c in sc["cells"] if c["length"] == 3000)
    assert cell["replicates_agree"] is True
    assert cell["all_match_predicted"] is False


# ------------------------------------------------------------- SCALING: vacuity

def test_scaling_does_not_hold_when_every_counter_is_absent():
    """No observed values is not "all observed values matched"."""
    rows = [row(L, None, r) for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]
    sc = M.scaling(rows)
    assert sc["holds"] is False
    for c in sc["cells"]:
        assert c["all_match_predicted"] is False
        assert c["missing_counter"] == M.TRIALS_PER_LENGTH


def test_counter_of_keeps_none_and_zero_distinct():
    """`.get(counter, 0)` would report "field absent" as "service billed zero units".

    The two have opposite remedies: one is a finding about billing, the other means we are
    reading the wrong field.
    """
    assert M.counter_of(row(1, 0)) == 0
    assert M.counter_of(row(1, None)) is None


# ------------------------------------------------------------ MATCHING: behaviour

def test_matching_holds_when_both_places_agree():
    mt = M.matching(honest_rows())
    assert mt["holds"] is True
    assert mt["n_comparable"] == len(M.LENGTHS) * M.TRIALS_PER_LENGTH
    assert mt["n_disagreeing"] == 0


def test_matching_refuses_zero_comparisons():
    """The vacuity trap: no `invocationMetrics.usage` anywhere.

    `n_disagreeing == 0` is then true of an empty set and would license "matches the billed
    quantity" from zero comparisons.
    """
    rows = [row(L, M.predicted_units(L), r, inv={})
            for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]
    mt = M.matching(rows)
    assert mt["holds"] is False
    assert mt["n_comparable"] == 0
    assert mt["n_disagreeing"] == 0, "the point is that zero disagreements did not save it"
    assert mt["n_no_invocation_usage_block"] == len(rows)


def test_matching_detects_a_value_disagreement():
    rows = honest_rows()
    rows[0]["invocation_usage"] = {M.COUNTER: 99}
    mt = M.matching(rows)
    assert mt["holds"] is False
    assert mt["n_disagreeing"] == 1
    assert mt["disagreements"][0]["differing_counters"][M.COUNTER] == {
        "usage": M.predicted_units(rows[0]["length"]), "invocation_usage": 99}


def test_matching_compares_the_union_not_the_intersection():
    """A counter present in one place and absent from the other is a disagreement.

    Intersecting the key sets would skip exactly that case — the one where the two blocks
    report different sets of counters — and report agreement.
    """
    rows = honest_rows()
    rows[0]["invocation_usage"] = dict(rows[0]["text_units"], topicPolicyUnits=4)
    mt = M.matching(rows)
    assert mt["holds"] is False
    assert "topicPolicyUnits" in mt["disagreements"][0]["differing_counters"]


def test_matching_caps_the_reported_disagreement_list_and_says_so():
    """A truncated list must not read as the whole set (feedback: no silent caps)."""
    rows = honest_rows()
    for r in rows:
        r["invocation_usage"] = {M.COUNTER: 999}
    mt = M.matching(rows)
    assert mt["n_disagreeing"] == len(rows)
    assert len(mt["disagreements"]) == mt["n_disagreements_shown"] <= 20
    assert mt["n_disagreements_shown"] < mt["n_disagreeing"]


# ------------------------------------------------------- instrument soundness

def test_instrument_is_sound_on_honest_rows():
    f = M.instrument_faults(honest_rows())
    assert f["sound"] is True
    assert f["n_interventions"] == 0
    assert f["n_partial_coverage"] == 0
    assert f["n_coverage_total_mismatch"] == 0


def test_intervention_makes_the_instrument_unsound():
    """A blocked request is a different treatment from an evaluated one.

    The `billing` guardrail sets every action NONE with every filter ENABLED so this cannot
    happen; if it happens anyway, the ladder is a mixture of two treatments.
    """
    rows = honest_rows()
    rows[3]["action"] = "GUARDRAIL_INTERVENED"
    f = M.instrument_faults(rows)
    assert f["sound"] is False
    assert f["n_interventions"] == 1


def test_partial_coverage_makes_the_instrument_unsound():
    """guarded < total: the service evaluated less than we sent.

    The unit count is then right for what it evaluated while the predictor is denominated in
    what we sent, so every "match" would be a comparison between two different quantities.
    """
    rows = honest_rows()
    # Selected by predicate, not by index: `honest_rows` is length-major while
    # `ladder_items` is replicate-major, so an index means different things in the two and
    # an index-chosen row is how this test first asserted guarded == total and passed
    # nothing.
    tgt = next(r for r in rows if r["length"] == 3000)
    tgt["coverage"]["textCharacters"] = {"guarded": 500, "total": 3000}
    f = M.instrument_faults(rows)
    assert f["sound"] is False
    assert f["n_partial_coverage"] == 1
    assert f["partial_coverage"][0]["guarded"] < f["partial_coverage"][0]["total"]


def test_coverage_total_disagreeing_with_sent_chars_is_a_fault():
    """If the service counted a different number of characters, the denominator differs.

    A silently-transformed payload (encoding, trimming, a qualifier wrapper) would show up
    only here, and without this check the resulting "match" would be a coincidence.
    """
    rows = honest_rows()
    rows[7]["coverage"]["textCharacters"] = {"guarded": 1200, "total": 1200}
    f = M.instrument_faults(rows)
    assert f["sound"] is False
    assert f["n_coverage_total_mismatch"] == 1


def test_missing_counter_makes_the_instrument_unsound():
    rows = honest_rows()
    rows[2]["text_units"] = {}
    f = M.instrument_faults(rows)
    assert f["sound"] is False
    assert f["n_missing_counter"] == 1


def test_all_zero_counters_make_the_instrument_unsound():
    """The second vacuity trap.

    An all-zero vector satisfies "every replicate equals its prediction" for no length and
    would otherwise be reported as a scaling result rather than as a broken reading.
    """
    rows = [row(L, 0, r) for L in M.LENGTHS for r in range(M.TRIALS_PER_LENGTH)]
    f = M.instrument_faults(rows)
    assert f["sound"] is False
    assert f["all_counters_zero"] is True


def test_a_genuine_zero_at_one_length_is_not_the_all_zero_fault():
    """Mutation check on the all-zero guard itself: it must not fire on a partial zero.

    Otherwise a real finding — "short inputs cost nothing" — would be misreported as an
    instrument failure and routed to INCONCLUSIVE.
    """
    rows = honest_rows()
    rows[0]["text_units"] = {M.COUNTER: 0}
    f = M.instrument_faults(rows)
    assert f["all_counters_zero"] is False
    assert f["sound"] is True, "one zero among nonzeros is data, not a fault"


# ------------------------------------------------------------------ usage breadth

def test_usage_breadth_reports_every_counter_seen():
    """Makes the single-counter reading auditable rather than asserted."""
    rows = honest_rows()
    rows[0]["text_units"] = dict(rows[0]["text_units"], topicPolicyUnits=2)
    ub = M.usage_breadth(rows)
    assert "topicPolicyUnits" in ub["counters_seen"]
    assert "topicPolicyUnits" in ub["nonzero_counters"]
    assert ub["counter_used_for_scaling"] == M.COUNTER


def test_usage_breadth_distinguishes_seen_from_nonzero():
    """A counter reported as 0 is present but did not move; conflating them hides which."""
    rows = honest_rows()
    for r in rows:
        r["text_units"] = dict(r["text_units"], wordPolicyUnits=0)
    ub = M.usage_breadth(rows)
    assert "wordPolicyUnits" in ub["counters_seen"]
    assert "wordPolicyUnits" not in ub["nonzero_counters"]


# ------------------------------------------------------- the verdict is a conjunction

def test_the_two_halves_are_independent():
    """Either half failing must fail the conjunction, and each must fail alone.

    If one half could never fail on its own, the conjunction would be decorative and the
    reported FALSE would not say which property broke.
    """
    rows = honest_rows()
    rows[0]["text_units"] = {M.COUNTER: 77}          # scaling breaks
    sc, mt = M.scaling(rows), M.matching(rows)
    assert sc["holds"] is False and mt["holds"] is False

    rows2 = honest_rows()
    rows2[0]["invocation_usage"] = {M.COUNTER: 77}   # matching only
    sc2, mt2 = M.scaling(rows2), M.matching(rows2)
    assert sc2["holds"] is True and mt2["holds"] is False


def test_case_is_sealed_as_existence_with_no_thresholds():
    """The oracle kind is the seal's, not the script's.

    An EXISTENCE case takes one boolean; if a future seal gave F10-2 a threshold or an n,
    this script's conjunction would be answering a different question than the one sealed.
    """
    import oracle as O
    b = O.BINDINGS[M.CASE]
    assert b.kind == "EXISTENCE"
    assert b.thresholds == ()
    assert O.planned_n(M.CASE) is None
