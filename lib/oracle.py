"""Falsifying conditions as executable data, bound to the sealed oracle prose.

The problem this module exists to solve
--------------------------------------
`claims/triage_rules.CASES[cid][3]` holds 93 oracle strings, and their sha256 is stamped
in `PREREGISTRATION.yaml:meta.oracle_registry` so that no falsifying condition can be
edited after data collection. That seal is strong and it is also inert: a string cannot
decide anything. Something has to turn "FALSE if the CI lower bound at the recommended
threshold is below 0.5" into a comparison, and whatever does that is where a sealed
prediction can quietly become a different prediction — the exact failure recorded in
`feedback_prose_is_not_verified`, where a justification string carried an unchecked number
that turned out to be false.

So the bindings below are **checked against the prose**, not trusted alongside it.
`prose_support_problems()` re-derives every numeric threshold in every binding from tokens
it asserts appear verbatim in the sealed oracle text, under a **declared** unit and a
**named** transform. Binding F3-2 to a 10% threshold when its oracle says "<5%" is a gate
failure, not a comment nobody reads. The direction of dependence is deliberate: prose is
the authority, the code is the derivation, and the derivation is what gets audited.

The gate earned its keep on its first run: it rejected eleven of my own bindings. Three had
pinned limits the sealed oracle states only by *reference* ("at each limit", "its limit"),
so the numbers were mine, not the pre-registration's. Two named a sample-size cell whose
`applies_to` does not list the case, which would have credited F3-11 and F6-7 with an n
designed for other cases. One, F7-7, compared a 60-second quantization grid against a
threshold of 60000 because the parser inferred milliseconds from a trailing "s" — a
factor-of-1000 error in the direction where every observation passes. Hence `unit` is
declared per binding and never inferred.

One threshold in the table is genuinely *not* in the prose. F5-6's oracle says the untagged
arm's recall upper bound must be "near 0", and "near" is not a number. That substitution
goes through the named transform `near_zero_as_5pct` so it appears in the gate's output as
an operationalisation rather than sitting in a tuple looking like something that was
measured.

Five verdicts, because two would force a lie
--------------------------------------------
TRUE / FALSE alone cannot express the pre-registration. Three of its shapes need more:

* **RECORDED.** F5-4a and F5-4b are sealed as "OUTCOME UNKNOWN — that is the experiment":
  does an unevaluable policy fail closed or open? Neither answer confirms or refutes
  anything, because nothing was predicted; both are the finding. Forcing them into TRUE or
  FALSE would publish a prediction that was never made, in whichever direction the data
  happened to land.
* **INCONCLUSIVE.** F3-8's oracle is TRUE if the recall lower bound exceeds 0.5 and FALSE if
  the *upper* bound is below 0.5. Those conditions do not partition: an interval spanning
  0.5 satisfies neither, and the gap is in the sealed text, not introduced here. Assigning
  it to either side would be inventing a decision the design declined to make.
* **NOT_TESTABLE.** F9-1 (policy-evaluation timeout) has no fault-injection surface. It is
  class X, it is in the exclusion register, and it must never appear in a pass count.

The asymmetries are the substance, not pedantry
----------------------------------------------
`ASYMMETRIC_FPR` exists for F3-3 alone, whose oracle reads "TRUE if the Wilson **upper**
bound is <10%; FALSE if the **LOWER** bound exceeds 10%". Comparing p̂ to 0.10 — the obvious
implementation — gets this wrong in both directions at once: it can call a claim false on a
point estimate that a 60-item corpus cannot resolve, and true on one whose interval reaches
well past the threshold.

Multiplicity is a family-level operation and is not performed here
-----------------------------------------------------------------
`evaluate()` returns a raw p-value and a family name. It does **not** apply
Benjamini–Hochberg, because BH is a step-up procedure over a set of p-values: applying it to
one case is not a conservative approximation of applying it to twelve, it is a different
procedure. `apply_family_corrections()` runs after all members of a family are collected.
Bonferroni *is* per-hypothesis, so the confirmatory α of 0.00625 is read from the
pre-registration and used in interval levels — a confirmatory ceiling computed at 0.05 would
be narrower than the design licenses, which is the direction that flatters a result.

A control whose removal changes nothing was never a control
-----------------------------------------------------------
`validity_checks.mutation_arms_are_mandatory` names 10 cases. For those, a TRUE verdict
without a recorded, inverted mutation arm is downgraded to INCONCLUSIVE with
`mutation_missing`. This is the project's own screen for the defect it screens the document
for (`feedback_vacuous_test_check`): "we asserted the control held and it held" is not
evidence unless removing the control was observed to break it.

Amendment eligibility is deliberately incomplete here
-----------------------------------------------------
`amendment_blockers()` reports what this module can see: verdict shape, n against the
pre-registered cell, and mutation inversion. It cannot see the two-calendar-day replication
requirement, which is derived from `t_start_utc` in the evidence records by
`check_amendment_readiness.py` — and must stay there, since a finding that could assert its
own replication would be asserting the thing under test. A caller that treats an empty
blocker list as permission to amend the document is wrong, and the returned record says so
in `blockers_are_not_exhaustive`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

try:                                    # repo root on sys.path (verify_prereg.py's way)
    from lib import stats as S
except ImportError:                     # lib/ itself on sys.path (lib/tests/conftest.py)
    import stats as S                   # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "PREREGISTRATION.yaml"


# ---------------------------------------------------------------------------
# verdict alphabet
# ---------------------------------------------------------------------------

TRUE = "TRUE"
FALSE = "FALSE"
INCONCLUSIVE = "INCONCLUSIVE"
RECORDED = "RECORDED"
NOT_TESTABLE = "NOT_TESTABLE"

VERDICTS = (TRUE, FALSE, INCONCLUSIVE, RECORDED, NOT_TESTABLE)

# Verdicts that may contribute to a "the document is confirmed / contradicted" count.
# RECORDED, INCONCLUSIVE and NOT_TESTABLE deliberately may not: a report that folded
# them into either column would overstate coverage in the direction of completeness,
# which is the one direction an exclusion register exists to prevent.
DECISIVE = (TRUE, FALSE)


# ---------------------------------------------------------------------------
# prose parsing — the check that keeps a binding honest
# ---------------------------------------------------------------------------

_NUM = r"[0-9]+(?:\.[0-9]+)?"

# The unit a binding's thresholds are expressed in. Declared per binding rather than
# inferred, because inference got it wrong: an earlier version of this parser converted
# every "…s" token to milliseconds, which turned F7-7's "quantize to 60s" into a threshold
# of 60000 against timestamps measured in seconds. A parser that guesses the unit will
# eventually guess a factor of 1000, and a factor of 1000 in a latency or lag comparison
# is not a rounding difference — it is a claim confirmed that should have been refuted.
UNITS = {
    "proportion": "a rate in [0,1]; prose writes it as a percentage or a bare decimal",
    "ms":         "milliseconds; prose may write ms or s",
    "s":          "seconds; prose may write s or ms",
    "count":      "a dimensionless count or an HTTP status",
}

# Transforms from the number written in the prose to the number the binding compares.
# Only named, checkable transforms are allowed: an unnamed arithmetic step between the
# sentence and the comparison is exactly the unverified constant this table exists to
# eliminate.
TRANSFORMS: dict[str, Callable[[float], float]] = {
    "identity": lambda v: v,
    # ">= 1 differing observation" and ">= 2 distinct values" are the same condition. The
    # prose states the former (F2-5), the DISTINCT_AT_LEAST kind counts the latter.
    "differing_to_distinct": lambda v: v + 1.0,
    # F5-6 alone. Its sealed oracle says the untagged arm's recall upper bound must be
    # "near 0"; "near" is not a number, so one has to be supplied, and this is the only
    # place in the module where a threshold is NOT read out of the prose. It is a named
    # transform rather than a literal 0.05 so that the substitution appears in the gate's
    # output and in DEVIATIONS.md instead of sitting in a tuple looking like a measurement.
    "near_zero_as_5pct": lambda v: v + 0.05,
}


# The unit each kind's comparison is *physically* in, fixed by which Observation field the
# kind reads. Declaring `unit` per binding was necessary but not sufficient: the gate checked
# that the derivation was internally consistent ("60s" under unit "ms" really is 60000) and
# so it accepted the very defect it was written for. The unit is not a free choice — a
# QUANTIZATION threshold is compared against `timestamps_s`, which is seconds by the field's
# own name, so "ms" there is wrong no matter how consistently it was converted.
#
# A kind absent from this table has no unit constraint (EXISTENCE and BOUNDARY compare
# against whatever the document's limit table is denominated in, which varies per case).
KIND_UNITS = {
    "BAND_CONTAINS":  "ms",         # latencies_ms
    "CI_OVERLAPS":    "ms",         # slope_ci, ms per additional tool invocation
    "QUANTIZATION":   "s",          # timestamps_s
    "LOWER_ABOVE":    "proportion",  # a Wilson bound
    "UPPER_BELOW":    "proportion",
    "ASYMMETRIC_FPR": "proportion",
    "DISTINCT_AT_LEAST": "count",
    "ROC_LATTICE":    "count",      # a vertex count
}


def parse_prose_number(token: str, unit: str = "count") -> float:
    """Parse an oracle-prose token into the unit the binding compares in.

    `unit` is required to be one of `UNITS` and is what disambiguates "60s". A percentage
    token is only legal for a proportion, and a bare decimal is read as already being in
    the target unit — so "0.5" for a proportion is 0.5, not 0.005.
    """
    if unit not in UNITS:
        raise ValueError(f"unknown unit {unit!r}; expected one of {sorted(UNITS)}")
    t = token.strip()

    m = re.fullmatch(rf"({_NUM})\s*%", t)
    if m:
        if unit != "proportion":
            raise ValueError(f"token {token!r} is a percentage but the binding's unit is "
                             f"{unit!r}; a rate cannot be compared against a duration")
        return float(m.group(1)) / 100.0

    m = re.fullmatch(rf"({_NUM})\s*ms", t)
    if m:
        if unit not in ("ms", "s"):
            raise ValueError(f"token {token!r} is a duration but the binding's unit is "
                             f"{unit!r}")
        v = float(m.group(1))
        return v if unit == "ms" else v / 1000.0

    m = re.fullmatch(rf"({_NUM})\s*s", t)
    if m:
        if unit not in ("ms", "s"):
            raise ValueError(f"token {token!r} is a duration but the binding's unit is "
                             f"{unit!r}")
        v = float(m.group(1))
        return v * 1000.0 if unit == "ms" else v

    m = re.fullmatch(_NUM, t)
    if m:
        return float(t)
    raise ValueError(f"cannot parse {token!r} as a proportion, duration or bare number")


def _prose_contains(token: str, text: str) -> bool:
    """Whether `token` appears in `text`, tolerating internal spacing only.

    Not a fuzzy match. `"5%"` must genuinely be in the oracle string; matching "50" as
    evidence for a "5" threshold is how a check becomes decorative. Digits are anchored
    on the left so "50" does not satisfy a search for "0".
    """
    esc = re.escape(token.strip()).replace(r"\ ", r"\s*")
    esc = esc.replace(r"%", r"\s*%").replace(r"ms", r"\s*ms")
    return re.search(rf"(?<![0-9.]){esc}", text) is not None


# ---------------------------------------------------------------------------
# bindings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Binding:
    """How one case's sealed prose is executed.

    `prose` is the list of tokens the binding asserts it read the numbers out of, and
    `thresholds` is what it derived. `prose_support_problems()` checks that each token is
    in the oracle text and that parsing the tokens reproduces the thresholds — so a
    binding cannot silently disagree with the sentence it claims to implement.
    """

    kind: str
    thresholds: tuple[float, ...] = ()
    prose: tuple[str, ...] = ()
    unit: str = "count"
    transform: str = "identity"
    cell: str | None = None            # which sample_sizes entry supplies planned n
    # Set only where the sealed oracle states a limit by REFERENCE ("at each limit",
    # "its limit") instead of by value. The referent is then in the document, not in the
    # oracle, so a prose token cannot exist and `thresholds` must stay empty — the
    # limits are read from the document at collection time and recorded in the evidence.
    limits_by_reference: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown oracle kind {self.kind!r}")
        if self.unit not in UNITS:
            raise ValueError(f"unknown unit {self.unit!r}")
        if self.transform not in TRANSFORMS:
            raise ValueError(f"unknown transform {self.transform!r}")
        if self.limits_by_reference and self.thresholds:
            raise ValueError("a binding whose limits are stated by reference cannot also "
                             "pin threshold values; the referent lives in the document")


# Kinds, each a shape of falsifying condition found in the sealed text. Keeping the set
# small and named after the shape (not after the case) is what stops this table from
# becoming 93 bespoke functions that no gate can compare with anything.
KINDS = {
    "EXISTENCE":            "a deterministic boolean observation (a field, metric or span exists / behaves)",
    "ENUM_EXACT":           "an observed enum must equal a documented set exactly",
    "BOUNDARY":             "accepted at the documented limit, rejected at limit+1",
    "ZERO_EVENTS":          "TRUE iff zero adverse events; a ceiling is reported either way",
    "DISTINCT_AT_LEAST":    "TRUE iff at least k distinct values were observed",
    "STRATUM_PURITY":       "TRUE iff no score stratum is mixed (law of total variance)",
    "LOWER_ABOVE":          "TRUE if lower bound > t; FALSE if upper bound < t; gap is INCONCLUSIVE",
    "UPPER_BELOW":          "TRUE if upper bound < t; FALSE otherwise at the pre-registered n",
    "ASYMMETRIC_FPR":       "TRUE if upper < t; FALSE only if LOWER > t (F3-3's shape)",
    "DISJOINT_INTERVALS":   "TRUE iff the detection interval's lower bound exceeds the FPR interval's upper bound",
    "BAND_CONTAINS":        "TRUE iff the measured p50..p99 band lies inside the document's ILLUSTRATIVE band",
    "NONNEG_RESIDUAL":      "TRUE iff the additivity residual is >= 0 within CI",
    "CI_OVERLAPS":          "TRUE iff a bootstrap CI overlaps the document's stated range",
    "SHIFT_EXCLUDES_ZERO":  "TRUE iff a paired location shift's CI excludes 0",
    "ROC_LATTICE":          "TRUE iff reachable operating points <= 7 and Youden's J peaks at an interior threshold",
    "PAIRED_IMPROVEMENT":   "TRUE iff a paired test shows improvement in the stated direction",
    "INDISTINGUISHABLE":    "TRUE iff the two intervals OVERLAP (the claim is of no difference)",
    "LAG_FLOOR":            "measured lag against each alarm period it constrains",
    "QUANTIZATION":         "TRUE iff observed timestamps quantize to the stated grid",
    "RECORDED":             "outcome unknown by design; the observation IS the finding",
    "NOT_TESTABLE":         "no instrument exists; excluded with a named remedy",
}


# The binding table. One entry per case in claims/triage_rules.CASES; the gate below
# fails on any case without one, and on any entry naming a case that does not exist.
BINDINGS: dict[str, Binding] = {
    # ---- F0 -------------------------------------------------------------
    "F0-1":  Binding("EXISTENCE", note="every §10 URL returns 200 and its title matches"),

    # ---- F1 config surface (28) -----------------------------------------
    "F1-1":  Binding("EXISTENCE"),
    "F1-2":  Binding("EXISTENCE"),
    "F1-3":  Binding("EXISTENCE", note="CREATE_FAILED with an Overly Permissive finding"),
    "F1-4":  Binding("EXISTENCE", note="exactly one union arm accepted per call"),
    "F1-5":  Binding("ENUM_EXACT"),
    "F1-6":  Binding("EXISTENCE"),
    "F1-7":  Binding("ENUM_EXACT"),
    "F1-8":  Binding("EXISTENCE"),
    "F1-9":  Binding("EXISTENCE"),
    "F1-10": Binding("BOUNDARY", (200.0, 1000.0), ("200", "1000"), unit="count"),
    "F1-11": Binding("EXISTENCE"),
    "F1-12": Binding("EXISTENCE", note="SYNCHRONOUS is the default when omitted"),
    "F1-13": Binding("BOUNDARY",
                     limits_by_reference="§3.1's contextual-grounding limits (100000 / 1000 "
                                         "/ 5000 chars). The sealed oracle says 'at each "
                                         "limit', so the values live in the document under "
                                         "test; pinning them here would let a binding "
                                         "disagree with the document silently instead of "
                                         "failing on it"),
    "F1-14": Binding("EXISTENCE"),
    "F1-15": Binding("EXISTENCE"),
    "F1-16": Binding("EXISTENCE"),
    "F1-17": Binding("EXISTENCE"),
    "F1-18": Binding("EXISTENCE", note="every score on the 6-value lattice over >=500 evaluations"),
    "F1-19": Binding("EXISTENCE"),
    "F1-20": Binding("BOUNDARY", (10.0,), ("10",), unit="count"),
    "F1-21": Binding("EXISTENCE"),
    "F1-22": Binding("EXISTENCE"),
    "F1-23": Binding("EXISTENCE"),
    "F1-24": Binding("EXISTENCE"),
    "F1-25": Binding("EXISTENCE"),
    "F1-26": Binding("EXISTENCE"),
    "F1-27": Binding("EXISTENCE"),
    "F1-28": Binding("EXISTENCE"),

    # ---- F2 determinism (5) ---------------------------------------------
    "F2-1":  Binding("ZERO_EVENTS", cell="determinism_cell",
                     note="one flip falsifies; H0 has probability 0, so no p-value"),
    "F2-2":  Binding("DISTINCT_AT_LEAST", (2.0,), ("2",), unit="count", cell="determinism_cell",
                     note="TRUE means NON-deterministic: >=2 distinct scores"),
    "F2-3":  Binding("STRATUM_PURITY", cell="determinism_cell"),
    "F2-4":  Binding("PAIRED_IMPROVEMENT", cell="determinism_cell",
                     note="flip rate must track tau placement toward 2p(1-p)"),
    "F2-5":  Binding("DISTINCT_AT_LEAST", (2.0,), ("1",), unit="count",
                     transform="differing_to_distinct", cell="determinism_cell",
                     note="the prose says '>=1 differing verdict or score'; one DIFFERING "
                          "observation means two DISTINCT values, and the transform names "
                          "that step instead of leaving a bare 2 next to a prose 1"),

    # ---- F3 detection (11) ----------------------------------------------
    "F3-1":  Binding("LOWER_ABOVE", (0.5,), ("0.5",), unit="proportion",
                     cell="attack_recall_cell"),
    "F3-2":  Binding("UPPER_BELOW", (0.05,), ("5%",), unit="proportion",
                     cell="benign_fpr_cell"),
    "F3-3":  Binding("ASYMMETRIC_FPR", (0.10,), ("10%",), unit="proportion",
                     cell="hard_negative_cell"),
    "F3-4":  Binding("LOWER_ABOVE", (0.5,), ("0.5",), unit="proportion",
                     cell="pii_per_entity_cell",
                     note="PER ENTITY: the cell is 11 per entity, not the 87-item corpus"),
    "F3-5":  Binding("DISJOINT_INTERVALS"),
    "F3-6":  Binding("ZERO_EVENTS", note="any miss or any near-miss block is an adverse event"),
    "F3-7":  Binding("DISJOINT_INTERVALS"),
    "F3-8":  Binding("LOWER_ABOVE", (0.5,), ("0.5",), unit="proportion",
                     cell="attack_recall_cell"),
    "F3-9":  Binding("ROC_LATTICE", (7.0,), ("7",), unit="count"),
    "F3-10": Binding("EXISTENCE", note="is a per-request score<->label join recoverable at all"),
    "F3-11": Binding("PAIRED_IMPROVEMENT", cell=None,
                     note="drift is TRUE; direction is not predicted. cell=None is a "
                          "FINDING, not an omission: regression_cell.applies_to lists only "
                          "F6-8, so no pre-registered n covers F3-11's +7d/+30d re-runs. "
                          "Recorded as DEV-P1-1 rather than silently borrowing F6-8's 200, "
                          "which would attribute a latency design decision to a detection "
                          "re-run"),

    # ---- F4 enforcement semantics (6) -----------------------------------
    "F4-1":  Binding("ZERO_EVENTS", cell="confirmatory_e_cell"),
    "F4-2":  Binding("ZERO_EVENTS", cell="confirmatory_e_cell"),
    "F4-3":  Binding("ZERO_EVENTS", cell="confirmatory_e_cell"),
    "F4-4":  Binding("ZERO_EVENTS", cell="confirmatory_e_cell"),
    "F4-5":  Binding("ZERO_EVENTS", cell="confirmatory_e_cell"),
    "F4-6":  Binding("ZERO_EVENTS", (403.0,), ("403",), unit="count",
                     cell="confirmatory_e_cell"),

    # ---- F5 non-bypassability (12) --------------------------------------
    "F5-1":  Binding("ZERO_EVENTS", cell="confirmatory_e_cell"),
    "F5-2":  Binding("ZERO_EVENTS", cell="confirmatory_e_cell"),
    "F5-3a": Binding("EXISTENCE"),
    "F5-3b": Binding("EXISTENCE"),
    "F5-4a": Binding("RECORDED", note="DENY or ALLOW; either is the finding"),
    "F5-4b": Binding("RECORDED", note="fail-closed or fail-open; AWS does not document it"),
    "F5-5":  Binding("DISJOINT_INTERVALS", cell="attack_recall_cell"),
    "F5-6":  Binding("UPPER_BELOW", (0.05,), ("0",), unit="proportion",
                     transform="near_zero_as_5pct", cell="attack_recall_cell",
                     note="DC-2. The sealed oracle says §3.2 is TRUE only if the UNTAGGED "
                          "arm's recall upper bound is 'near 0' and FALSE if untagged "
                          "detection is 'substantial'. 'Near 0' is operationalised as the "
                          "one-sided upper bound < 0.05 — the same 5% the rest of the "
                          "pre-registration uses for a negligible rate — and this is "
                          "recorded as an OPERATIONALISATION, not read out of the prose: "
                          "the token pinned is the prose's own 0, and DEVIATIONS.md carries "
                          "the rule. The direction is UPPER_BELOW because the document's "
                          "claim is that detection does NOT happen without tagging; the "
                          "prior 5/5 observation at n=5 predicts this will be REFUTED"),
    "F5-7a": Binding("EXISTENCE"),
    "F5-7b": Binding("EXISTENCE"),
    "F5-8":  Binding("EXISTENCE"),
    "F5-9":  Binding("EXISTENCE", note="hard-gated on a provably unused model"),

    # ---- F6 latency (9) -------------------------------------------------
    "F6-1":  Binding("BAND_CONTAINS", (50.0, 200.0), ("50", "200"), unit="ms",
                     cell="latency_arm_p99"),
    "F6-2":  Binding("BAND_CONTAINS", (100.0, 500.0), ("100", "500"), unit="ms",
                     cell="latency_arm_p99"),
    "F6-3":  Binding("BAND_CONTAINS", (5.0, 50.0), ("5", "50"), unit="ms",
                     cell="latency_arm_p99"),
    "F6-4":  Binding("BAND_CONTAINS", (50.0, 200.0), ("50", "200"), unit="ms",
                     cell="latency_arm_p99"),
    "F6-5":  Binding("BAND_CONTAINS", (100.0, 500.0), ("100", "500"), unit="ms",
                     cell="latency_arm_p99"),
    "F6-6":  Binding("BAND_CONTAINS", (800.0, 31000.0), ("800ms", "31s"), unit="ms",
                     cell="latency_arm_p99",
                     note="the document writes '31s+'; the trailing + makes the UPPER end "
                          "unfalsifiable, so only the 800ms floor is testable — see "
                          "band_upper_is_open()"),
    "F6-7":  Binding("NONNEG_RESIDUAL", cell="latency_arm_p50_p90_only",
                     note="latency_arm_p99.applies_to omits F6-7; the p50_p90_only cell is "
                          "the one that lists it, at n=200. Consistent with the oracle, "
                          "which tests a residual's sign and not a p99"),
    "F6-8":  Binding("CI_OVERLAPS", (165.0, 750.0), ("165", "750"), unit="ms",
                     cell="latency_arm_p50_p90_only"),
    "F6-9":  Binding("SHIFT_EXCLUDES_ZERO", cell="latency_arm_p99"),

    # ---- F7 observability (7) -------------------------------------------
    "F7-1":  Binding("EXISTENCE",
                     limits_by_reference="the count of documented policy metrics (19) is in "
                                         "this case's TITLE, not in its sealed oracle; the "
                                         "oracle is per-metric existence, so the count is a "
                                         "property of the metric list the script iterates "
                                         "and is recorded in the evidence, not compared here"),
    "F7-2":  Binding("EXISTENCE"),
    "F7-3":  Binding("EXISTENCE", (7.0,), ("7",), unit="count"),
    "F7-4":  Binding("EXISTENCE"),
    "F7-5":  Binding("EXISTENCE", note="the mutation that removes 'did we enable it' as a confound"),
    "F7-6":  Binding("LAG_FLOOR", cell="publish_lag_cell"),
    "F7-7":  Binding("QUANTIZATION", (60.0,), ("60s",), unit="s", cell="publish_lag_cell",
                     note="unit='s' is load-bearing: the timestamps are seconds, and an "
                          "inferred ms conversion made this threshold 60000, which every "
                          "observation would have satisfied"),

    # ---- F8 regional / tier / language (8) ------------------------------
    "F8-1":  Binding("EXISTENCE", (5.0,), ("5",), unit="count",
                     note="mutation must succeed in the 5 listed Regions and fail in the others"),
    "F8-2":  Binding("INDISTINGUISHABLE", cell="multilingual_cell",
                     note="the claim is of NO protection, so overlap CONFIRMS it"),
    "F8-3":  Binding("PAIRED_IMPROVEMENT", cell="multilingual_cell"),
    "F8-4":  Binding("EXISTENCE"),
    "F8-5":  Binding("BOUNDARY",
                     limits_by_reference="the per-tier denied-topic limits (CLASSIC 200, "
                                         "STANDARD 1000). The oracle says 'each tier "
                                         "accepts its limit'; F1-10 is the case that pins "
                                         "the two numbers, and it does so from prose that "
                                         "states them"),
    "F8-6":  Binding("EXISTENCE", cell="multilingual_cell"),
    "F8-7":  Binding("EXISTENCE"),
    "F8-8":  Binding("EXISTENCE"),

    # ---- F9 fail-secure (3) ---------------------------------------------
    "F9-1":  Binding("NOT_TESTABLE", note="no fault-injection surface; proxies are F5-4a/F5-4b"),
    "F9-2":  Binding("EXISTENCE"),
    "F9-3":  Binding("EXISTENCE"),

    # ---- F10 billing (3) ------------------------------------------------
    "F10-1": Binding("EXISTENCE", note="zero inference charge on input block, full on output block"),
    "F10-2": Binding("EXISTENCE"),
    "F10-3": Binding("EXISTENCE"),
}


# ---------------------------------------------------------------------------
# pre-registration lookups
# ---------------------------------------------------------------------------

_PREREG_CACHE: dict[str, Any] | None = None


def prereg() -> dict[str, Any]:
    """The sealed pre-registration, parsed once.

    Read from disk rather than duplicated as constants here: alpha, family membership and
    every n live in the sealed file, and a second copy in code would be a second source of
    truth that no hash covers.
    """
    global _PREREG_CACHE
    if _PREREG_CACHE is None:
        import yaml
        _PREREG_CACHE = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    return _PREREG_CACHE


def cases() -> dict[str, tuple]:
    """`claims/triage_rules.CASES`, imported lazily so lib/ does not depend on claims/."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_grx_triage_rules", ROOT / "claims" / "triage_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CASES


