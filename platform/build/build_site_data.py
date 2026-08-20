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
from datetime import date, datetime, timezone
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
        out.append({"file": f.name, "source": str(f.relative_to(ROOT)), "title": title,
                    "provenance": prov,
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


DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def derive_method(published: dict, archive: dict, cases: dict) -> dict:
    """Derived structure of the adjudication itself: kinds, guards, and who is replicated.

    Every number the method walkthrough states is computed here rather than written in the page. The
    replication counts are the load-bearing ones: a case is replicated when its evidence names two
    DISTINCT calendar days, and that is derived from the archive labels rather than from anybody's
    statement that a replication happened. The 2026-08-19 incident was exactly a process claim with no
    artifact behind it, so the only claim this platform can make about replication is one the build
    recomputes from the files.
    """
    kinds: dict[str, int] = {}
    guards: dict[str, int] = {}
    caveats = {"what_true_does_not_prove": 0, "what_false_does_not_prove": 0}
    verdict_of: dict[str, str] = {}
    for cid, pub in published.items():
        rec = pub.get("record") or {}
        adj = rec.get("record") or {}
        kind = adj.get("kind") or rec.get("kind") or "(none recorded)"
        kinds[kind] = kinds.get(kind, 0) + 1
        # `guards` is a name -> bool mapping in most cases, but not in all: a few records carry a list
        # instead. Iterating blindly counted a dict as a key and crashed, which is the better failure —
        # a `str()` around it would have produced a guard named "{'test': ...}" appearing once, i.e. a
        # census of guards that silently disagreed with the case pages.
        gs = rec.get("guards")
        if isinstance(gs, dict):
            for name in gs:
                guards[name] = guards.get(name, 0) + 1
        elif isinstance(gs, list):
            for entry in gs:
                name = entry.get("name") if isinstance(entry, dict) else entry
                if isinstance(name, str):
                    guards[name] = guards.get(name, 0) + 1
                else:
                    guards["(guard recorded without a name)"] = guards.get(
                        "(guard recorded without a name)", 0) + 1
        for key in caveats:
            if str(rec.get(key) or "").strip():
                caveats[key] += 1
        if pub.get("verdict"):
            verdict_of[cid] = pub["verdict"]

    # A caveat is only owed where the verdict has a direction to over-read.
    owed_true = sorted(c for c, v in verdict_of.items() if v == "TRUE")
    owed_false = sorted(c for c, v in verdict_of.items() if v == "FALSE")
    have_true = sorted(c for c in owed_true
                       if str((published[c].get("record") or {}).get("what_true_does_not_prove") or "").strip())
    have_false = sorted(c for c in owed_false
                        if str((published[c].get("record") or {}).get("what_false_does_not_prove") or "").strip())

    days_by_case: dict[str, list[str]] = {}
    disagreeing: list[dict] = []
    for cid in sorted(cases):
        labels = [a["label"] for a in archive.get(cid, [])]
        days = sorted({m.group(1) for lab in labels for m in [DATE_RE.search(lab)] if m})
        days_by_case[cid] = days
        live = verdict_of.get(cid)
        for a in archive.get(cid, []):
            if live and a.get("verdict") and a["verdict"] != live:
                disagreeing.append({"case": cid, "label": a["label"],
                                    "archived_verdict": a["verdict"], "live_verdict": live})

    # "Two distinct days" counts the archive's days plus the live file's occasion. An archive with one
    # day is one prior occasion, which with the live file makes two — but only if the live run is not
    # itself that day. The build cannot see the live run's date from the label set alone, so this
    # reports the archive's own distinct days and leaves the stronger assertion to
    # check_site_invariants.py, which reads the evidence timestamps. Reporting the weaker number here
    # is deliberate: an over-claimed replication count is the exact defect this file guards against.
    return {
        "kinds": dict(sorted(kinds.items())),
        "guard_names": dict(sorted(guards.items(), key=lambda kv: (-kv[1], kv[0]))),
        "caveats": {
            "cases_with_what_true_does_not_prove": len(have_true),
            "true_verdicts": len(owed_true),
            "true_verdicts_without_the_caveat": sorted(set(owed_true) - set(have_true)),
            "cases_with_what_false_does_not_prove": len(have_false),
            "false_verdicts": len(owed_false),
            "false_verdicts_without_the_caveat": sorted(set(owed_false) - set(have_false)),
            "why_this_is_counted": "The case page renders 'what this verdict does not prove' for every "
                                   "case and says so explicitly when the record carries no such "
                                   "statement. Counting it here makes the gap a number rather than "
                                   "something a reader would have to notice one case at a time.",
        },
        "archive_days_by_case": {c: d for c, d in days_by_case.items() if d},
        "n_cases_with_an_archive": sum(1 for d in days_by_case.values() if d),
        "n_cases_with_two_distinct_archive_days": sum(1 for d in days_by_case.values() if len(d) >= 2),
        "archives_disagreeing_with_the_live_verdict": disagreeing,
        "note": "Derived from the verdict files and the archive at build time. No count here is stored "
                "anywhere; each is recomputed, and a page that wants one asks this file for it.",
    }


def _yaml_no_duplicate_keys(text: str, rel: str) -> dict:
    """Parse YAML, refusing a mapping that defines the same key twice.

    PyYAML's safe_load accepts a duplicate key and silently keeps the last one. In an authored
    governance file that is the worst possible failure mode: two `schedulable:` lines under one
    family read as valid, and the one a human edited may be the one that is discarded. So the loader
    is told to fail instead. This is the same defect class as a config parser accepting a duplicate
    key that the service it configures rejects.
    """
    try:
        import yaml  # noqa: PLC0415 - only this derivation needs it
    except ImportError:  # pragma: no cover - depends on the interpreter, not on the tree
        die(f"{rel} needs PyYAML and this interpreter has none. Run the build under .venv-oracle or "
            f"the system interpreter; do NOT add a fallback parser, because a second YAML reader is "
            f"a second grammar for an authored governance file.")

    class NoDuplicates(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        seen: set = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=True)
            if key in seen:
                die(f"{rel} defines the key {key!r} twice in one mapping (line "
                    f"{key_node.start_mark.line + 1}). PyYAML would keep the last one silently.")
            seen.add(key)
        return loader.construct_mapping(node, deep=True)

    NoDuplicates.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        loaded = yaml.load(text, Loader=NoDuplicates)  # noqa: S506 - NoDuplicates derives SafeLoader
    except yaml.YAMLError as e:
        die(f"{rel} is not readable YAML: {e}")
    if not isinstance(loaded, dict):
        die(f"{rel} must be a mapping at the top level, not {type(loaded).__name__}")
    return loaded


def derive_families(inputs: dict[str, str], cases: dict) -> dict:
    """The authored per-family operational classification, checked against the sealed register.

    Checked in BOTH directions, deliberately. A missing entry is the obvious error; the dangerous one
    is the opposite — a family added to the register later would arrive with no classification, and
    every consumer that reads a flag with `.get(...)` would then treat "unclassified" as
    "unrestricted". Nothing may be schedulable, or non-network-position-sensitive, by omission.
    """
    rel = "platform/curation/families.yaml"
    data = _yaml_no_duplicate_keys(read_text(ROOT / "platform" / "curation" / "families.yaml", inputs),
                                   rel)
    fams = data.get("families")
    if not isinstance(fams, dict) or not fams:
        die(f"{rel} carries no `families` mapping")

    in_register = sorted({v[0] for v in cases.values()})
    authored = sorted(fams)
    missing = [f for f in in_register if f not in fams]
    extra = [f for f in authored if f not in in_register]
    if missing:
        die(f"{rel} does not classify {missing}, which the sealed register uses. An unclassified "
            f"family is schedulable by omission, which is the failure this check exists to prevent.")
    if extra:
        die(f"{rel} classifies {extra}, which no registered case belongs to. A stale entry is a rule "
            f"nothing enforces, and it makes the file look wider in coverage than it is.")

    vocab = data.get("vocabularies") or {}
    required = ("label", "cost", "runner", "mutates", "schedulable", "network_position_sensitive",
                "cadence_days", "why_cadence")
    for fam in in_register:
        entry = fams[fam]
        if not isinstance(entry, dict):
            die(f"{rel}: family {fam} is not a mapping")
        for key in required:
            if key not in entry:
                die(f"{rel}: family {fam} has no `{key}`. Every field this platform branches on must "
                    f"be stated, because a default would be an unauthored policy.")
        for key in ("cost", "runner", "mutates"):
            allowed = vocab.get(key)
            if isinstance(allowed, list) and entry[key] not in allowed:
                die(f"{rel}: family {fam} has {key}={entry[key]!r}, outside the declared "
                    f"vocabulary {allowed}")
        # The cadence pairing, checked in both directions. Each half alone has a specific silent
        # failure: a schedulable family with no cadence can never be reported STALE, so a schedule that
        # quietly stopped looks identical to one that is current; a non-schedulable family WITH a
        # cadence eventually badges itself stale, and its only remedy is a run somebody forbade — for
        # F6 a run that would also invalidate the comparison it appears to refresh.
        cadence = entry["cadence_days"]
        if not str(entry.get("why_cadence", "")).strip():
            die(f"{rel}: family {fam} sets cadence_days={cadence!r} and gives no reason. The pipeline "
                f"view renders this text beside the staleness state; the number alone is an unsourced "
                f"deadline.")
        if cadence is not None and not (isinstance(cadence, int) and not isinstance(cadence, bool)
                                        and cadence > 0):
            die(f"{rel}: family {fam} has cadence_days={cadence!r}, which is neither null nor a "
                f"positive whole number of days.")
        if entry["schedulable"] is True and cadence is None and entry["cost"] != "calendar_gated":
            die(f"{rel}: family {fam} is schedulable and has no cadence, so nothing can ever call it "
                f"stale. A schedule that silently stops would then be indistinguishable from one that "
                f"is up to date. Give it a cadence, or say it is calendar-gated and why.")
        if entry["schedulable"] is False and cadence is not None:
            die(f"{rel}: family {fam} is not schedulable but carries cadence_days={cadence}. A "
                f"staleness badge whose only remedy is a prohibited run is pressure toward that run.")
        if entry["cost"] == "calendar_gated" and cadence is not None:
            die(f"{rel}: family {fam} is calendar-gated and also carries a cadence. Its meaningful "
                f"dates come from its own comparison window; a cadence here is a second calendar.")
        if entry["schedulable"] is False and not str(entry.get("why_not_schedulable", "")).strip():
            die(f"{rel}: family {fam} is not schedulable and gives no reason. A prohibition with no "
                f"stated reason is the first one somebody removes.")
        if entry["network_position_sensitive"] is True:
            for key in ("why", "replication_requirement"):
                if not str(entry.get(key, "")).strip():
                    die(f"{rel}: family {fam} is network-position sensitive and has no `{key}`. The "
                        f"case page renders this text as a banner; an empty banner is no banner.")

    n_cases = {fam: sum(1 for v in cases.values() if v[0] == fam) for fam in in_register}
    # Repo-relative, because `check_site_invariants` proves the authored prose in here was not written
    # by this build by finding it verbatim in the file the document names. A name with no directory
    # would make that proof a search, and a search can match the wrong file.
    return {"schema": data.get("schema"), "vocabularies": vocab, "source": rel,
            "families": {f: {**fams[f], "n_cases": n_cases[f]} for f in in_register},
            "note": "Authored in platform/curation/families.yaml and validated against the sealed "
                    "register in both directions: a registered family absent here, or an entry here "
                    "for no registered family, fails the build. `cost` is a class, never a figure — "
                    "cost_model.yaml is the only source of prices."}


# ------------------------------------------------------------------ when did a measurement happen
#
# There is no `run_day` field. Nothing in `results/phase1/` records, in one agreed place, the calendar
# day on which the measurement was taken — the dates that exist are scattered over two dozen key names
# at every depth, and some of them are not observations at all (an IAM policy `Version`, a credential
# `expiry`, a `due_on` deadline). This is a real gap in the study and it is on the deficiency register;
# what follows is how the pipeline view is honest about it rather than a workaround that hides it.
#
# Two tables, and the build DIES on anything in neither. A pure allow-list would be the usual mistake:
# a name list cannot notice a new name (`feedback_scope_as_namelist`), so a producer that later writes
# its run day under a key nobody added would leave its family looking permanently unobserved. A pure
# deny-list has the opposite failure and it is worse — an `expiry` counted as an observation makes a
# family look FRESHER than it is, and a false "current" is the failure this whole platform exists to
# prevent. So every date-carrying key must be classified as one or the other, and an unclassified one
# fails the build with its path in the message.
#
# The direction of the residual error is chosen deliberately: where a day cannot be established the
# family reads NOT OBSERVED, never "within cadence". Under-claiming freshness is recoverable by
# reading the case; over-claiming it is what tells somebody a control was checked last week.
OBSERVATION_DAY_KEYS = {
    "t": "per-span and per-trial observation timestamp written by the instrument as it measured",
    "timestamp": "same, under the spelling the log-derived producers use",
    "t_utc": "explicitly-UTC observation timestamp",
    "t0_iso": "start of the measured interval, written by the producer at the time it ran",
    "t1_iso": "end of the measured interval",
    "started_utc": "producer start",
    "ended_utc": "producer end",
    "collected_at": "the moment the read was collected",
    "observed_on": "the day the offline observation was made",
    "observation_day": "explicit UTC day of the observation",
    "reread_utc_day": "the day a re-read was performed — a second occasion, which is the point",
    "on": "the day a re-derivation was performed",
    "latest": "the most recent record the read returned; bounded above by the read itself",
    "window_start": "bound of the interval the instrument itself was running over",
    "window_end": "same",
    "archived_StartTime": "start time of the archived job the record is a read of",
    "archived_EndTime": "end time of the same",
}
NOT_AN_OBSERVATION_KEYS = {
    "Version": "an IAM policy language version (2012-10-17). Not a date in this repository's sense.",
    "expiry": "when a credential or a state file STOPS being valid — in the future, and counting it "
              "would make a case look measured on a day nobody measured anything.",
    "due_on": "a deadline this study set itself. A deadline is not an observation.",
    "since": "the lower bound of a QUERY window, chosen by the producer. It says which period the "
             "data covers, not when the reading was taken.",
    "start": "same: a query-window bound.",
    "end": "same. Excluding it costs a little precision on a few cases and avoids reporting the far "
           "edge of a requested window as the day somebody looked.",
    "baseline_interval_opens_after": "a condition on when a FUTURE comparison becomes valid.",
    "window_opens_after": "same.",
}


def _observation_days(obj, path: str, days: set[str], unclassified: dict[str, str]) -> None:
    """Collect every observation day in a record; record every date-carrying key it cannot classify."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if isinstance(v, str) and DATE_RE.match(v.strip()):
                if k in OBSERVATION_DAY_KEYS:
                    days.add(DATE_RE.match(v.strip()).group(1))
                elif k not in NOT_AN_OBSERVATION_KEYS:
                    unclassified.setdefault(str(k), here)
            else:
                _observation_days(v, here, days, unclassified)
    elif isinstance(obj, list):
        # Bounded: a 20k-element span array carries one key name, and reading 200 of them establishes
        # the same key set as reading all of them. The days themselves come from the whole record via
        # min/max over what is read, and a scan that walked every element of F3-10 would add minutes
        # to every build to refine a calendar day it already has.
        for i, v in enumerate(obj[:200]):
            _observation_days(v, f"{path}[{i}]", days, unclassified)


def derive_pipeline(families: dict, cases: dict, published: dict, archive: dict, stamp: str) -> dict:
    """Per-family operational state: when it was last observed, whether that is inside its cadence,
    and which cases still owe a second day.

    The states are deliberately five, not two. `NOT OBSERVED` and `UNKNOWN CADENCE` are first-class,
    because the alternative is that a family with no derivable day falls into the same bucket as one
    that was measured yesterday. `REQUIRES A LOCAL RUN` exists so F6 never renders as stale — a
    staleness badge there is pressure toward a cloud re-run from the wrong network position, which
    would look like a replication and would not be one.

    There is no progress bar and no percentage. Nothing here is a fraction of a job: a family is a set
    of cases, each of which either has an established day or does not.
    """
    build_day = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).date()
    unclassified: dict[str, str] = {}
    per_case: dict[str, dict] = {}
    for cid in sorted(cases):
        pub = published.get(cid, {})
        days: set[str] = set()
        _observation_days(pub.get("record") or {}, cid, days, unclassified)
        # Archive labels carry a day each, and an archived file IS a prior occasion — the strongest
        # evidence of a distinct run day this build has, because it is a separate artifact.
        archive_days = {m.group(1) for a in archive.get(cid, [])
                        for m in [DATE_RE.search(a["label"])] if m}
        live = pub.get("verdict")
        disagreeing = [a for a in archive.get(cid, [])
                       if live and a.get("verdict") and a["verdict"] != live]
        all_days = sorted(days | archive_days)
        # A day after the as-of day is not an error: `--stamp` is caller-supplied and a deliberately
        # back-dated build is legitimate (the test suite does exactly that). It is recorded, and the
        # age is clamped at 0, so the only thing a future day can do is make a family read as recently
        # observed — never as negatively aged, and never as stale-by-arithmetic-accident.
        ahead = [d for d in all_days if d > build_day.isoformat()]
        per_case[cid] = {
            "case": cid, "family": cases[cid][0], "has_verdict": bool(live),
            "observation_days": all_days,
            "days_from_the_record": sorted(days),
            "days_from_the_archive": sorted(archive_days),
            "n_distinct_days": len(all_days),
            "observation_days_after_the_as_of_day": ahead,
            # REPLICATION IS COUNTED FROM THE ARCHIVE ALONE, AND THAT IS THE WHOLE POINT.
            #
            # Two timestamps inside one evidence file are not two occasions — a run that starts at
            # 23:58 and ends at 00:03 carries two calendar days and is one run. Counting the record's
            # days here would have published a replication claim for a single producer invocation,
            # which is the 2026-08-19 incident's exact shape: a process claim with no artifact behind
            # it. An archived `day1_*` file is a separate artifact, so it is the only thing that
            # establishes a prior occasion. The days from the record are kept above, where they answer
            # a different question (when was this last observed), and are not consulted here.
            "n_archived_prior_days": len(archive_days),
            "replication": ("disagreeing" if disagreeing else
                            "two_or_more_archived_days_agreeing" if len(archive_days) >= 2 else
                            "one_archived_prior_day" if archive_days else "no_archived_prior_day"),
            "disagreements": disagreeing,
        }
    if unclassified:
        die(f"date-carrying key(s) {sorted(unclassified)} appear in the verdict records "
            f"(first at {sorted(unclassified.values())[0]}) and are in neither "
            f"OBSERVATION_DAY_KEYS nor NOT_AN_OBSERVATION_KEYS. Classify each one: left unclassified "
            f"it is silently ignored, and a family whose only run-day evidence is under that key would "
            f"read as never observed.")

    rows = {}
    for fam, entry in families["families"].items():
        mine = [per_case[c] for c in sorted(per_case) if per_case[c]["family"] == fam]
        days = sorted({d for c in mine for d in c["observation_days"]})
        last = days[-1] if days else None
        age = max(0, (build_day - date.fromisoformat(last)).days) if last else None
        cadence = entry["cadence_days"]
        if entry["network_position_sensitive"] and entry["schedulable"] is False:
            state = "REQUIRES A LOCAL RUN"
        elif entry["schedulable"] is False:
            state = "HUMAN DECISION REQUIRED"
        elif cadence is None:
            state = "CALENDAR GATED"
        elif last is None:
            state = "NOT OBSERVED"
        elif age > cadence:
            state = "STALE"
        else:
            state = "WITHIN CADENCE"
        no_day = [c["case"] for c in mine if not c["observation_days"]]
        rows[fam] = {
            "family": fam, "label": entry["label"], "state": state,
            "schedulable": entry["schedulable"], "cadence_days": cadence,
            "why_cadence": entry["why_cadence"],
            "network_position_sensitive": entry["network_position_sensitive"],
            # `ui_state_when_old` is a vocabulary TOKEN for a component to key on, so the sentences a
            # reader needs are carried too. A page that had only the token would render
            # "requires_local_run" as its safety banner, which names the state and explains none of it —
            # and for F6 the explanation is the whole point: an in-cloud re-run changes the network
            # position, so it is a new measurement rather than a replication.
            "ui_state_when_old": entry.get("ui_state_when_old"),
            "why_not_schedulable": entry.get("why_not_schedulable"),
            "replication_requirement": entry.get("replication_requirement"),
            # Where the three authored sentences above came from, repo-relative. The publish gate proves
            # this build copied rather than composed any replication prose it emits by finding it
            # verbatim in the file the enclosing object names, so carrying the text without carrying its
            # origin fails the publish — which is the correct order of events.
            "source": families.get("source"),
            "last_observed_utc_day": last,
            "first_observed_utc_day": days[0] if days else None,
            "days_since_last_observation": age,
            "statement": (f"{fam} has not been observed in {age} day(s); its cadence is "
                          f"{cadence} day(s)." if age is not None and cadence is not None else
                          f"{fam} has not been observed in {age} day(s)." if age is not None else
                          f"No observation day can be established for any {fam} case from the "
                          f"published artifacts, so this platform cannot say when {fam} was last "
                          f"measured."),
            "n_cases": len(mine),
            "n_with_verdict": sum(1 for c in mine if c["has_verdict"]),
            "n_with_no_observed_day": len(no_day),
            "cases_with_no_observed_day": no_day,
            "replication": {k: sum(1 for c in mine if c["replication"] == k)
                            for k in ("no_archived_prior_day", "one_archived_prior_day",
                                      "two_or_more_archived_days_agreeing", "disagreeing")},
            # The four buckets above are mutually exclusive and `disagreeing` wins, which would
            # otherwise hide the fact it is describing: today ALL THREE cases with two archived days
            # are ones whose archive disagrees with the live verdict, so the agreeing bucket reads 0.
            # Left at that, "0 cases measured on two days" would be the opposite of what happened.
            "n_with_two_or_more_archived_days": sum(1 for c in mine
                                                    if c["n_archived_prior_days"] >= 2),
            # Two lists, deliberately, because they are two different facts and one of them is much
            # larger. "This case has a verdict and no prior occasion is archived" is a replication
            # backlog. "No observation day can be established for this case at all" is a metadata gap
            # in the study — 53 of the 93 cases — and a single list holding both would carry the first
            # label while mostly containing the second (`feedback_label_must_match_computation`).
            "cases_owing_a_second_day": [c["case"] for c in mine
                                         if c["has_verdict"] and c["n_archived_prior_days"] == 0],
            "cases_whose_observation_day_is_unknown": [
                c["case"] for c in mine if c["has_verdict"] and not c["observation_days"]],
            "cases_in_disagreement": [c["case"] for c in mine if c["replication"] == "disagreeing"],
        }

    return {
        "schema": "grx-pipeline/1",
        "as_of_utc_day": build_day.isoformat(),
        "as_of_note": "The build's own stamp. Nothing here reads a clock at render time: a page that "
                      "aged its own numbers in the browser would drift away from the payload it was "
                      "published with.",
        "states": ["WITHIN CADENCE", "STALE", "NOT OBSERVED", "CALENDAR GATED",
                   "HUMAN DECISION REQUIRED", "REQUIRES A LOCAL RUN"],
        "families": rows,
        "cases": per_case,
        "as_of_precedes_some_observations": sorted(
            c["case"] for c in per_case.values() if c["observation_days_after_the_as_of_day"]),
        "totals": {
            "n_cases": len(per_case),
            "n_with_no_observed_day": sum(1 for c in per_case.values()
                                          if not c["observation_days"]),
            "why_replication_is_counted_from_the_archive_only":
                "An archived day-1 file is a separate artifact and therefore a separate occasion. Two "
                "timestamps inside one evidence file are one run that crossed midnight. Only the first "
                "supports the sentence 'this was measured on two days'.",
            "n_one_archived_prior_day": sum(1 for c in per_case.values()
                                            if c["replication"] == "one_archived_prior_day"),
            "n_two_or_more_archived_days_agreeing": sum(
                1 for c in per_case.values()
                if c["replication"] == "two_or_more_archived_days_agreeing"),
            "n_with_two_or_more_archived_days": sum(1 for c in per_case.values()
                                                    if c["n_archived_prior_days"] >= 2),
            "n_no_archived_prior_day": sum(1 for c in per_case.values()
                                           if c["replication"] == "no_archived_prior_day"),
            "n_disagreeing": sum(1 for c in per_case.values() if c["replication"] == "disagreeing"),
            "families_stale": sorted(f for f, r in rows.items() if r["state"] == "STALE"),
            "families_not_observed": sorted(f for f, r in rows.items()
                                            if r["state"] == "NOT OBSERVED"),
        },
        "note": "Observation days are derived from the verdict records and the archive at build time, "
                "under a classification of every date-carrying key (see OBSERVATION_DAY_KEYS). The "
                "study has no single run-day field — a registered deficiency — so a case whose day "
                "cannot be established reads NOT OBSERVED and never 'current'. There is no progress "
                "bar and no percentage here: a family is a set of cases, not a job with a fraction "
                "done.",
    }


def _plain(obj, where: str):
    """YAML types → JSON types, with anything unexpected fatal rather than str()-ed.

    `derived_on: 2026-08-20` in an authored file loads as a `datetime.date`, which `json.dumps`
    refuses. A blanket `default=str` would fix that and would also quietly stringify a type nobody
    intended to publish; this converts the two date shapes and dies on the rest, so an authored value
    of a new kind is a build failure and not a surprise on the page.
    """
    if isinstance(obj, dict):
        return {str(k): _plain(v, f"{where}.{k}") for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v, f"{where}[{i}]") for i, v in enumerate(obj)]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    die(f"{where} loaded as {type(obj).__name__}, which has no agreed JSON rendering. Add one here "
        f"deliberately rather than letting the emitter guess.")


def derive_controls(inputs: dict[str, str], cases: dict, published: dict,
                    restricted: dict[str, list[str]]) -> dict:
    """The authored control→case mapping, with every annotation derived here rather than authored.

    The split is the same one `families.yaml` uses and it is the whole point of the file. Which
    controls exist, which cases measured them, and what a reader should do about it are **judgments**,
    so they are authored in `platform/curation/controls.yaml`. Every verdict, restriction badge and
    coverage count on this page is **derived** — from the sealed register, from `results/phase1/`, and
    from `results/CITATION-POLICY.md`. Author a verdict beside a control and the file becomes a second
    source of truth that can disagree with the census, which is the one thing this platform may not
    ship.

    This function deliberately does NOT re-implement the citation rules. `platform/build/
    check_controls.py` owns them and runs in the publish gate with `--verify-field-paths`; duplicating
    them here would create two rule sets to keep in step, and the weaker one would win by being the one
    that ran. What it does enforce is the invariant this emitter itself could violate: a case named in
    the authored file that the register does not contain, in which case the page would render a badge
    for a case nobody can look up.
    """
    rel = "platform/curation/controls.yaml"
    data = _yaml_no_duplicate_keys(read_text(ROOT / "platform" / "curation" / "controls.yaml", inputs),
                                   rel)
    controls = data.get("controls")
    if not isinstance(controls, list) or not controls:
        die(f"{rel} carries no `controls` list. A control page derived from nothing renders as a "
            f"dashboard with no controls, which reads as 'nothing to check'.")

    def annotate(case_id: str) -> dict:
        if case_id not in cases:
            die(f"{rel} names {case_id}, which is not in the sealed register. Every badge on the "
                f"control page has to resolve to a case a reader can open.")
        pub = published.get(case_id) or {}
        return {"case": case_id, "verdict": pub.get("verdict"),
                "has_verdict": bool(pub.get("verdict")),
                "restrictions": restricted.get(case_id, []),
                "family": cases[case_id][0], "title": cases[case_id][1]}

    rows = []
    for control in controls:
        if not isinstance(control, dict) or not control.get("id"):
            die(f"{rel} holds a control with no `id`; an unidentified control sits outside every "
                f"count on this page (`feedback_unnumbered_is_uncounted`)")
        findings = []
        for f in control.get("findings") or []:
            findings.append({
                "when": f.get("when"), "status": f.get("status"),
                "says": f.get("says"), "consequence": f.get("consequence"),
                "scope_note": f.get("scope_note"), "why_not_measured": f.get("why_not_measured"),
                "cites": [annotate(c) for c in (f.get("cites") or [])],
            })
        measured_by = [{**annotate(m["case"]), "why": m.get("why")}
                       for m in (control.get("measured_by") or [])]
        rows.append({
            "id": control["id"], "label": control.get("label"),
            "question": control.get("question"),
            "detect": control.get("detect"),
            "measured": control.get("measured"),
            "why_not_measured": control.get("why_not_measured"),
            "measured_by": measured_by,
            "findings": findings,
            "statuses": sorted({f["status"] for f in findings if f.get("status")}),
            "n_cases": len({c["case"] for c in measured_by}
                           | {c["case"] for f in findings for c in f["cites"]}),
        })

    by_status: dict[str, int] = {}
    for row in rows:
        for status in row["statuses"]:
            by_status[status] = by_status.get(status, 0) + 1

    return {
        "schema": data.get("schema"),
        "field_paths": _plain(data.get("field_paths"), f"{rel}:field_paths"),
        "vocabularies": _plain(data.get("vocabularies"), f"{rel}:vocabularies"),
        "unverifiable_paths": _plain(data.get("unverifiable_paths"), f"{rel}:unverifiable_paths"),
        "controls": _plain(rows, f"{rel}:controls"),
        "n_controls": len(rows),
        "controls_by_status": by_status,
        "note": "Topology authored in platform/curation/controls.yaml; every verdict, restriction and "
                "coverage count on this page derived at build time from the sealed register, "
                "results/phase1/ and results/CITATION-POLICY.md. `controls_by_status` counts controls "
                "carrying at least one finding of each status and is NOT a ratio: a control can carry "
                "two statuses at once, and no denominator over these counts means anything.",
    }


# ------------------------------------------------------------------------------- the two diagrams
#
# THE ONE THING A DIAGRAM MUST NOT DO
#
# An architecture picture is the most quotable artifact a project produces: it is what gets pasted
# into somebody else's deck, and it is read as authoritative long after the text beside it is
# forgotten. So the two things it asserts — that these are the components, and that this is what was
# established about each — must come from different places. The components are a judgment and are
# authored in `platform/curation/architecture.yaml`. Every status, badge, chip and count is derived
# here, from the sealed register, `results/phase1/` and `results/CITATION-POLICY.md`. A colour typed
# beside a box would be a second source of truth for a verdict, free to disagree with the census, and
# it is the diagram's version that a reader would remember.
#
# WHY THE COORDINATES ARE DERIVED TOO
#
# Hand-placed boxes are the same defect in a different coat. A hand-drawn layout is correct only for
# the topology it was drawn against; add one box and the arrows silently start crossing, and a reader
# misreads a crossing as a connection (`feedback_diagram_layout_rules`). So the layout below is
# computed from the authored edges, and `platform/build/tests/test_architecture_layout.py` asserts the
# number of crossings is exactly ZERO rather than under some tolerance — an equality assertion, which
# is available here only because the geometry is constrained enough to make it provable:
#
#   * the spine is a topological order of the non-property boxes, one per row, top to bottom;
#   * a `kind: property` box has exactly one incoming edge and no outgoing edges (the gate enforces
#     that), so it can be placed in its parent's own row, to the right, and its edge routed in a lane
#     above that row — a band no spine edge and no other row's lane occupies;
#   * an edge that skips rows is routed in a left-hand gutter, in a lane chosen so that nested spans
#     nest and the outer span takes the outer lane.
#
# Every offset below is monotone in the lane index for exactly that reason: a stub that reached its
# lane by crossing an inner lane's segment would be the one crossing the whole construction exists to
# rule out. The test recomputes the crossings geometrically from the emitted polylines, so if a future
# edit produces a pair of spans that properly overlap — the one case a single gutter cannot draw
# cleanly — the build fails and says so, rather than shipping a picture with a lie in it.

BOX_W, BOX_H = 200, 96
ROW_GAP = 52                     # > the deepest property lane offset (10 + 11*(N-1)), so a lane never
COL_PITCH = 274                  #   enters the row above; > the deepest riser (208 + 9*(N-1))
ROW_PITCH = BOX_H + ROW_GAP

# Restrictions that disqualify a case from COLOURING a box. Deliberately the same partition
# `check_controls.py` applies to a control's findings (its RESTRICTION_NEVER | RESTRICTION_CONTEXT_ONLY),
# and `check_architecture.py` asserts the two sets are equal rather than trusting this comment — two
# copies of a citation rule is two answers, and the weaker one wins by being the one that ran.
ARCH_NON_COLOURING = {"NEVER_CITE", "NOT_A_VERDICT", "UNMEASURED", "UNTESTABLE",
                      "MECHANISM_ONLY", "NO_CLAIM_MAPPED"}

# What each status means, rendered beside the box. The ORDER of the rules in `box_status` is the whole
# claim: a FALSE outranks a TRUE, so a component with four confirmations and one finding reads as
# contested. Colouring it green would be defensible arithmetic and would bury the finding, which is
# the only thing on the diagram a reader cannot afford to miss.
ARCH_STATUS_LABEL = {
    "contested": "measured, and the guidance did not hold somewhere on this component",
    "validated_in_part": "measured, and the documented behaviour held for at least one claim",
    "not_established": "measured, and nothing was established either way",
    "context_only": "cases exist but none of them is a citable verdict about this component",
    "not_measured": "this study never examined this component",
}


def box_status(annotated: list[dict]) -> tuple[str, str]:
    """The status of a box, as a function of its cases' verdicts and citation restrictions only.

    Shared with `check_architecture.py` by import, so the gate and the builder cannot drift. Returns
    the status and the sentence explaining it, because a colour with no stated derivation is a colour
    a reader has to take on trust.
    """
    if not annotated:
        return "not_measured", ("No case in the register is about this component, so nothing is "
                                "claimed. An uncoloured box would read as 'nothing to worry about'; "
                                "what it means is that this study did not look.")
    colouring = [c for c in annotated
                 if c["verdict"] and not (set(c["restrictions"]) & ARCH_NON_COLOURING)]
    false_ = [c["case"] for c in colouring if c["verdict"] == "FALSE"]
    true_ = [c["case"] for c in colouring if c["verdict"] == "TRUE"]
    inconclusive = [c["case"] for c in colouring if c["verdict"] == "INCONCLUSIVE"]
    if false_:
        return "contested", (f"{len(false_)} citable FALSE verdict(s) — {', '.join(false_)} — so the "
                             f"documented behaviour was not observed somewhere on this component. A "
                             f"FALSE outranks the {len(true_)} TRUE verdict(s) here on purpose: a "
                             f"component with a finding is a component with a finding.")
    if true_:
        return "validated_in_part", (f"{len(true_)} citable TRUE verdict(s) — {', '.join(true_)} — and "
                                     f"no FALSE. 'In part' is not modesty: a box carries many claims "
                                     f"and a TRUE on one of them is not validation of the component.")
    if inconclusive:
        return "not_established", (f"Only INCONCLUSIVE verdicts ({', '.join(inconclusive)}). An "
                                   f"INCONCLUSIVE verdict is not evidence against a claim and it "
                                   f"licenses no amendment, so it may never colour a box as "
                                   f"validated.")
    return "context_only", ("Every case here either carries no verdict or carries a citation "
                            "restriction that makes it something other than a verdict about this "
                            "component. It is listed so the reader can see what was looked at, and "
                            "it colours nothing.")


def architecture_metrics(cases: dict, published: dict, restricted: dict, archive: dict,
                         by_case: dict, families: dict, controls: dict, figures: dict,
                         registers: dict) -> dict[str, int]:
    """The closed set of numbers a box may display, each computed here and nowhere else.

    A number typed into the authored file would be a second source for something the census already
    knows, and it would go stale silently — the failure mode a diagram is worst at showing. So a box
    names a metric and this table computes it; a name with no entry fails the build
    (`feedback_prose_is_not_verified`).
    """
    # The same day extraction `derive_method` uses, from the archive LABEL — not a second reading of
    # the same fact with its own regex, which is how two counts of one thing start to disagree.
    days = {c: {m.group(1) for a in v for m in [DATE_RE.search(a["label"])] if m}
            for c, v in archive.items()}
    return {
        "cases_registered": len(cases),
        "verdicts_published": sum(1 for p in published.values() if p.get("verdict")),
        "verdicts_false": sum(1 for p in published.values() if p.get("verdict") == "FALSE"),
        "cases_with_an_archive": sum(1 for v in archive.values() if v),
        "cases_with_two_distinct_archive_days": sum(1 for d in days.values() if len(d) >= 2),
        "cases_carrying_a_restriction": len(restricted),
        "claims_mapped": sum(1 for c in cases if by_case.get(c)),
        "families_total": len(families["families"]),
        "families_macbook_only": sum(1 for v in families["families"].values()
                                     if v["network_position_sensitive"]),
        "controls_declared": controls["n_controls"],
        "figures_published": len(figures["present"]),
        "register_items": registers["n_items"],
    }


def _spine_order(box_ids: list[str], edges: list[dict], rel: str, diagram: str) -> list[str]:
    """A topological order of the spine, tie-broken by the order the boxes were authored in.

    The tie-break is what makes the authored file's box order meaningful rather than decorative: two
    boxes that no edge orders are drawn in the order somebody wrote them, and the same file always
    produces the same picture. A cycle is fatal here as well as in the gate — the gate is what a
    reader is told about, but a builder that produced coordinates for a cyclic graph would emit a
    layout with no top, and the loudest available signal for that is refusing to emit one.
    """
    rank = {b: i for i, b in enumerate(box_ids)}
    indeg = {b: 0 for b in box_ids}
    out: dict[str, list[str]] = {b: [] for b in box_ids}
    for e in edges:
        if e["from"] in indeg and e["to"] in indeg:
            indeg[e["to"]] += 1
            out[e["from"]].append(e["to"])
    ready = sorted([b for b in box_ids if indeg[b] == 0], key=rank.get)
    order: list[str] = []
    while ready:
        b = ready.pop(0)
        order.append(b)
        for n in out[b]:
            indeg[n] -= 1
            if indeg[n] == 0:
                ready = sorted([*ready, n], key=rank.get)
    if len(order) != len(box_ids):
        die(f"{rel}: diagram {diagram} has a cycle among its non-property boxes "
            f"({sorted(set(box_ids) - set(order))}). A pipeline diagram asserts an ORDER — sealed "
            f"before measured, replicated before amended — and a cycle means the file no longer "
            f"states one.")
    return order


def _layout(diagram: dict, boxes: dict[str, dict], edges: list[dict], rel: str) -> dict:
    """Place every box and route every edge. See the band argument above the constants.

    Returns the viewBox; mutates `boxes` and `edges` with geometry. Nothing here reads a verdict: the
    picture's shape is a function of the topology alone, so a new verdict never moves a box, and a
    reader comparing two releases sees the annotation change and the structure stay put.
    """
    spine = [b for b in boxes if boxes[b]["kind"] != "property"]
    order = _spine_order(spine, [e for e in edges
                                 if boxes[e["from"]]["kind"] != "property"
                                 and boxes[e["to"]]["kind"] != "property"],
                         rel, diagram["id"])
    row = {b: i for i, b in enumerate(order)}

    # A property's parent is its single incoming edge's source; the gate proves there is exactly one,
    # so this lookup cannot be ambiguous. `sats[parent]` keeps authored order, which is what decides
    # which lane each one gets — and the lanes are monotone, so authored order is drawing order.
    sats: dict[str, list[str]] = {b: [] for b in order}
    for e in edges:
        if boxes[e["to"]]["kind"] == "property":
            sats.setdefault(e["from"], []).append(e["to"])

    for b in order:
        boxes[b].update(x=0, y=row[b] * ROW_PITCH, w=BOX_W, h=BOX_H, row=row[b], column=0)
    for parent, kids in sats.items():
        for k, kid in enumerate(kids):
            boxes[kid].update(x=(k + 1) * COL_PITCH, y=boxes[parent]["y"], w=BOX_W, h=BOX_H,
                              row=boxes[parent]["row"], column=k + 1)

    # Gutter lanes for row-skipping spine edges. Lane 1 is innermost; an edge takes the lowest lane
    # whose spans it neither overlaps nor touches, so nested spans nest outward. Sorting by span
    # ascending is what makes the outer lane the longer edge, which is the condition under which the
    # stubs cannot cross (a stub reaching an outer lane passes no inner lane's column).
    lanes: list[list[tuple[int, int]]] = []
    skips = sorted([e for e in edges if boxes[e["to"]]["kind"] != "property"
                    and abs(row[e["to"]] - row[e["from"]]) > 1],
                   key=lambda e: abs(row[e["to"]] - row[e["from"]]))
    lane_of: dict[int, int] = {}
    for e in skips:
        a, b = sorted((row[e["from"]], row[e["to"]]))
        for i, taken in enumerate(lanes):
            if all(b < c or d < a for c, d in taken):
                taken.append((a, b))
                lane_of[id(e)] = i + 1
                break
        else:
            lanes.append([(a, b)])
            lane_of[id(e)] = len(lanes)

    for e in edges:
        src, dst = boxes[e["from"]], boxes[e["to"]]
        if dst["kind"] == "property":
            kids = sats[e["from"]]
            n, k = len(kids), kids.index(e["to"])
            # Monotone in k, and every offset decreasing: the riser of a further-out property sits
            # closer to the box, its lane sits higher, and its exit from the parent sits higher. Any
            # one of the three reversed puts a stub across an inner lane.
            riser = src["x"] + BOX_W + 8 + 9 * (n - 1 - k)
            exit_y = src["y"] + 20 + 14 * (n - 1 - k)
            lane_y = src["y"] - 10 - 11 * k
            drop = dst["x"] + 40
            e["points"] = [[src["x"] + BOX_W, exit_y], [riser, exit_y], [riser, lane_y],
                           [drop, lane_y], [drop, dst["y"]]]
            e["route"], e["lane"] = "property", k + 1
        elif abs(dst["row"] - src["row"]) == 1:
            top, bottom = sorted((src, dst), key=lambda b: b["y"])
            e["points"] = [[BOX_W / 2, top["y"] + BOX_H], [BOX_W / 2, bottom["y"]]]
            e["route"], e["lane"] = "spine", 0
        else:
            lane = lane_of[id(e)]
            gx = -(30 * lane + 8)
            sy, dy = src["y"] + BOX_H / 2 - 6 * lane, dst["y"] + BOX_H / 2 - 6 * lane
            e["points"] = [[0, sy], [gx, sy], [gx, dy], [0, dy]]
            e["route"], e["lane"] = "gutter", lane

    xs = [b["x"] for b in boxes.values()] + [b["x"] + BOX_W for b in boxes.values()]
    ys = [b["y"] for b in boxes.values()] + [b["y"] + BOX_H for b in boxes.values()]
    for e in edges:
        xs += [p[0] for p in e["points"]]
        ys += [p[1] for p in e["points"]]
    pad = 24
    return {"min_x": min(xs) - pad, "min_y": min(ys) - pad,
            "width": max(xs) - min(xs) + 2 * pad, "height": max(ys) - min(ys) + 2 * pad}


def derive_architecture(inputs: dict[str, str], cases: dict, published: dict,
                        restricted: dict[str, list[str]], metrics: dict[str, int]) -> dict:
    """The authored topology of the two diagrams, with every annotation and coordinate derived here.

    The coverage claim is the arm worth reading twice. Placed cases plus the authored `unplaced_cases`
    must equal the register EXACTLY, both directions, because a diagram is a claim about coverage
    whether or not it says so. Without that, a case joining the register later would appear on no
    diagram and in no list, which is the failure this repository is built against
    (`feedback_unnumbered_is_uncounted`) — and on a picture it is invisible by construction.

    The citation rules themselves are NOT re-implemented here; `platform/build/check_architecture.py`
    owns them and runs in the publish gate, importing the one status function from this module so
    there is a single rule set rather than two that can disagree.
    """
    rel = "platform/curation/architecture.yaml"
    path = ROOT / "platform" / "curation" / "architecture.yaml"
    data = _yaml_no_duplicate_keys(read_text(path, inputs), rel)
    diagrams = data.get("diagrams")
    if not isinstance(diagrams, list) or not diagrams:
        die(f"{rel} carries no `diagrams` list. An architecture view derived from nothing renders as "
            f"a page with no diagram, which reads as a platform that has no architecture.")

    declared = (data.get("vocabularies") or {}).get("count_from")
    if sorted(declared or []) != sorted(metrics):
        die(f"{rel}: the declared `count_from` vocabulary {sorted(declared or [])} is not the set of "
            f"metrics this build can compute {sorted(metrics)}. A declared metric nothing implements "
            f"renders as a blank number; an implemented one nobody declared is a rule that never "
            f"fires.")

    def annotate(case_id: str, where: str) -> dict:
        if case_id not in cases:
            die(f"{rel}: {where} names {case_id}, which is not in the sealed register. Every chip on "
                f"the diagram has to resolve to a case a reader can open.")
        pub = published.get(case_id) or {}
        return {"case": case_id, "verdict": pub.get("verdict"),
                "restrictions": restricted.get(case_id, []),
                "family": cases[case_id][0], "title": cases[case_id][1]}

    out_diagrams, placed = [], {}
    for d in diagrams:
        if not isinstance(d, dict) or not d.get("id"):
            die(f"{rel} holds a diagram with no `id`; an unidentified diagram sits outside every "
                f"count on this page")
        raw = d.get("boxes")
        if not isinstance(raw, list) or not raw:
            die(f"{rel}: diagram {d['id']} has no boxes")
        boxes: dict[str, dict] = {}
        for b in raw:
            if not isinstance(b, dict) or not b.get("id"):
                die(f"{rel}: diagram {d['id']} holds a box with no `id`")
            if b["id"] in boxes:
                die(f"{rel}: diagram {d['id']} defines the box {b['id']} twice")
            annotated = [annotate(c, f"{d['id']}/{b['id']}") for c in (b.get("cases") or [])]
            status, why = box_status(annotated)
            metric = b.get("count_from")
            mix: dict[str, int] = {}
            for c in annotated:
                key = c["verdict"] or "no verdict"
                mix[key] = mix.get(key, 0) + 1
            boxes[b["id"]] = {
                "id": b["id"], "label": b.get("label"), "detail": b.get("detail"),
                "kind": b.get("kind"), "program": b.get("program"),
                "venv": b.get("venv"), "machine": b.get("machine"),
                "cases": annotated, "n_cases": len(annotated),
                "why_these_cases": b.get("why_these_cases"),
                "measured": b.get("measured"), "why_not_measured": b.get("why_not_measured"),
                "status": status, "status_label": ARCH_STATUS_LABEL[status], "why_this_status": why,
                "verdict_mix": mix,
                "restrictions": sorted({r for c in annotated for r in c["restrictions"]}),
                "count_from": metric, "count": metrics[metric] if metric else None,
            }
            for c in annotated:
                placed.setdefault(c["case"], []).append(f"{d['id']}/{b['id']}")

        edges = []
        for e in d.get("edges") or []:
            for end in ("from", "to"):
                if e.get(end) not in boxes:
                    die(f"{rel}: diagram {d['id']} has an edge whose `{end}` is {e.get(end)!r}, which "
                        f"is not a box in it. An arrow to nothing is an arrow a reader completes "
                        f"themselves.")
            edges.append({"from": e["from"], "to": e["to"], "kind": e.get("kind"),
                          "label": e.get("label")})
        viewbox = _layout(d, boxes, edges, rel)
        by_status: dict[str, int] = {}
        for b in boxes.values():
            by_status[b["status"]] = by_status.get(b["status"], 0) + 1
        out_diagrams.append({
            "id": d["id"], "label": d.get("label"), "subtitle": d.get("subtitle"),
            "why_this_diagram": d.get("why_this_diagram"),
            "boxes": _plain(list(boxes.values()), f"{rel}:{d['id']}.boxes"),
            "edges": _plain(edges, f"{rel}:{d['id']}.edges"),
            "viewbox": viewbox, "boxes_by_status": by_status,
            "n_boxes": len(boxes), "n_edges": len(edges),
        })

    unplaced = []
    for u in data.get("unplaced_cases") or []:
        if not isinstance(u, dict) or not u.get("case"):
            die(f"{rel}: an entry in `unplaced_cases` has no `case`")
        unplaced.append({**annotate(u["case"], "unplaced_cases"), "why": u.get("why")})

    # Both directions, and both are load-bearing. A registered case in neither list is a case the
    # diagram silently omits; a case in both is a case the file says two things about, and the reader
    # sees only the friendlier one.
    both = sorted(set(placed) & {u["case"] for u in unplaced})
    neither = sorted(set(cases) - set(placed) - {u["case"] for u in unplaced})
    if both:
        die(f"{rel} places {both} on a diagram AND lists them as unplaced.")
    if neither:
        die(f"{rel} accounts for neither placing nor excluding {neither}. Every registered case must "
            f"appear on a diagram or be listed in `unplaced_cases` with a reason: a diagram is a "
            f"claim about coverage, and an unlisted case is the part of that claim nobody can check.")

    return {
        "schema": data.get("schema"),
        "vocabularies": _plain(data.get("vocabularies"), f"{rel}:vocabularies"),
        "diagrams": out_diagrams,
        "metrics": metrics,
        "unplaced_cases": _plain(unplaced, f"{rel}:unplaced_cases"),
        "coverage": {"n_registered": len(cases), "n_placed": len(placed),
                     "n_unplaced": len(unplaced),
                     "placed_on": {c: sorted(v) for c, v in sorted(placed.items())},
                     "why": "Placed plus unplaced equals the register exactly, checked in both "
                            "directions at build time. The build fails rather than drawing a diagram "
                            "whose coverage nobody stated."},
        "status_labels": ARCH_STATUS_LABEL,
        "non_colouring_restrictions": sorted(ARCH_NON_COLOURING),
        "geometry": {"box_w": BOX_W, "box_h": BOX_H, "row_pitch": ROW_PITCH,
                     "col_pitch": COL_PITCH,
                     "why": "Computed from the authored edges, never authored. "
                            "platform/build/tests/test_architecture_layout.py asserts zero crossing "
                            "edge pairs and zero edges through a box, as equalities."},
        "mapped_by": data.get("mapped_by"), "mapped_on": _plain(data.get("mapped_on"), "mapped_on"),
        "note": data.get("note"),
    }


def derive_audit(inputs: dict[str, str], stamp: str) -> dict:
    """Run the audit tools over the checked-in example submission and publish what they produced.

    WHY THE SITE SHIPS A WORKED EXAMPLE AT ALL
    ------------------------------------------
    The audit half of this platform is two command-line programs, because the site is static and has no
    backend: it cannot read a reader's repository, and it must never hold their AWS credentials. A page
    that only printed the commands would be honest and useless — a reader deciding whether to run
    anything needs to see the shape of the output first, including the states that read badly.

    So the build runs the real tools over `platform/audit/examples/`, in process, and publishes the
    inventory, the JSON report and the Markdown report verbatim. That is a derivation like every other
    number in this payload: nothing here is written by hand, and a change to either tool or to the
    example moves the published example on the next build.

    WHY IN PROCESS RATHER THAN A CHECKED-IN OUTPUT
    ---------------------------------------------
    A committed `report.json` beside the example would be a second source of truth for what the tools
    do, and the day the report generator changed, the site would show the old one while the CLI printed
    the new one — with nothing to notice, because both files would look authored. Importing the modules
    means the published example is what the code does today, and the manifest records the example's
    input hashes so the reader can check which submission it was derived from.

    The example's own files are recorded as inputs, so `gate_payload.py` sees them as sources: they are
    synthetic and every account id in them is the documentation-reserved one, but that is a property to
    be gated rather than asserted.
    """
    rel = "platform/curation/controls.yaml"
    data = _yaml_no_duplicate_keys(read_text(ROOT / rel, inputs), rel)
    controls_yaml = data.get("controls")
    if not isinstance(controls_yaml, list) or not controls_yaml:
        die(f"{rel} carries no `controls` list, so the audit tools would report nothing about every "
            f"submission and the page would read as an audit that found no problems")

    sys.path.insert(0, str(ROOT / "platform" / "audit"))
    import parse_iac  # noqa: PLC0415 - one implementation of the parser, imported not re-written
    import report as audit_report  # noqa: PLC0415

    example = ROOT / "platform" / "audit" / "examples" / "public-chat-gateway"
    if not example.is_dir():
        die(f"{example.relative_to(ROOT)} is missing: the audit page has no worked example to render, "
            f"and a page that silently drops it reads as a platform with no audit output at all")
    files = []
    for p in sorted(example.rglob("*")):
        if p.is_file():
            files.append({"file": str(p.relative_to(example)), "bytes": p.stat().st_size,
                          "source": record_input(p, inputs)})
    if not files:
        die(f"{example.relative_to(ROOT)} holds no files")

    inventory = parse_iac.build_inventory(example, controls_yaml)
    # `as_of` is the build stamp's calendar day, never a clock read: the report is a document, and a
    # back-dated rebuild must produce the date it was stamped for rather than today.
    as_of = f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
    rep = audit_report.build(inventory, controls_yaml, as_of)
    md = audit_report.markdown(rep)

    declared = sum(1 for o in inventory["observations"] if o["observation"] == "DECLARED")
    return {
        "schema": "grx-audit-page/1",
        "example": {
            "submission": str(example.relative_to(ROOT)),
            "files": files,
            "n_files": len(files),
            "n_controls_declared": declared,
            "is_synthetic": True,
            "why_synthetic": "Nothing in this submission was ever deployed and no resource in it "
                             "exists. A captured template from this study's own runs would carry real "
                             "resource identifiers, so the example is authored with the "
                             "documentation-reserved account id instead.",
        },
        "inventory": _plain(inventory, "audit inventory"),
        "report": _plain(rep, "audit report"),
        "markdown": md,
        "tools": {
            "parse": "platform/audit/parse_iac.py",
            "report": "platform/audit/report.py",
            "commands": [
                "git clone <your-repo> submission",
                ".venv-oracle/bin/python platform/audit/parse_iac.py "
                "--submission submission --out inventory.json",
                ".venv-oracle/bin/python platform/audit/report.py --inventory inventory.json "
                "--as-of <YYYY-MM-DD> --out-json report.json --out-md report.md",
            ],
        },
        "boundaries": [
            {"claim": "This platform never connects to your AWS account.",
             "how": "Neither program takes a profile, a region or a credential, and neither imports "
                    "boto3. The audit is a read of the files you point it at, on your machine."},
            {"claim": "This platform never changes your repository.",
             "how": "The submission directory is opened read-only, symlinks out of it are refused, and "
                    "the only outputs are the two documents you name. No pull request is opened "
                    "against anything you submit."},
            {"claim": "Nothing you type into this page leaves your browser.",
             "how": "The site is static files on S3 behind CloudFront. There is no API to post a repo "
                    "to; the form composes the commands you run yourself."},
        ],
        "note": "The example below is derived at build time by running the two programs named above "
                "over the checked-in example submission. It is not a stored output: change either "
                "program and the next build changes this page.",
    }


def derive_figures(inputs: dict[str, str], check_rc: int | None) -> dict:
    """Census the whitepaper figures, and record each PNG as an input this build read.

    `record_input` rather than a bare `read_bytes()`: the PNG bytes are copied into the payload
    verbatim (see `copy_figures`), so they are an input with a hash like every other, and the copy can
    declare the source it came from. Without that the figures would be the only published bytes with
    no provenance — the exact hole the manifest exists to close.
    """
    man = read_json(FIGURES / "MANIFEST.json", inputs)
    present, missing = [], []
    for p in sorted(FIGURES.glob("fig-*.png")):
        rel = record_input(p, inputs)
        present.append({"file": p.name, "bytes": p.stat().st_size,
                        "sha256": inputs[rel], "source": rel})
    names = {f["file"] for f in present}
    for n in range(1, 9):
        if not any(f.startswith(f"fig-{n:02d}") for f in names):
            missing.append(f"fig-{n:02d}")
    return {"manifest": man, "present": present, "missing": missing,
            "numeric_check": check_rc,
            "numeric_check_note": "rc of `tools/whitepaper_figures.py --check` under .venv-figs, "
                                  "passed in with --figure-check-rc by whoever ran it. 0 means the "
                                  "figures' NUMBERS were re-derived and matched; 1 means they "
                                  "differ, so a figure shows a value the artifacts no longer hold; "
                                  "null means this build did not run it, which the UI must render "
                                  "as 'not verified', never as fresh. The check compares numbers, "
                                  "never PNG bytes: rendered bytes move with matplotlib and "
                                  "freetype versions while the measurements do not.",
            "redaction_note": "These PNGs are copied byte for byte and are NOT text-scannable: a "
                              "regex cannot read a pixel, so the payload gate that catches an "
                              "account id in JSON would not catch one rendered into an axis label. "
                              "What protects a figure is that its numbers come from already-masked "
                              "artifacts, plus a human looking at the image. Stated here because an "
                              "unstated limit reads as a check that passed."}


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


def copy_figures(out_root: Path, figures: dict, outputs: dict[str, str],
                 provenance: dict[str, list[str]], inputs: dict[str, str]) -> int:
    """Copy each whitepaper PNG into the payload, hashed and attributed like every other output.

    Not masked, because a PNG is not text — `emit`'s `redact.mask_text` on compressed image bytes
    would either do nothing or corrupt the file, and doing nothing while calling itself masking is
    worse than not calling it at all. The honest statement of what that leaves unchecked is in
    `figures.json`'s `redaction_note`, where the figure gallery renders it.

    The alternative — leaving the copy to `publish_web.py` — is what this replaces: bytes uploaded by
    the publisher but absent from MANIFEST.json are bytes a reader cannot verify and a gate asserting
    set-equality against the manifest would have to be told to ignore.
    """
    for f in figures["present"]:
        src = ROOT / f["source"]
        rel = f"figures/{f['file']}"
        dst = (out_root / rel).resolve()
        if out_root not in dst.parents:
            die(f"refusing to write outside the output root: {dst}")
        data = src.read_bytes()
        if sha256_bytes(data) != inputs[f["source"]]:
            die(f"{f['source']} changed between the census and the copy; the payload would carry a "
                f"figure whose manifest hash is of different bytes")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        outputs[rel] = f["sha256"]
        provenance[rel] = [f["source"]]
    return len(figures["present"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"output root (default {DEFAULT_OUT}, outside the repository — see "
                         f"WHY THE PAYLOAD LIVES OUTSIDE THE REPOSITORY in this module's docstring)")
    ap.add_argument("--stamp", help="build stamp; default is now, UTC, YYYYmmddTHHMMSSZ")
    ap.add_argument("--clean", action="store_true", help="remove the output root first")
    # An integer this build did not compute, and the ONLY one. Running the figure check needs
    # `.venv-figs` (matplotlib), and importing that here would put a rendering toolchain inside the
    # deriver of the census. So the caller runs it and passes the return code, which this build
    # records verbatim. It is not defaulted to 0: an unrun check must render as "not verified", and a
    # default of 0 would render as verified — the one wrong answer of the three.
    ap.add_argument("--figure-check-rc", type=int, default=None,
                    help="return code of `.venv-figs/bin/python tools/whitepaper_figures.py "
                         "--check`. Omit if it was not run; NEVER pass 0 for 'not run'.")
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
        figures = derive_figures(inputs, args.figure_check_rc)
    with scope() as s_families:
        families = derive_families(inputs, cases)

    restricted: dict[str, list[str]] = {}
    for r in policy.get("restrictions", []):
        for c in r.get("cases", []):
            restricted.setdefault(c, []).append(r["restriction"])
    unknown = sorted(set(restricted) - set(cases))
    if unknown:
        die(f"results/CITATION-POLICY.md names {unknown}, which are not in the sealed register")

    # After `restricted`, deliberately: every badge this page renders is a restriction the citation
    # policy states, so the derivation cannot run before the policy has been read.
    with scope() as s_controls:
        controls = derive_controls(inputs, cases, published, restricted)
    # No new sources: every day here comes from the verdict files and the archive that the register,
    # published and archive scopes already recorded. Its source list is theirs, plus families.yaml for
    # the cadence it compares against.
    pipeline = derive_pipeline(families, cases, published, archive, stamp)
    # After controls, families, figures and registers, because every number a diagram box displays is
    # one of theirs. The diagram counts nothing itself — a box names a metric and this table computes
    # it, so the picture cannot show a total that disagrees with the page it links to.
    with scope() as s_arch:
        architecture = derive_architecture(
            inputs, cases, published, restricted,
            architecture_metrics(cases, published, restricted, archive, by_case, families, controls,
                                 figures, registers))
    # The audit page: the two command-line programs run over the checked-in example submission, in
    # process, so the published example is what the code does today rather than a stored output.
    with scope() as s_audit:
        audit = derive_audit(inputs, stamp)

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
                 "method": "read from the sealed register at build time, not from a recorded value"},
    }, census_sources)
    put("denominators.json", denominators,
        s_register.sorted() + s_published.sorted() + s_claims.sorted())
    put("claims.json", {"rows": rows, "n_rows": len(rows), "by_case": by_case}, s_claims.sorted())
    put("findings.json", {"findings": findings}, s_findings.sorted())
    put("registers.json", registers, s_registers.sorted())
    put("citation_policy.json", policy, s_policy.sorted())
    put("figures.json", figures, s_figures.sorted())
    put("archive.json", {"by_case": archive}, s_archive.sorted())
    # The register is a source too: this file's coverage claim is checked against it, so a reader who
    # wants to know whether the classification is complete needs the tree the check ran over.
    put("families.json", families, s_families.sorted() + s_register.sorted())
    # The register, the published verdicts and the citation policy are all sources of this file: every
    # verdict and badge beside a control is read out of them at build time, never authored beside it.
    put("controls.json", controls, s_controls.sorted() + s_register.sorted()
        + s_published.sorted() + s_policy.sorted())
    put("pipeline.json", pipeline, s_register.sorted() + s_published.sorted()
        + s_archive.sorted() + s_families.sorted())
    # Every source whose numbers a box can display, plus the three the annotation derives from. A
    # narrower list would let this file inherit a redaction exception it did not earn, and a wider one
    # would let it inherit one it should not have.
    put("architecture.json", architecture, s_arch.sorted() + s_register.sorted()
        + s_published.sorted() + s_policy.sorted() + s_archive.sorted() + s_claims.sorted()
        + s_families.sorted() + s_controls.sorted() + s_figures.sorted() + s_registers.sorted())
    put("audit.json", audit, s_audit.sorted() + s_register.sorted() + s_published.sorted()
        + s_policy.sorted())
    put("method.json", derive_method(published, archive, cases),
        s_register.sorted() + s_published.sorted() + s_archive.sorted())

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

    n_figs = copy_figures(out_root, figures, outputs, provenance, inputs)

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
    n_sched = sum(1 for v in families["families"].values() if v["schedulable"])
    print(f"  {len(families['families'])} families classified, {n_sched} schedulable, "
          f"{sum(1 for v in families['families'].values() if v['network_position_sensitive'])} "
          f"network-position sensitive")
    print(f"  {len(findings)} findings, {registers['n_items']} register items, "
          f"{len(policy.get('restrictions', []))} citation restrictions, "
          f"{n_figs} figures copied, missing {figures['missing'] or 'none'}")
    print(f"  {n_series} case(s) needed a series split at >= {SERIES_BYTES} bytes")
    for d in architecture["diagrams"]:
        print(f"  diagram {d['id']}: {d['n_boxes']} boxes, {d['n_edges']} edges, "
              + ", ".join(f"{k} {v}" for k, v in sorted(d["boxes_by_status"].items())))
    print(f"  architecture coverage {architecture['coverage']['n_placed']} placed + "
          f"{architecture['coverage']['n_unplaced']} unplaced = "
          f"{architecture['coverage']['n_registered']} registered")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        print(f"BUILD-FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
