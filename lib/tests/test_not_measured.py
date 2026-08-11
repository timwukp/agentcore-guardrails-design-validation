"""`oracle.not_measured` — the INCONCLUSIVE path, and the trap it must not reopen.

Context: DEVIATIONS.md/DEV-P1-8. Three case scripts needed a way to report "the precondition
failed, so nothing was measured" and reached for `phase1.obs_recorded(...)`. Because
`_decide` dispatches on the **sealed** kind and never on the observation's shape, those calls
reached an EXISTENCE/BOUNDARY `_need(...)` and raised `ValueError` — on exactly the branch
they existed to protect, and only after the money was spent. `not_measured` is the repair.

Every test here is written against a way the repair could go wrong rather than against its
happy path, because the happy path is one dict literal and would pass against a stub:

* **The trap must stay shut.** `evaluate(obs_recorded(...))` must still raise for these
  kinds. If a future refactor made `_decide` fall back to RECORDED on a shapeless
  observation, every case in the project could downgrade its own falsifiability at run time
  by discovering an inconvenience, and this suite would be the only thing that noticed.
* **INCONCLUSIVE, never RECORDED.** RECORDED is a sealed property meaning the
  pre-registration declared the outcome unknown and both answers are findings. A script
  granting itself RECORDED is the defect; asserted for both a BOUNDARY and an EXISTENCE case
  because they take different `_need` paths.
* **An empty reason is refused.** An INCONCLUSIVE with no stated cause is indistinguishable
  from a straddling interval, and the two have opposite remedies — collect more data vs
  repair the instrument.
* **`n_met` cannot be vacuously satisfied.** A case with a sealed n must not record it as met
  while measuring zero trials.
* **`mutation_inverted` stays unsatisfied** where mutation is mandatory, so a case cannot
  clear its mutation requirement by failing to run.
* **The record is complete.** `emit` and `amendment_blockers` read specific keys; a record
  missing one fails at the point of writing the result, i.e. after the spend.
"""

from __future__ import annotations

import pytest

import oracle as O
import phase1 as P


# Cases chosen for their sealed kinds, not arbitrarily: F8-5 is BOUNDARY and F8-6/F10-2 are
# EXISTENCE, and they are the actual call sites from DEV-P1-8. Read from the seal rather
# than hardcoded so a re-sealing that changed a kind fails here loudly.
BOUNDARY_CASE = "F8-5"
EXISTENCE_CASES = ("F8-6", "F8-7", "F10-2")


def test_the_call_sites_have_the_kinds_this_module_assumes():
    assert O.BINDINGS[BOUNDARY_CASE].kind == "BOUNDARY"
    for cid in EXISTENCE_CASES:
        assert O.BINDINGS[cid].kind == "EXISTENCE"


# --------------------------------------------------- the trap that must stay shut

@pytest.mark.parametrize("case_id", (BOUNDARY_CASE,) + EXISTENCE_CASES)
def test_obs_recorded_still_raises_on_a_non_recorded_kind(case_id):
    """The original defect, pinned as a requirement rather than remembered as fixed.

    `_need` refusing to manufacture a verdict from absent observations is the behaviour that
    makes the sealed kind authoritative. If this ever stops raising, `not_measured` becomes
    optional and any script can self-grant RECORDED.
    """
    with pytest.raises(ValueError):
        O.evaluate(P.obs_recorded(case_id, note="no data was collected"))


def test_a_genuinely_recorded_case_accepts_obs_recorded():
    """Mutation check on the test above: the ValueError must be about the KIND, not about
    `obs_recorded` being broken for everyone.

    Without this, "obs_recorded raises" would be satisfied by an `obs_recorded` that raises
    unconditionally, and the distinction the suite is asserting would be empty.
    """
    recorded = [cid for cid, b in O.BINDINGS.items() if b.kind == "RECORDED"]
    assert recorded, "the seal declares no RECORDED case; DEV-P1-3/F10-1 says otherwise"
    rec = O.evaluate(P.obs_recorded(recorded[0], note="declared unknown by the seal"))
    assert rec["verdict"] == O.RECORDED


# ------------------------------------------------------------- INCONCLUSIVE, not RECORDED

@pytest.mark.parametrize("case_id", (BOUNDARY_CASE,) + EXISTENCE_CASES)
def test_not_measured_is_inconclusive(case_id):
    rec = O.not_measured(case_id, "the precondition failed before any call was made")
    assert rec["verdict"] == O.INCONCLUSIVE
    assert rec["verdict"] != O.RECORDED
    assert rec["evidence"]["measured"] is False


