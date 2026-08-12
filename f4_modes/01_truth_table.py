#!/usr/bin/env python3
"""F4: the enforcement-mode truth table, measured on the live gateway data plane.

    python3 f4_modes/01_truth_table.py --dry-run
    python3 f4_modes/01_truth_table.py --n 3          # smoke
    python3 f4_modes/01_truth_table.py                # the pre-registered n=120 per cell

Six confirmatory cases, one script, because all six read the SAME 2x2 and differ only in
which cell they interrogate. Splitting them across six files would mean six independent
mode switches on one shared gateway, six restore paths, and six chances for one script's
unrestored mode to become another's silent confound. Here the axis state is set once per
arm and restored in a `finally` that also RE-RUNS the blocking assertion, per
PREREGISTRATION.yaml's `restore_verification` rule.

THE SIX CASES, AND WHAT EACH ONE COULD FALSIFY
----------------------------------------------
Each is `ZERO_EVENTS` at alpha = 0.05/8 = 0.00625, n = 120 per cell, `tolerate_failures: 0`.
`adverse` is the count of trials that came out the way the document says they cannot; the
sealed oracle text fixes the polarity and this script does not get a vote:

  F4-1  ENFORCE engine + guardrail policies only, NO baseline permit. The doc's §3.1 gotcha
        says this blocks ALL traffic including benign requests. adverse = a benign request
        that was NOT denied.  MUTATION MANDATORY.
  F4-2  A request that ENFORCE denies must pass under LOG_ONLY (the §7.1 tuning workflow).
        adverse = a trial that WAS blocked under LOG_ONLY.
  F4-3  The full 2x2. The doc (L309) says engine mode takes PRECEDENCE: engine LOG_ONLY with
        policy ACTIVE blocks nothing. adverse = a trial that WAS blocked in that cell.
        MUTATION MANDATORY.
  F4-4  Cedar default-deny: a request matching no policy is denied. adverse = NOT denied.
  F4-5  forbid overrides permit. adverse = a request matching both that was NOT denied.
  F4-6  "Denied requests receive HTTP 403 with a message identifying the denying policy ID"
        (L141). adverse = a denial whose status is not 403 OR whose body omits the policy id.

F4-6 IS EXPECTED TO REFUTE THE DOCUMENT, AND THAT IS A RESULT, NOT A BUG
------------------------------------------------------------------------
`lib/mcp.py` was written from the wire: a gateway policy denial arrives as **HTTP 200** with
`result.isError: true` and an `AuthorizeActionException` in the text. If that holds at
n=120, L141 is wrong on both halves of its sentence and three sites need amending. This
prediction is written here, BEFORE the run, so that a confirmation cannot be presented as a
discovery and a surprise cannot be quietly absorbed. The script asserts nothing about which
way it comes out; it classifies and counts.

F4-6's binding is the only one of the six carrying `thresholds`, `(403.0,)`. That threshold
is DECORATIVE to its kind: `oracle._decide`'s ZERO_EVENTS branch reads `obs.adverse` and `n`
and never looks at `b.thresholds`. So this script does the 403/policy-id classification
itself, in `_classify_f4_6`, rather than assuming the oracle applies the number it carries.
(`limits_by_reference` is empty for all six — verified against the sealed bindings on
2026-08-11, correcting an earlier note that claimed F4-6 carried `("403",)` there.)

WHAT COUNTS AS THE MEASUREMENT
------------------------------
One trial = one signed `tools/call` POST to the main gateway's `/mcp` endpoint as the
`grx-caller` role, and the observation is `lib/mcp.classify()`'s `Decision`. Not our own
reading of the body: `classify` recognises the documented denial markers, sets
`default_deny` only when the service names itself as such, and sets `unclassified` for an
`AuthorizeActionException` carrying no marker it knows. An `unclassified` hit exits **rc 1**
without a verdict, because an error shape nobody has seen before is not evidence about the
truth table — it is a gap in the instrument.

THE AXES ARE DRIVEN, AND THAT IS WHY F4 OWNS RESTORE
----------------------------------------------------
`infra/06_verify.py` deliberately pins the engine ARN but NOT either mode, with the comment
that F4 legitimately drives the mode to LOG_ONLY. So nothing outside this script will notice
a mode left switched, and the shared gateway is what every later phase measures. Both axes
are therefore restored to their MEASURED starting values (read at startup, not assumed from
the ledger) and re-verified by readback from an independent call:

  engine axis  `UpdateGateway` -> readback from BOTH the Update response and `GetGateway`,
               plus `04_gateway.wait_ready`. Resends the four required members AND the full
               live configuration, because UpdateGateway is a REPLACE: a field omitted is a
               field reset, and resetting `exceptionLevel` would silently change what every
               later error body contains.
  policy axis  `UpdatePolicy(policyEngineId, policyId, enforcementMode=...)` -> readback from
               `GetPolicy.enforcementMode`. `definition` is NOT resent: re-sending the Cedar
               body would re-run validation, and DC-1 is the finding that this exact
               statement fails validation without `IGNORE_ALL_FINDINGS`.

RETRY POLICY ON THIS PLANE, STATED BECAUSE IT WAS A DEFECT
----------------------------------------------------------
The data plane does not go through botocore, and `lib/mcp.py`'s pool is built with
`retries=False` on purpose (a transparently retried POST reports one duration covering
several attempts). So every retry decision lands in `checkpoint.is_retryable`, which works
from an allowlist. `McpTransportError` carried no identity until 2026-08-11 and would have
been classified permanent — the DEV-P1-11 shape, which on the control plane cost 3,378
trials with zero retries. It now carries `error_class`, the measured urllib3 names are on
the allowlist, and `lib/tests/test_mcp_retryability.py` pins both halves. Failures that are
OUR defect (no session id, no credentials) still carry no class and stay permanent.

COST AND BLAST RADIUS
---------------------
Zero text units: no `ApplyGuardrail`, no `InvokeGuardrailChecks`, no model. Billable surface
is Lambda invocations (<=1,440 at 128 MB / ~2 ms) plus control-plane calls, which are free.
cost_model.yaml's Phase 3 block budgets exactly this. The blast radius is the two mode
fields on ONE gateway and its ONE baseline policy, plus policies this script creates and
deletes in its own `finally` — `policy` is structurally untaggable, so that `finally` is the
only teardown channel and the tag sweep cannot catch a leak here.

Never touched: the six pre-existing READY gateways, the three DRAFT guardrails, the two
abandoned policy engines (read-only evidence for F1-3), any `harness_*`/`uitestagent_*`
runtime, and the `nopolicy` gateway (F6's paired baseline — giving it an engine would
destroy the pairing).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R                                                    # noqa: E402
import awsclients as A                                              # noqa: E402
import cedar                                                        # noqa: E402
import checkpoint as C                                              # noqa: E402
import mcp as M                                                     # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402
import testbed as T                                                 # noqa: E402
from evidence import EvidenceStore, capture                          # noqa: E402

FAMILY = "f4_modes"
CASES = ("F4-1", "F4-2", "F4-3", "F4-4", "F4-5", "F4-6")

# One definition of "terminal", borrowed rather than restated. Two definitions of when a
# gateway is ready is two answers to "did the mutation land", and the verdict would depend
# on which one a reader happened to look at. `f1_config/03_permit_trap.py` loads
# `03_policy_engine.py` the same way and for the same reason.
#
# The `sys.modules` key is a module-level CONSTANT rather than a parameter, and that is not
# style. `lib/tests/test_module_name_collisions.py` reads every by-path loader call
# statically to prove no two of them register the same name — `infra/04_gateway.py`'s stem is
# `04_gateway`, which is not a legal identifier and so cannot be imported normally, meaning
# a collision here would silently hand some other script a different module under the same
# key. A name built from a parameter is unreadable to that gate, which is why the first
# version of this file made it fail. Passing a literal keeps the guard able to see it.
GW_MODULE_NAME = "grx_infra_04_gateway"

_spec = importlib.util.spec_from_file_location(
    GW_MODULE_NAME, ROOT / "infra" / "04_gateway.py")
_gw = importlib.util.module_from_spec(_spec)
sys.modules[GW_MODULE_NAME] = _gw
_spec.loader.exec_module(_gw)

wait_ready = _gw.wait_ready
GW_TERMINAL_OK = _gw.TERMINAL_OK
GW_TERMINAL_BAD = _gw.TERMINAL_BAD

# The policy provisioner, for `wait_status` — the same "terminal" this project already uses for
# a policy's lifecycle. `f1_config/03_permit_trap.py` registers this module under the key
# `_grx_policy_engine`, so a DIFFERENT literal is required here or the two scripts would fight
# over one `sys.modules` entry and the loser would silently get the other's module object.
PE_MODULE_NAME = "grx_infra_03_policy_engine"

_spec_pe = importlib.util.spec_from_file_location(
    PE_MODULE_NAME, ROOT / "infra" / "03_policy_engine.py")
_pe = importlib.util.module_from_spec(_spec_pe)
sys.modules[PE_MODULE_NAME] = _pe
_spec_pe.loader.exec_module(_pe)

wait_status = _pe.wait_status
PE_TERMINAL_OK = _pe.TERMINAL_OK

# The blocking assertion itself, imported rather than restated. PREREGISTRATION.yaml's
# `restore_verification` rule says: "After every mutation: restore, then RE-RUN the blocking
# assertion. A restore is not assumed to have worked because the API call returned 200." A
# re-implementation here would be a SECOND definition of "the testbed is intact", and the two
# could disagree — at which point the guarantee is worth nothing, because which one ran would
# decide whether a broken testbed was reported. So the restore path calls the very functions
# `infra/06_verify.py` runs as the Phase-2 gate.
VERIFY_MODULE_NAME = "grx_infra_06_verify"

_spec_vf = importlib.util.spec_from_file_location(
    VERIFY_MODULE_NAME, ROOT / "infra" / "06_verify.py")
_vf = importlib.util.module_from_spec(_spec_vf)
sys.modules[VERIFY_MODULE_NAME] = _vf
_spec_vf.loader.exec_module(_vf)

Checks = _vf.Checks
verify_engine = _vf.verify_engine
verify_gateways = _vf.verify_gateways

# The two enums, spelled as the service models them. `EnforcementMode` is the POLICY axis and
# `GatewayPolicyEngineMode` is the ENGINE axis; they share the token LOG_ONLY and mean
# different things, which is precisely the confusion F4-3 exists to resolve. Verified against
# botocore 1.43.67's shapes rather than recalled: an earlier note in this project had the
# policy axis named `PolicyEnforcementMode`, which does not exist.
ENGINE_ENFORCE = "ENFORCE"
ENGINE_LOG_ONLY = "LOG_ONLY"
POLICY_ACTIVE = "ACTIVE"
POLICY_LOG_ONLY = "LOG_ONLY"

# Terminal states for the purpose of MUTATING a policy — a superset of `PE_TERMINAL_OK`, which is
# the set that counts as healthy. A policy in `UPDATE_FAILED` is not healthy, but it has settled,
# and it can be deleted. Waiting only for `ACTIVE` would burn the whole timeout on a policy that
# will never get there and then leak it. Measured on this testbed 2026-08-11: `DeletePolicy`
# against a policy still in `UPDATING` returns `ConflictException`.
POLICY_TERMINAL_FOR_MUTATION = ("ACTIVE", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED")

# How long a policy mutation is allowed to take, ONE definition. The first version of
# `_wait_policy_terminal` invented its own budget — 10 attempts x 3s = 27s — and the n=3 smoke on
# 2026-08-11 read `status='UPDATING'` at the end of it while `infra/03_policy_engine.wait_status`
# (which this same script uses successfully at CREATE time) allows 180s and `_set_policy_mode`
# below allows 120s. Three numbers for one question is three answers to it, and the shortest one
# silently wins wherever it is called. `MODE_READBACK_TIMEOUT_S` is defined further down next to
# the settle constants it belongs with; this is deliberately the same value and not a copy.
#
# The retry budget is separate and SHORTER on purpose: it runs in teardown, where 5 attempts at
# the full settle budget would be a 10-minute stall on a script that has already finished
# measuring. A policy that has not settled in one full budget plus four short ones is a leak to
# be REPORTED, not waited on — that is what the ledger entry is for.
DELETE_ATTEMPTS = 5
DELETE_SLEEP_S = 3.0
DELETE_RETRY_SETTLE_S = 30.0

# The benign request every arm sends. `echo` returns its text verbatim, takes a typed
# `amount`, and reaches no network — so tool behaviour is a constant and all observed
# variance belongs to the policy path. `amount` is present because the F4-4/F4-5 policies
# match on it, and a request whose shape differed between arms would confound the axis with
# the payload.
# `amount` is a float, not an int, and json.dumps preserving the `.0` is load-bearing.
# MEASURED 2026-08-11 (run r20260810T130945Z): an integral JSON literal `"amount": 100`
# reaches the policy engine as something it refuses to bind to Cedar `decimal` — the denial
# reads "Parameter format error: one or more numeric parameters must include a decimal point
# (e.g., 100.0). Check parameters: amount" — and BOTH narrow cells then deny for the wrong
# reason (evaluation error, not default-deny / not a matched permit). So the runtime demands
# what the validator already told us (`number` -> decimal, F1-12 count 3), but enforces it
# per-request on the LITERAL'S SPELLING, and a policy that type-checks can still error on
# every request whose caller sent `100` instead of `100.0`.
BENIGN_ARGS = {"text": "f4 truth table", "amount": 100.0}
TOOL = "echo"

# A tools/call that no policy can match, for F4-4. Same tool, same shape — the ONLY
# difference is an `amount` outside every policy's condition, so "matched no policy" is the
# single independent variable rather than "was a different request".
UNMATCHED_ARGS = {"text": "f4 unmatched", "amount": 4242.0}


# --------------------------------------------------------------------------
# classification: one Decision -> one row
# --------------------------------------------------------------------------

def _row(d: M.Decision, *, hit: bool, trial_id: str, **extra: Any) -> dict:
    """One checkpoint row. `hit` is what `arms.tally` counts into `x`.

    The full `Decision` goes in via `to_json()` (which drops the raw body and truncates the
    text) so a re-classification months later works from the archived row, not from a
    remembered reading. `hit` is derived per case by the `_classify_*` functions below and is
    never computed here: the polarity belongs next to the oracle text it comes from.
    """
    return {"trial_id": trial_id, "hit": bool(hit), **d.to_json(), **extra}


def _classify_denied_is_expected(d: M.Decision) -> tuple[bool, str]:
    """For cases whose oracle counts a trial that was NOT denied (F4-1, F4-4, F4-5).

    Returns `(adverse, why)`. Adverse means the document's prediction failed on this trial.
    `d.denied` is `outcome == "policy_denied"`, i.e. the service named it a denial — a
    `tool_error` is NOT counted as a denial, because our own handler's `bad_request` lands
    there and treating a malformed argument as enforcement would manufacture agreement with
    the document out of a bug in the request.
    """
    if d.outcome == "policy_denied":
        return False, "denied, as the document predicts"
    if d.outcome == "allowed":
        return True, "the tool RAN — the document says this request cannot reach it"
    # http_error / jsonrpc_error / tool_error: not an answer to the question asked. Counted
    # adverse would credit the document; counted benign would credit it too. Neither: these
    # rows are excluded from n by `_usable`, and the completion gate then decides whether
    # enough trials remain to sustain the pre-registered precision.
    return False, f"not an answer to this question: {d.outcome}"


def _classify_allowed_is_expected(d: M.Decision) -> tuple[bool, str]:
    """For cases whose oracle counts a trial that WAS blocked (F4-2, F4-3).

    Both are LOG_ONLY cells, where the document's claim is that nothing is blocked. So a
    denial is the adverse event and an allow confirms the claim.
    """
    if d.outcome == "allowed":
        return False, "not blocked, as the document predicts"
    if d.outcome == "policy_denied":
        return True, "BLOCKED under LOG_ONLY — the document says nothing is blocked here"
    return False, f"not an answer to this question: {d.outcome}"


def _classify_f4_6(d: M.Decision,
                   policy_ids: tuple[str, ...]) -> tuple[bool, str, dict]:
    """F4-6: "Denied requests receive HTTP 403 with a message identifying the policy ID."

    Two conjuncts, and the oracle's polarity is adverse if EITHER fails: adverse = the status
    differs from 403 OR the policy id is absent. Both are recorded separately so a partial
    refutation is legible — if the status were 403 but the id absent, only half the sentence
    would need amending, and a single boolean could not say which half.

    The 403 comparison is done here and not by the oracle: F4-6's binding carries
    `thresholds == (403.0,)`, but `oracle._decide`'s ZERO_EVENTS branch reads only
    `obs.adverse` and `n` and never consults `thresholds`. A script that assumed otherwise
    would be relying on a number the decision function does not read.

    `policy_ids` is REQUIRED and has no default, and that is not style. The first draft of
    this function ended on a placeholder that returned "not adverse" for every denial while
    referring to a helper that did not exist — so F4-6 would have reported agreement with the
    document *by construction*, which is the `feedback_vacuous_test_check` shape this project
    exists to catch. A parameter with no default makes the omission a TypeError at the call
    site instead of a published verdict. An EMPTY tuple is still rejected below, for the same
    reason: searching a message for nothing finds nothing, and "no id was found" would then
    be a property of the search rather than of the message.

    `_policy_id_in` looks for the ACTUAL id of a policy this run created, not for the word
    "policy" or a regex over id-shaped strings. A message containing "denied by policy" and
    no identifier satisfies a loose search while failing the claim as written, and the claim
    as written is what is under test.
    """
    if not policy_ids or not any(policy_ids):
        raise ValueError(
            "F4-6 needs at least one real policy id to search the denial message for. With "
            "an empty id set every message trivially 'omits the policy id', and the adverse "
            "count would measure the search rather than the service")
    found = _policy_id_in(d.text, policy_ids)
    detail = {
        "http_status": d.http_status,
        "status_is_403": d.http_status == 403,
        "outcome": d.outcome,
        "default_deny_named": d.default_deny,
        "authorize_exception": d.authorize_exception,
        "policy_id_found": found,
        "policy_id_present": bool(found),
        "policy_ids_searched": list(policy_ids),
    }
    if d.outcome != "policy_denied":
        # Only a DENIAL can be examined for the properties the sentence ascribes to denials.
        # A trial that was allowed says nothing about the shape of a denial, so it is not
        # usable for this case rather than being scored either way.
        return False, f"not a denial ({d.outcome}); says nothing about denial shape", detail

    # Both conjuncts, evaluated separately and then conjoined here, so the record says which
    # half of L141 failed. `adverse` is the negation of the conjunction, exactly as the sealed
    # text states it: "FALSE if the status differs or the policy ID is absent".
    status_ok = d.http_status == 403
    id_ok = bool(found)
    if status_ok and id_ok:
        return False, "403 and the policy id is named — the document holds on this trial", detail
    parts = []
    if not status_ok:
        parts.append(f"status is {d.http_status}, not 403")
    if not id_ok:
        parts.append("the message names no policy id this run created")
    return True, "; ".join(parts), detail


def _policy_id_in(text: str, policy_ids: tuple[str, ...]) -> str:
    """The first policy id that literally appears in the message, or "".

    Substring, case-sensitive, against ids this run created. Deliberately strict: the claim
    is that the message *identifies the denying policy ID*, and anything looser would let
    prose about policies pass as an identifier.
    """
    for pid in policy_ids:
        if pid and pid in text:
            return pid
    return ""


def _usable(d: M.Decision, case_id: str) -> bool:
    """Is this trial an answer to the question this case asks?

    A trial that neither ran nor was denied — a transport 5xx, a JSON-RPC protocol error —
    is not evidence about the truth table, and folding it into either count would move a
    verdict on the strength of a failure. Excluded from n, which makes it visible through
    `require_measured`'s per-arm 0.90 completion gate instead of through a silently smaller
    denominator (DEV-P1-11: a shortfall reported beside a verdict IS a verdict).

    F4-6 additionally requires a DENIAL: its question is about the shape of denials, so an
    allowed trial is not a smaller-precision answer, it is not an answer.
    """
    if case_id == "F4-6":
        return d.outcome == "policy_denied"
    return d.outcome in ("allowed", "policy_denied")


def _decision_from_row(row: dict) -> M.Decision:
    """Rebuild a `Decision` from an archived checkpoint row.

    This is what makes a cell readable by more than one case (see `CELLS`): F4-5 asks whether
    a permit-plus-forbid request is denied and F4-6 asks what the denial *looks like*, and
    both questions are about the same 120 responses. Re-sending them a second time would cost
    120 Lambda invocations and add no information.

    `text` is truncated to 2000 characters by `Decision.to_json`, so a reconstruction is NOT
    equivalent to the original for a message longer than that. F4-6 is the only case whose
    answer depends on the message body, and it does not re-derive its classification here —
    `_one_call` computes it from the FULL text at call time and stores the result on the row.
    See `_f4_6_from_row`.
    """
    return M.Decision(
        outcome=row.get("outcome", ""),
        http_status=row.get("http_status"),
        request_id=row.get("request_id", ""),
        is_error=row.get("is_error"),
        text=row.get("text", "") or "",
        default_deny=bool(row.get("default_deny")),
        authorize_exception=bool(row.get("authorize_exception")),
        unclassified=bool(row.get("unclassified")),
        duration_ms=float(row.get("duration_ms") or 0.0),
        session_id=row.get("session_id", "") or "",
        jsonrpc_error=row.get("jsonrpc_error"))


def _f4_6_from_row(row: dict) -> tuple[bool, str, bool]:
    """F4-6's stored classification: `(adverse, why, usable)`.

    Read from the row rather than recomputed, because the recomputation would run against a
    text `to_json` truncated at 2000 characters. A policy id sitting past that boundary would
    then be "absent" as a property of our own serializer, and the refutation this case is
    predicted to produce would rest on it. `_one_call` classifies from the full body once, at
    the moment the body exists.

    A truncated message in which no id was found is NOT counted adverse: it is unusable. That
    asymmetry is deliberate. "The message does not name the policy" and "we could not see all
    of the message" are different observations with opposite remedies, and only the first is
    evidence about the document. The second surfaces through `require_measured`'s completion
    gate, which is where a shortfall belongs.
    """
    if row.get("f4_6_indeterminate_truncation"):
        return False, "message was truncated before a policy id could be ruled out", False
    if row.get("outcome") != "policy_denied":
        return False, f"not a denial ({row.get('outcome')})", False
    return bool(row.get("f4_6_adverse")), str(row.get("f4_6_why") or ""), True


# --------------------------------------------------------------------------
# the configuration cells, and the cases that read them
# --------------------------------------------------------------------------
#
# A CELL is one live configuration plus one request shape. A CASE is a question asked of one
# or more cells. The two are separate because they are not in one-to-one correspondence and
# pretending otherwise costs real money for no information: the configuration
# `engine=ENFORCE, {baseline permit ACTIVE, forbid ACTIVE}, benign request` is simultaneously
#
#   * F4-5's oracle arm            (does a permit-plus-forbid request get denied?)
#   * F4-6's oracle arm            (what does that denial LOOK like?)
#   * F4-2's paired ENFORCE arm    (is this a request that ENFORCE denies?)
#   * F4-3's (ENFORCE, ACTIVE) 2x2 cell, which is also F4-3's mandatory mutation
#
# Four questions, one set of 120 responses. An earlier arm-per-case plan sent 1,460 requests;
# eight cells answer all six cases in 860, and the two figures differ ONLY in how many times
# the same request is re-sent under the same configuration. `cost_model.yaml`'s Phase 3
# `lambda_invoke` line carries this derivation, so the cost line and this table cannot drift
# apart silently.
#
# Every cell states the mode of EVERY policy that exists at that moment. None is defaulted:
# the enforced policy set is the independent variable of the whole family, and a policy whose
# mode was implicit would be a variable nobody declared. `_apply_config` refuses a cell that
# omits one.
#
# `expect` is the ARM's own prediction, not the sealed oracle's polarity. For an oracle cell
# the two coincide by construction; for a mutation, control or table cell they need not, and
# `hit` therefore means "this arm's own prediction failed on this trial". Only an oracle
# cell's hits ever reach `obs_zero_events`.

PLANNED_N = 120                      # sealed: O.planned_n("F4-1") == 120 for all six
CONTROL_N = 20                       # see CELLS["enforce__narrow_only__matched"]

# The policies THIS script creates. All three are created with `enforcementMode=LOG_ONLY`, so
# a create can never change what the gateway does before the arm that wants it says so.
POL_GUARDRAIL = "guardrail"
POL_NARROW = "narrow"
POL_FORBID = "forbid"

# Stages exist so that a policy is not merely inert but ABSENT while the cells that must not
# see it are running. F4-1's oracle text says "when only guardrail policies exist", and a
# LOG_ONLY permit sitting in the engine would make that sentence true only under a reading of
# LOG_ONLY — which is itself one of the things under test. Circularity is cheaper to avoid
# than to argue about, so the guardrail stage runs first and its policy is deleted before the
# permit is created.
#
# The guardrail policy is also the only billable surface in the family: a LOG_ONLY guardrail
# policy is still EVALUATED side-by-side, which means guardrail checks still run and still
# bill text units. Leaving it in the engine for the remaining six cells would bill roughly
# 500 text units instead of 120 for no measurement at all.
STAGES: tuple[dict[str, Any], ...] = (
    {"key": "guardrail_only", "creates": POL_GUARDRAIL,
     "why": ("F4-1 needs an engine whose ONLY policy is a guardrail policy. The permit and "
             "forbid policies are not created yet, so 'only guardrail policies exist' is "
             "literally true of the engine rather than true under an interpretation of "
             "LOG_ONLY — and LOG_ONLY's meaning is exactly what F4-2/F4-3 are testing")},
    {"key": "default_deny", "creates": POL_NARROW,
     "why": ("F4-4 needs a request that matches NO policy while a policy that could have "
             "matched is present and ACTIVE. A narrow permit conditioned on the request "
             "parameter supplies both halves: the unmatched request is the arm, and the same "
             "policy matching a different parameter value is the control")},
    {"key": "forbid_wins", "creates": POL_FORBID,
     "why": ("F4-5, F4-6, F4-2 and F4-3 all need a policy that DENIES a request the baseline "
             "permit allows. One unconstrained forbid supplies the denial for all four, and "
             "the engine/policy mode axes are then driven over it")},
)

CELLS: tuple[dict[str, Any], ...] = (
    # ---- stage 1: guardrail-only engine -------------------------------------------------
    {"key": "enforce__guardrail_only__benign", "stage": "guardrail_only",
     "engine": ENGINE_ENFORCE, "args": "benign", "expect": "denied", "n": PLANNED_N,
     "modes": {"baseline": POLICY_LOG_ONLY, POL_GUARDRAIL: POLICY_ACTIVE},
     "why": ("F4-1's ORACLE arm. The engine is ENFORCE and no permit is in the enforced set, "
             "so Cedar default-deny should block a benign request. The baseline permit is "
             "driven to LOG_ONLY rather than DELETED: re-creating it afterwards would have "
             "to pass IGNORE_ALL_FINDINGS (that is DC-1, F1-3's finding), and a failed "
             "re-create would leave the shared testbed without the permit every later phase "
             "depends on. The operationalization is recorded as a limitation")},
    {"key": "enforce__baseline_permit__benign", "stage": "guardrail_only",
     "engine": ENGINE_ENFORCE, "args": "benign", "expect": "allowed", "n": PLANNED_N,
     "modes": {"baseline": POLICY_ACTIVE, POL_GUARDRAIL: POLICY_ACTIVE},
     "why": ("F4-1's MANDATORY MUTATION. Restoring the baseline permit to ACTIVE must make "
             "the identical request pass. If it does not, the denial in the arm above was "
             "not caused by the missing permit and the §3.1 gotcha is unsupported by this "
             "run — which is why the seal marks F4-1's mutation mandatory. This is also the "
             "only cell in the family that bills text units: the request is expected to "
             "reach the tool, so the guardrail policy's output evaluation actually runs")},

    # ---- stage 2: default-deny ----------------------------------------------------------
    {"key": "enforce__narrow_only__unmatched", "stage": "default_deny",
     "engine": ENGINE_ENFORCE, "args": "unmatched", "expect": "denied", "n": PLANNED_N,
     "modes": {"baseline": POLICY_LOG_ONLY, POL_NARROW: POLICY_ACTIVE},
     "why": ("F4-4's ORACLE arm: a request matching no policy. The narrow permit is ACTIVE "
             "and conditioned on the request parameter, and this request carries a value "
             "outside that condition, so nothing in the enforced set matches it")},
    {"key": "enforce__narrow_only__matched", "stage": "default_deny",
     "engine": ENGINE_ENFORCE, "args": "benign", "expect": "allowed", "n": CONTROL_N,
     "modes": {"baseline": POLICY_LOG_ONLY, POL_NARROW: POLICY_ACTIVE},
     "why": ("F4-4's CONTROL, and it is load-bearing rather than decorative. If the narrow "
             "permit's `context.input.amount` condition does not evaluate the way the SDK "
             "samples assume, it matches NOTHING — and then both requests default-deny, "
             "F4-4 reads TRUE, and the reason would be that our policy never matched rather "
             "than that the service denies unmatched requests. So this cell sends the SAME "
             "tool with a parameter INSIDE the condition and must be ALLOWED. n=20, not 120: "
             "its job is to establish that the condition matches at all, which one allow "
             "already does; 20 buys margin against a transient without paying for precision "
             "no claim rests on")},

    # ---- stage 3: forbid, and both mode axes -------------------------------------------
    {"key": "enforce__permit_forbid__benign", "stage": "forbid_wins",
     "engine": ENGINE_ENFORCE, "args": "benign", "expect": "denied", "n": PLANNED_N,
     "modes": {"baseline": POLICY_ACTIVE, POL_FORBID: POLICY_ACTIVE},
     "why": ("the most-read cell in the family, and one measurement rather than four. It is "
             "F4-5's oracle arm (does forbid override permit), F4-6's oracle arm (what does "
             "the denial look like), F4-2's paired ENFORCE arm (establishing that this IS a "
             "request ENFORCE denies, without which F4-2's oracle sentence has no subject) "
             "and F4-3's (ENFORCE, ACTIVE) 2x2 cell, which is F4-3's mandatory mutation")},
    {"key": "enforce__permit_only__benign", "stage": "forbid_wins",
     "engine": ENGINE_ENFORCE, "args": "benign", "expect": "allowed", "n": PLANNED_N,
     "modes": {"baseline": POLICY_ACTIVE, POL_FORBID: POLICY_LOG_ONLY},
     "why": ("F4-5's CONTROL and F4-3's (ENFORCE, LOG_ONLY) 2x2 cell. Driving the forbid to "
             "LOG_ONLY must restore the allow; if the request is denied here too, the denial "
             "in the cell above was not the forbid's doing and 'forbid overrides permit' is "
             "unsupported by this run")},
    {"key": "log_only__permit_forbid__benign", "stage": "forbid_wins",
     "engine": ENGINE_LOG_ONLY, "args": "benign", "expect": "allowed", "n": PLANNED_N,
     "modes": {"baseline": POLICY_ACTIVE, POL_FORBID: POLICY_ACTIVE},
     "why": ("THE cell the document's most consequential mode claim lives on, and it answers "
             "two cases. L309 says engine mode takes precedence — 'an engine in LOG_ONLY "
             "blocks nothing, even if individual policies are ACTIVE' — which is F4-3's "
             "oracle. L737 says a request that ENFORCE denies passes under LOG_ONLY, which "
             "is F4-2's oracle. Same configuration, same request, two claim sites; the "
             "measurement is shared and both cases cite it")},
    {"key": "log_only__permit_only__benign", "stage": "forbid_wins",
     "engine": ENGINE_LOG_ONLY, "args": "benign", "expect": "allowed", "n": PLANNED_N,
     "modes": {"baseline": POLICY_ACTIVE, POL_FORBID: POLICY_LOG_ONLY},
     "why": ("F4-3's fourth 2x2 cell, (LOG_ONLY, LOG_ONLY). It carries no oracle of its own "
             "and is run anyway: without it the 'full 2x2' the sealed oracle text names "
             "would be three cells and a claim, and a table with a missing corner cannot "
             "show that the two axes are independent rather than confounded")},
)

ARGS_BY_KEY = {"benign": BENIGN_ARGS, "unmatched": UNMATCHED_ARGS}

# Which cells each case reads, and in which role. `oracle` is the cell whose hits become
# `adverse`; `mutation` is the cell whose inversion the seal may require; everything else is
# reported and gated for completion but never scored into the verdict.
CASE_CELLS: dict[str, dict[str, Any]] = {
    "F4-1": {"oracle": "enforce__guardrail_only__benign",
             "mutation": "enforce__baseline_permit__benign",
             "support": ()},
    "F4-2": {"oracle": "log_only__permit_forbid__benign",
             "mutation": None,
             "support": ("enforce__permit_forbid__benign",)},
    "F4-3": {"oracle": "log_only__permit_forbid__benign",
             "mutation": "enforce__permit_forbid__benign",
             "support": ("enforce__permit_only__benign",
                         "log_only__permit_only__benign")},
    "F4-4": {"oracle": "enforce__narrow_only__unmatched",
             "mutation": None,
             "support": ("enforce__narrow_only__matched",)},
    "F4-5": {"oracle": "enforce__permit_forbid__benign",
             "mutation": None,
             "support": ("enforce__permit_only__benign",)},
    "F4-6": {"oracle": "enforce__permit_forbid__benign",
             "mutation": None,
             "support": ()},
}

# `UpdateGateway` is a REPLACE, so an omitted member is a RESET. These are every member the
# operation accepts that `GetGateway` also returns, i.e. every field whose live value must be
# read and re-sent. `gatewayIdentifier` (input-only) and `policyEngineConfiguration` (the one
# field being changed) are handled separately. Verified against botocore 1.43.67 and
# re-verified at run time by `_check_update_gateway_shape`, because a member added by a future
# SDK would otherwise be silently reset on the first mode switch — and resetting
# `exceptionLevel` would change the body of every error every later phase reads.
UPDATE_GATEWAY_PASSTHROUGH = (
    "name", "description", "roleArn", "protocolType", "protocolConfiguration",
    "authorizerType", "authorizerConfiguration", "kmsKeyArn",
    "customTransformConfiguration", "interceptorConfigurations",
    "exceptionLevel", "wafConfiguration",
)

# After a control-plane readback confirms a mode change landed, wait this long before sending
# the first trial. FIXED, and deliberately not conditioned on any data-plane outcome: a settle
# loop that polled until the gateway behaved as the document predicts could never observe a
# refutation, because the refutation is precisely the outcome it would keep waiting through.
# The number is a guess at data-plane propagation and is stated as one; `trial_index` is
# recorded on every row so that a propagation lag longer than this shows up as adverse events
# clustered at the start of an arm rather than as an unexplained verdict.
SETTLE_DWELL_S = 15.0

# How long a mode change may take to become READABLE. Separate from the dwell above: this one
# is a control-plane fact with a definite answer, so it is polled rather than waited out.
MODE_READBACK_TIMEOUT_S = 120.0
MODE_READBACK_SLEEP_S = 3.0

# `Decision.to_json` truncates `text` at this many characters. Recorded on every row as
# `text_archived_complete` so a later re-analysis can tell, per row, whether the archived
# message is the whole message. Measured, not assumed: for the `policy_denied` path
# `lib/mcp.classify` builds `text` from the full content array (mcp.py:302) and only `to_json`
# clips it (mcp.py:245), so a denial classified at call time is classified on the whole body.
TEXT_ARCHIVE_LIMIT = 2000

# One checkpoint file per CELL, and the case-id slot carries the FAMILY rather than one of the
# six case ids. A cell is shared by up to four cases (see `CASE_CELLS`), so keying the file by a
# case id would either duplicate 120 live requests per case or assert that one case owns a
# measurement three others also read. `Checkpoint.load` is fatal on a case-id mismatch, which
# makes this constant load-bearing: changing it orphans every checkpoint on disk.
CHECKPOINT_CASE = "F4-cells"

# F4's own policies are created with validation OFF. F4 is not the validation experiment —
# F1-3 is, and it established that the unconstrained permit needs IGNORE_ALL_FINDINGS to
# create at all (DC-1). A policy that failed to create is not a mode measurement, and letting
# the finding gate reject one of these statements would turn a mode question into a validation
# question. The parameter is recorded in every case payload so that this is a stated design
# choice rather than a silent one.
F4_VALIDATION_MODE = "IGNORE_ALL_FINDINGS"

# The narrow permit's parameter bound. `BENIGN_ARGS["amount"]` is inside it and
# `UNMATCHED_ARGS["amount"]` is outside, which is the whole of F4-4's independent variable.
NARROW_AMOUNT_LIMIT = 500

# Guards that are not about completion but about whether the case has a subject at all. A cell
# can run to 100% completion and still leave a case unmeasured: if F4-4's control is DENIED,
# then the narrow permit never matched anything, both of F4-4's requests default-deny, and F4-4
# would read TRUE because our policy was inert rather than because the service denies unmatched
# requests. `require_measured` cannot see this — it gates n_usable/n_attempted and never looks
# at which way the trials came out.
#
# The bar is `x == 0`: not one usable trial in the guard cell may contradict its own prediction.
# That is strict on purpose. The oracle cells in this family are all ZERO_EVENTS at
# alpha=0.00625, so tolerating one exception in a subject cell while counting zero exceptions in
# the oracle cell would apply two different standards to the same kind of claim.
CASE_GUARDS: dict[str, tuple[dict[str, Any], ...]] = {
    "F4-2": ({"cell": "enforce__permit_forbid__benign",
              "why": ("F4-2's sealed text is 'a request that ENFORCE denies passes under "
                      "LOG_ONLY'. If ENFORCE did not deny this request, the sentence has no "
                      "subject: every trial in the LOG_ONLY cell would then pass for the "
                      "trivial reason that nothing ever blocked it, and the case would read "
                      "TRUE without the document's claim having been exercised")},),
    "F4-4": ({"cell": "enforce__narrow_only__matched",
              "why": ("`context.input.amount` is an UNVERIFIED path: it appears nowhere in the "
                      "document under test and only in lib/cedar.py's own samples. If the "
                      "gateway does not surface tool arguments there, the narrow permit "
                      "matches NOTHING, both of F4-4's requests default-deny, and F4-4 reads "
                      "TRUE because our policy was inert. This cell sends the same tool with "
                      "an amount INSIDE the condition and must be allowed")},),
    "F4-5": ({"cell": "enforce__permit_only__benign",
              "why": ("'forbid overrides permit' needs the permit to have been granting in the "
                      "first place. If the request is denied with the forbid in LOG_ONLY too, "
                      "the denial in the oracle cell was not the forbid's doing")},),
}


# --------------------------------------------------------------------------
# the Cedar bodies
# --------------------------------------------------------------------------

class ConfigError(RuntimeError):
    """A configuration step did not land, so no cell downstream of it measured anything.

    Separate from a data-plane result because the two are opposite kinds of event. A denial is
    an observation this family scores; a mode change that did not take is an instrument
    failure, and scoring the trials that follow it would attribute the previous configuration's
    behaviour to the one we believe we set. Raised, caught once in `main`, and turned into
    INCONCLUSIVE records for every case — never into a verdict.
    """


def build_policies(gateway_arn: str, *, echo_action_id: str) -> dict[str, dict[str, Any]]:
    """The three Cedar bodies this script creates, all assembled by `lib/cedar.py`.

    `gateway_arn` is REQUIRED and there is no `None` branch, for the reason
    `f1_config/03_permit_trap.py` documents: `cedar.gateway_resource(None)` returns
    `resource is AgentCore::Gateway`, which is the BASELINE statement. A permissive fallback
    would silently scope all three of these to every gateway in the account — including the six
    pre-existing READY gateways this project is forbidden to touch.
    """
    if not gateway_arn:
        raise ConfigError(
            "F4's policies need the real gateway ARN. cedar.gateway_resource(None) returns "
            "`resource is AgentCore::Gateway`, which would scope every one of these statements "
            "to EVERY gateway in the account, including the six pre-existing READY gateways "
            "this project must not touch")

    # `context.input.text`, NOT `context.output.text`, and the difference is measured rather
    # than assumed. F4-0's calibration matrix (2026-08-11, evidence/.../F4-0/calibration.json)
    # established that `definition.policy` rejects an output path inside an authorization
    # effect with:
    #
    #     Guardrail 'BedrockGuardrails::ContentFilter' references 'context.output' but the
    #     policy has an authorization effect. Use 'context.input.*' data paths for
    #     authorization policies.
    #
    # which is exactly what the document under test says at L332: request authorization uses
    # permit/forbid, output filtering uses the distinct `suppressOutput` effect. This policy is
    # a `forbid`, so it is an authorization policy, so it takes an input path. F4-1 does not
    # care WHICH path — its question is whether a guardrail policy GRANTS, and the answer
    # cannot depend on a path that never matches benign text at threshold 0.2.
    # The `action ==` scope is REQUIRED at runtime, not just at validation. MEASURED
    # 2026-08-11 (run r20260810T130945Z): this statement without the scope CREATES fine
    # (IGNORE_ALL_FINDINGS bypasses the validator that flags unscoped `context.input.*`,
    # see the narrow statement's comment below) — and then denies EVERY request, including
    # the F4-1 mutation cell whose baseline permit was ACTIVE, with
    #
    #     Authorization denied: a guardrail policy could not be evaluated - missing an
    #     attribute. Please retry.
    #
    # even though the request itself carried `text`. An unscoped guardrail is evaluated
    # where `context.input.text` does not exist, the evaluation error is a DENY (fail-closed,
    # same polarity as the narrow policy's parameter-format error), and F4-1's mutation —
    # "baseline permit + guardrail, benign traffic passes" — can never come out TRUE. Scoping
    # to the echo action makes the guardrail evaluable, which is the precondition for F4-1
    # measuring what it registered: whether a guardrail policy GRANTS.
    guardrail = cedar.statement(
        "forbid", resource=cedar.gateway_resource(gateway_arn),
        action=f'action == {cedar.ENTITY_ACTION}::"{echo_action_id}"',
        when_guardrails=cedar.guardrail_condition(
            "ContentFilter", ["HATE"], ["context.input.text"], threshold="0.2"))
    # MEASURED 2026-08-11, F4 smoke, CreatePolicy -> CREATE_FAILED. The obvious form of this
    # statement — `permit(principal, action, resource == <gw>) when { context.input.amount < 500 }`,
    # which is what lib/cedar.py's own F2-1 sample and PREREGISTRATION's F2-1 arm both described —
    # is REJECTED, on three independent counts. All three are recorded in
    # evidence/<run>/f1_config/F1-12/ and each one is a config-surface fact the document under test
    # does not state:
    #
    #  1. AN UNSCOPED `action` MUST TYPE-CHECK AGAINST EVERY ACTION IN THE SCHEMA. Leaving `action`
    #     unconstrained is not "applies to all actions"; it is "must be valid for all actions", and
    #     the validator enumerated them refusing ours:
    #         CallTool, UnknownTool, Http, Mcp, grxecho          -> no `input` attribute AT ALL
    #                                                               ("did you mean `output`?")
    #         InvokeAgent, InvokeLLM                             -> `input` exists but is OPTIONAL
    #         grxecho___echo                                     -> has `input.amount` (optional)
    #         grxecho___delay                                    -> no `amount` ("did you mean `ms`?")
    #         grxecho___fixed                                    -> no `amount` ("did you mean `key`?")
    #     So the context schema is PER-ACTION and is derived from each tool's own input schema —
    #     our Lambda declares `amount:number` on `echo`, `ms` on `delay`, `key` on `fixed`, and
    #     Cedar sees exactly that. Any condition on `context.input.*` therefore REQUIRES an
    #     `action ==` scope. lib/cedar.py's sample had the scope; this statement had dropped it.
    #  2. `input.amount` IS OPTIONAL, so a bare access is "unable to guarantee safety of access to
    #     optional attribute". The validator names the remedy: `context.input has amount && ..`.
    #  3. `amount` IS A CEDAR `decimal`, NOT A `Long`. `< 500` is "unexpected type: expected Long
    #     but saw decimal" — Cedar's decimal type has no `<` operator, only the comparator methods.
    #     A tool parameter declared `number` in an MCP input schema arrives as decimal.
    #
    # F4-4's CASE_GUARDS entry above flagged `context.input.amount` as an UNVERIFIED path and said
    # what would go wrong if it never matched. It is now verified, and the guard cell stays: a
    # statement that CREATES successfully still has to be shown to MATCH.
    narrow = cedar.statement(
        "permit", resource=cedar.gateway_resource(gateway_arn),
        action=f'action == {cedar.ENTITY_ACTION}::"{echo_action_id}"',
        when=(f"context.input has amount && context.input.amount.lessThan("
              f"{cedar.decimal_literal(float(NARROW_AMOUNT_LIMIT))})"))
    forbid = cedar.statement("forbid", resource=cedar.gateway_resource(gateway_arn))

    return {
        POL_GUARDRAIL: {
            "statement": guardrail,
            "why": ("a GUARDRAIL policy in the §3.1 gotcha's sense, and a `forbid` rather than "
                    "a `permit` because that is the point of the gotcha: guardrail policies "
                    "constrain, they do not GRANT. With the baseline permit driven to LOG_ONLY "
                    "this is the only ACTIVE policy on the engine and nothing in the enforced "
                    "set permits anything, which is the condition the document says blocks all "
                    "traffic. The ContentFilter/HATE/context.input.text/0.2 shape is taken "
                    "from lib/cedar.py's own samples rather than invented, because the point "
                    "is that a guardrail policy EXISTS, not that it fires — and a rejected "
                    "CreatePolicy would leave F4-1 unmeasured for a reason F4-1 is not about. "
                    "The input path is F4-0's result, not a preference: an output path in an "
                    "authorization effect is rejected at CreatePolicy")},
        POL_NARROW: {
            "statement": narrow,
            "why": (f"a permit that matches SOME requests and not others, so 'matched no "
                    f"policy' can be the single independent variable. amount < "
                    f"{NARROW_AMOUNT_LIMIT} admits BENIGN_ARGS ({BENIGN_ARGS['amount']}) and "
                    f"excludes UNMATCHED_ARGS ({UNMATCHED_ARGS['amount']}); same tool, same "
                    f"argument names, so the only difference between F4-4's arm and its control "
                    f"is whether a policy could match")},
        POL_FORBID: {
            "statement": forbid,
            "why": ("an unconstrained forbid over the same gateway the baseline permit grants. "
                    "Cedar's forbid-wins rule is what F4-5 tests, and this is the minimal "
                    "statement that puts a permit and a forbid over one request. It is also "
                    "the denial that F4-2, F4-3 and F4-6 all need to exist")},
    }


def plan_names(ac, run_id: str) -> dict[str, str]:
    """Every policy name, validated against the SDK's own pattern before the first create.

    All of them up front, exactly as `f1_config/03_permit_trap.py` does it and for the same
    reason: `check_name` raises locally for free, but a raise discovered at stage 3 would leave
    two stages' worth of measurements that can never be completed into a truth table. Policy
    names take no hyphens (DEV-P2-02), so the run id's own casing travels through unchanged.
    """
    return {key: T.check_name(ac, "CreatePolicy", f"grx_f4_{key}_{run_id}")
            for key in (POL_GUARDRAIL, POL_NARROW, POL_FORBID)}


# --------------------------------------------------------------------------
# the two axes
# --------------------------------------------------------------------------

def _check_update_gateway_shape(ac) -> dict[str, Any]:
    """Does `UpdateGateway` still accept exactly the members this script re-sends?

    UpdateGateway is a REPLACE: a member the live gateway carries and this call omits is a
    member RESET to its default. `UPDATE_GATEWAY_PASSTHROUGH` was derived from botocore 1.43.67,
    and a member added by a future SDK would be silently reset on the first mode switch. That is
    not a hypothetical class of damage: `exceptionLevel` is DEBUG on this testbed, and resetting
    it would change the body of every error message every later phase reads — including F4-6's
    own subject, which is what a denial message contains.

    So the shape is re-derived from the loaded model at run time and compared. An unhandled
    member is FATAL before any mutation, not a warning after one.
    """
    shape = ac.meta.service_model.operation_model("UpdateGateway").input_shape
    live_members = set(shape.members)
    handled = set(UPDATE_GATEWAY_PASSTHROUGH) | {"gatewayIdentifier", "policyEngineConfiguration"}
    unhandled = sorted(live_members - handled)
    absent = sorted(handled - live_members)
    return {
        "sdk": A.sdk_versions(),
        "live_members": sorted(live_members),
        "handled": sorted(handled),
        "unhandled": unhandled,
        "absent_from_model": absent,
        "required": sorted(shape.required_members),
        "ok": not unhandled and not absent,
        "why_checked": (
            "UpdateGateway is a REPLACE, so an omitted member is a reset. A member this SDK "
            "accepts and this script does not re-send would be wiped by the first mode switch; "
            "resetting exceptionLevel alone would change the body of every error message every "
            "later phase reads, including the denial bodies F4-6 measures"),
    }


def _engine_cfg_of(gw: dict) -> dict:
    return dict((gw.get("policyEngineConfiguration") or {}))


def _set_engine_mode(ac, store: EvidenceStore, *, gateway_id: str, engine_arn: str,
                     mode: str) -> dict[str, Any]:
    """Drive the ENGINE axis, and verify from two independent reads.

    The live configuration is read and re-sent whole (see `_check_update_gateway_shape`), with
    `policyEngineConfiguration` replaced by `{arn, mode}` — both members, because
    `GatewayPolicyEngineConfiguration` marks both required and a half-filled structure would be
    a validation error rather than a mode change.

    The ARN is re-sent as the ARN that is ALREADY there, read live. It is never taken from the
    ledger and never re-pointed: `infra/06_verify.py` pins the engine ARN precisely because
    nothing in the plan legitimately points this gateway at a different engine, and a mismatch
    here means something outside this script moved it — which makes every trial after this point
    a measurement of an unknown configuration. That case raises rather than continuing.

    Verification is `UpdateGateway`'s own response AND a separate `GetGateway`, because those
    are two calls and a single one could report an accepted intent rather than a settled state.
    """
    cur = capture(store, "get_gateway", ac, gatewayIdentifier=gateway_id)
    if not cur.ok:
        raise ConfigError(f"GetGateway failed before an engine-mode change: "
                          f"{cur.error_code}: {cur.error_message}")
    cfg = _engine_cfg_of(cur.response)
    live_arn, live_mode = cfg.get("arn", ""), cfg.get("mode", "")
    if not live_arn:
        raise ConfigError(
            "the main gateway has NO policy engine attached. Every cell in this family assumes "
            "the Phase-2 engine is attached; with none, a denial could not be a policy decision")
    if live_arn != engine_arn:
        raise ConfigError(
            f"the gateway points at a policy engine this script did not expect. Expected the "
            f"ARN read at startup, found a different one. Something outside F4 re-pointed the "
            f"gateway, so every trial from here would measure an unknown configuration")

    out: dict[str, Any] = {"axis": "engine", "from": live_mode, "to": mode, "changed": False,
                           "verified": live_mode == mode, "engine_arn_unchanged": True}
    if live_mode == mode:
        out["why_no_call"] = (
            "the gateway is already in this mode, read live rather than assumed from the "
            "ledger. Sending an UpdateGateway to set a field to its current value would be a "
            "mutation with no measurement behind it, and every mutation on a shared testbed is "
            "a chance to reset a member this script does not re-send")
        return out

    params: dict[str, Any] = {k: cur.response[k] for k in UPDATE_GATEWAY_PASSTHROUGH
                             if k in cur.response}
    params["gatewayIdentifier"] = gateway_id
    params["policyEngineConfiguration"] = {"arn": engine_arn, "mode": mode}
    out["resent_members"] = sorted(k for k in params if k != "gatewayIdentifier")

    A.limiter().wait("UpdateGateway")
    urec = capture(store, "update_gateway", ac, **params)
    if not urec.ok:
        raise ConfigError(f"UpdateGateway({mode}) failed: "
                          f"{urec.error_code}: {urec.error_message}")
    out["changed"] = True
    out["update_response_mode"] = _engine_cfg_of(urec.response).get("mode", "")
    out["request_id"] = urec.request_id

    try:
        gw = wait_ready(ac, gateway_id)
    except TimeoutError as exc:
        raise ConfigError(f"the gateway did not return to READY after an engine-mode change to "
                          f"{mode}: {exc}") from exc
    out["status_after"] = (gw or {}).get("status")

    back = capture(store, "get_gateway", ac, gatewayIdentifier=gateway_id)
    if not back.ok:
        raise ConfigError(f"the independent readback GetGateway failed: {back.error_code}")
    back_cfg = _engine_cfg_of(back.response)
    out["readback_mode"] = back_cfg.get("mode", "")
    out["readback_arn_matches"] = back_cfg.get("arn", "") == engine_arn
    out["verified"] = (out["update_response_mode"] == mode
                       and out["readback_mode"] == mode
                       and out["readback_arn_matches"])
    if not out["verified"]:
        raise ConfigError(
            f"the engine mode did not settle to {mode}: UpdateGateway reported "
            f"{out['update_response_mode']!r}, an independent GetGateway reported "
            f"{out['readback_mode']!r}, arn_matches={out['readback_arn_matches']}")
    return out


def _policy_mode_now(ac, *, engine_id: str, policy_id: str) -> tuple[str, str]:
    """`(lifecycle status, enforcementMode)` from a RAW call — no evidence record.

    Raw on purpose. This runs in a poll loop, and one archived record per poll would bury the
    calls that are actually evidence under dozens that are just waiting. The settled value is
    re-read through `capture` once, below, and that read is the record.
    """
    got = ac.get_policy(policyEngineId=engine_id, policyId=policy_id)
    return str(got.get("status") or ""), str(got.get("enforcementMode") or "")


def _set_policy_mode(ac, store: EvidenceStore, *, engine_id: str, policy_id: str,
                     logical: str, mode: str,
                     sleep=time.sleep) -> dict[str, Any]:
    """Drive the POLICY axis for one policy, and verify by readback.

    `definition` is NOT re-sent. Three facts support that, and the third is a measurement this
    script makes before it ever touches the shared baseline policy:

      * `UpdatePolicy`'s input shape requires only `policyEngineId` and `policyId`, so the Cedar
        body is not a required member of an update.
      * `name` is absent from `UpdatePolicy:in` ENTIRELY, which is evidence the operation is a
        partial update rather than a full replace: a replace that could not carry the name could
        not express a rename, and every replace-shaped operation in this API can.
      * `_probe_definition_preserved` runs the omit-definition update against a SACRIFICIAL
        policy this script created, and reads the Cedar body back. Inference becomes measurement
        before the risk is taken on a resource every later phase depends on.

    Re-sending it would re-run validation, and DC-1 is the finding that this exact baseline
    statement FAILS validation without IGNORE_ALL_FINDINGS. An UpdatePolicy that re-validated
    the baseline could leave the shared testbed without the permit — which is a worse outcome
    than any measurement in this family is worth.
    """
    status_before, mode_before = _policy_mode_now(ac, engine_id=engine_id, policy_id=policy_id)
    out: dict[str, Any] = {"axis": "policy", "logical": logical, "from": mode_before,
                           "to": mode, "status_before": status_before, "changed": False,
                           "verified": mode_before == mode,
                           "definition_resent": False}
    if mode_before == mode:
        out["why_no_call"] = ("already in this mode, read live. See `_set_engine_mode` — an "
                              "update with no measurement behind it is pure risk")
        return out

    A.limiter().wait("UpdatePolicy")
    urec = capture(store, "update_policy", ac,
                   policyEngineId=engine_id, policyId=policy_id, enforcementMode=mode,
                   # `validationMode` on an UPDATE, not just on a create. F1-11 measured on
                   # 2026-08-11 that `UpdatePolicy` re-validates the STORED Cedar body even when
                   # the request carries no `definition` member at all, and drove the shared
                   # baseline policy into UPDATE_FAILED with the two `Overly Permissive` findings
                   # DC-1 recorded at create time. Omitting `definition` avoids REPLACING the
                   # body; it does not avoid VALIDATING it. The mutation in F1-11 removed only
                   # this member and reproduced the failure, so it is load-bearing rather than
                   # defensive. See evidence/<run>/f1_config/F1-11/summary.json.
                   validationMode=F4_VALIDATION_MODE)
    if not urec.ok:
        raise ConfigError(f"UpdatePolicy({logical} -> {mode}) failed: "
                          f"{urec.error_code}: {urec.error_message}")
    out["changed"] = True
    out["request_id"] = urec.request_id
    out["update_response_mode"] = urec.response.get("enforcementMode")

    deadline = time.monotonic() + MODE_READBACK_TIMEOUT_S
    polls = 0
    while True:
        polls += 1
        st, md = _policy_mode_now(ac, engine_id=engine_id, policy_id=policy_id)
        if md == mode and st in PE_TERMINAL_OK:
            break
        if time.monotonic() >= deadline:
            raise ConfigError(
                f"policy {logical} did not settle to enforcementMode={mode} inside "
                f"{MODE_READBACK_TIMEOUT_S}s (last read: status={st!r} mode={md!r})")
        sleep(MODE_READBACK_SLEEP_S)
    out["polls"] = polls

    back = capture(store, "get_policy", ac, policyEngineId=engine_id, policyId=policy_id)
    if not back.ok:
        raise ConfigError(f"the confirming GetPolicy for {logical} failed: {back.error_code}")
    out["readback_mode"] = back.response.get("enforcementMode")
    out["readback_status"] = back.response.get("status")
    out["verified"] = out["readback_mode"] == mode and out["readback_status"] in PE_TERMINAL_OK
    if not out["verified"]:
        raise ConfigError(f"policy {logical} readback disagrees: mode={out['readback_mode']!r} "
                          f"status={out['readback_status']!r}, wanted {mode} + ACTIVE")
    return out


def _wait_policy_terminal(ac, *, engine_id: str, policy_id: str,
                          timeout_s: float | None = None,
                          sleep_s: float = MODE_READBACK_SLEEP_S,
                          sleep=time.sleep) -> list[str]:
    """Poll a policy to a terminal state. Returns the status sequence observed, never raises.

    A POLICY MUTATION IS ASYNCHRONOUS, and this invariant was learned three separate times in
    one session before it was written down once:

      * `DeletePolicy` on a policy in `UPDATING` returns `ConflictException`. Four calibration
        probe policies leaked onto the shared engine that way.
      * a `GetPolicy` read-back issued straight after `UpdatePolicy` returns an unsettled body,
        which made `_probe_definition_preserved` report `preserved=False` — a claim about the
        SERVICE manufactured by a race in the HARNESS.
      * a stage policy that could not be deleted left `stage_policy_ids` non-empty, so `_restore`
        returned `ok=False` while its own 15 blocking checks all PASSED.

    The returned list, not just the final value, goes into the evidence: a policy observed
    `UPDATING -> UPDATING -> ACTIVE` is a different fact from one observed `ACTIVE` on the first
    poll, and the difference is the propagation lag every later timing claim inherits.

    `DELETE_FAILED` and `UPDATE_FAILED` are terminal. They are not success, but a failed
    mutation has settled, and a caller that waited only for `ACTIVE` would spin the full timeout
    on a policy that is never going to reach it.
    """
    budget = MODE_READBACK_TIMEOUT_S if timeout_s is None else timeout_s
    deadline = time.monotonic() + budget
    seen: list[str] = []
    while True:
        try:
            st, _ = _policy_mode_now(ac, engine_id=engine_id, policy_id=policy_id)
        except Exception as exc:                                          # noqa: BLE001
            # ResourceNotFoundException included: a policy that is gone has settled, and for a
            # delete path that is the goal state rather than an error.
            st = "GONE" if "ResourceNotFound" in type(exc).__name__ or \
                           "ResourceNotFound" in str(exc) else f"POLL_ERROR:{type(exc).__name__}"
            seen.append(st)
            return seen
        seen.append(st)
        if st in POLICY_TERMINAL_FOR_MUTATION:
            return seen
        if time.monotonic() + sleep_s >= deadline:
            return seen
        sleep(sleep_s)


def _definition_statement_of(body: dict[str, Any]) -> tuple[str, str]:
    """The Cedar text out of a `GetPolicy` response, and WHICH member carried it.

    `definition` has two members and F4-0 measured that they are different parsers, so a reader
    that hardcodes one member is asserting which one the service echoes. That assertion was
    wrong once already: this function's predecessor read only `definition.cedar` while
    `_create_stage_policy` had been switched to SEND `definition.policy`, so it compared the
    statement against an empty string and called the body "not preserved".

    The member name is returned alongside the text and recorded, because "the service normalizes
    `policy` into `cedar` on read" is itself a config-surface fact about this API — one the
    document under test does not state either way.
    """
    defn = body.get("definition") or {}
    for member in ("policy", "cedar"):
        stmt = ((defn.get(member) or {}).get("statement") or "")
        if stmt:
            return str(stmt), member
    return "", ",".join(sorted(defn.keys())) or "<no definition member>"


def _probe_definition_preserved(ac, store: EvidenceStore, *, engine_id: str, policy_id: str,
                                logical: str, statement: str) -> dict[str, Any]:
    """Does an `UpdatePolicy` that omits `definition` leave the Cedar body intact?

    Run ONCE, against the first policy this script creates, before the shared baseline policy is
    ever updated. The whole policy axis rests on omitting `definition`, and the argument for
    omitting it was an inference from the input shape. An inference is not a measurement, and
    the resource the inference would be tested on in production is the one every later phase
    depends on — so it is tested here, on a policy that is disposable by construction.

    The update sets `enforcementMode` to the value the policy already has, so the probe changes
    nothing even if it succeeds: it exercises the omit-definition path and nothing else.
    """
    A.limiter().wait("UpdatePolicy")
    urec = capture(store, "update_policy", ac, policyEngineId=engine_id, policyId=policy_id,
                   enforcementMode=POLICY_LOG_ONLY,
                   validationMode=F4_VALIDATION_MODE)   # see `_set_policy_mode` and F1-11
    out: dict[str, Any] = {"probe": "update_policy_without_definition",
                           "logical": logical, "http_ok": urec.ok,
                           "http_status": urec.http_status, "request_id": urec.request_id,
                           "error_code": urec.error_code}
    if not urec.ok:
        out.update(ok=False, why=("UpdatePolicy without `definition` was REJECTED. The policy "
                                  "axis cannot be driven this way, and re-sending the Cedar "
                                  "body would re-validate the baseline statement that DC-1 "
                                  "shows fails validation"))
        return out

    # WAIT before reading. The first version of this probe read the body back immediately and
    # got `preserved=False, status='UPDATING'` — it had measured a policy mid-update and would
    # have reported "UpdatePolicy destroys the definition", which is a claim about the SERVICE
    # drawn from a race in the HARNESS. UpdatePolicy is asynchronous; a read that does not wait
    # for a terminal status is reading an intermediate state.
    out["status_waits"] = _wait_policy_terminal(ac, engine_id=engine_id, policy_id=policy_id)
    out["status_at_readback"] = out["status_waits"][-1] if out["status_waits"] else ""

    back = capture(store, "get_policy", ac, policyEngineId=engine_id, policyId=policy_id)
    if not back.ok:
        out.update(ok=False, why=f"the confirming GetPolicy failed: {back.error_code}")
        return out
    live_stmt, echoed_member = _definition_statement_of(back.response)
    out.update(
        statement_before=statement,
        statement_after=live_stmt,
        # Which member the service echoes is recorded, not assumed. We SEND
        # `definition.policy`; if GetPolicy returns the body under `cedar`, the service
        # normalizes between the two and the earlier `cedar`-only read-back would have compared
        # against an empty string and called it "not preserved" for the second time.
        echoed_definition_member=echoed_member,
        status_after=back.response.get("status"),
        enforcement_mode_after=back.response.get("enforcementMode"),
        preserved=live_stmt.strip() == statement.strip(),
        status_ok=back.response.get("status") in PE_TERMINAL_OK)
    out["ok"] = bool(out["preserved"] and out["status_ok"])
    out["why"] = (
        # This sentence used to end "...so the policy axis can be driven without re-validating
        # the baseline statement", which F1-11 measured to be FALSE. `UpdatePolicy` DOES
        # re-validate the stored body even with no `definition` member in the request; what makes
        # the update survive is that this probe — and every `_set_policy_mode` call — now sends
        # `validationMode=IGNORE_ALL_FINDINGS`. Recording the reason accurately matters because a
        # reader of this output would otherwise conclude the omission is what protects the body,
        # which is exactly the belief that drove the shared baseline into UPDATE_FAILED.
        f"an UpdatePolicy carrying (policyEngineId, policyId, enforcementMode, "
        f"validationMode={F4_VALIDATION_MODE}) and NO `definition` member left the Cedar body "
        f"byte-identical and the policy ACTIVE. Note what this does and does not show: the body "
        f"is not REPLACED, but per F1-11 it is still VALIDATED, so `validationMode` is what makes "
        f"the policy axis drivable on a statement that carries findings — not the omission"
        if out["ok"] else
        f"the omit-definition update did NOT preserve the policy: preserved="
        f"{out['preserved']}, status={out['status_after']!r}. Driving the shared baseline "
        f"policy this way could strand the testbed without its permit")
    return out


# --------------------------------------------------------------------------
# policy lifecycle
# --------------------------------------------------------------------------

def _run_definition_probe(ac, store: EvidenceStore, state: T.State, *,
                          engine_id: str, run_id: str) -> dict[str, Any]:
    """Create a subject that FAILS validation, probe the omit-definition update on it, delete it.

    The subject is a policy carrying `cedar.baseline_permit()` — byte-identical to the shared
    baseline's statement, and therefore carrying the same two `Overly Permissive` findings.

    THIS IS THE POINT, and it is a correction. The first version of this probe ran against F4's
    own guardrail policy, whose narrowly-scoped `forbid` passes validation cleanly. A probe for
    "does the update re-validate the stored body?" run on a statement with no findings CANNOT
    fail: there is nothing for a re-validation to reject. So the probe passed, reported
    `preserved=True` and `status=ACTIVE`, and the very next `UpdatePolicy` — the same call shape,
    against the baseline — drove the shared testbed into UPDATE_FAILED. F1-11 then reproduced the
    mechanism in both directions.

    The lesson generalizes past this script: a sacrificial subject must be sacrificial IN THE
    PROPERTY UNDER TEST, not merely disposable. A probe whose subject cannot exhibit the hazard is
    not a weak test of the hazard, it is a test of something else that returns a reassuring
    answer.

    Created in LOG_ONLY so it never enforces, and deleted before any cell runs — `_apply_config`
    refuses a cell that does not declare a mode for every policy on the engine, so a leaked probe
    policy would halt the run rather than silently join the enforced set.
    """
    statement = cedar.baseline_permit()
    name = T.check_name(ac, "CreatePolicy", f"grx_f4dp_{run_id}")
    logical = "f4_defprobe"

    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac,
                  name=name, policyEngineId=engine_id,
                  definition={"policy": {"statement": statement}},
                  description=("F4 omit-definition probe subject: the baseline permit, so the "
                               "subject carries the same validation findings as the resource "
                               "the probe protects"),
                  validationMode=F4_VALIDATION_MODE,
                  enforcementMode=POLICY_LOG_ONLY)
    if not rec.ok:
        return {"probe": "update_policy_without_definition", "ok": False,
                "why": (f"the probe SUBJECT could not be created ({rec.error_code}: "
                        f"{rec.error_message}), so the omit-definition path was never "
                        f"exercised on a statement that carries findings"),
                "subject_created": False}
    pid = rec.response.get("policyId") or ""
    state.record(T.Resource(
        kind="policy", logical=logical, name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid, "statement": statement},
        arn=rec.response.get("policyArn", ""), delete_priority=40,
        notes=("F4 omit-definition probe subject. Registered before its status is polled: "
               "`policy` takes no tags, so this ledger entry is the only channel that can "
               "find it.")))
    try:
        live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
    except TimeoutError as exc:
        return {"probe": "update_policy_without_definition", "ok": False,
                "why": f"the probe subject never reached a terminal status: {exc}",
                "subject_created": True, "policy_id": pid}
    if live.get("status") not in PE_TERMINAL_OK:
        return {"probe": "update_policy_without_definition", "ok": False,
                "why": (f"the probe subject settled {live.get('status')} rather than ACTIVE "
                        f"(reasons={live.get('statusReasons')}). DC-1 says this statement needs "
                        f"validationMode={F4_VALIDATION_MODE} at CREATE time, which was sent, "
                        f"so a failure here is a finding in its own right"),
                "subject_created": True, "policy_id": pid,
                "subject_status": live.get("status"),
                "subject_status_reasons": live.get("statusReasons")}

    out = _probe_definition_preserved(ac, store, engine_id=engine_id, policy_id=pid,
                                     logical=logical, statement=statement)
    out["subject_created"] = True
    out["subject_is_baseline_statement"] = True
    out["subject_carries_validation_findings"] = True
    out["subject_why"] = ("byte-identical to cedar.baseline_permit(), so the subject carries the "
                          "same two Overly Permissive findings as the resource the probe exists "
                          "to protect")
    out["deleted"] = _delete_stage_policy(ac, store, state, engine_id=engine_id,
                                          key="defprobe", policy_id=pid)
    if not out["deleted"]:
        out["ok"] = False
        out["why"] = (out.get("why", "") + " | and the probe SUBJECT could not be deleted, so it "
                      "would join the enforced set that every later cell declares")
    return out


def _create_stage_policy(ac, store: EvidenceStore, state: T.State, *, engine_id: str,
                         key: str, name: str, spec: dict[str, Any],
                         registry: dict[str, str] | None = None) -> str:
    """Create one stage policy in LOG_ONLY and poll it to ACTIVE. Returns its policy id.

    `registry` is the caller's `stage_policy_ids`, and it is passed IN rather than assigned from
    the return value because the return value does not exist on the path that matters. The
    caller used to write `stage_policy_ids[key] = _create_stage_policy(...)`; when the settle
    check below raised `ConfigError`, that assignment never ran, teardown iterated an empty
    registry, and the policy survived the run. Measured on 2026-08-11: a `narrow` policy
    reached CREATE_FAILED, all 15 blocking checks reported PASS (they assert the testbed is
    INTACT, and an extra failed policy violates none of them), and the leak was visible only in
    `state.json`. Registering inside the function makes the write happen before anything that
    can raise.

    LOG_ONLY at creation, always. A policy created ACTIVE would change what the gateway does at
    the moment of creation rather than at the moment a cell declares it, and the cells that run
    before it are measuring the enforced set — so a create that enforced would be an undeclared
    variable inserted between two arms.

    Registered in the ledger the moment `CreatePolicy` returns, before its status is polled: a
    policy in any state is a resource, `policy` is structurally untaggable (CreatePolicy accepts
    no `tags` member at all), and this script's `finally` is therefore the ONLY teardown channel
    that can find it. A kill during the poll must leave it in `state.json` or it is invisible.
    """
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac,
                  name=name, policyEngineId=engine_id,
                  # `policy`, NOT `cedar`. `CreatePolicy.definition` has both members and they
                  # are DIFFERENT PARSERS, which F4-0 measured on 2026-08-11: `cedar` is plain
                  # Cedar and rejects `when guardrails` as an unexpected token and
                  # `BedrockGuardrails::ContentFilter` as "not a valid function", while `policy`
                  # accepts both and validates data paths semantically. Every CreatePolicy in
                  # this repository sent `cedar`, which worked only because every statement sent
                  # before F4 was plain Cedar. See DEVIATIONS.md — this also leaves DC-1
                  # (F1-3's validation finding) conditional on the request shape it was measured
                  # under, which is an open item, not a settled one.
                  definition={"policy": {"statement": spec["statement"]}},
                  description=f"F4 truth table: {key}",
                  validationMode=F4_VALIDATION_MODE,
                  enforcementMode=POLICY_LOG_ONLY)
    if not rec.ok:
        raise ConfigError(f"CreatePolicy({key}) failed: {rec.error_code}: {rec.error_message}")
    pid = rec.response.get("policyId")
    if not pid:
        raise ConfigError(f"CreatePolicy({key}) returned no policyId")

    if registry is not None:
        registry[key] = pid          # BEFORE the ledger write and before any poll that can raise

    state.record(T.Resource(
        kind="policy", logical=f"f4_{key}", name=name,
        service="bedrock-agentcore-control",
        delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid,
             "enforcement_mode_at_create": POLICY_LOG_ONLY,
             "validation_mode_sent": F4_VALIDATION_MODE,
             "statement": spec["statement"]},
        arn=rec.response.get("policyArn", ""),
        delete_priority=40,
        notes=(f"F4 stage policy {key}. Registered before its status was polled because "
               f"`policy` takes no tags, so this ledger entry and this script's finally are "
               f"the only channels that can ever find it")))

    try:
        live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
    except TimeoutError as exc:
        raise ConfigError(f"policy {key} never reached a terminal status: {exc}") from exc
    if live.get("status") not in PE_TERMINAL_OK:
        raise ConfigError(
            f"policy {key} settled {live.get('status')} rather than ACTIVE "
            f"(reasons={live.get('statusReasons')}). An inert policy is not the enforced set "
            f"the cells declare, so nothing downstream would be measuring what it says")
    print(f"    created policy {key} -> {pid} (ACTIVE, {POLICY_LOG_ONLY})")
    return pid


def _delete_stage_policy(ac, store: EvidenceStore, state: T.State, *, engine_id: str,
                         key: str, policy_id: str, sleep=time.sleep) -> bool:
    """Delete one stage policy. Never raises: this runs in teardown paths.

    Waits for a terminal status first, then retries. `DeletePolicy` against a policy still in
    `UPDATING` returns `ConflictException`, and a single unretried attempt is how this script
    left a policy on the shared engine while reporting all 15 blocking checks green: the checks
    assert the testbed is INTACT, and a leaked extra policy in LOG_ONLY does not violate any of
    them. Only `stage_policy_ids` still being non-empty caught it.

    The retry loop is not belt-and-braces. The first attempt can lose the race legitimately: the
    status poll and the delete are two calls, and a policy can be re-driven into `UPDATING` by
    the propagation of a change made before the poll.
    """
    waits = _wait_policy_terminal(ac, engine_id=engine_id, policy_id=policy_id, sleep=sleep)
    last = waits[-1] if waits else ""
    if last == "GONE":
        state.drop("policy", f"f4_{key}")
        print(f"    policy {key} already gone (status polls: {'->'.join(waits)})")
        return True
    if last not in POLICY_TERMINAL_FOR_MUTATION:
        print(f"    WARN policy {key} never settled (status polls: {'->'.join(waits)}); "
              f"attempting the delete anyway", file=sys.stderr)

    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac, policyEngineId=engine_id, policyId=policy_id)
        if rec.ok:
            state.drop("policy", f"f4_{key}")
            print(f"    deleted policy {key}"
                  + (f" (attempt {attempt})" if attempt > 1 else ""))
            return True
        errors.append(f"attempt {attempt}: {rec.error_code}")
        if rec.error_code == "ResourceNotFoundException":
            state.drop("policy", f"f4_{key}")
            print(f"    policy {key} was already deleted (attempt {attempt})")
            return True
        if attempt < DELETE_ATTEMPTS:
            _wait_policy_terminal(ac, engine_id=engine_id, policy_id=policy_id,
                                  timeout_s=DELETE_RETRY_SETTLE_S, sleep=sleep)
            sleep(DELETE_SLEEP_S)

    print(f"    WARN policy {key} not deleted after {DELETE_ATTEMPTS} attempts "
          f"({'; '.join(errors)}). It is in state.json, which is the ONLY channel that can find "
          f"it — `policy` takes no tags, so the tag sweep cannot.", file=sys.stderr)
    return False


# --------------------------------------------------------------------------
# one configuration, one cell
# --------------------------------------------------------------------------

def _apply_config(ac, store: EvidenceStore, *, cell: dict[str, Any], gateway_id: str,
                  engine_arn: str, engine_id: str, baseline_policy_id: str,
                  stage_policy_ids: dict[str, str],
                  sleep=time.sleep) -> dict[str, Any]:
    """Put the live testbed into exactly the configuration this cell declares.

    Refuses a cell whose `modes` does not name EVERY policy that currently exists on the engine
    among the ones this family controls. The enforced policy set is the independent variable of
    the whole family; a policy present but unnamed would be a variable nobody declared, and the
    refusal is what makes the declaration load-bearing rather than documentation. It also
    catches a stage teardown that did not happen, which would otherwise show up as an
    unexplained verdict two cells later.
    """
    declared = set(cell["modes"])
    present = {"baseline"} | set(stage_policy_ids)
    if declared != present:
        raise ConfigError(
            f"cell {cell['key']} declares modes for {sorted(declared)} but the policies that "
            f"exist right now are {sorted(present)}. Every policy that exists must have a "
            f"declared mode: an undeclared one is a variable nobody controlled, and the "
            f"difference here also means a stage policy outlived its stage")

    engine = _set_engine_mode(ac, store, gateway_id=gateway_id, engine_arn=engine_arn,
                              mode=cell["engine"])
    policies = []
    for logical, mode in sorted(cell["modes"].items()):
        pid = baseline_policy_id if logical == "baseline" else stage_policy_ids[logical]
        policies.append(_set_policy_mode(ac, store, engine_id=engine_id, policy_id=pid,
                                         logical=logical, mode=mode, sleep=sleep))

    # A FIXED dwell, and deliberately not a poll. See SETTLE_DWELL_S: a loop that waited until
    # the gateway behaved as the document predicts could never observe a refutation, because the
    # refutation is exactly the outcome it would keep waiting through.
    print(f"    settling {SETTLE_DWELL_S:.0f}s (fixed; never conditioned on a data-plane "
          f"outcome)")
    sleep(SETTLE_DWELL_S)
    return {"cell": cell["key"], "engine": engine, "policies": policies,
            "dwell_s": SETTLE_DWELL_S,
            "why_fixed_dwell": (
                "a settle loop conditioned on the data plane would poll until the gateway "
                "agreed with the document. `trial_index` is on every row so a propagation lag "
                "longer than this dwell shows up as adverse events clustered at the start of a "
                "cell rather than as an unexplained verdict")}


def _one_call(client, cell: dict[str, Any], *, trial_id: str, trial_index: int,
              policy_ids: tuple[str, ...], tool_name: str) -> dict[str, Any]:
    """One `tools/call`, classified against this cell's own prediction.

    `tool_name` is the FULL MCP tool name — `<targetName>___<toolName>`, e.g. `grxecho___echo` —
    resolved from the ledger by `main`, exactly as `infra/08_smoke.py` does it. It is a required
    argument with no default because the bare short name is a silent failure, not a loud one:
    sending `echo` returns HTTP 200 with a JSON-RPC `-32602 "Unknown tool: echo"`, which is not a
    transport error and not a denial. Measured on 2026-08-11, all 8 cells ran to completion that
    way, every policy was created and deleted correctly, all 15 blocking checks passed, and every
    trial was recorded — with `n_usable = 0`, because `_usable` correctly refused to read a
    `jsonrpc_error` as an answer to "was this allowed or denied". A cell that predicts `denied`
    would otherwise have been satisfied by a request that never reached the policy engine.

    F4-6's classification is computed HERE, from the full `Decision.text`, and stored on the
    row. It is not re-derived at analysis time: `to_json` clips `text` at 2000 characters, so a
    re-derivation could report "the message names no policy id" as a property of our own
    serializer. `text_archived_complete` records, per row, whether that clip actually bit.
    """
    A.limiter().wait("InvokeGateway")
    d = client.call_tool(tool_name, dict(ARGS_BY_KEY[cell["args"]]))

    if cell["expect"] == "denied":
        adverse, why = _classify_denied_is_expected(d)
    else:
        adverse, why = _classify_allowed_is_expected(d)

    f6_adverse, f6_why, f6_detail = False, "", {}
    if d.outcome == "policy_denied":
        f6_adverse, f6_why, f6_detail = _classify_f4_6(d, policy_ids)

    text_len = len(d.text or "")
    return _row(
        d, hit=adverse, trial_id=trial_id,
        trial_index=trial_index,
        cell=cell["key"], expect=cell["expect"], why_hit=why,
        engine_mode=cell["engine"], policy_modes=dict(cell["modes"]),
        args_key=cell["args"],
        f4_6_adverse=f6_adverse, f4_6_why=f6_why, f4_6_detail=f6_detail,
        # Only ever set on PROOF of truncation, never on suspicion. `_f4_6_from_row` treats the
        # flag as "unusable", and F4-6's predicted result is the adverse one — so a flag raised
        # on suspicion would systematically DROP refutations and bias the family toward the
        # document. For the `policy_denied` path `lib/mcp.classify` builds `text` from the whole
        # content array, so this is currently unreachable by construction; it is the guard for a
        # shape where that stops being true.
        f4_6_indeterminate_truncation=False,
        text_len=text_len,
        text_archived_complete=text_len <= TEXT_ARCHIVE_LIMIT)


def _run_cell(fc, store: EvidenceStore, *, cell: dict[str, Any], gateway_url: str,
              run_id: str, region: str, n: int, session_timeout_s: int,
              policy_ids: tuple[str, ...], cp_root: Path | None,
              is_smoke: bool, tool_name: str) -> C.Checkpoint:
    """Send this cell's trials and return its checkpoint.

    A fresh MCP session per cell, with the cell key in the policy session id, so the session is
    never shared across two configurations — a reused session would make "which configuration
    was in force" a property of session state rather than of the axis we set.

    `set_meta` carries the configuration in `qualifiers`. That is the whole point: `DESIGN_KEYS`
    drift raises once any trial is recorded, so a resumed run that had been reconfigured cannot
    silently append trials from a different configuration to the same file.
    """
    cp = C.Checkpoint(case_id=CHECKPOINT_CASE, cell=cell["key"],
                      root=cp_root or Path("results") / "checkpoints")
    cp.load()
    cp.set_meta(
        source="gateway_tools_call",
        qualifiers=(f"engine={cell['engine']};"
                    + ";".join(f"{k}={v}" for k, v in sorted(cell["modes"].items()))),
        output_scope="tool_result",
        guardrail_version="none:policy-embedded-guardrail-functions",
        region=region,
        corpus=cell["args"],
        is_smoke=is_smoke,
        operation="InvokeGateway")

    # A transport failure at handshake time is an INSTRUMENT failure, not a result, so it is
    # translated into `ConfigError` and travels the same INCONCLUSIVE path as a mode change that
    # did not land. Before 2026-08-11 it escaped `main`'s handler as a traceback with rc=1, which
    # by this repo's exit-code convention means "an unclassified hit" — i.e. a broken client read
    # as a finding about the document. It also read as a gateway problem: the actual cause was
    # that `M.policy_session_id` emitted `enforce__guardrail_only__benign`, and the gateway
    # rejects `_` in that header (see lib/mcp.POLICY_SESSION_GRAMMAR), answering with a JSON-RPC
    # error about the request BODY. Both halves are fixed; this handler is the half that keeps a
    # future transport fault from being scored.
    try:
        client = M.client_for(gateway_url, fc, store=store,
                              policy_session_id=M.policy_session_id(run_id, cell["key"]),
                              session_timeout_s=session_timeout_s)
    except M.McpTransportError as exc:
        raise ConfigError(f"cell {cell['key']}: the MCP client could not be constructed, so no "
                          f"trial in this cell measured anything: {exc}") from exc
    try:
        try:
            client.initialize()
        except M.McpTransportError as exc:
            raise ConfigError(f"cell {cell['key']}: MCP initialize failed, so no trial in this "
                              f"cell measured anything. This is a transport fault, NOT a policy "
                              f"denial — a denial is HTTP 200 with result.isError (see F4-6): "
                              f"{exc}") from exc
        for i in range(1, n + 1):
            tid = f"t{i:04d}"
            if cp.is_done(tid):
                continue
            client.refresh_if_stale()
            cp.run_trial(tid, lambda t=tid, k=i: _one_call(
                client, cell, trial_id=t, trial_index=k, policy_ids=policy_ids,
                tool_name=tool_name))
            cp.save()
            if i % 20 == 0 or i == n:
                # properties, not methods — `results()`/`failures()` next door ARE methods, which
                # is why this was wrong for 3 trials and would have been wrong for 120.
                print(f"      {i}/{n} done={cp.n_done} failed={cp.n_failed}")
    finally:
        client.close()
        cp.save()
    return cp


# --------------------------------------------------------------------------
# tallies and verdicts
# --------------------------------------------------------------------------

def _tally(case_id: str, cell_key: str, cp: C.Checkpoint, planned_n: int,
           *, role: str) -> dict[str, Any]:
    """One cell's counts, in the shape `require_measured` and `obs_zero_events` consume.

    `arms.tally` is not reused: it requires an `ArmSpec`, which is an ApplyGuardrail corpus arm,
    and it computes `n_usable` as "every row that was recorded". This family needs `n_usable` to
    mean "every row that ANSWERS THIS CASE'S QUESTION", which is case-dependent — F4-6's
    question is about the shape of denials, so a trial that was allowed is not a lower-precision
    answer to it, it is not an answer. The shape of the returned dict is identical so that the
    gate reads both kinds of arm the same way.
    """
    rows = list(cp.results().values())
    if case_id == "F4-6":
        judged = [(r, _f4_6_from_row(r)) for r in rows]
        usable = [r for r, (_a, _w, u) in judged if u]
        x = sum(1 for _r, (a, _w, u) in judged if u and a)
    else:
        usable = [r for r in rows if _usable(_decision_from_row(r), case_id)]
        x = sum(1 for r in usable if r.get("hit"))
    fails = cp.failures()
    return {
        "case_id": case_id, "arm": f"{role}:{cell_key}", "cell": cell_key, "role": role,
        "corpus": cell_key, "planned_n": planned_n,
        "n_attempted": planned_n,
        "n_usable": len(usable),
        "x": x,
        "n_failed": len(fails),
        "failure_codes": sorted({v.get("error_code", "") for v in fails.values()}),
        "n_recorded": len(rows),
        "n_unclassified": sum(1 for r in rows if r.get("unclassified")),
        "rows": usable,
        "checkpoint": str(cp.path),
    }


def _inversion(tallies_by_cell: dict[str, dict], cell_key: str | None) -> tuple[bool | None, dict]:
    """Did the mutation cell come out the way its own prediction says?

    `None` when there is nothing to judge. It is not `False`: `oracle.evaluate` turns
    `mutation_inverted=False` into a FALSE verdict unconditionally — "the document is wrong" —
    and an absent measurement is not a refutation. In practice `None` should be unreachable,
    because a mutation cell is in its case's tally list and `require_measured` returns rc 2
    before any verdict if that cell did not complete.
    """
    if not cell_key:
        return None, {"cell": None, "why": "this case's seal names no mutation cell"}
    t = tallies_by_cell.get(cell_key)
    if t is None or t["n_usable"] == 0:
        return None, {"cell": cell_key, "n_usable": 0,
                      "why": ("the mutation cell produced no usable trial, so there is nothing "
                              "to invert. Reported as unknown rather than as a failure to "
                              "invert, which oracle.evaluate would read as 'document wrong'")}
    inverted = t["x"] == 0
    return inverted, {
        "cell": cell_key, "n_usable": t["n_usable"], "prediction_failures": t["x"],
        "inverted": inverted,
        "why": ("every usable trial in the mutation cell came out the way that cell predicts, "
                "so the treatment cell's outcome is attributable to the axis that differs "
                "between them"
                if inverted else
                f"{t['x']} of {t['n_usable']} usable trials in the mutation cell contradicted "
                f"its own prediction, so the treatment cell's outcome is NOT attributable to "
                f"the axis that differs between them"),
    }


def _guard_failures(case_id: str, tallies_by_cell: dict[str, dict]) -> list[dict]:
    """`CASE_GUARDS` violations: the case ran to completion but has no subject."""
    out = []
    for g in CASE_GUARDS.get(case_id, ()):
        t = tallies_by_cell.get(g["cell"])
        if t is None:
            out.append({**g, "n_usable": 0, "x": None,
                        "detail": "the guard cell produced no tally at all"})
        elif t["x"] != 0:
            out.append({**g, "n_usable": t["n_usable"], "x": t["x"],
                        "detail": (f"{t['x']} of {t['n_usable']} usable trials in "
                                   f"{g['cell']} contradicted its own prediction")})
    return out


def _cell_summary(t: dict) -> dict:
    """A cell's numbers without its 120 rows, for the parts of a payload a human reads."""
    return {k: t[k] for k in ("cell", "role", "planned_n", "n_attempted", "n_usable", "x",
                              "n_failed", "failure_codes", "n_recorded", "n_unclassified",
                              "checkpoint")}


