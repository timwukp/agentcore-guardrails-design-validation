#!/usr/bin/env python3
"""Refresh the hand-over bundle's copy of this repo, and check the counts its README states.

    python3 tools/sync_handover_bundle.py <bundle-dir>            # dry run: report the drift
    python3 tools/sync_handover_bundle.py <bundle-dir> --apply     # copy, prune, rewrite the manifest

WHY THIS EXISTS
---------------
`~/Downloads/AgentCore-guardrails-closed-loop-practices/` (the path is an ARGUMENT, not a constant —
nothing in a distributable file should name a local directory) holds the deliverables, the document
lineage, and a copy of this whole working tree under `validation/`, plus a `MANIFEST.sha256` for
`shasum -c`. It has been assembled and re-synced four times **by hand**, and it has drifted every
single time. On 2026-08-17 the drift was: its README claimed **21** deficiencies when the register
held **31**, it described the repo as current at a commit five merges old, it announced two pull
requests as *still open* that had been merged two days earlier, it said the EC2 runner was *stopped*
while the runner was RUNNING and billing, `validation/WHITEPAPER.md` was simply absent, and the
manifest was two days stale so `shasum -c` would report mismatches that are ordinary work rather
than corruption.

Every one of those is the same defect: a copy maintained by remembering what changed. The fix is to
derive what to copy (`feedback_fix_producer_not_janitor` — repair the producer, not the symptom), and
to make the README's numbers CHECKED rather than retyped (`feedback_prose_is_not_verified`).

WHAT IS IN THE BUNDLE, AND WHY THAT IS NOT `lib/tests/scan_scope.py`
--------------------------------------------------------------------
The include rule below is not new policy. It is the policy the bundle README already states in
prose, under *What was deliberately left out* — virtualenvs (absolute shebangs; a copied venv is a
broken venv), regenerated caches, `runner/.state/incoming/` (pull staging already merged into
`results/`), `runner/.state/*.tar.gz` (snapshots of this very tree), and Office lock files. This
script only makes that paragraph executable.

It deliberately does **not** import `out_of_scope` from `lib/tests/scan_scope.py`, even though the
two overlap on caches. That predicate answers *"is this file this repo's own source?"* and therefore
excludes `evidence/` and `runner/.state/`; this one answers *"does this file belong in a local
hand-over archive?"* and **includes `evidence/` on purpose** — 32,000 unredacted API responses whose
entire value is that a finding can be taken to AWS Support by request id. Sharing one predicate
between two different questions is how a scope becomes wrong for both.

    ⚠️ Because of that, a synced bundle is NOT distributable. It contains unredacted account ids,
       ARNs and bucket names by design. The bundle README says so twice; this script re-states it on
       every run so that nobody learns the policy only from a document they did not read.

WHAT THIS REFUSES TO DO
-----------------------
The mirror direction is repo → bundle, and `--apply` DELETES bundle files that no longer exist in
the repo, because a copy that only ever gains files keeps serving content the repo has retracted.
That makes this a destructive tool pointed at a directory outside the repo, so:

  * it refuses to run against a directory that does not look like the bundle (all five markers);
  * it refuses to plan from a repo scan that came back implausibly small (`FILE_FLOOR`) — a broken
    predicate returning nothing would otherwise present itself as "delete everything"
    (`feedback_zero_file_scan_is_error`, in its most expensive possible form);
  * it refuses to prune more than `PRUNE_FRACTION` of the bundle without `--allow-prune`;
  * it never touches `deliverables/`, `document-lineage/` or the bundle README except to VERIFY
    them. `document-lineage/` is frozen history whose sources are not all in this repo, and prose is
    not something a script should rewrite — a wrong count is reported with the derived value so a
    human fixes the sentence around it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# All five must be present for a directory to be accepted as the bundle. A marker set, not one
# marker: `validation/` alone would also match a half-built copy, and this tool deletes.
BUNDLE_MARKERS: tuple[str, ...] = (
    "README.md", "MANIFEST.sha256", "deliverables", "document-lineage", "validation",
)
MIRROR = "validation"          # the only subtree this script owns
MANIFEST = "MANIFEST.sha256"

# Directory-name PREFIXES, so the next virtualenv is covered before it is created. This is the
# lesson of `lib/tests/scan_scope.py`: a scope spelled as a set of names cannot notice a new name.
EXCLUDED_DIR_PREFIXES: tuple[str, ...] = (".venv",)
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset({
    ".git", "__pycache__", ".pytest_cache", "node_modules", ".wheel_cache",
})
EXCLUDED_FILE_GLOBS: tuple[str, ...] = ("*.pyc", ".DS_Store", "~$*")

RUNNER_STATE = Path("runner/.state")
RUNNER_STAGING = Path("runner/.staging")

# A plausibility floor on the repo scan, not decoration: see WHAT THIS REFUSES TO DO.
FILE_FLOOR = 20_000
PRUNE_FRACTION = 0.05

# Sites in the bundle README that state a number this script can derive. Exact counts, not floors:
# the regexes are phrasing-shaped, so a reworded sentence stops being recognised, the site count
# DROPS, and this fails — which forces a look instead of silently checking less than it used to.
# Same reasoning as `EXPECTED_PROSE_SITES` in claims/tests/test_future_work_register.py.
EXPECTED_CLAIM_SITES = {"deficiencies": 2, "inventory": 1, "manifest": 1}

# Each pattern's groups line up positionally with the derived values in `check_claims`.
DEFICIENCY_RE = re.compile(r"\*{0,2}(\d{1,3})\*{0,2}\s+(?:named\s+)?deficiencies")
# The inventory line is matched by its FULL canonical phrasing, not by `(\d+) MB` — the first draft
# of this check used the loose form and "agreed" with three figures that are not the bundle's size at
# all: `validation/evidence/` at 150 MB, the excluded virtualenvs at 284 MB, the excluded wheel cache
# at 224 MB. A check labelled "bundle size" whose match set includes other trees reports on a
# quantity nobody claimed (`feedback_label_must_match_computation`).
INVENTORY_RE = re.compile(r"\*\*([\d,]+) files, ([\d,]+) MB\*\*")
MANIFEST_RE = re.compile(r"sha256 of all ([\d,]+) files")
ITEM_RE = re.compile(r"^### (\d+)\. ", re.M)


# ---------------------------------------------------------------------------------------------
# What belongs in the bundle
# ---------------------------------------------------------------------------------------------

def exclusion_reason(rel: Path) -> str | None:
    """Why `rel` (repo-relative file path) is not part of the bundle, or None if it belongs."""
    for part in rel.parts[:-1]:
        if part in EXCLUDED_DIR_NAMES:
            return f"cache directory {part}/"
        if any(part.startswith(p) for p in EXCLUDED_DIR_PREFIXES):
            return f"virtualenv {part}/ (absolute shebangs; a copied venv is broken)"
    for pattern in EXCLUDED_FILE_GLOBS:
        if fnmatch(rel.name, pattern):
            return f"transient file matching {pattern}"
    if rel.is_relative_to(RUNNER_STAGING):
        return "runner/.staging/ (not the sanctioned pull path; see .gitignore)"
    if rel.is_relative_to(RUNNER_STATE):
        inner = rel.relative_to(RUNNER_STATE)
        if len(inner.parts) > 1:
            # `incoming/<stamp>/…`, 1.6 GB of pull staging whose contents are merged into results/.
            return f"runner/.state/{inner.parts[0]}/ subtree"
        if rel.name.endswith(".tar.gz"):
            return "runner/.state archive (a snapshot of this same tree)"
    return None


def repo_files() -> dict[Path, Path]:
    """Every repo file that belongs in the bundle, keyed by repo-relative path."""
    out = {p.relative_to(ROOT): p for p in ROOT.rglob("*")
           if p.is_file() and not p.is_symlink()
           and exclusion_reason(p.relative_to(ROOT)) is None}
    if len(out) < FILE_FLOOR:
        raise SystemExit(
            f"refusing to plan: the repo scan found only {len(out):,} files, floor {FILE_FLOOR:,}. "
            f"This tool DELETES bundle files absent from the repo, so an under-reading scan is not "
            f"a small sync — it is a request to empty the bundle. Fix the scan, not the floor.")
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------------------------

class Plan:
    def __init__(self) -> None:
        self.add: list[Path] = []
        self.replace: list[Path] = []
        self.delete: list[Path] = []
        self.hashes: dict[Path, str] = {}   # bundle-relative path -> sha256, reused by the manifest

    @property
    def dirty(self) -> bool:
        return bool(self.add or self.replace or self.delete)


def plan_mirror(bundle: Path, source: dict[Path, Path]) -> Plan:
    """Compare the repo against `<bundle>/validation` by CONTENT, never by mtime.

    Size-and-mtime is exactly the comparison this project has been burned by twice — `shutil.copy2`
    restores the source mtime, so a stale copy can carry a timestamp that argues it is fresh
    (`feedback_copy2_serves_the_mutant`, `feedback_pyc_serves_the_mutant`). Sizes are compared first
    only to skip hashing a file already known to differ.
    """
    plan = Plan()
    mirror = bundle / MIRROR
    present = {p.relative_to(mirror) for p in mirror.rglob("*") if p.is_file() and not p.is_symlink()}

    for rel, src in sorted(source.items()):
        dst = mirror / rel
        if rel not in present:
            plan.add.append(rel)
            continue
        if src.stat().st_size != dst.stat().st_size:
            plan.replace.append(rel)
            continue
        digest = sha256(dst)
        if digest != sha256(src):
            plan.replace.append(rel)
        else:
            plan.hashes[Path(MIRROR) / rel] = digest

    for rel in sorted(present - set(source)):
        plan.delete.append(rel)
    return plan


def apply_mirror(bundle: Path, source: dict[Path, Path], plan: Plan, allow_prune: bool) -> None:
    mirror = bundle / MIRROR
    budget = max(1, int(len(list(mirror.rglob("*"))) * PRUNE_FRACTION))
    if len(plan.delete) > budget and not allow_prune:
        raise SystemExit(
            f"refusing to delete {len(plan.delete):,} bundle files (soft budget {budget:,}, "
            f"{PRUNE_FRACTION:.0%} of the mirror). Either the repo really did retract that much, or "
            f"the include rule broke. Look at the list above, then pass --allow-prune if it is right.")

    for rel in plan.add + plan.replace:
        dst = mirror / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source[rel], dst)
        plan.hashes[Path(MIRROR) / rel] = sha256(dst)

    for rel in plan.delete:
        (mirror / rel).unlink()
    for directory in sorted((p for p in mirror.rglob("*") if p.is_dir()),
                            key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()


def verify_deliverables(bundle: Path) -> list[str]:
    """`deliverables/` holds copies of files version-controlled at the repo root. Verify, and refresh.

    These are the four files a reader is actually handed, so a drifted copy here is worse than a
    drifted copy under `validation/` — it is the wrong document under the right name.
    """
    notes: list[str] = []
    for dst in sorted((bundle / "deliverables").iterdir()):
        if not dst.is_file() or exclusion_reason(Path(dst.name)):
            continue
        src = ROOT / dst.name
        if not src.exists():
            notes.append(f"  ? {dst.name} — no counterpart at the repo root; left alone")
        elif sha256(src) != sha256(dst):
            shutil.copy2(src, dst)
            notes.append(f"  ↻ {dst.name} — refreshed from the repo")
    return notes


# ---------------------------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------------------------

def manifest_lines(bundle: Path, known: dict[Path, str]) -> list[str]:
    """`<sha256>  ./<path>` for every bundle file except the manifest itself, sorted by path.

    Sorted rather than in directory order so that two runs on the same content produce a
    byte-identical manifest: an artifact whose diff is noise cannot be reviewed.
    """
    lines = []
    for path in bundle.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(bundle)
        if rel == Path(MANIFEST):
            continue
        lines.append(f"{known.get(rel) or sha256(path)}  ./{rel.as_posix()}")
    return sorted(lines, key=lambda line: line.split("  ./", 1)[1])


# ---------------------------------------------------------------------------------------------
# The README's derivable numbers
# ---------------------------------------------------------------------------------------------

def register_size() -> int:
    items = [int(n) for n in ITEM_RE.findall((ROOT / "FUTURE-WORK.md").read_text(encoding="utf-8"))]
    if not items:
        raise SystemExit("FUTURE-WORK.md yielded no `### N.` items — the register parse is broken")
    return len(items)


def check_claims(bundle: Path, file_count: int, megabytes: int, manifest_entries: int) -> list[str]:
    """Compare each derivable number in the bundle README to the derived value. Report, never rewrite.

    `file_count` and `manifest_entries` differ by exactly one — the manifest does not list itself —
    and the README states both, in two sentences about two different things. They are passed
    separately rather than one being inferred from the other: two numbers, two claims
    (`feedback_two_numbers_two_claims`).

    Returns the failure lines; an empty list means every recognised site agreed.
    """
    text = (bundle / "README.md").read_text(encoding="utf-8")
    expected = {
        "deficiencies": (DEFICIENCY_RE, (register_size(),)),
        "inventory": (INVENTORY_RE, (file_count, megabytes)),
        "manifest": (MANIFEST_RE, (manifest_entries,)),
    }
    failures, found = [], {k: 0 for k in expected}
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, (pattern, derived) in expected.items():
            for match in pattern.finditer(line):
                found[label] += 1
                for stated, want in zip(match.groups(), derived):
                    if int(stated.replace(",", "")) != want:
                        failures.append(
                            f"  README.md:{lineno} states {match.group(0).strip()!r} "
                            f"but the derived {label} is {', '.join(f'{d:,}' for d in derived)}")
                        break
    for label, count in found.items():
        if count != EXPECTED_CLAIM_SITES[label]:
            failures.append(
                f"  {label}: recognised {count} site(s), expected exactly "
                f"{EXPECTED_CLAIM_SITES[label]}. A site that stopped matching is a site that "
                f"stopped being checked — read the README and update EXPECTED_CLAIM_SITES "
                f"deliberately, or restore the phrasing.")
    return failures


# ---------------------------------------------------------------------------------------------

def resolve_bundle(raw: str) -> Path:
    bundle = Path(raw).expanduser().resolve()
    missing = [m for m in BUNDLE_MARKERS if not (bundle / m).exists()]
    if missing:
        raise SystemExit(
            f"{bundle} is missing {', '.join(missing)} — that is not the hand-over bundle, and this "
            f"tool deletes files. Point it at the bundle root.")
    if bundle == ROOT or ROOT.is_relative_to(bundle):
        raise SystemExit(f"refusing to sync {bundle} onto itself (it contains the repo)")
    return bundle


def preview(label: str, items: list[Path], limit: int = 12) -> None:
    print(f"{label}: {len(items):,}")
    for rel in items[:limit]:
        print(f"    {rel.as_posix()}")
    if len(items) > limit:
        print(f"    … and {len(items) - limit:,} more")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bundle", help="path to the hand-over bundle root")
    ap.add_argument("--apply", action="store_true", help="copy, prune and rewrite the manifest")
    ap.add_argument("--allow-prune", action="store_true",
                    help=f"permit deleting more than {PRUNE_FRACTION:.0%} of the mirror")
    args = ap.parse_args(argv)

    bundle = resolve_bundle(args.bundle)
    source = repo_files()
    print(f"repo    {ROOT}: {len(source):,} files in scope for the bundle")
    print(f"bundle  {bundle}")

    plan = plan_mirror(bundle, source)
    preview("  add    ", plan.add)
    preview("  replace", plan.replace)
    preview("  delete ", plan.delete)

    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply to sync.")
        return 1 if plan.dirty else 0

    apply_mirror(bundle, source, plan, args.allow_prune)
    for note in verify_deliverables(bundle):
        print(note)

    lines = manifest_lines(bundle, plan.hashes)
    (bundle / MANIFEST).write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = len(lines) + 1                                   # the manifest does not list itself
    # The SUM OF FILE SIZES, in MB of 10^6 bytes. Say which, because `du -sh` reports ~25% more for
    # this tree — 32,000 mostly-tiny evidence files each round up to a block — and a size with two
    # defensible readings is a size that verifies nothing.
    size_mb = round(sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file()) / 1_000_000)
    print(f"\n{MANIFEST}: {len(lines):,} entries; bundle holds {total:,} files, {size_mb:,} MB "
          f"(sum of file sizes; du reports more)")

    failures = check_claims(bundle, total, size_mb, len(lines))
    print("\n⚠️  This bundle contains unredacted account ids, ARNs and bucket names under "
          "validation/evidence/ and validation/runner/.state/. Do not upload or attach it as-is.")
    if failures:
        print("\nREADME numbers that no longer hold (fix the prose by hand, then re-run):")
        print("\n".join(failures))
        return 1
    print("every derivable number in the bundle README agrees with the tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
