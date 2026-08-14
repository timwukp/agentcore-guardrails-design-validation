#!/usr/bin/env python3
"""F5-3a must keep reporting that its sealed instrument does not exist.

WHAT IS UNUSUAL ABOUT THE SCRIPT UNDER TEST, AND WHAT THESE ARMS PROTECT

The sealed oracle for F5-3a reads "TRUE if **DescribeEffectivePolicy** shows the deny on a fresh
child OU with a break-glass exception; FALSE if the policy does not propagate". That instrument does
not exist for SCPs: `DescribeEffectivePolicy`'s `PolicyType` enum has eleven members and
`SERVICE_CONTROL_POLICY` is not among them, while `CreatePolicy`'s `Type` enum has thirteen and does
include it. Both enums are read here out of the same shipped botocore model the script reads, so that
sentence is a derivation in this file too and not a claim about a claim.

So the pre-registered condition has NO TRUTH VALUE, and the script reports that via
`oracle.not_measured` instead of manufacturing a verdict from a substituted call. The single most
important arm in this file is `test_no_substituted_call_can_produce_a_verdict`: it runs `main()`
twice against a `ListPoliciesForTarget` double that reports FULL propagation onto the nested child
and then against one that reports NOTHING, and requires the published verdict to be INCONCLUSIVE
both times. A future edit that quietly promotes `ListPoliciesForTarget` to the verdict instrument
would make those two runs disagree, and that arm goes red. `test_the_script_has_no_code_path_that
_evaluates_an_oracle` is its static half, over the AST, because "no path exists" is not a statement
any single execution can make.

The second most important is `test_the_deny_applies_to_everyone_except_the_break_glass_role`. The
document's exception is an `ArnNotLike` on `aws:PrincipalArn` — deny everybody EXCEPT the break-glass
role. The inverted `ArnLike` form denies ONLY the break-glass role, which is the exact opposite of a
break-glass exception, and CreatePolicy/AttachPolicy would both accept it without complaint. So AWS
can never catch that inversion and only an arm here can. It is asserted twice: once on the shape of
the condition, and once on its MEANING, through a small `ArnLike`/`ArnNotLike` matcher — a string
check alone would pass a document whose operator was renamed to something inert.

NO AWS CALL, AND SPECIFICALLY NO ORGANIZATIONS CALL

This script creates real organizational units and a real SCP in a live management account. A test
that reached the API could attach a deny policy to a real OU. So `capture` is replaced wholesale,
`A.factory` is replaced with a factory that hands out `FakeOrg`, and `FakeOrg` is dicts — it is not a
botocore client and has no `meta`, so nothing here can reach a socket even if the patching were
incomplete. `P.emit` is replaced too, because the real one writes into `results/phase1/`, which the
root `conftest.py` fails a test for touching.

The service MODEL is real (`awsclients.service_model` reads a JSON file shipped inside botocore and
builds no client, so it resolves no credentials and opens no socket). That is deliberate: "the
effective-policy enum omits SERVICE_CONTROL_POLICY" is the finding under test, and a hand-typed
member list here would be the second source of truth the script exists to avoid.

WHY THE ORGANIZATION DOUBLE ENFORCES AWS'S OWN ORDERING RULES

`FakeOrg` refuses to delete a policy that is still attached and refuses to delete an OU that still
has children — the two constraints that make teardown order detach -> policy -> nested OU -> OU
rather than the reverse of creation order. A double without them would let a permuted teardown pass
every arm while stranding a real SCP in a real organization.

WHY THERE ARE A SUCCEEDING DOUBLE AND SEVERAL LYING ONES

`Cap(lie_delete_top_level_ou=True)` returns `ok=True` for the fresh OU's delete and leaves the OU
listed under root. That is the exact case a residue check computed from the deletion results alone
reports CLEAN: every delete row says it worked, and only the post-teardown inventory disagrees.

Two further lies exist because the residue fields are COUPLED in a coherent organization, and a guard
can only be shown to be load-bearing by a fixture in which it is the only thing that fails. An
undeleted nested OU blocks its parent's deletion, so a plain failure on the child makes `surviving`
fire as well — and an arm aimed at `nested_ou_deleted` would then pass for the wrong reason and would
keep passing with `nested_ou_deleted` deleted from the expression. Measured, not assumed: the first
version of the three residue arms here let three mutants survive for precisely that reason, and
`Cap`'s docstring records which lie now isolates which field.

Every double builds real `evidence.Record` instances rather than a stand-in class, so a field renamed
on `Record` breaks these arms instead of silently passing.

MUTANT / KILL TABLE (each mutant applied to the shipped file, the named arm run alone, red observed,
file restored from a byte-identical backup)

  M01 hardcode the eleven-member enum as a literal list in `shape_finding`
      -> test_shape_finding_derives_the_enums_and_hardcodes_neither
  M02 compute the difference the other way round (`eff` not in `create`)
      -> test_the_difference_is_exactly_the_two_authorization_policy_types
  M03 `scp_supported_by_describe_effective_policy` reads the CreatePolicy enum
      -> test_scp_is_reported_unsupported_by_describe_effective_policy
  M04 `ArnNotLike` -> `ArnLike` in `scp_document`
      -> test_the_break_glass_exception_is_written_as_arn_not_like
      -> test_the_deny_applies_to_everyone_except_the_break_glass_role
      -> test_the_document_that_reaches_create_policy_is_the_uninverted_one
  M05 drop `UpdateGatewayTarget` from ROUTE4_ACTIONS
      -> test_the_denied_actions_are_real_operations_in_the_shipped_model
  M06 `rejected_client_side_by_botocore` stops depending on the request id
      -> test_a_service_rejection_is_not_reported_as_a_botocore_refusal
  M07 delete the PROTECTED_OU_NAMES precondition loop
      -> test_a_missing_protected_ou_aborts_because_the_list_cannot_be_trusted
  M08 precondition drops the FeatureSet check
      -> test_a_feature_set_other_than_all_aborts_with_nothing_measured
  M09 precondition drops the `Status == ENABLED` half of the root policy-type check
      -> test_scp_not_enabled_on_the_root_aborts[pending]
  M10 move the emptiness check to AFTER the attach
      -> test_the_fresh_ou_is_proved_empty_before_the_attach
  M11 the two OU deletes permuted to the reverse of creation order (parent before child)
      -> test_teardown_order_is_detach_then_policy_then_nested_ou_then_ou
  M11b detach and delete-policy swapped
      -> test_teardown_order_is_detach_then_policy_then_nested_ou_then_ou
  M12 teardown returns after a failed detach
      -> test_a_failed_detach_does_not_strand_the_rest_of_the_sweep
  M13 `surviving` computed from the deletion results instead of the inventory
      -> test_a_lying_delete_is_caught_by_the_post_teardown_inventory
  M14 drop `and not never_attempted` from `clean`
      -> test_a_created_object_whose_delete_never_happened_is_residue
  M15 drop `and nested_gone` from `clean`
      -> test_the_nested_ous_delete_result_is_folded_in_explicitly
  M16 drop `and inventory_unchanged` from `clean`
      -> test_a_changed_inventory_is_residue_even_with_nothing_surviving
  M17 delete the PROTECTED_POLICY_NAMES alarm loop
      -> test_a_protected_policy_missing_after_teardown_raises_an_alarm
  M18 derive a TRUE/FALSE from `structure` after `not_measured`
      -> test_no_substituted_call_can_produce_a_verdict
      -> test_the_script_has_no_code_path_that_evaluates_an_oracle
  M19 `instrument_absent="ListPoliciesForTarget/SERVICE_CONTROL_POLICY"`
      -> test_the_instrument_declared_absent_is_the_one_the_seal_names
  M20 swallow the try's exception (`except Exception: pass` before the `finally`)
      -> test_teardown_and_emit_run_even_when_an_arm_above_them_aborts
  M21 `inventory` reads only the first page of OUs
      -> test_the_inventory_reads_every_page_of_both_listings
  H22 drop the `lim.wait("DeletePolicy")` call
      -> test_every_mutating_call_asks_the_limiter_to_wait_first
  H23 drop the ArnNotLike explanation from the dry-run banner
      -> test_the_dry_run_declares_the_break_glass_direction_and_teardown_order
  M24 the pre-registered call sent with `PolicyType="TAG_POLICY"`
      -> test_the_preregistered_call_is_sent_with_policy_type_service_control_policy
  M25 the SCP attached to the ROOT instead of the fresh OU
      -> test_the_policy_is_attached_to_the_fresh_ou_only
      -> test_nothing_the_script_did_not_create_is_ever_deleted_or_attached
  M26 the policy inventory filtered on `TAG_POLICY`
      -> test_the_inventory_filters_the_policy_listing_on_service_control_policy
  M27 the created policy name loses OWNED_PREFIX
      -> test_every_created_name_carries_the_owned_prefix_and_the_run_id

27 mutants, 27 killed. M04, M18 and M25 were re-run WITHOUT `-x` to confirm that every arm named for
them dies, not merely the first one pytest reached.

EXPECTED SURVIVORS, with reasons, because a vacuous arm is worse than no arm

  * `if not authoring: return 2` is UNREACHABLE on every path that reaches it. `authoring` is
    assigned unconditionally before `create_policy`'s result is inspected, and every earlier exit is
    an explicit `return 2` inside the `try`. An exception instead propagates. It is defensive depth,
    not dead weight, but no mutation of it can be observed and no arm claims to cover it — see
    `test_the_authoring_never_ran_branch_is_documented_as_unreachable`, which pins the reasoning
    rather than the behaviour.
  * The eleven/thirteen counts quoted in the module docstring are pinned by
    `test_the_counts_quoted_in_the_prose_are_the_sdks_own`, whose mutation target is botocore
    itself. It is a tripwire for an SDK upgrade (which is what the record's `expiry` is about), not
    a guard over this file's logic.
  * The oracle binding arm reads `claims/` and `PREREGISTRATION.yaml`, both sealed, so its mutant
    would have to be a re-seal. It is kept because a re-seal that gave F5-3a a planned n or a
    mandatory mutation would change what `not_measured` may claim.

WHAT THIS FILE DOES NOT COVER, STATED SO IT IS NOT MISTAKEN FOR COVERED

  * The inventory reads (`list_roots`, `list_organizational_units_for_parent`, `list_policies`,
    `list_policies_for_target`, `list_accounts_for_parent`) do NOT go through `capture`, so the
    before/after inventory and the emptiness check leave no evidence record and no request id. The
    verdict does not rest on them; the "nothing outside our own objects was touched" claim does, and
    that claim is therefore archived only as a derived boolean in the payload. Arms here assert the
    calls happen and what they are filtered on; they cannot assert that a reader could later audit
    them against AWS.
  * `after = inventory(org)` inside the `finally` is unguarded. If that read raises — the same
    transport failure `test_teardown_and_emit_run_even_when_an_arm_above_them_aborts` injects one
    step earlier — the residue computation and the `not_measured` record are both lost, after the
    sweep has already run. No arm asserts a behaviour here because there is none to assert.
  * Only `CreatePolicy` and `DeletePolicy` have entries in `awsclients.RATE_LIMITS`, so seven of the
    nine `lim.wait` calls are no-ops. `lib/` is sealed, so the set of unpaced operations is pinned
    (two-way) by `test_every_mutating_call_asks_the_limiter_to_wait_first` instead of fixed.
  * The precondition block runs `inventory()` BEFORE it checks `FeatureSet` and the root's policy
    types. In an organization where `ListPolicies(Filter=SERVICE_CONTROL_POLICY)` errors rather than
    returning an empty list, the script exits by traceback (rc=1, "unclassified" by the repo's own
    convention) instead of the rc=2 "nothing measured" it intends. That is within the stated rc
    convention, so it is recorded here rather than changed.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

SCRIPT = ROOT / "f5_redteam" / "10_route4_scp_propagation.py"
_spec = importlib.util.spec_from_file_location("grx_f5_10_route4_scp_propagation", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules["grx_f5_10_route4_scp_propagation"] = M
_spec.loader.exec_module(M)

import awsclients as A      # noqa: E402
import evidence as E        # noqa: E402
import oracle as O          # noqa: E402
import phase1 as P          # noqa: E402

SRC = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
PY = str(ROOT / ".venv-oracle" / "bin" / "python")

CASE = "F5-3a"
SCP = "SERVICE_CONTROL_POLICY"
RCP = "RESOURCE_CONTROL_POLICY"

# The sealed oracle text, and the operation name derived FROM it rather than retyped. Two capitalised
# words joined is the only CamelCase shape in the sentence, so this finds the instrument the seal
# names without a literal that could drift away from the seal.
SEAL = O.oracle_text(CASE)
SEALED_OPS = re.findall(r"\b(?:[A-Z][a-z0-9]+){2,}\b", SEAL)

# Read from the shipped model, exactly as the script does. `service_model` builds no client, so it
# resolves no credentials and opens no socket.
_ORG_MODEL = A.service_model("organizations")
EFF_ENUM = list(_ORG_MODEL.operation_model("DescribeEffectivePolicy").input_shape
                .members["PolicyType"].enum)
CREATE_ENUM = list(_ORG_MODEL.operation_model("CreatePolicy").input_shape.members["Type"].enum)
_AC_OPERATIONS = set(A.service_model("bedrock-agentcore-control").operation_names)

# AWS's published documentation-example account, on ONE line, for the same reason
# `test_route3_updategateway.py` gives: `check_redaction.py` structurally excuses an ARN whose
# account field is a placeholder, and a redacted 12-digit field is a value IAM would reject.
EXAMPLE_ACCOUNT = "111122223333"
RUN = "r20260813T090000Z"

ROOT_ID = "r-ab12"
PROD_ID = "ou-ab12-production"
DEVOPS_ID = "ou-ab12-devops"
FULLAWS_ID = "p-FullAWSAccess"
DEVOPSONLY_ID = "p-devOpsOnly"
PRODONLY_ID = "p-productionOnly"

BASE_OUS = {PROD_ID: {"Name": "production", "Parent": ROOT_ID},
            DEVOPS_ID: {"Name": "DevOps", "Parent": ROOT_ID}}
BASE_POLICIES = {FULLAWS_ID: "FullAWSAccess", DEVOPSONLY_ID: "devOpsOnly",
                 PRODONLY_ID: "productionOnly"}
PROTECTED_IDS = frozenset({PROD_ID, DEVOPS_ID, FULLAWS_ID, DEVOPSONLY_ID, PRODONLY_ID})


# ---------------------------------------------------------------------------
# the organization double: dicts, and AWS's own ordering rules
# ---------------------------------------------------------------------------

class FakeOrg:
    """An organization made of dicts, with no `meta` and no route to a socket.

    Deliberately NOT a botocore client and deliberately not a MagicMock: `inventory`,
    `policies_for_target` and the emptiness check call this object directly (they are not routed
    through `capture`), so their pagination and their filters are asserted against a thing that can
    refuse. A MagicMock would answer every one of them with a truthy sentinel.

    The two ordering rules AWS enforces are enforced here, because they are the whole reason
    teardown order is not the reverse of creation order:

      * a policy cannot be deleted while it is attached to anything;
      * an OU cannot be deleted while it still has children.

    Without them a permuted teardown would pass every behavioural arm here while stranding a live
    SCP in a live organization.
    """

    def __init__(self, *, feature_set: str = "ALL", master: str = EXAMPLE_ACCOUNT,
                 scp_status: str | None = "ENABLED", ous: dict | None = None,
                 policies: dict | None = None, page: int = 50) -> None:
        self.feature_set = feature_set
        self.master = master
        self.scp_status = scp_status
        self.ous: dict[str, dict] = dict(BASE_OUS if ous is None else ous)
        self.policies: dict[str, str] = dict(BASE_POLICIES if policies is None else policies)
        self.attachments: dict[str, set[str]] = {}
        self.accounts: dict[str, list[dict]] = {}
        self.page = page
        self.raises: dict[str, BaseException] = {}
        self.calls: list[tuple[str, dict]] = []
        self._seq = 0

    # -- helpers -----------------------------------------------------------

    def _log(self, op: str, params: dict) -> None:
        if op in self.raises:
            self.calls.append((op, params))
            raise self.raises[op]
        self.calls.append((op, params))

    def _paged(self, items: list, tok: str | None) -> tuple[list, str | None]:
        start = int(tok) if tok else 0
        chunk = items[start:start + self.page]
        nxt = start + self.page
        return chunk, (str(nxt) if nxt < len(items) else None)

    def new_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq}"

    # -- the operations the script calls without `capture` -----------------

    def describe_organization(self, **kw):
        self._log("describe_organization", kw)
        return {"Organization": {"Id": "o-example", "MasterAccountId": self.master,
                                 "FeatureSet": self.feature_set}}

    def list_roots(self, **kw):
        self._log("list_roots", kw)
        types = [{"Type": "TAG_POLICY", "Status": "ENABLED"}]
        if self.scp_status is not None:
            types.append({"Type": SCP, "Status": self.scp_status})
        return {"Roots": [{"Id": ROOT_ID, "Name": "Root", "PolicyTypes": types}]}

    def list_organizational_units_for_parent(self, ParentId, NextToken=None, **kw):
        self._log("list_organizational_units_for_parent",
                  {"ParentId": ParentId, "NextToken": NextToken})
        kids = [{"Id": i, "Name": d["Name"]} for i, d in sorted(self.ous.items())
                if d["Parent"] == ParentId]
        chunk, nxt = self._paged(kids, NextToken)
        return {"OrganizationalUnits": chunk, **({"NextToken": nxt} if nxt else {})}

    def list_policies(self, Filter, NextToken=None, **kw):
        self._log("list_policies", {"Filter": Filter, "NextToken": NextToken})
        # An SCP filter answers with SCPs; anything else answers with the (empty) set of that other
        # type. A script that filtered on the wrong type would therefore see no policies at all
        # rather than a plausible list.
        pols = ([{"Id": i, "Name": n, "Type": SCP} for i, n in sorted(self.policies.items())]
                if Filter == SCP else [])
        chunk, nxt = self._paged(pols, NextToken)
        return {"Policies": chunk, **({"NextToken": nxt} if nxt else {})}

    def list_policies_for_target(self, TargetId, Filter, NextToken=None, **kw):
        self._log("list_policies_for_target",
                  {"TargetId": TargetId, "Filter": Filter, "NextToken": NextToken})
        ids = sorted(self.attachments.get(TargetId, set())) if Filter == SCP else []
        pols = [{"Id": i, "Name": self.policies.get(i, "?"), "Type": SCP} for i in ids]
        chunk, nxt = self._paged(pols, NextToken)
        return {"Policies": chunk, **({"NextToken": nxt} if nxt else {})}

    def list_accounts_for_parent(self, ParentId, **kw):
        self._log("list_accounts_for_parent", {"ParentId": ParentId})
        return {"Accounts": list(self.accounts.get(ParentId, []))}


class FakeSts:
    def __init__(self, account: str = EXAMPLE_ACCOUNT) -> None:
        self.account = account

    def get_caller_identity(self):
        return {"Account": self.account, "Arn": f"arn:aws:iam::{self.account}:user/x"}


class FakeFactory:
    def __init__(self, org: FakeOrg, sts: FakeSts) -> None:
        self._org, self._sts = org, sts

    def organizations(self):
        return self._org

    def sts(self):
        return self._sts


class Limiter:
    """Records what it was asked to wait for. Not a no-op, so a dropped `wait` is visible."""

    def __init__(self) -> None:
        self.waited: list[str] = []

    def wait(self, operation: str, **_: object) -> float:
        self.waited.append(operation)
        return 0.0


# ---------------------------------------------------------------------------
# the capture doubles: one that SUCCEEDS, one that LIES
# ---------------------------------------------------------------------------

def _record(op: str, params: dict, *, ok: bool, seq: int, response: dict | None = None,
            error_code: str = "", error_message: str = "", request_id: str = "rid-0001",
            http_status: int | None = None) -> E.Record:
    """A real `evidence.Record`. A stand-in class would hide a field renamed on Record."""
    return E.Record(
        case_id=CASE, operation=op, service="organizations", region="us-east-1",
        params=dict(params), ok=ok,
        http_status=http_status if http_status is not None else (200 if ok else 400),
        request_id=request_id, response=response,
        error_code=error_code, error_message=error_message,
        error_class="" if ok else "ClientError",
        path=f"evidence/tmp/{seq:04d}_{op}_{'ok' if ok else 'err'}.json")


class Cap:
    """A `capture` replacement that drives `FakeOrg` and hands back real `Record`s.

    `fail` maps an operation to `(error_code, message)` and leaves the organization untouched.
    `boom` raises, for the transport failure that has to reach the `finally`.
    `blank_ids` drops the identifier out of a successful create response, which is how a created
    object acquires no id for any delete to name.
    `describe_effective` chooses what the pre-registered call comes back with.

    THREE NAMED LIES, each pointed at ONE residue field
    --------------------------------------------------
    A residue guard can only be shown to be load-bearing by a fixture in which it is the ONLY thing
    that fails. That is harder than it sounds, because a coherent organization couples the fields:
    an undeleted nested OU blocks its parent's deletion, so `surviving` fires too and an arm aimed at
    `nested_ou_deleted` proves nothing about it. Hence three targeted lies rather than one blunt one,
    each documented with what it isolates:

    * `lie` — a create that reports `ok=True` and creates nothing. Paired with `blank_ids` it
      produces the object the script cannot name: no id, so no delete row, and (because nothing was
      really created) nothing for `surviving` or `inventory_unchanged` to notice either. Only
      `never_attempted` can see it.
    * `lie_delete_top_level_ou` — the fresh OU's delete reports `ok=True` and the OU is still listed
      under root afterwards. Every deletion row says success, so a residue computed from those rows
      alone reports clean. Only the post-teardown inventory disagrees.
    * `nested_delete_reports_failure` — the nested OU's delete REALLY removes it and reports
      `ok=False`. The parent's delete then succeeds honestly, the inventory is unchanged, nothing
      survives — and the only signal the script has about the child says the delete failed. Only
      `nested_ou_deleted` can see it, and treating that signal as authoritative is the conservative
      direction.
    """

    def __init__(self, org: FakeOrg, *, fail: dict[str, tuple[str, str]] | None = None,
                 lie: frozenset[str] | set[str] = frozenset(),
                 blank_ids: frozenset[str] | set[str] = frozenset(),
                 boom: frozenset[str] | set[str] = frozenset(),
                 lie_delete_top_level_ou: bool = False,
                 nested_delete_reports_failure: bool = False,
                 describe_effective: str = "service_rejection") -> None:
        self.org = org
        self.fail = dict(fail or {})
        self.lie = set(lie)
        self.blank_ids = set(blank_ids)
        self.boom = set(boom)
        self.lie_delete_top_level_ou = lie_delete_top_level_ou
        self.nested_delete_reports_failure = nested_delete_reports_failure
        self.describe_effective = describe_effective
        self.calls: list[tuple[str, dict]] = []
        self._seq = 0

    @property
    def ops(self) -> list[str]:
        return [op for op, _ in self.calls]

    def params_for(self, op: str) -> list[dict]:
        return [p for o, p in self.calls if o == op]

    def __call__(self, store, operation, client, **params):          # noqa: ANN001
        self.calls.append((operation, dict(params)))
        self._seq += 1
        if operation in self.boom:
            raise RuntimeError(f"transport failure on {operation}")
        if operation in self.fail:
            code, msg = self.fail[operation]
            return _record(operation, params, ok=False, seq=self._seq,
                           error_code=code, error_message=msg)
        handler = getattr(self, f"_{operation}", None)
        if handler is None:
            return _record(operation, params, ok=True, seq=self._seq, response={})
        return handler(params)

    # -- one method per operation the script captures ----------------------

    def _create_organizational_unit(self, params):
        oid = self.org.new_id("ou-new-")
        if "create_organizational_unit" not in self.lie:
            self.org.ous[oid] = {"Name": params["Name"], "Parent": params["ParentId"]}
        body = {"Name": params["Name"], "Arn": f"arn:aws:organizations::{EXAMPLE_ACCOUNT}:ou/{oid}"}
        if "create_organizational_unit" not in self.blank_ids:
            body["Id"] = oid
        return _record("create_organizational_unit", params, ok=True, seq=self._seq,
                       response={"OrganizationalUnit": body})

    def _create_policy(self, params):
        pid = self.org.new_id("p-new-")
        if "create_policy" not in self.lie:
            self.org.policies[pid] = params["Name"]
        summary = {"Name": params["Name"], "Type": params["Type"],
                   "Arn": f"arn:aws:organizations::{EXAMPLE_ACCOUNT}:policy/{pid}"}
        if "create_policy" not in self.blank_ids:
            summary["Id"] = pid
        return _record("create_policy", params, ok=True, seq=self._seq,
                       response={"Policy": {"PolicySummary": summary,
                                            "Content": params["Content"]}})

    def _attach_policy(self, params):
        self.org.attachments.setdefault(params["TargetId"], set()).add(params["PolicyId"])
        return _record("attach_policy", params, ok=True, seq=self._seq, response={})

    def _detach_policy(self, params):
        self.org.attachments.get(params["TargetId"], set()).discard(params["PolicyId"])
        return _record("detach_policy", params, ok=True, seq=self._seq, response={})

    def _delete_policy(self, params):
        pid = params["PolicyId"]
        if any(pid in s for s in self.org.attachments.values()):
            # AWS's own rule, which is why teardown detaches first.
            return _record("delete_policy", params, ok=False, seq=self._seq,
                           error_code="PolicyInUseException",
                           error_message="the policy is attached to one or more targets")
        if "delete_policy" not in self.lie:
            self.org.policies.pop(pid, None)
        return _record("delete_policy", params, ok=True, seq=self._seq, response={})

    def _delete_organizational_unit(self, params):
        oid = params["OrganizationalUnitId"]
        if any(d["Parent"] == oid for d in self.org.ous.values()):
            # AWS's other rule, which is why the nested OU goes before its parent.
            return _record("delete_organizational_unit", params, ok=False, seq=self._seq,
                           error_code="OrganizationalUnitNotEmptyException",
                           error_message="the organizational unit still has children")
        top_level = self.org.ous.get(oid, {}).get("Parent") == ROOT_ID
        self.org.ous.pop(oid, None)
        if top_level and self.lie_delete_top_level_ou:
            # Reports success; the object is still there. Restored AFTER the pop so the parent's
            # own delete is evaluated against a genuinely childless OU — a lie about the CHILD
            # would make this delete fail for the honest reason and prove nothing.
            self.org.ous[oid] = {"Name": f"{M.OWNED_PREFIX}ou-{RUN}", "Parent": ROOT_ID}
        if not top_level and self.nested_delete_reports_failure:
            return _record("delete_organizational_unit", params, ok=False, seq=self._seq,
                           error_code="ConcurrentModificationException",
                           error_message="the organizational unit is being modified")
        return _record("delete_organizational_unit", params, ok=True, seq=self._seq, response={})

    def _describe_effective_policy(self, params):
        if self.describe_effective == "accepted":
            return _record("describe_effective_policy", params, ok=True, seq=self._seq,
                           response={"EffectivePolicy": {"PolicyType": params["PolicyType"]}})
        if self.describe_effective == "client_side":
            # botocore refused to send it: no request id, because there was no request.
            return _record("describe_effective_policy", params, ok=False, seq=self._seq,
                           request_id="", http_status=None,
                           error_code="ParamValidationError",
                           error_message="Unknown value for parameter PolicyType")
        return _record("describe_effective_policy", params, ok=False, seq=self._seq,
                       error_code="ValidationException",
                       error_message=f"1 validation error detected: value {SCP!r} at "
                                     f"'policyType' failed to satisfy constraint")


# ---------------------------------------------------------------------------
# running main() offline
# ---------------------------------------------------------------------------

class Run:
    def __init__(self, rc, cap, org, lim, emitted, out, err) -> None:
        self.rc, self.cap, self.org, self.lim = rc, cap, org, lim
        self.emitted, self.out, self.err = emitted, out, err

    @property
    def record(self) -> dict:
        assert self.emitted, "P.emit was never called, so nothing was published at all"
        return self.emitted[-1]["record"]

    @property
    def payload(self) -> dict:
        assert self.emitted, "P.emit was never called, so nothing was published at all"
        return self.emitted[-1]["payload"]


def _state_file(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"run_id": RUN, "region": "us-east-1",
                             "expires_at": "2026-08-20T00:00:00+00:00", "resources": []}),
                 encoding="utf-8")
    return p


def _run(monkeypatch, tmp_path, capsys, *, org=None, cap=None, expect_raises=None,
         caller=EXAMPLE_ACCOUNT):
    """Run `main()` end to end with no AWS anywhere. Returns a `Run`.

    `P.emit` is replaced because the real one writes `results/phase1/F5-3a.json`, and the root
    conftest fails any test that writes into the live results tree. The evidence store IS real,
    rooted in `tmp_path`.
    """
    org = org if org is not None else FakeOrg()
    cap = cap if cap is not None else Cap(org)
    lim = Limiter()
    emitted: list[dict] = []

    monkeypatch.setattr(M, "capture", cap)
    # The CALLER's account and the organization's management account are separate facts here, and
    # they have to be: deriving the caller from `org.master` would make `is_mgmt` true by
    # construction and the management-account precondition unfalsifiable.
    monkeypatch.setattr(M.A, "factory", lambda region, **kw: FakeFactory(org, FakeSts(caller)))
    monkeypatch.setattr(M.A, "limiter", lambda: lim)
    monkeypatch.setattr(M.P, "emit",
                        lambda case_id, record, payload, store=None, **kw: emitted.append(
                            {"case_id": case_id, "record": record, "payload": payload,
                             "store": store}) or (tmp_path / "emitted.json"))

    argv = ["--state", str(_state_file(tmp_path)), "--evidence-root", str(tmp_path / "ev")]
    rc = None
    if expect_raises is not None:
        with pytest.raises(expect_raises):
            M.main(argv)
    else:
        rc = M.main(argv)
    cp = capsys.readouterr()
    return Run(rc, cap, org, lim, emitted, cp.out, cp.err)


# ---------------------------------------------------------------------------
# the sealed oracle, and the instrument it names
# ---------------------------------------------------------------------------

def test_the_binding_is_existence_with_no_planned_n_and_no_mandatory_mutation():
    """What `not_measured` is allowed to claim depends on all three.

    A re-seal that gave F5-3a a planned n would make `n_met` False and add an amendment blocker
    this record does not currently carry; one that made the mutation mandatory would require an
    inversion arm the script has no instrument to run. Both would have to be read here before the
    verdict shape stayed honest, so the shape is pinned.
    """
    b = O.BINDINGS[CASE]
    assert b.kind == "EXISTENCE"
    assert b.thresholds == ()
    assert O.planned_n(CASE) is None
    assert O.mutation_is_mandatory(CASE) is False
    assert O.alpha_for(CASE) == pytest.approx(0.05)


def test_the_sealed_oracle_names_describe_effective_policy_and_nothing_else():
    """The instrument is not our choice: it is in the sealed text, and the text is the authority."""
    assert SEALED_OPS == ["DescribeEffectivePolicy"], (
        f"the sealed oracle for {CASE} no longer names exactly one operation ({SEALED_OPS}); "
        f"every argument in the script about a missing instrument has to be re-read")
    for phrase in ("fresh child OU", "break-glass", "does not propagate"):
        assert phrase in SEAL, f"the seal no longer asks for {phrase!r}"
    assert "ListPoliciesForTarget" not in SEAL, (
        "the seal names the effective-policy read; if it ever named the attachment read, the "
        "structural observation would BE the pre-registered instrument and this whole file changes")


def test_the_instrument_declared_absent_is_the_one_the_seal_names(monkeypatch, tmp_path, capsys):
    """`instrument_absent` must name the sealed operation, derived from the seal, not retyped.

    Kills M19: declaring `ListPoliciesForTarget` absent would be a true sentence about a call the
    seal never asked for, and would leave the sealed instrument silently unaccounted for.
    """
    r = _run(monkeypatch, tmp_path, capsys)
    absent = r.record["evidence"]["detail"]["instrument_absent"]
    assert absent.startswith(SEALED_OPS[0] + "/"), (
        f"the record declares {absent!r} absent, but the seal names {SEALED_OPS[0]}")
    assert absent.endswith(SCP)
    assert "ListPoliciesForTarget" not in absent, (
        "the attachment read is present and answers a different question; declaring it absent "
        "would hide the fact that the sealed instrument was never available")


# ---------------------------------------------------------------------------
# THE ARM THIS FILE EXISTS FOR
# ---------------------------------------------------------------------------

def test_no_substituted_call_can_produce_a_verdict(monkeypatch, tmp_path, capsys):
    """A TRUE/FALSE off `ListPoliciesForTarget` is the regression this file exists to prevent.

    Two runs of the same code against two organizations that differ ONLY in what the substituted
    instrument reports:

      * one where the policy is listed on the fresh OU AND on the nested child — the shape a reader
        looking for "the deny propagated" would read as TRUE;
      * one where `ListPoliciesForTarget` reports nothing anywhere — the shape that reads as FALSE.

    The structural observations must differ (or this arm proves nothing) and the published verdict
    must not: INCONCLUSIVE, `measured: False`, both times. Kills M18.
    """
    org_a = FakeOrg()
    # `ListPoliciesForTarget` reports DIRECT attachments, so inheritance onto the nested child is
    # not something AWS would show. This double shows it anyway, because the arm is about what the
    # script does with a propagation-shaped answer, not about what AWS returns.
    cap_a = Cap(org_a)
    real_attach = cap_a._attach_policy

    def _attach_everywhere(params):
        rec = real_attach(params)
        for target in list(org_a.ous):
            if target.startswith("ou-new-"):
                org_a.attachments.setdefault(target, set()).add(params["PolicyId"])
        return rec
    cap_a._attach_policy = _attach_everywhere
    a = _run(monkeypatch, tmp_path / "a", capsys, org=org_a, cap=cap_a)

    org_b = FakeOrg()
    cap_b = Cap(org_b)
    cap_b._attach_policy = lambda params: _record(               # attach ok, nothing recorded
        "attach_policy", params, ok=True, seq=0, response={})
    b = _run(monkeypatch, tmp_path / "b", capsys, org=org_b, cap=cap_b)

    # The substituted instrument really did answer differently in the two runs.
    assert a.payload["structure"]["our_policy_listed_on_nested_child"] is True
    assert b.payload["structure"]["our_policy_on_fresh_ou"] is False
    assert b.payload["structure"]["our_policy_listed_on_nested_child"] is False

    for run, name in ((a, "propagation-shaped"), (b, "no-attachment-shaped")):
        rec = run.record
        assert rec["verdict"] == O.INCONCLUSIVE, (
            f"the {name} answer from ListPoliciesForTarget produced {rec['verdict']!r}; a verdict "
            f"for {CASE} may only come from DescribeEffectivePolicy with PolicyType={SCP}, and "
            f"that operation does not accept it")
        assert rec["verdict"] not in O.DECISIVE
        assert rec["evidence"]["measured"] is False
        assert rec["evidence"]["detail"]["instrument_absent"] == (
            f"DescribeEffectivePolicy/{SCP}")
        assert "NOT EVALUABLE" in run.payload["status"]


def test_the_script_has_no_code_path_that_evaluates_an_oracle():
    """The static half: "no path exists" is not something one execution can establish.

    Read off the AST rather than by grep, so a call split across lines is one site. Kills M18 at
    desk even in the branch a test run does not enter.
    """
    o_calls, p_calls, bad = [], [], []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            if fn.value.id == "O":
                o_calls.append(fn.attr)
            if fn.value.id == "P":
                p_calls.append(fn.attr)
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name in ("evaluate", "obs_existence", "obs_zero_events", "obs_recorded", "_decide"):
            bad.append((name, node.lineno))
    assert not bad, (
        f"{CASE} builds an Observation or calls the decision procedure at {bad}. Its sealed "
        f"condition has no truth value — the instrument does not accept SERVICE_CONTROL_POLICY — "
        f"so anything that could return TRUE or FALSE here is a verdict about a different claim")
    assert o_calls, "a zero-site scan is an error, not a pass: the oracle import may have been renamed"
    assert set(o_calls) <= {"not_measured", "oracle_text", "planned_n", "alpha_for"}, (
        f"unexpected oracle entry points {sorted(set(o_calls))}; only not_measured may produce a "
        f"record for this case")
    assert o_calls.count("not_measured") == 1
    assert set(p_calls) == {"emit"}
    for attr in ("O.TRUE", "O.FALSE", "O.DECISIVE", 'record["verdict"] ='):
        assert attr not in SRC, (
            f"{attr!r} appears in the script; a verdict literal or an assignment over "
            f"not_measured's verdict is how a substituted call acquires the sealed oracle's name")


def test_the_structure_block_disclaims_being_the_sealed_instrument(monkeypatch, tmp_path, capsys):
    """The label travels with the observation, in the payload, not only in a docstring.

    A reader of `results/`/`evidence/` never sees this file. If the structural read were published
    without saying what it is not, the next person to summarise the run has nothing to stop them
    reporting it as the propagation result.
    """
    r = _run(monkeypatch, tmp_path, capsys)
    s = r.payload["structure"]
    assert s["instrument"] == "ListPoliciesForTarget"
    assert "not DescribeEffectivePolicy" in s["is_not_the_sealed_instrument"]
    assert "cannot settle the sealed oracle" in s["is_not_the_sealed_instrument"]
    assert "DIRECT attachments" in s["reading"], (
        "a False on the nested child is not evidence against inheritance, and the payload has to "
        "say so or the number invites the opposite reading")
    assert "UNPLANNED" in r.payload["status"]
    assert "CANNOT be evaluated" in r.payload["verdict_rule"]
    assert "Neither TRUE nor FALSE" in r.payload["verdict_reading"]


# ---------------------------------------------------------------------------
# 1. the shape finding, derived from the shipped model
# ---------------------------------------------------------------------------

def test_shape_finding_derives_the_enums_and_hardcodes_neither():
    """Both enums must come out of botocore, and no member may be typed into the function.

    Two halves, because either alone is passable. The behavioural half compares against the model
    read independently in this file; a hardcoded list that happens to be correct today would
    satisfy it. The static half reads `shape_finding`'s own AST and requires that no string literal
    in its body (docstring excluded) is a member of either enum, and that both enums arrive through
    `service_model` -> `operation_model` -> `input_shape.members`. Kills M01, which the behavioural
    half alone would survive.
    """
    sf = M.shape_finding()
    assert sf["describe_effective_policy_enum"] == EFF_ENUM
    assert sf["create_policy_enum"] == CREATE_ENUM
    assert sf["sdk"] == A.sdk_versions()

    fn = next(n for n in TREE.body
              if isinstance(n, ast.FunctionDef) and n.name == "shape_finding")
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)) else fn.body
    literals = {n.value for stmt in body for n in ast.walk(stmt)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    typed = literals & (set(EFF_ENUM) | set(CREATE_ENUM))
    assert not typed, (
        f"shape_finding types the enum member(s) {sorted(typed)} as literals. A hand-written list "
        f"is prose, and prose is not verified: it would keep reporting eleven members after an SDK "
        f"that added SERVICE_CONTROL_POLICY made the sealed oracle executable")
    calls = [n for stmt in body for n in ast.walk(stmt) if isinstance(n, ast.Call)]
    called = {n.func.attr for n in calls if isinstance(n.func, ast.Attribute)}
    assert {"service_model", "operation_model"} <= called, (
        f"shape_finding no longer reads the shipped service model (calls: {sorted(called)})")
    assert "input_shape" in ast.dump(fn), "the enum must be read off the operation's input shape"


def test_the_difference_is_exactly_the_two_authorization_policy_types():
    """`in_create_but_not_in_describe_effective` is the finding, and the direction matters.

    Computed the other way round it is empty for any SDK where the effective-policy enum is a
    subset — i.e. it reports "no difference" precisely when the difference is the whole result.
    Kills M02.
    """
    sf = M.shape_finding()
    missing = sf["in_create_but_not_in_describe_effective"]
    assert set(missing) == {SCP, RCP}, (
        f"the difference is {missing}; it must be exactly the two AUTHORIZATION policy types, "
        f"which is the fact that makes the omission coherent rather than a gap")
    assert missing, "an empty difference is the direction-reversed computation, not a finding"
    assert set(missing) == set(CREATE_ENUM) - set(EFF_ENUM)
    assert not (set(EFF_ENUM) - set(CREATE_ENUM)), (
        "every effective-policy type is also creatable, so the containment is one-directional and "
        "the difference has one meaningful direction")
    assert f"The difference is {missing}" in sf["reading"]


def test_scp_is_reported_unsupported_by_describe_effective_policy():
    """The one boolean the whole case turns on. Kills M03 (reading the CreatePolicy enum instead)."""
    sf = M.shape_finding()
    assert sf["scp_supported_by_describe_effective_policy"] is False
    assert SCP not in sf["describe_effective_policy_enum"]
    assert SCP in sf["create_policy_enum"], (
        "if CreatePolicy stopped accepting SERVICE_CONTROL_POLICY the authoring half would be "
        "unrunnable too, and this script's three arms would all need re-reading")


def test_the_counts_quoted_in_the_prose_are_the_sdks_own():
    """Eleven and thirteen appear in the module docstring, the dry run and the record's reason.

    EXPECTED SURVIVOR as a code mutant: its mutation target is botocore, not this repository. It is
    kept as the tripwire for the SDK upgrade the record's `expiry` is about — an SDK that adds
    SERVICE_CONTROL_POLICY to the effective-policy enum makes the sealed oracle executable and this
    whole script obsolete, and this arm is what says so on the day it happens.
    """
    assert len(EFF_ENUM) == 11 and len(CREATE_ENUM) == 13, (
        f"botocore now ships {len(EFF_ENUM)}/{len(CREATE_ENUM)} members. If "
        f"SERVICE_CONTROL_POLICY is now in the effective-policy enum, F5-3a is EXECUTABLE and the "
        f"not_measured record has expired")
    assert "eleven" in SRC and "thirteen" in SRC
    assert len(set(EFF_ENUM)) == len(EFF_ENUM), "a duplicated member would inflate the count"


# ---------------------------------------------------------------------------
# 3a. the SCP document, and the break-glass direction
# ---------------------------------------------------------------------------

BREAK_GLASS = f"arn:aws:iam::{EXAMPLE_ACCOUNT}:role/grx-breakglass-{RUN}"
SOME_OTHER_ROLE = f"arn:aws:iam::{EXAMPLE_ACCOUNT}:role/grx-caller"


def _deny_applies_to(doc: dict, principal_arn: str) -> bool:
    """Does this document's deny apply to `principal_arn`?

    A tiny evaluator rather than a string comparison, because the inversion under test is a
    statement about MEANING: `ArnNotLike` and `ArnLike` are both well-formed, both accepted by
    CreatePolicy, and they select complementary sets of principals. An unknown operator raises
    rather than defaulting, so renaming the condition to something inert is caught here too.
    """
    stmt, = doc["Statement"]
    assert stmt["Effect"] == "Deny", f"the statement is {stmt['Effect']!r}, not a Deny"
    cond = stmt["Condition"]
    assert list(cond) and len(cond) == 1, f"expected one condition operator, got {list(cond)}"
    op, = cond
    key, = cond[op]
    assert key == "aws:PrincipalArn", (
        f"the exception is keyed on {key!r}; only aws:PrincipalArn identifies the caller")
    matches = fnmatch.fnmatchcase(principal_arn, cond[op][key])
    if op == "ArnNotLike":
        return not matches
    if op == "ArnLike":
        return matches
    raise AssertionError(
        f"condition operator {op!r} is neither ArnLike nor ArnNotLike, so what this document does "
        f"to a principal cannot be stated; an inert operator denies everyone including break-glass")


def test_the_break_glass_exception_is_written_as_arn_not_like():
    """The shape half of M04. `ArnLike` here would deny ONLY the break-glass role."""
    doc = M.scp_document(BREAK_GLASS)
    stmt, = doc["Statement"]
    assert doc["Version"] == "2012-10-17"
    assert stmt["Effect"] == "Deny"
    assert stmt["Sid"] == "DenyRoute4ExceptBreakGlass"
    assert stmt["Resource"] == "*"
    assert list(stmt["Condition"]) == ["ArnNotLike"], (
        f"the condition operator is {list(stmt['Condition'])}; the positive form would deny only "
        f"the break-glass role, which is the exact inversion of a break-glass exception and would "
        f"still create and attach cleanly, so AWS would never object")
    assert "ArnLike" not in json.dumps(doc)
    assert stmt["Condition"]["ArnNotLike"]["aws:PrincipalArn"] == BREAK_GLASS


def test_the_deny_applies_to_everyone_except_the_break_glass_role():
    """The meaning half of M04, stated as what the document DOES rather than how it reads.

    Under the inversion both assertions flip, which is the point: the two lines below are the only
    place in the repository where the direction of this exception is a checked fact.
    """
    doc = M.scp_document(BREAK_GLASS)
    assert _deny_applies_to(doc, SOME_OTHER_ROLE) is True, (
        "the deny must reach ordinary principals, or the SCP denies nothing at all")
    assert _deny_applies_to(doc, BREAK_GLASS) is False, (
        "the deny must NOT reach the break-glass role; a document that denies only break-glass is "
        "the inversion of the exception the sealed oracle asks to see")


def test_the_denied_actions_are_real_operations_in_the_shipped_model():
    """A typo'd action denies nothing, and creates and attaches without complaint.

    Derived from botocore's `bedrock-agentcore-control` model rather than asserted as strings:
    `bedrock-agentcore:UpdateGateway` is the IAM action for the `UpdateGateway` operation, so the
    operation name has to exist in the model. Kills M05.
    """
    assert M.ROUTE4_ACTIONS, "a document denying nothing is not the Route 4 control"
    for action in M.ROUTE4_ACTIONS:
        service, _, operation = action.partition(":")
        assert service == "bedrock-agentcore", f"{action!r} names the wrong service prefix"
        assert operation in _AC_OPERATIONS, (
            f"{action!r} names {operation!r}, which is not an operation in the shipped "
            f"bedrock-agentcore-control model; a misspelled action denies nothing and the SCP "
            f"would still be created and attached")
    assert set(M.ROUTE4_ACTIONS) == {"bedrock-agentcore:UpdateGateway",
                                     "bedrock-agentcore:UpdateGatewayTarget"}, (
        "Route 4 is the gateway-update route; dropping either action leaves half of it undenied")
    doc = M.scp_document(BREAK_GLASS)
    assert doc["Statement"][0]["Action"] == list(M.ROUTE4_ACTIONS)


def test_the_document_that_reaches_create_policy_is_the_uninverted_one(monkeypatch, tmp_path,
                                                                      capsys):
    """The document as SENT, not as returned by the helper. Also kills M04.

    `main` builds the document and serialises it into `Content`; an edit that inverted the direction
    between the helper and the request would pass every arm above.
    """
    r = _run(monkeypatch, tmp_path, capsys)
    params, = r.cap.params_for("create_policy")
    assert params["Type"] == SCP
    sent = json.loads(params["Content"])
    assert _deny_applies_to(sent, SOME_OTHER_ROLE) is True
    assert list(sent["Statement"][0]["Condition"]) == ["ArnNotLike"]
    arn = sent["Statement"][0]["Condition"]["ArnNotLike"]["aws:PrincipalArn"]
    assert arn.startswith(f"arn:aws:iam::{EXAMPLE_ACCOUNT}:role/") and RUN in arn, (
        "the break-glass principal must be this run's own role in this account, so no other "
        "principal is exempted by accident")
    assert _deny_applies_to(sent, arn) is False
    assert r.payload["authoring"]["break_glass_form"].startswith("ArnNotLike"), (
        "the payload has to name the direction, because a reader of results/ cannot see the code")
    assert r.payload["authoring"]["document"] == sent
    assert "does not require the principal to exist" in " ".join(r.payload["limitations"]), (
        "acceptance says nothing about whether that role resolves, and the record must say so")


# ---------------------------------------------------------------------------
# 2. the service's own verdict, and the SDK/service distinction
# ---------------------------------------------------------------------------

def test_a_service_rejection_is_not_reported_as_a_botocore_refusal(monkeypatch):
    """A request id means AWS answered. Kills M06.

    The distinction is the whole reason this arm exists in the script: a client-side enum check is
    a statement about the SDK, and the finding being published is a statement about the service.
    Conflating them would let "botocore refused to send it" be reported as "AWS rejected it".
    """
    org = FakeOrg()
    cap = Cap(org, describe_effective="service_rejection")
    monkeypatch.setattr(M, "capture", cap)
    out = M.ask_the_service(org, None, Limiter(), target_id="ou-new-1")
    assert out["accepted"] is False
    assert out["request_id"] == "rid-0001"
    assert out["rejected_client_side_by_botocore"] is False, (
        "a failure carrying a request id was answered BY AWS; calling it a botocore refusal turns "
        "a fact about the service into a fact about our SDK")
    assert out["error_code"] == "ValidationException"
    assert out["http_status"] == 400
    assert out["evidence"].endswith("_describe_effective_policy_err.json")
    assert "a request id means the service answered" in out["reading"]


def test_a_botocore_client_side_rejection_has_no_request_id(monkeypatch):
    """The branch a success-only or service-only double never reaches."""
    org = FakeOrg()
    monkeypatch.setattr(M, "capture", Cap(org, describe_effective="client_side"))
    out = M.ask_the_service(org, None, Limiter(), target_id="ou-new-1")
    assert out["accepted"] is False
    assert out["request_id"] == ""
    assert out["rejected_client_side_by_botocore"] is True
    assert out["error_code"] == "ParamValidationError"


def test_an_acceptance_would_be_recorded_as_accepted(monkeypatch):
    """If AWS ever accepts SERVICE_CONTROL_POLICY here, that is the more interesting outcome.

    The script's own docstring says this arm is what would find it, so the arm has to be able to
    report it — a helper that hard-coded `accepted: False` would pass every other test in this file.
    """
    org = FakeOrg()
    monkeypatch.setattr(M, "capture", Cap(org, describe_effective="accepted"))
    out = M.ask_the_service(org, None, Limiter(), target_id="ou-new-1")
    assert out["accepted"] is True
    assert out["rejected_client_side_by_botocore"] is False
    assert out["error_code"] == ""


def test_the_preregistered_call_is_sent_with_policy_type_service_control_policy(monkeypatch,
                                                                               tmp_path, capsys):
    """The request really goes out, and it goes out asking the sealed question.

    Not a paraphrase of it: `PolicyType` must be SERVICE_CONTROL_POLICY and the target must be the
    fresh OU the deny is attached to. Asking about a policy type the enum accepts would produce a
    clean answer to a question nobody sealed.
    """
    r = _run(monkeypatch, tmp_path, capsys)
    params, = r.cap.params_for("describe_effective_policy")
    assert params["PolicyType"] == SCP
    ou_id = r.cap.params_for("attach_policy")[0]["TargetId"]
    assert params["TargetId"] == ou_id
    ans = r.payload["service_answer_to_the_preregistered_call"]
    assert ans["accepted"] is False and ans["request_id"] == "rid-0001"
    assert ans["rejected_client_side_by_botocore"] is False
    assert str(ans["error_code"]) in r.record["notes"][0], (
        "the not_measured reason has to carry what the service actually said, or the claim that "
        "AWS was asked anyway is unverifiable from the record")


# ---------------------------------------------------------------------------
# preconditions: rc=2 and nothing created
# ---------------------------------------------------------------------------

def _asserts_nothing_was_created(r: Run) -> None:
    assert r.rc == 2
    assert r.cap.calls == [], (
        f"the abort happened AFTER {r.cap.ops} — a precondition that fails must fail before any "
        f"organization object exists")
    assert r.emitted == [], "nothing was measured, so nothing may be published"
    # No object with a created-object id shape exists. Compared against the shape rather than
    # against BASE_OUS, because one of these fixtures deliberately starts an OU short.
    assert not [i for i in list(r.org.ous) + list(r.org.policies)
                if i.startswith(("ou-new-", "p-new-"))]
    assert r.org.attachments == {}


def test_a_non_management_account_aborts_with_nothing_measured(monkeypatch, tmp_path, capsys):
    """An SCP can only be authored from the management account; elsewhere every arm is a permission
    error wearing the shape of a finding.

    The caller's account and the organization's `MasterAccountId` are supplied independently, so
    `is_mgmt` is a comparison this fixture can make false — deriving one from the other would make
    the precondition true by construction.
    """
    r = _run(monkeypatch, tmp_path, capsys, org=FakeOrg(master="999988887777"),
             caller=EXAMPLE_ACCOUNT)
    _asserts_nothing_was_created(r)
    assert "preconditions not met" in r.err
    assert "management account" in r.err
    assert "management account: False" in r.out


def test_a_feature_set_other_than_all_aborts_with_nothing_measured(monkeypatch, tmp_path, capsys):
    """Kills M08. A CONSOLIDATED_BILLING organization has no SCPs at all, so every negative result
    would be about the organization's feature set rather than about the API."""
    r = _run(monkeypatch, tmp_path, capsys, org=FakeOrg(feature_set="CONSOLIDATED_BILLING"))
    _asserts_nothing_was_created(r)
    assert "FeatureSet=ALL" in r.err


