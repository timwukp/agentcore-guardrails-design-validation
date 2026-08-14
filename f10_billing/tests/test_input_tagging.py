"""F10-3's pure functions, tested by mutation rather than by example.

The question each arm answers: **for each way the pair could produce a confident wrong
answer, does the analysis notice?** The defect classes:

* **A changed manipulated variable.** The whole design is that the two arms send
  byte-identical text and differ only in `qualifiers`. If a builder edit ever changed the
  text between arms, tagged them differently than claimed, or tagged the wrong block, the
  run would measure text length or nothing — so the byte-identity and the
  only-difference-is-qualifiers properties are ARMS here, asserted from the builders.
* **A rounding artifact promoted to a verdict.** Text units are quantised at
  CHARS_PER_UNIT; a 1-unit delta at a step boundary is the likeliest wrong TRUE. The
  guard's three conditions (wide predicted delta, both denominators away from a boundary)
  are each asserted to fail on a configuration that violates them alone.
* **Collapsing usage into coverage.** Usage is the claim and coverage is the mechanism;
  each direction of disagreement (units drop without coverage narrowing; coverage narrows
  without units dropping) must be flagged as a disagreement, and the per-arm
  units-vs-ceil(guarded) reconciliation must catch a breakdown that does not reconcile to
  its parent.
* **Instrument faults routed to a verdict.** Interventions, absent counters, an all-zero
  vector, an under-covered UNTAGGED arm, a coverage total that is not what we sent, a
  wrong block count, an unpaired row — each must make the instrument unsound (and
  therefore INCONCLUSIVE), and the guards must not fire on sound data of either
  hypothesis.
* **The sealed binding.** F10-3 is sealed EXISTENCE with no thresholds, no planned n, no
  family (a declared seal gap) and no mandatory mutation; the choice of `obs_existence`
  over `obs_paired` is pinned by showing the sealed branch evaluates the former and
  raises on the latter.

Rows are built in `arms.run_arm`'s shape so a change to that shape breaks these tests
loudly rather than leaving them green against a shape the harness no longer emits.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    """Import `02_input_tagging.py`, whose name is not a Python identifier."""
    path = ROOT / "f10_billing" / "02_input_tagging.py"
    spec = importlib.util.spec_from_file_location("f10_input_tagging", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()

QLEN = len(M.QUERY)
SENT = M.CONTEXT_CHARS + QLEN


# --------------------------------------------------------------------------- helpers

def prow(item: dict, units: int | None, *, guarded: int | None, total: int | None,
         action: str = "NONE", n_blocks: int = 2) -> dict:
    """One trial row in `arms.run_arm`'s shape."""
    return {
        "item_id": item["id"],
        "label": item["label"],
        "text_units": {} if units is None else {M.COUNTER: units},
        "invocation_usage": {} if units is None else {M.COUNTER: units},
        "coverage": {"textCharacters":
                     ({} if guarded is None and total is None
                      else {"guarded": guarded, "total": total})},
        "action": action,
        "action_reason": "",
        "detected_types": [],
        "n_blocks": n_blocks,
        "request_id": f"req-{item['id']}",
    }


def honest_arms(n_pairs: int = 3, *, claim_true: bool = True):
    """(items, tagged_rows, untagged_rows) as a correctly-behaving service would produce.

    `claim_true=True` is the tagging-works world: the tagged arm bills only the guarded
    query and its coverage shows guarded < total. `claim_true=False` is the sealed FALSE
    branch: identical units, full coverage on both arms. Both worlds must be
    instrument-SOUND — a fault screen that fires on either hypothesis would decide the
    case by routing one answer to INCONCLUSIVE.
    """
    items = M.pair_items(n_pairs)
    u_units = M.predicted_units_if_identical(items[0])
    t_units = M.predicted_units_if_tagging_works(items[0]) if claim_true else u_units
    t_guarded = QLEN if claim_true else SENT
    tagged = [prow(it, t_units, guarded=t_guarded, total=SENT) for it in items]
    untagged = [prow(it, u_units, guarded=SENT, total=SENT) for it in items]
    return items, tagged, untagged


def joined_of(items, tagged, untagged):
    return M.join_pairs(items, tagged, untagged)


def recon_of(items, tagged, untagged):
    return M.reconcile(joined_of(items, tagged, untagged)["pairs"])


