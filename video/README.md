# `video/` — the narrated explainers, and why every second of them is derived

This directory renders the four bilingual videos embedded on `/design`: one **overview** under the
diagram, and one chapter per phase — **before**, **during**, **after** — at its own section head.
They exist to answer one question a reader of that page will reasonably ask — *did you measure this
design, or did you write it?* — in the one medium where an unsupported claim travels furthest and
gets checked least.

So the rule for this pipeline is stricter than for the prose: **nothing in the video is authored
here.** Every number is read from the published payload at render time, every spoken sentence is the
caption text verbatim, and the whole render is run twice and compared byte for byte before the page
is allowed to call it verified.

## What is in here

| file | what it is | what it must never contain |
|:---|:---|:---|
| `script/overview.yaml` | the 10 scenes' narration, `en` + `zh`, with `{placeholders}` for every quantity | a literal count; a paraphrase of a verdict; a claim of human narration |
| `script/{before,during,after}.yaml` | one chapter each, 7 scenes: `title, where, checkpoints, status, evidence, basis, verify` | another phase's numbers; a count that is not a placeholder |
| `scenes.py` | the frame HTML/SVG, and `resolve()` — the single place a payload number becomes a narration value | a hardcoded palette, a hardcoded coordinate, a hardcoded total |
| `render.py` | synthesis → screenshots → mux, and `--verify`'s double render | a duration target the narration was assumed to hit |
| `tests/test_scenes.py` | 53 tests, run under `.venv-oracle` | — |
| `tests/mutation_probe.py` | 8 mutants against `scenes.py`, run by hand — never in a gate, because it edits the module it tests | — |
| `out/` | **gitignored.** frames, audio cache, `media/`, `RENDER.json` | — |

The file set is derived, not listed: `script/*.yaml` is the inventory. Adding a fifth script adds a
fifth video to the expected file set, the manifest check, the invariant arm and the page — or fails
each of them in turn. `scenes.py` refuses an unknown video name rather than rendering an empty one.

## Running it

```sh
# all four videos, both languages, one pass — for iterating on wording or layout
/opt/homebrew/opt/python@3.12/bin/python3.12 video/render.py

# one chapter only, while working on it (default is --video all)
/opt/homebrew/opt/python@3.12/bin/python3.12 video/render.py --video before

# the publishable render: twice, fresh synthesis both times, every sha256 must match
rm -rf video/out/audio        # so pass A synthesizes too, instead of reading a dry run's cache
/opt/homebrew/opt/python@3.12/bin/python3.12 video/render.py --verify
echo "rc=$?"          # this rc is what publish_web.py's --render-rc wants; read it directly

.venv-oracle/bin/python -m pytest video/tests/ -q
```

A partial render is legal and stays honest: the manifest then declares tracks for one video, the
build checks per video that a name has **either all four files or none of them**, and `/design` shows
an embed only where four files exist. What is impossible is a video that shipped an mp4 without its
captions, or a page that invents an absence for a payload built before a script existed.