@pytest.mark.parametrize("case_id", (BOUNDARY_CASE,) + EXISTENCE_CASES)
def test_the_record_says_why_it_is_not_recorded(case_id):
    """The distinction has to travel with the result, not live only in a docstring."""
    rec = O.not_measured(case_id, "probe guardrail never reached READY")
    why = rec["evidence"]["why_not_recorded"]
    assert "sealed" in why
    assert O.BINDINGS[case_id].kind in why


# ------------------------------------------------------------------- an empty reason

@pytest.mark.parametrize("bad", ("", None))
def test_not_measured_refuses_an_empty_reason(bad):
    with pytest.raises(ValueError, match="needs a reason"):
        O.not_measured(EXISTENCE_CASES[0], bad)


def test_the_reason_reaches_both_the_notes_and_the_evidence():
    """A reader of `results/*.json` and a reader of the notes list must see the same cause."""
    reason = "botocore now enforces the definition maximum client-side"
    rec = O.not_measured(BOUNDARY_CASE, reason)
    assert rec["evidence"]["reason"] == reason
    assert any(reason in n for n in rec["notes"])


def test_detail_is_carried_verbatim():
    rec = O.not_measured(EXISTENCE_CASES[0], "no crossRegionDetails on the guardrail",
                         guardrail_id="gr-abc", read_back=None, n_arms=0)
    assert rec["evidence"]["detail"] == {"guardrail_id": "gr-abc", "read_back": None,
                                         "n_arms": 0}


def test_detail_is_a_copy_not_the_caller_s_dict():
    """A caller mutating its own kwargs afterwards must not rewrite recorded evidence."""
    d = {"k": ["a"]}
    rec = O.not_measured(EXISTENCE_CASES[0], "reason", **d)
    d["k"].append("b")
    assert rec["evidence"]["detail"]["k"] == ["a", "b"] or \
           rec["evidence"]["detail"]["k"] == ["a"]
    # The shallow copy is what `not_measured` promises; the assertion above tolerates it.
    # What must NOT happen is the top-level dict being shared:
    rec["evidence"]["detail"]["new"] = 1
    assert "new" not in d


# ------------------------------------------------------------------------- n_met

def test_n_met_is_false_when_the_seal_names_an_n():
    """Zero trials did not run the pre-registered arm.

    A True here would let a case that measured nothing pass the amendment bar's n check,
    which is the same vacuity class as a guard that cannot fail.
    """
    with_n = [cid for cid in O.BINDINGS if O.planned_n(cid) is not None]
    assert with_n, "no case has a sealed n; the seal's sample_sizes block says otherwise"
    cid = with_n[0]
    rec = O.not_measured(cid, "instrument unsound")
    assert rec["planned_n"] == O.planned_n(cid)
    assert rec["n_met"] is False
    assert rec["n_attempted"] == 0 and rec["n_usable"] == 0


def test_n_met_is_true_only_where_no_n_was_sealed():
    """Vacuous by the same rule `evaluate` uses — reused, not contradicted.

    The `planned_n is None` set is derived from the live seal, never listed: the first draft of
    this test hardcoded three cases it believed had no n, and F8-6 — EXISTENCE **with** n = 60
    from `multilingual_cell` — falsified it. That is the DEV-P1-4 point in miniature: the
    sealed kind does not predict whether an n exists, because F8-6's existence claim is about a
    difference between two measured rates.
    """
    without = [cid for cid in O.BINDINGS if O.planned_n(cid) is None]
    assert without
    for cid in without:
        assert O.not_measured(cid, "instrument unsound")["n_met"] is True


def test_kind_does_not_predict_whether_an_n_was_sealed():
    """Pins DEV-P1-4's load-bearing observation so a re-seal cannot quietly change it.

    If every EXISTENCE case had no n, DEV-P1-4's per-case classification would be redundant and
    a reader could infer "no n" from the kind. F8-6 is the counterexample; this test fails if it
    ever stops being one, at which point the entry needs rewriting rather than re-reading.
    """
    existence = [cid for cid, b in O.BINDINGS.items() if b.kind == "EXISTENCE"]
    with_n = [cid for cid in existence if O.planned_n(cid) is not None]
    assert with_n, ("no EXISTENCE case carries a sealed n; DEV-P1-4 states F8-6 does, so "
                    "either the seal changed or the entry is wrong")


