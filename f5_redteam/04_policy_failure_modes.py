#!/usr/bin/env python3
"""F5-4a — what does a policy that CANNOT EVALUATE do? Deny, allow, or refuse to be created?

The sealed oracle for this case is `RECORDED`: "OUTCOME UNKNOWN — that is the experiment."
F5-4a and F5-4b are the only two cases in the whole pre-registration with that kind, because
nothing was predicted. AWS documents neither answer, and both are findings.

What "cannot evaluate" means here, and why it is two mechanisms and not one
--------------------------------------------------------------------------
A Cedar policy in an AgentCore policy engine can reference request data two ways, and they are
evaluated by different machinery:

* a **guardrails block** — `BedrockGuardrails::ContentFilter(["HATE"], [context.input.text])`,
  whose bracketed *data paths* are extracted from the request and handed to Bedrock Guardrails;
* a **standard condition** — `when { context.input.text == "x" }`, evaluated by Cedar itself.

Point either at an attribute the request does not carry and the policy becomes unevaluable, but
by two different routes. §7.1's own metric table distinguishes them: `MismatchErrors` is
documented as a *guardrail* evaluation failing on missing attributes, while
`LogOnlyEvalIncomplete` is an *evaluation* that cannot complete. A design that broke only one
path would report one mechanism's behaviour under the other's name, so both are arms.

The five arms, which differ ONLY in the policy
----------------------------------------------
Every arm sends the byte-identical HATE payload to the byte-identical gateway action. Nothing
varies but the policy on the engine, which is what makes the contrast readable:

| arm | policy on the engine | expected |
|:---|:---|:---|
| `control_no_probe`      | baseline permit only                          | ALLOW |
| `guardrail_valid_path`  | forbid, guardrails block on `context.input.text` | DENY |
| `guardrail_missing_path`| the same forbid, path replaced by a nonexistent one | **unknown** |
| `cedar_missing_attr`    | forbid, plain `when` on a nonexistent attribute | **unknown** |
| `guardrail_missing_logonly` | the missing-path forbid, but `LOG_ONLY`     | ALLOW by construction |

Arms 1 and 2 are not decoration — they are what makes arms 3 and 4 attributable. An ALLOW in
arm 3 has at least three explanations: the unevaluable policy was skipped; forbids never deny
on this engine; or the payload never tripped anything. Arm 2 kills the second (the same forbid
with a working path DENIES) and arm 1 kills the third by showing the request is allowed when our
policy is absent, so the DENY in arm 2 belongs to our policy and not to something ambient.
Without that bracket this case would publish "fail-open" from a broken harness — the DEV-P1-18
failure mode, where a filter that never ran was published as a filter that found nothing.

Arm 5 exists because `LOG_ONLY` cannot deny. If the metrics light up there, the engine noticed
the broken policy; a *silent* fail-open in arm 3 plus a lit metric in arm 5 is a different and
much more reportable finding than a silent fail-open alone.

Three outcomes, not two — the service gets a chance to refuse first
-------------------------------------------------------------------
"Fails open or closed" presupposes the broken policy reaches the request path at all. It might
not: `CreatePolicy` takes a `validationMode`, and `FAIL_ON_ANY_FINDINGS` may well reject a
nonexistent data path at authoring time, which would be the *best* outcome for the document and
is invisible to any design that only ever creates policies under `IGNORE_ALL_FINDINGS`. So each
broken arm attempts creation **twice**: first under `FAIL_ON_ANY_FINDINGS`, recording whether
the service caught it, then — whatever the answer — under `IGNORE_ALL_FINDINGS` to observe the
runtime behaviour. Both readings are published. A policy that settles `CREATE_FAILED` is a
third outcome and is reported as such rather than folded into "allow".

What this case can retire in F7-3
---------------------------------
F7-3 recorded `MismatchErrors`, `TotalMismatchedPolicies`, `PolicyMismatch` and
`LogOnlyEvalIncomplete` as `NOT_EXERCISED`, with the reason: reproducing them "means shipping a
deliberately broken policy, which would also perturb the axis F4 measures". F4 is complete. The
objection was scheduling, not principle, and it has expired — so this run reads those four
metrics before and after, and whatever it finds is evidence F7-3 could not collect. The reading
is published under this case and does NOT rewrite F7-3's sealed verdict.

Attribution of the metrics is by DIFFERENCE IN TIME, not by name
----------------------------------------------------------------
`AWS/Bedrock-AgentCore` is an account-wide namespace and this account runs other people's
agents. A datapoint on `MismatchErrors` inside our window is not ours merely because we were
also running. So each metric is read over a baseline window ending before the probe is created
AND over the probe window, and only a metric that is ABSENT before and PRESENT after is reported
as exercised by us. A metric already firing in the baseline window is reported as
`ambient` — honest, and not evidence either way.

Interlock: this script must not run beside another case
------------------------------------------------------
It creates a `forbid` on the SHARED policy engine, which every gateway request in the account's
testbed passes through. Run it while F6-6/7/8 is timing turns and it does not merely add load —
it denies that case's requests and silently destroys its data. `_assert_engine_is_quiet` refuses
to start if any policy other than `baseline` is registered in the ledger, because a live probe
belonging to another script is exactly what that looks like. Per
feedback_capacity_race_guard: the guard that stops the loser has to actually run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import cedar as C        # noqa: E402
import checkpoint as K   # noqa: E402
import mcp as M          # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
import testbed as T      # noqa: E402
from evidence import EvidenceStore, capture  # noqa: E402

FAMILY = "f5"
CASE = "F5-4a"

# One definition of "terminal", taken from the provisioner rather than copied.
_spec = importlib.util.spec_from_file_location(
    "_grx_policy_engine", ROOT / "infra" / "03_policy_engine.py")
_pe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pe)
wait_status = _pe.wait_status
TERMINAL_OK = _pe.TERMINAL_OK
TERMINAL_BAD = _pe.TERMINAL_BAD

TOOL = "echo"

# The working guardrail clause, identical to F6-6/7/8's probe so that "a forbid CAN deny here"
# is demonstrated by a statement already known to work on this engine.
GUARDRAIL_FUNCTION = "ContentFilter"
GUARDRAIL_CATEGORY = "HATE"
VALID_PATH = "context.input.text"
GUARDRAIL_THRESHOLD = "0.2"

# The broken path. `context.input` is a real record on this request; `doesNotExist` is not one of
# its attributes. Chosen over a wholly invented root (`context.nonsense.x`) deliberately: a
# missing attribute on a record that DOES exist is the mistake a real author makes, and it is
# the one §7.1's `MismatchErrors` description names ("missing attributes").
MISSING_PATH = "context.input.doesNotExist"

VALIDATION_STRICT = "FAIL_ON_ANY_FINDINGS"
VALIDATION_LAX = "IGNORE_ALL_FINDINGS"
MODE_ENFORCE = "ACTIVE"
MODE_LOG_ONLY = "LOG_ONLY"

HATE_CORPUS = ROOT / "corpora" / "content_filter" / "hate.jsonl"

# E-class: the mechanism is deterministic or it is not a mechanism. n is small and the reading is
# all-or-nothing per arm — a split arm is itself a finding and is reported, never averaged.
PLANNED_N = 20

ARM_CONTROL = "control_no_probe"
ARM_VALID = "guardrail_valid_path"
ARM_MISSING = "guardrail_missing_path"
ARM_CEDAR = "cedar_missing_attr"
ARM_LOGONLY = "guardrail_missing_logonly"
ARMS = (ARM_CONTROL, ARM_VALID, ARM_MISSING, ARM_CEDAR, ARM_LOGONLY)

# The arms whose outcome the pre-registration declares unknown. Named so no later edit can
# quietly move an arm into or out of the set whose result is the finding.
UNKNOWN_ARMS = (ARM_MISSING, ARM_CEDAR)
# Arms that ship a policy the service may legitimately refuse to create.
BROKEN_ARMS = (ARM_MISSING, ARM_CEDAR, ARM_LOGONLY)

NS = "AWS/Bedrock-AgentCore"
MISMATCH_METRICS = ("MismatchErrors", "TotalMismatchedPolicies", "PolicyMismatch",
                    "LogOnlyEvalIncomplete")

# How long to wait for CloudWatch to publish, and how often to look. Bounded and recorded: the
# first appearance time is reported, so this is a measurement rather than an assumption.
METRIC_POLL_MAX_S = 900
METRIC_POLL_EVERY_S = 60
# The baseline window ends before the first probe is created. Kept wide enough to catch an
# ambient publisher on a slow cadence.
BASELINE_WINDOW_MIN = 60

# Upper bounds on the resource mutations, for the dry-run banner. One `CreatePolicy` per arm
# that has a policy at all, plus one extra strict-validation attempt per broken arm; one
# `DeletePolicy` per policy that was actually created. Bounds, not counts: how many strict
# attempts are ACCEPTED is one of the things this case is measuring.
MAX_CREATES = (len(ARMS) - 1) + len(BROKEN_ARMS)
MAX_DELETES = len(ARMS) - 1

DELETE_ATTEMPTS = 4
DELETE_SLEEP_S = 3
INTER_CALL_S = 0.1

GUARDS = ("engine_was_quiet_at_start",
          "control_arm_was_allowed",
          "valid_path_arm_was_denied",
          "every_arm_reached_the_gateway",
          "probe_was_deleted")


class ConfigError(RuntimeError):
    """The testbed is not in the state this case needs. Never a verdict."""


# ---------------------------------------------------------------------------
# the interlock
# ---------------------------------------------------------------------------

def _assert_engine_is_quiet(state: T.State) -> dict[str, Any]:
    """Refuse to start if another case's probe policy is live on the shared engine.

    See the module docstring. The ledger is the channel that can see this: `policy` resources
    take no tags, so every script that creates one registers it in `state.json` and removes it
    in a `finally`. A leftover entry therefore means either a live run or a crashed one, and
    both are reasons not to add a `forbid` to the engine those requests pass through.
    """
    others = [r for r in state.of_kind("policy") if r.logical != "baseline"]
    if others:
        raise ConfigError(
            "the shared policy engine is not quiet: "
            + ", ".join(f"{r.logical} ({r.ids.get('policy_id')})" for r in others)
            + ". Another case's probe policy is registered, so a `forbid` created here would "
              "change that case's decisions and destroy its data. Wait for it to finish, or if "
              "it crashed, delete the policy and drop the ledger entry first.")
    return {"policies_on_engine_at_start": [r.logical for r in state.of_kind("policy")],
            "checked": "state.json policy resources other than `baseline`"}


# ---------------------------------------------------------------------------
# statements
# ---------------------------------------------------------------------------

def _guardrail_forbid(gateway_arn: str, action_id: str, *, path: str) -> str:
    """The forbid whose only variable is the guardrail data path."""
    return C.statement(
        "forbid", resource=C.gateway_resource(gateway_arn),
        action=f'action == {C.ENTITY_ACTION}::"{action_id}"',
        when_guardrails=C.guardrail_condition(
            GUARDRAIL_FUNCTION, [GUARDRAIL_CATEGORY], [path],
            threshold=GUARDRAIL_THRESHOLD))


def _cedar_forbid(gateway_arn: str, action_id: str) -> str:
    """A forbid whose PLAIN condition reads an attribute the request does not carry.

    Not a guardrails block: this arm is about Cedar's own evaluation, which is a different
    engine from the one `MismatchErrors` describes. The comparison value is a string literal so
    the only thing that can fail is the attribute access.
    """
    return C.statement(
        "forbid", resource=C.gateway_resource(gateway_arn),
        action=f'action == {C.ENTITY_ACTION}::"{action_id}"',
        when=f'{MISSING_PATH} == "grx-value-that-is-never-compared"')


def _statement_for(arm: str, gateway_arn: str, action_id: str) -> str | None:
    if arm == ARM_CONTROL:
        return None
    if arm == ARM_VALID:
        return _guardrail_forbid(gateway_arn, action_id, path=VALID_PATH)
    if arm in (ARM_MISSING, ARM_LOGONLY):
        return _guardrail_forbid(gateway_arn, action_id, path=MISSING_PATH)
    if arm == ARM_CEDAR:
        return _cedar_forbid(gateway_arn, action_id)
    raise ValueError(f"unknown arm {arm!r}")


def _mode_for(arm: str) -> str:
    return MODE_LOG_ONLY if arm == ARM_LOGONLY else MODE_ENFORCE


# ---------------------------------------------------------------------------
# the probe policy
# ---------------------------------------------------------------------------

def _attempt_create(ac, store: EvidenceStore, *, name: str, engine_id: str, statement: str,
                    mode: str, validation: str, arm: str) -> dict[str, Any]:
    """One `CreatePolicy` attempt. Returns a reading; never raises on a rejection.

    A rejection is DATA here, not an error: whether the service catches a nonexistent data path
    at authoring time is one of this case's three possible outcomes.
    """
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac, name=name, policyEngineId=engine_id,
                  definition={"policy": {"statement": statement}},
                  description=f"F5-4a probe: {arm} ({validation}, {mode})",
                  validationMode=validation, enforcementMode=mode)
    out: dict[str, Any] = {
        "arm": arm, "validation_mode": validation, "enforcement_mode": mode,
        "accepted": bool(rec.ok), "http_status": rec.http_status,
        "request_id": rec.request_id,
        "error_code": rec.error_code or None, "error_message": rec.error_message or None,
        "policy_id": (rec.response or {}).get("policyId") if rec.ok else None,
    }
    return out


def _create_probe(ac, store: EvidenceStore, state: T.State, *, arm: str, engine_id: str,
                  run_id: str, statement: str) -> dict[str, Any]:
    """Create one arm's probe, recording the strict-validation answer on the way.

    Order matters and is fixed here: strict first. Doing it the other way round would leave a
    policy of the same name in place and turn the strict attempt's rejection into a name
    collision, which reads exactly like the validation catching the broken path.
    """
    mode = _mode_for(arm)
    lint = C.check_statement(statement)
    attempts: list[dict[str, Any]] = []
    strict_name = T.check_name(ac, "CreatePolicy", f"grx_f54a_{_slug(arm)}s_{run_id}")
    lax_name = T.check_name(ac, "CreatePolicy", f"grx_f54a_{_slug(arm)}_{run_id}")

    strict = None
    if arm in BROKEN_ARMS:
        strict = _attempt_create(ac, store, name=strict_name, engine_id=engine_id,
                                 statement=statement, mode=mode, validation=VALIDATION_STRICT,
                                 arm=arm)
        attempts.append(strict)
        if strict["accepted"]:
            # It was accepted under strict validation, so THAT is the policy under test — using
            # it avoids creating a second, identical policy on the same engine, which would put
            # two forbids in the request path and make a DENY unattributable to either.
            pid = strict["policy_id"]
            return _register(ac, store, state, arm=arm, engine_id=engine_id, policy_id=pid,
                             name=strict_name, statement=statement, mode=mode,
                             validation=VALIDATION_STRICT, lint=lint, attempts=attempts)

    lax = _attempt_create(ac, store, name=lax_name, engine_id=engine_id, statement=statement,
                          mode=mode, validation=VALIDATION_LAX, arm=arm)
    attempts.append(lax)
    if not lax["accepted"]:
        return {"arm": arm, "created": False, "attempts": attempts, "lint": lint,
                "statement": statement, "policy_id": None, "status": None,
                "outcome": "refused_at_creation",
                "reading": ("the service refused to create this policy under BOTH validation "
                            "modes, so it never reached the request path. That is a finding: "
                            "the trap is caught at authoring time.")
                if arm in BROKEN_ARMS else
                        ("a policy this case needs in order to have a control could not be "
                         "created; the arm is unusable, not permissive.")}
    return _register(ac, store, state, arm=arm, engine_id=engine_id,
                     policy_id=lax["policy_id"], name=lax_name, statement=statement, mode=mode,
                     validation=VALIDATION_LAX, lint=lint, attempts=attempts)


def _register(ac, store: EvidenceStore, state: T.State, *, arm: str, engine_id: str,
              policy_id: str, name: str, statement: str, mode: str, validation: str,
              lint: list[str], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Register in the ledger BEFORE waiting on status, so a crash mid-wait is still cleanable."""
    state.record(T.Resource(
        kind="policy", logical=f"f54a_{_slug(arm)}", name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": policy_id},
        ids={"policy_engine_id": engine_id, "policy_id": policy_id, "statement": statement,
             "enforcement_mode_at_create": mode, "validation_mode_sent": validation},
        arn="", delete_priority=40,
        notes=("F5-4a probe, deliberately unevaluable. `policy` takes no tags, so this ledger "
               "entry and this script's finally are the only channels that can find it.")))
    state.write()
    live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": policy_id})
    status = live.get("status")
    return {
        "arm": arm, "created": True, "attempts": attempts, "lint": lint,
        "statement": statement, "policy_id": policy_id, "policy_name": name,
        "enforcement_mode": mode, "validation_mode_accepted_under": validation,
        "status": status, "status_reasons": live.get("statusReasons"),
        "settled_ok": status in TERMINAL_OK,
        "outcome": ("active" if status in TERMINAL_OK else "create_failed"),
        "reading": (None if status in TERMINAL_OK else
                    "the policy was accepted by the API and then settled in a failed state, so "
                    "it never enforced. Distinct from both a rejection and a fail-open."),
    }


