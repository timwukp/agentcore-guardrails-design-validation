"""F8-1's pure functions, each arm pinned to the defect it exists to catch.

The nine-region probe's whole risk budget is silent misdirection: a region list typed
from memory instead of parsed from the seal, an error classifier that swallows an unread
failure into the document-confirming class, a residue read off the deletions list that
reports zero survivors precisely when one exists, and a client that quietly resolved a
default Region nine times. Every one of those is a pure function in
`08_policy_engine_regions.py`, so every one is testable here with no credentials and no
network (the `no_aws` fixture in conftest.py enforces both).

Arms with no mutation target are NAMED as such in their docstrings rather than implied
covered; the mutation run over this file is reported in the session log, not asserted
from inside it.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

import awsclients as A
import oracle as O

ROOT = Path(__file__).resolve().parents[2]


def _load(stem: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "f8_regional" / stem)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M8 = _load("08_policy_engine_regions.py", "f8_pe_regions")

# A display-name map assembled locally so the parser arms do not depend on botocore's
# data files; codes are built from parts (no region literal doubles as an ARN shape, so
# plain codes are fine — check_redaction targets ARNs and account ids).
DESCS = {
    "US East (N. Virginia)": "us-east-1",
    "Europe (London)": "eu-west-2",
    "Europe (Stockholm)": "eu-north-1",
    "Asia Pacific (Sydney)": "ap-southeast-2",
    "Asia Pacific (Tokyo)": "ap-northeast-1",
    "Asia Pacific (Singapore)": "ap-southeast-1",
    "US West (Oregon)": "us-west-2",
}

SEAL_LIKE = (
    "Guardrails-in-policy is currently available only in US East (N. Virginia), "
    "Europe (London), Europe (Stockholm), Asia Pacific (Sydney), and Asia Pacific "
    "(Tokyo). Singapore (ap-southeast-1) and most other Asia Pacific Regions are "
    "NOT yet supported — confirm Regional support first."
)


# ===================================================== region derivation

def test_supported_regions_derive_from_the_seal_and_match_the_harness_constant():
    """END-TO-END against the real sealed artifacts: the parse of claims/triage.csv
    through botocore's endpoints data must reproduce the harness's own list. If either
    the seal or awsclients.GUARDRAILS_IN_POLICY_SUPPORTED changes alone, this reds."""
    seal = M8.supported_regions_from_seal()
    assert seal["regions"] == tuple(A.GUARDRAILS_IN_POLICY_SUPPORTED)
    assert seal["sealed_carrier"] == "C-s1-quote-001"
    assert len(seal["regions"]) == 5


def test_supported_derivation_is_nonempty():
    """A zero-region scan must be an error, not a pass: the sealed derivation must
    yield a NON-EMPTY tuple, and the count must match the sealed title's 'exactly 5'."""
    seal = M8.supported_regions_from_seal()
    assert seal["regions"], "an empty derived region list would confirm anything"
    assert len(seal["regions"]) == M8.sealed_supported_count() == seal["sealed_count"]


def test_parser_orders_regions_by_position_in_the_sealed_sentence():
    got = M8.parse_supported_regions(SEAL_LIKE, DESCS)
    assert got == ("us-east-1", "eu-west-2", "eu-north-1",
                   "ap-southeast-2", "ap-northeast-1")


def test_parser_refuses_a_text_without_the_availability_marker():
    """A sealed sentence rewritten so 'available only in' vanishes must STOP the case,
    not let this file quietly supply a list of its own."""
    with pytest.raises(ValueError, match="marker"):
        M8.parse_supported_regions("Regions: US East (N. Virginia).", DESCS)


def test_parser_refuses_an_empty_parse():
    """Marker present, zero display names found: the empty-derivation refusal."""
    with pytest.raises(ValueError, match="zero Region"):
        M8.parse_supported_regions(
            "available only in some places. NOT yet supported elsewhere.", DESCS)


def test_parser_does_not_leak_the_named_unsupported_region_into_available():
    """'Singapore (ap-southeast-1)' is a raw code, not a display name, and sits after
    the availability segment; a parser that swept the whole text for codes would count
    the seal's one explicit NEGATIVE example as available."""
    got = M8.parse_supported_regions(SEAL_LIKE, DESCS)
    assert "ap-southeast-1" not in got


