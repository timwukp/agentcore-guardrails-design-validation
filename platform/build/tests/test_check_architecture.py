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

WHY SOME ARMS ARE POSITIVE AND ONE OF THEM ASSERTS rc == 0

A mutant can only show that a rule fires. Two of this gate's newer rules are about something the file
does NOT say: a box that names `from_section` takes its cases from the design document, so the failure
to worry about is the placement quietly not happening — no message, no finding, a diagram that reports
nine sections' evidence as absent. There is no mutation of the YAML that produces that; it comes from
reading the authored key instead of the resolved one. So `test_a_case_the_document_cites_stays_placed_
with_no_authored_list` deletes every document-cited case from every authored list and requires rc **0**,
and `test_the_real_file_reads_every_section_the_document_measures` closes the other direction — a
section the document measures that no box reads is a hop missing from the picture with nothing saying so.
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


@pytest.fixture(scope="module")
def sections() -> dict[str, dict]:
    """The design document's measured sections, through the gate's own reader.

    Module-scoped because `read_sections()` runs `check_practices.adjudicate()`, and re-parsing two
    editions of a 45-practice document once per arm would cost more than every other fixture combined.
    """
    return ca.read_sections()


@pytest.fixture(scope="module")
def section_cited(sections) -> set[str]:
    """Every case the design document cites — placement this file cannot revoke by editing itself."""
    return {c for s in sections.values() for c in (s.get("section_cites") or [])}


def _section_box(data: dict) -> tuple[dict, dict]:
    return _box(data, lambda b: b.get("from_section"), "reading its cases from a document section")


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


def _satellite_box(data: dict, kind: str) -> tuple[dict, dict]:
    return _box(data, lambda b: b.get("kind") == kind, f"kind: {kind}")


def _bilingual_diagram(data: dict) -> tuple[dict, dict]:
    """The first diagram whose prose is authored in both languages, with its own subtitle.

    Mutating a bare-string subtitle would test the string arm a second time; the bilingual arms need a
    value that already has the mapping shape, so the mutation is the only difference.
    """
    for d in data["diagrams"]:
        if isinstance(d.get("subtitle"), dict):
            return d, d["subtitle"]
    pytest.skip("no diagram currently carries a bilingual subtitle")


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


