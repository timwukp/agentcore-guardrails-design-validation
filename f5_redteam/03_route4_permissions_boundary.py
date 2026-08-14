#!/usr/bin/env python3
"""F5-3b — route #4: does an IAM permissions boundary actually stop `UpdateGateway`?

    python3 f5_redteam/03_route4_permissions_boundary.py --dry-run
    python3 f5_redteam/03_route4_permissions_boundary.py --n 2      # smoke
    python3 f5_redteam/03_route4_permissions_boundary.py

§4's mitigation table (claim `C-s4-4-trow-010`) tells the reader that the account-level backstop
for a leaked or confused runtime identity is "an SCP (or permission boundary) denying
`UpdateGateway` / policy-engine mutations except from a designated break-glass admin role", and
adds that this "holds even if route #3's role hygiene regresses". F5-2 measured route #3 itself.
This case measures the backstop, on the one identity in this account that exists to be attacked.

The sealed oracle (`F5-3b`, EXISTENCE, alpha 0.05, mandatory mutation arm):

    "TRUE if UpdateGateway is denied despite an identity policy granting it; FALSE if the
     boundary is ineffective. Mutation: remove boundary -> succeeds"

and the sealed method: "permissions boundary on grx-attacker, re-run the F5-2 attack".

WHY THE ATTACK MUST SUCCEED FIRST, IN THIS RUN
----------------------------------------------
A permissions boundary denies by **intersection**: the effective permissions of a role are the
identity policy AND the boundary. So if the identity policy never granted
`bedrock-agentcore:UpdateGateway` in the first place, the request is refused for the ordinary
reason — and an `AccessDeniedException` produced that way is **byte-for-byte indistinguishable**
from a boundary working. `grx-attacker` in its shipped configuration holds no `UpdateGateway`
(infra/01_iam.py: "Note the absence of UpdateGateway ... each absence is a separate F5 oracle"),
which means a run that merely attached a boundary and observed a denial would have measured the
role's shipped configuration and published it as a property of the boundary.

So the grant is applied first and the attack is shown to be **ACCEPTED** before any boundary
exists. That positive control is re-established here rather than cited from F5-2 for two reasons.
It is a different principal — F5-2 attacks as `grx-runtime-exec` and the seal names
`grx-attacker` — so F5-2's acceptance is not this role's acceptance. And an identity policy is a
live object: citing a result from a different day would make this case's denial contingent on a
grant nobody re-read.

Four arms, and the variable that changes between them is named in each:

  pre_grant_baseline    the role's shipped configuration. Must be DENIED. Establishes that the
                        grant below is what opens the route, not something already on the role.
  granted_no_boundary   MUTATION 1 (the grant). Must be ACCEPTED. Without this the whole case is
                        a statement about a request IAM refused to look at.
  boundary_denies       MUTATION 2a. Boundary = `Allow *` plus an explicit `Deny` on
                        `bedrock-agentcore:UpdateGateway`. This is the document's own wording.
  boundary_omits        MUTATION 2b. Boundary = an allow-list that does NOT mention
                        UpdateGateway. This is the *intersection* semantics, and it is the form
                        that could conceivably fail while 2a still worked.
  boundary_removed      THE SEALED MUTATION. Detach and re-run: must be ACCEPTED again.

TWO BOUNDARY FORMS, BECAUSE THEY ARE TWO DIFFERENT CLAIMS
---------------------------------------------------------
An explicit `Deny` wins wherever it appears, boundary or not, so arm 2a would hold even if
boundary intersection were broken — it tests the document's sentence, not the mechanism. Arm 2b
carries the mechanism: the action is simply absent from the ceiling, and only the intersection
rule denies it. The verdict is the AND over both, with each form reported separately, because
"the recommended control works" and "the control works for the reason a reader would assume" are
different sentences and a reader planning a backstop needs both.

Arm 2b has one confound the deny form does not: `UpdateGateway`'s required members include
`roleArn`, so `iam:PassRole` is in play as well (F5-2 measured this and named it
`binding_permission`). An allow-list that omitted BOTH would deny for either reason. So 2b's
ceiling deliberately **includes** `iam:PassRole` on the gateway execution role and every action
the role's shipped identity policy already carries; the only permission our grant adds that the
ceiling omits is `UpdateGateway` itself. `iam:SimulatePrincipalPolicy` is then read for both
actions separately, so IAM's own answer about which one is denied is on the record rather than
inferred from ours.

Each boundary arm also sends `GetGateway` as the attacker — an action INSIDE both ceilings. It
must succeed. Without it, a boundary that broke the role's credentials entirely, or a transient
`AssumeRole` failure, would read as the boundary blocking `UpdateGateway` specifically.

IAM IS EVENTUALLY CONSISTENT, IN BOTH DIRECTIONS, AND THAT IS A FALSE-VERDICT GENERATOR
---------------------------------------------------------------------------------------
`PutRolePermissionsBoundary` returning 200 is not the boundary being in force. F5-1 measured
32.1s for a grant to land on this account and found the revoke direction slow and flappy enough
to need its own bound; F5-2 recorded a revoke wait that ended on a single denial after which 9 of
the next 20 calls succeeded. A boundary attached and immediately tested therefore has a real
chance of reading INEFFECTIVE purely from propagation — the sealed FALSE, manufactured by
impatience — and a boundary detached and immediately tested has the mirror chance of reading as
"the mutation did not invert", which this script treats as NOT_MEASURED.

So every IAM transition is followed by a poll that requires `PROP_CONFIRM_N` **consecutive**
confirmations of the wanted outcome, bounded in time, and the elapsed seconds are recorded per
transition in `propagation`. Consecutive rather than cumulative: a cumulative count is satisfied
by an alternating sequence, which is precisely the fleet state that has not converged. A wait
that times out does not raise — it is recorded as `reached: false` and the guard that reads it
fails, because a timeout is a fact about IAM and an assertion is not.

The polling probes are `UpdateGateway` calls, i.e. the same instrument the arms use, and they are
tallied separately from every arm (`probe__<phase>` trial ids) so a converging sequence can never
be counted as evidence.

WHAT THE ATTACK BODY IS, AND WHY AN ACCEPTED CALL DAMAGES NOTHING
----------------------------------------------------------------
`UpdateGateway` is a FULL REPLACEMENT, not a patch: an omitted optional member is a request to
unset it. A hand-written attack body would therefore reset the session timeout and the debug
exception level of the gateway F4's truth table and every F6 latency verdict are published
against. Every attempt in this script sends the configuration read back from `GetGateway`,
member for member, filtered to the members `UpdateGateway` accepts **taken from the service
model at runtime**, with nothing changed. So an accepted call is a no-op that leaves the gateway
byte-identical — and still an authorization event, which is what the arms count. Authorization is
evaluated before the body takes effect, so this does not weaken the attack.

Unlike F5-2 this script never sets `policyEngineConfiguration.mode`. It has no reason to: the
question is who may call the API, and the LOG_ONLY chain is F5-2's subject. The gateway's
configuration is diffed field for field at the end anyway, using `infra/04_gateway.diff_configs`
and that module's own `PAIR_IGNORE` minus `policyEngineConfiguration` — which is compared
explicitly, because "this case did not touch the mode" is a claim worth checking rather than
assuming.

BLAST RADIUS, AND WHY THE TEARDOWN IS THE MOST IMPORTANT CODE HERE
------------------------------------------------------------------
Mutations, all of them on `grx-attacker` and on two IAM managed policies this run creates:

  1 inline policy on grx-attacker (the grant)          created, deleted
  2 customer-managed policies (the two boundary forms)  created, deleted
  2 PutRolePermissionsBoundary + 2 detaches             attached, detached
  0 changes to the gateway (every UpdateGateway is a no-op replacement)

A permissions boundary left attached to `grx-attacker` would silently change **every future F5
replication**: F5-1 and F5-2's denials would then be over-determined, and nothing in either
script reads the boundary, so both would keep publishing clean results about a role that is no
longer in its shipped configuration. The boundary is therefore detached in a `finally`, the role
is read back with `GetRole`, and `residue.clean` is computed from a created list and a
removed list rather than from the removals alone — a resource whose removal was never
*attempted* (the process was killed between the attach and the finally) contributes no row to a
removals list, so a residue derived from that list alone reports zero survivors for exactly the
case where one exists.

`rc=2` if anything survives, whatever the verdict. A verdict is about the document; an exit code
is about whether this run left the account as it found it.

Every mutation is recorded in the ledger BEFORE it is made, because `finally` is not a watchdog —
SIGKILL skips it — and `infra/99_teardown.py` replaying `state.json` is the durable second
channel. A ledger entry for something never created costs one `NoSuchEntity` at teardown; a
created boundary with no entry is an invisible permanent change to the attacker's ceiling.

COST
----
Zero text units: no model, no `ApplyGuardrail`, no `InvokeGuardrailChecks`. Billable surface is
~40 `bedrock-agentcore` control-plane calls plus ~20 IAM writes and reads. Under a cent.

Never touched: the six pre-existing READY gateways, the `nopolicy` gateway, the three DRAFT
guardrails, the two abandoned policy engines, any `harness_*`/`uitestagent_*` resource, and any
IAM role whose name does not begin with `grx-`.
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
import oracle as O                                                 # noqa: E402
import phase1 as P                                                 # noqa: E402
import testbed as T                                                # noqa: E402
from evidence import EvidenceStore, capture                        # noqa: E402

FAMILY = "f5"
CASE = "F5-3b"


def _load(spec):
    """Execute an already-built spec.

    The `spec_from_file_location` call is written out at the site rather than wrapped, because
    `lib/tests/test_module_name_collisions.py` reads the registered `sys.modules` name statically
    to prove two loaders cannot claim the same one for two different files. A helper taking the
    name as a parameter makes that name unreadable, and the guard then has to be told to stop
    looking — which is the check being disabled to keep the convenience.
    """
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The gateway pairing rule and the "terminal status" definition come from the provisioner that
# owns them, under the same sys.modules key and the same target expression F5-2 and F4 use — a
# private copy here would let this script's restore check and F6's pairing assertion drift apart
# while both claimed to compare the same fields.
_gwmod = _load(importlib.util.spec_from_file_location(
    "_grx_gateway", ROOT / "infra" / "04_gateway.py"))
PAIR_IGNORE = _gwmod.PAIR_IGNORE
diff_configs = _gwmod.diff_configs
wait_ready = _gwmod.wait_ready
GATEWAY_OK = _gwmod.TERMINAL_OK
GATEWAY_BAD = _gwmod.TERMINAL_BAD
MODE_ENFORCE = _gwmod.DEFAULT_MODE

# This case moves NO field on the gateway, so `policyEngineConfiguration` is compared explicitly
# instead of being ignored. `PAIR_IGNORE` exists to answer "does anything ELSE differ" for F6's
# pair; here the answer must be "nothing differs at all", the mode included.
RESTORE_IGNORE = tuple(k for k in PAIR_IGNORE if k != "policyEngineConfiguration")

# What infra/01_iam.py ships on the role. Asserted live at start, not assumed: a grant left by a
# crashed run would make the boundary arms' interpretation impossible.
BASELINE_INLINE = "grx-attacker-policy"

ARM_PRE_GRANT = "pre_grant_baseline"
ARM_GRANTED = "granted_no_boundary"
ARM_BOUNDARY_DENY = "boundary_denies"
ARM_BOUNDARY_OMIT = "boundary_omits"
ARM_REMOVED = "boundary_removed"
ARMS = (ARM_PRE_GRANT, ARM_GRANTED, ARM_BOUNDARY_DENY, ARM_BOUNDARY_OMIT, ARM_REMOVED)

# The two boundary arms are the ones the verdict reads, so they are the larger ones. The rest
# answer yes/no questions about the instrument. Every ACCEPTED attempt is a real UPDATING/READY
# cycle on the gateway F4 and F6 are published against, which is why the arms that expect
# acceptance are the smallest of all.
N_PRE_GRANT = 2
N_GRANTED = 3
N_BOUNDARY = 5
N_REMOVED = 3
N_PER_ARM = {ARM_PRE_GRANT: N_PRE_GRANT, ARM_GRANTED: N_GRANTED,
             ARM_BOUNDARY_DENY: N_BOUNDARY, ARM_BOUNDARY_OMIT: N_BOUNDARY,
             ARM_REMOVED: N_REMOVED}

BOUNDARY_ARMS = (ARM_BOUNDARY_DENY, ARM_BOUNDARY_OMIT)

DENIED_CODES = ("AccessDeniedException", "AccessDenied")
CONFLICT_CODES = ("ConflictException",)

# The action the boundary is meant to stop, and the one that is in play beside it because
# `roleArn` is a required member of UpdateGateway.
ACTION_UPDATE = "bedrock-agentcore:UpdateGateway"
ACTION_PASSROLE = "iam:PassRole"
ACTION_GET = "bedrock-agentcore:GetGateway"

# Everything the role's SHIPPED identity policy already allows (infra/01_iam.py, `attacker`).
# The omit-form ceiling is a superset of this plus iam:PassRole, so the only permission our grant
# adds that the ceiling withholds is UpdateGateway — which is what makes that arm a
# one-variable experiment rather than a race between two denials.
SHIPPED_ACTIONS = ("bedrock-agentcore:GetGateway", "bedrock-agentcore:ListGateways",
                   "bedrock-agentcore:InvokeGateway", "bedrock-agentcore:GetPolicyEngine",
                   "bedrock-agentcore:ListPolicies", "sts:GetCallerIdentity")

# Propagation, bounded in TIME and requiring consecutive agreement. Same shape and the same
# reasons as F5-2: one confirming probe is not convergence — F5-2 measured a revoke wait that
# ended on a single denial after which 9 of the next 20 calls succeeded.
PROP_MAX_S = 300
PROP_MAX_REMOVE_S = 900
PROP_EVERY_S = 10
PROP_CONFIRM_N = 3

GATEWAY_READY_TIMEOUT_S = 300
INTER_CALL_S = 0.2
# IAM has no entry in `awsclients.RATE_LIMITS`, and `limiter().wait()` returns 0.0 for an unknown
# operation — so `A.limiter().wait("PutRolePolicy")` would read as pacing while doing nothing at
# all, which is the defect the SELF_IMPOSED_LIMITS comment in that module describes. The IAM
# writes here are a couple of dozen in total and are spaced with an explicit sleep instead.
INTER_IAM_S = 0.5
DELETE_ATTEMPTS = 4
DELETE_SLEEP_S = 3

GUARDS = (
    "role_started_in_its_shipped_configuration",
    "role_started_with_no_permissions_boundary",
    "gateway_started_in_its_provisioned_configuration",
    "the_attack_succeeded_before_any_boundary_existed",
    "every_boundary_transition_was_observed_to_settle",
    "an_in_boundary_action_still_worked_under_each_boundary",
    "removing_the_boundary_reopened_the_route",
    "boundary_was_detached_and_the_role_read_back_clean",
    "grant_and_boundary_policies_were_deleted",
    "gateway_was_left_field_for_field_identical",
)

MAX_MUTATIONS = 8   # 1 grant + 2 managed policies + 2 attaches, and the undo of each


class ConfigError(RuntimeError):
    """A precondition that must stop the run before anything is mutated. Never a verdict."""


# ---------------------------------------------------------------------------
# the attack body: a full replacement built from the gateway's own state
# ---------------------------------------------------------------------------

def _update_shape(ac) -> tuple[frozenset[str], frozenset[str]]:
    """`UpdateGateway`'s accepted and required members, from the service model.

    Derived rather than listed, for the reason `testbed.check_name` gives about name grammars: a
    hard-coded member list is a second source of truth that drifts at the next botocore bump —
    and "UpdateGateway is a full replacement over THESE members" is the claim, so the SDK has to
    be the one asserting it. A member the model gains later is copied through automatically
    instead of being silently unset by our body.
    """
    sh = ac.meta.service_model.operation_model("UpdateGateway").input_shape
    return frozenset(sh.members), frozenset(sh.required_members)


def _noop_body(live: dict[str, Any], *, gateway_id: str, allowed: frozenset[str],
               required: frozenset[str]) -> dict[str, Any]:
    """The gateway's current configuration, as an `UpdateGateway` body, with NOTHING changed.

    Deep-copied because the caller keeps `live` for the end-of-run diff: a body that shared the
    nested `protocolConfiguration` dict would let any later edit mutate the very record the
    end-state comparison is verified against — a comparison that can then never fail.

    F5-3b never varies a member. There is no `mode=` parameter here on purpose: the mode is
    F5-2's subject, and a parameter this case does not need is a parameter a later edit could
    use to move the gateway F4 and F6 are published against.
    """
    kw: dict[str, Any] = {"gatewayIdentifier": gateway_id}
    for key in sorted(allowed - {"gatewayIdentifier"}):
        if key in live:
            kw[key] = copy.deepcopy(live[key])
    missing = sorted(required - set(kw))
    if missing:
        raise ConfigError(
            f"GetGateway did not return {missing}, which UpdateGateway requires. Sending the "
            f"body without them would be a ValidationException classified `unusable`, and a run "
            f"of those would report NOT_MEASURED for a reason that is our bug, not a boundary.")
    return kw


# ---------------------------------------------------------------------------
# the documents
# ---------------------------------------------------------------------------

def grant_document(gateway_arn: str, gw_role_arn: str) -> dict[str, Any]:
    """The identity policy the oracle's "despite an identity policy granting it" refers to.

    Both `bedrock-agentcore:UpdateGateway` and `iam:PassRole` are granted together. F5-2 already
    answered which of the two is load-bearing for route #3 (`binding_permission`), and this case
    asks a different question — whether a boundary stops the call — so a staged grant here would
    add an arm whose only outcome is a denial we already know how to explain.

    `bedrock-agentcore:GetGateway` is granted too, and is the in-boundary control: an action that
    sits INSIDE both ceilings, so a boundary that broke the role's credentials wholesale cannot
    be read as the boundary blocking UpdateGateway specifically. It is scoped to the same gateway
    ARN rather than `*` because the account holds six pre-existing READY gateways this project
    must not reach, even read-only.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "F53bGrantUpdateGateway", "Effect": "Allow",
             "Action": ACTION_UPDATE, "Resource": gateway_arn},
            {"Sid": "F53bGrantPassRole", "Effect": "Allow",
             "Action": ACTION_PASSROLE, "Resource": gw_role_arn},
            {"Sid": "F53bInBoundaryControl", "Effect": "Allow",
             "Action": ACTION_GET, "Resource": gateway_arn},
        ],
    }