def oracle_text(cid: str) -> str:
    return cases()[cid][3]


UNASSIGNED = "unassigned_by_seal"


def family_of(cid: str) -> str:
    """Which multiplicity family `cid` belongs to, according to the seal and only the seal.

    Three ways a case can be placed, in the order the pre-registration establishes them:
    an explicit `members` list; the `descriptive_no_test` class rule; or nothing at all.

    The class rule is read from `members_by_class` and `excluded_from_this_rule` rather
    than hardcoded. An earlier version of this function wrote `if cls in ("C", "O")`, which
    happened to match `members_by_class` but ignored the exclusion list — so F3-10, F7-6 and
    F7-7 were being assigned the very rule the seal names them to withhold. That is the
    `feedback_prose_is_not_verified` failure in its purest form: a rule restated in code
    beside the sealed rule, agreeing with it in the part that was remembered.

    Cases the seal places nowhere return `UNASSIGNED` instead of raising. Raising was worse
    than either alternative: 11 of the 93 sealed cases hit it (F5-3a/3b, F5-4a/4b, F5-7b,
    F5-8, F5-9, F9-1, F9-3, F10-1, F10-3), so `evaluate()` crashed on 12% of the suite —
    including both RECORDED cases, whose whole purpose is to be evaluable without a
    prediction. Returning a **named** family keeps the gap visible where a default would
    bury it: `apply_family_corrections` reports these cases, and reports as a seal gap any
    p-value that arrives under a family with no declared correction. A silent
    `descriptive_no_test` would have removed a correction without a record, which is what the
    raise was defending against; a named unassigned family defends against it without
    making a fifth of the suite unrunnable.
    """
    pr = prereg()
    for name, spec in pr["families"].items():
        if cid in (spec.get("members") or []):
            return name
    cls = cases()[cid][2]
    for name, spec in pr["families"].items():
        if cls in (spec.get("members_by_class") or []) and \
                cid not in (spec.get("excluded_from_this_rule") or []):
            return name
    return UNASSIGNED


