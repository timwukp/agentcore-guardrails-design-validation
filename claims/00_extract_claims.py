#!/usr/bin/env python3
"""Mechanically extract falsifiable claim units from the canonical guardrails document.

Phase 0, step 1 of the validation platform.

Design contract
---------------
This script is *deterministic and non-interpretive*. It does not decide what is
true, what is testable, or what should be merged. It only enumerates the
structural units of the document so that coverage becomes auditable rather than
asserted. Interpretation lives in ``triage.csv`` (curated) and is joined by
``check_coverage.py``.

Every emitted unit carries ``sha1(text)``. If the document is edited, the hash
changes and the corresponding triage row is invalidated, forcing re-triage. That
is the mechanism that stops coverage claims from silently expiring.

Unit types
----------
heading   scope anchor, not a claim (emitted so anchors are auditable)
thead     table header row
trow      table body row
bullet    ``- `` / ``* `` list item
numitem   ``N. `` list item
checkitem ``- [ ] `` checklist item
quote     blockquote group (consecutive ``> `` lines merged)
code      fenced code block, non-mermaid (API shapes are claims)
mermaid   node/edge/note label extracted from a fenced mermaid block
prose     assertive sentence in body text

Usage
-----
    python3 00_extract_claims.py --doc ../../agentcore_guardrails_best_practices_v1.2.md
    python3 00_extract_claims.py --doc <path> --stats-only
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# anchors
# --------------------------------------------------------------------------

# "### 3.1 Checkpoint Hop #1: ..." -> "s3-1"; "## 1. Executive Summary" -> "s1";
# "## Appendix A: ..." -> "appA".
# The trailing "\.?" matters: top-level headings in this document are written
# "## 1. Executive Summary" (with a period) while subsections are written
# "### 3.1 Checkpoint ..." (without). Without it, §1/§2/... fall through to the
# slug branch and the anchor namespace splits into two incompatible styles.
_NUMBERED_HEADING = re.compile(r"^(#{1,6})\s+(\d+(?:\.\d+)*)\.?\s+(.*)$")
_APPENDIX_HEADING = re.compile(r"^(#{1,6})\s+Appendix\s+([A-Z])\b[:\s]*(.*)$", re.I)
_ANY_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _slugify(text: str) -> str:
    text = re.sub(r"[`*_]", "", text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")[:40] or "x"


def heading_anchor(line: str) -> tuple[str, int, str] | None:
    """Return (anchor, level, title) for a heading line, else None."""
    m = _NUMBERED_HEADING.match(line)
    if m:
        return ("s" + m.group(2).replace(".", "-"), len(m.group(1)), m.group(3).strip())
    m = _APPENDIX_HEADING.match(line)
    if m:
        return ("app" + m.group(2).upper(), len(m.group(1)), m.group(3).strip())
    m = _ANY_HEADING.match(line)
    if m:
        return (_slugify(m.group(2)), len(m.group(1)), m.group(2).strip())
    return None


# --------------------------------------------------------------------------
# sentence splitting
# --------------------------------------------------------------------------

# Tokens whose trailing period must NOT end a sentence. Order matters: longest
# first, so "e.g." is protected before "g.".
_ABBREV = [
    "e.g.", "i.e.", "vs.", "etc.", "cf.", "incl.", "approx.", "Sec.", "Fig.",
    "No.", "Inc.", "Ltd.", "U.S.", "N. Virginia", "Mr.", "Ms.", "Dr.", "St.",
]

_SENT_END = re.compile(r"(?<=[.!?])[ \t]+(?=[\"'(\[]?[A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, protecting abbreviations, decimals and URLs."""
    guard: dict[str, str] = {}

    def _stash(pattern: str, tag: str, s: str) -> str:
        def sub(m: re.Match) -> str:
            key = f"\x00{tag}{len(guard)}\x00"
            guard[key] = m.group(0)
            return key
        return re.sub(pattern, sub, s)

    # URLs and inline code first: they may contain periods and capitals.
    text = _stash(r"<https?://[^>]+>|https?://\S+", "U", text)
    text = _stash(r"`[^`]+`", "C", text)
    # Decimals like "0.2", "v2.9", "1.0".
    text = _stash(r"\b\d+\.\d+\b", "D", text)
    for abbr in _ABBREV:
        text = _stash(re.escape(abbr), "A", text)

    parts = [p.strip() for p in _SENT_END.split(text)]

    out = []
    for p in parts:
        for key, val in guard.items():
            p = p.replace(key, val)
        if p:
            out.append(p)
    return out


