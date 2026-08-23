#!/usr/bin/env python3
"""Read the design — the 45 numbered best practices — out of the two v1.4 documents.

WHY THIS FILE CONTAINS NO SENTENCE ABOUT GUARDRAILS

The site publishes the *evidence*: 91 verdicts, two diagrams, an audit. The design those verdicts
were collected about lives in `agentcore_guardrails_best_practices_v1.4.md` and its zh-TW edition.
Publishing the design means one of two things, and only one of them is defensible:

  * copy the practice sentences into this repository and render those, or
  * read them out of the documents at build time and render what the documents say today.

The first is a second source of truth for the thing the whole study is about. It drifts silently —
the document gets an amendment, the page keeps the old sentence, and the page is the artifact people
quote. So every practice sentence on the new page is READ, in both languages, from the two editions,
whose sha256 this build records as inputs like any other input. There is no practice prose in this
repository, and a diff of the two documents is the only way to change a word of it.

WHAT IS DERIVED, AND HOW IT IS PROVEN RATHER THAN LOCATED

A locator ("the list after the 4th bold line in §3.1") is authored, unverifiable, and silently wrong
after any edit. Every structure below is instead derived and cross-checked between the two editions:

  * **The practices block.** In each of §3.1–§5.3 the practices are the one numbered list introduced
    by a bold-only label line. Several sections carry more than one such list (§5.3 has
    `**Capabilities …**` before `**Best Practices:**`), so the label itself is derived: the label that
    introduces such a list in the MOST sections wins, and it must be a strict unique maximum over at
    least `MIN_MARKER_SECTIONS` sections. In the English edition that is `Best Practices` (9 sections
    against the runner-up's 1); in the Chinese edition, `最佳實踐` (9 against 1). Neither string is
    typed here. A translated marker in this file would be a locator in a language this file cannot
    check, and the day the Chinese edition rewords its label the extractor would return an empty list
    and the page would render as "no practices" rather than fail.
  * **Phase** comes from the chapter heading, which carries `BEFORE` / `DURING` / `AFTER` in Latin
    letters in BOTH editions — asserted, not assumed: the two editions must agree per section.
  * **Hop** comes from `Hop #<n>` in the section heading, also Latin in both editions and also
    asserted to agree. Sections whose heading names no hop (§4.3, §5.2, §5.3) carry `None`; that is a
    fact about the document, not a gap to fill in.
  * **Citations** are found with `mdsource.CASE_ID`, the deck builder's own case-id pattern, so the
    site and the decks agree on what a citation is. A case id followed by a file extension is a
    **path reference** (`results/phase1/F1-15.json`), not a citation, and those are counted and
    reported rather than dropped in silence.

THE HOOK IS TWO-LEVEL, BECAUSE THAT IS WHAT THE DOCUMENT DOES

Measured over v1.4: 324 citations, 87 distinct cases, identical multisets in both editions — and only
15 of those citations sit inside a practice sentence, across 9 of the 45 practices. A one-level `cites`
field per practice would therefore report 36 of the 45 as having no evidence, which is true of the
sentence and false of the hop: §3.2's five practices carry no inline citation while the section around
them cites 11 distinct cases. So both levels are emitted and neither is inferred from the other:
`cites` per practice, `section_cites` per section, each with its own count. The two are separate
claims — 15 citations and 9 practices — and inferring either from the other is how "15 practices have
evidence" gets written.

WHAT A `verdict` WORD NEXT TO A CASE ID MEANS

The document writes `[verified F4-2, TRUE, n=120, …]`. That TRUE is the document's own assertion about
a case, and `platform/build/check_practices.py` checks every one of them against `results/phase1/`.
This module only *pairs* them — a verdict word binds to the nearest preceding case id inside the same
bracket span — and records the pair. Adjudicating a disagreement is a judgment and is not made here.

EXIT

Imported by `platform/build/build_site_data.py` (which owns the hashing and the annotation with
verdicts) and by `platform/build/check_practices.py` (which owns the legality and coverage rules).
Run directly it prints what it derived, which is how the numbers in
`results/PRACTICE-EVIDENCE-MAP.md` were measured.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from deckgen.mdsource import (  # noqa: E402  (vwidth is re-exported: `check_practices.py` measures a
                               # quoted fragment in visual columns, and a second width function for the
                               # same documents would be a second answer)
    CASE_ID,
    _balanced_spans,
    clean_cell,
    read_tables_from_lines,
    strip_citations,
    vwidth,  # noqa: F401 - re-exported for check_practices.py's column floor
)

EN_DOC = ROOT / "agentcore_guardrails_best_practices_v1.4.md"
ZH_DOC = ROOT / "agentcore_guardrails_best_practices_v1.4.zh-TW.md"

# The three phase chapters. §6 (latency), §7 (summary), §8 (checklist) are read too, but only §3–§5
# hold the numbered practices, and the marker derivation must not be diluted by a numbered list in a
# chapter that has no practices at all.
PHASE_CHAPTERS = ("3", "4", "5")
PHASE_TOKENS = ("BEFORE", "DURING", "AFTER")

CHAPTER_RE = re.compile(r"^## (\d+)\.\s*(.*)$")
SECTION_RE = re.compile(r"^### (\d+\.\d+)\s*(.*)$")
# `## Appendix D: …` / `## 附錄 D:…` — the letter is Latin in both editions, and it is the only part
# of an appendix heading that is. Anything else here would be a translated locator.
APPENDIX_RE = re.compile(r"^## [^0-9]*\b([A-Z])\s*[:：]")
SUBSECTION_RE = re.compile(r"^#{4,6} ")
# A label line and nothing else: `**Best Practices:**`. The trailing colon is optional and is not
# part of the derived marker, so a colon added or removed in one edition cannot desynchronise them.
BOLD_LABEL_RE = re.compile(r"^\*\*(.+?):?\*\*$")
ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")
CHECK_RE = re.compile(r"^- \[[ xX]\]\s+(.*)$")
HOP_RE = re.compile(r"Hop #(\d+(?:-[A-Za-z]+)?)")
VERDICT_RE = re.compile(r"\b(TRUE|FALSE|INCONCLUSIVE|RECORDED)\b")
# What makes a case id a filename rather than a citation. Deliberately narrow — an extension
# immediately after the id — because the obvious wider rule (expand to the surrounding
# non-whitespace token and look for a `/`) is language-dependent: Chinese runs a whole clause together
# with no spaces, so it swallowed `2026-08-11/12;F7-1,` and reported 304 citations against English's
# 320. The parity assertion below is what caught that, and it is why the rule is this one.
PATH_EXT_RE = re.compile(r"\.(json|md|yaml|yml|py|csv|txt)\b")
# What may sit between two case ids for them to still be one list sharing one verdict. `\w` covers CJK
# as well as Latin, so "not a word character and not a digit" is the same rule in both editions —
# `F6-1、F6-2` is a run and `F6-1, n=1000, F6-2` is not.
RUN_GAP_RE = re.compile(r"[^\w]*")

# Floors, all far below today's values and far above "the parser broke". A structural extractor that
# returns almost nothing produces a page that reads as "there is not much to say".
MIN_PRACTICES = 40
MIN_MARKER_SECTIONS = 6
MIN_PRINCIPLES = 5
MIN_ANTI_PATTERNS = 5
MIN_CHECKLIST_ITEMS = 20
MIN_CITATIONS = 250


class SourceError(RuntimeError):
    """A structure this module claims to derive could not be derived. Never a warning."""


def _fail(msg: str) -> None:
    raise SourceError(msg)


# --------------------------------------------------------------------------------------- scanning


def _unfenced(text: str) -> list[tuple[int, str]]:
    """`(1-based line number, line)` for every line outside a ```-fenced block.

    Fenced blocks are skipped rather than filtered later because §5.1's practices are interrupted by
    a `mermaid` diagram and a paragraph of prose between items 1 and 2. A scanner that ends a list at
    the first line that is not an item reported that section as having ONE practice instead of six,
    and the total as 40 instead of 45 — a truncation that looks exactly like a document with fewer
    practices in it.
    """
    out = []
    fenced = False
    for i, line in enumerate(text.split("\n"), 1):
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append((i, line))
    return out


class Section:
    """One `### n.m` section, with the chapter context a reader of the heading alone would miss."""

    def __init__(self, sid: str, chapter: str, phase: str | None, heading: str, line: int) -> None:
        self.id = sid
        self.chapter = chapter
        self.phase = phase
        self.heading = heading
        self.line = line
        self.hop = (HOP_RE.search(heading).group(1) if HOP_RE.search(heading) else None)
        self.lines: list[tuple[int, str]] = []


