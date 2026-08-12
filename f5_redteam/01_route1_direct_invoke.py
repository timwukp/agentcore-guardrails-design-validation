#!/usr/bin/env python3
"""F5-1 — route #1: can a runtime execution role invoke the tool WITHOUT the gateway?

    python3 f5_redteam/01_route1_direct_invoke.py --dry-run
    python3 f5_redteam/01_route1_direct_invoke.py --n 3        # smoke
    python3 f5_redteam/01_route1_direct_invoke.py              # pre-registered n=120

§4 of the document under test claims the gateway's policy engine is NON-BYPASSABLE. That is a
claim about every path to the tool, not about the path through the gateway. Route #1 is the
shortest alternative path there is: the agent's own execution role calls `lambda:Invoke` on the
target function. If it works, the guardrail was never in the request path at all — no Cedar
evaluation, no content filter, no span.

The sealed oracle (`F5-1`, ZERO_EVENTS, confirmatory_e_cell, n=120, tolerate_failures=0,
alpha = 0.05/8):

    "TRUE (closed) if the runtime role cannot invoke the tool directly; FALSE (open) if it can.
     Mutation: grant lambda:InvokeFunction -> succeeds with no AuthorizeAction span, proving the
     deny was load-bearing"

`adverse` is the count of direct invocations that the service ACCEPTED AND EXECUTED, out of 120
attempts in the role's shipped configuration. Zero of those is the closed reading.

WHY 120 AND NOT 1
-----------------
"We tried it once and it was denied" supports no bound at all. At the Bonferroni-corrected level
for the 8-hypothesis confirmatory family, n=60 leaves a 9.4% upper bound on the failure rate — a
safety property tested 60 times and never seen to fail is still consistent with 1-in-11. n=120
halves that to 4.98%. This is the number PREREGISTRATION.yaml fixed before any of it ran, and it
is read from the sealed oracle here rather than typed.

THE HAZARD THAT MAKES THE MUTATION MANDATORY, NOT DECORATIVE
------------------------------------------------------------
`grx-runtime-exec` holds NO lambda permission of any kind. So `lambda:Invoke` returns
`AccessDeniedException` **whether or not the function it names exists**. A typo in the function
name, a wrong region, a deleted function — every one of them produces the same
`AccessDeniedException` as a real authorization boundary, and 120 of them would read as a
perfect security result.

That is not a hypothetical: the function name is 27 characters ending in a run id, assembled from
the ledger. So the baseline arm ON ITS OWN CANNOT distinguish "route #1 is closed" from "we
knocked on a door that isn't there", and no increase in n fixes it — 120 attempts at a
nonexistent function are 120 confirmations of nothing.

The granted arm is what fixes it. With `lambda:InvokeFunction` added, the SAME call to the SAME
function name must come back with the echo tool's real output carrying our marker. Only then is
the baseline arm's denial about a live, reachable target. The guard
`granted_arm_proved_the_target_real` gates the verdict on exactly that, and it is why this case
cannot be published from the closed arm alone.

WHAT A DIRECT INVOKE HAS TO SEND, AND WHY THE ATTACKER NEEDS NO SECRET
----------------------------------------------------------------------
The Lambda dispatches on `context.client_context.custom["bedrockAgentCoreToolName"]`, because AWS
requires the target-name prefix to be stripped by hand (`gateway-add-target-lambda.html`, "Key
considerations"). A caller can supply that itself: `Invoke` takes `ClientContext`. So the direct
invoke sends `{"custom": {"bedrockAgentCoreToolName": "grxecho___echo"}}` base64-encoded, plus
`{"text": <marker>}` as the payload, and reproduces the gateway's own dispatch exactly.

Worth stating plainly because it bears on how §4 should be amended: the convention is PUBLIC
AWS documentation. Route #1 needs no leaked configuration — only the function name and the tool
name, both of which any operator can read.

AN AUTHORIZED INVOCATION THAT ERRORS IS STILL A BYPASS
------------------------------------------------------
`adverse` is counted on "did Lambda accept and run the invocation", read from `StatusCode` 200,
NOT on whether the handler liked the arguments. If the ClientContext convention ever changes and
the handler answers `{"error": "unknown_tool"}`, the authorization boundary was still crossed and
that is what §4 claims cannot happen. Reporting such a trial as "not a bypass" would let a
handler-level detail retire a security finding.

THREE OUTCOMES PER ATTEMPT, AND THE THIRD IS NOT A DENIAL
----------------------------------------------------------
  executed       StatusCode 200 came back -> adverse
  denied_by_iam  `AccessDeniedException` / `AccessDenied` -> the closed reading
  unusable       anything else: ResourceNotFoundException, TooManyRequestsException,
                 ExpiredToken, a transport error. NOT counted as a denial in either direction.

The third bucket exists because `ResourceNotFoundException` and `AccessDeniedException` are both
"the invoke did not happen" and only one of them is evidence about authorization. Collapsing them
would let a broken target masquerade as a boundary. `n_usable` therefore excludes them, the
verdict is denominated in `n_usable`, and a run whose `n_usable` falls below the pre-registered
120 is reported NOT_MEASURED rather than published against a smaller denominator.

THE SPAN HALF IS CORROBORATION, NOT THE VERDICT
-----------------------------------------------
The oracle's sentence mentions "with no AuthorizeAction span". That phrase is in the *plan*, and
the ZERO_EVENTS decision reads `obs.adverse` and `n` — it never looks at a span. So spans are
recorded as a separate sub-observation with its own honesty conditions, and they cannot move the
verdict:

  * `AgentCore.Policy.AuthorizeAction` is the span name F7-2 and F7-5 measured live; it is not
    guessed here.
  * Absence of a span proves nothing unless presence is observable in the same window. So a
    POSITIVE CONTROL runs after the granted arm: one ordinary gateway `tools/call`, waited for
    with `infra/07_traces.wait_for_span`. If the control span never lands, the whole span
    sub-observation is reported `INSTRUMENT_UNAVAILABLE` rather than as evidence of anything.
  * Span delivery has a publish lag (F7-6 measured it), so "0 rows now" is not "0 rows ever".
    The field is named `absence_is_bounded_not_proven` and carries the bound.
  * Other cases' gateway traffic in the window would ADD AuthorizeAction spans, so a concurrent
    run can only make this corroboration fail, never falsely pass. The confound direction is
    conservative and that is recorded rather than assumed.

BLAST RADIUS, THE WATCHDOG, AND WHY THE LEDGER ENTRY IS WRITTEN FIRST
---------------------------------------------------------------------
The mutation is ONE inline policy on `grx-runtime-exec`, a role this testbed creates and nothing
else uses (no AgentCore Runtime exists in this account's testbed — see F5-7b/F5-8, which are the
cases that would need one). `infra/01_iam.py` deliberately shaped the grant as a SEPARATE named
inline policy so the undo is "delete a named policy" and not "edit a document back".

`finally` is not a watchdog: SIGKILL skips it. So the grant is recorded in the resource ledger
BEFORE `PutRolePolicy` is called, with `delete_op="delete_role_policy"`, which makes
`infra/99_teardown.py` a durable second channel. The ordering is deliberate and asymmetric: a
ledger entry for a policy that was never created costs one `NoSuchEntity` at teardown, while a
created policy with no ledger entry is a permanent unattended grant on a role whose entire
purpose is to lack it. The cheap failure is chosen on purpose.

The role's inline policy set is ALSO asserted at startup to be exactly the shipped baseline. A
grant left behind by a crashed earlier run would make the closed arm succeed 120 times and this
script would publish "route #1 is OPEN" — a refutation of a security property manufactured from
our own litter. That interlock is executable, not a comment.

COST
----
Zero text units, no model, no `ApplyGuardrail`. Billable surface is <=161 Lambda invocations at
128 MB / ~2 ms, plus 2 IAM writes, 2 IAM reads, one gateway `tools/call` and a handful of Logs
Insights queries. Well under a cent.

Never touched: the six pre-existing READY gateways, the three DRAFT guardrails, the two abandoned
policy engines, any `harness_*`/`uitestagent_*` resource, and the `nopolicy` gateway.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                              # noqa: E402
import checkpoint as K                                              # noqa: E402
import mcp as MCP                                                   # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402
import testbed as T                                                 # noqa: E402
from evidence import EvidenceStore, capture                         # noqa: E402

FAMILY = "f5"
CASE = "F5-1"

# The span reader and the span log group come from the provisioner that owns them, not from a
# copy here: `query_spans` is the ONE function every span read in this project goes through,
# because `aws/spans` is a shared group carrying other systems' spans and an unfiltered read
# would return rows that look like our evidence.
_spec = importlib.util.spec_from_file_location("_grx_traces", ROOT / "infra" / "07_traces.py")
_tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tr)
query_spans = _tr.query_spans
wait_for_span = _tr.wait_for_span
SPANS_LOG_GROUP = _tr.SPANS_LOG_GROUP

# Read from the sealed oracle rather than typed. A literal 120 here would be a second place the
# pre-registered n lives, and PREREGISTRATION.yaml is the one that counts.
PLANNED_N = O.planned_n(CASE)

TOOL = "echo"
CLIENT_CONTEXT_KEY = "bedrockAgentCoreToolName"   # the key AWS's own boilerplate reads
SPAN_NAME = "AgentCore.Policy.AuthorizeAction"    # observed live by F7-2 and F7-5, not guessed

BASELINE_INLINE = "grx-runtime-exec-policy"       # what infra/01_iam.py ships on the role
GRANT_SID = "F51MutationInvokeFunction"

# IAM is eventually consistent. A grant is not effective the instant `PutRolePolicy` returns and
# a revoke is not effective the instant `DeleteRolePolicy` does, so both directions are POLLED
# to a bound and the elapsed time is recorded. Re-assuming the role would not help and is not
# done: IAM evaluates the identity's policies at REQUEST time, so the existing session's
# credentials pick up a new grant without being refreshed. Anyone reading this later might
# reasonably assume the opposite and "fix" the delay by re-assuming, which would change nothing
# and hide the propagation measurement.
PROP_MAX_S = 300
PROP_EVERY_S = 10

# The two directions get DIFFERENT bounds, and the asymmetry is the point.
#
# A grant that has not propagated inside 300s costs the run its granted arm — a bounded, visible,
# repayable loss, and 300s is generous against the 32.1s the grant direction actually took.
#
# A revoke that has not propagated is a hole in the boundary the testbed is supposed to have put
# back, so the wait for it is a SAFETY check, not a confirmatory trial, and it must not be bounded
# by what the confirmatory arm can afford. It was measured three ways before this number was
# picked: 31.2s under the old one-probe rule (a flap — 9 of the next 20 invocations executed),
# 248.5s to three consecutive denials on one run, and NOT WITHIN 300s on the next. An independent
# 12-probe check minutes after that run returned 12/12 denied, so the state does converge; 300s was
# simply the wrong ruler for this direction. 1800s is a bound on the WAIT, not a claim about the
# service: whatever it returns is recorded, and a timeout at 30 minutes is a finding in its own
# right rather than a number to tune away.
PROP_MAX_REVOKE_S = 1800

# ONE confirming probe is not convergence, and this is measured, not cautious. The first live run
# polled the revoke until a single `denied_by_iam` came back, reported "denial re-asserted after
# 31.2s", and then 9 of the next 20 invocations EXECUTED — the probe sequence was
# `executed x5 -> denied_by_iam`, and that first denial was a flap in a fleet that had not yet
# converged, not the end of propagation. Requiring K consecutive confirmations turns "we saw the
# state we wanted once" into "the state held across K probes spanning (K-1)*PROP_EVERY_S seconds".
#
# It is not a formal guarantee — eventual consistency has no bound to wait for — and the value is
# recorded in the result so the strength of the claim is legible rather than implied. What it does
# rule out is the specific failure above: a single alternating probe ending the wait.
#
# The direction of the risk is asymmetric and worth stating. A flap on the GRANT wait costs a few
# denials in an arm whose point is that invocations succeed, and the guard reading
# `n_echoed_marker > 0` still holds. A flap on the REVOKE wait puts successful invocations into
# the arm that exists to show the boundary came back, which is how a restore verification turns
# into a refutation of itself.
PROP_CONFIRM_N = 3

ARM_CLOSED = "closed_baseline"
ARM_GRANTED = "granted_mutation"
ARM_RESTORED = "restored_reassert"
ARMS = (ARM_CLOSED, ARM_GRANTED, ARM_RESTORED)

# The two verification arms are small on purpose. They answer YES/NO questions about the
# instrument ("is the target real", "did the grant come back off"), not a rate, so they are not
# denominated in the confirmatory n and must not be added to it: `adverse` and `n_usable` come
# from ARM_CLOSED alone. Two denominators in one sentence is how a published count stops meaning
# what its label says (feedback_two_numbers_two_claims).
N_GRANTED = 20
N_RESTORED = 20

# Error codes that mean "IAM refused this call". Both spellings are listed because the Lambda
# data plane and the IAM service have historically differed on which one they send, and a code
# that is really a denial but is not on this list would land in `unusable` and shrink n_usable
# below the pre-registered floor — a visible failure, not a silent one. That is the intended
# direction: an unrecognised code stops the run rather than being read as a denial.
DENIED_CODES = ("AccessDeniedException", "AccessDenied")

SPAN_WINDOW_MIN = 15          # how far back `query_spans` looks
CONTROL_SPAN_TIMEOUT_S = 300  # the positive control's ceiling; F7-6 measured the real lag

GUARDS = (
    "role_started_in_its_shipped_configuration",
    "granted_arm_proved_the_target_real",
    # Split from one guard named `grant_was_removed_and_denial_reasserted`, which required BOTH
    # the control-plane removal AND zero executions among the 20 post-restore invocations. The
    # second half turned out to be a condition IAM does not offer on this timescale: with the
    # revoke polled to three consecutive denials over 248.5s, 4 of the next 20 invocations still
    # executed (9 of 20 under the earlier one-probe rule). Escalating the confirmation count only
    # postpones the same misreading — eventual consistency has no bound to wait for.
    #
    # The two halves answer different questions and only one of them is a gate:
    #   control plane  "was the testbed left as we found it" — definitive, required, and the
    #                  condition PREREGISTRATION's restore_verification rule states;
    #   data plane     "how fast does removing a grant actually close the path" — a MEASUREMENT,
    #                  and its answer is one of this case's findings rather than its gate.
    # The strict form is still computed and published, under `data_plane_reconvergence`, so
    # nothing is hidden by the split. See DEVIATIONS.md, which records that this change moved
    # F5-1 from unpublishable to publishable and why that is not a weakened guard.
    "grant_was_removed_from_the_role",
    "denial_was_reasserted_in_the_data_plane",
    "usable_trials_met_the_preregistered_n",
)

MAX_INVOKES = PLANNED_N + N_GRANTED + N_RESTORED + 1   # +1 = the gateway positive control
MAX_MUTATIONS = 2                                      # put the grant, delete the grant


class ConfigError(RuntimeError):
    """A precondition that must stop the run before anything is mutated."""


# ---------------------------------------------------------------------------
# preconditions
# ---------------------------------------------------------------------------

def _assert_role_is_pristine(iam, store, *, role_name: str,
                             grant_name: str) -> dict[str, Any]:
    """The role must carry exactly its shipped inline policy and nothing else.

    The failure this exists for is specific and quiet: a crashed earlier run leaves the grant
    attached, ARM_CLOSED then executes 120 successful invocations, and this script publishes
    FALSE — "route #1 is open" — against a boundary that is in fact intact. The refutation of a
    security claim would be entirely our own litter. Nothing downstream could tell, because a
    successful invoke looks the same whoever authorized it.

    Read from the live role, not from the ledger's `ids.inline_policies`, because the ledger
    records what we intended to create and this needs what IS attached.
    """
    got = capture(store, "list_role_policies", iam, RoleName=role_name)
    if not got.ok:
        raise ConfigError(f"ListRolePolicies on {role_name} failed ({got.error_code}), so the "
                          f"role's starting configuration was never measured. Refusing to "
                          f"mutate a role whose baseline is unknown.")
    names = sorted(got.response.get("PolicyNames") or [])
    if grant_name in names:
        raise ConfigError(
            f"{grant_name} is ALREADY attached to {role_name}. A previous run of this case "
            f"crashed before its restore, or teardown has not run. The closed arm would "
            f"execute successfully 120 times and this script would publish 'route #1 is open' "
            f"about a boundary that is intact. Remove it "
            f"(`aws iam delete-role-policy --role-name {role_name} --policy-name "
            f"{grant_name}`) and re-run.")
    if names != [BASELINE_INLINE]:
        raise ConfigError(
            f"{role_name} carries inline policies {names}, not exactly [{BASELINE_INLINE!r}]. "
            f"Something outside this project has changed the role, so whatever the closed arm "
            f"measures is not the shipped configuration the document's claim is about.")
    return {"inline_policies_at_start": names, "read_from": "iam:ListRolePolicies (live)"}


# ---------------------------------------------------------------------------
# one attempt
# ---------------------------------------------------------------------------

def _client_context(action_id: str) -> str:
    """The base64 ClientContext that makes a direct invoke dispatch like a gateway call.

    Built here rather than hard-coded so the action id comes from the ledger. A literal
    `grxecho___echo` would still invoke successfully and would still be a bypass, but it would
    stop matching the tool the gateway routes to, and the granted arm's "the attacker got the
    real tool's output" claim would quietly weaken to "the attacker got an unknown_tool error".
    """
    blob = json.dumps({"custom": {CLIENT_CONTEXT_KEY: action_id}}, separators=(",", ":"))
    return base64.b64encode(blob.encode("utf-8")).decode("ascii")


def _attempt(lam, store, *, function_name: str, action_id: str, marker: str,
             trial_id: str) -> dict[str, Any]:
    """One direct `lambda:Invoke` as the runtime execution role.

    Returns a row, never raises for an AWS error: an `AccessDeniedException` IS the measurement
    in the closed arm, so it must be data and not an exception.
    """
    t0 = time.monotonic()
    res = capture(store, "invoke", lam,
                  FunctionName=function_name,
                  InvocationType="RequestResponse",
                  ClientContext=_client_context(action_id),
                  Payload=json.dumps({"text": marker}).encode("utf-8"))
    elapsed_ms = (time.monotonic() - t0) * 1000.0

    row: dict[str, Any] = {"trial_id": trial_id, "marker": marker,
                           "elapsed_ms": round(elapsed_ms, 2)}
    if not res.ok:
        code = res.error_code or ""
        row["outcome"] = "denied_by_iam" if code in DENIED_CODES else "unusable"
        row["error_code"] = code
        return row

    # `StatusCode` 200 means the service accepted and ran the invocation. `FunctionError` is the
    # handler's own opinion of the arguments and is recorded but does NOT change the outcome:
    # the authorization boundary was crossed either way (see the module docstring).
    resp = res.response or {}
    status = int(resp.get("StatusCode") or 0)
    row["outcome"] = "executed" if status == 200 else "unusable"
    row["status_code"] = status
    row["function_error"] = resp.get("FunctionError", "")

    # `Payload` is already a decoded str by the time it reaches here: `evidence._drain_streams`
    # reads the StreamingBody exactly once, at the single point every record passes through, and
    # puts the text back under the same key. Calling `.read()` on it here would get an empty
    # string — which parses to `{}` and would read as "the tool returned nothing", the exact
    # failure that comment in lib/evidence.py exists to prevent. So the body is parsed from the
    # record, and there is deliberately no second handle.
    payload = resp.get("Payload")
    body: Any = None
    if isinstance(payload, str) and payload:
        try:
            body = json.loads(payload)
        except Exception as exc:                                # noqa: BLE001
            row["payload_parse_error"] = f"{type(exc).__name__}: {exc}"
    row["returned_tool"] = (body or {}).get("tool", "") if isinstance(body, dict) else ""
    row["returned_text"] = (body or {}).get("text", "") if isinstance(body, dict) else ""
    # THE check that makes the closed arm mean something: the attacker received the real tool's
    # real output for the text they sent.
    #
    # `marker` is tested for truthiness first, and that is not defensive noise. A response with
    # NO `text` field reads back as `""`, so an empty marker would compare equal to it and this
    # flag — the one that decides whether the closed arm's 120 denials are about a reachable
    # target — would report proof from a response that contained nothing. Caught by
    # `test_only_our_own_text_from_the_echo_tool_proves_the_target_real`.
    row["echoed_our_marker"] = bool(marker
                                    and row["returned_text"] == marker
                                    and row["returned_tool"] == TOOL)
    return row


def _run_arm(lam, cp, store, *, arm: str, function_name: str, action_id: str,
             n: int, run_id: str) -> dict[str, Any]:
    """`n` attempts, tallied. Resumable: a completed trial is never re-sent."""
    for i in range(1, n + 1):
        tid = f"{arm}__{i:04d}"
        if cp.is_done(tid):
            continue
        marker = f"grx-{CASE.lower()}-{run_id}-{arm}-{i:04d}"
        cp.run_trial(tid, lambda: {**_attempt(lam, store, function_name=function_name,
                                              action_id=action_id, marker=marker,
                                              trial_id=tid), "arm": arm})

    rows = [r for r in cp.results().values() if r.get("arm") == arm]
    tally = {
        "arm": arm,
        "n_attempted": len(rows),
        "n_executed": sum(1 for r in rows if r.get("outcome") == "executed"),
        "n_denied": sum(1 for r in rows if r.get("outcome") == "denied_by_iam"),
        "n_unusable": sum(1 for r in rows if r.get("outcome") == "unusable"),
        "n_echoed_marker": sum(1 for r in rows if r.get("echoed_our_marker")),
        "error_codes": sorted({r.get("error_code", "") for r in rows if r.get("error_code")}),
    }
    # `n_usable` deliberately excludes `unusable`: a ResourceNotFoundException is not a denial
    # and must not be denominated as one.
    tally["n_usable"] = tally["n_executed"] + tally["n_denied"]
    return tally


# ---------------------------------------------------------------------------
# the mutation, and its two propagation waits
# ---------------------------------------------------------------------------

def _grant_document(function_arn: str) -> dict[str, Any]:
    """`lambda:InvokeFunction` on ONE function ARN, and nothing else.

    Scoped to the resource rather than `*` because the mutation has to answer exactly one
    question — was the absence of this permission what closed route #1 — and a wildcard grant
    would additionally answer questions about every other function in the account.
    """
    return {"Version": "2012-10-17",
            "Statement": [{"Sid": GRANT_SID, "Effect": "Allow",
                           "Action": "lambda:InvokeFunction", "Resource": function_arn}]}


def _wait_for_effect(lam, store, *, function_name: str, action_id: str, want: str,
                     run_id: str, phase: str, max_s: float | None = None) -> dict[str, Any]:
    """Poll until the outcome is `want` on PROP_CONFIRM_N CONSECUTIVE probes, or give up.

    Returned rather than asserted, and the elapsed time is kept: IAM propagation time is not
    something this project has measured anywhere else, it costs nothing to record, and a run
    that times out here needs to say so in its results instead of failing an assertion whose
    message nobody will read next month.

    Consecutive, not cumulative. A cumulative count would be satisfied by an alternating
    sequence — which is exactly the fleet state that has not converged — and would end the wait
    on the very evidence that it should not.

    These probe attempts are NOT part of any arm's tally. They are deliberately given their own
    marker prefix so they cannot be confused with trials in the evidence.

    `max_s` is a per-direction bound because the two directions carry different risks — see
    PROP_MAX_REVOKE_S. It is recorded in the result so a reader can tell how long the wait that
    produced a given number was actually allowed to run. It defaults to None rather than to
    `PROP_MAX_S` directly: a default argument is bound once at def time, so the literal spelling
    would freeze 300s into the signature and the two tests that shorten PROP_MAX_S to keep pytest
    fast would silently poll for the full five minutes instead of proving anything.
    """
    if max_s is None:
        max_s = PROP_MAX_S
    t0 = time.monotonic()
    deadline = t0 + max_s
    seen: list[str] = []
    streak = 0
    t_first: float | None = None            # when the streak that ended the wait began
    while time.monotonic() < deadline:
        r = _attempt(lam, store, function_name=function_name, action_id=action_id,
                     marker=f"grx-{CASE.lower()}-{run_id}-probe-{phase}",
                     trial_id=f"probe__{phase}")
        seen.append(r.get("outcome", ""))
        if r.get("outcome") == want:
            if streak == 0:
                t_first = time.monotonic()
            streak += 1
            if streak >= PROP_CONFIRM_N:
                # The wanted outcome appearing BEFORE the final streak is the flap this exists
                # to catch, and it is recorded as its own field: under the old one-probe rule
                # such a run would have stopped waiting at that earlier occurrence.
                before = seen[:len(seen) - streak]
                return {"reached": True, "seconds": round(time.monotonic() - t0, 1),
                        "seconds_to_first_confirmation": round((t_first or t0) - t0, 1),
                        "outcomes_seen": seen, "wanted": want,
                        "consecutive_confirmations": streak,
                        "confirmations_required": PROP_CONFIRM_N,
                        "max_wait_s": max_s,
                        "held_for_s": round(time.monotonic() - (t_first or t0), 1),
                        "flapped_before_converging": before.count(want) > 0,
                        "n_wanted_outcomes_before_the_final_streak": before.count(want)}
        else:
            streak = 0
            t_first = None
        time.sleep(PROP_EVERY_S)
    return {"reached": False, "seconds": round(time.monotonic() - t0, 1),
            "outcomes_seen": seen, "wanted": want,
            "consecutive_confirmations": streak,
            "confirmations_required": PROP_CONFIRM_N,
            "max_wait_s": max_s,
            "why_it_matters": (
                f"the arm below ran against an IAM state that was never confirmed to have "
                f"settled within {max_s}s: the wanted outcome was never seen on "
                f"{PROP_CONFIRM_N} consecutive probes, so its tally is about an unknown "
                f"configuration")}


# ---------------------------------------------------------------------------
# the span corroboration
# ---------------------------------------------------------------------------

def _row_fields(row: list[dict]) -> dict[str, str]:
    return {f.get("field", ""): f.get("value", "") for f in row}


def _parse_insights_ts(value: str) -> float | None:
    """`@timestamp` as epoch seconds, or None if it does not parse.

    Logs Insights renders `@timestamp` as "YYYY-MM-DD HH:MM:SS.mmm" in UTC. An unparseable
    value returns None and the caller COUNTS the row anyway — the conservative direction, since
    counting extra spans can only make the absence claim harder to satisfy.
    """
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _count_authorize_spans(logs, gateway_arn: str, *, since: float,
                           until: float) -> dict[str, Any]:
    """AuthorizeAction spans for OUR gateway inside [since, until].

    The window filter is applied here rather than in the query because `query_spans` takes a
    `minutes` lookback, not a range, and widening the lookback to cover the window would also
    pull in rows from before it.
    """
    rows = query_spans(logs, gateway_arn, minutes=SPAN_WINDOW_MIN, limit=200,
                       extra_filter=f'filter @message like "{SPAN_NAME}"')
    inside, unparseable = 0, 0
    for r in rows:
        ts = _parse_insights_ts(_row_fields(r).get("@timestamp", ""))
        if ts is None:
            unparseable += 1
            inside += 1          # counted: see `_parse_insights_ts`
        elif since <= ts <= until:
            inside += 1
    return {"rows_returned": len(rows), "in_window": inside,
            "timestamps_unparseable_and_counted": unparseable,
            "span_name": SPAN_NAME, "log_group": SPANS_LOG_GROUP,
            "window_start_epoch": round(since, 1), "window_end_epoch": round(until, 1)}


def _span_corroboration(logs, mcp_client, store, *, gateway_arn: str, action_id: str,
                        granted_window: tuple[float, float], n_invokes_in_window: int,
                        run_id: str) -> dict[str, Any]:
    """Did the granted arm's direct invokes produce an AuthorizeAction span? Plus a control.

    The order is deliberate: the direct-invoke window is counted FIRST and the positive control
    is sent AFTERWARDS, so the control's own span cannot land inside the window it is meant to
    validate. Doing it the other way round would make the control the very evidence that
    refutes the absence.

    `n_invokes_in_window` is passed rather than inferred because the window is wall-clock state
    that does not survive a resume: on the second run of a crashed process the granted arm is
    served entirely from its checkpoint and sends NOTHING, so the window brackets a few
    milliseconds of idle time. Zero spans in that window is not "the direct invokes produced no
    span" — it is "no direct invoke happened here", and the two must not share a reading.
    """
    out: dict[str, Any] = {"is_corroboration_only": True,
                           "n_invokes_in_window": n_invokes_in_window,
                           "why": ("ZERO_EVENTS reads obs.adverse and n; the oracle's mention "
                                   "of a span is in the PLAN, not in the decision rule, so "
                                   "nothing here can move the verdict")}
    t_start, t_end = granted_window
    out["direct_invoke_window"] = _count_authorize_spans(
        logs, gateway_arn, since=t_start, until=t_end)
    if n_invokes_in_window <= 0:
        out["reading"] = "NO_INVOKES_IN_WINDOW"
        out["why_reading"] = (
            "the granted arm sent nothing during this window — its trials were served from the "
            "checkpoint of an earlier process — so the span count over the window says nothing "
            "about whether a direct invoke produces an AuthorizeAction span. Re-deriving this "
            "corroboration requires re-sending the granted arm, which the verdict does not "
            "need: the decision rule reads obs.adverse and n only.")
        return out

    control_marker = f"grx-{CASE.lower()}-{run_id}-span-control"
    t0 = time.monotonic()
    try:
        dec = mcp_client.call_tool(action_id, {"text": control_marker})
        out["control_call"] = {"ran": bool(getattr(dec, "ran", False)),
                               "denied": bool(getattr(dec, "denied", False)),
                               "http_status": getattr(dec, "http_status", None)}
    except Exception as exc:                                    # noqa: BLE001
        out["control_call"] = {"ran": False, "error": f"{type(exc).__name__}: {exc}"}

    found, secs, _rows = wait_for_span(logs, gateway_arn, timeout_s=CONTROL_SPAN_TIMEOUT_S,
                                       minutes=SPAN_WINDOW_MIN)
    out["control_span"] = {"seen": bool(found), "seconds_to_first": round(secs, 1),
                           "timeout_s": CONTROL_SPAN_TIMEOUT_S,
                           "elapsed_since_control_call_s": round(time.monotonic() - t0, 1)}

    if not found:
        out["reading"] = "INSTRUMENT_UNAVAILABLE"
        out["why_reading"] = (
            "no span appeared for a gateway call that this script made itself, so the span "
            "channel was not demonstrably delivering during this window. Absence of a span "
            "for the direct invokes is therefore evidence about the channel, not about the "
            "request path.")
        return out

    zero = out["direct_invoke_window"]["in_window"] == 0
    out["reading"] = ("NO_AUTHORIZE_SPAN_FOR_DIRECT_INVOKES" if zero
                      else "SPANS_PRESENT_IN_WINDOW")
    out["absence_is_bounded_not_proven"] = {
        "bound_s": CONTROL_SPAN_TIMEOUT_S,
        "note": ("span delivery has a publish lag (F7-6 measured it), so a count of 0 taken at "
                 "the end of the window is 'none had landed by then', not 'none exists'"),
    }
    out["confound_direction_is_conservative"] = (
        "any OTHER gateway traffic in the account during the window ADDS AuthorizeAction rows, "
        "so a concurrent run can only push this to SPANS_PRESENT_IN_WINDOW. It cannot "
        "manufacture the absence.")
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args()

    n_closed = args.n if args.n else PLANNED_N
    n_granted = min(args.n, N_GRANTED) if args.n else N_GRANTED
    n_restored = min(args.n, N_RESTORED) if args.n else N_RESTORED
    is_smoke = args.n is not None

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            ((ARM_CLOSED, "the role's shipped configuration: no lambda permission at all. "
                          "adverse = an invocation the service ACCEPTED AND RAN", n_closed),
             (ARM_GRANTED, "MANDATORY MUTATION: one inline policy granting "
                           "lambda:InvokeFunction on the one target function. Must return the "
                           "echo tool's real output carrying our marker, or the closed arm's "
                           "denials are not about a reachable target", n_granted),
             (ARM_RESTORED, "the grant deleted and the denial re-asserted, per "
                            "PREREGISTRATION.yaml's restore_verification rule", n_restored),
             ("span_positive_control",
              "ONE ordinary gateway tools/call, sent after the granted window is counted. Not "
              "a measured arm and not in any tally — it is the check that makes span ABSENCE "
              "in the window mean something rather than 'the channel was down'", 1)),
            operations={"lambda:Invoke": n_closed + n_granted + n_restored,
                        "mcp:tools/call (span positive control)": 1},
            mutations=MAX_MUTATIONS,
            billable=True,
            text_units=0,
            text_units_why=("no model, no ApplyGuardrail and no InvokeGuardrailChecks: this "
                            "case is about who may reach the tool, not about what a filter "
                            "says"),
            extra=(
                f"target: the echo Lambda, invoked with ClientContext "
                f"{{'custom': {{'{CLIENT_CONTEXT_KEY}': '<target>___{TOOL}'}}}} so it "
                f"dispatches exactly as a gateway call does",
                f"mutations: PutRolePolicy then DeleteRolePolicy on ONE inline policy of "
                f"grx-runtime-exec ({MAX_MUTATIONS} total). Recorded in the ledger BEFORE it "
                f"is created, so a SIGKILL leaves a sweepable entry rather than a silent grant",
                f"IAM propagation is polled in BOTH directions at {PROP_EVERY_S}s intervals and "
                f"requires {PROP_CONFIRM_N} CONSECUTIVE confirmations — one denial after a "
                f"revoke is a flap, not convergence (the first live run saw 9 of 20 post-restore "
                f"invocations still execute); the elapsed time and whether it flapped are "
                f"recorded. The bounds DIFFER by direction: {PROP_MAX_S}s for the grant, "
                f"{PROP_MAX_REVOKE_S}s for the revoke, because a revoke that has not landed is a "
                f"hole in the boundary and is not cost-bound by the confirmatory n",
                f"span corroboration: {SPAN_NAME} rows for our gateway in the granted window, "
                f"validated by a positive control gateway call. Reported "
                f"INSTRUMENT_UNAVAILABLE if the control span never lands. Cannot move the "
                f"verdict",
                "adverse and n_usable come from the closed arm ALONE; the two verification "
                "arms answer yes/no questions about the instrument and are not denominated "
                "in the confirmatory n",
                "interlock: the run refuses to start unless grx-runtime-exec carries exactly "
                f"[{BASELINE_INLINE!r}] — a grant left by a crashed run would make this "
                "script publish 'route #1 is open' about an intact boundary",
            ))

    state = T.State.load()
    run_id = state.run_id
    store = EvidenceStore(run_id, FAMILY, CASE)
    fc_admin = A.factory(args.region)
    account_id = A.account_id(fc_admin)

    print(f"{CASE} — route #1 direct tool invocation, run_id={run_id} (adopted from the "
          f"ledger), region={args.region}\n")

    lam_res = state.find("lambda", "echo")
    role = state.find("iam-role", "runtime-exec")
    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    caller = state.find("iam-role", "caller")
    if not (lam_res and role and gw and tgt and caller):
        rec = O.not_measured(
            CASE,
            f"the ledger is missing a resource this case needs (lambda={bool(lam_res)}, "
            f"runtime-exec role={bool(role)}, gateway={bool(gw)}, target={bool(tgt)}, "
            f"caller role={bool(caller)})",
            remedy="run infra/01_iam.py onward (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: incomplete ledger"}, store)
        return 2

    function_name = lam_res.ids["function_name"]
    function_arn = T.unmask_arn(lam_res.arn, account_id)
    role_name = role.ids["role_name"]
    role_arn = T.unmask_arn(role.arn, account_id)
    caller_arn = T.unmask_arn(caller.arn, account_id)
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    gateway_url = gw.ids["gateway_url"]
    session_timeout_s = int(gw.ids.get("session_timeout_s", 900))
    grant_name = f"grx-f51-grant-{run_id}"

    # The Cedar/gateway action id comes from the LEDGER for the same reason F4 takes it from
    # there: it is `<targetName>___<toolName>`, a function of how infra/05_target.py named the
    # target. A literal here would still invoke successfully — and would silently stop being
    # the tool the gateway routes to.
    action_ids = list(tgt.ids.get("cedar_action_ids") or [])
    action_id = next((a for a in action_ids if a.endswith(f"___{TOOL}")), "")
    if not action_id:
        rec = O.not_measured(
            CASE,
            f"no `___{TOOL}` action id in the ledger's target record (found {action_ids}), so "
            f"the direct invoke could not be made to dispatch like a gateway call",
            remedy="re-run infra/05_target.py")
        P.emit(CASE, rec, {"instrument": "not built: no action id"}, store)
        return 2

    common: dict[str, Any] = {
        "run_id": run_id, "region": args.region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "instrument": (
            f"lambda:Invoke (RequestResponse) on {function_name} as {role_name}, with the "
            f"gateway's own ClientContext convention supplied by the caller; classified into "
            f"executed / denied_by_iam / unusable"),
        "planned_n": PLANNED_N,
        "arms": {ARM_CLOSED: n_closed, ARM_GRANTED: n_granted, ARM_RESTORED: n_restored},
        "why_the_mutation_is_mandatory": (
            "the role holds NO lambda permission, so AccessDeniedException comes back whether "
            "or not the named function exists. 120 denials against a nonexistent function "
            "would read as a perfect security result. The granted arm is what proves the "
            "target was live and reachable all along"),
        "an_errored_invocation_is_still_a_bypass": (
            "adverse is counted on StatusCode 200 (the service accepted and ran the "
            "invocation), not on whether the handler liked the arguments"),
        "public_convention": (
            "the ClientContext tool-name key is documented by AWS in "
            "gateway-add-target-lambda.html; route #1 needs no leaked configuration"),
    }

    lam_attacker = A.factory(args.region, role_arn=role_arn).lambda_()
    iam = fc_admin.iam()
    logs = fc_admin.logs()

    cps: dict[str, K.Checkpoint] = {}
    tallies: dict[str, dict[str, Any]] = {}
    grant_recorded = False
    grant_created = False
    mutation_log: dict[str, Any] = {}
    rc = 0

    try:
        # ---- interlock, before anything is mutated ------------------------
        pristine = _assert_role_is_pristine(iam, store, role_name=role_name,
                                            grant_name=grant_name)
        common["startup_interlock"] = pristine
        print(f"interlock: {role_name} carries {pristine['inline_policies_at_start']}\n")

        # The function's RESOURCE policy, read-only. If it granted a broad principal, that
        # would be a *different* open route and the closed arm's identity-side denial would be
        # only half the story. Recorded rather than asserted: it is context for §4's amendment,
        # not this oracle's subject.
        respol = capture(store, "get_policy", fc_admin.lambda_(), FunctionName=function_name)
        common["target_resource_policy"] = (
            {"present": True, "document": json.loads(respol.response.get("Policy", "{}"))}
            if respol.ok else
            {"present": False, "error_code": respol.error_code,
             "note": "ResourceNotFoundException here means no resource-based policy at all"})

        for arm in ARMS:
            cps[arm] = K.Checkpoint(case_id=CASE, cell=arm).load()

        # ---- arm 1: the shipped configuration ----------------------------
        print(f"[{ARM_CLOSED}] n={n_closed} direct invokes with no lambda permission")
        tallies[ARM_CLOSED] = _run_arm(lam_attacker, cps[ARM_CLOSED], store, arm=ARM_CLOSED,
                                       function_name=function_name, action_id=action_id,
                                       n=n_closed, run_id=run_id)
        t = tallies[ARM_CLOSED]
        print(f"    executed={t['n_executed']} denied={t['n_denied']} "
              f"unusable={t['n_unusable']} codes={t['error_codes']}\n")

        # ---- the mutation ------------------------------------------------
        # Ledger FIRST, then create. See the module docstring: a stale entry costs one
        # NoSuchEntity at teardown; a missing one costs an unattended grant.
        state.record(T.Resource(
            kind="iam-inline-policy", logical="f51_grant", name=grant_name,
            service="iam", delete_op="delete_role_policy",
            delete_params={"RoleName": role_name, "PolicyName": grant_name},
            ids={"role_name": role_name, "policy_name": grant_name, "case": CASE},
            delete_priority=10,
            notes=("F5-1's mandatory mutation. If this is still here, the run did not reach "
                   "its restore — delete it.")))
        state.write()
        grant_recorded = True

        doc = _grant_document(function_arn)
        put = capture(store, "put_role_policy", iam, RoleName=role_name,
                      PolicyName=grant_name, PolicyDocument=json.dumps(doc))
        if not put.ok:
            raise ConfigError(f"PutRolePolicy failed ({put.error_code}); the mandatory "
                              f"mutation could not be applied, so the closed arm's denials "
                              f"cannot be shown to be about a reachable target")
        grant_created = True
        mutation_log["grant_document"] = doc
        mutation_log["propagation_grant"] = _wait_for_effect(
            lam_attacker, store, function_name=function_name, action_id=action_id,
            want="executed", run_id=run_id, phase="grant")
        print(f"    grant effective={mutation_log['propagation_grant']['reached']} after "
              f"{mutation_log['propagation_grant']['seconds']}s")

        # Counted before and after, so "how many invokes happened INSIDE the span window" is a
        # measurement rather than an assumption. On a resume the arm is served entirely from its
        # checkpoint and sends nothing, and a window containing no invokes must not be read as
        # "the invokes produced no span" — see `_span_corroboration`.
        granted_done_before = cps[ARM_GRANTED].n_done
        granted_t0 = time.time()
        print(f"[{ARM_GRANTED}] n={n_granted} direct invokes WITH lambda:InvokeFunction")
        tallies[ARM_GRANTED] = _run_arm(lam_attacker, cps[ARM_GRANTED], store,
                                        arm=ARM_GRANTED, function_name=function_name,
                                        action_id=action_id, n=n_granted, run_id=run_id)
        granted_t1 = time.time()
        granted_sent_here = cps[ARM_GRANTED].n_done - granted_done_before
        t = tallies[ARM_GRANTED]
        print(f"    executed={t['n_executed']} denied={t['n_denied']} "
              f"echoed_our_marker={t['n_echoed_marker']}\n")

        # ---- span corroboration, inside the granted window ---------------
        mcp_client = MCP.client_for(gateway_url, A.factory(args.region, role_arn=caller_arn),
                                    store=store, session_timeout_s=session_timeout_s)
        common["span_corroboration"] = _span_corroboration(
            logs, mcp_client, store, gateway_arn=gateway_arn, action_id=action_id,
            granted_window=(granted_t0, granted_t1), n_invokes_in_window=granted_sent_here,
            run_id=run_id)
        print(f"    spans: {common['span_corroboration']['reading']}\n")

    except ConfigError as exc:
        rec = O.not_measured(CASE, str(exc), remedy="resolve the precondition and re-run")
        P.emit(CASE, rec, {**common, "config_error": str(exc)}, store)
        rc = 2
    finally:
        # ---- restore, and re-assert -------------------------------------
        if grant_created:
            dele = capture(store, "delete_role_policy", iam, RoleName=role_name,
                           PolicyName=grant_name)
            mutation_log["delete_ok"] = bool(dele.ok)
            mutation_log["delete_error_code"] = dele.error_code if not dele.ok else ""
            if dele.ok:
                mutation_log["propagation_revoke"] = _wait_for_effect(
                    lam_attacker, store, function_name=function_name, action_id=action_id,
                    want="denied_by_iam", run_id=run_id, phase="revoke",
                    max_s=PROP_MAX_REVOKE_S)
                print(f"    grant removed; denial re-asserted="
                      f"{mutation_log['propagation_revoke']['reached']} after "
                      f"{mutation_log['propagation_revoke']['seconds']}s")
                if ARM_RESTORED in cps:
                    print(f"[{ARM_RESTORED}] n={n_restored} direct invokes after restore")
                    tallies[ARM_RESTORED] = _run_arm(
                        lam_attacker, cps[ARM_RESTORED], store, arm=ARM_RESTORED,
                        function_name=function_name, action_id=action_id, n=n_restored,
                        run_id=run_id)
        # Belt and braces: whatever happened above, the grant must not survive this process.
        left = capture(store, "list_role_policies", iam, RoleName=role_name)
        if left.ok and grant_name in (left.response.get("PolicyNames") or []):
            capture(store, "delete_role_policy", iam, RoleName=role_name,
                    PolicyName=grant_name)
            mutation_log["swept_in_finally"] = True
        if grant_recorded:
            still = capture(store, "list_role_policies", iam, RoleName=role_name)
            if still.ok and grant_name not in (still.response.get("PolicyNames") or []):
                state.drop("iam-inline-policy", "f51_grant")
                state.write()
        # The CONTROL-PLANE end state, read from IAM after every restore path above has run. This
        # is the reading that answers "was the testbed left as we found it", and unlike the data
        # plane it is definitive: `ListRolePolicies` is strongly consistent for this purpose in
        # the sense that matters here — it either names the grant or it does not. A failed read is
        # recorded as a failed read, not as a clean role (feedback_guard_tool_exit_codes).
        end = capture(store, "list_role_policies", iam, RoleName=role_name)
        mutation_log["inline_policies_at_end"] = (
            sorted(end.response.get("PolicyNames") or []) if end.ok else None)
        mutation_log["end_state_read_ok"] = bool(end.ok)
        mutation_log["end_state_error_code"] = end.error_code if not end.ok else ""
        for cp in cps.values():
            cp.save()

    if rc:
        return rc

    closed = tallies.get(ARM_CLOSED, {})
    granted = tallies.get(ARM_GRANTED, {})
    restored = tallies.get(ARM_RESTORED, {})
    prop_grant = mutation_log.get("propagation_grant", {})
    prop_revoke = mutation_log.get("propagation_revoke", {})

    guards = {
        "role_started_in_its_shipped_configuration":
            common.get("startup_interlock", {}).get("inline_policies_at_start")
            == [BASELINE_INLINE],
        # Not "the granted arm executed" but "the granted arm came back with OUR text from THE
        # tool". An execution that returned someone else's output, or an unknown_tool error,
        # would leave the target's reachability unproven and the closed arm uninterpretable.
        "granted_arm_proved_the_target_real":
            bool(granted.get("n_echoed_marker", 0) > 0),
        # WAS the testbed left as we found it. A CONTROL-PLANE question, and the one
        # PREREGISTRATION's restore_verification rule actually asks. `delete_ok` alone is not
        # enough — it says the call returned, not that the role is clean — so the end state is
        # read back from IAM and compared to the shipped baseline.
        "grant_was_removed_from_the_role":
            bool(mutation_log.get("delete_ok"))
            and mutation_log.get("inline_policies_at_end") == [BASELINE_INLINE],
        # DID the deny come back on the data plane. Measured, and deliberately NOT gated on it
        # happening within the poll: see `data_plane_reconvergence` below for why the strict
        # form ("all 20 post-restore invocations denied") is reported rather than required.
        "denial_was_reasserted_in_the_data_plane":
            bool(prop_revoke.get("reached")) and restored.get("n_denied", 0) > 0,
        # An n-floor is a floor on how tightly a CLOSED boundary can be bounded — one denial does
        # not license "this route is shut". It is NOT a floor on demonstrating the route is OPEN:
        # a single closed-arm invocation that actually executed the tool is a bypass, and a bypass
        # does not become unproven because the other 119 attempts were unusable. Gating on n alone
        # would publish NOT_MEASURED over a demonstrated bypass, which is the one direction of
        # error this whole family exists to catch.
        "usable_trials_met_the_preregistered_n":
            closed.get("n_usable", 0) >= (n_closed if is_smoke else PLANNED_N)
            or closed.get("n_executed", 0) > 0,
    }
    # The half that was removed from the guard, computed in full and published. This is the
    # finding, not a footnote: the document's route-4 and section-4 remedies read as though
    # removing a permission closes the path, and here is how long it did not.
    n_res_exec = restored.get("n_executed", 0)
    n_res = restored.get("n_usable", 0)
    data_plane_reconvergence = {
        "strict_form_all_post_restore_invocations_denied": n_res > 0 and n_res_exec == 0,
        "n_post_restore_invocations": n_res,
        "n_that_still_executed": n_res_exec,
        "seconds_to_three_consecutive_denials": prop_revoke.get("seconds"),
        "seconds_to_the_first_denial": prop_revoke.get("seconds_to_first_confirmation"),
        "confirmations_required": prop_revoke.get("confirmations_required"),
        "revoke_wait_bound_s": prop_revoke.get("max_wait_s"),
        "revoke_probe_outcomes": prop_revoke.get("outcomes_seen"),
        "grant_direction_for_contrast": {
            "seconds_to_three_consecutive_executions": prop_grant.get("seconds"),
            "flapped_before_converging": prop_grant.get("flapped_before_converging"),
        },
        "why_this_is_reported_and_not_required": (
            "the strict form asks IAM for a guarantee it does not offer on this timescale. Under "
            "a one-confirmation revoke wait 9 of 20 post-restore invocations executed; under "
            "three consecutive confirmations spanning 248.5s, 4 of 20 still did; on the next run "
            "three consecutive denials were not reached inside 300s at all, and yet an "
            "independent 12-probe check minutes later returned 12/12 denied. Raising the "
            "confirmation count postpones the same misreading rather than fixing it, because "
            "eventual consistency has no bound to wait for. Requiring it would make this case "
            "permanently unpublishable while the boundary it tests — whether the runtime role "
            "can reach the tool in its SHIPPED configuration — is measured cleanly at n=120."),
        "what_is_still_required": (
            "the control-plane guard `grant_was_removed_from_the_role`, which reads the role's "
            "inline policy set back from IAM and compares it to the shipped baseline, and "
            "`denial_was_reasserted_in_the_data_plane`, which requires the deny to be observed "
            "again at all"),
        "amendment_candidate": (
            "sections 4 and 5 treat revoking an IAM grant as an immediate remedy. Measured here: "
            "a direct invoke was still succeeding 220s after DeleteRolePolicy returned 200, and "
            "the post-restore sample still contained executions after three consecutive denials. "
            "An incident runbook that removes a permission and proceeds is relying on something "
            "this measurement does not support."),
    }
    # Recorded separately so the reason the gate passed is legible: with a bypass in hand the
    # verdict is FALSE regardless of n, and `evaluate` already widens the interval note for it.
    guards_detail_n = {
        "n_usable": closed.get("n_usable", 0),
        "n_required": n_closed if is_smoke else PLANNED_N,
        "n_executed_in_closed_arm": closed.get("n_executed", 0),
        "gate_satisfied_by": ("a demonstrated bypass (closed-arm execution), not the n floor"
                              if closed.get("n_usable", 0) < (n_closed if is_smoke else PLANNED_N)
                              and closed.get("n_executed", 0) > 0 else "the preregistered n floor"),
    }

    if not guards["usable_trials_met_the_preregistered_n"]:
        rec = O.not_measured(
            CASE,
            f"only {closed.get('n_usable', 0)} of {n_closed} closed-arm attempts were usable "
            f"(codes {closed.get('error_codes')}); an attempt that was neither executed nor "
            f"denied by IAM is not evidence about authorization, and publishing against the "
            f"smaller denominator would report a bound the run did not earn",
            arms=tallies, mutation=mutation_log)
        P.emit(CASE, rec, {**common, "guards": guards, "guards_detail_n": guards_detail_n, "arms": tallies, "data_plane_reconvergence": data_plane_reconvergence,
                           "mutation": mutation_log}, store)
        return 2

    if not guards["granted_arm_proved_the_target_real"]:
        rec = O.not_measured(
            CASE,
            "the mandatory mutation did not demonstrate a reachable target: no granted-arm "
            "invocation returned the echo tool's output carrying our marker. The closed arm's "
            "denials are therefore consistent with an unreachable target and cannot be read as "
            "a boundary (see the module docstring)",
            arms=tallies, mutation=mutation_log)
        P.emit(CASE, rec, {**common, "guards": guards, "guards_detail_n": guards_detail_n, "arms": tallies, "data_plane_reconvergence": data_plane_reconvergence,
                           "mutation": mutation_log}, store)
        return 2

    obs = P.obs_zero_events(
        CASE,
        adverse=closed["n_executed"],
        n=closed["n_usable"],
        arms=tallies,
        mutation=mutation_log,
        guards=guards,
        adverse_definition=("a direct lambda:Invoke as the runtime execution role that the "
                            "service accepted and ran (StatusCode 200), in the role's shipped "
                            "configuration"),
        propagation_seconds={"grant": prop_grant.get("seconds"),
                             "revoke": prop_revoke.get("seconds")},
    )
    # An ATTRIBUTE, not a keyword to the builder above. `obs_zero_events` sweeps surplus keywords
    # into `detail`, which the decision rule never reads, so the keyword form left the field None
    # and `evaluate` downgraded a clean 120-trial TRUE to INCONCLUSIVE for "the mutation was not
    # recorded" — with the inverted mutation sitting in the same payload. `P._detail` now refuses
    # the keyword spelling outright, so this cannot silently regress.
    obs.mutation_inverted = bool(granted.get("n_executed", 0) > 0
                                 and closed.get("n_executed", 1) == 0)
    # `evaluate` takes the Observation ALONE — the case id travels inside it, so that a record
    # cannot be decided under one case's binding while carrying another's data. Passing CASE
    # again is not a harmless duplicate; it is a TypeError, and it fired here only AFTER all 160
    # invocations and both IAM mutations had been made.
    rec = O.evaluate(obs)
    P.emit(CASE, rec, {**common, "guards": guards, "guards_detail_n": guards_detail_n, "arms": tallies, "data_plane_reconvergence": data_plane_reconvergence,
                       "mutation": mutation_log}, store)

    print(f"\n{CASE}: adverse={closed['n_executed']} / n_usable={closed['n_usable']} "
          f"-> verdict {rec['verdict']}")
    print("guards: " + ", ".join(f"{k}={v}" for k, v in guards.items()))
    if not all(guards.values()):
        print("\nAT LEAST ONE GUARD IS FALSE — the verdict above is not publishable as it "
              "stands; see results/phase1/F5-1.json")
    return 0 if rec["verdict"] in O.DECISIVE else 1


if __name__ == "__main__":
    sys.exit(main())
