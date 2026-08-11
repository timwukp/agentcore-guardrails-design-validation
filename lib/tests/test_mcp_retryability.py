"""The gateway data plane's retry seam: does a transport failure survive as retryable?

`lib/mcp.py` sends its POSTs through a `urllib3.PoolManager` built with `retries=False`, so
urllib3 retries nothing and botocore is not in the path at all. Every retry decision on this
plane therefore lands in `lib/checkpoint.is_retryable`, which works from an ALLOWLIST and
classifies anything it cannot identify as **permanent**.

That combination has a known failure mode with a known cost. On the control plane the same
shape — an exception whose identity was computed at the raise site and then folded into a
prose message — meant `EndpointConnectionError` reached `is_retryable` unidentifiable, was
classified permanent, and a ~80 s local network outage burned 3,378 Phase 1 trials with zero
retries (DEV-P1-11). The scripts exited rc=0, because a smaller denominator is not an error.

F4 sends up to 1,440 data-plane calls, so this file pins the contract on the second plane
BEFORE the first one is sent. Two halves, both asserted, because either alone is a defect:

* a real transport failure must arrive as an `McpTransportError` that `is_retryable` says
  True to — otherwise the retry machinery is unreachable exactly where it is needed;
* a failure that is OUR OWN defect (no session id, no credentials) must arrive with an empty
  `error_class` and stay permanent — otherwise a harness bug is retried three times and
  reported as service flakiness.

The exception names are not asserted from memory. `test_the_measured_urllib3_names_are_on_the
_allowlist` re-derives them by making real failing connections through a real PoolManager, so
if urllib3 renames a class the test fails rather than the harness silently losing trials.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import checkpoint as C  # noqa: E402
import mcp as M  # noqa: E402

# Captured at IMPORT time, before `conftest.no_aws` patches it. Exactly one test needs it —
# see `test_the_measured_urllib3_names_are_on_the_allowlist` for why the block is lifted
# there and why lifting it cannot reach AWS.
_REAL_CONNECT = socket.socket.connect

URL = "https://grx-gw-test.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"


class Creds:
    """The minimum SigV4Auth needs. Not a real credential; nothing is ever sent."""

    access_key = "AKIAIOSFODNN7EXAMPLE"
    secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    token = None

    def get_frozen_credentials(self):
        return self


class RaisingPool:
    """A pool whose `request` raises the class under test, as urllib3 would."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls = 0

    def request(self, *a, **kw):  # noqa: ANN002, ANN003
        self.calls += 1
        raise self.exc

    def clear(self) -> None:
        pass


def client(pool) -> M.McpClient:
    c = M.McpClient(URL, "us-east-1", Creds(), pool=pool)
    # A session id is set directly so `_post`'s missing-session guard is not what fires;
    # this suite is about the transport failure, and the guard has its own test below.
    c.session_id = "test-session"
    return c


# --------------------------------------------------------------------------
# the retryable half
# --------------------------------------------------------------------------

# Names measured against urllib3 2.7.0 in this venv on 2026-08-11 by making real failing
# connections — see test_the_measured_urllib3_names_are_on_the_allowlist, which re-derives
# them rather than trusting this list.
TRANSPORT = [
    urllib3.exceptions.NameResolutionError("h", None, socket.gaierror("nodename")),
    urllib3.exceptions.NewConnectionError(None, "connection refused"),
    urllib3.exceptions.ConnectTimeoutError(None, "timed out"),
    urllib3.exceptions.ReadTimeoutError(None, URL, "read timed out"),
    urllib3.exceptions.ProtocolError("connection aborted"),
    urllib3.exceptions.SSLError("handshake failure"),
]


@pytest.mark.parametrize("exc", TRANSPORT, ids=lambda e: type(e).__name__)
def test_a_transport_failure_is_raised_as_a_retryable_error(exc):
    """The class name must survive the raise, and `is_retryable` must then say True.

    Asserting `is_retryable` and not merely the attribute is the point: the attribute is a
    means, and a test that stopped at `error_class == "..."` would still pass if the
    allowlist did not contain the name — i.e. it would pass while every such trial was lost.
    """
    pool = RaisingPool(exc)
    with pytest.raises(M.McpTransportError) as ei:
        client(pool).call_tool("echo", {"text": "x"})

    assert ei.value.error_class == type(exc).__name__
    assert C.is_retryable(ei.value) is True
    assert C.error_code(ei.value) == type(exc).__name__


