#!/usr/bin/env python3
"""Account-field masking for everything written into `results/`.

Why this module exists, and why it is not two edits at two call sites
--------------------------------------------------------------------
`ApplyGuardrail` returns `assessments[].appliedGuardrailDetails.guardrailArn`, and
`GetGuardrail` returns `crossRegionDetails.guardrailProfileArn`. Both embed the account
ID. Both are *load-bearing evidence*: F8-6's entire instrument is the Region field of
that ARN, so the answer cannot be "stop recording it".

The first live Phase 1 run therefore wrote the account ID into **82 files and 1,122
lines** under `results/`, and the redaction gate caught it — correctly, and only after
the fact. Hand-editing those files would have been the second-instance defect in
`feedback_second_instance_bugs`: the next run, and every run after it, re-creates them,
because the leak is not in the files but in the path that writes them.

So the mask is applied at the **two writers into `results/`** — `Checkpoint.save()` and
`phase1.emit()` — rather than at the call sites that happen to read an ARN today. A new
case that records a new ARN-bearing field inherits the mask without knowing it exists,
which is the only version of this that survives a case being added by someone who has
not read this file.

`evidence/` is deliberately NOT masked
--------------------------------------
The evidence tree is the local audit archive whose whole purpose is that a claim can be
taken to AWS Support and looked up (see `evidence.py`'s docstring). A masked ARN there
would defeat that. It is excluded from the redaction gate by directory, and that
exclusion is now stated as a decision in `check_redaction.py` rather than looking like an
oversight — the gate's own docstring previously claimed to scan "JSON evidence" while
`SKIP_DIRS` excluded it, which is exactly the kind of contradiction that gets resolved in
the wrong direction later.

What is preserved, deliberately
-------------------------------
The ARN keeps its six-colon shape and every other field: partition, service, Region,
resource type and resource id all survive, and only the account field is replaced by
`ACCOUNT_PLACEHOLDER`.

No example ARN is written out here. An earlier draft of this docstring spelled one with a
literal twelve-digit account field to be illustrative, and thereby created two fresh
redaction findings *inside the module whose job is to prevent them* — the same mistake
`check_redaction.py`'s own ALLOW comment records making. The round trip is asserted in
`lib/tests/test_redact.py` instead, where a fixture is data rather than prose.

`f8_regional/05_xregion.py`'s `region_of`/`partition_of` read `parts[3]`/`parts[1]` of a
`split(":")`, so field *positions* must not move. A mask that dropped the field would
shift the Region into the account slot and silently re-label every trial's serving
Region — turning a redaction fix into a data corruption. Verified by test: masking is
idempotent and leaves `region_of` and `partition_of` unchanged.

A second class of identifier, added later and for a measured reason
------------------------------------------------------------------
The account ID was the only thing this module masked until 2026-08-14, when F5-7b — the
first and only case in the project that BUILDS A VPC — wrote 31 VPC-family ids into
`results/phase1/F5-7b.json`. `phase1.emit()` had masked that file correctly all along;
the masker simply had no rule for the class. See `register_resource_id`, which is opt-in
per producer, so no case that does not create infrastructure is affected by it at all.

The lesson generalises past this module: a test that asserts a write is *wrapped* in a
masker (`lib/tests/test_results_writes_are_masked.py`) and a gate that reads the *bytes*
(`check_redaction.py`) do not overlap, and what lives in the gap is precisely "an
identifier shape the masker does not cover". The gate has to stay the backstop.
"""

from __future__ import annotations

import re
from typing import Any

# The account field of an ARN: the 5th colon-delimited field. Anchored on the four
# fields before it rather than on `\b\d{12}\b` alone, so a 12-digit corpus fixture or a
# UUID tail elsewhere on the same line is not touched — this function's job is ARNs, and
# a broader substitution would corrupt PII corpus rows on their way into a checkpoint.
#
# The account field is optional-and-empty in some services' ARNs (S3), so `\d{12}` is
# matched rather than `[^:]*`: an already-empty field is left exactly as it is.
_ARN_ACCOUNT = re.compile(
    r"(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)(\d{12})(:)")

