#!/usr/bin/env python3
"""Gate over the design document's own citations — does the document agree with this platform's register?

WHAT THIS GATE IS FOR

The site is about to publish the design, and the reason to publish it here rather than anywhere else is
one sentence: *these practices were measured on this platform, and you can check.* That sentence is
worth nothing if the checking is a claim. So it is a program.

`platform/build/practices_source.py` reads all 45 practices out of the two v1.4 editions and parses the
324 case references the document makes about itself. This gate takes every asserted `(case, verdict)`
pair out of that parse and compares it against two artifacts the document does not control:

  * `results/phase1/<case>.json` — the live verdict of each case, via `check_controls.read_verdicts()`.
  * the machine block of `results/CITATION-POLICY.md` — which cases may be cited and as what, via
    `check_controls.read_restrictions()`.

Both readers are IMPORTED, not reimplemented. A second reader for the same file is a second answer to
the same question, and the one that goes stale is always the copy. The restriction *sets* are imported
for the same reason: no case id is hardcoded in this file, so a case that acquires `NEVER_CITE` tomorrow
is covered without an edit here — a gate whose scope is a name list cannot notice a new name.

WHAT COMES OUT, AND WHY A LEDGER RATHER THAN A SUPPRESSION LIST

Three kinds of disagreement survive that comparison and none can be settled by a program:

  * the document asserts a verdict the register does not carry;
  * the document asserts the verdict of a case the policy says may never be cited as one;
  * the document asserts TRUE or FALSE for a case whose restriction is `PARTIAL` — legal on one
    dimension and forbidden on another, and only a reader of the sentence can tell which one it is.

Each is adjudicated once, by a human, in `platform/curation/practices.yaml`, and this gate holds that
ledger to three rules that a suppression list does not have:

  1. **Both directions are fatal.** An occurrence with no entry fails; an entry whose occurrence no
     longer exists fails. So a new disagreement cannot arrive quietly and an old excuse cannot outlive
     the sentence it was written for.
  2. **The quotation is re-read.** Each entry quotes a fragment of the sentence in BOTH editions, and
     the gate asserts the fragment is still inside the span the payload publishes. A `(case, verdict)`
     key alone stays true while its reason stops being; a quotation cannot.
  3. **`OPEN_*` is a finding, not an exemption.** An open entry must name the FUTURE-WORK item it
     belongs to and what it is blocked on, and their number is CAPPED and ratchets down only. A defect
     a build knows about and a reader does not is what this project's editorial rule exists to prevent.

WHY THE `NEVER_CITE` RULE IS WEAKER HERE THAN IN `check_controls.py`

There, `F5-3b` may not appear in a `cites:` list at all, because `controls.yaml` is the platform's own
voice recommending something to a reader and a bare mention is already a citation. Here the subject is a
narrative document that has to be able to say *why* a case is unusable — and it does, four times, once
with the words "carries NO publishable standing" in the same sentence as the verdict. So the rule is
that a `NEVER_CITE` case may be NAMED and may not have its verdict ASSERTED without adjudication.
Naming and citing are different acts; a gate that could not distinguish them would forbid disclosure.

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

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # so this runs as a script and imports as a module
    sys.path.insert(0, str(HERE))

import practices_source  # noqa: E402
from check_controls import (  # noqa: E402
    RESTRICTION_CONTEXT_ONLY,
    RESTRICTION_NEVER,
    RESTRICTION_NEEDS_SCOPE,
    RESTRICTION_NOT_ESTABLISHED_ONLY,
    Findings,
    die,
    load_yaml_no_duplicate_keys,
    read_restrictions,
    read_verdicts,
    rel,
)

ROOT = HERE.parent.parent
# The default only. It is never reassigned: the path actually read is threaded into `check_shape` and
# `match` so their messages name it. An earlier version wrote this global so the messages would be
# right, and the cost showed up two calls later — `--practices` resolves its default at parse time, so
# a second run in the same process silently read the first run's file and failed against it.
CURATION = ROOT / "platform" / "curation" / "practices.yaml"

SCHEMA = "grx-practices/1"

# The number of OPEN findings the design document currently carries. This is a CEILING and it
# ratchets DOWN only: it drops when a v1.5 amendment removes a site, and raising it is the change
# that has to be argued for. There is deliberately no floor — a floor would make fixing the document
# fail the build — and the ceiling is here rather than in the YAML because a count in a curation file
# is a number two places can disagree about.
MAX_OPEN_ADJUDICATIONS = 7

MIN_WHY = 80
MIN_EVIDENCE = 20
# Visual COLUMNS, not characters. A character floor written for English is a shorter floor in Chinese:
# `不具可發布地位` says as much as "carries NO publishable standing" in 7 characters, and a floor of 12
# characters would reject the Chinese quotation of a sentence whose English quotation it accepts —
# the gate would then be weaker on the edition it was measuring more strictly. `vwidth` counts CJK as
# two columns, which is the width the same text occupies for a reader, and it is the repo's one width
# implementation (`tools/deckgen/mdsource.py`, already used to fit slide cells).
MIN_FRAGMENT = 12

DISPOSITIONS = {
    "LEGAL_PER_METRIC": "legal",
    "LEGAL_WITHDRAWN_IN_PLACE": "legal",
    "OPEN_RESTS_ON_RESTRICTED_DIMENSION": "open",
    "OPEN_QUALIFICATION_ABSENT": "open",
}

ENTRY_REQUIRED = {"case", "asserted", "where", "disposition", "why", "evidence", "span_must_contain"}
# `unit` names the sub-unit a per-unit oracle scored; the OPEN four are what makes a finding
# actionable. Anything outside this set is a typo, and a typo in a governance file reads as a rule.
ENTRY_OPTIONAL = {"unit", "register_item", "restriction", "withheld", "blocked_on"}
OPEN_REQUIRES = ("register_item", "restriction", "withheld", "blocked_on")
LEGAL_FORBIDS = ("register_item", "blocked_on")

TOP_REQUIRED = {"schema", "adjudicated_on", "adjudicated_against", "citation_adjudications"}

VERDICT_WORDS = ("TRUE", "FALSE")
RATE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent\b)|\bpass rate\b|\bgrade\b", re.IGNORECASE)


# --------------------------------------------------------------------------- what needs adjudicating


def needs_adjudication(assertions: list[dict], verdicts: dict[str, str],
                       restrictions: dict[str, set[str]]) -> list[dict]:
    """Every asserted pair a human has to rule on, with the rule that caught it.

    A pair with `asserted: None` is a citation of a case, not a claim about its verdict, and it is not
    adjudicated — the document names 87 distinct cases and most of those mentions assert nothing. The
    four arms below are disjoint by construction (first match wins) so one sentence cannot be counted
    as two findings, and every one of them is derived from the restriction sets rather than from a list
    of case ids.
    """
    out = []
    for a in assertions:
        case, asserted = a["case"], a["asserted"]
        if asserted is None:
            continue
        tags = restrictions.get(case, set())
        on_disk = verdicts.get(case)
        if on_disk != asserted:
            reason = f"the register says {on_disk} and the document asserts {asserted}"
            rule = "DISAGREES_WITH_REGISTER"
        elif tags & RESTRICTION_NEVER:
            reason = f"{sorted(tags & RESTRICTION_NEVER)} — its verdict may not be cited as one"
            rule = "NEVER_CITE"
        elif tags & RESTRICTION_CONTEXT_ONLY and asserted in VERDICT_WORDS:
            reason = f"{sorted(tags & RESTRICTION_CONTEXT_ONLY)} — not citable as a verdict"
            rule = "CONTEXT_ONLY"
        elif "PARTIAL" in tags and asserted in VERDICT_WORDS:
            reason = "PARTIAL — legal on one dimension and withheld on another"
            rule = "PARTIAL"
        elif tags & RESTRICTION_NOT_ESTABLISHED_ONLY and asserted in VERDICT_WORDS:
            reason = f"{sorted(tags & RESTRICTION_NOT_ESTABLISHED_ONLY)} — INCONCLUSIVE is not "
            reason += "evidence in either direction"
            rule = "NOT_EVIDENCE_AGAINST"
        else:
            continue
        out.append({**a, "rule": rule, "reason": reason,
                    "on_disk": on_disk, "restrictions": sorted(tags)})
    return out


def key(row: dict) -> tuple[str, str, str]:
    return (row["case"], row["asserted"], row["where"])


# --------------------------------------------------------------------------- the ledger


def check_shape(data: dict, f: Findings, ledger: Path = CURATION) -> list[dict]:
    if data.get("schema") != SCHEMA:
        die(f"{rel(ledger)} declares schema {data.get('schema')!r}, not {SCHEMA!r}")
    missing = TOP_REQUIRED - set(data)
    if missing:
        die(f"{rel(ledger)} is missing {sorted(missing)}")
    unknown = set(data) - TOP_REQUIRED
    if unknown:
        die(f"{rel(ledger)} carries unknown top-level key(s) {sorted(unknown)}")

    entries = data["citation_adjudications"]
    if not isinstance(entries, list) or not entries:
        die(f"{rel(ledger)} has no citation_adjudications; a ledger that reads empty and a "
            f"document with nothing to adjudicate are not the same state, and only one of them is "
            f"reachable by deleting a key")

    for i, e in enumerate(entries):
        at = f"entry #{i + 1}"
        if not isinstance(e, dict):
            f.add(at, f"is a {type(e).__name__}, not a mapping")
            continue
        at = f"{e.get('case')}/{e.get('asserted')}/{e.get('where')}"
        missing = ENTRY_REQUIRED - set(e)
        if missing:
            f.add(at, f"is missing {sorted(missing)}")
        unknown = set(e) - ENTRY_REQUIRED - ENTRY_OPTIONAL
        if unknown:
            f.add(at, f"carries unknown key(s) {sorted(unknown)}")
        # `asserted: TRUE` unquoted is the Python object `True` under YAML 1.1, not the string the
        # document wrote. Without this guard the symptom is a pair of contradictory-looking messages —
        # "no entry at all" for the real occurrence and "an exemption that outlives its sentence" for
        # the entry meant to cover it — which reads as two document defects instead of one missing
        # pair of quotes. The verdict words are exactly the two YAML 1.1 spells as booleans, so this
        # is not a hypothetical trap: it is the only way to write this field wrong.
        if not isinstance(e.get("asserted"), str):
            f.add(at, f"asserted is {type(e.get('asserted')).__name__}, not a string. YAML 1.1 reads "
                      f"bare TRUE/FALSE as booleans, and a verdict word is not a boolean here — it is "
                      f"the token the document prints. Quote it: asserted: \"TRUE\"")
        disposition = e.get("disposition")
        kind = DISPOSITIONS.get(disposition)
        if kind is None:
            f.add(at, f"disposition {disposition!r} is not one of {sorted(DISPOSITIONS)}")
        elif kind == "open":
            for k in OPEN_REQUIRES:
                if not e.get(k):
                    f.add(at, f"is {disposition} and must name {k!r}: an open finding that names no "
                              f"register item and no blocker is an exemption wearing a finding's name")
        else:
            for k in LEGAL_FORBIDS:
                if e.get(k):
                    f.add(at, f"is {disposition} and carries {k!r}; a citation ruled legal is not "
                              f"blocked on anything, and pretending it is hides what is")
        for k, floor in (("why", MIN_WHY), ("evidence", MIN_EVIDENCE)):
            v = e.get(k)
            if not isinstance(v, str) or len(v.strip()) < floor:
                f.add(at, f"{k!r} is {len(v.strip()) if isinstance(v, str) else 'not a string'}, "
                          f"under the floor of {floor} characters")
        frag = e.get("span_must_contain")
        if not isinstance(frag, dict) or set(frag) != {"en", "zh"}:
            f.add(at, "span_must_contain must be a mapping of exactly en and zh; a fragment quoted "
                      "in one edition leaves the other edition's sentence unchecked")
            continue
        for lang in ("en", "zh"):
            if not isinstance(frag[lang], str):
                f.add(at, f"span_must_contain.{lang} is not a string")
                continue
            w = practices_source.vwidth(frag[lang].strip())
            if w < MIN_FRAGMENT:
                f.add(at, f"span_must_contain.{lang} is {w} visual column(s), under the floor of "
                          f"{MIN_FRAGMENT}; a fragment that short can match a sentence it was not "
                          f"written about")
        if isinstance(frag["en"], str) and frag["en"].strip() == frag.get("zh", "").strip():
            f.add(at, "quotes the same fragment for both editions, so one of the two sentences is "
                      "unchecked — or the Chinese edition left it untranslated, which is a finding "
                      "of its own")
    return [e for e in entries if isinstance(e, dict)]


def match(occurrences: list[dict], entries: list[dict], f: Findings,
          ledger: Path = CURATION) -> list[dict]:
    """Pair each occurrence with the one entry that quotes it, and fail on anything left over.

    Matching on the fragment rather than on the key is what makes two sites in the same section
    distinguishable: §7.1 asserts F7-1 TRUE twice, about different metrics, and a key of
    `(case, verdict, section)` cannot tell those apart. It also means an entry cannot drift onto a
    sentence it was not written about, because the pairing fails rather than silently re-homing.
    """
    matched = []
    by_key: dict[tuple, list[dict]] = {}
    for e in entries:
        by_key.setdefault(key(e), []).append(e)
    used: list[int] = []
    for occ in occurrences:
        candidates = [e for e in by_key.get(key(occ), [])
                      if e["span_must_contain"]["en"] in occ["span"]["en"]
                      and e["span_must_contain"]["zh"] in occ["span"]["zh"]]
        where = f"{occ['case']}/{occ['asserted']}/{occ['where']}"
        if not candidates:
            same_key = by_key.get(key(occ), [])
            hint = ("no entry at all" if not same_key else
                    f"{len(same_key)} entry/entries with this key, none of whose quoted fragments "
                    f"is still in the sentence")
            f.add(where, f"{occ['rule']}: {occ['reason']} — and there is {hint}. English span: "
                         f"{occ['span']['en'][:200]!r}")
            continue
        if len(candidates) > 1:
            f.add(where, f"{len(candidates)} entries all quote this one sentence; the ledger cannot "
                         f"say which ruling applies to it")
            continue
        e = candidates[0]
        if id(e) in used:
            f.add(where, "shares its entry with another occurrence; one ruling cannot cover two "
                         "sentences, or the count of what is wrong is smaller than what is wrong")
            continue
        used.append(id(e))
        matched.append({**occ, "disposition": e["disposition"], "why": e["why"],
                        "evidence": e["evidence"],
                        "kind": DISPOSITIONS[e["disposition"]],
                        **{k: e[k] for k in ENTRY_OPTIONAL if k in e}})
    for e in entries:
        if id(e) not in used:
            f.add(f"{e['case']}/{e['asserted']}/{e['where']}",
                  f"is adjudicated in {ledger.name} but no such assertion occurs in the document "
                  f"any more (or its quoted fragment no longer appears in both editions). An "
                  f"exemption that outlives its sentence is how a fixed defect stays excused.")
    return matched


# --------------------------------------------------------------------------- the derivation itself


def check_derivation(design: dict, registered: set[str], f: Findings) -> None:
    """The parse's own internal consistency, and both directions of coverage."""
    n_sections = sum(s["n_practices"] for s in design["sections"])
    if n_sections != design["n_practices"]:
        f.add("practices", f"the sections account for {n_sections} practice(s) but {design['n_practices']} "
                           f"were extracted; a practice outside every section sits outside every count")
    keyed = [k for s in design["sections"] for k in s["keys"]]
    if sorted(keyed) != sorted(p["key"] for p in design["practices"]):
        f.add("practices", "the per-section key lists and the practice list are not the same set")
    if len(set(keyed)) != len(keyed):
        f.add("practices", "a practice key appears in two sections")

    cited = set(design["citation_census"]["cases"])
    unknown = sorted(cited - registered)
    if unknown:
        f.add("citations", f"the document cites {len(unknown)} case id(s) that are not in the sealed "
                           f"register: {unknown}. Either the register lost a case or the document has "
                           f"a typo, and a chip on the page would link to nothing either way.")
    uncited = sorted(registered - cited)
    if len(cited) + len(uncited) != len(registered):
        f.add("citations", "cited and uncited do not partition the register")
    if not uncited:
        f.add("citations", "every registered case is cited by the document, which has never been "
                           "true; the coverage-ceiling list would render as empty and say nothing")

    for p in design["practices"]:
        for lang in ("en", "zh"):
            if not p["prose"][lang].strip():
                f.add(p["key"], f"has empty {lang} prose after citation stripping")


