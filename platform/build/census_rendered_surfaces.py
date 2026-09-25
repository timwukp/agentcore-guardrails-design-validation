#!/usr/bin/env python3
"""Which payload prose a reader actually SEES, in each language, measured in a browser.

WHY THIS IS NOT A STATIC ANALYSIS

The site review reported 582 payload strings as the translation backlog. That number is a property of
the payload files, and it is the wrong denominator for the question "how much English does a zh-TW
reader read". Three gaps separate the two:

  * A payload string can exist and render nowhere. `record` carries every field of every verdict file;
    the case page renders a chosen few. Counting the rest inflates the backlog with work no reader is
    waiting for, and an inflated backlog is one nobody starts.
  * A payload string can render and be CORRECT in English. Every sealed oracle sentence, every quoted
    artifact value, is deliberately verbatim — translating it would make this platform a paraphrase
    layer over its own evidence, which is refused. Counting those as owed makes the number unfixable.
  * A payload string can render in one language and not the other. That is the actual defect, and it is
    invisible to any analysis of the payload alone: the payload holds one string, and whether a reader
    sees it depends on which branch of a component the locale takes.

So this walks the built site in a real browser, in both locales, over every route, and reports the one
denominator that means anything: prose that RENDERS, is AUTHORED rather than quoted, and is IDENTICAL in
both languages. `feedback_e2e_browser_verification` — a UI claim needs a browser; and
`feedback_share_needs_the_window` — the share is meaningless until the window is named, so the output
carries all four counts, not just the ratio.

HOW `AUTHORED` IS DECIDED, AND WHY IT IS NOT A JUDGEMENT

Not by a hand-kept list of keys, and not by guessing from the key name. Two questions are asked of each
rendered string, in this order, and both are answered from the string's own bytes:

  IDENTIFIER  it contains no whitespace anywhere. A sha256 digest, an ARN, a CloudFormation resource id
              or a `results/phase1/*.json` path is not a sentence in any language, so no translation is
              owed and no `lang` marking changes how it is read. Asked FIRST, because "whose words are
              these" has a true and useless answer for a string that has no words.
  ARTIFACT    it occurs verbatim under `results/`, `claims/`, or in `PREREGISTRATION.yaml` — it is a
              producer's or a pre-registration's own words. It must stay English, marked `lang="en"`.
              Translating it is the substitution this platform exists to refuse.
  AUTHORED    neither. Either a human wrote it in `platform/curation/*.yaml`, or the build composed it.
              Both are this platform's own voice, and both are owed a translation.

The IDENTIFIER question is here because the first run of this census did not ask it and was wrong by
59%: it reported 755 owed strings, of which 445 were digests and paths. Both questions are decided from
the bytes, so a string that migrates between categories is re-measured rather than re-judged.

What the rules CANNOT see, each counted rather than argued about: a curation file that quotes an artifact
verbatim reads as ARTIFACT, which under-counts the backlog (see the ambiguous count); and a space-joined
list of identifiers reads as prose, which over-counts it.

WHAT `RENDERS` MEANS HERE

Text a reader can reach without leaving the route. Every `<details>` is opened before collection,
because content behind a disclosure is one click away and is not a different kind of absent — but the
flag is recorded per string, so a later decision to treat disclosures differently does not need a new
walk. Text hidden by `display:none` is NOT collected: the walker reads `innerText`, which the browser
computes after layout, so an element the CSS removes contributes nothing.

WHAT THIS SCRIPT IS NOT

Not a gate. It measures; `check_site_invariants.py` is where a measurement becomes a publish condition,
and the ratcheting ceiling it will hold comes from this file's output rather than from a number typed
into it. It also needs a running preview server and a browser, which a publish must not.

USAGE

    python3 platform/build/csp_preview.py --port 8901 &            # serves site/dist with the real CSP
    python3 platform/build/census_rendered_surfaces.py --out platform/census/<stamp>.json

Exit 0 = the walk completed. 2 = it could not run (no server, no browser, a route that failed to
render, a payload it could not read). A census that silently covered 3 routes of 14 would report a
small backlog for the same reason a scan of zero files reports no findings
(`feedback_zero_file_scan_is_error`), so every floor below is fatal rather than a warning.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# `lib/` on the path rather than the repo root, deliberately: this file runs under the interpreter
# that owns `playwright`, and putting the repo root first would make the `platform/` directory
# shadow the standard library's `platform` module for everything imported after it.
sys.path.insert(0, str(REPO / "lib"))
import redact  # noqa: E402  the mask for the excerpts this ledger publishes — see `write_ledger`

DEFAULT_PAYLOAD = Path.home() / "Downloads" / "grx-site-payload"
DEFAULT_BASE = "http://127.0.0.1:8901"

# Where a string has to occur to count as somebody else's words rather than this platform's.
ARTIFACT_ROOTS = ("results", "claims")
ARTIFACT_FILES = ("PREREGISTRATION.yaml",)

# A payload string shorter than this collides with ordinary page furniture — "n", "TRUE", "2026-08-12"
# all occur in a hundred places and matching them would report every route as rendering everything.
# The threshold is a measurement floor, not a claim that short strings do not need translating; short
# ones are covered by `strings.ts`, which is a typed dictionary and cannot have a missing translation.
MIN_STRING_CHARS = 24

# A string with no word separator anywhere in it is not a sentence in any language, so no translation is
# owed for it and no `lang` marking changes how it is read.
#
# This category is not a refinement anybody predicted; it came out of the first run of this census, which
# reported a 755-string backlog of which 445 turned out to be sha256 digests, ARNs, `results/phase1/*.json`
# paths and CloudFormation resource identifiers. They landed in the authored bucket for a defensible
# reason — a MANIFEST path is genuinely not quoted from inside any artifact's bytes — and the resulting
# number was still wrong by 59%, because "whose words are these" was answering a question nobody asked
# about a string that has no words. The test asked here is the one that decides the work: is this prose.
#
# There is no threshold to tune. English prose of >= 24 characters contains a space; the rule needs no
# list of identifier shapes to maintain and cannot fall behind a new one. What it CAN misfile is a
# space-joined list of identifiers ("results/a.json, results/b.json"), which reads as prose here and is
# counted as owed. That direction is the safe one: it over-states the backlog rather than hiding it.
WORD_SEPARATOR = re.compile(r"\s")

# Floors. Each is a collapse detector: the walk is worthless if it covered a handful of routes or found
# a handful of strings, and both failures look exactly like a small backlog.
MIN_ROUTES = 13
MIN_PAYLOAD_STRINGS = 200
MIN_RENDERED_CHARS_PER_ROUTE = 400

# The character floor above is not enough on its own, and this is not a hypothetical: the first run of
# this script hit a `site/dist/data` symlink that `npm run build` had removed, so every route rendered
# the payload-missing notice instead of its content. `/findings` in English still produced 734 characters
# of navigation chrome and CLEARED the floor; only the Chinese walk fell under it, and only because
# Chinese is denser per character. A floor on volume cannot tell chrome from content
# (`feedback_probe_must_reach_the_code`), so the route must also be shown to have received its data.
#
# Matched as the payload path plus the status, because that pair is what the error view renders and what
# no content view can contain. A route whose own prose happened to include the phrase would be a false
# positive worth having: it would stop the census until somebody looked.
FETCH_FAILED = re.compile(r"\./data/[\w./-]+\.json:\s*HTTP\s+\d{3}")

LOCALES = ("en", "zh-TW")

# The route table, mirroring `site/src/App.tsx`. Case pages are sampled rather than walked in full: 93
# case pages share one component, so the property under measurement (which of that component's prose is
# translated) is the same on all of them, while three chosen for their VERDICT exercise the three
# different branches of the caveat block — which is the part of that page that differs by case.
#
# "Mirroring" was, until 2026-09-10, a claim only this comment made: two hand-maintained lists of the
# same routes, and nothing that noticed when they disagreed. A route added to the app and not here
# would fall out of the census silently — the ceiling cannot catch it, because a page the walk never
# visits contributes zero strings, and zero is exactly what a fully-translated page contributes too.
# So `check_route_tables_agree()` below derives the app's side from `App.tsx` itself and refuses to
# walk anything until the two sets are equal (`feedback_derive_both_sides_of_a_gate`).
STATIC_ROUTES = ("/", "/findings", "/figures", "/register", "/citations", "/claims", "/method",
                 "/design", "/architecture", "/provenance", "/pipeline", "/audit", "/report")

# `<Route path="...">` literals in the app's route table. Parametrised routes (`/case/:id`) are sampled
# separately and the catch-all `*` is the 404 view, so both are excluded from the equality; everything
# else the app serves, this census must walk.
APP_ROUTE_RE = re.compile(r'<Route\s+path="(/[^":]*)"')


def check_route_tables_agree() -> None:
    """Fail before the walk if `STATIC_ROUTES` and `site/src/App.tsx` name different route sets.

    Derived from the app source rather than written down twice: the census walking 12 of 13 routes
    reports a smaller backlog than the site has, and that failure renders as SUCCESS. The regex is a
    claim about how routes are declared (`feedback_discovery_pattern_is_a_claim`), so its own yield is
    floored: an App.tsx this pattern cannot read at all is a reason to stop, not a clean diff.
    """
    app_tsx = REPO / "site" / "src" / "App.tsx"
    found = set(APP_ROUTE_RE.findall(app_tsx.read_text(encoding="utf-8")))
    if len(found) < 3:
        cannot_run(f"{len(found)} static route(s) parsed from {app_tsx}; the route declaration shape "
                   f"has changed and this censusʼs equality check can no longer read the appʼs side")
    if found != set(STATIC_ROUTES):
        only_app = sorted(found - set(STATIC_ROUTES))
        only_here = sorted(set(STATIC_ROUTES) - found)
        cannot_run(f"route tables disagree: App.tsx serves {only_app or 'nothing extra'} that this "
                   f"census does not walk, and this census names {only_here or 'nothing extra'} that "
                   f"App.tsx does not serve. A route the walk misses contributes zero strings, which "
                   f"is indistinguishable from a translated page, so the walk refuses to start.")

# The DOM walk. Kept as one expression so it runs in a single round trip per route, and so what it
# collects is readable in one place rather than assembled across several evaluate() calls.
COLLECT_JS = r"""
() => {
  // Every disclosure open first: content behind one is a click away, not absent. Recorded per node
  // below so a later decision to score them differently does not need another walk.
  const opened = [];
  document.querySelectorAll('details').forEach(d => { if (!d.open) { d.open = true; opened.push(1); } });
  const out = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      const p = n.parentElement;
      if (!p) return NodeFilter.FILTER_REJECT;
      const tag = p.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') return NodeFilter.FILTER_REJECT;
      if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      // What the CSS removes, a reader does not read. offsetParent is null for display:none subtrees.
      if (p.offsetParent === null && p.tagName !== 'BODY') return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  let n;
  while ((n = walk.nextNode())) {
    const p = n.parentElement;
    const langHost = p.closest('[lang]');
    out.push({
      text: n.nodeValue,
      tag: p.tagName.toLowerCase(),
      lang: langHost ? langHost.getAttribute('lang') : null,
      verbatim: !!p.closest('.verbatim'),
      behind_disclosure: !!p.closest('details'),
    });
  }
  return {nodes: out, disclosures_opened: opened.length,
          html_lang: document.documentElement.lang, title: document.title};
}
"""


def cannot_run(msg: str) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    raise SystemExit(2)


def norm(s: str) -> str:
    """Collapse whitespace and normalise Unicode form, so a match is not defeated by JSX wrapping.

    NFC because the payload and the DOM can disagree on composition for the same glyph, and a census
    that reported a translated string as missing because of a combining form would send somebody to
    retranslate prose that is already there.
    """
    return unicodedata.normalize("NFC", " ".join(str(s).split()))


# ------------------------------------------------------------------- matching a Markdown source string
#
# FUTURE-WORK item 43: this census asked whether a RAW payload string appears verbatim in the DOM, and
# every field the site renders as Markdown therefore matched nothing. `registers.json/items[]/body_md`
# is `**bold**`, backticks, pipe tables and list markers; `/register` renders it through
# `<Body src={i.body_md}/>` -> `Markdown` (`site/src/lib/md.tsx:267`), which emits React elements, so
# the reader's text is the body with every marker REMOVED and the raw string is not a substring of it.
# The row was dropped at a `continue` labelled "exists in the payload, reaches no reader" -- the exact
# opposite of the truth. 125,957 characters of this platform's own prose were absent from a backlog
# whose ceiling was 259 strings, and the drop left no trace, so the count of what was dropped was zero
# by construction (`feedback_zero_needs_a_ran_flag`).
#
# What this is NOT: a Markdown parser. Two parsers reading one format is how the other side moves
# without anybody noticing (`feedback_two_readers_one_format`), and `md.tsx` is the only renderer this
# site has. This is a lossy FINGERPRINT applied to both sides of the comparison -- strip the characters
# Markdown uses as syntax, collapse what is left -- so it can only ever say "these two texts share a
# body of words", which is the question the backlog actually asks. Its failures are recorded as such:
#
#   - It cannot see through a link. `[text](url)` renders as `text`, and the fingerprint keeps `url`,
#     so a string containing a link still misses. Those rows are published with `contains_link: true`
#     instead of vanishing.
#   - It could in principle match words that never occupied one reader-visible block. At >= 24
#     characters of prose that is a remote risk, and it is bounded rather than argued about: a row
#     matched only after stripping is published under its own `match_basis`, so the ceiling's one-time
#     correction is auditable string by string instead of arriving as a bigger number.
# Three rules, each mirroring one line of `site/src/lib/md.tsx` so that the fingerprint drops exactly
# what that renderer drops, and each cited here because a rule copied without its source is a second
# parser waiting to diverge:
#   MD_LINK     `/^\[([^\]]*)\]\(([^)\s]+)\)/`        md.tsx:74  -- the anchor keeps its TEXT, not its href
#   TABLE_DIV   `/^\s*\|?[\s:|-]+\|[\s:|-]*$/`        md.tsx:110 -- a divider row renders as no text at all
#   LIST_MARKER `/^(\s*)([-*+]|\d+[.)])\s+/`         md.tsx:204 -- a marker becomes an <li>, not text
#   MD_SYNTAX   the characters md.tsx consumes as markup (emphasis, code, heading, quote, cell wall)
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")
LIST_MARKER = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+", re.M)
MD_SYNTAX = re.compile(r"[*_`~#>|\[\]]+")
MD_FENCE = re.compile(r"^\s*(```+|~~~+)", re.M)


def fingerprint(s: str) -> str:
    """The comparable form of a string: what a reader's eye would have left after `md.tsx` ran.

    Applied to the payload string AND to the rendered text, because a fingerprint used on one side only
    is a different comparison in each direction.

    ALL whitespace is removed rather than collapsed. Stripping `` ` `` from ``the `ceiling`.`` leaves
    `the ceiling .` while the DOM says `the ceiling.`, so a collapse-only fingerprint missed every
    string whose markup ended mid-sentence -- which is most of them. Whitespace carries no information
    this census reads: the question is whether a body of words reaches a reader, and at >= 24 characters
    of prose a whitespace-blind containment test is not meaningfully weaker.
    """
    lines = [ln for ln in str(s).splitlines() if not TABLE_DIVIDER.match(ln)]
    out = LIST_MARKER.sub("", MD_LINK.sub(r"\1", "\n".join(lines)))
    return unicodedata.normalize("NFC", "".join(MD_SYNTAX.sub(" ", out).split()))


def payload_strings(payload: Path) -> dict[str, list[str]]:
    """Every string in the payload long enough to be prose, mapped to where it came from.

    Keyed by the STRING rather than by its path: the same sentence can be emitted at several paths and
    the question here is whether a reader sees it, not how many places produced it. The paths are kept
    as the value so a finding can name the file somebody has to edit.
    """
    if not payload.is_dir():
        cannot_run(f"{payload} is not a directory; there is no payload to take a census of")
    found: dict[str, list[str]] = {}
    files = sorted(payload.rglob("*.json"))
    if not files:
        cannot_run(f"no JSON under {payload}")

    def walk(node, path: str) -> None:
        if isinstance(node, str):
            if len(node.strip()) >= MIN_STRING_CHARS:
                found.setdefault(norm(node), []).append(path)
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    for f in files:
        try:
            walk(json.loads(f.read_text(encoding="utf-8")), f.relative_to(payload).as_posix())
        except (OSError, json.JSONDecodeError) as e:
            cannot_run(f"{f} is not readable JSON ({type(e).__name__}); a census that skipped a "
                       f"payload file would under-report the backlog and look like progress")
    if len(found) < MIN_PAYLOAD_STRINGS:
        cannot_run(f"only {len(found)} payload string(s) of >= {MIN_STRING_CHARS} characters, below the "
                   f"floor of {MIN_PAYLOAD_STRINGS}; the walk would report a tiny backlog because it "
                   f"read almost nothing")
    return found


def artifact_corpus() -> tuple[str, int]:
    """The bytes of every producer-written and pre-registered file, as one normalised haystack.

    One string rather than a per-file index because the only question asked of it is membership, and a
    single normalised haystack answers that without the census having to care which of 900 files a
    sentence came from. The file count is returned so an empty read is fatal rather than silently
    classifying every rendered sentence as this platform's own voice — which would make the backlog
    look enormous and the ARTIFACT category look empty.
    """
    parts: list[str] = []
    n = 0
    for root in ARTIFACT_ROOTS:
        base = REPO / root
        if not base.is_dir():
            cannot_run(f"{base} does not exist; ARTIFACT classification would be vacuous and every "
                       f"quoted sentence would be reported as owed a translation")
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".json", ".yaml", ".yml", ".csv", ".txt", ".md"):
                parts.append(norm(f.read_text(encoding="utf-8", errors="replace")))
                n += 1
    for name in ARTIFACT_FILES:
        f = REPO / name
        if not f.is_file():
            cannot_run(f"{f} does not exist; the pre-registration's own wording would be classified as "
                       f"this platform's prose")
        parts.append(norm(f.read_text(encoding="utf-8", errors="replace")))
        n += 1
    if n < 100:
        cannot_run(f"the artifact corpus is {n} file(s); too few to classify against")
    return "\n".join(parts), n


def curation_corpus() -> tuple[str, int]:
    """The authored curation files, for the AMBIGUOUS count only.

    A curation file may quote an artifact verbatim — a control's status sentence lifted from a verdict
    file, say. Such a string is ARTIFACT by the rule above, and the rule is right about what it must
    render as; but it is also a sentence a human wrote into a curation file, so reporting it as purely
    quoted overstates how much of the backlog is out of scope. Those strings are counted separately
    rather than reclassified, because deciding which of the two a given sentence is takes a human
    reading it, and this file measures.
    """
    base = REPO / "platform" / "curation"
    if not base.is_dir():
        cannot_run(f"{base} does not exist")
    files = sorted(base.glob("*.yaml"))
    if not files:
        cannot_run(f"no curation YAML under {base}")
    return "\n".join(norm(f.read_text(encoding="utf-8", errors="replace")) for f in files), len(files)


def sample_cases(payload: Path) -> list[tuple[str, str]]:
    """One case page per verdict, so all three branches of the caveat block get walked.

    Chosen from the payload rather than named here: a hardcoded id goes vacuous the day that case's
    verdict changes, and it would then be exercising a branch nobody thinks it is
    (`feedback_scope_as_namelist`).
    """
    want = ["TRUE", "FALSE", "INCONCLUSIVE", "RECORDED"]
    picked: list[tuple[str, str]] = []
    files = sorted((payload / "cases").glob("*.json"))
    if not files:
        cannot_run(f"no case pages under {payload}/cases")
    # Prefer a case that carries an authored caveat for TRUE and FALSE: that box is the newest rendered
    # surface and the one this round added, so a census that missed it would report on the site as it
    # was before the change.
    for verdict in want:
        best = None
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("verdict") != verdict:
                continue
            if isinstance(d.get("authored_caveat"), dict):
                best = d["case"]
                break
            best = best or d["case"]
        if best:
            picked.append((verdict, best))
    missing = [v for v in want if v not in {p[0] for p in picked}]
    if missing:
        cannot_run(f"no case page for verdict(s) {missing}; the caveat block's branches would go unwalked")
    return picked


def check_server(base: str) -> None:
    try:
        with urllib.request.urlopen(f"{base}/index.html", timeout=5) as r:
            if r.status != 200:
                cannot_run(f"{base}/index.html returned HTTP {r.status}")
    except (urllib.error.URLError, OSError) as e:
        cannot_run(f"cannot reach {base} ({type(e).__name__}). Start the preview server first:\n"
                   f"    python3 platform/build/csp_preview.py --port 8901")


# ---------------------------------------------------------------------------- what the walk costs
#
# THE TIMEOUT WAS A GUESS AND IS NOW A MEASUREMENT — FUTURE-WORK item 42. It sat at a flat 15 s, set
# when `/design` held one video and no chapter, and on 2026-09-18 the census failed on that route in
# zh-TW and then passed on an unchanged tree: a publish gate whose red was indistinguishable from its
# flake, where the remedy a flake trains into a maintainer ("run it again") is the same keystroke that
# would dispose of a real regression. Three things replace the guess, and all three are PUBLISHED into
# the census document rather than left in whoever-ran-it's terminal:
#
#   1. Every (route, locale) records its own elapsed milliseconds, so the next person to move this
#      number sets it from a distribution with its n and its load instead of from a figure somebody
#      once found sufficient (`feedback_narrow_interval_is_not_stability`).
#   2. A retry is COUNTED. "Passed on attempt k" is a fact about the measurement, and until now k
#      appeared in no file — only in a session log a human chose to write.
#   3. The walk stops downloading bytes no assertion in it will ever read: mp4 responses are aborted
#      and the count is published. `/design` carries eight `<video preload="metadata">` elements over
#      26.39 MB, and a media element's metadata fetch holds the document's load event open, so the
#      single-threaded preview server was being asked for megabytes before a census that measures TEXT
#      could begin. What this deliberately cannot see is a broken or missing video; that is
#      `media.json`'s job and the browser walk's, neither of which this file replaces.
# The measurement that replaces the guess. 2026-09-21: four runs of this script against
# `csp_preview.py` on 8901, 17 routes x 2 locales each, **136 navigations, 0 retries**, machine load
# average 4.78-6.58 (read with `sysctl -n vm.loadavg` at each run's start, in the log below):
#
#     min 554.6 ms | median 655.1 ms | p90 898.2 ms | max 1191.8 ms
#
# The slowest pair in every one of the four runs was `/design` in zh-TW — the route with the eight video
# elements, which is the route the 15 s guess died on. Per-run medians were 653.2 / 654.3 / 656.6 / 660.8
# ms, a 7.6 ms spread; the stopping rule was four runs, written into the loop before any number was read.
# Every figure above is re-derivable from `what_the_walk_cost` in the four ledgers
# `platform/census/rendered-surfaces-20260921T17{2955,3233,3504,3735}Z.json`, and the run log is
# `session-logs/a4-census-timing-20260921.log`.
#
# A narrow spread is not stability (`feedback_narrow_interval_is_not_stability`), so the timeout is NOT
# set near the observed distribution. It is the observed maximum times a stated multiple, because the
# job of this number is to bound a HANG, and a timeout tight enough to be informative about latency is
# also tight enough to turn a slow CI box into a refusal — which is the failure mode that produced item
# 42. Anybody moving it moves the multiple, in sight of the n and the load it was derived from.
SLOWEST_OBSERVED_MS = 1200          # 1191.8 ms, rounded up, over the 136 navigations above
ARRIVAL_TIMEOUT_MULTIPLE = 25       # 25x the slowest ever observed here; was 12.6x under the old guess
ROUTE_ARRIVAL_TIMEOUT_MS = SLOWEST_OBSERVED_MS * ARRIVAL_TIMEOUT_MULTIPLE    # 30_000
MAX_ROUTE_ATTEMPTS = 3
# Aborted so the load event is not held open by bytes this script never reads. Kept narrow on purpose:
# `.vtt` caption tracks are text and cheap, and blocking them would start deciding what the census can
# see about captions.
BLOCKED_MEDIA_GLOB = "**/*.mp4"

# A positive arrival condition rather than a quiet-network one. Idle is the absence of a signal, which is
# also what "has not started yet" looks like; this waits for content to BE there
# (`feedback_probe_must_reach_the_code`).
ARRIVAL_JS = ("min => { const m = document.querySelector('main');"
              " return !!m && m.innerText.trim().length >= min; }")


class ArrivalFailed(RuntimeError):
    """Every attempt timed out. Carries each attempt's elapsed ms so the report can name them all."""

    def __init__(self, waits_ms: list[float], last: BaseException):
        super().__init__(f"{len(waits_ms)} attempt(s) timed out")
        self.waits_ms = waits_ms
        self.last = last


def arrive(page, url_for, *, min_chars: int = MIN_RENDERED_CHARS_PER_ROUTE,
           timeout_ms: int = ROUTE_ARRIVAL_TIMEOUT_MS,
           attempts_allowed: int = MAX_ROUTE_ATTEMPTS,
           clock=time.monotonic, before_attempt=None) -> dict:
    """Navigate and wait for content, retrying a COUNTED number of times; return what it cost.

    Lifted out of `walk()` deliberately. Inline, its only caller was a live Playwright browser behind a
    four-minute walk, so a mutant in the retry arithmetic was unreachable by any test -- the same shape
    of defect as a writer living inside `main()`. `clock` is injectable because a test that measured
    elapsed time by sleeping would be measuring this machine's load
    (`feedback_harness_test_measures_the_machine`).

    `url_for(k)` must return a DISTINCT url per attempt: this is a HashRouter behind a cache-busting
    query, and a retry that re-requested the first url would be answered from cache and report a time
    the first attempt could not have achieved.
    """
    waits: list[float] = []
    last: BaseException | None = None
    for k in range(attempts_allowed):
        if before_attempt is not None:
            before_attempt(k)
        started = clock()
        page.goto(url_for(k), wait_until="load")
        try:
            page.wait_for_function(ARRIVAL_JS, arg=min_chars, timeout=timeout_ms)
        except Exception as e:                        # noqa: BLE001 - reported, not swallowed
            last = e
            waits.append((clock() - started) * 1000.0)
            continue
        page.wait_for_load_state("networkidle")
        waits.append((clock() - started) * 1000.0)
        return {"elapsed_ms": round(waits[-1], 1),
                "attempts": len(waits),
                "failed_attempt_ms": [round(ms, 1) for ms in waits[:-1]]}
    raise ArrivalFailed(waits, last or RuntimeError("no attempt was made"))


def classify_rows(strings: dict[str, list[str]], walked: dict[tuple[str, str], dict],
                  routes: list[str], artifacts: set[str] | frozenset[str],
                  curated: set[str] | frozenset[str]) -> tuple[list[dict], list[dict]]:
    """Which payload strings reach a reader, on what basis, and which this instrument cannot place.

    Returns `(rows, dropped)`. Lifted out of `main()` for the same reason as `arrive()`: the item-43
    logic below is the whole of the ceiling's correction, and inline it could only be exercised by a
    live browser walk.

    Two passes over the same routes, because two different questions are being asked and only one of
    them was being asked before. VERBATIM: the payload string appears in the rendered text as written.
    STRIPPED: it appears once Markdown syntax is removed from both sides -- which is what happens to
    every `body_md` the site renders through `md.tsx`. A string that matches neither is published with
    what is known about why, rather than dropped at a `continue`.
    """
    fp_text = {k: fingerprint(v["text"]) for k, v in walked.items()}
    rows: list[dict] = []
    dropped: list[dict] = []
    for s, paths in sorted(strings.items()):
        on_en = [r for r in routes if s in walked[(r, "en")]["text"]]
        basis = "verbatim"
        if not on_en:
            f = fingerprint(s)
            on_en = [r for r in routes if f and f in fp_text[(r, "en")]]
            basis = "markdown_stripped"
        if not on_en:
            dropped.append({
                "chars": len(s),
                "payload_paths": sorted(set(paths)),
                # The failure modes of the fingerprint that are mechanically visible, so the
                # unexplained remainder is a number somebody can chase rather than a mood.
                "contains_link": bool(MD_LINK.search(s)),
                "contains_code_fence": bool(MD_FENCE.search(s)),
                "text": s[:200],
            })
            continue
        on_zh = ([r for r in routes if s in walked[(r, "zh-TW")]["text"]] if basis == "verbatim"
                 else [r for r in routes if fingerprint(s) in fp_text[(r, "zh-TW")]])
        rows.append({
            "chars": len(s),
            "payload_paths": sorted(set(paths)),
            "renders_on": on_en,
            "also_renders_in_zh": on_zh,
            "match_basis": basis,
            # Identifier first: a string with no words is owed nothing regardless of whose it is, and
            # asking "whose words" about a digest produces an answer that is true and useless.
            "classification": ("IDENTIFIER" if not WORD_SEPARATOR.search(s)
                               else "ARTIFACT" if s in artifacts else "AUTHORED"),
            "also_in_curation": s in curated,
            "text": s[:400],
        })
    return rows, dropped


def write_ledger(census: dict, out: Path) -> None:
    """Serialize the ledger, with every string it QUOTES masked for publication.

    `platform/census/` is distributed, and every row here quotes a fixed-width excerpt of a payload
    string so a human can find the string the row is about. Measured 2026-09-22: six such excerpts
    per ledger failed `check_redaction.py`, in all six ledgers written that evening -- five because
    a 200-character slice cut through the `<account>` placeholder of the second ARN on the line,
    leaving a fragment the gate must fail closed on, and one because the excerpt quoted F5-7b's VPC
    CIDR into a third file. `redact.mask_quotation` is the fix and carries the whole argument; here
    the only design question is WHERE it runs.

    It runs at the writer, which is the last thing that happens, and that is the point. Every count
    in this document, and the verbatim/stripped matching that decides them, has already been
    computed against the raw strings -- so the mask cannot move a number, cannot move the backlog
    ceiling, and cannot change which route a string was found on. The mask being the last step is
    also why it is a WALK over the whole document rather than a rule per field: `text` is the field
    that failed today, and a masker that knows the field names is a masker the next field escapes.

    The lesson generalises past this file. `lib/redact.py` masks on the way into `results/` for the
    same reason -- a leak is in the path that writes a file, not in the file -- and this ledger was
    a second write path that nobody had put a mask on, because the strings reaching it were already
    masked. They were. It was the slicing that was not.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(redact.mask_quotations(census), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n", encoding="utf-8")


def walk(base: str, routes: list[str]) -> tuple[dict[tuple[str, str], dict], dict]:
    """Every route in every locale, in one browser.

    Returns the collected nodes per (route, locale) AND what the walk cost: per-route elapsed time,
    attempts taken, and media requests aborted. The second half is a deliverable, not diagnostics --
    see the block above this function.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        cannot_run("playwright is not importable. `pip install playwright && playwright install "
                   "chromium`. This script measures what a browser renders and cannot fall back to "
                   "reading the source (`feedback_e2e_browser_verification`)")

    out: dict[tuple[str, str], dict] = {}
    cost: dict[str, dict] = {}
    blocked = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for locale in LOCALES:
                ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 900})

                def _abort_media(route_obj) -> None:
                    nonlocal blocked
                    blocked += 1
                    route_obj.abort()

                # An aborted media request surfaces as an `error` event ON THE ELEMENT, which is not a
                # `pageerror` and does not reach the handler below: `<video>`'s children are fallback
                # content for a browser with no media support, so nothing this census reads changes
                # shape. That is asserted rather than assumed -- the rendered-character floor and the
                # `html_lang` check below both still have to pass on every route.
                ctx.route(BLOCKED_MEDIA_GLOB, _abort_media)
                # The locale is a stored reader choice, so it is written before any script runs rather
                # than clicked afterwards: a click leaves the first render in the other language, and
                # a walk that collected during that frame would report English on every route.
                ctx.add_init_script(
                    f"try {{ localStorage.setItem('agdv.locale', {json.dumps(locale)}); }} catch (e) {{}}")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                for i, route in enumerate(routes):
                    # The cache-busting query is load-bearing, not hygiene. This is a HashRouter, so
                    # `index.html#/a` -> `index.html#/b` is a fragment change: the browser does not
                    # navigate, `wait_until="load"` resolves against the document already loaded, and
                    # `networkidle` was reached before React had even started the new route's fetch. The
                    # first run of this script measured `/findings` at 235 characters that way and the
                    # floor caught it. A distinct query per route makes each visit a real navigation --
                    # and the attempt number is in it too, so a retry is a fresh navigation rather than
                    # a warmed cache reporting a time the first attempt could not have achieved.
                    try:
                        cost[f"{route}|{locale}"] = arrive(
                            page,
                            lambda k, i=i, route=route: f"{base}/index.html?route={i}.{k}#{route}",
                            # Errors are cleared per attempt: a pageerror thrown by a navigation that
                            # then timed out belongs to the attempt that threw it, and carrying it
                            # forward would fail the retry that succeeded.
                            before_attempt=lambda k: errors.clear())
                    except ArrivalFailed as fail:
                        waits = ", ".join(f"{ms / 1000:.1f} s" for ms in fail.waits_ms)
                        cannot_run(
                            f"{route} in {locale} never rendered {MIN_RENDERED_CHARS_PER_ROUTE} "
                            f"characters of main content in {len(fail.waits_ms)} attempt(s) of "
                            f"{ROUTE_ARRIVAL_TIMEOUT_MS / 1000:.0f} s ({waits}; "
                            f"{type(fail.last).__name__}). Either the route is broken or the payload "
                            f"file it reads is missing -- and unlike the flat 15 s this replaced, that "
                            f"is now a statement about {MAX_ROUTE_ATTEMPTS} independent navigations")
                    got = page.evaluate(COLLECT_JS)
                    text = norm(" ".join(n["text"] for n in got["nodes"]))
                    broken = FETCH_FAILED.search(text)
                    if broken:
                        cannot_run(f"{route} in {locale} rendered {broken.group(0)!r} — the view never "
                                   f"received its payload file, so what was collected is chrome. If "
                                   f"`site/dist/data` is missing, `npm run build` removed it: it is a "
                                   f"symlink to the payload that the preview expects a developer to "
                                   f"recreate")
                    if len(text) < MIN_RENDERED_CHARS_PER_ROUTE:
                        cannot_run(f"{route} in {locale} rendered {len(text)} character(s), under the "
                                   f"floor of {MIN_RENDERED_CHARS_PER_ROUTE}. A route that failed to "
                                   f"render contributes nothing and would look like a route with "
                                   f"nothing untranslated on it")
                    if got["html_lang"] != locale:
                        cannot_run(f"{route} reports <html lang={got['html_lang']!r}> while the walk "
                                   f"asked for {locale!r}; the locale did not take and every string "
                                   f"would be measured against the wrong language")
                    if errors:
                        cannot_run(f"{route} in {locale} raised {errors[:3]}; a route that threw may "
                                   f"have stopped rendering half way")
                    out[(route, locale)] = {"text": text, "nodes": got["nodes"],
                                            "disclosures_opened": got["disclosures_opened"],
                                            "title": got["title"]}
                ctx.close()
        finally:
            browser.close()

    # A zero here would mean the abort handler never fired, which on a tree whose `/design` route
    # carries eight `<video>` elements means the glob stopped matching -- and an unfired blocker is
    # indistinguishable from a fast page unless somebody says so out loud
    # (`feedback_zero_needs_a_ran_flag`).
    if blocked == 0:
        cannot_run(f"the media blocker aborted 0 request(s) over {len(routes)} route(s) x "
                   f"{len(LOCALES)} locale(s). Either no route embeds media any more -- in which case "
                   f"delete the blocker rather than leaving a waiver that does nothing -- or "
                   f"{BLOCKED_MEDIA_GLOB!r} no longer matches what the payload serves, and the walk's "
                   f"published timings are then measuring a load nobody declared")

    waits = sorted(cost.values(), key=lambda c: -c["elapsed_ms"])
    summary = {
        "timeout_ms_per_attempt": ROUTE_ARRIVAL_TIMEOUT_MS,
        # The timeout's derivation travels with every measurement, so a reader whose own run is slower
        # than the basis can see that immediately instead of discovering it as a refusal. A constant
        # published without the distribution it came from is the guess item 42 is about.
        "timeout_basis": {
            "slowest_observed_ms": SLOWEST_OBSERVED_MS,
            "multiple": ARRIVAL_TIMEOUT_MULTIPLE,
            "measured_over_navigations": 136,
            "measured_over_runs": 4,
            "measured_on": "2026-09-21",
            "load_average_range": [4.78, 6.58],
            "runs": ["platform/census/rendered-surfaces-20260921T172955Z.json",
                     "platform/census/rendered-surfaces-20260921T173233Z.json",
                     "platform/census/rendered-surfaces-20260921T173504Z.json",
                     "platform/census/rendered-surfaces-20260921T173735Z.json"],
            "log": "session-logs/a4-census-timing-20260921.log",
        },
        "max_attempts": MAX_ROUTE_ATTEMPTS,
        "media_requests_aborted": blocked,
        "media_blocked_glob": BLOCKED_MEDIA_GLOB,
        "navigations": sum(c["attempts"] for c in cost.values()),
        "retried": sorted(k for k, c in cost.items() if c["attempts"] > 1),
        "slowest_ms": waits[0]["elapsed_ms"] if waits else None,
        # `statistics.median`, not `sorted(...)[n // 2]`. There are 2 locales x an even route count, so
        # the upper-middle element would be published under a label that says something else
        # (`feedback_label_must_match_computation`).
        "median_ms": round(statistics.median(c["elapsed_ms"] for c in cost.values()), 1) if cost
                     else None,
        "per_route_locale": cost,
    }
    return out, summary


