"""F3-9's operating-point set, and the API constraint that shapes it.

Why this file exists
--------------------
`roc_points()` produces the numbers F3-9 publishes — the vertex count, Youden's J, its
argmax, whether that argmax is interior — and until now nothing tested it. That gap was not
theoretical: the strength lattice was changed from four settings to three, `interior`'s
definition was rewritten, and the whole 680-test offline suite stayed green. A published
figure with no arm behind it is the shape of `feedback_prose_is_not_verified` one level up.

The lattice is three settings because the service forbids the fourth. `CreateGuardrail`
rejects an all-NONE `contentPolicyConfig`:

    ValidationException: At least one content filter strength must be set to not NONE.

so the ROC's leftmost non-trivial vertex — configured, classifying nothing — cannot be
built. That is a measured property (probed three ways on 2026-08-10, recorded in
`P.UNREACHABLE_STRENGTHS`), and the arms here hold it to being *stated* rather than
silently absorbed into a smaller number.

The load-bearing arm is `test_interior_is_defined_against_endpoints_not_lattice_position`.
When NONE left the tuple, `STRENGTHS[0]` stopped meaning "the setting that classifies
nothing" and started meaning LOW, a real operating point. Any check still phrased as
"argmax is not at STRENGTHS[0]" would reject a perfectly good result — and it would reject
it as a *finding about the guardrail*, which is the worst available failure mode: a
harness bug wearing the costume of a measurement.

Offline, $0. Pure arithmetic on synthetic tallies; no manifest, no AWS.
"""

from __future__ import annotations

import phase1 as P
import pytest


def cell(tp: int, pos: int, fp: int, neg: int) -> dict:
    return {"tp": tp, "pos": pos, "fp": fp, "neg": neg}


def sweep(**by_strength: dict) -> dict:
    """Tallies keyed by strength, as `01_content_filter.py` builds them."""
    return dict(by_strength)


# A well-behaved sweep: recall rises with strength, so does FPR, and MEDIUM is the best J.
GOOD = sweep(
    LOW=cell(tp=50, pos=100, fp=2, neg=100),      # tpr .50  fpr .02  J .48
    MEDIUM=cell(tp=85, pos=100, fp=5, neg=100),   # tpr .85  fpr .05  J .80
    HIGH=cell(tp=95, pos=100, fp=40, neg=100),    # tpr .95  fpr .40  J .55
)


# ------------------------------------------------------- the lattice and its constraint

def test_the_lattice_is_exactly_the_buildable_strengths() -> None:
    """NONE must be absent, and the other three present in ascending order.

    Order matters beyond tidiness: `trapezoid_auc` integrates over the points in the order
    `roc_points` emits them, so a shuffled lattice yields an AUC for a polyline that
    doubles back on itself.
    """
    assert P.STRENGTHS == ("LOW", "MEDIUM", "HIGH"), P.STRENGTHS
    assert "NONE" not in P.STRENGTHS, (
        "NONE is back in the lattice. CreateGuardrail rejects an all-NONE "
        "contentPolicyConfig, so every arm would call P.guardrail('cf-none') on a manifest "
        "entry no create call can produce")


def test_the_unbuildable_setting_is_recorded_with_its_reason() -> None:
    """"Three settings" without a reason reads as a design choice, not a constraint."""
    assert "NONE" in P.UNREACHABLE_STRENGTHS
    why = P.UNREACHABLE_STRENGTHS["NONE"]
    assert "ValidationException" in why, why
    assert "At least one content filter strength must be set to not NONE" in why, why
    # The inputEnabled=False probe is what rules out "just disable the filters instead",
    # and it is the part a future reader is most likely to try.
    assert "inputEnabled=False" in why, why
    assert "2026-08-10" in why, "an undated measurement cannot be re-checked"


def test_the_reason_travels_into_the_emitted_record() -> None:
    """A constraint documented only in a source comment is invisible in the results."""
    out = P.roc_points(GOOD)
    assert out["unreachable_strengths"] == dict(P.UNREACHABLE_STRENGTHS)
    assert out["lattice_size"] == 3
    assert out["max_reachable_given_lattice"] == 5


