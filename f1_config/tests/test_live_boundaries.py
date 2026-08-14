"""Offline arms over `f1_config/05_live_boundaries.py`'s pure core.

WHY THESE ARMS EXIST
--------------------
F1-6's verdict path is a fold over 8 sacrificial CreateGuardrail responses, and the two
ways it can lie are both silent: a cell table that quietly covers less than the sealed
conjunction (a verdict over a smaller quantifier than the oracle names), and a rejection
that is really a throttle or an account limitation being scored as the claim holding —
which is exactly how F8-5's STANDARD half got confounded. Every branch of that fold is
provable with no credentials and no network (the autouse `no_aws` fixture in this
directory's conftest blocks the socket), so it is proven here rather than discovered
live with probe guardrails half-created.

WHAT IS DELIBERATELY NOT TESTED HERE
------------------------------------
The transport (`run_cell`, `main`) drives `phase1.create_probe_guardrail` /
`delete_probe_guardrails` / `probe_residue`, whose contracts — including the
2026-08-13 `case_id` NameError regression and the two-list residue computation — are
covered by `lib/tests/test_probe_guardrail.py` (10 arms, mutation-checked there).
Re-testing them here would be a second copy of those arms that could drift from the
helper they pin.

MUTATION LEDGER (each arm below names its mutant; run by hand with cp/restore, never
`git checkout --`, clearing f1_config/__pycache__ and f1_config/tests/__pycache__ on
every cycle — stale bytecode has served a mutant in this repo before):
  M1 cells(): drop the topicPolicyConfig block          -> test_cell_table_is_the_full_...
  M2 cells(): flip the STANDARD-absent expectation      -> test_cell_table_is_the_full_...
  M3 config_for(): nest crossRegionConfig in the block  -> test_config_holds_everything_...
  M4 classify_rejection(): drop the throttle branch     -> test_classify_rejection_taxonomy
  M5 read_cell(): drop the `expect` key                 -> test_read_cell_keeps_expected_...
  M6 decide(): score ANY std-no rejection as holding    -> test_a_confounded_rejection_is_...
  M7 decide(): stop requiring the STANDARD-with control -> test_standard_unavailable_...
  M8 decide(): let a confound anywhere veto a clean
     counterexample                                     -> test_a_clean_counterexample_...
  M9 exit_code(): return 0 on surviving residue         -> test_exit_code_reports_ran_...
  M10 DEFERRED: drop a deferred case id                 -> test_deferred_cases_are_named_...
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# The module name starts with a digit, so it is loaded by path — the same pattern
# f1_config/tests/test_f1_3_offline_mutations.py uses for 03_permit_trap.py.
_spec = importlib.util.spec_from_file_location(
    "live_boundaries", ROOT / "f1_config" / "05_live_boundaries.py")
lb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lb)

# The two rejection texts this project has actually recorded, quoted from evidence so the
# classifier is tested against what the service says rather than what I remember it
# saying (evidence/smoke20260810T0305Z/f8/F8-5/0003_* and 0004_*).
TIER_MSG = ("Can't configure guardrail policy tier. Enable cross-Region inference for "
            "your guardrail to use Standard tier. For more information, see the Amazon "
            "Bedrock documentation.")
THROTTLE_MSG = ("Too many requests, please wait before trying again. You have sent too "
                "many requests.  Wait before trying again.")


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def _reading(block: str, tier: str, xr: bool, *, accepted: bool,
             error_code: str = "", error_message: str = "") -> dict:
    """One cell reading, built through the module's OWN read_cell so these arms test the
    real reading path and not a hand-rolled imitation of its output shape."""
    label = f"{lb.BLOCK_SLUG[block]}-{tier.lower()}-{'xr' if xr else 'noxr'}"
    p = P.ProbeGuardrail(
        label=label, name=f"grx-gr-f1-6-{label}-rtest", accepted=accepted,
        guardrail_id="gr-test" if accepted else None,
        error_code=error_code or None, error_message=error_message or None,
        http_status=200 if accepted else 400, request_id="rid-test",
        detail={"block": block, "tier": tier, "cross_region": xr,
                "expect": "rejected" if (tier == "STANDARD" and not xr) else "accepted"})
    return lb.read_cell(p)


def _clean_block(block: str) -> list[dict]:
    """The four cells of one block, in the pattern the document claims."""
    return [
        _reading(block, "CLASSIC", False, accepted=True),
        _reading(block, "CLASSIC", True, accepted=True),
        _reading(block, "STANDARD", False, accepted=False,
                 error_code="ValidationException", error_message=TIER_MSG),
        _reading(block, "STANDARD", True, accepted=True),
    ]


def _clean_all() -> list[dict]:
    return _clean_block("contentPolicyConfig") + _clean_block("topicPolicyConfig")


def _swap(readings: list[dict], block: str, tier: str, xr: bool,
          replacement: dict) -> list[dict]:
    return [replacement if (r["block"], r["tier"], r["cross_region"]) ==
            (block, tier, xr) else r for r in readings]


# ---------------------------------------------------------------------------
# the cell table
# ---------------------------------------------------------------------------

def test_cell_table_is_the_full_2x2_per_tier_carrying_block():
    """8 cells, every (block, tier, crossRegionConfig) combination exactly once, and the
    document's prediction on each. Mutants M1 (a dropped block) and M2 (a flipped
    expectation) both die here: a partial table is a verdict over a smaller quantifier
    than the sealed conjunction, and a flipped expectation would make the dry-run banner
    predict the opposite of §3.4."""
    cs = lb.cells()
    combos = {(c["block"], c["tier"], c["cross_region"]) for c in cs}
    assert len(cs) == 8 and len(combos) == 8, (
        "the design is 2 blocks x 2 tiers x {absent, present}; a duplicate or missing "
        "cell is a conjunction evaluated over the wrong table")
    assert combos == {(b, t, x) for b in ("contentPolicyConfig", "topicPolicyConfig")
                      for t in ("CLASSIC", "STANDARD") for x in (False, True)}
    for c in cs:
        want = "rejected" if (c["tier"] == "STANDARD" and not c["cross_region"]) \
            else "accepted"
        assert c["expect"] == want, (
            f"{c['label']}: §3.4 predicts {want}; only the STANDARD-without cell is "
            f"predicted rejected")
        assert c["rules_out"], "every cell must say why it is in the design"
    labels = [c["label"] for c in cs]
    assert len(set(labels)) == 8, "labels name guardrails; a collision reuses a name"
    # The guardrail name is `grx-gr-f1-6-<label>-<run_id>` and the model caps name at 50.
    run_id = "r20260810T130945Z"
    for label in labels:
        assert len(f"grx-gr-f1-6-{label}-{run_id}") <= 50, (
            f"{label}: the probe name would exceed CreateGuardrail's 50-char maximum "
            f"and fail the create for a reason unrelated to the boundary under test")


def test_config_holds_everything_constant_except_the_manipulated_variables():
    """Within a block, tierName and crossRegionConfig presence are the ONLY differences;
    the tier sits ON the block and crossRegionConfig sits at the TOP level with the
    evidence-backed profile id. Mutant M3 (crossRegionConfig nested into the block) dies
    here: nested, it would be silently dropped or rejected for shape, and the absent
    cells would no longer be the manipulation they claim to be."""
    for block in ("contentPolicyConfig", "topicPolicyConfig"):
        stripped = []
        for c in (x for x in lb.cells() if x["block"] == block):
            cfg = lb.config_for(c)
            assert set(cfg) <= {block, "crossRegionConfig"}, (
                f"{c['label']}: unexpected top-level keys {sorted(cfg)}")
            assert cfg[block]["tierConfig"] == {"tierName": c["tier"]}, (
                f"{c['label']}: tierConfig must sit ON {block} — it is not a top-level "
                f"CreateGuardrail member")
            if c["cross_region"]:
                assert cfg.get("crossRegionConfig") == \
                    {"guardrailProfileIdentifier": lb.PROFILE_ID}, (
                        f"{c['label']}: crossRegionConfig must be TOP-LEVEL and carry "
                        f"the evidence-backed profile id, its only required member")
            else:
                assert "crossRegionConfig" not in cfg, (
                    f"{c['label']}: an 'absent' cell that sends the field measures "
                    f"nothing")
            body = {k: v for k, v in cfg[block].items() if k != "tierConfig"}
            stripped.append(body)
        assert all(s == stripped[0] for s in stripped), (
            f"{block}: with tierConfig and crossRegionConfig removed the four configs "
            f"must be identical, or a rejection could be about the varying content "
            f"rather than the manipulated variables (the F8-5 length lesson)")


def test_the_profile_id_is_the_evidence_backed_one():
    """The constant and its provenance. No mutation target beyond the constant itself —
    named honestly: this arm pins the value to the accepted-create evidence path so a
    'fixed' typo in either is loud, but it cannot prove the evidence file's content
    (the no_aws suite does not read the evidence tree)."""
    assert lb.PROFILE_ID == "us.guardrail.v1:0"
    assert "0001_create_guardrail_ok.json" in lb.PROFILE_ID_PROVENANCE


# ---------------------------------------------------------------------------
# rejection classification — the confound taxonomy
# ---------------------------------------------------------------------------

def test_classify_rejection_taxonomy():
    """The two recorded messages classify as themselves, the account classes are named,
    and an unknown code falls through to `unclassified` instead of being binned by
    guess. Mutant M4 (throttle branch removed) dies on the first assertion — and if
    throttles fell through to `unclassified` they would still confound, which is why
    the assertion is on the CLASS NAME: the record must say 'throttle', because the
    remedy for a throttle (pace and retry) differs from the remedy for a mystery."""
    assert lb.classify_rejection("ThrottlingException", THROTTLE_MSG) == "throttle"
    assert lb.classify_rejection("ValidationException", TIER_MSG) == lb.TIER_XREGION
    assert lb.classify_rejection("AccessDeniedException", "no") == "access"
    assert lb.classify_rejection("ServiceQuotaExceededException", "x") == "quota"
    assert lb.classify_rejection(
        "ValidationException",
        "One or more of your guardrail topic definitions exceeds the maximum allowed "
        "length.") == "other_validation", (
        "a ValidationException about something else (here: F8-5's length boundary) must "
        "NOT classify as the tier/cross-Region rejection")
    assert lb.classify_rejection("SomeNewException", "??") == "unclassified"
    with pytest.raises(ValueError):
        lb.classify_rejection("", "")   # accepted probes have nothing to classify
    for cls in ("throttle", "access", "quota", "unclassified"):
        assert cls in lb.CONFOUND_CLASSES
    assert lb.TIER_XREGION not in lb.CONFOUND_CLASSES, (
        "the one class that may be scored as the claim holding must not be in the "
        "confound set")


def test_read_cell_keeps_expected_beside_observed():
    """F8-5's read_probe discipline: the prediction travels with the observation, and a
    rejection carries its classification. Mutant M5 (the `expect` key dropped) dies
    here; without it a FALSE verdict cannot say which cell broke."""
    ok = _reading("contentPolicyConfig", "CLASSIC", False, accepted=True)
    assert ok["expect"] == "accepted" and ok["observed"] == "accepted"
    assert ok["matches_expected"] is True and ok["classification"] is None

    rej = _reading("topicPolicyConfig", "STANDARD", False, accepted=False,
                   error_code="ValidationException", error_message=TIER_MSG)
    assert rej["expect"] == "rejected" and rej["observed"] == "rejected"
    assert rej["matches_expected"] is True
    assert rej["classification"] == lb.TIER_XREGION
    assert rej["request_id"], "a rejection is quotable only with its request id"


# ---------------------------------------------------------------------------
# decide() — the fold, and the confound rules
# ---------------------------------------------------------------------------

def test_decide_true_needs_the_clean_pattern_on_both_blocks():
    d = lb.decide(_clean_all())
    assert d["measured"] is True and d["observed"] is True
    assert d["confounds"] == [] and d["counterexamples"] == []
    assert all(v["result"] == "holds" for v in d["per_block"].values())


def test_standard_succeeding_anyway_is_false_even_if_the_other_block_holds():
    """The oracle's own FALSE branch: 'if either succeeds anyway'. One clean acceptance
    of (STANDARD, absent) decides the universally quantified conjunction."""
    readings = _swap(_clean_all(), "topicPolicyConfig", "STANDARD", False,
                     _reading("topicPolicyConfig", "STANDARD", False, accepted=True))
    d = lb.decide(readings)
    assert d["measured"] is True and d["observed"] is False
    assert d["per_block"]["topicPolicyConfig"]["result"] == "fails"
    assert d["per_block"]["contentPolicyConfig"]["result"] == "holds"


def test_classic_rejected_without_the_field_is_also_false():
    """The conjunction's other conjunct, attributable because CLASSIC-with was accepted."""
    readings = _swap(_clean_all(), "contentPolicyConfig", "CLASSIC", False,
                     _reading("contentPolicyConfig", "CLASSIC", False, accepted=False,
                              error_code="ValidationException",
                              error_message="CLASSIC requires crossRegionConfig (?)"))
    d = lb.decide(readings)
    assert d["measured"] is True and d["observed"] is False
    assert d["per_block"]["contentPolicyConfig"]["result"] == "fails"