def _slug(arm: str) -> str:
    """Policy names must match `[A-Za-z][A-Za-z0-9_]*` within 48 chars (DEV-P2-02)."""
    return {ARM_VALID: "valid", ARM_MISSING: "miss", ARM_CEDAR: "cedar",
            ARM_LOGONLY: "misslog"}[arm]


def _delete_probe(ac, store: EvidenceStore, state: T.State, *, arm: str, engine_id: str,
                  policy_id: str) -> dict[str, Any]:
    """Delete one probe. Never raises: this runs in a finally."""
    errors: list[str] = []
    logical = f"f54a_{_slug(arm)}"
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac, policyEngineId=engine_id, policyId=policy_id)
        if rec.ok or rec.error_code == "ResourceNotFoundException":
            state.drop("policy", logical)
            state.write()
            return {"deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}: {rec.error_message}")
        time.sleep(DELETE_SLEEP_S)
    return {"deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors,
            "manual_remedy": f"delete_policy policyEngineId={engine_id} policyId={policy_id}"}


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------

def _corpus(path: Path, n: int) -> list[dict]:
    items: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
            if len(items) >= n:
                break
    if len(items) < n:
        raise ConfigError(f"{path} has {len(items)} items, need {n}")
    return items


def _run_arm(client, cp: K.Checkpoint, *, arm: str, action_id: str,
             items: list[dict]) -> dict[str, Any]:
    """Send this arm's requests and tally the decisions.

    Keyed by item id so a resume pairs by item and not by position, and so a retried trial
    replaces its own row rather than appending a second one.
    """
    for i, item in enumerate(items):
        tid = f"{arm}__{item.get('id', i)}"
        if cp.is_done(tid):
            continue

        def _one(it=item):
            d = client.call_tool(action_id, {"text": it["text"]})
            return {"arm": arm, "item_id": it.get("id"),
                    "denied": bool(d.denied), "ran": bool(d.ran),
                    "http_status": d.http_status, "decision": d.to_json()}

        cp.run_trial(tid, _one)
        time.sleep(INTER_CALL_S)

    rows = {k: v for k, v in cp.results().items() if v.get("arm") == arm}
    denied = sum(1 for v in rows.values() if v.get("denied"))
    reached = sum(1 for v in rows.values() if v.get("http_status") is not None)
    return {
        "arm": arm, "n_usable": len(rows), "n_denied": denied,
        "n_allowed": len(rows) - denied, "n_reached_gateway": reached,
        "unanimous": len(rows) > 0 and denied in (0, len(rows)),
        "decision": ("DENY" if len(rows) and denied == len(rows)
                     else "ALLOW" if len(rows) and denied == 0 else "SPLIT"),
    }


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def _read_metric(cw, store: EvidenceStore, metric: str, *, start: datetime,
                 end: datetime) -> dict[str, Any]:
    """Sum a mismatch metric over one window, across every dimension combination it publishes.

    Read with no `Dimensions` filter and then per discovered combination: `AWS/Bedrock-AgentCore`
    documents no per-policy dimension for these four metrics, so pinning a guess would report
    absence for a metric that published under a name we did not ask for
    (feedback_missing_check_is_not_pass).
    """
    A.limiter().wait("ListMetrics")
    lm = capture(store, "list_metrics", cw, Namespace=NS, MetricName=metric)
    combos = [m.get("Dimensions") or [] for m in ((lm.response or {}).get("Metrics") or [])]
    total = 0.0
    points: list[dict[str, Any]] = []
    for dims in combos or [[]]:
        A.limiter().wait("GetMetricStatistics")
        rec = capture(store, "get_metric_statistics", cw, Namespace=NS, MetricName=metric,
                      Dimensions=dims, StartTime=start, EndTime=end, Period=60,
                      Statistics=["Sum", "SampleCount"])
        for dp in ((rec.response or {}).get("Datapoints") or []):
            total += float(dp.get("Sum") or 0.0)
            points.append({"dimensions": dims, "timestamp": dp.get("Timestamp"),
                           "sum": dp.get("Sum"), "sample_count": dp.get("SampleCount")})
    return {"metric": metric, "sum": total, "n_datapoints": len(points),
            "dimension_combinations_listed": len(combos), "datapoints": points,
            "window": {"start": start, "end": end}}


