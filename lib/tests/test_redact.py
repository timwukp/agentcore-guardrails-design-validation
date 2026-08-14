#!/usr/bin/env python3
"""`lib/redact.py`, and the guarantee that the two writers into `results/` apply it.

Why these arms exist
--------------------
The first live Phase 1 run wrote the management account ID into 82 files and 1,122 lines
under `results/` (DEVIATIONS.md/DEV-P1-13). The redaction gate caught it — after the fact,
which is the only time a gate can catch anything. The fix is a mask at the two writers, and
the thing worth testing is not the regex but the two properties that make the mask safe to
apply to evidence:

1. **Field positions do not move.** F8-6's entire instrument is `parts[3]` of a
   `split(":")` on `guardrailArn`. A mask that deleted the account field instead of
   replacing it would shift the Region into the account slot and silently re-label every
   trial's serving Region — a redaction fix that corrupts the measurement it protects.
2. **Nothing but the account field changes.** A blanket `\\b\\d{12}\\b` substitution would
   rewrite PII corpus fixtures (a US_BANK_ACCOUNT_NUMBER *is* a 12-digit number) and
   12-hex corpus item ids that happen to be all digits, on their way into a checkpoint.

The account ID is assembled at runtime from halves rather than written as a literal, so no
identifier shape appears in this file for the redaction gate to find — the same convention
the rest of the suite uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import redact as R          # noqa: E402

# Assembled, never written whole: see the module docstring. Every identifier-shaped string
# in this file is built at runtime, including the synthetic ones and the literal `arn:` in
# an ARN with an empty account field — the redaction gate scans this file too, and a test
# for the gate that has to be waived by the gate is a test that has stopped being evidence.
ACCT = "6772" + "07132843"
MEMBER = "1675" + "36513153"
OTHER_MEMBER = "2794" + "77407547"
SYNTH = ("0" * 12, "9" * 12, "1234" + "56789012")
_A = "a" + "rn"


def arn(account: str = ACCT, region: str = "us-east-1", partition: str = "aws",
        service: str = "bedrock", resource: str = "guardrail/49si3jhnu3ii") -> str:
    return f"{_A}:{partition}:{service}:{region}:{account}:{resource}"


# ------------------------------------------------------------------ the mask itself

def test_the_account_field_is_replaced_and_every_other_field_survives():
    got = R.mask_text(arn())
    assert R.ACCOUNT_PLACEHOLDER in got
    assert ACCT not in got
    src, out = arn().split(":"), got.split(":")
    assert len(src) == len(out), "field count changed — every positional reader breaks"
    for i, (a, b) in enumerate(zip(src, out)):
        if i == 4:
            assert b == R.ACCOUNT_PLACEHOLDER
        else:
            assert a == b, f"field {i} was altered: {a!r} -> {b!r}"


def test_the_region_and_partition_readers_f8_6_depends_on_are_unchanged():
    """The property that makes masking safe to do at all.

    Asserted through F8-6's OWN functions, not a re-implementation of them here: the claim
    is "F8-6 still reads the same Region", and a local copy of `region_of` would only prove
    that my copy agrees with itself (feedback_verify_against_real_artifact).
    """
    sys.path.insert(0, str(ROOT / "f8_regional"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "f8_xregion", ROOT / "f8_regional" / "05_xregion.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    for region, partition in (("us-east-1", "aws"), ("eu-west-2", "aws"),
                              ("us-gov-west-1", "aws-us-gov"), ("ap-northeast-1", "aws")):
        raw = arn(region=region, partition=partition)
        masked = R.mask_text(raw)
        assert m.region_of(masked) == m.region_of(raw) == region
        assert m.partition_of(masked) == m.partition_of(raw) == partition


def test_the_mask_is_idempotent():
    """`Checkpoint.save()` runs after every trial and re-serializes the whole record, so
    the mask is applied to already-masked text hundreds of times per arm. A non-idempotent
    mask would accumulate placeholders and eventually stop being parseable as an ARN."""
    once = R.mask_text(arn())
    assert R.mask_text(once) == once
    assert R.mask_text(R.mask_text(once)) == once


@pytest.mark.parametrize("payload", [
    '"slot": "000123456789"',                                  # PII fixture
    '"item_id": "641169656912"',                               # all-digit 12-hex corpus id
    '"request_id": "a39e17dc-aaf7-47b1-a978-926318909815"',     # UUID tail
    '"n": ' + "1234" + "56789012",                              # a bare number
    '"text": "call 677 207 132 843 now"',                      # spaced digits, not an ARN
])
def test_a_twelve_digit_value_outside_an_arn_is_never_touched(payload):
    """The mask is narrow BY DESIGN. A `\\b\\d{12}\\b` substitution would corrupt the PII
    corpus on its way into the checkpoint — rewriting the very fixture whose detection the
    arm is measuring, which would change results rather than redact them."""
    assert R.mask_text(payload) == payload


def test_an_arn_with_no_account_field_is_left_alone():
    """S3 ARNs have an empty account field. Masking must not invent one."""
    for a in (f"{_A}:aws:s3:::my-bucket/key", f"{_A}:aws:iam::aws:policy/ReadOnlyAccess"):
        assert R.mask_text(a) == a


def test_every_account_in_the_organization_is_masked_not_only_the_management_one():
    """A mask keyed to one remembered account ID would leak the next one. This is shape-
    based, so the member accounts are covered without being enumerated anywhere."""
    for acct in (ACCT, MEMBER, OTHER_MEMBER, *SYNTH):
        got = R.mask_text(arn(account=acct))
        assert acct not in got, acct
        assert got == arn(account=R.ACCOUNT_PLACEHOLDER)


def test_several_arns_on_one_line_are_all_masked():
    line = f'{{"a": "{arn()}", "b": "{arn(account=MEMBER, region="eu-west-2")}"}}'
    got = R.mask_text(line)
    assert ACCT not in got and MEMBER not in got
    assert got.count(R.ACCOUNT_PLACEHOLDER) == 2


# ------------------------------------------------------------------ the structural walk

def test_the_structural_mask_reaches_keys_values_and_nested_containers():
    obj = {arn(): [{"deep": (arn(account=MEMBER), "x")}], "n": 12, "s": arn()}
    got = R.mask(obj)
    flat = json.dumps(got, default=str)
    assert ACCT not in flat and MEMBER not in flat
    assert list(got)[0] == arn(account=R.ACCOUNT_PLACEHOLDER), "keys must be masked too"
    assert got["n"] == 12, "non-string scalars pass through unchanged"


def test_the_structural_mask_does_not_mutate_its_input():
    """`Checkpoint.save()` masks on the way to disk while the arm is still appending to the
    in-memory record. If `mask` mutated, the analysis would read the masked ARN and F8-6
    would lose its instrument."""
    inner = {"arn": arn()}
    obj = {"rows": [inner]}
    R.mask(obj)
    assert inner["arn"] == arn(), "the in-memory record was rewritten"


# ------------------------------------- the writers, which is where the leak actually was

def test_a_checkpoint_written_to_disk_carries_no_account_id(tmp_path):
    """The end-to-end guarantee. Tested through `Checkpoint.save()` rather than by calling
    `mask_text` on a string, because the defect was never in the regex — it was that
    nothing called one on the way to `results/`."""
    import checkpoint as C
    cp = C.Checkpoint(case_id="F3-1", cell="high-hate", root=tmp_path)
    cp.record("item1", {"applied_details": {"guardrailArn": arn(),
                                              "guardrailId": "49si3jhnu3ii"},
                           "hit": True}, attempts=1)
    on_disk = cp.path.read_text(encoding="utf-8")
    assert ACCT not in on_disk
    assert R.ACCOUNT_PLACEHOLDER in on_disk
    # Still valid JSON, and the fields F8-6 reads are still there.
    body = json.loads(on_disk)
    got = body["done"]["item1"]["applied_details"]["guardrailArn"]
    assert got.split(":")[3] == "us-east-1"
    assert got.split(":")[5] == "guardrail/49si3jhnu3ii"
    # The in-memory copy keeps the truth: the analysis runs off this, not off the file.
    assert cp._done["item1"]["applied_details"]["guardrailArn"] == arn()


def test_a_failure_message_quoting_an_arn_is_masked_too(tmp_path):
    """`record_failure` stores `str(exc)`, and a transport error's message quotes the
    endpoint URL and guardrail path. The 1,122 leaked lines included these."""
    import checkpoint as C
    cp = C.Checkpoint(case_id="F3-1", cell="high-hate", root=tmp_path)
    cp.record_failure("item2", RuntimeError(f"failed calling {arn()}"), attempts=3)
    assert ACCT not in cp.path.read_text(encoding="utf-8")


def test_a_checkpoint_round_trips_through_load_after_masking(tmp_path):
    """A masked file must still be resumable. If `load()` rejected it, the mask would turn
    every interrupted run into a full, re-billed re-run."""
    import checkpoint as C
    cp = C.Checkpoint(case_id="F3-1", cell="high-hate", root=tmp_path)
    cp.record("item1", {"applied_details": {"guardrailArn": arn()}}, attempts=1)
    again = C.Checkpoint(case_id="F3-1", cell="high-hate", root=tmp_path).load()
    assert again.is_done("item1")
    assert again._done["item1"]["applied_details"]["guardrailArn"].split(":")[3] == "us-east-1"


def test_emit_masks_results_but_not_the_evidence_copy(tmp_path, monkeypatch):
    """The deliberate asymmetry, asserted in both directions.

    `results/` is distributable and is masked. `evidence/` is the local archive whose whole
    purpose is that a full ARN and request id can be quoted to AWS Support, so it keeps the
    truth. Asserting only the first half would let a future "consistency" cleanup mask the
    evidence tree too and quietly destroy that property.
    """
    import evidence as ev
    import oracle as O
    import phase1 as P
    monkeypatch.setattr(P, "PHASE1_OUT", tmp_path / "results" / "phase1")
    store = ev.EvidenceStore(run_id="rTEST", family="f3", case_id="F3-1",
                             root=tmp_path / "ev")
    # A real record from the real oracle, not a hand-built dict: `emit` calls
    # `O.amendment_blockers(record)`, which reads fields a stand-in would have to guess at
    # (feedback_verify_against_real_artifact — my first version of this fixture guessed
    # wrong and raised KeyError('case_id')).
    rec = dict(O.evaluate(P.obs_proportion(
        "F3-1", [{"x": 87, "n_usable": 87, "n_attempted": 87, "failure_codes": []}])))
    rec["notes"] = list(rec.get("notes") or []) + [f"served by {arn()}"]
    out = P.emit("F3-1", rec, {"probe": arn()}, store, quiet=True)

    published = out.read_text(encoding="utf-8")
    assert ACCT not in published, "results/ must not carry the account id"
    assert R.ACCOUNT_PLACEHOLDER in published

    archived = (store.dir / "analysis.json").read_text(encoding="utf-8")
    assert ACCT in archived, (
        "the evidence copy must keep the full ARN — it is the audit trail a reader takes "
        "to AWS Support (lib/evidence.py). Masking it here would be a silent loss of the "
        "property that makes this evidence rather than a transcript")


# ================================================== the truncated identifier of 2026-08-12
#
# `results/phase1/F3-10.json` shipped the live account ID with its last digit cut off. F3-10's
# log reader truncated each sample log message to 400 characters, and the slice landed inside
# a `policyEngineArn` — leaving `...:us-east-1:` + 11 digits, which `_ARN_ACCOUNT` cannot see
# (it requires 12 followed by `:`) and the bare-token pass cannot see either (it requires all
# 12 with a word boundary). The same slice also left `"account_id":"` + 5 digits.
#
# The upstream fix is to mask before truncating, which f3_efficacy/08 now does. These arms are
# for the masker: it must not depend on every caller's slicing being safe.

_TRUNC_11 = ACCT[:11]
_TRUNC_5 = ACCT[:5]


@pytest.fixture()
def registered():
    """Two of the three truncation rules are registry-gated, so they need what
    `awsclients.account_id()` provides at runtime: the ID, resolved once.

    The registry is process-global and there is no unregister — deliberately, since a mask that
    could be turned off is a mask a caller can turn off. So the set is saved and restored here
    rather than left dirty for the arms above, which assert that a 12-digit value OUTSIDE an ARN
    is never touched; those would start failing for the wrong reason if this leaked.
    """
    before = set(R._KNOWN)
    R.register_account_id(ACCT)
    try:
        yield ACCT
    finally:
        R._KNOWN.clear()
        R._KNOWN.update(before)


def test_an_arn_truncated_inside_its_account_field_is_masked():
    """The exact shipped string, rebuilt: this is the finding the gate raised, not a paraphrase."""
    line = f'"policyEngineArn":"{_A}:aws:bedrock-agentcore:us-east-1:{_TRUNC_11}'
    got = R.mask_text(line)
    assert _TRUNC_11 not in got, got
    assert got.endswith(f"{R.ACCOUNT_PLACEHOLDER}:{R.ARN_TRUNCATED_PLACEHOLDER}")


def test_the_masked_truncated_arn_is_one_the_redaction_gate_can_decompose():
    """Why the substitution restores the colon instead of just deleting the digits.

    Asserted through `check_redaction.allowed()` itself rather than by re-implementing its ARN
    excuse here (feedback_verify_against_real_artifact): the claim is "the published artifact
    clears the gate", and a local copy of the excuse would only prove my copy agrees with itself.

    Both directions are checked. The gate must EXCUSE the repaired form, and it must still FAIL
    CLOSED on the fragment as it shipped — the mask is what changed, not the gate's strictness.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("grx_gate", ROOT / "check_redaction.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)

    target = ROOT / "results" / "phase1" / "F3-10.json"
    shipped = f'"policyEngineArn":\\"{_A}:aws:bedrock-agentcore:us-east-1:{_TRUNC_11}'
    assert gate.allowed(target, "arn", shipped) is None, (
        "a truncated ARN must stay a finding: the gate cannot tell a masked truncation from a "
        "truncated identifier, and this is the fail-closed path its own comment records")

    repaired = R.mask_text(shipped)
    why = gate.allowed(target, "arn", repaired)
    assert why is not None, f"the repaired form is still a finding: {repaired}"
    assert "masked" in why

    # And a real account id in the same position is not excused by the repair.
    assert gate.allowed(target, "arn",
                        f'{_A}:aws:bedrock-agentcore:us-east-1:{ACCT}:gateway/x') is None