@pytest.mark.parametrize("status,label", [(None, "absent"), ("PENDING_DISABLE", "pending")],
                         ids=["absent", "pending"])
def test_scp_not_enabled_on_the_root_aborts(monkeypatch, tmp_path, capsys, status, label):
    """Both halves of the root check: the type may be missing, or present and not ENABLED.

    Kills M09 — dropping the `Status == "ENABLED"` half leaves the `pending` case passing, and a
    root mid-disable is exactly the state in which an attach succeeds and enforces nothing.
    """
    r = _run(monkeypatch, tmp_path, capsys, org=FakeOrg(scp_status=status))
    _asserts_nothing_was_created(r)
    assert "SERVICE_CONTROL_POLICY enabled on the root" in r.err


@pytest.mark.parametrize("drop", ["production", "DevOps"])
def test_a_missing_protected_ou_aborts_because_the_list_cannot_be_trusted(monkeypatch, tmp_path,
                                                                         capsys, drop):
    """Kills M07, and this is the arm that keeps the do-not-touch list meaningful.

    `PROTECTED_OU_NAMES` is a list of names in ONE organization. Run against a different
    organization it protects nothing, silently: every name is absent, so nothing is ever matched
    and nothing is ever reported as at risk. Requiring every protected name to be PRESENT before
    creating anything is what turns the list from decoration into a check on which organization
    this is.
    """
    ous = {i: d for i, d in BASE_OUS.items() if d["Name"] != drop}
    r = _run(monkeypatch, tmp_path, capsys, org=FakeOrg(ous=ous))
    _asserts_nothing_was_created(r)
    assert repr(drop) in r.err
    assert "do-not-touch list cannot be trusted" in r.err


