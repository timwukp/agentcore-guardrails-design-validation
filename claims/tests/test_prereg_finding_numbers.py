"""Every number in FINDING-P0-PREREG.md must still be true of the artifacts.

Same discipline as test_finding_numbers.py: a write-up's figures decay the moment
the design changes, and they decay silently in the flattering direction. Each
figure here is re-derived from PREREGISTRATION.yaml or from lib/stats.py, so a
change to a sample size breaks a test rather than leaving a stale claim in a
report.

It also re-checks the two bounds the finding's argument rests on — 7.13% at n=60
with one false positive, and 9.42% at the Bonferroni level — because those are the
numbers that make DEV-P0-2 and DEV-P0-3 corrections rather than opinions.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

FINDING = ROOT / "results" / "FINDING-P0-PREREG.md"
PREREG = ROOT / "PREREGISTRATION.yaml"
STAMP = ROOT / "PREREGISTRATION.sha256"
VERIFIER = ROOT / "verify_prereg.py"
SUITE = HERE / "test_prereg_verifier.py"


@pytest.fixture(scope="module")
def doc() -> str:
    assert FINDING.exists(), f"{FINDING.name} not written"
    return FINDING.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pr() -> dict:
    return yaml.safe_load(PREREG.read_text(encoding="utf-8"))


def _pin(doc: str, needle: str) -> None:
    assert needle in doc, f"FINDING-P0-PREREG.md no longer states {needle!r}"


def one_sided_hi(x: int, n: int, alpha: float = 0.05) -> float:
    from lib import stats as S
    return S.wilson_ci(x, n, level=1 - 2 * alpha).hi


# ---- the bounds the argument rests on ---------------------------------------

def test_the_713_percent_bound_that_justifies_dev_p0_2(doc):
    """If this is not 7.13%, DEV-P0-2 is not a correction."""
    got = one_sided_hi(1, 60)
    assert f"{got:.2%}" == "7.13%"
    _pin(doc, "**7.13%**")
    _pin(doc, "| 60 | 4.31% | **7.13%** |")


def test_n87_clears_the_five_percent_rule_with_one_false_positive(doc):
    got = one_sided_hi(1, 87)
    assert got < 0.05
    assert f"{got:.2%}" == "4.99%"
    _pin(doc, "| 87 | 3.06% | **4.99%** |")


def test_n86_does_not_clear_it_so_87_is_minimal():
    """The finding calls 87 the sized minimum; 86 must fail."""
    assert one_sided_hi(1, 86) >= 0.05


def test_the_942_percent_bound_that_justifies_dev_p0_3(doc, pr):
    """A control passing 60 times is consistent with a ~1-in-11 failure rate."""
    a = pr["derived"]["bonferroni_per_hypothesis_alpha"]["value"]
    got = one_sided_hi(0, 60, a)
    assert f"{got:.2%}" == "9.42%"
    assert 1 / got == pytest.approx(10.6, abs=0.5), "the '1 in 11' phrasing"
    _pin(doc, "| 60 | **9.42%** |")
    _pin(doc, "**1 request in 11**")


def test_119_is_the_minimal_confirmatory_n(doc, pr):
    a = pr["derived"]["bonferroni_per_hypothesis_alpha"]["value"]
    assert one_sided_hi(0, 119, a) < 0.05 <= one_sided_hi(0, 118, a)
    assert f"{one_sided_hi(0, 119, a):.2%}" == "4.98%"
    _pin(doc, "| 119 | 4.98% |")


def test_the_weak_recall_oracle_figures(doc, pr):
    """DEV-P0-4's premise, recomputed.

    This test is why DEV-SEAL-2 exists. Its first version asserted the finding's
    claim that the rule is 'satisfied at n=10 by an 80% observed recall' — and
    failed, because wilson_ci(8,10).lo = 0.4902. The false figure had been sealed
    into PREREGISTRATION.yaml inside a prose `rule:` string that no check parsed.
    """
    from lib import stats as S
    w = pr["sample_sizes"]["attack_recall_cell"]["oracle_is_weak_at"]

    # satisfiable at n=4 with perfect recall
    assert w["smallest_satisfying_n"] == 4
    assert S.wilson_ci(4, 4).lo > 0.5
    assert S.wilson_ci(3, 3).lo <= 0.5, "then 4 is not the smallest"
    _pin(doc, "| 4/4 — smallest satisfying n | **4** | 0.5101 | yes |")

    # and at n=8 without perfect recall, so the weakness is not an artefact of a
    # flawless run
    assert w["smallest_n_below_perfect_recall"] == 8
    assert S.wilson_ci(7, 8).lo > 0.5
    assert not any(S.wilson_ci(x, n).lo > 0.5
                   for n in range(1, 8) for x in range(n))
    _pin(doc, "| 7/8 — smallest without perfect recall | **8** | 0.5291 | yes |")

    # the refuted figure, retained as a pinned counterexample
    assert S.wilson_ci(8, 10).lo < 0.5
    assert f"{S.wilson_ci(8, 10).lo:.4f}" == "0.4902"
    _pin(doc, "| 8/10 | 10 | 0.4902 | no |")


def test_the_finding_records_the_post_seal_defect(doc):
    """DEV-SEAL-2 must be reported, not quietly fixed."""
    _pin(doc, "A false figure inside the sealed file")
    _pin(doc, "DEV-SEAL-2")
    _pin(doc, "a justification that is not machine-checkable is not\nverified")


def test_the_prose_rule_no_longer_carries_the_false_figure(pr):
    """The refuted claim must be gone from the string it was sealed into.

    Checking the prose as well as the data, because the data block only helps if
    the sentence it replaced was actually removed — otherwise the file states
    both.
    """
    rule = pr["sample_sizes"]["attack_recall_cell"]["rule"]
    why = next(d["why"] for d in pr["deviations_from_plan"]
               if d["id"] == "DEV-P0-4")
    for text in (rule, why):
        assert "satisfied at n=10" not in text
        assert "n=10 by an 80%" not in text
    assert "n=4" in rule and "n=8" in rule


def test_deletion_is_as_loud_as_falsification(pr):
    """DEV-SEAL-2's structural fix: every field the checks read is required."""
    import importlib
    vp = importlib.import_module("verify_prereg")
    assert vp.missing_required_fields(pr) == []
    import copy
    d = copy.deepcopy(pr)
    del d["sample_sizes"]["attack_recall_cell"]["oracle_is_weak_at"]
    assert len(vp.missing_required_fields(d)) == 5


