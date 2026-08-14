#!/usr/bin/env python3
"""F9-3: when ApplyGuardrail is throttled, is the throttle OBSERVABLE — or does content
pass through unevaluated?

    .venv-oracle/bin/python f9_failsecure/01_throttle_burst.py --dry-run
    .venv-oracle/bin/python f9_failsecure/01_throttle_burst.py --n 20      # smoke
    .venv-oracle/bin/python f9_failsecure/01_throttle_burst.py

The sealed oracle (kind E, EXISTENCE):

    TRUE if throttled requests are denied or error rather than passing unevaluated;
    FALSE if a throttle silently allows content through

and the sealed method is "drive ApplyGuardrail past its 100 rps quota, inspect verdicts".

THE BURST IS SINGLE-DIGIT SECONDS, AND THAT IS A BLAST-RADIUS DECISION
---------------------------------------------------------------------
The 100 rps ApplyGuardrail ceiling is an ACCOUNT-level, per-Region quota, not a
per-guardrail one. Exceeding it deliberately means that for the duration of the burst any
OTHER caller of ApplyGuardrail in this account and Region can be throttled too, and this
account carries ~$27k/mo of unrelated traffic. So the offered load is bounded three ways,
each by a named constant rather than by a loop that runs until something happens:

  * `N_BURST` requests, hard maximum, counted — not "until a throttle appears";
  * `BURST_DEADLINE_S` seconds of OFFERED LOAD, after which every remaining task returns
    without calling AWS. Single digit, deliberately;
  * `BURST_WORKERS` concurrent requests, so the instantaneous offered rate is bounded by
    `BURST_WORKERS / latency` and cannot run away.

A multi-minute burst is NOT run and must not be added here. If this case ever needs more
signal, the answer is a second short burst on another day (which is also how the
replication rule is discharged), not a longer one.

WHY THIS CASE DELIBERATELY DEFEATS THE HARNESS'S OWN RATE LIMITER
-----------------------------------------------------------------
Every other script in this repo calls `lim.wait(op)` before each request precisely so it
never earns a `ThrottlingException`: `lib/awsclients.RateLimiter` is a floor on spacing,
and `lib/phase1.run_arms` is sequential for the same reason ("concurrency would put the
arms into contention for that budget"). F9-3 is the one case whose subject IS the ceiling,
so it has to exceed it.

The bypass is honest, minimal and local, and it is none of the things it could have been:

  * `RATE_LIMITS` is NOT edited, and `A.limiter()` is NOT monkeypatched. The limiter is a
    shared, process-global object (`awsclients._LIMITER`); mutating it or its table would
    silently unpace every other call site in the same process, including this script's own
    control arm. Nothing here writes to either.
  * The bypass is simply THAT THE BURST ARM DOES NOT CALL `lim.wait`. Pacing in this
    platform is opt-in per call site, so declining to opt in is the whole mechanism — and
    it is auditable rather than asserted: `lim.waits["ApplyGuardrail"]` is snapshotted
    either side of each arm, and the record shows the counter MOVING across the control arm
    and STANDING STILL across the burst (`limiter_waits_delta`). A future edit that
    accidentally paced the burst shows up as a non-zero delta beside a zero throttle count.
  * The control arm keeps its `lim.wait`, so the ceiling is still respected everywhere the
    case is not measuring it.

What legitimises exceeding this particular ceiling and no other: `A.limit_provenance
("ApplyGuardrail")` is `aws_documented`. Six entries in that table are `self_imposed`
guesses, and bursting past one of those would measure our own caution. This one is AWS's
published 100 rps, which is the number the sealed method names.

WHY THE BURST DOES NOT GO THROUGH `arms.run_arm`, AND THE TWO RETRY LAYERS
-------------------------------------------------------------------------
A `ThrottlingException` here is the SUCCESS CONDITION OF THE SETUP, not an error to
retry. Two independent layers would otherwise hide it, and both are checked:

  1. **botocore's transparent retry.** Under `standard` or `adaptive` mode botocore
     re-drives a throttled request until it succeeds and reports one duration covering
     several attempts, so the observation would be "zero throttles" from a run that was
     throttled repeatedly. `lib/awsclients.ClientFactory._config` ALREADY sets
     `retries={"mode": "standard", "total_max_attempts": 1}` — one attempt, i.e. no retry —
     for its own reasons (an AccessDenied oracle that fired on attempt 3 would be recorded
     as if it fired immediately). This file therefore inherits the setting rather than
     restating it: `burst_client` builds its client by MERGING onto the factory's own
     `Config`, and `assert_retries_disabled` runs BEFORE the first request is sent. A copy
     of the retry dict here would be a second, unchecked source of truth that could drift
     from lib's and mask exactly the defect the assertion exists to catch.
  2. **the harness's own retry.** `checkpoint.RETRY_CODES` contains
     `ThrottlingException`, and `arms.run_arm` retries through it with linear backoff. That
     is right for every arm whose throttle is an accident and wrong for the one arm whose
     throttle is the measurement, so this case does not use `run_arm` at all. It calls
     `evidence.capture` directly, where a failure is data: `rec.ok`, `.error_code`,
     `.http_status`, `.request_id`, `.path`.

THE TRICHOTOMY, AND WHY THE THIRD BUCKET NEEDS A CONTROL
--------------------------------------------------------
Every response is classified into exactly one of four buckets, with counts:

  (a) EVALUATED          — a real verdict came back: the word policy reported our term and
                           the action is the one the control established.
  (b) OBSERVABLE FAILURE — `rec.ok` is False. A ThrottlingException, a 429, a timeout: any
                           failure the caller can see. Throttles are counted as a NAMED
                           SUBSET of this bucket (see the guard below).
  (c) SILENT PASS        — HTTP 200, no intervention, and no `wordPolicy` block at all:
                           the content went through unevaluated.
  (d) UNCLASSIFIED       — anything else. Loud, and fatal to the verdict, rather than
                           folded into whichever neighbouring bucket looks close.

Bucket (c) is the hard one, because **a 200 with no intervention is the NORMAL response to
benign content**. Read naively, every unthrottled benign 200 looks like a silent pass and
every silent pass looks like benign content. Two things separate them:

  * the probe text provably trips the guardrail. It contains a term from the provisioned
    custom word list (`phase1.configured_words`, read from the manifest — not a literal
    here), and the `words` guardrail configures every term at `inputAction: BLOCK`. An
    exact-match word filter is chosen over a content filter for this precisely because it
    is deterministic: there is no confidence threshold to land the wrong side of.
  * a PRE-BURST CONTROL sends that same text at low rate and REFUSES TO PROCEED unless
    every trial comes back `GUARDRAIL_INTERVENED` with the term reported. So the control
    validates the classifier, not just the guardrail: if the service ever reported the
    match under a different spelling, or returned the block under a different action, the
    control fails and this script stops — instead of quietly filing every burst response as
    a silent pass.

`wordPolicy` is ABSENT on a non-match (measured; see the table in
`arms.read_assessment`), which is what makes (c) expressible at all. Note that
`assessments[]` is never empty even at `action=NONE` — it still carries
`appliedGuardrailDetails` and `invocationMetrics` — so "no assessment" here means "no
`wordPolicy` block", not "no assessments list". Classifying on the empty list would put
every silent pass into (a).

THE VERDICT RULE, INCLUDING THE TWO REFUSALS THAT ARE MANDATORY
--------------------------------------------------------------
    FALSE          if (c) > 0                      — a throttle let content through
    TRUE           if (c) == 0 and throttles > 0   — and (d) == 0
    INCONCLUSIVE   otherwise

Two guards make an INCONCLUSIVE, and neither may be relaxed into a TRUE:

  * **no throttle, no case.** A run that never got throttled proves nothing whatsoever
    about throttling; "(c) == 0" over an unthrottled burst is vacuously true of a run that
    never put the question. The sealed oracle's subject is "throttled requests".
    The guard reads the THROTTLE subset of (b) rather than (b) itself, which is stricter
    than the plain reading and stricter in the honest direction: 480 AccessDenied responses
    are observable failures that also never reached the quota.
  * **the mutation must invert.** Rate is the treatment. The control arm (serial, paced)
    must show ZERO throttles and the burst arm must show some; if both arms throttle
    equally, or neither does, the manipulation did not do anything and the burst's cleanliness
    is not attributable to it. `mutation_inverted` is recorded either way. It is set as an
    ATTRIBUTE after construction, never as a `**detail` keyword — `phase1._detail` raises on
    an Observation field name passed as detail, after F5-1 published INCONCLUSIVE over a
    successful run whose mandatory mutation had inverted 20/20.

F9-3's mutation is not sealed as mandatory (`O.mutation_is_mandatory('F9-3')` is False), so
`oracle.evaluate` will not downgrade the verdict on its own. The downgrade is therefore
performed HERE, explicitly, rather than left to a machine that has not been asked to do it.

THE ACHIEVED RATE IS RECORDED, NOT THE INTENDED ONE
---------------------------------------------------
An intended 300 rps that actually achieved 40 rps is the reason a zero-throttle result
would happen, and the payload has to make that diagnosable. So `achieved_rps` is
`requests / (last end - first start)`, measured, and it is printed next to the documented
ceiling. The specific trap this case walks into otherwise is botocore's default
`max_pool_connections=10`: 96 worker threads sharing a 10-connection pool queue behind it
and offer ~10/latency ~= 24 rps — a quarter of the ceiling — while every thread looks busy.
`burst_client` raises the pool to `BURST_WORKERS` for this client only, and the pool size
travels in the payload beside the achieved rate so the two can be read together.

WHAT A TRUE HERE WOULD NOT PROVE
--------------------------------
That the guardrail is fail-secure in an APPLICATION. This measures what ApplyGuardrail
returns to its caller. Whether the caller then fails closed — treats the exception as a
block rather than logging it and forwarding the content — is a property of the integration
and is invisible from here. The gateway data path is a different transport with its own
quota, and is not exercised.

COST, AND WHAT IS AND IS NOT VERIFIED ABOUT IT
----------------------------------------------
`N_TOTAL_MAX` = `N_CONTROL` + `N_BURST` requests, one short content block each, one text
unit each (`probe_text` is well under the 1,000-character unit). The word-filter usagetype
`USE1-Guardrail-WordPolicyUnitsConsumed` EXISTS on the bill
(results/FINDING-P0-PRICING.md) but carries no verified price in `cost_model.yaml`, so the
estimate below is priced at the highest verified ApplyGuardrail rate — the content-policy
unit, $0.00015 — and is therefore an UPPER BOUND rather than a projection. Said plainly
because a five-decimal number sourced from memory is how this project's cost model was
wrong by 5x once already.

NOTHING IS CREATED
------------------
No guardrail, policy, gateway or role. The subject is the provisioner's existing `words`
guardrail, used read-only through ApplyGuardrail at `guardrailVersion=DRAFT` exactly as
F3-6, F8-7 and F10-2 use their manifest guardrails. Zero mutations, so the residue is zero
by construction — and it is still COMPUTED, from the created-vs-deleted two lists in
`phase1.probe_residue`, in a `finally`, so that a later edit which does create something
inherits the teardown instead of needing one written.
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from botocore.config import Config

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R                                                     # noqa: E402
import awsclients as A                                               # noqa: E402
import oracle as O                                                   # noqa: E402
import phase1 as P                                                   # noqa: E402
import stats as S                                                    # noqa: E402
import testbed as T                                                  # noqa: E402
from evidence import EvidenceStore, Record, capture                   # noqa: E402

CASE = "F9-3"
FAMILY = "f9"

# The provisioner's exact-match word-filter guardrail. Chosen over a content filter
# because the control has to be DETERMINISTIC: a custom word either appears or it does
# not, with no confidence threshold to land the wrong side of.
GUARDRAIL_KEY = "words"
GUARDRAIL_VERSION = "DRAFT"

# The `assessments[]` key whose presence means "the policy under test evaluated this
# request". Absent on a non-match, which is what makes the silent-pass bucket expressible.
POLICY_BLOCK = "wordPolicy"

# The action a matching term produces when the guardrail is not throttled. Asserted by the
# control rather than assumed here: `wordsConfig[].inputAction` is BLOCK in the
# provisioner, and a configuration change that made it NONE must stop this case rather
# than silently reclassify every burst response.
EXPECT_ACTION = "GUARDRAIL_INTERVENED"

# ---- the three bounds on offered load. See the docstring; these are the blast radius. ---
N_CONTROL = 12            # serial, paced, low rate. The mutation's other arm.
N_BURST = 480             # HARD maximum requests in the burst. Not "until a throttle".
BURST_WORKERS = 96        # concurrent in-flight requests, and the connection-pool size
BURST_DEADLINE_S = 5.0    # seconds of OFFERED LOAD. Single digit, deliberately.
N_TOTAL_MAX = N_CONTROL + N_BURST

# The documented ceiling this case exists to exceed. Read from `awsclients`, not typed
# here, so the number the verdict is compared against is the number the harness paces to.
DOCUMENTED_RPS = A.rate_limit_for("ApplyGuardrail")

# Cost. One short block per call, one text unit per block. See the docstring on why this is
# an upper bound and not a price for the word-policy usagetype.
TEXT_UNITS_PER_CALL = 1
USD_PER_TEXT_UNIT_UPPER_BOUND = 0.00015   # cost_model.yaml: guardrail_text_unit, verified

# Error codes that mean "the quota refused this request". `http_status == 429` is treated
# as a throttle too, so a code this list has never seen still lands in the right subset.
THROTTLE_CODES = frozenset({
    "ThrottlingException", "Throttling", "ThrottledException",
    "TooManyRequestsException", "RequestLimitExceeded", "RequestThrottled",
    "RequestThrottledException", "SlowDown",
    "ServiceQuotaExceededException",
})

# The four buckets. Named constants because they are keys in the published payload.
EVALUATED = "evaluated"
OBSERVABLE_FAILURE = "observable_failure"
SILENT_PASS = "silent_pass"
UNCLASSIFIED = "unclassified"
BUCKETS = (EVALUATED, OBSERVABLE_FAILURE, SILENT_PASS, UNCLASSIFIED)


class Refusal(RuntimeError):
    """A precondition that makes the verdict unsafe to compute. Never a verdict."""


class RetryConfigError(Refusal):
    """The effective retry config is not what this case requires.

    Its own class because it is the single most likely way F9-3 produces a false verdict:
    a client that transparently retries a throttle observes zero throttles and concludes
    that nothing was throttled. Raised BEFORE the first request.
    """


# ---------------------------------------------------------------------------
# the probe text
# ---------------------------------------------------------------------------

def probe_text(words: list[str]) -> str:
    """Short, benign-looking prose carrying ONE provisioned custom word.

    The term comes from `phase1.configured_words` — the manifest — and not from a literal
    here, for the reason `configured_topic` gives: a term that disagreed with the
    provisioned guardrail would produce a control that never intervenes, and this script
    would then refuse for a reason that had nothing to do with throttling.

    Short because ApplyGuardrail bills per text unit and a burst multiplies whatever this
    costs by `N_BURST`. One sentence is one text unit.
    """
    if not words:
        raise Refusal(
            "the manifest records no custom words, so no text can be constructed that the "
            "guardrail provably intervenes on — and without that, every unthrottled 200 "
            "is indistinguishable from a silent pass")
    text = f"the {words[0]} note is filed"
    if len(text) > 1000:
        raise Refusal(f"probe text is {len(text)} characters, over the 1,000-character "
                      f"text unit; a burst would bill more than one unit per call")
    return text


def expected_word(words: list[str]) -> str:
    return words[0]


# ---------------------------------------------------------------------------
# the retry configuration, asserted before anything is sent
# ---------------------------------------------------------------------------

def retry_view(cfg: Config) -> dict[str, Any]:
    """The effective retry settings of a botocore `Config`, as a plain dict.

    botocore accepts `max_attempts` and `total_max_attempts` as spellings of the same
    thing, so both are reported and the effective attempt count is derived from whichever
    is present. A view that read only one key would call a retrying client retry-free.
    """
    retries = dict(cfg.retries or {})
    total = retries.get("total_max_attempts")
    if total is None:
        total = retries.get("max_attempts")
    return {
        "mode": retries.get("mode"),
        "total_max_attempts": retries.get("total_max_attempts"),
        "max_attempts": retries.get("max_attempts"),
        "effective_total_attempts": total,
        "max_pool_connections": cfg.max_pool_connections,
        "read_timeout": cfg.read_timeout,
        "connect_timeout": cfg.connect_timeout,
    }


def assert_retries_disabled(cfg: Config, *, where: str) -> dict[str, Any]:
    """Refuse unless this config makes exactly ONE attempt per request.

    Called before the first request of every arm, and its return value is published. The
    failure it prevents is silent by construction: botocore's `standard` and `adaptive`
    modes re-drive a throttled request until it succeeds, so the run would observe zero
    throttles, report an unthrottled burst, and conclude nothing — while every number in
    the record looked right.

    `mode` is deliberately NOT constrained. What matters is the attempt count: `standard`
    with one attempt retries nothing, and pinning the mode string as well would make this
    case fail if `lib/awsclients.py` ever moved to `legacy` with one attempt, which is the
    same behaviour under a different name.
    """
    v = retry_view(cfg)
    total = v["effective_total_attempts"]
    if total is None:
        raise RetryConfigError(
            f"{where}: the client Config declares no attempt limit "
            f"({v['mode']!r} mode, retries={cfg.retries!r}), so botocore's default applies "
            f"and a ThrottlingException would be retried away before this case could see "
            f"it. F9-3's setup condition is that the throttle SURVIVES to the caller")
    if int(total) != 1:
        raise RetryConfigError(
            f"{where}: the client Config allows {total} attempts per request. Any value "
            f"above 1 means botocore re-drives a throttled request transparently, so a "
            f"throttled run reports zero throttles and this case returns a false verdict. "
            f"lib/awsclients.ClientFactory._config sets total_max_attempts=1; something "
            f"has overridden it")
    return v


def burst_client(fc: A.ClientFactory, *, pool: int = BURST_WORKERS):
    """A bedrock-runtime client for the burst: the factory's own config, wider pool.

    TWO things about how this is built are load-bearing.

    **The retry config is INHERITED, not restated.** The config is read off the factory's
    own client (`meta.config`) and merged with a single override, so
    `lib/awsclients.ClientFactory._config`'s `total_max_attempts=1` reaches this client by
    construction. Writing a fresh `Config(retries={...})` here would create a second copy
    of a setting whose whole purpose is to be checked — and a copy cannot detect a drift in
    the original. `assert_retries_disabled` runs on the merged result, so if lib ever
    changes its mind this case stops instead of publishing a retried run.

    **The connection pool has to be widened, and this is the case's most likely dud.**
    botocore's default is `max_pool_connections=10`. With 96 worker threads sharing 10
    connections, the offered rate is bounded by `10 / latency` — about 24 rps against the
    p50 ApplyGuardrail latency in this project's evidence tree — so the burst would sit at
    a quarter of the ceiling, be throttled zero times, and look like a clean pass. The
    pool is therefore raised to the worker count for THIS client only; the factory's cached
    client, which every other case uses, is untouched.
    """
    base = fc.bedrock_runtime().meta.config
    cfg = base.merge(Config(max_pool_connections=int(pool)))
    assert_retries_disabled(cfg, where="burst client (merged onto awsclients' Config)")
    # A distinct client rather than the factory's cached one, built off the same session so
    # the region pin and the credentials are the same fact.
    return fc.session().client("bedrock-runtime", region_name=fc.region, config=cfg)


# ---------------------------------------------------------------------------
# a thread-safe evidence store, for the one case that is concurrent
# ---------------------------------------------------------------------------

class ConcurrentEvidenceStore(EvidenceStore):
    """`EvidenceStore`, with `add` serialised. Subclassed HERE rather than changed in lib.

    `EvidenceStore.add` does `self._seq += 1` and then writes `<seq>_<op>_<ok|err>.json`.
    That read-modify-write is three bytecodes and is not atomic, so two threads finishing
    inside the same interpreter tick take the SAME sequence number and one record
    overwrites the other — quietly, with both records claiming the same path. Every other
    case in this project is sequential (`phase1.run_arms` says so in its docstring), so
    this is unreachable outside F9-3 and correctly absent from lib.

    A subclass rather than a monkeypatch on the shared class: patching `EvidenceStore.add`
    would change the behaviour of every store in the process, including any created by a
    library this file imports, to fix a problem that only this file has.

    The lock covers the FILE WRITE ONLY. It is taken after the network call has returned,
    inside `capture`, so it costs a few hundred microseconds of serialisation per request
    and does not pace the burst — which would defeat the point of the burst.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._add_lock = threading.Lock()

    def add(self, rec: Record) -> Record:
        with self._add_lock:
            return super().add(rec)


