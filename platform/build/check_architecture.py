#!/usr/bin/env python3
"""Curation gate for `platform/curation/architecture.yaml` — the two diagrams' authored topology.

WHAT THIS GATE IS FOR
=====================

An architecture diagram is the most quotable thing a project makes. It travels without the text beside
it, it is read as authoritative, and a reader who takes one wrong colour away from it takes it away
permanently. So the file that authors the topology is held to the same standard as a verdict file:
every case it names exists, every box either cites cases or says in writing that nothing was measured,
and the union of what the diagrams cover and what they explicitly do not must equal the register.

WHY IT CHECKS THE AUTHORED FILE AND NOT THE PAYLOAD

`build_site_data.derive_architecture()` derives the colours; this gate checks the judgments that go
INTO that derivation. The two are complementary and neither replaces the other:
`check_site_invariants.py` re-checks the emitted `architecture.json` against `census.json`, so a stale
or hand-edited payload fails there. Here the subject is the YAML a human wrote.

WHY IT IMPORTS THE STATUS RULE INSTEAD OF RESTATING IT

`check_controls.py` deliberately keeps its own YAML loader rather than importing the builder's, on the
principle that a gate which imports the builder cannot fail the builder. That principle applies to a
gate checking the builder's OUTPUT. This gate checks an authored input, and the status rule
(`box_status`) is a citation rule — the one kind of thing this repository must never hold two copies
of, because the weaker copy wins by being the one that ran. So it is imported, and
`check_the_two_modules_agree_on_which_restrictions_disqualify_a_case` asserts that the imported set is
identical to the partition `check_controls.py` applies to a control's findings. A divergence between
the two files fails this gate rather than producing two differently-coloured views of one verdict.

WHY NO CASE ID APPEARS IN THIS FILE
===================================

Same reason as `check_controls.py`: which cases are non-citable is stated by
`results/CITATION-POLICY.md`, which declares itself authoritative for tooling. A gate with `F5-3b`
typed into it would go vacuous the day the policy moved that restriction, and would enforce a stale
rule in the meantime (`feedback_scope_as_namelist`).

EXIT CODES
==========

0 clean. 2 for findings, and for an input so broken the rules cannot run. Never 1: that is what a
Python traceback exits with, and a crash must not be readable as "one finding".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CURATION = ROOT / "platform" / "curation" / "architecture.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_controls as cc  # noqa: E402  - its loader, register reader and restriction reader
from build_site_data import ARCH_NON_COLOURING, box_status  # noqa: E402  - the one status rule

SCHEMA = "grx-architecture/1"

# Floors. A gate that passes over an empty file has told you nothing
# (`feedback_zero_file_scan_is_error`).
MIN_DIAGRAMS = 2
MIN_BOXES = 12
MIN_EDGES = 12

# Minimum lengths for the authored prose. Every one of these fields is a judgment a machine cannot
# supply, and a one-word placeholder is the shape a forgotten justification takes.
MIN_WHY = 40
MIN_DETAIL = 60
MIN_WHY_NOT_MEASURED = 60
MIN_SUBTITLE = 60
MIN_WHY_DIAGRAM = 120

TOP_KEYS = {"schema", "vocabularies", "diagrams", "unplaced_cases", "mapped_by", "mapped_on", "note"}
VOCAB_KEYS = {"kind", "venv", "machine", "edge_kind", "count_from"}
DIAGRAM_KEYS = {"id", "label", "subtitle", "why_this_diagram", "boxes", "edges"}
BOX_KEYS = {"id", "label", "detail", "kind", "program", "venv", "machine", "cases",
            "why_these_cases", "measured", "why_not_measured", "count_from"}
EDGE_KEYS = {"from", "to", "kind", "label"}
UNPLACED_KEYS = {"case", "why"}

# Keys the BUILDER computes. Present in the authored file they would be a second source of truth for
# a verdict or a coordinate, and the diagram's copy is the one a reader would remember. Named
# explicitly rather than left to the allowlist so the message can say why.
FORBIDDEN_BOX_KEYS = {
    "verdict": "a verdict is read from results/phase1/ at build time",
    "verdicts": "as above",
    "status": "derived by box_status() from the cases' verdicts and restrictions",
    "colour": "derived from the status",
    "color": "derived from the status",
    "badge": "derived from the citation policy",
    "restrictions": "read from results/CITATION-POLICY.md",
    "n_cases": "counted from `cases`",
    "count": "computed from the metric named by `count_from`",
    "x": "the layout is computed from the edges, never authored",
    "y": "as above",
    "row": "as above",
    "column": "as above",
    "layer": "as above",
}

# `measured: none` is the only value the key may take. A truthy value would be a claim about a
# measurement in the file whose whole point is that measurements are read from elsewhere.
MEASURED_NONE = "none"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--architecture", type=Path, default=CURATION)
    args = ap.parse_args(argv)

    f = cc.Findings()
    data = cc.load_yaml_no_duplicate_keys(args.architecture)
    registered, verdicts = cc.read_verdicts()
    restrictions = cc.read_restrictions()

    check_rule_sets_agree(f)
    vocab = check_shape(data, f)
    diagrams = data.get("diagrams") if isinstance(data.get("diagrams"), list) else []

    placed: dict[str, list[str]] = {}
    used: dict[str, set[str]] = {k: set() for k in VOCAB_KEYS}
    for d in diagrams:
        if not isinstance(d, dict) or not d.get("id"):
            f.add(cc.rel(args.architecture), "a diagram has no `id`; an unidentified diagram sits "
                                             "outside every count on the page")
            continue
        check_diagram(d, vocab, used, registered, verdicts, restrictions, placed, f)

    check_vocabulary_is_used(vocab, used, f)
    unplaced = check_unplaced(data, registered, f)
    check_coverage(registered, placed, unplaced, restrictions, f)

    if not placed:
        cc.die(f"{cc.rel(args.architecture)} places zero cases on zero diagrams. Every legality rule "
               f"in this gate would then pass over an empty set.")
    return f.report(f"{cc.rel(args.architecture)}: {len(diagrams)} diagram(s), "
                    f"{len(placed)} case(s) placed, {len(unplaced)} explicitly unplaced")


# --------------------------------------------------------------------------------- shape


def check_rule_sets_agree(f: cc.Findings) -> None:
    """The imported colouring rule must be the same partition this repository's other gate applies.

    Not a tautology and not decoration: `check_controls.py` decides whether a case may carry a
    control's finding, and `box_status` decides whether it may colour an architecture box. Those are
    the same question about the same restriction table, so a divergence means one of the two views
    is citing a verdict the other refuses — and the diagram is the view that gets quoted.
    """
    expected = cc.RESTRICTION_NEVER | cc.RESTRICTION_CONTEXT_ONLY
    if ARCH_NON_COLOURING != expected:
        f.add("rule sets", f"build_site_data.ARCH_NON_COLOURING is {sorted(ARCH_NON_COLOURING)} but "
                           f"check_controls disqualifies {sorted(expected)}. Two copies of one "
                           f"citation rule means one view colours a box from a verdict the other "
                           f"refuses to cite.")
    unknown = ARCH_NON_COLOURING - cc.KNOWN_RESTRICTIONS
    if unknown:
        f.add("rule sets", f"{sorted(unknown)} is not in the citation policy's known vocabulary")


def check_shape(data: dict, f: cc.Findings) -> dict:
    if data.get("schema") != SCHEMA:
        f.add("schema", f"is {data.get('schema')!r}, not {SCHEMA!r}. A consumer keyed on the schema "
                        f"would render an unknown shape as an empty diagram.")
    extra = sorted(set(data) - TOP_KEYS)
    if extra:
        f.add("top level", f"unknown key(s) {extra}. A typo'd key is silently ignored, so an "
                           f"unknown one is reported rather than tolerated.")
    for key in ("mapped_by", "mapped_on", "note"):
        if not str(data.get(key) or "").strip():
            f.add("top level", f"`{key}` is empty. An authored judgment with no author and no date "
                               f"cannot be reviewed, and this file is changed by review.")

    vocab = data.get("vocabularies")
    if not isinstance(vocab, dict):
        cc.die("`vocabularies` is missing or is not a mapping. Without it every value in the file is "
               "unconstrained, and an unconstrained value is one nothing can reject.")
    missing = sorted(VOCAB_KEYS - set(vocab))
    if missing:
        cc.die(f"`vocabularies` declares no {missing}; the rules below would pass over an open set")
    extra_v = sorted(set(vocab) - VOCAB_KEYS)
    if extra_v:
        f.add("vocabularies", f"declares {extra_v}, which no rule reads. A vocabulary nothing "
                              f"enforces makes the file look more constrained than it is.")
    for key in sorted(VOCAB_KEYS):
        if not isinstance(vocab.get(key), list) or not vocab[key]:
            f.add(f"vocabularies.{key}", "is not a non-empty list")

    diagrams = data.get("diagrams")
    if not isinstance(diagrams, list) or len(diagrams) < MIN_DIAGRAMS:
        cc.die(f"`diagrams` holds {len(diagrams) if isinstance(diagrams, list) else 'no'} entries, "
               f"below the floor of {MIN_DIAGRAMS}")
    return vocab


# --------------------------------------------------------------------------------- diagrams


def check_diagram(d: dict, vocab: dict, used: dict[str, set[str]], registered: set[str],
                  verdicts: dict[str, str], restrictions: dict[str, set[str]],
                  placed: dict[str, list[str]], f: cc.Findings) -> None:
    where = f"diagram {d['id']}"
    extra = sorted(set(d) - DIAGRAM_KEYS)
    if extra:
        f.add(where, f"unknown key(s) {extra}")
    if not str(d.get("label") or "").strip():
        f.add(where, "has no `label`")
    if len(str(d.get("subtitle") or "").strip()) < MIN_SUBTITLE:
        f.add(where, f"`subtitle` is under {MIN_SUBTITLE} characters. It is the sentence that tells a "
                     f"reader how to read the picture; without it they invent a reading.")
    if len(str(d.get("why_this_diagram") or "").strip()) < MIN_WHY_DIAGRAM:
        f.add(where, f"`why_this_diagram` is under {MIN_WHY_DIAGRAM} characters. A diagram nobody had "
                     f"to justify is a diagram whose scope nobody chose.")

    boxes = d.get("boxes")
    if not isinstance(boxes, list) or len(boxes) < MIN_BOXES:
        f.add(where, f"holds {len(boxes) if isinstance(boxes, list) else 'no'} box(es), below the "
                     f"floor of {MIN_BOXES}")
        return
    by_id: dict[str, dict] = {}
    seen_case: dict[str, str] = {}
    for b in boxes:
        if not isinstance(b, dict) or not b.get("id"):
            f.add(where, "holds a box with no `id`")
            continue
        if b["id"] in by_id:
            f.add(where, f"defines box {b['id']} twice")
        by_id[b["id"]] = b
        check_box(b, where, vocab, used, registered, verdicts, restrictions, seen_case, f)
        for c in b.get("cases") or []:
            placed.setdefault(c, []).append(f"{d['id']}/{b['id']}")

    check_edges(d, by_id, vocab, used, f)


def check_box(b: dict, where: str, vocab: dict, used: dict[str, set[str]], registered: set[str],
              verdicts: dict[str, str], restrictions: dict[str, set[str]],
              seen_case: dict[str, str], f: cc.Findings) -> None:
    at = f"{where}/{b['id']}"
    for key, why in sorted(FORBIDDEN_BOX_KEYS.items()):
        if key in b:
            f.add(at, f"authors `{key}`, which is derived, not authored ({why}). A derived value in "
                      f"this file is a second source of truth for it, and the diagram's copy is the "
                      f"one a reader remembers.")
    extra = sorted(set(b) - BOX_KEYS - set(FORBIDDEN_BOX_KEYS))
    if extra:
        f.add(at, f"unknown key(s) {extra}")

    if not str(b.get("label") or "").strip():
        f.add(at, "has no `label`")
    if len(str(b.get("detail") or "").strip()) < MIN_DETAIL:
        f.add(at, f"`detail` is under {MIN_DETAIL} characters. The box itself shows a label; the "
                  f"detail is the only place a reader learns what the component actually is.")
    for key in ("kind", "venv", "machine"):
        val = b.get(key)
        if val is None:
            f.add(at, f"has no `{key}`. A default here would be an unauthored classification.")
        elif val not in (vocab.get(key) or []):
            f.add(at, f"has {key}={val!r}, outside the declared vocabulary {vocab.get(key)}")
        else:
            used[key].add(val)
    metric = b.get("count_from")
    if metric is not None:
        if metric not in (vocab.get("count_from") or []):
            f.add(at, f"has count_from={metric!r}, outside the declared vocabulary")
        else:
            used["count_from"].add(metric)

    program = b.get("program")
    if program is not None:
        # A path, not a name. `census.py` lives at the repository root and `day2_replicate.py` under
        # `tools/`; a bare name would make this check a search, and a search can match the wrong file.
        if not (ROOT / str(program)).is_file():
            f.add(at, f"names program {program!r}, which is not a file in this repository. A box "
                      f"naming a program a reader cannot open is a box asserting machinery that may "
                      f"not exist.")

    cases = b.get("cases") or []
    measured = b.get("measured")
    if cases and measured is not None:
        f.add(at, f"carries both `cases` and `measured: {measured!r}`. Exactly one is true of a box, "
                  f"and a box claiming both leaves a reader to choose.")
    if not cases and measured is None:
        f.add(at, "has neither `cases` nor `measured: none`. A box with no cases and no statement "
                  "that nothing was measured renders as uncoloured, which reads as 'nothing to worry "
                  "about' — the one thing it does not mean.")
    if cases:
        if len(str(b.get("why_these_cases") or "").strip()) < MIN_WHY:
            f.add(at, f"`why_these_cases` is under {MIN_WHY} characters. Which cases are ABOUT a "
                      f"component is the judgment this whole file exists to record.")
        if len(set(cases)) != len(cases):
            f.add(at, "names a case twice, which would double-count it in the coverage census")
        for c in cases:
            if c not in registered:
                f.add(at, f"names {c}, which is not in the sealed register")
                continue
            if c in seen_case:
                f.add(at, f"names {c}, already placed on {seen_case[c]} in this diagram. One case "
                          f"colouring two boxes of one picture says the same evidence twice.")
            seen_case[c] = b["id"]
            if cc.RESTRICTION_NEVER & restrictions.get(c, set()):
                f.add(at, f"places {c}, which the citation policy marks "
                          f"{sorted(cc.RESTRICTION_NEVER & restrictions[c])}. It may be cited as "
                          f"nothing at all, so it belongs in `unplaced_cases` with the reason.")
    else:
        if measured != MEASURED_NONE:
            f.add(at, f"has measured={measured!r}; the only permitted value is {MEASURED_NONE!r}")
        if len(str(b.get("why_not_measured") or "").strip()) < MIN_WHY_NOT_MEASURED:
            f.add(at, f"`why_not_measured` is under {MIN_WHY_NOT_MEASURED} characters. An unmeasured "
                      f"box is the most easily misread state on the diagram and it is the one that "
                      f"most needs a sentence.")

    check_status(b, at, verdicts, restrictions, f)


def check_status(b: dict, at: str, verdicts: dict[str, str], restrictions: dict[str, set[str]],
                 f: cc.Findings) -> None:
    """Re-state the colouring rule in terms of VERDICT STRINGS, over the same shared function.

    Not a tautology: `box_status` decides by walking its own precedence, and these arms say what the
    answer must look like from outside — a green box needs a citable TRUE, a box supported only by
    restricted cases may not be green or red, and an INCONCLUSIVE-only box may never read as
    validated. If somebody folds INCONCLUSIVE into TRUE inside the rule, this fires.
    """
    annotated = [{"case": c, "verdict": verdicts.get(c),
                  "restrictions": sorted(restrictions.get(c, set()))}
                 for c in (b.get("cases") or [])]
    status, _ = box_status(annotated)
    citable = [c for c in annotated if c["verdict"] and not (set(c["restrictions"])
                                                            & ARCH_NON_COLOURING)]
    if status == "validated_in_part" and not any(c["verdict"] == "TRUE" for c in citable):
        f.add(at, f"computes as validated_in_part with no citable TRUE verdict among "
                  f"{[c['case'] for c in annotated]}")
    if status == "contested" and not any(c["verdict"] == "FALSE" for c in citable):
        f.add(at, f"computes as contested with no citable FALSE verdict among "
                  f"{[c['case'] for c in annotated]}")
    if annotated and not citable and status in {"validated_in_part", "contested"}:
        f.add(at, f"computes as {status} although every case on it carries a restriction in "
                  f"{sorted(ARCH_NON_COLOURING)}. A restricted case may be a box's only support and "
                  f"still colour nothing.")
    if citable and all(c["verdict"] == "INCONCLUSIVE" for c in citable) and \
            status == "validated_in_part":
        f.add(at, "computes as validated_in_part on INCONCLUSIVE support only. An INCONCLUSIVE "
                  "verdict is not evidence against a claim and licenses no amendment, so it may "
                  "never colour a box as validated.")


def check_edges(d: dict, by_id: dict[str, dict], vocab: dict, used: dict[str, set[str]],
                f: cc.Findings) -> None:
    where = f"diagram {d['id']}"
    edges = d.get("edges")
    if not isinstance(edges, list) or len(edges) < MIN_EDGES:
        f.add(where, f"holds {len(edges) if isinstance(edges, list) else 'no'} edge(s), below the "
                     f"floor of {MIN_EDGES}. A diagram with no arrows asserts no relations, and the "
                     f"relations are what a topology IS.")
        return

    seen: set[tuple[str, str]] = set()
    indeg: dict[str, int] = {b: 0 for b in by_id}
    outdeg: dict[str, int] = {b: 0 for b in by_id}
    adj: dict[str, list[str]] = {b: [] for b in by_id}
    for e in edges:
        if not isinstance(e, dict):
            f.add(where, f"holds an edge that is not a mapping: {e!r}")
            continue
        extra = sorted(set(e) - EDGE_KEYS)
        if extra:
            f.add(where, f"edge {e.get('from')}->{e.get('to')} has unknown key(s) {extra}")
        a, b = e.get("from"), e.get("to")
        bad = [end for end, v in (("from", a), ("to", b)) if v not in by_id]
        if bad:
            f.add(where, f"edge {a}->{b} has {bad} naming no box in this diagram. An arrow to "
                         f"nothing is an arrow a reader completes themselves.")
            continue
        if a == b:
            f.add(where, f"edge {a}->{b} is a self-edge")
            continue
        if (a, b) in seen:
            f.add(where, f"edge {a}->{b} is declared twice; the second is drawn over the first")
        seen.add((a, b))
        if not str(e.get("label") or "").strip():
            f.add(where, f"edge {a}->{b} has no `label`. An unlabelled arrow says only that two "
                         f"things are related, which the reader could already see.")
        kind = e.get("kind")
        if kind not in (vocab.get("edge_kind") or []):
            f.add(where, f"edge {a}->{b} has kind={kind!r}, outside the declared vocabulary")
        else:
            used["edge_kind"].add(kind)
        indeg[b] += 1
        outdeg[a] += 1
        adj[a].append(b)

    for bid, box in sorted(by_id.items()):
        if indeg[bid] + outdeg[bid] == 0:
            f.add(f"{where}/{bid}", "has no edge at all. An unconnected box is on the picture without "
                                    "being part of it, and a reader cannot tell whether that is a "
                                    "claim or an oversight.")
        if box.get("kind") == "property":
            # The rule the crossing-free layout rests on. A property with two parents, or with a
            # child, cannot be placed in one row beside one parent, and the layout would then have to
            # route an edge across the spine — which is where the crossings come from.
            if indeg[bid] != 1:
                f.add(f"{where}/{bid}", f"is kind: property with {indeg[bid]} incoming edge(s), not "
                                        f"exactly 1. A property is a property OF one component, and "
                                        f"the layout places it in that component's row.")
            if outdeg[bid] != 0:
                f.add(f"{where}/{bid}", f"is kind: property with {outdeg[bid]} outgoing edge(s). A "
                                        f"property is a leaf; an arrow out of one makes it a stage.")
            for parent, kids in adj.items():
                if bid in kids and by_id[parent].get("kind") == "property":
                    f.add(f"{where}/{bid}", f"hangs off {parent}, which is itself a property")

    # Acyclicity, over every box. A pipeline diagram asserts an ORDER — sealed before measured,
    # replicated before amended — and a cycle means it no longer states one.
    colour: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        colour[node] = 1
        for nxt in adj[node]:
            if colour.get(nxt) == 1:
                f.add(where, f"has a cycle: {' -> '.join([*path, node, nxt])}")
            elif colour.get(nxt) is None:
                visit(nxt, [*path, node])
        colour[node] = 2

    for bid in sorted(by_id):
        if colour.get(bid) is None:
            visit(bid, [])


def check_vocabulary_is_used(vocab: dict, used: dict[str, set[str]], f: cc.Findings) -> None:
    """Both directions, for the four vocabularies that CLASSIFY something.

    `kind`, `venv`, `machine` and `edge_kind` label boxes and edges. A value declared there and used
    nowhere is a rule that can never fire, and it makes the file read as covering ground it does not —
    a declared `.venv-agentcore` asserts a virtual environment some step runs in, and the assertion
    outlives the step.

    `count_from` is exempt, and not because checking it is inconvenient. It is not a classification: it
    is the closed set of derived numbers the BUILDER can supply, and `derive_architecture()` already
    checks it in both directions against the metric table — declaring a metric the builder cannot
    compute kills the build, and computing one this file does not declare kills it too. Requiring each
    metric to appear on a box would say something different and false: that a number worth computing is
    a number worth putting in a box. A metric the diagrams do not display is still a metric the payload
    carries, and the count of either is a derived number this docstring has no business asserting.
    """
    for key in sorted(VOCAB_KEYS - {"count_from"}):
        unused = sorted(set(vocab.get(key) or []) - used[key])
        if unused:
            f.add(f"vocabularies.{key}", f"declares {unused}, which no box or edge uses")


# --------------------------------------------------------------------------------- coverage


def check_unplaced(data: dict, registered: set[str], f: cc.Findings) -> dict[str, str]:
    out: dict[str, str] = {}
    entries = data.get("unplaced_cases")
    if not isinstance(entries, list):
        cc.die("`unplaced_cases` is missing or is not a list. It is required even when empty: the "
               "coverage claim is checked in both directions and there is no direction without it.")
    for u in entries:
        if not isinstance(u, dict) or not u.get("case"):
            f.add("unplaced_cases", f"an entry has no `case`: {u!r}")
            continue
        extra = sorted(set(u) - UNPLACED_KEYS)
        if extra:
            f.add(f"unplaced_cases/{u['case']}", f"unknown key(s) {extra}")
        if u["case"] in out:
            f.add("unplaced_cases", f"lists {u['case']} twice")
        if u["case"] not in registered:
            f.add("unplaced_cases", f"lists {u['case']}, which is not in the sealed register")
        if len(str(u.get("why") or "").strip()) < MIN_WHY:
            f.add(f"unplaced_cases/{u['case']}", f"`why` is under {MIN_WHY} characters. An omission "
                                                 f"with no stated reason is indistinguishable from an "
                                                 f"oversight, and that is what this list exists to "
                                                 f"distinguish.")
        out[u["case"]] = str(u.get("why") or "")
    return out


def check_coverage(registered: set[str], placed: dict[str, list[str]], unplaced: dict[str, str],
                   restrictions: dict[str, set[str]], f: cc.Findings) -> None:
    """Placed ∪ unplaced == the register, and the two disjoint. Both directions are load-bearing.

    A diagram is a claim about coverage whether or not it admits one. Without the ceiling a case
    joining the register later would appear on no diagram and in no list — invisible by construction,
    which is the failure mode this repository is built against (`feedback_unnumbered_is_uncounted`).
    """
    both = sorted(set(placed) & set(unplaced))
    neither = sorted(registered - set(placed) - set(unplaced))
    ghosts = sorted((set(placed) | set(unplaced)) - registered)
    if both:
        f.add("coverage", f"{both} are placed on a diagram AND listed as unplaced. A reader sees only "
                          f"the friendlier of two answers.")
    if neither:
        f.add("coverage", f"{neither} are in the register and are neither placed nor explicitly "
                          f"unplaced. Every registered case must appear on a diagram or be listed "
                          f"with a reason.")
    if ghosts:
        f.add("coverage", f"{ghosts} appear in this file and not in the register")

    # And the specific direction the citation policy cares about: a NEVER_CITE case must be accounted
    # for out loud, because dropping it silently is the friendlier-looking mistake.
    for case, rs in sorted(restrictions.items()):
        if cc.RESTRICTION_NEVER & rs and case not in unplaced:
            f.add("coverage", f"{case} carries {sorted(cc.RESTRICTION_NEVER & rs)} and is not listed "
                              f"in `unplaced_cases`. A case that may be cited as nothing must be "
                              f"excluded in writing, not by absence.")


if __name__ == "__main__":
    raise SystemExit(main())
