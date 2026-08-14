#!/usr/bin/env python3
"""`runner/iam_policy.py` — the derivation, and the two properties that make it safe to attach.

The policy is generated, so the thing worth testing is not its text but that it stays a
DERIVATION: every API the validation has been measured making is mapped, nothing is scoped wider
than it has to be, and the file itself discloses no identifier.

The account ID is assembled from halves where one is needed, the same convention
`lib/tests/test_redact.py` uses — a test for a redaction-sensitive property that itself needs a
redaction waiver has stopped being evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner"))

import iam_policy as IP          # noqa: E402

ACCT = "0000" + "00000000"
REGION = "us-east-1"
BUCKET = "grx-validation-runner-test"

_HAS_EVIDENCE = bool(list((ROOT / "evidence").glob("*/*/*/*.json")))
needs_evidence = pytest.mark.skipif(
    not _HAS_EVIDENCE,
    reason="evidence/ is local-only and gitignored; the derivation cannot run in a fresh clone")


# ------------------------------------------------------------------ the derivation

@needs_evidence
def test_every_api_the_validation_has_called_is_mapped_to_an_action():
    """The whole point. A case that starts calling a new API fails HERE, at desk, rather than
    at 2am on the instance with an AccessDenied nobody is awake to read."""
    missing = IP.unmapped_operations()
    assert missing == [], (
        "these (service, operation) pairs appear in evidence/ with no MAPPING entry:\n"
        + "\n".join(f"  {s}.{o}" for s, o in missing)
        + "\nAdd each with the IAM action it needs and the narrowest scope that works.")


def test_a_refused_operation_is_accounted_for_without_being_granted():
    """`MEASURED_NOT_GRANTED` exists so the audit can be satisfied by a written refusal rather than
    only by a grant. Both halves are asserted: the pair no longer reads as unmapped, and not one of
    the actions it names appears anywhere in the document."""
    assert IP.MEASURED_NOT_GRANTED, "the mechanism is empty, so the assertions below are vacuous"
    for pair in IP.MEASURED_NOT_GRANTED:
        assert pair not in IP.MAPPING, f"{pair} is both mapped and refused — pick one"
    granted = {a for st in IP.document(ACCT, REGION, BUCKET)["Statement"] for a in st["Action"]}
    # Spelled from the operation name rather than hardcoded, so a second entry is covered too.
    for service, op in IP.MEASURED_NOT_GRANTED:
        action = f"{service}:{''.join(p.title() for p in op.split('_'))}"
        assert action not in granted, f"{action} is refused in MEASURED_NOT_GRANTED and granted"


def test_every_refusal_carries_a_written_reason():
    """Same rule as RUNNER_EXTRAS: a refusal with no reason is a refusal nobody can revisit. The
    reason has to be data, not a comment, so an entry cannot be added without one."""
    assert all(isinstance(v, str) and len(v) > 40 for v in IP.MEASURED_NOT_GRANTED.values()), \
        [k for k, v in IP.MEASURED_NOT_GRANTED.items()
         if not (isinstance(v, str) and len(v) > 40)]


def test_the_refusal_list_cannot_be_used_to_silence_an_unmapped_call(monkeypatch):
    """The mechanism's risk, stated as a test. `MEASURED_NOT_GRANTED` makes the audit satisfiable
    without a grant, which is exactly what a future maintainer would reach for to make a red gate go
    green — so it must not be able to hide a pair nobody has considered. It cannot: entries are
    written by hand with a reason, and an operation NOT in either dict is still reported."""
    monkeypatch.setattr(IP, "measured_operations",
                        lambda: {("iam", "create_user"): 1, ("iam", "update_assume_role_policy"): 1})
    assert IP.unmapped_operations() == [("iam", "create_user")]


@needs_evidence
def test_the_derivation_reads_a_non_trivial_number_of_calls():
    """Both bounds, per feedback_zero_file_scan_is_error and its inverse. A floor against a
    mis-rooted glob; a floor on distinct pairs against a tree holding one case's calls only."""
    counts = IP.measured_operations()
    assert sum(counts.values()) >= 10_000, f"only {sum(counts.values())} archived calls found"
    assert len(counts) >= 30, f"only {len(counts)} distinct (service, operation) pairs found"


def test_an_empty_evidence_tree_raises_instead_of_yielding_an_empty_policy(monkeypatch, tmp_path):
    """The failure DIRECTION. An empty derivation must not read as "no permissions needed"."""
    monkeypatch.setattr(IP, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="read nothing"):
        IP.measured_operations()


