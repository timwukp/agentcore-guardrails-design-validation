# 2026-09-18 (later) — the post-#58 re-sync, and a sentence that expires with nothing checking it

Session: `fd230f67-029c-480f-a070-54c1670fc4e4` (resume with
`claude --resume fd230f67-029c-480f-a070-54c1670fc4e4` from `/Users/tmwu/Downloads`).
Working tree: `/Users/tmwu/Downloads/grx-validation` (not a git repo — Git Data API pushes only).
Repo: `github.com/timwukp/agentcore-guardrails-design-validation`.

## Main landed

**PR #58 merged 2026-09-18T02:08:09Z** → `main` = **`868ad266b380`**. Verified rather than taken from
the merge's word: `tools/repo_diff.py` reads **1049 remote blobs = 1049 local files, 0 added / 0
modified / 0 deleted**; the head branch `fix/bundle-commit-line-check` returns **404** (auto-deleted);
**0 open pull requests**.

## The deferred `--apply`, and the new check firing on a real stale value

This is the run #58 was written for, and the first thing it did was convict the sentence #58 added the
check for:

```
README.md:25  states 'sha256 of all 42,906 files'      but the derived manifest is 42,909
README.md:101 states 'current as of commit **`6cd5600842e2`** (1,044 blobs'
                                                       but the derived commit is 868ad266b380, 1,049
README.md:255 states '**42,907 files, 261 MB**'        but the derived inventory is 42,910, 261
```

Line 101 is `COMMIT_RE`. **Twelve hours earlier that same sentence was a month and 23 merges stale and
nothing in the world reported it.** It is now stale by one merge and reported at the first opportunity
— which is the whole difference the change bought, and it is exercised end to end here, not in a
fixture.

## The second finding: the clause beside it could not be checked at all, because it was not a number

`README.md:102` said **"No pull request is open, so every file here that `main` carries is also on
`main`"**. That sentence was true when written and **false the moment a pull request opened** — which,
in this repo's workflow, is every round. `check_claims()` cannot check it: it is not a derived value,
it is a claim about a *transient* state of GitHub, and no supplied flag makes a transient fact durable.

The same defect class as the commit line, one clause over: **a sentence that expires, with nothing that
can convict it.** So the fix is not a fresher value — it is to stop asserting a perishable fact.
Reworded to the invariant that actually holds forever about a snapshot:

> The mirror was taken with **zero pull requests open**, so every file here that `main` carries is
> byte-identical to `main` **at that commit** and no unmerged work reached it; repo work done after that
> commit is *absent* from this tree, never divergent.

and followed by a paragraph stating the scope out loud — that the mirror does not track `main`
continuously, that the commit above therefore goes stale between syncs **by construction**, and that
the next sync convicts it instead of letting it read as current. A reader who knows a number is
snapshot-scoped cannot be misled by its age; the month-stale line misled because nothing said so.

## Convergence, and why the loop terminates

Five `--apply` invocations, all in `session-logs/bundle-sync-20260918-final.log` with each run's own rc:

| run | rc | what it did |
|:---|:---|:---|
| 1 | 1 | add 3 / replace 2, manifest → 42,909; convicted the three sites above |
| 2 | 0 | after the three hand-fixes — clean |
| 3 | 1 | after the rewording; convicted **two count sites**, because run 2 had added `bundle-shasum-20260918-final.{log,rc}` to the mirror (+2) |
| 4 | 0 | after fixing 42,909 → 42,911 and 42,910 → 42,912 — clean |
| 5 | 0 | after rewriting the shasum log; add 0 / replace 0, counts unchanged — **fixed point** |

**The loop terminates for one reason**: `OWN_OUTPUT_GLOBS = ("session-logs/bundle-sync-*",)` keeps the
tool's own logs out of the mirror. A tool that copies its own output cannot converge — every run would
produce a file the next run must copy. `bundle-shasum-*` is deliberately **not** excluded, and run 3 is
what that costs: two files, one extra cycle, and the counts move. That is the correct trade (the shasum
result belongs in the archive) but it is why the count sites moved twice in one round.

