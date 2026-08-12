#!/usr/bin/env python3
"""Provision the EC2 runner: an instance that can execute the remaining cases unattended.

Why an instance at all
----------------------
The laptop closing ends a run. Several remaining cases are wall-clock bound rather than
compute bound — a replicate that has to happen the next day, a `--compare` read that is date
gated to 2026-08-18 and 2026-09-10 — and those cannot be "run faster", only "run while nobody is
watching". That is the whole benefit, and it is worth stating plainly because the OTHER remaining
blockers are not helped at all: F5-8 and F5-7b need a minimal AgentCore Runtime to exist, F5-3a
needs an Organizations child OU, and F5-9 is gated on an account-level setting. An instance does
not unblock any of those.

Two things deliberately stay on the laptop:

  * **Latency measurement.** F6's numbers were taken from one network position. Re-taking any of
    them from inside a VPC would produce a different number for a different question, and a mixed
    corpus would be worse than either. `runner/README.md` records this as a non-goal.
  * **Publication.** The instance holds no GitHub credential. It syncs `results/`, `state.json`
    and `evidence/` to one S3 bucket; the redaction gate and the full suite run here, and the
    Git Data API push happens from here. Nothing leaves the account without passing the gate on a
    machine that has the gate.

Design, and what each choice buys
---------------------------------
  * **No SSH, no inbound rule at all.** Access is SSM Session Manager, which dials out. The
    security group has zero ingress permissions and egress on 443 only.
  * **IMDSv2 required, hop limit 1.** The instance role is the credential a stray SSRF would want.
  * **Encrypted gp3 root volume**, because the evidence tree lands on it.
  * **A derived, prefix-scoped instance policy** — see `runner/iam_policy.py`. `iam:PassRole` and
    every IAM write are bound to `grx-*`.
  * **Idempotent.** Every step checks for what it would create and reuses it, so this script is
    safe to re-run after a partial failure. It prints what it found versus what it made.

Cost, disclosed rather than assumed: a `t3.small` in us-east-1 is $0.0208/hour on demand, so
about **$15.2/month** running continuously, plus **$1.60/month** for the 20 GiB gp3 root volume,
plus S3 at $0.023/GB-month for whatever is synced (the evidence tree is ~30 MB masked, so
cents). Call it **$17/month** while it is up, and nothing after `runner/teardown.py`. The
instance type is a constant below; the workload is API-bound, so more vCPU would not make it
faster.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from pathlib import Path

import botocore

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runner"))
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A           # noqa: E402
import iam_policy as IP          # noqa: E402

REGION = "us-east-1"
INSTANCE_TYPE = "t3.small"
VOLUME_GIB = 20
ROLE_NAME = "grx-runner-ec2"
PROFILE_NAME = "grx-runner-ec2"
SG_NAME = "grx-runner-sg"
INSTANCE_TAG = "grx-validation-runner"

# The bucket is identified by this prefix plus these tags, never by a name derived from the
# account — see `find_bucket()` for the measurement that retired the derivation. The tags are the
# same pair put on the instance and its volumes, so one query describes the whole fleet.
BUCKET_PREFIX = "grx-validation-runner-"
BUCKET_TAGS = [{"Key": "Project", "Value": "grx-validation"},
               {"Key": "ManagedBy", "Value": "runner/provision.py"}]
AL2023_SSM_PARAM = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
SSM_MANAGED_POLICY = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"

# Where the runner's own ids are recorded. Gitignored: an instance id is not a redaction target
# but a subnet, security-group and VPC id are (`check_redaction.py` PATTERNS
# `vpc-or-subnet-id`), and a file that has to be waived by the gate on every run is a file that
# trains a reader to waive things.
STATE_PATH = ROOT / "runner" / ".state" / "runner.json"

TRUST = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow",
                   "Principal": {"Service": "ec2.amazonaws.com"},
                   "Action": "sts:AssumeRole"}],
}


def find_bucket(s3) -> str | None:
    """Our bucket, found by PREFIX plus TAGS rather than by recomputing its name.

    This replaces `bucket_name(account_id) = PREFIX + sha256(account_id)[:16]`, whose docstring
    claimed the digest "is not reversible to the twelve digits". **That claim is false, and the
    margin is not close.** An AWS account ID is 12 decimal digits, so the preimage space is 10^12
    — about 2^40. Measured on this laptop with the exact expression that derivation used
    (`hashlib.sha256(...).hexdigest()[:16]`, CPython 3.12.12): **2,874,794 candidates per second
    on one core**, so exhausting the whole space costs **4.0 days single-core, 12 hours on 8
    cores**, and roughly **100 seconds** on one consumer GPU at a published hashcat SHA-256 rate
    of 10 GH/s. And the answer is unambiguous when it arrives: for a given 64-bit digest the
    expected number of *other* 12-digit preimages is 10^12 / 2^64 = 5.4e-8, so a hit is
    effectively the account ID itself.

    So the old name was not a hash of the account in any protective sense — it was an *encoding*
    of it, and publishing the name published the account. The bucket namespace being global was
    the right thing to worry about; a fast digest over a 2^40 space was the wrong answer to it.

    A random suffix carries **no** information about the account, which is what the original
    docstring wanted to be true. The cost is that the name can no longer be recomputed, so
    idempotence needs a different mechanism: discovery. Prefix alone is not enough (the namespace
    is global, so another account could hold `grx-validation-runner-anything`), and `list_buckets`
    only ever returns buckets in the caller's own account — so prefix ∧ own-account ∧ our tags
    identifies ours without any derivable name. The tags are the same ones the instance and its
    volumes carry, so the fleet is tagged one way.

    See DEV-P4-25. `feedback_prose_is_not_verified`: the false claim lived in a docstring for as
    long as nobody put a number on it.
    """
    for b in s3.list_buckets()["Buckets"]:
        if not b["Name"].startswith(BUCKET_PREFIX):
            continue
        try:
            tags = {t["Key"]: t["Value"]
                    for t in s3.get_bucket_tagging(Bucket=b["Name"])["TagSet"]}
        except botocore.exceptions.ClientError as exc:
            # An untagged or unreadable bucket is not ours to claim. `NoSuchTagSet` is the
            # ordinary case for a bucket someone created by hand; the other two mean we cannot
            # tell, and "cannot tell" must not resolve to "yes".
            if exc.response["Error"]["Code"] in (
                    "NoSuchTagSet", "AccessDenied", "PermanentRedirect", "NoSuchBucket"):
                continue
            raise
        if all(tags.get(t["Key"]) == t["Value"] for t in BUCKET_TAGS):
            return b["Name"]
    return None


def _log(made: bool, what: str, detail: str = "") -> None:
    print(f"  {'created ' if made else 'reusing '} {what}{(' ' + detail) if detail else ''}")


def ensure_bucket(s3) -> str:
    if found := find_bucket(s3):
        _log(False, f"s3://{BUCKET_PREFIX}<suffix>")
        return found
    # `secrets`, not `random`: this only has to be unguessable, but a name that a reader can
    # regenerate from a seed is a name that carries information again.
    name = BUCKET_PREFIX + secrets.token_hex(8)
    # us-east-1 is the one Region where CreateBucketConfiguration must be omitted.
    s3.create_bucket(Bucket=name)
    # Tagged FIRST after creation, because the tags are how the next run finds this bucket. A
    # bucket created and left untagged is a bucket the next `provision.py` cannot see, and it
    # would create a second one beside it — silently, since both match the prefix.
    s3.put_bucket_tagging(Bucket=name, Tagging={"TagSet": BUCKET_TAGS})
    s3.put_public_access_block(
        Bucket=name,
        PublicAccessBlockConfiguration={"BlockPublicAcls": True, "IgnorePublicAcls": True,
                                        "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_encryption(
        Bucket=name,
        ServerSideEncryptionConfiguration={"Rules": [
            {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
             "BucketKeyEnabled": True}]})
    s3.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    # The evidence tree is the audit archive and the code tarball is reproducible, so nothing here
    # is worth keeping forever; 90 days outlives any run and bounds the bill.
    s3.put_bucket_lifecycle_configuration(
        Bucket=name,
        LifecycleConfiguration={"Rules": [
            {"ID": "expire-90d", "Status": "Enabled", "Filter": {"Prefix": ""},
             "Expiration": {"Days": 90},
             "NoncurrentVersionExpiration": {"NoncurrentDays": 30},
             "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 3}}]})
    # The suffix is masked in output for the same reason the README masks it: a bucket name that
    # reaches a terminal reaches a session log, and a session log is pushed. The real name is in
    # the gitignored `runner/.state/runner.json`, which is where every other resolved id lives.
    _log(True, f"s3://{BUCKET_PREFIX}<suffix>", "(private, SSE-S3, versioned, 90-day expiry, "
                                               "tagged for discovery)")
    return name


def ensure_role(iam, account_id: str, bucket: str) -> str:
    doc = IP.document(account_id, REGION, bucket)
    try:
        iam.get_role(RoleName=ROLE_NAME)
        made = False
    except botocore.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(TRUST),
            Description="grx-validation unattended runner; policy derived from evidence/",
            MaxSessionDuration=3600,
            Tags=[{"Key": "Project", "Value": "grx-validation"}])
        made = True
    # Written every run, not only on create: the derivation is the source of truth, so a new
    # measured operation reaches the live role by re-running this script.
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="grx-derived",
                        PolicyDocument=json.dumps(doc, separators=(",", ":")))
    iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=SSM_MANAGED_POLICY)
    _log(made, f"role {ROLE_NAME}",
         f"({sum(len(s['Action']) for s in doc['Statement'])} actions, "
         f"{len(doc['Statement'])} statements)")

    try:
        iam.get_instance_profile(InstanceProfileName=PROFILE_NAME)
        made = False
    except botocore.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_instance_profile(InstanceProfileName=PROFILE_NAME)
        made = True
    prof = iam.get_instance_profile(InstanceProfileName=PROFILE_NAME)["InstanceProfile"]
    if not any(r["RoleName"] == ROLE_NAME for r in prof["Roles"]):
        iam.add_role_to_instance_profile(InstanceProfileName=PROFILE_NAME, RoleName=ROLE_NAME)
    _log(made, f"instance profile {PROFILE_NAME}")
    return prof["Arn"]


def ensure_sg(ec2, vpc_id: str) -> str:
    found = ec2.describe_security_groups(Filters=[
        {"Name": "group-name", "Values": [SG_NAME]},
        {"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]
    if found:
        sg_id = found[0]["GroupId"]
        made = False
    else:
        sg_id = ec2.create_security_group(
            GroupName=SG_NAME, VpcId=vpc_id,
            Description="grx-validation runner: no ingress, egress 443 only (SSM dials out)",
        )["GroupId"]
        # The default egress rule allows everything; replace it with 443 so the instance can
        # reach AWS APIs, the AL2023 repos and PyPI and nothing else.
        ec2.revoke_security_group_egress(
            GroupId=sg_id, IpPermissions=[{"IpProtocol": "-1",
                                           "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
        ec2.authorize_security_group_egress(
            GroupId=sg_id, IpPermissions=[{
                "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                "IpRanges": [{"CidrIp": "0.0.0.0/0",
                              "Description": "SSM, AWS APIs, AL2023 repos, PyPI"}]}])
        made = True
    ingress = ec2.describe_security_groups(GroupIds=[sg_id])["SecurityGroups"][0]["IpPermissions"]
    if ingress:
        raise SystemExit(f"{SG_NAME} has {len(ingress)} ingress rule(s); this runner takes none")
    _log(made, f"security group {SG_NAME}", "(0 ingress, egress tcp/443)")
    return sg_id


def find_instance(ec2) -> dict | None:
    res = ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [INSTANCE_TAG]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
    ])["Reservations"]
    for r in res:
        for i in r["Instances"]:
            return i
    return None


def ensure_instance_profile(ec2, iid: str) -> str | None:
    """Assert the instance carries the DERIVED profile, and re-attach it if it does not.

    This is not defensive coding, it is a measured fact about this account. An SSM State Manager
    association named `SystemAssociationForManagingInstances` runs the `AWS-AttachIAMToInstance`
    document at `rate(1 hour)` against `InstanceIds: ['*']`, and CloudTrail shows what it does:
    `DisassociateIamInstanceProfile` immediately followed by `AssociateIamInstanceProfile` with
    `AmazonSSMRoleForInstancesQuickSetup`, on every instance in the Region, at :01 every hour
    (observed 05:01, 06:01, 07:01 on 2026-08-12). It replaces unconditionally — it does not skip an
    instance that already has a profile — so the least-privilege role this script derives survives
    **at most one hour** and then silently stops being the role the runner runs as.

    Three consequences, in increasing order of how much they matter:

    1. It looks like an S3 outage. The symptom was `aws s3 cp` failing with `403 Forbidden` on a
       bucket whose policy plainly grants `s3:GetObject` to `grx-runner-ec2` — because the caller
       was not `grx-runner-ec2`. A cryptic error is a missing guard
       (`feedback_cryptic_error_is_missing_guard`), and the guard that was missing is this one: the
       script reused a running instance without ever asking what identity it now had.
    2. The documented design was not the deployed one. `runner/README.md` describes a policy
       derived from `evidence/` and scoped to `grx-*`; for most of every hour that policy was
       attached to a profile nothing used. A config nothing deploys does not exist
       (`feedback_no_deploy_path_no_component`), and this is its mirror image — a config that
       deploys and is then overwritten.
    3. **It is a measurement-integrity problem, not just a privilege one.** The replacing role
       carries `AmazonSSMFullAccess` plus an inline policy from an unrelated project that grants
       `bedrock-agentcore:*` and `bedrock-agentcore-control:*` on `*`. Those are the resources
       under test — the READY gateways, the DRAFT guardrails, the policy engines, the `nopolicy`
       baseline. A machine that measures AgentCore should not be able to reconfigure AgentCore,
       and for most of every hour this one could. The "never touch" list was being enforced by
       discipline rather than by IAM.

    Repair rather than refuse, because every S3 access the instance makes is initiated by a laptop
    command (`sync.py push*`, `rebootstrap`, `run.py --detach`), so checking here makes the runner
    self-healing on the only path that matters. What this does NOT do is touch the association: it
    targets every instance in the account and three other projects' instances depend on it, so
    re-scoping it is a decision for whoever owns the account, exactly like the account-wide
    Transaction Search setting `lib/testbed.py` asserts and never enables.

    Returns a message when it had to repair, `None` when the profile was already correct — so the
    caller can print the repair rather than have it happen silently. A silent repair would hide how
    often the clobber happens, which is the number that decides whether presigned transfers are
    needed instead.
    """
    assoc = ec2.describe_iam_instance_profile_associations(
        Filters=[{"Name": "instance-id", "Values": [iid]}])["IamInstanceProfileAssociations"]
    live = [a for a in assoc if a["State"] in ("associating", "associated")]
    current = live[0]["IamInstanceProfile"]["Arn"].split("/")[-1] if live else None
    if current == PROFILE_NAME:
        return None
    # Attached by NAME, not by ARN: `associate_iam_instance_profile` accepts either, and the name
    # means this path needs no IAM client and therefore no IAM read permission on the laptop side.
    if live:
        ec2.replace_iam_instance_profile_association(
            AssociationId=live[0]["AssociationId"],
            IamInstanceProfile={"Name": PROFILE_NAME})
        return (f"instance profile was {current!r}, not {PROFILE_NAME!r} — re-attached. "
                f"The hourly AWS-AttachIAMToInstance association had replaced it; see "
                f"ensure_instance_profile() and DEV-P4-26.")
    ec2.associate_iam_instance_profile(
        InstanceId=iid, IamInstanceProfile={"Name": PROFILE_NAME})
    return (f"instance had NO instance profile — attached {PROFILE_NAME!r}. "
            f"See ensure_instance_profile() and DEV-P4-26.")


def render_bootstrap(bucket: str) -> str:
    """`runner/bootstrap.sh` with its two placeholders filled in.

    Separate from `launch` because user data runs ONCE, at first boot, and the script has been
    edited since this instance booted more than once already. An edit to bootstrap.sh that only
    reaches the next instance is an edit that does not exist on the machine actually running the
    work (feedback_embedded_asset_staleness), so `runner/sync.py rebootstrap` renders the same text
    from the same function and re-runs it in place. One renderer, so the two paths cannot drift.
    """
    text = (ROOT / "runner" / "bootstrap.sh").read_text(encoding="utf-8")
    out = text.replace("@@BUCKET@@", bucket).replace("@@REGION@@", REGION)
    if "@@" in out:
        raise SystemExit(f"bootstrap.sh has an unsubstituted placeholder: "
                         f"{[ln for ln in out.splitlines() if '@@' in ln]}")
    return out


def launch(ec2, ssm, profile_arn: str, sg_id: str, subnet_id: str, bucket: str) -> str:
    ami = ssm.get_parameter(Name=AL2023_SSM_PARAM)["Parameter"]["Value"]
    user_data = render_bootstrap(bucket)
    out = ec2.run_instances(
        ImageId=ami, InstanceType=INSTANCE_TYPE, MinCount=1, MaxCount=1,
        SubnetId=subnet_id, SecurityGroupIds=[sg_id],
        IamInstanceProfile={"Arn": profile_arn},
        UserData=user_data,
        InstanceInitiatedShutdownBehavior="stop",
        MetadataOptions={"HttpTokens": "required", "HttpPutResponseHopLimit": 1,
                         "HttpEndpoint": "enabled"},
        BlockDeviceMappings=[{"DeviceName": "/dev/xvda",
                              "Ebs": {"VolumeSize": VOLUME_GIB, "VolumeType": "gp3",
                                      "Encrypted": True, "DeleteOnTermination": True}}],
        TagSpecifications=[{"ResourceType": rt,
                            "Tags": [{"Key": "Name", "Value": INSTANCE_TAG},
                                     {"Key": "Project", "Value": "grx-validation"},
                                     {"Key": "ManagedBy", "Value": "runner/provision.py"}]}
                           for rt in ("instance", "volume")],
    )
    return out["Instances"][0]["InstanceId"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve everything and print the plan; create nothing")
    args = ap.parse_args()

    # Clients come from the project's factory rather than a bare `boto3.Session`, and the reason
    # is not style. `A.account_id()` is the ONE place the account ID is resolved, because it
    # registers the value with `redact.register_account_id` so the masker can find the bare
    # 12 digits OUTSIDE ARN position. This script embeds the account ID in every resource ARN of
    # the IAM policy document it writes, and it PRINTS a plan under `--dry-run` — so an
    # unregistered account ID here is precisely the leak that function exists to prevent. (It was
    # also once the input the bucket name was derived from; `find_bucket()` records why that is
    # gone, and the print above is why the choke point still matters.)
    #
    # This replaces an inline `sess.client("sts").get_caller_identity()["Account"]`, which
    # `lib/tests/test_account_id_choke_point.py` failed on. Worth recording rather than quietly
    # fixing: the test was already in the tree, the choke point's own docstring says "ten inline
    # call sites are ten places to forget", and this file forgot — written in the same week, by
    # someone who had read it. The guard is what made a new module's leak a red test instead of a
    # finding in a published artifact (DEV-P4-25).
    #
    # The factory also disables botocore's transparent retry. That is the right default here:
    # every step below is idempotent and this script is documented as safe to re-run, so a
    # transient failure should stop and be re-run rather than be absorbed into one call whose
    # duration and outcome no longer describe a single attempt.
    fc = A.factory(REGION)
    account_id = A.account_id(fc)
    ec2, iam, ssm, s3 = (fc.client(n) for n in ("ec2", "iam", "ssm", "s3"))

    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise SystemExit("no default VPC in " + REGION)
    vpc_id = vpcs[0]["VpcId"]
    subnets = sorted(ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}],
                                          )["Subnets"], key=lambda s: s["AvailabilityZone"])
    subnet = next(s for s in subnets if s["MapPublicIpOnLaunch"])

    print(f"account {'<account>'}  region {REGION}  vpc <default>  az {subnet['AvailabilityZone']}")
    unmapped = []
    try:
        unmapped = IP.unmapped_operations()
    except RuntimeError as exc:
        print(f"  ! policy derivation: {exc}")
    if unmapped:
        raise SystemExit("unmapped operations in evidence/: "
                         + ", ".join(f"{s}.{o}" for s, o in unmapped)
                         + "\nadd them to runner/iam_policy.py MAPPING first")

    if args.dry_run:
        # The bucket is looked up, not derived, so a dry run reports whether one already exists
        # rather than printing a name it computed. The policy document is built against the real
        # name when there is one, because the resource ARNs it scopes are that bucket's.
        found = find_bucket(s3)
        doc = IP.document(account_id, REGION, found or BUCKET_PREFIX + "<suffix>")
        print(f"  plan: {INSTANCE_TYPE}, {VOLUME_GIB} GiB gp3 encrypted, "
              f"s3://{BUCKET_PREFIX}<suffix> ({'exists' if found else 'would be created'}), "
              f"role {ROLE_NAME} with "
              f"{sum(len(s['Action']) for s in doc['Statement'])} actions")
        print("  ~$17/month while running; nothing after runner/teardown.py")
        return 0

    bucket = ensure_bucket(s3)
    profile_arn = ensure_role(iam, account_id, bucket)
    sg_id = ensure_sg(ec2, vpc_id)

    inst = find_instance(ec2)
    if inst:
        _log(False, f"instance {inst['InstanceId']}", f"({inst['State']['Name']})")
        if inst["State"]["Name"] == "stopped":
            ec2.start_instances(InstanceIds=[inst["InstanceId"]])
            print("    started")
        iid = inst["InstanceId"]
        # Reuse is not the same as "unchanged". Something else in this account re-attaches a
        # different profile every hour, so the identity of a reused instance has to be read rather
        # than assumed — see ensure_instance_profile().
        if repaired := ensure_instance_profile(ec2, iid):
            print(f"    ! {repaired}")
    else:
        # An instance profile is not usable the instant it is created; RunInstances returns
        # InvalidParameterValue until IAM has propagated it. Retried rather than slept on a fixed
        # delay, per feedback_cryptic_error_is_missing_guard: the retry loop names the condition.
        for attempt in range(12):
            try:
                iid = launch(ec2, ssm, profile_arn, sg_id, subnet["SubnetId"], bucket)
                break
            except botocore.exceptions.ClientError as exc:
                if "Invalid IAM Instance Profile" not in str(exc) or attempt == 11:
                    raise
                print(f"    waiting for the instance profile to propagate ({attempt + 1}/12)")
                time.sleep(5)
        _log(True, f"instance {iid}", f"({INSTANCE_TYPE}, {VOLUME_GIB} GiB gp3 encrypted)")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(
        {"instance_id": iid, "region": REGION, "bucket": bucket, "role": ROLE_NAME,
         "security_group_id": sg_id, "subnet_id": subnet["SubnetId"], "vpc_id": vpc_id,
         "instance_type": INSTANCE_TYPE}, indent=2) + "\n", encoding="utf-8")
    print(f"\nids recorded in {STATE_PATH.relative_to(ROOT)} (gitignored)")
    print(f"next: runner/sync.py push        # upload the working tree")
    print(f"      aws ssm start-session --target {iid} --region {REGION}")
    print(f"      runner/teardown.py         # when done; ~$17/month until then")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
