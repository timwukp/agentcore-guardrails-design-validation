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

# The stem of the AgentCore Runtime deployment-package bucket. A stem and not a name: the bucket is
# `<NAME_PREFIX><stem>-<account>-<region>`, and the two identifiers that would make it a name are
# still arguments to `statements()`, so the rule in the module docstring holds. The producer that
# creates the bucket composes it by the same rule, and if the two ever disagree the symptom is an
# AccessDenied on PutObject naming a bucket that is not in the policy — which is legible.
CODE_BUCKET_STEM = "runtime-code"

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
    # `bedrock:TagResource` is required because every probe guardrail this project creates carries
    # tags (`lib/phase1.create_probe_guardrail` passes `A.tags_for(run_id, expires_at)`, and the
    # tags are not decoration — they are how a sweep finds an abandoned resource). A `Create*` call
    # that includes `tags` authorizes the tagging separately, and it fails the WHOLE create rather
    # than creating an untagged resource.
    #
    # This is the class of permission a derivation from operation names can NEVER find, and it is
    # worth being precise about why. `MAPPING` is keyed on (service, operation) pairs read out of
    # the evidence tree, so it can only discover actions that correspond to a call somebody made.
    # Nobody calls TagResource here — it is an implicit requirement of an argument to a different
    # call. `RUNNER_EXTRAS` already carries one family of these (reads the SERVICE performs while a
    # policy settles); this is a second family, and the two have the same signature from the
    # outside: a least-privilege policy that is complete by construction and still denied.
    #
    # Measured 2026-08-13, and it cost a run to find: F1-6's eight `CreateGuardrail` probes all
    # returned `AccessDeniedException` with
    #   "not authorized to perform: bedrock:TagResource on resource:
    #    arn:aws:bedrock:us-east-1:<acct>:guardrail/* because no identity-based policy allows ..."
    # The case's confound classifier correctly refused to score an access error as its claim
    # holding, so no false verdict was published — but the message names an action, and an
    # AccessDenied that names an action the policy does not contain is the cheapest diagnosis
    # available. Read it before theorising (this one was first misread as credential staleness from
    # the hourly instance-profile clobber, which is a real effect and was NOT this).
    ("bedrock", "create_guardrail"): (
        ("bedrock:CreateGuardrail", "bedrock:TagResource"), "any"),
    ("bedrock", "get_guardrail"): (("bedrock:GetGuardrail",), "any"),
    ("bedrock", "delete_guardrail"): (("bedrock:DeleteGuardrail",), "any"),

    # F5-9's instrument: the account-level enforced guardrail configuration. `any` because the
    # operation takes no resource — it addresses the account, which is precisely why F5-9 sends
    # `modelEnforcement` scoped to one unused model on every call and aborts if the readback
    # disagrees. The IAM scope cannot express that bound; only the case can.
    #
    # The action names are MEASURED, not inferred from the operation names. Probed from the instance
    # on 2026-08-13 with the read-only member of the family, which is the safe one to be denied:
    #   AccessDeniedException: ... not authorized to perform:
    #   bedrock:ListEnforcedGuardrailsConfiguration
    # Note the plural in the List form and the singular in the other two — they track the API
    # operation names exactly, so guessing "EnforcedGuardrail" for all three would have produced a
    # policy that denies the read and a run that fails its own precondition check.
    ("bedrock", "put_enforced_guardrail_configuration"): (
        ("bedrock:PutEnforcedGuardrailConfiguration",), "any"),
    ("bedrock", "delete_enforced_guardrail_configuration"): (
        ("bedrock:DeleteEnforcedGuardrailConfiguration",), "any"),

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
    # Added 2026-08-14 for F1-15, and it is worth saying why it was missing for so long rather than
    # just adding it. `delete_gateway_target` has existed in this repo since `infra/05_target.py`,
    # but only as the `delete_op` STRING on a ledger record — `infra/` creates the two `grxecho`
    # targets and leaves them standing for the life of the testbed, so no run has ever replayed that
    # string and no evidence file names the operation. `unmapped_operations()` therefore had nothing
    # to flag, and the grant's absence was invisible in exactly the way a derivation from observed
    # calls is blind to a call nobody has made yet.
    #
    # F1-15 is the first case that creates gateway targets of its own and must remove them in the
    # same run: it adds one target per `targetConfiguration` arm to `gateway/main`, and leaving those
    # behind is not a leak of something inert. Extra targets on `main` advertise extra tools, and
    # `main` is the ENFORCE half of the pair `nopolicy` is the latency baseline for, so residue there
    # is contamination of the testbed every later F4/F6 run reads. The read half of this family
    # (`ListGatewayTargets`, `GetGatewayTarget`) is already granted below in RUNNER_EXTRAS, for a
    # different reason — the SERVICE performs those on the caller's behalf while a policy settles —
    # so this entry completes a family that was two-thirds present.
    ("bedrock-agentcore-control", "delete_gateway_target"): (
        ("bedrock-agentcore:DeleteGatewayTarget",), "any"),
    # Entered evidence/ on 2026-08-13 when F5-2's cleanup deleted the gateway it had created
    # (evidence/r20260810T130945Z/f5/F5-2/0507_delete_gateway_ok.json, HTTP 202). Found by
    # test_every_api_the_validation_has_called_is_mapped_to_an_action — at desk, which is the
    # failure location that test exists to buy.
    ("bedrock-agentcore-control", "delete_gateway"): (
        ("bedrock-agentcore:DeleteGateway",), "any"),

    # ---- AgentCore Runtime. Added 2026-08-14 for F5-8, whose sealed method is "minimal runtime
    # whose handler calls GetCallerIdentity", and for F1-15's `http.agentcoreRuntime` target.
    #
    # These were absent until now because the recorded plan of record held that a Runtime needed a
    # linux/arm64 CONTAINER image, and therefore a Graviton builder, and was therefore out of reach.
    # That premise read only one arm of a union: `agentRuntimeArtifact` also accepts
    # `codeConfiguration` — an S3 zip plus PYTHON_3_12 plus an entry point — which was measured on
    # 2026-08-14 to reach READY in 10.8 seconds and serve an HTTP 200 with no container anywhere.
    #
    # Scope is `any`, matching `create_gateway` above, and for two reasons. A create has no resource
    # to be scoped to; and a Runtime's name cannot carry `NAME_PREFIX`. The API constrains the name
    # to `[a-zA-Z][a-zA-Z0-9_]*` — no hyphens — so this project's runtimes are `grx_*` while every
    # prefix-bound scope in `statements()` is bound to `grx-*`. A scope written against `grx-*`
    # would match none of them and deny every call while looking narrow, which is worse than `*`
    # labelled as `*`.
    #
    # `CreateAgentRuntime` needs TWO actions, and the second one is not derivable from the API
    # surface. Creating a runtime implicitly creates its DEFAULT endpoint, and IAM authorizes that
    # implicit step separately: the first EC2 run of F5-8 with only `CreateAgentRuntime` granted
    # came back with
    #
    #     not authorized to perform: bedrock-agentcore:CreateAgentRuntimeEndpoint on resource:
    #     arn:aws:bedrock-agentcore:<region>:<account>:runtime/*   (request id fb914e1b-...)
    #
    # There is no `create_agent_runtime_endpoint` call anywhere in this tree, so nothing in
    # `evidence/` will ever name it and `unmapped_operations()` cannot find it. It is recorded here
    # against the operation that actually needs it, with the AccessDenied that proved it, because
    # the alternative is re-discovering it from a five-minute round trip on the instance.
    #
    # A third one appeared behind the second: a runtime also gets a WORKLOAD IDENTITY, created
    # implicitly under `workload-identity-directory/default/workload-identity/*`, and the caller is
    # authorized for that too (request id 14f4f1e4-53d9-42e4-b3ec-a4a309a7e0cb). So one
    # `CreateAgentRuntime` call needs at least four distinct permissions across three services, and
    # AWS does not publish the list --- `runtime-permissions.html` answers the caller question with
    # "attach BedrockAgentCoreFullAccess", and enumerates least privilege only for the EXECUTION
    # role, which is a different principal solving a different problem. A least-privilege caller
    # policy for this API therefore cannot be derived from documentation; it can only be measured,
    # one 403 at a time, which is what the request ids in these comments are.
    ("bedrock-agentcore-control", "create_agent_runtime"): (
        ("bedrock-agentcore:CreateAgentRuntime",
         "bedrock-agentcore:CreateAgentRuntimeEndpoint",
         "bedrock-agentcore:CreateWorkloadIdentity"), "any"),
    ("bedrock-agentcore-control", "get_agent_runtime"): (
        ("bedrock-agentcore:GetAgentRuntime",), "any"),
    # The delete side carries the symmetric endpoint action, and unlike the create side that is
    # ANTICIPATED rather than observed — no run has yet reached a successful delete to prove it is
    # needed. It is granted anyway because the cost of being wrong is asymmetric: a superfluous
    # action on a `*` scope that already carries DeleteAgentRuntime widens nothing meaningful, while
    # a missing one denies TEARDOWN, and a denied teardown leaks a READY runtime that bills until
    # someone notices. If the evidence shows `delete_agent_runtime` succeeding, this stays as the
    # cheaper side of that trade; it is labelled so a reader does not mistake it for a measurement.
    ("bedrock-agentcore-control", "delete_agent_runtime"): (
        ("bedrock-agentcore:DeleteAgentRuntime",
         "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
         "bedrock-agentcore:DeleteWorkloadIdentity"), "any"),
    ("bedrock-agentcore", "invoke_agent_runtime"): (
        ("bedrock-agentcore:InvokeAgentRuntime",), "any"),

    # ---- the deployment-package bucket, on its own scope.
    # A Runtime under `codeConfiguration` reads its code from S3, so the runner has to be able to
    # put a zip there. This is NOT the runner's transport bucket: `GrxRunnerTransport` at the foot
    # of `statements()` is scoped to the one bucket that carries the tarball in and the results and
    # evidence out, and widening it to cover a second bucket would also widen `s3:GetObject` over
    # the audit trail. A separate scope keeps `PutObject` and `DeleteObject` off the archive, which
    # is the property that statement's own comment claims for it.
    ("s3", "head_bucket"): (("s3:ListBucket",), "code_bucket"),
    ("s3", "put_object"): (("s3:PutObject",), "code_bucket"),
    ("s3", "delete_object"): (("s3:DeleteObject",), "code_bucket"),

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
    # `bedrock-agentcore:TagResource` for the same reason as `bedrock:TagResource` above, and
    # INFERRED rather than measured: `f8_regional/08_policy_engine_regions.py` creates a policy
    # engine per Region with `tags=A.tags_for(...)`, which is the identical shape that F1-6's
    # tagged `CreateGuardrail` failed on. Included ahead of the failure because F8-1 mutates NINE
    # Regions, and discovering this from the far side would cost nine denied creates whose error
    # code is `AccessDeniedException` — the one code that case's own taxonomy refuses to score
    # (IAM mimics feature-unavailability), so it would land INCONCLUSIVE rather than red. Marked
    # inferred so the distinction from the measured entry above survives.
    ("bedrock-agentcore-control", "create_policy_engine"): (
        ("bedrock-agentcore:CreatePolicyEngine",
         "bedrock-agentcore:TagResource"), "any"),                          # inferred
    ("bedrock-agentcore-control", "delete_policy_engine"): (
        ("bedrock-agentcore:DeletePolicyEngine",), "any"),
    # MEASURED, and only visible from the instance. `unmapped_operations()` reads `evidence/`, which
    # is local-only in BOTH directions: the laptop's tree and the instance's tree hold different
    # subsets, so the audit's answer depends on where it runs. It was empty on the laptop and named
    # this pair on the instance — where the live rounds actually happened. Worth stating plainly
    # because `runner/provision.py:406` hard-gates on that audit: a gap the laptop cannot see would
    # block the next provision, and only there.
    ("bedrock-agentcore-control", "get_policy_engine"): (
        ("bedrock-agentcore:GetPolicyEngine",), "any"),
    # ---- Natural-language policy authoring. F1-19's B arm is the only caller in the project.
    #
    # MEASURED 2026-08-14, and it cost a live round:
    #
    #   AccessDeniedException: User: .../grx-runner-ec2/i-... is not authorized to perform:
    #   bedrock-agentcore:StartPolicyGeneration on resource: .../policy-engine/grx_pe_...
    #   because no identity-based policy allows the bedrock-agentcore:StartPolicyGeneration action
    #
    # This is a DIFFERENT hole from the ManageResourceScopedPolicy one above, and the difference is
    # the interesting part. That one was "an operation name cannot reveal an action the service
    # checks under another name". This one is more basic: `measured_operations()` derives the policy
    # from calls the evidence tree RECORDS AS HAVING RUN, and a call that has never once succeeded
    # anywhere leaves no such record. F1-19's B arm had never completed — it was blocked behind the
    # union-member and scope defects for three rounds — so the derivation had no way to learn the
    # action, and the first round in which the A arms finally worked is necessarily the first round
    # that could surface it. A least-privilege policy derived from observed successes cannot grant
    # the permission for a call that has not yet had one. The bootstrap has to be broken by hand,
    # here, which is what this entry is.
    #
    # The two reads are INFERRED, not measured: the deny above stopped the chain at the first call,
    # so `get_policy_generation` and `list_policy_generation_assets` were never reached. They are
    # named on the same argument as the three inferred policy entries above — cheap to include, and
    # the alternative is spending another live round to learn each one, which this case has now done
    # three times.
    ("bedrock-agentcore-control", "start_policy_generation"): (
        ("bedrock-agentcore:StartPolicyGeneration",), "any"),               # measured
    ("bedrock-agentcore-control", "get_policy_generation"): (
        ("bedrock-agentcore:GetPolicyGeneration",), "any"),                 # inferred
    ("bedrock-agentcore-control", "list_policy_generation_assets"): (
        ("bedrock-agentcore:ListPolicyGenerationAssets",), "any"),          # inferred

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
    # `infra/07_traces.py:241` passes `tags` here, so this create needs `logs:TagResource` too — but
    # it is NOT listed on this entry. The `logs:TagResource` below is on `any` and already covers it;
    # adding a `log_group`-scoped copy here would be a grant that reads as prefix-bound while the
    # effective permission is `*`. Written out because the omission looks like the very oversight
    # this round was fixing, and because the first draft of this change did add it — and
    # `test_the_log_tagging_grant_is_not_described_more_narrowly_than_it_is` failed on it.
    ("logs", "create_log_group"): (("logs:CreateLogGroup",), "log_group"),
    ("logs", "put_retention_policy"): (("logs:PutRetentionPolicy",), "log_group"),
    # `logs:TagResource` sits on `any`, NOT on `log_group`, and the wider scope is deliberate: the
    # `create_delivery` below passes `tags` too, and a delivery ARN is
    # `arn:aws:logs:<region>:<acct>:delivery:<id>` where <id> is server-assigned — there is no
    # prefix to bind it to. Leaving the log-group-scoped copy in place as well would have been
    # worse than useless: TagResource would be granted on `*` regardless, and the narrow entry
    # would read in review as a bound that is not in force. Same lesson as mutant M10 — a grant
    # that looks scoped and is not is the failure mode this module exists to prevent.
    ("logs", "tag_resource"): (("logs:TagResource",), "any"),
    # The delivery APIs address a delivery id that does not exist until Create returns, and
    # PutDeliverySource names an arbitrary resource ARN, so these cannot be resource-scoped.
    ("logs", "put_delivery_source"): (("logs:PutDeliverySource",), "any"),
    ("logs", "put_delivery_destination"): (("logs:PutDeliveryDestination",), "any"),
    ("logs", "create_delivery"): (("logs:CreateDelivery", "logs:TagResource"), "any"),
    ("logs", "delete_delivery"): (("logs:DeleteDelivery",), "any"),

    # ---- X-Ray. Read-only, and note `assert_transaction_search` ASSERTS and never enables:
    # no `xray:Update*` is granted, so the instance cannot change an account-wide setting other
    # systems depend on even if a future edit tried to.
    ("xray", "get_trace_segment_destination"): (("xray:GetTraceSegmentDestination",), "any"),

    # ---- IAM. The narrowest scope in this policy, and the one that matters most.
    # `iam:TagRole` for the same reason as `iam:TagPolicy` below — `infra/01_iam.py:504` and
    # `infra/02_lambda.py:141` both pass `Tags` to CreateRole. This one has never failed, and only
    # because both scripts run from a workstation under a human's admin credentials. It would have
    # failed the first time a case created its own role on the instance.
    ("iam", "create_role"): (("iam:CreateRole", "iam:TagRole"), "role"),
    ("iam", "put_role_policy"): (("iam:PutRolePolicy",), "role"),
    ("iam", "list_role_policies"): (("iam:ListRolePolicies",), "role"),
    ("iam", "delete_role_policy"): (("iam:DeleteRolePolicy",), "role"),
    # Absent until 2026-08-14, and the reason it went unnoticed is worth stating: `iam:CreateRole`
    # has been granted since the first EC2 run, but every case that created a role before F5-8 left
    # it for `infra/` to delete from the laptop, so `delete_role` had never appeared in `evidence/`
    # and `unmapped_operations()` had nothing to flag. F5-8 is the first case that creates and
    # deletes its own execution role inside one run, and it found the gap the only way this gap can
    # be found — an AccessDenied in the `finally`, AFTER the inline policy had already been deleted,
    # leaving a stripped role standing. That ordering is why this is a grant and not a teardown fix.
    ("iam", "delete_role"): (("iam:DeleteRole",), "role"),
    ("iam", "get_role"): (("iam:GetRole",), "role"),
    ("iam", "get_role_policy"): (("iam:GetRolePolicy",), "role"),

    # F5-3b and F5-4b, added 2026-08-13 by enumerating every `capture(store, <op>, iam, ...)` in
    # both scripts at once rather than one failed run at a time — which is what the first two
    # rounds cost (`bedrock:TagResource`, then `sts:AssumeRole`, then this).
    #
    # `list_attached_role_policies` is the one that stopped F5-3b, and the refusal was CORRECT
    # behaviour by the case, not a nuisance: an attached MANAGED policy could grant UpdateGateway
    # from outside the inline document the case reads, so a denial in the pre-grant arm would have
    # an explanation the case cannot see. It refuses to measure rather than score a denial it
    # cannot attribute (feedback_missing_check_is_not_pass).
    ("iam", "list_attached_role_policies"): (("iam:ListAttachedRolePolicies",), "role"),
    # The permissions-boundary pair IS the instrument of F5-3b: the case's whole question is
    # whether a boundary stops UpdateGateway, so it must be able to attach and detach one.
    ("iam", "put_role_permissions_boundary"): (("iam:PutRolePermissionsBoundary",), "role"),
    ("iam", "delete_role_permissions_boundary"): (("iam:DeleteRolePermissionsBoundary",), "role"),
    # `simulate_principal_policy` is a READ that answers "what does IAM think this identity may
    # do", which is how the case distinguishes a boundary denial from a missing grant without
    # making the call. Scoped to the role prefix because the PolicySourceArn is a grx- role.
    ("iam", "simulate_principal_policy"): (("iam:SimulatePrincipalPolicy",), "role"),
    # A managed policy, because a permissions boundary must BE one — a boundary cannot be an
    # inline document. This needs the `policy` scope: a managed-policy ARN is
    # `arn:aws:iam::<acct>:policy/<name>`, which the `role/grx-*` pattern cannot match, so
    # reusing the role scope here would have produced a policy that reads as scoped and denies
    # every call. The names are `grx-f53b-boundary-{deny,omit}-<run-id>` (read from the script at
    # line ~1244, not assumed), so the prefix bound holds.
    #
    # `iam:TagPolicy` is the FOURTH time the implicit-permission class has cost a live run
    # (`bedrock:TagResource`, then the two-sided assume-role gate, then `list_attached_role_policies`,
    # now this), and it went missing despite the comment above claiming the round had enumerated
    # both scripts "at once". That claim was true and still insufficient, which is the point worth
    # recording: the enumeration walked `capture(store, <op>, ...)` OPERATION NAMES, and no
    # enumeration over operation names can find an action that an ARGUMENT requires. CreatePolicy
    # with `Tags=` authorizes `iam:TagPolicy` separately and fails the WHOLE create when it is
    # missing — the create is not attempted-then-untagged, it is denied outright:
    #
    #   "not authorized to perform: iam:TagPolicy on resource:
    #    policy grx-f53b-boundary-deny-<run-id> because no identity-based policy allows ..."
    #
    # The fix for the CLASS, not this instance, is
    # `test_every_tagged_create_also_grants_the_tagging_action` in runner/tests/: it scans
    # arguments rather than operation names, so a `Tags=` added to any future create is a red test
    # at desk instead of a fifth 5-minute IAM-propagation round on the instance.
    ("iam", "create_policy"): (("iam:CreatePolicy", "iam:TagPolicy"), "policy"),
    ("iam", "delete_policy"): (("iam:DeletePolicy",), "policy"),

    # ---- Lambda: F5's echo tool target.
    # `lambda:TagResource` because both creates at `infra/02_lambda.py:266,279` pass `Tags`. Same
    # class as `iam:TagRole` above and latent for the same reason: provisioning runs from a
    # workstation, so the instance's copy of this grant has never been exercised.
    ("lambda", "create_function"): (("lambda:CreateFunction", "lambda:TagResource"), "function"),
    ("lambda", "add_permission"): (("lambda:AddPermission",), "function"),
    ("lambda", "get_policy"): (("lambda:GetPolicy",), "function"),
    ("lambda", "invoke"): (("lambda:InvokeFunction",), "function"),

    # ---- EC2: one read, for the PrivateLink surface F5-7 probes.
    ("ec2", "describe_vpc_endpoint_services"): (("ec2:DescribeVpcEndpointServices",), "any"),

    # ---- EC2: F5-7b's own network. The only case in this project that builds a VPC.
    #
    # READ THE BLAST RADIUS BEFORE THE LIST. Every entry below lands on the `any` scope, i.e.
    # `Resource: ["*"]`, because EC2 creates have nothing to scope to: `CreateVpc` names no
    # resource, and the id it returns is what everything after it would be scoped by. So this
    # block grants `ec2:DeleteVpc`, `ec2:DeleteSubnet`, `ec2:DeleteRoute` and
    # `ec2:DeleteSecurityGroup` account-wide — including over the VPC, the subnet and the security
    # group the runner instance itself lives in. Those ids are deliberately NOT written here: the
    # producer resolves them at runtime from the `grx-runner-sg` NAME, so the deny-list cannot go
    # stale silently if the runner is ever rebuilt, and no real network id enters a published file.
    #
    # That is the sharpest self-inflicted hazard in this policy. A teardown bug that deleted the
    # runner's own route or security group would sever SSM, and the instance is reachable ONLY by
    # SSM — there is no key pair and no public ingress. The loss would not be one case; it would
    # be the ability to run or clean up anything at all, including whatever the bug leaked.
    #
    # IAM cannot express the guard, for the same reason the module docstring gives for the six
    # pre-existing gateways: there is no way to say "every VPC except this one". So the guard
    # lives in the producer, and it is two guards rather than one, because a single check is a
    # single point of failure for an irreversible action:
    #   1. a deny-list holding the runner's own VPC, EVERY subnet in it and EVERY security group in
    #      it — resolved from the SG name before the first create, asserted before every destructive
    #      EC2 call, ABORTING rather than skipping, and refusing every id if it is empty so that an
    #      unresolved list fails closed instead of reading as "nothing is forbidden";
    #   2. every delete addressed by an id read back FROM THE LEDGER, never by a describe filter
    #      — a filter that matches too much is how the wrong VPC gets deleted, and a resource
    #      this run did not record is not a resource this run may remove.
    # `f5_redteam/tests/` pins both, because this failure mode is unreviewable after the fact.
    #
    # `ec2:CreateTags` rides along on each create for the same reason `iam:TagRole` and
    # `lambda:TagResource` do: every create below passes `TagSpecifications`, and a tagged create
    # without the tagging action fails the CREATE rather than the tagging. That class is caught at
    # desk by `test_every_tagged_create_also_grants_the_tagging_action`.
    #
    # `DeleteNetworkInterface` is the one entry that is INFERRED rather than measured. AgentCore
    # VPC mode attaches ENIs into the supplied subnets via a service-linked role
    # (`EXCLUSION_REGISTER.md:83-85`), and a subnet holding an ENI cannot be deleted. If the
    # service reclaims its own ENIs promptly this grant is never used; if it does not, the
    # alternative is a leaked VPC and a leaked NAT gateway that bills by the hour. An unused
    # grant is the cheaper error, and it is labelled so a reviewer can see which way it went.
    ("ec2", "describe_availability_zones"): (("ec2:DescribeAvailabilityZones",), "any"),
    ("ec2", "create_vpc"): (("ec2:CreateVpc", "ec2:CreateTags"), "any"),
    ("ec2", "describe_vpcs"): (("ec2:DescribeVpcs",), "any"),
    ("ec2", "delete_vpc"): (("ec2:DeleteVpc",), "any"),
    ("ec2", "create_subnet"): (("ec2:CreateSubnet", "ec2:CreateTags"), "any"),
    ("ec2", "describe_subnets"): (("ec2:DescribeSubnets",), "any"),
    ("ec2", "delete_subnet"): (("ec2:DeleteSubnet",), "any"),
    ("ec2", "create_security_group"): (("ec2:CreateSecurityGroup", "ec2:CreateTags"), "any"),
    ("ec2", "describe_security_groups"): (("ec2:DescribeSecurityGroups",), "any"),
    ("ec2", "delete_security_group"): (("ec2:DeleteSecurityGroup",), "any"),
    ("ec2", "create_internet_gateway"): (
        ("ec2:CreateInternetGateway", "ec2:CreateTags"), "any"),
    ("ec2", "attach_internet_gateway"): (("ec2:AttachInternetGateway",), "any"),
    ("ec2", "detach_internet_gateway"): (("ec2:DetachInternetGateway",), "any"),
    ("ec2", "delete_internet_gateway"): (("ec2:DeleteInternetGateway",), "any"),
    ("ec2", "allocate_address"): (("ec2:AllocateAddress", "ec2:CreateTags"), "any"),
    ("ec2", "release_address"): (("ec2:ReleaseAddress",), "any"),
    ("ec2", "describe_addresses"): (("ec2:DescribeAddresses",), "any"),
    ("ec2", "create_nat_gateway"): (("ec2:CreateNatGateway", "ec2:CreateTags"), "any"),
    ("ec2", "describe_nat_gateways"): (("ec2:DescribeNatGateways",), "any"),
    ("ec2", "delete_nat_gateway"): (("ec2:DeleteNatGateway",), "any"),
    ("ec2", "create_route_table"): (("ec2:CreateRouteTable", "ec2:CreateTags"), "any"),
    ("ec2", "describe_route_tables"): (("ec2:DescribeRouteTables",), "any"),
    ("ec2", "associate_route_table"): (("ec2:AssociateRouteTable",), "any"),
    ("ec2", "disassociate_route_table"): (("ec2:DisassociateRouteTable",), "any"),
    ("ec2", "delete_route_table"): (("ec2:DeleteRouteTable",), "any"),
    # THE MUTATION AND ITS INVERSE. `mutation_is_mandatory("F5-7b")` is True, so both of these are
    # load-bearing: the case is NOT answered by observing a VPC that never had a route. It is
    # answered by adding the route, re-observing, then removing it and re-verifying the original
    # observation (PREREGISTRATION.yaml `restore_verification`: a restore is not assumed to have
    # worked because the API returned 200).
    ("ec2", "create_route"): (("ec2:CreateRoute",), "any"),
    ("ec2", "delete_route"): (("ec2:DeleteRoute",), "any"),
    ("ec2", "describe_network_interfaces"): (("ec2:DescribeNetworkInterfaces",), "any"),
    ("ec2", "delete_network_interface"): (("ec2:DeleteNetworkInterface",), "any"),   # inferred

    # ---- Organizations: F5-3a only, and the blast radius is why these are enumerated one by one
    # rather than granted as `organizations:*`.
    #
    # There is NO bootstrap chicken-and-egg here, contrary to what an earlier version of this
    # comment claimed. `statements()` iterates all of `MAPPING.values()`, so an entry is granted the
    # moment it is written, whether or not any case has performed it; `measured_operations()` feeds
    # `unmapped_operations()`, which is an AUDIT in the other direction — every measured call must
    # have a mapping. So when F5-3a's first run (2026-08-13) died on `describe_organization` with
    # AccessDeniedException, the cause was a MISSING MAPPING ENTRY and a live role derived before it
    # existed, not a derivation that could not reach the action. The distinction matters: the fix is
    # to write the entry and re-apply, never to work around the derivation. The entries are read
    # from the script rather than guessed
    # (`feedback_derive_from_every_producer`): every `capture(store, <op>, org, ...)` in
    # `f5_redteam/10_route4_scp_propagation.py` appears here and nothing else does.
    #
    # What is DELIBERATELY ABSENT is the more important half. There is no `EnablePolicyType` and no
    # `DisablePolicyType`: those change an org-wide setting that the account's other workloads
    # depend on, SCPs are already enabled here, and no arm of this case needs to toggle them. There
    # is no `UpdatePolicy` and no `MoveAccount`, so the case cannot alter one of the three existing
    # SCPs or relocate a real account even if a future edit tried to. Deletes are granted because
    # teardown must reach the two objects the case creates, and the case's own prefix guard plus its
    # emptiness check on the fresh OU are what keep those deletes off anything shared. No
    # `organizations:TagResource` is granted because neither create call passes Tags — verified in
    # the source, not assumed, since a tagged create authorizes the tagging separately and that is
    # precisely how `bedrock:TagResource` came to be missing here.
    ("organizations", "describe_effective_policy"): (
        ("organizations:DescribeEffectivePolicy",), "any"),
    ("organizations", "create_organizational_unit"): (
        ("organizations:CreateOrganizationalUnit",), "any"),
    ("organizations", "delete_organizational_unit"): (
        ("organizations:DeleteOrganizationalUnit",), "any"),
    ("organizations", "create_policy"): (("organizations:CreatePolicy",), "any"),
    ("organizations", "delete_policy"): (("organizations:DeletePolicy",), "any"),
    ("organizations", "attach_policy"): (("organizations:AttachPolicy",), "any"),
    ("organizations", "detach_policy"): (("organizations:DetachPolicy",), "any"),
}