@needs_evidence
def test_the_measured_role_names_all_carry_the_prefix_the_policy_scopes_to():
    """`NAME_PREFIX` is the load-bearing half of the IAM scope, so it is checked against the
    archived `create_role` params rather than against the comment beside it."""
    seen = []
    for path in (IP.ROOT / "evidence").glob("*/*/*/*_create_role_ok.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        name = (rec.get("params") or {}).get("RoleName")
        if name:
            seen.append(name)
    assert seen, "no archived create_role call to check the prefix against"
    assert all(n.startswith(IP.NAME_PREFIX) for n in seen), sorted(set(seen))


# ---------------------------------------------- the implicit-permission class (tagged creates)

# Every `capture(..., Tags=...)` site in the repo, with the service and the IAM action the tag
# argument requires. This table is REVIEWED KNOWLEDGE; the scan below is the tripwire that keeps it
# honest in both directions.
#
# Why this file needs a whole extra mechanism: `MAPPING` is keyed on (service, operation) pairs read
# out of the evidence tree, so `unmapped_operations()` can only ever find actions that correspond to
# a call SOMEBODY MADE. An action required by an ARGUMENT to a different call is structurally
# invisible to it. That blind spot cost four live runs on the instance — `bedrock:TagResource`,
# then the two-sided assume-role gate, then `iam:ListAttachedRolePolicies`, then `iam:TagPolicy` —
# at roughly five minutes of IAM propagation each, and the third round was performed by explicitly
# enumerating both scripts' capture() calls at once, which still missed it. Enumerating operation
# names harder was never going to work. This scans arguments instead.
#
# A tagged create fails WHOLE when the tagging action is missing: CreatePolicy with `Tags=` returns
# AccessDenied naming `iam:TagPolicy` and creates nothing. So a missing entry here is not a cosmetic
# gap — it is a case that cannot run.
TAGGED_CREATE_SITES: dict[tuple[str, str], tuple[str, str]] = {
    ("f1_config/03_permit_trap.py", "create_policy_engine"):
        ("bedrock-agentcore-control", "bedrock-agentcore:TagResource"),
    ("f3_efficacy/00_guardrails.py", "create_guardrail"): ("bedrock", "bedrock:TagResource"),
    ("f5_redteam/03_route4_permissions_boundary.py", "create_policy"): ("iam", "iam:TagPolicy"),
    ("f7_observability/01_tracing_mutation.py", "create_delivery"): ("logs", "logs:TagResource"),
    ("f8_regional/08_policy_engine_regions.py", "create_policy_engine"):
        ("bedrock-agentcore-control", "bedrock-agentcore:TagResource"),
    ("infra/01_iam.py", "create_role"): ("iam", "iam:TagRole"),
    ("infra/02_lambda.py", "create_role"): ("iam", "iam:TagRole"),
    ("infra/02_lambda.py", "create_function"): ("lambda", "lambda:TagResource"),
    ("infra/03_policy_engine.py", "create_policy_engine"):
        ("bedrock-agentcore-control", "bedrock-agentcore:TagResource"),
    ("infra/07_traces.py", "create_log_group"): ("logs", "logs:TagResource"),
    ("infra/07_traces.py", "tag_resource"): ("logs", "logs:TagResource"),
    ("infra/07_traces.py", "create_delivery"): ("logs", "logs:TagResource"),
    ("lib/phase1.py", "create_guardrail"): ("bedrock", "bedrock:TagResource"),
}

_TAG_KWARGS = {"Tags", "tags", "TagList", "tagList"}


def _tagged_create_sites() -> set[tuple[str, str]]:
    """Every `capture(store, "<op>", <client>, ..., Tags=...)` in the repo, as (relpath, op).

    AST rather than a regex, for the reason `lib/tests/test_rate_limits.py` documents at length:
    a textual scan for `Tags=` matches dict literals, docstrings and vendored library source, and
    parsing sees calls where a regex sees characters that look like calls.

    Keyed on (path, op) and not on line number: line numbers move whenever anything above them is
    edited, and a tripwire that goes red on an unrelated edit is a tripwire someone deletes.
    """
    import ast
    out: set[tuple[str, str]] = set()
    for path in ROOT.rglob("*.py"):
        if any(p.startswith(".venv") for p in path.parts) or "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "capture"):
                continue
            if not {k.arg for k in node.keywords if k.arg} & _TAG_KWARGS:
                continue
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str):
                out.add((path.relative_to(ROOT).as_posix(), node.args[1].value))
    return out


