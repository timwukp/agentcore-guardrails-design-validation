"""Mutation coverage for `check_architecture.py`, one arm per rule it claims to enforce.

WHY EVERY RULE NEEDS AN ARM

The gate exits 0 against the real `architecture.yaml`. That result is worth exactly nothing on its own:
a gate whose every rule is unreachable exits 0 too, and from outside the two are the same observation
(`feedback_vacuous_test_check`). So each rule gets a mutant that ought to trip it, and every arm asserts
the exit code **and** a fragment of the message — a rule that fires for the wrong reason will pass the
wrong file later, and the rc alone cannot tell the two apart.

HOW THE MUTANTS ARE BUILT

The real file is loaded, one thing is changed in the loaded structure, and the result is dumped to a
temporary file the gate is pointed at. Mutating the real structure rather than a hand-built fixture is
deliberate: a fixture drifts from the document it stands for, and then these arms certify a diagram
nobody publishes. The register, the verdict files and the citation policy are the repository's real ones
throughout, because they are what the legality rules derive from.

No case id is typed into this file, for the same reason none is typed into the gate. Which cases are
non-citable is stated by `results/CITATION-POLICY.md`; an arm with `F5-3b` in it would go vacuous the day
the policy moved that restriction, and would meanwhile be testing a rule the policy no longer states
(`feedback_scope_as_namelist`).

WHY THE ARMS ASSERT rc == 2 AND NEVER rc == 1

Both paths out of the gate — a finding and an unusable input — exit 2. 1 is what a Python traceback
exits with, so an arm accepting 1 would accept a crash as a detection.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import check_architecture as ca  # noqa: E402
import check_controls as cc  # noqa: E402

yaml = pytest.importorskip("yaml", reason="the gate itself refuses to run without PyYAML")


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def real() -> dict:
    return cc.load_yaml_no_duplicate_keys(ca.CURATION)


@pytest.fixture(scope="module")
def facts() -> tuple[set[str], dict[str, str], dict[str, set[str]]]:
    registered, verdicts = cc.read_verdicts()
    return registered, verdicts, cc.read_restrictions()


@pytest.fixture(scope="module")
def by_verdict(facts) -> dict[str, list[str]]:
    """Unrestricted cases grouped by verdict — the only ones that may legally colour a box."""
    _, verdicts, restrictions = facts
    out: dict[str, list[str]] = {}
    for case, v in verdicts.items():
        if not (set(restrictions.get(case, set())) & ca.ARCH_NON_COLOURING):
            out.setdefault(v, []).append(case)
    return {k: sorted(v) for k, v in out.items()}


@pytest.fixture(scope="module")
def never_cite(facts) -> list[str]:
    _, _, restrictions = facts
    return sorted(c for c, rs in restrictions.items() if cc.RESTRICTION_NEVER & rs)


def _pick(group: dict[str, list[str]], key: str) -> str:
    cases = group.get(key)
    if not cases:
        pytest.skip(f"the repository currently has no citable case with verdict {key!r}, so this arm "
                    f"cannot be built from real artifacts and must not be built from invented ones")
    return cases[0]


def _run(tmp_path: Path, data: dict, capsys) -> tuple[int, str]:
    """Dump `data`, run the gate over it, and return (rc, everything it printed)."""
    path = tmp_path / "architecture.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        rc = ca.main(["--architecture", str(path)])
    except SystemExit as e:                    # `die()` for an input the rules cannot run over
        rc = e.code
    captured = capsys.readouterr()
    return rc, captured.out + captured.err


def _d(data: dict, i: int = 0) -> dict:
    return data["diagrams"][i]


def _box(data: dict, pred, what: str) -> tuple[dict, dict]:
    """The first (diagram, box) satisfying `pred`. Skips rather than inventing one."""
    for d in data["diagrams"]:
        for b in d["boxes"]:
            if pred(b):
                return d, b
    pytest.skip(f"architecture.yaml currently has no box that is {what}")


def _measured_box(data: dict) -> tuple[dict, dict]:
    return _box(data, lambda b: b.get("cases"), "backed by cases")


def _unmeasured_box(data: dict) -> tuple[dict, dict]:
    return _box(data, lambda b: b.get("measured") is not None, "declared `measured: none`")


def _property_box(data: dict) -> tuple[dict, dict]:
    return _box(data, lambda b: b.get("kind") == "property", "kind: property")


# --------------------------------------------------------------------------- 0. the control


def test_the_real_file_passes(capsys):
    """The no-mutant control. Without it every arm below would pass just as well if the gate had begun
    failing unconditionally, which is the likeliest way a mutation suite goes quietly worthless."""
    rc = ca.main([])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "OK:" in out
    assert "diagram(s)" in out and "placed" in out, "the summary must state what it covered"


def test_an_unmutated_copy_also_passes(tmp_path, real, capsys):
    """And the harness itself must not be what fails: a round-trip through `yaml.safe_dump` has to
    survive the gate, or every arm below would 'detect' its own serialisation."""
    rc, out = _run(tmp_path, copy.deepcopy(real), capsys)
    assert rc == 0, out


# --------------------------------------------------------------------------- 1. shape


def test_a_wrong_schema_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    data["schema"] = "grx-architecture/2"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "schema" in out, out


def test_an_unknown_top_level_key_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    data["diagram"] = []                       # a plausible typo for `diagrams`
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "unknown key" in out, out


def test_a_missing_author_or_date_is_caught(tmp_path, real, capsys):
    for key in ("mapped_by", "mapped_on", "note"):
        data = copy.deepcopy(real)
        data[key] = ""
        rc, out = _run(tmp_path, data, capsys)
        assert rc == 2 and key in out, out


def test_a_missing_vocabulary_stops_the_gate_rather_than_passing_it(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    del data["vocabularies"]["kind"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "kind" in out, out


def test_a_vocabulary_entry_no_box_uses_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    data["vocabularies"]["kind"] = [*data["vocabularies"]["kind"], "sidecar"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "sidecar" in out, out


def test_the_count_from_vocabulary_is_exempt_from_the_use_check(tmp_path, real, capsys):
    """The deliberate asymmetry, pinned so nobody 'fixes' it into a rule that contradicts the builder.

    `derive_architecture()` requires the declared metric set to equal the metric table exactly, both
    directions. If this gate ALSO demanded that each metric appear on a box, the two rules together
    would forbid the builder from computing a number the diagrams do not display — and the only way to
    satisfy both would be to put a box on the page for the sake of a metric.
    """
    data = copy.deepcopy(real)
    unused = [m for m in data["vocabularies"]["count_from"]
              if not any(b.get("count_from") == m for d in data["diagrams"] for b in d["boxes"])]
    assert unused, "this arm needs at least one declared metric that no box displays"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 0, out
    assert not any(m in out for m in unused), out


def test_one_diagram_is_below_the_floor(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    data["diagrams"] = data["diagrams"][:1]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "floor" in out, out


# --------------------------------------------------------------------------- 2. the diagram


def test_a_short_subtitle_or_justification_is_caught(tmp_path, real, capsys):
    for key, floor in (("subtitle", ca.MIN_SUBTITLE), ("why_this_diagram", ca.MIN_WHY_DIAGRAM)):
        data = copy.deepcopy(real)
        _d(data)[key] = "x" * (floor - 1)
        rc, out = _run(tmp_path, data, capsys)
        assert rc == 2 and key in out, out


def test_a_duplicate_box_id_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    d = _d(data)
    d["boxes"].append(copy.deepcopy(d["boxes"][0]))
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "defines box" in out, out


def test_a_diagram_with_too_few_boxes_or_edges_is_caught(tmp_path, real, capsys):
    for key in ("boxes", "edges"):
        data = copy.deepcopy(real)
        _d(data)[key] = _d(data)[key][:2]
        rc, out = _run(tmp_path, data, capsys)
        assert rc == 2 and "floor" in out, out


# --------------------------------------------------------------------------- 3. the box


@pytest.mark.parametrize("key", sorted(ca.FORBIDDEN_BOX_KEYS))
def test_authoring_a_derived_value_is_caught(tmp_path, real, capsys, key):
    """The rule the user set: topology is authored, every annotation is derived. A box that carries its
    own status or its own coordinates is a second source of truth for the thing most likely to be
    quoted, and the diagram's copy is the one a reader remembers."""
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    box[key] = "green" if key in {"colour", "color", "status", "badge"} else 1
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and key in out and "derived" in out, out