def _sections(text: str) -> tuple[list[Section], dict[str, list[tuple[int, str]]]]:
    """Every section, in document order, plus the lines of each chapter that precede its sections."""
    sections: list[Section] = []
    chapters: dict[str, list[tuple[int, str]]] = {}
    cur: Section | None = None
    chapter = phase = None
    for lineno, line in _unfenced(text):
        m = CHAPTER_RE.match(line)
        if m:
            cur = None
            chapter = m.group(1)
            found = [t for t in PHASE_TOKENS if re.search(rf"\b{t}\b", m.group(2))]
            if len(found) > 1:
                _fail(f"line {lineno}: chapter heading names {found}; a chapter belongs to one phase")
            phase = found[0] if found else None
            chapters.setdefault(chapter, [])
            continue
        m = SECTION_RE.match(line)
        if m:
            cur = Section(m.group(1), chapter, phase, m.group(2), lineno)
            sections.append(cur)
            continue
        if cur is not None:
            cur.lines.append((lineno, line))
        elif chapter is not None:
            chapters[chapter].append((lineno, line))
    return sections, chapters


def _labelled_lists(lines: list[tuple[int, str]]) -> list[tuple[str, list[tuple[int, str]]]]:
    """Numbered lists introduced by a bold-only label line, as `(label, [(line, text)])`.

    An item is collected only when its ordinal is exactly the next one expected, so a nested list or
    a second list restarting at 1 cannot extend the first. Everything between two items — a diagram,
    a paragraph, a table — belongs to the item above it and is skipped, which is what lets §5.1 parse.
    """
    out: list[tuple[str, list[tuple[int, str]]]] = []
    for k, (_, line) in enumerate(lines):
        label = BOLD_LABEL_RE.match(line.strip())
        if not label:
            continue
        j = k + 1
        while j < len(lines) and not lines[j][1].strip():
            j += 1
        if j >= len(lines) or not ITEM_RE.match(lines[j][1]) or ITEM_RE.match(lines[j][1]).group(1) != "1":
            continue
        items: list[tuple[int, str]] = []
        want = 1
        while j < len(lines):
            lineno, text = lines[j]
            m = ITEM_RE.match(text)
            if m and int(m.group(1)) == want:
                items.append((lineno, m.group(2).strip()))
                want += 1
                j += 1
                continue
            if items and (BOLD_LABEL_RE.match(text.strip()) or SUBSECTION_RE.match(text)):
                break
            j += 1
        out.append((label.group(1).strip(), items))
    return out


