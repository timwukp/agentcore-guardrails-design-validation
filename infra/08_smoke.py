#!/usr/bin/env python3
"""Phase 2 step 8: the end-to-end benign call. **This is the project's first billable request.**

Everything before this step was metadata. This script sends a real MCP `tools/call` through
`grx-gw` (policy engine, ENFORCE) and through `grx-gw-nopolicy`, and then asserts a span
carrying our gateway ARN appears in `aws/spans`. That is the plan's Phase 2 gate, verbatim:
"gateway READY; span visible for our ARN".

What a benign call being *allowed* actually proves, and what it does not
-----------------------------------------------------------------------
It proves the whole chain is wired: SigV4 signing under `bedrock-agentcore`, the MCP session
header, the gateway's AWS_IAM authorizer accepting our assumed `grx-caller` principal, the Cedar
baseline permit matching, the `GATEWAY_IAM_ROLE` credential provider reaching the Lambda, the
Lambda dispatching on `___`-prefixed tool names, and the response coming back parseable.

It does **not** prove enforcement works. A permit-everything policy and a broken evaluator are
indistinguishable from an allowed benign call — which is exactly why this script also sends one
call it expects to be **denied**, using a principal the baseline permit does not cover. Without
that negative, the gate would be satisfied by a gateway whose policy engine was doing nothing,
and Phase 3 would open with a testbed that cannot deny anything and no way to know it. Per the
project's own rule that every case is mutation-paired: an allow with no matching deny is not
evidence.

Why there is no deny arm in *this* script, stated rather than left as an omission
--------------------------------------------------------------------------------
The honest cheap negative is not available here. A nonexistent tool name is not a policy
decision, so `grxecho___nosuchtool` would prove nothing; and every genuinely decisive negative
requires changing the policy, which is F4's job — F4 owns the 2×2 truth table and runs under
Bonferroni as a confirmatory family, and duplicating a weaker version of it here would add a
result that has to be excluded from the analysis.

So the gate this script establishes is exactly "the chain is wired", and the project's
mutation-pairing rule is satisfied one phase later rather than being quietly dropped: **Phase 3
must not be reported without F4's inverting mutations.** What this script does add for free is
both sides of the *exemption* claim — `tools/call` is policy-evaluated, `prompts/list` is
documented exempt — which costs two requests and tells F4 whether its exemption arm has a
working baseline.

Cost
----
Four to six tool invocations plus their policy evaluations, and a few Logs Insights scans over
`aws/spans` (scanned-bytes billing, filtered to our ARN over a 15-minute window). Under **$0.01**
and disclosed rather than rounded to zero, because a step with no line item reads as a step
nobody costed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "infra"))

import awsclients as A                                            # noqa: E402
import cedar                                                       # noqa: E402
import mcp as M                                                    # noqa: E402
import testbed as T                                               # noqa: E402
from evidence import EvidenceStore                                 # noqa: E402
from testbed import State                                          # noqa: E402

import importlib.util                                              # noqa: E402


def _load_traces_module():
    """`07_traces.py` starts with a digit, so it cannot be imported by name.

    Loaded by path rather than copied, because `query_spans` carries the one non-negotiable
    detail — the filter to our gateway ARN — and a second copy of that function is a second
    place for the filter to be dropped. `lib/tests/test_module_name_collisions.py` requires the
    registered name to not collide with anything `lib/` owns, hence the `_infra07` prefix.
    """
    spec = importlib.util.spec_from_file_location(
        "_infra07_traces", Path(__file__).resolve().parent / "07_traces.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The benign argument set. `amount=100` sits BELOW the 500 threshold every later Cedar numeric
# arm uses, so this smoke call stays on the allowed side of a condition later phases will place
# there — a smoke test that happened to trip a future arm's threshold would have to be rewritten
# the moment that arm was added.
BENIGN_ARGS = {"text": "phase2 smoke", "amount": 100}


def one_call(client: M.McpClient, action_id: str, args: dict, label: str) -> M.Decision:
    d = client.call_tool(action_id, args)
    flag = ""
    if d.unclassified:
        flag = "  UNCLASSIFIED"
    elif d.default_deny:
        flag = "  default-deny"
    print(f"    {label:22s} {d.outcome:14s} http={d.http_status} "
          f"{d.duration_ms:7.1f}ms  req={d.request_id or '?'}{flag}")
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run", action="store_true",
                    help="send the calls. THIS SPENDS MONEY (under $0.01).")
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--skip-spans", action="store_true",
                    help="skip the span assertion. Only for a re-run whose purpose is the "
                         "tool-call half; the Phase 2 GATE includes the span, so a --skip-spans "
                         "run does NOT satisfy it and the summary records that.")
    ap.add_argument("--span-timeout", type=int, default=300)
    args = ap.parse_args()

    if not (args.dry_run or args.run):
        print("refusing to run: pass --dry-run or --run.", file=sys.stderr)
        return 2

    state = State.load(Path(args.state) if args.state else None)

    if args.dry_run:
        print(f"Phase 2 step 8 — end-to-end benign call, run_id={state.run_id}")
        tgt = state.find("gateway-target", "main")
        acts = tgt.ids["cedar_action_ids"] if tgt else ["grxecho___echo (from the ledger)"]
        print(f"  action ids    {acts}")
        print(f"  benign args   {json.dumps(BENIGN_ARGS)}   (amount<500, so this call stays on "
              f"the allowed side of the threshold later Cedar arms use)")
        print("  arms:")
        print("    main/tools/call        expect allowed   (baseline permit matches)")
        print("    nopolicy/tools/call    expect allowed   (no engine at all)")
        print("    main/prompts/list      expect allowed   (documented policy-exempt)")
        print("    main/tools/list        expect allowed   — and NOT used as an oracle: "
              "listing is a meta action")
        print(f"  span assert   Logs Insights over {'aws/spans'} filtered to OUR gateway ARN, "
              f"up to {args.span_timeout}s")
        print("  cost          <$0.01 — the FIRST billable request of the project")
        print("\n--dry-run: no AWS call made, nothing spent.")
        return 0

    f = A.factory(args.region)
    account_id = A.account_id(f)
    store = EvidenceStore(state.run_id, "infra", "P2-08-smoke")
    store.write_environment()

    caller = state.find("iam-role", "caller")
    tgt = state.get("gateway-target", "main")
    action_echo = cedar.action_id(tgt.ids["target_name"], "echo")

    print(f"Phase 2 step 8 — end-to-end smoke, run_id={state.run_id}, region={args.region}")
    if caller:
        # The principal Cedar sees. Printed because every principal-scoped arm in Phases 3-5
        # depends on it being the assumed role and not the ambient user, and this is the first
        # place the real value is observable.
        print(f"  principal     assumed-role/{caller.name}  (what Cedar matches on)")
        fc = A.factory(args.region, role_arn=T.unmask_arn(caller.arn, account_id))
    else:
        print("  principal     WARNING: no iam-role/caller in the ledger; calling with ambient "
              "credentials, so every later `principal ==` arm would see a different id",
              file=sys.stderr)
        fc = f

    results: dict[str, dict] = {}
    ok = True

    for logical in ("main", "nopolicy"):
        gw = state.get("gateway", logical)
        url = gw.ids["gateway_url"]
        print(f"  {logical}  {url}")
        client = M.client_for(url, fc, store=store,
                              policy_session_id=M.policy_session_id(state.run_id,
                                                                    f"smoke-{logical}"),
                              session_timeout_s=gw.ids.get("session_timeout_s", 900))
        try:
            init = client.initialize()
            print(f"    initialize             session={client.session_id[:12]}… "
                  f"server={((init.get('result') or {}).get('serverInfo') or {}).get('name')}")

            tools, d_list = client.list_tools()
            names = sorted(t.get("name", "") for t in tools)
            print(f"    tools/list             {d_list.outcome:14s} {names}")
            if action_echo not in names:
                # Not fatal by itself — visibility is not authorization and its absence is not
                # non-authorization either. Said out loud because it usually means the target
                # is not READY on this gateway, which the next call will show properly.
                print(f"    NOTE: {action_echo} is not in tools/list. Listing is a meta action, "
                      f"so this is not evidence either way; the tools/call below is.")

            d_call = one_call(client, action_echo, BENIGN_ARGS, "tools/call echo")
            d_prompts = client.prompts_list()
            print(f"    prompts/list           {d_prompts.outcome:14s} "
                  f"(documented policy-exempt)")

            results[logical] = {
                "session_id_prefix": client.session_id[:12],
                "tools_listed": names,
                "tools_call": d_call.to_json(),
                "prompts_list": d_prompts.to_json(),
                "reactive_renewals": client.reactive_renewals,
            }

            if not d_call.allowed:
                ok = False
                if d_call.default_deny:
                    why = ("a DEFAULT-DENY, which means the baseline permit is not matching. An "
                           "ENFORCE engine with no effective permit denies everything, so every "
                           "later arm would fail for that reason rather than for its own.")
                elif d_call.unclassified:
                    why = ("an error shape lib/mcp.classify() does not recognise, which is why "
                           "it is flagged rather than bucketed: " + (d_call.text or "")[:300])
                else:
                    why = "text=" + (d_call.text or "")[:300]
                print(f"FAIL: the benign call on {logical} was {d_call.outcome} — {why}",
                      file=sys.stderr)
            # The echoed payload is the `context.output.*` driver for F5-5, so its round trip is
            # asserted here rather than discovered missing three phases later.
            elif logical == "main":
                echoed = (d_call.text or "")
                if BENIGN_ARGS["text"] not in echoed:
                    ok = False
                    print(f"FAIL: the tool responded but did not echo the input text. "
                          f"`context.output.text` is what F5-5's suppressOutput arm reads, so a "
                          f"non-echoing target makes that arm untestable. got={echoed[:200]!r}",
                          file=sys.stderr)
                else:
                    print("    echo round trip        input text present in the response "
                          "(context.output.* is drivable)")
        finally:
            client.close()

    # Both gateways must agree on the benign call, or the F6 pair is not comparable: a difference
    # in *outcome* between the two arms is not a latency difference, and Phase 6 would be
    # differencing an allow against a deny.
    if ("main" in results and "nopolicy" in results):
        a = results["main"]["tools_call"]["outcome"]
        b = results["nopolicy"]["tools_call"]["outcome"]
        if a != b:
            ok = False
            print(f"FAIL: the benign call had outcome {a} on main and {b} on nopolicy. F6 pairs "
                  f"these two, and differencing an allow against a deny measures nothing.",
                  file=sys.stderr)
        else:
            print(f"  pair check    same outcome on both gateways: {a}")

    # --- the span assertion: the Phase 2 gate -------------------------------------------------
    span_verdict: dict = {"asserted": not args.skip_spans}
    if args.skip_spans:
        print("  spans         SKIPPED by flag — this run does NOT satisfy the Phase 2 gate")
    else:
        tr = _load_traces_module()
        logs = f.logs()
        for logical in ("main", "nopolicy"):
            gw_arn = T.unmask_arn(state.get("gateway", logical).arn, account_id)
            found, secs, rows = tr.wait_for_span(logs, gw_arn, timeout_s=args.span_timeout)
            span_verdict[logical] = {"found": found, "first_seen_after_s": round(secs, 1),
                                     "n_rows": len(rows)}
            if found:
                print(f"    {logical:9s} span for our ARN visible after {secs:.0f}s "
                      f"({len(rows)} rows)")
            else:
                ok = False
                print(f"FAIL: no span carrying {logical}'s gateway ARN appeared in aws/spans "
                      f"within {args.span_timeout}s. Either 07_traces.py's delivery is not "
                      f"live or Transaction Search is not routing — and every O-claim in F7 "
                      f"would then be measuring the absence of our configuration rather than "
                      f"the service's behaviour.", file=sys.stderr)
        # A single observation, labelled as such. F7-6 measures publish lag properly at n=30;
        # this one sample exists only to tell F7-6 whether its ceiling is realistic.
        seen = [v["first_seen_after_s"] for k, v in span_verdict.items()
                if isinstance(v, dict) and v.get("found")]
        if seen:
            print(f"  publish lag   first span after {min(seen):.0f}–{max(seen):.0f}s "
                  f"(n=1 per gateway — NOT the F7-6 measurement, which is n=30 with p50/p90/max)")

    store.write_summary({
        "arms": results, "spans": span_verdict, "ok": ok,
        "satisfies_phase2_gate": bool(ok and not args.skip_spans),
        "benign_args": BENIGN_ARGS, "action_id": action_echo,
        "note": "an allowed benign call proves the chain is wired, not that enforcement works; "
                "F4 owns the truth table and every case there is mutation-paired.",
    })

    if not ok:
        return 1
    print("\nPhase 2 gate SATISFIED: both gateways READY, benign call allowed end to end on "
          "both, and a span carrying each gateway's ARN is visible in aws/spans.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
