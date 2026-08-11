#!/usr/bin/env python3
"""Phase 2 step 2: deploy `grx-echo-<runid>`, the deterministic tool target.

The handler and its tool schema live in `infra/echo_handler.py`; this script packages that
file and creates the function, its own execution role, and the resource policy that lets the
gateway invoke it.

Why the code hash is asserted rather than trusted
-------------------------------------------------
`UpdateFunctionCode` returns `LastUpdateStatus: InProgress`, so a script that updates and exits
has deployed nothing yet — the next call may reach the *old* code. That is not a slow start, it
is a silent wrong-version measurement: `echo_handler.py`'s `slept_ms` field is F6's ground-truth
`TargetExecutionTime`, and an arm collected against a previous build would contribute a
correct-looking number produced by different code. So the deploy waits for `Successful` and
then compares the function's `CodeSha256` against the sha256 of the zip it just built.

The zip is built deterministically
----------------------------------
`ZipInfo` entries carry a fixed timestamp and the archive is written to a bytes buffer, so the
same handler source yields the same `CodeSha256` on every run. Two consequences, both wanted:
`--ensure` can tell "already deployed with this exact code" from "deployed with something
else" without keeping a state file of hashes, and Phase 8's +7d/+30d re-runs can *prove* the
target was unchanged rather than asserting it. A zip whose mtime came from the filesystem would
differ on every build and make that impossible.

Why the function gets its own execution role
--------------------------------------------
`grx-gw-exec` is the *gateway's* role and its contents are under test (F5-4b removes a
statement from it). A Lambda that shared it would stop being invocable the moment a red-team
arm mutated it, and the arm's result would then be confounded: "the gateway could not evaluate
guardrails" and "the tool could not write logs" would both be in flight at once.

Cost
----
Lambda's free tier covers 1M requests and 400,000 GB-seconds per month. The full project sends
roughly 20,000 tool calls at 128 MB and well under 100 ms each — about 250 GB-seconds. Storage
for a ~4 KB zip is negligible. **Effectively $0**, and reported as such in COST.md rather than
omitted: a phase with no line item looks like a phase nobody costed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "infra"))

import awsclients as A                                            # noqa: E402
from evidence import EvidenceStore, capture, new_run_id            # noqa: E402
from testbed import Resource, State                                # noqa: E402

import echo_handler                                                # noqa: E402

HANDLER_SRC = Path(__file__).resolve().parent / "echo_handler.py"

RUNTIME = "python3.12"
HANDLER = "echo_handler.lambda_handler"
MEMORY_MB = 128
# 30 s: above the handler's own 5 s delay cap with a wide margin, and below the gateway's
# tolerance. A timeout at the handler's cap would make a capped `delay` call indistinguishable
# from a platform timeout, and F6's additivity arm sends delay=2000.
TIMEOUT_S = 30

# Deletion priorities. The resource policy dies with the function; the function must go before
# its execution role (85) but after the gateway target that references it (05_target.py, 20).
_FN_PRIORITY = 60
_FN_ROLE_PRIORITY = 85


def build_zip() -> tuple[bytes, str]:
    """A byte-reproducible zip of the handler. Returns (bytes, sha256-base64-as-hex).

    Lambda reports `CodeSha256` as **base64 of the SHA-256 of the zip**, so the comparison at
    the end of this script must be against that encoding, not against a hex digest. Both are
    computed here and the hex one is what goes into the state file, because a hex digest is
    what a reader can reproduce with `shasum -a 256`.
    """
    buf = io.BytesIO()
    src = HANDLER_SRC.read_bytes()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # A fixed date_time and explicit permissions: `zipfile.write()` would embed the file's
        # mtime, which changes on every checkout and would make CodeSha256 unstable across
        # machines. 0o644 with the regular-file bit, matching what `zipfile.write` produces for
        # a normal file, so the archive is not merely reproducible but ordinary.
        info = zipfile.ZipInfo("echo_handler.py", date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = (0o100644 & 0xFFFF) << 16
        info.create_system = 3
        z.writestr(info, src)
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def code_sha256_b64(data: bytes) -> str:
    """The encoding Lambda uses for `CodeSha256`: base64 of the raw digest."""
    import base64
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def fn_role_spec(run_id: str) -> dict:
    """The Lambda's own execution role: logs only. Nothing else — the tool touches nothing."""
    return {
        "name": f"grx-echo-exec-{run_id}",
        "trust": {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        },
        "inline": {
            "grx-echo-logs": {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogGroup", "logs:CreateLogStream",
                               "logs:PutLogEvents"],
                    "Resource": "arn:aws:logs:*:*:*",
                }],
            },
        },
    }


