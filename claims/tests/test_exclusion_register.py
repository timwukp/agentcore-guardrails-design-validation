"""The exclusion register's self-checks must be able to fail.

03_exclusion_register.py promises to exit non-zero rather than emit a register it
cannot stand behind. That promise is worth nothing unless each check actually
fires on the defect it names — a `check()` that returned `[]` unconditionally
would produce the same green run (per feedback_vacuous_test_check).

The control arm matters as much as the mutations: a check that fired on
everything would "catch" all four mutations and also condemn the real triage.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "03_exclusion_register.py"


def _load():
    spec = importlib.util.spec_from_file_location("reg", SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


reg = _load()


@pytest.fixture(scope="module")
def clean():
    rows = reg.load()
    assert rows, "triage.csv is empty — every assertion below would be vacuous"
    return rows


def first_x(rows: list[dict]) -> dict:
    return next(r for r in rows if r["cls"] == "X")


def test_control_arm_no_check_fires_on_the_real_triage(clean):
    """If this fails, the mutation tests below prove nothing."""
    problems = reg.check(copy.deepcopy(clean))
    assert problems == [], f"checks fire on unmutated input: {problems[:3]}"


def test_x_row_without_a_reason_is_caught(clean):
    rows = copy.deepcopy(clean)
    first_x(rows)["exclusion_reason"] = ""
    assert any("no exclusion reason" in p for p in reg.check(rows))


def test_x_row_without_a_remedy_is_caught(clean):
    """'Hard to test' is not an exclusion — it is a shrug.

    A reason with no remedy leaves a reviewer unable to distinguish a structural
    impossibility from a scoping choice, which is the whole distinction the
    register exists to make.
    """
    rows = copy.deepcopy(clean)
    first_x(rows)["exclusion_reason"] = "Hard to test, skipping."
    assert any("Remedy" in p for p in reg.check(rows))


def test_reason_citing_a_nonexistent_case_is_caught(clean):
    """The check that earned its keep on the first run.

    It caught a reason citing F5-3c — an arm the plan explicitly DECLINED — as
    though it were a proxy that runs. A register naming a nonexistent proxy
    offers false comfort, which is worse than admitting the gap.
    """
    rows = copy.deepcopy(clean)
    r = first_x(rows)
    r["exclusion_reason"] += " See F9-99 for the proxy."
    assert any("F9-99" in p for p in reg.check(rows))


def test_class_outside_the_seven_is_caught(clean):
    rows = copy.deepcopy(clean)
    rows[0]["cls"] = "Z"
    assert any("outside E/S/C/O/D/N/X" in p for p in reg.check(rows))


# ---- the CASES / DECLINED_ARMS distinction ------------------------------------

def test_declined_arm_is_nameable_but_not_credited_as_a_proxy():
    """The load-bearing distinction: naming without crediting.

    A declined arm may appear in prose so a limit is identifiable, but it must
    never be rendered under "nearest proxy run". If DECLINED_ARMS entries leaked
    into CASES, the register would credit an experiment that does not exist.
    """
    import triage_rules as R
    assert R.DECLINED_ARMS, "no declined arms declared"
    for arm in R.DECLINED_ARMS:
        assert arm not in R.CASES, (
            f"{arm} is in both CASES and DECLINED_ARMS — the register would print "
            f"it as a proxy that runs")

    reason = "Same structural limit as F5-3c; F5-4b is the nearest proxy."
    assert reg.proxies(reason) == ["F5-4b"]
    assert reg.declined(reason) == ["F5-3c"]


def test_declined_arms_state_why_they_are_declined():
    import triage_rules as R
    for arm, why in R.DECLINED_ARMS.items():
        assert len(why) >= 120, f"{arm}: justification too thin to audit"


# ---- anchor formatting -------------------------------------------------------

@pytest.mark.parametrize("anchor,expected", [
    ("s4", "§4"),
    ("s4-5-2", "§4.5.2"),
    ("s10", "§10"),
    ("appC", "Appendix C"),
    ("agentcore-policy-metrics", "`agentcore-policy-metrics`"),
])
def test_fmt_anchor(anchor, expected):
    """'§s4-5-2' is not a section number a reader can look up."""
    assert reg.fmt_anchor(anchor) == expected


# ---- arithmetic must reconcile ----------------------------------------------

def test_class_counts_reconcile_to_the_row_count(clean):
    """A register whose parts do not sum to its whole is not evidence.

    Per feedback_label_must_match_computation: a breakdown must reconcile to its
    parent, or a reader cannot tell which number is wrong.
    """
    counts = {}
    for r in clean:
        counts[r["cls"]] = counts.get(r["cls"], 0) + 1
    tested = sum(counts.get(c, 0) for c in reg.TESTED)
    untested = sum(counts.get(c, 0) for c in reg.UNTESTED)
    assert tested + untested == len(clean)


def test_every_untested_row_has_a_reason(clean):
    """D and N rows are not gaps, but they are not silent either."""
    missing = [r["claim_id"] for r in clean
               if r["cls"] in reg.UNTESTED and not r["exclusion_reason"].strip()]
    assert missing == [], f"{len(missing)} untested claim(s) carry no reason: {missing[:5]}"


def test_every_tested_row_names_at_least_one_case(clean):
    naked = [r["claim_id"] for r in clean
             if r["cls"] in reg.TESTED and not r["cases"].split()]
    assert naked == [], f"{len(naked)} tested claim(s) cite no case: {naked[:5]}"


def test_register_on_disk_is_current(clean):
    """--check equivalent: a stale register is a wrong register."""
    out = reg.OUT
    assert out.exists(), f"{out.name} has not been generated"
    assert out.read_text(encoding="utf-8") == reg.render(clean), (
        f"{out.name} is stale — re-run 03_exclusion_register.py")


def test_register_carries_no_account_identifiers():
    """Redaction gate at the source, per feedback_redact_cloud_metadata.

    The register is generated into a report destined for external distribution.
    A 12-digit account ID in generated prose is the same leak as one typed by
    hand, and it is easier to catch here than in a pre-push scan.
    """
    import re
    text = reg.OUT.read_text(encoding="utf-8")
    hits = re.findall(r"\b\d{12}\b", text)
    assert hits == [], f"account-shaped identifiers in the register: {set(hits)}"
    assert "arn:aws:" not in text, "ARN in the register"
