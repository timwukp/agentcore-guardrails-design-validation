"""The redaction gate must find a leak that is really there.

A gate that has never caught anything is not a gate, it is a habit. This suite
plants a canary file containing one instance of every pattern and requires each
to be reported, then requires the gate to pass on the real tree.

The manual version of this check nearly went wrong in an instructive way: the
canary was written into results/, the verification command aborted on a shell
error before its `rm` ran, and the canary was left on disk while the terminal
showed a passing gate. Writing the canary to a tmp_path and letting pytest own
cleanup removes the whole class of mistake.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent               # grx-validation/
SRC = ROOT / "check_redaction.py"


# The sys.modules key must NOT be "redact".
#
# `check_redaction.py` is loaded here by path because it is a top-level script, not an
# importable package member. The name it was registered under used to be "redact", chosen
# when nothing else in the tree owned that name. `lib/redact.py` then took it, and
# `check_redaction.py` itself now does `import redact as _redact` — so this loader was
# publishing a DIFFERENT module under the name its own subject imports. Worse, the
# registration happens before `exec_module`, so the import inside `check_redaction.py`
# resolved to the half-initialized module that was mid-load, and every consumer of
# `lib/redact.py` in the same process (lib/checkpoint.py, lib/phase1.py, lib/tests/
# test_redact.py) inherited that stub. Each suite passed alone; the combined run failed with
# `AttributeError: module 'redact' has no attribute 'mask_text'` ~20 times.
#
# The key is therefore the subject's own filename, which no importable module can claim,
# and `test_the_loader_does_not_squat_on_a_real_module_name` fails if it drifts back.
_MODNAME = "check_redaction_under_test"


def _load():
    spec = importlib.util.spec_from_file_location(_MODNAME, SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


redact = _load()

# Canaries are ASSEMBLED AT RUNTIME, never written as literals.
#
# The first version of this file spelled out a real account ID and a real role
# ARN, and the gate immediately flagged its own test suite — correctly. Waiving
# them via ALLOW would have been the wrong fix: it would have put real
# identifiers in a file destined for distribution and then silenced the only
# thing that noticed. Since the patterns are shape-based, a shape is all a canary
# needs, and no shape need appear as a literal in the source.
_A = "9" * 12                    # account-id shape, not a real account
_HEX = "0" + "1234567890abcdef"  # 17 hex chars, vpc/subnet id shape

CANARY_LINES = {
    "aws-account-id": f"Account {_A} ran the test.",
    "arn": f"Role arn{':'}aws:iam::{_A}:role/grx-gw-exec was assumed.",
    "s3-uri": "Evidence at s3" + "://my-evidence-bucket/run1/.",
    "access-key-id": "Key " + "AKIA" + "IOSFODNN7EXAMPLE was rotated.",
    "private-ip": "Host " + "10." + "0.42.17 answered.",
    "vpc-or-subnet-id": f"Network vpc-{_HEX} and subnet-{_HEX}.",
}


@pytest.mark.parametrize("name,line", sorted(CANARY_LINES.items()))
def test_every_pattern_matches_its_canary(name, line):
    rx = next(r for n, r, _d in redact.PATTERNS if n == name)
    assert rx.search(line), f"pattern {name!r} does not match its own canary: {line!r}"


def test_patterns_do_not_fire_on_innocent_text():
    """False positives are cheap but not free — a gate nobody trusts gets bypassed."""
    innocent = [
        "The corpus holds 108 PII cases across 24 patterns.",
        "Measured p50 was 42ms at n=1000, doc line 140.",
        "See sha1:75b90ee42b92 for the claim text.",
        "Version 1.2, dated August 8 2026.",
        "Wilson lower bound 0.8412 at alpha=0.05.",
    ]
    for line in innocent:
        for name, rx, _d in redact.PATTERNS:
            assert not rx.search(line), f"{name} false-positives on: {line!r}"


def test_twelve_digit_pattern_does_not_match_eleven_or_thirteen():
    rx = next(r for n, r, _d in redact.PATTERNS if n == "aws-account-id")
    assert not rx.search("id " + "9" * 11 + " here"), "11 digits matched"
    assert not rx.search("id " + "9" * 13 + " here"), "13 digits matched"
    assert rx.search("id " + "9" * 12 + " here"), "12 digits did not match"


def test_gate_reports_a_planted_leak(tmp_path, monkeypatch):
    """End-to-end: run the gate over a tree containing a canary.

    Uses monkeypatched module globals rather than copying the project, so the
    canary can never be written into the real tree (the exact mistake the manual
    version made).
    """
    for i, (name, line) in enumerate(sorted(CANARY_LINES.items())):
        (tmp_path / f"file_{i}.md").write_text(line + "\n", encoding="utf-8")
    # Pad above MIN_FILES so the denominator guard does not fire first — this test
    # is about pattern detection, not about the floor.
    for i in range(redact.MIN_FILES):
        (tmp_path / f"pad_{i}.md").write_text("nothing to see here\n", encoding="utf-8")

    monkeypatch.setattr(redact, "ROOT", tmp_path)
    rc = redact.main([])
    assert rc == 1, f"gate returned {rc} on a tree with {len(CANARY_LINES)} leaks"


def test_gate_fails_when_it_reads_almost_nothing(tmp_path, monkeypatch):
    """feedback_zero_file_scan_is_error: a scan below the floor is rc=2, not rc=0.

    This is the check that catches a broken file list — the failure that reported
    CLEAN twice in this codebase's history.
    """
    (tmp_path / "only.md").write_text("clean content\n", encoding="utf-8")
    monkeypatch.setattr(redact, "ROOT", tmp_path)
    assert redact.main([]) == 2


def test_gate_fails_on_an_empty_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(redact, "ROOT", tmp_path)
    assert redact.main([]) == 2


def test_allow_entries_each_carry_a_reason():
    """No longer vacuous: ALLOW has two real entries (the PII corpus fixtures)."""
    assert redact.ALLOW, "this assertion is only meaningful with entries present"
    for entry in redact.ALLOW:
        suffix, name, needle, why = entry
        assert len(why) >= 20, f"ALLOW entry {suffix}/{name} has no real reason"
        assert name in {n for n, _r, _d in redact.PATTERNS}, \
            f"ALLOW entry names unknown pattern {name!r}"
        assert needle.strip(), f"{suffix}/{name} waives the whole file"


def test_every_allow_entry_actually_fires():
    """Replaces `test_allow_is_empty_and_that_is_deliberate`.

    That test existed because the first draft carried eight DEAD entries, each
    waiving this file or the test suite for "its own pattern definition" — but a
    regex written as source does not match itself, so none ever fired. Dead entries
    advertise waivers that do not exist, and a reviewer reading ALLOW would conclude
    the gate had been argued down when nothing had been waived. Its docstring said
    to delete it in the same change that adds a real exception; this is that change,
    and this is the assertion that replaces it.

    Emptiness was never the property worth protecting — **liveness** was. So rather
    than assert the list is empty, assert every entry is load-bearing: remove it and
    the gate must report a finding it currently waives. An entry that fails this is
    dead weight, exactly what the original test was guarding against, and the check
    keeps working however many legitimate entries accumulate.
    """
    assert redact.ALLOW, "nothing to check — see test_allow_entries_each_carry_a_reason"
    for i, entry in enumerate(redact.ALLOW):
        suffix, name, needle, _why = entry
        target = ROOT / suffix
        assert target.exists(), f"ALLOW entry {i} names a missing file: {suffix}"
        hits = [ln for ln in target.read_text(encoding="utf-8").splitlines()
                if needle in ln and
                next(r for n, r, _d in redact.PATTERNS if n == name).search(ln)]
        assert hits, (
            f"ALLOW entry {i} ({suffix}, {name}, {needle!r}) waives nothing: no "
            f"line in that file both contains the needle and matches the pattern. "
            f"Delete it — a dead waiver is worse than no waiver.")


def test_the_gate_fails_if_a_waived_fixture_is_removed_from_its_file(monkeypatch):
    """Mutation control for the test above: with ALLOW emptied, the gate must FAIL.

    Without this, `test_every_allow_entry_actually_fires` could pass while the
    waivers were irrelevant — e.g. if the patterns had been quietly loosened so
    nothing fired at all. The whole tree is scanned, so this also proves the two
    entries are the ONLY things standing between the current tree and a clean run.
    """
    monkeypatch.setattr(redact, "ALLOW", [])
    assert redact.main([]) == 1, (
        "with ALLOW emptied the gate reported clean — either the patterns no longer "
        "fire on the PII corpus fixtures, or the waivers were never needed")


def test_allow_mechanism_actually_waives_when_it_matches(tmp_path, monkeypatch):
    """The mechanism must work, even though nothing currently uses it.

    Without this, emptying ALLOW would leave the waiver code path untested and
    the first real exception would be trusted on faith.
    """
    leak = CANARY_LINES["aws-account-id"]
    (tmp_path / "waived.md").write_text(leak + "\n", encoding="utf-8")
    for i in range(redact.MIN_FILES):
        (tmp_path / f"pad_{i}.md").write_text("clean\n", encoding="utf-8")

    monkeypatch.setattr(redact, "ROOT", tmp_path)
    assert redact.main([]) == 1, "planted leak was not reported before waiving"

    monkeypatch.setattr(redact, "ALLOW", [
        ("waived.md", "aws-account-id", "ran the test",
         "synthetic entry exercising the waiver path in the test suite"),
    ])
    assert redact.main([]) == 0, "ALLOW entry did not waive its match"


def test_allow_entry_does_not_waive_a_different_line_in_the_same_file(
        tmp_path, monkeypatch):
    """Narrowness is the property that makes an exception safe.

    A waiver keyed on a substring must not silence a second, unrelated leak in
    the same file — otherwise 'reviewed exception' degrades into 'ignore file'.
    """
    (tmp_path / "waived.md").write_text(
        CANARY_LINES["aws-account-id"] + "\n" + CANARY_LINES["s3-uri"] + "\n",
        encoding="utf-8")
    for i in range(redact.MIN_FILES):
        (tmp_path / f"pad_{i}.md").write_text("clean\n", encoding="utf-8")

    monkeypatch.setattr(redact, "ROOT", tmp_path)
    monkeypatch.setattr(redact, "ALLOW", [
        ("waived.md", "aws-account-id", "ran the test",
         "synthetic entry exercising the waiver path in the test suite"),
    ])
    assert redact.main([]) == 1, (
        "the second leak in a partially-waived file was silenced — the waiver is "
        "acting as a whole-file skip")


def test_gate_passes_on_the_real_tree():
    """The actual deliverable: this project carries no unredacted identifiers."""
    proc = subprocess.run([sys.executable, str(SRC)], cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"redaction gate fails on the real tree:\n{proc.stdout}\n{proc.stderr}")
    assert "PASSED" in proc.stdout


def test_no_canary_file_was_left_behind():
    """Guards against the manual run's actual failure mode."""
    strays = sorted(p.name for p in ROOT.rglob("*CANARY*"))
    assert strays == [], f"canary files left in the tree: {strays}"