def _derive_marker(sections: list[Section]) -> tuple[str, dict[str, int]]:
    """The label that introduces the practices list, derived from how many sections use it."""
    freq: collections.Counter[str] = collections.Counter()
    for s in sections:
        if s.chapter not in PHASE_CHAPTERS:
            continue
        for label, items in _labelled_lists(s.lines):
            if items:
                freq[label] += 1
    if not freq:
        _fail("no bold-labelled numbered list anywhere in the phase chapters; the practices block "
              "could not be located at all")
    ranked = freq.most_common()
    top, n_top = ranked[0]
    if n_top < MIN_MARKER_SECTIONS:
        _fail(f"the most common list label {top!r} introduces a list in only {n_top} section(s), "
              f"below the floor of {MIN_MARKER_SECTIONS}; that is not a document-wide convention "
              f"and picking it would be a guess")
    if len(ranked) > 1 and ranked[1][1] == n_top:
        _fail(f"two labels tie at {n_top} sections ({top!r} and {ranked[1][0]!r}); the practices "
              f"block cannot be identified by frequency and this extractor must not choose")
    return top, dict(ranked)


# --------------------------------------------------------------------------------------- citations


def citations(text: str) -> tuple[list[str], list[str]]:
    """`(case ids cited, case ids appearing as filenames)` in document order."""
    cited, paths = [], []
    for m in CASE_ID.finditer(text):
        (paths if PATH_EXT_RE.match(text[m.end():]) else cited).append(m.group(0))
    return cited, paths


