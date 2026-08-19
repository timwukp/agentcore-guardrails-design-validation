#!/usr/bin/env python3
"""Derive every byte the GRX Live site serves. The ONLY writer of the site payload.

Why this exists, and why it is a build rather than a database
------------------------------------------------------------
The whole discipline of this repository is that a number is derived, never remembered. A DynamoDB
item saying `verdict: FALSE` is a hand-written number wearing a database's clothes: it is a second
source of truth, a second surface the redaction gate must cover, and — worst of the three — it can
be half-updated, so a dashboard can show a new verdict beside a stale census total. A producer run
rewrites a *set* of verdict files together; anything that can display half of that set is itself a
governance defect.

The served dataset is under 10 MB, so none of that risk buys anything. This script reads the
artifacts, derives everything, and emits an immutable payload with a manifest. Atomicity comes from
publishing under `v/<stamp>/` and flipping a pointer, not from a transaction.

What it will not do
-------------------
- It never writes outside `--out`. Every path is checked against the resolved output root.
- It never writes into the repository's own trees. `results/`, `claims/` and `evidence/` are opened
  read-only and the output root is refused if it resolves inside any of them.
- It has a floor on every input. A census that reads 3 cases, a triage that reads 12 rows or a
  phase1 directory holding 9 files is an ERROR, not a small dataset: a payload derived from almost
  nothing renders as a clean, confident, empty dashboard. `feedback_zero_file_scan_is_error`.
- It does not decide what is citable. That is `results/CITATION-POLICY.md`, whose machine block is
  copied through so the UI renders a restriction as data rather than as copy.
- It emits no total it did not compute. `denominators.json` carries each number **with the prose
  definition of what it counts**, because 93 / 92 / 90 / 91 differ for stated reasons and a
  dashboard showing four bare integers invites the reader to assume one of them is wrong.

WHY THE PAYLOAD LIVES OUTSIDE THE REPOSITORY
--------------------------------------------
The default output root is a SIBLING of the repository (`../grx-site-payload`), and `main()` refuses
any root under `ROOT`. This is not tidiness; it is what keeps two gates from corrupting each other.

The payload is published — by S3 upload rather than by `git push`, but published — so it must be
gated. It is also a *derivation* of files that already carry reviewed, path-scoped exceptions in
`check_redaction.py`'s ALLOW table. Put it inside the repo and `check_redaction.py` reads it too, and
then every reviewed exception needs a second entry under a second path. Measured 2026-08-19, first
build: 45 findings, of which 44 were second copies of two already-reviewed lines in
`results/phase1/F5-7b.json` (its VPC CIDR) — and the 45th was real. A gate whose output is 98 %
known-benign is a gate whose reader stops reading, which is precisely how the real one hides.

The alternative — adding the payload's directory to `SKIP_DIRS` — is the single change that would
make `check_redaction.py` blind to the bytes we serve, and `lib/tests/test_redaction_gate_skips.py`
would go GREEN on it, because that test's proxy for "published" is "tracked by git" and the payload
is gitignored *and* published. That proxy breaks the day publication stops meaning GitHub.

So: `check_redaction.py` gates the sources, in the repo; `platform/build/gate_payload.py` gates the
payload, where it lands, importing the same `PATTERNS` and `allowed()` (import, never fork) and
asserting set-equality between what it scanned and what is about to be uploaded. Neither gate has to
waive anything on the other's behalf, and neither can be blinded by a change made for the other's
convenience.

Usage
-----
    .venv-oracle/bin/python platform/build/build_site_data.py            # -> ../grx-site-payload
    .venv-oracle/bin/python platform/build/build_site_data.py --out ~/x --stamp 20260819T120000Z
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

RESULTS = ROOT / "results"
PHASE1 = RESULTS / "phase1"
ARCHIVE = PHASE1 / "archive"
FIGURES = RESULTS / "figures"
TRIAGE = ROOT / "claims" / "triage.csv"

# Deliberately a SIBLING of the repository, not a directory inside it. The reason is in the
# docstring; the enforcement is in `main()`, which refuses any output root under ROOT.
DEFAULT_OUT = ROOT.parent / "grx-site-payload"

# Floors. Each is far below the current value and far above "something went wrong": the point is to
# catch a build that read the wrong tree, not to pin today's counts (which a test derives).
MIN_CASES = 80
MIN_PHASE1_FILES = 80
MIN_TRIAGE_ROWS = 400
MIN_FINDINGS = 10
MIN_REGISTER_ITEMS = 25

# A subtree this big goes to `series/<CASE>.json` and is replaced by a stub. F3-10 is 1.4 MB and is
# the reason: the case page must open without it, and the series viewer fetches it on demand.
SERIES_BYTES = 16 * 1024
MACHINE_RE = re.compile(r"<!--\s*machine\s*\n(.*?)\n-->", re.S)
PROVENANCE_RE = re.compile(r"<!--\s*provenance\s*\n(.*?)\n-->", re.S)


class BuildError(RuntimeError):
    """A derivation could not be made. Never downgraded to a warning."""


def die(msg: str) -> None:
    raise BuildError(msg)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --------------------------------------------------------------------------------------------
# Provenance: which sources each emitted file derives from.
#
# `gate_payload.py` needs this and cannot compute it. A payload file may legitimately contain a value
# that `check_redaction.py`'s ALLOW table excuses under a SOURCE path — `results/phase1/F5-7b.json`'s
# VPC CIDR is the measured case — and the payload gate must be able to inherit that reviewed excuse
# without inventing a new one. Inheriting it requires knowing which source a payload byte came from,
# and only this script knows: it is the thing that did the reading.
#
# Measured 2026-08-19 over the 104-file payload: of 2,410 pattern hits, 2,406 are excused by
# path-INDEPENDENT rules (an ARN whose account field is already `<account>`, a wildcard, an
# AWS-managed policy). Exactly 4 need a path-scoped excuse, in 2 files. So provenance is not carrying
# the bulk of the work — it is carrying the 4 cases where the alternative is a blanket waiver on the
# payload, which is the thing that makes a gate stop being read.
#
# The stack, rather than one "current" scope: a derivation may call another, and a source read by the
# inner one is a source of the outer one too. Recording into every open scope is what makes that true
# without either function knowing about the other.
_READS: list[list[str]] = []


class scope:  # noqa: N801 - used as a context manager, reads as one
    """Collect the repo-relative path of every input read while this is open."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    def __enter__(self) -> "scope":
        _READS.append(self.paths)
        return self

    def __exit__(self, *exc) -> None:
        _READS.pop()

    def sorted(self) -> list[str]:
        return sorted(set(self.paths))