def test_a_missing_view_vocabulary_stops_the_gate(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    del data["vocabularies"]["view"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "view" in out, out


def test_a_diagram_with_no_view_is_caught(tmp_path, real, capsys):
    """Which page draws a diagram is declared, not inferred. `Architecture.tsx` filters on this key, so a
    diagram with no view is one both pages draw — and the evidence page would then show the design's own
    loop under the heading 'what the study looked at', which is the one thing it is not."""
    data = copy.deepcopy(real)
    del _d(data)["view"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "view" in out, out


def test_a_view_outside_the_vocabulary_is_caught(tmp_path, real, capsys):
    data = copy.deepcopy(real)
    _d(data)["view"] = "both"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "vocabulary" in out, out


def test_a_view_no_diagram_uses_is_caught(tmp_path, real, capsys):
    """The other direction, and the one that decays silently: if every diagram moved to one page, the
    unused view would stay declared and would go on describing a partition the file no longer makes."""
    data = copy.deepcopy(real)
    data["vocabularies"]["view"] = [*data["vocabularies"]["view"], "printable"]
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "printable" in out, out


def test_the_real_file_declares_a_diagram_in_every_view(real):
    """Positive direction, over the real file: each declared view has at least one diagram, so the arms
    that quantify over a view's diagrams are not quantifying over nothing."""
    declared = set(real["vocabularies"]["view"])
    used = {d.get("view") for d in real["diagrams"]}
    assert declared == used, f"declared {sorted(declared)}, used {sorted(v for v in used if v)}"


# --------------------------------------------------------------------------- 2. the diagram


def test_a_short_subtitle_or_justification_is_caught(tmp_path, real, capsys):
    for key, floor in (("subtitle", ca.MIN_SUBTITLE), ("why_this_diagram", ca.MIN_WHY_DIAGRAM)):
        data = copy.deepcopy(real)
        _d(data)[key] = "x" * (floor - 1)
        rc, out = _run(tmp_path, data, capsys)
        assert rc == 2 and key in out, out


def test_a_bilingual_value_saying_the_same_thing_twice_is_caught(tmp_path, real, capsys):
    """`authored()`'s own rule, restated where the value is authored rather than emitted.

    A `zh` that repeats the English claims a translation the reader does not get, and it is worse than an
    untranslated string because the untranslated one is counted: `census_rendered_surfaces.py` measures
    bare strings as the backlog, and a mapping is assumed done. So the dishonest shape is the one that
    has to fail.
    """
    data = copy.deepcopy(real)
    d, _ = _bilingual_diagram(data)
    text = "x" * (ca.MIN_SUBTITLE + 10)
    d["subtitle"] = {"en": text, "zh": text}
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "both languages" in out, out


def test_a_short_chinese_half_is_caught(tmp_path, real, capsys):
    """Each half is held to its own floor. An arm reading only `en` would pass a `zh` trimmed to two
    characters, and the reader of the Chinese page is the one who would find out."""
    data = copy.deepcopy(real)
    d, _ = _bilingual_diagram(data)
    floor = int(ca.MIN_SUBTITLE * ca.ZH_LENGTH_RATIO)
    d["subtitle"] = {"en": "x" * (ca.MIN_SUBTITLE + 10), "zh": "z" * (floor - 1)}
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "subtitle.zh" in out, out


def test_a_short_english_half_is_caught_at_the_full_floor(tmp_path, real, capsys):
    """And the Chinese ratio must not have relaxed the English side on the way past."""
    data = copy.deepcopy(real)
    d, _ = _bilingual_diagram(data)
    d["subtitle"] = {"en": "x" * (ca.MIN_SUBTITLE - 1), "zh": "z" * (ca.MIN_SUBTITLE + 10)}
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "subtitle.en" in out, out


def test_a_bilingual_value_with_a_third_key_is_caught(tmp_path, real, capsys):
    """A mapping with an extra key loses whatever is in it silently — including a `zh-TW` somebody added
    thinking the payload keyed languages by tag."""
    data = copy.deepcopy(real)
    d, _ = _bilingual_diagram(data)
    d["subtitle"] = {"en": "x" * (ca.MIN_SUBTITLE + 10), "zh": "z" * (ca.MIN_SUBTITLE + 10),
                     "zh-TW": "z" * (ca.MIN_SUBTITLE + 10)}
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "exactly" in out, out


def test_the_real_file_has_a_bilingual_diagram_at_all(real):
    """Otherwise the four arms above are testing a shape the file does not use, and the day the last
    bilingual value is deleted they would go on passing over bare strings."""
    bilingual = [d["id"] for d in real["diagrams"] if isinstance(d.get("subtitle"), dict)]
    assert bilingual, "no diagram carries a bilingual subtitle; the prose arms have gone vacuous"


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


# ------------------------------------------- 3b. a box that reads a document section


def test_a_section_that_the_document_does_not_have_is_caught(tmp_path, real, capsys):
    """A box may name a section only if the design document has one, with citations of its own.

    The section ids are the document's, and a renumbering there would otherwise leave a box silently
    reading nothing: `sections.get(sid, {})` yields no cases, the box draws as not_measured, and the page
    would report 'this study never looked' about a section the study covered.
    """
    data = copy.deepcopy(real)
    _, box = _section_box(data)
    box["from_section"] = "9.9"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "9.9" in out and "measured section" in out, out


@pytest.mark.parametrize("key", sorted(ca.FROM_SECTION_DERIVES))
def test_authoring_a_derived_key_beside_from_section_is_caught(tmp_path, real, capsys, key):
    """The split, in the direction this file can break it: a second wording of a section is one wording
    that can go stale, and it is the one on the picture."""
    data = copy.deepcopy(real)
    _, box = _section_box(data)
    box[key] = ["F1-1"] if key == "cases" else ("none" if key == "measured" else "x" * 200)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and key in out and "document" in out, out


def test_the_real_file_reads_every_section_the_document_measures(real, sections):
    """Positive direction, and a ceiling on the other side of `from_section`.

    A section the document measures and no box reads is a piece of the design the diagram silently drops
    — the reader sees five hops where the document prescribes six, and nothing in the payload says a
    section is missing. This is the arm that would have caught the closed-loop diagram shipping with a
    phase left out.
    """
    read = {str(b["from_section"]) for d in real["diagrams"] for b in d["boxes"]
            if b.get("from_section")}
    assert read == set(sections), f"the document measures {sorted(set(sections) - read)} that no box " \
                                  f"reads, and boxes read {sorted(read - set(sections))} it does not " \
                                  f"measure"


def test_a_section_box_places_the_cases_the_document_cites(real, sections, capsys):
    """The count, derived twice and compared — the placement census against the document's own citations.

    `check_box` resolves a section box's cases and hands them to the coverage census; this asserts the
    two agree, over the real file rather than a mutant. Two numbers are two claims, so neither is inferred
    from the other (`feedback_two_numbers_two_claims`): the left side counts boxes in this file, the right
    side counts citations in the document.
    """
    from_boxes = {c for d in real["diagrams"] for b in d["boxes"] if b.get("from_section")
                  for c in sections[str(b["from_section"])]["section_cites"]}
    from_doc = {c for s in sections.values() for c in s["section_cites"]}
    assert from_boxes == from_doc, sorted(from_doc ^ from_boxes)
    assert len(from_doc) >= 40, f"the document cites {len(from_doc)} distinct case(s); this arm would " \
                                f"then be asserting almost nothing"


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


@pytest.mark.parametrize("kind", sorted(ca.SATELLITE_KINDS))
def test_a_satellite_box_with_a_second_parent_is_caught(tmp_path, real, capsys, kind):
    """The placement rule the crossing-free layout rests on, over every satellite kind.

    A satellite with two parents cannot sit in one parent's row, and the layout would have to route an
    edge across the spine to reach it. Parametrized over the kinds rather than written for `property`,
    because `alternative` was added later and shares the whole contract — a rule checked for one of two
    kinds is a rule the newer kind can walk past.
    """
    data = copy.deepcopy(real)
    d, sat = _satellite_box(data, kind)
    parent = next(e["from"] for e in d["edges"] if e["to"] == sat["id"])
    other = next(b["id"] for b in d["boxes"]
                 if b["id"] not in {sat["id"], parent} and b.get("kind") not in ca.SATELLITE_KINDS)
    d["edges"].append({"from": other, "to": sat["id"], "kind": "data_flow", "label": "also"})
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "incoming" in out, out


@pytest.mark.parametrize("kind", sorted(ca.SATELLITE_KINDS))
def test_an_edge_out_of_a_satellite_box_is_caught(tmp_path, real, capsys, kind):
    data = copy.deepcopy(real)
    d, sat = _satellite_box(data, kind)
    target = next(b["id"] for b in d["boxes"]
                  if b["id"] != sat["id"] and b.get("kind") not in ca.SATELLITE_KINDS)
    d["edges"].append({"from": sat["id"], "to": target, "kind": "data_flow", "label": "onward"})
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "outgoing" in out, out


def test_a_feedback_label_does_not_buy_a_satellite_an_outgoing_edge(tmp_path, real, capsys):
    """The reason the degree counts span the feedback edges as well as the ordering ones.

    `feedback` is exempt from the acyclicity walk and from nothing else. If the degree checks had been
    built over the order graph — the natural way to write them, since that is the graph the walk needs —
    then labelling an edge `feedback` would let a satellite acquire a child, and the crossing-free
    construction rests on satellites having none.
    """
    data = copy.deepcopy(real)
    d, sat = _satellite_box(data, "property")
    target = next(b["id"] for b in d["boxes"]
                  if b["id"] != sat["id"] and b.get("kind") not in ca.SATELLITE_KINDS)
    d["edges"].append({"from": sat["id"], "to": target,
                       "kind": ca.FEEDBACK_EDGE_KIND, "label": "onward"})
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "outgoing" in out, out


def test_a_feedback_edge_that_closes_no_loop_is_caught(tmp_path, real, capsys):
    """What replaces the acyclicity exemption, in the direction the label can be abused.

    An edge marked `feedback` is not walked for cycles, so the label is a way to draw an arrow the
    ordering rules would otherwise reject. The price is that it must actually close a loop: there has to
    be a path from its head back to its tail. Without this arm, `feedback` reads as 'exempt this arrow
    from the rules', which is a licence rather than a kind.
    """
    data = copy.deepcopy(real)
    found = None
    for d in data["diagrams"]:
        adj: dict[str, list[str]] = {b["id"]: [] for b in d["boxes"]}
        kinds = {b["id"]: b.get("kind") for b in d["boxes"]}
        existing = set()
        for e in d["edges"]:
            adj[e["from"]].append(e["to"])
            existing.add((e["from"], e["to"]))

        def reaches(src: str, dst: str, adj: dict[str, list[str]] = adj) -> bool:
            seen, stack = {src}, [src]
            while stack:
                for n in adj[stack.pop()]:
                    if n == dst:
                        return True
                    if n not in seen:
                        seen.add(n)
                        stack.append(n)
            return False

        spine = [b for b in adj if kinds[b] not in ca.SATELLITE_KINDS]
        found = next(((d, a, b) for a in spine for b in spine
                      if a != b and (a, b) not in existing and not reaches(b, a)), None)
        if found:
            break
    if not found:
        pytest.skip("every ordered pair of spine boxes already has a return path, so a feedback edge "
                    "that closes no loop cannot be built from the real topology")
    d, a, b = found
    d["edges"].append({"from": a, "to": b, "kind": ca.FEEDBACK_EDGE_KIND, "label": "back, allegedly"})
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and "closes no loop" in out and f"{a}->{b}" in out, out


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


def test_a_registered_case_that_is_neither_placed_nor_excluded_is_caught(
        tmp_path, real, capsys, section_cited):
    """The ceiling, in the direction that matters: a case joining the register later must not be able to
    appear on no diagram and in no list. Invisible by construction is the failure mode this repository is
    built against (`feedback_unnumbered_is_uncounted`).

    The case has to be one that ONLY this file places. Half the closed-loop diagram's boxes take their
    cases from the design document's own citations, and no edit to this file can revoke those — which is
    the point of `from_section` and is asserted directly in the arm below. Deleting a document-cited case
    from every authored list here leaves it placed, so an arm that picked one would report the ceiling
    broken when it is the derivation working.
    """
    data = copy.deepcopy(real)
    dropped = next((c for d in data["diagrams"] for b in d["boxes"]
                    for c in (b.get("cases") or [])
                    if len(b["cases"]) > 1 and c not in section_cited), None)
    assert dropped, "every case on a multi-case box is also cited by the design document; this arm " \
                    "needs one whose only placement is authored here"
    # Out of every box, in every diagram, or the union still covers it.
    for d in data["diagrams"]:
        for b in d["boxes"]:
            if dropped in (b.get("cases") or []):
                b["cases"].remove(dropped)
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 2 and dropped in out and "neither" in out, out


def test_a_case_the_document_cites_stays_placed_with_no_authored_list(
        tmp_path, real, capsys, section_cited):
    """The positive direction of `from_section`, and the arm that would fail on the likeliest regression.

    `check_box` returns the RESOLVED case list rather than `b["cases"]`, so a box that names a section
    places what the document cites. Read the authored key instead and those boxes place nothing: the
    coverage census would then report every document-cited case as unplaced, the ceiling would pass over
    all nine boxes, and the legality rules would quantify over an empty set for half the diagram — the
    shape a rule takes when it goes quiet (`feedback_derive_from_every_producer`).

    So a case the document cites is deleted from every authored list in this file and the gate must still
    exit 0. Nothing else is changed, and the control arm above proves the unmutated copy passes.
    """
    data = copy.deepcopy(real)
    removed = 0
    for d in data["diagrams"]:
        for b in d["boxes"]:
            keep = [c for c in (b.get("cases") or []) if c not in section_cited]
            if b.get("cases") is None or keep == b["cases"]:
                continue
            removed += len(b["cases"]) - len(keep)
            if keep:
                b["cases"] = keep
                continue
            # A box stripped bare has to say so, or it fails the has-neither rule instead and this arm
            # would 'detect' the wrong finding.
            del b["cases"]
            b.pop("why_these_cases", None)
            b["measured"] = "none"
            b["why_not_measured"] = "x" * (ca.MIN_WHY_NOT_MEASURED + 10)
    assert removed >= 8, f"only {removed} authored placement(s) overlap the document's citations; this " \
                         f"arm would then prove almost nothing"
    rc, out = _run(tmp_path, data, capsys)
    assert rc == 0, out


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