def test_the_half_width_rule_gives_87(doc, pr):
    from lib import stats as S

    def hw(n: int, p: float = 0.85) -> float:
        ci = S.wilson_ci(round(p * n), n)
        return (ci.hi - ci.lo) / 2

    assert hw(87) <= 0.075 < hw(86)
    assert pr["sample_sizes"]["attack_recall_cell"]["n"] == 87
    _pin(doc, "half-width ≤ 0.075")


def test_the_sidedness_defect_numbers(doc, pr):
    """§4.1's before/after: 0.043 vs 0.759 (mixed) and 0.060 vs 0.739 (consistent)."""
    from lib import stats as S
    dj = pr["sample_sizes"]["multilingual_cell"]["disjointness_check"]
    assert f"{one_sided_hi(0, 60):.3f}" == "0.043", "the one-sided value first used"
    assert f"{S.wilson_ci(51, 60).lo:.3f}" == "0.739"
    assert f"{S.wilson_ci(0, 60).hi:.3f}" == "0.060"
    assert dj["classic_upper_at_x0_n60"] == pytest.approx(0.06017, abs=1e-5)
    assert dj["en_lower_at_p85_n60"] == pytest.approx(0.738854, abs=1e-5)
    _pin(doc, "**0.060 vs 0.739**")
    assert dj["classic_upper_at_x0_n60"] < dj["en_lower_at_p85_n60"]


# ---- counts ------------------------------------------------------------------

