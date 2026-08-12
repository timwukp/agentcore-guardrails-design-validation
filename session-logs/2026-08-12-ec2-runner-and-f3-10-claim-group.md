# Session log — 2026-08-12: the EC2 runner, and the claim group F3-10 answers for

**Resume this conversation with:**

```
claude --resume 8772d51a-6471-4747-a0da-9e2d1e42c8e7
```

Transcript on disk:
`~/.claude/projects/-Users-tmwu-Downloads/8772d51a-6471-4747-a0da-9e2d1e42c8e7.jsonl`

Continuation of `2026-08-11-f2-1-green-and-span-surface.md`. Object under test throughout:
`~/Downloads/agentcore_guardrails_best_practices_v1.2.md` (74,465 bytes, sha256 `46644958…`, which
is the hash `PREREGISTRATION.yaml` pins).

## Live state of the runner, for whoever reads this next

| thing | value |
|---|---|
| instance | `i-0f90ac6377bba523b`, `t3.small`, us-east-1, 20 GiB gp3 encrypted |
| access | SSM Session Manager only — zero ingress rules, egress tcp/443 |
| bucket | `grx-validation-runner-<suffix>` (private, SSE-S3, versioned, 90-day expiry) — real name in the gitignored `runner/.state/runner.json`, and **never written down here**: see DEV-P4-25 |
| cost | ~$17/month while up, nothing after `runner/teardown.py` |
| interpreter | python3.12.13, `deps: boto3 1.43.67  numpy 2.5.2  scipy 1.18.0  pytest 9.1.1` |
| on the instance | 2,614 python files, 26,620 evidence files, 14 external input files |

Everything is driven from the laptop with four commands:

```
runner/sync.py push            # the working tree
runner/sync.py push-evidence   # 178 MB, only when a live case has run
runner/sync.py push-inputs     # the document under test + the PII corpus
runner/sync.py rebootstrap     # re-run bootstrap.sh in place
runner/run.py --detach --label <name> '<cmd>'   # survives the laptop closing
runner/run.py --jobs / --tail <name>
```

## What happened, in order

1. **`sync.py rebootstrap`, and why it had to exist.** EC2 user data runs **once**, at first boot.
   Every `grx-*` helper, scratch directory and shell-env line that `bootstrap.sh` installs is
   therefore frozen at whatever the script said the day the instance launched — so `grx-evidence`,
   written after that day, simply did not exist on the running machine, and the first hand-rolled
   attempt to pull the evidence archive died on the very tmpfs the newer script avoids. That is
   `feedback_embedded_asset_staleness` in shell form: an edit that only reaches the *next* instance
   is an edit that is not on the machine doing the work. The fix renders the script through the
   **same** `provision.render_bootstrap()` the launch path uses and re-runs it over SSM as a single
   `commands` entry (it uses `set -uo pipefail`, an `exec > >(tee)` redirect and functions, none of
   which survive being split into separate entries, each its own shell). Every step is idempotent,
   so "run it again" is always the safe move — which meant making the `.bashrc` append
   marker-guarded, because an unguarded `>>` stacks a duplicate block on every rerun.

2. **`/tmp` is a tmpfs at half of RAM — 957 MB on a t3.small — and the offline suite fills it.**
   26 test modules `copytree` the 178 MB evidence tree into their `tmp_path`, so one run wrote
   954 MB of scratch and the *next* command failed with `[Errno 28] No space left on device` while
   `df` on the repo showed 18 GB free. The error names the wrong thing. Scratch now lives on the
   root volume in four places that have to agree: `run.py`'s `PREAMBLE`, `bootstrap.sh` from line 1,
   the `.bashrc` block, and `--basetemp=/opt/grx/tmp/pytest` (which pytest wipes at start, bounding
   it). The `mkdir` comes **before** the `export`, because a `TMPDIR` that does not exist breaks
   `dnf` and `pip` with an error that names neither.

3. **Suite on the instance: 156 failed / 170 errors → 26 failed / 21 errors.** After the evidence
   tree arrived and TMPDIR moved: `26 failed, 1660 passed, 3 skipped, 21 errors in 528.74s`. The
   remainder resolved into **two missing external inputs plus one write-guard cluster**, not 326
   undifferentiated failures.

