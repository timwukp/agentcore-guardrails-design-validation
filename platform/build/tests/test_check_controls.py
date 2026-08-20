"""Mutation coverage for `check_controls.py`, one arm per rule it claims to enforce.

WHY EVERY RULE NEEDS AN ARM

`check_controls.py` exited 0 against the real `controls.yaml` the first time it was run. That is the
least informative possible result: a gate whose every rule was accidentally unreachable exits 0 too,
and the two are indistinguishable from the outside. So each rule below is given a mutant that ought
to trip it, and the arm asserts both the exit code **and** a fragment of the message — because a rule
that fires for the wrong reason is a rule that will pass the wrong file later.

HOW THE MUTANTS ARE BUILT

The real `controls.yaml` is loaded, one thing is changed in the loaded structure, and the result is
dumped to a temporary file the gate is pointed at. Mutating the real structure rather than a minimal
hand-built fixture is deliberate: a fixture drifts away from the file it stands for, and then the arms
test a document nobody publishes. The census, verdict files and citation policy are the repository's
real ones throughout, because those are the artifacts the rules derive from and a fake would let a
legality rule pass over a table the real policy does not contain.

The restricted cases these arms need are **looked up from the citation policy at test time**, never
typed in. `check_controls.py` contains no case id on purpose, and a test that hardcoded `F5-3b` would
reintroduce exactly the coupling the gate was written to avoid — and would go vacuous the day the
policy moves that restriction to a different case (`feedback_scope_as_namelist`).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import check_controls as cc  # noqa: E402

yaml = pytest.importorskip("yaml", reason="the gate itself refuses to run without PyYAML")


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def real() -> dict:
    return cc.load_yaml_no_duplicate_keys(cc.CURATION)


@pytest.fixture(scope="module")
def facts() -> tuple[set[str], dict[str, str], dict[str, set[str]]]:
    registered, verdicts = cc.read_verdicts()
    return registered, verdicts, cc.read_restrictions()


@pytest.fixture(scope="module")
def by_restriction(facts) -> dict[str, list[str]]:
    """Cases grouped by the restriction the citation policy gives them, derived not typed."""
    _, _, restrictions = facts
    out: dict[str, list[str]] = {}
    for case, rs in restrictions.items():
        for r in rs:
            out.setdefault(r, []).append(case)
    return {k: sorted(v) for k, v in out.items()}


@pytest.fixture(scope="module")
def by_verdict(facts) -> dict[str, list[str]]:
    """Unrestricted cases grouped by verdict — the only ones a status rule may legally rest on."""
    _, verdicts, restrictions = facts
    out: dict[str, list[str]] = {}
    for case, v in verdicts.items():
        if not restrictions.get(case):
            out.setdefault(v, []).append(case)
    return {k: sorted(v) for k, v in out.items()}


def _pick(group: dict[str, list[str]], key: str) -> str:
    cases = group.get(key)
    if not cases:
        pytest.skip(f"the repository currently has no case with {key!r}, so this arm cannot be built "
                    f"from real artifacts and must not be built from invented ones")
    return cases[0]


def _run(tmp_path: Path, data: dict, capsys) -> tuple[int, str]:
    """Dump `data`, run the gate over it, and return (rc, everything it printed)."""
    path = tmp_path / "controls.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        rc = cc.main(["--controls", str(path)])
    except SystemExit as e:                    # `die()` for an unusable input
        rc = e.code
    captured = capsys.readouterr()
    return rc, captured.out + captured.err


def _control(data: dict, cid: str) -> dict:
    for c in data["controls"]:
        if c.get("id") == cid:
            return c
    raise AssertionError(f"control {cid} vanished from controls.yaml; this arm needs rewriting")


def _first_with_status(data: dict, status: str) -> tuple[dict, dict]:
    for c in data["controls"]:
        for f in c.get("findings") or []:
            if f.get("status") == status:
                return c, f
    pytest.skip(f"controls.yaml currently has no finding with status {status!r}")


def _first_with_restricted_citation(data: dict, restrictions: dict[str, set[str]]) -> dict:
    for c in data["controls"]:
        for f in c.get("findings") or []:
            for case in f.get("cites") or []:
                if cc.RESTRICTION_NEEDS_SCOPE & restrictions.get(case, set()):
                    return f
    pytest.skip("controls.yaml cites no case carrying PARTIAL or REPLICATION_POSITION_BOUND")


# --------------------------------------------------------------------------- 0. the control


def test_the_real_file_passes(capsys):
    """The no-mutant control. Without it every arm below would also pass if the gate had started
    failing unconditionally, which is the single most likely way this file goes vacuous."""
    rc = cc.main([])
    out = capsys.readouterr().out
    assert rc == 0, f"the published controls.yaml does not pass its own gate:\n{out}"
    assert "registered case(s)" in out and "live verdict(s)" in out, out


def test_the_dumped_round_trip_also_passes(real, tmp_path, capsys):
    """The control for the *harness*: every arm below dumps a mutated structure, so a dump that the
    gate rejected for its own reasons would make all of them pass for the wrong reason."""
    rc, out = _run(tmp_path, copy.deepcopy(real), capsys)
    assert rc == 0, f"an unmutated round-trip through yaml.safe_dump fails the gate:\n{out}"


def test_field_path_verification_passes_on_the_real_file(capsys):
    """`--verify-field-paths` is opt-in, so it needs its own control or it could be dead code."""
    pytest.importorskip("boto3", reason="introspection needs an SDK; that is why the flag is opt-in")
    rc = cc.main(["--verify-field-paths"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "verified against a live service model" in out, out


# --------------------------------------------------------------------------- 1. shape and floors


def test_an_unknown_top_level_key_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    data["contorls"] = []
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "unknown top-level key" in out, out


def test_a_wrong_schema_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    data["schema"] = "grx-controls/2"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "schema is" in out, out


def test_zero_controls_fails_rather_than_passing_over_nothing(real, tmp_path, capsys):
    """The empty case, which set-and-count rules cannot catch: no control violates any rule."""
    data = copy.deepcopy(real)
    data["controls"] = []
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "missing or empty" in out, out


def test_a_truncated_file_fails_the_floor(real, tmp_path, capsys):
    """One surviving control breaks no rule either, so the floor is a separate claim from the rules."""
    data = copy.deepcopy(real)
    data["controls"] = data["controls"][:1]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "below the floor" in out, out


def test_a_duplicate_control_id_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    data["controls"].append(copy.deepcopy(data["controls"][0]))
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "duplicates the id" in out, out


def test_a_control_with_no_findings_fails(real, tmp_path, capsys):
    """A control that can produce no statement is one the report omits in silence."""
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["findings"] = []
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "zero findings" in out, out


def test_a_detect_rule_with_no_paths_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["detect"]["paths"] = []
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "no `paths:`" in out, out


def test_a_detect_rule_with_no_stated_source_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    del _control(data, "policy_engine_mode")["detect"]["paths_source"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "paths_source" in out, out


def test_a_duplicate_key_in_one_mapping_fails(tmp_path, capsys):
    """PyYAML keeps the last duplicate silently. Written as raw text because a dict cannot hold one."""
    path = tmp_path / "controls.yaml"
    path.write_text("schema: grx-controls/1\ncontrols: []\ncontrols: []\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cc.main(["--controls", str(path)])
    assert exc.value.code == 2
    assert "twice in one mapping" in capsys.readouterr().err


# --------------------------------------------------------------------------- 2. the typo class


def test_a_misspelled_finding_key_fails(real, tmp_path, capsys):
    """`citess:` instead of `cites:` must not read as a finding that cites nothing.

    This is the arm the whole key-allowlist exists for. Without it, the status rules below are all
    defeatable by a single transposed letter, and the file would still look fully populated.
    """
    data = copy.deepcopy(real)
    control, finding = _first_with_status(data, "measured_true")
    finding["citess"] = finding.pop("cites")
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "unknown key(s) ['citess']" in out, out


def test_a_misspelled_control_key_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    control = _control(data, "policy_engine_mode")
    control["measured_bye"] = control.pop("measured_by")
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "measured_bye" in out, out


def test_an_absent_cites_key_fails(real, tmp_path, capsys):
    """An absent list and an empty one mean different things, so the key is required either way."""
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_true")
    del finding["cites"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "no `cites:` key" in out, out


def test_an_empty_cites_list_fails_under_a_measured_status(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_true")
    finding["cites"] = []
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "cites nothing" in out, out


# --------------------------------------------------------------------------- 3. measured vs not


def test_a_control_that_is_neither_measured_nor_declared_unmeasured_fails(real, tmp_path, capsys):
    """Nothing may be unmeasured by omission: the two states must be told apart in the report."""
    data = copy.deepcopy(real)
    del _control(data, "policy_engine_mode")["measured_by"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "unmeasured by omission" in out, out


def test_measured_none_with_a_thin_reason_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _control(data, "inbound_authorizer_type")["why_not_measured"] = "not tested"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "why_not_measured" in out, out


def test_measured_none_with_a_measured_finding_fails(real, tmp_path, capsys):
    """A control no case looked at cannot produce a measured statement about the reader's system."""
    data = copy.deepcopy(real)
    control = _control(data, "inbound_authorizer_type")
    control["findings"][0]["status"] = "measured_true"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "cannot produce a measured statement" in out, out