Two interpreters, deliberately: Playwright and PyYAML live in the Homebrew 3.12 (it owns the
Chromium 1208 cache the site's browser walks already use), and the test/oracle venv is pinned and
isolated by `check_venv_isolation.py`. Neither can be collapsed into the other without breaking one
of those two properties.

## The four determinism links, each measured — one of them twice

`--verify` is only meaningful if the pipeline *can* be byte-reproducible. That was measured on this
machine link by link rather than assumed. Three links held on the first measurement; the fourth
turned out to have been measured too narrowly, and the section after this one is what that cost:

- **Amazon Polly** returns byte-identical mp3 for identical `(text, voice, engine)` — on both the
  `generative` engine (English) and `neural` (Chinese). This was the load-bearing surprise: it is
  what lets `--verify` re-synthesize instead of reusing a cache, so the audio is inside the proof
  rather than beside it.
- **Chromium** screenshots are byte-identical across separate browser launches.
- **ffmpeg** is byte-identical *per single-stream stage* with `-map_metadata -1 -fflags +bitexact
  -flags:v +bitexact -flags:a +bitexact`. Without those flags every output stamps an encoder string
  and drifts. **With** them, a *combined* two-input mux still drifts — see the next section, which is
  the one place this pipeline's first design was wrong and the measurement said so.
- **The payload** is hashed into `RENDER.json`, so "the same render" also means "of the same
  numbers".

### The mux is three calls because one call does not reproduce

The first version of `render.py` muxed frames and audio in a single ffmpeg call, on the strength of a
smoke test that said "ffmpeg with these flags is byte-identical". The first real `--verify` failed:
both mp4s differed between the two renders, while both VTTs matched.

The diagnosis, before any change was made:

| what was compared | result |
|:---|:---|
| video elementary stream (`-map 0:v -c copy -f md5`) | **identical** in both renders, both languages |
| audio elementary stream | **identical** in both renders, both languages |
| `mdat`, `stsz`, `stts`, `stss` atom sizes | **identical** |
| `stsc` (sample-to-chunk), `stco` (chunk offsets) | **differ** — 929 chunks vs 265 |
| the same mux re-run 3× over byte-identical inputs | **3 different files** |
| the same, plus `-max_interleave_delta 0` | **3 different files** |
| video-only encode, re-run | identical |
| audio-only encode, re-run 3× | 3/3 identical |
| `-c copy` remux of the two finished files, re-run 3× | 3/3 identical |

So no media content ever drifted. The muxer grouped identical samples into different chunks, because
its interleaver flushes on whatever the encoders have handed it at that instant — wall-clock
dependent. Splitting into two single-stream encodes plus a copy-only remux removes the dependency:
with both inputs finished on disk, chunking follows from timestamps alone.

The lesson is about the smoke test, not about ffmpeg. It muxed one stream, so it never exercised the
interleaver at all, and it licensed a claim two streams wide from a measurement one stream wide. The
`--verify` arm caught it precisely because it renders the *whole* pipeline twice rather than
re-testing the links individually.

The caveat that survives all of it: byte-reproducibility here is **machine-scoped**. The frames
rasterize whatever Helvetica and PingFang TC this Mac ships. `RENDER.json` therefore records
`platform` beside the hashes, and claims reproducibility on this platform rather than portability to
yours.

## How a number gets into the narration

```
census.json / denominators.json / practices.json / architecture.json   (the published payload)
        │
        └─ scenes.py resolve() ─► {n_published: 91, v_true: …, cl_boxes: …}
                 │                          │
                 │                          └─► frame text and the diagram's box labels
                 └─► render.py resolve_text() fills script/<video>.yaml's {placeholders}
                                │
                                ├─► aws polly synthesize-speech   (the spoken words)
                                └─► the WebVTT cue                (the same words, verbatim)
```

Captions cannot disagree with speech because they are not two artifacts — they are one string used
twice. Chinese narration is fed to Polly **as Traditional characters**, unconverted, for that same
reason: converting for the synthesizer would make the caption text and the synthesis input two
different strings, and the caption is what a reader who cannot hear the track relies on.

Two tests hold the "no authored numbers" line from both sides.
`test_every_narration_placeholder_resolves_and_every_count_is_a_placeholder` rejects any bare
2-or-more-digit integer in a narration template — the failure mode where a number is correct today
and silently stale next build. `test_frames_surface_the_sentinels` renders the scenes from a **lying
payload** of distinctive sentinels (86093, 86091, 86046, …) and requires each to appear in the frame
that claims it. Scanning the source for literals was considered and rejected: it passes a scene that
reads the wrong payload field.

Sentinels are not just distinct, and two rounds of debugging are why. `613` was picked as a phase's
restricted-case count and two tests failed: `613` is also the arrowhead x the layout derives as
`620 - 7`, so a frame "surfaced" a number the payload never supplied. `631` was picked next and the
AFTER chapter looked cross-wired: `631` is a substring of `86317`. So the suite now derives both
guards — `test_the_chapter_sentinels_do_not_collide_with_the_geometry` re-derives the coordinates and
`test_no_sentinel_is_a_substring_of_another_sentinel` checks the table against itself — because a
sentinel that collides with the thing it is meant to distinguish makes every test above it vacuous.

Four chapters multiply the ways a number can be right in the wrong place, so three tests are about
*whose* number it is: each chapter must surface its own phase's counts
(`test_chapter_frames_surface_their_own_phases_numbers`), must **not** surface its neighbours'
(`test_a_chapter_never_shows_another_phases_numbers`), and must highlight exactly the diagram boxes
its own sections own (`test_chapter_highlights_exactly_the_boxes_its_own_sections_own`). A chapter
that read `BEFORE` for all three phases would pass every "the number came from the payload" test
ever written.

`tests/mutation_probe.py` then checks those tests can fail. It edits `scenes.py` in place, so it runs
by hand and never in a gate: control first (53 passed, un-mutated), then eight mutants — cases summed
instead of deduplicated, restricted counted as any restriction, every chapter reading BEFORE, the
loop drawn with nothing faded, highlight = every box with a status, inherited derived as "not own",
spine labels centred on their boxes again, and the label clearance read from the boxes instead of the
connectors. **8 of 8 killed** — and the last two are the two rendering defects below, so a mutant that
restores either one now reds the suite instead of shipping. The clearance mutant is killed by exactly
one arm, which is the discrimination claim: the arm that convicts it is the arm written for it. It restores the file in a `finally` and re-verifies the sha256 afterwards, because
an earlier inline version of this harness was killed by a command timeout mid-mutation and left
`highlight=None)` resident in the module.

## What none of those assertions can see: the frame

Every check above reads text. The chapter dry run's frames were opened and looked at anyway, and
three defects were there that no assertion in this repository would ever have reported — and the
third one was found by looking at the frames rendered to confirm the fix for the first:

- **Box labels overlapped.** Labels were centred on their boxes, and a label up to 66 characters wide
  on a 200-px box runs straight over the satellite label beside it — illegibly, on three of the six
  hops. Every number in the frame was correct and derived. This defect is **live in the already
  published overview video**, which was rendered before the fix and verified byte-for-byte against
  itself. The fix leans each label away from the other column using `satellite`, the payload's own
  derived flag, so the side a label takes is not a coordinate authored here either
  (`test_every_label_leans_away_from_the_other_column`).
- **A count column did not line up.** With each number sizing its own box, a two-digit row pushed its
  caption further right than a one-digit row, and six captions came out on six left edges. Now the
  numbers sit in a fixed right-aligned column, because the numbers are what a viewer compares.
- **The relocated labels crossed the return path.** Leaning the spine's labels left of their boxes
  separated them from the satellites' and put them straight across the loop's own closing edges: the
  gutter and feedback connectors run down the same left margin (x = −38 and −68 in this geometry), so
  a 56-character label anchored 16 units left of a box at x = 0 ran its tail through two 3-unit
  strokes, and the arrowhead re-entering hop #1 landed inside the label's last word. The first fix
  created it, the first fix's own verification frames showed it, and nothing else could have: the
  payload, the manifest, the captions and all 51 assertions were unchanged and correct throughout.
  The clearance is now derived from the **connectors** — the minimum x over every point of every edge,
  computed from the whole edge list so a label does not slide as the reveal adds boxes, and not from
  the edges whose `route` string this file believes runs left, because a route vocabulary is a name
  list (`feedback_scope_as_namelist`). Two arms hold it, both deriving each side rather than pinning a
  coordinate: `test_no_spine_label_crosses_a_connector` and
  `test_a_spine_label_does_not_move_as_the_reveal_adds_boxes`.

All three are recorded here rather than quietly fixed. The general fact is that a rendering pipeline
whose every value is gated can still produce a frame nobody can read, and only opening the PNG finds
it — and the sharper one is that the third defect was *introduced by the fix for the first* and lived
for exactly as long as it took to look at the output again. A fix is a change, and a change to a
renderer is not verified by the tests that passed before it.

## Rendered against *which* numbers

`RENDER.json` records the payload's input hashes, which is what proves "the same render of the same
numbers" between two passes. It cannot prove the shipped payload is the one that was narrated —
`census.json` differs between two builds of the identical register by its `build_stamp` alone, so
hash-equality against the live payload is unusable by construction and was never going to convict a
video rendered last week against a register that has since moved.

So the manifest also records `resolved_values`: the output of `scenes.resolve()`, which is exactly
the set of quantities the narration and frames can contain and nothing else. `arm_media` re-runs
`scenes.resolve()` against the payload being gated and requires every key to agree, naming the ones
that moved. A stamp change is invisible to it; a verdict flipping from INCONCLUSIVE to TRUE is not.

## Voices, and the disclosure that is not optional

| track | voice | engine | language code |
|:---|:---|:---|:---|
| English | Ruth | `generative` | `en-US` |
| Chinese | Zhiyu | `neural` | `cmn-CN` |

Polly ships **no zh-TW voice at all**, and no generative Chinese voice either. So the Chinese track
is Mainland Mandarin on the neural engine, and both the page and the closing scene of the narration
say so aloud, in both languages. This is the same editorial rule the rest of the platform runs on: a
gap gets named, not smoothed over. Describing this track as 真人發聲 or as 台灣華語 would be the
project contradicting itself in the one artifact nobody can diff.

## Where the bytes live, and how the site is allowed to talk about them

`out/` is gitignored. The repository carries what *derives* the video — this file, `scenes.py`,
`render.py`, `script/*.yaml` — and the payload carries the bytes, copied and hashed by
`build_site_data.copy_media()` exactly the way the whitepaper figures are. Committing ~8 MB of mp4
would put the one artifact nobody can review in the one place everything is reviewed.

The honesty chain from render to rendered page:

1. `render.py --verify` writes `out/media/RENDER.json`: script sha256, the four payload input
   hashes, the resolved values, `platform`, per-track voice/engine/duration/sha256, and
   `verified_identical_renders`.
2. `build_site_data.derive_media()` re-hashes every copied file against RENDER.json's declaration
   and dies on a mismatch, so a manifest cannot outlive the bytes it describes. The *expected* file
   set is derived from `script/*.yaml` × `{en,zh}` × `{mp4,vtt}` — the gate's two sides come from
   two producers, not from one list maintained by hand.
3. `check_site_invariants.arm_media` then holds media to a **stricter** standard than figures: a
   drifted figure still ships behind honest wording, but a video whose two renders disagreed does
   not ship at all. Present media requires `render_check == 0` *and*
   `verified_identical_renders == true`, every track flagged `synthesized`, and the string
   "Amazon Polly" present in the shipped bundle.
4. `publish_web.py --render-rc` is passed by whoever ran the double render and **has no default**.
   Omitting it is legal and honest — the payload then reads `render_check: null`, the page reads
   "not verified", and step 3 refuses to publish media in that state. Inventing a `0` is the one
   move the design makes impossible to do quietly.

## Measured, this round

All four videos, one `--verify` run on 2026-09-18, `rc=0` and `verified_identical_renders: true`
(`video/out/render-verify.log`):

| video | scenes | en | zh | en mp4 | zh mp4 |
|:---|---:|---:|---:|---:|---:|
| overview | 10 | 212.3 s (3:32) | 205.6 s (3:26) | 4.49 MB | 3.69 MB |
| before | 7 | 138.8 s (2:19) | 144.1 s (2:24) | 3.14 MB | 2.81 MB |
| during | 7 | 143.1 s (2:23) | 147.1 s (2:27) | 3.19 MB | 2.82 MB |
| after | 7 | 153.5 s (2:34) | 153.1 s (2:33) | 3.41 MB | 2.83 MB |

- **8 tracks, 1298 s of media, 26.39 MB of mp4 plus 21.9 KB of WebVTT.** Every chapter lands inside
  the plan's 2–3 minute target and the overview under its 4–6; both are recorded rather than met.
  Padding narration to hit a runtime would be writing prose for the clock instead of the reader, and
  the numbers spoken are the payload's, so there is nothing to pad with. In all eight the final
  caption cue ends on the last frame of media — `-shortest` at the copy stage trims the video to the
  narration, so there is no silent tail.
- The Chinese track of a chapter runs **longer** than the English one for `before` and `during` and
  shorter for `overview`. Mandarin says the same thing in about a third of the characters (see the
  cost figures below) and is still not uniformly faster, because the two engines differ: Zhiyu is
  neural, Ruth is generative, and the generative voice paces a technical sentence differently. Worth
  writing down because "the Chinese one will be shorter" was the expectation, and it is wrong in
  three tracks of four.
- Reproducibility, incidentally cross-checked in the earlier round: the English mp4 the pipeline
  produced hashed to the same `d7ca1e58…` as a hand-run copy-remux — from a different working
  directory, with different absolute paths in the concat lists.
- Cost, read off the meter: **56,863 characters over 246 `SynthesizeSpeech` requests**, which prices
  at **$1.4939** (`session-logs/polly-spend-20260918-chapters.log`). It decomposes exactly, to the
  request: four verify passes at 58 requests / 13,436 characters each, plus one single-video render
  of `before` at 14 / 3,119. A pass is 58 requests and not 62 because the three chapters close on the
  same `verify` scene word for word, and the cache is keyed on the request — so four of the 62 texts
  are billed once between them. Cumulative for this explainer, both rounds: **85,339 characters, 366
  requests, $2.21–$2.26**, against the repo's $95 ceiling.
- **Of that $1.49, $1.41 is verification and $0.08 is rendering something new.** That is the shape
  this pipeline's own rule gives it: any edit to a scene template invalidates the double render, and
  a second pass that reused the audio cache would prove nothing about synthesis. The eight durations
  are identical across the two verify runs to 0.1 s — the audio never changed, only the frames — and
  the cache still cannot be reused. Recorded because the next person to fix a one-line geometry bug
  should know it costs $0.71, not because the amount is large.
- **Do not count `out/audio/` to bound this.** It holds one mp3 per distinct request, and an earlier
  version of this file read that as proof nothing was billed twice. `--verify` deletes the directory
  between its two renders on purpose (`render.py`, `# force a second synthesis`), so every
  verification bills two full passes and the surviving cache is always one pass wide however many
  were paid for. Spend is a fact about a remote meter; a local artifact cannot bound it. Disclosed
  because undisclosed spend is the failure mode, not the amount.