def ensure_fn_role(iam, store, spec: dict, tag_list: list[dict]) -> str:
    """Create the function's execution role if absent; return its ARN."""
    name = spec["name"]
    try:
        return iam.get_role(RoleName=name)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass
    capture(store, "create_role", iam, RoleName=name,
            AssumeRolePolicyDocument=json.dumps(spec["trust"]),
            Description="execution role for the grx-echo deterministic tool target",
            Tags=tag_list).raise_for_status()
    for pn, doc in spec["inline"].items():
        capture(store, "put_role_policy", iam, RoleName=name, PolicyName=pn,
                PolicyDocument=json.dumps(doc)).raise_for_status()
    return iam.get_role(RoleName=name)["Role"]["Arn"]


def wait_active(lam, name: str, *, timeout_s: int = 120, sleep=time.sleep) -> dict:
    """Poll until State=Active and LastUpdateStatus is terminal. Returns the final config.

    Both fields, not just `State`: a freshly created function reaches `Active` while an
    `UpdateFunctionCode` is still `InProgress`, and invoking in that window can run the
    previous code. The docstring's point about wrong-version measurement is enforced here.
    """
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        last = lam.get_function_configuration(FunctionName=name)
        state = last.get("State")
        upd = last.get("LastUpdateStatus")
        if state == "Failed":
            raise RuntimeError(f"{name} is State=Failed: {last.get('StateReason')}")
        if upd == "Failed":
            raise RuntimeError(
                f"{name} LastUpdateStatus=Failed: {last.get('LastUpdateStatusReason')}")
        if state == "Active" and upd in (None, "Successful"):
            return last
        sleep(2.0)
    raise TimeoutError(
        f"{name} did not become Active/Successful in {timeout_s}s; last state="
        f"{last.get('State')} update={last.get('LastUpdateStatus')}. Invoking now could run "
        f"a previous build, which would contribute a wrong-version latency observation.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--ttl-hours", type=int, default=72)
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--smoke", action="store_true",
                    help="after deploying, invoke each of the three modes DIRECTLY (not "
                         "through the gateway) and print the responses. This is the "
                         "--n 3 smoke of the plan's dry-run rule: it proves the handler "
                         "dispatches before a gateway, a policy engine and a target are "
                         "built on top of it.")
    args = ap.parse_args()

    if not args.dry_run and not args.ensure:
        print("refusing to run: pass --dry-run or --ensure.", file=sys.stderr)
        return 2

    data, zip_hex = build_zip()
    schema = echo_handler.TOOL_SCHEMA

    if args.dry_run:
        run_id = args.run_id or "dryrun"
        print(f"Phase 2 step 2 — Lambda target, run_id={run_id}")
        print(f"  function      grx-echo-{run_id}")
        print(f"  runtime       {RUNTIME}  handler={HANDLER}  "
              f"mem={MEMORY_MB}MB  timeout={TIMEOUT_S}s")
        print(f"  exec role     {fn_role_spec(run_id)['name']}  (logs only)")
        print(f"  zip           {len(data)} bytes  sha256={zip_hex}")
        print(f"                CodeSha256 (base64, what Lambda reports) = "
              f"{code_sha256_b64(data)}")
        print(f"  tools         {[t['name'] for t in schema]}")
        for t in schema:
            props = t["inputSchema"].get("properties", {})
            req = t["inputSchema"].get("required", [])
            print(f"    {t['name']:8s} " + ", ".join(
                f"{k}:{v['type']}{'*' if k in req else ''}" for k, v in props.items()))
        print("  payload table (mode=fixed):")
        for k, v in sorted(echo_handler.PAYLOADS.items()):
            print(f"    {k:8s} len={len(v):5d} sha256={echo_handler.payload_digest(k)}")
        print("\n--dry-run: no AWS call made.")
        return 0

    run_id = args.run_id or new_run_id()
    expires = (datetime.now(timezone.utc)
               + timedelta(hours=args.ttl_hours)).replace(microsecond=0).isoformat()

    f = A.factory(args.region)
    lam = f.lambda_()
    iam = f.iam()
    account_id = f.sts().get_caller_identity()["Account"]

    state = State.load_or_new(run_id, args.region, expires, path=Path(args.state)
                              if args.state else None)
    run_id = state.run_id
    tags = A.tags_for(run_id, state.expires_at)
    tag_list = [{"Key": k, "Value": v} for k, v in sorted(tags.items())]

    store = EvidenceStore(run_id, "infra", "P2-02-lambda")
    store.write_environment()

    name = f"grx-echo-{run_id}"
    print(f"Phase 2 step 2 — Lambda target {name}, region={args.region}")

    role_spec = fn_role_spec(run_id)
    role_arn = ensure_fn_role(iam, store, role_spec, tag_list)
    state.record(Resource(
        kind="iam-role", logical="echo-exec", name=role_spec["name"], service="iam",
        delete_op="delete_role", delete_params={"RoleName": role_spec["name"]},
        ids={"role_name": role_spec["name"],
             "inline_policies": sorted(role_spec["inline"])},
        arn=role_arn, delete_priority=_FN_ROLE_PRIORITY,
        notes="grx-echo's own execution role. Separate from grx-gw-exec on purpose: that "
              "role's contents are F5-4b's mutation target, and a shared role would confound "
              "'guardrails could not evaluate' with 'the tool could not log'.",
    ))

    exists = True
    try:
        cfg = lam.get_function_configuration(FunctionName=name)
    except lam.exceptions.ResourceNotFoundException:
        exists = False
        cfg = {}

    want_b64 = code_sha256_b64(data)
    if not exists:
        rec = capture(store, "create_function", lam,
                      FunctionName=name, Runtime=RUNTIME, Role=role_arn, Handler=HANDLER,
                      Code={"ZipFile": data}, Timeout=TIMEOUT_S, MemorySize=MEMORY_MB,
                      Description="deterministic tool target for guardrails validation",
                      Tags=tags)
        if not rec.ok and rec.error_code == "InvalidParameterValueException":
            # IAM role propagation. The only retry in this script, and it is bounded and
            # explained rather than a general backoff: create_function validates that it can
            # assume the role, and a role created seconds ago in 01_iam.py or just above may
            # not have propagated. Retrying anything else here would mask a real rejection.
            print("  role not yet assumable (IAM propagation); retrying for up to 60s")
            for _ in range(12):
                time.sleep(5.0)
                rec = capture(store, "create_function", lam,
                              FunctionName=name, Runtime=RUNTIME, Role=role_arn,
                              Handler=HANDLER, Code={"ZipFile": data}, Timeout=TIMEOUT_S,
                              MemorySize=MEMORY_MB,
                              Description="deterministic tool target for guardrails "
                                          "validation",
                              Tags=tags)
                if rec.ok or rec.error_code != "InvalidParameterValueException":
                    break
        rec.raise_for_status()
        print(f"  created  request-id {rec.request_id}")
    elif cfg.get("CodeSha256") != want_b64:
        print(f"  code differs (live {cfg.get('CodeSha256')} != built {want_b64}); updating")
        capture(store, "update_function_code", lam, FunctionName=name,
                ZipFile=data).raise_for_status()
    else:
        print("  exists with the exact built code (CodeSha256 matches)")

    cfg = wait_active(lam, name)

    # The assertion the docstring is about. A deploy that reported success and left the old
    # code would otherwise be discovered only as an anomalous F6 residual, weeks later.
    live_sha = cfg.get("CodeSha256")
    if live_sha != want_b64:
        print(f"FAIL: deployed CodeSha256 {live_sha} != built {want_b64}. The function is "
              f"running code other than infra/echo_handler.py, so slept_ms — F6's "
              f"ground-truth TargetExecutionTime — would be produced by an unknown build.",
              file=sys.stderr)
        return 1

    fn_arn = cfg["FunctionArn"]
    state.record(Resource(
        kind="lambda", logical="echo", name=name, service="lambda",
        delete_op="delete_function", delete_params={"FunctionName": name},
        ids={"function_name": name, "code_sha256_hex": zip_hex,
             "code_sha256_b64": want_b64, "runtime": RUNTIME, "handler": HANDLER,
             "memory_mb": MEMORY_MB, "timeout_s": TIMEOUT_S,
             "tools": [t["name"] for t in schema],
             "payload_digests": {k: echo_handler.payload_digest(k)
                                 for k in sorted(echo_handler.PAYLOADS)}},
        arn=fn_arn, delete_priority=_FN_PRIORITY,
        notes="deterministic tool target; echo/fixed/delay. The code hash is recorded so "
              "Phase 8's +7d/+30d re-runs can PROVE the target was unchanged.",
    ))

    # The gateway's permission to invoke. A resource policy rather than relying solely on the
    # gateway role's identity policy: both are required for a cross-service invoke, and the
    # statement id is fixed so re-running is idempotent (a duplicate raises
    # ResourceConflictException, which is caught rather than treated as a failure).
    gw_role = state.find("iam-role", "gw-exec")
    if gw_role:
        sid = f"grx-gw-invoke-{run_id}".replace(":", "-")[:100]
        rec = capture(store, "add_permission", lam,
                      FunctionName=name, StatementId=sid,
                      Action="lambda:InvokeFunction",
                      Principal=f"arn:aws:iam::{account_id}:role/{gw_role.name}")
        if rec.ok:
            print(f"  resource policy: {gw_role.name} may invoke  (sid {sid})")
        elif rec.error_code == "ResourceConflictException":
            print(f"  resource policy already present (sid {sid})")
        else:
            rec.raise_for_status()
    else:
        # Not fatal, and said out loud rather than skipped silently: 01_iam.py may not have
        # run yet, and 05_gateway.py re-checks this before creating a gateway.
        print("  NOTE: no iam-role/gw-exec in the ledger, so no resource policy was added. "
              "Run infra/01_iam.py --ensure first, then re-run this script.",
              file=sys.stderr)

    if args.smoke:
        print("\nsmoke: invoking each mode directly (bypassing the gateway)")
        # The client context the GATEWAY would send, synthesized here. This is the only place
        # the harness fabricates it — every later phase gets the real one from the gateway —
        # and it is deliberately built with the `___`-prefixed tool name so the smoke test
        # exercises `tool_name_from_context`'s stripping rather than bypassing it.
        import base64
        ok = True
        for tool, payload in (("echo", {"text": "smoke", "amount": 500}),
                              ("fixed", {"key": "short"}),
                              ("delay", {"ms": 50})):
            cc = base64.b64encode(json.dumps({"custom": {
                "bedrockAgentCoreMessageVersion": "1.0",
                "bedrockAgentCoreAwsRequestId": "smoke",
                "bedrockAgentCoreMcpMessageId": "smoke",
                "bedrockAgentCoreGatewayId": "smoke",
                "bedrockAgentCoreTargetId": "smoke",
                "bedrockAgentCoreToolName": f"grxecho___{tool}",
            }}).encode()).decode()
            r = lam.invoke(FunctionName=name, Payload=json.dumps(payload).encode(),
                           ClientContext=cc)
            body = json.loads(r["Payload"].read())
            fault = r.get("FunctionError")
            print(f"  {tool:6s} -> {json.dumps(body)[:220]}")
            if fault or body.get("error") or body.get("tool") != tool:
                print(f"  FAIL: {tool} did not dispatch cleanly "
                      f"(FunctionError={fault})", file=sys.stderr)
                ok = False
        if not ok:
            return 1

    store.write_summary({"function": name, "code_sha256_hex": zip_hex,
                         "code_sha256_b64": want_b64, "smoke": bool(args.smoke)})
    print(f"\nstate -> {state.write().name}")
    print(f"zip sha256 {zip_hex}  ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