def alpha_for(cid: str) -> float:
    """The per-hypothesis alpha to build intervals at.

    Bonferroni is per-hypothesis, so the confirmatory family's 0.00625 is used directly.
    Every other family gets 0.05: BH does not change an individual interval, it changes
    which p-values are declared significant, and that happens in
    `apply_family_corrections`.
    """
    fam = family_of(cid)
    spec = prereg()["families"].get(fam, {})
    if spec.get("correction") == "bonferroni":
        return float(spec["alpha_per_hypothesis"])
    # UNASSIGNED lands here too, at the nominal alpha. That is the honest reading: the seal
    # declares no correction for these cases, and inventing a stricter one after data
    # collection would be as outcome-dependent as inventing a looser one. The gap itself is
    # reported by apply_family_corrections, not hidden inside a quietly adjusted interval.
    return float(prereg()["derived"]["alpha"])


def planned_n(cid: str) -> int | None:
    """The pre-registered n for `cid`, from the cell its binding names.

    Two cases (F3-4, F6-8) appear in two cells, which is why the binding must name one:
    F3-4's oracle is per-entity, so its n is 11 per entity and *not* the 87-item corpus,
    and choosing the larger number would make a per-entity result look 8x better powered
    than it is.
    """
    b = BINDINGS[cid]
    if b.cell is None:
        return None
    return int(prereg()["sample_sizes"][b.cell]["n"])