LEDGER_NAME = re.compile(r"^rendered-surfaces-(\d{8})T(\d{6})Z\.json$")
# How far ahead of the clock a stamp may sit. Not zero, because a caller composes the name a few seconds
# before the program parses it; small enough that a whole timezone offset cannot pass through.
STAMP_FUTURE_TOLERANCE_S = 120


def check_out_stamp(out: Path, now: datetime.datetime | None = None,
                    existing: list[Path] | None = None) -> None:
    """The file NAME is this measurement's only timestamp, so it is a field and needs a validator.

    `measured_on` in the output says the timestamp lives in the file name, and `build_site_data.py`
    selects the ledger the translation ceiling counts against with
    `sorted(CENSUS_DIR.glob("rendered-surfaces-*.json"))[-1]` — the newest **by name**. That makes the
    name load-bearing while leaving it to whoever types the command, which is a mandatory field with no
    producer (`feedback_mandatory_field_timing`).

    It failed exactly that way on 2026-09-18. Two ledgers were written with LOCAL time labelled `Z`
    (`…T151900Z.json` at 07:33:59 UTC, `…T155900Z.json` at 07:48:25 UTC — the machine is UTC+8), so they
    out-sorted every correctly stamped ledger for the following eight hours. A re-run measured that
    afternoon's tree at `…T095804Z`, and the build kept reading the earlier one: the census had been
    re-run, the number it produced was ignored, and every log line named the stale file while reporting a
    pass. Both were renamed to their true UTC times, derived from their own mtime, and this function is
    what stops the third one.

    Three refusals, all before the four-minute walk:
      * a name that is not `rendered-surfaces-<YYYYMMDD>T<HHMMSS>Z.json`, or whose digits are not a real
        UTC instant — a name the selector's sort cannot order meaningfully;
      * a stamp AFTER the clock (beyond `STAMP_FUTURE_TOLERANCE_S`), which is what local-time-as-`Z`
        looks like from here, and which would suppress every correct stamp until the offset elapsed;
      * a stamp not strictly newer than the newest ledger already present, because such a file cannot
        become the ledger anything reads — the walk would run, the JSON would be written, and the ceiling
        would keep counting the older measurement.

    The clock is read to VALIDATE, never to author: the stamp still comes from the caller, so the output
    stays a function of its inputs, and `now`/`existing` are injected so the arms holding this do not
    measure the machine they run on (`feedback_harness_test_measures_the_machine`).
    """
    m = LEDGER_NAME.match(out.name)
    if not m:
        cannot_run(f"--out {out.name} is not `rendered-surfaces-<YYYYMMDD>T<HHMMSS>Z.json`. The file name "
                   f"is this measurement's only timestamp and `build_site_data.py` picks the newest by "
                   f"NAME, so a name outside the convention is a measurement nothing will read.")
    try:
        stamp = datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=datetime.timezone.utc)
    except ValueError as e:
        cannot_run(f"--out {out.name}: {m.group(1)}T{m.group(2)}Z is not a real UTC instant ({e})")
        return
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ahead = (stamp - now).total_seconds()
    if ahead > STAMP_FUTURE_TOLERANCE_S:
        cannot_run(
            f"--out {out.name} is stamped {ahead / 3600:.1f} h AHEAD of the UTC clock "
            f"({now.strftime('%Y%m%dT%H%M%SZ')}). A stamp in the future is almost always local time "
            f"labelled Z, and because the ledger is chosen by name it would suppress every correct "
            f"stamp until that offset elapsed — the census would run and the ceiling would keep "
            f"counting an older measurement.")
    if existing is None:
        existing = sorted(out.parent.glob("rendered-surfaces-*.json")) if out.parent.is_dir() else []
    others = [p.name for p in existing if p.name != out.name and LEDGER_NAME.match(p.name)]
    if others and max(others) >= out.name:
        cannot_run(
            f"--out {out.name} is not newer than {max(others)}, which is already in "
            f"{out.parent}. `build_site_data.py` reads the newest by name, so this walk would spend four "
            f"minutes producing a ledger nothing selects — and every gate would keep reporting the older "
            f"one by name while passing.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--out", type=Path, required=True, help="where to write the census JSON")
    args = ap.parse_args(argv)

    # Checked BEFORE the browser walk, which costs about four minutes. `--out platform/census` —
    # naming the directory these files live in rather than a file inside it — spent that whole walk and
    # then died in `write_text` with `IsADirectoryError`, discarding the measurement. The write is the
    # last statement in the program, so every precondition on it that is not asserted here is a
    # precondition asserted at the most expensive possible moment.
    out = args.out.expanduser()
    if out.is_dir():
        cannot_run(f"--out {out} is a directory. It names the census FILE to write; the convention is "
                   f"platform/census/rendered-surfaces-<UTC stamp>.json, and `build_site_data.py` "
                   f"reads the newest match of that glob.")
    if not out.parent.is_dir() and out.parent.exists():
        cannot_run(f"--out {out}: its parent {out.parent} exists and is not a directory")
    check_out_stamp(out)

    check_route_tables_agree()
    check_server(args.base)
    payload = args.payload.expanduser()
    strings = payload_strings(payload)
    artifacts, n_artifact_files = artifact_corpus()
    curated, n_curation_files = curation_corpus()

    cases = sample_cases(payload)
    routes = list(STATIC_ROUTES) + [f"/case/{cid}" for _, cid in cases]
    if len(routes) < MIN_ROUTES:
        cannot_run(f"{len(routes)} route(s) to walk, below the floor of {MIN_ROUTES}")

    walked, walk_cost = walk(args.base, routes)

    # ---------------------------------------------------------------- classify and match
    rendered, dropped = classify_rows(strings, walked, routes, artifacts, curated)
    authored = [r for r in rendered if r["classification"] == "AUTHORED"]
    artifact = [r for r in rendered if r["classification"] == "ARTIFACT"]
    identifiers = [r for r in rendered if r["classification"] == "IDENTIFIER"]
    untranslated = [r for r in authored if r["also_renders_in_zh"]]
    ambiguous = [r for r in artifact if r["also_in_curation"]]

    # ---------------------------------------------------------------- who has to be edited
    #
    # A flat list of 755 sentences is not a plan, and the number of sentences is the wrong unit of work
    # anyway: `audit.json/markdown` is ONE string of 37 KB composed by `platform/audit/report.py` from
    # templates, so translating it means translating that program's templates, not that string. Grouping
    # by the payload path is what turns the backlog into the set of files somebody edits, and the group
    # key is DERIVED from the path rather than assigned by a rule somebody has to maintain.
    by_producer: dict[str, dict] = {}
    for r in untranslated:
        for p in r["payload_paths"]:
            # file + the first two path segments: enough to separate `audit.json/report/controls[...]`
            # from `audit.json/markdown`, and not so much that every array index is its own group.
            head = p.split("/")
            key = "/".join(head[:3]) if len(head) > 2 else p
            key = re.sub(r"\[\d+\]", "[]", key)
            g = by_producer.setdefault(key, {"strings": 0, "chars": 0, "routes": set()})
            g["strings"] += 1
            g["chars"] += r["chars"]
            g["routes"].update(r["renders_on"])
    producers = {k: {"strings": v["strings"], "chars": v["chars"], "routes": sorted(v["routes"])}
                 for k, v in sorted(by_producer.items(), key=lambda kv: -kv[1]["chars"])}

    # ---------------------------------------------------------------- quoted, but marked as quoted?
    #
    # A separate defect from the backlog, and one only a DOM walk can see. A quoted artifact sentence is
    # correct in English, but only if the markup says it is English: `lang` picks the font stack's CJK
    # fallback and tells a screen reader which phonology to use, so an unmarked artifact sentence on a
    # Chinese page is pronounced as Chinese and rendered in CJK glyph forms. `check_site_invariants.py`
    # holds a FLOOR on how many elements carry `lang="en"`, which is a collapse detector; it cannot say
    # whether the ones that matter are among them. This can, because it knows which strings are quoted.
    # Split the same way as the backlog and for the same reason: the first measurement of this defect
    # reported 106 nodes, and the samples were sha256 digests and `tools/whitepaper_figures.py`. A digest
    # is read out character by character in either language and its glyphs are identical in both font
    # stacks, so `lang` changes nothing about it; a quoted SENTENCE left unmarked is read aloud with
    # Mandarin phonology. Both are published, because a category dropped without a number is a silent cap.
    #
    # `text` is truncated at 400 chars, so compare a truncated node against a truncated string; a node
    # holding a 5 KB quotation still matches on its first 400 characters.
    prose_set = {r["text"] for r in artifact}
    ident_set = {r["text"] for r in identifiers}
    unmarked: list[dict] = []
    unmarked_identifiers = 0
    marked_prose = 0
    for route in routes:
        for node in walked[(route, "zh-TW")]["nodes"]:
            t = norm(node["text"])
            if len(t) < MIN_STRING_CHARS:
                continue
            in_prose = t[:400] in prose_set
            if node["lang"] == "en":
                marked_prose += in_prose
                continue
            if in_prose:
                unmarked.append({"route": route, "tag": node["tag"], "lang": node["lang"],
                                 "verbatim_class": node["verbatim"], "text": t[:200]})
            elif t[:400] in ident_set:
                unmarked_identifiers += 1

    # A zero above is worth nothing on its own. If quoted prose never occupies a whole text node — if it
    # always renders spliced together with surrounding words — then no node can ever match `prose_set`,
    # the unmarked count is structurally zero, and the arm is vacuous while reporting clean
    # (`feedback_vacuous_test_check`). The marked count is the denominator that distinguishes the two
    # readings: a large one says the match works and every matched sentence carries its mark; a zero one
    # says this measurement is incapable of finding the defect and must not be quoted as evidence.
    if not unmarked and not marked_prose:
        cannot_run("no quoted-prose node matched a payload string in either direction, so the "
                   "lang=\"en\" measurement cannot distinguish 'all marked' from 'unable to see it'. "
                   "Whole-node matching is the wrong probe for how this site renders quotations.")

    per_route = {}
    for r in routes:
        owed = [x for x in untranslated if r in x["renders_on"]]
        per_route[r] = {
            "authored_untranslated": len(owed),
            "authored_untranslated_chars": sum(x["chars"] for x in owed),
            "rendered_chars_en": len(walked[(r, "en")]["text"]),
            "rendered_chars_zh": len(walked[(r, "zh-TW")]["text"]),
            "disclosures_opened": walked[(r, "en")]["disclosures_opened"],
        }

    census = {
        # The stamp still comes from the caller — the output stays a function of its inputs — but it is
        # no longer unchecked: `check_out_stamp()` reads the clock to refuse a name in the future or one
        # no selector would pick. See its docstring for the two files that made it necessary.
        "measured_on": "see the file name, validated against the UTC clock by check_out_stamp()",
        "how": {
            "base": args.base,
            "payload": str(payload),
            "locales": list(LOCALES),
            "routes": routes,
            "min_string_chars": MIN_STRING_CHARS,
            "artifact_files_read": n_artifact_files,
            "curation_files_read": n_curation_files,
        },
        "what_the_walk_cost": walk_cost,
        "counts": {
            "payload_strings_of_prose_length": len(strings),
            "of_those_rendered_somewhere": len(rendered),
            "matched_verbatim": sum(1 for r in rendered if r["match_basis"] == "verbatim"),
            "matched_only_after_stripping_markdown": sum(
                1 for r in rendered if r["match_basis"] == "markdown_stripped"),
            "dropped_for_want_of_a_match": len(dropped),
            "dropped_and_containing_a_markdown_link": sum(1 for d in dropped if d["contains_link"]),
            "rendered_and_an_identifier_not_prose": len(identifiers),
            "rendered_and_artifact": len(artifact),
            "rendered_and_authored": len(authored),
            "rendered_authored_and_identical_in_both_locales": len(untranslated),
            "artifact_strings_also_present_in_a_curation_file": len(ambiguous),
            "producers_the_backlog_traces_to": len(producers),
            "quoted_prose_nodes_not_marked_lang_en_on_the_zh_page": len(unmarked),
            "quoted_prose_nodes_that_do_carry_lang_en_on_the_zh_page": marked_prose,
            "identifier_nodes_not_marked_lang_en_on_the_zh_page": unmarked_identifiers,
        },
        "what_each_count_is_not": {
            "payload_strings_of_prose_length":
                "Not a backlog. It includes every string the payload carries at any path, most of which "
                "no component reads.",
            "matched_only_after_stripping_markdown":
                "The size of FUTURE-WORK item 43, measured rather than argued. Every string in this "
                "class reaches a reader and was previously counted as reaching nobody, because the "
                "site renders it through md.tsx and the raw payload text -- markers and all -- is not "
                "a substring of what md.tsx emits. This is the whole of the ceiling's one-time "
                "correction: it is derived here, per string, so the correction arrives with its cause "
                "attached rather than as a ratchet that learned to rise.",
            "dropped_for_want_of_a_match":
                "The number this defect hid, and it was 0 by construction until now: a dropped row "
                "left no trace at all. It is NOT a count of strings no reader sees -- it is a count of "
                "strings THIS INSTRUMENT cannot place, which is a property of the matcher. Every one is "
                "published under `dropped` with its payload paths, so the remainder is auditable.",
            "dropped_and_containing_a_markdown_link":
                "The one failure mode of the fingerprint that is mechanically visible: `[text](url)` "
                "renders as `text` and the fingerprint keeps `url`, so the string cannot match. "
                "Published as a denominator for the drops, not as an excuse for them.",
            "rendered_and_an_identifier_not_prose":
                "Not a backlog and not a provenance claim. A digest, an ARN, a resource id or a "
                "`results/phase1/*.json` path has no words, so it is owed no translation and no `lang` "
                "marking; this count exists so those strings are visibly EXCLUDED from the backlog "
                "rather than quietly dropped from it. It says nothing about whose bytes they are.",
            "rendered_and_artifact":
                "Not work. These are a producer's or the pre-registration's own words and must stay "
                "English, marked lang=\"en\". Translating them would make this platform a paraphrase "
                "layer over its own evidence.",
            "rendered_authored_and_identical_in_both_locales":
                "The backlog, and the only count here that is one. A string in this set is this "
                "platform's own prose that a zh-TW reader reads in English.",
            "artifact_strings_also_present_in_a_curation_file":
                "The rule's own blind spot, counted rather than argued about: a curation file that "
                "quotes an artifact verbatim classifies as ARTIFACT, so this many strings could belong "
                "in either category and only a human reading them can say which.",
            "producers_the_backlog_traces_to":
                "Not a file count and not a task count. One key can be a template in a program "
                "(`audit.json/markdown` is composed by platform/audit/report.py) or a literal in a "
                "curation file; the key says where to look, not how much work is behind it.",
            "quoted_prose_nodes_not_marked_lang_en_on_the_zh_page":
                "Not part of the translation backlog and not fixed by translating anything: these "
                "sentences are correctly English. The defect is that the markup does not say so, so a "
                "screen reader on the zh-TW page applies Mandarin phonology to them and the CJK font "
                "fallback picks the wrong glyph forms. Counted here because only a DOM walk that knows "
                "which strings are quoted can see it; the invariant harness holds a floor on lang=\"en\" "
                "elements, which detects collapse but cannot say the right ones are marked.",
            "quoted_prose_nodes_that_do_carry_lang_en_on_the_zh_page":
                "The denominator for the count above, and the only thing that makes a zero there "
                "readable. It is not a quality measure: it says the whole-node match CAN fire, so a "
                "zero unmarked count means the marks are present rather than that the probe is blind.",
            "identifier_nodes_not_marked_lang_en_on_the_zh_page":
                "Published so the split above is auditable, and NOT filed as a defect: a digest or a "
                "path is pronounced character by character in either language and its glyphs do not "
                "differ between the two font stacks, so marking it changes nothing a reader perceives.",
        },
        "per_route": per_route,
        "dropped": sorted(dropped, key=lambda d: (-d["chars"], d["text"])),
        "backlog_by_producer": producers,
        "backlog": sorted(untranslated, key=lambda r: (-r["chars"], r["text"])),
        "ambiguous": sorted(ambiguous, key=lambda r: (-r["chars"], r["text"])),
        "quoted_but_unmarked": sorted(unmarked, key=lambda r: (r["route"], r["text"])),
    }

    write_ledger(census, out)

    c = census["counts"]
    print(f"census: {len(routes)} route(s) x {len(LOCALES)} locale(s) walked")
    print(f"  {c['payload_strings_of_prose_length']:5} payload string(s) of >= {MIN_STRING_CHARS} chars")
    print(f"  {c['of_those_rendered_somewhere']:5} render somewhere")
    print(f"  {c['rendered_and_an_identifier_not_prose']:5} of those have no word separator at all "
          f"(digest, ARN, path: not prose in any language)")
    print(f"  {c['rendered_and_artifact']:5} of those are quoted artifact (must stay English)")
    print(f"  {c['rendered_and_authored']:5} of those are this platform's own prose")
    print(f"  {c['rendered_authored_and_identical_in_both_locales']:5} <- BACKLOG: authored prose a "
          f"zh-TW reader reads in English")
    print(f"  {c['artifact_strings_also_present_in_a_curation_file']:5} ambiguous (quoted, but also in "
          f"a curation file)")
    print(f"  {c['producers_the_backlog_traces_to']:5} payload producer(s) the backlog traces to; the "
          f"largest five by characters:")
    for k, v in list(producers.items())[:5]:
        print(f"        {v['chars']:7} chars  {v['strings']:4} string(s)  {k}")
    print(f"  {c['quoted_prose_nodes_not_marked_lang_en_on_the_zh_page']:5} quoted SENTENCE(s) rendered "
          f"on the zh-TW page WITHOUT lang=\"en\", of "
          f"{c['quoted_prose_nodes_not_marked_lang_en_on_the_zh_page'] + marked_prose} matched")
    print(f"  {c['identifier_nodes_not_marked_lang_en_on_the_zh_page']:5} identifier node(s) likewise "
          f"unmarked (published for the split; not a defect)")
    print(f"  {c['matched_verbatim']:5} matched verbatim, "
          f"{c['matched_only_after_stripping_markdown']} only after stripping Markdown "
          f"(item 43), {c['dropped_for_want_of_a_match']} dropped for want of a match of which "
          f"{c['dropped_and_containing_a_markdown_link']} contain a link")
    w = walk_cost
    print(f"  cost: {w['navigations']} navigation(s) for {len(routes) * len(LOCALES)} "
          f"(route, locale) pair(s); median {w['median_ms'] / 1000:.1f} s, slowest "
          f"{w['slowest_ms'] / 1000:.1f} s against a {w['timeout_ms_per_attempt'] / 1000:.0f} s "
          f"timeout x {w['max_attempts']} attempt(s); {w['media_requests_aborted']} media request(s) "
          f"aborted")
    if w["retried"]:
        # "Passed on attempt k" is the honest reading of any census run, and until this line existed k
        # appeared only in a session log somebody chose to write (item 42).
        print(f"  RETRIED: {', '.join(w['retried'])} — this run passed on a later attempt, and the "
              f"census document records which")
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
