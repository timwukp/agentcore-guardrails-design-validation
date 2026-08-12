#!/usr/bin/env python3
"""Phase 2 step 4: create the two gateways — `grx-gw-<runid>` and `grx-gw-nopolicy-<runid>`.

Both, in one script, because they are a **matched pair** and the pairing is the design. F6's
latency arms are analyzed by Wilcoxon signed-rank on paired differences, and the pairing is
only valid if the two gateways differ in exactly one field: `policyEngineConfiguration`. Two
scripts, or one script run twice with different arguments, would let `protocolConfiguration`,
`exceptionLevel` or the session timeout drift between them and silently confound every latency
difference with a configuration difference. Here the shared fields are built once, by
`base_kwargs()`, and the diff is asserted before either gateway is used.

Ordering: gateway before target
-------------------------------
`CreateGatewayTarget` requires `gatewayIdentifier`, so the gateway must exist first. That is
why this is step 4 and the target is step 5 — the reverse of what a "the Lambda is the target,
so register it first" reading would suggest.

`authorizerType=AWS_IAM`, and what it costs us
----------------------------------------------
Chosen so Cedar sees an `AgentCore::IamEntity` principal whose id is
`arn:aws:sts::<account>:assumed-role/<role>` (`policy-conditions.html`) — stable across
invocations, which `principal ==` matching requires. CUSTOM_JWT would need an IdP, and
`NONE` would remove the principal entirely and make every principal-scoped arm untestable.

The cost is that there is no boto3 operation to invoke a tool: all 66 `bedrock-agentcore`
data-plane operations were enumerated and none of them is a gateway invoke. Tool calls are
SigV4-signed MCP JSON-RPC POSTs to `gatewayUrl`, which `lib/mcp.py` implements. `gatewayUrl`
appears in `CreateGateway`/`GetGateway` output and in **no** list operation, which is one of
the three reasons Phase 2 keeps a state file at all.

`exceptionLevel="DEBUG"`
------------------------
The only value the enum offers. It makes the service return detailed error information, and
half this project's oracles are error responses: F5-4a asks whether a policy referencing a
nonexistent context path denies or allows, and the *reason* it gives is the finding. Without
DEBUG the answer could come back as an opaque 403 that cannot distinguish "the policy denied"
from "the policy could not be evaluated". Note this is set on BOTH gateways, so it cannot
become a latency confound — an extra error path costs nothing on the success path, but the
paired design does not require us to argue that.

Tracing
-------
Not configurable here, and that turned out to be a fact about the API rather than a choice of
ours. `bedrock-agentcore-control` has **zero** operations or shape members matching Trac/Observ/
Telem: tracing on a gateway is a CloudWatch Logs **vended delivery**, i.e. a separate triple of
`PutDeliverySource(resourceArn=<gateway arn>, logType="TRACES")` → `PutDeliveryDestination(
deliveryDestinationType="XRAY")` → `CreateDelivery`. `07_traces.py` owns that mechanism.

The consequence is good for F7-5. Because the delivery is its own object, the mutation is
`DeleteDelivery`/`CreateDelivery` on the TRACES delivery, which flips exactly one thing and
leaves this gateway's configuration byte-identical — so "spans absent for our ARN" cannot be
confounded with "the gateway changed". Had tracing been an `UpdateGateway` field, the mutation
would have had to rewrite the gateway and would have carried that confound.

Nothing about tracing is therefore set at create time, which also keeps F7-5's baseline intact.

Rate limit and cost
-------------------
`CreateGateway`/`UpdateGateway` are 5/s. A gateway has no per-hour charge; the billable events
are tool invocations and policy evaluations. This step is **$0**; the end-to-end benign call in
`08_smoke.py` is the first billable request.
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
import testbed as T                                               # noqa: E402
from evidence import EvidenceStore, capture, new_run_id            # noqa: E402
from testbed import Resource, State                                # noqa: E402

_GATEWAY_PRIORITY = 30

TERMINAL_OK = {"READY"}
TERMINAL_BAD = {"FAILED", "UPDATE_UNSUCCESSFUL", "DELETING"}

# Both gateways start in the mode the truth-table work needs as its baseline. ENFORCE, not
# LOG_ONLY: an ENFORCE engine plus the baseline permit from step 3 is the configuration a
# reader following §3.1 ends up with, and it is the only mode in which a deny is observable
# end to end. F4 varies this field per arm via UpdateGateway; LOG_ONLY arms set it there.
DEFAULT_MODE = "ENFORCE"

# 900 s. Long enough that no arm's session expires mid-run (F6's longest arm is ~40 min but
# each trial is its own session), short enough that abandoned sessions from a killed run do
# not linger past the 72 h resource TTL. Identical on both gateways.
SESSION_TIMEOUT_S = 900

# The F6 pairing assertion's ignore list, defined ONCE here and imported by 06_verify.py.
#
# The admission rule, and it is narrow: a field belongs here only if it CANNOT be equal for two
# distinct gateways — service-assigned identity, or a timestamp. A field that merely happens to
# differ today does not qualify, because ignoring it is how a pairing assertion silently stops
# asserting: the F6 paired difference would then carry an unknown configuration bias that looks
# internally consistent in both arms and is invisible in the results.
#
# `workloadIdentityDetails` qualifies on measured evidence, not on the plausibility of the name.
# The two ARNs were compared field by field: the prefix
# `…:workload-identity-directory/default/workload-identity` is byte-identical across the pair and
# the final segment is exactly the gateway id, so the value is a restatement of `gatewayId` —
# already ignored — in ARN form.
#
# Defined as a constant rather than written out at both call sites because it previously WAS
# written out twice: `04_gateway.py` and `06_verify.py` each carried a literal, so adding this
# field to one left the other asserting on it. That is not a hypothetical — the verifier would
# have failed on `workloadIdentityDetails` immediately after 04's pair check passed, and the
# obvious reading of that ("the verifier disagrees with the creator") is wrong and expensive.
PAIR_IGNORE = ("name", "description", "gatewayArn", "gatewayId", "gatewayUrl", "createdAt",
               "updatedAt", "status", "statusReasons", "ResponseMetadata",
               "workloadIdentityDetails",
               # The one field the pair is DESIGNED to differ in. Ignored here because
               # `diff_configs` is asked "does anything ELSE differ"; the mode itself is
               # asserted separately, per gateway, by 06_verify.py.
               "policyEngineConfiguration")


def base_kwargs(name: str, role_arn: str, description: str) -> dict:
    """Every field shared by the two gateways. The ONLY difference is added by the caller.

    Kept as one function rather than two literals so the paired design is enforced by
    construction: a field added here appears on both gateways or on neither, and F6's paired
    difference stays attributable to `policyEngineConfiguration` alone.
    """
    return {
        "name": name,
        "description": description,
        "roleArn": role_arn,
        "protocolType": "MCP",
        "protocolConfiguration": {
            "mcp": {
                "sessionConfiguration": {"sessionTimeoutInSeconds": SESSION_TIMEOUT_S},
                # Explicitly disabled. Response streaming would make a latency measurement
                # ambiguous — time-to-first-byte and time-to-last-byte are different
                # quantities, and §6.1's rows do not say which one they mean. With streaming
                # off there is one duration to measure.
                "streamingConfiguration": {"enableResponseStreaming": False},
            },
        },
        "authorizerType": "AWS_IAM",
        "exceptionLevel": "DEBUG",
    }


def diff_configs(a: dict, b: dict, *, ignore: tuple[str, ...] = ()) -> list[str]:
    """Fields that differ between two live gateway configurations.

    Used as an assertion, not a report: the paired latency design requires the two gateways to
    differ in `policyEngineConfiguration` and nothing else. A silent second difference would
    bias every paired difference by an unknown amount, and the bias would be invisible in the
    results because both arms would look internally consistent.
    """
    keys = (set(a) | set(b)) - set(ignore)
    out = []
    for k in sorted(keys):
        va, vb = a.get(k), b.get(k)
        if json.dumps(va, sort_keys=True, default=str) != \
           json.dumps(vb, sort_keys=True, default=str):
            out.append(f"{k}: {va!r} != {vb!r}")
    return out


def workload_identity_is_pure_identity(live: dict[str, dict],
                                       gateway_ids: dict[str, str]) -> list[str]:
    """Check that `workloadIdentityDetails` really is a restatement of the gateway id.

    This is the discharge of `PAIR_IGNORE`'s admission rule for that field, and it exists because
    the alternative was a comment. `workloadIdentityDetails` is the one entry in the ignore list
    whose "cannot be equal across a pair" status is a claim about service behaviour rather than a
    tautology like `gatewayArn`, so the claim is tested on every run instead of being asserted
    once by me and trusted thereafter: if the service ever puts a *configuration* value in this
    structure — a directory name, a mode, an auth setting — ignoring the field would start hiding
    a real difference, and nothing else in the pipeline would notice.

    The two properties, both measured on the live pair before this was written:
      1. every ARN's prefix up to the last `/` is byte-identical across the pair, so the only
         varying part is the final segment;
      2. that final segment is exactly the gateway's own id, which `PAIR_IGNORE` already covers
         as `gatewayId`.

    Together they mean the field carries no information the pair check would otherwise compare.
    Returns a list of problems, empty when the field is pure identity — the caller treats a
    non-empty list as fatal, because "ignored on grounds that no longer hold" is worse than a
    plain difference: the pair check would keep reporting valid.
    """
    problems: list[str] = []
    prefixes: dict[str, str] = {}
    for logical, cfg in live.items():
        details = cfg.get("workloadIdentityDetails")
        if not isinstance(details, dict):
            problems.append(f"{logical}: workloadIdentityDetails is {type(details).__name__}, "
                            f"not a dict — the ignore justification assumed one ARN field")
            continue
        # Not `details["workloadIdentityArn"]` — an ADDED key is exactly the drift this guards
        # against, so the whole structure is checked, not the one field I expect.
        extra = set(details) - {"workloadIdentityArn"}
        if extra:
            problems.append(
                f"{logical}: workloadIdentityDetails gained {sorted(extra)}. The field is "
                f"ignored by PAIR_IGNORE on the grounds that it holds only an identity ARN; a "
                f"new key could be configuration, and ignoring it would hide a real difference")
        arn = details.get("workloadIdentityArn") or ""
        if "/" not in arn:
            problems.append(f"{logical}: workloadIdentityArn {arn!r} has no '/' to split on")
            continue
        prefix, _, tail = arn.rpartition("/")
        prefixes[logical] = prefix
        want = gateway_ids.get(logical, "")
        if tail != want:
            problems.append(
                f"{logical}: workloadIdentityArn's last segment is {tail!r} but the gateway id "
                f"is {want!r}. The field is only ignorable because it restates gatewayId; a "
                f"segment that is something else may be a value the pair check should compare")
    distinct = set(prefixes.values())
    if len(distinct) > 1:
        problems.append(
            f"the workload-identity ARN prefixes differ across the pair: {sorted(distinct)}. "
            f"Only the final segment may vary; a differing prefix means the two gateways sit in "
            f"different workload-identity directories, which is a configuration difference and "
            f"must not be ignored")
    return problems


def wait_ready(ac, gateway_id: str, *, timeout_s: int = 300, sleep=time.sleep) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    transport_errors = 0
    while time.monotonic() < deadline:
        try:
            last = ac.get_gateway(gatewayIdentifier=gateway_id)
        except Exception as exc:                      # noqa: BLE001
            transport_errors += 1
            if transport_errors > 10:
                raise
            print(f"    (transport error {transport_errors}: {type(exc).__name__}; retrying)")
            sleep(3.0)
            continue
        st = last.get("status")
        if st in TERMINAL_OK or st in TERMINAL_BAD:
            return last
        sleep(4.0)
    raise TimeoutError(
        f"gateway {gateway_id} never reached a terminal status in {timeout_s}s; last="
        f"{last.get('status')} reasons={last.get('statusReasons')}")


def find_by_name(ac, name: str) -> dict | None:
    """Look up a gateway by our name. NOTE: ListGateways' response key is `items`.

    Not `gateways`, and not the `policyEngines` that ListPolicyEngines uses. The keys are
    inconsistent per operation within this one service model, and reading the wrong one returns
    None, which iterates as empty and reports "not found" — a false negative that would make
    this script create a second gateway on every run.
    """
    token = None
    while True:
        kw = {"maxResults": 100}
        if token:
            kw["nextToken"] = token
        resp = ac.list_gateways(**kw)
        for row in resp.get("items") or []:
            if row.get("name") == name:
                return row
        token = resp.get("nextToken")
        if not token:
            return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--ttl-hours", type=int, default=72)
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--mode", default=DEFAULT_MODE, choices=["ENFORCE", "LOG_ONLY"])
    args = ap.parse_args()

    if not args.dry_run and not args.ensure:
        print("refusing to run: pass --dry-run or --ensure.", file=sys.stderr)
        return 2

    if args.dry_run:
        rid = args.run_id or "dryrun"
        kw = base_kwargs(f"grx-gw-{rid}", "<role arn from the ledger>", "…")
        print(f"Phase 2 step 4 — gateways, run_id={rid}")
        print(f"  policy gw     grx-gw-{rid}          "
              f"policyEngineConfiguration.mode={args.mode}")
        print(f"  baseline gw   grx-gw-nopolicy-{rid}  policyEngineConfiguration=<absent>")
        print("  shared config (identical on both, so the F6 pair differs in ONE field):")
        for k, v in kw.items():
            if k in ("name", "description", "roleArn"):
                continue
            print(f"    {k:24s} {json.dumps(v)}")
        print("  tracing       not a gateway field at all — it is a CloudWatch Logs vended "
              "delivery (PutDeliverySource/Destination + CreateDelivery), owned by 07_traces.py; "
              "F7-5 mutates the TRACES delivery, leaving this config byte-identical")
        print(f"  rate limit    CreateGateway {A.rate_limit_for('CreateGateway')}/s "
              f"({A.limit_provenance('CreateGateway')})")
        print("\n--dry-run: no AWS call made.")
        return 0

    run_id = args.run_id or new_run_id()
    expires = (datetime.now(timezone.utc)
               + timedelta(hours=args.ttl_hours)).replace(microsecond=0).isoformat()

    f = A.factory(args.region)
    ac = f.agentcore_control()
    account_id = A.account_id(f)

    state = State.load_or_new(run_id, args.region, expires,
                             path=Path(args.state) if args.state else None)
    run_id = state.run_id
    tags = A.tags_for(run_id, state.expires_at)

    store = EvidenceStore(run_id, "infra", "P2-04-gateway")
    store.write_environment()

    # Prerequisites, read from the ledger and never guessed. `State.get` raises with the list
    # of what IS present, because a guessed name that happened to match another run's resource
    # would attribute that resource's behaviour to this run.
    gw_role = state.get("iam-role", "gw-exec")
    engine = state.get("policy-engine", "main")
    engine_id = engine.ids["policy_engine_id"]
    # Rebuilt from the id, not unmasked from the stored ARN: this value is SENT to the API, and
    # reconstructing from the caller's own account cannot silently carry another account's id.
    engine_arn = T.policy_engine_arn(args.region, account_id, engine_id)
    role_arn = T.unmask_arn(gw_role.arn, account_id)

    baseline_pol = state.find("policy", "baseline")
    if baseline_pol is None:
        print("FAIL: no policy/baseline in the ledger. An ENFORCE engine with no permit "
              "denies ALL traffic via Cedar default-deny, so this gateway would be created "
              "in a state where every benign control fails for a reason unrelated to what "
              "any arm measures. Run infra/03_policy_engine.py --ensure first.",
              file=sys.stderr)
        return 1

    print(f"Phase 2 step 4 — gateways, run_id={run_id}, region={args.region}")
    print(f"  role          {gw_role.name}")
    print(f"  engine        {engine_id}  mode={args.mode}")

    plan = [
        ("main", f"grx-gw-{run_id}",
         {"policyEngineConfiguration": {"arn": engine_arn, "mode": args.mode}},
         "policy-engine gateway: the configuration a reader following §3.1 ends up with"),
        ("nopolicy", f"grx-gw-nopolicy-{run_id}", {},
         "paired latency baseline: identical to grx-gw except that it has NO policy engine, "
         "so an F6 paired difference isolates the policy/guardrail hops"),
    ]

    live: dict[str, dict] = {}
    for logical, name, extra, purpose in plan:
        rec_existing = state.find("gateway", logical)
        gid = rec_existing.ids.get("gateway_id") if rec_existing else None
        if not gid:
            found = find_by_name(ac, name)
            gid = found.get("gatewayId") if found else None
            if gid:
                print(f"  {logical:9s} exists under our name: {gid}")

        if not gid:
            kw = base_kwargs(name, role_arn, purpose[:200])
            kw.update(extra)
            kw["tags"] = tags
            A.limiter().wait("CreateGateway")
            rec = capture(store, "create_gateway", ac, **kw)
            rec.raise_for_status()
            gid = rec.response["gatewayId"]
            print(f"  {logical:9s} created {gid}  request-id {rec.request_id}")

        got = wait_ready(ac, gid)
        if got.get("status") not in TERMINAL_OK:
            print(f"FAIL: gateway {name} is {got.get('status')}: {got.get('statusReasons')}",
                  file=sys.stderr)
            return 1
        live[logical] = got

        url = got.get("gatewayUrl", "")
        if not url:
            # Fatal rather than a warning: gatewayUrl appears in no list operation, so a
            # gateway recorded without it cannot be invoked by any later phase and cannot be
            # recovered by re-listing. Better to fail here, where the cause is visible.
            print(f"FAIL: gateway {name} came back READY with no gatewayUrl. Every tool call "
                  f"is a SigV4 POST to that URL and it appears in no list operation, so a "
                  f"ledger entry without it is unusable.", file=sys.stderr)
            return 1

        pec = got.get("policyEngineConfiguration") or {}
        print(f"  {logical:9s} READY   policyEngineConfiguration="
              f"{pec.get('mode') or 'absent'}")

        state.record(Resource(
            kind="gateway", logical=logical, name=name,
            service="bedrock-agentcore-control",
            delete_op="delete_gateway", delete_params={"gatewayIdentifier": gid},
            ids={
                "gateway_id": gid,
                # Stored because it is required to invoke and derivable from nothing.
                "gateway_url": url,
                "authorizer_type": got.get("authorizerType"),
                "exception_level": got.get("exceptionLevel"),
                "session_timeout_s": SESSION_TIMEOUT_S,
                # The relationship F5-2 must restore *exactly* after mutating it. Recorded as
                # the engine id plus the mode, not as the ARN: the ARN is rebuilt from the id
                # and the caller's account at use time.
                "policy_engine_id": engine_id if logical == "main" else None,
                "policy_engine_mode": pec.get("mode"),
                "protocol_configuration": got.get("protocolConfiguration"),
                "role_arn_masked_source": gw_role.name,
            },
            arn=got.get("gatewayArn", ""), delete_priority=_GATEWAY_PRIORITY,
            notes=purpose,
        ))

    # The pairing assertion. `policyEngineConfiguration` is expected to differ; anything else
    # differing means the F6 paired design is invalid, and it is better to know now than to
    # discover it as an unexplained median shift after 16,000 calls. See PAIR_IGNORE for what is
    # excluded and the rule that admits an entry there.
    #
    # First the one ignored field whose exclusion rests on service behaviour rather than on a
    # tautology. Checked BEFORE the diff, so a failure reads as "the justification for ignoring
    # workloadIdentityDetails no longer holds" rather than as a pairing failure.
    wid_problems = workload_identity_is_pure_identity(
        live, {lg: state.get("gateway", lg).ids["gateway_id"] for lg in ("main", "nopolicy")})
    if wid_problems:
        print("FAIL: PAIR_IGNORE excludes workloadIdentityDetails on the measured grounds that "
              "it only restates the gateway id, and that no longer holds:", file=sys.stderr)
        for p in wid_problems:
            print(f"       - {p}", file=sys.stderr)
        return 1
    print("  ignore check  workloadIdentityDetails is identity only (shared prefix, tail == "
          "gatewayId), so excluding it from the pair check hides nothing")

    extra_diffs = diff_configs(live["main"], live["nopolicy"], ignore=PAIR_IGNORE)
    if extra_diffs:
        print("FAIL: the two gateways differ in more than policyEngineConfiguration, so a "
              "paired F6 difference would not isolate the policy hops:", file=sys.stderr)
        for d in extra_diffs:
            print(f"       - {d}", file=sys.stderr)
        return 1
    print("  pair check    identical except policyEngineConfiguration  (F6 pairing valid)")

    # The tag-index question the ledger's docstring leaves open, answered now. Before this run
    # the account held six gateways, all untagged, and the tagging API indexed zero resources
    # of type `gateway` — which does not distinguish "gateways are not indexed" from "no
    # tagged gateway has ever existed here". We have just created two tagged ones, so the
    # lookup is now decisive, and the answer changes what 99_teardown.py may conclude.
    swept = T.sweep_by_tag(f, run_id)
    gw_arns = {r["arn"] for r in swept if r["type"] == "gateway"}
    ours = {T.unmask_arn(state.get("gateway", lg).arn, account_id) for lg in ("main",
                                                                             "nopolicy")}
    if ours <= gw_arns:
        print(f"  tag index     gateways ARE indexed ({len(gw_arns)} found by tag) — the "
              f"teardown sweep can prove zero gateway survivors")
        indexed = True
    else:
        missing = sorted(ours - gw_arns)
        print(f"  tag index     gateways are NOT indexed by resourcegroupstaggingapi: "
              f"{len(missing)} of our 2 tagged gateways are absent from the sweep. This is a "
              f"FINDING, not a failure: it means the teardown's tag channel structurally "
              f"cannot prove zero gateway survivors, and the ledger channel is load-bearing "
              f"for that type.")
        indexed = False

    store.write_summary({
        "gateways": {lg: state.get("gateway", lg).ids["gateway_id"]
                     for lg in ("main", "nopolicy")},
        "mode": args.mode,
        "pair_identical_except_policy_engine": True,
        "gateways_indexed_by_tagging_api": indexed,
        "n_tag_indexed_gateways": len(gw_arns),
    })
    print(f"\nstate -> {state.write().name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