def test_a_failed_describe_organization_aborts_rather_than_guessing(monkeypatch, tmp_path, capsys):
    org = FakeOrg()
    org.raises["describe_organization"] = RuntimeError("AWSOrganizationsNotInUseException")
    r = _run(monkeypatch, tmp_path, capsys, org=org)
    assert r.rc == 2
    assert r.cap.calls == []
    assert "Organizations management account" in r.err


def test_the_inventory_reads_every_page_of_both_listings(monkeypatch, tmp_path, capsys):
    """Kills M21. One item per page, so a single-page read sees only the first OU and the first SCP.

    A truncated OU listing makes the protected-OU precondition fail against the very organization
    the script was written for; a truncated policy listing makes the post-teardown alarm fire for
    policies that are present. Both failures point at the wrong cause, which is worse than either.
    """
    r = _run(monkeypatch, tmp_path, capsys, org=FakeOrg(page=1))
    assert r.rc == 0, r.err
    before = r.payload["organization"]["inventory_before"]
    assert before["ou_names"] == ["DevOps", "production"]
    assert before["scp_names"] == ["FullAWSAccess", "devOpsOnly", "productionOnly"]
    tokens = [p["NextToken"] for p in
              [q for o, q in r.org.calls if o == "list_organizational_units_for_parent"]]
    assert any(t is not None for t in tokens), (
        "a paginated fixture that never handed out a NextToken would make this arm vacuous")
    assert "ALARM" not in r.err