def note_read(rel: str) -> None:
    for open_scope in _READS:
        open_scope.append(rel)


def record_input(p: Path, inputs: dict[str, str]) -> str:
    """Hash a file this build read and record it as an input. Returns its repo-relative path.

    Used where the bytes are parsed by somebody else (`census.load_register()` owns the register's
    grammar, and re-implementing it here to get a hash is how two readers of one file start to
    disagree). The hash is still of the bytes THIS build read.
    """
    rel = str(p.relative_to(ROOT))
    inputs[rel] = sha256_bytes(p.read_bytes())
    note_read(rel)
    return rel


def read_text(p: Path, inputs: dict[str, str]) -> str:
    if not p.is_file():
        die(f"{p.relative_to(ROOT)} is not a file")
    b = p.read_bytes()
    rel = str(p.relative_to(ROOT))
    inputs[rel] = sha256_bytes(b)
    note_read(rel)
    return b.decode("utf-8")


def read_json(p: Path, inputs: dict[str, str]):
    try:
        return json.loads(read_text(p, inputs))
    except json.JSONDecodeError as e:
        die(f"{p.relative_to(ROOT)} is not readable JSON: {e}")


# --------------------------------------------------------------------------------------------
# series splitting


def split_series(obj, prefix: str = "", out: dict | None = None):
    """Move heavy subtrees out of a case record, leaving a stub that names where they went.

    Returns `(light, heavy)`. A stub carries the element count and the byte size, because a series
    with 60 % of its requests found is a different object from one with 100 % and the case page has
    to be able to say so before it fetches anything.
    """
    heavy = {} if out is None else out
    if isinstance(obj, dict):
        light = {}
        for k, v in obj.items():
            light[k] = split_series(v, f"{prefix}.{k}" if prefix else str(k), heavy)[0]
        return light, heavy
    if isinstance(obj, list):
        raw = json.dumps(obj, ensure_ascii=False)
        if len(raw.encode()) >= SERIES_BYTES:
            heavy[prefix] = obj
            return {"$series": prefix, "n": len(obj), "bytes": len(raw.encode())}, heavy
        return [split_series(v, f"{prefix}[{i}]", heavy)[0] for i, v in enumerate(obj)], heavy
    return obj, heavy