def test_assertion_count_is_not_overstated(doc):
    """The finding cites 120; it may grow, but must not be overstated."""
    r = subprocess.run([sys.executable, str(VERIFIER)], capture_output=True,
                       text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stdout
    m = re.search(r"OK — (\d+) assertions", r.stdout)
    assert m, f"verifier output changed shape: {r.stdout!r}"
    actual = int(m.group(1))
    claimed = int(re.search(r"\| \*\*(\d+)\*\* \|", doc).group(1))
    assert claimed <= actual, f"finding claims {claimed} assertions, verifier runs {actual}"
    _pin(doc, "112")


def test_mutation_test_count_is_not_overstated(doc):
    """Counts COLLECTED tests, not `def test_` lines — the suite is parametrised.

    Counting defs would report 40 against a truthful 45 and make a correct figure
    look overstated. The same slip was present in test_finding_numbers.py.
    """
    m = re.search(r"\*\*(\d+)\*\* \(incl\. (\d+) control arms\)", doc)
    assert m, "the finding no longer states a mutation-test count"
    # The control-arm count is read from the document and checked against the
    # suite, not pinned as a literal in this regex: a hardcoded "2" made this test
    # fail on the legitimate addition of a third arm, which trains the reader to
    # edit the test rather than the document (same defect as the hardcoded seal).
    n_arms = len([ln for ln in SUITE.read_text(encoding="utf-8").splitlines()
                  if ln.startswith("def test_control_arm")])
    assert int(m.group(2)) == n_arms, (
        f"the finding says {m.group(2)} control arms, the suite defines {n_arms}")
    r = subprocess.run([sys.executable, "-m", "pytest", str(SUITE), "-q",
                        "--collect-only", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, cwd=str(ROOT))
    got = re.search(r"(\d+) tests? collected", r.stdout)
    assert got, f"could not read a collected count:\n{r.stdout[-500:]}"
    actual = int(got.group(1))
    assert actual > 0, "collecting zero tests must not read as agreement"
    assert int(m.group(1)) <= actual, (
        f"finding claims {m.group(1)}, pytest collects {actual}")


def test_every_control_arm_is_named_in_the_finding(doc):
    """Each arm must be described in the prose, not just counted in the table.

    The count alone was checkable before an arm was added and stayed checkable
    after; what it could not catch is §5 continuing to say 'Two control arms, not
    one' and explaining only two of the three. So this asserts the SET, keyed on
    the reason each arm exists — a fourth arm added without a sentence explaining
    what it protects against will fail here.
    """
    src = SUITE.read_text(encoding="utf-8")
    arms = {ln.split("(")[0][len("def "):] for ln in src.splitlines()
            if ln.startswith("def test_control_arm")}
    assert arms == {
        "test_control_arm_unmutated_tree_passes",
        "test_control_arm_survives_a_yaml_roundtrip",
        "test_control_arm_the_unpatched_verifier_clears_every_per_check_floor",
    }, "a control arm was added or renamed; §5's prose must say what it protects"

    _pin(doc, f"{len(arms)} control arms")
    _pin(doc, "Three control arms, not one")
    for needle in ("an unmutated tree must pass",
                   "no-op YAML round-trip",
                   "clear every per-check assertion"):
        _pin(doc, needle)


def test_family_count_and_disjointness(doc, pr):
    fams = pr["families"]
    assert len(fams) == 7
    _pin(doc, "| Hypothesis families declared, disjointness enforced | 7 |")
    seen: set[str] = set()
    for spec in fams.values():
        members = set(spec.get("members", []))
        assert not (members & seen), f"families overlap at {members & seen}"
        seen |= members


def test_every_deviation_from_plan_is_recorded(doc, pr):
    """The finding's count of corrected sizes must track the YAML, not a memory.

    The split is read from each entry's `corrects` field. It used to be inferred
    from the PRESENCE of a `design_impact` field, which was accurate for six
    entries and wrong for both that followed — DEV-P0-7 changes no size (its own
    design_impact says so) and DEV-P0-8 corrects a size this FILE set, not one the
    plan set. The proxy would have published 7 where the answer is 5, and wrongly
    in two different ways at once. See DEVIATIONS.md/DEV-SEAL-6.

    A count read from a structural accident is not better verified than prose; it
    is worse, because it looks computed.
    """
    devs = pr["deviations_from_plan"]
    ids = [d["id"] for d in devs]
    assert ids == [f"DEV-P0-{i}" for i in range(1, len(devs) + 1)], \
        "the ids are not a contiguous run, so one was deleted or renumbered"
    assert len(devs) == 8

    plan_sizes = [d["id"] for d in devs if d["corrects"] == "plan_size"]
    assert plan_sizes == ["DEV-P0-1", "DEV-P0-2", "DEV-P0-3", "DEV-P0-4",
                         "DEV-P0-6"]
    _pin(doc, f"| Plan sizes corrected | **{len(plan_sizes)}** |")

    # The three non-plan-size entries, each named with its class, so a
    # reclassification cannot pass silently.
    assert {d["id"]: d["corrects"] for d in devs
            if d["corrects"] != "plan_size"} == {
        "DEV-P0-5": "convention",
        "DEV-P0-7": "provenance",
        "DEV-P0-8": "prereg_size",
    }
    _pin(doc, f"| Sizes this file set and then corrected | **1** |")
    for d in ids:
        _pin(doc, d)


def test_the_deviation_class_is_not_a_free_label(pr):
    """Mutation control: the classification must be checkable, not just present.

    Without this, `corrects` could be set to anything and the count above would
    faithfully report a fiction. The verifier's own consistency rule is what makes
    the label answerable to the entry it labels, so it is exercised here directly.
    """
    import importlib
    import copy
    vp = importlib.import_module("verify_prereg")

    problems: list[str] = []
    assert vp.check_deviation_classes(pr, problems) > 0
    assert problems == [], f"the live file does not satisfy its own rule: {problems}"

    # A provenance entry whose design_impact states a size transition is a
    # contradiction and must be caught.
    d = copy.deepcopy(pr)
    ent = next(x for x in d["deviations_from_plan"] if x["id"] == "DEV-P0-7")
    ent["design_impact"] = "hard_negatives 69 -> 60"
    problems = []
    vp.check_deviation_classes(d, problems)
    assert any("states a transition" in p for p in problems)

    # An unknown class, and a class with no reason, must both fail.
    for field, value, needle in [("corrects", "cosmetic", "is not one of"),
                                 ("corrects_why", "  ", "no corrects_why")]:
        d = copy.deepcopy(pr)
        next(x for x in d["deviations_from_plan"]
             if x["id"] == "DEV-P0-8")[field] = value
        problems = []
        vp.check_deviation_classes(d, problems)
        assert any(needle in p for p in problems), f"{field}={value!r} not caught"

    # Deleting an entry to lower the count must break the contiguity check.
    d = copy.deepcopy(pr)
    del d["deviations_from_plan"][3]
    problems = []
    vp.check_deviation_classes(d, problems)
    assert any("contiguous run" in p for p in problems)


def test_corpora_still_exceed_their_sized_minimums(doc, pr):
    """hard_negatives is 60 after DEV-P0-8, not the 69 DEV-P0-2 first set.

    The margin over the sized minimum is asserted rather than the literal, because
    what makes the cell valid is `total >= n`, and pinning only the literal would
    keep passing if the minimum rose past it.
    """
    ss, co = pr["sample_sizes"], pr["corpora"]
    assert co["benign"]["total"] == 110 >= ss["benign_fpr_cell"]["n"]
    assert co["hard_negatives"]["total"] == 60 >= ss["hard_negative_cell"]["n"] == 58
    _pin(doc, "Benign 60→110, hard negatives 60→69→60")


# ---- sealing properties ------------------------------------------------------

def test_the_finding_quotes_the_actual_seal(doc):
    """The finding must quote the LIVE seal, whatever it currently is.

    Derived from PREREGISTRATION.sha256 rather than hardcoded: a literal here
    would fail on every legitimate re-seal even when the finding had been updated
    correctly, which trains the reader to edit the test instead of the document.
    The first version of this test did hardcode it, and did exactly that on the
    DEV-SEAL-2 re-seal.
    """
    pinned = STAMP.read_text(encoding="utf-8").split()[0]
    assert len(pinned) == 64
    _pin(doc, f"`{pinned[:12]}…`")
    # And the stamp must match the file it claims to seal.
    import hashlib
    assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == pinned


def test_deviations_file_records_every_reseal_as_an_unbroken_chain():
    """Each entry's 'hash before' must be the previous entry's 'hash after'.

    A chain, not a set of pairs: that is what makes the history complete rather
    than merely present. If a re-seal happened without an entry, the chain breaks
    at that point — which is precisely the event this file exists to prevent
    going unrecorded.
    """
    import re as _re
    dev = (ROOT / "DEVIATIONS.md").read_text(encoding="utf-8")
    befores = _re.findall(r"\*\*Hash before:\*\* `([0-9a-f]{64})`", dev)
    afters = _re.findall(r"\*\*Hash after:\*\* `([0-9a-f]{64})`", dev)
    assert len(befores) == len(afters) >= 2, "expected at least DEV-SEAL-1 and -2"
    for i in range(1, len(befores)):
        assert befores[i] == afters[i - 1], (
            f"chain breaks at entry {i + 1}: before={befores[i][:12]}… but the "
            f"previous entry ended at {afters[i - 1][:12]}… — an unrecorded re-seal")
    pinned = STAMP.read_text(encoding="utf-8").split()[0]
    assert afters[-1] == pinned, "the last recorded hash is not the live seal"
    # Every entry must state whether data existed; that field decides how much
    # the change matters.
    assert dev.count("**Data existed:**") == len(befores)
    assert "DEV-SEAL-1" in dev and "DEV-SEAL-2" in dev


def test_oracle_registry_hash_is_pinned_and_current(pr):
    import json
    sys.path.insert(0, str(ROOT / "claims"))
    import hashlib
    import triage_rules as R
    canon = json.dumps({c: R.CASES[c][3] for c in sorted(R.CASES)},
                       sort_keys=True, ensure_ascii=False)
    got = hashlib.sha256(canon.encode()).hexdigest()
    assert got == pr["meta"]["oracle_registry"]["sha256"], (
        "an oracle changed after sealing — this requires a DEVIATIONS.md entry")


# ---- honesty properties ------------------------------------------------------

def test_finding_records_defects_in_its_own_design():
    """Section 4 is the calibration section, as in FINDING-P0-TRIAGE."""
    text = FINDING.read_text(encoding="utf-8")
    assert "Defects the verifier found in the pre-registration itself" in text
    for defect in ("sidedness mismatch", "no declared decision rule"):
        assert defect in text, f"self-caught defect no longer recorded: {defect!r}"


def test_finding_states_zero_spend():
    text = FINDING.read_text(encoding="utf-8")
    assert "**$0**" in text


def test_finding_carries_no_cloud_identifiers():
    text = FINDING.read_text(encoding="utf-8")
    assert re.findall(r"\b\d{12}\b", text) == []
    assert "arn:aws:" not in text