def test_parser_stops_at_the_end_of_the_enumeration():
    """A display name appearing LATER in the text — say in a not-supported clause — must
    not join the available set: the parse consumes the enumeration, not a text window.
    (The first draft scanned a window bounded by the NOT-marker and this arm caught it:
    a name before the marker leaked in.)"""
    text = ("available only in US East (N. Virginia). Asia Pacific (Singapore) is "
            "NOT yet supported.")
    assert M8.parse_supported_regions(text, DESCS) == ("us-east-1",)


def test_parser_survives_the_period_inside_n_virginia():
    """Naive sentence-splitting dies on 'N. Virginia'; the enumeration parse must not:
    the name containing the period is consumed whole and the next name still counts."""
    text = "available only in US East (N. Virginia), and Europe (London). More prose."
    assert M8.parse_supported_regions(text, DESCS) == ("us-east-1", "eu-west-2")


def test_seal_names_singapore_unsupported_and_the_default_probe_set_omits_it():
    """Documents the recorded gap: the seal's single named-unsupported Region is not
    among the four probed unavailable Regions. If either side changes — the probe set
    gains ap-southeast-1 or the seal drops it — this arm reds and the deviation text in
    the payload is stale."""
    seal = M8.supported_regions_from_seal()
    assert seal["seal_named_unsupported"] == ("ap-southeast-1",)
    plan = M8.probe_regions(seal["regions"])
    assert "ap-southeast-1" not in plan["regions"]
    assert "deviation" in plan and "awsclients" in plan["deviation"]


def test_probe_regions_width_matches_the_sealed_method_and_contains_the_five():
    seal = M8.supported_regions_from_seal()
    plan = M8.probe_regions(seal["regions"])
    assert len(plan["regions"]) == M8.sealed_probe_count() == 9
    assert set(seal["regions"]) <= set(plan["regions"])
    assert len(set(plan["regions"])) == len(plan["regions"])
    assert plan["regions"], "a zero-region probe plan must be an error"
    assert len(plan["unsupported_probed"]) == 4


def test_probe_regions_refuses_a_plan_missing_a_sealed_available_region():
    """The success half of the oracle is unmeasurable if a sealed Region is absent from
    the plan; feeding a supported set the plan cannot cover must raise."""
    seal = M8.supported_regions_from_seal()
    with pytest.raises(RuntimeError, match="omits"):
        M8.probe_regions(tuple(seal["regions"]) + ("mx-central-1",))


def test_sealed_counts_agree_with_the_sealed_binding():
    """The 'exactly 5' in the title, the binding threshold 5.0, and the '9-region'
    method text are three sealed carriers; the parsers must read them, not remember
    them."""
    assert M8.sealed_supported_count() == int(O.BINDINGS["F8-1"].thresholds[0]) == 5
    assert M8.sealed_probe_count() == 9


def test_sealed_rows_lookup_refuses_a_case_with_no_row():
    with pytest.raises(RuntimeError, match="no sealed claim row"):
        M8.sealed_rows_for_case("F8-999")


def test_probe_plan_refuses_a_width_other_than_the_sealed_nine(monkeypatch):
    """The membership of the unavailable side is unsealed but the WIDTH is not: an
    8-region list under a sealed '9-region probe' must refuse."""
    seal = M8.supported_regions_from_seal()
    monkeypatch.setattr(A, "F8_1_REGIONS", tuple(A.F8_1_REGIONS[:-1]))
    with pytest.raises(RuntimeError, match="9-region"):
        M8.probe_regions(seal["regions"])


def test_probe_plan_refuses_duplicates(monkeypatch):
    seal = M8.supported_regions_from_seal()
    dup = tuple(A.F8_1_REGIONS[:-1]) + (A.F8_1_REGIONS[0],)
    monkeypatch.setattr(A, "F8_1_REGIONS", dup)
    with pytest.raises(RuntimeError, match="duplicate"):
        M8.probe_regions(seal["regions"])


def test_probe_plan_refuses_an_empty_region_list(monkeypatch):
    """A zero-region probe must be an error, not a pass — the probe-plan side of the
    same rule the parser enforces on the seal side."""
    seal = M8.supported_regions_from_seal()
    monkeypatch.setattr(A, "F8_1_REGIONS", ())
    with pytest.raises(RuntimeError, match="empty|zero"):
        M8.probe_regions(seal["regions"])