def test_the_vertex_count_stays_under_the_sealed_ceiling() -> None:
    """The oracle allows <= 7. Three measured points plus two endpoints is 5.

    Asserted as an inequality against the sealed ceiling rather than as `== 5`, because the
    thing that must hold is the oracle's bound; 5 is today's value of it.
    """
    out = P.roc_points(GOOD)
    assert out["operating_points_with_trivial_endpoints"] == 5
    assert out["operating_points_with_trivial_endpoints"] <= 7
    assert out["endpoints_added"] == 2


# ------------------------------------------------------------- distinct points, not configs

def test_two_strengths_behaving_identically_are_one_operating_point() -> None:
    """A collapsed lattice must shrink the count, or the ROC reports points it lacks.

    This is the arm that distinguishes "the service exposes 3 settings" from "the service
    behaves 3 different ways". If MEDIUM and HIGH are indistinguishable on our corpus, the
    polyline has 2 measured vertices and saying 3 would overstate the resolution of every
    threshold recommendation drawn from it.
    """
    collapsed = sweep(
        LOW=cell(tp=50, pos=100, fp=2, neg=100),
        MEDIUM=cell(tp=85, pos=100, fp=5, neg=100),
        HIGH=cell(tp=85, pos=100, fp=5, neg=100),      # identical to MEDIUM
    )
    out = P.roc_points(collapsed)
    assert out["distinct_measured_points"] == 2, out["distinct_measured_points"]
    assert out["lattice_size"] == 3, "the lattice is unchanged; only the behaviour collapsed"
    assert out["operating_points_with_trivial_endpoints"] == 4


def test_a_missing_strength_is_skipped_not_zero_filled() -> None:
    """An interrupted run must not contribute a (0,0) vertex it never measured.

    Zero-filling would be the quiet version of this bug: the point would land exactly on
    the trivial endpoint, get absorbed by the union with {(0,0)}, and the count would look
    right while resting on an arm that never ran.
    """
    partial = sweep(LOW=GOOD["LOW"], MEDIUM=GOOD["MEDIUM"])
    out = P.roc_points(partial)
    assert [p["strength"] for p in out["points"]] == ["LOW", "MEDIUM"]
    assert out["distinct_measured_points"] == 2


# ------------------------------------------------------------------- Youden's J and interior

def test_youden_j_and_its_argmax() -> None:
    out = P.roc_points(GOOD)
    assert out["youden_j_argmax"] == "MEDIUM"
    assert out["youden_j_max"] == pytest.approx(0.80)
    assert out["argmax_is_interior"] is True


def test_interior_is_defined_against_endpoints_not_lattice_position() -> None:
    """THE arm: an argmax at LOW is interior, because LOW is a real operating point.

    `interior` used to exclude `STRENGTHS[0]`, which was NONE — genuinely at (0,0). With
    the lattice shortened, that same expression excludes LOW, and F3-9's oracle would fail
    on a sweep whose best setting is the weakest one. The failure would be reported as a
    property of the guardrail rather than of this function, which is why it is pinned here
    and not left to the live run to discover.
    """
    low_is_best = sweep(
        LOW=cell(tp=90, pos=100, fp=5, neg=100),      # J .85
        MEDIUM=cell(tp=92, pos=100, fp=20, neg=100),  # J .72
        HIGH=cell(tp=95, pos=100, fp=60, neg=100),    # J .35
    )
    out = P.roc_points(low_is_best)
    assert out["youden_j_argmax"] == "LOW"
    assert out["argmax_is_interior"] is True, (
        "an argmax at the weakest buildable strength was reported as non-interior — "
        "'interior' is about the trivial endpoints (0,0) and (1,1), not about position in "
        "the lattice")


