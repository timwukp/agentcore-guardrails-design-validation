"""The reference-title matcher must discriminate in BOTH directions.

02_check_references.py reported 24/24 pass. That number is worthless unless the
matcher can also say NO — a `tokens()` that returned a constant would produce the
same 24/24. These are the negative cases (per feedback_vacuous_test_check).

The positives are the four references that the FIRST draft of the matcher flagged
as broken. They were correct all along; the matcher lacked stemming and discarded
the parentheticals that carried the identifying words. Pinning them here stops
that regression from returning as a fake document defect.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "02_check_references.py"


def _load():
    spec = importlib.util.spec_from_file_location("refchk", SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # @dataclass/annotations need this first
    spec.loader.exec_module(mod)
    return mod


refchk = _load()


def matches(row_title: str, page_title: str) -> bool:
    return bool(refchk.tokens(row_title) & refchk.tokens(page_title))


# The four that a naive matcher rejects. Each needs either stemming
# (policy/policies, test/testing) or the parenthetical kept.
SHOULD_MATCH = [
    ("Guardrails in AgentCore Policy",
     "Guardrails in policies - Amazon Bedrock AgentCore"),
    ("Getting Started with Gateway Guardrails",
     "Getting started with guardrails in the AgentCore CLI - Amazon Bedrock AgentCore"),
    ("Testing Policies (LOG_ONLY workflow)",
     "Test a policy in LOG_ONLY mode - Amazon Bedrock AgentCore"),
    ("AgentCore Memory Best Practices (Memory security; not guardrails-specific)",
     "Best practices - Amazon Bedrock AgentCore"),
    ("Policy Conditions (when guardrails)",
     "Policy conditions - Amazon Bedrock AgentCore"),
    ("Understanding Cedar Policies",
     "Understanding Cedar policies - Amazon Bedrock AgentCore"),
]

# Pages that are genuinely the wrong page. If any of these matched, a real
# mis-citation in the document would sail through as "verified".
SHOULD_NOT_MATCH = [
    ("AgentCore Gateway Metrics", "Amazon S3 pricing - AWS"),
    ("Guardrails Supported Languages", "Page Not Found - AWS Documentation"),
    ("Guardrails Tiers", "Understanding Cedar policies - Amazon Bedrock AgentCore"),
    ("ApplyGuardrail API", "AgentCore Optimization - Amazon Bedrock AgentCore"),
    ("Guardrails Input Tagging", "AgentCore Evaluations - Amazon Bedrock AgentCore"),
    # The killer case: boilerplate alone must not constitute a match, or every
    # AWS doc page would match every row.
    ("AgentCore Policy Metrics", "Amazon Bedrock AgentCore Developer Guide - AWS"),
]


@pytest.mark.parametrize("row,page", SHOULD_MATCH)
def test_correct_reference_is_accepted(row, page):
    assert matches(row, page), (
        f"{row!r} should match {page!r} — this reference is correct in the "
        f"document and the matcher is what is wrong")


@pytest.mark.parametrize("row,page", SHOULD_NOT_MATCH)
def test_wrong_page_is_rejected(row, page):
    assert not matches(row, page), (
        f"{row!r} must NOT match {page!r} — if it does, the 24/24 pass is "
        f"vacuous and a real mis-citation would go unreported")


def test_boilerplate_alone_is_not_a_match():
    """Every AWS page title ends in '- Amazon Bedrock AgentCore'."""
    assert refchk.tokens("Amazon Bedrock AgentCore Developer Guide - AWS") == set()


def test_stemming_unifies_inflections():
    assert refchk._stem("policies") == refchk._stem("policy")
    assert refchk._stem("testing") == refchk._stem("test")
    assert refchk._stem("guardrails") == refchk._stem("guardrail")
    # ...and does not over-merge
    assert refchk._stem("metrics") != refchk._stem("mode")


def test_parse_row_keeps_the_parenthetical():
    title, url = refchk.parse_row(
        "Policy Conditions (when guardrails) || <https://docs.aws.amazon.com/x.html>")
    assert "guardrails" in title
    assert url == "https://docs.aws.amazon.com/x.html"


def test_parse_row_strips_markdown_and_angle_brackets():
    title, url = refchk.parse_row("**Bold Title** || <https://example.com/a.html>")
    assert title == "Bold Title"
    assert url == "https://example.com/a.html"


def test_parse_row_rejects_a_row_with_no_url():
    assert refchk.parse_row("Some Title || no link here") is None


def test_all_stopword_title_is_reported_unverifiable_not_passed():
    """'How Bedrock Guardrails Works' must not silently score a content match.

    If stopword removal empties a row title, the honest answer is 'unverifiable',
    which is what the script records — never 'yes'.
    """
    toks = refchk.tokens("How Bedrock Guardrails Works")
    # 'guardrail' survives as the one content word, so this row IS checkable.
    # The guard matters for any future row that reduces to nothing.
    assert refchk.tokens("How to Use the Guide") == set()
    assert toks  # documents current behaviour for this specific title
