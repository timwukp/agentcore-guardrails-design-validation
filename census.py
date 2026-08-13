#!/usr/bin/env python3
"""Derive the project's case census from the sealed artifacts, and refuse to guess.

Run:  .venv-oracle/bin/python census.py            # human report to stdout
      .venv-oracle/bin/python census.py --write    # also refresh results/_progress_census.txt

WHY THIS FILE EXISTS. `results/_progress_census.txt` was written by hand once. Its
headline — "27 remaining" — was correct, and it was correct *by accident*: it
subtracted 63 published-and-claim-mapped cases from the 90 cases `triage.csv` maps,
while calling those 90 "the register". The register is 93. Two offsetting errors landed
on the right number, and no one could have noticed, because a hand-written count has
nothing to disagree with. Same shape as `feedback_two_numbers_two_claims`: the
numerator and the denominator moved independently and the sentence read fine.

So every number below is derived, and the derivations that must agree are asserted
against each other rather than reconciled in prose.

THERE ARE FOUR DENOMINATORS, NOT ONE. Reporting "n of 93" or "n of 90" is wrong in
both directions, and which one is wrong depends on the question:

  registered          93  every case in the sealed oracle registry
  verdict-eligible    92  registered minus the cases whose own sealed oracle says
                          they cannot be tested at all
  claim-mapped        90  cases that at least one triaged claim points at, i.e. cases
                          whose verdict discharges something in the document
  published           65  cases with a verdict on disk

Coverage is `published / verdict-eligible`. A case that cannot be tested is not
outstanding work, and a case that no claim points at is still real work — it just
discharges an API-surface fact rather than a document sentence.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TRIAGE = ROOT / "claims" / "triage.csv"
PREREG = ROOT / "PREREGISTRATION.yaml"
PHASE1 = ROOT / "results" / "phase1"
CENSUS = ROOT / "results" / "_progress_census.txt"

# The register holds 93 cases; `triage.csv` maps claims to 90 of them. The residue is
# THREE cases, and each is absent for its own reason. The reasons are declared here and
# the residue is DERIVED below; a mismatch in either direction is an error, not a
# footnote. That is the whole point of the table: if a future triage pass maps a claim to
# F1-4, or unmaps one from some other case, this file fails and someone has to look.
#
# `check` is a substring that must appear in the case's own sealed oracle or instrument
# text, so the reason is verified against the seal rather than asserted here in prose
# (`feedback_prose_is_not_verified`).
CLAIM_UNMAPPED_BY_DESIGN = {
    "F9-1": {
        "kind": "untestable",
        "check": "NOT TESTABLE",
        "why": "Its own sealed oracle says so: AgentCore exposes no fault-injection "
               "surface for policy evaluation, so an induced evaluation timeout cannot "
               "be produced. It is excluded from the verdict-eligible denominator — it "
               "is not outstanding work and never will be. The nearest proxies (F5-4a, "
               "F5-4b) are separately registered and both have verdicts.",
    },
    "F1-21": {
        "kind": "api-surface",
        "check": "service-model read",
        "why": "Its proposition is about the SERVICE MODEL, not about a document "
               "sentence: whether `guardrailVersion` and "
               "`modelEnforcement.includedModels` are required fields. The document "
               "mentions `guardrailVersion` three times and asserts requiredness at "
               "none of them — §3.2's bullet (mapped to F1-7/F1-10) says only "
               "\"obtain\" it, §3.3's code sample (F1-2) passes it, and §6.2's metric "
               "row (F7-3) names it as a dimension. So there is no claim to map, and "
               "the absence is correct. It is verdict-eligible and has a verdict: it "
               "establishes the surface the other F1 cases are read against.",
    },
    "F1-4": {
        "kind": "api-surface",
        "check": "cedar-only, policy-only, both",
        "why": "Same class as F1-21, and cleaner: the arity of the `PolicyDefinition` "
               "union is an API fact, and a text search over all 546 triaged claims for "
               "the constraint returns ZERO rows — the document shows the union in use "
               "and never states that exactly one arm is accepted. Nothing to map.",
    },
}


def fail(msg: str) -> None:
    print(f"CENSUS-FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_register() -> tuple[dict, str]:
    """Return (CASES, recomputed registry sha256).

    The sha is recomputed with PREREGISTRATION.yaml's own recorded serialization so the
    seal is checked for LIVENESS, not merely quoted (`feedback_provenance_stamp_liveness`).
    """
    from claims.triage_rules import CASES  # noqa: PLC0415  (sealed artifact, imported late)

    ser = json.dumps({c: CASES[c][3] for c in sorted(CASES)},
                     sort_keys=True, ensure_ascii=False).encode()
    return CASES, hashlib.sha256(ser).hexdigest()


def prereg_registry_sha() -> tuple[int, str]:
    """Read n_cases and sha256 from PREREGISTRATION.yaml without importing yaml.

    A one-key read does not justify a dependency, and the two lines are stable under the
    seal — if the file's shape changes, this raises rather than returning a wrong number.
    """
    n_cases = sha = None
    inside = False
    for raw in PREREG.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s.startswith("oracle_registry:"):
            inside = True
            continue
        if inside:
            if s.startswith("n_cases:"):
                n_cases = int(s.split(":", 1)[1].strip())
            elif s.startswith("sha256:"):
                sha = s.split(":", 1)[1].strip().strip("'\"")
            elif s and not raw.startswith((" ", "\t")):
                break
            if n_cases is not None and sha is not None:
                break
    if n_cases is None or sha is None:
        fail("could not read meta.oracle_registry.{n_cases,sha256} from PREREGISTRATION.yaml")
    return n_cases, sha


def claim_mapped() -> tuple[set[str], int]:
    rows = list(csv.DictReader(TRIAGE.open(encoding="utf-8")))
    mapped: set[str] = set()
    for r in rows:
        # Whitespace-token read, not a whole-cell compare: a `cases` cell can hold
        # several ids ("F3-10 F3-9"), and an equality test silently drops those rows.
        mapped |= set((r.get("cases") or "").split())
    return mapped, len(rows)


def published() -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for f in sorted(PHASE1.glob("*.json")):
        if "archive" in f.parts or "archive" in f.name:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(d, dict) and d.get("verdict") and isinstance(d.get("case_id"), str):
            out.setdefault(d["case_id"], []).append((f.name, d["verdict"]))
    return out


def run(write: bool = False) -> int:
    """Derive and report the census. Raises SystemExit(1) on any failed invariant.

    Kept separate from `main()` because `main()` reads `sys.argv`, and a callable that
    parses argv is not callable from a test — under pytest it sees pytest's own flags and
    exits 2. The first version of this file had them fused, every mutation arm below came
    back `SystemExit(2)` instead of `SystemExit(1)`, and the arm that noticed was the one
    checking a guard that had nothing to do with argument parsing
    (`feedback_cryptic_error_is_missing_guard`).
    """
    CASES, sha_live = load_register()
    n_declared, sha_declared = prereg_registry_sha()
    register = set(CASES)

    lines: list[str] = []
    def out(s: str = "") -> None:
        lines.append(s)
        print(s)

    out("case census — every number below is derived, none is remembered")
    out(f"  register        claims/triage_rules.py CASES            {len(register)} case(s)")
    out(f"  registry sha256 recomputed                             {sha_live}")
    out(f"  registry sha256 PREREGISTRATION.yaml declares           {sha_declared}")
    if sha_live != sha_declared:
        fail("the oracle registry no longer hashes to its sealed sha256 — a sealed "
             "artifact has been edited, which is prohibited; do not report a census "
             "over an unsealed register")
    if len(register) != n_declared:
        fail(f"register holds {len(register)} cases, PREREGISTRATION.yaml declares "
             f"{n_declared}; the two cannot both be right")
    out("  -> seal live: the register hashes to its declared sha256 and its declared size")
    out()

    mapped, n_rows = claim_mapped()
    ver = published()

    # --- invariants, asserted rather than described -------------------------------------
    if mapped - register:
        fail(f"claims map to case(s) that are not registered: {sorted(mapped - register)}")
    if set(ver) - register:
        fail(f"verdict published for unregistered case(s): {sorted(set(ver) - register)}")
    residue = register - mapped
    if residue != set(CLAIM_UNMAPPED_BY_DESIGN):
        fail(f"the claim-unmapped residue is {sorted(residue)}, but "
             f"CLAIM_UNMAPPED_BY_DESIGN declares {sorted(CLAIM_UNMAPPED_BY_DESIGN)}. "
             f"Every unmapped register case needs a stated reason; add or remove one.")
    for cid, meta in CLAIM_UNMAPPED_BY_DESIGN.items():
        sealed = " ".join(str(x) for x in CASES[cid])
        if meta["check"] not in sealed:
            fail(f"{cid}: the declared reason cites {meta['check']!r}, which does not "
                 f"appear in the case's own sealed text — the reason is unverified prose")

    untestable = {c for c, m in CLAIM_UNMAPPED_BY_DESIGN.items() if m["kind"] == "untestable"}
    eligible = register - untestable
    if set(ver) & untestable:
        fail(f"a case declared untestable has a verdict: {sorted(set(ver) & untestable)}")

    out(f"  claims triaged                                         {n_rows} row(s)")
    out(f"  claim-mapped    cases at least one claim points at      {len(mapped)}")
    out(f"  untestable      by their own sealed oracle              {len(untestable)} "
        f"{sorted(untestable)}")
    out(f"  verdict-eligible register minus untestable              {len(eligible)}")
    out(f"  published       verdict on disk under results/phase1/   {len(ver)}")
    out(f"  REMAINING       verdict-eligible minus published        {len(eligible - set(ver))}")
    out()
    out("  the three registered cases no claim points at, and why each is correct:")
    for cid in sorted(CLAIM_UNMAPPED_BY_DESIGN):
        m = CLAIM_UNMAPPED_BY_DESIGN[cid]
        v = ver.get(cid)
        state = f"verdict {v[0][1]}" if v else "no verdict"
        out(f"    {cid:6s} {m['kind']:12s} {state:14s} {m['why'][:96]}…")
    out()

    verdicts = collections.Counter(v[0][1] for v in ver.values())
    out("  verdicts: " + ", ".join(f"{k} {n}" for k, n in sorted(verdicts.items())))
    out()

    fam_of = {c: CASES[c][0] for c in register}
    out("  by family (published / verdict-eligible):")
    for fam in sorted({fam_of[c] for c in register}, key=lambda f: (len(f), f)):
        elig = {c for c in eligible if fam_of[c] == fam}
        done = elig & set(ver)
        gap = sorted(elig - done)
        out(f"    {fam:4s} {len(done):3d}/{len(elig):<3d}" +
            (f"   outstanding: {' '.join(gap)}" if gap else "   complete"))
    out()
    rem = sorted(eligible - set(ver))
    out(f"  outstanding ({len(rem)}): {' '.join(rem)}")

    if write:
        CENSUS.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwrote {CENSUS.relative_to(ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="refresh results/_progress_census.txt from this derivation")
    args = ap.parse_args(argv)
    return run(write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