# ---------------------------------------------------------------------------
# classification: exactly one bucket per response
# ---------------------------------------------------------------------------

def is_throttle(rec: Record) -> bool:
    """Did the quota refuse this request?

    Reads the error code AND the HTTP status. The status is checked because the code is the
    service's to choose: a 429 under a name `THROTTLE_CODES` has never seen would otherwise
    be counted as an unrelated error, and the "did we reach the quota" guard would then
    refuse a run that had in fact been throttled.
    """
    if rec.ok:
        return False
    if (rec.error_code or "") in THROTTLE_CODES:
        return True
    return rec.http_status == 429


def classify(rec: Record, *, expect_word: str,
             expect_action: str = EXPECT_ACTION) -> dict[str, Any]:
    """Put one response in exactly one bucket, and say why in the row.

    The reading is recorded per row, not just the bucket, because the interesting cell of
    this case is a bucket boundary: "200, no intervention, no wordPolicy" and "200,
    intervened, term reported" are one field apart and mean opposite things.
    """
    row: dict[str, Any] = {
        "ok": rec.ok,
        "http_status": rec.http_status,
        "error_code": rec.error_code or None,
        "error_class": rec.error_class or None,
        "request_id": rec.request_id,
        "evidence": rec.path,
        "duration_ms": rec.duration_ms,
        "throttled": is_throttle(rec),
    }

    if not rec.ok:
        row.update({
            "bucket": OBSERVABLE_FAILURE,
            "reading": ("the caller received an error, which is what the oracle's TRUE "
                        "branch requires of a refused request"),
            "action": None, "words_detected": [], "blocks_present": [],
        })
        return row

    asm = R.read_assessment(rec.response or {})
    detected = {w.casefold() for w in asm.words_detected}
    word_hit = expect_word.casefold() in detected
    block_present = POLICY_BLOCK in asm.blocks_present
    row.update({"action": asm.action, "words_detected": list(asm.words_detected),
                "blocks_present": list(asm.blocks_present),
                "text_units": dict(asm.text_units),
                "policy_block_present": block_present,
                "expected_word_reported": word_hit})

    if word_hit and asm.action == expect_action:
        row.update({"bucket": EVALUATED,
                    "reading": ("a real verdict: the word policy reported the configured "
                                "term and the action is the one the control established")})
    elif not word_hit and not block_present and asm.action == "NONE":
        row.update({"bucket": SILENT_PASS,
                    "reading": (
                        f"HTTP 200, action=NONE and no {POLICY_BLOCK} block, on text the "
                        f"control proved this guardrail intervenes on. The content went "
                        f"through UNEVALUATED — the oracle's FALSE")})
    else:
        row.update({"bucket": UNCLASSIFIED,
                    "reading": (
                        f"neither an evaluation nor a silent pass: action={asm.action!r}, "
                        f"expected_word_reported={word_hit}, {POLICY_BLOCK} "
                        f"{'present' if block_present else 'absent'}. A response nobody has "
                        f"read may not be folded into whichever bucket looks closest")})
    return row


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bucket counts, the throttle subset, and the intervals — over one arm."""
    counts = {b: sum(1 for r in rows if r["bucket"] == b) for b in BUCKETS}
    n = len(rows)
    n_throttled = sum(1 for r in rows if r["throttled"])
    n_other_failures = counts[OBSERVABLE_FAILURE] - n_throttled
    out: dict[str, Any] = {
        "n": n,
        "buckets": counts,
        "n_throttled": n_throttled,
        "n_observable_failures_not_throttles": n_other_failures,
        "failure_codes": sorted({r["error_code"] for r in rows
                                 if r["error_code"]}),
        "actions_seen": sorted({str(r.get("action")) for r in rows
                                if r.get("action") is not None}),
    }
    # Every rate reported as a proportion carries a Wilson interval from lib/stats.py, and
    # the informative bound differs per rate: for a count that should be ZERO the CEILING
    # is the result (0/480 silent passes bounds the silent-pass rate), and for a count that
    # should be positive the FLOOR is.
    if n:
        for key, x in (("throttle_rate", n_throttled),
                       ("evaluated_rate", counts[EVALUATED]),
                       ("silent_pass_rate", counts[SILENT_PASS])):
            ci = S.wilson_ci(x, n)
            out[key] = {"x": x, "n": n, "point": ci.point, "lo": ci.lo, "hi": ci.hi,
                        "method": ci.method, "level": ci.level}
    return out


# ---------------------------------------------------------------------------
# the two arms
# ---------------------------------------------------------------------------

def _rate(rows_timing: list[tuple[float, float]], n_sent: int) -> dict[str, Any]:
    """Achieved rate from the requests that were actually sent.

    `requests / (last end - first start)`, measured — never the intended rate. An intended
    300 rps that achieved 40 is the reason a zero-throttle result happens, and a payload
    that reported the intention would hide it.
    """
    if not rows_timing or n_sent <= 0:
        return {"n_sent": n_sent, "wall_s": 0.0, "achieved_rps": 0.0,
                "why": "no request was sent, so no rate was achieved"}
    t0 = min(t for t, _ in rows_timing)
    t1 = max(e for _, e in rows_timing)
    wall = max(t1 - t0, 1e-9)
    lat = sorted(e - t for t, e in rows_timing)
    return {
        "n_sent": n_sent,
        "wall_s": wall,
        "achieved_rps": n_sent / wall,
        "documented_rps_ceiling": DOCUMENTED_RPS,
        "over_documented_ceiling": (n_sent / wall) > (DOCUMENTED_RPS or 0),
        "latency_ms_p50": lat[len(lat) // 2] * 1000.0,
        "latency_ms_max": lat[-1] * 1000.0,
        "basis": "requests sent / (last response end - first request start), measured",
    }


def run_control(client, store: EvidenceStore, lim, *, gid: str, text: str,
                expect_word: str, n: int = N_CONTROL) -> dict[str, Any]:
    """The low-rate arm: serial, paced through the limiter, no concurrency.

    This is both the mutation's other arm AND the validation of the classifier. It must
    come back all-EVALUATED and un-throttled, and `decide` refuses the case if it does not:
    without it every unthrottled 200 in the burst looks like a silent pass and every silent
    pass looks like benign content.

    It keeps `lim.wait("ApplyGuardrail")`. The low rate comes from being serial — one
    in-flight request at ~0.4 s each is a couple of rps — and the limiter is what
    guarantees the arm cannot EXCEED the ceiling it is the control for.
    """
    rows: list[dict[str, Any]] = []
    timing: list[tuple[float, float]] = []
    waits_before = dict(lim.waits)
    for _ in range(n):
        lim.wait("ApplyGuardrail")
        t0 = time.monotonic()
        rec = capture(store, "apply_guardrail", client,
                      guardrailIdentifier=gid, guardrailVersion=GUARDRAIL_VERSION,
                      source="INPUT", outputScope=R.OUTPUT_SCOPE,
                      content=[{"text": {"text": text}}])
        timing.append((t0, time.monotonic()))
        rows.append({**classify(rec, expect_word=expect_word), "arm": "control"})
    return {
        "arm": "control", "rows": rows, "tally": tally(rows),
        "rate": _rate(timing, len(rows)),
        "paced_through_limiter": True,
        "limiter_waits_delta": _waits_delta(waits_before, lim.waits),
    }


def _waits_delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """How much the shared limiter slept, per operation, across one arm.

    Published for both arms because it is the AUDIT of the bypass: the control's
    `ApplyGuardrail` entry moves and the burst's must not. A future edit that accidentally
    paced the burst appears here as a non-zero delta beside a zero throttle count, instead
    of as an inexplicably clean result.
    """
    keys = set(before) | set(after)
    return {k: round(after.get(k, 0.0) - before.get(k, 0.0), 6)
            for k in sorted(keys)
            if abs(after.get(k, 0.0) - before.get(k, 0.0)) > 0}


def run_burst(client, store: EvidenceStore, lim, *, gid: str, text: str,
              expect_word: str, n: int = N_BURST, workers: int = BURST_WORKERS,
              deadline_s: float = BURST_DEADLINE_S,
              now=time.monotonic) -> dict[str, Any]:
    """The over-quota arm: `n` requests through `workers` threads, DELIBERATELY UNPACED.

    `lim.wait` is not called — see the module docstring on why that is the whole bypass and
    why it is legitimate here and nowhere else. `lim.waits` is snapshotted either side so
    the absence of pacing is a recorded observation rather than a claim.

    Bounded three ways: `n` requests, `workers` concurrent, and `deadline_s` seconds of
    offered load. Every task checks the deadline BEFORE calling AWS and returns without
    sending if it has passed, so the load stops on time even if the queue has not drained.
    A request already in flight may still be waiting on the read timeout inherited from
    `lib/awsclients.py`; the deadline bounds the LOAD, not the wall clock.

    One client, shared across threads: botocore clients are documented thread-safe, and one
    client is what makes the connection pool the pool the achieved rate is computed against.
    """
    rows: list[dict[str, Any]] = []
    timing: list[tuple[float, float]] = []
    lock = threading.Lock()
    n_skipped = 0
    waits_before = dict(lim.waits)
    t_start = now()
    deadline = t_start + float(deadline_s)

    def one(_i: int) -> None:
        nonlocal n_skipped
        if now() >= deadline:
            with lock:
                n_skipped += 1
            return
        t0 = time.monotonic()
        # No `lim.wait` here. That omission IS the bypass, and it is the only one.
        rec = capture(store, "apply_guardrail", client,
                      guardrailIdentifier=gid, guardrailVersion=GUARDRAIL_VERSION,
                      source="INPUT", outputScope=R.OUTPUT_SCOPE,
                      content=[{"text": {"text": text}}])
        t1 = time.monotonic()
        row = {**classify(rec, expect_word=expect_word), "arm": "burst"}
        with lock:
            rows.append(row)
            timing.append((t0, t1))

    with ThreadPoolExecutor(max_workers=int(workers)) as ex:
        list(ex.map(one, range(int(n))))

    return {
        "arm": "burst", "rows": rows, "tally": tally(rows),
        "rate": _rate(timing, len(rows)),
        "paced_through_limiter": False,
        "limiter_waits_delta": _waits_delta(waits_before, lim.waits),
        "n_planned": int(n),
        "n_skipped_after_deadline": n_skipped,
        "workers": int(workers),
        "deadline_s": float(deadline_s),
        "why_unpaced": (
            "the sealed method is 'drive ApplyGuardrail past its 100 rps quota'. Every "
            "other arm in this repo calls lim.wait so it never throttles; this one must, so "
            "it does not call it. RATE_LIMITS is not edited and the shared limiter is not "
            "patched — limiter_waits_delta shows it was not consulted"),
    }


# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------

def check_control(control: dict[str, Any]) -> None:
    """Refuse unless the control proves the probe text is intervened on. Mandatory.

    Three separate refusals, because the remedies differ and a single "control failed"
    would not say which. None of them is a verdict about the document: they say the
    instrument was not in a state to ask the question.
    """
    t = control["tally"]
    if not t["n"]:
        raise Refusal("the control arm sent no request, so nothing established that this "
                      "guardrail intervenes on the probe text at all")
    if t["n_throttled"]:
        raise Refusal(
            f"the control arm was throttled {t['n_throttled']}/{t['n']} times while paced "
            f"below the documented {DOCUMENTED_RPS} rps ceiling. The rate mutation cannot "
            f"be attributed to this script's own load when the baseline is already at the "
            f"ceiling — something else in this account is consuming the quota")
    if t["buckets"][EVALUATED] != t["n"]:
        raise Refusal(
            f"the control arm intervened on only {t['buckets'][EVALUATED]}/{t['n']} trials "
            f"(buckets {t['buckets']}, actions {t['actions_seen']}). The probe text MUST be "
            f"content this guardrail provably intervenes on when it is not throttled: "
            f"without that, an unthrottled 200 in the burst is indistinguishable from a "
            f"silent pass, and a silent pass is indistinguishable from benign content")


def decide(control: dict[str, Any], burst: dict[str, Any]) -> dict[str, Any]:
    """The trichotomy, the two mandatory guards, and the verdict they license.

    Returns the decision as data — `observed`, `inconclusive_because`, `mutation_inverted`
    — rather than emitting anything, so the whole rule is assertable offline.
    """
    cb, bb = control["tally"], burst["tally"]
    silent = bb["buckets"][SILENT_PASS]
    unclassified = bb["buckets"][UNCLASSIFIED]
    n_throttled = bb["n_throttled"]

    # Rate is the treatment: paced-and-serial vs unpaced-and-concurrent. The mutation
    # inverted iff the burst throttled and the control did not.
    mutation_inverted = bool(n_throttled > 0 and cb["n_throttled"] == 0)

    why: list[str] = []
    if not bb["n"]:
        why.append(
            "the burst sent 0 requests, so nothing was measured. This is a harness "
            "condition, not a result")
    if unclassified:
        why.append(
            f"{unclassified} burst response(s) fell in no bucket: neither an evaluation "
            f"nor a silent pass. A response nobody has read cannot be counted as either, "
            f"and the trichotomy is the whole instrument")
    if not n_throttled:
        rate = burst["rate"]
        why.append(
            f"0 of {bb['n']} burst requests were throttled at an ACHIEVED "
            f"{rate.get('achieved_rps', 0.0):.1f} rps against a documented "
            f"{DOCUMENTED_RPS} rps ceiling "
            f"(pool={burst.get('workers')}, p50 latency "
            f"{rate.get('latency_ms_p50', 0.0):.0f} ms). A run that was never throttled "
            f"proves nothing about throttling: '0 silent passes' is vacuously true of a "
            f"question that was never put, so this is NOT a TRUE")
    if not mutation_inverted:
        why.append(
            f"the rate mutation did not invert: control throttles={cb['n_throttled']}, "
            f"burst throttles={n_throttled}. If both arms behave the same way, the burst's "
            f"cleanliness is not attributable to the rate manipulation")

    # FALSE takes precedence over the guards, in one direction only: an OBSERVED silent
    # pass is a refutation whether or not the burst reached the quota, because content that
    # went through unevaluated did so regardless of why. It cannot be un-observed by a
    # precondition, and downgrading it to INCONCLUSIVE would suppress the one outcome this
    # case exists to be able to report.
    if silent:
        verdict_path = "false"
        observed = False
        inconclusive_because: list[str] = []
    elif why:
        verdict_path = "inconclusive"
        observed = False
        inconclusive_because = why
    else:
        verdict_path = "true"
        observed = True
        inconclusive_because = []

    return {
        "verdict_path": verdict_path,
        "observed": observed,
        "inconclusive_because": inconclusive_because,
        "mutation_inverted": mutation_inverted,
        "n_evaluated": bb["buckets"][EVALUATED],
        "n_observable_failures": bb["buckets"][OBSERVABLE_FAILURE],
        "n_throttled": n_throttled,
        "n_silent_pass": silent,
        "n_unclassified": unclassified,
        "control_throttled": cb["n_throttled"],
        "control_evaluated": cb["buckets"][EVALUATED],
        "rule": ("FALSE if any burst response was a silent pass; TRUE if none was AND the "
                 "burst was throttled at least once AND no response was unclassified AND "
                 "the rate mutation inverted; INCONCLUSIVE otherwise"),
    }


# ---------------------------------------------------------------------------
# front end
# ---------------------------------------------------------------------------

def plan(n_burst: int) -> list[tuple[str, str, int]]:
    return [
        ("control", f"constructed:1 text x {N_CONTROL} reps, paced", N_CONTROL),
        ("burst", f"constructed:1 text x {n_burst} reps, UNPACED", n_burst),
    ]


def estimated_cost_usd(n_calls: int) -> float:
    return n_calls * TEXT_UNITS_PER_CALL * USD_PER_TEXT_UNIT_UPPER_BOUND


def main(argv: list[str] | None = None) -> int:                          # noqa: C901
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)

    n_burst = min(args.n, N_BURST) if args.n else N_BURST
    is_smoke = args.n is not None
    n_total = N_CONTROL + n_burst

    if args.dry_run:
        # The retry assertion is exercised HERE TOO, on the Config the factory builds,
        # because a dry run is the last moment before the money is spent at which the
        # instrument can be checked. `_config` is read rather than a client being built:
        # constructing a client resolves credentials, which can reach the instance metadata
        # service, and this file must make no call of any kind on this path.
        cfg = A.ClientFactory(region=args.region)._config("bedrock-runtime")
        rv = assert_retries_disabled(cfg, where="dry run (awsclients' Config, unmerged)")
        return P.dry_run_banner(
            CASE, plan(n_burst),
            operations={"ApplyGuardrail": n_total},
            mutations=0, billable=True, blocks_per_call=1,
            text_units=n_total * TEXT_UNITS_PER_CALL,
            text_units_why=(
                f"one short content block per call, well under the 1,000-character text "
                f"unit, so {TEXT_UNITS_PER_CALL} unit per call over {n_total} calls"),
            extra=[
                f"guardrail: the provisioner's {GUARDRAIL_KEY!r} key at "
                f"{GUARDRAIL_VERSION} — an exact-match custom word list at "
                f"inputAction=BLOCK. Used READ-ONLY through ApplyGuardrail; 0 mutations, so "
                f"the residue is zero by construction and is still computed from the "
                f"created-vs-deleted two lists in a finally",
                f"RETRY CONFIG ASSERTED BEFORE ANY REQUEST: "
                f"mode={rv['mode']!r} effective_total_attempts="
                f"{rv['effective_total_attempts']}. A ThrottlingException is this case's "
                f"SETUP CONDITION, and botocore's transparent retry would re-drive it until "
                f"it succeeded — zero throttles observed, nothing concluded",
                f"the harness's OTHER retry layer is avoided by not using arms.run_arm: "
                f"checkpoint.RETRY_CODES contains ThrottlingException and would retry the "
                f"measurement away with linear backoff",
                f"THE LIMITER IS BYPASSED FOR THE BURST ARM ONLY, and by omission: the "
                f"burst does not call lim.wait. RATE_LIMITS is not edited and the shared "
                f"limiter is not patched. Ceiling "
                f"{DOCUMENTED_RPS} rps, provenance "
                f"{A.limit_provenance('ApplyGuardrail')!r} — bursting past a self_imposed "
                f"guess would have measured our own caution",
                f"BLAST RADIUS: the 100 rps ceiling is ACCOUNT-level per Region, so other "
                f"callers in this account (~$27k/mo of unrelated traffic) can be throttled "
                f"for the duration. Bounded by three named constants: {n_burst} requests "
                f"max, {BURST_WORKERS} concurrent, {BURST_DEADLINE_S}s of OFFERED LOAD. No "
                f"multi-minute burst is run",
                f"connection pool raised to {BURST_WORKERS} for the burst client only: "
                f"botocore's default of 10 would cap the offered rate at ~10/latency ~= 24 "
                f"rps, a quarter of the ceiling, and the burst would report zero throttles "
                f"while every thread looked busy. The ACHIEVED rate is recorded, never the "
                f"intended one",
                "FOUR buckets, exactly one per response: EVALUATED (term reported + the "
                "control's action) / OBSERVABLE FAILURE (rec.ok False; throttles counted as "
                "a named subset) / SILENT PASS (200, action NONE, no wordPolicy block) / "
                "UNCLASSIFIED (loud, and fatal to the verdict)",
                "the PRE-BURST CONTROL is mandatory and refuses the case if it does not "
                "intervene on every trial: without it an unthrottled 200 is "
                "indistinguishable from a silent pass, since a 200 with no intervention is "
                "the NORMAL response to benign content",
                "MANDATORY GUARD: 0 throttles => INCONCLUSIVE, never TRUE. '0 silent "
                "passes' over an unthrottled burst is vacuously true of a question never "
                "put. The guard reads the THROTTLE SUBSET of the failures, not the failures "
                "— 480 AccessDenied responses are observable failures that also never "
                "reached the quota",
                f"MUTATION (rate): control paced+serial expects 0 throttles and 100% "
                f"intervention; burst expects throttles. No inversion => INCONCLUSIVE. "
                f"O.mutation_is_mandatory({CASE!r}) is "
                f"{O.mutation_is_mandatory(CASE)}, so oracle.evaluate will not downgrade "
                f"on its own and this script does it explicitly",
                f"COST UPPER BOUND ~${estimated_cost_usd(n_total):.4f} for {n_total} "
                f"calls. USE1-Guardrail-WordPolicyUnitsConsumed exists on the bill "
                f"(results/FINDING-P0-PRICING.md) but has no verified price in "
                f"cost_model.yaml, so this is priced at the highest verified ApplyGuardrail "
                f"rate (${USD_PER_TEXT_UNIT_UPPER_BOUND}/unit, the content-policy unit) — a "
                f"bound, not a projection",
                f"this case answers no triaged claim row: O.family_of({CASE!r}) is "
                f"{O.family_of(CASE)!r}",
            ] + ([f"SMOKE RUN (--n {args.n}): {n_burst} burst requests almost certainly "
                  f"will not reach the quota, so the expected outcome is INCONCLUSIVE on "
                  f"the no-throttle guard. A smoke run's rate is never a result"]
                 if is_smoke else []))

    # ---- live from here -----------------------------------------------------------
    # The ledger, read rather than hardcoded. One testbed, one ledger, one run id: the
    # evidence for this case has to land in the same run directory as the rest of the
    # phase or `check_amendment_readiness.py` counts its replication days separately.
    state = T.State.load()
    run_id = args.run_id or state.run_id
    if args.region != state.region:
        print(f"FATAL: --region {args.region} but the ledger's testbed is in "
              f"{state.region}. The 100 rps quota is per-Region, so a burst in one Region "
              f"and a guardrail in another measure different quotas",
              file=sys.stderr)
        return 2

    man = P.manifest()
    words = P.configured_words(man)
    text = probe_text(words)
    word = expected_word(words)
    gid = P.guardrail(GUARDRAIL_KEY, man=man)

    fc = A.factory(args.region)
    store = ConcurrentEvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()
    lim = A.limiter()

    # Nothing is created by this case. The lists exist so the residue is computed from
    # created-vs-deleted rather than from the deletions alone, and so a later edit that
    # DOES create a probe guardrail inherits the teardown instead of needing one written.
    probes: list[P.ProbeGuardrail] = []
    deletions: list[dict[str, Any]] = []
    control: dict[str, Any] | None = None
    burst: dict[str, Any] | None = None
    refusal: str | None = None
    retry_asserted: dict[str, Any] = {}

    try:
        client = burst_client(fc, pool=BURST_WORKERS)
        retry_asserted = assert_retries_disabled(
            client.meta.config, where="live client, before the first request")
        print(f"\n{CASE}: retry config asserted before any request — "
              f"mode={retry_asserted['mode']!r} "
              f"attempts={retry_asserted['effective_total_attempts']} "
              f"pool={retry_asserted['max_pool_connections']}")
        print(f"  guardrail {gid} ({GUARDRAIL_KEY}/{GUARDRAIL_VERSION})   "
              f"probe text {text!r} ({len(text)} chars, 1 text unit)")
        print(f"  bounds: {N_CONTROL} control + {n_burst} burst requests, "
              f"{BURST_WORKERS} concurrent, {BURST_DEADLINE_S}s of offered load, "
              f"cost upper bound ${estimated_cost_usd(n_total):.4f}")

        print(f"\n  arm control  {N_CONTROL:>5d} requests  serial, PACED through the "
              f"limiter")
        control = run_control(client, store, lim, gid=gid, text=text,
                              expect_word=word, n=N_CONTROL)
        ct = control["tally"]
        print(f"    -> {ct['buckets'][EVALUATED]}/{ct['n']} evaluated, "
              f"{ct['n_throttled']} throttled, "
              f"{ct['buckets'][SILENT_PASS]} silent, "
              f"{control['rate']['achieved_rps']:.1f} rps achieved")
        check_control(control)

        print(f"\n  arm burst    {n_burst:>5d} requests  {BURST_WORKERS} threads, "
              f"UNPACED, {BURST_DEADLINE_S}s deadline")
        burst = run_burst(client, store, lim, gid=gid, text=text, expect_word=word,
                          n=n_burst, workers=BURST_WORKERS,
                          deadline_s=BURST_DEADLINE_S)
        bt = burst["tally"]
        print(f"    -> {bt['n']} sent ({burst['n_skipped_after_deadline']} skipped after "
              f"the deadline) at {burst['rate']['achieved_rps']:.1f} rps achieved "
              f"vs {DOCUMENTED_RPS} rps documented")
        for b in BUCKETS:
            print(f"       {b:20s} {bt['buckets'][b]:>5d}")
        print(f"       {'of which throttled':20s} {bt['n_throttled']:>5d}  "
              f"{bt['failure_codes']}")
    except Refusal as exc:
        refusal = str(exc)
        print(f"\nFATAL: {refusal}", file=sys.stderr)
    finally:
        # Teardown in a finally, unconditionally. Empty by design here — see above — and
        # the residue is still computed from BOTH lists, never from `deletions` alone: a
        # probe whose delete was never attempted contributes no row to that list, so a
        # residue derived from it reports zero survivors for exactly the case where one
        # exists.
        if probes:
            deletions = P.delete_probe_guardrails(fc.bedrock(), store, lim, probes)
        residue = P.probe_residue(probes, deletions)

    common: dict[str, Any] = {
        "run_id": run_id, "is_smoke": is_smoke,
        "aws_calls": (control["tally"]["n"] if control else 0)
                     + (burst["tally"]["n"] if burst else 0),
        "billable_calls": (control["tally"]["n"] if control else 0)
                          + (burst["tally"]["n"] if burst else 0),
        "billable_text_units": ((control["tally"]["n"] if control else 0)
                                + (burst["tally"]["n"] if burst else 0))
                               * TEXT_UNITS_PER_CALL,
        "mutations": 0,
        "estimated_cost_usd_upper_bound": estimated_cost_usd(
            (control["tally"]["n"] if control else 0)
            + (burst["tally"]["n"] if burst else 0)),
        "cost_basis": (
            f"one text unit per call at ${USD_PER_TEXT_UNIT_UPPER_BOUND}/unit — the "
            f"VERIFIED content-policy rate from cost_model.yaml, used as an UPPER BOUND "
            f"because USE1-Guardrail-WordPolicyUnitsConsumed exists on the bill "
            f"(results/FINDING-P0-PRICING.md) with no verified price. A five-decimal "
            f"figure from memory is how this project's cost model was once wrong by 5x"),
        "bounds": {"n_control": N_CONTROL, "n_burst_max": n_burst,
                   "n_total_max": n_total, "workers": BURST_WORKERS,
                   "offered_load_deadline_s": BURST_DEADLINE_S,
                   "why_bounded_by_constants": (
                       "the 100 rps ApplyGuardrail ceiling is ACCOUNT-level per Region, so "
                       "the burst can throttle unrelated callers in an account carrying "
                       "~$27k/mo of other traffic. A loop that ran until a throttle "
                       "appeared would have no bound at all")},
        "retry_config_asserted_before_first_request": retry_asserted,
        "why_the_retry_assertion_exists": (
            "botocore's standard/adaptive retry re-drives a throttled request until it "
            "succeeds, so a throttled run would report zero throttles and this case would "
            "conclude nothing while every number looked right. The setting is INHERITED "
            "from lib/awsclients.ClientFactory._config (total_max_attempts=1) by merging "
            "onto its Config rather than restated here — a copy could not detect a drift "
            "in the original — and it is asserted before the first request, not after"),
        "second_retry_layer_avoided": (
            "checkpoint.RETRY_CODES contains ThrottlingException and arms.run_arm retries "
            "through it with linear backoff. Right for every arm whose throttle is an "
            "accident; fatal to the one arm whose throttle IS the measurement. This case "
            "therefore calls evidence.capture directly and does not use run_arm"),
        "limiter_bypass": {
            "operation": "ApplyGuardrail",
            "documented_rps": DOCUMENTED_RPS,
            "provenance": A.limit_provenance("ApplyGuardrail"),
            "how": ("the burst arm does not call lim.wait. RATE_LIMITS is not edited, "
                    "awsclients._LIMITER is not patched, and no shared object is mutated: "
                    "pacing in this platform is opt-in per call site, so declining to opt "
                    "in is the entire mechanism"),
            "why_legitimate_here": (
                "F9-3's sealed method is 'drive ApplyGuardrail past its 100 rps quota'. "
                "The ceiling is aws_documented, so exceeding it measures the SERVICE; six "
                "entries in RATE_LIMITS are self_imposed guesses and bursting past one of "
                "those would have measured our own caution"),
            "why_nowhere_else": (
                "every other case wants the opposite. A throttle inside an F2-5 "
                "determinism arm would add an invisible multi-second tail to one trial's "
                "wall clock and be published as a latency observation, and "
                "phase1.run_arms is sequential for the same reason"),
            "audit": {"control_waits_delta": (control or {}).get("limiter_waits_delta"),
                      "burst_waits_delta": (burst or {}).get("limiter_waits_delta"),
                      "reading": ("the control's ApplyGuardrail entry moves and the "
                                  "burst's must be absent. A future edit that accidentally "
                                  "paced the burst appears here as a non-zero delta beside "
                                  "a zero throttle count")},
        },
        "concurrency": {
            "workers": BURST_WORKERS,
            "max_pool_connections": retry_asserted.get("max_pool_connections"),
            "why_the_pool_was_widened": (
                "botocore's default max_pool_connections is 10. 96 threads sharing 10 "
                "connections offer ~10/latency ~= 24 rps against this project's p50 "
                "ApplyGuardrail latency — a quarter of the ceiling — so the burst would "
                "report zero throttles while every thread looked busy. Widened on THIS "
                "client only, by merging onto the factory's Config; the factory's cached "
                "client, which every other case uses, is untouched"),
            "evidence_store_is_subclassed_not_patched": (
                "EvidenceStore.add does a non-atomic `self._seq += 1` and then writes "
                "<seq>_<op>.json, so two threads can take the same sequence number and one "
                "record silently overwrites the other. Serialised in a LOCAL SUBCLASS "
                "(ConcurrentEvidenceStore) rather than by patching the shared class, and "
                "the lock covers the file write only — taken after the network call has "
                "returned, so it does not pace the burst"),
        },
        "guardrail": {"key": GUARDRAIL_KEY, "guardrail_id": gid,
                      "version": GUARDRAIL_VERSION,
                      "purpose": (man.get("guardrails") or {})
                      .get(GUARDRAIL_KEY, {}).get("purpose", ""),
                      "read_only": True,
                      "why_a_word_filter": (
                          "the control must be DETERMINISTIC. An exact-match custom word "
                          "either appears or it does not; a content filter has a "
                          "confidence threshold to land the wrong side of, and a control "
                          "that intervened on 11 of 12 trials would refuse this case for a "
                          "reason unrelated to throttling")},
        "probe": {"text": text, "chars": len(text), "expected_word": word,
                  "expected_action": EXPECT_ACTION,
                  "words_from_manifest": words,
                  "why_not_a_literal": (
                      "phase1.configured_words reads the provisioned list. A term typed "
                      "here that disagreed with the guardrail would produce a control that "
                      "never intervenes, and the case would refuse for the wrong reason")},
        "residue": residue,
        "creates_nothing": (
            "no guardrail, policy, gateway or role. The subject is the provisioner's "
            "existing `words` guardrail used read-only through ApplyGuardrail, so residue "
            "is zero by construction — and it is still computed from the created-vs-deleted "
            "two lists in a finally, so an edit that does create something inherits the "
            "teardown"),
        "instrument": {"operation": "ApplyGuardrail", "source": "INPUT",
                       "output_scope": R.OUTPUT_SCOPE, "blocks_per_call": 1,
                       "policy_block_read": POLICY_BLOCK,
                       "sdk": A.sdk_versions()},
        "no_claim_row": (
            f"O.family_of({CASE!r}) is {O.family_of(CASE)!r}: the seal assigns this case no "
            f"triaged document claim row. Recorded rather than omitted, because a case that "
            f"answers no claim must be visible as such"),
    }

    # ---- the refusal path: the instrument was not in a state to ask the question ----
    if refusal is not None or control is None or burst is None:
        reason = refusal or ("the arms did not complete, so no response was classified")
        rec = O.not_measured(CASE, reason,
                             control=(control or {}).get("tally"),
                             burst=(burst or {}).get("tally"))
        P.emit(CASE, rec, {
            **common,
            "why_inconclusive": (
                "a precondition failed. This is a statement about the instrument, never "
                "about the document: an unvalidated classifier cannot tell a silent pass "
                "from benign content, and reporting either way would be a guess"),
            "verdict_rule": ("no verdict is computed when the control does not establish "
                             "that the guardrail intervenes on the probe text"),
            "verdict_reading": reason,
            "what_true_does_not_prove": "nothing was measured, so nothing is claimed",
            "why_this_matters_operationally": (
                "the failure mode this case exists to detect — a throttle that lets "
                "content through unevaluated — remains unmeasured, so a reader must not "
                "treat the absence of a FALSE here as reassurance"),
            "expiry": ("a statement about a quota's behaviour on one day; quotas and their "
                       "enforcement change without notice"),
        }, store)
        # rc=2: nothing was measured. Not rc=1 — the buckets are not in disagreement, the
        # instrument never reached them.
        return 2

    d = decide(control, burst)

    o = P.obs_existence(
        CASE, d["observed"],
        # `n` is the burst's classified responses: the denominator the trichotomy was
        # evaluated over. The control's 12 are the mutation's other arm and are reported
        # separately rather than pooled — they are a different treatment.
        n=burst["tally"]["n"],
        reading=("every burst response classified into exactly one of EVALUATED / "
                 "OBSERVABLE FAILURE / SILENT PASS / UNCLASSIFIED; TRUE requires zero "
                 "silent passes, zero unclassified, at least one throttle, and an inverted "
                 "rate mutation"),
        buckets=burst["tally"]["buckets"],
        n_throttled=d["n_throttled"],
        n_silent_pass=d["n_silent_pass"],
        n_unclassified=d["n_unclassified"],
        achieved_rps=burst["rate"]["achieved_rps"],
        documented_rps=DOCUMENTED_RPS,
        control_evaluated=d["control_evaluated"],
        control_throttled=d["control_throttled"],
        verdict_path=d["verdict_path"],
        inconclusive_because=d["inconclusive_because"])
    # An ATTRIBUTE, never a **detail keyword: `phase1._detail` refuses an Observation field
    # name passed as detail, because the value would land where the decision rule never
    # looks and the field would keep its default.
    o.mutation_inverted = d["mutation_inverted"]

    if d["verdict_path"] == "inconclusive":
        # `evaluate` on this observation would return FALSE — EXISTENCE reads
        # `observed_bool`, which is False whenever the conjunction does not hold — and FALSE
        # is exactly the wrong answer: "a throttle silently allowed content through" is not
        # what an unthrottled burst observed. Neither of `evaluate`'s branches fits a
        # question that was never put, so this path uses `O.not_measured`, which produces an
        # INCONCLUSIVE record in `evaluate`'s shape. F9-3's mutation is not sealed mandatory,
        # so `evaluate` would not have downgraded anything on its own either.
        rec = O.not_measured(
            CASE, "; ".join(d["inconclusive_because"]),
            buckets=burst["tally"]["buckets"],
            achieved_rps=burst["rate"]["achieved_rps"],
            documented_rps=DOCUMENTED_RPS,
            mutation_inverted=d["mutation_inverted"])
    else:
        rec = O.evaluate(o)

    payload = {
        **common,
        "decision": d,
        "control_arm": {k: v for k, v in control.items() if k != "rows"},
        "burst_arm": {k: v for k, v in burst.items() if k != "rows"},
        # Rows, capped. The full per-call record — params, response, request id, headers —
        # is in the evidence tree; these are the classified readings an analysis needs
        # without reopening several hundred files. Every non-EVALUATED row is kept
        # whatever the cap, because those are the ones a reader will want to see.
        "rows_interesting": [r for r in control["rows"] + burst["rows"]
                             if r["bucket"] != EVALUATED],
        "rows_evaluated_sample": [r for r in burst["rows"]
                                  if r["bucket"] == EVALUATED][:10],
        "n_rows_total": len(control["rows"]) + len(burst["rows"]),
        "buckets_definition": {
            EVALUATED: ("HTTP 200 carrying a real verdict: the wordPolicy block reported "
                        "the configured term and the action is the one the control "
                        "established"),
            OBSERVABLE_FAILURE: ("rec.ok is False — a ThrottlingException, a 429, a "
                                 "timeout: any failure the CALLER can see. Throttles are "
                                 "counted as a named subset"),
            SILENT_PASS: (f"HTTP 200, action NONE, and NO {POLICY_BLOCK} block, on text the "
                          f"control proved this guardrail intervenes on. The content went "
                          f"through unevaluated"),
            UNCLASSIFIED: ("anything else. Loud and fatal to the verdict rather than "
                           "folded into whichever neighbouring bucket looks close"),
            "why_the_empty_assessments_list_is_not_the_test": (
                "assessments[] is never empty even at action=NONE — it carries "
                "appliedGuardrailDetails and invocationMetrics regardless — so 'no "
                "assessment' here means 'no wordPolicy block'. Classifying on the empty "
                "list would put every silent pass into EVALUATED"),
        },
        "mutation": {
            "treatment": "request rate",
            "control_arm": (f"{N_CONTROL} requests, serial, paced through the limiter; "
                            f"expects 0 throttles and 100% intervention"),
            "burst_arm": (f"{burst['tally']['n']} requests, {BURST_WORKERS} threads, "
                          f"unpaced; expects throttles to appear"),
            "control_throttled": d["control_throttled"],
            "burst_throttled": d["n_throttled"],
            "inverted": d["mutation_inverted"],
            "sealed_as_mandatory": O.mutation_is_mandatory(CASE),
            "why_recorded_anyway": (
                "the seal does not make this case's mutation mandatory, so oracle.evaluate "
                "does not consult it. Without it, a clean burst is indistinguishable from a "
                "burst that never loaded the service: the control is what makes the rate "
                "manipulation the thing that changed"),
        },
        "verdict_rule": d["rule"],
        "verdict_reading": (
            f"{d['n_evaluated']} of {burst['tally']['n']} burst responses carried a real "
            f"verdict, {d['n_observable_failures']} were observable failures "
            f"({d['n_throttled']} of them throttles), and {d['n_silent_pass']} were silent "
            f"passes, at an ACHIEVED {burst['rate']['achieved_rps']:.1f} rps against a "
            f"documented {DOCUMENTED_RPS} rps ceiling. "
            + ("A silent pass was observed: content reached no evaluation and the caller "
               "was told nothing" if d["n_silent_pass"] else
               "No response returned 200 without being evaluated"
               if d["verdict_path"] == "true" else
               "The question was not put: " + "; ".join(d["inconclusive_because"]))),
        "what_true_does_not_prove": [
            "that an APPLICATION using this API fails closed. This measures what "
            "ApplyGuardrail returns to its caller. Whether the caller then treats the "
            "exception as a block, or logs it and forwards the content anyway, is a "
            "property of the integration and is invisible from here",
            "anything about the gateway data path or InvokeGuardrailChecks. Both are "
            "different transports with their own quotas, and neither is exercised",
            f"anything about sustained load. The offered load was bounded to "
            f"{BURST_DEADLINE_S}s because the ceiling is account-level and this account "
            f"carries unrelated traffic; a longer burst could behave differently, and this "
            f"run says nothing about it",
            "that the 100 rps figure is correct. The achieved rate is measured and "
            "reported, but this design detects a throttle — it does not locate the "
            "threshold, which would need a rate ladder",
        ],
        "why_this_matters_operationally": (
            "fail-secure is the whole reason a guardrail is in the request path. If a "
            "throttle returned 200 with no assessment, every caller that checks `action` "
            "would read the response as clean and forward unevaluated content — a bypass "
            "that appears under LOAD, which is exactly when it matters and exactly when "
            "nobody is reading logs. The operational consequence of TRUE is the opposite "
            "and just as concrete: at 100 rps the guardrail becomes an availability "
            "dependency, so the integration needs an explicit throttle path (queue, shed, "
            "or deny) rather than a try/except that logs and continues"),
        "expiry": (
            "a statement about one account, one Region and one day. Service quotas and "
            "their enforcement change without notice and can be raised on request, so "
            "this observation dates from its run and a change belongs in "
            "AWS-BEHAVIOR-CHANGES.md rather than silently replacing it"),
    }
    P.emit(CASE, rec, payload, store)

    if not residue["clean"]:
        print(f"FATAL: residue survived teardown: {residue['surviving']}", file=sys.stderr)
        return 2
    if d["n_unclassified"]:
        # rc=1, the unclassified exit: the run happened and produced responses this file
        # cannot place. Distinct from rc=2 (nothing measured) and from rc=0 (a clean run,
        # whatever the verdict).
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
