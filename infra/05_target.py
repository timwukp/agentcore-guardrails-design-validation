#!/usr/bin/env python3
"""Phase 2 step 5: register the echo Lambda as an MCP target on BOTH gateways.

Both, again for the pairing: an F6 paired difference is only attributable to the policy hops if
the two gateways expose the same tools, backed by the same Lambda, under the same schema. The
target name is identical on both (`grxecho`) so the MCP tool names — and therefore the Cedar
action identifiers — are identical too.

The target name is the Cedar action prefix, and it has no underscores
--------------------------------------------------------------------
`policy-scope.html` gives the MCP action format as `<TargetName>___<ToolName>`, so the target
name is not cosmetic: `grxecho` + `___` + `echo` is the string a policy's
`AgentCore::Action::"..."` must match exactly, and it is also the string
`infra/echo_handler.py` splits with `rsplit(DELIMITER, 1)`. `grx_echo` would have worked for
the handler (rsplit takes the last delimiter) but would read as ambiguous, and the AWS
boilerplate's left-hand `index()` cut would break on it. `TARGET_NAME` is asserted
underscore-free rather than merely chosen carefully.

`GATEWAY_IAM_ROLE`, not `CALLER_IAM_CREDENTIALS`
------------------------------------------------
The credential provider decides *whose* identity invokes the Lambda. `GATEWAY_IAM_ROLE` means
the gateway's execution role does it — which is what makes `grx-gw-exec`'s contents
load-bearing, and therefore what makes F5-4b a real experiment: removing
`bedrock:InvokeGuardrailChecks` from that role can only affect guardrail evaluation if that
role is the one being used. Under `CALLER_IAM_CREDENTIALS` the harness's own credentials would
reach the Lambda and F5-4b would mutate a role that nothing consults.

Why the schema is imported rather than restated
-----------------------------------------------
`echo_handler.TOOL_SCHEMA` is registered verbatim. A schema written out again here would be a
second source of truth for the tool contract, and the specific drift it invites is documented in
the handler: a schema declaring `amount` as a string while the handler tests
`isinstance(amount, (int, float))` makes every Cedar numeric-condition arm take the
`bad_request` branch, which the arm reads as the policy denying.

Cost
----
$0. A target is metadata; the billable event is a tool call.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "infra"))

import awsclients as A                                            # noqa: E402
import cedar                                                       # noqa: E402
import testbed as T                                               # noqa: E402
from evidence import EvidenceStore, capture, new_run_id            # noqa: E402
from testbed import Resource, State                                # noqa: E402

import echo_handler                                                # noqa: E402

# The Cedar action prefix. No underscores, no delimiter — see the module docstring.
TARGET_NAME = "grxecho"

_TARGET_PRIORITY = 20

TERMINAL_OK = {"READY"}
TERMINAL_BAD = {"FAILED", "UPDATE_UNSUCCESSFUL", "DELETING", "SYNCHRONIZE_UNSUCCESSFUL"}
# CREATE_PENDING_AUTH and its siblings are terminal-for-us: they mean the target is waiting on
# an OAuth authorization flow that a GATEWAY_IAM_ROLE target should never enter. Treating them
# as "still creating" would hang the script for the full timeout on a misconfiguration.
TERMINAL_PENDING_AUTH = {"CREATE_PENDING_AUTH", "UPDATE_PENDING_AUTH",
                         "SYNCHRONIZE_PENDING_AUTH"}


def target_config(lambda_arn: str) -> dict:
    return {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_arn,
                "toolSchema": {"inlinePayload": echo_handler.TOOL_SCHEMA},
            },
        },
    }


CREDENTIALS = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]


def wait_target(ac, gateway_id: str, target_id: str, *, timeout_s: int = 300,
                sleep=time.sleep) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    transport_errors = 0
    while time.monotonic() < deadline:
        try:
            last = ac.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
        except Exception as exc:                       # noqa: BLE001
            transport_errors += 1
            if transport_errors > 10:
                raise
            print(f"    (transport error {transport_errors}: {type(exc).__name__}; retrying)")
            sleep(3.0)
            continue
        st = last.get("status")
        if st in TERMINAL_OK or st in TERMINAL_BAD or st in TERMINAL_PENDING_AUTH:
            return last
        sleep(4.0)
    raise TimeoutError(
        f"target {target_id} on {gateway_id} never reached a terminal status in {timeout_s}s; "
        f"last={last.get('status')} reasons={last.get('statusReasons')}")


def find_target(ac, gateway_id: str, name: str) -> dict | None:
    """Find a target by name. ListGatewayTargets' response key is `items`, like ListGateways."""
    token = None
    while True:
        kw = {"gatewayIdentifier": gateway_id, "maxResults": 100}
        if token:
            kw["nextToken"] = token
        resp = ac.list_gateway_targets(**kw)
        for row in resp.get("items") or []:
            if row.get("name") == name:
                return row
        token = resp.get("nextToken")
        if not token:
            return None