def _cells_for(case_id: str) -> list[str]:
    """The cells this case reads, oracle first, de-duplicated with order preserved.

    De-duplication matters: F4-3's mutation cell is also read by F4-2 and F4-5, and a cell listed
    twice would be gated twice and would appear twice in the tally list `require_measured`
    averages over.
    """
    spec = CASE_CELLS[case_id]
    ordered = [spec["oracle"]]
    if spec["mutation"]:
        ordered.append(spec["mutation"])
    ordered.extend(spec["support"])
    return list(dict.fromkeys(ordered))


def _role_of(case_id: str, cell_key: str) -> str:
    spec = CASE_CELLS[case_id]
    if cell_key == spec["oracle"]:
        return "oracle"
    if cell_key == spec["mutation"]:
        return "mutation"
    return "support"


def _evaluate_case(case_id: str, checkpoints: dict[str, C.Checkpoint], *,
                   common: dict[str, Any], store: EvidenceStore,
                   is_smoke: bool, n_by_cell: dict[str, int]) -> int:
    """Score one case from the cells it reads, emit its record, and return its exit code.

    The order of the gates is the order of the questions, and it is not arbitrary. Did the cells
    this case needs even run (completion)? Is every hit an error shape the instrument recognises
    (unclassified)? Does the case have a subject at all (guards)? Only then is there a verdict to
    compute. Each gate that fires produces an INCONCLUSIVE record rather than a verdict, because
    every one of them is a statement about the instrument and none is evidence about the
    document.
    """
    cells = _cells_for(case_id)
    tallies_by_cell = {
        c: _tally(case_id, c, checkpoints[c], n_by_cell[c], role=_role_of(case_id, c))
        for c in cells if c in checkpoints}
    missing = [c for c in cells if c not in tallies_by_cell]

    payload: dict[str, Any] = {
        **common,
        "cells_read": {c: {"role": _role_of(case_id, c),
                           "why": next(x["why"] for x in CELLS if x["key"] == c)}
                       for c in cells},
        "cell_summaries": [_cell_summary(t) for t in tallies_by_cell.values()],
        "oracle_cell": CASE_CELLS[case_id]["oracle"],
        "mutation_cell": CASE_CELLS[case_id]["mutation"],
        "mutation_mandatory_per_seal": O.mutation_is_mandatory(case_id),
        "guards": [dict(g) for g in CASE_GUARDS.get(case_id, ())],
        "why_cells_are_shared": (
            "a cell is one live configuration plus one request shape; a case is a question "
            "asked of one or more cells. Six cases read eight cells, and "
            "enforce__permit_forbid__benign answers four of them from ONE set of responses. "
            "Re-sending the same request under the same configuration once per case would cost "
            "600 extra gateway calls and add no information"),
    }

    if missing:
        rec = O.not_measured(
            case_id,
            f"cells this case depends on did not run: {missing}. A verdict from the remaining "
            f"cells would be a verdict from a different design than the one that was sealed",
            missing_cells=missing, cells_required=cells)
        P.emit(case_id, rec, payload, store)
        return 2

    tallies = list(tallies_by_cell.values())
    gate = P.require_measured(tallies, is_smoke=is_smoke)
    if gate != 0:
        rec = O.not_measured(
            case_id,
            "the per-arm completion gate was not met, so the pre-registered precision was not "
            "reached. A shortfall reported beside a verdict IS a verdict (DEV-P1-11), so no "
            "verdict is published here",
            cell_summaries=payload["cell_summaries"])
        P.emit(case_id, rec, payload, store)
        return 2

    ot = tallies_by_cell[CASE_CELLS[case_id]["oracle"]]
    if ot["n_unclassified"]:
        rec = O.not_measured(
            case_id,
            f"{ot['n_unclassified']} trial(s) in the oracle cell carried an error shape "
            f"lib/mcp.classify does not recognise. An unrecognised shape is a gap in the "
            f"INSTRUMENT, not evidence about the truth table: classified either way it would "
            f"move a verdict on the strength of something nobody has characterised",
            oracle_cell=_cell_summary(ot))
        P.emit(case_id, rec, payload, store)
        return 1

    guard_fails = _guard_failures(case_id, tallies_by_cell)
    if guard_fails:
        rec = O.not_measured(
            case_id,
            "a subject guard failed: the cells ran to completion but this case has nothing to "
            "ask the question of. See `guard_failures` — each entry names what would otherwise "
            "have been concluded and why it would have been wrong",
            guard_failures=guard_fails)
        P.emit(case_id, rec, {**payload, "guard_failures": guard_fails}, store)
        return 2

    inverted, inversion_detail = _inversion(tallies_by_cell, CASE_CELLS[case_id]["mutation"])

    obs = P.obs_zero_events(
        case_id, adverse=ot["x"], n=ot["n_usable"],
        oracle_cell=_cell_summary(ot),
        cells=[_cell_summary(t) for t in tallies],
        adverse_examples=[{k: r.get(k) for k in
                           ("trial_id", "trial_index", "outcome", "http_status", "why_hit",
                            "f4_6_why", "request_id")}
                          for r in ot["rows"]
                          if (r.get("f4_6_adverse") if case_id == "F4-6" else r.get("hit"))][:10],
        mutation=inversion_detail)
    obs.mutation_inverted = inverted
    rec = O.evaluate(obs)

    # The F1-3 pattern, and for the F1-3 reason: the seal is not overridden from inside a case
    # script. `oracle.evaluate` turns a mandatory mutation that did not invert into FALSE, and
    # FALSE is the right verdict in the sense the seal means it — the case's TRUE was not
    # established. But FALSE reads as "the document is wrong", and a non-inverting mutation is
    # an ATTRIBUTION failure, which is a different claim. So the verdict is left where the seal
    # put it and the blocker is written into the record as data, because
    # check_amendment_readiness.py reads finding provenance blocks and never a case payload.
    local_blockers: list[str] = []
    if O.mutation_is_mandatory(case_id) and inverted is False:
        local_blockers.append(
            f"{case_id}'s mandatory mutation did NOT invert: {inversion_detail.get('why')}. The "
            f"sealed verdict stands as oracle.evaluate computed it, but this record does not "
            f"support any v1.3 amendment asserting the document is WRONG here — what was "
            f"measured is that the outcome could not be attributed to the axis under test")
    if ot["n_usable"] < ot["planned_n"]:
        local_blockers.append(
            f"the oracle cell contributed {ot['n_usable']} usable trials against a "
            f"pre-registered {ot['planned_n']}. It cleared the 0.90 completion gate, so the "
            f"verdict stands, but any interval quoted from this record must be computed at "
            f"n={ot['n_usable']} and not at the planned n")
    if local_blockers:
        print(f"\nAMENDMENT BLOCKERS for {case_id} (the verdict stands; the remedy does not):",
              file=sys.stderr)
        for bl in local_blockers:
            print(f"  - {bl}", file=sys.stderr)

    P.emit(case_id, rec, {
        **payload,
        "adverse": ot["x"],
        "n_usable": ot["n_usable"],
        "mutation": inversion_detail,
        "local_amendment_blockers": local_blockers,
        "local_amendment_blockers_why": (
            "conditions that leave the sealed VERDICT intact but withdraw support from the "
            "REMEDY a v1.3 amendment would carry. They live in the record because "
            "check_amendment_readiness.py reads FINDING provenance blocks and replication days, "
            "not case payloads"),
        "replication_required": (
            "the conflict-resolution protocol requires reproduction on >=2 separate UTC days "
            "before the document is amended. One run of this script is one day"),
        "expiry": (
            "these are service behaviours, not model reads. AWS could change Cedar evaluation, "
            "the engine-mode precedence rule or the denial envelope at any time; if it does, "
            "that is an AWS-BEHAVIOR-CHANGES.md entry rather than a correction to this record"),
    }, store)
    return 0