def faults_of(items, tagged, untagged):
    return M.instrument_faults(items, tagged, untagged,
                               joined_of(items, tagged, untagged))


# ----------------------------------------------------- the manipulated variable

def test_arms_send_byte_identical_text():
    """The single non-negotiable design property: same bytes, both arms.

    If this fails, every downstream number measures text length, not tagging, and
    nothing statistical could notice.
    """
    it = M.pair_items(1)[0]
    assert M.block_texts(M.blocks_tagged(it)) == M.block_texts(M.blocks_untagged(it))


def test_only_manipulated_variable_is_qualifiers():
    """Strip the qualifiers and the two requests must be structurally identical, and the
    untagged arm must carry no qualifiers on any block."""
    it = M.pair_items(1)[0]
    t, u = M.blocks_tagged(it), M.blocks_untagged(it)
    stripped = [{"text": {"text": b["text"]["text"]}} for b in t]
    assert stripped == u
    assert all(q == () for q in M.block_qualifiers(u))
    mc = M.manipulation_check(it)
    assert mc["ok"] is True
    assert mc["texts_identical"] is True
    assert mc["untagged_has_no_qualifiers"] is True


def test_tagged_arm_qualifies_exactly_the_query_block():
    """The RAG shape: the bulk context stays untagged; ONLY the query is guard_content.

    Tagging the context (or both blocks) would test a different claim — that tagging
    everything bills like tagging nothing — and would predict no delta at all.
    """
    it = M.pair_items(1)[0]
    t = M.blocks_tagged(it)
    quals = M.block_qualifiers(t)
    qualified = [i for i, q in enumerate(quals) if q]
    assert qualified == [1], "exactly one qualified block, and it is the second"
    assert t[1]["text"]["text"] == it["query"]
    assert quals[1] == (M.GUARD_QUALIFIER,)
    assert quals[0] == (), "the context block must NOT be qualified"


def test_qualifier_value_comes_from_the_shipped_model():
    """`guard_content` is asserted against botocore's own enum, not this repo's prose.

    WEAKNESS, stated: the negative branch (a model without the qualifier) cannot be
    exercised offline because the shipped model genuinely contains it, so
    `sdk_qualifier_check`'s refusal path has no killable mutant in this suite.
    """
    chk = M.sdk_qualifier_check()
    assert chk["ok"] is True
    assert M.GUARD_QUALIFIER == "guard_content"
    assert chk["qualifier_enum"] == ["grounding_source", "query", "guard_content"]
    assert chk["guard_content_in_enum"] is True
    assert chk["counter_in_usage_shape"] is True
    for name in ("topicPolicyUnits", "contentPolicyUnits", "wordPolicyUnits",
                 "sensitiveInformationPolicyUnits", "sensitiveInformationPolicyFreeUnits",
                 "contextualGroundingPolicyUnits", "contentPolicyImageUnits",
                 "automatedReasoningPolicyUnits", "automatedReasoningPolicies"):
        assert name in chk["usage_members"]
    assert {"guarded", "total"} <= set(chk["coverage_members"])
    assert chk["sdk"]["botocore"], "the SDK version must travel with the shape claims"


def test_pair_ids_are_distinct_and_content_bound(monkeypatch):
    """Replicates share text but not ids (the checkpoint resumes by id), and the id
    hashes the text so a stale checkpoint cannot be reused after an edit."""
    ids = [it["id"] for it in M.pair_items(5)]
    assert len(set(ids)) == len(ids)
    before = M.pair_id(0)
    monkeypatch.setattr(M, "QUERY", M.QUERY + " CHANGED")
    assert M.pair_id(0) != before


# ------------------------------------------------- the shape and the arithmetic

def test_prompt_is_rag_shaped():
    """A large retrieved-context block plus a small query — the sealed oracle's own
    words. A query comparable in size to the context would make the predicted delta
    small and the design pointless."""
    it = M.pair_items(1)[0]
    assert len(it["context"]) == M.CONTEXT_CHARS
    assert len(it["context"]) >= 10 * len(it["query"])
    assert len(it["query"]) < M.CHARS_PER_UNIT