def boundary_deny_document(gateway_arn: str) -> dict[str, Any]:
    """The document's own wording: a boundary that DENIES the mutating call.

    `Allow *` plus an explicit `Deny`. The allow half matters: a boundary is a ceiling, so a
    document containing only the Deny would reduce the role's effective permissions to nothing
    and every arm — including the in-boundary control — would fail for a reason that has nothing
    to do with UpdateGateway.

    The Deny is scoped to this run's gateway ARN, not `*`. A wildcard would additionally deny
    UpdateGateway against the six pre-existing gateways, which is a change to how this identity
    relates to resources outside the testbed even though it can already reach none of them.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "CeilingAllowsEverythingElse", "Effect": "Allow",
             "Action": "*", "Resource": "*"},
            {"Sid": "DenyGatewayReconfiguration", "Effect": "Deny",
             "Action": ACTION_UPDATE, "Resource": gateway_arn},
        ],
    }


def boundary_omit_document(gateway_arn: str, gw_role_arn: str) -> dict[str, Any]:
    """The intersection form: UpdateGateway is simply ABSENT from the ceiling.

    This is the arm that tests the mechanism rather than the sentence. An explicit `Deny` wins
    wherever it appears — in an identity policy, in a boundary, in a resource policy — so the
    deny-form arm would hold even if boundary intersection were broken. Here nothing denies
    anything: the action is outside the ceiling, and only the rule that effective permissions are
    the INTERSECTION of identity policy and boundary can produce a denial.

    The allow-list is deliberately a superset of the role's shipped identity policy plus
    `iam:PassRole` on the gateway execution role. That is what makes this a one-variable
    experiment: `roleArn` is a required member of UpdateGateway, so a ceiling omitting PassRole
    as well would deny for either reason and the two are indistinguishable in the response.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "CeilingAllowsWhatTheRoleAlreadyHad", "Effect": "Allow",
             "Action": list(SHIPPED_ACTIONS), "Resource": "*"},
            {"Sid": "CeilingAllowsPassRoleSoTheOnlyVariableIsUpdateGateway", "Effect": "Allow",
             "Action": ACTION_PASSROLE, "Resource": gw_role_arn},
            {"Sid": "CeilingAllowsReadingThisGateway", "Effect": "Allow",
             "Action": ACTION_GET, "Resource": gateway_arn},
        ],
    }


