"""`infra/01_iam.py:caller_trust` — the resource half of assume-role, and the name it duplicates.

F5-3b crashed rc=1 on 2026-08-13 with

    AccessDenied ... User: arn:aws:sts::<acct>:assumed-role/grx-runner-ec2/<instance> is not
    authorized to perform: sts:AssumeRole on resource: arn:aws:iam::<acct>:role/grx-attacker-<run>

and the instructive part is that the identity policy was only half the problem. The runner's
derived policy was missing `sts:AssumeRole` AND the target role's trust policy named the laptop IAM
user only. Assume-role requires both sides to agree, so fixing either alone leaves the same
AccessDenied with the same message — which is why the two fixes have tests in two places
(`runner/tests/test_runner_policy.py` asserts the grant exists and is prefix-scoped; this file
asserts the trust names the principal).

These are the properties worth holding, in the order they would hurt if they broke:

1. the runner is trusted, or every F5 case that runs AS another identity dies on its first call;
2. the trust never widens to the account root, or every F5 claim about what an identity CANNOT do
   becomes unfalsifiable — anything in the account could have done it;
3. the single-principal document keeps its original scalar shape, or `ensure_roles`' drift check
   fires on every already-provisioned role and a real tampering signal is lost in the churn;
4. `RUNNER_ROLE_NAME` still equals `provision.ROLE_NAME`, because it is duplicated rather than
   imported and a rename would otherwise be discovered as a live trust failure mid-run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from infra_by_path import load_infra

ROOT = Path(__file__).resolve().parents[2]

iam_mod = load_infra("01_iam")

ACCT = "1111" + "22223333"
CALLER = f"arn:aws:iam::{ACCT}:user/tim"
RUNNER = f"arn:aws:iam::{ACCT}:role/grx-runner-ec2"


def _principals(doc: dict) -> list[str]:
    """Every AWS principal in the document, as a LIST regardless of which shape was used.

    Written as a helper so the shape assertions live in their own test rather than being smuggled
    into every other one: a test that only ever reads through a normaliser cannot notice that the
    scalar/list distinction was lost.

    ALL statements, not `Statement[0]`. `grx-runtime-exec` is trusted by both the service and the
    harness, and its document is `service_trust(...)["Statement"] + caller_trust(...)["Statement"]`
    — so a helper that read only the first statement would report that role as having no AWS
    principal and the spec-wiring test below would have passed by looking at the wrong statement.
    That is exactly how this helper was first written, and the test caught it.
    """
    out: list[str] = []
    for st in doc["Statement"]:
        aws = st.get("Principal", {}).get("AWS")
        if aws is None:
            continue
        out.extend([aws] if isinstance(aws, str) else list(aws))
    return out


# ------------------------------------------------------------------ the name it duplicates

def test_the_runner_role_name_matches_the_one_provision_actually_creates():
    """`RUNNER_ROLE_NAME` is duplicated from `runner/provision.py` on purpose — `infra/` provisions
    the objects under test and should not import whichever transport happens to drive it. The cost
    of that choice is exactly this test: without it, renaming the role in one file produces a trust
    policy naming a principal that does not exist, which IAM accepts happily and which then fails
    as an AccessDenied halfway through a live run."""
    sys.path.insert(0, str(ROOT / "runner"))
    try:
        import provision as PV
    finally:
        sys.path.pop(0)
    assert iam_mod.RUNNER_ROLE_NAME == PV.ROLE_NAME, (
        f"infra/01_iam.py says {iam_mod.RUNNER_ROLE_NAME!r} but runner/provision.py creates "
        f"{PV.ROLE_NAME!r} — the trust policy would name a role that does not exist")


def test_the_runner_role_name_is_prefix_bound():
    """A name outside the `grx-` prefix would be trusted by these roles while sitting outside every
    teardown guard and outside the derived policy's resource scope."""
    assert iam_mod.RUNNER_ROLE_NAME.startswith("grx-")


# ------------------------------------------------------------------ the runner is trusted

def test_the_runner_is_trusted_when_named():
    doc = iam_mod.caller_trust(CALLER, ACCT, also_trust=(RUNNER,))
    assert RUNNER in _principals(doc)