def test_the_inventory_filters_the_policy_listing_on_service_control_policy(monkeypatch, tmp_path,
                                                                           capsys):
    """A listing filtered on another policy type reports an organization with no SCPs at all."""
    r = _run(monkeypatch, tmp_path, capsys)
    filters = {p["Filter"] for o, p in r.org.calls if o == "list_policies"}
    assert filters == {SCP}
    targets = {p["Filter"] for o, p in r.org.calls if o == "list_policies_for_target"}
    assert targets == {SCP}


# ---------------------------------------------------------------------------
# the emptiness check, before the attach
# ---------------------------------------------------------------------------

def test_the_fresh_ou_is_proved_empty_before_the_attach(monkeypatch, tmp_path, capsys):
    """Kills M10, in the only direction that matters: ORDER.

    An SCP on an OU containing accounts changes what principals in those accounts may do. A fresh
    OU cannot contain accounts, which is exactly why the check is cheap and exactly why it must not
    be skipped: if the id being used is not the object that was just created, the check is the last
    thing between this script and a deny attached over live workloads. `list_accounts_for_parent`
    must therefore happen BEFORE `create_policy` — after the attach, the damage is already done and
    the abort is a report rather than a prevention.
    """
    r = _run(monkeypatch, tmp_path, capsys)
    assert r.rc == 0, r.err
    checked = [i for i, (op, _) in enumerate(r.org.calls) if op == "list_accounts_for_parent"]
    assert len(checked) == 1
    ou_id = r.cap.params_for("attach_policy")[0]["TargetId"]
    assert [p["ParentId"] for o, p in r.org.calls
            if o == "list_accounts_for_parent"] == [ou_id], (
        "the emptiness of the OU that gets the deny is what matters, not of some other parent")
    assert "confirmed empty" in r.out

    # And the ordering claim itself, which only a populated OU can demonstrate.
    org = FakeOrg()
    populated = Cap(org)
    real_create = populated._create_organizational_unit

    def _create_and_populate(params):
        rec = real_create(params)
        oid = rec.response["OrganizationalUnit"]["Id"]
        org.accounts[oid] = [{"Id": "123456789012", "Name": "a-real-workload"}]
        return rec
    populated._create_organizational_unit = _create_and_populate
    r2 = _run(monkeypatch, tmp_path / "populated", capsys, org=org, cap=populated)
    assert r2.rc == 2
    assert "Aborting before the attach" in r2.err
    assert "create_policy" not in r2.cap.ops, (
        "a policy was created for an OU that already contained accounts; the emptiness check must "
        "run BEFORE the authoring arm, not after it")
    assert "attach_policy" not in r2.cap.ops
    assert r2.org.attachments == {}


