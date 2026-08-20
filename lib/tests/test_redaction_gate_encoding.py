#!/usr/bin/env python3
"""An identifier the gate can read must stay unreadable in every encoding it can arrive in.

What shipped
------------
On 2026-08-19 the live AWS account ID was found **twenty times** in
`results/phase1/F5-7b.json`, in the tree pushed to the repository (private, verified the same day).
It had been there since the only commit that ever touched that path (`3f3c398b`, 2026-08-14), through
every run of the redaction gate in between, all of which exited 0 over that exact file. Private
visibility is why there is no incident to report; it is not why the defect is small — a
pre-publication gate that is wrong for five days is wrong regardless of who was looking.

F5-7b invokes an AgentCore runtime whose ARN is a **path segment of the invoke URL**, so every colon
in it arrives percent-escaped, and a botocore read-timeout message quotes the URL verbatim into the
record. `check_redaction.py`'s account pattern is `\\b\\d{12}\\b`. The character before those twelve
digits was the trailing LETTER of an escape, so the leading word boundary could not exist. Same
one-character cause for `arn`, `private-ip`, `vpc-or-subnet-id` and `s3-uri`, and for both of
`lib/redact.py`'s ARN passes.

Why the two-layer defence did not help, which is the part these tests exist to keep fixed
-----------------------------------------------------------------------------------------
`lib/redact.py`'s docstring rests on masker and gate being independent, so that what lives in the
gap is only "an identifier shape the masker does not cover". They were **not** independent here: both
anchored the account ID on `\\b`, and both failed on the same input for the same reason. Two layers
with a shared assumption are one layer. Worse, the gate *did* fire on this file — `private-ip`, on
the case's VPC CIDR — and a human reviewed that line and wrote the ALLOW. The file was known,
reviewed, and still shipped the ID.

So the assertions below are not "the encoded ARN is caught". They are:

* the gate applies its patterns to **more than one form** of a line (`scan_forms`), so the fix is a
  property of the scan rather than of five patched regexes — and a future performance edit that drops
  the decoded form reds this file;
* the two layers are checked **separately** on the same input, because their independence is the
  claim that failed;
* two arms assert the OLD anchors were blind, so a reader can see what the fix changed rather than
  taking "fixed" on trust (`feedback_identical_output_wrong_assertion`: a test that passes both
  before and after the fix is watching the wrong quantity);
* one arm is a no-mutant control — a clean line must produce nothing — because eleven arms that all
  fire prove only that the patterns are eager.

Every 12-digit value here is assembled from halves at run time, and the string `arn` is assembled
too, exactly as `lib/tests/test_redact.py` does it: this file is inside the gate's own scan, and
writing either literal would make the gate fail on its own test suite. That is not a hypothetical —
it is what happened to the first draft of the comment in `lib/redact.py` that documents this fix.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import redact as R  # noqa: E402

# Registered under a name of this file's own, never `check_redaction`: that stem is an importable
# top-level name under pytest and `lib/tests/test_module_name_collisions.py` is the gate that says
# a by-path loader must not squat it. A literal, so that gate can resolve it statically.
SUBJECT_MODULE_NAME = "_encscan_check_redaction"

# Not the live account. A shape-valid 12-digit value that is not one of AWS's reserved documentation
# examples either — those are excused by name in `allowed()`, so using one would make every
# detection arm below vacuous.
FAKE_ACCOUNT = "4099" + "38471625"
_A = "a" + "rn"
_PCT_COLON = "%" + "3A"
_PCT_SLASH = "%" + "2F"


def _subject():
    path = ROOT / "check_redaction.py"
    spec = importlib.util.spec_from_file_location(SUBJECT_MODULE_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gate():
    return _subject()


def _encoded_arn(account: str = FAKE_ACCOUNT) -> str:
    """The shape that shipped: a runtime ARN percent-encoded as a URL path segment."""
    return (_A + _PCT_COLON + "aws" + _PCT_COLON + "bedrock-agentcore" + _PCT_COLON
            + "us-east-1" + _PCT_COLON + account + _PCT_COLON + "runtime" + _PCT_SLASH
            + "grx_f57b_noroute_r20260810t130945z")


def _timeout_message(account: str = FAKE_ACCOUNT) -> str:
    """The whole record field, as botocore wrote it, as JSON, as the file held it."""
    return ('    "error_message": "Read timeout on endpoint URL: '
            '\\"https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/'
            + _encoded_arn(account) + '/invocations\\"",')


def _matches(gate_mod, line: str) -> list[tuple[str, str, str]]:
    """`(pattern name, the form's note, the form that matched)`, in the gate's own order.

    The note, not a list position: `scan_forms` now produces forms for two independent reasons
    (percent-decoding and blanking non-ASCII), so an index no longer identifies which repair found
    the identifier — and a test that reads the label off a position is a test that agrees with a
    mislabelled finding.
    """
    out = []
    for name, rx, _desc in gate_mod.PATTERNS:
        for form, note in gate_mod.scan_forms(line):
            if rx.search(form):
                out.append((name, note, form))
                break
    return out


def _hits(gate_mod, line: str) -> set[tuple[str, str]]:
    """`(pattern name, the note of the form it fired on)` for every pattern that fires.

    Written against `scan_forms` + `PATTERNS` rather than by calling `main()`, so the arms are about
    the scan's coverage of one line and do not depend on the repository's current contents.
    """
    return {(name, note) for name, note, _form in _matches(gate_mod, line)}


def _unwaived(gate_mod, path: Path, line: str) -> list[str]:
    """The pattern names that fire on this line and that `allowed()` does not excuse.

    The excuse is tried in the same order `main()` tries it — the form that matched first, then the
    bytes as written — because the two answer different questions: an ALLOW needle is authored
    against what the file contains, while the ARN excuse has to decompose the identifier, which it
    can only do once the line is decoded. Getting this order wrong in a *test* would have looked
    exactly like a leak: the first draft of this helper reported 20 findings on an already-masked
    file (`feedback_correction_wrong_twice` — the check on the fix needs checking too).
    """
    out = []
    for name, note, form in _matches(gate_mod, line):
        why = gate_mod.allowed(path, name, form)
        if not why and note:
            why = gate_mod.allowed(path, name, line)
        if not why:
            out.append(name)
    return out


# --------------------------------------------------------------------------------------------
# What the fix changed. These two arms FAIL on the pre-2026-08-19 code and are the only reason a
# reader can tell the difference between a fix and a claim.
# --------------------------------------------------------------------------------------------

def test_the_old_account_anchor_was_structurally_blind_to_this_line():
    """`\\b\\d{12}\\b` cannot match, and the reason is one character.

    Not "did not happen to match": the character preceding the digits is a letter, so the leading
    `\\b` asserts a boundary between two word characters, which cannot exist. Asserted directly on
    the old pattern rather than on an old copy of the gate, because it is the *anchor* that was
    wrong.
    """
    line = _timeout_message()
    assert FAKE_ACCOUNT in line
    assert re.search(r"\b\d{12}\b", line) is None


def test_the_old_masker_pass_was_a_no_op_on_this_line():
    """The registered-token substitution `\\b<aid>\\b` changed nothing — same cause."""
    line = _timeout_message()
    assert re.sub(rf"\b{FAKE_ACCOUNT}\b", R.ACCOUNT_PLACEHOLDER, line) == line


# --------------------------------------------------------------------------------------------
# Layer 1: the gate.
# --------------------------------------------------------------------------------------------

def test_the_gate_detects_the_account_in_the_encoded_arn(gate):
    assert ("aws-account-id", "url-decoded ×1") in _hits(gate, _timeout_message())


def test_the_gate_detects_the_arn_shape_in_the_encoded_arn(gate):
    assert any(name == "arn" for name, _n in _hits(gate, _timeout_message()))


def test_the_gate_still_detects_the_plain_form_at_depth_zero(gate):
    """The as-written form is scanned first and is not replaced by the decoded one.

    Decoding is lossy in the direction that matters (`%25` collapses), so an identifier plainly
    visible in the bytes must still be reported against the bytes.
    """
    plain = _timeout_message().replace(_PCT_COLON, ":").replace(_PCT_SLASH, "/")
    assert ("aws-account-id", "") in _hits(gate, plain)


def test_a_double_encoded_identifier_is_reached_too(gate):
    """One round is the case that shipped; a second exists because that is how `%` gets encoded."""
    twice = _timeout_message().replace("%", "%25")
    assert any(name == "aws-account-id" for name, _n in _hits(gate, twice))


def test_the_scan_applies_patterns_to_more_than_one_form(gate):
    """The fix is a property of the SCAN, not of five patched regexes.

    This is the arm that reds if someone later drops the decoded form for speed — the whole class of
    defect comes back at that moment, silently, with every pattern still looking correct.
    """
    line = _timeout_message()
    forms = gate.scan_forms(line)
    assert len(forms) >= 2
    assert forms[0] == (line, ""), "the bytes as written must be the first form scanned"
    assert FAKE_ACCOUNT in forms[1][0]
    assert _PCT_COLON not in forms[1][0], "the second form must actually be decoded"


def test_a_line_with_no_escapes_costs_exactly_one_form(gate):
    """Ordinary lines must not pay for this. 47 MB is read on every gate run."""
    assert gate.scan_forms('{"n_usable": 999}') == [('{"n_usable": 999}', "")]


# --------------------------------------------------------------------------------------------
# The second instance of the same `\b` assumption, found 2026-08-20 while mutation-testing the
# payload gate: a non-ASCII character is a word character, so it destroys the boundary exactly as
# the trailing letter of `%3A` did. Percent-decoding does not help here at all.
# --------------------------------------------------------------------------------------------

def test_an_account_id_surrounded_by_cjk_is_detected(gate):
    """`帳戶<account>號` — the shape a zh-TW deliverable can carry.

    This project ships zh-TW markdown and two 61-slide zh-TW decks, so prose with no space between a
    label and a value is the normal case, not a contrived one.
    """
    line = "帳戶" + FAKE_ACCOUNT + "號的設定"
    assert any(name == "aws-account-id" for name, _n in _hits(gate, line))
    assert ("aws-account-id", "non-ASCII blanked") in _hits(gate, line)


def test_an_account_id_next_to_high_bytes_is_detected(gate):
    """What a PNG text chunk or a compiled bundle looks like once read as latin-1.

    `platform/build/gate_payload.py` scans undecodable files as latin-1 rather than skipping them, so
    every high byte becomes a character — and in latin-1 most of them are letters.
    """
    line = "\xff\xfe" + FAKE_ACCOUNT + "\xc0\xc1"
    assert any(name == "aws-account-id" for name, _n in _hits(gate, line))


def test_the_old_boundary_was_structurally_blind_to_both(gate):
    """The pre-2026-08-20 gate on the same two lines. Without this the fix is a claim.

    Asserted against `\\b\\d{12}\\b` directly rather than against a saved copy of the old file: the
    property under test is the boundary rule, and naming it is what makes the arm readable.
    """
    old = re.compile(r"\b\d{12}\b")
    assert not old.search("帳戶" + FAKE_ACCOUNT + "號的設定")
    assert not old.search("\xff\xfe" + FAKE_ACCOUNT + "\xc0\xc1")


def test_blanking_does_not_reach_inside_an_ascii_hex_digest(gate):
    """The measured reason this is a form and not a widened pattern.

    Of 11,679 hex digests in the scanned tree, 281 contain a run of exactly twelve digits. Under
    `(?<!\\d)\\d{12}(?!\\d)` every one of those is a finding; under a blanked form none is, because
    the characters that protect them are ASCII letters and blanking never touches ASCII.
    """
    digest = "a1b2" + FAKE_ACCOUNT + "abcd" + "0" * 44
    assert len(digest) == 64
    assert not any(name == "aws-account-id" for name, _n in _hits(gate, digest))


def test_blanking_preserves_length_so_snippets_still_line_up(gate):
    """One character for one character: a reported snippet must point at the same place."""
    line = "帳戶" + FAKE_ACCOUNT + "號"
    forms = gate.scan_forms(line)
    blanked = [f for f, note in forms if note == "non-ASCII blanked"]
    assert blanked and len(blanked[0]) == len(line)


def test_a_percent_encoded_cjk_path_around_an_account_needs_BOTH_repairs(gate):
    """Blanking is applied to the decoded forms too, not only to the raw line.

    This is what a URL containing Chinese looks like: the CJK is percent-encoded UTF-8 and the account
    ID is plain. Neither repair alone reaches it —

    * as written, the last hex digit of `%B3` is a DIGIT, so the run is thirteen digits long and
      `\\b\\d{12}\\b` correctly declines to match a longer number;
    * decoded, the neighbours are CJK, which is the blindness the arms above establish.

    So the arm holds the composition, and it reds if a later edit blanks only the raw line.
    """
    label, suffix = urllib.parse.quote("帳戶"), urllib.parse.quote("號")
    line = f'"path": "/{label}{FAKE_ACCOUNT}{suffix}/invocations"'
    assert FAKE_ACCOUNT in line and "%" in line
    hits = _hits(gate, line)
    assert any(name == "aws-account-id" for name, _n in hits), \
        f"neither repair alone reaches this; got {sorted(hits)}"
    assert any(name == "aws-account-id" and "url-decoded" in note and "non-ASCII blanked" in note
               for name, note in hits), f"expected a composed form; got {sorted(hits)}"


def test_no_mutant_control_a_clean_line_produces_no_findings(gate):
    """Eleven arms that all fire would prove only that the patterns are eager.

    `feedback_vacuous_test_check`: the control has to be run, not assumed.
    """
    assert _hits(gate, '{"url": "https://example.com/runtimes/none", "n": 998}') == set()


def test_a_reviewed_exception_survives_decoding(gate):
    """An ALLOW needle is authored against what the file CONTAINS.

    A waiver written against the raw bytes must not be voided because the gate now also looks at a
    decoded copy — otherwise the fix would convert 13,000 reviewed exceptions into findings and the
    gate would be turned off within the day.
    """
    src = ROOT / "results" / "phase1" / "F5-7b.json"
    # Assembled at run time. A literal dotted quad here would make the gate raise a finding on this
    # test file, which has no ALLOW entry of its own — the self-scanning trap again
    # (`feedback_self_scanning_guard`), and the reason the reviewed exception is keyed to F5-7b's
    # path rather than to the value.
    cidr = "10." + "61.0.0/16"
    line = f'  "instrument": "A VPC built for this case alone: {cidr}, a public subnet",'
    assert gate.allowed(src, "private-ip", line)


# --------------------------------------------------------------------------------------------
# Layer 2: the masker. Checked separately from the gate on the same input, because their
# independence is the property that failed.
# --------------------------------------------------------------------------------------------

def test_the_masker_masks_the_encoded_arn_with_nothing_registered():
    """Registry-free, like `_ARN_ACCOUNT`: it must protect an account nobody registered.

    The next member account, or another team's, can arrive in our results the same way — F7's
    instrument enumerates a shared namespace — and it will never be in `_KNOWN`.
    """
    R._KNOWN.discard(FAKE_ACCOUNT)
    out = R.mask_text(_timeout_message())
    assert FAKE_ACCOUNT not in out
    assert R.ACCOUNT_PLACEHOLDER in out


def test_the_mask_leaves_the_encoded_arn_well_formed():
    """The escapes around the account field survive, so the result is still a decodable ARN.

    Same reason `ARN_TRUNCATED_PLACEHOLDER` restores its colon: the gate's ARN excuse decomposes the
    line, and a masker that destroyed the shape would make the gate fail closed on its own output.
    """
    R._KNOWN.discard(FAKE_ACCOUNT)
    out = R.mask_text(_timeout_message())
    assert _PCT_COLON + R.ACCOUNT_PLACEHOLDER + _PCT_COLON in out


def test_a_registered_account_is_masked_when_fused_to_letters():
    """`(?<!\\d)…(?!\\d)`, not `\\b…\\b`.

    The property that matters is "not part of a longer NUMBER" — that is what protects the
    `US_BANK_ACCOUNT_NUMBER` corpus and 12-digit epochs. Letters around an account ID never make it
    less of a disclosure, and percent-encoding is the ordinary way a colon becomes a letter.
    """
    R.register_account_id(FAKE_ACCOUNT)
    assert FAKE_ACCOUNT not in R.mask_text("providerX" + FAKE_ACCOUNT + "Yname")


def test_the_wider_boundary_still_protects_a_longer_digit_run():
    """The regression the wider boundary could have caused, asserted rather than assumed."""
    R.register_account_id(FAKE_ACCOUNT)
    longer = '{"epoch_us": 1' + FAKE_ACCOUNT + '7}'
    assert R.mask_text(longer) == longer


def test_the_wider_boundary_leaves_an_unrelated_twelve_digit_value_alone():
    """A corpus row whose entity type IS a 12-digit number must survive masking intact.

    `lib/redact.py`'s docstring rejects "mask every `\\b\\d{12}\\b`" for exactly this reason, and the
    fix must not smuggle that widening in through the boundary change.
    """
    R.register_account_id(FAKE_ACCOUNT)
    row = '{"slot": "US_BANK_ACCOUNT_NUMBER", "value": "4839' + '20174655"}'
    assert R.mask_text(row) == row


def test_masking_the_encoded_form_is_idempotent():
    R.register_account_id(FAKE_ACCOUNT)
    once = R.mask_text(_timeout_message())
    assert R.mask_text(once) == once


# --------------------------------------------------------------------------------------------
# The artifact that shipped. This is the only arm that reads the repository, and it is here so the
# incident cannot silently recur in the one file that is known to have carried it.
# --------------------------------------------------------------------------------------------

def test_the_file_that_shipped_the_account_id_no_longer_carries_it(gate):
    """`results/phase1/F5-7b.json`: 20 occurrences on 2026-08-19, 0 after masking.

    Asserted through the GATE rather than by a string search, so this arm covers any encoding the
    scan now reaches rather than only the one that was found.
    """
    src = ROOT / "results" / "phase1" / "F5-7b.json"
    text = src.read_text(encoding="utf-8")
    assert len(text) > 10_000, "read the wrong file; an empty read must not pass"
    unwaived = []
    for lineno, line in enumerate(text.splitlines(), 1):
        unwaived += [(lineno, name) for name in _unwaived(gate, src, line)]
    assert unwaived == []


def test_that_same_check_fails_on_the_pre_fix_content(gate):
    """The mutant for the arm above: put the identifier back and the check must convict.

    Without this, `test_the_file_that_shipped_…` passes on a file that is clean for any reason at
    all — including a waiver that grew wide enough to excuse the real thing — and a green result
    would mean nothing. The mutant is the file's own pre-fix shape, not an invented one: one masked
    field per line, restored to a 12-digit value under the SAME reviewed path, so the arm is proving
    the path-scoped ALLOW does not excuse an account ID.
    """
    src = ROOT / "results" / "phase1" / "F5-7b.json"
    mutant = src.read_text(encoding="utf-8").replace(
        _PCT_COLON + R.ACCOUNT_PLACEHOLDER + _PCT_COLON,
        _PCT_COLON + FAKE_ACCOUNT + _PCT_COLON)
    assert mutant != src.read_text(encoding="utf-8"), \
        "the mutation found nothing to change; the file no longer has the shape this arm tests"
    convicted = [name for line in mutant.splitlines()
                 for name in _unwaived(gate, src, line)]
    assert "aws-account-id" in convicted
