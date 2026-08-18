#!/usr/bin/env python3
"""`tools/sync_handover_bundle.py` deletes files in a directory outside this repo. Pin what it does.

Why this file exists
--------------------
The hand-over bundle had been assembled and re-synced four times by hand and had drifted every time;
the fourth drift was found on 2026-08-17 with its README claiming **21** deficiencies against a
register of **31**, a commit five merges stale, two merged pull requests described as open, a RUNNING
EC2 runner described as stopped, and `validation/WHITEPAPER.md` simply absent. The sync script exists
to replace that remembering with derivation.

Which makes the script itself the new risk. It mirrors repo → bundle and **prunes**: any bundle file
with no repo counterpart is deleted. Two failure modes are therefore worth more than the convenience
it buys, and both are pinned below with an arm that fails if the guard is removed:

* an **under-reading scan**. If the include predicate broke and returned few files, every other
  bundle file becomes "absent from the repo" and the plan becomes *delete the archive*. This is
  `feedback_zero_file_scan_is_error` in its most expensive form, so the floor is asserted here and
  not merely documented there.
* a **content comparison that trusts metadata**. `shutil.copy2` restores the source mtime, so a copy
  can carry a timestamp that argues it is fresh while holding different bytes — this project has
  been bitten by exactly that twice (`feedback_copy2_serves_the_mutant`,
  `feedback_pyc_serves_the_mutant`). `test_plan_compares_bytes_not_metadata` writes two files of
  equal length and identical mtime and requires the plan to notice.

The deliberate disagreement with `lib/tests/scan_scope.py` is also pinned. That predicate answers
"is this file this repo's own source?" and excludes `evidence/`; this one answers "does this file
belong in a local hand-over archive?" and includes it. A future tidy-up that unifies the two would
either publish 32,000 unredacted API responses or silently drop the archive the bundle exists for,
so the test states the divergence as intended behaviour rather than leaving it to be inferred.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SUBJECT_MODULE_NAME = "_sync_handover_bundle"


def _subject():
    spec = importlib.util.spec_from_file_location(
        SUBJECT_MODULE_NAME, REPO / "tools" / "sync_handover_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _subject()


def _bundle(root: Path, files: dict[str, bytes] | None = None) -> Path:
    """A directory that satisfies every bundle marker, so `resolve_bundle` accepts it."""
    bundle = root / "bundle"
    (bundle / "validation").mkdir(parents=True)
    (bundle / "deliverables").mkdir()
    (bundle / "document-lineage").mkdir()
    (bundle / "README.md").write_text("readme\n", encoding="utf-8")
    (bundle / "MANIFEST.sha256").write_text("", encoding="utf-8")
    for rel, data in (files or {}).items():
        path = bundle / "validation" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return bundle


# ---------------------------------------------------------------------------------------------
# What belongs in the bundle
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "runner/.state/runner.json",          # the bookkeeping that says which instance produced this
    "runner/.state/manifest.txt",
    "results/FINDING-F3-10.md",
    "claims/triage.csv",
    "agentcore_guardrails_best_practices_v1.4.pptx",
])
def test_these_belong_in_the_bundle(mod, rel):
    assert mod.exclusion_reason(Path(rel)) is None, rel


@pytest.mark.parametrize("rel", [
    "lib/__pycache__/redact.cpython-312.pyc",
    ".pytest_cache/CACHEDIR.TAG",
    "f1_config/.wheel_cache/botocore-1.40.0.whl",
    "runner/.staging/20260813T000000Z/out/x.json",
    "runner/.state/incoming/20260812T130844Z/out/x.json",
    "runner/.state/evidence.tar.gz",
    "results/~$deck.pptx",
    "lib/redact.pyc",
])
def test_these_do_not(mod, rel):
    assert mod.exclusion_reason(Path(rel)) is not None, rel


def test_the_evidence_tree_is_included_here_and_excluded_there(mod):
    """The one place this predicate and `scan_scope.out_of_scope` must disagree — on purpose.

    Unifying them would either publish unredacted evidence or drop it from the archive whose entire
    value is holding it. See this module's docstring.
    """
    sys.path.insert(0, str(REPO / "lib" / "tests"))
    from scan_scope import out_of_scope

    rel = Path("evidence/r20260810T130945Z/f1/F1-26/summary.json")
    assert out_of_scope(rel) is True, "scan_scope must keep evidence out of a SOURCE scan"
    assert mod.exclusion_reason(rel) is None, "the bundle must keep evidence IN"


def test_a_new_virtualenv_is_covered_before_it_is_created(mod):
    assert mod.EXCLUDED_DIR_PREFIXES == (".venv",), (
        "if this becomes a list of exact venv names it stops noticing the next one — the defect "
        "lib/tests/scan_scope.py was written to end")


def test_every_member_of_the_virtualenv_family_is_excluded(mod):
    """The names are BUILT from the prefix, not listed.

    The first version of this file listed `.venv-oracle`, `.venv-figs` and an invented future name in
    a parametrize table, and `lib/tests/test_scan_scope.py::
    test_no_scanner_carries_its_own_virtualenv_name_list` failed it on the first full run — a literal
    holding two or more `.venv…` strings is an attempt to enumerate a family a prefix already covers,
    and it is the enumeration that goes stale when the fourth member arrives (DEV-P4-41, DEV-P4-42).
    Deriving the paths from the prefix is both a passing file and a stronger test: it asserts the
    RULE, so it covers the next member without being edited.
    """
    prefix = mod.EXCLUDED_DIR_PREFIXES[0]
    for suffix in ("", "-oracle", "-figs", "-a-name-nobody-has-chosen-yet"):
        rel = Path(f"{prefix}{suffix}") / "lib" / "python3.12" / "site-packages" / "x.py"
        assert mod.exclusion_reason(rel) is not None, rel


def test_repo_files_refuses_an_implausibly_small_scan(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "only.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        mod.repo_files()
    assert "floor" in str(excinfo.value)


# ---------------------------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------------------------

def test_plan_detects_add_replace_and_delete(mod, tmp_path):
    bundle = _bundle(tmp_path, {"same.txt": b"same", "old.txt": b"gone", "drift.txt": b"aaa"})
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    (repo / "same.txt").write_bytes(b"same")
    (repo / "drift.txt").write_bytes(b"bbbb")
    (repo / "sub" / "new.txt").write_bytes(b"new")
    source = {p.relative_to(repo): p for p in repo.rglob("*") if p.is_file()}

    plan = mod.plan_mirror(bundle, source)
    assert plan.add == [Path("sub/new.txt")]
    assert plan.replace == [Path("drift.txt")]
    assert plan.delete == [Path("old.txt")]
    # A file that matched is hashed once and the digest reused for the manifest, not re-read.
    assert plan.hashes[Path("validation/same.txt")] == mod.sha256(repo / "same.txt")


def test_plan_compares_bytes_not_metadata(mod, tmp_path):
    """Equal size, identical mtime, different content — copy2's exact signature. Must be REPLACE."""
    bundle = _bundle(tmp_path, {"f.txt": b"AAAA"})
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_bytes(b"BBBB")
    stat = (bundle / "validation" / "f.txt").stat()
    import os
    os.utime(repo / "f.txt", (stat.st_atime, stat.st_mtime))
    assert (repo / "f.txt").stat().st_mtime == stat.st_mtime
    assert (repo / "f.txt").stat().st_size == stat.st_size

    plan = mod.plan_mirror(bundle, {Path("f.txt"): repo / "f.txt"})
    assert plan.replace == [Path("f.txt")]


