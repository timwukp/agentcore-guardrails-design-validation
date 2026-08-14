"""F1-15 — does a policy engine attach and evaluate on all three gateway target types?

Sealed oracle (`lib/oracle.py`, `Binding("EXISTENCE")`)
------------------------------------------------------
    TRUE if a policy engine attaches and evaluates on all three target types;
    FALSE if any target type bypasses policy evaluation

The three types are the claim's, not this file's. `C-s4-1-bullet-007` (`claims/triage.csv:147`)
names them by wire surface: MCP targets (`POST /mcp`, JSON-RPC `tools/call`), HTTP runtime targets
(`POST /<target>/invocations`), and HTTP inference targets (`POST /inference`) — "not MCP tools
only". `CreateGatewayTarget`'s `targetConfiguration` union has exactly three arms, `mcp` / `http` /
`inference`, and they line up with the claim one for one.

What the diagnostic settled before this file was written
--------------------------------------------------------
`f1_config/diag_target_types.py` ran on 2026-08-14 (`results/DIAG-target-types-20260814T054243Z.json`)
and answered the three unknowns that decide this case's design. Two of them changed it:

  1. **The `http` arm cannot be created here at all.** `CreateGatewayTarget` refused it with

         ValidationException: HTTP target configuration is not supported for gateways with MCP
         protocol type. Provide an MCP-compatible target configuration and retry the request.

     and `CreateGateway`'s `protocolType` is an enum whose ONLY member is `MCP` (botocore 1.43.67).
     So there is no gateway this API can create on which an `http.*` target is accepted. This is
     not a permission, a quota or a Region gap — it is the shape of the API. Note it also disposes
     of the substitution the dependency audit worried about: the refusal names the whole `http`
     arm, so `http.passthrough` was never an available shortcut either.

  2. **The inference surface is real, and it is not at the path the claim gives.** `POST /inference`
     returned `{"success":false,"error":"Http operation is not supported for gateway protocol type
     MCP"}` — the same MCP wall. But `POST /inference/v1/messages` returned

         {"type":"error","error":{"type":"invalid_request_error",
          "message":"Missing required field 'model' in request body"}}

     which is a *provider-shaped* validation error, so the gateway accepted the path, routed the
     request, and something downstream parsed it. The inference target type exists and is reachable;
     the claim's spelling of its path does not.

  3. An `inference.provider` target with a plain HTTPS `endpoint` reached READY in 5.2 s on an MCP
     gateway. The arm needs no connector and no allow-listed provider.

Why this case cannot return TRUE or FALSE, and why that is a result
-------------------------------------------------------------------
The oracle quantifies over three target types. One of them is unconstructible, so:

  * It is not FALSE. FALSE requires a target type that "bypasses policy evaluation" — a request
    that reaches a tool without the engine seeing it. A target type that cannot be created never
    carries a request, so nothing bypasses anything. Recording FALSE would publish a security
    failure that did not happen.
  * It is not TRUE. TRUE requires the engine to evaluate on all three. Two is not three, and
    reading "all three" as "all that exist" is a substitution the seal does not license — the same
    defect `f3_efficacy/07_model_drift.py:724` names when it cites "answering F1-15 with an
    `http.passthrough` target" as the archetype: it decides a different quantity than the seal, and
    because the verdict is one word the substitution is invisible in the published record.

So the verdict is INCONCLUSIVE via `oracle.not_measured()`, and the INCONCLUSIVE is the honest
report of a testbed limit that is really an API limit. `PREREGISTRATION.yaml`'s standing rule
applies and is worth restating at the site: **INCONCLUSIVE is not FALSE and licenses no amendment
to the document.** The claim is not refuted here. What is established is narrower and still worth
publishing: at this API version, in this Region, the document's three-target-type sentence names a
target type the service will not create.

What this file therefore measures
---------------------------------
Everything that CAN be measured, so the INCONCLUSIVE is bounded by evidence rather than by an
absent attempt:

  * The `http` arm is attempted anyway, every run, and its refusal is captured through `capture()`.
    An unconstructible arm asserted from a diagnostic is hearsay in the case's own record; a case
    whose payload contains the ValidationException is not. It also means the day this enum grows a
    second member, this case starts succeeding instead of silently staying INCONCLUSIVE.
  * For the two arms that DO exist, policy evaluation is measured directly, with a baseline. A
    denial observed under a `forbid` means nothing unless the same call was observed to succeed
    without it — otherwise "the engine denied it" and "the call never worked" are the same
    observation. So each live arm is invoked twice: once with no policy on the engine, once with a
    gateway-scoped `forbid` ACTIVE.

The instrument: one gateway-scoped `forbid`, no condition
---------------------------------------------------------
    forbid (principal, action, resource == AgentCore::Gateway::"<disposable gateway arn>");

Unconstrained action ON PURPOSE, and it is what makes this case answerable at all. The Cedar action
id for an MCP tool is `<TargetName>___<ToolName>` (`lib/cedar.py:147`) — but what the action id of an
*inference* request is, nobody here knows, and the whole question is whether the engine sees such a
request. A policy that had to name the action could only be written for the target type whose
grammar is already known, so it could not ask the question about the other one. An unconstrained
action asks it uniformly: if the engine evaluates this statement for a request, the request is
denied whatever its action turns out to be.

No `when` clause either, and that is not laziness. Round 3 of `f1_config/diag_resource_form.py`
measured that a conditional statement needs a SPECIFIC action, because the attribute the condition
reads has to exist in that action's context — `context.input.text` was refused against an
unconstrained action, with the service naming the built-in `CallTool`. A bare `forbid` has no
attribute to resolve, so it sidesteps a constraint that would otherwise force the action back into
the head.

`resource ==` a specific ARN, not `resource is AgentCore::Gateway`. The type form applies to every
gateway on the engine, and this engine is shared with `gateway/main` — the ENFORCE half of the F6
pair. A type-scoped `forbid` would take `main` down for as long as it existed, which for a
`forbid(principal, action, ...)` means every F4 and F6 call in flight would deny. The ARN form
confines the blast radius to a gateway this script created and will delete. (The type form is also
what drew `not authorized to perform: bedrock-agentcore:ManageAdminPolicy` on 2026-08-14, so it is
plausibly not even available to this caller.)

`enforcementMode="ACTIVE"`, which is the one place this file departs from the diagnostics that came
before it. `f1_config/diag_resource_form.py` creates every policy `LOG_ONLY` precisely so a
transiently-live `forbid` cannot change a shared gateway's behaviour. Here the behaviour change IS
the measurement — LOG_ONLY would produce a record of evaluation in a log and no observable decision
at the caller — and it is safe for the same reason the resource form is: the only gateway the
statement can match is the disposable one. `validationMode="IGNORE_ALL_FINDINGS"` because a DC-1
"Overly Permissive"-style finding on the way in would block a policy whose findings are not what
this case is about.

Running on a disposable clone, and never on `main`
-------------------------------------------------
The gateway is cloned from `main`'s live `GetGateway` response through `CreateGateway`'s own input
shape (`f5_redteam/02_route3_updategateway.py:865-873`), which carries the same
`policyEngineConfiguration` — verified by the diagnostic, whose report records
`clone_has_policy_engine: true`. Cloning rather than hand-building matters: the question is whether
the engine evaluates on the gateway configuration this project validates, and a gateway differing in
one member would answer it about a configuration nobody has.

Nothing in the tree asserts `main`'s target count — `list_gateway_targets` has exactly one call site
(`infra/05_target.py:121`) and it searches by name — so adding targets there would not have broken a
test. It would still have been wrong: extra targets advertise extra tools in `tools/list` on the
ENFORCE half of a matched pair, and the `forbid` above would have had to be scoped away from the
very gateway it was attached to.

Teardown, and the propagation delay that has to be retried
----------------------------------------------------------
Targets before the gateway (a gateway with targets will not delete), then the policy, then the
gateway. The diagnostic measured that this is not enough on its own: every `delete_gateway_target`
returned ok, `list_gateway_targets` then returned an EMPTY list, and `delete_gateway` still failed
`ValidationException` — the deletions had not finished propagating service-side. A retry 15 s later
succeeded. So the gateway delete is retried, because the thing left behind on a single-attempt
failure is a gateway holding a `policyEngineConfiguration` and billing.

Every resource is recorded in the ledger BEFORE it is created and dropped only AFTER its delete
returns ok. Policies are untaggable, so for the `forbid` the ledger is the only channel that finds a
survivor after a kill — and a surviving `forbid`, even ARN-scoped, is the one piece of residue here
that could change another case's result if its gateway id were ever reused.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                               # noqa: E402
import cedar as C                                                    # noqa: E402
import mcp as M                                                      # noqa: E402
import oracle as O                                                   # noqa: E402
import phase1 as P                                                   # noqa: E402
import redact as R                                                   # noqa: E402
import testbed as T                                                  # noqa: E402
from botocore.auth import SigV4Auth                                  # noqa: E402
from botocore.awsrequest import AWSRequest                           # noqa: E402
from evidence import EvidenceStore, capture                          # noqa: E402

import urllib3                                                       # noqa: E402

FAMILY = "f1_config"
CASE = "F1-15"

SIGNING_SERVICE = "bedrock-agentcore"

# The MCP arm reuses `grxecho` as its target NAME on purpose. The name is the Cedar action prefix
# (`<TargetName>___<ToolName>`, and it may not contain an underscore — asserted at
# infra/05_target.py:167-170), so keeping it identical means the action id this case exercises is
# `grxecho___echo`, byte for byte the id F5-4a and infra/08_smoke.py have already driven. Names are
# scoped per gateway, so this collides with nothing on `main`.
MCP_TARGET_NAME = "grxecho"
MCP_TOOL = "echo"
# amount < 500, so the call is benign under every numeric condition this testbed has ever authored.
# It matters that the baseline call is one nothing else would deny: the baseline's job is to show the
# call works, and a baseline that failed for an unrelated reason would make the forbid unreadable.
MCP_ARGS = {"text": "F1-15 target type coverage", "amount": 100}

INFERENCE_TARGET_NAME = "grxinference"
# Measured, not guessed: `/inference` is refused on an MCP gateway and `/inference/v1/messages` is
# served. See the module docstring, and `results/DIAG-target-types-20260814T054243Z.json` for the
# two response bodies that separate them.
INFERENCE_PATH = "/inference/v1/messages"
INFERENCE_ENDPOINT = "https://bedrock-runtime.us-east-1.amazonaws.com"
# Measured, not chosen. The first run of this case sent `anthropic.claude-3-5-haiku-20241022-v1:0`
# and got HTTP 400 "Model ID contains invalid characters" — the colon. It is not a quirk of one id:
# `operations[].models[].model` in `CreateGatewayTarget`'s shape has pattern
# `[a-zA-Z0-9\-\._\*\?@]+(/...)*`, which admits `*` and `?` globs and no colon at all, so Bedrock's
# `...-v1:0` form cannot be spelled on this surface. `f1_config/diag_inference_body.py` carries the
# measurement and the controls that separate the charset wall from the routing wall behind it.
#
# Whether the UPSTREAM provider answers is not this case's question — a provider-side 4xx still shows
# the gateway forwarded rather than denied, and that is the distinction being measured. What matters
# is only that the request gets far enough to be eligible for a denial.
INFERENCE_MODEL = "anthropic.claude-3-5-haiku-20241022-v1"

HTTP_TARGET_NAME = "grxhttpruntime"

POLL_SECONDS = 5
POLL_TIMEOUT = 300
TERMINAL_GW = {"READY", "FAILED", "CREATE_FAILED", "UPDATE_FAILED"}
TERMINAL_TGT = {"READY", "FAILED", "CREATE_FAILED", "UPDATE_FAILED",
                "CREATE_PENDING_AUTH", "UPDATE_PENDING_AUTH", "SYNCHRONIZE_PENDING_AUTH"}
TERMINAL_POL = {"ACTIVE", "CREATE_FAILED", "FAILED"}

DELETE_ATTEMPTS = 4
DELETE_BACKOFF_S = 15
# After the forbid reports ACTIVE. A policy that is ACTIVE on the control plane is not necessarily
# being applied by the data plane yet, and the failure mode is the worst one available here: the
# post-policy call would be observed as ALLOWED and read as "this target type bypasses policy
# evaluation", which is this case's FALSE. A settle is cheap; that mistake is a published verdict.
POLICY_SETTLE_S = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fake_runtime_arn(region: str, account: str) -> str:
    """A pattern-valid ARN for a runtime that does not exist.

    The `http` arm is attempted to capture its refusal, and the refusal is about the arm and the
    gateway's protocol type — it happens before anything resolves the ARN, which the diagnostic
    confirmed by getting the identical message with this same absent runtime. Building a real
    runtime to feed an arm that is rejected for being the wrong arm would cost a role, a zip, an
    upload and a ~10 s create to learn nothing extra.
    """
    return f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/grx_f115_absent-zzzzzzzzzz"


def arms(region: str, account: str, lambda_arn: str, tool_schema: list[dict]) -> list[dict]:
    """One entry per target type the claim names, in the claim's own order."""
    creds = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
    return [
        {"label": "mcp", "name": MCP_TARGET_NAME,
         "claim_surface": "MCP target: POST /mcp, JSON-RPC tools/call",
         "config": {"mcp": {"lambda": {"lambdaArn": lambda_arn,
                                       "toolSchema": {"inlinePayload": tool_schema}}}},
         "credentials": creds},
        {"label": "http_runtime", "name": HTTP_TARGET_NAME,
         "claim_surface": "HTTP runtime target: POST /<target>/invocations",
         "config": {"http": {"agentcoreRuntime": {"arn": fake_runtime_arn(region, account)}}},
         "credentials": creds},
        # `operations` and `models` are not optional decoration here, even though the API marks them
        # optional. `f1_config/diag_inference_body.py` round 1 created this target with `endpoint`
        # alone and every colon-free model id came back 404 "Model '...' not found on any target":
        # a `provider` target that declares no models advertises nothing, so the gateway's routing
        # layer can never select it and no request reaches a point where policy could apply. A target
        # that exists but cannot be routed to is not a target type under test.
        {"label": "inference", "name": INFERENCE_TARGET_NAME,
         "claim_surface": "HTTP inference target: POST /inference",
         "config": {"inference": {"provider": {
             "endpoint": INFERENCE_ENDPOINT,
             # `path` is the CLIENT-facing path, served under the gateway's `/inference` prefix —
             # which is why the live surface is `/inference/v1/messages` and not `/inference`.
             "operations": [{"path": "/v1/messages",
                             "models": [{"model": "anthropic.claude-*"},
                                        {"model": "claude-*"}]}]}}},
         "credentials": creds},
    ]


