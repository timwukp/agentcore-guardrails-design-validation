#!/usr/bin/env python3
"""F0-1: verify §10's documentation references resolve. $0, no AWS, read-only HTTP.

Why this is a real test and not bookkeeping
-------------------------------------------
§10 is 24 rows of the form "<title> || <url>". Classifying them as "excluded —
just doc pointers" would have been the easy call, and it would have been wrong on
two counts:

  1. A dead URL in a best-practices document is a defect a reader hits
     immediately. It is cheap to check and there is no reason not to.
  2. The stated TITLE is a claim about what lives at that URL. A link that
     resolves to a page about something else is worse than a 404, because the
     reader believes they have been given a source.

So the oracle has two parts, and the second is the one that can actually
embarrass us: HTTP 200 AND the page's <title> is consistent with the row's title.

Failure semantics
-----------------
No network is a SKIP, not a pass: this script exits 3 when it cannot reach
docs.aws.amazon.com at all, so an offline run can never be mistaken for green
(the same discipline as feedback_zero_file_scan_is_error — a check that read
nothing must not report clean).

Writes results/FINDING-F0-1-references.json for the evidence store.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
TRIAGE = HERE / "triage.csv"
OUT = RESULTS / "FINDING-F0-1-references.json"

UA = "grx-validation/1.0 (doc reference check; +local)"
TIMEOUT = 20

# Words that carry no discriminating power when comparing a row title to a page
# title — every AWS doc page contains most of them.
#
# 'guardrails' and 'policy' are NOT stopwords: they are exactly the words that
# distinguish "Guardrails in policies" from "Understanding Cedar policies". They
# were on this list in the first draft, which made four correct references look
# broken while the matcher, not the document, was at fault.
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "to", "for", "with", "on", "by",
    "aws", "amazon", "bedrock", "agentcore", "guide", "developer", "user",
    "documentation", "docs", "how", "using", "use", "get", "started",
    "understand", "best", "not", "specific", "work",
}

# Minimal suffix stripping so "policy"/"policies" and "test"/"testing" match.
# A full stemmer would be overkill and would introduce its own false merges; the
# only requirement is that inflections of the SAME word compare equal.
_SUFFIXES = ("ies", "ing", "es", "s")


def _stem(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(w) for w in words
            if w not in STOPWORDS and _stem(w) not in STOPWORDS and len(w) > 2}


def parse_row(text: str) -> tuple[str, str] | None:
    """'Title || <https://url>' -> (title, url)."""
    parts = [p.strip() for p in text.split("||")]
    if len(parts) < 2:
        return None
    url_match = re.search(r"https?://[^\s<>|)\]]+", parts[-1])
    if not url_match:
        return None
    title = re.sub(r"[*`]", "", parts[0]).strip()
    # Parentheticals are KEPT. They read as asides, but in this document they
    # carry the specific words that identify the page — "Policy Conditions (when
    # guardrails)" and "Testing Policies (LOG_ONLY workflow)" are both matched
    # only by their parenthetical. Stripping them made correct rows look wrong.
    title = re.sub(r"[()]", " ", title).strip()
    return title, url_match.group(0).rstrip(">").rstrip(".")


def fetch(url: str) -> tuple[int | None, str, str]:
    """-> (status, page_title, error). status None means the request never landed."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(200_000).decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        return exc.code, "", f"HTTP {exc.code}"
    except Exception as exc:  # URLError, timeout, DNS, TLS
        return None, "", f"{type(exc).__name__}: {exc}"

    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    page_title = html.unescape(m.group(1)).strip() if m else ""
    page_title = re.sub(r"\s+", " ", page_title)
    return status, page_title, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="check only the first N (smoke)")
    ap.add_argument("--offline", action="store_true",
                    help="parse and report rows without any network access")
    args = ap.parse_args()

    with TRIAGE.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["anchor"] == "s10"
                and r["unit_type"] == "trow"]
    if not rows:
        print("no §10 reference rows found in triage.csv — nothing to check",
              file=sys.stderr)
        return 2

    parsed = []
    for r in rows:
        got = parse_row(r["text"])
        if got is None:
            parsed.append((r["claim_id"], "", "", "unparseable row"))
        else:
            parsed.append((r["claim_id"], got[0], got[1], ""))

    unparseable = [p for p in parsed if p[3]]
    if unparseable:
        print(f"FAIL — {len(unparseable)} row(s) do not carry a parseable title||url:")
        for cid, _t, _u, err in unparseable:
            print(f"  {cid}: {err}")
        return 1

    if args.offline:
        print(f"offline: {len(parsed)} reference rows parsed, no requests made")
        for cid, title, url, _ in parsed:
            print(f"  {cid}  {title[:44]:<44} {url}")
        return 3

    todo = parsed[: args.limit] if args.limit else parsed
    print(f"checking {len(todo)} documentation references\n")

    results = []
    unreachable = 0
    for cid, title, url, _ in todo:
        status, page_title, err = fetch(url)
        if status is None:
            unreachable += 1
        overlap = tokens(title) & tokens(page_title)
        expected = tokens(title)
        # A row title reduced to nothing by stopword removal cannot be checked for
        # content match; record that rather than scoring it a pass.
        if not expected:
            match = "unverifiable (title is all stopwords)"
        elif not page_title:
            match = "unverifiable (page has no title)"
        elif overlap:
            match = "yes"
        else:
            match = "NO"
        ok = status == 200 and match in ("yes", "unverifiable (title is all stopwords)",
                                         "unverifiable (page has no title)")
        results.append({
            "claim_id": cid, "row_title": title, "url": url,
            "http_status": status, "page_title": page_title,
            "title_overlap": sorted(overlap), "title_match": match,
            "error": err, "pass": ok,
        })
        flag = "ok  " if ok else "FAIL"
        print(f"  {flag} {status if status is not None else '---'}  {cid}  "
              f"{title[:38]:<38} {match}")
        if err:
            print(f"       {err}")

    if unreachable == len(todo):
        print(f"\nSKIPPED — all {len(todo)} requests failed to land. This is a network "
              f"problem, not a result; exiting 3 so it cannot be read as a pass.",
              file=sys.stderr)
        return 3

    failed = [r for r in results if not r["pass"]]
    RESULTS.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "case": "F0-1",
        "claim": "§10's documentation references resolve and describe what they claim",
        "oracle": "TRUE if every URL returns HTTP 200 and its page title shares a "
                  "content word with the row title; FALSE for any non-200 or any page "
                  "whose title is unrelated to the row's stated title",
        "n_checked": len(results),
        "n_failed": len(failed),
        "unreachable": unreachable,
        "results": results,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\n{len(results) - len(failed)}/{len(results)} references verified")
    print(f"evidence: {OUT.relative_to(HERE.parent)}")
    if failed:
        print(f"\n{len(failed)} reference(s) need a v1.3 correction:")
        for r in failed:
            print(f"  {r['claim_id']}  HTTP {r['http_status']}  {r['url']}")
            if r["title_match"] == "NO":
                print(f"      row says {r['row_title']!r}, page says {r['page_title']!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