def test_the_original_caller_is_still_trusted():
    """Adding the instance must not evict the laptop: `infra/01_iam.py` is still run from a
    workstation, and a document that dropped the caller would lock the provisioner out of the roles
    it had just created."""
    doc = iam_mod.caller_trust(CALLER, ACCT, also_trust=(RUNNER,))
    assert CALLER in _principals(doc)


def test_every_role_the_harness_assumes_trusts_the_runner():
    """The wiring, not the helper. `caller_trust` growing an `also_trust` parameter is worth nothing
    if a call site forgets to pass it, and the call site that forgets is the one whose case fails at
    2am.

    "Every role the harness assumes" is spelled as "every spec naming any AWS principal at all",
    not as a list of three names, so a fourth assumable role added later is a red test. `gx-exec`
    is trusted by the SERVICE only and is never assumed by anything in this repo — it is checked in
    the opposite direction by the next test rather than exempted here.
    """
    specs = iam_mod.role_specs("r20260101T000000Z", ACCT, CALLER, region="us-east-1")
    checked = []
    for name, spec in specs.items():
        if not _principals(spec.get("trust", {"Statement": []})):
            continue
        assert RUNNER in _principals(spec["trust"]), f"{name} does not trust the runner"
        checked.append(name)
    assert sorted(checked) == ["attacker", "caller", "runtime-exec"], sorted(checked)


def test_a_service_only_role_is_not_given_a_human_principal():
    """`grx-gw-exec` is a gateway execution role: the service assumes it, nothing in this repo does.
    Adding the runner to it would be a grant with no case behind it, and the direction that matters
    is that the blanket "trust the runner everywhere" fix was NOT applied where it was not needed."""
    specs = iam_mod.role_specs("r20260101T000000Z", ACCT, CALLER, region="us-east-1")
    assert _principals(specs["gw-exec"]["trust"]) == []
    assert specs["gw-exec"]["trust"]["Statement"][0]["Principal"]["Service"] \
        == "bedrock-agentcore.amazonaws.com"


def test_the_runtime_exec_role_keeps_both_of_its_principals():
    """It is trusted by the service (it IS a runtime execution role) and by the harness (F5-1 reads
    it as the caller). The addition must not have displaced the service statement, which would
    break gateway invocation in a way no F5 arm would attribute to a trust policy."""
    spec = iam_mod.role_specs("r20260101T000000Z", ACCT, CALLER, region="us-east-1")["runtime-exec"]
    services = [st["Principal"]["Service"] for st in spec["trust"]["Statement"]
                if "Service" in st.get("Principal", {})]
    assert services == ["bedrock-agentcore.amazonaws.com"], services
    assert RUNNER in _principals(spec["trust"])
    assert CALLER in _principals(spec["trust"])


# ------------------------------------------------------------------ what must NOT happen

def test_the_trust_never_widens_to_the_account_root():
    """The invariant the whole F5 family rests on. `{"AWS": account_id}` is shorter, would have
    fixed F5-3b just as well, and would have made every "an identity cannot do X" verdict
    unfalsifiable, because anything in the account could then have done X."""
    for also in ((), (RUNNER,), (RUNNER, f"arn:aws:iam::{ACCT}:role/grx-other")):
        doc = iam_mod.caller_trust(CALLER, ACCT, also_trust=also)
        for p in _principals(doc):
            assert p != ACCT, "trust widened to the account root"
            assert p != f"arn:aws:iam::{ACCT}:root", "trust widened to the account root"
            # Asserted by DECOMPOSING the ARN rather than by comparing against a literal prefix.
            # Two reasons, and the second is the one that changed this line: an equality on the
            # first three fields is stricter than a `startswith` (which would also accept a longer
            # service name beginning with `iam`), and a literal ARN prefix here is reported by
            # check_redaction.py. That report is correct behaviour, not a false positive — the gate
            # fails CLOSED on an ARN it cannot decompose into fields, and a bare prefix has no
            # account field to read — so the fix is to stop writing an ARN, not to waive the gate
            # for a file whose subject is IAM trust policies.
            fields = p.split(":")
            assert fields[:3] == ["arn", "aws", "iam"], p
            assert fields[3] == "", f"{p} carries a Region; IAM ARNs are global"
            assert "/" in fields[-1], f"{p} names no specific principal"