def mutation_is_mandatory(cid: str) -> bool:
    return cid in set(
        prereg()["validity_checks"]["mutation_arms_are_mandatory"]["applies_to"])


def band_upper_is_open(cid: str) -> bool:
    """Whether the document's stated band has an open upper end ("31s+").

    F6-6 is the only such case. It matters because a measured p99 above 31s cannot
    falsify a claim of "31s+" — the claim admits any larger value — so the falsifiable
    content is the 800ms floor alone. Reporting F6-6 as though both ends were testable
    would credit the document with a prediction it did not make.
    """
    return "+" in re.sub(r"\s", "", oracle_text(cid)).replace("p50", "")[:400] and \
        BINDINGS[cid].kind == "BAND_CONTAINS" and "31s+" in oracle_text(cid).replace(" ", "")


# ---------------------------------------------------------------------------
# interval helpers at the case's own alpha
# ---------------------------------------------------------------------------

def one_sided_hi(x: int, n: int, alpha: float) -> float:
    """Upper end of a one-sided (1-alpha) bound, as the two-sided (1-2a) upper end."""
    return S.wilson_ci(x, n, level=1 - 2 * alpha).hi


def one_sided_lo(x: int, n: int, alpha: float) -> float:
    return S.wilson_ci(x, n, level=1 - 2 * alpha).lo


def ceiling_at_zero(n: int, alpha: float) -> float:
    """Exact one-sided ceiling after zero adverse events: 1 - alpha^(1/n).

    Reported even when the verdict is TRUE. `families.single_counterexample.note` requires
    it: "a zero-flip result carries a quantified ceiling rather than an unqualified
    'deterministic'". Without it, 300 clean trials and 3 clean trials read identically.
    """
    return S.rule_of_three(n, level=1 - alpha, one_sided=True)


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """What a family script hands the oracle. Fields not relevant to a kind stay None.

    `n_usable` is separate from `n_attempted` on purpose: `lib/checkpoint.py` keeps failed
    trials out of the results, so a cell can complete fewer trials than it attempted, and
    the interval must be built on the usable count while the shortfall stays visible.
    """

    case_id: str
    n_attempted: int = 0
    n_usable: int = 0
    adverse: int | None = None                  # ZERO_EVENTS / proportions: x
    observed_bool: bool | None = None            # EXISTENCE
    observed_enum: Sequence[str] | None = None   # ENUM_EXACT
    expected_enum: Sequence[str] | None = None
    at_limit_ok: bool | None = None              # BOUNDARY
    over_limit_rejected: bool | None = None
    distinct_values: Sequence[float] | None = None
    scores: Sequence[float] | None = None        # STRATUM_PURITY
    decisions: Sequence[int] | None = None
    detect_x: int | None = None                  # DISJOINT_INTERVALS / INDISTINGUISHABLE
    detect_n: int | None = None
    fpr_x: int | None = None
    fpr_n: int | None = None
    latencies_ms: Sequence[float] | None = None  # BAND_CONTAINS
    residual_ci: tuple[float, float] | None = None
    slope_ci: tuple[float, float] | None = None
    shift_ci: tuple[float, float] | None = None
    operating_points: int | None = None          # ROC_LATTICE
    argmax_j_interior: bool | None = None
    p_value: float | None = None                 # PAIRED_IMPROVEMENT
    improved: bool | None = None
    lag_p90_s: float | None = None               # LAG_FLOOR
    alarm_periods_s: Sequence[float] | None = None
    timestamps_s: Sequence[float] | None = None  # QUANTIZATION
    mutation_inverted: bool | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _need(obs: Observation, *names: str) -> None:
    missing = [k for k in names if getattr(obs, k) is None]
    if missing:
        raise ValueError(f"{obs.case_id}: kind {BINDINGS[obs.case_id].kind} needs "
                         f"{', '.join(missing)}; an oracle cannot be evaluated on absent "
                         f"observations, and defaulting them would manufacture a verdict")