4. **`sync.py push-inputs` — the two things the suite reads from outside the repo.** All 21 errors
   were `claims/tests/test_corpus_gate.py` refusing to run without the PII corpus, and most of the
   26 failures were the redaction gate and `verify_prereg.py` unable to find the document under
   test. Neither is in the tree, so `push` could never have carried them, and neither is a defect —
   a validation project whose subject is a document has to be handed the document. The set is
   **derived**, by walking `PREREGISTRATION.yaml` for any string value beginning `~/` or `../`:
   those are exactly the two ways that file can name something it does not contain, and they are
   resolved the same way by the code under test (`~/` against `Path.home()` per
   `claims/check_coverage.py:40` and `verify_prereg.py:984`; `../` against the repo root). A
   hand-written pair would be a second enumeration of "what this suite needs from outside", short by
   one the day a third input is declared. A declared `sha256` is **checked before upload, not
   recorded after** — shipping a document that is not the sealed one would give the instance a
   different subject while every result still said v1.2. The archive layout *is* the destination
   (`inputs/home/…`, `inputs/repo-parent/…`), so `grx-inputs` holds no path of its own to drift, and
   the document lands in **both** `/root/Downloads` and `/home/ec2-user/Downloads` because which one
   `Path.home()` returns depends on whether the suite was started over SSM or interactively.
   `runner/tests/test_runner_inputs.py`: 8 arms, including the wrong-hash mutation with its control.

5. **A real correctness defect in F3-10: the claim group was 9, the register says 10.**
   `08_score_label_join.py` published `sealed_units_in_this_claim_group` as a hand-written tuple of
   nine ids. The missing one, `C-s7-1-prose-004`, is **§7.1 step 3's own sentence** — *"Label results
   and use the confidence scores in the logs to build a confusion matrix"* — and therefore the unit
   the case exists to answer for. It was omitted because its `cases` cell reads `"F3-10 F3-9"`: the
   one F3-10 row a whole-cell comparison misses. Membership is now by **whitespace token**, which is
   how `claims/check_coverage.py` reads the same column, and `_sealed_units()` lives in the parent
   with `08b` importing it by name so the two files cannot disagree. The mutation check reproduces
   the whole-cell bug so the guard is not vacuous. The derived 10 matches FINDING-F5-4A §11's
   independent count. A list typed into a payload is a claim nothing checks
   (`feedback_prose_is_not_verified`), and how many units a finding touches decides how much of the
   document an amendment has to reach.

   Consequence to record as a deviation: **`results/phase1/F3-10.json` still carries the stale
   9-item list**, because re-running 08 costs 122 live requests and two mode flips.
   `F3-10_log_surface_join.json` was regenerated and carries `"n": 10`.

6. **F3-10's status is decided by its evidence, not by preference.** All 1,491 records carry
   `t_start_utc` on a single calendar day (`days: {'2026-08-12': 1491}`), so per the sealed `MIN_DAYS`
   rule the FINDING must be `OBSERVATIONS_COMPLETE` with a non-empty `blocked_on`, not
   `READY_TO_AMEND`. `check_amendment_readiness.py` prints `OK — 52 assertions over 10 findings`.