ACCOUNT_PLACEHOLDER = "<account>"

# An ARN whose account field was CUT SHORT by a length-based slice upstream. Measured
# 2026-08-12 in `results/phase1/F3-10.json`: a sample log message truncated to 400 characters
# ended inside the account field of a `policyEngineArn`, leaving eleven of the live account's
# twelve digits — invisible to `_ARN_ACCOUNT` because that pattern requires all twelve followed
# by `:`. (Written without the offending string: quoting it here is what put two findings in
# this module on the first attempt at documenting it, the same mistake `check_redaction.py`'s own
# ALLOW comment records making. The literal is reconstructed from halves in
# `lib/tests/test_redact.py`, where it is data rather than prose.)
#
# Shape-based and registry-free, like `_ARN_ACCOUNT` and for the same reason: it must protect an
# account nobody registered. It is safe to be registry-free ONLY because of the anchoring — the
# four ARN fields must precede it, and `(?![\d:])` means a complete account field (which always
# has `:` after it) is left to `_ARN_ACCOUNT`. Nothing outside ARN position can match.
_ARN_ACCOUNT_TRUNCATED = re.compile(
    r"(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)(\d{1,12})(?![\d:])")

# What replaces the resource field of an ARN that was cut off mid-identifier. The masker does not
# only remove the digits, it RESTORES THE SIX-COLON SHAPE, because the redaction gate's ARN excuse
# decomposes a line with `arn:aws[a-z-]*:[^:\s]*:[^:\s]*:([^:\s]*):` and therefore requires the
# colon that terminates the account field. Without it the gate counts fewer decomposable ARNs than
# it detected and fails CLOSED — correctly, since it cannot tell a masked truncation from a
# truncated identifier — and a fully-masked artifact would need a waiver to ship. Restoring the
# shape is the fix that keeps the gate strict: `check_redaction.py` still refuses any account
# field that is not exactly `ACCOUNT_PLACEHOLDER`, and the marker says plainly that a resource id
# was lost to the slice rather than pretending one was there.
ARN_TRUNCATED_PLACEHOLDER = "<truncated>"

# A field whose NAME says it holds an account ID, whose value was cut short the same way. The
# same 400-character slice also produced `"account_id":"67720` — 5 of 12 digits, in no ARN. This
# one IS registry-gated: unlike ARN position, a field called `account_id` could legitimately hold
# a synthetic 12-digit value (the `US_BANK_ACCOUNT_NUMBER` corpus is the live example this
# module's docstring already refuses to break), so only a prefix of an ID this process actually
# resolved is masked.
_ACCOUNT_FIELD = re.compile(
    r"(\\?\"?(?:aws[._])?account[._]?id\\?\"?\s*[:=]\s*\\?\"?)(\d{1,12})(?!\d)",
    re.IGNORECASE)

# How many leading digits of a registered account ID count as a disclosure worth masking, when
# the position itself already says the value IS an account ID — ARN field 5, or a field named
# `account_id`. Four is short enough to catch the `"account_id":"67720` case measured on
# 2026-08-12; a shorter floor would mask one- and two-digit tails that carry no identifying
# information.
_MIN_TRUNCATED_PREFIX = 4

# The floor for the UNANCHORED rule — a prefix at the end of a string, in no particular field.
# It has to be much higher, and the first draft of this module proved why: at 4 it masked the
# string `"n":6772`, because that ends with the account's first four digits after a non-digit.
# `mask()` walks every string leaf of every checkpoint row, so an over-match there silently
# corrupts recorded data, which is worse than a partial disclosure of four digits. Eight of
# twelve digits is still a real disclosure, and an unrelated standalone number ending in exactly
# those eight is not a case worth trading data integrity for.
_MIN_UNANCHORED_PREFIX = 8

