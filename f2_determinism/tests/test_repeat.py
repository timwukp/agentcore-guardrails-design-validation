"""F2-5's fingerprint and summary functions, tested by mutation.

F2-5 reduces 300 responses to one integer — the number of distinct fingerprints — and hands it
to a `DISTINCT_AT_LEAST` oracle with threshold 2. Everything therefore rests on the fingerprint
being exactly as wide as the decision and no wider, and the two failure directions are not
symmetric:

* **Too wide → TRUE by construction.** Latency, request id and text-unit counters vary across
  byte-identical calls for reasons that are not verdicts. Including any of them would make "the
  service is non-deterministic" true of every possible run, which is the vacuous-test defect
  (feedback_vacuous_test_check). Since TRUE is the direction that confirms the document, this is
  the dangerous one.
* **Too narrow → a missed real difference.** A fingerprint reading only `action` would call a
  changed confidence level identical.

So the suite asserts both: that each excluded field cannot move the count, and that each
included field can. Plus the two structural traps the code documents:

* the sorted-**type** construction, because `sorted()` over dicts raises `TypeError` on any
  response with two detected filters — i.e. on the interesting responses only, never on the
  trivial ones a smoke run produces;
* distinct trial ids per replicate, because `arms.run_arm` skips ids the checkpoint holds, so
  300 copies sharing an id would send one call and report 300 — a FALSE manufactured by the
  resume logic.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "f2_determinism" / "01_repeat.py"
    spec = importlib.util.spec_from_file_location("f2_repeat", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


# --------------------------------------------------------------------------- helpers

def row(**over) -> dict:
    """A trial row in `arms.run_arm`'s shape, with the fields F2-5 reads."""
    base = {
        "id": "t0",
        "action": "NONE",
        "action_reason": "",
        "detected_types": [],
        "blocked_types": [],
        "confidences": {},
        "topics_detected": [],
        "words_detected": [],
        "pii_detected": [],
        "text_units": {"contentPolicyUnits": 1},
        "coverage": {"textCharacters": {"guarded": 100, "total": 100}},
        "guardrail_latency_ms": 42,
    }
    base.update(over)
    return base


# ------------------------------------------------------- the fingerprint is stable

def test_identical_rows_fingerprint_identically():
    assert M.fingerprint(row()) == M.fingerprint(row())


def test_fingerprint_is_json_and_key_ordered():
    """Key order is not documented as stable, and an ordering difference is not a verdict
    difference. Without `sort_keys` the case would report a TRUE about JSON serialisation."""
    fp = M.fingerprint(row(detected_types=["VIOLENCE"], confidences={"VIOLENCE": "HIGH"}))
    assert json.loads(fp)
    assert fp == json.dumps(json.loads(fp), sort_keys=True, separators=(",", ":"))


def test_filter_order_does_not_change_the_fingerprint():
    """The response's filter order is not documented as stable either."""
    a = row(detected_types=["VIOLENCE", "HATE"],
            confidences={"VIOLENCE": "HIGH", "HATE": "LOW"})
    b = row(detected_types=["HATE", "VIOLENCE"],
            confidences={"HATE": "LOW", "VIOLENCE": "HIGH"})
    assert M.fingerprint(a) == M.fingerprint(b)


def test_two_detected_filters_do_not_raise():
    """The sorted-TYPE construction, pinned.

    `sorted(<generator of dicts>)` raises TypeError because dicts do not compare — and it
    would do so only on responses with two or more detected filters, which is exactly the
    interesting case and never the trivial one a `--n 3` smoke run produces. A crash here
    would arrive 300 calls into a paid run.
    """
    r = row(detected_types=["VIOLENCE", "HATE", "INSULTS"],
            confidences={"VIOLENCE": "HIGH", "HATE": "HIGH", "INSULTS": "MEDIUM"},
            blocked_types=["VIOLENCE", "HATE"])
    assert M.fingerprint(r)


# ------------------------------------------------- included fields CAN move the count

@pytest.mark.parametrize("field,value", [
    ("action", "GUARDRAIL_INTERVENED"),
    ("action_reason", "content policy"),
    ("detected_types", ["VIOLENCE"]),
    ("topics_detected", ["Investment Advice"]),
    ("words_detected", ["moonquake"]),
    ("pii_detected", ["EMAIL"]),
])
def test_a_decision_field_changes_the_fingerprint(field, value):
    """Too narrow is the other failure direction: a real difference reported as identical."""
    assert M.fingerprint(row(**{field: value})) != M.fingerprint(row())