7. **A flaky network turned a retry loop into two concurrent suite runs, and both became
   unreportable.** `sync.py`/`run.py` calls started failing with `EndpointConnectionError` to
   `ssm.us-east-1.amazonaws.com`, so a `for i in 1 2 3` loop fired `run.py --detach --label suite-03`
   more than once. Two defects made that destructive rather than merely wasteful, and both are now
   fixed in `runner/run.py`:

   * **A reused label truncates the running job's log and races it for the `.rc` file.** `--jobs`
     afterwards reported `suite-03  rc 1  0 lines`, which is not what happened to either job — an
     empty log beside a failing exit code reads as a fast, clean failure, and it was neither.
     `--detach` now asks the instance whether the label is free and exits 3 if it is not; `--force`
     overwrites and says so.
   * **`pytest --basetemp=DIR` REMOVES DIR at startup**, so the second run deleted the first run's
     `tmp_path` trees mid-flight. Scratch is now per label (`$TMPDIR/<label>`, exported into the
     detached job's environment), which makes the isolation and the disk bound the same mechanism.

   Both stale runs were terminated by killing the pytest child rather than the wrapper, so the
   wrapper recorded the honest `143` instead of leaving no `.rc` at all. `suite-03` and `suite-04`
   are void by termination; **`suite-05`** is the first clean run with the external inputs present.

## What happened after the runner was up (same session, later)

8. **`suite-05` — the first clean run — and all nine of its failures accounted for.**
   `26 failed / 21 errors` became **9 failed** once the external inputs were present, and every one
   resolved into a three-way story with no residue:

   * **1 real defect**, caught by the project's own guard: `test_account_id_choke_point` reported
     `runner/provision.py:265` resolving the account id with an inline
     `sts.get_caller_identity()`. That bypasses `lib/awsclients.account_id()`, which is the ONE
     place the value may be resolved because it registers it with `redact.register_account_id` —
     and `provision.py` puts the account id in an IAM policy, in a bucket name and in a plan it
     PRINTS under `--dry-run`. Fixed by routing through the factory; `27 passed`.
   * **2 real gate failures**, fixed below.
   * **6 write-guard arms that are not broken.** A decisive isolation experiment settled it:
     `test_write_guard_mutation.py` alone → **20 passed**; `test_write_guard.py` alone → **19
     passed**; both together → **39 passed**. The cause is that `conftest.py:316`'s
     `_foreign_live_run()` asks the **real process table** whether a live script from this
     repository is running, and the redaction-gate test spawns `check_redaction.py`. So the
     suite's result depends on how the suite was invoked. Worth recording as a deviation; it is
     not a protection failure.

9. **A second account-id leak, in code written this session, that no guard could have caught.**
   `provision.py` derived the runner bucket name from `sha256(account_id).hexdigest()[:16]`, with a
   docstring asserting that this "is not reversible to the twelve digits". Measured instead of
   argued: **2,874,794 candidates/sec on one core** with the exact expression the code used
   (CPython 3.12.12) over a keyspace of only 10^12 twelve-digit account ids — 4.0 days on one core,
   ~12 hours on eight, **~100 seconds** on one consumer GPU at a published hashcat rate of 10 GH/s.
   Expected number of *other* twelve-digit preimages for a given 64-bit digest: 10^12/2^64 =
   **5.4e-8**, so a hit is the account id itself. A truncated fast digest over a small keyspace is
   an **encoding**, not a hash.

   The real bucket name had already reached line 22 of *this file*, and the gate did not see it,
   because a bare bucket name carries no `s3://` scheme for the `s3-uri` pattern to fire on — **the
   gate cannot see what has no scheme.** Scrubbed here; the derivation is replaced by
   `secrets.token_hex(8)` plus discovery by **prefix ∧ own-account ∧ tags** (`list_buckets` returns
   only the caller's own buckets, which is what makes a prefix safe in a global namespace), tagging
   in the call immediately after `create_bucket` because an untagged bucket is invisible to the next
   run, and every "cannot tell whether it is ours" outcome — `NoSuchTagSet`, `AccessDenied`,
   `PermanentRedirect`, `NoSuchBucket` — resolving to `continue`, never to "yes". → **DEV-P4-25**.

   **Still to do:** the live bucket has not been migrated. The code is done; the running bucket
   still has the derived name.

10. **`results/FINDING-F3-10.md` written**, `OBSERVATIONS_COMPLETE` + `blocked_on`, and then
    materially strengthened by reading the register instead of trusting memory: the 739-vs-742
    question resolved (739 is the opening ` ```mermaid ` fence; node C is 742), **V13-05** identified
    as the candidate this case discharges, V13-05's own proposed amendment ("spans, not metrics")
    **refuted** — spans carry no score, so the instrument is neither — and §10.3 filed as a NEW
    candidate beside V13-12 rather than under it, because on the metric surface LOG_ONLY "reports
    nothing" while on the log surface it reports loudly and reports as an error; merging them would
    produce a candidate that contradicts itself.

11. **Redaction gate: 6 findings → 0.** Three were in the gitignored `runner/.state/runner.json`, so
    `.state` joined `SKIP_DIRS` — and because a skip is the strongest waiver in the gate (an `ALLOW`
    entry excuses one pattern on one line; a skip blinds it to a whole subtree), the justification is
    now checked rather than written: `lib/tests/test_redaction_gate_skips.py` asserts that **every**
    `SKIP_DIRS` entry is matched by a `.gitignore` rule, with `.git` the single exception because git
    never tracks its own directory. Two more were the false `runner/README.md:55` claim, corrected to
    describe the random suffix. The last two were ARN matches that first went in as narrow `ALLOW`
    anchors — which **put two fresh findings in the gate's own source**, exactly the trap the `ALLOW`
    comment block warns about. Backed out and replaced with two new kinds in the *derived* ARN
    excuse, since both are properties of ARN grammar rather than facts about two files: an **empty**
    account field (S3's grammar has no account segment) and the literal **`aws`** (an AWS-managed
    policy ARN, byte-identical in every account). Both are exact-equality tests, so neither widens
    the gate over a real 12-digit id.

12. **Case-verdict census, recomputed from disk rather than remembered:** **63 of 90
    register-named cases now have verdicts** (TRUE 37 / FALSE 15 / INCONCLUSIVE 10 / RECORDED 1),
    **27 remaining**. Two honest discrepancies to chase: `PREREGISTRATION.yaml` seals **93** cases
    while `claims/triage.csv` names **90**, and **F1-21 / F1-4** have verdicts but appear in no
    register row.

## Open, in the order I would pick it up

1. **`runner/run.py --tail suite-05`** — the first clean run with the external inputs present
   (started 05:44 UTC, ~9 min end to end, PID 33757/33758). It runs detached, so it finishes whether
   or not the laptop is open. Expect the 21 corpus-gate errors and the document-under-test failures
   to be gone; diagnose whatever remains of `lib/tests/test_write_guard*`,
   `lib/tests/test_write_guard_mutation.py` (control arm + M10/M13/M14/M15),
   `test_account_id_choke_point`, and `build_is_reproducible ran 1 assertion(s), expected >= 40`.
2. **FINDING-F3-10** in the `FINDING-F5-4A.md` house style, `OBSERVATIONS_COMPLETE` +
   `blocked_on` naming the second-day replicate, `cases: ["F3-10"]`.
3. **DEV-P4-23** (the two instrument defects, incl. the stale published 9-item list) and
   **DEV-P4-24** (truncation-defeats-the-mask) in `DEVIATIONS.md`; reconcile with DEV-P4-01, V13-05,
   V13-10 and F1-18's "not measurable" framing; candidates into `build_v13_candidates.py`, then
   regenerate `V13_CANDIDATES.md` (never edit it by hand).
4. Push per `feedback_stack_prs_by_concern` — the whole new `runner/` tree, the F3-10 join changes,
   the regenerated results, `lib/redact.py` and its tests. Via `/tmp/api_push.sh`; **never
   `git push`**, and the redaction gate must read a non-zero file count and exit 0 first.
5. Then the date-gated F3-11 `--compare` runs (2026-08-18, 2026-09-10) and the long τ-sweep move to
   the instance. F6 latency and publication stay on the laptop: one network position, and the
   instance holds no GitHub credential.

## State at the point the laptop was closed (2026-08-12, later still)

The publication gate is **green on the whole tree**: `461 file(s)`, `29,631,637 bytes read`,
`8762 reviewed exception(s) waived`, `PASSED`, `GATE-RC=0` — and the file count is the number that
matters as much as the verdict, because a gate that reads zero files also "passes"
(`feedback_zero_file_scan_is_error`). `claims/tests/test_redaction_gate.py` and the new
`lib/tests/test_redaction_gate_skips.py` are green together: **36 passed**.

Getting there cost three findings inside `check_redaction.py` itself, all the same mistake — writing
a literal identifier shape into the gate's own source, twice in `ALLOW` entries and once in a
comment describing the new `s3-uri` rule. All three are now excused **derivedly** or not present at
all, so `ALLOW` ends this session *smaller* than it started. The four findings the EC2 runner added
are excused by rules in `allowed()`, not by per-file waivers:

| finding | derived excuse | why it is a property of the notation, not of the file |
|---|---|---|
| `arn:…:s3:::bucket` | `absent` | S3's ARN grammar has no account segment at all — bucket names are global |
| `iam::aws:policy/…` | `aws-owned` | an AWS-managed policy, byte-identical in every account on earth |
| two `s3://…-<suffix>` URIs | `s3-uri` + `_PLACEHOLDER_AT` | the distinguishing part is *already* a placeholder; what remains is a prefix constant in tracked source |

`.state` is now a checked skip rather than a commented one: every `SKIP_DIRS` entry must be matched
by a `.gitignore` rule, `.git` being the sole exception because git never tracks its own directory.
Two mutation arms prove that check can fail.

**Next action is the staged push** (item 4 above), which was blocked only on the gate.

## The push, and what it found about the repo (2026-08-12, later still)

Three PRs are open, stacked:

| PR | head → base | what |
|---|---|---|
| **#6** | `feat/f5-redteam` → `main` | lands #3/#4/#5, which had merged but never propagated |
| **#7** | `feat/f3-10-score-label-join` → `feat/f5-redteam` | the F3-10 claim group + DEV-P4-23/-24 |
| **#8** | `feat/ec2-runner` → `feat/f3-10-score-label-join` | the runner + the gate changes it forced + DEV-P4-25/-26 |

Working tree and `feat/ec2-runner` now agree exactly: **522 blobs both sides, 0 changed, 0 unpushed,
0 on the branch but not local.**

### Three PRs were merged and none of their content was on `main`

The first thing the push needed was a diff against `main`, and it came back with **144 "new" files**
— including the whole F6, F7 and F5 families, which were reviewed and merged days ago. That is not a
plausible answer, so it was the diff that got checked next, not the files.

`#2..#5` were a stack, `main ← harness-guards ← f6-f7 ← f5-redteam ← register-and-docs`, merged in
ascending PR order inside **23 seconds**:

| PR | head | base | merged |
|---|---|---|---|
| #2 | `feat/harness-guards` | `main` | 06:52:32Z |
| #3 | `feat/f6-f7-results` | `feat/harness-guards` | 06:52:41Z |
| #4 | `feat/f5-redteam` | `feat/f6-f7-results` | 06:52:47Z |
| #5 | `feat/register-and-docs` | `feat/f5-redteam` | 06:52:55Z |

#2 put `harness-guards` into `main` **first**, and only nine seconds later did #3 put `f6-f7` into
`harness-guards`. Every parent was merged into *its* parent before receiving its child, so the stack
collapsed downward into itself and never propagated up. `main` @ `a854d650` served **378** blobs; the
tip `feat/f5-redteam` @ `3738e9b2` served **497**. Every merge succeeded and every PR says "Merged".

A stack has to be merged **top-down**, or each PR re-parented onto `main` as the one below it lands.
The detection is the same either way: diff the working tree against what the branch *serves*, never
against what the PR list claims. `feedback_merged_pr_is_not_landed` records it.

### The pusher had to be rewritten, and the reason was measured

`/tmp/api_push.sh`'s blob loop uses `gh api -X POST --input <file>`. On the 17-file PR #7 push it
returned `HTTP 400 "We received a malformed request from your client"` on **9 of 17** blobs and
`net/http: TLS handshake timeout` on a 10th — **in no size order**: a 98 KB source file landed while a
22 KB one did not, and that same 22 KB file landed byte-identical on the very next attempt. So a
retry version (`api_push2.sh`) was written. It made things worse: the timeouts became persistent and
it gave up after six attempts.

Retrying harder was the wrong move, so the next step was to find out what was actually broken. In the
same shell, the same minute:

* `gh api rate_limit` → `4969/5000` remaining. Not a rate limit.
* `curl https://api.github.com/rate_limit` → HTTP 200, TLS handshake 0.07 s, total 0.09 s. Not the
  network.
* `curl -X POST -H "Authorization: bearer $(gh auth token)" --data-binary @payload.json` → uploaded
  all three previously-failing blobs, **including the 1.2 MB `results/phase1/F3-10.json`**, SHAs
  matching `git hash-object` on the first attempt each. Not the payload and not the API.

The fault is in gh's HTTP client at this body size. `/tmp/api_push3.sh` uses curl for every call and
keeps `gh auth token` only for the credential; both pushes then went through with **0 mismatches** and
**0 files not served with the expected sha**. The retry loop is kept, and it is only safe because the
SHA comparison is what decides success — the API can answer 201 for bytes that were never sent
(`feedback_verify_uploaded_blob_sha`, now updated with this).

Two details worth keeping: `curl -f` is not used, because on a 4xx it throws away the body and the
body is where GitHub names the field it objected to; and every payload goes to a **file**, never argv,
because a 1.6 MB base64 string on a command line dies as "Argument list too long" partway through a
list, which looks exactly like a network error.
