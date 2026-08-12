#!/usr/bin/env python3
"""F7-4: policy authorization appears in traces as its own span, per request.

    python3 f7_observability/02_span_operations.py --dry-run
    python3 f7_observability/02_span_operations.py --n 3      # smoke
    python3 f7_observability/02_span_operations.py            # n=20

Sealed oracle: "TRUE if AuthorizeAction-style spans appear for our gateway ARN; FALSE if
absent." Kind EXISTENCE, no pre-registered n, no mutation required.

THE SEALED SENTENCE IS AN EXISTENCE CLAIM, AND THIS SCRIPT DOES NOT QUIETLY STRENGTHEN IT
-----------------------------------------------------------------------------------------
"Spans appear for our gateway ARN" is satisfied by one span. Per-request coverage — *every*
request getting its own authorization span — is a strictly stronger property, and it is the
one an operator actually needs, because a decision log with gaps cannot be audited. Both are
measured, and they are kept apart on purpose:

    the VERDICT is decided on the sealed existence reading (>= 1 span joins),
    the COVERAGE RATE is reported beside it as the stronger statement, with its own
    interval, and it is NOT allowed to change the verdict.

Deciding the verdict on coverage instead would be re-writing a sealed oracle after seeing
the data, which is the failure mode the pre-registration exists to prevent. Reporting only
the sealed reading would throw away the more useful number. So both, labelled.

WHY THIS CASE IS NOT VACUOUS, AND WHAT IT OWES F7-5
---------------------------------------------------
An existence claim about telemetry is trivially confirmable by pointing at any rows that
happen to be in the log group. Three separate things stop that here:

1. `query_spans` filters every read to ONE gateway ARN. `aws/spans` is a **pre-existing
   shared** log group carrying other systems' spans (30-day retention, not ours), so an
   unfiltered query would return rows that read as our evidence.
2. The join is on **this run's own request ids**: the client reads `x-amzn-requestid` off the
   MCP response and the span carries `attributes.aws.request.id`. Rows that predate this
   script cannot satisfy it.
3. **F7-5** established, by deleting the vended TRACES delivery and putting it back, that
   spans appear here *because* of our delivery. Without that, "spans exist" would be
   compatible with the rows arriving through some other account-level configuration, and the
   presence reading would not be about our gateway's tracing at all.

(1) and (2) are enforced in this script. (3) is a precondition it can only *read*, so it
reads `results/phase1/F7-5.json` and records that verdict in its own payload. A missing or
non-TRUE F7-5 does not block this case — presence is still presence — but it is recorded,
because the reader is entitled to know which of the three legs was standing.

WHAT ELSE THIS RUN HARVESTS, AND WHY IT IS COLLECTED HERE RATHER THAN LATER
---------------------------------------------------------------------------
The same rows answer questions three other cases need, and re-fetching them later would be
a second sample of a different population:

- **the complete leaf-path inventory, per span name.** DEV-P4-01 rests on the absence of any
  score-shaped attribute. That entry's strongest support is the *complete* attribute
  inventory of the `AuthorizeAction` span — an absence in a complete enumeration is a
  property of the schema, not of the sample. Recorded here as data, so the claim is not prose.
- **the decision attributes** (`authorization_decision`, `log_only_matched_policies`,
  `log_only_decision_flipping_policies`, the policy-id fields). F3-10 needs the *decision*
  side of a score-decision join, and F4's LOG_ONLY findings gain an independent channel.
- **the latency attributes** (`latency_ms`, `overhead_latency_ms`, `execute_tool_latency_ms`).
  F6 was planned around client-side timing; these are server-side and per request, which
  removes the client's own network variance from the number.

None of these are scored here. They are written as evidence for the cases that own them,
which is why this script produces exactly one verdict.

A CORRECTION THIS CASE INHERITS
-------------------------------
An earlier session recorded, in prose, that `AgentCore.Policy.AuthorizeAction` spans do not
exist and that the decision was merely an attribute of the `InvokeTool` span. That was
**wrong and is retracted** (DEVIATIONS.md/DEV-P4-01, and RECONNECT.md): 246 such spans
existed over 48 h, paired 1:1 with `InvokeTool`, 27 of them inside the very sample the claim
was written from. The probe tallied leaf *paths* and never tallied span `name`, so no
assertion covered the sentence. This script therefore tallies span **names** as data — the
measurement whose absence let a wrong sentence stand — and expects the document to be
correct on this point.

COST
----
n `tools/call` on a Lambda target plus Logs Insights reads. **Zero text units**: no
guardrail term, no ApplyGuardrail, no model. No mutation, no resource created or changed.
"""