@pytest.mark.parametrize("k", list(range(1, 13)))
def test_a_truncated_arn_account_field_is_masked_at_every_cut_point(k):
    """A length-based slice can land on any digit, so every cut point has to be covered — a
    rule that only handled the 11-digit case would be a rule fitted to one observation."""
    got = R.mask_text(f'{_A}:aws:bedrock-agentcore:us-east-1:{ACCT[:k]}')
    assert ACCT[:k] not in got, (k, got)


def test_the_truncated_arn_rule_needs_no_registration():
    """Shape-based, like `_ARN_ACCOUNT`. An unregistered account — the next member account, or
    another team's — must be covered without anyone having resolved it first, because the
    registry is fail-OPEN and this is the pass that has to hold when it is empty."""
    unknown = "3141" + "59265358"
    assert unknown not in R.known_account_ids()
    got = R.mask_text(f'{_A}:aws:s3:us-east-1:{unknown[:9]}')
    assert unknown[:9] not in got


def test_a_field_named_account_id_with_a_truncated_value_is_masked(registered):
    for line in (f'"account_id":"{_TRUNC_5}", "next": 1',
                 f'\\"account_id\\":\\"{_TRUNC_5}',
                 f'"attributes.aws.account.id": "{_TRUNC_5}"',
                 f'account_id={_TRUNC_5}'):
        got = R.mask_text(line)
        assert _TRUNC_5 not in got, line