def test_an_unknown_box_key_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    box["case"] = ["F1-1"]                     # a plausible typo for `cases`
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "unknown key" in out, out


def test_a_short_detail_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    box["detail"] = "x" * (ca.MIN_DETAIL - 1)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "detail" in out, out


@pytest.mark.parametrize("key", ["kind", "venv", "machine"])
def test_a_missing_classification_is_caught(tmp_path, real, capsys, key):
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    del box[key]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and key in out, out


@pytest.mark.parametrize("key", ["kind", "venv", "machine", "count_from"])
def test_a_value_outside_the_vocabulary_is_caught(tmp_path, real, capsys, key):
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    box[key] = "whatever"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "vocabulary" in out, out


def test_a_program_that_does_not_exist_is_caught(tmp_path, real, capsys):
    """A box naming a script asserts machinery. The gate resolves the path from the repository root, so
    a renamed or deleted producer fails here rather than becoming a dead link on the page."""
    data = copy.deepcopy(real)
    _, box = _box(data, lambda b: b.get("program"), "naming a program")
    box["program"] = "tools/no_such_program.py"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "not a file" in out, out


def test_every_program_named_by_the_real_file_exists():
    """The positive direction, over the real file rather than a mutant. `census.py` sits at the
    repository root while `day2_replicate.py` sits under `tools/`, so the paths are the only thing that
    can be checked — and the arm above would pass over a file that named none."""
    data = cc.load_yaml_no_duplicate_keys(ca.CURATION)
    named = [b["program"] for d in data["diagrams"] for b in d["boxes"] if b.get("program")]
    assert len(named) >= 8, f"only {len(named)} box(es) name a program; this check has gone thin"
    for p in named:
        assert (ca.ROOT / p).is_file(), p


