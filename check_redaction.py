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
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import redact as _redact  # noqa: E402

ROOT = Path(__file__).resolve().parent

SCAN_EXT = {".py", ".md", ".csv", ".json", ".yaml", ".yml", ".txt", ".sh", ".sql"}
# An OOXML file is a zip of XML, so reading its bytes finds nothing and an extension
# skip would have been indistinguishable from a pass. The two v1.4 decks are built from
# the Markdown and distributed alongside it, so a leak in the source reaches a reader
# through them as well: the package is unzipped and every UTF-8 part is scanned. Only
# the raw XML is scanned, not a tag-stripped concatenation — stripping tags with no
# separator can fuse digits from adjacent table cells into a spurious 12-digit "account
# id", and this renderer never splits a run mid-token, so an identifier cannot hide
# across two <a:t> elements.
OOXML_EXT = {".pptx", ".docx", ".xlsx"}
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "node_modules", "evidence",
             ".state", ".staging"}
# Virtualenvs are matched by PREFIX, not enumerated. Enumerating them is how this gate
# already failed once: DEVIATIONS records a version where `".venv" not in p.parts` never
# matched `.venv-oracle`, so the scan read 1,272 files of site-packages and its own
# non-empty floor was satisfied by dependencies rather than by the repo. Listing each
# venv by name fixes that instance and leaves the next one uncovered — `.venv-figs`, added
# 2026-08-15 for the whitepaper figures, would have been the third such instance. A
# predicate cannot go stale when someone creates a fourth.
SKIP_DIR_PREFIXES = (".venv",)
# Every entry above is a directory that CANNOT reach a reader, and that is the whole
# justification for skipping it — this gate's docstring scopes it to "everything that
# could be published". Three of the entries hold project data rather than tooling:
# `evidence/`, 178 MB of raw API responses kept local by written policy;
# `runner/.state/`, which records the live instance id and the runner bucket name —
# precisely the value DEV-P4-25 exists to keep out of a pushable file; and
# `runner/.staging/`, the local-only scratch path `.gitignore:14-22` describes, which
# `tools/day2_replicate.py` uses for its pre-run snapshot of `results/phase1/`.
#
# `.staging` was added on 2026-08-15 after that snapshot made the gate FAIL on six
# private-ip hits, all of them in copies of `results/phase1/F5-7b.json` — a file whose
# original carries a reviewed ALLOW for exactly those lines, keyed to its path. The
# alternative fixes were both worse: waiving the pattern again under a second path teaches
# a reader that F5-7b's VPC CIDR is always fine wherever it appears, and moving the
# snapshot out of the repo would put the one copy of day 1 somewhere a crashed run's
# operator would not think to look. (The CIDR itself is deliberately not written here: this
# file is inside its own scan, so quoting the literal made the gate FAIL on its own source
# — which is the guard working, and `feedback_self_scanning_guard` says describe the value
# rather than exempt the file by path.) The gate was reading a directory that neither publication path can reach,
# which is the mirror image of the defect the skip list is usually accused of.
#
# "Cannot reach a reader" is a claim, so it is checked rather than trusted:
# `lib/tests/test_redaction_gate_skips.py` asserts that every entry here is matched by a
# `.gitignore` rule, with `.git` the single exception because git never tracks its own
# directory by construction. The test is what makes this list safe to extend — a skip
# added for a directory that IS published now reds the suite instead of silently
# blinding the gate to whatever is inside it.

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
    # F5-2's offline fixtures need ONE entry, not the six the same fixtures would have needed
    # written the obvious way, and the difference is worth recording because it is the pattern to
    # copy. `test_route3_updategateway.py` holds AWS's published example account on a single line
    # and interpolates it into every ARN, so each of those ARNs is excused by the DERIVED
    # template-field rule in `allowed()` and only the digits themselves need reviewing. The digits
    # cannot be replaced: `_pass_role_grant` builds an IAM policy `Resource` that is asserted on
    # for shape, and `<account>` is a value IAM rejects, so a redacted fixture would assert against
    # a request that cannot be made. Verified before waiving, not assumed — neither this
    # organization's management account nor either member account appears anywhere in that file.
    #
    # The needle includes the assignment, not just the constant name. `needle in line` is a plain
    # substring test, so the bare name `EXAMPLE_ACCOUNT` would also waive every line that
    # INTERPOLATES it — and a real 12-digit account landing on one of those ARN lines would then be
    # waived by an entry whose written reason says it cannot be. That is the shape where the
    # justification prose and the code disagree and only the prose gets read
    # (`feedback_prose_is_not_verified`), so the anchor is the definition itself.
    ("f5_redteam/tests/test_route3_updategateway.py", "aws-account-id", 'EXAMPLE_ACCOUNT = "',
     "AWS's published documentation-example account ID, bound to one constant that every ARN "
     "fixture in the file interpolates. Anchored on the assignment, so it waives that one line: a "
     "real identifier on any other line — including any line that uses the constant — still "
     "fails the gate"),
    # The EC2 runner added FOUR findings and none of them is in this list, which is the outcome to
    # aim for. Two `arn` matches and two `s3-uri` matches are excused by DERIVED rules in
    # `allowed()` instead, because each is a property of the notation rather than a fact about a
    # file: a service whose ARN grammar has no account segment, an AWS-managed resource, and a
    # bucket URI whose distinguishing part is already a placeholder. All four first went in here as
    # narrow anchors, and doing so put fresh findings in the gate's OWN SOURCE — the one file that
    # must never need a waiver — exactly as the paragraphs above warn. Backed out.
    #
    # F5-7b raised FOURTEEN findings. Three were real and are NOT waived: the runner instance's own
    # vpc / subnet / security-group ids, hard-coded as a deny-list in the producer. The gate was
    # right about them, and the fix was to delete them — the producer now resolves that deny-list at
    # runtime from the `grx-runner-sg` NAME, which is both unpublishable-by-construction and strictly
    # safer, because a hard-coded list stops protecting anything the moment the runner is rebuilt.
    # Recording that here because it is the outcome the paragraphs above keep arguing for: the first
    # question a finding asks is whether the value should be in the file at all, and three times out
    # of fourteen the answer was no.
    #
    # The remaining entries are the fixtures, and they are non-secret for two different reasons.
    #
    # The CIDRs: RFC1918 addresses of a VPC that this script CREATES AND DESTROYS inside a single
    # run. They cannot be replaced with a documentation range — RFC 5737's 192.0.2.0/24 is not a
    # range EC2 will accept for a VPC, so a "redacted" CIDR would be one `CreateVpc` rejects, and
    # the constant would then describe a network that cannot exist. They cannot be omitted either:
    # 10.61/16 is chosen specifically so it cannot collide with the runner's own 172.31/16, and
    # `test_the_new_vpc_cannot_collide_with_the_runners_own_addressing` asserts exactly that. One
    # entry anchored on `10.61.` covers all six lines in the one file that defines the range; a
    # DIFFERENT private address in that same file — a real one, pasted from an instance — still
    # fails the gate, which is the property that makes a single needle acceptable here.
    ("f5_redteam/12_vpc_egress_image_pull.py", "private-ip", "10.61.",
     "RFC1918 CIDRs for the VPC this case builds and tears down within one run. Chosen to be "
     "disjoint from the runner's own 172.31/16 and asserted to be so; not a range EC2 would "
     "accept if it were replaced by a documentation-example address, and not an address that "
     "identifies anything once the run ends"),
    # The fake ids: DELIBERATELY NONEXISTENT, and their nonexistence is the measurement. The
    # diagnostic's `vpc_shape` arm passes them to `CreateAgentRuntime` to establish that VPC mode is
    # live and validates its inputs, and the evidence FOR that is AWS's own refusal quoting them
    # back: "The following subnets could not be found: ...". Redacting them would break the
    # correspondence between the fixture and the archived response, which is the only thing that
    # makes the arm readable. Anchored on the constant names, so a real id elsewhere in the file
    # still fails.
    ("f5_redteam/diag_vpc_runtime.py", "vpc-or-subnet-id", "FAKE_SUBNETS",
     "structurally well-formed but deliberately nonexistent subnet ids, whose REFUSAL by EC2 is "
     "the diagnostic's `vpc_shape` observation; they address nothing in any account"),
    ("f5_redteam/diag_vpc_runtime.py", "vpc-or-subnet-id", "FAKE_SG",
     "same fixture as the entry above: a deliberately nonexistent security-group id passed to "
     "CreateAgentRuntime to show VPC mode validates its inputs"),
    # And the archived record of that refusal. `results/` is the distributable tree, so this one is
    # load-bearing: the finding is inside AWS's error string, quoted verbatim with its
    # x-amzn-requestid. Anchored on the error text rather than on the ids, so the waiver survives a
    # re-run under a new stamp while still failing on any other identifier in the file.
    ("results/DIAG-vpc-runtime-20260814T092455Z.json", "vpc-or-subnet-id",
     "subnets could not be found",
     "the fake subnet ids echoed back inside EC2's own refusal message, archived as the raw "
     "evidence for the diagnostic's `vpc_shape` arm; the same nonexistent ids as the two entries "
     "above, and unredactable without severing the response from the request that produced it"),
    # The write-up of that same run, and the same needle as the producer entry above for the same
    # reason. The finding's §6 states the range in order to state WHY it was chosen — disjointness
    # from the runner's own 172.31/16 — and a claim about non-collision that does not name either
    # range is not a claim a reader can check. Anchored on `10.61.`, so a real private address
    # pasted into this finding from an instance still fails the gate.
    ("results/FINDING-F5-7B.md", "private-ip", "10.61.",
     "the RFC1918 CIDR of a VPC created and destroyed inside one run, named in the finding so its "
     "asserted disjointness from the runner's own addressing is checkable; addresses nothing once "
     "the run ends"),
    # The result file of that run: third and last instance of the same needle. The CIDR reaches it
    # through the `instrument` string, which describes the fixture — the VPC built for this case
    # alone, its public subnet holding a NAT gateway and its private subnet holding the runtime's
    # ENIs — and an instrument description that will not say what address range it built is not one
    # a reader can evaluate. (Written without quoting the range: this file is scanned by the very
    # pattern being waived, and the paragraphs above are emphatic that the gate's own source is the
    # one file that must never need a waiver. An earlier draft of this comment quoted it and put a
    # finding in exactly that place.)
    #
    # Note what is deliberately NOT waived here. The vpc / subnet / sg / eni ids in this same file
    # are MASKED, by `redact.register_resource_id`, not excused: they identified resources that
    # really existed in a real account, and a placeholder costs the reader nothing because the
    # placeholder keeps the family prefix. The CIDR is different in kind — a compile-time constant
    # of the producer, already published by the two entries above, and chosen to be inert. That
    # asymmetry is the point: a waiver is for a value whose redaction would destroy meaning, and
    # everything else gets masked. Anchored on `10.61.`, so any other private address in this file
    # still fails the gate.
    ("results/phase1/F5-7b.json", "private-ip", "10.61.",
     "the same run-scoped RFC1918 CIDR as the producer and finding entries above, reaching this "
     "file through the `instrument` description of the fixture; the resource IDS in this file are "
     "masked rather than waived"),
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