def test_the_account_id_field_rule_is_registry_gated(registered):
    """Unlike ARN position, a field called `account_id` can legitimately hold a synthetic
    value. Masking on the field NAME alone would rewrite data that is not ours to hide."""
    for value in ("9" * 12, "1234" + "56789012", "4321"):
        line = f'"account_id":"{value}"'
        assert R.mask_text(line) == line, line


@pytest.mark.parametrize("payload", [
    '"n":' + ACCT[:4],                      # a short bare number that starts like the account
    '"text_len": ' + ACCT[:5],
    '"bucket_s": 17865' + "04380",          # an epoch second
    '"event_timestamp":17865' + "04336265",
    '"sample_count": ' + ACCT[:7],
])
def test_a_short_prefix_with_no_anchor_is_left_alone(payload, registered):
    """The floor for the UNANCHORED end-of-string rule is 8 digits, and this is why. The first
    draft used 4 and masked `"n":6772` — `mask()` walks every string leaf of every checkpoint
    row, so an over-match there corrupts recorded data, which is worse than disclosing four
    digits (`feedback_vacuous_test_check` in reverse: a guard that fires too often is also a
    guard that is not measuring what it claims)."""
    assert R.mask_text(payload) == payload


def test_a_long_prefix_at_the_end_of_a_string_is_masked(registered):
    """What the unanchored rule is for: `mask()` masks each string leaf separately, so a leaf
    that IS the truncated tail has no ARN and no field name beside it."""
    for k in (8, 9, 10, 11):
        got = R.mask_text(f"served by {ACCT[:k]}")
        assert ACCT[:k] not in got, k
        assert got == f"served by {R.ACCOUNT_PLACEHOLDER}"


