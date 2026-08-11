"""`phase1.dry_run_banner` — the last checkpoint before money is spent.

A dry-run banner is the only artefact a reader sees *before* the spend, so a wrong number in it
is not cosmetic: it is the projection the phase budget is approved against. Three of its
arguments (`operations`, `mutations`, `billable`) exist because the first version hard-coded
them and mislabelled F8-4's and F8-5's plans; a fourth (`text_units`) exists because the default
one-unit-per-block estimate is wrong by construction for F10-2, the one case whose subject IS
the text-unit count.

What is tested here is the arithmetic and the refusals, not the wording:

* **The operation breakdown must sum to the plan.** A breakdown that disagreed would be a second
  label over the same computation — the `feedback_label_must_match_computation` defect.
* **A text-unit override needs a stated basis.** Per feedback_prose_is_not_verified, a number
  that replaces a derived one without saying how it was derived is unverified prose, and this is
  the one place a script can substitute its own cost figure.
* **`billable=False` must not print a unit projection**, because control-plane calls bill no text
  units and a projection there would inflate the phase estimate with units that cannot exist.
* **The sealed oracle, kind, alpha and n come from the seal**, so a case cannot print a
  reassuring question next to a different instrument.

`capsys` is used rather than mocking `print`: the assertion is about what a reader sees.
"""

from __future__ import annotations

import pytest

import oracle as O
import phase1 as P


CASE = "F10-2"          # the case the text-unit override was added for
PLAN = [("ladder", "constructed ladder", 27)]


def test_returns_zero_so_a_dry_run_never_reports_failure(capsys):
    assert P.dry_run_banner(CASE, PLAN) == 0
    capsys.readouterr()


def test_prints_the_sealed_oracle_kind_and_alpha(capsys):
    P.dry_run_banner(CASE, PLAN)
    out = capsys.readouterr().out
    assert O.BINDINGS[CASE].kind in out
    assert O.oracle_text(CASE)[:40] in out
    assert str(O.alpha_for(CASE)) in out


def test_prints_the_arm_total_and_every_arm(capsys):
    P.dry_run_banner(CASE, [("a", "c1", 10), ("b", "c2", 7)])
    out = capsys.readouterr().out
    assert "total calls: 17" in out
    assert "arms (2):" in out
    # Every arm listed, not just the first: an unlisted arm is unprojected spend.
    assert "n=10" in out and "n=7" in out


# --------------------------------------------------------- the operation breakdown

def test_default_breakdown_is_apply_guardrail(capsys):
    P.dry_run_banner(CASE, PLAN)
    out = capsys.readouterr().out
    assert "ApplyGuardrail x27" in out
    assert "total calls: 27" in out


def test_a_multi_operation_breakdown_is_printed_in_full(capsys):
    P.dry_run_banner(CASE, [("a", "c", 690)],
                     operations={"ApplyGuardrail": 460, "InvokeGuardrailChecks": 230})
    out = capsys.readouterr().out
    assert "ApplyGuardrail x460" in out
    assert "InvokeGuardrailChecks x230" in out
    assert "total calls: 690" in out


def test_a_breakdown_that_does_not_sum_to_the_plan_is_refused():
    """The check that makes the breakdown evidence rather than a caption."""
    with pytest.raises(ValueError, match="operation breakdown sums to"):
        P.dry_run_banner(CASE, [("a", "c", 100)],
                         operations={"ApplyGuardrail": 60, "CreateGuardrail": 30})


def test_an_over_counting_breakdown_is_refused_too():
    """Both directions. An over-count inflates the projection; an under-count hides spend."""
    with pytest.raises(ValueError, match="operation breakdown sums to"):
        P.dry_run_banner(CASE, [("a", "c", 100)], operations={"ApplyGuardrail": 140})


# ------------------------------------------------------------- the text-unit override

def test_default_projection_is_blocks_times_calls(capsys):
    P.dry_run_banner(CASE, [("a", "c", 10)], blocks_per_call=3)
    out = capsys.readouterr().out
    assert "billable text-unit sources: ~30" in out


def test_an_override_replaces_the_default(capsys):
    P.dry_run_banner(CASE, PLAN, text_units=48,
                     text_units_why="sum of ceil(length/1000) over the ladder")
    out = capsys.readouterr().out
    assert "billable text-unit sources: ~48" in out
    assert "27" not in out.split("billable text-unit sources:")[1].split("\n")[0]


