#!/usr/bin/env python3
"""The metric tables F7-1/F7-2/F7-3 are scored against, and the counts DEV-P4-03 quotes.

Why this file exists
--------------------
`DEVIATIONS.md`'s DEV-P4-03 argues that eleven of twenty-nine documented metrics cannot be
exercised without abusing a shared AWS service, and its scope IS those two numbers. Prose is
not verified: someone adding a metric to a table in
`f7_observability/03_metrics_existence.py` would leave the deviation entry describing a scope
it no longer has, and nothing would fail. The entry states "the script asserts these counts at
import time", so this file exists to make that sentence load-bearing — and to prove the
assertion can actually fire, which is the part a passing check never shows on its own.

Three things are checked:

1. the derived counts equal the pinned ones (and therefore equal the entry's prose);
2. **mutation** — six deliberate table edits, each of which must be caught. A count check that
   cannot fail is decoration;
3. the invariants that make the exclusion list honest: every excluded metric carries a stated
   reason, every basis name is one of the four defined, and no case is left with nothing to
   score (which would make its verdict vacuous rather than TRUE).

Loaded by path under a module-level name constant so
`test_module_name_collisions.py` can statically resolve it — the phase scripts are not a
package and two by-path loads under the same name would silently share one module object.

    python3 lib/tests/test_f7_metric_tables.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

METRICS_MODULE_NAME = "grx_f7_03_metrics_existence"
METRICS_SRC = Path(__file__).resolve().parents[2] / "f7_observability" / "03_metrics_existence.py"


def _register(spec):
    """Execute a by-path module, with lib/ importable the way the script expects.

    The spec is built at the CALL SITE rather than from a `name` parameter here, so that
    `test_module_name_collisions.py` — which resolves the first argument of
    `spec_from_file_location` statically and cannot follow a parameter — can see this file's one
    fixed key, `METRICS_MODULE_NAME`, and check it against every other loader's. Verified
    2026-08-12: under the previous `_load(src, name)` shape the scan resolved NOTHING from this
    file, so a duplicate of that key would have gone unreported. The two mutation call sites
    below stay unresolvable by construction and are listed as such in that gate's UNRESOLVABLE
    table.
    """
    lib = str(Path(__file__).resolve().parents[1])
    if lib not in sys.path:
        sys.path.insert(0, lib)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _register(importlib.util.spec_from_file_location(
        METRICS_MODULE_NAME, METRICS_SRC))


def test_source_exists():
    assert METRICS_SRC.is_file(), f"{METRICS_SRC} is missing"


def test_derived_counts_match_the_pinned_ones(m):
    """The numbers DEV-P4-03 quotes are the numbers the tables actually contain."""
    got = m.metric_table_counts()
    for key, want in m.DEV_P4_03_COUNTS.items():
        assert got[key] == want, (
            f"{key}: tables give {got[key]!r}, DEV-P4-03 states {want!r}. Fix both together — "
            f"the deviation entry's scope is these numbers")


def test_import_time_assertion_passes_on_the_real_tables(m):
    m.assert_dev_p4_03_counts()          # must not raise


def test_the_specific_numbers_in_the_deviations_prose(m):
    """Pinned separately from the dict, because the prose states them one at a time.

    Two numbers in one sentence move independently. Deriving 29 and asserting 11 = 29 - 18
    would let a paired edit slip through, so each is checked against the tables directly.
    """
    got = m.metric_table_counts()
    assert got["documented_pairs"] == 29
    assert got["distinct_names"] == 28          # Invocations is documented in two namespaces
    assert got["excluded"] == 11
    assert got["scored"] == 18
    assert got["per_case"]["F7-1"] == {"documented": 15, "scored": 10}
    assert got["per_case"]["F7-2"] == {"documented": 7, "scored": 4}
    assert got["per_case"]["F7-3"] == {"documented": 7, "scored": 4}


def test_invocations_is_the_only_name_in_two_namespaces(m):
    """The 29-vs-28 gap has exactly one cause, and it is named in the deviation entry."""
    names = [nm for t in (m.GATEWAY_METRICS, m.POLICY_METRICS, m.GUARDRAIL_METRICS)
             for nm, _, _ in t]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert dupes == ["Invocations"], (
        f"the (namespace, metric)-pair count differs from the distinct-name count because of "
        f"{dupes}; DEV-P4-03 attributes it to Invocations alone")


def test_every_exclusion_carries_a_reason(m):
    for nm, basis, why in (m.GATEWAY_METRICS + m.POLICY_METRICS + m.GUARDRAIL_METRICS):
        if basis == m.EX_NONE:
            assert len(why) >= 40, f"{nm} is excluded on a {len(why)}-character reason"


def test_every_basis_is_one_of_the_four_defined(m):
    known = {m.EX_FRESH, m.EX_POLICY, m.EX_GUARDRAIL, m.EX_NONE}
    for nm, basis, _ in (m.GATEWAY_METRICS + m.POLICY_METRICS + m.GUARDRAIL_METRICS):
        assert basis in known, f"{nm} names an unknown basis {basis!r}"


def test_no_case_is_left_with_nothing_to_score(m):
    """A case whose every metric is excluded would publish a vacuous verdict."""
    for case, table in m.CASE_METRIC_TABLE.items():
        scored = [nm for nm, b, _ in table if b != m.EX_NONE]
        assert scored, f"{case} has no exercised metric, so its verdict would be vacuous"


def test_the_two_negative_controls_are_not_in_any_scored_table(m):
    """`FirstByteLatency` is the document's own negative claim; scoring it would invert it."""
    names = {nm for t in (m.GATEWAY_METRICS, m.POLICY_METRICS, m.GUARDRAIL_METRICS)
             for nm, _, _ in t}
    assert m.CONTROL_ABSENT_NAME not in names, (
        f"{m.CONTROL_ABSENT_NAME} is a metric the document says does NOT exist; it must be a "
        f"control, never a metric expected to publish")
    assert m.CONTROL_WRONG_NS != m.NS_GUARDRAILS