def test_a_measured_control_claiming_not_measured_fails(real, tmp_path, capsys):
    """The other direction: resting on a case *and* reporting that nobody looked is a contradiction."""
    data = copy.deepcopy(real)
    control = _control(data, "policy_engine_mode")
    control["findings"][0]["status"] = "not_measured"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "cannot both rest on a case" in out, out


def test_declaring_both_measured_by_and_measured_none_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    control = _control(data, "policy_engine_mode")
    control["measured"] = "none"
    control["why_not_measured"] = "x" * (cc.MIN_WHY_NOT_MEASURED + 10)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "cannot be both" in out, out


def test_a_thin_why_in_measured_by_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["measured_by"][0]["why"] = "it measures it"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "`why` is" in out, out


def test_a_case_not_in_the_register_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["measured_by"][0]["case"] = "F99-1"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "not in the sealed register" in out, out


def test_not_measured_that_cites_something_fails(real, tmp_path, by_verdict, by_restriction, capsys):
    """Citing anything under `not_measured` manufactures evidence out of its own absence."""
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "not_measured")
    restricted = {c for cs in by_restriction.values() for c in cs}
    unrestricted = [c for c in by_verdict["TRUE"] if c not in restricted]
    assert unrestricted, "no unrestricted TRUE case exists; this arm would test the wrong rule"
    finding["cites"] = [unrestricted[0]]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "has nothing to cite" in out, out


