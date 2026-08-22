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
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
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
MIN_ROUTES = 12
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
STATIC_ROUTES = ("/", "/findings", "/figures", "/register", "/citations", "/claims", "/method",
                 "/architecture", "/provenance", "/pipeline", "/audit", "/report")

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


def walk(base: str, routes: list[str]) -> dict[tuple[str, str], dict]:
    """Every route in every locale, in one browser, returning the collected nodes per (route, locale)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        cannot_run("playwright is not importable. `pip install playwright && playwright install "
                   "chromium`. This script measures what a browser renders and cannot fall back to "
                   "reading the source (`feedback_e2e_browser_verification`)")

    out: dict[tuple[str, str], dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for locale in LOCALES:
                ctx = browser.new_context(locale=locale, viewport={"width": 1280, "height": 900})
                # The locale is a stored reader choice, so it is written before any script runs rather
                # than clicked afterwards: a click leaves the first render in the other language, and
                # a walk that collected during that frame would report English on every route.
                ctx.add_init_script(
                    f"try {{ localStorage.setItem('agdv.locale', {json.dumps(locale)}); }} catch (e) {{}}")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                for i, route in enumerate(routes):
                    del errors[:]
                    # The cache-busting query is load-bearing, not hygiene. This is a HashRouter, so
                    # `index.html#/a` -> `index.html#/b` is a fragment change: the browser does not
                    # navigate, `wait_until="load"` resolves against the document already loaded, and
                    # `networkidle` was reached before React had even started the new route's fetch. The
                    # first run of this script measured `/findings` at 235 characters that way and the
                    # floor caught it. A distinct query per route makes each visit a real navigation.
                    page.goto(f"{base}/index.html?route={i}#{route}", wait_until="load")
                    # And a positive arrival condition rather than a quiet-network one. Idle is the
                    # absence of a signal, which is also what "has not started yet" looks like; this
                    # waits for content to BE there (`feedback_probe_must_reach_the_code`).
                    try:
                        page.wait_for_function(
                            "min => { const m = document.querySelector('main');"
                            " return !!m && m.innerText.trim().length >= min; }",
                            arg=MIN_RENDERED_CHARS_PER_ROUTE, timeout=15000)
                    except Exception as e:                        # noqa: BLE001 - reported, not swallowed
                        cannot_run(f"{route} in {locale} never rendered {MIN_RENDERED_CHARS_PER_ROUTE} "
                                   f"characters of main content within 15 s "
                                   f"({type(e).__name__}). Either the route is broken or the payload "
                                   f"file it reads is missing")
                    page.wait_for_load_state("networkidle")
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
    return out


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

    check_server(args.base)
    payload = args.payload.expanduser()
    strings = payload_strings(payload)
    artifacts, n_artifact_files = artifact_corpus()
    curated, n_curation_files = curation_corpus()

    cases = sample_cases(payload)
    routes = list(STATIC_ROUTES) + [f"/case/{cid}" for _, cid in cases]
    if len(routes) < MIN_ROUTES:
        cannot_run(f"{len(routes)} route(s) to walk, below the floor of {MIN_ROUTES}")

    walked = walk(args.base, routes)

    # ---------------------------------------------------------------- classify and match
    rows: list[dict] = []
    for s, paths in sorted(strings.items()):
        on_en = [r for r in routes if s in walked[(r, "en")]["text"]]
        if not on_en:
            continue                     # exists in the payload, reaches no reader
        on_zh = [r for r in routes if s in walked[(r, "zh-TW")]["text"]]
        rows.append({
            "chars": len(s),
            "payload_paths": sorted(set(paths)),
            "renders_on": on_en,
            "also_renders_in_zh": on_zh,
            # Identifier first: a string with no words is owed nothing regardless of whose it is, and
            # asking "whose words" about a digest produces an answer that is true and useless.
            "classification": ("IDENTIFIER" if not WORD_SEPARATOR.search(s)
                               else "ARTIFACT" if s in artifacts else "AUTHORED"),
            "also_in_curation": s in curated,
            "text": s[:400],
        })

    rendered = rows
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
        "measured_on": "see the file name; this script takes no clock reading",
        "how": {
            "base": args.base,
            "payload": str(payload),
            "locales": list(LOCALES),
            "routes": routes,
            "min_string_chars": MIN_STRING_CHARS,
            "artifact_files_read": n_artifact_files,
            "curation_files_read": n_curation_files,
        },
        "counts": {
            "payload_strings_of_prose_length": len(strings),
            "of_those_rendered_somewhere": len(rendered),
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
        "backlog_by_producer": producers,
        "backlog": sorted(untranslated, key=lambda r: (-r["chars"], r["text"])),
        "ambiguous": sorted(ambiguous, key=lambda r: (-r["chars"], r["text"])),
        "quoted_but_unmarked": sorted(unmarked, key=lambda r: (r["route"], r["text"])),
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(census, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                        encoding="utf-8")

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
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
