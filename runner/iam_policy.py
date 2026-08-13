#!/usr/bin/env python3
"""The EC2 runner's IAM policy, DERIVED from the calls the validation has actually made.

Why derived rather than written
-------------------------------
The obvious way to give a runner instance permission is `bedrock:*`, `logs:*`, `iam:*`. That
would work on the first try and would tell a reviewer nothing about what the validation needs —
and `iam:*` on an instance reachable by anyone with `ssm:StartSession` is a privilege-escalation
path, not a convenience.

So the action list is built from the evidence tree. Every AWS call this project has ever made is
archived as `evidence/<run>/<family>/<case>/NNNN_<operation>_<ok|err>.json` carrying its `service`
and `operation`, so the exact API surface is a fact on disk rather than a recollection. `MAPPING`
translates each measured `(service, operation)` pair to the IAM action(s) it requires, and
`unmapped_operations()` reports any measured pair with no entry. `runner/tests/` asserts that set
is empty, which means a case that starts calling a new API fails the test rather than failing at
2am on the instance with an AccessDenied nobody is awake to read.

The direction of failure matters: an unmapped operation is a TEST failure here, never a silent
`*`. Per feedback_zero_file_scan_is_error, a derivation that reads nothing must not report
"nothing needed" — `measured_operations()` raises when the evidence tree yields no calls.

What this policy deliberately does NOT do
-----------------------------------------
It cannot express "do not touch the six pre-existing READY gateways, the three DRAFT guardrails,
the two abandoned policy engines, the `harness_*`/`uitestagent_*` resources, or the `nopolicy`
gateway". Those are other people's resources and F6's paired baseline, and IAM has no way to say
"every gateway except these". That protection lives in the case scripts and their tests, and
moving execution to an instance does not change it. Naming the gap here so a reader does not
mistake a scoped policy for a guardrail it is not.

No account ID, Region or bucket name is written in this file. `statements()` takes them as
arguments and the caller resolves them at run time (`awsclients.account_id()` locally, STS on the
instance) — the same rule the rest of the repo follows, so this file needs no redaction waiver.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Where the project's own resources live in each namespace. Measured, not assumed: every role
# name in the evidence tree begins `grx-` (`grx-gw-exec-`, `grx-caller-`, `grx-attacker-`), and
# `runner/tests/` asserts that against the archived `create_role` params rather than trusting
# this comment.
NAME_PREFIX = "grx-"

# The gateway log groups AgentCore vends into. F7's whole instrument is a namespace-wide read of
# a SHARED namespace, so the read side cannot be narrowed to our own groups without changing what
# F7 measures — that is why `logs:FilterLogEvents` and `logs:DescribeLogGroups` are granted on
# `*` below while every WRITE is prefix-scoped.
VENDED_LOG_PREFIX = "/aws/vendedlogs/bedrock-agentcore/"

# (service, operation) -> the IAM action(s) it needs, and which resource scope applies.
#
# `converse` and `invoke_model` both map to `bedrock:InvokeModel`: the Converse API is authorized
# under InvokeModel, which is the kind of fact that has to be written down rather than inferred
# from the operation name. `mcp:*` operations are not an AWS API at all — they are JSON-RPC over
# HTTPS to a gateway endpoint, signed with SigV4 for the service `bedrock-agentcore`
# (`lib/mcp.py:SIGNING_SERVICE`), so they authorize as one data-plane action.
MAPPING: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    # ---- Bedrock guardrails: control plane on `*`, because CreateGuardrail has no resource to
    # scope to (the id does not exist until the call returns).
    ("bedrock", "create_guardrail"): (("bedrock:CreateGuardrail",), "any"),
    ("bedrock", "get_guardrail"): (("bedrock:GetGuardrail",), "any"),
    ("bedrock", "delete_guardrail"): (("bedrock:DeleteGuardrail",), "any"),

    # ---- Bedrock runtime.
    ("bedrock-runtime", "apply_guardrail"): (("bedrock:ApplyGuardrail",), "any"),
    ("bedrock-runtime", "converse"): (("bedrock:InvokeModel",), "any"),
    ("bedrock-runtime", "invoke_model"): (("bedrock:InvokeModel",), "any"),
    ("bedrock-runtime", "invoke_guardrail_checks"): (
        ("bedrock:ApplyGuardrail", "bedrock:InvokeGuardrailChecks"), "any"),

    # ---- AgentCore control plane.
    ("bedrock-agentcore-control", "create_gateway"): (
        ("bedrock-agentcore:CreateGateway",), "any"),
    ("bedrock-agentcore-control", "get_gateway"): (("bedrock-agentcore:GetGateway",), "any"),
    ("bedrock-agentcore-control", "update_gateway"): (
        ("bedrock-agentcore:UpdateGateway",), "any"),
    ("bedrock-agentcore-control", "create_gateway_target"): (
        ("bedrock-agentcore:CreateGatewayTarget",), "any"),
    # Entered evidence/ on 2026-08-13 when F5-2's cleanup deleted the gateway it had created
    # (evidence/r20260810T130945Z/f5/F5-2/0507_delete_gateway_ok.json, HTTP 202). Found by
    # test_every_api_the_validation_has_called_is_mapped_to_an_action — at desk, which is the
    # failure location that test exists to buy.
    ("bedrock-agentcore-control", "delete_gateway"): (
        ("bedrock-agentcore:DeleteGateway",), "any"),
    # The four policy calls each authorize TWO actions, and the second one is not derivable from
    # the call name. Measured on 2026-08-12: the runner's derived role already held
    # `bedrock-agentcore:CreatePolicy`, and `CreatePolicy` still failed —
    #
    #   AccessDeniedException: ... not authorized to perform:
    #   bedrock-agentcore:ManageResourceScopedPolicy on resource: <the GATEWAY arn>
    #   because no identity-based policy allows the bedrock-agentcore:ManageResourceScopedPolicy action
    #
    # — because a policy is scoped to the resource it guards, so the service authorizes against the
    # GATEWAY as well as against the policy. This is a standing hole in the derivation's premise,
    # worth stating where the premise lives: `measured_operations()` reads the *operation names*
    # from the evidence tree, and an operation name cannot reveal an action the service checks
    # under a different name. The evidence tree recorded `create_policy` succeeding for two weeks
    # under admin credentials, where the extra check passed invisibly. Only a least-privilege
    # caller could surface it, and the runner is the first one this project has had.
    #
    # `create_policy` is the one arm MEASURED to need it. The other three are inferred from the
    # same mechanism rather than observed, and are marked so: they are cheap to include and the
    # alternative is discovering each one at the cost of a failed multi-hundred-call run. If a
    # future least-privilege failure names an action for a call NOT listed here, that is evidence
    # about this comment, not about the API.
    ("bedrock-agentcore-control", "create_policy"): (
        ("bedrock-agentcore:CreatePolicy",
         "bedrock-agentcore:ManageResourceScopedPolicy"), "any"),          # measured
    ("bedrock-agentcore-control", "get_policy"): (
        ("bedrock-agentcore:GetPolicy",
         "bedrock-agentcore:ManageResourceScopedPolicy"), "any"),          # inferred
    ("bedrock-agentcore-control", "update_policy"): (
        ("bedrock-agentcore:UpdatePolicy",
         "bedrock-agentcore:ManageResourceScopedPolicy"), "any"),          # inferred
    ("bedrock-agentcore-control", "delete_policy"): (
        ("bedrock-agentcore:DeletePolicy",
         "bedrock-agentcore:ManageResourceScopedPolicy"), "any"),          # inferred
    ("bedrock-agentcore-control", "create_policy_engine"): (
        ("bedrock-agentcore:CreatePolicyEngine",), "any"),
    ("bedrock-agentcore-control", "delete_policy_engine"): (
        ("bedrock-agentcore:DeletePolicyEngine",), "any"),

    # ---- The gateway data plane, reached as MCP over HTTPS with SigV4.
    ("mcp", "mcp:initialize"): (("bedrock-agentcore:InvokeGateway",), "any"),
    ("mcp", "mcp:notifications/initialized"): (("bedrock-agentcore:InvokeGateway",), "any"),
    ("mcp", "mcp:tools/list"): (("bedrock-agentcore:InvokeGateway",), "any"),
    ("mcp", "mcp:tools/call"): (("bedrock-agentcore:InvokeGateway",), "any"),
    ("mcp", "mcp:prompts/list"): (("bedrock-agentcore:InvokeGateway",), "any"),

    # ---- CloudWatch metrics. Read-only, and `*` is the only resource CloudWatch metric reads
    # accept.
    ("cloudwatch", "get_metric_statistics"): (("cloudwatch:GetMetricStatistics",), "any"),
    ("cloudwatch", "get_metric_data"): (("cloudwatch:GetMetricData",), "any"),
    ("cloudwatch", "list_metrics"): (("cloudwatch:ListMetrics",), "any"),

    # ---- CloudWatch Logs. Reads on `*` (see VENDED_LOG_PREFIX), writes prefix-scoped.
    ("logs", "describe_log_groups"): (("logs:DescribeLogGroups",), "any"),
    ("logs", "filter_log_events"): (("logs:FilterLogEvents",), "any"),
    ("logs", "create_log_group"): (("logs:CreateLogGroup",), "log_group"),
    ("logs", "put_retention_policy"): (("logs:PutRetentionPolicy",), "log_group"),
    ("logs", "tag_resource"): (("logs:TagResource",), "log_group"),
    # The delivery APIs address a delivery id that does not exist until Create returns, and
    # PutDeliverySource names an arbitrary resource ARN, so these cannot be resource-scoped.
    ("logs", "put_delivery_source"): (("logs:PutDeliverySource",), "any"),
    ("logs", "put_delivery_destination"): (("logs:PutDeliveryDestination",), "any"),
    ("logs", "create_delivery"): (("logs:CreateDelivery",), "any"),
    ("logs", "delete_delivery"): (("logs:DeleteDelivery",), "any"),

    # ---- X-Ray. Read-only, and note `assert_transaction_search` ASSERTS and never enables:
    # no `xray:Update*` is granted, so the instance cannot change an account-wide setting other
    # systems depend on even if a future edit tried to.
    ("xray", "get_trace_segment_destination"): (("xray:GetTraceSegmentDestination",), "any"),

    # ---- IAM. The narrowest scope in this policy, and the one that matters most.
    ("iam", "create_role"): (("iam:CreateRole",), "role"),
    ("iam", "put_role_policy"): (("iam:PutRolePolicy",), "role"),
    ("iam", "list_role_policies"): (("iam:ListRolePolicies",), "role"),
    ("iam", "delete_role_policy"): (("iam:DeleteRolePolicy",), "role"),

    # ---- Lambda: F5's echo tool target.
    ("lambda", "create_function"): (("lambda:CreateFunction",), "function"),
    ("lambda", "add_permission"): (("lambda:AddPermission",), "function"),
    ("lambda", "get_policy"): (("lambda:GetPolicy",), "function"),
    ("lambda", "invoke"): (("lambda:InvokeFunction",), "function"),

    # ---- EC2: one read, for the PrivateLink surface F5-7 probes.
    ("ec2", "describe_vpc_endpoint_services"): (("ec2:DescribeVpcEndpointServices",), "any"),
}

# Actions no measured call needs but the runner does, with the reason each is here. Separated from
# MAPPING so the derivation stays a derivation: these are the runner's own needs, not the
# validation's API surface.
RUNNER_EXTRAS: dict[str, str] = {
    "sts:GetCallerIdentity": "lib/awsclients.account_id() — the one place the account is resolved",
    "iam:GetRole": "the case scripts read back a role they created before waiting on propagation",
    "iam:PassRole": "CreateGateway and CreateFunction hand a grx- execution role to the service",
    "bedrock-agentcore:ListGateways": "state.json reconciliation before a resumed run reuses a "
                                      "gateway, so a stale id fails loudly instead of silently "
                                      "creating a second one",
    "bedrock-agentcore:ListPolicies": "the same reconciliation for policies, which are the "
                                      "resource the arms create and delete most often",
    "bedrock-agentcore:GetPolicyEngine": "F1-3 reads the two abandoned engines as read-only "
                                         "evidence and must be able to confirm they still exist",
    # ---------------------------------------------------------------------------------------
    # Read actions the SERVICE performs on the caller's behalf while a policy settles, which no
    # call in the evidence tree makes and therefore no derivation from operation names can find.
    # Measured 2026-08-12, second failure in the same run: `CreatePolicy` returned 200 and the
    # policy then settled `CREATE_FAILED` with
    #   reasons=['Insufficient permissions to list targets on gateway with ID <gw>']
    # The failure is ASYNCHRONOUS, so it does not arrive as an AccessDeniedException on the call
    # — it arrives as a status on a resource that was created. A harness that only checked the
    # CreatePolicy response would have carried on with a dead policy, which is why
    # `_create_probe` waits for the settled status and refuses to continue without a live
    # guardrail (`feedback_missing_check_is_not_pass`).
    #
    # Only `ListGatewayTargets` is named by a measured error. The other two are the rest of that
    # read family on the same resources, included together because each one otherwise costs a
    # failed multi-hundred-call run to discover, and all three are read-only. Marked so the
    # distinction between measured and inferred survives.
    "bedrock-agentcore:ListGatewayTargets": "the service lists a gateway's targets while a "
                                            "resource-scoped policy settles; measured as the "
                                            "CREATE_FAILED reason on 2026-08-12",
    "bedrock-agentcore:GetGatewayTarget": "inferred companion of ListGatewayTargets — settlement "
                                          "reads target detail, and a second async CREATE_FAILED "
                                          "costs a whole run to observe",
    "bedrock-agentcore:ListPolicyEngines": "inferred; the engine-to-gateway binding is resolved "
                                           "during the same settlement",
    "bedrock:ListGuardrails": "confirms the three DRAFT guardrails are untouched before a run, "
                              "which is a precondition no arm may violate",
    "logs:DescribeDeliveries": "delivery teardown has to find the deliveries it created before "
                               "it can delete them",
    "logs:DescribeDeliverySources": "the source half of that teardown, addressed by name rather "
                                    "than by the delivery id",
    "logs:DescribeDeliveryDestinations": "the destination half; a leaked destination keeps "
                                         "billing after a run ends",
    "logs:GetLogEvents": "a single-stream read, cheaper and better-ordered than FilterLogEvents "
                         "when the stream is already known",
    "logs:StartQuery": "Logs Insights, which is how the span surface is read when the event "
                       "volume exceeds what FilterLogEvents pagination can cover in one window",
    "logs:StopQuery": "cancels a Logs Insights query the runner abandons, so an interrupted read "
                      "does not keep consuming the account's concurrent-query quota",
    "logs:GetQueryResults": "collects the Logs Insights result set StartQuery only schedules",
}


def measured_operations() -> dict[tuple[str, str], int]:
    """Every `(service, operation)` in the evidence tree, with its call count.

    Raises when the tree yields nothing. A derivation that read zero files and concluded "no
    permissions needed" is the failure mode of feedback_zero_file_scan_is_error, and it would
    produce an EMPTY policy that looks deliberate.
    """
    counts: dict[tuple[str, str], int] = {}
    for path in (ROOT / "evidence").glob("*/*/*/*.json"):
        if not path.name[:4].isdigit():
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        svc, op = rec.get("service"), rec.get("operation")
        if svc and op:
            counts[(svc, op)] = counts.get((svc, op), 0) + 1
    if not counts:
        raise RuntimeError(
            "no AWS calls found under evidence/ — the policy derivation read nothing. "
            "evidence/ is local-only and gitignored, so this is expected in a fresh clone and "
            "means the policy cannot be derived here, NOT that no permissions are needed.")
    return counts


def unmapped_operations() -> list[tuple[str, str]]:
    """Measured pairs with no MAPPING entry. Asserted empty by `runner/tests/`."""
    return sorted(pair for pair in measured_operations() if pair not in MAPPING)


def statements(account_id: str, region: str, bucket: str) -> list[dict]:
    """The policy statements, grouped by resource scope.

    Actions are collected per scope so the document stays readable, and every scope other than
    `any` is prefix-bound to `NAME_PREFIX`. The account ID and Region arrive as arguments — see
    the module docstring on why neither is written here.
    """
    by_scope: dict[str, set[str]] = {}
    for actions, scope in MAPPING.values():
        by_scope.setdefault(scope, set()).update(actions)
    by_scope.setdefault("any", set()).update(RUNNER_EXTRAS)

    resources = {
        "any": ["*"],
        "role": [f"arn:aws:iam::{account_id}:role/{NAME_PREFIX}*"],
        "function": [f"arn:aws:lambda:{region}:{account_id}:function:{NAME_PREFIX}*"],
        "log_group": [
            f"arn:aws:logs:{region}:{account_id}:log-group:{VENDED_LOG_PREFIX}*",
            f"arn:aws:logs:{region}:{account_id}:log-group:{VENDED_LOG_PREFIX}*:*",
        ],
    }
    # iam:PassRole and iam:GetRole belong on the role scope, not on `*`: PassRole on `*` is the
    # escalation this whole file exists to avoid.
    by_scope["any"] -= {"iam:PassRole", "iam:GetRole"}
    by_scope["role"] |= {"iam:PassRole", "iam:GetRole"}

    out = [{"Sid": f"Grx{scope.title().replace('_', '')}",
            "Effect": "Allow",
            "Action": sorted(by_scope[scope]),
            "Resource": resources[scope]}
           for scope in ("any", "role", "function", "log_group") if by_scope.get(scope)]

    # The runner's own transport: the code tarball in, results and evidence out. Scoped to the
    # one bucket, and deliberately without `s3:DeleteBucket*` or any bucket-policy write, so a
    # compromised instance cannot remove the audit trail it produced.
    out.append({
        "Sid": "GrxRunnerTransport",
        "Effect": "Allow",
        "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"],
        "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
    })
    return out


def document(account_id: str, region: str, bucket: str) -> dict:
    return {"Version": "2012-10-17", "Statement": statements(account_id, region, bucket)}