# --------------------------------------------------------------------------------------
# The two one-directional gates in `_score`. Both were bidirectional once, and both
# discarded readings in the direction they had no business touching (DEV-P4-03, DEV-P4-04).
# --------------------------------------------------------------------------------------

def _score_one(m, *, has_dp: bool, trusted: bool, basis: str, in_inv: bool = True):
    """Run `_score` over a single fabricated metric row and return it."""
    read = {"has_datapoints": has_dp, "n_series": 1 if has_dp else 1,
            "n_datapoints": 200 if has_dp else 0, "sum": 80.0 if has_dp else None,
            "trusted": trusted,
            "why_untrusted": "" if trusted else "CloudWatch reported the result as incomplete"}
    win = {"per_metric": {"M": read}, "all_reads_trusted": trusted}
    inv = {"names": {"M": []} if in_inv else {}, "dimension_values": {}}
    sc = m._score("F7-X", (("M", basis, "x" * 60),), win, win, inv, {basis: True}, ("scope",))
    return sc, sc["rows"][0]


def test_truncation_does_not_invalidate_a_presence(m):
    """Run 3's error: `AllowDecisions` returned 200 datapoints under a `Paginated` status.

    A partial read can omit datapoints; it cannot fabricate them. So the guard must let this
    metric score, while still recording that the read itself was not trusted.
    """
    sc, row = _score_one(m, has_dp=True, trusted=False, basis=m.EX_FRESH)
    assert row["published"] is True
    assert row["read_trusted"] is False, "the untrusted read must still be recorded as such"
    assert row["absence_rests_on_untrusted_read"] is False
    assert sc["untrusted_metrics"] == ["M"]
    assert sc["untrusted_absences"] == []
    assert sc["absences_are_from_trusted_reads"] is True, (
        "a truncated PRESENCE must not withhold the verdict — that is what run 3 did to F7-1 "
        "and F7-2")


def test_truncation_does_invalidate_an_absence(m):
    """The other half: run 1 scored a truncated empty read as a document defect."""
    sc, row = _score_one(m, has_dp=False, trusted=False, basis=m.EX_FRESH)
    assert row["published"] is False
    assert row["absence_rests_on_untrusted_read"] is True
    assert sc["untrusted_absences"] == ["M"]
    assert sc["absences_are_from_trusted_reads"] is False, (
        "an absence read off a partial response must block the verdict")


def test_a_trusted_absence_still_scores_false(m):
    """The gate must not swallow real absences, which are the findings this family exists for."""
    sc, _ = _score_one(m, has_dp=False, trusted=True, basis=m.EX_FRESH)
    assert sc["absent"] == ["M"]
    assert sc["absences_are_from_trusted_reads"] is True
    assert sc["all_scored_published"] is False