def signed_post(pool, creds, region: str, url: str, body: bytes, timeout_s: float) -> dict:
    """One SigV4-signed POST, reported as data rather than raised.

    `connection` is kept out of the signed headers for the reason `lib/mcp.py:483-489` gives. A
    transport failure is captured in the same shape as a response because for this case every
    outcome is an observation — the question is what the gateway did, and "it did not answer" is a
    legitimate answer that must not become a traceback inside a `try` that owns live resources.
    """
    h = {"content-type": "application/json", "accept": "application/json"}
    frozen = creds.get_frozen_credentials() if hasattr(creds, "get_frozen_credentials") else creds
    req = AWSRequest(method="POST", url=url, data=body, headers=h)
    SigV4Auth(frozen, SIGNING_SERVICE, region).add_auth(req)
    started = time.time()
    try:
        resp = pool.request("POST", url, body=body, headers=dict(req.headers), redirect=False,
                            timeout=urllib3.Timeout(connect=10, read=timeout_s))
    except Exception as exc:                                          # noqa: BLE001
        return {"transport_error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - started, 3)}
    raw = resp.data.decode("utf-8", "replace")
    return {"status": resp.status, "body_head": R.mask(raw[:1500]),
            "body_bytes": len(resp.data), "elapsed_s": round(time.time() - started, 3)}


def classify_inference(out: dict) -> str:
    """What one inference-path response says about POLICY, not about the provider.

    `front_door_reject` is checked early and exists because its absence produced a WRONG VERDICT.
    The first run of this case (2026-08-14) sent the model id
    `anthropic.claude-3-5-haiku-20241022-v1:0` and got HTTP 400
    `{"error":{"type":"invalid_request_error","message":"Model ID contains invalid characters."}}` in
    38 ms — both before AND after a live `forbid`, byte for byte. The earlier version of this
    function matched `invalid_request_error` and called that `routed`, meaning "the gateway forwarded
    rather than denied"; the scorer then read routed-in-both-phases as a BYPASS and published FALSE.

    That is DEV-P4-22 (`f3_efficacy/08_score_label_join.py:425-448`) arriving on a surface this
    producer had not thought to apply it to. It guarded the MCP arm against precisely this failure —
    a bad tool name errors BEFORE policy evaluation, so the window measures traffic the engine never
    saw — and then walked into the same trap on the inference arm. A request the gateway refuses on
    input validation never reaches the engine, so both observations were uninterpretable and a
    security failure was published from the pair anyway. The 38 ms was a second tell: too fast to
    have crossed an engine and an upstream provider.

    Hence a bucket whose only job is to say "this observation is not eligible to be interpreted".
    `f1_config/diag_inference_body.py` measures which bodies clear the front door; `INFERENCE_MODEL`
    carries its answer.

    Buckets:

    * `policy_denied`     -- the response names policy enforcement. The engine evaluated.
    * `front_door_reject` -- the gateway's own input validation. Pre-evaluation, so neither a bypass
                             nor evidence of anything about policy.
    * `gateway_error`     -- refused for protocol/path/signature reasons. Silent on policy.
    * `provider_reached`  -- an error recognisably the UPSTREAM's (model access, throttle, unknown
                             model at Bedrock). The request crossed the gateway.
    * `allowed`           -- 2xx, end to end.

    Only `allowed` and `provider_reached` mean the request travelled far enough that a denial would
    have had to intervene, so only those two can witness a bypass.

    The denial markers are the ones `lib/mcp.py:343-349` measured on this service: a policy denial
    arrives as JSON-RPC -32002 with "Tool Execution Denied" / "not allowed due to policy
    enforcement" / "Policy evaluation denied", not the documented `isError` + AuthorizeAction shape.
    Matched on response TEXT rather than status, because this surface is not JSON-RPC and its error
    envelope belongs to the provider.
    """
    if "transport_error" in out:
        return "gateway_error"
    text = (out.get("body_head") or "").lower()
    for marker in ("policy enforcement", "policy evaluation denied", "tool execution denied",
                   "authorizeaction", "not allowed due to policy", "-32002"):
        if marker in text:
            return "policy_denied"
    # Matched on the validator's own wording, not on the generic `invalid_request_error` envelope
    # that wraps it — that envelope is also what a legitimate provider-side rejection uses.
    #
    # "not found on any target" is the gateway's ROUTING layer, and it belongs in this bucket for the
    # same reason: `f1_config/diag_inference_body.py` round 1 measured it on a `provider` target that
    # declared no `operations[].models`, so no model id could map to it. A request that never chose a
    # target is a request the engine had no target to evaluate against, which is just as
    # pre-evaluation as a charset rejection and just as uninterpretable.
    if ("contains invalid characters" in text or "missing required field" in text
            or "not found on any target" in text or "not_found_error" in text):
        return "front_door_reject"
    status = out.get("status")
    if status and 200 <= status < 300:
        return "allowed"
    # A gateway complaining about its own protocol or path is not a policy decision. Matched
    # narrowly and on the gateway's own wording, so a provider error that happens to contain the
    # word "supported" is not swept in here.
    if "is not supported for gateway protocol type" in text or "http operation is not supported" \
            in text:
        return "gateway_error"
    if any(k in text for k in ("accessdenied", "not authorized", "don't have access", "throttl",
                               "toomanyrequests", "on-demand throughput", "isn't supported",
                               "validationexception", "serviceunavailable", "internalserver")):
        return "provider_reached"
    return "gateway_error"


def wait_gateway(ac, gid: str) -> tuple[str, float]:
    started = time.time()
    while True:
        st = ac.get_gateway(gatewayIdentifier=gid).get("status", "")
        if st in TERMINAL_GW or time.time() - started > POLL_TIMEOUT:
            return st, round(time.time() - started, 1)
        time.sleep(POLL_SECONDS)


def wait_target(ac, gid: str, tid: str) -> tuple[str, float, dict]:
    started = time.time()
    while True:
        got = ac.get_gateway_target(gatewayIdentifier=gid, targetId=tid)
        st = got.get("status", "")
        if st in TERMINAL_TGT or time.time() - started > POLL_TIMEOUT:
            return st, round(time.time() - started, 1), got
        time.sleep(POLL_SECONDS)


def wait_policy(ac, eid: str, pid: str) -> tuple[str, float, dict]:
    started = time.time()
    while True:
        got = ac.get_policy(policyEngineId=eid, policyId=pid)
        st = got.get("status", "")
        if st in TERMINAL_POL or time.time() - started > POLL_TIMEOUT:
            return st, round(time.time() - started, 1), got
        time.sleep(POLL_SECONDS)


def call_mcp(fc, store, gw_url: str, run_id: str, phase: str, timeout_s: int) -> dict:
    """`tools/list` then `tools/call echo` through the MCP surface, as two observations.

    Both are recorded, and the FIRST one turned out to carry the case. The first run of this
    producer returned `tool_not_advertised` for the post-policy MCP phase and stopped there, which
    the scorer read as `unknown`. Looking at what it had actually captured:

        baseline      advertised: [grxecho___delay, grxecho___echo, grxecho___fixed]  outcome allowed
        under_forbid  advertised: []                                 list_outcome allowed

    `tools/list` SUCCEEDED under the forbid and returned nothing. The engine did not fail the
    listing; it filtered every tool out of it. That is the policy engine evaluating on the MCP target
    type — a directly observed change in the gateway's behaviour caused by the policy — and the first
    version discarded it as an inconclusive precondition because it was looking only for a denial on
    the call.

    So the listing is now reported as data in both phases (`advertised`, `listed`) and the call is
    attempted regardless of whether the tool appears. Attempting it anyway is not a relapse into
    DEV-P4-22, which is a trap about SILENTLY measuring pre-evaluation traffic: the two facts are
    recorded separately, so a `-32002` is readable as a denial while a tool-not-found is readable as
    an artifact of the empty listing rather than as an allow. Making the call is also the only way to
    find out which of those two the service does, and if it is `-32002` the case gets an unambiguous
    denial on top of the filtering.

    The client is built from the project factory, not `boto3.Session()`, because the factory may hold
    an assumed `grx-caller` session and Cedar's principal is that assumed role. Ambient user
    credentials would present a different principal, and under a `principal ==` policy every arm
    would default-deny — indistinguishable from the policy working (`lib/mcp.py:814-821`).
    """
    action = C.action_id(MCP_TARGET_NAME, MCP_TOOL)
    out: dict = {"action_id": action}
    try:
        client = M.client_for(gw_url, fc, store=store,
                              policy_session_id=M.policy_session_id(run_id, f"f115-{phase}"),
                              session_timeout_s=timeout_s)
        client.initialize()
        tools, d_list = client.list_tools()
        names = [t.get("name") for t in tools]
        out.update({"advertised": names, "listed": action in names,
                    "list_outcome": d_list.outcome, "list_is_error": d_list.is_error,
                    "list_jsonrpc_error": R.mask(d_list.jsonrpc_error)
                                          if d_list.jsonrpc_error else None})
        d = client.call_tool(action, MCP_ARGS)
        out.update({"outcome": d.outcome, "http_status": d.http_status, "is_error": d.is_error,
                    "default_deny": d.default_deny, "authorize_exception": d.authorize_exception,
                    "unclassified": d.unclassified, "duration_ms": round(d.duration_ms, 1),
                    "text_head": R.mask((d.text or "")[:600]),
                    "jsonrpc_error": R.mask(d.jsonrpc_error) if d.jsonrpc_error else None})
        return out
    except Exception as exc:                                          # noqa: BLE001
        out.update({"outcome": "transport_error", "error": f"{type(exc).__name__}: {exc}"})
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--state")
    ap.add_argument("--evidence-root")
    ap.add_argument("--read-timeout", type=float, default=30.0)
    ap.add_argument("--inference-model", default=INFERENCE_MODEL,
                    help="model id for the inference arm's request body. The default is whatever "
                         "f1_config/diag_inference_body.py measured as clearing the gateway's "
                         "front-door validation; override only with another measured value, since "
                         "a body the gateway rejects on validation produces observations that are "
                         "not eligible to be interpreted (see classify_inference)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the arms, the forbid statement and the paths; call nothing")
    args = ap.parse_args()

    if O.mutation_is_mandatory(CASE):
        raise SystemExit(
            f"{CASE} is sealed with a mandatory mutation arm and this script implements a single "
            f"observation arm. Publishing without the mutation would publish under a rule the seal "
            f"does not name.")

    if args.dry_run:
        acct = "111122223333"
        gw_arn = f"arn:aws:bedrock-agentcore:{args.region}:{acct}:gateway/grx-gw-f115-example"
        print(json.dumps({
            "case": CASE, "oracle": O.oracle_text(CASE),
            "arms": [{k: v for k, v in a.items() if k != "credentials"}
                     for a in arms(args.region, acct,
                                   f"arn:aws:lambda:{args.region}:{acct}:function:grx-echo",
                                   [{"name": MCP_TOOL}])],
            "forbid_statement": C.statement("forbid", resource=C.gateway_resource(gw_arn)),
            "definition_member": C.GUARDRAILS_DEFINITION_MEMBER,
            "mcp_action_id": C.action_id(MCP_TARGET_NAME, MCP_TOOL),
            "inference_path": INFERENCE_PATH,
        }, indent=2))
        return 0

    state = T.State.load(Path(args.state) if args.state else None)
    run_id = state.run_id
    if state.region != args.region:
        raise SystemExit(f"ledger is for {state.region}, not {args.region}")

    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    fc = A.factory(args.region)
    account = A.account_id(fc)
    ac = fc.client("bedrock-agentcore-control")

    main_gw = state.get("gateway", "main")
    engine = state.get("policy-engine", "main")
    engine_id = engine.ids["policy_engine_id"]
    lam = state.get("lambda", "echo")
    lambda_arn = T.unmask_arn(lam.arn, account)
    sys.path.insert(0, str(ROOT / "infra"))
    import echo_handler                                               # noqa: E402
    tool_schema = list(echo_handler.TOOL_SCHEMA)

    print(f"{CASE} — run_id={run_id}, region={args.region}")
    print(f"  oracle: {O.oracle_text(CASE)}\n")

    payload: dict = {
        "case": CASE, "run_id": run_id, "region": args.region, "started_utc": _now_iso(),
        "oracle_text": O.oracle_text(CASE),
        "claim": "C-s4-1-bullet-007",
        "diagnostic": "results/DIAG-target-types-20260814T054243Z.json",
        "policy_engine_id": engine_id,
        "inference_model": args.inference_model,
        "gateway_protocol_type_enum": list(
            ac.meta.service_model.operation_model("CreateGateway")
            .input_shape.members["protocolType"].metadata.get("enum") or []),
        "arms": {}, "baseline": {}, "under_forbid": {}, "notes": [],
    }

    gid = ""
    gw_arn = ""
    gw_url = ""
    created: list[tuple[str, str]] = []
    policy_id = ""
    live: dict[str, str] = {}          # label -> target name, for arms that exist

    try:
        # ---- 1. the disposable clone, carrying main's policy engine ------------
        got_main = ac.get_gateway(gatewayIdentifier=main_gw.ids["gateway_id"])
        create_allowed = frozenset(
            ac.meta.service_model.operation_model("CreateGateway").input_shape.members)
        name = T.check_name(ac, "CreateGateway", f"grx-gw-f115-{run_id}"[:48])
        kw = {k: copy.deepcopy(v) for k, v in got_main.items() if k in create_allowed}
        kw["name"] = name
        kw["description"] = (f"GRX {CASE} disposable: one target per targetConfiguration arm, with "
                             f"an ARN-scoped forbid. Delete on sight.")[:200]
        kw["tags"] = A.tags_for(run_id, state.expires_at)
        pec = kw.get("policyEngineConfiguration") or {}
        if not pec:
            raise SystemExit(
                "the clone of gateway/main carries no policyEngineConfiguration, so this case "
                "would measure a gateway with no engine attached and every arm would read as a "
                "bypass. CreateGateway's input shape or GetGateway's output changed; set the "
                "member explicitly from the ledger's policy-engine id before re-running.")
        payload["policy_engine_mode"] = pec.get("mode")

        state.record(T.Resource(
            kind="gateway", logical="f115", name=name, service="bedrock-agentcore-control",
            delete_op="delete_gateway", delete_params={"gatewayIdentifier": name},
            ids={"gateway_id": "", "case": CASE}, delete_priority=30,
            notes=f"{CASE} disposable gateway. If this is still here the run did not reach its "
                  f"teardown; it holds a policyEngineConfiguration and bills."))
        state.write()

        A.limiter().wait("CreateGateway")
        made = capture(store, "create_gateway", ac, **kw).raise_for_status()
        gid = made.response["gatewayId"]
        gw_arn = made.response.get("gatewayArn", "")
        gw_url = made.response.get("gatewayUrl", "")
        state.record(T.Resource(
            kind="gateway", logical="f115", name=name, service="bedrock-agentcore-control",
            delete_op="delete_gateway", delete_params={"gatewayIdentifier": gid},
            ids={"gateway_id": gid, "gateway_url": gw_url, "case": CASE},
            arn=gw_arn, delete_priority=30, notes=f"{CASE} disposable gateway."))
        state.write()

        st, secs = wait_gateway(ac, gid)
        payload["gateway"] = {"id": gid, "status": st, "seconds_to_terminal": secs,
                              "url": R.mask(gw_url), "arn": R.mask(gw_arn)}
        print(f"  gateway {gid}: {st} after {secs}s")
        if st != "READY":
            payload["notes"].append(f"the clone settled {st}; nothing below is interpretable")
            return _emit_inconclusive(
                payload, store,
                f"the disposable gateway settled {st} instead of READY, so no target type was "
                f"exercised")

        base = gw_url.rsplit("/mcp", 1)[0] if gw_url.endswith("/mcp") else gw_url.rstrip("/")

        # ---- 2. one target per arm; the http refusal is a measurement ----------
        for arm in arms(args.region, account, lambda_arn, tool_schema):
            label, tname = arm["label"], arm["name"]
            row = {"claim_surface": arm["claim_surface"], "target_name": tname,
                   "config": R.mask(arm["config"])}
            A.limiter().wait("CreateGatewayTarget")
            rec = capture(store, "create_gateway_target", ac, gatewayIdentifier=gid, name=tname,
                          description=f"GRX {CASE} {label}"[:200],
                          targetConfiguration=arm["config"],
                          credentialProviderConfigurations=arm["credentials"])
            row["constructible"] = bool(rec.ok)
            if rec.ok:
                tid = rec.response["targetId"]
                created.append((label, tid))
                tst, tsecs, _ = wait_target(ac, gid, tid)
                row.update({"target_id": tid, "status": tst, "seconds_to_terminal": tsecs})
                if tst == "READY":
                    live[label] = tname
                print(f"  arm {label:14s} CREATED -> {tst} after {tsecs}s")
            else:
                row.update({"error_code": rec.error_code or rec.error_class,
                            "error_message": R.mask(str(rec.error_message))})
                print(f"  arm {label:14s} REFUSED: {row['error_code']}: "
                      f"{str(row['error_message'])[:150]}")
            payload["arms"][label] = row

        # ---- 3. baseline: do the live arms work with NO policy? ----------------
        pool = urllib3.PoolManager(retries=False)
        creds = fc.session().get_credentials()
        session_timeout = int(main_gw.ids.get("session_timeout_s") or 900)

        def probe(phase: str) -> dict:
            out: dict = {}
            if "mcp" in live:
                out["mcp"] = call_mcp(fc, store, gw_url, run_id, phase, session_timeout)
                print(f"    {phase:12s} mcp        -> {out['mcp']['outcome']}")
            if "inference" in live:
                # The prompt text is the only thing that varies between phases, so a byte-identical
                # pair of RESPONSES cannot be explained by having sent identical requests.
                body = json.dumps({
                    "model": args.inference_model, "max_tokens": 16,
                    "messages": [{"role": "user", "content": f"GRX {CASE} {phase}"}],
                }).encode()
                raw = signed_post(pool, creds, args.region, f"{base}{INFERENCE_PATH}", body,
                                  args.read_timeout)
                raw["classification"] = classify_inference(raw)
                raw["path"] = INFERENCE_PATH
                raw["model"] = args.inference_model
                out["inference"] = raw
                print(f"    {phase:12s} inference  -> {raw['classification']} "
                      f"(HTTP {raw.get('status', raw.get('transport_error'))})")
            return out

        print("  baseline (no policy on the engine):")
        payload["baseline"] = probe("baseline")

        # ---- 4. the ARN-scoped forbid, ACTIVE ---------------------------------
        stmt = C.statement("forbid", resource=C.gateway_resource(gw_arn))
        payload["forbid_statement"] = R.mask(stmt)
        payload["definition_member"] = C.GUARDRAILS_DEFINITION_MEMBER
        pol_name = T.check_name(ac, "CreatePolicy", f"grx_pol_f115_{run_id}".replace("-", "_")[:48])
        state.record(T.Resource(
            kind="policy", logical="f115_forbid", name=pol_name,
            service="bedrock-agentcore-control", delete_op="delete_policy",
            delete_params={"policyEngineId": engine_id, "policyId": ""},
            ids={"policy_engine_id": engine_id, "case": CASE}, delete_priority=40,
            notes=f"{CASE} ARN-scoped forbid, enforcementMode ACTIVE. Policies are untaggable, so "
                  f"this ledger entry is the only way to find it after a kill. It denies every "
                  f"action on ONE disposable gateway; if that gateway is gone it is inert, but "
                  f"delete it anyway."))
        state.write()

        A.limiter().wait("CreatePolicy")
        prec = capture(store, "create_policy", ac, name=pol_name,
                       definition=C.policy_definition(stmt),
                       description=f"GRX {CASE} gateway-scoped forbid"[:200],
                       validationMode="IGNORE_ALL_FINDINGS", enforcementMode="ACTIVE",
                       policyEngineId=engine_id)
        payload["forbid_created"] = bool(prec.ok)
        if not prec.ok:
            payload["forbid_error"] = {"code": prec.error_code or prec.error_class,
                                       "message": R.mask(str(prec.error_message))}
            print(f"  forbid REFUSED: {payload['forbid_error']['code']}: "
                  f"{str(payload['forbid_error']['message'])[:200]}")
            return _emit_inconclusive(
                payload, store,
                f"the gateway-scoped forbid could not be created "
                f"({payload['forbid_error']['code']}), so no target type was observed under a live "
                f"policy and evaluation was not measured on any of them")
        policy_id = prec.response["policyId"]
        state.record(T.Resource(
            kind="policy", logical="f115_forbid", name=pol_name,
            service="bedrock-agentcore-control", delete_op="delete_policy",
            delete_params={"policyEngineId": engine_id, "policyId": policy_id},
            ids={"policy_engine_id": engine_id, "policy_id": policy_id, "case": CASE},
            delete_priority=40, notes=f"{CASE} ARN-scoped forbid, ACTIVE."))
        state.write()

        pst, psecs, pgot = wait_policy(ac, engine_id, policy_id)
        payload["forbid_status"] = {"status": pst, "seconds_to_terminal": psecs,
                                    "reasons": R.mask(pgot.get("statusReasons") or [])}
        print(f"  forbid {policy_id}: {pst} after {psecs}s")
        if pst != "ACTIVE":
            return _emit_inconclusive(
                payload, store,
                f"the gateway-scoped forbid settled {pst} rather than ACTIVE, so the post-policy "
                f"calls would have been made with no policy in force and could not distinguish "
                f"evaluation from its absence")

        time.sleep(POLICY_SETTLE_S)
        payload["policy_settle_seconds"] = POLICY_SETTLE_S

        # ---- 5. the same calls, under the forbid ------------------------------
        print("  under the forbid:")
        payload["under_forbid"] = probe("under_forbid")

        return _decide(payload, store)

    finally:
        # Policy first: it is the only resource here that could affect anything outside this run,
        # and it is the one a kill leaves hardest to find.
        if policy_id:
            A.limiter().wait("DeletePolicy")
            d = capture(store, "delete_policy", ac, policyEngineId=engine_id, policyId=policy_id)
            print(f"  teardown forbid: {'ok' if d.ok else d.error_code}")
            if d.ok:
                state.drop("policy", "f115_forbid")
                state.write()
        for label, tid in reversed(created):
            A.limiter().wait("DeleteGatewayTarget")
            d = capture(store, "delete_gateway_target", ac, gatewayIdentifier=gid, targetId=tid)
            print(f"  teardown target {label}: {'ok' if d.ok else d.error_code}")
        # Retried: the diagnostic measured every target delete returning ok, an EMPTY
        # list_gateway_targets, and delete_gateway still failing ValidationException because the
        # target deletions had not finished propagating service-side. A retry 15 s later worked.
        for attempt in range(1, DELETE_ATTEMPTS + 1):
            if not gid:
                break
            A.limiter().wait("DeleteGateway")
            d = capture(store, "delete_gateway", ac, gatewayIdentifier=gid)
            if d.ok:
                print(f"  teardown gateway {gid}: ok (attempt {attempt})")
                state.drop("gateway", "f115")
                state.write()
                break
            print(f"  teardown gateway {gid}: {d.error_code} (attempt {attempt}"
                  f"{'; retrying' if attempt < DELETE_ATTEMPTS else '; GIVING UP — LEAKED'})")
            if attempt < DELETE_ATTEMPTS:
                time.sleep(DELETE_BACKOFF_S)


def _per_type_verdicts(payload: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Per target type: `evaluated`, `bypassed`, `unconstructible`, `not_eligible`, `unknown`.

    Returns the labels and, beside each, the sentence that justifies it — because the first version
    of this function returned a bare `bypassed` for the inference arm and that one word became a
    published FALSE. A label a reader cannot audit is how that happened.

    Two rules, both learned from that run:

    **A bypass requires an ELIGIBLE baseline.** The observation must show the request travelling far
    enough that a policy denial would have had to intervene to stop it: an MCP call that returned
    `allowed`, or an inference request that reached the provider or got a 2xx. The old version
    accepted `routed`, a bucket that included the gateway's own input-validation rejection, so a
    request refused at the front door in BOTH phases scored as a bypass. It had proven only that the
    surface rejects malformed bodies consistently.

    **Identical responses in both phases are RECORDED but do not veto.** An earlier draft of this
    function treated a byte-identical pair as disqualifying, on the reasoning that it is the signature
    of a response produced upstream of anything the policy could change. Round 2 of
    `f1_config/diag_inference_body.py` showed why that veto had to go: with a routable target, the
    inference arm gets HTTP 200 carrying
    `{"Output":{"__type":"com.amazon.coral.service#UnknownOperationException"},"Version":"1.0"}` —
    bedrock-runtime's own Coral front end saying it does not serve `/v1/messages`. That body is
    DETERMINISTIC and does not echo the prompt, so if the gateway forwards in both phases the two
    responses are necessarily identical. Vetoing on that would have suppressed exactly the finding
    the case exists to detect: a target type that forwards to its provider while a `forbid` scoped to
    its gateway is ACTIVE.

    The eligibility rule already does the work the veto was added for. Round 1's bad pair was a
    `front_door_reject`, which eligibility now excludes on its own. So identical-ness is reported in
    the justification and left to the reader, which is the right division of labour: it is a fact
    about the observation, not a defect in it.

    `not_eligible` is a first-class outcome, distinct from `unknown`: it means the instrument never
    got a question to the engine on this target type, which is a fact about this producer rather than
    about the service, and it is what must be reported instead of a bypass.
    """
    out: dict[str, str] = {}
    why: dict[str, str] = {}
    for label in ("mcp", "http_runtime", "inference"):
        arm = payload["arms"].get(label) or {}
        if not arm.get("constructible") or arm.get("status") != "READY":
            out[label] = "unconstructible"
            why[label] = (f"the target could not be created: "
                          f"{arm.get('error_code') or arm.get('status') or 'no attempt recorded'}")
            continue
        before = (payload.get("baseline") or {}).get(label) or {}
        after = (payload.get("under_forbid") or {}).get(label) or {}

        if label == "mcp":
            eligible = before.get("outcome") == "allowed"
            denied = after.get("outcome") == "policy_denied"
            # The tool-list channel. A listing that SUCCEEDS and comes back empty, against a
            # baseline that advertised the tool, is the engine mediating this target type: the
            # policy changed what the gateway was willing to disclose.
            filtered = (bool(before.get("listed")) and not after.get("listed")
                        and after.get("list_outcome") == "allowed")
            still_ran = after.get("outcome") == "allowed"
            same = (before.get("text_head") is not None
                    and before.get("text_head") == after.get("text_head"))
        else:
            eligible = before.get("classification") in ("allowed", "provider_reached")
            denied = after.get("classification") == "policy_denied"
            filtered = False
            still_ran = after.get("classification") in ("allowed", "provider_reached")
            same = (before.get("body_head") is not None
                    and before.get("body_head") == after.get("body_head"))

        if denied:
            out[label] = "evaluated"
            why[label] = "the call was denied by policy under a live forbid and allowed without it"
        elif filtered:
            out[label] = "evaluated"
            why[label] = (f"tools/list succeeded under the forbid and returned "
                          f"{len(after.get('advertised') or [])} tools against "
                          f"{len(before.get('advertised') or [])} in the baseline, so the engine "
                          f"filtered this target's tools rather than failing the request")
        elif not eligible:
            out[label] = "not_eligible"
            why[label] = (
                f"the baseline never reached the engine (baseline "
                f"{before.get('classification') or before.get('outcome') or 'no observation'}), so "
                f"neither phase asked a question policy could answer; this is a limit of the "
                f"instrument, not an observation about the service")
        elif still_ran:
            out[label] = "bypassed"
            why[label] = (
                "the baseline crossed the gateway and the same call crossed it again, unchanged, "
                "under a forbid that was ACTIVE and scoped to this gateway's ARN"
                + (" (the two responses are byte-identical, which is expected here: the upstream "
                   "error body is deterministic and does not echo the request)" if same else ""))
        else:
            out[label] = "unknown"
            why[label] = (f"baseline {before.get('classification') or before.get('outcome')}, "
                          f"under forbid {after.get('classification') or after.get('outcome')}: "
                          f"neither a denial nor a demonstrated pass-through")
    return out, why


def _decide(payload: dict, store: EvidenceStore) -> int:
    per_type, why = _per_type_verdicts(payload)
    payload["per_type"] = per_type
    payload["per_type_reason"] = why
    print("\n  per target type:")
    for k, v in per_type.items():
        print(f"    {k:14s} {v:18s} {why[k]}")

    bypassed = [k for k, v in per_type.items() if v == "bypassed"]
    if bypassed:
        # The one path to a decidable verdict short of all three evaluating: "FALSE if ANY target
        # type bypasses policy evaluation" is an existential, so one witness settles it and the
        # unconstructible arm stops mattering.
        #
        # Reaching this branch on the strength of an ineligible baseline is what happened on
        # 2026-08-14, so `_per_type_verdicts` now requires the baseline to have reached the engine
        # and the two responses to differ. A FALSE here is a published finding that AgentCore fails
        # to evaluate policy on a target type, which is a security claim about someone else's
        # product; the bar for it is a demonstrated pass-through, not an unexplained pair.
        obs = P.obs_existence(CASE, False, n=len(per_type), per_type=per_type,
                              per_type_reason=why, bypassed=bypassed, **_detail(payload))
        record = O.evaluate(obs)
        P.emit(CASE, record, payload, store)
        print(f"  {CASE}: {record.get('verdict')} — {bypassed} carried traffic under a live forbid")
        return 0

    evaluated = [k for k, v in per_type.items() if v == "evaluated"]
    unconstructible = [k for k, v in per_type.items() if v == "unconstructible"]
    not_eligible = [k for k, v in per_type.items() if v == "not_eligible"]
    if len(evaluated) == 3:
        obs = P.obs_existence(CASE, True, n=3, per_type=per_type, per_type_reason=why,
                              **_detail(payload))
        record = O.evaluate(obs)
        P.emit(CASE, record, payload, store)
        print(f"  {CASE}: {record.get('verdict')} — all three target types evaluated")
        return 0

    reason = (
        "the oracle quantifies over three target types and one of them cannot be built at this API "
        "version: CreateGatewayTarget refuses every `http.*` configuration on a gateway whose "
        "protocolType is MCP, and MCP is the only member of CreateGateway's protocolType enum. "
        f"Evaluated on {evaluated or 'none'}; unconstructible: {unconstructible or 'none'}; "
        f"not eligible to be interpreted: {not_eligible or 'none'}. Not FALSE — a target type that "
        "cannot carry a request cannot bypass evaluation of one, and an arm whose baseline never "
        "reached the engine witnesses nothing; not TRUE — that is not the conjunction the seal "
        "names, and reading `all three` as `all that exist` would decide a different quantity.")
    if not_eligible:
        reason += (
            " The not-eligible arms are a limit of this instrument rather than a property of the "
            "service, and they are reported as such so that no later reader mistakes them for a "
            "measured pass-through.")
    return _emit_inconclusive(payload, store, reason)


def _detail(payload: dict) -> dict:
    """The fields every verdict shape carries, so a reader of the record needs no second file."""
    return {"claim": payload.get("claim"),
            "protocol_type_enum": payload.get("gateway_protocol_type_enum"),
            "forbid_statement": payload.get("forbid_statement"),
            "forbid_status": (payload.get("forbid_status") or {}).get("status"),
            "inference_path": INFERENCE_PATH,
            "inference_model": payload.get("inference_model")}


def _emit_inconclusive(payload: dict, store: EvidenceStore, reason: str) -> int:
    payload["ended_utc"] = _now_iso()
    payload["inconclusive_reason"] = reason
    record = O.not_measured(CASE, reason, per_type=payload.get("per_type"),
                            per_type_reason=payload.get("per_type_reason"), **_detail(payload))
    P.emit(CASE, record, payload, store)
    print(f"\n  {CASE}: {record.get('verdict')}")
    print(f"  reason: {reason}")
    print("  INCONCLUSIVE is not FALSE and licenses no amendment to the document.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