def check_no_rate(path: Path, f: Findings) -> None:
    """No rate, percentage or grade in the authored ledger.

    The same rule the audit page is held to, applied to the file the page's caveats come from. A
    finding is a place the guidance did not hold, never a fraction of places it did.
    """
    for i, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if line.lstrip().startswith("#"):
            continue
        m = RATE_RE.search(line)
        if m:
            f.add(f"{path.name}:{i}", f"states {m.group(0)!r}; this platform publishes denominators, "
                                      f"not rates")


# --------------------------------------------------------------------------- the shared entry point


def adjudicate(curation: Path = CURATION) -> dict:
    """The whole picture, for the gate and for `build_site_data.py` to publish.

    One function, imported by both, so the page and the gate cannot disagree about which citations
    are open findings. Raises `SystemExit(2)` through `die()` on a malformed ledger; returns the
    findings list otherwise, so a caller decides whether a violation is fatal.
    """
    if not curation.is_file():
        die(f"{curation} does not exist")
    data = load_yaml_no_duplicate_keys(curation)
    design = practices_source.extract_files()
    registered, verdicts = read_verdicts()
    restrictions = read_restrictions()

    f = Findings()
    entries = check_shape(data, f, curation)
    occurrences = needs_adjudication(design["assertions"], verdicts, restrictions)
    matched = match(occurrences, entries, f, curation)
    check_derivation(design, registered, f)
    check_no_rate(curation, f)

    open_findings = [m for m in matched if m["kind"] == "open"]
    if len(open_findings) > MAX_OPEN_ADJUDICATIONS:
        f.add("ledger", f"{len(open_findings)} open finding(s) against a ceiling of "
                        f"{MAX_OPEN_ADJUDICATIONS}; the ceiling ratchets down only, so a new one "
                        f"must be fixed or the ceiling argued up in the same change")
    for m in open_findings:
        if not restrictions.get(m["case"], set()) & (RESTRICTION_NEEDS_SCOPE | RESTRICTION_NEVER
                                                     | RESTRICTION_CONTEXT_ONLY):
            f.add(m["case"], "is an open finding but carries no restriction in CITATION-POLICY, so "
                             "nothing downstream would render it as scope-bound")

    return {
        "design": design,
        "adjudications": matched,
        "occurrences": occurrences,
        "open_findings": open_findings,
        "adjudicated_on": data["adjudicated_on"],
        "adjudicated_against": data["adjudicated_against"],
        "n_registered": len(registered),
        "n_restricted": len(restrictions),
        "findings": f,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--practices", type=Path, default=CURATION)
    ap.add_argument("--json", action="store_true",
                    help="print the adjudicated findings as JSON instead of a summary")
    args = ap.parse_args(argv)

    try:
        result = adjudicate(args.practices)
    except practices_source.SourceError as exc:
        die(f"the design could not be read out of the two documents: {exc}")
        raise  # unreachable; die() exits

    design, f = result["design"], result["findings"]
    census = design["citation_census"]
    print(f"=== design citation gate\n    {result['n_registered']} registered case(s), "
          f"{result['n_restricted']} carrying a restriction")
    print(f"    {design['n_practices']} practice(s) in {len(design['sections'])} section(s), "
          f"{len(design['principles'])} principle(s), {len(design['anti_patterns'])} anti-pattern(s), "
          f"{design['n_checklist_items']} checklist item(s)")
    print(f"    {census['n_citations']} citation(s) over {census['n_distinct']} distinct case(s), "
          f"identical in both editions; {design['n_assertions']} of them assert a verdict")
    print(f"    {len(result['occurrences'])} assertion(s) needed a human ruling, "
          f"{len(result['adjudications'])} matched an entry, "
          f"{len(result['open_findings'])} of those are OPEN findings "
          f"(ceiling {MAX_OPEN_ADJUDICATIONS})")
    for m in result["adjudications"]:
        print(f"      {m['disposition']:34s} {m['case']:6s} {m['asserted']:6s} §{m['where']}")

    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k not in ("design", "findings")},
                         indent=2, sort_keys=True, ensure_ascii=False))

    return f.report(f"{len(result['adjudications'])} adjudicated citation(s) in "
                    f"{args.practices.name}")


if __name__ == "__main__":
    sys.exit(main())
