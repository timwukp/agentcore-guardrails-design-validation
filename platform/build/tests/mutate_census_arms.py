#!/usr/bin/env python3
"""Apply named mutants to `census_rendered_surfaces.py` and require `test_census_cost_and_matching` to die.

Not named `test_*` on purpose: it edits a file in the tree and must never run as part of a suite that is
also reading that file. Run it alone, tee its output into `session-logs/`, and it restores the original on
its way out whatever happens.

WHY A SCRIPT RATHER THAN A PARAGRAPH IN A LOG
---------------------------------------------
"Mutation-checked, 13 mutants, all killed" is a claim, and a claim with no derivation cannot be re-run
after somebody edits the arms. Each entry below is `(name, old, new)` applied as an exact single
replacement, so a mutant that no longer applies -- because the line it targets was rewritten -- is a hard
error rather than a silent pass.

The no-mutant control runs FIRST and must be green: a harness that reports "every mutant was killed"
against a suite that was already red proves nothing (`feedback_vacuous_test_check`).

`PYTHONDONTWRITEBYTECODE` and a `__pycache__` sweep, because two of these mutants change the source
length by zero bytes within the same second, and a cached `.pyc` would serve the ORIGINAL to the test
that is supposed to see the mutant (`feedback_pyc_serves_the_mutant`).

    platform/build/tests/mutate_census_arms.py [--python PATH]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SUBJECT = REPO / "platform" / "build" / "census_rendered_surfaces.py"
ARMS = REPO / "platform" / "build" / "tests" / "test_census_cost_and_matching.py"

MUTANTS: list[tuple[str, str, str]] = [
    # ---- arrive(): the retry arithmetic item 42 exists to publish -------------------------------
    ("elapsed is the sum of every attempt, not the successful one",
     'return {"elapsed_ms": round(waits[-1], 1),',
     'return {"elapsed_ms": round(sum(waits), 1),'),
    ("the failed attempts are dropped instead of published",
     '"failed_attempt_ms": [round(ms, 1) for ms in waits[:-1]]}',
     '"failed_attempt_ms": []}'),
    ("attempts counts the allowance rather than what happened",
     '"attempts": len(waits),',
     '"attempts": attempts_allowed,'),
    ("one extra navigation past the published maximum",
     "for k in range(attempts_allowed):",
     "for k in range(attempts_allowed + 1):"),
    ("the retry re-requests the first url and is served from cache",
     "page.goto(url_for(k), wait_until=\"load\")",
     "page.goto(url_for(0), wait_until=\"load\")"),
    ("a timed-out attempt still waits for networkidle",
     '            waits.append((clock() - started) * 1000.0)\n            continue',
     '            page.wait_for_load_state("networkidle")\n'
     '            waits.append((clock() - started) * 1000.0)\n            continue'),
    ("the arrival floor never reaches the browser",
     "page.wait_for_function(ARRIVAL_JS, arg=min_chars, timeout=timeout_ms)",
     "page.wait_for_function(ARRIVAL_JS, arg=1, timeout=timeout_ms)"),
    ("the timeout never reaches the browser",
     "ARRIVAL_JS, arg=min_chars, timeout=timeout_ms)",
     "ARRIVAL_JS, arg=min_chars, timeout=1_000_000)"),
    ("the per-attempt hook is called once for the whole route",
     "        if before_attempt is not None:\n            before_attempt(k)",
     "        if before_attempt is not None and k == 0:\n            before_attempt(k)"),
    ("exhaustion returns a cost dict instead of refusing",
     "    raise ArrivalFailed(waits, last or RuntimeError(\"no attempt was made\"))",
     "    return {\"elapsed_ms\": 0.0, \"attempts\": len(waits), \"failed_attempt_ms\": []}"),
    ("the exception that ended the walk is swallowed",
     "raise ArrivalFailed(waits, last or RuntimeError(\"no attempt was made\"))",
     "raise ArrivalFailed(waits, RuntimeError(\"no attempt was made\"))"),

    # ---- the timeout's derivation, which is the whole of item 42's complaint --------------------
    ("the timeout is a literal again rather than a measured maximum times a stated multiple",
     "ROUTE_ARRIVAL_TIMEOUT_MS = SLOWEST_OBSERVED_MS * ARRIVAL_TIMEOUT_MULTIPLE",
     "ROUTE_ARRIVAL_TIMEOUT_MS = 30_000  #"),
    ("the headroom is tightened onto the observed distribution",
     "ARRIVAL_TIMEOUT_MULTIPLE = 25 ",
     "ARRIVAL_TIMEOUT_MULTIPLE = 1  "),

    # ---- fingerprint(): each rule mirrors a line of md.tsx --------------------------------------
    ("the anchor's href survives, so no linked sentence matches",
     'out = LIST_MARKER.sub("", MD_LINK.sub(r"\\1", "\\n".join(lines)))',
     'out = LIST_MARKER.sub("", "\\n".join(lines))'),
    ("table divider rows are text again",
     "lines = [ln for ln in str(s).splitlines() if not TABLE_DIVIDER.match(ln)]",
     "lines = list(str(s).splitlines())"),
    ("list markers are text again",
     'out = LIST_MARKER.sub("", MD_LINK.sub(r"\\1", "\\n".join(lines)))',
     'out = MD_LINK.sub(r"\\1", "\\n".join(lines))'),
    ("whitespace is collapsed rather than removed",
     'return unicodedata.normalize("NFC", "".join(MD_SYNTAX.sub(" ", out).split()))',
     'return unicodedata.normalize("NFC", " ".join(MD_SYNTAX.sub(" ", out).split()))'),
    ("markdown syntax is left in place, which is the defect item 43 names",
     'MD_SYNTAX.sub(" ", out)',
     'out'),

    # ---- classify_rows(): the denominator, and the ceiling that depends on it -------------------
    ("the second pass is gone: every body_md reaches no reader again",
     '        if not on_en:\n            f = fingerprint(s)',
     '        if False:\n            f = fingerprint(s)'),
    ("an empty fingerprint matches every route",
     "on_en = [r for r in routes if f and f in fp_text[(r, \"en\")]]",
     "on_en = [r for r in routes if f in fp_text[(r, \"en\")]]"),
    ("the zh side is compared verbatim while en matched stripped",
     '        on_zh = ([r for r in routes if s in walked[(r, "zh-TW")]["text"]] if basis == "verbatim"\n'
     '                 else [r for r in routes if fingerprint(s) in fp_text[(r, "zh-TW")]])',
     '        on_zh = [r for r in routes if s in walked[(r, "zh-TW")]["text"]]'),
    ("a drop is a continue again, so the count is 0 by construction",
     "            dropped.append({",
     "            _unused = ({"),
    ("the match basis is not published",
     '"match_basis": basis,',
     '"match_basis": "verbatim",'),
    ("an identifier is classified by corpus, so digests enter the backlog",
     '"classification": ("IDENTIFIER" if not WORD_SEPARATOR.search(s)\n'
     '                               else "ARTIFACT" if s in artifacts else "AUTHORED"),',
     '"classification": ("ARTIFACT" if s in artifacts\n'
     '                               else "IDENTIFIER" if not WORD_SEPARATOR.search(s)\n'
     '                               else "AUTHORED"),'),
    ("a drop is truncated like a row, hiding nothing but claiming a width it does not have",
     '                "text": s[:200],',
     '                "text": s[:400],'),

    # ---- write_ledger(): the excerpts this distributed document publishes -----------------------
    ("the ledger is written unmasked, as all six of 2026-09-21's were",
     "        json.dumps(redact.mask_quotations(census), indent=2, ensure_ascii=False, "
     "sort_keys=True)",
     "        json.dumps(census, indent=2, ensure_ascii=False, sort_keys=True)"),
    ("only the backlog is masked, so a dropped row still publishes what the slice cut",
     "    out.write_text(\n"
     "        json.dumps(redact.mask_quotations(census), indent=2, ensure_ascii=False, "
     "sort_keys=True)\n        + \"\\n\", encoding=\"utf-8\")",
     "    census = dict(census, backlog=redact.mask_quotations(census.get(\"backlog\") or []))\n"
     "    out.write_text(json.dumps(census, indent=2, ensure_ascii=False, sort_keys=True)\n"
     "                   + \"\\n\", encoding=\"utf-8\")"),
    ("chars is recomputed from the masked excerpt, so the mask moves a published number",
     "    out.write_text(\n"
     "        json.dumps(redact.mask_quotations(census), indent=2, ensure_ascii=False, "
     "sort_keys=True)\n        + \"\\n\", encoding=\"utf-8\")",
     "    census = redact.mask_quotations(census)\n"
     "    for _r in census.get(\"backlog\") or []:\n"
     "        _r[\"chars\"] = len(_r[\"text\"])\n"
     "    out.write_text(json.dumps(census, indent=2, ensure_ascii=False, sort_keys=True)\n"
     "                   + \"\\n\", encoding=\"utf-8\")"),
]


def run_arms(python: str) -> int:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for cache in (REPO / "platform" / "build").rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    proc = subprocess.run([python, "-m", "pytest", str(ARMS), "-q", "-p", "no:cacheprovider"],
                          cwd=REPO, env=env, capture_output=True, text=True)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=str(REPO / ".venv-oracle" / "bin" / "python"))
    args = ap.parse_args(argv)

    original = SUBJECT.read_text(encoding="utf-8")
    print(f"subject: {SUBJECT.relative_to(REPO)} ({len(original)} bytes)")
    print(f"arms:    {ARMS.relative_to(REPO)}")
    print(f"python:  {args.python}\n")

    rc = run_arms(args.python)
    print(f"[control] no mutant -> rc {rc} ({'GREEN' if rc == 0 else 'RED'})")
    if rc != 0:
        print("the control is red; a mutation result read off a red suite means nothing")
        return 2

    survivors: list[str] = []
    try:
        for i, (name, old, new) in enumerate(MUTANTS, 1):
            n = original.count(old)
            if n != 1:
                print(f"[{i:02d}/{len(MUTANTS)}] CANNOT APPLY ({n} match) {name}")
                survivors.append(f"{name} (pattern matched {n} times)")
                continue
            SUBJECT.write_text(original.replace(old, new, 1), encoding="utf-8")
            rc = run_arms(args.python)
            killed = rc != 0
            print(f"[{i:02d}/{len(MUTANTS)}] {'killed ' if killed else 'SURVIVED'} rc {rc}  {name}")
            if not killed:
                survivors.append(name)
    finally:
        SUBJECT.write_text(original, encoding="utf-8")
        assert SUBJECT.read_text(encoding="utf-8") == original, "the subject was not restored"

    rc = run_arms(args.python)
    print(f"\n[control] restored -> rc {rc} ({'GREEN' if rc == 0 else 'RED'})")
    print(f"{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed")
    for s in survivors:
        print(f"  SURVIVOR: {s}")
    return 0 if not survivors and rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
