#!/usr/bin/env python3
"""Phase 2 step 1: the four IAM roles the testbed needs.

Each role exists to make a specific claim testable, and the *shape* of each one is itself
under test. They are not four variations on a theme:

`grx-gw-exec` — the gateway execution role
    Carries **exactly** the two statements our §3.1 tells readers to attach:
    `bedrock-agentcore:*` and `bedrock:InvokeGuardrailChecks`. Written as two separate
    statements rather than one merged block, because **removing the second is the F5-4b
    mutation** — the crown jewel: strip the guardrail-evaluation permission that §3.1
    requires, so guardrail evaluation *cannot run*, and observe whether the engine fails
    closed (DENY) or open (ALLOW). §3.3 BP#4 admits AWS documents neither. A single merged
    statement would make that mutation an edit to a string; two statements make it a
    deletion, which is what a reader following §3.1 would actually get wrong.

`grx-caller` — the principal Cedar sees
    The harness **assumes** this role for every gateway invocation so the policy's principal
    is a stable `AgentCore::IamEntity`. Calling as the IAM user `timwu` would make principal
    matching depend on a principal no policy was written for, and — worse — the user carries
    AdministratorAccess, so every authorization test would run as a principal that can do
    anything. F4-4's "a request matching no policy is denied" is only meaningful for a
    principal whose access is decided by the policy engine.

`grx-attacker` — the red team identity
    Deliberately near-powerless. F5-1/F5-2 measure whether an identity *without*
    `UpdateGateway` can reach the tool or relax the mode; the mutation grants the permission
    and expects the attack to then succeed, proving the deny was load-bearing rather than
    incidental. Its permissions boundary is F5-3b's subject.

`grx-runtime-exec` — the runtime execution role
    F5-1's route #1: assume it and call `lambda:InvokeFunction` directly on the echo Lambda,
    going around the gateway. Expect AccessDenied; the mutation grants it and expects success
    with no `AuthorizeAction` span, which is what makes "the gateway is the only path" an
    observation rather than an assumption.

Why the trust policies are copied from a working role in this account
--------------------------------------------------------------------
`bedrock-agentcore.amazonaws.com` with `aws:SourceAccount` was read off
`retail-agentcore-gateway`, the execution role of a **READY** gateway in this account
(2026-08-10, read-only). A trust policy guessed from documentation and a trust policy proven
to work for a live gateway are different classes of evidence, and getting this wrong fails at
`CreateGateway` with a message about the role rather than about the trust relationship
(`feedback_verify_against_real_artifact`).

`grx-caller`, `grx-attacker` and `grx-runtime-exec` trust the **caller's own principal**
rather than a service. Their whole purpose is that the harness can assume them, and a role
trusting a service the harness is not cannot be assumed at all.

Idempotence
-----------
By name, like `f3_efficacy/00_guardrails.py`, and with the same rule: **a matching name is
not a matching configuration.** `--ensure` re-reads the live inline policies and the trust
policy and refuses the run when either disagrees with the spec, naming the field. A stale
`grx-gw-exec` — one still carrying an F5-4b mutation from a killed run, say — is READY and
attaches to a gateway perfectly well; nothing downstream would notice that guardrail
evaluation has been silently unable to run since the last aborted red-team arm.

Cost: IAM has no charges. **$0.**
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                            # noqa: E402
import redact                                                     # noqa: E402
from evidence import EvidenceStore, capture, new_run_id            # noqa: E402
from testbed import Resource, State                                # noqa: E402

# IAM is global, but every client in this project is region-pinned by construction
# (lib/awsclients.py makes `region` positional). us-east-1 is IAM's own endpoint region.
IAM_REGION = A.MAIN_REGION

# Deletion priority: roles go LAST (90) among Phase 2 resources. A gateway whose execution
# role has been deleted cannot be deleted cleanly, and a Lambda's resource policy references
# the gateway role's ARN.
_ROLE_PRIORITY = 90


def _sts_identity(f) -> tuple[str, str]:
    """(account id, caller ARN). Both needed: the account for ARNs, the ARN for trust."""
    ident = f.sts().get_caller_identity()
    return ident["Account"], ident["Arn"]


def service_trust(account_id: str) -> dict:
    """Trust policy for a role AgentCore assumes.

    Read off `retail-agentcore-gateway` — the live execution role of a READY gateway in this
    account — rather than composed from docs. `aws:SourceAccount` is the confused-deputy
    guard and is present in that working policy, so it is present here.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": account_id}},
        }],
    }


