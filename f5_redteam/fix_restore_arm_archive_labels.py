#!/usr/bin/env python3
"""One-off: correct a WRONG label on an already-written F5-1 restore-arm archive, and migrate both
archives to the schema `archive_flapped_restore_arm.py` writes today.

    python3 f5_redteam/fix_restore_arm_archive_labels.py --check
    python3 f5_redteam/fix_restore_arm_archive_labels.py

WHY THIS EXISTS
---------------
`F5-1__restored_reassert__timed_out_revoke_archive.json` attributes its 20 rows to a revoke wait
that timed out at 308.8s. That is false, and the log says so: the run which timed out
(`/tmp/f5_01d.log`, and its published record) re-sent NOTHING — a checkpointed arm is served from
disk — so those rows were sent by the PREVIOUS run, whose revoke wait confirmed three consecutive
denials at 248.5s (`/tmp/f5_01c.log`). They are a valid measurement of the arm, not a defect: 4 of
20 invocations executed AFTER the denial was confirmed to hold, which is the strongest form of the
reconvergence finding rather than a reason to discard anything.

The distinction is not cosmetic. Filing a valid replicate as a defect deletes a real observation
under a false description, and it is the same class of error as the defects it was filing: a record
whose label does not match what produced it. So the label becomes `earlier_replicate`, the archive
grows an explicit `label_correction` block, and the corrected reason travels with the rows.

WHAT THIS DOES NOT DO
---------------------
It does not change a single trial row, and it does not touch the evidence tree. Every invocation
remains under `evidence/<run_id>/f5_redteam/F5-1/` with its request and response. Only the
provenance wrapper around the rows is rewritten.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CP_DIR = ROOT / "results" / "checkpoints"

# The REASONS table is imported from the writer rather than restated, so a correction cannot drift
# from the vocabulary the writer will use for the next archive. The module name starts with a digit
# in its siblings; this one does not, but it is loaded by path for the same reason they are.
_spec = importlib.util.spec_from_file_location(
    "_archiver", ROOT / "f5_redteam" / "archive_flapped_restore_arm.py")
_archiver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_archiver)
REASONS = _archiver.REASONS

WRONG = CP_DIR / "F5-1__restored_reassert__timed_out_revoke_archive.json"
RIGHT = CP_DIR / "F5-1__restored_reassert__earlier_replicate_archive.json"
FLAPPED = CP_DIR / "F5-1__restored_reassert__flapped_revoke_archive.json"

CORRECTION = {
    "was_labelled": "timed_out_revoke",
    "corrected_to": "earlier_replicate",
    "why_the_first_label_was_wrong": (
        "it attributed these rows to the run whose revoke wait timed out at 308.8s. That run "
        "re-sent nothing: `restored_reassert` was already checkpointed, and a checkpointed arm is "
        "served from disk. The rows were sent by the preceding run, whose revoke wait confirmed "
        "three consecutive denials at 248.5s — so they were sent AFTER the arm's precondition was "
        "established, which makes them a valid measurement and not a defect."),
    "how_it_was_established": (
        "the two runs' stdout and their published records: 'denial re-asserted=True after 248.5s' "
        "for the run that sent them, 'denial re-asserted=False after 308.8s' for the run that did "
        "not. The checkpoint's own row count did not change between the two."),
    "what_it_would_have_cost": (
        "a real observation — 4 of 20 invocations executing after three consecutive denials — "
        "filed as an instrument defect and cited nowhere. It is now replicate 2 of 3 in "
        "results/FINDING-F5-1-REVOCATION.md."),
}


def _migrate(body: dict, label: str) -> dict:
    """Rewrite the provenance wrapper to today's schema. Row data is passed through untouched."""
    reason = REASONS[label]
    n_exec = (body.get("outcomes") or {}).get("executed", 0)
    n_den = (body.get("outcomes") or {}).get("denied_by_iam", 0)
    is_defect = reason["kind"] == "defect"
    out = dict(body)
    out.pop("defect_label", None)
    out.pop("why_it_is_not_the_arm_it_was_filed_under", None)
    out["label"] = label
    out["kind"] = reason["kind"]
    out["what_this_actually_measured"] = (
        f"{body.get('n_done')} direct lambda:Invoke attempts sent after DeleteRolePolicy returned "
        f"successfully, of which {n_exec} still EXECUTED and {n_den} were denied."
        + (" The denial had NOT been confirmed to hold when they were sent — see why_moved."
           if is_defect else
           " The denial HAD been confirmed to hold when they were sent, so this is a valid "
           "measurement of the arm — see why_moved."))
    out["why_moved"] = (
        ("`restored_reassert` is defined as invocations AFTER the denial has been re-asserted, and "
         "'after' was not established when these were sent. " if is_defect else "") + reason["text"])
    out["the_finding_this_supports"] = (
        "removing an IAM permission is not an instantaneous remedy, and confirming the denial does "
        "not establish that it has converged. The document's route-4 and section-4 remedies read "
        "as though revoking a grant closes the path at once; measured here, invocations kept "
        "succeeding after DeleteRolePolicy returned 200 AND after three consecutive denials were "
        "observed. Amendment candidate — see results/FINDING-F5-1-REVOCATION.md.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="print and write nothing")
    args = ap.parse_args()

    if not WRONG.is_file() and RIGHT.is_file():
        print(f"already corrected: {RIGHT.name} exists and {WRONG.name} does not")
        return 0
    for p in (WRONG, FLAPPED):
        if not p.is_file():
            print(f"FAIL: {p} does not exist")
            return 2
    if RIGHT.is_file():
        print(f"FAIL: {RIGHT.name} already exists alongside {WRONG.name}; resolve by hand")
        return 2

    wrong = json.loads(WRONG.read_text(encoding="utf-8"))
    flapped = json.loads(FLAPPED.read_text(encoding="utf-8"))

    # The rows are the one thing that must survive verbatim. Compared before and after, not assumed.
    rows_before = json.dumps(wrong.get("done"), sort_keys=True)

    fixed = _migrate(wrong, "earlier_replicate")
    fixed["label_correction"] = CORRECTION
    assert json.dumps(fixed.get("done"), sort_keys=True) == rows_before, "rows changed"

    flapped_fixed = _migrate(flapped, "flapped_revoke")
    assert json.dumps(flapped_fixed.get("done"), sort_keys=True) == json.dumps(
        flapped.get("done"), sort_keys=True), "rows changed"

    print(f"{WRONG.name}: {wrong.get('outcomes')} -> label earlier_replicate (kind replicate)")
    print(f"{FLAPPED.name}: {flapped.get('outcomes')} -> schema migrated, label unchanged")
    if args.check:
        print(f"  --check: nothing written. Would write {RIGHT.name}, delete {WRONG.name}, "
              f"rewrite {FLAPPED.name}")
        return 0

    RIGHT.write_text(json.dumps(fixed, indent=2, sort_keys=True), encoding="utf-8")
    FLAPPED.write_text(json.dumps(flapped_fixed, indent=2, sort_keys=True), encoding="utf-8")
    WRONG.unlink()
    print(f"  wrote {RIGHT.name}; rewrote {FLAPPED.name}; removed {WRONG.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
