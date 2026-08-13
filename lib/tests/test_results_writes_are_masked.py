#!/usr/bin/env python3
"""Every write into `results/` is masked, or it is named here with a reason.

Why this file exists
--------------------
`results/` is the distributable record and `evidence/` is the local-only archive. The mask
that separates them lives in `lib/phase1.emit`, which is the channel every *case verdict*
goes through — so it protects the writes that go through it, and nothing else.

Measured on 2026-08-12: `f2_determinism/03_score_harvest.py` writes one side file directly
(`results/phase1/F2_score_harvest_shared.json`, 900 joined rows, too large for the verdict
records) and that single write bypassed the mask. It shipped the live account id **six
times** — `account_id` and `attributes.aws.account.id`, which the gateway's log surface
publishes as standalone values outside any ARN — while the four verdict files written beside
it from the same dict were clean. That is the shape of `feedback_second_instance_bugs`: the
fix lived in the shared path, and this write was not on it.

`check_redaction.py` is the standing backstop and it would have caught this at push time.
But a gate that fires only after a leak has been written, in a file that happens to be
scanned, is a last line and not an invariant. This test is the invariant: a `results/` write
must mask, or appear in `WAIVED` with a written reason.

WAIVED is not a permission list, it is an inventory
---------------------------------------------------
The twelve entries below are every unmasked `results/` write in the repo on 2026-08-12. None
of them leaks today, and that was measured rather than assumed: across all 287 files under
`results/`, the live account id appears **0** times and **0** of the 8635 `arn:aws` strings
carry a 12-digit account — every one reads `<account>`. (The 205 twelve-digit tokens that do
appear are synthetic PII-corpus values such as `000123456789`; none is an AWS account.)

They are listed rather than fixed because masking five other families' scripts at once is a
change to working code for a latent risk, and the value of this test does not depend on it:
the test fails the moment a **thirteenth** unmasked `results/` write appears, which is
precisely how the twelfth would otherwise have arrived.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRS = {".venv", ".venv-oracle", ".venv-baseline", "__pycache__", ".git",
             "node_modules", "evidence", ".pytest_cache", ".state", "tests"}

MASKERS = {"mask_text", "mask"}

# (path relative to the repo root, the name the write is called on).
# Each entry is a write into `results/` that does not mask, with the reason it is tolerated.
WAIVED: dict[tuple[str, str], str] = {
    ("f1_config/01_sdk_bisect.py", "RESULTS"):
        "an SDK-version/attribute inventory built from local wheels — pip metadata and "
        "`dir()` output, no AWS call in the payload. results/f1_sdk_bisect.json holds 0 ARNs.",
    ("f3_efficacy/00_guardrails.py", "out"):
        "the guardrail manifest. It carries ids, not ARNs, and the region comes from argv; "
        "results/phase1_guardrails.json holds 0 ARNs. This is the entry most likely to need "
        "the mask first if the manifest ever grows an arn field.",
    ("f6_latency/03_composition.py", "tmp"):
        "F6-6's CloudWatch window: four timestamps, a turn count and a recorded_by string. "
        "results/checkpoints/F6-6__cw_windows.json holds 0 ARNs.",
    ("f6_latency/recover_cw_window.py", "WINDOWS_PATH"):
        "the same four-timestamp window record, rewritten by the recovery path.",
    ("f3_efficacy/07_model_drift.py", "path"):
        "F3-11's day snapshot: model ids and per-file counts from the sealed corpora.",
    ("f3_efficacy/07_model_drift.py", "_snapshot_path"):
        "the same snapshot, written on the --compare path.",
    ("census.py", "CENSUS"):
        "results/_progress_census.txt is derived ONLY from files already under results/ — the "
        "claim register and the verdict records, each of which went through the mask on the "
        "way in. Its output cannot carry an identifier its inputs do not; 0 twelve-digit "
        "tokens and 0 ARNs today.",
    ("claims/02_check_references.py", "OUT"):
        "F0-1's payload is HTTP statuses, URLs and page titles fetched from docs.aws.amazon.com. "
        "No AWS API call and no ARN reaches it; the only account-shaped risk would be a doc "
        "page that itself prints an account id.",
    ("f5_redteam/archive_flapped_restore_arm.py", "archive_path"):
        "re-serializes a checkpoint body READ BACK from results/checkpoints/, which "
        "lib/checkpoint.py:351 already wrote through redact.mask_text. The ARNs in the archive "
        "are the masked ones; masking again would be a second pass over <account>.",
    ("f5_redteam/archive_flapped_restore_arm.py", "tmp"):
        "the same already-masked body, rewritten cleared-of-rows through a .json.tmp then "
        "replace()d over the checkpoint — an atomic rewrite, not a new source of content.",
    ("f5_redteam/fix_restore_arm_archive_labels.py", "RIGHT"):
        "relabels the two F5-1 restore-arm archives in place; input and output are the same "
        "already-masked checkpoint bodies, with only the arm label changed.",
    ("f5_redteam/fix_restore_arm_archive_labels.py", "FLAPPED"):
        "the flapped-revoke half of that same relabel, written in the same call — an "
        "already-masked checkpoint body in, the same body with a corrected arm label out.",
}


# Writes that live inside a `results/`-writing module but do NOT target `results/`.
# The resolver cannot see through `Path(args.path)` or through an EvidenceStore object, so
# every write in such a module that it cannot place is listed here by hand. Three of the four
# are the deliberately-unmasked `evidence/` copy that sits one line below a masked `results/`
# write — the exact boundary DEV-P4-30 crossed, named at the four lines where it matters.
NOT_A_RESULTS_TARGET: dict[tuple[str, str], str] = {
    ("build_v13_candidates.py", "OUT"):
        "writes V13_CANDIDATES.md at the repo root, not under results/. It is distributable "
        "and the redaction gate scans it; it carries claim text and case ids, no AWS response.",
    ("lib/phase1.py", "store"):
        "`(store.dir / 'analysis.json')` — the evidence/ copy, which must stay UNMASKED. It is "
        "the local-only archive that holds the true ARN so a finding can be traced back to the "
        "resource; the masked copy went to results/ on the line above. Masking this would "
        "destroy the only record of which gateway produced a row.",
    ("f3_efficacy/08b_log_surface_join.py", "store"):
        "the same evidence/ copy paired with a masked results/ write one line above (F3-10's "
        "supplementary read).",
    ("f3_efficacy/08c_window_audit.py", "store"):
        "the same evidence/ copy paired with a masked results/ write one line above (F3-10's "
        "closed-window re-read). It writes no verdict — `kind: SUPPLEMENTARY_READ` — but it "
        "carries the true gateway and policy names the re-read was addressed to, which is what "
        "makes the unmasked local copy the traceable one.",
    ("f5_redteam/04b_logonly_flip_read.py", "store"):
        "the same evidence/ copy paired with a masked results/ write one line above (F5-4a's "
        "log-only flip read).",
}


def _py_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        out.append(p)
    return sorted(out)


def _root_name(node: ast.AST) -> str:
    """The leftmost name of an attribute/call/subscript/`/` chain, or ''.

    `ast.BinOp` matters as much as the rest: pathlib paths are built with `/`, so
    `RESULTS / "phase1_guardrails.json"` is a BinOp whose left arm holds the only name in
    the expression. Omitting it made this walk miss `f3_efficacy/00_guardrails.py:617` and
    both writes in `07_model_drift.py` — three sites already inventoried in WAIVED, which is
    the only reason the omission was visible at all rather than silently narrowing the scan.
    """
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.BinOp):
            node = node.left
        else:
            return ""


def _calls_a_masker(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in MASKERS:
                return True
    return False


def _mentions_results(expr: ast.AST) -> bool:
    """A path expression naming the `results` directory, as a literal segment."""
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            v = sub.value
            if v == "results" or v.startswith("results/") or "/results/" in v:
                return True
    return False


def _results_names(tree: ast.Module) -> set[str]:
    """Every name in the module that holds a path under `results/`.

    A fixpoint rather than one pass, because these paths are built in layers —
    `RESULTS = ROOT / "results"`, then `out = RESULTS / "phase1_guardrails.json"`, then
    `tmp = WINDOWS_PATH.with_suffix(...)` — and a single pass would see only the first.
    Functions are included by their `return` expressions, which is what catches
    `_snapshot_path(day_tag).write_text(...)`: the receiver is a call, not a name.

    Scope is ignored on purpose. Two different functions using the same local name for
    different things would over-catch, and over-catching costs a waiver line; under-catching
    costs an account id in a distributed file.
    """
    names: set[str] = set()
    for _ in range(6):                      # depth of nesting seen here is 3; 6 is slack
        before = len(names)
        for node in ast.walk(tree):
            targets: list[ast.AST] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Return) and sub.value is not None and (
                            _mentions_results(sub.value)
                            or _root_name(sub.value) in names):
                        names.add(node.name)
                continue
            if value is None:
                continue
            hit = _mentions_results(value) or _root_name(value) in names
            if not hit:
                continue
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        if len(names) == before:
            break
    return names


def _masked_names(tree: ast.Module) -> set[str]:
    """Names holding the output of a masker, so a write of `after` counts as masked.

    Without this the guard is purely syntactic — it would credit
    `p.write_text(mask_text(s))` and flag `after = mask_text(s); ...; p.write_text(after)`,
    which is the same write with its assertions in between. That false positive matters more
    than it sounds: the pressure it creates is to inline the mask and drop the checks that run
    between masking and writing.

    Transitive, and deliberately not flow-sensitive: a name later reassigned from an unmasked
    expression still counts. That is the one hole here, and it is narrower than the hole a
    false positive opens by teaching the reader to waive.
    """
    names: set[str] = set()
    for _ in range(4):
        before = len(names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if not (_calls_a_masker(value) or _root_name(value) in names):
                continue
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        if len(names) == before:
            break
    return names


def _results_writes(path: Path) -> list[tuple[str, int, bool]]:
    """(receiver root name, line, masked?) for every write whose TARGET is under results/.

    Resolved from the path expression, not from "the module mentions results somewhere". The
    first draft of this test used the looser rule and flagged 24 writes, most of them into
    `evidence/` or `runner/.state/` — neither of which is distributed. A guard that reports
    two-thirds noise is a guard that gets a blanket waiver, which is worse than no guard.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = _results_names(tree)
    masked_names = _masked_names(tree)
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text"):
            continue
        recv_expr = node.func.value
        if not (_mentions_results(recv_expr) or _root_name(recv_expr) in names):
            continue
        payloads = list(node.args) + [k.value for k in node.keywords]
        masked = any(_calls_a_masker(a) or _root_name(a) in masked_names for a in payloads)
        out.append((_root_name(recv_expr), node.lineno, masked))
    return out