# --------------------------------------------------------------------------------------------
# derivations


def derive_register(inputs: dict[str, str]) -> tuple[dict, str, int, str]:
    """The sealed case register, with its seal checked for liveness rather than quoted."""
    import census  # noqa: PLC0415 - the repo's own derivation, reused so there is one implementation

    cases, live_sha = census.load_register()
    n_declared, declared_sha = census.prereg_registry_sha()
    record_input(ROOT / "PREREGISTRATION.yaml", inputs)
    record_input(ROOT / "claims" / "triage_rules.py", inputs)
    if live_sha != declared_sha:
        die(f"the sealed register hashes to {live_sha} but PREREGISTRATION.yaml declares "
            f"{declared_sha} — a drifted seal must fail the build, not be published")
    if len(cases) != n_declared:
        die(f"the register holds {len(cases)} cases but PREREGISTRATION.yaml declares {n_declared}")
    if len(cases) < MIN_CASES:
        die(f"the register read {len(cases)} case(s), below the floor of {MIN_CASES}")
    return cases, live_sha, n_declared, declared_sha


def derive_published(inputs: dict[str, str]) -> dict[str, dict]:
    """Every live verdict file under `results/phase1/`, keyed by case id.

    `archive/` is excluded the way `census.py` excludes it — a superseded artifact is not a verdict.
    A case with two live verdict files is fatal: the dashboard would have to pick one.
    """
    files = sorted(PHASE1.glob("*.json"))
    if len(files) < MIN_PHASE1_FILES:
        die(f"results/phase1/ holds {len(files)} file(s), below the floor of {MIN_PHASE1_FILES}")
    out: dict[str, dict] = {}
    for f in files:
        d = read_json(f, inputs)
        if not isinstance(d, dict) or not isinstance(d.get("case_id"), str):
            continue
        cid = d["case_id"]
        if not d.get("verdict"):
            # A real artifact with no verdict — e.g. F3-11_snapshot.json. Kept out of the verdict
            # count and recorded so the UI can show it exists rather than silently dropping it.
            out.setdefault(cid, {}).setdefault("_no_verdict_files", []).append(f.name)
            continue
        if "verdict" in out.get(cid, {}):
            die(f"{cid} has two live verdict files ({out[cid]['file']} and {f.name}); the site "
                f"cannot choose between them")
        entry = out.setdefault(cid, {})
        entry.update({"file": f.name, "verdict": d["verdict"], "record": d})
    return out


def derive_archive(inputs: dict[str, str]) -> dict[str, list[dict]]:
    """Superseded and set-aside artifacts, with the label that says why each was set aside."""
    out: dict[str, list[dict]] = {}
    for f in sorted(ARCHIVE.glob("*.json")):
        stem = f.stem
        case, _, label = stem.partition("__")
        d = read_json(f, inputs)
        out.setdefault(case, []).append({
            "file": f.name, "label": label or "unlabelled",
            "verdict": d.get("verdict") if isinstance(d, dict) else None,
            "run_id": d.get("run_id") if isinstance(d, dict) else None,
            "sha256": inputs[str(f.relative_to(ROOT))],
        })
    return out