# Sentences that assert something checkable. A sentence with none of these and
# no verb-like content is usually navigational ("The following diagram shows...").
#
# Case matters here: "does" is a verb, "Document" is not, and an earlier
# case-insensitive version tagged "*End of Document*" as an assertive claim on
# the strength of the substring "Document". Verbs are therefore matched
# lowercase-only, with a separate sentence-initial alternative for the ones that
# legitimately open a sentence ("Provides ...", "Requires ...").
_VERBS = (
    r"is|are|was|were|has|have|does|do|must|should|shall|will|can|cannot|"
    r"can't|may|might|requires?|required|supports?|supported|provides?|"
    r"applies|applied|returns?|blocks?|denies|denied|evaluates?|publishes?|"
    r"documents|documented|not"
)
_ASSERTIVE = re.compile(rf"(?:^|\W)(?:{_VERBS})(?=\W|$)")
_ASSERTIVE_INITIAL = re.compile(rf"^\W*(?:{_VERBS})(?=\W|$)", re.I)

# Purely navigational / meta sentences: exclude from prose claims but keep a
# record so the exclusion is visible rather than silent.
_NAVIGATIONAL = re.compile(
    r"^\W*(the following|this section|this document defines|use this|"
    r"see (section|the)|references?:|usage|scope note|key implications|"
    r"tier selection|where each hop sits|the hooks above only bind|"
    r"end of document)",
    re.I,
)

# Bold run-in labels that introduce the next construct ("**What it does:**",
# "**Supported Safeguards:**"). These are headings in bold clothing: they assert
# nothing, so scoring them "passed" would inflate coverage with free wins.
_RUNIN_LABEL = re.compile(r"^\**[A-Z][^.!?]{0,60}:\**$")

# A colon-terminated stem whose content lives in the following list/table
# ("It has three modes (Accelerator, Built-in Tools section):"). The claim is
# in the items, not the stem.
_LEADIN = re.compile(r":\**\s*$")


def classify_prose(sent: str) -> str:
    """Return "" for a claim-bearing sentence, else the reason it is not one.

    The default is INCLUSION. A verb-list allowlist was tried first and dropped
    two real claims ("AWS recommends calibrating ..." — "recommends" was not in
    the list; "(3) Label results and use the confidence scores ..." — imperative
    mood has no auxiliary verb). An excluded claim is invisible, whereas an
    over-included one merely gets triaged D/N with a written reason. The
    asymmetry says fail toward inclusion, so only explicit non-claim shapes are
    filtered and the verb test applies solely to short fragments.

    The reason string is carried into the CSV so that every excluded sentence is
    visible and auditable. Nothing is dropped silently.
    """
    if _RUNIN_LABEL.match(sent):
        return "runin-label"
    if _NAVIGATIONAL.match(sent):
        return "navigational"
    if _LEADIN.search(sent) and len(sent) < 120 and not _ASSERTIVE.search(sent):
        # A lead-in stem may still assert something before the colon
        # ("Thresholds: ... AgentCore applies defaults of 0.2"), so the verb
        # test guards this branch rather than gating everything.
        return "leadin-stem"
    if len(sent) < 25 and not (_ASSERTIVE.search(sent) or _ASSERTIVE_INITIAL.match(sent)):
        return "fragment"
    return ""


# --------------------------------------------------------------------------
# mermaid label extraction
# --------------------------------------------------------------------------

_MERMAID_LABELS = [
    re.compile(r'\["([^"]+)"\]'),          # node["label"]
    re.compile(r'\{"([^"]+)"\}'),          # decision{"label"}
    re.compile(r'\(\["([^"]+)"\]\)'),      # stadium
    re.compile(r'--\s*"([^"]+)"\s*-{1,3}>'),  # edge -- "label" -->
    re.compile(r'-\.\s*"([^"]+)"\s*\.-'),  # dotted edge -. "label" .->
]
_MERMAID_NOTE = re.compile(r"^\s*Note\s+(?:over|left of|right of)\s+[^:]+:\s*(.+)$")
_MERMAID_MSG = re.compile(r"^\s*\w+\s*-{1,2}>>?\s*\w+\s*:\s*(.+)$")
_MERMAID_SUBGRAPH = re.compile(r'^\s*subgraph\s+\w+\["([^"]+)"\]')


