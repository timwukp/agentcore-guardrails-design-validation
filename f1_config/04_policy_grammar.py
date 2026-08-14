#!/usr/bin/env python3
"""F1-19 / F1-24 / F1-25 — CreatePolicy grammar probes against the live baseline engine.

    python3 f1_config/04_policy_grammar.py --dry-run
    python3 f1_config/04_policy_grammar.py

WHY THIS FILE, WITH THIS NAME
-----------------------------
`f1_config/02_model_surface.py` established (its SURFACE_ONLY table, F1-8 and F1-17 rows)
that a Cedar body travels as an opaque `definition.cedar.statement` string: no shape in any
of the four service models describes the grammar inside it, so every grammar question is a
server-side fact by construction, and that file names `f1_config/04_policy_grammar.py` as
the successor that closes them. RECONNECT.md's work order puts this file after F4. The name
is kept even though `04_update_revalidation.py` already carries the `04_` prefix: renaming
that file would move a sha256 its tests pin, and a duplicated prefix is cheaper than a
broken pin.

Scope note, so the deferral ledger stays honest: 02_model_surface defers FIVE cases to a
grammar probe — F1-8 (PromptAttack subtypes in the constructor), F1-17 (suppressOutput as an
effect), and the three decided here. **F1-8 and F1-17 remain OPEN after this script.** They
are not half-built here because F1-17's oracle needs an end-to-end tool call through the
echo Lambda ("...and suppresses tool output"), which is a different instrument from a parse
probe, and F1-8's per-subtype sweep belongs beside it. Their INCONCLUSIVE deferral records
from 02_model_surface stand until a successor decides them.

THE THREE SEALED CASES (claims/triage_rules.CASES, quoted by the dry-run banner)
--------------------------------------------------------------------------------
  F1-19  Threshold defaults 0.2/0.4/0.6 apply only via NL authoring.
         TRUE if hand-written Cedar omitting a threshold is REJECTED while NL authoring
         fills the documented defaults; FALSE if hand-written policies silently receive
         defaults. Method: paired CreatePolicy (hand-written, no threshold) vs
         StartPolicyGeneration.
  F1-24  when {} cannot be mixed with when guardrails {} in one policy.
         TRUE if a policy mixing both condition forms is rejected; FALSE if accepted.
         Method: CreatePolicy mutation: mixed policy vs two separate policies.
  F1-25  Guardrails-in-policy has no regex/pattern matching.
         TRUE if the policy grammar rejects a regex construct in a guardrails condition;
         FALSE if any pattern-matching form is accepted.

THE DELIBERATE BYPASS OF lib/cedar.py's GUARDS
----------------------------------------------
`cedar.statement()` REFUSES to assemble a statement mixing `when {}` with
`when guardrails {}` — it raises ValueError, because a local failure in a dry run beats a
CREATE_FAILED policy that a later arm misreads as a deny. `cedar.guardrail_condition()`
likewise requires a threshold with no default and validates function names and categories.
Those guards encode exactly the documented rules F1-24, F1-19 and F1-25 exist to TEST, so
this script needs the SERVICE's verdict on strings the helpers refuse to produce.

Three commitments make the bypass safe rather than silent:

(a) The bypass is DELIBERATE and total per arm: every statement predicted REJECTED is
    hand-assembled in a named builder below (`no_threshold_statement`, `mixed_statement`,
    `pattern_statements`), never routed through the helpers, and its arm record carries
    `built_by: "hand"` plus whatever `cedar.check_statement` says about it — for the
    malformed arms the lint findings are EXPECTED and recorded as confirmation that the
    local guard would have refused the string, i.e. that the bypass was necessary.

(b) `cedar.check_statement` is still run on every CONTROL statement, and a control that
    fails it aborts the case as not-measured. The bypass must not silently reach an arm
    that is supposed to be well-formed: a control malformed by the harness would be
    rejected by the service, "rejected" would be uninformative, and the predicted-rejected
    arm's rejection would read as the grammar holding when it was really the harness
    malforming BOTH requests. `bypass_partition_problems()` enforces the partition as
    data — every predicted-ACCEPTED arm must be helper-built and lint-clean, every
    predicted-REJECTED arm must be hand-built — and a violation aborts all three cases.

(c) The sacrificial subject is sacrificial IN THE PROPERTY UNDER TEST. This repo already
    paid for that lesson once: `f1_config/04_update_revalidation.py`'s "WHY F4'S PROBE
    COULD NOT HAVE CAUGHT THIS" section records that F4's re-validation probe ran against a
    cleanly-validating `forbid` statement, so a probe for "does the update re-validate?"
    had nothing for the re-validation to reject and could not fail — "a sacrificial subject
    must be sacrificial IN THE PROPERTY UNDER TEST, not merely disposable." Here that means
    the malformation each case asks about must be ON the sacrificial policy itself (the
    mixed conditions, the omitted threshold, the pattern construct), and the paired control
    must differ from it in ONLY that property, so an accept/reject split is attributable to
    the property and to nothing else.

HOW A GRAMMAR REJECTION IS DISTINGUISHED FROM A DC-1 VALIDATION FINDING
-----------------------------------------------------------------------
DC-1 (F1-3) and F1-11 (04_update_revalidation.py) established that this service ALSO fails
policies for semantic validation findings ("Overly Permissive ..."), and that omitting
`validationMode` makes even the baseline permit statement fail. A probe that failed for the
DC-1 reason and got scored as "the grammar rejected it" is the single most likely way this
script produces a wrong TRUE. Three defences, layered:

  1. Every CreatePolicy arm sends `validationMode=IGNORE_ALL_FINDINGS`. For a grammar probe
     the question is whether the BODY PARSES; an "Overly Permissive" finding is a semantic
     judgement about a body that parsed, not a grammar rejection, so the finding gate is
     switched off for every arm equally. This is the correct mode HERE and would be the
     wrong mode for F1-3, whose subject is the finding gate itself.
  2. Every statement uses effect `forbid`. A forbid cannot be "overly permissive", so the
     DC-1 finding class should be unreachable even before the mode is considered — two
     independent reasons, both recorded. (The scope was ALSO unconstrained when this was
     written. It is not any more: as of 2026-08-14 every statement names a specific gateway
     and the echo action, because those are the only values the service accepts here — see
     `Scope`. That strengthens this defence rather than weakening it.)
  3. The outcome is CLASSIFIED, never read off the rc: `classify_create_outcome` buckets
     each arm by error code and statusReasons text. A failure whose reasons match the DC-1
     "Overly Permissive" tokens is VALIDATION_FINDING and is never counted as a rejection;
     a throttle/conflict/access error is INFRASTRUCTURE and not measured; only a failure
     whose reasons/message match grammar tokens is REJECTED_GRAMMAR; anything else is
     UNCLASSIFIED and forces INCONCLUSIVE with the text recorded. Being wrong loudly beats
     being right silently — the same rule 03_permit_trap applies in the other direction.

BLAST RADIUS, AND WHY enforcementMode=LOG_ONLY
----------------------------------------------
Every sacrificial policy is created on the EXISTING baseline engine
(state.find("policy","baseline").ids["policy_engine_id"]), which the live `main` gateway
points at in ENFORCE mode. A sacrificial `forbid` that settled ACTIVE-and-enforcing would
change the shared gateway's deny behaviour for the seconds it exists, so every arm sends
`enforcementMode=LOG_ONLY`: grammar acceptance is a property of the body and the validator,
not of the enforcement mode, and LOG_ONLY keeps a transiently-live policy from denying a
concurrent family's tool call. Nothing pre-existing is touched: not the baseline policy,
not the two abandoned engines, not the six READY gateways, not the three DRAFT guardrails,
not the `nopolicy` gateway, and no `harness_*`/`uitestagent_*` resource. The baseline
policy's status is re-read (read-only) after teardown and the run exits 2 if it is not
still ACTIVE.

TEARDOWN AND RESIDUE
--------------------
Every created policy is registered in state.json the moment CreatePolicy returns (policies
are structurally untaggable — CreatePolicy has no tags member, testbed.TAG_INDEX_BLIND_KINDS
— so the ledger is the ONLY channel that finds a survivor). Deletion happens in a per-case
`finally`, and residue is computed by `policy_residue` from the created-vs-deleted lists,
never from the deletions list alone: a policy whose delete was never ATTEMPTED (the loop
died between create and finally) contributes no deletion row at all, so a residue computed
from deletions would report zero survivors for exactly the case where one exists — the same
two-list reasoning as phase1.probe_residue, per policy id, never one bool.

One residue class is UNDELETABLE BY CONSTRUCTION and is reported, not gated on: F1-19's arm
B creates a policy GENERATION, and the service model exposes no DeletePolicyGeneration —
the 22 Policy* operations carry Start/Get/List for generations and no Delete (verified
against the bundled model in this file's own run record). A generation is a draft artifact,
not a policy: it enforces nothing and appears on no evaluation path, so it cannot change
the testbed's behaviour; it is removed when 99_teardown deletes the engine. It is named in
the payload as `undeletable_residue` rather than silently omitted, and it does NOT flip the
exit code, because rc=2 for a residue no API call can remove would train operators to
ignore rc=2.

EXIT CODES (repo convention: rc reports whether the test RAN, never whether the document
was right): rc=0 every case measured and every deletable resource cleaned up; rc=2 nothing
measured, or teardown left a deletable survivor, or the baseline policy is no longer
ACTIVE; rc=1 an unclassified outcome or a case that could not be measured while others
were.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import time
from pathlib import Path
from typing import Any, NamedTuple, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import cedar as C        # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
import testbed as T      # noqa: E402
from evidence import EvidenceStore, capture  # noqa: E402

FAMILY = "f1"
CASES = ("F1-19", "F1-24", "F1-25")

IGNORE = "IGNORE_ALL_FINDINGS"
LOG_ONLY = "LOG_ONLY"

# One definition of "terminal" for policies, imported from the provisioner exactly as
# 03_permit_trap.py does and for the same reason: two definitions of terminal would be two
# definitions of what CREATE_FAILED means, and every verdict here is a status read.
_spec = importlib.util.spec_from_file_location(
    "_grx_policy_engine", ROOT / "infra" / "03_policy_engine.py")
_pe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pe)
wait_status = _pe.wait_status
TERMINAL_OK = _pe.TERMINAL_OK
TERMINAL_BAD = _pe.TERMINAL_BAD

# Policy generations have their own status alphabet (GetPolicyGeneration output enum);
# wait_status's TERMINAL sets do not cover it, so the generation poll is separate.
GENERATION_TERMINAL = ("GENERATED", "GENERATE_FAILED", "DELETE_FAILED")
GENERATION_TIMEOUT_S = 300.0
GENERATION_SLEEP_S = 5.0

# The DC-1 finding tokens, same tuple as 03_permit_trap.OVERLY_PERMISSIVE_TOKENS. Matched
# case-insensitively against joined statusReasons / error message. A failure matching one
# of these is a semantic VALIDATION FINDING and must never be scored as a grammar
# rejection: that mistake is the single most likely wrong TRUE this script can produce.
OVERLY_PERMISSIVE_TOKENS = ("overly permissive", "overlypermissive", "too permissive",
                            "permits all", "unconstrained", "overly broad")

# Tokens that make a failure attributable to the GRAMMAR (a body that did not parse or a
# construct the grammar refuses). Checked only AFTER the finding tokens, so a DC-1 text
# containing "invalid" can never fall through into this bucket. The set is deliberately
# broad on parser vocabulary and an unmatched failure is UNCLASSIFIED (INCONCLUSIVE, rc=1),
# never TRUE: the service's exact wording is not knowable offline, and guessing it in the
# permissive direction is how a throttle becomes "the grammar held".
GRAMMAR_TOKENS = ("syntax", "parse", "unexpected", "invalid", "unsupported",
                  "not supported", "not allowed", "cannot", "unable to", "malformed",
                  "unknown", "expected", "unrecognized", "unrecognised", "grammar",
                  "condition", "guardrail", "operator", "wildcard", "pattern", "regex",
                  "threshold", "decimal", "mix")

# Error codes that mean the INSTRUMENT (network, quota, name collision), not the grammar.
INFRASTRUCTURE_CODES = frozenset({
    "ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException",
    "ConflictException", "AccessDeniedException", "InternalServerException",
    "InternalFailure", "ServiceUnavailableException", "ServiceUnavailable",
    "ResourceNotFoundException", "RequestTimeout", "EndpointConnectionError",
})

# Outcome alphabet for one CreatePolicy arm.
ACCEPTED = "ACCEPTED"
REJECTED_GRAMMAR = "REJECTED_GRAMMAR"
VALIDATION_FINDING = "VALIDATION_FINDING"
INFRASTRUCTURE = "INFRASTRUCTURE"
NOT_SETTLED = "NOT_SETTLED"
UNCLASSIFIED = "UNCLASSIFIED"

# The standard condition and the guardrails condition F1-24 splits. Held as module
# constants so the mixed statement and the two split statements are built from the SAME
# two strings: the sealed mutation is "the SAME two conditions split across two separate
# policies", and three ad-hoc copies could drift into three different conditions.
STD_CONDITION = 'context.input.text == "grx-value-that-is-never-equal"'
GUARDRAIL_FN = "ContentFilter"
GUARDRAIL_CATEGORY = "HATE"
GUARDRAIL_PATH = "context.input.text"
EXPLICIT_THRESHOLD = "0.2"

# The gateway target and tool the scope names; the same echo tool F5-4a's ACTIVE guardrails
# policies used. Kept as constants so the scope helper and any future arm cannot disagree.
ECHO_TARGET = "grxecho"
ECHO_TOOL = "echo"

# WHY STD_CONDITION AND GUARDRAIL_PATH ARE THESE STRINGS AND NOT THE ONES THEY WERE
# ---------------------------------------------------------------------------------
# Both were changed on 2026-08-14 after `f1_config/diag_resource_form.py`'s 17-cell factorial
# probe. Neither change is a convenience; each is forced by a categorical service refusal, and
# the previous values could not have produced a measurement at all.
#
#   GUARDRAIL_PATH was `context.output.text`. Any policy with an authorization effect
#   (permit/forbid) that references an output path is refused outright, independent of
#   resource, action and union member:
#
#       "references 'context.output' but the policy has an authorization effect.
#        Use 'context.input.*' data paths"
#
#   That is not a property of these three claims — it is a property of every forbid statement
#   the service will accept. `f4_modes/00_syntax_probe.py`'s F4-0 calibration already recorded
#   it on 2026-08-11 (evidence/.../f4_modes/F4-0/calibration.json, cells policy.doc_syntax and
#   policy.plain_when); this module was written without consulting it. Output-path guardrails
#   are reachable only through the `suppressOutput` effect, which is F1-17's subject, not
#   F1-19/24/25's.
#
#   STD_CONDITION was `context.input.amount < 500`. A condition's attributes are validated
#   against the schema of every action the statement reaches, and the echo tool has no
#   `amount` attribute (probe cell 15: CREATE_FAILED, `input.amount` not present in the
#   context of the action). `context.input.text == "grx-value-that-is-never-equal"` is the
#   same SHAPE of condition — one standard Cedar comparison over a context attribute — over an
#   attribute that exists. Probe cell 17 confirmed it reaches ACTIVE.
#
# FINDING-P1 §6 pre-registered the rule that the path must not be "quietly switched" to
# `context.input.text`, because that would change what the cases measure. The switch is made
# anyway and the register is honoured, not evaded, because the choice the prediction imagined
# does not exist: it is switch-or-never-measure, not switch-or-measure-the-stricter-thing. What
# the three cases now measure is stated exactly:
#
#   * F1-19 asks whether a hand-written guardrail call with NO threshold is rejected. The path
#     is a fixed property of BOTH its arm and its control, so it is not the variable.
#   * F1-24 asks whether the two condition FORMS can be mixed. Both split arms carry the same
#     strings the mixed statement does.
#   * F1-25 asks whether pattern operators are accepted inside a guardrails block.
#
# In none of the three does the input/output distinction enter the sealed oracle. What IS lost
# is generality: a TRUE here is now evidence about input-path guardrails only. That limitation
# is carried into each payload's `what_true_does_not_prove`, and the output-path refusal is
# recorded as a mechanism observation in results/FINDING-P1-CEDAR-RESOURCE-SCOPE.md.

# THE SCOPE CLAUSE, AND WHY IT IS AN ARGUMENT AND NOT A MODULE CONSTANT
# ---------------------------------------------------------------------
# `Scope` is the `action ==` / `resource ==` pair every statement in this module carries,
# hand-built and helper-built alike. One object threaded through every builder, for the same
# reason STD_CONDITION is one string: the hand-built arms exist to differ from the
# helper-built ones in exactly ONE property, and a scope that drifted between them would add a
# second difference and silently destroy the attribution all three cases rest on.
#
# It was a module constant (`STATEMENT_RESOURCE = C.gateway_resource(None)`, the TYPE form) for
# one day, on the reasoning that these cases concern the AUTHORING surface, are never evaluated
# against traffic, and should therefore carry the resource form §3.1 of the document writes.
# That reasoning was wrong in a way no amount of reading could have revealed, and the 17-cell
# probe in `f1_config/diag_resource_form.py` is what revealed it. Three service facts, each
# proven live and each fatal to the old shape:
#
#   1. The TYPE form makes the statement an ADMIN policy. `resource is AgentCore::Gateway`
#      returns `AccessDeniedException: not authorized to perform
#      bedrock-agentcore:ManageAdminPolicy` (probe cells 11 and 16), which the grx-runner-ec2
#      role does not hold and should not be granted for a grammar probe. So the document's own
#      §3.1 example is, in this account, unauthorable — a fact about IAM surface area, not
#      about grammar, and one this module must route around rather than measure.
#   2. With a CONSTRAINED action the type form is refused outright: "a constrained action scope
#      was encountered, please constrain the resource to a specific AgentCore::Gateway
#      resource" (cell 13). The action and resource scopes are coupled; they cannot be chosen
#      independently.
#   3. An UNCONSTRAINED action makes every context attribute validate against every action on
#      the engine, including service built-ins: "argument `context.input.text` is not present
#      in the context of action `AgentCore::Action::\"CallTool\"`" (cell 12). So `action` cannot
#      be left bare either, whatever the data path is.
#
# What is left is exactly one authorable shape, and it needs a live gateway ARN: hence an
# argument. The shape reached ACTIVE three times in the probe (cells 9, 14 and 17 — 14
# deliberately replicating 9, because a positive control that runs once is an anecdote).
#
# The earlier repair — making `resource` a required argument of `cedar.statement()` — was
# necessary and stands. It was not sufficient, and FINDING-P1 §3's reading of WHY (that the
# `unexpected token guardrails` error was the wildcard defect "wearing a mask") was wrong. The
# actual cause of those token errors was the `definition` union member; see `create_arm`.


class Scope(NamedTuple):
    """The action/resource pair, and the statement head built from it."""
    action: str
    resource: str

    def head(self, effect: str = "forbid") -> str:
        """The head the hand-assembled f-strings use, byte-identical to the one
        `cedar.statement()` builds, so the two provenances cannot drift."""
        return f"{effect} (principal, {self.action}, {self.resource})"


def scope_for(gateway_arn: str) -> Scope:
    """The one authorable scope: this gateway, the echo tool.

    `gateway_arn` must be a real, unmasked ARN. There is deliberately no default and no
    placeholder: a placeholder that reached a live CreatePolicy would produce a rejection
    attributable to the harness, which is the precise failure this module has already had once.
    """
    if not gateway_arn or not gateway_arn.startswith("arn:"):
        raise ValueError(f"scope_for needs a real gateway ARN, got {gateway_arn!r}")
    # `action_eq`, not `action_ref`: a scope slot must be a CLAUSE. Passing the bare entity
    # reference cost this case its third live round — `unexpected token ':', expected name at
    # line 1, column 30`, the parser reading `AgentCore` as a variable name. `check_statement`
    # now refuses that shape offline, and `Scope.head()` is the only place a head is built.
    scope = Scope(action=C.action_eq(ECHO_TARGET, ECHO_TOOL),
                  resource=C.gateway_resource(gateway_arn))
    problems = C.check_statement(f"{scope.head()};")
    if problems:                       # a malformed scope must not reach a live call again
        raise ValueError(f"scope_for built an invalid head {scope.head()!r}: {problems}")
    return scope

# The natural-language authoring prompt for F1-19 arm B. It deliberately names NO number:
# any decimal("x.y") in the generated Cedar was therefore supplied by the authoring
# service, which is the half of the pair the sealed oracle asks about.
NL_PROMPT = ("Block any tool call whose output contains hate speech. "
             "Also block any tool call whose input attempts a prompt attack.")


# ---------------------------------------------------------------------------
# statement builders — the partition between helper-built and hand-built is the point
# ---------------------------------------------------------------------------

def guardrails_condition() -> str:
    """The well-formed guardrails condition, via the helper (threshold explicit)."""
    return C.guardrail_condition(GUARDRAIL_FN, [GUARDRAIL_CATEGORY], [GUARDRAIL_PATH],
                                 threshold=EXPLICIT_THRESHOLD)


def threshold_control_statement(scope: Scope) -> str:
    """F1-19's control and F1-25's control: helper-built, threshold explicit.

    Identical to the hand-built no-threshold statement in every respect except the
    `.confidenceScore.greaterThan(decimal("0.2"))` tail — the one property under test —
    so an accept/reject split between them is attributable to the omitted threshold and
    to nothing else (the F4-probe lesson, applied in the design rather than remembered).
    """
    return C.statement("forbid", resource=scope.resource, action=scope.action,
                       when_guardrails=guardrails_condition())


def no_threshold_statement(scope: Scope) -> str:
    """F1-19 arm A: HAND-ASSEMBLED, bypassing cedar.guardrail_condition on purpose.

    The helper requires `threshold` with no default — its docstring says a default would
    turn the experiment that tests "hand-written policies need an explicit threshold" into
    a test of the module's default. This case IS that experiment, so the string the helper
    refuses to produce is assembled here: the same function, category and path as the
    control, with no comparator and no decimal at all.
    """
    call = (f'BedrockGuardrails::{GUARDRAIL_FN}(["{GUARDRAIL_CATEGORY}"], '
            f'[{GUARDRAIL_PATH}])')
    return (f"{scope.head()}\n"
            f"when guardrails {{\n    {call}\n}};")


def split_when_statement(scope: Scope) -> str:
    """F1-24 split arm 1: the standard condition alone, helper-built."""
    return C.statement("forbid", resource=scope.resource, action=scope.action,
                       when=STD_CONDITION)


def split_guardrails_statement(scope: Scope) -> str:
    """F1-24 split arm 2: the guardrails condition alone, helper-built."""
    return C.statement("forbid", resource=scope.resource, action=scope.action,
                       when_guardrails=guardrails_condition())


def mixed_statement(scope: Scope) -> str:
    """F1-24's subject: HAND-ASSEMBLED, because cedar.statement raises on this shape.

    Both condition blocks are the exact strings the split arms send — assembled from the
    same constants — so a rejection here paired with two acceptances there isolates the
    MIXING as the rejected property.
    """
    return (f"{scope.head()}\n"
            f"when {{ {STD_CONDITION} }}\n"
            f"when guardrails {{\n    {guardrails_condition()}\n}};")


def pattern_statements(scope: Scope) -> dict[str, dict[str, str]]:
    """F1-25's subjects: two pattern-matching forms, both HAND-ASSEMBLED.

    Two forms rather than one because the sealed FALSE branch is "if ANY pattern-matching
    form is accepted": a single-form probe under-covers a FALSE. Two is still not "any" —
    the payload's what_true_does_not_prove says which forms remain unprobed.

    Each form's rejection has a stated reading, because a rejection can have more than one
    cause and the honest record says which causes are indistinguishable.
    """
    base = guardrails_condition()
    return {
        "like_on_path": {
            "statement": (f"{scope.head()}\n"
                          f"when guardrails {{\n    {base} && "
                          f'{GUARDRAIL_PATH} like "*jailbreak*"\n}};'),
            "why": ("Cedar's own pattern operator (`like` with `*` globs) applied to the "
                    "data path inside the guardrails block — the most direct construct "
                    "the document's 'no regex/pattern matching' limitation forbids, and "
                    "the one a reader who knows standard Cedar would reach for first"),
            "rejection_reading": (
                "a rejection is attributable to the guardrails grammar refusing a pattern "
                "operator, OR to it refusing any non-guardrail term beside the guardrail "
                "call. Both causes are the documented limitation behaving as documented; "
                "the two are not distinguishable from statusReasons alone and are not "
                "claimed to be"),
        },
        "regex_shaped_category": {
            "statement": (f"{scope.head()}\n"
                          f"when guardrails {{\n"
                          f'    BedrockGuardrails::{GUARDRAIL_FN}(["HATE.*"], '
                          f'[{GUARDRAIL_PATH}])["HATE.*"].confidenceScore'
                          f'.greaterThan(decimal("{EXPLICIT_THRESHOLD}"))\n}};'),
            "why": ("a regex-shaped string in the CATEGORY slot — where a reader would "
                    "most plausibly put a pattern to match several categories at once. "
                    "cedar.guardrail_condition refuses this locally (unknown category), "
                    "so it is hand-assembled"),
            "rejection_reading": (
                "a rejection is consistent with 'no pattern matching' AND with 'category "
                "must be a documented literal'. Operationally the two are the same fact — "
                "the category slot does not evaluate patterns — but this form alone could "
                "not carry the case, which is why like_on_path is probed beside it"),
        },
    }


def bypass_partition_problems(arms: Sequence[dict]) -> list[str]:
    """Every way the helper bypass could have leaked into the wrong arm.

    Each arm dict carries `label`, `statement`, `predict` ("accepted"/"rejected") and
    `built_by` ("helpers"/"hand"). Two invariants, both fatal to all three cases:

      * a predicted-ACCEPTED arm must be helper-built AND pass cedar.check_statement —
        otherwise the bypass has quietly reached an arm meant to be well-formed, and a
        rejection elsewhere reads as the grammar holding when it was really the harness
        malforming requests;
      * a predicted-REJECTED arm must be hand-built — the helpers refuse these strings by
        design, so an arm claiming to be helper-built either means cedar.py's guard was
        weakened or the arm is not testing what its label says.
    """
    problems: list[str] = []
    for arm in arms:
        lint = C.check_statement(arm["statement"])
        if arm["predict"] == "accepted":
            if arm["built_by"] != "helpers":
                problems.append(
                    f"{arm['label']}: predicted accepted but built_by={arm['built_by']!r}; "
                    f"the hand-assembly bypass must never reach an arm that is supposed "
                    f"to be well-formed")
            if lint:
                problems.append(
                    f"{arm['label']}: predicted accepted but cedar.check_statement flags "
                    f"{lint}; a control the harness malformed makes every rejection in "
                    f"its case uninformative")
        elif arm["predict"] == "rejected":
            if arm["built_by"] != "hand":
                problems.append(
                    f"{arm['label']}: predicted rejected but built_by={arm['built_by']!r}; "
                    f"the helpers refuse to produce these strings, so this label cannot "
                    f"be true unless cedar.py's guard was weakened")
        else:
            problems.append(f"{arm['label']}: unknown prediction {arm['predict']!r}")
    return problems


# ---------------------------------------------------------------------------
# outcome classification — a rejection is a CLASSIFIED fact, never an rc read
# ---------------------------------------------------------------------------

def classify_create_outcome(*, http_ok: bool, error_code: str = "",
                            error_message: str = "", terminal_status: str | None = None,
                            status_reasons: Sequence[str] = (),
                            timed_out: bool = False) -> dict[str, Any]:
    """Bucket one CreatePolicy arm's fate. Pure; the offline tests mutate against it.

    Order of checks is load-bearing: the DC-1 finding tokens are matched BEFORE the
    grammar tokens, because the finding text contains words ("unconstrained") that would
    otherwise satisfy the grammar bucket — the exact substitution this function exists to
    prevent. An unmatched failure is UNCLASSIFIED, which no decider ever converts into a
    TRUE.
    """
    reasons = [str(r) for r in status_reasons]
    joined = (" ".join(reasons) + " " + (error_message or "")).lower()
    finding_hits = [t for t in OVERLY_PERMISSIVE_TOKENS if t in joined]
    grammar_hits = [t for t in GRAMMAR_TOKENS if t in joined]
    base = {"reasons": reasons, "error_code": error_code or "",
            "matched_finding_tokens": finding_hits,
            "matched_grammar_tokens": grammar_hits}

    if not http_ok:
        if error_code in INFRASTRUCTURE_CODES:
            return {**base, "outcome": INFRASTRUCTURE,
                    "why": (f"synchronous {error_code}: the instrument, not the grammar, "
                            f"is what failed; nothing about the body was judged")}
        if finding_hits:
            return {**base, "outcome": VALIDATION_FINDING,
                    "why": ("the error text carries the DC-1 finding vocabulary; a "
                            "validation finding is a semantic judgement about a body that "
                            "parsed and is never a grammar rejection")}
        if error_code == "ValidationException" and grammar_hits:
            return {**base, "outcome": REJECTED_GRAMMAR,
                    "why": "synchronous ValidationException with parser vocabulary"}
        return {**base, "outcome": UNCLASSIFIED,
                "why": (f"synchronous {error_code or 'error'} whose text matches neither "
                        f"the finding tokens nor the grammar tokens; an unread rejection "
                        f"must not be counted for either side")}

    if timed_out or terminal_status is None:
        return {**base, "outcome": NOT_SETTLED,
                "why": "the status never became terminal, so there is nothing to classify"}
    if terminal_status in TERMINAL_OK:
        return {**base, "outcome": ACCEPTED, "why": "settled ACTIVE"}
    if terminal_status == "CREATE_FAILED":
        if finding_hits:
            return {**base, "outcome": VALIDATION_FINDING,
                    "why": ("CREATE_FAILED whose statusReasons are the DC-1 finding class "
                            "— under validationMode=IGNORE_ALL_FINDINGS this should be "
                            "unreachable, so beyond not being a grammar rejection it is "
                            "evidence the finding gate fired despite the mode, which is "
                            "its own record")}
        if grammar_hits:
            return {**base, "outcome": REJECTED_GRAMMAR,
                    "why": "CREATE_FAILED with parser vocabulary in statusReasons"}
        return {**base, "outcome": UNCLASSIFIED,
                "why": ("CREATE_FAILED with reasons this script cannot place; forcing "
                        "INCONCLUSIVE with the text recorded beats scoring an unread "
                        "failure as the grammar holding")}
    return {**base, "outcome": UNCLASSIFIED,
            "why": f"terminal status {terminal_status!r} is not a shape this probe expects"}


# ---------------------------------------------------------------------------
# F1-19's generated-body reading
# ---------------------------------------------------------------------------

_GUARD_CALL_RE = re.compile(r"BedrockGuardrails::(\w+)\s*\(")
_GUARD_THRESH_RE = re.compile(
    r'BedrockGuardrails::(\w+)\s*\((?:(?!BedrockGuardrails::).)*?decimal\("([^"]+)"\)',
    re.S)


def generation_statements(assets: Sequence[dict]) -> list[str]:
    """Every Cedar body in a ListPolicyGenerationAssets response, both union arms read."""
    out: list[str] = []
    for a in assets or []:
        d = a.get("definition") or {}
        for key in ("cedar", "policy"):
            st = ((d.get(key) or {}).get("statement")) or ""
            if st:
                out.append(str(st))
    return out


def generation_asset_findings(assets: Sequence[dict]) -> list[dict[str, str]]:
    """Per-fragment findings from ListPolicyGenerationAssets, flattened with their fragment.

    WHY THIS IS READ AND NOT JUST THE STATEMENTS
    --------------------------------------------
    Round 5 (2026-08-14) reached `GENERATED` and produced ZERO statements, and the summary said
    only `measurable=False, why="the generation produced no BedrockGuardrails call"`. That is our
    INFERENCE from an absence. What the service actually returned, per fragment, was:

        {"type": "INVALID", "description": "Non-translatable: cannot be expressed in Dogwood"}

    for both "Block any tool call whose output contains hate speech." and "Block any tool call
    whose input attempts a prompt attack." — an explicit refusal, naming the reason, on exactly the
    two intents the document's §3.1 defaults are about.

    An absence and a documented refusal are different observations and support different claims.
    "We saw no guardrails call" is compatible with a probe that asked wrongly; "the service reports
    this intent is non-translatable" is the service's own account of why, and it is the sentence a
    reader of the design document needs. Dropping it and keeping only the count was the reporting
    equivalent of reading a 400's status code and discarding its message — the same mistake that
    cost this case three rounds, in the opposite direction.

    `type` is kept verbatim rather than mapped to a boolean: this project has one observation of
    one vocabulary, and normalising an alphabet seen once invents a taxonomy.
    """
    out: list[dict[str, str]] = []
    for a in assets or []:
        frag = str(a.get("rawTextFragment") or "")
        for f in a.get("findings") or []:
            out.append({"fragment": frag,
                        "type": str(f.get("type") or ""),
                        "description": str(f.get("description") or "")})
    return out


def extract_guardrail_thresholds(text: str) -> dict[str, list[str]]:
    """function name -> decimal literals attached to its calls, in order of appearance."""
    found: dict[str, list[str]] = {}
    for m in _GUARD_THRESH_RE.finditer(text):
        found.setdefault(m.group(1), []).append(m.group(2))
    return found


def authoring_defaults_check(statements: Sequence[str]) -> dict[str, Any]:
    """Did the NL authoring service fill the documented defaults?

    Compared against cedar.AUTHORING_DEFAULTS — the one place those numbers live — rather
    than against literals here, so this file cannot drift from the module every other
    family reads them from. Three-way answer:

      * measurable=False when no guardrail call was generated at all, or a call names a
        function outside AUTHORING_DEFAULTS (an unread comparison must not decide);
      * matched=False when a generated call carries NO threshold (the service did not fill
        a default), or carries a number that is not the documented default for its
        function;
      * matched=True only when every generated guardrail call carries exactly its
        function's documented default.
    """
    calls: dict[str, int] = {}
    thresholds: dict[str, list[str]] = {}
    for text in statements:
        for m in _GUARD_CALL_RE.finditer(text):
            calls[m.group(1)] = calls.get(m.group(1), 0) + 1
        for fn, vals in extract_guardrail_thresholds(text).items():
            thresholds.setdefault(fn, []).extend(vals)

    unknown = sorted(set(calls) - set(C.AUTHORING_DEFAULTS))
    out: dict[str, Any] = {
        "n_statements": len(statements),
        "calls_per_function": calls,
        "thresholds_per_function": thresholds,
        "unknown_functions": unknown,
        "expected_defaults": dict(C.AUTHORING_DEFAULTS),
        "defaults_source": ("lib/cedar.py AUTHORING_DEFAULTS — the single home of the "
                            "documented 0.2/0.4/0.2 numbers, not retyped here"),
    }
    if not calls:
        out.update(measurable=False, matched=None,
                   why=("the generation produced no BedrockGuardrails call, so there is "
                        "no threshold to compare; the NL prompt did not translate to a "
                        "guardrails-in-policy condition"))
        return out
    if unknown:
        out.update(measurable=False, matched=None,
                   why=(f"generated function(s) {unknown} are outside AUTHORING_DEFAULTS; "
                        f"comparing them against a default nobody documented would "
                        f"manufacture a verdict"))
        return out
    missing = sorted(fn for fn, n in calls.items()
                     if len(thresholds.get(fn, [])) < n)
    if missing:
        out.update(measurable=True, matched=False,
                   why=(f"generated call(s) for {missing} carry no decimal threshold at "
                        f"all: the authoring service did NOT fill a default"))
        return out
    mismatched = {fn: vals for fn, vals in thresholds.items()
                  if any(v != C.AUTHORING_DEFAULTS[fn] for v in vals)}
    out.update(measurable=True, matched=not mismatched, mismatched=mismatched,
               why=("every generated guardrail call carries exactly its function's "
                    "documented default" if not mismatched else
                    f"generated thresholds disagree with the documented defaults: "
                    f"{mismatched}"))
    return out


# ---------------------------------------------------------------------------
# the paired-verdict deciders, one per case — pure, and the offline tests' main target
# ---------------------------------------------------------------------------

def decide_f1_19(a_outcome: str, control_outcome: str, *, generation_terminal: bool,
                 defaults: dict[str, Any]) -> dict[str, Any]:
    """F1-19 is a conjunction over a PAIR, and a missing half is not a refutation."""
    if control_outcome != ACCEPTED:
        return {"measurable": False, "observed": None,
                "why": (f"the control (same statement WITH an explicit threshold) did not "
                        f"reach a usable state (outcome {control_outcome}); without it, "
                        f"'rejected' is uninformative — the create might fail for any "
                        f"reason, the same control logic 02_model_surface's F1-4 block "
                        f"uses with its length-1 policyEngineId")}
    if a_outcome == ACCEPTED:
        return {"measurable": True, "observed": False,
                "why": ("hand-written Cedar omitting a threshold was ACCEPTED; the sealed "
                        "TRUE branch ('omitting a threshold is REJECTED') is refuted "
                        "regardless of what the NL half does. Whether the stored body "
                        "silently acquired a default is read back and recorded beside "
                        "this")}
    if a_outcome != REJECTED_GRAMMAR:
        return {"measurable": False, "observed": None,
                "why": (f"the hand-written arm's failure is {a_outcome}, not a grammar "
                        f"rejection; a validation finding, an infrastructure error or an "
                        f"unclassified failure is not the event the oracle names")}
    if not generation_terminal or not defaults.get("measurable"):
        return {"measurable": False, "observed": None,
                "why": ("the hand-written half rejected as predicted, but the NL "
                        "authoring half could not be read to a comparable answer ("
                        + str(defaults.get("why") or "generation never reached a terminal "
                              "state") +
                        "); a missing half is not a refutation, so this is not-measured "
                        "rather than FALSE")}
    return {"measurable": True, "observed": bool(defaults.get("matched")),
            "why": ("hand-written-no-threshold REJECTED and the generated body carries "
                    "the documented defaults" if defaults.get("matched") else
                    "hand-written-no-threshold REJECTED but the generated body does not "
                    "carry the documented defaults, so the pair does not confirm the "
                    "sealed sentence")}


def decide_f1_24(mixed_outcome: str, when_only_outcome: str,
                 guardrails_only_outcome: str, *, mutation_ran: bool) -> dict[str, Any]:
    """The sealed method NAMES the mutation: mixed policy vs two separate policies."""
    if not mutation_ran:
        return {"measurable": False, "observed": None, "inverted": None,
                "why": ("the split-policy mutation did not run (--no-mutation); without "
                        "it, 'rejected' could mean either condition was individually "
                        "invalid, so no verdict is available")}
    if when_only_outcome != ACCEPTED or guardrails_only_outcome != ACCEPTED:
        return {"measurable": False, "observed": None, "inverted": None,
                "why": (f"the split arms did not both reach a usable state (when-only "
                        f"{when_only_outcome}, guardrails-only {guardrails_only_outcome}); "
                        f"a rejection of the mixed policy is then attributable to an "
                        f"individually-invalid condition rather than to the mixing")}
    if mixed_outcome == ACCEPTED:
        return {"measurable": True, "observed": False, "inverted": False,
                "why": "the mixed policy was ACCEPTED; the sealed claim is refuted"}
    if mixed_outcome == REJECTED_GRAMMAR:
        return {"measurable": True, "observed": True, "inverted": True,
                "why": ("the mixed policy was rejected while the SAME two conditions, "
                        "split across two policies, were each accepted — the rejection is "
                        "attributable to the mixing and to nothing else")}
    return {"measurable": False, "observed": None, "inverted": None,
            "why": (f"the mixed arm's failure is {mixed_outcome}, which is not a grammar "
                    f"rejection; no verdict is available")}


def decide_f1_25(form_outcomes: dict[str, str], control_outcome: str) -> dict[str, Any]:
    """FALSE fires on ANY accepted form; TRUE needs every probed form rejected."""
    if control_outcome != ACCEPTED:
        return {"measurable": False, "observed": None,
                "why": (f"the control (the same guardrails block WITHOUT the pattern "
                        f"construct) did not reach a usable state (outcome "
                        f"{control_outcome}); a pattern arm's rejection is then "
                        f"uninformative")}
    accepted = sorted(k for k, v in form_outcomes.items() if v == ACCEPTED)
    if accepted:
        return {"measurable": True, "observed": False,
                "why": (f"pattern-matching form(s) {accepted} were ACCEPTED; the sealed "
                        f"FALSE branch fires on any accepted form")}
    not_rejected = sorted(k for k, v in form_outcomes.items() if v != REJECTED_GRAMMAR)
    if not_rejected:
        return {"measurable": False, "observed": None,
                "why": (f"form(s) {not_rejected} failed for a reason that is not a "
                        f"grammar rejection ("
                        + ", ".join(f"{k}={form_outcomes[k]}" for k in not_rejected) +
                        "); an unread failure decides nothing")}
    return {"measurable": True, "observed": True,
            "why": "every probed pattern form was rejected and the control was accepted"}


# ---------------------------------------------------------------------------
# residue and exit code
# ---------------------------------------------------------------------------

def policy_residue(created: Sequence[dict], deletions: Sequence[dict]) -> dict[str, Any]:
    """What survived, from BOTH lists — phase1.probe_residue's reasoning, per policy id.

    Deriving survivors from `deletions` alone would be circular: a policy whose delete was
    never ATTEMPTED (the loop died between the create and the finally) contributes no
    deletion row at all, so a residue computed from that list reports zero survivors for
    exactly the case where one exists.
    """
    created_ids = [c["policy_id"] for c in created if c.get("policy_id")]
    attempted = {d["policy_id"] for d in deletions}
    deleted = {d["policy_id"] for d in deletions if d.get("deleted")}
    surviving = [p for p in created_ids if p not in deleted]
    return {
        "n_created": len(created_ids),
        "n_delete_attempted": len(attempted),
        "n_deleted": len(deleted),
        "surviving": surviving,
        "never_attempted": [p for p in created_ids if p not in attempted],
        "per_policy": [{"policy_id": p,
                        "deleted": p in deleted,
                        "delete_attempted": p in attempted} for p in created_ids],
        "clean": not surviving,
        "why_two_lists": ("a policy whose delete was never ATTEMPTED contributes no row "
                          "to `deletions`, so a residue computed from that list alone "
                          "would report zero survivors for exactly the case where one "
                          "exists (phase1.probe_residue's reasoning, applied to policies)"),
    }


def exit_code(*, n_measured: int, n_expected: int, residues_clean: bool,
              baseline_ok: bool, any_unclassified: bool) -> int:
    """rc reports whether the test RAN, never whether the document was right.

    rc=2: nothing measured, a deletable survivor, or the shared baseline policy harmed.
    rc=1: an unclassified outcome, or some-but-not-all expected cases measured.
    rc=0: everything expected was measured and cleaned up.
    """
    if not residues_clean or not baseline_ok or n_measured == 0:
        return 2
    if any_unclassified or n_measured < n_expected:
        return 1
    return 0


# ---------------------------------------------------------------------------
# live plumbing
# ---------------------------------------------------------------------------

def create_arm(ac, store: EvidenceStore, state: T.State, *, engine_id: str, case_id: str,
               label: str, name: str, statement: str, predict: str,
               built_by: str, why: str) -> dict[str, Any]:
    """One sacrificial CreatePolicy, polled to terminal and classified.

    Every arm sends validationMode=IGNORE_ALL_FINDINGS (the DC-1 defence — see the module
    docstring's per-layer reasoning) and enforcementMode=LOG_ONLY (so a transiently-live
    forbid cannot change the shared ENFORCE gateway's behaviour). The policy is registered
    in state.json the moment the create returns: policies are untaggable, so the ledger is
    the only channel that finds a survivor after a kill.

    THE UNION MEMBER IS LOAD-BEARING. `definition` is a union with two arms, and the extended
    guardrails grammar exists ONLY under `definition.policy`. Sent under `definition.cedar`,
    every `when guardrails` statement in this file came back

        "When parsing the policy statement, the following errors occurred:
         * unexpected token `guardrails`"

    which reads as "guardrails-in-policy is not a supported construct" — a spectacular false
    finding against a document whose §3.1, §4.1 and §4.2 are built on it. It was this module's
    request shape, not the grammar. Under `definition.cedar` that error message is *correct*:
    `guardrails` genuinely is an unexpected token in the base Cedar grammar, so nothing about
    it was ever misleading. Every accepted `when guardrails` policy in the account (F5-4a,
    F5-4b, F6, F2, F4) went through the `policy` member; this module was the only one using
    `cedar` while sending guardrails, which is exactly why the defect was invisible to every
    other case. `infra/03_policy_engine.py`'s baseline permit still uses `cedar` correctly — it
    carries no guardrails block.

    Proven by `f1_config/diag_resource_form.py` cells 1-6 and 10 (cedar member, every resource
    form and data path: token error) against cells 9, 14 and 17 (policy member: ACTIVE), and
    already on record in F4-0's 2026-08-11 calibration matrix, which this module did not read.
    """
    lint = C.check_statement(statement)
    print(f"  arm {label:<22s} predict={predict:<8s} built_by={built_by}")
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac,
                  name=name,
                  policyEngineId=engine_id,
                  definition=C.policy_definition(statement),
                  description=f"{case_id} sacrificial arm {label} (grammar probe)"[:200],
                  validationMode=IGNORE,
                  enforcementMode=LOG_ONLY)
    out: dict[str, Any] = {
        "case_id": case_id, "label": label, "predict": predict, "built_by": built_by,
        "why_this_arm": why, "statement": statement,
        "local_lint": lint,
        "local_lint_reading": (
            "EXPECTED findings confirming the local guard would refuse this string, i.e. "
            "the bypass was necessary" if (predict == "rejected" and lint) else
            "clean, as a control must be" if not lint else
            "UNEXPECTED lint findings on a control — bypass_partition_problems should "
            "have refused this run"),
        "validation_mode": IGNORE, "enforcement_mode": LOG_ONLY,
        "policy_name": name,
        "http_ok": rec.ok, "http_status": rec.http_status,
        "request_id": rec.request_id,
        "error_code": rec.error_code, "error_message": rec.error_message,
        "policy_id": None, "terminal_status": None, "status_reasons": [],
        "timed_out": False,
    }
    if rec.ok:
        pid = rec.response.get("policyId")
        out["policy_id"] = pid
        state.record(T.Resource(
            kind="policy", logical=f"grammar_{case_id.lower().replace('-', '_')}_{label}",
            name=name, service="bedrock-agentcore-control",
            delete_op="delete_policy",
            delete_params={"policyEngineId": engine_id, "policyId": pid},
            ids={"policy_engine_id": engine_id, "policy_id": pid,
                 "case_id": case_id, "arm": label},
            arn=rec.response.get("policyArn", ""),
            delete_priority=40,
            notes=(f"{case_id} sacrificial grammar-probe policy ({label}). LOG_ONLY + "
                   f"IGNORE_ALL_FINDINGS; registered before its status was polled so a "
                   f"kill during the poll leaves a tracked resource, and policies are "
                   f"untaggable so this ledger row is the only channel that finds it")))
        try:
            live = wait_status(ac.get_policy,
                               {"policyEngineId": engine_id, "policyId": pid})
            out["terminal_status"] = live.get("status")
            out["status_reasons"] = [str(r) for r in (live.get("statusReasons") or [])]
        except TimeoutError as exc:
            out["timed_out"] = True
            out["timeout_detail"] = str(exc)
    out["classification"] = classify_create_outcome(
        http_ok=rec.ok, error_code=rec.error_code, error_message=rec.error_message,
        terminal_status=out["terminal_status"], status_reasons=out["status_reasons"],
        timed_out=out["timed_out"])
    out["outcome"] = out["classification"]["outcome"]
    print(f"        -> {out['outcome']}  (status={out['terminal_status']!r} "
          f"error={rec.error_code or 'none'})")
    return out


def delete_arm_policies(ac, store: EvidenceStore, state: T.State,
                        created: Sequence[dict]) -> list[dict[str, Any]]:
    """Delete every arm that created a policy. Every delete is attempted; none is skipped
    because an earlier one failed — stopping early would leave the rest behind for a
    reason unrelated to them."""
    out: list[dict[str, Any]] = []
    for arm in created:
        pid = arm.get("policy_id")
        if not pid:
            continue
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac,
                      policyEngineId=arm["engine_id"], policyId=pid)
        row = {"label": arm["label"], "policy_id": pid, "deleted": rec.ok,
               "error_code": rec.error_code or None, "request_id": rec.request_id}
        out.append(row)
        if rec.ok:
            state.drop("policy",
                       f"grammar_{arm['case_id'].lower().replace('-', '_')}_{arm['label']}")
            print(f"  deleted {arm['case_id']}/{arm['label']} ({pid})")
        else:
            print(f"  WARN {arm['case_id']}/{arm['label']} ({pid}) NOT deleted: "
                  f"{rec.error_code}; it is in state.json", file=sys.stderr)
    return out


def settle_generation(ac, *, engine_id: str, generation_id: str,
                      sleep=time.sleep) -> tuple[dict[str, Any], list[str]]:
    """Poll GetPolicyGeneration to its own terminal alphabet. The sequence is kept."""
    deadline = time.monotonic() + GENERATION_TIMEOUT_S
    seen: list[str] = []
    while True:
        body = ac.get_policy_generation(policyEngineId=engine_id,
                                        policyGenerationId=generation_id)
        body.pop("ResponseMetadata", None)
        st = str(body.get("status") or "")
        seen.append(st)
        if st in GENERATION_TERMINAL:
            return body, seen
        if time.monotonic() + GENERATION_SLEEP_S >= deadline:
            return body, seen
        sleep(GENERATION_SLEEP_S)


# ---------------------------------------------------------------------------
# per-case runners
# ---------------------------------------------------------------------------

def _common(run_id: str, region: str, engine_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id, "region": region, "is_smoke": False,
        "billable_calls": 0, "text_units": 0,
        "ambient_sdk": A.sdk_versions(),
        "policy_engine_id": engine_id,
        "instrument": (
            "sacrificial CreatePolicy arms against the existing baseline policy engine, "
            "each polled to a terminal status (infra/03_policy_engine.wait_status) and "
            "CLASSIFIED by error code and statusReasons text; plus, for F1-19, one "
            "StartPolicyGeneration polled to the generation's own terminal alphabet and "
            "read back through ListPolicyGenerationAssets"),
        "dc1_defence": (
            "every CreatePolicy arm sends validationMode=IGNORE_ALL_FINDINGS, because a "
            "grammar probe asks whether the BODY PARSES and an 'Overly Permissive' "
            "finding is a semantic judgement about a body that parsed (DC-1 / F1-3, and "
            "F1-11's proof that omitting the mode fails even the baseline statement). "
            "Every statement is also a forbid with an unconstrained scope, which cannot "
            "be overly permissive — two independent reasons the DC-1 class is out of "
            "reach. The residual risk is classified, not assumed away: a failure whose "
            "reasons carry the finding vocabulary is scored VALIDATION_FINDING and never "
            "as a rejection, and an unmatched failure is UNCLASSIFIED, never TRUE"),
        "enforcement_mode_choice": (
            "enforcementMode=LOG_ONLY on every arm: grammar acceptance is a property of "
            "the body and the validator, not of the mode, and a transiently-ACTIVE forbid "
            "on the shared engine would change the live ENFORCE gateway's deny behaviour "
            "for the seconds it exists"),
        "bypass_statement": (
            "arms predicted REJECTED are hand-assembled, deliberately bypassing "
            "cedar.statement()/guardrail_condition(), whose guards encode the very rules "
            "under test; every arm predicted ACCEPTED is helper-built and passed "
            "cedar.check_statement before any call was spent, and "
            "bypass_partition_problems() aborts the run if the partition is violated. The "
            "sacrificial subject carries the malformation under test itself — the lesson "
            "of f1_config/04_update_revalidation.py's 'WHY F4'S PROBE COULD NOT HAVE "
            "CAUGHT THIS': a sacrificial subject must be sacrificial IN THE PROPERTY "
            "UNDER TEST, not merely disposable"),
    }


def run_f1_19(ac, store: EvidenceStore, state: T.State, *, engine_id: str,
              gateway_arn: str, run_id: str, names: dict[str, str]) -> dict[str, Any]:
    case = "F1-19"
    scope = scope_for(gateway_arn)
    created: list[dict] = []
    deletions: list[dict] = []
    gen_summary: dict[str, Any] = {"started": False}
    try:
        a = create_arm(ac, store, state, engine_id=engine_id, case_id=case,
                       label="A_no_threshold", name=names["f119_omit"],
                       statement=no_threshold_statement(scope), predict="rejected",
                       built_by="hand",
                       why=("hand-written when guardrails block whose condition has NO "
                           "comparator and NO threshold — the exact omission the sealed "
                           "TRUE branch predicts is rejected"))
        a["engine_id"] = engine_id
        created.append(a)

        ctrl = create_arm(ac, store, state, engine_id=engine_id, case_id=case,
                          label="A_control_with_threshold", name=names["f119_ctrl"],
                          statement=threshold_control_statement(scope), predict="accepted",
                          built_by="helpers",
                          why=("the SAME statement with an explicit decimal(\"0.2\"): "
                              "without an accepted control, 'rejected' is uninformative "
                              "— the create might fail for any reason"))
        ctrl["engine_id"] = engine_id
        created.append(ctrl)

        # If the no-threshold arm was ACCEPTED, read the stored body back: the sealed
        # FALSE branch is 'hand-written policies silently receive defaults', and only the
        # stored statement can say whether a default was inserted.
        stored_readback: dict[str, Any] | None = None
        if a["outcome"] == ACCEPTED and a.get("policy_id"):
            grec = capture(store, "get_policy", ac,
                           policyEngineId=engine_id, policyId=a["policy_id"])
            if grec.ok:
                d = (grec.response or {}).get("definition") or {}
                body = (((d.get("cedar") or {}).get("statement"))
                        or ((d.get("policy") or {}).get("statement")) or "")
                stored_readback = {
                    "statement_after": body,
                    "byte_identical_to_sent": body == a["statement"],
                    "thresholds_in_stored_body": extract_guardrail_thresholds(body),
                    "silently_received_default": bool(
                        extract_guardrail_thresholds(body)),
                }

        # Arm B: natural-language authoring. StartPolicyGeneration -> poll -> assets.
        print("  arm B_nl_authoring        StartPolicyGeneration (prompt names NO number)")
        A.limiter().wait("StartPolicyGeneration")   # no documented ceiling; wait is a no-op
        srec = capture(store, "start_policy_generation", ac,
                       policyEngineId=engine_id,
                       name=names["f119_gen"],
                       resource={"arn": gateway_arn},
                       content={"rawText": NL_PROMPT})
        gen_statements: list[str] = []
        asset_findings: list[dict[str, str]] = []
        defaults = {"measurable": False, "matched": None,
                    "why": "the generation was never started"}
        gen_terminal = False
        if srec.ok:
            gen_id = srec.response.get("policyGenerationId")
            gen_summary = {"started": True, "generation_id": gen_id,
                           "request_id": srec.request_id}
            body, seen = settle_generation(ac, engine_id=engine_id,
                                           generation_id=gen_id)
            # One evidence-grade read of the settled state (poll loops are not evidence).
            capture(store, "get_policy_generation", ac,
                    policyEngineId=engine_id, policyGenerationId=gen_id)
            gen_summary.update(status_sequence=seen, status=body.get("status"),
                               status_reasons=[str(r) for r in
                                               (body.get("statusReasons") or [])],
                               findings=body.get("findings"))
            gen_terminal = body.get("status") in GENERATION_TERMINAL
            if body.get("status") == "GENERATED":
                arec = capture(store, "list_policy_generation_assets", ac,
                               policyEngineId=engine_id, policyGenerationId=gen_id)
                if arec.ok:
                    assets = (arec.response or {}).get("policyGenerationAssets") or []
                    gen_statements = generation_statements(assets)
                    asset_findings = generation_asset_findings(assets)
                    gen_summary.update(asset_findings=asset_findings,
                                       n_assets=len(assets))
            defaults = authoring_defaults_check(gen_statements)
            # When nothing was generated, the service's OWN reason (if it gave one) replaces our
            # inference from the absence. See generation_asset_findings.
            if not defaults.get("measurable") and asset_findings:
                refusals = [f for f in asset_findings if f["type"] == "INVALID"]
                if refusals:
                    defaults = {**defaults, "service_declined_to_translate": True,
                                "why": (
                                    f"the generation settled GENERATED and emitted "
                                    f"{len(gen_statements)} statement(s): the service reported "
                                    f"{len(refusals)} of {len(asset_findings)} finding(s) as "
                                    f"INVALID, e.g. {refusals[0]['description']!r} for the "
                                    f"fragment {refusals[0]['fragment']!r}. So there is no "
                                    f"generated threshold to compare against the documented "
                                    f"defaults, and the reason is the service's, not ours")}
            if body.get("status") != "GENERATED" and gen_terminal:
                defaults = {"measurable": False, "matched": None,
                            "why": (f"the generation settled "
                                    f"{body.get('status')!r}, so no body exists to read")}
        else:
            gen_summary = {"started": False, "error_code": srec.error_code,
                           "error_message": srec.error_message,
                           "request_id": srec.request_id}
        print(f"        -> generation {gen_summary.get('status', 'NOT_STARTED')!r}  "
              f"defaults: measurable={defaults.get('measurable')} "
              f"matched={defaults.get('matched')}")

        decision = decide_f1_19(a["outcome"], ctrl["outcome"],
                                generation_terminal=gen_terminal, defaults=defaults)
        payload_extra = {
            "arms": created,
            "stored_readback_of_accepted_no_threshold_arm": stored_readback,
            "nl_generation": {**gen_summary, "prompt": NL_PROMPT,
                              "prompt_names_no_number": True,
                              "generated_statements": gen_statements,
                              "defaults_check": defaults},
            "pairing": decision,
            "verdict_rule": (
                "TRUE iff BOTH halves hold: (1) the hand-written arm omitting a threshold "
                "is REJECTED_GRAMMAR while its explicit-threshold control is ACCEPTED — "
                "the control is part of the rule, not a sanity check — and (2) the "
                "generated Cedar from StartPolicyGeneration carries exactly the "
                "documented defaults from cedar.AUTHORING_DEFAULTS. FALSE iff the "
                "hand-written arm is ACCEPTED (with the stored body read back for a "
                "silently-inserted default), or the generated thresholds disagree with "
                "the documented defaults. A generation that cannot be driven to a "
                "terminal, readable state is NOT-MEASURED — a missing half is not a "
                "refutation"),
            "verdict_reading": decision["why"],
            "what_true_does_not_prove": (
                "Nor does it hold for output-path guardrails. Every arm here uses "
                "`context.input.text`, because a policy with an authorization effect that "
                "references `context.output.*` is refused outright by the service (\"Use "
                "'context.input.*' data paths\"), so the input path is the only one on "
                "which these cases could be measured at all; output-path guardrails go "
                "through the `suppressOutput` effect, which is F1-17's subject. "
                "That aside: "
                "that the defaults are 0.2/0.4/0.6 for the three functions the TITLE "
                "names — the comparison is against cedar.AUTHORING_DEFAULTS "
                "(ContentFilter 0.2, PromptAttack 0.4, SensitiveInformation 0.2) and only "
                "for the functions this one generation actually emitted; a function the "
                "generation did not produce was not compared. Nor that every NL prompt "
                "gets defaults: n=1 prompt, chosen to name no number. Nor anything about "
                "what the thresholds DO at evaluation time — that is F1-18/F3's subject"),
            "why_this_matters_operationally": (
                "a reader who hand-writes Cedar expecting the documented defaults to "
                "apply ships a policy that is rejected (or worse, silently thresholdless "
                "if FALSE); a reader must know the defaults belong to the authoring "
                "service alone. cedar.guardrail_condition's no-default-threshold design "
                "rests on this case being TRUE"),
            "expiry": ("a service-validator behaviour plus a generation-service "
                       "behaviour; either could change without an SDK bump. A change is "
                       "an AWS-BEHAVIOR-CHANGES.md entry"),
        }
        return {"case": case, "decision": decision, "created": created,
                "payload_extra": payload_extra,
                "unclassified": any(x["outcome"] == UNCLASSIFIED for x in created)}
    finally:
        deletions.extend(delete_arm_policies(ac, store, state, created))
        residue = policy_residue(created, deletions)
        # The generation itself: no DeletePolicyGeneration exists in the model (22
        # Policy* operations, none deletes a generation), so it is named residue, not
        # gated residue. It enforces nothing and dies with the engine.
        gen_residue = {
            "generation_id": gen_summary.get("generation_id"),
            "deletable": False,
            "why_not_deleted": (
                "the service model exposes no DeletePolicyGeneration; a generation is a "
                "draft artifact on the engine, enforces nothing, and is removed when "
                "99_teardown deletes the engine. Named here rather than silently "
                "omitted; deliberately NOT counted against the exit code, because rc=2 "
                "for a residue no API call can remove would train operators to ignore "
                "rc=2"),
        } if gen_summary.get("started") else None
        deletions_out = {"deletions": deletions, "residue": residue,
                         "undeletable_residue": gen_residue}
        # stash for main() via attribute on the returned dict — set in the try's return
        # path; on an exception path main() reads the store's summary instead.
        store.write_summary({"teardown": deletions_out})


def run_f1_24(ac, store: EvidenceStore, state: T.State, *, engine_id: str,
              gateway_arn: str, run_id: str, names: dict[str, str],
              mutation: bool) -> dict[str, Any]:
    case = "F1-24"
    scope = scope_for(gateway_arn)
    created: list[dict] = []
    deletions: list[dict] = []
    try:
        mixed = create_arm(ac, store, state, engine_id=engine_id, case_id=case,
                           label="mixed_both_forms", name=names["f124_mixed"],
                           statement=mixed_statement(scope), predict="rejected",
                           built_by="hand",
                           why=("one statement carrying BOTH `when { ... }` and `when "
                               "guardrails { ... }` — the combination cedar.statement() "
                               "refuses to build, hand-assembled from the same two "
                               "condition strings the split arms send"))
        mixed["engine_id"] = engine_id
        created.append(mixed)

        w_out = g_out = None
        if mutation:
            w = create_arm(ac, store, state, engine_id=engine_id, case_id=case,
                           label="split_when_only", name=names["f124_when"],
                           statement=split_when_statement(scope), predict="accepted",
                           built_by="helpers",
                           why=("the sealed mutation, half 1: the SAME standard condition "
                               "alone. Predicted accepted — without this, a rejection of "
                               "the mixed policy could mean the when-condition was "
                               "individually invalid"))
            w["engine_id"] = engine_id
            created.append(w)
            g = create_arm(ac, store, state, engine_id=engine_id, case_id=case,
                           label="split_guardrails_only", name=names["f124_guard"],
                           statement=split_guardrails_statement(scope), predict="accepted",
                           built_by="helpers",
                           why=("the sealed mutation, half 2: the SAME guardrails "
                               "condition alone. Predicted accepted — the other "
                               "individually-invalid alternative eliminated"))
            g["engine_id"] = engine_id
            created.append(g)
            w_out, g_out = w["outcome"], g["outcome"]

        decision = decide_f1_24(mixed["outcome"], w_out or "NOT_RUN",
                                g_out or "NOT_RUN", mutation_ran=mutation)
        payload_extra = {
            "arms": created,
            "mutation": {
                "ran": mutation,
                "mandatory_per_seal": O.mutation_is_mandatory(case),
                "inverted": decision.get("inverted"),
                "why_constitutive": (
                    "the sealed METHOD names it ('CreatePolicy mutation: mixed policy vs "
                    "two separate policies'), and it is constitutive of the verdict here "
                    "even though PREREGISTRATION.yaml's mutation_arms_are_mandatory list "
                    "does not include F1-24: without both split arms accepted, a "
                    "rejection of the mixed policy cannot be attributed to the mixing"),
            },
            "verdict_rule": (
                "TRUE iff the mixed policy is REJECTED_GRAMMAR while BOTH split policies "
                "— the SAME two condition strings, one per policy — are ACCEPTED. FALSE "
                "iff the mixed policy is ACCEPTED. Any other combination is not-measured: "
                "a split arm rejected means the condition itself was invalid and the "
                "mixed rejection is confounded"),
            "verdict_reading": decision["why"],
            "what_true_does_not_prove": (
                "Nor does it hold for output-path guardrails. Every arm here uses "
                "`context.input.text`, because a policy with an authorization effect that "
                "references `context.output.*` is refused outright by the service (\"Use "
                "'context.input.*' data paths\"), so the input path is the only one on "
                "which these cases could be measured at all; output-path guardrails go "
                "through the `suppressOutput` effect, which is F1-17's subject. "
                "That aside: "
                "that every mixing shape is rejected: this probes ONE standard condition "
                "beside ONE guardrails condition, when+when-guardrails. unless beside "
                "when guardrails, two guardrails blocks, or an unless guardrails mix are "
                "unprobed. Nor does it prove anything about evaluation-time semantics of "
                "either condition — both policies are LOG_ONLY and never evaluated here"),
            "why_this_matters_operationally": (
                "a reader combining a business condition with a guardrail check in one "
                "statement — the natural first draft — gets a CREATE_FAILED policy; the "
                "documented remedy (two statements) must actually work, which is what the "
                "split arms establish rather than assume"),
            "expiry": ("a grammar behaviour of the live validator, dated by this run; a "
                       "later grammar accepting the mix is an AWS-BEHAVIOR-CHANGES.md "
                       "entry"),
        }
        return {"case": case, "decision": decision, "created": created,
                "payload_extra": payload_extra,
                "unclassified": any(x["outcome"] == UNCLASSIFIED for x in created)}
    finally:
        deletions.extend(delete_arm_policies(ac, store, state, created))
        store.write_summary({"teardown": {"deletions": deletions,
                                          "residue": policy_residue(created, deletions)}})


def run_f1_25(ac, store: EvidenceStore, state: T.State, *, engine_id: str,
              gateway_arn: str, run_id: str, names: dict[str, str]) -> dict[str, Any]:
    case = "F1-25"
    scope = scope_for(gateway_arn)
    created: list[dict] = []
    deletions: list[dict] = []
    try:
        forms = pattern_statements(scope)
        form_outcomes: dict[str, str] = {}
        for i, (form, spec) in enumerate(sorted(forms.items())):
            arm = create_arm(ac, store, state, engine_id=engine_id, case_id=case,
                             label=f"pattern_{form}", name=names[f"f125_{i}"],
                             statement=spec["statement"], predict="rejected",
                             built_by="hand", why=spec["why"])
            arm["engine_id"] = engine_id
            arm["rejection_reading"] = spec["rejection_reading"]
            created.append(arm)
            form_outcomes[form] = arm["outcome"]

        ctrl = create_arm(ac, store, state, engine_id=engine_id, case_id=case,
                          label="control_no_pattern", name=names["f125_ctrl"],
                          statement=threshold_control_statement(scope), predict="accepted",
                          built_by="helpers",
                          why=("the same guardrails block WITHOUT any pattern construct; "
                              "without it accepted, a pattern arm's rejection is "
                              "uninformative"))
        ctrl["engine_id"] = engine_id
        created.append(ctrl)

        decision = decide_f1_25(form_outcomes, ctrl["outcome"])
        payload_extra = {
            "arms": created,
            "forms_probed": {k: {"why": v["why"],
                                 "rejection_reading": v["rejection_reading"],
                                 "outcome": form_outcomes[k]}
                             for k, v in forms.items()},
            "verdict_rule": (
                "TRUE iff EVERY probed pattern form is REJECTED_GRAMMAR while the "
                "pattern-free control is ACCEPTED. FALSE iff ANY probed form is ACCEPTED "
                "— the sealed FALSE branch is existential. A form failing for a "
                "non-grammar reason, or a rejected control, is not-measured"),
            "verdict_reading": decision["why"],
            "what_true_does_not_prove": (
                "Nor does it hold for output-path guardrails. Every arm here uses "
                "`context.input.text`, because a policy with an authorization effect that "
                "references `context.output.*` is refused outright by the service (\"Use "
                "'context.input.*' data paths\"), so the input path is the only one on "
                "which these cases could be measured at all; output-path guardrails go "
                "through the `suppressOutput` effect, which is F1-17's subject. "
                "That aside: "
                "that NO pattern-matching form exists: the sealed FALSE branch is 'if ANY "
                "pattern-matching form is accepted', and this run probes exactly two "
                "forms (a `like` glob on the data path; a regex-shaped category "
                "literal). Unprobed forms that could still falsify the claim include "
                "`like` inside an `unless guardrails` block, a pattern in the path list "
                "(e.g. context.output.*), a regex against the aggregation, and any "
                "future grammar extension. A TRUE here is 'the two most natural forms "
                "are rejected', not an exhaustion proof — and per-form rejection causes "
                "are recorded because the regex-shaped-category rejection is "
                "indistinguishable from an unknown-category rejection (both mean the "
                "slot does not evaluate patterns, but they are not the same sentence)"),
            "why_this_matters_operationally": (
                "a reader porting a WAF-style regex deny-list into guardrails-in-policy "
                "must know the grammar gives them categories and thresholds, not "
                "patterns; if any pattern form silently worked, deny-lists would be "
                "written in it and would break without notice when the undocumented "
                "acceptance changed"),
            "expiry": ("a grammar behaviour of the live validator, dated by this run; a "
                       "later grammar accepting a pattern form is an "
                       "AWS-BEHAVIOR-CHANGES.md entry AND a falsification of the sealed "
                       "claim from that date"),
        }
        return {"case": case, "decision": decision, "created": created,
                "payload_extra": payload_extra,
                "unclassified": any(x["outcome"] == UNCLASSIFIED for x in created)}
    finally:
        deletions.extend(delete_arm_policies(ac, store, state, created))
        store.write_summary({"teardown": {"deletions": deletions,
                                          "residue": policy_residue(created, deletions)}})


# ---------------------------------------------------------------------------
# dry run
# ---------------------------------------------------------------------------

# The scope the DRY RUN prints with. A dry run has no live gateway to name, and `scope_for`
# refuses to invent one, so the placeholder is spelled out loudly and uses the documentation
# account id from lib/redact.py's safe-literal list.
#
# It goes through `scope_for` and NOT through `Scope(...)` directly, which is not a style
# preference. The first version of this constant assembled the fields by hand and got the action
# slot wrong — `action_ref` where `action_eq` was needed — so the dry run cheerfully printed a
# head the service rejects, three lines above the words "predict: control ACCEPTED". A pre-flight
# check that builds its subject differently from the flight is not a pre-flight check. One
# construction path, self-validated inside `scope_for`, for both.
DRY_RUN_SCOPE = scope_for("arn:aws:bedrock-agentcore:us-east-1:111122223333:"
                          "gateway/DRY-RUN-PLACEHOLDER-NOT-A-REAL-GATEWAY")


def _dry_run(no_mutation: bool) -> int:
    rc = 0
    scope = DRY_RUN_SCOPE
    forms = pattern_statements(scope)
    shared = [
        "billable: False — control plane only, no model invocation, no text units",
        "every CreatePolicy arm sends validationMode=IGNORE_ALL_FINDINGS: a grammar "
        "probe asks whether the BODY PARSES, and an 'Overly Permissive' finding (DC-1) "
        "is a semantic judgement about a body that parsed, not a grammar rejection. "
        "Outcomes are classified by error code and statusReasons text, never by rc; a "
        "failure carrying the finding vocabulary is scored VALIDATION_FINDING, an "
        "unmatched one UNCLASSIFIED — neither ever counts as a rejection",
        "every CreatePolicy arm sends enforcementMode=LOG_ONLY so a transiently-live "
        "forbid on the shared baseline engine cannot change the ENFORCE gateway's "
        "behaviour",
        "arms predicted REJECTED are hand-assembled, deliberately bypassing "
        "cedar.statement()/guardrail_condition() whose guards encode the rules under "
        "test; every predicted-ACCEPTED arm is helper-built and lint-checked, and "
        "bypass_partition_problems() aborts the run on any leak of the bypass into a "
        "well-formed arm",
        "teardown deletes every created policy in a per-case finally; residue is "
        "computed from created-vs-deleted (two lists, per policy id, never one bool); "
        "the baseline policy is re-read afterwards and must still be ACTIVE",
    ]
    banners = {
        "F1-19": dict(
            arms=[("A_no_threshold", "CreatePolicy, hand-written, threshold OMITTED", 1),
                  ("A_control_with_threshold", "CreatePolicy, same statement + "
                                               "decimal(\"0.2\")", 1),
                  ("B_nl_authoring", "StartPolicyGeneration + poll + assets read", 1)],
            operations={"CreatePolicy": 2, "StartPolicyGeneration": 1},
            mutations=3,
            extra=[
                f"  A sends: {no_threshold_statement(scope)!r}".replace("\n", " / "),
                f"  control sends: {threshold_control_statement(scope)!r}".replace("\n", " / "),
                f"  B sends rawText={NL_PROMPT!r} (names NO number, so any decimal in "
                f"the generated body was supplied by the service)",
                "  predict: A REJECTED, control ACCEPTED, generated body carries "
                "cedar.AUTHORING_DEFAULTS (ContentFilter 0.2 / PromptAttack 0.4 / "
                "SensitiveInformation 0.2)",
                "  if B cannot reach a terminal, readable state: NOT-MEASURED, not "
                "FALSE — a missing half is not a refutation",
                "  the generation itself is undeletable by construction (no "
                "DeletePolicyGeneration in the model); it is named residue, enforces "
                "nothing, and dies with the engine",
            ]),
        "F1-24": dict(
            arms=([("mixed_both_forms", "CreatePolicy, when{}+when guardrails{}", 1)]
                  + ([] if no_mutation else
                     [("split_when_only", "CreatePolicy, same when{} alone", 1),
                      ("split_guardrails_only", "CreatePolicy, same guardrails alone", 1)])),
            operations={"CreatePolicy": 1 if no_mutation else 3},
            mutations=1 if no_mutation else 3,
            extra=[
                f"  mixed sends: {mixed_statement(scope)!r}".replace("\n", " / "),
                "  predict: mixed REJECTED, both splits ACCEPTED — the sealed method "
                "names the mutation, and without it 'rejected' could mean either "
                "condition was individually invalid",
            ] + (["  --no-mutation: the split arms are SKIPPED, so this case emits "
                  "not-measured — the mutation is constitutive here"] if no_mutation
                 else [])),
        "F1-25": dict(
            arms=[(f"pattern_{k}", "CreatePolicy, hand-assembled pattern form", 1)
                  for k in sorted(forms)]
                 + [("control_no_pattern", "CreatePolicy, same block w/o pattern", 1)],
            operations={"CreatePolicy": len(forms) + 1},
            mutations=len(forms) + 1,
            extra=[
                *(f"  {k} sends: {v['statement']!r}".replace("\n", " / ")
                  for k, v in sorted(forms.items())),
                "  predict: every pattern form REJECTED, control ACCEPTED. The sealed "
                "FALSE branch is existential ('if ANY form is accepted'), so two probed "
                "forms under-cover a FALSE; what_true_does_not_prove says so",
            ]),
    }
    for cid in CASES:
        b = banners[cid]
        rc |= P.dry_run_banner(cid, b["arms"], operations=b["operations"],
                               mutations=b["mutations"], billable=False,
                               extra=shared + b["extra"])
        print()
    return rc


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:                          # noqa: C901
    ap = argparse.ArgumentParser(
        description="F1-19/F1-24/F1-25 CreatePolicy grammar probes",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-mutation", action="store_true",
                    help="skip F1-24's split-policy arms. The mutation is constitutive "
                         "for that case, so it then emits not-measured; F1-19 and F1-25 "
                         "are unaffected (their controls are controls, not mutations)")
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--evidence-root", default=None,
                    help="write call records under this directory instead of evidence/. "
                         "For OFFLINE harnesses only; capture() refuses a fake client "
                         "writing into the published tree")
    args = ap.parse_args(argv)

    if args.dry_run:
        return _dry_run(args.no_mutation)

    try:
        state = T.State.load(Path(args.state) if args.state else None)
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    base = state.find("policy", "baseline")
    gw = state.find("gateway", "main")
    if base is None or gw is None or not gw.arn:
        print("FATAL: the ledger lacks policy/baseline or gateway/main (with an ARN); "
              "these probes run against the existing engine and the generation needs a "
              "resource ARN. Run Phase 2 first.", file=sys.stderr)
        return 2
    engine_id = base.ids["policy_engine_id"]
    run_id = state.run_id

    fac = A.factory(args.region)
    ac = fac.agentcore_control()
    account_id = A.account_id(fac)
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    root = Path(args.evidence_root) if args.evidence_root else None
    stores = {cid: EvidenceStore(run_id, FAMILY, cid, root=root) for cid in CASES}
    for st in stores.values():
        st.write_environment()

    print(f"F1 policy-grammar probes, run_id={run_id} (adopted from the ledger), "
          f"region={args.region}")
    print(f"  engine {engine_id}  (baseline policy is READ-ONLY here)\n")

    # ---- every name validated before the first call (03_permit_trap.plan_names) -------
    names = {
        "f119_omit": T.check_name(ac, "CreatePolicy", f"grx_f119_omit_{run_id}"),
        "f119_ctrl": T.check_name(ac, "CreatePolicy", f"grx_f119_ctrl_{run_id}"),
        # The ONE name here that must not be derived from the run id alone.
        #
        # Every other name in this dict belongs to a policy, and policies are deleted in the
        # per-case `finally`, so the name is free again on the next attempt. A policy GENERATION is
        # not: there is no DeletePolicyGeneration in the service model (the module docstring calls
        # it undeletable by construction and treats it as named residue). A deterministic name for
        # an undeletable resource makes the arm SINGLE-SHOT PER RUN ID — and this case adopts one
        # run id, so single-shot per run id means single-shot forever.
        #
        # Measured 2026-08-14, immediately after the round that finally reached the service:
        # round 5 created `grx_f119_gen_r20260810T130945Z` and settled GENERATED; round 6 got
        # `ConflictException: Generation with the same name already exists` and recorded arm B as
        # NOT_STARTED — a clean measurement in one round, then a permanent, silent-looking failure
        # in every round after it, from an arm that had just started working. Worse, the second
        # round's payload OVERWROTE the first's, so the successful read survived only in the
        # append-numbered evidence records.
        #
        # The UTC-second suffix keeps the `grx_f119_gen_<run_id>_` prefix, so residue is still
        # attributable to this run and this case by prefix, while each attempt is its own resource.
        # A timestamp rather than a random token because the attempt's TIME is the thing a reader
        # correlating undeletable residue against a log actually wants.
        "f119_gen": T.check_name(ac, "StartPolicyGeneration",
                                 f"grx_f119_gen_{run_id}_"
                                 f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}",
                                 member="name"),
        "f124_mixed": T.check_name(ac, "CreatePolicy", f"grx_f124_mixed_{run_id}"),
        "f124_when": T.check_name(ac, "CreatePolicy", f"grx_f124_when_{run_id}"),
        "f124_guard": T.check_name(ac, "CreatePolicy", f"grx_f124_guard_{run_id}"),
        "f125_0": T.check_name(ac, "CreatePolicy", f"grx_f125_p0_{run_id}"),
        "f125_1": T.check_name(ac, "CreatePolicy", f"grx_f125_p1_{run_id}"),
        "f125_ctrl": T.check_name(ac, "CreatePolicy", f"grx_f125_ctrl_{run_id}"),
    }

    # ---- the bypass partition, enforced before any call is spent ----------------------
    # Built from the SAME scope object the three runners derive from the same gateway ARN, so
    # the partition check reads the exact strings the live calls will send. A partition checked
    # against differently-scoped statements would be a check of something else.
    scope = scope_for(gateway_arn)
    print(f"  scope: {scope.action}, {scope.resource}\n")
    planned = [
        {"label": "F1-19/A_no_threshold", "statement": no_threshold_statement(scope),
         "predict": "rejected", "built_by": "hand"},
        {"label": "F1-19/A_control", "statement": threshold_control_statement(scope),
         "predict": "accepted", "built_by": "helpers"},
        {"label": "F1-24/mixed", "statement": mixed_statement(scope),
         "predict": "rejected", "built_by": "hand"},
        {"label": "F1-24/split_when", "statement": split_when_statement(scope),
         "predict": "accepted", "built_by": "helpers"},
        {"label": "F1-24/split_guardrails", "statement": split_guardrails_statement(scope),
         "predict": "accepted", "built_by": "helpers"},
        *({"label": f"F1-25/{k}", "statement": v["statement"],
           "predict": "rejected", "built_by": "hand"}
          for k, v in sorted(pattern_statements(scope).items())),
        {"label": "F1-25/control", "statement": threshold_control_statement(scope),
         "predict": "accepted", "built_by": "helpers"},
    ]
    problems = bypass_partition_problems(planned)
    if problems:
        print("FATAL: the helper-bypass partition is violated; a control the harness "
              "malformed would make every rejection uninformative:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        for cid in CASES:
            rec = O.not_measured(
                cid, f"bypass partition violated before any call was spent: {problems}",
                problems=problems)
            P.emit(cid, rec, {**_common(run_id, args.region, engine_id),
                              "partition_problems": problems}, stores[cid], quiet=True)
        return 2

    common = _common(run_id, args.region, engine_id)
    results: list[dict[str, Any]] = []
    try:
        results.append(run_f1_19(ac, stores["F1-19"], state, engine_id=engine_id,
                                 gateway_arn=gateway_arn, run_id=run_id, names=names))
        print()
        results.append(run_f1_24(ac, stores["F1-24"], state, engine_id=engine_id,
                                 gateway_arn=gateway_arn, run_id=run_id, names=names,
                                 mutation=not args.no_mutation))
        print()
        results.append(run_f1_25(ac, stores["F1-25"], state, engine_id=engine_id,
                                 gateway_arn=gateway_arn, run_id=run_id, names=names))
    finally:
        # ---- the shared testbed must be verifiably unharmed ---------------------------
        brec = capture(stores["F1-19"], "get_policy", ac,
                       policyEngineId=engine_id,
                       policyId=base.ids["policy_id"])
        baseline_status = (brec.response or {}).get("status") if brec.ok else None
        baseline_ok = baseline_status == "ACTIVE"
        print(f"\nbaseline policy after teardown: status={baseline_status!r} "
              f"({'OK' if baseline_ok else 'NOT OK'})")

    # ---- emit ------------------------------------------------------------------------
    n_measured = 0
    any_unclassified = False
    residues_clean = True
    for r in results:
        cid = r["case"]
        decision = r["decision"]
        # The per-case finally already deleted its policies and wrote a two-list residue
        # (policy_residue) into its evidence summary. The residue the EXIT CODE gates on
        # is re-derived from the ledger, which is the same two-list reasoning with the
        # ledger as the created-list: create_arm records every policy before polling and
        # delete_arm_policies drops a row only on a successful delete, so a row still
        # present IS a survivor — including one whose delete was never attempted.
        leftover = [res for (kind, logical), res in state.resources.items()
                    if kind == "policy"
                    and logical.startswith(f"grammar_{cid.lower().replace('-', '_')}")]
        residue = {
            "survivors_in_ledger": [{"logical": res.logical,
                                     "policy_id": res.ids.get("policy_id")}
                                    for res in leftover],
            "clean": not leftover,
            "basis": ("the state.json ledger: create_arm records every policy before "
                      "polling and delete_arm_policies drops it only on a successful "
                      "delete, so a row still present IS a survivor — including one "
                      "whose delete was never attempted (the two-list reasoning, with "
                      "the ledger as the created-list)"),
        }
        residues_clean = residues_clean and residue["clean"]
        any_unclassified = any_unclassified or r["unclassified"]

        payload = {**common, **r["payload_extra"], "residue": residue,
                   "mutation_mandatory_per_seal": O.mutation_is_mandatory(cid)}
        if decision["measurable"]:
            n_measured += 1
            o = P.obs_existence(
                cid, bool(decision["observed"]),
                # n=1: one deterministic control-plane validator outcome per arm, not a
                # rate. No sealed n exists for these cases (planned_n is None), so 1
                # asserts the conjunction was evaluated over this one paired run.
                n=1,
                arm_outcomes={a["label"]: a["outcome"] for a in r["created"]})
            if cid == "F1-24":
                # An Observation FIELD, set as an attribute after construction —
                # P.obs_existence's **detail raises TypeError on field-name collisions
                # by design, and a value swept into detail is a value the decision rule
                # never reads (the F5-1 lesson in phase1._detail's docstring).
                o.mutation_inverted = decision.get("inverted")
            rec = O.evaluate(o)
        else:
            rec = O.not_measured(cid, decision["why"],
                                 arm_outcomes={a["label"]: a["outcome"]
                                               for a in r["created"]})
        P.emit(cid, rec, payload, stores[cid])

    rc = exit_code(n_measured=n_measured, n_expected=len(CASES),
                   residues_clean=residues_clean, baseline_ok=baseline_ok,
                   any_unclassified=any_unclassified)
    print(f"\n{n_measured}/{len(CASES)} case(s) measured; residues "
          f"{'clean' if residues_clean else 'NOT CLEAN'}; baseline "
          f"{'ACTIVE' if baseline_ok else 'HARMED'}; rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