from __future__ import annotations

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
import stats as S                                        # noqa: E402
import testbed as T                                      # noqa: E402
from evidence import EvidenceStore                       # noqa: E402

FAMILY = "f7"
CASE = "F7-4"

# Module-level constants so `lib/tests/test_module_name_collisions.py` can resolve both
# by-path loads statically. The infra scripts start with a digit and cannot be imported by
# name at all.
TRACES_MODULE_NAME = "grx_infra_07_traces"
TRACES_PATH = ROOT / "infra" / "07_traces.py"

TOOL = "echo"
TEXT = "f7-4 span operations"
ARM = "traced"
PLANNED_N = 20

# The span whose existence is the sealed question. Matched on a PREFIX, not equality: the
# probe found the gateway publishes both `AgentCore.Gateway.InvokeTool` and the
# tool-qualified `AgentCore.Gateway.InvokeTool.grxecho___echo`, so an equality match on a
# name the service is free to qualify would report a real span as absent.
AUTHZ_SPAN_PREFIX = "AgentCore.Policy.AuthorizeAction"

REAL_RESPONSE_OUTCOMES = ("allowed", "policy_denied")

SPAN_WAIT_TIMEOUT_S = 420
SPAN_POLL_S = 20.0
JOIN_LOOKBACK_MIN = 180
JOIN_LIMIT = 500

# How long to wait, after the early read, before taking the coverage reading.
#
# 600s, and the number has a measurement behind it rather than a feeling: this script's first
# run read 15 of 20 request ids at +60s past the first join and 20 of 20 when the same ids were
# re-queried at roughly +11 minutes. The slowest of those twenty spans therefore took somewhere
# between 1 and 11 minutes to become queryable, and 600s sits above the only upper bound we
# have measured. F7-6 is the case that turns this into a distribution instead of a bound; until
# it runs, this constant is deliberately generous, because the cost of waiting is ten minutes
# and the cost of reading early is a false finding about gaps in an audit trail.
COVERAGE_SETTLE_S = 600

# Attribute groups harvested for other cases. Each is a list of leaf-path SUBSTRINGS, matched
# case-insensitively against the flattened path, so a service-side rename that keeps the word
# still lands in the right group.
HARVEST = {
    "decision": ("authorization_decision", "policy", "determining", "log_only", "mismatch"),
    "latency": ("latency", "duration", "elapsed", "time_ms"),
    "score_shaped": ("score", "confidence", "threshold", "guardrail", "probab", "sever"),
    "identity": ("request.id", "session", "trace", "span"),
}

GUARDS = ("calls_reached_gateway", "join_is_this_run", "no_truncation", "authz_span_named")

_ID_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


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


def _leaves(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten to leaf paths. Lists collapse to `[]` so 30 rows do not yield 30 path names."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_leaves(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        if not obj:
            out[f"{prefix}[]"] = []
        for v in obj:
            out.update(_leaves(v, f"{prefix}[]"))
    else:
        out[prefix] = obj
    return out


def _f7_5_precondition() -> dict[str, Any]:
    """Read F7-5's published verdict. Reported, never used to gate this case.

    A case that read another case's verdict and then *changed its own answer* would couple two
    results in a way no reader could unpick. This only records which of this case's three
    non-vacuity legs was actually standing.
    """
    p = ROOT / "results" / "phase1" / "F7-5.json"
    if not p.exists():
        return {"present": False, "verdict": "", "reading": (
            "F7-5 has not been published, so the claim that spans appear BECAUSE of our "
            "vended delivery is not yet established. This case's presence reading stands on "
            "the ARN filter and the per-request join alone")}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"present": True, "verdict": "", "error": str(exc)}
    v = (d.get("record") or d).get("verdict", "")
    return {"present": True, "verdict": v, "reading": (
        "F7-5 is TRUE, so deleting the vended TRACES delivery removed these spans and "
        "restoring it brought them back: the rows joined below are here because of our "
        "delivery, not because of some other account-level configuration"
        if v == O.TRUE else
        f"F7-5 published {v!r}, so the 'spans appear because of OUR delivery' leg is not "
        f"established. Presence below still holds — it is joined per request id — but it "
        f"is not evidence that our configuration is what produces it")}