def test_not_measured_without_a_reason_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "not_measured")
    finding["why_not_measured"] = "n/a"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "must say why" in out, out


# --------------------------------------------------------------------------- 4. citation legality


def test_measured_true_citing_a_false_verdict_fails(real, tmp_path, by_verdict, capsys):
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_true")
    finding["cites"] = [_pick(by_verdict, "FALSE")]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "requires TRUE" in out, out


def test_measured_false_citing_a_true_verdict_fails(real, tmp_path, by_verdict, capsys):
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_false")
    finding["cites"] = [_pick(by_verdict, "TRUE")]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "requires FALSE" in out, out


def test_an_inconclusive_case_cited_as_a_measured_result_fails(real, tmp_path, by_restriction,
                                                               capsys):
    """The study's own editorial rule, enforced: an INCONCLUSIVE verdict is not evidence against."""
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_false")
    finding["cites"] = [_pick(by_restriction, "NOT_EVIDENCE_AGAINST")]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "not evidence against a claim" in out, out


def test_a_never_cite_case_in_a_finding_fails(real, tmp_path, by_restriction, capsys):
    """The case whose verdict on disk is TRUE and which may be cited as nothing at all."""
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_true")
    finding["cites"] = [_pick(by_restriction, "NEVER_CITE")]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "NEVER_CITE" in out, out