def test_predictions_are_computed_not_tabulated():
    """Checked on the shipped item AND on a fake item of different lengths: under the
    shipped constants alone, a hard-coded `return 7` would be an equivalent mutant."""
    it = M.pair_items(1)[0]
    assert M.predicted_units_if_identical(it) == math.ceil(SENT / M.CHARS_PER_UNIT)
    assert M.predicted_units_if_tagging_works(it) == math.ceil(QLEN / M.CHARS_PER_UNIT)
    assert (M.predicted_delta_units(it)
            == M.predicted_units_if_identical(it)
            - M.predicted_units_if_tagging_works(it))
    fake = {"context": "c" * 3300, "query": "q" * 450}
    assert M.predicted_units_if_identical(fake) == 4       # ceil(3750/1000)
    assert M.predicted_units_if_tagging_works(fake) == 1   # ceil(450/1000)
    assert M.predicted_delta_units(fake) == 3


def test_shipped_constants_pass_the_rounding_guard_with_a_wide_delta():
    """The delta must be several units wide, or a rounding boundary could explain it."""
    g = M.rounding_guard()
    assert g["ok"] is True
    assert M.MIN_DELTA_UNITS >= 2, ("a rounding artifact is worth 1 unit per reading; "
                                    "a guard at 1 would not guard")
    assert g["predicted_delta_units"] >= M.MIN_DELTA_UNITS
    assert g["predicted_delta_units"] == (g["units_if_identical"]
                                          - g["units_if_tagging_works"])


def test_rounding_guard_rejects_a_boundary_straddling_total():
    """A total sitting exactly on a step boundary is where one stray character flips a
    unit; the guard must refuse it even when the delta is wide."""
    g = M.rounding_guard(context_chars=6 * M.CHARS_PER_UNIT - QLEN)
    assert g["sent_chars_total"] % M.CHARS_PER_UNIT == 0
    assert g["total_margin_ok"] is False
    assert g["ok"] is False


def test_rounding_guard_rejects_a_narrow_delta():
    """A context small enough that both hypotheses predict nearly the same unit count
    cannot separate them, however clean the run."""
    g = M.rounding_guard(context_chars=600)
    assert g["delta_ok"] is False
    assert g["ok"] is False


def test_rounding_guard_rejects_a_query_near_a_boundary():
    """The guarded denominator gets the same margin as the total: a 20-char query sits
    20 chars from the zero boundary, where separator accounting could move the tagged
    reading."""
    g = M.rounding_guard(query="x" * 20)
    assert g["guarded_margin_ok"] is False
    assert g["ok"] is False


def test_distance_to_step_boundary_is_zero_on_the_boundary():
    assert M.distance_to_step_boundary(M.CHARS_PER_UNIT) == 0
    assert M.distance_to_step_boundary(M.CHARS_PER_UNIT + 3) == 3
    assert M.distance_to_step_boundary(M.CHARS_PER_UNIT - 3) == 3


# ----------------------------------------------------------- pairing and reading

def test_pairs_join_by_item_id_not_by_position():
    """A positional zip would silently mispair the moment one arm lost a trial; joining
    by id must survive a reordered partner arm."""
    items, tagged, untagged = honest_arms(3)
    j = M.join_pairs(items, tagged, list(reversed(untagged)))
    assert j["n_pairs"] == 3
    for p in j["pairs"]:
        assert p["tagged"]["item_id"] == p["untagged"]["item_id"] == p["item"]["id"]


def test_join_reports_unpaired_rows():
    items, tagged, untagged = honest_arms(3)
    j = M.join_pairs(items, tagged, untagged[:-1])
    assert j["n_pairs"] == 2
    assert j["unpaired_tagged"] == [items[-1]["id"]]
    assert j["unpaired_untagged"] == []


def test_usage_units_keeps_none_and_zero_distinct():
    """`.get(counter, 0)` would report "field absent" as "service billed zero"; the two
    have opposite remedies (reused from the sibling for exactly this property)."""
    it = M.pair_items(1)[0]
    assert M.usage_units(prow(it, 0, guarded=SENT, total=SENT)) == 0
    assert M.usage_units(prow(it, None, guarded=SENT, total=SENT)) is None


# ------------------------------------------ reconciliation: the two honest worlds

