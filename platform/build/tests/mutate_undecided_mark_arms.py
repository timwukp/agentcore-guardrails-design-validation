#!/usr/bin/env python3
"""Apply named mutants to the SPA and require `walk_release.py`'s undecided-mark arms to die.

Not named `test_*`, for the same reason `mutate_census_arms.py` is not: it edits files in the tree,
rebuilds the bundle over `site/dist`, and must never run while a suite is reading either. Run it alone
and tee its output into `session-logs/`; it restores every file on its way out whatever happens.

WHY THE SUBJECT IS THE SPA AND NOT THE PAYLOAD
----------------------------------------------
`check_site_invariants.py` already holds the payload half of issue #37's presentation change, and 13
mutants in `test_check_site_invariants.py` kill it — a count `test_practice_evidence_map.py` re-derives
from the arm name each of them asserts, because a number written into a docstring is a number nobody
checks (`feedback_prose_is_not_verified`). None of them can see the half that matters to a
reader: whether the dagger, its accessible name, the dashed border and the explanatory panel actually
REACH the screen. The 2026-08-20 defect in this repository was exactly that gap — every diagram box's
class token was present in the CSS and all 38 rendered slate — so a presentation change verified only in
JSON is a change verified in the wrong artifact (`feedback_class_token_is_not_a_colour`,
`feedback_e2e_browser_verification`).

WHAT A KILL MEANS HERE
----------------------
`walk_release.py` exits 1 with a `PROBLEMS` list, so the rc alone would also go non-zero if some
unrelated arm broke. Each mutant therefore declares the SUBSTRING its problem message must contain, and
a mutant killed by a different message counts as a survivor with its output recorded — the red set is
read by name, not by exit code (`feedback_red_set_by_name`).

PRECONDITION
------------
`csp_preview.py` must already be serving `site/dist` on `--base`. The harness rebuilds the bundle
between mutants and re-links `site/dist/data`, which `vite build` deletes on every run; a walk against a
dist whose `data` link is missing fails for a reason that has nothing to do with the mutant, so the link
is asserted after every build rather than assumed.

    platform/build/tests/mutate_undecided_mark_arms.py --base http://127.0.0.1:8902
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SITE = REPO / "site"
DIST = SITE / "dist"
PAYLOAD = REPO.parent / "grx-site-payload"
WALK = REPO / "platform" / "build" / "walk_release.py"
PLAYWRIGHT_PYTHON = "/opt/homebrew/opt/python@3.12/bin/python3.12"

# (name, relative path, old, new, the problem substring the walk must print)
MUTANTS: list[tuple[str, str, str, str, str]] = [
    ("the register table stops passing the mark",
     "src/views/Overview.tsx",
     "<VerdictBadge v={r.verdict} undecided={r.undecided_subquestions} />",
     "<VerdictBadge v={r.verdict} />",
     "the register table renders 0 marked badge(s)"),
    # Design.tsx draws this chip twice — under a practice, and in the uncited-cases list at the foot of
    # the page — so the pattern carries the line after it. A mutant that matched both would be two
    # mutants wearing one name, and the survivor report could not say which producer was unheld.
    ("the design page's evidence chip stops passing the mark",
     "src/views/Design.tsx",
     "<VerdictBadge v={c.verdict} undecided={c.undecided} />\n          {says.has(c.case) ? (",
     "<VerdictBadge v={c.verdict} />\n          {says.has(c.case) ? (",
     "with no mark, while census.json leaves"),
    # NOT a mutant, deliberately, and recorded rather than left unsaid: the fourth `VerdictBadge` on
    # `/design` is the uncited-cases list, and every case in it is one the design document never cites —
    # which today excludes all three undecided cases. Dropping its mark would change nothing on screen,
    # so a mutant there could only ever survive. What holds it instead is the walk's rule itself, which
    # is per-CHIP and producer-agnostic: the day a marked case becomes uncited, its chip in that list is
    # compared like every other (`feedback_vacuous_test_check` — a mutant that cannot die measures the
    # fixture, not the guard).
    ("the dashed border becomes solid, leaving colour as the only cue",
     "src/styles.css",
     ".v-partial {\n  border-style: dashed;\n}",
     ".v-partial {\n  border-style: solid;\n}",
     "not dashed"),
    ("the dagger itself disappears and only the class remains",
     "src/components/ui.tsx",
     '          {" †"}',
     '          {""}',
     "renders its mark as ''"),
    ("the mark loses its accessible name",
     "src/components/ui.tsx",
     '          aria-label={`${t("ui.verdict.undecidedMark")} ${marked.join("; ")}`}',
     '          aria-label=""',
     "a dagger with no accessible name"),
    ("the verdict token is replaced by a friendlier phrase beside the mark",
     "src/components/ui.tsx",
     '      {v}\n      {marked.length ? (',
     '      {marked.length ? t("ui.undecided.heading") : v}\n      {marked.length ? (',
     "which no longer contains the bare token"),
    ("the explanatory panel loses the hook the probe finds it by",
     "src/components/ui.tsx",
     '<div className="note warn undecided" key={n}>',
     '<div className="note warn" key={n}>',
     "undecided panel(s) for 1 undecided sub-question(s)"),
    # `verdict_on_disk` is printed by the undecided panel AND by the restriction box below it, at
    # different indents. Anchoring on the sentence above it keeps this mutant on the panel.
    ("the panel stops naming the verdict on disk",
     "src/components/ui.tsx",
     '            {t("ui.undecided.diskUnchanged")}{" "}\n            <span className="mono" lang="en">\n              {r.verdict_on_disk}\n',
     '            {t("ui.undecided.diskUnchanged")}{" "}\n            <span className="mono" lang="en">\n              {""}\n',
     "never renders the verdict on disk"),
    ("the audit page's chip stops carrying the dagger",
     "src/views/Audit.tsx",
     '              {m.undecided.length ? " †" : ""}\n',
     "",
     "audit chip(s) carry the dagger against 1"),
    # The three producers the first pass of this change missed. Each was bare in a shipped build and
    # each is held by a different rule, so each gets its own mutant: a producer whose mark no probe
    # kills is a producer that will go bare again (`feedback_derive_from_every_producer`).
    ("the rulings table on /design stops passing the mark",
     "src/views/Design.tsx",
     "<VerdictBadge v={r.on_disk} undecided={r.undecided} />",
     "<VerdictBadge v={r.on_disk} />",
     "with no mark, while census.json leaves"),
    ("a cited case under a report measurement loses the dagger",
     "src/views/Report.tsx",
     '              {k.case} · {k.verdict}\n              {k.undecided.length ? " †" : ""}\n',
     "              {k.case} · {k.verdict}\n",
     "report chip(s) carry the dagger against 2"),
    ("the licence under a recommendation loses the dagger",
     "src/views/Report.tsx",
     '                      {l.case} · {l.verdict}\n                      {l.undecided.length ? " †" : ""}\n',
     "                      {l.case} · {l.verdict}\n",
     "report chip(s) carry the dagger against 2"),
]


def build() -> None:
    """Rebuild the bundle and re-establish the payload link `vite build` deletes."""
    proc = subprocess.run(["npm", "run", "build"], cwd=SITE, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"npm run build failed:\n{(proc.stdout + proc.stderr)[-3000:]}")
    link = DIST / "data"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(PAYLOAD)
    if not (link / "census.json").is_file():
        raise SystemExit(f"{link} does not resolve to a payload; every fetch would 404 and the walk "
                         f"would fail for a reason that is not the mutant")


def build_may_fail() -> str | None:
    """Same, but a compile error is a legitimate kill: tsc refusing the mutant is the strongest death.

    Returns the compiler's output when the build fails, otherwise None.
    """
    try:
        build()
    except SystemExit as e:
        return str(e)
    return None


def walk(base: str) -> tuple[int, str]:
    proc = subprocess.run([PLAYWRIGHT_PYTHON, str(WALK), "--base", base],
                          cwd=REPO, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8902")
    args = ap.parse_args(argv)

    files = sorted({rel for _, rel, _, _, _ in MUTANTS})
    original = {rel: (SITE / rel).read_text(encoding="utf-8") for rel in files}
    for rel in files:
        print(f"subject: site/{rel} ({len(original[rel])} bytes)")
    print(f"probe:   {WALK.relative_to(REPO)} --base {args.base}\n")

    build()
    t0 = time.monotonic()
    rc, body = walk(args.base)
    print(f"[control] no mutant -> rc {rc} ({'GREEN' if rc == 0 else 'RED'}) "
          f"in {time.monotonic() - t0:.0f}s")
    if rc != 0:
        print(body[-3000:])
        print("the control is red; a mutation result read off a red probe means nothing")
        return 2

    survivors: list[str] = []
    try:
        for i, (name, rel, old, new, phrase) in enumerate(MUTANTS, 1):
            source = original[rel]
            n = source.count(old)
            if n != 1:
                print(f"[{i:02d}/{len(MUTANTS)}] CANNOT APPLY ({n} match) {name}")
                survivors.append(f"{name} (pattern matched {n} times in site/{rel})")
                continue
            (SITE / rel).write_text(source.replace(old, new, 1), encoding="utf-8")
            t0 = time.monotonic()
            compile_error = build_may_fail()
            if compile_error is not None:
                print(f"[{i:02d}/{len(MUTANTS)}] killed  by the compiler  {name}")
                (SITE / rel).write_text(source, encoding="utf-8")
                continue
            rc, body = walk(args.base)
            hit = phrase in body
            killed = rc != 0 and hit
            print(f"[{i:02d}/{len(MUTANTS)}] {'killed ' if killed else 'SURVIVED'} rc {rc} "
                  f"in {time.monotonic() - t0:.0f}s  {name}")
            if not killed:
                where = "no PROBLEMS at all" if rc == 0 else f"died without {phrase!r}"
                print(f"            {where}")
                for line in body.splitlines():
                    if line.strip().startswith("- "):
                        print(f"            {line.strip()}")
                survivors.append(f"{name} ({where})")
            (SITE / rel).write_text(source, encoding="utf-8")
    finally:
        for rel in files:
            (SITE / rel).write_text(original[rel], encoding="utf-8")
            assert (SITE / rel).read_text(encoding="utf-8") == original[rel], \
                f"site/{rel} was not restored"
        build()

    rc, body = walk(args.base)
    print(f"\n[control] restored -> rc {rc} ({'GREEN' if rc == 0 else 'RED'})")
    print(f"{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed")
    for s in survivors:
        print(f"  SURVIVOR: {s}")
    return 0 if not survivors and rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