def mermaid_labels(block: list[str]) -> list[str]:
    """Extract human-readable labels from a mermaid block, in document order."""
    labels: list[str] = []
    for raw in block:
        line = raw.rstrip()
        for m in _MERMAID_SUBGRAPH.finditer(line):
            labels.append(m.group(1))
        for m in _MERMAID_NOTE.finditer(line):
            labels.append(m.group(1))
        for m in _MERMAID_MSG.finditer(line):
            labels.append(m.group(1))
        for pat in _MERMAID_LABELS:
            for m in pat.finditer(line):
                labels.append(m.group(1))
    # Normalize: <br/> is layout, not content. Deduplicate within the block
    # while preserving order (a label repeated in one diagram is one claim).
    seen: set[str] = set()
    out: list[str] = []
    for lab in labels:
        norm = re.sub(r"<br\s*/?>", " ", lab)
        norm = re.sub(r"&nbsp;|#35;", lambda m: "#" if m.group(0) == "#35;" else " ", norm)
        norm = re.sub(r"\s+", " ", norm).strip()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


# --------------------------------------------------------------------------
# unit model
# --------------------------------------------------------------------------


@dataclass
class Unit:
    anchor: str
    unit_type: str
    ordinal: int
    line: int
    text: str
    note: str = ""
    claim_id: str = field(default="", init=False)
    sha1: str = field(default="", init=False)

    def finalize(self) -> None:
        self.claim_id = f"C-{self.anchor}-{self.unit_type}-{self.ordinal:03d}"
        self.sha1 = hashlib.sha1(self.text.encode("utf-8")).hexdigest()


_TABLE_SEP = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
_FENCE = re.compile(r"^\s*```(\w*)")
_CHECK = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
_NUMITEM = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")


def clean_cell(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.strip()).strip()


def extract(doc: Path) -> list[Unit]:
    lines = doc.read_text(encoding="utf-8").splitlines()
    units: list[Unit] = []
    counters: dict[tuple[str, str], int] = {}
    anchor = "front"

    def emit(unit_type: str, line_no: int, text: str, note: str = "") -> None:
        text = clean_cell(text)
        if not text:
            return
        key = (anchor, unit_type)
        counters[key] = counters.get(key, 0) + 1
        u = Unit(anchor, unit_type, counters[key], line_no, text, note)
        u.finalize()
        units.append(u)

    i = 0
    n = len(lines)
    in_table = False
    table_row_idx = 0
    quote_buf: list[str] = []
    quote_start = 0

    def flush_quote() -> None:
        nonlocal quote_buf
        if quote_buf:
            emit("quote", quote_start, " ".join(quote_buf))
            quote_buf = []

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        # ---- fenced blocks -------------------------------------------------
        fence = _FENCE.match(raw)
        if fence:
            flush_quote()
            in_table = False
            lang = fence.group(1).lower()
            block: list[str] = []
            start = i + 1
            i += 1
            while i < n and not _FENCE.match(lines[i]):
                block.append(lines[i])
                i += 1
            i += 1  # consume closing fence
            if lang == "mermaid":
                for lab in mermaid_labels(block):
                    emit("mermaid", start, lab)
            elif block:
                emit("code", start, " ".join(x.strip() for x in block), note=f"lang={lang or 'none'}")
            continue

        # ---- headings ------------------------------------------------------
        h = heading_anchor(raw) if stripped.startswith("#") else None
        if h:
            flush_quote()
            in_table = False
            anchor, _level, title = h
            counters[(anchor, "heading")] = counters.get((anchor, "heading"), 0) + 1
            u = Unit(anchor, "heading", counters[(anchor, "heading")], i + 1, title,
                     note="scope anchor")
            u.finalize()
            units.append(u)
            i += 1
            continue

        # ---- blockquotes ---------------------------------------------------
        q = _QUOTE.match(raw)
        if q:
            if not quote_buf:
                quote_start = i + 1
            body = q.group(1).strip()
            if body:
                quote_buf.append(body)
            i += 1
            continue
        flush_quote()

        # ---- tables --------------------------------------------------------
        if stripped.startswith("|"):
            if _TABLE_SEP.match(raw):
                in_table = True   # separator seen: previous row was the header
                i += 1
                continue
            cells = [clean_cell(c) for c in stripped.strip("|").split("|")]
            row_type = "trow" if in_table else "thead"
            if not in_table:
                table_row_idx = 0
            table_row_idx += 1
            # One unit per row, cells joined by " || " so a row stays atomic:
            # a table row is one proposition (metric X means Y, used for Z).
            emit(row_type, i + 1, " || ".join(cells),
                 note=f"cells={len(cells)}")
            i += 1
            continue
        in_table = False

        # ---- list items ----------------------------------------------------
        c = _CHECK.match(raw)
        if c:
            emit("checkitem", i + 1, c.group(1))
            i += 1
            continue

        m = _NUMITEM.match(raw)
        if m:
            body = m.group(3)
            start = i + 1
            i += 1
            # absorb wrapped continuation lines (indented, not a new construct)
            while i < n and _is_continuation(lines[i]):
                body += " " + lines[i].strip()
                i += 1
            emit("numitem", start, body)
            continue

        b = _BULLET.match(raw)
        if b:
            body = b.group(2)
            start = i + 1
            i += 1
            while i < n and _is_continuation(lines[i]):
                body += " " + lines[i].strip()
                i += 1
            emit("bullet", start, body)
            continue

        # ---- prose ---------------------------------------------------------
        if stripped:
            para = [stripped]
            i += 1
            while i < n and lines[i].strip() and not _starts_construct(lines[i]):
                para.append(lines[i].strip())
                i += 1
            text = " ".join(para)
            para_start = i - len(para) + 1
            for sent in split_sentences(text):
                emit("prose", para_start, sent, note=classify_prose(sent))
            continue

        i += 1

    flush_quote()
    return units


