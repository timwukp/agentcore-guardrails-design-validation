#!/usr/bin/env python3
"""Cedar policy construction, in one place, because five families author policies.

F2 (determinism), F3 (gateway-side efficacy), F4 (mode semantics), F5 (red team) and
`infra/03_policy_engine.py` all send Cedar statements. Building them ad hoc in five files
would guarantee drift in exactly the details that decide whether a policy compiles at all,
and a policy that fails to compile lands in `CREATE_FAILED` — which an arm reading "the
request was denied" would score as an enforcement result.

Everything here is a pure string builder. No AWS calls, no clock, no randomness, so the
whole module is testable offline and the statements in `results/` are reproducible from the
inputs recorded beside them.

The four facts this module encodes, each read off AWS documentation rather than recalled
--------------------------------------------------------------------------------------
1. **Action names.** `policy-scope.html` gives a per-target-type table: MCP targets use
   `<TargetName>___<ToolName>`, Runtime targets `<TargetName>___<METHOD>:/invocations`, HTTP
   proxy targets `<TargetName>___<METHOD>:<uri>`. Triple underscore in all three — the same
   delimiter `infra/echo_handler.py` splits on, and the same one
   `gateway-add-target-lambda.html` renders as a single underscore in prose. Our target is
   MCP/Lambda, so the first form applies.

2. **Cedar has no action wildcard.** `policy-scope.html` states it outright: each action must
   be named explicitly, and grouping is done by writing `action in AgentCore::Action::"<target
   name>"` against a *target* rather than by a pattern. This matters for F4: a truth table that
   wanted "deny every tool" cannot be written as `action like "grx*"`. `forbid(principal,
   action, resource)` — an unconstrained scope — is the documented way to match everything.

3. **Resource specificity is conditional.** When the scope names one or more *specific*
   actions, the resource must be a specific gateway ARN (`resource ==
   AgentCore::Gateway::"<arn>"`); a type check (`resource is AgentCore::Gateway`) is only for
   scopes that match any action. So `baseline_permit()` — which matches any action — correctly
   uses the type check, while every tool-specific arm must be handed a gateway ARN. Getting
   this backwards produces a validation finding, not a runtime deny, which is why
   `check_statement()` below refuses the combination locally before spending an API call.

4. **`when guardrails` replaces `when`, and needs a threshold.** Three separate documented
   constraints: no regex, no mixing standard `when {…}` with `when guardrails {…}`, and at
   least one guardrail definition per guardrails block. Plus: hand-written policies get **no**
   default threshold — the 0.2/0.4/0.2 defaults apply only to the natural-language authoring
   service. `guardrail_condition()` therefore requires a threshold argument with no default
   value at all, so a caller cannot omit it and silently inherit ours.

The score lattice and why there are exactly seven operating points
-----------------------------------------------------------------
`policy-guardrails-in-policies.html`: "Current possible scores are discrete values {0, 0.2,
0.4, 0.6, 0.8, and 1.0}". With a strict `greaterThan(τ)` over six possible scores, the number
of *distinct* classifiers is the number of ways τ can partition six ordered values, i.e. 7:

    τ < 0        -> all 6 scores exceed τ            (accept-everything)
    0.0 <= τ<0.2 -> 5 scores exceed τ
    0.2 <= τ<0.4 -> 4
    0.4 <= τ<0.6 -> 3
    0.6 <= τ<0.8 -> 2
    0.8 <= τ<1.0 -> 1
    τ >= 1.0     -> 0                                (accept-nothing)

`THRESHOLD_LATTICE` lists the six non-negative representatives. The seventh — the
accept-everything point — requires a **negative** threshold, and whether Cedar's `decimal`
accepts one is not documented on that page. It is exposed as `NEGATIVE_THRESHOLD` and marked
as an open empirical question rather than assumed either way: F3's ROC is a 7-vertex polyline
only if that vertex is constructible, and if the API rejects it the polyline has 6 vertices
and the report must say so. Guessing would put a fabricated vertex in a published figure.
"""

from __future__ import annotations

import re

# --- names ----------------------------------------------------------------

# `policy-scope.html`, "Action names by target type". Same delimiter as
# `infra/echo_handler.py`'s DELIMITER, duplicated here rather than imported because that file
# is deployed into a Lambda zip and must not import from `lib/`. The two are asserted equal in
# `infra/tests/test_cedar.py`, which is the only way a duplicated constant stays honest.
DELIMITER = "___"

NAMESPACE = "AgentCore"
ENTITY_ACTION = f"{NAMESPACE}::Action"
ENTITY_GATEWAY = f"{NAMESPACE}::Gateway"
ENTITY_IAM = f"{NAMESPACE}::IamEntity"
ENTITY_OAUTH = f"{NAMESPACE}::OAuthUser"

