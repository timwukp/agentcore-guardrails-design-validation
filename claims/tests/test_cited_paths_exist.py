#!/usr/bin/env python3
"""Every repo-relative path a distributable document cites must exist in the distributed tree.

Why this file exists
--------------------
On 2026-08-20 two citations in this repository resolved to nothing, and both for the same reason:
there are **two directories called `session-logs/`** — this repo's, and the outer cross-device
`~/Downloads/session-logs/`. `FUTURE-WORK.md` item 33 and
`results/FINDING-F6-DAY2-DECISIVENESS.md` both cited `session-logs/f6-day2-REAL-20260819.log` as
**Evidence**, and a second document cited
`session-logs/2026-08-15-grx-whitepaper-v1-figures-scan-scope.md`. Both files existed — in the outer
directory. A reader who clones the repository and follows the citation finds nothing.

That is worse than a broken link. This project's whole discipline is that a claim names the artifact
it rests on, so a citation a reader cannot fetch is a claim with no evidence *that reads exactly like
a claim with evidence*. Nothing noticed, because a path inside prose is checked by nobody
(`feedback_prose_is_not_verified`, in path form).

What is checked
---------------
A backticked token is a citation of this repository when it satisfies **both** conditions:

1. **Anchored** — its first path component is an existing top-level entry of the repo. That is what
   keeps the guard precise: `\\b\\d{12}\\b`, `--delete-bucket`, `x-amzn-requestid` and `https://…`
   are not anchored and are never considered. The anchor set is *derived* from the tree, not listed,
   because a hardcoded list walks straight past a new top-level directory — `platform/` arrived on
   2026-08-19 and would have been uncovered the day it appeared (`feedback_scope_as_namelist`).
2. **Extension-bearing, with the extension DERIVED from the tree.** The last component must end in a
   suffix that some in-scope file actually has. This is the rule that separates a path from the three
   things that look like one, all of them real examples from these documents:

   | Not a citation | Why |
   |---|---|
   | `lib/mcp.classify`, `lib/evidence.capture` | module-qualified **symbols**; no file has suffix `.classify` |
   | `tools/call`, `tools/list` | MCP JSON-RPC **method names** that collide with a real directory |
   | `f6_latency/F6-2_5`, `f10_billing/02` | **evidence subdirectory** ids, relative to the skipped `evidence/` tree |

   Deriving the suffix set rather than listing it keeps the ceiling: the day a `.parquet` lands in
   the tree, `results/x.parquet` becomes checkable without anyone remembering to allow it.

A `path:123` or `path:12-34` line reference is checked as the file it names — that is the citation.
A pytest node id is cut at `::`. Tokens carrying glob or placeholder metacharacters (`*`, `?`, `<`,
`{`, `...`) are excluded: `results/phase1/F6-*.json` and `results/phase1/<case>.json` are patterns.

**Dated records under `session-logs/` are out of scope** (`scan_scope.is_dated_record`). A log citing
a file that has since been renamed is an accurate record of what was true on its date; editing it to
agree with today would falsify it.

A path the prose itself declares absent — a specification, quoted incident output, or a gitignored
runtime file — is registered in `ABSENT_BY_DESIGN` with a reason, and two assertions keep that list
from rotting. See the comment above it: the invariant is not "every backticked path exists" but "a
path cited as evidence resolves, and a path cited as absent is declared as absent".

What this deliberately does not check: a citation of a *directory* with no extension, and a path
inside a dated log. Both are stated here rather than left for a reader to infer
(`feedback_guard_scope_is_a_claim`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib" / "tests"))
from scan_scope import is_dated_record, out_of_scope, walk_in_scope  # noqa: E402  shared predicates

# Anything inside single backticks with no whitespace in it.
TOKEN_RE = re.compile(r"`([^`\s]+)`")

# Placeholders and globs are not citations.
NOT_A_CITATION = set("*?<>{}[]|$")

# A trailing `:123` or `:12-34` or `:12,34` is a LINE REFERENCE, and the citation is the file it
# points at — `lib/mcp.py:343-349` is a claim about `lib/mcp.py`. Stripping it is what lets the
# guard check the commonest citation form in these documents instead of skipping it.
LINE_SUFFIX_RE = re.compile(r":\d+(?:[-,]\d+)*$")

# A floor on the guard's own denominator: a scan that recognised no citations would pass silently,
# which is the failure this repository has had twice (`feedback_zero_file_scan_is_error`). Measured
# 2026-08-20 at 1,000+ anchored citations across 40+ documents; the floor is set well below so
# ordinary editing does not red it, and far enough above zero to be a real assertion.
MIN_CITATIONS = 300
MIN_DOCUMENTS = 15

# ---------------------------------------------------------------------------------------------------
# NOT EVERY CITED PATH IS SUPPOSED TO EXIST.
#
# The first run of this guard reported 11 dangling paths, and only ONE was the defect it was written
# for. The other ten were of three kinds, and in each the surrounding sentence says so in words:
#
#   * a **specification** — the sentence's whole point is that the file has to be written
#     ("`…test_route_credential_reachability.py` does not exist. It must pin, at minimum: …");
#   * **quoted output** from a past incident, naming a transient file that was correctly deleted;
#   * a **local-only runtime file** that is gitignored by design and exists only while the runner is
#     provisioned.
#
# So "every backticked path exists" is the wrong invariant; the right one is "a path cited as evidence
# resolves, and a path cited as absent is registered as absent". A guard that forced the first reading
# would push an author to create a stub file to satisfy it, or to stop naming the file the work must
# produce — both worse than the defect.
#
# This is a name list, and a name list cannot notice a new name (`feedback_scope_as_namelist`) — here
# that is the intended property: each new non-existent cited path must be declared once, by hand, with
# a reason. `test_every_registered_absence_is_still_absent_and_still_cited` keeps it from rotting in
# either direction.
ABSENT_BY_DESIGN: dict[str, str] = {
    "f5_redteam/tests/test_route_credential_reachability.py":
        "SPECIFICATION. FUTURE-WORK item on F5-8's missing test file; both citations state that it "
        "does not exist and go on to list what it must pin.",
    "results/CROSSMAP-ACG-THREATS.json":
        "SPECIFICATION. The per-cell threat map figure 6 would read. Register item 28's closing "
        "condition is authoring it from the pinned OWASP v1.1 PDF; `whitepaper_figures.py` records "
        "figure 6 as BLOCKED and writes no image precisely because this file is absent.",
    "runner/.state/runner.json":
        "LOCAL-ONLY RUNTIME FILE. `runner/.state/` is gitignored and out of scan scope; the citations "
        "say so, and the point being made is that the real instance name is written there and "
        "deliberately nowhere else.",
    "evidence/ext.json":
        "QUOTED OUTPUT. DEVIATIONS reproduces a diagnostic that printed the wrong tree above the "
        "right path; the path is the quoted text, not a claim that the file is fetchable.",
    "results/checkpoints/F3-1__pii-ssn.json":
        "QUOTED OUTPUT. The transient checkpoint a unit test wrote during incident DEV-P1-17. Naming "
        "it is how the incident is identified; it was removed as part of the fix.",
    "results/checkpoints/T__main.json":
        "QUOTED OUTPUT. The path in a `StubClient` \"stub exhausted\" error reproduced in DEVIATIONS; "
        "`T` is the stub's placeholder case id, not a case.",
}


def _anchors() -> set[str]:
    """The top-level entries of the repository — the anchor set, derived, never listed.

    Derived because a hardcoded list is what a new top-level directory walks straight past
    (`feedback_scope_as_namelist`): `platform/` was added on 2026-08-19 and would have been
    uncovered on the day it appeared.
    """
    return {p.name for p in ROOT.iterdir()}


def _suffixes() -> set[str]:
    """Every file suffix present in the in-scope tree — the "is this a filename" test, DERIVED.

    Listing the extensions instead would repeat the defect this repo spent 2026-08-20 removing from
    `check_redaction.py`, where a nine-extension allowlist silently excluded 93 files
    (`feedback_scope_as_namelist`). Derived, a `.parquet` dropped into `results/` becomes checkable
    the day it lands, while `.classify` — a method name, not a file type — never does.
    """
    out = {p.suffix for p in walk_in_scope() if p.suffix}
    assert len(out) > 5, (
        f"only {len(out)} suffix(es) derived from the tree — with a near-empty set nothing is "
        f"recognised as a path and this guard reports clean over every document")
    return out


def _docs() -> list[Path]:
    """In-scope markdown, minus dated session records — see the module docstring."""
    return sorted(p for p in ROOT.rglob("*.md")
                  if not out_of_scope(p.relative_to(ROOT))
                  and not is_dated_record(p.relative_to(ROOT)))


def _citations(text: str, anchors: set[str], suffixes: set[str]) -> set[str]:
    out = set()
    for raw in TOKEN_RE.findall(text):
        tok = LINE_SUFFIX_RE.sub("", raw.split("::")[0].rstrip(".,;:"))
        if not tok or set(tok) & NOT_A_CITATION or "..." in tok:
            continue
        if tok.split("/")[0] not in anchors:
            continue
        # The last component must look like a FILE. Without this the guard reads MCP method names
        # (`tools/call`), module-qualified symbols (`lib/mcp.classify`) and evidence subdirectory ids
        # (`f10_billing/02`) as citations, and each false positive is a reason to delete the guard
        # rather than fix a document.
        if Path(tok).suffix not in suffixes:
            continue
        out.add(tok)
    return out


def test_every_cited_repo_path_exists():
    anchors, suffixes = _anchors(), _suffixes()
    docs = _docs()
    dangling: list[str] = []
    total = 0
    citing_docs = 0
    for doc in docs:
        cites = _citations(doc.read_text(encoding="utf-8"), anchors, suffixes)
        total += len(cites)
        citing_docs += 1 if cites else 0
        for tok in sorted(cites):
            if tok not in ABSENT_BY_DESIGN and not (ROOT / tok).exists():
                dangling.append(f"  {doc.relative_to(ROOT)} cites `{tok}`")

    assert total >= MIN_CITATIONS and citing_docs >= MIN_DOCUMENTS, (
        f"recognised only {total} citation(s) across {citing_docs} document(s), below the floor of "
        f"{MIN_CITATIONS}/{MIN_DOCUMENTS}. The extractor has stopped matching, so this guard is "
        f"reporting clean over prose it is not reading.")

    assert not dangling, (
        "these documents cite repo-relative paths that do not exist in the tree:\n"
        + "\n".join(dangling)
        + "\n\nA citation a reader cannot fetch is a claim with no evidence that reads exactly like "
          "a claim with evidence. Note there are TWO directories named `session-logs/` — this "
          "repo's and the outer ~/Downloads one — which is how this failed on 2026-08-20: the "
          "cited file existed, in the wrong tree. Copy the artifact in, or stop citing it. If the "
          "sentence's point is that the file does NOT exist — a specification, quoted output, or a "
          "local-only runtime file — add it to ABSENT_BY_DESIGN with the reason.")


def test_every_registered_absence_is_still_absent_and_still_cited():
    """`ABSENT_BY_DESIGN` rots in two directions, and both are silent without this arm.

    An entry whose file now **exists** is a waiver suppressing nothing, which is how a list like this
    grows past anyone's ability to audit it. An entry nothing **cites** any more is a claim about a
    document that has since been reworded — and the reason text attached to it is then describing a
    sentence that no longer exists (`feedback_vacuous_test_check`).
    """
    anchors, suffixes = _anchors(), _suffixes()
    cited: set[str] = set()
    for doc in _docs():
        cited |= _citations(doc.read_text(encoding="utf-8"), anchors, suffixes)

    for tok, reason in sorted(ABSENT_BY_DESIGN.items()):
        assert not (ROOT / tok).exists(), (
            f"{tok} now EXISTS, so its ABSENT_BY_DESIGN entry waives nothing. Remove the entry — with "
            f"it in place a later deletion of that file would go unnoticed. Registered reason: {reason}")
        assert tok in cited, (
            f"nothing cites {tok} any more, so its ABSENT_BY_DESIGN entry is describing a sentence that "
            f"has been reworded or deleted. Remove it. Registered reason: {reason}")
        assert len(reason) >= 60, f"{tok}'s reason is too short to be auditable: {reason!r}"


def test_the_guard_catches_a_dangling_citation():
    """The mutation arm, run against doctored text rather than the live tree.

    Without it, the arm above passes for an extractor that recognises nothing an author would
    actually write (`feedback_vacuous_test_check`). Both a plainly missing file and the real
    2026-08-20 shape — a path that exists in the OUTER `session-logs/` — must be caught.
    """
    anchors, suffixes = _anchors(), _suffixes()
    for fake in ("results/phase1/F99-1.json",
                 "session-logs/f6-day2-NOT-COPIED-IN.log",
                 "platform/build/does_not_exist.py",
                 "lib/gone.py:12-19"):            # a line reference still cites its file
        cites = _citations(f"Evidence: `{fake}` records the run.", anchors, suffixes)
        want = LINE_SUFFIX_RE.sub("", fake)
        assert want in cites, f"the extractor does not recognise `{fake}` as a citation"
        assert not (ROOT / want).exists(), f"{want} exists, so this arm asserts nothing"


def test_the_guard_does_not_fire_on_patterns_flags_symbols_or_method_names():
    """False positives are how a guard gets deleted rather than fixed.

    Every entry after the first row is a token that appears verbatim in this repository's documents
    and was reported as dangling by the first version of this extractor on 2026-08-20.
    """
    anchors, suffixes = _anchors(), _suffixes()
    for benign in (r"\b\d{12}\b", "--delete-bucket", "x-amzn-requestid", "SCAN_EXT",
                   "results/phase1/F6-*.json", "results/phase1/<case>.json",
                   "https://github.com/x/y", "~/Downloads/notes.md", "lib", "results",
                   "lib/mcp.classify", "lib/evidence.capture", "lib/awsclients.account_id()",
                   "tools/call", "tools/list",
                   "f3_efficacy/F3-10", "f6_latency/F6-2_5", "f10_billing/02",
                   "results/phase1/.../F6-1.json"):
        cites = _citations(f"see `{benign}` for detail", anchors, suffixes)
        assert not cites, f"`{benign}` was read as a citation of this repo: {cites}"


def test_the_suffix_set_is_derived_from_the_tree():
    """The ceiling on the rule above, asserted in both directions.

    It must contain the suffixes this repo's citations actually use — otherwise the guard silently
    stops checking them — and it must NOT contain the things that merely look like suffixes, which
    is what makes a dotted symbol reference distinguishable from a path.
    """
    suffixes = _suffixes()
    for present in (".md", ".py", ".json", ".csv", ".yaml", ".log", ".sha256"):
        assert present in suffixes, (
            f"no in-scope file has suffix {present}, so every citation ending in it is now invisible "
            f"to this guard — check whether those files moved or were deleted")
    for absent in (".classify", ".capture", ".account_id()"):
        assert absent not in suffixes, (
            f"{absent} is now a real file suffix in this tree, so module-qualified symbol references "
            f"ending in it will be read as dangling citations")


def test_the_anchor_set_is_derived_and_covers_the_directories_that_matter():
    """A hardcoded anchor list would have missed `platform/`, added the day before this file."""
    anchors = _anchors()
    for required in ("results", "claims", "lib", "runner", "session-logs", "FUTURE-WORK.md"):
        assert required in anchors, (
            f"{required} is no longer a top-level entry, so every citation of it is now invisible "
            f"to this guard — check whether it moved or was deleted")
