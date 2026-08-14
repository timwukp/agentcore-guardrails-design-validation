"""Nobody sends `definition={"cedar": ...}` by accident.

WHAT THIS PREVENTS, stated as the failure and not as the rule
-------------------------------------------------------------
`CreatePolicy`'s `definition` is a union. The extended guardrails grammar exists ONLY under
`definition.policy`; under `definition.cedar` the body is parsed as base Cedar and every
guardrails construct comes back as

    "When parsing the policy statement, the following errors occurred:
     * unexpected token `guardrails`"

On 2026-08-14 that message was the reported cause of eight failed arms across F1-19, F1-24 and
F1-25 — a second wasted live round after the resource-clause repair — and read on its own it says
"guardrails-in-policy is not a supported construct", which is a spectacular false finding against
a document whose §3.1, §4.1 and §4.2 are built on that construct. The message was never
misleading. It was answering a request nobody meant to send.

Three properties of that failure are why this is a scan and not a comment:

1. **The defect was a two-character difference inside a dict literal.** `{"cedar": {...}}` vs
   `{"policy": {...}}` in a keyword argument, in a module that otherwise did everything right.
   No test that enumerates operation names, and no reviewer reading for logic, sees it.

2. **Every other module was already correct**, which is exactly why it stayed invisible: F5-4a,
   F5-4b, F6, F2 and F4 all send `policy`. A defect present in one call site out of six is not
   discoverable by comparing outcomes within a case — it took a factorial probe across BOTH the
   member and the resource form (`f1_config/diag_resource_form.py`) to attribute it, because the
   two variables covaried perfectly across the modules that differed.

3. **The knowledge already existed in-repo and was not consulted.** F4-0's calibration matrix
   recorded `cedar.doc_syntax -> unexpected token guardrails` on 2026-08-11, three days before
   the round that rediscovered it at the cost of a live round. A fact recorded in an evidence
   JSON that no test reads is a fact the next author will pay for again. This file is the reading.

WHAT THE SCAN CANNOT SEE, said plainly
--------------------------------------
It finds dict LITERALS with a constant `"cedar"` key. It cannot see a computed member —
`definition={member: {"statement": s}}` — which is what the three deliberate member-varying
probes write (`f4_modes/00_syntax_probe.py`, `f4_modes/01_truth_table.py`,
`f1_config/diag_resource_form.py`). That gap is tolerable for a specific reason and not merely
admitted: a module that puts the member in a VARIABLE has necessarily thought about which member
it is sending, and the defect this file exists to prevent is the opposite — a member inherited
without thought from a literal somebody copied. A scan that also flagged computed members would
fire on exactly the three modules that got this right, which is how a guard earns the reputation
that gets it deleted.

WHAT IS NOT ASSERTED
--------------------
That every `policy`-member body is ACCEPTED. It is not: the member is necessary and nowhere near
sufficient. A `policy`-member statement is still refused for an output data path under an
authorization effect, for a type-form resource without ManageAdminPolicy, for a constrained
action with an unconstrained resource, and for a context attribute absent from a reached action's
schema. Those are service constraints, none is decidable from a request dict, and asserting any
of them here would be a green test beside a failing policy.
"""

from __future__ import annotations

import ast
from pathlib import Path

import cedar as C

ROOT = Path(__file__).resolve().parents[2]

SKIP_PARTS = ("/tests/", "/.venv", "/.staging", "/__pycache__", "/.wheel_cache")

# Production sites allowed to send the `cedar` member, each with the reason it is CORRECT there.
# A new site not on this list fails the scan below, which is the point: the member becomes a
# decision somebody has to write down rather than a default somebody inherits.
CEDAR_MEMBER_ALLOWLIST = {
    "infra/03_policy_engine.py": (
        "the baseline permit, which carries no guardrails construct at all — base Cedar is what "
        "`cedar` means, and this is the one body for which it is the honest member"),
    "f1_config/03_permit_trap.py": (
        "F1-3's subject is the validation-finding gate on the baseline permit statement; the "
        "body is base Cedar and the member is part of the request shape under test"),
    "lib/f1_surface.py": (
        "F1's union-arm probe deliberately sends cedar-only, policy-only and both-arms "
        "definitions to establish what the union itself accepts; the member IS the variable, and "
        "this module is where that variable is supposed to live"),
}


