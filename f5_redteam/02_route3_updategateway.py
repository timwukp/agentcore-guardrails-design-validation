#!/usr/bin/env python3
"""F5-2 — route #3: can a runtime execution role turn the policy engine off?

    python3 f5_redteam/02_route3_updategateway.py --dry-run
    python3 f5_redteam/02_route3_updategateway.py --n 3        # smoke
    python3 f5_redteam/02_route3_updategateway.py              # pre-registered n=120
    python3 f5_redteam/02_route3_updategateway.py --also-null-pec   # + the omission probe

§4 of the document under test claims the gateway's policy engine is NON-BYPASSABLE. F5-1 tested
the shortest way around it — call the tool without the gateway. This case tests the shortest way
*through* it: leave the request path exactly where it is and change the gateway so the path stops
evaluating anything. One `UpdateGateway` with `policyEngineConfiguration.mode = LOG_ONLY` and
every subsequent request is evaluated, logged, and allowed.

The sealed oracle (`F5-2`, ZERO_EVENTS, confirmatory_e_cell, n=120, alpha = 0.05/8):

    "TRUE (closed) if UpdateGateway is denied to the runtime role; FALSE if it succeeds. Full
     chain: grant -> LOG_ONLY set -> previously-blocked request passes -> restore -> re-assert
     blocking"

`adverse` is the count of `UpdateGateway` calls the control plane ACCEPTED from
`grx-runtime-exec` in its shipped configuration, out of 120. Zero of those is the closed reading.

WHAT THE CLOSED ARM SENDS, AND WHY IT IS A NO-OP EVEN IF IT SUCCEEDS
--------------------------------------------------------------------
`UpdateGateway` is a FULL REPLACEMENT, not a patch. The botocore input shape carries
`protocolConfiguration`, `exceptionLevel`, `description` and `policyEngineConfiguration` as
optional members, and omitting one is a request to unset it — so a naive attack body would
reset the session timeout and the debug exception level of the gateway that F4 and F6 are
published against.

Every attempt in this script therefore sends the configuration read back from `GetGateway`,
member for member, filtered to the members `UpdateGateway` actually accepts (taken from the
service model at runtime, not from a list typed here). The closed arm's body is the gateway's
own current state with nothing changed.

That is not a weakened attack. IAM authorization is evaluated before the request body takes
effect, so an accepted no-op and an accepted mutation are the same authorization event — which
is what `adverse` counts. What it buys is that an unexpectedly-accepted call in the confirmatory
arm damages nothing: 120 accepted no-ops leave the gateway byte-identical, and the finding is
still that the call was accepted.

THE HAZARD THAT MAKES THE MUTATION MANDATORY, NOT DECORATIVE
------------------------------------------------------------
`grx-runtime-exec` holds no `bedrock-agentcore` control-plane permission of any kind. IAM
therefore answers `AccessDeniedException` **before it looks at the request at all** — so a wrong
gateway identifier, a malformed body, a member the model does not accept, a stale region, all
produce the same `AccessDeniedException` as a real authorization boundary. 120 of them would read
as a perfect security result while proving nothing but that we sent a request IAM refused to look
at.

The granted arm is what fixes it. With the permission attached, the SAME body sent to the SAME
gateway must be ACCEPTED. Only then is the closed arm's denial about a request the service would
otherwise have honoured. `granted_arm_proved_the_call_is_otherwise_accepted` gates the verdict on
exactly that.

THE GRANT IS STAGED, BECAUSE `roleArn` IS A REQUIRED MEMBER
-----------------------------------------------------------
`UpdateGateway`'s required members are `gatewayIdentifier`, `name`, `roleArn`, `authorizerType`.
Passing a role means `iam:PassRole` is in play as well as `bedrock-agentcore:UpdateGateway`, and
granting only the first would produce an `AccessDeniedException` that is indistinguishable, in
the data, from "the route is closed" — a mutation that fails to invert, read as a confirmation.

So the grant is applied in two stages and the arms are separated:

  granted_update_only   `bedrock-agentcore:UpdateGateway` on this gateway ARN, alone
  granted_mutation      the above PLUS `iam:PassRole` on the gateway execution role

`binding_permission` in the result names which stage made the call succeed. That is a finding in
its own right: §4's remedy is written as though withholding one API permission closes this route,
and the answer to "which permission is load-bearing" belongs in the amendment.

WHY THE GRANTED ARM IS 5 AND NOT 120
------------------------------------
The confirmatory n lives in the closed arm alone. The granted arm answers a yes/no question about
the instrument — is this call accepted when the permission exists — and each accepted attempt is a
real control-plane update of the gateway that F4's truth table and F6's latency pair are published
against. Twenty accepted updates would put the gateway through twenty UPDATING/READY cycles for no
gain in what the arm can say. `adverse` and `n_usable` come from ARM_CLOSED only, so the two
denominators never meet in one sentence (`feedback_two_numbers_two_claims`).

FOUR OUTCOMES PER ATTEMPT, AND TWO OF THEM ARE NOT DENIALS
-----------------------------------------------------------
  accepted       the call returned 2xx -> adverse
  denied_by_iam  `AccessDeniedException` / `AccessDenied` -> the closed reading
  conflict       `ConflictException`: the gateway was still UPDATING from the previous accepted
                 call. An authorization success that the service then serialized away. Counted
                 as USABLE and as adverse, because IAM had already said yes.
  unusable       anything else: `ValidationException`, `ResourceNotFoundException`, throttling,
                 a transport error. NOT a denial in either direction.

The `conflict` bucket is separate from `accepted` because the two are different observations of
the same authorization outcome, and collapsing them would hide the serialization behaviour; it is
counted INTO adverse because `ConflictException` is returned after authorization, so the caller
was authorized. `unusable` is excluded from `n_usable`, and a run whose `n_usable` falls below the
pre-registered 120 is reported NOT_MEASURED rather than published against a smaller denominator.

THE FULL CHAIN, AND WHY IT NEEDS A POLICY THIS RUN CREATES
----------------------------------------------------------
The oracle's chain requires "a previously-blocked request passes". Nothing on this engine blocks
anything: the only policy is the baseline permit
`permit(principal, action, resource is AgentCore::Gateway);` — the statement §3.1 tells readers to
add — and it denies nothing. Flipping a gateway with no blocking policy to LOG_ONLY changes no
decision, and an arm where every request was allowed before and after would demonstrate nothing at
all.

So the chain creates a `forbid` first, and each leg is MEASURED rather than assumed:

  enforce_blocked      amount=999.0 -> must be DENIED   (the forbid is load-bearing)
  enforce_allowed      amount=1.0   -> must be ALLOWED  (the forbid is not blocking everything)
  logonly_blocked      amount=999.0 -> ALLOWED is the bypass
  reasserted_blocked   amount=999.0 -> must be DENIED again after the restore

The `forbid` is written with `unless { ... lessThan(...) }` rather than a `greaterThanOrEqual`
condition because `lessThan` on a Cedar decimal is the operator F4 verified live on this engine.
`amount` is sent as `999.0`, with the decimal point, for the reason F4 measured and recorded: an
integral JSON literal reaches the policy engine as something it refuses to bind to a Cedar
decimal, and both halves then deny for an evaluation error rather than a policy decision.

BOTH DIRECTIONS OF THE FLIP ARE POLLED, NOT ASSUMED
---------------------------------------------------
`UpdateGateway` returning 200 is a control-plane fact. Whether the data plane has stopped (or
resumed) enforcing is a separate question with its own latency, and nothing in the documentation
bounds it. So after the flip the chain polls until the blocked request is allowed, and after the
restore it polls until it is denied again, both bounded and both with the elapsed time recorded.
How long a LOG_ONLY window persists after `mode` is set back to `ENFORCE` is a measurement §7's
promotion workflow does not mention and an incident runbook would want.

WHAT IS DELIBERATELY NOT DONE TO `main`
---------------------------------------
The case's method note also asks whether omitting `policyEngineConfiguration` from an
`UpdateGateway` body CLEARS it. The member is optional in the model — and per F5-7a's lesson,
shape optionality carries no information about behaviour, so this has to be measured.

It is not measured on `grx-gw-<runid>`. Re-attaching a policy engine to a gateway that has none is
undocumented, so an irreversible detach is possible, and `main` is the ENFORCE half of the pair
`nopolicy` is the baseline for: unmaking it retroactively unmakes the F4 truth table and every F6
latency verdict. `--also-null-pec` therefore creates a DISPOSABLE gateway with the same engine,
probes the omission there, and deletes it. Default off, because the pre-registered confirmatory run
has a fixed mutation count.

BLAST RADIUS, THE WATCHDOG, AND THE LEDGER-FIRST ORDERING
--------------------------------------------------------
Mutations: two inline policies on `grx-runtime-exec` (created, then deleted), one `forbid` policy
on the shared engine (created, then deleted), and two `UpdateGateway` calls on `main` (to LOG_ONLY
and back). Each is recorded in the resource ledger BEFORE it is made, because `finally` is not a
watchdog — SIGKILL skips it — and `infra/99_teardown.py` reading `state.json` is the durable second
channel. The asymmetry is deliberate: a ledger entry for something never created costs one
`NoSuchEntity` at teardown, while a created grant with no entry is a permanent unattended
permission on a role whose entire purpose is to lack it.

Three interlocks refuse to start:

  the role must carry exactly its shipped inline policy — a grant left by a crashed run would make
  the closed arm succeed 120 times and this script would publish "route #3 is open" about an
  intact boundary, manufactured from our own litter;

  the shared policy engine must be quiet — a `forbid` created here changes another case's
  decisions, and F5-4a refuses to start for the mirror-image reason;

  the gateway must start in its provisioned configuration, READY and in ENFORCE with the run's
  engine attached — everything downstream is a statement about that gateway.

The gateway's configuration is diffed field for field at the end, using
`infra/04_gateway.diff_configs` and that module's own `PAIR_IGNORE` (minus
`policyEngineConfiguration`, which is compared explicitly because it is the field this case
moves). Imported, not retyped: the pairing rule F6 depends on has one definition.

COST
----
Zero text units: no model, no `ApplyGuardrail`, no `InvokeGuardrailChecks`. Billable surface is
~150 `bedrock-agentcore` control-plane calls, 4 IAM writes, a `CreatePolicy`/`DeletePolicy` pair,
and 12 gateway `tools/call` probes. Under a cent.

Never touched: the six pre-existing READY gateways, the three DRAFT guardrails, the two abandoned
policy engines, any `harness_*`/`uitestagent_*` resource, and the `nopolicy` gateway.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                              # noqa: E402
import cedar as C                                                   # noqa: E402
import checkpoint as K                                              # noqa: E402
import mcp as MCP                                                   # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402
import testbed as T                                                 # noqa: E402
from evidence import EvidenceStore, capture                         # noqa: E402

FAMILY = "f5"
CASE = "F5-2"


def _load(spec):
    """Execute an already-built spec.

    The `spec_from_file_location` calls are written out at each site rather than wrapped, because
    `lib/tests/test_module_name_collisions.py` reads the registered `sys.modules` name statically
    to prove two loaders cannot claim the same one. A helper taking the name as a parameter makes
    that name unreadable, and the guard then has to be told to stop looking — which is the check
    being disabled to keep the convenience.
    """
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The gateway pairing rule and the "terminal status" definition come from the provisioners that
# own them. A copy of PAIR_IGNORE here would let the restore check and F6's pairing assertion
# drift apart while both claimed to be comparing the same fields.
_gwmod = _load(importlib.util.spec_from_file_location(
    "_grx_gateway", ROOT / "infra" / "04_gateway.py"))
_pemod = _load(importlib.util.spec_from_file_location(
    "_grx_policy_engine", ROOT / "infra" / "03_policy_engine.py"))
PAIR_IGNORE = _gwmod.PAIR_IGNORE
diff_configs = _gwmod.diff_configs
wait_ready = _gwmod.wait_ready
GATEWAY_DEFAULT_MODE = _gwmod.DEFAULT_MODE
wait_status = _pemod.wait_status
# Two DIFFERENT terminal sets, imported under names that cannot be confused. A gateway settles
# in `READY` and a policy in `ACTIVE`, and one shared `TERMINAL_OK` here would have made the
# startup interlock reject every healthy gateway — a refusal indistinguishable, in the log,
# from the gateway genuinely not being provisioned.
GATEWAY_OK = _gwmod.TERMINAL_OK
GATEWAY_BAD = _gwmod.TERMINAL_BAD
POLICY_OK = _pemod.TERMINAL_OK

# The one field this case moves, so it is compared explicitly rather than ignored. `PAIR_IGNORE`
# exists to answer "does anything ELSE differ" for F6's pair; here the mode is the subject.
RESTORE_IGNORE = tuple(k for k in PAIR_IGNORE if k != "policyEngineConfiguration")

# Read from the sealed oracle rather than typed: a literal 120 here would be a second place the
# pre-registered n lives, and PREREGISTRATION.yaml is the one that counts.
PLANNED_N = O.planned_n(CASE)

TOOL = "echo"
BASELINE_INLINE = "grx-runtime-exec-policy"       # what infra/01_iam.py ships on the role

MODE_ENFORCE = "ENFORCE"
MODE_LOG_ONLY = "LOG_ONLY"

# The two grants, as separate named inline policies so each undo is "delete a named policy"
# rather than "edit a document back", and so the staged arms can differ by exactly one of them.
GRANT_UPDATE_SID = "F52MutationUpdateGateway"
GRANT_PASSROLE_SID = "F52MutationPassRole"

ARM_CLOSED = "closed_baseline"
ARM_UPDATE_ONLY = "granted_update_only"
ARM_GRANTED = "granted_mutation"
ARM_RESTORED = "restored_reassert"
ARMS = (ARM_CLOSED, ARM_UPDATE_ONLY, ARM_GRANTED, ARM_RESTORED)

# Small on purpose: see the module docstring. These answer yes/no questions about the instrument,
# not a rate, and every accepted attempt is a real UPDATING/READY cycle on the gateway F4 and F6
# are published against. ARM_RESTORED is larger because its attempts are expected to be denied
# and a denial changes nothing.
N_UPDATE_ONLY = 3
N_GRANTED = 5
N_RESTORED = 20

DENIED_CODES = ("AccessDeniedException", "AccessDenied")
CONFLICT_CODES = ("ConflictException",)

# IAM is eventually consistent in both directions; F5-1 measured 32.1s for a grant to land and
# found the revoke direction slow and flappy enough to need its own bound. Re-assuming the role
# would not help and is not done: IAM evaluates the identity's policies at REQUEST time.
PROP_MAX_S = 300
PROP_EVERY_S = 10
PROP_MAX_REVOKE_S = 1800
# One confirming probe is not convergence. F5-1 measured the failure this prevents: a revoke wait
# ended on a single denial, and 9 of the next 20 calls then succeeded.
PROP_CONFIRM_N = 3

# The data-plane side of the flip has its own latency, separate from IAM's and from the gateway's
# UPDATING window, and nothing documents it. Polled in both directions and recorded.
DATA_PLANE_MAX_S = 300
DATA_PLANE_EVERY_S = 10
DATA_PLANE_CONFIRM_N = 2

GATEWAY_READY_TIMEOUT_S = 300

# The forbid's threshold, and the two amounts either side of it. Floats with a decimal point:
# F4 measured that an integral JSON literal reaches the engine as something it refuses to bind to
# a Cedar decimal, and BOTH halves then deny for an evaluation error rather than a decision.
AMOUNT_LIMIT = 500.0
BLOCK_AMOUNT = 999.0
ALLOW_AMOUNT = 1.0

# Requests per chain leg. Three, because a leg's reading is all-or-nothing: a split leg is itself
# a finding and is reported rather than averaged.
N_PROBE = 3

LEG_ENFORCE_BLOCKED = "enforce_blocked"
LEG_ENFORCE_ALLOWED = "enforce_allowed"
LEG_LOGONLY_BLOCKED = "logonly_blocked"
LEG_REASSERTED = "reasserted_blocked"
LEGS = (LEG_ENFORCE_BLOCKED, LEG_ENFORCE_ALLOWED, LEG_LOGONLY_BLOCKED, LEG_REASSERTED)

DELETE_ATTEMPTS = 4
DELETE_SLEEP_S = 3
INTER_CALL_S = 0.2

GUARDS = (
    "gateway_started_in_its_provisioned_configuration",
    "role_started_in_its_shipped_configuration",
    "engine_was_quiet_at_start",
    "granted_arm_proved_the_call_is_otherwise_accepted",
    "blocking_policy_was_load_bearing_before_the_mutation",
    "log_only_flip_let_the_blocked_request_through",
    "blocking_was_reasserted_in_the_data_plane",
    "gateway_was_restored_field_for_field",
    "grants_were_removed_from_the_role",
    "probe_policy_was_deleted",
    "usable_trials_met_the_preregistered_n",
)

MAX_MUTATIONS = 7   # 2 grants + 2 revokes + 1 forbid + 1 delete + 2 UpdateGateway... see below


class ConfigError(RuntimeError):
    """A precondition that must stop the run before anything is mutated."""


# ---------------------------------------------------------------------------
# the request body: a full replacement built from the gateway's own state
# ---------------------------------------------------------------------------

def _update_shape(ac) -> tuple[frozenset[str], frozenset[str]]:
    """`UpdateGateway`'s accepted and required members, from the service model.

    Derived rather than listed. A hard-coded member list would be a second source of truth that
    drifts at the next botocore bump — and "UpdateGateway is a full replacement over THESE
    members" is the claim, so the SDK has to be the one asserting it. A member the model gains
    later is then copied through automatically instead of being silently unset by our body.
    """
    sh = ac.meta.service_model.operation_model("UpdateGateway").input_shape
    return frozenset(sh.members), frozenset(sh.required_members)


def _settle(ac, gateway_id: str) -> dict[str, Any]:
    """`wait_ready`, plus the status it settled INTO.

    `wait_ready` returns on any terminal status, `READY` and `UPDATE_UNSUCCESSFUL` alike — which
    is right for a waiter and wrong for a caller that then reads a field off the result and calls
    it the new configuration. A failed update leaves a gateway whose `mode` is whatever it was
    before, so without this the chain could report a flip that the service rejected.
    """
    live = wait_ready(ac, gateway_id, timeout_s=GATEWAY_READY_TIMEOUT_S)
    st = live.get("status")
    return {"live": live, "status": st, "settled_ok": st in GATEWAY_OK,
            "status_reasons": live.get("statusReasons") if st in GATEWAY_BAD else None}


def _replacement_kwargs(live: dict[str, Any], *, gateway_id: str, allowed: frozenset[str],
                        required: frozenset[str], mode: str | None = None,
                        drop_pec: bool = False) -> dict[str, Any]:
    """The gateway's current configuration, as an `UpdateGateway` body, with at most one change.

    Deep-copied because the caller keeps `live` for the end-of-run diff, and a body that shared
    the nested `policyEngineConfiguration` dict would mutate the very record the restore is
    verified against — a comparison that can never fail.
    """
    kw: dict[str, Any] = {"gatewayIdentifier": gateway_id}
    for key in sorted(allowed - {"gatewayIdentifier"}):
        if key in live:
            kw[key] = copy.deepcopy(live[key])
    if drop_pec:
        kw.pop("policyEngineConfiguration", None)
    elif mode is not None:
        pec = kw.get("policyEngineConfiguration")
        if not isinstance(pec, dict):
            raise ConfigError(
                f"the gateway carries no policyEngineConfiguration, so `mode={mode}` cannot be "
                f"set on it. This case is about disabling an engine that is attached; a gateway "
                f"without one is F6's `nopolicy` baseline, not this one.")
        pec["mode"] = mode
    missing = sorted(required - set(kw))
    if missing:
        raise ConfigError(
            f"GetGateway did not return {missing}, which UpdateGateway requires. Sending the "
            f"body without them would be a ValidationException classified `unusable`, and 120 "
            f"of those would report NOT_MEASURED for a reason that is our bug, not a boundary.")
    return kw


# ---------------------------------------------------------------------------
# preconditions
# ---------------------------------------------------------------------------

def _assert_role_is_pristine(iam, store, *, role_name: str,
                             grant_names: tuple[str, ...]) -> dict[str, Any]:
    """The role must carry exactly its shipped inline policy and nothing else.

    Read from the live role, not from the ledger's `ids.inline_policies`: the ledger records what
    we intended to create, and this needs what IS attached. The failure it exists for is quiet —
    a grant left behind by a crashed run makes ARM_CLOSED succeed 120 times and this script
    publishes FALSE, a refutation of a security property assembled entirely from our own litter,
    and nothing downstream could tell because an accepted call looks the same whoever authorized
    it.
    """
    got = capture(store, "list_role_policies", iam, RoleName=role_name)
    if not got.ok:
        raise ConfigError(
            f"ListRolePolicies on {role_name} failed ({got.error_code}), so the role's starting "
            f"configuration was never measured. Refusing to mutate a role whose baseline is "
            f"unknown.")
    names = sorted(got.response.get("PolicyNames") or [])
    already = [n for n in grant_names if n in names]
    if already:
        raise ConfigError(
            f"{already} already attached to {role_name}. A previous run of this case crashed "
            f"before its restore, or teardown has not run. The closed arm would be accepted 120 "
            f"times and this script would publish 'route #3 is open' about an intact boundary. "
            f"Delete them (`aws iam delete-role-policy --role-name {role_name} --policy-name "
            f"<name>`) and re-run.")
    if names != [BASELINE_INLINE]:
        raise ConfigError(
            f"{role_name} carries inline policies {names}, not exactly [{BASELINE_INLINE!r}]. "
            f"Something outside this project has changed the role, so whatever the closed arm "
            f"measures is not the shipped configuration the document's claim is about.")
    return {"inline_policies_at_start": names, "read_from": "iam:ListRolePolicies (live)"}


def _assert_engine_is_quiet(state: T.State) -> dict[str, Any]:
    """Refuse to start if another case's probe policy is live on the shared engine.

    The mirror image of F5-4a's interlock, and for the same reason: this script adds a `forbid` to
    an engine every gateway request passes through, so a concurrent case's decisions would change
    under it and its data would be destroyed. The ledger is the channel that can see this —
    `policy` resources take no tags, so every script that creates one registers it here.
    """
    others = [r for r in state.of_kind("policy") if r.logical != "baseline"]
    if others:
        raise ConfigError(
            "the shared policy engine is not quiet: "
            + ", ".join(f"{r.logical} ({r.ids.get('policy_id')})" for r in others)
            + ". Another case's probe policy is registered, so the `forbid` this chain needs "
              "would change that case's decisions. Wait for it to finish, or if it crashed, "
              "delete the policy and drop the ledger entry first.")
    return {"policies_on_engine_at_start": [r.logical for r in state.of_kind("policy")],
            "checked": "state.json policy resources other than `baseline`"}


def _assert_gateway_is_provisioned(live: dict[str, Any], *, engine_arn: str) -> dict[str, Any]:
    """READY, ENFORCE, and carrying THIS run's engine.

    All three are asserted rather than recorded because every number this case produces is a
    statement about that gateway. A gateway already in LOG_ONLY would make the chain's
    `logonly_blocked` leg pass without any mutation of ours, and the bypass would be an artefact
    of a state we inherited.
    """
    status = live.get("status")
    pec = live.get("policyEngineConfiguration") or {}
    if status not in GATEWAY_OK:
        raise ConfigError(
            f"the gateway is {status}, not READY. An UpdateGateway against a gateway that is "
            f"still settling returns ConflictException, which this script counts as adverse "
            f"because it follows authorization — so a non-READY start would put conflicts into "
            f"the closed arm and read as a bypass.")
    if pec.get("mode") != MODE_ENFORCE:
        raise ConfigError(
            f"the gateway's policyEngineConfiguration.mode is {pec.get('mode')!r}, not "
            f"{MODE_ENFORCE!r}. The chain measures a flip FROM enforcing TO not enforcing; "
            f"starting in LOG_ONLY would make the bypass leg pass with no mutation from us.")
    if pec.get("arn") != engine_arn:
        raise ConfigError(
            f"the gateway's attached policy engine is {pec.get('arn')!r}, not the ledger's "
            f"{engine_arn!r}. The forbid this chain creates would go to an engine that is not in "
            f"the request path, and every leg would read ALLOW.")
    return {"status": status, "mode": pec.get("mode"), "engine_arn_matches_ledger": True,
            "exception_level": live.get("exceptionLevel"),
            "read_from": "bedrock-agentcore-control:GetGateway (live)"}


# ---------------------------------------------------------------------------
# one attempt
# ---------------------------------------------------------------------------

def _attempt(ac, store, *, kwargs: dict[str, Any], trial_id: str) -> dict[str, Any]:
    """One `UpdateGateway` as whichever role `ac` holds.

    Returns a row, never raises for an AWS error: an `AccessDeniedException` IS the measurement
    in the closed arm, so it must be data and not an exception.
    """
    A.limiter().wait("UpdateGateway")
    t0 = time.monotonic()
    res = capture(store, "update_gateway", ac, **kwargs)
    elapsed_ms = (time.monotonic() - t0) * 1000.0

    row: dict[str, Any] = {"trial_id": trial_id, "elapsed_ms": round(elapsed_ms, 2)}
    if not res.ok:
        code = res.error_code or ""
        row["outcome"] = ("denied_by_iam" if code in DENIED_CODES
                          else "conflict" if code in CONFLICT_CODES
                          else "unusable")
        row["error_code"] = code
        row["error_message"] = res.error_message or ""
        return row
    resp = res.response or {}
    row["outcome"] = "accepted"
    row["gateway_status_after"] = resp.get("status")
    row["http_status"] = res.http_status
    return row


def _run_arm(ac, cp, store, *, arm: str, kwargs: dict[str, Any], n: int,
             settle: bool = False, gateway_id: str = "") -> dict[str, Any]:
    """`n` attempts, tallied. Resumable: a completed trial is never re-sent.

    `settle` waits for the gateway to return to a terminal status after an ACCEPTED attempt. Only
    the arms that expect acceptance pass it: a denied attempt changes no state, and polling
    `GetGateway` 120 times in the closed arm would add two minutes and a hundred calls to measure
    a status that cannot have moved.
    """
    for i in range(1, n + 1):
        tid = f"{arm}__{i:04d}"
        if cp.is_done(tid):
            continue
        cp.run_trial(tid, lambda: {**_attempt(ac, store, kwargs=kwargs, trial_id=tid),
                                   "arm": arm})
        row = cp.results().get(tid) or {}
        if settle and row.get("outcome") == "accepted" and gateway_id:
            try:
                wait_ready(ac, gateway_id, timeout_s=GATEWAY_READY_TIMEOUT_S)
            except Exception as exc:                              # noqa: BLE001
                # Recorded, not raised: a settle timeout is about the next attempt's
                # ConflictException risk, not about this attempt's authorization outcome, which
                # is already in the checkpoint.
                row["settle_error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(INTER_CALL_S)

    rows = [r for r in cp.results().values() if r.get("arm") == arm]
    tally = {
        "arm": arm,
        "n_attempted": len(rows),
        "n_accepted": sum(1 for r in rows if r.get("outcome") == "accepted"),
        "n_conflict": sum(1 for r in rows if r.get("outcome") == "conflict"),
        "n_denied": sum(1 for r in rows if r.get("outcome") == "denied_by_iam"),
        "n_unusable": sum(1 for r in rows if r.get("outcome") == "unusable"),
        "error_codes": sorted({r.get("error_code", "") for r in rows if r.get("error_code")}),
    }
    # A ConflictException follows authorization, so it is an authorized call and belongs in
    # `adverse`. It is tallied separately as well, because "authorized then serialized away" and
    # "authorized and applied" are different observations and only one of them changed the
    # gateway.
    tally["n_authorized"] = tally["n_accepted"] + tally["n_conflict"]
    # `n_usable` excludes `unusable`: a ValidationException is not a denial and must not be
    # denominated as one.
    tally["n_usable"] = tally["n_authorized"] + tally["n_denied"]
    return tally


# ---------------------------------------------------------------------------
# the grants, and their propagation waits
# ---------------------------------------------------------------------------

def _update_gateway_grant(gateway_arn: str) -> dict[str, Any]:
    """`bedrock-agentcore:UpdateGateway` on ONE gateway ARN, and nothing else.

    Scoped to the resource rather than `*` because the mutation has to answer exactly one
    question — was the absence of this permission what closed route #3 — and a wildcard grant
    would additionally answer questions about every other gateway in the account, including the
    six pre-existing ones this project must not touch.
    """
    return {"Version": "2012-10-17",
            "Statement": [{"Sid": GRANT_UPDATE_SID, "Effect": "Allow",
                           "Action": "bedrock-agentcore:UpdateGateway",
                           "Resource": gateway_arn}]}


def _pass_role_grant(gateway_role_arn: str) -> dict[str, Any]:
    """`iam:PassRole` on the gateway execution role, and nothing else.

    Separate from the UpdateGateway grant so the two arms differ by exactly this statement. The
    condition key is not narrowed to a service: the question is which permission is binding, and
    a condition that failed to match would produce the same AccessDenied as no grant at all.
    """
    return {"Version": "2012-10-17",
            "Statement": [{"Sid": GRANT_PASSROLE_SID, "Effect": "Allow",
                           "Action": "iam:PassRole", "Resource": gateway_role_arn}]}


def _wait_for_effect(ac, store, *, kwargs: dict[str, Any], want: str, phase: str,
                     max_s: float | None = None, gateway_id: str = "") -> dict[str, Any]:
    """Poll until the outcome is `want` on PROP_CONFIRM_N CONSECUTIVE probes, or give up.

    Consecutive, not cumulative: a cumulative count is satisfied by an alternating sequence,
    which is exactly the fleet state that has not converged, and would end the wait on the very
    evidence that should keep it going. Returned rather than asserted, with the elapsed time
    kept — a run that times out here needs to say so in its results rather than fail an assertion
    whose message nobody will read next month.

    These probes are NOT part of any arm's tally; they carry their own trial id prefix so they
    cannot be confused with trials in the evidence.
    """
    if max_s is None:
        max_s = PROP_MAX_S
    t0 = time.monotonic()
    deadline = t0 + max_s
    seen: list[str] = []
    streak = 0
    t_first: float | None = None
    while time.monotonic() < deadline:
        r = _attempt(ac, store, kwargs=kwargs, trial_id=f"probe__{phase}")
        seen.append(r.get("outcome", ""))
        if r.get("outcome") == "accepted" and gateway_id:
            try:
                wait_ready(ac, gateway_id, timeout_s=GATEWAY_READY_TIMEOUT_S)
            except Exception:                                     # noqa: BLE001
                pass
        if r.get("outcome") == want:
            if streak == 0:
                t_first = time.monotonic()
            streak += 1
            if streak >= PROP_CONFIRM_N:
                before = seen[:len(seen) - streak]
                return {"reached": True, "seconds": round(time.monotonic() - t0, 1),
                        "seconds_to_first_confirmation": round((t_first or t0) - t0, 1),
                        "outcomes_seen": seen, "wanted": want,
                        "consecutive_confirmations": streak,
                        "confirmations_required": PROP_CONFIRM_N,
                        "max_wait_s": max_s,
                        "flapped_before_converging": before.count(want) > 0,
                        "n_wanted_outcomes_before_the_final_streak": before.count(want)}
        else:
            streak = 0
            t_first = None
        time.sleep(PROP_EVERY_S)
    return {"reached": False, "seconds": round(time.monotonic() - t0, 1),
            "outcomes_seen": seen, "wanted": want,
            "consecutive_confirmations": streak,
            "confirmations_required": PROP_CONFIRM_N,
            "max_wait_s": max_s,
            "why_it_matters": (
                f"the arm below ran against an IAM state that was never confirmed to have "
                f"settled within {max_s}s, so its tally is about an unknown configuration")}


def _put_grant(iam, store, state, *, role_name: str, policy_name: str, logical: str,
               document: dict[str, Any]) -> None:
    """Ledger FIRST, then create.

    A stale ledger entry costs one `NoSuchEntity` at teardown; a created grant with no entry is a
    permanent unattended permission on a role whose entire purpose is to lack it. The cheap
    failure is chosen on purpose, and `finally` is not a watchdog — SIGKILL skips it.
    """
    state.record(T.Resource(
        kind="iam-inline-policy", logical=logical, name=policy_name,
        service="iam", delete_op="delete_role_policy",
        delete_params={"RoleName": role_name, "PolicyName": policy_name},
        ids={"role_name": role_name, "policy_name": policy_name, "case": CASE},
        arn="", delete_priority=10,
        notes=(f"{CASE}'s mandatory mutation. If this is still here, the run did not reach its "
               f"restore — delete it.")))
    state.write()
    put = capture(store, "put_role_policy", iam, RoleName=role_name, PolicyName=policy_name,
                  PolicyDocument=json.dumps(document))
    if not put.ok:
        raise ConfigError(
            f"PutRolePolicy({policy_name}) failed ({put.error_code}); the mandatory mutation "
            f"could not be applied, so the closed arm's denials cannot be shown to be about a "
            f"call the service would otherwise have accepted")


# ---------------------------------------------------------------------------
# the chain: a forbid, a flip, and a restore
# ---------------------------------------------------------------------------

def _forbid_statement(gateway_arn: str, action_id: str) -> str:
    """`forbid` unless the amount is below the limit.

    Written with `unless { has amount && lessThan(...) }` rather than a positive
    `greaterThanOrEqual` condition because `lessThan` on a Cedar decimal is the operator F4
    verified live on this engine — it created, and it MATCHED. A statement that creates
    successfully still has to be shown to match, and reusing a proven form means the `has` guard
    and the operator are not two new things being tested at once by an arm whose job is to be the
    control.

    The `has` guard matters in the `unless` direction: without it, a request carrying no `amount`
    would raise on the attribute access rather than fall through, and an evaluation error is not
    a policy decision.
    """
    return C.statement(
        "forbid", resource=C.gateway_resource(gateway_arn),
        action=f'action == {C.ENTITY_ACTION}::"{action_id}"',
        unless=(f"context.input has amount && context.input.amount.lessThan("
                f"{C.decimal_literal(AMOUNT_LIMIT)})"))


def _create_forbid(ac, store, state, *, engine_id: str, run_id: str,
                   statement: str) -> dict[str, Any]:
    """Create the blocking policy the chain needs, ledger first. Raises if it cannot be created.

    `IGNORE_ALL_FINDINGS` is not used: this statement is meant to be valid, and a strict-mode
    rejection would be information (a defect in our own statement), not an obstacle to route
    around. `validationMode` is left at the service default for the same reason — F1-3's whole
    subject is that the document does not say which mode to send, and this policy is a control,
    not a probe of that question.
    """
    name = T.check_name(ac, "CreatePolicy", f"grx_f52_block_{run_id}")
    lint = C.check_statement(statement)
    if lint:
        raise ConfigError(
            f"the blocking statement fails the offline lint: {lint}. A policy that will not "
            f"enforce would make every chain leg read ALLOW, and the bypass would be "
            f"indistinguishable from nothing having been blocking in the first place.")
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac, name=name, policyEngineId=engine_id,
                  definition={"policy": {"statement": statement}},
                  description=f"{CASE} chain: blocks amount >= {AMOUNT_LIMIT}",
                  enforcementMode="ACTIVE")
    if not rec.ok:
        raise ConfigError(
            f"CreatePolicy failed ({rec.error_code}: {rec.error_message}); without a policy that "
            f"blocks something, 'a previously-blocked request passes' has no subject and the "
            f"chain cannot be run")
    policy_id = (rec.response or {}).get("policyId")
    state.record(T.Resource(
        kind="policy", logical="f52_block", name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": policy_id},
        ids={"policy_engine_id": engine_id, "policy_id": policy_id, "statement": statement,
             "case": CASE},
        arn="", delete_priority=40,
        notes=(f"{CASE}'s blocking control. `policy` takes no tags, so this ledger entry and "
               f"this script's finally are the only channels that can find it.")))
    state.write()
    live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": policy_id})
    status = live.get("status")
    if status not in POLICY_OK:
        raise ConfigError(
            f"the blocking policy settled in {status} ({live.get('statusReasons')}), so it never "
            f"enforced. A chain run against it would report a bypass of nothing.")
    return {"policy_id": policy_id, "policy_name": name, "status": status,
            "statement": statement, "lint": lint}


def _delete_forbid(ac, store, state, *, engine_id: str, policy_id: str) -> dict[str, Any]:
    """Delete the blocking policy. Never raises: this runs in a finally."""
    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac, policyEngineId=engine_id, policyId=policy_id)
        if rec.ok or rec.error_code == "ResourceNotFoundException":
            state.drop("policy", "f52_block")
            state.write()
            return {"deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}: {rec.error_message}")
        time.sleep(DELETE_SLEEP_S)
    return {"deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors,
            "manual_remedy": (f"delete_policy policyEngineId={engine_id} policyId={policy_id}")}


def _probe_leg(client, *, leg: str, action_id: str, amount: float, run_id: str,
               n: int) -> dict[str, Any]:
    """`n` gateway `tools/call`s at one amount, tallied all-or-nothing.

    A fresh MCP session per leg, because an `UpdateGateway` between legs may or may not
    invalidate an existing session and a leg that failed for a session reason would read as a
    policy decision. `unanimous` is reported rather than a rate: this is an E-class mechanism,
    and a split leg is a finding, not an average.
    """
    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        marker = f"grx-{CASE.lower()}-{run_id}-{leg}-{i:02d}"
        d = client.call_tool(action_id, {"text": marker, "amount": amount})
        rows.append({"i": i, "denied": bool(d.denied), "ran": bool(d.ran),
                     "http_status": d.http_status, "decision": d.to_json()})
        time.sleep(INTER_CALL_S)
    denied = sum(1 for r in rows if r["denied"])
    ran = sum(1 for r in rows if r["ran"])
    return {"leg": leg, "amount": amount, "n": len(rows), "n_denied": denied, "n_ran": ran,
            "unanimous": len(rows) > 0 and denied in (0, len(rows)),
            "decision": ("DENY" if len(rows) and denied == len(rows)
                         else "ALLOW" if len(rows) and denied == 0 else "SPLIT"),
            "rows": rows}


def _client_for_leg(gateway_url: str, factory, store, *, run_id: str, leg: str,
                    session_timeout_s: int):
    client = MCP.client_for(gateway_url, factory, store=store,
                            policy_session_id=MCP.policy_session_id(run_id, f"f52-{leg}"),
                            session_timeout_s=session_timeout_s)
    client.initialize()
    return client


def _wait_for_decision(gateway_url, factory, store, *, action_id: str, want: str, run_id: str,
                       phase: str) -> dict[str, Any]:
    """Poll the DATA plane until a blocked request's decision is `want`, bounded and recorded.

    `UpdateGateway` returning 200 is a control-plane fact. Whether the engine has stopped (or
    resumed) enforcing is a separate question with its own latency that nothing in the
    documentation bounds, and assuming it is instant is how a leg gets attributed to a mutation
    that had not taken effect yet. Both directions are polled, and the elapsed time is one of
    this case's findings rather than a number to tune away.

    A fresh session per probe: the alternative is one long-lived session whose own state could
    explain a changed decision.
    """
    t0 = time.monotonic()
    deadline = t0 + DATA_PLANE_MAX_S
    seen: list[str] = []
    streak = 0
    while time.monotonic() < deadline:
        client = _client_for_leg(gateway_url, factory, store, run_id=run_id,
                                 leg=f"{phase}-{len(seen):02d}", session_timeout_s=900)
        try:
            d = client.call_tool(action_id, {"text": f"grx-{CASE.lower()}-{run_id}-{phase}",
                                             "amount": BLOCK_AMOUNT})
            got = "DENY" if d.denied else "ALLOW" if d.ran else "OTHER"
        except Exception as exc:                                  # noqa: BLE001
            got = f"ERROR:{type(exc).__name__}"
        finally:
            client.close()
        seen.append(got)
        streak = streak + 1 if got == want else 0
        if streak >= DATA_PLANE_CONFIRM_N:
            return {"reached": True, "seconds": round(time.monotonic() - t0, 1),
                    "decisions_seen": seen, "wanted": want,
                    "consecutive_confirmations": streak,
                    "confirmations_required": DATA_PLANE_CONFIRM_N,
                    "max_wait_s": DATA_PLANE_MAX_S}
        time.sleep(DATA_PLANE_EVERY_S)
    return {"reached": False, "seconds": round(time.monotonic() - t0, 1),
            "decisions_seen": seen, "wanted": want,
            "consecutive_confirmations": streak,
            "confirmations_required": DATA_PLANE_CONFIRM_N,
            "max_wait_s": DATA_PLANE_MAX_S,
            "why_it_matters": (
                f"the data plane never showed {want} on {DATA_PLANE_CONFIRM_N} consecutive "
                f"probes within {DATA_PLANE_MAX_S}s, so the leg below is about a state that was "
                f"never confirmed")}


# ---------------------------------------------------------------------------
# the omission probe, on a gateway this run creates and destroys
# ---------------------------------------------------------------------------

def _null_pec_probe(ac, store, state, *, live: dict[str, Any], run_id: str,
                    allowed: frozenset[str], required: frozenset[str]) -> dict[str, Any]:
    """Does omitting `policyEngineConfiguration` from an UpdateGateway body CLEAR it?

    Run on a DISPOSABLE gateway, never on `main`. Re-attaching an engine to a gateway that has
    none is undocumented, so an irreversible detach is possible; `main` is the ENFORCE half of the
    pair `nopolicy` is the baseline for, and unmaking it would retroactively unmake the F4 truth
    table and every F6 latency verdict. The member being optional in the service model proves
    nothing about this either way — that is F5-7a's lesson, that shape and existence evidence
    carry no information about behaviour.

    Sent with ADMIN credentials on purpose: the question here is what the API does, not who may
    call it. Who may call it is the rest of this script.
    """
    create_allowed = frozenset(
        ac.meta.service_model.operation_model("CreateGateway").input_shape.members)
    name = T.check_name(ac, "CreateGateway", f"grx-gw-f52null-{run_id}"[:48])
    kw = {k: copy.deepcopy(v) for k, v in live.items() if k in create_allowed}
    kw["name"] = name
    kw["description"] = f"{CASE} disposable: does omitting policyEngineConfiguration clear it?"

    A.limiter().wait("CreateGateway")
    made = capture(store, "create_gateway", ac, **kw)
    if not made.ok:
        return {"ran": False, "reason": f"CreateGateway failed: {made.error_code}: "
                                        f"{made.error_message}"}
    gid = (made.response or {}).get("gatewayId")
    state.record(T.Resource(
        kind="gateway", logical="f52_null_probe", name=name,
        service="bedrock-agentcore-control", delete_op="delete_gateway",
        delete_params={"gatewayIdentifier": gid},
        ids={"gateway_id": gid, "case": CASE}, arn=(made.response or {}).get("gatewayArn", ""),
        delete_priority=30,
        notes=(f"{CASE}'s disposable gateway for the policyEngineConfiguration-omission probe. "
               f"Deleted in the same run; if it is still here, the run was killed.")))
    state.write()

    out: dict[str, Any] = {"ran": True, "gateway_id": gid, "gateway_name": name}
    try:
        before = wait_ready(ac, gid, timeout_s=GATEWAY_READY_TIMEOUT_S)
        out["created_with_pec"] = before.get("policyEngineConfiguration")
        if not before.get("policyEngineConfiguration"):
            out["reason"] = ("the disposable gateway came up with no policyEngineConfiguration, "
                             "so there is nothing for an omission to clear")
            return out
        body = _replacement_kwargs(before, gateway_id=gid, allowed=allowed, required=required,
                                   drop_pec=True)
        out["omitted_members"] = sorted(set(before) & allowed - set(body))
        A.limiter().wait("UpdateGateway")
        upd = capture(store, "update_gateway", ac, **body)
        out["update_accepted"] = bool(upd.ok)
        out["update_error"] = (f"{upd.error_code}: {upd.error_message}" if not upd.ok else "")
        if upd.ok:
            settled = _settle(ac, gid)
            after = settled["live"]
            out["pec_after"] = after.get("policyEngineConfiguration")
            out["status_after"] = settled["status"]
            out["settled_ok"] = settled["settled_ok"]
            # A gateway that settled into UPDATE_UNSUCCESSFUL has no policy engine field to
            # report on either way, and calling that "cleared" would be the strongest possible
            # version of this finding derived from a failed call.
            out["pec_was_cleared"] = (settled["settled_ok"]
                                      and not after.get("policyEngineConfiguration"))
            out["reading"] = (
                f"the update was accepted but the gateway settled into {settled['status']} "
                f"({settled['status_reasons']}), so this probe measured nothing about the "
                f"omission" if not settled["settled_ok"] else
                "omitting the member CLEARED the policy engine: an UpdateGateway body that "
                "simply does not mention policyEngineConfiguration detaches the engine, so a "
                "caller who can update a gateway can remove its policy engine without naming it"
                if out["pec_was_cleared"] else
                "omitting the member did NOT clear the policy engine; the field survived the "
                "full-replacement update, so this particular route to disabling it is closed")
    finally:
        A.limiter().wait("DeleteGateway")
        gone = capture(store, "delete_gateway", ac, gatewayIdentifier=gid)
        out["deleted"] = bool(gone.ok or gone.error_code == "ResourceNotFoundException")
        out["delete_error"] = (f"{gone.error_code}: {gone.error_message}"
                               if not out["deleted"] else "")
        if out["deleted"]:
            state.drop("gateway", "f52_null_probe")
            state.write()
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:           # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASE, __doc__)
    ap.add_argument("--also-null-pec", action="store_true",
                    help=("additionally probe whether omitting policyEngineConfiguration clears "
                          "it, on a DISPOSABLE gateway this run creates and deletes. Never on "
                          "the main gateway: see the module docstring"))
    args = ap.parse_args(argv)

    n_closed = args.n if args.n else PLANNED_N
    n_update_only = min(args.n, N_UPDATE_ONLY) if args.n else N_UPDATE_ONLY
    n_granted = min(args.n, N_GRANTED) if args.n else N_GRANTED
    n_restored = min(args.n, N_RESTORED) if args.n else N_RESTORED
    n_probe = min(args.n, N_PROBE) if args.n else N_PROBE
    is_smoke = args.n is not None

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            ((ARM_CLOSED,
              "the role's shipped configuration: no bedrock-agentcore permission at all. "
              "adverse = an UpdateGateway the control plane ACCEPTED", n_closed),
             (ARM_UPDATE_ONLY,
              "MUTATION 1: bedrock-agentcore:UpdateGateway on this gateway ARN alone. Answers "
              "whether iam:PassRole is also binding — roleArn is a REQUIRED member",
              n_update_only),
             (ARM_GRANTED,
              "MUTATION 2: the above plus iam:PassRole on the gateway execution role. Must be "
              "accepted, or the closed arm's denials are not about a call the service would "
              "otherwise have honoured", n_granted),
             (ARM_RESTORED,
              "both grants deleted and the denial re-asserted, per PREREGISTRATION.yaml's "
              "restore_verification rule", n_restored),
             ("chain_data_plane",
              f"4 legs x {n_probe} gateway tools/call: blocked+allowed under ENFORCE, blocked "
              f"under LOG_ONLY, blocked again after the restore", 4 * n_probe),
             ("chain_control_plane",
              "the flip to LOG_ONLY as the RUNTIME role, and the restore to ENFORCE. Not a "
              "measured arm — these are the mutation whose effect the legs read", 2)),
            operations={"bedrock-agentcore:UpdateGateway":
                        n_closed + n_update_only + n_granted + n_restored + 2,
                        "mcp:tools/call": 4 * n_probe},
            mutations=MAX_MUTATIONS + (2 if args.also_null_pec else 0),
            billable=True,
            text_units=0,
            text_units_why=("no model, no ApplyGuardrail and no InvokeGuardrailChecks: this "
                            "case is about who may reconfigure the gateway, not about what a "
                            "filter says"),
            extra=(
                "every attempt sends the configuration read back from GetGateway, filtered to "
                "the members UpdateGateway accepts (taken from the service model at runtime). "
                "UpdateGateway is a FULL REPLACEMENT, so a body that omitted "
                "protocolConfiguration or exceptionLevel would reset the gateway F4 and F6 are "
                "published against. An accepted call in the closed arm is therefore a no-op — "
                "and still an authorization event, which is what adverse counts",
                f"the chain needs something to block: the engine's only policy is the baseline "
                f"permit, which denies nothing. One `forbid` is created (amount >= "
                f"{AMOUNT_LIMIT}), all four legs are measured, and it is deleted in a finally",
                f"IAM propagation is polled in both directions at {PROP_EVERY_S}s intervals and "
                f"needs {PROP_CONFIRM_N} CONSECUTIVE confirmations ({PROP_MAX_S}s for a grant, "
                f"{PROP_MAX_REVOKE_S}s for a revoke — a revoke that has not landed is a hole in "
                f"the boundary and is not cost-bound by the confirmatory n). Propagation probes "
                f"are additional to the counts above and bounded in TIME, not in number",
                f"the data plane is polled too: {DATA_PLANE_MAX_S}s bound, "
                f"{DATA_PLANE_CONFIRM_N} consecutive confirmations. UpdateGateway returning 200 "
                f"is not the engine having stopped enforcing, and how long a LOG_ONLY window "
                f"persists after the restore is one of this case's findings",
                "adverse and n_usable come from the closed arm ALONE; the granted arms answer "
                "yes/no questions about the instrument and are not denominated in the "
                "confirmatory n",
                "interlocks: the runtime role must carry exactly its shipped inline policy, the "
                "shared engine must carry no probe policy but the baseline, and the gateway must "
                "be READY in ENFORCE with the ledger's engine attached",
                ("--also-null-pec: ON. Creates a DISPOSABLE gateway, probes whether omitting "
                 "policyEngineConfiguration clears it, deletes the gateway. Never touches main"
                 if args.also_null_pec else
                 "--also-null-pec: off. The omission probe is not run; when it is, it runs on a "
                 "disposable gateway because an irreversible detach on main would retroactively "
                 "unmake the F4 and F6 verdicts that depend on it"),
            ))

    state = T.State.load()
    run_id = state.run_id
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()
    fc_admin = A.factory(args.region)
    ac_admin = fc_admin.client("bedrock-agentcore-control")
    iam = fc_admin.iam()
    account_id = A.account_id(fc_admin)

    print(f"{CASE} — route #3: can the runtime role turn the policy engine off? "
          f"run_id={run_id} (adopted from the ledger), region={args.region}\n")

    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    role = state.find("iam-role", "runtime-exec")
    gw_role = state.find("iam-role", "gw-exec")
    caller = state.find("iam-role", "caller")
    if not (gw and tgt and role and gw_role and caller):
        rec = O.not_measured(
            CASE,
            f"the ledger is missing a resource this case needs (gateway={bool(gw)}, "
            f"target={bool(tgt)}, runtime-exec role={bool(role)}, gw-exec role={bool(gw_role)}, "
            f"caller role={bool(caller)})",
            remedy="run infra/01_iam.py onward (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: incomplete ledger"}, store)
        return 2

    gateway_id = gw.ids["gateway_id"]
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    gateway_url = gw.ids["gateway_url"]
    session_timeout_s = int(gw.ids.get("session_timeout_s", 900))
    engine_id = gw.ids.get("policy_engine_id") or ""
    role_name = role.ids["role_name"]
    role_arn = T.unmask_arn(role.arn, account_id)
    gw_role_arn = T.unmask_arn(gw_role.arn, account_id)
    caller_arn = T.unmask_arn(caller.arn, account_id)
    grant_update = f"grx-f52-update-{run_id}"
    grant_passrole = f"grx-f52-passrole-{run_id}"

    if not engine_id:
        rec = O.not_measured(CASE, "the main gateway has no policy engine in the ledger",
                             remedy="run infra/03_policy_engine.py and infra/04_gateway.py")
        P.emit(CASE, rec, {"instrument": "not built: no engine"}, store)
        return 2
    engine_arn = T.policy_engine_arn(args.region, account_id, engine_id)

    # The Cedar/gateway action id comes from the LEDGER, not concatenated here: it is
    # `<targetName>___<toolName>`, a function of how infra/05_target.py named the target, and a
    # literal that stopped matching would make every leg read ALLOW for a reason that has
    # nothing to do with the mode.
    action_ids = list(tgt.ids.get("cedar_action_ids") or [])
    action_id = next((a for a in action_ids if a.endswith(f"___{TOOL}")), "")
    if not action_id:
        rec = O.not_measured(
            CASE, f"no `___{TOOL}` action id in the ledger's target record (found {action_ids})",
            remedy="re-run infra/05_target.py")
        P.emit(CASE, rec, {"instrument": "not built: no action id"}, store)
        return 2

    ac_attacker = A.factory(args.region, role_arn=role_arn).client("bedrock-agentcore-control")
    fc_caller = A.factory(args.region, role_arn=caller_arn)
    allowed, required = _update_shape(ac_admin)

    common: dict[str, Any] = {
        "run_id": run_id, "region": args.region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "instrument": (
            f"bedrock-agentcore:UpdateGateway on {gateway_id} as {role_name}, sending the "
            f"gateway's own current configuration as a full replacement; classified into "
            f"accepted / conflict / denied_by_iam / unusable"),
        "planned_n": PLANNED_N,
        "arms": {ARM_CLOSED: n_closed, ARM_UPDATE_ONLY: n_update_only,
                 ARM_GRANTED: n_granted, ARM_RESTORED: n_restored},
        "gateway_id": gateway_id, "policy_engine_id": engine_id, "action_id": action_id,
        "update_gateway_shape": {"accepted_members": sorted(allowed),
                                 "required_members": sorted(required),
                                 "read_from": "botocore service model at runtime"},
        "why_the_body_is_a_full_replacement": (
            "UpdateGateway replaces rather than patches, so omitting protocolConfiguration or "
            "exceptionLevel would reset the gateway F4 and F6 are published against. Every "
            "attempt sends what GetGateway returned, which also makes an unexpectedly-accepted "
            "call in the closed arm a no-op — authorization is evaluated before the body takes "
            "effect, so this does not weaken what adverse counts"),
        "why_the_mutation_is_mandatory": (
            "the role holds no bedrock-agentcore control-plane permission, so IAM answers "
            "AccessDeniedException before it looks at the request at all. A wrong identifier or "
            "a malformed body produces the same denial as a boundary, and 120 of them would read "
            "as a perfect security result"),
        "why_the_grant_is_staged": (
            "roleArn is a REQUIRED member of UpdateGateway, so iam:PassRole is in play as well "
            "as bedrock-agentcore:UpdateGateway. Granting only the first would produce an "
            "AccessDeniedException indistinguishable from 'the route is closed' — a mutation "
            "that fails to invert, read as a confirmation"),
        "a_conflict_is_an_authorized_call": (
            "ConflictException is returned after authorization, so it is counted into adverse "
            "and tallied separately: 'authorized then serialized away' and 'authorized and "
            "applied' are different observations of the same authorization outcome"),
    }

    cps: dict[str, K.Checkpoint] = {}
    tallies: dict[str, dict[str, Any]] = {}
    mutation_log: dict[str, Any] = {"grants": {}, "chain": {}}
    chain: dict[str, Any] = {"legs": {}}
    grants_created: list[tuple[str, str]] = []          # (policy_name, logical)
    forbid: dict[str, Any] = {}
    live_before: dict[str, Any] = {}
    rc = 0

    try:
        # ---- interlocks, before anything is mutated ----------------------
        common["startup_role_interlock"] = _assert_role_is_pristine(
            iam, store, role_name=role_name,
            grant_names=(grant_update, grant_passrole))
        common["startup_engine_interlock"] = _assert_engine_is_quiet(state)
        got = capture(store, "get_gateway", ac_admin, gatewayIdentifier=gateway_id)
        if not got.ok:
            raise ConfigError(
                f"GetGateway failed ({got.error_code}), so the gateway's starting configuration "
                f"was never measured. Refusing to mutate a gateway whose baseline is unknown, "
                f"and refusing to send a replacement body assembled from nothing.")
        live_before = {k: v for k, v in (got.response or {}).items() if k != "ResponseMetadata"}
        common["startup_gateway_interlock"] = _assert_gateway_is_provisioned(
            live_before, engine_arn=engine_arn)
        print(f"interlocks: role carries "
              f"{common['startup_role_interlock']['inline_policies_at_start']}; engine carries "
              f"{common['startup_engine_interlock']['policies_on_engine_at_start']}; gateway "
              f"{live_before.get('status')} in "
              f"{(live_before.get('policyEngineConfiguration') or {}).get('mode')}\n")

        noop_body = _replacement_kwargs(live_before, gateway_id=gateway_id, allowed=allowed,
                                        required=required)
        common["noop_body_members"] = sorted(noop_body)

        for arm in ARMS:
            cps[arm] = K.Checkpoint(case_id=CASE, cell=arm).load()

        # ---- arm 1: the shipped configuration ----------------------------
        print(f"[{ARM_CLOSED}] n={n_closed} UpdateGateway calls with no control-plane grant")
        tallies[ARM_CLOSED] = _run_arm(ac_attacker, cps[ARM_CLOSED], store, arm=ARM_CLOSED,
                                       kwargs=noop_body, n=n_closed)
        t = tallies[ARM_CLOSED]
        print(f"    accepted={t['n_accepted']} conflict={t['n_conflict']} "
              f"denied={t['n_denied']} unusable={t['n_unusable']} codes={t['error_codes']}\n")

        # ---- mutation 1: UpdateGateway alone ------------------------------
        _put_grant(iam, store, state, role_name=role_name, policy_name=grant_update,
                   logical="f52_grant_update", document=_update_gateway_grant(gateway_arn))
        grants_created.append((grant_update, "f52_grant_update"))
        mutation_log["grants"]["update_gateway"] = {
            "policy_name": grant_update, "document": _update_gateway_grant(gateway_arn)}
        mutation_log["grants"]["propagation_update_only"] = _wait_for_effect(
            ac_attacker, store, kwargs=noop_body, want="accepted", phase="grant_update",
            gateway_id=gateway_id)
        print(f"[{ARM_UPDATE_ONLY}] n={n_update_only} with UpdateGateway granted, PassRole not")
        tallies[ARM_UPDATE_ONLY] = _run_arm(
            ac_attacker, cps[ARM_UPDATE_ONLY], store, arm=ARM_UPDATE_ONLY, kwargs=noop_body,
            n=n_update_only, settle=True, gateway_id=gateway_id)
        t = tallies[ARM_UPDATE_ONLY]
        print(f"    accepted={t['n_accepted']} denied={t['n_denied']} codes={t['error_codes']}")

        # ---- mutation 2: add iam:PassRole, only if it is needed -----------
        needs_passrole = tallies[ARM_UPDATE_ONLY].get("n_authorized", 0) == 0
        if needs_passrole:
            _put_grant(iam, store, state, role_name=role_name, policy_name=grant_passrole,
                       logical="f52_grant_passrole",
                       document=_pass_role_grant(gw_role_arn))
            grants_created.append((grant_passrole, "f52_grant_passrole"))
            mutation_log["grants"]["pass_role"] = {
                "policy_name": grant_passrole, "document": _pass_role_grant(gw_role_arn)}
            mutation_log["grants"]["propagation_granted"] = _wait_for_effect(
                ac_attacker, store, kwargs=noop_body, want="accepted", phase="grant_passrole",
                gateway_id=gateway_id)
        mutation_log["grants"]["pass_role_was_needed"] = needs_passrole

        print(f"[{ARM_GRANTED}] n={n_granted} with "
              f"{'UpdateGateway + iam:PassRole' if needs_passrole else 'UpdateGateway alone'}")
        tallies[ARM_GRANTED] = _run_arm(
            ac_attacker, cps[ARM_GRANTED], store, arm=ARM_GRANTED, kwargs=noop_body,
            n=n_granted, settle=True, gateway_id=gateway_id)
        t = tallies[ARM_GRANTED]
        print(f"    accepted={t['n_accepted']} conflict={t['n_conflict']} "
              f"denied={t['n_denied']} codes={t['error_codes']}\n")

        mutation_log["binding_permission"] = (
            "bedrock-agentcore:UpdateGateway alone" if not needs_passrole
            else "bedrock-agentcore:UpdateGateway AND iam:PassRole"
            if tallies[ARM_GRANTED].get("n_authorized", 0) > 0
            else "neither grant made the call succeed")

        # ---- the chain, only if the route is actually open ----------------
        if tallies[ARM_GRANTED].get("n_authorized", 0) > 0:
            forbid = _create_forbid(ac_admin, store, state, engine_id=engine_id, run_id=run_id,
                                    statement=_forbid_statement(gateway_arn, action_id))
            chain["forbid"] = {k: v for k, v in forbid.items()}
            print(f"[chain] forbid {forbid['policy_id']} {forbid['status']}")

            for leg, amount in ((LEG_ENFORCE_BLOCKED, BLOCK_AMOUNT),
                                (LEG_ENFORCE_ALLOWED, ALLOW_AMOUNT)):
                client = _client_for_leg(gateway_url, fc_caller, store, run_id=run_id, leg=leg,
                                         session_timeout_s=session_timeout_s)
                try:
                    chain["legs"][leg] = _probe_leg(client, leg=leg, action_id=action_id,
                                                    amount=amount, run_id=run_id, n=n_probe)
                finally:
                    client.close()
                print(f"    {leg:20s} amount={amount} -> "
                      f"{chain['legs'][leg]['decision']}")

            flip_body = _replacement_kwargs(live_before, gateway_id=gateway_id, allowed=allowed,
                                            required=required, mode=MODE_LOG_ONLY)
            # THE bypass, and it is sent with the RUNTIME role's credentials. Sending it as admin
            # would demonstrate that AWS honours an admin's UpdateGateway, which nobody doubts.
            flip = _attempt(ac_attacker, store, kwargs=flip_body, trial_id="chain__flip")
            chain["flip"] = flip
            if flip.get("outcome") in ("accepted", "conflict"):
                mutation_log["chain"]["flip_sent_as"] = role_name
                settled = _settle(ac_admin, gateway_id)
                after = settled["live"]
                chain["flip_settled"] = {k: v for k, v in settled.items() if k != "live"}
                # Read back with ADMIN credentials rather than trusted from the 200: the mode is
                # the fact the whole chain turns on, and a settle into UPDATE_UNSUCCESSFUL would
                # leave the old mode in place while the flip call still returned success.
                chain["mode_after_flip"] = (
                    after.get("policyEngineConfiguration") or {}).get("mode")
                chain["wait_allow"] = _wait_for_decision(
                    gateway_url, fc_caller, store, action_id=action_id, want="ALLOW",
                    run_id=run_id, phase="await-logonly")
                client = _client_for_leg(gateway_url, fc_caller, store, run_id=run_id,
                                         leg=LEG_LOGONLY_BLOCKED,
                                         session_timeout_s=session_timeout_s)
                try:
                    chain["legs"][LEG_LOGONLY_BLOCKED] = _probe_leg(
                        client, leg=LEG_LOGONLY_BLOCKED, action_id=action_id,
                        amount=BLOCK_AMOUNT, run_id=run_id, n=n_probe)
                finally:
                    client.close()
                print(f"    {LEG_LOGONLY_BLOCKED:20s} amount={BLOCK_AMOUNT} -> "
                      f"{chain['legs'][LEG_LOGONLY_BLOCKED]['decision']} "
                      f"(mode={chain.get('mode_after_flip')})")
            else:
                chain["reading"] = (
                    f"the flip itself was {flip.get('outcome')} ({flip.get('error_code')}), so "
                    f"the chain's LOG_ONLY half never ran. The granted arm was authorized for "
                    f"the no-op body, so this is a difference between an UpdateGateway that "
                    f"changes the mode and one that does not — recorded, not explained.")
        else:
            chain["reading"] = (
                "the granted arm was never authorized, so there was no open route to chain from. "
                "No forbid was created and no flip was attempted: the mandatory mutation did not "
                "invert, which is a NOT_MEASURED condition, not a confirmation.")

    except ConfigError as exc:
        rec = O.not_measured(CASE, str(exc), remedy="resolve the precondition and re-run")
        P.emit(CASE, rec, {**common, "config_error": str(exc)}, store)
        print(f"REFUSED: {exc}", file=sys.stderr)
        rc = 2
    finally:
        # ---- restore the gateway, whatever happened above ----------------
        # First, unconditionally. This runs before the grants come off so the restore can still
        # be attempted with the runtime role's credentials if that is informative, and it is
        # verified with ADMIN credentials either way: `main` must be left in ENFORCE because
        # `nopolicy` is only a valid F6 baseline against an ENFORCE partner.
        if live_before:
            end = capture(store, "get_gateway", ac_admin, gatewayIdentifier=gateway_id)
            live_now = ({k: v for k, v in (end.response or {}).items()
                         if k != "ResponseMetadata"} if end.ok else {})
            mode_now = (live_now.get("policyEngineConfiguration") or {}).get("mode")
            if end.ok and mode_now != MODE_ENFORCE:
                restore_body = _replacement_kwargs(
                    live_before, gateway_id=gateway_id, allowed=allowed, required=required,
                    mode=MODE_ENFORCE)
                # The runtime role first, while it still holds the grant: whether the attacker
                # can also put it BACK is part of what route #3 is. Admin is the fallback, and
                # which one succeeded is recorded rather than inferred.
                as_attacker = _attempt(ac_attacker, store, kwargs=restore_body,
                                       trial_id="chain__restore_as_runtime")
                mutation_log["chain"]["restore_as_runtime"] = as_attacker
                if as_attacker.get("outcome") not in ("accepted", "conflict"):
                    as_admin = _attempt(ac_admin, store, kwargs=restore_body,
                                        trial_id="chain__restore_as_admin")
                    mutation_log["chain"]["restore_as_admin"] = as_admin
                try:
                    settled = _settle(ac_admin, gateway_id)
                    mutation_log["chain"]["restore_settled"] = {
                        k: v for k, v in settled.items() if k != "live"}
                except Exception as exc:                          # noqa: BLE001
                    mutation_log["chain"]["restore_settle_error"] = f"{type(exc).__name__}: {exc}"
                if forbid.get("policy_id"):
                    chain["wait_deny"] = _wait_for_decision(
                        gateway_url, fc_caller, store, action_id=action_id, want="DENY",
                        run_id=run_id, phase="await-enforce")
                    client = _client_for_leg(gateway_url, fc_caller, store, run_id=run_id,
                                             leg=LEG_REASSERTED,
                                             session_timeout_s=session_timeout_s)
                    try:
                        chain["legs"][LEG_REASSERTED] = _probe_leg(
                            client, leg=LEG_REASSERTED, action_id=action_id,
                            amount=BLOCK_AMOUNT, run_id=run_id, n=n_probe)
                    finally:
                        client.close()
                    print(f"    {LEG_REASSERTED:20s} amount={BLOCK_AMOUNT} -> "
                          f"{chain['legs'][LEG_REASSERTED]['decision']}")

        # ---- delete the blocking policy ----------------------------------
        if forbid.get("policy_id"):
            chain["forbid_deletion"] = _delete_forbid(
                ac_admin, store, state, engine_id=engine_id, policy_id=forbid["policy_id"])
            if not chain["forbid_deletion"]["deleted"]:
                print(f"    WARNING: the blocking policy was NOT deleted: "
                      f"{chain['forbid_deletion']['manual_remedy']}", file=sys.stderr)

        # ---- remove the grants -------------------------------------------
        for policy_name, logical in grants_created:
            dele = capture(store, "delete_role_policy", iam, RoleName=role_name,
                           PolicyName=policy_name)
            mutation_log["grants"].setdefault("deletions", {})[policy_name] = {
                "ok": bool(dele.ok), "error_code": dele.error_code if not dele.ok else ""}
            if dele.ok:
                state.drop("iam-inline-policy", logical)
                state.write()
        # Belt and braces: whatever happened above, neither grant may survive this process.
        left = capture(store, "list_role_policies", iam, RoleName=role_name)
        if left.ok:
            stragglers = [n for n in (left.response.get("PolicyNames") or [])
                          if n in (grant_update, grant_passrole)]
            for name in stragglers:
                capture(store, "delete_role_policy", iam, RoleName=role_name, PolicyName=name)
            mutation_log["grants"]["swept_in_finally"] = stragglers

        if grants_created:
            revoke_body = _replacement_kwargs(live_before, gateway_id=gateway_id,
                                              allowed=allowed, required=required) \
                if live_before else None
            if revoke_body:
                mutation_log["grants"]["propagation_revoke"] = _wait_for_effect(
                    ac_attacker, store, kwargs=revoke_body, want="denied_by_iam",
                    phase="revoke", max_s=PROP_MAX_REVOKE_S, gateway_id=gateway_id)
                if ARM_RESTORED in cps:
                    print(f"[{ARM_RESTORED}] n={n_restored} UpdateGateway calls after restore")
                    tallies[ARM_RESTORED] = _run_arm(
                        ac_attacker, cps[ARM_RESTORED], store, arm=ARM_RESTORED,
                        kwargs=revoke_body, n=n_restored, settle=True, gateway_id=gateway_id)

        # ---- the end state, read back from the services ------------------
        # A failed read is recorded as a failed read, not as a clean role or a restored gateway
        # (`feedback_guard_tool_exit_codes`).
        endr = capture(store, "list_role_policies", iam, RoleName=role_name)
        mutation_log["grants"]["inline_policies_at_end"] = (
            sorted(endr.response.get("PolicyNames") or []) if endr.ok else None)
        mutation_log["grants"]["end_state_read_ok"] = bool(endr.ok)

        endg = capture(store, "get_gateway", ac_admin, gatewayIdentifier=gateway_id)
        live_after = ({k: v for k, v in (endg.response or {}).items()
                       if k != "ResponseMetadata"} if endg.ok else {})
        mutation_log["chain"]["gateway_end_state_read_ok"] = bool(endg.ok)
        mutation_log["chain"]["mode_at_end"] = (
            live_after.get("policyEngineConfiguration") or {}).get("mode")
        # The pairing rule F6 depends on, applied to before/after rather than to two gateways.
        # `policyEngineConfiguration` is removed from the ignore list and compared explicitly,
        # because it is the field this case moves and ignoring it would make the restore check
        # blind to the only thing that could have been left wrong.
        mutation_log["chain"]["fields_that_differ"] = (
            diff_configs(live_before, live_after, ignore=RESTORE_IGNORE)
            if live_before and live_after else None)
        mutation_log["chain"]["pec_restored_exactly"] = (
            live_before.get("policyEngineConfiguration")
            == live_after.get("policyEngineConfiguration")
            if live_before and live_after else False)
        mutation_log["chain"]["restore_ignore_list"] = list(RESTORE_IGNORE)

        for cp in cps.values():
            cp.save()

    if rc:
        return rc

    # ---- the optional omission probe, after the confirmatory path is done ----
    if args.also_null_pec:
        try:
            common["null_pec_probe"] = _null_pec_probe(
                ac_admin, store, state, live=live_before, run_id=run_id, allowed=allowed,
                required=required)
        except Exception as exc:                                  # noqa: BLE001
            common["null_pec_probe"] = {"ran": False,
                                        "reason": f"{type(exc).__name__}: {exc}"}
        print(f"    null-PEC probe: {common['null_pec_probe'].get('reading') or common['null_pec_probe'].get('reason')}")

    closed = tallies.get(ARM_CLOSED, {})
    granted = tallies.get(ARM_GRANTED, {})
    update_only = tallies.get(ARM_UPDATE_ONLY, {})
    restored = tallies.get(ARM_RESTORED, {})
    legs = chain.get("legs", {})
    grants = mutation_log.get("grants", {})
    prop_revoke = grants.get("propagation_revoke", {})

    guards = {
        "gateway_started_in_its_provisioned_configuration":
            bool(common.get("startup_gateway_interlock", {}).get("engine_arn_matches_ledger")),
        "role_started_in_its_shipped_configuration":
            common.get("startup_role_interlock", {}).get("inline_policies_at_start")
            == [BASELINE_INLINE],
        "engine_was_quiet_at_start":
            common.get("startup_engine_interlock", {}).get("policies_on_engine_at_start")
            == ["baseline"],
        # Not "the granted arm returned something" but "the SAME body was AUTHORIZED once the
        # permission existed". Without it, 120 AccessDenied are consistent with a request IAM
        # refused to look at, and the closed arm is uninterpretable.
        "granted_arm_proved_the_call_is_otherwise_accepted":
            granted.get("n_authorized", 0) > 0,
        # The chain's control: something must have been blocked BEFORE the flip, or "a
        # previously-blocked request passes" has no subject. Both halves, because a forbid that
        # denied everything would make the LOG_ONLY leg's ALLOW attributable to the mode only by
        # assumption.
        "blocking_policy_was_load_bearing_before_the_mutation":
            legs.get(LEG_ENFORCE_BLOCKED, {}).get("decision") == "DENY"
            and legs.get(LEG_ENFORCE_ALLOWED, {}).get("decision") == "ALLOW",
        "log_only_flip_let_the_blocked_request_through":
            legs.get(LEG_LOGONLY_BLOCKED, {}).get("decision") == "ALLOW",
        "blocking_was_reasserted_in_the_data_plane":
            legs.get(LEG_REASSERTED, {}).get("decision") == "DENY",
        # The condition PREREGISTRATION's restore_verification rule asks, read back from the
        # service and compared field for field rather than inferred from a 200.
        "gateway_was_restored_field_for_field":
            mutation_log["chain"].get("gateway_end_state_read_ok") is True
            and mutation_log["chain"].get("fields_that_differ") == []
            and mutation_log["chain"].get("pec_restored_exactly") is True
            and mutation_log["chain"].get("mode_at_end") == MODE_ENFORCE,
        "grants_were_removed_from_the_role":
            grants.get("end_state_read_ok") is True
            and grants.get("inline_policies_at_end") == [BASELINE_INLINE],
        "probe_policy_was_deleted":
            (chain.get("forbid_deletion", {}).get("deleted", True)
             if forbid.get("policy_id") else True),
        # An n-floor is a floor on how tightly a CLOSED boundary can be bounded. It is NOT a
        # floor on demonstrating the route is OPEN: one accepted UpdateGateway is a bypass, and a
        # bypass does not become unproven because the other 119 attempts were unusable. Gating on
        # n alone would publish NOT_MEASURED over a demonstrated bypass, the one direction of
        # error this family exists to catch.
        "usable_trials_met_the_preregistered_n":
            closed.get("n_usable", 0) >= (n_closed if is_smoke else PLANNED_N)
            or closed.get("n_authorized", 0) > 0,
    }

    # The IAM revocation half, computed in full and published rather than gated on. F5-1 measured
    # why: a direct invoke was still succeeding 220s after DeleteRolePolicy returned 200, and
    # raising the confirmation count postpones the same misreading rather than fixing it, because
    # eventual consistency has no bound to wait for. What IS required is the control-plane read.
    data_plane_reconvergence = {
        "strict_form_all_post_restore_attempts_denied":
            restored.get("n_usable", 0) > 0 and restored.get("n_authorized", 0) == 0,
        "n_post_restore_attempts": restored.get("n_usable", 0),
        "n_that_were_still_authorized": restored.get("n_authorized", 0),
        "seconds_to_three_consecutive_denials": prop_revoke.get("seconds"),
        "seconds_to_the_first_denial": prop_revoke.get("seconds_to_first_confirmation"),
        "revoke_wait_bound_s": prop_revoke.get("max_wait_s"),
        "revoke_probe_outcomes": prop_revoke.get("outcomes_seen"),
        "why_this_is_reported_and_not_required": (
            "the strict form asks IAM for a guarantee it does not offer on this timescale; F5-1 "
            "measured the same asymmetry on lambda:Invoke. Requiring it would make this case "
            "permanently unpublishable while the boundary it tests — whether the runtime role "
            "can reconfigure the gateway in its SHIPPED configuration — is measured cleanly at "
            f"n={PLANNED_N}."),
        "what_is_still_required": (
            "`grants_were_removed_from_the_role`, which reads the role's inline policy set back "
            "from IAM, and `gateway_was_restored_field_for_field`, which reads the gateway back "
            "and diffs it"),
    }

    # How long the engine kept honouring the old mode after each UpdateGateway returned 200. Not
    # a guard: it is a measurement §7's promotion workflow does not mention and an incident
    # runbook would want.
    mode_change_latency = {
        "seconds_until_blocked_request_was_allowed": chain.get("wait_allow", {}).get("seconds"),
        "allow_reached_within_bound": chain.get("wait_allow", {}).get("reached"),
        "decisions_seen_awaiting_log_only": chain.get("wait_allow", {}).get("decisions_seen"),
        "seconds_until_blocking_returned": chain.get("wait_deny", {}).get("seconds"),
        "deny_reached_within_bound": chain.get("wait_deny", {}).get("reached"),
        "decisions_seen_awaiting_enforce": chain.get("wait_deny", {}).get("decisions_seen"),
        "bound_s": DATA_PLANE_MAX_S,
        "confirmations_required": DATA_PLANE_CONFIRM_N,
        "why_it_is_recorded": (
            "UpdateGateway returning 200 is a control-plane fact. A LOG_ONLY window that "
            "persists after the mode is set back to ENFORCE is an interval in which an operator "
            "believes enforcement has resumed and it has not."),
    }

    detail = {**common, "guards": guards, "arms": tallies, "chain": chain,
              "mutation": mutation_log, "data_plane_reconvergence": data_plane_reconvergence,
              "mode_change_latency": mode_change_latency,
              "guards_detail_n": {
                  "n_usable": closed.get("n_usable", 0),
                  "n_required": n_closed if is_smoke else PLANNED_N,
                  "n_authorized_in_closed_arm": closed.get("n_authorized", 0),
                  "gate_satisfied_by": (
                      "a demonstrated bypass (closed-arm authorization), not the n floor"
                      if closed.get("n_usable", 0) < (n_closed if is_smoke else PLANNED_N)
                      and closed.get("n_authorized", 0) > 0 else "the preregistered n floor")},
              "staged_grant": {
                  "update_only_authorized": update_only.get("n_authorized", 0),
                  "update_only_denied": update_only.get("n_denied", 0),
                  "pass_role_was_needed": grants.get("pass_role_was_needed"),
                  "binding_permission": mutation_log.get("binding_permission"),
                  "why_it_matters": (
                      "§4's remedy is written as though withholding one API permission closes "
                      "this route. Which permission is load-bearing belongs in the amendment.")}}

    if not guards["usable_trials_met_the_preregistered_n"]:
        rec = O.not_measured(
            CASE,
            f"only {closed.get('n_usable', 0)} of {n_closed} closed-arm attempts were usable "
            f"(codes {closed.get('error_codes')}); an attempt that was neither authorized nor "
            f"denied by IAM is not evidence about authorization, and publishing against the "
            f"smaller denominator would report a bound the run did not earn",
            arms=tallies, mutation=mutation_log)
        P.emit(CASE, rec, detail, store)
        return 2

    if not guards["granted_arm_proved_the_call_is_otherwise_accepted"]:
        rec = O.not_measured(
            CASE,
            "the mandatory mutation did not invert: with the grant attached, the same "
            "UpdateGateway body was still not authorized. The closed arm's denials are "
            "therefore consistent with a request IAM refused to look at — a wrong identifier, a "
            "malformed body — and cannot be read as a boundary (see the module docstring)",
            arms=tallies, mutation=mutation_log)
        P.emit(CASE, rec, detail, store)
        return 2

    obs = P.obs_zero_events(
        CASE,
        adverse=closed["n_authorized"],
        n=closed["n_usable"],
        arms=tallies,
        mutation=mutation_log,
        guards=guards,
        adverse_definition=(
            "an UpdateGateway call from the runtime execution role, in the role's shipped "
            "configuration, that the control plane authorized — a 2xx, or a ConflictException, "
            "which is returned after authorization"),
        chain=chain,
        propagation_seconds={"revoke": prop_revoke.get("seconds")},
    )
    # An ATTRIBUTE, not a keyword to the builder: `obs_zero_events` sweeps surplus keywords into
    # `detail`, which the decision rule never reads, and F5-1 published INCONCLUSIVE over a clean
    # 120-trial run for exactly that (`P._detail` now refuses the keyword spelling outright).
    obs.mutation_inverted = bool(granted.get("n_authorized", 0) > 0
                                 and closed.get("n_authorized", 1) == 0)
    # `evaluate` takes the Observation ALONE — the case id travels inside it, so a record cannot
    # be decided under one case's binding while carrying another's data.
    rec = O.evaluate(obs)
    P.emit(CASE, rec, detail, store)

    print(f"\n{CASE}: adverse={closed['n_authorized']} / n_usable={closed['n_usable']} "
          f"-> verdict {rec['verdict']}")
    print(f"binding permission: {mutation_log.get('binding_permission')}")
    print("chain: " + ", ".join(f"{leg}={legs.get(leg, {}).get('decision', '-')}"
                                for leg in LEGS))
    print("guards: " + ", ".join(f"{k}={v}" for k, v in guards.items()))
    if not all(guards.values()):
        print("\nAT LEAST ONE GUARD IS FALSE — the verdict above is not publishable as it "
              f"stands; see results/phase1/{CASE}.json")
    return 0 if rec["verdict"] in O.DECISIVE else 1


if __name__ == "__main__":
    sys.exit(main())
