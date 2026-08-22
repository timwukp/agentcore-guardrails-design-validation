#!/usr/bin/env python3
"""The gate that stops the site from stating a claim its artifacts do not support.

WHY A SEMANTIC GATE, SEPARATELY FROM THE REDACTION GATE
-------------------------------------------------------
`gate_payload.py` asks "do these bytes leak an identifier". This asks a different question: "is every
claim these bytes let the UI render backed by something on disk". The two failures are unrelated. A
perfectly redacted payload can still say a case was replicated when it was measured once, and that is
the exact defect this project incurred on 2026-08-19 — a *process* claim ("a replication happened")
that no *artifact* supported.

The strategy is to make the claim and its evidence be checked by the same build that emits them, so a
false claim fails the PUBLISH rather than being corrected in a later erratum.

THE ARMS, and what each one would have caught
---------------------------------------------
1.  `manifest_liveness` — every output the manifest names exists, hashes to what it says, and the set
    of files on disk equals the set the manifest lists, both directions. A stale manifest beside fresh
    files is a provenance stamp with two readings (`feedback_provenance_stamp_liveness`).
2.  `replication_needs_two_days` — a case may only be presentable as replicated if its archive spans
    two distinct UTC calendar days AND a `day1_*` archive exists AND every archive file it names is on
    disk with the recorded sha256. Plus the count in `method.json` is re-derived here from
    `archive.json` rather than trusted: two numbers produced by two paths must be derived twice
    (`feedback_two_numbers_two_claims`). `archive.json` is keyed by ARTIFACT, not only by case — two
    keys (`F3-10_log_surface_join`, `F5-4a_logonly_read`) are sub-artifact snapshots with no census row
    and no verdict — so the derivation is restricted to keys the census knows, and a separate check
    requires every non-case key to carry no verdict. An archived verdict for something the census does
    not count would be a verdict outside every denominator. `pipeline.json` counts archived days in its
    own code path, so its per-case counts and its headline two-day total are cross-derived here too —
    that page is where a reader goes to ask "was this measured twice", and its total is the sentence
    they carry away whether or not the rows beneath it agree with it.
3.  `no_replication_claim_authored_by_the_build` — a forward guard over three kinds of value, because a
    replication claim is not always a boolean. Outside `record` (the derived layer, which the build
    writes): a key matching /replicat/ may not be TRUE for a case outside the two-day set; a VOCABULARY
    token (`two_or_more_archived_days_agreeing`, `no_archived_prior_day`, …) is classified against the
    number of archived days it asserts and checked against the archive in both directions, over- and
    under-claiming alike, with an unclassified token failing the gate rather than passing it; and PROSE
    must either appear verbatim in the repo file its document names or sit under a key that declares
    itself a rationale (`why_…`, `…_note`) and name no case and no calendar day. The words are what a
    reader actually believes — a page saying "two_or_more_archived_days_agreeing" is the 2026-08-19
    sentence whether or not any flag is set — and a boolean-only guard reads that page as making no
    claim at all. Inside `record` (a verbatim copy of the producer's evidence file,
    minus the heavy series arrays) such keys DO legitimately exist — F10-2's billing-scaling cells
    each carry `replicates_agree`, which is about repeated cells inside one run — so instead of
    excusing that subtree, every replication-named value in it is compared against the same path in
    the on-disk evidence file. Excusing a subtree is where the next instance hides
    (`feedback_guard_scope_is_a_claim`); proving the build authored nothing there costs one file read.
4.  `no_hardcoded_totals` — the seven load-bearing counts (93, 92, 91, 90, 46, 23, 20) may not appear
    in the built bundle as string literals. A typed total is a second source of truth that survives
    the next re-derivation and silently disagrees with it. STRING literals only: minified JS is full
    of bare `20`s and `23`s as offsets and lengths, so a bare-number rule would be unenforceable and
    would end up disabled.
5.  `no_pass_rate` — every occurrence of "pass rate" in the bundle must be preceded by "there is no",
    and at least one must exist. Not "must equal one exact sentence": the overview and the method page
    each deny it in their own words, and a rule that admitted only one wording would have to be
    widened every time the copy is edited, which is how a guard gets deleted. 46 TRUE over 91
    published is not 50.5% of anything — the denominators differ by definition and INCONCLUSIVE is a
    result, not a missing one.

    In both languages, and the Chinese half is not a courtesy: a zh page whose only statement about a
    pass rate was its silence would be a different platform from the en one. `沒有` must be
    IMMEDIATELY before `通過率` — Chinese negates by prefix, so there is no equivalent of the English
    few-words window — and the two counts must be EQUAL, which is what makes deleting the denial from
    one language fail instead of passing by having nothing left to check
    (`feedback_two_numbers_two_claims`). The arm reads bytes, so it cannot tell a sentence from a
    dictionary key: a key named `noPassRate` failed this arm on 2026-08-20 and was renamed
    `ovw.noRatio` rather than being excused, because widening the rule to permit a shape is how the
    guard would eventually be deleted. The failure message now says which of the two happened.
6.  `denominators_carry_definitions` — each of the four has prose long enough to be a definition, an
    integer `n`, and a named derivation source. A number whose definition is missing is the one a
    reader will divide by.
7.  `verdict_mix_sums_to_published` — the four verdict buckets must sum to the published denominator,
    with INCONCLUSIVE its own bucket.
8.  `citation_policy_is_wired_both_ways` — every restriction names a case in the census, and that
    case's row carries the restriction. A policy the case pages cannot see is decoration.
9.  `figures_are_real_pngs` — each present figure exists, matches its recorded sha256 and byte count,
    and starts with the PNG signature. A figure isn't verified until something looks at the bytes
    (`feedback_chart_encoding_defects`); a JSON error page saved as `.png` renders as a broken image
    and no JSON assertion sees it. A non-zero `numeric_check` does not fail the publish — shipping a
    known drift honestly is allowed — but the bundle must then contain the wording that renders it, so
    a payload cannot know it drifted while the page stays silent.
10. `oracles_are_sealed` — every case carries a non-empty `oracle_text` marked sealed, and the
    registry hash the census reports recomputed equals the declared one.
11. `pipeline_states_are_styled` — every state in `pipeline.json`'s vocabulary has a rule in the built
    stylesheet. The badge class is derived from the state name in the component, so a state added later
    renders unstyled, and an unstyled badge reads as a state with nothing wrong — which for STALE and
    NOT OBSERVED is the one wrong reading. TypeScript cannot see it: the class is a string the CSS never
    imports (`feedback_vitest_css_stub`).
12. `audit_report_is_licensed` — the published audit report is the only payload file that gives a reader
    an INSTRUCTION rather than a measurement, so every recommendation in it must rest on a case the
    register knows, whose verdict the census agrees with, which is TRUE or FALSE, and which the citation
    policy does not mark NEVER_CITE. `report.py` enforces the same rules while composing; re-checking
    them here is the difference between a program's word for its own behaviour and a property of the
    bytes being served. The report's quoted verdict mix is re-derived from the census (a third copy of
    those four numbers), withheld recommendations must each state why, and no key or string anywhere on
    the page may present a rate, a score or a percentage — a pass rate over these controls would divide
    "measured, and the guidance did not hold" by the same denominator as "never examined".
13. `audit_vocabularies_are_styled` — the same check as arm 11, over `controls.json`'s status and
    observation vocabularies, whose badge classes the audit views also derive from the payload token.
    Its wrong reading is the sharper one: an unstyled `not_measured` badge is a plain box, and a plain
    box beside a control reads as "nothing remarkable here" where the token means this study never
    examined that control.
14. `architecture_colours_are_licensed` — no box on either diagram is coloured by a verdict the census
    does not publish: a green box needs a citable TRUE, a red one a citable FALSE, a box supported only
    by restricted cases is coloured by none of them, and INCONCLUSIVE-only support may never read as
    validated. Plus the coverage ceiling in both directions (placed ∪ excluded == the census, disjoint)
    and the same styling check as arms 11 and 13 over the five status classes and the three edge routes.
    This arm exists because a diagram is the payload's most quotable artifact and the one that travels
    WITHOUT the case table under it — `check_architecture.py` and `derive_architecture()` both read the
    authored topology, and neither is a second reading of the colour that actually shipped.

    It also checks that the status colour REACHES the box, which the styling check above cannot see. On
    2026-08-20 every status token was in the served stylesheet and every box was drawn in the same
    neutral slate anyway: `.st-contested` and `.archbox` are both single-class selectors, `.archbox` was
    the later one, and its own `border` shorthand discarded the status colour — while the legend printed
    beside the diagram went on advertising five. So the stylesheet publishes each status colour as the
    custom property `--st` and the box rule reads it, and both halves of that are asserted here: a status
    that states a colour without publishing it, or a box rule that names its own border colour instead of
    reading the property, fails the publish.

15. `both_languages_shipped` — the Chinese edition is in the bytes being served: the `zh-TW` tag, the
    toggle's own label (`中文`, written in the language it switches TO), a FLOOR on how many distinct
    Chinese runs reach the bundle, a floor on `lang="en"` in the markup, and a `.verbatim` rule in the
    stylesheet. `strings.ts` makes a missing translation a type error and `i18n.test.ts` asserts what
    a type cannot see, but both are claims about the SOURCE; this arm exists for what happens between
    the source and the reader — a tree-shaken dictionary, a half-landed translation pass, a stale
    `dist/`. All of those ship a toggle that says 中文 above English headings, where an untranslated
    heading is indistinguishable from one deliberately quoted verbatim. The last two properties are
    the verbatim rule as the browser experiences it rather than as a comment describes it: `lang`
    chooses the font stack and the screen reader's phonology, and `.verbatim` is what makes a quoted
    English block look quoted rather than look like prose somebody forgot to translate.
16. `authored_caveats_are_marked` — the 49 case pages carrying a bound this platform WROTE must reach the
    reader marked as this platform's, not as the run's. The payload count agrees with the pages, the
    sentence sits outside `record` (which stays byte-identical to the verdict file), no authored sentence
    stands on a case whose record already speaks, all four provenance fields are present, and the bundle
    carries the head sentence in BOTH languages plus the provenance line. The styling half is a repeat of
    arms 11/13 with the lesson attached: `.note.authored` must not merely have a class token, it must
    declare `dashed` — a border STYLE, because a token that was in the stylesheet while every box rendered
    the same slate is a defect already shipped here once, and hue alone carries nothing in greyscale. The
    unreviewed count is a LEDGER, not a failure: all 49 are unreviewed today, so an arm that failed on it
    would be an arm that has to be disabled to publish.
17. `authored_prose_is_bilingual` — the payload prose this platform WROTE reaches a Chinese reader in
    Chinese, and the part that does not yet is a number that may only fall. Arm 15 checks that the
    Chinese edition shipped; this one exists because that edition was built on a false premise. The site
    rendered every payload string `lang="en"` and told a zh-TW reader it was quoted evidence; a browser
    census of both locales over every route (`census_rendered_surfaces.py`) measured 1,958 strings a
    reader reaches, of which 767 are quoted artifact and 316 are this platform's own sentences — the
    denominator definitions, the audit's promises about somebody's AWS account, the diagram colour
    wordings. Those three come out of `platform/census/rendered-surfaces-20260822T092500Z.json` and are
    quoted here WITH the file name, because every one of them moves when a component changes what it
    renders: 310 authored strings were reachable before the diagram status labels started serving their
    Chinese halves, and re-reading them from the newest census is the only way this paragraph stays a
    measurement. The one number a gate enforces is the backlog ceiling below, not any of these.
    So the arm checks three things: every `{en, zh}` value carries two non-blank and DIFFERENT
    halves (identical halves pass every structural check, give the reader nothing, and remove the string
    from the backlog, so the number would improve by exactly the work not done); a FLOOR on how many such
    values exist, because deleting the feature otherwise reports zero malformed ones; and a CEILING on
    how many of the census's own backlog paths still hold a bare string, checked in BOTH directions —
    above it is a regression, below it is a translation written without lowering the number, and slack
    left above the measurement is where the next regression hides. What it cannot see is stated on the
    function: whether a translation MEANS what it translates, and any authored surface added since the
    last census run.
18. `verdict_palette_is_readable` — every verdict the census publishes reaches the reader as a legible
    colour that is not a grey, and the palette has ONE source. Contrast against all three page
    backgrounds clears WCAG 2.1 SC 1.4.3 (4.5:1, the only cited floor in the arm); Lab chroma and
    pairwise ΔE clear two floors that are judgements and are labelled as such. That second half is the
    half with a defect behind it: `--v-inconclusive` shipped from the first commit as #7c8798, Lab chroma
    10.4, which is the chroma of this stylesheet's own `--fg-dim` and `--fg-faint` — the two colours it
    uses to mean "this matters less" — at ΔE 10 and ΔE 5 from them. So the verdict for 20 of 91 outcomes
    was drawn in the site's de-emphasis colour, directly under prose calling it a result rather than a
    missing one, and it passed AA at 4.66:1 the whole time it did. Rendering one of four outcomes as
    absent data computes by implication the pass rate this platform refuses to compute. Plus: no verdict
    colour appears as a hex literal in the JS bundle (four were typed into `CaseDetail.tsx`, two of them
    the TRUE and RECORDED hues spent on rows of a timeline containing no verdict), the favicon is drawn
    only in colours the sheet declares, and the icon is linked with a RELATIVE href — `/favicon.svg`
    404s under the `v/<stamp>/` prefix this site is published at, and a missing icon was the only
    console error on the landing route.

Exit 0 = all arms pass. 1 = a violation. 2 = the gate could not run (missing payload, unreadable
JSON): a gate that cannot run must not report clean (`feedback_guard_tool_exit_codes`).

Four groups of arms are pinned by a COMMITTED harness, `platform/build/tests/test_check_site_invariants.py`
— one mutant per property plus a no-mutant control, re-run on every suite: the replication arms (the
claim whose false form this project has already published once), the audit-report arm (the only payload
file that instructs a reader), arm 14 (the only one that states a conclusion about a component in a
single colour), and arms 5 + 15 (the only properties that are about a BUILD STEP rather than about a
claim in a payload file — nothing that reads the source can see a tree-shaken dictionary or a stale
`dist/`). The rest rest on the one-off exercise recorded below, which is a memory rather than a test
(`feedback_test_suite_over_memory`): it cannot notice the day an arm stops looking. Extending the
harness to them is register work, and the limit is stated here rather than left to be inferred from the
absence of tests. Arm 16 is pinned too, by eight mutants in the same harness (2026-08-22) — five over the
payload, three over `dist/` — because the styling half is the exact shape of the defect that got past arms
11 and 13 on 2026-08-20, and leaving it on a one-off exercise would repeat the choice that failed. It also
earned its keep before it had a single mutant: adding it turned three EXISTING tests in that harness red,
because `site/dist` predated the feature while the freshly built payload already carried the prose. A
stale-`dist/` defect arriving by accident is exactly what this arm is for.

MUTATION-CHECKED — the arms that existed on 2026-08-20 by a one-off exercise, 19/19; arm 14 by nine
committed mutants, arms 5 + 15 by eight more (2026-08-20, the Chinese edition), and arm 16 by eight
(2026-08-22, the authored caveats), each killed by the arm that watches the property it broke, run
against COPIES of the payload and `dist`
--------------------------------------------------------------------------------------------------
A no-mutant control ran first and exited 0, so a red run is attributable to the assertions rather than
to a copy the gate could not read at all. Two findings from that exercise are worth stating, because
both made the first version of this test worthless while it looked thorough:

* **`manifest_liveness` masked every other arm.** Any edit to a payload file changes its sha256, so
  the manifest arm fired first on all fourteen semantic mutants and the arms under test were never
  shown to fire at all — a red result for the wrong reason (`feedback_identical_output_wrong_assertion`
  in the opposite direction). Fixed by having the harness recompute the manifest after each mutation,
  which is also the realistic case: a defect that reaches publish arrives WITH a consistent manifest,
  because `build_site_data.py` hashes whatever it emitted, defect included.
* **One mutant never landed.** The typed-total mutant inserted itself after `const `, a string esbuild's
  minified output does not contain (it emits `var`/`let`), so the file was unchanged and the gate's
  clean exit proved nothing (`feedback_probe_must_reach_the_code`). The harness then asserted that
  every mutant changed at least one byte before running the gate.

The nineteen: no-mutant control; manifest sha256 flipped; unlisted file added; F6-5's two archives
re-dated to one day; a non-case archive key given a verdict; an archive's recorded sha256 corrupted; a
day-2 archive dropped from the payload with `method.json`'s counts made consistent with the omission;
an archive label re-dated away from the file it names; a one-day case flagged replicated in the derived
layer; a `record` value the producer never wrote; a typed `"46"`; a pass rate asserted; the drift
wording removed while `numeric_check` is non-zero; a definition cut to a stub; the verdict mix made not
to sum; a restricted case's page stripped of its badge; one PNG byte flipped; an "Access Denied" JSON
body saved as a `.png` with its recorded bytes and sha256 updated to match; one `oracle_text` blanked.

The eight for arms 5 and 15, all against a copied `dist/` because that is the layer they read: the
Chinese negation stripped (沒有通過率 -> 通過率, with the English half still passing); the Chinese term
deleted instead, which only the cross-language COUNT can see; `ovw.noRatio` renamed back to
`ovw.noPassRate`, the real collision, asserting the diagnostic that distinguishes a name from a claim;
`zh-TW` renamed to `zh-Hant`; 中文 replaced, so the dictionary is present and unreachable; the
dictionary thinned to ~100 distinct runs while both denials are preserved, so the kill is attributable
to the floor and not to arm 5; `lang:` renamed to `xlang:`, which the arm's first version survived and
which is why it now matches a whole property name; and `.verbatim` renamed in the stylesheet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = REPO / "results" / "phase1" / "archive"

# A replication claim in the derived layer is not always a boolean. `pipeline.json` states each case's
# replication state IN WORDS, and the words are what a reader actually believes: a page saying
# "two_or_more_archived_days_agreeing" is the 2026-08-19 sentence, whether or not any flag is set. So
# every replication-named STRING the build emits outside `record` is classified here against the number
# of archived prior days it asserts, and checked against the archive.
#
# Two tables rather than one, for the reason established for the date keys: a bare allow-list of claim
# strings cannot notice a new one (`feedback_scope_as_namelist`), and a bare deny-list is worse than
# useless here — a value it fails to recognise as a claim would pass silently, which is the exact
# failure this arm exists to catch. An unclassified replication-named string fails the gate with its
# path, so a new vocabulary has to be classified by whoever introduces it.
CLAIMS_N_ARCHIVED_PRIOR_DAYS = {
    # value -> the minimum number of distinct archived days it asserts
    "one_archived_prior_day": 1,
    "two_or_more_archived_days_agreeing": 2,
    "disagreeing": 1,          # a disagreement is still a second occasion, and a louder one
}
CLAIMS_NO_ARCHIVED_PRIOR_DAY = {
    # value -> checked in the other direction: the archive must hold nothing, or the payload is
    # under-claiming, which is a payload/archive disagreement in its own right
    "no_archived_prior_day",
}

# The other kind of replication-named string in the payload is PROSE — a finding's provenance paragraph,
# F6's replication requirement, the note explaining how this view counts. No table can adjudicate a
# paragraph against an archive, but excusing prose is where the next instance hides
# (`feedback_guard_scope_is_a_claim`), so it is admitted two ways and no third:
#
#   1. Traceable — it appears verbatim in the repo file the enclosing document names, which establishes
#      that the build copied it rather than composed it. This is the proof already used for `record`.
#   2. A rationale — prose under a key that DECLARES itself one (`why_…`, `…_note`, `note`), naming no
#      case and no calendar day. Such a sentence explains how a number is counted; it cannot assert that
#      a replication happened, because the two things a claim must name to be believed are exactly what
#      it may not contain, and the key it sits under says in advance that it is not a finding.
#
# The key-shape half is what closes the loophole the no-case/no-day half leaves open on its own: a
# paragraph can assert "both days were re-derived" without naming either. Under `provenance.replication`
# — a key that reads as a record — that must be somebody's authored sentence in a file on disk. Only a
# key whose own name says "rationale" may be composed here, and then only about counting.
VOCABULARY_TOKEN = re.compile(r"^[a-z][a-z0-9_]*$")
RATIONALE_KEY = re.compile(r"^(why_|note$|.*_note$)")
# A percentage anywhere in the audit page. `\d{1,3}` with a word boundary, so a figure like `1.2%` is
# caught and a bare `%` in prose is not: what is forbidden is a NUMBER presented as a rate.
PERCENTAGE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
CALENDAR_DAY = re.compile(r"20\d\d-\d\d-\d\d")
DEFAULT_PAYLOAD = REPO.parent / "grx-site-payload"
DEFAULT_DIST = REPO / "site" / "dist"

# The counts the platform must always derive. Kept as strings because that is the form the check
# looks for, and listed here rather than computed so that the list itself is reviewable.
FORBIDDEN_LITERALS = ("93", "92", "91", "90", "46", "23", "20")

# The one sentence allowed to contain the phrase.
PASS_RATE_DISCLAIMER = "There is no pass rate on this platform."

# The Chinese half of the same rule. `沒有` prefixes what it negates, so — unlike the English window,
# which has to allow "there is no" a few words back — the negation is required IMMEDIATELY before the
# term, and the term is pinned because it is the one a Chinese reader would grep the page for.
PASS_RATE_ZH = "通過率"
NO_ZH = "沒有"

MIN_DEFINITION_CHARS = 40

# Han ideographs. Deliberately no CJK punctuation: a "translation" consisting of `，` would satisfy a
# punctuation-inclusive range while saying nothing, and nothing is the state this looks for.
HAN = "㐀-䶿一-鿿豈-﫿"

# Characters that may appear INSIDE one Chinese run without ending it — punctuation, digits and Latin,
# because a translated sentence quotes `oracle_text`, a file name and a verdict word mid-clause.
RUN_INNER = HAN + r"0-9A-Za-z，。、：；「」『』（）？！—…·　\s"

# A floor on how much Chinese reaches the bundle, not a count. Measured 450 distinct runs on
# 2026-08-20 against a 481-entry dictionary; the floor sits a third below that so adding a string never
# fails the gate, while the failure this catches — half a dictionary, which is what tree-shaking, a bad
# merge or a half-finished translation pass actually produces — lands well under it. A single missing
# key is `i18n.test.ts`'s job; it can see keys, and this can only see bytes.
MIN_CJK_RUNS = 300

# A floor on `lang="en"` in the rendered markup. Measured 136 on 2026-08-20 and 160 on 2026-08-21,
# after the browser walk below. This is the verbatim rule expressed where it has effects: it selects the
# Latin font stack over the CJK one and tells a screen reader which phonology to use, so an artifact's
# own English sentence stripped of it is read aloud as though it were Chinese.
#
# WHAT THIS FLOOR CANNOT SEE, stated because the gap was found the hard way. A `lang="en"` in the source
# is ONE occurrence in the bundle however many elements it ends up governing at runtime: the mark on
# `Markdown`'s root covers every heading, table cell and code span of every artifact body on the site,
# and deleting it moves this count from 160 to 159. So this arm detects the mark being STRIPPED
# WHOLESALE — a renamed prop, a bundle built before the feature — and cannot detect a container that
# stopped marking its subtree. That is a DOM property, and the floor is deliberately not raised toward
# the measurement to imply otherwise: a floor near 160 would fail the publish on any refactor that
# consolidated two marks into one, while still missing the defect it looks like it covers.
#
# The check that DOES see it is the browser walk prescribed in `csp_preview.py` — every text node whose
# effective language is `zh-TW` but whose content is English prose. Run on 2026-08-21 over 18 routes in
# the Chinese locale it found six unmarked surfaces, the largest being every rendered markdown body, and
# reports zero after the fix.
MIN_VERBATIM_MARKS = 60


class Gate:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def fail(self, arm: str, msg: str) -> None:
        self.failures.append(f"[{arm}] {msg}")

    def note(self, arm: str, msg: str) -> None:
        self.notes.append(f"[{arm}] {msg}")

    def check(self, arm: str, ok: bool, msg: str, passed: str = "") -> bool:
        if ok:
            if passed:
                self.note(arm, passed)
            return True
        self.fail(arm, msg)
        return False


def cannot_run(msg: str) -> None:
    print(f"[gate cannot run] {msg}", file=sys.stderr)
    raise SystemExit(2)


def load(payload: Path, name: str) -> dict:
    path = payload / name
    if not path.is_file():
        cannot_run(f"{path} is missing; the payload is incomplete")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        cannot_run(f"{path} is not readable JSON: {exc}")
    return {}  # unreachable; keeps the type checker and `noImplicitReturns` habits honest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def days_from_labels(labels: list[str]) -> set[str]:
    """`day1_2026-08-10` / `day2_indecisive_2026-08-19` -> {'2026-08-10', '2026-08-19'}."""
    return {m.group(0) for label in labels if (m := re.search(r"\d{4}-\d{2}-\d{2}", label))}


# ---------------------------------------------------------------------------- arms

def arm_manifest_liveness(g: Gate, payload: Path) -> None:
    arm = "manifest_liveness"
    manifest = load(payload, "MANIFEST.json")
    outputs = manifest.get("outputs_sha256")
    if not isinstance(outputs, dict) or not outputs:
        g.fail(arm, "MANIFEST.json has no non-empty outputs_sha256")
        return
    on_disk = {
        p.relative_to(payload).as_posix()
        for p in payload.rglob("*")
        if p.is_file() and p.name != "MANIFEST.json"
    }
    listed = set(outputs)
    missing = sorted(listed - on_disk)
    extra = sorted(on_disk - listed)
    g.check(arm, not missing, f"the manifest names {len(missing)} file(s) that do not exist: "
                              f"{missing[:5]}")
    g.check(arm, not extra, f"{len(extra)} file(s) are in the payload but not in the manifest: "
                            f"{extra[:5]}. An unlisted file is one nothing verified.")
    drifted = [rel for rel, want in outputs.items()
               if rel in on_disk and sha256_file(payload / rel) != want]
    g.check(arm, not drifted,
            f"{len(drifted)} file(s) do not hash to the manifest's value: {drifted[:5]}. The stamp "
            "would then have two readings — the files, and the record of the files.",
            passed=f"{len(outputs)} outputs match their recorded sha256, set equality both ways")
    n_outputs = manifest.get("n_outputs")
    g.check(arm, isinstance(n_outputs, int) and n_outputs == len(outputs) + 1,
            f"n_outputs={n_outputs} but outputs_sha256 holds {len(outputs)} entries (+1 for "
            "MANIFEST.json itself)")


def arm_replication(g: Gate, payload: Path, census_cases: set[str]) -> dict[str, set[str]]:
    arm = "replication_needs_two_days"
    archive = load(payload, "archive.json").get("by_case", {})
    method = load(payload, "method.json")
    if not archive:
        g.fail(arm, "archive.json has no by_case block; the replication panel would have no source")
        return {}

    two_day: set[str] = set()
    for key, entries in archive.items():
        labels = [e.get("label", "") for e in entries]
        days = days_from_labels(labels)
        if len(days) >= 2 and key in census_cases:
            two_day.add(key)
            g.check(arm, any(lbl.startswith("day1_") for lbl in labels),
                    f"{key} spans {sorted(days)} but has no day1_* archive, so there is no "
                    "first-day file for a second day to be compared against")
        if key not in census_cases:
            # A sub-artifact snapshot. It may be archived, but it may not carry an adjudication: a
            # verdict for something with no census row is a verdict outside every denominator.
            verdicts = [e.get("verdict") for e in entries if e.get("verdict")]
            g.check(arm, not verdicts,
                    f"{key} is not a case in the census yet its archive records verdict(s) "
                    f"{verdicts}. Either the census is missing a row or an archive is asserting an "
                    "adjudication nothing counts.")
        for entry in entries:
            name = entry.get("file", "")
            path = ARCHIVE_DIR / name
            if not path.is_file():
                g.fail(arm, f"{key}: archive {name} is referenced but absent from {ARCHIVE_DIR}")
                continue
            digest = sha256_file(path)
            if digest != entry.get("sha256"):
                g.fail(arm, f"{key}: archive {name} hashes {digest[:12]}… but the payload records "
                            f"{str(entry.get('sha256'))[:12]}…")
            # The label is what the day count is derived from, so it may not be free text: it must be
            # the artifact's own name. Otherwise a payload could be internally consistent and still
            # wrong — every count in it derived from a label nothing on disk supports.
            g.check(arm, name == f"{key}__{entry.get('label')}.json",
                    f"{key}: label {entry.get('label')!r} does not name the file {name!r} it came "
                    "from, so the dates the replication panel counts are free text")

        # Set equality against the filesystem, not just existence. An archive file on disk that the
        # payload omits is a day the site cannot see — which is how an under-claimed replication and an
        # over-claimed one look identical from inside the payload.
        on_disk = {p.name for p in ARCHIVE_DIR.glob(f"{key}__*.json")}
        referenced = {e.get("file") for e in entries}
        g.check(arm, on_disk == referenced,
                f"{key}: {sorted(on_disk ^ referenced)} is in {ARCHIVE_DIR.name}/ or in the payload "
                "but not both")

    # Re-derived here rather than read: `method.json`'s count and `archive.json`'s labels are produced
    # by different code paths over the same evidence, so they must be derived twice and compared.
    declared = method.get("n_cases_with_two_distinct_archive_days")
    g.check(arm, declared == len(two_day),
            f"method.json says {declared} case(s) have two distinct archive days; re-deriving from "
            f"archive.json over census cases gives {len(two_day)} ({sorted(two_day)})",
            passed=f"{len(two_day)} case(s) span two distinct UTC days: {sorted(two_day)}")

    # Both directions over the KEY SET too, so a case dropped from the builder's map cannot agree with
    # it by being absent from both sides of a per-key comparison.
    declared_days = method.get("archive_days_by_case", {})
    days_by_case = {k: days_from_labels([e.get("label", "") for e in v])
                    for k, v in archive.items() if k in census_cases}
    with_days = {k for k, v in days_by_case.items() if v}
    g.check(arm, set(declared_days) == with_days,
            f"archive_days_by_case covers {sorted(set(declared_days) ^ with_days)[:5]} differently "
            "from the archive itself")
    mismatched = [
        key for key, entries in archive.items() if key in census_cases
        and set(declared_days.get(key, [])) != days_from_labels([e.get("label", "") for e in entries])
    ]
    g.check(arm, not mismatched,
            f"archive_days_by_case disagrees with the archive labels for {mismatched[:5]}")

    # A THIRD derivation of the same quantity, because `pipeline.json` is the page a reader visits to
    # ask "was this measured twice", and it counts archived days in its own code path. Two numbers
    # produced by two paths must each be derived (`feedback_two_numbers_two_claims`); and the total is
    # checked as well as the per-case values, because the total is the sentence — a page saying "0 cases
    # measured on two days" is believed whether or not the rows beneath it agree.
    pipeline = load(payload, "pipeline.json")
    p_cases = pipeline.get("cases") or {}
    g.check(arm, bool(p_cases), "pipeline.json carries no cases block, so the freshness view would "
                                "have nothing to render and this cross-check nothing to compare")
    off = [f"{c}: pipeline says {row.get('n_archived_prior_days')}, the archive holds "
           f"{sorted(days_by_case.get(c, set()))}"
           for c, row in sorted(p_cases.items())
           if row.get("n_archived_prior_days") != len(days_by_case.get(c, set()))]
    g.check(arm, not off,
            f"pipeline.json's archived-day count disagrees with archive.json for {off[:5]}")
    declared_two = (pipeline.get("totals") or {}).get("n_with_two_or_more_archived_days")
    g.check(arm, declared_two == len(two_day),
            f"pipeline.json's totals say {declared_two} case(s) have two or more archived days; the "
            f"archive gives {len(two_day)} ({sorted(two_day)})")
    return days_by_case


def arm_no_authored_replication_claim(g: Gate, payload: Path, census_cases: set[str],
                                      days_by_case: dict[str, set[str]]) -> None:
    arm = "no_replication_claim_authored_by_the_build"
    two_day = {k for k, v in days_by_case.items() if len(v) >= 2}
    derived_offenders: list[str] = []
    authored_in_record: list[str] = []
    unclassified: list[str] = []
    unattributable: list[str] = []
    n_derived = n_verbatim = n_worded = n_prose = n_note = 0

    def _squeeze(s: str) -> str:
        return " ".join(s.split())

    def source_named_above(doc: object, parts: list[str]) -> str | None:
        """The nearest enclosing object's repo-relative `source`, walking outward from the value."""
        for k in range(len(parts), -1, -1):
            node = at(doc, parts[:k])
            if isinstance(node, dict) and isinstance(node.get("source"), str):
                return node["source"]
        return None

    def replicat_paths(node: object, where: str, out: dict[str, object]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if re.search(r"replicat", str(key), re.IGNORECASE):
                    out[f"{where}/{key}"] = value
                replicat_paths(value, f"{where}/{key}", out)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                replicat_paths(value, f"{where}/{i}", out)

    def at(node: object, parts: list[str]) -> object:
        for part in parts:
            if isinstance(node, list):
                if not part.isdigit() or int(part) >= len(node):
                    return KeyError
                node = node[int(part)]
            elif isinstance(node, dict):
                if part not in node:
                    return KeyError
                node = node[part]
            else:
                return KeyError
        return node

    for path in sorted(payload.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        rel = path.relative_to(payload).as_posix()
        case_hint = path.stem  # cases/F6-5.json -> F6-5
        found: dict[str, object] = {}
        replicat_paths(data, "", found)
        if not found:
            continue

        # The verbatim half: `cases/<id>.json`'s `record` is the producer's evidence file with the
        # heavy series arrays split out. Anything replication-named in there must still be the
        # producer's value, byte for byte, at the same path.
        evidence: object = None
        if rel.startswith("cases/") and isinstance(data, dict) and data.get("verdict_file"):
            source = REPO / "results" / "phase1" / str(data["verdict_file"])
            if not source.is_file():
                g.fail(arm, f"{rel} names verdict_file {data['verdict_file']}, which is not on disk, "
                            "so its record cannot be checked against the producer's own bytes")
            else:
                evidence = json.loads(source.read_text(encoding="utf-8"))

        for where, value in found.items():
            parts = [p for p in where.split("/") if p]
            if parts and parts[0] == "record":
                n_verbatim += 1
                if evidence is None:
                    authored_in_record.append(f"{rel}:{where} (no evidence file to compare against)")
                elif at(evidence, parts[1:]) != value:
                    authored_in_record.append(
                        f"{rel}:{where} is {value!r} but the producer's file has "
                        f"{at(evidence, parts[1:])!r}"
                    )
                continue
            n_derived += 1
            # The case a claim is ABOUT may come from the filename (cases/F6-5.json) or from the path
            # inside a whole-register view (pipeline.json's /cases/F6-5/replication). Resolve it from
            # either, and treat an unattributable claim as a failure rather than skipping it: a
            # replication claim no reader can pin to a case is one no gate can check.
            case = next((p for p in parts if p in census_cases),
                        case_hint if case_hint in census_cases else None)
            if value is True and case not in two_day:
                derived_offenders.append(f"{rel}:{where} is true for {case}")
            if isinstance(value, str) and not VOCABULARY_TOKEN.match(value.strip()):
                n_prose += 1
                src = source_named_above(data, parts)
                if src is None:
                    named = sorted(c for c in census_cases
                                   if re.search(rf"\b{re.escape(c)}\b", value))
                    days = sorted(set(CALENDAR_DAY.findall(value)))
                    key = parts[-1] if parts else ""
                    if not RATIONALE_KEY.match(key):
                        unattributable.append(
                            f"{rel}:{where} is build-authored prose about replication under a key that "
                            f"does not declare itself a rationale, and no enclosing object names a "
                            f"repo-relative `source`, so nothing establishes the build did not compose "
                            f"the claim")
                    elif named or days:
                        unattributable.append(
                            f"{rel}:{where} is a build-authored rationale naming {(named + days)[:4]}. "
                            f"A rationale explains how a number is counted; naming a case or a day "
                            f"makes it an assertion about a measurement, which must come from a file")
                    else:
                        n_note += 1
                elif not (REPO / src).is_file():
                    unattributable.append(f"{rel}:{where} names source {src}, which is not on disk")
                elif _squeeze(value) not in _squeeze((REPO / src).read_text(encoding="utf-8")):
                    authored_in_record.append(
                        f"{rel}:{where} is prose that does not appear in {src}, so this build "
                        f"composed it")
            elif isinstance(value, str):
                n_worded += 1
                if value in CLAIMS_N_ARCHIVED_PRIOR_DAYS:
                    need = CLAIMS_N_ARCHIVED_PRIOR_DAYS[value]
                    if case is None:
                        unattributable.append(f"{rel}:{where} says {value!r}")
                    elif len(days_by_case.get(case, set())) < need:
                        derived_offenders.append(
                            f"{rel}:{where} says {value!r} for {case}, which asserts >= {need} "
                            f"archived day(s); the archive holds "
                            f"{sorted(days_by_case.get(case, set()))}")
                elif value in CLAIMS_NO_ARCHIVED_PRIOR_DAY:
                    if case is None:
                        unattributable.append(f"{rel}:{where} says {value!r}")
                    elif days_by_case.get(case):
                        derived_offenders.append(
                            f"{rel}:{where} says {value!r} for {case} but the archive holds "
                            f"{sorted(days_by_case[case])}, so the payload under-claims what was "
                            f"measured")
                else:
                    unclassified.append(f"{rel}:{where} = {value!r}")

    g.check(arm, not derived_offenders,
            f"the derived layer sets a replication flag for a case outside the two-day set: "
            f"{derived_offenders[:5]}",
            passed=f"{n_derived} replication-named field(s) in the derived layer ({n_worded} vocabulary "
                   f"state(s) checked against the archive, {n_prose - n_note} paragraph(s) found "
                   f"verbatim in the file their document names, {n_note} build-authored rationale(s) "
                   f"naming no case and no day); {len(two_day)} case(s) may be "
                   f"presented as measured on two archived days: {sorted(two_day)}")
    g.check(arm, not unclassified,
            f"a replication-named string in the derived layer is in neither "
            f"CLAIMS_N_ARCHIVED_PRIOR_DAYS nor CLAIMS_NO_ARCHIVED_PRIOR_DAY, so nothing checked it "
            f"against the archive: {unclassified[:5]}")
    g.check(arm, not unattributable,
            f"a replication claim names no case, so no archive can be compared against it: "
            f"{unattributable[:5]}")
    g.check(arm, not authored_in_record,
            f"a replication-named value under `record` differs from the producer's evidence file, so "
            f"the build authored it: {authored_in_record[:5]}",
            passed=f"{n_verbatim} replication-named field(s) under `record` are the producer's own "
                   "values at the same paths")


def arm_bundle_text(g: Gate, dist: Path) -> str:
    bundles = sorted(p for p in (dist / "assets").glob("*.js")) if dist.is_dir() else []
    if not bundles:
        cannot_run(f"no built bundle under {dist}/assets — nothing to check, which must not pass")
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in bundles)
    g.note("bundle", f"{len(bundles)} bundle(s), {len(text)} chars")

    arm = "no_hardcoded_totals"
    clean = True
    for literal in FORBIDDEN_LITERALS:
        # Quoted, and the whole literal: `"93"` but not `"2026-08-20"` and not a bare `93` offset.
        hits = re.findall(rf"""(["'`]){literal}\1""", text)
        clean &= g.check(arm, not hits,
                         f'the bundle contains the string literal "{literal}" {len(hits)} time(s). '
                         "Every total on this platform is derived from denominators.json at runtime; "
                         "a typed one survives the next re-derivation and disagrees with it silently.")
    if clean:
        g.note(arm, f"none of {FORBIDDEN_LITERALS} appears as a string literal")

    arm = "no_pass_rate"
    occurrences = list(re.finditer(r"pass[\s-]?rate", text, re.IGNORECASE))
    asserted = [m for m in occurrences
                if not re.search(r"there\s+is\s+no\s+$", text[max(0, m.start() - 24):m.start()],
                                 re.IGNORECASE)]
    # An occurrence with no space or hyphen in it is `noPassRate` — a dictionary key, not a sentence,
    # and the bundle carries keys as string literals like any other. It still fails, because the arm
    # reads bytes and cannot tell a reader's page from a lookup table, but it fails saying which of the
    # two things happened: renaming the key costs nothing, and widening the rule to excuse a shape is
    # how the guard would eventually be deleted.
    identifiers = sorted({m.group(0) for m in asserted if not re.search(r"[\s-]", m.group(0))})
    g.check(arm, not asserted,
            f'{len(asserted)} of {len(occurrences)} "pass rate" occurrence(s) are not preceded by '
            f'"there is no": {[text[max(0, m.start() - 60):m.end() + 40] for m in asserted[:2]]}. '
            "There is no denominator on this platform that a verdict count may be divided by."
            + (f" {len(identifiers)} of them are camelCase identifiers ({identifiers}), so this is a "
               "NAME spelling the phrase rather than a claim: name the key after what it denies "
               "(`noRatio`), the way `rep.noRatio` does." if identifiers else ""))
    g.check(arm, bool(occurrences),
            "the phrase does not appear at all, so this arm proved nothing: the UI must actively "
            f"deny a pass rate, and {PASS_RATE_DISCLAIMER!r} is the wording the overview uses",
            passed=f"all {len(occurrences)} English occurrence(s) of the phrase are denials")

    # The same rule in the other language, and not a courtesy: a Chinese page whose only statement
    # about a pass rate was its silence would be a different platform from the English one. `沒有` has
    # to be IMMEDIATELY before the term — Chinese negates by prefix, so there is no equivalent of the
    # English window, and two characters is the whole of the negation.
    zh = [i for i in range(len(text)) if text.startswith(PASS_RATE_ZH, i)]
    zh_asserted = [i for i in zh if text[max(0, i - len(NO_ZH)):i] != NO_ZH]
    g.check(arm, not zh_asserted,
            f"{len(zh_asserted)} of {len(zh)} occurrence(s) of {PASS_RATE_ZH!r} are not immediately "
            f"preceded by {NO_ZH!r}: "
            f"{[text[max(0, i - 30):i + 20] for i in zh_asserted[:2]]}")
    g.check(arm, len(zh) == len(occurrences),
            f"{len(occurrences)} English denial(s) but {len(zh)} Chinese: the two languages state the "
            f"same rule, so a count that differs means a denial was dropped from one of them — or that "
            f"a translation reached for a term other than {PASS_RATE_ZH!r}, which is the term this "
            "platform uses and the one a reader greps for",
            passed=f"{len(zh)} Chinese denial(s), matching the English count")
    return text


def arm_denominators(g: Gate, payload: Path) -> dict:
    arm = "denominators_carry_definitions"
    denominators = load(payload, "denominators.json")
    g.check(arm, len(denominators) >= 4, f"only {len(denominators)} denominator(s) in the payload")
    for name, block in denominators.items():
        definition = str(block.get("definition", ""))
        g.check(arm, len(definition) >= MIN_DEFINITION_CHARS,
                f"{name}'s definition is {len(definition)} chars; these four numbers differ for "
                "stated reasons and the statement is the point")
        g.check(arm, isinstance(block.get("n"), int), f"{name}.n is not an integer")
        g.check(arm, bool(block.get("derived_from")), f"{name} does not name what it was derived from")
    g.note(arm, ", ".join(f"{k}={v.get('n')}" for k, v in sorted(denominators.items())))
    return denominators


def arm_verdict_mix(g: Gate, payload: Path, denominators: dict) -> None:
    arm = "verdict_mix_sums_to_published"
    census = load(payload, "census.json")
    mix = census.get("verdict_mix", {})
    g.check(arm, "INCONCLUSIVE" in mix,
            "INCONCLUSIVE is not a bucket of its own in verdict_mix; it must never be folded into "
            "either decisive column")
    published = (denominators.get("published") or {}).get("n")
    total = sum(v for v in mix.values() if isinstance(v, int))
    g.check(arm, total == published,
            f"the verdict buckets sum to {total} but the published denominator is {published}. Two "
            "counts derived from the same files must agree, or one of them is describing a "
            "different set than its label says.",
            passed=f"{mix} sums to the published denominator {published}")


def arm_citation_policy(g: Gate, payload: Path, census_cases: set[str]) -> None:
    arm = "citation_policy_is_wired_both_ways"
    policy = load(payload, "citation_policy.json")
    restrictions = policy.get("restrictions", [])
    g.check(arm, bool(restrictions), "citation_policy.json has no restrictions; the badges the case "
                                     "pages render would come from copy instead of data")
    n_wired = 0
    for entry in restrictions:
        named = entry.get("cases")
        if not isinstance(named, list) or not named:
            g.fail(arm, f"a restriction names no cases: {json.dumps(entry)[:140]}")
            continue
        g.check(arm, bool(str(entry.get("reason", "")).strip()),
                f"the restriction on {named} states no reason, so the badge would assert a rule with "
                "no ground")
        for case in named:
            if case not in census_cases:
                g.fail(arm, f"the policy restricts {case}, which is not in the census")
                continue
            # The case PAGE is what a reader sees, and it renders only what its own file carries.
            page = payload / "cases" / f"{case}.json"
            if not page.is_file():
                g.fail(arm, f"{case} is restricted but has no case page in the payload")
                continue
            carried = json.loads(page.read_text(encoding="utf-8")).get("citation_restrictions") or []
            if not any(r.get("reason") == entry.get("reason") for r in carried):
                g.fail(arm, f"{case}'s page does not carry the restriction whose reason begins "
                            f"{str(entry.get('reason'))[:60]!r}, so the badge cannot render")
            else:
                n_wired += 1
    g.note(arm, f"{len(restrictions)} restriction(s) covering {n_wired} case page(s), each wired both "
                "ways between the policy and the page that renders it")


def arm_figures(g: Gate, payload: Path, bundle_text: str) -> None:
    arm = "figures_are_real_pngs"
    figures = load(payload, "figures.json")
    present = figures.get("present", [])
    g.check(arm, bool(present), "no figures in the payload")
    for entry in present:
        path = payload / "figures" / entry["file"]
        if not path.is_file():
            g.fail(arm, f"{entry['file']} is listed present but absent from the payload")
            continue
        data = path.read_bytes()
        g.check(arm, data[:8] == b"\x89PNG\r\n\x1a\n",
                f"{entry['file']} does not start with the PNG signature; an error page saved under a "
                ".png name renders as a broken image and no JSON assertion notices")
        g.check(arm, len(data) == entry.get("bytes"),
                f"{entry['file']} is {len(data)} B, recorded as {entry.get('bytes')} B")
        g.check(arm, hashlib.sha256(data).hexdigest() == entry.get("sha256"),
                f"{entry['file']} does not match its recorded sha256")
    rc = figures.get("numeric_check")
    g.check(arm, isinstance(rc, int),
            "figures.json carries no integer numeric_check, so the freshness badge would be derived "
            "from nothing. It must be the rc of whitepaper_figures.py --check, passed in.")
    if isinstance(rc, int) and rc != 0:
        # Shipping a known drift is allowed; shipping it silently is not.
        g.check(arm, "drifted (rc " in bundle_text,
                f"numeric_check is {rc} — the figures' numbers no longer match the values recorded "
                "when they were drawn — but the bundle contains no wording that renders a drift, so "
                "the page would show stale charts as if they were current")
    for missing in figures.get("missing", []):
        g.check(arm, bool(str(missing).strip()), "a missing figure is listed with an empty name")
    g.note(arm, f"{len(present)} PNG(s) verified byte for byte, numeric_check rc={rc}, "
                f"missing={figures.get('missing')}")


def arm_oracles(g: Gate, payload: Path) -> None:
    arm = "oracles_are_sealed"
    census = load(payload, "census.json")
    seal = census.get("seal", {})
    g.check(arm, seal.get("registry_sha256_declared") == seal.get("registry_sha256_recomputed"),
            "the oracle registry's declared hash differs from the recomputed one: an oracle changed "
            "after its measurement ran",
            passed=f"registry seal live over {seal.get('n_cases_declared')} declared oracles")
    cases = sorted((payload / "cases").glob("*.json"))
    g.check(arm, len(cases) >= 90, f"only {len(cases)} case file(s) in the payload")
    for path in cases:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not str(data.get("oracle_text", "")).strip():
            g.fail(arm, f"{path.name} has an empty oracle_text; the case page would show a verdict "
                        "with no falsifying condition beside it")
        if data.get("oracle_is_sealed") is not True:
            g.fail(arm, f"{path.name} does not mark its oracle sealed")
    g.note(arm, f"{len(cases)} case files carry a sealed, non-empty oracle")


def arm_pipeline_states_are_styled(g: Gate, payload: Path, dist: Path) -> None:
    """Every state the payload can render must have a rule in the built stylesheet.

    The badge class is DERIVED in the component (`WITHIN CADENCE` -> `s-within-cadence`) rather than
    looked up in a table, so a state added to the vocabulary later renders as a badge with no rule —
    and an unstyled badge reads as a state with nothing wrong, which for STALE or NOT OBSERVED is the
    one wrong reading. Nothing in TypeScript can catch this: the class name is a string the CSS never
    imports (`feedback_vitest_css_stub`), so it is checked here, against the bytes that get served.
    """
    arm = "pipeline_states_are_styled"
    states = load(payload, "pipeline.json").get("states") or []
    g.check(arm, bool(states), "pipeline.json declares no state vocabulary, so this arm would be "
                               "vacuous and the freshness view would have nothing to colour")
    sheets = sorted((dist / "assets").glob("*.css")) if (dist / "assets").is_dir() else []
    if not sheets:
        cannot_run(f"no stylesheet under {dist}/assets — the badge classes cannot be checked, and a "
                   "missing check is not a pass")
    css = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sheets)
    # A whole class token, not a substring: `.s-stale` occurs inside `.s-stale-DISABLED`, so a substring
    # test would call a renamed-away rule present. The negative lookahead is what makes the mutant in
    # `test_check_site_invariants.py` die instead of surviving with the rule visibly disabled.
    missing = [s for s in states
               if not re.search(rf"\.s-{re.escape(str(s).lower().replace(' ', '-'))}(?![\w-])", css)]
    g.check(arm, not missing,
            f"{missing} render as badges with no rule in the stylesheet, so they would appear as "
            f"unremarkable states",
            passed=f"all {len(states)} pipeline state(s) have a rule in {len(sheets)} stylesheet(s)")


