#!/usr/bin/env python3
"""Evidence capture: every AWS call recorded with the identifiers AWS Support reads.

Why this exists
---------------
The in-house harnesses this project reuses (``claude-code-enterprise-bedrock``,
``agentcore-tsso-poc``) normalize responses for readability and drop
``ResponseMetadata`` in the process. That discards ``x-amzn-requestid`` — the one
field that lets a reader take a claim of ours to AWS Support and have it looked
up. A claim backed by a request ID is a different class of evidence from a claim
backed by a transcript, so capture happens **before** normalization, not after.

What is recorded, for every call, success or failure
---------------------------------------------------
Request parameters, HTTP status, every response header (``x-amzn-requestid`` and
``x-amzn-trace-id`` hoisted to the top level), wall-clock ``t0``/``t1`` from
``time.perf_counter_ns`` plus a wall timestamp, region, botocore version, the
pre-registration sha256 in force, and — on failure — the error code, message and
the full ``ClientError`` metadata. An exception is evidence: a test whose oracle
is ``AccessDenied`` (F5-1, F5-2, F5-3b) has its *entire* result in the error path,
so an exception that is not captured is a test that was not run.

Two design points worth stating because they are easy to get wrong
------------------------------------------------------------------
1. **The prereg hash is read at capture time, not imported as a constant.** If the
   pre-registration is re-sealed mid-project, evidence captured before and after
   must say so on its own face. A constant frozen at import would silently label
   old evidence with a new hash.
2. **Latency is measured around the botocore call only.** ``perf_counter_ns`` is
   monotonic (``time.time()`` can step backwards under NTP correction, which would
   produce negative durations in a latency corpus). This number includes client-side
   serialization and any botocore-internal retries; it is therefore *not*
   interchangeable with the service-side ``GuardrailLatency`` metric, and F6's
   additivity test depends on not confusing the two. ``retry_attempts`` is recorded
   so a call that retried can be identified rather than silently inflating a p99.

Usage
-----
    from lib.evidence import EvidenceStore, capture

    store = EvidenceStore(run_id="r20260809a", family="f5", case_id="F5-7a")
    ec2 = boto3.client("ec2", region_name="us-east-1")
    rec = capture(store, "describe_vpc_endpoint_services", ec2,
                  Filters=[{"Name": "service-name", "Values": ["com.amazonaws.*"]}])
    rec.raise_for_status()      # opt in to raising; by default errors are DATA
    payload = rec.response
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import botocore
from botocore.client import BaseClient
from botocore.exceptions import ClientError, BotoCoreError

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = ROOT / "evidence"
PREREG_HASH_FILE = ROOT / "PREREGISTRATION.sha256"

# Header names are lower-cased by botocore, but a mixed-case variant has been seen
# from some endpoints. Look for both rather than assuming.
_REQID_KEYS = ("x-amzn-requestid", "x-amzn-RequestId", "x-amz-request-id")
_TRACE_KEYS = ("x-amzn-trace-id", "X-Amzn-Trace-Id")


def prereg_hash() -> str:
    """The sha256 currently sealing the pre-registration, read at call time.

    Returns the literal string ``"UNSEALED"`` rather than raising if the file is
    missing: evidence captured without a seal must be *labelled* as such, not
    lost. A missing seal is a finding about the run, and swallowing it into an
    exception would mean the run produced no record at all.
    """
    try:
        return PREREG_HASH_FILE.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        return "UNSEALED"


def _first(d: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        if k in d:
            return str(d[k])
        for actual, v in d.items():          # case-insensitive fallback
            if actual.lower() == k.lower():
                return str(v)
    return ""


def _jsonable(obj: Any) -> Any:
    """Make a botocore response JSON-serializable without losing information.

    ``datetime`` becomes an ISO-8601 string and ``bytes`` becomes a marked
    latin-1 round-trip rather than being dropped. Anything else unknown is
    stringified with its type name attached, so an unserializable field shows up
    in the evidence as an identifiable object instead of vanishing.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return {"__bytes_latin1__": bytes(obj).decode("latin-1")}
    if isinstance(obj, set):
        return sorted(obj)
    return f"<{type(obj).__name__}:{obj!r}>"