def _starts_construct(line: str) -> bool:
    s = line.strip()
    return bool(
        s.startswith("#") or s.startswith("|") or s.startswith(">")
        or _FENCE.match(line) or _BULLET.match(line) or _NUMITEM.match(line)
    )


def _is_continuation(line: str) -> bool:
    """A wrapped list-item line: indented, non-blank, starts no new construct."""
    if not line.strip():
        return False
    if not line.startswith(("  ", "\t")):
        return False
    return not _starts_construct(line)


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

FIELDS = ["claim_id", "anchor", "unit_type", "ordinal", "doc_line", "sha1", "note", "text"]


def write_csv(units: list[Unit], out: Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for u in units:
            w.writerow({
                "claim_id": u.claim_id,
                "anchor": u.anchor,
                "unit_type": u.unit_type,
                "ordinal": u.ordinal,
                "doc_line": u.line,
                "sha1": u.sha1,
                "note": u.note,
                "text": u.text,
            })


def print_stats(units: list[Unit], doc: Path) -> None:
    from collections import Counter
    by_type = Counter(u.unit_type for u in units)
    notes = Counter(u.note for u in units if u.note)
    print(f"document      : {doc}")
    print(f"doc sha256    : {hashlib.sha256(doc.read_bytes()).hexdigest()}")
    print(f"total units   : {len(units)}")
    print()
    for t, c in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"  {t:<10} {c:>5}")
    print()
    claimable = sum(1 for u in units if u.unit_type != "heading" and not u.note.startswith(
        ("navigational", "runin-label", "leadin-stem", "fragment")))
    print(f"  headings (anchors, not claims) : {by_type.get('heading', 0)}")
    for reason in ("navigational", "runin-label", "leadin-stem", "fragment"):
        print(f"  prose excluded ({reason:<13}): {notes.get(reason, 0)}")
    print(f"  CLAIMABLE UNITS                : {claimable}")
    dupes = len(units) - len({u.sha1 for u in units})
    print(f"  duplicate-text units           : {dupes}"
          "  (candidates for sites[] merge)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "claims_raw.csv")
    ap.add_argument("--stats-only", action="store_true")
    args = ap.parse_args(argv)

    if not args.doc.is_file():
        print(f"error: no such document: {args.doc}", file=sys.stderr)
        return 2

    units = extract(args.doc)
    print_stats(units, args.doc)
    if not args.stats_only:
        write_csv(units, args.out)
        print(f"\nwrote {args.out} ({len(units)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