# Actions no measured call needs but the runner does, with the reason each is here. Separated from
# MAPPING so the derivation stays a derivation: these are the runner's own needs, not the
# validation's API surface.
RUNNER_EXTRAS: dict[str, str] = {
    "sts:GetCallerIdentity": "lib/awsclients.account_id() — the one place the account is resolved",
    "iam:GetRole": "the case scripts read back a role they created before waiting on propagation",
    "iam:PassRole": "CreateGateway, CreateFunction and CreateAgentRuntime each hand a grx- "
                    "execution role to the service",
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
    "bedrock:ListEnforcedGuardrailsConfiguration": "the ONLY readback in this API family — there is "
                                                   "no Get operation — so it is how F5-9 checks "
                                                   "that zero configurations exist before it puts "
                                                   "one, that its own put landed scoped to one "
                                                   "model, and that teardown really removed it. "
                                                   "Called outside capture() because it establishes "
                                                   "preconditions rather than measuring an arm",
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
    # ---------------------------------------------------------------------------------------
    # Organizations reads F5-3a performs OUTSIDE `capture()`, and therefore outside the evidence
    # tree, so no MAPPING entry can ever produce them. They are here for the same structural reason
    # `bedrock:ListGuardrails` is: they establish preconditions and shape the finding rather than
    # measure an arm, so they are deliberately not recorded as observations. All six are read-only.
    "organizations:DescribeOrganization": "F5-3a's first call, and its refusal is the case's own "
                                         "precondition check: SCP authoring needs the management "
                                         "account, and an AccessDenied here has to be "
                                         "distinguishable from a member-account run",
    "organizations:ListRoots": "the root id every OU and attach is addressed relative to",
    "organizations:ListOrganizationalUnitsForParent": "the pre- and post-run inventory that proves "
                                                      "the two existing child OUs were untouched",
    "organizations:ListPolicies": "the same inventory for the three existing SCPs, which the "
                                  "residue check compares against by id",
    "organizations:ListPoliciesForTarget": "reads what is attached to the fresh OU, which is how "
                                           "the attach is confirmed without DescribeEffectivePolicy",
    "organizations:ListAccountsForParent": "the emptiness check that must pass BEFORE a deny "
                                           "policy is attached to anything; without it the case "
                                           "could attach a deny to an OU containing real accounts",
    # ---------------------------------------------------------------------------------------
    # F5-3b, measured 2026-08-13. The case's whole question is what an identity holding a
    # permissions boundary CANNOT do, so it has to run AS that identity: `ClientFactory(role_arn=…)`
    # calls `sts.assume_role` inside `session()`, not inside `capture()`, which is why no MAPPING
    # entry can ever produce it. The first run died with
    #   AccessDenied ... not authorized to perform: sts:AssumeRole on resource:
    #   arn:aws:iam::<acct>:role/grx-attacker-<run-id>
    # Note this is only HALF the gate. Assume-role needs the identity policy and the target role's
    # trust policy to agree, and that run's real cause was the trust policy naming the laptop IAM
    # user only — the harness moved to the instance and the trust never followed. Granting this
    # action does nothing on its own; see `infra/01_iam.py:caller_trust(also_trust=…)`.
    "sts:AssumeRole": "F5-3b runs AS grx-attacker/grx-caller to measure what a boundaried identity "
                      "cannot do; assumed in ClientFactory.session(), outside capture(), and "
                      "listed in ROLE_SCOPED_EXTRAS so it cannot reach a non-grx- role",
    # Measured 2026-08-14, and it is not the permission it looks like. CreateAgentRuntime under
    # `codeConfiguration` checks that the CALLER can read the zip, not only that the execution role
    # can --- a confused-deputy guard, and the right design: without it, anyone able to pass a role
    # could make the service fetch an object they cannot read themselves. Nothing in this repo calls
    # `get_object` against the code bucket, so no evidence file will ever name it and
    # `unmapped_operations()` cannot find it; it belongs to the same implicit-permission class as the
    # tagged creates. It cost five runs to locate because the service reports it as
    #     ValidationException: Access denied when trying to retrieve zip file from S3.
    #     Check if you have sufficient permissions on the object
    # which names the object and not the caller, so every check went to the object, the execution
    # role, the bucket's ownership and encryption settings, and the IAM propagation delay --- all of
    # which were correct. What isolated it: the SAME role and the SAME uploaded zip that the instance
    # was refused for were accepted immediately when CreateAgentRuntime was called by an
    # administrator instead, which leaves only the caller as the variable.
    "s3:GetObject": "CreateAgentRuntime with a codeConfiguration artifact verifies that the CALLER "
                    "can read the deployment zip, not just the execution role it is passed; scoped "
                    "to the code bucket by CODE_BUCKET_SCOPED_EXTRAS so it cannot read the account",
}