def test_reconcile_when_tagging_works():
    items, tagged, untagged = honest_arms(3, claim_true=True)
    r = recon_of(items, tagged, untagged)
    assert r["result_class"] == "fewer_on_every_pair"
    assert r["n_fewer"] == 3 and r["n_identical"] == 0 and r["n_inverted"] == 0
    assert r["n_mechanism_worked"] == 3
    assert r["n_disagreeing_pairs"] == 0
    assert r["n_breakdown_broken"] == 0
    v = M.verdict(r)
    assert v["observed"] is True
    assert v["outside_sealed_branches"] is False


def test_reconcile_when_billing_is_identical():
    """The sealed FALSE branch, verbatim: 'FALSE if identical'."""
    items, tagged, untagged = honest_arms(3, claim_true=False)
    r = recon_of(items, tagged, untagged)
    assert r["result_class"] == "identical_on_every_pair"
    v = M.verdict(r)
    assert v["observed"] is False
    assert v["sealed_false_branch_identical"] is True
    assert v["outside_sealed_branches"] is False


# ------------------------- reconciliation: usage and coverage must not be collapsed

def test_units_drop_but_coverage_unchanged_is_a_disagreement_not_a_clean_true():
    """The mechanism did not narrow, yet the bill fell. The verdict follows usage (the
    sealed oracle names the billed quantity) but the disagreement must be on the face
    of the result, once per pair."""
    items, tagged, untagged = honest_arms(3, claim_true=True)
    for row in tagged:
        row["coverage"]["textCharacters"] = {"guarded": SENT, "total": SENT}
    r = recon_of(items, tagged, untagged)
    assert r["n_fewer"] == 3
    assert r["n_mechanism_worked"] == 0
    assert r["n_disagreeing_pairs"] == 3
    assert M.verdict(r)["observed"] is True, "usage decides; the finding travels beside it"


def test_coverage_narrows_but_units_do_not_is_a_disagreement_and_false():
    items, tagged, untagged = honest_arms(3, claim_true=False)
    for row in tagged:
        row["coverage"]["textCharacters"] = {"guarded": QLEN, "total": SENT}
    r = recon_of(items, tagged, untagged)
    assert r["result_class"] == "identical_on_every_pair"
    assert r["n_mechanism_worked"] == 3
    assert r["n_disagreeing_pairs"] == 3
    assert M.verdict(r)["observed"] is False


def test_mechanism_requires_the_untagged_arm_to_be_fully_covered():
    """`tagged.guarded < total` alone is not "tagging worked": if the untagged arm was
    ALSO under-covered, the narrowing is the service's, not the qualifier's."""
    items, tagged, untagged = honest_arms(1, claim_true=True)
    untagged[0]["coverage"]["textCharacters"] = {"guarded": SENT - 50, "total": SENT}
    r = recon_of(items, tagged, untagged)
    assert r["pairs"][0]["mechanism_says_tagging_worked"] is False


def test_breakdown_must_reconcile_to_its_parent():
    """A tagged unit count that is neither ceil(guarded/quantum) nor anything else the
    coverage supports is a breakdown that does not reconcile — the defect this repo has
    been bitten by — and must be flagged even though 'fewer' still holds."""
    items, tagged, untagged = honest_arms(3, claim_true=True)
    tagged[0]["text_units"] = {M.COUNTER: M.predicted_units_if_tagging_works(items[0]) + 1}
    r = recon_of(items, tagged, untagged)
    assert r["n_fewer"] == 3, "2 < 7 is still fewer; that is why a separate check exists"
    assert r["n_breakdown_broken"] == 1
    assert r["pairs"][0]["tagged_units_match_guarded"] is False
    assert r["pairs"][1]["tagged_units_match_guarded"] is True


def test_mixed_pairs_refuse_the_true_branch():
    """One identical pair among fewer-pairs: 'bills fewer' did not hold universally, and
    the outcome is outside both sealed branches — flagged, not misfiled."""
    items, tagged, untagged = honest_arms(3, claim_true=True)
    tagged[1]["text_units"] = {M.COUNTER: M.predicted_units_if_identical(items[1])}
    tagged[1]["coverage"]["textCharacters"] = {"guarded": SENT, "total": SENT}
    r = recon_of(items, tagged, untagged)
    assert r["result_class"] == "mixed"
    v = M.verdict(r)
    assert v["observed"] is False
    assert v["sealed_false_branch_identical"] is False
    assert v["outside_sealed_branches"] is True


