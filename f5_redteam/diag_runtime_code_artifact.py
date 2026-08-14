"""DIAGNOSTIC (not a registered case): is there an AgentCore Runtime this project can build?

Why this exists
---------------
Three cases have no verdict for one shared reason: this project owns no AgentCore Runtime.
`results/DEPENDENCY-AUDIT-2026-08-13.md` recorded the blocker as an *image* problem —

    an AgentCore Runtime needs a **linux/arm64** container image, and the runner instance is a
    **t3.small / x86_64 with 2 vCPU**. A qemu cross-build on 2 shared vCPU is impractical

— and concluded that a Graviton builder or CodeBuild ARM was the way in. Read against the
pinned service model, that premise is too strong. `agentRuntimeArtifact` is a **union**:

    containerConfiguration  requires ['containerUri']       <- an ECR image
    codeConfiguration       requires ['code','runtime','entryPoint']

The second arm takes an S3 zip, a managed `PYTHON_3_12` runtime and an entry point. AWS calls it
*direct code deployment* and documents it. Its documentation does say

    AgentCore Runtime only supports **arm64** instruction set architecture

but read where that sentence sits: it is the instruction for `uv pip install
--python-platform aarch64-manylinux2014`, i.e. it is about the **wheels** in the package, not
about the package. Code with no compiled dependencies has no wheels to cross-build, and a
handler that satisfies the HTTP service contract needs none — `/invocations` POST and `/ping`
GET on `0.0.0.0:8080` is reachable from `http.server` in the standard library.

So the blocker as recorded may be an artifact of reading one arm of a union. That is worth an
hour to settle, because if the code arm works then the arm64 builder leaves the critical path
for two of the three blocked cases and only F5-7b still needs a container — its sealed oracle is
denominated in an *image pull* ("a VPC-mode runtime without a NAT route fails image pull"), and a
code artifact does not pull an image.

WHAT THIS SCRIPT DECIDES, AND WHAT IT DELIBERATELY DOES NOT
-----------------------------------------------------------
It writes NO verdict and does not touch `results/phase1/`. F5-8's oracle is sealed and its
producer does not exist yet; this script exists to find out whether that producer is worth
writing, and to answer the four questions in the order that stops the earliest:

    1. does `CreateAgentRuntime` ACCEPT a `codeConfiguration` artifact in this account/Region?
    2. does the runtime reach terminal `READY`, or `CREATE_FAILED` with a reason?
    3. does `InvokeAgentRuntime` reach the handler at all?
    4. what does `sts:GetCallerIdentity` return from inside it?

Question 4 is F5-8's oracle almost verbatim, and that is on purpose — a probe that stops at 3
would prove the plumbing and leave the case exactly as blocked as it was. But an answer here is
NOT F5-8: the case wants a ledgered runtime, paced calls, archived evidence with
`x-amzn-requestid`, and an `obs_existence` through the sealed binding. What this can establish is
whether that work has a target.

The handler reports which credential-bearing environment variables EXIST by name, never their
values, and the report is masked through `lib/redact.py` before it is written. The names are the
interesting part anyway: they say which credential mechanism a runtime is given, and that is the
mechanism §4.4 of the document under test is really about.

RESIDUE
-------
Every resource is created by this script and deleted by it in a `finally`, and the report states
what was created and what was deleted so the two can be compared. Nothing is written to the
ledger: `infra/99_teardown.py` deletes what the ledger names, and a diagnostic that registered a
runtime there would make a *failed* probe look like testbed the next teardown is responsible for.
The cost of that choice is that a crash between create and delete leaks a runtime, so the names
carry the run id and the report names them explicitly.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import redact as R       # noqa: E402
import testbed as T      # noqa: E402

REGION = A.MAIN_REGION
POLL_SECONDS = 10
POLL_TIMEOUT = 600          # CREATING -> READY; a code artifact installs nothing, but the
                            # service still provisions, and 10 minutes is well past the
                            # point where "still CREATING" is the finding rather than a wait.

# The handler. Pure standard library on purpose: the moment this imports boto3 it acquires a
# dependency that has to be in the zip, and the whole question is whether a zip with no
# cross-built wheels works. SigV4 is ~40 lines of hmac, which is cheaper than being unable to
# tell a packaging failure from a service refusal.
# The handler, the zip and the execution policy live in `runtime_code_pkg` so that this
# diagnostic and F5-8's producer share ONE program. A reader checks the instrument here and then
# reads a verdict there; two copies would let those diverge invisibly.
from runtime_code_pkg import (                                        # noqa: E402
    HANDLER, build_zip, execution_policy, service_trust)

def main(argv: list[str] | None = None) -> int:      # noqa: C901, PLR0912, PLR0915
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true",
                    help="do NOT delete the runtime; for handing a live ARN to F1-15")
    ap.add_argument("--dry-run", action="store_true")
    # The settle is a parameter because it turned out to be the variable under test. This script
    # succeeded from the laptop with 15 seconds and then failed TWICE from the instance with the
    # same 15, same bucket, same policy document, on `CreateAgentRuntime` reporting
    # "Access denied when trying to retrieve zip file from S3". The instance is in-region, so every
    # call before the sleep returns in a fraction of the time it takes from a laptop over the
    # public internet --- which means the laptop run had substantially more WALL CLOCK between
    # `put_role_policy` and `create_agent_runtime` than the constant suggests. A hardcoded 15 was
    # measuring the caller's latency, not the service's consistency window.
    ap.add_argument("--settle", type=int, default=15,
                    help="seconds between put_role_policy and CreateAgentRuntime, so the new "
                         "role's TRUST policy can propagate before the service assumes it. NOT "
                         "for the zip read: CreateAgentRuntime reads the zip as the CALLER, so a "
                         "403 there is a missing s3:GetObject on the caller and no wait fixes it")
    args = ap.parse_args(argv)

    state = T.State.load()
    run_id = state.run_id
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # AgentRuntime names are word-character only in the pinned model's pattern, so the run id's
    # form matters: lower-cased and stripped of separators rather than passed through.
    short = run_id.lower().replace("-", "").replace("_", "")
    rt_name = f"grx_diag_code_{short}"
    role_name = f"grx-diag-runtime-code-{run_id}"

    fac = A.factory(REGION)
    account = A.account_id(fac)
    R.register_account_id(account)
    bucket = f"grx-runtime-code-{account}-{REGION}"
    prefix = f"diag/{run_id}/deployment_package.zip"

    if args.dry_run:
        print("DIAGNOSTIC dry run — no AWS call")
        print(f"  would create IAM role      {role_name}")
        print(f"  would create S3 bucket     {bucket} (if absent) and put {prefix}")
        print(f"  would create AgentRuntime  {rt_name} (codeConfiguration, PYTHON_3_12, HTTP)")
        print(f"  would invoke it, then DELETE the runtime, the object and the role")
        print(f"  zip: {len(build_zip())} bytes, 1 entry (main.py, 0o644)")
        return 0

    print(f"DIAGNOSTIC runtime code artifact — run_id={run_id}, region={REGION}")
    print("  no verdict is written; results/phase1 is not touched\n")

    iam = fac.iam()
    s3 = fac.client("s3")
    ac = fac.agentcore_control()
    rt = fac.agentcore()

    # NO `lim.wait()` anywhere below, deliberately. Every operation this script calls is
    # called ONCE, and not one of them has a `RATE_LIMITS` entry — so a `wait` would return
    # 0.0 and read in the source as pacing that is not happening. That exact illusion is what
    # DEV-P4-33 was: fourteen `lim.wait()` names across ten scripts that named operations the
    # table did not know. The one loop here, the `GetAgentRuntime` poll, paces itself with
    # POLL_SECONDS, which is a real interval rather than a lookup that misses.

    report: dict[str, Any] = {
        "diagnostic": "runtime-code-artifact",
        "question": "does CreateAgentRuntime accept a container-free codeConfiguration here",
        "run_id": run_id, "region": REGION, "collected_at": tag,
        "sdk": A.sdk_versions(),
        "created": [], "deleted": [], "steps": [],
    }

    # The parameter is `_label`, not `name`: a `step("iam_role", name=role_name)` call binds
    # `name` twice and raises TypeError from inside the `finally`, which is where the residue
    # cleanup lives. That is the worst place in this script for an avoidable crash --- it
    # deleted the role, then died before deleting the object and writing the report.
    def step(_label: str, **kw: Any) -> None:
        report["steps"].append({"step": _label, **kw})
        print(f"  {_label}: " + ", ".join(f"{k}={v}" for k, v in kw.items() if k != "detail"))

    role_arn = None
    runtime_id = None
    made_bucket = False
    try:
        # ---- 1. the code bucket ------------------------------------------
        try:
            s3.head_bucket(Bucket=bucket)
            step("s3_bucket", existed=True, bucket=R.mask_text(bucket))
        except Exception:                                        # noqa: BLE001
            s3.create_bucket(Bucket=bucket)      # us-east-1 takes no LocationConstraint
            made_bucket = True
            report["created"].append(f"s3-bucket/{bucket}")
            step("s3_bucket", created=True, bucket=R.mask_text(bucket))

        zbytes = build_zip()
        s3.put_object(Bucket=bucket, Key=prefix, Body=zbytes,
                      ExpectedBucketOwner=account)
        report["created"].append(f"s3-object/{prefix}")
        step("upload", key=prefix, bytes=len(zbytes))

        # ---- 2. the execution role ---------------------------------------
        # A NEW role, deliberately. `grx-runtime-exec-<run>` already exists and looks like the
        # obvious candidate, but its inline policy set IS F5-1's published oracle: that case
        # asserts the exact baseline at startup and `infra/01_iam.py --ensure` refuses on
        # drift. Adding an S3 read to it to satisfy a diagnostic would silently change the
        # premise of a case that is already published.
        role_arn = iam.create_role(
            RoleName=role_name, AssumeRolePolicyDocument=json.dumps(service_trust(account)),
            Description="GRX diagnostic: AgentCore Runtime code-artifact probe",
            Tags=[{"Key": k, "Value": v} for k, v in
                  A.tags_for(run_id, state.expires_at).items()],
        )["Role"]["Arn"]
        report["created"].append(f"iam-role/{role_name}")
        iam.put_role_policy(RoleName=role_name, PolicyName="grx-diag-runtime-code",
                            PolicyDocument=json.dumps(
                                execution_policy(account, bucket, prefix, REGION)))
        step("iam_role", name=role_name, arn=R.mask_text(role_arn))

        # IAM is eventually consistent for a brand-new role's trust: CreateAgentRuntime can
        # fail to assume a role that `get_role` already returns. This wait is the F1-3
        # asynchronous-settle trap in a new place, so it is a wait and not a retry-on-any-error
        # — a retry loop would also swallow a genuine trust-policy mistake.
        #
        # RETRACTED, 2026-08-14. This paragraph used to claim that TWO things settle here: the trust
        # policy, and then the role's INLINE policy, the latter being what the "Access denied when
        # trying to retrieve zip file from S3" message reports. That was wrong, and it was wrong in
        # the direction that makes a wait look like a fix.
        #
        # The real cause of that message is not propagation of anything. `CreateAgentRuntime`
        # verifies that **the CALLER** can read the deployment zip, not just the execution role it
        # is handed --- so the missing grant was `s3:GetObject` on the code bucket for
        # `grx-runner-ec2`, and no value of `--settle` would ever have supplied it.
        # `runner/iam_policy.py:560-571` records how that was isolated: the same role and the same
        # uploaded zip that the instance was refused for were accepted immediately when
        # `CreateAgentRuntime` was called by an administrator, which leaves the caller as the only
        # variable. The same source explicitly rules the IAM propagation delay OUT as a cause.
        #
        # The paragraph is retracted in place rather than deleted, because the failure mode it
        # illustrates is worth keeping: a plausible eventual-consistency story attached to a real
        # symptom, which reads as an explanation, survives review, and quietly converts a missing
        # permission into a timing knob. The wait below is kept for the FIRST reason only --- the
        # trust policy genuinely does have to propagate before the service can assume the role ---
        # and it is a wait rather than a retry-on-any-error so that a genuine trust-policy mistake
        # surfaces instead of being swallowed (F1-3's asynchronous-settle trap, in a new place).
        report["settle_seconds"] = args.settle
        time.sleep(args.settle)

        # ---- 3. the runtime ----------------------------------------------
        artifact = {"codeConfiguration": {
            "code": {"s3": {"bucket": bucket, "prefix": prefix}},
            "runtime": "PYTHON_3_12",
            "entryPoint": ["main.py"],
        }}
        try:
            resp = ac.create_agent_runtime(
                agentRuntimeName=rt_name,
                agentRuntimeArtifact=artifact,
                roleArn=role_arn,
                networkConfiguration={"networkMode": "PUBLIC"},
                protocolConfiguration={"serverProtocol": "HTTP"},
                description="GRX diagnostic: container-free code artifact probe",
            )
        except Exception as e:                                   # noqa: BLE001
            report["answer_q1_create_accepted"] = False
            report["create_error"] = R.mask_text(f"{type(e).__name__}: {e}")
            step("create_agent_runtime", accepted=False,
                 error=type(e).__name__)
            raise SystemExit(0)

        runtime_id = resp["agentRuntimeId"]
        runtime_arn = resp["agentRuntimeArn"]
        report["created"].append(f"agent-runtime/{runtime_id}")
        report["answer_q1_create_accepted"] = True
        report["runtime_arn"] = R.mask_text(runtime_arn)
        report["runtime_version"] = resp.get("agentRuntimeVersion")
        step("create_agent_runtime", accepted=True, id=runtime_id,
             status=resp.get("status"))

        # ---- 4. poll to terminal ------------------------------------------
        t0 = time.time()
        status, failure = resp.get("status"), None
        while time.time() - t0 < POLL_TIMEOUT:
            d = ac.get_agent_runtime(agentRuntimeId=runtime_id)
            status = d.get("status")
            failure = d.get("failureReason")
            if status in ("READY", "CREATE_FAILED"):
                break
            time.sleep(POLL_SECONDS)
        report["answer_q2_terminal_status"] = status
        report["failure_reason"] = R.mask_text(failure) if failure else None
        report["seconds_to_terminal"] = round(time.time() - t0, 1)
        step("poll", status=status, seconds=report["seconds_to_terminal"],
             failure=failure or "-")

        # ---- 5. invoke ----------------------------------------------------
        if status == "READY":
            try:
                inv = rt.invoke_agent_runtime(
                    agentRuntimeArn=runtime_arn,
                    contentType="application/json",
                    accept="application/json",
                    payload=json.dumps({"prompt": "who am i"}).encode(),
                )
                raw = inv["response"].read().decode("utf-8", "replace")
                report["answer_q3_invoke_reached_handler"] = True
                report["invoke_status_code"] = inv.get("statusCode")
                # The request id is what makes this quotable later. F5-8's evidence has to be
                # traceable back to a specific call, and `x-amzn-requestid` is the only handle
                # on it that survives once the runtime is deleted.
                report["invoke_request_id"] = (inv.get("ResponseMetadata") or {}).get("RequestId")
                report["invoke_response_headers"] = {
                    k: v for k, v in ((inv.get("ResponseMetadata") or {})
                                      .get("HTTPHeaders") or {}).items()
                    if k.lower().startswith("x-amzn-") or k.lower() == "content-type"}
                try:
                    report["answer_q4_identity"] = R.mask(json.loads(raw))
                except json.JSONDecodeError:
                    report["answer_q4_identity_raw"] = R.mask_text(raw[:2000])
                step("invoke", ok=True, status=inv.get("statusCode"),
                     bytes=len(raw))
            except Exception as e:                               # noqa: BLE001
                report["answer_q3_invoke_reached_handler"] = False
                report["invoke_error"] = R.mask_text(f"{type(e).__name__}: {e}")
                step("invoke", ok=False, error=type(e).__name__)
        else:
            report["answer_q3_invoke_reached_handler"] = None
            step("invoke", skipped=f"status was {status}")

    finally:
        # ---- 6. residue ---------------------------------------------------
        if runtime_id and not args.keep:
            try:
                ac.delete_agent_runtime(agentRuntimeId=runtime_id)
                report["deleted"].append(f"agent-runtime/{runtime_id}")
                step("delete_runtime", id=runtime_id)
            except Exception as e:                               # noqa: BLE001
                step("delete_runtime", FAILED=type(e).__name__)
        elif runtime_id:
            report["kept_deliberately"] = f"agent-runtime/{runtime_id}"
            step("delete_runtime", kept="--keep was passed")
        # `--keep` has to keep the role and the code object too, not just the runtime. The
        # first version deleted them anyway, which left a READY runtime whose execution role
        # no longer existed --- so the one thing `--keep` is for, handing a working ARN to
        # F1-15, was exactly what it could not deliver. A runtime resolves its credentials
        # per session from that role, and re-reads the S3 object when it restarts, so keeping
        # the runtime while deleting both is keeping the name and discarding the thing.
        if role_arn and not args.keep:
            for fn, kw, label in (
                    (iam.delete_role_policy,
                     {"RoleName": role_name, "PolicyName": "grx-diag-runtime-code"}, "policy"),
                    (iam.delete_role, {"RoleName": role_name}, "role")):
                try:
                    fn(**kw)
                except Exception as e:                           # noqa: BLE001
                    step("delete_role", part=label, FAILED=type(e).__name__)
            report["deleted"].append(f"iam-role/{role_name}")
            step("delete_role", name=role_name)
        elif role_arn:
            report.setdefault("kept_deliberately_also", []).append(f"iam-role/{role_name}")
            step("delete_role", kept="--keep was passed")
        if not args.keep:
            try:
                s3.delete_object(Bucket=bucket, Key=prefix)
                report["deleted"].append(f"s3-object/{prefix}")
            except Exception as e:                               # noqa: BLE001
                step("delete_object", FAILED=type(e).__name__)
        else:
            report.setdefault("kept_deliberately_also", []).append(f"s3-object/{prefix}")
            step("delete_object", kept="--keep was passed")
        if made_bucket:
            # The bucket is left standing when this script created it: a code bucket is
            # reusable infrastructure for the F5-8/F1-15 producers this probe exists to
            # justify, and deleting it would mean re-creating it in ten minutes. It is named
            # and reported so the choice is visible rather than an oversight.
            report["left_standing_deliberately"] = f"s3-bucket/{bucket}"

        out = ROOT / "results" / f"DIAG-runtime-code-artifact-{tag}.json"
        out.write_text(json.dumps(R.mask(report), indent=2, sort_keys=True, default=str) + "\n")
        print(f"\n  report: {out.relative_to(ROOT)}")
        print(f"  created {len(report['created'])}, deleted {len(report['deleted'])}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
