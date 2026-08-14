"""Offline arms over `04_policy_grammar.py`'s pure functions.

Same discipline as `test_f1_3_offline_mutations.py` and for the same reason: a guard
proven only by reasoning is not a guard (`feedback_vacuous_test_check`), and the guards
here are the difference between a grammar verdict and a DC-1 validation finding published
as one. Everything below runs with no credentials and provably no network (the autouse
`no_aws` fixture in this directory's conftest blocks socket.connect).

WHAT IS AND IS NOT COVERED
--------------------------
Covered: statement assembly and the helper-bypass partition, the rejection-vs-DC-1
classification, the two-list residue computation, the generated-body defaults reading,
the three paired-verdict deciders, and the exit-code mapping. NOT covered: the live
`main()` flow (create/poll/delete ordering, the per-case finally, the ledger writes) —
unlike F1-3 this module has no FakeAC end-to-end harness, and that gap is stated in the
run report rather than papered over. The pure deciders are where a wrong TRUE would be
manufactured, which is why they get the mutation checks.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import cedar as C

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "policy_grammar", ROOT / "f1_config" / "04_policy_grammar.py")
pg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pg)

# The scope every builder now takes. A fixed test ARN using the documentation account id, so the
# statements under test are byte-identical in shape to the live ones while naming nothing real.
# It is built through `scope_for` rather than assembled here: if the coupling rules ever change,
# these arms should move with the production helper and not silently diverge from it.
SCOPE = pg.scope_for("arn:aws:bedrock-agentcore:us-east-1:111122223333:"
                     "gateway/grx-gw-offline-test")


# ---------------------------------------------------------------------------
# statement assembly and the bypass partition
# ---------------------------------------------------------------------------

def test_mixed_statement_is_the_string_the_helper_refuses():
    """The bypass is necessary: cedar.statement raises on exactly this combination,
    and the hand-assembled string carries both condition forms built from the SAME
    two condition strings the split arms send.

    `resource=` is passed even though this call is expected to raise, and that is not
    incidental. `pytest.raises(ValueError)` would be satisfied by ANY ValueError, so a call
    that failed for a second reason would keep this test green while no longer testing the
    mixing rule at all. Since `resource` became required, omitting it raises TypeError before
    the mixing check runs — which is how this test failed, and it failed usefully: the
    assertion was never about the argument list, so the argument list has to be valid for the
    assertion to mean what it says.
    """
    with pytest.raises(ValueError):
        C.statement("forbid", resource=SCOPE.resource, action=SCOPE.action,
                    when=pg.STD_CONDITION, when_guardrails=pg.guardrails_condition())
    text = pg.mixed_statement(SCOPE)
    assert "when {" in text.replace("when guardrails", "")
    assert "when guardrails {" in text
    assert pg.STD_CONDITION in text
    assert pg.guardrails_condition() in text
    # and the local lint flags it, confirming check_statement would have refused it
    assert any("mixes" in p for p in C.check_statement(text))


def test_the_data_path_and_the_standard_condition_are_the_forced_ones():
    """A registered deviation, pinned so a future edit cannot quietly undo it — or quietly
    re-apply it without noticing that these three cases then measure something else.

    Both values changed on 2026-08-14 because the service refuses their predecessors
    categorically, not because they were inconvenient:

      * `context.output.*` in any policy with an authorization effect: "references
        'context.output' but the policy has an authorization effect. Use 'context.input.*' data
        paths". Recorded by F4-0 on 2026-08-11, re-proven by diag cells 7 and 8.
      * `context.input.amount` on the echo action: CREATE_FAILED, the attribute is not in that
        action's context schema (diag cell 15). Cell 17 proved the input.text equality ACTIVE.

    If either constant moves back, these arms go red and whoever moved it has to say what the
    cases now measure. That is the function of pinning a deviation rather than commenting on it.
    """
    assert pg.GUARDRAIL_PATH == "context.input.text"
    assert pg.STD_CONDITION == 'context.input.text == "grx-value-that-is-never-equal"'
    assert "context.output" not in pg.guardrails_condition()
    # the scope is the one authorable shape: specific gateway ARN + constrained echo action
    assert SCOPE.resource.startswith("resource == AgentCore::Gateway::")
    assert SCOPE.action == C.action_eq(pg.ECHO_TARGET, pg.ECHO_TOOL)


def test_the_generation_name_is_not_derived_from_the_run_id_alone():
    """A deterministic name for an UNDELETABLE resource makes an arm single-shot.

    Checked on the source because `names` is assembled inside `main()` against a live client, and
    the property is about how the string is BUILT. Round 5 created
    `grx_f119_gen_r20260810T130945Z` and read it successfully; round 6 got
    `ConflictException: Generation with the same name already exists` and reported arm B as
    NOT_STARTED. Every policy name in that dict may stay deterministic — policies are deleted in
    the per-case finally — but this one may not, and the distinction is invisible unless someone
    states it, which is what this arm does.
    """
    src = (ROOT / "f1_config" / "04_policy_grammar.py").read_text(encoding="utf-8")
    i = src.index('"f119_gen":')
    entry = src[i:i + 400]
    assert "time.gmtime()" in entry, (
        "the StartPolicyGeneration name looks deterministic again; a generation cannot be "
        "deleted, so the second attempt under a fixed name is a ConflictException forever")
    assert 'grx_f119_gen_{run_id}_' in entry, (
        "the run-id prefix is how undeletable generation residue stays attributable to this "
        "run and case — keep it even though the name must also be unique")


def test_asset_findings_are_read_with_the_fragment_they_belong_to():
    """The service's refusal is the observation; the empty statement list is only its shadow.

    Shaped from the real 2026-08-14 response, which returned two assets, each with no definition
    and one `INVALID` finding reading "Non-translatable: cannot be expressed in Dogwood". A reader
    that returned the descriptions WITHOUT their fragments would be useless for the thing this is
    for — saying WHICH intent the service declined — so the pairing is asserted, not just the count.
    """
    assets = [
        {"policyGenerationAssetId": "a1",
         "rawTextFragment": "Block any tool call whose input attempts a prompt attack.",
         "findings": [{"type": "INVALID",
                       "description": "Non-translatable: cannot be expressed in Dogwood"}]},
        {"policyGenerationAssetId": "a2",
         "rawTextFragment": "Block any tool call whose output contains hate speech.",
         "findings": [{"type": "INVALID",
                       "description": "Non-translatable: cannot be expressed in Dogwood"}]},
    ]
    # no `definition` on either asset, so there is nothing to read as a statement
    assert pg.generation_statements(assets) == []
    found = pg.generation_asset_findings(assets)
    assert len(found) == 2
    assert {f["type"] for f in found} == {"INVALID"}
    assert all("Non-translatable" in f["description"] for f in found)
    assert {f["fragment"] for f in found} == {
        "Block any tool call whose input attempts a prompt attack.",
        "Block any tool call whose output contains hate speech."}
    # and the absence of any generated body is still not measurable — the refusal explains the
    # absence, it does not turn it into a comparison
    d = pg.authoring_defaults_check(pg.generation_statements(assets))
    assert d["measurable"] is False and d["matched"] is None


def test_asset_findings_tolerate_the_shapes_a_success_would_have():
    """An asset that DID translate carries a definition and, plausibly, no findings at all. The
    reader must not require the failure shape it was written from."""
    ok = [{"policyGenerationAssetId": "a3", "rawTextFragment": "…",
           "definition": {"policy": {"statement": 'permit (principal, action, resource);'}}}]
    assert pg.generation_asset_findings(ok) == []
    assert pg.generation_statements(ok) == ['permit (principal, action, resource);']
    assert pg.generation_asset_findings([]) == []
    assert pg.generation_asset_findings(None) == []


def test_the_dry_run_prints_the_same_scope_shape_the_live_path_sends():
    """The dry run is the pre-flight check for these three cases, so its statement text has to be
    the text the service will see — otherwise the banner reassures a reader about a head that
    differs from the one about to be sent.

    It failed in exactly that way once. `DRY_RUN_SCOPE` was hand-assembled with the bare action
    reference while `scope_for` used the `action ==` clause, so the dry run printed
    `forbid (principal, AgentCore::Action::"grxecho___echo", …)` — which the parser refuses at
    column 30 — three lines above the words "predict: control ACCEPTED". Both values now come
    from `scope_for`, and this arm is what keeps them from diverging again.
    """
    assert pg.DRY_RUN_SCOPE.action == SCOPE.action
    assert pg.DRY_RUN_SCOPE.resource.startswith("resource == AgentCore::Gateway::")
    # the placeholder must stay a placeholder: documentation account id, named as unreal
    assert "111122223333" in pg.DRY_RUN_SCOPE.resource
    assert "DRY-RUN-PLACEHOLDER-NOT-A-REAL-GATEWAY" in pg.DRY_RUN_SCOPE.resource
    # and the head it prints lints clean, by the same lint the live scope passes
    assert C.check_statement(f"{pg.DRY_RUN_SCOPE.head()};") == []


def test_no_threshold_statement_omits_exactly_the_threshold():
    """Arm A differs from its control in ONLY the property under test (the F4-probe
    lesson: sacrificial in the property, not merely disposable)."""
    a = pg.no_threshold_statement(SCOPE)
    ctrl = pg.threshold_control_statement(SCOPE)
    assert "decimal(" not in a
    assert 'decimal("0.2")' in ctrl
    # same function, category and path in both
    for token in ("BedrockGuardrails::ContentFilter", '"HATE"', pg.GUARDRAIL_PATH):
        assert token in a and token in ctrl
    assert any("threshold" in p for p in C.check_statement(a))
    assert C.check_statement(ctrl) == []


def test_split_statements_reuse_the_mixed_statements_conditions():
    assert pg.STD_CONDITION in pg.split_when_statement(SCOPE)
    assert pg.guardrails_condition() in pg.split_guardrails_statement(SCOPE)
    assert C.check_statement(pg.split_when_statement(SCOPE)) == []
    assert C.check_statement(pg.split_guardrails_statement(SCOPE)) == []


def test_pattern_statements_carry_their_constructs_and_the_helper_refuses_them():
    forms = pg.pattern_statements(SCOPE)
    assert set(forms) == {"like_on_path", "regex_shaped_category"}
    assert ' like "*jailbreak*"' in forms["like_on_path"]["statement"]
    assert '"HATE.*"' in forms["regex_shaped_category"]["statement"]
    # the helper refuses the regex-shaped category, so hand assembly was necessary
    with pytest.raises(ValueError):
        C.guardrail_condition("ContentFilter", ["HATE.*"], [pg.GUARDRAIL_PATH],
                              threshold="0.2")
    # every form states why it was chosen and what its rejection can and cannot mean
    for spec in forms.values():
        assert spec["why"] and spec["rejection_reading"]


def test_bypass_partition_accepts_the_planned_shape():
    planned = [
        {"label": "ok-ctrl", "statement": pg.threshold_control_statement(SCOPE),
         "predict": "accepted", "built_by": "helpers"},
        {"label": "ok-mixed", "statement": pg.mixed_statement(SCOPE),
         "predict": "rejected", "built_by": "hand"},
    ]
    assert pg.bypass_partition_problems(planned) == []


@pytest.mark.parametrize("arm,fragment", [
    # a hand-built arm predicted accepted: the bypass leaked into a well-formed arm
    ({"label": "leak", "statement": "forbid (principal, action, resource);",
      "predict": "accepted", "built_by": "hand"}, "hand-assembly bypass"),
    # a control that fails the local lint: the harness malformed a control
    ({"label": "badctrl",
      "statement": "forbid (principal, action, resource)\nwhen guardrails { x }",
      "predict": "accepted", "built_by": "helpers"}, "check_statement flags"),
    # a rejected-predicted arm claiming helper provenance: the guard was weakened
    ({"label": "weak", "statement": "forbid (principal, action, resource);",
      "predict": "rejected", "built_by": "helpers"}, "refuse to produce"),
], ids=["hand-built-control", "lint-dirty-control", "helper-built-malformed"])
def test_bypass_partition_refuses_each_leak(arm, fragment):
    problems = pg.bypass_partition_problems([arm])
    assert problems, f"partition accepted a leaking arm: {arm['label']}"
    assert any(fragment in p for p in problems)


# ---------------------------------------------------------------------------
# classification: a rejection is never read off the rc, and DC-1 is never a rejection
# ---------------------------------------------------------------------------

# The live DC-1 finding text, verbatim from the F1-3 offline harness, so the classifier
# is tested against the sentence the service actually returns and not a paraphrase.
DC1_REASON = ("Overly Permissive: Policy Engine will allow every request for the "
              "specified principal (AgentCore::IamEntity), action (Any Future Tools) "
              "and resource (gateway/*) combination if the policy is added or updated")


@pytest.mark.parametrize("kw,want", [
    (dict(http_ok=True, terminal_status="ACTIVE"), pg.ACCEPTED),
    # the single most likely wrong TRUE: a DC-1 finding scored as a grammar rejection
    (dict(http_ok=True, terminal_status="CREATE_FAILED", status_reasons=[DC1_REASON]),
     pg.VALIDATION_FINDING),
    (dict(http_ok=True, terminal_status="CREATE_FAILED",
          status_reasons=["Syntax error at line 2: unexpected token"]),
     pg.REJECTED_GRAMMAR),
    (dict(http_ok=True, terminal_status="CREATE_FAILED",
          status_reasons=["Invalid guardrail condition: pattern operators are not "
                          "supported"]), pg.REJECTED_GRAMMAR),
    # the DC-1 vocabulary also contains grammar-ish words ("unconstrained"); the finding
    # bucket must win because it is checked first
    (dict(http_ok=True, terminal_status="CREATE_FAILED",
          status_reasons=["Overly Permissive: unconstrained scope cannot be parsed"]),
     pg.VALIDATION_FINDING),
    (dict(http_ok=False, error_code="ValidationException",
          error_message="Failed to parse policy statement"), pg.REJECTED_GRAMMAR),
    (dict(http_ok=False, error_code="ThrottlingException",
          error_message="Rate exceeded"), pg.INFRASTRUCTURE),
    (dict(http_ok=False, error_code="ConflictException",
          error_message="Policy with this name already exists"), pg.INFRASTRUCTURE),
    (dict(http_ok=True, timed_out=True), pg.NOT_SETTLED),
    # a failure this script cannot read must never be counted for either side
    (dict(http_ok=True, terminal_status="CREATE_FAILED",
          status_reasons=["something entirely novel happened"]), pg.UNCLASSIFIED),
    (dict(http_ok=False, error_code="SomethingNewException",
          error_message="totally novel"), pg.UNCLASSIFIED),
], ids=["active", "dc1-finding", "syntax", "pattern-reject", "finding-beats-grammar",
        "sync-parse", "throttle", "name-conflict", "timeout", "unread-async",
        "unread-sync"])
def test_classify_create_outcome(kw, want):
    got = pg.classify_create_outcome(**kw)
    assert got["outcome"] == want, got


# ---------------------------------------------------------------------------
# residue: derived from BOTH lists, per policy id, never from deletions alone
# ---------------------------------------------------------------------------

def test_residue_sees_a_never_attempted_delete():
    """The load-bearing case: a policy created but whose delete was never ATTEMPTED
    contributes no deletion row, so a deletions-only computation reports zero survivors
    for exactly the run that has one."""
    created = [{"policy_id": "pol-a"}, {"policy_id": "pol-b"}]
    deletions = [{"policy_id": "pol-a", "deleted": True}]   # pol-b: no row at all
    r = pg.policy_residue(created, deletions)
    assert r["surviving"] == ["pol-b"]
    assert r["never_attempted"] == ["pol-b"]
    assert not r["clean"]
    assert {p["policy_id"]: p["deleted"] for p in r["per_policy"]} == \
        {"pol-a": True, "pol-b": False}


def test_residue_sees_a_failed_delete_and_a_clean_run():
    created = [{"policy_id": "pol-a"}, {"policy_id": "pol-b"},
               {"policy_id": None}]           # a synchronous rejection created nothing
    failed = [{"policy_id": "pol-a", "deleted": True},
              {"policy_id": "pol-b", "deleted": False}]
    r = pg.policy_residue(created, failed)
    assert r["surviving"] == ["pol-b"] and r["never_attempted"] == [] and not r["clean"]
    clean = pg.policy_residue(created, [{"policy_id": "pol-a", "deleted": True},
                                        {"policy_id": "pol-b", "deleted": True}])
    assert clean["clean"] and clean["n_created"] == 2


# ---------------------------------------------------------------------------
# generated-body reading
# ---------------------------------------------------------------------------

GEN_DEFAULTED = ('forbid (principal, action, resource)\nwhen guardrails {\n'
                 '    BedrockGuardrails::ContentFilter(["HATE"], [context.output.text])'
                 '["HATE"].confidenceScore.greaterThan(decimal("0.2")) && '
                 'BedrockGuardrails::PromptAttack(["JAILBREAK"], [context.input.text])'
                 '["JAILBREAK"].confidenceScore.greaterThan(decimal("0.4"))\n};')


def test_extract_thresholds_pairs_each_call_with_its_own_decimal():
    got = pg.extract_guardrail_thresholds(GEN_DEFAULTED)
    assert got == {"ContentFilter": ["0.2"], "PromptAttack": ["0.4"]}


def test_defaults_check_matches_the_documented_defaults():
    r = pg.authoring_defaults_check([GEN_DEFAULTED])
    assert r["measurable"] and r["matched"]
    # compared against lib/cedar.py's table, not a literal here
    assert r["expected_defaults"] == C.AUTHORING_DEFAULTS


def test_defaults_check_rejects_a_wrong_number_and_a_missing_one():
    wrong = GEN_DEFAULTED.replace('decimal("0.2")', 'decimal("0.6")')
    r = pg.authoring_defaults_check([wrong])
    assert r["measurable"] and r["matched"] is False
    # a generated call with NO threshold: the service did not fill a default
    bare = ('forbid (principal, action, resource)\nwhen guardrails {\n'
            '    BedrockGuardrails::ContentFilter(["HATE"], [context.output.text])\n};')
    r2 = pg.authoring_defaults_check([bare])
    assert r2["measurable"] and r2["matched"] is False


def test_defaults_check_refuses_to_decide_what_it_cannot_read():
    assert pg.authoring_defaults_check([])["measurable"] is False
    assert pg.authoring_defaults_check(
        ["permit (principal, action, resource);"])["measurable"] is False
    unknown = GEN_DEFAULTED.replace("ContentFilter", "FutureFunction")
    assert pg.authoring_defaults_check([unknown])["measurable"] is False


def test_generation_statements_reads_both_union_arms():
    assets = [{"definition": {"cedar": {"statement": "s1"}}},
              {"definition": {"policy": {"statement": "s2"}}},
              {"definition": {}}, {}]
    assert pg.generation_statements(assets) == ["s1", "s2"]


# ---------------------------------------------------------------------------
# the paired-verdict deciders
# ---------------------------------------------------------------------------

D_OK = {"measurable": True, "matched": True, "why": "defaults present"}
D_BAD = {"measurable": True, "matched": False, "why": "0.6 != 0.2"}
D_UNREAD = {"measurable": False, "matched": None, "why": "no guardrail call generated"}


@pytest.mark.parametrize("a,ctrl,term,defaults,measurable,observed", [
    # the TRUE conjunction
    (pg.REJECTED_GRAMMAR, pg.ACCEPTED, True, D_OK, True, True),
    # control rejected -> 'rejected' is uninformative
    (pg.REJECTED_GRAMMAR, pg.REJECTED_GRAMMAR, True, D_OK, False, None),
    # hand-written accepted -> FALSE regardless of the NL half
    (pg.ACCEPTED, pg.ACCEPTED, False, D_UNREAD, True, False),
    # missing half is not a refutation
    (pg.REJECTED_GRAMMAR, pg.ACCEPTED, False, D_UNREAD, False, None),
    (pg.REJECTED_GRAMMAR, pg.ACCEPTED, True, D_UNREAD, False, None),
    # generated numbers disagree with the documented defaults -> FALSE
    (pg.REJECTED_GRAMMAR, pg.ACCEPTED, True, D_BAD, True, False),
    # a DC-1 finding on the hand-written arm is not the sealed event
    (pg.VALIDATION_FINDING, pg.ACCEPTED, True, D_OK, False, None),
    (pg.UNCLASSIFIED, pg.ACCEPTED, True, D_OK, False, None),
], ids=["true", "control-rejected", "a-accepted-false", "gen-unread",
        "gen-terminal-but-unreadable", "defaults-mismatch-false", "dc1-on-a",
        "unclassified-a"])
def test_decide_f1_19(a, ctrl, term, defaults, measurable, observed):
    got = pg.decide_f1_19(a, ctrl, generation_terminal=term, defaults=defaults)
    assert got["measurable"] is measurable
    assert got["observed"] is observed


@pytest.mark.parametrize("mixed,w,g,ran,measurable,observed,inverted", [
    (pg.REJECTED_GRAMMAR, pg.ACCEPTED, pg.ACCEPTED, True, True, True, True),
    (pg.ACCEPTED, pg.ACCEPTED, pg.ACCEPTED, True, True, False, False),
    # a split arm rejected: the mixed rejection is confounded
    (pg.REJECTED_GRAMMAR, pg.REJECTED_GRAMMAR, pg.ACCEPTED, True, False, None, None),
    (pg.REJECTED_GRAMMAR, pg.ACCEPTED, pg.REJECTED_GRAMMAR, True, False, None, None),
    # the mutation did not run: no verdict is available
    (pg.REJECTED_GRAMMAR, "NOT_RUN", "NOT_RUN", False, False, None, None),
    # a non-grammar failure of the mixed arm decides nothing
    (pg.VALIDATION_FINDING, pg.ACCEPTED, pg.ACCEPTED, True, False, None, None),
], ids=["true-inverted", "accepted-false", "when-split-bad", "guardrails-split-bad",
        "no-mutation", "dc1-on-mixed"])
def test_decide_f1_24(mixed, w, g, ran, measurable, observed, inverted):
    got = pg.decide_f1_24(mixed, w, g, mutation_ran=ran)
    assert (got["measurable"], got["observed"], got["inverted"]) == \
        (measurable, observed, inverted)


@pytest.mark.parametrize("forms,ctrl,measurable,observed", [
    ({"a": pg.REJECTED_GRAMMAR, "b": pg.REJECTED_GRAMMAR}, pg.ACCEPTED, True, True),
    # the sealed FALSE branch is existential: ONE accepted form decides it
    ({"a": pg.REJECTED_GRAMMAR, "b": pg.ACCEPTED}, pg.ACCEPTED, True, False),
    ({"a": pg.ACCEPTED, "b": pg.ACCEPTED}, pg.ACCEPTED, True, False),
    ({"a": pg.REJECTED_GRAMMAR, "b": pg.UNCLASSIFIED}, pg.ACCEPTED, False, None),
    ({"a": pg.REJECTED_GRAMMAR, "b": pg.REJECTED_GRAMMAR}, pg.REJECTED_GRAMMAR,
     False, None),
], ids=["all-rejected-true", "one-accepted-false", "all-accepted-false",
        "unread-form", "control-rejected"])
def test_decide_f1_25(forms, ctrl, measurable, observed):
    got = pg.decide_f1_25(forms, ctrl)
    assert (got["measurable"], got["observed"]) == (measurable, observed)


# ---------------------------------------------------------------------------
# exit code: rc reports whether the test RAN, never whether the document was right
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kw,rc", [
    (dict(n_measured=3, n_expected=3, residues_clean=True, baseline_ok=True,
          any_unclassified=False), 0),
    # a FALSE verdict still exits 0 — the verdict is not the rc's business, which is
    # why exit_code never sees a verdict at all
    (dict(n_measured=0, n_expected=3, residues_clean=True, baseline_ok=True,
          any_unclassified=False), 2),
    (dict(n_measured=3, n_expected=3, residues_clean=False, baseline_ok=True,
          any_unclassified=False), 2),
    (dict(n_measured=3, n_expected=3, residues_clean=True, baseline_ok=False,
          any_unclassified=False), 2),
    (dict(n_measured=3, n_expected=3, residues_clean=True, baseline_ok=True,
          any_unclassified=True), 1),
    (dict(n_measured=2, n_expected=3, residues_clean=True, baseline_ok=True,
          any_unclassified=False), 1),
    # residue outranks unclassified when both hold
    (dict(n_measured=1, n_expected=3, residues_clean=False, baseline_ok=True,
          any_unclassified=True), 2),
], ids=["clean", "nothing-measured", "residue", "baseline-harmed", "unclassified",
        "partial", "residue-outranks"])
def test_exit_code(kw, rc):
    assert pg.exit_code(**kw) == rc


# ---------------------------------------------------------------------------
# the sealed surface this script claims to serve
# ---------------------------------------------------------------------------

def test_the_three_cases_are_sealed_and_none_marks_its_mutation_mandatory():
    """The script checks O.mutation_is_mandatory and honors it; this pins what 'honors'
    currently means (none of the three is in the sealed mandatory list, so a missing
    mutation downgrades nothing in evaluate() — the F1-24 mutation is constitutive via
    decide_f1_24 instead, which the parametrized arms above enforce). If the seal ever
    lists one of these cases, this test goes red and the script's handling must be
    re-derived, not assumed."""
    import oracle as O
    rows = O.cases()
    for cid in pg.CASES:
        assert cid in rows and rows[cid][2] == "C"
        assert O.BINDINGS[cid].kind == "EXISTENCE"
        assert O.mutation_is_mandatory(cid) is False
