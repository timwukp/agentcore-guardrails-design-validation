#!/usr/bin/env python3
"""F5-3a — Route 4: SCP authoring, and the propagation instrument that turns out not to exist.

SEALED ORACLE (claims/triage_rules.py, kind EXISTENCE, planned_n=None, alpha=0.05):

    TRUE if DescribeEffectivePolicy shows the deny on a fresh child OU with a break-glass
    exception; FALSE if the policy does not propagate

Method, from the same seal: "fresh child OU + SCP; enforcement from inside a member account is
F5-3c".

THE HEADLINE: THE PRE-REGISTERED INSTRUMENT DOES NOT COVER SCPs

`DescribeEffectivePolicy`'s `PolicyType` parameter is typed by the `EffectivePolicyType` enum, and
in botocore 1.43.67 that enum has eleven members:

    TAG_POLICY, BACKUP_POLICY, AISERVICES_OPT_OUT_POLICY, CHATBOT_POLICY, DECLARATIVE_POLICY_EC2,
    SECURITYHUB_POLICY, INSPECTOR_POLICY, UPGRADE_ROLLOUT_POLICY, BEDROCK_POLICY, S3_POLICY,
    NETWORK_SECURITY_DIRECTOR_POLICY

`SERVICE_CONTROL_POLICY` is not one of them. `CreatePolicy`'s own `PolicyType` enum has thirteen
members and DOES include it, alongside `RESOURCE_CONTROL_POLICY`. So the two enums differ by exactly
the two policy types that are *authorization* policies rather than *management* policies, and
`DescribeEffectivePolicy` covers only the management ones.

That is a structural fact about the API, not a permissions problem, a Region problem, or an
enable-the-policy-type problem. `SERVICE_CONTROL_POLICY` is `ENABLED` on this organization's root
and the caller is the management account; the operation still cannot be asked the question. The
reason is coherent: a management policy has a computable "effective" value because child settings
merge with parent settings, whereas an SCP's effect is an intersection evaluated per request per
principal per action — there is no single document that is "the effective SCP".

So the sealed oracle's condition cannot be evaluated, and this script does NOT manufacture a verdict
by swapping in a different call. Substituting `ListPoliciesForTarget` and calling it
`DescribeEffectivePolicy` would answer a different question — attachment and inheritance STRUCTURE
rather than evaluated effect — while wearing the sealed oracle's name.

WHAT THIS SCRIPT THEREFORE DOES: THREE THINGS, LABELLED SEPARATELY

  1. THE SHAPE FINDING, derived from the shipped service model with no AWS call. Both enums are
     read out of botocore and their difference is computed, so the finding is reproducible by anyone
     with the same SDK pinned and does not depend on our account at all.

  2. THE SERVICE'S OWN VERDICT, because a client-side enum is a statement about the SDK and not
     about AWS. botocore does not validate enum VALUES client-side, so the request goes out and the
     service answers. Its error code and message are recorded. If the service were to accept
     `SERVICE_CONTROL_POLICY` despite the enum, that would be the more interesting outcome and this
     arm is what would find it.

  3. THE AUTHORING HALF, which IS executable and is half the sealed case's own title ("Route 4: SCP
     authoring and propagation"). A real SCP is created carrying a deny on the Route 4 action with a
     break-glass exception, attached to a fresh EMPTY child OU, and its attachment and inheritance
     to a nested child are read back with `ListPoliciesForTarget`. This is recorded as an UNPLANNED
     mechanism observation in the shape F1-11 established — it consumes no alpha, carries no
     pre-registered verdict, and is labelled as structure rather than effect.

WHY THE OU IS EMPTY, AND WHY THAT IS NOT A WEAKNESS HERE

An SCP attached to an OU containing accounts changes what principals in those accounts may do. This
account is the management account of an organization whose two existing OUs (`production`, `DevOps`)
carry real workloads. A fresh EMPTY OU has no member accounts, so no principal anywhere can be
affected by the deny no matter what it says — and because the sealed method explicitly assigns
"enforcement from inside a member account" to the separate case F5-3c, the empty OU is not a
compromise. It is the correct subject for the half of the question this case owns. (An SCP also does
not apply to the management account itself even when attached above it, which is a second reason
this cannot reach into live traffic.)

WHAT IS NEVER TOUCHED: the OUs `production` and `DevOps`, and the policies `FullAWSAccess`,
`devOpsOnly`, `productionOnly`. The script asserts the pre-existing inventory before it creates
anything and asserts it again after teardown, so a stray attach or delete is caught rather than
assumed absent.

TEARDOWN ORDER MATTERS AND IS NOT SYMMETRIC WITH CREATION

Creation is OU -> nested OU -> policy -> attach. Teardown must be detach -> delete policy -> delete
nested OU -> delete OU, because a policy cannot be deleted while attached and an OU cannot be
deleted while it has children. A `finally` that ran the creation order backwards would fail on the
first step and strand everything after it, so the order is explicit and each step's failure is
recorded per-object rather than aborting the sweep.

EXIT CODES follow the repo convention: rc reports whether the test RAN, never whether the document
was right. rc=0 the arms ran and the organization is verified back to its pre-run inventory; rc=2
nothing was measured OR residue survived (an OU or policy left behind, or the inventory changed);
rc=1 unclassified.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                                # noqa: E402
import oracle as O                                                    # noqa: E402
import phase1 as P                                                    # noqa: E402
import testbed as T                                                   # noqa: E402
from evidence import EvidenceStore, capture                           # noqa: E402

FAMILY = "f5_redteam"
CASE = "F5-3a"

SCP = "SERVICE_CONTROL_POLICY"

# The Route 4 action the document's §4.4 names. Denying it is the point of the SCP; the break-glass
# exception is what the sealed oracle asks to see alongside it.
ROUTE4_ACTIONS = ("bedrock-agentcore:UpdateGateway", "bedrock-agentcore:UpdateGatewayTarget")

# Names of organization objects this script may create. Anything NOT matching this prefix is
# somebody else's and is never created, attached, detached or deleted by this file.
OWNED_PREFIX = "grx-f53a-"

# Asserted before and after. A run that changes this inventory has reached outside its own objects.
PROTECTED_OU_NAMES = ("production", "DevOps")
PROTECTED_POLICY_NAMES = ("FullAWSAccess", "devOpsOnly", "productionOnly")


# ---------------------------------------------------------------------------
# 1. the shape finding, from the shipped model, with no AWS call
# ---------------------------------------------------------------------------

def shape_finding() -> dict[str, Any]:
    """Read both enums out of botocore and compute their difference.

    Derived rather than typed: a hand-written list of eleven strings in this file would be prose,
    and prose is not verified. If a future SDK adds SERVICE_CONTROL_POLICY to the effective-policy
    enum, this function reports it and the sealed oracle becomes executable — which is exactly the
    condition the payload's `expiry` is about.
    """
    sm = A.service_model("organizations")
    eff = sm.operation_model("DescribeEffectivePolicy").input_shape.members["PolicyType"]
    create = sm.operation_model("CreatePolicy").input_shape.members["Type"]
    eff_enum = list(eff.enum or [])
    create_enum = list(create.enum or [])
    missing = [t for t in create_enum if t not in eff_enum]
    return {
        "sdk": A.sdk_versions(),
        "describe_effective_policy_enum": eff_enum,
        "create_policy_enum": create_enum,
        "in_create_but_not_in_describe_effective": missing,
        "scp_supported_by_describe_effective_policy": SCP in eff_enum,
        "reading": (
            f"DescribeEffectivePolicy accepts {len(eff_enum)} policy types and CreatePolicy "
            f"accepts {len(create_enum)}. The difference is {missing}, i.e. exactly the "
            f"authorization policies. An SCP's effect is an intersection evaluated per request, "
            f"per principal and per action, so there is no single document that is 'the effective "
            f"SCP' for a target — which is a coherent reason for the omission rather than a gap."),
    }


# ---------------------------------------------------------------------------
# 2. the service's own verdict on the pre-registered call
# ---------------------------------------------------------------------------

def ask_the_service(org, store, lim, *, target_id: str) -> dict[str, Any]:
    """Send DescribeEffectivePolicy(PolicyType=SERVICE_CONTROL_POLICY) and record what AWS says.

    botocore does not validate enum VALUES client-side, so this request really goes out. That
    matters: the enum is a statement about the SDK, and this arm is a statement about the service.
    A client-side rejection would still be recorded, but it would be labelled as such — and the
    `client_side` flag below is how a reader tells the two apart rather than having to trust this
    docstring.
    """
    lim.wait("DescribeEffectivePolicy")
    rec = capture(store, "describe_effective_policy", org,
                  PolicyType=SCP, TargetId=target_id)
    client_side = (not rec.ok) and not rec.request_id
    return {
        "accepted": bool(rec.ok),
        "error_code": rec.error_code,
        "error_message": rec.error_message,
        "http_status": rec.http_status,
        "request_id": rec.request_id,
        "rejected_client_side_by_botocore": bool(client_side),
        "evidence": rec.path,
        "reading": (
            "a request id means the service answered; no request id on a failure means botocore "
            "refused to send it, which is a fact about the SDK and not about AWS"),
    }


# ---------------------------------------------------------------------------
# 3. the authoring half, and structural propagation
# ---------------------------------------------------------------------------

def scp_document(break_glass_arn: str) -> dict[str, Any]:
    """A deny on the Route 4 actions with a break-glass exception.

    The exception is expressed with `ArnNotLike` on `aws:PrincipalArn`: the deny applies to every
    principal EXCEPT the break-glass role. Written this way round deliberately — a `Deny` with a
    positive `ArnLike` would deny only the break-glass role, which is the exact inversion of what
    a break-glass exception means and would still create and attach cleanly.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "DenyRoute4ExceptBreakGlass",
            "Effect": "Deny",
            "Action": list(ROUTE4_ACTIONS),
            "Resource": "*",
            "Condition": {"ArnNotLike": {"aws:PrincipalArn": break_glass_arn}},
        }],
    }


