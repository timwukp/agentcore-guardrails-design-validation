"""Mutation tests for the design-citation gate.

WHY EVERY ARM HERE IS A MUTATION AND NOT AN ASSERTION ABOUT THE CURRENT TREE

`check_practices.py` exists to make one sentence checkable: *the design was measured on this platform,
it is not asserted*. A gate that makes that claim is worth exactly what its failure modes are worth, and
a gate arm that has never fired is indistinguishable from one that cannot (`feedback_vacuous_test_check`).
So each test below takes the real tree — which passes — changes one thing that ought to break it, and
requires the named finding. `test_the_real_tree_adjudicates_clean` is the no-mutant control and runs
first: without it, every other test here would also pass against a gate that flagged everything.

WHY THE MUTATIONS ARE THE ONES THEY ARE

They are the five ways this hook can rot, and the two-way counting is two separate tests because it is
two separate claims (`feedback_two_numbers_two_claims`):

  * the register moves under the document — a verdict is amended and a citation of the old one stays;
  * the sentence moves under the ledger — the sentence an exemption was granted for is rewritten, and
    the exemption would otherwise keep applying to whatever replaced it;
  * the ledger has an entry for a sentence that no longer occurs — an exemption outliving its defect;
  * an occurrence has no entry — a new disagreement arriving quietly;
  * the two editions stop agreeing — a Chinese reader shown fewer links, or different ones.

The YAML-boolean arm is here because it already happened: `asserted: TRUE` unquoted is `True` under
YAML 1.1, and the symptom was eleven "no entry at all" findings paired with eleven "outlives its
sentence" findings — a missing pair of quotes reading as twenty-two document defects
(`feedback_cryptic_error_is_missing_guard`).

The column-floor arm is here because a character floor is a *different* floor in each language, and it
rejected the Chinese quotation of a sentence whose English quotation it accepted. A gate that is
weaker on the edition it appears to check more strictly is worse than no floor, because the number it
prints is the same either way.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import check_practices as cp  # noqa: E402
import practices_source as ps  # noqa: E402
from check_controls import Findings  # noqa: E402

LEDGER = REPO / "platform" / "curation" / "practices.yaml"

# What the tree carries today. These are not the gate's rules — the gate hardcodes no case id and no
# count — they are this test file's fixture, so a mutation's effect is measured against a known base.
N_ADJUDICATED = 11
N_OPEN = 7


# --------------------------------------------------------------------------- the base, read once

@pytest.fixture(scope="module")
def base():
    """The real design, register and ledger. Read once: extracting two 160 KB documents is the cost."""
    from check_controls import read_restrictions, read_verdicts

    registered, verdicts = read_verdicts()
    design = ps.extract_files()
    return {"design": design, "registered": registered, "verdicts": verdicts,
            "restrictions": read_restrictions(),
            "entries": yaml.safe_load(LEDGER.read_text(encoding="utf-8"))["citation_adjudications"]}


def _run(base, *, verdicts=None, design=None, entries=None):
    """`needs_adjudication` + `match`, the pair that decides what is unruled, over mutated inputs."""
    f = Findings()
    design = design if design is not None else base["design"]
    occ = cp.needs_adjudication(design["assertions"],
                                verdicts if verdicts is not None else base["verdicts"],
                                base["restrictions"])
    matched = cp.match(occ, copy.deepcopy(base["entries"] if entries is None else entries), f)
    return occ, matched, f.items


def _ledger_to(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- the no-mutant control

def test_the_real_tree_adjudicates_clean():
    """The control. Every other test in this file asserts a change from this state."""
    result = cp.adjudicate()
    assert result["findings"].items == []
    assert len(result["adjudications"]) == N_ADJUDICATED
    assert len(result["open_findings"]) == N_OPEN
    assert len(result["occurrences"]) == N_ADJUDICATED, "an unruled occurrence would be a finding"


def test_every_open_finding_names_a_register_item_and_a_blocker(base):
    """An OPEN disposition is a published finding, so the fields that make it actionable are required."""
    for e in base["entries"]:
        if cp.DISPOSITIONS[e["disposition"]] != "open":
            continue
        for k in cp.OPEN_REQUIRES:
            assert e.get(k), f"{e['case']}/{e['where']} is {e['disposition']} and names no {k!r}"


# --------------------------------------------------------------------------- the register moves

def test_flipping_a_registered_verdict_leaves_a_citation_unruled(base):
    """An amended verdict must not leave the document's citation of the old one passing.

    F6-1 is cited FALSE and the register says FALSE, so today it needs no ruling — its restriction
    licenses the verdict itself. Amend the register to TRUE and the document's FALSE is a claim the
    register contradicts, which is the one thing no reason can excuse without a human writing it down.
    """
    _, _, clean = _run(base)
    assert clean == []

    mutant = dict(base["verdicts"], **{"F6-1": "TRUE"})
    occ, matched, items = _run(base, verdicts=mutant)
    disagreements = [o for o in occ if o["case"] == "F6-1"]
    assert disagreements, "flipping the register produced no new occurrence"
    assert all(o["rule"] == "DISAGREES_WITH_REGISTER" for o in disagreements)
    assert any("F6-1" in i and "the register says TRUE" in i for i in items), items
    assert len(matched) == N_ADJUDICATED, "the mutation should add findings, not re-home rulings"


def test_a_bare_citation_is_not_a_claim_about_a_verdict(base):
    """The complement of the arm above: naming a case asserts nothing, and must not be adjudicated.

    Most of the 324 references name a case without a verdict word. If those needed rulings the ledger
    would grow to the size of the document and stop being read, which is how a suppression list is born.
    """
    bare = [a for a in base["design"]["assertions"] if a["asserted"] is None]
    assert bare, "the fixture assumes the document cites cases without asserting verdicts"
    occ, _, _ = _run(base)
    assert not [o for o in occ if o["asserted"] is None]


# --------------------------------------------------------------------------- the sentence moves

def test_rewriting_the_withdrawn_sentence_expires_its_exemption(base):
    """F5-3b is citable only because the sentence withdraws it. Remove the withdrawal and it is not.

    This is the mutation a `(case, verdict, section)` key cannot catch: the key stays true while the
    reason stops being. The document is not touched on disk — the mutation is applied to the extracted
    span, which is the same string the page publishes and the gate reads.
    """
    design = copy.deepcopy(base["design"])
    hit = 0
    for a in design["assertions"]:
        if a["case"] == "F5-3b" and a["asserted"] == "TRUE":
            a["span"]["en"] = a["span"]["en"].replace("carries NO publishable standing",
                                                      "confirms the design")
            hit += 1
    assert hit == 1, "the fixture assumes exactly one F5-3b TRUE assertion"

    _, matched, items = _run(base, design=design)
    assert len(matched) == N_ADJUDICATED - 1
    assert any("F5-3b" in i and "none of whose quoted fragments" in i for i in items), items
    assert any("F5-3b" in i and "outlives its sentence" in i for i in items), items


def test_an_entry_whose_sentence_is_gone_fails(base):
    """Direction one of the two-way count: an exemption cannot outlive the defect it excuses."""
    entries = copy.deepcopy(base["entries"])
    ghost = copy.deepcopy(entries[0])
    ghost["where"] = "9.9"
    entries.append(ghost)

    _, matched, items = _run(base, entries=entries)
    assert len(matched) == N_ADJUDICATED
    assert any("9.9" in i and "no such assertion occurs" in i for i in items), items


def test_an_occurrence_with_no_entry_fails(base):
    """Direction two: a disagreement cannot arrive quietly. Two claims, two tests."""
    entries = [e for e in copy.deepcopy(base["entries"]) if e["case"] != "F5-3b"]
    assert len(entries) == len(base["entries"]) - 1

    _, matched, items = _run(base, entries=entries)
    assert len(matched) == N_ADJUDICATED - 1
    assert any("F5-3b" in i and "no entry at all" in i for i in items), items


def test_two_entries_cannot_quote_the_same_sentence(base):
    """A sentence with two rulings has none: the ledger cannot say which applies."""
    entries = copy.deepcopy(base["entries"])
    twin = next(e for e in entries if e["case"] == "F5-3b")
    entries.append(copy.deepcopy(twin))

    _, _, items = _run(base, entries=entries)
    assert any("F5-3b" in i and "entries all quote this one sentence" in i for i in items), items


def test_two_sentences_cannot_share_one_ruling(base):
    """§7.1 asserts F7-1 TRUE twice about different metrics; one entry must not cover both."""
    entries = [e for e in copy.deepcopy(base["entries"])
               if not (e["case"] == "F7-1" and e["where"] == "7.1")]
    shared = {"case": "F7-1", "asserted": "TRUE", "where": "7.1",
              "disposition": "LEGAL_PER_METRIC", "unit": "any",
              "evidence": "results/phase1/F7-1.json per_metric published",
              "why": "x" * (cp.MIN_WHY + 1),
              # A fragment both §7.1 sentences contain, which is exactly what makes it the wrong key.
              "span_must_contain": {"en": "TRUE for `LogOnlyMatches`", "zh": "`LogOnlyMatches` 為 TRUE"}}
    entries.append(shared)

    _, _, items = _run(base, entries=entries)
    assert any("F7-1" in i and ("shares its entry" in i or "no entry at all" in i
                                or "none of whose quoted fragments" in i) for i in items), items


# --------------------------------------------------------------------------- the derivation moves

def test_dropping_a_practice_breaks_the_section_census(base):
    """A practice outside every section sits outside every count."""
    design = copy.deepcopy(base["design"])
    design["practices"].pop(0)
    f = Findings()
    cp.check_derivation(design, base["registered"], f)
    assert any("practice" in i for i in f.items), f.items


def test_blanking_one_edition_of_a_practice_is_a_finding(base):
    """A card with prose in one language and none in the other is a page that lies about parity."""
    design = copy.deepcopy(base["design"])
    design["practices"][0]["prose"]["zh"] = "   "
    f = Findings()
    cp.check_derivation(design, base["registered"], f)
    assert any("empty zh prose" in i for i in f.items), f.items


def test_an_uncited_case_list_that_empties_is_a_finding(base):
    """The coverage ceiling in the other direction must never render as an empty list saying nothing."""
    design = copy.deepcopy(base["design"])
    design["citation_census"]["cases"] = sorted(base["registered"])
    f = Findings()
    cp.check_derivation(design, base["registered"], f)
    assert any("every registered case is cited" in i for i in f.items), f.items


def test_a_cited_id_outside_the_register_is_a_finding(base):
    """A chip linking to nothing. `F5-7B` vs `F5-7b` is how this arrives — a letter, not a rewrite."""
    design = copy.deepcopy(base["design"])
    design["citation_census"]["cases"] = sorted(set(design["citation_census"]["cases"]) | {"F5-7B"})
    f = Findings()
    cp.check_derivation(design, base["registered"], f)
    assert any("F5-7B" in i and "sealed register" in i for i in f.items), f.items


def test_deleting_a_practice_from_one_edition_fails_parity():
    """The two editions are compared, not assumed. 45 practices in one and 44 in the other must fail."""
    en = ps.EN_DOC.read_text(encoding="utf-8")
    zh = ps.ZH_DOC.read_text(encoding="utf-8")
    ps.extract(en, zh)  # control: unmutated text parses

    victim = next(li for li in zh.split("\n") if li.startswith("5. "))
    with pytest.raises(ps.SourceError):
        ps.extract(en, zh.replace(victim + "\n", "", 1))


# --------------------------------------------------------------------------- the ledger's own shape

def test_an_unquoted_verdict_names_the_yaml_boolean_trap(tmp_path, monkeypatch):
    """`asserted: TRUE` is a boolean under YAML 1.1, and the symptom is 22 misleading findings."""
    text = LEDGER.read_text(encoding="utf-8")
    assert '    asserted: "TRUE"\n' in text
    mutant = tmp_path / "practices.yaml"
    mutant.write_text(text.replace('    asserted: "TRUE"\n', "    asserted: TRUE\n", 1),
                      encoding="utf-8")

    monkeypatch.setattr(cp, "CURATION", cp.CURATION)
    result = cp.adjudicate(mutant)
    items = result["findings"].items
    assert any("YAML 1.1" in i and "not a string" in i for i in items), items


def test_the_fragment_floor_is_measured_in_columns_not_characters():
    """Why the floor is columns: the shipped Chinese quotations are under it counted as characters.

    `不具可發布地位` says what "carries NO publishable standing" says in seven characters. Under a
    character floor of 12 the gate accepts the English quotation of a sentence and rejects the Chinese
    one — checking the Chinese edition less while printing the same number.
    """
    zh = "不具可發布地位"
    assert len(zh) < cp.MIN_FRAGMENT
    assert ps.vwidth(zh) >= cp.MIN_FRAGMENT
    assert ps.vwidth("此指標為 TRUE") >= cp.MIN_FRAGMENT


def test_a_short_fragment_is_rejected_in_either_language(base):
    """The floor still fires: a fragment that short matches sentences it was not written about."""
    for lang, short in (("en", "TRUE"), ("zh", "為 TRUE")):
        data = {"schema": cp.SCHEMA, "adjudicated_on": "2026-08-23",
                "adjudicated_against": {"register": "x"},
                "citation_adjudications": copy.deepcopy(base["entries"])}
        data["citation_adjudications"][0]["span_must_contain"][lang] = short
        f = Findings()
        cp.check_shape(data, f)
        assert any(f"span_must_contain.{lang}" in i and "visual column" in i for i in f.items), f.items


def test_one_fragment_cannot_serve_both_editions(base):
    """The same string quoted twice leaves one edition unchecked — or is an untranslated sentence."""
    data = {"schema": cp.SCHEMA, "adjudicated_on": "2026-08-23",
            "adjudicated_against": {"register": "x"},
            "citation_adjudications": copy.deepcopy(base["entries"])}
    frag = data["citation_adjudications"][0]["span_must_contain"]
    frag["zh"] = frag["en"]
    f = Findings()
    cp.check_shape(data, f)
    assert any("same fragment for both editions" in i for i in f.items), f.items


def test_an_open_entry_missing_its_blocker_is_a_finding(base):
    """An open finding that names no register item and no blocker is an exemption in a finding's name."""
    data = {"schema": cp.SCHEMA, "adjudicated_on": "2026-08-23",
            "adjudicated_against": {"register": "x"},
            "citation_adjudications": copy.deepcopy(base["entries"])}
    victim = next(e for e in data["citation_adjudications"]
                  if cp.DISPOSITIONS[e["disposition"]] == "open")
    victim.pop("blocked_on")
    f = Findings()
    cp.check_shape(data, f)
    assert any("must name 'blocked_on'" in i for i in f.items), f.items