def test_apply_copies_prunes_and_removes_the_emptied_directory(mod, tmp_path):
    bundle = _bundle(tmp_path, {"keep.txt": b"k", "dead/old.txt": b"o"})
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "keep.txt").write_bytes(b"k")
    (repo / "added.txt").write_bytes(b"a")
    source = {p.relative_to(repo): p for p in repo.rglob("*") if p.is_file()}

    plan = mod.plan_mirror(bundle, source)
    mod.apply_mirror(bundle, source, plan, allow_prune=True)

    mirror = bundle / "validation"
    assert (mirror / "added.txt").read_bytes() == b"a"
    assert not (mirror / "dead" / "old.txt").exists()
    assert not (mirror / "dead").exists(), "an emptied directory is left behind otherwise"


def test_apply_refuses_a_mass_prune_without_the_flag(mod, tmp_path):
    bundle = _bundle(tmp_path, {f"f{i}.txt": b"x" for i in range(40)})
    plan = mod.plan_mirror(bundle, {})
    with pytest.raises(SystemExit) as excinfo:
        mod.apply_mirror(bundle, {}, plan, allow_prune=False)
    assert "refusing to delete" in str(excinfo.value)
    assert len(list((bundle / "validation").iterdir())) == 40, "nothing may be deleted on refusal"