def arm_both_languages_shipped(g: Gate, bundle: str, dist: Path) -> None:
    """The Chinese edition is in the bytes being served, and the verbatim rule survived with it.

    `strings.ts` makes a MISSING translation a type error — one dictionary, one key set, each value a
    `[en, zhTW]` tuple — and `i18n.test.ts` asserts over that same object the things a type cannot see
    (a blank value, English pasted into both slots, a placeholder present in one language only). Both
    are claims about the SOURCE. This arm is the only check that reads what a reader downloads, and the
    failures it can see are the ones that happen between the two: a bundler that tree-shook the
    dictionary, a merge that landed half a translation pass, a `dist/` left over from before the
    feature existed. A build like that ships a page with a Chinese toggle and English headings, and a
    reader cannot tell an untranslated heading from a heading deliberately quoted verbatim.

    So four properties, none of them expressible in TypeScript:

    * The locale tag `zh-TW` is in the bundle at all. Without it there is no second language to pick.
    * `中文` is in the bundle. That is the toggle's own label, written in the language it switches TO —
      a reader whose browser advertises `en` reaches Chinese only through that button, so a translated
      dictionary behind a missing switch is a translation nobody can get to.
    * Enough distinct Chinese runs reach the bundle (`MIN_CJK_RUNS`). A floor, not a count.
    * `lang="en"` appears on enough elements (`MIN_VERBATIM_MARKS`), and `.verbatim` has a rule in the
      stylesheet. Those two are the verbatim rule as the browser experiences it rather than as a
      comment describes it: `lang` picks the font stack and the screen reader's phonology, and the
      `.verbatim` rule is what makes a quoted English block look quoted instead of looking like this
      platform's own prose that somebody forgot to translate.

    The Chinese pass-rate denial is checked in `no_pass_rate` beside the English one, because it is the
    same rule and a reader looking for where that rule lives should find one place.
    """
    arm = "both_languages_shipped"
    g.check(arm, bool(re.search(r"""(["'`])zh-TW\1""", bundle)),
            "the locale tag 'zh-TW' does not appear as a string literal in the bundle, so the shipped "
            "SPA has one language however many the source has")
    g.check(arm, "中文" in bundle,
            "the language toggle's own label (中文) is not in the bundle: a reader whose browser asks "
            "for English can only reach the Chinese edition through that button")

    runs = {m.group(0).strip()
            for m in re.finditer(rf"[{RUN_INNER}]*[{HAN}][{RUN_INNER}]*", bundle)}
    long_runs = {r for r in runs if len(r) >= 4}
    g.check(arm, len(long_runs) >= MIN_CJK_RUNS,
            f"only {len(long_runs)} distinct Chinese run(s) of 4+ characters are in the bundle, under "
            f"the floor of {MIN_CJK_RUNS}. The dictionary held 481 entries when the floor was set, so "
            "a number this low is a bundle built before the translation, or one that shipped part of "
            "it — either of which renders English headings on a page whose toggle says 中文.",
            passed=f"{len(long_runs)} distinct Chinese run(s) in the bundle, floor {MIN_CJK_RUNS}")

    # A whole property name, not a substring: without the lookbehind `xmlLang:"en"` — or any minified
    # identifier ending in `lang` — counts toward a floor about an attribute the browser reads, which is
    # the same mistake as calling a renamed-away CSS rule present.
    marks = re.findall(r"""(?<![\w$])lang:\s*(["'`])en\1""", bundle)
    g.check(arm, len(marks) >= MIN_VERBATIM_MARKS,
            f"only {len(marks)} element(s) in the bundle carry lang=\"en\", under the floor of "
            f"{MIN_VERBATIM_MARKS}. Every block of payload prose — oracle_text, a verdict, a "
            "why_this_status — renders in English in both languages and says so in the markup; "
            "stripped of that, a screen reader pronounces the artifact's own words as Chinese and the "
            "CJK font stack picks the glyphs.",
            passed=f'{len(marks)} element(s) mark their contents as verbatim English')

    sheets = sorted((dist / "assets").glob("*.css")) if (dist / "assets").is_dir() else []
    if not sheets:
        cannot_run(f"no stylesheet under {dist}/assets — the verbatim rule cannot be checked, and a "
                   "missing check is not a pass")
    css = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sheets)
    g.check(arm, bool(re.search(r"\.verbatim(?![\w-])", css)),
            "the stylesheet has no `.verbatim` rule, so a quoted English block on a Chinese page is "
            "styled exactly like this platform's own prose — which makes a sealed quotation "
            "indistinguishable from a translation somebody forgot",
            passed="`.verbatim` has a rule, so a quoted block reads as quoted")