def test_a_never_cite_case_in_measured_by_also_fails(real, tmp_path, by_restriction, capsys):
    """"Cited as nothing" includes being named as the case that measured a control."""
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["measured_by"][0]["case"] = _pick(by_restriction,
                                                                          "NEVER_CITE")
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "including as the case that measured" in out, out


def test_a_mechanism_only_case_cited_as_a_verdict_fails(real, tmp_path, by_restriction, capsys):
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_true")
    finding["cites"] = [_pick(by_restriction, "MECHANISM_ONLY")]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "context_only" in out, out


def test_a_partial_citation_without_its_scope_fails(real, tmp_path, facts, capsys):
    """A restriction travels with the citation; dropping it publishes a wider claim than the evidence."""
    data = copy.deepcopy(real)
    _, _, restrictions = facts
    finding = _first_with_restricted_citation(data, restrictions)
    del finding["scope_note"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "restriction travels with the citation" in out, out


def test_a_thin_scope_note_fails(real, tmp_path, facts, capsys):
    data = copy.deepcopy(real)
    _, _, restrictions = facts
    _first_with_restricted_citation(data, restrictions)["scope_note"] = "p50 only"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "scope_note of" in out, out


def test_a_scope_note_on_an_unrestricted_citation_fails(real, tmp_path, capsys):
    """The other direction. A note where none is needed trains readers to skip the ones that matter."""
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_true")
    finding["scope_note"] = "x" * (cc.MIN_SCOPE_NOTE + 10)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "cites no case that needs one" in out, out


def test_an_unclassified_restriction_is_not_treated_as_no_restriction(real, tmp_path, monkeypatch,
                                                                     by_verdict, capsys):
    """If the citation policy grows a restriction this gate does not know, that must be a finding.

    The dangerous default is the opposite: an unrecognised restriction falling through every `if` and
    reading as an unrestricted case. Injected by shrinking the gate's own classification sets, which
    is the same thing as the policy growing a new one.
    """
    data = copy.deepcopy(real)
    case = _pick(by_verdict, "TRUE")
    monkeypatch.setattr(cc, "read_restrictions",
                        lambda: {case: {"SOME_RESTRICTION_ADDED_LATER"}})
    _, finding = _first_with_status(data, "measured_true")
    finding["cites"] = [case]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "does not classify" in out, out


# --------------------------------------------------------------------------- 5. reachability


def test_a_when_value_the_detector_cannot_produce_fails(real, tmp_path, capsys):
    """A rule that can never fire looks exactly like a rule that passed."""
    data = copy.deepcopy(real)
    control = _control(data, "policy_engine_mode")
    for finding in control["findings"]:
        if "value" in (finding.get("when") or {}):
            finding["when"]["value"] = "ENFORCE_BUT_MISSPELLED"
            break
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "can never fire" in out, out


def test_a_when_value_with_no_declared_values_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    del _control(data, "policy_engine_mode")["detect"]["values"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "no `values:` list" in out, out


def test_an_unknown_when_key_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["findings"][0]["when"] = {"valeu": "ENFORCE"}
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "unknown key(s) ['valeu']" in out, out


def test_a_bad_observation_value_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["findings"][0]["when"] = {"observation": "MAYBE"}
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "when.observation" in out, out


def test_thin_prose_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _, finding = _first_with_status(data, "measured_true")
    finding["says"] = "it is bad"
    finding["consequence"] = "fix it"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "`says` is" in out and "`consequence` is" in out, out


# --------------------------------------------------------------------------- 6. field paths


@pytest.fixture(autouse=True, scope="module")
def _need_boto3():
    pytest.importorskip("boto3", reason="the field-path arms introspect a real service model")


def _run_paths(tmp_path: Path, data: dict, capsys) -> tuple[int, str]:
    path = tmp_path / "controls.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        rc = cc.main(["--controls", str(path), "--verify-field-paths"])
    except SystemExit as e:
        rc = e.code
    captured = capsys.readouterr()
    return rc, captured.out + captured.err


def test_a_detect_path_no_service_model_has_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["detect"]["paths"] = ["policyengineconfiguration.moed"]
    _control(data, "policy_engine_mode")["detect"]["value_from"] = "policyengineconfiguration.moed"
    rc, out = _run_paths(tmp_path, data, capsys)
    assert rc == 2 and "is in no service model" in out, out


def test_dropping_an_exemption_fails(real, tmp_path, capsys):
    """The exemptions are load-bearing, so removing one must be loud rather than silently fine."""
    data = copy.deepcopy(real)
    data["unverifiable_paths"] = data["unverifiable_paths"][1:]
    rc, out = _run_paths(tmp_path, data, capsys)
    assert rc == 2 and "not listed under `unverifiable_paths:`" in out, out


def test_an_exemption_for_a_path_the_model_does_have_fails(real, tmp_path, capsys):
    """The both-directions arm. A stale exemption is where a real typo hides next time."""
    data = copy.deepcopy(real)
    data["unverifiable_paths"].append(
        {"path": "policyengineconfiguration.mode",
         "why": "x" * (cc.MIN_WHY + 10)})
    rc, out = _run_paths(tmp_path, data, capsys)
    assert rc == 2 and "the service model does have it" in out, out


def test_an_exemption_no_control_uses_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    data["unverifiable_paths"].append(
        {"path": "some.path.nobody.matches.on", "why": "x" * (cc.MIN_WHY + 10)})
    rc, out = _run_paths(tmp_path, data, capsys)
    assert rc == 2 and "no control uses it" in out, out


def test_an_exemption_without_a_reason_fails(real, tmp_path, capsys):
    data = copy.deepcopy(real)
    data["unverifiable_paths"][0] = {"path": data["unverifiable_paths"][0]["path"]}
    rc, out = _run_paths(tmp_path, data, capsys)
    assert rc == 2 and "needs both `path:` and `why:`" in out, out


def test_value_from_outside_the_rules_own_paths_fails(real, tmp_path, capsys):
    """Otherwise the value is read from a field the rule never matched on."""
    data = copy.deepcopy(real)
    _control(data, "policy_engine_mode")["detect"]["value_from"] = "enforcementmode"
    rc, out = _run_paths(tmp_path, data, capsys)
    assert rc == 2 and "not one of this rule's" in out, out


def test_introspection_that_yields_almost_nothing_is_an_error(real, tmp_path, monkeypatch, capsys):
    """A gate that cannot introspect must not report every path as unverifiable and carry on.

    Without this, an SDK change that broke `model_paths` would turn the whole verification into a
    formality: 0 known paths means nothing is verified and — with exemptions in place — nothing is
    reported either (`feedback_guard_tool_exit_codes`).
    """
    data = copy.deepcopy(real)
    monkeypatch.setattr(cc, "model_paths", lambda *a, **k: set())
    rc, out = _run_paths(tmp_path, data, capsys)
    assert rc == 2 and "field path(s)" in out, out


# --------------------------------------------------------------------------- 7. the inputs


def test_a_truncated_phase1_tree_is_an_error_not_an_empty_verdict_map(monkeypatch, capsys):
    """Every status rule reads a verdict. Over an empty verdict map they would all report `None`,
    which is a different message but the same uselessness — so the floor comes first."""
    monkeypatch.setattr(cc, "PHASE1", REPO / "platform")     # a real directory with no verdicts
    with pytest.raises(SystemExit) as exc:
        cc.read_verdicts()
    assert exc.value.code == 2
    assert "below the floor" in capsys.readouterr().err


def test_a_citation_policy_with_no_restrictions_is_an_error(monkeypatch, tmp_path, capsys):
    """Every legality rule intersects with the restriction table; over an empty table all pass."""
    fake = tmp_path / "CITATION-POLICY.md"
    fake.write_text("# x\n<!-- machine " + json.dumps({"restrictions": []}) + " -->\n",
                    encoding="utf-8")
    monkeypatch.setattr(cc, "CITATION_POLICY", fake)
    with pytest.raises(SystemExit) as exc:
        cc.read_restrictions()
    assert exc.value.code == 2
    assert "zero restrictions" in capsys.readouterr().err