def test_resolve_bundle_rejects_a_directory_that_is_not_the_bundle(mod, tmp_path):
    bundle = _bundle(tmp_path)
    (bundle / "MANIFEST.sha256").unlink()
    with pytest.raises(SystemExit) as excinfo:
        mod.resolve_bundle(str(bundle))
    assert "MANIFEST.sha256" in str(excinfo.value)


def test_resolve_bundle_rejects_syncing_a_copy_onto_itself(mod, tmp_path, monkeypatch):
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(mod, "ROOT", bundle / "validation")
    with pytest.raises(SystemExit) as excinfo:
        mod.resolve_bundle(str(bundle))
    assert "onto itself" in str(excinfo.value)


# ---------------------------------------------------------------------------------------------
# The manifest, checked against the real `shasum -c` rather than against my idea of its format
# ---------------------------------------------------------------------------------------------

def test_the_manifest_is_sorted_excludes_itself_and_shasum_c_accepts_it(mod, tmp_path):
    bundle = _bundle(tmp_path, {"b.txt": b"b", "a/a.txt": b"a"})
    lines = mod.manifest_lines(bundle, {})
    paths = [line.split("  ./", 1)[1] for line in lines]

    assert paths == sorted(paths)
    assert "MANIFEST.sha256" not in paths, "a manifest listing itself can never verify"
    assert "validation/a/a.txt" in paths and "README.md" in paths

    (bundle / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    done = subprocess.run(["shasum", "-c", "MANIFEST.sha256"], cwd=bundle,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count(": OK") == len(lines)


def test_the_manifest_reuses_a_known_digest_without_rereading(mod, tmp_path):
    bundle = _bundle(tmp_path, {"f.txt": b"real"})
    lines = mod.manifest_lines(bundle, {Path("validation/f.txt"): "deadbeef"})
    assert any(line == "deadbeef  ./validation/f.txt" for line in lines)


# ---------------------------------------------------------------------------------------------
# The README's derivable numbers
# ---------------------------------------------------------------------------------------------

def _readme(bundle: Path, text: str) -> None:
    (bundle / "README.md").write_text(text, encoding="utf-8")


def test_claims_pass_when_every_number_agrees(mod, tmp_path, monkeypatch):
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(mod, "register_size", lambda: 31)
    monkeypatch.setattr(mod, "EXPECTED_CLAIM_SITES", {"deficiencies": 2, "inventory": 1, "manifest": 1})
    _readme(bundle, "sha256 of all 32,808 files\n31 named deficiencies\n**31** deficiencies\n"
                    "**32,809 files, 199 MB**\n")
    assert mod.check_claims(bundle, file_count=32_809, megabytes=199, manifest_entries=32_808) == []


def test_a_stale_deficiency_count_is_reported_with_the_derived_value(mod, tmp_path, monkeypatch):
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(mod, "register_size", lambda: 31)
    monkeypatch.setattr(mod, "EXPECTED_CLAIM_SITES", {"deficiencies": 1, "inventory": 0, "manifest": 0})
    _readme(bundle, "21 named deficiencies\n")
    failures = mod.check_claims(bundle, file_count=1, megabytes=1, manifest_entries=1)
    assert len(failures) == 1 and "31" in failures[0] and "README.md:1" in failures[0]


def test_a_site_that_stops_matching_is_a_failure_not_a_pass(mod, tmp_path, monkeypatch):
    """The exact-count assertion. A rewording that escapes the regex must fail loudly."""
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(mod, "register_size", lambda: 31)
    monkeypatch.setattr(mod, "EXPECTED_CLAIM_SITES", {"deficiencies": 2, "inventory": 0, "manifest": 0})
    _readme(bundle, "31 named deficiencies\nthirty-one shortcomings\n")
    failures = mod.check_claims(bundle, file_count=1, megabytes=1, manifest_entries=1)
    assert any("expected exactly 2" in f for f in failures)


def test_an_unrelated_size_figure_is_not_read_as_the_bundle_size(mod, tmp_path, monkeypatch):
    """The regression the first draft of this check had.

    A loose `(\\d+) MB` matched `validation/evidence/` at 150 MB, the excluded virtualenvs at 284 MB
    and the excluded wheel cache at 224 MB, and reported all three as disagreeing with the bundle's
    size — three failures about a quantity nobody had claimed. The inventory is matched by its full
    canonical phrasing instead (`feedback_label_must_match_computation`).
    """
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(mod, "register_size", lambda: 31)
    monkeypatch.setattr(mod, "EXPECTED_CLAIM_SITES", {"deficiencies": 0, "inventory": 1, "manifest": 0})
    _readme(bundle, "`validation/evidence/` (150 MB) — the raw archive\n"
                    "`.venv-*/` (284 MB) | absolute shebangs\n"
                    "**32,809 files, 199 MB**\n")
    assert mod.check_claims(bundle, file_count=32_809, megabytes=199, manifest_entries=1) == []


def test_the_file_count_and_the_manifest_count_are_checked_separately(mod, tmp_path, monkeypatch):
    """They differ by one and are stated in two sentences about two things.

    Inferring one from the other would let a wrong manifest sentence ride on a right inventory one
    (`feedback_two_numbers_two_claims`).
    """
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(mod, "register_size", lambda: 31)
    monkeypatch.setattr(mod, "EXPECTED_CLAIM_SITES", {"deficiencies": 0, "inventory": 1, "manifest": 1})
    _readme(bundle, "sha256 of all 32,809 files\n**32,809 files, 199 MB**\n")
    failures = mod.check_claims(bundle, file_count=32_809, megabytes=199, manifest_entries=32_808)
    assert len(failures) == 1 and "manifest" in failures[0]


def test_the_inventory_checks_both_of_its_numbers(mod, tmp_path, monkeypatch):
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(mod, "register_size", lambda: 31)
    monkeypatch.setattr(mod, "EXPECTED_CLAIM_SITES", {"deficiencies": 0, "inventory": 1, "manifest": 0})
    _readme(bundle, "**32,809 files, 250 MB**\n")
    failures = mod.check_claims(bundle, file_count=32_809, megabytes=199, manifest_entries=1)
    assert len(failures) == 1, "the right file count must not excuse the wrong size"


def test_register_size_is_derived_from_the_real_register(mod):
    """Not a fixture: the number this script checks against must come from the live file."""
    assert mod.register_size() == len(mod.ITEM_RE.findall(
        (REPO / "FUTURE-WORK.md").read_text(encoding="utf-8")))
    assert mod.register_size() > 20