def test_region_descriptions_refuses_an_empty_endpoints_read(monkeypatch):
    """An empty display-name map would parse every seal as empty; the instrument must
    stop the case rather than parse everything as nothing."""
    class _FakeSession:
        def get_data(self, name):
            return {"partitions": []}

    import botocore.session
    monkeypatch.setattr(botocore.session, "get_session", lambda: _FakeSession())
    with pytest.raises(RuntimeError, match="zero region descriptions"):
        M8.region_descriptions()


def test_region_descriptions_is_nonempty_and_maps_the_five():
    """The instrument that reads the seal: an empty display-name map would parse every
    seal as empty, so it must refuse — and it must actually carry the five names the
    sealed row uses."""
    descs = M8.region_descriptions()
    assert descs, "an empty endpoints read must raise inside region_descriptions"
    for desc, code in DESCS.items():
        if desc != "US West (Oregon)":
            assert descs.get(desc) == code


# ===================================================== the error classifier

def _cls(code="", klass="", msg="", status=None):
    return M8.classify_failure(error_code=code, error_class=klass,
                               error_message=msg, http_status=status)


def test_classifier_access_denied_never_supports():
    """The IAM gap that reads exactly like unavailability."""
    c = _cls(code="AccessDeniedException", msg="not authorized to perform")
    assert c["class"] == "access_denied"
    assert c["supports_absence"] == "never"


def test_classifier_throttle_never_supports():
    c = _cls(code="ThrottlingException")
    assert c["class"] == "throttled"
    assert c["supports_absence"] == "never"
    assert _cls(code="WeirdCode", status=429)["class"] == "throttled"


def test_classifier_feature_absent_by_code():
    c = _cls(code="UnknownOperationException")
    assert c["class"] == "feature_not_available"
    assert c["supports_absence"] == "yes"


def test_classifier_feature_absent_by_message_on_a_dual_use_code():
    c = _cls(code="ValidationException",
             msg="This operation is not supported in this Region")
    assert c["class"] == "feature_not_available"


def test_classifier_bare_validation_exception_is_not_feature_absence():
    """ValidationException is what a malformed NAME gets too; without the unavailability
    message it must not be scored as regional evidence."""
    c = _cls(code="ValidationException", msg="name does not match pattern")
    assert c["class"] == "unclassified"
    assert c["supports_absence"] == "never"


def test_classifier_endpoint_failure_is_conditional():
    c = _cls(klass="EndpointConnectionError",
             msg="Could not connect to the endpoint URL")
    assert c["class"] == "endpoint_unresolvable"
    assert c["supports_absence"] == "conditional"


def test_classifier_unclassified_branch_never_supports():
    """The crux: an error nobody has read must NOT be scored as a supporting failure."""
    c = _cls(code="EntirelyNovelException", msg="???")
    assert c["class"] == "unclassified"
    assert c["supports_absence"] == "never"


# ===================================================== verdict logic

SUP = ("us-east-1", "eu-west-2", "eu-north-1", "ap-southeast-2", "ap-northeast-1")
OTH = ("us-west-2", "eu-central-1", "sa-east-1", "ap-south-1")
ALL = SUP + OTH


def _outs(mapping):
    return [{"region": r, "outcome": oc} for r, oc in mapping.items()]


def _clean():
    m = {r: "created" for r in SUP}
    m.update({r: "feature_not_available" for r in OTH})
    return m


def test_verdict_true_when_all_nine_are_decisive():
    v = M8.verdict_from_outcomes(_outs(_clean()), SUP, ALL)
    assert v["verdict_bool"] is True
    assert not v["mismatches"] and not v["ambiguous"]
    assert len(v["supports"]) == 9


def test_verdict_false_when_an_unsupported_region_creates_an_engine():
    """'FALSE on any mismatch': a success where the document says unavailable."""
    m = _clean()
    m["sa-east-1"] = "created"
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is False
    assert any(x["region"] == "sa-east-1" for x in v["mismatches"])


def test_verdict_false_when_a_listed_region_is_distinguishably_refused():
    """The FALSE must come from THE refused listed Region, not incidentally from
    elsewhere: the first mutation run produced a mutant that swapped the refusal
    buckets and still returned FALSE (the four unavailable Regions were misrouted into
    mismatches), so a verdict-only assertion let it survive. The mismatch row itself is
    what pins the routing."""
    m = _clean()
    m["eu-north-1"] = "feature_not_available"
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is False
    assert [x["region"] for x in v["mismatches"]] == ["eu-north-1"]
    assert {x["region"] for x in v["supports"]} == set(ALL) - {"eu-north-1"}