def evaluate(obs: Observation) -> dict[str, Any]:
    """Decide one case. Returns a record; never raises on a merely disappointing result.

    The returned `verdict` answers "what did the sealed oracle say about this data", and
    nothing else. Whether the document may be amended is a separate question with more
    conditions, answered by `amendment_blockers`.
    """
    cid = obs.case_id
    if cid not in BINDINGS:
        raise KeyError(f"{cid} has no binding; every case in CASES must have one")
    b = BINDINGS[cid]
    alpha = alpha_for(cid)
    want_n = planned_n(cid)
    n = obs.n_usable or obs.n_attempted
    rec: dict[str, Any] = {
        "case_id": cid,
        "kind": b.kind,
        "family": family_of(cid),
        "alpha": alpha,
        "planned_n": want_n,
        "n_attempted": obs.n_attempted,
        "n_usable": obs.n_usable,
        "n_met": (want_n is None) or (obs.n_usable >= want_n),
        "thresholds": list(b.thresholds),
        "p_value": obs.p_value,
        "notes": [],
    }

    verdict, evidence = _decide(b, obs, alpha, n)
    rec["verdict"] = verdict
    rec["evidence"] = evidence

    # A mandatory mutation that did not invert means the control was never load-bearing,
    # so a TRUE verdict is not available regardless of how clean the primary arm was.
    if mutation_is_mandatory(cid):
        rec["mutation_required"] = True
        rec["mutation_inverted"] = obs.mutation_inverted
        if obs.mutation_inverted is None:
            if verdict == TRUE:
                rec["verdict"] = INCONCLUSIVE
                rec["notes"].append(
                    "mutation arm is mandatory for this case and was not recorded; a "
                    "control observed only to hold is not evidence that it is doing work")
        elif obs.mutation_inverted is False:
            rec["verdict"] = FALSE
            rec["notes"].append(
                "the mutation did not invert the outcome, so removing the control changed "
                "nothing: the control is not load-bearing and the claim that it protects "
                "is unsupported")
    else:
        rec["mutation_required"] = False

    if not rec["n_met"] and rec["verdict"] in DECISIVE:
        rec["notes"].append(
            f"n_usable={obs.n_usable} is below the pre-registered {want_n}; the verdict "
            f"stands on the data collected but its interval is wider than the design "
            f"promised, so it does not clear the amendment bar")
    return rec


def not_measured(case_id: str, reason: str, **detail: Any) -> dict[str, Any]:
    """An INCONCLUSIVE record for a case that could not be measured, in `evaluate`'s shape.

    Why this exists, and why it is not `evaluate(phase1.obs_recorded(cid, ...))`
    -------------------------------------------------------------------------
    RECORDED is a **kind**, sealed per case, and `_decide` dispatches on the sealed kind —
    never on the shape of the observation it is handed. So an observation carrying only a
    `detail` dict, passed under a case sealed as EXISTENCE or BOUNDARY, reaches that kind's
    `_need(...)` and raises `ValueError`. That is `_need` working correctly: it is refusing
    to manufacture a verdict from absent observations.

    But three case scripts had a legitimate need for which they reached for `obs_recorded`:
    a precondition check that fails *before* any data is collected. F8-5 discovers that
    botocore now enforces the definition maximum client-side, so an over-length probe never
    reaches the service; F8-6 discovers that `crossRegionDetails` is absent, so the
    guardrail under test is not cross-Region at all. In both cases the instrument is
    unsound and the honest output is "this was not measured, and here is why" — which is
    INCONCLUSIVE, not RECORDED. RECORDED means *the pre-registration declared the outcome
    unknown and both answers are findings*; it is a property of the seal, and a script
    cannot grant it to itself. Two shipped branches did exactly that and would have crashed
    on the path they existed to protect (DEVIATIONS.md/DEV-P1-8).

    The record is built here rather than by a caller because `emit` and
    `amendment_blockers` both read `verdict`, `n_met`, `planned_n` and `mutation_required`,
    and a hand-rolled dict missing one of them would fail at the point of writing the
    result — i.e. after the money was spent.
    """
    if case_id not in BINDINGS:
        raise KeyError(f"{case_id} has no binding; every case in CASES must have one")
    if not reason:
        raise ValueError(
            f"{case_id}: not_measured needs a reason. An INCONCLUSIVE verdict with no "
            f"stated cause is indistinguishable from a straddling interval, and the two "
            f"have opposite remedies — one is fixed by collecting more data, the other by "
            f"repairing the instrument")
    b = BINDINGS[case_id]
    want_n = planned_n(case_id)
    rec: dict[str, Any] = {
        "case_id": case_id,
        "kind": b.kind,
        "family": family_of(case_id),
        "alpha": alpha_for(case_id),
        "planned_n": want_n,
        "n_attempted": 0,
        "n_usable": 0,
        # False whenever the seal names an n. Deliberately not special-cased to True for
        # the None-n cases: `n_met` answers "was the pre-registered arm run", and zero
        # trials did not run it. A case with no sealed n has nothing to fall short of, so
        # `evaluate`'s own rule (None -> True) is reused rather than contradicted.
        "n_met": (want_n is None),
        "thresholds": list(b.thresholds),
        "p_value": None,
        "notes": [f"not measured: {reason}"],
        "verdict": INCONCLUSIVE,
        "evidence": {
            "reason": reason,
            "measured": False,
            "why_not_recorded": (
                "RECORDED is a sealed property of the case, meaning the pre-registration "
                "declared the outcome unknown and both answers are findings. This case's "
                "sealed kind is "
                f"{b.kind}: it made a prediction, and the prediction was not tested"),
            "detail": dict(detail),
        },
        "mutation_required": mutation_is_mandatory(case_id),
    }
    if rec["mutation_required"]:
        rec["mutation_inverted"] = None
    return rec


