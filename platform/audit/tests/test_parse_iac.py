#!/usr/bin/env python3
"""Arms for the submission parser. Each one asserts a specific way it must not lie.

TWO FAILURE MODES, AND WHICH ONE THESE TESTS ARE FOR

A parser like this can be wrong in two directions, and they are not symmetric. Reporting a control
DECLARED when the template does not declare it produces a finding a reader can walk to the cited line
and refute — embarrassing, self-correcting. Reporting NOT_DECLARED when the template *does* declare it
produces a **false clean**: a reader is told the audit looked and saw nothing, when in truth the
parser could not read the file. Nothing in the report distinguishes that from a genuinely absent
control. So the weight here is on the second: the generated-template arm below drives every control in
the real `controls.yaml` through the parser, so a detection rule the parser structurally cannot match
fails a test instead of quietly reporting NOT_DECLARED forever.

WHY TEMPLATES ARE GENERATED FROM `controls.yaml` RATHER THAN WRITTEN OUT

A hand-written fixture template freezes today's 19 controls. Add a twentieth with a path shape the
matcher does not handle and every test still passes. Generating the fixture from each control's own
`detect` block means the arm's coverage grows with the authored file, which is the same reason
`test_check_controls.py` deep-copies the real YAML instead of building its own.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve()
AUDIT = HERE.parent.parent
REPO = AUDIT.parent.parent
sys.path.insert(0, str(AUDIT))
sys.path.insert(0, str(REPO / "platform" / "build"))

import check_controls  # noqa: E402
import parse_iac  # noqa: E402

CONTROLS_YAML = REPO / "platform" / "curation" / "controls.yaml"


# --------------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def controls() -> list[dict]:
    data = check_controls.load_yaml_no_duplicate_keys(CONTROLS_YAML)
    got = data.get("controls") or []
    assert len(got) >= check_controls.MIN_CONTROLS, "the real controls file is the fixture; an empty " \
                                                    "one would make every arm below vacuous"
    return got


def write(root: Path, rel: str, obj) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1) if not isinstance(obj, str) else obj, encoding="utf-8")
    return p


def nest(path: str, value) -> dict:
    """`{'a': {'b': value}}` from `"a.b"`."""
    segs = path.split(".")
    out: dict = {}
    cur = out
    for s in segs[:-1]:
        cur[s] = {}
        cur = cur[s]
    cur[segs[-1]] = value
    return out


def hint_of(detect: dict, default: str = "thing") -> str:
    """One resource-type word for a fixture to build.

    `type_hint` is a string OR a list of words, because one control can live on more than one resource
    shape (`executionRoleArn` on a harness, `roleArn` on a gateway). A fixture only needs a type the
    matcher will accept, so it takes the first — but it must not assume the singular form, or every arm
    below silently stops running the day a control gains a second hint.
    """
    raw = detect.get("type_hint") or default
    words = [raw] if isinstance(raw, str) else list(raw)
    return str(words[0] if words else default)


def template_for(control: dict, value=None, values_by_path: dict[str, str] | None = None) -> dict:
    """A CloudFormation template that declares exactly the paths this control detects.

    One resource per path, so two paths sharing a prefix cannot collide while nesting.

    `values_by_path` exists because two controls can read the **same** path — `policy_engine_mode` and
    `enforcement_latency_budget` both read `policyEngineConfiguration.mode`. Generating each control's
    template independently then wrote `LOG_ONLY` in one file and a placeholder in another, and the
    parser correctly reported a disagreement, which made the value unreadable and every downstream arm
    vacuous. The parser was right; the fixture was incoherent. Callers building one submission from
    several controls pass a shared map so the templates agree with each other.
    """
    detect = control["detect"]
    hint = hint_of(detect)
    values = detect.get("values") or []
    default = value if value is not None else (values[0] if values else "SOMETHING")
    resources = {}
    for i, p in enumerate(detect.get("paths") or []):
        val = default if value is not None else (values_by_path or {}).get(p, default)
        resources[f"R{i}"] = {"Type": f"AWS::BedrockAgentCore::{hint.capitalize()}",
                              "Properties": nest(p, val)}
    return {"AWSTemplateFormatVersion": "2010-09-09", "Resources": resources}


def coherent_values(controls: list[dict]) -> dict[str, str]:
    """path → the value every generated template must use for it. A control with an enum wins the
    path, because an enum value is the one a finding can be keyed on."""
    out: dict[str, str] = {}
    for c in controls:
        values = (c.get("detect") or {}).get("values") or []
        if not values:
            continue
        for p in (c.get("detect") or {}).get("paths") or []:
            out.setdefault(p, values[0])
    return out


def observation_for(inventory: dict, control_id: str) -> dict:
    for o in inventory["observations"]:
        if o["control"] == control_id:
            return o
    raise AssertionError(f"{control_id} missing from the inventory entirely")


def run(root: Path, controls: list[dict]) -> dict:
    return parse_iac.build_inventory(root, controls)


# --------------------------------------------------------------------------------- the two controls


def test_every_control_is_detectable_from_its_own_rule(tmp_path, controls):
    """The load-bearing arm: a rule the parser cannot match is a permanent false clean.

    It is not load-bearing ALONE, and the reason is worth stating where the fixture is. `template_for`
    writes a scalar at exactly the authored path and builds the resource type out of the hint, so it
    generates the one template shape guaranteed to match — and it passed while two controls in
    `controls.yaml` could not be matched by any real template on earth: one named a STRUCTURE
    (`targetconfiguration.mcp.lambda`, whose members are what a reader writes), and one carried a
    `role` hint over paths that live on a gateway. Both read NOT_DECLARED for every submission.
    The two arms below close that gap by making the fixture less kind.
    """
    undetected = []
    for c in controls:
        if not (c.get("detect") or {}).get("paths"):
            continue
        sub = tmp_path / c["id"]
        sub.mkdir(parents=True, exist_ok=True)
        write(sub, "template.json", template_for(c))
        obs = observation_for(run(sub, controls), c["id"])
        if obs["observation"] != "DECLARED":
            undetected.append(c["id"])
    assert not undetected, (f"these control(s) declare a detection rule the parser cannot match, so "
                            f"they would read NOT_DECLARED on a template that does declare them: "
                            f"{undetected}")


def test_every_control_is_detectable_when_its_path_names_a_structure(tmp_path, controls):
    """The same sweep, with the scalar one level BELOW the authored path.

    This is what a real template looks like whenever a rule names a structure: nobody writes a value at
    `TargetConfiguration.Mcp.Lambda`, they write `LambdaArn` inside it. `flatten` records only scalars,
    so a suffix-only matcher can never end at the authored path, and the control reports "not seen in
    your files" about a submission that declares it in full.
    """
    undetected = []
    for c in controls:
        paths = (c.get("detect") or {}).get("paths") or []
        if not paths:
            continue
        hint = hint_of(c["detect"])
        resources = {f"R{i}": {"Type": f"AWS::BedrockAgentCore::{hint.capitalize()}",
                               "Properties": nest(f"{p}.someMemberTheRuleDoesNotName", "SOMETHING")}
                     for i, p in enumerate(paths)}
        sub = tmp_path / c["id"]
        sub.mkdir(parents=True, exist_ok=True)
        write(sub, "template.json", {"Resources": resources})
        obs = observation_for(run(sub, controls), c["id"])
        if obs["observation"] != "DECLARED":
            undetected.append(c["id"])
    assert not undetected, (f"these control(s) name a path a real template can only declare by writing "
                            f"a member inside it, and the parser did not see it: {undetected}")


def test_every_hint_word_matches_not_only_the_first(tmp_path, controls):
    """A control can live on several resource shapes, and each one must be reachable.

    `executionRoleArn` is a harness member and `roleArn` a gateway member. A matcher honouring only the
    first word in `type_hint` excludes the other shape silently — the exclusion is invisible precisely
    because NOT_DECLARED is a legitimate answer that names no rule.
    """
    multi = [c for c in controls if isinstance((c["detect"] or {}).get("type_hint"), list)
             and len(c["detect"]["type_hint"]) > 1]
    assert multi, "no control carries more than one type hint, so this arm would be vacuous"
    for c in multi:
        for word in c["detect"]["type_hint"]:
            sub = tmp_path / f"{c['id']}-{word}"
            sub.mkdir(parents=True, exist_ok=True)
            resources = {f"R{i}": {"Type": f"AWS::BedrockAgentCore::{str(word).capitalize()}",
                                   "Properties": nest(p, "SOMETHING")}
                         for i, p in enumerate(c["detect"]["paths"])}
            write(sub, "t.json", {"Resources": resources})
            obs = observation_for(run(sub, controls), c["id"])
            assert obs["observation"] == "DECLARED", (
                f"{c['id']} names the hint {word!r} but a resource of that shape declaring its paths "
                f"was reported NOT_DECLARED")


def test_an_unrelated_repo_declares_nothing(tmp_path, controls):
    """The negative control. Without it the arm above would pass on a parser that says DECLARED always."""
    write(tmp_path, "package.json", {"name": "app", "dependencies": {"react": "19"}})
    write(tmp_path, "cdk.out/tree.json", {"version": "tree-0.1", "tree": {"id": "App"}})
    inv = run(tmp_path, controls)
    assert all(o["observation"] == "NOT_DECLARED" for o in inv["observations"])
    assert inv["submission"]["resources_found"] == 0


# --------------------------------------------------------------------------------- values


def test_the_declared_value_is_reported(tmp_path, controls):
    c = next(c for c in controls if (c["detect"].get("values") or []))
    want = c["detect"]["values"][0]
    write(tmp_path, "t.json", template_for(c, value=want))
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["value"] == want
    assert obs["values_seen"] == [want]


def test_two_resources_in_different_modes_are_not_collapsed(tmp_path, controls):
    """A repo with one ENFORCE and one LOG_ONLY gateway must not be reported as either.

    Collapsing to the first value read is how a report tells someone their fleet is enforcing when one
    gateway is not. The disagreement is the finding.
    """
    c = next(c for c in controls if len(c["detect"].get("values") or []) >= 2)
    a, b = c["detect"]["values"][0], c["detect"]["values"][1]
    write(tmp_path, "a.json", template_for(c, value=a))
    write(tmp_path, "b.json", template_for(c, value=b))
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "DECLARED"
    assert obs["value"] is None, "one value must not be chosen when the templates disagree"
    assert sorted(obs["disagreement"]) == sorted([a, b])


def test_a_value_outside_the_declared_enum_is_flagged(tmp_path, controls):
    c = next(c for c in controls if (c["detect"].get("values") or []))
    write(tmp_path, "t.json", template_for(c, value="MODE_FROM_THE_FUTURE"))
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["values_outside_the_declared_enum"] == ["MODE_FROM_THE_FUTURE"]


def test_a_ref_is_recorded_unresolved_not_as_a_value(tmp_path, controls):
    """`!Ref EngineMode` is not a mode. Resolving it would invent a value the template lacks."""
    c = next(c for c in controls if (c["detect"].get("values") or []))
    path = c["detect"]["value_from"] or c["detect"]["paths"][0]
    hint = hint_of(c["detect"])
    body = nest(path, None)

    # Written as YAML so the short tag is exercised as CloudFormation actually writes it.
    text = yaml.safe_dump({"Resources": {"R": {"Type": f"AWS::BedrockAgentCore::{hint.capitalize()}",
                                               "Properties": body}}})
    text = text.replace("null", "!Ref EngineMode")
    (tmp_path / "t.yaml").write_text(text, encoding="utf-8")

    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "DECLARED", "the property IS declared; only its value is unknown"
    assert obs["value"] is None
    assert obs["values_seen"] == []
    assert obs["unresolved"] and obs["unresolved"][0]["unresolved_tag"] == "Ref"


# --------------------------------------------------------------------------------- matching rigour


def test_a_path_is_a_suffix_not_a_substring(tmp_path, controls):
    """`mode` must not match `crossRegionMode`. A substring test would make every report noise."""
    c = next(c for c in controls if (c["detect"].get("values") or []))
    leaf = (c["detect"]["paths"][0]).split(".")[-1]
    hint = hint_of(c["detect"])
    write(tmp_path, "t.json", {"Resources": {"R": {
        "Type": f"AWS::BedrockAgentCore::{hint.capitalize()}",
        "Properties": {f"crossRegion{leaf.capitalize()}": "ENFORCE",
                       f"{leaf}Override": "ENFORCE"}}}})
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "NOT_DECLARED", f"{obs['sites']}"


def test_the_type_hint_excludes_the_wrong_resource(tmp_path, controls):
    """A property of the right name on an unrelated resource type is not this control."""
    c = next(c for c in controls if (c["detect"].get("type_hint")))
    write(tmp_path, "t.json", {"Resources": {"R": {
        "Type": "AWS::SQS::Queue", "Properties": nest(c["detect"]["paths"][0], "ENFORCE")}}})
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "NOT_DECLARED"


def test_a_nested_property_under_a_cdk_wrapper_still_matches(tmp_path, controls):
    """CDK synth nests; suffix matching is what makes an authored path survive that."""
    c = next(c for c in controls if (c["detect"].get("values") or []))
    hint = hint_of(c["detect"])
    deep = {"Configuration": {"Nested": nest(c["detect"]["paths"][0], c["detect"]["values"][0])}}
    write(tmp_path, "cdk.out/Stack.template.json", {"Resources": {"R": {
        "Type": f"AWS::BedrockAgentCore::{hint.capitalize()}", "Properties": deep}}})
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "DECLARED"
    assert obs["value"] == c["detect"]["values"][0]


def test_snake_case_terraform_attributes_match_camel_case_rules(tmp_path, controls):
    """Without segment normalisation a Terraform plan matches nothing — a silent false clean."""
    c = next(c for c in controls if (c["detect"].get("values") or []))
    path = c["detect"]["value_from"] or c["detect"]["paths"][0]
    snake = ".".join(_snake(s) for s in path.split("."))
    plan = {"planned_values": {"root_module": {"child_modules": [{"resources": [{
        "address": "module.gw.aws_thing", "type": f"aws_{hint_of(c['detect'])}",
        "values": nest(snake, c["detect"]["values"][0])}]}]}}}
    write(tmp_path, "plan.json", plan)
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "DECLARED", f"looked for {snake}"
    assert obs["sites"][0]["source_kind"] == "terraform_plan"


def _snake(seg: str) -> str:
    """`policyengineconfiguration` → `policy_engine_configuration` is not recoverable; insert
    separators crudely so the normaliser has something to strip."""
    return "_".join([seg[:3], seg[3:]]) if len(seg) > 4 else seg


def test_a_repeated_list_field_reports_every_occurrence(tmp_path, controls):
    """A guardrail with four filters has four sites; reporting one hides three."""
    c = next(c for c in controls if (c["detect"].get("values") or []))
    path = c["detect"]["paths"][0]
    hint = hint_of(c["detect"])
    if "." not in path:
        pytest.skip("this control's rule has no nestable path to place in a list")
    head, leaf = path.rsplit(".", 1)
    write(tmp_path, "t.json", {"Resources": {"R": {
        "Type": f"AWS::BedrockAgentCore::{hint.capitalize()}",
        "Properties": nest(head, [{leaf: v} for v in ("A", "B", "C")])}}})
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert len(obs["sites"]) == 3
    assert obs["values_seen"] == ["A", "B", "C"] or obs["value"] is None


# --------------------------------------------------------------------------------- line numbers


def test_the_reported_line_is_the_real_line(tmp_path, controls):
    """A citation a reader cannot walk to is not a citation."""
    c = next(c for c in controls if (c["detect"].get("values") or []))
    path = c["detect"]["value_from"] or c["detect"]["paths"][0]
    hint = hint_of(c["detect"])
    lines = ["Resources:", "  R:", f"    Type: AWS::BedrockAgentCore::{hint.capitalize()}",
             "    Properties:"]
    indent = 6
    for seg in path.split(".")[:-1]:
        lines.append(" " * indent + f"{seg}:")
        indent += 2
    lines.append(" " * indent + f"{path.split('.')[-1]}: {c['detect']['values'][0]}")
    expected_line = len(lines)
    (tmp_path / "t.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "DECLARED"
    assert obs["sites"][0]["line"] == expected_line, f"reported {obs['sites'][0]}"
    assert obs["sites"][0]["file"] == "t.yaml"


# --------------------------------------------------------------------------------- caveats


def test_hcl_only_submission_says_so_rather_than_reading_clean(tmp_path, controls):
    (tmp_path / "main.tf").write_text('resource "aws_thing" "g" { mode = "LOG_ONLY" }\n',
                                      encoding="utf-8")
    inv = run(tmp_path, controls)
    assert inv["submission"]["hcl_files_not_parsed"] == 1
    joined = " ".join(inv["caveats"])
    assert "HCL" in joined and "terraform show -json" in joined
    assert "ZERO resources" in joined, "an HCL-only repo parsed nothing; that must be stated too"


def test_zero_resources_is_reported_as_not_a_clean_result(tmp_path, controls):
    write(tmp_path, "readme.json", {"hello": "world"})
    inv = run(tmp_path, controls)
    assert any("ZERO resources" in c and "not a clean result" in c for c in inv["caveats"])


def test_a_truncated_scan_marks_itself_incomplete(tmp_path, controls, monkeypatch):
    monkeypatch.setattr(parse_iac, "MAX_TOTAL_BYTES", 10)
    c = next(c for c in controls if (c["detect"].get("values") or []))
    write(tmp_path, "a.json", template_for(c))
    write(tmp_path, "b.json", template_for(c))
    inv = run(tmp_path, controls)
    assert inv["submission"]["complete"] is False
    assert any("INCOMPLETE" in x and "not seen" in x for x in inv["caveats"])


def test_a_file_over_the_ceiling_is_named_in_skipped(tmp_path, controls, monkeypatch):
    monkeypatch.setattr(parse_iac, "MAX_FILE_BYTES", 5)
    c = next(c for c in controls if (c["detect"].get("values") or []))
    write(tmp_path, "big.json", template_for(c))
    inv = run(tmp_path, controls)
    assert [s for s in inv["submission"]["skipped"] if "ceiling" in s["why"]]


def test_the_file_count_ceiling_is_reported_not_silent(tmp_path, controls, monkeypatch):
    monkeypatch.setattr(parse_iac, "MAX_FILES_CONSIDERED", 2)
    c = next(c for c in controls if (c["detect"].get("values") or []))
    for i in range(6):
        write(tmp_path, f"t{i}.json", template_for(c))
    inv = run(tmp_path, controls)
    assert inv["submission"]["complete"] is False
    assert any("NOT_DECLARED results mean 'not seen'" in x for x in inv["caveats"])


# --------------------------------------------------------------------------------- hostile input


def test_a_symlink_is_not_followed(tmp_path, controls):
    """A submitted repo can link anywhere on the machine reading it."""
    secret = tmp_path.parent / "outside.json"
    secret.write_text(json.dumps({"Resources": {}}), encoding="utf-8")
    (tmp_path / "link.json").symlink_to(secret)
    inv = run(tmp_path, controls)
    assert [s for s in inv["submission"]["skipped"] if "symlink" in s["why"]]
    assert inv["submission"]["bytes_read"] == 0


def test_a_python_object_tag_is_data_not_an_instruction(tmp_path, controls):
    """Composing must never construct. `safe_load` would raise; `unsafe_load` would execute."""
    (tmp_path / "t.yaml").write_text(
        "Resources:\n  R:\n    Type: !!python/object/apply:os.system ['touch /tmp/grx-pwned']\n",
        encoding="utf-8")
    inv = run(tmp_path, controls)
    assert not Path("/tmp/grx-pwned").exists(), "the parser executed a submitted tag"
    assert inv["submission"]["resources_found"] == 0


def test_nesting_deeper_than_the_ceiling_is_skipped_with_a_reason(tmp_path, controls):
    deep: dict = {"Resources": {"R": {"Type": "AWS::BedrockAgentCore::Gateway"}}}
    cur = deep["Resources"]["R"]["Properties"] = {}
    for i in range(parse_iac.MAX_DEPTH + 5):
        cur["n"] = {}
        cur = cur["n"]
    write(tmp_path, "t.json", deep)
    inv = run(tmp_path, controls)
    assert [s for s in inv["submission"]["skipped"] if "nesting deeper" in s["why"]]


def test_a_yaml_syntax_error_is_a_named_skip_not_a_crash(tmp_path, controls):
    (tmp_path / "t.yaml").write_text("Resources:\n  R: [unclosed\n", encoding="utf-8")
    inv = run(tmp_path, controls)
    assert [s for s in inv["submission"]["skipped"] if "not parseable" in s["why"]]


def test_a_non_utf8_file_is_a_named_skip(tmp_path, controls):
    (tmp_path / "t.json").write_bytes(b'{"Resources": "\xff\xfe bad"}')
    inv = run(tmp_path, controls)
    assert [s for s in inv["submission"]["skipped"] if "UTF-8" in s["why"]]


def test_node_modules_is_skipped_but_cdk_out_is_not(tmp_path, controls):
    """`cdk.out` holds synth output — the most valuable directory in a CDK submission."""
    c = next(c for c in controls if (c["detect"].get("values") or []))
    write(tmp_path, "node_modules/pkg/t.json", template_for(c))
    inv = run(tmp_path, controls)
    assert observation_for(inv, c["id"])["observation"] == "NOT_DECLARED"

    write(tmp_path, "cdk.out/Stack.template.json", template_for(c))
    inv = run(tmp_path, controls)
    assert observation_for(inv, c["id"])["observation"] == "DECLARED"


def test_multi_document_yaml_reads_past_the_first_document(tmp_path, controls):
    c = next(c for c in controls if (c["detect"].get("values") or []))
    hint = hint_of(c["detect"])
    doc1 = yaml.safe_dump({"Resources": {"A": {"Type": "AWS::SQS::Queue"}}})
    doc2 = yaml.safe_dump({"Resources": {"B": {
        "Type": f"AWS::BedrockAgentCore::{hint.capitalize()}",
        "Properties": nest(c["detect"]["paths"][0], c["detect"]["values"][0])}}})
    (tmp_path / "t.yaml").write_text(doc1 + "---\n" + doc2, encoding="utf-8")
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "DECLARED", "only the first YAML document was read"


# --------------------------------------------------------------------------------- terraform


def test_a_terraform_child_module_is_walked(tmp_path, controls):
    """A gateway inside a module must not read NOT_DECLARED."""
    c = next(c for c in controls if (c["detect"].get("values") or []))
    path = c["detect"]["value_from"] or c["detect"]["paths"][0]
    plan = {"planned_values": {"root_module": {"child_modules": [{"child_modules": [{"resources": [{
        "address": "module.a.module.b.aws_gw", "type": f"aws_{hint_of(c['detect'])}",
        "values": nest(path, c["detect"]["values"][0])}]}]}]}}}
    write(tmp_path, "plan.json", plan)
    obs = observation_for(run(tmp_path, controls), c["id"])
    assert obs["observation"] == "DECLARED"
    assert obs["sites"][0]["resource"] == "module.a.module.b.aws_gw"


# --------------------------------------------------------------------------------- the CLI


def test_the_cli_refuses_a_controls_file_with_no_controls(tmp_path, controls):
    empty = tmp_path / "empty.yaml"
    empty.write_text("schema: grx-controls/1\ncontrols: []\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        parse_iac.main(["--submission", str(tmp_path), "--controls", str(empty)])
    assert e.value.code == 2


def test_the_cli_writes_a_stable_inventory(tmp_path, controls):
    c = next(c for c in controls if (c["detect"].get("values") or []))
    sub = tmp_path / "sub"
    sub.mkdir()
    write(sub, "t.json", template_for(c))
    out = tmp_path / "inv" / "inventory.json"
    assert parse_iac.main(["--submission", str(sub), "--out", str(out)]) == 0
    first = out.read_text(encoding="utf-8")
    assert parse_iac.main(["--submission", str(sub), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == first, "the same submission must parse identically"
    assert json.loads(first)["schema"] == "grx-inventory/1"


def test_the_submission_root_must_be_a_directory(tmp_path):
    with pytest.raises(SystemExit) as e:
        parse_iac.build_inventory(tmp_path / "nope", [{"id": "x", "detect": {}}])
    assert e.value.code == 2
