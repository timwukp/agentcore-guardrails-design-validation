"""`phase1.require_measured` — the gate that turns a shortfall into an exit code.

Context: DEVIATIONS.md/DEV-P1-11. On 2026-08-10 an ~80 s local network outage killed 3,378
of 3,464 Phase 1 trials. Every arm still held the two or three trials it had completed
before the outage, so the gate's only condition — `n_usable > 0` — held, and all six F3
scripts exited **rc=0** and wrote verdicts: F3-1 published TRUE from **15 usable trials
against a pre-registered 87**, F3-2 and F3-3 reached INCONCLUSIVE from 3.

Nothing lied. `n_usable=15`, `n_met=False`, the `failure_codes` list and a note that the
interval was wider than the design promised were all recorded faithfully. The defect is
that **a shortfall reported beside a verdict is a verdict**: rc=0 is the signal a batch
driver reads, and a downstream analysis step keyed on the exit code would have consumed
those numbers as finished work.

So the arms here are written against the failure the old gate let through, not against the
happy path:

* the exact shape of the real incident (15/87 and 3/120) must now be rc=2
* per arm as well as pooled, because **a total cannot see an empty part** — the same defect
  as `n_usable` being the sum of two denominators in `oracle._decide`
* a smoke run must stay rc=0, or `--n 3` becomes unusable as plumbing proof
* the threshold has to be load-bearing in both directions: just-above passes, just-below
  fails, so a hardcoded `return 0` or `return 2` cannot pass this file
* the message must name the arms and the resume path, because an exit code that does not
  say what to do next gets suppressed rather than fixed
"""

from __future__ import annotations

import pytest

import phase1 as P


def arm(name: str, usable: int, attempted: int, *, x: int = 0,
        codes: list[str] | None = None) -> dict:
    """A tally in the shape `arms.tally` produces — the keys `_counts` actually reads."""
    return {"case_id": "F3-1", "arm": name, "planned_n": attempted,
            "n_attempted": attempted, "n_usable": usable, "x": x,
            "n_failed": attempted - usable,
            "failure_codes": codes if codes is not None else
            (["EndpointConnectionError"] if usable < attempted else [])}


# ------------------------------------------------------------------ the incident

def test_the_real_incident_now_fails(capsys):
    """15 usable out of a pre-registered 87 — the run that published TRUE at rc=0."""
    rc = P.require_measured([arm("HIGH", 15, 87)])
    assert rc == 2, "a verdict from 17% of the designed sample is not a measurement"
    err = capsys.readouterr().err
    assert "15/87" in err
    assert "EndpointConnectionError" in err, "the cause must travel with the refusal"


def test_the_other_half_of_the_incident_also_fails():
    """F3-2/F3-3 reached INCONCLUSIVE from 3 of 120. INCONCLUSIVE is still a verdict."""
    assert P.require_measured([arm("main", 3, 120)]) == 2


# ------------------------------------------------- pooled cannot hide an empty arm

def test_a_single_empty_arm_fails_even_when_the_pool_looks_healthy(capsys):
    """Eleven healthy arms and one empty one pool to ~92% — above the threshold.

    This is the arm that justifies checking per-arm at all. The empty arm is not a
    rounding error: it is a stratum an oracle divides by (`oracle._decide`'s two-interval
    kinds take `detect_n` and `fpr_n` separately), so a pooled-only gate would hand
    INDISTINGUISHABLE a 0/0 side while reporting the run as complete.
    """
    tallies = [arm(f"lang-{i}", 60, 60) for i in range(11)] + [arm("lang-x", 0, 60)]
    pooled = sum(t["n_usable"] for t in tallies) / sum(t["n_attempted"] for t in tallies)
    assert pooled > P.MIN_COMPLETION, f"fixture must exercise the pooled blind spot ({pooled:.3f})"

    assert P.require_measured(tallies) == 2
    err = capsys.readouterr().err
    assert "lang-x" in err, "the offending arm must be named, not just counted"
    assert "0/60" in err


def test_there_is_no_pooled_shortfall_the_per_arm_check_can_miss():
    """The converse direction, and the reason the gate does NOT also test the pool.

    The first version checked `bad or pooled < min_completion`. That pooled half was
    **unreachable**, and the mutation run found it: deleting it changed no result. The
    proof is one line of algebra — with `f_i = u_i/a_i` and weights `a_i`,
    `pooled = Σ(a_i·f_i)/Σa_i` is a weighted mean of the per-arm fractions, and a weighted
    mean of numbers all `>= t` is itself `>= t`.

    So this arm asserts the implication rather than a redundant guard: over a wide sweep of
    arm shapes, every run whose non-empty arms all clear the floor has a pooled fraction
    that clears it too. If a future edit weakens the per-arm loop — exempting small arms,
    say — the implication breaks here and this arm says the pooled guard must come back.
    """
    t = P.MIN_COMPLETION
    worst = 1.0
    shapes = (1, 3, 6, 60, 87, 100, 120, 2190)
    # Every arm at its worst passing value is the extremal case; mixing sizes cannot push
    # a weighted mean below the minimum of its terms, so the sweep is over compositions.
    for a1 in shapes:
        for a2 in shapes:
            for a3 in (0,) + shapes:      # include an attempted-nothing arm
                tallies = []
                for att in (a1, a2, a3):
                    if att == 0:
                        tallies.append(arm("empty", 0, 0))
                        continue
                    import math
                    u = math.ceil(att * t)          # the smallest passing count
                    tallies.append(arm(f"a{att}", u, att))
                assert P.require_measured(tallies) == 0, tallies
                n_u = sum(x["n_usable"] for x in tallies)
                n_a = sum(x["n_attempted"] for x in tallies)
                worst = min(worst, n_u / n_a)
    assert worst >= t, (
        f"found a pooled fraction {worst} below the floor while every arm passed — the "
        f"pooled guard is NOT redundant and must be restored in require_measured")