def _query(tr, logs, gateway_arn: str, want: set[str]) -> dict[str, Any]:
    """Rows for exactly these request ids. Restricted at the QUERY, so it cannot truncate."""
    if not want:
        return {"rows": [], "n_rows": 0, "ids": set(), "truncated": False}
    bad = sorted(i for i in want if not _ID_SAFE.match(i))
    if bad:
        raise ConfigError(
            f"request id(s) {bad} do not match {_ID_SAFE.pattern} and cannot be "
            f"interpolated into a Logs Insights filter")
    clause = " or ".join(f'@message like "{i}"' for i in sorted(want))
    rows = tr.query_spans(logs, gateway_arn, minutes=JOIN_LOOKBACK_MIN, limit=JOIN_LIMIT,
                          extra_filter=f"filter {clause}")
    parsed: list[dict] = []
    ids: set[str] = set()
    for row in rows:
        msg = next((f["value"] for f in row if f.get("field") == "@message"), None)
        if not msg:
            continue
        try:
            obj = json.loads(msg)
        except json.JSONDecodeError:
            continue
        rid = (obj.get("attributes") or {}).get("aws.request.id")
        if rid in want:
            parsed.append(obj)
            ids.add(rid)
    return {"rows": parsed, "n_rows": len(rows), "ids": ids,
            "truncated": len(rows) >= JOIN_LIMIT}


def _inventory(rows: list[dict]) -> dict[str, Any]:
    """Per-span-name leaf-path inventory plus the harvest groups.

    Complete, not sampled: the point of DEV-P4-01's strongest support is that the
    `AuthorizeAction` span's attribute set is enumerated in full, so an absence in it is a
    property of the schema rather than of how many rows were looked at.
    """
    by_name: dict[str, dict[str, Any]] = {}
    for obj in rows:
        nm = obj.get("name") or "?"
        slot = by_name.setdefault(nm, {"n": 0, "paths": set()})
        slot["n"] += 1
        slot["paths"].update(_leaves(obj).keys())

    out: dict[str, Any] = {}
    for nm, slot in sorted(by_name.items()):
        paths = sorted(slot["paths"])
        groups = {g: sorted(p for p in paths
                            if any(k in p.lower() for k in keys))
                  for g, keys in HARVEST.items()}
        out[nm] = {"n_rows": slot["n"], "n_paths": len(paths), "paths": paths,
                   "harvest": groups}
    return out