# The account IDs this process has been told about, masked as bare tokens as well as in ARN
# position. See `register_account_id`.
_KNOWN: set[str] = set()


def register_account_id(account_id: str) -> None:
    """Teach the mask one account ID, so it is masked OUTSIDE ARN position too.

    Why a registry rather than widening `_ARN_ACCOUNT`
    -------------------------------------------------
    Measured 2026-08-12: the redaction gate found the account ID in `results/phase1/F7-1.json`
    and `F7-2.json`, inside a CloudWatch dimension value — `ProviderName` on
    `ResourceAccessTokenFetchSuccess`, naming another team's OAuth2 credential provider in the
    same account, whose *name* embeds the account ID. That is not an ARN and no ARN-anchored
    pattern can reach it. F7's whole instrument is a namespace-wide enumeration of a SHARED
    namespace, so the general form of this leak is: any resource name any other team chose can
    arrive in our results, and resource names are free text.

    The obvious widening — mask every `\\b\\d{12}\\b` — is the one this module's docstring
    already rejects, and for a live reason: a PII corpus fixture whose entity type IS a
    12-digit number (`US_BANK_ACCOUNT_NUMBER`) comes back on checkpoint rows, and masking it
    would destroy the record of which fixture was sent. Masking only IDs this process has
    actually resolved is narrow enough to leave corpus content alone and wide enough to cover
    a name nobody anticipated. The sealed corpora were checked for the live account ID at the
    time of writing and do not contain it; `lib/tests/test_redact.py` keeps that check honest.

    Registration is a side effect of `awsclients.account_id()`, which is the only place the ID
    is resolved (enforced by `lib/tests/test_account_id_choke_point.py`), so a new case
    inherits the mask without knowing this function exists — the same property the two-writer
    design gives ARN masking. Unregistered is fail-OPEN, which is why the gate stays the
    backstop: it is what caught this.
    """
    if not account_id or not account_id.isdigit() or len(account_id) != 12:
        raise ValueError(f"account_id must be 12 digits, got {account_id!r}")
    _KNOWN.add(account_id)


def known_account_ids() -> frozenset[str]:
    """The registered account IDs. For tests and for reporting what the mask can see."""
    return frozenset(_KNOWN)


# ---------------------------------------------------------------------------------------------
# ephemeral infrastructure ids
# ---------------------------------------------------------------------------------------------
# The id families this registry accepts. Deliberately WIDER than the redaction gate's
# `vpc-or-subnet-id` pattern, which covers only vpc/subnet/sg/eni: a producer that creates an
# internet gateway, a NAT gateway, a route table and an Elastic IP discloses those ids in exactly
# the same way, and masking only the four the gate happens to check is tuning the fix to the
# tripwire rather than to the disclosure. `ela-attach` is here because an AgentCore VPC runtime's
# ENI carries a service-owned attachment id (measured 2026-08-14, F5-7b §5).
_RESOURCE_ID = re.compile(
    r"^(vpc|subnet|sg|eni|igw|nat|rtb|eipalloc|acl|ela-attach)-[0-9a-f]{8,17}$")

# The placeholder KEEPS THE FAMILY PREFIX and numbers within it, for the same reason
# `ACCOUNT_PLACEHOLDER` keeps the ARN's six-colon shape: the evidence has to stay readable. A
# residue block saying `DependencyViolation: The subnet <redacted-2> has dependencies` still tells
# a reader which resource kind blocked the teardown and that it was the second subnet registered,
# which is the whole content of the observation. Collapsing every id to one opaque token would
# make a two-subnet topology indistinguishable from a one-subnet one.
#
# Contains no hex, so masking is idempotent: a second pass finds no registered id to replace.
_KNOWN_RESOURCES: dict[str, str] = {}
_RESOURCE_COUNTS: dict[str, int] = {}