def test_verdict_false_beats_ambiguity_elsewhere():
    """A decisive mismatch decides the case even when another Region is unmeasured —
    the seal says 'FALSE on any mismatch', not 'FALSE if fully measured'."""
    m = _clean()
    m["sa-east-1"] = "created"
    m["ap-south-1"] = "access_denied"
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is False


def test_verdict_access_denied_blocks_true():
    """An IAM gap in one Region leaves the case unmeasured rather than confirmed."""
    m = _clean()
    m["ap-south-1"] = "access_denied"
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is None
    assert any(a["region"] == "ap-south-1" for a in v["ambiguous"])


def test_verdict_unclassified_error_is_never_a_supporting_failure():
    """The taxonomy's load-bearing rule, applied end to end."""
    m = _clean()
    m["us-west-2"] = "unclassified"
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is None


def test_verdict_endpoint_failure_supports_only_with_a_network_control():
    """With every Region unreachable there is no round trip proving the box is online,
    so nine endpoint failures must not read as nine absences."""
    m = {r: "endpoint_unresolvable" for r in ALL}
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is None
    assert v["network_control_ok"] is False


def test_verdict_endpoint_failure_with_corroboration_supports():
    m = _clean()
    m["ap-south-1"] = "endpoint_unresolvable"
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is True
    basis = next(s for s in v["supports"] if s["region"] == "ap-south-1")["basis"]
    assert "endpoint_corroborated" in basis


def test_verdict_endpoint_failure_in_a_listed_region_is_a_mismatch_when_corroborated():
    m = _clean()
    m["eu-west-2"] = "endpoint_unresolvable"
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is False


def test_verdict_a_region_never_probed_blocks_true():
    """A 7/9 probe cannot report on a 9-region claim: coverage is part of TRUE."""
    m = _clean()
    m.pop("eu-central-1")
    v = M8.verdict_from_outcomes(_outs(m), SUP, ALL)
    assert v["verdict_bool"] is None
    assert any(a["region"] == "eu-central-1" and a["why"] == "never probed"
               for a in v["ambiguous"])


def test_verdict_over_zero_outcomes_is_not_true():
    """The degenerate zero-region case: nothing measured must never read as confirmed."""
    v = M8.verdict_from_outcomes([], SUP, ALL)
    assert v["verdict_bool"] is None


def test_verdict_over_an_empty_intended_list_is_not_true_by_vacuity():
    """With zero intended Regions, zero supports satisfies the coverage equation; the
    nonempty-supports conjunct is what keeps that from reading as TRUE."""
    v = M8.verdict_from_outcomes([], SUP, ())
    assert v["verdict_bool"] is None


# ===================================================== seal-derivation refusals
# These monkeypatch the sealed-row reader so the guards in supported_regions_from_seal
# have red arms: each refusal branch fires only when the seal and the parse disagree,
# which the real artifacts (correctly) never do.

def test_seal_derivation_refuses_a_partial_parse(monkeypatch):
    """A row yielding 2 Regions against a sealed 'exactly 5' must stop the case, not
    probe a 2-region claim under the seal's name."""
    monkeypatch.setattr(M8, "sealed_rows_for_case", lambda cid, path=None: [
        ("X-row", "available only in US East (N. Virginia), Europe (London).")])
    with pytest.raises(RuntimeError, match="sealed title says exactly"):
        M8.supported_regions_from_seal()


def test_seal_derivation_refuses_disagreement_with_the_harness_constant(monkeypatch):
    """Five Regions parsed but not the harness's five: two derivations of one sealed
    fact disagree, and probing under either would attribute the choice to the seal."""
    monkeypatch.setattr(M8, "sealed_rows_for_case", lambda cid, path=None: [
        ("X-row", "available only in US East (N. Virginia), Europe (London), Europe "
                  "(Stockholm), Asia Pacific (Sydney), and US West (Oregon).")])
    with pytest.raises(RuntimeError, match="disagrees"):
        M8.supported_regions_from_seal()


