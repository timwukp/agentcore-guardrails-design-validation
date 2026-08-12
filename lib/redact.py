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
