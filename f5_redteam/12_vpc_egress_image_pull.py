#!/usr/bin/env python3
"""F5-7b — does a VPC-mode runtime's image pull actually depend on a NAT route?

    Sealed oracle: "TRUE if a VPC-mode runtime without a NAT route fails image pull and
    succeeds with one; FALSE if egress is reachable either way"

`mutation_is_mandatory("F5-7b")` is True and `planned_n` is None. So this case is a two-arm
comparison over one runtime each, plus the inverse of the mutation and a re-verification, and it
cannot be published from a single arm.

WHY THIS IS THE LAST CASE IN THE PROJECT THAT COULD RUN
-------------------------------------------------------
Of the three cases with no verdict, F9-1 is sealed UNTESTABLE by its own oracle (AgentCore exposes
no fault-injection surface for policy evaluation) and F10-1 waits on Cost Explorer's ~24 h data lag,
which is physics rather than work. F5-7b is the only one whose obstacle was ours. It was recorded as
blocked on an arm64 container build (`results/DEPENDENCY-AUDIT-2026-08-13.md:103-125`) and it is not:
`containerUri`'s own pattern admits `public.ecr.aws`, which `f5_redteam/diag_vpc_runtime.py` then
MEASURED — a public multi-arch image is accepted and reaches READY. No ECR repository, no Docker
daemon, no cross-build, no `ecr:*` grant.

WHAT THE DIAGNOSTIC HANDED THIS SCRIPT, AND THE TRAP IT NAMED
-------------------------------------------------------------
`results/DIAG-vpc-runtime-20260814T092455Z.json`, measured 2026-08-14:

  * a public image in PUBLIC mode reached **READY in 10.1 s** with an empty `failureReason`;
  * a nonexistent TAG was refused **synchronously** by `CreateAgentRuntime`
    (`ValidationException: Public ECR resource not found for URI ...`), so image EXISTENCE is
    resolved by the control plane on its own network path, not the customer VPC's. That closes the
    ambiguity this script would otherwise have to defend against: a pull failure observed AFTER a
    successful create cannot be a missing image;
  * `networkMode=VPC` is live and validated server-side (fake subnet ids → `CREATE_FAILED`, "The
    following subnets could not be found").

And the trap, which is the single most likely way to publish a wrong verdict here: **READY arrived
at the very FIRST poll — 10.1 s, i.e. exactly one poll interval** — for that container and for
F5-8's code artifact alike. That is a strong hint that READY does not mean the image has been
fetched; the pull may be lazy, or deferred to first invoke. A producer that scored this case on
create-time status alone could watch its no-NAT arm reach READY and record "egress is reachable
either way", which is the oracle's FALSE, on no evidence whatsoever.

So **both channels are measured on every arm**: the create-time terminal status with its
`failureReason`, AND an actual `InvokeAgentRuntime`. The scoring below reads whichever channel
discriminated, and if NEITHER did it returns INCONCLUSIVE for a stated instrument reason rather than
choosing a verdict. That branch is not a hedge — F1-15 is INCONCLUSIVE for exactly such a reason and
the reason is the finding.

THE IMAGE SERVES NOTHING, AND THAT IS FINE
------------------------------------------
`public.ecr.aws/nginx/nginx:stable` listens on :80 and never answers AgentCore's contract
(`POST /invocations`, `GET /ping`, on :8080). So a *successful* pull still yields a failing invoke.
That does not weaken the comparison, because the comparison is DIFFERENTIAL: both arms run the same
image and differ only in one route. What the oracle needs is that the two arms be distinguishable,
not that either succeed end to end. Choosing an image that serves the contract would require
building one, which is the dependency this case was blocked on for a day.

The consequence for scoring is stated explicitly rather than left implicit: this script can conclude
"the pull differs with and without the route". It cannot conclude "the runtime works", and the
payload's `what_true_does_not_prove` says so.

THE NETWORK, AND WHY IT IS BUILT FROM SCRATCH
---------------------------------------------
    vpc            10.61.0.0/16              tagged with the run id
    subnet public  10.61.0.0/24              holds the NAT gateway
    subnet private 10.61.1.0/24              holds the runtime's ENIs
    igw            attached to the vpc
    rtb public     0.0.0.0/0 -> igw          associated to the public subnet
    rtb private    (local only, at first)    associated to the private subnet
    eip + natgw    in the public subnet

Both route tables are created and associated EXPLICITLY, so nothing depends on the VPC's main route
table. That is not tidiness: the mutation is a `0.0.0.0/0` route, and adding it to a main route
table would silently change the other subnet too, which would make the arms differ in more than the
one thing under test.

A new VPC rather than the runner's own, for a reason that is also the safety argument below: the
mutation and its inverse are `CreateRoute`/`DeleteRoute`, and the runner instance is reachable ONLY
by SSM — no key pair, no public ingress. A `DeleteRoute` in the runner's VPC would sever the only
channel that can run or clean up anything, including this script's own teardown.

THE TWO GUARDS, AND WHY THEY ARE HERE AND NOT IN IAM
----------------------------------------------------
`runner/iam_policy.py` now grants `ec2:DeleteVpc`, `ec2:DeleteSubnet`, `ec2:DeleteRoute` and
`ec2:DeleteSecurityGroup`, and EC2 network resources are not nameable by ARN pattern the way roles
are, so those grants land on `*`. IAM therefore cannot express "not the runner's own network". The
bound has to be in this script:

  1. `guard()` — an explicit deny-list of the runner's `vpc-`/`subnet-`/`sg-` ids, asserted before
     every destructive EC2 call. It **aborts**, it does not skip: a destructive call aimed at the
     wrong id means this script's bookkeeping is wrong, and continuing on wrong bookkeeping is how
     the second wrong call happens.
  2. every delete is addressed by an id **read back from this run's ledger entry**, never from a
     `describe_*` filter. A filter that matched too widely once would delete somebody else's subnet
     and the tag it filtered on would be the reason.

`f5_redteam/tests/test_vpc_egress_image_pull.py` pins both.

TEARDOWN ORDER, WHICH IS LOAD-BEARING
-------------------------------------
Runtimes first, because their ENIs sit in the private subnet and a subnet with a dependent ENI
refuses to delete; then a wait on the ENIs actually clearing, polled rather than assumed. Then
routes, route-table associations and route tables; then the NAT gateway (polled to `deleted` — the
EIP cannot be released while it is attached, and this is the one resource here that bills at an
hourly rate); then the EIP; then IGW detach and delete; then the security group; then the subnets;
then the VPC. `delete_priority` on each ledger entry encodes this so `runner/teardown.py` gets the
same order if this script is killed.

COST
----
One NAT gateway at ~$0.045/h plus a few cents of data, three runtimes that are created and deleted,
and no model call. A run under an hour is a few cents; the ceiling in `cost_model.yaml` is $95 and
the projection is $6.67. The NAT gateway is the only item that keeps billing if leaked, which is why
it is ledgered before it is created and polled to `deleted` on the way out.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import awsclients as A                                                # noqa: E402
import oracle as O                                                    # noqa: E402
import phase1 as P                                                    # noqa: E402
import redact as R                                                    # noqa: E402
import testbed as T                                                   # noqa: E402
from evidence import EvidenceStore, capture                           # noqa: E402
from runtime_code_pkg import service_trust                            # noqa: E402

FAMILY = "f5_redteam"
CASE = "F5-7b"

# ---------------------------------------------------------------------------- the deny-list
# The runner instance's own network: its VPC, EVERY subnet in that VPC, and every security group in
# it. Losing any of them severs SSM, which is the only channel that can run or clean up anything —
# including this script's own teardown.
#
# RESOLVED AT RUNTIME from the security group NAME (`runner/provision.py:SG_NAME`), not written here
# as ids. An earlier draft hard-coded the three ids, on the argument that a derived deny-list reads
# from the same bookkeeping whose failure it exists to survive. That argument was wrong twice over:
#
#   * it does not read the same bookkeeping. The ids came from `runner/provision.py`'s output —
#     i.e. from `runner/.state/`. Resolving from a NAME reads the EC2 control plane instead, which
#     is the authority, not a copy of it.
#   * a hard-coded list cannot go stale LOUDLY. If the runner is ever rebuilt — and its instance
#     profile is already being swapped out from under it hourly by an account-wide association —
#     the literals would name three resources that no longer exist, so `guard()` would pass on
#     everything while protecting nothing. That is the exact failure a guard must not have.
#
# Derivation also widens the set correctly: all subnets and all security groups in the runner's VPC,
# rather than the one subnet and one SG that happen to be attached today.
#
# `resolve_forbidden()` RAISES if it cannot resolve, and `guard()` raises if the set was never
# populated. An unresolvable deny-list must stop the run, never open it.
#
# The name is duplicated from `runner/provision.py:SG_NAME` rather than imported: `runner/` is the
# control plane that drives this script from outside, and importing it into a case producer would
# make the producer unrunnable anywhere the runner package is absent. A name is also the one thing
# here that is safe to write down — it identifies nothing on its own.
RUNNER_SG_NAME = "grx-runner-sg"
FORBIDDEN_IDS: frozenset[str] = frozenset()

VPC_CIDR = "10.61.0.0/16"
PUBLIC_CIDR = "10.61.0.0/24"
PRIVATE_CIDR = "10.61.1.0/24"
# 10.61/16 deliberately: the default VPC is 172.31/16, so nothing here can collide with the
# runner's own addressing even by accident.

# The image the diagnostic measured. Multi-arch, public, pulls in PUBLIC mode, reaches READY, and
# does NOT serve AgentCore's contract. See the docstring on why that last property is acceptable.
IMAGE = "public.ecr.aws/nginx/nginx:stable"

POLL_SECONDS = 10
POLL_TIMEOUT = 600            # VPC-mode creates settle slower than PUBLIC ones; measured 10.1 s for
                              # the fake-id refusal, but a real ENI attach is not that call.
NAT_POLL_SECONDS = 15
NAT_AVAILABLE_TIMEOUT = 300
NAT_DELETED_TIMEOUT = 600
ENI_CLEAR_TIMEOUT = 420
ENI_POLL_SECONDS = 15
INTER_IAM_S = 2.0
TRUST_SETTLE_S = 15           # a new role's trust policy is eventually consistent and
                              # CreateAgentRuntime assumes it synchronously. F5-8:309-314.
ROUTE_SETTLE_S = 20           # after CreateRoute, before the arm that depends on it. A WAIT and not
                              # a retry: a retry would let arm B pass on its third attempt and
                              # publish "egress works" while hiding that it did not work at first.
TERMINAL = {"READY", "CREATE_FAILED", "UPDATE_FAILED"}

ARM_NO_ROUTE = "no_nat_route"
ARM_WITH_ROUTE = "with_nat_route"
ARM_RESTORED = "route_removed_again"

# Reused from the diagnostic rather than re-guessed. Post-pull is checked BEFORE pull because
# nothing health-checks an image it did not fetch, and several pull words ("not found", "denied")
# appear in unrelated messages.
#
# `timeout` AND `timed out` WERE IN THIS LIST AND ARE NOT ANY MORE. Measured 2026-08-14: all three
# arms of the first live run failed their invoke with a botocore *client-side* read timeout, which
# matched `timeout` here and was therefore labelled `pull` — i.e. as evidence that the image was
# never fetched. It is no such thing. The decisive tell is in the durations: 70082, 70077 and
# 70073 ms, a 9 ms spread across three arms whose network configurations DIFFER. That is a fixed
# local socket timeout observed three times, not a property of any fetch.
#
# The words were plausible here as long as this list only ever read a SERVICE-supplied
# `failureReason`, where "pull timed out" is a real message. They stop being plausible the moment
# the same list is pointed at a client-side error, whose text names the AWS endpoint URL and
# nothing about a container. Removing them is not enough on its own — a message that never arrived
# cannot name any step, whatever words it happens to contain — so `pull_evidence` now refuses such
# an invoke STRUCTURALLY, on `http_status is None`, before any string is inspected.
#
# This is DEV-P4-22 for the second time on an unrelated surface. F1-15's false FALSE came from two
# byte-identical 107-byte bodies at 38 ms being read as "routed"; this came from three constant
# 70 s timeouts being read as "pull_failed". Both are a CONSTANT mistaken for a MEASUREMENT.
PULL_MARKERS = ("pull", "image not found", "manifest", "not found", "unauthorized",
                "no such", "unable to retrieve", "registry", "denied",
                "unreachable", "network")
POST_PULL_MARKERS = ("ping", "health", "8080", "port", "did not respond",
                     "readiness", "container failed to start", "did not become healthy",
                     "exited", "exit code", "crashloop", "restart")


# ---------------------------------------------------------------------------- guards

class GuardTripped(RuntimeError):
    """A destructive call was aimed at an id on the deny-list, or at no id at all."""


def resolve_forbidden(ec2, store) -> frozenset[str]:
    """The runner's own VPC, all its subnets and all its security groups, from the SG name.

    Sets the module-level `FORBIDDEN_IDS` and returns it. Raises if the security group cannot be
    found or carries no VpcId: a deny-list that cannot be built is not a reason to proceed without
    one, and this runs BEFORE the first create, so aborting here costs nothing.

    Read-only describes. Nothing in this function mutates anything.
    """
    global FORBIDDEN_IDS                                              # noqa: PLW0603
    sg = capture(store, "describe_security_groups", ec2,
                 Filters=[{"Name": "group-name", "Values": [RUNNER_SG_NAME]}])
    sg.raise_for_status()
    groups = sg.response.get("SecurityGroups") or []
    if not groups:
        raise GuardTripped(
            f"cannot resolve the runner's own network: no security group named {RUNNER_SG_NAME!r} "
            f"in this region. Refusing to run a script that issues ec2:Delete* with no deny-list.")
    vpc_id = groups[0].get("VpcId") or ""
    if not vpc_id:
        raise GuardTripped(
            f"security group {RUNNER_SG_NAME!r} reports no VpcId, so the runner's VPC is unknown "
            f"and the deny-list would be incomplete. Refusing to run.")

    subs = capture(store, "describe_subnets", ec2,
                   Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    subs.raise_for_status()
    sgs = capture(store, "describe_security_groups", ec2,
                  Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    sgs.raise_for_status()

    ids = {vpc_id}
    ids |= {s["SubnetId"] for s in subs.response.get("Subnets") or []}
    ids |= {g["GroupId"] for g in sgs.response.get("SecurityGroups") or []}
    FORBIDDEN_IDS = frozenset(i for i in ids if i)
    print(f"  deny-list: {len(FORBIDDEN_IDS)} id(s) resolved from the runner's own VPC "
          f"(1 vpc, {len(subs.response.get('Subnets') or [])} subnet(s), "
          f"{len(sgs.response.get('SecurityGroups') or [])} security group(s))")
    return FORBIDDEN_IDS


def guard(*ids: str) -> None:
    """Assert every id is this run's own and not the runner's. ABORTS; does not skip.

    Also refuses an EMPTY id, which is the more likely failure in practice: a `.get()` on a
    ledger entry that was never completed yields `""`, and several EC2 deletes treat a missing
    parameter as a validation error rather than a no-op — but `delete_route`'s destination is a
    CIDR, and a call assembled from partly-empty bookkeeping is not a call worth making.
    """
    if not FORBIDDEN_IDS:
        raise GuardTripped(
            "the deny-list is empty, so `resolve_forbidden()` either never ran or found nothing. "
            "Every destructive call in this script is guarded against it; an empty guard is not a "
            "guard. Aborting before the first delete.")
    for i in ids:
        if not i:
            raise GuardTripped(
                "a destructive EC2 call was assembled with an empty resource id, which means this "
                "run's bookkeeping is incomplete. Aborting rather than guessing: read the ledger "
                "and delete by hand.")
        if i in FORBIDDEN_IDS:
            raise GuardTripped(
                f"REFUSING to touch {i}: it belongs to the runner instance's own network. The "
                f"instance is reachable only by SSM, so deleting this would sever the only channel "
                f"that can run or clean up anything, including this script's own teardown.")


def register_own_ids(state, residue: dict) -> dict[str, str]:
    """Teach `lib/redact.py` every infrastructure id THIS RUN created, before `results/` is written.

    MEASURED 2026-08-14: the first live run of this case wrote **31 unredacted VPC-family ids** into
    `results/phase1/F5-7b.json` — the VPC, both subnets, the security group and the leftover ENI,
    several of them inside EC2's own `DependencyViolation` strings in the residue block. `P.emit`
    had masked that file correctly the whole time. The leak was that `lib/redact.py` had no rule for
    the class, because this is the only case in the project that creates EC2 network resources, so
    nothing had ever needed one. `lib/tests/test_results_writes_are_masked.py` passed throughout: it
    asserts the write is WRAPPED in a masker, not that the masker covers what the payload holds.

    Registered from the LEDGER rather than at each create site. `build_network` writes the ledger
    entry BEFORE every create (see its docstring), so the ledger holds every id this case is
    responsible for destroying — exactly the set that should be masked, and complete for the same
    reason the teardown is entitled to rely on it. Registering inside `step()` instead would miss
    the creates that do not go through `step()`, and would miss them SILENTLY.

    What is deliberately NOT registered: anything that is not this run's own. The runner's own VPC,
    subnets and security groups — the 20 ids `resolve_forbidden()` prints — stay readable, because
    that printout is how a human confirms the deny-list resolved to the right network. A masked
    safety printout is a useless one.
    """
    for res in state.deletion_order():
        if (res.ids or {}).get("case") != CASE:
            continue
        for value in (res.ids or {}).values():
            if isinstance(value, str):
                try:
                    R.register_resource_id(value)
                except ValueError:
                    pass                  # `ids` also carries `case` and other non-id bookkeeping
    # The ENIs are NOT ledgered as resources of this case: the AgentCore service creates them inside
    # our subnet and they are discovered during teardown, so their ids appear in the residue rather
    # than in the ledger. That is also where they leaked from.
    for item in residue.get("not_deleted") or []:
        for token in str(item.get("resource", "")).replace("/", " ").split():
            try:
                R.register_resource_id(token)
            except ValueError:
                pass
    return R.known_resource_ids()


def bucket_failure(reason: str) -> tuple[str, str]:
    """Label a `failureReason` as pull, post-pull, or unreadable — and say why."""
    if not reason:
        return "no_reason_given", "the service returned no failureReason at all"
    low = reason.lower()
    post = [m for m in POST_PULL_MARKERS if m in low]
    pre = [m for m in PULL_MARKERS if m in low]
    if post:
        return "post_pull", f"names a step that presupposes a fetched image: {post}"
    if pre:
        return "pull", f"names the fetch itself: {pre}"
    return "unclassified", "matched no marker in either list — read the raw string"


def arm_signature(arm: dict) -> dict:
    """What an arm said, read off whichever channel it said it on.

    Carried over from `diag_vpc_runtime.arm_signature()` and for the reason recorded there: the
    first version of that predicate read only `failure_reason`, so an arm refused synchronously by
    `CreateAgentRuntime` registered as having said nothing, and the run's most favourable
    measurement was labelled unmeasurable. Comparing a `(channel, code, text)` triple makes it
    impossible to compare two arms on a field only one of them populates.
    """
    if arm.get("create_refused"):
        return {"channel": "create_refused",
                "code": str(arm.get("error_code") or ""),
                "text": str(arm.get("error_message") or "")}
    return {"channel": "terminal",
            "code": str(arm.get("terminal_status") or ""),
            "text": str(arm.get("failure_reason") or "")}


def invoke_signature(arm: dict) -> dict:
    """The same idea for the invoke channel, which has three outcomes and not two.

    An invoke can be refused by the service (an error code), answered by the runtime, or answered
    by the service on the runtime's behalf when the runtime is not there. Only the first two are
    distinguishable without reading the body, so the body is carried.
    """
    inv = arm.get("invoke") or {}
    if not inv:
        return {"channel": "not_attempted", "code": "", "text": ""}
    if not inv.get("ok"):
        return {"channel": "invoke_error", "code": str(inv.get("error_code") or ""),
                "text": str(inv.get("error_message") or "")}
    return {"channel": "invoke_ok", "code": "200", "text": str(inv.get("body") or "")[:400]}


# ---------------------------------------------------------------------------- network build

def _tags(run_id: str, expires_at: str, name: str) -> list[dict]:
    d = dict(A.tags_for(run_id, expires_at))
    d["Name"] = name
    return [{"Key": k, "Value": v} for k, v in d.items()]


def _wait(fn, want, timeout: int, every: int, what: str) -> tuple[str, float]:
    """Poll `fn()` until it returns a value in `want`. Returns (last_value, seconds)."""
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        last = fn()
        if last in want:
            return last, round(time.time() - t0, 1)
        time.sleep(every)
    return last, round(time.time() - t0, 1)


def build_network(ec2, store, state, run_id: str, expires_at: str, az: str) -> dict:
    """Create the VPC and everything in it, LEDGER-FIRST at every step.

    Ledger-first for the reason `11_route_credential_reachability.py:262-266` states: the window
    between a successful create and a recorded create is the window in which a kill leaves an
    untracked resource. A stale ledger entry costs one `NotFound` at teardown; an unrecorded NAT
    gateway costs $0.045 an hour until somebody notices.

    The ledger entry is written before the create with the id it does not yet know left blank, then
    RE-recorded once the id exists — `State.record` is keyed on `(kind, logical)`, so the second
    write replaces the first in place rather than accumulating.
    """
    net: dict = {"az": az}

    def step(kind, logical, name, delete_op, id_key, priority, notes, call_op, **params):
        state.record(T.Resource(
            kind=kind, logical=logical, name=name, service="ec2",
            delete_op=delete_op, delete_params={}, delete_priority=priority,
            ids={"case": CASE}, notes=notes))
        state.write()
        rec = capture(store, call_op, ec2, **params).raise_for_status()
        # The id is dug out by key rather than by position: several of these responses nest it one
        # level down under the resource name, and a positional read would silently pick up a
        # request id when the shape changed.
        res = rec.response or {}
        rid = ""
        for k, v in res.items():
            if isinstance(v, dict) and id_key in v:
                rid = v[id_key]
                break
            if k == id_key:
                rid = v
                break
        if not rid:
            raise RuntimeError(f"{call_op} returned no {id_key}: {json.dumps(res)[:300]}")
        state.record(T.Resource(
            kind=kind, logical=logical, name=name, service="ec2",
            delete_op=delete_op, delete_params={id_key: rid}, delete_priority=priority,
            ids={id_key: rid, "case": CASE}, notes=notes))
        state.write()
        print(f"    {logical:16} {rid}")
        return rid

    print("  building the network")
    net["vpc_id"] = step(
        "ec2-vpc", "f57b_vpc", f"grx-f57b-{run_id}", "delete_vpc", "VpcId", 90,
        "F5-7b's own VPC. Everything else in this ledger tagged F5-7b lives inside it, so it "
        "deletes LAST. If this is still here the run did not reach its teardown.",
        "create_vpc", CidrBlock=VPC_CIDR,
        TagSpecifications=[{"ResourceType": "vpc",
                            "Tags": _tags(run_id, expires_at, f"grx-f57b-{run_id}")}])

    for logical, cidr, label in (("f57b_subnet_public", PUBLIC_CIDR, "public"),
                                 ("f57b_subnet_private", PRIVATE_CIDR, "private")):
        net[f"subnet_{label}"] = step(
            "ec2-subnet", logical, f"grx-f57b-{label}-{run_id}", "delete_subnet", "SubnetId", 80,
            f"F5-7b's {label} subnet. The private one holds the runtime's ENIs, so runtimes must "
            f"be deleted and their ENIs cleared before this can go.",
            "create_subnet", VpcId=net["vpc_id"], CidrBlock=cidr, AvailabilityZone=az,
            TagSpecifications=[{"ResourceType": "subnet",
                                "Tags": _tags(run_id, expires_at,
                                              f"grx-f57b-{label}-{run_id}")}])

    net["sg_id"] = step(
        "ec2-sg", "f57b_sg", f"grx-f57b-sg-{run_id}", "delete_security_group", "GroupId", 70,
        "F5-7b's security group. Egress allow-all (the default for a new group) and NO ingress: "
        "the runtime is reached through the AgentCore data plane, never directly.",
        "create_security_group", GroupName=f"grx-f57b-sg-{run_id}", VpcId=net["vpc_id"],
        Description=f"GRX {CASE}: VPC-mode runtime egress test",
        TagSpecifications=[{"ResourceType": "security-group",
                            "Tags": _tags(run_id, expires_at, f"grx-f57b-sg-{run_id}")}])

    net["igw_id"] = step(
        "ec2-igw", "f57b_igw", f"grx-f57b-igw-{run_id}", "delete_internet_gateway",
        "InternetGatewayId", 60,
        "F5-7b's internet gateway. Must be DETACHED from the VPC before it can be deleted; "
        "runner/teardown.py reads detach_vpc_id from ids for that.",
        "create_internet_gateway",
        TagSpecifications=[{"ResourceType": "internet-gateway",
                            "Tags": _tags(run_id, expires_at, f"grx-f57b-igw-{run_id}")}])
    capture(store, "attach_internet_gateway", ec2,
            InternetGatewayId=net["igw_id"], VpcId=net["vpc_id"]).raise_for_status()
    # Re-recorded so teardown knows what to detach it from. Without this the delete fails with
    # DependencyViolation and reads like a propagation problem.
    state.record(T.Resource(
        kind="ec2-igw", logical="f57b_igw", name=f"grx-f57b-igw-{run_id}", service="ec2",
        delete_op="delete_internet_gateway",
        delete_params={"InternetGatewayId": net["igw_id"]}, delete_priority=60,
        ids={"InternetGatewayId": net["igw_id"], "detach_vpc_id": net["vpc_id"], "case": CASE},
        notes="F5-7b's internet gateway, ATTACHED to detach_vpc_id. Detach before delete."))
    state.write()

    net["eip_alloc"] = step(
        "ec2-eip", "f57b_eip", f"grx-f57b-eip-{run_id}", "release_address", "AllocationId", 55,
        "F5-7b's Elastic IP, attached to the NAT gateway. Cannot be released until the NAT "
        "gateway reaches state `deleted`, which is polled and not assumed.",
        "allocate_address", Domain="vpc",
        TagSpecifications=[{"ResourceType": "elastic-ip",
                            "Tags": _tags(run_id, expires_at, f"grx-f57b-eip-{run_id}")}])

    net["nat_id"] = step(
        "ec2-natgw", "f57b_natgw", f"grx-f57b-nat-{run_id}", "delete_nat_gateway",
        "NatGatewayId", 50,
        "F5-7b's NAT gateway. THE ONLY RESOURCE IN THIS RUN THAT BILLS AT AN HOURLY RATE "
        "(~$0.045/h). If this is still here, it is costing money right now.",
        "create_nat_gateway", SubnetId=net["subnet_public"], AllocationId=net["eip_alloc"],
        TagSpecifications=[{"ResourceType": "natgateway",
                            "Tags": _tags(run_id, expires_at, f"grx-f57b-nat-{run_id}")}])

    # 45 written literally rather than carried through the loop tuple: both tables delete at the
    # same point, so a loop variable would have been a varying-looking value that never varies —
    # and it hides the number from the AST scan in
    # `f5_redteam/tests/test_vpc_egress_image_pull.py` that checks the teardown order.
    for logical, label in (("f57b_rtb_public", "public"),
                           ("f57b_rtb_private", "private")):
        net[f"rtb_{label}"] = step(
            "ec2-rtb", logical, f"grx-f57b-rtb-{label}-{run_id}", "delete_route_table",
            "RouteTableId", 45,
            f"F5-7b's {label} route table, EXPLICITLY associated to the {label} subnet so the "
            f"VPC's main route table carries nothing and the two subnets cannot influence each "
            f"other. Associations must be dropped before the table can be deleted.",
            "create_route_table", VpcId=net["vpc_id"],
            TagSpecifications=[{"ResourceType": "route-table",
                                "Tags": _tags(run_id, expires_at,
                                              f"grx-f57b-rtb-{label}-{run_id}")}])

    for label in ("public", "private"):
        assoc = capture(store, "associate_route_table", ec2,
                        RouteTableId=net[f"rtb_{label}"],
                        SubnetId=net[f"subnet_{label}"]).raise_for_status()
        net[f"assoc_{label}"] = (assoc.response or {}).get("AssociationId", "")
        state.record(T.Resource(
            kind="ec2-rtb-assoc", logical=f"f57b_assoc_{label}",
            name=f"grx-f57b-assoc-{label}-{run_id}", service="ec2",
            delete_op="disassociate_route_table",
            delete_params={"AssociationId": net[f"assoc_{label}"]}, delete_priority=40,
            ids={"AssociationId": net[f"assoc_{label}"],
                 "RouteTableId": net[f"rtb_{label}"], "case": CASE},
            notes=f"F5-7b's {label} subnet/route-table association."))
        state.write()

    # The public subnet's default route. NOT the mutation — this one is part of the fixture, and it
    # exists so the NAT gateway itself can reach the internet. Arm A's "no route" is about the
    # PRIVATE table.
    capture(store, "create_route", ec2, RouteTableId=net["rtb_public"],
            DestinationCidrBlock="0.0.0.0/0",
            GatewayId=net["igw_id"]).raise_for_status()

    print("    waiting for the NAT gateway to become available")
    def nat_state() -> str:
        r = capture(store, "describe_nat_gateways", ec2, NatGatewayIds=[net["nat_id"]])
        gws = ((r.response or {}).get("NatGateways") or [{}])
        return str(gws[0].get("State") or "")
    st, secs = _wait(nat_state, {"available", "failed", "deleted"},
                     NAT_AVAILABLE_TIMEOUT, NAT_POLL_SECONDS, "nat gateway")
    net["nat_state"] = st
    net["nat_seconds"] = secs
    print(f"    nat gateway {st} after {secs}s")
    if st != "available":
        raise RuntimeError(
            f"the NAT gateway reached {st!r} rather than available after {secs}s. Arm B needs a "
            f"working NAT gateway, and an arm B that fails for a NAT reason would read exactly "
            f"like an arm B that fails for a pull reason — which is the confusion this whole case "
            f"has to avoid.")
    return net


# ---------------------------------------------------------------------------- the runtime arms

def make_role(iam, store, role_name: str, account: str, run_id: str, expires_at: str,
              state) -> str:
    """A minimal execution role, ledgered before it is created.

    NOT `grx-runtime-exec-<run_id>`: the exact content of that role's inline policy set IS F5-1's
    published oracle, `infra/01_iam.py --ensure` refuses on drift, and the runner's own derived
    policy carries an explicit Deny on `iam:PutRolePolicy` for `role/grx-runtime-exec-*` so that
    this mistake fails at the API rather than in a published verdict.
    """
    state.record(T.Resource(
        kind="iam-role", logical="f57b_runtime_exec", name=role_name, service="iam",
        delete_op="delete_role", delete_params={"RoleName": role_name},
        ids={"role_name": role_name, "case": CASE}, delete_priority=20,
        notes=("F5-7b's runtime execution role. Its inline policy `grx-runtime-vpcegress` must be "
               "deleted before the role.")))
    state.write()
    capture(store, "create_role", iam, RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(service_trust(account)),
            Description=f"GRX {CASE}: VPC-mode runtime egress test",
            Tags=[{"Key": k, "Value": v}
                  for k, v in A.tags_for(run_id, expires_at).items()]).raise_for_status()
    time.sleep(INTER_IAM_S)
    capture(store, "put_role_policy", iam, RoleName=role_name,
            PolicyName="grx-runtime-vpcegress",
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Sid": "Logs", "Effect": "Allow",
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents",
                               "logs:DescribeLogStreams"],
                    "Resource": "*"}]})).raise_for_status()
    return f"arn:aws:iam::{account}:role/{role_name}"


def runtime_arm(ac, rt, store, state, *, arm: str, name: str, role_arn: str,
                net: dict, run_id: str, expires_at: str) -> dict:
    """Create one VPC-mode runtime, settle it, and INVOKE it. Both channels, every arm.

    Both, because of the trap the diagnostic named: READY arrived at the first poll for a container
    that had not been given time to pull anything, so create-time status alone may not observe the
    pull at all. If the pull is lazy, the invoke is where it happens.
    """
    out: dict = {"arm": arm, "runtime_name": name, "image": IMAGE,
                 "network_mode": "VPC", "subnets": [net["subnet_private"]],
                 "security_groups": [net["sg_id"]]}
    state.record(T.Resource(
        kind="agent-runtime", logical=f"f57b_runtime_{arm}", name=name, service="bedrock-agentcore",
        delete_op="delete_agent_runtime", delete_params={}, delete_priority=10,
        ids={"case": CASE, "arm": arm},
        notes=(f"F5-7b arm {arm}. Holds an ENI in the private subnet, so it must be deleted "
               f"before the subnet and the ENI must be observed to clear.")))
    state.write()

    rec = capture(store, "create_agent_runtime", ac,
                  agentRuntimeName=name,
                  agentRuntimeArtifact={"containerConfiguration": {"containerUri": IMAGE}},
                  roleArn=role_arn,
                  networkConfiguration={
                      "networkMode": "VPC",
                      "networkModeConfig": {"subnets": [net["subnet_private"]],
                                            "securityGroups": [net["sg_id"]]}},
                  protocolConfiguration={"serverProtocol": "HTTP"},
                  tags=A.tags_for(run_id, expires_at))
    if not rec.ok:
        out.update({"created": False, "create_refused": True, "error_code": rec.error_code,
                    "error_message": rec.error_message, "request_id": rec.request_id})
        state.drop("agent-runtime", f"f57b_runtime_{arm}")
        state.write()
        print(f"      CREATE REFUSED  {rec.error_code}: {rec.error_message}")
        return out

    res = rec.response or {}
    rid = str(res.get("agentRuntimeId") or "")
    arn = str(res.get("agentRuntimeArn") or "")
    out.update({"created": True, "runtime_id": rid, "runtime_arn_recorded": bool(arn)})
    state.record(T.Resource(
        kind="agent-runtime", logical=f"f57b_runtime_{arm}", name=name, service="bedrock-agentcore",
        delete_op="delete_agent_runtime", delete_params={"agentRuntimeId": rid},
        delete_priority=10, arn=arn, ids={"agentRuntimeId": rid, "case": CASE, "arm": arm},
        notes=(f"F5-7b arm {arm}. Holds an ENI in the private subnet, so it must be deleted "
               f"before the subnet and the ENI must be observed to clear.")))
    state.write()

    t0 = time.time()
    status, reason = "", ""
    while time.time() - t0 < POLL_TIMEOUT:
        g = capture(store, "get_agent_runtime", ac, agentRuntimeId=rid)
        if not g.ok:
            out["poll_error"] = f"{g.error_code}: {g.error_message}"
            break
        status = str((g.response or {}).get("status") or "")
        reason = str((g.response or {}).get("failureReason") or "")
        if status in TERMINAL:
            break
        time.sleep(POLL_SECONDS)
    label, why = bucket_failure(reason)
    out.update({"terminal_status": status, "failure_reason": reason,
                "seconds_to_terminal": round(time.time() - t0, 1),
                "step_label": label, "step_why": why})
    print(f"      {status or '(no status)'} after {out['seconds_to_terminal']}s  [{label}]")
    print(f"      reason: {reason or '(none)'}")

    # ---- the second channel. Attempted even when the runtime never reached READY, because
    # "what does an invoke say about a runtime that failed to create" is itself part of what
    # distinguishes the arms, and skipping it would leave one arm with a channel the other has.
    inv = capture(store, "invoke_agent_runtime", rt, agentRuntimeArn=arn,
                  contentType="application/json", accept="application/json",
                  payload=json.dumps({"f57b_arm": arm, "prompt": "ping"}).encode())
    body = ""
    if inv.ok:
        raw = (inv.response or {}).get("response")
        body = raw if isinstance(raw, str) else json.dumps(raw)[:1000] if raw else ""
    out["invoke"] = {"ok": bool(inv.ok), "http_status": inv.http_status,
                     "error_code": inv.error_code, "error_message": inv.error_message,
                     "request_id": inv.request_id, "body": body[:1000],
                     "duration_ms": inv.duration_ms}
    ilab, iwhy = bucket_failure(str(inv.error_message or "") + " " + body)
    out["invoke"]["step_label"] = ilab
    out["invoke"]["step_why"] = iwhy
    print(f"      invoke: {'200' if inv.ok else inv.error_code}  [{ilab}] "
          f"{(inv.error_message or body or '')[:120]}")
    return out


def delete_runtime(ac, store, state, arm: str) -> bool:
    """Delete one arm's runtime by the id READ BACK FROM THE LEDGER, never from a describe."""
    entry = state.find("agent-runtime", f"f57b_runtime_{arm}")
    if entry is None:
        return True
    rid = (entry.ids or {}).get("agentRuntimeId", "")
    if not rid:
        state.drop("agent-runtime", f"f57b_runtime_{arm}")
        state.write()
        return True
    d = capture(store, "delete_agent_runtime", ac, agentRuntimeId=rid)
    if d.ok or d.error_code in ("ResourceNotFoundException", "ValidationException"):
        state.drop("agent-runtime", f"f57b_runtime_{arm}")
        state.write()
        return True
    return False


