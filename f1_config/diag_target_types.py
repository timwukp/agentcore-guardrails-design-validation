"""DIAGNOSTIC (not a registered case): do `http.*` and `inference.*` gateway targets exist here?

Why this exists
---------------
F1-15's sealed oracle is an EXISTENCE binding: "TRUE if a policy engine attaches and evaluates on
all three target types; FALSE if any target type bypasses policy evaluation." The three types come
from claim `C-s4-1-bullet-007`, which names them by wire surface — MCP targets (`POST /mcp`,
JSON-RPC `tools/call`), HTTP runtime targets (`POST /<target>/invocations`), and HTTP inference
targets (`POST /inference`) — and `CreateGatewayTarget`'s `targetConfiguration` union has exactly
three arms matching them: `mcp`, `http`, `inference`.

One of those three has ever been built in this repo. `mcp.lambda` is `grxecho`, created by
`infra/05_target.py` on both halves of the F6 pair. `http.agentcoreRuntime` and
`inference.provider` have **zero** call sites and zero appearances anywhere in `evidence/`, so
before a producer is written around them, three things are unknown and each one can invalidate the
whole design:

  U1  Does `CreateGatewayTarget` accept a `http.*` or `inference.*` arm AT ALL on a gateway whose
      `protocolType` is `MCP`? Every gateway in this account is MCP, because that is what
      `infra/04_gateway.py` creates, and `protocolType` is not a member of `UpdateGateway`'s input
      the way an afterthought would be. If the arms are refused on an MCP gateway then F1-15 is a
      question about a gateway this testbed does not have, which is a different finding than
      either verdict the seal names.

  U2  What are the invocation paths, really? The claim asserts `/<target>/invocations` and
      `/inference`. `gateway_url` in the ledger is the `/mcp` URL, and no list or get operation
      returns any other path, so the claim's two paths are the claim's assertion and not something
      read off the service. A producer that POSTs to a path the gateway does not serve measures
      404s and calls them bypasses.

  U3  Is the `inference` arm's `endpoint` allowed to be any HTTPS URL, or must it be a provider the
      service recognises? The shape says `pattern=https://[a-zA-Z0-9\\-\\.]+(:[0-9]{1,5})?(/.*)?`
      and nothing more, but a pattern is a syntax check and the service may resolve the host.

Why a nonexistent Runtime ARN is the right probe for U1
-------------------------------------------------------
`http.agentcoreRuntime` requires a live `arn`, and building one costs a role, a zip, an upload and
a ~10 s create (`f5_redteam/11_route_credential_reachability.py` does all of it). Doing that work
first and THEN discovering the arm is refused on an MCP gateway would be paying for the answer in
the wrong order. So this probe sends an ARN that matches the shape's pattern exactly and names a
runtime that does not exist, and reads the FAILURE MODE rather than the success:

    "no such runtime" / ResourceNotFound  ->  the arm is accepted, U1 is answered YES, and the
                                              producer's only remaining cost is a real runtime
    ValidationException naming the arm,
    the protocol or the target type      ->  the arm is refused, U1 is answered NO, and no runtime
                                              needed to be built to learn it

The distinction is in the message, so the message is recorded verbatim rather than a boolean.

What this script may and may not do
-----------------------------------
It writes NO verdict and touches no `results/phase1/` file. Its output is an observation for the
F1-15 producer's design and for the FINDING document, nothing more.

It runs on a DISPOSABLE gateway and never on `main`. Two independent reasons, and the second is the
one that would not be obvious:

  * `main` is the ENFORCE half of the pair `nopolicy` is the latency baseline for. Extra targets on
    it advertise extra tools in `tools/list`, and while nothing in the tree asserts `main`'s target
    COUNT (checked: `list_gateway_targets` has exactly one call site, `infra/05_target.py:121`,
    which searches by name), a probe that leaves residue there contaminates a shared instrument
    mid-flight for every later F4/F6 run.
  * A probe is allowed to fail in ways a case is not. If this script is killed between a create and
    its delete, a disposable gateway is deleted by a teardown sweep on the RunId tag and nothing
    else notices; the same residue on `main` is a config difference in the F6 pair.

The disposable gateway is cloned from `main`'s live `GetGateway` response through
`CreateGateway`'s own input shape — the recipe at `f5_redteam/02_route3_updategateway.py:865-873` —
so it carries the same `policyEngineConfiguration`, the same authorizer and the same protocol.
Cloning rather than re-deriving matters here: the question is whether the arms work on the gateway
configuration this project actually validates, and a hand-built gateway that differed in one member
would answer it about a configuration nobody has.

Nothing here creates a policy. Whether the engine EVALUATES on each type is F1-15's measurement and
is deliberately out of scope; this script only asks whether the targets can be created and reached.
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
import redact as R                                                   # noqa: E402
import testbed as T                                                  # noqa: E402
from botocore.auth import SigV4Auth                                  # noqa: E402
from botocore.awsrequest import AWSRequest                           # noqa: E402
from evidence import EvidenceStore, capture                          # noqa: E402

import urllib3                                                       # noqa: E402

FAMILY = "f1_config"
LABEL = "DIAG-target-types"

SIGNING_SERVICE = "bedrock-agentcore"

# The endpoint for the `inference` arm. Bedrock's own runtime host is the honest choice available
# without standing up a server: it is a real HTTPS inference endpoint in this Region, it satisfies
# the shape's pattern, and if the service resolves the host at create time it will resolve. What it
# is NOT is a provider that will answer a gateway-forwarded request correctly — and that is fine
# for this probe, whose question is create-time acceptance and path existence. A 4xx from the
# provider is still proof the gateway routed somewhere.
INFERENCE_ENDPOINT = "https://bedrock-runtime.us-east-1.amazonaws.com"

# A syntactically perfect ARN for a runtime that does not exist. The suffix is 10 characters from
# the shape's own `[a-zA-Z0-9]{10}` class; the stem obeys `[a-zA-Z][a-zA-Z0-9_]{0,47}` and so
# carries an underscore, because AgentCore Runtime names cannot contain a hyphen while every
# prefix-bound IAM scope in this project is `grx-`.
FAKE_RUNTIME_STEM = "grx_f115probe_absent"
FAKE_RUNTIME_SUFFIX = "zzzzzzzzzz"

POLL_SECONDS = 5
POLL_TIMEOUT = 300
# Teardown retries. See the `finally` block for the measurement that set these.
DELETE_ATTEMPTS = 4
DELETE_BACKOFF_S = 15
TERMINAL_GW = {"READY", "FAILED", "CREATE_FAILED", "UPDATE_FAILED"}
# From infra/05_target.py:67-73. `*_PENDING_AUTH` is terminal FOR US: it means the credential
# provider is misconfigured, and treating it as non-terminal turns a fast diagnosis into a 300 s
# hang.
TERMINAL_TGT = {"READY", "FAILED", "CREATE_FAILED", "UPDATE_FAILED",
                "CREATE_PENDING_AUTH", "UPDATE_PENDING_AUTH", "SYNCHRONIZE_PENDING_AUTH"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fake_runtime_arn(region: str, account: str) -> str:
    return (f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/"
            f"{FAKE_RUNTIME_STEM}-{FAKE_RUNTIME_SUFFIX}")


def arms(region: str, account: str, lambda_arn: str, tool_schema: list[dict]) -> list[dict]:
    """One entry per `targetConfiguration` union arm the claim names.

    The `mcp.lambda` arm is a POSITIVE CONTROL and is not here for its own sake: it is the shape
    `infra/05_target.py` has created successfully on this exact gateway configuration. If it fails
    on the disposable clone then the clone is not equivalent to `main` and nothing the other two
    arms report can be attributed to the arms.
    """
    return [
        {
            "label": "mcp_lambda",
            "claim_surface": "MCP target: POST /mcp, JSON-RPC tools/call",
            "expect": "ACCEPTED — positive control, the shape infra/05_target.py already creates",
            "config": {"mcp": {"lambda": {"lambdaArn": lambda_arn,
                                          "toolSchema": {"inlinePayload": tool_schema}}}},
            "credentials": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        },
        {
            "label": "http_agentcore_runtime",
            "claim_surface": "HTTP runtime target: POST /<target>/invocations",
            "expect": ("either a not-found on the ARN (arm accepted) or a validation error naming "
                       "the arm/protocol (arm refused) — the message decides U1"),
            "config": {"http": {"agentcoreRuntime": {"arn": fake_runtime_arn(region, account)}}},
            "credentials": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        },
        {
            "label": "inference_provider",
            "claim_surface": "HTTP inference target: POST /inference",
            "expect": "unknown; U3 asks whether any pattern-valid HTTPS endpoint is accepted",
            "config": {"inference": {"provider": {"endpoint": INFERENCE_ENDPOINT}}},
            "credentials": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        },
    ]


def candidate_paths(target_names: dict[str, str]) -> list[dict[str, str]]:
    """The wire surfaces to probe, and which claim sentence each one is testing.

    `/mcp` is included even though it is known to work, for the same reason the `mcp.lambda` arm is:
    a path probe whose control is untested cannot distinguish "this path does not exist" from "this
    signer is wrong".
    """
    out = [{"label": "mcp", "path": "/mcp",
            "why": "control: the path the ledger's gateway_url already carries"}]
    tn = target_names.get("http_agentcore_runtime")
    if tn:
        out.append({"label": "runtime_invocations", "path": f"/{tn}/invocations",
                    "why": "the claim's HTTP-runtime surface, with the created target's name"})
    if target_names.get("inference_provider"):
        out += [
            {"label": "inference", "path": "/inference",
             "why": "the claim's inference surface, verbatim"},
            # The shape's own `operations[].path` examples are `/v1/messages` and `/v1/responses`,
            # which is evidence the inference surface may be pathed per operation rather than at a
            # single `/inference`. Probed because a 404 on `/inference` alone would otherwise be
            # read as "the surface does not exist" when it may only be spelled differently.
            {"label": "inference_v1_messages", "path": "/inference/v1/messages",
             "why": "the shape's own operations[].path example, in case /inference is a prefix"},
            {"label": "v1_messages", "path": "/v1/messages",
             "why": "the same example at the root, in case the gateway serves it unprefixed"},
        ]
    return out


def signed_post(pool, creds, region: str, url: str, body: bytes,
                timeout_s: float) -> dict:
    """One SigV4-signed POST, reported as data rather than raised.

    Every outcome here is an observation — a 404 answers U2 as informatively as a 200 — so a
    transport failure is captured in the same shape as a response and never propagated. `connection`
    is kept out of the signed headers for the reason `lib/mcp.py:483-489` gives.
    """
    h = {"content-type": "application/json", "accept": "application/json"}
    frozen = creds.get_frozen_credentials() if hasattr(creds, "get_frozen_credentials") else creds
    req = AWSRequest(method="POST", url=url, data=body, headers=h)
    SigV4Auth(frozen, SIGNING_SERVICE, region).add_auth(req)
    started = time.time()
    try:
        resp = pool.request("POST", url, body=body, headers=dict(req.headers),
                            redirect=False, timeout=urllib3.Timeout(connect=10, read=timeout_s))
    except Exception as exc:                                          # noqa: BLE001
        return {"transport_error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - started, 3)}
    raw = resp.data.decode("utf-8", "replace")
    return {"status": resp.status,
            # Truncated because a provider error page can be kilobytes of HTML and the informative
            # part is always at the front. The full body is in the evidence store's own record only
            # for calls that went through `capture`; these do not, so the cap is the record.
            "body_head": R.mask(raw[:1200]),
            "body_bytes": len(resp.data),
            "elapsed_s": round(time.time() - started, 3)}


def wait_gateway(ac, gid: str) -> tuple[str, float]:
    started = time.time()
    while True:
        got = ac.get_gateway(gatewayIdentifier=gid)
        st = got.get("status", "")
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--state")
    ap.add_argument("--evidence-root")
    ap.add_argument("--read-timeout", type=float, default=30.0)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the three arms and the candidate paths, call nothing")
    args = ap.parse_args()

    state = T.State.load(Path(args.state) if args.state else None)
    run_id = state.run_id
    if state.region != args.region:
        raise SystemExit(f"ledger is for {state.region}, not {args.region}")

    if args.dry_run:
        print(json.dumps({"arms": [{k: v for k, v in a.items() if k != "credentials"}
                                   for a in arms(args.region, "111122223333",
                                                 "arn:aws:lambda:us-east-1:111122223333:"
                                                 "function:grx-echo", [{"name": "echo"}])],
                          "candidate_paths": candidate_paths(
                              {"http_agentcore_runtime": "grxrt",
                               "inference_provider": "grxinf"})}, indent=2))
        return 0

    store = EvidenceStore(run_id, FAMILY, LABEL,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    fc = A.factory(args.region)
    account = A.account_id(fc)
    ac = fc.client("bedrock-agentcore-control")

    main_gw = state.get("gateway", "main")
    echo_tgt = state.get("gateway-target", "main")
    lam = state.get("lambda", "echo")
    lambda_arn = T.unmask_arn(lam.arn, account)
    tool_schema = list(echo_tgt.ids.get("tool_schema") or [])
    if not tool_schema:
        # The ledger stores tool NAMES, not the schema. Rebuilt from the module that is the
        # authority for it, so the control arm sends the same inlinePayload infra/05_target.py did
        # rather than an approximation of it.
        sys.path.insert(0, str(ROOT / "infra"))
        import echo_handler                                           # noqa: E402
        tool_schema = list(echo_handler.TOOL_SCHEMA)

    report: dict = {
        "label": LABEL, "run_id": run_id, "region": args.region,
        "started_utc": _now_iso(),
        "questions": {
            "U1": "does CreateGatewayTarget accept http.* / inference.* on an MCP gateway",
            "U2": "which invocation paths does the gateway actually serve",
            "U3": "does inference.provider.endpoint accept any pattern-valid HTTPS URL",
        },
        "fake_runtime_arn": R.mask(fake_runtime_arn(args.region, account)),
        "inference_endpoint": INFERENCE_ENDPOINT,
        "cloned_from": {"logical": "main", "gateway_id": main_gw.ids["gateway_id"]},
        "arms": [], "paths": [], "notes": [],
    }

    gid = ""
    created: list[tuple[str, str]] = []          # (label, targetId), for teardown
    target_names: dict[str, str] = {}

    try:
        # ---- 1. the disposable clone -----------------------------------------
        live = ac.get_gateway(gatewayIdentifier=main_gw.ids["gateway_id"])
        create_allowed = frozenset(
            ac.meta.service_model.operation_model("CreateGateway").input_shape.members)
        name = T.check_name(ac, "CreateGateway", f"grx-gw-f115probe-{run_id}"[:48])
        kw = {k: copy.deepcopy(v) for k, v in live.items() if k in create_allowed}
        kw["name"] = name
        kw["description"] = (f"{LABEL} disposable clone of gateway/main: probes whether http.* and "
                             f"inference.* target arms are accepted. Delete on sight.")[:200]
        kw["tags"] = A.tags_for(run_id, state.expires_at)

        report["clone_members"] = sorted(kw)
        report["clone_has_policy_engine"] = "policyEngineConfiguration" in kw
        if not report["clone_has_policy_engine"]:
            # Not fatal for THIS script — it asks about target creation, not evaluation — but it
            # would be fatal for the F1-15 producer built on this recipe, so it is recorded loudly
            # rather than discovered again there.
            report["notes"].append(
                "the clone carries NO policyEngineConfiguration, so CreateGateway does not echo "
                "the member GetGateway returns; the F1-15 producer must set it explicitly from "
                "the ledger's policy-engine id instead of relying on the clone")

        # Ledger FIRST, then create: the window between a successful create and a recorded create
        # is the window in which a kill leaves an untracked gateway.
        state.record(T.Resource(
            kind="gateway", logical="f115probe", name=name,
            service="bedrock-agentcore-control",
            delete_op="delete_gateway", delete_params={"gatewayIdentifier": name},
            ids={"gateway_id": "", "case": LABEL}, delete_priority=30,
            notes=f"{LABEL} disposable probe gateway. If this is still here the run did not reach "
                  f"its teardown; deleting it affects no verdict."))
        state.write()

        A.limiter().wait("CreateGateway")
        made = capture(store, "create_gateway", ac, **kw).raise_for_status()
        gid = made.response["gatewayId"]
        gw_url = made.response.get("gatewayUrl", "")
        state.record(T.Resource(
            kind="gateway", logical="f115probe", name=name,
            service="bedrock-agentcore-control",
            delete_op="delete_gateway", delete_params={"gatewayIdentifier": gid},
            ids={"gateway_id": gid, "gateway_url": gw_url, "case": LABEL},
            arn=made.response.get("gatewayArn", ""), delete_priority=30,
            notes=f"{LABEL} disposable probe gateway."))
        state.write()

        st, secs = wait_gateway(ac, gid)
        report["gateway"] = {"id": gid, "status": st, "seconds_to_terminal": secs,
                             "url": R.mask(gw_url)}
        print(f"  gateway {gid}: {st} after {secs}s")
        if st != "READY":
            report["notes"].append(f"the clone settled {st}, so no arm below is interpretable")
            return _finish(report, store)

        base = gw_url.rsplit("/mcp", 1)[0] if gw_url.endswith("/mcp") else gw_url.rstrip("/")
        report["gateway"]["base_url_derived"] = R.mask(base)
        report["gateway"]["url_ended_with_mcp"] = gw_url.endswith("/mcp")

        # ---- 2. one create per union arm -------------------------------------
        for arm in arms(args.region, account, lambda_arn, tool_schema):
            label = arm["label"]
            tname = f"grx{label.replace('_', '')}"[:40]     # no underscore: Cedar action prefix
            row = {"label": label, "claim_surface": arm["claim_surface"],
                   "expect": arm["expect"], "target_name": tname,
                   "config": R.mask(arm["config"])}
            A.limiter().wait("CreateGatewayTarget")
            rec = capture(store, "create_gateway_target", ac,
                          gatewayIdentifier=gid, name=tname,
                          description=f"{LABEL} {label} probe"[:200],
                          targetConfiguration=arm["config"],
                          credentialProviderConfigurations=arm["credentials"])
            row["create_ok"] = bool(rec.ok)
            if rec.ok:
                tid = rec.response["targetId"]
                created.append((label, tid))
                target_names[label] = tname
                tst, tsecs, got = wait_target(ac, gid, tid)
                row.update({"target_id": tid, "status": tst, "seconds_to_terminal": tsecs,
                            "status_reasons": got.get("statusReasons") or []})
                print(f"  arm {label:24s} CREATED -> {tst} after {tsecs}s")
            else:
                row.update({"error_code": rec.error_code or rec.error_class,
                            "error_message": R.mask(str(rec.error_message))})
                print(f"  arm {label:24s} REFUSED: {row['error_code']}: "
                      f"{row['error_message'][:160]}")
            report["arms"].append(row)

        # ---- 3. which paths does it serve ------------------------------------
        # A minimal JSON-RPC body for every path. Deliberately the SAME body everywhere: the
        # question is which paths exist, and a per-path body would confound "this path is absent"
        # with "this path rejected this payload".
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                           "params": {}}).encode()
        pool = urllib3.PoolManager(retries=False)
        # Through the factory, not boto3 directly: the factory may hold an assumed
        # `grx-caller` session, and that is the identity Cedar sees as the principal
        # (lib/mcp.py:814-821). `session` is a method on ClientFactory, not a property.
        creds = fc.session().get_credentials()
        for cand in candidate_paths(target_names):
            url = f"{base}{cand['path']}"
            out = signed_post(pool, creds, args.region, url, body, args.read_timeout)
            report["paths"].append({**cand, "url": R.mask(url), **out})
            shown = out.get("status", out.get("transport_error"))
            print(f"  path {cand['label']:24s} {cand['path']:28s} -> {shown}")

        return _finish(report, store)

    finally:
        # Targets before the gateway (a gateway with targets cannot be deleted), and each delete
        # captured so a refusal is evidence rather than a message on a terminal nobody kept.
        for label, tid in reversed(created):
            A.limiter().wait("DeleteGatewayTarget")
            d = capture(store, "delete_gateway_target", ac,
                        gatewayIdentifier=gid, targetId=tid)
            print(f"  teardown target {label}: {'ok' if d.ok else d.error_code}")
        # Retried, because the first run of this script measured the failure it protects against:
        # every `delete_gateway_target` returned ok and `delete_gateway` then came back
        # `ValidationException`, leaving a READY gateway standing. `list_gateway_targets` on it
        # returned an EMPTY list at the same moment, so the targets were gone from the caller's view
        # and the gateway still refused to be deleted — the target deletions had not finished
        # propagating on the service side. A bare retry 15 s later succeeded.
        #
        # The retry is here rather than in a caller because a leaked gateway is not inert: it holds a
        # `policyEngineConfiguration` pointing at the shared engine, and it bills. A `finally` that
        # gives up after one attempt turns a propagation delay into residue somebody has to find.
        for attempt in range(1, DELETE_ATTEMPTS + 1):
            if not gid:
                break
            A.limiter().wait("DeleteGateway")
            d = capture(store, "delete_gateway", ac, gatewayIdentifier=gid)
            if d.ok:
                print(f"  teardown gateway {gid}: ok (attempt {attempt})")
                state.drop("gateway", "f115probe")
                state.write()
                break
            print(f"  teardown gateway {gid}: {d.error_code} (attempt {attempt}"
                  f"{'; retrying' if attempt < DELETE_ATTEMPTS else '; GIVING UP — LEAKED'})")
            if attempt < DELETE_ATTEMPTS:
                time.sleep(DELETE_BACKOFF_S)


def _finish(report: dict, store: EvidenceStore) -> int:
    report["ended_utc"] = _now_iso()
    out = ROOT / "results" / f"{LABEL}-{_now_stamp()}.json"
    # Masked, because `results/` is the distributable tree and this report carries gateway ids and
    # target ARNs read straight off live responses. It was the THIRTEENTH unmasked `results/` write
    # in the repo and `lib/tests/test_results_writes_are_masked.py` failed on it, which is exactly
    # the arrival that test exists to catch. Masked rather than added to that file's WAIVED
    # inventory: the argument for waiving the original twelve was that masking five other families'
    # working scripts is a real change for a latent risk, and none of that applies to a write added
    # by this project's own diagnostic.
    out.write_text(R.mask_text(json.dumps(report, indent=2, sort_keys=True) + "\n"))
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