def citation_spans(text: str) -> list[tuple[int, int]]:
    """The `[…]` and `*(…)*` spans that hold a citation, each counted once.

    A parenthesis span nested inside a bracket span is dropped rather than scanned again. §3.3 BP#1
    is why: its `*(v1.3 note: … [corrected per F2-5, FALSE, …])*` aside contains the bracket, so two
    independent passes read F2-5 twice and the document's assertion count came out 330 against 324
    citations. Neither number was wrong about what it measured, which is exactly why one of them had
    to stop being reported as the other.
    """
    found = []
    for opener, closer in (("[", "]"), ("(", ")")):
        for a, b in _balanced_spans(text, opener, closer):
            inner = text[a + 1 : b - 1]
            if CASE_ID.search(inner) and not inner.startswith("http"):
                found.append((a, b))
    # Only the maximal spans. `_balanced_spans` is called once per delimiter pair, so a bracket inside
    # a parenthesised aside is found by both passes and its cases were paired twice — in both
    # directions, since §7.1's `*(Diagram amended … [F5-4a …; F7-1, TRUE …])*` has the bracket inside
    # and §3.3's aside has it the other way round.
    return sorted((a, b) for a, b in found
                  if not any((oa, ob) != (a, b) and oa <= a and b <= ob for oa, ob in found))


def asserted_verdicts(text: str) -> list[tuple[str, str | None, int, str]]:
    """Every `(case, the verdict the document asserts for it, its offset, the span it was read from)`.

    A verdict word binds to the nearest preceding case id inside the same span, and to every id in an
    unbroken run of ids before it — `[F6-1, F6-2, F6-3, F6-4, F6-5, all FALSE]` asserts FALSE of five
    cases, not of the last one. Nearest-only binding read four of those five as asserting nothing, and
    a citation that asserts nothing cannot disagree with the register, so a wrong verdict inside a
    comma list was unreachable by the check that exists to catch exactly that.

    A run is broken by anything that is not punctuation or whitespace, which is the only form of this
    rule that works on both editions: the separator is `, ` in English and `、` in Chinese, while
    `F6-3 and F6-1, both FALSE` and its `F6-3 與 F6-1` translation both break the run and fall back to
    nearest-only in both languages. A word list here — "and", "與", "both" — would be a translated
    locator, and the parity assertion in `extract()` is what would catch it having drifted.

    A case id with no verdict word after it still yields `None`; that is a citation of the case, not a
    claim about its verdict, and it must not be adjudicated as one.
    """
    out: list[tuple[str, str | None, int, str]] = []
    for a, b in citation_spans(text):
        inner = text[a + 1 : b - 1]
        toks = [(m.start(), m.group(0), "case") for m in CASE_ID.finditer(inner)
                if not PATH_EXT_RE.match(inner[m.end():])]
        toks += [(m.start(), m.group(1), "verdict") for m in VERDICT_RE.finditer(inner)]
        toks.sort()
        run: list[tuple[int, str]] = []
        end = 0
        for at, tok, kind in toks:
            if kind == "case":
                if run and RUN_GAP_RE.fullmatch(inner[end:at]) is None:
                    out += [(t, None, o, inner) for o, t in run]
                    run = []
                run.append((at, tok))
                end = at + len(tok)
            elif run:
                out += [(t, tok, o, inner) for o, t in run]
                run = []
        out += [(t, None, o, inner) for o, t in run]
    return out


def _line_index(text: str) -> list[int]:
    """Character offset of the start of every line, for turning a span offset into a line number."""
    idx, pos = [0], 0
    for line in text.split("\n")[:-1]:
        pos += len(line) + 1
        idx.append(pos)
    return idx


def _locations(text: str) -> list[tuple[int, str]]:
    """`(line, stable location id)` for every heading, so an assertion can be addressed without a line.

    A line number is not a name: inserting one sentence in chapter 3 moves every assertion below it,
    and an exemption ledger keyed on line numbers would go stale on the next edit while still looking
    precise. A section id (`3.1`) or a chapter/appendix id (`ch:9`, `app:D`) survives that, and moving
    a citation from one section to another is exactly the change that SHOULD force re-adjudication.
    """
    out = []
    for lineno, line in _unfenced(text):
        m = SECTION_RE.match(line)
        if m:
            out.append((lineno, m.group(1)))
            continue
        m = CHAPTER_RE.match(line)
        if m:
            out.append((lineno, f"ch:{m.group(1)}"))
            continue
        m = APPENDIX_RE.match(line)
        if m:
            out.append((lineno, f"app:{m.group(1)}"))
    return out