def test_the_tagged_create_scan_finds_a_non_trivial_number_of_sites():
    """feedback_zero_file_scan_is_error. A scan that matched nothing — a renamed `capture`, a
    mis-rooted rglob — would make the two assertions below pass while checking nothing."""
    sites = _tagged_create_sites()
    assert len(sites) >= 10, f"only {len(sites)} tagged create sites found — the scan is broken"


def test_every_tagged_create_also_grants_the_tagging_action():
    """The property, and the whole reason this section exists.

    Stated as COVERAGE, not co-location: the tagging action does not have to sit on the create's own
    MAPPING entry, it has to be granted on a resource the created object matches. The first draft of
    this test demanded co-location and contradicted
    `test_the_log_tagging_grant_is_not_described_more_narrowly_than_it_is` — `logs:TagResource` has
    to be on `any` for deliveries, so a second `log_group`-scoped copy for `create_log_group` would
    be a bound that is not in force. Both properties hold at once only under this formulation, and
    the pair of them disagreeing is what showed the first one was wrong.

    Coverage is checked against the emitted Resource lists rather than assumed from the scope name,
    which is the mistake that produced the `iam:CreatePolicy`-on-`role/grx-*` scope bug: a
    managed-policy ARN cannot match a `role/` pattern, so that grant read as scoped and denied
    every call.
    """
    doc = IP.document(ACCT, REGION, BUCKET)
    by_action: dict[str, set[str]] = {}
    for st in doc["Statement"]:
        for action in st["Action"]:
            by_action.setdefault(action, set()).update(st["Resource"])
    scope_resources = {st["Sid"]: set(st["Resource"]) for st in doc["Statement"]}

    problems = []
    for (relpath, op), (service, tag_action) in sorted(TAGGED_CREATE_SITES.items()):
        entry = IP.MAPPING.get((service, op))
        if entry is None:
            problems.append(f"  {relpath}: ({service}, {op}) has no MAPPING entry at all")
            continue
        granted_on = by_action.get(tag_action)
        if not granted_on:
            problems.append(f"  {relpath}: ({service}, {op}) passes tags and {tag_action} is not "
                            f"granted anywhere in the document")
            continue
        sid = "Grx" + entry[1].title().replace("_", "")
        target = scope_resources.get(sid, set())
        if granted_on != {"*"} and not target <= granted_on:
            problems.append(
                f"  {relpath}: ({service}, {op}) creates under {sorted(target)} but {tag_action} is "
                f"granted only on {sorted(granted_on)} — the create is denied outright")
    assert not problems, (
        "these creates pass Tags but the tagging action is not granted on the resource they create, "
        "so the create fails WHOLE with AccessDenied naming the tag action:\n" + "\n".join(problems))


def test_a_newly_tagged_create_cannot_be_added_without_review():
    """The tripwire, in both directions. A `Tags=` added to any create is a red test at desk rather
    than a failed live run; and an entry left behind after a create stops passing tags is reported
    too, so the table cannot quietly become a list of things that used to be true."""
    found = _tagged_create_sites()
    declared = set(TAGGED_CREATE_SITES)
    undeclared = sorted(found - declared)
    assert not undeclared, (
        f"these call sites pass a tag argument and are not in TAGGED_CREATE_SITES: {undeclared}\n"
        f"Add each with the service and the IAM tagging action it requires, and check that action "
        f"is in MAPPING — a tagged create with no tagging grant is denied outright.")
    stale = sorted(declared - found)
    assert not stale, f"declared in TAGGED_CREATE_SITES but no longer passing tags: {stale}"


def test_the_log_tagging_grant_is_not_described_more_narrowly_than_it_is():
    """`logs:TagResource` is on `any` because a delivery ARN ends in a server-assigned id with no
    prefix to bind to. That is a real widening and it is asserted rather than commented, because the
    alternative — keeping a `log_group`-scoped copy beside it — would have read in review as a bound
    that was not in force. Mutant M10's lesson, applied to a different action."""
    doc = IP.document(ACCT, REGION, BUCKET)
    holders = [st for st in doc["Statement"] if "logs:TagResource" in st["Action"]]
    assert len(holders) == 1, (
        f"logs:TagResource appears in {len(holders)} statements; if one of them is prefix-scoped it "
        f"is decorative, because the other grants the same action on a wider resource")
    assert holders[0]["Resource"] == ["*"], holders[0]["Resource"]