def _decide(b: Binding, obs: Observation, alpha: float, n: int) -> tuple[str, dict]:
    k = b.kind

    if k == "NOT_TESTABLE":
        return NOT_TESTABLE, {"reason": b.note}

    if k == "RECORDED":
        return RECORDED, {"observation": obs.detail,
                          "why_no_verdict": "the pre-registration declares this outcome "
                                            "unknown; both answers are findings"}

    if k == "EXISTENCE":
        _need(obs, "observed_bool")
        return (TRUE if obs.observed_bool else FALSE), {"observed": obs.observed_bool,
                                                        "detail": obs.detail}

    if k == "ENUM_EXACT":
        _need(obs, "observed_enum", "expected_enum")
        got, want = set(obs.observed_enum), set(obs.expected_enum)
        return (TRUE if got == want else FALSE), {
            "observed": sorted(got), "expected": sorted(want),
            "missing": sorted(want - got), "unexpected": sorted(got - want)}

    if k == "BOUNDARY":
        _need(obs, "at_limit_ok", "over_limit_rejected")
        ok = bool(obs.at_limit_ok) and bool(obs.over_limit_rejected)
        return (TRUE if ok else FALSE), {
            "at_limit_accepted": obs.at_limit_ok,
            "over_limit_rejected": obs.over_limit_rejected,
            "limits": list(b.thresholds)}

    if k == "ZERO_EVENTS":
        _need(obs, "adverse")
        x = int(obs.adverse)
        if n <= 0:
            return INCONCLUSIVE, {"reason": "no usable trials"}
        ev = {"x": x, "n": n,
              "ceiling_one_sided": ceiling_at_zero(n, alpha) if x == 0
                                   else one_sided_hi(x, n, alpha),
              "ceiling_method": "exact 1-alpha^(1/n)" if x == 0 else "wilson one-sided",
              "interval": str(S.wilson_ci(x, n, level=1 - alpha))}
        return (TRUE if x == 0 else FALSE), ev

    if k == "DISTINCT_AT_LEAST":
        _need(obs, "distinct_values")
        need = int(b.thresholds[0]) if b.thresholds else 2
        vals = sorted({float(v) for v in obs.distinct_values})
        return (TRUE if len(vals) >= need else FALSE), {
            "distinct": vals, "required": need, "n": n}

    if k == "STRATUM_PURITY":
        _need(obs, "scores", "decisions")
        vd = S.variance_decomposition(obs.scores, obs.decisions)
        return (TRUE if vd["conditionally_deterministic"] else FALSE), vd

    if k in ("LOWER_ABOVE", "UPPER_BELOW", "ASYMMETRIC_FPR"):
        _need(obs, "adverse")
        x = int(obs.adverse)
        if n <= 0:
            return INCONCLUSIVE, {"reason": "no usable trials"}
        t = b.thresholds[0]
        ci = S.wilson_ci(x, n, level=1 - alpha)
        lo, hi = one_sided_lo(x, n, alpha), one_sided_hi(x, n, alpha)
        ev = {"x": x, "n": n, "point": ci.point, "one_sided_lo": lo, "one_sided_hi": hi,
              "threshold": t, "interval": str(ci)}
        if k == "LOWER_ABOVE":
            if lo > t:
                return TRUE, ev
            if hi < t:
                return FALSE, ev
            ev["gap"] = ("the interval spans the threshold; the sealed oracle states both "
                         "conditions and they do not partition, so neither fires")
            return INCONCLUSIVE, ev
        if k == "UPPER_BELOW":
            # The sealed text is two-valued ("FALSE otherwise"), and at the pre-registered
            # n it is decidable: the cell is sized so the tolerated adverse count clears
            # the bound. Only a shortfall creates a gap, and that is reported as one
            # rather than resolved by fiat.
            if hi < t:
                return TRUE, ev
            want = planned_n(obs.case_id)
            if want is not None and obs.n_usable < want:
                ev["gap"] = (f"upper bound {hi:.4f} does not clear {t} but n_usable="
                             f"{obs.n_usable} < {want}; at the pre-registered n this rule "
                             f"is decidable, so the shortfall is the reason, not the data")
                return INCONCLUSIVE, ev
            return FALSE, ev
        if lo > t:                                    # ASYMMETRIC_FPR
            return FALSE, ev
        if hi < t:
            return TRUE, ev
        ev["gap"] = ("F3-3's oracle falsifies only on the LOWER bound; an interval "
                     "straddling the threshold supports neither statement")
        return INCONCLUSIVE, ev

    if k in ("DISJOINT_INTERVALS", "INDISTINGUISHABLE"):
        _need(obs, "detect_x", "detect_n", "fpr_x", "fpr_n")
        # Both denominators must be positive, and this is checked HERE rather than left to
        # lib/stats.py's own `n must be positive` ValueError. The distinction is not style:
        # the two-interval kinds are the only ones whose observation carries TWO
        # denominators, and `n_usable = detect_n + fpr_n`, so an entirely empty stratum is
        # invisible to every n-based check upstream — `require_measured` sees a healthy
        # total and `n_met` can be satisfied while one of the two rates does not exist.
        # F8-2 hit exactly that: a `--n 3` head of multilingual/zh-TW.jsonl is three
        # JAILBREAK items, because the file's 6 CLEAN items sit at positions 54-59, so the
        # FPR arm was 0/0 and the crash landed in wilson_ci AFTER 24 billable calls.
        #
        # A stats-layer ValueError is the correct behaviour for stats (a Wilson interval on
        # n=0 does not exist and inventing one would be the vacuous-test defect a level
        # down), but it surfaces as a traceback rather than a verdict, which loses the
        # already-collected evidence and — worse — reads as a harness crash rather than as
        # "this comparison was not measured". INCONCLUSIVE with the empty side named is the
        # honest record, and it is the same reasoning as `not_measured`: an unsound
        # instrument yields no verdict, not a convenient one.
        if int(obs.detect_n) <= 0 or int(obs.fpr_n) <= 0:
            empty = [nm for nm, v in (("detection", int(obs.detect_n)),
                                      ("false_positive", int(obs.fpr_n))) if v <= 0]
            return INCONCLUSIVE, {
                "reason": (f"{' and '.join(empty)} stratum has n=0, so this kind's "
                           f"two-interval comparison has nothing to compare; a verdict "
                           f"here would rest on one interval only"),
                "detect_n": int(obs.detect_n), "fpr_n": int(obs.fpr_n),
                "why_not_caught_upstream": ("n_usable is the SUM of the two denominators, "
                                            "so an empty stratum does not reduce it"),
            }
        d = S.wilson_ci(int(obs.detect_x), int(obs.detect_n), level=1 - alpha)
        f = S.wilson_ci(int(obs.fpr_x), int(obs.fpr_n), level=1 - alpha)
        disjoint = d.lo > f.hi
        ev = {"detection": str(d), "false_positive": str(f), "disjoint": disjoint,
              "gap": d.lo - f.hi}
        if k == "DISJOINT_INTERVALS":
            return (TRUE if disjoint else FALSE), ev
        # F8-2 claims CLASSIC gives NO protection for zh/ja/ko, so overlap CONFIRMS the
        # document and separation refutes it. The inversion is easy to get backwards,
        # which is why it is a distinct kind and not a flag.
        ev["claim_direction"] = "the document claims no discrimination; overlap confirms it"
        return (FALSE if disjoint else TRUE), ev

    if k == "BAND_CONTAINS":
        _need(obs, "latencies_ms")
        lo_band, hi_band = b.thresholds
        p50 = S.quantile(obs.latencies_ms, 0.50)
        p90 = S.quantile(obs.latencies_ms, 0.90)
        p99 = S.quantile(obs.latencies_ms, 0.99) if len(obs.latencies_ms) >= 100 else None
        top = p99 if p99 is not None else p90
        open_upper = band_upper_is_open(obs.case_id)
        inside = (p50 >= lo_band) and (open_upper or top <= hi_band)
        ev = {"p50": p50, "p90": p90, "p99": p99, "band": [lo_band, hi_band],
              "upper_end_open": open_upper,
              "ci_p50": str(S.quantile_ci(obs.latencies_ms, 0.50, level=1 - alpha)),
              "n": len(obs.latencies_ms)}
        if p99 is None:
            ev["note"] = ("fewer than 100 observations, so a p99 does not exist; the band "
                          "check used p90 and no p99 may be published")
        if open_upper:
            ev["note_open"] = ("the document writes an open-ended upper bound, so no "
                               "measured value can exceed it; only the floor is falsifiable")
        return (TRUE if inside else FALSE), ev

    if k == "NONNEG_RESIDUAL":
        _need(obs, "residual_ci")
        lo, hi = obs.residual_ci
        return (TRUE if lo >= 0 else FALSE), {
            "residual_ci": [lo, hi],
            "structural": ("a significantly negative residual means the hops overlap and "
                           "falsifies the decomposition model behind §6.1, §6.3 and §6.4")}

    if k == "CI_OVERLAPS":
        _need(obs, "slope_ci")
        lo, hi = obs.slope_ci
        a, bnd = b.thresholds
        overlaps = not (hi < a or lo > bnd)
        return (TRUE if overlaps else FALSE), {"slope_ci": [lo, hi], "stated": [a, bnd]}

    if k == "SHIFT_EXCLUDES_ZERO":
        _need(obs, "shift_ci")
        lo, hi = obs.shift_ci
        return (TRUE if (lo > 0 or hi < 0) else FALSE), {"shift_ci": [lo, hi]}

    if k == "ROC_LATTICE":
        _need(obs, "operating_points", "argmax_j_interior")
        max_pts = int(b.thresholds[0])
        ok = int(obs.operating_points) <= max_pts and bool(obs.argmax_j_interior)
        return (TRUE if ok else FALSE), {
            "operating_points": obs.operating_points, "max_reachable": max_pts,
            "youden_j_interior": obs.argmax_j_interior,
            "consequence": ("more than 7 points falsifies F1-18's lattice claim; a J peak "
                            "at tau=0 or tau=1 means the score carries no usable signal")}

    if k == "PAIRED_IMPROVEMENT":
        _need(obs, "improved", "p_value")
        sig = float(obs.p_value) < alpha
        return (TRUE if (obs.improved and sig) else FALSE), {
            "improved": obs.improved, "p_value": obs.p_value, "alpha": alpha,
            "note": ("the p-value is raw; the family's BH step-up runs in "
                     "apply_family_corrections, not here")}

    if k == "LAG_FLOOR":
        _need(obs, "lag_p90_s", "alarm_periods_s")
        broken = [p for p in obs.alarm_periods_s if p < float(obs.lag_p90_s)]
        return (FALSE if broken else TRUE), {
            "lag_p90_s": obs.lag_p90_s,
            "alarm_periods_s": list(obs.alarm_periods_s),
            "periods_below_lag": broken,
            "consequence": ("an alarm whose evaluation period is under the p90 publish lag "
                            "cannot fire reliably, and §6.4 does not say so")}

    if k == "QUANTIZATION":
        _need(obs, "timestamps_s")
        grid = b.thresholds[0]
        offs = [abs(math.remainder(float(t), grid)) for t in obs.timestamps_s]
        ok = all(o < 1e-6 for o in offs)
        return (TRUE if ok else FALSE), {"grid_s": grid, "max_offset_s": max(offs) if offs else 0.0}

    raise AssertionError(f"kind {k} has no decision branch")


