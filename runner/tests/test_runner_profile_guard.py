#!/usr/bin/env python3
"""`runner/provision.ensure_instance_profile()` — the guard that reads the instance's identity.

Why this file exists
--------------------
The runner's whole security story is one derived, least-privilege role. It was not the role the
instance ran as. An account-wide SSM State Manager association (`AWS-AttachIAMToInstance`, targets
`InstanceIds: ['*']`, `rate(1 hour)`) disassociates whatever profile an instance has and associates
`AmazonSSMRoleForInstancesQuickSetup` instead — observed in CloudTrail at 05:01, 06:01 and 07:01 on
2026-08-12, on this instance and three others. So the derived role survived at most an hour, and for
the rest of every hour the runner held `AmazonSSMFullAccess` plus an unrelated project's inline
policy granting `bedrock-agentcore:*` on `*` — control over the very resources under test.

The symptom was `aws s3 cp` returning `403 Forbidden` from a bucket whose role policy plainly
granted `s3:GetObject`, because the caller was not that role. Nothing in the tree could have caught
it: `provision.py` reused a running instance and never asked what identity it had.

What is asserted, and what deliberately is not
----------------------------------------------
The clobber itself cannot be tested — it is another system's schedule. What can be tested is the
guard's decision, and that is where the defect would live: a check that repairs when it should not
churns the association every poll, and one that does not repair when it should is the bug it was
written for. All three branches are exercised against a stub, so no test here touches AWS.

The stub is deliberately strict about which API is called. `replace_iam_instance_profile_association`
and `associate_iam_instance_profile` are different calls with different preconditions — replacing
requires a live association id, associating requires there be none — and calling the wrong one
fails at run time with an error that names neither. So each arm asserts the call, not just the
outcome.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner"))

import provision as PV          # noqa: E402

IID = "i-0stub"

# Assembled at run time rather than written as a literal, which is this project's standing
# convention: `check_redaction.py` scans every file including this one, and `claims/tests/`
# builds its canaries the same way so that no identifier SHAPE appears as a literal anywhere in
# the tree. That is why the gate's `ALLOW` list was empty by design for most of the project, and
# writing this ARN out longhand cost one gate finding before it was assembled instead.
#
# The account field is the single digit `1`. No AWS account is numbered 1, and the guard under test
# never reads that field — it takes `.split("/")[-1]`. But the string is still the REAL shape the
# API returns, because a stub that returned `instance-profile/name` would not prove the split works
# on what EC2 actually sends (feedback_verify_against_real_artifact).
_ARN_PREFIX = ":".join(["arn", "aws", "iam", "", "1", ""])


class _Ec2:
    """A stub EC2 client that records the mutating call it received.

    Only the three methods the guard uses. Anything else raises `AttributeError`, which is the point:
    a guard that grew a new API call would fail here rather than silently reach AWS from a test.
    """

    def __init__(self, associations):
        self._assoc = associations
        self.calls: list[tuple[str, dict]] = []

    def describe_iam_instance_profile_associations(self, Filters):
        assert Filters == [{"Name": "instance-id", "Values": [IID]}], Filters
        return {"IamInstanceProfileAssociations": self._assoc}

    def replace_iam_instance_profile_association(self, **kw):
        self.calls.append(("replace", kw))
        return {}

    def associate_iam_instance_profile(self, **kw):
        self.calls.append(("associate", kw))
        return {}


def _assoc(name: str, state: str = "associated", aid: str = "iip-assoc-0stub"):
    return {"AssociationId": aid, "State": state,
            "IamInstanceProfile": {"Arn": f"{_ARN_PREFIX}instance-profile/{name}"}}


# ------------------------------------------------------------------ the three branches

def test_the_correct_profile_is_left_alone():
    """The common case, and the one a too-eager guard would break.

    `run.py --tail` calls this on every poll. If a correct profile were re-associated anyway, a long
    run would churn the association hundreds of times, and each churn is a window in which the
    instance's credentials are being replaced.
    """
    ec2 = _Ec2([_assoc(PV.PROFILE_NAME)])
    assert PV.ensure_instance_profile(ec2, IID) is None
    assert ec2.calls == [], f"a correct profile was modified: {ec2.calls}"


def test_a_foreign_profile_is_replaced_by_association_id():
    """The measured case: the hourly association has swapped in its own profile."""
    ec2 = _Ec2([_assoc("AmazonSSMRoleForInstancesQuickSetup", aid="iip-assoc-0real")])
    msg = PV.ensure_instance_profile(ec2, IID)
    assert msg and "AmazonSSMRoleForInstancesQuickSetup" in msg and PV.PROFILE_NAME in msg, msg
    assert "DEV-P4-26" in msg, (
        "the repair message must point at the deviation entry; a bare 're-attached' line tells the "
        "next reader nothing about why it keeps happening")
    assert ec2.calls == [("replace", {"AssociationId": "iip-assoc-0real",
                                      "IamInstanceProfile": {"Name": PV.PROFILE_NAME}})], ec2.calls


def test_no_association_at_all_uses_associate_not_replace():
    """Between the association's disassociate and its associate there is no profile at all.

    A 1-second window on somebody else's schedule, but `provision.py` polls this on every command,
    so it will land in it eventually. `replace_iam_instance_profile_association` has no association
    id to pass in that state and would fail; `associate_iam_instance_profile` is the right call.
    """
    ec2 = _Ec2([])
    msg = PV.ensure_instance_profile(ec2, IID)
    assert msg and "NO instance profile" in msg, msg
    assert ec2.calls == [("associate", {"InstanceId": IID,
                                        "IamInstanceProfile": {"Name": PV.PROFILE_NAME}})], ec2.calls


def test_a_disassociating_association_does_not_count_as_live():
    """State matters, not mere presence.

    `describe_iam_instance_profile_associations` keeps returning an association in `disassociating`
    and `disassociated` states. Treating those as live would make the guard try to REPLACE an
    association that is going away — and, worse, would let a `disassociated` entry naming the right
    profile read as "already correct" while the instance in fact has none.
    """
    ec2 = _Ec2([_assoc(PV.PROFILE_NAME, state="disassociated")])
    msg = PV.ensure_instance_profile(ec2, IID)
    assert msg and "NO instance profile" in msg, (
        "a disassociated association naming the right profile was read as healthy; the instance "
        f"would have been left with no role. got: {msg!r}")
    assert ec2.calls and ec2.calls[0][0] == "associate", ec2.calls


def test_associating_counts_as_live():
    """The other half of the state question: a profile mid-attach is not missing.

    `associating` is transient and resolves to `associated`. Calling `associate` again in that state
    is an error, so the guard has to treat it as live — and if it is the RIGHT profile, leave it.
    """
    ec2 = _Ec2([_assoc(PV.PROFILE_NAME, state="associating")])
    assert PV.ensure_instance_profile(ec2, IID) is None
    assert ec2.calls == [], ec2.calls


def test_the_guard_is_actually_wired_into_every_laptop_path():
    """A guard nothing calls is not a guard (feedback_no_deploy_path_no_component).

    Every laptop→instance command goes through one of these three loaders, and each has to consult
    the profile: `sync.py` because it makes the instance read and write S3, `run.py` because a
    detached run uploads its results at the end with whatever identity it has by then, and
    `provision.py` because reusing a running instance is the moment its identity is assumed.
    """
    for rel, anchor in (("runner/sync.py", "_state"),
                        ("runner/run.py", "_client"),
                        ("runner/provision.py", "find_instance")):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "ensure_instance_profile" in src, (
            f"{rel} never checks the instance profile, so the clobber is invisible on that path "
            f"(the loader to wire it into is {anchor}())")