# ------------------------------------------------------------------ the scoping

def test_iam_write_actions_are_never_granted_on_a_wildcard_resource():
    """The escalation path this file exists to close: `iam:PutRolePolicy` on `*` lets anyone who
    can reach the instance rewrite any role in the account, including an administrator's."""
    doc = IP.document(ACCT, REGION, BUCKET)
    # Two shapes are allowed, both prefix-bound. `policy/grx-*` arrived with F5-3b's permissions
    # boundaries, which must be MANAGED policies — a boundary cannot be an inline document — so
    # `iam:CreatePolicy` addresses `arn:aws:iam::<acct>:policy/<name>` and no `role/` pattern can
    # match it. The assertion is widened by naming the second pattern rather than by relaxing to
    # "contains grx-", so a third shape appearing later is still a red test.
    allowed_suffixes = (f"role/{IP.NAME_PREFIX}*", f"policy/{IP.NAME_PREFIX}*")
    seen_suffixes = set()
    for st in doc["Statement"]:
        iam_actions = [a for a in st["Action"] if a.startswith("iam:")]
        if not iam_actions:
            continue
        assert st["Resource"] != ["*"], (
            f"{iam_actions} granted on * in {st['Sid']}")
        for r in st["Resource"]:
            assert r.endswith(allowed_suffixes), f"{r} in {st['Sid']} ({iam_actions})"
            seen_suffixes.add(next(s for s in allowed_suffixes if r.endswith(s)))
    assert seen_suffixes == set(allowed_suffixes), (
        f"only {sorted(seen_suffixes)} present — an allowed pattern with nothing on it means the "
        f"list has outlived its reason and should shrink")


def test_a_mapping_scope_that_statements_does_not_emit_raises():
    """Reachable for the first time on 2026-08-13, when `policy` became the fifth scope. The emitted
    order is a literal tuple, so a MAPPING entry naming a scope missing from it would be dropped
    without a word and the policy would deny those calls while looking complete — the same
    failure shape as an empty derivation reading as "nothing needed"."""
    original = dict(IP.MAPPING)
    IP.MAPPING[("iam", "tag_role")] = (("iam:TagRole",), "rolee")   # a plausible typo
    try:
        with pytest.raises(RuntimeError, match="does not emit"):
            IP.document(ACCT, REGION, BUCKET)
    finally:
        IP.MAPPING.clear()
        IP.MAPPING.update(original)
    assert IP.document(ACCT, REGION, BUCKET), "the restore left the module broken"


def test_the_permissions_boundary_policies_are_scoped_to_the_prefix():
    """F5-3b creates managed policies named `grx-f53b-boundary-*`. `iam:CreatePolicy` on `*` would
    let the instance create a policy under any name, which matters because the next call attaches
    one as a BOUNDARY — the object that decides what another role may do."""
    doc = IP.document(ACCT, REGION, BUCKET)
    for action in ("iam:CreatePolicy", "iam:DeletePolicy"):
        holders = [st for st in doc["Statement"] if action in st["Action"]]
        assert len(holders) == 1, f"{action} appears in {len(holders)} statements"
        assert holders[0]["Resource"] == [f"arn:aws:iam::{ACCT}:policy/{IP.NAME_PREFIX}*"], \
            holders[0]["Resource"]
    # The boundary write must not be able to reach a role outside the prefix either: attaching a
    # boundary to someone else's role would restrict a workload this project does not own.
    for action in ("iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary"):
        holders = [st for st in doc["Statement"] if action in st["Action"]]
        assert len(holders) == 1, action
        assert holders[0]["Resource"] == [f"arn:aws:iam::{ACCT}:role/{IP.NAME_PREFIX}*"]


def test_pass_role_is_prefix_scoped():
    """`iam:PassRole` on `*` is equivalent to assuming any role in the account via any service
    that will take one. It is moved onto the role scope explicitly in `statements()`, so this
    asserts the move happened rather than trusting the comment that says it should."""
    doc = IP.document(ACCT, REGION, BUCKET)
    holders = [st for st in doc["Statement"] if "iam:PassRole" in st["Action"]]
    assert len(holders) == 1, "PassRole appears in more than one statement"
    assert holders[0]["Resource"] == [f"arn:aws:iam::{ACCT}:role/{IP.NAME_PREFIX}*"]