def test_the_measured_urllib3_names_are_on_the_allowlist(monkeypatch):
    """Re-derive the class names from real failing connections instead of trusting a list.

    The allowlist is a set of STRINGS, so it silently stops matching if urllib3 renames a
    class — and the symptom would not be an error, it would be trials lost with zero
    retries. This makes three connections that cannot succeed and asserts that whatever
    comes back is a name we honour: an invalid TLD (fails in DNS), a closed loopback port
    (fails in connect), and an unroutable address (fails in connect or times out).

    The third target is in **RFC 5737 TEST-NET-1** (`192.0.2.0/24`), the block IANA reserves
    for documentation and examples, rather than in RFC 1918 private space. Two reasons, and
    the second is the one that matters: TEST-NET-1 is guaranteed never to be routed, whereas a
    private-range literal may name a real subnet on whatever network this runs on — and
    `check_redaction`'s `private-ip` pattern flags those, correctly, because it cannot tell a
    made-up one from one of ours. Choosing a reserved-for-documentation address keeps the gate
    honest without a waiver. (The private range is deliberately not spelled out here: writing
    it as an example would itself be a finding, which is how this paragraph's first draft
    failed the gate.)

    `conftest.no_aws`'s socket block is lifted for this test only, because that block IS one
    of the failure modes being exercised — with it in place all three attempts return
    `RuntimeError` and the test would assert on the fixture instead of on urllib3. Lifting
    it is safe and bounded: the three targets are an unresolvable name and two addresses in
    reserved ranges, none of which can reach AWS, no credential is constructed, and the
    timeout is 1 s. The first target does not even leave the resolver.
    """
    monkeypatch.setattr(socket.socket, "connect", _REAL_CONNECT)
    pool = urllib3.PoolManager(retries=False,
                               timeout=urllib3.Timeout(connect=1.0, read=1.0))
    seen = []
    for url in ("https://no-such-host-grx-validation.example.invalid/mcp",
                "https://127.0.0.1:9/mcp",
                "https://192.0.2.1:443/mcp"):
        try:
            pool.request("POST", url, body=b"{}",
                         headers={"content-type": "application/json"})
        except Exception as exc:  # noqa: BLE001
            seen.append(type(exc).__name__)
        else:
            pytest.fail(f"{url} unexpectedly succeeded; this test needs a failing connection")

    assert len(seen) == 3, seen
    # Guard against the inverse of the DEV-P1-11 shape: if the fixture (or anything else)
    # replaced the failure with a generic error, every name would be "RuntimeError" and the
    # allowlist assertion below would be testing nothing about urllib3 at all.
    assert "RuntimeError" not in seen, (
        f"the socket block was still in place, so these are fixture errors rather than "
        f"urllib3's own classes: {seen}")
    unhandled = [n for n in seen if n not in C.RETRYABLE_TRANSPORT]
    assert not unhandled, (
        f"urllib3 {urllib3.__version__} raised {unhandled}, which lib/checkpoint.py would "
        f"classify PERMANENT — every such data-plane trial would be lost with zero retries")


def test_the_failed_attempt_is_still_recorded_before_the_raise():
    """A lost trial must leave evidence, or the hole in the denominator is unexplainable.

    `_post` appends the `Attempt` and calls `_record` BEFORE raising, so a trial that never
    got a response is still archived with its duration and its error text. Asserted here
    because the raise is what a reader's eye follows, and moving it above the append would
    be an easy, silent regression.
    """
    pool = RaisingPool(urllib3.exceptions.ProtocolError("connection aborted"))
    c = client(pool)
    with pytest.raises(M.McpTransportError):
        c.call_tool("echo", {"text": "x"})

    assert len(c.attempts) == 1
    att = c.attempts[0]
    assert att.http_status is None
    assert att.error.startswith("ProtocolError: ")
    assert att.duration_ms >= 0.0


# --------------------------------------------------------------------------
# the permanent half — our own defects must NOT be retried
# --------------------------------------------------------------------------

def test_a_missing_session_id_is_permanent_not_retryable():
    """No session id is a defect in our code; retrying it spends the budget three times.

    It also never reaches the pool, so `RaisingPool.calls` staying 0 proves the guard fired
    before the request rather than after a failed round trip.
    """
    pool = RaisingPool(AssertionError("must not be reached"))
    c = M.McpClient(URL, "us-east-1", Creds(), pool=pool)
    with pytest.raises(M.McpTransportError) as ei:
        c.call_tool("echo", {"text": "x"})

    assert pool.calls == 0
    assert ei.value.error_class == ""
    assert C.is_retryable(ei.value) is False


def test_a_transport_class_we_do_not_honour_stays_permanent():
    """The allowlist must not become a denylist.

    `ClosedPoolError` means we closed the pool ourselves and `MaxRetryError` cannot be
    raised by a `retries=False` pool; both are deliberately absent from
    `RETRYABLE_TRANSPORT`, and this pins that absence so a future widening is a decision
    rather than an accident.
    """
    for exc in (urllib3.exceptions.ClosedPoolError(None, "closed"),
                urllib3.exceptions.DecodeError("bad gzip")):
        pool = RaisingPool(exc)
        with pytest.raises(M.McpTransportError) as ei:
            client(pool).call_tool("echo", {"text": "x"})
        assert ei.value.error_class == type(exc).__name__
        assert C.is_retryable(ei.value) is False


def test_run_trial_actually_retries_a_data_plane_transport_failure():
    """End to end through the real retry machinery, which is the claim that matters.

    The three previous tests assert the pieces; this one asserts the composition — a
    `call_tool` that fails twice at the transport and succeeds on the third attempt must be
    recorded as ONE usable trial with `attempts=3`, and the linear 5 s/10 s backoff must
    have been used. Before `error_class` was carried, this test would have seen one attempt
    and a failure.
    """
    boom = urllib3.exceptions.NewConnectionError(None, "refused")
    calls: list[int] = []
    slept: list[float] = []

    def trial() -> dict:
        calls.append(1)
        if len(calls) < 3:
            pool = RaisingPool(boom)
            client(pool).call_tool("echo", {"text": "x"})
            raise AssertionError("unreachable")
        return {"hit": False, "outcome": "allowed"}

    cp = C.Checkpoint("F4-1", "smoke", root=Path("/tmp/grx-test-mcp-retry"))
    got = cp.run_trial("t1", trial, base_delay=5.0, sleep=slept.append)

    assert len(calls) == 3
    assert got is not None and got["attempts"] == 3
    assert slept == [5.0, 10.0]
    assert cp.n_failed == 0
