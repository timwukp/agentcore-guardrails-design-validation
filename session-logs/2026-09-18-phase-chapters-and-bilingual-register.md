# 2026-09-18 — the three phase chapters, and the census reading that forced a bilingual register

Two concerns, one PR, and the second half of this log explains why they are not separable.

Scope carried in: finish the three phase-chapter videos (2–3 min each, bilingual) so `/design` embeds one
explainer per phase beside the overview, then run the gates, document, and push. What actually happened
is that the gates were run *and read*, and the census — plan step 6, the one everybody remembers last —
came back **above** its ceiling for reasons that had nothing to do with the videos.

---

## 1. The chapters

`video/script/{before,during,after}.yaml` join `overview.yaml`. One `--verify` run (double render, fresh
synthesis, byte-identical or non-zero) at `rc=0`, `verified_identical_renders: true`:

| video | scenes | en | zh | en mp4 | zh mp4 |
|:---|---:|---:|---:|---:|---:|
| overview | 10 | 212.3 s | 205.6 s | 4.49 MB | 3.69 MB |
| before | 7 | 138.8 s | 144.1 s | 3.14 MB | 2.81 MB |
| during | 7 | 143.1 s | 147.1 s | 3.19 MB | 2.82 MB |
| after | 7 | 153.5 s | 153.1 s | 3.41 MB | 2.83 MB |

**8 tracks, 1298 s, 26.39 MB of mp4 + 21.9 KB of WebVTT.** Every chapter is inside the plan's 2–3 minute
target and the overview inside its 4–6 — recorded, not met: padding narration to a clock would be writing
for the clock, and every number spoken is resolved from the payload, so there is nothing to pad with.

The expectation that the Chinese track would be the shorter one is **wrong in three tracks of four**.
Mandarin says the same thing in about a third of the characters and is still slower here, because the
engines differ: Zhiyu is neural, Ruth is generative, and the generative voice paces a technical sentence
differently.

### What the assertions could not see, and what now holds it

Three rendering defects were found by *looking at the frames*, in both locales, which no JSON assertion in
this repository can do. The third is the one worth keeping:

1. two labels overlapping where a satellite sat beside the spine;
2. a label leaning into the other column;
3. **the spine labels crossed the diagram's own return path** — and this one was *introduced by the fix
   for the first*. Centring a label on its box put it straight through the gutter and feedback
   connectors running down the left margin.

The fix is derived, not tuned: `spine_label_right = min(0, gutter_x) - 16`, where `gutter_x` is the
leftmost x of any connector point on the diagram, so the clearance is read from the **connectors** rather
than from the boxes. Two arms hold it, and the fixture is a payload that *has* left-margin connectors —
`test_no_spine_label_crosses_a_connector` first asserts `leftmost_stroke < 0`, because a fixture without
one cannot discriminate. The second arm renders at `boxes_shown=2` and at `None` and requires the same
`text x=` per box, so the label cannot move as the reveal adds boxes.

`video/tests` is **53 arms** (floor was 8 — see §4), and the mutation probe kills **8 of 8**, control
first at `rc=0`. Two mutants are new: centring the spine labels again, and reading the clearance from the
boxes instead of the connectors. The second is killed by exactly **one** arm, which is what a
mutation probe is for.

### Cost, read off the meter

**56,863 characters over 246 `SynthesizeSpeech` requests → $1.4939**, reconciled against CloudWatch across
three hourly buckets with no residue: four verify passes at 58 requests / 13,436 characters each, plus one
single-video render of `before` at 14 / 3,119. A pass is **58** requests, not 62, because the three
chapters close on the same `verify` scene verbatim and the Polly cache is keyed on the *request*
(voice | engine | language | text). $1.41 of the $1.49 is re-verification, not production. Cumulative for
the whole explainer: 85,339 characters / 366 requests / **$2.21–$2.26**, against the $95 repo ceiling.
Full derivation: `session-logs/polly-spend-20260918-chapters.log`.

---

## 2. The census came back above its ceiling — and the videos were not why

Plan step 6 says re-run `census_rendered_surfaces.py`. It reported **304** untranslated rendered strings
against `MAX_UNTRANSLATED_RENDERED = 299`, and the arm's own message says what to do about it:

> The ceiling only ever falls: a new untranslated surface has to be translated, not admitted.