# ---------------------------------------------------------------------------
# family-level multiplicity, run after all members are collected
# ---------------------------------------------------------------------------

def apply_family_corrections(records: Sequence[dict]) -> dict[str, Any]:
    """Apply each family's declared correction across its members' p-values.

    Kept out of `evaluate()` because BH is a step-up procedure over a *set*: running it on
    one p-value is not a conservative version of running it on twelve, it is a different
    procedure that happens to return the raw value. Bonferroni is per-hypothesis and has
    already shaped the intervals, so it is reported here rather than reapplied.

    Members with no p-value are listed, not silently dropped — a family whose declared
    membership is 12 and whose correction ran over 3 has had its correction weakened, and
    that must appear in the output rather than in nobody's notes.
    """
    pr = prereg()
    by_family: dict[str, list[dict]] = {}
    for r in records:
        by_family.setdefault(r["family"], []).append(r)

    out: dict[str, Any] = {}
    for fam, spec in pr["families"].items():
        members = list(spec.get("members") or [])
        present = by_family.get(fam, [])
        with_p = [r for r in present if r.get("p_value") is not None]
        entry: dict[str, Any] = {
            "correction": spec.get("correction"),
            "declared_members": members,
            "records_present": [r["case_id"] for r in present],
            "members_absent": [m for m in members if m not in {r["case_id"] for r in present}],
            "members_without_p_value": [r["case_id"] for r in present
                                        if r.get("p_value") is None],
        }
        if spec.get("correction") == "benjamini_hochberg" and with_p:
            q = float(spec.get("q", 0.05))
            flags, adj = S.benjamini_hochberg([r["p_value"] for r in with_p], q=q)
            entry["q"] = q
            entry["adjusted"] = {r["case_id"]: {"p_raw": r["p_value"], "p_adj": a,
                                                "reject_null": bool(f)}
                                 for r, a, f in zip(with_p, adj, flags)}
        elif spec.get("correction") == "bonferroni":
            entry["alpha_per_hypothesis"] = float(spec["alpha_per_hypothesis"])
            entry["applied_where"] = ("in the interval level of every member's bound, at "
                                      "evaluate() time; not reapplied here")
            if len(members) != 8:
                entry["seal_violation"] = (
                    f"the confirmatory family is frozen at 8 members and now lists "
                    f"{len(members)}; changing membership changes alpha_per_hypothesis for "
                    f"every other member, which after data collection is an "
                    f"outcome-dependent threshold")
        if spec.get("correction") in (None, "none") and with_p:
            entry["uncorrected_p_values"] = [r["case_id"] for r in with_p]
            entry["seal_gap"] = (
                f"family {fam!r} declares correction {spec.get('correction')!r} but "
                f"{len(with_p)} member(s) arrived with a p-value; a p-value under no "
                f"declared correction is uncorrected, and saying so is the only honest "
                f"option — choosing a correction now would be outcome-dependent")
        out[fam] = entry

    # Records whose case the seal places in no family at all. Reported as its own entry
    # rather than folded into descriptive_no_test: these cases (F5-3a/3b, F5-4a/4b, F5-7b,
    # F5-8, F5-9, F9-1, F9-3, F10-1, F10-3) include S-class members, and quietly giving an
    # S-class case "no correction" is exactly the substitution family_of used to raise over.
    stray = by_family.get(UNASSIGNED, [])
    if stray:
        with_p = [r for r in stray if r.get("p_value") is not None]
        out[UNASSIGNED] = {
            "correction": None,
            "declared_members": [],
            "records_present": [r["case_id"] for r in stray],
            "members_absent": [],
            "members_without_p_value": [r["case_id"] for r in stray
                                        if r.get("p_value") is None],
            "uncorrected_p_values": [r["case_id"] for r in with_p],
            "seal_gap": (
                f"the sealed families block places {len(stray)} evaluated case(s) in no "
                f"family and gives their class no class-level rule, so no multiplicity "
                f"correction is defined for them. Their verdicts stand as single "
                f"hypotheses; any p-value among them is uncorrected. Recorded as a gap in "
                f"the pre-registration rather than repaired here, because assigning a "
                f"family after data collection chooses a threshold from the data"),
        }
    return out


# ---------------------------------------------------------------------------
# amendment blockers (partial by design)
# ---------------------------------------------------------------------------

def amendment_blockers(rec: dict) -> dict[str, Any]:
    """What this module can see standing between a verdict and a document amendment.

    Deliberately NOT a permission. The two-calendar-day replication rule is derived from
    `t_start_utc` in the evidence records by `check_amendment_readiness.py`, and it stays
    there because a finding that could assert its own replication would be asserting the
    thing under test — which is exactly the local-vs-UTC-midnight defect recorded as
    DEV-SEAL-10.
    """
    blockers: list[str] = []
    if rec["verdict"] not in DECISIVE:
        blockers.append(f"verdict is {rec['verdict']}, which supports no amendment: "
                        f"RECORDED and INCONCLUSIVE are findings about what was observed, "
                        f"not about what the document got wrong")
    if not rec["n_met"]:
        # `n_met_basis`, when a case set one, wins over re-deriving the sentence here.
        # A roll-up case's `n_met` is the AND over strata because its sealed n is per
        # stratum, so composing the text from the case-level counts joined a POOLED
        # numerator to a per-stratum denominator and published
        # "n_usable=93 is below the pre-registered 11" for F3-4 — every number correct, the
        # sentence false (DEV-P1-12). A shortfall a reader can disprove by arithmetic is
        # worse than no message: it invites dismissing a real blocker.
        blockers.append(rec.get("n_met_basis")
                        or f"n_usable={rec['n_usable']} is below the pre-registered "
                           f"{rec['planned_n']}")
    if rec.get("mutation_required") and rec.get("mutation_inverted") is not True:
        blockers.append("the mandatory mutation arm did not run, or did not invert")
    return {
        "case_id": rec["case_id"],
        "blockers": blockers,
        "clear_here": not blockers,
        "blockers_are_not_exhaustive": (
            "the >=2-separate-calendar-days replication rule, the archived x-amzn-requestid "
            "requirement and the alternative-explanation register are checked by "
            "check_amendment_readiness.py against the evidence records, not here"),
    }


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

MIN_BOUND_CASES = 93          # every case in CASES; mutation-tested in lib/tests/

# Class-S cases the sealed families block places in no family, so no multiplicity
# correction is defined for them. Found by the gate, not by reading: F10-1 (billing
# asymmetry — zero inference charge for input-blocked vs full charge for output-blocked)
# and F10-3 (tagged RAG prompts bill fewer text units than untagged) are statistical
# claims that the seal's `members` lists omit and whose class S the
# `descriptive_no_test.members_by_class` rule (C and O only) does not reach.
#
# The seal is SEALED and `verify_prereg.py --seal` refuses to re-stamp it (DEV-SEAL-1), so
# this cannot be repaired — nor should it be: adding F10-1 to a BH family after the gap was
# discovered would choose a family for a case whose data is not yet collected, which is the
# outcome-dependent move the freeze exists to block. It is declared here instead, and the
# gate compares the observed set against this one **in both directions**. A permanently-red
# gate would be worked around within a week; a gate that goes red the moment a *twelfth*
# case joins the gap, or a listed one leaves it, is one that still means something.
#
# Consequence carried into the report: F10-1 and F10-3 are single hypotheses at the nominal
# alpha, uncorrected, and are reported as such. See DEVIATIONS.md/DEV-P1-3.
DECLARED_SEAL_GAPS = frozenset({"F10-1", "F10-3"})


