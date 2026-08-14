"""`cedar.statement()` cannot be called without a resource clause, and nobody does.

Why this file exists, stated as the failure it prevents rather than as the rule it enforces.

On 2026-08-13 all nine arms of F1-19, F1-24 and F1-25 came back INCONCLUSIVE from a live EC2
round. Not one of them measured anything. The cause was a single missing keyword argument:
`cedar.statement()` defaulted `resource` to the bare token `resource`, and
`f1_config/04_policy_grammar.py` was the only module in the repo that took the default. The API
refuses an unconstrained resource outright:

    "When parsing the policy statement, a wildcard resource was detected. To avoid unexpected
     behavior changes, please constrain the resource either to a specific AgentCore::Gateway
     resource or to the AgentCore::Gateway resource type."

Three things about that round are worth encoding as tests rather than as a comment somebody
reads once:

1. **The default was not lenient, it was invalid.** A default that cannot ever produce a valid
   value is worse than a required argument, because it turns a TypeError at desk into a 400 on
   an instance five minutes into a live round. `resource` is now required; the first arm below
   holds that.

2. **Only ONE of the eight arms reported the wildcard message** — F1-24's `split_when_only`, the
   sole arm without a guardrails block. The other seven failed at token level with `unexpected
   token guardrails`, and the first reading of that (recorded in FINDING-P1 §3 and since
   RETRACTED) was that the wildcard defect was "wearing a more alarming mask": one cause, two
   messages, the grammar check simply running first. That reading was wrong, and how it was wrong
   is the more useful lesson. It rested on a correlation across two GROUPS of observations —
   accepted policies elsewhere in the account vs these rejected arms — that differed in TWO
   variables at once: the resource form AND the `definition` union member. A comparison across
   groups cannot separate variables that covary within them, however exact the correlation looks.
   The token errors were caused entirely by the union member (see
   `test_definition_union_member.py`); the resource clause was a real, independent second defect
   that this file's scans hold. Both had to be repaired, and only an independent-variation design
   (`f1_config/diag_resource_form.py`) could say which was which.

3. **The fix belongs to the CLASS.** Fixing the three call sites would leave the next author to
   rediscover this. `test_no_production_caller_omits_the_resource_clause` scans the tree, so a
   fourth call site added later is a red test at desk. This is the same shape as
   `runner/tests/test_runner_policy.py`'s tagged-create scan: an argument-level defect is
   invisible to any check that enumerates function names, so the scan has to read ARGUMENTS.

NOT asserted here, deliberately: that a constrained resource is SUFFICIENT. It is not. F5-5
reached CREATE_FAILED with a properly scoped resource because `a provider's context field-path
argument must be declared on every action the rule applies to` — `context.output.text` is not in
the context of the echo action. That is a service constraint about action schemas, it is not
decidable from a statement string alone, and pretending otherwise here would be a test that
passes while the policy still fails.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import cedar as C

ROOT = Path(__file__).resolve().parents[2]

# Directories that hold production scripts — the ones whose statements go to the API. Test trees
# are excluded on purpose: a test may legitimately build a deliberately-invalid statement in
# order to assert that something rejects it, and `f1_config/tests/test_policy_grammar.py` does
# exactly that.
SKIP_PARTS = ("/tests/", "/.venv", "/.staging", "/__pycache__", "/.wheel_cache")


def _production_py_files() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        rel = "/" + p.relative_to(ROOT).as_posix()
        if any(s in rel for s in SKIP_PARTS):
            continue
        out.append(p)
    return out


def _statement_calls() -> list[tuple[str, int, frozenset[str]]]:
    """Every `*.statement(...)` / `statement(...)` call in production code, with its kwarg names.

    Keyed on (relpath, lineno, kwargs) rather than matched by regex because
    `f"forbid (principal, action, resource)"` and a real call are indistinguishable to a regex,
    and because a call spanning three lines — which two of the fixed sites now do — has its
    keywords on a different line from its name.
    """
    found = []
    for p in _production_py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file is the suite's problem, not ours
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if name != "statement":
                continue
            found.append((rel, node.lineno,
                          frozenset(k.arg for k in node.keywords if k.arg)))
    return found


# ------------------------------------------------------------------ the signature

def test_the_resource_argument_is_required():
    """The property that makes the whole class unrepeatable: omitting it is now a TypeError.

    Asserted through the real call rather than by reading `inspect.signature`, because a
    signature with `resource: str` and no default still permits a default to be reintroduced
    somewhere else (a wrapper, a partial) while this assertion keeps failing.
    """
    with pytest.raises(TypeError):
        C.statement("forbid", when="context.input.amount < 500")  # type: ignore[call-arg]


def test_the_resource_argument_is_keyword_only_and_has_no_default():
    sig = inspect.signature(C.statement)
    param = sig.parameters["resource"]
    assert param.default is inspect.Parameter.empty, \
        "a default on `resource` reintroduces the defect this file exists to prevent"
    assert param.kind is inspect.Parameter.KEYWORD_ONLY, \
        "positional `resource` would let a caller pass a condition into it by accident"


def test_the_bare_wildcard_token_is_not_what_the_helper_offers():
    """Whichever form a caller passes, it must be a real constraint and not the token that was
    defaulted before. The TYPE form is what §3.1 of the document under test writes; note that in
    this account it is not authorable by the runner role (it makes the statement an ADMIN policy
    requiring `bedrock-agentcore:ManageAdminPolicy`), which is why the F1 grammar module passes
    the specific-ARN form instead. That is an IAM fact, not a grammar fact, and it does not make
    the type form wrong to offer."""
    assert C.gateway_resource(None) == "resource is AgentCore::Gateway"
    assert C.gateway_resource(None) != "resource"
    arn = "arn:aws:bedrock-agentcore:us-east-1:111122223333:gateway/gw-abc"
    assert C.gateway_resource(arn) == f'resource == AgentCore::Gateway::"{arn}"'


# ------------------------------------------------------------------ the class scan

def test_the_statement_call_scan_finds_a_non_trivial_number_of_sites():
    """A scan that silently matched nothing would make every arm below vacuously green — the
    same reason the tagged-create scan in `runner/tests/` carries a floor. Deliberately a floor
    and not an exact count: an exact count goes red on legitimate growth, which teaches people
    to bump the number without reading why it moved."""
    calls = _statement_calls()
    assert len(calls) >= 20, (
        f"only {len(calls)} `statement(...)` calls found in production code; the scan is "
        f"probably broken rather than the repo having shrunk")


def test_no_production_caller_omits_the_resource_clause():
    """The class fix. A call site added later without `resource=` fails here, at desk, instead
    of as nine INCONCLUSIVE arms after a live round."""
    missing = [(rel, ln) for rel, ln, kw in _statement_calls() if "resource" not in kw]
    assert missing == [], (
        "these `cedar.statement(...)` calls omit `resource=` and will be rejected by the API "
        f"with 'a wildcard resource was detected': {missing}")


def test_the_f1_grammar_module_scopes_every_statement_it_hand_assembles():
    """The three helper call sites are covered by the scan above; the four HAND-ASSEMBLED
    statements in the same module are not, because they never call `statement()` at all — they
    are f-strings, which is precisely why they were missed the first time. This arm reads the
    source and asserts no bare `action, resource)` head survives there.

    Keyed on the file, not on line numbers: a tripwire that goes red when somebody adds a
    docstring above it gets deleted rather than fixed.
    """
    src = (ROOT / "f1_config" / "04_policy_grammar.py").read_text(encoding="utf-8")
    assert "action, resource)" not in src, (
        "a bare unconstrained resource head is back in f1_config/04_policy_grammar.py; the API "
        "rejects it and every arm of F1-19/24/25 returns INCONCLUSIVE")
    # every hand-assembled head now comes from Scope.head(), so there is exactly one place a
    # scope can be got wrong and the f-strings cannot drift from the helper-built statements
    assert "scope.head()" in src


def test_the_hand_built_and_helper_built_arms_carry_the_SAME_resource_clause():
    """The attribution the three cases rest on. F1-19's pair differs in the threshold tail and
    NOTHING else; F1-24's mixed arm differs from its split arms only in the mixing. A resource
    clause that drifted between hand-built and helper-built statements would add a second
    difference and make every accept/reject split uninterpretable — which is why the module
    holds one `STATEMENT_RESOURCE` constant instead of passing a literal at each site.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "grx_f1_04_policy_grammar_resource_probe",
        ROOT / "f1_config" / "04_policy_grammar.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    scope = mod.scope_for(
        "arn:aws:bedrock-agentcore:us-east-1:111122223333:gateway/grx-gw-test-only")
    assert scope.resource.startswith("resource == AgentCore::Gateway::")
    assert scope.action == C.action_eq(mod.ECHO_TARGET, mod.ECHO_TOOL)

    built = {
        "threshold_control (helper)": mod.threshold_control_statement(scope),
        "no_threshold (hand)": mod.no_threshold_statement(scope),
        "split_when (helper)": mod.split_when_statement(scope),
        "split_guardrails (helper)": mod.split_guardrails_statement(scope),
        "mixed (hand)": mod.mixed_statement(scope),
    }
    for label, form in mod.pattern_statements(scope).items():
        built[f"pattern:{label} (hand)"] = form["statement"]

    for label, stmt in built.items():
        first_line = stmt.splitlines()[0]
        assert scope.resource in first_line, \
            f"{label} does not carry {scope.resource!r}: {first_line!r}"
        assert scope.action in first_line, \
            f"{label} does not carry {scope.action!r}: {first_line!r}"
        assert "action, resource)" not in stmt, f"{label} still has a wildcard resource"


def test_the_scope_refuses_to_invent_a_gateway_arn():
    """A placeholder ARN reaching a live CreatePolicy would produce a rejection attributable to
    the harness — the precise failure mode this module has already had twice. `scope_for` has no
    default and refuses anything that is not an ARN, so the only way to get a scope is to have
    discovered a real gateway."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "grx_f1_04_policy_grammar_scope_probe", ROOT / "f1_config" / "04_policy_grammar.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    for bad in ("", None, "grx-gw-main", "resource is AgentCore::Gateway"):
        with pytest.raises(ValueError):
            mod.scope_for(bad)
