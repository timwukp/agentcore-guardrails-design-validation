# FUTURE-WORK plan — the open items, grouped by what unblocks them

Draft for review, 2026-09-28. This plans the work and does none of it. It is in the repo so it can be cited; the grouping
still awaits review.

Scope: 48 numbered items. 8 carry a closing mark in their own text (1, 24, 33, 34, 36, 40, 42, 43),
which leaves **40 open**. A mark was matched as the first `**CLOSED` / `**RESOLVED` / `**Closed by` in
the item's body (`session-logs/fw-status-20260928.txt`). Item 2's "Blocker RESOLVED" covers only its
blocker, so item 2 is counted open.

## Group A — needs AWS calls, so each needs your go-ahead (9)

| item | what it needs | cost | note |
|---:|---|---|---|
| 10 | F10-1 measurement, design in `f10_billing/F10-1-DESIGN.md` | < $0.10 | 3 authorizations listed there |
| 45 | decide whether this account uses cost-allocation tags | $0 | **F10-1's design activates one tag key, so approving it answers 45** |
| 44 | delete `vol-0aaa5827f1d9dd730` | saves ~$3.20/mo | step 5 of your ordered list |
| 27 | a new F8-5 STANDARD-tier observation at 1000 chars | ~$0 | a new observation of a sealed case, so the item itself says it needs you |
| 3 | re-run F5-8 day-2 clean, or diagnose the empty-reason failure | ~$0.10 | the old output is only in S3, and the instance is gone |
| 13 | F3-11 `--compare`, owed 2026-08-18 and 2026-09-10 | ~$0 | **both dates have passed unrun.** A run now is a +48 d compare, a named deviation, not the sealed +7 d/+30 d |
| 2 | day-2 data for the 12 amended cases | ~$1 | via `tools/day2_replicate.py` only |
| 14 | a recurring canary of a few high-value cases | ~$1/run | design first; running it on a schedule is a standing cost |
| 47 | explain two charges from 2026-08-13 | $0 | if the only answer needs enabling something in the account, write it into `DEVIATIONS.md` instead |

## Group B — local code, no AWS, can be done PR by PR (14)

Order is by how much each one protects a published number:

1. **37**: drive the expected red set to zero, not to "documented as four".
2. **23**: `lib.oracle` refuses a trial whose call carries a transient error, and the boolean-over-error
   population is enumerated. Item 27 depends on this.
3. **48**: a `cdk diff` wrapper that passes `--strict` and fails on "Omitted … changes".
4. **39**: compare media hashes against the previous release, with a deliberate re-pin.
5. **38**: `media.json` records the ffmpeg version, the Playwright revision and the voice/engine pair.
6. **46**: audit every usage-type reader for the name-is-a-key assumption, and list them by name.
7. **25**: add an `observed_utc_date` field to F8-5 and F8-8 (a new field, not a renamed run id).
8. **22**: the replication gate states its scope in its own output.
9. **26**: F10-3's checkpoint `meta.qualifiers` records the per-block qualifiers.
10. **15**: `f5_redteam/tests/test_route_credential_reachability.py`.
11. **29(c)**: a guard that refuses to delete a conflicted `incoming/` tree.
12. **31**: the gate's runtime, stated once and measured.
13. **17**: stale test floors. The runner is gone, so the check becomes "the same files collect here".
14. **16**: `sync.py pull`. Verification only, and `pull` itself was declined twice, so this is last.

## Group C — writing, in the whitepaper and the guardrails document (15)

4, 5, 6, 7, 8, 9, 11, 12, 18, 19, 20, 28, 30, 32, 35. One chapter pass can close several at once:

- **methods chapter**: 4 (threats to validity), 19 (repeatability vocabulary), 20 (verdict taxonomy),
  32 (decisiveness), 6 (measured propositions vs reasoned prescriptions);
- **limitations**: 5 (no conjunction), 11 (no fault injection), 7 (evidence strength per chapter);
- **Chapter 2**: 8 and 28 (OWASP/GENSEC cross-map by TID only), gated on 30's open question of whether
  the OWASP Agentic 2026 list supersedes T1–T17;
- **citation hygiene**: 12 (F5-3b never cited), 18 (F2-3/F2-4 records), 9 (chart conventions);
- **35**: its only remainder is a checklist file.

## Group D — only a person can close these (2)

- **41**: the viewer-path half. Someone with the second factor loads the live page once and pastes the
  headers, labelled with the release stamp. The CSP half was read off the deployed policy on 2026-09-28
  (`session-logs/deployed-headers-20260928.log`, rc 0).
- **21**: a DOI deposit (Zenodo or similar). Publishing outward is your call.

## Suggested order

1. Group A's cheap decisions together: approving 10 answers 45, and 44 is already on your list.
2. Group B items 37, then 23, then 48, one PR each, because every later measurement reads through them.
3. Group C as one whitepaper amendment pass, after 23 so the prose cites settled verdicts.
