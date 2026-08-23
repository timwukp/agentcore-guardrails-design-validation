"""Pull tables out of the two v1.4 Markdown files so slides quote them, not retype them.

The English and zh-TW files are structurally parallel (same 21 tables in the same
order — that parity is checked, not assumed, by :func:`assert_parallel`), so a
table is addressed by **index** and the same index gives the same table in both
languages. That keeps the two decks from drifting the way hand-copied cells would.

Verdict citations (``[verified F8-2, TRUE, n=240, 2026-08-10]``) are stripped from
slide cells and replaced by one footnote per slide pointing at the document. The
test is content-driven rather than keyword-driven — a bracket span is a citation
if it contains a case id — so it works identically on both languages.
"""

from __future__ import annotations

import re

CASE_ID = re.compile(r"\bF\d+-\d+[ab]?\b")


def _balanced_spans(s, opener, closer):
    """Top-level balanced ``opener…closer`` spans as (start, end_exclusive)."""
    spans = []
    depth = 0
    start = -1
    for i, ch in enumerate(s):
        if ch == opener:
            if depth == 0:
                start = i
            depth += 1
        elif ch == closer and depth:
            depth -= 1
            if depth == 0:
                spans.append((start, i + 1))
    return spans


def strip_citations(text):
    """Drop verdict citations: ``[… F1-2 …]`` spans and ``*(… F1-2 …)*`` asides."""
    out = text
    for _ in range(3):
        changed = False
        for a, b in reversed(_balanced_spans(out, "[", "]")):
            inner = out[a + 1 : b - 1]
            if CASE_ID.search(inner) and not inner.startswith("http"):
                out = out[:a].rstrip() + " " + out[b:].lstrip()
                changed = True
        if not changed:
            break
    for a, b in reversed(_balanced_spans(out, "(", ")")):
        italic = out[a - 1 : a] == "*" or out[max(0, a - 2) : a] == "*("
        inner = out[a + 1 : b - 1]
        if italic and CASE_ID.search(inner):
            end = b + 2 if out[b : b + 2] == ")*" else b
            end = b + 1 if out[b : b + 1] == "*" else end
            out = out[: a - 1] + " " + out[end:]
    # "… — verified [F5-6, TRUE]" leaves a dangling verb behind once the bracket goes.
    out = re.sub(r"\s*[—–-]?\s*(verified|corrected per|corrected)\s*(?=[)\]]|$)", "", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"—\s*$", "", out)
    return out.strip(" —·")


_SENT_END = re.compile(r"(?<=[.!?。！？])\s+|(?<=[。！？])")


def abridge(text, budget):
    """Keep whole sentences up to ``budget`` visual columns; never cut mid-sentence.

    A slide cell has room for a few lines, and the document's cells run to paragraphs.
    Cutting at a sentence boundary keeps every word on the slide a word the document
    actually wrote — the alternative, an ellipsis mid-clause, can invert a meaning.
    The boundary set covers both languages (``.``/``。``), so one budget serves both;
    the *visual* width is what is measured, since one CJK glyph occupies two columns.
    """
    if vwidth(text) <= budget:
        return text
    parts = [p for p in _SENT_END.split(text) if p]
    out = []
    used = 0
    for p in parts:
        w = vwidth(p) + 1
        if out and used + w > budget:
            break
        out.append(p.strip())
        used += w
    if len(out) == len(parts):
        # Nothing was dropped — a single sentence wider than the whole budget, which the
        # table's own fit loop handles by shrinking the type. Appending an ellipsis here
        # would claim a truncation that did not happen.
        return text
    joined = " ".join(out).strip()
    ends_clean = joined.endswith(("。", ".", "!", "?", "！", "？"))
    joined = rebalance(joined)
    return joined if ends_clean else joined + " …"


def rebalance(text):
    """Close a ``**bold**`` or ``` `code` ``` span that a sentence cut left open.

    A bold span in the source often runs across two sentences, so keeping only the
    first leaves a lone ``**`` — which the renderer then prints literally.
    """
    if text.count("**") % 2:
        text += "**"
    if text.count("`") % 2:
        text += "`"
    return text


def vwidth(text):
    """CJK counts double. Kept local so this module does not import the renderer."""
    n = 0
    for ch in text:
        o = ord(ch)
        wide = (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3
                or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE6F
                or 0xFF00 <= o <= 0xFF60 or 0xFFE0 <= o <= 0xFFE6)
        n += 2 if wide else 1
    return n


def clean_cell(text, drop_cites=True):
    t = text.strip()
    if drop_cites:
        t = strip_citations(t)
    t = re.sub(r"<(https?://[^>]+)>", r"\1", t)
    t = t.replace("\\|", "|")
    return t.strip()


def read_tables(path):
    """Every Markdown pipe-table in ``path``, in order, as ``(headers, rows)``."""
    return read_tables_from_lines(open(path, encoding="utf-8").read().split("\n"))


def read_tables_from_lines(lines):
    """The same reader, over lines already in hand.

    Split out for `platform/build/practices_source.py`, which needs the tables of ONE section
    (§7.1's principles, §7.2's anti-patterns) and must not address them by a whole-document index —
    an index is a hand-written locator that goes stale the moment a table is inserted above it. A
    second table reader over a slice would be a second answer to the same question, so this is the
    one implementation and `read_tables` is now a caller of it.
    """
    tables, block, in_fence = [], None, False
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.lstrip().startswith("|"):
            (block := block if block is not None else []).append(line.strip())
        elif block:
            tables.append(block)
            block = None
    if block:
        tables.append(block)

    parsed = []
    for block in tables:
        rows = []
        for raw in block:
            if re.fullmatch(r"\|[\s:|-]+\|", raw):
                continue
            cells = raw.strip().strip("|").split("|")
            rows.append([c.strip() for c in cells])
        parsed.append((rows[0], rows[1:]))
    return parsed


class Source:
    """The two documents, addressed in parallel."""

    def __init__(self, en_path, zh_path):
        self.paths = {"en": en_path, "zh": zh_path}
        self.tables = {k: read_tables(v) for k, v in self.paths.items()}
        self.assert_parallel()

    def assert_parallel(self):
        n_en, n_zh = len(self.tables["en"]), len(self.tables["zh"])
        if n_en != n_zh:
            raise SystemExit(f"table count differs: en={n_en} zh={n_zh} — decks would drift")
        for i, ((he, re_), (hz, rz)) in enumerate(zip(self.tables["en"], self.tables["zh"])):
            if len(he) != len(hz) or len(re_) != len(rz):
                raise SystemExit(f"table #{i} shape differs: en={len(he)}x{len(re_)} zh={len(hz)}x{len(rz)}")

    def table(self, lang, index, drop_cites=True, keep_rows=None, keep_cols=None, budget=None):
        headers, rows = self.tables[lang][index]
        if keep_cols is not None:
            headers = [headers[c] for c in keep_cols]
            rows = [[r[c] for c in keep_cols] for r in rows]
        if keep_rows is not None:
            rows = [rows[r] for r in keep_rows]

        def cell(c):
            c = clean_cell(c, drop_cites)
            return abridge(c, budget) if budget else c

        return (
            [clean_cell(h, drop_cites) for h in headers],
            [[cell(c) for c in row] for row in rows],
        )
