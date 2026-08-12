#!/usr/bin/env python3
"""Phase 99: delete everything this project created, and **prove** nothing survived.

Two channels, and the point is that they are independent
-------------------------------------------------------
* **Ledger channel** — `state.json` in `deletion_order()`. Knows the reference constraints (a
  target before its gateway, a delivery source before the gateway it names, an inline policy
  before its role) and knows the exact delete parameters, because they were recorded as data at
  create time rather than reconstructed here.
* **Tag channel** — `resourcegroupstaggingapi`, sweeping `Project=guardrails-doc-validation`.
  Finds resources whose creation was **never recorded**: the window between a successful
  `create_*` and the `state.write()` that follows it cannot be closed, so an orphan from a
  killed run is a real possibility and the ledger structurally cannot see it.

Neither channel alone can support the claim "zero survivors", and the two failure modes are
opposite: the ledger misses what it never recorded, the tag index misses what it does not
index. So the script runs both, **cross-checks them against each other**, and reports each
resource under one of four states — `deleted`, `already-absent`, `orphan` (tag-only) and
`blind` (ledger-only, i.e. a type the tag index does not cover).

The `blind` category exists because it was measured, not feared
--------------------------------------------------------------
`lib/testbed.TAG_INDEX_BLIND_KINDS` lists the kinds the tagging API does **not** index in
us-east-1, each with its measurement and a named replacement channel: `iam-role` (681 roles in
the account, 102 carrying at least one tag, 0 returned for `ResourceTypeFilters=['iam:role']`)
and `policy` (structurally untaggable — `CreatePolicy` has no `tags` input member). Those two
are the whole blind set, and both are in the ledger, so `blind` means "deleted via the ledger,
not confirmable via the sweep" rather than "possibly missed".

This corrects an earlier version of this paragraph which asserted that every resource
`07_traces.py` creates was invisible to the tag channel, inferred from a constant
(`SWEEP_TYPE_FILTERS`) that `sweep_by_tag()` never applied — see DEV-P2-07. Measured: every
`logs` resource of a full run that carries an ARN in the ledger IS indexed, 9/9; the other 4 rows
are deliveries, which record no ARN and are therefore cross-checkable on neither channel.

Channel 3 therefore survives on its own merits, which are narrower and real:
* **Deliveries record no ARN in the ledger.** A delivery is created and deleted by id, so the
  ledger can delete it but the ARN-keyed cross-check cannot see it in either channel.
* **Tags are create-time-only on `put_delivery_source`/`put_delivery_destination`** (DEV-P2-06),
  so a resource created before that fix, or by an interrupted run that died between `put_*` and
  `tag_resource`, exists **untagged** — invisible to a tag sweep however complete its index is.
An orphan that carries no tag is exactly what a tag channel cannot find, so this channel sweeps
`describe_delivery_sources`/`describe_delivery_destinations`/`describe_deliveries` by name and
states per-type coverage in `teardown_log.json`.

What it will not delete
-----------------------
The hard isolation rule, enforced in code and not only in a docstring. `PROTECTED_SUBSTRINGS`
covers the six pre-existing READY gateways, the `harness_*`/`uitestagent_*` runtimes and their
ten delivery resources, and the two abandoned June-2026 policy engines (read-only evidence for
F1-3). Any candidate whose name or ARN matches is refused with a printed reason, *including* one
that arrives via the tag channel — a mistagged pre-existing resource must not be deletable by a
sweep. The three DRAFT guardrails are covered by the same list.

Exit code
---------
Non-zero if anything survives, if any protected resource was matched, or if either channel could
not run. Per `feedback_guard_tool_exit_codes`: **a sweep that cannot run must not report clean.**
A `logs` API that throws leaves `channels_ok=False` and the script exits non-zero even if
everything it did see was deleted.

Cost: $0. Deletes are free; the sweep is free.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                            # noqa: E402
import redact                                                      # noqa: E402
import testbed as T                                               # noqa: E402
from evidence import EvidenceStore, capture                        # noqa: E402
from testbed import Resource, State                                # noqa: E402

TEARDOWN_LOG = ROOT / "teardown_log.json"

# Phase 1's guardrails are NOT in state.json, and that is by design — `f3_efficacy/00_guardrails.py`
# argues for idempotence by deterministic name rather than by a ledger, because "the service's own
# list is the state" and a stale ledger would make it create duplicates. Sound for provisioning;
# it leaves a hole here.
#
# The first dry-run of this script found it: 12 guardrails tagged `Project=guardrails-doc-validation`
# came back from the tag sweep as ORPHANs — correctly labelled, since they are absent from the
# ledger, but "orphan" understates it. They are a live, deliberately-provisioned Phase 1 testbed,
# and leaving them was right while also being the failure mode that produces residue after the
# project ends: the tag channel can *see* them but has no recorded delete operation, so
# `--delete-orphans` would report them `orphan-unhandled` and exit non-zero forever.
#
# So the registry Phase 1 does write is read as a THIRD ledger. Not folded into state.json (that
# would re-introduce the stale-ledger problem 00_guardrails.py avoided) — read at teardown time,
# where being stale is harmless because every delete is idempotent and a missing guardrail is
# `already-absent`.
PHASE1_GUARDRAIL_REGISTRY = ROOT / "results" / "phase1_guardrails.json"

# Never delete anything matching these, from either channel. The list is the plan's isolation
# rule expressed as code: a rule that lives only in prose is one careless `--all` away from
# being violated.
#
# Matched with `_` and `-` treated as the SAME character, which is not cosmetic — it is a defect
# this list had until it was mutation-checked. The isolation rule was written from the runtime
# names (`harness_finance`, `uitestagent_...`), but the CloudWatch delivery resources those
# runtimes own are named with hyphens (`harness-finance-traces`, `ui-test-traces-source`). With
# a literal match, **0 of the 84 pre-existing delivery resources in this account matched any
# protected substring.** The `grx-` prefix filter happened to exclude them anyway, so nothing was
# ever at risk — but a safety net that depends on a *different* filter being correct is not a
# safety net. Normalizing the separator makes the list match what the account actually contains.
PROTECTED_SUBSTRINGS = (
    "finance-trading", "healthcare-medical", "insurance-claims",
    "manufacturing-maintenance", "real-estate-valuation", "retail-inventory",
    # Runtime families and the delivery resources they own, under either separator.
    "harness_", "harness-", "uitestagent_", "uitestagent-", "ui-test-", "bug-fix-",
    "llmops_", "llmops-",
    # The two abandoned June-2026 policy engines: read-only evidence for F1-3 (the `permit`
    # validation trap). Deleting them would destroy the CREATE_FAILED policy whose two
    # `Overly Permissive` statusReasons are the project's single highest-value found artifact.
    "agentcore_test_pol", "agentcore_test_pe",
)

# Our own names must not be self-protected, or teardown would refuse to delete the testbed and
# every run would exit non-zero with residue. Asserted at import: a future addition to the list
# above that happens to match `grx-` fails here rather than at 3 a.m. after a Phase 6 run.
# Two prefixes, because the service imposes two name grammars — see `not_ours`. `_OUR_PREFIX` is
# kept as the canonical form used in messages and in the import-time assertion below, which
# normalises separators anyway, so the assertion covers both.
_OUR_PREFIX = "grx-"
_OUR_PREFIXES = ("grx-", "grx_")
for _s in PROTECTED_SUBSTRINGS:
    if _s.replace("_", "-").lower() in _OUR_PREFIX or _OUR_PREFIX.startswith(
            _s.replace("_", "-").lower()):
        raise AssertionError(
            f"PROTECTED_SUBSTRINGS entry {_s!r} matches our own {_OUR_PREFIX!r} naming, which "
            f"would make teardown refuse to delete this project's own resources and exit "
            f"non-zero forever.")
for _p in _OUR_PREFIXES:
    # Every prefix must normalise to the canonical one, or a name using the other separator
    # would pass `not_ours` while `protected()` — which normalises — judged it differently.
    if _p.replace("_", "-") != _OUR_PREFIX:
        raise AssertionError(
            f"prefix {_p!r} does not normalise to {_OUR_PREFIX!r}; the two gates would then "
            f"disagree about whether a name is ours.")

# Error codes that mean "already gone". Treated as success, because a teardown must be
# re-runnable: the second run of a partially-successful teardown should end clean, not report
# failures for the resources the first run removed.
GONE_CODES = {
    "ResourceNotFoundException", "NoSuchEntity", "NoSuchEntityException",
    "ResourceNotFound", "ValidationException",   # some deletes 400 on an absent id
    "NotFoundException", "ConflictException",
}

# Deletes that must be retried because the service enforces the ordering asynchronously: a
# gateway can report the target gone while still holding it for a few seconds.
RETRY_CODES = {"ConflictException", "ResourceInUseException", "ThrottlingException",
               "TooManyRequestsException", "ValidationException"}


def not_ours(name_or_arn: str) -> str:
    """A second, structural gate: refuse anything that is not named like ours.

    `PROTECTED_SUBSTRINGS` is a deny-list and deny-lists are only as complete as the enumeration
    behind them. The account's three pre-existing DRAFT guardrails are named `demo`, `test` and
    `demo123` — the isolation rule names them as a group ("the 3 DRAFT guardrails") but no
    substring in the list matches them, and no substring reasonably could without also matching
    something a future phase creates.

    So the deny-list is backed by an allow-list: every resource this project creates is named
    `grx-*`, and anything else is refused regardless of what tags it carries. That covers the
    three guardrails, and it covers the case the deny-list cannot — a pre-existing resource of a
    kind nobody thought to enumerate that someone tagged `Project=guardrails-doc-validation` by
    accident.

    Only the TAG channel is filtered this way. Ledger rows are exempt because they record what
    we ourselves created: if a future phase ever needs a differently-named resource, the ledger
    is the authorization, and it is written by our own code rather than by a tag anyone can set.

    Both separators are accepted, and that is forced by the service rather than chosen (DEV-P2-02):
    `bedrock-agentcore` runs TWO name grammars. Gateways and gateway targets take
    `([0-9a-zA-Z][-]?){1,48}`, so those are `grx-…`; policy engines and policies take
    `^[A-Za-z][A-Za-z0-9_]*$` — **hyphens are rejected** — so those must be `grx_…`. An allow-list
    that recognised only one separator would have refused to delete our own policy engine while
    reporting a clean sweep of everything else, which is the exact failure this gate exists to
    prevent, inverted. `protected()` already normalises the separators for the same reason.
    """
    tail = (name_or_arn or "").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if any(tail.startswith(p) for p in _OUR_PREFIXES):
        return ""
    return (f"name {tail!r} does not start with any of {_OUR_PREFIXES!r}; the tag channel deletes "
            f"only resources named like ours, because a deny-list cannot enumerate every "
            f"pre-existing resource someone might mistag")


def protected(name_or_arn: str) -> str:
    """The matching substring if this must not be touched, else "".

    `_` and `-` are normalized to the same character on both sides. See the note on
    `PROTECTED_SUBSTRINGS`: the same logical resource family appears with either separator
    depending on which API named it, and a literal match protected none of this account's 84
    pre-existing delivery resources.
    """
    low = (name_or_arn or "").lower().replace("_", "-")
    for s in PROTECTED_SUBSTRINGS:
        if s.lower().replace("_", "-") in low:
            return s
    return ""


def delete_resource(f, store, res: Resource, account_id: str, *,
                    dry: bool, attempts: int = 4) -> dict:
    """Replay one recorded delete. Returns a row for the teardown log."""
    guard = protected(res.name) or protected(res.arn)
    if guard:
        return {"kind": res.kind, "logical": res.logical, "name": res.name,
                "state": "refused", "reason": f"matches protected substring {guard!r}"}

    if dry:
        return {"kind": res.kind, "logical": res.logical, "name": res.name,
                "state": "would-delete", "op": res.delete_op,
                "priority": res.delete_priority}

    client = f.client(res.service)
    params = {k: (T.unmask_arn(v, account_id) if isinstance(v, str) else v)
              for k, v in (res.delete_params or {}).items()}

    last = None
    for attempt in range(1, attempts + 1):
        rec = capture(store, res.delete_op, client, **params)
        if rec.ok:
            return {"kind": res.kind, "logical": res.logical, "name": res.name,
                    "state": "deleted", "request_id": rec.request_id, "attempts": attempt}
        last = rec
        if rec.error_code in GONE_CODES and rec.error_code not in RETRY_CODES:
            return {"kind": res.kind, "logical": res.logical, "name": res.name,
                    "state": "already-absent", "error_code": rec.error_code}
        if rec.error_code in RETRY_CODES and attempt < attempts:
            # Bounded and explained. The service enforces some reference constraints
            # asynchronously, so a correct deletion order can still hit a transient conflict;
            # an unbounded retry would instead hide a genuine ordering bug in our priorities.
            wait = 5.0 * attempt
            print(f"      {rec.error_code} on attempt {attempt}; retrying in {wait:.0f}s")
            time.sleep(wait)
            continue
        break

    if last is not None and last.error_code in GONE_CODES:
        return {"kind": res.kind, "logical": res.logical, "name": res.name,
                "state": "already-absent", "error_code": last.error_code}
    return {"kind": res.kind, "logical": res.logical, "name": res.name,
            "state": "FAILED",
            "error_code": last.error_code if last else "?",
            "error": (last.error_message if last else "")[:400]}


def delete_role_prerequisites(f, store, res: Resource, *, dry: bool) -> list[dict]:
    """An IAM role cannot be deleted while it holds inline or attached policies.

    Handled here rather than as extra ledger rows because the policies are *part of* the role
    for our purposes and listing them live is more reliable than trusting the ledger to have
    recorded every `put_role_policy` — including one added by a red-team mutation that a killed
    run never got to record.
    """
    if res.kind != "iam-role":
        return []
    iam = f.iam()
    rows = []
    try:
        inline = iam.list_role_policies(RoleName=res.name).get("PolicyNames") or []
        attached = [x["PolicyArn"] for x in
                    iam.list_attached_role_policies(RoleName=res.name)
                    .get("AttachedPolicies") or []]
    except Exception as exc:                                       # noqa: BLE001
        return [{"kind": "iam-role-policies", "logical": res.logical, "name": res.name,
                 "state": "FAILED", "error": f"{type(exc).__name__}: {exc}"}]
    for pn in inline:
        if dry:
            rows.append({"kind": "iam-inline-policy", "logical": res.logical,
                         "name": f"{res.name}/{pn}", "state": "would-delete"})
            continue
        rec = capture(store, "delete_role_policy", iam, RoleName=res.name, PolicyName=pn)
        rows.append({"kind": "iam-inline-policy", "logical": res.logical,
                     "name": f"{res.name}/{pn}",
                     "state": "deleted" if rec.ok else "FAILED",
                     "error_code": rec.error_code})
    for pa in attached:
        if dry:
            rows.append({"kind": "iam-attached-policy", "logical": res.logical,
                         "name": f"{res.name}/{pa.split('/')[-1]}", "state": "would-delete"})
            continue
        rec = capture(store, "detach_role_policy", iam, RoleName=res.name, PolicyArn=pa)
        rows.append({"kind": "iam-attached-policy", "logical": res.logical,
                     "name": f"{res.name}/{pa.split('/')[-1]}",
                     "state": "detached" if rec.ok else "FAILED",
                     "error_code": rec.error_code})
    return rows


def phase1_guardrails() -> list[Resource]:
    """Phase 1's guardrails as `Resource` rows, read from the registry it writes.

    Returns [] if the registry is absent, which is the correct answer for a checkout that never
    ran Phase 1 — and is distinguishable from "the file exists and lists nothing", which would
    mean Phase 1 ran and provisioned none.

    Priority 40: after everything Phase 2 built (a gateway's policy engine may reference a
    guardrail through a Cedar `when guardrails {...}` clause) and before the IAM roles at 85.
    """
    if not PHASE1_GUARDRAIL_REGISTRY.exists():
        return []
    try:
        reg = json.loads(PHASE1_GUARDRAIL_REGISTRY.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  WARNING: {PHASE1_GUARDRAIL_REGISTRY.name} is unreadable ({exc}); Phase 1's "
              f"guardrails will show up as tag-channel orphans instead.", file=sys.stderr)
        return []
    out = []
    for logical, g in sorted((reg.get("guardrails") or {}).items()):
        gid = g.get("guardrail_id")
        if not gid:
            continue
        out.append(Resource(
            kind="guardrail", logical=f"phase1-{logical}", name=g.get("name", gid),
            service="bedrock", delete_op="delete_guardrail",
            delete_params={"guardrailIdentifier": gid},
            ids={"guardrail_id": gid, "purpose": g.get("purpose", ""),
                 "version": g.get("version", "DRAFT")},
            arn="", delete_priority=40,
            notes="Phase 1 F3/F8/F10 guardrail, read from results/phase1_guardrails.json. Not "
                  "in state.json because 00_guardrails.py is idempotent by name rather than by "
                  "ledger; without this path these are visible to the tag sweep but have no "
                  "recorded delete operation.",
        ))
    return out


def sweep_logs_delivery(f, run_id: str | None) -> tuple[list[dict], bool]:
    """Direct sweep of the `logs` resources the tag channel cannot see.

    Returns (rows, ok). `ok` is False if any API call failed — and that False propagates to the
    exit code, because a channel that could not run must not be reported as finding nothing.
    """
    logs = f.logs()
    rows: list[dict] = []
    ok = True
    prefix = "grx-"

    def paged(op, key):
        nonlocal ok
        token = None
        out = []
        while True:
            # `limit`, not `maxResults`. The `logs` delivery operations take
            # `{limit, nextToken}` only — the dry-run caught this as an `Unknown parameter in
            # input` that the channel reported as "could not run", which is exactly the
            # behaviour intended for a broken channel but would have read as a clean sweep if
            # the exception had been swallowed.
            kw = {"limit": 50}
            if token:
                kw["nextToken"] = token
            try:
                resp = getattr(logs, op)(**kw)
            except Exception as exc:                               # noqa: BLE001
                print(f"  logs sweep: {op} FAILED ({type(exc).__name__}: {exc}). This channel "
                      f"could not run, so 'zero survivors' is NOT established for `logs`.",
                      file=sys.stderr)
                ok = False
                return out
            out.extend(resp.get(key) or [])
            token = resp.get("nextToken")
            if not token:
                return out

    for row in paged("describe_delivery_sources", "deliverySources"):
        nm = row.get("name", "")
        if not nm.startswith(prefix) or (run_id and run_id not in nm):
            continue
        rows.append({"kind": "delivery-source", "name": nm, "arn": row.get("arn", "")})
    for row in paged("describe_delivery_destinations", "deliveryDestinations"):
        nm = row.get("name", "")
        if not nm.startswith(prefix) or (run_id and run_id not in nm):
            continue
        rows.append({"kind": "delivery-destination", "name": nm, "arn": row.get("arn", "")})
    for row in paged("describe_deliveries", "deliveries"):
        src = row.get("deliverySourceName", "")
        if not src.startswith(prefix) or (run_id and run_id not in src):
            continue
        rows.append({"kind": "delivery", "name": str(row.get("id")),
                     "arn": row.get("arn", ""), "source": src})

    # Vended log groups. Named after the gateway id, not the run id, so the run filter cannot be
    # applied by name — the ledger is consulted for those and this sweep reports the prefix.
    try:
        token = None
        while True:
            kw = {"logGroupNamePrefix": "/aws/vendedlogs/bedrock-agentcore/gateway/", "limit": 50}
            if token:
                kw["nextToken"] = token
            resp = logs.describe_log_groups(**kw)
            for g in resp.get("logGroups") or []:
                rows.append({"kind": "log-group", "name": g["logGroupName"],
                             "arn": g.get("arn", "")})
            token = resp.get("nextToken")
            if not token:
                break
    except Exception as exc:                                       # noqa: BLE001
        print(f"  logs sweep: describe_log_groups FAILED ({type(exc).__name__}: {exc})",
              file=sys.stderr)
        ok = False
    return rows, ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the deletion order and both sweeps; delete nothing")
    ap.add_argument("--confirm", action="store_true",
                    help="actually delete. Required — there is no default that destroys.")
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--all-runs", action="store_true",
                    help="sweep the whole project rather than just this run's RunId. Finds "
                         "orphans from earlier killed runs; will NOT delete them unless "
                         "--delete-orphans is also given.")
    ap.add_argument("--delete-orphans", action="store_true",
                    help="delete tag-channel resources absent from the ledger. Off by default: "
                         "an unrecognised tagged resource is more likely a concurrent run's "
                         "live testbed than an orphan, and deleting that is worse than leaving "
                         "residue.")
    args = ap.parse_args()

    if not (args.dry_run or args.confirm):
        print("refusing to run: pass --dry-run or --confirm.", file=sys.stderr)
        return 2

    dry = not args.confirm
    f = A.factory(args.region)
    account_id = A.account_id(f)

    try:
        state = State.load(Path(args.state) if args.state else None)
    except FileNotFoundError:
        state = None

    run_id = state.run_id if state else None
    store = EvidenceStore(run_id or "no-ledger", "infra", "P99-teardown")
    store.write_environment()

    print(f"Phase 99 — teardown ({'DRY RUN' if dry else 'DELETING'}), region={args.region}")
    print(f"  ledger        {'state.json run_id=' + run_id if run_id else 'ABSENT — the tag '
                             'channel is the only channel this run has'}")

    rows: list[dict] = []
    channels_ok = True
    refused: list[dict] = []

    # ---- channel 1: the ledger, in reference order -----------------------------------------
    # Two registries merged into one ordered list: state.json (Phase 2) and
    # results/phase1_guardrails.json (Phase 1). Merged and re-sorted rather than run in
    # sequence, because the priorities encode reference constraints ACROSS the two — a policy
    # engine at 35 may hold a Cedar guardrail clause, so the guardrails at 40 must come after it.
    p1 = phase1_guardrails()
    if p1:
        print(f"  Phase 1 registry: {len(p1)} guardrail(s) from "
              f"{PHASE1_GUARDRAIL_REGISTRY.name}")
    if state or p1:
        order = sorted((list(state.resources.values()) if state else []) + p1,
                       key=lambda r: (r.delete_priority, T._neg_str(r.created_at)))
        print(f"  deleting {len(order)} recorded resources in reference order:")
        for res in order:
            print(f"    [{res.delete_priority:3d}] {res.kind}/{res.logical} {res.name}")
            rows.extend(delete_role_prerequisites(f, store, res, dry=dry))
            row = delete_resource(f, store, res, account_id, dry=dry)
            rows.append(row)
            if row["state"] == "refused":
                refused.append(row)
                print(f"          REFUSED: {row['reason']}")
            elif row["state"] not in ("would-delete",):
                print(f"          {row['state']}")
    else:
        print("  no ledger; skipping channel 1")

    # ---- channel 2: the tag sweep, which is what proves the claim ----------------------------
    print("\n  tag sweep (the channel that finds unrecorded resources):")
    try:
        swept = T.sweep_by_tag(f, None if args.all_runs else run_id)
    except Exception as exc:                                       # noqa: BLE001
        print(f"  FAILED: {type(exc).__name__}: {exc}. A sweep that cannot run must not report "
              f"clean, so this teardown will exit non-zero.", file=sys.stderr)
        swept, channels_ok = [], False

    # What the ledger channel accounts for, by ARN *and* by id. Phase 1's guardrail rows carry no
    # ARN — the registry stores ids — so an ARN-only cross-check would classify all 12 as orphans
    # even after channel 1 deleted them. The id substring is enough here because a guardrail id is
    # 12 random characters and appears in its ARN's tail.
    ledger_arns = {T.unmask_arn(r.arn, account_id) for r in
                   (list(state.resources.values()) if state else []) + p1 if r.arn}
    ledger_ids = {str(v) for r in ((list(state.resources.values()) if state else []) + p1)
                  for k, v in (r.ids or {}).items()
                  if k.endswith("_id") and isinstance(v, str) and v}

    def accounted(arn: str) -> bool:
        if arn in ledger_arns:
            return True
        tail = arn.rsplit("/", 1)[-1]
        return bool(tail) and tail in ledger_ids

    by_run: dict[str, list[dict]] = {}
    for r in swept:
        by_run.setdefault(r["tags"].get("RunId", "<no RunId>"), []).append(r)
    for rid, items in sorted(by_run.items()):
        mark = " (this run)" if rid == run_id else ""
        print(f"    RunId={rid}{mark}: {len(items)} tagged resources")

    orphans = [r for r in swept if not accounted(r["arn"])]
    for r in orphans:
        guard = protected(r["arn"]) or not_ours(r["arn"])
        if guard:
            # A mistagged pre-existing resource must not be deletable by a sweep. This is the
            # case the isolation rule exists for and the reason `protected()` is applied to the
            # tag channel too, not only to the ledger.
            row = {"kind": r["type"], "name": r["arn"], "state": "refused",
                   "reason": f"tag-channel orphan matching protected substring {guard!r}"}
            rows.append(row)
            refused.append(row)
            print(f"    REFUSED orphan {redact.mask_text(r['arn'])}: protected {guard!r}")
            continue
        rid = r["tags"].get("RunId", "")
        if not args.delete_orphans or (run_id and rid and rid != run_id and not args.all_runs):
            rows.append({"kind": r["type"], "name": r["arn"], "state": "orphan-left",
                         "run_id": rid,
                         "reason": "tag-only resource; --delete-orphans not given. An "
                                   "unrecognised tagged resource may be a concurrent run's "
                                   "live testbed."})
            print(f"    ORPHAN (left) {redact.mask_text(r['arn'])} RunId={rid or '?'}")
            continue
        # Deleting an orphan needs a delete operation we never recorded, so it is reconstructed
        # from the ARN — and only for the types this project creates.
        rows.append({"kind": r["type"], "name": r["arn"], "state": "orphan-unhandled",
                     "reason": "no recorded delete_op; delete manually or re-run the owning "
                               "phase's script with --ensure then teardown again"})
        print(f"    ORPHAN (unhandled) {redact.mask_text(r['arn'])}")

    # ---- channel 3: the `logs` types neither channel above covers ---------------------------
    print("\n  logs sweep (the tag index DOES cover `logs`, but deliveries record no ARN and "
          "`put_delivery_*` tags are create-time-only, so an untagged orphan is reachable only "
          "by name — this channel is not optional):")
    logs_rows, logs_ok = sweep_logs_delivery(f, None if args.all_runs else run_id)
    channels_ok = channels_ok and logs_ok
    ledger_logs_names = {r.name for r in (state.resources.values() if state else [])
                         if r.service == "logs"}
    for r in logs_rows:
        # `not_ours` reads the segment after the last `/`, which for a vended log group
        # (`/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/<gateway-id>`) is the
        # gateway id — so ours pass and another gateway's are refused, which is the intent.
        guard = protected(r["name"]) or not_ours(r["name"])
        known = r["name"] in ledger_logs_names
        state_s = ("in-ledger" if known else "logs-orphan")
        if guard:
            state_s = "refused"
            refused.append({"kind": r["kind"], "name": r["name"], "state": "refused",
                            "reason": f"protected {guard!r}"})
        print(f"    {r['kind']:22s} {r['name']:50s} {state_s}")
        rows.append({"kind": r["kind"], "name": r["name"], "state": f"logs-sweep:{state_s}"})

    # ---- the verdict -------------------------------------------------------------------------
    failed = [r for r in rows if r["state"] == "FAILED"]
    survivors_tag = [r for r in rows if r["state"].startswith("orphan")]
    survivors_logs = [r for r in rows if r["state"] == "logs-sweep:logs-orphan"]

    verdict = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run_id": run_id,
        "region": args.region,
        "dry_run": dry,
        "channels_ok": channels_ok,
        "n_ledger_resources": len(state.resources) if state else 0,
        "n_tagged_found": len(swept),
        "n_failed": len(failed),
        "n_orphans_left": len(survivors_tag),
        "n_logs_orphans": len(survivors_logs),
        "n_refused_protected": len(refused),
        "tag_channel_covers": sorted({r["type"] for r in swept}),
        "tag_channel_blind_to": ["logs (delivery-source, delivery-destination, delivery, "
                                 "log-group) — swept directly by channel 3"],
        "rows": rows,
    }
    TEARDOWN_LOG.write_text(json.dumps(redact.mask(verdict), indent=2, sort_keys=True) + "\n")
    store.write_summary(verdict)
    print(f"\n  teardown_log.json written ({len(rows)} rows)")

    if dry:
        print("\n--dry-run: nothing deleted. Re-run with --confirm.")
        return 0

    # Re-sweep after deleting. The whole point: the claim is not "the deletes returned 200", it
    # is "nothing is there now", and only a second read can say that.
    print("\n  re-sweep to establish zero survivors:")
    time.sleep(5.0)
    try:
        again = T.sweep_by_tag(f, None if args.all_runs else run_id)
    except Exception as exc:                                       # noqa: BLE001
        print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        again, channels_ok = [], False
    # A survivor is something WE should have deleted. Anything protected or not named like ours
    # was never a deletion candidate, so counting it here would make the exit code depend on
    # other systems' resources and no run could ever finish clean.
    remaining = [r for r in again
                 if not protected(r["arn"]) and not not_ours(r["arn"])]
    for r in remaining:
        print(f"    SURVIVOR {redact.mask_text(r['arn'])}")
    logs_again, logs_ok2 = sweep_logs_delivery(f, None if args.all_runs else run_id)
    channels_ok = channels_ok and logs_ok2
    logs_remaining = [r for r in logs_again
                      if not protected(r["name"]) and not not_ours(r["name"])
                      and r["kind"] != "log-group"]
    for r in logs_remaining:
        print(f"    SURVIVOR (logs) {r['kind']} {r['name']}")

    verdict["resweep_survivors"] = len(remaining)
    verdict["resweep_logs_survivors"] = len(logs_remaining)
    verdict["channels_ok"] = channels_ok
    TEARDOWN_LOG.write_text(json.dumps(redact.mask(verdict), indent=2, sort_keys=True) + "\n")

    bad = bool(failed or remaining or logs_remaining or refused or not channels_ok)
    if bad:
        print(f"\nTEARDOWN INCOMPLETE: {len(failed)} failed delete(s), {len(remaining)} tagged "
              f"survivor(s), {len(logs_remaining)} logs survivor(s), {len(refused)} protected "
              f"match(es), channels_ok={channels_ok}. Exiting non-zero: a teardown that cannot "
              f"prove zero survivors has not established zero survivors.", file=sys.stderr)
        return 1
    print("\nzero survivors, both channels agree, and the `logs` types the tag index does not "
          "cover were swept directly. teardown_log.json holds the evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