def test_an_inverted_pair_is_counted_and_refuses_true():
    items, tagged, untagged = honest_arms(2, claim_true=True)
    tagged[0]["text_units"] = {M.COUNTER: M.predicted_units_if_identical(items[0]) + 1}
    r = recon_of(items, tagged, untagged)
    assert r["n_inverted"] == 1
    assert r["result_class"] == "mixed"
    assert M.verdict(r)["observed"] is False


def test_no_pairs_is_not_a_result():
    r = M.reconcile([])
    assert r["result_class"] == "no_pairs"
    assert M.verdict(r)["observed"] is False


# ------------------------------------------------------- instrument soundness

def test_instrument_is_sound_in_both_honest_worlds():
    """The fault screen must not decide the case: tagged partial coverage is the
    PREDICTION of the true-world, not a fault, and full coverage is the false-world."""
    for claim_true in (True, False):
        items, tagged, untagged = honest_arms(3, claim_true=claim_true)
        f = faults_of(items, tagged, untagged)
        assert f["sound"] is True, f"claim_true={claim_true}"
        assert f["n_untagged_partial_coverage"] == 0


def test_intervention_is_a_fault():
    items, tagged, untagged = honest_arms(2)
    tagged[0]["action"] = "GUARDRAIL_INTERVENED"
    f = faults_of(items, tagged, untagged)
    assert f["sound"] is False
    assert f["n_interventions"] == 1


def test_missing_counter_is_a_fault():
    items, tagged, untagged = honest_arms(2)
    untagged[1]["text_units"] = {}
    f = faults_of(items, tagged, untagged)
    assert f["sound"] is False
    assert f["n_missing_counter"] == 1


def test_all_zero_counters_are_a_fault():
    """A delta over an all-zero vector holds by construction and says nothing."""
    items, tagged, untagged = honest_arms(2)
    for row in tagged + untagged:
        row["text_units"] = {M.COUNTER: 0}
    f = faults_of(items, tagged, untagged)
    assert f["sound"] is False
    assert f["all_counters_zero"] is True


def test_one_genuine_zero_is_not_the_all_zero_fault():
    """The guard's own mutation check: a single zero among non-zeros is data."""
    items, tagged, untagged = honest_arms(2)
    tagged[0]["text_units"] = {M.COUNTER: 0}
    f = faults_of(items, tagged, untagged)
    assert f["all_counters_zero"] is False


def test_untagged_partial_coverage_is_a_fault():
    """guarded < total on the UNTAGGED arm: the baseline did not evaluate everything,
    so a delta would partly measure the service's own shortfall."""
    items, tagged, untagged = honest_arms(2)
    untagged[0]["coverage"]["textCharacters"] = {"guarded": SENT - 200, "total": SENT}
    f = faults_of(items, tagged, untagged)
    assert f["sound"] is False
    assert f["n_untagged_partial_coverage"] == 1


def test_tagged_partial_coverage_is_not_that_fault():
    """The same reading on the TAGGED arm is the prediction under the true-hypothesis;
    a screen that faulted it would route every confirming run to INCONCLUSIVE."""
    items, tagged, untagged = honest_arms(2, claim_true=True)
    f = faults_of(items, tagged, untagged)
    assert f["n_untagged_partial_coverage"] == 0
    assert f["sound"] is True


def test_coverage_total_differing_from_sent_chars_is_a_fault():
    """The service counted a different denominator than we sent — every prediction is
    then denominated in the wrong quantity, including a small separator difference,
    deliberately."""
    items, tagged, untagged = honest_arms(2)
    untagged[0]["coverage"]["textCharacters"] = {"guarded": SENT + 7, "total": SENT + 7}
    f = faults_of(items, tagged, untagged)
    assert f["sound"] is False
    assert f["n_coverage_total_mismatch"] == 1


def test_missing_coverage_is_a_fault():
    """Without coverage the mechanism cannot be reconciled with the claim at all."""
    items, tagged, untagged = honest_arms(2)
    tagged[0]["coverage"] = {}
    f = faults_of(items, tagged, untagged)
    assert f["sound"] is False
    assert f["n_missing_coverage"] == 1