def arm_audit_vocabularies_are_styled(g: Gate, payload: Path, dist: Path) -> None:
    """Every audit status and observation the payload can render must have a rule in the stylesheet.

    Same mechanism as the arm above and the same reason for existing separately: the audit views derive
    `st-<status>` and `o-<observation>` from the payload token rather than looking either up in a table,
    so a vocabulary member added to `controls.yaml` later renders as a badge with no rule.

    Which reading that produces is the point. An unstyled `not_measured` badge is a plain box beside a
    control, and a plain box reads as "nothing remarkable here" — where the token means this study never
    examined the control at all. Under-stating a finding is recoverable by reading the line; making an
    unexamined control look examined is the failure this platform exists to refuse.
    """
    arm = "audit_vocabularies_are_styled"
    vocab = load(payload, "controls.json").get("vocabularies") or {}
    statuses = vocab.get("status") or []
    observations = vocab.get("observation") or []
    g.check(arm, bool(statuses) and bool(observations),
            f"controls.json declares {len(statuses)} status and {len(observations)} observation "
            "token(s); with either empty this arm would be vacuous and the audit views would have "
            "nothing to colour")
    sheets = sorted((dist / "assets").glob("*.css")) if (dist / "assets").is_dir() else []
    if not sheets:
        cannot_run(f"no stylesheet under {dist}/assets — the badge classes cannot be checked, and a "
                   "missing check is not a pass")
    css = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sheets)
    # Whole class tokens for the same reason as above. `\w` covers the underscore, so `.st-not_measured`
    # does not answer for a renamed `.st-not_measured_at_all`.
    missing = [f"st-{s}" for s in statuses
               if not re.search(rf"\.st-{re.escape(str(s).lower())}(?![\w-])", css)]
    missing += [f"o-{o}" for o in observations
                if not re.search(rf"\.o-{re.escape(str(o).lower())}(?![\w-])", css)]
    g.check(arm, not missing,
            f"{missing} render as badges with no rule in the stylesheet, so a control this study never "
            f"examined would look no different from one it measured",
            passed=f"all {len(statuses)} status and {len(observations)} observation token(s) have a rule "
                   f"in {len(sheets)} stylesheet(s)")


