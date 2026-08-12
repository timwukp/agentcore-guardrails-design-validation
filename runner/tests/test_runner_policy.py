#!/usr/bin/env python3
"""`runner/iam_policy.py` — the derivation, and the two properties that make it safe to attach.

The policy is generated, so the thing worth testing is not its text but that it stays a
DERIVATION: every API the validation has been measured making is mapped, nothing is scoped wider
than it has to be, and the file itself discloses no identifier.

The account ID is assembled from halves where one is needed, the same convention
`lib/tests/test_redact.py` uses — a test for a redaction-sensitive property that itself needs a
redaction waiver has stopped being evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner"))

import iam_policy as IP          # noqa: E402

ACCT = "0000" + "00000000"
REGION = "us-east-1"
BUCKET = "grx-validation-runner-test"

_HAS_EVIDENCE = bool(list((ROOT / "evidence").glob("*/*/*/*.json")))
needs_evidence = pytest.mark.skipif(
    not _HAS_EVIDENCE,
    reason="evidence/ is local-only and gitignored; the derivation cannot run in a fresh clone")


# ------------------------------------------------------------------ the derivation

@needs_evidence
def test_every_api_the_validation_has_called_is_mapped_to_an_action():
    """The whole point. A case that starts calling a new API fails HERE, at desk, rather than
    at 2am on the instance with an AccessDenied nobody is awake to read."""
    missing = IP.unmapped_operations()
    assert missing == [], (
        "these (service, operation) pairs appear in evidence/ with no MAPPING entry:\n"
        + "\n".join(f"  {s}.{o}" for s, o in missing)
        + "\nAdd each with the IAM action it needs and the narrowest scope that works.")


@needs_evidence
def test_the_derivation_reads_a_non_trivial_number_of_calls():
    """Both bounds, per feedback_zero_file_scan_is_error and its inverse. A floor against a
    mis-rooted glob; a floor on distinct pairs against a tree holding one case's calls only."""
    counts = IP.measured_operations()
    assert sum(counts.values()) >= 10_000, f"only {sum(counts.values())} archived calls found"
    assert len(counts) >= 30, f"only {len(counts)} distinct (service, operation) pairs found"


def test_an_empty_evidence_tree_raises_instead_of_yielding_an_empty_policy(monkeypatch, tmp_path):
    """The failure DIRECTION. An empty derivation must not read as "no permissions needed"."""
    monkeypatch.setattr(IP, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="read nothing"):
        IP.measured_operations()


@needs_evidence
def test_the_measured_role_names_all_carry_the_prefix_the_policy_scopes_to():
    """`NAME_PREFIX` is the load-bearing half of the IAM scope, so it is checked against the
    archived `create_role` params rather than against the comment beside it."""
    seen = []
    for path in (IP.ROOT / "evidence").glob("*/*/*/*_create_role_ok.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        name = (rec.get("params") or {}).get("RoleName")
        if name:
            seen.append(name)
    assert seen, "no archived create_role call to check the prefix against"
    assert all(n.startswith(IP.NAME_PREFIX) for n in seen), sorted(set(seen))


# ------------------------------------------------------------------ the scoping

def test_iam_write_actions_are_never_granted_on_a_wildcard_resource():
    """The escalation path this file exists to close: `iam:PutRolePolicy` on `*` lets anyone who
    can reach the instance rewrite any role in the account, including an administrator's."""
    doc = IP.document(ACCT, REGION, BUCKET)
    for st in doc["Statement"]:
        iam_actions = [a for a in st["Action"] if a.startswith("iam:")]
        if not iam_actions:
            continue
        assert st["Resource"] != ["*"], (
            f"{iam_actions} granted on * in {st['Sid']}")
        assert all(r.endswith(f"role/{IP.NAME_PREFIX}*") for r in st["Resource"]), st["Resource"]


def test_pass_role_is_prefix_scoped():
    """`iam:PassRole` on `*` is equivalent to assuming any role in the account via any service
    that will take one. It is moved onto the role scope explicitly in `statements()`, so this
    asserts the move happened rather than trusting the comment that says it should."""
    doc = IP.document(ACCT, REGION, BUCKET)
    holders = [st for st in doc["Statement"] if "iam:PassRole" in st["Action"]]
    assert len(holders) == 1, "PassRole appears in more than one statement"
    assert holders[0]["Resource"] == [f"arn:aws:iam::{ACCT}:role/{IP.NAME_PREFIX}*"]


def test_no_action_is_a_service_wildcard():
    """`bedrock:*` would make the derivation decorative."""
    for st in IP.document(ACCT, REGION, BUCKET)["Statement"]:
        for action in st["Action"]:
            assert not action.endswith(":*"), action
            assert action != "*", st["Sid"]


def test_the_transport_cannot_destroy_its_own_audit_trail():
    """The instance uploads evidence and results. It must not be able to delete them, or a run
    that goes wrong can erase the record of having gone wrong."""
    for st in IP.document(ACCT, REGION, BUCKET)["Statement"]:
        for action in st["Action"]:
            assert not action.startswith("s3:Delete"), action
            assert not action.startswith("s3:Put") or action == "s3:PutObject", action


def test_no_action_can_change_an_account_wide_setting():
    """`assert_transaction_search` ASSERTS and never enables — Transaction Search is account-wide
    and other systems depend on it. The policy makes that structural: no X-Ray write is granted,
    so a future edit to the case script cannot flip it even by accident."""
    granted = {a for st in IP.document(ACCT, REGION, BUCKET)["Statement"] for a in st["Action"]}
    for action in granted:
        if action.startswith("xray:"):
            assert action.startswith("xray:Get"), action
    assert not {a for a in granted if a.startswith(("organizations:", "account:", "iam:CreateUser",
                                                    "iam:AttachRolePolicy"))}


# ------------------------------------------------------------------ the file itself

def test_the_policy_module_writes_no_identifier():
    """It takes the account, Region and bucket as arguments precisely so it does not have to.
    Checked here as well as by the redaction gate, so a regression fails the suite too."""
    src = (ROOT / "runner" / "iam_policy.py").read_text(encoding="utf-8")
    import re
    assert not re.search(r"\b\d{12}\b", src), "a 12-digit identifier appears in the module"
    # An ARN template is fine; an ARN with a literal account field is not.
    for m in re.finditer(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:([^:{}]*):", src):
        assert not m.group(1).isdigit() or not m.group(1), m.group(0)


def test_every_runner_extra_carries_a_written_reason():
    """An action with no reason beside it is an action nobody can remove later, because nobody
    knows why it is there (feedback_prose_is_not_verified: the reason must be data, and here it
    is the dict value, so an entry cannot be added without one)."""
    assert all(isinstance(v, str) and len(v) > 15 for v in IP.RUNNER_EXTRAS.values()), \
        [k for k, v in IP.RUNNER_EXTRAS.items() if not (isinstance(v, str) and len(v) > 15)]


def test_the_document_is_valid_json_and_within_the_inline_policy_size_limit():
    """IAM inline role policies cap at 10,240 characters. A derivation that silently exceeded it
    would fail at PutRolePolicy on a live account, which is a worse place to find out."""
    text = json.dumps(IP.document(ACCT, REGION, BUCKET), separators=(",", ":"))
    assert json.loads(text)
    assert len(text) < 10_240, f"{len(text)} characters — over the inline policy limit"