def _unplaceable_writes(path: Path) -> list[tuple[str, int, bool]]:
    """Writes in a module that declares a module-level `results/` path, which the resolver
    could not place.

    This is the backstop for the one thing static resolution cannot do: follow a target that
    arrives at runtime. `remask_score_harvest_side_file.py` writes to `Path(args.path)`, whose
    default is the leaking file — invisible to `_results_writes`, and exactly the shape that
    would carry the next leak past a resolver-only guard.

    Restricting it to modules that declare a `results/` constant is what keeps it from
    degenerating into "the module mentions results somewhere", which flagged 24 sites, most of
    them noise.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    declares = any(isinstance(n, ast.Assign) and _mentions_results(n.value) for n in tree.body)
    if not declares:
        return []
    placed = {(r, line) for r, line, _m in _results_writes(path)}
    masked_names = _masked_names(tree)
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text"):
            continue
        recv = _root_name(node.func.value)
        if (recv, node.lineno) in placed:
            continue
        payloads = list(node.args) + [k.value for k in node.keywords]
        masked = any(_calls_a_masker(a) or _root_name(a) in masked_names for a in payloads)
        out.append((recv, node.lineno, masked))
    return out


def test_every_results_write_is_masked_or_named():
    unnamed = []
    for path in _py_files():
        rel = str(path.relative_to(ROOT))
        for recv, line, masked in _results_writes(path):
            if masked or (rel, recv) in WAIVED:
                continue
            unnamed.append(f"{rel}:{line}  {recv}.write_text(...)")
    assert not unnamed, (
        "a write into results/ neither masks nor appears in WAIVED. `results/` is the "
        "distributable record; `lib/phase1.emit` masks, a direct write does not:\n  "
        + "\n  ".join(unnamed))


def test_the_harvest_side_file_is_masked_and_not_waived():
    """The write that actually leaked. Pinned by name so a revert cannot pass quietly."""
    rel = "f2_determinism/03_score_harvest.py"
    writes = _results_writes(ROOT / rel)
    extras = [w for w in writes if w[0] == "RESULT_EXTRA"]
    assert extras, f"{rel} no longer writes RESULT_EXTRA; this test is now watching nothing"
    for recv, line, masked in extras:
        assert masked, (
            f"{rel}:{line} writes the 900-row side file unmasked. On 2026-08-12 that write "
            f"shipped the account id 6 times (DEV-P4-30)")
        assert (rel, recv) not in WAIVED, \
            "the leaking write must be fixed, not waived"


def test_a_mask_bound_to_a_name_before_the_write_counts_as_masked():
    """The DEV-P4-30 repair script masks, checks the result, and only then writes.

    It is the reason `_masked_names` exists. If the guard credited only an inline
    `write_text(mask_text(...))`, the cheapest way to make this file pass would be to delete
    the four assertions that stand between the mask and the write — the ones that prove the
    masker actually saw the account id.
    """
    rel = "f2_determinism/remask_score_harvest_side_file.py"
    writes = _unplaceable_writes(ROOT / rel)
    assert writes, (
        f"{rel} no longer has a write the resolver cannot place; this test is watching nothing. "
        f"Its target comes from `--path`, which is why it lands here and not in "
        f"_results_writes")
    unmasked = [line for _r, line, m in writes if not m]
    assert not unmasked, f"{rel} writes unmasked at line(s) {unmasked}"
    assert not any((rel, recv) in NOT_A_RESULTS_TARGET for recv, _l, _m in writes), \
        "the repair script writes the file it repairs; it must mask, not be excluded"


def test_a_write_in_a_results_module_is_masked_or_placed_outside_results():
    """The runtime-target backstop, over the whole repo."""
    unnamed = []
    for path in _py_files():
        rel = str(path.relative_to(ROOT))
        for recv, line, masked in _unplaceable_writes(path):
            if masked or (rel, recv) in NOT_A_RESULTS_TARGET or (rel, recv) in WAIVED:
                continue
            unnamed.append(f"{rel}:{line}  {recv}.write_text(...)")
    assert not unnamed, (
        "a module that writes into results/ has a write whose target this scan cannot place, "
        "and it neither masks nor is named in NOT_A_RESULTS_TARGET:\n  " + "\n  ".join(unnamed))


def test_every_exclusion_still_points_at_a_real_unmasked_write():
    """`feedback_vacuous_test_check`, for NOT_A_RESULTS_TARGET rather than WAIVED."""
    live = set()
    for path in _py_files():
        rel = str(path.relative_to(ROOT))
        for recv, _line, masked in _unplaceable_writes(path):
            if not masked:
                live.add((rel, recv))
    stale = sorted(k for k in NOT_A_RESULTS_TARGET if k not in live)
    assert not stale, f"these exclusions no longer match an unmasked write: {stale}"


@pytest.mark.parametrize("reason", sorted(NOT_A_RESULTS_TARGET.values()))
def test_every_exclusion_states_a_reason_not_a_shrug(reason: str):
    assert len(reason) > 40, "an exclusion has to say where the write actually goes and why"


def test_the_evidence_copy_is_excluded_and_never_required_to_mask():
    """The boundary itself. `evidence/` holds the true ARN by written policy; `results/` does
    not. A guard that demanded a mask here would delete the traceability the archive exists for.
    """
    rel = "lib/phase1.py"
    unmasked = [line for r, line, m in _unplaceable_writes(ROOT / rel) if not m and r == "store"]
    assert unmasked, (
        f"{rel} no longer has an unmasked write onto the evidence store. If emit() changed, "
        f"re-read the evidence/results policy before deleting this test")
    assert (rel, "store") in NOT_A_RESULTS_TARGET, \
        "the evidence copy must be excluded by name, not by the resolver failing to notice it"


def test_every_waiver_still_points_at_a_real_unmasked_write():
    """A waiver for a write that no longer exists is a stale exception granting nothing.

    `feedback_vacuous_test_check`: an inventory whose entries have decayed into no-ops
    reports a clean bill of health for a list it is no longer checking.
    """
    live = set()
    for path in _py_files():
        rel = str(path.relative_to(ROOT))
        for recv, _line, masked in _results_writes(path):
            if not masked:
                live.add((rel, recv))
    stale = sorted(k for k in WAIVED if k not in live)
    assert not stale, (
        "these waivers no longer match an unmasked results/ write — the write was masked, "
        f"moved or deleted, so delete the waiver: {stale}")


@pytest.mark.parametrize("reason", sorted(WAIVED.values()))
def test_every_waiver_states_a_reason_not_a_shrug(reason: str):
    assert len(reason) > 40, "a waiver has to say what it is waiving and why"


def test_the_scan_reads_more_than_zero_files():
    """`feedback_zero_file_scan_is_error`: a scan finding nothing must not agree with anything.

    The floors are below the measured values (92 files, 10 writer modules on 2026-08-12) so
    that adding a script does not red the suite. The named probes are the real guard: a
    SKIP_DIRS entry that quietly swallowed a whole family would keep the count plausible.
    """
    files = _py_files()
    rels = {str(p.relative_to(ROOT)) for p in files}
    assert len(files) > 60, f"only {len(files)} python files scanned"
    for probe in ("f2_determinism/03_score_harvest.py", "lib/phase1.py", "census.py",
                  "f5_redteam/archive_flapped_restore_arm.py"):
        assert probe in rels, \
            f"{probe} is no longer scanned — SKIP_DIRS or the glob has narrowed"
    writers = [p for p in files if _results_writes(p)]
    assert len(writers) >= 8, \
        f"only {len(writers)} modules write into results/; the AST walk has stopped finding them"
