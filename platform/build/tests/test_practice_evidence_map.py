"""Re-derive every number `results/PRACTICE-EVIDENCE-MAP.md` states.

WHY THE DOCUMENT CARRIES A MACHINE BLOCK AT ALL

A number inside a sentence is unchecked (`feedback_prose_is_not_verified`), and this repository has
already been wrong that way: a register size hand-copied into three files was stale in all three, and a
deficiency count in the handover README was seven items behind. So the map states its numbers twice —
once as prose a reader can follow, and once as data this test re-derives from
`practices_source.extract_files()` and `check_practices.adjudicate()`. The prose is checked against the
block by review; the block is checked against the tree by this file.

WHY THE ASSERTION IS DICT EQUALITY AND NOT A LIST OF LOOKUPS

Equality is what makes the *coverage* of this test derivable rather than remembered. A per-key `assert`
list passes over any key someone adds later, which is how an unverified number ends up in a file whose
header says every number is verified (`feedback_unnumbered_is_uncounted`). Under equality, a new key
fails until this test knows how to derive it — the failure is the request to derive it.

WHAT THIS TEST DOES NOT DO

It does not check the prose. Nothing here can tell that a sentence says "seven" while the block says 8;
that is a review job, and the block is deliberately small enough to read beside the tables. What it does
guarantee is that no number in the block is a memory of a measurement.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import check_practices as cp  # noqa: E402
from check_controls import read_verdicts  # noqa: E402

MAP = REPO / "results" / "PRACTICE-EVIDENCE-MAP.md"
GATE_TESTS = Path(__file__).parent / "test_check_practices.py"
SCHEMA = "grx-practice-evidence-map/1"

# The four sections this test derives in full. `schema`, `note`, `derived_on` and
# `authoritative_for_tooling` are prose about the block rather than measurements of the tree.
DERIVED_SECTIONS = ("design", "citations", "adjudications", "gate")
PROSE_KEYS = {"schema", "authoritative_for_tooling", "note", "derived_on"}


@pytest.fixture(scope="module")
def machine():
    text = MAP.read_text(encoding="utf-8")
    blocks = re.findall(r"<!-- machine\n(.*?)\n-->", text, re.DOTALL)
    assert len(blocks) == 1, f"expected exactly one machine block, found {len(blocks)}"
    data = json.loads(blocks[0])
    assert data["schema"] == SCHEMA
    return data


@pytest.fixture(scope="module")
def derived():
    """The same two entry points the gate and the page use. No third derivation lives here."""
    result = cp.adjudicate()
    design = result["design"]
    registered, _ = read_verdicts()
    census = design["citation_census"]
    cited = set(census["cases"])
    loc = collections.Counter(a["where"] for a in design["assertions"])
    busiest, busiest_n = loc.most_common(1)[0]

    def marker_counts(pick):
        return {lang: pick(sorted(freq.items(), key=lambda kv: -kv[1]))
                for lang, freq in design["marker_frequency"].items()}

    disposition = collections.Counter(m["disposition"] for m in result["adjudications"])
    return {
        "design": {
            "n_practices": design["n_practices"],
            "n_sections": len(design["sections"]),
            "n_phases": len(design["phases"]),
            "hops": [s["hop"] for s in design["sections"] if s["hop"]],
            "sections_without_hop": [s["id"] for s in design["sections"] if not s["hop"]],
            "n_principles": len(design["principles"]),
            "n_anti_patterns": len(design["anti_patterns"]),
            "n_checklist_items": design["n_checklist_items"],
            "n_checklist_groups": len(design["checklist"]),
            "marker_frequency": marker_counts(lambda ranked: ranked[0][1]),
            "marker_runner_up_frequency": marker_counts(lambda ranked: ranked[1][1]),
        },
        "citations": {
            "n_citations": census["n_citations"],
            "n_distinct_cases": census["n_distinct"],
            "n_inside_a_practice": sum(len(p["cites"]) for p in design["practices"]),
            "n_practices_carrying_one": sum(1 for p in design["practices"] if p["cites"]),
            "n_assertions": design["n_assertions"],
            "n_assertion_locations": len(loc),
            "busiest_location": {"where": busiest, "n": busiest_n},
            "n_cited_outside_the_register": len(cited - registered),
            "uncited_registered_cases": sorted(registered - cited),
        },
        "adjudications": {
            "n_registered": result["n_registered"],
            "n_adjudicated": len(result["adjudications"]),
            "n_legal": sum(1 for m in result["adjudications"] if m["kind"] == "legal"),
            "n_open": len(result["open_findings"]),
            "open_ceiling": cp.MAX_OPEN_ADJUDICATIONS,
            "by_disposition": dict(sorted(disposition.items())),
            "open_register_items": sorted({m["register_item"] for m in result["open_findings"]}),
        },
        "gate": {
            "mutation_arms": len(re.findall(r"^def test_", GATE_TESTS.read_text(encoding="utf-8"),
                                            re.MULTILINE)),
        },
        "_findings": result["findings"].items,
    }


def test_the_gate_passes_before_any_number_is_compared(derived):
    """A map derived from a failing tree would describe a state nobody is looking at."""
    assert derived["_findings"] == []


@pytest.mark.parametrize("section", DERIVED_SECTIONS)
def test_the_stated_numbers_are_the_derived_numbers(machine, derived, section):
    assert machine[section] == derived[section], (
        f"results/PRACTICE-EVIDENCE-MAP.md's {section!r} block disagrees with the tree it describes")


def test_every_key_in_the_block_is_either_derived_or_prose(machine):
    """No number sits outside this test's reach. A key nobody derives is a claim nobody checks."""
    assert set(machine) == set(DERIVED_SECTIONS) | PROSE_KEYS


def test_the_open_findings_prose_names_the_register_item_the_block_names(machine):
    """The one cross-check between prose and data that can be made mechanically."""
    text = MAP.read_text(encoding="utf-8")
    for item in machine["adjudications"]["open_register_items"]:
        assert f"item {item}" in text, f"the block names register item {item} and the prose does not"


def test_the_map_states_no_rate(machine):
    """Same rule as the ledger and the audit page: denominators, never rates."""
    from check_controls import Findings

    f = Findings()
    cp.check_no_rate(MAP, f)
    # Exactly one, and it is `36 %` — quoted from CITATION-POLICY.md's own reason for withholding the
    # dimension, a share of a confidence interval rather than a share of practices. Asserting the count
    # is what stops this arm from passing on an empty findings list, which is the state it would report
    # if the detector or the path ever stopped working (`feedback_vacuous_test_check`).
    assert len(f.items) == 1, f.items
    assert "36 %" in f.items[0]
