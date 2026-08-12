#!/usr/bin/env python3
"""The account ID is resolved in exactly one place, and that place registers it for masking.

Why this file exists
--------------------
Measured 2026-08-12: the redaction gate reported the live account ID in
`results/phase1/F7-1.json` and `F7-2.json`. It was not in an ARN — it was inside a CloudWatch
dimension value, `ProviderName` on `ResourceAccessTokenFetchSuccess`, which names another
team's OAuth2 credential provider in the same account and whose name embeds the account ID.
`lib/redact.py` masked ARN account fields only, so nothing on the write path could see it.

The fix is `redact.register_account_id`, and the failure mode of that fix is obvious: a mask
that has to be told the value is a mask that can be forgotten. So registration was made a side
effect of `awsclients.account_id()` and every inline `get_caller_identity()["Account"]` was
routed through it. This file is what stops the eighteenth call site from coming back — a
`sts().get_caller_identity()["Account"]` written by hand next month passes every other test in
the suite and silently loses the mask, and the only symptom would be another account ID in
`results/`, found by the gate after the fact if at all.

Per feedback_no_deploy_path_no_component: a masking rule with no path that reaches it is not a
masking rule. These tests ARE that path's proof.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import redact  # noqa: E402

# The one file allowed to make the call: the choke point itself. Its docstring also quotes the
# forbidden expression, which is why the scan cannot simply grep for the text.
CHOKE_POINT = "lib/awsclients.py"

SKIP_DIRS = {".git", ".venv", ".venv-oracle", ".venv-baseline", "__pycache__",
             ".pytest_cache", "evidence", "node_modules"}


def _py_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        out.append(p)
    assert len(out) > 50, f"the scan found only {len(out)} python files — it is not scanning"
    return sorted(out)


def _account_index_calls(tree: ast.AST) -> list[int]:
    """Line numbers of every `<expr>.get_caller_identity()[...]` subscript in the tree.

    Read from the AST rather than by regex, so the choke point's own docstring — which quotes
    the expression verbatim to explain the rule — is not a finding in the file that defines it.
    A comment or string cannot be a Call node.
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        val = node.value
        if (isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute)
                and val.func.attr == "get_caller_identity"):
            hits.append(node.lineno)
    return hits


def test_only_the_choke_point_resolves_the_account_id():
    offenders: dict[str, list[int]] = {}
    scanned = 0
    for p in _py_files():
        rel = str(p.relative_to(ROOT))
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        scanned += 1
        if rel == CHOKE_POINT:
            continue
        lines = _account_index_calls(tree)
        if lines:
            offenders[rel] = lines
    assert scanned > 50, f"only {scanned} files parsed — a zero-file scan must not pass"
    assert not offenders, (
        f"{sum(len(v) for v in offenders.values())} inline account-ID resolution(s) outside "
        f"{CHOKE_POINT}: {offenders}. Use `A.account_id(factory)`, which registers the value "
        f"with redact.register_account_id — see that function for the leak this prevents.")


def test_the_choke_point_registers_what_it_resolves():
    """`account_id()` must call `register_account_id` — checked in the AST, not the docstring.

    A choke point that resolves the value and forgets to register it is worse than eighteen
    inline call sites, because the test above would then certify a mask that never runs.
    """
    tree = ast.parse((ROOT / CHOKE_POINT).read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "account_id"), None)
    assert fn is not None, f"{CHOKE_POINT} has no `account_id` function"
    resolves = _account_index_calls(fn)
    assert resolves, "`account_id()` does not resolve the account ID"
    registers = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "register_account_id"]
    assert registers, ("`account_id()` resolves the account ID without registering it for "
                       "masking — the mask would be silently absent for every run")
    returned = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert returned, "`account_id()` returns nothing"


# Every account-shaped value in this file is BUILT, never spelled. A 12-digit literal here
# would be a finding in the gate's own test suite — the mistake `redact.py`'s docstring records
# making twice already — and one of the values needed is the live account ID, which must not
# appear in a distributed file at all. `_ACCT` is synthetic and `_OTHER` is a different
# synthetic value; neither can collide with a real account read from `evidence/`, because
# `test_the_sealed_corpora_contain_no_registered_account_id` would then fail loudly.
_ACCT = "1" * 12
_OTHER = "2" * 12


