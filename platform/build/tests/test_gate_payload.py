#!/usr/bin/env python3
"""Every guard in `gate_payload.py`, checked by breaking it.

Why each arm exists
-------------------
A gate is a claim about bytes nobody will read again. The only way to know it is doing anything is to
hand it a payload that must fail and watch it fail — `feedback_vacuous_test_check`. So each arm below
mutates exactly one property and asserts the specific refusal, and the FIRST arm is a no-mutant
control: a clean payload must pass, or every other arm proves only that the gate is indiscriminate.

The arm that matters most is `test_an_unrelated_sources_waiver_does_not_excuse`. This gate excuses a
hit by inheriting a path-scoped exception from the payload file's SOURCE, and the whole value of that
design is that the inheritance is scoped. If a waiver from any source excused any payload file, the
gate would be granting a blanket payload-wide waiver with extra steps — which is the thing
`build_site_data.py`'s docstring says must never happen, and the reason the payload lives outside the
repository at all.

Self-scanning discipline
------------------------
This file is inside `check_redaction.py`'s scan. Every identifier below is assembled from halves at
run time: a literal 12-digit account, a literal ARN or a literal dotted quad here would make the repo
gate raise a finding on its own test suite. That is not hypothetical — it happened three times in one
session to comments in `check_redaction.py` and `lib/redact.py` (`feedback_self_scanning_guard`).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SUBJECT_MODULE_NAME = "_gp_gate_payload"

# Assembled, never written whole. A shape-valid 12-digit value that is not one of AWS's reserved
# documentation examples — those are excused by name, which would make every detection arm vacuous.
FAKE_ACCOUNT = "4099" + "38471625"
_CIDR = "10." + "61.0.0/16"          # F5-7b's run-scoped VPC CIDR, the one reviewed exception in play
_PCT_COLON = "%" + "3A"
_A = "a" + "rn"

# A real repo file whose ALLOW entry excuses that CIDR under its own path, and a real repo file that
# carries no private-ip exception at all. Both are asserted to exist, so a rename reds this file
# instead of silently turning two arms into the same arm.
SRC_WITH_WAIVER = "results/phase1/F5-7b.json"
SRC_WITHOUT_WAIVER = "results/CITATION-POLICY.md"


def _subject():
    path = ROOT / "platform" / "build" / "gate_payload.py"
    spec = importlib.util.spec_from_file_location(SUBJECT_MODULE_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gp():
    return _subject()


@pytest.fixture(autouse=True, scope="module")
def _sources_exist():
    for rel in (SRC_WITH_WAIVER, SRC_WITHOUT_WAIVER):
        assert (ROOT / rel).is_file(), f"{rel} moved; two arms below would collapse into one"


def make_payload(tmp_path: Path, files: dict[str, str], provenance: dict[str, list[str]],
                 pad_to: int = 45, skip_manifest: bool = False,
                 drop_from_manifest: str | None = None) -> Path:
    """A synthetic payload with a well-formed manifest, padded past the gate's file floor.

    Padded with real files rather than by lowering `MIN_FILES`: monkeypatching the floor would make
    every arm run against a gate configured differently from the one that ships, and the floor is
    itself a guard (`feedback_zero_file_scan_is_error`).
    """
    root = tmp_path / "payload"
    root.mkdir(parents=True, exist_ok=True)
    allf = dict(files)
    for i in range(pad_to):
        allf[f"cases/PAD-{i:02d}.json"] = json.dumps({"case": f"PAD-{i:02d}", "n": i}) + "\n"
    outputs = {}
    prov = dict(provenance)
    for rel, text in allf.items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        outputs[rel] = hashlib.sha256(text.encode()).hexdigest()
        prov.setdefault(rel, ["PREREGISTRATION.yaml"])
    if drop_from_manifest:
        outputs.pop(drop_from_manifest, None)
    # The manifest is itself an emitted file, so the gate requires provenance for it too — the real
    # build records `provenance["MANIFEST.json"] = sorted(inputs)`. Omitting it here made ten arms
    # fail on a fixture defect and made `test_a_file_with_no_provenance_fails` pass vacuously, which
    # is exactly what the no-mutant control is for.
    prov.setdefault("MANIFEST.json", ["PREREGISTRATION.yaml"])
    if not skip_manifest:
        man = {"build_stamp": "20260819T000000Z", "tool": "test",
               "n_inputs": 1, "n_outputs": len(outputs) + 1,
               "inputs_sha256": {"PREREGISTRATION.yaml": "0" * 64},
               "outputs_sha256": outputs, "provenance": prov, "note": "synthetic"}
        (root / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    return root


def run(gp, root: Path, *extra: str) -> int:
    return gp.main(["--payload", str(root), *extra])


# --------------------------------------------------------------------------------------------
# The control. Without this, every arm below proves only that the gate refuses everything.
# --------------------------------------------------------------------------------------------

def test_no_mutant_control_a_clean_payload_passes(gp, tmp_path):
    root = make_payload(tmp_path, {"census.json": json.dumps({"rows": [], "n": 91}) + "\n"}, {})
    assert run(gp, root) == 0


# --------------------------------------------------------------------------------------------
# Detection.
# --------------------------------------------------------------------------------------------

def test_a_literal_account_id_in_the_payload_fails(gp, tmp_path):
    root = make_payload(tmp_path, {"cases/X-1.json": '{"acct": "' + FAKE_ACCOUNT + '"}\n'}, {})
    assert run(gp, root) == 1


def test_a_percent_encoded_account_id_in_the_payload_fails(gp, tmp_path):
    """The 2026-08-19 defect, at the payload layer.

    The payload is a derivation of records that quote AgentCore invoke URLs, so this is the shape most
    likely to arrive here — and it must not depend on `build_site_data.py` having masked it.
    """
    enc = (_A + _PCT_COLON + "aws" + _PCT_COLON + "bedrock-agentcore" + _PCT_COLON + "us-east-1"
           + _PCT_COLON + FAKE_ACCOUNT + _PCT_COLON + "runtime/x")
    root = make_payload(tmp_path, {"cases/X-1.json": '{"url": "https://h/runtimes/' + enc + '"}\n'},
                        {})
    assert run(gp, root) == 1


def test_an_account_id_in_a_log_file_fails(gp, tmp_path):
    """The extension predicate, which is the whole reason this gate walks by exclusion.

    This arm is where the repo gate's scope gap was found. It used to say "`check_redaction.py`
    selects by `SCAN_EXT` and `.log` is not in it — register item 35's still-open second instance",
    and on 2026-08-20 that comparison was measured rather than left standing: the allowlist was
    skipping 87 files, 7 unwaived identifiers among them. `check_redaction.py` now walks by
    exclusion too. The arm stays, because the *payload* is the surface with the widest set of
    unforeseeable artefact types, and a `.log` in it must still be read.
    """
    root = make_payload(tmp_path, {"build.log": "uploading to acct " + FAKE_ACCOUNT + "\n"}, {})
    assert run(gp, root) == 1


def test_an_account_id_inside_an_undecodable_file_fails(gp, tmp_path):
    """"Binary" is not a reason not to look. A PNG text chunk or a compiled bundle is ASCII inside."""
    root = make_payload(tmp_path, {"cases/X-1.json": "{}\n"}, {})
    blob = root / "assets" / "logo.png"
    blob.parent.mkdir(parents=True, exist_ok=True)
    raw = b"\x89PNG\r\n\x1a\n\xff\xfe" + FAKE_ACCOUNT.encode() + b"\xc0\xc1"
    blob.write_bytes(raw)
    man = json.loads((root / "MANIFEST.json").read_text())
    man["outputs_sha256"]["assets/logo.png"] = hashlib.sha256(raw).hexdigest()
    man["provenance"]["assets/logo.png"] = ["PREREGISTRATION.yaml"]
    (root / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    assert run(gp, root) == 1


def test_the_bare_runner_bucket_name_is_already_covered_by_the_account_pattern(gp):
    """Why this gate adds NO pattern of its own for it — asserted rather than assumed.

    `runner/iam_policy.py` builds the bucket as a prefix, a stem, the account and the Region joined by
    hyphens. The plan for this gate called for a dedicated pattern because an `s3://`-shaped pattern
    cannot see a bare name. Measured: the character before the twelve digits is a HYPHEN, a non-word
    character, so `aws-account-id` fires. This arm is what keeps that true — narrow the account
    pattern and this reds, instead of the docstring quietly becoming false.
    """
    gate = gp.load_subject()
    bare = "grx-" + "runtime-code-" + FAKE_ACCOUNT + "-us-east-1"
    fired = {name for name, rx, _d in gate.PATTERNS if rx.search(bare)}
    assert "aws-account-id" in fired
    assert not {"s3-uri", "arn"} & fired, \
        "if an s3/arn pattern now covers this, the docstring's reasoning needs rewriting"


# --------------------------------------------------------------------------------------------
# Inheritance — the part that must be scoped, not global.
# --------------------------------------------------------------------------------------------

def test_a_sources_reviewed_waiver_is_inherited(gp, tmp_path):
    line = '{"instrument": "A VPC built for this case alone: ' + _CIDR + ', a public subnet"}\n'
    root = make_payload(tmp_path, {"cases/F5-7b.json": line},
                        {"cases/F5-7b.json": [SRC_WITH_WAIVER]})
    assert run(gp, root) == 0


def test_an_unrelated_sources_waiver_does_not_excuse(gp, tmp_path):
    """The same bytes, one field changed: the source they are declared to come from.

    If this passed, the gate's excuse would be payload-wide rather than provenance-scoped, and the
    design would be a blanket waiver wearing a manifest.
    """
    line = '{"instrument": "A VPC built for this case alone: ' + _CIDR + ', a public subnet"}\n'
    root = make_payload(tmp_path, {"cases/F5-7b.json": line},
                        {"cases/F5-7b.json": [SRC_WITHOUT_WAIVER]})
    assert run(gp, root) == 1


def test_a_waiver_never_excuses_an_account_id(gp, tmp_path):
    """F5-7b's ALLOW entry is for a CIDR. Inheriting it must not carry an account ID with it.

    This is the 2026-08-19 failure in miniature: that file WAS known to the gate and DID carry a
    reviewed exception, and the account ID was three fields away.
    """
    line = '{"instrument": "' + _CIDR + ' and account ' + FAKE_ACCOUNT + '"}\n'
    root = make_payload(tmp_path, {"cases/F5-7b.json": line},
                        {"cases/F5-7b.json": [SRC_WITH_WAIVER]})
    assert run(gp, root) == 1


def test_a_shape_excused_hit_needs_no_source_at_all(gp, tmp_path):
    """An ARN already masked to the placeholder is a REDACTED ARN, which is what the gate asks for.

    Declared against a source with no exceptions of any kind, so the arm proves the excuse is
    shape-based and did not sneak in through provenance.
    """
    masked = (_A + ":aws:bedrock-agentcore:us-east-1:<account>:gateway/grx-gw-x")
    root = make_payload(tmp_path, {"cases/X-1.json": '{"Value": "' + masked + '"}\n'},
                        {"cases/X-1.json": [SRC_WITHOUT_WAIVER]})
    assert run(gp, root) == 0


# --------------------------------------------------------------------------------------------
# Structural guards. Each raises rather than returning 1: the gate could not establish what it was
# asked to establish, which is a different outcome from "looked and found something".
# --------------------------------------------------------------------------------------------

def test_a_payload_below_the_file_floor_fails(gp, tmp_path):
    root = make_payload(tmp_path, {"census.json": "{}\n"}, {}, pad_to=2)
    with pytest.raises(gp.GateError, match="below the floor"):
        run(gp, root)


def test_an_empty_payload_fails(gp, tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(gp.GateError):
        run(gp, root)


def test_a_missing_manifest_fails(gp, tmp_path):
    root = make_payload(tmp_path, {"census.json": "{}\n"}, {}, skip_manifest=True)
    with pytest.raises(gp.GateError, match="MANIFEST"):
        run(gp, root)


def test_a_file_on_disk_that_the_manifest_does_not_declare_fails(gp, tmp_path):
    """Not a subset check. An extra file nobody derived is exactly what a set-equality arm catches."""
    root = make_payload(tmp_path, {"census.json": "{}\n"}, {},
                        drop_from_manifest="census.json")
    with pytest.raises(gp.GateError, match="does not match its manifest"):
        run(gp, root)


def test_a_declared_file_missing_from_disk_fails(gp, tmp_path):
    root = make_payload(tmp_path, {"census.json": "{}\n"}, {})
    (root / "census.json").unlink()
    with pytest.raises(gp.GateError, match="does not match its manifest"):
        run(gp, root)


def test_content_that_drifted_from_the_manifest_fails(gp, tmp_path):
    """A payload edited after it was built. Gating it would establish nothing about the build."""
    root = make_payload(tmp_path, {"census.json": '{"n": 91}\n'}, {})
    (root / "census.json").write_text('{"n": 999}\n', encoding="utf-8")
    with pytest.raises(gp.GateError, match="differs from the manifest"):
        run(gp, root)


def test_a_file_with_no_provenance_fails(gp, tmp_path):
    root = make_payload(tmp_path, {"census.json": "{}\n"}, {})
    man = json.loads((root / "MANIFEST.json").read_text())
    man["provenance"].pop("census.json")
    (root / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    with pytest.raises(gp.GateError, match="no provenance"):
        run(gp, root)


def test_the_manifest_itself_needs_provenance(gp, tmp_path):
    """The manifest is an emitted file and is gated like one. It is also the arm the fixture broke on.

    `build_site_data.py` records the manifest's own sources; if a future edit drops that line, the
    payload stops being fully accounted for and this reds rather than the gate quietly accepting one
    unattributed file.
    """
    root = make_payload(tmp_path, {"census.json": "{}\n"}, {})
    man = json.loads((root / "MANIFEST.json").read_text())
    man["provenance"].pop("MANIFEST.json")
    (root / "MANIFEST.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    with pytest.raises(gp.GateError, match="no provenance"):
        run(gp, root)


def test_an_upload_list_that_differs_from_what_was_scanned_fails(gp, tmp_path):
    """The gate must be able to prove it read the bytes that are about to be uploaded."""
    root = make_payload(tmp_path, {"census.json": "{}\n"}, {})
    listing = tmp_path / "upload.txt"
    rels = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    listing.write_text("\n".join(rels[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(gp.GateError, match="upload list"):
        run(gp, root, "--upload-list", str(listing))


def test_a_matching_upload_list_passes(gp, tmp_path):
    root = make_payload(tmp_path, {"census.json": "{}\n"}, {})
    listing = tmp_path / "upload.txt"
    rels = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    listing.write_text("\n".join(rels) + "\n", encoding="utf-8")
    assert run(gp, root, "--upload-list", str(listing)) == 0


def test_a_payload_inside_the_repository_is_refused(gp, tmp_path):
    """Gating a copy in the wrong place would pass while the served bytes went unread."""
    with pytest.raises(gp.GateError, match="inside the repository"):
        run(gp, ROOT / "results")


# --------------------------------------------------------------------------------------------
# The real payload, when one has been built.
# --------------------------------------------------------------------------------------------

def test_the_real_payload_passes_if_it_has_been_built(gp):
    root = gp.DEFAULT_PAYLOAD
    if not (root / "MANIFEST.json").is_file():
        pytest.skip(f"no payload at {root}; run platform/build/build_site_data.py first")
    assert run(gp, root) == 0
