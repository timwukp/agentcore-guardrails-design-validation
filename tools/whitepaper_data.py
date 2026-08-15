#!/usr/bin/env python3
"""Derive every number the whitepaper quotes, from the register and the published verdicts.

Why this file exists
--------------------
`WHITEPAPER-DESIGN.md` §5 ends with a rule: *"Every figure must be generated from the evidence tree
by a script in the repo, never hand-drawn, so that Appendix G's reproduction claim is true. Any
figure whose numbers cannot be regenerated does not ship."* The same rule has to bind the prose, or
the paper's tables become the thing this project has a name for — a number in a justification
string that nothing re-derives (`feedback_prose_is_not_verified`).

So the paper quotes no total it did not get from here, and this script derives every total from the
two sealed sources plus the published verdict files:

  * `claims/triage.csv` — 546 triaged claims, each with its class, its case ids and, when it has no
    case, the written reason why not;
  * `claims/triage_rules.py` — the 93-case sealed registry (`CASES`), whose sha256 is recomputed
    rather than quoted;
  * `results/phase1/*.json` — one file per published verdict.

`census.py`'s own primitives are imported rather than re-implemented. Two scripts deriving "how many
verdicts are published" from the same tree by different code is how two numbers that must agree stop
agreeing (`feedback_two_numbers_two_claims`), and `census.py` is the one the README tells readers to
run.

Outputs, both regenerable and both gitignored by nothing:
  * `results/WHITEPAPER-DATA.json` — machine-readable, one object per case and per section;
  * `results/WHITEPAPER-APPENDIX-C.md` — Appendix C, the full register, in the C↔E form the USENIX
    artifact-appendix pattern asks for: every claim traceable to the experiment that decided it, and
    every claim without one carrying its exclusion reason.

Usage:
    ./.venv-oracle/bin/python tools/whitepaper_data.py [--check]

`--check` regenerates into memory and exits non-zero if the files on disk differ, which is what a
gate would run. Without it, the files are written.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import census  # noqa: E402  sibling script; ROOT is derived there the same way

sys.path.insert(0, str(ROOT / "lib"))
from redact import mask_text  # noqa: E402  the choke point every results/ write goes through

TRIAGE = ROOT / "claims" / "triage.csv"
PHASE1 = ROOT / "results" / "phase1"
DATA_OUT = ROOT / "results" / "WHITEPAPER-DATA.json"
APPC_OUT = ROOT / "results" / "WHITEPAPER-APPENDIX-C.md"

# The four states a verdict can carry, in the order the paper presents them. INCONCLUSIVE sits
# third deliberately: it is not a weaker FALSE, and a table that sorts it next to FALSE invites
# exactly the reading the document's own rule forbids.
VERDICTS = ("TRUE", "FALSE", "INCONCLUSIVE", "RECORDED")


def rows() -> list[dict]:
    return list(csv.DictReader(TRIAGE.open(encoding="utf-8")))


def verdict_files() -> dict[str, dict]:
    """case_id -> the parsed verdict file, for the ONE file per case census.published() accepts."""
    out: dict[str, dict] = {}
    for case, files in census.published().items():
        # published() returns [(filename, verdict), ...]; a case with two files is a snapshot
        # variant, and the canonical one is the file named exactly <case>.json.
        name = f"{case}.json"
        pick = name if any(f == name for f, _ in files) else files[0][0]
        out[case] = json.loads((PHASE1 / pick).read_text(encoding="utf-8"))
    return out


def evidence_of(d: dict) -> dict:
    """The four numbers the paper is allowed to quote for a case, or empty where there are none.

    A case with no `record.evidence` is not an error: RECORDED verdicts and several INCONCLUSIVE
    ones have no interval by construction, and inventing one for symmetry is how a table stops
    being readable as evidence.
    """
    rec = d.get("record") or {}
    ev = rec.get("evidence") or {}
    return {
        "n": ev.get("n"),
        "x": ev.get("x"),
        "interval": ev.get("interval"),
        "threshold": ev.get("threshold"),
        "kind": rec.get("kind") or d.get("kind"),
        "family": rec.get("family"),
    }


def build() -> dict:
    CASES, registry_sha = census.load_register()
    mapped, n_claims = census.claim_mapped()
    vf = verdict_files()
    tri = rows()

    cases = []
    for cid in sorted(CASES, key=lambda c: (c.split("-")[0], int(c.split("-")[1].rstrip("ab")), c)):
        fam, title, cls, oracle = CASES[cid][0], CASES[cid][1], CASES[cid][2], CASES[cid][3]
        d = vf.get(cid)
        claim_ids = sorted(r["claim_id"] for r in tri if cid in (r.get("cases") or "").split())
        cases.append({
            "case_id": cid,
            "family": fam,
            "title": title,
            "cls": cls,
            "oracle_chars": len(oracle),
            "verdict": (d or {}).get("verdict"),
            "published": d is not None,
            "run_id": (d or {}).get("run_id"),
            "region": (d or {}).get("region"),
            "strength": (d or {}).get("strength"),
            "claim_ids": claim_ids,
            "n_claims": len(claim_ids),
            **evidence_of(d or {}),
        })

    # Section mix, by claim x case: a claim naming two cases contributes to both, which is why the
    # design's table totals exceed the claim count and says so.
    sec: dict[str, dict] = {}
    for r in tri:
        s = sec.setdefault(r["anchor"], {"anchor": r["anchor"], "claims": 0, "with_case": 0,
                                         "mix": collections.Counter(), "cases": set()})
        s["claims"] += 1
        ids = (r.get("cases") or "").split()
        if ids:
            s["with_case"] += 1
        for cid in ids:
            s["cases"].add(cid)
            v = (vf.get(cid) or {}).get("verdict")
            if v:
                s["mix"][v] += 1
    sections = [{"anchor": s["anchor"], "claims": s["claims"], "with_case": s["with_case"],
                 "cases": sorted(s["cases"]),
                 "mix": {v: s["mix"].get(v, 0) for v in VERDICTS if s["mix"].get(v)}}
                for s in sorted(sec.values(), key=lambda s: -s["claims"])]

    caseless = [r for r in tri if not (r.get("cases") or "").split()]
    unexplained = [r["claim_id"] for r in caseless if not (r.get("exclusion_reason") or "").strip()]

    return {
        "generated_by": "tools/whitepaper_data.py",
        "sources": {
            "register": "claims/triage_rules.py (sealed)",
            "register_sha256_recomputed": registry_sha,
            "triage": "claims/triage.csv (sealed)",
            "verdicts": "results/phase1/*.json",
        },
        "totals": {
            "claims_triaged": n_claims,
            "claims_with_a_case": sum(1 for r in tri if (r.get("cases") or "").split()),
            "claims_without_a_case": len(caseless),
            "claims_without_a_case_and_without_a_reason": len(unexplained),
            "cases_registered": len(CASES),
            "cases_published": sum(1 for c in cases if c["published"]),
            "cases_unpublished": sorted(c["case_id"] for c in cases if not c["published"]),
            "verdict_mix": {v: sum(1 for c in cases if c["verdict"] == v) for v in VERDICTS},
            "class_mix": dict(collections.Counter(r["cls"] for r in tri)),
        },
        "cases": cases,
        "sections": sections,
        "exclusions": dict(collections.Counter(
            (r.get("rule") or "unruled").split(":")[0] for r in caseless)),
        "unexplained_exclusions": unexplained,
    }


def appendix_c(d: dict) -> str:
    t = d["totals"]
    L = [
        "# Appendix C — The full register: claims → cases → verdicts",
        "",
        "**GENERATED — do not hand-edit.** `./.venv-oracle/bin/python tools/whitepaper_data.py`",
        "",
        f"- **{t['claims_triaged']}** triaged claims, of which **{t['claims_with_a_case']}** carry at "
        f"least one case id and **{t['claims_without_a_case']}** carry none.",
        f"- **{t['claims_without_a_case_and_without_a_reason']}** caseless claims have no written "
        "exclusion reason. That number is the one to check first: a register with unexplained "
        "omissions is a selective register.",
        f"- **{t['cases_registered']}** cases in the sealed registry, recomputed sha256 "
        f"`{d['sources']['register_sha256_recomputed'][:16]}…`, of which **{t['cases_published']}** "
        "carry a verdict on disk.",
        f"- Verdicts: " + ", ".join(f"**{v} {n}**" for v, n in t["verdict_mix"].items() if n) + ".",
        "",
        "An INCONCLUSIVE verdict is not evidence against the claim it tests. It records that the "
        "instrument could not decide, and it licenses no amendment to the document under test.",
        "",
        "## C.1 — Claim → case → verdict (the C↔E map)",
        "",
        "| Case (E) | Family | Verdict | n | x | interval | Claims (C) | Run |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in d["cases"]:
        claims = ", ".join(c["claim_ids"]) if c["claim_ids"] else "— (registered, no claim points here)"
        L.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            c["case_id"], c["family"], c["verdict"] or "not published",
            c["n"] if c["n"] is not None else "—",
            c["x"] if c["x"] is not None else "—",
            c["interval"] or "—", claims, c["run_id"] or "—"))

    L += ["", "## C.2 — By document section, ordered by claim count", "",
          "Mix is counted claim × case, so a claim naming two cases contributes twice and the "
          "totals exceed the claim count.", "",
          "| Section anchor | Claims | With a case | Verdict mix | Cases |", "|---|---|---|---|---|"]
    for s in d["sections"]:
        mix = ", ".join(f"{v} {n}" for v, n in s["mix"].items()) or "—"
        L.append(f"| {s['anchor']} | {s['claims']} | {s['with_case']} | {mix} | "
                 f"{', '.join(s['cases']) or '—'} |")

    L += ["", "## C.3 — Why the caseless claims carry no case", "",
          "Grouped by the triage rule that excluded them. The rules are sealed; the counts are "
          "derived.", "", "| Rule prefix | Claims |", "|---|---|"]
    for rule, n in sorted(d["exclusions"].items(), key=lambda kv: -kv[1]):
        L.append(f"| `{rule}` | {n} |")
    if d["unexplained_exclusions"]:
        L += ["", "**UNEXPLAINED — these are a defect, not a category:**",
              ", ".join(d["unexplained_exclusions"])]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="compare against what is on disk and exit 1 on any difference")
    a = ap.parse_args(argv)

    d = build()
    # Masked BEFORE the --check comparison, not just before the write, so the two paths compare the
    # same bytes. `results/` is the distributable record and every write into it must mask
    # (lib/tests/test_results_writes_are_masked.py); this payload is derived only from files
    # already under `results/`, so on clean input the mask is a no-op — which is the point. A
    # guarantee that holds because the inputs happen to be clean is not a guarantee.
    data = mask_text(json.dumps(d, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    appc = mask_text(appendix_c(d))

    if a.check:
        bad = [p.name for p, want in ((DATA_OUT, data), (APPC_OUT, appc))
               if not p.exists() or p.read_text(encoding="utf-8") != want]
        if bad:
            print(f"STALE — regenerate: {', '.join(bad)}", file=sys.stderr)
            return 1
        print("FRESH — both generated files match the register and the verdicts on disk.")
        return 0

    DATA_OUT.write_text(data, encoding="utf-8")
    APPC_OUT.write_text(appc, encoding="utf-8")
    t = d["totals"]
    print(f"wrote {DATA_OUT.relative_to(ROOT)} and {APPC_OUT.relative_to(ROOT)}")
    print(f"  {t['claims_triaged']} claims, {t['cases_registered']} cases, "
          f"{t['cases_published']} published, mix {t['verdict_mix']}")
    print(f"  caseless {t['claims_without_a_case']}, of which "
          f"{t['claims_without_a_case_and_without_a_reason']} without a written reason")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