## Final state

| gate | result |
|:---|:---|
| `--apply --main-sha 868ad266b380 --main-blobs 1049` | **rc 0**, `every derivable number in the bundle README agrees with the tree` |
| manifest | **42,911 entries; 42,912 files, 261 MB** |
| `shasum -c MANIFEST.sha256` | **rc 0 — 42,911 OK, 0 not-OK** |
| `check_redaction.py --verbose`, run **last**, rc read directly | **rc 0** — `PASSED — no unredacted cloud identifiers in 1126 scanned files`, 74,980,525 bytes, 10,968 reviewed exceptions waived (1121 before this round's five files); re-run after this file's final edit and agreeing |

The pre-merge run's one expected `./README.md` mismatch is **resolved**: that manifest predated the
hand-fix, and every `--apply` since rewrote it over the fixed README. Both runs recorded in
`session-logs/bundle-shasum-20260918-final.log`, run B being the one the README's own sentence claims.

The bundle carries unredacted account ids, ARNs and bucket names under `validation/evidence/` and
`validation/runner/.state/` by design. It is never uploaded or attached.

**This file is deliberately NOT in the mirror, and that is now a stated property rather than a debt.**
The bundle is a snapshot of `main` at `868ad266b380`; this round's files are not on `main` yet, so
copying them in would put unmerged work in a tree whose README says none reached it. The reworded
sentence makes "absent" the correct state for post-snapshot work instead of something to excuse. The
next sync picks this file up, the counts move, and `check_claims()` convicts the two count sites — which
is the loop working, not drift.

## The site was NOT redeployed, and did not need to be — derived, not assumed

Asked directly whether anything was deployed to the live app. The answer is no, and here is the basis
rather than a recollection.

The live pointer, read from the payload bucket (`current.json` in `GrxLive`'s `PayloadBucket` output,
us-east-1) rather than from any note in this repo:

```
stamp           20260917T091943Z
release_prefix  /v/20260917T091943Z/
published_by    platform/build/publish_web.py
manifest_sha256 ac598f65860553b04ae347a59e23e9a1f9978f2596c25f97a8e8bc528b551988
figure_check_rc 0      render_rc 0      12 gates rc 0, 1 skipped (no scenarios.json)
```

That is the **design round's step-5 release of 2026-09-17** — the one that put the `/design` page, the
`closed_loop` diagram and the overview video live. It is still what CloudFront serves.

**Neither #57 nor #58 touched a payload input.** Their union is **13 paths** (`tools/sync_handover_bundle.py`
is in both): four test/gate files, `verify_phase0.sh`, `tools/tests/test_sync_handover_bundle.py`, and
seven session logs. Cross-checked against the *published* payload's own declared inputs — 303 distinct
declared paths harvested from the served `MANIFEST.json` + `census.json` — the intersection is **NONE**.
So the bytes CloudFront serves cannot have moved, and a republish would flip a pointer to identical
content.

Scope of that check, stated because it bounds the claim: it reads the declared input paths of two
published files, not a rebuild-and-compare of the whole payload. A rebuild would be the stronger
instrument; it was not run, because the input intersection being empty already settles the question and
rebuilding overwrites the local preview payload.

## Deliberately not done

- **No republish.** Flipping the pointer to byte-identical content spends a CloudFront invalidation to
  change nothing, and every release stamp in this project is supposed to mark a difference.
- **No hand-patched manifest**, at any point in the five runs.
- **No FUTURE-WORK item** for the perishable-sentence defect: it was closed in the change that found it,
  and the register's size is derived, so +1 ripples an exact count across four prose sites.
- **The four standing reds** (FUTURE-WORK item 37) untouched — each needs one ledger entry.
- **The three phase-chapter videos** remain the open plan scope.