# --- guardrails -----------------------------------------------------------

GUARDRAIL_FUNCTIONS = {
    "ContentFilter": ("VIOLENCE", "HATE", "SEXUAL", "MISCONDUCT", "INSULTS"),
    "PromptAttack": ("JAILBREAK", "PROMPT_INJECTION", "PROMPT_LEAKAGE"),
    # The 31 SDK entity types are a superset; only the ones this project's corpora exercise
    # are listed, because an unlisted category must fail `check_statement` loudly rather than
    # be sent and rejected by the service after a resource has been created.
    "SensitiveInformation": (
        "CREDIT_DEBIT_CARD_NUMBER", "US_SOCIAL_SECURITY_NUMBER", "EMAIL", "PHONE",
        "ADDRESS", "AWS_ACCESS_KEY", "AWS_SECRET_KEY", "PASSWORD", "IP_ADDRESS",
        "NAME", "USERNAME",
    ),
}

COMPARATORS = ("greaterThan", "greaterThanOrEqual", "lessThan", "lessThanOrEqual")
AGGREGATIONS = ("confidenceScore", "maxConfidenceScore()", "minConfidenceScore()", "count()")

SCORE_LATTICE = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
THRESHOLD_LATTICE = ("0.0", "0.2", "0.4", "0.6", "0.8", "1.0")
# The seventh operating point. Constructibility is UNKNOWN — see the module docstring.
NEGATIVE_THRESHOLD = "-0.2"

# The documented authoring-service defaults. Present so F1 can assert that a hand-written
# policy omitting a threshold is REJECTED while these values are what the NL service supplies
# — i.e. so the numbers live in one place instead of in three prose comments.
AUTHORING_DEFAULTS = {"ContentFilter": "0.2", "PromptAttack": "0.4",
                      "SensitiveInformation": "0.2"}

EFFECTS = ("permit", "forbid", "suppressOutput")

_DECIMAL_RE = re.compile(r"^-?\d+\.\d{1,4}$")