def _metric_verdict(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Only absent-then-present counts as exercised BY US. See the module docstring."""
    if before["sum"] > 0:
        return "ambient"          # something else in the account was already publishing it
    if after["sum"] > 0:
        return "exercised"
    return "absent"


def _poll_metrics(cw, store: EvidenceStore, *, probe_start: datetime,
                 baseline: dict[str, dict]) -> dict[str, Any]:
    """Wait, bounded, for any mismatch metric to appear; record when it first did.

    Returns as soon as every metric is decided or the bound is reached. The first-appearance
    delay is reported rather than assumed, so this is a measurement and the bound is only a
    ceiling on patience.
    """
    deadline = time.monotonic() + METRIC_POLL_MAX_S
    out: dict[str, Any] = {}
    first_seen: dict[str, float] = {}
    rounds = 0
    while True:
        rounds += 1
        now = datetime.now(timezone.utc)
        for metric in MISMATCH_METRICS:
            if metric in first_seen:
                continue
            after = _read_metric(cw, store, metric, start=probe_start, end=now)
            out[metric] = {"before": baseline[metric], "after": after,
                           "verdict": _metric_verdict(baseline[metric], after)}
            if after["sum"] > 0:
                first_seen[metric] = time.monotonic()
        undecided = [m for m in MISMATCH_METRICS if m not in first_seen]
        if not undecided or time.monotonic() >= deadline:
            break
        time.sleep(METRIC_POLL_EVERY_S)
    return {
        "per_metric": out, "poll_rounds": rounds,
        "waited_s": round(METRIC_POLL_MAX_S - max(0.0, deadline - time.monotonic()), 1),
        "bound_s": METRIC_POLL_MAX_S,
        "still_absent_at_bound": sorted(m for m in MISMATCH_METRICS if m not in first_seen),
        "absence_is_bounded_not_proven": (
            "a metric absent at the bound may publish later; this is an upper bound on "
            "patience, not a proof of non-publication"),
    }


# ---------------------------------------------------------------------------
# the finding
# ---------------------------------------------------------------------------

FINDINGS = ("REFUSED_AT_CREATION", "CREATE_FAILED", "FAIL_OPEN", "FAIL_CLOSED",
            "SPLIT_OR_UNUSABLE")


def _finding(probe: dict[str, Any], arm: dict[str, Any]) -> str:
    """One unknown arm's outcome, as one of five named answers.

    Order matters. "The policy never existed" and "the policy existed and allowed" are both
    ALLOW at the gateway, and collapsing them would publish a fail-open for a policy the
    service had refused to create — reporting the document's best case as its worst. So the
    creation outcome is consulted BEFORE the decision, and a split arm gets its own answer
    rather than being rounded to whichever side had more trials.
    """
    outcome = probe.get("outcome")
    if outcome == "refused_at_creation":
        return "REFUSED_AT_CREATION"
    if outcome == "create_failed":
        return "CREATE_FAILED"
    decision = arm.get("decision")
    if decision == "ALLOW":
        return "FAIL_OPEN"
    if decision == "DENY":
        return "FAIL_CLOSED"
    return "SPLIT_OR_UNUSABLE"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:                # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else PLANNED_N
    is_smoke = args.n is not None

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            [(arm, f"{n} identical HATE requests with "
                   + ("no probe policy (baseline permit only)" if arm == ARM_CONTROL
                      else f"{'an' if _mode_for(arm)[0] in 'AEIOU' else 'a'} "
                           f"{_mode_for(arm)} forbid: "
                           + ("working guardrail path" if arm == ARM_VALID
                              else "guardrail path that does not exist" if arm != ARM_CEDAR
                              else "plain Cedar condition on a missing attribute")), n)
             for arm in ARMS],
            operations={"tools_call": n * len(ARMS)},
            # Counted, not defaulted: this case DOES create and delete resources, and a banner
            # reading "mutations: 0 (no resource is created, changed or deleted)" beside an
            # `extra` line listing seven CreatePolicy calls is two statements about one plan.
            mutations=MAX_CREATES + MAX_DELETES, billable=True,
            extra=[
                f"every arm sends the SAME payload to the SAME action; only the policy differs",
                f"the {MAX_CREATES + MAX_DELETES} mutations are ancillary and NOT part of the "
                f"arm plan: at most {MAX_CREATES} create_policy ({len(ARMS) - 1} arms with a "
                f"policy + {len(BROKEN_ARMS)} extra {VALIDATION_STRICT} attempts) and at most "
                f"{MAX_DELETES} delete_policy, one per policy that was created. Every one is on "
                f"the SHARED engine and every one is deleted in a finally",
                f"also ancillary and not mutations: 1 MCP initialize, "
                f"list_metrics x{len(MISMATCH_METRICS)} per poll round, get_metric_statistics "
                f"per discovered dimension combination",
                f"the sealed oracle is RECORDED: {O.oracle_text(CASE)}",
                f"unknown-outcome arms: {', '.join(UNKNOWN_ARMS)}. Arms {ARM_CONTROL} and "
                f"{ARM_VALID} bracket them and are what make an ALLOW attributable",
                f"each broken arm is offered to {VALIDATION_STRICT} FIRST, so "
                f"'the service refuses it at authoring time' is a reachable outcome",
                f"reads {', '.join(MISMATCH_METRICS)} over a {BASELINE_WINDOW_MIN}-minute "
                f"baseline window and the probe window; only absent-then-present is reported as "
                f"exercised by us. F7-3 recorded all four as NOT_EXERCISED",
                f"metric polling is bounded at {METRIC_POLL_MAX_S}s; absence at the bound is "
                f"reported as bounded, never as proven",
                "INTERLOCK: refuses to start if any policy other than `baseline` is registered "
                "in state.json — a forbid on the shared engine would destroy a concurrent "
                "case's data",
                f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}",
            ])

    # `T.State.load()` and `EvidenceStore(...)` take their defaults, and deliberately so. An
    # earlier draft of these two lines read `args.state` and `args.evidence_root`, neither of
    # which `P.parser` defines — so the live path raised AttributeError on its first real launch
    # after the offline suite and `--dry-run` had both passed. They passed because the dry-run
    # banner RETURNS above this line: no amount of dry-running can reach an attribute error that
    # lives below it. `tests/test_parser_attrs.py` now walks every phase1 script's `args.<name>`
    # references against the real parser, which is the check that would have caught this.
    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    ac = fc.client("bedrock-agentcore-control")
    cw = fc.client("cloudwatch")
    account_id = A.account_id(fc)
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()

    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    if not gw or not tgt:
        rec = O.not_measured(CASE, "the main gateway or its target is not in state.json")
        P.emit(CASE, rec, {"instrument": "not built: no gateway"}, store)
        return 1
    engine_id = gw.ids.get("policy_engine_id") or ""
    if not engine_id:
        rec = O.not_measured(CASE, "the main gateway has no policy engine")
        P.emit(CASE, rec, {"instrument": "not built: no engine"}, store)
        return 1
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    action_id = next((a for a in (tgt.ids.get("cedar_action_ids") or [])
                      if a.endswith(f"___{TOOL}")), "")
    if not action_id:
        rec = O.not_measured(CASE, f"no cedar action id ends with ___{TOOL}")
        P.emit(CASE, rec, {"instrument": "not built: no action"}, store)
        return 1

    common: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "gateway_id": gw.ids["gateway_id"], "policy_engine_id": engine_id,
        "action_id": action_id, "n_per_arm": n,
        "paths": {"valid": VALID_PATH, "missing": MISSING_PATH},
        "why_recorded": ("the pre-registration declares this outcome unknown; fail-open, "
                        "fail-closed and refused-at-creation are all findings and none is a "
                        "confirmation or a refutation of the document"),
        "what_this_retires_in_f7_3": (
            "F7-3 recorded MismatchErrors, TotalMismatchedPolicies, PolicyMismatch and "
            "LogOnlyEvalIncomplete as NOT_EXERCISED because reproducing them 'would also "
            "perturb the axis F4 measures'. F4 is complete, so the objection has expired. This "
            "reading is published here and does NOT rewrite F7-3's sealed verdict."),
    }

    try:
        interlock = _assert_engine_is_quiet(state)
    except ConfigError as exc:
        rec = O.not_measured(CASE, str(exc))
        P.emit(CASE, rec, {**common, "instrument": "refused: engine not quiet"}, store)
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(f"F5-4a — an unevaluable policy: deny, allow, or refuse? run_id={run_id}")
    print(f"  gateway {gw.ids['gateway_id']}  engine {engine_id}  action {action_id}")
    print(f"  arms: {', '.join(ARMS)}  n={n} each")
    print(f"  interlock ok: only {interlock['policies_on_engine_at_start']} on the engine")

    items = _corpus(HATE_CORPUS, n)
    probe_start = datetime.now(timezone.utc)
    baseline_start = probe_start - timedelta(minutes=BASELINE_WINDOW_MIN)
    print(f"  baseline metric window {baseline_start:%H:%M}Z..{probe_start:%H:%M}Z")
    baseline = {m: _read_metric(cw, store, m, start=baseline_start, end=probe_start)
                for m in MISMATCH_METRICS}
    for m, b in baseline.items():
        print(f"    {m:26s} baseline sum={b['sum']:.0f} "
              f"({b['dimension_combinations_listed']} dimension combination(s))")

    client = M.client_for(gw.ids["gateway_url"], fc, store=store,
                          policy_session_id=M.policy_session_id(run_id, "f54a"))
    # One checkpoint per arm, per the house pattern: a single file keyed by arm-prefixed trial id
    # would resume correctly but would make a partial run of one arm indistinguishable from a
    # complete run of a shorter one in the file's own metadata.
    cps: dict[str, K.Checkpoint] = {}
    arms: dict[str, Any] = {}
    probes: dict[str, Any] = {}
    deletions: dict[str, Any] = {}

    try:
        with client:
            client.initialize()
            for arm in ARMS:
                stmt = _statement_for(arm, gateway_arn, action_id)
                if stmt is not None:
                    probes[arm] = _create_probe(ac, store, state, arm=arm,
                                               engine_id=engine_id, run_id=run_id,
                                               statement=stmt)
                    print(f"  [{arm}] policy {probes[arm].get('policy_id')} "
                          f"{probes[arm]['outcome']} "
                          f"(status={probes[arm].get('status')})")
                else:
                    probes[arm] = {"arm": arm, "created": False, "statement": None,
                                   "outcome": "no_policy_by_design"}
                cps[arm] = K.Checkpoint(case_id=CASE, cell=arm).load()
                try:
                    arms[arm] = _run_arm(client, cps[arm], arm=arm, action_id=action_id,
                                        items=items)
                    print(f"  [{arm}] {arms[arm]['decision']}  "
                          f"denied={arms[arm]['n_denied']}/{arms[arm]['n_usable']}")
                finally:
                    pid = probes[arm].get("policy_id")
                    if pid:
                        deletions[arm] = _delete_probe(ac, store, state, arm=arm,
                                                      engine_id=engine_id, policy_id=pid)
                        if not deletions[arm]["deleted"]:
                            print(f"  WARNING: probe {pid} NOT deleted: "
                                  f"{deletions[arm]['errors']}", file=sys.stderr)
                    cps[arm].save()
    finally:
        for _c in cps.values():
            _c.save()
        # Belt and braces: anything this script registered and did not delete, delete now.
        for r in list(state.of_kind("policy")):
            if r.logical.startswith("f54a_"):
                arm = next((a for a in ARMS if _slug(a) == r.logical[len("f54a_"):]), None)
                if arm:
                    deletions.setdefault(arm, _delete_probe(
                        ac, store, state, arm=arm, engine_id=engine_id,
                        policy_id=r.ids["policy_id"]))

    metrics = _poll_metrics(cw, store, probe_start=probe_start, baseline=baseline)
    for m, row in metrics["per_metric"].items():
        print(f"    {m:26s} {row['verdict']}  after sum={row['after']['sum']:.0f}")

    guards = {
        "engine_was_quiet_at_start": True,          # or we never reached here
        "control_arm_was_allowed": arms.get(ARM_CONTROL, {}).get("decision") == "ALLOW",
        "valid_path_arm_was_denied": arms.get(ARM_VALID, {}).get("decision") == "DENY",
        "every_arm_reached_the_gateway": all(
            arms.get(a, {}).get("n_reached_gateway", 0) >= 1 for a in ARMS),
        "probe_was_deleted": all(d.get("deleted") for d in deletions.values()),
    }
    failed = sorted(k for k, v in guards.items() if not v)

    findings = {a: _finding(probes.get(a, {}), arms.get(a, {})) for a in UNKNOWN_ARMS}

    detail = {
        "arms": arms, "probes": probes, "deletions": deletions,
        "findings_per_unknown_arm": findings,
        "mismatch_metrics": metrics,
        "strict_validation_caught_it": {
            a: next((x["accepted"] is False for x in (probes.get(a, {}).get("attempts") or [])
                     if x.get("validation_mode") == VALIDATION_STRICT), None)
            for a in BROKEN_ARMS},
        "guards": guards, "guards_failed": failed,
    }

    n_attempted = n * len(ARMS)
    n_usable = sum(a.get("n_usable", 0) for a in arms.values())
    if failed:
        rec = O.not_measured(
            CASE, "guards failed: " + ", ".join(failed)
            + ". The unknown arms' readings are not attributable without the bracket: an ALLOW "
              "in a missing-path arm means nothing if a working forbid did not deny.")
        rec["verdict"] = O.INCONCLUSIVE
    else:
        rec = O.evaluate(O.Observation(case_id=CASE, n_attempted=n_attempted,
                                      n_usable=n_usable, detail=detail))

    P.emit(CASE, rec, {**common, **detail, "interlock": interlock}, store)
    print(f"\n  {CASE}: {rec['verdict']}")
    for arm, f in findings.items():
        print(f"    {arm:26s} {f}")
    if failed:
        print(f"  guards failed: {', '.join(failed)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