def prose_support_problems() -> list[str]:
    """Every way a binding can disagree with the sealed oracle it claims to implement.

    This is the module's own version of the check it applies to the document. A threshold
    that lives only in code is a number nobody verified; hoisting it into `thresholds` and
    re-deriving it from tokens asserted to be in the prose is what makes it checkable.
    """
    problems: list[str] = []
    C = cases()

    for cid in sorted(C):
        if cid not in BINDINGS:
            problems.append(f"{cid} is in CASES with no binding in lib/oracle.py, so its "
                            f"sealed oracle cannot be evaluated by anything")
    for cid in sorted(BINDINGS):
        if cid not in C:
            problems.append(f"binding {cid} names a case that is not in CASES")

    if len(BINDINGS) < MIN_BOUND_CASES:
        problems.append(f"only {len(BINDINGS)} bindings; the floor is {MIN_BOUND_CASES}. A "
                        f"floor below the current count would let a deleted binding pass")

    for cid, b in sorted(BINDINGS.items()):
        if cid not in C:
            continue
        text = C[cid][3]

        # The unit must match the field the kind compares against, not merely be internally
        # consistent with the prose token. This is what actually catches the F7-7 defect: a
        # 60-second grid declared as "ms" converts to 60000 without contradiction, and the
        # comparison is then against `timestamps_s` — seconds — so every offset passes.
        want_unit = KIND_UNITS.get(b.kind)
        if want_unit is not None and b.unit != want_unit:
            problems.append(
                f"{cid}: kind {b.kind} compares in {want_unit!r} (fixed by the Observation "
                f"field it reads) but the binding declares unit {b.unit!r}; a consistent "
                f"conversion into the wrong unit is still the wrong comparison")

        if len(b.thresholds) != len(b.prose):
            problems.append(
                f"{cid}: {len(b.thresholds)} threshold(s) but {len(b.prose)} prose "
                f"token(s). Every number the binding compares against must be traceable "
                f"to the sentence it came from, or it is an unverified constant")
            continue
        for t, tok in zip(b.thresholds, b.prose):
            if not _prose_contains(tok, text):
                problems.append(f"{cid}: prose token {tok!r} does not appear in the sealed "
                                f"oracle text, so threshold {t} rests on nothing")
                continue
            try:
                parsed = TRANSFORMS[b.transform](parse_prose_number(tok, b.unit))
            except ValueError as e:
                problems.append(f"{cid}: {e}")
                continue
            if not math.isclose(parsed, t, rel_tol=1e-9):
                problems.append(f"{cid}: prose token {tok!r} in unit {b.unit!r} under "
                                f"transform {b.transform!r} yields {parsed} but the binding "
                                f"says {t}")

        # An operationalisation is a threshold the prose does NOT state, and it is the one
        # place a sealed oracle can legitimately be turned into a comparison it does not
        # itself contain ("near 0" -> < 0.05). It is legitimate only if it is written down:
        # the note must say so, and DEVIATIONS.md must carry the rule.
        if "operationalis" in b.note.lower() or "operationaliz" in b.note.lower():
            if "OPERATIONALISATION" not in b.note and "operationalised as" not in b.note:
                problems.append(f"{cid}: the note gestures at an operationalisation without "
                                f"stating the rule; the substituted threshold has to be "
                                f"readable next to the prose it replaces")

        # A kind that needs a threshold and has none would silently compare against a
        # default, which is the same defect as a hardcoded number with no provenance.
        if b.kind in ("LOWER_ABOVE", "UPPER_BELOW", "ASYMMETRIC_FPR", "BAND_CONTAINS",
                      "CI_OVERLAPS", "ROC_LATTICE", "QUANTIZATION") and not b.thresholds:
            problems.append(f"{cid}: kind {b.kind} requires at least one threshold")
        if b.kind == "BAND_CONTAINS" and len(b.thresholds) != 2:
            problems.append(f"{cid}: BAND_CONTAINS needs exactly 2 thresholds "
                            f"(lo, hi), got {len(b.thresholds)}")

        # The cell a binding names must actually list the case, or planned_n is reading
        # somebody else's sample size.
        if b.cell is not None:
            cell = prereg()["sample_sizes"].get(b.cell)
            if cell is None:
                problems.append(f"{cid}: names sample-size cell {b.cell!r}, which is not "
                                f"in the pre-registration")
            elif cid not in (cell.get("applies_to") or []):
                problems.append(f"{cid}: names cell {b.cell!r}, but that cell's applies_to "
                                f"does not list {cid} — the n would come from a design "
                                f"decision made for other cases")

        # Class and kind must agree on whether a verdict is even available.
        cls = C[cid][2]
        if cls == "X" and b.kind != "NOT_TESTABLE":
            problems.append(f"{cid}: class X (excluded) but kind {b.kind} would produce a "
                            f"verdict; an excluded case must not enter a pass count")
        if b.kind == "NOT_TESTABLE" and cls != "X":
            problems.append(f"{cid}: kind NOT_TESTABLE but class {cls}; a case with an "
                            f"instrument must not be reported as untestable")

        # Every bound case must be placeable and evaluable. `family_of` used to raise for 11
        # of them, which meant `evaluate()` crashed on 12% of the sealed suite — a failure
        # that would have surfaced only when a family script ran, months into collection.
        # The gate now asks the question offline, for every case, on every run.
        try:
            fam = family_of(cid)
            alpha_for(cid)
        except Exception as e:                                    # noqa: BLE001
            problems.append(f"{cid}: cannot be placed in a family or given an alpha "
                            f"({type(e).__name__}: {e}); evaluate() would raise on it")
            continue
        if fam == UNASSIGNED and cls == "S" and cid not in DECLARED_SEAL_GAPS:
            problems.append(
                f"{cid}: class S with no family the seal declares, so no multiplicity "
                f"correction covers a statistical case, and it is not in "
                f"DECLARED_SEAL_GAPS. Either the seal covers it and the binding is wrong, "
                f"or the gap is real and must be declared and carried into the report")

    # The declared-gap list is checked in the closing direction too. A list that only ever
    # excuses failures becomes a permanent exemption nobody re-reads; this makes it a
    # two-way assertion, so a gap that closes (or a case that never had one) is a gate
    # failure rather than a stale line in a constant.
    for cid in sorted(DECLARED_SEAL_GAPS):
        if cid not in BINDINGS:
            problems.append(f"DECLARED_SEAL_GAPS names {cid}, which has no binding")
            continue
        if family_of(cid) != UNASSIGNED:
            problems.append(
                f"{cid} is declared a seal gap but the seal now places it in family "
                f"{family_of(cid)!r}; the declaration is stale and the report's "
                f"'uncorrected single hypothesis' statement about it is now false")
        elif C[cid][2] != "S":
            problems.append(f"{cid} is declared a seal gap on the strength of being class S "
                            f"but is class {C[cid][2]!r}")

    # Every case with a mandatory mutation must be bound to a kind that can express the
    # inversion, and must not be RECORDED-only... except where the pre-registration itself
    # declares the outcome unknown (F5-4b), where the mutation restores a permission
    # rather than predicting a direction.
    for cid in sorted(prereg()["validity_checks"]
                      ["mutation_arms_are_mandatory"]["applies_to"]):
        if cid not in BINDINGS:
            problems.append(f"{cid} has a mandatory mutation arm but no binding")
        elif BINDINGS[cid].kind == "NOT_TESTABLE":
            problems.append(f"{cid} has a mandatory mutation arm but is bound NOT_TESTABLE")

    return problems


def main(argv: list[str] | None = None) -> int:
    problems = prose_support_problems()
    C = cases()
    print(f"cases: {len(C)}   bindings: {len(BINDINGS)}   kinds in use: "
          f"{len({b.kind for b in BINDINGS.values()})}/{len(KINDS)}")
    counts: dict[str, int] = {}
    for b in BINDINGS.values():
        counts[b.kind] = counts.get(b.kind, 0) + 1
    for k in sorted(counts, key=lambda x: (-counts[x], x)):
        print(f"  {counts[k]:>3}  {k}")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nevery binding is traceable to its sealed oracle text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