# --------------------------------------------------------------------------
# dry run
# --------------------------------------------------------------------------

def _dry_run(n_by_cell: dict[str, int]) -> int:
    """One banner per case. Six, not one, because six records will be published."""
    rc = 0
    for case_id in CASES:
        cells = _cells_for(case_id)
        total = sum(n_by_cell[c] for c in cells)
        mutations = sum(1 + len(next(x for x in CELLS if x["key"] == c)["modes"])
                        for c in cells)
        billable = case_id == "F4-1"
        rc = max(rc, P.dry_run_banner(
            case_id,
            [(c, f"{_role_of(case_id, c)} / engine="
                 f"{next(x for x in CELLS if x['key'] == c)['engine']} / "
                 f"{next(x for x in CELLS if x['key'] == c)['expect']}", n_by_cell[c])
             for c in cells],
            operations={"InvokeGateway": total},
            mutations=mutations,
            billable=billable,
            text_units=(2 * n_by_cell[CASE_CELLS["F4-1"]["oracle"]] if billable else 0),
            text_units_why=(
                "F4-1 is the ONLY case in this family with a billable surface, and the earlier "
                "blanket 'F4 bills nothing' was wrong. Its guardrail policy makes the service "
                "evaluate a ContentFilter over `context.input.text`, and a LOG_ONLY guardrail "
                "policy is still EVALUATED — so text units are billed whether or not it "
                "enforces. Both of this case's cells send input the filter must score; whether "
                "the oracle cell's 120 also bill depends on whether default-deny short-circuits "
                "before guardrail evaluation, which is not documented, so both are counted. "
                "Staging exists partly for this: deleting the guardrail policy before the "
                "remaining six cells keeps the total near 240 instead of ~1,000"
                if billable else
                "no ApplyGuardrail, no InvokeGuardrailChecks, no model, and no guardrail policy "
                "on the engine during any cell this case reads. Gateway and control-plane calls "
                "bill no text units"),
            extra=[
                f"reads {len(cells)} of the {len(CELLS)} configuration cells: "
                + ", ".join(f"{c} ({_role_of(case_id, c)})" for c in cells),
                "a CELL is one live configuration plus one request shape; a CASE is a question "
                "asked of one or more cells. All six cases together read eight cells and "
                f"{sum(n_by_cell[c['key']] for c in CELLS)} gateway requests. An arm-per-case "
                "design sent 1,460 for the same six answers, differing only in how many times "
                "the same request was re-sent under the same configuration",
                f"the mutation count is axis switches, not experiments: 1 engine-mode set plus "
                f"one policy-mode set per declared policy, per cell. Each is verified by "
                f"readback from an INDEPENDENT call before any trial is sent, and a mode that "
                f"does not settle raises rather than being measured around",
                f"a FIXED {SETTLE_DWELL_S:.0f}s dwell after each configuration, never a poll on "
                f"the data plane: a loop that waited until the gateway agreed with the document "
                f"could not observe a refutation. `trial_index` on every row makes a longer lag "
                f"visible as adverse events clustered at the start of a cell",
                "the baseline permit is never DELETED, only driven to enforcementMode=LOG_ONLY. "
                "Re-creating it would need validationMode=IGNORE_ALL_FINDINGS (that is DC-1, "
                "F1-3's finding) and a failed re-create would strand the shared testbed without "
                "the permit every later phase depends on. F4-1 and F4-4 therefore realize 'no "
                "permit' as an OPERATIONALIZATION, recorded as a limitation, and F4-1's "
                "mandatory mutation is what resolves it",
                "`definition` is never re-sent on an UpdatePolicy, and that inference is "
                "MEASURED before the shared baseline policy is touched: the omit-definition "
                "path is probed against a sacrificial policy this script created and the Cedar "
                "body is read back byte-for-byte",
                "UpdateGateway is a REPLACE, so the live configuration is read and re-sent "
                "whole. The member list is re-derived from the loaded SDK model at run time "
                "and an unhandled member is FATAL before any mutation: resetting "
                "exceptionLevel would change the body of every error message every later "
                "phase reads, including the denial bodies F4-6 measures",
                "F4-6 IS EXPECTED TO REFUTE the document. A gateway policy denial arrives as "
                "HTTP 200 with result.isError true and an AuthorizeActionException, not the "
                "HTTP 403 that L141 claims. This prediction is on the record before the run so "
                "a confirmation cannot be presented as a discovery",
                "teardown restores BOTH axes to the values MEASURED at startup (not the ledger's "
                "recorded ones), deletes every policy this script created, and then RE-RUNS "
                "infra/06_verify.py's own verify_engine and verify_gateways — the same functions "
                "the Phase-2 gate runs, imported rather than restated, because two definitions "
                "of 'the testbed is intact' could disagree",
            ]))
    return rc


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def _restore(ac, store: EvidenceStore, state: T.State, *, start: dict[str, Any],
             gateway_id: str, engine_arn: str, engine_id: str, baseline_policy_id: str,
             stage_policy_ids: dict[str, str], account_id: str, region: str,
             keep_policies: bool) -> dict[str, Any]:
    """Delete what this script created, put both axes back, then RE-RUN the blocking assertion.

    Never raises. It runs from a `finally`, and an exception here would mask both the result and
    the true state of the testbed. Every failure is recorded and turned into `ok: False`, which
    `main` converts into a non-zero exit — a shared testbed left in an unknown configuration
    must not be reported as a clean run.
    """
    out: dict[str, Any] = {"deleted": {}, "axes": {}, "verify": None, "errors": []}

    if keep_policies:
        out["deleted"]["skipped"] = ("--keep-policies: F4's policies are left in place. They are "
                                     "in state.json, which is the only channel that can find "
                                     "them — `policy` takes no tags")
    else:
        for key, pid in list(stage_policy_ids.items()):
            try:
                if _delete_stage_policy(ac, store, state, engine_id=engine_id, key=key,
                                        policy_id=pid):
                    stage_policy_ids.pop(key, None)
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

    # The blocking assertion, re-run rather than assumed. PREREGISTRATION.yaml: "A restore is
    # not assumed to have worked because the API call returned 200."
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
                 and (keep_policies or not stage_policy_ids))
    out["why_measured_start"] = (
        "both axes are restored to the values READ LIVE at startup, not to the ledger's "
        "recorded ones. state.json records policy_engine_mode=ENFORCE and "
        "enforcement_mode=ACTIVE, but a ledger is a record of an intent at provisioning time "
        "and this script must return the testbed to what it actually found")
    return out