# ---------------------------------------------------------------------------- scoring

def pull_evidence(arm: dict) -> tuple[str, str]:
    """Did THIS arm's image get fetched? One of `pull_failed` / `pull_succeeded` / `ambiguous`.

    Written as an explicit decision table over the two channels rather than as a chain of ifs on
    whichever field happened to be populated, and deliberately written BEFORE the arms ran, so the
    reading is not fitted to the observation. `ambiguous` is a first-class outcome with the same
    standing as the other two: F1-15's false FALSE was produced by a classifier that had no bucket
    for "this observation does not answer the question", so every unrecognised shape fell into a
    bucket that did.

    The reason returned alongside is not decoration. A verdict here is one word, and one word cannot
    be audited against the evidence that produced it.
    """
    if arm.get("create_refused"):
        return "ambiguous", (
            f"CreateAgentRuntime refused the call outright ({arm.get('error_code')}: "
            f"{arm.get('error_message')}), so no image was ever asked for and this arm says nothing "
            f"about the pull")
    status = arm.get("terminal_status") or ""
    label = arm.get("step_label") or ""
    inv = arm.get("invoke") or {}
    ilabel = inv.get("step_label") or ""

    # Channel 1: the create settled into a failure that names the fetch.
    if status in ("CREATE_FAILED", "UPDATE_FAILED") and label == "pull":
        return "pull_failed", (
            f"the create settled {status} and its failureReason names the fetch itself "
            f"({arm.get('step_why')}): {(arm.get('failure_reason') or '')[:200]}")
    if status in ("CREATE_FAILED", "UPDATE_FAILED") and label == "post_pull":
        return "pull_succeeded", (
            f"the create settled {status}, but its failureReason names a step that presupposes a "
            f"fetched image ({arm.get('step_why')}), so the fetch itself worked: "
            f"{(arm.get('failure_reason') or '')[:200]}")

    # A RESPONSE THAT NEVER ARRIVED NAMES NO STEP. Checked before any marker, and structurally
    # rather than on the message text, because the text of a client-side failure is written by
    # botocore and describes the endpoint it gave up on — it can contain any word at all, including
    # words that legitimately appear in a service's own pull diagnostics.
    #
    # Measured 2026-08-14: all three arms hung for 70082/70077/70073 ms with `http_status` None, no
    # request id and no error code, and the old code labelled every one of them `pull_failed`
    # because the string contained "timeout". The identical durations are the proof that nothing
    # about any image was being observed: three differently-routed runtimes do not agree to 9 ms.
    #
    # `public.ecr.aws/nginx/nginx:stable` makes this the EXPECTED shape on a SUCCESSFUL pull, which
    # is what makes the old label so dangerous: nginx binds :80, AgentCore's contract is :8080, so a
    # fetched and running container also never answers, and the platform reports that by saying
    # nothing rather than by returning a `failureReason`. The label was therefore most likely wrong
    # on precisely the arm the seal needs to be right about.
    if inv and not inv.get("ok") and inv.get("http_status") is None \
            and not inv.get("request_id"):
        return "ambiguous", (
            f"the invoke never received an HTTP response at all (no status, no request id, "
            f"{(inv.get('duration_ms') or 0) / 1000:.1f}s), so it cannot name the fetch or any "
            f"other step. With this image a successful pull produces the same silence as a failed "
            f"one — nginx serves :80 and AgentCore's contract is :8080 — so this arm does not "
            f"distinguish a fetched image from an unfetched one: "
            f"{(inv.get('error_message') or '')[:160]}")

    # Channel 2: the create reached READY, which the diagnostic warned may precede the fetch. The
    # invoke is then the only place the fetch is observable.
    if status == "READY":
        if inv.get("ok"):
            return "pull_succeeded", (
                "the create reached READY and the invoke was answered, which cannot happen unless "
                "the image was fetched and started")
        if ilabel == "post_pull":
            return "pull_succeeded", (
                f"the create reached READY and the invoke failed at a step that presupposes a "
                f"running container ({inv.get('step_why')}), which is the expected shape for this "
                f"image: it serves :80 and AgentCore's contract is :8080")
        if ilabel == "pull":
            return "pull_failed", (
                f"the create reached READY but the invoke failed naming the fetch "
                f"({inv.get('step_why')}) — i.e. READY was reached before the image was pulled, "
                f"which is exactly the lazy-pull hazard the diagnostic flagged: "
                f"{(inv.get('error_message') or inv.get('body') or '')[:200]}")
        return "ambiguous", (
            f"the create reached READY and the invoke produced {ilabel!r} "
            f"({(inv.get('error_code') or '')}: "
            f"{(inv.get('error_message') or inv.get('body') or '')[:200]}), which does not "
            f"distinguish a fetched image from an unfetched one")

    if status in ("CREATE_FAILED", "UPDATE_FAILED"):
        return "ambiguous", (
            f"the create settled {status} but its failureReason matched no marker in either list "
            f"({arm.get('step_why')}): {(arm.get('failure_reason') or '')[:200]}")
    return "ambiguous", (
        f"the create never reached a terminal status within {POLL_TIMEOUT}s (last seen "
        f"{status or 'nothing'}), so nothing about the fetch was observed")