def caller_trust(caller_arn: str, account_id: str) -> dict:
    """Trust policy for a role the harness assumes.

    The caller's *exact* ARN, not the account root. `Principal: {"AWS": account}` would let
    any principal in the account assume it, and F5-1/F5-2's whole design is that
    `grx-attacker` and `grx-runtime-exec` are reachable only through a deliberate
    `AssumeRole` by the harness. A role assumable by everything in the account cannot support
    a claim about what an identity *cannot* do.

    An assumed-role ARN is normalised to its role ARN: `sts:AssumeRole` trust cannot name a
    session (`arn:aws:sts::<acct>:assumed-role/Name/session`), only the role itself. Without
    this the script would work when run as an IAM user and fail with an opaque
    MalformedPolicyDocument when run from an assumed role — e.g. from CI.
    """
    principal = caller_arn
    parts = caller_arn.split(":")
    if len(parts) >= 6 and parts[2] == "sts" and parts[5].startswith("assumed-role/"):
        role_name = parts[5].split("/")[1]
        principal = f"arn:aws:iam::{account_id}:role/{role_name}"
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": principal},
            "Action": "sts:AssumeRole",
        }],
    }


def role_specs(run_id: str, account_id: str, caller_arn: str,
               region: str) -> dict[str, dict]:
    """The declared table: logical name -> spec.

    Resource ARNs are scoped to this run's names wherever the API permits it. A wildcard
    would be simpler and would silently widen every red-team arm: `grx-attacker` granted
    `lambda:InvokeFunction` on `*` could reach another system's function in this account,
    which carries ~$27k/mo of unrelated workloads.
    """
    echo_arn = f"arn:aws:lambda:{region}:{account_id}:function:grx-echo-{run_id}"
    specs: dict[str, dict] = {}

    # --- the gateway execution role ---------------------------------------
    specs["gw-exec"] = {
        "name": f"grx-gw-exec-{run_id}",
        "purpose": "gateway execution role carrying exactly the doc's §3.1 policy",
        "trust": service_trust(account_id),
        "inline": {
            # TWO statements, deliberately. Statement 2 is F5-4b's deletion target: §3.1
            # requires `bedrock:InvokeGuardrailChecks` on the gateway execution role, and
            # removing it makes guardrail evaluation unable to run. Whether the engine then
            # denies or allows is the experiment §3.3 BP#4 says AWS does not document.
            "grx-gw-exec-policy": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AgentCoreAsDocumented",
                        "Effect": "Allow",
                        "Action": "bedrock-agentcore:*",
                        "Resource": "*",
                    },
                    {
                        # Kept as its own Sid so the F5-4b mutation is "remove the statement
                        # with this Sid" — a data operation a journal can record and replay,
                        # not a string edit (see lib/mutation_journal.py's design).
                        "Sid": "InvokeGuardrailChecks",
                        "Effect": "Allow",
                        "Action": "bedrock:InvokeGuardrailChecks",
                        "Resource": "*",
                    },
                    {
                        # NOT from the document. The gateway must be able to invoke its
                        # Lambda target, which §3.1 does not mention because it is a property
                        # of using a Lambda target rather than of guardrails. Marked so the
                        # F5-4b analysis cannot mistake it for a documented requirement:
                        # the doc's claim is about the first two statements only.
                        "Sid": "HarnessLambdaTargetNotFromTheDocument",
                        "Effect": "Allow",
                        "Action": "lambda:InvokeFunction",
                        "Resource": [echo_arn, f"{echo_arn}:*"],
                    },
                ],
            },
        },
    }

    # --- the stable Cedar principal ---------------------------------------
    specs["caller"] = {
        "name": f"grx-caller-{run_id}",
        "purpose": "the principal Cedar sees; assumed by the harness for every gateway call",
        "trust": caller_trust(caller_arn, account_id),
        "inline": {
            # `bedrock-agentcore:InvokeGateway`-shaped access plus the MCP data-plane call.
            # Scoped to this run's gateways by name pattern: the account holds 6 pre-existing
            # READY gateways that must never be reachable by a harness identity.
            "grx-caller-policy": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "InvokeOurGatewaysOnly",
                        "Effect": "Allow",
                        "Action": ["bedrock-agentcore:InvokeGateway",
                                   "bedrock-agentcore:GetGateway",
                                   "bedrock-agentcore:ListGateways",
                                   "bedrock-agentcore:ListGatewayTargets",
                                   "bedrock-agentcore:GetGatewayTarget"],
                        "Resource": [
                            f"arn:aws:bedrock-agentcore:{region}:{account_id}:gateway/grx-gw-*",
                            f"arn:aws:bedrock-agentcore:{region}:{account_id}:gateway/grx-gw-*/*",
                        ],
                    },
                    {
                        # Read-only on the policy engine: F4's arms need to confirm the
                        # engine's mode and the policy's enforcementMode as part of the
                        # oracle, and reading it as the *caller* rather than as an admin
                        # keeps the observation inside the identity under test.
                        "Sid": "ReadOurPolicyEngine",
                        "Effect": "Allow",
                        "Action": ["bedrock-agentcore:GetPolicyEngine",
                                   "bedrock-agentcore:GetPolicy",
                                   "bedrock-agentcore:ListPolicies",
                                   "bedrock-agentcore:ListPolicyEngines"],
                        "Resource": "*",
                    },
                ],
            },
        },
    }

    # --- the red team identity --------------------------------------------
    specs["attacker"] = {
        "name": f"grx-attacker-{run_id}",
        "purpose": "F5-1/F5-2 attacker: can invoke, cannot UpdateGateway, cannot invoke "
                   "Lambda directly",
        "trust": caller_trust(caller_arn, account_id),
        "inline": {
            # Read + invoke only. Every F5 attack asserts a specific AccessDenied, so the
            # role must be able to *reach* the API (a network or endpoint error is not an
            # authorization result) while lacking the one permission under test. Note the
            # absence of UpdateGateway, DeleteGateway, UpdatePolicy and lambda:InvokeFunction
            # — each absence is a separate F5 oracle, and each is granted by a mutation.
            "grx-attacker-policy": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "ReachTheApiButChangeNothing",
                        "Effect": "Allow",
                        "Action": ["bedrock-agentcore:GetGateway",
                                   "bedrock-agentcore:ListGateways",
                                   "bedrock-agentcore:InvokeGateway",
                                   "bedrock-agentcore:GetPolicyEngine",
                                   "bedrock-agentcore:ListPolicies"],
                        "Resource": "*",
                    },
                    {
                        # sts:GetCallerIdentity so an arm can prove WHICH identity produced
                        # an AccessDenied. Without it, "the attacker was denied" and "the
                        # assume-role silently fell back to the harness identity" look the
                        # same in the evidence.
                        "Sid": "ProveWhoWeAre",
                        "Effect": "Allow",
                        "Action": "sts:GetCallerIdentity",
                        "Resource": "*",
                    },
                ],
            },
        },
    }

    # --- the runtime execution role ---------------------------------------
    specs["runtime-exec"] = {
        "name": f"grx-runtime-exec-{run_id}",
        "purpose": "F5-1 route #1: must NOT be able to invoke the echo Lambda directly",
        # Trusts BOTH the service (it is a runtime execution role) and the caller (F5-1
        # assumes it directly to make the attempt). Two statements rather than a merged
        # Principal block, because they are two different facts and one may be revoked
        # without the other.
        "trust": {
            "Version": "2012-10-17",
            "Statement": (service_trust(account_id)["Statement"]
                          + caller_trust(caller_arn, account_id)["Statement"]),
        },
        "inline": {
            "grx-runtime-exec-policy": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        # Deliberately NO lambda:InvokeFunction. That absence IS F5-1's
                        # oracle, and F5-1's mutation adds it as a separate inline policy so
                        # the undo is "delete a named policy" rather than "edit a document".
                        "Sid": "ObservabilityAndIdentityOnly",
                        "Effect": "Allow",
                        "Action": ["sts:GetCallerIdentity",
                                   "logs:CreateLogStream", "logs:PutLogEvents"],
                        "Resource": "*",
                    },
                ],
            },
        },
    }

    return specs