# ---------------------------------------------------------------------------
# teardown: the order, and the sweep that does not stop
# ---------------------------------------------------------------------------

def test_teardown_order_is_detach_then_policy_then_nested_ou_then_ou(monkeypatch, tmp_path,
                                                                    capsys):
    """Kills M11. The order is NOT the reverse of creation, and both constraints are AWS's.

    Creation is OU -> nested OU -> policy -> attach. Reversing that gives detach -> policy -> OU ->
    nested OU, which fails on the parent OU (it still has a child) and strands it. The double
    enforces both of AWS's rules — a policy cannot be deleted while attached, an OU cannot be
    deleted while it has children — so a permuted order fails here the way it would fail live.
    """
    r = _run(monkeypatch, tmp_path, capsys)
    assert r.rc == 0, r.err
    creates = [op for op in r.cap.ops if op.startswith("create_") or op == "attach_policy"]
    assert creates == ["create_organizational_unit", "create_organizational_unit",
                       "create_policy", "attach_policy"]

    teardown = [op for op in r.cap.ops
                if op in ("detach_policy", "delete_policy", "delete_organizational_unit")]
    assert teardown == ["detach_policy", "delete_policy",
                        "delete_organizational_unit", "delete_organizational_unit"], (
        f"teardown ran {teardown}; a policy cannot be deleted while attached and an OU cannot be "
        f"deleted while it has children, so the reverse of creation order fails on its first step "
        f"and strands everything after it")

    ou_id = r.cap.params_for("attach_policy")[0]["TargetId"]
    deleted_ous = [p["OrganizationalUnitId"] for p in
                   r.cap.params_for("delete_organizational_unit")]
    assert deleted_ous[-1] == ou_id, "the parent OU must be deleted last, after its child"
    assert deleted_ous[0] != ou_id
    assert r.payload["residue"]["clean"] is True, r.payload["residue"]