# ---------------------------------------------------------------------------- teardown

def teardown(ec2, ac, iam, store, state, net: dict, role_name: str,
             arms_created: list[str], report: dict) -> dict:
    """Delete everything, in the order the docstring gives, by ledger-read ids only.

    Every step is best-effort and none aborts the rest: a failed IGW detach must not leave the NAT
    gateway billing. The one thing that DOES abort is `guard()`, because a destructive call aimed at
    the wrong id is not a step that can be retried past.
    """
    deleted: list[str] = []
    failed: list[dict] = []

    def _del(kind: str, logical: str, op: str, client, *, ok_codes=(), **extra) -> None:
        entry = state.find(kind, logical)
        if entry is None:
            return
        params = dict(entry.delete_params or {})
        if not params:
            state.drop(kind, logical)
            state.write()
            return
        guard(*[v for v in params.values() if isinstance(v, str)])
        params.update(extra)
        d = capture(store, op, client, **params)
        if d.ok or (d.error_code in ok_codes):
            deleted.append(f"{kind}/{logical}")
            state.drop(kind, logical)
            state.write()
        else:
            failed.append({"resource": f"{kind}/{logical}", "params": params,
                           "error": f"{d.error_code}: {d.error_message}"})

    print("  teardown")

    # 1. the runtimes. They hold ENIs in the private subnet.
    for arm in arms_created:
        if not delete_runtime(ac, store, state, arm):
            failed.append({"resource": f"agent-runtime/{arm}", "error": "delete_agent_runtime"})

    # 2. the ENIs, POLLED and not assumed. A subnet with a dependent ENI refuses to delete, and the
    #    refusal (`DependencyViolation`) reads like a propagation delay, so a script that did not
    #    wait here would appear to have leaked a subnet for a reason it could not name. This is a
    #    DESCRIBE with a filter, which is allowed — the ban on describe-filters is on the DELETES.
    if net.get("subnet_private"):
        def eni_count() -> str:
            r = capture(store, "describe_network_interfaces", ec2,
                        Filters=[{"Name": "subnet-id", "Values": [net["subnet_private"]]}])
            return str(len((r.response or {}).get("NetworkInterfaces") or []))
        left, secs = _wait(eni_count, {"0"}, ENI_CLEAR_TIMEOUT, ENI_POLL_SECONDS, "enis")
        report["eni_clear_seconds"] = secs
        report["eni_left_in_private_subnet"] = left
        print(f"    private-subnet ENIs: {left} after {secs}s")
        if left != "0":
            # Delete the leftovers by id, each one re-checked to be IN OUR OWN SUBNET before the
            # call. The id comes from a describe, which is the one place this script has to, so the
            # guard is doubled: our subnet AND our vpc, then the deny-list.
            r = capture(store, "describe_network_interfaces", ec2,
                        Filters=[{"Name": "subnet-id", "Values": [net["subnet_private"]]}])
            for eni in (r.response or {}).get("NetworkInterfaces") or []:
                if eni.get("SubnetId") != net["subnet_private"] or eni.get("VpcId") != net["vpc_id"]:
                    raise GuardTripped(
                        f"describe_network_interfaces returned {eni.get('NetworkInterfaceId')} in "
                        f"subnet {eni.get('SubnetId')} / vpc {eni.get('VpcId')}, which is not this "
                        f"run's. Refusing to delete anything from this list.")
                guard(eni.get("SubnetId", ""), eni.get("VpcId", ""))
                d = capture(store, "delete_network_interface", ec2,
                            NetworkInterfaceId=eni["NetworkInterfaceId"])
                if not d.ok:
                    failed.append({"resource": f"eni/{eni['NetworkInterfaceId']}",
                                   "error": f"{d.error_code}: {d.error_message}"})

    # 3. the mutation route, if the restore below did not already remove it.
    _del("ec2-route", "f57b_nat_route", "delete_route", ec2,
         ok_codes=("InvalidRoute.NotFound",))

    # 4. route-table associations, then the tables.
    for label in ("public", "private"):
        _del("ec2-rtb-assoc", f"f57b_assoc_{label}", "disassociate_route_table", ec2,
             ok_codes=("InvalidAssociationID.NotFound",))
    for label in ("public", "private"):
        _del("ec2-rtb", f"f57b_rtb_{label}", "delete_route_table", ec2,
             ok_codes=("InvalidRouteTableID.NotFound",))

    # 5. the NAT gateway, polled to `deleted`. The EIP cannot be released before it is, and this is
    #    the only resource in the run that bills hourly.
    _del("ec2-natgw", "f57b_natgw", "delete_nat_gateway", ec2,
         ok_codes=("NatGatewayNotFound",))
    if net.get("nat_id"):
        def nat_state() -> str:
            r = capture(store, "describe_nat_gateways", ec2, NatGatewayIds=[net["nat_id"]])
            gws = ((r.response or {}).get("NatGateways") or [{}])
            return str(gws[0].get("State") or "")
        st, secs = _wait(nat_state, {"deleted"}, NAT_DELETED_TIMEOUT, NAT_POLL_SECONDS, "natgw")
        report["nat_delete_state"] = st
        report["nat_delete_seconds"] = secs
        print(f"    nat gateway {st} after {secs}s")
        if st != "deleted":
            failed.append({"resource": "ec2-natgw/f57b_natgw",
                           "error": f"reached {st!r} rather than deleted after {secs}s — IT IS "
                                    f"STILL BILLING"})

    # 6. the EIP.
    _del("ec2-eip", "f57b_eip", "release_address", ec2,
         ok_codes=("InvalidAllocationID.NotFound",))

    # 7. the IGW: detach, then delete. Detached by the vpc id recorded in `ids`, not re-derived.
    igw = state.find("ec2-igw", "f57b_igw")
    if igw is not None:
        gid = (igw.ids or {}).get("InternetGatewayId", "")
        vid = (igw.ids or {}).get("detach_vpc_id", "")
        if gid and vid:
            guard(gid, vid)
            dt = capture(store, "detach_internet_gateway", ec2,
                         InternetGatewayId=gid, VpcId=vid)
            if not dt.ok and dt.error_code not in ("Gateway.NotAttached",
                                                   "InvalidInternetGatewayID.NotFound"):
                failed.append({"resource": "ec2-igw/detach",
                               "error": f"{dt.error_code}: {dt.error_message}"})
    _del("ec2-igw", "f57b_igw", "delete_internet_gateway", ec2,
         ok_codes=("InvalidInternetGatewayID.NotFound",))

    # 8. security group, subnets, vpc.
    _del("ec2-sg", "f57b_sg", "delete_security_group", ec2,
         ok_codes=("InvalidGroup.NotFound",))
    for label in ("private", "public"):
        _del("ec2-subnet", f"f57b_subnet_{label}", "delete_subnet", ec2,
             ok_codes=("InvalidSubnetID.NotFound",))
    _del("ec2-vpc", "f57b_vpc", "delete_vpc", ec2, ok_codes=("InvalidVpcID.NotFound",))

    # 9. the role, inline policy first.
    if state.find("iam-role", "f57b_runtime_exec") is not None:
        p = capture(store, "delete_role_policy", iam, RoleName=role_name,
                    PolicyName="grx-runtime-vpcegress")
        time.sleep(INTER_IAM_S)
        r = capture(store, "delete_role", iam, RoleName=role_name)
        if r.ok or r.error_code == "NoSuchEntity":
            deleted.append("iam-role/f57b_runtime_exec")
            state.drop("iam-role", "f57b_runtime_exec")
            state.write()
        else:
            failed.append({"resource": "iam-role/f57b_runtime_exec",
                           "error": f"{p.error_code or ''} / {r.error_code}: {r.error_message}"})

    residue = {
        "deleted": deleted,
        "not_deleted": failed,
        "back_to_baseline": not failed,
        "note": ("Everything this case created is created and deleted here. The NAT gateway is the "
                 "only item that would keep billing, so its delete is polled to state `deleted` "
                 "rather than trusted to return 200 — the restore_verification discipline applied "
                 "to a teardown."),
    }
    print(f"    deleted {len(deleted)}"
          f"{(', FAILED ' + str(len(failed))) if failed else ''}")
    return residue