# --------------------------------------------------------------------------------------
# The ARN excuse. Added after it was found VACUOUS in live use.
#
# `allowed()` grants a per-line excuse when every ARN on the line has its account field
# masked. The original implementation was a `for … else` over `finditer` with the
# service and Region fields written as `[a-z0-9-]*`. Source code that BUILDS an ARN
# writes those fields as f-string placeholders, which contain `{`, `}` and `_` — so the
# decompose regex matched nothing, `finditer` yielded an empty iterator, and control fell
# into `else`, returning the message "every ARN on this line has its account field
# masked" for a line whose account field had never been read.
#
# That is the vacuous-guard shape (feedback_vacuous_test_check) and it was live, not
# theoretical: one line in lib/ was being excused by it at the time.
#
# The fix cross-checks the excuse's own match count against the REPORTING pattern's and
# fails closed on disagreement. These arms hold both directions, because a fix in this
# direction is one keystroke from a gate that excuses everything.
#
# Every fixture is assembled at runtime for the same reason as CANARY_LINES above.
_ARN = "arn" + ":aws"
_PH = "<account>"                 # must equal lib/redact.ACCOUNT_PLACEHOLDER


def _excuse(line: str, name: str = "arn"):
    """`allowed()` for a path inside the tree, so the ALLOW suffix rules cannot fire."""
    return redact.allowed(ROOT / "lib" / "_fixture_not_a_real_file.py", name, line)


