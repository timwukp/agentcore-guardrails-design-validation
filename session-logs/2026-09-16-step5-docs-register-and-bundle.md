# 2026-09-16 — GRX validation: the documentation round, and two scopes that were wrong until run

Session: `fd230f67-029c-480f-a070-54c1670fc4e4` (resume with
`claude --resume fd230f67-029c-480f-a070-54c1670fc4e4` from `/Users/tmwu/Downloads`).
Working tree: `/Users/tmwu/Downloads/grx-validation` (not a git repo — Git Data API pushes only).
Repo: `github.com/timwukp/agentcore-guardrails-design-validation`, main at `aab3c58eebfe`
(step 4 merged as PR #54).

## What this step delivers

Step 5, the last of `~/.claude/plans/lovely-whistling-sphinx.md`: the documentation that describes
what steps 1–4 published, the four deficiencies that shipping them exposed, and the hand-over bundle
re-synced against the result. No behaviour changes on the site; the publish and the live probe stay
user-gated, because flipping the release pointer is outward-facing.

- `README.md` — rows for `platform/`, `site/`, `video/`, `tools/`, the whitepapers, the two v1.4
  documents and the five standing docs; a new section *What the site publishes, and the one rule
  holding it up*; a `## Running` block that names the interpreter each entry point needs.
- `FUTURE-WORK.md` — **36 → 40 items**, all four filed against the shipping work itself.
- `RECONNECT.md` — a resume banner for the plan's step→PR table (#50 / #52 / #53 / #54), and a money
  section whose largest line is now Polly.
- `WHITEPAPER.md:1389` — the register's size, which is a count and therefore has to move with it.
- `video/README.md` — the Polly cost, replaced by a measurement.
- `tools/sync_handover_bundle.py` + its test — two scope defects, both below.
- `session-logs/polly-spend-20260916-video.log` — the meter reading, in full.

## The register grew because four greens were disbelieved

Items **37–40** were not found by reading the code. Each came from not accepting a passing result:

| item | the green that was believed | what it actually said |
|:---|:---|:---|
| 37 | four standing red tests, one red for 27 days | a known red is a red; the register now names each test and the ledger it reads |
| 38 | `--verify` renders twice and the bytes match | on **one machine**. ffmpeg build, Chromium build and voice model are unrecorded, so the claim has no scope |
| 39 | three media gates agree | they share one within-run assumption; **nothing detects a Polly voice-model change**, because both arms re-synthesize from the same voice and therefore agree |
| 40 | `COST.md` says `actual to date $0.00`, all 13 entries `actual_usd: 0.0` | the tag-based method cannot see per-request Polly spend; the real figure is $0.72–$0.77 and appears in no cost file |

Item 39 was itself wrong in draft. I had written that a voice change would surface as a `--verify`
failure. It would not: `--verify` compares two renders of the same release to each other, and
`copy_media()` writes the hashes `arm_media` later re-reads, so every check in the chain is
within-release. Nothing in the repo compares this release's audio against the last one's. The item
was corrected before it was filed, which is the only reason it is worth having.

## The Polly number, wrong twice

`video/README.md` shipped in PR #54 claiming **$0.121**, "counted rather than estimated". Both halves
were wrong, and the justification was worse than the number: the count came from
`video/out/audio/` holding exactly 20 mp3 files, one per scene per language — while `render.py:306`
runs `shutil.rmtree(OUT / "audio")` between the two renders of `--verify`, commented
`# force a second synthesis`. A cache deliberately evicted mid-run bounds nothing that remains in it.

Measured at the meter instead (CloudWatch `AWS/Polly` / `RequestCharacters` /
`Operation=SynthesizeSpeech`, hour by hour, in `polly-spend-20260916-video.log`):

| | |
|:---|:---|
| characters billed | **28,476** |
| requests | **120** |
| price | **$0.72 – $0.77** (the interval is the engine mix, not measurement error) |
| overrun vs. the published figure | **6×** |

The 120 requests decompose exactly into this session's history: two full `--verify` passes and one
single render (3 × 20 = 60 en + 60 zh minus the 6 orphaned English scenes of the first aborted run,
plus 14 draft requests). A total that does not resolve into your own history is not your total.

This was the **second** wrong correction of the same figure — "≈$1.8" from a remembered character
count, then $0.121 from the wrong artifact. A correction inherits no credibility from the error it
replaces, so this one carries its instrument, its dimensions and its decomposition. Both traps in
Cost Explorer are written down as well: `AWS/Polly` has no engine dimension, so characters are
countable there but not priceable; and Cost Explorer returning groups for August and none for
September is a ~1-day lag, not a zero.

## The sync tool's scope was wrong twice, and running it is what said so

Both defects are the same shape as the ones this repo keeps finding: a scope written as a list of
names cannot notice the next name, and a tool that reads its own output cannot be trusted about it.

**1. A fourth cache.** The exclusion set held `__pycache__`, `.pytest_cache` and `.wheel_cache`. A dry
run put six `.ruff_cache/` files in the bundle's ADD list, while the module docstring promised that
"regenerated caches" were left out. The promise is now the predicate —
`CACHE_DIR_RE = ^(__pycache__|\.[\w.-]*cache)$` — with a test asserting seven cache shapes are
excluded (including one for a tool nobody has installed), that no name in `EXCLUDED_DIR_NAMES`
contains "cache", and that `results/cache-behaviour-notes.md` stays **in**. Mutation-checked: control
clean, "rule removed" leaks 7 files, "old name list" leaks 4.

**2. The mirror could not converge.** Three consecutive `--apply` runs derived **42,881 → 42,882 →
42,883** files, gaining exactly one each time, and each run's `check_claims` failed on a README that
had just been corrected to the number the previous run derived. The cause was mine: I logged each run
to `session-logs/bundle-sync-*.log` with the exit code echoed into a sibling `.rc` — inside the tree
being copied. The scan runs before the `.rc` exists, so run N mirrored run N-1's verdict and left its
own behind for run N+1. `OWN_OUTPUT_GLOBS` now excludes the script's own telemetry from the mirror
(the logs stay in the repo, where they are evidence). Mutation-checked both directions: with the rule
removed, 0 of 4 own-output files are excluded; with the lazy fix `session-logs/*`, all four go but so
do 2 of 2 real session logs — 90-odd records of how this platform was built, which is most of what the
bundle is for.

The lesson generalises past this tool: any guard that writes into the tree it inspects has to exclude
its own writes, or its steady state is one file away forever.

## The bundle, after

```
add    : 0
replace: 2      tools/sync_handover_bundle.py, tools/tests/test_sync_handover_bundle.py
delete : 4      the four bundle-sync log/rc files that should never have been copied
MANIFEST.sha256: 42,878 entries; bundle holds 42,879 files, 252 MB (sum of file sizes)
every derivable number in the bundle README agrees with the tree.       rc 0
```

`shasum -c MANIFEST.sha256` from the bundle root: **42,878 OK, 0 mismatches, rc 0**
(`bundle-shasum-20260916-3.log`). The bundle README's own *deliberately left out* table gained the
two rows above, and its two self-referential counts are derived rather than remembered.

The bundle still contains unredacted account ids, ARNs and bucket names under `validation/evidence/`
by design, and is therefore **not distributable**. The script re-states that on every run.

## Item 37 came true before the PR was open

The gate run for this step returned **5 failed, 1558 passed, 10 skipped** over
`claims/tests lib/tests tools/tests`. Four are the reds item 37 tabulates. The fifth was new:

```
claims/tests/test_verify_phase0_gates_every_test_directory.py
  these test directories exist on disk but verify_phase0.sh does not gate them:
    video/tests
```

`video/tests` shipped in PR #54 — 8 arms, run directly as `pytest video/tests`, reported green in the
pull request, merged — and nothing added it to `verify_phase0.sh`. So the explainer's tests rode through
a merge outside the gate that is the reason to believe them, including the sentinel that fails when a
scene's numbers stop coming from the payload. Fixed here: `"video/tests:8"` in `TEST_SPECS`, `video/tests/`
in the combined invocation, and a floor-rationale entry recording how it got missed. `bash -n` clean, the
arm green, `video/tests` 8 passed under the gate's interpreter.

This is the **second** time that same arm has caught the same gap — `tools/tests` was the first, on
2026-08-15, two days after eleven directories were gated as eight. And the only reason it surfaced today
is that I diffed the red set **by name** against item 37's table instead of comparing counts. `5 failed`
against a remembered `4 failed` is precisely the arithmetic item 37 says nobody performs; the item was
written hours earlier, describing a failure mode that then happened.

I also repeated, in the very run that found it, the wrapper mistake item 37 cites: `pytest … | tail -6`
with `echo $?` afterwards recorded **rc 0** for a run with five failures, because `$?` is `tail`'s. That
`.rc` is **deleted, not corrected**: pytest's own code for that run was never captured, and typing `1`
into the file would state an unmeasured value. The log carries a note saying why it has no verdict beside
it, and the verdict lives in `gates-20260916-step5-rerun.log`, whose rc came straight from pytest. A file
that says `0` is worse than a missing one, because an rc exists so a later reader can trust it without
re-reading the log — which is exactly how it would have been read. Knowing a trap by name is not
the same as not walking into it; the defence that works is capturing the rc of the process you care
about, every time, rather than remembering to.

## One thing I read wrong along the way

I took a `.rc` file as the verdict of a run that was still going. The first `--apply` had left its
`.rc` behind; the second was running with an empty log, because python redirected to a file is
block-buffered and an unfinished run looks exactly like a silent one. The `.rc`'s mtime predated the
log's, which is what caught it, confirmed with `ps`. An exit-code file older than the log it belongs
to is a **previous** run's answer.

## Gates

| gate | result | log |
|:---|:---|:---|
| `verify_prereg.py` | rc 0 — SEALED, hash matches `a2136a9d3dbb…`, 189 assertions recomputed | `gates-20260916-step5.log` |
| `pytest claims/tests lib/tests tools/tests` | **5 failed, 1558 passed, 10 skipped** in 43:12 — 4 inherited (item 37) + `video/tests` ungated | `gates-20260916-step5.log` |
| `pytest claims/tests tools/tests video/tests`, after the fix | **3 failed, 587 passed, 7 skipped** in 28:30, **rc 1 captured with no pipe** — exactly the three known claims/tests reds, and `video/tests` now inside the gate | `gates-20260916-step5-rerun.log` |
| `bash -n verify_phase0.sh` | clean | — |
| `shasum -c MANIFEST.sha256`, bundle root | **42,878 OK, 0 mismatches, rc 0** | `bundle-shasum-20260916-3.log` |
| `tools/sync_handover_bundle.py … --apply` | rc 0, "every derivable number in the bundle README agrees with the tree" | `bundle-sync-20260916-apply-3.log` |
| `check_redaction.py --verbose` | **PASSED — 1096 scanned files, rc 0**, read from the `.rc` written immediately after the process and never through a pipe | `redaction-20260916-step5-final.log` |

There are two redaction logs because the gate has to be the **last** thing that runs: the first pass
(1095 files) was overtaken by the note appended to `gates-20260916-step5.log`, so it was re-run against
the tree as it will actually be pushed. A scan whose subject changed after it finished has measured a
tree that no longer exists, and 1 file of difference is the whole reason to re-run rather than reason not
to.

The rc **1** on the third row is correct and expected: three of item 37's four reds live in
`claims/tests`, so a green rc there would mean the suite had stopped seeing them. The number that had to
change is the *set*, and it did — from five names to three, with the fifth fixed rather than absorbed.

## State at the end of this step

| the plan's steps | PR | state |
|:---|:---|:---|
| 1 extractor + `check_practices.py` + practice-evidence map | #50 | merged |
| 2 `closed_loop` diagram | #52 | merged |
| 3 `/design` page | #53 | merged |
| 4 video pipeline + `media.json` + CSP | #54 | merged |
| 5 docs / register / bundle | this PR | open, for the user to merge |

Not done, deliberately: **the publish and the live probe**. Both are outward-facing, so they wait for
the user to say go. After that, the three phase-chapter videos, and the four reds now filed as item 37.