# ---------------------------------------------------------------------------
# idempotence: a matching name is not a matching configuration
# ---------------------------------------------------------------------------

def _doc(raw) -> dict:
    """IAM returns policy documents URL-encoded when the client is not JSON-aware."""
    if isinstance(raw, str):
        return json.loads(urllib.parse.unquote(raw))
    return raw


def _canon(obj):
    """Order-insensitive canonical form for policy comparison.

    IAM re-orders `Action` and `Resource` lists and may return a single-element list as a
    bare string. A naive `==` would report drift on every run, which trains the operator to
    pass `--force` — and a check that is habitually bypassed is not a check.
    """
    if isinstance(obj, dict):
        return {k: _canon(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return sorted((_canon(v) for v in obj), key=lambda x: json.dumps(x, sort_keys=True))
    if isinstance(obj, str):
        return obj
    return obj


def verify_role(iam, name: str, spec: dict) -> list[str]:
    """Fields where the live role disagrees with its spec. Empty means verified.

    Compares the trust policy and every inline policy document. This is the check that
    catches a role still carrying a mutation from a killed red-team run: `grx-gw-exec`
    without its `InvokeGuardrailChecks` statement is a perfectly healthy role that attaches
    to a gateway and silently cannot evaluate guardrails.
    """
    bad: list[str] = []
    try:
        live = iam.get_role(RoleName=name)["Role"]
    except iam.exceptions.NoSuchEntityException:
        return [f"role {name} does not exist"]

    if _canon(_doc(live.get("AssumeRolePolicyDocument"))) != _canon(spec["trust"]):
        bad.append("trust policy differs from spec")

    want = spec["inline"]
    got_names = set(iam.list_role_policies(RoleName=name)["PolicyNames"])
    missing = sorted(set(want) - got_names)
    extra = sorted(got_names - set(want))
    if missing:
        bad.append(f"inline policies missing: {missing}")
    if extra:
        # An EXTRA inline policy is the shape a red-team mutation leaves behind: F5-1's
        # mutation adds `grx-mutation-*` granting lambda:InvokeFunction. Reporting it as
        # drift is the point — a leftover grant is a live privilege escalation.
        bad.append(f"unexpected inline policies present (a leftover mutation?): {extra}")
    for pn in sorted(set(want) & got_names):
        live_doc = _doc(iam.get_role_policy(RoleName=name, PolicyName=pn)["PolicyDocument"])
        if _canon(live_doc) != _canon(want[pn]):
            live_sids = sorted(s.get("Sid", "?") for s in live_doc.get("Statement", []))
            want_sids = sorted(s.get("Sid", "?") for s in want[pn].get("Statement", []))
            detail = (f"statement Sids live={live_sids} spec={want_sids}"
                      if live_sids != want_sids else "statement bodies differ")
            bad.append(f"inline policy {pn} differs: {detail}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the four roles and their policies; make no mutating call")
    ap.add_argument("--ensure", action="store_true",
                    help="create anything missing; verify anything present")
    ap.add_argument("--fix-drift", action="store_true",
                    help="rewrite trust and inline policies where the live role disagrees "
                         "with the spec. Off by default: an unexpected inline policy is "
                         "usually a leftover red-team mutation, and silently deleting it "
                         "would erase the evidence that a run left a privilege behind.")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--ttl-hours", type=int, default=72)
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None, help="path to state.json")
    args = ap.parse_args()

    if not args.dry_run and not args.ensure:
        print("refusing to run: pass --dry-run or --ensure. A script whose default action "
              "mutates the account is the wrong default.", file=sys.stderr)
        return 2

    state_path = Path(args.state) if args.state else None

    # --dry-run must make NO AWS call at all, including sts:GetCallerIdentity, so the
    # printed table is produced with placeholders. That keeps the contract "no AWS call"
    # literally true and makes two dry runs byte-identical and diffable.
    if args.dry_run:
        run_id = args.run_id or "dryrun"
        account_id = redact.ACCOUNT_PLACEHOLDER
        caller_arn = f"arn:aws:iam::{account_id}:user/<caller>"
        # The placeholder is passed through, NOT a 12-digit stand-in. An earlier draft passed
        # a literal `0`×12 here, which the redaction gate correctly reported as an account-id
        # shape: the gate's patterns are shape-based on purpose, so any 12-digit literal in
        # the tree is a finding regardless of its value, and arguing for an exception would
        # have meant either waiving a shape the gate exists to catch or spelling a fake
        # account id into source. Using the placeholder removes the shape instead of excusing
        # it, and it makes the printed table consistent with `caller_arn` above rather than
        # showing two different fictions for the same account in one dry run.
        specs = role_specs(run_id, account_id, caller_arn, args.region)
        print(f"Phase 2 step 1 — {len(specs)} IAM roles, run_id={run_id}")
        for logical, spec in specs.items():
            print(f"\n  {logical:14s} {spec['name']}")
            print(f"                 {spec['purpose']}")
            trust_p = [s.get("Principal") for s in spec["trust"]["Statement"]]
            print(f"                 trusts: {json.dumps(redact.mask(trust_p))}")
            for pn, doc in spec["inline"].items():
                sids = [s.get("Sid") for s in doc["Statement"]]
                print(f"                 inline {pn}: {sids}")
        print("\n--dry-run: no AWS call made (account id and caller ARN are placeholders).")
        return 0

    run_id = args.run_id or new_run_id()
    expires = (datetime.now(timezone.utc)
               + timedelta(hours=args.ttl_hours)).replace(microsecond=0).isoformat()

    f = A.factory(args.region)
    iam = f.iam()
    account_id, caller_arn = _sts_identity(f)
    specs = role_specs(run_id, account_id, caller_arn, args.region)

    state = State.load_or_new(run_id, args.region, expires, path=state_path)
    # Resume keeps the ledger's run id, so the specs must be rebuilt against it — otherwise a
    # resumed run would create `grx-gw-exec-<new>` while the ledger names `<old>`.
    if state.run_id != run_id:
        run_id = state.run_id
        specs = role_specs(run_id, account_id, caller_arn, args.region)
    tags = A.tags_for(state.run_id, state.expires_at)
    tag_list = [{"Key": k, "Value": v} for k, v in sorted(tags.items())]

    store = EvidenceStore(state.run_id, "infra", "P2-01-iam")
    store.write_environment()

    print(f"Phase 2 step 1 — IAM, run_id={state.run_id}, region={args.region}")
    created, verified, drifted = 0, 0, []

    for logical, spec in specs.items():
        name = spec["name"]
        drift = verify_role(iam, name, spec)
        exists = not (len(drift) == 1 and drift[0].endswith("does not exist"))

        if exists and drift and not args.fix_drift:
            print(f"  DRIFT   {logical:14s} {name}", file=sys.stderr)
            for d in drift:
                print(f"          - {d}", file=sys.stderr)
            drifted.append(logical)
            continue

        if not exists:
            rec = capture(store, "create_role", iam,
                          RoleName=name,
                          AssumeRolePolicyDocument=json.dumps(spec["trust"]),
                          Description=spec["purpose"][:1000],
                          MaxSessionDuration=3600,
                          Tags=tag_list)
            if not rec.ok:
                print(f"  FAILED  {logical}: {rec.error_code}: {rec.error_message}",
                      file=sys.stderr)
                drifted.append(logical)
                continue
            created += 1
            print(f"  created {logical:14s} {name}  request-id {rec.request_id}")
        elif args.fix_drift:
            print(f"  fixing  {logical:14s} {name}: {'; '.join(drift)}")
            capture(store, "update_assume_role_policy", iam, RoleName=name,
                    PolicyDocument=json.dumps(spec["trust"])).raise_for_status()
            for pn in iam.list_role_policies(RoleName=name)["PolicyNames"]:
                if pn not in spec["inline"]:
                    print(f"          removing unexpected inline policy {pn}")
                    capture(store, "delete_role_policy", iam,
                            RoleName=name, PolicyName=pn).raise_for_status()

        # put_role_policy is idempotent (it overwrites), so it runs on both the create and
        # the fix path. Applied AFTER the role exists, in a loop that raises: a role created
        # without its inline policy is a role that fails at a use site far from here.
        for pn, doc in spec["inline"].items():
            capture(store, "put_role_policy", iam, RoleName=name, PolicyName=pn,
                    PolicyDocument=json.dumps(doc)).raise_for_status()

        arn = iam.get_role(RoleName=name)["Role"]["Arn"]
        state.record(Resource(
            kind="iam-role", logical=logical, name=name, service="iam",
            delete_op="delete_role", delete_params={"RoleName": name},
            ids={"role_name": name},
            arn=arn, delete_priority=_ROLE_PRIORITY,
            notes=spec["purpose"] + " | inline policies must be deleted before the role",
        ))
        # Stored so teardown does not have to list them at delete time: a role whose inline
        # policies cannot be enumerated (throttled, or the role already half-deleted) would
        # otherwise fail DeleteConflict with nothing to act on.
        state.get("iam-role", logical).ids["inline_policies"] = sorted(spec["inline"])
        state.write()

        post = verify_role(iam, name, spec)
        if post:
            # Re-verified after writing, never assumed: the same rule the mutation arms
            # follow (restore, then re-run the assertion). A put_role_policy that returned
            # 200 and left a different document is exactly the case a trusting script misses.
            print(f"  FAILED  {logical}: still drifted after write: {post}", file=sys.stderr)
            drifted.append(logical)
        else:
            verified += 1
            if exists and not args.fix_drift:
                print(f"  exists  {logical:14s} {name}  (config verified)")

    store.write_summary({"created": created, "verified": verified,
                         "drifted": sorted(drifted), "n_specs": len(specs)})
    print(f"\nstate -> {state.write().name}  "
          f"({created} created, {verified} verified this run)")

    if drifted:
        print(f"\nFAIL: {len(drifted)} role(s) not in the specified state: "
              f"{sorted(drifted)}\n"
              f"      An unexpected inline policy is usually a red-team mutation a killed "
              f"run failed to undo — a live privilege, not untidiness. Inspect it, then "
              f"re-run with --fix-drift to remove it.", file=sys.stderr)
        return 1

    # IAM is eventually consistent for role propagation to other services: CreateGateway can
    # fail with "cannot assume role" for a role created seconds earlier. Said here rather than
    # slept on, because a sleep whose length nothing verifies is a guess, and 02_lambda.py's
    # own create is the natural place the delay is absorbed.
    if created:
        print("note: IAM role propagation is eventually consistent. If CreateGateway "
              "reports it cannot assume grx-gw-exec, re-run 05_gateway.py — the role is "
              "correct, the propagation was not complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
