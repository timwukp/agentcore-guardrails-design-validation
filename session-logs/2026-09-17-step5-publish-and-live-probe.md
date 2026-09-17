# 2026-09-17 — GRX validation: the design goes live, and the probe becomes an instrument

Session: `fd230f67-029c-480f-a070-54c1670fc4e4` (resume with
`claude --resume fd230f67-029c-480f-a070-54c1670fc4e4` from `/Users/tmwu/Downloads`).
Working tree: `/Users/tmwu/Downloads/grx-validation` (not a git repo — Git Data API pushes only).
Repo: `github.com/timwukp/agentcore-guardrails-design-validation`, main at `a50bbed43012`
(step 5's documentation merged as PR #55).

## What this round delivers

The second half of step 5 of `~/.claude/plans/lovely-whistling-sphinx.md`, authorized explicitly
because it is outward-facing: **publish a new release and probe it**. Both halves of that sentence were
done, in that order, with the gate run first and the pointer flipped last.

- **Release `v/20260917T091943Z/` is live.** Twelve gates at rc 0, one skipped by a property of the
  payload rather than by choice.
- **`platform/build/walk_release.py`** — new, ~330 lines. The browser probe that every release so far
  had, and that no release could repeat, because every one of those probes lived in `/tmp`.
- Three logs and their exit codes: `publish-dryrun-20260917`, `publish-confirm-20260917`,
  `walk-release-20260917`, plus `walk-release-20260917-controls.log`.
- **`FUTURE-WORK.md` 40 → 41 items.** Item 41 is what this publish proved it cannot see.
- **Two test directories, 435 arms, brought inside `verify_phase0.sh`** — they had never been in it, and
  the arm written to notice that could not see them either. Recorded in item 37 as its third instance.

No re-render, so **no additional Polly spend**. Incremental cost is S3 PUTs plus one CloudFront
invalidation — cents, against a repo ceiling of $95.

## The publish

`--dry-run` first, at stamp `20260917T091155Z`: every gate rc 0, `scanned 1098 files`, three diagrams
laid out, `architecture coverage 92 placed + 1 unplaced = 93 registered`, 21 SPA tests actually run
(the runner verifies the count, because `node --test` over a glob that matches nothing exits 0),
`PASSED — 57 site invariants`. The figure numeric check reported `FRESH` at rc 0, and that rc is
**measured by the publisher itself** rather than passed in: `pub.figure_check_rc = figures.rc`, with
`rc_ok=(0,1)` because rc 1 there is *data* the site renders as a freshness badge. Only `--render-rc`
comes from the operator, because `video/render.py --verify` is a double render that re-bills Polly, so
nothing may infer it.

Then `--confirm`, at stamp `20260917T091943Z`: `scanned 1100 files` (the two dry-run logs are now in
the tree — every new log changes the redaction gate's subject, which is why that gate runs last in a
manual sequence), upload to `v/20260917T091943Z/`, then `current.json`, then the root `index.html`
**last**, then `invalidation IC2TC1TEMW6RX6YH8VG8VRMTLY for /index.html, /current.json, /`.

The order is the safety property: the pointer is the last object written, so a failed gate leaves the
previous release serving and a half-finished upload is not reachable from anywhere.

`verify_served()` then re-downloaded what the bucket holds, in the two halves `upload()` wrote —
`fetched 123 payload object(s), set-equal` and `fetched 4 SPA object(s), set-equal` — and re-ran the
redaction patterns over the **fetched** bytes at rc 0. Set equality, not a count: one file missing and
one file extra is the same integer.

The live pointer, read back from the origin afterwards:

| field | value |
|:---|:---|
| `stamp` | `20260917T091943Z` |
| `manifest_sha256` | `ac598f65…` |
| `figure_check_rc` | 0 |
| `render_rc` | 0 |
| `gates` | 12, all rc 0 |
| `gates_skipped` | `['scenario curation gate']` — the payload contains no `scenarios.json`, so the gate is not required; the B2B/B2C lens is still unauthored |

## The probe, and why it is a file

`walk_release.py` exists because of a defect in the *method* of the previous four releases: each was
walked in Chromium before the flip, each walk's output survived under `session-logs/`, and each walk's
**instrument** was a throwaway script in `/tmp`. PR #54's probe cannot be re-run. Nobody can now state
which selectors it read or what its thresholds were. A measurement whose instrument is gone is a claim,
and the whole argument of this repository is that claims and measurements are different things.

Three things it reads that no other check in the repo can:

1. **CSP violations, counted at the page.** The listener is installed with `add_init_script`, before
   any application script runs, because a violation fired during the first paint is exactly the one a
   listener attached afterwards cannot see.
2. **Every `<video>`, at the element.** `readyState`, `duration`, `videoWidth/Height`, `error`, and the
   caption track's cue count — then the measured duration compared against `media.json`'s own published
   `duration_s`. A `<video>` that decodes nothing renders its poster and raises no error; a caption
   track the browser dropped is silent everywhere else.
3. **The four verdict colours from `getComputedStyle`.** The stylesheet arm in
   `check_site_invariants.py` reads the *sheet*; this reads the *screen*. This project has already
   shipped the gap between those two claims once — on 2026-08-20 the served page rendered all 38
   diagram boxes in the neutral slate while the class tokens were present in the CSS, because a
   single-class selector later in the file shadowed the rule (`site/src/styles.css:795`).

It imports the route table from `census_rendered_surfaces.py` and the contrast arithmetic from
`check_site_invariants.py` instead of restating either, and calls `check_route_tables_agree()` itself
rather than trusting that something else did. Two copies of the WCAG formula would let the probe and
the gate report different ratios for the same pair of colours.

### What it measured against the published bytes

13 routes × 2 locales, served by `csp_preview.py` under the CSP parsed out of `site-stack.ts`,
at the release's own path:

| | |
|:---|:---|
| CSP violations | **0** |
| console / page errors | none |
| videos read at the element | 2 (`overview.en.mp4`, `overview.zh.mp4`) |
| `readyState` | 4 for both |
| duration measured vs `media.json` | 212.328 s / 205.608 s, both within 0.05 s of the published value |
| decoded size | 1920×1080 both |
| caption cues | 10 each; track languages `en` and `zh-TW` |
| verdict contrast on screen | FALSE 6.50:1 · INCONCLUSIVE 6.75:1 · RECORDED 5.12:1 · TRUE 5.89:1 (11 px / 400), all clearing AA's 4.5:1 |
| Polly disclosure present beside each player | yes, in both languages |

Two properties of the page force the probe's shape, both established by measurement rather than
assumption: the app is a **HashRouter**, so changing only the fragment is not a navigation and
`wait_until="load"` resolves against the previous document — hence a distinct `?walk=<i>` per route;
and `preload="metadata"` means a healthy video reads `readyState 0` until the probe calls `v.load()`
and waits for `readyState >= 1 || v.error`. A false negative of that kind is how a probe stops being
believed.

### Three controls, because `problems: []` proves nothing on its own

Full output in `session-logs/walk-release-20260917-controls.log`.

| control | mutation | result |
|:---|:---|:---|
| 1 | the same release served under the stack's CSP **minus `media-src`** (the policy before PR #54) | **rc 1**, 6 problems: mp4 *and* vtt blocked, `MediaError code 4`, both locales |
| 2 | `inv.AA_CONTRAST` patched to 7.0 (AAA) | **rc 1**, all four ratios convicted — so the numbers come from the page, not from a constant |
| 3 | `--prefix /v/19990101T000000Z` | **rc 2**, `CANNOT RUN` — a refusal, distinct from rc 1's verdict |

## Three things that went wrong, and what each cost

**`${PIPESTATUS[0]}` recorded an empty exit code.** The first controls capture ended with
`control-1 rc=` beside a page of real failures: zsh has no `PIPESTATUS` (it is `$pipestatus[1]`). Same
class as the `| tail` that recorded rc 0 for a five-failure pytest run the day before, and the second
time in two days that an rc was lost to a pipe. Fixed by writing each process's output to a file and
`echo $? > …rc` on the next line; the controls were re-run and the log rebuilt around the captured
artifacts. **An exit code read through a pipe is not that process's exit code.**

**The publish log named the payload bucket, twice.** `lib.redact.mask_text` left it unchanged
(`changed: False` — the bucket name matches no pattern in the masker), while `check_redaction.py` *does*
carry an S3-bucket-URI pattern, so the log would have failed the push after the fact. Replaced by hand
with `<bucket>`, following the existing convention in `session-logs/runner-teardown-20260819.log`, and
the edit is declared in a `NOTE` appended to the log itself rather than left invisible. The bucket is
regenerable from the `GrxLive` stack's `PayloadBucket` output, so nothing is lost.

**A stamped build cannot be previewed at `/`.** `npm run build -- --base=/v/<stamp>/` emits absolute
asset URLs, so the local preview serves an index that requests `/v/<stamp>/assets/…`. Rebuilding with a
relative base would have walked *different bytes than were published*. Solved instead with
`ln -sfn ../../dist site/dist/v/<stamp>`, which serves the exact published bytes at the exact published
path; the symlink was removed afterwards and `site/dist` left as the publisher leaves it.

## And the round's largest finding, which was not about the publish at all

Reading `verify_phase0.sh` while writing the log above, I listed every `*/tests` directory on disk **with
its depth**. Thirteen were in `TEST_SPECS`. Fifteen exist:

| directory | arms | in the gate |
|:---|--:|:---|
| `platform/build/tests` | 378 | **no** |
| `platform/audit/tests` | 57 | **no** |

**435 arms outside the repo's own test gate, since the day each was written** — more than the twelfth and
thirteenth directories combined (`tools/tests` 48, `video/tests` 8), and they are not incidental arms:
they are the mutation-checked refusals of `gate_payload.py` and `build_site_data.py`, the three states of
`--figure-check-rc`, and the audit report's two documents. The layer the publish trusts was the layer
running outside the gate that is the reason to trust it.

The part worth keeping is *why the check missed it*.
`claims/tests/test_verify_phase0_gates_every_test_directory.py` exists precisely to hold the
hand-written list equal to the tree — it caught `tools/tests` in August and `video/tests` yesterday — and
its `_on_disk()` globbed `*/tests` only, with a docstring explaining that the depth "match[es] the
project layout the gate encodes (`<family>/tests`)". That sentence was true of the eleven family
directories and false of `platform/`. A hand-written list is a claim about the tree; **a discovery
pattern is the same claim one indirection further in**, and the docstring excusing where a guard need not
look is where the next instance hides.

Sharper still: the table in `FUTURE-WORK.md` item 37 — this project's own record of its standing reds —
was produced by running `pytest platform/build/tests tools lib video/tests` **by hand**. Those arms were
being read as evidence in the same breath as being absent from the gate, and nobody noticed because
running them by hand produced the same green either way.

Fixed here, not filed:

- `TEST_SPECS` gains `platform/build/tests:378` and `platform/audit/tests:57`, both in the collect-count
  loop and in the combined invocation, with the rationale recorded beside the other fourteen.
- `_on_disk()` walks `*/tests` **and** `*/*/tests`, excluding third-party trees through the shared
  `scan_scope.out_of_scope` predicate rather than a fourth copy of a skip list.
- Two new arms hold the depth limit itself: one compares the bounded walk against an unbounded
  `rglob("tests")` and fails with instructions if anything ever sits deeper; one is the control proving
  the extra depth is load-bearing *today*, so the widening cannot be silently reverted.
- Two mutation arms, with the unmutated tree as the control (4 passed before them, 6 after): dropping
  `platform/build/tests:378` from a **copy** of the script must fail the set comparison, and restoring the
  original depth-1 glob must fail both new arms. Neither mutant writes to the tree.

Measured, so the cost of the fix is on the record: **435 passed in 541.03 s** (`rc 0`,
`session-logs/platform-tests-20260917.log`), which makes the full gate about 9 minutes longer than the
1 h 24 min 16 s that item 31 records for its twelve-directory run of 2026-08-17.

## The red set, diffed by name

`claims/tests lib/tests tools/tests video/tests platform/build/tests platform/audit/tests`:
**4 failed, 2006 passed, 10 skipped in 1 h 08 min 04 s**, rc 1
(`session-logs/tests-20260917-docs-round.log`). The four FAILED lines were compared **as a set of
names** against `FUTURE-WORK.md` item 37's table, not as a count — which is the whole point of that item,
and is what caught a fifth red yesterday:

| red | in item 37's table |
|:---|:---|
| `claims/tests/test_cited_paths_exist.py::test_every_cited_repo_path_exists` | yes |
| `claims/tests/test_hash_citations.py::test_every_elided_hash_citation_resolves_to_a_derivable_hash` | yes |
| `claims/tests/test_repo_copy_exclusions.py::test_every_dynamic_copy_source_is_declared_and_still_there` | yes |
| `lib/tests/test_results_writes_are_masked.py::test_a_write_in_a_results_module_is_masked_or_placed_outside_results` | yes |

No new reds, none went green. Their *contents* were read too, not just their names, because a documented
red can hide a new instance inside itself: all four flag exactly the sites the table names, with one
addition — `test_every_cited_repo_path_exists` now reports **two** sites for the same missing
`platform/curation/scenarios.yaml`, the second being item 37's own table, written yesterday. The table
now says so rather than under-reporting its own red.

## Item 41 — what this publish proved it cannot see

The publish path is strong about bytes and silent about headers. `verify_served()` re-downloads the
release and re-scans it; meanwhile the `Content-Security-Policy`, the `Cache-Control` and the
Lambda@Edge auth decision are all asserted **from `site-stack.ts`** — by a CDK test against the
synthesised template, and by `csp_preview.py`, which parses the same file. Two green checks over one
source. Nothing reads the deployed `ResponseHeadersPolicy`, and nothing reads back the immutable
`Cache-Control` the publisher claims to set.

The last mile is genuinely unreachable from here and the middle is not, which is what makes it a
deficiency rather than a scope decision. Three unauthenticated requests to the distribution today — the
root, `/current.json` and the new stamped path — all returned **302** to
`<pool-domain>.auth.us-east-1.amazoncognito.com/authorize`. That is the gate failing closed, which is
the desired behaviour, and it is also why the object's headers cannot be observed: a redirect carries
the redirect's headers. The pool has `mfa: REQUIRED` and this platform must never create an account, so
no scripted browser will ever hold a session here.

Item 41's cheap half is one boto3 call —
`cloudfront get-response-headers-policy` compared character for character against the parse of
`site-stack.ts`, plus an `s3api head-object` on one immutable and one mutable object. That is the check
that would catch a console edit. The viewer path itself closes only as a **dated** record: a human with
the second factor, pasting the response headers into a log labelled with the release stamp they were
read against.

## Deliberately not done

- **No re-render.** `render.py --verify` re-synthesizes from Polly by design, so running it to feel
  better about `--render-rc 0` would have billed a second full pass for a pipeline whose inputs did not
  change.
- **No live browser walk.** See above; it is filed, not fudged.
- **No handover-bundle re-sync.** The bundle currently mirrors `a50bbed43012`, where the register holds
  40 items. Bumping its count now would trade one stale number for another — the bundle would claim 41
  while mirroring a commit that has 40. It re-syncs after this PR merges.
- **No change to the phase chapters.** Three of them remain unbuilt; that is the next round.

## Files this round touches

| file | change |
|:---|:---|
| `platform/build/walk_release.py` | new — the release probe, with its scope limits in its own docstring |
| `session-logs/publish-dryrun-20260917.log` / `.rc` | the gate run, rc 0 |
| `session-logs/publish-confirm-20260917.log` / `.rc` | the publish, rc 0, bucket name hand-redacted with a declared NOTE |
| `session-logs/walk-release-20260917.log` / `.rc` | the walk, rc 0 |
| `session-logs/walk-release-20260917-controls.log` | the three controls, rc 1 / 1 / 2, rebuilt after the lost rc |
| `verify_phase0.sh` | `platform/build/tests:378` and `platform/audit/tests:57` — the fourteenth and fifteenth gated directories |
| `claims/tests/test_verify_phase0_gates_every_test_directory.py` | `_on_disk()` widened to two depths through the shared scope predicate; 2 new arms over the depth limit + 2 mutation arms |
| `session-logs/platform-tests-20260917.log` / `.rc` | 435 passed in 541.03 s, rc 0 — the measurement behind the two floors |
| `FUTURE-WORK.md` | 40 → 41 items; item 41 and the preamble that accounts for it; item 37 gains the third instance of the ungated-directory gap |
| `RECONNECT.md` | the resume banner (all five steps merged, the live release, the probe, item 41) and both register counts |
| `WHITEPAPER.md` | the register's size, which is a count and has to move with it |
| `README.md`, `platform/README.md` | `walk_release.py`: how it is run, what only a browser can answer, and what it cannot reach |