EXCUSED_ARN_LINES = {
    "masked account":
        f'{_ARN}:bedrock:us-east-1:{_PH}:guardrail/abc123',
    "template account, template region":
        f'return f"{_ARN}:bedrock-agentcore:{{region}}:{{account_id}}:policy-engine/{{id}}"',
    "template account, empty region (sts)":
        f'return f"{_ARN}:sts::{{account_id}}:assumed-role/{{role_name}}"',
    "attribute access inside the placeholder":
        f'Principal=f"{_ARN}:iam::{{account_id}}:role/{{gw_role.name}}"',
    "angle-bracket doc placeholder":
        f'the entity id is `{_ARN}:sts::<acct>:assumed-role/<role>`',
    "exact wildcard account (IAM policy resource)":
        f'"Resource": "{_ARN}:logs:*:*:*"',
    "two masked ARNs on one line":
        f'a="{_ARN}:iam::{_PH}:role/x" b="{_ARN}:lambda:us-east-1:{_PH}:function:y"',
}

REPORTED_ARN_LINES = {
    "a real account id":
        f'X = "{_ARN}:iam::' + "9" * 12 + ':role/admin"',
    "one masked and one real on the same line":
        f'a=f"{_ARN}:iam::{{acct}}:role/x" b="{_ARN}:iam::' + "9" * 12 + ':role/y"',
    "wildcard region but a real account":
        f'"Resource": "{_ARN}:logs:*:' + "9" * 12 + ':*"',
    "a truncated prefix the excuse cannot decompose":
        f'the pattern is r"{_ARN}[a-z-]*:"',
    "partial mask - only the first four digits":
        f'X = "{_ARN}:iam::' + "<acc>" + "9" * 8 + ':role/admin"',
}


