"""Mutation suite for verify_prereg.py.

Per feedback_vacuous_test_check: `verify_prereg.py` reporting 120 green
assertions proves nothing until each class of tampering is shown to make it fail.
The mutations below are the ways a pre-registration could be quietly weakened
after the fact — a sample size lowered, an oracle reworded, a family grown so the
Bonferroni divisor changes, a corpus shrunk below its sized minimum — and each
must be caught.

The control arm comes first: a check that fired unconditionally would "kill"
every mutant and score a perfect 100% while verifying nothing.

Every test operates on a COPY in tmp_path. The real PREREGISTRATION.yaml is
never modified, because a test that mutates the artifact it verifies can leave
the tree poisoned if it dies mid-run — which already happened once in this
project with a redaction canary.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
VERIFIER = ROOT / "verify_prereg.py"
PREREG = ROOT / "PREREGISTRATION.yaml"

# Read from the pre-registration rather than hardcoded, so a corpus that moves
# does not leave this suite quietly copying nothing.
SOURCE_CORPUS_REL = yaml.safe_load(
    PREREG.read_text(encoding="utf-8")
)["corpora"]["pii"]["source_corpus_audit"]["path"]


def run_verifier(cwd: Path) -> subprocess.CompletedProcess:
    """Run the verifier as a subprocess against a copied tree.

    A subprocess rather than an in-process call because the verifier resolves
    every path from its own __file__, so only a real copied tree exercises the
    same code path the operator runs.
    """
    return subprocess.run([sys.executable, str(cwd / "verify_prereg.py")],
                          capture_output=True, text=True, cwd=str(cwd))


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal copy of the repo sufficient for the verifier to run.

    The copy is normalised to a PRE-SEAL state: status reset to
    SEALED_PENDING_STAMP and no stamp file. The real PREREGISTRATION.yaml is
    sealed, and copying it verbatim would make every sealing test fail for a
    reason unrelated to what it tests — which is exactly what happened on the
    first run of this suite. Normalising here keeps the suite independent of
    whether the live file happens to be sealed at the moment it runs.
    """
    dst = tmp_path / "grx"
    dst.mkdir()
    shutil.copy2(VERIFIER, dst / "verify_prereg.py")
    text = PREREG.read_text(encoding="utf-8")
    assert "status: SEALED" in text, "the status field this fixture rewrites is gone"
    text = text.replace("status: SEALED_PENDING_STAMP", "status: SEALED", 1)
    text = text.replace("status: SEALED", "status: SEALED_PENDING_STAMP", 1)
    (dst / "PREREGISTRATION.yaml").write_text(text, encoding="utf-8")
    shutil.copytree(ROOT / "lib", dst / "lib",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "claims", dst / "claims",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    # DEV-P0-6's audit of the source PII corpus is recomputed from .jsonl files
    # in a SIBLING repository, addressed relative to the tree root. Copying them
    # to the same relative position is what makes those assertions live in the
    # mutant; without it they would silently take the skip branch and every
    # mutation of an item count would "pass" for the wrong reason.
    src_corpus = (ROOT / SOURCE_CORPUS_REL).resolve()
    if src_corpus.is_dir():
        shutil.copytree(src_corpus, (dst / SOURCE_CORPUS_REL).resolve())
    # corpora/ holds build.py, from which check_entity_screen_exclusions() IMPORTS
    # the screen. Without it that check takes its "could not import" NOTE branch
    # and returns early — so DEV-P0-8's exclusion assertions were skipping in every
    # mutant, exactly the failure the src_corpus copy above exists to prevent, one
    # directory over. Found by a mutation of the exclusion count that should have
    # been killed and was not (DEV-SEAL-6).
    shutil.copytree(ROOT / "corpora", dst / "corpora",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dst


def test_the_fixture_does_not_silently_skip_a_whole_check(tree):
    """The fixture must reproduce the checks, not a subset of them.

    Every "NOTE: ... was NOT recomputed" line in the verifier marks a check that
    disables itself when an input is absent. That behaviour is right for an
    operator on a machine without the sibling corpus, and wrong here: a mutant
    tree missing an input scores a kill for whatever else failed, or no kill at
    all. Asserting on the NOTES rather than on one named directory covers the
    class, so adding a third optional input cannot quietly reopen the hole.
    """
    r = run_verifier(tree)
    notes = [ln for ln in r.stdout.splitlines() if "NOT recomputed" in ln]
    assert notes == [], (
        "the mutation fixture is missing inputs, so these checks did not run "
        "against any mutant:\n  " + "\n  ".join(notes))


def test_the_live_prereg_is_sealed_and_verifies():
    """The fixture normalises its copy, so something must still check the real file.

    Without this, the suite could pass in full while the actual
    PREREGISTRATION.yaml was unsealed or failing — the fixture would have hidden
    it. This asserts the live artifact, not a copy.
    """
    import subprocess as sp
    stamp = ROOT / "PREREGISTRATION.sha256"
    assert stamp.exists(), "the live pre-registration is not sealed"
    doc = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    assert doc["meta"]["status"] == "SEALED"
    r = sp.run([sys.executable, str(VERIFIER)], capture_output=True, text=True,
               cwd=str(ROOT))
    assert r.returncode == 0, f"the live pre-registration does not verify:\n{r.stdout}"
    assert "SEALED, hash matches" in r.stdout


def mutate(tree: Path, fn) -> None:
    """Apply fn to the parsed YAML and write it back."""
    path = tree / "PREREGISTRATION.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")


def mutate_existing(tree: Path, dotted: str, value) -> None:
    """Falsify a field that must ALREADY EXIST, addressed by dotted path.

    Why this exists (DEV-SEAL-6). A mutation that sets a key the verifier does not
    read is not a mutation — it adds an unused key, and the test then passes on
    whatever else happened to fail in the same run. That is not hypothetical: this
    suite carried such a test for one amendment, after DEV-SEAL-4 renamed
    `authored_new` to `positive_items_authored`. The test had been written
    correctly and verified as killing; the rename broke it without breaking it
    visibly, because `mutate()` will happily create any key handed to it.

    So the precondition is the point: falsifying a field REQUIRES the field, and a
    renamed or deleted target must fail here rather than pass. Use this in
    preference to `mutate()` wherever the mutation is "change an existing value";
    `mutate()` remains correct for structural mutations (adding a family member,
    deleting a block) where the key genuinely should not already be there.
    """
    parts = dotted.split(".")

    def fn(d):
        node = d
        for p in parts[:-1]:
            assert isinstance(node, dict) and p in node, \
                f"mutation target {dotted!r} does not exist (missing at {p!r}) — " \
                f"the field was renamed or removed, so this mutation would test nothing"
        # walked separately so the assertion message can name the failing segment
            node = node[p]
        assert parts[-1] in node, (
            f"mutation target {dotted!r} does not exist — the field was renamed or "
            f"removed, so setting it would add an unread key and this test would "
            f"pass without mutating anything")
        assert node[parts[-1]] != value, (
            f"mutation target {dotted!r} already holds {value!r}, so this mutation "
            f"changes nothing")
        node[parts[-1]] = value

    mutate(tree, fn)


# ---- control arm -------------------------------------------------------------

def test_control_arm_unmutated_tree_passes(tree):
    """If this fails, every kill below is meaningless."""
    r = run_verifier(tree)
    assert r.returncode == 0, f"control arm failed:\n{r.stdout}\n{r.stderr}"
    assert "every derived value recomputed" in r.stdout


def test_control_arm_survives_a_yaml_roundtrip(tree):
    """The mutations rewrite the YAML, so the rewrite itself must be harmless.

    Without this, a formatting-induced failure would be indistinguishable from a
    genuine kill and every mutation would look successful.
    """
    mutate(tree, lambda d: None)
    r = run_verifier(tree)
    assert r.returncode == 0, f"a no-op roundtrip broke the verifier:\n{r.stdout}"


# ---- mutations on the derived constants --------------------------------------

def test_kills_restored_298(tree):
    """The project's original error, reintroduced deliberately."""
    def m(d):
        d["derived"]["determinism_zero_event_n"]["value"] = 298
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "determinism_zero_event_n.value" in r.stdout


def test_kills_298_with_its_justification_also_edited(tree):
    """The subtler version: change the number AND the powers that justify it.

    A verifier that only checked internal consistency would pass this. It is
    caught because the powers are recomputed from the power function, not read
    from the file.
    """
    def m(d):
        dz = d["derived"]["determinism_zero_event_n"]
        dz["value"] = 298
        dz["power_at_298"] = 0.951      # a lie that makes 298 look sufficient
        dz["power_at_299"] = 0.952
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "power_at_298" in r.stdout


def test_kills_wrong_bonferroni_divisor(tree):
    """alpha/4 while the family has 8 members would halve every corrected p."""
    def m(d):
        d["derived"]["bonferroni_per_hypothesis_alpha"]["value"] = 0.0125
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "bonferroni_per_hypothesis_alpha" in r.stdout


def test_kills_wrong_order_statistic(tree):
    def m(d):
        d["derived"]["latency_p99_order_statistics"]["lower_order_stat"] = 950
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "lower_order_stat" in r.stdout


# ---- mutations on the sample sizes -------------------------------------------

def test_kills_benign_cell_lowered_to_60(tree):
    """The exact weakening DEV-P0-2 exists to prevent."""
    def m(d):
        d["sample_sizes"]["benign_fpr_cell"]["n"] = 60
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "benign_fpr_cell" in r.stdout


def test_kills_confirmatory_cell_lowered(tree):
    def m(d):
        d["sample_sizes"]["confirmatory_e_cell"]["n"] = 60
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "confirmatory_e_cell" in r.stdout


def test_kills_determinism_cell_below_the_derived_requirement(tree):
    def m(d):
        d["sample_sizes"]["determinism_cell"]["n"] = 250
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "below the derived requirement" in r.stdout


def test_kills_p99_claim_at_n_200(tree):
    """Moving the p99 arm to n=200 truncates the interval at the sample max."""
    def m(d):
        d["sample_sizes"]["latency_arm_p99"]["n"] = 200
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "truncated" in r.stdout or "latency_arm_p99" in r.stdout


def test_kills_non_disjoint_multilingual_intervals(tree):
    def m(d):
        d["sample_sizes"]["multilingual_cell"]["disjointness_check"][
            "classic_upper_at_x0_n60"] = 0.9
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "multilingual_cell" in r.stdout


def test_kills_the_false_n10_claim_if_it_returns(tree):
    """DEV-SEAL-2's defect, reintroduced as data rather than as prose.

    The original claim was "the oracle is satisfied at n=10 by an 80% observed
    recall", and wilson_ci(8,10).lo = 0.4902 refutes it. Asserting the refuted
    bound directly, because that is the field the claim would have to live in
    now: while it sat in an unparsed `rule:` string, nothing could catch it.
    """
    def m(d):
        d["sample_sizes"]["attack_recall_cell"]["oracle_is_weak_at"][
            "lower_bound_at_n_10_x_8"] = 0.5101   # a bound that WOULD satisfy 0.5
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "lower_bound_at_n_10_x_8" in r.stdout


def test_deleting_the_weakness_block_is_not_a_way_to_skip_its_checks(tree):
    """A check that vanishes with its data is not a check.

    The eight assertions added in DEV-SEAL-2 all read oracle_is_weak_at. If
    removing the block made the verifier skip them and still exit 0, the fix
    would be defeatable by deletion — which is easier than lying.

    Exit 2, not 1: a deleted commitment is an unusable input, not a
    disagreement. Before the precondition pass existed this raised a bare
    KeyError — the right code by accident, reported as a crash.
    """
    def m(d):
        del d["sample_sizes"]["attack_recall_cell"]["oracle_is_weak_at"]
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 2, f"removing the block gave rc={r.returncode}"
    assert "would be SKIPPED rather than run" in r.stderr
    assert "oracle_is_weak_at.smallest_satisfying_n" in r.stderr
    assert "Traceback" not in r.stderr, "reported as a crash, not as a finding"


@pytest.mark.parametrize("path", [
    ("derived", "bonferroni_per_hypothesis_alpha"),
    ("sample_sizes", "benign_fpr_cell"),
    ("sample_sizes", "confirmatory_e_cell"),
    ("sample_sizes", "multilingual_cell"),
    ("families",),
    ("corpora",),
])
def test_deleting_any_required_section_exits_2(tree, path):
    """The precondition list must cover every section the checks read, not one.

    Parametrised because a list naming only the field that prompted it would be
    a fix for one instance of the bug rather than for the bug.
    """
    def m(d):
        node = d
        for part in path[:-1]:
            node = node[part]
        del node[path[-1]]
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 2, f"deleting {'.'.join(path)} gave rc={r.returncode}"
    assert "Traceback" not in r.stderr


def test_the_precondition_list_is_not_vacuous():
    """Mutation-check the guard itself, per feedback_vacuous_test_check.

    A missing_required_fields() that returned [] unconditionally would pass every
    test above. So: it must find nothing in the real file, and must find the
    named field once that field is removed from a copy.
    """
    sys.path.insert(0, str(ROOT))
    import importlib
    vp = importlib.import_module("verify_prereg")
    doc = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    assert vp.missing_required_fields(doc) == [], "the live file is incomplete"
    del doc["sample_sizes"]["confirmatory_e_cell"]["bound_at_119"]
    found = vp.missing_required_fields(doc)
    assert "sample_sizes.confirmatory_e_cell.bound_at_119" in found
    assert len(found) == 1, f"one deletion reported as {len(found)} problems"


def test_kills_a_non_minimal_smallest_n(tree):
    """The exact mistake the new check caught in my own first correction.

    n=5 satisfies the oracle at 5/5, so calling it the SMALLEST satisfying n is
    false while every individual bound in the block stays arithmetically correct.
    A verifier that only recomputed the bounds would pass this.
    """
    def m(d):
        w = d["sample_sizes"]["attack_recall_cell"]["oracle_is_weak_at"]
        w["smallest_satisfying_n"] = 5
        w["lower_bound_at_that_n"] = 0.5654775668382794   # wilson_ci(5,5).lo
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "also does" in r.stdout


def test_kills_a_wrong_bound_in_the_oracle_weakness_block(tree):
    def m(d):
        d["sample_sizes"]["attack_recall_cell"]["oracle_is_weak_at"][
            "lower_bound_at_n_10_x_8"] = 0.6
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "lower_bound_at_n_10_x_8" in r.stdout


def test_the_satisfies_rule_helper_does_not_claim_minimality():
    """DEV-SEAL-2's second defect: a helper named minimal() that never checked n-1.

    Asserted on the source because the bug was in the NAME and DOCSTRING, which
    no behavioural test can see — and a misleading name is what stopped the real
    check being written for four call sites.
    """
    src = VERIFIER.read_text(encoding="utf-8")
    assert "def minimal(" not in src, "the misleading helper name is back"
    assert "def satisfies_rule(" in src
    head = src.split("def satisfies_rule(")[1].split('"""')[2]
    assert "minimal(" not in head, "call sites still use the old name"


# ---- mutations on the corpora ------------------------------------------------

def test_kills_corpus_below_its_sized_minimum(tree):
    def m(d):
        d["corpora"]["benign"]["total"] = 40
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "below the sized minimum" in r.stdout


def test_kills_corpus_arithmetic_that_does_not_close(tree):
    def m(d):
        d["corpora"]["content_filter"]["total"] = 999
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "total !=" in r.stdout


# ---- mutations on DEV-P0-6's PII cell and source-corpus audit ----------------
#
# The PII cell is the newest and least-exercised part of the pre-registration, so
# it gets the same treatment the oracle_is_weak_at block got: every figure that a
# reader would take on trust is mutated to confirm a check reads it. Two of these
# reproduce errors actually made while writing DEV-P0-6.

def test_the_source_corpus_audit_assertions_are_live_not_skipped(tree):
    """The audit's item counts are worthless if the corpus is not in the mutant.

    check_pii_source_audit() SKIPS its four item-count assertions when the source
    corpus is absent, which is correct for a reader who lacks the sibling repo and
    fatal for a mutation suite: every item-count mutation below would pass by
    taking the skip branch. This asserts the fixture put the corpus in place and
    the verifier actually read it.
    """
    audit = yaml.safe_load((tree / "PREREGISTRATION.yaml").read_text(
        encoding="utf-8"))["corpora"]["pii"]["source_corpus_audit"]
    assert (tree / audit["path"]).is_dir(), "the fixture did not copy the corpus"
    r = run_verifier(tree)
    assert r.returncode == 0
    assert "source PII corpus absent" not in r.stdout, \
        "the verifier took the skip branch, so the item-count checks did not run"


def test_kills_a_pii_cell_sized_below_its_own_power_rule(tree):
    """n=10 gives 94.4% power, not 95% — the value the rule actually requires."""
    def m(d):
        d["sample_sizes"]["pii_per_entity_cell"]["n"] = 10
        d["corpora"]["pii"]["per_entity"] = 10
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "pii_per_entity_cell" in r.stdout


def test_kills_a_pii_cell_too_small_for_its_oracle_to_fire(tree):
    """Below n=4 the oracle cannot fire at x=0, so the cell cannot conclude.

    An entity that detects nothing would be reported as "not falsified" — the
    failure mode the sizing rule exists to prevent, and the one a flat corpus
    total had.
    """
    def m(d):
        d["sample_sizes"]["pii_per_entity_cell"]["n"] = 3
        d["corpora"]["pii"]["per_entity"] = 3
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1


def test_kills_a_wrong_oracle_firing_floor(tree):
    """5 was my first answer; wilson_ci(0,4).hi = 0.4899, so the floor is 4.

    Caught before it was written by checking the claim, and pinned here so it
    cannot be reintroduced by someone reasoning the same way.
    """
    def m(d):
        d["sample_sizes"]["pii_per_entity_cell"]["smallest_n_where_oracle_can_fire"] = 5
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "smallest n" in r.stdout


def test_kills_pii_positives_that_are_not_per_entity_times_entities(tree):
    """A flat total is exactly what DEV-P0-6 corrected. It must not come back."""
    def m(d):
        d["corpora"]["pii"]["positives"] = 108
        d["corpora"]["pii"]["total"] = 135
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "positives != per_entity" in r.stdout


def test_kills_a_stale_sdk_entity_count(tree):
    """The SDK is read live, so a pinned count that drifts must fail loudly.

    This is the check that would have caught the original defect: a corpus can be
    internally consistent to the last item and still target the wrong entity set.
    """
    def m(d):
        d["corpora"]["pii"]["entity_types_from_sdk"] = 15
        d["sample_sizes"]["pii_per_entity_cell"]["entity_types"] = 15
        d["corpora"]["pii"]["positives"] = 165
        d["corpora"]["pii"]["total"] = 192
        d["sample_sizes"]["pii_per_entity_cell"]["total_positives"] = 165
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "SDK enumerates" in r.stdout


def test_kills_a_mapping_target_the_sdk_does_not_define(tree):
    """CREDIT_CARD is the SOURCE corpus's label, not an SDK entity type.

    Writing the source label as its own target is the most natural way to get this
    table wrong, because 13 of the 15 keys are plausible-looking names that the
    SDK does not use.
    """
    def m(d):
        d["corpora"]["pii"]["source_corpus_audit"]["mapping"]["CREDIT_CARD"] = \
            "CREDIT_CARD"
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "the SDK does not enumerate" in r.stdout


@pytest.mark.parametrize("field,wrong", [
    ("labels_mapping_after_relabelling", 4),   # the value I first wrote
    ("sdk_entity_types_uncovered", 25),        # the other value I first wrote
    ("labels_with_no_sdk_entity_type", 7),
    ("sdk_entity_types_covered", 6),
    ("distinct_positive_labels", 14),
    ("positive_items", 81 + 1),
    ("negative_items", 27 + 1),
    ("reusable_items", 40),
    ("unmappable_items", 41),
])
def test_kills_every_falsified_audit_count(tree, field, wrong):
    """Each count in the audit is recomputed, so each must be individually killable.

    Parametrised rather than written once because the defect this block exists to
    fix was TWO wrong numbers in the same paragraph: checking one of them would
    have left the other exactly as unverified as before.
    """
    def m(d):
        d["corpora"]["pii"]["source_corpus_audit"][field] = wrong
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1, f"{field} = {wrong} was not caught"
    assert f"source_corpus_audit.{field}" in r.stdout


def test_kills_a_mapping_that_does_not_cover_the_corpus_on_disk(tree):
    """A label present on disk but dropped from the table would skew every count.

    Deleting a key makes the audit's own arithmetic self-consistent at a smaller
    label set — the same "deletion is cheaper than falsification" attack the
    precondition pass closed for missing fields, one level down.
    """
    def m(d):
        del d["corpora"]["pii"]["source_corpus_audit"]["mapping"]["JWT_TOKEN"]
        a = d["corpora"]["pii"]["source_corpus_audit"]
        a["distinct_positive_labels"] = 14
        a["labels_with_no_sdk_entity_type"] = 7
        a["unmappable_items"] = 37
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "does not cover the corpus" in r.stdout


def test_kills_reused_plus_authored_not_equal_to_positives(tree):
    """The provenance split must account for every positive item, or items vanish.

    This test was vacuous for one amendment (DEV-SEAL-6). It set `authored_new`,
    which DEV-SEAL-4 had renamed to `positive_items_authored`, so it was adding an
    unread key to the YAML and passing on a failure raised elsewhere in the same
    run. It was written correctly, verified as killing, and then decayed silently
    when the field it named moved.

    `mutate_existing` is the fix for the class rather than for this instance: it
    refuses to set a key that is not already present, so the next rename fails
    loudly here instead of leaving a green test that mutates nothing.
    """
    mutate_existing(tree, "corpora.pii.positive_items_authored", 300)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "reused verbatim + authored != positives" in r.stdout


def test_kills_negatives_that_disagree_with_the_reused_corpus(tree):
    """The negatives are the source corpus MINUS the entity screen; both must add up.

    The assertion this test reads changed shape in DEV-P0-8. It used to be plain
    equality against the 27 negatives on disk, and its failure message said "reused
    verbatim"; the amendment made it `negatives + screened_out == source`, because
    26 of 27 is no longer verbatim reuse. Pinning the old message here would have
    left the test passing only until someone reworded it, so it now asserts on the
    arithmetic the check actually performs.
    """
    mutate_existing(tree, "corpora.pii.negatives", 40)
    mutate_existing(tree, "corpora.pii.total", 381)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "does not\nequal" in r.stdout or "does not equal" in r.stdout.replace(
        "\n", " "), f"the identity did not fire:\n{r.stdout}"
    assert "negatives in the source corpus" in r.stdout.replace("\n", " ")


def test_kills_an_entity_screen_exclusion_count_that_absorbs_a_changed_negative(tree):
    """The tighter half of the same identity, and the reason it is an identity.

    `negatives + screened_out == 27` can be satisfied by moving BOTH terms, which
    is exactly how a shrinking corpus could be made to look accounted-for. The
    exclusion count is pre-registered precisely so it cannot absorb the change:
    the screen is re-run against the corpus on disk, so claiming 2 exclusions when
    the screen finds 1 must fail even though the arithmetic balances.
    """
    mutate_existing(tree, "corpora.pii.negatives", 25)
    mutate_existing(tree, "corpora.pii.total", 366)
    mutate_existing(tree, "corpora.pii.entity_screen_exclusions.pii_negatives", 2)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "entity_screen_exclusions.pii_negatives" in r.stdout.replace("\n", " ")


def test_deleting_the_source_corpus_audit_is_not_a_way_to_skip_its_checks(tree):
    """Every assertion in check_pii_source_audit reads this block, so rc must be 2.

    The same class as DEV-SEAL-2's finding: deleting a field deletes its check,
    and that is the cheaper attack unless the field is a declared precondition.
    """
    def m(d):
        del d["corpora"]["pii"]["source_corpus_audit"]
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 2, f"expected rc=2 (unusable input), got {r.returncode}"
    assert "source_corpus_audit" in r.stderr
    assert "Traceback" not in r.stderr, "a missing field must not be a crash"


# ---- mutations on the families ----------------------------------------------

def test_kills_confirmatory_family_grown_without_realpha(tree):
    """Adding a 9th confirmatory hypothesis changes alpha for the other eight.

    Uses a REAL case id (F5-7b, otherwise unfamilied) rather than a made-up one,
    so the kill must come from the family-size/alpha mismatch and cannot be
    satisfied by the cheaper "not a case" check.
    """
    def m(d):
        d["families"]["confirmatory"]["members"].append("F5-7b")
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "9 members but alpha was divided by 8" in r.stdout
    assert "alpha_per_hypothesis is not" in r.stdout


def test_kills_a_case_in_two_families(tree):
    """Two decision rules for one hypothesis means the convenient one is available."""
    def m(d):
        d["families"]["exploratory_detection"]["members"].append("F4-1")
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "two families" in r.stdout


def test_kills_a_nonexistent_case_in_a_family(tree):
    def m(d):
        d["families"]["exploratory_latency"]["members"].append("F6-99")
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "not a case" in r.stdout


def test_kills_a_sized_case_with_no_declared_family(tree):
    """This is the mutation that found a real gap: F2-2/F2-4/F2-5 were sized but
    belonged to no family, so their decision rule was undeclared."""
    def m(d):
        d["families"]["single_counterexample"]["members"] = ["F2-1", "F2-3"]
        del d["families"]["exploratory_determinism"]
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "in no declared family" in r.stdout


# ---- mutations on the scope statements --------------------------------------

def test_kills_scope_count_disagreeing_with_the_triage(tree):
    def m(d):
        for s in d["out_of_scope"]:
            if s["id"] == "class_X_claims":
                s["statement"] = "2 claims are excluded, each with a reason."
    mutate(tree, m)
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "class_X_claims" in r.stdout


# ---- the oracle registry ----------------------------------------------------

def test_oracle_edit_is_reported_before_sealing_and_fatal_after(tree):
    """An edited falsifying condition is the highest-value tampering there is.

    Before sealing it is a NOTE (editing an oracle pre-data is legitimate);
    once sealed it must be fatal. Both halves are asserted, because a gate that
    only warned would let a post-hoc oracle rewrite through.
    """
    rules = tree / "claims" / "triage_rules.py"
    src = rules.read_text(encoding="utf-8")
    marker = "FALSE if >=1 flip"
    assert marker in src, "F2-1's oracle no longer contains the mutated substring"
    rules.write_text(src.replace(marker, "FALSE if >=99 flips", 1), encoding="utf-8")

    r = run_verifier(tree)
    assert r.returncode == 0, "pre-sealing, an oracle edit should NOTE, not fail"
    assert "ORACLE REGISTRY CHANGED" in r.stdout

    seal = subprocess.run([sys.executable, str(tree / "verify_prereg.py"), "--seal"],
                          capture_output=True, text=True, cwd=str(tree))
    assert seal.returncode == 0, f"sealing failed:\n{seal.stdout}\n{seal.stderr}"

    r2 = run_verifier(tree)
    assert r2.returncode == 1, "post-sealing, an oracle edit must be fatal"
    assert "ORACLE REGISTRY CHANGED" in r2.stdout


# ---- sealing behaviour ------------------------------------------------------

def test_seal_then_verify_is_green_and_hash_matches(tree):
    seal = subprocess.run([sys.executable, str(tree / "verify_prereg.py"), "--seal"],
                          capture_output=True, text=True, cwd=str(tree))
    assert seal.returncode == 0
    assert "SEALED  sha256 =" in seal.stdout
    stamp = tree / "PREREGISTRATION.sha256"
    assert stamp.exists()
    r = run_verifier(tree)
    assert r.returncode == 0
    assert "SEALED, hash matches" in r.stdout


def test_resealing_is_refused(tree):
    args = [sys.executable, str(tree / "verify_prereg.py"), "--seal"]
    assert subprocess.run(args, capture_output=True, text=True,
                          cwd=str(tree)).returncode == 0
    again = subprocess.run(args, capture_output=True, text=True, cwd=str(tree))
    assert again.returncode == 1
    assert "may not be re-sealed" in again.stderr


def test_editing_a_sealed_prereg_is_detected(tree):
    subprocess.run([sys.executable, str(tree / "verify_prereg.py"), "--seal"],
                   capture_output=True, text=True, cwd=str(tree))
    mutate(tree, lambda d: d.update({"_tampered": True}))
    r = run_verifier(tree)
    assert r.returncode == 1
    assert "modified since sealing" in r.stdout


def test_sealing_sets_status_to_sealed(tree):
    subprocess.run([sys.executable, str(tree / "verify_prereg.py"), "--seal"],
                   capture_output=True, text=True, cwd=str(tree))
    doc = yaml.safe_load((tree / "PREREGISTRATION.yaml").read_text(encoding="utf-8"))
    assert doc["meta"]["status"] == "SEALED"


# ---- unusable-input handling -----------------------------------------------

def test_missing_prereg_exits_2_not_0(tree):
    (tree / "PREREGISTRATION.yaml").unlink()
    r = run_verifier(tree)
    assert r.returncode == 2, "a missing pre-registration must not read as verified"


def test_empty_prereg_exits_2(tree):
    (tree / "PREREGISTRATION.yaml").write_text("", encoding="utf-8")
    r = run_verifier(tree)
    assert r.returncode == 2


def test_prereg_without_derived_section_exits_2(tree):
    (tree / "PREREGISTRATION.yaml").write_text("meta: {version: 1}\n", encoding="utf-8")
    r = run_verifier(tree)
    assert r.returncode == 2
    assert "verification of nothing" in r.stderr


# ---- the analysis-time gate ------------------------------------------------

def test_analysis_gate_rejects_an_undeclared_case(tree, tmp_path):
    results = tmp_path / "results.json"
    results.write_text('{"cases": [{"case_id": "F99-1", "n": 300}]}', encoding="utf-8")
    r = subprocess.run([sys.executable, str(tree / "verify_prereg.py"),
                        "--check-analysis", str(results)],
                       capture_output=True, text=True, cwd=str(tree))
    assert r.returncode == 1
    assert "not a case" in r.stdout


def test_analysis_gate_rejects_underpowered_n(tree, tmp_path):
    results = tmp_path / "results.json"
    results.write_text('{"cases": [{"case_id": "F2-1", "n": 50}]}', encoding="utf-8")
    r = subprocess.run([sys.executable, str(tree / "verify_prereg.py"),
                        "--check-analysis", str(results)],
                       capture_output=True, text=True, cwd=str(tree))
    assert r.returncode == 1
    assert "below the pre-registered" in r.stdout


def test_analysis_gate_rejects_a_pvalue_on_a_descriptive_case(tree, tmp_path):
    """A C/O case has no p-value. One appearing means an undeclared test ran."""
    results = tmp_path / "results.json"
    results.write_text('{"cases": [{"case_id": "F1-3", "n": 2, "p_value": 0.01}]}',
                       encoding="utf-8")
    r = subprocess.run([sys.executable, str(tree / "verify_prereg.py"),
                        "--check-analysis", str(results)],
                       capture_output=True, text=True, cwd=str(tree))
    assert r.returncode == 1
    assert "descriptive" in r.stdout


def test_analysis_gate_rejects_an_empty_results_file(tree, tmp_path):
    """Per feedback_zero_file_scan_is_error: reading nothing must not pass."""
    results = tmp_path / "results.json"
    results.write_text('{"cases": []}', encoding="utf-8")
    r = subprocess.run([sys.executable, str(tree / "verify_prereg.py"),
                        "--check-analysis", str(results)],
                       capture_output=True, text=True, cwd=str(tree))
    assert r.returncode == 1
    assert "zero cases" in r.stdout


def test_analysis_gate_accepts_a_declared_case_at_full_n(tree, tmp_path):
    """The gate must also be able to say yes, or it is not a gate."""
    results = tmp_path / "results.json"
    results.write_text('{"cases": [{"case_id": "F2-1", "n": 300}]}', encoding="utf-8")
    r = subprocess.run([sys.executable, str(tree / "verify_prereg.py"),
                        "--check-analysis", str(results)],
                       capture_output=True, text=True, cwd=str(tree))
    assert r.returncode == 0


# ---- the verifier's own floor ----------------------------------------------

def test_verifier_refuses_to_report_success_on_too_few_assertions(tree):
    """The MIN_FILES/MIN_ROWS discipline, applied to the verifier itself.

    This test caught a real weakness in the mechanism it tests (DEV-SEAL-6). Its
    first version removed three check calls and asserted rc=2 against a global
    floor of 60. It passed while the verifier ran ~120 assertions and started
    FAILING at 189 — because removing three checks left 84, still above 60. The
    test was right and the floor was wrong: **a floor set below the current total
    loosens every time the verifier gets stronger**, and a single grand total
    cannot detect one missing check at any threshold.

    So the verifier now holds a per-check floor table, and this test removes the
    same three checks from it.
    """
    src = (tree / "verify_prereg.py").read_text(encoding="utf-8")
    assert "if total < 60:" in src, "the global floor has been removed"
    assert "starved" in src, "the per-check floor table has been removed"
    patched = src
    for name in ("derived", "sample_sizes", "families"):
        before = patched
        patched = re.sub(rf'^\s*\("{name}", lambda: check_{name}\(.*?\n',
                         "", patched, count=1, flags=re.M)
        assert patched != before, f"could not remove the {name} check from CHECKS"
    (tree / "verify_prereg.py").write_text(patched, encoding="utf-8")
    r = run_verifier(tree)
    assert r.returncode == 2
    assert "does not match REQUIRED_CHECKS" in r.stderr, (
        f"three checks were deleted and the verifier did not name their absence:"
        f"\n{r.stdout}\n{r.stderr}")
    for name in ("derived", "families", "sample_sizes"):
        assert name in r.stderr


def test_a_check_that_stops_asserting_is_rc2_not_a_pass(tree):
    """The defect the global floor could not catch: ONE check silently gutted.

    Removing a single check leaves the total far above any floor, so before the
    per-check table this was indistinguishable from a pass. Gutting the smallest
    check (mutation_arms, floor 3) is the strongest form of the test: if even the
    cheapest check is individually load-bearing, the mechanism works for all of
    them.
    """
    src = (tree / "verify_prereg.py").read_text(encoding="utf-8")
    patched = src.replace("    arms = pr[\"validity_checks\"]"
                          "[\"mutation_arms_are_mandatory\"][\"applies_to\"]",
                          "    arms = []", 1)
    assert patched != src, "could not neutralise check_mutation_arms"
    (tree / "verify_prereg.py").write_text(patched, encoding="utf-8")
    r = run_verifier(tree)
    assert r.returncode == 2, (
        f"a check that asserted nothing reported rc={r.returncode}; the per-check "
        f"floor is not load-bearing")
    assert "mutation_arms ran 0 assertion(s)" in r.stderr


def test_control_arm_the_unpatched_verifier_clears_every_per_check_floor(tree):
    """Mutation control for the two tests above.

    Without this, both could pass because the verifier ALWAYS exits 2 — e.g. if a
    floor had been set above what a check can produce. The control arm at the top
    of this file checks rc=0 overall; this one names the specific mechanism.
    """
    r = run_verifier(tree)
    assert r.returncode == 0, f"unpatched tree does not pass:\n{r.stdout}"
    assert "ran" not in r.stderr, f"a floor fired on the unmutated tree: {r.stderr}"