def arm_authored_caveats_are_marked(g: Gate, payload: Path, dist: Path, bundle: str) -> None:
    """A caveat this platform wrote must reach the reader marked as this platform's, never as the run's.

    49 case pages carry a sentence bounding what their verdict does not establish, and no run produced any
    of them: `platform/curation/caveats.yaml` was authored against each case's own record, because the
    record itself says nothing. That is a defensible thing to publish and an indefensible thing to publish
    unmarked — a reader who cannot tell the two apart has been handed a later reader's reasoning at the
    evidentiary strength of a measurement, which is the one substitution this platform exists to refuse.

    `check_caveats.py` enforces the rules over the AUTHORED FILE. This arm is about the SHIPPED ARTIFACT,
    and the failures it can see are the ones that happen after that gate passes:

    * The prose is in the payload but the box that distinguishes it is not in the bundle — a component
      refactor, a bad merge, a `dist/` from before the feature. The sentence then renders in whatever box
      catches it, i.e. as the record's own.
    * `.note.authored` has a class token in the CSS but no declaration that changes anything. That is not
      hypothetical here: a token present in the stylesheet while all 38 boxes still rendered slate is a
      defect this repository has already shipped once (`feedback_class_token_is_not_a_colour`). So the
      rule must carry `dashed` — a border STYLE, not a hue, so the cue survives greyscale and the 8% of
      readers for whom hue alone carries nothing.
    * The sentence migrated INTO `record`. `record` is meant to be byte-identical to
      `results/phase1/<case>.json`, so a reader diffing the two finds nothing added. An authored sentence
      inside it silently makes a producer-written artifact partly hand-written, and every downstream
      consumer that trusts `record` inherits that.
    * An authored caveat landed on a case whose record already carries its own. `check_caveats.py` refuses
      that against the census; this checks it against what shipped, because the two can disagree if the
      payload was built from a different verdict set than the gate read.

    What this arm cannot see: whether any of the 49 sentences is TRUE of its case. That is a human read,
    and `review_status` says in the payload that no human has done it yet. An arm asserting the provenance
    fields exist is not an arm asserting the prose is right, and the ledger below counts the unreviewed
    ones so the gap has a number rather than a disclaimer.
    """
    arm = "authored_caveats_are_marked"
    method = load(payload, "method.json").get("caveats") or {}
    declared = method.get("cases_with_an_authored_caveat")
    files = sorted((payload / "cases").glob("*.json")) if (payload / "cases").is_dir() else []
    if not files:
        cannot_run(f"no case payloads under {payload}/cases — the authored caveats cannot be checked, "
                   "and a missing check is not a pass")

    carried: dict[str, dict] = {}
    inside_record: list[str] = []
    shadowing: list[str] = []
    incomplete: list[str] = []
    unreviewed: list[str] = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cannot_run(f"{f.name} is not readable JSON; a payload this arm cannot parse must not pass")
        cid = str(d.get("case") or f.stem)
        record = d.get("record") or {}
        if "authored_caveat" in record:
            inside_record.append(cid)
        a = d.get("authored_caveat")
        if not isinstance(a, dict):
            continue
        carried[cid] = a
        # The same field-per-verdict rule the builder uses. Named here rather than imported so this arm
        # states the claim it is checking instead of agreeing with the code it is checking.
        own = {"TRUE": "what_true_does_not_prove", "FALSE": "what_false_does_not_prove"}.get(
            str(d.get("verdict")))
        if own and str(record.get(own) or "").strip():
            shadowing.append(cid)
        missing = [k for k in ("why", "verdict", "derived_from", "authored_by", "authored_on",
                               "authored_from", "review_status") if not a.get(k)]
        if missing:
            incomplete.append(f"{cid}({','.join(missing)})")
        if str(a.get("review_status")) != "reviewed_by_a_human":
            unreviewed.append(cid)

    g.check(arm, bool(carried),
            "no case payload carries an `authored_caveat`, so every check below is vacuous. Either the "
            "curation stopped reaching the build, or the feature was removed while its gate stayed",
            passed=f"{len(carried)} case page(s) carry an authored caveat")
    g.check(arm, declared == len(carried),
            f"method.json publishes cases_with_an_authored_caveat={declared} while {len(carried)} case "
            f"page(s) actually carry one. The count and the pages are two claims and must be derived "
            f"from the same build, or the site states a coverage figure no page supports",
            passed=f"the published count ({declared}) is the number of pages carrying one")
    g.check(arm, not inside_record,
            f"{inside_record} carry `authored_caveat` INSIDE `record`, which is supposed to be "
            f"byte-identical to the verdict file. An authored sentence there makes a producer's artifact "
            f"partly hand-written, invisibly to everything downstream that trusts it",
            passed="every authored caveat sits outside `record`, so the records stay diffable")
    g.check(arm, not shadowing,
            f"{shadowing} carry BOTH an authored caveat and their own verdict's caveat in the record. The "
            f"authored one would then stand where the study's own sentence belongs",
            passed="no authored caveat stands where the record already speaks")
    g.check(arm, not incomplete,
            f"{incomplete} carry an authored caveat with a field missing. A page that cannot say who "
            f"wrote a sentence, when, or from what, presents it at the record's strength",
            passed=f"all {len(carried)} carry `why`, `derived_from` and four provenance fields")

    # A ledger, not a failure. Every one of the 49 is unreviewed today, and an arm that failed on that
    # would have to be disabled to publish at all — so it counts them and says so, which is the same
    # shape as the exemption ceilings elsewhere in this file.
    g.check(arm, len(unreviewed) <= len(carried),
            "impossible by construction; the ledger below is the point",
            passed=f"{len(unreviewed)} of {len(carried)} authored caveat(s) are not yet reviewed by a "
                   f"human, and each page says so in its own provenance line")

    # The head sentence is what tells a reader whose sentence this is. It is checked as a distinctive
    # fragment rather than in full because the bundle is minified and the string may be split.
    for fragment, why in (
        ("written by a later reader", "the English head sentence, which is the only thing on the page "
                                     "that says the bound was not written by the run"),
        ("後來的讀者", "the Chinese head sentence — a zh-TW reader would otherwise see the box with no "
                    "statement of who wrote what is in it"),
        ("Review status", "the provenance line, which carries the unreviewed status into view"),
    ):
        g.check(arm, fragment in bundle,
                f"the bundle does not contain {fragment!r} — {why}. The payload still carries "
                f"{len(carried)} authored sentence(s), so they would render as the record's own",
                passed=f"{fragment!r} is in the shipped bundle")

    sheets = sorted((dist / "assets").glob("*.css")) if (dist / "assets").is_dir() else []
    if not sheets:
        cannot_run(f"no stylesheet under {dist}/assets — the authored box's cue cannot be checked, and "
                   "a missing check is not a pass")
    css = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sheets)
    rules = re.findall(r"\.note\.authored(?![\w-])[^{]*\{([^}]*)\}", css)
    g.check(arm, bool(rules),
            "the stylesheet has no `.note.authored` rule, so a sentence this platform wrote is styled "
            "exactly like a sentence the run wrote",
            passed=f"`.note.authored` has {len(rules)} rule(s)")
    g.check(arm, any("dashed" in r for r in rules),
            f"`.note.authored` exists but no rule in it declares `dashed`: {rules}. A class token that "
            f"changes nothing visible is the defect this repository already shipped once — the cue has "
            f"to be a border STYLE, because hue alone carries nothing in greyscale or for a reader with "
            f"a colour vision deficiency",
            passed="the authored box is cued by a dashed border, which survives greyscale")