The cause was not the explainer. **Future-work items 37–41 landed on 2026-09-17 and the census was not
re-run**, so the arm counted against a ledger from 2026-09-16 and passed on a tree that had already
exceeded it. Five new item titles, five new rendered English strings, one gate that could not see them
because its ledger was stale. That is a measurement with no liveness, and the honest response is not a
higher number.

### The bilingual deficiency register

`FUTURE-WORK.md` is English prose, and its item titles and tier headings render on `/register` in **both**
locales. So a zh-TW reader had been reading this project's own self-conviction in a language they had not
chosen, on a page whose banner says the English on it is quoted evidence — which these sentences are not.
They are ours.

- **`platform/curation/register_zh.yaml`** (new): 42 item titles and 5 tier headings in Traditional
  Chinese, keyed by the number the document itself assigns. A curation file rather than a second column
  in `FUTURE-WORK.md` for the same reason as `architecture.yaml`: the document is parsed, and a document
  carrying its own translation in a shape the parser understands is a document whose format is a schema.
- **`derive_registers()` now dies** on an untranslated item, an untranslated tier heading, a translation
  for a number the document does not use, or a translation for a heading it no longer uses. Both
  directions, because a renumbered register with a stale translation file attaches *every other* title to
  the wrong item and no count notices.
- Mandatory **now**, all 42 in the commit that adds the file, because a field is mandatory for free
  exactly once: before the first writer exists who did not fill it in
  (`feedback_mandatory_field_timing`). This is precisely how items 37–41 got in.
- A translation here may not soften. Several titles are this project convicting itself; identifiers
  (case ids, `run_id`, TRUE / FALSE / INCONCLUSIVE, tier numbers) stay as they are, because they are
  identifiers and not words.
- `body_md` stays bare English. Translating long-form prose is different work from refusing to ship a
  new item untranslated; it is filed rather than half-done. **This sentence originally said "and stays
  in the backlog", which is false and is now register item 43**: a `body_md` is rendered as Markdown, the
  census matches raw payload strings against rendered text, and 115,067 characters of register bodies
  have never been in any ledger the ceiling counts. See §6.

Consumers rewired through `useAuthored()` / `<A/>`: `Register.tsx` (a module-level `en()` helper keeps the
facet key and the deadline scan on the English half, so the filter cannot key on an object) and
`FigureGallery.tsx`. `npm run typecheck` clean, `npm test` 21/21.

**Ceiling: 299 → 259.** Measured, not chosen — the arm fails in *both* directions, and it names the number
to write.

---

## 3. Item 42: the census failed and then passed on the same tree

While re-running the census, the first attempt exited **2**:

> `FATAL: /design in zh-TW never rendered 400 characters of main content within 15 s (TimeoutError).
> Either the route is broken or the payload file it reads is missing`

The second exited **0** and walked all 17 routes × 2 locales. Between them the same route was loaded by
hand under the same locale and the same init script: `main` measured **44,707** characters, empty console.
Neither cause the message names was true.

Filed as **register item 42** rather than shrugged at, because the census *is* the ledger the translation
ceiling counts against, so it is a publish gate whose red is indistinguishable from its flake — and the
remedy a flake teaches is the same keystroke that disposes of a real regression. The mechanism is not
mysterious, which is what makes the fixed 15 s a guess: `/design` is now the heaviest route on the site
(eight `<video>` elements over 26.39 MB, served by a single-threaded local server, navigated with
`wait_until="load"`, which waits on subresources), and the floor was set when that route had one video.
It closes when the run records a per-route elapsed time, counts and publishes its own retries, and stops
waiting for bytes no assertion in it reads.

Two ledgers of one tree now exist — `…T073359Z.json` from *k*=2 and `…T074825Z.json` from *k*=1, the
second forced by item 42 itself changing the register the census walks — and the only place *k* appears is
this log.

Those are not the names they were written under. **Both were originally `…T151900Z` and `…T155900Z` —
local time on a UTC+8 machine, labelled `Z`** — which is §7, and the more expensive half of item 42.

---

## 4. Gates, floors and the two arms that were not there

**Floors re-baselined** (all fifteen directories re-collected, because raising two while trusting thirteen
is how the list fell behind three times already):

    video/tests   8 -> 53      platform/build/tests 378 -> 388 -> 395
    claims/tests  471 -> 474   tools/tests          122 -> 130

`video/tests` is the one to read twice: the floor stood at **8** — the count on the day PR #54 merged —
while the directory collects **53**. Every arm holding a chapter to its own phase's numbers sat in that
45-arm gap, and the gate would have printed a pass with `test_scenes.py` cut back to its original eight.

