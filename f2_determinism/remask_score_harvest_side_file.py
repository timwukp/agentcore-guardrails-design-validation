#!/usr/bin/env python3
"""Re-mask `results/phase1/F2_score_harvest_shared.json` in place — the DEV-P4-30 repair.

Why a separate script rather than a re-run
------------------------------------------
`03_score_harvest.py` wrote its 900-row side file with a bare `json.dumps` and shipped the
account id six times: `account_id`, and `attributes.aws.account.id` under
`join.<arm>.log_surface.numeric_strings_seen`. The script is fixed and every future run masks.
This file was written before the fix.

Re-running the script would not repair it. The harvest reads the log surface over the window
`t0..t1` of its own invocation, so a resume that skips every trial matches no events, and the
`every_arm_was_evaluated` gate fails on a degenerate window (DEV-P4-29). Repairing the file
therefore means transforming the bytes that exist, not re-collecting them.

That transformation is exactly equal to the fix, not merely similar to it. The fix writes
`mask_text(json.dumps(obj))`; this file holds `json.dumps(obj)`; so `mask_text(<this file>)`
is byte-identical to what the fixed script would produce from the same `obj`. `--check`
prints the diff without writing it.

What this asserts before it writes
----------------------------------
* the account id resolves through `A.account_id`, the one choke point that registers it with
  the masker — without that registration `mask_text` cannot see a bare 12-digit token, and
  this script would report success having changed nothing (`feedback_vacuous_test_check`);
* the file contains that id before the rewrite. If it does not, this is the wrong file or an
  already-repaired one, and the script exits 3 rather than rewriting bytes for no reason;
* after masking, zero occurrences remain, the text still parses as JSON, and the parsed
  object has the same key structure and the same 900 rows as before.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A  # noqa: E402
import redact  # noqa: E402
import testbed as T  # noqa: E402

TARGET = ROOT / "results" / "phase1" / "F2_score_harvest_shared.json"
D12 = re.compile(r"(?<!\d)\d{12}(?!\d)")


def _shape(obj: object) -> object:
    """Key structure only — enough to prove the mask edited values, not the document."""
    if isinstance(obj, dict):
        return {k: _shape(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [len(obj)] + ([_shape(obj[0])] if obj else [])
    return type(obj).__name__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report what would change and write nothing")
    ap.add_argument("--path", default=str(TARGET), help="file to repair")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.is_file():
        print(f"MISSING — {path} does not exist; nothing to repair", file=sys.stderr)
        return 3

    before = path.read_text(encoding="utf-8")
    obj_before = json.loads(before)

    # The region comes from the ledger, not from the environment, for the same reason every
    # other script in this repo reads it there: `A.factory` takes `region` positionally and
    # write-once, and the only region whose STS answer is the right one is the region the
    # harvest itself ran in. `A.account_id` is the one choke point that calls
    # `redact.register_account_id`, which is what makes the bare 12-digit form visible to
    # `mask_text` at all.
    state = T.State.load()
    aid = A.account_id(A.factory(state.region))    # resolves AND registers with the masker
    n_before = before.count(aid)
    if n_before == 0:
        print(f"NOT THE LEAK — {path.name} carries 0 occurrences of this account id. Either it "
              f"was already repaired, or it was written by an account other than the caller's; "
              f"either way this script must not rewrite it.", file=sys.stderr)
        return 3

    after = redact.mask_text(before)
    n_after = after.count(aid)
    obj_after = json.loads(after)                   # still JSON, before anything is written

    if n_after:
        print(f"INCOMPLETE — {n_after} of {n_before} occurrence(s) survived mask_text. The "
              f"masker did not see them all; do not publish this file.", file=sys.stderr)
        return 1
    if _shape(obj_before) != _shape(obj_after):
        print("SHAPE CHANGED — masking altered the document structure, not just values. "
              "Refusing to write.", file=sys.stderr)
        return 1

    rows_before = {k: len(v) for k, v in (obj_before.get("rows_by_arm") or {}).items()}
    rows_after = {k: len(v) for k, v in (obj_after.get("rows_by_arm") or {}).items()}
    if rows_before != rows_after:
        print(f"ROWS CHANGED — {rows_before} became {rows_after}. Refusing to write.",
              file=sys.stderr)
        return 1

    residual = sorted(set(D12.findall(after)))
    # `--path` exists so this can be rehearsed on a copy outside the tree, so the label must
    # not assume the file is under ROOT — `relative_to` raises rather than falling back.
    try:
        label = str(path.resolve().relative_to(ROOT))
    except ValueError:
        label = str(path)
    print(label)
    print(f"  account id occurrences: {n_before} -> {n_after}")
    print(f"  rows by arm: {rows_before} (total {sum(rows_before.values())})")
    print(f"  bytes: {len(before)} -> {len(after)}")
    if residual:
        print(f"  NOTE {len(residual)} other 12-digit token(s) remain, which the gate will "
              f"judge on its own terms: {residual[:6]}")

    if args.check:
        print("  --check: nothing written")
        return 0

    path.write_text(after, encoding="utf-8")
    print(f"  rewrote {path.name} — masked, {sum(rows_after.values())} rows preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