def test_a_legal_entry_carrying_a_blocker_is_a_finding(base):
    """A citation ruled legal is not blocked on anything, and pretending it is hides what is."""
    data = {"schema": cp.SCHEMA, "adjudicated_on": "2026-08-23",
            "adjudicated_against": {"register": "x"},
            "citation_adjudications": copy.deepcopy(base["entries"])}
    victim = next(e for e in data["citation_adjudications"]
                  if cp.DISPOSITIONS[e["disposition"]] == "legal")
    victim["blocked_on"] = "a v1.5 amendment"
    f = Findings()
    cp.check_shape(data, f)
    assert any("carries 'blocked_on'" in i for i in f.items), f.items


def test_an_unknown_key_in_the_ledger_is_a_finding(base):
    """A typo in a governance file reads as a rule, and a rule nothing enforces is worse than none."""
    data = {"schema": cp.SCHEMA, "adjudicated_on": "2026-08-23",
            "adjudicated_against": {"register": "x"},
            "citation_adjudications": copy.deepcopy(base["entries"])}
    data["citation_adjudications"][0]["scope_note"] = "per metric"
    f = Findings()
    cp.check_shape(data, f)
    assert any("unknown key(s) ['scope_note']" in i for i in f.items), f.items


def test_an_empty_ledger_dies_rather_than_reading_clean(tmp_path):
    """Deleting the key must not be the cheapest way to a clean build."""
    mutant = _ledger_to(tmp_path / "practices.yaml",
                        {"schema": cp.SCHEMA, "adjudicated_on": "2026-08-23",
                         "adjudicated_against": {"register": "x"},
                         "citation_adjudications": []})
    with pytest.raises(SystemExit) as exc:
        cp.adjudicate(mutant)
    assert exc.value.code == 2