def document_assertions(text: str) -> list[dict]:
    """Every asserted `(case, verdict)` pair in a whole document, with the line it sits on.

    Document-wide on purpose. The 45 practice sentences hold 16 citations; the assertions this
    platform most needs to check against its own register are in the surrounding prose, the appendix
    change log and the summary tables. A check scoped to the practices would report those as absent.
    """
    starts = _line_index(text)
    locs = _locations(text)
    out = []
    for a, b in citation_spans(text):
        inner = text[a + 1 : b - 1]
        line = max(i for i, s in enumerate(starts, 1) if s <= a)
        where = ([loc for ln, loc in locs if ln <= line] or ["front-matter"])[-1]
        for case, verdict, at, _ in asserted_verdicts(text[a : b + 1]):
            # A window around the case id, not the head of the span. §7.1's amendment aside and
            # Appendix D's change-log rows run past 2,000 characters and pair a dozen cases each, so a
            # leading excerpt showed one case's id above another case's verdict — a quotation that
            # would send an adjudicator to the wrong sentence.
            #
            # The width is not cosmetic. `check_practices.py` asserts that an exemption's quoted
            # fragment is still present IN THIS STRING, and the payload publishes this same string for
            # every assertion an exemption covers — so the gate checks exactly what a reader can see. A
            # gate reading a wider context than the page shows would let an exemption rest on a
            # sentence the reader is never given. The width is what it is because Appendix D's F5-3b
            # clause states the offending TRUE 380 characters before it withdraws it, and an exemption
            # that could not quote the withdrawal would have to be taken on trust.
            out.append({"case": case, "asserted": verdict, "line": line, "where": where,
                        "span": inner[max(0, at - 60) : at + 460]})
    return out


# --------------------------------------------------------------------------------------- one edition


def _read_edition(text: str, lang: str) -> dict:
    sections, chapters = _sections(text)
    marker, freq = _derive_marker(sections)

    practices, sec_rows = [], []
    for s in sections:
        if s.chapter not in PHASE_CHAPTERS:
            continue
        matching = [items for label, items in _labelled_lists(s.lines) if label == marker and items]
        if len(matching) > 1:
            _fail(f"[{lang}] §{s.id} carries {len(matching)} lists labelled {marker!r}; which one "
                  f"holds the practices is then a choice this extractor cannot make")
        if not matching:
            continue
        cited, paths = [], []
        for _, line in s.lines:
            c, p = citations(line)
            cited += c
            paths += p
        sec_rows.append({
            "id": s.id, "chapter": s.chapter, "phase": s.phase, "hop": s.hop,
            "heading": s.heading, "line": s.line,
            "n_practices": len(matching[0]),
            "section_cites": sorted(set(cited)),
            "n_section_citations": len(cited),
        })
        for n, (lineno, raw) in enumerate(matching[0], 1):
            cited_here, paths_here = citations(raw)
            practices.append({
                "key": f"bp:{s.id}#{n}", "section": s.id, "n": n,
                "phase": s.phase, "hop": s.hop, "line": lineno,
                "raw": raw, "prose": strip_citations(raw),
                "cites": sorted(set(cited_here)),
                "n_citations": len(cited_here),
                "asserted": [{"case": c, "asserted": v}
                             for c, v, _, _ in asserted_verdicts(raw)],
                "path_references": sorted(set(paths_here)),
            })

    if len(practices) < MIN_PRACTICES:
        _fail(f"[{lang}] {len(practices)} practice(s) extracted, below the floor of {MIN_PRACTICES}")

    cited_all, paths_all = citations(text)
    return {
        "lang": lang,
        "marker": marker,
        "marker_frequency": freq,
        "sections": sec_rows,
        "practices": practices,
        "principles": _principles(sections, lang),
        "anti_patterns": _anti_patterns(sections, lang),
        "checklist": _checklist(chapters, lang),
        "citation_census": {
            "n_citations": len(cited_all),
            "n_distinct": len(set(cited_all)),
            "cases": sorted(set(cited_all)),
            "n_path_references": len(paths_all),
            "path_references": sorted(set(paths_all)),
        },
        "assertions": document_assertions(text),
    }


def _one_section(sections: list[Section], sid: str, lang: str) -> Section:
    found = [s for s in sections if s.id == sid]
    if len(found) != 1:
        _fail(f"[{lang}] expected exactly one §{sid} section, found {len(found)}")
    return found[0]