# ---------------------------------------------------------------------------- main

def decide(arms: dict, report: dict, *, mutation_restored: bool) -> dict:
    """Score the three arms against the seal. Pure: no AWS, no clock, no filesystem, no `state`.

    Split out of `main()` on 2026-08-14, and the reason is worth recording because it is the whole
    justification for this function existing. The first live run of this case mislabelled a
    client-side socket timeout as a failed image pull (see the comment on `PULL_MARKERS`). Fixing
    the instrument means the archived arms have to be RE-SCORED — and re-scoring them by
    transcribing this branch table into a one-off script would put the published `record.reason`
    one careless edit away from disagreeing with what the producer itself would have written. A
    rederived result whose reason string is a paraphrase is worse than no rederive at all, because
    the file still looks like the producer's own output.

    So both paths call this. What is deliberately NOT shared:
    `f5_redteam/tests/test_vpc_egress_image_pull.py::_score` still states the intended table
    independently, and it is still independent for the reason its own docstring gives — a change
    here shows up as a disagreement rather than as both sides moving together.

    `mutation_restored` is passed rather than read out of `report` because the two are different
    facts: `report['default_route_gone']` is the RE-VERIFICATION (the blocking assertion, re-run
    after the restore) and `mutation_restored` is whether the restoring API call was made at all.
    PREREGISTRATION.yaml's `restore_verification` rule names F5-7b precisely because the second
    does not imply the first.
    """
    ev = {name: pull_evidence(arm) for name, arm in arms.items()}

    a = ev.get(ARM_NO_ROUTE, ("missing", "the arm did not run"))
    b = ev.get(ARM_WITH_ROUTE, ("missing", "the arm did not run"))
    c = ev.get(ARM_RESTORED, ("missing", "the arm did not run"))

    signatures = {name: {"create": arm_signature(arm), "invoke": invoke_signature(arm)}
                  for name, arm in arms.items()}

    restore_holds = mutation_restored and bool(report.get("default_route_gone")) and c[0] == a[0]

    verdict_reading = ""
    if a[0] == "missing" or b[0] == "missing":
        record = O.not_measured(
            CASE, f"an arm did not run: {ARM_NO_ROUTE}={a[0]}, {ARM_WITH_ROUTE}={b[0]}",
            arms=arms, evidence=ev, signatures=signatures, report=report)
    elif "ambiguous" in (a[0], b[0]):
        # The instrument branch, and it is a real answer rather than a shrug. The oracle asks a
        # question about the PULL; an arm that reached a terminal state whose channels do not
        # distinguish a fetched image from an unfetched one has not answered it, and calling that
        # FALSE is precisely the error F1-15 published for 24 minutes.
        record = O.not_measured(
            CASE,
            f"neither channel distinguished the fetch on at least one arm "
            f"({ARM_NO_ROUTE}={a[0]}, {ARM_WITH_ROUTE}={b[0]}). The oracle is denominated in the "
            f"image pull, and an observation that does not locate the pull cannot answer it in "
            f"either direction.",
            arms=arms, evidence=ev, signatures=signatures, report=report,
            why_no_route=a[1], why_with_route=b[1])
    elif not restore_holds:
        record = O.not_measured(
            CASE,
            f"the mutation's inverse was not verified: restored={mutation_restored}, "
            f"default_route_gone={report.get('default_route_gone')}, "
            f"{ARM_RESTORED}={c[0]} against {ARM_NO_ROUTE}={a[0]}. PREREGISTRATION.yaml's "
            f"restore_verification rule names F5-7b, and a mutation whose inverse is not "
            f"re-verified leaves every reading in this run standing on an unchecked premise.",
            arms=arms, evidence=ev, signatures=signatures, report=report)
    elif (a[0], b[0]) not in (("pull_failed", "pull_succeeded"),
                             ("pull_succeeded", "pull_succeeded")):
        # The oracle offers exactly two decidable shapes: the fetch fails without the route and
        # succeeds with it (TRUE), or "egress is reachable either way" (FALSE). Two other pairs are
        # arithmetically possible and neither is either verdict:
        #
        #   (pull_failed, pull_failed)     the route made no difference and NEITHER arm fetched.
        #                                  That is not "reachable either way" — it is UNreachable
        #                                  either way, which the seal does not name, and which
        #                                  points at the fixture rather than at the platform.
        #   (pull_succeeded, pull_failed)  fetching worked WITHOUT the route and failed WITH it.
        #                                  Incoherent as a statement about egress; something other
        #                                  than the route changed between the arms.
        #
        # Both would fall through a bare `observed = (a and b)` into a published FALSE, because
        # `not TRUE` and `FALSE` are the same boolean and different claims. The seal's FALSE is a
        # positive assertion about someone else's product and it does not get made by default.
        record = O.not_measured(
            CASE,
            f"the arms produced a pair the oracle does not name: {ARM_NO_ROUTE}={a[0]}, "
            f"{ARM_WITH_ROUTE}={b[0]}. The seal decides between 'fails without a route and "
            f"succeeds with one' and 'egress is reachable either way'; this is neither, so it is "
            f"reported rather than rounded to the nearer verdict.",
            arms=arms, evidence=ev, signatures=signatures, report=report,
            why_no_route=a[1], why_with_route=b[1])
    else:
        observed = (a[0] == "pull_failed" and b[0] == "pull_succeeded")
        verdict_reading = (
            f"TRUE: without a default route out of the private subnet the image fetch failed, and "
            f"with one it succeeded, over the same image and the same runtime shape. "
            f"{ARM_NO_ROUTE}: {a[1]} // {ARM_WITH_ROUTE}: {b[1]}"
            if observed else
            f"FALSE: the image fetch SUCCEEDED on both arms, so the private subnet reached the "
            f"registry with no default route at all — the oracle's 'egress is reachable either "
            f"way'. {ARM_NO_ROUTE}: {a[1]} // {ARM_WITH_ROUTE}: {b[1]}")
        obs = P.obs_existence(
            CASE, observed, n=1,
            reading=verdict_reading,
            arm_no_route=a[0], arm_with_route=b[0], arm_restored=c[0],
            channels_measured=["create_terminal_status", "invoke_agent_runtime"],
            union_arm="containerConfiguration (public.ecr.aws image) — NOT the code artifact, "
                      "because a code artifact pulls no image and this oracle is denominated in "
                      "the pull")
        # Set as an ATTRIBUTE, not passed as `**detail`. F5-7b is a mandatory-mutation case, so
        # `evaluate` downgrades a clean TRUE to INCONCLUSIVE unless `mutation_inverted` is True —
        # and `**detail` keys land where the decision rule never looks. This line replaces a
        # `restore_reverified=restore_holds` keyword that did exactly that: it was not an
        # `Observation` field, so `phase1._detail`'s guard could not fire on it (that guard rejects
        # *misplaced field names*, and this was a name the dataclass has never had), the field kept
        # its default of None, and the case could not have published TRUE or FALSE on any input.
        # `lib/phase1.py:_detail` records F5-1 shipping the same defect with the right spelling in
        # the wrong place; this was the same defect with the wrong spelling. Caught by
        # `test_decide_agrees_with_the_independently_stated_table`, which only became possible to
        # write once the branch table moved out of `main()` — before that, the TRUE branch was
        # unreachable without building a VPC, so nothing ever evaluated it.
        #
        # `restore_holds` rather than the literal True: this branch is only reached when it is
        # already True (see `elif not restore_holds` above), and writing the variable keeps the
        # oracle's field tied to the value that gated it instead of asserting it a second time.
        obs.mutation_inverted = restore_holds
        record = O.evaluate(obs)

    return {"record": record, "evidence": ev, "signatures": signatures,
            "restore_holds": restore_holds, "verdict_reading": verdict_reading,
            "labels": {ARM_NO_ROUTE: a, ARM_WITH_ROUTE: b, ARM_RESTORED: c}}