class EvidenceProvenanceError(RuntimeError):
    """Raised when a call that did not reach AWS would be filed as if it had.

    Separate from `CapturedCallError`, which reports what the *service* said. This one
    reports that there was no service: the record would be a fabrication sitting in the
    tree the replication gate counts days from. It is deliberately NOT catchable by the
    `except RuntimeError` retry paths' intent — a harness pointed at the wrong root should
    stop, not retry against the same wrong root — but it subclasses RuntimeError so no
    existing handler is bypassed silently.
    """


class CapturedCallError(RuntimeError):
    """Raised by `Record.raise_for_status`, carrying the AWS error code.

    A plain `RuntimeError` was the original, and it broke the retry path silently.
    `capture()` swallows the `ClientError` by design — an error is *data* here, because
    half this project's oracles are `AccessDenied` — so by the time `raise_for_status`
    runs, the only remaining evidence of *what* failed is the fields on the Record.
    Raising a bare RuntimeError discarded them, with two consequences that both looked
    like results rather than defects:

    * `lib/checkpoint.is_retryable` classifies an unrecognised exception as **permanent**
      (deliberately: an allowlist, so a harness bug does not read as service flakiness).
      A ThrottlingException arriving as RuntimeError therefore got **zero** retries, and
      the entire backoff mechanism was dead on the only path that uses it. A run that
      lost 40 items to throttling would report 40 failures and a smaller denominator —
      arithmetically honest, and a needless loss of exactly the data the arm was for.
    * The checkpoint recorded `error_code="RuntimeError"` for every failure, so
      `tally()`'s `failure_codes` — the field that says *why* an arm has holes — read
      "RuntimeError" whatever happened. Throttling, an expired token and a malformed
      request were one indistinguishable bucket.

    Subclassing RuntimeError keeps every existing `except RuntimeError` working, so this
    widens what callers can see without narrowing what they already caught.
    """

    def __init__(self, message: str, *, error_code: str = "", error_class: str = "",
                 request_id: str = "", http_status: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_class = error_class
        self.request_id = request_id
        self.http_status = http_status


_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def safe_component(text: str) -> str:
    """Make ``text`` usable as ONE filename component, without losing information.

    `Record.operation` is a boto3 method name for a control-plane call (`create_gateway`,
    already safe) but the **JSON-RPC method** for an MCP call — and every MCP method except
    `initialize` contains a `/`: `tools/call`, `tools/list`, `prompts/list`,
    `notifications/initialized`. Interpolated into a path, `/` is a directory separator, so
    `0002_mcp:notifications/initialized_ok.json` asked to write into a `mcp:notifications`
    directory that does not exist and raised `FileNotFoundError` from inside the evidence
    writer. That is the worst place for it: the call to AWS had already succeeded and been
    billed, and the archive of it is what failed.

    Only `initialize` survived, which is why nothing caught this earlier — the handshake is
    the one method with no `/` in its name, so `08_smoke.py` wrote record 0001 and died on
    0002. A single passing case that is passing for a reason that does not generalise
    (`feedback_vacuous_test_check`).

    The substitution is total rather than targeted: anything outside `[A-Za-z0-9._-]` becomes
    `-`. Replacing only `/` would leave the same latent break for the next operation label
    with a `:`, a space or a `*` in it — and the set of things that can appear here is not
    ours to enumerate, since it comes from whatever protocol a future family speaks. The
    unabbreviated operation stays in the record body under `operation`, so the filename is a
    convenience and the evidence is unaffected; an analysis reads the field, not the name.
    """
    cleaned = _UNSAFE_IN_FILENAME.sub("-", text).strip("-.")
    return cleaned or "unnamed"


@dataclass
class Record:
    """One AWS API call. Every field is an observation; nothing here is a verdict."""

    case_id: str
    operation: str
    service: str
    region: str
    params: dict
    ok: bool
    http_status: int | None = None
    request_id: str = ""
    trace_id: str = ""
    retry_attempts: int | None = None
    headers: dict = field(default_factory=dict)
    response: dict | None = None
    error_code: str = ""
    error_message: str = ""
    error_class: str = ""
    error_metadata: dict = field(default_factory=dict)
    duration_ms: float = 0.0
    t_start_utc: str = ""
    t_end_utc: str = ""
    sdk_version: str = ""
    prereg_sha256: str = ""
    path: str = ""

    def raise_for_status(self) -> "Record":
        """Opt in to exception semantics.

        The default is that an error is *data*: half this project's oracles are
        ``AccessDenied``, and a wrapper that raised by default would make the
        expected result of a red-team case indistinguishable from a harness bug.
        Callers whose oracle is success call this explicitly.

        Raises `CapturedCallError` (a RuntimeError subclass) carrying the AWS error code,
        so `lib/checkpoint.is_retryable` can still see that a ThrottlingException is
        transient after `capture()` has absorbed the original `ClientError`.
        """
        if not self.ok:
            raise CapturedCallError(
                f"{self.case_id}: {self.operation} failed with "
                f"{self.error_code or self.error_class}: {self.error_message} "
                f"(request id {self.request_id or 'none'})",
                error_code=self.error_code, error_class=self.error_class,
                request_id=self.request_id, http_status=self.http_status)
        return self


_SEQ_RE = re.compile(r"^(\d{4,})_")


def _highest_seq(d: Path) -> int:
    """Highest ``NNNN_`` prefix already in `d`, or 0 if none.

    Reads the filenames rather than a counter file: the filenames ARE the ledger, so a
    counter that disagreed with them would be a second source of truth for the same fact.
    Width is ``\\d{4,}`` rather than exactly 4 so a case that ever exceeds 9999 calls keeps
    ordering correctly instead of wrapping into an existing name.
    """
    top = 0
    for p in d.glob("*.json"):
        m = _SEQ_RE.match(p.name)
        if m:
            top = max(top, int(m.group(1)))
    return top


class EvidenceStore:
    """Writes one JSON file per call under ``evidence/<run_id>/<family>/<case_id>/``.

    Files are named ``<seq>_<operation>_<ok|err>.json`` with a zero-padded
    sequence, so the directory listing preserves call order without depending on
    filesystem mtime granularity — two calls inside the same millisecond are
    common at 100 rps and mtime would not separate them.

    ``<operation>`` in the *name* is passed through :func:`safe_component`, because an MCP
    method (``tools/call``) contains a path separator. The name is therefore lossy by design;
    the exact operation is always in the record's ``operation`` field.

    THE SEQUENCE RESUMES; IT DOES NOT RESTART
    -----------------------------------------
    ``_seq`` starts above the highest sequence already on disk rather than at 0. Without
    that, the second run of a case into the same run id rewrites ``0001_*.json`` onward and
    **deletes the first run's records**. That is not a hypothetical: the ``>=2 separate
    calendar days`` replication rule is discharged by re-running a case on a later day, and
    every gateway-side case adopts the *ledger's* run id (one testbed, one ledger — see
    ``testbed.State.load_or_new``), so a replication necessarily lands in the directory the
    first observation is stored in. `check_amendment_readiness.py` derives its day count
    from ``t_start_utc`` across those very files, so the clobber would remove day 1 and the
    replication would read as a *single* day — the run that was supposed to earn the
    amendment silently revoking it instead.

    Resuming means one directory can hold several observations of one case. That is correct:
    the day-count is derived per record, so N days of records in one directory count as N.
    ``summary.json`` and ``analysis.json`` are single-slot and ARE overwritten by design —
    they are indexes of the latest run, not evidence — which is why
    ``check_amendment_readiness.py`` and ``07a_compare_runs.py`` both skip them when
    collecting dates.
    """

    def __init__(self, run_id: str, family: str, case_id: str,
                 root: Path | None = None) -> None:
        self.run_id = run_id
        self.family = family
        self.case_id = case_id
        self.dir = (root or EVIDENCE_ROOT) / run_id / family / case_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._seq = _highest_seq(self.dir)
        self.records: list[Record] = []

    def _rel(self, p: Path) -> str:
        """Project-relative path where possible, absolute otherwise.

        ``relative_to`` raises when the store is rooted outside the project — which
        happens under pytest's ``tmp_path`` and would happen for any operator who
        redirected the evidence root to another volume. A recorded path that throws
        is worse than an absolute one, so the fallback is the absolute path rather
        than an exception.
        """
        try:
            return str(p.relative_to(ROOT))
        except ValueError:
            return str(p)

    def environment(self) -> dict:
        """Run context that a reproduction attempt needs and cannot recover later.

        No account ID, no ARNs, no caller identity: this file is written into a
        tree that gets published, and the redaction gate treats a 12-digit number
        as a finding. Identity belongs in the local-only run log, not here.
        """
        return {
            "run_id": self.run_id,
            "family": self.family,
            "case_id": self.case_id,
            "prereg_sha256": prereg_hash(),
            "sdk_version": botocore.__version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "hostname_sha": "",           # deliberately empty; see docstring
            "captured_utc": datetime.now(timezone.utc).isoformat(),
        }

    def write_environment(self) -> Path:
        p = self.dir / "environment.json"
        p.write_text(json.dumps(self.environment(), indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
        return p

    def add(self, rec: Record) -> Record:
        self._seq += 1
        name = f"{self._seq:04d}_{safe_component(rec.operation)}_{'ok' if rec.ok else 'err'}.json"
        p = self.dir / name
        rec.path = self._rel(p)
        p.write_text(json.dumps(asdict(rec), indent=2, sort_keys=True,
                                default=_jsonable, ensure_ascii=False) + "\n",
                     encoding="utf-8")
        self.records.append(rec)
        return rec

    def write_summary(self, extra: dict | None = None) -> Path:
        """An index of the calls, so a reader does not have to open all of them."""
        p = self.dir / "summary.json"
        body = {
            **self.environment(),
            "n_calls": len(self.records),
            "n_ok": sum(1 for r in self.records if r.ok),
            "n_err": sum(1 for r in self.records if not r.ok),
            "calls": [
                {"seq": i + 1, "operation": r.operation, "region": r.region,
                 "ok": r.ok, "http_status": r.http_status,
                 "request_id": r.request_id, "error_code": r.error_code,
                 "duration_ms": r.duration_ms, "file": Path(r.path).name}
                for i, r in enumerate(self.records)
            ],
            **(extra or {}),
        }
        p.write_text(json.dumps(body, indent=2, sort_keys=True,
                                default=_jsonable, ensure_ascii=False) + "\n",
                     encoding="utf-8")
        return p


def _drain_streams(response: dict) -> None:
    """Replace any streaming payload in `response` with the text it carries, in place.

    `InvokeModel` returns its payload as a `StreamingBody`, which is a file object over the
    socket. Two consequences, and the second is why this function exists rather than a
    `default=` hook on the serialiser:

    1. It is not serialisable. Before this, `capture(store, "invoke_model", ...)` died with
       `TypeError: cannot pickle 'BufferedReader' instances` at `store.add`, AFTER the call had
       been billed and its request id received. So the evidence tree could not record an
       `InvokeModel` call at all, and every case needing that transport was unreachable
       (feedback_no_deploy_path_no_component). Found by F5-6's `--probe`, on four calls.

    2. Reading it is DESTRUCTIVE and one-shot. That rules out serialising a copy and leaving
       the original for the caller: whoever reads second gets an empty string, silently, and an
       empty body parses to `{}` — which for F5-6 would have read as "no assessment present",
       i.e. a failed trial, for reasons entirely internal to this file.

    So the stream is drained exactly once, here, at the single point every record passes
    through, and the text is put back where the payload was. Callers read the body off
    `rec.response`, never off their own handle — there is no other handle, and a caller that
    somehow kept one gets the empty read rather than a duplicate charge.

    Decoded as UTF-8 with `errors="replace"` rather than left as bytes: the record is written
    as JSON, and a body that cannot be decoded must still produce a readable record of a call
    that really happened. Non-text payloads are left as a length marker instead of mangled.
    """
    for key, val in list(response.items()):
        if not hasattr(val, "read"):
            continue
        raw = val.read()
        if isinstance(raw, (bytes, bytearray)):
            try:
                response[key] = raw.decode("utf-8")
            except UnicodeDecodeError:
                response[key] = f"<{len(raw)} bytes, not utf-8>"
        else:
            response[key] = raw


def capture(store: EvidenceStore, operation: str, client, **params) -> Record:
    """Call ``client.<operation>(**params)``, recording everything either way.

    ``operation`` is the snake_case boto3 method name. The service label is taken
    from the client's own service model so it cannot drift from the client that
    was actually used.

    A SYNTHETIC CLIENT MAY NOT WRITE INTO THE PUBLISHED EVIDENCE TREE
    -----------------------------------------------------------------
    On 2026-08-10 the offline mutation harness for F1-3 ran ``main()`` end-to-end against a
    fake ``bedrock-agentcore-control``. It patched the analysis writer, so no fake *verdict*
    was published — but it did not redirect the evidence root, and 221 fabricated call
    records (request ids ``rq-dflt``, HTTP 200, invented statuses) landed in
    ``evidence/<ledger run id>/f1/F1-3/`` beside the 22 real ones.

    That is worse than a stray file. `check_amendment_readiness.py` derives the
    ">=2 separate calendar days" replication count from ``t_start_utc`` across *every*
    record in the run directory, so fabricated calls were one calendar day away from
    counting as an observation that earns a document amendment. The pytest write guard in
    the root ``conftest.py`` could not catch it: this harness is a plain ``python3`` script,
    not a test.

    So the refusal lives here, at the only point every record passes through: a client that
    is not a botocore client is refused unless the store is explicitly rooted outside
    ``evidence/``. Offline harnesses pass ``root=`` (a tmp dir) and are unaffected; what is
    blocked is the specific mistake of forgetting to.

    **The test is ``isinstance(client, BaseClient)``, not the type of ``client.meta``.** The
    first version of this guard checked the meta — and it would NOT have caught the incident
    it was written for. That fake assigns ``self.meta = REAL_AC.meta`` deliberately, so
    ``testbed.check_name`` reads name patterns out of the genuine service model; a borrowed
    meta *is* a real ``ClientMeta``. What cannot be borrowed is being an instance of
    botocore's client class, since only ``ClientCreator`` produces one. A guard whose
    discriminator the known offender passes is not a guard.
    """
    meta = client.meta
    service = meta.service_model.service_name
    region = meta.region_name
    if not isinstance(client, BaseClient) and store.dir.is_relative_to(EVIDENCE_ROOT):
        # `_rel`, not `relative_to`: the latter raises when the store is rooted outside the
        # project, which is exactly the case a monkeypatched EVIDENCE_ROOT produces — the
        # guard would then die formatting its own error message instead of reporting it.
        raise EvidenceProvenanceError(
            f"refusing to write a synthetic {operation!r} record into the published "
            f"evidence tree ({store._rel(store.dir)}). {type(client).__name__} is not a "
            f"botocore BaseClient, so its responses never crossed the network and its "
            f"request ids are invented. Fabricated records in a run directory are counted by "
            f"check_amendment_readiness.py when it derives replication days from "
            f"t_start_utc — they could earn a document amendment. Pass "
            f"EvidenceStore(..., root=<tmp dir>) in offline harnesses")

    t0_wall = datetime.now(timezone.utc)
    t0 = time.perf_counter_ns()
    resp: dict | None = None
    err: BaseException | None = None
    try:
        resp = getattr(client, operation)(**params)
    except (ClientError, BotoCoreError) as exc:
        err = exc
    t1 = time.perf_counter_ns()
    t1_wall = datetime.now(timezone.utc)

    rec = Record(
        case_id=store.case_id, operation=operation, service=service, region=region,
        params=json.loads(json.dumps(params, default=_jsonable)),
        ok=err is None,
        duration_ms=(t1 - t0) / 1e6,
        t_start_utc=t0_wall.isoformat(), t_end_utc=t1_wall.isoformat(),
        sdk_version=botocore.__version__, prereg_sha256=prereg_hash(),
    )

    # Both branches read ResponseMetadata: a ClientError carries the same
    # request id as a success, and for the AccessDenied oracles that id IS the
    # evidence.
    rmeta: dict = {}
    if resp is not None:
        rmeta = resp.get("ResponseMetadata", {}) or {}
        rec.response = {k: v for k, v in resp.items() if k != "ResponseMetadata"}
        _drain_streams(rec.response)
    elif isinstance(err, ClientError):
        rmeta = (err.response or {}).get("ResponseMetadata", {}) or {}
        rec.error_code = (err.response or {}).get("Error", {}).get("Code", "")
        rec.error_message = (err.response or {}).get("Error", {}).get("Message", "")
        rec.error_metadata = json.loads(json.dumps(
            {k: v for k, v in (err.response or {}).items() if k != "ResponseMetadata"},
            default=_jsonable))
    if err is not None:
        rec.error_class = type(err).__name__
        if not rec.error_message:
            rec.error_message = str(err)

    headers = {k.lower(): v for k, v in (rmeta.get("HTTPHeaders") or {}).items()}
    rec.headers = headers
    rec.http_status = rmeta.get("HTTPStatusCode")
    rec.request_id = rmeta.get("RequestId") or _first(headers, _REQID_KEYS)
    rec.trace_id = _first(headers, _TRACE_KEYS)
    rec.retry_attempts = rmeta.get("RetryAttempts")

    return store.add(rec)


RUN_ID_RE = re.compile(r"^r(\d{4})(\d{2})(\d{2})T\d{2}\d{2}?\d{0,2}Z?$")


def new_run_id(stamp: str | None = None, *, now: datetime | None = None) -> str:
    """A run id derived from an explicit stamp, or from the wall clock.

    ``stamp`` is accepted so callers under test can pin it. Format ``rYYYYMMDDTHHMMSSZ``.

    A stamp whose **date** disagrees with today's UTC date is rejected. This is not
    tidiness. It happened: ``r20260810T0930Z`` was minted for the F5-7a replication
    because the local calendar had rolled to the 10th while UTC was still
    2026-08-09T16:20 — so a same-day repeat carried a run id asserting a second day.
    The mislabelling was caught downstream, by ``07a_compare_runs.py`` reading
    ``t_start_utc`` out of the records, and that is the right place for the *authoritative*
    check: a run id is a label and evidence timestamps are data.

    But a mislabelled directory is a trap for every later reader, and the gates
    deliberately do not trust run ids, which means nothing downstream would ever
    *correct* the name. The cheapest fix is to refuse to create it. Local midnight is
    not UTC midnight for most of the world, and the replication rule counts UTC days
    because that is what the records carry.
    """
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y%m%d")
    if stamp:
        m = RUN_ID_RE.match(stamp)
        if not m:
            raise ValueError(
                f"run id {stamp!r} is not of the form rYYYYMMDDTHHMMSSZ; an unparseable "
                f"run id cannot be checked against the clock, and the replication rule "
                f"counts calendar days")
        if "".join(m.groups()) != today:
            raise ValueError(
                f"run id {stamp!r} names date {'-'.join(m.groups())} but the current UTC "
                f"date is {now.strftime('%Y-%m-%d')}. Local midnight is not UTC midnight, "
                f"and evidence records are stamped in UTC — a run id naming tomorrow "
                f"would label a same-day repeat as a replication")
        return stamp
    return "r" + now.strftime("%Y%m%dT%H%M%SZ")