# AWS's RESERVED documentation-example account IDs. These appear verbatim throughout the AWS
# documentation precisely so that examples can be well-formed without naming anyone's account, and
# AWS does not issue them to customers — so unlike every other 12-digit token, the VALUE itself
# proves it is not an identifier.
#
# Derived rather than listed per file, for the reason the ALLOW block above argues at length: this
# is a property of the notation, not a fact about a file. On 2026-08-14 fifteen findings across five
# test files were all one of these three values, and waiving them individually would have meant five
# more path anchors that say nothing a reader could not read off the value. The set is checked by
# EXACT equality, so any other 12-digit number — including a real account — is still reported.
#
# Deliberately NOT written here: this project's own account ID. Naming it in order to assert it is
# absent from this set would put a finding in the gate's own source, which is the one file that must
# never need a waiver. It was checked outside the gate instead, and each of these three is a
# published AWS example rather than an account this organization can reach.
AWS_DOC_EXAMPLE_ACCOUNTS = frozenset({"111122223333", "123456789012", "999988887777"})

# The same two placeholder spellings, used by the `s3-uri` branch to ask "is what follows this
# match a placeholder?" rather than "is this field one?". Anchored with `.match(line, pos)` so it
# must sit IMMEDIATELY after the URI — a placeholder later on the line excuses nothing.
_PLACEHOLDER_AT = re.compile(r"<[a-z_-]+>|\{[A-Za-z_][A-Za-z0-9_.\[\]'\"]*\}")