def test_a_failed_detach_does_not_strand_the_rest_of_the_sweep(monkeypatch, tmp_path, capsys):
    """Kills M12. Each step's failure is recorded per object rather than aborting the sweep.

    A detach that fails leaves the policy attached, so the delete will fail too — but the two OUs
    can still go, and stopping at the first failure would leave three objects behind instead of
    one. rc must still report residue, and the residue must name the survivor.
    """
    org = FakeOrg()
    cap = Cap(org, fail={"detach_policy": ("ConcurrentModificationException", "try again")})
    r = _run(monkeypatch, tmp_path, capsys, org=org, cap=cap)
    assert [op for op in r.cap.ops if op.startswith(("detach", "delete"))] == [
        "detach_policy", "delete_policy",
        "delete_organizational_unit", "delete_organizational_unit"], (
        "the sweep stopped early: a failed detach must not strand the OUs, which are deletable")
    res = r.payload["residue"]
    assert r.rc == 2
    assert res["clean"] is False
    assert res["surviving"], "the policy is still attached and still exists; it is residue"
    assert set(r.org.ous) == set(BASE_OUS), "both OUs were still swept"
    assert "Delete these by hand" in r.err


def test_nothing_is_detached_when_nothing_was_ever_attached(monkeypatch, tmp_path, capsys):
    """A detach of an attachment that does not exist is a call that can only produce a
    misleading error in the log, and `attached` is what gates it."""
    org = FakeOrg()
    cap = Cap(org, fail={"attach_policy": ("AccessDeniedException", "no")})
    r = _run(monkeypatch, tmp_path, capsys, org=org, cap=cap)
    assert "detach_policy" not in r.cap.ops
    assert "delete_policy" in r.cap.ops, (
        "the policy was created even though the attach failed, so it must still be deleted")
    assert r.payload["structure"] == {}, (
        "with no attachment there is no structural observation to report, and an empty dict is "
        "the honest record of that")
    assert r.payload["authoring"]["accepted"] is True
    assert r.rc == 0
    assert r.payload["residue"]["clean"] is True


def test_teardown_and_emit_run_even_when_an_arm_above_them_aborts(monkeypatch, tmp_path, capsys):
    """Kills M20. The `finally` must sweep and publish, and must NOT swallow the abort into rc=0.

    The abort here is a transport failure in the structural read — after the OU, the nested OU, the
    policy and the attachment all exist, which is the worst moment for the process to stop. Both
    halves are asserted: the objects are gone, the record is published, and the exception still
    escapes. A swallowed exception would return rc=0 for a run that measured half of itself.
    """
    org = FakeOrg()
    org.raises["list_policies_for_target"] = RuntimeError("connection reset by peer")
    cap = Cap(org)
    r = _run(monkeypatch, tmp_path, capsys, org=org, cap=cap, expect_raises=RuntimeError)
    assert r.rc is None, "main returned instead of propagating; the abort was swallowed"
    assert [op for op in r.cap.ops if op.startswith(("detach", "delete"))] == [
        "detach_policy", "delete_policy",
        "delete_organizational_unit", "delete_organizational_unit"]
    assert set(r.org.ous) == set(BASE_OUS), "the created OUs outlived the abort"
    assert set(r.org.policies) == set(BASE_POLICIES)
    assert r.emitted, "the finally must publish what WAS observed, even after an abort"
    assert r.record["verdict"] == O.INCONCLUSIVE
    assert r.payload["residue"]["clean"] is True
    assert r.payload["structure"] == {}, "the arm that aborted contributed no observation"


