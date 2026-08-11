"""The deterministic tool target. No model, no network, no state.

This file is the Lambda function's source, deployed by `infra/02_lambda.py` as a zip. It is a
separate file rather than an inline string so that `verify_phase0.sh`'s compile gate covers it:
a SyntaxError in a handler embedded in a string would be discovered by a `ValidationException`
at the first tool call, after the gateway and policy engine had already been built.

Why a constant tool
-------------------
Every observed variance in Phases 3–6 must be attributable to the policy/guardrail path. A
model-backed target would contribute its own non-determinism and its own latency distribution,
and F2's whole subject is separating policy determinism from guardrail non-determinism — an
experiment that cannot survive a third source of variation it did not measure.

So the tool is a pure function of its arguments, with three modes:

`echo`   — returns `text` verbatim. This is the **`context.output.*` driver**: without a tool
           whose output the caller controls, `suppressOutput` and the output-side content
           filters are essentially untestable, because nothing else in the testbed can place a
           chosen string into a tool response.
`fixed`  — returns a canned payload chosen by `key` from a table whose sha256 is returned
           alongside it. The hash is the point: F3's gateway-side arms compare payloads
           across configurations, and "the payload changed between arms" and "the guardrail
           behaved differently" are indistinguishable unless the payload is pinned. A reader
           can recompute the digest from `PAYLOADS` in this file.
`delay`  — sleeps a requested number of milliseconds, then reports the sleep it actually
           performed. This is the **ground-truth `TargetExecutionTime`** term in F6's
           additivity identity `Duration_gw ≟ GuardrailLatency + TargetExecutionTime + ε`.
           Without a target whose execution time is known independently of the service's own
           reporting, testing that identity would mean using the service's number on both
           sides, which tests nothing.

`amount` is a typed **number** and `text` a **string** so Cedar parameter conditions
(`context.input.amount >= 500`) are exercisable — F2-1's pure-Cedar arm depends on a numeric
parameter reaching the policy engine as a number, not as a string that happens to contain
digits.

Determinism, stated precisely
-----------------------------
`echo` and `fixed` are pure. `delay` is pure in its *return value* and deliberately not in its
wall clock. Nothing here reads the clock into a returned field except `slept_ms`, which is
measured with `time.monotonic` and reported so a trial can distinguish "the sleep was 250 ms"
from "the platform descheduled us". No randomness, no I/O, no imports beyond the standard
library — a dependency would introduce a version whose behaviour could change between arms
collected on different days, and Phase 8 re-runs at +7d and +30d.
"""

from __future__ import annotations

import hashlib
import json
import time

# The tool-name delimiter. AWS's `gateway-tool-naming.html` specifies
# `${target_name}___${tool_name}` — three underscores. Note that
# `gateway-add-target-lambda.html` renders it as `${target_name}_${tool_name}` in prose while
# its own boilerplate on the same page uses `"___"`; the naming page and the boilerplate agree,
# so the single underscore is a documentation error. Splitting on the wrong delimiter yields a
# tool name of `_echo` and an "unknown tool" error for every call, so this is asserted against
# the observed context in `infra/tests/test_echo_handler.py` rather than trusted.
DELIMITER = "___"

# Canned payloads for `fixed`. Versioned by content hash, not by a version number nobody
# increments. Keys are chosen to be inert with respect to every guardrail in the testbed: a
# payload that happened to trip a content filter would make the *target* a confound in an arm
# measuring the filter.
PAYLOADS: dict[str, str] = {
    "benign": "The requested inventory count is 42 units, available in warehouse B.",
    "short": "ok",
    # 1 KiB of a repeating benign phrase, for F10's text-unit accounting and F6's payload-size
    # arm. Built by repetition rather than by a lorem-ipsum blob so its length is exact and its
    # content is verifiable by inspection.
    "kib": ("inventory record ok. " * 52)[:1024],
}


def payload_digest(key: str) -> str:
    """sha256 of a canned payload, so an arm can pin what it received.

    Returned in the response rather than only computed here: an arm that compares payloads
    across configurations needs the digest *in its evidence file*, and recomputing it during
    analysis from a table that may have been edited since is not a check.
    """
    return hashlib.sha256(PAYLOADS[key].encode("utf-8")).hexdigest()


def tool_name_from_context(context) -> str:
    """The bare tool name, with the target-name prefix stripped.

    AWS requires this to be done by hand (`gateway-add-target-lambda.html`, "Key
    considerations"). `rsplit` with a count of 1 rather than `index`: a *target* name
    containing the delimiter would make a left-hand `index` cut in the wrong place, and the
    AWS boilerplate's `originalToolName.index(delimiter)` has that bug. Our target names
    contain no underscores, so this is defensive — but the failure it prevents is a tool name
    of `_echo` reported as "unknown tool", which reads as a gateway problem rather than a
    parsing one.
    """
    custom = {}
    client_context = getattr(context, "client_context", None)
    if client_context is not None:
        custom = getattr(client_context, "custom", None) or {}
    raw = custom.get("bedrockAgentCoreToolName", "")
    if DELIMITER in raw:
        return raw.rsplit(DELIMITER, 1)[1]
    return raw