# The reporting patterns, by name, so a derived excuse can re-scan a line with the EXACT pattern
# that reported it. Deriving this from PATTERNS rather than restating a regex is the point: the
# excuse and the finding can never disagree about what matched (the same reason `_ARN_DETECT`
# duplicates the `arn` shape and is checked against it).
PATTERNS_BY_NAME = {n: p for n, p, _d in PATTERNS}

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
            elif acct == "":
                # The account field is EMPTY, which for some services is the grammar rather
                # than an omission: an S3 bucket ARN has no Region and no account segment at
                # all, by AWS's design, because bucket names are globally unique. There is no
                # identifier in that position to leak. Exact equality with the empty string, so
                # an ARN that merely *starts* with the same service still has its real account
                # field read. (This branch replaced two per-file ALLOW entries whose narrow
                # anchors had to spell the ARNs out, creating findings in this very file.)
                kinds.add("absent")
            elif acct in AWS_DOC_EXAMPLE_ACCOUNTS:
                # A complete, well-formed ARN whose account field is one of AWS's reserved
                # documentation examples. These have to stay well-formed: the offline fakes that
                # carry them exist to return what the real service would return, and several
                # assertions are on ARN SHAPE, so a placeholder would make the fake produce a value
                # the service could never emit and the test would assert against a shape that does
                # not exist.
                kinds.add("doc-example")
            elif acct == "aws":
                # AWS's own account position: `iam::aws:policy/...` names an AWS-MANAGED policy,
                # published in AWS's documentation and byte-identical in every account on earth.
                # `aws` is not a 12-digit id and cannot be confused with one.
                kinds.add("aws-owned")
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
        if kinds and kinds <= {"template", "wildcard", "absent", "aws-owned", "doc-example"}:
            return ("the account field of every ARN on this line is a run-time format "
                    "placeholder ({identifier}), an exact `*` wildcard, empty (a service such "
                    "as S3 whose ARN grammar has no account segment), the literal `aws` (an "
                    "AWS-managed resource), or one of AWS's reserved documentation-example "
                    "account IDs — i.e. this line contains no account identifier. A real "
                    "account id is 12 digits and is matched by exact equality against the "
                    "example set, so it would still be reported here and by the "
                    "aws-account-id pattern")
        return (f"every ARN on this line has its account field masked to "
                f"{_redact.ACCOUNT_PLACEHOLDER} (lib/redact.py) or is a run-time format "
                f"placeholder; partition, Region and resource id are not redaction targets")
    if name == "s3-uri":
        # A bucket URI whose distinguishing part is ALREADY a placeholder is a redacted bucket URI,
        # which is what this gate asks for. The `s3-uri` pattern fires on the scheme and then runs
        # as far as the character class allows, which stops at the opening angle bracket — so what
        # it matched is the prefix, and the placeholder is the next thing on the line. (Deliberately
        # written WITHOUT an example: spelling one out here put a finding in this very file for the
        # third time in one session. The `ALLOW` block's warning applies to comments too, and a
        # comment is exactly where it is easiest to forget.) Excused only when EVERY s3 URI on
        # the line is immediately followed by a placeholder, so a line carrying one masked URI and
        # one real bucket name still fails — the same per-line, all-matches discipline the
        # `aws-account-id` branch below had to be rewritten to use.
        #
        # What survives is the PREFIX, and that is deliberate: `BUCKET_PREFIX` is a project constant
        # in tracked source, not anything derived from the account. What it hides is the random
        # suffix, which is the only part that identifies one bucket (DEV-P4-25).
        hits = list(PATTERNS_BY_NAME["s3-uri"].finditer(line))
        if hits and all(_PLACEHOLDER_AT.match(line, h.end()) for h in hits):
            return ("every s3:// URI on this line is immediately followed by a `<placeholder>` or "
                    "`{template}`, i.e. the bucket's distinguishing part has already been redacted; "
                    "what remains is a prefix constant that appears in tracked source")
        return None
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
            # AWS's reserved documentation examples are excused FIRST, ahead of the ARN-position
            # guard below, and that ordering is the whole point rather than an oversight. The guard
            # refuses to excuse a token in an ARN's account field because the excuses beneath it are
            # circumstantial — "it also appears in a corpus", "it is also part of a UUID" — and
            # circumstance does not survive being in the one position where 12 digits mean an
            # account. This excuse is not circumstantial: the value is reserved by AWS and cannot be
            # a real account in any position, so an ARN carrying it carries no identifier. Exact
            # equality against three constants, so nothing else takes this branch.
            if tok in AWS_DOC_EXAMPLE_ACCOUNTS:
                why.add("one of AWS's reserved documentation-example account IDs, which AWS "
                        "publishes for use in examples and does not issue to customers — the "
                        "value itself proves it is not an identifier")
                continue
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