def test_a_confounded_rejection_is_not_scored_as_the_claim_holding():
    """THE invariant: an account-limitation or throttle rejection in the decisive cell
    must not become TRUE. Mutant M6 (any std-no rejection scored as holding) dies on
    all three variants. F8-5's STANDARD half is variant one, verbatim."""
    # throttle in the decisive cell
    readings = _swap(_clean_all(), "contentPolicyConfig", "STANDARD", False,
                     _reading("contentPolicyConfig", "STANDARD", False, accepted=False,
                              error_code="ThrottlingException",
                              error_message=THROTTLE_MSG))
    d = lb.decide(readings)
    assert d["measured"] is False and d["observed"] is None, (
        "a throttled rejection scored as the boundary holding is the F8-5 confound "
        "republished")
    assert any("throttle" in c for c in d["confounds"])

    # access denial in the decisive cell
    readings = _swap(_clean_all(), "contentPolicyConfig", "STANDARD", False,
                     _reading("contentPolicyConfig", "STANDARD", False, accepted=False,
                              error_code="AccessDeniedException",
                              error_message="not authorized"))
    d = lb.decide(readings)
    assert d["measured"] is False

    # a ValidationException about something ELSE — a rejection nobody has read
    readings = _swap(_clean_all(), "contentPolicyConfig", "STANDARD", False,
                     _reading("contentPolicyConfig", "STANDARD", False, accepted=False,
                              error_code="ValidationException",
                              error_message="Your topic definition exceeds the maximum "
                                            "allowed length."))
    d = lb.decide(readings)
    assert d["measured"] is False, (
        "a validation message that does not name the tier/cross-Region relationship "
        "must not be scored as the claim holding")


