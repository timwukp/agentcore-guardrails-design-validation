"""Mutation suite for corpora/verify_corpora.py.

The gate asserts three properties (manifest matches disk, build is byte-reproducible,
kappa passes and is about the live corpus). Each mutation below breaks exactly one of
them and the gate must fail. Without this file, `verify_corpora.py` would be a script
that prints OK -- and a gate that has never been observed to fail is indistinguishable
from a gate that cannot.

Everything runs against a COPY in tmp_path. The corpus and the pre-registration are
the artefacts under test; a suite that mutated them in place could leave the tree
poisoned if it died mid-run, which has already happened once in this project with a
redaction canary.

The copy is what makes the reproducibility check meaningful here too: `build.py` is
invoked with `cwd` set to the copy, so it reads the copy's PREREGISTRATION.yaml and
writes into the copy's tmp dir. A mutation to the copied corpus is therefore visible
to the rebuild exactly as a hand-edit of the real corpus would be.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GATE_REL = Path("corpora") / "verify_corpora.py"

# The build reuses items from an EXTERNAL source corpus (the 108-case PII corpus).
# Its path is recorded in the pre-registration as a path relative to ROOT, so a copy
# of the tree at a different depth would not find it. Resolved once here so the
# fixture can rewrite it to an absolute path.

@pytest.fixture
def tree(tmp_path: Path, copy_repo) -> Path:
    """A working copy of the repo, with the external source path made absolute.

    The exclusion list is `conftest.copy_repo`'s, derived from `.gitignore` in one place; the
    hand-written list this fixture used to carry omitted `f1_config/.wheel_cache/` and so wrote
    214 MB of pip cache per arm (DEV-P4-36). `results` is excluded per call because nothing
    below this line reads it.
    """
    import yaml
    dst = copy_repo(tmp_path / "grx", "results")

    pr_path = dst / "PREREGISTRATION.yaml"
    pr = yaml.safe_load(pr_path.read_text(encoding="utf-8"))
    rel = pr["corpora"]["pii"]["source_corpus_audit"]["path"]
    src = (ROOT / rel).resolve()
    assert src.is_dir(), (
        f"PRECONDITION: the source corpus is not at {src}; every mutation below "
        f"would fail for that reason instead of the one it names")
    # Rewrite the path in the TEXT, not via yaml.dump: re-serialising the file would
    # change its bytes and break the seal, making every run fail on the hash instead
    # of on the mutation.
    text = pr_path.read_text(encoding="utf-8")
    assert text.count(rel) == 1, f"{rel!r} appears {text.count(rel)}× — cannot rewrite"
    pr_path.write_text(text.replace(rel, str(src)), encoding="utf-8")
    # That edit breaks the seal, so re-stamp the copy. The seal is verified by
    # verify_prereg.py, which is not what this suite tests.
    import hashlib
    (dst / "PREREGISTRATION.sha256").write_text(
        hashlib.sha256(pr_path.read_bytes()).hexdigest() + "  PREREGISTRATION.yaml\n",
        encoding="utf-8")
    _restamp(dst)
    return dst


def _restamp(tree: Path) -> None:
    """Re-run the generators so the copy's derived artefacts match its own seal.

    The path rewrite above changes the pre-registration's bytes, hence its seal, so
    both derived artefacts now carry a stamp from a different seal -- which the gate
    correctly rejects. Regenerating them is exactly the remedy the gate names, and
    doing it here means the control arm tests the gate rather than the fixture.
    """
    seal = (tree / "PREREGISTRATION.sha256").read_text(encoding="utf-8").split()[0]
    for rel in ("corpora/MANIFEST.json", "corpora/irr_report.json"):
        p = tree / rel
        d = json.loads(p.read_text(encoding="utf-8"))
        d["prereg_sha256"] = seal
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                     encoding="utf-8")


def run(tree: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(tree / GATE_REL)],
                          capture_output=True, text=True, cwd=str(tree))


def read_json(tree: Path, rel: str) -> dict:
    return json.loads((tree / rel).read_text(encoding="utf-8"))


def write_json(tree: Path, rel: str, d: dict) -> None:
    (tree / rel).write_text(
        json.dumps(d, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")


# ---- control arms ------------------------------------------------------------

def test_control_arm_the_unmutated_copy_passes(tree):
    """Without this, every mutation below could be killing the fixture."""
    r = run(tree)
    assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert "OK —" in r.stdout


def test_control_arm_every_check_clears_its_floor(tree):
    """The floors must be satisfiable by the real artefacts.

    A floor set above the true yield fails in service, in a way that has nothing to
    do with the corpus. That happened while writing the gate: kappa_gate's floor was
    11 and it yields 10.
    """
    r = run(tree)
    assert r.returncode == 0
    assert "stops asserting" not in r.stderr


# ---- property 1: the manifest describes the files on disk -------------------

def test_kills_an_edited_corpus_file(tree):
    p = tree / "corpora" / "benign" / "benign.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = lines[0].replace("text", "txet", 1)
    p.write_text("".join(lines), encoding="utf-8")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "sha256" in r.stderr


def test_kills_a_deleted_corpus_file(tree):
    (tree / "corpora" / "content_filter" / "hate.jsonl").unlink()
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "absent on disk" in r.stderr


def test_kills_a_removed_line_even_when_the_manifest_hash_is_updated(tree):
    """The item-count check, independent of the checksum check.

    An editor who removes a line and re-runs `shasum` would leave the checksum
    consistent and the count wrong. Both must be pinned, or the pair is one check.
    """
    import hashlib
    p = tree / "corpora" / "benign" / "benign.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    p.write_text("".join(lines[:-1]), encoding="utf-8")
    man = read_json(tree, "corpora/MANIFEST.json")
    man["files"]["benign/benign.jsonl"]["sha256"] = hashlib.sha256(
        p.read_bytes()).hexdigest()
    write_json(tree, "corpora/MANIFEST.json", man)
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "lines, manifest says" in r.stderr


def test_kills_an_unaccounted_corpus_file(tree):
    """A .jsonl no manifest entry names: invisible to a checksum sweep."""
    (tree / "corpora" / "benign" / "extra.jsonl").write_text(
        '{"label": "CLEAN", "text": "smuggled in"}\n', encoding="utf-8")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "not in the\nmanifest" in r.stderr.replace("  ", " ") or \
           "not in the" in r.stderr


def test_kills_a_manifest_total_that_does_not_add_up(tree):
    man = read_json(tree, "corpora/MANIFEST.json")
    man["total_items"] += 1
    write_json(tree, "corpora/MANIFEST.json", man)
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "total_items" in r.stderr


# ---- property 2: the build is byte-reproducible -----------------------------

def test_kills_a_hand_edited_item_that_the_manifest_agrees_with(tree):
    """The reproducibility check's reason for existing.

    Here the manifest is updated to match the edit, so property 1 is satisfied and
    only the rebuild can tell that the text is not what the templates generate. This
    is the mutation that separates "the manifest is honest" from "the corpus is
    generated".
    """
    import hashlib
    p = tree / "corpora" / "benign" / "benign.jsonl"
    items = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]
    items[0]["text"] = "a sentence no template in banks.py can produce"
    p.write_text("".join(json.dumps(i, ensure_ascii=False, sort_keys=True) + "\n"
                         for i in items), encoding="utf-8")
    man = read_json(tree, "corpora/MANIFEST.json")
    man["files"]["benign/benign.jsonl"]["sha256"] = hashlib.sha256(
        p.read_bytes()).hexdigest()
    write_json(tree, "corpora/MANIFEST.json", man)

    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "rebuilt bytes differ" in r.stderr


def test_kills_a_nondeterministic_builder(tree):
    """If the build stopped being deterministic, the corpus stops being evidence."""
    p = tree / "corpora" / "build.py"
    src = p.read_text(encoding="utf-8")
    needle = "def build_benign() -> list[dict]:"
    assert needle in src, "PRECONDITION: build_benign no longer has that signature"
    src = src.replace(needle, needle + "\n    import random as _r", 1)
    # Perturb one emitted item in a way that depends on nothing the seal fixes.
    old = 'record("benign/benign.jsonl", benign)'
    assert old in src, "PRECONDITION: the benign record call changed shape"
    src = src.replace(
        old,
        'import random as _r2\n'
        '    benign[0]["text"] = benign[0]["text"] + str(_r2.random())\n'
        '    ' + old, 1)
    p.write_text(src, encoding="utf-8")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "rebuilt bytes differ" in r.stderr


def test_kills_a_builder_that_ignores_out_and_writes_nothing_there(tree):
    """An empty rebuilt tree must not read as 'identical'.

    The mutation exits 0: it builds a complete corpus, just not where it was asked to.
    Suppressing the writes outright would instead crash the builder (it reads each
    file back to checksum it) and this test would pass via the build-failure branch
    without ever exercising the empty-tree guard -- which is what its first two
    versions did.
    """
    p = tree / "corpora" / "build.py"
    src = p.read_text(encoding="utf-8")
    needle = 'out = Path(args.out).resolve() if args.out else ROOT / "corpora"'
    assert needle in src, "PRECONDITION: the --out wiring changed shape"
    src = src.replace(needle, 'import tempfile as _t\n'
                              '    out = Path(_t.mkdtemp(prefix="grx-ignored-"))', 1)
    p.write_text(src, encoding="utf-8")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "wrote nothing" in r.stderr, r.stderr


def test_kills_a_builder_that_emits_a_file_the_corpus_does_not_have(tree):
    """Membership, not just content: an extra file in the rebuild must fail.

    Comparing only the files present in BOTH trees would pass here, because every
    shared file is identical. That is the loophole this branch closes.
    """
    p = tree / "corpora" / "build.py"
    src = p.read_text(encoding="utf-8")
    needle = 'record("benign/benign.jsonl", benign)'
    assert needle in src, "PRECONDITION: the benign record call changed shape"
    src = src.replace(needle, needle + '\n    write_jsonl(out / "benign" / "surprise.jsonl", benign[:1])', 1)
    p.write_text(src, encoding="utf-8")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "MEMBERSHIP" in r.stderr, r.stderr


def test_kills_a_build_that_fails_outright(tree):
    """rc != 0 from the builder must not be mistaken for 'nothing differed'."""
    p = tree / "corpora" / "build.py"
    src = p.read_text(encoding="utf-8")
    src = src.replace("def main(argv: list[str] | None = None) -> int:",
                      "def main(argv: list[str] | None = None) -> int:\n"
                      "    raise SystemExit(3)", 1)
    p.write_text(src, encoding="utf-8")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "build.py --out failed" in r.stderr


# ---- property 3: kappa, about this corpus and this seal ---------------------

def test_kills_a_kappa_below_the_gate(tree):
    irr = read_json(tree, "corpora/irr_report.json")
    irr["kappa"] = 0.42
    irr["passes_gate"] = False
    write_json(tree, "corpora/irr_report.json", irr)
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "below the gate" in r.stderr


def test_kills_a_passes_gate_flag_that_lies(tree):
    """The flag must agree with the arithmetic, not be trusted."""
    irr = read_json(tree, "corpora/irr_report.json")
    irr["passes_gate"] = False          # kappa is unchanged and passes
    write_json(tree, "corpora/irr_report.json", irr)
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "passes_gate disagrees" in r.stderr


def test_kills_a_lowered_gate(tree):
    """Lowering the gate in the report must not lower the gate.

    The threshold is a pre-registered quantity. A report that carries its own copy
    could relax it after seeing the data, which is the whole failure mode
    pre-registration exists to prevent.
    """
    irr = read_json(tree, "corpora/irr_report.json")
    irr["gate"] = 0.3
    write_json(tree, "corpora/irr_report.json", irr)
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "not the sealed gate" in r.stderr


def test_kills_an_audit_of_a_different_corpus(tree):
    """kappa can pass while describing a corpus that has since changed."""
    irr = read_json(tree, "corpora/irr_report.json")
    irr["n_corpus"] = irr["n_corpus"] - 100
    write_json(tree, "corpora/irr_report.json", irr)
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "the audit rated a corpus of" in r.stderr


def test_kills_unsure_counted_as_agreement(tree):
    irr = read_json(tree, "corpora/irr_report.json")
    irr["unsure_counted_as"] = "agreement"
    write_json(tree, "corpora/irr_report.json", irr)
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "unsure_counted_as" in r.stderr


def test_kills_a_stale_provenance_stamp(tree):
    """The decision recorded in the gate's docstring, made checkable.

    A derived artefact stamped with an older seal is ambiguous on its own -- valid
    but old, or silently stale. The gate resolves it by requiring regenerability, so
    a stale stamp must fail and the remedy is to re-run the generator.
    """
    for rel in ("corpora/MANIFEST.json", "corpora/irr_report.json"):
        d = read_json(tree, rel)
        d["prereg_sha256"] = "0" * 64
        write_json(tree, rel, d)
        r = run(tree)
        assert r.returncode == 1, f"{rel} stale stamp survived:\n{r.stdout}"
        assert "re-run the generator" in r.stderr
        # restore before testing the next one, so each is tested alone
        _restamp(tree)
    assert run(tree).returncode == 0, "the restore did not restore"


# ---- the gate's own failure modes -------------------------------------------

def test_a_missing_artifact_is_rc2_not_a_pass(tree):
    """per feedback_guard_tool_exit_codes: a gate that cannot run is not clean."""
    (tree / "corpora" / "irr_report.json").unlink()
    r = run(tree)
    assert r.returncode == 2, r.stdout
    assert "cannot run" in r.stderr


def test_a_check_that_stops_asserting_is_rc2_not_a_pass(tree):
    """Neutralise the smallest check and confirm the floor catches it.

    A deleted or gutted check runs zero assertions and reports no problems, which is
    byte-identical to a passing check unless something pins the yield.
    """
    p = tree / GATE_REL
    src = p.read_text(encoding="utf-8")
    needle = "def check_kappa(problems: list[str]) -> int:"
    assert needle in src
    src = src.replace(needle, needle + "\n    return 0", 1)
    p.write_text(src, encoding="utf-8")
    r = run(tree)
    assert r.returncode == 2, r.stdout
    assert "kappa_gate ran 0 assertion" in r.stderr


def test_the_finding_and_the_gate_agree_on_the_numbers():
    """§7 item 3 cites the gate's assertion count and this suite's size.

    Re-derived from the live artefacts rather than pinned as literals, so growing the
    gate updates the report instead of failing a test — the same rule as the seal.
    Both are asserted as ceilings: a report may understate, never overstate.
    """
    gate = subprocess.run([sys.executable, str(ROOT / GATE_REL)],
                          capture_output=True, text=True, cwd=str(ROOT))
    assert gate.returncode == 0, f"{gate.stdout}\n{gate.stderr}"
    import re
    m = re.search(r"OK — (\d+) assertions", gate.stdout)
    assert m, f"the gate's output changed shape: {gate.stdout!r}"
    n_assert = int(m.group(1))

    col = subprocess.run([sys.executable, "-m", "pytest", str(Path(__file__)), "-q",
                          "--collect-only", "-p", "no:cacheprovider"],
                         capture_output=True, text=True, cwd=str(ROOT))
    c = re.search(r"(\d+) tests? collected", col.stdout)
    assert c, f"could not read a collected count:\n{col.stdout[-400:]}"
    n_tests = int(c.group(1))
    assert n_tests > 0, "collecting zero tests must not read as agreement"

    doc = (ROOT / "results" / "FINDING-P0-PREREG.md").read_text(encoding="utf-8")
    d = re.search(r"\((\d+) assertions, (\d+) mutation tests\)", doc)
    assert d, "the finding no longer states the corpus gate's size"
    assert int(d.group(1)) <= n_assert, (
        f"the finding claims {d.group(1)} assertions, the gate runs {n_assert}")
    assert int(d.group(2)) <= n_tests, (
        f"the finding claims {d.group(2)} mutation tests, pytest collects {n_tests}")

    # The three properties must each be named, because the count alone cannot say
    # whether the gate checks three things or one thing three times.
    for needle in ("re-checks κ against the *sealed* threshold",
                   "describes the files on disk",
                   "reproduces all 49 files byte"):
        assert needle in doc, f"§7 no longer states {needle!r}"


def test_a_removed_check_is_rc2_not_a_pass(tree):
    """A floor starves only if the check still runs; a DELETED row starves nothing.

    So membership is pinned separately against REQUIRED_CHECKS.
    """
    import re
    p = tree / GATE_REL
    src = p.read_text(encoding="utf-8")
    src2 = re.sub(r'^\s*\("build_is_reproducible".*\n', "", src, flags=re.M)
    assert src2 != src, "PRECONDITION: the CHECKS row was not found"
    p.write_text(src2, encoding="utf-8")
    r = run(tree)
    assert r.returncode == 2, r.stdout
    assert "does not match REQUIRED_CHECKS" in r.stderr