# ------------------------------------------------------- 4. measured, or explicitly not


def test_a_box_with_both_cases_and_measured_none_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    box["measured"] = "none"
    box["why_not_measured"] = "x" * 200
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "both" in out, out


def test_a_box_with_neither_is_caught(tmp_path, real, capsys):
    """The state that renders as an uncoloured box, which a reader takes for 'nothing to worry about'."""
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    del box["cases"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "neither" in out, out


def test_a_short_why_these_cases_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    box["why_these_cases"] = "x" * (ca.MIN_WHY - 1)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "why_these_cases" in out, out


def test_a_short_why_not_measured_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _, box = _unmeasured_box(data)
    box["why_not_measured"] = "x" * (ca.MIN_WHY_NOT_MEASURED - 1)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "why_not_measured" in out, out


def test_a_truthy_measured_value_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _, box = _unmeasured_box(data)
    box["measured"] = "partially"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "measured" in out, out


# --------------------------------------------------------------------------- 5. the cases


def test_a_case_not_in_the_register_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    box["cases"] = [*box["cases"], "F99-9"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "F99-9" in out and "register" in out, out


def test_the_same_case_named_twice_in_one_box_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    box["cases"] = [*box["cases"], box["cases"][0]]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "twice" in out, out


def test_one_case_colouring_two_boxes_of_one_diagram_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    # Needs a diagram with two case-bearing boxes — `verdict_pipeline` has exactly one, so the first
    # such box is not enough and picking it would make this arm a StopIteration rather than a test.
    d = next((x for x in data["diagrams"]
              if sum(1 for b in x["boxes"] if b.get("cases")) >= 2), None)
    if d is None:
        pytest.skip("no diagram currently has two case-bearing boxes to collide")
    box, other = [b for b in d["boxes"] if b.get("cases")][:2]
    other["cases"] = [*other["cases"], box["cases"][0]]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "already placed" in out, out


def test_placing_a_never_cite_case_on_a_box_is_caught(tmp_path, real, capsys, never_cite):
    """The user's rule: a NEVER_CITE case may never be a box's support. It cannot be cited as anything,
    so its only legal home is `unplaced_cases`, with the reason in writing."""
    if not never_cite:
        pytest.skip("the citation policy currently marks no case NEVER_CITE")
    case = never_cite[0]
    data = copy.deepcopy(real)
    data["unplaced_cases"] = [u for u in data["unplaced_cases"] if u["case"] != case]
    _, box = _measured_box(data)
    box["cases"] = [*box["cases"], case]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and case in out, out


# --------------------------------------------------------------------------- 6. the colouring rule


def test_the_two_modules_agree_on_which_restrictions_disqualify_a_case():
    """One citation rule, not two. The architecture view and the controls view answer the same question
    about the same restriction table; if they diverge, the diagram colours a box from a verdict the
    other gate refuses to cite — and the diagram is the artifact that travels without its text."""
    assert ca.ARCH_NON_COLOURING == cc.RESTRICTION_NEVER | cc.RESTRICTION_CONTEXT_ONLY
    assert ca.ARCH_NON_COLOURING <= cc.KNOWN_RESTRICTIONS


def test_an_inconclusive_only_box_may_not_read_as_validated(by_verdict):
    """Asserted against the shared rule directly, because this is the one the user named. There is no
    mutant of the YAML that produces it — the rule is in `box_status`, and the arm has to reach it."""
    case = _pick(by_verdict, "INCONCLUSIVE")
    status, why = ca.box_status([{"case": case, "verdict": "INCONCLUSIVE", "restrictions": []}])
    assert status == "not_established", f"{case} alone gave {status}: {why}"


def test_a_restricted_case_colours_nothing_even_when_it_is_the_only_support(facts):
    _, verdicts, restrictions = facts
    supported = [c for c, rs in restrictions.items()
                 if (set(rs) & ca.ARCH_NON_COLOURING) and verdicts.get(c) in {"TRUE", "FALSE"}]
    if not supported:
        pytest.skip("no case currently carries both a non-colouring restriction and a TRUE/FALSE verdict")
    case = supported[0]
    status, why = ca.box_status([{"case": case, "verdict": verdicts[case],
                                  "restrictions": sorted(restrictions[case])}])
    assert status == "context_only", f"{case} ({verdicts[case]}) gave {status}: {why}"


def test_one_false_outranks_four_trues(by_verdict):
    """The precedence the user's rule turns on, and the one a later refactor is most likely to invert:
    a component with four TRUEs and one FALSE is a component with a finding, and a green box buries it."""
    trues = (by_verdict.get("TRUE") or [])[:4]
    false = _pick(by_verdict, "FALSE")
    if len(trues) < 4:
        pytest.skip("fewer than four citable TRUE verdicts exist")
    mix = [{"case": c, "verdict": "TRUE", "restrictions": []} for c in trues]
    assert ca.box_status(mix)[0] == "validated_in_part"
    mix.append({"case": false, "verdict": "FALSE", "restrictions": []})
    assert ca.box_status(mix)[0] == "contested"


def test_a_box_with_no_cases_is_not_measured_rather_than_clean():
    status, why = ca.box_status([])
    assert status == "not_measured", why


# --------------------------------------------------------------------------- 7. the edges


def test_an_edge_to_a_box_that_does_not_exist_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _d(data)["edges"][0]["to"] = "nowhere"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "nowhere" in out, out


def test_a_self_edge_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    e = _d(data)["edges"][0]
    e["to"] = e["from"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "self-edge" in out, out


def test_a_duplicate_edge_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    d = _d(data)
    d["edges"].append(copy.deepcopy(d["edges"][0]))
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "twice" in out, out


def test_an_unlabelled_edge_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _d(data)["edges"][0]["label"] = ""
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "label" in out, out


def test_an_edge_kind_outside_the_vocabulary_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _d(data)["edges"][0]["kind"] = "maybe"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "vocabulary" in out, out


def test_a_cycle_is_caught(tmp_path, real, capsys):
    """The pipeline diagram's whole claim is an ORDER — sealed before measured, replicated before
    amended. A cycle means it no longer states one, and the layout would have no topological order to
    lay out either."""
    data = copy.deepcopy(real)
    d = _d(data)
    e = d["edges"][0]
    d["edges"].append({"from": e["to"], "to": e["from"], "kind": e["kind"], "label": "back"})
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "cycle" in out, out


def test_an_isolated_box_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    d = _d(data)
    orphan = copy.deepcopy(d["boxes"][0])
    orphan["id"] = "orphan"
    # Its cases go with it, or the duplicate-case rule fires at the same path and this arm passes on
    # the wrong finding — the box path contains "orphan" either way.
    orphan.pop("cases", None)
    orphan["measured"] = "none"
    orphan["why_not_measured"] = "x" * (ca.MIN_WHY_NOT_MEASURED + 10)
    d["boxes"].append(orphan)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "no edge at all" in out, out


def test_a_property_box_with_a_second_parent_is_caught(tmp_path, real, capsys):
    """The placement rule the crossing-free layout rests on. A property with two parents cannot sit in
    one parent's row, and the layout would have to route an edge across the spine to reach it."""
    data = copy.deepcopy(real)
    d, prop = _property_box(data)
    parent = next(e["from"] for e in d["edges"] if e["to"] == prop["id"])
    other = next(b["id"] for b in d["boxes"]
                 if b["id"] not in {prop["id"], parent} and b.get("kind") != "property")
    d["edges"].append({"from": other, "to": prop["id"], "kind": "data_flow", "label": "also"})
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "incoming" in out, out


def test_an_edge_out_of_a_property_box_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    d, prop = _property_box(data)
    target = next(b["id"] for b in d["boxes"]
                  if b["id"] != prop["id"] and b.get("kind") != "property")
    d["edges"].append({"from": prop["id"], "to": target, "kind": "data_flow", "label": "onward"})
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "outgoing" in out, out


# --------------------------------------------------------------------------- 8. coverage


def test_an_unplaced_entry_with_no_reason_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    if not data["unplaced_cases"]:
        pytest.skip("no case is currently excluded, so there is no entry to shorten")
    data["unplaced_cases"][0]["why"] = "x" * (ca.MIN_WHY - 1)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "why" in out, out


def test_an_unplaced_case_that_is_not_registered_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    data["unplaced_cases"] = [*data["unplaced_cases"],
                              {"case": "F99-9", "why": "x" * (ca.MIN_WHY + 10)}]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "F99-9" in out, out


def test_a_case_both_placed_and_unplaced_is_caught(tmp_path, real, capsys):
    """Two answers, of which a reader sees only the friendlier."""
    data = copy.deepcopy(real)
    _, box = _measured_box(data)
    data["unplaced_cases"] = [*data["unplaced_cases"],
                              {"case": box["cases"][0], "why": "x" * (ca.MIN_WHY + 10)}]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and box["cases"][0] in out, out


def test_a_registered_case_that_is_neither_placed_nor_excluded_is_caught(tmp_path, real, capsys):
    """The ceiling, in the direction that matters: a case joining the register later must not be able to
    appear on no diagram and in no list. Invisible by construction is the failure mode this repository is
    built against (`feedback_unnumbered_is_uncounted`)."""
    data = copy.deepcopy(real)
    dropped = None
    for d in data["diagrams"]:
        for b in d["boxes"]:
            if len(b.get("cases") or []) > 1:
                dropped = b["cases"].pop()
                break
        if dropped:
            break
    assert dropped, "no box has two cases to drop one from"
    # And out of the other diagram too, or the union still covers it.
    for d in data["diagrams"]:
        for b in d["boxes"]:
            if dropped in (b.get("cases") or []):
                b["cases"].remove(dropped)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and dropped in out and "neither" in out, out


def test_a_never_cite_case_missing_from_the_exclusion_list_is_caught(
        tmp_path, real, capsys, never_cite):
    if not never_cite:
        pytest.skip("the citation policy currently marks no case NEVER_CITE")
    case = never_cite[0]
    data = copy.deepcopy(real)
    data["unplaced_cases"] = [u for u in data["unplaced_cases"] if u["case"] != case]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and case in out, out


def test_an_empty_unplaced_list_is_a_list_and_not_an_absent_key(tmp_path, real, capsys):
    """`unplaced_cases` is required even when empty: the coverage claim is checked in both directions,
    and without the key there is no second direction to check."""
    data = copy.deepcopy(real)
    del data["unplaced_cases"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "unplaced_cases" in out, out


def test_a_file_with_no_placed_cases_at_all_fails_rather_than_passing_vacuously(
        tmp_path, real, capsys):
    """Every legality rule in the gate quantifies over placed cases. Strip them and the rules all pass —
    which is exactly the result a scan reading zero of something must never produce
    (`feedback_zero_file_scan_is_error`)."""
    data = copy.deepcopy(real)
    for d in data["diagrams"]:
        for b in d["boxes"]:
            if b.get("cases"):
                del b["cases"]
                b["measured"] = "none"
                b["why_not_measured"] = "x" * (ca.MIN_WHY_NOT_MEASURED + 10)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2, out
    assert "zero cases" in out or "neither" in out, out
