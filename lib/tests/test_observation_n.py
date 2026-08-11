#!/usr/bin/env python3
"""Every Observation builder must carry a trial count, and the builders are checked as a class.

Why this file exists
--------------------
F8-6's live run collected 60 usable trials. Its arm printed `xregion: 60/60` and
`-> x=60 n_usable=60`. The record it published said:

    {"verdict": "TRUE", "n_usable": 0, "n_attempted": 0, "planned_n": 60, "n_met": false,
     "notes": ["n_usable=0 is below the pre-registered 60; the verdict stands on the data
                collected but its interval is wider than the design promised, so it does
                not clear the amendment bar"]}

Nothing in that note is arithmetically wrong. `Observation.n_usable` defaults to 0,
`obs_existence` did not accept an `n` at all, and `evaluate` computed `n_met` correctly from
the count it was given. The defect is that the count was never supplied, so a *shortfall*
was manufactured by the builder rather than measured by the run — a published amendment
blocker against data the run actually had.

Why a per-case test would not have caught it
--------------------------------------------
F8-6 is the ONLY one of the 46 EXISTENCE cases whose seal names an n. For the other 45 the
zero is invisible, because `n_met` is `(planned_n is None) or (n_usable >= planned_n)` and
the first disjunct is True. So the bug lived in a builder shared by five call sites and was
observable through exactly one of them — and it becomes observable through another the
moment a re-seal gives some other EXISTENCE case an n. That is the same shape as DEV-P1-4:
**a case's sealed kind does not predict whether the seal gives it an n**, so no builder may
assume its kind is n-less.

Hence the assertions here are over the *pairing of the builder set with the sealed set*,
not over F8-6. `test_every_builder_that_can_receive_a_sealed_n_accepts_one` enumerates the
builders from the module and the n-bearing cases from the live seal, so a re-seal that
gives F8-8 an n, or a new builder added without an `n`, fails here rather than in a result
file after the money is spent.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import oracle as O          # noqa: E402
import phase1 as P          # noqa: E402


# Builders whose Observation legitimately carries no trial count, each with the reason it
# cannot. Listed rather than inferred: "the ones that don't take n" would be satisfied by
# any builder that simply forgot to (feedback_vacuous_test_check), and per
# feedback_prose_is_not_verified the count below is derived from this table.
NO_N_BY_DESIGN = {
    "obs_recorded":
        "RECORDED means the seal declared the outcome unknown; the record is the detail "
        "dict itself and `_decide` reads no count. Both RECORDED cases have planned_n None "
        "and the assertion below fails if that ever changes.",
    "obs_boundary":
        "BOUNDARY is two booleans — accepted at the limit, rejected over it — so there is "
        "no sample. All 4 BOUNDARY cases have planned_n None, asserted below.",
}


def _builders() -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(fn)
        for name, fn in vars(P).items()
        if name.startswith("obs_") and inspect.isfunction(fn)
    }


def _accepts_n(sig: inspect.Signature) -> bool:
    """True if the builder takes a trial count under any of the three names in use.

    `obs_intervals` denominates its n as `detect_n` + `fpr_n` because its two rates have
    different denominators and a single `n` would have to be one of them; `obs_proportion`
    reads its counts out of the tally dicts it is handed. Both are counted as accepting a
    count, because they do — the thing this gate is written against is a builder that
    accepts NO count and therefore leaves the field at its default.
    """
    p = sig.parameters
    if "n" in p or "tallies" in p:
        return True
    return "detect_n" in p and "fpr_n" in p


def test_the_builder_set_is_the_one_this_gate_was_written_against():
    """A gate that stopped matching its subject reports clean.

    Nine builders at the time of writing: proportion, existence, zero_events, intervals,
    boundary, distinct, paired, roc, recorded. The floor is a tripwire for a renamed prefix
    or a moved module, not a target; it rises when the set grows, which is a deliberate
    edit. (Written first as 10 from memory, which the module refuted — the count belongs to
    the enumeration, not to my recollection of it.)
    """
    b = _builders()
    assert len(b) >= 9, (
        f"found only {len(b)} obs_* builder(s) in lib/phase1.py; the naming convention this "
        "gate enumerates by has changed, so it is no longer checking anything")
    assert set(NO_N_BY_DESIGN) <= set(b), (
        f"NO_N_BY_DESIGN names builders that no longer exist: "
        f"{sorted(set(NO_N_BY_DESIGN) - set(b))}")


def test_every_builder_either_accepts_a_trial_count_or_is_listed_with_a_reason():
    without = {n for n, s in _builders().items() if not _accepts_n(s)}
    assert without == set(NO_N_BY_DESIGN), (
        "the set of Observation builders that accept no trial count has changed.\n"
        f"  now countless: {sorted(without)}\n"
        f"  documented:    {sorted(NO_N_BY_DESIGN)}\n"
        "A builder with no count leaves Observation.n_usable at its default of 0, which "
        "makes `evaluate` report a shortfall against data the run collected (F8-6). Add an "
        "`n` parameter, or list the builder here with the reason its kind has no sample.")


def test_obs_existence_requires_n_rather_than_defaulting_it():
    """The specific regression, pinned as a signature property.

    Asserted on the signature and not only by behaviour: a default of 0 would satisfy every
    call site and every arm below while restoring exactly the defect — the whole point is
    that a caller must state its denominator, so the absence of a default IS the fix.
    """
    p = inspect.signature(P.obs_existence).parameters["n"]
    assert p.default is inspect.Parameter.empty, (
        "obs_existence.n has a default again. A default is what produced F8-6's false "
        "shortfall: five call sites silently inherited 0.")
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
        "n must be keyword-only. Positionally it sits beside `observed`, and "
        "`obs_existence(CASE, 60)` would read as a count while setting the verdict.")
    with pytest.raises(TypeError):
        P.obs_existence("F8-6", True)          # type: ignore[call-arg]


def test_a_negative_count_is_refused():
    with pytest.raises(ValueError, match="negative"):
        P.obs_existence("F8-6", True, n=-1)


# ------------------------------------------------------------- the sealed-n pairing

def _n_bearing_cases() -> dict[str, int]:
    """Cases whose seal names a planned_n, read live from PREREGISTRATION.yaml."""
    return {c: n for c in O.BINDINGS if (n := O.planned_n(c)) is not None}


def test_every_kind_with_a_sealed_n_has_a_builder_that_can_report_one():
    """The class-level statement: a sealed n needs a path for the count to reach evaluate.

    Read from the seal rather than listed, so a re-seal that gives an n to a BOUNDARY or
    RECORDED case — the two kinds documented above as countless — fails HERE instead of
    quietly publishing `n_met: false` from a builder that has nowhere to put the number.
    """
    countless_kinds = {"BOUNDARY", "RECORDED"}
    offenders = {
        c: (O.BINDINGS[c].kind, n)
        for c, n in _n_bearing_cases().items()
        if O.BINDINGS[c].kind in countless_kinds
    }
    assert not offenders, (
        "the pre-registration now seals an n for a case whose kind has no sample:\n"
        + "\n".join(f"  {c}: kind={k} planned_n={n}" for c, (k, n) in offenders.items())
        + "\nEither the kind needs a trial count (give its builder an `n` and update "
          "NO_N_BY_DESIGN), or the seal is wrong. Do not let it default to 0 — that "
          "reports a shortfall against data the run collected.")


def test_the_only_existence_case_with_a_sealed_n_is_still_f8_6():
    """Pinned because the blast radius of this defect is exactly this set.

    Not a constraint on the seal — a re-seal MAY legitimately add one. It is a tripwire:
    when the set grows, the new case's call site has to be checked for the same fault, and
    an assertion is the only thing that will say so.
    """
    existence = {c: n for c, n in _n_bearing_cases().items()
                 if O.BINDINGS[c].kind == "EXISTENCE"}
    assert existence == {"F8-6": 60}, (
        f"EXISTENCE cases with a sealed n are now {existence}, not just F8-6. Check each "
        "one's obs_existence call site passes the count the seal will be compared against.")


def test_a_sealed_n_met_by_the_data_no_longer_reports_a_shortfall():
    """End to end, through `evaluate`, on the case that published the false note."""
    rec = O.evaluate(P.obs_existence("F8-6", True, n=60, n_disclosed=60))
    assert rec["verdict"] == O.TRUE
    assert rec["n_usable"] == 60 and rec["n_attempted"] == 60
    assert rec["planned_n"] == 60
    assert rec["n_met"] is True
    assert not [x for x in rec["notes"] if "below the pre-registered" in x], (
        f"the shortfall note survived a run that met its sealed n: {rec['notes']}")


def test_a_genuine_shortfall_still_reports_one():
    """The mutation control for the arm above.

    Without this, the fix would be indistinguishable from deleting the shortfall note —
    which is the defect DEV-P1-11/DEV-P1-12 were written about, in the opposite direction:
    a run that published verdicts from 3% of its designed sample at rc=0.
    """
    rec = O.evaluate(P.obs_existence("F8-6", True, n=7))
    assert rec["n_met"] is False
    assert any("n_usable=7 is below the pre-registered 60" in x for x in rec["notes"]), rec
