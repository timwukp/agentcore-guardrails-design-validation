"""Do `test_scenes.py`'s assertions discriminate? Break each derivation on purpose and check.

A green suite over a lying payload still proves nothing until each arm is shown to FAIL when the
thing it describes is broken (`feedback_vacuous_test_check`). This script edits `scenes.py` in place,
one mutant at a time, runs the suite, and restores the file — with a no-mutant control first, because
a suite that is already red kills every mutant for free.

Run by hand, never in a gate:

    .venv-oracle/bin/python video/tests/mutation_probe.py

Two properties it has because the first hand-rolled version lacked them: the restore is in a
`finally` AND re-verified by sha before exit (a run killed by a timeout once left a mutant resident
in `scenes.py`, which then serves every later test — `feedback_killed_harness_races_next`), and the
anchor for every mutant is asserted present before anything is written, so a refactor that moves the
code being mutated reports a missing anchor instead of silently probing nothing.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent / "scenes.py"
PYTEST = [".venv-oracle/bin/python", "-m", "pytest", "video/tests/", "-q", "--no-header", "--tb=no"]

# mutant name -> (anchor in scenes.py, replacement)
MUTANTS: dict[str, tuple[str, str]] = {
    "cases summed instead of deduplicated": (
        '        for c in s["cases"]:\n            out.setdefault(c["case"], c)',
        '        for i, c in enumerate(s["cases"]):\n            out[f\'{s["id"]}:{i}\'] = c'),
    "restricted counts cases with ANY restriction": (
        'if set(c["restrictions"]) & non_colouring),',
        'if c["restrictions"]),'),
    "every chapter reads the BEFORE phase": (
        "return _chapter(payload, lang, CHAPTERS[video])",
        'return _chapter(payload, lang, "BEFORE")'),
    "the loop is drawn with nothing faded": (
        "highlight=mine)", "highlight=None)"),
    "highlight is every box that has a status": (
        'mine = {b["id"] for b in cl["boxes"] if b.get("from_section") in sec_ids}',
        'mine = {b["id"] for b in cl["boxes"] if b.get("status")}'),
    "inherited is derived as 'not own' rather than from status_basis": (
        '== "section")', '!= "practice")'),
    # The two rendering defects that shipped in the live overview. Neither was caught by an assertion
    # when it shipped; both are here so a later edit cannot quietly restore them.
    "spine labels are centred on their boxes again": (
        'anchor, tx = "end", spine_label_right',
        'anchor, tx = "middle", b["x"] + b["w"] / 2'),
    "the label clearance is read from the boxes, not the connectors": (
        "spine_label_right = min(0, gutter_x) - 16",
        'spine_label_right = min(b["x"] for b in cl["boxes"]) - 16'),
}


def run() -> tuple[int, str]:
    r = subprocess.run(PYTEST, capture_output=True, text=True, cwd=HERE.parent.parent)
    tail = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    return r.returncode, tail[-1] if tail else "(no output)"


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    before = hashlib.sha256(original.encode()).hexdigest()
    missing = [name for name, (anchor, _) in MUTANTS.items() if anchor not in original]
    if missing:
        print("ANCHOR MISSING — these mutants would probe nothing:")
        for name in missing:
            print(f"  - {name}")
        return 2

    rows: list[tuple[str, int, str]] = []
    try:
        rc, tail = run()
        print(f"no-mutant control: rc={rc}  {tail}")
        if rc != 0:
            print("the suite is already red; fix it before reading any mutant as killed")
            return 2
        for name, (anchor, replacement) in MUTANTS.items():
            TARGET.write_text(original.replace(anchor, replacement), encoding="utf-8")
            rc, tail = run()
            rows.append((name, rc, tail))
            print(f"{'KILLED  ' if rc else 'SURVIVED'} {name}\n           {tail}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")
        after = hashlib.sha256(TARGET.read_text(encoding="utf-8").encode()).hexdigest()
        print(f"scenes.py {'restored' if after == before else 'NOT RESTORED'} ({after[:12]})")
        if after != before:
            return 3

    survivors = [n for n, rc, _ in rows if rc == 0]
    print(f"\n{len(rows) - len(survivors)}/{len(rows)} mutants killed")
    if survivors:
        print("survivors — the assertion for each of these describes nothing:")
        for name in survivors:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