def test_confidence_change_alone_changes_the_fingerprint():
    """`confidence` is the nearest thing the API has to a score, and the oracle says
    "verdict or score". A fingerprint blind to it would answer a narrower question."""
    a = row(detected_types=["VIOLENCE"], confidences={"VIOLENCE": "HIGH"})
    b = row(detected_types=["VIOLENCE"], confidences={"VIOLENCE": "LOW"})
    assert M.fingerprint(a) != M.fingerprint(b)


def test_blocked_change_alone_changes_the_fingerprint():
    """`detected` is what the classifier said; `blocked` is what the config did. Separate
    facts, and a change in either is a change in the decision surface."""
    a = row(detected_types=["VIOLENCE"], blocked_types=["VIOLENCE"])
    b = row(detected_types=["VIOLENCE"], blocked_types=[])
    assert M.fingerprint(a) != M.fingerprint(b)


# ---------------------------------------------- excluded fields CANNOT move the count

@pytest.mark.parametrize("field,value", [
    ("guardrail_latency_ms", 99999),
    ("text_units", {"contentPolicyUnits": 7}),
    ("coverage", {"textCharacters": {"guarded": 1, "total": 1}}),
    ("id", "a-completely-different-trial-id"),
])
def test_a_non_decision_field_does_not_change_the_fingerprint(field, value):
    """Each of these varies across byte-identical calls for reasons that are not verdicts.

    Latency is continuous and essentially never repeats: including it would make the verdict
    TRUE for every possible run, so the case would confirm §3.3 from an artefact.
    """
    assert M.fingerprint(row(**{field: value})) == M.fingerprint(row())


def test_the_exclusions_are_documented_as_data():
    """`FINGERPRINT_EXCLUSIONS` travels into the result file, so the exclusions are auditable
    rather than asserted. An exclusion with no stated reason is indistinguishable from an
    oversight."""
    for key, why in M.FINGERPRINT_EXCLUSIONS.items():
        assert why.strip(), f"{key} is excluded with no reason"
    # The four fields that vary across byte-identical calls must each be named. Matched on
    # the whole key set rather than per-key substring so a renamed key fails here instead of
    # silently dropping an exclusion from the audit trail.
    keys = {k.lower() for k in M.FINGERPRINT_EXCLUSIONS}
    assert any("latency" in k for k in keys)
    assert any("usage" in k or "text_units" in k for k in keys)
    assert any("requestid" in k for k in keys)
    assert any("coverage" in k for k in keys)
    assert len(M.FINGERPRINT_EXCLUSIONS) >= 4


# ------------------------------------------------------------------- repeated_items

def test_repeated_items_have_distinct_ids():
    """`arms.run_arm` skips known ids. Shared ids would send ONE call and report n done —
    a FALSE verdict manufactured by the resume logic rather than observed."""
    items = M.repeated_items({"id": "src", "text": "hello", "label": "X"}, 300, tag="main")
    assert len(items) == 300
    assert len({i["id"] for i in items}) == 300


def test_repeated_items_send_identical_text():
    """The whole design: identical bytes on every trial. A varying text would make any
    difference a statement about the inputs."""
    items = M.repeated_items({"id": "src", "text": "hello", "label": "X"}, 20, tag="main")
    assert len({i["text"] for i in items}) == 1


def test_repeated_items_are_stable_across_calls():
    """Ids are content hashes, not counters, so a resumed run re-derives the same ids."""
    a = M.repeated_items({"id": "s", "text": "t", "label": "X"}, 10, tag="main")
    b = M.repeated_items({"id": "s", "text": "t", "label": "X"}, 10, tag="main")
    assert [i["id"] for i in a] == [i["id"] for i in b]


def test_the_two_arms_cannot_collide():
    """The companion arm repeats a different item; if the tag did not enter the hash, the two
    arms' ids would collide and the checkpoint would serve one arm's rows to the other."""
    a = M.repeated_items({"id": "s", "text": "t", "label": "X"}, 10, tag="main")
    b = M.repeated_items({"id": "s", "text": "t", "label": "X"}, 10, tag="companion")
    assert not ({i["id"] for i in a} & {i["id"] for i in b})


def test_trial_index_and_arm_tag_are_carried():
    """Both are needed to attribute a row to an arm and a position after the fact."""
    items = M.repeated_items({"id": "s", "text": "t", "label": "X"}, 5, tag="main")
    assert [i["trial_index"] for i in items] == [0, 1, 2, 3, 4]
    assert {i["arm_tag"] for i in items} == {"main"}
    assert {i["source_item_id"] for i in items} == {"s"}