def derive_claims(inputs: dict[str, str]) -> tuple[list[dict], dict[str, list[str]]]:
    rows = list(csv.DictReader(read_text(TRIAGE, inputs).splitlines()))
    if len(rows) < MIN_TRIAGE_ROWS:
        die(f"claims/triage.csv read {len(rows)} row(s), below the floor of {MIN_TRIAGE_ROWS}")
    by_case: dict[str, list[str]] = {}
    for r in rows:
        # Whitespace-token read, not a whole-cell compare: a `cases` cell can hold several ids.
        for cid in (r.get("cases") or "").split():
            by_case.setdefault(cid, []).append(r["claim_id"])
    return rows, by_case


def derive_denominators(cases: dict, published: dict, by_case: dict, rows: list) -> dict:
    n_registered = len(cases)
    with_verdict = {c for c, v in published.items() if v.get("verdict")}
    untestable = sorted(c for c in cases if c not in with_verdict and _untestable(cases[c]))
    eligible = n_registered - len(untestable)
    mapped = sorted(set(by_case) & set(cases))
    return {
        "registered": {
            "n": n_registered,
            "definition": "cases in the sealed register `claims/triage_rules.py::CASES`, whose "
                          "sha256 PREREGISTRATION.yaml declares. This is the only number that "
                          "cannot change without breaking a seal.",
            "derived_from": "claims/triage_rules.py"},
        "verdict_eligible": {
            "n": eligible,
            "definition": f"registered minus the case(s) whose own sealed oracle declares them "
                          f"untestable ({', '.join(untestable) or 'none'}). Being eligible is a "
                          f"property of the oracle, not of whether the run happened.",
            "untestable": untestable,
            "derived_from": "claims/triage_rules.py oracle text"},
        "claim_mapped": {
            "n": len(mapped),
            "definition": "registered cases that at least one row of `claims/triage.csv` points "
                          "at. The three that no claim points at are correct: two are API-surface "
                          "facts about the service model rather than about a document sentence, "
                          "and one is untestable.",
            "unmapped": sorted(set(cases) - set(mapped)),
            "derived_from": "claims/triage.csv `cases` column, whitespace-tokenised"},
        "published": {
            "n": len(with_verdict),
            "definition": "cases with a verdict on disk under `results/phase1/`, excluding "
                          "`archive/`. A published verdict is not the same as a citable one — see "
                          "citation_policy.json.",
            "outstanding": sorted(
                c for c in cases if c not in with_verdict and c not in untestable),
            "derived_from": "results/phase1/*.json"},
        "claims_triaged": {
            "n": len(rows),
            "definition": "rows in `claims/triage.csv`. Rows, not claims: a merge group can hold "
                          "several rows pointing at one canonical claim.",
            "derived_from": "claims/triage.csv"},
    }


def _untestable(entry) -> bool:
    """Does this case's own sealed oracle say it cannot be tested?

    Read from the oracle text rather than from a list of case ids, so a future untestable case is
    counted without an edit here (`feedback_scope_as_namelist`).
    """
    oracle = (entry[3] or "").lower()
    return "untestable" in oracle or "no fault-injection surface" in oracle


def derive_verdict_mix(published: dict) -> dict[str, int]:
    mix: dict[str, int] = {}
    for v in published.values():
        if v.get("verdict"):
            mix[v["verdict"]] = mix.get(v["verdict"], 0) + 1
    return dict(sorted(mix.items()))


def derive_findings(inputs: dict[str, str]) -> list[dict]:
    out = []
    for f in sorted(RESULTS.glob("FINDING-*.md")):
        text = read_text(f, inputs)
        m = PROVENANCE_RE.search(text)
        prov = None
        if m:
            try:
                prov = json.loads(m.group(1))
            except json.JSONDecodeError as e:
                die(f"{f.name}: provenance block is not valid JSON: {e}")
        title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), f.stem)
        out.append({"file": f.name, "title": title, "provenance": prov,
                    "body_md": PROVENANCE_RE.sub("", text).strip(),
                    "sha256": inputs[str(f.relative_to(ROOT))]})
    if len(out) < MIN_FINDINGS:
        die(f"read {len(out)} finding(s), below the floor of {MIN_FINDINGS}")
    return out