def units(path: Path) -> list[tuple[str, str]]:
    """``(label, text)`` pairs to scan for one file — several for an OOXML package."""
    rel = str(path.relative_to(ROOT))
    if path.suffix.lower() in OOXML_EXT:
        out = []
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                try:
                    out.append((f"{rel}!{name}", z.read(name).decode("utf-8")))
                except (UnicodeDecodeError, KeyError):
                    continue
        if not out:
            raise OSError("no readable XML part inside the package")
        return out
    return [(rel, path.read_text(encoding="utf-8"))]


def files() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SCAN_EXT | OOXML_EXT:
            continue
        parts = p.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        if any(part.startswith(SKIP_DIR_PREFIXES) for part in parts[:-1]):
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
    # Printed separately, and printed at all, because a reader checking whether the
    # decks were covered has only this line to go on.
    ooxml = [str(p.relative_to(ROOT)) for p in paths if p.suffix.lower() in OOXML_EXT]
    print(f"  OOXML {sorted(OOXML_EXT)} — {len(ooxml)} package(s) unzipped: "
          f"{', '.join(ooxml) if ooxml else 'none'}")
    print(f"  skipped dirs {sorted(SKIP_DIRS)} "
          f"+ any dir starting with {list(SKIP_DIR_PREFIXES)}")

    if len(paths) < MIN_FILES:
        print(f"\nFAIL — scanned {len(paths)} file(s), below the floor of {MIN_FILES}. "
              f"A scan that read (almost) nothing must not report clean; the file "
              f"list is broken, not the tree.", file=sys.stderr)
        return 2

    findings: list[tuple[str, int, str, str]] = []
    waived = 0
    scanned_bytes = 0

    for path in paths:
        try:
            parts = units(path)
        except (UnicodeDecodeError, OSError, zipfile.BadZipFile) as exc:
            print(f"\nFAIL — cannot read {path.relative_to(ROOT)}: {exc}. An "
                  f"unreadable file is an unscanned file.", file=sys.stderr)
            return 2
        for label, text in parts:
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
                            print(f"  waived {label}:{lineno} [{name}] — {why}")
                        continue
                    findings.append((label, lineno, name, line.strip()[:120]))

    print(f"  {scanned_bytes:,} bytes read, {waived} reviewed exception(s) waived")

    if findings:
        print(f"\nFAIL — {len(findings)} unredacted identifier(s):\n", file=sys.stderr)
        for label, lineno, name, snippet in findings:
            print(f"  {label}:{lineno}  [{name}]  {snippet}", file=sys.stderr)
        print(f"\nRedact these, or add a narrow reviewed exception to ALLOW with a "
              f"written reason.", file=sys.stderr)
        return 1

    print(f"\nPASSED — no unredacted cloud identifiers in {len(paths)} scanned files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