def inventory(org) -> dict[str, Any]:
    """The organization's OUs under root and its SCPs, for a before/after comparison."""
    roots = org.list_roots()["Roots"]
    root = roots[0]
    ous = []
    tok = None
    while True:
        r = org.list_organizational_units_for_parent(
            ParentId=root["Id"], **({"NextToken": tok} if tok else {}))
        ous.extend(r.get("OrganizationalUnits") or [])
        tok = r.get("NextToken")
        if not tok:
            break
    pols = []
    tok = None
    while True:
        r = org.list_policies(Filter=SCP, **({"NextToken": tok} if tok else {}))
        pols.extend(r.get("Policies") or [])
        tok = r.get("NextToken")
        if not tok:
            break
    return {
        "root_id": root["Id"],
        "scp_enabled_on_root": any(
            p.get("Type") == SCP and p.get("Status") == "ENABLED"
            for p in (root.get("PolicyTypes") or [])),
        "ou_names": sorted(o["Name"] for o in ous),
        "ou_ids": sorted(o["Id"] for o in ous),
        "scp_names": sorted(p["Name"] for p in pols),
        "scp_ids": sorted(p["Id"] for p in pols),
    }


def policies_for_target(org, target_id: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    tok = None
    while True:
        r = org.list_policies_for_target(
            TargetId=target_id, Filter=SCP, **({"NextToken": tok} if tok else {}))
        out.extend({"Id": p["Id"], "Name": p["Name"]} for p in (r.get("Policies") or []))
        tok = r.get("NextToken")
        if not tok:
            break
    return out


# ---------------------------------------------------------------------------
# dry run
# ---------------------------------------------------------------------------

def _dry_run(sf: dict[str, Any]) -> int:
    print(f"{CASE} — Route 4 SCP authoring and propagation  (DRY RUN)")
    print()
    print(f"  oracle ({O.BINDINGS[CASE].kind}): {O.oracle_text(CASE)}")
    print(f"  planned_n: {O.planned_n(CASE)}   alpha: {O.alpha_for(CASE)}")
    print()
    print("  THE PRE-REGISTERED INSTRUMENT DOES NOT COVER SCPs.")
    print(f"    DescribeEffectivePolicy PolicyType enum ({len(sf['describe_effective_policy_enum'])}):")
    for t in sf["describe_effective_policy_enum"]:
        print(f"      {t}")
    print(f"    CreatePolicy Type enum has {len(sf['create_policy_enum'])}; the difference is")
    print(f"      {sf['in_create_but_not_in_describe_effective']}")
    print(f"    SERVICE_CONTROL_POLICY supported by DescribeEffectivePolicy: "
          f"{sf['scp_supported_by_describe_effective_policy']}")
    print()
    print("  so this script does NOT substitute a different call and call it the sealed oracle.")
    print("  it records three separately-labelled things:")
    print("    1  the shape finding above, derived from botocore, no AWS call")
    print("    2  the SERVICE's own answer to the pre-registered call (botocore does not validate")
    print("       enum values, so the request really goes out; a request id proves AWS answered)")
    print("    3  the AUTHORING half, which IS executable, as an UNPLANNED mechanism observation")
    print("       in F1-11's shape — no alpha, no pre-registered verdict, labelled STRUCTURE")
    print("       (attachment + inheritance via ListPoliciesForTarget) and not EFFECT")
    print()
    print("  objects created, all prefixed " + OWNED_PREFIX + ":")
    print("    fresh EMPTY child OU under root, plus a nested child OU inside it")
    print("    one SCP: Deny on " + ", ".join(ROUTE4_ACTIONS))
    print("      with a break-glass exception as ArnNotLike on aws:PrincipalArn")
    print("      (ArnNotLike, not ArnLike: the inverted form would deny ONLY the break-glass role")
    print("       and would still create and attach cleanly, so the direction is asserted)")
    print("    attached to the fresh OU only")
    print()
    print("  blast radius: the OU is EMPTY, so no principal can be affected by the deny whatever")
    print("    it says. The sealed method assigns in-account enforcement to F5-3c, so an empty OU")
    print("    is the correct subject here rather than a compromise. An SCP also never applies to")
    print("    the management account itself.")
    print(f"    never touched: OUs {PROTECTED_OU_NAMES}, policies {PROTECTED_POLICY_NAMES}")
    print("    inventory asserted before AND after; teardown is detach -> delete policy ->")
    print("    delete nested OU -> delete OU, which is NOT the reverse of creation order")
    print()
    print("  billable: no. AWS Organizations control-plane calls are free.")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{CASE} Route 4 SCP authoring and propagation")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--evidence-root", default=None)
    args = ap.parse_args(argv)

    sf = shape_finding()
    if args.dry_run:
        return _dry_run(sf)

    state = T.State.load(Path(args.state) if args.state else None)
    run_id = state.run_id
    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    fc = A.factory(args.region)
    org = fc.organizations()
    lim = A.limiter()
    # `A.account_id(fc)` and not an inline `get_caller_identity()["Account"]`: the helper REGISTERS
    # the id with `redact.register_account_id`, which is how the masker finds a bare account number
    # outside ARN position. This case compares `MasterAccountId` against it, so an inline read would
    # put a 12-digit account into a distributable record with nothing taught to mask it. Enforced by
    # `lib/tests/test_account_id_choke_point.py`, which exists because of exactly that leak.
    acct = A.account_id(fc)

    print(f"{CASE} — Route 4 SCP authoring and propagation, run_id={run_id}")
    print(f"  SERVICE_CONTROL_POLICY supported by DescribeEffectivePolicy: "
          f"{sf['scp_supported_by_describe_effective_policy']}")
    print(f"  enum difference vs CreatePolicy: {sf['in_create_but_not_in_describe_effective']}")
    print()

    # ---- preconditions -----------------------------------------------------
    try:
        o = org.describe_organization()["Organization"]
    except Exception as exc:                                          # noqa: BLE001
        print(f"FATAL: describe_organization failed ({type(exc).__name__}). This case needs the "
              f"Organizations management account.", file=sys.stderr)
        return 2
    is_mgmt = str(o.get("MasterAccountId") or "") == acct
    before = inventory(org)
    print(f"  management account: {is_mgmt}   featureSet={o.get('FeatureSet')}")
    print(f"  root {before['root_id']}  SCPs enabled: {before['scp_enabled_on_root']}")
    print(f"  existing OUs: {before['ou_names']}")
    print(f"  existing SCPs: {before['scp_names']}")
    if not is_mgmt or o.get("FeatureSet") != "ALL" or not before["scp_enabled_on_root"]:
        print("\nFATAL: preconditions not met (need the management account, FeatureSet=ALL, and "
              "SERVICE_CONTROL_POLICY enabled on the root). Nothing measured.", file=sys.stderr)
        return 2
    for name in PROTECTED_OU_NAMES:
        if name not in before["ou_names"]:
            print(f"\nFATAL: expected protected OU {name!r} is absent, so this is not the "
                  f"organization this script was written against and its do-not-touch list cannot "
                  f"be trusted.", file=sys.stderr)
            return 2
    print()

    break_glass = f"arn:aws:iam::{acct}:role/grx-breakglass-{run_id}"
    doc = scp_document(break_glass)

    ou_id = ""
    nested_id = ""
    policy_id = ""
    attached = False
    created: list[dict[str, str]] = []
    deleted: list[dict[str, Any]] = []
    authoring: dict[str, Any] = {}
    structure: dict[str, Any] = {}
    service_answer: dict[str, Any] = {}
    after: dict[str, Any] = {}

    try:
        # ---- fresh EMPTY child OU, and a nested child for inheritance -----
        lim.wait("CreateOrganizationalUnit")
        r = capture(store, "create_organizational_unit", org,
                    ParentId=before["root_id"], Name=f"{OWNED_PREFIX}ou-{run_id}"[:128])
        if not r.ok:
            print(f"FATAL: could not create the fresh OU ({r.error_code}: {r.error_message}).",
                  file=sys.stderr)
            return 2
        ou_id = str(((r.response or {}).get("OrganizationalUnit") or {}).get("Id") or "")
        created.append({"kind": "ou", "id": ou_id})
        print(f"  created fresh EMPTY OU {ou_id}")

        lim.wait("CreateOrganizationalUnit")
        r = capture(store, "create_organizational_unit", org,
                    ParentId=ou_id, Name=f"{OWNED_PREFIX}nested-{run_id}"[:128])
        if r.ok:
            nested_id = str(((r.response or {}).get("OrganizationalUnit") or {}).get("Id") or "")
            created.append({"kind": "ou", "id": nested_id})
            print(f"  created nested child OU {nested_id} (for the inheritance read)")

        # a fresh OU must have no accounts, and that is checked rather than assumed
        acc = org.list_accounts_for_parent(ParentId=ou_id).get("Accounts") or []
        if acc:
            print(f"\nFATAL: the fresh OU already contains {len(acc)} account(s). It was created "
                  f"seconds ago, so this is not the object it should be, and attaching a deny to "
                  f"it could affect real principals. Aborting before the attach.", file=sys.stderr)
            return 2
        print(f"  confirmed empty: 0 member accounts")

        # ---- AUTHORING: does the service accept this SCP? -----------------
        lim.wait("CreatePolicy")
        r = capture(store, "create_policy", org,
                    Content=json.dumps(doc, separators=(",", ":")),
                    Description=f"{CASE} Route 4 deny with break-glass exception; "
                                f"attached to an empty OU only",
                    Name=f"{OWNED_PREFIX}deny-{run_id}"[:128], Type=SCP)
        authoring = {
            "accepted": bool(r.ok),
            "error_code": r.error_code, "error_message": r.error_message,
            "http_status": r.http_status, "request_id": r.request_id,
            "document": doc,
            "break_glass_principal": break_glass,
            "break_glass_form": "ArnNotLike on aws:PrincipalArn (deny everyone EXCEPT this role)",
            "evidence": r.path,
        }
        if not r.ok:
            print(f"  AUTHORING: REJECTED  {r.error_code}: {r.error_message}")
        else:
            policy_id = str(((r.response or {}).get("Policy") or {})
                            .get("PolicySummary", {}).get("Id") or "")
            created.append({"kind": "policy", "id": policy_id})
            print(f"  AUTHORING: accepted, policy {policy_id}")

            lim.wait("AttachPolicy")
            r2 = capture(store, "attach_policy", org, PolicyId=policy_id, TargetId=ou_id)
            attached = bool(r2.ok)
            print(f"  attach to {ou_id}: ok={attached}"
                  + ("" if attached else f"  {r2.error_code}: {r2.error_message}"))

        # ---- 2. the service's own answer to the pre-registered call -------
        service_answer = ask_the_service(org, store, lim, target_id=ou_id)
        print(f"  DescribeEffectivePolicy(PolicyType={SCP}): accepted="
              f"{service_answer['accepted']} code={service_answer['error_code']!r} "
              f"request_id={service_answer['request_id']!r} "
              f"client_side={service_answer['rejected_client_side_by_botocore']}")

        # ---- 3. STRUCTURE: attachment and inheritance ---------------------
        if attached:
            on_ou = policies_for_target(org, ou_id)
            on_nested = policies_for_target(org, nested_id) if nested_id else []
            on_root = policies_for_target(org, before["root_id"])
            structure = {
                "instrument": "ListPoliciesForTarget",
                "is_not_the_sealed_instrument": (
                    "ListPoliciesForTarget reports which policies are ATTACHED to a target. It is "
                    "not DescribeEffectivePolicy and does not report an evaluated effect, so it "
                    "cannot settle the sealed oracle and is not offered as doing so."),
                "attached_to_fresh_ou": on_ou,
                "attached_to_nested_child": on_nested,
                "attached_to_root": on_root,
                "our_policy_on_fresh_ou": any(p["Id"] == policy_id for p in on_ou),
                "our_policy_listed_on_nested_child": any(
                    p["Id"] == policy_id for p in on_nested),
                "our_policy_leaked_to_root": any(p["Id"] == policy_id for p in on_root),
                "reading": (
                    "ListPoliciesForTarget reports DIRECT attachments, so an SCP attached to a "
                    "parent OU is expected NOT to appear on the child even though it does apply "
                    "to it. A False on the nested child is therefore not evidence against "
                    "inheritance — which is precisely why this cannot stand in for an effective-"
                    "policy read, and why no verdict is derived from it."),
            }
            print(f"  STRUCTURE: on fresh OU={structure['our_policy_on_fresh_ou']} "
                  f"listed on nested child={structure['our_policy_listed_on_nested_child']} "
                  f"leaked to root={structure['our_policy_leaked_to_root']}")

    finally:
        # ---- teardown: detach -> policy -> nested OU -> OU ----------------
        if attached and policy_id:
            lim.wait("DetachPolicy")
            d = capture(store, "detach_policy", org, PolicyId=policy_id, TargetId=ou_id)
            deleted.append({"kind": "detach", "id": policy_id, "ok": bool(d.ok),
                            "error_code": d.error_code})
            print(f"  detach {policy_id}: ok={d.ok}")
        if policy_id:
            lim.wait("DeletePolicy")
            d = capture(store, "delete_policy", org, PolicyId=policy_id)
            deleted.append({"kind": "policy", "id": policy_id, "ok": bool(d.ok),
                            "error_code": d.error_code})
            print(f"  delete policy {policy_id}: ok={d.ok}"
                  + ("" if d.ok else f"  {d.error_code}: {d.error_message}"))
        for oid in [i for i in (nested_id, ou_id) if i]:
            lim.wait("DeleteOrganizationalUnit")
            d = capture(store, "delete_organizational_unit", org, OrganizationalUnitId=oid)
            deleted.append({"kind": "ou", "id": oid, "ok": bool(d.ok),
                            "error_code": d.error_code})
            print(f"  delete OU {oid}: ok={d.ok}"
                  + ("" if d.ok else f"  {d.error_code}: {d.error_message}"))

        after = inventory(org)
        # Residue from TWO LISTS: what was created vs what a delete actually removed. Derived from
        # the post-teardown inventory rather than from the deletion results, because a delete whose
        # call never happened contributes no row and a deletions-only residue would report clean
        # exactly when something survived (phase1.probe_residue's rule, applied to org objects).
        surviving = ([i for i in created
                      if i["kind"] == "ou" and i["id"] in set(after["ou_ids"])]
                     + [i for i in created
                        if i["kind"] == "policy" and i["id"] in set(after["scp_ids"])])
        # A nested OU is not listed under root, so absence from ou_ids does not prove it is gone.
        # Its delete result is the only signal available, so it is folded in explicitly.
        nested_gone = all(d["ok"] for d in deleted if d["kind"] == "ou" and d["id"] == nested_id) \
            if nested_id else True
        never_attempted = [i["id"] for i in created
                           if not any(d["id"] == i["id"] for d in deleted)]
        inventory_unchanged = (before["ou_names"] == after["ou_names"]
                               and before["scp_names"] == after["scp_names"])
        residue = {
            "n_created": len(created),
            "n_delete_attempted": len([d for d in deleted if d["kind"] != "detach"]),
            "surviving": [i["id"] for i in surviving],
            "never_attempted": never_attempted,
            "nested_ou_deleted": nested_gone,
            "inventory_unchanged": inventory_unchanged,
            "clean": (not surviving) and nested_gone and inventory_unchanged
                     and not never_attempted,
        }
        print(f"  residue: created={residue['n_created']} surviving={residue['surviving']} "
              f"inventory_unchanged={inventory_unchanged} clean={residue['clean']}")
        for name in PROTECTED_POLICY_NAMES:
            if name not in after["scp_names"]:
                print(f"  ALARM: protected policy {name!r} is no longer present after teardown.",
                      file=sys.stderr)

        # ---- the verdict: the instrument does not exist -------------------
        record = O.not_measured(
            CASE,
            f"the pre-registered instrument does not cover SCPs: DescribeEffectivePolicy's "
            f"PolicyType enum has {len(sf['describe_effective_policy_enum'])} members and "
            f"SERVICE_CONTROL_POLICY is not among them, while CreatePolicy's has "
            f"{len(sf['create_policy_enum'])} and does include it "
            f"(difference: {sf['in_create_but_not_in_describe_effective']}). The service was asked "
            f"anyway and answered {service_answer.get('error_code') or 'n/a'!r}. No substitute "
            f"call is reported under this oracle's name.",
            instrument_absent="DescribeEffectivePolicy/SERVICE_CONTROL_POLICY",
            authoring_accepted=authoring.get("accepted"),
            attached=attached,
            sdk=sf["sdk"])

        payload = {
            "run_id": run_id,
            "region": args.region,
            "status": (
                "SEALED ORACLE NOT EVALUABLE. Reported as such rather than as a verdict. The "
                "authoring half below is an UNPLANNED mechanism observation in the shape F1-11 "
                "established: it spends no alpha and carries no pre-registered verdict."),
            "shape_finding": sf,
            "service_answer_to_the_preregistered_call": service_answer,
            "organization": {
                "is_management_account": is_mgmt,
                "feature_set": o.get("FeatureSet"),
                "root_id": before["root_id"],
                "scp_enabled_on_root": before["scp_enabled_on_root"],
                "inventory_before": before,
                "inventory_after": after,
                "protected_ous": list(PROTECTED_OU_NAMES),
                "protected_policies": list(PROTECTED_POLICY_NAMES),
            },
            "authoring": authoring,
            "structure": structure,
            "residue": residue,
            "verdict_rule": (
                "EXISTENCE, and it CANNOT be evaluated. The sealed oracle reads "
                "'TRUE if DescribeEffectivePolicy shows the deny on a fresh child OU'. That "
                "operation does not accept SERVICE_CONTROL_POLICY, so the condition has no truth "
                "value here. Recorded via oracle.not_measured with the shape evidence, because a "
                "TRUE derived from a different call would be a verdict about a different claim."),
            "verdict_reading": (
                "Neither TRUE nor FALSE. What IS established: an SCP denying the Route 4 actions "
                "with a break-glass exception "
                f"{'was accepted' if authoring.get('accepted') else 'was NOT accepted'} by "
                "CreatePolicy and "
                f"{'attached' if attached else 'did not attach'} to a fresh empty OU. That is the "
                "authoring half of the case's own title. The propagation half needs an instrument "
                "the API does not offer for this policy type."),
            "what_true_does_not_prove": (
                "There is no TRUE here to qualify. The authoring observation proves only that the "
                "organization ACCEPTED the document — not that the deny would be enforced against "
                "any principal, not that the break-glass exception evaluates the way it reads, and "
                "not that an account moved into the OU would be constrained. Enforcement from "
                "inside a member account is the separate sealed case F5-3c and nothing here "
                "anticipates its result. The OU was deliberately EMPTY, so this case has no "
                "evidence about effect on real principals at all."),
            "why_this_matters_operationally": (
                "Route 4 in the document is an SCP-based control, and an operator asked to prove "
                "it is in force will reach for DescribeEffectivePolicy because that is what the "
                "name suggests. They will get an error, and the reason is structural rather than a "
                "misconfiguration they can fix: an SCP has no single effective document. Verifying "
                "an SCP control means enumerating attachments up the OU tree and reasoning about "
                "the intersection, or testing behaviour from inside a member account. Any runbook "
                "that says 'confirm with DescribeEffectivePolicy' cannot be followed."),
            "limitations": [
                "The empty OU means this case observes authoring and attachment STRUCTURE only. "
                "ListPoliciesForTarget reports direct attachments, so an SCP on a parent is "
                "expected not to be listed on a child even though it applies — no inheritance "
                "conclusion is drawn from that read.",
                "The break-glass role ARN is constructed, not created. CreatePolicy does not "
                "require the principal to exist, so acceptance says nothing about whether that "
                "role resolves.",
                f"Read against {sf['sdk']}. If a later SDK adds SERVICE_CONTROL_POLICY to the "
                f"effective-policy enum, the sealed oracle becomes executable and this record "
                f"expires.",
            ],
            "expiry": state.expires_at,
        }
        P.emit(CASE, record, payload, store)

    if not authoring:
        print("\nFATAL: the authoring arm never ran, so nothing was measured.", file=sys.stderr)
        return 2
    if not residue["clean"]:
        print(f"\nFATAL: organization residue survived. surviving={residue['surviving']} "
              f"never_attempted={residue['never_attempted']} "
              f"inventory_unchanged={residue['inventory_unchanged']}. Delete these by hand; an "
              f"orphan SCP or OU is a permanent artefact in a live organization.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