**Two defects in the harness itself**, both found by running the whole directory rather than the file:

1. `media.json`'s no-manifest branch omitted `videos`, so on any machine that had not rendered, the arm
   comparing the payload's video list against the scripts on disk read `None` as a *disagreement* instead
   of as a complete absence of media. `videos` is a property of the scripts — what this payload owes a
   player for — so it is carried in both branches now, with `rendered_videos: []` beside it: nothing
   rendered is a measured zero, not an unanswered question.
2. The media group's fabrication built **one track per language** while four videos now ship, and the arm
   pairs tracks with the files that shipped. It also carried no `resolved_values`, so the control was
   testing the absence of a field rather than the state the group is about. Both fixed, derived from the
   payload's own `videos`; the control's file count is derived too (`len(videos) * 4`) instead of the 4 it
   asserted while one video existed.

**New arms, +7 in `platform/build/tests` (388 → 395):**

- six over `derive_registers()`'s refusals — untranslated title, orphan title, untranslated tier, orphan
  tier, duplicate item number (PyYAML's last-wins would put one item's Chinese under another's), and the
  no-mutant control;
- **the stale-video arm the media group never had**: every file present, byte-identical to its manifest,
  doubly rendered and honestly disclosed, and still *saying* a number the payload no longer publishes,
  because the bytes were rendered last week. Nothing in this repository could tell a fresh render from an
  old one before it, since the spoken numbers live in an audio track nobody re-listens to.

`registers.json` also gets its own floor in `MIN_AUTHORED_PROSE_OBJECTS` (**84** = 42 titles + 42
resolved tier headings), with no slack: the producer dies on an untranslated item, so the only way that
count can fall is an item being *removed*, which should have to move the line.

---

## 5. Where this leaves the plan

All five plan steps were merged before today; this round is the second half of step 5's deliverable (the
chapters) plus the census obligation the plan wrote into step 6. **The live publish is a separate,
explicitly authorized act and has not been performed** — `v/20260917T091943Z/` stays live until the user
says otherwise.

Why the two concerns ride one PR: separating them would leave `main` green on a knowingly stale census
ledger. The chapters cannot be pushed with a 299 ceiling that a re-run has already disproved, and the
register cannot be pushed without the census that measured it.

---

## 6. The whole script ran, and the red set was six plus a gate

`./verify_phase0.sh` end to end — the first time since the explainer landed — needed `PYTHON=` pointed at
the oracle venv (its default `python3` is now the 3.14 homebrew build with no pytest, and the script exits
**2** before running a single gate). Result: **12 of 14 gates**, suite **6 failed, 3856 passed, 16 skipped
in 1:15:18**. The whole value of that number came from diffing the red set **by name** against the four in
register item 37, which is the only reason the last two paragraphs of this log exist.

| red, by name | provenance | disposition |
|:---|:---|:---|
| item 37's four | inherited, each with a named ledger | unchanged, carried |
| `test_every_prose_count_matches_a_derived_count` | **mine, this round** | fixed — `EXPECTED_PROSE_SITES` 4 → 5 |
| `test_the_real_staging_tree_holds_nothing_the_live_tree_disagrees_with` | **2026-08-13 / 2026-08-19** | written up in item 29, not resolvable here |
| gate `every .py compiles` (rc 1) | **2026-08-20** | fixed — the walk was reading `node_modules` |

Three things worth keeping:

1. **The prose-count red was the good half of that arm.** Every count in the new text *derived*
   correctly; what failed was `EXPECTED_PROSE_SITES`, the assertion that notices a sentence stating a
   count nothing checks. `README.md`'s new paragraph was exactly that sentence. A test that only
   validated the numbers it already knew about would have passed and left the new claim unchecked.
2. **The staging-tree arm is red in two independent halves, and neither is a test defect.** `classify()`
   now reports **17** conflicts where item 29 measured 8 on 2026-08-16 — the nine new ones are
   `f6_latency`'s three case directories, whose per-case roll-ups were rewritten on **2026-08-19** by the
   day-2 re-run into the same `run_id`, which is precisely the recurrence item 29 said remedy (b) would
   prevent. Staged vs live: `captured_utc` 2026-08-11 vs 2026-08-19, `macOS-26.6` vs `macOS-26.6.1`,
   `n_calls` 8 vs 2012, `cedar_only.authz_ms.ci_p50` `55 [54, 56]` vs `59 [58, 60]`. Both are real days
   on a differently patched machine, and **which one a published F6 figure rests on is issue #37's open
   question**, so nothing here picked a winner. The second half — `refused` is **300**, every
   `results/` file the pull staged — has been red since **2026-08-13** and was never recorded anywhere:
   it is not a conflict but two programs disagreeing about what a pull is (`runner/sync.py pull` stages
   `evidence/` **and** `results/`; `merge_evidence.classify()` refuses everything outside `evidence/`).