def test_standard_unavailable_account_wide_is_not_the_claim():
    """If STANDARD WITH crossRegionConfig is also rejected, the STANDARD-without
    rejection cannot be attributed to the missing field — the same rejection the oracle
    reads as TRUE would be produced by an account where STANDARD is simply unavailable.
    Mutant M7 (the with-control no longer required) dies here."""
    readings = _swap(_clean_all(), "topicPolicyConfig", "STANDARD", True,
                     _reading("topicPolicyConfig", "STANDARD", True, accepted=False,
                              error_code="ValidationException",
                              error_message="STANDARD tier is not available"))
    d = lb.decide(readings)
    assert d["measured"] is False and d["observed"] is None
    assert d["per_block"]["topicPolicyConfig"]["result"] == "confounded"
    assert any("unavailable in this account" in c or "cannot be attributed" in c
               for c in d["confounds"])


def test_a_clean_counterexample_beats_a_confound_on_the_other_block():
    """FALSE is still decidable through a confound elsewhere: one clean 'succeeds anyway'
    refutes the universal conjunction whatever happened on the other block — while the
    confound stays on the record. Mutant M8 (confound anywhere vetoes the verdict) dies
    here."""
    readings = _clean_all()
    readings = _swap(readings, "contentPolicyConfig", "STANDARD", False,
                     _reading("contentPolicyConfig", "STANDARD", False, accepted=True))
    readings = _swap(readings, "topicPolicyConfig", "STANDARD", False,
                     _reading("topicPolicyConfig", "STANDARD", False, accepted=False,
                              error_code="ThrottlingException",
                              error_message=THROTTLE_MSG))
    d = lb.decide(readings)
    assert d["measured"] is True and d["observed"] is False, (
        "a counterexample decides a universally quantified conjunction; only TRUE is "
        "unavailable through a confound")
    assert d["confounds"], "the confound must still be reported, not consumed"