def derive_registers(inputs: dict[str, str]) -> dict:
    """`FUTURE-WORK.md`'s numbered items, each under the tier heading that precedes it."""
    text = read_text(ROOT / "FUTURE-WORK.md", inputs)
    items, tier, cur = [], None, None
    for line in text.splitlines():
        if line.startswith("## "):
            tier = line[3:].strip()
            continue
        m = re.match(r"^### (\d+)\.\s+(.*)$", line)
        if m:
            cur = {"n": int(m.group(1)), "tier": tier, "title": m.group(2).strip(), "body_md": []}
            items.append(cur)
            continue
        if cur is not None:
            cur["body_md"].append(line)
    for it in items:
        it["body_md"] = "\n".join(it["body_md"]).strip()
    if len(items) < MIN_REGISTER_ITEMS:
        die(f"FUTURE-WORK.md yielded {len(items)} numbered item(s), below the floor of "
            f"{MIN_REGISTER_ITEMS}")
    ns = [it["n"] for it in items]
    if len(set(ns)) != len(ns):
        die(f"FUTURE-WORK.md has duplicate item numbers: "
            f"{sorted(n for n in set(ns) if ns.count(n) > 1)}")
    side = {}
    for name in ("ERRATA.md", "CENSUS-NOT-MEASURED.md", "DEVIATIONS.md", "EXCLUSION_REGISTER.md"):
        p = RESULTS / name
        side[name] = read_text(p, inputs) if p.is_file() else None
    return {"items": items, "n_items": len(items), "side_registers": side}


def derive_citation_policy(inputs: dict[str, str]) -> dict:
    text = read_text(RESULTS / "CITATION-POLICY.md", inputs)
    m = MACHINE_RE.search(text)
    if not m:
        die("results/CITATION-POLICY.md has no `<!-- machine ... -->` block; the UI would have to "
            "hardcode which verdicts are citable, which is the defect the file exists to fix")
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        die(f"results/CITATION-POLICY.md machine block is not valid JSON: {e}")
    meta["body_md"] = MACHINE_RE.sub("", text).strip()
    return meta


def derive_figures(inputs: dict[str, str]) -> dict:
    man = read_json(FIGURES / "MANIFEST.json", inputs)
    present, missing = [], []
    for p in sorted(FIGURES.glob("fig-*.png")):
        present.append({"file": p.name, "bytes": p.stat().st_size,
                        "sha256": sha256_bytes(p.read_bytes())})
    names = {f["file"] for f in present}
    for n in range(1, 9):
        if not any(f.startswith(f"fig-{n:02d}") for f in names):
            missing.append(f"fig-{n:02d}")
    return {"manifest": man, "present": present, "missing": missing,
            "numeric_check": None,
            "numeric_check_note": "rc of `tools/whitepaper_figures.py --check` under .venv-figs. "
                                  "null means this build did not run it, which the UI must render "
                                  "as 'not verified', never as fresh."}


# --------------------------------------------------------------------------------------------
# emit