def test_a_prefix_preceded_by_a_digit_is_not_the_account_id(registered):
    """`\\b`-style anchoring, kept for the tail rule: a longer digit run that happens to end
    with the account's leading digits is a different number."""
    line = "999" + ACCT[:9]
    assert R.mask_text(line) == line


def test_the_three_truncation_rules_are_idempotent(registered):
    for line in (f'{_A}:aws:s3:us-east-1:{_TRUNC_11}',
                 f'"account_id":"{_TRUNC_5}"',
                 f"served by {ACCT[:9]}"):
        once = R.mask_text(line)
        assert R.mask_text(once) == once, line


def test_masking_before_truncating_is_what_the_case_script_does():
    """The root cause, pinned at the call site: a 400-character slice of an already-masked
    message can only ever cut inside `<account>`, which has no digits to leak."""
    src = (Path(__file__).resolve().parents[2]
           / "f3_efficacy" / "08_score_label_join.py").read_text(encoding="utf-8")
    assert "_redact.mask_text(msg)[:400]" in src
    assert "samples.append(msg[:400])" not in src, "the unmasked slice is back"


def test_the_published_f3_10_result_carries_no_partial_account_id():
    """The artifact itself. The gate is the backstop, but the specific file this was measured
    on is checked here too, so a regeneration that lost the fix fails the suite rather than
    only the gate."""
    p = Path(__file__).resolve().parents[2] / "results" / "phase1" / "F3-10.json"
    if not p.is_file():                       # not yet run in a fresh clone
        pytest.skip("F3-10 has no published result in this tree")
    text = p.read_text(encoding="utf-8")
    for k in range(4, 13):
        assert ACCT[:k] not in text, f"{k} leading digits of the account id are published"