def test_a_rate_in_the_ledger_is_a_finding(tmp_path):
    """This platform publishes denominators. A finding is a place guidance did not hold, not a fraction."""
    good = tmp_path / "clean.yaml"
    good.write_text("# 97% in a comment is prose about this rule\nadjudicated_on: 2026-08-23\n",
                    encoding="utf-8")
    f = Findings()
    cp.check_no_rate(good, f)
    assert f.items == [], "the control must not fire on a comment"

    bad = tmp_path / "rate.yaml"
    bad.write_text("why: 97% of the practices are validated\n", encoding="utf-8")
    f = Findings()
    cp.check_no_rate(bad, f)
    assert any("97%" in i for i in f.items), f.items


def test_the_open_ceiling_fires_when_it_is_exceeded(monkeypatch):
    """The ceiling ratchets down only, so an eighth open finding must fail the build, not print an 8."""
    monkeypatch.setattr(cp, "MAX_OPEN_ADJUDICATIONS", N_OPEN - 1)
    result = cp.adjudicate()
    assert any("open finding(s) against a ceiling" in i for i in result["findings"].items)


def test_the_gate_exits_two_not_one_on_a_violation(tmp_path, capsys):
    """Exit 1 is a traceback in this repo, and must never be readable as one violation."""
    mutant = _ledger_to(tmp_path / "practices.yaml",
                        {"schema": cp.SCHEMA, "adjudicated_on": "2026-08-23",
                         "adjudicated_against": {"register": "x"},
                         "citation_adjudications": [{"case": "F0-1", "asserted": "TRUE",
                                                     "where": "9.9", "disposition": "LEGAL_PER_METRIC",
                                                     "why": "y" * (cp.MIN_WHY + 1),
                                                     "evidence": "e" * (cp.MIN_EVIDENCE + 1),
                                                     "span_must_contain": {"en": "no such sentence here",
                                                                           "zh": "文件中沒有這個句子"}}]})
    assert cp.main(["--practices", str(mutant)]) == 2
    assert cp.main([]) == 0