def boundary_form_for(arm: str, *, gateway_arn: str, gw_role_arn: str) -> dict[str, Any]:
    if arm == ARM_BOUNDARY_DENY:
        return boundary_deny_document(gateway_arn)
    if arm == ARM_BOUNDARY_OMIT:
        return boundary_omit_document(gateway_arn, gw_role_arn)
    raise ValueError(f"{arm!r} is not a boundary arm; boundary arms are {BOUNDARY_ARMS}")


# ---------------------------------------------------------------------------
# preconditions
# ---------------------------------------------------------------------------

def assert_role_is_pristine(iam, store, *, role_name: str,
                            grant_name: str) -> dict[str, Any]:
    """Exactly the shipped inline policy, and NO permissions boundary.

    Read from the live role, not from the ledger's `ids.inline_policies`: the ledger records what
    a provisioner intended to create, and this needs what IS attached. Two failures it exists
    for, both quiet:

    * a grant left by a crashed run would make `pre_grant_baseline` succeed, and the arm whose
      whole job is to show that OUR grant opens the route would instead show that someone else's
      did;
    * a boundary left by a crashed run would make `granted_no_boundary` fail, and this script
      would report NOT_MEASURED about an intact instrument — or, worse, a boundary carrying a
      Deny we did not write would produce the sealed TRUE from our own litter.

    Refuses rather than repairing. `infra/01_iam.py --ensure --fix-drift` is the tool that
    removes an unexpected inline policy, and it prints what it removed; silently deleting one
    here would erase the evidence that a previous run left a privilege behind.
    """
    got = capture(store, "list_role_policies", iam, RoleName=role_name)
    if not got.ok:
        raise ConfigError(
            f"ListRolePolicies on {role_name} failed ({got.error_code}), so the role's starting "
            f"configuration was never measured. Refusing to mutate a role whose baseline is "
            f"unknown.")
    names = sorted(got.response.get("PolicyNames") or [])
    if grant_name in names:
        raise ConfigError(
            f"{grant_name!r} is already attached to {role_name}. A previous run of this case "
            f"crashed before its restore, or teardown has not run. Delete it "
            f"(`aws iam delete-role-policy --role-name {role_name} --policy-name {grant_name}`) "
            f"and re-run.")
    if names != [BASELINE_INLINE]:
        raise ConfigError(
            f"{role_name} carries inline policies {names}, not exactly [{BASELINE_INLINE!r}]. "
            f"Something outside this case has changed the role, so the arms below would not be "
            f"about the shipped configuration the document's claim is about.")

    attached = capture(store, "list_attached_role_policies", iam, RoleName=role_name)
    if not attached.ok:
        raise ConfigError(
            f"ListAttachedRolePolicies on {role_name} failed ({attached.error_code}); an "
            f"attached managed policy could grant UpdateGateway outside the inline document "
            f"this case reads, and the pre-grant arm would then be denied for no reason we know")
    managed = sorted(p["PolicyArn"] for p in (attached.response.get("AttachedPolicies") or []))
    if managed:
        raise ConfigError(
            f"{role_name} carries attached managed policies {managed}; infra/01_iam.py attaches "
            f"none. The role's effective permissions are therefore not the document this case "
            f"reads, and the grant's contribution could not be isolated.")

    boundary = read_boundary(iam, store, role_name=role_name)
    if not boundary["read_ok"]:
        raise ConfigError(
            f"GetRole on {role_name} failed ({boundary['error_code']}), so whether a "
            f"permissions boundary is already attached is unknown. That is the one fact this "
            f"whole case turns on; refusing to attach a second one on top of an unknown first.")
    if boundary["attached"]:
        raise ConfigError(
            f"{role_name} already carries a permissions boundary "
            f"({boundary['boundary_arn']}). This case's required pre-state is NO boundary: with "
            f"one already in force, `granted_no_boundary` cannot establish that the attack is "
            f"otherwise accepted, and a denial under our boundary would be attributable to "
            f"either. Detach it (`aws iam delete-role-permissions-boundary --role-name "
            f"{role_name}`) and re-run.")
    return {"inline_policies_at_start": names, "attached_managed_policies_at_start": managed,
            "permissions_boundary_at_start": None,
            "read_from": "iam:ListRolePolicies + ListAttachedRolePolicies + GetRole (live)"}


def assert_gateway_is_provisioned(live: dict[str, Any], *, engine_arn: str) -> dict[str, Any]:
    """READY, in ENFORCE, carrying THIS run's engine.

    F5-3b changes no gateway field, so none of this is load-bearing for the attack itself. It is
    asserted anyway because an accepted `UpdateGateway` is a real full-replacement write, and a
    gateway that was already mid-update, or already in a mode this run did not put it in, is a
    gateway whose end-state diff would report a difference this case did not cause — which would
    be indistinguishable, in the record, from this case having damaged it.
    """
    status = live.get("status")
    pec = live.get("policyEngineConfiguration") or {}
    if status not in GATEWAY_OK:
        raise ConfigError(
            f"the gateway is {status}, not READY. An UpdateGateway against a gateway that is "
            f"still settling returns ConflictException, which this script counts as an "
            f"AUTHORIZED call — so a non-READY start would put conflicts into the boundary arms "
            f"and read as the boundary failing.")
    if pec.get("mode") != MODE_ENFORCE:
        raise ConfigError(
            f"the gateway's policyEngineConfiguration.mode is {pec.get('mode')!r}, not "
            f"{MODE_ENFORCE!r}. This case must leave it exactly as it found it and `nopolicy` is "
            f"only a valid F6 baseline against an ENFORCE partner, so a run that started "
            f"somewhere else could not tell 'we restored it' from 'we never moved it'.")
    if pec.get("arn") != engine_arn:
        raise ConfigError(
            f"the gateway's attached policy engine is {pec.get('arn')!r}, not the ledger's "
            f"{engine_arn!r}. The gateway under attack is not the one this run built.")
    return {"status": status, "mode": pec.get("mode"), "engine_arn_matches_ledger": True,
            "exception_level": live.get("exceptionLevel"),
            "read_from": "bedrock-agentcore-control:GetGateway (live)"}


# ---------------------------------------------------------------------------
# one attempt, and one arm
# ---------------------------------------------------------------------------

def _attempt(ac, store, *, kwargs: dict[str, Any], trial_id: str) -> dict[str, Any]:
    """One `UpdateGateway` as whichever role `ac` holds. Never raises for an AWS error.

    An `AccessDeniedException` IS the measurement in three of the five arms, so it has to be data
    and not an exception — `evidence.capture` records the failure branch identically to the
    success branch, and the request id in that record is what makes the denial quotable.

    Four outcomes, and two of them are not denials:

      accepted       2xx: the boundary did not stop it
      conflict       `ConflictException`: returned AFTER authorization, so IAM said yes and the
                     service then serialized the call away. Counted as AUTHORIZED, tallied
                     separately, because "authorized then serialized" and "authorized and
                     applied" are different observations of the same authorization outcome
      denied_by_iam  `AccessDeniedException` / `AccessDenied`
      unusable       anything else — `ValidationException`, `ResourceNotFoundException`, a
                     throttle, a transport error. NOT a denial in either direction, and excluded
                     from `n_usable` so our own malformed request can never be denominated as a
                     security result
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
        row["request_id"] = res.request_id
        return row
    row["outcome"] = "accepted"
    row["gateway_status_after"] = (res.response or {}).get("status")
    row["http_status"] = res.http_status
    row["request_id"] = res.request_id
    return row


def tally(arm: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for one arm, with `n_usable` excluding what was neither authorized nor denied."""
    t = {
        "arm": arm,
        "n_attempted": len(rows),
        "n_accepted": sum(1 for r in rows if r.get("outcome") == "accepted"),
        "n_conflict": sum(1 for r in rows if r.get("outcome") == "conflict"),
        "n_denied": sum(1 for r in rows if r.get("outcome") == "denied_by_iam"),
        "n_unusable": sum(1 for r in rows if r.get("outcome") == "unusable"),
        "error_codes": sorted({r.get("error_code", "") for r in rows if r.get("error_code")}),
        "rows": rows,
    }
    t["n_authorized"] = t["n_accepted"] + t["n_conflict"]
    t["n_usable"] = t["n_authorized"] + t["n_denied"]
    # All-or-nothing, like every E-class mechanism arm in this project: a split arm is itself a
    # finding and is reported, never averaged into a rate the oracle does not ask for.
    t["unanimous"] = t["n_usable"] > 0 and t["n_authorized"] in (0, t["n_usable"])
    t["reading"] = ("AUTHORIZED" if t["n_usable"] and t["n_authorized"] == t["n_usable"]
                    else "DENIED" if t["n_usable"] and t["n_authorized"] == 0
                    else "SPLIT" if t["n_usable"] else "NOTHING_USABLE")
    return t


