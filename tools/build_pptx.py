#!/usr/bin/env python3
"""Build the two v1.4 decks — one English, one zh-TW — from the two v1.4 Markdown files.

Run with the SYSTEM python3, not ``.venv-oracle``: python-pptx is installed only on the
homebrew interpreter, and the oracle venv is deliberately kept minimal.

    python3 tools/build_pptx.py                      # both decks, next to the .md files
    python3 tools/build_pptx.py --lang zh            # one language
    python3 tools/build_pptx.py --out-dir ~/Downloads

The two decks are generated from ONE slide plan (:mod:`deckgen.deck`), so they cannot
drift in slide count or order; ``Source`` refuses to start if the two documents stop
being structurally parallel.
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from deckgen import deck  # noqa: E402
from deckgen.mdsource import Source  # noqa: E402

OUT = {
    "en": "agentcore_guardrails_best_practices_v1.4.pptx",
    "zh": "agentcore_guardrails_best_practices_v1.4.zh-TW.pptx",
}


def find_doc(name, search):
    for base in search:
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    raise SystemExit(f"cannot find {name} in: {', '.join(search)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lang", choices=["en", "zh", "both"], default="both")
    ap.add_argument("--doc-dir", action="append", default=[],
                    help="extra directory to look for the two .md files (repeatable)")
    ap.add_argument("--out-dir", default=None, help="default: alongside the source .md files")
    args = ap.parse_args(argv)

    search = [*args.doc_dir, ROOT, os.path.expanduser("~/Downloads")]
    en_path = find_doc(deck.DOC_EN, search)
    zh_path = find_doc(deck.DOC_ZH, search)
    src = Source(en_path, zh_path)  # raises if the two documents are not parallel
    print(f"source  en {en_path}\n        zh {zh_path}\n        {len(src.tables['en'])} tables, parity OK")

    out_dir = os.path.expanduser(args.out_dir) if args.out_dir else os.path.dirname(en_path)
    os.makedirs(out_dir, exist_ok=True)
    langs = ["en", "zh"] if args.lang == "both" else [args.lang]
    warned = 0
    for lang in langs:
        path = os.path.join(out_dir, OUT[lang])
        n, warnings = deck.build(lang, src, path)
        print(f"built   {lang}  {n} slides  {os.path.getsize(path):,} bytes  {path}")
        for w in warnings:
            print(f"  WARN {lang}  {w}")
        warned += len(warnings)
    # A layout that could not be made to fit is a real defect in the deck, so it is
    # reported through the exit code as well — silence would read as "it all fits".
    return 1 if warned else 0


if __name__ == "__main__":
    raise SystemExit(main())