@pytest.mark.parametrize("label,line", sorted(EXCUSED_ARN_LINES.items()))
def test_arn_excuse_waives_a_line_that_carries_no_identifier(label, line):
    rx = next(r for n, r, _d in redact.PATTERNS if n == "arn")
    assert rx.search(line), (
        f"{label}: the fixture no longer trips the arn pattern, so this arm proves nothing "
        f"about the excuse. Fixture: {line!r}")
    assert _excuse(line), (
        f"{label}: this line contains no cloud identifier — the account field is masked, a "
        f"run-time placeholder, or an exact wildcard — yet the excuse refused it. Refusing "
        f"is the SAFE direction, but a gate that reports source code as a leak gets waived "
        f"wholesale by the next person. Fixture: {line!r}")


@pytest.mark.parametrize("label,line", sorted(REPORTED_ARN_LINES.items()))
def test_arn_excuse_never_waives_a_line_it_has_not_fully_parsed(label, line):
    """The direction that matters. Each fixture failed against the original `for/else`."""
    assert _excuse(line) is None, (
        f"{label}: the ARN excuse waived this line. Fixture: {line!r}")


def test_arn_excuse_match_count_is_cross_checked_against_the_reporting_pattern():
    """The mechanism of the fix, asserted directly rather than only through its symptoms.

    The excuse must never inspect fewer ARNs than the reporting pattern found. Stated as a
    property over every fixture in this file — including the reported ones — so a future
    rewrite that reintroduces a laxer decompose regex fails here with a reason, instead of
    silently excusing the lines it cannot read.
    """
    for label, line in list(EXCUSED_ARN_LINES.items()) + list(REPORTED_ARN_LINES.items()):
        detected = len(redact._ARN_DETECT.findall(line))
        parsed = len(redact._ARN_ACCOUNT_FIELD.findall(line))
        if parsed != detected:
            assert _excuse(line) is None, (
                f"{label}: the excuse parsed {parsed} of {detected} ARN(s) on this line and "
                f"still waived it. An excuse that has not read every account field cannot "
                f"claim they are all masked.")


def test_the_placeholder_shape_cannot_match_a_real_account_id():
    """Recognising `{placeholder}` must not be a way to smuggle 12 digits past the gate."""
    assert not redact._ARN_TEMPLATE_FIELD.fullmatch("9" * 12)
    assert not redact._ARN_TEMPLATE_FIELD.fullmatch("{" + "9" * 12 + "}")
    assert redact._ARN_TEMPLATE_FIELD.fullmatch("{account_id}")
    # And the placeholder the rest of the project uses must still be the one lib/redact.py
    # declares — the excuse compares against it by identity, not by this literal.
    assert _PH == redact._redact.ACCOUNT_PLACEHOLDER, (
        "lib/redact.ACCOUNT_PLACEHOLDER changed; the fixtures above are now testing a "
        "placeholder the gate does not use")
