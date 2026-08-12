#!/usr/bin/env python3
"""F7-5: tracing must be explicitly enabled, or spans are absent.

    python3 f7_observability/01_tracing_mutation.py --dry-run
    python3 f7_observability/01_tracing_mutation.py --n 3      # smoke
    python3 f7_observability/01_tracing_mutation.py            # n=10 per arm

Sealed oracle: "TRUE if spans are absent with tracing off and present with it on; FALSE if
spans appear either way. This is the mutation that removes 'did we enable it' as a confound
for every other O-claim." Kind EXISTENCE, and `mutation_is_mandatory(F7-5)` is **True** —
this case *is* a mutation, so `evaluate` will not hand it a TRUE without one.

WHY THIS CASE RUNS FIRST IN F7, AND WHY THAT ORDER IS NOT COSMETIC
-----------------------------------------------------------------
F7-4, F3-10, the τ-sweep replacing F2-2/F2-3/F2-4 and (now) F6's server-side latency all
read `aws/spans`. Every one of them would produce the same output if our delivery were
misconfigured and we were reading some other system's rows, or if a query window were wrong
and we were reading nothing. "Tracing is on" is the shared precondition of all of them, and
an unverified precondition is exactly what a vacuous suite is made of. So this script
establishes, by removing it and putting it back, that the delivery is what puts our spans
there — and only then is any other span-derived reading worth collecting.

WHAT IS MUTATED, AND WHY IT IS A DELIVERY RATHER THAN A GATEWAY FIELD
--------------------------------------------------------------------
Gateway tracing is **not** a gateway field. There is no `tracingEnabled` on
CreateGateway/UpdateGateway; spans reach `aws/spans` through a CloudWatch Logs **vended
delivery** — `PutDeliverySource(logType="TRACES")` → `PutDeliveryDestination(XRAY)` →
`CreateDelivery` (see `infra/07_traces.py`). The mutation is therefore `DeleteDelivery` on
that one delivery, which leaves the gateway configuration **byte-identical**.

That matters for the confound this case exists to remove. Had tracing been a gateway field,
`UpdateGateway` would have been the mutation — and `UpdateGateway` is a REPLACE on this
service (F4's measured behaviour: an omitted member is RESET), so "spans stopped" would be
confoundable with "the gateway changed". Mutating the delivery cannot do that, and guard
`gateway_config_unchanged` proves it rather than asserting it: the gateway config is hashed
before and after and the two hashes must be equal.

THE RESTORE CHANGES THE DELIVERY ID, AND THE LEDGER MUST LEARN THE NEW ONE
--------------------------------------------------------------------------
`create_delivery` mints a **new** delivery id, so after the restore the ledger's recorded
`delete_params: {"id": "<old>"}` names an object that no longer exists. Teardown replays
`delete_op`/`delete_params` **as data** (`lib/testbed.Resource`'s docstring: so that a
teardown running in a different process from the creator can still work), so a stale id
would make teardown call `delete_delivery` on a dead id, and the live delivery this script
created would survive the sweep as an untracked resource. That is the
no-deploy-path-no-component defect pointed the other way: an object that exists but nothing
deletes. So the restore **re-records** the resource with the new id and flushes the ledger,
and `state.json`'s `ids.f7_5_recreate` — which `infra/07_traces.py` stored *for this case* —
is what the restore replays, rather than a reconstruction of what infra probably did.

THE THREE ARMS, AND WHY THE ON ARM IS RUN TWICE
-----------------------------------------------
    ON-1   delivery live      -> spans MUST appear   (establishes the instrument)
    OFF    delivery deleted   -> spans MUST NOT      (the mutation)
    ON-2   delivery restored  -> spans MUST appear   (establishes the restore)

Running ON only once — before the mutation — would leave a TRUE resting on an arm never
re-established: "no spans while off" is equally consistent with *we permanently broke the
delivery*, and the reader could not tell which. ON-2 is what separates a reversible
mutation from a broken testbed, and it is the same reason F4 re-verifies its axes after
restoring them.

WHY ABSENCE IS CLAIMED PER REQUEST ID AND NOT PER TIME WINDOW
-------------------------------------------------------------
The weak version of this measurement is "query a window after the delete and find nothing",
which any wrong window satisfies. The strong version needs a marker that ties *these*
requests to *those* rows, and it turns out one exists and is already measured: the client
reads `x-amzn-requestid` off the MCP response (`lib/mcp.Decision.request_id`) and the span
carries `attributes.aws.request.id`. Joining F4 and F2-1 checkpoints against live spans
matched **242 of 250 span request ids (96.8%)** — one request id carries two spans
(`AgentCore.Gateway.InvokeTool` and `AgentCore.Policy.AuthorizeAction`); the eight
non-joiners are `Initialize` / `NotificationsInitialized` rows whose request ids were never
recorded as trials. See DEVIATIONS.md/DEV-P4-01.

So the OFF arm's claim is not "no spans in a window" but **"no span carries any of these
ten request ids"**, and the ON arms' claim is "these request ids appear". A wrong window
now shows up as a *failed ON arm*, which is INCONCLUSIVE, rather than as a false TRUE.

HOW LONG "ABSENT" WAITS, AND WHY THE NUMBER IS MEASURED IN-RUN
--------------------------------------------------------------
Declaring absence after too short a wait is the standard way to manufacture this TRUE. The
wait is therefore derived from a measurement taken in the same run: ON-1 records the elapsed
time from request to first queryable span (`wait_for_span` returns it), and the OFF arm waits
`max(OFF_WAIT_FLOOR_S, LAG_MULTIPLE x that lag)`. Both the observed lag and the wait actually
used are recorded, so a reader can check the margin instead of trusting it.

WHY THERE IS NO RETRY ON AN INCONVENIENT OFF ARM
------------------------------------------------
A single generous settle (`DELETE_SETTLE_S`) runs *before* the OFF traffic, and the OFF arm
is attempted exactly once. The alternative — "if spans appear, wait longer and try again" —
is a forking path whose stopping rule is the result, and it would convert any propagation
delay into a TRUE. If spans appear in the OFF arm, that is recorded as the FALSE the oracle
names, with the settle and the wait beside it so the reading can be challenged on its
numbers rather than on its intent.

THE SEVEN GUARDS, AND THE ONE THAT MATTERS MOST
-----------------------------------------------
Every guard failure yields INCONCLUSIVE via `O.not_measured` — never a verdict.

    on1_joins                 ON-1 joined >=1 request id. Else the instrument never worked
                              and the OFF arm's zero measures nothing.
    off_calls_reached_gateway  **the load-bearing one.** Every OFF trial returned a real
                              gateway decision (`allowed` or `policy_denied`). If the calls
                              had failed, "no spans" would be true for the wrong reason —
                              no request, no span — and would read as evidence about
                              tracing. This is the vacuity trap for this case.
    delivery_deleted          `traces_delivery_live` reads False after the delete, so the
                              mutation actually landed.
    delivery_restored         and True again after the recreate.
    on2_joins                 ON-2 joined >=1, so the mutation was reversible.
    arms_disjoint             the three arms' request-id sets are pairwise disjoint, or a
                              join is ambiguous about which arm produced a row.
    gateway_config_unchanged  the gateway config hash is identical before and after.

WHAT THIS CASE DELIBERATELY DOES NOT TOUCH
------------------------------------------
Only the **main** gateway's TRACES delivery is mutated. `grx-gw-nopolicy`'s delivery is left
alone — it is F6's paired baseline, and desynchronising the pair's observability would damage
a case this one has no business touching. The shared XRAY *destination* and both *sources*
are also left alone: only the delivery joining them is deleted, which is the smallest object
whose removal turns tracing off. Transaction Search is **asserted**, never enabled: it is an
account-wide setting other systems here depend on (`assert_transaction_search`).

COST
----
3 arms x n trials of `tools/call` on a Lambda target: at n=10, 30 Lambda invocations plus
free control-plane and Logs Insights calls. No guardrail term, no ApplyGuardrail, no model,
so **zero text units**. The wall clock, not the money, is the cost: roughly 25-35 minutes,
almost all of it the deliberately generous settles and waits.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                   # noqa: E402
import mcp as M                                          # noqa: E402
import oracle as O                                       # noqa: E402
import phase1 as P                                       # noqa: E402
import testbed as T                                      # noqa: E402
from evidence import EvidenceStore, capture              # noqa: E402

FAMILY = "f7"
CASE = "F7-5"

# Registered under a name `lib/` and the repo root do not own, and held in a module-level
# constant so `lib/tests/test_module_name_collisions.py` can resolve it statically. The infra
# scripts start with a digit, so they cannot be imported by name at all.
TRACES_MODULE_NAME = "grx_infra_07_traces"
TRACES_PATH = ROOT / "infra" / "07_traces.py"

TOOL = "echo"
TEXT = "f7-5 tracing mutation"

PLANNED_N_PER_ARM = 10

ARM_ON1 = "on-1"
ARM_OFF = "off"
ARM_ON2 = "on-2"
ARMS = (ARM_ON1, ARM_OFF, ARM_ON2)

# Outcomes that mean the request reached a policy evaluation and the gateway answered. Both
# produce spans: F4 measured that a denial is HTTP 200 + JSON-RPC -32002, and the probe found
# `authorization_decision = DENY` rows carrying the same span pair as an ALLOW. So this case is
# mode-agnostic by construction and does not touch either mode axis.
REAL_RESPONSE_OUTCOMES = ("allowed", "policy_denied")

# Seconds to wait after DeleteDelivery before sending OFF traffic. Generous and single-shot on
# purpose: see the module docstring on why there is no retry.
DELETE_SETTLE_S = 300

# The OFF arm waits max(floor, multiple x observed ON-1 lag) before declaring absence.
OFF_WAIT_FLOOR_S = 600
LAG_MULTIPLE = 4.0

# Ceiling for how long an ON arm will wait for its first span before giving up. A miss here is
# an instrument failure (INCONCLUSIVE), not a result.
ON_WAIT_TIMEOUT_S = 420

# Logs Insights lookback and row cap for the join query. The query is restricted to the arm's
# own request ids (see `_span_request_ids`), so at most ~2 rows per id can match and the cap is
# unreachable by a wide margin — reaching it would mean the filter is not filtering, which
# `_span_request_ids` raises on rather than reports. The lookback comfortably covers the
# longest wait this script performs (300 s settle + 600 s floor) plus the publish lag.
JOIN_LOOKBACK_MIN = 180
JOIN_LIMIT = 500

GUARDS = ("on1_joins", "off_calls_reached_gateway", "delivery_deleted",
          "delivery_restored", "on2_joins", "arms_disjoint",
          "gateway_config_unchanged")


class ConfigError(RuntimeError):
    """The testbed is not in the state this case needs. Never a verdict."""


def _load_traces():
    spec = importlib.util.spec_from_file_location(TRACES_MODULE_NAME, TRACES_PATH)
    if spec is None or spec.loader is None:                     # pragma: no cover
        raise ConfigError(f"cannot load {TRACES_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[TRACES_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def _config_hash(ac, gateway_id: str) -> tuple[str, dict]:
    """A stable hash of the gateway configuration, for the unchanged-config guard.

    The response's own metadata is dropped before hashing: `ResponseMetadata` carries a fresh
    request id on every call and `updatedAt` moves when anything touches the resource, so
    hashing them would make this guard fail for reasons that are not configuration changes —
    a guard that cries wolf is a guard that gets relaxed.
    """
    cfg = ac.get_gateway(gatewayIdentifier=gateway_id)
    cfg.pop("ResponseMetadata", None)
    body = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest(), cfg


def _send_arm(fc, store, *, arm: str, gateway_url: str, run_id: str, tool_name: str,
              n: int, session_timeout_s: int) -> dict[str, Any]:
    """Send n `tools/call` requests, returning their client-observed request ids.

    A transport fault at handshake time is an INSTRUMENT failure and is raised as
    `ConfigError` so it travels the INCONCLUSIVE path — it is not evidence about tracing.
    """
    try:
        client = M.client_for(gateway_url, fc, store=store,
                              policy_session_id=M.policy_session_id(run_id, arm),
                              session_timeout_s=session_timeout_s)
        client.initialize()
    except M.McpTransportError as exc:
        raise ConfigError(
            f"arm {arm}: the MCP client could not be established, so this arm measured "
            f"nothing about tracing: {exc}") from exc

    trials: list[dict[str, Any]] = []
    t0 = time.time()
    for i in range(1, n + 1):
        client.refresh_if_stale()
        d = client.call_tool(tool_name, {"text": f"{TEXT} {arm} {i}"})
        trials.append({"i": i, "outcome": d.outcome, "request_id": d.request_id,
                       "http_status": d.http_status})
    t1 = time.time()

    real = [t for t in trials if t["outcome"] in REAL_RESPONSE_OUTCOMES]
    with_id = [t for t in real if t["request_id"]]
    return {
        "arm": arm,
        "n_sent": len(trials),
        "n_real_response": len(real),
        "n_with_request_id": len(with_id),
        "request_ids": sorted({t["request_id"] for t in with_id}),
        "outcomes": sorted({t["outcome"] for t in trials}),
        "trials": trials,
        "sent_epoch_start": t0,
        "sent_epoch_end": t1,
    }


_ID_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _span_request_ids(tr, logs, gateway_arn: str, want: set[str]) -> dict[str, Any]:
    """Which of `want` appear as a span `attributes.aws.request.id`, plus the span names.

    THE QUERY IS RESTRICTED TO `want`, AND THAT IS A CORRECTNESS FIX, NOT AN OPTIMISATION
    ------------------------------------------------------------------------------------
    The first version asked for every span on this gateway in a 180-minute window and joined
    in Python. Measured live, that returned **500 rows = the row cap**, i.e. a truncated
    answer: `query_spans` sorts `@timestamp desc`, so the reply was the newest 500 of an
    unknown larger set, and 250 distinct request ids from the F4/F2-1 backlog were enough to
    fill it.

    A desc-sort argument does rescue the reading — our arm's spans are the newest, so
    truncation could not hide them — but that argument is exactly the kind of reasoning that
    made an earlier prose claim about span names wrong (DEVIATIONS.md/DEV-P4-01). Filtering
    the query by the arm's own request ids removes the need for it: at most two rows per
    request id can match, so the reply cannot be truncated, and `truncated_at_limit` becomes
    a real alarm rather than a permanent True.

    It also improves the byproduct. `span_names` now tallies the names of spans carrying
    **these** request ids rather than the names present in a shared window, which is the
    per-request statement F7-4 needs.
    """
    if not want:
        return {"n_rows": 0, "n_parsed": 0, "ids": set(), "span_names": {},
                "truncated_at_limit": False, "n_wanted": 0}
    bad = sorted(i for i in want if not _ID_SAFE.match(i))
    if bad:
        # Interpolating an unexpected literal into a query string is how a filter silently
        # stops filtering, and a filter that stops filtering on `aws/spans` reads another
        # system's rows as our evidence.
        raise ConfigError(
            f"request id(s) {bad} do not match {_ID_SAFE.pattern}, so they cannot be "
            f"interpolated into a Logs Insights filter")
    clause = " or ".join(f'@message like "{i}"' for i in sorted(want))
    rows = tr.query_spans(logs, gateway_arn, minutes=JOIN_LOOKBACK_MIN, limit=JOIN_LIMIT,
                          extra_filter=f"filter {clause}")
    if len(rows) >= JOIN_LIMIT:
        # Unreachable with a working filter: {len(want)} ids can produce only a handful of
        # rows. Raised rather than recorded, because a truncated reply is an answer about the
        # tail and this function's callers treat its answer as complete.
        raise ConfigError(
            f"the id-restricted span query returned {len(rows)} rows, at the {JOIN_LIMIT} cap, "
            f"for only {len(want)} request ids. The filter is not filtering, so neither a "
            f"presence nor an absence reading from it can be trusted")
    ids: set[str] = set()
    names: dict[str, int] = {}
    n_parsed = 0
    for row in rows:
        msg = next((f["value"] for f in row if f.get("field") == "@message"), None)
        if not msg:
            continue
        try:
            obj = json.loads(msg)
        except json.JSONDecodeError:
            continue
        n_parsed += 1
        rid = (obj.get("attributes") or {}).get("aws.request.id")
        if rid:
            ids.add(rid)
        nm = obj.get("name") or "?"
        names[nm] = names.get(nm, 0) + 1
    # Intersected with `want`, not returned raw: the filter is a SUBSTRING match on the raw
    # message, so a row could in principle carry one of these ids in some other field. The
    # join must be on the parsed `attributes.aws.request.id` and nothing looser.
    return {"n_rows": len(rows), "n_parsed": n_parsed, "ids": ids & want,
            "ids_seen_not_wanted": sorted(ids - want),
            "span_names": names, "n_wanted": len(want),
            "truncated_at_limit": len(rows) >= JOIN_LIMIT}


def _wait_for_arm_spans(tr, logs, gateway_arn: str, want: set[str], *,
                        timeout_s: int, poll_s: float = 20.0) -> dict[str, Any]:
    """Poll until at least one of `want` appears as a span request id, or time out."""
    t0 = time.monotonic()
    last: dict[str, Any] = {}
    while True:
        last = _span_request_ids(tr, logs, gateway_arn, want)
        hit = last["ids"]
        if hit:
            return {"joined": sorted(hit), "n_joined": len(hit),
                    "elapsed_s": time.monotonic() - t0, "timed_out": False,
                    "query": {k: v for k, v in last.items() if k != "ids"}}
        if time.monotonic() - t0 >= timeout_s:
            return {"joined": [], "n_joined": 0, "elapsed_s": time.monotonic() - t0,
                    "timed_out": True,
                    "query": {k: v for k, v in last.items() if k != "ids"}}
        time.sleep(poll_s)


def _restore(tr, logs, store, state, res, *, account_id: str, source_nm: str,
             gateway_arn: str, dest_nm: str, tags: dict) -> dict[str, Any]:
    """Recreate the TRACES delivery and TEACH THE LEDGER its new id.

    Never raises. A restore failure must be *reported* — a script that dies here leaves
    tracing off for every later case, and an exception traceback is a worse channel for that
    than a recorded `ok: false` the caller turns into a guard failure and a warning.

    Two paths, in order:

    1. Replay `ids.f7_5_recreate` from the ledger — the `{deliverySourceName,
       deliveryDestinationArn}` pair `infra/07_traces.py` stored **for this case**. Replaying
       what was recorded at create time restores the delivery that existed, rather than a
       delivery this script reasoned its way to.
    2. Fall back to `tr.ensure_delivery`, which re-PUTs the source and destination too. Only
       reached if (1) fails, e.g. because the shared destination is gone.

    Both are followed by the ledger update, because either path mints a new delivery id.
    """
    out: dict[str, Any] = {"attempted": True, "ok": False, "path": "", "error": "",
                           "ledger_updated": False,
                           "delivery_id_before": res.ids.get("delivery_id", "")}
    recreate = dict(res.ids.get("f7_5_recreate") or {})
    if recreate:
        params = {k: T.unmask_arn(v, account_id) if isinstance(v, str) else v
                  for k, v in recreate.items()}
        try:
            rec = capture(store, "create_delivery", logs, tags=tags, **params)
            rec.raise_for_status()
            dlv = (rec.response or {}).get("delivery") or {}
            out.update(ok=True, path="ledger_f7_5_recreate",
                       delivery_id=dlv.get("id", ""), replayed_params=recreate)
        except Exception as exc:                                   # noqa: BLE001
            out["error"] = f"ledger replay failed: {type(exc).__name__}: {exc}"

    if not out["ok"]:
        try:
            src, dst, dlv = tr.ensure_delivery(
                logs, store, source_nm=source_nm, resource_arn=gateway_arn,
                log_type=tr.LOG_TYPES["traces"], dest_nm=dest_nm, dest_type="XRAY",
                dest_config=None, tags=tags)
            out.update(ok=True, path="ensure_delivery", delivery_id=dlv.get("id", ""),
                       destination_arn=dst.get("arn", ""), source_name=src.get("name", ""))
        except Exception as exc:                                   # noqa: BLE001
            out["error"] = (out["error"] + " | " if out["error"] else "") + \
                f"ensure_delivery failed: {type(exc).__name__}: {exc}"

    new_id = out.get("delivery_id") or ""
    if out["ok"] and new_id:
        # Teardown replays delete_op/delete_params AS DATA, so all three sites that carry the
        # id have to move together: a ledger where `name` and `ids.delivery_id` disagree with
        # `delete_params` is a ledger that reads as consistent and deletes the wrong object.
        res.name = new_id
        res.ids["delivery_id"] = new_id
        res.delete_params = {"id": new_id}
        res.notes = (res.notes + " " if res.notes else "") + (
            f"Recreated by F7-5 after its mutation; the id changed from "
            f"{out['delivery_id_before']} to {new_id}, and this entry was re-recorded so "
            f"teardown deletes the live delivery rather than the deleted one.")
        state.record(res)
        out["ledger_updated"] = True
    elif out["ok"]:
        out["error"] = (out["error"] + " | " if out["error"] else "") + (
            "create succeeded but returned no delivery id, so the ledger still names the "
            "DELETED id and teardown would leak this delivery — fix state.json by hand")
    return out


def _evaluate(state: dict[str, Any], *, n_planned: int) -> tuple[dict, dict]:
    """Guards first, then the sealed oracle. Returns (record, extra payload)."""
    g = state["guards"]
    failed = [k for k in GUARDS if not g.get(k)]
    if failed:
        rec = O.not_measured(
            CASE,
            "guard(s) " + ", ".join(failed) + " did not hold, so the arms do not measure "
            "what this oracle asks. An absence of spans is only evidence about tracing when "
            "the requests demonstrably reached the gateway, the mutation demonstrably "
            "landed, and the restore demonstrably worked",
            guards=g, guard_detail=state["guard_detail"])
        return rec, {"why_inconclusive": (
            "the OFF arm's zero is the whole result, and a zero has at least four other "
            "causes: the calls never reached the gateway, the delivery was never actually "
            "deleted, the query window or row cap hid the rows, or the restore failed and "
            "the testbed is now broken. Each has its own guard, and any of them failing "
            "makes the verdict unavailable rather than merely weaker")}

    on1 = state["arms"][ARM_ON1]
    off = state["arms"][ARM_OFF]
    on2 = state["arms"][ARM_ON2]

    off_absent = off["join"]["n_joined"] == 0
    on_present = on1["join"]["n_joined"] > 0 and on2["join"]["n_joined"] > 0
    observed = bool(off_absent and on_present)

    # n is the OFF arm's usable count: it is the denominator of "none of these produced a
    # span", which is the claim the verdict turns on. The ON arms are conjuncts, not trials
    # over which a rate is estimated, and folding them in would inflate n against a claim
    # they do not denominate.
    n_off = off["n_real_response"]
    import stats as S                                             # noqa: PLC0415
    ceiling = S.rule_of_three(n_off, one_sided=True) if n_off else None

    o = P.obs_existence(
        CASE, observed, n=n_off,
        off_arm_absent=off_absent,
        on_arms_present=on_present,
        n_joined_on1=on1["join"]["n_joined"],
        n_joined_off=off["join"]["n_joined"],
        n_joined_on2=on2["join"]["n_joined"],
        span_lag_on1_s=on1["join"]["elapsed_s"],
        off_wait_s=state["off_wait_s"],
        delete_settle_s=DELETE_SETTLE_S,
        span_absence_ceiling_one_sided=ceiling)
    o.mutation_inverted = off_absent
    rec = O.evaluate(o)
    return rec, {
        "span_absence_ceiling_one_sided": ceiling,
        "ceiling_reading": (
            f"with 0 of {n_off} OFF-arm request ids appearing as spans, the one-sided 95% "
            f"ceiling on the per-request span-leak rate is "
            f"{ceiling if ceiling is None else round(ceiling, 6)}. This bounds LEAKAGE while "
            f"tracing is off; it is not a claim about how completely spans appear while it "
            f"is on, which is what the two ON arms establish qualitatively and F7-4 measures"),
        "mutation_reading": (
            "`mutation_inverted` is set to the OFF arm's absence, so a mutation that failed "
            "to invert forces FALSE through `evaluate`'s mandatory-mutation branch as well "
            "as through `observed_bool`. The redundancy is deliberate: F7-5 is the case whose "
            "entire content is that the control is load-bearing, and it should be impossible "
            "to publish a TRUE here from a mutation that did nothing"),
    }


def main(argv: list[str] | None = None) -> int:                     # noqa: C901, PLR0915
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else PLANNED_N_PER_ARM
    is_smoke = args.n is not None

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            [(ARM_ON1, "delivery live -> spans MUST appear", PLANNED_N_PER_ARM),
             (ARM_OFF, "delivery deleted -> spans MUST NOT appear", PLANNED_N_PER_ARM),
             (ARM_ON2, "delivery restored -> spans MUST appear again", PLANNED_N_PER_ARM)],
            operations={"tools/call": 3 * PLANNED_N_PER_ARM},
            mutations=2, billable=False, text_units=0,
            text_units_why=("no guardrail term, no ApplyGuardrail and no model invocation: "
                            "this case reads telemetry about plain tool calls"),
            extra=[
                "the 2 mutations are delete_delivery + create_delivery. They are NOT in the "
                "operation breakdown above because `dry_run_banner` checks that the "
                "breakdown sums to the arm plan, and these are control-plane calls outside "
                "the per-trial total. Logs Insights queries are likewise excluded: their "
                "count is data-dependent (the ON arms poll until a span joins)",
                "create_delivery mints a NEW delivery id, so the restore re-records the "
                "ledger entry. A stale delete_params.id would make teardown delete a dead "
                "id and leave the live delivery untracked",
                "the mutation is DeleteDelivery on the MAIN gateway's TRACES delivery. "
                "Gateway tracing is NOT a gateway field, so the gateway configuration stays "
                "byte-identical — and guard `gateway_config_unchanged` hashes it before and "
                "after rather than asserting that",
                "grx-gw-nopolicy's delivery is NOT touched: it is F6's paired baseline. The "
                "shared XRAY destination and both delivery sources are also left in place; "
                "only the delivery joining them is deleted",
                "Transaction Search is ASSERTED ACTIVE, never enabled — it is account-wide "
                "and other systems here depend on it",
                "absence is claimed PER REQUEST ID, not per time window: the client's "
                "x-amzn-requestid joins to the span's attributes.aws.request.id (measured at "
                "242/250 = 96.8% on existing F4/F2-1 data). A wrong window therefore shows "
                "up as a failed ON arm (INCONCLUSIVE), not as a false TRUE",
                f"the OFF arm waits max({OFF_WAIT_FLOOR_S}s, {LAG_MULTIPLE}x the span lag "
                f"MEASURED in ON-1) after a {DELETE_SETTLE_S}s post-delete settle, and is "
                f"attempted ONCE. There is no retry-if-spans-appear: that stopping rule is "
                f"the result, and it would convert propagation delay into a TRUE",
                "the ON arm runs twice, before and after. Without ON-2 a TRUE would rest on "
                "an arm never re-established, and 'no spans while off' would be equally "
                "consistent with 'we permanently broke the delivery'",
                f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}. The "
                f"load-bearing one is `off_calls_reached_gateway` — if the OFF calls had "
                f"failed, 'no spans' would be true because there was no request, and would "
                f"read as evidence about tracing",
                "wall clock roughly 25-35 minutes, nearly all of it the settles and waits",
            ])

    state = T.State.load()
    run_id = state.run_id
    region = state.region
    fc = A.factory(region)
    account_id = A.account_id(fc)
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()

    tr = _load_traces()
    logs = fc.client("logs")
    xray = fc.client("xray")
    ac = fc.client("bedrock-agentcore-control")

    gw = state.find("gateway", "main")
    if not gw:
        rec = O.not_measured(CASE, "the ledger carries no gateway/main, so there is no "
                                   "gateway whose tracing could be mutated",
                             remedy="run infra/04_gateway.py (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: incomplete ledger"}, store)
        return 2

    gateway_id = gw.ids["gateway_id"]
    gateway_url = gw.ids["gateway_url"]
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    session_timeout_s = int(gw.ids.get("session_timeout_s", 900))
    # The Cedar action ids live on the gateway-TARGET, not the gateway: the full MCP tool name
    # is `<targetName>___<toolName>`, so it cannot exist before a target does. Read from the
    # same place F4 and F2-1 read it, because a second way of resolving the tool name is a
    # second thing that can disagree — and the disagreement would show up as a -32602
    # measured-nothing rather than as an error.
    tgt = state.find("gateway-target", "main")
    action_ids = list((tgt.ids.get("cedar_action_ids") if tgt else None) or [])
    tool_name = next((a for a in action_ids if a.endswith(f"___{TOOL}")), "")

    source_nm = tr.source_name(run_id, "main", "traces")
    dest_nm = tr.dest_name(run_id, "shared", "traces")
    tags = A.tags_for(run_id, state.expires_at)
    dlv_res = state.find("delivery", "main-traces")

    common: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "n_per_arm": n, "planned_n_per_arm": PLANNED_N_PER_ARM,
        "gateway_id": gateway_id, "tool_name": tool_name,
        "mutated_object": {
            "kind": "cloudwatch-logs delivery", "source_name": source_nm,
            "destination_name": dest_nm, "log_type": tr.LOG_TYPES["traces"],
            "why": ("gateway tracing is a vended delivery, not a gateway field, so deleting "
                    "the delivery turns tracing off while leaving the gateway config "
                    "byte-identical"),
        },
        "untouched": {
            "nopolicy_delivery": "F6's paired baseline — desynchronising the pair would "
                                 "damage a case this one has no business touching",
            "delivery_sources_and_destination": "only the delivery joining them is deleted",
            "transaction_search": "asserted ACTIVE, never enabled (account-wide setting)",
            "policy_and_engine_modes": ("neither axis is touched. F4 measured that a denial "
                                        "is HTTP 200 + JSON-RPC -32002 and the probe found "
                                        "DENY rows carrying the same span pair as ALLOW, so "
                                        "this case is mode-agnostic by construction"),
        },
        "guard_names": list(GUARDS),
        "waits": {"delete_settle_s": DELETE_SETTLE_S,
                  "off_wait_floor_s": OFF_WAIT_FLOOR_S,
                  "lag_multiple": LAG_MULTIPLE,
                  "on_wait_timeout_s": ON_WAIT_TIMEOUT_S,
                  "single_attempt": ("the OFF arm is attempted once; a "
                                     "retry-if-spans-appear rule would make the stopping "
                                     "rule the result")},
        "join_query": {"log_group": tr.SPANS_LOG_GROUP, "lookback_minutes": JOIN_LOOKBACK_MIN,
                       "row_limit": JOIN_LIMIT,
                       "why_500": ("query_spans sorts @timestamp desc, so a small cap makes "
                                   "an absence claim a claim about a truncated tail")},
    }

    if not tool_name:
        rec = O.not_measured(
            CASE, f"the ledger's gateway/main carries no Cedar action id ending in "
                  f"'___{TOOL}' (saw {action_ids}), so no tool call can be addressed",
            remedy="re-run infra/05_target.py")
        P.emit(CASE, rec, {**common, "instrument": "not built: no tool name"}, store)
        return 2

    if dlv_res is None:
        # Refused BEFORE the mutation rather than handled after it. Without the ledger entry
        # the restore has no recorded recreate params and no row to re-record, so a run that
        # proceeded would delete a delivery it could only restore by guesswork — and the
        # guess would be untracked by teardown even if it worked.
        rec = O.not_measured(
            CASE, "the ledger carries no delivery/main-traces, so the delivery this case "
                  "must delete could be removed but not restored to a tracked state",
            remedy="run `python3 infra/07_traces.py --ensure` so the ledger records the "
                   "delivery and its f7_5_recreate parameters")
        P.emit(CASE, rec, {**common, "instrument": "not built: no delivery in ledger"}, store)
        return 2

    st: dict[str, Any] = {"arms": {}, "guards": {k: False for k in GUARDS},
                          "guard_detail": {}, "off_wait_s": 0.0}
    restore: dict[str, Any] = {"attempted": False, "ok": False, "error": "not reached",
                               "path": "", "ledger_updated": False}
    cfg_hash_before = ""
    # Set immediately BEFORE the delete call, not after. Set after, it would read False in
    # exactly the case that needs it — an exception raised by the delete call itself, which
    # may still have deleted the delivery.
    delete_attempted = False

    try:
        # ---- preconditions -------------------------------------------------------
        # `assert_transaction_search` raises a plain RuntimeError, and its own docstring names
        # exactly the failure this case must not mistake for a result: Transaction Search
        # being down "would make F7-5's 'tracing off -> no spans' arm pass for the wrong
        # reason". Re-raised as ConfigError so it travels the INCONCLUSIVE path rather than
        # being caught by a broad `except RuntimeError` that would also swallow real bugs.
        try:
            ts = tr.assert_transaction_search(xray, store)
        except ConfigError:
            raise
        except RuntimeError as exc:
            raise ConfigError(str(exc)) from exc
        cfg_hash_before, cfg_before = _config_hash(ac, gateway_id)
        live_before = tr.traces_delivery_live(logs, run_id, "main")
        common["preconditions"] = {
            "transaction_search": {k: ts.get(k) for k in ("Destination", "Status")},
            "traces_delivery_live_at_start": live_before,
            "gateway_config_sha256_before": cfg_hash_before,
        }
        print(f"F7-5 — tracing mutation, run_id={run_id}, region={region}")
        print(f"  Transaction Search {ts.get('Destination')}/{ts.get('Status')}; "
              f"TRACES delivery live={live_before}")
        if not live_before:
            raise ConfigError(
                "the main gateway's TRACES delivery is not live at start, so ON-1 cannot "
                "establish the instrument and the mutation has nothing to remove. Run "
                "`python3 infra/07_traces.py --ensure` first")

        # ---- ARM ON-1 ------------------------------------------------------------
        print(f"\n  [{ARM_ON1}] delivery live — sending {n} calls")
        on1 = _send_arm(fc, store, arm=ARM_ON1, gateway_url=gateway_url, run_id=run_id,
                        tool_name=tool_name, n=n, session_timeout_s=session_timeout_s)
        print(f"      outcomes={on1['outcomes']} real={on1['n_real_response']}/{n} "
              f"ids={on1['n_with_request_id']}")
        on1["join"] = _wait_for_arm_spans(tr, logs, gateway_arn, set(on1["request_ids"]),
                                          timeout_s=ON_WAIT_TIMEOUT_S)
        print(f"      joined {on1['join']['n_joined']} after "
              f"{on1['join']['elapsed_s']:.0f}s "
              f"(span names {on1['join']['query']['span_names']})")
        st["arms"][ARM_ON1] = on1

        # ---- the mutation --------------------------------------------------------
        found = tr.existing_delivery(logs, source_nm)
        if not found:
            raise ConfigError(
                f"no delivery found for source {source_nm}, so there is nothing to delete "
                f"even though traces_delivery_live read True moments ago")
        # The id is read LIVE, not from the ledger: if a previous run of this script died
        # between the delete and the re-record, the ledger's id is the dead one, and deleting
        # by it would appear to succeed at removing nothing while leaving tracing ON — the
        # OFF arm would then be measuring a live delivery.
        dlv_id = found["id"]
        common["mutated_object"]["delivery_id_live"] = dlv_id
        common["mutated_object"]["delivery_id_in_ledger"] = dlv_res.ids.get("delivery_id", "")
        print(f"\n  [mutate] delete_delivery id={dlv_id}")
        delete_attempted = True
        capture(store, "delete_delivery", logs, id=dlv_id).raise_for_status()
        live_after_delete = tr.traces_delivery_live(logs, run_id, "main")
        st["guards"]["delivery_deleted"] = not live_after_delete
        st["guard_detail"]["delivery_deleted"] = {
            "delivery_id": dlv_id, "live_after_delete": live_after_delete}
        print(f"      traces_delivery_live={live_after_delete}  "
              f"(settling {DELETE_SETTLE_S}s before OFF traffic)")
        time.sleep(DELETE_SETTLE_S)

        # ---- ARM OFF -------------------------------------------------------------
        print(f"  [{ARM_OFF}] delivery deleted — sending {n} calls")
        off = _send_arm(fc, store, arm=ARM_OFF, gateway_url=gateway_url, run_id=run_id,
                        tool_name=tool_name, n=n, session_timeout_s=session_timeout_s)
        print(f"      outcomes={off['outcomes']} real={off['n_real_response']}/{n} "
              f"ids={off['n_with_request_id']}")
        lag = float(on1["join"]["elapsed_s"] or 0.0)
        off_wait = max(float(OFF_WAIT_FLOOR_S), LAG_MULTIPLE * lag)
        st["off_wait_s"] = off_wait
        print(f"      waiting {off_wait:.0f}s (floor {OFF_WAIT_FLOOR_S}s, "
              f"{LAG_MULTIPLE}x measured lag {lag:.0f}s) before reading")
        time.sleep(off_wait)
        seen = _span_request_ids(tr, logs, gateway_arn, set(off["request_ids"]))
        hit = seen["ids"]
        off["join"] = {"joined": sorted(hit), "n_joined": len(hit),
                       "elapsed_s": off_wait, "timed_out": False,
                       "query": {k: v for k, v in seen.items() if k != "ids"}}
        print(f"      joined {len(hit)} of {len(off['request_ids'])} OFF request ids")
        st["arms"][ARM_OFF] = off

        # ---- restore, then ARM ON-2 ---------------------------------------------
        print(f"\n  [restore] recreating delivery for {source_nm}")
        restore = _restore(tr, logs, store, state, dlv_res, account_id=account_id,
                           source_nm=source_nm, gateway_arn=gateway_arn,
                           dest_nm=dest_nm, tags=tags)
        live_after_restore = tr.traces_delivery_live(logs, run_id, "main")
        # The ledger update is part of the guard, not a side note: a restored delivery the
        # ledger cannot delete is a leak, and a leak is a testbed defect this case caused.
        st["guards"]["delivery_restored"] = (
            bool(restore["ok"]) and live_after_restore and bool(restore["ledger_updated"]))
        st["guard_detail"]["delivery_restored"] = {
            "restore": restore, "live_after_restore": live_after_restore}
        print(f"      ok={restore['ok']} via={restore['path']} live={live_after_restore} "
              f"ledger_updated={restore['ledger_updated']} {restore.get('error', '')}")

        print(f"  [{ARM_ON2}] delivery restored — sending {n} calls")
        on2 = _send_arm(fc, store, arm=ARM_ON2, gateway_url=gateway_url, run_id=run_id,
                        tool_name=tool_name, n=n, session_timeout_s=session_timeout_s)
        print(f"      outcomes={on2['outcomes']} real={on2['n_real_response']}/{n} "
              f"ids={on2['n_with_request_id']}")
        on2["join"] = _wait_for_arm_spans(tr, logs, gateway_arn, set(on2["request_ids"]),
                                          timeout_s=ON_WAIT_TIMEOUT_S)
        print(f"      joined {on2['join']['n_joined']} after "
              f"{on2['join']['elapsed_s']:.0f}s")
        st["arms"][ARM_ON2] = on2

        # ---- remaining guards ---------------------------------------------------
        cfg_hash_after, _ = _config_hash(ac, gateway_id)
        st["guards"]["gateway_config_unchanged"] = cfg_hash_after == cfg_hash_before
        st["guard_detail"]["gateway_config_unchanged"] = {
            "sha256_before": cfg_hash_before, "sha256_after": cfg_hash_after}

        st["guards"]["on1_joins"] = on1["join"]["n_joined"] > 0
        st["guard_detail"]["on1_joins"] = {"n_joined": on1["join"]["n_joined"],
                                           "n_ids": len(on1["request_ids"]),
                                           "timed_out": on1["join"]["timed_out"]}
        st["guards"]["on2_joins"] = on2["join"]["n_joined"] > 0
        st["guard_detail"]["on2_joins"] = {"n_joined": on2["join"]["n_joined"],
                                           "n_ids": len(on2["request_ids"]),
                                           "timed_out": on2["join"]["timed_out"]}

        st["guards"]["off_calls_reached_gateway"] = (
            off["n_real_response"] == n and off["n_with_request_id"] == n)
        st["guard_detail"]["off_calls_reached_gateway"] = {
            "n_sent": off["n_sent"], "n_real_response": off["n_real_response"],
            "n_with_request_id": off["n_with_request_id"],
            "outcomes": off["outcomes"],
            "why": ("if the OFF calls had not reached a policy evaluation, 'no spans' would "
                    "be true because there was no request, and would read as evidence about "
                    "tracing")}

        sets = {k: set(st["arms"][k]["request_ids"]) for k in ARMS}
        overlaps = {f"{a}&{b}": sorted(sets[a] & sets[b])
                    for i, a in enumerate(ARMS) for b in ARMS[i + 1:] if sets[a] & sets[b]}
        st["guards"]["arms_disjoint"] = not overlaps
        st["guard_detail"]["arms_disjoint"] = {"overlaps": overlaps,
                                               "sizes": {k: len(v) for k, v in sets.items()}}

    except ConfigError as exc:
        rec = O.not_measured(CASE, f"the testbed was not in the state this case needs: {exc}",
                             partial=st.get("guards"))
        P.emit(CASE, rec, {**common, "config_error": str(exc), "restore": restore,
                           "partial_state": {k: v for k, v in st.items()
                                             if k != "arms"}}, store)
        return 2

    finally:
        # THE ONLY UNCONDITIONAL PROMISE THIS SCRIPT MAKES.
        #
        # Every failure mode above this line — a ConfigError, a botocore fault in the OFF arm,
        # a KeyboardInterrupt during a 10-minute sleep — happens while tracing is OFF, and
        # tracing is the shared precondition of F7-4, F3-10, the tau-sweep and F6's
        # server-side latency. A script that dies here does not merely fail its own case: it
        # silently converts every later span-derived reading into a vacuous zero. So the
        # restore is in a `finally`, gated on whether the delete was attempted and whether a
        # restore already ran, and it prints to stderr because a leak of this kind must be
        # visible to whoever is watching the terminal.
        if delete_attempted and not restore["attempted"]:
            print("\n  [finally] the run did not reach its own restore — recreating the "
                  "TRACES delivery now, because leaving tracing off would silently empty "
                  "every later span-derived case", file=sys.stderr)
            restore = _restore(tr, logs, store, state, dlv_res, account_id=account_id,
                               source_nm=source_nm, gateway_arn=gateway_arn,
                               dest_nm=dest_nm, tags=tags)
            print(f"  [finally] restore ok={restore['ok']} via={restore['path']} "
                  f"ledger_updated={restore['ledger_updated']} {restore.get('error', '')}",
                  file=sys.stderr)
            if not restore["ok"]:
                print("  [finally] RESTORE FAILED. Tracing is OFF for gateway/main. Run "
                      "`python3 infra/07_traces.py --ensure` before any other F7, F6, F3-10 "
                      "or tau-sweep case, and check state.json's delivery/main-traces id.",
                      file=sys.stderr)

    rec, extra = _evaluate(st, n_planned=PLANNED_N_PER_ARM)

    arm_summary = {
        k: {"n_sent": v["n_sent"], "n_real_response": v["n_real_response"],
            "n_request_ids": len(v["request_ids"]), "outcomes": v["outcomes"],
            "n_joined": v["join"]["n_joined"], "join_elapsed_s": v["join"]["elapsed_s"],
            "span_names_seen": v["join"]["query"]["span_names"],
            "query_truncated_at_limit": v["join"]["query"]["truncated_at_limit"]}
        for k, v in st["arms"].items()}

    P.emit(CASE, rec, {
        **common, **extra,
        "guards": st["guards"], "guard_detail": st["guard_detail"],
        "arms": arm_summary, "arms_full": st["arms"], "restore": restore,
        "off_wait_s": st["off_wait_s"],
        "verdict_rule": (
            "TRUE iff BOTH ON arms joined at least one of their own request ids to a span "
            "AND the OFF arm joined none of its own. Any guard failure yields INCONCLUSIVE "
            "rather than a verdict"),
        "verdict_reading": (
            "TRUE here means: with the vended TRACES delivery deleted, requests that "
            "demonstrably reached the gateway and received real policy decisions produced no "
            "span carrying their request ids, and the same traffic did produce such spans "
            "both before the delete and after the restore. It does NOT mean spans are "
            "complete while tracing is on — the ON arms establish presence, not coverage; "
            "F7-4 measures what those spans contain"),
        "what_this_unblocks": (
            "every other span-derived reading in the project. F7-4, F3-10, the τ-sweep that "
            "replaces F2-2/F2-3/F2-4 and F6's server-side latency all read aws/spans, and "
            "each would produce identical-looking output from a misconfigured delivery or a "
            "wrong window. This case is the shared precondition they were all resting on "
            "unverified, which is why DEV-P4-01 moved F7 upstream of them"),
        "expiry": (
            "this is a statement about how a vended delivery behaves on this service today. "
            "If AgentCore ever gains a gateway-level tracing field, the mutation changes "
            "shape and this script must be re-derived, not merely re-run"),
    }, store)

    ok = all(st["guards"].values()) and bool(restore["ok"])
    if not ok:
        print("\n  WARNING: guards or restore did not fully hold — see the record",
              file=sys.stderr)
    return 0 if (ok and rec["verdict"] in O.DECISIVE) else 2


if __name__ == "__main__":
    sys.exit(main())