@pytest.mark.parametrize("label,tally", [
    # Every setting classifies nothing: sits ON (0,0).
    ("origin", sweep(LOW=cell(0, 100, 0, 100), MEDIUM=cell(0, 100, 0, 100),
                     HIGH=cell(0, 100, 0, 100))),
    # Every setting blocks everything: sits ON (1,1).
    ("unit", sweep(LOW=cell(100, 100, 100, 100), MEDIUM=cell(100, 100, 100, 100),
                   HIGH=cell(100, 100, 100, 100))),
    # Chance: TPR == FPR, so J == 0 everywhere. No usable signal.
    ("chance", sweep(LOW=cell(30, 100, 30, 100), MEDIUM=cell(60, 100, 60, 100),
                     HIGH=cell(90, 100, 90, 100))),
])
def test_degenerate_sweeps_are_not_interior(label: str, tally: dict) -> None:
    """The complement of the arm above: a sweep carrying no signal must not read as one.

    Without these three, `argmax_is_interior` could be hardcoded True and every other arm
    here would still pass — the same vacuity the amendment gate's control arm exists to
    rule out.
    """
    out = P.roc_points(tally)
    assert out["argmax_is_interior"] is False, f"{label}: {out['points']}"


def test_an_empty_sweep_reports_nothing_rather_than_zero() -> None:
    """No data must be distinguishable from a measured J of 0."""
    out = P.roc_points({})
    assert out["points"] == []
    assert out["youden_j_argmax"] is None
    assert out["youden_j_max"] is None
    assert out["argmax_is_interior"] is False
    assert out["auc_trapezoid"] is None, (
        "an AUC was computed from no points; a number here would be indistinguishable "
        "from a measured area")


# ------------------------------------------------------------------------- rates and caveats

def test_a_zero_denominator_does_not_crash_or_invent_a_rate() -> None:
    """An arm whose corpus failed to load has pos=0; the rate is 0, not a ZeroDivisionError.

    Recorded deliberately rather than raising, because F3-9's cell either ran or did not,
    and `distinct_measured_points` is what the analysis reads to notice.
    """
    out = P.roc_points(sweep(LOW=cell(0, 0, 0, 0), MEDIUM=GOOD["MEDIUM"]))
    low = next(p for p in out["points"] if p["strength"] == "LOW")
    assert low["tpr"] == 0.0 and low["fpr"] == 0.0


def test_ppv_is_reported_at_every_prereg_prevalence() -> None:
    """§7.1's arithmetic is recall+FPR; PPV at realistic prevalence is what it omits."""
    out = P.roc_points(GOOD)
    for p in out["points"]:
        assert set(p["ppv_at_prevalence"]) == {"0.001", "0.01", "0.1"}, p
    med = next(p for p in out["points"] if p["strength"] == "MEDIUM")
    # tpr .85, fpr .05, pi .01  ->  .85*.01 / (.85*.01 + .05*.99)
    assert med["ppv_at_prevalence"]["0.01"] == pytest.approx(0.0085 / (0.0085 + 0.0495))


def test_the_auc_caveat_names_the_actual_point_count() -> None:
    """The caveat used to say "4 interior points" and outlived the lattice it described.

    A caveat carrying a stale number is worse than none: it reads as precision, and the
    downward bias it warns about is *larger* with three points than with four.
    """
    out = P.roc_points(GOOD)
    caveat = out["auc_caveat"]
    assert f"{len(out['points'])} measured point(s)" in caveat, caveat
    assert "downward-biased" in caveat
    assert "secondary descriptor only" in caveat
    assert "NONE vertex is unbuildable" in caveat, (
        "the caveat no longer explains why the bias exceeds the design's expectation")


def test_the_lattice_matches_the_provisioner() -> None:
    """Two copies of the lattice exist by necessity; they must not diverge.

    `f3_efficacy/00_guardrails.py` cannot be imported (its name starts with a digit), so
    the constant is duplicated and the manifest loader cross-checks it at run time. That
    check only fires once a manifest exists; this one fires offline, on the source.
    """
    src = (P.ROOT / "f3_efficacy" / "00_guardrails.py").read_text(encoding="utf-8")
    assert 'STRENGTHS = ("LOW", "MEDIUM", "HIGH")' in src, (
        "the provisioner's lattice no longer matches lib/phase1.STRENGTHS; the arms would "
        "sweep strengths whose guardrails were never created")