# ----------------------------------------------------------------------- summarise

def test_identical_rows_yield_one_fingerprint():
    s = M.summarise([row() for _ in range(300)])
    assert s["n_rows"] == 300
    assert s["n_distinct_fingerprints"] == 1
    assert s["bijection_check"]["equal"] is True


def test_one_differing_row_yields_two():
    """The oracle's threshold is 2 distinct values, because ">=1 differing" means two."""
    rows = [row() for _ in range(299)] + [row(action="GUARDRAIL_INTERVENED")]
    s = M.summarise(rows)
    assert s["n_distinct_fingerprints"] == 2


def test_latency_variation_alone_yields_one():
    """The vacuity guard, end to end: 300 different latencies must not read as 300 verdicts."""
    rows = [row(guardrail_latency_ms=i) for i in range(300)]
    s = M.summarise(rows)
    assert s["n_distinct_fingerprints"] == 1
    assert s["latency_ms"]["distinct"] == 300
    assert s["latency_ms"]["n"] == 300


def test_the_codebook_is_a_bijection():
    """The oracle counts distinct FLOATS. If the coding were not a bijection with the
    fingerprints, the verdict would be about the coding and not about the service."""
    rows = [row(), row(action="GUARDRAIL_INTERVENED"), row(detected_types=["HATE"])]
    s = M.summarise(rows)
    assert s["bijection_check"]["equal"] is True
    assert len(s["fingerprint_codebook"]) == s["n_distinct_fingerprints"] == 3
    assert len(set(s["codes"])) == 3


def test_codes_are_floats_for_the_distinct_oracle():
    s = M.summarise([row(), row(action="GUARDRAIL_INTERVENED")])
    assert all(isinstance(c, float) for c in s["codes"])


def test_fingerprint_counts_sum_to_n_rows():
    """A count that did not reconcile to its parent would be a second label over the same
    computation (feedback_label_must_match_computation)."""
    rows = [row() for _ in range(10)] + [row(action="GUARDRAIL_INTERVENED")] * 3
    s = M.summarise(rows)
    assert sum(s["fingerprint_counts"].values()) == s["n_rows"] == 13


def test_varying_text_units_is_flagged_as_a_fault_not_a_verdict():
    """Identical input, so a varying unit count is a billing finding (F10-2's subject) or an
    instrument fault. Counting it as a differing verdict would confirm §3.3 from an artefact."""
    rows = [row(text_units={"contentPolicyUnits": 1}) for _ in range(5)]
    rows[0]["text_units"] = {"contentPolicyUnits": 2}
    s = M.summarise(rows)
    assert s["n_distinct_fingerprints"] == 1
    assert s["instrument_faults"]["text_units_varied"] is True


def test_varying_coverage_is_flagged_as_a_fault():
    rows = [row() for _ in range(5)]
    rows[0]["coverage"] = {"textCharacters": {"guarded": 50, "total": 100}}
    s = M.summarise(rows)
    assert s["n_distinct_fingerprints"] == 1
    assert s["instrument_faults"]["coverage_varied"] is True


def test_no_fault_is_reported_on_uniform_rows():
    """Mutation check on the fault flags: a guard that always fires is not a guard."""
    s = M.summarise([row() for _ in range(5)])
    assert s["instrument_faults"]["text_units_varied"] is False
    assert s["instrument_faults"]["coverage_varied"] is False


def test_latency_summary_survives_all_none():
    """A guardrail response without `invocationMetrics` yields no latency. The summary must
    report absence rather than raising on min() of an empty sequence — mid-run, after spend."""
    s = M.summarise([row(guardrail_latency_ms=None) for _ in range(5)])
    assert s["latency_ms"]["n"] == 0
    assert s["latency_ms"]["p50"] is None
    assert s["latency_ms"]["min"] is None


# ------------------------------------------------------------------ seal fidelity

def test_the_sealed_oracle_is_distinct_at_least_two():
    """The threshold is 2, not 1: the prose says ">=1 differing" and one difference means two
    distinct values. A threshold of 1 would be satisfied by a single response."""
    import oracle as O
    b = O.BINDINGS[M.CASE]
    assert b.kind == "DISTINCT_AT_LEAST"
    assert b.thresholds == (2.0,) or b.thresholds == (2,)
    assert O.planned_n(M.CASE) == 300


def test_the_companion_arm_is_not_part_of_the_sealed_n():
    """The oracle is evaluated on the main arm alone; pooling would change the sealed n."""
    assert M.COMPANION_N < 300
