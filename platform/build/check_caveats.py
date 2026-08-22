#!/usr/bin/env python3
"""Gate over `platform/curation/caveats.yaml` — the authored bounds on how a verdict may be read.

WHAT THIS GATE IS FOR

Every other authored file in `platform/curation/` says something about the study's shape. This one
says something about a verdict's *limits*, in the platform's own voice, on a page where the reader is
looking at a verdict. That makes it the file most able to do quiet damage in either direction: a
caveat that overstates a limit makes the study look weaker than its evidence, and a caveat that
understates one leaves the reader over-reading with a reassuring sentence in front of them.

WHAT IS DERIVED, AND WHAT IS ONLY CHECKED

Who is owed a caveat is NOT decided here. It is imported from `build_site_data.caveat_census`, the
single producer of that rule, so this gate and the published number cannot disagree by construction.
The repo has already shipped one wrong caveat-coverage figure (39, in `platform/audit/report.py`'s
docstring, where its own function derives 33) and it came from a second unscoped count of the same
fields. One producer, imported.

`platform/audit/report.py` counts something DIFFERENT on purpose — nine caveat field names across all
91 cases — and publishes its own derivation. Two numbers, two claims; this gate says nothing about it.

THE CEILING MATTERS MORE THAN THE FLOOR HERE

The obvious failure is a missing caveat. The dangerous one is an entry for a case whose record ALREADY
carries its own sentence: the page would then show a platform paraphrase in the slot where an artifact
exists, which is the one substitution this platform may never make. Both are fatal, and
`tests/test_check_caveats.py` proves each arm can fail.

WHAT A CAVEAT MAY NOT SAY, AND WHICH OF THOSE RULES A PROGRAM CAN HOLD

Three rules bind the prose. Two are mechanical:

  1. A case whose oracle decided on an absence — zero events, one distinct value, statistical
     indistinguishability, an upper bound below a line — must have a caveat that states a BOUND.
     Greenland, Senn, Rothman, Carlin, Poole, Goodman & Altman, Eur J Epidemiol 31:337-350 (2016),
     items #4 and #6: a nonsignificant result does not support the test hypothesis, and p > 0.05 does
     not mean absence "was shown or demonstrated". This arm is checked positively — the caveat must
     contain bound-language — rather than by banning words, because a ban on "no effect" is satisfied
     by any paraphrase and would read as covering a property it cannot see.
  2. No caveat may assert that a value has been refuted or excluded. Same paper, item #20: "An effect
     size outside the 95 % confidence interval has been refuted (or excluded) by the data. No!" This
     arm IS a phrase ban, because these phrasings have no innocent reading in this file, and every
     banned phrase is exercised by an arm in `tests/test_check_caveats.py`.

The third — no caveat introduces a fact that is not in the record — is NOT mechanical, and this gate
cannot pretend otherwise. `derived_from` is checked to name fields the case actually carries, which
catches a citation of evidence that does not exist; it cannot catch a sentence that names a real field
and then says something false about it. That is a human read, and `review_status` in the YAML says
whether one has happened.

EXIT CODES

0 = every rule holds. 2 = at least one violation, all of them printed. Never 1, because 1 is what a
Python traceback exits with and a crash must not be readable as "one finding".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site_data as B  # noqa: E402 - path must be set before the import

ROOT = Path(__file__).resolve().parent.parent.parent
CURATION = ROOT / "platform" / "curation" / "caveats.yaml"
PHASE1 = ROOT / "results" / "phase1"

# Floors. A file that shrank to nothing must fail rather than pass over an empty set
# (`feedback_zero_file_scan_is_error`). MIN_AUTHORED is deliberately well below the 49 authored today:
# a floor set at the measurement fails on the first legitimate case whose record acquires its own
# sentence — which is an IMPROVEMENT — while still catching the file being emptied or unparsed. What
# this floor cannot see is a single entry going missing; that is what the both-directions check
# against the census is for, and the census is derived, not typed.
MIN_AUTHORED = 20
MIN_PHASE1_FILES = 90

# A one-line placeholder is the shape a forgotten caveat takes. The shortest authored `why` today is
# far above this; see the note on MIN_AUTHORED for why the floor is not raised to meet it.
MIN_WHY_CHARS = 120

ALLOWED_KEYS = {"verdict", "why", "derived_from"}

# The file-level fields that say whose sentences these are. Named here rather than inline in `check()` so
# there is one place to read the answer to "what does the page have to be able to say about this prose",
# and one place for the test to neuter when it proves the rule is live.
PROVENANCE_FIELDS = ("authored_by", "authored_on", "authored_from", "review_status")

# Which verdicts rest on NOT observing something — and therefore must carry a BOUND.
#
# This is keyed on (verdict, kind), not on kind alone, because the shape belongs to the DIRECTION that
# holds, not to the oracle. ZERO_EVENTS is the clearest case: TRUE means 0 events in n trials, which a
# reader will read as a rate of zero; FALSE means events WERE seen, which is a presence finding and
# needs no ceiling. Keying on the kind alone gets both wrong in opposite directions — it would demand
# bound-language from the 1 case where events were observed, and it would let all 9 EXISTENCE/FALSE
# cases (the thing was not seen in the probes that ran) through with no bound at all.
#
# The criterion, applied case by case against each oracle's own text: the holding verdict is
# established by a NON-observation over a sample, so a reader can mistake it for a zero rate or a zero
# difference. A sample is part of the criterion because that is what makes the remedy — a one-sided
# ceiling — available; a single read of an API enum has no n and gets a different kind of limit.
#
# EVERY pair present in the silent set must appear here, including the ones that are NOT absence-shaped.
# A pair missing from this table is a finding, not a pass. A guard whose unlisted cases are assumed safe
# is a guard asserting a scope it never checked.
ABSENCE_SHAPED: dict[tuple[str, str], tuple[bool, str]] = {
    # -- absence-shaped: the verdict is a non-observation over a sample -----------------------------
    ("TRUE", "ZERO_EVENTS"): (True, "0 events in n trials reads as a rate of 0"),
    ("FALSE", "EXISTENCE"): (True, "the thing was not observed in the probes that ran"),
    ("FALSE", "DISTINCT_AT_LEAST"): (True, "one distinct value in n is a 0/n non-observation of variation"),
    ("TRUE", "INDISTINGUISHABLE"): (True, "a nonsignificant difference reads as no difference"),
    ("TRUE", "UPPER_BELOW"): (True, "an upper bound below a line reads as none at all"),
    ("TRUE", "ASYMMETRIC_FPR"): (True, "a Wilson upper bound under 10% reads as no false positives"),
    ("TRUE", "NONNEG_RESIDUAL"): (True, "not significantly negative reads as not negative"),
    ("FALSE", "LOWER_ABOVE"): (True, "an upper bound below the line reads as never detected"),
    ("FALSE", "PAIRED_IMPROVEMENT"): (True, "no measured improvement reads as no improvement exists"),
    # -- not absence-shaped: the verdict is something that WAS observed -----------------------------
    ("FALSE", "ZERO_EVENTS"): (False, "events were observed"),
    ("TRUE", "EXISTENCE"): (False, "the thing was observed"),
    ("FALSE", "BAND_CONTAINS"): (False, "a measured band outside a documented range is a discrepancy seen"),
    ("TRUE", "BAND_CONTAINS"): (False, "a measured band inside a documented range is conformity seen"),
    ("FALSE", "CI_OVERLAPS"): (False, "a disjoint interval is a difference seen"),
    ("TRUE", "DISJOINT_INTERVALS"): (False, "disjoint intervals are discrimination seen"),
    ("TRUE", "LOWER_ABOVE"): (False, "a lower bound above the line is efficacy seen"),
    ("TRUE", "PAIRED_IMPROVEMENT"): (False, "a significant paired improvement is an effect seen"),
    ("FALSE", "BOUNDARY"): (False, "a tier mismatch is a behaviour seen"),
    # These two carry a negative component with no sample behind it, so the ceiling remedy does not
    # apply and this arm does not ask for it. Their real limit is the one read, at one API version, on
    # one date — which the `why` prose has to carry and no arm here can confirm. Recorded rather than
    # omitted so the choice is visible.
    ("TRUE", "ENUM_EXACT"): (False, "an exact enum match is one read, not a sample"),
    ("TRUE", "ROC_LATTICE"): (False, "an interior optimum is a shape seen; the <=7 ceiling is F1's, not this case's"),
}

# Positive evidence that the caveat did the work rule 1 requires. There are two honest ways to bound a
# non-observation, and this arm accepts either, because which one is available depends on what limited
# the case:
#
#   CEILING — a number. "0 flips in 300 calls bounds the rate from above; the one-sided 95% ceiling is
#   about 1.0%." Available when the non-observation happened over a SAMPLE, so an n exists to put in
#   the arithmetic. This is the form Greenland et al. item #4 points at directly.
#
#   EQUIVALENCE — a rival world. "A pattern that is stored and then ignored would produce exactly this
#   observation." Available always, and it is the STRONGER form when what limited the case was coverage
#   rather than sampling: the 9 EXISTENCE/FALSE cases probed a set of shapes, not n draws from a
#   population, so there is no rate to put a ceiling on and inventing an n to satisfy a regex would be
#   worse prose than naming the shape the probes could not have reached.
#
# What this arm deliberately does NOT accept is the hedge — "is unmeasured", "is unobserved", "nothing
# here shows". Those name a gap without saying what fills it, and a reader takes them as modesty rather
# than as a limit on the verdict they are looking at. The distinction is the whole point of the arm; it
# is also why widening these patterns until the file passes would be self-defeating, and why
# the `unbounded` arm in `tests/test_check_caveats.py` exists to prove the arm can still fail.
CEILING_LANGUAGE = re.compile(
    r"\b(bounds? (it |the |from )|bounded|ceiling|one-sided|upper bound|lower bound|"
    r"compatible with|consistent with|does not exclude|not a rate|no power claim)\b",
    re.IGNORECASE)
EQUIVALENCE_LANGUAGE = re.compile(
    r"(produce exactly this observation|produce this same observation|produce the same data|"
    r"would look identical|look identical|cannot tell (them|the two) apart|"
    r"indistinguishable from|no arm here could have seen|"
    r"could not have (been )?(seen|reached)|would have looked the same|same observation)",
    re.IGNORECASE)


def bounds_the_reading(why: str) -> bool:
    return bool(CEILING_LANGUAGE.search(why) or EQUIVALENCE_LANGUAGE.search(why))

# Phrases with no innocent reading in this file (rule 2, Greenland item #20). Matched on the
# whitespace-normalised `why`. Each is exercised by a test arm.
BANNED_PHRASES = (
    "has been refuted",
    "was refuted",
    "is refuted",
    "are refuted",
    "has been excluded by the data",
    "excluded by the data",
    "ruled out by the data",
    "outside the interval has been excluded",
    "demonstrates absence",
    "demonstrates that no",
    "proves there is no",
    "proves that no",
    "shows that no effect",
    "no effect exists",
)

FINDINGS: list[str] = []


def fail(msg: str) -> None:
    FINDINGS.append(msg)


def norm(s: str) -> str:
    return " ".join(str(s).split())


def load_yaml(path: Path | None = None) -> dict:
    path = path or CURATION
    if not path.is_file():
        print(f"FATAL: {path} does not exist", file=sys.stderr)
        raise SystemExit(2)
    return B._yaml_no_duplicate_keys(path.read_text(encoding="utf-8"), str(path))


def load_published() -> dict[str, dict]:
    """The live verdict files, in the shape `caveat_census` expects.

    Read directly rather than through the build, so this gate can run before a build exists. The
    SHAPE is the build's (`{cid: {"verdict":..., "record":...}}`) because the census rule is the
    build's, and a gate that reshapes its input to suit itself is a gate testing its own adapter.
    """
    files = sorted(PHASE1.glob("*.json"))
    if len(files) < MIN_PHASE1_FILES:
        print(f"FATAL: results/phase1/ holds {len(files)} file(s), below the floor of "
              f"{MIN_PHASE1_FILES}; a caveat gate that reads no verdicts must not report clean",
              file=sys.stderr)
        raise SystemExit(2)
    out: dict[str, dict] = {}
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"FATAL: {f.name} is not readable JSON ({type(e).__name__})", file=sys.stderr)
            raise SystemExit(2) from e
        if isinstance(d, dict) and isinstance(d.get("case_id"), str) and d.get("verdict"):
            out[d["case_id"]] = {"verdict": d["verdict"], "record": d}
    return out


def kind_of(published: dict, cid: str) -> str:
    rec = published[cid]["record"]
    adj = rec.get("record") if isinstance(rec.get("record"), dict) else {}
    return str(rec.get("kind") or (adj or {}).get("kind") or "")


def record_fields(published: dict, cid: str) -> set[str]:
    """Every field name a caveat may legitimately name in `derived_from`, for this case.

    The verdict file's own top-level keys, plus its nested `record` block's, plus the page-level names
    the build attaches (`oracle_text`, `citation_restrictions`) which live beside the record rather
    than inside it.
    """
    rec = published[cid]["record"]
    names = set(rec)
    adj = rec.get("record")
    if isinstance(adj, dict):
        names |= set(adj)
    return names | {"oracle_text", "citation_restrictions"}


def check(path: Path | None = None) -> None:
    """Every rule, against the file at `path` (the real one unless a test points elsewhere).

    No mutation machinery lives here. `platform/build/tests/test_check_caveats.py` builds each mutant by
    loading the REAL file, changing one thing, dumping it to a temporary path and pointing this gate at
    it — the same shape as the architecture and control gate tests. A `--mutate` flag would have put the
    code that breaks this gate inside the gate that has to be trustworthy, and it would have been a flag
    somebody could pass on a publish run.
    """
    FINDINGS.clear()  # so a test calling this twice does not read the first run's findings
    data = load_yaml(path)
    published = load_published()
    census = B.caveat_census(published)

    silent_direction = {c: k for k, d in census.items() for c in d["silent"]}
    entries = data.get("caveats")
    if not isinstance(entries, dict) or not entries:
        fail("the file carries no `caveats` mapping, so nothing bounds the reading of any case whose "
             "record is silent. An unparsed or emptied file must not read as a clean run.")
        return

    # ---------------------------------------------------------------- floors
    if len(entries) < MIN_AUTHORED:
        fail(f"caveats.yaml authors {len(entries)} caveat(s), below the floor of {MIN_AUTHORED}. "
             f"A file that shrank to nothing must fail rather than pass over an empty set.")

    for field in PROVENANCE_FIELDS:
        if not norm(data.get(field) or ""):
            fail(f"caveats.yaml carries no `{field}`. These sentences are not the study's words and "
                 f"the page must be able to say whose they are.")

    # ---------------------------------------------------------------- both directions vs the census
    extra = sorted(set(entries) - set(silent_direction))
    for cid in extra:
        if cid not in published:
            fail(f"{cid}: authored here but is not a published case with a verdict.")
        else:
            fail(f"{cid}: authored here, but it is NOT in the published silent set. Either its record "
                 f"already carries its own `{B.CAVEAT_FIELD_FOR.get(published[cid]['verdict'], '?')}` "
                 f"— in which case this file shadows an artifact with a paraphrase — or its verdict "
                 f"changed and the caveat outlived it.")
    for cid in sorted(set(silent_direction) - set(entries)):
        fail(f"{cid}: the census publishes it as silent ({silent_direction[cid]}) and no caveat is "
             f"authored. Its case page says only that the record states no limits.")

    # ---------------------------------------------------------------- per entry
    for cid in sorted(entries):
        e = entries[cid]
        if not isinstance(e, dict):
            fail(f"{cid}: entry is not a mapping")
            continue
        unknown = sorted(set(e) - ALLOWED_KEYS)
        if unknown:
            fail(f"{cid}: unknown key(s) {unknown}. A misspelt key reads as a caveat with no "
                 f"provenance, and `why` would fall back to nothing.")
        if cid in silent_direction and e.get("verdict") != silent_direction[cid]:
            fail(f"{cid}: authored for verdict {e.get('verdict')!r}, published verdict is "
                 f"{silent_direction[cid]!r}. A caveat that outlives a verdict change is worse than "
                 f"no caveat, because it is read as current.")
        why = norm(e.get("why") or "")
        if len(why) < MIN_WHY_CHARS:
            fail(f"{cid}: `why` is {len(why)} characters, below the floor of {MIN_WHY_CHARS}. A "
                 f"caveat this short is a placeholder, and it renders as though it were a bound.")
        low = why.lower()
        for phrase in BANNED_PHRASES:
            if phrase in low:
                fail(f"{cid}: `why` contains {phrase!r}. Greenland et al. 2016 item #20 — a value "
                     f"outside an interval has not been refuted or excluded by the data; and items "
                     f"#4/#6 — a nonsignificant result does not demonstrate absence.")
        src = e.get("derived_from")
        if not isinstance(src, list) or not src:
            fail(f"{cid}: `derived_from` must be a non-empty list naming the record fields the "
                 f"caveat reads. A bound with no named evidence is an opinion.")
        elif cid in published:
            have = record_fields(published, cid)
            for name in src:
                if str(name) not in have:
                    fail(f"{cid}: `derived_from` names {name!r}, which this case's record does not "
                         f"carry. A caveat citing evidence that does not exist is worse than silence.")
        if cid not in published:
            continue
        pair = (published[cid]["verdict"], kind_of(published, cid))
        if pair not in ABSENCE_SHAPED:
            fail(f"{cid}: verdict/kind pair {pair} is not classified in ABSENCE_SHAPED. Whether this "
                 f"verdict rests on a non-observation decides whether its caveat must state a bound, "
                 f"and an unclassified pair is not the same as a safe one — classify it.")
        elif ABSENCE_SHAPED[pair][0] and not bounds_the_reading(why):
            fail(f"{cid}: {pair[1]}/{pair[0]} rests on a non-observation ({ABSENCE_SHAPED[pair][1]}) "
                 f"and the caveat neither states a ceiling nor names a rival world that produces the "
                 f"same observation. Greenland et al. items #4/#6: a non-observation is a rate below a "
                 f"ceiling, not a rate of 0. Naming the gap is a hedge; bound it or show what fills it.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--caveats", type=Path, default=CURATION,
                    help="the authored file to check; the tests point this at their mutants")
    ap.add_argument("--list-kinds", action="store_true",
                    help="print every (verdict, oracle kind) pair among the authored cases and how "
                         "ABSENCE_SHAPED classifies it, so the table can be read against the oracles")
    args = ap.parse_args(argv)

    if args.list_kinds:
        published = load_published()
        data = load_yaml(args.caveats)
        pairs: dict[tuple[str, str], list[str]] = {}
        for cid in sorted(data.get("caveats") or {}):
            if cid not in published:
                continue
            pairs.setdefault((published[cid]["verdict"],
                              kind_of(published, cid) or "(none recorded)"), []).append(cid)
        for p in sorted(pairs):
            known = ABSENCE_SHAPED.get(p)
            mark = "UNCLASSIFIED" if known is None else ("bound required" if known[0] else "-")
            print(f"{p[0]:6} {p[1]:22} {mark:15} n={len(pairs[p]):2}  {' '.join(pairs[p])}")
        return 0

    check(args.caveats)
    if FINDINGS:
        for f in FINDINGS:
            print(f"caveats: {f}")
        print(f"\n{len(FINDINGS)} finding(s).", file=sys.stderr)
        return 2
    print(f"caveats: OK — {args.caveats} agrees with the published silent set, every entry names its "
          f"evidence, and no absence is written as a demonstration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
