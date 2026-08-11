"""Per-trial checkpoint/resume with retries that cannot become data.

Why this is not the checkpoint helper it is derived from
-------------------------------------------------------
The pattern comes from `kaggle-measuring-agi/test_bedrock_200seeds.py`, which proved
itself over a multi-hour overnight run (`feedback_checkpoint_resume`): a per-trial JSON
keyed by trial id, saved after **every** trial, with 3 retries and `sleep(delay * attempt)`
backoff. Two of its behaviours are wrong *for this project*, and both would corrupt
published numbers rather than merely inconvenience a rerun.

**1. A failed trial must not be a data point.** That harness records a trial that failed
all 3 attempts as `{"p1": 0, "p3": 0, "p4": 0, "error": ...}` — sensible there, because a
missing answer *is* a wrong answer in a benchmark. Here it would be a fabricated
observation: a `ThrottlingException` recorded as `blocked=False` enters an F3 recall
denominator as a guardrail that failed to detect an attack. So `record()` refuses a result
for a trial that did not complete; failures are stored in a **separate** `failed` map and
`results()` never returns them. `n_attempted` and `n_usable` are both reported, because a
cell whose n shrank silently is the `feedback_zero_file_scan_is_error` failure applied to
trials.

**2. A checkpoint write must be atomic.** `json.dump(open(path, "w"))` truncates the file
before writing it, so a kill (or a full disk) during the write of trial 900 destroys trials
1–899. The plan's Phase-4 gate is *"checkpoint/resume verified by killing and resuming a
run"*, and that gate would have been passing against a file that a kill could erase. Writes
go to a temp file in the same directory, are `fsync`'d, and are `os.replace`'d — atomic on
POSIX.

What the retry loop must leave behind
------------------------------------
`lib/awsclients.py` disables botocore's transparent retry so that one recorded call is one
attempt. Retries therefore live here, and each one is **counted into the trial record**
(`attempts`, `retry_delay_s`). A latency arm that silently retried would publish a p99
containing a 5-second backoff sleep and call it service latency; with the count in the
record, `--exclude-retried` in analysis is a decision a reader can see, not one the harness
made for them.

Errors are classified before being retried. A `ThrottlingException` is transient and worth
3 attempts; an `AccessDeniedException` is frequently *the oracle* (F5-1, F5-2, F5-3b all
assert it) and retrying it wastes 15 seconds proving a permission is still absent. A
`ValidationException` means the request was malformed — a harness bug that no number of
retries fixes. `RETRY_CODES` is an explicit allowlist for that reason: the default for an
unknown error is **do not retry**, because a retried unknown error looks like a flaky
service when it is usually our own defect.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from botocore.exceptions import BotoCoreError, ClientError

import redact as _redact

# Transient AWS error codes worth another attempt. An allowlist, not a denylist: an
# unrecognised code is treated as permanent, so a harness bug surfaces as a failure
# instead of as three slow failures that read like service flakiness.
RETRY_CODES = frozenset({
    "ThrottlingException", "Throttling", "TooManyRequestsException",
    "RequestLimitExceeded", "ProvisionedThroughputExceededException",
    "ServiceUnavailable", "ServiceUnavailableException",
    "InternalServerException", "InternalFailure", "InternalError",
    "RequestTimeout", "RequestTimeoutException",
    "ModelTimeoutException",        # bedrock-runtime, transient
    "ModelNotReadyException",       # bedrock-runtime, transient
})

# Codes that are frequently the ORACLE of a red-team case. Retrying them is not merely
# wasteful, it is misleading: F5-2's whole result is that UpdateGateway is denied, and a
# log showing three attempts suggests we doubted the answer.
ORACLE_CODES = frozenset({
    "AccessDeniedException", "AccessDenied", "UnauthorizedException",
    "ResourceNotFoundException", "ConflictException",
    "ValidationException", "ThrottledException",
})

MAX_ATTEMPTS = 3
BASE_DELAY_S = 5.0


def error_code(exc: BaseException) -> str:
    """The AWS error code, or the exception class name when there is none.

    An exception carrying a non-empty `error_code` attribute is honoured before the class
    name is used, which is how `evidence.CapturedCallError` survives this layer. The check
    is structural rather than an `isinstance` against `evidence`: `checkpoint` sits below
    `evidence` in the import order used by every arm script (`arms` imports both), and
    importing upward to recognise one exception type would make the retry policy depend on
    the evidence writer.

    This mattered concretely. `capture()` absorbs the `ClientError` by design — an error is
    *data* here, because half this project's oracles are `AccessDenied` — so `arms.run_arm`
    only ever raises the wrapper. Before this branch existed, every failure in every Phase
    1 arm was recorded as `error_code="RuntimeError"`, and `tally()`'s `failure_codes` — the
    field that explains why an arm has holes — could not distinguish throttling from a
    malformed request. Found by test_a_failed_trial_is_excluded_from_the_denominator, which
    asserted the *code* and not merely the count.

    A connection-level failure has NO AWS error code, so the wrapper carries
    `error_code=""` and the fall-through returned the wrapper's own class name:
    `failure_codes` read `["CapturedCallError"]` for 3,378 lost trials whose actual cause
    was `EndpointConnectionError` (DEV-P1-11). `error_class` is therefore consulted between
    the two — it is the transport-level name the same wrapper already carries, and it is the
    only place the cause survives.
    """
    if isinstance(exc, ClientError):
        return str(exc.response.get("Error", {}).get("Code") or "ClientError")
    wrapped = getattr(exc, "error_code", "")
    if isinstance(wrapped, str) and wrapped:
        return wrapped
    klass = getattr(exc, "error_class", "")
    if isinstance(klass, str) and klass:
        return klass
    return type(exc).__name__


# Meta fields that determine what a trial IS, rather than describing the run that made it.
# A resume whose design keys disagree with the checkpoint's is refused by `set_meta`.
#
# Derived from what `arms.run_arm` records, minus the three that legitimately vary across a
# resume: `run_id` (varying it is how this project re-emits without re-billing), `planned_n`
# (a `--n 3` smoke followed by a full run grows it), and `sdk` (an SDK upgrade mid-case is
# worth noticing but is not a change to the request — and `arms.run_arm` already refuses
# outright if the installed botocore cannot model ApplyGuardrail).
#
# `corpus` is included: two arms reading different corpora under one label would pool items
# whose ids may not even collide, and the resulting n would be the sum of two designs.
DESIGN_KEYS = ("source", "qualifiers", "output_scope", "guardrail_version", "region",
               "corpus", "is_smoke", "operation")

# Transport-level failures: no AWS error code, transient by nature. Named once and used
# for BOTH the raw botocore exception and the wrapper, because they are the same event
# reaching this module by two different paths and a set duplicated per path is a set that
# will diverge.
#
# The first six are botocore's. The rest are `urllib3`'s, and they are here because the
# gateway DATA plane does not go through botocore at all: `lib/mcp.py` signs a POST and
# sends it through a `urllib3.PoolManager` built with `retries=False` (deliberately — a
# transparently retried POST reports one duration covering several attempts, and a policy
# denial that arrived on attempt 3 would be recorded as if it arrived immediately). So
# EVERY retry decision on that plane lands here, and a name missing from this set is a
# trial lost with zero retries. That is not hypothetical: it is exactly DEV-P1-11, where an
# `EndpointConnectionError` reaching `is_retryable` stripped of its identity burned 3,378
# Phase 1 trials against a policy that would have absorbed the outage whole. F4 sends up to
# 1,440 data-plane calls, so the same blind spot on the same seam was worth closing before
# the first one was sent.
#
# The urllib3 names are MEASURED, not recalled (urllib3 2.7.0, this venv, 2026-08-11):
#   DNS failure          -> NameResolutionError  (subclasses NewConnectionError)
#   connection refused   -> NewConnectionError   (subclasses ConnectTimeoutError)
#   connect timeout      -> ConnectTimeoutError
# `ReadTimeoutError` and `ConnectTimeoutError` collide by NAME with botocore's, which is why
# the two halves can share one set; the collision is a coincidence of naming, not a shared
# class, and `error_code()` compares names rather than classes so it does not matter.
# `ProtocolError` is a mid-flight connection close; `SSLError` is included because a
# handshake failure against a healthy endpoint is transient in practice. `MaxRetryError`
# and `ClosedPoolError` are deliberately ABSENT: with `retries=False` the former cannot be
# raised by this pool, and the latter means we closed the pool ourselves — a defect in our
# code, which per this function's allowlist rule must be classified permanent.
RETRYABLE_TRANSPORT = frozenset({
    # botocore
    "EndpointConnectionError", "ConnectionClosedError", "ReadTimeoutError",
    "ConnectTimeoutError", "HTTPClientError", "ConnectionError",
    # urllib3 (the MCP data plane in lib/mcp.py)
    "NameResolutionError", "NewConnectionError", "ProtocolError", "SSLError",
})


def is_retryable(exc: BaseException) -> bool:
    """Retry throttles and transport hiccups; never retry an oracle answer.

    The allowlist is deliberate — an unrecognised exception is classified **permanent** so a
    harness bug cannot masquerade as service flakiness. But an allowlist only works if every
    live failure mode is actually on it, and a mode that reaches this function stripped of
    its identity is off the list by construction.

    That happened twice, on the same seam, and the second one cost a whole Phase 1 run:

    * A `ThrottlingException` arriving as the `capture()` wrapper had a *code*, and the
      `wrapped` branch below was added to honour it.
    * An `EndpointConnectionError` arriving as the wrapper has **no code at all** —
      `error_code=""` — so it fell past that branch to `return False`. A local ~80 s
      network outage on 2026-08-10 therefore burned 3,378 trials with **zero** retries,
      against a retry policy that would have absorbed it whole. Every arm silently
      continued on the 3 trials it had before the outage, `require_measured` saw a positive
      denominator, and the scripts exited **rc=0** with published verdicts (DEV-P1-11).

    So the wrapper is now judged on its `error_class` when it has no code, against the same
    `RETRYABLE_TRANSPORT` set used for raw botocore errors.
    """
    if isinstance(exc, ClientError):
        return error_code(exc) in RETRY_CODES
    if isinstance(exc, BotoCoreError):
        return type(exc).__name__ in RETRYABLE_TRANSPORT
    # A wrapper carrying an AWS error code is judged on that code, not on its class.
    # Without this, a ThrottlingException that reached us through `raise_for_status` was
    # classified permanent and got zero retries — the backoff machinery was dead on the
    # only path that uses it, and the loss showed up as a smaller denominator rather than
    # as an error.
    wrapped = getattr(exc, "error_code", "")
    if isinstance(wrapped, str) and wrapped:
        return wrapped in RETRY_CODES
    # ...and a wrapper carrying NO code is judged on the transport class it does carry.
    # Without this branch the retry policy is silently unreachable for every failure that
    # never got an HTTP response — i.e. for exactly the failures retrying exists to absorb.
    klass = getattr(exc, "error_class", "")
    if isinstance(klass, str) and klass:
        return klass in RETRYABLE_TRANSPORT
    return False


def backoff_delay(attempt: int, *, base: float = BASE_DELAY_S) -> float:
    """`base * attempt` — linear, matching the validated overnight run.

    Not exponential and not jittered, deliberately. The ceilings this harness respects are
    **documented per-second rates** (1/s for policy-engine lifecycle, 5/s for policy and
    gateway mutations), not an opaque adaptive quota, so `lib/awsclients.RateLimiter`
    already spaces calls below the limit. Backoff here handles the residual — a
    server-side hiccup — where doubling would push a 3rd attempt 20 s out and, in an n=1000
    latency arm, silently reorder interleaved A/B pairs.
    """
    if attempt < 1:
        raise ValueError("attempt is 1-based")
    return base * attempt


@dataclass
class Checkpoint:
    """A resumable per-trial record for one cell of one case.

    `case_id` and `cell` together name the file, so two arms of the same case (guardrail-on
    vs guardrail-off) never share a checkpoint. Sharing one is how a resumed run would
    "skip" trials it had never done, because the ids collided.
    """

    case_id: str
    cell: str
    root: Path = Path("results") / "checkpoints"
    _done: dict[str, Any] = field(default_factory=dict, repr=False)
    _failed: dict[str, Any] = field(default_factory=dict, repr=False)
    _meta: dict[str, Any] = field(default_factory=dict, repr=False)
    # The meta as it was on disk, kept separate from `_meta` (which the current run
    # overwrites) so `set_meta` can compare the two. See `DESIGN_KEYS`.
    _loaded_meta: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---------------------------------------------------------------- paths

    @property
    def path(self) -> Path:
        return self.root / f"{self.case_id}__{self.cell}.json"

    # ------------------------------------------------------------ load/save

    def load(self) -> "Checkpoint":
        """Read an existing checkpoint, or start an empty one.

        A corrupt file is **fatal**, not silently discarded. Starting fresh on a parse
        error would turn a partially-written file into a full re-run whose evidence
        directory already holds records for trials the checkpoint no longer knows about —
        duplicated trials in the evidence, missing from the analysis.
        """
        if not self.path.is_file():
            return self
        try:
            body = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise RuntimeError(
                f"{self.path} is not readable JSON ({e}). Refusing to start fresh: the "
                f"evidence tree may already hold records for completed trials, and a "
                f"blank checkpoint would collect them a second time. Inspect the file, "
                f"then either repair it or move it aside deliberately") from e
        if body.get("case_id") != self.case_id or body.get("cell") != self.cell:
            raise RuntimeError(
                f"{self.path} holds case={body.get('case_id')!r} cell={body.get('cell')!r} "
                f"but was opened as case={self.case_id!r} cell={self.cell!r} — resuming "
                f"would attribute one arm's trials to another")
        self._loaded_meta = dict(body.get("meta") or {})
        self._done = dict(body.get("done") or {})
        self._failed = dict(body.get("failed") or {})
        self._meta = dict(body.get("meta") or {})
        return self

    def save(self) -> None:
        """Atomically persist. Called after every trial, not every N trials.

        ARN account fields are masked on the way out (`lib/redact.py`). `results/` is
        distributable and a checkpoint carries `appliedGuardrailDetails.guardrailArn` on
        every row, so the first live run wrote the account ID into 82 files before the
        redaction gate caught it. Masking here rather than at the call sites that read an
        ARN means a future case inherits it (DEVIATIONS.md/DEV-P1-13).

        The mask applies to the serialized copy only — `self._done` keeps the true ARN, so
        an in-flight arm and the analysis that follows it still read what the service
        actually returned.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        body = {
            "case_id": self.case_id,
            "cell": self.cell,
            "n_done": len(self._done),
            "n_failed": len(self._failed),
            "meta": self._meta,
            "done": self._done,
            "failed": self._failed,
        }
        tmp = self.path.with_suffix(".json.tmp")
        # Same directory, so os.replace is a rename within one filesystem and therefore
        # atomic. Writing to /tmp and copying would not be.
        with tmp.open("w", encoding="utf-8") as fh:
            # default=str runs BEFORE the mask would see a non-JSON value, so the mask is
            # applied to an already-JSON-shaped structure: dump to a string, mask, write.
            # Masking `body` directly would miss an ARN inside an object that only becomes
            # a string via default=str.
            fh.write(_redact.mask_text(
                json.dumps(body, indent=2, sort_keys=True, default=str)))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    # -------------------------------------------------------------- queries

    def is_done(self, trial_id: str) -> bool:
        return trial_id in self._done

    def results(self) -> dict[str, Any]:
        """Completed trials only. Failures are never analysable results."""
        return dict(self._done)

    def failures(self) -> dict[str, Any]:
        return dict(self._failed)

    @property
    def n_done(self) -> int:
        return len(self._done)

    @property
    def n_failed(self) -> int:
        return len(self._failed)

    def set_meta(self, **kw: Any) -> None:
        """Record the arm's configuration — and refuse a resume that changed the design.

        `load` already refuses a checkpoint whose `case_id`/`cell` disagree, because
        "resuming would attribute one arm's trials to another". The same argument applies to
        every field that determines what a trial *is*, and those were recorded here and
        never checked.

        That gap is not hypothetical. F3-7 collected 120 trials at `source=INPUT`, where the
        contextual-grounding filter is silently skipped, and published a FALSE from them
        (DEVIATIONS.md/DEV-P1-18). Fixing the arm to `source=OUTPUT` and re-running would
        have found 120 completed trial ids in the checkpoint, skipped every one of them, and
        re-published the identical wrong verdict — with the corrected source now recorded in
        the meta beside rows that were never collected that way. The fix would have looked
        applied and changed nothing.

        So a resume across a design change is fatal here, in the same way and for the same
        reason as the `case_id`/`cell` guard. The remedy is stated in the message rather than
        automated: deleting a checkpoint discards paid-for trials, which is the operator's
        call, not the library's.

        Only design keys are compared. `run_id` deliberately is NOT one — resuming the same
        arm under a new run id is the normal way this project avoids re-billing, and it is
        exactly how F8-6 and F10-2 were re-emitted at $0. `planned_n` is not one either: a
        `--n 3` smoke followed by a full run legitimately grows it, and `is_smoke` is
        compared instead, which catches the direction that matters (smoke rows silently
        counted as a full run).
        """
        drift = {}
        for k in DESIGN_KEYS:
            if k in kw and k in self._loaded_meta and self._loaded_meta[k] != kw[k]:
                drift[k] = (self._loaded_meta[k], kw[k])
        if drift and self._done:
            detail = "\n".join(f"  {k}: on disk {old!r} -> now {new!r}"
                               for k, (old, new) in sorted(drift.items()))
            raise RuntimeError(
                f"{self.path} holds {len(self._done)} completed trial(s) collected under a "
                f"DIFFERENT arm design:\n{detail}\n"
                f"Resuming would skip those trials and publish them as if they had been "
                f"collected the new way — the fix would look applied while changing "
                f"nothing. This is the same failure the case_id/cell guard prevents.\n"
                f"If the old trials are genuinely obsolete, move or delete "
                f"{self.path.name} deliberately; that discards trials already paid for, "
                f"which is not this library's decision to make.")
        self._meta.update(kw)

    # --------------------------------------------------------------- record

    def record(self, trial_id: str, result: dict[str, Any], *, attempts: int = 1,
               retry_delay_s: float = 0.0) -> None:
        """Store a completed trial. Re-recording an existing id is an error.

        Silently overwriting would hide the duplicate-trial bug the Phase-4 gate exists to
        catch: a resumed run that re-ran work it had already done would produce the right
        *count* with the wrong trials in it.
        """
        if trial_id in self._done:
            raise RuntimeError(
                f"trial {trial_id!r} is already recorded in {self.path.name}. A resumed "
                f"run must skip completed trials, not overwrite them — an overwrite keeps "
                f"the count correct while changing which trials the count is over")
        self._done[trial_id] = {**result, "attempts": attempts,
                                "retry_delay_s": round(retry_delay_s, 3)}
        self._failed.pop(trial_id, None)   # a retry that finally succeeded
        self.save()

    def record_failure(self, trial_id: str, exc: BaseException, *,
                       attempts: int, retry_delay_s: float = 0.0) -> None:
        """Store a trial that could not be completed. NOT a result.

        Kept in the checkpoint (rather than dropped) for two reasons: a resumed run should
        retry it, and the analysis must be able to state how many trials were attempted
        versus usable. A cell that quietly shrinks from 300 to 287 changes every interval
        it feeds.
        """
        if attempts < 1:
            raise ValueError(f"attempts must be at least 1, got {attempts}: a recorded "
                             f"failure means a call was made, and a 0 here would say "
                             f"otherwise")
        self._failed[trial_id] = {
            "error_code": error_code(exc),
            "error_class": type(exc).__name__,
            "error_message": str(exc)[:500],
            "attempts": attempts,
            "retry_delay_s": round(retry_delay_s, 3),
        }
        self.save()

    # ------------------------------------------------------------------ run

    def run_trial(self, trial_id: str, fn: Callable[[], dict[str, Any]], *,
                  max_attempts: int = MAX_ATTEMPTS,
                  base_delay: float = BASE_DELAY_S,
                  sleep: Callable[[float], None] = time.sleep) -> dict[str, Any] | None:
        """Run one trial with retries, recording it exactly once.

        Returns the result, or None if the trial could not be completed. A caller that
        treats None as a result is the failure mode this whole module is shaped around, so
        the type makes the distinction unmissable rather than encoding it in a sentinel
        value that arithmetic would happily consume.
        """
        if self.is_done(trial_id):
            return self._done[trial_id]

        total_delay = 0.0
        last: BaseException | None = None
        made = 0
        for attempt in range(1, max_attempts + 1):
            made = attempt
            try:
                result = fn()
            except BaseException as exc:                     # noqa: BLE001
                last = exc
                # An oracle code is the answer, not an obstacle: F5-1/F5-2/F5-3b assert
                # AccessDenied. Retrying it would spend 15 s re-proving a permission is
                # absent and would leave a record implying we doubted the result.
                if not is_retryable(exc) or attempt == max_attempts:
                    break
                delay = backoff_delay(attempt, base=base_delay)
                total_delay += delay
                sleep(delay)
            else:
                self.record(trial_id, result, attempts=attempt,
                            retry_delay_s=total_delay)
                return self._done[trial_id]

        assert last is not None
        # `made`, NOT max_attempts. An oracle error breaks out after one call, and writing
        # 3 there would put a number in the evidence that no call produced — a record
        # implying we retried an AccessDenied twice before believing it. Found by
        # test_an_oracle_error_costs_exactly_one_attempt, which asserted the observable
        # call count and the recorded count separately; only the second one caught it.
        self.record_failure(trial_id, last, attempts=made, retry_delay_s=total_delay)
        return None


def resume_summary(cp: Checkpoint, planned_n: int) -> dict[str, Any]:
    """What a resumed run must print before doing anything else.

    `usable_fraction` is the number that decides whether an arm may be analysed at all:
    the pre-registered n is a *precision* commitment, and a cell that completed 240 of 300
    trials has a wider interval than the one the pre-registration promised. Printing it at
    the start means the shortfall is visible before the analysis, not discovered in it.
    """
    if planned_n <= 0:
        raise ValueError("planned_n must be positive; it comes from the sealed "
                         "pre-registration, and a zero would make every fraction 100%")
    return {
        "case_id": cp.case_id,
        "cell": cp.cell,
        "planned_n": planned_n,
        "n_done": cp.n_done,
        "n_failed": cp.n_failed,
        "n_remaining": max(0, planned_n - cp.n_done),
        "usable_fraction": round(cp.n_done / planned_n, 4),
        "complete": cp.n_done >= planned_n,
    }