def verify_schema(live: dict) -> list[str]:
    """Assert the registered schema is byte-identical to the handler's own.

    "A matching name is not a matching configuration" (`f3_efficacy/00_guardrails.py`). Here
    the specific stake is the parameter *types*: the schema is what the gateway validates
    incoming arguments against, so a drifted `amount` type silently changes what reaches the
    Cedar evaluator, and the arm sees a `bad_request` it attributes to the policy.
    """
    problems = []
    cfg = ((live.get("targetConfiguration") or {}).get("mcp") or {}).get("lambda") or {}
    got = (cfg.get("toolSchema") or {}).get("inlinePayload")
    if got is None:
        problems.append("registered target has no inline tool schema")
        return problems
    want = echo_handler.TOOL_SCHEMA
    if json.dumps(got, sort_keys=True) != json.dumps(want, sort_keys=True):
        got_names = sorted(t.get("name", "") for t in got)
        want_names = sorted(t["name"] for t in want)
        problems.append(f"registered schema differs from echo_handler.TOOL_SCHEMA "
                        f"(tools registered={got_names} expected={want_names})")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--ttl-hours", type=int, default=72)
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    args = ap.parse_args()

    if not args.dry_run and not args.ensure:
        print("refusing to run: pass --dry-run or --ensure.", file=sys.stderr)
        return 2

    if cedar.DELIMITER in TARGET_NAME or "_" in TARGET_NAME:
        print(f"FAIL: TARGET_NAME {TARGET_NAME!r} contains an underscore, which makes the "
              f"Cedar action identifier ambiguous.", file=sys.stderr)
        return 1

    if args.dry_run:
        rid = args.run_id or "dryrun"
        print(f"Phase 2 step 5 — MCP target, run_id={rid}")
        print(f"  target name   {TARGET_NAME}   (on BOTH gateways, so the Cedar action ids "
              f"match)")
        print(f"  lambda        grx-echo-{rid}")
        print(f"  credentials   {CREDENTIALS[0]['credentialProviderType']} — the gateway "
              f"execution role invokes the tool, which is what makes F5-4b meaningful")
        print("  tool -> Cedar action identifier:")
        for t in echo_handler.TOOL_SCHEMA:
            print(f"    {t['name']:8s} -> AgentCore::Action::"
                  f"\"{cedar.action_id(TARGET_NAME, t['name'])}\"")
        print("\n--dry-run: no AWS call made.")
        return 0

    run_id = args.run_id or new_run_id()
    expires = (datetime.now(timezone.utc)
               + timedelta(hours=args.ttl_hours)).replace(microsecond=0).isoformat()

    f = A.factory(args.region)
    ac = f.agentcore_control()
    account_id = f.sts().get_caller_identity()["Account"]

    state = State.load_or_new(run_id, args.region, expires,
                             path=Path(args.state) if args.state else None)
    run_id = state.run_id

    store = EvidenceStore(run_id, "infra", "P2-05-target")
    store.write_environment()

    echo = state.get("lambda", "echo")
    lambda_arn = T.unmask_arn(echo.arn, account_id)

    print(f"Phase 2 step 5 — MCP target {TARGET_NAME}, run_id={run_id}")
    print(f"  lambda        {echo.name}  (code sha256 "
          f"{echo.ids.get('code_sha256_hex', '?')[:16]}…)")

    for logical in ("main", "nopolicy"):
        gw = state.get("gateway", logical)
        gid = gw.ids["gateway_id"]

        rec_existing = state.find("gateway-target", logical)
        tid = rec_existing.ids.get("target_id") if rec_existing else None
        if not tid:
            found = find_target(ac, gid, TARGET_NAME)
            tid = found.get("targetId") if found else None
            if tid:
                print(f"  {logical:9s} target exists: {tid}")

        if not tid:
            rec = capture(store, "create_gateway_target", ac,
                          gatewayIdentifier=gid,
                          name=TARGET_NAME,
                          description="deterministic echo tool target for guardrails "
                                      "validation",
                          targetConfiguration=target_config(lambda_arn),
                          credentialProviderConfigurations=CREDENTIALS)
            rec.raise_for_status()
            tid = rec.response["targetId"]
            print(f"  {logical:9s} created {tid}  request-id {rec.request_id}")

        live = wait_target(ac, gid, tid)
        st = live.get("status")
        if st in TERMINAL_PENDING_AUTH:
            print(f"FAIL: target {tid} on {gw.name} is {st}. A GATEWAY_IAM_ROLE target should "
                  f"never wait on an authorization flow; this indicates the credential "
                  f"provider was not applied. reasons={live.get('statusReasons')}",
                  file=sys.stderr)
            return 1
        if st not in TERMINAL_OK:
            print(f"FAIL: target {tid} on {gw.name} is {st}: {live.get('statusReasons')}",
                  file=sys.stderr)
            return 1

        problems = verify_schema(live)
        if problems:
            print(f"FAIL: {logical}: " + "; ".join(problems), file=sys.stderr)
            return 1

        print(f"  {logical:9s} READY   schema verified against echo_handler.TOOL_SCHEMA")

        state.record(Resource(
            kind="gateway-target", logical=logical, name=TARGET_NAME,
            service="bedrock-agentcore-control",
            delete_op="delete_gateway_target",
            delete_params={"gatewayIdentifier": gid, "targetId": tid},
            ids={"target_id": tid, "gateway_id": gid,
                 "target_name": TARGET_NAME,
                 "lambda_function": echo.name,
                 "credential_provider_type": CREDENTIALS[0]["credentialProviderType"],
                 # The MCP tool names, which are ALSO the Cedar action identifiers. Stored so
                 # every later phase authors policies against the same strings this script
                 # registered, instead of rebuilding them from a target name it assumes.
                 "tool_names": [t["name"] for t in echo_handler.TOOL_SCHEMA],
                 "cedar_action_ids": [cedar.action_id(TARGET_NAME, t["name"])
                                      for t in echo_handler.TOOL_SCHEMA]},
            arn="", delete_priority=_TARGET_PRIORITY,
            notes="MCP Lambda target. Must be deleted BEFORE its gateway (priority 20 < 30) "
                  "and before the Lambda it points at (60).",
        ))

    # The two targets must expose the same action ids, or the F6 pair is not comparable at the
    # tool level even though the gateways match at the config level.
    a = state.get("gateway-target", "main").ids["cedar_action_ids"]
    b = state.get("gateway-target", "nopolicy").ids["cedar_action_ids"]
    if a != b:
        print(f"FAIL: the two gateways expose different action ids ({a} vs {b}), so an F6 "
              f"paired trial would not be calling the same tool on both sides.",
              file=sys.stderr)
        return 1
    print(f"  pair check    identical action ids on both gateways: {a}")

    store.write_summary({"target_name": TARGET_NAME, "cedar_action_ids": a,
                         "targets": {lg: state.get("gateway-target", lg).ids["target_id"]
                                     for lg in ("main", "nopolicy")}})
    print(f"\nstate -> {state.write().name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