def run_arm(ac, store, *, arm: str, kwargs: dict[str, Any], n: int,
            settle: bool = False, gateway_id: str = "") -> dict[str, Any]:
    """`n` attempts, tallied.

    No checkpoint, deliberately, and this is a departure from F5-2 worth stating. A trial in a
    boundary arm is only meaningful while that boundary is attached, and a resumed process
    cannot re-enter the window it was killed in — so `is_done` would let a later run pair
    post-detach trials with a boundary that no longer exists and report them as one arm. The
    arms here are 2-5 calls, so there is nothing expensive to resume.

    `settle` waits for the gateway to return to a terminal status after an ACCEPTED attempt.
    Only the arms that expect acceptance pass it: a denied attempt changes no state, and polling
    `GetGateway` after every denial would add calls to measure a status that cannot have moved.
    """
    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        row = _attempt(ac, store, kwargs=kwargs, trial_id=f"{arm}__{i:04d}")
        row["arm"] = arm
        if settle and row.get("outcome") == "accepted" and gateway_id:
            try:
                wait_ready(ac, gateway_id, timeout_s=GATEWAY_READY_TIMEOUT_S)
            except Exception as exc:                              # noqa: BLE001
                # Recorded, not raised: a settle timeout is about the NEXT attempt's conflict
                # risk, not about this attempt's authorization outcome, which is already tallied.
                row["settle_error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        time.sleep(INTER_CALL_S)
    return tally(arm, rows)


# ---------------------------------------------------------------------------
# propagation
# ---------------------------------------------------------------------------

def wait_for_effect(ac, store, *, kwargs: dict[str, Any], want: str, phase: str,
                    max_s: float = PROP_MAX_S, gateway_id: str = "",
                    every_s: float = PROP_EVERY_S) -> dict[str, Any]:
    """Poll until the outcome is `want` on `PROP_CONFIRM_N` CONSECUTIVE probes, or give up.

    Consecutive, not cumulative. A cumulative count is satisfied by an alternating sequence,
    which is exactly the fleet state that has not converged, and would end the wait on the very
    evidence that should keep it going. F5-2 measured the failure this prevents: a revoke wait
    ended on a single denial, and 9 of the next 20 calls then succeeded.

    Returned rather than asserted, with the elapsed seconds kept. A run that times out here must
    say so in its results — `every_boundary_transition_was_observed_to_settle` reads
    `reached` — rather than fail an assertion whose message nobody will read next month. The
    observed delay is itself one of this case's findings: nothing in §4's mitigation table says
    how long after `PutRolePermissionsBoundary` returns 200 the ceiling is actually in force, and
    an operator applying a backstop during an incident needs that number.

    These probes carry `probe__<phase>` trial ids and are NOT part of any arm's tally, so a
    converging sequence can never be counted as evidence about the boundary.
    """
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
                return {"reached": True, "phase": phase, "wanted": want,
                        "seconds": round(time.monotonic() - t0, 1),
                        "seconds_to_first_confirmation": round((t_first or t0) - t0, 1),
                        "outcomes_seen": seen,
                        "consecutive_confirmations": streak,
                        "confirmations_required": PROP_CONFIRM_N,
                        "max_wait_s": max_s,
                        "flapped_before_converging": before.count(want) > 0,
                        "n_wanted_outcomes_before_the_final_streak": before.count(want)}
        else:
            streak = 0
            t_first = None
        time.sleep(every_s)
    return {"reached": False, "phase": phase, "wanted": want,
            "seconds": round(time.monotonic() - t0, 1), "outcomes_seen": seen,
            "consecutive_confirmations": streak,
            "confirmations_required": PROP_CONFIRM_N, "max_wait_s": max_s,
            "why_it_matters": (
                f"the arm that follows ran against an IAM state never confirmed to have settled "
                f"within {max_s}s, so its tally is about an unknown configuration")}


def simulate(iam, store, *, role_arn: str, actions: tuple[str, ...],
             resource_arns: list[str], phase: str) -> dict[str, Any]:
    """IAM's own answer for each action separately, via `SimulatePrincipalPolicy`.

    Read for one reason: the omit-form boundary withholds `UpdateGateway` while `roleArn` makes
    `iam:PassRole` part of the same request, and an `AccessDeniedException` names neither. The
    simulator evaluates the principal's identity policies **and its attached permissions
    boundary**, so it can say which action is outside the ceiling where the API response cannot.

    Corroborating, never decisive, and the payload says so. A simulation is not an authorization
    event: it is subject to its own eventual consistency, it does not see a service's own
    resource policy or a FAS session, and this project's rule is that a claim about what the
    service does rests on a call the service answered. `wait_for_effect` — real UpdateGateway
    calls — remains the propagation instrument.
    """
    out: dict[str, Any] = {"phase": phase, "per_action": {}, "read_ok": True,
                           "is_corroborating_not_decisive": (
                               "SimulatePrincipalPolicy evaluates identity policies and the "
                               "attached permissions boundary, which is why it can name WHICH "
                               "action is outside the ceiling. It is not an authorization event "
                               "and is never read as one: the arms are real UpdateGateway calls")}
    for action in actions:
        kw: dict[str, Any] = {"PolicySourceArn": role_arn, "ActionNames": [action]}
        if resource_arns:
            kw["ResourceArns"] = resource_arns
        rec = capture(store, "simulate_principal_policy", iam, **kw)
        if not rec.ok:
            out["read_ok"] = False
            out["per_action"][action] = {"error_code": rec.error_code,
                                         "error_message": rec.error_message}
            continue
        results = (rec.response or {}).get("EvaluationResults") or []
        out["per_action"][action] = {
            "decisions": [r.get("EvalDecision") for r in results],
            "matched_statements": [[s.get("SourcePolicyId") for s in
                                    (r.get("MatchedStatements") or [])] for r in results],
            "permissions_boundary_decision_detail": [
                sorted((r.get("PermissionsBoundaryDecisionDetail") or {}).items())
                for r in results],
            "allowed": all(r.get("EvalDecision") == "allowed" for r in results) and bool(results),
        }
        time.sleep(INTER_IAM_S)
    return out


# ---------------------------------------------------------------------------
# the mutations, ledger first
# ---------------------------------------------------------------------------

def put_grant(iam, store, state, *, role_name: str, policy_name: str,
              document: dict[str, Any]) -> None:
    """Ledger FIRST, then create.

    A stale ledger entry costs one `NoSuchEntity` at teardown; a created grant with no entry is a
    permanent unattended `UpdateGateway` on the identity whose entire purpose is to lack it. The
    cheap failure is chosen on purpose, and `finally` is not a watchdog — SIGKILL skips it.
    """
    state.record(T.Resource(
        kind="iam-inline-policy", logical="f53b_grant", name=policy_name,
        service="iam", delete_op="delete_role_policy",
        delete_params={"RoleName": role_name, "PolicyName": policy_name},
        ids={"role_name": role_name, "policy_name": policy_name, "case": CASE},
        arn="", delete_priority=10,
        notes=(f"{CASE}'s identity grant — the 'identity policy granting it' the sealed oracle "
               f"names. If this is still here, the run did not reach its restore: delete it.")))
    state.write()
    put = capture(store, "put_role_policy", iam, RoleName=role_name, PolicyName=policy_name,
                  PolicyDocument=json.dumps(document))
    time.sleep(INTER_IAM_S)
    if not put.ok:
        raise ConfigError(
            f"PutRolePolicy({policy_name}) failed ({put.error_code}: {put.error_message}); the "
            f"identity grant could not be applied, so a denial under the boundary could not be "
            f"shown to be 'despite an identity policy granting it' — which is the whole oracle.")


def create_boundary_policy(iam, store, state, *, name: str, logical: str,
                           document: dict[str, Any], tag_list: list[dict[str, str]],
                           description: str) -> dict[str, Any]:
    """Create the managed policy that will serve as a boundary. Ledger first.

    A permissions boundary must be a **managed policy ARN**: `PutRolePermissionsBoundary` takes
    `PermissionsBoundary` as an ARN, not a document, so this case cannot express its ceiling
    inline the way a grant can. That is why there are two more resources to clean up than a
    reader of the sealed method ("permissions boundary on grx-attacker") would expect, and why
    the ledger entries carry a delete priority ABOVE the attachment's: a managed policy that is
    still serving as a boundary cannot be deleted, so the detach has to run first.

    Tagged with the project tag set, so `99_teardown.py`'s tag sweep can find it even if this
    process is killed between the create and the ledger write.
    """
    rec = capture(store, "create_policy", iam, PolicyName=name,
                  PolicyDocument=json.dumps(document), Description=description[:1000],
                  Tags=tag_list)
    time.sleep(INTER_IAM_S)
    if not rec.ok:
        raise ConfigError(
            f"CreatePolicy({name}) failed ({rec.error_code}: {rec.error_message}); without a "
            f"managed policy there is no boundary to attach, and this arm has no subject.")
    arn = ((rec.response or {}).get("Policy") or {}).get("Arn") or ""
    if not arn:
        raise ConfigError(
            f"CreatePolicy({name}) returned no Policy.Arn, so the boundary cannot be attached "
            f"and — worse — a managed policy may exist that this run cannot name to delete. "
            f"Check for it by name before re-running.")
    state.record(T.Resource(
        kind="iam-policy", logical=logical, name=name,
        service="iam", delete_op="delete_policy",
        delete_params={"PolicyArn": arn},
        ids={"policy_name": name, "case": CASE, "purpose": "permissions boundary document"},
        arn=arn, delete_priority=20,
        notes=(f"{CASE}'s permissions boundary document. Must be DETACHED before it can be "
               f"deleted, which is why the attachment entry has a lower delete_priority.")))
    state.write()
    return {"policy_arn": arn, "policy_name": name, "document": document,
            "request_id": rec.request_id}


def attach_boundary(iam, store, state, *, role_name: str, policy_arn: str,
                    logical: str) -> dict[str, Any]:
    """Attach the boundary. Ledger FIRST, and at a priority that runs before the policy delete.

    The ledger entry's `delete_op` is `delete_role_permissions_boundary`, so
    `infra/99_teardown.py` — which replays `delete_op` with `delete_params` against a client for
    `service` — detaches it without needing to know anything about this case. That is the durable
    channel: a boundary left attached to `grx-attacker` would silently over-determine the
    denials in every future F5-1 and F5-2 replication, and neither of those scripts reads the
    boundary, so both would keep publishing clean results about a role that is no longer in its
    shipped configuration.
    """
    state.record(T.Resource(
        kind="iam-permissions-boundary", logical=logical, name=role_name,
        service="iam", delete_op="delete_role_permissions_boundary",
        delete_params={"RoleName": role_name},
        ids={"role_name": role_name, "boundary_arn": policy_arn, "case": CASE},
        arn="", delete_priority=5,
        notes=(f"{CASE} attached a permissions boundary to {role_name}. If this entry survives, "
               f"the attacker's ceiling is still altered and every F5 replication is affected — "
               f"detach it first, then delete the managed policy.")))
    state.write()
    rec = capture(store, "put_role_permissions_boundary", iam, RoleName=role_name,
                  PermissionsBoundary=policy_arn)
    time.sleep(INTER_IAM_S)
    if not rec.ok:
        raise ConfigError(
            f"PutRolePermissionsBoundary({role_name}) failed ({rec.error_code}: "
            f"{rec.error_message}); no boundary is in force, so a denial below would be about "
            f"something else entirely.")
    return {"attached": True, "boundary_arn": policy_arn, "request_id": rec.request_id}


def read_boundary(iam, store, *, role_name: str) -> dict[str, Any]:
    """What boundary the role carries, read back from `GetRole`.

    A failed read is recorded as a failed read, never as a clean role
    (`feedback_guard_tool_exit_codes`): `attached` is None when `read_ok` is False, so a caller
    that treats falsy as clean gets None rather than a silent False.
    """
    rec = capture(store, "get_role", iam, RoleName=role_name)
    if not rec.ok:
        return {"read_ok": False, "attached": None, "boundary_arn": None,
                "error_code": rec.error_code, "error_message": rec.error_message}
    role = (rec.response or {}).get("Role") or {}
    pb = role.get("PermissionsBoundary") or {}
    return {"read_ok": True, "attached": bool(pb), "boundary_arn": pb.get("PermissionsBoundaryArn"),
            "boundary_type": pb.get("PermissionsBoundaryType")}


def detach_boundary(iam, store, state, *, role_name: str, logical: str) -> dict[str, Any]:
    """Detach, retry, then READ THE ROLE BACK. Never raises: this runs in a `finally`.

    The read-back is the point. `DeleteRolePermissionsBoundary` returning 200 is a control-plane
    acknowledgement, and this case's single most damaging residue is a boundary that is still
    there — so the answer to "is it gone" comes from `GetRole`, not from the delete's status code.
    `NoSuchEntity` counts as detached because a role with no boundary is the state we want; any
    other error leaves `detached` False and the caller reports residue.
    """
    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        rec = capture(store, "delete_role_permissions_boundary", iam, RoleName=role_name)
        if rec.ok or rec.error_code in ("NoSuchEntity", "NoSuchEntityException"):
            break
        errors.append(f"attempt {attempt}: {rec.error_code}: {rec.error_message}")
        time.sleep(DELETE_SLEEP_S)
    after = read_boundary(iam, store, role_name=role_name)
    detached = bool(after["read_ok"] and after["attached"] is False)
    if detached:
        state.drop("iam-permissions-boundary", logical)
        state.write()
    return {"detached": detached, "errors": errors, "read_back": after,
            "manual_remedy": (
                None if detached else
                f"aws iam delete-role-permissions-boundary --role-name {role_name}  "
                f"# a boundary left here changes every future F5-1/F5-2 replication")}


def delete_boundary_policy(iam, store, state, *, policy_arn: str,
                           logical: str) -> dict[str, Any]:
    """Delete the managed policy. Never raises: this runs in a `finally`.

    Retried because the detach it depends on is eventually consistent: IAM can still report the
    policy as in use for a short window after `DeleteRolePermissionsBoundary` returns, and a
    single attempt would leave a customer-managed policy behind for a reason that resolves
    itself in seconds.
    """
    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        rec = capture(store, "delete_policy", iam, PolicyArn=policy_arn)
        if rec.ok or rec.error_code in ("NoSuchEntity", "NoSuchEntityException"):
            state.drop("iam-policy", logical)
            state.write()
            return {"deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}: {rec.error_message}")
        time.sleep(DELETE_SLEEP_S)
    return {"deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors,
            "manual_remedy": f"aws iam delete-policy --policy-arn {policy_arn}"}


def delete_grant(iam, store, state, *, role_name: str, policy_name: str) -> dict[str, Any]:
    """Delete the identity grant. Never raises: this runs in a `finally`."""
    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        rec = capture(store, "delete_role_policy", iam, RoleName=role_name,
                      PolicyName=policy_name)
        if rec.ok or rec.error_code in ("NoSuchEntity", "NoSuchEntityException"):
            state.drop("iam-inline-policy", "f53b_grant")
            state.write()
            return {"deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}: {rec.error_message}")
        time.sleep(DELETE_SLEEP_S)
    return {"deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors,
            "manual_remedy": (f"aws iam delete-role-policy --role-name {role_name} "
                              f"--policy-name {policy_name}")}


def in_boundary_control(ac_attacker, store, *, gateway_id: str, arm: str) -> dict[str, Any]:
    """`GetGateway` as the attacker — an action INSIDE both ceilings. Must succeed.

    Without it, three unrelated failures all look like the boundary working: a boundary document
    that reduced the role's effective permissions to nothing (the failure mode of a Deny-only
    ceiling), an `AssumeRole` that silently expired mid-run, and a regional or endpoint problem.
    Each would produce `AccessDenied` on `UpdateGateway` and this case would publish the sealed
    TRUE from an instrument that had stopped working.
    """
    rec = capture(store, "get_gateway", ac_attacker, gatewayIdentifier=gateway_id)
    return {"arm": arm, "ok": bool(rec.ok), "error_code": rec.error_code or None,
            "error_message": rec.error_message or None, "request_id": rec.request_id,
            "why": ("an action inside the ceiling must still work, or a denial on UpdateGateway "
                    "is not attributable to the boundary withholding UpdateGateway")}


# ---------------------------------------------------------------------------
# residue, from two lists
# ---------------------------------------------------------------------------

def residue(created: list[dict[str, Any]], removed: list[dict[str, Any]], *,
            boundary_at_end: dict[str, Any],
            inline_at_end: list[str] | None) -> dict[str, Any]:
    """What this run left behind, from a CREATED list and a REMOVED list.

    Deriving the survivors from the removals alone would be circular, which is the reasoning
    `phase1.probe_residue` states for probe guardrails and which applies here with a worse
    consequence: a mutation whose undo was never *attempted* — the process was killed between
    the attach and the `finally` — contributes no row to `removed` at all, so a residue computed
    from that list would report zero survivors for exactly the case where a permissions boundary
    is still altering the attacker's ceiling.

    Two extra terms are read back from IAM rather than inferred from either list, because for
    this case "residue" is a STATE and not a bookkeeping entry:

      `boundary_still_attached`  — GetRole says a boundary is in force. The damaging one.
      `unexpected_inline`        — the role's inline policy set is not exactly the shipped one.

    A failed read-back is residue, not cleanliness: `boundary_at_end["read_ok"]` False leaves
    `boundary_still_attached` None and `clean` False, because a boundary we could not look at is
    not a boundary we know is gone.
    """
    made = [c["id"] for c in created]
    attempted = {r["id"] for r in removed}
    gone = {r["id"] for r in removed if r.get("removed")}
    surviving = [i for i in made if i not in gone]
    boundary_still = (None if not boundary_at_end.get("read_ok")
                      else bool(boundary_at_end.get("attached")))
    unexpected_inline = (None if inline_at_end is None
                         else sorted(set(inline_at_end) - {BASELINE_INLINE}))
    out = {
        "n_created": len(made),
        "n_removal_attempted": len(attempted),
        "n_removed": len(gone),
        "surviving": surviving,
        "never_attempted": [i for i in made if i not in attempted],
        "created": created,
        "removed": removed,
        "boundary_still_attached": boundary_still,
        "boundary_read_back": boundary_at_end,
        "inline_policies_at_end": inline_at_end,
        "unexpected_inline_policies": unexpected_inline,
        "why_two_lists": (
            "a mutation whose undo was never ATTEMPTED contributes no row to the removals, so a "
            "residue computed from that list alone reports zero survivors for exactly the case "
            "where one exists"),
        "why_the_state_is_read_back_too": (
            "the damaging residue for this case is not a bookkeeping entry, it is a boundary "
            "still in force on grx-attacker: every future F5-1/F5-2 replication would then be "
            "over-determined, and neither of those scripts reads the boundary"),
    }
    out["clean"] = (not surviving and boundary_still is False and unexpected_inline == [])
    return out


# ---------------------------------------------------------------------------
# guards and the verdict
# ---------------------------------------------------------------------------

def guards(*, interlock_role: dict[str, Any], interlock_gateway: dict[str, Any],
           arms: dict[str, dict[str, Any]], propagation: dict[str, dict[str, Any]],
           controls: dict[str, dict[str, Any]], res: dict[str, Any],
           gateway_read_ok: bool, gateway_diff: list[str] | None,
           pec_identical: bool) -> dict[str, bool]:
    """Every condition under which this case's numbers mean what they say.

    Each is a separate name because the remedies differ: a failed positive control means the
    instrument never worked, a failed propagation wait means the run was too impatient, and
    surviving residue means the account was left changed. Collapsing them into one boolean would
    make all three read as "the boundary did not hold".
    """
    return {
        "role_started_in_its_shipped_configuration":
            interlock_role.get("inline_policies_at_start") == [BASELINE_INLINE]
            and interlock_role.get("attached_managed_policies_at_start") == [],
        "role_started_with_no_permissions_boundary":
            "permissions_boundary_at_start" in interlock_role
            and interlock_role.get("permissions_boundary_at_start") is None,
        "gateway_started_in_its_provisioned_configuration":
            bool(interlock_gateway.get("engine_arn_matches_ledger")),
        # THE gate. Without an accepted attack before any boundary existed, every denial below is
        # consistent with a request IAM refused to look at, and the sealed TRUE would be a
        # statement about the role's shipped configuration rather than about the boundary.
        "the_attack_succeeded_before_any_boundary_existed":
            arms.get(ARM_GRANTED, {}).get("n_authorized", 0) > 0,
        "every_boundary_transition_was_observed_to_settle":
            bool(propagation) and all(p.get("reached") is True for p in propagation.values()),
        "an_in_boundary_action_still_worked_under_each_boundary":
            bool(controls) and set(controls) >= set(BOUNDARY_ARMS)
            and all(controls[a].get("ok") is True for a in BOUNDARY_ARMS),
        # The sealed mutation, and it is required in the direction that makes the denial
        # attributable: detaching must reopen the route.
        "removing_the_boundary_reopened_the_route":
            arms.get(ARM_REMOVED, {}).get("n_authorized", 0) > 0,
        "boundary_was_detached_and_the_role_read_back_clean":
            res.get("boundary_still_attached") is False,
        "grant_and_boundary_policies_were_deleted":
            res.get("surviving") == [] and res.get("unexpected_inline_policies") == [],
        "gateway_was_left_field_for_field_identical":
            gateway_read_ok is True and gateway_diff == [] and pec_identical is True,
    }


def boundary_reading(arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Per-boundary-form outcome, and the AND the verdict reads.

    Reported per form because "the recommended control works" (the Deny form) and "the control
    works for the reason a reader would assume" (the intersection form) are different sentences.
    A run where the Deny form blocked and the omit form did not is the most interesting outcome
    this case can produce and would be invisible in a single boolean.
    """
    per = {arm: arms.get(arm, {}).get("reading", "MISSING") for arm in BOUNDARY_ARMS}
    blocked = {arm: per[arm] == "DENIED" for arm in BOUNDARY_ARMS}
    return {
        "per_form": per,
        "blocked_per_form": blocked,
        "all_forms_blocked": all(blocked.values()),
        "any_form_ineffective": any(v == "AUTHORIZED" for v in per.values()),
        "rule": ("observed_bool is the AND over both boundary forms. A form that is SPLIT or "
                 "MISSING is not a block: an all-or-nothing mechanism arm that split is a "
                 "finding, and an arm that never ran is not evidence of anything"),
    }


def narrative(*, reading: dict[str, Any], arms: dict[str, dict[str, Any]],
              propagation: dict[str, dict[str, Any]], sdk: str) -> dict[str, str]:
    """The five sentences every payload in this project carries, built where they can be tested.

    In a function rather than inline in `main()` so a test can read them without faking a run,
    and so the FALSE branch is written at the same time as the TRUE branch rather than being
    discovered when it fires.
    """
    per = reading["per_form"]
    delays = {k: v.get("seconds") for k, v in propagation.items()}
    if reading["all_forms_blocked"]:
        verdict_reading = (
            f"both boundary forms denied UpdateGateway to an identity whose own policy granted "
            f"it. The deny form (the document's wording) and the omit form (the intersection "
            f"rule, with iam:PassRole deliberately inside the ceiling) both read DENIED, and "
            f"detaching the boundary made the same body accepted again "
            f"({arms.get(ARM_REMOVED, {}).get('n_authorized', 0)} of "
            f"{arms.get(ARM_REMOVED, {}).get('n_usable', 0)} usable attempts)")
    elif reading["any_form_ineffective"]:
        verdict_reading = (
            f"at least one boundary form did NOT stop the call: {per}. The route §4 offers as "
            f"the account-level backstop was open to an identity carrying its own grant, which "
            f"is the sealed FALSE and is the stronger direction of evidence — an accepted call "
            f"is an authorization event, not an inference")
    else:
        verdict_reading = (
            f"the boundary arms did not read cleanly either way: {per}. A split arm on an "
            f"all-or-nothing mechanism is itself the finding and is reported rather than "
            f"averaged")
    return {
        "verdict_rule": (
            "TRUE iff BOTH boundary forms denied every usable attempt while the identity policy "
            "granted the action, AND the positive control (the same body, same role, no "
            "boundary) was authorized, AND detaching the boundary made it authorized again. The "
            "positive control is load-bearing rather than decorative: grx-attacker holds no "
            "UpdateGateway in its shipped configuration, so a denial without it would be the "
            "ordinary refusal of an ungranted action, which is byte-for-byte identical to a "
            "boundary working"),
        "verdict_reading": verdict_reading,
        "what_true_does_not_prove": (
            "that a boundary blocks the mutation for a principal this case did not test. The "
            "measurement is one role in one account: an SCP applies to a whole account and a "
            "boundary applies to the identity it is attached to, so nothing here says a "
            "confused-deputy path through a DIFFERENT identity is closed — that identity has no "
            "boundary. It also says nothing about enforcement from inside a constrained member "
            "account (F5-3c, structurally unreachable here — this is the Organizations "
            "management account, where SCPs never apply), and nothing about the other actions "
            "§4's table names in the same breath: policy-engine mutations were not attempted "
            "under either ceiling. Finally, a boundary a break-glass admin can remove is a "
            "control whose strength is the change management around iam:PutRolePermissionsBoundary, "
            "which this case measured by exercising rather than by testing"),
        "why_this_matters_operationally": (
            f"§4 offers this as the backstop that 'holds even if route #3's role hygiene "
            f"regresses', and F5-2 measured that route #3 regresses exactly one PutRolePolicy at "
            f"a time. What the table does not say is how long the backstop takes to become real: "
            f"the observed settle delays per transition were {delays} seconds, requiring "
            f"{PROP_CONFIRM_N} consecutive confirmations. An operator attaching a boundary "
            f"during an incident is not protected at the moment the API returns 200, and an "
            f"operator DETACHING one for a break-glass repair is still constrained after it "
            f"returns — both directions are in `propagation`"),
        "expiry": (
            f"an IAM evaluation-semantics result, dated by botocore {sdk} and by the account's "
            f"configuration on the run date. Permissions-boundary intersection is a documented "
            f"IAM rule rather than an AgentCore behaviour, so the fragile half is the resource "
            f"scoping: a new bedrock-agentcore action that reconfigures a gateway without being "
            f"called UpdateGateway would be outside the Deny form's reach, and this case would "
            f"still read TRUE. Re-run against the operation list when the service model changes"),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:            # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    n_of = {arm: (min(args.n, N_PER_ARM[arm]) if args.n else N_PER_ARM[arm]) for arm in ARMS}
    is_smoke = args.n is not None

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            ((ARM_PRE_GRANT,
              "the role's shipped configuration: no UpdateGateway at all. Must be DENIED, so "
              "the grant below is demonstrably what opens the route", n_of[ARM_PRE_GRANT]),
             (ARM_GRANTED,
              "MUTATION 1: an inline policy granting UpdateGateway + iam:PassRole. Must be "
              "ACCEPTED — without it every denial below is consistent with a request IAM "
              "refused to look at", n_of[ARM_GRANTED]),
             (ARM_BOUNDARY_DENY,
              "MUTATION 2a: boundary = Allow * plus an explicit Deny on UpdateGateway. The "
              "document's own wording", n_of[ARM_BOUNDARY_DENY]),
             (ARM_BOUNDARY_OMIT,
              "MUTATION 2b: boundary = an allow-list that omits UpdateGateway and INCLUDES "
              "iam:PassRole. The intersection rule, one variable", n_of[ARM_BOUNDARY_OMIT]),
             (ARM_REMOVED,
              "THE SEALED MUTATION: detach the boundary and re-run. Must be ACCEPTED again, or "
              "the denials above are not attributable to the boundary", n_of[ARM_REMOVED])),
            operations={"bedrock-agentcore:UpdateGateway": sum(n_of.values())},
            mutations=MAX_MUTATIONS,
            billable=True,
            text_units=0,
            text_units_why=("no model, no ApplyGuardrail and no InvokeGuardrailChecks: this "
                            "case is about who may reconfigure the gateway, not about what a "
                            "filter says"),
            extra=(
                f"sealed oracle ({O.BINDINGS[CASE].kind}): {O.oracle_text(CASE)}",
                f"mandatory mutation arm: {O.mutation_is_mandatory(CASE)} — and it is the "
                f"boundary REMOVAL, per the seal's 'remove boundary -> succeeds'",
                "every attempt sends the configuration read back from GetGateway, filtered to "
                "the members UpdateGateway accepts (from the service model at runtime). "
                "UpdateGateway is a FULL REPLACEMENT, so a body omitting protocolConfiguration "
                "or exceptionLevel would reset the gateway F4 and F6 are published against. An "
                "accepted call is therefore a no-op — and still an authorization event",
                "this case NEVER sets policyEngineConfiguration.mode; that is F5-2's subject. "
                "The gateway is diffed field for field at the end anyway, with "
                "policyEngineConfiguration compared explicitly rather than ignored",
                f"IAM propagation is polled after EVERY transition at {PROP_EVERY_S}s intervals "
                f"and needs {PROP_CONFIRM_N} CONSECUTIVE confirmations ({PROP_MAX_S}s bound for "
                f"an attach, {PROP_MAX_REMOVE_S}s for the detach — a ceiling that has not lifted "
                f"is not a hole, so patience there is cheap). Probe calls carry probe__<phase> "
                f"trial ids and are counted in NO arm",
                "a permissions boundary must be a MANAGED POLICY ARN, so this case creates two "
                "customer-managed policies as well as one inline grant. The detach ledger entry "
                "has a LOWER delete_priority than the policy entries, because a policy still "
                "serving as a boundary cannot be deleted",
                "iam:SimulatePrincipalPolicy is read per action under the omit form, so IAM's "
                "own answer about WHICH action is outside the ceiling is on the record. "
                "Corroborating only — a simulation is not an authorization event",
                "GetGateway as the attacker is sent under each boundary as an in-boundary "
                "control: it must SUCCEED, or a denial on UpdateGateway is not attributable to "
                "the ceiling withholding UpdateGateway",
                f"guards, all NOT_MEASURED-on-failure: {', '.join(GUARDS)}",
                "rc=2 if anything survives, whatever the verdict. A boundary left attached to "
                "grx-attacker would silently over-determine every future F5-1/F5-2 replication",
            ))

    state = T.State.load()
    run_id = state.run_id
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()
    fc_admin = A.factory(args.region)
    ac_admin = fc_admin.client("bedrock-agentcore-control")
    iam = fc_admin.iam()
    account_id = A.account_id(fc_admin)
    tag_list = [{"Key": k, "Value": v}
                for k, v in sorted(A.tags_for(state.run_id, state.expires_at).items())]

    print(f"{CASE} — route #4: does a permissions boundary stop UpdateGateway? "
          f"run_id={run_id} (adopted from the ledger), region={args.region}\n")

    gw = state.find("gateway", "main")
    role = state.find("iam-role", "attacker")
    gw_role = state.find("iam-role", "gw-exec")
    if not (gw and role and gw_role):
        rec = O.not_measured(
            CASE,
            f"the ledger is missing a resource this case needs (gateway={bool(gw)}, "
            f"attacker role={bool(role)}, gw-exec role={bool(gw_role)})",
            remedy="run infra/01_iam.py onward (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: incomplete ledger"}, store)
        return 2

    gateway_id = gw.ids["gateway_id"]
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    engine_id = gw.ids.get("policy_engine_id") or ""
    if not engine_id:
        rec = O.not_measured(CASE, "the main gateway has no policy engine in the ledger",
                             remedy="run infra/03_policy_engine.py and infra/04_gateway.py")
        P.emit(CASE, rec, {"instrument": "not built: no engine"}, store)
        return 2
    engine_arn = T.policy_engine_arn(args.region, account_id, engine_id)
    role_name = role.ids["role_name"]
    role_arn = T.unmask_arn(role.arn, account_id)
    gw_role_arn = T.unmask_arn(gw_role.arn, account_id)
    grant_name = f"grx-f53b-grant-{run_id}"
    # Managed policy names must be unique in the account and are what a human greps for at 3am.
    boundary_names = {ARM_BOUNDARY_DENY: f"grx-f53b-boundary-deny-{run_id}",
                      ARM_BOUNDARY_OMIT: f"grx-f53b-boundary-omit-{run_id}"}

    ac_attacker = A.factory(args.region, role_arn=role_arn).client("bedrock-agentcore-control")
    allowed, required = _update_shape(ac_admin)

    common: dict[str, Any] = {
        "run_id": run_id, "region": args.region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "instrument": (
            f"bedrock-agentcore:UpdateGateway on {gateway_id} as {role_name}, sending the "
            f"gateway's own current configuration as a full replacement; classified into "
            f"accepted / conflict / denied_by_iam / unusable"),
        "arms_planned": dict(n_of),
        "gateway_id": gateway_id, "policy_engine_id": engine_id,
        "attacker_role": role_name,
        "boundary_policy_names": boundary_names,
        "grant_policy_name": grant_name,
        "update_gateway_shape": {"accepted_members": sorted(allowed),
                                 "required_members": sorted(required),
                                 "read_from": "botocore service model at runtime"},
        "why_the_positive_control_is_mandatory": (
            "a permissions boundary denies by INTERSECTION, so if the identity policy never "
            "granted UpdateGateway the request is refused for the ordinary reason — and that "
            "AccessDeniedException is byte-for-byte identical to a boundary working. "
            "grx-attacker holds no UpdateGateway in its shipped configuration (infra/01_iam.py), "
            "so without an accepted call before any boundary existed this case would measure "
            "the role's shipped configuration and publish it as a property of the boundary"),
        "why_two_boundary_forms": (
            "an explicit Deny wins wherever it appears, so the deny form tests the document's "
            "sentence and would hold even if boundary intersection were broken. The omit form "
            "carries the mechanism: the action is absent from the ceiling and only the "
            "intersection rule denies it. Its allow-list deliberately includes iam:PassRole, "
            "because roleArn is a required member of UpdateGateway and a ceiling omitting both "
            "would deny for either reason"),
        "why_the_body_is_a_full_replacement": (
            "UpdateGateway replaces rather than patches, so omitting protocolConfiguration or "
            "exceptionLevel would reset the gateway F4 and F6 are published against. Every "
            "attempt sends what GetGateway returned, which also makes an unexpectedly-accepted "
            "call a no-op: authorization is evaluated before the body takes effect, so this "
            "does not weaken what the arms count"),
        "a_conflict_is_an_authorized_call": (
            "ConflictException is returned after authorization, so it is counted as AUTHORIZED "
            "and tallied separately: 'authorized then serialized away' and 'authorized and "
            "applied' are different observations of the same authorization outcome"),
        "no_checkpoint_by_design": (
            "a trial in a boundary arm is only meaningful while that boundary is attached, and "
            "a resumed process cannot re-enter the window it was killed in. A checkpoint would "
            "let a later run pair post-detach trials with a boundary that no longer exists"),
    }

    arms: dict[str, dict[str, Any]] = {}
    propagation: dict[str, dict[str, Any]] = {}
    controls: dict[str, dict[str, Any]] = {}
    simulations: dict[str, dict[str, Any]] = {}
    created: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    interlock_role: dict[str, Any] = {}
    interlock_gateway: dict[str, Any] = {}
    live_before: dict[str, Any] = {}
    boundary_state: dict[str, str] = {}          # arm -> policy arn currently attached
    grant_applied = False
    config_error = ""

    try:
        # ---- interlocks, before anything is mutated ----------------------
        interlock_role = assert_role_is_pristine(iam, store, role_name=role_name,
                                                 grant_name=grant_name)
        got = capture(store, "get_gateway", ac_admin, gatewayIdentifier=gateway_id)
        if not got.ok:
            raise ConfigError(
                f"GetGateway failed ({got.error_code}), so the gateway's starting configuration "
                f"was never measured. Refusing to send a replacement body assembled from "
                f"nothing, and refusing to claim at the end that nothing changed.")
        live_before = {k: v for k, v in (got.response or {}).items() if k != "ResponseMetadata"}
        interlock_gateway = assert_gateway_is_provisioned(live_before, engine_arn=engine_arn)
        body = _noop_body(live_before, gateway_id=gateway_id, allowed=allowed, required=required)
        common["noop_body_members"] = sorted(body)
        print(f"interlocks: {role_name} carries "
              f"{interlock_role['inline_policies_at_start']}, no boundary; gateway "
              f"{live_before.get('status')} in "
              f"{(live_before.get('policyEngineConfiguration') or {}).get('mode')}\n")

        # ---- arm 1: the shipped configuration ----------------------------
        print(f"[{ARM_PRE_GRANT}] n={n_of[ARM_PRE_GRANT]} with no grant and no boundary")
        arms[ARM_PRE_GRANT] = run_arm(ac_attacker, store, arm=ARM_PRE_GRANT, kwargs=body,
                                      n=n_of[ARM_PRE_GRANT])
        print(f"    {arms[ARM_PRE_GRANT]['reading']}  "
              f"codes={arms[ARM_PRE_GRANT]['error_codes']}")

        # ---- mutation 1: the identity grant, and the positive control ----
        put_grant(iam, store, state, role_name=role_name, policy_name=grant_name,
                  document=grant_document(gateway_arn, gw_role_arn))
        grant_applied = True
        created.append({"id": f"inline:{grant_name}", "kind": "iam-inline-policy",
                        "name": grant_name, "role": role_name})
        propagation["grant"] = wait_for_effect(
            ac_attacker, store, kwargs=body, want="accepted", phase="grant",
            gateway_id=gateway_id)
        print(f"    grant settled in {propagation['grant'].get('seconds')}s "
              f"(reached={propagation['grant'].get('reached')})")
        print(f"[{ARM_GRANTED}] n={n_of[ARM_GRANTED]} with the grant, no boundary")
        arms[ARM_GRANTED] = run_arm(ac_attacker, store, arm=ARM_GRANTED, kwargs=body,
                                    n=n_of[ARM_GRANTED], settle=True, gateway_id=gateway_id)
        print(f"    {arms[ARM_GRANTED]['reading']}  "
              f"codes={arms[ARM_GRANTED]['error_codes']}")

        # ---- mutations 2a and 2b: the two boundary forms -----------------
        # Run only if the positive control worked. Attaching a boundary after a failed control
        # would collect denials nobody can interpret, at the cost of two managed policies and
        # two IAM transitions on a role every other F5 case depends on.
        if arms[ARM_GRANTED]["n_authorized"] > 0:
            for arm in BOUNDARY_ARMS:
                logical = f"f53b_{arm}"
                made = create_boundary_policy(
                    iam, store, state, name=boundary_names[arm], logical=logical,
                    document=boundary_form_for(arm, gateway_arn=gateway_arn,
                                               gw_role_arn=gw_role_arn),
                    tag_list=tag_list,
                    description=f"{CASE} permissions boundary probe, {arm}. Deleted by the same "
                                f"run; if it survives, the run was killed.")
                created.append({"id": f"policy:{made['policy_arn']}", "kind": "iam-policy",
                                "name": made["policy_name"], "arm": arm})
                attach_boundary(iam, store, state, role_name=role_name,
                                policy_arn=made["policy_arn"], logical=logical)
                boundary_state[arm] = made["policy_arn"]
                created.append({"id": f"boundary:{arm}", "kind": "iam-permissions-boundary",
                                "name": role_name, "arm": arm})

                propagation[f"attach_{arm}"] = wait_for_effect(
                    ac_attacker, store, kwargs=body, want="denied_by_iam",
                    phase=f"attach_{arm}", gateway_id=gateway_id)
                print(f"    boundary {arm} in force after "
                      f"{propagation[f'attach_{arm}'].get('seconds')}s "
                      f"(reached={propagation[f'attach_{arm}'].get('reached')})")

                controls[arm] = in_boundary_control(ac_attacker, store, gateway_id=gateway_id,
                                                    arm=arm)
                simulations[arm] = simulate(
                    iam, store, role_arn=role_arn,
                    actions=(ACTION_UPDATE, ACTION_PASSROLE, ACTION_GET),
                    resource_arns=[gateway_arn], phase=arm)

                print(f"[{arm}] n={n_of[arm]} with the boundary attached")
                arms[arm] = run_arm(ac_attacker, store, arm=arm, kwargs=body, n=n_of[arm],
                                    settle=True, gateway_id=gateway_id)
                print(f"    {arms[arm]['reading']}  codes={arms[arm]['error_codes']}  "
                      f"in-boundary GetGateway ok={controls[arm]['ok']}")

                # Detach between the two forms: a role carries at most one boundary, and
                # replacing one with the other in a single call would make the propagation wait
                # unable to tell which ceiling it was watching converge.
                det = detach_boundary(iam, store, state, role_name=role_name, logical=logical)
                removed.append({"id": f"boundary:{arm}", "removed": det["detached"],
                                "detail": det})
                boundary_state.pop(arm, None)
                dele = delete_boundary_policy(iam, store, state,
                                              policy_arn=made["policy_arn"], logical=logical)
                removed.append({"id": f"policy:{made['policy_arn']}",
                                "removed": dele["deleted"], "detail": dele})

                # THE SEALED MUTATION, measured after the LAST form comes off. Measured once
                # rather than after each form: it is one claim — "remove boundary -> succeeds" —
                # and two arms with the same name would be two numbers for one sentence.
                if arm == BOUNDARY_ARMS[-1]:
                    propagation["detach"] = wait_for_effect(
                        ac_attacker, store, kwargs=body, want="accepted", phase="detach",
                        max_s=PROP_MAX_REMOVE_S, gateway_id=gateway_id)
                    print(f"    boundary lifted after "
                          f"{propagation['detach'].get('seconds')}s "
                          f"(reached={propagation['detach'].get('reached')})")
                    print(f"[{ARM_REMOVED}] n={n_of[ARM_REMOVED]} with the boundary detached")
                    arms[ARM_REMOVED] = run_arm(
                        ac_attacker, store, arm=ARM_REMOVED, kwargs=body,
                        n=n_of[ARM_REMOVED], settle=True, gateway_id=gateway_id)
                    print(f"    {arms[ARM_REMOVED]['reading']}  "
                          f"codes={arms[ARM_REMOVED]['error_codes']}")
        else:
            print("    positive control did NOT succeed — no boundary will be attached",
                  file=sys.stderr)

    except ConfigError as exc:
        config_error = str(exc)
        print(f"REFUSED: {exc}", file=sys.stderr)
    finally:
        # ---- teardown: the most important code in this file ---------------
        # Unconditional and idempotent. Every branch above may have been skipped, taken
        # halfway, or interrupted; what follows must be able to run after any of them.
        for arm, policy_arn in list(boundary_state.items()):
            det = detach_boundary(iam, store, state, role_name=role_name,
                                  logical=f"f53b_{arm}")
            removed.append({"id": f"boundary:{arm}", "removed": det["detached"], "detail": det})
            if not det["detached"]:
                print(f"    WARNING: boundary NOT detached: {det['manual_remedy']}",
                      file=sys.stderr)
            dele = delete_boundary_policy(iam, store, state, policy_arn=policy_arn,
                                          logical=f"f53b_{arm}")
            removed.append({"id": f"policy:{policy_arn}", "removed": dele["deleted"],
                            "detail": dele})
        # Belt and braces: anything this case registered in the ledger and did not remove.
        for r in list(state.of_kind("iam-permissions-boundary")):
            if r.ids.get("case") == CASE:
                det = detach_boundary(iam, store, state, role_name=r.ids.get("role_name", ""),
                                      logical=r.logical)
                removed.append({"id": f"boundary:{r.logical}", "removed": det["detached"],
                                "detail": det})
        for r in list(state.of_kind("iam-policy")):
            if r.ids.get("case") == CASE:
                dele = delete_boundary_policy(iam, store, state,
                                              policy_arn=T.unmask_arn(r.arn, account_id),
                                              logical=r.logical)
                removed.append({"id": f"policy:{T.unmask_arn(r.arn, account_id)}",
                                "removed": dele["deleted"], "detail": dele})
        if grant_applied:
            g = delete_grant(iam, store, state, role_name=role_name, policy_name=grant_name)
            removed.append({"id": f"inline:{grant_name}", "removed": g["deleted"], "detail": g})
            if not g["deleted"]:
                print(f"    WARNING: grant NOT deleted: {g['manual_remedy']}", file=sys.stderr)

        # ---- the end state, read back from the services ------------------
        boundary_at_end = read_boundary(iam, store, role_name=role_name)
        endr = capture(store, "list_role_policies", iam, RoleName=role_name)
        inline_at_end = (sorted(endr.response.get("PolicyNames") or []) if endr.ok else None)
        endg = capture(store, "get_gateway", ac_admin, gatewayIdentifier=gateway_id)
        live_after = ({k: v for k, v in (endg.response or {}).items()
                       if k != "ResponseMetadata"} if endg.ok else {})
        gateway_diff = (diff_configs(live_before, live_after, ignore=RESTORE_IGNORE)
                        if live_before and live_after else None)
        pec_identical = (live_before.get("policyEngineConfiguration")
                         == live_after.get("policyEngineConfiguration")
                         if live_before and live_after else False)
        res = residue(created, removed, boundary_at_end=boundary_at_end,
                      inline_at_end=inline_at_end)

    end_state = {
        "boundary_at_end": boundary_at_end,
        "inline_policies_at_end": inline_at_end,
        "role_end_state_read_ok": bool(endr.ok),
        "gateway_end_state_read_ok": bool(endg.ok),
        "gateway_fields_that_differ": gateway_diff,
        "gateway_pec_identical": pec_identical,
        "restore_ignore_list": list(RESTORE_IGNORE),
        "why_the_gateway_is_diffed_at_all": (
            "this case changes no gateway field, so an empty diff is the claim. Every accepted "
            "attempt was nonetheless a real full-replacement write, and policyEngineConfiguration "
            "is compared explicitly rather than sitting in the ignore list — the field F5-2 "
            "moves is the field a no-op body could most plausibly have dropped"),
    }

    reading = boundary_reading(arms)
    g = guards(interlock_role=interlock_role, interlock_gateway=interlock_gateway, arms=arms,
               propagation=propagation, controls=controls, res=res,
               gateway_read_ok=bool(endg.ok), gateway_diff=gateway_diff,
               pec_identical=pec_identical)
    narr = narrative(reading=reading, arms=arms, propagation=propagation,
                     sdk=A.sdk_versions().get("botocore", "?"))

    detail = {**common, **narr, "arms": arms, "guards": g, "guards_failed":
              sorted(k for k, v in g.items() if not v),
              "boundary_reading": reading, "propagation": propagation,
              "in_boundary_controls": controls, "simulations": simulations,
              "residue": res, "end_state": end_state,
              "startup_role_interlock": interlock_role,
              "startup_gateway_interlock": interlock_gateway,
              "mutation": {
                  "grant_applied": grant_applied,
                  "boundary_forms_attached": sorted(
                      a for a in BOUNDARY_ARMS if a in arms),
                  "sealed_mutation": "detach the boundary; the same body must be accepted again",
                  "sealed_mutation_arm": ARM_REMOVED,
                  "sealed_mutation_authorized": arms.get(ARM_REMOVED, {}).get("n_authorized", 0),
              }}

    if config_error:
        rec = O.not_measured(CASE, config_error, remedy="resolve the precondition and re-run",
                             arms=arms, residue=res)
        P.emit(CASE, rec, {**detail, "config_error": config_error}, store)
        # rc=2 either way: a refusal measured nothing, and if the refusal happened after a
        # mutation the residue block below has already reported what survived. Two reasons for
        # one exit code, both named in the record.
        return 2

    # ---- the two conditions under which no verdict is available ----------
    # Both are instrument failures, and both would otherwise be published as a verdict about
    # the document. The FALSE branch is deliberately NOT one of them: an ineffective boundary is
    # the sealed FALSE and is a finding.
    if not g["the_attack_succeeded_before_any_boundary_existed"]:
        rec = O.not_measured(
            CASE,
            f"the positive control did not succeed: with UpdateGateway and iam:PassRole granted "
            f"and NO boundary attached, the same body was still not authorized "
            f"({arms.get(ARM_GRANTED, {}).get('error_codes')}). Every denial under a boundary is "
            f"therefore consistent with a request IAM refused to look at — a wrong identifier, a "
            f"malformed body, an expired session — and cannot be read as the boundary working",
            arms=arms, residue=res)
        P.emit(CASE, rec, detail, store)
        print(f"\n{CASE}: NOT_MEASURED — the positive control did not succeed", file=sys.stderr)
        return 2

    if not g["removing_the_boundary_reopened_the_route"] and reading["all_forms_blocked"]:
        rec = O.not_measured(
            CASE,
            f"the boundary arms were denied but the sealed mutation did not invert: after "
            f"detaching the boundary the same body was still not authorized "
            f"({arms.get(ARM_REMOVED, {}).get('error_codes')}; detach wait reached="
            f"{propagation.get('detach', {}).get('reached')}). The denials are therefore not "
            f"attributable to the boundary — the likeliest alternative is that the grant itself "
            f"lapsed or that IAM had not converged — and publishing TRUE would credit the "
            f"boundary with a denial it may not have produced",
            arms=arms, residue=res)
        P.emit(CASE, rec, detail, store)
        print(f"\n{CASE}: NOT_MEASURED — the boundary removal did not reopen the route",
              file=sys.stderr)
        return 2

    obs = P.obs_existence(
        CASE, reading["all_forms_blocked"],
        # `n` is the number of trials the conjunction was evaluated over: the usable attempts in
        # the two arms the verdict reads. The control arms are NOT folded in — they answer yes/no
        # questions about the instrument, and summing them would denominate a security claim with
        # calls that were DESIGNED to be authorized (`feedback_two_numbers_two_claims`).
        n=sum(arms.get(a, {}).get("n_usable", 0) for a in BOUNDARY_ARMS),
        n_basis=(f"usable UpdateGateway attempts in {' + '.join(BOUNDARY_ARMS)}; the control "
                 f"arms are reported separately and are not part of this denominator"),
        arms={a: {k: v for k, v in t.items() if k != "rows"} for a, t in arms.items()},
        boundary_reading=reading, propagation=propagation, in_boundary_controls=controls,
        simulations=simulations, guards=g, residue=res, end_state=end_state)
    # An ATTRIBUTE, not a keyword: `obs_existence` sweeps surplus keywords into `detail`, which
    # the decision rule never reads, and F5-1 published INCONCLUSIVE over a clean 120-trial run
    # whose mandatory mutation had inverted 20/20 for exactly that. `P._detail` refuses the
    # keyword spelling outright now; this is the other spelling.
    #
    # The flag is a DIFFERENCE between arms, not a property of one: the boundary arms must have
    # denied AND the detached arm must have been authorized. Where the boundary was ineffective
    # the removal changed nothing, which is False — and for this EXISTENCE case that is the
    # correct reading and lands on the same FALSE the observation already carries, with
    # `evaluate` adding the note that the control was not load-bearing.
    obs.mutation_inverted = bool(reading["all_forms_blocked"]
                                 and arms.get(ARM_REMOVED, {}).get("n_authorized", 0) > 0)
    # `evaluate` takes the Observation ALONE — the case id travels inside it, so a record cannot
    # be decided under one case's binding while carrying another's data.
    rec = O.evaluate(obs)
    P.emit(CASE, rec, detail, store)

    print(f"\n{CASE}: {reading['per_form']} -> verdict {rec['verdict']}")
    print("guards: " + ", ".join(f"{k}={v}" for k, v in g.items()))
    if not all(g.values()):
        print("\nAT LEAST ONE GUARD IS FALSE — the verdict above is not publishable as it "
              f"stands; see results/phase1/{CASE}.json", file=sys.stderr)
    if not res["clean"]:
        print(f"\nRESIDUE SURVIVED: {res['surviving']} "
              f"boundary_still_attached={res['boundary_still_attached']} "
              f"unexpected_inline={res['unexpected_inline_policies']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
