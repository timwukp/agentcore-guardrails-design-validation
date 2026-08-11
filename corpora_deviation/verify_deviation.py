#!/usr/bin/env python3
"""The gate for the UNSEALED corpora: manifest matches disk, build reproduces, no power claim.

`corpora/verify_corpora.py` guards the pre-registered corpora. This guards the three
built after the seal (topic, word_probe, grounding — F3-5/F3-6/F3-7, see
DEVIATIONS.md/DEV-P1-4). It is deliberately NOT a copy of that gate, because the two
trees have different authority and a gate that treated them identically would grant
this one authority it does not have.

Four properties:

1. **The manifest describes the files on disk.** Every sha256 recomputed, every line
   count re-counted, and the reverse direction too — a .jsonl on disk that the manifest
   does not name is an unaccounted corpus file that a checksum sweep alone never sees.

2. **The build is byte-reproducible.** `build_deviation.py --out <tmp>` must reproduce
   this tree exactly. Rebuilt into a temporary directory, never in place: rebuilding in
   place would overwrite the very difference the check exists to find. This is the
   property that makes an unsealed corpus usable as evidence at all — it cannot claim
   the seal's authority, so regenerability is the only authority left to it.

3. **It does not claim to be sealed.** `sealed` must be exactly `False` and
   `why_not_sealed` must be non-empty. This is the one check with no analogue in the
   sealed gate, and it is the reason this file exists rather than a shared helper: the
   failure mode being guarded is *promotion*. A `sealed: true` appearing here — by a
   hand edit, a copy-paste from the sealed manifest, or a future refactor that shares
   the writer — would silently convert three unpowered cases into three that look
   pre-registered, and every downstream `n_met` would then read as a met floor rather
   than a vacuous one.

4. **The stamp is live, and liveness is proven by rebuilding.** `prereg_sha256_at_build`
   records the seal in force when the tree was generated. A stamp older than the live
   seal has two readings — "generated under the previous seal and still valid" or
   "silently stale" — and a recorded string cannot distinguish them. Property (2)
   already establishes the tree is regenerable, so the ambiguity is resolved the same
   way `corpora/verify_corpora.py` resolves it: a mismatched stamp fails, and the remedy
   is to re-run the generator, after which (2) proves nothing but the stamp changed.

What this gate deliberately does NOT check: Cohen's kappa. There is none. These items are
constructed by rule from word banks in `build_deviation.py`, not labelled by annotators,
so there is no second rater and no agreement statistic to gate — inter-rater reliability
is undefined here, not merely low. Asserting a kappa over rule-generated labels would be
measuring the rule against itself. Property (2) is the substitute and it is a stronger
one for constructed data: the labels are reproducible from the code that assigns them.

Exit codes: 0 all four hold; 1 a property fails; 2 the gate could not run — per
feedback_guard_tool_exit_codes, a gate that cannot execute must never report clean.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "MANIFEST.json"
BUILD = HERE / "build_deviation.py"
STAMP = ROOT / "PREREGISTRATION.sha256"

# Not build outputs, so a byte-diff must not expect them in a fresh tree.
NOT_BUILD_OUTPUT = {"build_deviation.py", "verify_deviation.py"}

# The three cases this tree serves. Pinned here so a fourth directory appearing without
# a DEVIATIONS entry fails rather than being absorbed.
EXPECTED_CASES = {"topic": "F3-5", "word_probe": "F3-6", "grounding": "F3-7"}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fatal(msg: str) -> int:
    print(f"FATAL: {msg}", file=sys.stderr)
    return 2


def check_manifest(problems: list[str]) -> int:
    n = 0
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = man.get("files") or {}
    n += 1
    if not files:
        problems.append("MANIFEST.json records zero files, which cannot be right")
        return n

    total = 0
    for rel, spec in sorted(files.items()):
        p = HERE / rel
        n += 1
        if not p.is_file():
            problems.append(f"{rel}: named in the manifest, absent on disk")
            continue
        n += 1
        got = sha256_file(p)
        if got != spec["sha256"]:
            problems.append(f"{rel}: sha256 {got[:12]}… but the manifest says "
                            f"{spec['sha256'][:12]}… — the file changed after the build")
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        n += 1
        if len(lines) != spec["items"]:
            problems.append(f"{rel}: {len(lines)} non-blank lines, manifest says "
                            f"{spec['items']}")
        # Labels are what the oracles condition on, so an unrecorded label is a silent
        # change in what the corpus means, not just in what it contains.
        n += 1
        try:
            seen = sorted({json.loads(ln)["label"] for ln in lines})
        except (json.JSONDecodeError, KeyError) as e:
            problems.append(f"{rel}: unreadable item or missing label ({e})")
        else:
            if seen != sorted(spec["labels"]):
                problems.append(f"{rel}: labels on disk {seen} != manifest "
                                f"{sorted(spec['labels'])}")
        total += spec["items"]

    n += 1
    if total != man.get("total_items"):
        problems.append(f"per-file items sum to {total}, total_items says "
                        f"{man.get('total_items')}")

    on_disk = {str(p.relative_to(HERE)) for p in HERE.rglob("*.jsonl")}
    n += 1
    extra = on_disk - set(files)
    if extra:
        problems.append(f"{len(extra)} .jsonl file(s) on disk are not in the manifest: "
                        f"{sorted(extra)[:5]}")

    n += 1
    if man.get("cases") != EXPECTED_CASES:
        problems.append(f"cases={man.get('cases')} but this gate expects "
                        f"{EXPECTED_CASES} — a new cell needs a DEVIATIONS.md entry "
                        f"before it can be gated as if it had one")
    return n


def check_reproducible(problems: list[str]) -> int:
    n = 0
    with tempfile.TemporaryDirectory(prefix="grx-dev-repro-") as td:
        dst = Path(td) / "corpora_deviation"
        r = subprocess.run([sys.executable, str(BUILD), "--out", str(dst)],
                           capture_output=True, text=True, cwd=str(ROOT))
        n += 1
        if r.returncode != 0:
            problems.append(f"build_deviation.py --out failed (rc={r.returncode}): "
                            f"{(r.stderr or r.stdout).strip()[-300:]}")
            return n
        n += 1
        if not dst.is_dir():
            problems.append("build_deviation.py --out wrote nothing, so 'reproducible' "
                            "would be a true statement about an empty tree")
            return n

        built = {str(p.relative_to(dst)) for p in dst.rglob("*")
                 if p.is_file() and p.name not in NOT_BUILD_OUTPUT}
        live = {str(p.relative_to(HERE)) for p in HERE.rglob("*")
                if p.is_file() and p.name not in NOT_BUILD_OUTPUT
                and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        n += 1
        if built != live:
            problems.append(f"the rebuilt tree differs in MEMBERSHIP: "
                            f"only-live={sorted(live - built)[:5]} "
                            f"only-rebuilt={sorted(built - live)[:5]}")
        n += 1
        if not built:
            problems.append("the rebuilt tree contains zero comparable files")
            return n

        for rel in sorted(built & live):
            n += 1
            if sha256_file(dst / rel) != sha256_file(HERE / rel):
                problems.append(f"{rel}: rebuilt bytes differ from the committed copy "
                                f"— the build is not deterministic, or the file was "
                                f"edited by hand")
    return n


def check_not_sealed(problems: list[str]) -> int:
    """The promotion guard. See property (3) in the module docstring."""
    n = 0
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))

    n += 1
    if man.get("sealed") is not False:
        problems.append(f"sealed={man.get('sealed')!r}, must be exactly False — an "
                        f"unsealed corpus that claims the seal converts three vacuous "
                        f"n_met values into three that read as met floors")
    n += 1
    why = str(man.get("why_not_sealed") or "").strip()
    if not why:
        problems.append("why_not_sealed is empty; 'not sealed' with no reason is "
                        "indistinguishable from an oversight")
    n += 1
    if "planned_n" not in why:
        problems.append("why_not_sealed does not mention planned_n, which is the "
                        "consequence a reader needs to carry forward")

    # And the claim must still be true of the live bindings: these three cases must have
    # no sealed n. If a future seal adds one, this tree stops being the right home for
    # their corpus and the deviation entry stops being accurate.
    sys.path.insert(0, str(ROOT / "lib"))
    try:
        import oracle as O
    except Exception as e:                        # noqa: BLE001 - reported, not raised
        problems.append(f"could not import lib/oracle.py to re-check planned_n: {e}")
        return n + 1
    for cell, case in sorted(EXPECTED_CASES.items()):
        n += 1
        got = O.planned_n(case)
        if got is not None:
            problems.append(f"{case} ({cell}) now has a sealed planned_n={got}; "
                            f"why_not_sealed and DEV-P1-4 are out of date")
    return n


def check_stamp_live(problems: list[str]) -> int:
    n = 0
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seal = STAMP.read_text(encoding="utf-8").split()[0]
    n += 1
    got = str(man.get("prereg_sha256_at_build") or "")
    if got != seal:
        problems.append(f"MANIFEST.json was generated under seal {got[:12] or '(none)'}… "
                        f"but the live seal is {seal[:12]}… — re-run "
                        f"build_deviation.py so the tree is known to be regenerable "
                        f"from the seal in force")
    n += 1
    if len(seal) != 64:
        problems.append(f"PREREGISTRATION.sha256 does not hold a sha256: {seal[:20]!r}")
    return n


# Floors are the assertion yield on the CURRENT artefacts, rounded down. The target is
# the SILENT case — few assertions and no problems — which is how a check that has
# stopped asserting looks from the outside.
CHECKS = [
    ("manifest_matches_disk", check_manifest, 22),
    ("build_is_reproducible", check_reproducible, 8),
    ("not_sealed", check_not_sealed, 6),
    ("stamp_is_live", check_stamp_live, 2),
]
REQUIRED_CHECKS = {"manifest_matches_disk", "build_is_reproducible", "not_sealed",
                   "stamp_is_live"}


def main(argv: list[str] | None = None) -> int:
    for p in (MANIFEST, BUILD, STAMP):
        if not p.is_file():
            return fatal(f"{p.relative_to(ROOT)} is missing — the unsealed-corpus gate "
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

    # Problems before floors, and no floor complaint when a check already found
    # something: a check that short-circuits on a real failure yields a low count for a
    # reason it has already explained, and reporting "it stopped asserting" there would
    # replace an accurate diagnosis with a misleading one.
    if problems:
        print(f"FAILED — {len(problems)} problem(s) in {total} assertions:",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        if starved:
            print("  (also below the expected assertion yield, which a check that "
                  "short-circuits on a real failure will be:", file=sys.stderr)
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

    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    print(f"OK — {total} assertions over {man['total_items']} items in "
          f"{len(man['files'])} files")
    print("  manifest sha256 matches disk, build reproduces byte for byte")
    print(f"  sealed=false, no power claim for "
          f"{', '.join(sorted(EXPECTED_CASES.values()))} (DEVIATIONS.md/DEV-P1-4)")
    print(f"  generated under the live seal {man['prereg_sha256_at_build'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
