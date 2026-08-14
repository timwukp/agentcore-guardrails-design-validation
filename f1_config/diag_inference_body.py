"""Which request body does the inference target surface actually accept?

Why this exists
---------------
The first F1-15 run (2026-08-14) produced a FALSE verdict that was wrong, and the reason is worth
recording precisely because the failure looked like a result.

The inference arm was invoked before and after a live `forbid`. Both times it answered HTTP 400 with
a byte-identical 107-byte body:

    {"error":{"type":"invalid_request_error","message":"Model ID contains invalid characters."}}

in 38 ms and 59 ms. The producer's classifier read "an error naming a model field" as `routed` —
the gateway forwarded rather than denied — and read "routed before AND after the forbid" as a
target type that bypasses policy evaluation, which is this case's FALSE condition. Published, that
would have been a claim that AgentCore fails to evaluate policy on inference targets.

It is nothing of the kind. The model id sent was `anthropic.claude-3-5-haiku-20241022-v1:0` and the
surface rejected it for its CHARACTERS — almost certainly the colon. A request refused on charset
validation is refused before anything evaluates it, so both observations are of traffic the policy
engine never saw. This is `f3_efficacy/08_score_label_join.py:425-448`'s DEV-P4-22 trap arriving on
a surface the producer had not thought to apply it to: it guarded the MCP arm against exactly this
(an unqualified tool name errors before policy evaluation) and then walked into it on the inference
arm. 38 ms is also far too fast to have crossed a policy engine and an upstream provider, which is
a second tell the classifier ignored.

So before F1-15 can be re-run, one factual question has to be answered by measurement rather than
by a second guess: what does a request body on `POST {base}/inference/v1/messages` have to look like
to get PAST validation? Only then does "the gateway did not deny it" mean anything, because only
then has the request been given the chance to be denied.

What is being varied, and why these candidates
----------------------------------------------
Only the model id, and one body-shape control. `CreateGatewayTarget`'s `inference.provider` shape
offers `modelMapping.providerPrefix{strip,separator}`, which tells us model ids are expected to
arrive with a provider prefix that the gateway may strip before forwarding — so the accepted form
is plausibly a bare Anthropic model name, a dotted Bedrock id without the version colon, or a
prefixed form the mapping is designed to split. The candidates cover:

  * the exact string that failed, as a NEGATIVE CONTROL. If it stops failing, something other than
    the model id was wrong and every conclusion below is void.
  * the same id with the `:0` version suffix removed, and with the colon replaced by a dot — the
    two minimal edits that test "the colon specifically".
  * a bare Anthropic-style name with no provider prefix at all.
  * the `us.` cross-Region inference prefix form, which is the id shape Bedrock itself now wants for
    several Anthropic models.
  * a deliberately absent `model` field, as a SECOND control. The probe that first found this
    surface got "Missing required field 'model'" — so if that message comes back here, the surface
    is still parsing bodies the same way it did then and this diagnostic is talking to the thing it
    thinks it is talking to.

Reading the results
-------------------
The success condition is NOT a 200. This gateway's `inference.provider` endpoint points at
`bedrock-runtime`, and whether that upstream answers a Messages-shaped POST from this caller is a
different question with its own credential and model-access conditions — F5-9 already established
that this account has a model gate. What is needed is a response that proves validation was passed
and the request was handled downstream of it: a 200, or an upstream error that is clearly the
PROVIDER's rather than the gateway's front-door charset check (an access-denied on a model, a
throttle, an unknown-model-id from Bedrock itself).

The distinction is the whole point, so the report records the full body for every candidate and
draws no automatic conclusion beyond a coarse bucket. A human reads it.

Cost and safety
---------------
One disposable gateway cloned from `main` (so it carries the same `policyEngineConfiguration`), one
inference target, N signed POSTs, then teardown with the retry the earlier diagnostic measured as
necessary. No policy is created — this asks nothing about enforcement. Nothing touches `main`.
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
LABEL = "DIAG-inference-body"
SIGNING_SERVICE = "bedrock-agentcore"
INFERENCE_ENDPOINT = "https://bedrock-runtime.us-east-1.amazonaws.com"
INFERENCE_PATH = "/inference/v1/messages"
TARGET_NAME = "grxinference"
POLL_SECONDS = 5
POLL_TIMEOUT = 300
DELETE_ATTEMPTS = 4
DELETE_BACKOFF_S = 15
TERMINAL_GW = {"READY", "FAILED", "CREATE_FAILED", "UPDATE_FAILED"}
TERMINAL_TGT = {"READY", "FAILED", "CREATE_FAILED", "UPDATE_FAILED",
                "CREATE_PENDING_AUTH", "UPDATE_PENDING_AUTH", "SYNCHRONIZE_PENDING_AUTH"}

# What round 1 established, since it decides the target configuration below
# -------------------------------------------------------------------------
# Round 1 created the target with `{"provider": {"endpoint": ...}}` and nothing else, and measured:
#
#   anthropic.claude-3-5-haiku-20241022-v1:0     400  Model ID contains invalid characters.
#   us.anthropic.claude-3-5-haiku-20241022-v1:0  400  Model ID contains invalid characters.
#   anthropic.claude-3-5-haiku-20241022-v1       404  Model '...' not found on any target.
#   anthropic.claude-3-5-haiku-20241022-v1.0     404  Model '...' not found on any target.
#   claude-3-5-haiku-20241022                    404  Model '...' not found on any target.
#   (model field absent)                         400  Missing required field 'model' in request body
#
# Two distinct walls, cleanly separated. The colon is a CHARSET violation: exactly the two ids
# containing `:` got the 400, and every colon-free id got past it. That is corroborated by the API
# shape rather than inferred from the pair — `operations[].models[].model` has pattern
# `[a-zA-Z0-9\-\._\*\?@]+(/...)*`, which admits `*` and `?` globs and not `:`. The Bedrock model id
# `...-v1:0` simply cannot be spelled in this field.
#
# The 404 is the second wall and the more informative one: "not found on any TARGET" is the
# gateway's own routing layer reporting that no inference target declares that model. A
# `provider` target with no `operations` advertises no models, so nothing could ever route to it.
# That is why round 1 found no eligible body: it was asking a target that could not serve anything.
#
# So round 2 declares an operation and a model glob, which is what makes the target routable.
TARGET_CONFIG = {"inference": {"provider": {
    "endpoint": INFERENCE_ENDPOINT,
    # `path` is the CLIENT-facing path, which the gateway serves under its `/inference` prefix —
    # matching the `/inference/v1/messages` that responded when `/inference` alone did not.
    "operations": [{"path": "/v1/messages",
                    "models": [{"model": "anthropic.claude-*"}, {"model": "claude-*"}]}],
}}}

# (label, model id or None to omit the field entirely)
CANDIDATES: list[tuple[str, str | None]] = [
    # Should now ROUTE: matches the `anthropic.claude-*` glob and contains no colon.
    ("glob_match_dotted", "anthropic.claude-3-5-haiku-20241022-v1"),
    # Should also route, via the second glob. Tests that prefix-free ids are servable, which decides
    # whether `modelMapping.providerPrefix.strip` is needed at all.
    ("glob_match_bare", "claude-3-5-haiku-20241022"),
    # Bedrock's real id for this model, minus the `:0` the charset forbids. If the gateway forwards
    # and Bedrock answers, this is the id that gets furthest.
    ("bedrock_id_no_colon", "anthropic.claude-3-5-haiku-20241022-v1.0"),
    # CONTROL 1: still colon-bearing. Must still be a `front_door_reject`. If this one suddenly
    # routes, the charset diagnosis is wrong and the conclusions above are void.
    ("colon_still_rejected", "anthropic.claude-3-5-haiku-20241022-v1:0"),
    # CONTROL 2: colon-free but matching neither glob. Must be `no_route`. This is what separates
    # "the target now serves models" from "the target now serves everything regardless of the
    # declaration" — without it, a routing success proves nothing about the models list.
    ("unmatched_model", "openai.gpt-4o-mini"),
    # CONTROL 3: the message round 1 got with no model field. Confirms this round is talking to the
    # same validator.
    ("model_field_absent", None),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def body_for(model: str | None) -> bytes:
    b: dict = {"max_tokens": 16, "messages": [{"role": "user", "content": "GRX F1-15 body probe"}]}
    if model is not None:
        b["model"] = model
    return json.dumps(b).encode()


def bucket(out: dict) -> str:
    """A coarse label. Deliberately coarse — the body is what gets read.

    `front_door_reject` and `no_route` are the ones that matter: both are the gateway's own handling
    of the request, before policy evaluation, so any F1-15 observation made through either is
    uninterpretable.

    Round 1 of this diagnostic (2026-08-14T06:09Z) read `out["body_head"]` while `signed_post` stores
    the key as `body`, so `text` was always empty and every candidate bucketed as `other`. That in
    turn tripped the negative-control check, which reported "NEGATIVE CONTROL BROKE" — a false alarm
    from this typo rather than a finding. The printed bodies were unaffected and carried the real
    result, which is the only reason the round was still usable, and a decent argument for printing
    raw responses next to every derived label.
    """
    if "transport_error" in out:
        return "transport_error"
    text = (out.get("body") or "").lower()
    status = out.get("status") or 0
    if 200 <= status < 300:
        return "ok"
    if "contains invalid characters" in text or "missing required field" in text:
        return "front_door_reject"
    # The gateway parsed the body, then could not map the model id onto any of its inference
    # targets' declared `operations[].models`. Its own routing layer, upstream of the provider.
    if "not found on any target" in text or "not_found_error" in text:
        return "no_route"
    if "is not supported for gateway protocol type" in text:
        return "protocol_reject"
    if any(k in text for k in ("accessdenied", "not authorized", "don't have access",
                               "throttl", "toomanyrequests", "on-demand throughput",
                               "isn't supported", "validationexception")):
        return "provider_reached"
    return "other"


def signed_post(pool, creds, region: str, url: str, body: bytes, timeout_s: float) -> dict:
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
    return {"status": resp.status, "body": R.mask(raw[:2000]), "body_bytes": len(resp.data),
            "elapsed_s": round(time.time() - started, 3),
            "request_id": resp.headers.get("x-amzn-requestid", "")}


def wait_gateway(ac, gid: str) -> tuple[str, float]:
    started = time.time()
    while True:
        st = ac.get_gateway(gatewayIdentifier=gid).get("status", "")
        if st in TERMINAL_GW or time.time() - started > POLL_TIMEOUT:
            return st, round(time.time() - started, 1)
        time.sleep(POLL_SECONDS)


def wait_target(ac, gid: str, tid: str) -> tuple[str, float]:
    started = time.time()
    while True:
        st = ac.get_gateway_target(gatewayIdentifier=gid, targetId=tid).get("status", "")
        if st in TERMINAL_TGT or time.time() - started > POLL_TIMEOUT:
            return st, round(time.time() - started, 1)
        time.sleep(POLL_SECONDS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--state")
    ap.add_argument("--evidence-root")
    ap.add_argument("--read-timeout", type=float, default=45.0)
    args = ap.parse_args()

    state = T.State.load(Path(args.state) if args.state else None)
    run_id = state.run_id
    store = EvidenceStore(run_id, FAMILY, LABEL,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    fc = A.factory(args.region)
    account = A.account_id(fc)
    ac = fc.client("bedrock-agentcore-control")
    main_gw = state.get("gateway", "main")

    report: dict = {"label": LABEL, "run_id": run_id, "region": args.region,
                    "started_utc": _now_iso(), "path": INFERENCE_PATH,
                    "endpoint": INFERENCE_ENDPOINT, "candidates": [], "notes": []}

    gid = ""
    tid = ""
    try:
        got_main = ac.get_gateway(gatewayIdentifier=main_gw.ids["gateway_id"])
        create_allowed = frozenset(
            ac.meta.service_model.operation_model("CreateGateway").input_shape.members)
        name = T.check_name(ac, "CreateGateway", f"grx-gw-infbody-{run_id}"[:48])
        kw = {k: copy.deepcopy(v) for k, v in got_main.items() if k in create_allowed}
        kw["name"] = name
        kw["description"] = "GRX DIAG inference body probe. Delete on sight."
        kw["tags"] = A.tags_for(run_id, state.expires_at)

        state.record(T.Resource(
            kind="gateway", logical="infbody", name=name, service="bedrock-agentcore-control",
            delete_op="delete_gateway", delete_params={"gatewayIdentifier": name},
            ids={"gateway_id": ""}, delete_priority=30,
            notes="DIAG inference body probe. Holds a policyEngineConfiguration and bills."))
        state.write()

        A.limiter().wait("CreateGateway")
        made = capture(store, "create_gateway", ac, **kw).raise_for_status()
        gid = made.response["gatewayId"]
        gw_url = made.response.get("gatewayUrl", "")
        state.record(T.Resource(
            kind="gateway", logical="infbody", name=name, service="bedrock-agentcore-control",
            delete_op="delete_gateway", delete_params={"gatewayIdentifier": gid},
            ids={"gateway_id": gid}, arn=made.response.get("gatewayArn", ""),
            delete_priority=30, notes="DIAG inference body probe."))
        state.write()

        st, secs = wait_gateway(ac, gid)
        print(f"  gateway {gid}: {st} after {secs}s")
        report["gateway"] = {"id": gid, "status": st, "url": R.mask(gw_url)}
        if st != "READY":
            report["notes"].append(f"gateway settled {st}; no probe ran")
            return 0
        base = gw_url.rsplit("/mcp", 1)[0] if gw_url.endswith("/mcp") else gw_url.rstrip("/")

        A.limiter().wait("CreateGatewayTarget")
        rec = capture(store, "create_gateway_target", ac, gatewayIdentifier=gid, name=TARGET_NAME,
                      description="GRX DIAG inference body probe",
                      targetConfiguration=TARGET_CONFIG,
                      credentialProviderConfigurations=[
                          {"credentialProviderType": "GATEWAY_IAM_ROLE"}])
        if not rec.ok:
            report["notes"].append(
                f"inference target refused: {rec.error_code}: {rec.error_message}")
            print(f"  target REFUSED: {rec.error_code}")
            return 0
        tid = rec.response["targetId"]
        tst, tsecs = wait_target(ac, gid, tid)
        print(f"  inference target {tid}: {tst} after {tsecs}s")
        report["target"] = {"id": tid, "status": tst, "config": TARGET_CONFIG}
        if tst != "READY":
            return 0

        pool = urllib3.PoolManager(retries=False)
        creds = fc.session().get_credentials()
        url = f"{base}{INFERENCE_PATH}"
        for label, model in CANDIDATES:
            out = signed_post(pool, creds, args.region, url, body_for(model), args.read_timeout)
            out["candidate"] = label
            out["model"] = model
            out["bucket"] = bucket(out)
            report["candidates"].append(out)
            print(f"  {label:22s} model={str(model):48s} {out['bucket']:18s} "
                  f"HTTP {out.get('status', out.get('transport_error'))} "
                  f"{out.get('elapsed_s')}s")
            print(f"      {str(out.get('body'))[:300]}")

        buckets = {c["candidate"]: c["bucket"] for c in report["candidates"]}
        report["buckets"] = buckets

        # Control 1: the colon must still be refused on charset. If it is not, the charset
        # explanation for round 1's result is wrong and nothing built on it can be trusted.
        if buckets.get("colon_still_rejected") != "front_door_reject":
            report["notes"].append(
                f"CONTROL 1 BROKE: a colon-bearing model id bucketed as "
                f"{buckets.get('colon_still_rejected')} rather than front_door_reject, so the "
                f"charset explanation of round 1 is wrong and F1-15 must not assume it")
        # Control 2: a model matching no declared glob must not route. Without this, a routing
        # success would not show that the `models` declaration is what does the routing — the target
        # might simply forward everything.
        if buckets.get("unmatched_model") not in ("no_route", "front_door_reject"):
            report["notes"].append(
                f"CONTROL 2 BROKE: a model matching neither declared glob bucketed as "
                f"{buckets.get('unmatched_model')}, so this target forwards models it does not "
                f"declare and the `operations[].models` list is not what routes requests")
        # Control 3: same validator as round 1.
        if buckets.get("model_field_absent") != "front_door_reject":
            report["notes"].append(
                f"CONTROL 3 BROKE: an absent model field bucketed as "
                f"{buckets.get('model_field_absent')} rather than front_door_reject, so this round "
                f"is not reaching the validator round 1 reached")

        # Eligible for F1-15 means the request crossed the gateway, so a policy denial would have had
        # to intervene to stop it. A 404 from the gateway's own routing does NOT qualify, which is
        # the whole distinction round 1 lacked.
        eligible = [c["candidate"] for c in report["candidates"]
                    if c["bucket"] in ("ok", "provider_reached")]
        report["eligible_for_f115"] = eligible
        if eligible:
            report["notes"].append(
                f"F1-15's inference arm can be given an eligible request: use model "
                f"{[c['model'] for c in report['candidates'] if c['candidate'] == eligible[0]][0]} "
                f"with the target configuration recorded under `target.config`")
        else:
            report["notes"].append(
                "no candidate crossed the gateway, so F1-15's inference arm still cannot be given a "
                "request that is eligible to be denied; the arm must be reported as not measured "
                "rather than as a bypass")
        return 0
    finally:
        if tid:
            A.limiter().wait("DeleteGatewayTarget")
            d = capture(store, "delete_gateway_target", ac, gatewayIdentifier=gid, targetId=tid)
            print(f"  teardown target: {'ok' if d.ok else d.error_code}")
        for attempt in range(1, DELETE_ATTEMPTS + 1):
            if not gid:
                break
            A.limiter().wait("DeleteGateway")
            d = capture(store, "delete_gateway", ac, gatewayIdentifier=gid)
            if d.ok:
                print(f"  teardown gateway: ok (attempt {attempt})")
                state.drop("gateway", "infbody")
                state.write()
                break
            print(f"  teardown gateway: {d.error_code} (attempt {attempt}"
                  f"{'; retrying' if attempt < DELETE_ATTEMPTS else '; GIVING UP — LEAKED'})")
            if attempt < DELETE_ATTEMPTS:
                time.sleep(DELETE_BACKOFF_S)
        report["ended_utc"] = _now_iso()
        out_path = ROOT / "results" / f"{LABEL}-{_now_stamp()}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(R.mask(report), indent=2) + "\n")
        print(f"  wrote {out_path.relative_to(ROOT)}")
        for n in report["notes"]:
            print(f"  NOTE: {n}")


if __name__ == "__main__":
    raise SystemExit(main())