# ---------------------------------------------------------------------------
# residue, from TWO lists
# ---------------------------------------------------------------------------

def test_a_lying_delete_is_caught_by_the_post_teardown_inventory(monkeypatch, tmp_path, capsys):
    """Kills M13, and this is why the residue comes from the inventory and not the delete results.

    The double reports `ok=True` for the fresh OU's delete and leaves the OU listed under root.
    EVERY deletion row says success — that is the point, and it is asserted below rather than
    assumed — so a residue computed from those rows reports CLEAN while a real OU survives in a real
    organization. That is the one direction of error that leaves a permanent artefact behind.
    """
    org = FakeOrg()
    cap = Cap(org, lie_delete_top_level_ou=True)
    r = _run(monkeypatch, tmp_path, capsys, org=org, cap=cap)
    res = r.payload["residue"]
    assert res["n_delete_attempted"] == 3, "policy + nested OU + OU, detach excluded"
    ou_id = r.cap.params_for("attach_policy")[0]["TargetId"]
    assert res["surviving"] == [ou_id], (
        f"every delete reported ok and the inventory still lists {ou_id}; a residue derived from "
        f"the deletion results alone would have called this clean")
    assert ou_id in r.org.ous, "the fixture must really have left the OU behind"
    assert res["never_attempted"] == []
    assert res["nested_ou_deleted"] is True, (
        "the nested OU really went, so nested_ou_deleted cannot be what makes this run dirty")
    assert res["inventory_unchanged"] is False
    assert res["clean"] is False
    assert r.rc == 2
    assert "an orphan SCP or OU is a permanent artefact" in r.err


def test_a_created_object_whose_delete_never_happened_is_residue(monkeypatch, tmp_path, capsys):
    """Kills M14 — `never_attempted`, the other half of the two-list rule.

    Reached by a create that succeeds while its response carries no `Id`: the script records having
    created something and holds no identifier for it, so no delete can name it and no deletion row
    mentions it. `clean` must be False on the strength of that alone.

    The fixture ALSO makes the create produce no object, and that is deliberate rather than
    incidental: it is what isolates this field. If the object really existed it would appear in the
    post-teardown inventory, `surviving` and `inventory_unchanged` would both fire, and dropping
    `never_attempted` from `clean` would change nothing observable — the arm would be vacuous. What
    is asserted here is a claim about the script's KNOWLEDGE: it cannot tell whether the object
    exists, because it has no id to ask about, and an unknown is not clean.
    """
    org = FakeOrg()
    cap = Cap(org, blank_ids={"create_organizational_unit"},
              lie={"create_organizational_unit"})
    r = _run(monkeypatch, tmp_path, capsys, org=org, cap=cap)
    res = r.payload["residue"]
    assert res["never_attempted"], (
        "a created object with no id has no deletion row at all; if that is not residue, the "
        "residue check reports clean exactly when something survived")
    assert "" in res["never_attempted"]
    assert res["n_created"] == 3 and res["n_delete_attempted"] == 1, (
        "three objects recorded as created, and only the policy had an id to delete")
    # The other three fields are all clean, so `never_attempted` is the only thing that can be
    # making `clean` False here.
    assert res["surviving"] == []
    assert res["nested_ou_deleted"] is True
    assert res["inventory_unchanged"] is True
    assert res["clean"] is False
    assert r.rc == 2
    assert "never_attempted=" in r.err


def test_the_nested_ous_delete_result_is_folded_in_explicitly(monkeypatch, tmp_path, capsys):
    """Kills M15. A nested OU is not listed under root, so `ou_ids` structurally cannot see it.

    `list_organizational_units_for_parent(ParentId=root)` returns DIRECT children only, so the
    nested OU's absence from `after["ou_ids"]` proves nothing whatever — it was never going to be
    there. Its delete result is the only signal that exists, and this fixture makes that signal say
    failure while everything else looks clean: the child's delete reports
    `ConcurrentModificationException`, the parent's delete then succeeds honestly, the inventory
    matches, and nothing survives.

    Isolating it this way needs a LYING service rather than a merely failing one, and the reason is
    worth writing down: in a coherent organization an undeleted child BLOCKS its parent's deletion,
    so a plain failure on the child makes `surviving` fire as well and the arm would prove nothing
    about `nested_ou_deleted`. What is asserted is therefore the conservative reading — a delete
    whose only available signal says it failed must be treated as a survivor, because the script has
    no second channel to check it against.
    """
    org = FakeOrg()
    cap = Cap(org, nested_delete_reports_failure=True)
    r = _run(monkeypatch, tmp_path, capsys, org=org, cap=cap)
    res = r.payload["residue"]
    assert res["nested_ou_deleted"] is False
    # Every other field is clean, so this is the only one that can be making `clean` False.
    assert res["surviving"] == []
    assert res["never_attempted"] == []
    assert res["inventory_unchanged"] is True
    assert res["clean"] is False
    assert r.rc == 2

    after = r.payload["organization"]["inventory_after"]
    nested_id = [p["OrganizationalUnitId"] for p in
                 r.cap.params_for("delete_organizational_unit")][0]
    assert nested_id not in after["ou_ids"], (
        "a nested OU is never listed under root, so `surviving` structurally cannot report it and "
        "nested_ou_deleted is the only place its fate is recorded")
    assert nested_id not in r.org.ous, (
        "in this fixture the child really did go and the service said otherwise; the script cannot "
        "know that, and reporting residue off the failed result is the conservative direction")


def test_a_changed_inventory_is_residue_even_with_nothing_surviving(monkeypatch, tmp_path, capsys):
    """Kills M16. Every created object was deleted, and the organization still is not as it was.

    The scenario is a protected OU that vanished during the run — the stray delete the before/after
    comparison exists to catch. Nothing this script created survives, so `surviving`,
    `never_attempted` and `nested_ou_deleted` are all clean, and only `inventory_unchanged`
    disagrees.
    """
    org = FakeOrg()
    cap = Cap(org)
    real_detach = cap._detach_policy

    def _detach_and_lose_an_ou(params):
        org.ous.pop(DEVOPS_ID, None)          # somebody else's OU, gone mid-run
        return real_detach(params)
    cap._detach_policy = _detach_and_lose_an_ou

    r = _run(monkeypatch, tmp_path, capsys, org=org, cap=cap)
    res = r.payload["residue"]
    assert res["surviving"] == [] and res["never_attempted"] == []
    assert res["nested_ou_deleted"] is True
    assert res["inventory_unchanged"] is False
    assert res["clean"] is False
    assert r.rc == 2
    before = r.payload["organization"]["inventory_before"]
    after = r.payload["organization"]["inventory_after"]
    assert "DevOps" in before["ou_names"] and "DevOps" not in after["ou_names"]


def test_a_protected_policy_missing_after_teardown_raises_an_alarm(monkeypatch, tmp_path, capsys):
    """Kills M17. The named policies are checked by NAME after teardown, on stderr.

    `inventory_unchanged` already goes False here, so this alarm is redundant for the exit code and
    is not redundant for the operator: rc=2 says "residue", and only this line says WHICH
    pre-existing policy is gone — the difference between re-running and restoring an SCP by hand.
    """
    org = FakeOrg()
    cap = Cap(org)
    real_delete = cap._delete_policy

    def _delete_and_lose_a_protected_policy(params):
        org.policies.pop(PRODONLY_ID, None)
        return real_delete(params)
    cap._delete_policy = _delete_and_lose_a_protected_policy

    r = _run(monkeypatch, tmp_path, capsys, org=org, cap=cap)
    assert "ALARM" in r.err
    assert "'productionOnly'" in r.err
    assert "no longer present after teardown" in r.err
    assert r.rc == 2
    assert set(M.PROTECTED_POLICY_NAMES) == {"FullAWSAccess", "devOpsOnly", "productionOnly"}
    assert set(M.PROTECTED_OU_NAMES) == {"production", "DevOps"}


def test_a_clean_run_returns_zero_and_reports_the_organization_back_to_its_inventory(
        monkeypatch, tmp_path, capsys):
    """rc=0 means the arms RAN and the organization verified back — never that the document was
    right. The verdict in the same payload is INCONCLUSIVE, and both are correct at once."""
    r = _run(monkeypatch, tmp_path, capsys)
    assert r.rc == 0, r.err
    res = r.payload["residue"]
    assert res == {**res, "clean": True, "surviving": [], "never_attempted": [],
                   "nested_ou_deleted": True, "inventory_unchanged": True}
    assert res["n_created"] == 3, "OU, nested OU, policy"
    assert res["n_delete_attempted"] == 3
    assert r.org.ous == BASE_OUS and r.org.policies == BASE_POLICIES
    assert r.record["verdict"] == O.INCONCLUSIVE, (
        "rc=0 reports that the test ran; the verdict is a separate statement and the two must not "
        "be read off each other")
    assert r.payload["organization"]["inventory_before"]["ou_names"] == (
        r.payload["organization"]["inventory_after"]["ou_names"])
    blockers = O.amendment_blockers(r.record)["blockers"]
    assert blockers and any("INCONCLUSIVE" in b for b in blockers), (
        "an unmeasured case must never be amendment-eligible")


def test_the_authoring_never_ran_branch_is_documented_as_unreachable():
    """EXPECTED SURVIVOR, stated rather than quietly left uncovered.

    `if not authoring: return 2` cannot be reached. `authoring` is assigned unconditionally from
    `create_policy`'s record before `r.ok` is inspected, and every earlier exit inside the `try` is
    an explicit `return 2` whose value wins over anything after the `finally`; an exception
    propagates instead of falling through. So no mutation of that branch is observable and no arm
    in this file claims to cover it. It is defensive depth for a future edit that adds a path
    between the emptiness check and the create — and this arm is what will notice if that edit
    arrives, because the assertion below will stop holding.
    """
    body = SRC.split("def main(", 1)[1]
    assert "if not authoring:" in body, (
        "the guard was removed; re-read whether it is reachable now")
    assert body.count("authoring = {") == 1, (
        "authoring is assigned in more than one place; the unreachability argument above depended "
        "on there being exactly one unconditional assignment")
    # The authoring arm, from the throttle before the create to the guard that reads its result.
    arm = body.split('lim.wait("CreatePolicy")', 1)[1].split("if not authoring:", 1)[0]
    assert arm.index("authoring = {") < arm.index("if not r.ok:"), (
        "authoring must be built BEFORE the create's outcome is branched on, or a rejected create "
        "would leave it empty and the branch would fire on a run that did measure the rejection")
    # Every early exit inside the `try` is an explicit `return`, which is what makes the branch
    # unreachable: nothing falls through to it with `authoring` still empty. A `pass` or a `break`
    # there would change that, so the shape is pinned by AST rather than by reading.
    main_fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    try_node, = [n for n in main_fn.body if isinstance(n, ast.Try) and n.finalbody]
    exits = [n for n in ast.walk(try_node) if isinstance(n, (ast.Break, ast.Continue))]
    assert not exits, (
        "the try block now contains a break/continue, so a path can reach `if not authoring` "
        "without having run the authoring arm; that branch is no longer unreachable and needs a "
        "behavioural arm rather than this one")


