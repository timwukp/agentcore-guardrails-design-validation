#!/usr/bin/env python3
"""The MCP data plane: SigV4-signed JSON-RPC over HTTP to a gateway's `gatewayUrl`.

This module exists because **there is no boto3 operation that invokes a gateway tool.** All 66
`bedrock-agentcore` data-plane operations were enumerated; none of them is a gateway invoke
(the closest, `InvokeAgentRuntime`, is a different resource). A tool call is a SigV4-signed
`POST` of an MCP JSON-RPC envelope to the `gatewayUrl` that `CreateGateway`/`GetGateway`
returns — so every observation in F2, F3 (gateway-side), F4, F5 and F6 passes through the code
below, and a defect here is indistinguishable from a finding about the service.

Why hand-rolled rather than a client library
--------------------------------------------
`httpx` and `requests` are **absent from both venvs** (`urllib3 2.7.0` is what is installed),
and the reference `mcp-proxy-for-aws` helper is an `httpx.Auth` subclass. Adding a dependency to
sign an HTTP request would change the environment that every result is attributed to, three
phases in, for no observational gain. `botocore.auth.SigV4Auth` + `botocore.awsrequest.AWSRequest`
are present and are what botocore itself signs with, so the signature path here is the same code
that signs every control-plane call in this project.

The one load-bearing detail inherited from that helper, and it is not obvious: **pop the
`connection` header before signing.** `Connection: keep-alive` is not part of the server-side
signature calculation, so including it in `SignedHeaders` produces a signature mismatch — a 403
that reads exactly like an authorization finding. That would have been attributed to Cedar.

Sessions are enabled, so the session header is mandatory
-------------------------------------------------------
`infra/04_gateway.py` sets `protocolConfiguration.mcp.sessionConfiguration`, which **enables**
MCP sessions on both gateways. Per `gateway-sessions.html` that changes the client contract:

* `initialize` returns an `Mcp-Session-Id` **response header**.
* Every subsequent request must carry it. Missing it -> **HTTP 400**.
* An unknown or expired id -> **HTTP 404**.
* Under SigV4 the session is scoped to the caller's principal ARN, so a different principal
  reusing a valid id also gets 404.

A client that skipped the handshake would therefore fail every call in every phase with a 400
that has nothing to do with any hypothesis under test. `initialize` is not optional politeness
here; it is what makes the transport work at all. `sessionTimeoutInSeconds` is 900 (the legal
range is 900-28800, default 3600), which is short enough that a long arm must handle renewal —
see `refresh_if_stale`.

A denial is an HTTP 200, so the oracle cannot read the status code
------------------------------------------------------------------
`use-gateway-with-policy.html` gives the deny shape verbatim:

    {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":
     "AuthorizeActionException - Tool Execution Denied: Tool call not allowed due to policy
      enforcement [No policy applies to the request (denied by default).]"}],"isError":true}}

HTTP **200**. `isError: true` inside `result`, and the reason in prose. Any oracle keyed on the
status code is blind to every policy decision this project measures. `classify()` therefore reads
`result.isError` and the message text, and keeps an explicit `unclassified` bucket rather than
letting an unrecognised error fall through to "allowed" — the direction of that default decides
whether an unknown failure mode is reported as a bypass.

Two further documented facts that shape the API here
----------------------------------------------------
* **Policy evaluation applies only to tools.** `prompts/list`, `prompts/get`, `resources/list`,
  `resources/read` and `resources/templates/list` are always allowed regardless of engine mode.
  `prompts_list()`/`resources_list()` exist so F4 can *measure* that rather than assume it.
* **`tools/list` is a meta action.** A principal may list a tool "if there exists any set of
  circumstances under which a call to that tool would be permitted". Visibility in `tools/list`
  is therefore **not** evidence that a call is authorized, and `list_tools()`'s docstring says so
  where a reader will see it.

Temporal policies need a header we generate
-------------------------------------------
`x-amzn-bedrock-agentcore-policy-session-id` is **client**-generated and must be present on
every request from the first if the engine contains a temporal policy; the gateway never
generates one, and its absence is a validation error rather than a deny. It is a constructor
argument, not a per-call one, because a session id that changed mid-conversation would silently
reset whatever temporal state the policy accumulated.

Nothing in this module decides anything
---------------------------------------
`classify()` returns observations (`outcome`, `is_error`, `text`, flags). It assigns no pass/fail
and applies no threshold; that is `lib/oracle.py`'s job, and keeping the split means a transport
bug cannot manufacture a verdict.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evidence import EvidenceStore, Record  # noqa: E402

import botocore  # noqa: E402

# --------------------------------------------------------------------------
# protocol constants
# --------------------------------------------------------------------------

# The version the AWS gateway sample sends. Pinned rather than "latest": the negotiated version
# is echoed in the initialize result, and a version the harness did not choose would make a
# behavioural change on the service side indistinguishable from one on ours.
PROTOCOL_VERSION = "2025-06-18"

# The SigV4 signing name. `bedrock-agentcore` for BOTH planes — the control-plane model's
# endpointPrefix is `bedrock-agentcore-control` but its signingName is `bedrock-agentcore`, and
# the signing name is what goes in the credential scope.
SIGNING_SERVICE = "bedrock-agentcore"

SESSION_HEADER = "Mcp-Session-Id"
POLICY_SESSION_HEADER = "x-amzn-bedrock-agentcore-policy-session-id"

# The accepted grammar of the policy-session-id header value. MEASURED against the live main
# gateway on 2026-08-11, not read from documentation — the AgentCore docs state that the header is
# client-generated and required from the first call, but state no grammar for it, and our own
# document repeats the requirement without one either (see V13_CANDIDATES.md, F4-0b).
#
# What was measured, one variable at a time, on `initialize`:
#   accepted   `A-Z a-z 0-9 -`   hyphen legal in any position including leading and trailing
#   rejected   `_`  `.`  `:`  `~`  `+`  `%`      (`%5F` rejected too: the value is NOT
#                                                 percent-decoded before validation)
#   length     128 accepted, 129 rejected — bisected, so the ceiling is exact, not a bound
#
# The rejection is the reason this constant exists rather than a comment. An illegal value is
# answered with HTTP 400, `x-amzn-errortype: InternalFailure`, and a JSON-RPC body of
# `-32600 "Invalid request - Malformed JSON-RPC request"`. That error names the BODY, and the body
# is well-formed; it took a five-variant bisect to establish that the fault was a header. Per
# `feedback_cryptic_error_is_missing_guard`, the guard belongs on our side of the call.
POLICY_SESSION_ALLOWED = re.compile(r"[^A-Za-z0-9-]")
POLICY_SESSION_MAX_LEN = 128
POLICY_SESSION_GRAMMAR = "^[A-Za-z0-9-]{1,128}$"


def normalize_policy_session_id(raw: str) -> str:
    """Coerce `raw` into `POLICY_SESSION_GRAMMAR`, injectively.

    Injectivity matters more than prettiness here; see `policy_session_id`. The hash is over the
    ORIGINAL string, so two arms that normalize to the same characters still receive different
    session ids.
    """
    norm = POLICY_SESSION_ALLOWED.sub("-", raw)
    if norm == raw and len(norm) <= POLICY_SESSION_MAX_LEN:
        return norm
    tag = "-h" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return norm[:POLICY_SESSION_MAX_LEN - len(tag)] + tag


def check_policy_session_id(value: str) -> None:
    """Raise `McpTransportError` on a value the gateway would reject. Never sent blind.

    Called from `McpClient.__init__`, so a malformed id fails before any AWS call is made and
    before any trial is counted. Without this, the failure arrives as a JSON-RPC error about the
    body and is indistinguishable, in a results table, from a gateway rejecting the request.
    """
    bad = sorted(set(POLICY_SESSION_ALLOWED.findall(value)))
    if bad or not value or len(value) > POLICY_SESSION_MAX_LEN:
        raise McpTransportError(
            f"policy session id {value!r} violates the measured gateway grammar "
            f"{POLICY_SESSION_GRAMMAR}: "
            f"{'illegal characters ' + ''.join(bad) if bad else ''}"
            f"{'; ' if bad and len(value) > POLICY_SESSION_MAX_LEN else ''}"
            f"{f'length {len(value)} > {POLICY_SESSION_MAX_LEN}' if len(value) > POLICY_SESSION_MAX_LEN else ''}"
            f"{'empty value' if not value else ''}. "
            f"The gateway answers an illegal value with HTTP 400 and a JSON-RPC "
            f"-32600 'Malformed JSON-RPC request', which names the body and not the header, so "
            f"this is checked here instead. Use mcp.normalize_policy_session_id().")

# Both media types, deliberately. MCP's streamable-HTTP transport requires a client to accept
# `text/event-stream`, and a server is entitled to answer 406 if it does not — which would be a
# transport failure indistinguishable, in a results table, from a gateway rejecting the call.
# Our gateways are created with `enableResponseStreaming: False` so the answer should always be
# JSON, but advertising only JSON would make that configuration load-bearing for the transport
# as well as for the latency measurement. `_parse_body` handles either.
ACCEPT = "application/json, text/event-stream"

CONTENT_TYPE = "application/json"

# The prose the service uses when Cedar's default-deny fires. Matched as a substring, and the
# broader `AuthorizeActionException` marker is checked separately, so a reworded parenthetical
# degrades to "policy_denied without an identified reason" instead of to "allowed".
AUTHORIZE_EXCEPTION = "AuthorizeActionException"
DEFAULT_DENY_TEXT = "No policy applies to the request (denied by default)"
_DENY_MARKERS = ("Tool Execution Denied", "policy enforcement")

# Methods that AWS documents as exempt from policy evaluation. Kept as data so F4 can iterate
# them instead of a test naming them one at a time and missing the fifth.
UNEVALUATED_METHODS = ("prompts/list", "prompts/get", "resources/list", "resources/read",
                       "resources/templates/list")

_SSE_DATA_RE = re.compile(r"^data:\s?(.*)$")


class McpTransportError(RuntimeError):
    """A failure of the transport, as distinct from a decision by the gateway.

    Separate from `evidence.CapturedCallError` because the two mean opposite things to an arm: a
    `CapturedCallError` on a control-plane call may be the observation (`AccessDenied` is half
    this project's oracles), whereas a malformed MCP envelope or a missing session header is a
    defect in this module and must never be scored as a result. Carries the status and request id
    so the failure is still traceable to a service-side log entry.

    `error_class` is the name of the underlying transport exception when there is one, and it is
    the field that makes this exception RETRYABLE. `lib/checkpoint.is_retryable` works from an
    allowlist and classifies anything it cannot identify as permanent, judging a code-less
    wrapper on exactly this attribute; without it, every data-plane failure got **zero** retries
    while `retries=False` on the pool meant nothing else would retry either. That combination
    already cost this project 3,378 Phase 1 trials on the control plane (DEV-P1-11), where the
    same identity was computed at the raise site and then discarded. It is empty for the raises
    that are genuinely OUR defect — a missing session id, absent credentials, a gateway whose
    session configuration is not what the ledger recorded — because those must not be retried:
    retrying a bug just spends the rate budget three times before failing identically.
    """

    def __init__(self, message: str, *, http_status: int | None = None,
                 request_id: str = "", body: str = "", error_class: str = "") -> None:
        super().__init__(message)
        self.http_status = http_status
        self.request_id = request_id
        self.body = body[:4000]
        self.error_class = error_class


# --------------------------------------------------------------------------
# observations
# --------------------------------------------------------------------------

OUTCOMES = ("allowed", "policy_denied", "tool_error", "jsonrpc_error", "http_error")


@dataclass
class Decision:
    """What the gateway did, as an observation. No verdict, no threshold, no pass/fail.

    `outcome` is one of `OUTCOMES`:

    * `allowed`       -- `result` present, `isError` falsy. The tool ran.
    * `policy_denied` -- `isError` true and the text carries the documented denial markers.
    * `tool_error`    -- `isError` true, no denial marker. Our own handler's `bad_request`
                         lands here, which is why `unclassified` exists: an error shape nobody
                         has seen before must be visible, not folded into a known bucket.
    * `jsonrpc_error` -- a JSON-RPC `error` object rather than a `result`. Protocol-level.
    * `http_error`    -- non-2xx. 400 = missing session header, 404 = unknown/expired session
                         or wrong principal, 403 = signature or IAM.

    `default_deny` is only ever True when the service named itself as such; it is not inferred
    from the absence of a policy, because "no policy matched" and "a forbid matched" are the two
    hypotheses F4-4 exists to separate.
    """

    outcome: str
    http_status: int | None
    request_id: str = ""
    is_error: bool | None = None
    text: str = ""
    content: list = field(default_factory=list)
    structured: Any = None
    jsonrpc_error: dict | None = None
    default_deny: bool = False
    authorize_exception: bool = False
    unclassified: bool = False
    duration_ms: float = 0.0
    session_id: str = ""
    body: dict | None = None

    @property
    def denied(self) -> bool:
        return self.outcome == "policy_denied"

    @property
    def ran(self) -> bool:
        return self.outcome == "allowed"

    # `allowed` reads better than `ran` at a call site asserting an expectation, and both names
    # exist deliberately: `ran` is about the tool, `allowed` is about the decision, and an arm
    # that cares which one it means should be able to say so.
    allowed = ran

    def to_json(self) -> dict:
        """The row that goes into `results/`. Includes the flags, excludes the raw body.

        `body` is omitted here on purpose: the full response is already archived by `_record()`
        under its request id, and duplicating it into the results table would make the table
        large enough that nobody reads it while adding no information. `unclassified` and
        `default_deny` are kept, because an analysis that drops them cannot distinguish "the
        service denied by default" from "we did not recognise the answer" — and `classify()`
        exists to keep those apart.
        """
        return {
            "outcome": self.outcome,
            "http_status": self.http_status,
            "request_id": self.request_id,
            "is_error": self.is_error,
            "text": self.text[:2000],
            "default_deny": self.default_deny,
            "authorize_exception": self.authorize_exception,
            "unclassified": self.unclassified,
            "duration_ms": round(self.duration_ms, 3),
            "session_id": self.session_id,
            "jsonrpc_error": self.jsonrpc_error,
        }


def _text_of(content: list) -> str:
    """Concatenate the `text` fields of an MCP content array, in order."""
    parts = []
    for item in content or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(parts)


def classify(http_status: int | None, body: dict | None, *, request_id: str = "",
             duration_ms: float = 0.0, session_id: str = "") -> Decision:
    """Turn one HTTP response into a `Decision`. Pure; no I/O, no clock.

    Pure so that every classification in `results/` is reproducible from the archived response
    body alone — including a re-classification months later, if a reader disputes the reading of
    a message we treated as a denial.
    """
    if http_status is None or not (200 <= http_status < 300):
        return Decision(outcome="http_error", http_status=http_status,
                        request_id=request_id, duration_ms=duration_ms,
                        session_id=session_id, body=body,
                        text=json.dumps(body)[:2000] if body is not None else "")

    if not isinstance(body, dict):
        return Decision(outcome="jsonrpc_error", http_status=http_status,
                        request_id=request_id, duration_ms=duration_ms,
                        session_id=session_id, unclassified=True,
                        text=f"response body was {type(body).__name__}, not a JSON object")

    if "error" in body and "result" not in body:
        err = body.get("error") or {}
        msg = str(err.get("message", ""))
        # MEASURED 2026-08-11, F4 smoke, run r20260810T130945Z: a gateway policy denial
        # arrives as a JSON-RPC **error**, code -32002, message "Tool Execution Denied: Tool
        # call not allowed due to policy enforcement [Policy evaluation denied due to
        # <policyId>]" — NOT as the `result.isError` + AuthorizeActionException shape the
        # module docstring was written from. Both shapes are kept: this branch catches the
        # protocol-level form, the `isError` branch below still catches the in-band form, and
        # whichever the service sends classifies as `policy_denied`. Without this, every
        # denial landed in `jsonrpc_error`, `_usable` (correctly) refused it as an answer,
        # and a truth-table run whose denials all worked reported zero usable trials.
        # `is_error` stays None here on purpose: there is no `result` to read it from, and
        # inventing True would let a reader think the in-band shape was observed.
        authorize = AUTHORIZE_EXCEPTION in msg
        marker = any(m in msg for m in _DENY_MARKERS)
        if authorize or marker:
            return Decision(outcome="policy_denied", http_status=http_status,
                            request_id=request_id, text=msg,
                            default_deny=DEFAULT_DENY_TEXT in msg,
                            authorize_exception=authorize,
                            unclassified=not marker,
                            jsonrpc_error=err,
                            duration_ms=duration_ms, session_id=session_id, body=body)
        return Decision(outcome="jsonrpc_error", http_status=http_status,
                        request_id=request_id, duration_ms=duration_ms,
                        session_id=session_id, body=body,
                        jsonrpc_error=err, text=msg)

    result = body.get("result")
    if not isinstance(result, dict):
        # A 200 with neither result nor error. Marked unclassified rather than guessed: this is
        # the shape a notification acknowledgement has, and treating it as success would let a
        # dropped tool call read as an allow.
        return Decision(outcome="jsonrpc_error", http_status=http_status,
                        request_id=request_id, duration_ms=duration_ms,
                        session_id=session_id, body=body, unclassified=True,
                        text="200 response carried neither `result` nor `error`")

    content = result.get("content") or []
    text = _text_of(content)
    is_error = bool(result.get("isError"))

    if not is_error:
        return Decision(outcome="allowed", http_status=http_status, request_id=request_id,
                        is_error=False, text=text, content=content,
                        structured=result.get("structuredContent"),
                        duration_ms=duration_ms, session_id=session_id, body=body)

    authorize = AUTHORIZE_EXCEPTION in text
    marker = any(m in text for m in _DENY_MARKERS)
    if authorize or marker:
        return Decision(outcome="policy_denied", http_status=http_status,
                        request_id=request_id, is_error=True, text=text, content=content,
                        default_deny=DEFAULT_DENY_TEXT in text,
                        authorize_exception=authorize,
                        # An `AuthorizeActionException` whose prose we do not recognise is still
                        # a denial, but the *reason* is unknown and that must be visible.
                        unclassified=not marker,
                        duration_ms=duration_ms, session_id=session_id, body=body)

    return Decision(outcome="tool_error", http_status=http_status, request_id=request_id,
                    is_error=True, text=text, content=content,
                    structured=result.get("structuredContent"),
                    # Our echo handler's own `{"error": "bad_request"}` is a known member of this
                    # bucket; anything that is not it is flagged.
                    unclassified="bad_request" not in text and "error" not in text.lower(),
                    duration_ms=duration_ms, session_id=session_id, body=body)


# --------------------------------------------------------------------------
# the client
# --------------------------------------------------------------------------

@dataclass
class Attempt:
    """One HTTP round trip, kept whether or not it succeeded."""

    method: str
    http_status: int | None
    request_id: str
    duration_ms: float
    t_start_utc: str
    t_end_utc: str
    session_id: str
    headers: dict
    body: dict | None
    error: str = ""


class McpClient:
    """A session-holding MCP client for one gateway URL and one principal.

    One instance = one principal = one MCP session. Not shared across principals, because the
    documented scoping means a session id presented by a different principal returns 404 — and
    a 404 in the middle of an arm reads as an expiry rather than as the reuse bug it is.

    Construction does no I/O. `initialize()` is explicit so a caller can time it separately from
    the tool calls it enables: the handshake is a round trip, and folding it into the first
    `call_tool` would put a one-off cost into F6's first paired difference.
    """

    def __init__(self, gateway_url: str, region: str, credentials, *,
                 store: EvidenceStore | None = None,
                 policy_session_id: str | None = None,
                 session_timeout_s: int = 900,
                 accept: str = ACCEPT,
                 connect_timeout: float = 10.0,
                 read_timeout: float = 70.0,
                 pool: urllib3.PoolManager | None = None) -> None:
        if not gateway_url.startswith("https://"):
            raise ValueError(
                f"gateway_url must be https (SigV4 over http would sign the payload "
                f"differently and the gateway does not serve it): {gateway_url!r}")
        self.gateway_url = gateway_url
        self.region = region
        self.credentials = credentials
        self.store = store
        if policy_session_id:
            check_policy_session_id(policy_session_id)
        self.policy_session_id = policy_session_id
        self.session_timeout_s = session_timeout_s
        self.accept = accept
        self.session_id: str = ""
        self.session_started_monotonic: float | None = None
        self.protocol_version: str = ""
        self.server_info: dict = {}
        # Counted, not hidden. A reactive renewal costs the trial that triggered it an extra
        # round trip, so F6 must be able to exclude those trials rather than average them in.
        self.session_renewals: int = 0
        self.reactive_renewals: int = 0
        self._id = 0
        self.attempts: list[Attempt] = []
        # retries=False for the reason `lib/awsclients.py` disables botocore's: a transparently
        # retried POST reports one duration covering several attempts, and a policy denial that
        # arrived on attempt 3 would be recorded as if it arrived immediately.
        self._pool = pool or urllib3.PoolManager(
            retries=False,
            timeout=urllib3.Timeout(connect=connect_timeout, read=read_timeout),
        )

    # -- signing -----------------------------------------------------------

    def _sign(self, body: bytes, headers: dict[str, str]) -> dict[str, str]:
        """SigV4-sign a POST to the gateway URL and return the headers to send.

        `connection` is popped before signing — see the module docstring. It is popped from the
        dict we build, so the pool manager is free to add its own afterwards: what matters is
        that it is not in `SignedHeaders`.
        """
        h = {k: v for k, v in headers.items() if k.lower() != "connection"}
        creds = self.credentials
        if hasattr(creds, "get_frozen_credentials"):
            creds = creds.get_frozen_credentials()
        req = AWSRequest(method="POST", url=self.gateway_url, data=body, headers=h)
        SigV4Auth(creds, SIGNING_SERVICE, self.region).add_auth(req)
        return dict(req.headers)

    # -- transport ---------------------------------------------------------

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    @staticmethod
    def _parse_body(raw: bytes, content_type: str) -> dict | None:
        """Parse a JSON body, or the JSON carried by an SSE `data:` frame.

        Both, because the gateway's `Accept` handling is a service behaviour we do not control
        and a 406 avoided by advertising `text/event-stream` is worthless if the SSE answer then
        fails to parse. An SSE stream with several frames is joined in order; in practice a
        single JSON-RPC response arrives as one frame.
        """
        if not raw:
            return None
        if "text/event-stream" in (content_type or ""):
            chunks = []
            for line in raw.decode("utf-8", "replace").splitlines():
                m = _SSE_DATA_RE.match(line)
                if m:
                    chunks.append(m.group(1))
            text = "".join(chunks).strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"__unparsed_sse__": text[:4000]}
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {"__unparsed__": raw.decode("utf-8", "replace")[:4000]}

    def _post(self, payload: dict, *, with_session: bool = True,
              expect_response: bool = True) -> Attempt:
        """One signed POST. Returns an `Attempt`; raises only on a transport-level failure."""
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "content-type": CONTENT_TYPE,
            "accept": self.accept,
            "content-length": str(len(body)),
        }
        if with_session:
            if not self.session_id:
                raise McpTransportError(
                    f"no MCP session id, and this gateway has sessionConfiguration set, so "
                    f"{payload.get('method')!r} would be answered with HTTP 400 for a reason "
                    f"unrelated to any hypothesis. Call initialize() first.")
            headers[SESSION_HEADER] = self.session_id
        if self.policy_session_id:
            # Sent on EVERY request including initialize, per the documented requirement that a
            # temporal policy sees it from the first call. Harmless when no temporal policy
            # exists, so it is unconditional rather than arm-dependent.
            headers[POLICY_SESSION_HEADER] = self.policy_session_id

        signed = self._sign(body, headers)

        t0_wall = datetime.now(timezone.utc)
        t0 = time.perf_counter_ns()
        resp = None
        err = ""
        err_class = ""
        try:
            resp = self._pool.request("POST", self.gateway_url, body=body, headers=signed,
                                      preload_content=True)
        except Exception as exc:                                   # noqa: BLE001
            # The class name is kept SEPARATELY from the formatted message, not only inside it.
            # `checkpoint.is_retryable` matches an allowlist against a bare name, so a name that
            # survives merely as a substring of prose is a name that cannot be matched — and an
            # unmatched transport failure is classified permanent and retried zero times.
            err_class = type(exc).__name__
            err = f"{err_class}: {exc}"
        t1 = time.perf_counter_ns()
        t1_wall = datetime.now(timezone.utc)

        if resp is None:
            att = Attempt(method=str(payload.get("method", "")), http_status=None,
                          request_id="", duration_ms=(t1 - t0) / 1e6,
                          t_start_utc=t0_wall.isoformat(), t_end_utc=t1_wall.isoformat(),
                          session_id=self.session_id, headers={}, body=None, error=err)
            self.attempts.append(att)
            self._record(att, payload)
            raise McpTransportError(
                f"POST to the gateway failed before a response: {err}",
                error_class=err_class)

        rheaders = {k.lower(): v for k, v in resp.headers.items()}
        parsed = None
        if expect_response:
            parsed = self._parse_body(resp.data, rheaders.get("content-type", ""))

        att = Attempt(
            method=str(payload.get("method", "")),
            http_status=resp.status,
            request_id=(rheaders.get("x-amzn-requestid")
                        or rheaders.get("x-amzn-request-id")
                        or rheaders.get("x-amz-request-id", "")),
            duration_ms=(t1 - t0) / 1e6,
            t_start_utc=t0_wall.isoformat(), t_end_utc=t1_wall.isoformat(),
            session_id=self.session_id, headers=rheaders, body=parsed,
        )
        self.attempts.append(att)
        self._record(att, payload)
        return att

    def _record(self, att: Attempt, payload: dict) -> None:
        """Write the attempt into the evidence store, in the same `Record` shape as an API call.

        Deliberately the same dataclass `lib/evidence.py`'s `capture()` produces: an MCP tool
        call and a control-plane call end up in one uniform archive, so an analysis that joins on
        `request_id` does not need to know which plane a row came from. `service` is written as
        `mcp` rather than `bedrock-agentcore` so the plane is still recoverable.
        """
        if self.store is None:
            return
        rec = Record(
            case_id=self.store.case_id,
            operation=f"mcp:{att.method or 'unknown'}",
            service="mcp", region=self.region,
            params=json.loads(json.dumps(payload, default=str)),
            ok=att.http_status is not None and 200 <= att.http_status < 300 and not att.error,
            http_status=att.http_status,
            request_id=att.request_id,
            trace_id=att.headers.get("x-amzn-trace-id", ""),
            headers=att.headers,
            response=att.body if isinstance(att.body, dict) else None,
            error_message=att.error,
            duration_ms=att.duration_ms,
            t_start_utc=att.t_start_utc, t_end_utc=att.t_end_utc,
            sdk_version=botocore.__version__,
        )
        self.store.add(rec)

    # -- session -----------------------------------------------------------

    def initialize(self) -> dict:
        """Perform the MCP handshake and capture the `Mcp-Session-Id` response header.

        The header is read off the **response**, not generated by us. `x-amzn-bedrock-agentcore-
        policy-session-id` is the opposite — client-generated — and confusing the two is why this
        docstring says which is which.

        Also sends `notifications/initialized` afterwards, as the protocol requires, and tolerates
        a non-2xx answer to it: the notification carries no id and no result, so a gateway that
        ignores it costs us nothing, whereas a hard failure here would abort a run over a message
        whose only purpose is politeness. Whether it was accepted is recorded.
        """
        payload = {
            "jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "grx-validation", "version": "1.0"},
            },
        }
        att = self._post(payload, with_session=False)
        if att.http_status != 200:
            raise McpTransportError(
                f"initialize returned HTTP {att.http_status}. 403 = signature or IAM (check "
                f"that `connection` was popped before signing and that the caller may "
                f"bedrock-agentcore:InvokeGateway); anything else, read the body.",
                http_status=att.http_status, request_id=att.request_id,
                body=json.dumps(att.body))

        sid = ""
        for k, v in att.headers.items():
            if k == SESSION_HEADER.lower():
                sid = v
                break
        if not sid:
            raise McpTransportError(
                "initialize succeeded but returned no Mcp-Session-Id header. Both gateways are "
                "created with protocolConfiguration.mcp.sessionConfiguration set, so sessions "
                "are enabled and every subsequent request needs that header or the gateway "
                "answers 400. A missing header here means the gateway's session configuration "
                "is not what infra/04_gateway.py recorded, which is a finding about the "
                "configuration surface, not a transport hiccup.",
                http_status=att.http_status, request_id=att.request_id,
                body=json.dumps(att.headers))

        self.session_id = sid
        self.session_started_monotonic = time.monotonic()
        result = (att.body or {}).get("result") or {}
        self.protocol_version = str(result.get("protocolVersion", ""))
        self.server_info = result.get("serverInfo") or {}

        # The protocol-required follow-up notification. No id, so no response is expected.
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                       expect_response=False)
        except McpTransportError:
            pass

        return result

    def session_age_s(self) -> float:
        if self.session_started_monotonic is None:
            return float("inf")
        return time.monotonic() - self.session_started_monotonic

    def refresh_if_stale(self, *, fraction: float = 0.7) -> bool:
        """Re-initialize **between** trials if the session is close to its timeout.

        Called by an arm's loop, never from inside `call_tool`. The distinction is the whole
        point: a session that expires mid-arm costs one trial an extra round trip, and F6 reports
        p99 latency — a single 2x observation at n=1000 moves the 99th percentile. Renewing
        proactively at a fraction of the timeout puts that cost between trials, where it is not
        measured, and returns True so the caller can record where it happened.

        `fraction` defaults to 0.7 of the configured 900 s, i.e. ~630 s, which is above the
        slowest single trial by more than two orders of magnitude.
        """
        if not self.session_id:
            return False
        if self.session_age_s() < fraction * self.session_timeout_s:
            return False
        self.session_id = ""
        self.session_started_monotonic = None
        self.initialize()
        self.session_renewals += 1
        return True

    # -- requests ----------------------------------------------------------

    def request(self, method: str, params: dict | None = None, *,
                renew_on_404: bool = True) -> Decision:
        """Send one JSON-RPC request and classify the answer.

        `renew_on_404` handles a session that expired or was never valid for this principal.
        It re-initializes **once** and retries, incrementing `reactive_renewals` — that counter
        is the flag an analysis uses to drop the affected trial rather than to average a
        double-round-trip latency into a percentile. Set it False in any arm where a 404 is
        itself the observation.
        """
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method,
                   "params": params or {}}
        att = self._post(payload)

        if att.http_status == 404 and renew_on_404:
            self.session_id = ""
            self.session_started_monotonic = None
            self.initialize()
            self.reactive_renewals += 1
            payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method,
                       "params": params or {}}
            att = self._post(payload)

        return classify(att.http_status, att.body, request_id=att.request_id,
                        duration_ms=att.duration_ms, session_id=att.session_id)

    def list_tools(self) -> tuple[list[dict], Decision]:
        """`tools/list`. **Visibility here is not authorization.**

        AWS documents listing as a *meta* action: a principal may list a tool "if there exists
        any set of circumstances under which a call to that tool would be permitted". So a tool
        appearing in this list says only that some hypothetical request could be allowed — not
        that the request an arm is about to send will be. An arm that used `tools/list` as its
        oracle would report an allow for a call that gets denied, so the tuple returns the raw
        `Decision` alongside the list and no caller gets the list without it.
        """
        d = self.request("tools/list")
        tools = []
        if d.body and isinstance(d.body.get("result"), dict):
            tools = d.body["result"].get("tools") or []
        return tools, d

    def call_tool(self, name: str, arguments: dict | None = None, *,
                  renew_on_404: bool = True) -> Decision:
        """`tools/call`. `name` is the MCP tool name, i.e. `<TargetName>___<ToolName>`.

        The same string `lib/cedar.action_id()` builds and `infra/echo_handler.py` splits, which
        is why neither this module nor its callers construct it by concatenation.
        """
        return self.request("tools/call", {"name": name, "arguments": arguments or {}},
                            renew_on_404=renew_on_404)

    def prompts_list(self) -> Decision:
        """`prompts/list` — documented as exempt from policy evaluation.

        Present so F4 can measure the exemption instead of citing it. If a `forbid`-everything
        policy also blocked this, the documented statement "policy evaluation applies only to
        MCP tools" would be false, and that is a finding worth an explicit call.
        """
        return self.request("prompts/list")

    def resources_list(self) -> Decision:
        """`resources/list` — the other half of the same exemption claim."""
        return self.request("resources/list")

    def close(self) -> None:
        """Release the pool. The MCP session is left to expire on its own.

        There is a `DELETE` in the streamable-HTTP spec for ending a session, but the gateway's
        behaviour for it is not documented on the pages this project read, and issuing an
        undocumented verb at teardown time could confound a subsequent arm's 404. Sessions expire
        in 900 s; the resources themselves are torn down by tag.
        """
        self._pool.clear()

    def __enter__(self) -> "McpClient":
        self.initialize()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# --------------------------------------------------------------------------
# construction helpers
# --------------------------------------------------------------------------

def client_for(gateway_url: str, factory, *, store: EvidenceStore | None = None,
               policy_session_id: str | None = None,
               session_timeout_s: int = 900, **kw) -> McpClient:
    """Build a client whose credentials come from a `lib/awsclients.ClientFactory`.

    Going through the factory rather than `boto3.Session()` is what makes the Cedar principal
    correct: the factory may hold an assumed `grx-caller` session, and Cedar's principal id is
    `arn:aws:sts::<account>:assumed-role/grx-caller-<runid>`. A client built from ambient user
    credentials would present `timwu` instead, and every `principal ==` arm would default-deny —
    a result that looks exactly like the policy working.

    The credential object is passed through unfrozen. `SigV4Auth` is given frozen credentials at
    signing time via `get_frozen_credentials()`, so a refreshable assumed-role session keeps
    working across an arm longer than its one-hour credential lifetime.
    """
    creds = factory.session().get_credentials()
    if creds is None:
        raise McpTransportError(
            "no credentials available to sign the MCP request; a gateway call cannot be made "
            "anonymously and an unsigned POST returns 403, which reads as an authorization "
            "finding.")
    return McpClient(gateway_url, factory.region, creds, store=store,
                     policy_session_id=policy_session_id,
                     session_timeout_s=session_timeout_s, **kw)


def policy_session_id(run_id: str, arm: str, index: int = 0) -> str:
    """A deterministic client-generated id for the temporal-policy header.

    Deterministic, and derived from the arm rather than random, for the reason
    `feedback_checkpoint_resume` gives: a resumed run must present the *same* id, or a temporal
    policy sees a fresh session and the trials before and after the interruption are not
    comparable.

    The value is normalized to `POLICY_SESSION_GRAMMAR`, which was MEASURED, not assumed — see
    that constant. The previous implementation used `urllib.parse.quote(raw, safe="-_.")`, which
    leaves `_` and `.` unquoted and percent-encodes everything else; both of those choices were
    wrong in the same direction. `_` and `.` are rejected by the gateway, and percent-encoding
    does not rescue a rejected character (`%5F` is rejected too — the value is not
    percent-decoded before validation, and `%` is itself illegal).

    A disambiguating hash is appended when, and only when, normalization or truncation actually
    changed the string. Mapping `_ . :` all to `-` is not injective on its own — `a_b` and `a-b`
    would become the same session id, which would silently merge the temporal state of two arms
    into one and make them non-comparable while every request still returned 200. Suffixing only
    the ids that were altered keeps the unaltered ones byte-identical to what is already recorded
    in `evidence/`, so this fix does not invalidate earlier records.
    """
    raw = f"{run_id}-{arm}-{index}"
    return normalize_policy_session_id(raw)


if __name__ == "__main__":
    # Offline self-check: the classifier, against the response shapes AWS documents. No network,
    # no credentials, so this runs anywhere and is the thing to read first when a phase reports
    # an outcome that looks wrong.
    doc_deny = {
        "jsonrpc": "2.0", "id": 2,
        "result": {"content": [{"type": "text", "text":
            "AuthorizeActionException - Tool Execution Denied: Tool call not allowed due to "
            "policy enforcement [No policy applies to the request (denied by default).]"}],
            "isError": True},
    }
    cases = {
        "documented default-deny (HTTP 200!)": (200, doc_deny),
        "successful tool call": (200, {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": '{"tool":"echo","text":"hi"}'}],
            "isError": False}}),
        "our handler's bad_request": (200, {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": '{"error":"bad_request"}'}],
            "isError": True}}),
        "missing session header": (400, {"message": "Bad Request"}),
        "expired/foreign session": (404, {"message": "Not Found"}),
        "jsonrpc error": (200, {"jsonrpc": "2.0", "id": 1,
                                "error": {"code": -32601, "message": "Method not found"}}),
        "unrecognised isError text": (200, {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": "something nobody has seen"}],
            "isError": True}}),
    }
    print(f"{'case':38s} {'outcome':14s} {'flags'}")
    for label, (status, body) in cases.items():
        d = classify(status, body)
        flags = []
        if d.default_deny:
            flags.append("default_deny")
        if d.authorize_exception:
            flags.append("authorize_exception")
        if d.unclassified:
            flags.append("UNCLASSIFIED")
        print(f"{label:38s} {d.outcome:14s} {','.join(flags) or '-'}")
    print(f"\nsigning service   {SIGNING_SERVICE}")
    print(f"protocol version  {PROTOCOL_VERSION}")
    print(f"session header    {SESSION_HEADER} (response; gateway-generated)")
    print(f"policy header     {POLICY_SESSION_HEADER} (request; CLIENT-generated)")
    print(f"unevaluated       {', '.join(UNEVALUATED_METHODS)}")
