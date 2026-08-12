#!/usr/bin/env python3
"""F2-1: are pure-Cedar policy decisions deterministic, measured on the live gateway?

    python3 f2_determinism/02_policy_determinism.py --dry-run
    python3 f2_determinism/02_policy_determinism.py --n 3          # smoke
    python3 f2_determinism/02_policy_determinism.py                # the sealed n

THE CLAIM, AND WHY IT IS THE HALF OF §3.1 THAT MATTERS
------------------------------------------------------
The document under test says guardrails are non-deterministic and Cedar policies are not
(L139, L285, L290, L753, L764). `f2_determinism/01_repeat.py` measured the first clause on
the ApplyGuardrail surface and returned FALSE — 300 byte-identical responses, which bounds
the flip rate at ~0.0099 rather than showing variation. This case measures the SECOND
clause, and it is a different instrument on a different service: a signed `tools/call`
against the gateway data plane with a policy engine in ENFORCE and one pure-Cedar policy.

Sealed oracle (`F2-1`, ZERO_EVENTS, n=300 per `determinism_cell`):

    TRUE if 0 decision flips in n=300 identical calls to a policy with no guardrail term;
    FALSE if >=1 flip (H0: p_flip=0, one counterexample suffices)

"No guardrail term" is literal here and is the reason this script exists separately from
F4's: the statement carries `when { ... }`, never `when guardrails { ... }`, so nothing in
the evaluation path calls a model. That is what makes a flip attributable to Cedar rather
than to the classifier F2-5 already bounded.

WHAT A FLIP IS, STATED BEFORE THE DATA
--------------------------------------
Within one arm every request is byte-identical and the configuration is fixed, so the
decisions ought to be one value repeated. A flip is a trial whose decision differs from its
own arm's modal decision, and `adverse` is the sum of those over all arms. Zero flips means
every arm was constant. Two properties of this definition are deliberate:

  * it is defined per ARM, not per run. Two arms that are each internally constant but
    differ from each other is the DESIGNED outcome, not a flip — that is the boundary
    working. Pooling the arms and counting distinct values would report the experiment's own
    independent variable as non-determinism.
  * the modal decision is not "the expected" decision. An arm that denied all 300 trials has
    zero flips even if it was supposed to allow them. That is why the guards below exist:
    zero flips from an arm that never did what it was configured to do is a measurement of
    an inert policy, and `ZERO_EVENTS` would read TRUE for it.

THE VACUITY TRAP THIS SCRIPT IS BUILT AROUND
--------------------------------------------
Determinism is the easiest claim in this project to confirm by accident. A policy that
matches nothing, an engine that is not enforcing, a tool name the gateway does not know
(measured 2026-08-11: a bare `echo` returns JSON-RPC -32602 and every trial is a protocol
error) — each produces a perfectly constant column of responses, and each would publish
TRUE. So the design refuses to accept constancy on its own:

  * `boundary_below` sends amount=499.9 and must be ALLOWED — the permit granted.
  * `boundary_at`    sends amount=500.0 and must be DENIED  — Cedar default-deny fired.

The two differ by 0.1 in one parameter and by nothing else: same tool, same text, same
argument names, same configuration, same session grammar. If both come out the same way, the
condition is not being evaluated and this run measured the constancy of a broken instrument.
`GUARDS` turns that into INCONCLUSIVE, never into a verdict. A third arm, `far_outside`
(amount=4242.0, n=30), is the F2-5 companion-arm pattern: it keeps a FALSE-direction reading
from resting on one value sitting exactly on the boundary.

Only trials that are an ANSWER — allowed or policy_denied — enter n. A transport fault or a
JSON-RPC protocol error is not a decision, and folding it into either count would move a
verdict on the strength of a failure (DEV-P1-11).

WHY 499.9 AND NOT 499.9999
--------------------------
Cedar's `decimal` takes up to four fractional digits, so 499.9999 would be a tighter
boundary. Whether the POLICY ENGINE binds a request literal at that precision is unmeasured:
what is measured (2026-08-11, F4) is only that an integral literal `100` is refused outright
with "one or more numeric parameters must include a decimal point". A four-digit arm could
therefore fail for a reason that has nothing to do with determinism, and the whole run's
money would buy an INCONCLUSIVE. So the scored arms sit on the one-digit lattice
`lib/cedar.decimal_literal` accepts from a float, and the precision question is asked
separately by `PRECISION_PROBE` — three unscored calls whose result is recorded in the
payload. It is a config-surface fact (F1's family), not evidence about F2-1, and it is
labelled that way rather than quietly folded in.

THE AXES ARE DRIVEN, SO THIS SCRIPT OWNS RESTORE
------------------------------------------------
The baseline permit is unconstrained, so it would allow `boundary_at` too. It is driven to
`enforcementMode=LOG_ONLY` for the duration and back to its MEASURED starting value
afterwards — never deleted, for F4's stated reason (re-creating it needs
IGNORE_ALL_FINDINGS, DC-1, and a failed re-create strands the shared testbed).

Every axis driver, terminal-state definition and blocking assertion is IMPORTED from
`f4_modes/01_truth_table.py` rather than restated. Two definitions of "the mode landed" or
"the testbed is intact" can disagree, and then which one ran decides whether a broken
testbed is reported. F4 measured those paths against this exact gateway; a second copy here
would be a second thing to keep true.

COST AND BLAST RADIUS
---------------------
Zero text units: no guardrail term anywhere, no ApplyGuardrail, no model. Billable surface
is at most 303 Lambda invocations (only the allowed arm reaches the tool) plus free
control-plane calls. The blast radius is one policy this script creates and deletes in its
own `finally` (`policy` is structurally untaggable, so that `finally` and `state.json` are
the only channels that can find it) and two mode fields on the shared gateway.

Never touched: the six pre-existing READY gateways, the three DRAFT guardrails, the two
abandoned policy engines, any `harness_*`/`uitestagent_*` resource, and the `nopolicy`
gateway (F6's paired baseline).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                              # noqa: E402
import cedar                                                        # noqa: E402
import checkpoint as C                                              # noqa: E402
import mcp as M                                                     # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402
import testbed as T                                                 # noqa: E402
from evidence import EvidenceStore, capture                          # noqa: E402

FAMILY = "f2_determinism"
CASE = "F2-1"

# F4's module, loaded by path because `01_truth_table` is not a legal identifier. The
# `sys.modules` key is a module-level CONSTANT and not a parameter: `lib/tests/
# test_module_name_collisions.py` reads every by-path loader call STATICALLY to prove no two
# register the same name, and a name built from a parameter is invisible to it (that gate is
# what failed on F4's first version). This key is distinct from the three F4 itself
# registers.
#
# Importing rather than copying is the whole point. What comes across is the set of paths F4
# measured against this same gateway: `UpdateGateway` is a REPLACE so the live configuration
# must be re-read and re-sent whole; `UpdatePolicy` must NOT resend `definition`; a mode
# change is confirmed by readback from an INDEPENDENT call; and "the testbed is intact" means
# `infra/06_verify.py`'s own two functions, not a local re-implementation. A second copy of
# any of those would be a second answer to a question whose answer decides whether a shared
# testbed is reported broken.
F4_MODULE_NAME = "grx_f4_truth_table"

_spec_f4 = importlib.util.spec_from_file_location(
    F4_MODULE_NAME, ROOT / "f4_modes" / "01_truth_table.py")
_f4 = importlib.util.module_from_spec(_spec_f4)
sys.modules[F4_MODULE_NAME] = _f4
_spec_f4.loader.exec_module(_f4)

ConfigError = _f4.ConfigError
ENGINE_ENFORCE = _f4.ENGINE_ENFORCE
POLICY_ACTIVE = _f4.POLICY_ACTIVE
POLICY_LOG_ONLY = _f4.POLICY_LOG_ONLY
PE_TERMINAL_OK = _f4.PE_TERMINAL_OK
SETTLE_DWELL_S = _f4.SETTLE_DWELL_S
TEXT_ARCHIVE_LIMIT = _f4.TEXT_ARCHIVE_LIMIT
wait_status = _f4.wait_status
_check_update_gateway_shape = _f4._check_update_gateway_shape
_engine_cfg_of = _f4._engine_cfg_of
_set_engine_mode = _f4._set_engine_mode
_set_policy_mode = _f4._set_policy_mode
_policy_mode_now = _f4._policy_mode_now
_wait_policy_terminal = _f4._wait_policy_terminal
Checks = _f4.Checks
verify_engine = _f4.verify_engine
verify_gateways = _f4.verify_gateways
DELETE_ATTEMPTS = _f4.DELETE_ATTEMPTS
DELETE_SLEEP_S = _f4.DELETE_SLEEP_S
DELETE_RETRY_SETTLE_S = _f4.DELETE_RETRY_SETTLE_S
POLICY_TERMINAL_FOR_MUTATION = _f4.POLICY_TERMINAL_FOR_MUTATION

TOOL = "echo"

# The condition's bound, and the two values that straddle it. The `.0` and `.9` are not
# cosmetic: MEASURED 2026-08-11 (F4, run r20260810T130945Z), a request whose numeric literal
# carries no decimal point is refused by the policy engine with "Parameter format error: one
# or more numeric parameters must include a decimal point (e.g., 100.0). Check parameters:
# amount", which arrives as a DENIAL and would have made the allowed arm deny for a reason
# that is not a decision.
AMOUNT_LIMIT = 500.0
AMOUNT_BELOW = 499.9
AMOUNT_AT = 500.0
AMOUNT_FAR = 4242.0

# Identical on every trial of every arm. The text is what makes "identical calls" literal:
# only `amount` differs between arms, so a difference in outcome has exactly one candidate
# cause. It is also deliberately dull — this policy carries no guardrail term, so no
# classifier reads it, and a text chosen for its content would suggest otherwise.
TEXT = "f2 policy determinism"

# Four unscored calls at four fractional digits, to answer a question that would otherwise
# sit unmeasured behind a design choice (see the module docstring). Recorded in the payload as
# a CONFIG-SURFACE observation and never counted into `adverse`: F2-1's oracle is about
# repeated identical calls, and a probe of a different request shape is not one of them.
PRECISION_PROBE_AMOUNT = 499.9999
PRECISION_PROBE_N = 4


# --------------------------------------------------------------------------
# the arms
# --------------------------------------------------------------------------
#
# One configuration for all three arms — engine ENFORCE, baseline permit LOG_ONLY, this
# script's narrow permit ACTIVE — so there is no mode switch anywhere between the first trial
# and the last. That is not an economy. Every mode switch is an event that could explain a
# flip, and F2-1's whole question is whether an unchanged configuration returns an unchanged
# answer; a script that reconfigured between arms would have to argue that the reconfiguration
# was not the cause.

PLANNED_N = 300              # sealed: O.planned_n("F2-1") == 300 (`determinism_cell`)
COMPANION_N = 30             # see ARMS["far_outside"]

ARMS: tuple[dict[str, Any], ...] = (
    {"key": "boundary_below", "amount": AMOUNT_BELOW, "expect": "allowed", "n": PLANNED_N,
     "scored": True,
     "why": ("the arm the sealed n is spent on. amount=499.9 is inside "
             "`amount.lessThan(decimal(\"500.0\"))` by one step of the lattice "
             "`lib/cedar.decimal_literal` accepts from a float, so the narrow permit is the "
             "only thing in the enforced set that can grant this request — the baseline "
             "permit is in LOG_ONLY. 300 identical calls, and every one must come back "
             "allowed or the permit is not granting and constancy would be vacuous")},
    {"key": "boundary_at", "amount": AMOUNT_AT, "expect": "denied", "n": PLANNED_N,
     "scored": True,
     "why": ("the other side of the same boundary, and equally scored. amount=500.0 is NOT "
             "less than 500.0, so nothing in the enforced set matches and Cedar default-deny "
             "decides. Determinism of a DENY is the same claim as determinism of an ALLOW and "
             "the document draws no distinction, so this arm's flips are counted into the "
             "same `adverse` rather than reported beside the verdict — a flip reported beside "
             "a verdict is a verdict (DEV-P1-11), and here it would be a refutation left out "
             "of the number that decides")},
    {"key": "far_outside", "amount": AMOUNT_FAR, "expect": "denied", "n": COMPANION_N,
     "scored": True,
     "why": ("the F2-5 companion-arm pattern at n=30: a second value on the deny side, far "
             "from the boundary, so a FALSE verdict cannot rest on one input sitting exactly "
             "where a comparator is most likely to be implemented ambiguously. Scored like "
             "the others — 30 identical calls that were not identical in outcome would "
             "falsify the claim just as surely — but it is not what the sealed n is spent on, "
             "and the record says which arms carried the 300")},
)

ARMS_BY_KEY = {a["key"]: a for a in ARMS}

# The declared configuration, spelled for every policy that will exist. `_apply_config`'s
# refusal to run a cell that omits one is F4's, and the reason carries over unchanged: the
# enforced policy set is this family's independent variable, and a policy present but
# undeclared is a variable nobody controlled.
POL_NARROW = "narrow"
MODES = {"baseline": POLICY_LOG_ONLY, POL_NARROW: POLICY_ACTIVE}

# Guards that are not about completion but about whether the run had a subject. Each names
# what would otherwise be concluded and why it would be wrong; `_guard_failures` turns any
# violation into INCONCLUSIVE.
#
# The bar for the modal-decision guards is TOTAL agreement with the arm's declared
# expectation, not a majority. That is not extra strictness for its own sake: any trial
# disagreeing with the arm's expectation is either a flip (already counted in `adverse`, so
# the verdict is FALSE and the guard is moot) or a sign the whole arm went the other way. The
# two cases cannot both be tolerated by one threshold.
GUARDS: tuple[dict[str, Any], ...] = (
    {"id": "permit_grants",
     "why": ("`boundary_below` must be ALLOWED. If it is denied, the narrow permit never "
             "matched — `context.input.amount` appears nowhere in the document under test and "
             "only in lib/cedar.py's own samples — and then all three arms default-deny, all "
             "three are constant, and F2-1 reads TRUE because nothing was ever decided. This "
             "is F4-4's CASE_GUARDS reasoning applied to a determinism claim, where it bites "
             "harder: F4-4 would at least have noticed a wrong verdict, and constancy looks "
             "the same either way")},
    {"id": "default_deny_fires",
     "why": ("`boundary_at` must be DENIED. If it is allowed, something in the enforced set "
             "is granting requests the narrow permit does not match — the likeliest candidate "
             "being a baseline permit whose drive to LOG_ONLY did not take — and the engine is "
             "then not the configuration this script declared")},
    {"id": "boundary_discriminates",
     "why": ("`boundary_below` and `boundary_at` must reach OPPOSITE modal decisions. They "
             "differ by 0.1 in one parameter and in nothing else, so opposite outcomes are the "
             "positive evidence that the condition is evaluated per request at all. Identical "
             "outcomes on both sides mean the constancy this case measures belongs to an "
             "instrument that is not asking a question")},
    {"id": "no_unclassified",
     "why": ("no trial may carry an error shape `lib/mcp.classify` does not recognise. An "
             "unrecognised shape is a gap in the INSTRUMENT: classified as a decision it "
             "could manufacture a flip, and classified as unusable it could hide one")},
)

# One checkpoint per arm. The case-id slot carries the CASE, unlike F4's family-keyed
# `F4-cells`, because no other case reads these arms — F2-2/F2-3/F2-4 need per-trial
# guardrail SCORES, which a policy with no guardrail term cannot produce by construction.
CHECKPOINT_CASE = CASE

# This script's policy is created with validation off, for F4's stated reason: F1-3 is the
# validation experiment (DC-1 — the unconstrained permit needs IGNORE_ALL_FINDINGS to create
# at all), and a policy that failed to create is not a determinism measurement. Recorded in
# the payload so it is a stated choice rather than a silent one.
VALIDATION_MODE = "IGNORE_ALL_FINDINGS"


# --------------------------------------------------------------------------
# the Cedar body
# --------------------------------------------------------------------------

def build_policy(gateway_arn: str, *, echo_action_id: str) -> dict[str, Any]:
    """The one statement this script creates: a pure-Cedar permit, no guardrail term.

    `gateway_arn` is required with no `None` branch for the reason `f1_config/03_permit_trap.py`
    documents: `cedar.gateway_resource(None)` returns `resource is AgentCore::Gateway`, which
    is the BASELINE statement, and a permissive fallback would scope this permit to every
    gateway in the account including the six pre-existing READY ones this project must not
    touch.

    Every element of the shape is MEASURED (2026-08-11, F4, run r20260810T130945Z) rather than
    chosen, and each one is a config-surface fact the document under test does not state:

      * the `action ==` scope is REQUIRED, not optional. An unscoped `action` must type-check
        against EVERY action in the schema, and the context schema is PER-ACTION and derived
        from each tool's own input schema — `CallTool`, `UnknownTool`, `Http`, `Mcp` and
        `grxecho` carry no `input` attribute at all. Without the scope the policy either fails
        validation or, under IGNORE_ALL_FINDINGS, creates and then errors on every request.
      * `context.input has amount` is required because `amount` is OPTIONAL in the schema and a
        bare access is "unable to guarantee safety of access to optional attribute".
      * `.lessThan(decimal("500.0"))`, not `< 500`: an MCP `number` parameter arrives as Cedar
        `decimal`, and decimal has no `<` operator, only the comparator methods.

    `when`, never `when guardrails` — that is the case, not a detail. `lib/cedar.statement`
    rejects a statement carrying both, and `_assert_no_guardrail_term` below re-checks the
    assembled text, because F2-1's whole claim is about a policy with no model in its
    evaluation path.
    """
    if not gateway_arn:
        raise ConfigError(
            "F2-1's policy needs the real gateway ARN. cedar.gateway_resource(None) returns "
            "`resource is AgentCore::Gateway`, which would scope this permit to EVERY gateway "
            "in the account, including the six pre-existing READY gateways this project must "
            "not touch")
    statement = cedar.statement(
        "permit", resource=cedar.gateway_resource(gateway_arn),
        action=f'action == {cedar.ENTITY_ACTION}::"{echo_action_id}"',
        when=(f"context.input has amount && context.input.amount.lessThan("
              f"{cedar.decimal_literal(AMOUNT_LIMIT)})"))
    return {
        "statement": statement,
        "why": (f"a permit that matches SOME requests and not others, conditioned on one "
                f"numeric parameter with no guardrail term anywhere in it. amount < "
                f"{AMOUNT_LIMIT} admits {AMOUNT_BELOW} and excludes {AMOUNT_AT} and "
                f"{AMOUNT_FAR}, which is the entire independent variable of this case: three "
                f"arms differing in one number and in nothing else"),
    }


def _assert_no_guardrail_term(statement: str) -> None:
    """Refuse to run if the statement mentions a guardrail at all.

    F2-1's sealed text says "a policy with no guardrail term", and that phrase is the
    difference between this case and F2-2/F2-3. `cedar.statement` already refuses to MIX
    `when` with `when guardrails`, but it would happily assemble a guardrail-only statement,
    and a future edit that moved this policy onto the guardrail path would still create,
    still run, and still publish a verdict under F2-1's oracle text — the verdict would just
    be about something else. Checking the assembled text is the cheapest way to make that
    edit fail loudly.
    """
    lowered = statement.lower()
    bad = [tok for tok in ("guardrail", "bedrockguardrails", "contentfilter",
                           "piientity", "topic", "wordfilter") if tok in lowered]
    if bad:
        raise ConfigError(
            f"F2-1's statement mentions {bad}, so it is not the pure-Cedar policy the sealed "
            f"oracle names ('a policy with no guardrail term'). A guardrail term puts a model "
            f"in the evaluation path, which is the surface F2-5 measured and F2-2/F2-3 are "
            f"registered for — a verdict from this script would carry F2-1's oracle text over "
            f"a different experiment")


# --------------------------------------------------------------------------
# one configuration
# --------------------------------------------------------------------------

def _apply_config(ac, store: EvidenceStore, *, gateway_id: str, engine_arn: str,
                  engine_id: str, baseline_policy_id: str, narrow_policy_id: str,
                  sleep=time.sleep) -> dict[str, Any]:
    """Put the testbed into the one configuration all three arms share.

    Applied ONCE, before the first trial, and not touched again until restore. Every readback
    is from an independent call (F4's `_set_engine_mode`/`_set_policy_mode` do that), so
    "the mode landed" is a control-plane fact rather than an inference from an HTTP 200.
    """
    engine = _set_engine_mode(ac, store, gateway_id=gateway_id, engine_arn=engine_arn,
                              mode=ENGINE_ENFORCE)
    ids = {"baseline": baseline_policy_id, POL_NARROW: narrow_policy_id}
    policies = [
        _set_policy_mode(ac, store, engine_id=engine_id, policy_id=ids[logical],
                         logical=logical, mode=mode, sleep=sleep)
        for logical, mode in sorted(MODES.items())]

    # A FIXED dwell, never a poll on the data plane. F4's reasoning applies verbatim and
    # applies more sharply here: a loop that waited until the gateway agreed with the
    # document could not observe a refutation, and this case's refutation is a single
    # disagreeing trial. `trial_index` is on every row, so propagation lag longer than the
    # dwell shows up as flips clustered at the start of an arm rather than as a bare FALSE.
    print(f"    settling {SETTLE_DWELL_S:.0f}s (fixed; never conditioned on a data-plane "
          f"outcome)")
    sleep(SETTLE_DWELL_S)
    return {"engine": engine, "policies": policies, "dwell_s": SETTLE_DWELL_S,
            "modes_declared": dict(MODES),
            "why_one_configuration": (
                "all three arms run under this single configuration and no mode is switched "
                "between the first trial and the last. F2-1 asks whether an unchanged "
                "configuration returns an unchanged answer, so a reconfiguration mid-run "
                "would be an event that could explain a flip")}


# --------------------------------------------------------------------------
# policy lifecycle
# --------------------------------------------------------------------------

def _create_policy(ac, store: EvidenceStore, state: T.State, *, engine_id: str, name: str,
                   spec: dict[str, Any], registry: dict[str, str]) -> str:
    """Create the narrow permit in LOG_ONLY, poll it to ACTIVE, return its id.

    `registry` is written BEFORE the ledger write and before any poll that can raise. F4
    measured what the alternative costs: `registry[key] = _create_policy(...)` loses the id
    whenever the settle check raises, teardown then iterates an empty registry, and the policy
    survives the run while all 15 blocking checks report PASS — they assert the testbed is
    INTACT, and an extra failed policy violates none of them.

    Created LOG_ONLY and driven ACTIVE by `_apply_config`, so creation cannot change what the
    gateway does before this script says so.
    """
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac,
                  name=name, policyEngineId=engine_id,
                  # `policy`, NOT `cedar`: F4-0 measured that `definition` carries both
                  # members and they are DIFFERENT PARSERS. This statement is plain Cedar and
                  # would parse either way; `policy` is used so that the request shape matches
                  # the one every other measured fact in this project was established under.
                  definition={"policy": {"statement": spec["statement"]}},
                  description="F2-1 pure-Cedar determinism: narrow numeric permit",
                  validationMode=VALIDATION_MODE,
                  enforcementMode=POLICY_LOG_ONLY)
    if not rec.ok:
        raise ConfigError(f"CreatePolicy failed: {rec.error_code}: {rec.error_message}")
    pid = rec.response.get("policyId")
    if not pid:
        raise ConfigError("CreatePolicy returned no policyId")

    registry[POL_NARROW] = pid

    state.record(T.Resource(
        kind="policy", logical=f"f2_{POL_NARROW}", name=name,
        service="bedrock-agentcore-control",
        delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid,
             "enforcement_mode_at_create": POLICY_LOG_ONLY,
             "validation_mode_sent": VALIDATION_MODE,
             "statement": spec["statement"]},
        arn=rec.response.get("policyArn", ""),
        delete_priority=40,
        notes=("F2-1 narrow permit. Registered before its status was polled because "
               "`policy` takes no tags, so this ledger entry and this script's finally are "
               "the only channels that can ever find it")))

    try:
        live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
    except TimeoutError as exc:
        raise ConfigError(f"the narrow policy never reached a terminal status: {exc}") from exc
    if live.get("status") not in PE_TERMINAL_OK:
        raise ConfigError(
            f"the narrow policy settled {live.get('status')} rather than ACTIVE "
            f"(reasons={live.get('statusReasons')}). An inert policy is not the enforced set "
            f"this run declares, and every arm would then default-deny — which is constant, "
            f"and constancy is what this case counts")
    print(f"    created policy {POL_NARROW} -> {pid} (ACTIVE, {POLICY_LOG_ONLY})")
    return pid


def _delete_policy(ac, store: EvidenceStore, state: T.State, *, engine_id: str,
                   policy_id: str, sleep=time.sleep) -> bool:
    """Delete the narrow permit. Never raises — this runs from teardown paths.

    Waits for a terminal status, then retries: `DeletePolicy` against a policy still in
    `UPDATING` answers `ConflictException`, and F4 measured that a single unretried attempt
    leaves a policy on the shared engine while every blocking check reports green.
    """
    waits = _wait_policy_terminal(ac, engine_id=engine_id, policy_id=policy_id, sleep=sleep)
    last = waits[-1] if waits else ""
    if last == "GONE":
        state.drop("policy", f"f2_{POL_NARROW}")
        print(f"    policy already gone (status polls: {'->'.join(waits)})")
        return True
    if last not in POLICY_TERMINAL_FOR_MUTATION:
        print(f"    WARN policy never settled (status polls: {'->'.join(waits)}); attempting "
              f"the delete anyway", file=sys.stderr)

    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac, policyEngineId=engine_id, policyId=policy_id)
        if rec.ok:
            state.drop("policy", f"f2_{POL_NARROW}")
            print(f"    deleted policy" + (f" (attempt {attempt})" if attempt > 1 else ""))
            return True
        errors.append(f"attempt {attempt}: {rec.error_code}")
        if rec.error_code == "ResourceNotFoundException":
            state.drop("policy", f"f2_{POL_NARROW}")
            print(f"    policy was already deleted (attempt {attempt})")
            return True
        if attempt < DELETE_ATTEMPTS:
            _wait_policy_terminal(ac, engine_id=engine_id, policy_id=policy_id,
                                  timeout_s=DELETE_RETRY_SETTLE_S, sleep=sleep)
            sleep(DELETE_SLEEP_S)

    print(f"    WARN policy not deleted after {DELETE_ATTEMPTS} attempts "
          f"({'; '.join(errors)}). It is in state.json, which is the ONLY channel that can "
          f"find it — `policy` takes no tags, so the tag sweep cannot.", file=sys.stderr)
    return False


# --------------------------------------------------------------------------
# trials
# --------------------------------------------------------------------------

def args_for(arm: dict[str, Any]) -> dict[str, Any]:
    """The request body for one arm. Byte-identical on every trial of that arm."""
    return {"text": TEXT, "amount": float(arm["amount"])}


def _one_call(client, arm: dict[str, Any], *, trial_id: str, trial_index: int,
              tool_name: str) -> dict[str, Any]:
    """One `tools/call`, recorded as a DECISION rather than as a pass/fail.

    `tool_name` is the FULL MCP name (`<targetName>___<toolName>`, e.g. `grxecho___echo`),
    resolved from the ledger and required with no default. MEASURED 2026-08-11: the bare short
    name returns HTTP 200 with JSON-RPC -32602 "Unknown tool: echo" — not a transport error and
    not a denial — and an entire F4 run completed that way with `n_usable = 0`. For a
    determinism case the same mistake is worse than useless: 300 identical protocol errors are
    perfectly constant, so a script that scored them would publish TRUE.

    `decision` is the field the analysis counts, and it is `Decision.outcome` unmodified. No
    per-arm expectation is folded into it: `hit`, which `arms.tally` would read, is left False
    on every row precisely so that nothing downstream can mistake "disagreed with the arm's
    prediction" for "flipped". The flip is computed later, against the arm's own modal value.
    """
    A.limiter().wait("InvokeGateway")
    d = client.call_tool(tool_name, args_for(arm))
    text_len = len(d.text or "")
    return {
        "trial_id": trial_id, "hit": False,
        **d.to_json(),
        "trial_index": trial_index,
        "arm": arm["key"], "expect": arm["expect"], "amount": float(arm["amount"]),
        "decision": d.outcome,
        "text_len": text_len,
        "text_archived_complete": text_len <= TEXT_ARCHIVE_LIMIT,
    }


def _run_arm(fc, store: EvidenceStore, *, arm: dict[str, Any], gateway_url: str, run_id: str,
             region: str, n: int, session_timeout_s: int, cp_root: Path | None,
             is_smoke: bool, tool_name: str) -> C.Checkpoint:
    """Send one arm's trials and return its checkpoint.

    A fresh MCP session per arm, with the arm key in the policy session id, so no session is
    shared across two request shapes. Within the arm the session is reused across all trials —
    that IS the "identical calls" condition, and `trial_index` on every row is what makes a
    session-state effect visible as flips clustered in one part of the arm.
    """
    cp = C.Checkpoint(case_id=CHECKPOINT_CASE, cell=arm["key"],
                      root=cp_root or Path("results") / "checkpoints")
    cp.load()
    cp.set_meta(
        source="gateway_tools_call",
        qualifiers=(f"engine={ENGINE_ENFORCE};"
                    + ";".join(f"{k}={v}" for k, v in sorted(MODES.items()))
                    + f";amount={arm['amount']}"),
        output_scope="tool_result",
        # No guardrail is involved at all, and that is the case rather than an omission. The
        # value says so explicitly instead of leaving the field empty, because an empty field
        # reads as "not recorded".
        guardrail_version="none:pure-cedar-no-guardrail-term",
        region=region,
        corpus=f"synthetic:echo(text,amount={arm['amount']})",
        is_smoke=is_smoke,
        operation="InvokeGateway")

    try:
        client = M.client_for(gateway_url, fc, store=store,
                              policy_session_id=M.policy_session_id(run_id, arm["key"]),
                              session_timeout_s=session_timeout_s)
    except M.McpTransportError as exc:
        raise ConfigError(f"arm {arm['key']}: the MCP client could not be constructed, so no "
                          f"trial in this arm measured anything: {exc}") from exc
    try:
        try:
            client.initialize()
        except M.McpTransportError as exc:
            raise ConfigError(f"arm {arm['key']}: MCP initialize failed, so no trial in this "
                              f"arm measured anything. This is a transport fault, NOT a "
                              f"denial — a denial is HTTP 200 with a JSON-RPC -32002 (F4-6): "
                              f"{exc}") from exc
        for i in range(1, n + 1):
            tid = f"t{i:04d}"
            if cp.is_done(tid):
                continue
            client.refresh_if_stale()
            cp.run_trial(tid, lambda t=tid, k=i: _one_call(
                client, arm, trial_id=t, trial_index=k, tool_name=tool_name))
            cp.save()
            if i % 50 == 0 or i == n:
                print(f"      {i}/{n} done={cp.n_done} failed={cp.n_failed}")
    finally:
        client.close()
        cp.save()
    return cp


def _precision_probe(fc, store: EvidenceStore, *, gateway_url: str, run_id: str,
                     session_timeout_s: int, tool_name: str) -> dict[str, Any]:
    """Four unscored calls at four fractional digits. Never raises, never counted.

    This exists so that a design choice does not silently become an unmeasured claim. The
    scored arms sit on the one-fractional-digit lattice because whether the policy engine
    binds a request literal at Cedar's full four-digit precision is UNKNOWN — what was measured
    (F4, 2026-08-11) is only that an integral literal is refused. Rather than assert either way
    in a comment, this asks.

    Its result is reported as a CONFIG-SURFACE observation for F1's family and is excluded from
    `adverse` and from n. F2-1's oracle counts repeated identical calls, and four calls of a
    different request shape are not among them; folding them in would make a config-surface
    fact into evidence about determinism.
    """
    out: dict[str, Any] = {
        "amount": PRECISION_PROBE_AMOUNT, "n": PRECISION_PROBE_N,
        "predicted": ("allowed, if the engine binds four fractional digits: 499.9999 is "
                      "strictly less than 500.0"),
        "why_unscored": ("a different request shape from the scored arms, so it is not one of "
                         "the 'identical calls' F2-1's oracle counts. It answers a "
                         "config-surface question (F1's family) that would otherwise sit "
                         "behind an unexamined choice in this script"),
        "outcomes": [], "distinct_outcomes": [], "error": None,
    }
    try:
        client = M.client_for(gateway_url, fc, store=store,
                              policy_session_id=M.policy_session_id(run_id, "precisionprobe"),
                              session_timeout_s=session_timeout_s)
    except M.McpTransportError as exc:                                    # noqa: BLE001
        out["error"] = f"client: {type(exc).__name__}: {exc}"
        return out
    try:
        client.initialize()
        for _ in range(PRECISION_PROBE_N):
            A.limiter().wait("InvokeGateway")
            d = client.call_tool(tool_name, {"text": TEXT, "amount": PRECISION_PROBE_AMOUNT})
            out["outcomes"].append({"outcome": d.outcome, "http_status": d.http_status,
                                    "text": (d.text or "")[:400],
                                    "request_id": d.request_id})
    except Exception as exc:                                              # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            client.close()
        except Exception:                                                 # noqa: BLE001
            pass
    out["distinct_outcomes"] = sorted({o["outcome"] for o in out["outcomes"]})
    out["reading"] = (
        "four-digit request literals bind and the permit matched"
        if out["distinct_outcomes"] == ["allowed"] else
        f"four-digit request literals did NOT simply match: {out['distinct_outcomes']}"
        f"{' / ' + str(out['error']) if out['error'] else ''}. This is why the scored arms use "
        f"one fractional digit; had they used four, the allowed arm could have failed for a "
        f"reason that is not a decision")
    return out


# --------------------------------------------------------------------------
# tally, guards, verdict
# --------------------------------------------------------------------------

USABLE_OUTCOMES = ("allowed", "policy_denied")


def _tally(arm_key: str, cp: C.Checkpoint, planned_n: int) -> dict[str, Any]:
    """One arm's counts, in the shape `require_measured` reads, plus the flip count.

    `arms.tally` is not reused: it wants an `ArmSpec`, which is an ApplyGuardrail corpus arm,
    and it computes `n_usable` as "every row recorded". Here a row is usable only if it is a
    DECISION — `allowed` or `policy_denied`. A transport fault or a JSON-RPC protocol error is
    not an answer to "what did the policy decide", and 300 identical protocol errors are
    perfectly constant, so counting them would let a broken instrument publish TRUE.

    `flips = n_usable - modal_count`. Reported per arm; summed across arms by
    `_evaluate`, since a flip anywhere is a flip in identical calls to a pure-Cedar policy.
    """
    rows = list(cp.results().values())
    usable = [r for r in rows if r.get("decision") in USABLE_OUTCOMES]
    counts = Counter(r["decision"] for r in usable)
    modal, modal_n = (counts.most_common(1)[0] if counts else ("", 0))
    fails = cp.failures()
    disagree = sum(1 for r in usable
                   if (r["decision"] == "allowed") != (ARMS_BY_KEY[arm_key]["expect"] == "allowed"))
    return {
        "case_id": CASE, "arm": arm_key, "cell": arm_key, "corpus": arm_key,
        "planned_n": planned_n, "n_attempted": planned_n,
        "n_usable": len(usable),
        # `x` is what `_counts` (and therefore `require_measured`'s reporting) reads. The flip
        # count is the adverse quantity of this case, so it goes here — the completion gate
        # never reads `x` for a decision, but a reader triaging a refusal sees the right number.
        "x": len(usable) - modal_n,
        "flips": len(usable) - modal_n,
        "modal_decision": modal,
        "modal_n": modal_n,
        "decision_counts": dict(counts),
        "expect": ARMS_BY_KEY[arm_key]["expect"],
        "modal_matches_expect": (
            (modal == "allowed") == (ARMS_BY_KEY[arm_key]["expect"] == "allowed")
            if modal else False),
        "n_disagreeing_with_expect": disagree,
        "n_failed": len(fails),
        "failure_codes": sorted({v.get("error_code", "") for v in fails.values()}),
        "n_recorded": len(rows),
        "n_unclassified": sum(1 for r in rows if r.get("unclassified")),
        "n_not_a_decision": len(rows) - len(usable),
        "not_a_decision_outcomes": sorted({r.get("outcome", "") for r in rows
                                           if r.get("decision") not in USABLE_OUTCOMES}),
        "flip_examples": [{k: r.get(k) for k in ("trial_id", "trial_index", "outcome",
                                                 "http_status", "request_id")}
                          for r in usable if r["decision"] != modal][:10],
        "checkpoint": str(cp.path),
    }


def _guard_failures(tallies: dict[str, dict]) -> list[dict]:
    """`GUARDS` violations. Each entry says what would have been concluded and why it is wrong."""
    out: list[dict] = []
    by_id = {g["id"]: g for g in GUARDS}

    for key in ("boundary_below", "boundary_at"):
        t = tallies.get(key)
        gid = "permit_grants" if key == "boundary_below" else "default_deny_fires"
        if t is None:
            out.append({**by_id[gid], "arm": key,
                        "detail": "the arm produced no tally at all"})
        elif t["n_usable"] == 0:
            out.append({**by_id[gid], "arm": key,
                        "detail": "the arm produced no usable decision"})
        elif not t["modal_matches_expect"] or t["n_disagreeing_with_expect"]:
            out.append({**by_id[gid], "arm": key,
                        "detail": (f"modal decision {t['modal_decision']!r} against an "
                                   f"expected {t['expect']!r}; "
                                   f"{t['n_disagreeing_with_expect']} of {t['n_usable']} "
                                   f"usable trials disagreed with the arm's expectation")})

    lo, at = tallies.get("boundary_below"), tallies.get("boundary_at")
    if lo and at and lo["modal_decision"] and lo["modal_decision"] == at["modal_decision"]:
        out.append({**by_id["boundary_discriminates"],
                    "arm": "boundary_below|boundary_at",
                    "detail": (f"both sides of the boundary reached the same modal decision "
                               f"{lo['modal_decision']!r} despite differing by "
                               f"{AMOUNT_AT - AMOUNT_BELOW:g} in `amount` and in nothing else")})

    noisy = {k: t["n_unclassified"] for k, t in tallies.items() if t["n_unclassified"]}
    if noisy:
        out.append({**by_id["no_unclassified"], "arm": ",".join(sorted(noisy)),
                    "detail": f"unclassified trials per arm: {noisy}"})
    return out


def _arm_summary(t: dict) -> dict:
    return {k: t[k] for k in
            ("arm", "expect", "planned_n", "n_attempted", "n_usable", "flips",
             "modal_decision", "modal_n", "decision_counts", "modal_matches_expect",
             "n_disagreeing_with_expect", "n_failed", "failure_codes", "n_recorded",
             "n_unclassified", "n_not_a_decision", "not_a_decision_outcomes", "checkpoint")}


def _evaluate(tallies: dict[str, dict], *, common: dict[str, Any], store: EvidenceStore,
              is_smoke: bool) -> int:
    """Score the case, emit its record, return its exit code.

    The gate order is the order of the questions, and each gate that fires produces
    INCONCLUSIVE rather than a verdict, because every one of them is a statement about the
    instrument and none is evidence about the document.
    """
    summaries = [_arm_summary(t) for t in tallies.values()]
    payload: dict[str, Any] = {
        **common,
        "arms": {a["key"]: {"amount": a["amount"], "expect": a["expect"], "n": a["n"],
                            "scored": a["scored"], "why": a["why"]} for a in ARMS},
        "arm_summaries": summaries,
        "guards": [dict(g) for g in GUARDS],
        "flip_definition": (
            "a flip is a usable trial whose decision differs from its own arm's MODAL "
            "decision, and `adverse` is the sum over arms. Per-arm and not per-run: the two "
            "boundary arms are DESIGNED to differ from each other, so pooling them and "
            "counting distinct values would report this experiment's independent variable as "
            "non-determinism. The modal decision is not the expected decision — an arm that "
            "denied every trial has zero flips even if it was configured to allow them, which "
            "is exactly what the guards exist to catch"),
        "usable_definition": (
            "a trial is usable only if its outcome is a DECISION (allowed or policy_denied). "
            "A transport fault or a JSON-RPC protocol error is not an answer to 'what did the "
            "policy decide', and 300 identical protocol errors are perfectly constant — "
            "scoring them would let a broken instrument publish TRUE (measured 2026-08-11: a "
            "bare tool name yields -32602 on every call)"),
    }

    missing = [a["key"] for a in ARMS if a["key"] not in tallies]
    if missing:
        rec = O.not_measured(
            CASE, f"arms this case depends on did not run: {missing}. The guards that "
                  f"establish the run had a subject are defined over both boundary arms, so a "
                  f"verdict from the remainder would be a verdict from a different design",
            missing_arms=missing, arms_required=[a["key"] for a in ARMS])
        P.emit(CASE, rec, payload, store)
        return 2

    gate = P.require_measured(list(tallies.values()), is_smoke=is_smoke)
    if gate != 0:
        rec = O.not_measured(
            CASE,
            "the per-arm completion gate was not met, so the pre-registered precision was not "
            "reached. A shortfall reported beside a verdict IS a verdict (DEV-P1-11), so no "
            "verdict is published here",
            arm_summaries=summaries)
        P.emit(CASE, rec, payload, store)
        return 2

    guard_fails = _guard_failures(tallies)
    if guard_fails:
        rec = O.not_measured(
            CASE,
            "a subject guard failed: the arms ran to completion but this run has no live "
            "decision to ask the question of. Constancy is the outcome this case counts, and "
            "an inert policy, a non-enforcing engine and a deterministic service all produce "
            "it — see `guard_failures`, where each entry names what would otherwise have been "
            "concluded",
            guard_failures=guard_fails)
        P.emit(CASE, rec, {**payload, "guard_failures": guard_fails}, store)
        return 2

    scored = [t for t in tallies.values() if ARMS_BY_KEY[t["arm"]]["scored"]]
    adverse = sum(t["flips"] for t in scored)
    n = sum(t["n_usable"] for t in scored)

    obs = P.obs_zero_events(
        CASE, adverse=adverse, n=n,
        arm_summaries=summaries,
        n_denominator=(
            "the union of every scored arm's usable trials. `obs_zero_events` takes n "
            "explicitly for exactly this shape (F3-6's precedent: adverse events drawn from "
            "more than one population are denominated in their union), and the sealed n=300 "
            "is met by each of the two boundary arms on its own"),
        flips_by_arm={t["arm"]: t["flips"] for t in scored},
        flip_examples={t["arm"]: t["flip_examples"] for t in scored if t["flip_examples"]})
    rec = O.evaluate(obs)

    blockers: list[str] = []
    for t in scored:
        if t["n_usable"] < t["planned_n"] and t["planned_n"] >= PLANNED_N:
            blockers.append(
                f"arm {t['arm']} contributed {t['n_usable']} usable trials against a "
                f"pre-registered {t['planned_n']}. It cleared the completion gate, so the "
                f"verdict stands, but any ceiling quoted from this record must be computed at "
                f"the achieved n and not at the planned one")
    if blockers:
        print("\nAMENDMENT BLOCKERS (the verdict stands; the remedy does not):", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)

    P.emit(CASE, rec, {
        **payload,
        "adverse": adverse,
        "n_usable": n,
        "false_means_what": (
            "FALSE means at least one trial in a scored arm decided differently from the rest "
            "of its own arm under a byte-identical request and an unchanged configuration — a "
            "single counterexample, which is why the seal puts this case in the "
            "`single_counterexample` family with no multiplicity correction"),
        "true_means_what": (
            f"TRUE means zero flips in {n} usable decisions, which bounds the per-call flip "
            f"rate by the Clopper-Pearson ceiling in the record rather than establishing "
            f"determinism. It bounds only OBSERVABLE flips: the instrument sees the decision, "
            f"not the evaluation, so a policy engine that reached the same answer by a "
            f"different path on some trial is invisible to it"),
        "relation_to_f2_5": (
            "F2-5 measured the other clause of the same sentence on a different service: 300 "
            "identical ApplyGuardrail calls, verdict FALSE, flip rate bounded at ~0.0099. The "
            "two together are the document's contrast — non-deterministic guardrails, "
            "deterministic policies — measured on the two surfaces separately. Neither "
            "licenses the other: F2-5's guardrail returns a 4-value enum, and this case's "
            "policy has no guardrail term at all"),
        "not_measured_here": (
            "whether the policy decision is a deterministic FUNCTION of a non-deterministic "
            "guardrail score. That is F2-2/F2-3/F2-4, and it needs per-trial score "
            "observability, which a policy with no guardrail term cannot produce by "
            "construction"),
        "local_amendment_blockers": blockers,
        "replication_required": (
            "the conflict-resolution protocol requires reproduction on >=2 separate UTC days "
            "before the document is amended. One run of this script is one day"),
        "expiry": (
            "a service behaviour, not a model read. AWS could change Cedar evaluation at any "
            "time; if it does, that is an AWS-BEHAVIOR-CHANGES.md entry rather than a "
            "correction to this record"),
    }, store)
    return 0


# --------------------------------------------------------------------------
# dry run
# --------------------------------------------------------------------------

def _dry_run(n_by_arm: dict[str, int]) -> int:
    total = sum(n_by_arm.values())
    return P.dry_run_banner(
        CASE,
        [(a["key"], f"echo(amount={a['amount']}) / expect {a['expect']}", n_by_arm[a["key"]])
         for a in ARMS],
        operations={"InvokeGateway": total},
        # 1 engine-mode set + 1 per declared policy, then create + delete of the narrow permit.
        mutations=1 + len(MODES) + 2,
        billable=False,
        extra=[
            f"one configuration for all {len(ARMS)} arms — engine={ENGINE_ENFORCE}, "
            + ", ".join(f"{k}={v}" for k, v in sorted(MODES.items()))
            + " — applied once and not switched again until restore. F2-1 asks whether an "
              "unchanged configuration returns an unchanged answer, so a reconfiguration "
              "mid-run would be an event that could explain a flip",
            f"the arms differ in ONE number: amount={AMOUNT_BELOW} (inside the permit's "
            f"condition), {AMOUNT_AT} (the boundary itself, not less than it) and {AMOUNT_FAR} "
            f"(far outside). Same tool, same text, same argument names, same configuration",
            "the policy carries `when { ... }` and NEVER `when guardrails { ... }`; "
            "`_assert_no_guardrail_term` refuses to run otherwise, because 'a policy with no "
            "guardrail term' is the sealed oracle's own wording and is what separates this "
            "case from F2-2/F2-3",
            "a flip is a usable trial whose decision differs from its own arm's MODAL "
            "decision. Per-arm, because the two boundary arms are DESIGNED to differ from each "
            "other; and modal rather than expected, because an arm that denied everything is "
            "constant too — which is what the four guards exist to catch",
            "GUARDS: boundary_below must be ALLOWED (the permit granted), boundary_at must be "
            "DENIED (default-deny fired), the two must reach OPPOSITE decisions (the condition "
            "is evaluated per request), and no trial may be unclassified. Any violation is "
            "INCONCLUSIVE, never a verdict — an inert policy produces perfect constancy and "
            "would otherwise publish TRUE",
            f"a FIXED {SETTLE_DWELL_S:.0f}s dwell after the configuration lands, never a poll "
            f"on the data plane: a loop that waited until the gateway agreed with the document "
            f"could not observe a refutation, and this case's refutation is one trial",
            f"{PRECISION_PROBE_N} extra calls at amount={PRECISION_PROBE_AMOUNT} are sent as an "
            f"UNSCORED config-surface probe: whether the engine binds four fractional digits is "
            f"unmeasured, which is why the scored arms use one. Recorded in the payload, "
            f"excluded from `adverse` and from n",
            "every axis driver, terminal-state definition and blocking assertion is imported "
            "from f4_modes/01_truth_table.py rather than restated — two definitions of 'the "
            "mode landed' or 'the testbed is intact' can disagree, and then which one ran "
            "decides whether a broken shared testbed is reported",
            "teardown deletes the created policy, restores both axes to the values MEASURED at "
            "startup, and RE-RUNS infra/06_verify.py's verify_engine and verify_gateways",
        ])


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def _restore(ac, store: EvidenceStore, state: T.State, *, start: dict[str, Any],
             gateway_id: str, engine_arn: str, engine_id: str, baseline_policy_id: str,
             created: dict[str, str], account_id: str, region: str,
             keep_policies: bool) -> dict[str, Any]:
    """Delete what this script created, put both axes back, re-run the blocking assertion.

    Never raises: it runs from a `finally`, and an exception here would mask both the result
    and the true state of the shared testbed. Failures become `ok: False`, which `main` turns
    into a non-zero exit.
    """
    out: dict[str, Any] = {"deleted": {}, "axes": {}, "verify": None, "errors": []}

    if keep_policies:
        out["deleted"]["skipped"] = ("--keep-policies: the narrow permit is left in place. It "
                                     "is in state.json, which is the only channel that can "
                                     "find it — `policy` takes no tags")
    else:
        for key, pid in list(created.items()):
            try:
                if _delete_policy(ac, store, state, engine_id=engine_id, policy_id=pid):
                    created.pop(key, None)
                    out["deleted"][key] = pid
            except Exception as exc:                                       # noqa: BLE001
                out["errors"].append(f"delete {key}: {type(exc).__name__}: {exc}")

    for label, fn in (
            ("baseline_policy", lambda: _set_policy_mode(
                ac, store, engine_id=engine_id, policy_id=baseline_policy_id,
                logical="baseline", mode=start["baseline_mode"])),
            ("engine", lambda: _set_engine_mode(
                ac, store, gateway_id=gateway_id, engine_arn=engine_arn,
                mode=start["engine_mode"]))):
        try:
            out["axes"][label] = fn()
        except Exception as exc:                                           # noqa: BLE001
            out["errors"].append(f"restore {label}: {type(exc).__name__}: {exc}")
            out["axes"][label] = {"error": str(exc)}

    try:
        c = Checks()
        verify_engine(ac, state, c)
        verify_gateways(ac, state, account_id, region, c)
        print("\nblocking assertion, re-run after restore:")
        c.print()
        out["verify"] = c.to_json()
    except Exception as exc:                                               # noqa: BLE001
        out["errors"].append(f"re-verify: {type(exc).__name__}: {exc}")

    out["restored_to_measured_start"] = dict(start)
    out["ok"] = (not out["errors"]
                 and bool(out["verify"]) and bool(out["verify"].get("ok"))
                 and (keep_policies or not created))
    out["why_measured_start"] = (
        "both axes are restored to the values READ LIVE at startup, not to the ledger's "
        "recorded ones. A ledger records an intent at provisioning time; this script must "
        "return the shared testbed to what it actually found")
    return out


def main(argv: list[str] | None = None) -> int:                            # noqa: C901
    ap = P.parser(CASE, __doc__)
    ap.add_argument("--keep-policies", action="store_true",
                    help="skip deletion of the policy this script creates (inspection only; "
                         "it is in state.json, which is the ONLY channel that finds it)")
    ap.add_argument("--state", default=None)
    ap.add_argument("--evidence-root", default=None,
                    help="write call records under this directory instead of evidence/. For "
                         "OFFLINE harnesses only")
    ap.add_argument("--checkpoint-root", default=None)
    ap.add_argument("--skip-precision-probe", action="store_true",
                    help="omit the 4 unscored four-fractional-digit calls")
    args = ap.parse_args(argv)

    n_by_arm = {a["key"]: (min(args.n, a["n"]) if args.n else a["n"]) for a in ARMS}
    if args.dry_run:
        return _dry_run(n_by_arm)

    is_smoke = args.n is not None

    try:
        state = T.State.load(Path(args.state) if args.state else None)
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        rec = O.not_measured(
            CASE, "state.json is absent, so there is no gateway, no policy engine and no "
                  "baseline policy to configure. Nothing was sent",
            remedy="run infra/01_iam.py onward (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: no ledger"}, None)
        return 2

    run_id = state.run_id
    if args.run_id and args.run_id != run_id:
        print(f"FATAL: --run-id {args.run_id!r} disagrees with the ledger's {run_id!r}.",
              file=sys.stderr)
        return 2

    admin = A.factory(args.region)
    ac = admin.agentcore_control()
    account_id = A.account_id(admin)
    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    print(f"{CASE} — pure-Cedar policy determinism, run_id={run_id} (adopted from the "
          f"ledger), region={args.region}\n")

    gw = state.find("gateway", "main")
    eng = state.find("policy-engine", "main")
    pol = state.find("policy", "baseline")
    caller = state.find("iam-role", "caller")
    if not (gw and eng and pol and caller):
        rec = O.not_measured(
            CASE, f"the ledger is missing a resource this case needs (gateway={bool(gw)}, "
                  f"policy-engine={bool(eng)}, baseline policy={bool(pol)}, caller "
                  f"role={bool(caller)})",
            remedy="run infra/01_iam.py onward (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: incomplete ledger"}, store)
        return 2

    gateway_id = gw.ids["gateway_id"]
    gateway_url = gw.ids["gateway_url"]
    engine_id = eng.ids["policy_engine_id"]
    baseline_policy_id = pol.ids["policy_id"]
    session_timeout_s = int(gw.ids.get("session_timeout_s", 900))
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    caller_arn = T.unmask_arn(caller.arn, account_id)

    shape = _check_update_gateway_shape(ac)
    common: dict[str, Any] = {
        "run_id": run_id, "region": args.region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "update_gateway_shape_check": shape,
        "validation_mode_for_this_policy": VALIDATION_MODE,
        "why_validation_off": (
            "F1-3 is the validation experiment and it established that a permit needs "
            "IGNORE_ALL_FINDINGS to create at all (DC-1). A policy that failed to create is "
            "not a determinism measurement, so letting the finding gate reject this statement "
            "would turn a determinism question into a validation one"),
        "instrument": (
            "signed MCP tools/call POSTs to the main gateway's /mcp endpoint as the grx-caller "
            "role, classified by lib/mcp.classify(); one pure-Cedar permit created for the "
            "run, both mode axes driven by UpdateGateway/UpdatePolicy and verified by readback "
            "from independent calls"),
        "axis_drivers_imported_from": (
            "f4_modes/01_truth_table.py — UpdateGateway is a REPLACE so the live configuration "
            "is re-read and re-sent whole; UpdatePolicy does not resend `definition`; 'the "
            "testbed is intact' is infra/06_verify.py's own verify_engine/verify_gateways. Two "
            "definitions of any of those can disagree, and then which one ran decides whether "
            "a broken shared testbed is reported"),
        "unverified_context_path": (
            "the permit conditions on `context.input.amount`. No `context.` path appears "
            "anywhere in the document under test; the shape comes from lib/cedar.py's own "
            "samples and was measured live by F4. The `permit_grants` guard exists because an "
            "unmatched path would make the policy inert — and an inert policy is perfectly "
            "constant, which is what this case counts"),
    }

    live0 = capture(store, "get_gateway", ac, gatewayIdentifier=gateway_id)
    if not live0.ok:
        rec = O.not_measured(
            CASE, f"the startup GetGateway failed ({live0.error_code}), so the axes' starting "
                  f"values were never measured and could not be restored",
            error_code=live0.error_code)
        P.emit(CASE, rec, common, store)
        return 2
    cfg0 = _engine_cfg_of(live0.response)
    engine_arn = cfg0.get("arn", "")
    start = {"engine_mode": cfg0.get("mode", ""),
             "baseline_mode": _policy_mode_now(ac, engine_id=engine_id,
                                               policy_id=baseline_policy_id)[1]}
    common["measured_start"] = dict(start)
    print(f"measured start: engine mode={start['engine_mode']!r}, baseline policy "
          f"enforcementMode={start['baseline_mode']!r}")
    print(f"UpdateGateway shape check: ok={shape['ok']} unhandled={shape['unhandled']}\n")

    if not shape["ok"]:
        rec = O.not_measured(
            CASE,
            f"UpdateGateway's input shape carries members this script does not re-send "
            f"({shape['unhandled']}) or is missing members it would send "
            f"({shape['absent_from_model']}). UpdateGateway is a REPLACE, so driving the engine "
            f"axis would RESET those members on a shared gateway. No mutation was attempted",
            shape=shape)
        P.emit(CASE, rec, common, store)
        return 2

    fc = A.factory(args.region, role_arn=caller_arn)
    tallies: dict[str, dict] = {}
    created: dict[str, str] = {}
    rc = 0
    restore: dict[str, Any] = {}

    try:
        # The Cedar action id comes from the LEDGER, not from a literal here. It is
        # `<targetName>___<toolName>`, a function of how infra/05_target.py named the target, so
        # a literal would drift silently: the policy would still CREATE (the action id is just a
        # string to the validator) and would match no request, every arm would default-deny, and
        # the run would be perfectly constant. The `permit_grants` guard would catch it, but a
        # refusal to start is cheaper than 630 wasted calls.
        tgt = state.find("gateway-target", "main")
        action_ids = list((tgt.ids.get("cedar_action_ids") if tgt else None) or [])
        echo_action_id = next((a for a in action_ids if a.endswith(f"___{TOOL}")), "")
        if not echo_action_id:
            raise ConfigError(
                f"the ledger's target/main carries no Cedar action id ending in '___{TOOL}' "
                f"(saw {action_ids}). The permit must scope `action ==` to the echo tool, "
                f"because an unscoped action has to type-check against actions that carry no "
                f"`context.input` at all")
        spec = build_policy(gateway_arn, echo_action_id=echo_action_id)
        _assert_no_guardrail_term(spec["statement"])
        problems = cedar.check_statement(spec["statement"])
        if problems:
            raise ConfigError(
                f"the statement failed lib/cedar.py's own grammar check ({problems}), so a "
                f"rejection by the service would be attributable to the harness")
        name = T.check_name(ac, "CreatePolicy", f"grx_f2_{POL_NARROW}_{run_id}")
        common["policy"] = {"name": name, "action_scope": echo_action_id, **spec}
        print(f"policy statement:\n  {spec['statement']}\n")

        _create_policy(ac, store, state, engine_id=engine_id, name=name, spec=spec,
                       registry=created)
        common["config"] = _apply_config(
            ac, store, gateway_id=gateway_id, engine_arn=engine_arn, engine_id=engine_id,
            baseline_policy_id=baseline_policy_id, narrow_policy_id=created[POL_NARROW])

        for arm in ARMS:
            n = n_by_arm[arm["key"]]
            print(f"\n  arm {arm['key']} (n={n}, amount={arm['amount']}, expect "
                  f"{arm['expect']})")
            cp = _run_arm(fc, store, arm=arm, gateway_url=gateway_url, run_id=run_id,
                          region=args.region, n=n, session_timeout_s=session_timeout_s,
                          cp_root=Path(args.checkpoint_root) if args.checkpoint_root else None,
                          is_smoke=is_smoke, tool_name=echo_action_id)
            t = _tally(arm["key"], cp, n)
            tallies[arm["key"]] = t
            print(f"      decisions={t['decision_counts']} flips={t['flips']} "
                  f"usable={t['n_usable']}/{n}")

        if args.skip_precision_probe:
            common["precision_probe"] = {"skipped": "--skip-precision-probe"}
        else:
            print(f"\n  unscored config-surface probe: amount={PRECISION_PROBE_AMOUNT} x"
                  f"{PRECISION_PROBE_N}")
            common["precision_probe"] = _precision_probe(
                fc, store, gateway_url=gateway_url, run_id=run_id,
                session_timeout_s=session_timeout_s, tool_name=echo_action_id)
            print(f"      {common['precision_probe']['reading']}")

        print("\nverdict")
        rc = _evaluate(tallies, common=common, store=store, is_smoke=is_smoke)

    except ConfigError as exc:
        print(f"\nFATAL: {exc}", file=sys.stderr)
        rec = O.not_measured(
            CASE, f"a configuration step did not land, so the arms were not all measured under "
                  f"a known configuration: {exc}",
            arms_run=sorted(tallies),
            arms_required=[a["key"] for a in ARMS])
        P.emit(CASE, rec, {**common, "arm_summaries": [_arm_summary(t)
                                                       for t in tallies.values()]}, store)
        rc = 2

    finally:
        print("\nteardown and restore")
        restore = _restore(ac, store, state, start=start, gateway_id=gateway_id,
                           engine_arn=engine_arn, engine_id=engine_id,
                           baseline_policy_id=baseline_policy_id, created=created,
                           account_id=account_id, region=args.region,
                           keep_policies=args.keep_policies)
        (store.dir / "restore.json").write_text(json.dumps(restore, indent=2, default=str))
        store.write_summary()

    if not restore.get("ok"):
        print("\nFATAL: the testbed was NOT verified back to its measured starting state. "
              "Every later phase measures this gateway, so a non-zero exit here is the only "
              "thing that stops the next script from running against an unknown configuration.",
              file=sys.stderr)
        for err in restore.get("errors", []):
            print(f"  - {err}", file=sys.stderr)
        for c in (restore.get("verify") or {}).get("checks", []):
            if not c["ok"]:
                print(f"  - FAILED CHECK {c['name']}: {c['detail']}", file=sys.stderr)
        return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
