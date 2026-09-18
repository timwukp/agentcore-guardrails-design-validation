# 2026-09-18 — the bundle re-sync, and the one number in its README nothing checked

Session: `fd230f67-029c-480f-a070-54c1670fc4e4` (resume with
`claude --resume fd230f67-029c-480f-a070-54c1670fc4e4` from `/Users/tmwu/Downloads`).
Working tree: `/Users/tmwu/Downloads/grx-validation` (not a git repo — Git Data API pushes only).
Repo: `github.com/timwukp/agentcore-guardrails-design-validation`, main at `6cd5600842e2`
(PR #57 — the argparse-help blocker and the floor-drift detector — merged by the user).

## Main landed

Verified blob by blob rather than by reading the merge's word for it: **1044 remote blobs = 1044 local
files, 0 differing / 0 remote-only / 0 local-only**, head branch auto-deleted, **0 open pull requests**.

## The re-sync, which is what #57 unblocked

`python3 tools/sync_handover_bundle.py ~/Downloads/AgentCore-guardrails-closed-loop-practices --apply`
now runs. Dry run first (rc 1, meaning drift, which is the point of a dry run):
**add 29 / replace 9 / delete 1** — the deleted file is `site/dist/assets/index-DemSrLVX.js`, a
superseded build asset. Then `--apply`, logged to `session-logs/bundle-sync-20260918.{log,rc}` with the
exit code taken from the tool and not from a wrapper:

```
MANIFEST.sha256: 42,906 entries; bundle holds 42,907 files, 261 MB (sum of file sizes; du reports more)
```

`check_claims()` then reported **four** stale numbers, which is the tool working:

```
README.md:25  states 'sha256 of all 42,878 files' but the derived manifest is 42,906
README.md:117 states '40 named deficiencies'     but the derived deficiencies is 41
README.md:131 states '**40** deficiencies'       but the derived deficiencies is 41
README.md:255 states '**42,879 files, 252 MB**'  but the derived inventory is 42,907, 261
```

All four hand-fixed in the bundle README, which the script verifies and never rewrites — prose is not
something a script should edit, and a wrong count is reported *with the derived value* so a human fixes
the sentence around it.

## The finding: a fifth site, which nothing checked at all

The bundle README also said this, at `README.md:101`:

> current as of commit **`a4d836dd91f3`** (776 blobs, local tree and remote verified blob-by-blob after
> the user merged PR #34 on 2026-08-17). **No pull request is open**, …

That commit is **23 merges and one month old**, and 776 blobs against a tree that now holds 1,044. It
had survived every one of the syncs that corrected the other four numbers, for one reason: it is the
only claim in that README `check_claims()` did not recognise. **A README where four sentences are
verified and the fifth is not is read as a verified README** — the same defect the whole script exists
against (`feedback_prose_is_not_verified`), one site over, and the more dangerous instance because the
neighbours' correctness is what makes it credible.

Hand-fixing it would have been the janitor's fix, so the producer got the change
(`feedback_fix_producer_not_janitor`).

### `COMMIT_RE`, and why the values are supplied rather than fetched

```python
COMMIT_RE = re.compile(r"current as of commit \*\*`([0-9a-f]{7,40})`\*\* \(([\d,]+) blobs")
EXPECTED_CLAIM_SITES = {"deficiencies": 2, "inventory": 1, "manifest": 1, "commit": 1}
```

This is the one number the module cannot derive by reading the repo: it lives on GitHub. The tool is
deliberately offline — it copies 42,000 local files and **deletes** — and making a destructive local
operation depend on the network would let it fail for a reason that has nothing to do with the copy. So
`--main-sha` and `--main-blobs` are **supplied** from `tools/repo_diff.py`'s measurement and are **not
defaulted**, which is the refusal `--figure-check-rc` already makes in the publisher: omitting them
leaves the site *counted but unchecked* and the run **non-clean**, rather than silently unverified. Half
the pair is refused at the command line — one claim in two numbers.

Comparison rules, both of which are the reason this is a function and not an `==`:

- a sha compares **by prefix in either direction**, because the README states twelve characters while
  git and the API hand over seven or forty, and an abbreviation is the same commit;
- a blob count compares **as a number**, so `1,044` and `1044` are not a difference.

### Arms (4 new functions = **8** collected; `tools/tests/test_sync_handover_bundle.py` **35 → 43**,
all passing in 8.67 s)

| arm | what it holds |
|:---|:---|
| `test_the_commit_sentence_agrees_when_both_values_are_supplied` | the clean case |
| `test_omitting_the_values_leaves_the_run_non_clean_instead_of_skipping_the_site` | a gate that could not run must not report clean — **and** the site is still counted, so rewording the sentence to escape the check fails on the exact-site-count assertion instead |
| `test_the_commit_check_discriminates_on_both_of_its_numbers` (×5) | `6cd5600842e2`/`1,044` and `1044` and the abbreviation pass; **the real stale sha** `a4d836dd91f3` fails; **the real stale blob count** 776 with the *right* sha fails — two numbers, two claims |
| `test_supplying_one_value_without_the_other_is_refused_at_the_command_line` (×2) | `main()` raises rather than checking the sha alone |

One incidental repair the new site forced: six existing claim arms monkeypatched
`EXPECTED_CLAIM_SITES` as a **literal three-key dict**, so a fourth site made them raise `KeyError`.
They now go through `_sites(mod, monkeypatch, **counts)`, which derives *zero of every other known site*
from the real dictionary. A test that restates a production structure as a literal is a second copy of
it, and the fifth site would have hit the same six arms again.

## Verification

| gate | result |
|:---|:---|
| `tools/tests/test_sync_handover_bundle.py` | **43 passed**, 8.67 s — **35** before this change, measured off the pre-change collection rather than remembered (the tool's docstring says "32-arm", which is a dated claim from 2026-08-17, not today's count) |
| `lib/tests/test_argparse_help_strings.py` (the new `help=` strings must survive it too) | 8 passed |
| `shasum -c MANIFEST.sha256` over the bundle | rc 1, **42,905 OK, one FAILED: `./README.md`** — expected, see below |
| `check_redaction.py --verbose`, run **last**, rc read directly | **rc 0**, `PASSED — no unredacted cloud identifiers in 1121 scanned files`; a second pass after this file's final edit agreed at the same count, both writing outside the tree |

**The one shasum mismatch is honest bookkeeping, not corruption, and it is not a `validation/` file.**
The manifest was written by this date's `--apply`; `check_claims()` then reported the four stale numbers,
and the README was hand-fixed *afterwards* — so the manifest holds the pre-fix README's digest. It
resolves on the next `--apply`.

**Which is deliberately not today.** The bundle currently mirrors `6cd5600842e2` **exactly**, because the
`--apply` ran while the tree still equalled `main`. Re-applying now would copy this round's
unmerged files into it and make the README's neighbouring sentence — *"No pull request is open, so every
file here that `main` carries is also on `main`"* — false, which is the class of defect this whole round
is about. So the final `--apply --main-sha … --main-blobs …` happens **after this round's pull request
merges**, when the mirror, the manifest, the commit sentence and the no-open-PR sentence can all be true
at the same moment. That is also when the new check gets exercised end to end.

The bundle carries unredacted account ids, ARNs and bucket names under `validation/evidence/` and
`validation/runner/.state/` by design. It is never uploaded or attached.

## Deliberately not done

- **No hand-patched manifest.** Rewriting one line of `MANIFEST.sha256` to make `shasum -c` quiet would
  be repairing the diagnostic instead of the tree.
- **No network call added to the sync tool**, for the reason recorded next to `COMMIT_RE`.
- **The four standing reds** (FUTURE-WORK item 37) are untouched; each needs one ledger entry, which is
  that item's close condition.
- **No floor raised.** `tools/tests` collects 130 against a floor of 122; the drift arm added in #57
  allows `max(12, 8%)` = 12 and 8 are used, and the script's rule is that floors move when a suite
  grows by a **file**. The next file there will trip the detector, which is it working.
- **No FUTURE-WORK item** for the commit-line gap: it was closed in the change that found it, and the
  register's size is derived, so +1 ripples an exact count across four prose sites in three documents.
