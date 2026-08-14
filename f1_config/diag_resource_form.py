"""DIAGNOSTIC (not a registered case): which nuisance parameter blocks `when guardrails`?

Why this exists
---------------
On 2026-08-14, after `cedar.statement()`'s invalid `resource` default was repaired (see
`results/FINDING-P1-CEDAR-RESOURCE-SCOPE.md`), F1-19/24/25 were re-run on EC2 with a properly
constrained resource — the TYPE form, `resource is AgentCore::Gateway`. Seven of eight arms
STILL failed, with the same message as before:

    When parsing the policy statement, the following errors occurred:
    * unexpected token `guardrails`

and the eighth (F1-24's `split_when_only`, the only arm with no guardrails block) failed with
something new:

    not authorized to perform: bedrock-agentcore:ManageAdminPolicy

That second message is the clue. A statement scoped to the resource TYPE applies to every
gateway on the engine, and the service appears to treat such a statement as an ADMIN policy —
a different authorisation surface, and plausibly a different validation path. Meanwhile the
`when guardrails` policies that DID reach ACTIVE in this account (F5-4a ×6, F5-4b) carried a
fully specific head: `action == AgentCore::Action::"grxecho___echo"` and
`resource == AgentCore::Gateway::"<arn>"`.

So three parameters differ at once between the arms that work and the arms that do not:
resource form (type vs specific ARN), action scope (unconstrained vs specific), and the
guardrail context path (`context.output.text` vs `context.input.text`). One re-run cannot
attribute the failure to any of them, and guessing would mean refactoring the case module on a
hypothesis. This script varies them independently instead.

ROUND 2 — what round 1 actually found, and why the grid changed
---------------------------------------------------------------
Round 1 ran the six cells below and ALL SIX failed with `unexpected token guardrails`,
including cell 6, the positive control that reproduces F5-4a's accepted head byte for byte.
By this script's own rule that meant the difference was not in the statement text, so the
comparison moved to the REQUEST around the statement, and there it was immediately:

    f5_redteam/04_policy_failure_modes.py:274   definition={"policy":  {"statement": ...}}
    f1_config/04_policy_grammar.py              definition={"cedar":   {"statement": ...}}

`definition` is a union with two arms. Every policy in this account that ever parsed a
`when guardrails` block was sent through the `policy` arm; every arm that reported
`unexpected token guardrails` was sent through the `cedar` arm. The message is not a service
quirk and not misleading at all — in the pure-Cedar grammar, `guardrails` IS an unexpected
token. The guardrails extension lives in the `policy` grammar.

This also corrects the reading recorded in `results/FINDING-P1-CEDAR-RESOURCE-SCOPE.md` §3.
That document argued the token error was "the wildcard resource defect wearing a more alarming
mask", on the strength of an exact correlation: the eight statements that were accepted had
constrained resources, and the arms that were rejected did not. The correlation was real and
the inference was wrong, because the two groups differed in TWO variables at once — resource
form and union member — and a correlation across two groups cannot separate variables that
covary perfectly within them. Only a design that varies them independently can, which is what
the grid below now does. The resource repair was still necessary (one arm did report the
wildcard message); it was not sufficient, and it was never the cause of the other seven.

The grid therefore carries `member` as its first axis. Cells 1-6 are kept unchanged so the
round-1 observations stay comparable, and cells 7-10 add the `policy` arm:

    #   member  resource form  action          path
    7   policy  type           unconstrained   context.output.text   <- what F1 arms would send
    8   policy  ARN            unconstrained   context.output.text
    9   policy  ARN            == echo         context.input.text    <- TRUE positive control
    10  cedar   ARN            == echo         context.input.text    <- negative control (=cell 6)

Cell 9 must reach ACTIVE: it is F5-4a's accepted request in every member, including the union
arm. If it does not, nothing changed about the request and the difference is temporal, which is
a different investigation. Cell 10 pins the attribution from the other side: same statement,
same everything, `cedar` arm, expected to fail. Cells 7 and 8 then say whether the F1 module
needs only the member change or the resource form as well — `split_when_only`'s
`ManageAdminPolicy` denial suggests a type-scoped statement may be an admin policy, but that
arm was pure Cedar and the question has not been asked on the `policy` arm.

The round-1 grid (all six cells send the SAME well-formed guardrails condition, threshold explicit —
the exact string `threshold_control_statement()` uses, which is the CONTROL all three cases
depend on; if a control cannot be created, no arm of any of the three cases is interpretable):

    #  resource form                          action          path
    1  resource is AgentCore::Gateway         unconstrained   context.output.text   <- today's arms
    2  resource == AgentCore::Gateway::"arn"  unconstrained   context.output.text
    3  resource is AgentCore::Gateway         unconstrained   context.input.text
    4  resource == AgentCore::Gateway::"arn"  unconstrained   context.input.text
    5  resource == AgentCore::Gateway::"arn"  == echo action  context.output.text
    6  resource == AgentCore::Gateway::"arn"  == echo action  context.input.text   <- replicates F5-4a

Cell 6 is a POSITIVE CONTROL: it is the head F5-4a created successfully. If cell 6 does not
reach ACTIVE, the difference is not in the statement at all (something about the engine, the
role or the date changed since 2026-08-10) and no conclusion may be drawn from cells 1-5.
Cell 5 is the F5-5 cell: same head, `context.output.text`, which reached CREATE_FAILED there
because a provider's context field-path argument must be declared on every action the rule
applies to, and the echo tool's schema has no output.text.

What this script may and may not do
-----------------------------------
It writes NO verdict and touches no `results/phase1/` file. It is a mechanism probe whose only
job is to tell the repair which parameter to change, and its output belongs in the FINDING
document as an observation, not in any case's payload. Every policy is created LOG_ONLY with
IGNORE_ALL_FINDINGS (a transiently-live `forbid` must not change the shared gateway's
behaviour, and a DC-1 finding must not be scored as a grammar result), is registered in the
ledger the moment CreatePolicy returns (policies are untaggable, so the ledger is the only
channel that finds a survivor after a kill), and is deleted in a `finally`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import cedar as C        # noqa: E402
import redact as R       # noqa: E402
import testbed as T      # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_grx_diag_policy_engine", ROOT / "infra" / "03_policy_engine.py")
_pe = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_pe)
wait_status = _pe.wait_status

IGNORE = "IGNORE_ALL_FINDINGS"
LOG_ONLY = "LOG_ONLY"

# Held identical to f1_config/04_policy_grammar.py's constants on purpose: this probe is only
# informative about that module if the condition it sends is the condition that module sends.
GUARDRAIL_FN = "ContentFilter"
GUARDRAIL_CATEGORY = "HATE"
EXPLICIT_THRESHOLD = "0.2"
PLAIN_CONDITION = "context.input.amount < 500"   # == 04_policy_grammar.STD_CONDITION
# A plain condition over an attribute the echo action actually has. The comparison value can
# never occur in a real echo call, so if this policy ever went live it would match nothing —
# the same "sacrificial but inert" property F5-4a's probe statements were built for.
ECHO_PLAIN_CONDITION = 'context.input.text == "grx-value-that-is-never-equal"'

# F5-4a's target and tool, so cell 6 reproduces a head that is KNOWN to have reached ACTIVE.
ECHO_TARGET = "grxecho"
ECHO_TOOL = "echo"


def _condition(path: str) -> str:
    return C.guardrail_condition(GUARDRAIL_FN, [GUARDRAIL_CATEGORY], [path],
                                 threshold=EXPLICIT_THRESHOLD)


def cells(gateway_arn: str) -> list[dict[str, str]]:
    """The grid, each cell labelled with the four parameters it holds."""
    type_form = C.gateway_resource(None)
    arn_form = C.gateway_resource(gateway_arn)
    echo = f"action == {C.action_ref(ECHO_TARGET, ECHO_TOOL)}"
    out = []
    for label, member, resource, action, path, expect in (
        # -- round 1: the `cedar` union arm. All six failed identically. ------------------
        ("1_type_anyaction_output", "cedar", type_form, "action", "context.output.text",
         "reproduces today's F1 arms; failed round 1"),
        ("2_arn_anyaction_output", "cedar", arn_form, "action", "context.output.text",
         "isolated the RESOURCE FORM; failed round 1, so the type form was not the blocker"),
        ("3_type_anyaction_input", "cedar", type_form, "action", "context.input.text",
         "isolated the PATH under the type form; failed round 1"),
        ("4_arn_anyaction_input", "cedar", arn_form, "action", "context.input.text",
         "ARN form plus F5-4a's path, action unconstrained; failed round 1"),
        ("5_arn_echoaction_output", "cedar", arn_form, echo, "context.output.text",
         "the F5-5 cell; failed round 1 at the parser, before any action-schema check"),
        ("6_arn_echoaction_input", "cedar", arn_form, echo, "context.input.text",
         "round 1's intended positive control — failed, which is what exposed the union arm"),
        # -- round 2: the `policy` union arm, the one every accepted policy used. ---------
        ("7_policy_type_anyaction_output", "policy", type_form, "action",
         "context.output.text",
         "what the F1 module would send with only the member changed"),
        ("8_policy_arn_anyaction_output", "policy", arn_form, "action",
         "context.output.text",
         "member + ARN form, action unconstrained: does output.text survive an unconstrained "
         "action, or does F5-5's action-schema constraint bite here"),
        ("9_policy_arn_echoaction_input", "policy", arn_form, echo, "context.input.text",
         "TRUE POSITIVE CONTROL: F5-4a's accepted request in every member including the union "
         "arm. If this fails, the change is temporal and cells 7-8 say nothing"),
        ("10_cedar_arn_echoaction_input", "cedar", arn_form, echo, "context.input.text",
         "NEGATIVE CONTROL: identical to cell 9 except the union arm, so an accept in 9 and a "
         "reject here attributes the difference to the member and to nothing else"),
        # -- round 3: the exact heads the F1 module needs, one cell per open question. -----
        # Round 2 settled the member (9 ACTIVE vs 10 rejected) and turned up a second
        # constraint: cells 7 and 8 were refused with "references 'context.output' but the
        # policy has an authorization effect. Use 'context.input.*' data paths". Both were
        # refused identically, so the resource form had no observable effect BEFORE that check
        # — which means the type-vs-ARN question is still unanswered for a statement that gets
        # past it. These four cells ask it, and the two after them ask the same of the plain
        # `when` arm, whose only observation so far (ManageAdminPolicy denied) came from the
        # `cedar` member and cannot be attributed to the resource form either.
        ("11_policy_type_anyaction_input", "policy", type_form, "action",
         "context.input.text",
         "the MINIMAL change to the F1 module: member + path, resource form left as the type "
         "form the document's own §3.1 writes"),
        ("12_policy_arn_anyaction_input", "policy", arn_form, "action", "context.input.text",
         "same but resource-specific: separates 'unconstrained action is fine' from 'the type "
         "form is fine', which cells 7/8 could not"),
        ("13_policy_type_echoaction_input", "policy", type_form, echo, "context.input.text",
         "type form with a specific action: isolates the RESOURCE form with everything else "
         "held at the values cell 9 proved acceptable"),
        ("14_policy_arn_echoaction_input_replicate", "policy", arn_form, echo,
         "context.input.text",
         "cell 9 again. A positive control that is only run once is an anecdote, and every "
         "conclusion in round 3 is read against it"),
        ("15_policy_arn_anyaction_plainwhen", "policy", arn_form, "action", None,
         "F1-24's split_when arm on the policy member: a plain `when {…}` and no guardrails "
         "block at all. It must be ACCEPTED or F1-24 has no control"),
        ("16_policy_type_anyaction_plainwhen", "policy", type_form, "action", None,
         "the same plain `when {…}` on the type form. The ManageAdminPolicy denial this arm "
         "drew on 2026-08-14 was on the `cedar` member; if it recurs here it is the resource "
         "form, and if it does not it was the member"),
        # -- round 4: the last control precondition. --------------------------------------
        # Round 3 refused cell 15's plain `when { context.input.amount < 500 }` because
        # `input.amount` is not in the context of every action an unconstrained `action`
        # reaches, and refused cell 12's `context.input.text` for the same reason naming the
        # built-in action `CallTool`. So a conditional policy needs a SPECIFIC action, and the
        # attribute has to exist in THAT action's context. `context.input.text` does exist for
        # the echo action (cells 9 and 14 reached ACTIVE on it). F1-24's split_when arm is a
        # plain `when`, so it needs a plain condition over an attribute the echo action has —
        # which `context.input.amount` is not. This cell checks the replacement BEFORE the
        # module is rewritten around it, because a control that cannot be created is exactly
        # what made all three cases unmeasurable twice already.
        ("17_policy_arn_echoaction_plainwhen_text", "policy", arn_form, echo,
         f"plain:{ECHO_PLAIN_CONDITION}",
         "F1-24's split_when arm's replacement head: plain `when` over context.input.text, an "
         "attribute the echo action demonstrably has. Must be ACCEPTED or F1-24 still has no "
         "control and the mixing claim stays unmeasurable"),
    ):
        # path=None means "no guardrails block at all": a plain Cedar `when {…}`, held at the
        # F1 module's own STD_CONDITION so the cell speaks about that module's arm and not
        # about some other condition this file invented.
        if path is None:
            statement = C.statement("forbid", resource=resource, action=action,
                                    when=PLAIN_CONDITION)
        elif path.startswith("plain:"):
            statement = C.statement("forbid", resource=resource, action=action,
                                    when=path[len("plain:"):])
        else:
            statement = C.statement("forbid", resource=resource, action=action,
                                    when_guardrails=_condition(path))
        out.append({
            "label": label,
            "member": member,
            "resource": resource,
            "action": action,
            "path": path or "(none: plain when)",
            "expect": expect,
            "statement": statement,
        })
    return out


def probe(ac, state: T.State, *, engine_id: str, cell: dict[str, str],
          name: str) -> dict[str, Any]:
    """One CreatePolicy, polled to terminal, classified by nothing — the raw fate is the point.

    Deliberately NOT run through `04_policy_grammar.classify_create_outcome`: that classifier
    exists to protect a verdict, and reusing it here would let a diagnostic inherit a
    verdict-grade bucket name it has no standing to assign.
    """
    logical = f"diag_resource_form_{cell['label']}"
    print(f"  cell {cell['label']:<32s} member={cell['member']:<7s} "
          f"action={'echo' if '==' in cell['action'] else 'any':<5s} path={cell['path']}")
    A.limiter().wait("CreatePolicy")
    row: dict[str, Any] = {**cell, "policy_name": name, "policy_id": None,
                           "http_ok": None, "error_code": None, "error_message": None,
                           "terminal_status": None, "status_reasons": []}
    try:
        resp = ac.create_policy(
            name=name, policyEngineId=engine_id,
            definition={cell["member"]: {"statement": cell["statement"]}},
            description="DIAGNOSTIC resource-form probe (no verdict)"[:200],
            validationMode=IGNORE, enforcementMode=LOG_ONLY)
        row["http_ok"] = True
    except Exception as exc:                                    # noqa: BLE001
        row["http_ok"] = False
        row["error_code"] = type(exc).__name__
        resp_meta = getattr(exc, "response", None) or {}
        err = resp_meta.get("Error") or {}
        row["error_code"] = err.get("Code") or row["error_code"]
        row["error_message"] = err.get("Message") or str(exc)
        print(f"        -> {row['error_code']}: {str(row['error_message'])[:150]}")
        return row

    pid = resp.get("policyId")
    row["policy_id"] = pid
    state.record(T.Resource(
        kind="policy", logical=logical, name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid, "diagnostic": cell["label"]},
        arn=resp.get("policyArn", ""), delete_priority=40,
        notes=("diagnostic resource-form probe policy; LOG_ONLY + IGNORE_ALL_FINDINGS; "
               "registered before its status was polled because policies are untaggable "
               "and this ledger row is the only channel that finds a survivor")))
    try:
        live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
        row["terminal_status"] = live.get("status")
        row["status_reasons"] = [str(r) for r in (live.get("statusReasons") or [])]
    except TimeoutError as exc:
        row["terminal_status"] = "TIMED_OUT"
        row["status_reasons"] = [str(exc)]
    print(f"        -> {row['terminal_status']}"
          + (f": {row['status_reasons'][0][:150]}" if row["status_reasons"] else ""))
    return row


def main() -> int:
    state = T.State.load()
    base = state.find("policy", "baseline")
    gw = state.find("gateway", "main")
    if base is None or gw is None or not gw.arn:
        print("FATAL: the ledger lacks policy/baseline or gateway/main (with an ARN)",
              file=sys.stderr)
        return 2
    engine_id = base.ids["policy_engine_id"]
    run_id = state.run_id

    fac = A.factory(A.MAIN_REGION)
    ac = fac.agentcore_control()
    account_id = A.account_id(fac)
    gateway_arn = T.unmask_arn(gw.arn, account_id)

    print(f"DIAGNOSTIC resource-form probe, run_id={run_id}, engine {engine_id}")
    print("  no verdict is written; results/phase1 is not touched\n")

    grid = cells(gateway_arn)
    # The cell label is descriptive, not a name: `grx_diagrf_1_type_anyaction_output_<run_id>`
    # is 52 characters and CreatePolicy.name caps at 48 (checked offline by check_name, which
    # is why this cost no live call). The short form keeps the run_id — a name without it
    # could collide with another run's policy and attribute its fate to this probe.
    names = {c["label"]: T.check_name(ac, "CreatePolicy",
                                      f"grx_diagrf_c{c['label'].split('_')[0]}_{run_id}")
             for c in grid}

    rows: list[dict[str, Any]] = []
    try:
        for cell in grid:
            rows.append(probe(ac, state, engine_id=engine_id, cell=cell,
                              name=names[cell["label"]]))
    finally:
        print()
        for row in rows:
            pid = row.get("policy_id")
            if not pid:
                continue
            A.limiter().wait("DeletePolicy")
            try:
                ac.delete_policy(policyEngineId=engine_id, policyId=pid)
                state.drop("policy", f"diag_resource_form_{row['label']}")
                print(f"  deleted {row['label']} ({pid})")
            except Exception as exc:                            # noqa: BLE001
                print(f"  WARN {row['label']} ({pid}) NOT deleted: {exc}; it is in "
                      f"state.json", file=sys.stderr)
        survivors = [logical for (kind, logical) in state.resources
                     if kind == "policy" and logical.startswith("diag_resource_form_")]
        brec = ac.get_policy(policyEngineId=engine_id, policyId=base.ids["policy_id"])
        baseline_status = brec.get("status")
        print(f"  baseline policy after teardown: {baseline_status!r}")
        print(f"  survivors in ledger: {survivors or 'none'}")

    out = ROOT / "results" / "DIAG-P1-RESOURCE-FORM.json"
    payload = {
        "kind": "DIAGNOSTIC",
        "not_a_verdict": ("a mechanism probe for the F1-19/24/25 repair. No sealed oracle is "
                          "evaluated, no alpha is spent, and nothing here may be cited as "
                          "confirmation of any document claim."),
        "run_id": run_id, "engine_id": engine_id, "region": A.MAIN_REGION,
        "cells": rows,
        "baseline_status_after": baseline_status,
        "survivors": survivors,
    }
    # `R.mask_text`, not `.replace(account_id, …)`, which is what this line used to be. The leak
    # that made `lib/redact.py` exist was an ARN whose account field carried the live id with its
    # last digit cut off — a form no `str.replace` of the whole id can see. `A.account_id()` above
    # already registered the id with the masker, so masking here is a call rather than a second
    # implementation of one, and `lib/tests/test_results_writes_are_masked.py` can see that it is.
    out.write_text(R.mask_text(json.dumps(payload, indent=2, sort_keys=True)) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")

    if survivors or baseline_status != "ACTIVE":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