def _section_table(sections: list[Section], sid: str, lang: str, floor: int) -> list[list[str]]:
    """The one pipe-table inside a section, addressed by the section rather than by a global index."""
    s = _one_section(sections, sid, lang)
    tables = read_tables_from_lines([line for _, line in s.lines])
    if len(tables) != 1:
        _fail(f"[{lang}] §{sid} holds {len(tables)} table(s); this extractor reads the one table a "
              f"section carries and must not choose between two")
    _, rows = tables[0]
    if len(rows) < floor:
        _fail(f"[{lang}] §{sid}'s table has {len(rows)} row(s), below the floor of {floor}")
    return rows


def _principles(sections: list[Section], lang: str) -> list[dict]:
    rows = _section_table(sections, "7.1", lang, MIN_PRINCIPLES)
    return [{"n": int(r[0]) if r[0].strip().isdigit() else i,
             "principle": clean_cell(r[1], drop_cites=False),
             "rationale": clean_cell(r[2], drop_cites=False),
             "cites": sorted(set(citations(" ".join(r))[0]))}
            for i, r in enumerate(rows, 1)]


def _anti_patterns(sections: list[Section], lang: str) -> list[dict]:
    rows = _section_table(sections, "7.2", lang, MIN_ANTI_PATTERNS)
    return [{"n": i,
             "anti_pattern": clean_cell(r[0], drop_cites=False),
             "problem": clean_cell(r[1], drop_cites=False),
             "recommendation": clean_cell(r[2], drop_cites=False),
             "cites": sorted(set(citations(" ".join(r))[0]))}
            for i, r in enumerate(rows, 1)]


def _checklist(chapters: dict[str, list[tuple[int, str]]], lang: str) -> list[dict]:
    """§8's `- [ ]` items, grouped by the bold label above them.

    The groups are the document's four implementation phases. Their labels are read, not named: the
    Chinese edition writes `**階段一:基礎**`, and a list of English group names here would return an
    empty checklist on that edition.
    """
    lines = chapters.get("8") or []
    groups: list[dict] = []
    for _, line in lines:
        label = BOLD_LABEL_RE.match(line.strip())
        if label:
            groups.append({"label": label.group(1).strip(), "items": []})
            continue
        m = CHECK_RE.match(line)
        if not m:
            continue
        if not groups:
            _fail(f"[{lang}] §8 has a checklist item before any group label; an ungrouped item "
                  f"sits outside every count")
        raw = m.group(1).strip()
        groups[-1]["items"].append({
            "raw": raw, "prose": strip_citations(raw),
            "cites": sorted(set(citations(raw)[0])),
        })
    n = sum(len(g["items"]) for g in groups)
    if n < MIN_CHECKLIST_ITEMS:
        _fail(f"[{lang}] §8 yielded {n} checklist item(s), below the floor of "
              f"{MIN_CHECKLIST_ITEMS}")
    return groups


# --------------------------------------------------------------------------------------- both