def test_every_role_scoped_extra_is_actually_on_the_role_scope():
    """`RUNNER_EXTRAS` defaults every action onto `Resource: ["*"]`, and three of its members are
    steps toward acting as a DIFFERENT identity. `statements()` moves them; this asserts the move
    happened for every member of the tuple, so adding a fourth without wiring it is a red test
    rather than a silent grant on `*`."""
    doc = IP.document(ACCT, REGION, BUCKET)
    role_arn = f"arn:aws:iam::{ACCT}:role/{IP.NAME_PREFIX}*"
    assert IP.ROLE_SCOPED_EXTRAS, "the tuple is empty — the move below would be vacuous"
    for action in IP.ROLE_SCOPED_EXTRAS:
        holders = [st for st in doc["Statement"] if action in st["Action"]]
        assert len(holders) == 1, f"{action} appears in {len(holders)} statements"
        assert holders[0]["Resource"] == [role_arn], (
            f"{action} is granted on {holders[0]['Resource']}, not the {IP.NAME_PREFIX} prefix")


def test_a_role_scoped_extra_that_nothing_declares_raises():
    """Found by mutation, 2026-08-13. `by_scope["role"] |= set(ROLE_SCOPED_EXTRAS)` GRANTS rather
    than moves, so deleting `sts:AssumeRole` from `RUNNER_EXTRAS` produced a byte-identical document
    — the written reason beside it was decorative. The derivation now refuses, which is what makes
    `test_every_runner_extra_carries_a_written_reason` mean something for these three actions."""
    monkey = list(IP.ROLE_SCOPED_EXTRAS) + ["kms:Decrypt"]
    original = IP.ROLE_SCOPED_EXTRAS
    IP.ROLE_SCOPED_EXTRAS = tuple(monkey)
    try:
        with pytest.raises(RuntimeError, match="no MAPPING entry and no RUNNER_EXTRAS"):
            IP.document(ACCT, REGION, BUCKET)
    finally:
        IP.ROLE_SCOPED_EXTRAS = original
    assert IP.document(ACCT, REGION, BUCKET), "the restore left the module broken"


def test_assume_role_cannot_reach_a_role_this_project_does_not_own():
    """F5-3b needs `sts:AssumeRole` because it runs AS the boundaried identity it is measuring.
    On `*` that would let anything reaching the instance become any role in the account that
    trusts it — including roles belonging to the account's other workloads. Named separately from
    the loop above because this is the specific one added late (2026-08-13) and the one whose
    scope a reader of that diff needs to see asserted."""
    doc = IP.document(ACCT, REGION, BUCKET)
    granted = {a for st in doc["Statement"] for a in st["Action"]}
    assert "sts:AssumeRole" in granted, "F5-3b cannot run without it"
    for st in doc["Statement"]:
        if "sts:AssumeRole" not in st["Action"]:
            continue
        for res in st["Resource"]:
            assert res.endswith(f"role/{IP.NAME_PREFIX}*"), res
            assert res != "*", st["Sid"]
    # The wider family stays out: these would let the instance mint credentials by other routes,
    # and no arm of any case needs one.
    for forbidden in ("sts:AssumeRoleWithWebIdentity", "sts:AssumeRoleWithSAML",
                      "sts:GetFederationToken", "sts:SetSourceIdentity"):
        assert forbidden not in granted, forbidden


def test_no_action_is_a_service_wildcard():
    """`bedrock:*` would make the derivation decorative."""
    for st in IP.document(ACCT, REGION, BUCKET)["Statement"]:
        for action in st["Action"]:
            assert not action.endswith(":*"), action
            assert action != "*", st["Sid"]


def test_the_transport_cannot_destroy_its_own_audit_trail():
    """The instance uploads evidence and results. It must not be able to delete them, or a run
    that goes wrong can erase the record of having gone wrong."""
    for st in IP.document(ACCT, REGION, BUCKET)["Statement"]:
        for action in st["Action"]:
            assert not action.startswith("s3:Delete"), action
            assert not action.startswith("s3:Put") or action == "s3:PutObject", action


