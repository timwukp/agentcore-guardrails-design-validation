#!/usr/bin/env python3
"""Phase 2 step 3: create `grx-pe-<runid>` and its baseline permit policy.

Two resources, and the second one is the whole point of the step: a policy engine with no
`permit` in it blocks all traffic in ENFORCE mode, so "the testbed is built" and "the testbed
can serve a benign request" are different states and the second needs a policy.

What this script deliberately does NOT do
-----------------------------------------
It does not decide whether the baseline permit our document recommends is *valid*. That is
F1-3 (Phase 3), the highest-value single test in the plan, and it must be run as a clean
experiment against a fresh engine with the validation mode as its independent variable. Here
the engine simply needs to work, so the baseline permit goes in under
`validationMode=IGNORE_ALL_FINDINGS` — the value the AWS getting-started guide passes for this
same statement — and the script *records that it had to*.

That recording is the evidence, and it is worth being precise about why. The account already
contains policy `agentcore_test_pol_50513b5b-p6okjcbkkc`: exactly the statement our §3.1/§7.2/§8
tell readers to add, sitting in `CREATE_FAILED` with two `Overly Permissive` findings, created
in June 2026 by an unrelated experiment. That is a strong indication, but it is not our
measurement: we do not know what validation mode that call used. So this script tries the
document's default path **first** — no `validationMode` at all — and only falls back to
`IGNORE_ALL_FINDINGS` if that is rejected, printing which path was taken. If the default path
succeeds, DC-1 is not reproducible and the document may be fine; if it fails, we have our own
first-hand instance of the trap, with our own request id, before Phase 3 even starts.

Why the fallback is not "just always pass IGNORE_ALL_FINDINGS"
--------------------------------------------------------------
Always passing it would build a working testbed and destroy the observation. The cost of trying
the documented path first is one rejected API call.

Rate limit
----------
`CreatePolicyEngine` and `DeletePolicyEngine` are quota-limited to **1/s** (verified in Service
Quotas, not assumed). `lib/awsclients.py`'s limiter carries that number; this script creates one
engine, so the limit only matters when a teardown-and-rebuild cycle runs back to back.

Cost
----
Policy engines and policies have no per-hour charge; evaluation is billed at the gateway. This
step is **$0**.
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

import awsclients as A                                            # noqa: E402
import cedar                                                       # noqa: E402
import testbed as T                                                # noqa: E402
from evidence import EvidenceStore, capture, new_run_id            # noqa: E402
from testbed import Resource, State                                # noqa: E402

# The engine must outlive every gateway that points at it, and the policy must go before the
# engine. Gateways are 30 (05_gateway.py), targets 20 (06_target.py).
_ENGINE_PRIORITY = 70
_POLICY_PRIORITY = 40

TERMINAL_OK = {"ACTIVE"}
TERMINAL_BAD = {"CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED", "DELETING"}


def wait_status(get, ident_kwargs: dict, *, key: str = "status",
                timeout_s: int = 180, sleep=time.sleep) -> dict:
    """Poll a get_* operation until its status is terminal. Returns the last response.

    Transport errors are retried rather than raised, for the reason
    `f3_efficacy/00_guardrails.py` gives: a DNS blip during the wait would lose the resource's
    identifiers, and a created-but-unrecorded policy engine is precisely the orphan the tag
    sweep exists to catch. Better to keep polling and let the timeout be the failure.
    """
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    transport_errors = 0
    while time.monotonic() < deadline:
        try:
            last = get(**ident_kwargs)
        except Exception as exc:                     # noqa: BLE001 — see docstring
            transport_errors += 1
            if transport_errors > 10:
                raise
            print(f"    (transport error {transport_errors} while polling: "
                  f"{type(exc).__name__}; retrying)")
            sleep(3.0)
            continue
        st = last.get(key)
        if st in TERMINAL_OK or st in TERMINAL_BAD:
            return last
        sleep(3.0)
    raise TimeoutError(f"status never became terminal in {timeout_s}s; last={last.get(key)} "
                       f"reasons={last.get('statusReasons')}")


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

    baseline = cedar.baseline_permit()
    lint = cedar.check_statement(baseline)

    if args.dry_run:
        rid = args.run_id or "dryrun"
        print(f"Phase 2 step 3 — policy engine, run_id={rid}")
        print(f"  engine        grx_pe_{rid}        (UNDERSCORES: CreatePolicyEngine.name is "
              f"^[A-Za-z][A-Za-z0-9_]*$, max 48 — hyphens are rejected, unlike CreateGateway)")
        print(f"  policy        grx_pol_baseline_{rid}")
        print("  statement     (verbatim from our §3.1/§7.2/§8):")
        print(f"    {baseline}")
        print(f"  local lint    {lint or 'no known trap detected'}")
        print("  attempt 1     CreatePolicy WITHOUT validationMode  <- the document's path")
        print("  attempt 2     validationMode=IGNORE_ALL_FINDINGS   <- only if attempt 1 is "
              "rejected; the AWS getting-started guide's path")
        print(f"  rate limit    CreatePolicyEngine "
              f"{A.rate_limit_for('CreatePolicyEngine')}/s "
              f"({A.limit_provenance('CreatePolicyEngine')})")
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
    tags = A.tags_for(run_id, state.expires_at)

    store = EvidenceStore(run_id, "infra", "P2-03-policy-engine")
    store.write_environment()

    # UNDERSCORES, not hyphens, and validated against the SDK's own regex before any call.
    #
    # `CreatePolicyEngine` and `CreatePolicy` require `^[A-Za-z][A-Za-z0-9_]*$` (max 48) —
    # hyphens are REJECTED — while `CreateGateway`/`CreateGatewayTarget` take
    # `([0-9a-zA-Z][-]?){1,48}`, which allows them. One service, two grammars. `grx-pe-<runid>`
    # cost a live ValidationException to discover something the botocore service model had been
    # carrying all along, which is why `testbed.check_name` now reads the constraint from the
    # model rather than from a copy of the regex here (DEV-P2-02).
    #
    # This also explains the two pre-existing engines in this account being named
    # `agentcore_test_pe_*`: whoever built them hit the same wall.
    engine_name = T.check_name(ac, "CreatePolicyEngine", f"grx_pe_{run_id}")
    print(f"Phase 2 step 3 — policy engine {engine_name}, region={args.region}")

    # --- the engine -------------------------------------------------------
    existing = state.find("policy-engine", "main")
    engine_id = existing.ids.get("policy_engine_id") if existing else None

    if engine_id:
        print(f"  ledger already has engine {engine_id}; verifying live")
    else:
        # Read the output key off the operation's own shape rather than assuming a house
        # convention. This service model is genuinely inconsistent: ListPolicyEngines returns
        # `policyEngines`, ListPolicies returns `policies`, ListGateways returns `items`. An
        # earlier survey of this account read `.get("items")` from ListPolicyEngines, got None,
        # and reported "0 policy engines" while two ACTIVE engines existed.
        found = None
        token = None
        while True:
            kw = {"maxResults": 100}
            if token:
                kw["nextToken"] = token
            resp = ac.list_policy_engines(**kw)
            for row in resp.get("policyEngines") or []:
                if row.get("name") == engine_name:
                    found = row
                    break
            token = resp.get("nextToken")
            if found or not token:
                break
        if found:
            engine_id = found["policyEngineId"]
            print(f"  engine exists under our name: {engine_id} (status {found.get('status')})")
        else:
            A.limiter().wait("CreatePolicyEngine")
            rec = capture(store, "create_policy_engine", ac,
                          name=engine_name,
                          description="guardrails-doc-validation disposable policy engine",
                          tags=tags)
            rec.raise_for_status()
            engine_id = rec.response["policyEngineId"]
            print(f"  created engine {engine_id}  request-id {rec.request_id}")

    got = wait_status(ac.get_policy_engine, {"policyEngineId": engine_id})
    if got.get("status") not in TERMINAL_OK:
        print(f"FAIL: engine {engine_id} is {got.get('status')}: {got.get('statusReasons')}",
              file=sys.stderr)
        return 1
    print(f"  engine ACTIVE   {engine_id}")

    state.record(Resource(
        kind="policy-engine", logical="main", name=engine_name,
        service="bedrock-agentcore-control",
        delete_op="delete_policy_engine", delete_params={"policyEngineId": engine_id},
        ids={"policy_engine_id": engine_id},
        arn=got.get("policyEngineArn", ""), delete_priority=_ENGINE_PRIORITY,
        notes="the engine every gateway in this run points at. Its ARN is rebuilt at use "
              "time from the id via testbed.policy_engine_arn(), because the ledger stores "
              "ARNs account-masked and a masked ARN cannot be sent to an API.",
    ))

    # --- the baseline permit ---------------------------------------------
    # Same grammar as the engine — `CreatePolicy.name` carries the identical pattern.
    pol_name = T.check_name(ac, "CreatePolicy", f"grx_pol_baseline_{run_id}")
    existing_pol = state.find("policy", "baseline")
    if existing_pol and existing_pol.ids.get("policy_id"):
        pid = existing_pol.ids["policy_id"]
        live = ac.get_policy(policyEngineId=engine_id, policyId=pid)
        print(f"  policy exists   {pid} status={live.get('status')} "
              f"enforcementMode={live.get('enforcementMode')}")
        if live.get("status") in TERMINAL_BAD:
            print(f"FAIL: baseline policy {pid} is {live.get('status')}: "
                  f"{live.get('statusReasons')}. A CREATE_FAILED baseline permit means the "
                  f"engine has no permit at all, and in ENFORCE mode every benign request "
                  f"will be denied by Cedar's default-deny — which an arm would misread as "
                  f"a guardrail decision.", file=sys.stderr)
            return 1
        store.write_summary({"policy_engine_id": engine_id, "policy_id": pid,
                             "resumed": True})
        print(f"\nstate -> {state.write().name}")
        return 0

    if lint:
        print(f"FAIL: the document's own baseline statement fails local lint: {lint}",
              file=sys.stderr)
        return 1

    # Attempt 1: exactly what the document says, with no validationMode. See the docstring —
    # this call existing is the measurement, and its failure is a result rather than an error.
    A.limiter().wait("CreatePolicy")
    attempt1 = capture(store, "create_policy", ac,
                       name=pol_name, policyEngineId=engine_id,
                       definition={"cedar": {"statement": baseline}},
                       description="baseline permit exactly as our doc recommends; "
                                   "attempt 1 = no validationMode (the document's path)")
    dc1_reproduced: bool | None = None
    validation_mode_used: str | None = None

    if attempt1.ok:
        pid = attempt1.response["policyId"]
        print(f"  created policy  {pid} on the DOCUMENT'S path (no validationMode)  "
              f"request-id {attempt1.request_id}")
        # Not done yet: CreatePolicy can return 200 with the policy heading for CREATE_FAILED.
        # DC-1's policy is exactly that shape — a successful create followed by a failed
        # validation — so "the call succeeded" is not "the document's path works".
        live = wait_status(ac.get_policy,
                          {"policyEngineId": engine_id, "policyId": pid})
        if live.get("status") in TERMINAL_BAD:
            dc1_reproduced = True
            print(f"  DC-1 REPRODUCED: policy {pid} settled in {live.get('status')} with "
                  f"reasons {live.get('statusReasons')}. The document's baseline permit, "
                  f"sent as the document describes it, does not become ACTIVE.")
            A.limiter().wait("DeletePolicy")
            capture(store, "delete_policy", ac, policyEngineId=engine_id, policyId=pid)
            pid = None
        else:
            dc1_reproduced = False
            validation_mode_used = "(none)"
            print(f"  policy ACTIVE on the document's path — DC-1 NOT reproduced here. "
                  f"Phase 3's F1-3 decides whether the June 2026 CREATE_FAILED instance in "
                  f"this account was caused by something else.")
    else:
        dc1_reproduced = True
        pid = None
        print(f"  DC-1 REPRODUCED at the API: {attempt1.error_code}: "
              f"{attempt1.error_message} (request-id {attempt1.request_id})")

    if pid is None:
        # A DISTINCT name for attempt 2, because DeletePolicy releases the name asynchronously.
        #
        # Measured (DEV-P2-03): attempt 1 settled CREATE_FAILED, `delete_policy` returned 200,
        # and `create_policy` under the same name immediately after failed with
        # `ConflictException: Policy with the same name already exists` — while
        # `list_policies` on the engine returned ZERO rows. So the name outlives both the
        # delete's 200 and the policy's own visibility, and no amount of polling the *list*
        # can tell us when it is free: the resource we would be waiting on is already absent.
        #
        # Retrying the same name with backoff was the alternative, and it is worse: the wait
        # would be unbounded in principle, and on this path we are on the DC-1 branch, which
        # is a finding we want recorded promptly and unambiguously rather than behind a retry
        # loop whose failures look like the finding itself. A distinct suffix removes the
        # coupling entirely — and it makes the evidence clearer, since the two attempts are
        # then two separately addressable policy names in the archive rather than one name
        # with two histories.
        pol_name = T.check_name(ac, "CreatePolicy", f"{pol_name}_v2")
        A.limiter().wait("CreatePolicy")
        attempt2 = capture(store, "create_policy", ac,
                          name=pol_name, policyEngineId=engine_id,
                          definition={"cedar": {"statement": baseline}},
                          validationMode="IGNORE_ALL_FINDINGS",
                          description="baseline permit; attempt 2 = IGNORE_ALL_FINDINGS, "
                                      "the path the AWS getting-started guide uses and the "
                                      "one our document never mentions")
        attempt2.raise_for_status()
        pid = attempt2.response["policyId"]
        validation_mode_used = "IGNORE_ALL_FINDINGS"
        print(f"  created policy  {pid} with validationMode=IGNORE_ALL_FINDINGS  "
              f"request-id {attempt2.request_id}")
        live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
        if live.get("status") in TERMINAL_BAD:
            print(f"FAIL: even IGNORE_ALL_FINDINGS left policy {pid} in "
                  f"{live.get('status')}: {live.get('statusReasons')}", file=sys.stderr)
            return 1

    print(f"  policy {live.get('status')}  enforcementMode="
          f"{live.get('enforcementMode')}  validationMode={validation_mode_used}")

    state.record(Resource(
        kind="policy", logical="baseline", name=pol_name,
        service="bedrock-agentcore-control",
        delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_id": pid, "policy_engine_id": engine_id,
             "validation_mode_used": validation_mode_used,
             "enforcement_mode": live.get("enforcementMode"),
             "dc1_reproduced": dc1_reproduced,
             "statement": baseline},
        arn=live.get("policyArn", ""), delete_priority=_POLICY_PRIORITY,
        notes="the baseline permit. Without it an ENFORCE-mode engine denies ALL traffic by "
              "Cedar default-deny, so every later arm's benign control would fail for a "
              "reason unrelated to what the arm measures.",
    ))

    store.write_summary({
        "policy_engine_id": engine_id, "policy_id": pid,
        "dc1_reproduced": dc1_reproduced,
        "validation_mode_used": validation_mode_used,
        "note": "dc1_reproduced is a Phase 2 side observation, not F1-3's result: n=1, one "
                "validation mode, one engine. F1-3 runs the full arm set.",
    })
    print(f"\nstate -> {state.write().name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