def test_the_action_is_only_assume_role():
    doc = iam_mod.caller_trust(CALLER, ACCT, also_trust=(RUNNER,))
    st = doc["Statement"][0]
    assert st["Action"] == "sts:AssumeRole", st["Action"]
    assert st["Effect"] == "Allow"
    assert "Condition" not in st or st["Condition"], "an empty Condition block is a lie"


def test_no_wildcard_reaches_the_principal_list():
    doc = iam_mod.caller_trust(CALLER, ACCT, also_trust=(RUNNER,))
    assert "*" not in json.dumps(doc["Statement"][0]["Principal"])


# ------------------------------------------------------------------ shape and normalisation

def test_the_single_principal_case_keeps_its_scalar_shape():
    """Emitting `["arn:..."]` where the provisioned roles carry `"arn:..."` is equally valid IAM
    and would make `ensure_roles`' canonicalised comparison report drift on every existing role.
    Drift is how a leftover red-team mutation is detected, so churn here costs a real signal."""
    doc = iam_mod.caller_trust(CALLER, ACCT)
    assert doc["Statement"][0]["Principal"]["AWS"] == CALLER
    assert isinstance(doc["Statement"][0]["Principal"]["AWS"], str)


def test_two_principals_become_a_list():
    doc = iam_mod.caller_trust(CALLER, ACCT, also_trust=(RUNNER,))
    assert isinstance(doc["Statement"][0]["Principal"]["AWS"], list)
    assert len(_principals(doc)) == 2


def test_the_runner_provisioning_itself_does_not_produce_a_duplicate():
    """`provision.py` is re-runnable FROM the instance, in which case the caller and the addition
    are the same principal. IAM accepts a document naming one principal twice and canonicalises it
    on read, so the next drift check would compare a two-entry spec against a one-entry live
    document and report tampering that never happened."""
    doc = iam_mod.caller_trust(RUNNER, ACCT, also_trust=(RUNNER,))
    assert _principals(doc) == [RUNNER]
    assert isinstance(doc["Statement"][0]["Principal"]["AWS"], str), \
        "collapsed to one principal but kept the list shape, which still churns the drift check"


def test_an_assumed_role_session_arn_is_normalised_on_both_sides():
    """Trust cannot name a session. The caller side was always normalised; `also_trust` has to be
    too, or running the provisioner from an assumed role produces MalformedPolicyDocument for the
    addition only — a failure that appears to come from the new parameter rather than from the ARN
    form."""
    session = f"arn:aws:sts::{ACCT}:assumed-role/grx-runner-ec2/i-0abc"
    doc = iam_mod.caller_trust(CALLER, ACCT, also_trust=(session,))
    assert RUNNER in _principals(doc)
    assert not any("assumed-role" in p for p in _principals(doc))
    assert not any(":sts:" in p for p in _principals(doc))


def test_an_empty_also_trust_is_the_document_the_roles_were_provisioned_with():
    """The default must be byte-identical to what the parameter replaced, so the diff that added it
    cannot have changed any already-provisioned role."""
    assert iam_mod.caller_trust(CALLER, ACCT) == {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": CALLER},
            "Action": "sts:AssumeRole",
        }],
    }


def test_order_is_deterministic_so_the_drift_check_does_not_flap():
    """`dict.fromkeys` rather than `set`: a set would reorder the principals between interpreter
    runs and the canonicalised comparison would report drift at random."""
    a = iam_mod.caller_trust(CALLER, ACCT, also_trust=(RUNNER, f"arn:aws:iam::{ACCT}:role/grx-z"))
    b = iam_mod.caller_trust(CALLER, ACCT, also_trust=(RUNNER, f"arn:aws:iam::{ACCT}:role/grx-z"))
    assert _principals(a) == _principals(b) == [
        CALLER, RUNNER, f"arn:aws:iam::{ACCT}:role/grx-z"]


def test_the_helper_writes_no_identifier_of_its_own():
    """It takes the account as an argument. A literal that leaked in would put a real account into
    every trust document and into this test's assertions."""
    import re
    src = (ROOT / "infra" / "01_iam.py").read_text(encoding="utf-8")
    assert not re.search(r"\b\d{12}\b", src), "a 12-digit identifier appears in infra/01_iam.py"