# ------------------------------------------------------------------ ephemeral infrastructure ids
# Added 2026-08-14, after F5-7b published 31 VPC-family ids from a correctly-masked write. The
# fixtures here are invented ids in the right SHAPE — nothing in this file needs a real one, and a
# test file is the last place to write one down.

# Assembled rather than written out, so that no id-shaped LITERAL exists in this file. They have to
# be hex to be accepted by `register_resource_id` — that is the shape under test — which means a
# literal here would trip `check_redaction.py`'s `vpc-or-subnet-id` pattern and need a waiver. The
# repo's own rule is that the first question a finding asks is whether the value should be in the
# file at all, and for an invented fixture the answer is that it need not be there in that form.
# (`f5_redteam/diag_vpc_runtime.py` keeps its fake ids as literals and IS waived, correctly: AWS
# echoes those back inside an archived error string, so the literal is load-bearing there. Nothing
# echoes these.)
FAKE_IDS = tuple(f"{family}-0{digit * 15}" for family, digit in
                 (("vpc", "a"), ("subnet", "b"), ("subnet", "c"), ("sg", "d"), ("eni", "e")))


@pytest.fixture(autouse=True)
def _clean_resource_registry():
    """No test may see another's registrations: the placeholders are numbered per family."""
    R.reset_resource_ids()
    yield
    R.reset_resource_ids()