def test_no_action_can_change_an_account_wide_setting():
    """`assert_transaction_search` ASSERTS and never enables — Transaction Search is account-wide
    and other systems depend on it. The policy makes that structural: no X-Ray write is granted,
    so a future edit to the case script cannot flip it even by accident."""
    granted = {a for st in IP.document(ACCT, REGION, BUCKET)["Statement"] for a in st["Action"]}
    for action in granted:
        if action.startswith("xray:"):
            assert action.startswith("xray:Get"), action
    assert not {a for a in granted if a.startswith(("account:", "iam:CreateUser",
                                                    "iam:AttachRolePolicy"))}
    # Organizations was a blanket ban until F5-3a, which cannot ask the question at all without it:
    # SCP authoring happens in the management account or nowhere. The ban is replaced by an
    # ALLOWLIST rather than relaxed to a prefix, so it fails CLOSED — an `organizations:` action
    # added to `iam_policy.py` for any reason is a red test until someone puts it in this set and
    # justifies it, which is the opposite of what `startswith("organizations:")` would have done
    # once it was deleted.
    #
    # The line between the two sets is whether the action can reach an object this project does not
    # own. Creating and deleting a fresh OU and a fresh SCP touches only objects named with the
    # case's own prefix, and the case checks the OU is empty before attaching a deny to it. Toggling
    # a policy TYPE, updating an existing policy, or moving an account changes something the
    # account's other workloads share, and no arm of any case needs to.
    org_allowed = {
        "organizations:DescribeOrganization",
        "organizations:DescribeEffectivePolicy",
        "organizations:ListRoots",
        "organizations:ListOrganizationalUnitsForParent",
        "organizations:ListAccountsForParent",
        "organizations:ListPolicies",
        "organizations:ListPoliciesForTarget",
        "organizations:CreateOrganizationalUnit",
        "organizations:DeleteOrganizationalUnit",
        "organizations:CreatePolicy",
        "organizations:DeletePolicy",
        "organizations:AttachPolicy",
        "organizations:DetachPolicy",
    }
    org_granted = {a for a in granted if a.startswith("organizations:")}
    assert org_granted <= org_allowed, sorted(org_granted - org_allowed)
    # Named individually as well, because the allowlist above is a set-difference check and would
    # be satisfied by simply adding a dangerous action to it. These are the ones whose absence is
    # the point, so a reader of a diff that adds one sees a test asserting it must not be there.
    for forbidden in ("organizations:EnablePolicyType", "organizations:DisablePolicyType",
                      "organizations:UpdatePolicy", "organizations:MoveAccount",
                      "organizations:RemoveAccountFromOrganization",
                      "organizations:LeaveOrganization", "organizations:DeleteOrganization",
                      "organizations:CreateAccount", "organizations:CloseAccount",
                      "organizations:InviteAccountToOrganization",
                      "organizations:EnableAWSServiceAccess",
                      "organizations:RegisterDelegatedAdministrator"):
        assert forbidden not in granted, forbidden
        assert forbidden not in org_allowed, f"{forbidden} was added to the allowlist"


# ------------------------------------------------------------------ the file itself

def test_the_policy_module_writes_no_identifier():
    """It takes the account, Region and bucket as arguments precisely so it does not have to.
    Checked here as well as by the redaction gate, so a regression fails the suite too."""
    src = (ROOT / "runner" / "iam_policy.py").read_text(encoding="utf-8")
    import re
    assert not re.search(r"\b\d{12}\b", src), "a 12-digit identifier appears in the module"
    # An ARN template is fine; an ARN with a literal account field is not.
    for m in re.finditer(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:([^:{}]*):", src):
        assert not m.group(1).isdigit() or not m.group(1), m.group(0)


def test_every_runner_extra_carries_a_written_reason():
    """An action with no reason beside it is an action nobody can remove later, because nobody
    knows why it is there (feedback_prose_is_not_verified: the reason must be data, and here it
    is the dict value, so an entry cannot be added without one)."""
    assert all(isinstance(v, str) and len(v) > 15 for v in IP.RUNNER_EXTRAS.values()), \
        [k for k, v in IP.RUNNER_EXTRAS.items() if not (isinstance(v, str) and len(v) > 15)]


def test_the_document_is_valid_json_and_within_the_inline_policy_size_limit():
    """IAM inline role policies cap at 10,240 characters. A derivation that silently exceeded it
    would fail at PutRolePolicy on a live account, which is a worse place to find out."""
    text = json.dumps(IP.document(ACCT, REGION, BUCKET), separators=(",", ":"))
    assert json.loads(text)
    assert len(text) < 10_240, f"{len(text)} characters — over the inline policy limit"