def _context_meta(context) -> dict:
    """The AgentCore metadata, echoed back so a trial can join a response to a request.

    `bedrockAgentCoreAwsRequestId` and `bedrockAgentCoreMcpMessageId` are the join keys F7
    needs to link a span to a trial. They arrive only in the client context, so a response
    that omits them cannot be joined to its span afterwards — and F3-10's whole question is
    whether per-request linkage survives.
    """
    custom = {}
    client_context = getattr(context, "client_context", None)
    if client_context is not None:
        custom = getattr(client_context, "custom", None) or {}
    return {k: custom.get(k, "") for k in (
        "bedrockAgentCoreMessageVersion", "bedrockAgentCoreAwsRequestId",
        "bedrockAgentCoreMcpMessageId", "bedrockAgentCoreGatewayId",
        "bedrockAgentCoreTargetId", "bedrockAgentCoreToolName")}


def lambda_handler(event, context):
    """Dispatch on the stripped tool name. Returns a JSON-serializable dict.

    Errors are returned as data with an `error` key rather than raised. A raised exception
    becomes a Lambda function error, which the gateway surfaces as a 5xx — and a 5xx is
    indistinguishable from a genuine service failure in an arm whose oracle is an HTTP status.
    An arm asserting "the tool was reached and rejected the arguments" needs a 200 carrying a
    refusal.
    """
    tool = tool_name_from_context(context)
    args = event if isinstance(event, dict) else {}
    meta = _context_meta(context)
    base = {"tool": tool, "context": meta}

    if tool == "echo":
        text = args.get("text")
        if not isinstance(text, str):
            return {**base, "error": "bad_request",
                    "detail": f"echo requires a string `text`; got {type(text).__name__}"}
        amount = args.get("amount")
        return {**base, "mode": "echo", "text": text,
                # Echoed so a Cedar condition on `context.input.amount` can be correlated
                # with what the tool actually received: a policy that denies on
                # `amount >= 500` and a tool that saw a string "500" are a real failure mode,
                # and it is invisible unless the tool reports the type it observed.
                "amount": amount, "amount_type": type(amount).__name__,
                "text_len": len(text),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}

    if tool == "fixed":
        key = args.get("key", "benign")
        if key not in PAYLOADS:
            return {**base, "error": "bad_request",
                    "detail": f"unknown key {key!r}; known: {sorted(PAYLOADS)}"}
        return {**base, "mode": "fixed", "key": key, "text": PAYLOADS[key],
                "text_len": len(PAYLOADS[key]), "text_sha256": payload_digest(key)}

    if tool == "delay":
        ms = args.get("ms", 0)
        if not isinstance(ms, (int, float)) or isinstance(ms, bool):
            return {**base, "error": "bad_request",
                    "detail": f"delay requires a numeric `ms`; got {type(ms).__name__}"}
        # Capped. An unbounded sleep from a malformed argument would burn the function's
        # timeout and bill for it, and every arm here uses ms <= 2000.
        ms = max(0.0, min(float(ms), 5000.0))
        t0 = time.monotonic()
        time.sleep(ms / 1000.0)
        slept = (time.monotonic() - t0) * 1000.0
        return {**base, "mode": "delay", "requested_ms": ms,
                # The MEASURED sleep, which is the ground-truth TargetExecutionTime term.
                # Reported separately from `requested_ms` because they differ under
                # descheduling, and F6's residual would absorb that difference as ε if only
                # the requested value were known.
                "slept_ms": round(slept, 3)}

    return {**base, "error": "unknown_tool",
            "detail": f"no tool named {tool!r}; known: echo, fixed, delay",
            # The raw name, so a delimiter-parsing failure is diagnosable from the response
            # rather than requiring a CloudWatch log dive.
            "raw_tool_name": meta.get("bedrockAgentCoreToolName", "")}


# The tool schema, kept HERE beside the handler that implements it.
#
# `02_lambda.py` imports this and `04_target.py` registers it, so the schema the gateway
# advertises and the dispatch that serves it cannot drift apart — which is a real failure mode
# with a real signature: a schema declaring `amount` as a string while the handler tests
# `isinstance(amount, (int, float))` would make every Cedar numeric-condition arm silently
# take the `bad_request` branch, and the arm would read it as the policy denying.
TOOL_SCHEMA = [
    {
        "name": "echo",
        "description": "Returns the supplied text verbatim. Deterministic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "text to return unchanged"},
                "amount": {"type": "number",
                           "description": "an amount, for Cedar numeric conditions"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "fixed",
        "description": "Returns a canned payload selected by key. Deterministic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string",
                        "description": "one of: " + ", ".join(sorted(PAYLOADS))},
            },
            "required": [],
        },
    },
    {
        "name": "delay",
        "description": "Sleeps for the requested milliseconds and reports the measured sleep.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ms": {"type": "number", "description": "milliseconds to sleep, 0-5000"},
            },
            "required": ["ms"],
        },
    },
]


if __name__ == "__main__":
    # Runnable locally so the payload table's digests can be read without deploying. Printed
    # rather than asserted here; `infra/tests/test_echo_handler.py` holds the assertions.
    print(json.dumps({k: {"len": len(v), "sha256": payload_digest(k)}
                      for k, v in sorted(PAYLOADS.items())}, indent=2))