def main(argv: list[str] | None = None) -> int:                            # noqa: C901
    ap = P.parser("F4", __doc__)
    ap.add_argument("--keep-policies", action="store_true",
                    help="skip deletion of the policies this script creates (inspection only; "
                         "they are in state.json, which is the ONLY channel that finds them)")
    ap.add_argument("--state", default=None)
    ap.add_argument("--evidence-root", default=None,
                    help="write call records under this directory instead of evidence/. For "
                         "OFFLINE harnesses only: capture() refuses a non-botocore client whose "
                         "store is under evidence/, so this is how an offline run says where "
                         "its records belong")
    ap.add_argument("--checkpoint-root", default=None)
    args = ap.parse_args(argv)

    n_by_cell = {c["key"]: (min(args.n, c["n"]) if args.n else c["n"]) for c in CELLS}
    if args.dry_run:
        return _dry_run(n_by_cell)

    is_smoke = args.n is not None

    try:
        state = T.State.load(Path(args.state) if args.state else None)
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        for case_id in CASES:
            rec = O.not_measured(
                case_id,
                "state.json is absent, so there is no gateway, no policy engine and no baseline "
                "policy to configure. Nothing was sent",
                remedy="run infra/01_iam.py onward (Phase 2) first")
            P.emit(case_id, rec, {"instrument": "not built: no ledger"}, None)
        return 2

    run_id = state.run_id
    if args.run_id and args.run_id != run_id:
        print(f"FATAL: --run-id {args.run_id!r} disagrees with the ledger's {run_id!r}.",
              file=sys.stderr)
        return 2

    admin = A.factory(args.region)
    ac = admin.agentcore_control()
    account_id = A.account_id(admin)
    store = EvidenceStore(run_id, FAMILY, "F4",
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    print(f"F4 — the enforcement-mode truth table, run_id={run_id} (adopted from the ledger), "
          f"region={args.region}\n")

    gw = state.find("gateway", "main")
    eng = state.find("policy-engine", "main")
    pol = state.find("policy", "baseline")
    caller = state.find("iam-role", "caller")
    if not (gw and eng and pol and caller):
        for case_id in CASES:
            rec = O.not_measured(
                case_id,
                f"the ledger is missing a resource this family needs (gateway={bool(gw)}, "
                f"policy-engine={bool(eng)}, baseline policy={bool(pol)}, caller "
                f"role={bool(caller)})",
                remedy="run infra/01_iam.py onward (Phase 2) first")
            P.emit(case_id, rec, {"instrument": "not built: incomplete ledger"}, store)
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
        "validation_mode_for_f4_policies": F4_VALIDATION_MODE,
        "why_validation_off": (
            "F4 is not the validation experiment — F1-3 is, and it established that the "
            "unconstrained permit needs IGNORE_ALL_FINDINGS to create at all (DC-1). A policy "
            "that failed to create is not a mode measurement, so letting the finding gate "
            "reject one of these statements would turn a mode question into a validation one"),
        "instrument": (
            "signed MCP tools/call POSTs to the main gateway's /mcp endpoint as the grx-caller "
            "role, classified by lib/mcp.classify(); both mode axes driven by "
            "UpdateGateway/UpdatePolicy and verified by readback from independent calls"),
        "operationalization_no_permit": (
            "F4-1 and F4-4 need 'no permit in the enforced set'. The baseline permit is driven "
            "to enforcementMode=LOG_ONLY rather than deleted, because re-creating it would need "
            "IGNORE_ALL_FINDINGS and a failed re-create would strand the shared testbed. This "
            "is an OPERATIONALIZATION of the document's condition, not the literal condition, "
            "and it is what F4-1's mandatory mutation resolves: if the denial disappears when "
            "the permit returns to ACTIVE, a LOG_ONLY permit demonstrably did not grant"),
        "unverified_context_path": (
            "the narrow permit conditions on `context.input.amount`. No `context.` path appears "
            "anywhere in the document under test; the shape comes from lib/cedar.py's own "
            "samples. F4-4's control cell exists precisely because an unmatched path would make "
            "the policy inert and F4-4 would read TRUE for the wrong reason"),
    }

    live0 = capture(store, "get_gateway", ac, gatewayIdentifier=gateway_id)
    if not live0.ok:
        for case_id in CASES:
            rec = O.not_measured(case_id, f"the startup GetGateway failed "
                                          f"({live0.error_code}), so the axes' starting values "
                                          f"were never measured and could not be restored",
                                 error_code=live0.error_code)
            P.emit(case_id, rec, common, store)
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
        for case_id in CASES:
            rec = O.not_measured(
                case_id,
                f"UpdateGateway's input shape carries members this script does not re-send "
                f"({shape['unhandled']}) or is missing members it would send "
                f"({shape['absent_from_model']}). UpdateGateway is a REPLACE, so driving the "
                f"engine axis would RESET those members on a shared gateway. No mutation was "
                f"attempted",
                shape=shape)
            P.emit(case_id, rec, common, store)
        return 2

    fc = A.factory(args.region, role_arn=caller_arn)
    checkpoints: dict[str, C.Checkpoint] = {}
    stage_policy_ids: dict[str, str] = {}
    config_log: list[dict[str, Any]] = []
    probe: dict[str, Any] | None = None
    rc = 0
    restore: dict[str, Any] = {}

    try:
        # The Cedar action id comes from the LEDGER, not from a constant here. It is
        # `<targetName>___<toolName>`, so it is a function of how `infra/05_target.py` named the
        # target, and a literal in this file would drift silently: the resulting policy would
        # still CREATE (the action id is just a string to the validator) but would match no
        # request, and F4-4 would read TRUE because its permit was inert — the exact failure mode
        # F4-4's CASE_GUARDS entry exists to catch. Asserting against the ledger turns a silent
        # mismatch into a refusal to start.
        tgt = state.find("gateway-target", "main")
        action_ids = list((tgt.ids.get("cedar_action_ids") if tgt else None) or [])
        echo_action_id = next((a for a in action_ids if a.endswith(f"___{TOOL}")), "")
        if not echo_action_id:
            raise ConfigError(
                f"the ledger's target/main carries no Cedar action id ending in '___{TOOL}' "
                f"(saw {action_ids}). The narrow permit must scope `action ==` to the echo tool, "
                f"because an unscoped action has to type-check against actions that carry no "
                f"`context.input` at all (CallTool, UnknownTool, Http, Mcp), and it cannot")
        specs = build_policies(gateway_arn, echo_action_id=echo_action_id)
        for key, spec in specs.items():
            problems = cedar.check_statement(spec["statement"])
            if problems:
                raise ConfigError(
                    f"the {key} statement failed lib/cedar.py's own grammar check ({problems}), "
                    f"so a rejection by the service would be attributable to the harness")
        names = plan_names(ac, run_id)
        common["policies"] = {k: {"name": names[k], **specs[k]} for k in specs}

        # The omit-definition probe runs ONCE here, before any cell and before the shared
        # baseline policy is ever updated, on a subject this script creates for the purpose.
        probe = _run_definition_probe(ac, store, state, engine_id=engine_id, run_id=run_id)
        common["update_policy_definition_probe"] = probe
        print(f"\nomit-definition probe: ok={probe['ok']} — {probe['why']}")
        if not probe["ok"]:
            raise ConfigError(
                f"the omit-definition UpdatePolicy probe FAILED on a sacrificial policy whose "
                f"statement carries the SAME validation findings as the baseline: "
                f"{probe['why']}. The policy axis is not driven on the shared baseline policy "
                f"under that condition")

        for stage in STAGES:
            key = stage["creates"]
            print(f"\nstage {stage['key']}: creating policy {key}")
            # No `stage_policy_ids[key] =` here on purpose; the function registers itself. See
            # `_create_stage_policy`'s docstring — the assignment form loses the id on exactly
            # the path where teardown needs it.
            _create_stage_policy(
                ac, store, state, engine_id=engine_id, key=key, name=names[key],
                spec=specs[key], registry=stage_policy_ids)

            for cell in [c for c in CELLS if c["stage"] == stage["key"]]:
                n = n_by_cell[cell["key"]]
                print(f"\n  cell {cell['key']} (n={n}, expect {cell['expect']})")
                config_log.append(_apply_config(
                    ac, store, cell=cell, gateway_id=gateway_id, engine_arn=engine_arn,
                    engine_id=engine_id, baseline_policy_id=baseline_policy_id,
                    stage_policy_ids=stage_policy_ids))
                checkpoints[cell["key"]] = _run_cell(
                    fc, store, cell=cell, gateway_url=gateway_url, run_id=run_id,
                    region=args.region, n=n, session_timeout_s=session_timeout_s,
                    policy_ids=tuple(stage_policy_ids.values()) + (baseline_policy_id,),
                    cp_root=Path(args.checkpoint_root) if args.checkpoint_root else None,
                    is_smoke=is_smoke,
                    # The same ledger-resolved string the narrow permit scopes its `action ==`
                    # to. One value, one source, so a policy that names one tool cannot be
                    # exercised by a request that names another.
                    tool_name=echo_action_id)

            _delete_stage_policy(ac, store, state, engine_id=engine_id, key=key,
                                 policy_id=stage_policy_ids[key])
            stage_policy_ids.pop(key, None)

        common["config_log"] = config_log
        print("\nverdicts")
        rcs = [_evaluate_case(case_id, checkpoints, common=common, store=store,
                              is_smoke=is_smoke, n_by_cell=n_by_cell)
               for case_id in CASES]
        rc = max(rcs)

    except ConfigError as exc:
        print(f"\nFATAL: {exc}", file=sys.stderr)
        common["config_log"] = config_log
        for case_id in CASES:
            if any(c in checkpoints for c in _cells_for(case_id)):
                # Partial data exists, but a truth table missing a corner is not the design that
                # was sealed. The cells that ran are recorded; no verdict is computed from them.
                pass
            rec = O.not_measured(
                case_id, f"a configuration step did not land, so the cells this case needs were "
                         f"not all measured under a known configuration: {exc}",
                cells_run=sorted(checkpoints),
                cells_required=_cells_for(case_id))
            P.emit(case_id, rec, common, store)
        rc = 2

    finally:
        print("\nteardown and restore")
        restore = _restore(ac, store, state, start=start, gateway_id=gateway_id,
                           engine_arn=engine_arn, engine_id=engine_id,
                           baseline_policy_id=baseline_policy_id,
                           stage_policy_ids=stage_policy_ids, account_id=account_id,
                           region=args.region, keep_policies=args.keep_policies)
        (store.dir / "restore.json").write_text(json.dumps(restore, indent=2, default=str))
        store.write_summary()

    if not restore.get("ok"):
        print("\nFATAL: the testbed was NOT verified back to its measured starting state. "
              "Every later phase measures this gateway, so a non-zero exit here is the only "
              "thing that stops the next script from running against an unknown configuration.",
              file=sys.stderr)
        for err in restore.get("errors", []):
            print(f"  - {err}", file=sys.stderr)
        for name, ok, detail in (restore.get("verify") or {}).get("checks", []) and [
                (c["name"], c["ok"], c["detail"])
                for c in restore["verify"]["checks"] if not c["ok"]]:
            print(f"  - FAILED CHECK {name}: {detail}", file=sys.stderr)
        return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