def extract(en_text: str, zh_text: str) -> dict:
    """The design, in both languages, with every parity assertion this platform publishes under.

    Parity is not decoration. The Chinese page renders the Chinese document, so if the two editions
    disagree on how many practices §4.1 has, one of the two pages is silently short — and it is
    always the Chinese one that gets fewer readers who would notice.
    """
    en, zh = _read_edition(en_text, "en"), _read_edition(zh_text, "zh")

    if en["marker"] == zh["marker"]:
        _fail(f"both editions derive the same practices label {en['marker']!r}; either the Chinese "
              f"edition left it untranslated or one document was read twice")

    e_ids = [s["id"] for s in en["sections"]]
    z_ids = [s["id"] for s in zh["sections"]]
    if e_ids != z_ids:
        _fail(f"the editions disagree on which sections carry practices: en={e_ids} zh={z_ids}")
    for a, b in zip(en["sections"], zh["sections"]):
        if a["n_practices"] != b["n_practices"]:
            _fail(f"§{a['id']} has {a['n_practices']} practice(s) in English and "
                  f"{b['n_practices']} in Chinese; one of the two pages would be short")
        for field in ("phase", "hop"):
            if a[field] != b[field]:
                _fail(f"§{a['id']} derives {field}={a[field]!r} from the English heading and "
                      f"{b[field]!r} from the Chinese one; both editions state it in Latin "
                      f"characters, so a disagreement is a document defect")

    if len(en["practices"]) != len(zh["practices"]):
        _fail(f"{len(en['practices'])} practices in English, {len(zh['practices'])} in Chinese")

    e_cens, z_cens = en["citation_census"], zh["citation_census"]
    if e_cens["n_citations"] != z_cens["n_citations"] or e_cens["cases"] != z_cens["cases"]:
        _fail(f"the editions cite differently: en {e_cens['n_citations']} citations over "
              f"{e_cens['n_distinct']} cases, zh {z_cens['n_citations']} over "
              f"{z_cens['n_distinct']}. A Chinese reader would be shown a different evidence base.")
    if e_cens["n_citations"] < MIN_CITATIONS:
        _fail(f"{e_cens['n_citations']} citations found, below the floor of {MIN_CITATIONS}; the "
              f"evidence hook would render as almost empty")

    practices = []
    identical = []
    for a, b in zip(en["practices"], zh["practices"]):
        if a["key"] != b["key"]:
            _fail(f"practice keys diverged: {a['key']} vs {b['key']}")
        if a["cites"] != b["cites"]:
            _fail(f"{a['key']} cites {a['cites']} in English and {b['cites']} in Chinese")
        if a["raw"].strip() == b["raw"].strip():
            identical.append(a["key"])
        practices.append({
            "key": a["key"], "section": a["section"], "n": a["n"],
            "phase": a["phase"], "hop": a["hop"],
            "prose": {"en": a["prose"], "zh": b["prose"]},
            "raw": {"en": a["raw"], "zh": b["raw"]},
            "line": {"en": a["line"], "zh": b["line"]},
            "cites": a["cites"],
            "asserted": a["asserted"],
        })
    if identical:
        _fail(f"{len(identical)} practice(s) are byte-identical in both editions ({identical[:5]}); "
              f"an untranslated practice renders to a Chinese reader as the platform's own voice")

    tables = {}
    for name, floor, fields in (("principles", MIN_PRINCIPLES, ("principle", "rationale")),
                                ("anti_patterns", MIN_ANTI_PATTERNS,
                                 ("anti_pattern", "problem", "recommendation"))):
        if len(en[name]) != len(zh[name]):
            _fail(f"{name}: {len(en[name])} rows in English, {len(zh[name])} in Chinese")
        if len(en[name]) < floor:
            _fail(f"{name}: {len(en[name])} rows, below the floor of {floor}")
        rows = []
        for a, b in zip(en[name], zh[name]):
            if a["cites"] != b["cites"]:
                _fail(f"{name} row {a['n']} cites {a['cites']} in English and {b['cites']} in "
                      f"Chinese")
            row = {"n": a["n"], "cites": a["cites"]}
            for f in fields:
                # The first column of §7.2 is a short label and one row of it — an AWS product name —
                # is legitimately the same in both editions, so identity is not fatal here the way it
                # is for a practice sentence. It is recorded so the translation census can see it.
                row[f] = {"en": a[f], "zh": b[f], **({"untranslated": True} if a[f] == b[f] else {})}
            rows.append(row)
        tables[name] = rows

    if [len(g["items"]) for g in en["checklist"]] != [len(g["items"]) for g in zh["checklist"]]:
        _fail("the two editions' implementation checklists have different group sizes")

    # The assertions are the part a reader is asked to trust, so the two editions must assert the same
    # verdicts in the same places. Keyed by (case, verdict, location) rather than by line, because the
    # editions are not line-aligned — the Chinese file is 348 lines shorter — and a line-keyed
    # comparison would fail on formatting instead of on meaning.
    def _akey(row):
        return (row["case"], row["asserted"], row["where"])

    e_keys = collections.Counter(_akey(r) for r in en["assertions"])
    z_keys = collections.Counter(_akey(r) for r in zh["assertions"])
    if e_keys != z_keys:
        diff = sorted((e_keys - z_keys).items()) + sorted((z_keys - e_keys).items())
        _fail(f"the editions assert different verdicts: {len(en['assertions'])} vs "
              f"{len(zh['assertions'])} pairs, {len(diff)} key(s) unmatched, e.g. {diff[:4]}")
    assertions = [{"case": a["case"], "asserted": a["asserted"], "where": a["where"],
                   "line": {"en": a["line"], "zh": b["line"]},
                   "span": {"en": a["span"], "zh": b["span"]}}
                  for a, b in zip(en["assertions"], zh["assertions"])]
    for a, b in zip(en["assertions"], zh["assertions"]):
        if _akey(a) != _akey(b):
            _fail(f"the editions' assertions are the same multiset but not in the same order: "
                  f"{_akey(a)} against {_akey(b)}. Pairing them by position would mislabel a span.")

    sections = []
    for a, b in zip(en["sections"], zh["sections"]):
        sections.append({
            "id": a["id"], "chapter": a["chapter"], "phase": a["phase"], "hop": a["hop"],
            "heading": {"en": a["heading"], "zh": b["heading"]},
            "n_practices": a["n_practices"],
            "keys": [p["key"] for p in practices if p["section"] == a["id"]],
            "section_cites": sorted(set(a["section_cites"]) | set(b["section_cites"])),
            "n_section_citations": a["n_section_citations"],
        })
        if set(a["section_cites"]) != set(b["section_cites"]):
            _fail(f"§{a['id']} cites {sorted(set(a['section_cites']) ^ set(b['section_cites']))} in "
                  f"one edition and not the other")

    return {
        "marker": {"en": en["marker"], "zh": zh["marker"]},
        "marker_frequency": {"en": en["marker_frequency"], "zh": zh["marker_frequency"]},
        "phases": [p for p in PHASE_TOKENS if any(s["phase"] == p for s in sections)],
        "sections": sections,
        "practices": practices,
        "n_practices": len(practices),
        "principles": tables["principles"],
        "anti_patterns": tables["anti_patterns"],
        "checklist": [{"label": {"en": a["label"], "zh": b["label"]},
                       "items": [{"prose": {"en": x["prose"], "zh": y["prose"]},
                                  "raw": {"en": x["raw"], "zh": y["raw"]},
                                  "cites": sorted(set(x["cites"]) | set(y["cites"]))}
                                 for x, y in zip(a["items"], b["items"])]}
                      for a, b in zip(en["checklist"], zh["checklist"])],
        "n_checklist_items": sum(len(g["items"]) for g in en["checklist"]),
        "citation_census": {
            "n_citations": e_cens["n_citations"],
            "n_distinct": e_cens["n_distinct"],
            "cases": e_cens["cases"],
            "n_path_references": e_cens["n_path_references"],
            "path_references": e_cens["path_references"],
            "n_inline_practice_citations": sum(p["n_citations"] for p in en["practices"]),
            "both_editions": "identical multisets, asserted by extract()",
        },
        "assertions": assertions,
        "n_assertions": len(assertions),
    }


