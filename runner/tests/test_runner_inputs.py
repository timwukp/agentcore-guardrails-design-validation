#!/usr/bin/env python3
"""`runner/sync.py external_inputs()` — the set of things the suite needs from outside the repo.

Why this file exists at all: the second suite run on the instance produced 47 non-green tests, and
21 of them were a single missing directory while most of the rest were a single missing file. Both
are named by `PREREGISTRATION.yaml` and neither is in the tree, so `push` could never have carried
them. The fix is a derivation, and a derivation is only worth having if it fails when it stops
deriving — so the tests below assert the properties, not the two answers.

The two answers ARE asserted in one place (`test_the_two_known_inputs_are_both_found`), because
"the walk still finds the document under test" is the regression this whole subcommand exists to
prevent. Everything else is written so that a third external input would be picked up rather than
silently dropped.
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner"))

import sync as SY                # noqa: E402

# Resolvable only on a machine that HAS the external inputs. They are outside the repo by
# definition, so a fresh clone cannot have them and these tests skip rather than fail — the same
# convention test_runner_policy.py uses for the gitignored evidence tree.
try:
    _INPUTS = SY.external_inputs()
except SystemExit as exc:
    _INPUTS, _WHY = (), str(exc)
else:
    _WHY = ""
needs_inputs = pytest.mark.skipif(
    not _INPUTS, reason=f"the external inputs are not on this machine: {_WHY}")


# ------------------------------------------------------------------ the derivation

@needs_inputs
def test_every_external_path_in_the_prereg_is_accounted_for():
    """The walk's result must equal an independent scan of the same file.

    Read from the YAML again here rather than from `external_inputs()`'s output, so the test cannot
    inherit the reader's bug — the shape of the 9-vs-10 sealed-unit defect this project already hit
    once, where the assertion and the code being asserted shared a mistake.
    """
    pr = yaml.safe_load((ROOT / "PREREGISTRATION.yaml").read_text(encoding="utf-8"))
    seen = []

    def scan(node):
        vals = (node.values() if isinstance(node, dict)
                else node if isinstance(node, list) else ())
        for val in vals:
            if isinstance(val, str) and val.startswith(("~/", "../")):
                seen.append(val)
            scan(val)

    scan(pr)
    assert seen, "the pre-registration names no external path; this test would prove nothing"
    assert sorted(seen) == sorted(s["declared"] for s in _INPUTS)


@needs_inputs
def test_the_two_known_inputs_are_both_found():
    """The regression this subcommand exists to prevent, named rather than implied.

    `~/…` is the document under test and `../…` is the PII source corpus; the instance was missing
    both. If a future edit narrows the walk so that one of them stops matching, the failure has to
    land here and not on the instance forty minutes into a suite run.
    """
    by_kind = {s["kind"]: s for s in _INPUTS}
    assert set(by_kind) == {"home", "repo-parent"}
    assert by_kind["home"]["src"].name.endswith(".md")
    assert by_kind["home"]["src"].is_file()
    assert by_kind["repo-parent"]["src"].is_dir()
    assert by_kind["repo-parent"]["src"].name == "pii-corpus"


@needs_inputs
def test_each_input_resolves_the_way_the_code_under_test_resolves_it():
    """`~/` against `Path.home()`, `../` against the repo root. Not against each other.

    This is the property that decides whether the file lands where `claims/check_coverage.py` and
    `verify_prereg.py` will look for it. Getting it backwards would still produce a tarball, still
    upload cleanly, and still leave every dependent test failing for a reason that names neither.
    """
    for spec in _INPUTS:
        if spec["kind"] == "home":
            assert spec["src"] == Path.home() / spec["declared"][2:]
        else:
            assert spec["src"] == ROOT.parent / spec["declared"][3:]


@needs_inputs
def test_a_declared_hash_is_checked_rather_than_recorded():
    """The document's sha256 is pinned by the pre-registration, so the check is the point.

    Mutation: hand the reader a pre-registration whose declared hash cannot match, and it must
    refuse. Without this arm the sha256 field could be read, stored in the manifest and never
    compared, and the failure mode — an instance measuring a different document while every result
    still says v1.2 — would be invisible.
    """
    pinned = [s for s in _INPUTS if s["sha256"]]
    assert pinned, "no external input declares a hash; this test would prove nothing"
    for spec in pinned:
        assert hashlib.sha256(spec["src"].read_bytes()).hexdigest() == spec["sha256"]


def test_a_prereg_declaring_a_wrong_hash_is_refused(monkeypatch, tmp_path):
    """The mutation for the arm above, on a synthetic pre-registration so nothing sealed is touched.

    `PREREGISTRATION.yaml` is a sealed bound artifact pinned by sha256, so the file on disk is never
    edited — the module's path constant is repointed instead.
    """
    doc = tmp_path / "Downloads" / "subject.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("the document under test", encoding="utf-8")
    fake = tmp_path / "PREREG.yaml"
    fake.write_text(yaml.safe_dump({
        "meta": {"document_under_test": {"path": "~/Downloads/subject.md",
                                         "sha256": "0" * 64}}}), encoding="utf-8")
    monkeypatch.setattr(SY, "PREREG", fake)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(SystemExit) as exc:
        SY.external_inputs()
    assert "not the sealed artifact" in str(exc.value)

    # And the control: the same file with its real hash is accepted, so the refusal above is the
    # hash comparison and not some other objection to a synthetic pre-registration.
    fake.write_text(yaml.safe_dump({
        "meta": {"document_under_test": {
            "path": "~/Downloads/subject.md",
            "sha256": hashlib.sha256(doc.read_bytes()).hexdigest()}}}), encoding="utf-8")
    got = SY.external_inputs()
    assert [s["declared"] for s in got] == ["~/Downloads/subject.md"]


def test_a_prereg_naming_nothing_external_is_an_error_not_an_empty_push(monkeypatch, tmp_path):
    """An empty result means the walk stopped matching, which is the failure worth catching.

    Returning `()` would make `push-inputs` print a cheerful zero and leave the instance exactly as
    broken as it was before the subcommand existed.
    """
    fake = tmp_path / "PREREG.yaml"
    fake.write_text(yaml.safe_dump({"meta": {"note": "nothing outside the repo"}}), encoding="utf-8")
    monkeypatch.setattr(SY, "PREREG", fake)
    with pytest.raises(SystemExit) as exc:
        SY.external_inputs()
    assert "names no external path" in str(exc.value)


def test_a_declared_path_that_is_absent_here_is_refused(monkeypatch, tmp_path):
    """The instance cannot be handed what this machine does not have; say so at push time."""
    fake = tmp_path / "PREREG.yaml"
    fake.write_text(yaml.safe_dump({"corpora": {"x": {"path": "../not-a-real-sibling/corpus"}}}),
                    encoding="utf-8")
    monkeypatch.setattr(SY, "PREREG", fake)
    with pytest.raises(SystemExit) as exc:
        SY.external_inputs()
    assert "does not exist here" in str(exc.value)


# ------------------------------------------------------------------ the archive layout

@needs_inputs
def test_the_archive_layout_is_the_destination(tmp_path, monkeypatch):
    """Packing and unpacking, end to end, without S3 — the property `grx-inputs` depends on.

    The shell helper holds no destination of its own: it extracts `inputs/home/…` to each home and
    `inputs/repo-parent/…` beside the repo, and everything below the prefix is whatever this
    function wrote. So the test that matters is that unpacking the archive reproduces the declared
    relative paths exactly, because a `--strip-components` off by one produces a tarball that
    installs cleanly into the wrong place (feedback_span_vs_points_offbyone).
    """
    tgz = tmp_path / "inputs.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        for spec in _INPUTS:
            base = f"inputs/{spec['kind']}"
            if spec["dest_parent_rel"]:
                base += "/" + spec["dest_parent_rel"]
            if spec["src"].is_file():
                tar.add(spec["src"], arcname=f"{base}/{spec['src'].name}")
            else:
                for path in sorted(spec["src"].rglob("*")):
                    if path.is_file() and path.name != ".DS_Store":
                        tar.add(path, arcname=f"{base}/{spec['src'].name}/"
                                              f"{path.relative_to(spec['src'])}")
    with tarfile.open(tgz) as tar:
        names = tar.getnames()
        out = tmp_path / "unpacked"
        tar.extractall(out, filter="data")

    assert names, "packed nothing"
    for spec in _INPUTS:
        # `--strip-components=1` in grx-inputs removes the leading `inputs/`; the kind is then the
        # root each copy targets.
        root = out / "inputs" / spec["kind"]
        rel = (Path(spec["dest_parent_rel"]) / spec["src"].name if spec["dest_parent_rel"]
               else Path(spec["src"].name))
        assert (root / rel).exists(), f"{spec['declared']} did not land at {rel} under {spec['kind']}"
        if spec["src"].is_file():
            assert (root / rel).read_bytes() == spec["src"].read_bytes()
        else:
            packed = {str(p.relative_to(root / rel)) for p in (root / rel).rglob("*")
                      if p.is_file()}
            here = {str(p.relative_to(spec["src"])) for p in spec["src"].rglob("*")
                    if p.is_file() and p.name != ".DS_Store"}
            assert packed == here


@needs_inputs
def test_the_shell_helper_and_the_packer_agree_on_the_two_prefixes():
    """`grx-inputs` names `inputs/home` and `inputs/repo-parent`; `cmd_push_inputs` writes them.

    Two files, one convention, and nothing in between to enforce it — so it is enforced here. A
    `kind` renamed on one side only would leave the helper copying an empty directory and reporting
    success.
    """
    helper = (ROOT / "runner" / "bootstrap.sh").read_text(encoding="utf-8")
    for kind in {s["kind"] for s in _INPUTS}:
        assert f"/opt/grx/tmp/inputs/{kind}" in helper, \
            f"bootstrap.sh does not install the {kind!r} prefix that push-inputs writes"