def test_seal_derivation_refuses_two_carrier_rows(monkeypatch):
    """Two sealed rows both carrying the marker: which supplies the list would be a
    silent choice, so it must be a refusal instead."""
    row = "available only in US East (N. Virginia)."
    monkeypatch.setattr(M8, "sealed_rows_for_case",
                        lambda cid, path=None: [("A-row", row), ("B-row", row)])
    with pytest.raises(RuntimeError, match="two sealed rows"):
        M8.supported_regions_from_seal()


def test_seal_derivation_refuses_when_no_row_carries_the_marker(monkeypatch):
    monkeypatch.setattr(M8, "sealed_rows_for_case",
                        lambda cid, path=None: [("A-row", "prose with no list")])
    with pytest.raises(RuntimeError, match="carries"):
        M8.supported_regions_from_seal()


def test_sealed_count_refuses_a_binding_that_drifted_from_the_title(monkeypatch):
    """The 'exactly 5' title and the binding threshold are two sealed carriers of one
    number; if they ever disagree, neither may be preferred silently."""
    monkeypatch.setitem(O.BINDINGS, "F8-1",
                        O.Binding("EXISTENCE", (6.0,), ("6",), unit="count"))
    with pytest.raises(ValueError, match="disagree"):
        M8.sealed_supported_count()


# ===================================================== residue

def _made(*pairs):
    return [{"region": r, "engine_id": e, "name": f"grx_pe_f81_{r.replace('-', '_')}"}
            for r, e in pairs]


def test_residue_clean_when_every_created_engine_was_deleted():
    created = _made(("us-east-1", "pe1"), ("eu-west-2", "pe2"))
    dels = [{"region": "us-east-1", "engine_id": "pe1", "deleted": True},
            {"region": "eu-west-2", "engine_id": "pe2", "deleted": True}]
    r = M8.residue(created, dels)
    assert r["clean"] is True and r["surviving"] == [] and r["n_created"] == 2


def test_residue_counts_a_never_attempted_delete_as_a_survivor():
    """THE two-list property: an engine whose delete was never attempted contributes no
    deletion row, so a residue computed from the deletions alone would report zero
    survivors in exactly the case where one exists."""
    created = _made(("us-east-1", "pe1"), ("eu-west-2", "pe2"))
    dels = [{"region": "us-east-1", "engine_id": "pe1", "deleted": True}]
    r = M8.residue(created, dels)
    assert r["clean"] is False
    assert r["surviving"] == [{"region": "eu-west-2", "engine_id": "pe2"}]
    assert r["never_attempted"] == [{"region": "eu-west-2", "engine_id": "pe2"}]


def test_residue_counts_a_failed_delete_as_a_survivor():
    created = _made(("sa-east-1", "pe9"))
    dels = [{"region": "sa-east-1", "engine_id": "pe9", "deleted": False}]
    r = M8.residue(created, dels)
    assert r["surviving"] == [{"region": "sa-east-1", "engine_id": "pe9"}]
    assert r["never_attempted"] == []


def test_residue_is_reported_per_engine_and_region_not_as_one_bool():
    """A survivor must carry its Region and id — 'teardown failed' without them is a
    sweep of the whole account."""
    created = _made(("us-east-1", "pe1"), ("ap-south-1", "pe2"))
    r = M8.residue(created, [])
    assert {(s["region"], s["engine_id"]) for s in r["surviving"]} == {
        ("us-east-1", "pe1"), ("ap-south-1", "pe2")}


def test_residue_keys_on_region_and_id_together():
    """The same id string deleted in the WRONG Region must not clear the survivor."""
    created = _made(("us-east-1", "pe1"))
    dels = [{"region": "eu-west-2", "engine_id": "pe1", "deleted": True}]
    r = M8.residue(created, dels)
    assert r["surviving"] == [{"region": "us-east-1", "engine_id": "pe1"}]


# ===================================================== region pinning

class _Meta:
    def __init__(self, region, endpoint):
        self.region_name = region
        self.endpoint_url = endpoint


class _Client:
    def __init__(self, region, endpoint):
        self.meta = _Meta(region, endpoint)


def test_region_pin_passes_and_records_when_client_matches():
    c = _Client("eu-north-1",
                "https://bedrock-agentcore-control.eu-north-1.amazonaws.com")
    rec = M8.assert_region_pinned(c, "eu-north-1")
    assert rec["resolved"] == "eu-north-1" and "eu-north-1" in rec["endpoint"]