def test_a_missing_cell_is_a_confound_not_a_default():
    """decide() over 7 readings must refuse, not fill the gap: a conjunction evaluated
    over a partial table is a verdict over a smaller quantifier than the sealed text."""
    readings = [r for r in _clean_all()
                if (r["block"], r["tier"], r["cross_region"]) !=
                ("topicPolicyConfig", "CLASSIC", True)]
    d = lb.decide(readings)
    assert d["measured"] is False
    assert d["per_block"]["topicPolicyConfig"]["result"] == "confounded"
    assert any("never read" in c for c in d["confounds"])


# ---------------------------------------------------------------------------
# exit codes and residue
# ---------------------------------------------------------------------------

def test_exit_code_reports_ran_not_right():
    """rc is about the RUN. A FALSE verdict with clean teardown is a successful test
    (rc=0); surviving residue is rc=2 whatever the verdict said; a confounded case
    measured nothing (rc=2); the unreachable leftover is rc=1, loudly. Mutant M9
    (residue ignored) dies on the second line."""
    ok = dict(n_read=8, n_cells=8, measured=True, residue_clean=True)
    assert lb.exit_code(**{**ok, "verdict": O.FALSE}) == 0, (
        "a verdict that refutes the document is a test that RAN; rc must not read as "
        "CI-red for 'the document was wrong'")
    assert lb.exit_code(**{**ok, "verdict": O.TRUE}) == 0
    assert lb.exit_code(n_read=8, n_cells=8, measured=True, residue_clean=False,
                        verdict=O.TRUE) == 2, (
        "a surviving probe guardrail is a teardown failure this run owns, whatever the "
        "verdict said")
    assert lb.exit_code(n_read=7, n_cells=8, measured=True, residue_clean=True,
                        verdict=O.TRUE) == 2
    assert lb.exit_code(n_read=8, n_cells=8, measured=False, residue_clean=True,
                        verdict=O.INCONCLUSIVE) == 2
    assert lb.exit_code(**{**ok, "verdict": O.INCONCLUSIVE}) == 1


