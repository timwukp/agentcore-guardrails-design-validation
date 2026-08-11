#!/usr/bin/env python3
"""The corpus gate: sizes match the seal, the build is byte-reproducible, kappa passes.

Three properties, each of which can fail independently, and none of which the other
two would catch:

1. **The manifest describes the files on disk.** Every recorded sha256 is recomputed.
   Without this, a hand-edited .jsonl would keep a stale, correct-looking manifest
   and every downstream size claim would be about a file that no longer exists.

2. **The build is byte-reproducible.** `build.py --out <tmp>` must produce a tree
   identical to `corpora/`. This is what makes the corpus *evidence* rather than an
   artefact: a reader can regenerate it. It is checked by rebuilding into a
   temporary directory, never in place -- rebuilding in place would overwrite the
   very difference it is meant to detect.

3. **The kappa gate is met, and the report is about THIS corpus and THIS seal.**
   kappa >= gate is necessary but not sufficient: a report can pass its gate while
   describing a corpus that has since changed. So `n_corpus`, `corpus_manifest_total`
   and `prereg_sha256` are all re-checked against the live artefacts.

On (3): `prereg_sha256` in a derived artefact records the seal in force WHEN THAT
ARTEFACT WAS GENERATED -- it is the same provenance stamp `lib/evidence.py` writes
into every API record, and evidence records are never rewritten. That makes a stamp
older than the live seal ambiguous on its own: it could mean "generated under the
previous seal and still valid" or "silently stale". This gate removes the ambiguity
in the only way that is sound -- by requiring the artefact to be REGENERABLE from
the live seal, which is a statement about content, not about a recorded string. A
mismatched stamp therefore fails here and the remedy is to re-run the generator, at
which point property (2) proves nothing but the stamp changed.

Exit codes: 0 all three hold; 1 a property fails; 2 the gate could not run
(per feedback_guard_tool_exit_codes -- a gate that cannot execute must never be
reported as clean).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CORPORA = Path(__file__).resolve().parent
ROOT = CORPORA.parent
MANIFEST = CORPORA / "MANIFEST.json"
IRR = CORPORA / "irr_report.json"
BUILD = CORPORA / "build.py"
STAMP = ROOT / "PREREGISTRATION.sha256"

# Files that are inputs to or outputs of the AUDIT, not of the build. The build
# does not write them, so a byte-diff must not expect them in a fresh tree.
NOT_BUILD_OUTPUT = {"audit_sample.jsonl", "audit_ratings.jsonl", "irr_report.json",
                    "LABELS.md", "labeling_protocol.md", "build.py", "banks.py",
                    "audit.py", "verify_corpora.py"}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fatal(msg: str) -> int:
    print(f"FATAL: {msg}", file=sys.stderr)
    return 2


def check_manifest(problems: list[str]) -> int:
    """Every file the manifest names exists, and its sha256 still matches."""
    n = 0
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = man["files"]
    if not files:
        problems.append("MANIFEST.json records zero files, which cannot be right")
        return 1
    total = 0
    for rel, spec in sorted(files.items()):
        p = CORPORA / rel
        n += 1
        if not p.is_file():
            problems.append(f"{rel}: named in the manifest, absent on disk")
            continue
        got = sha256_file(p)
        n += 1
        if got != spec["sha256"]:
            problems.append(f"{rel}: sha256 {got[:12]}… but manifest says "
                            f"{spec['sha256'][:12]}… — the file changed after the build")
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        n += 1
        if len(lines) != spec["items"]:
            problems.append(f"{rel}: {len(lines)} lines, manifest says {spec['items']}")
        total += spec["items"]

    n += 1
    if total != man["total_items"]:
        problems.append(f"manifest per-file items sum to {total}, "
                        f"total_items says {man['total_items']}")

    # And the reverse direction: a .jsonl on disk that the manifest does not name is
    # an unaccounted corpus file, which a checksum sweep alone would never notice.
    on_disk = {str(p.relative_to(CORPORA)) for p in CORPORA.rglob("*.jsonl")
               if p.name not in NOT_BUILD_OUTPUT}
    n += 1
    extra = on_disk - set(files)
    if extra:
        problems.append(f"{len(extra)} .jsonl file(s) on disk are not in the "
                        f"manifest: {sorted(extra)[:5]}")
    return n


def check_reproducible(problems: list[str]) -> int:
    """`build.py --out <tmp>` must reproduce corpora/ byte for byte."""
    n = 0
    with tempfile.TemporaryDirectory(prefix="grx-corp-repro-") as td:
        dst = Path(td) / "corpora"
        r = subprocess.run([sys.executable, str(BUILD), "--out", str(dst)],
                           capture_output=True, text=True, cwd=str(ROOT))
        n += 1
        if r.returncode != 0:
            problems.append(f"build.py --out failed (rc={r.returncode}): "
                            f"{(r.stderr or r.stdout).strip()[-300:]}")
            return n
        n += 1
        if not dst.is_dir():
            problems.append("build.py --out wrote nothing, so 'reproducible' would "
                            "be true of an empty tree")
            return n

        built = {str(p.relative_to(dst)) for p in dst.rglob("*")
                 if p.is_file() and p.name not in NOT_BUILD_OUTPUT}
        live = {str(p.relative_to(CORPORA)) for p in CORPORA.rglob("*")
                if p.is_file() and p.name not in NOT_BUILD_OUTPUT
                and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        n += 1
        if built != live:
            problems.append(
                f"the rebuilt tree differs in MEMBERSHIP: only-live={sorted(live-built)[:5]} "
                f"only-rebuilt={sorted(built-live)[:5]}")
        n += 1
        if not built:
            problems.append("the rebuilt tree contains zero comparable files")
            return n

        for rel in sorted(built & live):
            n += 1
            if sha256_file(dst / rel) != sha256_file(CORPORA / rel):
                problems.append(f"{rel}: rebuilt bytes differ from the committed "
                                f"corpus — the build is not deterministic, or the "
                                f"file was edited by hand")
    return n


def check_kappa(problems: list[str]) -> int:
    """The gate is met, and the report describes the live corpus and the live seal."""
    n = 0
    irr = json.loads(IRR.read_text(encoding="utf-8"))
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seal = STAMP.read_text(encoding="utf-8").split()[0]

    gate = irr["gate"]
    kappa = irr["kappa"]
    n += 1
    if not (0.0 <= kappa <= 1.0):
        problems.append(f"kappa={kappa} is not a kappa")
    n += 1
    if kappa < gate:
        problems.append(f"kappa={kappa:.4f} is below the gate {gate}")
    n += 1
    if irr["passes_gate"] is not (kappa >= gate):
        problems.append("passes_gate disagrees with kappa vs gate")

    # The gate value itself must be the sealed one, not a number the report chose.
    import yaml
    pr = yaml.safe_load((ROOT / "PREREGISTRATION.yaml").read_text(encoding="utf-8"))
    sealed_gate = pr["corpora"]["labelling"]["inter_rater"]["gate"]
    n += 1
    if gate != sealed_gate:
        problems.append(f"the report's gate {gate} is not the sealed gate {sealed_gate}")

    n += 1
    if irr["n_corpus"] != man["total_items"]:
        problems.append(f"the audit rated a corpus of {irr['n_corpus']} items; the "
                        f"manifest now has {man['total_items']}")
    n += 1
    if irr["corpus_manifest_total"] != man["total_items"]:
        problems.append(f"corpus_manifest_total={irr['corpus_manifest_total']} but "
                        f"the manifest says {man['total_items']}")
    n += 1
    if irr["n_rated"] <= 0:
        problems.append("n_rated is not positive, so kappa is about nothing")

    # An UNSURE counted as agreement would inflate kappa; the protocol says otherwise.
    n += 1
    if irr.get("unsure_counted_as") != "disagreement":
        problems.append("unsure_counted_as is not 'disagreement'")

    # Provenance: see the module docstring. A stale stamp fails, and the remedy is
    # to re-run the generator -- which the reproducibility check then proves changed
    # nothing else.
    for name, art in (("irr_report.json", irr), ("MANIFEST.json", man)):
        n += 1
        if art.get("prereg_sha256") != seal:
            problems.append(
                f"{name} was generated under seal "
                f"{str(art.get('prereg_sha256'))[:12]}… but the live seal is "
                f"{seal[:12]}… — re-run the generator so the artefact is known to "
                f"be regenerable from the seal in force")
    return n


# Floors are the number of assertions each check yields on the CURRENT artefacts,
# rounded down: the point is to catch a check that has stopped asserting, so a floor
# above the true yield fails in service (which is how the 11 first written here for
# kappa_gate was caught -- it yields 10) and a floor far below it catches nothing.
CHECKS = [
    ("manifest_matches_disk", check_manifest, 100),
    ("build_is_reproducible", check_reproducible, 40),
    ("kappa_gate", check_kappa, 10),
]
REQUIRED_CHECKS = {"manifest_matches_disk", "build_is_reproducible", "kappa_gate"}


def main(argv: list[str] | None = None) -> int:
    for p in (MANIFEST, IRR, BUILD, STAMP):
        if not p.is_file():
            return fatal(f"{p.relative_to(ROOT)} is missing — the corpus gate "
                         f"cannot run, which is not the same as passing")

    present = {name for name, _fn, _floor in CHECKS}
    if present != REQUIRED_CHECKS:
        return fatal(f"the CHECKS table does not match REQUIRED_CHECKS: "
                     f"missing={sorted(REQUIRED_CHECKS - present)} "
                     f"unexpected={sorted(present - REQUIRED_CHECKS)}")

    problems: list[str] = []
    starved: list[str] = []
    total = 0
    for name, fn, floor in CHECKS:
        n = fn(problems)
        total += n
        if n < floor:
            starved.append(f"{name} ran {n} assertion(s), expected >= {floor}")

    # Problems are reported BEFORE floors, and the floor is not applied when a check
    # already found something. A check that hits a real failure may legitimately
    # short-circuit -- check_reproducible returns early when the builder exits
    # non-zero, because there is no tree to compare -- and that yields a low count
    # for a reason it has already explained. Reporting "the check stopped asserting"
    # there would replace an accurate diagnosis with a misleading one. The floor's
    # target is the SILENT case: few assertions and no problems.
    if problems:
        print(f"FAILED — {len(problems)} problem(s) in {total} assertions:",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        if starved:
            print("  (also, below the expected assertion yield, which a check that "
                  "short-circuits on a real failure will do:", file=sys.stderr)
            for s in starved:
                print(f"     - {s}", file=sys.stderr)
            print("  )", file=sys.stderr)
        return 1

    if starved:
        print("A check that stops asserting is indistinguishable from a check that "
              "passes:", file=sys.stderr)
        for s in starved:
            print(f"  - {s}", file=sys.stderr)
        return 2

    irr = json.loads(IRR.read_text(encoding="utf-8"))
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    print(f"OK — {total} assertions over {man['total_items']} items in "
          f"{len(man['files'])} files")
    print(f"  manifest sha256 matches disk, build reproduces byte for byte")
    print(f"  kappa = {irr['kappa']:.4f} >= {irr['gate']} over {irr['n_rated']} "
          f"rated items")
    print(f"  generated under the live seal "
          f"{man['prereg_sha256'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
