#!/usr/bin/env python3
"""Arms for the audit report. Most of them defend one sentence: the report may not say something the
study did not measure.

The governance rules this file makes mechanical, each with the arm that would catch its violation:

- **No pass rate, score or grade, anywhere in the rendered document.** A ratio over 46 TRUE / 23 FALSE
  / 20 INCONCLUSIVE / 2 RECORDED would treat "measured and the guidance did not hold" as the same kind
  of miss as "nothing was established", and would score a control never examined as a pass.
- **An INCONCLUSIVE verdict licenses no recommendation.** The same rule that governs the study's own
  document amendments, applied to the reader's report.
- **A case the citation policy marks NEVER_CITE can never be a recommendation's support.**
- **Every authored finding reaches the reader.** The first version of the report matched one finding per
  control and silently dropped the rest; five of fourteen recommendations went missing and nothing
  failed. That arm is `test_no_authored_finding_is_dropped`, and it is the reason this file exists in
  the shape it does.
- **NOT_DECLARED never reads as absent, and an unmapped value never reads as a pass.**

Mutants deep-copy the real `controls.yaml` and change one thing, for the reason
`test_check_controls.py` gives: a hand-built fixture drifts from the file it stands for, and then the
arms test a document nobody publishes. Restricted and INCONCLUSIVE cases are looked up from the
artifacts at test time, never typed.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve()
AUDIT = HERE.parent.parent
REPO = AUDIT.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(AUDIT))
sys.path.insert(0, str(REPO / "platform" / "build"))

import check_controls  # noqa: E402
import parse_iac  # noqa: E402
import report as report_mod  # noqa: E402
from test_parse_iac import coherent_values, nest, template_for, write  # noqa: E402

CONTROLS_YAML = REPO / "platform" / "curation" / "controls.yaml"


# --------------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def controls() -> list[dict]:
    got = (check_controls.load_yaml_no_duplicate_keys(CONTROLS_YAML) or {}).get("controls") or []
    assert len(got) >= check_controls.MIN_CONTROLS
    return got


@pytest.fixture(scope="module")
def verdicts() -> dict[str, str]:
    _ids, v = check_controls.read_verdicts()
    assert len(v) >= 80, "the real verdicts are the fixture"
    return v


@pytest.fixture(scope="module")
def restrictions() -> dict[str, set[str]]:
    return check_controls.read_restrictions()


def a_case_with(verdicts: dict[str, str], verdict: str) -> str:
    got = sorted(c for c, v in verdicts.items() if v == verdict)
    assert got, f"no case on disk has verdict {verdict}; this arm would be vacuous"
    return got[0]


def a_case_restricted(restrictions: dict[str, set[str]], restriction: str) -> str:
    got = sorted(c for c, rs in restrictions.items() if restriction in rs)
    assert got, f"no case carries {restriction}; this arm would be vacuous"
    return got[0]


def submission_declaring_everything(root: Path, controls: list[dict]) -> Path:
    """One template per control, so a single report exercises every detection rule at once."""
    sub = root / "repo"
    sub.mkdir(parents=True, exist_ok=True)
    shared = coherent_values(controls)
    for c in controls:
        if (c.get("detect") or {}).get("paths"):
            write(sub, f"{c['id']}.template.json", template_for(c, values_by_path=shared))
    return sub


def build(root: Path, controls: list[dict], as_of: str | None = "2026-08-20") -> dict:
    sub = submission_declaring_everything(root, controls)
    inv = parse_iac.build_inventory(sub, controls)
    return report_mod.build(inv, controls, as_of)


def dump(tmp_path: Path, controls: list[dict]) -> Path:
    """A controls.yaml on disk holding a mutated control list, for the CLI-level arms."""
    p = tmp_path / "controls.yaml"
    p.write_text(yaml.safe_dump({"schema": "grx-controls/1", "controls": controls},
                                sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


def applicable(mutant: list[dict]) -> tuple[dict, dict]:
    """A (control, finding) pair the generated submission actually triggers.

    `submission_declaring_everything` builds each template from `detect.values[0]`, and
    `match_findings` prefers value-keyed findings over observation-keyed ones. So mutating "the first
    finding with a consequence" can land on a finding the submission never reaches — the mutant then
    changes nothing, the arm passes, and it has tested nothing (`feedback_probe_must_reach_the_code`).
    This picks a pair that is reachable by construction.
    """
    for c in mutant:
        det = c.get("detect") or {}
        if not det.get("paths") or c.get("measured") == "none":
            continue
        values = det.get("values") or []
        for f in c["findings"]:
            when = f.get("when") or {}
            if not f.get("consequence"):
                continue
            if values and str(when.get("value")) == str(values[0]):
                return c, f
            if not values and when.get("observation") == "DECLARED":
                return c, f
    raise AssertionError("no reachable finding carries a consequence; every mutation arm below "
                         "would be vacuous")


# --------------------------------------------------------------------------------- controls


def test_the_real_artifacts_produce_a_report(tmp_path, controls):
    r = build(tmp_path, controls)
    assert r["schema"] == "grx-audit-report/1"
    assert len(r["controls"]) == len(controls)
    assert r["recommendations"], "a submission declaring every control must yield recommendations, " \
                                "or every arm below about recommendations is vacuous"


def test_the_verdict_mix_is_derived_not_typed(tmp_path, controls, verdicts):
    r = build(tmp_path, controls)
    mix = r["study"]["verdict_mix"]
    assert sum(mix.values()) == len(verdicts)
    assert set(mix) <= {"TRUE", "FALSE", "INCONCLUSIVE", "RECORDED"}, mix
    assert mix == {v: sum(1 for x in verdicts.values() if x == v) for v in sorted(set(verdicts.values()))}


def test_the_same_submission_produces_a_byte_identical_report(tmp_path, controls):
    """A report that changes when nothing changed cannot be diffed, so it cannot be trusted."""
    first = build(tmp_path / "a", controls)
    second = build(tmp_path / "b", controls)
    # The submission root differs between the two temp dirs, so compare everything that is not a path.
    for doc in (first, second):
        doc["inventory"]["submission"] = None
        doc["inventory"]["resources"] = None
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert report_mod.markdown(first) == report_mod.markdown(second)


def test_evidence_through_is_derived_from_the_artifacts(tmp_path, controls):
    r = build(tmp_path, controls)
    got = r["evidence_through_at_least"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", got or ""), got
    assert got == r["evidence_through_at_least"]
    assert r["as_of"] == "2026-08-20", "the run date arrives as an argument, never from a clock"


# --------------------------------------------------------------------------------- no score, ever


# Patterns for a *ratio or grade over the reader's controls* — not for individual words. The first
# draft banned "score", "scored" and "passing" outright and fired three times on legitimate
# measurement prose: "the text volume passing through it", "reported above, not scored", and "a
# numeric guardrail score" (`grounding score` is a real Bedrock Guardrails field). A check that fires
# on correct output gets weakened or deleted, so it is narrowed to the thing that is actually
# forbidden.
BANNED = [
    r"\d+\s*%",
    r"\bpass rate\b", r"\bfail(ure)? rate\b", r"\bpass/fail\b",
    r"\b(compliance|security|risk|audit|overall)\s+(score|grade|rating)\b",
    r"\bgrade[ds]?\b", r"\bscored?\s+\d", r"\bcontrols?\s+passed\b",
    r"\b\d+\s*/\s*\d+\s+(pass|controls|checks|compliant)\b",
]


def test_the_rendered_report_contains_no_ratio_or_grade(tmp_path, controls):
    md = report_mod.markdown(build(tmp_path, controls))
    # The prose explaining *why* there is no pass rate necessarily contains the phrase, so the check
    # runs over the document with that one sentence removed rather than being weakened for it.
    body = md.replace("There is no pass rate in this report.", "")
    hits = {p: re.findall(p, body, flags=re.I) for p in BANNED}
    hits = {p: v for p, v in hits.items() if v}
    assert not hits, f"the report renders a score or ratio: {hits}"


def test_the_banned_pattern_list_can_actually_fire(tmp_path, controls):
    """The negative control for the arm above: without it, a broken regex list passes forever."""
    md = report_mod.markdown(build(tmp_path, controls)) + "\n\nOverall score: 75% passing.\n"
    assert any(re.findall(p, md, flags=re.I) for p in BANNED)


def test_the_headline_is_a_denominator_statement(tmp_path, controls):
    h = build(tmp_path, controls)["headline"]
    assert "%" not in h["statement"]
    assert not [k for k in h if re.search(r"rate|score|grade|percent", k, re.I)], sorted(h)
    assert h["controls_the_study_covers"] == len(controls)
    assert h["controls_you_declare"] <= h["controls_the_study_covers"]


# --------------------------------------------------------------------------------- citation legality


def test_an_inconclusive_verdict_licenses_no_recommendation(tmp_path, controls, verdicts):
    """The rule that governs this study's own amendments, applied to the reader's report."""
    case = a_case_with(verdicts, "INCONCLUSIVE")
    mutant = copy.deepcopy(controls)
    target, finding = applicable(mutant)
    finding["status"] = "not_established"
    finding["cites"] = [case]

    r = build(tmp_path, mutant)
    # Checked by the injected case rather than by control: `policy_engine_mode` authors two findings
    # under `when: {value: LOG_ONLY}`, so its *other* finding legitimately still recommends something.
    # Asserting "no recommendation for this control" would fail on correct behaviour.
    assert not [x for x in r["recommendations"]
                if any(l["case"] == case for l in x["licensed_by"])], \
        "an INCONCLUSIVE verdict reached the recommendations section"
    withheld = [w for w in r["recommendations_withheld"] if w["control"] == target["id"]]
    assert withheld and "licenses no recommendation" in withheld[0]["why_withheld"]


def test_a_never_cite_case_cannot_license_a_recommendation(tmp_path, controls, restrictions):
    case = a_case_restricted(restrictions, "NEVER_CITE")
    mutant = copy.deepcopy(controls)
    target, finding = applicable(mutant)
    finding["cites"] = [case]

    r = build(tmp_path, mutant)
    assert not [x for x in r["recommendations"]
                if any(l["case"] == case for l in x["licensed_by"])], \
        f"{case} carries NEVER_CITE and licensed a recommendation anyway"
    assert [w for w in r["recommendations_withheld"] if w["control"] == target["id"]]


def test_every_recommendation_on_the_real_file_rests_on_a_true_or_false_verdict(tmp_path, controls,
                                                                               restrictions):
    r = build(tmp_path, controls)
    for rec in r["recommendations"]:
        assert rec["licensed_by"], rec["control"]
        for lic in rec["licensed_by"]:
            assert lic["verdict"] in ("TRUE", "FALSE"), rec
            assert "NEVER_CITE" not in restrictions.get(lic["case"], set()), rec


def test_a_withheld_recommendation_is_printed_rather_than_dropped(tmp_path, controls, verdicts):
    case = a_case_with(verdicts, "INCONCLUSIVE")
    mutant = copy.deepcopy(controls)
    target, finding = applicable(mutant)
    finding["status"] = "not_established"
    finding["cites"] = [case]

    r = build(tmp_path, mutant)
    md = report_mod.markdown(r)
    assert "recommendation(s) withheld" in md
    assert f"`{target['id']}`" in md, "a withheld recommendation must name its control"


def test_an_unregistered_case_is_a_hard_failure(tmp_path, controls):
    mutant = copy.deepcopy(controls)
    _target, finding = applicable(mutant)
    finding["cites"] = ["F99-1"]
    with pytest.raises(SystemExit) as e:
        build(tmp_path, mutant)
    assert e.value.code == 2


# --------------------------------------------------------------------------------- completeness


def test_no_authored_finding_is_dropped(tmp_path, controls):
    """Four controls author two findings under one `when`. A first-match lookup lost five
    recommendations and nothing failed, which is why this arm counts rather than samples."""
    sub = submission_declaring_everything(tmp_path, controls)
    inv = parse_iac.build_inventory(sub, controls)
    r = report_mod.build(inv, controls, None)

    by_id = {c["id"]: c for c in controls}
    for line in r["controls"]:
        control = by_id[line["control"]]
        expected, _why = report_mod.match_findings(
            control, next(o for o in inv["observations"] if o["control"] == line["control"]))
        assert len(line["measurements"]) == len(expected), (
            f"{line['control']}: {len(expected)} authored finding(s) apply but "
            f"{len(line['measurements'])} were rendered")

    # And the shape that produced the bug must exist, or the arm above proves nothing.
    doubled = [c["id"] for c in controls
               if len({json.dumps(f.get("when"), sort_keys=True) for f in c["findings"]})
               < len(c["findings"])]
    assert doubled, "no control authors two findings under one `when`; this arm is vacuous"


def test_every_rendered_case_appears_in_the_markdown(tmp_path, controls):
    r = build(tmp_path, controls)
    md = report_mod.markdown(r)
    for line in r["controls"]:
        for m in line["measurements"]:
            for c in m["cases"]:
                assert f"**{c['case']} — {c['verdict']}**" in md, c


def test_a_control_missing_from_the_inventory_is_a_hard_failure(tmp_path, controls):
    """A stale inventory silently under-reports coverage, which reads as better coverage."""
    sub = submission_declaring_everything(tmp_path, controls)
    inv = parse_iac.build_inventory(sub, controls)
    inv["observations"] = inv["observations"][1:]
    with pytest.raises(SystemExit) as e:
        report_mod.build(inv, controls, None)
    assert e.value.code == 2


# --------------------------------------------------------------------------------- the five states


def test_not_measured_is_rendered_as_its_own_state(tmp_path, controls):
    """Two controls are genuinely unmeasured. An audit tool that cannot say so lets 'no finding'
    cover both 'we looked and it was fine' and 'we never looked'."""
    unmeasured = [c["id"] for c in controls if c.get("measured") == "none"]
    assert unmeasured, "no control is declared unmeasured; this arm is vacuous"
    r = build(tmp_path, controls)
    md = report_mod.markdown(r)
    assert "NOT MEASURED — this study never examined this control" in md
    for cid in unmeasured:
        line = next(l for l in r["controls"] if l["control"] == cid)
        assert line["statuses"] == ["not_measured"]
        assert not [x for x in r["recommendations"] if x["control"] == cid], \
            "an unmeasured control cannot yield a recommendation"


def test_a_value_no_measurement_covers_is_not_a_pass(tmp_path, controls):
    target = next(c for c in controls
                  if (c["detect"].get("values") or []) and c.get("measured") != "none"
                  and any("value" in (f.get("when") or {}) for f in c["findings"]))
    sub = tmp_path / "repo"
    sub.mkdir(parents=True)
    write(sub, "t.template.json", template_for(target, value="A_STATE_FROM_THE_FUTURE"))
    inv = parse_iac.build_inventory(sub, controls)
    r = report_mod.build(inv, controls, None)
    line = next(l for l in r["controls"] if l["control"] == target["id"])
    assert line["observation"] == "DECLARED"
    assert line["statuses"] == []
    assert "no measurement mapped to that value" in line["why_this_status"]
    md = report_mod.markdown(r)
    assert "NO MEASUREMENT MAPPED TO THIS STATE" in md
    assert "gap in this study's coverage, not a finding about your configuration" in md


def test_not_declared_never_reads_as_absent(tmp_path, controls):
    sub = tmp_path / "empty"
    sub.mkdir()
    write(sub, "readme.json", {"hello": 1})
    inv = parse_iac.build_inventory(sub, controls)
    md = report_mod.markdown(report_mod.build(inv, controls, None))
    assert "not evidence that the control is absent from your system" in md.lower()
    assert "ZERO resources" in md, "the inventory's own caveat must be carried into the report"


def test_a_disagreement_between_templates_attaches_no_measurement(tmp_path, controls):
    """Two gateways in different modes: neither measurement applies to 'the submission'."""
    target = next(c for c in controls if len(c["detect"].get("values") or []) >= 2
                  and c.get("measured") != "none")
    sub = tmp_path / "repo"
    sub.mkdir(parents=True)
    write(sub, "a.template.json", template_for(target, value=target["detect"]["values"][0]))
    write(sub, "b.template.json", template_for(target, value=target["detect"]["values"][1]))
    inv = parse_iac.build_inventory(sub, controls)
    r = report_mod.build(inv, controls, None)
    line = next(l for l in r["controls"] if l["control"] == target["id"])
    if not any("value" in (f.get("when") or {}) for f in target["findings"]):
        pytest.skip("this control's findings key on the observation, not the value")
    assert line["statuses"] == []
    assert "more than one value" in line["why_this_status"]


# --------------------------------------------------------------------------------- verdict limits


def test_a_case_with_no_stated_limits_says_so(tmp_path, controls):
    """39 of 91 cases state nothing about what their verdict does not prove. Silence there would read
    as 'no limits', which is the opposite of the truth."""
    caveats = report_mod.read_case_caveats()
    silent = {c for c, v in caveats.items() if not v["present"]}
    assert silent, "every case states its limits; this arm is vacuous"
    md = report_mod.markdown(build(tmp_path, controls))
    r = build(tmp_path, controls)
    cited_silent = {c["case"] for l in r["controls"] for m in l["measurements"] for c in m["cases"]
                    if c["case"] in silent}
    assert cited_silent, "no silent case is cited by any control; this arm is vacuous"
    assert "records no statement of what its verdict does not prove" in md


def test_a_case_with_stated_limits_shows_them(tmp_path, controls):
    r = build(tmp_path, controls)
    md = report_mod.markdown(r)
    stated = [c for l in r["controls"] for m in l["measurements"] for c in m["cases"]
              if c["limits_stated_by_the_case"]]
    assert stated, "no cited case states its limits; this arm is vacuous"
    assert "Limits of that verdict, from the case file:" in md
    snippet = stated[0]["what_this_verdict_does_not_prove"][:60]
    assert snippet in md


def test_the_caveat_counts_the_cases_that_state_no_limits(tmp_path, controls):
    r = build(tmp_path, controls)
    caveats = report_mod.read_case_caveats()
    n_with = sum(1 for c in caveats.values() if c["present"])
    joined = " ".join(r["caveats"])
    assert f"{n_with} of {len(caveats)} published case(s) state" in joined
    assert f"The remaining {len(caveats) - n_with} do not" in joined


def test_a_scope_bound_measurement_carries_its_scope_into_the_recommendation(tmp_path, controls):
    r = build(tmp_path, controls)
    scoped = [x for x in r["recommendations"] if x.get("scope_note")]
    assert scoped, "no recommendation is scope-bound; F6's position-bound verdicts should be"
    md = report_mod.markdown(r)
    assert "Only within this scope:" in md


# --------------------------------------------------------------------------------- the CLI


def test_the_cli_refuses_an_unknown_inventory_schema(tmp_path, controls):
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps({"schema": "something-else/9", "observations": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        report_mod.main(["--inventory", str(inv)])
    assert e.value.code == 2


def test_the_cli_refuses_a_controls_file_with_no_controls(tmp_path, controls):
    sub = submission_declaring_everything(tmp_path, controls)
    inv_path = tmp_path / "inv.json"
    inv = parse_iac.build_inventory(sub, controls)
    inv_path.write_text(json.dumps(inv), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        report_mod.main(["--inventory", str(inv_path), "--controls", str(dump(tmp_path, []))])
    assert e.value.code == 2


def test_the_cli_writes_both_documents(tmp_path, controls):
    sub = submission_declaring_everything(tmp_path, controls)
    inv_path = tmp_path / "inv.json"
    inv_path.write_text(json.dumps(parse_iac.build_inventory(sub, controls)), encoding="utf-8")
    md, js = tmp_path / "r.md", tmp_path / "r.json"
    assert report_mod.main(["--inventory", str(inv_path), "--as-of", "2026-08-20",
                           "--out-md", str(md), "--out-json", str(js)]) == 0
    assert md.read_text(encoding="utf-8").startswith("# AgentCore security-design audit")
    assert json.loads(js.read_text(encoding="utf-8"))["as_of"] == "2026-08-20"


def test_a_caveat_field_of_any_shape_renders(tmp_path):
    """Case files spell their limits as a string, a list or a dict; none may crash the renderer."""
    assert report_mod.as_text("a  b") == "a b"
    assert report_mod.as_text(["a", "b"]) == "a b"
    assert report_mod.as_text({"b": "2", "a": "1"}) == "a: 1 b: 2"
    assert report_mod.as_text("x" * 900).endswith("…")
    assert len(report_mod.as_text("x" * 900)) == 700