def main(argv: list[str] | None = None) -> int:                     # noqa: PLR0915
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else PLANNED_N
    is_smoke = args.n is not None

    if args.dry_run:
        return P.dry_run_banner(
            CASE, [(ARM, "tool calls whose spans are then joined by request id", PLANNED_N)],
            operations={"tools/call": PLANNED_N},
            mutations=0, billable=False, text_units=0,
            text_units_why=("no guardrail term, no ApplyGuardrail and no model invocation: "
                            "this case reads telemetry about plain tool calls"),
            extra=[
                "the VERDICT is decided on the sealed EXISTENCE reading (>=1 AuthorizeAction "
                "span joins one of this run's request ids). Per-request COVERAGE is measured "
                "and reported beside it with its own interval, and is NOT allowed to move the "
                "verdict — deciding on coverage would be strengthening a sealed oracle after "
                "seeing the data",
                f"the span name is matched on the PREFIX {AUTHZ_SPAN_PREFIX!r}: the gateway "
                f"publishes both `AgentCore.Gateway.InvokeTool` and a tool-qualified "
                f"`...InvokeTool.<tool>`, so an equality match would report a real span absent",
                "three legs make an existence claim about telemetry non-vacuous: the ARN "
                "filter inside query_spans (aws/spans is a PRE-EXISTING SHARED group), the "
                "join on THIS RUN's request ids, and F7-5. The first two are enforced here; "
                "F7-5's verdict is read from results/phase1/F7-5.json and RECORDED, not used "
                "to gate this case",
                "the query is restricted to the arm's own request ids, so it cannot truncate; "
                "guard `no_truncation` treats hitting the row cap as an error rather than a "
                "reported caveat",
                "harvested for OTHER cases, not scored here: the COMPLETE per-span-name leaf "
                "path inventory (DEV-P4-01's strongest support is a complete enumeration of "
                "the AuthorizeAction span's attributes), the decision attributes (F3-10, F4's "
                "LOG_ONLY findings), and the server-side latency attributes (F6 gains a "
                "better instrument than client-side timing)",
                "an earlier prose claim that these spans do NOT exist is retracted "
                "(DEVIATIONS.md/DEV-P4-01). This script tallies span NAMES as data — the "
                "measurement whose absence let that sentence stand",
                f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}",
            ])

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    account_id = A.account_id(fc)
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()
    tr = _load_traces()
    logs = fc.client("logs")

    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    if not gw or not tgt:
        rec = O.not_measured(CASE, "the ledger carries no gateway/main or gateway-target/main",
                             remedy="run infra/04_gateway.py and infra/05_target.py first")
        P.emit(CASE, rec, {"instrument": "not built: incomplete ledger"}, store)
        return 2

    gateway_arn = T.unmask_arn(gw.arn, account_id)
    action_ids = list(tgt.ids.get("cedar_action_ids") or [])
    tool_name = next((a for a in action_ids if a.endswith(f"___{TOOL}")), "")

    common: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(), "n_planned": PLANNED_N, "n_sent": n,
        "gateway_id": gw.ids["gateway_id"], "tool_name": tool_name,
        "span_name_matched_by_prefix": AUTHZ_SPAN_PREFIX,
        "log_group": tr.SPANS_LOG_GROUP,
        "guard_names": list(GUARDS),
        "non_vacuity_legs": {
            "arn_filter": ("query_spans filters every read to one gateway ARN; aws/spans is a "
                           "pre-existing shared group carrying other systems' spans"),
            "per_request_join": ("the join is on this run's own x-amzn-requestid values, so "
                                 "rows predating this script cannot satisfy it"),
            "f7_5": "read below; recorded, not used to gate this case",
        },
        "f7_5_precondition": _f7_5_precondition(),
    }

    if not tool_name:
        rec = O.not_measured(
            CASE, f"gateway-target/main carries no Cedar action id ending in '___{TOOL}' "
                  f"(saw {action_ids}), so no tool call can be addressed",
            remedy="re-run infra/05_target.py")
        P.emit(CASE, rec, {**common, "instrument": "not built: no tool name"}, store)
        return 2

    print(f"F7-4 — span operations, run_id={run_id}, region={region}")
    try:
        client = M.client_for(gw.ids["gateway_url"], fc, store=store,
                              policy_session_id=M.policy_session_id(run_id, ARM),
                              session_timeout_s=int(gw.ids.get("session_timeout_s", 900)))
        client.initialize()
        trials = []
        for i in range(1, n + 1):
            client.refresh_if_stale()
            d = client.call_tool(tool_name, {"text": f"{TEXT} {i}"})
            trials.append({"i": i, "outcome": d.outcome, "request_id": d.request_id,
                           "http_status": d.http_status})
    except M.McpTransportError as exc:
        rec = O.not_measured(
            CASE, f"the MCP client could not be established or used, so no request was made "
                  f"whose span could be looked for: {exc}")
        P.emit(CASE, rec, {**common, "transport_error": str(exc)}, store)
        return 2

    real = [t for t in trials if t["outcome"] in REAL_RESPONSE_OUTCOMES and t["request_id"]]
    want = {t["request_id"] for t in real}
    print(f"  sent {len(trials)}, real {len(real)}, distinct request ids {len(want)}")

    try:
        # Poll until the first join, then read once more after a settle so the reading is not
        # taken at the instant the first row landed: coverage measured the moment the earliest
        # span appears would under-report the others purely because they had not arrived yet.
        t0 = time.monotonic()
        q: dict[str, Any] = {"rows": [], "ids": set(), "n_rows": 0, "truncated": False}
        while True:
            q = _query(tr, logs, gateway_arn, want)
            if q["ids"]:
                break
            if time.monotonic() - t0 >= SPAN_WAIT_TIMEOUT_S:
                break
            time.sleep(SPAN_POLL_S)
        first_join_s = time.monotonic() - t0
        early: dict[str, Any] = {}
        if q["ids"]:
            print(f"  first join after {first_join_s:.0f}s; settling {SPAN_POLL_S * 3:.0f}s "
                  f"then re-reading")
            time.sleep(SPAN_POLL_S * 3)
            q = _query(tr, logs, gateway_arn, want)
            early = {"elapsed_s": round(time.monotonic() - t0, 1),
                     "n_ids_joined": len(q["ids"])}

            # A SECOND, LATER READ — because the first one is confounded with publish lag.
            #
            # This is not belt-and-braces; it is a correction. The first version of this script
            # took one reading a minute after the first span landed, got 15 of 20 requests
            # carrying an authorization span, and was about to report "coverage 0.75, and a
            # coverage materially below 1.0 is a finding in its own right — a decision log with
            # gaps cannot be audited". Re-reading the SAME 20 request ids about eleven minutes
            # later returned 20 of 20. The five "missing" spans were not missing; they had not
            # been published yet.
            #
            # So a coverage number is only a coverage number once publishing has finished. Read
            # too early it is a LOWER BOUND, and reporting it as a gap in the audit trail would
            # have put a false correction into the v1.3 amendment pass — a defect in the
            # document that the document does not have. Both reads are kept and labelled: the
            # early one is what an operator polling immediately would see (useful, and F7-6's
            # subject), the late one is the coverage claim.
            print(f"  early read: {len(q['ids'])}/{len(want)} ids joined; "
                  f"waiting {COVERAGE_SETTLE_S}s for the publish lag to clear")
            time.sleep(COVERAGE_SETTLE_S)
            q_late = _query(tr, logs, gateway_arn, want)
            if len(q_late["ids"]) >= len(q["ids"]):
                q = q_late            # never regress: the later read is the superset
            else:
                early["late_read_returned_fewer"] = {
                    "n_early": len(q["ids"]), "n_late": len(q_late["ids"]),
                    "handling": ("kept the earlier, larger read and recorded this. Logs "
                                 "Insights scans a time window, so a later query can drop "
                                 "rows that aged past the lookback; that is a property of the "
                                 "query, not of the telemetry")}
    except ConfigError as exc:
        rec = O.not_measured(CASE, f"the span query could not be trusted: {exc}")
        P.emit(CASE, rec, {**common, "config_error": str(exc)}, store)
        return 2

    inv = _inventory(q["rows"])
    authz_names = [nm for nm in inv if nm.startswith(AUTHZ_SPAN_PREFIX)]
    authz_ids = {obj["attributes"]["aws.request.id"] for obj in q["rows"]
                 if (obj.get("name") or "").startswith(AUTHZ_SPAN_PREFIX)
                 and (obj.get("attributes") or {}).get("aws.request.id")}

    guards = {
        "calls_reached_gateway": len(real) == n,
        "join_is_this_run": bool(q["ids"]) and q["ids"] <= want,
        "no_truncation": not q["truncated"],
        "authz_span_named": bool(authz_names),
    }
    guard_detail = {
        "calls_reached_gateway": {"n_sent": len(trials), "n_real": len(real),
                                  "outcomes": sorted({t["outcome"] for t in trials})},
        "join_is_this_run": {"n_joined": len(q["ids"]), "n_wanted": len(want),
                             "first_join_s": first_join_s},
        "no_truncation": {"n_rows": q["n_rows"], "limit": JOIN_LIMIT},
        "authz_span_named": {"names_matching_prefix": authz_names,
                             "all_span_names": {k: v["n_rows"] for k, v in inv.items()}},
    }

    failed = [k for k, v in guards.items() if not v]
    if failed:
        rec = O.not_measured(
            CASE, "guard(s) " + ", ".join(failed) + " did not hold, so a presence reading "
            "would not be about this run's requests on this gateway",
            guards=guards, guard_detail=guard_detail)
        P.emit(CASE, rec, {**common, "guards": guards, "guard_detail": guard_detail,
                           "span_inventory": inv}, store)
        return 2

    # The sealed reading: at least one AuthorizeAction-style span for our gateway ARN.
    observed = bool(authz_ids)
    # The stronger reading, reported and NOT used for the verdict.
    n_covered = len(authz_ids)
    coverage = n_covered / len(want) if want else 0.0
    cov_ci = S.wilson_ci(n_covered, len(want), level=0.95) if want else None

    o = P.obs_existence(
        CASE, observed, n=len(want),
        n_request_ids=len(want), n_joined_any_span=len(q["ids"]),
        n_with_authz_span=n_covered,
        span_names=sorted(inv), authz_span_names=authz_names,
        first_join_s=first_join_s)
    rec = O.evaluate(o)

    P.emit(CASE, rec, {
        **common,
        "guards": guards, "guard_detail": guard_detail,
        "trials": trials,
        "join": {"n_wanted": len(want), "n_joined_any": len(q["ids"]),
                 "n_rows": q["n_rows"], "first_join_s": first_join_s,
                 "truncated": q["truncated"]},
        "span_inventory": inv,
        "sealed_reading": {
            "observed_bool": observed,
            "rule": (f"TRUE iff at least one span whose name starts with "
                     f"{AUTHZ_SPAN_PREFIX!r} carries one of this run's request ids"),
        },
        "coverage_reading_not_scored": {
            "n_with_authz_span": n_covered, "n_request_ids": len(want),
            "coverage": round(coverage, 6),
            "wilson_95_lo": None if cov_ci is None else round(cov_ci.lo, 6),
            "wilson_95_hi": None if cov_ci is None else round(cov_ci.hi, 6),
            "why_not_scored": (
                "the sealed oracle is an existence claim, satisfied by one span. Per-request "
                "coverage is the property an auditor needs, and it is strictly stronger — so "
                "it is measured and reported, but deciding the verdict on it would be "
                "strengthening a sealed oracle after seeing the data"),
            "reading": (
                f"{n_covered} of {len(want)} requests carry their own authorization span, read "
                f"after a {COVERAGE_SETTLE_S}s settle. Coverage below 1.0 is only a finding if "
                f"publishing had finished — see `read_timing` below, which is why this number "
                f"is taken late and not at the first join"),
            "read_timing": {
                "early_read": early,
                "coverage_settle_s": COVERAGE_SETTLE_S,
                "why_two_reads": (
                    "a coverage number taken before the publish lag has cleared is a LOWER "
                    "BOUND, not a gap. This script's first run read 15 of 20 at ~60s past the "
                    "first join and 20 of 20 when the same ids were re-queried ~11 minutes "
                    "later: the five 'missing' authorization spans existed and had simply not "
                    "been published. Reporting the early number as a gap would have put a "
                    "correction into v1.3 for a defect the document does not have"),
                "who_owns_the_lag": (
                    "F7-6. The bound here (somewhere between 1 and 11 minutes for the slowest "
                    "of twenty spans) is what set COVERAGE_SETTLE_S; F7-6 replaces the bound "
                    "with a distribution"),
            },
        },
        "harvested_for_other_cases": {
            "note": ("collected here because the same rows answer these questions, and a "
                     "later re-fetch would sample a different population. NOT scored here"),
            "dev_p4_01": ("the COMPLETE leaf-path inventory per span name is in "
                          "`span_inventory`; the `score_shaped` harvest group is the list "
                          "DEV-P4-01 claims is empty, now as data rather than prose"),
            "f3_10": "the `decision` harvest group is the left-hand side F3-10 needs",
            "f6": ("the `latency` harvest group is server-side and per request, which removes "
                   "the client's network variance from F6's numbers"),
        },
        "verdict_rule": (
            "TRUE iff >=1 AuthorizeAction-prefixed span joins one of this run's request ids, "
            "with all four guards holding. Any guard failure is INCONCLUSIVE, not a verdict"),
        "verdict_reading": (
            "TRUE means policy authorization is observable as its own span, joinable to a "
            "specific client request, on the gateway whose ARN this query filtered to. It "
            "does NOT mean every request produces one (see the coverage reading), and it does "
            "not say anything about what those spans contain — the attribute inventory is "
            "recorded as data for the cases that own those questions"),
        "what_true_does_not_prove": (
            "that the spans are complete, that they are timely (F7-6 measures publish lag), "
            "or that they carry a numeric guardrail score (DEV-P4-01 says they do not, and "
            "the `score_shaped` group here is where that would show up if it were wrong)"),
        "family_note": (
            "F7-4's presence reading is only about OUR configuration because F7-5 removed the "
            "delivery and the spans went away. That is why F7-5 runs first"),
        "expiry": (
            "a statement about the span schema this service publishes today. Span names and "
            "attribute paths are service-owned and can change without notice, so the "
            "inventory is timestamped evidence, not a stable contract"),
    }, store)
    return 0 if rec["verdict"] in O.DECISIVE else 2


if __name__ == "__main__":
    sys.exit(main())
