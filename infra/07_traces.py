#!/usr/bin/env python3
"""Phase 2 step 7: turn on gateway observability — via CloudWatch Logs *vended delivery*.

CORRECTION to an assumption this project carried until it was checked
---------------------------------------------------------------------
`infra/04_gateway.py`'s docstring says tracing is "not configured here" and that this script
enables it. The intent was right; the mechanism was wrong, and the wrong mechanism was written
into a docstring, so it is corrected here in the place that implements it:

* `CreateGateway`'s input shape is exactly `{name, description, clientToken, roleArn,
  protocolType, protocolConfiguration, authorizerType, authorizerConfiguration, kmsKeyArn,
  interceptorConfigurations, policyEngineConfiguration, exceptionLevel, tags}`. There is **no**
  tracing or observability member.
* `bedrock-agentcore-control` has **zero** operations matching Trac/Observ/Telem. There is no
  `UpdateGatewayObservability` to call and nothing for F7-5 to flip on the gateway itself.
* `observability-configure.html` states that for memory, gateways and built-in tools AgentCore
  "doesn't configure log destinations for you automatically". Enabling is a **CloudWatch Logs
  delivery** on the gateway's ARN:

      logs.put_delivery_source(name=…, resourceArn=<gateway arn>, logType="TRACES")
      logs.put_delivery_destination(name=…, deliveryDestinationType="XRAY")
      logs.create_delivery(deliverySourceName=…, deliveryDestinationArn=…)

  and, for logs, `logType="APPLICATION_LOGS"` → `deliveryDestinationType="CWL"` with
  `deliveryDestinationConfiguration={"destinationResourceArn": <log group arn>}`.

So F7-5's mutation is `delete_delivery` / `create_delivery` on the TRACES delivery, not an
`UpdateGateway`. That is a better experiment than the one originally planned — it flips exactly
one object and leaves the gateway configuration byte-identical, so "spans absent" cannot be
confounded with "the gateway changed".

Transaction Search is asserted, never enabled
---------------------------------------------
`xray.get_trace_segment_destination()` already returns `{"Destination": "CloudWatchLogs",
"Status": "ACTIVE"}` in this account. Enabling it is an account-wide setting that other systems
here depend on, so this script asserts and fails loudly instead. If it were ever INACTIVE,
spans would be absent for a reason that has nothing to do with our delivery, and F7-5's
"tracing off → no spans" arm would pass for the wrong reason.

Tracing goes on BOTH gateways, and that is a pairing decision
-------------------------------------------------------------
Span emission is work the service does per request. If `grx-gw` had tracing and
`grx-gw-nopolicy` did not, every F6 paired difference would contain the policy hops *plus* one
side's trace-emission cost, with no way to separate them after the fact. The pair is therefore
kept symmetric: identical deliveries on both. The XRAY destination is shared (a destination is
not resource-scoped); the CWL destinations are per-gateway because each names its own log group.

Ordering consequence, stated because it is easy to get wrong: F7-5 (Phase 4) turns tracing
**off** for one gateway and runs before F6 (Phase 6). Re-running this script `--ensure` is the
restoration gate — it is idempotent, and it exits non-zero unless both gateways have a live
TRACES delivery. Phase 6 must not start until it does.

Teardown coverage, measured rather than inferred from a constant
---------------------------------------------------------------
This paragraph used to say the opposite of the truth, and the correction is the point
(DEV-P2-07). It read that `lib/testbed.SWEEP_TYPE_FILTERS` omits `logs`, so the tag channel was
"structurally blind to every resource this script creates". `sweep_by_tag()` passes `TagFilters`
only and never passed `ResourceTypeFilters`, so that constant constrained nothing — and the
measurement is the reverse: **every one of this run's `logs` resources that can be cross-checked
is indexed, 9/9** (4 delivery-sources, 3 delivery-destinations, 2 log groups). The remaining 4
ledger rows are the deliveries, which record no ARN and so are unverifiable in either direction —
counted separately rather than folded into the numerator, because "13/13" would have been a
coverage claim about 4 resources nothing checked. The types actually missing from the index are
`iam-role` and `policy`, both of which the old list claimed were covered.

The tag channel is therefore load-bearing here in the ordinary way. `99_teardown.py`'s separate
`logs` sweep survives on two narrower reasons that the false one was masking: a **delivery
records no ARN** in the ledger (it is created and deleted by id), so the ARN-keyed cross-check
cannot see it on either channel; and `put_delivery_source`/`put_delivery_destination` accept
`tags` **only on the create path** (DEV-P2-06), so a resource left behind by a run that died
between the `put_*` and its `tag_resource` exists *untagged* — which no tag sweep can find,
however complete its index. The coverage number is printed and written to the summary on every
run, so it stays a measurement rather than a docstring. The account already holds 10 delivery
sources / 10 destinations / 10 deliveries, all belonging to `harness_*` runtimes and named
`<name>-traces-source` / `<name>-traces-xray-dest` / `<name>-cwl`. Ours are named under the run
id so they cannot collide, and none of theirs is read for anything but a collision check.

Cost
----
Span and log ingestion, plus storage. Our log group gets a 7-day retention policy so the
project's own logs cannot outlive the project; `aws/spans` retention (30 days) is not ours to
set. At the project's ~20,000 calls the ingestion is a few MB. **~$0.01**, reported rather than
rounded away.
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

# Deletion priorities, all BELOW the gateway's 30. A delivery source holds the gateway ARN, so
# the reference is removed before its referent even though the service may well tolerate the
# reverse order — teardown is not the place to find out.
_DELIVERY_PRIORITY = 22
_SOURCE_PRIORITY = 24
_DEST_PRIORITY = 26
_LOGGROUP_PRIORITY = 28

LOG_TYPES = {"traces": "TRACES", "applogs": "APPLICATION_LOGS"}

# 7 days. Long enough that a failed overnight arm can still be diagnosed the next morning,
# short enough that nothing we create outlives the 72 h resource TTL by more than a week if a
# teardown is ever missed.
RETENTION_DAYS = 7

# The shared `aws/spans` log group. Pre-existing, 30-day retention, NOT ours: every query
# against it must be filtered to our gateway ARN, or it returns other systems' spans.
SPANS_LOG_GROUP = "aws/spans"


def log_group_name(gateway_id: str) -> str:
    """The console's default vended-log group form, followed rather than invented.

    Matching the console's naming means a reader who enables this through the UI lands on the
    same group and can compare, which is the difference between evidence they can reproduce and
    evidence they must take on trust.
    """
    return f"/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/{gateway_id}"


def source_name(run_id: str, logical: str, kind: str) -> str:
    return f"grx-{logical}-{kind}-src-{run_id}"


def dest_name(run_id: str, logical: str, kind: str) -> str:
    return f"grx-{logical}-{kind}-dst-{run_id}"


def assert_transaction_search(xray, store) -> dict:
    """Assert, do not enable. Returns the destination config."""
    rec = capture(store, "get_trace_segment_destination", xray)
    rec.raise_for_status()
    d = rec.response
    if d.get("Destination") != "CloudWatchLogs" or d.get("Status") != "ACTIVE":
        raise RuntimeError(
            f"Transaction Search is Destination={d.get('Destination')} "
            f"Status={d.get('Status')}, not CloudWatchLogs/ACTIVE. Spans would be absent for a "
            f"reason unrelated to our delivery, which would make F7-5's 'tracing off -> no "
            f"spans' arm pass for the wrong reason. This script will NOT enable it: it is an "
            f"account-wide setting other systems in this account depend on.")
    return d


def existing_delivery(logs, source_nm: str) -> dict | None:
    """Find a delivery by its source name. `create_delivery` is not idempotent."""
    token = None
    while True:
        kw = {"limit": 50}   # NOT maxResults: the logs delivery ops take {limit, nextToken}
        if token:
            kw["nextToken"] = token
        resp = logs.describe_deliveries(**kw)
        for row in resp.get("deliveries") or []:
            if row.get("deliverySourceName") == source_nm:
                return row
        token = resp.get("nextToken")
        if not token:
            return None


def collision_check(logs, run_id: str, *, project: str = A.PROJECT_TAG) -> list[str]:
    """Names we are about to PUT that are in use by something **not ours**.

    `put_delivery_source` and `put_delivery_destination` are PUTs: they would silently
    reconfigure an existing delivery source rather than failing. The ten `harness_*` resources in
    this account are exactly the kind of thing that must not be reconfigured, so the check runs
    before any write, and it checks the names we are about to use rather than trusting the run-id
    suffix to be unique.

    Ownership is decided by TAG, not by name (DEV-P2-06)
    ---------------------------------------------------
    The first version returned every name that already existed, which conflated the two cases the
    guard has to separate: a stranger's resource under our name (must abort) and **our own**
    resource from an interrupted earlier attempt of this same run (must proceed — that is what
    `--ensure` means). `07_traces.py --ensure` failed part-way through its first live run, leaving
    5 of our own delivery resources in place, and the guard then refused every retry while
    reporting them as resources that must not be reconfigured. A name-based guard cannot tell those
    apart, and the failure mode is the expensive one: it blocks the resume path, so the tempting
    fix is to weaken or skip the guard that protects ten live `harness_*` resources.

    So a name in use is excused only when the resource carries this project's `Project` tag AND our
    `RunId`. Both, because `Project` alone would let a *concurrent* run's resources be overwritten,
    and `RunId` is what makes "ours" mean this run. `list_tags_for_resource` is the arbiter rather
    than the name string, and a tag read that fails is treated as NOT ours — fail closed, since a
    guard that cannot establish ownership must not grant it.
    """
    ours_planned = set()
    for logical in ("main", "nopolicy"):
        for kind in LOG_TYPES:
            ours_planned.add(source_name(run_id, logical, kind))
            ours_planned.add(dest_name(run_id, logical, kind))
    ours_planned.add(dest_name(run_id, "shared", "traces"))

    # name -> arn, for everything that exists now, so ownership can be read off the tags.
    existing: dict[str, str] = {}
    for op, key, coll in (("describe_delivery_sources", "deliverySources", "source"),
                          ("describe_delivery_destinations", "deliveryDestinations", "dest")):
        token = None
        while True:
            kw = {"limit": 50}   # NOT maxResults: the logs delivery ops take {limit, nextToken}
            if token:
                kw["nextToken"] = token
            r = getattr(logs, op)(**kw)
            for x in r.get(key) or []:
                if x.get("name"):
                    existing[x["name"]] = x.get("arn", "")
            token = r.get("nextToken")
            if not token:
                break

    foreign = []
    for name in sorted(ours_planned & set(existing)):
        arn = existing[name]
        if not arn:
            foreign.append(f"{name} (no ARN returned, so ownership cannot be established)")
            continue
        try:
            tags = logs.list_tags_for_resource(resourceArn=arn).get("tags") or {}
        except Exception as exc:                                   # noqa: BLE001
            foreign.append(f"{name} (tags unreadable: {type(exc).__name__} — treated as not ours)")
            continue
        if tags.get("Project") == project and tags.get("RunId") == run_id:
            continue                                               # our own, this run: resumable
        foreign.append(f"{name} (Project={tags.get('Project')!r} RunId={tags.get('RunId')!r})")
    return foreign


def ensure_log_group(logs, store, name: str, tags: dict) -> str:
    """Create the vended-log group with a bounded retention. Returns its ARN."""
    rec = capture(store, "create_log_group", logs, logGroupName=name, tags=tags)
    if not rec.ok and rec.error_code != "ResourceAlreadyExistsException":
        rec.raise_for_status()
    capture(store, "put_retention_policy", logs, logGroupName=name,
            retentionInDays=RETENTION_DAYS).raise_for_status()
    resp = logs.describe_log_groups(logGroupNamePrefix=name, limit=5)
    for g in resp.get("logGroups") or []:
        if g.get("logGroupName") == name:
            # The delivery destination wants a plain group ARN; describe_log_groups returns it
            # with a trailing `:*` on some paths, which PutDeliveryDestination rejects.
            return g["arn"].rstrip("*").rstrip(":")
    raise RuntimeError(f"created log group {name} but it does not appear in describe_log_groups")


def put_tagged(logs, store, op: str, *, name: str, tags: dict, **kw):
    """`put_delivery_*` with tags only when the resource does not already exist.

    Why this wrapper exists (DEV-P2-06)
    -----------------------------------
    `PutDeliverySource` and `PutDeliveryDestination` are create-**or-update**, and their `tags`
    member is accepted only on the create path:

        ConflictException: Tags can only be provided when a resource is being created,
                           not updated.

    Measured directly, both directions, on a source this script had just created: re-PUT **with**
    `tags` → ConflictException; re-PUT **without** → accepted. So the tag argument turns an
    otherwise idempotent PUT into one that fails on every subsequent call.

    That made `--ensure` non-idempotent for every delivery resource, and the shared XRAY
    destination is simply where it surfaced first: gateway `main` creates it, then gateway
    `nopolicy` PUTs the same name with the same tags in the same run, which is an update. The
    second-instance shape from `feedback_second_instance_bugs` — a templated loop whose first
    iteration creates and whose second must not.

    The fix is to decide by *existence* rather than by catching the conflict. `get_delivery_source`
    / `get_delivery_destination` take `{name}` only, so the probe is exact and cheap. Preferred over
    a retry-on-ConflictException because that message is not unique to this cause — `CreateDelivery`
    returns ConflictException for an existing delivery too — and a handler keyed on an error string
    would swallow a real conflict. Tags are then reconciled through `tag_resource`, which is the
    operation that *is* idempotent, so a resource that pre-dates this fix still ends up correctly
    tagged rather than being left untagged and invisible to the teardown sweep.
    """
    probe = {"put_delivery_source": "get_delivery_source",
             "put_delivery_destination": "get_delivery_destination"}[op]
    try:
        getattr(logs, probe)(name=name)
        exists = True
    except logs.exceptions.ResourceNotFoundException:
        exists = False
    rec = capture(store, op, logs, name=name, **({} if exists else {"tags": tags}), **kw)
    return rec, exists


def reconcile_tags(logs, store, arn: str, tags: dict) -> None:
    """Ensure `tags` are on `arn` regardless of which path created it.

    Needed because the create-time tag argument is skipped for an existing resource. `TagResource`
    is idempotent, so this runs unconditionally rather than only on the update path: a delivery
    resource created before this fix landed carries no tags at all, and an untagged resource is
    invisible to the teardown sweep — the one failure mode the tags exist to prevent.
    """
    rec = capture(store, "tag_resource", logs, resourceArn=arn, tags=tags)
    rec.raise_for_status()


def ensure_delivery(logs, store, *, source_nm: str, resource_arn: str, log_type: str,
                    dest_nm: str, dest_type: str, dest_config: dict | None,
                    tags: dict) -> tuple[dict, dict, dict]:
    """(source, destination, delivery) — idempotent. PUTs then a guarded create."""
    src, _ = put_tagged(logs, store, "put_delivery_source", name=source_nm, tags=tags,
                        resourceArn=resource_arn, logType=log_type)
    src.raise_for_status()
    reconcile_tags(logs, store, src.response["deliverySource"]["arn"], tags)

    kw = {"deliveryDestinationType": dest_type, "outputFormat": "json"}
    if dest_config:
        kw["deliveryDestinationConfiguration"] = dest_config
    dst, _ = put_tagged(logs, store, "put_delivery_destination", name=dest_nm, tags=tags, **kw)
    if not dst.ok and dst.error_code == "ValidationException" and dest_type == "XRAY":
        # An XRAY destination takes no outputFormat on some API versions. Retried once, with
        # the reason named, rather than sending the reduced shape blindly on every call — the
        # difference matters if a future version starts honouring it.
        kw.pop("outputFormat", None)
        dst, _ = put_tagged(logs, store, "put_delivery_destination", name=dest_nm, tags=tags, **kw)
    dst.raise_for_status()
    dest_arn = dst.response["deliveryDestination"]["arn"]
    reconcile_tags(logs, store, dest_arn, tags)

    found = existing_delivery(logs, source_nm)
    if found:
        return src.response["deliverySource"], dst.response["deliveryDestination"], found
    dlv = capture(store, "create_delivery", logs, deliverySourceName=source_nm,
                  deliveryDestinationArn=dest_arn, tags=tags)
    dlv.raise_for_status()
    return (src.response["deliverySource"], dst.response["deliveryDestination"],
            dlv.response["delivery"])


def query_spans(logs, gateway_arn: str, *, minutes: int = 15, limit: int = 50,
                extra_filter: str = "", timeout_s: int = 90) -> list[dict]:
    """Logs Insights over `aws/spans`, filtered to ONE gateway ARN. Reused by 08 and F7.

    The filter is not optional and is not a convenience: `aws/spans` is a pre-existing shared
    group carrying other systems' spans, so an unfiltered query returns rows that would read as
    our evidence. `Phase 0`'s note that this group "is not a clean baseline" is enforced here,
    in the one function every span read goes through.
    """
    now = int(time.time())
    q = (f'fields @timestamp, @message '
         f'| filter @message like "{gateway_arn}" ')
    if extra_filter:
        q += f"| {extra_filter} "
    q += f"| sort @timestamp desc | limit {limit}"
    start = logs.start_query(logGroupNames=[SPANS_LOG_GROUP],
                             startTime=now - minutes * 60, endTime=now, queryString=q)
    qid = start["queryId"]
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = logs.get_query_results(queryId=qid)
        st = r.get("status")
        if st == "Complete":
            return r.get("results") or []
        if st in ("Failed", "Cancelled", "Timeout"):
            raise RuntimeError(f"Logs Insights query {qid} ended {st}")
        time.sleep(1.5)
    logs.stop_query(queryId=qid)
    raise TimeoutError(f"Logs Insights query {qid} did not complete in {timeout_s}s")


def wait_for_span(logs, gateway_arn: str, *, timeout_s: int = 300,
                  minutes: int = 15) -> tuple[bool, float, list[dict]]:
    """Poll until at least one span for `gateway_arn` appears. Returns (found, seconds, rows).

    The elapsed time is returned rather than discarded because it is a *first observation* of
    the quantity F7-6 measures properly (publish lag, n=30, p50/p90/max). A single sample is
    not that measurement and must not be reported as it — but recording it costs nothing and
    tells the next phase whether its 300 s ceiling is anywhere near reality.
    """
    t0 = time.monotonic()
    deadline = t0 + timeout_s
    rows: list[dict] = []
    while time.monotonic() < deadline:
        rows = query_spans(logs, gateway_arn, minutes=minutes, limit=5)
        if rows:
            return True, time.monotonic() - t0, rows
        time.sleep(10.0)
    return False, time.monotonic() - t0, rows


def traces_delivery_live(logs, run_id: str, logical: str) -> bool:
    return existing_delivery(logs, source_name(run_id, logical, "traces")) is not None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ensure", action="store_true")
    ap.add_argument("--verify-only", action="store_true",
                    help="assert Transaction Search ACTIVE and both gateways' TRACES "
                         "deliveries live; create nothing. This is the gate Phase 6 runs "
                         "after F7-5 has mutated tracing.")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--ttl-hours", type=int, default=72)
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    args = ap.parse_args()

    if not (args.dry_run or args.ensure or args.verify_only):
        print("refusing to run: pass --dry-run, --ensure or --verify-only.", file=sys.stderr)
        return 2

    if args.dry_run:
        rid = args.run_id or "dryrun"
        print(f"Phase 2 step 7 — gateway observability via CloudWatch Logs vended delivery, "
              f"run_id={rid}")
        print("  precondition  xray.get_trace_segment_destination() == "
              "CloudWatchLogs/ACTIVE  (asserted, never enabled)")
        print("  per gateway (BOTH, so the F6 pair stays symmetric):")
        for logical in ("main", "nopolicy"):
            print(f"    {logical}")
            print(f"      TRACES         {source_name(rid, logical, 'traces')}"
                  f"  -> XRAY  {dest_name(rid, 'shared', 'traces')} (shared)")
            print(f"      APPLICATION_LOGS {source_name(rid, logical, 'applogs')}"
                  f"  -> CWL   {dest_name(rid, logical, 'applogs')}")
            print(f"      log group      {log_group_name(f'grx-gw-{rid}')}"
                  f"  retention={RETENTION_DAYS}d")
        print("  F7-5 mutation  delete_delivery / create_delivery on the TRACES delivery — "
              "the gateway config stays byte-identical, so 'spans absent' cannot be confounded "
              "with 'the gateway changed'")
        print("  teardown       these are `logs` resources and the tag sweep DOES index them "
              "(measured 13/13; the kinds it misses are iam-role and policy, see "
              "testbed.TAG_INDEX_BLIND_KINDS); 99_teardown.py also sweeps logs directly, as a "
              "second independent channel")
        print("\n--dry-run: no AWS call made.")
        return 0

    state = State.load(Path(args.state) if args.state else None) if (
        args.verify_only or args.state or not args.run_id) else None
    if state is None:
        expires = (datetime.now(timezone.utc)
                   + timedelta(hours=args.ttl_hours)).replace(microsecond=0).isoformat()
        state = State.load_or_new(args.run_id or new_run_id(), args.region, expires)
    run_id = state.run_id

    f = A.factory(args.region)
    logs = f.logs()
    xray = f.client("xray")
    account_id = A.account_id(f)

    store = EvidenceStore(run_id, "infra", "P2-07-traces")
    store.write_environment()

    print(f"Phase 2 step 7 — observability, run_id={run_id}, region={args.region}")
    ts = assert_transaction_search(xray, store)
    print(f"  txn search    {ts.get('Destination')}/{ts.get('Status')}  (asserted, unchanged)")

    if args.verify_only:
        live = {lg: traces_delivery_live(logs, run_id, lg) for lg in ("main", "nopolicy")}
        for lg, ok in live.items():
            print(f"  {lg:9s} TRACES delivery {'live' if ok else 'ABSENT'}")
        if not all(live.values()):
            print("FAIL: at least one gateway has no TRACES delivery. If F7-5 has run, its "
                  "restore did not complete; starting F6 now would put an unpaired "
                  "trace-emission cost into every paired difference.", file=sys.stderr)
            return 1
        print("  symmetric     both gateways emit spans — F6 pairing unaffected by tracing")
        return 0

    tags = A.tags_for(run_id, state.expires_at)

    clash = collision_check(logs, run_id)
    if clash:
        print(f"FAIL: these delivery names are in use by resources that are NOT ours and "
              f"PutDeliverySource/PutDeliveryDestination would OVERWRITE them: {clash}. This "
              f"account holds 10 delivery sources belonging to harness_* runtimes; none may be "
              f"reconfigured. Ownership is decided by the Project+RunId tags, so an existing "
              f"resource from an interrupted attempt of THIS run is not reported here — see "
              f"collision_check's docstring.", file=sys.stderr)
        return 1

    # The shared XRAY destination. One object for both gateways: a destination of type XRAY
    # carries no resource reference, so per-gateway copies would be two names for one thing and
    # two more rows for teardown to get right.
    shared_xray_nm = dest_name(run_id, "shared", "traces")

    for logical in ("main", "nopolicy"):
        gw = state.get("gateway", logical)
        gw_arn = T.unmask_arn(gw.arn, account_id)
        gid = gw.ids["gateway_id"]
        print(f"  {logical}")

        # --- TRACES -> X-Ray (this is what F7-5 flips) -------------------------------------
        src, dst, dlv = ensure_delivery(
            logs, store,
            source_nm=source_name(run_id, logical, "traces"), resource_arn=gw_arn,
            log_type=LOG_TYPES["traces"], dest_nm=shared_xray_nm, dest_type="XRAY",
            dest_config=None, tags=tags)
        print(f"    TRACES      {src['name']} -> XRAY {shared_xray_nm}  "
              f"delivery {dlv.get('id')}")

        state.record(Resource(
            kind="delivery-source", logical=f"{logical}-traces", name=src["name"],
            service="logs", delete_op="delete_delivery_source",
            delete_params={"name": src["name"]},
            ids={"log_type": LOG_TYPES["traces"], "gateway_id": gid},
            arn=src.get("arn", ""), delete_priority=_SOURCE_PRIORITY,
            notes="TRACES source on the gateway ARN. Deleted before the gateway (24 < 30) "
                  "because it holds a reference to it.",
        ))
        state.record(Resource(
            kind="delivery", logical=f"{logical}-traces", name=str(dlv.get("id")),
            service="logs", delete_op="delete_delivery",
            delete_params={"id": dlv.get("id")},
            ids={"delivery_id": dlv.get("id"),
                 "delivery_source_name": src["name"],
                 # Stored unmasked-source: Resource.to_json runs redact.mask over the whole
                 # row, so the account id in this ARN is masked on write like every other.
                 "delivery_destination_arn": dst["arn"],
                 "gateway_id": gid,
                 # F7-5 recreates this exact pair. Stored as the two names/ARNs it needs so the
                 # mutation is a data replay, not a rebuild from assumptions about our naming.
                 "f7_5_recreate": {"deliverySourceName": src["name"],
                                   "deliveryDestinationArn": dst["arn"]}},
            arn="", delete_priority=_DELIVERY_PRIORITY,
            notes="F7-5's mutation target: delete_delivery turns tracing OFF for this gateway "
                  "while leaving the gateway configuration byte-identical.",
        ))

        # --- APPLICATION_LOGS -> CloudWatch Logs -------------------------------------------
        lg_name = log_group_name(gid)
        lg_arn = ensure_log_group(logs, store, lg_name, tags)
        state.record(Resource(
            kind="log-group", logical=f"{logical}-applogs", name=lg_name, service="logs",
            delete_op="delete_log_group", delete_params={"logGroupName": lg_name},
            ids={"retention_days": RETENTION_DAYS, "gateway_id": gid},
            arn=lg_arn, delete_priority=_LOGGROUP_PRIORITY,
            notes=f"vended application logs, console default naming, {RETENTION_DAYS}d "
                  f"retention so our logs cannot outlive the project.",
        ))

        src2, dst2, dlv2 = ensure_delivery(
            logs, store,
            source_nm=source_name(run_id, logical, "applogs"), resource_arn=gw_arn,
            log_type=LOG_TYPES["applogs"],
            dest_nm=dest_name(run_id, logical, "applogs"), dest_type="CWL",
            dest_config={"destinationResourceArn": lg_arn}, tags=tags)
        print(f"    APP LOGS    {src2['name']} -> CWL {lg_name}  delivery {dlv2.get('id')}")

        state.record(Resource(
            kind="delivery-source", logical=f"{logical}-applogs", name=src2["name"],
            service="logs", delete_op="delete_delivery_source",
            delete_params={"name": src2["name"]},
            ids={"log_type": LOG_TYPES["applogs"], "gateway_id": gid},
            arn=src2.get("arn", ""), delete_priority=_SOURCE_PRIORITY, notes="",
        ))
        state.record(Resource(
            kind="delivery-destination", logical=f"{logical}-applogs", name=dst2["name"],
            service="logs", delete_op="delete_delivery_destination",
            delete_params={"name": dst2["name"]},
            ids={"destination_type": "CWL", "log_group": lg_name},
            arn=dst2["arn"], delete_priority=_DEST_PRIORITY, notes="",
        ))
        state.record(Resource(
            kind="delivery", logical=f"{logical}-applogs", name=str(dlv2.get("id")),
            service="logs", delete_op="delete_delivery",
            delete_params={"id": dlv2.get("id")},
            ids={"delivery_id": dlv2.get("id"), "delivery_source_name": src2["name"],
                 "gateway_id": gid},
            arn="", delete_priority=_DELIVERY_PRIORITY, notes="",
        ))
        state.write()

    # The shared XRAY destination, recorded ONCE and last: it is referenced by both gateways'
    # deliveries, so it must be deleted after both of them, which its priority (26) already
    # guarantees relative to the deliveries (22).
    dd = logs.get_delivery_destination(name=shared_xray_nm)["deliveryDestination"]
    state.record(Resource(
        kind="delivery-destination", logical="shared-traces", name=shared_xray_nm,
        service="logs", delete_op="delete_delivery_destination",
        delete_params={"name": shared_xray_nm},
        ids={"destination_type": "XRAY", "shared_by": ["main", "nopolicy"]},
        arn=dd["arn"], delete_priority=_DEST_PRIORITY,
        notes="one X-Ray destination serves both gateways: an XRAY destination carries no "
              "resource reference, so per-gateway copies would be two names for one thing.",
    ))

    # Symmetry, asserted rather than assumed from the loop having run twice — the loop's second
    # iteration could have hit an idempotent no-op path on a partially-built run.
    live = {lg: traces_delivery_live(logs, run_id, lg) for lg in ("main", "nopolicy")}
    if not all(live.values()):
        print(f"FAIL: TRACES deliveries are asymmetric across the pair: {live}. Every F6 "
              f"paired difference would carry one side's trace-emission cost.", file=sys.stderr)
        return 1
    print("  symmetric     both gateways emit spans — F6 pairing unaffected by tracing")

    # Tag coverage, measured on the resources we just made. This used to be reported as a blind
    # spot inferred from `SWEEP_TYPE_FILTERS`, a constant nothing applied; the measurement says
    # `logs` IS indexed (DEV-P2-07). Kept as a printed number rather than a claim in prose, so a
    # future change in the index shows up in the run output.
    #
    # Rows WITHOUT an ARN are counted separately instead of being filtered out. Filtering them was
    # how "13/13 indexed" hid the fact that `delivery` rows record no ARN at all: a resource with
    # no ARN in the ledger cannot be cross-checked against the sweep in either direction, which is
    # a gap in the cross-check itself and not a coverage success.
    swept = T.sweep_by_tag(f, run_id)
    swept_arns = {r["arn"] for r in swept}
    logs_rows = [r for r in state.resources.values() if r.service == "logs"]
    with_arn = [r for r in logs_rows if r.arn]
    no_arn = [f"{r.kind}/{r.logical}" for r in logs_rows if not r.arn]
    indexed = [r for r in with_arn if T.unmask_arn(r.arn, account_id) in swept_arns]
    print(f"  tag index     {len(indexed)}/{len(with_arn)} of our ARN-bearing `logs` resources "
          f"are visible to the tag sweep ({len(swept)} rows for this run)")
    if no_arn:
        # Not fatal: the ledger deletes a delivery by id, which it does record, so teardown works.
        # Printed because it bounds what the cross-check can prove, and an unstated bound reads
        # as full coverage.
        print(f"  cross-check   {len(no_arn)} ledger row(s) carry no ARN, so they cannot be "
              f"cross-checked against the sweep: {', '.join(no_arn)}. Teardown deletes these by "
              f"recorded id, so the gap is in the CHECK's reach, not in the delete path.")

    store.write_summary({
        "transaction_search": ts.get("Status"),
        "traces_symmetric": True,
        "shared_xray_destination": shared_xray_nm,
        "log_groups": [log_group_name(state.get("gateway", lg).ids["gateway_id"])
                       for lg in ("main", "nopolicy")],
        "retention_days": RETENTION_DAYS,
        "n_logs_resources": len(logs_rows),
        "n_logs_resources_tag_indexed": len(indexed),
        "mechanism": "cloudwatch-logs-vended-delivery (NOT a CreateGateway field)",
    })
    print(f"\nstate -> {state.write().name}")
    print("span visibility is asserted by infra/08_smoke.py, which makes the first billable "
          "call and then waits for a span carrying our gateway ARN.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