def test_wrong_block_count_is_a_fault():
    """A 1-block trial did not send the RAG pair; whatever it billed is off-design."""
    items, tagged, untagged = honest_arms(2)
    tagged[0]["n_blocks"] = 1
    f = faults_of(items, tagged, untagged)
    assert f["sound"] is False
    assert f["n_wrong_block_count"] == 1


def test_incoherent_coverage_is_a_fault():
    items, tagged, untagged = honest_arms(2)
    tagged[0]["coverage"]["textCharacters"] = {"guarded": SENT + 1, "total": SENT}
    f = faults_of(items, tagged, untagged)
    assert f["sound"] is False
    assert f["n_incoherent_coverage"] == 1


def test_unpaired_row_is_a_fault():
    items, tagged, untagged = honest_arms(2)
    f = M.instrument_faults(items, tagged, untagged[:-1],
                            M.join_pairs(items, tagged, untagged[:-1]))
    assert f["sound"] is False
    assert f["n_unpaired"] == 1


# ------------------------------------------------------------- the sealed binding

def test_case_is_sealed_existence_unassigned_no_n_no_mandatory_mutation():
    """The sealed evidence for every structural choice this script makes."""
    import oracle as O
    b = O.BINDINGS[M.CASE]
    assert b.kind == "EXISTENCE"
    assert b.thresholds == ()
    assert O.planned_n(M.CASE) is None
    assert O.family_of(M.CASE) == O.UNASSIGNED
    assert M.CASE in O.DECLARED_SEAL_GAPS
    assert O.alpha_for(M.CASE) == pytest.approx(0.05)
    assert O.mutation_is_mandatory(M.CASE) is False


def test_obs_existence_is_the_helper_the_sealed_branch_evaluates():
    """`_decide` dispatches on the sealed kind: an EXISTENCE observation evaluates, in
    both directions, with no mutation downgrade."""
    import oracle as O
    import phase1 as P
    rec_t = O.evaluate(P.obs_existence(M.CASE, True, n=5))
    rec_f = O.evaluate(P.obs_existence(M.CASE, False, n=5))
    assert rec_t["verdict"] == O.TRUE
    assert rec_f["verdict"] == O.FALSE
    assert rec_t["n_met"] is True, "planned_n is None, so n_met is vacuous"


def test_obs_paired_would_crash_the_sealed_binding():
    """Why NOT `obs_paired`, pinned: it fills improved/p_value and leaves observed_bool
    None, so the sealed EXISTENCE branch must refuse to manufacture a verdict."""
    import oracle as O
    import phase1 as P
    with pytest.raises(ValueError, match="observed_bool"):
        O.evaluate(P.obs_paired(M.CASE, improved=True, p_value=0.01, n=5))


# --------------------------------------------------------------------------- cost

def test_price_is_read_from_the_verified_cost_model():
    assert M.text_unit_price_usd() == pytest.approx(0.00015)


def test_cost_estimate_arithmetic():
    """Dollars = units x verified price, with the worst case covering both hypotheses."""
    it = M.pair_items(1)[0]
    est = M.cost_estimate(5)
    worst = 5 * 2 * M.predicted_units_if_identical(it)
    expected = 5 * (M.predicted_units_if_identical(it)
                    + M.predicted_units_if_tagging_works(it))
    assert est["worst_case_units"] == worst
    assert est["expected_units_if_claim_true"] == expected
    assert est["worst_case_usd"] == pytest.approx(worst * 0.00015)
    assert est["worst_case_usd"] >= est["expected_usd_if_claim_true"]
    assert est["worst_case_usd"] < 1.0, "orders of magnitude under the $1000/mo authority"


def test_plan_totals_two_calls_per_pair():
    assert sum(n for _, _, n in M.plan(None)) == 2 * M.N_PAIRS
    assert sum(n for _, _, n in M.plan(2)) == 4


def test_dry_run_exits_zero_offline_with_a_coherent_banner(capsys):
    """--dry-run must make no AWS call (the suite's conftest blocks sockets, so reaching
    the network would error) and must disclose the pair, the arithmetic and the dollars."""
    rc = M.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "bills fewer text units" in out, "the sealed oracle text is printed"
    assert "billable: True" in out
    assert "$" in out
    assert "guard_content" in out
    assert str(M.rounding_guard()["predicted_delta_units"]) in out
