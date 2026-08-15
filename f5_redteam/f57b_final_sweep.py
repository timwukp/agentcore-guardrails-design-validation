#!/usr/bin/env python3
"""Delete the residue a VPC-mode AgentCore runtime leaves behind, once the service releases its ENI.

Written for F5-7b, whose run ended with four items it could not delete: a service-managed
`agentic_ai` ENI attached by `amazon-aws`, and the security group, private subnet and VPC stacked
behind it. `f57b-sweep` retried the chain every 5 minutes for its full 240-minute budget — 48
consecutive `InvalidParameterValue` refusals — and exited 3 with all four retained in the ledger
rather than reported clean. The service released the interface some time after that, unprompted, and
the three items behind it then deleted on the first attempt. See `results/FINDING-F5-7B.md` §5-6.

That is why this exists as a script rather than as a command someone types once: the release happens
on the service's schedule, hours after every poller has given up, so the delete necessarily runs in a
*different process* from the one that created the resources. Ids therefore come in as arguments, read
back from the run's residue record (`residue.not_deleted[].params` in the case's `analysis.json`) —
never from a describe-and-guess, because a describe cannot say which VPC was this case's.

Two independent guards, because deleting the runner's own VPC loses SSM-only access to the instance
and there is no key pair to fall back on:

  1. every target must be absent from a deny-list resolved at runtime from the `grx-runner-sg` NAME
     — the runner's VPC, its subnets and its security groups. Resolving by name is how
     `12_vpc_egress_image_pull.py` does it: the hard-coded list it replaced protected under a sixth
     of the runner's network, and would go stale silently if the runner were rebuilt. An empty
     resolution refuses every delete rather than permitting all of them.
  2. `--cidr` must match the VPC's actual CIDR block. Not redundant with (1): it is an orthogonal
     second opinion on identity, and it is the guard that still holds if the deny-list is resolved
     against the wrong account or region. F5-7b deliberately used a block that cannot overlap the
     runner's default VPC, which is what makes the check discriminating rather than decorative.

Ids are arguments for a second reason: the runner's network ids are deliberately not written into any
repo file, and a cleanup script carrying literals is one edit away from carrying the wrong ones.

Usage:
    f5_redteam/f57b_final_sweep.py --vpc V --subnet S --sg G --eni E --cidr C [--region us-east-1]

Deletes in dependency order (sg, subnet, vpc) and reports each failure instead of aborting, so a
partial release is visible rather than hidden behind the first exception.
"""
from __future__ import annotations

import argparse

import boto3

RUNNER_SG_NAME = "grx-runner-sg"


def deny_list(ec2) -> set[str]:
    """The runner's own network, resolved from a name. Empty means refuse everything."""
    deny: set[str] = set()
    for sg in ec2.describe_security_groups(
            Filters=[{"Name": "group-name", "Values": [RUNNER_SG_NAME]}])["SecurityGroups"]:
        deny.add(sg["GroupId"])
        deny.add(sg["VpcId"])
        for s in ec2.describe_subnets(
                Filters=[{"Name": "vpc-id", "Values": [sg["VpcId"]]}])["Subnets"]:
            deny.add(s["SubnetId"])
        for g in ec2.describe_security_groups(
                Filters=[{"Name": "vpc-id", "Values": [sg["VpcId"]]}])["SecurityGroups"]:
            deny.add(g["GroupId"])
    return deny


def main() -> None:
    ap = argparse.ArgumentParser()
    for f in ("vpc", "subnet", "sg", "eni", "cidr"):
        ap.add_argument(f"--{f}", required=True)
    ap.add_argument("--region", default="us-east-1")
    a = ap.parse_args()

    ec2 = boto3.client("ec2", region_name=a.region)

    deny = deny_list(ec2)
    if not deny:
        raise SystemExit(f"deny-list resolved EMPTY from {RUNNER_SG_NAME} — refusing every delete")
    print(f"deny-list: {len(deny)} id(s) resolved from the {RUNNER_SG_NAME} name")

    overlap = [t for t in (a.sg, a.subnet, a.vpc) if t in deny]
    if overlap:
        raise SystemExit(f"REFUSING: target is in the runner's own network: {overlap}")

    vpcs = ec2.describe_vpcs(VpcIds=[a.vpc])["Vpcs"]
    if vpcs[0]["CidrBlock"] != a.cidr:
        raise SystemExit(f"REFUSING: {a.vpc} is {vpcs[0]['CidrBlock']}, not the expected {a.cidr}")
    print(f"{a.vpc} carries the expected CIDR and is not the runner's — both guards pass")

    # The ENI is the gate. If it is still held, the chain cannot clear, and issuing the three deletes
    # anyway produces DependencyViolations that read like a permissions problem instead of a wait.
    try:
        ec2.describe_network_interfaces(NetworkInterfaceIds=[a.eni])
        raise SystemExit(f"{a.eni} still exists — the chain is still blocked, nothing to do")
    except ec2.exceptions.ClientError as e:
        if "NotFound" not in str(e):
            raise
        print(f"{a.eni} is gone (NotFound) — the service released it")

    for call, kw, name in [(ec2.delete_security_group, {"GroupId": a.sg}, "ec2-sg"),
                           (ec2.delete_subnet, {"SubnetId": a.subnet}, "ec2-subnet/private"),
                           (ec2.delete_vpc, {"VpcId": a.vpc}, "ec2-vpc")]:
        try:
            call(**kw)
            print(f"  deleted {name}")
        except ec2.exceptions.ClientError as e:
            print(f"  {name}: {e.response['Error']['Code']}: {e.response['Error']['Message']}")

    left = ec2.describe_vpcs(Filters=[{"Name": "vpc-id", "Values": [a.vpc]}])["Vpcs"]
    print(f"back_to_baseline: {not left}   (vpcs still matching: {len(left)})")


if __name__ == "__main__":
    main()