def decimal_literal(value: str | float) -> str:
    """A Cedar `decimal("x.y")` literal, validated.

    Cedar's decimal type requires a decimal point and at most four fractional digits. `1` is
    not a decimal literal and `decimal("1")` is a type error; `0.20000` exceeds the precision.
    Both are rejected here rather than at the API, because the API rejection arrives as a
    generic validation finding attached to a policy that then sits in `CREATE_FAILED` — and
    `CREATE_FAILED` is the state DC-1 showed is easy to mistake for an enforcement result.

    A float input is formatted to one decimal place, which is exact for every value on the
    documented score lattice and would be wrong for anything else — so a float carrying more
    precision than the lattice can express raises instead of being silently rounded.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if abs(value * 10 - round(value * 10)) > 1e-9:
            raise ValueError(
                f"{value!r} is not expressible on the documented score lattice "
                f"{SCORE_LATTICE}; pass a string if a finer threshold is intended, so the "
                f"choice is visible in the policy text rather than produced by rounding.")
        text = f"{value:.1f}"
    else:
        text = str(value).strip()
    if not _DECIMAL_RE.match(text):
        raise ValueError(
            f"{text!r} is not a Cedar decimal literal: it needs a decimal point and 1-4 "
            f"fractional digits (`0.2`, not `0` or `.2` or `0.20000`).")
    return f'decimal("{text}")'


def action_id(target_name: str, tool_name: str) -> str:
    """The MCP action identifier: `<TargetName>___<ToolName>`."""
    if DELIMITER in target_name:
        raise ValueError(
            f"target name {target_name!r} contains {DELIMITER!r}, which makes the action "
            f"identifier ambiguous and breaks the handler's own rsplit-based parsing.")
    return f"{target_name}{DELIMITER}{tool_name}"


def action_ref(target_name: str, tool_name: str) -> str:
    return f'{ENTITY_ACTION}::"{action_id(target_name, tool_name)}"'


def guardrail_condition(function: str, categories: list[str] | tuple[str, ...],
                        paths: list[str] | tuple[str, ...], *,
                        threshold, category: str | None = None,
                        comparator: str = "greaterThan",
                        aggregation: str | None = None) -> str:
    """One guardrail assertion, e.g.

        BedrockGuardrails::ContentFilter(["HATE"],[context.output.message])["HATE"]
          .confidenceScore.greaterThan(decimal("0.2"))

    `threshold` is keyword-only and has **no default**, deliberately: the documented 0.2/0.4/
    0.2 defaults belong to the natural-language authoring service, and a default here would
    make a hand-written policy that forgot its threshold silently acquire one — turning the
    experiment that tests "hand-written policies need an explicit threshold" into a test of
    this module's default. `AUTHORING_DEFAULTS` is available for callers that want to
    reproduce the service's numbers *on purpose*.

    When `aggregation` is None the per-category form `[<category>].confidenceScore` is used
    and `category` defaults to the single requested category. `maxConfidenceScore()` and
    friends take no category subscript.
    """
    if function not in GUARDRAIL_FUNCTIONS:
        raise ValueError(f"unknown guardrail function {function!r}; "
                         f"known: {sorted(GUARDRAIL_FUNCTIONS)}")
    known = GUARDRAIL_FUNCTIONS[function]
    bad = [c for c in categories if c not in known]
    if bad:
        raise ValueError(f"{function} categories {bad} are not documented; known: {known}")
    if not categories:
        raise ValueError("at least one category is required")
    if not paths:
        raise ValueError(
            "at least one data path is required: the guardrail evaluates the values the paths "
            "extract, and a guardrails block with no path has nothing to score.")
    if comparator not in COMPARATORS:
        raise ValueError(f"unknown comparator {comparator!r}; known: {COMPARATORS}")

    cats = "[" + ", ".join(f'"{c}"' for c in categories) + "]"
    ps = "[" + ", ".join(paths) + "]"
    call = f"BedrockGuardrails::{function}({cats}, {ps})"

    if aggregation in (None, "confidenceScore"):
        cat = category or (categories[0] if len(categories) == 1 else None)
        if cat is None:
            raise ValueError(
                "a per-category confidenceScore needs an explicit `category` when more than "
                "one category is scanned; otherwise use aggregation='maxConfidenceScore()'.")
        if cat not in known:
            raise ValueError(f"category {cat!r} is not a documented {function} category")
        access = f'["{cat}"].confidenceScore'
    else:
        if aggregation not in AGGREGATIONS:
            raise ValueError(f"unknown aggregation {aggregation!r}; known: {AGGREGATIONS}")
        access = f".{aggregation}"

    return f"{call}{access}.{comparator}({decimal_literal(threshold)})"


def statement(effect: str, *, principal: str = "principal", action: str = "action",
             resource: str = "resource", when: str | None = None,
             unless: str | None = None, when_guardrails: str | None = None,
             unless_guardrails: str | None = None) -> str:
    """Assemble a complete Cedar statement, with the documented mixing rule enforced.

    `when`/`unless` and `when guardrails`/`unless guardrails` are mutually exclusive:
    `policy-guardrails-in-policies.html` says the guardrails block *replaces* the standard
    condition. A statement carrying both is rejected here so the failure is a local
    `ValueError` in a dry run rather than a `CREATE_FAILED` policy that a later arm reads as a
    deny.
    """
    if effect not in EFFECTS:
        raise ValueError(f"unknown effect {effect!r}; known: {EFFECTS}")
    g = [c for c in (when_guardrails, unless_guardrails) if c]
    s = [c for c in (when, unless) if c]
    if g and s:
        raise ValueError(
            "a Cedar statement cannot mix `when {...}` with `when guardrails {...}` — the "
            "guardrails block replaces the standard condition "
            "(policy-guardrails-in-policies.html, Limitations).")
    if len(g) > 1 or len(s) > 1:
        raise ValueError("at most one condition clause per statement")

    head = f"{effect} ({principal}, {action}, {resource})"
    if when:
        return f"{head}\nwhen {{ {when} }};"
    if unless:
        return f"{head}\nunless {{ {unless} }};"
    if when_guardrails:
        return f"{head}\nwhen guardrails {{\n    {when_guardrails}\n}};"
    if unless_guardrails:
        return f"{head}\nunless guardrails {{\n    {unless_guardrails}\n}};"
    return f"{head};"


def gateway_resource(gateway_arn: str | None) -> str:
    """`resource ==` a specific gateway, or the any-action type check."""
    if gateway_arn:
        return f'resource == {ENTITY_GATEWAY}::"{gateway_arn}"'
    return f"resource is {ENTITY_GATEWAY}"


def baseline_permit() -> str:
    """The statement our §3.1/§7.2/§8 tell readers to add, **verbatim**.

    This exact text is DC-1: policy `agentcore_test_pol_50513b5b-p6okjcbkkc` in this account's
    abandoned engine is precisely this statement and sits in `CREATE_FAILED` with two
    `Overly Permissive` findings. It is reproduced character-for-character so that F1-3's
    result is about the document's recommendation and not about a paraphrase of it.

    Note what is *not* here: `validationMode`. The mode is a `CreatePolicy` parameter, not part
    of the statement, and the whole point of F1-3 is that the document tells readers to send
    this statement without telling them which mode to send it under.
    """
    return "permit(principal, action, resource is AgentCore::Gateway);"


def assumed_role_principal(account_id: str, role_name: str) -> str:
    """The Cedar principal id for an assumed-role caller.

    `policy-conditions.html`: the entity id is `arn:aws:sts::<account>:assumed-role/<role>` —
    note **sts**, not iam, and **no session name**, even though `sts:GetCallerIdentity` returns
    an ARN that has one (`.../assumed-role/<role>/<session>`). Writing the caller-identity ARN
    into a policy would produce a principal that never matches, and the symptom would be a
    default-deny that looks exactly like the policy working.
    """
    if not account_id.isdigit() or len(account_id) != 12:
        raise ValueError(f"account_id must be 12 digits, got {account_id!r}")
    return f"arn:aws:sts::{account_id}:assumed-role/{role_name}"


def principal_eq_role(account_id: str, role_name: str) -> str:
    return f'principal == {ENTITY_IAM}::"{assumed_role_principal(account_id, role_name)}"'


def check_statement(text: str) -> list[str]:
    """Local lint. Returns a list of problems; empty means "nothing detectable offline".

    Deliberately **not** a Cedar parser. It checks only the handful of constraints that AWS
    documents and that we have seen produce a `CREATE_FAILED` or a never-matching policy, so a
    clean result here is not a claim of validity — it is a claim that the four known traps are
    absent. Real validation is the service's, and `03_policy_engine.py` reads `status` and
    `statusReasons` rather than trusting this function.
    """
    problems: list[str] = []
    if not text.rstrip().endswith(";"):
        problems.append("statement must end with `;`")
    if "when guardrails" in text and re.search(r"when\s*\{", text):
        problems.append("mixes `when {...}` with `when guardrails {...}` (documented as "
                        "unsupported: the guardrails block replaces the standard condition)")
    if "when guardrails" in text and "BedrockGuardrails::" not in text:
        problems.append("`when guardrails {...}` block contains no guardrail definition "
                        "(documented as required)")
    if re.search(r"action\s+like\s", text):
        problems.append("Cedar does not support wildcard actions; name each action or group "
                        "them with `action in AgentCore::Action::\"<target>\"`")
    # Specificity: a scope naming a concrete action needs a concrete gateway ARN.
    if f'{ENTITY_ACTION}::"' in text and "resource is " in text:
        problems.append(
            "a scope naming specific action(s) requires `resource == AgentCore::Gateway::"
            "\"<arn>\"`; `resource is AgentCore::Gateway` is only for any-action scopes")
    for m in re.finditer(r'decimal\("([^"]*)"\)', text):
        if not _DECIMAL_RE.match(m.group(1)):
            problems.append(f'decimal("{m.group(1)}") is not a valid Cedar decimal literal')
    if "BedrockGuardrails::" in text:
        for m in re.finditer(r"BedrockGuardrails::(\w+)", text):
            if m.group(1) not in GUARDRAIL_FUNCTIONS:
                problems.append(f"unknown guardrail function {m.group(1)!r}")
        if "decimal(" not in text:
            problems.append(
                "a hand-written guardrail policy must state its threshold explicitly; the "
                "0.2/0.4/0.2 defaults apply only to the natural-language authoring service")
    return problems


if __name__ == "__main__":
    # A few statements printed so the exact text can be inspected without an AWS call.
    gw = "arn:aws:bedrock-agentcore:us-east-1:<account>:gateway/grx-gw-example"
    samples = {
        "baseline_permit (DC-1, verbatim from our doc)": baseline_permit(),
        "F2-1 pure Cedar (no guardrail term)": statement(
            "permit", resource=gateway_resource(gw),
            action=f"action == {action_ref('grxecho', 'echo')}",
            when="context.input.amount < 500"),
        "F3 content filter on tool output": statement(
            "suppressOutput", resource=gateway_resource(gw),
            action=f"action == {action_ref('grxecho', 'echo')}",
            when_guardrails=guardrail_condition(
                "ContentFilter", ["HATE"], ["context.output.text"], threshold="0.2")),
        "F5-4a nonexistent context path": statement(
            "forbid", resource=gateway_resource(gw),
            action=f"action == {action_ref('grxecho', 'echo')}",
            when="context.input.doesNotExist == \"x\""),
    }
    for label, text in samples.items():
        print(f"--- {label}")
        print(text)
        probs = check_statement(text)
        print(f"    lint: {probs or 'no known trap detected'}\n")