def emit(out_root: Path, rel: str, payload, outputs: dict[str, str],
         sources: list[str], provenance: dict[str, list[str]],
         inputs: dict[str, str]) -> None:
    """Mask, write, hash, and record which sources this file derives from.

    `sources` is checked against `inputs` rather than trusted: a provenance entry naming a file this
    build did not read is worse than no entry at all, because `gate_payload.py` would inherit that
    file's reviewed exceptions on the strength of a path that was never opened. An empty source list
    is refused for the same reason — it would silently mean "inherit nothing", which reads identically
    to "nothing to inherit" and is the shape a future maintainer's forgotten argument takes.
    """
    import lib.redact as redact  # noqa: PLC0415 - masking is a write-path concern

    dst = (out_root / rel).resolve()
    if out_root not in dst.parents and dst != out_root:
        die(f"refusing to write outside the output root: {dst}")
    unread = [s for s in sources if s not in inputs]
    if unread:
        die(f"{rel} declares sources this build never read: {unread}. Provenance is what "
            f"gate_payload.py inherits a reviewed redaction exception from; a fictional entry "
            f"would grant an excuse no reviewer ever gave.")
    if not sources:
        die(f"{rel} declares no source. Every emitted file is a derivation of something.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = redact.mask_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    dst.write_text(text, encoding="utf-8")
    outputs[rel] = sha256_bytes(text.encode())
    provenance[rel] = sorted(set(sources))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"output root (default {DEFAULT_OUT}, outside the repository — see "
                         f"WHY THE PAYLOAD LIVES OUTSIDE THE REPOSITORY in this module's docstring)")
    ap.add_argument("--stamp", help="build stamp; default is now, UTC, YYYYmmddTHHMMSSZ")
    ap.add_argument("--clean", action="store_true", help="remove the output root first")
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = ROOT / out_root
    out_root = out_root.resolve()
    for guarded in (RESULTS, ROOT / "claims", ROOT / "evidence", ROOT / "lib"):
        if guarded == out_root or guarded in out_root.parents:
            die(f"refusing an output root inside {guarded.relative_to(ROOT)}; this script must not "
                f"be able to write into the artifacts it derives from")
    if out_root == ROOT or ROOT in out_root.parents:
        die(f"refusing an output root inside the repository ({out_root}). The payload is gated by "
            f"platform/build/gate_payload.py where it lands; inside ROOT it would ALSO be read by "
            f"check_redaction.py, which would then have to waive a derived copy of every reviewed "
            f"exception its sources already carry — and the alternative, skipping the directory, is "
            f"the one change that makes that gate blind to the bytes we publish. Measured "
            f"2026-08-19: with the payload at site/data the repo gate raised 44 findings that were "
            f"all second copies of two already-reviewed lines, which is how a real 45th hides.")
    stamp = args.stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    inputs: dict[str, str] = {}
    outputs: dict[str, str] = {}
    provenance: dict[str, list[str]] = {}

    # One scope per derivation, so each emitted file can declare the sources it actually came from
    # rather than inheriting the whole build's input list. The granularity matters most per case:
    # `cases/F5-7b.json` must inherit F5-7b's reviewed exception and nobody else's.
    with scope() as s_register:
        cases, live_sha, n_declared, declared_sha = derive_register(inputs)
    with scope() as s_published:
        published = derive_published(inputs)
    with scope() as s_archive:
        archive = derive_archive(inputs)
    with scope() as s_claims:
        rows, by_case = derive_claims(inputs)
    denominators = derive_denominators(cases, published, by_case, rows)
    mix = derive_verdict_mix(published)
    with scope() as s_findings:
        findings = derive_findings(inputs)
    with scope() as s_registers:
        registers = derive_registers(inputs)
    with scope() as s_policy:
        policy = derive_citation_policy(inputs)
    with scope() as s_figures:
        figures = derive_figures(inputs)

    restricted: dict[str, list[str]] = {}
    for r in policy.get("restrictions", []):
        for c in r.get("cases", []):
            restricted.setdefault(c, []).append(r["restriction"])
    unknown = sorted(set(restricted) - set(cases))
    if unknown:
        die(f"results/CITATION-POLICY.md names {unknown}, which are not in the sealed register")

    if args.clean and out_root.exists():
        shutil.rmtree(out_root)

    census_rows = []
    for cid in sorted(cases):
        fam, title, tier, oracle, instrument = cases[cid]
        pub = published.get(cid, {})
        census_rows.append({
            "case": cid, "family": fam, "title": title, "tier": tier,
            "has_verdict": bool(pub.get("verdict")), "verdict": pub.get("verdict"),
            "claims": sorted(by_case.get(cid, [])),
            "n_claims": len(by_case.get(cid, [])),
            "citation_restrictions": restricted.get(cid, []),
            "archive_labels": [a["label"] for a in archive.get(cid, [])],
            "files_without_verdict": pub.get("_no_verdict_files", []),
        })
    def put(rel: str, payload, sources: list[str]) -> None:
        emit(out_root, rel, payload, outputs, sources, provenance, inputs)

    census_sources = (s_register.sorted() + s_published.sorted() + s_archive.sorted()
                      + s_claims.sorted() + s_policy.sorted())
    put("census.json", {
        "build_stamp": stamp, "rows": census_rows, "verdict_mix": mix,
        "seal": {"registry_sha256_recomputed": live_sha,
                 "registry_sha256_declared": declared_sha, "n_cases_declared": n_declared,
                 "checked": "recomputed from the register itself and compared, not quoted"},
    }, census_sources)
    put("denominators.json", denominators,
        s_register.sorted() + s_published.sorted() + s_claims.sorted())
    put("claims.json", {"rows": rows, "n_rows": len(rows), "by_case": by_case}, s_claims.sorted())
    put("findings.json", {"findings": findings}, s_findings.sorted())
    put("registers.json", registers, s_registers.sorted())
    put("citation_policy.json", policy, s_policy.sorted())
    put("figures.json", figures, s_figures.sorted())
    put("archive.json", {"by_case": archive}, s_archive.sorted())

    n_series = 0
    for cid in sorted(cases):
        pub = published.get(cid, {})
        fam, title, tier, oracle, instrument = cases[cid]
        rec = pub.get("record") or {}
        light, heavy = split_series(rec, "")
        page = {
            "case": cid, "family": fam, "tier": tier, "title": title,
            "oracle_text": oracle, "oracle_is_sealed": True,
            "instrument": instrument,
            "verdict": pub.get("verdict"), "verdict_file": pub.get("file"),
            "claims": sorted(by_case.get(cid, [])),
            "citation_restrictions": [r for r in policy.get("restrictions", [])
                                      if cid in r.get("cases", [])],
            "archive": archive.get(cid, []),
            "record": light,
            "series_available": sorted(heavy),
        }
        # This case's OWN sources, not the build's. The verdict file and the archives are named per
        # case; the register, triage and citation policy are shared and are read for every page.
        case_sources = s_register.sorted() + s_claims.sorted() + s_policy.sorted()
        for name in ([pub["file"]] if pub.get("file") else []) + pub.get("_no_verdict_files", []):
            case_sources.append(str((PHASE1 / name).relative_to(ROOT)))
        for a in archive.get(cid, []):
            case_sources.append(str((ARCHIVE / a["file"]).relative_to(ROOT)))
        put(f"cases/{cid}.json", page, case_sources)
        if heavy:
            put(f"series/{cid}.json", {"case": cid, "series": heavy}, case_sources)
            n_series += 1

    missing_prov = sorted(set(outputs) - set(provenance))
    if missing_prov:
        die(f"emitted without provenance: {missing_prov}")

    # Recorded BEFORE the payload is serialised, so the manifest documents its own provenance too.
    # `emit` overwrites the entry with the same value; the point is that the dict inside the file is
    # total over the payload, so `gate_payload.py` never meets a file with no provenance at all and
    # has no reason to grow a special case for one.
    provenance["MANIFEST.json"] = sorted(inputs)
    put("MANIFEST.json", {
        "build_stamp": stamp, "tool": "platform/build/build_site_data.py",
        "n_inputs": len(inputs), "n_outputs": len(outputs) + 1,
        "inputs_sha256": inputs, "outputs_sha256": outputs,
        "provenance": provenance,
        "note": "outputs_sha256 excludes MANIFEST.json itself; provenance does not. Every input "
                "hash is of the bytes "
                "this build actually read, so a reader can prove which tree the payload came from. "
                "provenance maps each emitted file to the repo-relative sources it derives from; "
                "platform/build/gate_payload.py uses it to inherit a source's reviewed redaction "
                "exception instead of granting the payload a waiver of its own.",
    }, sorted(inputs))

    # The absolute path, not a repo-relative one: the output root is outside ROOT by design, and a
    # reader has to be able to see WHERE the published bytes were written.
    print(f"built {len(outputs)} file(s) into {out_root} at stamp {stamp}")
    print(f"  register {len(cases)} cases, seal live | verdicts "
          f"{', '.join(f'{k} {v}' for k, v in mix.items())}")
    print("  denominators " + " | ".join(
        f"{k} {v['n']}" for k, v in denominators.items()))
    print(f"  {len(findings)} findings, {registers['n_items']} register items, "
          f"{len(policy.get('restrictions', []))} citation restrictions, "
          f"{len(figures['present'])} figures present, missing {figures['missing'] or 'none'}")
    print(f"  {n_series} case(s) needed a series split at >= {SERIES_BYTES} bytes")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        print(f"BUILD-FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
