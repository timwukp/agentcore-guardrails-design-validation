#!/usr/bin/env python3
"""What the redaction gate SELECTS, and what it PRINTS. Both were defects on 2026-08-20.

Two changes landed in `check_redaction.py` that day, and neither is provable by reading it.

**1. Inclusion stopped being a name list.** Until then `SCAN_EXT` held nine extensions —
`.csv .json .md .py .sh .sql .txt .yaml .yml` — and a file whose suffix was not among them
left the scan in silence. On the tree that day the allowlist was skipping **87 files /
701,558 bytes**: 56 `.jsonl` corpora (the files that hold identifier shapes *by design*), 22
`.log` + 3 `.rc` under `session-logs/` (a directory with no `.gitignore` rule and four files
already on `main`), 4 checkpoints that left the scan the instant a suffix was appended to a
`.json` name, `PREREGISTRATION.sha256`, and `.gitignore`. Scanning them found **7 unwaived
identifiers in 2 files**, so this was a live gap, not a tidiness argument.

The arms below plant an identifier in each of those shapes. Every one of them **passed
vacuously before the change** — the gate never opened the file — which is what makes them a
fix rather than a claim (`feedback_identical_output_wrong_assertion`). One arm reconstructs
the nine extensions and asserts each fixture's suffix was absent from them, so that claim is
checked rather than remembered.

**2. The gate stopped being a leak channel.** The first run with the wider predicate convicted
`session-logs/redaction-gate-20260819-pctfix.log` — *this gate's own earlier output* — on four
identifiers it had printed itself, and a pytest `-v` log on six that were nothing but test
ids. A gate that manufactures the finding it looks for has not closed the gap, it has moved it
(`feedback_fix_producer_not_janitor`). So `_snippet` masks, and the last arm here is the one
that matters most: it runs the gate's own patterns over the gate's own output and requires zero
unwaived hits. That arm is what generalises — it holds for a leak shape nobody has thought of.

Every 12-digit value in this file is assembled from halves at run time, and every
`parametrize` is over a dict KEY, never over the fixture: pytest stringifies parameters into
test ids and `-v` prints ids, which is precisely how the six-identifier log above was written.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SUBJECT = ROOT / "check_redaction.py"

# Registered under a name of this file's own, for the reason
# `lib/tests/test_module_name_collisions.py` states: `check_redaction` is an importable
# top-level name under pytest, and publishing a different object under it poisons every
# other consumer in the same process.
SUBJECT_MODULE_NAME = "_predscan_check_redaction"

# Shapes, not identifiers. Neither half matches anything on its own.
ACCOUNT = "4099" + "38471625"
ACCOUNT_2 = "5170" + "22849163"

# The allowlist as it stood, recovered from the banner line of the last gate run that had one
# (`session-logs/redaction-gate-20260819-pctfix-2.log`) rather than from memory. Its only use
# is to prove the fixtures below were outside it.
OLD_SCAN_EXT = {".csv", ".json", ".md", ".py", ".sh", ".sql", ".txt", ".yaml", ".yml"}

# One entry per real class of file the allowlist was skipping. The key is prose so it can be a
# test id; the value is the filename.
SKIPPED_SHAPES = {
    "session log": "gate-run.log",
    "return code file": "batch.rc",
    "jsonl corpus row": "pii_corpus.jsonl",
    "checkpoint with an appended suffix": "F2-2__tau_floor.json.smoke-20260812",
    "sha256 sidecar": "PREREGISTRATION.sha256",
    "dotfile with no stem": ".gitignore",
    "no extension at all": "Makefile",
    "an extension nobody has thought of": "notes.bananas",
}


def _subject():
    spec = importlib.util.spec_from_file_location(SUBJECT_MODULE_NAME, SUBJECT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def gate():
    return _subject()


def _tree(tmp_path: Path, gate, **files: str) -> None:
    """Write `files` plus enough clean padding to clear the MIN_FILES floor.

    The floor exists to catch a broken file list, and it returns rc 2 — which is non-zero, so
    an arm asserting "not clean" would pass on a tree that was never scanned. Padding keeps
    every arm below testing what it says it tests.
    """
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    for i in range(gate.MIN_FILES):
        (tmp_path / f"pad_{i}.md").write_text("nothing to see here\n", encoding="utf-8")


def _run(gate, monkeypatch, tmp_path: Path, capsys) -> tuple[int, str]:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    rc = gate.main([])
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


# --------------------------------------------------------------- the control arm, first

def test_no_mutant_control_a_tree_of_odd_extensions_with_no_identifiers_passes(
        gate, monkeypatch, tmp_path, capsys):
    """Per `feedback_vacuous_test_check`: without this, every arm below could be passing
    because the wider predicate raises findings on *anything* it reads, and the fixtures'
    identifiers would be doing no work.
    """
    _tree(tmp_path, gate, **{n: "a clean line of prose\n" for n in SKIPPED_SHAPES.values()})
    rc, out = _run(gate, monkeypatch, tmp_path, capsys)
    assert rc == 0, f"clean tree of odd extensions returned {rc}:\n{out}"
    # And it really did read them, rather than passing by skipping them — the failure this
    # whole file is about would otherwise look identical here.
    assert f"{len(SKIPPED_SHAPES) + gate.MIN_FILES} file(s)" in out, out


# ------------------------------------------------------------------- 1. inclusion

@pytest.mark.parametrize("shape", sorted(SKIPPED_SHAPES))
def test_a_file_the_extension_allowlist_would_have_skipped_is_scanned(
        shape, gate, monkeypatch, tmp_path, capsys):
    name = SKIPPED_SHAPES[shape]
    _tree(tmp_path, gate, **{name: f"Account {ACCOUNT} ran the batch.\n"})
    rc, out = _run(gate, monkeypatch, tmp_path, capsys)
    assert rc == 1, f"{name} ({shape}) carried an account ID and the gate returned {rc}:\n{out}"
    assert name in out, f"the gate failed, but not on {name}:\n{out}"


@pytest.mark.parametrize("shape", sorted(SKIPPED_SHAPES))
def test_the_nine_extension_allowlist_was_structurally_blind_to_that_file(shape):
    """The arm that turns the one above from an assertion into a regression test.

    If a fixture's suffix were in `OLD_SCAN_EXT`, the arm above would have passed before the
    change too, and would therefore be pinning nothing.
    """
    name = SKIPPED_SHAPES[shape]
    assert Path(name).suffix.lower() not in OLD_SCAN_EXT, (
        f"{name} would have been scanned by the old nine-extension allowlist, so the "
        f"companion arm for {shape!r} does not distinguish the fix from the bug")


def test_inclusion_consults_the_filename_for_nothing_at_all(gate):
    """A fixture list cannot notice a filter written in a shape it does not cover.

    `SKIPPED_SHAPES` is eight names. A *deny*list, a `MIN_SIZE`, a re-added allowlist with
    ten entries — each would leave most arms above green. So this reads `files()` itself and
    requires that the only names it consults are directory names.
    """
    assert not hasattr(gate, "SCAN_EXT"), (
        "SCAN_EXT is back. It was removed on 2026-08-20 because it was hiding 87 files; if "
        "there is a new reason for it, the module docstring and this file must change first.")
    fn = next(n for n in ast.parse(SUBJECT.read_text(encoding="utf-8")).body
              if isinstance(n, ast.FunctionDef) and n.name == "files")
    names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert not names & {"suffix", "suffixes", "stem", "name"}, (
        f"files() now inspects {sorted(names & {'suffix', 'suffixes', 'stem', 'name'})} on a "
        "path. Inclusion keyed on a filename is the defect this file exists to pin; the "
        "directory skips are matched on `parts`, which needs no such attribute.")
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert used <= {"out", "p", "parts", "part", "ROOT", "SKIP_DIRS", "SKIP_DIR_PREFIXES",
                    "any", "sorted", "list", "Path"}, (   # `list`/`Path`: the return annotation
        f"files() reads a global this arm has not accounted for: {sorted(used)}. If it is a "
        "new selection rule, it is exactly what this file is meant to notice.")


def test_a_file_that_will_not_decode_as_utf8_is_scanned_as_latin1_not_skipped(
        gate, monkeypatch, tmp_path, capsys):
    """"Binary" is not a reason not to look — and rc 2 is not the same as rc 1.

    A regression that raised `UnicodeDecodeError` would make `main()` return 2 with "cannot
    read", which is also non-zero. That is a *different* outcome: it stops the whole scan on
    the first PNG in the tree instead of reading it. Both halves are asserted.
    """
    _tree(tmp_path, gate)
    (tmp_path / "bundle.bin").write_bytes(
        b"\xff\xfe\x00chunk " + ACCOUNT.encode() + b" \xc0\xc1trailing")
    rc, out = _run(gate, monkeypatch, tmp_path, capsys)
    assert rc == 1, f"an undecodable file carrying an account ID returned {rc}:\n{out}"
    assert "cannot read" not in out, f"the file was refused rather than read:\n{out}"
    assert "(latin-1)" in out, (
        f"the finding does not say which decoding produced it; a reader who greps the file "
        f"for the reported bytes will not find them:\n{out}")


# ------------------------------------------------------- 2. the gate is not a leak channel

def test_the_report_does_not_contain_the_identifier_it_is_reporting(
        gate, monkeypatch, tmp_path, capsys):
    _tree(tmp_path, gate, **{"gate-run.log": f"Account {ACCOUNT} ran the batch.\n"})
    rc, out = _run(gate, monkeypatch, tmp_path, capsys)
    assert rc == 1
    assert ACCOUNT not in out, (
        "the gate printed the account ID it had just caught. Its own output is a file — it "
        f"lands in session-logs/, in a PR body and in a screenshot:\n{out}")
    assert "<aws-account-id>" in out, f"nothing was masked; the snippet is missing:\n{out}"


def test_the_report_still_carries_enough_to_act_on(
        gate, monkeypatch, tmp_path, capsys):
    """The other half of the arm above, which a `_snippet` returning `""` would satisfy."""
    _tree(tmp_path, gate, **{"gate-run.log": f"Account {ACCOUNT} ran the batch.\n"})
    rc, out = _run(gate, monkeypatch, tmp_path, capsys)
    assert rc == 1
    for needed in ("gate-run.log", ":1", "[aws-account-id]", "ran the batch"):
        assert needed in out, (
            f"the report omits {needed!r}, so a reader cannot find the line it is about. "
            f"Masking the value must not cost the context:\n{out}")


def test_a_second_identifier_on_the_same_line_is_masked_too(
        gate, monkeypatch, tmp_path, capsys):
    """`search()` returns one span. A snippet built from it would print the other value.

    Worse than printing both, it would read as though the surviving one had been reviewed.
    """
    _tree(tmp_path, gate,
          **{"gate-run.log": f"Accounts {ACCOUNT} and {ACCOUNT_2} both answered.\n"})
    rc, out = _run(gate, monkeypatch, tmp_path, capsys)
    assert rc == 1
    for value in (ACCOUNT, ACCOUNT_2):
        assert value not in out, f"one of two account IDs on the line survived:\n{out}"


def test_a_pattern_that_stops_short_of_the_value_does_not_print_it(
        gate, monkeypatch, tmp_path, capsys):
    """One line raises one finding PER PATTERN, and each of them prints the line.

    `arn` is `\\barn:aws[a-z-]*:[a-z0-9-]*:` — it matches up to the region and stops *before*
    the account field. So a snippet masking only the firing pattern's own matches printed the
    account ID in the `arn` finding while masking it in the `aws-account-id` finding directly
    below. Both findings must be clean, which is why `_snippet` applies every pattern.
    """
    line = f"Role arn{':'}aws:iam::{ACCOUNT}:role/grx-gw-exec was assumed."
    _tree(tmp_path, gate, **{"gate-run.log": line + "\n"})
    rc, out = _run(gate, monkeypatch, tmp_path, capsys)
    assert rc == 1
    assert "[arn]" in out and "[aws-account-id]" in out, (
        f"this arm needs both patterns to fire on the line to mean anything:\n{out}")
    assert ACCOUNT not in out, (
        f"the account ID survived in a finding raised by a pattern that does not cover "
        f"it:\n{out}")


def test_the_gates_own_output_passes_the_gates_own_patterns(
        gate, monkeypatch, tmp_path, capsys):
    """The general form, and the only arm here that covers a shape nobody has enumerated.

    Every arm above names a value and asserts it is absent. This one asserts the property:
    **the report is a file that would itself pass this gate.** It plants one instance of every
    pattern, then runs `PATTERNS` + `allowed()` over the gate's own stdout and stderr. Any
    future addition to the report — a `--verbose` line, a summary, a new column — is covered
    the day it is written rather than the day someone remembers to add an arm.

    `allowed()` is called with a path under the scanned root so the general, file-independent
    excuses apply (the reserved documentation accounts, decimal fractions) while no
    path-scoped ALLOW entry can excuse anything: a reviewed exception is authored against one
    file's content, and it has no business excusing this gate's diagnostics.
    """
    plants = {
        "an account id": f"Account {ACCOUNT} ran it.",
        "a role arn": f"Role arn{':'}aws:iam::{ACCOUNT}:role/grx-gw-exec.",
        "an s3 uri": "Evidence at s3" + "://grx-eviden" + "ce-bucket/run1/.",
        "an access key": "Key " + "AKIA" + "IOSFODNN7EXAMPLE rotated.",
        "a private ip": "Host " + "10." + "0.42.17 answered.",
        "a vpc id": "Network vpc-0" + "1234567890abcdef.",
    }
    _tree(tmp_path, gate,
          **{f"planted_{i}.log": line + "\n" for i, line in enumerate(sorted(plants.values()))})
    rc, out = _run(gate, monkeypatch, tmp_path, capsys)
    assert rc == 1, f"the plants did not convict, so there is no report to check:\n{out}"

    probe = tmp_path / "the-gates-own-report.log"
    leaks = []
    for lineno, line in enumerate(out.splitlines(), 1):
        for form, _note in gate.scan_forms(line):
            for name, rx, _desc in gate.PATTERNS:
                if rx.search(form) and not gate.allowed(probe, name, form):
                    leaks.append(f"  report line {lineno} [{name}]: {line.strip()[:100]}")
                    break
    assert not leaks, (
        "the gate's own output would fail the gate. Whatever it prints is written to "
        "session-logs/, pasted into PR bodies and screenshotted, so a report carrying an "
        "identifier does not close the gap it found — it moves it:\n" + "\n".join(leaks))
