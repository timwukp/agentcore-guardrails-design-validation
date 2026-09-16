# 2026-09-16 — GRX validation: the narrated explainer, and the mux that would not reproduce

Session: `fd230f67-029c-480f-a070-54c1670fc4e4` (resume with
`claude --resume fd230f67-029c-480f-a070-54c1670fc4e4` from `/Users/tmwu/Downloads`).
Working tree: `/Users/tmwu/Downloads/grx-validation` (not a git repo — Git Data API pushes only).
Repo: `github.com/timwukp/agentcore-guardrails-design-validation`, main at `35279b34bf08`
(step 3 merged as PR #53).

## What this step delivers

Step 4 of the plan in `~/.claude/plans/lovely-whistling-sphinx.md`: the bilingual narrated explainer
embedded on `/design`, the payload contract that describes it, the gate that refuses to publish it
dishonestly, and the CSP directive without which it would not play at all.

- `video/script/overview.yaml` — 10 scenes, `en` + `zh` (Traditional), every quantity a
  `{placeholder}`.
- `video/scenes.py` — frames and the diagram, drawn from payload coordinates and payload counts;
  `resolve()` is the single place a payload number becomes a narration value.
- `video/render.py` — Polly synthesis → Chromium screenshots → three ffmpeg calls; `--verify`
  renders the whole thing twice and requires every output byte-identical.
- `video/tests/test_scenes.py` — 8 tests, including a lying-payload sentinel render and a rejection
  of any bare 2+-digit integer in a narration template.
- `platform/build/build_site_data.py` — `derive_media()` / `copy_media()` / `--render-rc` /
  `--media-dir`.
- `platform/build/check_site_invariants.py` — `arm_media` (`media_is_real_and_disclosed`), the 57th
  invariant.
- `platform/build/publish_web.py` — `--render-rc` forwarded and recorded in the release pointer,
  with no default.
- `platform/infra/lib/site-stack.ts` — `media-src 'self'`, plus two CDK assertions.
- `site/src/views/Design.tsx` + `strings.ts` / `types.ts` / `data.ts` / `styles.css` — the player,
  the caption track, and the synthesis disclosure as required prose in both languages.
- `video/README.md` — the pipeline, and what each stage measures rather than assumes.

## The one thing that went wrong, and what it cost

`--verify` failed on its first real run: both mp4s differed between the two renders, both VTTs
matched. The diagnosis is logged in full in `mux-determinism-20260916-video.log`. In short:

1. Both elementary streams were byte-identical in both renders, both languages.
2. An atom walk put the entire difference in `stsc` and `stco` — sample-to-chunk and chunk offsets,
   929 chunks against 265. `mdat`, `stsz`, `stts` and `stss` were identical.
3. Re-running the same mux over byte-identical inputs gave 3 different files. Adding
   `-max_interleave_delta 0` gave 3 more.
4. Every single-stream stage reproduced: video-only encode, audio-only 3/3, `-c copy` remux 3/3.

So no media content ever drifted; the muxer grouped identical samples into different chunks because
its interleaver flushes on whatever the encoders have handed it at that instant. The fix is three
ffmpeg calls instead of one.

The real defect was in the *smoke test* that licensed the single-call design: it muxed one stream, so
it never exercised the interleaver, and a one-stream measurement was allowed to license a two-stream
claim. Both `video/render.py`'s docstring and `video/README.md` now say so where the old claim stood,
rather than quietly shipping the fix. Filed as a memory: `feedback_smoke_test_narrower_than_production`.

Second, smaller: the retried `--verify` then died on `Read timeout on endpoint URL: …polly…` after
the first arm had completed every file. `synthesize()` now retries 4 times with 5/15/45 s backoff and
commits through a `.part` rename, because the cache key is the request and a truncated mp3 would have
been served as a hit forever after.

## A defect the test suite found that no gate would have

`media.json` was emitted with an empty source scope whenever nothing had been rendered, and
`emit()` — correctly — refuses a payload file that declares no derivation. On this machine the media
existed, so the build passed; in the suite, 3 tests failed and 80 more errored, all one cause. The
scripts under `video/script/` are now recorded as inputs unconditionally: they are what the expected
file set is derived from, so they are the honest source in the "nothing rendered" state too.

Related, and the reason `--media-dir` exists: the renderer writes into a *gitignored* directory, so
the test fixture's payload silently changed shape depending on whether the developer had rendered the
explainer. With a render present and no `--render-rc`, the media arm correctly failed — reddening the
whole suite for a reason unconnected to the property under test. The media root is now an argument;
the fixture passes an empty directory, and the media arm's own tests fabricate their media state.

## The gate, and its mutants

`arm_media` is deliberately stricter than `arm_figures`: a drifted figure ships behind honest
wording, but a video whose two renders disagreed does not ship at all. Present media requires
`render_check == 0` **and** `verified_identical_renders == true`; every track must declare
`synthesized: true` with a voice, an engine and a measured duration; and the served bundle must carry
the string "Amazon Polly".

Mutation-tested with a no-mutant control first (10 tests, all passing):

| mutant | killed by |
|:---|:---|
| control: complete, hashed, verified media | *passes* — and asserts "4 media file(s) verified byte for byte" |
| an HTML error page saved as `overview.en.mp4` | no MP4 `ftyp` box |
| a caption file without its `WEBVTT` line | does not start with WEBVTT |
| a recorded sha256 that is not the bytes' | does not match its recorded sha256 |
| one language dropped from `present` | present ∪ missing ≠ what the scripts define |
| media present with `render_check: null` | only a 0 from `--verify` licenses shipping |
| `verified_identical_renders: false` beside rc 0 | manifest does not attest verified renders |
| a track claiming `synthesized: false` | the payload breaking the platform's editorial rule |
| a track with `duration_s: 0` | no measured duration |
| "Amazon Polly" stripped from the JS bundle | no Polly disclosure wording in the served bundle |

The fabrication also had to bump `MANIFEST.json`'s `n_outputs`, or the kills would have belonged to
`manifest_liveness` instead — a mutation test whose kill is attributable to the wrong arm is a
coincidence.

## Measured this session

| gate | result |
|:---|:---|
| `video/render.py --verify` | rc 0, `verified_identical_renders: true`, 2 tracks |
| en track | Ruth / generative / en-US, **212.328 s**, 4 693 875 B, 10 scenes |
| zh track | Zhiyu / neural / **cmn-CN**, **205.608 s**, 3 857 242 B, 10 scenes |
| last caption cue | ends exactly at the last frame of media, both tracks — no silent tail |
| payload build | 123 files, 4 media copied, missing none, render check rc 0 |
| site invariants | rc 0, **57** arms (was 56), `4 media file(s) verified byte for byte` |
| invariants test file | 76 passed (66 before, +10 media mutants) |
| `build_site_data` tests | 36 passed |
| census | backlog **299**, byte-for-byte the same set as the published ledger; 17 routes incl. `/design` |
| browser walk, both locales | `readyState: 4`, duration 212.328 / 205.608, 1920×1080, 10 cues, 0 CSP violations, 0 console errors, disclosure present |
| CDK tests | 15 passed, incl. the two new `media-src` assertions |
| tsc / `npm run build` | rc 0 / rc 0 |
| site node tests | 21 passed |
| redaction (repo) | rc 0, **1078** files, 66 569 982 bytes read, re-run after the last edit in the tree |
| — its scan set, from the gate's own `files()` walker | **66** paths under `video/`: 2 mp4, 2 vtt, 20 mp3, 36 png, RENDER.json, 3 py, README, yaml — the byte artifacts are named, not assumed to be covered |
| `gate_payload.py` | rc 0, 123 payload files |
| `check_venv_isolation.py` | rc 0, 8 observations |

Cost: **$0.121** of Polly, all of it — 3 350 English characters on the generative engine at $30/M
plus 1 231 Chinese characters on neural at $16/M. Counted, not estimated: `video/out/audio/` holds
exactly **20** mp3 files, one per scene per language, so no request was ever billed twice. The cache
key is the request, which is why the second render of a `--verify`, the failed Polly-timeout arm and
every re-render since all cost nothing. No new AWS resources. Well under the repo's $95 ceiling.

A correction on the record: an earlier draft of this log and of `video/README.md` said "≈ $1.8" and
"~6,300 characters per pass". Both were arithmetic on a remembered character count, off by roughly
15×, and neither was derived until the numbers above were computed from the script and the cache. An
estimate written in the voice of a measurement is the defect, not the size of the error.

## Deviations from the plan, on the record

- **Python, not a node project** for `video/`. Same Chromium 1208 out of the same Playwright cache,
  same Apache-2.0 licence, and no `node_modules` for the scanners to skip.
- **A screenshot per scene *step*, not per frame.** Progressive-reveal stills timed to the measured
  narration, rather than 30 renders a second of a static diagram. Every load-bearing requirement is
  kept: payload numbers, measured durations, captions from the synthesis input, bitexact stages,
  provenance in `media.json`.
- **Rendered bytes live outside the repository** (`video/out/`, gitignored), exactly as the payload
  does. The repo carries the derivers; the payload carries the bytes, hashed by `copy_media()`.
- **3:32 / 3:26, not the planned 4–6 minutes.** Padding narration to reach a runtime would be writing
  prose for the clock instead of the reader, so the measurement is recorded rather than met.
- **`--media-dir`**, which the plan did not name, for the hermeticity reason above.

## The four inherited reds, each checked rather than waved off

The full sweep over `platform/build/tests tools lib video/tests` is **1 failed, 1478 passed, 10
skipped**; `claims/tests` was not in that sweep's paths, so its three were run separately and all
three still fail. That is the same four reds main already carried, and none of them is new — but
"pre-existing" was verified per finding, not asserted:

| red | flagged | verdict |
|:---|:---|:---|
| `test_results_writes_are_masked` | `platform/audit/report.py:573`, `census_rendered_surfaces.py:651` | neither file is in this changeset |
| `test_cited_paths_exist` | `SITE-REVIEW-20260822.md` cites `curation/scenarios.yaml` | not in this changeset; scenarios.yaml is the user-gated view never built |
| `test_hash_citations` | `DEVIATIONS.md: ebe77ed2…13f85ddf` | not in this changeset |
| `test_repo_copy_exclusions` | `test_check_site_invariants.py:110` and `:124` | **this file IS modified here**, so main's blob was fetched: the same two `copytree` sites sit at lines 100 and 114 there. Step 4 moved them 10 lines down and changed nothing else |

The last row is the reason the check was worth doing: a finding that names a file you just edited
looks like yours, and the only way to tell is to read the other version.

## Still open

- The three phase chapters (before / during / after) — the plan's second video tranche. The script
  format, the gate and the expectation set already take more than one script; adding
  `video/script/phase-before.yaml` makes its absence a *reported gap* rather than a silence.
- Step 5: README / FUTURE-WORK / bundle sync, then a publish and a live probe.
- Unchanged and unrelated: issue #37, and the user-gated items carried from earlier sessions.