def test_the_exercise_basis_gates_only_absence(m):
    """DEV-P4-03's corrected rule, pinned in both directions."""
    _, published = _score_one(m, has_dp=True, trusted=True, basis=m.EX_NONE)
    assert published["counted_in_conjunction"] is True, (
        "a metric that published must be scored whatever its exercise basis")
    sc_absent, absent = _score_one(m, has_dp=False, trusted=True, basis=m.EX_NONE)
    assert absent["counted_in_conjunction"] is False
    assert [e["metric"] for e in sc_absent["excluded_not_exercised"]] == ["M"]


# --------------------------------------------------------------------------------------
# Mutation run: prove the count check can fail.
# --------------------------------------------------------------------------------------

DRIFT = "metric table drift"
RATIONALE = "stated rationale"
UNKNOWN_BASIS = "unknown exercise basis"

MUTANTS = (
    ("add a gateway metric",
     '("Latency", EX_FRESH, "published for any gateway request"),',
     '("Latency", EX_FRESH, "published for any gateway request"),\n'
     '    ("Bogus", EX_FRESH, "a metric that is not in the document at all"),',
     DRIFT),
    ("drop a gateway metric",
     '("Duration", EX_FRESH, "published for any gateway request"),', '', DRIFT),
    ("silently un-exclude Throttles (the DoS-shaped one)",
     '("Throttles", EX_NONE,', '("Throttles", EX_FRESH,', DRIFT),
    ("silently exclude a metric that IS exercised",
     '("AllowDecisions", EX_POLICY,', '("AllowDecisions", EX_NONE,', DRIFT),
    ("move a guardrail metric out of scoring",
     '("TextUnitCount", EX_GUARDRAIL,', '("TextUnitCount", EX_NONE,', DRIFT),
    ("exclude a metric with no stated reason",
     '("SuppressOutputs", EX_NONE,\n     "requires a policy with the suppressOutput effect. No '
     'such policy was created by any "\n     "phase of this project, so an absence here would '
     'measure our plan, not the document"),',
     '("SuppressOutputs", EX_NONE, "n/a"),', RATIONALE),
    ("typo a basis name so a metric is neither scored nor excluded",
     '("GuardrailLatency", EX_POLICY,', '("GuardrailLatency", "PROJECT_POLICYY",',
     UNKNOWN_BASIS),
)


@pytest.mark.parametrize("label,find,replace,expect", MUTANTS, ids=[x[0] for x in MUTANTS])
def test_mutant_is_caught(tmp_path, label, find, replace, expect):
    """Each table edit must make the import-time assertion raise, for its OWN reason.

    Asserting merely "something raised" would pass even if one check masked all the others —
    which is exactly what happened while the real tables still held a 32-character exclusion
    reason: every mutant load raised before its mutation could matter, and the whole run was
    vacuous while reporting green. So each mutant names the check it must trip.

    The mutated copy is imported under a per-mutant private name, so no mutation can leak into
    the module object the rest of this file uses.
    """
    src = METRICS_SRC.read_text()
    assert find in src, f"mutation {label!r} does not apply: its anchor is not in the source"
    mutated = src.replace(find, replace, 1)
    assert mutated != src
    dst = tmp_path / "mutant.py"
    dst.write_text(mutated)

    name = f"_mutant_{abs(hash(label))}"
    try:
        with pytest.raises(RuntimeError) as exc:
            _register(importlib.util.spec_from_file_location(name, dst))
        msg = str(exc.value)
        assert expect in msg, (
            f"mutation {label!r} raised, but not from the check it targets ({expect!r}); "
            f"got: {msg}")
    finally:
        sys.modules.pop(name, None)


def test_the_unmutated_source_imports_clean(tmp_path):
    """The control for the mutation run above.

    If the pristine source itself raised, every mutant would be "caught" for a reason unrelated
    to its mutation and the run would prove nothing.
    """
    dst = tmp_path / "control.py"
    dst.write_text(METRICS_SRC.read_text())
    name = "_control_metrics_module"
    try:
        _register(importlib.util.spec_from_file_location(name, dst))
    finally:
        sys.modules.pop(name, None)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