def extract_files(en_path: Path = EN_DOC, zh_path: Path = ZH_DOC) -> dict:
    for p in (en_path, zh_path):
        if not p.is_file():
            _fail(f"{p} is not a file; the design cannot be read out of a document that is not there")
    return extract(en_path.read_text(encoding="utf-8"), zh_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print the whole structure as JSON")
    args = ap.parse_args(argv)
    try:
        data = extract_files()
    except SourceError as exc:
        print(f"SOURCE-FAIL: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    m = data["marker"]
    print(f"marker derived: en={m['en']!r} zh={m['zh']!r}")
    print(f"  en frequency {data['marker_frequency']['en']}")
    print(f"  zh frequency {data['marker_frequency']['zh']}")
    print(f"{data['n_practices']} practices in {len(data['sections'])} sections, "
          f"phases {data['phases']}")
    for s in data["sections"]:
        print(f"  §{s['id']:4s} {str(s['phase']):6s} hop {str(s['hop']):5s} "
              f"{s['n_practices']} practice(s), section cites {len(s['section_cites'])} case(s)")
    c = data["citation_census"]
    print(f"citations {c['n_citations']} over {c['n_distinct']} distinct case(s); "
          f"{c['n_inline_practice_citations']} of them inside a practice sentence; "
          f"{c['n_path_references']} filename reference(s) excluded {c['path_references']}")
    print(f"{len(data['principles'])} principles, {len(data['anti_patterns'])} anti-patterns, "
          f"{data['n_checklist_items']} checklist items in {len(data['checklist'])} groups")
    where = collections.Counter(a["where"] for a in data["assertions"])
    print(f"{data['n_assertions']} verdict assertion(s), identical in both editions, over "
          f"{len(where)} location(s); busiest {where.most_common(4)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