def test_residue_from_a_died_run_would_be_caught():
    """The scenario the two-list residue exists for, driven through the module's exit
    mapping: a probe created a guardrail, the process died before its delete was
    attempted, and rc must be 2 even though every ATTEMPTED delete succeeded.
    (probe_residue's own arithmetic is pinned in lib/tests/test_probe_guardrail.py;
    this arm pins that THIS script's rc honors it.)"""
    probes = [P.ProbeGuardrail(label="cf-classic-noxr", name="n1", accepted=True,
                               guardrail_id="gr-1"),
              P.ProbeGuardrail(label="cf-classic-xr", name="n2", accepted=True,
                               guardrail_id="gr-2")]
    deletions = [{"label": "cf-classic-noxr", "name": "n1", "guardrail_id": "gr-1",
                  "deleted": True, "error_code": None, "request_id": "r"}]
    res = P.probe_residue(probes, deletions)
    assert res["clean"] is False and res["surviving"] == ["gr-2"]
    assert lb.exit_code(n_read=8, n_cells=8, measured=True,
                        residue_clean=res["clean"], verdict=O.FALSE) == 2


# ---------------------------------------------------------------------------
# scope pins
# ---------------------------------------------------------------------------

def test_deferred_cases_are_named_and_not_emitted():
    """The file's scope promise as data: F1-6 only; the five successors are deferred,
    not decided. Mutant M10 (a deferred id dropped) dies here — and dropping one would
    also break the docstring's promise that the deferral is visible as data rather
    than prose."""
    assert lb.CASE == "F1-6"
    assert tuple(lb.DEFERRED) == ("F1-10", "F1-11", "F1-12", "F1-13", "F1-20")
    assert lb.CASE not in lb.DEFERRED
    # Each deferred case really is one 02_model_surface.py defers to this file: pinned
    # against the sealed bindings' knowledge of them existing at all.
    for cid in lb.DEFERRED:
        assert cid in O.BINDINGS, f"{cid} is not a sealed case"


def test_the_seal_names_no_n_and_no_mandatory_mutation_for_f1_6():
    """The two facts the script's n=8 justification and mutation branch rest on, pinned
    so a re-seal that changes either fails HERE at desk instead of silently changing
    what the live run asserts. No mutation target in 05_live_boundaries.py — this arm
    guards the script's premises, not its code — and it is named as such."""
    assert O.planned_n("F1-6") is None, (
        "the binding names no sample-size cell; if a re-seal gives F1-6 an n, the "
        "script's 'nothing to fall short of' justification is stale")
    assert O.mutation_is_mandatory("F1-6") is False, (
        "if the seal ever adds F1-6 to mutation_arms_are_mandatory, the script's "
        "guarded branch starts executing and must be re-reviewed")
    assert O.BINDINGS["F1-6"].kind == "EXISTENCE"