def test_an_override_with_no_stated_basis_is_refused():
    """The unverified-prose guard. A substituted cost figure must say where it came from."""
    with pytest.raises(ValueError, match="needs `text_units_why`"):
        P.dry_run_banner(CASE, PLAN, text_units=48)


@pytest.mark.parametrize("why", ("", None))
def test_an_empty_or_none_basis_is_refused(why):
    with pytest.raises(ValueError, match="needs `text_units_why`"):
        P.dry_run_banner(CASE, PLAN, text_units=48, text_units_why=why)


def test_the_basis_is_printed_so_a_reader_can_check_it(capsys):
    """A recorded basis nobody sees is the same as no basis."""
    why = "sum of ceil(length/1000) over the ladder — NOT one unit per call"
    P.dry_run_banner(CASE, PLAN, text_units=48, text_units_why=why)
    out = capsys.readouterr().out
    assert "text-unit basis:" in out
    assert why in out


def test_an_override_of_zero_is_honoured_not_treated_as_absent():
    """`if text_units:` would silently fall back to the default for a genuine zero.

    A case that provably consumes no text units — control-plane only, but still wanting the
    banner's billable framing — would then have its projection replaced by the call count.
    """
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        P.dry_run_banner(CASE, PLAN, text_units=0, text_units_why="control-plane only")
    assert "billable text-unit sources: ~0" in buf.getvalue()


def test_no_basis_line_is_printed_when_there_is_no_override(capsys):
    """The line must appear only where a substitution happened, or it means nothing."""
    P.dry_run_banner(CASE, PLAN)
    assert "text-unit basis:" not in capsys.readouterr().out


# ----------------------------------------------------------------------- billable

def test_billable_false_prints_no_unit_projection(capsys):
    """Control-plane calls bill no text units; projecting them would inflate the estimate."""
    P.dry_run_banner(CASE, [("a", "c", 4)], billable=False)
    out = capsys.readouterr().out
    assert "billable text units: 0" in out
    assert "billable text-unit sources" not in out


def test_billable_false_still_prints_the_call_total(capsys):
    """The calls happen and are rate-limited even though they bill no units."""
    P.dry_run_banner(CASE, [("a", "c", 4)], billable=False,
                     operations={"CreateGuardrail": 4})
    out = capsys.readouterr().out
    assert "total calls: 4" in out
    assert "CreateGuardrail x4" in out


# ----------------------------------------------------------------------- mutations

def test_zero_mutations_says_so_explicitly(capsys):
    P.dry_run_banner(CASE, PLAN)
    out = capsys.readouterr().out
    assert "mutations: 0" in out
    assert "no resource is created" in out


def test_a_nonzero_mutation_count_drops_the_reassurance(capsys):
    """"mutations: 4  (no resource is created…)" would be a contradiction printed as a fact."""
    P.dry_run_banner(CASE, [("a", "c", 4)], mutations=4, billable=False,
                     operations={"CreateGuardrail": 4})
    out = capsys.readouterr().out
    assert "mutations: 4" in out
    assert "no resource is created" not in out


# ------------------------------------------------------------------- seal fidelity

def test_a_case_with_a_sealed_n_prints_it(capsys):
    with_n = next(cid for cid in O.BINDINGS if O.planned_n(cid) is not None)
    P.dry_run_banner(with_n, [("a", "c", 1)])
    assert f"pre-registered n: {O.planned_n(with_n)}" in capsys.readouterr().out


def test_a_case_with_no_sealed_n_points_at_deviations(capsys):
    """Silence would read as "n = 0" or as an oversight; the pointer names where to look."""
    assert O.planned_n(CASE) is None
    P.dry_run_banner(CASE, PLAN)
    out = capsys.readouterr().out
    assert "none (see DEVIATIONS)" in out


def test_an_unknown_case_id_is_refused():
    with pytest.raises(KeyError):
        P.dry_run_banner("F99-9", PLAN)


def test_extra_lines_are_printed_after_the_plan(capsys):
    P.dry_run_banner(CASE, PLAN, extra=["SCOPE: no invoice is read"])
    out = capsys.readouterr().out
    assert "SCOPE: no invoice is read" in out
    assert out.index("total calls") < out.index("SCOPE:")