3. **A gate was red for ~29 days because the wrapper was never run as a wrapper.** `every .py compiles`
   swept `platform/infra/node_modules`, where `aws-cdk`'s `init-templates/sample-app/python/app.template.py`
   holds `%name.PythonModule%` placeholders and is not valid Python by design. Every gate in that window
   was run individually by hand, so the script's own red had no reader. The fix bounds the walk and
   **prints both sides**: `285 .py files (ours); 27 vendored under node_modules, not read`.

### Item 43, found by asking what an item costs — and the first explanation was wrong

Adding an item to the register raises the untranslated-surface backlog by **zero**, and the reason is the
item. Grepping both of the day's ledgers for a sentence out of item 37's body returns 0 in each; grepping
the 15:59 ledger for `registers.json` returns 0 occurrences of the producer at all, while the 06:45 one
carries that item's *title* as `registers.json/items[35]/title`.

**The first explanation I wrote for that was the collapsed `<details>`, and it is false.** `COLLECT_JS`
opens every disclosure before walking, publishes `disclosures_opened`, and records `behind_disclosure` per
node — and the counted title sits inside the same collapsed element as the uncounted body. The real cause
is the match: the census keys its universe by the **raw** payload string and keeps a row only
`if s in walked[(r,"en")]["text"]`, so a `body_md` rendered through `<Body>` → `Markdown`
(`site/src/lib/md.tsx:267`) — markers stripped — is never a substring of what the reader reads, and the
row is dropped at `continue` as *reaches no reader*. The confirming case is the opposite one: the largest
string the backlog does carry is `audit.json/markdown` at 37,483 characters, and `/report` shows it as
text **on purpose** (`strings.ts:655`). The census sees Markdown exactly when the page refuses to render
it. That correction is written into the item beside the evidence that killed the first version, because a
correction inherits no credibility from the error it replaces (`feedback_correction_wrong_twice`).

Measured on the `20260918T074920Z` payload, by the class each string would have been given:
**42 register bodies = 115,067 chars** and **2 side registers = 10,890** would be AUTHORED (owed a
translation, absent from a 259-string backlog); **19 findings bodies = 376,017** would be ARTIFACT (must
stay English, and absent from the disclosure count that reports 993 marked quoted sentences).
`CaseDetail.tsx:719` renders record fields through the same component per case and is not counted.

The uncomfortable part is the direction of the flattery: this morning's work lowered a number by exactly
the amount the instrument could see, and the total it is a fraction of was never derived. Item 43 says the
remedy is a denominator — including a published count of the payload strings the run *drops* for want of a
match, which was 0 by construction — not a translation sprint, and that the corrected reading must land
**once**, with its cause beside it, rather than as a ceiling that learns to rise.

Register: **43** items. `registers.json`'s authored-prose floor moves 84 → **86** with it, which is the
intended cost of a new item — a floor a new item can satisfy without moving is measuring nothing.

---

## 7. The ledger the gate was counting was eight hours in the future

Re-running the census to make item 43's arithmetic honest is what surfaced this, and it is worse than
anything §6 lists: **a re-measured census was written, and silently discarded, while the gate printed a
pass naming the stale file.**

`build_site_data.py:696` selects the ledger with
`sorted(CENSUS_DIR.glob("rendered-surfaces-*.json"))[-1]` — newest **by name**. The name is therefore a
field of the measurement, and it had no producer: whoever ran the command typed it. Two of the day's
ledgers were typed as **local** time and labelled `Z` on a UTC+8 machine:

| written (mtime, UTC) | typed name | offset | consequence |
|:---|:---|---:|:---|
| 07:33:59Z | `…T151900Z.json` | **+8.2 h** | out-sorted every correct stamp until 15:19 |
| 07:48:25Z | `…T155900Z.json` | **+8.2 h** | same, until 15:59 |
| 06:29:13Z | `…T064500Z.json` | +15.8 min | harmless — still sorts between its neighbours |
| 10:00:26Z | `…T095804Z.json` | −2.0 min | the 43-item re-measure, **never selected** |