# RUNNER_EXTRAS land on the `any` scope, i.e. `Resource: ["*"]`. These three must not: each one is
# a step toward using a DIFFERENT identity, and on `*` that is the account-wide escalation this
# module exists to make impossible. `statements()` moves them onto the prefix-bound role scope, and
# `runner/tests/` asserts the move happened for every member of this tuple rather than trusting
# that the two lines below stayed in sync with it.
ROLE_SCOPED_EXTRAS = ("iam:PassRole", "iam:GetRole", "sts:AssumeRole")

# Same mechanism, different scope. `s3:GetObject` must reach the code bucket and NOTHING else --- on
# `*` it would read every object in the account, and this module's whole claim is that it does not do
# that. It is kept off the `any` scope the same way the three above are.
CODE_BUCKET_SCOPED_EXTRAS = ("s3:GetObject",)

# Operations that ARE in the evidence tree and are deliberately NOT granted to the instance, with
# the reason each is refused. Adding a MAPPING entry satisfies the audit and GRANTS; this satisfies
# the audit and REFUSES, which until 2026-08-13 was a distinction the module could not express.
#
# It came up the first time the two halves disagreed. `infra/01_iam.py --fix-drift`, run from the
# LAPTOP to give three roles a trust policy naming the instance, archived
# `iam.update_assume_role_policy` into evidence/ — and the audit then demanded a mapping for it, so
# the derivation's only two options were "grant a trust-policy write to the instance" or "fail the
# gate forever". Neither is right. The provisioner is not the runner: it runs from a workstation
# under a human's credentials, and the instance has never needed to call this.
#
# Why refusing matters more here than the prefix scope would suggest: the runner already holds
# `iam:PutRolePolicy` on `grx-*`, so it can already change what those roles may DO.
# `UpdateAssumeRolePolicy` changes who may BECOME them, which is a different and worse power — a
# principal from outside this account can be added to a trust policy, and that is a cross-account
# path out of the blast radius the prefix is supposed to define. "It is already scoped to grx-*" is
# not an answer, because the scope bounds which roles are affected, not who ends up holding them.
MEASURED_NOT_GRANTED: dict[tuple[str, str], str] = {
    ("iam", "update_assume_role_policy"):
        "trust-policy write, performed by infra/01_iam.py --fix-drift from a workstation under a "
        "human's credentials. The instance has never called it and must not be able to: combined "
        "with the PutRolePolicy it already holds on grx-*, it would let a compromised instance "
        "hand a grx- role to a principal in another account.",
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
    """Measured pairs that are neither mapped nor explicitly refused. Asserted empty by
    `runner/tests/`.

    A pair in `MEASURED_NOT_GRANTED` counts as ACCOUNTED FOR, not as granted: somebody has looked at
    it and written down why the instance does not get it. The alternative was a gate that can only
    be satisfied by granting, which turns "least privilege" into "whatever the provisioner happened
    to call".
    """
    return sorted(pair for pair in measured_operations()
                  if pair not in MAPPING and pair not in MEASURED_NOT_GRANTED)


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
        # Managed policies, for F5-3b's permissions boundaries. A separate scope and not a second
        # ARN on the role scope, because `iam:CreatePolicy` and `iam:PutRolePolicy` would then each
        # be granted on both resource shapes, which is wider than either needs.
        "policy": [f"arn:aws:iam::{account_id}:policy/{NAME_PREFIX}*"],
        "function": [f"arn:aws:lambda:{region}:{account_id}:function:{NAME_PREFIX}*"],
        "log_group": [
            f"arn:aws:logs:{region}:{account_id}:log-group:{VENDED_LOG_PREFIX}*",
            f"arn:aws:logs:{region}:{account_id}:log-group:{VENDED_LOG_PREFIX}*:*",
        ],
        # The AgentCore Runtime deployment-package bucket, named by the same rule the producer
        # names it by. Both ARN shapes are present because the three actions on this scope split
        # across them: `s3:ListBucket` is authorized against the BUCKET (that is what HeadBucket
        # checks), while PutObject and DeleteObject are authorized against the OBJECT. A scope
        # carrying only one shape would deny half its own actions.
        "code_bucket": [
            f"arn:aws:s3:::{NAME_PREFIX}{CODE_BUCKET_STEM}-{account_id}-{region}",
            f"arn:aws:s3:::{NAME_PREFIX}{CODE_BUCKET_STEM}-{account_id}-{region}/*",
        ],
    }
    # PassRole, GetRole and AssumeRole belong on the role scope, not on `*`: PassRole on `*` is the
    # escalation this whole file exists to avoid, and AssumeRole on `*` is the same escalation by a
    # shorter route.
    #
    # The `|=` below GRANTS, it does not merely move, and that was worth catching. A mutation run on
    # 2026-08-13 deleted `sts:AssumeRole` from RUNNER_EXTRAS and the document came out UNCHANGED,
    # because that line adds the action whether or not anything declared it — so the entry carrying
    # the written reason was decorative and `test_every_runner_extra_carries_a_written_reason` was
    # guarding a string nothing depended on. Every member is now required to be DECLARED first, which
    # makes the reason load-bearing: an action reaches the role scope only by being in RUNNER_EXTRAS
    # (with its reason) or in MAPPING (with the measured call that needs it).
    declared = set(RUNNER_EXTRAS) | {a for actions, _ in MAPPING.values() for a in actions}
    undeclared = [a for a in ROLE_SCOPED_EXTRAS if a not in declared]
    if undeclared:
        raise RuntimeError(
            f"ROLE_SCOPED_EXTRAS names {undeclared}, which no MAPPING entry and no RUNNER_EXTRAS "
            f"entry declares. Moving an action onto the role scope is not how it acquires a reason "
            f"to exist — add it to RUNNER_EXTRAS with one, or to MAPPING with the call that needs it.")
    by_scope["any"] -= set(ROLE_SCOPED_EXTRAS)
    by_scope["role"] |= set(ROLE_SCOPED_EXTRAS)

    # `s3:GetObject` onto the code bucket, by the same declared-first rule.
    undeclared_cb = [a for a in CODE_BUCKET_SCOPED_EXTRAS if a not in declared]
    if undeclared_cb:
        raise RuntimeError(
            f"CODE_BUCKET_SCOPED_EXTRAS names {undeclared_cb}, which nothing declares. Add it to "
            f"RUNNER_EXTRAS with a written reason, or to MAPPING with the call that needs it.")
    by_scope["any"] -= set(CODE_BUCKET_SCOPED_EXTRAS)
    by_scope.setdefault("code_bucket", set()).update(CODE_BUCKET_SCOPED_EXTRAS)

    # The emitted order is a literal tuple, so a MAPPING entry naming a scope that is not in it —
    # a typo, or a new scope added to MAPPING and forgotten here — would be silently DROPPED and the
    # resulting policy would deny those calls while looking complete. Adding the `policy` scope on
    # 2026-08-13 is what made this reachable: before it, all four scopes were as old as the file.
    emitted = ("any", "role", "policy", "function", "log_group", "code_bucket")
    orphans = sorted(set(by_scope) - set(emitted))
    if orphans:
        raise RuntimeError(
            f"MAPPING uses scope(s) {orphans} that `statements()` does not emit, so every action "
            f"in them would be silently dropped from the policy. Add each to `emitted` and to "
            f"`resources` with the narrowest ARN pattern that works.")
    missing_resources = sorted(s for s in by_scope if s not in resources)
    if missing_resources:
        raise RuntimeError(f"no resource pattern defined for scope(s) {missing_resources}")

    out = [{"Sid": f"Grx{scope.title().replace('_', '')}",
            "Effect": "Allow",
            "Action": sorted(by_scope[scope]),
            "Resource": resources[scope]}
           for scope in emitted if by_scope.get(scope)]

    # The first Deny in this file, added 2026-08-14 with `iam:DeleteRole`. Every IAM grant here is
    # scoped to `role/grx-*`, which was a sufficient boundary while the granted verbs were
    # Create/Put/Get — but `grx-*` contains two roles that are not testbed, and for them a delete or
    # a policy write is not a cleanup, it is damage to something already published:
    #
    #   grx-runner-ec2        the instance's OWN role. Deleting it ends the run that deleted it and
    #                         every run after, and re-provisioning is a laptop operation, so a
    #                         detached job that did this would strand the instance unreachable.
    #   grx-runtime-exec-*    F5-1's published oracle. That case's finding IS the emptiness of this
    #                         role's inline policy set; `infra/01_iam.py --ensure` refuses to run on
    #                         drift and `f5_redteam/01_route1_direct_invoke.py` asserts the exact
    #                         baseline at startup. A PutRolePolicy here does not break a test, it
    #                         retroactively falsifies a verdict that has already been published --
    #                         and it would do so silently, because the policy would look like setup.
    #
    # An explicit Deny and not a narrower Allow, because Deny wins over every Allow in the same
    # policy: a future scope added to MAPPING cannot widen its way past this, which is the property
    # a comment asking people to be careful does not have. The READ verbs stay allowed on purpose --
    # F5-1 has to be able to `list_role_policies` on the role it is making a claim about.
    out.append({
        "Sid": "GrxProtectLoadBearingRoles",
        "Effect": "Deny",
        "Action": ["iam:DeleteRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
                   "iam:AttachRolePolicy", "iam:UpdateAssumeRolePolicy",
                   "iam:PutRolePermissionsBoundary"],
        "Resource": [f"arn:aws:iam::{account_id}:role/grx-runner-ec2",
                     f"arn:aws:iam::{account_id}:role/grx-runtime-exec-*"],
    })

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