def main(argv: list[str] | None = None) -> int:                       # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            ((ARM_NO_ROUTE,
              "one VPC-mode runtime in a private subnet whose route table carries ONLY the local "
              "route. Both channels measured: create-time terminal status with failureReason, and "
              "an actual InvokeAgentRuntime", 1),
             (ARM_WITH_ROUTE,
              "MANDATORY MUTATION: 0.0.0.0/0 -> the NAT gateway, added to the private route table. "
              "A SECOND runtime, so the pull happens with the route already in place; a runtime "
              "created before the route would confound a lazy pull with a re-pull", 1),
             (ARM_RESTORED,
              "the route deleted and a THIRD runtime created, per PREREGISTRATION.yaml's "
              "restore_verification rule: restore, then RE-RUN the blocking assertion. A restore "
              "is not assumed to have worked because DeleteRoute returned 200", 1)),
            # Sums to the arm plan total, which is what `dry_run_banner` checks and what it is right
            # to check: a breakdown that also counted the ~30 EC2 fixture calls would be a second,
            # larger denominator sitting beside the measured one. The fixture is described in
            # `extra` instead, where it cannot be mistaken for a trial count.
            operations={"bedrock-agentcore:CreateAgentRuntime then InvokeAgentRuntime, "
                        "one runtime per arm": 3},
            mutations=2,
            billable=False,
            text_units=0,
            text_units_why=("no model, no guardrail and no ApplyGuardrail: this case is about "
                            "whether a network route gates an image fetch"),
            extra=(
                f"image: {IMAGE} — public, multi-arch, measured by diag_vpc_runtime.py to pull and "
                f"reach READY in PUBLIC mode. It serves :80 and NOT AgentCore's :8080 contract, "
                f"which is acceptable because the comparison is differential",
                f"network: {VPC_CIDR} with a public subnet ({PUBLIC_CIDR}) holding a NAT gateway "
                f"and a private subnet ({PRIVATE_CIDR}) holding the runtime's ENIs. Built and "
                f"destroyed by this script; nothing touches the runner's own VPC",
                f"cost: one NAT gateway at ~$0.045/h. It is ledgered before it is created and its "
                f"delete is polled to state `deleted`",
                f"guards: a hard deny-list of the runner's own vpc/subnet/sg ids asserted before "
                f"every destructive EC2 call, and every delete addressed by a ledger-read id",
            ))

    if not O.mutation_is_mandatory(CASE):
        raise SystemExit(
            f"{CASE} is no longer sealed with a mandatory mutation arm, but this script implements "
            f"one and reports `mutations: 2`. Read the seal before running it.")

    # The default ledger and the default evidence root, with no `--state` / `--evidence-root`
    # overrides. Case 11 offers both because it hand-rolls its own ArgumentParser; this case uses
    # `P.parser`, which defines exactly four flags (dry_run, n, region, run_id) — so reading
    # `args.state` here raised AttributeError at RUNTIME and never under `--dry-run`, because the
    # read sits below the banner's return. `claims/tests/test_parser_attrs.py` caught it before the
    # live run. The overrides bought nothing anyway: this case has one ledger and one evidence tree.
    state = T.State.load()
    run_id = state.run_id
    if state.region != args.region:
        raise SystemExit(f"ledger is for {state.region}, not {args.region}")

    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()

    fc = A.factory(args.region)
    account = A.account_id(fc)
    ec2 = fc.client("ec2")
    iam = fc.client("iam")
    ac = fc.client("bedrock-agentcore-control")
    rt = fc.client("bedrock-agentcore")

    short = run_id.lower().replace("-", "").replace("_", "")
    role_name = f"grx-runtime-vpcegress-{run_id}"

    print(f"{CASE} — run_id={run_id}, region={args.region}")
    print(f"  oracle: {O.oracle_text(CASE)}\n")

    net: dict = {}
    role_arn = ""
    arms: dict[str, dict] = {}
    arms_created: list[str] = []
    report: dict = {}
    residue: dict = {}
    mutation_applied = False
    mutation_restored = False

    # Before the try block, and before anything is created: if the deny-list cannot be built there
    # is nothing to tear down yet, so raising here leaks no resource. Inside the try it would enter
    # teardown — which itself calls `guard()` — and the first thing teardown did would be to raise.
    resolve_forbidden(ec2, store)

    try:
        azs = capture(store, "describe_availability_zones", ec2).raise_for_status()
        az = next(z["ZoneName"] for z in (azs.response or {}).get("AvailabilityZones", [])
                  if z.get("State") == "available")
        print(f"  az: {az}")

        net = build_network(ec2, store, state, run_id, state.expires_at, az)
        report["network"] = {k: v for k, v in net.items()}

        role_arn = make_role(iam, store, role_name, account, run_id, state.expires_at, state)
        print(f"  role: {role_name}")
        # A WAIT and not a retry loop: a retry would also swallow a genuine trust-policy error and
        # spend the timeout proving that VPC mode does not work when the defect is one line of JSON.
        time.sleep(TRUST_SETTLE_S)

        # ---- arm A: no route out of the private subnet -------------------------
        print(f"\n  --- {ARM_NO_ROUTE}: private route table carries only the local route")
        arms_created.append(ARM_NO_ROUTE)
        arms[ARM_NO_ROUTE] = runtime_arm(
            ac, rt, store, state, arm=ARM_NO_ROUTE, name=f"grx_f57b_noroute_{short}"[:48],
            role_arn=role_arn, net=net, run_id=run_id, expires_at=state.expires_at)
        # Deleted now rather than at teardown, so exactly one runtime is ever attached to the
        # private subnet. Two runtimes sharing it would not change the routing, but they would make
        # the ENI wait at teardown ambiguous about which arm was slow to release.
        delete_runtime(ac, store, state, ARM_NO_ROUTE)
        arms_created.remove(ARM_NO_ROUTE)

        # ---- THE MUTATION ------------------------------------------------------
        print(f"\n  MUTATION: 0.0.0.0/0 -> {net['nat_id']} in {net['rtb_private']}")
        state.record(T.Resource(
            kind="ec2-route", logical="f57b_nat_route", name="0.0.0.0/0->natgw", service="ec2",
            delete_op="delete_route",
            delete_params={"RouteTableId": net["rtb_private"],
                           "DestinationCidrBlock": "0.0.0.0/0"},
            delete_priority=30,
            ids={"RouteTableId": net["rtb_private"], "case": CASE},
            notes=("F5-7b's MANDATORY MUTATION: the default route out of the private subnet. Its "
                   "inverse is a DeleteRoute, and the seal requires the inverse to be applied and "
                   "the blocking assertion re-run.")))
        state.write()
        capture(store, "create_route", ec2, RouteTableId=net["rtb_private"],
                DestinationCidrBlock="0.0.0.0/0",
                NatGatewayId=net["nat_id"]).raise_for_status()
        mutation_applied = True
        time.sleep(ROUTE_SETTLE_S)

        # ---- arm B: the same thing, one route later -----------------------------
        print(f"\n  --- {ARM_WITH_ROUTE}: the same runtime shape, with the NAT route in place")
        arms_created.append(ARM_WITH_ROUTE)
        arms[ARM_WITH_ROUTE] = runtime_arm(
            ac, rt, store, state, arm=ARM_WITH_ROUTE, name=f"grx_f57b_route_{short}"[:48],
            role_arn=role_arn, net=net, run_id=run_id, expires_at=state.expires_at)
        delete_runtime(ac, store, state, ARM_WITH_ROUTE)
        arms_created.remove(ARM_WITH_ROUTE)

        # ---- THE INVERSE, AND THE RE-VERIFICATION -------------------------------
        # PREREGISTRATION.yaml `restore_verification`, whose applies_to names F5-7b: "After every
        # mutation: restore, then RE-RUN the blocking assertion. A restore is not assumed to have
        # worked because the API call returned 200."
        print(f"\n  RESTORE: deleting the route")
        guard(net["rtb_private"])
        dr = capture(store, "delete_route", ec2, RouteTableId=net["rtb_private"],
                     DestinationCidrBlock="0.0.0.0/0")
        if dr.ok or dr.error_code == "InvalidRoute.NotFound":
            mutation_restored = True
            state.drop("ec2-route", "f57b_nat_route")
            state.write()
        else:
            report["restore_error"] = f"{dr.error_code}: {dr.error_message}"
        # The route table is read back rather than trusted, which is the first half of the rule.
        rtb = capture(store, "describe_route_tables", ec2, RouteTableIds=[net["rtb_private"]])
        routes = (((rtb.response or {}).get("RouteTables") or [{}])[0].get("Routes") or [])
        report["private_routes_after_restore"] = [
            {k: v for k, v in r.items() if k in ("DestinationCidrBlock", "GatewayId",
                                                 "NatGatewayId", "State")} for r in routes]
        report["default_route_gone"] = not any(
            r.get("DestinationCidrBlock") == "0.0.0.0/0" for r in routes)
        print(f"    default route gone: {report['default_route_gone']}")
        time.sleep(ROUTE_SETTLE_S)

        print(f"\n  --- {ARM_RESTORED}: the blocking assertion, re-run after the restore")
        arms_created.append(ARM_RESTORED)
        arms[ARM_RESTORED] = runtime_arm(
            ac, rt, store, state, arm=ARM_RESTORED, name=f"grx_f57b_restored_{short}"[:48],
            role_arn=role_arn, net=net, run_id=run_id, expires_at=state.expires_at)
        delete_runtime(ac, store, state, ARM_RESTORED)
        arms_created.remove(ARM_RESTORED)

    finally:
        residue = teardown(ec2, ac, iam, store, state, net, role_name, arms_created, report)

    # ---- the verdict --------------------------------------------------------
    # The branch table lives in `decide()` so that a rederive over archived arms runs the identical
    # code rather than a transcription of it; see that function's docstring.
    scored = decide(arms, report, mutation_restored=mutation_restored)
    ev = scored["evidence"]
    for name, (label, why) in ev.items():
        print(f"\n  {name}: {label}\n    {why}")

    signatures = scored["signatures"]
    restore_holds = scored["restore_holds"]
    record = scored["record"]
    verdict_reading = scored["verdict_reading"]

    payload = {
        "run_id": run_id,
        "region": args.region,
        "instrument": (
            f"A VPC built for this case alone: {VPC_CIDR}, a public subnet holding a NAT gateway "
            f"and a private subnet holding the runtime's ENIs, each subnet on its own explicitly "
            f"associated route table. Three VPC-mode AgentCore Runtimes created in sequence from "
            f"the same public image ({IMAGE}) and the same execution role, differing only in "
            f"whether the private route table carried 0.0.0.0/0 -> the NAT gateway. Every arm "
            f"measured on BOTH channels: the create-time terminal status with its failureReason, "
            f"and an actual InvokeAgentRuntime."),
        "arms": arms,
        "pull_evidence": {k: {"label": v[0], "why": v[1]} for k, v in ev.items()},
        "signatures": signatures,
        "network_and_restore": report,
        "mutation": {
            "applied": mutation_applied,
            "restored": mutation_restored,
            "inverse_reverified": restore_holds,
            "what": "ec2:CreateRoute 0.0.0.0/0 -> the NAT gateway on the private route table, and "
                    "its inverse ec2:DeleteRoute",
            "rule": "PREREGISTRATION.yaml restore_verification, whose applies_to names F5-7b: "
                    "restore, then RE-RUN the blocking assertion",
        },
        "residue": residue,
        "verdict_rule": O.oracle_text(CASE),
        "verdict_reading": verdict_reading or "see `record.reason`",
        "what_true_does_not_prove": [
            "that the runtime WORKS in a VPC — the image serves :80 and AgentCore's contract is "
            "POST /invocations and GET /ping on :8080, so no arm here produced a functioning "
            "runtime and none was needed: the comparison is differential",
            "that a NAT gateway is the only way to supply the route — a VPC endpoint or an "
            "internet gateway on the private subnet would also carry the fetch, and this case "
            "measured one arrangement rather than enumerating them",
            "anything about a CONTAINER image held in a private ECR repository, which needs an "
            "additional grant and, in a VPC with no route, an endpoint of its own",
            "that the pull is the FIRST thing to fail without egress — it is the thing the seal "
            "names, and other steps may also fail; the arms are labelled by which step the service "
            "itself named, not by which step failed earliest",
        ],
        "why_this_matters_operationally": (
            "The document's VPC guidance tells a reader that a private-subnet runtime needs a NAT "
            "route or an equivalent, which is advice with a cost attached: a NAT gateway bills "
            "hourly. Whether it is actually REQUIRED, and what the failure looks like when it is "
            "absent, is the difference between provisioning one on evidence and provisioning one "
            "on caution."),
        "limitations": [
            "one Region, one AZ, one image, one arm per condition — planned_n is None for this "
            "case, so n=1 is the pre-registered denominator and not a shortfall",
            "the private subnet had no VPC endpoints at all, so this measures the absence of ANY "
            "egress path and not the absence of a NAT gateway specifically",
            "single calendar day: under PREREGISTRATION.yaml's reproduction_before_amendment rule "
            "a day-2 replication is required before the document is amended on this result",
        ],
        "billable_calls": 0,
        "mutations": 2,
        "expiry": state.expires_at,
    }

    register_own_ids(state, residue)
    P.emit(CASE, record, payload, store)
    if not residue.get("back_to_baseline"):
        print(f"  WARNING: residue did not return to baseline; see results/phase1/{CASE}.json "
              f"-> residue.not_deleted")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