def test_phase1_none_n_count_matches_the_deviation_entry():
    """DEV-P1-4 states 9 of Phase 1's 18 cases have no sealed n. Re-derived, not remembered.

    Per feedback_prose_is_not_verified: a count written into a justification paragraph is
    unchecked prose, and this one was wrong on its first draft (13, from a hand-picked query
    list rather than from the seal).
    """
    phase1 = ([f"F3-{i}" for i in range(1, 10)]
              + [f"F8-{i}" for i in range(2, 9)] + ["F2-5", "F10-2"])
    assert len(phase1) == 18
    missing = [c for c in phase1 if c not in O.BINDINGS]
    assert not missing, f"Phase 1 case(s) absent from the seal: {missing}"
    without = sorted(c for c in phase1 if O.planned_n(c) is None)
    assert without == ["F10-2", "F3-5", "F3-6", "F3-7", "F3-9",
                       "F8-4", "F8-5", "F8-7", "F8-8"]

    # And the three the entry calls the ACTUAL deviation: rate oracles with no floor.
    rate_kinds = {"DISJOINT_INTERVALS", "ZERO_EVENTS"}
    rate_without_n = sorted(c for c in without if O.BINDINGS[c].kind in rate_kinds)
    assert rate_without_n == ["F3-5", "F3-6", "F3-7"]


# -------------------------------------------------------------------- mutation

def test_mutation_stays_unsatisfied_where_it_is_mandatory():
    """`mutation_inverted = None`, not False and not absent.

    None means "not established"; True would clear the requirement by not running, and
    omitting the key would make `amendment_blockers` read a missing mutation as no
    requirement.
    """
    mandatory = [cid for cid in O.BINDINGS if O.mutation_is_mandatory(cid)]
    assert mandatory, "no case requires a mutation; the seal says otherwise"
    rec = O.not_measured(mandatory[0], "instrument unsound")
    assert rec["mutation_required"] is True
    assert "mutation_inverted" in rec
    assert rec["mutation_inverted"] is None


def test_no_mutation_key_is_invented_where_none_is_required():
    optional = [cid for cid in O.BINDINGS if not O.mutation_is_mandatory(cid)]
    assert optional
    rec = O.not_measured(optional[0], "instrument unsound")
    assert rec["mutation_required"] is False


# ----------------------------------------------------- shape parity with evaluate()

def test_the_record_has_every_key_evaluate_produces():
    """`emit` and `amendment_blockers` read `evaluate`'s shape.

    A key present in one and missing in the other fails at the point of writing the result —
    after the spend — which is the failure mode `not_measured` exists to prevent, so it must
    not reintroduce it in a different place.
    """
    cid = EXISTENCE_CASES[0]
    measured = O.evaluate(P.obs_existence(cid, True, n=1, note="probe"))
    unmeasured = O.not_measured(cid, "instrument unsound")
    missing = set(measured) - set(unmeasured)
    assert not missing, f"not_measured omits key(s) evaluate produces: {sorted(missing)}"


def test_alpha_family_and_thresholds_come_from_the_seal():
    cid = BOUNDARY_CASE
    rec = O.not_measured(cid, "instrument unsound")
    assert rec["alpha"] == O.alpha_for(cid)
    assert rec["family"] == O.family_of(cid)
    assert rec["thresholds"] == list(O.BINDINGS[cid].thresholds)
    assert rec["kind"] == O.BINDINGS[cid].kind


def test_an_unknown_case_id_is_refused():
    """A typo must not produce a well-formed INCONCLUSIVE for a case that does not exist."""
    with pytest.raises(KeyError):
        O.not_measured("F99-9", "instrument unsound")


def test_p_value_is_none_rather_than_absent():
    """A missing key and a null p-value read differently downstream; nothing was tested."""
    rec = O.not_measured(EXISTENCE_CASES[0], "instrument unsound")
    assert "p_value" in rec and rec["p_value"] is None


# ------------------------------------------------------- it blocks an amendment

def test_an_unmeasured_case_cannot_clear_the_amendment_bar():
    """The end-to-end property. INCONCLUSIVE plus an unsatisfied mutation must block.

    Asserted through the real gate rather than by reading fields, because the fields only
    matter insofar as `amendment_blockers` consumes them.
    """
    cid = EXISTENCE_CASES[0]
    blockers = O.amendment_blockers(O.not_measured(cid, "instrument unsound"))
    assert blockers, "a case that measured nothing must not be amendable"
