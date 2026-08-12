#!/usr/bin/env python3
"""Redaction gate: no cloud identifiers in anything destined for distribution.

Why a script and not a grep one-liner
-------------------------------------
The one-liner has failed twice in this codebase's history, both times reporting
CLEAN while reading nothing:

  * an unquoted `$(git diff --name-only)` word-split a path and the scan read zero
    files (feedback_quote_grep_filelists);
  * a bare `grep` in a non-interactive shell exited 127, which the caller read as
    "no matches" (feedback_guard_tool_exit_codes).

Both failures share one shape: **a scan that read nothing reported clean.** So
this script's first assertion is on its own denominator — fewer than MIN_FILES
files scanned is a FAILURE, not a pass (feedback_zero_file_scan_is_error).

What is scanned, and what is deliberately not
---------------------------------------------
Everything that could be published: source, generated Markdown, CSV, and the JSON
under ``results/``. Binary and cache paths are skipped by extension, and the skip
list is printed so it cannot quietly grow to cover a leak.

``evidence/`` is skipped **by decision, not by oversight**, and this paragraph
exists because an earlier version of this docstring said "JSON evidence" was
scanned while ``SKIP_DIRS`` excluded ``evidence`` — a contradiction that would
eventually be resolved in whichever direction was cheaper at the time. The
decision: the evidence tree is the local audit archive whose entire purpose is that
a claim can be taken to AWS Support and looked up by request id and full ARN
(``lib/evidence.py``). Masking it would defeat that. It is therefore **local-only
and never distributed**, and the release path is ``results/`` plus the Markdown
deliverables, which ARE scanned. Anything copied out of ``evidence/`` into a
distributable file is scanned at its destination.

Patterns are shape-based, not a blocklist of known IDs. A blocklist only catches
the identifiers I remembered to add; `\\b\\d{12}\\b` catches the one I did not.
The cost is false positives on innocent 12-digit numbers, which is the right
trade — an allowlist of reviewed exceptions is cheap, a missed account ID is not.

Usage: python3 check_redaction.py [--verbose]
Exit:  0 clean · 1 findings · 2 the scan itself could not be trusted
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import redact as _redact  # noqa: E402

ROOT = Path(__file__).resolve().parent

SCAN_EXT = {".py", ".md", ".csv", ".json", ".yaml", ".yml", ".txt", ".sh", ".sql"}
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", ".venv-oracle",
             ".venv-baseline", "node_modules", "evidence"}

# A scan of this project that reads fewer than this many files has not read the
# project. The number is a floor, not an estimate: it only has to be low enough
# never to false-alarm and high enough to catch a broken file list.
MIN_FILES = 10

PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("aws-account-id", re.compile(r"\b\d{12}\b"),
     "12-digit AWS account identifier"),
    ("arn", re.compile(r"\barn:aws[a-z-]*:[a-z0-9-]*:"),
     "AWS ARN"),
    ("s3-uri", re.compile(r"\bs3://[a-z0-9][a-z0-9.-]{2,}"),
     "S3 bucket URI"),
    ("access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
     "AWS access key ID"),
    ("private-ip", re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
     "private RFC1918 address"),
    ("vpc-or-subnet-id", re.compile(r"\b(?:vpc|subnet|sg|eni)-[0-9a-f]{8,17}\b"),
     "VPC-family resource id"),
]

# Reviewed exceptions: (file suffix, pattern name, substring that must be present
# on the matching line, written reason). An exception is a decision, not a
# silencer, so it is matched narrowly — a bare "skip this file" would hide the
# next leak in the same file.
#
# This list was EMPTY BY DESIGN for most of the project, and that history is worth
# keeping: the first draft carried eight entries waiving this file and the test
# suite for "their own pattern definitions". Every one was dead — a regex written
# as SOURCE does not match itself (`\b\d{12}\b` contains no twelve digits) — and
# the test suite was fixed properly instead, assembling its canaries at runtime so
# no identifier shape appears as a literal anywhere in the tree.
#
# Dead entries are worse than none: they advertise waivers that do not exist, so a
# reviewer reading ALLOW would conclude the gate had been argued down when it had
# not.
#
# The two entries below are the first real ones, and they are here because the PII
# corpus needs to CONTAIN identifier shapes — that is the whole point of a PII
# detection corpus. The alternative was to relax `access-key-id` and
# `aws-account-id`, which would have blinded the gate across all 44 files to catch
# two known fixtures. A narrow exception costs one reviewed line; a loosened
# pattern costs the next real leak.
#
# Both values are verified non-secret, not merely assumed so:
#   * the AWS_ACCESS_KEY fixtures are AWS's own published example access key IDs,
#     used verbatim throughout the AWS documentation. Structurally valid,
#     cryptographically useless.
#   * the US_BANK_ACCOUNT_NUMBER fixtures are synthetic account numbers authored
#     for this corpus. They trip `aws-account-id` because that pattern is
#     shape-based (`\b\d{12}\b`) and a 12-digit bank account number has the same
#     shape as an account ID. The pattern is right to fire; the value is not an
#     account ID. Verified: no real account ID from this organization (management
#     or either member account) appears anywhere in the tree.
#
# The literal values are deliberately NOT quoted in this comment. An earlier draft
# spelled them out here to be helpful and thereby created two fresh findings in
# this very file — which would have needed two more waivers, in a file whose job is
# to refuse them. A gate's own source is the last place to widen. Read the values
# in corpora/banks.py, where they belong and are already waived.
ALLOW: list[tuple[str, str, str, str]] = [
    ("f4_modes/00_syntax_probe.py", "arn", "us-east-1:0:gateway/dry",
     "dry-run placeholder ARN with account field literally `0` — one digit, not a "
     "12-digit account ID, and no AWS account can be numbered 0; the shape-based ARN "
     "pattern correctly fires on the arn: prefix, but the value is synthetic input "
     "for statement_variants() offline calibration and resolves to nothing"),
    ("corpora/banks.py", "access-key-id", "AWS_ACCESS_KEY",
     "AWS's published example access key IDs, required as PII corpus fixtures for "
     "the AWS_ACCESS_KEY entity type; structurally valid and non-functional"),
    ("corpora/banks.py", "aws-account-id", "US_BANK_ACCOUNT_NUMBER",
     "synthetic 12-digit US bank account numbers authored for the "
     "US_BANK_ACCOUNT_NUMBER entity type; same shape as an account ID, which is "
     "why the shape-based pattern correctly fires, but not an account ID"),
    # The three below are AWS's own DOCUMENTATION-EXAMPLE identifiers appearing inside
    # OFFLINE fakes. They are waived rather than redacted because the alternative is worse
    # in a specific way: these fakes exist to stand in for a real API response, and
    # `f1_config/tests/` deliberately borrows a real service model so `testbed.check_name`
    # reads the genuine pattern. Replacing a well-formed example ARN with a placeholder
    # would make the fake return a value the real service could never return, and the test
    # would then be asserting against a shape that does not exist.
    #
    # Verified before waiving, not assumed: neither this organization's management account
    # nor either member account appears in any of these lines — the value is AWS's published
    # example account, used verbatim across the AWS documentation. Each entry is matched on
    # a narrow substring, so it waives the example-bearing line and nothing else in the
    # same file; a real identifier landing on a different line in any of them still fails.
    ("f1_config/tests/test_f1_3_offline_mutations.py", "aws-account-id", "policyArn",
     "AWS's published example account ID inside the offline FakeAC's synthetic "
     "CreatePolicy response; the ARN must be well-formed because the assertion is on "
     "ARN shape, and a placeholder would be a shape the service cannot return"),
    ("f1_config/tests/test_f1_3_offline_mutations.py", "arn", "policyArn",
     "same line as the entry above: the `arn` pattern correctly fires on a complete "
     "example ARN whose account field is AWS's documentation example, not ours"),
    ("f1_config/tests/test_f1_3_offline_mutations.py", "aws-account-id",
     "get_caller_identity",
     "AWS's published example account ID returned by the stubbed STS in an offline arm. "
     "The value is consumed by `testbed.unmask_arn`, which REQUIRES 12 digits and raises "
     "otherwise, so a placeholder would make the fake unusable"),
    ("lib/f1_surface.py", "aws-account-id", "guardrailIdentifier",
     "a 12-character guardrail identifier (`gr-` + 12 digits) in a botocore "
     "ParamValidator probe. It trips the shape-based account-ID pattern because the "
     "digit run has the same shape; it is a guardrail id, not an account ID, and the "
     "probe sends nothing anywhere"),
    # F5's offline fixtures. Same reasoning as the f1_config/tests entries above, and the same
    # verification: the account field is AWS's published documentation example, and neither this
    # organization's management account nor either member account appears in any of these lines.
    #
    # Not redacted, for a reason specific to what these two fixtures feed. `_grant_policy` builds
    # an IAM policy document whose `Resource` is the function ARN, and the F5-4a fixtures build a
    # Cedar-side gateway ARN; both are asserted on for SHAPE. `redact.ACCOUNT_PLACEHOLDER` is
    # `<account>`, which is not 12 digits, so a redacted fixture would assert against a policy
    # document IAM would reject — the test would pass while describing a request that cannot be
    # made. Each entry matches a narrow constant name, so it waives the fixture's line and nothing
    # else in the file; a real identifier landing on any other line still fails the gate.
    ("f5_redteam/tests/test_policy_failure_modes.py", "aws-account-id", "GW_ARN",
     "AWS's published example account ID in the offline gateway-ARN fixture for F5-4a's "
     "policy-failure arms; no AWS call is made anywhere in that file"),
    ("f5_redteam/tests/test_policy_failure_modes.py", "arn", "GW_ARN",
     "same line as the entry above: the `arn` pattern correctly fires on a complete ARN whose "
     "account field is AWS's documentation example, not ours"),
    ("f5_redteam/tests/test_route1_direct_invoke.py", "aws-account-id", "FN_ARN",
     "AWS's published example account ID in the offline Lambda-ARN fixture. It is fed to "
     "`_grant_policy`, whose output shape is asserted on, and IAM requires a 12-digit account "
     "field in a Resource ARN"),
    ("f5_redteam/tests/test_route1_direct_invoke.py", "arn", "FN_ARN",
     "same line as the entry above: a complete example ARN, correctly matched by the shape-based "
     "`arn` pattern"),
    ("f5_redteam/tests/test_route1_direct_invoke.py", "arn", "_count_authorize_spans",
     "a synthetic gateway ARN whose account field is the single digit `1` — not a 12-digit "
     "account ID, and no AWS account can be numbered 1. It exists to assert that the span query "
     "is filtered on the ARN it was handed; `query_spans` is replaced and nothing is sent"),
]


# Two shapes that are structurally indistinguishable from an account ID and are provably
# not one. Both are DERIVED, not listed: a hand-written list of the values I happened to
# see would grow silently with every run, and the point of a shape-based pattern is to
# catch the identifier I did not think of.
#
#   1. **A corpus item id or slot value.** Corpus ids are 12 hex characters, so ~0.46% of
#      them (observed: 13 of 2,823, against (10/16)^12 expected) are all digits and trip
#      `\b\d{12}\b`. The PII corpus also *contains* identifier shapes by design — a
#      US_BANK_ACCOUNT_NUMBER fixture is a 12-digit number because that is what the entity
#      type is. Checkpoints record `item_id` and `slot` on every row, so these reach
#      `results/` legitimately.
#
#      The excuse is granted only if the token appears **verbatim in a sealed corpus
#      file**, which is why this is safe: `corpora/verify_corpora.py` pins those files by
#      sha256, so the set of excusable values cannot be widened by editing this gate. An
#      account ID would have to be committed into a sealed corpus and re-sealed to slip
#      through, which is a visible, gated act rather than an oversight.
#
#   2. **The last group of a UUID.** `request_id` is a UUID whose final group is 12 hex
#      characters; 4 of them in this run's output were all digits. Excused only when the
#      match is preceded by the rest of the UUID on the same line, so a bare 12-digit
#      number is never excused by this rule.
_UUID_HEAD = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
_UUID_TAIL = re.compile(_UUID_HEAD + r"(\d{12})\b")

# The ARN excuse's three regexes, separated so the excuse can DETECT an ARN it cannot decompose
# and refuse rather than pass. `_ARN_DETECT` is the reporting pattern itself (same shape as
# PATTERNS["arn"]) so the two can never disagree about how many ARNs a line has;
# `_ARN_ACCOUNT_FIELD` extracts the account position and tolerates `{template}` segments in the
# service and Region fields, which the old pattern could not; `_ARN_TEMPLATE_FIELD` recognises an
# f-string/`.format()` placeholder. A 12-digit account id cannot match `_ARN_TEMPLATE_FIELD`, so
# recognising placeholders never widens the gate over real identifiers.
_ARN_DETECT = re.compile(r"\barn:aws[a-z-]*:[a-z0-9-]*:")
_ARN_ACCOUNT_FIELD = re.compile(
    r"\barn:aws[a-z-]*:[^:\s]*:[^:\s]*:([^:\s]*):")
_ARN_TEMPLATE_FIELD = re.compile(r"\{[A-Za-z_][A-Za-z0-9_.\[\]'\"]*\}|<[a-z_-]+>")

_corpus_values: set[str] | None = None


def corpus_values() -> set[str]:
    """Every string value in every sealed corpus file, read once.

    Read from the files rather than from a list in this module, so the rule tracks the
    corpora and cannot drift from them. If the corpora are missing this returns an empty
    set, which makes the gate STRICTER (nothing is excused), never more permissive — the
    failure direction matters, per feedback_zero_file_scan_is_error.
    """
    global _corpus_values
    if _corpus_values is not None:
        return _corpus_values
    import json
    out: set[str] = set()
    for d in ("corpora", "corpora_deviation"):
        for p in (ROOT / d).rglob("*.jsonl"):
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    for v in json.loads(line).values():
                        if isinstance(v, str):
                            out.add(v)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
    _corpus_values = out
    return out


def allowed(path: Path, name: str, line: str) -> str | None:
    rel = str(path.relative_to(ROOT))
    for suffix, pname, needle, why in ALLOW:
        if rel.endswith(suffix) and pname == name and needle in line:
            return why
    # An ARN whose account field is already the placeholder is a REDACTED ARN, which is
    # what this gate is asking for. Excused here rather than by relaxing the `arn` pattern,
    # because the pattern must keep firing on every ARN that still carries an account: the
    # excuse is granted per line and only when the account field is *exactly* the
    # placeholder, so a real account ID anywhere in the same ARN still fails.
    #
    # What survives masking is the partition, service, Region and resource id. None is on
    # the redaction list, and the guardrail id is already recorded in plaintext beside it
    # as `guardrailId` — so excusing this line hides nothing that the row does not already
    # disclose in a field no pattern covers.
    if name == "arn":
        detected = len(_ARN_DETECT.findall(line))
        fields = _ARN_ACCOUNT_FIELD.findall(line)
        # Fail CLOSED when the excuse parser sees fewer ARNs than the detector did. The
        # previous version was a `for/else` over `finditer`, so an ARN the parser could not
        # decompose produced an EMPTY iterator and fell straight into `else` — excusing the
        # line with the message "every ARN on this line has its account field masked" when it
        # had inspected no account field at all. That is the vacuous-guard shape
        # (feedback_vacuous_test_check), and it was not hypothetical: `lib/testbed.py`'s
        # `arn:aws:bedrock-agentcore:{region}:{account_id}:policy-engine/{id}` was being
        # excused by it, because the old field pattern `[a-z0-9-]*` cannot match `{region}`.
        # A truncated ARN prefix at end of line took the same path. (Not spelled out here: an
        # earlier draft wrote the literal prefix into this comment and thereby created a finding
        # in the gate's own source, which is the one file that must never need a waiver.)
        if not fields or len(fields) != detected:
            return None
        kinds = set()
        for acct in fields:
            if acct == _redact.ACCOUNT_PLACEHOLDER:
                kinds.add("masked")
            elif _ARN_TEMPLATE_FIELD.fullmatch(acct):
                kinds.add("template")
            elif acct == "*":
                # An IAM policy resource wildcard. `*` in the account position is the absence
                # of an account, not a masked one, and it cannot be confused with an
                # identifier: this branch tests the field for EXACT equality with `*`, so a
                # wildcard Region followed by a real 12-digit account still fails. (Not
                # illustrated with a literal ARN here — doing so put a finding in this very
                # file, which is the one place a waiver must never be needed.)
                kinds.add("wildcard")
            else:
                return None
        if kinds and kinds <= {"template", "wildcard"}:
            return ("the account field of every ARN on this line is a run-time format "
                    "placeholder ({identifier}) or an exact `*` wildcard, i.e. this is source "
                    "code that BUILDS an ARN or an IAM policy resource pattern, and it "
                    "contains no identifier; a real account id is 12 digits and matches "
                    "neither shape, so it would still be reported here and by the "
                    "aws-account-id pattern")
        return (f"every ARN on this line has its account field masked to "
                f"{_redact.ACCOUNT_PLACEHOLDER} (lib/redact.py) or is a run-time format "
                f"placeholder; partition, Region and resource id are not redaction targets")
    if name == "aws-account-id":
        # EVERY 12-digit token on the line must be excusable, not just the first one.
        #
        # Measured 2026-08-12: the previous version did `re.search(...)` and reasoned about
        # that single token, so one excusable token waived the WHOLE line — a line carrying a
        # corpus fixture and a real account id would have been excused by the fixture. This is
        # the same vacuous-excuse shape DEV-P2-01 records for the ARN branch, in the branch
        # right below it, and it survived that fix because only the ARN half was re-read.
        toks = re.findall(r"\b\d{12}\b", line)
        why: set[str] = set()
        for tok in toks:
            # Never excuse a token that sits in the account field of an ARN, whatever else it
            # matches. That is the one position where a 12-digit number IS an account ID, and a
            # corpus fixture that happened to equal one would otherwise waive a real leak.
            if re.search(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:" + tok, line):
                return None
            if tok in corpus_values():
                why.add("appears verbatim in a sha256-sealed corpus file, so it is corpus "
                        "content (a 12-hex item id that is all digits, or a PII fixture "
                        "whose entity type IS a 12-digit number), not an account ID")
                continue
            if re.search(_UUID_HEAD + tok + r"\b", line):
                why.add("the last group of a UUID request id, matched only with the rest "
                        "of the UUID present on the same line")
                continue
            # The fractional part of a decimal number. `\b\d{12}\b` treats `.` as a word
            # boundary, so a latency figure whose fraction happens to be exactly twelve
            # digits — `758.324053273605`, published by F6's CloudWatch percentile read —
            # is reported as an account id. It cannot be one: an identifier is a token, and
            # this token's own delimiters make it the tail of a number. Anchored on a digit
            # before the `.` and on NO digit or `.` after, so neither an integer part nor a
            # dotted-quad segment takes this branch.
            if re.search(r"\d\." + tok + r"(?![\d.])", line):
                why.add("the fractional part of a decimal number (digit, `.`, then exactly "
                        "twelve digits and no further digit or `.`), which is a numeric "
                        "value rather than an identifier")
                continue
            return None
        if why:
            return " AND ".join(sorted(why))
    # The same sealed-corpus rule, applied to access key IDs. `corpora/banks.py` already
    # has a path-scoped waiver for AWS's published example keys, but a PII corpus exists to
    # be SENT: the fixtures come back on every checkpoint row as `slot`, so the waiver was
    # scoped to one site of a value that legitimately reaches many. Deriving the excuse
    # from sealed corpus membership covers every site without naming any — and without
    # naming the keys here, which would create findings in this file (see the ALLOW
    # comment above).
    if name == "access-key-id":
        m = re.search(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", line)
        if m and m.group() in corpus_values():
            return ("appears verbatim in a sha256-sealed corpus file: an AWS_ACCESS_KEY "
                    "PII fixture (AWS's own published example keys — structurally valid, "
                    "cryptographically useless) echoed back on a result row")
    return None


def files() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix not in SCAN_EXT:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    # argv is a parameter, not read from sys.argv unconditionally: the test suite
    # calls main() in-process, where sys.argv holds pytest's own flags and
    # argparse would SystemExit(2) on them — which looks exactly like the
    # "scan could not be trusted" exit code and would mask a real failure.
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    paths = files()
    print(f"redaction gate: {len(paths)} file(s) under {ROOT.name}/")
    print(f"  extensions {sorted(SCAN_EXT)}")
    print(f"  skipped dirs {sorted(SKIP_DIRS)}")

    if len(paths) < MIN_FILES:
        print(f"\nFAIL — scanned {len(paths)} file(s), below the floor of {MIN_FILES}. "
              f"A scan that read (almost) nothing must not report clean; the file "
              f"list is broken, not the tree.", file=sys.stderr)
        return 2

    findings: list[tuple[Path, int, str, str]] = []
    waived = 0
    scanned_bytes = 0

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            print(f"\nFAIL — cannot read {path.relative_to(ROOT)}: {exc}. An "
                  f"unreadable file is an unscanned file.", file=sys.stderr)
            return 2
        scanned_bytes += len(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rx, _desc in PATTERNS:
                m = rx.search(line)
                if not m:
                    continue
                why = allowed(path, name, line)
                if why:
                    waived += 1
                    if args.verbose:
                        print(f"  waived {path.relative_to(ROOT)}:{lineno} "
                              f"[{name}] — {why}")
                    continue
                findings.append((path, lineno, name, line.strip()[:120]))

    print(f"  {scanned_bytes:,} bytes read, {waived} reviewed exception(s) waived")

    if findings:
        print(f"\nFAIL — {len(findings)} unredacted identifier(s):\n", file=sys.stderr)
        for path, lineno, name, snippet in findings:
            print(f"  {path.relative_to(ROOT)}:{lineno}  [{name}]  {snippet}",
                  file=sys.stderr)
        print(f"\nRedact these, or add a narrow reviewed exception to ALLOW with a "
              f"written reason.", file=sys.stderr)
        return 1

    print(f"\nPASSED — no unredacted cloud identifiers in {len(paths)} scanned files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