def register_resource_id(resource_id: str) -> str:
    """Teach the mask one ephemeral infrastructure id, and return its placeholder.

    Why a registry, and why this is not a shape-based pattern
    --------------------------------------------------------
    Measured 2026-08-14: `results/phase1/F5-7b.json` shipped **31 unredacted identifiers** — a
    VPC, two subnets, a security group and an ENI — and `phase1.emit()` had masked it correctly
    the whole time. The leak was not a missing mask call. It was that `mask_text` had no rule for
    this class of value, because until F5-7b no case in the project had ever created an EC2
    network resource. `lib/tests/test_results_writes_are_masked.py` passed, because it asserts the
    write is WRAPPED in a masker; the gate failed, because it reads the bytes. The gap between
    those two is exactly "a class of identifier the masker does not know about", and this function
    is the general form of the fix rather than a hand-edit of one file.

    Registry-gated, not shape-based, and the reason is the mirror of `register_account_id`'s. A
    shape rule like `\\b(?:vpc|subnet)-[0-9a-f]{8,17}\\b` would be safe from corpus collisions —
    no PII fixture looks like that — but it would also mask ids this process never created,
    including the runner's OWN network ids, which several scripts print deliberately so that a
    human can confirm the deny-list resolved to the right VPC (`resolve_forbidden()`). Masking
    those would turn a safety printout into an unreadable one. Only ids a producer registers —
    i.e. ids it created and is responsible for destroying — are masked.

    Unregistered is fail-OPEN, exactly as for accounts, which is why the gate stays the backstop:
    the gate is what caught this, and a registry that silently covered nothing would look
    identical to one that worked.
    """
    if not _RESOURCE_ID.match(resource_id or ""):
        raise ValueError(
            f"not an ephemeral infrastructure id: {resource_id!r}. Expected one of "
            f"vpc/subnet/sg/eni/igw/nat/rtb/eipalloc/acl/ela-attach followed by 8-17 hex digits. "
            f"Registering an arbitrary string would let a caller mask anything, including "
            f"evidence.")
    if resource_id in _KNOWN_RESOURCES:
        return _KNOWN_RESOURCES[resource_id]
    kind = resource_id.rsplit("-", 1)[0]
    _RESOURCE_COUNTS[kind] = _RESOURCE_COUNTS.get(kind, 0) + 1
    placeholder = f"{kind}-<redacted-{_RESOURCE_COUNTS[kind]}>"
    _KNOWN_RESOURCES[resource_id] = placeholder
    return placeholder


def known_resource_ids() -> dict[str, str]:
    """The registered ephemeral ids and their placeholders. For tests and for reporting."""
    return dict(_KNOWN_RESOURCES)


def reset_resource_ids() -> None:
    """Forget every registered ephemeral id.

    For tests only. Account registration has no equivalent because an account ID is a property of
    the whole process, while these ids belong to one run of one case and a test that registers a
    fixture must not leak it into the next test's assertions.
    """
    _KNOWN_RESOURCES.clear()
    _RESOURCE_COUNTS.clear()