def test_region_pin_refuses_a_client_resolved_to_another_region():
    """The single most likely silent failure in a multi-region loop: a client that fell
    back to a default would report the default's availability nine times."""
    c = _Client("us-east-1",
                "https://bedrock-agentcore-control.us-east-1.amazonaws.com")
    with pytest.raises(RuntimeError, match="resolved region"):
        M8.assert_region_pinned(c, "eu-north-1")


def test_region_pin_refuses_an_endpoint_naming_another_region():
    """Attribute and wire destination must agree; the wire is what the probe measures."""
    c = _Client("eu-north-1",
                "https://bedrock-agentcore-control.us-east-1.amazonaws.com")
    with pytest.raises(RuntimeError, match="endpoint"):
        M8.assert_region_pinned(c, "eu-north-1")


# ===================================================== the deletable guard

def test_assert_deletable_allows_this_runs_own_engine():
    M8.assert_deletable("pe1", "grx_pe_f81_us_east_1_r1", frozenset({"pe1"}),
                        frozenset())


def test_assert_deletable_refuses_an_engine_this_run_did_not_create():
    with pytest.raises(RuntimeError, match="someone else's"):
        M8.assert_deletable("pe_other", "grx_pe_f81_us_east_1_r1",
                            frozenset({"pe1"}), frozenset())


def test_assert_deletable_refuses_the_protected_ledger_engine():
    """The baseline engine carries the policy later phases read; protection must hold
    even if the id somehow entered the created list."""
    with pytest.raises(RuntimeError, match="protected"):
        M8.assert_deletable("pe_ledger", "grx_pe_f81_x", frozenset({"pe_ledger"}),
                            frozenset({"pe_ledger"}))


def test_assert_deletable_refuses_a_name_outside_this_cases_namespace():
    """agentcore_test_pe_*, harness_*, uitestagent_* and the ledger's grx_pe_<runid>
    all fail the prefix check by construction."""
    for name in ("agentcore_test_pe_1", "harness_thing", "uitestagent_thing",
                 "grx_pe_r20990101T000000Z"):
        with pytest.raises(RuntimeError, match="namespace"):
            M8.assert_deletable("pe1", name, frozenset({"pe1"}), frozenset())


# ===================================================== names and exit codes

def test_engine_name_satisfies_the_no_hyphen_grammar_for_every_probed_region():
    """CreatePolicyEngine's name pattern forbids hyphens and caps at 48 (DEV-P2-02);
    the longest region code with a real run id must fit."""
    pat = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
    for region in A.F8_1_REGIONS:
        n = M8.engine_name("r20260810T130945Z", region)
        assert pat.fullmatch(n), n
        assert len(n) <= 48, n
        assert n.startswith(M8.ENGINE_NAME_PREFIX)


def test_exit_code_zero_only_when_all_probed_and_residue_clean():
    assert M8.run_exit_code(n_probed=9, n_intended=9, residue_clean=True) == 0


def test_exit_code_two_when_residue_survives_whatever_else_happened():
    """A survivor must never exit clean, even from a fully probed run."""
    assert M8.run_exit_code(n_probed=9, n_intended=9, residue_clean=False) == 2


def test_exit_code_two_when_nothing_was_measured():
    assert M8.run_exit_code(n_probed=0, n_intended=9, residue_clean=True) == 2


def test_exit_code_one_for_a_partial_probe():
    assert M8.run_exit_code(n_probed=7, n_intended=9, residue_clean=True) == 1


def test_exit_code_reports_running_not_rightness():
    """No verdict argument exists: the rc cannot encode whether the document was right.
    (No mutation target — this arm pins the SIGNATURE, and a verdict parameter added to
    run_exit_code would red it as a TypeError.)"""
    import inspect
    params = inspect.signature(M8.run_exit_code).parameters
    assert set(params) == {"n_probed", "n_intended", "residue_clean"}


# ===================================================== seal honoring

def test_planned_n_and_mutation_mandatory_are_read_not_assumed():
    """The script's stated premises about the seal, pinned so a re-seal that gives F8-1
    an n or a mandatory mutation reds HERE instead of silently invalidating the payload
    text. (No mutation target in 08_*.py — this arm guards against the SEAL moving.)"""
    assert O.planned_n("F8-1") is None
    assert O.mutation_is_mandatory("F8-1") is False
