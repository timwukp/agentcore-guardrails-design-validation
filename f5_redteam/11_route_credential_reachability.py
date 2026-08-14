#!/usr/bin/env python3
"""F5-8: are the execution role's credentials readable from inside a tool session?

    Sealed oracle: "TRUE if sts:GetCallerIdentity from inside the session returns the
    execution role; FALSE if credentials are unreachable. Confirms 4.4's premise from PUBLIC
    evidence, removing an NDA citation"
    Sealed method: "minimal runtime whose handler calls GetCallerIdentity"
    Binding: EXISTENCE

WHY THIS CASE MATTERED ENOUGH TO UNBLOCK
----------------------------------------
Section 4.4 of the design document rests on one mechanism, and states it as fact:

    "any code in the session can read the execution role's credentials via the microVM
     metadata service (Accelerator: 'any code executing within a tool session can access
     these credentials')"

Everything section 4.4 recommends follows from that sentence. The reason the execution role
must not hold `bedrock-agentcore:UpdateGateway`, or policy-engine mutation, or interceptor
management, is that a jailbroken agent can *become* the execution role and use those grants
itself. If the premise is false the advice is merely tidy; if it is true the advice is the
anti-jailbreak control, and least privilege on that role is load-bearing.

The citation was to an NDA'd accelerator document. This case replaces it with a public
measurement, which is the entire value on offer: the recommendation stops depending on a
source a reader cannot check.

WHY IT WAS BLOCKED, AND WHAT WAS ACTUALLY IN THE WAY
---------------------------------------------------
The recorded blocker was that an AgentCore Runtime needs a linux/arm64 CONTAINER image, and
so needed an ECR repository and a Graviton or CodeBuild builder that this project does not
have. That premise read one arm of a union. `agentRuntimeArtifact` also accepts
`codeConfiguration` — an S3 zip, `PYTHON_3_12`, and an entry point — and AWS's "AgentCore
Runtime only supports arm64" sentence sits inside a `uv pip install
--python-platform aarch64-manylinux2014` instruction: it is about WHEELS. Standard-library
code has no wheels to cross-build.

`f5_redteam/diag_runtime_code_artifact.py` measured that on 2026-08-14: `CreateAgentRuntime`
with `codeConfiguration` was accepted, reached READY in 10.8 seconds, and served an HTTP 200.
No container, no ECR, no builder. This producer runs the sealed method through that arm.

WHY THE FIRST PROBE'S ANSWER WAS NOT USED
-----------------------------------------
The diagnostic's first live run reported `credential_source: "none_found"` and no reachable
credentials. Read literally that is F5-8 FALSE — the oracle's own words are "FALSE if
credentials are unreachable" — and it would have published a refutation of section 4.4's
premise.

It was a probe gap. That run checked two channels, `AWS_*` environment variables and the
container-credentials endpoint, and the document names a third one explicitly: the microVM
metadata service, 169.254.169.254, which had never been tried. `runtime_code_pkg` now probes
eight channels and records every one of them, tried or skipped, with its status or its
exception name. A negative on this case is publishable, so it may not rest on the list of
places somebody happened to look; the list is therefore part of the record.

WHAT A TRUE HERE DOES NOT ESTABLISH
-----------------------------------
Three things, and they are worth stating because each is a plausible over-read.

It does not establish that the credentials carry any particular PERMISSION. This runtime's
execution role can read one S3 prefix and write logs. That an agent can assume its execution
role says nothing about what that role may do — which is exactly why section 4.4's advice is
about the role's grants and not about the reachability.

It does not establish reachability from a CONTAINER-based runtime. This measures the
`codeConfiguration` arm. The two arms are the same microVM contract as documented, and the
credential channel is a property of the sandbox rather than of the artefact, but that is an
inference and it is not what ran.

It does not establish that `sts:GetCallerIdentity` was AUTHORIZED. That call needs no IAM
permission at all, and the execution policy this script attaches deliberately omits it. The
measurement is that credentials exist and STS accepts them, not that a grant allowed it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import awsclients as A                                               # noqa: E402
import oracle as O                                                   # noqa: E402
import phase1 as P                                                   # noqa: E402
import testbed as T                                                  # noqa: E402
from evidence import EvidenceStore, capture                          # noqa: E402
from runtime_code_pkg import (                                       # noqa: E402
    build_zip, execution_policy, service_trust)

FAMILY = "f5_redteam"
CASE = "F5-8"

# Three invocations, not one. Each `InvokeAgentRuntime` without a session id opens a NEW tool
# session, and the claim under test is about "any code executing within a tool session" — so the
# denominator that means anything is a count of sessions, and one session cannot distinguish "the
# credentials are there" from "the credentials were there once". Three is small because the
# EXISTENCE binding is a conjunction and not a rate: a single session that could not reach its
# credentials would make this FALSE, and no number of extra sessions would recover it.
N_TRIALS_DEFAULT = 3

# The poll cadence for the create. A real interval, unlike a `lim.wait()` on an operation the
# rate-limit table does not know: `GetAgentRuntime` has no `RATE_LIMITS` entry, so a `wait` on it
# would return 0.0 and read in the source as pacing that is not happening (DEV-P4-33).
POLL_SECONDS = 10
POLL_TIMEOUT = 600
INTER_IAM_S = 2.0

# Terminal states, from the SDK's own `AgentRuntimeStatus` enum: CREATING / CREATE_FAILED /
# UPDATING / UPDATE_FAILED / READY / DELETING.
TERMINAL = {"READY", "CREATE_FAILED", "UPDATE_FAILED"}

# The bucket this project keeps AgentCore deployment packages in. It is composed by the same rule
# `runner/iam_policy.py` composes its `code_bucket` ARN pattern by, and the two must agree or the
# runner is denied `PutObject` on a bucket the policy does not name.
# `f5_redteam/tests/test_route_credential_reachability.py` pins the agreement, because the failure
# mode is a mid-run AccessDenied on the instance rather than anything visible at desk.
CODE_BUCKET_STEM = "runtime-code"


def bucket_name(account: str, region: str) -> str:
    return f"grx-{CODE_BUCKET_STEM}-{account}-{region}"


def _identity_of(body: str) -> dict:
    """The `identity` block out of one `/invocations` response, or a reason it is missing."""
    try:
        return dict(json.loads(body).get("identity") or {})
    except Exception as exc:                                          # noqa: BLE001
        return {"error": f"the response body did not parse: {type(exc).__name__}",
                "body_head": body[:200]}


def _returned_the_execution_role(identity: dict, role_name: str) -> tuple[bool, str]:
    """Did this session's STS answer name THIS runtime's execution role?

    The test is on the assumed-role name inside the ARN, not on a substring of the whole
    response, and not merely on `sts_http_status == 200`. A 200 is necessary and not
    sufficient: STS answers 200 for whatever principal the credentials belong to, so an
    instance-profile credential leaking in from the caller's environment would also be a 200
    and would also contain an ARN. What makes it F5-8's TRUE is that the principal is the
    execution role this script created for this runtime and passed to no one else.
    """
    if identity.get("sts_http_status") != 200:
        return False, (f"sts_http_status was {identity.get('sts_http_status')!r}, "
                       f"credential_source {identity.get('credential_source')!r}")
    want = f"assumed-role/{role_name}/"
    body = identity.get("sts_response") or ""
    if want not in body:
        return False, f"STS answered 200 but the principal is not {want!r}"
    return True, f"assumed-role/{role_name}/ via {identity.get('credential_source')!r}"


def _dry_run(args: argparse.Namespace) -> int:
    print(f"{CASE} dry run — no AWS call, no client, no ledger read\n")
    print(f"oracle ({O.BINDINGS[CASE].kind}): {O.oracle_text(CASE)}\n")
    print(f"pre-registered n: {O.planned_n(CASE) or 'none'}   "
          f"mandatory mutation arm: {O.mutation_is_mandatory(CASE)}")
    print(f"\nwould create, in order:")
    print(f"  1. an IAM role  grx-runtime-cred-<run_id>  (ledgered BEFORE the create)")
    print(f"  2. an S3 object f5-8/<run_id>/deployment_package.zip in "
          f"grx-{CODE_BUCKET_STEM}-<account>-{args.region}")
    print(f"     the bucket is a PRECONDITION and is not created here — "
          f"run f5_redteam/diag_runtime_code_artifact.py if it is absent")
    print(f"  3. an AgentCore Runtime grx_f58_cred_<run_id>, codeConfiguration / "
          f"PYTHON_3_12 / HTTP / PUBLIC")
    print(f"\nwould then invoke it {args.n} time(s) — {args.n} separate tool sessions — and read "
          f"the identity each session reports")
    print(f"would delete all three, then write results/phase1/{CASE}.json")
    print(f"\nzip: {len(build_zip())} bytes, 1 entry (main.py, 0o644)")
    print("billable model calls: 0. This case calls no model: the handler talks to STS, "
          "which is free.")
    return 0


def main(argv: list[str] | None = None) -> int:                       # noqa: C901, PLR0912, PLR0915
    ap = argparse.ArgumentParser(description=f"{CASE} execution-role credential reachability")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and the oracle; make no AWS call")
    ap.add_argument("--n", type=int, default=N_TRIALS_DEFAULT,
                    help=f"tool sessions to open (default {N_TRIALS_DEFAULT})")
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--evidence-root", default=None)
    args = ap.parse_args(argv)

    # Before any client and before the ledger: a --dry-run that builds a client has already
    # authenticated, and one that reads the ledger fails in a fresh clone for a reason that has
    # nothing to do with the case.
    if args.dry_run:
        return _dry_run(args)

    if O.mutation_is_mandatory(CASE):
        raise SystemExit(
            f"{CASE} is sealed with a mandatory mutation arm and this script implements a single "
            f"observation arm. Publishing without the mutation would publish under a rule the "
            f"seal does not name.")

    # The run id comes from the ledger, never minted here: one testbed, one ledger, one run id,
    # or the RunId tag splits across resources and a teardown sweep for either value finds half.
    state = T.State.load(Path(args.state) if args.state else None)
    run_id = state.run_id
    if state.region != args.region:
        raise SystemExit(f"ledger is for {state.region}, not {args.region}")

    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    fc = A.factory(args.region)
    # Through the choke point, which also registers the id with the redactor. An inline
    # get_caller_identity()["Account"] would put a bare 12-digit number into a distributable
    # record (lib/tests/test_account_id_choke_point.py).
    account = A.account_id(fc)
    iam = fc.client("iam")
    s3 = fc.client("s3")
    ac = fc.client("bedrock-agentcore-control")
    rt = fc.client("bedrock-agentcore")

    short = run_id.lower().replace("-", "").replace("_", "")
    role_name = f"grx-runtime-cred-{run_id}"
    rt_name = f"grx_f58_cred_{short}"
    bucket = bucket_name(account, args.region)
    prefix = f"f5-8/{run_id}/deployment_package.zip"

    print(f"{CASE} — run_id={run_id}, region={args.region}, sessions={args.n}")
    print(f"  oracle: {O.oracle_text(CASE)}\n")

    trials: list[dict] = []
    # Initialised before the try: the `finally` and the verdict block below both read them, and a
    # failure in step 0 would otherwise raise NameError from inside the teardown — which is the one
    # place in this script where an avoidable crash costs an undeleted resource.
    status = ""
    elapsed = 0.0
    runtime_id = ""
    runtime_arn = ""
    role_arn = ""
    object_put = False
    residue: dict = {}

    try:
        # ---- 0. the bucket is a precondition, not a step ----------------------
        # HeadBucket and not CreateBucket, deliberately. A create here would need
        # `s3:CreateBucket` in the runner's derived policy for a bucket that already exists,
        # and a bucket is the one resource in this script that outlives the run — so it is
        # provisioned once by the diagnostic and asserted here. A refusal names the fix.
        head = capture(store, "head_bucket", s3, Bucket=bucket)
        if not head.ok:
            raise SystemExit(
                f"the deployment-package bucket {bucket} is not reachable "
                f"({head.error_code or head.error_class}: {head.error_message}). It is a "
                f"precondition of this case, not something it creates: run "
                f"`python3 f5_redteam/diag_runtime_code_artifact.py` once, which creates it, "
                f"or grant s3:ListBucket on it if the bucket is there and this caller is not "
                f"allowed to see it.")
        print(f"  bucket: {bucket} reachable")

        # ---- 1. the execution role ------------------------------------------
        # Ledger FIRST, then create. The window between a successful create and a recorded
        # create is the window in which a kill leaves an untracked resource; a stale ledger
        # entry costs one NoSuchEntity at teardown, which is the cheaper failure.
        #
        # A NEW role, deliberately. `grx-runtime-exec-<run_id>` exists and looks like the
        # obvious candidate, but the exact content of its inline policy set IS F5-1's published
        # oracle — that case asserts the baseline at startup and `infra/01_iam.py --ensure`
        # refuses on drift — so adding an S3 read to it would silently change the premise of a
        # case that is already published.
        state.record(T.Resource(
            kind="iam-role", logical="f58_runtime_exec", name=role_name,
            service="iam", delete_op="delete_role", delete_params={"RoleName": role_name},
            ids={"role_name": role_name, "case": CASE}, delete_priority=20,
            notes=("F5-8's runtime execution role. Its inline policy `grx-runtime-cred` must be "
                   "deleted before the role. If this is still here, the run did not reach its "
                   "teardown.")))
        state.write()
        rec = capture(store, "create_role", iam, RoleName=role_name,
                      AssumeRolePolicyDocument=json.dumps(service_trust(account)),
                      Description=f"GRX {CASE}: AgentCore Runtime credential reachability",
                      Tags=[{"Key": k, "Value": v} for k, v in
                            A.tags_for(run_id, state.expires_at).items()]).raise_for_status()
        role_arn = rec.response["Role"]["Arn"]
        time.sleep(INTER_IAM_S)
        capture(store, "put_role_policy", iam, RoleName=role_name,
                PolicyName="grx-runtime-cred",
                PolicyDocument=json.dumps(
                    execution_policy(account, bucket, prefix, args.region))
                ).raise_for_status()
        time.sleep(INTER_IAM_S)
        print(f"  role: {role_name}")

        # ---- 2. the deployment package --------------------------------------
        state.record(T.Resource(
            kind="s3-object", logical="f58_code_zip", name=prefix,
            service="s3", delete_op="delete_object",
            delete_params={"Bucket": bucket, "Key": prefix},
            ids={"bucket": bucket, "key": prefix, "case": CASE}, delete_priority=30,
            notes="F5-8's runtime code. Harmless if it survives, but it is not free to store."))
        state.write()
        zbytes = build_zip()
        capture(store, "put_object", s3, Bucket=bucket, Key=prefix, Body=zbytes,
                ContentType="application/zip").raise_for_status()
        object_put = True
        print(f"  code: s3://{bucket}/{prefix} ({len(zbytes)} bytes)")

        # IAM is eventually consistent for a brand-new role's trust relationship, and
        # CreateAgentRuntime assumes the role synchronously. This is a WAIT and not a
        # retry-on-any-error: a retry loop would also swallow a genuine trust-policy mistake and
        # spend ten minutes proving the union arm does not work when the defect is one condition
        # key. F1-3's asynchronous-settle trap, in a new place.
        time.sleep(15)

        # ---- 3. the runtime -------------------------------------------------
        state.record(T.Resource(
            kind="agent-runtime", logical="f58_runtime", name=rt_name,
            service="bedrock-agentcore-control", delete_op="delete_agent_runtime",
            delete_params={},   # filled in below: the id does not exist until the call returns
            ids={"runtime_name": rt_name, "case": CASE}, delete_priority=10,
            notes="F5-8's minimal runtime. Delete this first; it holds the role open."))
        state.write()
        rec = capture(
            store, "create_agent_runtime", ac,
            agentRuntimeName=rt_name,
            description=f"GRX {CASE} credential reachability probe",
            agentRuntimeArtifact={"codeConfiguration": {
                "code": {"s3": {"bucket": bucket, "prefix": prefix}},
                "runtime": "PYTHON_3_12",
                "entryPoint": ["main.py"],
            }},
            roleArn=role_arn,
            networkConfiguration={"networkMode": "PUBLIC"},
            protocolConfiguration={"serverProtocol": "HTTP"},
            tags=A.tags_for(run_id, state.expires_at),
        ).raise_for_status()
        runtime_id = rec.response["agentRuntimeId"]
        runtime_arn = rec.response["agentRuntimeArn"]
        # Now the ledger entry can name what teardown needs to delete. Re-recording replaces the
        # entry in place (State is keyed on (kind, logical)), so this is a completion and not a
        # second resource.
        state.record(T.Resource(
            kind="agent-runtime", logical="f58_runtime", name=rt_name,
            service="bedrock-agentcore-control", delete_op="delete_agent_runtime",
            delete_params={"agentRuntimeId": runtime_id},
            ids={"runtime_name": rt_name, "runtime_id": runtime_id, "case": CASE},
            delete_priority=10,
            notes="F5-8's minimal runtime. Delete this first; it holds the role open."))
        state.write()
        print(f"  runtime: {rt_name} ({runtime_id}) CREATING")

        t0 = time.monotonic()
        status = "CREATING"
        failure = ""
        while time.monotonic() - t0 < POLL_TIMEOUT:
            time.sleep(POLL_SECONDS)
            g = capture(store, "get_agent_runtime", ac, agentRuntimeId=runtime_id)
            if not g.ok:
                failure = f"{g.error_code}: {g.error_message}"
                break
            status = (g.response or {}).get("status", "?")
            failure = (g.response or {}).get("failureReason", "") or failure
            if status in TERMINAL:
                break
        elapsed = round(time.monotonic() - t0, 1)
        print(f"  status: {status} after {elapsed}s{('  ' + failure) if failure else ''}")

        # ---- 4. the sessions ------------------------------------------------
        if status == "READY":
            for i in range(args.n):
                inv = capture(store, "invoke_agent_runtime", rt,
                              agentRuntimeArn=runtime_arn,
                              contentType="application/json", accept="application/json",
                              payload=json.dumps({"prompt": "who am i", "trial": i}).encode())
                if not inv.ok:
                    trials.append({"trial": i, "usable": False,
                                   "why": f"{inv.error_code}: {inv.error_message}",
                                   "request_id": inv.request_id})
                    print(f"  session {i}: INVOKE FAILED {inv.error_code}")
                    continue
                body = str((inv.response or {}).get("response") or "")
                identity = _identity_of(body)
                ok, why = _returned_the_execution_role(identity, role_name)
                trials.append({
                    "trial": i, "usable": "sts_http_status" in identity or "error" in identity,
                    "returned_execution_role": ok, "reading": why,
                    "credential_source": identity.get("credential_source"),
                    "sts_http_status": identity.get("sts_http_status"),
                    "channels_probed": identity.get("channels_probed"),
                    "all_aws_env_names": identity.get("all_aws_env_names"),
                    "request_id": inv.request_id,
                    # A distinct session per call is the premise of the denominator, so the id
                    # the service assigned is recorded rather than assumed.
                    "runtime_session_id": inv.headers.get(
                        "x-amzn-bedrock-agentcore-runtime-session-id"),
                })
                print(f"  session {i}: {'EXECUTION ROLE' if ok else 'NOT THE ROLE'} — {why}")
        else:
            print(f"  no session opened: the runtime never reached READY")

    finally:
        # ---- 5. teardown ----------------------------------------------------
        # Every delete is captured, and the ledger entry is dropped only AFTER its delete
        # succeeded. Dropping first would make a failed delete invisible to the tag sweep.
        deleted, failed = [], []
        if runtime_id:
            d = capture(store, "delete_agent_runtime", ac, agentRuntimeId=runtime_id)
            if d.ok:
                state.drop("agent-runtime", "f58_runtime")
                state.write()
                deleted.append(f"agent-runtime/{runtime_id}")
            else:
                failed.append(f"agent-runtime/{runtime_id}: {d.error_code}")
        if role_arn:
            dp = capture(store, "delete_role_policy", iam, RoleName=role_name,
                         PolicyName="grx-runtime-cred")
            time.sleep(INTER_IAM_S)
            dr = capture(store, "delete_role", iam, RoleName=role_name)
            if dp.ok and dr.ok:
                state.drop("iam-role", "f58_runtime_exec")
                state.write()
                deleted.append(f"iam-role/{role_name}")
            else:
                failed.append(f"iam-role/{role_name}: "
                              f"{dp.error_code or ''}/{dr.error_code or ''}")
        if object_put:
            do = capture(store, "delete_object", s3, Bucket=bucket, Key=prefix)
            if do.ok:
                state.drop("s3-object", "f58_code_zip")
                state.write()
                deleted.append(f"s3-object/{prefix}")
            else:
                failed.append(f"s3-object/{prefix}: {do.error_code}")
        residue = {"deleted": deleted, "not_deleted": failed,
                   "back_to_baseline": not failed,
                   "bucket_left_standing": bucket,
                   "why_the_bucket_stays": (
                       "it is shared provisioning for every AgentCore Runtime this project "
                       "creates, it holds nothing after the object above is deleted, and "
                       "re-creating it per run would need s3:CreateBucket in the runner's "
                       "derived policy for no gain")}
        print(f"  teardown: deleted {len(deleted)}"
              f"{(', FAILED ' + str(len(failed))) if failed else ''}")

    # ---- 6. the verdict ----------------------------------------------------
    usable = [t for t in trials if t.get("usable")]
    n_usable = len(usable)
    all_returned_role = bool(usable) and all(t["returned_execution_role"] for t in usable)

    if not usable:
        record = O.not_measured(
            CASE, "no tool session produced a readable identity block",
            status_reached=status if runtime_id else "the runtime was never created",
            trials=trials)
    else:
        obs = P.obs_existence(
            CASE, all_returned_role, n=n_usable,
            reading=("every tool session's sts:GetCallerIdentity returned this runtime's "
                     "execution role" if all_returned_role else
                     "at least one tool session did not return the execution role"),
            credential_sources=sorted({str(t.get("credential_source")) for t in usable}),
            distinct_sessions=len({t.get("runtime_session_id") for t in usable}),
            union_arm="codeConfiguration (S3 zip, PYTHON_3_12) — no container image",
            execution_policy_grants_get_caller_identity=False)
        record = O.evaluate(obs)

    payload = {
        "run_id": run_id,
        "region": args.region,
        "instrument": (
            "One AgentCore Runtime created from the `codeConfiguration` arm of the "
            "`agentRuntimeArtifact` union: a standard-library-only HTTP handler in an S3 zip, "
            "PYTHON_3_12, serverProtocol HTTP, networkMode PUBLIC. Each InvokeAgentRuntime "
            "without a session id opens a new tool session; the handler probes eight credential "
            "channels and then calls sts:GetCallerIdentity with a hand-rolled SigV4 signature."),
        "sessions_requested": args.n,
        "sessions_usable": n_usable,
        "trials": trials,
        "terminal_status": status if runtime_id else None,
        "seconds_to_terminal": elapsed if runtime_id else None,
        "residue": residue,
        "verdict_rule": O.oracle_text(CASE),
        "verdict_reading": (
            "TRUE: the execution role's credentials are reachable from inside a tool session, "
            "which is section 4.4's premise, now from public evidence"
            if all_returned_role else
            "not TRUE: see `trials` for what each session reported and `channels_probed` for "
            "every credential channel that was tried"),
        "what_true_does_not_prove": [
            "that the credentials carry any particular permission — this role could read one S3 "
            "prefix and write logs, and reachability says nothing about grants",
            "that a CONTAINER-based runtime behaves the same way; this measured the "
            "codeConfiguration arm, and the container arm is an inference from the shared microVM "
            "contract rather than an observation",
            "that sts:GetCallerIdentity was authorized — it requires no IAM permission, and the "
            "execution policy attached here deliberately omits it, so the call proves the "
            "credentials exist and STS accepts them, not that a grant allowed it",
        ],
        "why_this_matters_operationally": (
            "Section 4.4 tells a reader not to put UpdateGateway, policy-engine mutation or "
            "interceptor management on an agent's execution role, and the whole force of that "
            "advice is that a jailbroken agent can assume the role and use those grants itself. "
            "The document cited an NDA'd accelerator for the mechanism. This case replaces that "
            "citation with a measurement anybody can repeat."),
        "limitations": [
            "one runtime, one Region, one union arm, three sessions",
            "the channel enumeration is eight mechanisms wide; a ninth channel this project has "
            "not heard of would be invisible to it, which is why every probed channel is recorded "
            "rather than summarised into a boolean",
            "no model was called, so this says nothing about what an agent's own reasoning would "
            "do with the credentials once it had them",
        ],
        "billable_calls": 0,
        "mutations": 0,
        "expiry": state.expires_at,
    }

    P.emit(CASE, record, payload, store)
    if not usable:
        return 2
    if not residue["back_to_baseline"]:
        print("  WARNING: residue did not return to baseline; see results/phase1/"
              f"{CASE}.json -> residue.not_deleted")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