# ---------------------------------------------------------------------------
# blast radius: what is created, what is never touched
# ---------------------------------------------------------------------------

def test_every_created_name_carries_the_owned_prefix_and_the_run_id(monkeypatch, tmp_path, capsys):
    """Anything not matching the prefix is somebody else's, and the run id is what makes an
    orphan attributable to a run rather than to the project."""
    r = _run(monkeypatch, tmp_path, capsys)
    names = [p["Name"] for p in r.cap.params_for("create_organizational_unit")]
    names += [p["Name"] for p in r.cap.params_for("create_policy")]
    assert len(names) == 3
    for name in names:
        assert name.startswith(M.OWNED_PREFIX), f"{name!r} is outside the owned namespace"
        assert RUN in name, f"{name!r} cannot be attributed to a run"
        assert len(name) <= 128, "Organizations rejects a name over 128 characters"
    assert len(set(names)) == 3, "two objects sharing a name make a teardown ambiguous"


def test_nothing_the_script_did_not_create_is_ever_deleted_or_attached(monkeypatch, tmp_path,
                                                                       capsys):
    """The pre-existing OUs and policies are named in the script and are never a call's subject."""
    r = _run(monkeypatch, tmp_path, capsys)
    created_ids = {r.cap.params_for("attach_policy")[0]["TargetId"],
                   r.cap.params_for("attach_policy")[0]["PolicyId"]}
    touched = set()
    for op, params in r.cap.calls:
        if op.startswith(("delete_", "detach_", "attach_")):
            touched |= {v for v in params.values() if isinstance(v, str)}
    assert touched, "a zero-site scan is an error, not a pass"
    assert not (touched & PROTECTED_IDS), (
        f"a mutating call named a pre-existing object: {sorted(touched & PROTECTED_IDS)}")
    assert ROOT_ID not in touched, (
        "the root is never an attach target here; an SCP on the root applies to every account in "
        "the organization")
    assert created_ids <= touched


def test_the_policy_is_attached_to_the_fresh_ou_only(monkeypatch, tmp_path, capsys):
    r = _run(monkeypatch, tmp_path, capsys)
    attaches = r.cap.params_for("attach_policy")
    assert len(attaches) == 1
    ou_id = attaches[0]["TargetId"]
    assert ou_id.startswith("ou-new-")
    s = r.payload["structure"]
    assert s["our_policy_on_fresh_ou"] is True
    assert s["our_policy_leaked_to_root"] is False, (
        "an SCP that reached the root would apply to every account in the organization, which is "
        "the one outcome this case must be able to notice")
    assert s["attached_to_root"] == [], "the root carried no SCP in the fixture and must carry none"


def test_every_mutating_call_asks_the_limiter_to_wait_first(monkeypatch, tmp_path, capsys):
    """A dropped `wait` is invisible in the result and visible only here (kills H22).

    The second assertion used to record a LIMITATION rather than a property: only `CreatePolicy`
    and `DeletePolicy` had entries in `awsclients.RATE_LIMITS`, so every other `wait` below was a
    NO-OP (`RateLimiter.wait` returns 0.0 for an unknown operation), and the arm pinned WHICH calls
    were unpaced so that the day an entry was added it would fire and the sentence would be
    re-read instead of quietly becoming false.

    That day was 2026-08-13. The repo-wide cross-check found 14 of the 29 waited names missing from
    `RATE_LIMITS`, every Organizations operation this case touches was given a self-imposed rate,
    and this arm fired with `unpaced == []`. So the second assertion is now a property: every call
    this case paces is a call the limiter actually paces. (The old docstring also said `lib/` is
    sealed and this file therefore could not add the ceilings — `lib/stats.py` is sealed;
    `lib/awsclients.py` is not, and the fix landed there.)
    """
    r = _run(monkeypatch, tmp_path, capsys)
    assert r.lim.waited == [
        "CreateOrganizationalUnit", "CreateOrganizationalUnit", "CreatePolicy", "AttachPolicy",
        "DescribeEffectivePolicy", "DetachPolicy", "DeletePolicy",
        "DeleteOrganizationalUnit", "DeleteOrganizationalUnit"], r.lim.waited
    assert A.rate_limit_for("CreatePolicy") == 5.0
    assert A.rate_limit_for("DeletePolicy") == 5.0
    unpaced = sorted({op for op in r.lim.waited if A.rate_limit_for(op) is None})
    assert unpaced == [], (
        f"{unpaced} are waited on by this case but absent from RATE_LIMITS, so those waits sleep "
        f"for nothing while reading as rate limiting — the defect lib/tests/test_rate_limits.py "
        f"exists to prevent. Add a rate (marked self-imposed if it is ours) rather than accepting "
        f"a wait that does nothing")
    # And the Organizations rates are OURS. The management-account control plane publishes no
    # per-second ceiling for these, so a record that presented them as AWS's would be citing our
    # caution as a fact about the service.
    for op in ("CreateOrganizationalUnit", "DeleteOrganizationalUnit", "AttachPolicy",
               "DetachPolicy", "DescribeEffectivePolicy"):
        assert op in A.SELF_IMPOSED_LIMITS, f"{op}'s rate is no longer marked as self-imposed"


def test_the_evidence_store_is_written_and_every_captured_call_carries_a_path(monkeypatch,
                                                                             tmp_path, capsys):
    """A call whose record has no path is a call whose evidence cannot be found again."""
    r = _run(monkeypatch, tmp_path, capsys)
    ev = tmp_path / "ev" / RUN / M.FAMILY / CASE
    assert (ev / "environment.json").is_file(), (
        "the environment file is what pins the SDK and the prereg hash to this run's records")
    env = json.loads((ev / "environment.json").read_text(encoding="utf-8"))
    assert env["case_id"] == CASE and env["family"] == M.FAMILY
    assert r.payload["authoring"]["evidence"].endswith(".json")
    assert r.payload["service_answer_to_the_preregistered_call"]["evidence"].endswith(".json")


def test_the_record_reason_carries_the_numbers_the_finding_rests_on(monkeypatch, tmp_path, capsys):
    """`not_measured` refuses an empty reason; this pins that the reason is the FINDING.

    An INCONCLUSIVE with no stated cause is indistinguishable from a straddling interval, and the
    two have opposite remedies. The counts and the difference are what make this one diagnosable
    without opening the payload.
    """
    r = _run(monkeypatch, tmp_path, capsys)
    reason = r.record["evidence"]["reason"]
    assert "does not cover SCPs" in reason
    assert str(len(EFF_ENUM)) in reason and str(len(CREATE_ENUM)) in reason
    assert SCP in reason and RCP in reason
    assert "No substitute call is reported under this oracle's name" in reason
    detail = r.record["evidence"]["detail"]
    assert detail["authoring_accepted"] is True
    assert detail["attached"] is True
    assert detail["sdk"] == A.sdk_versions()
    assert r.record["n_met"] is True, (
        "the seal names no n for this case, so there is nothing to fall short of; a False here "
        "would add a shortfall blocker that misdescribes why the case is INCONCLUSIVE")
    assert r.record["mutation_required"] is False


def test_what_true_does_not_prove_is_written_down_even_though_there_is_no_true(monkeypatch,
                                                                              tmp_path, capsys):
    """The empty OU is the whole reason this case has no evidence about effect on principals.

    An authoring acceptance is a statement about the organization accepting a document. A reader
    who took it for enforcement would have the wrong idea about Route 4, and the payload is where
    that has to be blocked.
    """
    r = _run(monkeypatch, tmp_path, capsys)
    text = r.payload["what_true_does_not_prove"]
    assert "There is no TRUE here to qualify" in text
    assert "F5-3c" in text, "in-account enforcement is a different sealed case and must be named"
    assert "deliberately EMPTY" in text
    assert "cannot be followed" in r.payload["why_this_matters_operationally"], (
        "the operational consequence is that a runbook citing DescribeEffectivePolicy is "
        "unfollowable; that is the finding an operator needs")
    assert r.payload["expiry"] == "2026-08-20T00:00:00+00:00"


# ---------------------------------------------------------------------------
# the declared plan
# ---------------------------------------------------------------------------

def _dry(*extra):
    r = subprocess.run([PY, str(SCRIPT), "--dry-run", *extra], cwd=ROOT, capture_output=True,
                       text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_the_dry_run_declares_the_missing_instrument_and_makes_no_aws_call():
    """The dry run is the last moment before the money is spent at which the question can be
    compared with the instrument, so it must print the comparison and not the plan alone."""
    out = _dry()
    assert "DRY RUN" in out
    assert O.oracle_text(CASE) in out
    assert "THE PRE-REGISTERED INSTRUMENT DOES NOT COVER SCPs." in out
    assert f"PolicyType enum ({len(EFF_ENUM)})" in out
    for member in EFF_ENUM:
        assert member in out, f"{member} is missing from the enumerated list"
    assert f"CreatePolicy Type enum has {len(CREATE_ENUM)}" in out
    assert f"'{SCP}', '{RCP}'" in out
    assert "supported by DescribeEffectivePolicy: False" in out
    assert "does NOT substitute a different call" in out
    assert "billable: no" in out


def test_the_dry_run_declares_the_break_glass_direction_and_teardown_order():
    """Kills H23. The two things a reader cannot infer from the object list.

    The direction of the exception and the asymmetry of teardown are both decisions that look
    arbitrary until they are stated, and a dry run that omitted them would leave the operator
    unable to check either before the live run.
    """
    out = _dry()
    assert "ArnNotLike, not ArnLike" in out
    assert "deny ONLY the break-glass role" in out
    assert "detach -> delete policy ->" in out
    assert "delete nested OU -> delete OU" in out
    assert "NOT the reverse of creation order" in out
    assert "fresh EMPTY child OU" in out
    assert str(M.PROTECTED_OU_NAMES) in out and str(M.PROTECTED_POLICY_NAMES) in out
    assert "F5-3c" in out, "the case that owns in-account enforcement has to be named here too"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