def test_a_registered_id_is_masked_outside_arn_position():
    """The property the leak needed: an account ID inside a free-text resource NAME."""
    before = redact.known_account_ids()
    redact.register_account_id(_ACCT)
    try:
        # The exact shape that leaked: another team's credential-provider name, whose only
        # structure around the ID is hyphens.
        name = f"ESDMCP-OAuth2-Provider-us-east-1-{_ACCT}-prod"
        masked = redact.mask_text(name)
        assert _ACCT not in masked, f"the registered account ID survived masking: {masked}"
        assert masked == f"ESDMCP-OAuth2-Provider-us-east-1-{redact.ACCOUNT_PLACEHOLDER}-prod"
        # Idempotent, and reached through the recursive walk the writers actually use — keys
        # included, which is where `phase1.emit` puts dimension names.
        assert redact.mask(masked) == masked
        assert _ACCT not in str(redact.mask({"ProviderName": [name], name: name}))
    finally:
        if _ACCT not in before:
            redact._KNOWN.discard(_ACCT)


def test_an_unregistered_twelve_digit_token_is_left_alone():
    """The narrowness that lets this rule exist at all.

    A PII corpus fixture whose entity type IS a 12-digit number comes back on checkpoint rows.
    Masking every `\\b\\d{12}\\b` would erase the record of which fixture was sent, which is why
    `redact.py`'s docstring refused that widening. The registry keeps the refusal true.
    """
    assert _OTHER not in redact.known_account_ids(), (
        "this test's fixture collides with a registered account ID; pick another")
    assert redact.mask_text(f"slot={_OTHER}") == f"slot={_OTHER}"
    # And a registered ID embedded in a LONGER digit run is not an account reference either.
    before = redact.known_account_ids()
    redact.register_account_id(_ACCT)
    try:
        assert redact.mask_text(f"x{_ACCT}9") == f"x{_ACCT}9"
        assert redact.mask_text(f"slot={_OTHER}") == f"slot={_OTHER}"
    finally:
        if _ACCT not in before:
            redact._KNOWN.discard(_ACCT)


def test_register_rejects_anything_that_is_not_a_twelve_digit_account():
    """A loose registry is a substitution rule aimed at arbitrary text."""
    for bad in ("", "1" * 11, "1" * 13, "1" * 11 + "a", f"  {_ACCT}  ", _ACCT + "\n"):
        with pytest.raises(ValueError):
            redact.register_account_id(bad)


def _live_account_ids() -> set[str]:
    """Account IDs this machine can actually see, from the UNMASKED local evidence tree.

    A test process registers nothing — it makes no AWS call — so checking the corpora against
    `known_account_ids()` alone would skip on every run and certify nothing
    (feedback_vacuous_test_check). `evidence/` is the one tree deliberately left unmasked
    (`redact.py`'s docstring: a claim has to be quotable to AWS Support with real ARNs), so the
    account under test is readable there and nowhere else offline. It is local-only and never
    distributed, so this reads a value it must not print — hence the assertion messages below
    quote the corpus path, never the ID.

    A fresh clone has no `evidence/` and legitimately has no account to check against; that
    case skips, which is the honest answer rather than a pass.
    """
    out: set[str] = set(redact.known_account_ids())
    pat = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:(\d{12}):")
    ev = ROOT / "evidence"
    if ev.is_dir():
        for p in sorted(ev.rglob("*.json"))[:400]:
            try:
                m = pat.search(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if m:
                out.add(m.group(1))
                break
    return out


def test_the_sealed_corpora_contain_no_registered_account_id():
    """The one way the narrow rule could still corrupt data.

    If a sealed corpus fixture were byte-equal to the account ID, masking it would rewrite
    corpus content on its way into a checkpoint. Checked against the corpora as they are rather
    than asserted in a comment: at the time of writing the live account ID appears in no
    corpus file, and this fails if a future corpus adds it.
    """
    ids = _live_account_ids()
    if not ids:
        pytest.skip("no account ID is visible offline (no evidence/ tree); nothing to check")
    hits = []
    for d in ("corpora", "corpora_deviation"):
        for p in (ROOT / d).rglob("*.jsonl"):
            text = p.read_text(encoding="utf-8")
            for aid in ids:
                if re.search(rf"\b{aid}\b", text):
                    hits.append(f"{p.relative_to(ROOT)}:{aid}")
    assert not hits, f"a sealed corpus contains a registered account ID: {hits}"