Three of four names were typed rather than derived. The failure is not that a human typo'd; it is
`feedback_mandatory_field_timing` again — a mandatory field is free to enforce exactly once, before the
first writer exists who did not fill it in, and this one had been written by hand nine times.

What made it invisible is the reporting. Every log line and the gate's pass message **named the file**, so
the run looked fully attributed; what no line said was that the named file was not the newest measurement.
A name in a log is not a provenance check when the name is the thing that is wrong.

The fix has two halves. The pair is **renamed to its true UTC instants**, derived from each file's own
mtime with the mtimes preserved through `os.utime` so the derivation stays re-runnable — and only that
pair, because only that pair corrupted the selection order. And `check_out_stamp()` now refuses, *before*
the four-minute walk: a name outside the convention, digits that are not a real UTC instant, a stamp more
than 120 s ahead of the clock (with the distance printed, so a timezone reads as one), and a stamp not
strictly newer than the newest conforming ledger present — a walk whose output nothing will select is four
minutes spent on an unreadable number. `platform/build/tests/test_census_stamp.py` is **11 arms**, control
first, every one with `now` and `existing` injected: an arm about "eight hours in the future" written
against `datetime.now()` would pass or fail by the timezone of whoever ran it, which is the defect under
test (`feedback_harness_test_measures_the_machine`). The last arm re-validates *every* ledger in the
directory against the ones older than it, so a file added by hand is derived into the check rather than
trusted (`feedback_derive_both_sides_of_a_gate`).

`platform/build/tests` **395 → 406** for the new file. Nothing pins the name-to-mtime offsets above,
deliberately: mtime does not survive a clone, which is also why the guard compares the name against the
clock at the instant of writing instead of against the file afterwards.

### What the re-run then measured

The payload was rebuilt (`20260918T101654Z`, 135 files, 43 register items, `--render-rc 0
--figure-check-rc 0` — the two rcs measured earlier today over inputs that have not changed since) and the
harness re-read the ledger it should have been reading all along:

    [authored_prose_is_bilingual] 259 string(s) still bare, exactly the published ceiling,
      measured by rendered-surfaces-20260918T095804Z.json
    PASSED — 57 site invariants hold

`gate_payload.py` rc 0 over 135 payload files + 4 built SPA files (34,279,093 characters, 2,422 shape-excused,
4 inherited exceptions, 15 files decoded as latin-1 rather than skipped for being binary).

**The red set, by name, is back to item 37's four and nothing else.** `platform/build/tests` **406/406**,
`claims/tests` red only on the three that item 37 already names — `test_every_cited_repo_path_exists`,
`test_every_elided_hash_citation_resolves_to_a_derivable_hash`,
`test_every_dynamic_copy_source_is_declared_and_still_there` (`3 failed, 877 passed in 41:20`) — and
`runner/tests`/`tools/tests`/`video/tests` red only on the fourth,
`test_the_real_staging_tree_holds_nothing_the_live_tree_disagrees_with` (`1 failed, 264 passed, 12 skipped
in 14:36`). The two reds this round introduced or inherited unrecorded are gone; the four that remain are
each carried with a ledger.

**The browser walk: 13 routes × 2 locales, `read 8 of 8 expected video element(s)`, 0 CSP violations, 0
problems, rc 0**, with the four verdict colours re-measured from `getComputedStyle` (5.12 / 5.89 / 6.50 /
6.75:1, all clearing AA) and the Polly disclosure read off the rendered page in both languages.

Two things about that walk are worth writing down rather than smoothing over. First, **the server it ran
against is not the one this session started**: `csp_preview.py --port 8901` exited immediately with
`OSError: [Errno 48] Address already in use`, because a preview from 14:25 was still holding the port. The
walk is still sound — the handler serves `site/dist` from disk per request and `dist/data` is a symlink to
the payload, so it served the bytes built minutes earlier — but "I started a server and then walked it" was
false, and the pid this session tracked to kill (61611) had already been gone for hours
(`feedback_cleanup_finds_no_target`). Second, before killing the real one (14528), the CSP was **read off a
response header** and compared to `csp_preview.py --print-only`, and the two are character-identical
including `media-src 'self'`. That is a header read from a response rather than asserted from source — for
the *local* preview only. The live distribution still has never had a header read off it, which is item 41
and is not closed by this.