def arm_audit_report_is_licensed(g: Gate, payload: Path, census: dict, census_cases: set[str]) -> None:
    """The published audit report may only recommend what a citable verdict licenses.

    `audit.json` is the one payload file that gives a reader an INSTRUCTION — "scope this role", "budget
    for a different rollout path" — rather than a measurement. That makes it the file where a governance
    slip does the most damage, and the slip is not hypothetical: an INCONCLUSIVE verdict licenses no
    amendment to this study's own document, so it cannot license advice to somebody else's deployment
    either, and `F5-3b` is TRUE on disk and citable as nothing at all.

    `report.py` enforces both rules while composing. This arm re-checks them on the bytes about to be
    served, against the census and the citation policy as published — because the enforcement and the
    output would otherwise be the same program's word for its own behaviour, and the day a refactor
    widened `LICENSES_RECOMMENDATION` nothing outside that file would notice.

    It also re-derives the verdict mix the report quotes. The report states the study's totals to give
    its reader a denominator, so those four numbers are a THIRD copy of them (`feedback_two_numbers_two_
    claims`), and a stale copy would understate how much of the study did not hold.
    """
    arm = "audit_report_is_licensed"
    audit = load(payload, "audit.json")
    report = audit.get("report") or {}
    inventory = audit.get("inventory") or {}
    g.check(arm, report.get("schema") == "grx-audit-report/1"
            and inventory.get("schema") == "grx-inventory/1",
            f"audit.json carries an unknown shape (report {report.get('schema')!r}, inventory "
            f"{inventory.get('schema')!r}); every arm below reads named keys and would be vacuous")

    verdicts = {r["case"]: r.get("verdict") for r in census.get("rows", []) if isinstance(r, dict)}
    restrictions = {r["case"]: set(r.get("citation_restrictions") or [])
                    for r in census.get("rows", []) if isinstance(r, dict)}
    mix = {v: sum(1 for x in verdicts.values() if x == v) for v in sorted({v for v in verdicts.values()
                                                                          if v})}
    quoted = (report.get("study") or {}).get("verdict_mix")
    g.check(arm, quoted == mix,
            f"the audit report quotes the verdict mix as {quoted}, and the census derives {mix}: the "
            f"report's denominator no longer describes the study it cites",
            passed=f"the report's verdict mix re-derives from census.json ({mix})")

    recs = report.get("recommendations") or []
    g.check(arm, bool(recs), "the published audit report recommends nothing at all, so every arm below "
                             "would pass by having nothing to check")
    unlicensed, unknown_case = [], []
    for rec in recs:
        for cite in rec.get("licensed_by") or []:
            case, verdict = cite.get("case"), cite.get("verdict")
            if case not in census_cases:
                unknown_case.append(f"{rec.get('control')} cites {case!r}, absent from the register")
                continue
            if verdict != verdicts.get(case):
                unlicensed.append(f"{rec.get('control')} cites {case} as {verdict!r}, and the census "
                                  f"says {verdicts.get(case)!r}")
            if verdict not in ("TRUE", "FALSE"):
                unlicensed.append(f"{rec.get('control')} rests on {case}, whose verdict is {verdict!r}: "
                                  f"an INCONCLUSIVE or unpublished result licenses no recommendation")
            forbidden = restrictions.get(case, set()) & {"NEVER_CITE"}
            if forbidden:
                unlicensed.append(f"{rec.get('control')} rests on {case}, which the citation policy "
                                  f"marks {sorted(forbidden)}")
    g.check(arm, not unknown_case, f"the report cites case(s) that are not in the register: "
                                   f"{unknown_case}")
    g.check(arm, not unlicensed, f"{len(unlicensed)} recommendation citation(s) are not licensed: "
                                 f"{unlicensed}",
            passed=f"{len(recs)} recommendation(s), each licensed only by a citable TRUE or FALSE "
                   f"verdict")

    withheld = report.get("recommendations_withheld")
    g.check(arm, isinstance(withheld, list),
            "the report carries no `recommendations_withheld` list, so a recommendation this study "
            "declined to make would be indistinguishable from one nobody considered")
    for item in withheld or []:
        g.check(arm, bool(str(item.get("why_withheld", "")).strip()),
                f"a withheld recommendation for {item.get('control')!r} states no reason")

    # No ratio, anywhere. Not a style rule: a pass rate over these controls would divide "measured, and
    # the guidance did not hold" by the same denominator as "never examined", and the reader would carry
    # away a number that feels like information. The one key allowed to say `ratio` is the one that
    # explains why there is none.
    offenders: list[str] = []

    def scan(node: object, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if re.search(r"pass_rate|passed_count|n_passed|score|grade|percent", str(key)) or (
                        "ratio" in str(key) and "no_ratio" not in str(key)):
                    offenders.append(f"{where}/{key}")
                scan(value, f"{where}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                scan(value, f"{where}[{i}]")
        elif isinstance(node, str) and PERCENTAGE.search(node):
            offenders.append(f"{where} states the percentage {PERCENTAGE.search(node).group(0)!r}")

    scan(audit, "audit.json")
    g.check(arm, not offenders,
            f"the audit page states a rate or a score, which is arithmetic over incommensurable "
            f"states: {offenders}",
            passed="no rate, score, grade or percentage anywhere on the audit page")

    example = audit.get("example") or {}
    g.check(arm, example.get("is_synthetic") is True and bool(example.get("files")),
            "the worked example is not marked synthetic or names no files: a reader must not be able "
            "to mistake an authored template for a captured deployment")


def arm_architecture_colours_are_licensed(g: Gate, payload: Path, census: dict,
                                          census_cases: set[str], dist: Path) -> None:
    """No box on either diagram may be coloured by a verdict the census does not publish.

    The diagram is the artifact most likely to leave this platform on its own — screenshotted into a
    deck, pasted into a review — and it leaves without the case table underneath it. So a green box is
    the highest-leverage false claim the payload can make, and the claim has to be re-checked against
    `census.json` here rather than trusted from the builder that drew it: `derive_architecture()` and
    `check_architecture.py` both read the authored file, and neither of them is a second pair of eyes on
    the colour that actually shipped.

    Four things are checked, each one a rule the user set for this view:

    * a `validated_in_part` box has at least one case whose census verdict is TRUE and whose citation
      restrictions do not disqualify it;
    * a `contested` box likewise has a citable FALSE — the status says the guidance did not hold
      somewhere, and it may not rest on a restricted case;
    * no box supported only by INCONCLUSIVE reads as validated, because an INCONCLUSIVE verdict
      licenses no amendment to this study's own document and cannot colour a component green either;
    * every case the diagrams place is in the register, and placed ∪ unplaced covers it exactly — a
      case that appeared on no diagram and in no exclusion list would be invisible by construction.

    And the styling arm, for the same reason the pipeline and audit vocabularies have one: the five
    status classes are DERIVED from the payload token in the view, so a status added later renders as a
    plain box — and a plain box beside a component reads as "nothing remarkable here", which is the one
    thing `contested` does not mean.
    """
    arm = "architecture_colours_are_licensed"
    arch = load(payload, "architecture.json")
    diagrams = arch.get("diagrams") or []
    g.check(arm, len(diagrams) >= 2, f"architecture.json carries {len(diagrams)} diagram(s); every arm "
                                     f"below quantifies over their boxes and would be vacuous")

    verdicts = {r["case"]: r.get("verdict") for r in census.get("rows", []) if isinstance(r, dict)}
    restrictions = {r["case"]: set(r.get("citation_restrictions") or [])
                    for r in census.get("rows", []) if isinstance(r, dict)}
    non_colouring = set(arch.get("non_colouring_restrictions") or [])
    g.check(arm, bool(non_colouring),
            "architecture.json declares no non-colouring restriction set, so the licence checks below "
            "would treat a NEVER_CITE case as ordinary support")

    boxes = [(d.get("id"), b) for d in diagrams for b in d.get("boxes") or []]
    g.check(arm, len(boxes) >= 24, f"the two diagrams carry {len(boxes)} box(es) between them, too few "
                                   f"for this arm to be reading the published payload")

    bad, ghost = [], []
    placed: set[str] = set()
    for did, b in boxes:
        ids = [c.get("case") for c in b.get("cases") or []]
        placed.update(i for i in ids if i)
        unknown = [i for i in ids if i not in census_cases]
        if unknown:
            ghost.append(f"{did}/{b.get('id')} places {unknown}, absent from census.json")
            continue
        citable = [i for i in ids if verdicts.get(i) and not (restrictions.get(i, set()) & non_colouring)]
        status = b.get("status")
        if status == "validated_in_part" and not any(verdicts[i] == "TRUE" for i in citable):
            bad.append(f"{did}/{b.get('id')} is coloured validated_in_part with no citable TRUE verdict "
                       f"among {ids}")
        if status == "contested" and not any(verdicts[i] == "FALSE" for i in citable):
            bad.append(f"{did}/{b.get('id')} is coloured contested with no citable FALSE verdict among "
                       f"{ids}")
        if status in {"validated_in_part", "contested"} and ids and not citable:
            bad.append(f"{did}/{b.get('id')} is coloured {status} although every case on it is "
                       f"non-citable")
        if status == "validated_in_part" and citable and all(verdicts[i] == "INCONCLUSIVE"
                                                             for i in citable):
            bad.append(f"{did}/{b.get('id')} reads as validated on INCONCLUSIVE support only")
    g.check(arm, not ghost, "; ".join(ghost))
    g.check(arm, not bad, f"{len(bad)} box colour(s) the census does not license: " + "; ".join(bad),
            passed=f"every coloured box on {len(diagrams)} diagram(s) rests on a citable verdict "
                   f"({len(boxes)} boxes checked)")

    unplaced = {u.get("case") for u in arch.get("unplaced_cases") or []}
    missing = sorted(census_cases - placed - unplaced)
    overlap = sorted(placed & unplaced)
    g.check(arm, not missing and not overlap,
            f"coverage does not close: {missing} appear on no diagram and in no exclusion list, and "
            f"{overlap} appear in both",
            # "registered", not "published": `census.json` carries a row per registered case, and 93 is
            # the register's denominator while 91 is the published one. Naming the wrong denominator in
            # a passing message is how a gate teaches a reader a number that is not the one it checked.
            passed=f"{len(placed)} placed + {len(unplaced)} excluded covers all {len(census_cases)} "
                   f"registered case(s), disjointly")

    statuses = sorted(arch.get("status_labels") or {})
    g.check(arm, bool(statuses), "architecture.json declares no status vocabulary, so the styling check "
                                 "below would be vacuous")
    sheets = sorted((dist / "assets").glob("*.css")) if (dist / "assets").is_dir() else []
    if not sheets:
        cannot_run(f"no stylesheet under {dist}/assets — the box classes cannot be checked, and a "
                   "missing check is not a pass")
    css = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sheets)
    # Whole class tokens, as in the two arms above: `.st-not_measured` must not answer for a renamed
    # `.st-not_measured_here`.
    unstyled = [f"st-{s}" for s in statuses
                if not re.search(rf"\.st-{re.escape(str(s).lower())}(?![\w-])", css)]
    routes = sorted({e.get("route") for d in diagrams for e in d.get("edges") or [] if e.get("route")})
    g.check(arm, bool(routes), "no edge declares a route, so the edge styling check would be vacuous")
    unstyled += [f"e-{r}" for r in routes
                 if not re.search(rf"\.e-{re.escape(str(r).lower())}(?![\w-])", css)]
    g.check(arm, not unstyled,
            f"{unstyled} render with no rule in the stylesheet, so a contested component would look no "
            f"different from an unexamined one",
            passed=f"all {len(statuses)} status and {len(routes)} edge-route token(s) have a rule in "
                   f"{len(sheets)} stylesheet(s)")

    # A TOKEN IN THE STYLESHEET IS NOT A COLOUR ON THE BOX
    #
    # The check above passed on 2026-08-20 against a served page that drew all 38 boxes in the same neutral
    # slate. `.st-contested` and `.archbox` are both single-class selectors and `.archbox` is declared
    # later, so its own `border` won the cascade and discarded every status colour — while the legend
    # printed beside the diagram went on advertising five. The gate could not see it, because a rule being
    # present in the file is a different claim from that rule reaching the element.
    #
    # A custom property makes the second claim greppable, which is why the stylesheet was rewritten to use
    # one: each status rule publishes its colour as `--st`, and the box rule reads it. `.archbox` never
    # declares `--st`, so there is nothing for a later rule to override, and the two halves of that
    # arrangement are asserted here separately — half of it is a monochrome diagram again.
    no_var = [f"st-{s}" for s in statuses
              if not re.search(rf"\.st-{re.escape(str(s).lower())}(?![\w-])\{{[^}}]*--st:", css)]
    g.check(arm, not no_var,
            f"{no_var} state a colour without publishing it as `--st`, so the diagram surface's own rule "
            f"decides the box border and the status on the element decides nothing")
    g.check(arm, re.search(r"\.archbox(?![\w-])\{[^}]*border:[^;}]*var\(--st(?![\w-])", css) is not None,
            "the `.archbox` rule does not take its border colour from `--st`, so every box is drawn in "
            "whatever colour that one rule names, whatever the payload says about the component",
            passed=f"all {len(statuses)} status(es) publish `--st` and the diagram box takes its border "
                   f"from it, so a box's colour is the status the payload put on it")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    payload = args.payload.expanduser()
    if not payload.is_dir():
        cannot_run(f"{payload} is not a directory")

    g = Gate()
    census = load(payload, "census.json")
    census_cases = {r["case"] for r in census.get("rows", []) if isinstance(r, dict) and "case" in r}
    if len(census_cases) < 90:
        cannot_run(f"census.json lists {len(census_cases)} case(s); every arm below is scoped to that "
                   "set and would be near-vacuous")

    arm_manifest_liveness(g, payload)
    days_by_case = arm_replication(g, payload, census_cases)
    arm_no_authored_replication_claim(g, payload, census_cases, days_by_case)
    bundle = arm_bundle_text(g, args.dist.expanduser())
    denominators = arm_denominators(g, payload)
    arm_verdict_mix(g, payload, denominators)
    arm_citation_policy(g, payload, census_cases)
    arm_figures(g, payload, bundle)
    arm_pipeline_states_are_styled(g, payload, args.dist.expanduser())
    arm_both_languages_shipped(g, bundle, args.dist.expanduser())
    arm_audit_vocabularies_are_styled(g, payload, args.dist.expanduser())
    arm_authored_caveats_are_marked(g, payload, args.dist.expanduser(), bundle)
    arm_audit_report_is_licensed(g, payload, census, census_cases)
    arm_architecture_colours_are_licensed(g, payload, census, census_cases, args.dist.expanduser())
    arm_oracles(g, payload)

    if args.verbose or g.failures:
        for note in g.notes:
            print(f"  {note}")
    if g.failures:
        print(f"\nFAILED — {len(g.failures)} site invariant violation(s)", file=sys.stderr)
        for item in g.failures:
            print(f"  * {item}", file=sys.stderr)
        return 1
    print(f"PASSED — {len(g.notes)} site invariants hold over {payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
