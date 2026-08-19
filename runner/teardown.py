#!/usr/bin/env python3
"""Remove everything `runner/provision.py` created. One command, and it says what it did.

Why this file exists as code rather than as a paragraph in a README
------------------------------------------------------------------
A runner costs about $17/month whether or not anything is running on it, and a role holding
`iam:PutRolePolicy` on `grx-*` is a standing privilege. Both should end when the work does, and a
teardown that is a list of console clicks is a teardown that does not happen.

Order matters and is the reverse of creation: the instance first (it is what holds the credential),
then the instance profile and role, then the security group, and the bucket LAST and only when
explicitly asked. `--keep-bucket` is the default, because the bucket holds the evidence a run
produced and deleting it silently would destroy the audit archive this project is built on. Use
`--delete-bucket` when the output has been pulled and merged.

Idempotent: every step tolerates the thing already being gone, so a re-run after a partial
teardown finishes the job rather than raising on the first missing resource.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import boto3
import botocore

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runner"))
import provision as PV           # noqa: E402


def _gone(exc: Exception, *codes: str) -> bool:
    if not isinstance(exc, botocore.exceptions.ClientError):
        return False
    return exc.response["Error"]["Code"] in codes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--delete-bucket", action="store_true",
                    help="also empty and delete the S3 bucket (it holds the evidence archive)")
    ap.add_argument("--stop-only", action="store_true",
                    help="stop the instance and keep everything; ~$1.60/month for the volume")
    args = ap.parse_args()

    if not PV.STATE_PATH.is_file():
        raise SystemExit(f"{PV.STATE_PATH.relative_to(ROOT)} is missing; nothing recorded to "
                         "tear down. If an instance exists, it is tagged Name="
                         f"{PV.INSTANCE_TAG}.")
    st = json.loads(PV.STATE_PATH.read_text(encoding="utf-8"))
    sess = boto3.Session(region_name=st["region"])
    ec2, iam, s3 = (sess.client(n) for n in ("ec2", "iam", "s3"))
    did: list[str] = []

    if args.stop_only:
        ec2.stop_instances(InstanceIds=[st["instance_id"]])
        print(f"stopped {st['instance_id']} — the root volume still bills at ~$1.60/month; "
              "runner/provision.py starts it again")
        return 0

    # 1. The instance. Waited on, not fired and forgotten: the security group cannot be deleted
    # while an ENI still references it, and "DependencyViolation" three steps later is a worse
    # error than a wait here (feedback_cryptic_error_is_missing_guard).
    try:
        ec2.terminate_instances(InstanceIds=[st["instance_id"]])
        print(f"terminating {st['instance_id']} …")
        ec2.get_waiter("instance_terminated").wait(
            InstanceIds=[st["instance_id"]],
            WaiterConfig={"Delay": 10, "MaxAttempts": 40})
        did.append(f"instance {st['instance_id']} terminated")
    except botocore.exceptions.ClientError as exc:
        if not _gone(exc, "InvalidInstanceID.NotFound"):
            raise
        did.append(f"instance {st['instance_id']} already gone")

    # 2. Instance profile, then role. The role cannot be deleted while it is in a profile or has
    # policies attached, so both are unwound explicitly rather than relying on cascade.
    try:
        iam.remove_role_from_instance_profile(InstanceProfileName=PV.PROFILE_NAME,
                                             RoleName=PV.ROLE_NAME)
    except botocore.exceptions.ClientError as exc:
        if not _gone(exc, "NoSuchEntity"):
            raise
    for fn, kw in ((iam.delete_instance_profile, {"InstanceProfileName": PV.PROFILE_NAME}),):
        try:
            fn(**kw)
            did.append(f"instance profile {PV.PROFILE_NAME} deleted")
        except botocore.exceptions.ClientError as exc:
            if not _gone(exc, "NoSuchEntity"):
                raise
    try:
        for name in iam.list_role_policies(RoleName=PV.ROLE_NAME)["PolicyNames"]:
            iam.delete_role_policy(RoleName=PV.ROLE_NAME, PolicyName=name)
        for pol in iam.list_attached_role_policies(RoleName=PV.ROLE_NAME)["AttachedPolicies"]:
            iam.detach_role_policy(RoleName=PV.ROLE_NAME, PolicyArn=pol["PolicyArn"])
        iam.delete_role(RoleName=PV.ROLE_NAME)
        did.append(f"role {PV.ROLE_NAME} deleted (this is the privilege revocation)")
    except botocore.exceptions.ClientError as exc:
        if not _gone(exc, "NoSuchEntity"):
            raise
        did.append(f"role {PV.ROLE_NAME} already gone")

    # 3. Security group. The ENI can take a little while to release after termination.
    for attempt in range(12):
        try:
            ec2.delete_security_group(GroupId=st["security_group_id"])
            did.append(f"security group {PV.SG_NAME} deleted")
            break
        except botocore.exceptions.ClientError as exc:
            if _gone(exc, "InvalidGroup.NotFound"):
                did.append(f"security group {PV.SG_NAME} already gone")
                break
            if "DependencyViolation" not in str(exc) or attempt == 11:
                raise
            time.sleep(5)

    # 4. The bucket, only on request.
    #
    # The bucket NAME is never printed. It lives in `runner/.state/`, which is gitignored
    # precisely because a resolved infrastructure id is a redaction target, and printing it puts
    # the same string into a terminal transcript and — the moment anyone redirects stdout — into a
    # `session-logs/*.log` file that is not gitignored at all. That is not hypothetical: on
    # 2026-08-20, when `check_redaction.py` stopped selecting files by extension,
    # `session-logs/runner-teardown-20260819.log` was one of the two files it convicted, on the
    # bucket name this line used to print. There is exactly one runner bucket and its name is
    # derivable from the state file, so the name carries no information the operator lacks —
    # it only carries it somewhere it should not go (`feedback_fix_producer_not_janitor`).
    if args.delete_bucket:
        n = 0
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=st["bucket"]):
            objs = [{"Key": o["Key"], "VersionId": o["VersionId"]}
                    for k in ("Versions", "DeleteMarkers") for o in page.get(k, [])]
            for i in range(0, len(objs), 1000):
                s3.delete_objects(Bucket=st["bucket"], Delete={"Objects": objs[i:i + 1000]})
                n += len(objs[i:i + 1000])
        s3.delete_bucket(Bucket=st["bucket"])
        did.append(f"runner bucket deleted ({n} object versions) — name deliberately not "
                   f"printed; `aws s3 ls` lists it")
    else:
        did.append("runner bucket KEPT — it holds the evidence archive; re-run with "
                   "--delete-bucket once the output is merged. Name deliberately not "
                   "printed; `aws s3 ls` lists it")

    PV.STATE_PATH.unlink(missing_ok=True)
    print("\n".join(f"  {line}" for line in did))
    print("\nrunner cost after this: $0 for compute" + ("" if args.delete_bucket else
          ", ~$0.02/month for the retained bucket (90-day expiry is already set)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