# ------------------------------------------------------------ the threshold is real

@pytest.mark.parametrize("usable,expect", [(90, 0), (89, 2), (100, 0)])
def test_the_threshold_is_load_bearing_in_both_directions(usable: int, expect: int):
    """Just-above passes and just-below fails, so neither constant answer can pass."""
    assert P.require_measured([arm("a", usable, 100)]) == expect


def test_the_default_threshold_is_the_documented_one():
    """0.90, matching the comment's arithmetic: an 87-item cell keeps >= 79.

    Pinned because the number is a pre-registration-adjacent commitment: the comment
    reasons about where the rule-of-three bound lands at this fraction, and a silent
    change to 0.5 would leave that reasoning describing a gate that no longer exists.
    """
    assert P.MIN_COMPLETION == 0.90
    assert P.require_measured([arm("a", 79, 87)]) == 0
    assert P.require_measured([arm("a", 78, 87)]) == 2


# ------------------------------------------------------------------- smoke is exempt

def test_a_smoke_run_is_not_held_to_the_completion_floor():
    """A 3-item arm losing one trial is 67%, and the smoke path's job is plumbing proof.

    Its results are never reported — `is_smoke` travels in the checkpoint metadata for
    exactly that reason — so failing it here would make `--n 3` unusable as the pre-flight
    the dry-run discipline requires.
    """
    assert P.require_measured([arm("a", 2, 3)], is_smoke=True) == 0
    assert P.require_measured([arm("a", 2, 3)], is_smoke=False) == 2


def test_a_smoke_run_that_measured_nothing_still_fails():
    """The exemption is from the *floor*, not from the original zero check.

    A smoke run with no usable trials proved nothing about the plumbing, which is the one
    thing it exists to prove.
    """
    assert P.require_measured([arm("a", 0, 3)], is_smoke=True) == 2


# ---------------------------------------------------------------------- edge shapes

def test_zero_usable_across_every_arm_fails_with_the_zero_message(capsys):
    assert P.require_measured([arm("a", 0, 60), arm("b", 0, 60)]) == 2
    assert "zero usable trials" in capsys.readouterr().err


def test_an_arm_that_attempted_nothing_is_skipped_not_divided_by():
    """`n_attempted == 0` must not raise ZeroDivisionError.

    It happens for real: a language arm whose corpus filter matched no items. The pooled
    check still governs, so an all-zero-attempt run cannot pass through this door.
    """
    assert P.require_measured([arm("a", 60, 60), arm("empty", 0, 0)]) == 0
    assert P.require_measured([arm("empty", 0, 0)]) == 2


def test_a_healthy_full_run_passes():
    """The happy path, last: it is one line and would pass against a stub."""
    assert P.require_measured([arm("a", 87, 87, x=80), arm("b", 87, 87, x=4)]) == 0


def test_the_refusal_reports_the_run_level_size_and_every_failure_code(capsys):
    """The pooled figure and the code union are reporting, and both must survive edits.

    The pooled fraction is no longer a *gate* (see the docstring's derivation) but it is
    still what a reader triaging the refusal reads first: "3% of the run" and "90% of the
    run" call for different responses. The union of codes across arms is what distinguishes
    the DEV-P1-11 shape — one transport code everywhere, i.e. an outage — from scattered
    throttling, which needs a rate change rather than a retry.

    The union is asserted on a code carried by an arm that **passed** the floor, because a
    failing arm's codes are already printed on its own row: a version that dropped the union
    would still show those, and an arm asserting only them would pass against it. A
    surviving-arm code is the one piece of triage information that exists nowhere else — it
    is what says "this hit the whole run", i.e. an outage, rather than "this arm was
    unlucky".
    """
    tallies = [arm("HIGH", 15, 87, codes=["EndpointConnectionError"]),
               arm("LOW", 84, 87, codes=["ThrottlingException"])]   # LOW = 96.6%, passes
    assert P.require_measured(tallies) == 2
    err = capsys.readouterr().err
    assert "pooled 99/174" in err
    assert "56.9%" in err, "the run-level fraction, not just the raw counts"
    assert "EndpointConnectionError" in err
    assert "ThrottlingException" in err, (
        "a code from an arm that PASSED the floor appears only in the pooled union; without "
        "it a reader cannot tell a whole-run outage from one unlucky arm")
    # And the passing arm is not listed as an offender: only HIGH's row is printed.
    rows = [ln for ln in err.splitlines() if ln.strip().startswith("arm ")]
    assert len(rows) == 1 and "HIGH" in rows[0], rows


def test_the_refusal_tells_the_reader_how_to_resume(capsys):
    """An exit code that does not say what to do next gets suppressed rather than fixed.

    The resume path is the reason a shortfall can be fatal without being expensive: the
    checkpoint keys on the item, so re-running the same --run-id re-sends only the missing
    trials and re-bills nothing.
    """
    P.require_measured([arm("HIGH", 15, 87)])
    err = capsys.readouterr().err
    assert "--run-id" in err
    assert "re-billed" in err or "re-bill" in err
