#!/usr/bin/env python3
"""`runner/sync.cmd_push()` — the guard that makes "pushed" mean "the instance is running this".

Why this file exists
--------------------
On 2026-08-12 `sync.py push` printed

    pushed 526 files, 3,232,921 bytes, sha256 d0110f92cc78cafe
    on the instance: grx-refresh

and the instance kept the tree it already had. The second line was a HINT to the operator, not a
report of work done, and it was read as a report. A job was then launched against code from four
hours earlier.

It survived only by luck. The file the job needed was **absent**, so python died with
`[Errno 2] No such file or directory` inside the first second and the mistake announced itself.
Had the file merely been **stale** — one edit behind, which is the far more common state after a
push — the run would have completed normally and published results attributed to code that never
produced them. That is the failure mode this project has already met twice
(`feedback_build_reported_success_built_nothing`: a Makefile whose default goal was not `all`, so
integration tests exercised a three-day-old daemon; `feedback_no_deploy_path_no_component`: a
config nothing deploys does not exist). A push whose only evidence of arrival is a printed
instruction has no deploy path.

What is asserted here
---------------------
Not the S3 upload and not SSM — both are stubbed, and neither is where the defect lived. The
defect was in the **verdict**: `push` returned 0 without any observation of the instance. So every
arm below drives `_run_on_instance` to a different outcome and checks that `cmd_push` only reports
success when the instance said `VERIFIED`, and that the manifest it uploads is the one that could
detect a stale file at all.

The stale arm is the mutation arm. It is the case the old code got wrong, so a test suite that
only covered the happy path would have passed against the bug (`feedback_vacuous_test_check`).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner"))

import sync as SY               # noqa: E402


# --------------------------------------------------------------------------------------------
# stubs
# --------------------------------------------------------------------------------------------

class _S3:
    """Records what was uploaded and answers `head_object` consistently with it.

    `head_object` must agree with the `put_object` that preceded it, because `cmd_push` compares
    them: a stub that returned a fixed digest would make the upload check pass by construction and
    the test would stop measuring it.
    """

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict] = {}

    def put_object(self, Bucket, Key, Body, Metadata=None, **kw):
        self.objects[Key] = Body
        self.metadata[Key] = Metadata or {}

    def head_object(self, Bucket, Key, **kw):
        return {"Metadata": self.metadata[Key], "ContentLength": len(self.objects[Key])}


@pytest.fixture
def push(monkeypatch, tmp_path):
    """`cmd_push` with S3 and SSM replaced, returning `(rc, s3, calls)`.

    The real `ROOT.rglob` walk is left alone: the manifest's whole job is to describe THIS tree,
    and a fixture that packaged a toy directory instead would verify a manifest of files nobody
    ships.
    """
    s3 = _S3()
    monkeypatch.setattr(SY.boto3, "client", lambda *a, **k: s3)
    monkeypatch.setattr(SY, "_state", lambda: {
        "region": "us-east-1", "bucket": "b-stub", "instance_id": "i-0stub"})

    def _make(reply):
        calls: list[str] = []

        def _fake(st, script, *, timeout_s=900):
            calls.append(script)
            return reply

        monkeypatch.setattr(SY, "_run_on_instance", _fake)
        rc = SY.cmd_push(object())
        return rc, s3, calls

    return _make


# --------------------------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------------------------

def test_a_confirmed_refresh_is_the_only_success(push, capsys):
    rc, s3, calls = push((0, "refreshed\nVERIFIED 526 file(s) on the instance\n", ""))
    assert rc == 0
    assert len(calls) == 1, "the refresh must be part of push, not an instruction to the operator"
    assert "grx-refresh" in calls[0]
    assert "code/grx-validation.tar.gz" in s3.objects
    assert "code/MANIFEST.txt" in s3.objects


def test_a_stale_instance_makes_push_fail(push, capsys):
    """THE MUTATION ARM — the exact 2026-08-12 failure, replayed.

    `sha256sum -c` on a tree missing one packaged file exits 1 and names it. Before this guard the
    push returned 0 here and the operator launched a job.
    """
    rc, _s3, _calls = push((1, "refreshed\n",
                            "f2_determinism/03_score_harvest.py: FAILED open or read\n"))
    assert rc != 0, "a tree that does not match what was packaged is NOT a successful push"
    assert "NOT CONFIRMED" in capsys.readouterr().err


def test_a_refresh_that_never_ran_makes_push_fail(push, capsys):
    """rc 0 with no VERIFIED line. The old code's exact shape: no observation, reported success.

    This arm matters separately from the one above because an SSM invocation can succeed as a
    *command* while the work inside it did nothing — `set -uo pipefail` without `-e` will run to
    the end of the script after a failed line. So the verdict cannot rest on rc alone.
    """
    rc, _s3, _calls = push((0, "refreshed 2026-08-12T11:47:38Z\n", ""))
    assert rc != 0, "no VERIFIED line means nothing on the instance was compared"
    assert "NOT CONFIRMED" in capsys.readouterr().err


def test_an_ssm_timeout_is_not_a_pass(push, capsys):
    rc, _s3, _calls = push((124, "", "timed out after 900s waiting for cid-1"))
    assert rc != 0, ("a guard that could not make its observation must not use the absence of "
                     "that observation as confirmation (feedback_guard_tool_exit_codes)")


# --------------------------------------------------------------------------------------------
# the manifest — the thing that does the detecting
# --------------------------------------------------------------------------------------------

def test_the_manifest_hashes_contents_not_names(push):
    """A name-only manifest cannot see a stale file, which is the whole point.

    Checked against `hashlib` on the real bytes rather than against `sha256sum` output, so the
    assertion does not depend on a tool the laptop and the instance spell differently.
    """
    _rc, s3, _calls = push((0, "VERIFIED 1 file(s)\n", ""))
    lines = s3.objects["code/MANIFEST.txt"].decode().splitlines()
    assert lines, "an empty manifest would make sha256sum -c verify nothing"
    by_rel = {}
    for line in lines:
        sha, rel = line.split("  ", 1)
        assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
        by_rel[rel] = sha
    # This file is in the tree, so it must be in the manifest with its real digest.
    me = str(Path(__file__).resolve().relative_to(ROOT))
    assert me in by_rel, f"{me} is a packaged file and must be covered"
    assert by_rel[me] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    # `sha256sum -c` format is exactly two spaces; one space silently becomes an unreadable line
    # and `--quiet` would report it as a WARNING rather than a mismatch.
    assert all(line.count("  ") >= 1 for line in lines)


def test_the_verify_script_compares_the_line_count_to_what_was_packaged(push):
    """A manifest that arrives truncated must not read as clean.

    `sha256sum -c` on 3 of 526 lines exits 0 — it verifies what it was given. So the count is
    asserted separately, against the number the packager counted
    (`feedback_two_numbers_two_claims`: two numbers in one sentence move independently, so each is
    derived rather than inferred from the other).
    """
    _rc, s3, calls = push((0, "VERIFIED 1 file(s)\n", ""))
    n_packaged = len(s3.objects["code/MANIFEST.txt"].decode().splitlines())
    script = calls[0]
    assert f"-ne {n_packaged}" in script, \
        "the instance-side count must be compared to the packaged count, not to itself"
    assert "sha256sum -c" in script
    assert "--quiet" in script


def test_the_verify_script_does_not_let_a_failed_refresh_continue(push):
    """`grx-refresh` failing and the manifest check passing anyway is the half-refresh case.

    Only reachable if the previous tarball happened to match, so it is cheap to get wrong and
    invisible when wrong. The script must exit on the refresh's own rc.
    """
    _rc, _s3, calls = push((0, "VERIFIED 1 file(s)\n", ""))
    script = calls[0]
    assert "grx-refresh ||" in script, "the refresh's exit code has to be read"
    assert "exit 9" in script