def _production_py_files() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        rel = "/" + p.relative_to(ROOT).as_posix()
        if any(s in rel for s in SKIP_PARTS):
            continue
        out.append(p)
    return out


def _definition_sends() -> list[tuple[str, int, tuple[str, ...]]]:
    """Every dict LITERAL in production code whose constant keys name a definition member.

    Reads the AST rather than grepping for `"cedar"` because that string appears all over this
    repo in READER code — `(definition or {}).get("cedar")` — which is not a send and must not be
    flagged. A dict literal keyed by a member name is a send, wherever it sits: passed as
    `definition=`, nested under a `"definition":` key in a request dict, or returned from a
    helper. All three shapes exist here, which is why the scan keys on the literal and not on the
    call.
    """
    members = {"cedar", "policy"}
    found: list[tuple[str, int, tuple[str, ...]]] = []
    for p in _production_py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = tuple(k.value for k in node.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str))
            if not (set(keys) & members):
                continue
            # a member-keyed dict is a definition only if its VALUE carries a statement; this
            # excludes lookup tables that happen to be keyed by member name (abbreviations,
            # display labels) from being read as requests
            if not any(isinstance(v, ast.Dict)
                       and any(isinstance(k, ast.Constant) and k.value == "statement"
                               for k in v.keys)
                       for v in node.values):
                continue
            found.append((rel, node.lineno, keys))
    return found


def test_the_helpers_name_the_members_they_claim_to():
    assert C.policy_definition("s") == {"policy": {"statement": "s"}}
    assert C.base_definition("s") == {"cedar": {"statement": "s"}}
    assert C.GUARDRAILS_DEFINITION_MEMBER == "policy"


def test_the_definition_scan_finds_a_non_trivial_number_of_sites():
    """A scan matching nothing makes the arm below vacuously green — the same floor the
    resource-clause scan carries, and for the same reason."""
    sends = _definition_sends()
    assert len(sends) >= 3, (
        f"only {len(sends)} literal `definition=` sends found; the scan is probably broken "
        f"rather than the repo having shrunk")


def test_every_cedar_member_send_site_is_allowlisted_with_a_reason():
    """The class fix. A module that sends the `cedar` member without appearing above fails here,
    at desk, instead of returning `unexpected token guardrails` for every arm after a live
    round — and the failure asks its author the one question that matters: does this body use
    the extended grammar?"""
    unlisted = sorted({rel for rel, _, keys in _definition_sends()
                       if "cedar" in keys and rel not in CEDAR_MEMBER_ALLOWLIST})
    assert unlisted == [], (
        "these modules send definition={'cedar': ...}. If the body uses `when guardrails`, a "
        "BedrockGuardrails:: provider or the suppressOutput effect, it will be rejected with "
        "'unexpected token guardrails' — use cedar.policy_definition(). If it is genuinely base "
        f"Cedar, add the file to CEDAR_MEMBER_ALLOWLIST with the reason: {unlisted}")


def test_every_allowlist_entry_still_exists_and_still_sends_the_member():
    """An allowlist nobody prunes becomes permission granted to files that no longer need it,
    and the next author reads a stale entry as precedent."""
    senders = {rel for rel, _, keys in _definition_sends() if "cedar" in keys}
    stale = sorted(set(CEDAR_MEMBER_ALLOWLIST) - senders)
    assert stale == [], (
        f"these allowlist entries no longer send the cedar member and should be removed: {stale}")
    for rel, reason in CEDAR_MEMBER_ALLOWLIST.items():
        assert len(reason) > 40, f"{rel}'s allowlist reason is too thin to be a reason"


def test_the_f1_grammar_module_sends_the_policy_member():
    """The instance fix, pinned. The module that paid for this discovery must not drift back,
    and the check is on the SEND — `create_arm` — not on a constant it might stop using."""
    src = (ROOT / "f1_config" / "04_policy_grammar.py").read_text(encoding="utf-8")
    assert "definition=C.policy_definition(statement)" in src
    assert '{"cedar": {"statement": statement}}' not in src
