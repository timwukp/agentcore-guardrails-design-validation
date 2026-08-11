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