def mask_text(s: str) -> str:
    """Replace the account field of every ARN in `s`, and every registered account ID.

    Idempotent: the placeholder contains no digits, so a second pass finds nothing to
    replace. The bare-token pass is anchored on `\\b` at both ends, so a 12-digit account ID
    embedded in a longer digit run is left alone — such a run is not an account reference.

    A TRUNCATED ACCOUNT ID IS STILL AN ACCOUNT ID
    ---------------------------------------------
    Measured 2026-08-12: `results/phase1/F3-10.json` shipped a `policyEngineArn` whose account
    field held the live account ID with its last digit cut off, and beside it a field named
    `account_id` holding the first five. Neither pass above could see either one: the ARN pattern
    requires exactly 12 digits followed by `:`, and the bare-token pass requires all 12 with a
    word boundary after them. (Both strings are reconstructed from halves in
    `lib/tests/test_redact.py` and are deliberately not quoted here — see
    `_ARN_ACCOUNT_TRUNCATED`.)

    The cause was upstream and is fixed there too — `_app_logs` truncated each sample log
    message to 400 characters BEFORE the mask ran, and the slice landed inside the account
    field (`feedback_cut_counts_bytes`: a length-based slice knows nothing about what it is
    cutting). But a masker that only works on untruncated input is a masker whose correctness
    depends on every caller's slicing, so the tail case is handled here as well.

    Three rules, each anchored on something other than the digits themselves, because a bare
    "mask any short digit run" would corrupt corpus rows and timestamps:

      * `_ARN_ACCOUNT_TRUNCATED` — ARN position, registry-free. Shape alone identifies it, and
        the substitution also restores the colon the slice removed, so the result is a
        well-formed masked ARN rather than a fragment the redaction gate must fail closed on
        (see `ARN_TRUNCATED_PLACEHOLDER`).
      * `_ACCOUNT_FIELD` — a field NAMED account id, registry-gated, since such a field can
        legitimately hold a synthetic value.
      * end of string, registry-gated — for the case where the whole string IS the truncated
        tail. This one is what `mask()` needs, since that walk masks each string leaf
        separately; a whole-file `mask_text` will usually be served by the two above instead.

    All three require the digits not to be preceded by another digit (or, in the ARN and field
    cases, to sit exactly where an account ID sits), so a longer number that merely happens to
    start with the same digits cannot match.
    """
    out = _ARN_ACCOUNT.sub(rf"\g<1>{ACCOUNT_PLACEHOLDER}\g<3>", s)
    out = _ARN_ACCOUNT_TRUNCATED.sub(
        rf"\g<1>{ACCOUNT_PLACEHOLDER}:{ARN_TRUNCATED_PLACEHOLDER}", out)
    for aid in _KNOWN:
        if aid in out:
            out = re.sub(rf"\b{aid}\b", ACCOUNT_PLACEHOLDER, out)
        out = _ACCOUNT_FIELD.sub(
            lambda m: (m.group(1) + ACCOUNT_PLACEHOLDER) if aid.startswith(m.group(2))
            else m.group(0), out)
        # Longest prefix first: masking `6772` before `67720713284` would leave digits behind.
        for k in range(len(aid) - 1, _MIN_UNANCHORED_PREFIX - 1, -1):
            head = aid[:k]
            if out.endswith(head) and not out[:-k][-1:].isdigit():
                out = out[:-k] + ACCOUNT_PLACEHOLDER
                break
    # Registered ephemeral infrastructure ids. Longest first, so that if one registered id is ever
    # a prefix of another the longer substitution happens before the shorter one can strand a tail
    # — the same ordering rule, and for the same reason, as the truncated-account loop above.
    # Plain `str.replace` rather than a regex: these are complete ids, and the placeholder carries
    # no hex, so there is nothing for a second pass to match.
    for rid, placeholder in sorted(_KNOWN_RESOURCES.items(), key=lambda kv: -len(kv[0])):
        if rid in out:
            out = out.replace(rid, placeholder)
    return out


def mask(obj: Any) -> Any:
    """Recursively mask ARN account fields in a JSON-shaped structure.

    Keys are masked as well as values. A checkpoint's `failed` map is keyed by trial id
    and its *values* hold error messages that quote the endpoint URL and ARN, but a
    future record keyed by an ARN would otherwise slip past a values-only walk.

    Containers are rebuilt rather than mutated in place: `Checkpoint.save()` masks on the
    way to disk and must not alter the in-memory record the running arm is still
    appending to. A mutating version would make the mask observable to the analysis,
    which is the one place the true ARN still has to be readable.
    """
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {mask(k) if isinstance(k, str) else k: mask(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(mask(v) for v in obj)
    return obj