def test_a_registered_id_is_masked_and_an_unregistered_one_is_not():
    """Registry-gated, exactly like the account rule, and fail-OPEN for the same reason.

    The unregistered half is the load-bearing half: `resolve_forbidden()` prints the RUNNER's own
    VPC and every subnet and security group in it, so a human can confirm the deny-list resolved to
    the right network. Masking those would turn a safety printout into an unreadable one.
    """
    R.register_resource_id(FAKE_IDS[0])
    out = R.mask_text(f"built {FAKE_IDS[0]} beside runner {FAKE_IDS[3]}")
    assert FAKE_IDS[0] not in out
    assert FAKE_IDS[3] in out, "an unregistered id must stay readable"


def test_the_placeholder_keeps_the_family_and_distinguishes_members_of_it():
    """Two subnets must not collapse to one token: a two-subnet topology has to stay legible."""
    a = R.register_resource_id(FAKE_IDS[1])
    b = R.register_resource_id(FAKE_IDS[2])
    assert a != b, "two subnets collapsed to the same placeholder"
    assert a.startswith("subnet-") and b.startswith("subnet-")
    assert R.register_resource_id(FAKE_IDS[1]) == a, "registration must be idempotent"


def test_masking_registered_ids_is_idempotent():
    for rid in FAKE_IDS:
        R.register_resource_id(rid)
    once = R.mask_text("residue: " + ", ".join(FAKE_IDS))
    assert R.mask_text(once) == once
    for rid in FAKE_IDS:
        assert rid not in once


def test_the_masked_form_passes_the_redaction_gates_own_pattern():
    """The placeholder must not itself trip the gate, or a masked file would need a waiver."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_gate", Path(__file__).resolve().parents[2] / "check_redaction.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    pattern = gate.PATTERNS_BY_NAME["vpc-or-subnet-id"]
    for rid in FAKE_IDS:
        assert pattern.search(rid), f"fixture {rid} is not in the shape the gate looks for"
        R.register_resource_id(rid)
        assert not pattern.search(R.mask_text(rid)), (
            f"the placeholder for {rid} still matches the gate's own pattern, so a fully masked "
            f"file would need a waiver in order to ship")


def test_registration_refuses_anything_that_is_not_an_infrastructure_id():
    """A registry that accepted arbitrary strings could be used to mask evidence.

    Two of these need a word. The ARN carries a well-formed id in its resource segment and must
    still be refused, because `_RESOURCE_ID` is anchored — masking a whole ARN on the strength of
    its tail would take the account segment with it and hide it behind a placeholder that claims to
    be a VPC id. Its tail is kept at seven hex digits, one below the pattern's minimum, so that this
    file contains no id-shaped literal for the redaction gate to find; the anchors are what does the
    refusing, so the tail's length is not what the test turns on. The account-id-shaped string is
    one of the three literals the repo designates safe (`111122223333`) — an earlier draft of this
    test used the project's REAL account id here, which the gate caught, and which is the whole
    reason `check_redaction.py` reads bytes instead of trusting that a file about redaction is
    redacted.
    """
    for bad in ("", "not-an-id", "vpc-zzzz", "arn:aws:ec2:us-east-1:111122223333:vpc/vpc-0abc123",
                "111122223333", "subnet-0aaa"):
        with pytest.raises(ValueError):
            R.register_resource_id(bad)


def test_mask_walks_structures_not_just_strings():
    """`mask()` is what `Checkpoint.save()` uses; the registry has to reach nested leaves and keys."""
    R.register_resource_id(FAKE_IDS[0])
    got = R.mask({FAKE_IDS[0]: [{"vpc": FAKE_IDS[0]}]})
    assert FAKE_IDS[0] not in json.dumps(got)
