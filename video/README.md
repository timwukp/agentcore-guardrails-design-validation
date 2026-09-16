# `video/` — the narrated explainer, and why every second of it is derived

This directory renders the bilingual explainer embedded on `/design`. It exists to answer one
question a reader of that page will reasonably ask — *did you measure this design, or did you write
it?* — in the one medium where an unsupported claim travels furthest and gets checked least.

So the rule for this pipeline is stricter than for the prose: **nothing in the video is authored
here.** Every number is read from the published payload at render time, every spoken sentence is the
caption text verbatim, and the whole render is run twice and compared byte for byte before the page
is allowed to call it verified.

## What is in here

| file | what it is | what it must never contain |
|:---|:---|:---|
| `script/overview.yaml` | the 10 scenes' narration, `en` + `zh`, with `{placeholders}` for every quantity | a literal count; a paraphrase of a verdict; a claim of human narration |
| `scenes.py` | the frame HTML/SVG, and `resolve()` — the single place a payload number becomes a narration value | a hardcoded palette, a hardcoded coordinate, a hardcoded total |
| `render.py` | synthesis → screenshots → mux, and `--verify`'s double render | a duration target the narration was assumed to hit |
| `tests/test_scenes.py` | 8 tests, run under `.venv-oracle` | — |
| `out/` | **gitignored.** frames, audio cache, `media/`, `RENDER.json` | — |

## Running it

```sh
# both languages, one pass — for iterating on wording or layout
/opt/homebrew/opt/python@3.12/bin/python3.12 video/render.py

# the publishable render: twice, fresh synthesis both times, every sha256 must match
/opt/homebrew/opt/python@3.12/bin/python3.12 video/render.py --verify
echo "rc=$?"          # this rc is what publish_web.py's --render-rc wants; read it directly

.venv-oracle/bin/python -m pytest video/tests/ -q
```

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
                 └─► render.py resolve_text() fills script/overview.yaml's {placeholders}
                                │
                                ├─► aws polly synthesize-speech   (the spoken words)
                                └─► the WebVTT cue                (the same words, verbatim)
```

Captions cannot disagree with speech because they are not two artifacts — they are one string used
twice. Chinese narration is fed to Polly **as Traditional characters**, unconverted, for that same
reason: converting for the synthesizer would make the caption text and the synthesis input two
different strings, and the caption is what a reader who cannot hear the track relies on.

Two tests hold the "no authored numbers" line from both sides. `test_narration_placeholders_resolve`
rejects any bare 2-or-more-digit integer in a narration template — the failure mode where a number
is correct today and silently stale next build. `test_frames_surface_payload_numbers` renders the
scenes from a **lying payload** of distinctive sentinels (86093, 86091, 86046, …, all mutually
distinct so a swapped pair fails too) and requires each to appear in the frame that claims it.
Scanning the source for literals was considered and rejected: it passes a scene that reads the wrong
payload field.

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

- Overview: **3:32** English (4.69 MB), **3:26** Chinese (3.86 MB), 10 scenes each, and in both the
  final caption cue ends on the last frame of media — `-shortest` at the copy stage trims the video
  to the narration, so there is no silent tail. Shorter than the 4–6 minute target in the plan;
  padding the narration to hit a number would be writing prose for the runtime instead of the
  reader, so the measurement is recorded rather than met.
- Reproducibility, incidentally cross-checked: the English mp4 the pipeline produced hashes to the
  same `d7ca1e58…` as the hand-run copy-remux during the diagnosis above — from a different working
  directory, with different absolute paths in the concat lists.
- Cost, counted rather than estimated: the narration is **3,350 English characters** (Ruth,
  generative, $30/M) and **1,231 Chinese characters** (Zhiyu, neural, $16/M) — **$0.121** to
  synthesize the whole explainer once. `out/audio/` holds exactly **20** mp3 files, one per scene per
  language and no more, which is the evidence that nothing was ever paid for twice: the cache key is
  the request, so the second render of a `--verify` and every re-render since cost $0. Chinese is
  cheaper by characters, not by rate — Mandarin says the same thing in a third of the glyphs.
  Disclosed because undisclosed spend is the failure mode, not the amount.
