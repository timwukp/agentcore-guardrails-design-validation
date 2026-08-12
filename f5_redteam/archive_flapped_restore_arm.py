#!/usr/bin/env python3
"""Move an F5-1 `restored_reassert` arm aside, because it measured a different thing.

    python3 f5_redteam/archive_flapped_restore_arm.py --check   # print what it would do
    python3 f5_redteam/archive_flapped_restore_arm.py           # archive + clear the checkpoint
    python3 f5_redteam/archive_flapped_restore_arm.py --label timed_out_revoke

WHY THIS EXISTS
---------------
`restored_reassert` is defined as "20 direct invokes AFTER the grant is removed and the denial has
been re-asserted". Its first live run recorded 9 executions and 11 denials, and the reason is not
that the boundary is leaky: `_wait_for_effect` ended the revoke wait on a SINGLE `denied_by_iam`
probe after the sequence `executed x5 -> denied_by_iam`, and that first denial was a flap in a
fleet that had not converged. So those 20 trials were sent DURING revocation propagation, not
after it.

That makes them a real measurement of something the project had not measured before — how long an
`Invoke` keeps succeeding after `DeleteRolePolicy` returns 200 and a probe confirms the denial —
and NOT a measurement of the arm they are filed under. Leaving them in place would keep
`grant_was_removed_and_denial_reasserted` false forever, because a resume serves the arm from its
checkpoint and never re-sends it. Deleting them would discard the propagation finding.

So they are archived with their provenance and the checkpoint is cleared, and `_wait_for_effect`
now requires `PROP_CONFIRM_N` consecutive confirmations so the re-run measures the arm's actual
definition. Recorded as a deviation in DEVIATIONS.md.

WHAT THIS DOES NOT DO
---------------------
It does not touch the evidence tree. Every one of those 20 invocations is still archived under
`evidence/<run_id>/f5_redteam/F5-1/` with its full request and response, so the archive written
here is an index into records that remain where they were, not a copy that could drift from them.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

CASE = "F5-1"
ARM = "restored_reassert"
CP_PATH = ROOT / "results" / "checkpoints" / f"{CASE}__{ARM}.json"

# An archive label is not free text, and the reason is not tidiness. This script's whole licence to
# discard a live arm is that the arm answered a different question than the one it was filed under,
# so the SPECIFIC reason has to travel with the rows. A `--reason "whatever"` flag would let a
# future run launder any inconvenient arm out of the result by typing a sentence; an enumeration
# means adding a new justification is a code change that shows up in review.
#
# Two KINDS, and conflating them is the mistake this enumeration was rewritten to stop. A `defect`
# arm was sent against a state the run's own rule says was never established, so it is not the arm
# it was filed under. A `replicate` arm is a perfectly valid measurement that is being set aside so
# the arm can be taken again under a changed instrument — nothing is wrong with it, and calling it
# a defect would delete a real observation under a false description. The first use of --label
# timed_out_revoke did exactly that: the rows were attributed to a 308.8s timeout when the log shows
# that run re-sent nothing and served the arm from the PREVIOUS run's checkpoint, where the revoke
# had converged legitimately at 248.5s. The label was corrected to earlier_replicate.
REASONS = {
    "flapped_revoke": {
        "kind": "defect",
        "text": (
            "`_wait_for_effect` ended the revoke wait on a SINGLE `denied_by_iam` probe after the "
            "sequence `executed x5 -> denied_by_iam`, and that first denial was a flap in a fleet "
            "that had not converged, so 'after the denial was re-asserted' was never established. "
            "The wait now requires PROP_CONFIRM_N consecutive confirmations."),
    },
    "earlier_replicate": {
        "kind": "replicate",
        "text": (
            "NOT a defect. These rows were sent after the revoke wait confirmed three consecutive "
            "denials (248.5s), which is the arm's definition, and 4 of 20 invocations still "
            "executed. They are set aside only because a checkpointed arm is served from disk on "
            "the next run, so leaving them in place would mean the arm is never re-measured after "
            "the revoke bound changed from PROP_MAX_S to PROP_MAX_REVOKE_S. They count as a "
            "replicate of the reconvergence finding and are cited as one."),
    },
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="print and write nothing")
    ap.add_argument("--label", default="flapped_revoke", choices=sorted(REASONS),
                    help="why this arm is being moved aside; see REASONS for the two kinds")
    args = ap.parse_args()
    archive_path = (ROOT / "results" / "checkpoints"
                    / f"{CASE}__{ARM}__{args.label}_archive.json")

    if not CP_PATH.is_file():
        print(f"FAIL: {CP_PATH} does not exist; there is nothing to archive")
        return 2
    body = json.loads(CP_PATH.read_text(encoding="utf-8"))
    done = body.get("done") or {}
    outcomes = collections.Counter(v.get("outcome") for v in done.values())

    # Refuse to move a CLEAN arm, whatever the label. Zero executions means the strict post-restore
    # form is satisfied, which is the best outcome this arm can have and leaves nothing to
    # re-measure. This applies to `replicate` as much as to `defect`: the only arm worth setting
    # aside is one that still has to be taken again, and a script that will move any arm on request
    # is a way to make an inconvenient result disappear.
    if outcomes.get("executed", 0) == 0:
        print(f"FAIL: {CP_PATH} records {dict(outcomes)} — no executions, so the strict "
              f"post-restore form is SATISFIED and there is nothing to re-measure. Refusing to "
              f"move a clean arm.")
        return 2
    if archive_path.is_file():
        print(f"FAIL: {archive_path} already exists. Refusing to overwrite an archive — inspect "
              f"it and move it aside deliberately if this really should replace it.")
        return 2

    n_exec = outcomes.get("executed", 0)
    reason = REASONS[args.label]
    is_defect = reason["kind"] == "defect"
    archive = {
        "archived_from": CP_PATH.name,
        "case_id": body.get("case_id"),
        "cell": body.get("cell"),
        "n_done": body.get("n_done"),
        "outcomes": dict(outcomes),
        "label": args.label,
        "kind": reason["kind"],
        "what_this_actually_measured": (
            f"{body.get('n_done')} direct lambda:Invoke attempts sent after DeleteRolePolicy "
            f"returned successfully, of which {n_exec} still EXECUTED and "
            f"{outcomes.get('denied_by_iam', 0)} were denied."
            + (" The denial had NOT been confirmed to hold when they were sent — see why_moved."
               if is_defect else
               " The denial HAD been confirmed to hold when they were sent, so this is a valid "
               "measurement of the arm — see why_moved.")),
        "why_moved": (
            ("`restored_reassert` is defined as invocations AFTER the denial has been "
             "re-asserted, and 'after' was not established when these were sent. "
             if is_defect else "") + reason["text"]),
        "the_finding_this_supports": (
            "removing an IAM permission is not an instantaneous remedy, and confirming the denial "
            "does not establish that it has converged. The document's route-4 and section-4 "
            "remedies read as though revoking a grant closes the path at once; measured here, "
            "invocations kept succeeding after DeleteRolePolicy returned 200 AND after three "
            "consecutive denials were observed. Amendment candidate — see "
            "results/FINDING-F5-1-REVOCATION.md."),
        "evidence_is_unmoved": (
            "every invocation remains archived under evidence/<run_id>/f5_redteam/F5-1/ with its "
            "request and response; this file is an index, not a copy"),
        "done": done,
        "failed": body.get("failed") or {},
        "meta": body.get("meta") or {},
    }

    print(f"{CASE}/{ARM}: {body.get('n_done')} rows, outcomes {dict(outcomes)}")
    print(f"  {n_exec} invocation(s) EXECUTED after DeleteRolePolicy returned; label="
          f"{args.label}")
    if args.check:
        print(f"  --check: nothing written. Would archive to {archive_path.name} and clear "
              f"{CP_PATH.name}")
        return 0

    archive_path.write_text(json.dumps(archive, indent=2, sort_keys=True), encoding="utf-8")
    cleared = {**body, "done": {}, "failed": {}, "n_done": 0, "n_failed": 0}
    tmp = CP_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cleared, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(CP_PATH)
    print(f"  wrote {archive_path}")
    print(f"  cleared {CP_PATH.name} (case_id/cell/meta preserved, 0 rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
