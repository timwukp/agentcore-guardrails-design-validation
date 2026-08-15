# Reconnect note — updated 2026-08-15

Read this first if the session dropped. It is the shortest path back to the live state.

## ⇢ RESUME HERE (2026-08-15): **the project has entered its WHITEPAPER phase; measurement and both decks are finished and the two user decisions are MADE (see below)**

Written because the laptop may be powered off at any moment.

**⚠ Two things in this banner are now stale further down the file: the runner is RUNNING, not
stopped (~$0.58/day — `runner/teardown.py` for $0), and PR #29 is MERGED (main `cd5f802132ab`,
689 blobs, verified blob-by-blob 2026-08-15).**

### The whitepaper phase — three new files, read them before drafting anything

The user asked for an AWS-whitepaper-style publication in which every viewpoint is validated, with
method and results in appendices, rigorous charts, and an objective list of the study's own
deficiencies. Research and design are done; drafting has not started.

- **`results/RESEARCH-whitepaper-conventions-20260815.md`** — what is actually *verified* about AWS
  whitepaper convention and the OWASP/GENSEC cross-map. 16 primary sources, 25 claims through
  3-vote adversarial panels, **13 survived / 12 killed**. Its headline is a negative result: AWS's
  **identifier and versioning** conventions are real and machine-verifiable, its **prose-block
  templates are not** (four "AWS template" claims refuted 0-3). Also records the four wrong
  citation anchors that must be re-pointed before publication.
- **`WHITEPAPER-DESIGN.md`** — the chapter structure, the `ACG-nn-BPnn` control-ID scheme, the
  two-tier claim policy (deterministic → scoped *prevents*; probabilistic → measured reduction +
  residual risk), chapter ordering by measured evidence strength, and the 8-figure list. Every
  decision tagged **[C]** confirmed / **[I]** our inference / **[U]** unsourced.
- **`results/RESEARCH-evidence-presentation-20260815.md`** — pass 2, landed 2026-08-15.
  `wf_3762680e-846`, 108 agents, 26 primary sources, **129 claims extracted, 25 verified, 23 survived /
  2 killed**. Establishes the ACM and USENIX badge vocabularies, Registered Reports, the four-part
  validity structure **and the trap in citing it** (that Essential is human-participant-scoped;
  `Benchmarking.md` requires only construct validity), negative-result protection, and effect-sizes-with-
  intervals. Its two sharpest findings for us: our second-day runs are **repeatability, not
  reproduction** — ACM reserves both *Reproduced* and *Replicated* for non-authors, so **no independent
  party has re-run anything here** — and our `TRUE/FALSE/INCONCLUSIVE/RECORDED` taxonomy has **no located
  precedent** and must be defined, not cited.
- **`FUTURE-WORK.md`** — the deficiency list, **21 items** in 5 tiers, each with derived evidence.
  Item numbers are stable identifiers, not positions. **Tier-1 item 1 is CLOSED** (both prevention
  overclaims rewritten in both editions, Appendix D correction item 23). Still open in Tier 1: the 12
  single-day amendments; F5-8's undiagnosed 2-of-3-session day-2 fault; and new **item 19**, that this
  study says "reproduction" where the accepted vocabulary says "repeatability".

**Blocked on one thing only, and it is narrower than it was:** `wf_3762680e-846` has landed, so
**Chapter 12 is unblocked**. **Appendix D is not** — the pass returned only two citable figure anchors
(a distribution-form mapping and a truncated-bar antipattern) and left censoring, binomial intervals at
zero successes, and colour-blind-safe three-state encoding **unadjudicated rather than unsearched**:
eight primary sources were fetched and never voted on, including **WCAG 2.2 Use of Color**, which is the
right citation for figure 6. Next step is a **scoped verification of those eight URLs**, listed in
`RESEARCH-evidence-presentation-20260815.md` §5 — a verification, not a search. Everything else is
draftable now.

### Measurement: done. 91 of 92 published, 1 outstanding and it is a decision, not a run

Regenerate rather than trust; the numbers below were read from the command, not remembered:

```
.venv-oracle/bin/python census.py            # read-only;  --write rewrites results/_progress_census.txt
```

**93 sealed cases → 92 verdict-eligible** (minus F9-1, untestable by its own oracle) → **91
published**, **TRUE 46 / FALSE 23 / INCONCLUSIVE 20 / RECORDED 2**. Every family reads `complete`
except F10 (2/3). Of the 91, **90 are publishable**: F5-3b is TRUE but its
`every_boundary_transition_was_observed_to_settle` guard failed, so it is **non-publishable and must
not be cited as confirmation**.

The single outstanding case, **F10-1**, is not a missing run. The `ce:GetCostAndUsage` grant is
removable and I declined to remove it unilaterally; that is recorded in
`results/CENSUS-NOT-MEASURED.md`. It needs a decision, not an instrument.

### The document exists in two languages and both are published

| file | bytes | sha256 |
|:---|--:|:---|
| `agentcore_guardrails_best_practices_v1.4.md` | 161,264 | `0ce7608fbf39f17b…` |
| `agentcore_guardrails_best_practices_v1.4.zh-TW.md` | 154,801 | `bcfa943a57450f74…` |

PRs #24 (EN v1.4) and #25 (zh-TW) are merged; `main` is **`95b03ea91c9a`**, 678 blobs, tree-verified
after the merge (`feedback_merged_pr_is_not_landed`). Only v1.4 and v1.2 are kept — `只保留1.4`,
`1.2要保留`. `~/Downloads/agentcore_guardrails_best_practices_v1.2.md` is the sealed
`document_under_test` (`PREREGISTRATION.yaml:58-60`) and **must never be deleted or modified**.

### The bilingual PPTX decks are DONE — 61 slides each, rebuild with one command

Request: *做成PPTX, one for english version, one for chinese version* — one deck per language, from
v1.4. Both exist and both are published. **They are generated, never hand-edited**: edit the deck
plan and rebuild, or the next build silently discards the edit.

```
python3 tools/build_pptx.py                  # SYSTEM python3 — python-pptx is not in .venv-oracle
                                             # exit 1 if any slide overflows; 0 means it all fits
```

| file | bytes | sha256 | slides |
|:---|--:|:---|--:|
| `agentcore_guardrails_best_practices_v1.4.pptx` | 177,474 | `7b3cef94e216a5d7…` | 61 |
| `agentcore_guardrails_best_practices_v1.4.zh-TW.pptx` | 187,014 | `74a6e561ad30254b…` | 61 |

Both are also copied to `~/Downloads/` (hash-verified identical). The slide plan is **one** plan in
two languages — every string is a `t(en, zh)` pair — so the two decks have the same 61 slides in the
same order and a sentence cannot be updated in one language and forgotten in the other.

- `render.py` — the layout engine. Slide kinds `title_slide` / `divider` / `bullets` / `table` /
  `kpi` / `twocol` / `diagram`. Three disciplines are load-bearing: it **measures then fits** (picks
  the largest font that still fits), it **writes east-asian typefaces**, and anything that still
  cannot be made to fit **appends to `Deck.warnings`**, which the CLI prints and turns into exit 1 —
  a slide that quietly runs off the bottom otherwise looks deliberate.
- `mdsource.py` — pulls all 21 tables out of both files so slides *quote* the document instead of
  retyping it. Tables are addressed by **index**; `Source.assert_parallel()` raises if the two files'
  table counts or shapes diverge. `abridge(text, budget)` shortens a long cell **at a sentence
  boundary** (`.`/`。`, CJK measured double-width) so every word on a slide is a word the document
  wrote, and `rebalance()` closes a `**`/`` ` `` span the cut left open.
- `diagrams.py` — the 11 mermaid figures as **native PowerPoint shapes** (closed loop §2, hop
  lifecycle §2.1, billing asymmetry §3.2, tier decision §3.4, LOG_ONLY precedence §4.1, containment
  boundary §4.4, network containment §4.5.5, streaming §5.1, trace tree §6.3, threshold tuning §7.1,
  reference architecture §9). Editable in PowerPoint, no render dependency.
- `deck.py` + `deck_after.py` — the plan itself, split at the document's own BEFORE/DURING → AFTER
  boundary. `deck.build(lang, src, path)` returns `(slide_count, warnings)`.
- `tools/tests/test_deckgen.py` — 15 tests, 7 of which `importorskip` python-pptx so the oracle venv
  stays green. Three pin defects that each produced a *plausible slide* rather than an error: a code
  span nested in bold printing its own backticks, an abridged cell leaving `**` unclosed, and
  `<a:cs>` written before `<a:ea>` (out of schema order → PowerPoint offers to repair the file).

**Verified on the built decks, not assumed:** 0 shapes outside the slide, 0 markup leaks, every
`a:rPr` child in schema order (`latin → ea → cs`, 1,571 runs EN / 1,575 ZH), `PingFang TC` on every
ZH run, complete `[Content_Types].xml`, no dangling relationship, no duplicate shape id.
**PowerPoint could not be used to open them** — this machine has no display session, so
`osascript`-driven export timed out and `screencapture` fails; the checks above are structural, and
a human should still open both once.

**`check_redaction.py` now reads inside OOXML packages.** `SCAN_EXT` had no `.pptx`, so the gate
would have skipped the deliverable and still printed PASSED. It unzips `.pptx`/`.docx`/`.xlsx` and
scans every UTF-8 part, prints which packages it opened, and treats a package with no readable part
as unreadable rather than clean. Current run: **622 files, 2 packages unzipped, 40,028,666 bytes,
exit 0**. Read the exit code directly — never pipe it to `tail`.

**Four environment facts that each cost time to learn — do not re-derive:**

- **python-pptx 1.0.2 lives on the system homebrew python3 only** (`/opt/homebrew/bin/python3`). It
  is **not** in `.venv-oracle`. Build with `python3`; the venv raises `ModuleNotFoundError`.
- **The package is `tools/deckgen/`, not `tools/pptx/`.** The first name shadowed the installed
  `pptx` package and every import failed. Import as `from deckgen.mdsource import Source` with
  `sys.path.insert(0, 'tools')`.
- **No `mmdc` and no LibreOffice**, so mermaid cannot be rasterised. PowerPoint *is* installed.
  Native shapes were chosen deliberately: editable in PowerPoint, no render dependency.
- **python-pptx writes only `<a:latin>`.** A run containing Chinese needs `<a:ea>` (and `<a:cs>`) or
  PowerPoint substitutes per glyph. `render.Deck._style_run` writes all three. Fonts actually
  installed here: Arial, Helvetica Neue, PingFang TC. **Microsoft JhengHei and Consolas are
  absent** — hence latin `Arial`, east-asian `PingFang TC`, mono `Courier New`.

**Table index map** (same index = same table in both languages, verified). Ten tables have cells too
long to quote whole — **#4** (five bypass routes, 4,310-char cell), **#5**, **#9**, **#11**, **#13**,
**#15**, **#16**, **#17**, **#19**, **#20**. They are passed a `budget=` and abridged at a sentence
boundary; no cell is retyped and no bilingual override table was needed, which is why there is no
`overrides` mechanism to maintain. Table #4 and table #18 are additionally **split across two
slides** with `keep_rows`. The rest quote verbatim. Verdict citations are stripped by
`strip_citations` (content-driven — it keys on case ids, so it works on both languages) and replaced
by one footnote per slide pointing back at the document.

### The two user decisions — BOTH MADE 2026-08-15; one is done, one is queued

1. **`reproduction_before_amendment` inconsistency → the user chose the strict reading** ("從嚴"):
   the two-UTC-day bar binds every amendment, so the 12 cases amended on a single calendar day's
   data — **F6-1…F6-5, F6-8, F4-6, F3-4, F8-4, F8-5, F1-14, F10-3** — each owe a day-2
   replication. The user explicitly queued this as a to-do rather than an immediate run ("可以將這
   放在to-list"), so it sits in the list below and **does not block anything published**: until a
   case's day-2 lands, its v1.4 amendment stands on one day's data and should be cited with that
   caveat. If any day-2 *contradicts* day 1, that is a finding, not a fix-up — record it and bring
   it back to the user.
2. **Sealed `claims/triage.csv:147` (`POST /inference` vs the measured `/inference/v1/messages`) →
   annotated, not edited.** DONE: `results/ERRATA.md` entry **E-1** carries the correction, the
   evidence pointers and the reasoning; the csv stays byte-identical and its seal stands.

### Still owed, mechanically

- **Day-2 replications — one runner session covers all of it** (start with `runner/provision.py`):
  - **F5-8** (window opened 2026-08-15 UTC — it is the gate for swapping §4.4 route #3's
    Accelerator/NDA citation for public evidence), **F4-6**, **F2-1** — owed already.
  - **The 12 single-day-amended cases** per user decision 1 above: F6-1…F6-5, F6-8, F3-4, F8-4,
    F8-5, F1-14, F10-3 (F4-6 is already in the line above). Queued, per the user, not urgent.
- `f5_redteam/tests/test_route_credential_reachability.py` — F5-8 has no test file.
- `F3-11 --compare` on **2026-08-18** and **2026-09-10**.
- `runner/sync.py pull` exits 0 after an `EndpointConnectionError`. Deferred deliberately as its own
  change; do not fold it into unrelated work.

### The runner is STOPPED, on purpose

`i-0f90ac6377bba523b` (`t3.small`, us-east-1) was stopped 2026-08-15 after this note was written.
Nothing was running on it: every job in `runner/run.py --jobs` carries an exit code, the one `LOST?`
row is a stale 2026-08-12 job. A stopped `t3.small` bills only its 40 GB volume (~$0.11/day).
Restart with `runner/provision.py` (it knows the instance id). The one thing that needs it is the
queued day-2 replication batch above (F5-8/F4-6/F2-1 plus the 12 from user decision 1 — LIVE AWS
work); everything else (the decks, the publication steps) is laptop-only by design — python-pptx is on the system python3, and the instance deliberately holds no
GitHub credential.

## HISTORICAL (2026-08-13): **71 of 92 published; F5 is the whole remaining bulk**

Do not read the case counts out of this file. Regenerate them:

```
.venv-oracle/bin/python census.py --write     # rewrites results/_progress_census.txt
```

Every number in that file is derived from `claims/triage_rules.py` + what is on disk under
`results/phase1/`; nothing in it is remembered, which is why it is the artifact and this section is
only a pointer. As of this writing it reads **71 published / 21 outstanding** of **92
verdict-eligible** (93 registered minus F9-1, the one case untestable by its own sealed oracle), and
**TRUE 41 / FALSE 18 / INCONCLUSIVE 11 / RECORDED 1**. `RECORDED` is a verdict value, not an
exemption: that case (F5-4a) has a file like every other.

| family | state |
|:---|:---|
| **F0, F2, F3, F4, F6, F7** | **complete** — 1/1, 5/5, 11/11, 6/6, 9/9, 7/7 |
| F1 | 20/28 — outstanding F1-6, F1-15, F1-19, F1-24…F1-28 |
| **F5** | **4/12** — outstanding F5-2, F5-3a, F5-3b, F5-4b, F5-5, F5-7b, F5-8, F5-9 |
| F8 | 7/8 — F8-1 |
| F9 | 0/2 — F9-2, F9-3 (F9-1 is untestable, not outstanding) |
| F10 | 1/3 — F10-1, F10-3 |

**Do F5 next.** It is 8 of the 21 outstanding cases and the only family with a large block left; the
rest are singletons.

**F5-7a and F0-1 were not work — they were bookkeeping.** Both were measured, written up and
guarded, and neither had a `results/phase1/` record, so the census counted them outstanding while
their finding documents said they were done (DEV-P4-33). F0-1 was found by
`test_a_written_up_case_has_a_verdict_record`, the guard written after F5-7a, on its first run. That
guard now exists, so this specific way of being wrong is closed — but the general shape is worth
carrying: **a family line reading `F5 4/12` is indistinguishable from honest remaining work.** If a
case looks stuck, check whether it is actually finished before planning a run for it.

### Two things below this line are now WITHDRAWN — do not resume from them

- **The τ-sweep is dead.** The section below plans F2-2/F2-3/F2-4 as a τ-sweep because "no numeric
  guardrail score is published anywhere" (DEV-P4-01). **DEV-P4-27 refuted that**: the score is in the
  *application* logs, at `body.policy.guardrailFindings.<policy>.contentFilter[].score`, as a
  **string**. F2-2/F2-3/F2-4 and F1-18 were measured directly against it and are sealed. The
  original absence probes were not sloppy — they surveyed the surfaces the *document* named, and the
  value was somewhere the document never mentions (`feedback_surfaces_a_doc_names`).
- **"Do F7 next, not F2-2" is spent.** F7 is 7/7.

### Owed write-ups, tracked because a verdict on disk is not a finding

- **FINDING docs owed** for F1-18, F2-2, F2-3, F2-4 (one doc, DEV-P4-27's surface is the story);
  for §3.1's determinism contrast (F2-5 FALSE beside F2-1 TRUE — neither surface varied at all);
  and for F4-6's pre-registered refutation. Format reference: `results/FINDING-F3-10.md`.
- **Day-2 replications owed**: F4-6, F2-1. *(F5-7a's is done — `r20260810T002001Z`, 75 fields, 0
  disagreements, `results/f5_7a_replication.json`; it was listed here in error.)*
- **F0-1 rests on one dated observation** (2026-08-09) of a property that can change — link
  liveness. A re-check must write a **second dated file**, not overwrite
  `results/FINDING-F0-1-references.json`: that artifact is the only observation of that date and
  `claims/tests/test_finding_numbers.py` pins the document's "24/24" against it.
- `FINDING-F3-10.md` is `OBSERVATIONS_COMPLETE`, blocked on a UTC day after 2026-08-12.
  `V13-05` is `BLOCKED_ON_REPLICATION`. `F3-11` needs `--compare` on **2026-08-18** and
  **2026-09-10**.

### The repo state that matters more than any of the above

**`main` is missing 42 files, including the entire `runner/` tree.** PRs #6–#11 were merged in
ascending number order, which for a stack is *top-down*: #6 put `feat/f5-redteam` into `main` first,
then #7–#11 merged upward into branches that `main` had already stopped tracking. Nothing
propagated (`feedback_merged_pr_is_not_landed`, now the third occurrence).

**PR #12** (`feat/write-guard-column-width` → `main`) lands all of it in one merge — 539 blobs
verified byte-for-byte against the trees API, `MERGEABLE`/`CLEAN`. **Push further work onto that same
branch so #12 updates in place. Do not open a new stack** — restacking is what caused this.

```
/tmp/api_push3.sh feat/write-guard-column-width feat/write-guard-column-width <msg-file> <file-list>
```

### There is an EC2 runner, and it is the reason the suites are green on two kernels

`t3.small` in us-east-1, `runner/provision.py` → `runner/sync.py push` → `runner/run.py --detach`.
It exists because five test arms need `setsid` / GNU `df --output=avail` and one needs a `ps` that
truncates — all Linux-only. The laptop suite skips those arms and the runner runs them, so the two
pass counts differ by design and neither is quoted here — regenerate them. Every skip states its
reason and three state a measured number. Two things stay on the laptop by design: **F6 latency** (one network position) and **every
publication** (the instance holds no GitHub credential).

Its disk is the hazard — see **DEV-P4-31**. One suite's `--basetemp` scratch is a measured 10.6 GB,
`run.py` refuses a launch below a **12 GB** floor, and pruning also reclaims a job killed without an
rc file. `--jobs` says `LOST?` rather than inferring `RUNNING`.

## HISTORICAL (2026-08-11, late): F4 full + F2-1 landed; F7 was then the critical path

Kept for the reasoning, not the plan. Its case counts ("44 of 93") and its τ-sweep design are both
superseded above — F7 is 7/7 and DEV-P4-27 found the score. What survives intact is the span
inventory, the request-id join, and the F7-4 correction, all of which were re-measured.

- **F4 full run: DONE at n=120/cell.** F4-1..F4-5 TRUE, F4-6 FALSE (the pre-registered
  refutation). Every cell 120/120 usable, 0 failed, 0 unclassified.
- **F2-1: DONE and TRUE.** `f2_determinism/02_policy_determinism.py`, 3 arms under ONE
  configuration (engine ENFORCE / baseline LOG_ONLY / narrow permit ACTIVE):
  `boundary_below` amount=499.9 → 300/300 **allowed**; `boundary_at` amount=500.0 → 300/300
  **policy_denied**; `far_outside` amount=4242.0 → 30/30 denied. **630/630 usable, 0 flips, 0
  failures**, one-sided flip-rate ceiling **0.00474**. All four subject guards passed, so the
  constancy is not the constancy of an inert policy. Testbed restored, 15/15 blocking checks
  PASS.
  - New config-surface fact from its unscored probe: **four-fractional-digit request literals DO
    bind** (`amount=499.9999` → allowed). The scored arms use one digit anyway, because that was
    unmeasured when the arms were chosen and a wrong guess would have cost the run.
  - Read alongside F2-5 (FALSE, guardrail ceiling 0.00994), **the document's determinism
    contrast in §3.1 did not appear**: neither surface produced any observable variation. That is
    v1.3 material and needs its own finding doc before the amendment pass.
- **DEV-P4-01 registered — no numeric guardrail score is published anywhere.**
  `f7_observability/00_span_shape_probe.py` (read-only, scores nothing) read 60 real spans for
  our gateway from `aws/spans`: **58 distinct attribute paths, zero matches for
  `score`/`confidence`/`threshold`/`guardrail`**, and the plan's predicted
  `aws.agentcore.policy.guardrails.<category>.scores` is **ABSENT**. Full inventory:
  `results/span_shape_probe.json`.
  - **Consequence for ordering: F7 is upstream of F2-2/F2-3/F2-4 and of F3-10.** All four were
    scheduled before F7 on the assumption the score came from the response; it comes from
    telemetry or nowhere, and F7-5 is what makes any span-derived reading non-vacuous.
  - F2-2/F2-3/F2-4 move to a **τ-sweep** instrument (mixed decisions at fixed τ over a fixed
    input prove ≥2 distinct latent scores without observing one — conservative, can only
    under-report). F2-3's strata become τ-bands, which can only *hide* a mixed stratum, so a
    TRUE there must be reported as weakened **in the verdict**, not a footnote.
  - **F1-18 is not rescued and must not be.** It claims a six-value numeric lattice no surface
    exposes → v1.3 amendment material, not a manufactured verdict.
  - What the spans DO carry, per request: `aws.request.id`,
    `aws.agentcore.policy.authorization_decision`, `authorization_reason`,
    `determining_policies[]`, `log_only_matched_policies[]`,
    `log_only_decision_flipping_policies[]`, `gateway.policy.mode`, `jsonrpc.error.code`,
    `tool.name`, and **`latency_ms` / `overhead_latency_ms` / `execute_tool_latency_ms`**.
  - F3-10's FALSE direction is now indicated (decision is joinable per request; the score §7.1
    needs has no left-hand side) but is **not scored** — it gets its own script, including the
    metrics-only arm its sealed method requires.
  - F6 gains a better instrument: server-side per-request latency attributes, which exclude the
    client's own network variance from the policy-overhead number. Register that separately when
    F6 is written.
  - **F7-4: `AgentCore.Policy.AuthorizeAction` spans DO exist** — 246 of them over 48 h, paired
    1:1 with `AgentCore.Gateway.InvokeTool`, and **27 were already inside the probe's original
    60-row sample**. An earlier draft of this file claimed the opposite. That claim was written
    in prose from the *one* sample span the probe serialises into `sample_span_leaves` (an
    InvokeTool row); the probe tallies leaf **paths** and never tallied span `name` at all, so
    nothing checked it — `feedback_prose_is_not_verified` exactly. Re-measured at three
    window/limit settings (120 min × 60, 120 min × 500, 48 h × 500): AuthorizeAction present in
    all three. **The document is right here and F7-4 has no amendment material.** The full span
    inventory is 5 operations: `AgentCore.Gateway.InvokeTool`,
    `AgentCore.Gateway.InvokeTool.grxecho___echo`, `AgentCore.Policy.AuthorizeAction`,
    `AgentCore.Gateway.Initialize`, `AgentCore.Gateway.NotificationsInitialized`.
  - **The request-id join is real and measured: 242 of 250 span `attributes.aws.request.id`
    values (96.8%) match a client-observed `x-amzn-requestid` recorded in an F4/F2-1 checkpoint.**
    One request id carries two spans (InvokeTool + AuthorizeAction), which is the join F7-4's
    sealed method asks for and the left-hand side F3-10 needs. The 8 non-joining ids are the
    `Initialize` / `NotificationsInitialized` spans, whose request ids we never recorded as
    trials. This also gives F7-5 a **specific** absent-arm marker: not "no spans in a window"
    but "no span carries any of *these* request ids".
- Gates re-run after all of the above: `verify_prereg.py` **rc=0, seal `a2136a9d…` intact, 189
  assertions**; `lib/tests/` **672 passed, 2 skipped** (this includes the static
  module-name-collision test that both new by-path loaders had to satisfy).
- Stale checkpoints: the F2-1 n=3 smoke is quarantined under
  `results/checkpoints/_stale_20260811_f2smoke/`. Never resume from a quarantine directory.

## HISTORICAL (2026-08-11, evening): F4 smoke is GREEN (rc=0); next is the full n=120 run

The section below this one is HISTORICAL — F4 was finished later the same day. Current state:

- `f4_modes/01_truth_table.py` runs end to end: `--n 3` smoke exits 0, all 8 cells complete,
  testbed restores cleanly, verdicts F4-1..F4-5 TRUE and F4-6 FALSE (the pre-registered
  expected refutation: denials arrive as HTTP 200 + JSON-RPC error -32002, not the documented
  403 + policy id). n=3 does not clear the amendment bar; the full run needs n=120/cell.
- Three measured fixes landed on the way (each carries a MEASURED comment at the site):
  1. The narrow Cedar permit needs `action ==` scoping, a `has` guard, and
     `.lessThan(decimal(...))` — an unscoped `context.input.*` condition must type-check
     against every action in the schema (see `build_policies`).
  2. The guardrail policy needs the same `action ==` scope AT RUNTIME: unscoped, it denies
     everything with "guardrail policy could not be evaluated - missing an attribute", even
     though `IGNORE_ALL_FINDINGS` let it create (see the guardrail statement comment).
  3. `amount` must be sent as `100.0`, not `100` — the engine refuses to bind an integral
     JSON literal to Cedar `decimal` ("Parameter format error"), and both narrow cells then
     deny for the wrong reason (see `BENIGN_ARGS` comment).
- `lib/mcp.classify` now recognises the JSON-RPC -32002 denial shape as `policy_denied`
  (both wire shapes kept; see the MEASURED comment in the error branch).
- Stale checkpoints from the two defective smokes are quarantined under
  `results/checkpoints/_stale_20260811_*` — do not resume from them; the current
  `F4-cells__*.json` checkpoints (post-fix) are the live ones.
- Next: Phase 4 — F2 determinism (4 arms × n=300) + gateway-side F3 + F3-10 + F7.

## HISTORICAL (2026-08-11, morning): F4 is half-written and does not run yet

Task #8 (Phase 3). F1-3 is complete and READY_TO_AMEND; **F4 is mid-write**.

`f4_modes/01_truth_table.py` — **279 lines, syntax-valid, NOT runnable.** It currently holds the
module docstring (the full six-case design), imports, constants, and the classification helpers. Not
yet written: `_f4_6_row`, the arm runners, the two axis switchers, `main()`, teardown.

**One known defect to fix first.** `_classify_f4_6` ends with a placeholder line:

```python
return False, "", detail       # the real decision needs the policy ids; see `_f4_6_row`
```

`_f4_6_row` does not exist. As it stands the function returns "not adverse" for **every** denial,
which would make F4-6 report agreement with the document by construction — the exact
`feedback_vacuous_test_check` shape. Either finish `_f4_6_row` (it needs the created policy ids, so
it has to be a closure or take them as an argument) or fold the classification into the arm runner.
**Do not run F4-6 until this is closed.**

Order of work after that: `--dry-run` (all six banners) → `--n 3` smoke → full n=120 × 6 cells →
`f4_modes/tests/{conftest.py,test_f4_offline_mutations.py}` mirroring `f1_config/tests/` exactly →
then `f1_config/04_policy_grammar.py` and `05_live_boundaries.py` → then wire both test dirs into
`verify_phase0.sh`'s `run_tests()` and raise `compile_all()`'s floor → then update `V13_CANDIDATES.md`.

### Design decisions already closed — do not re-derive

- **Six cases in ONE script.** All six read the same 2×2 and differ only in which cell they
  interrogate. Six files would mean six mode switches on one shared gateway and six restore paths.
- **`billable=False`** in every dry-run banner: F4 sends no `ApplyGuardrail` and no
  `InvokeGuardrailChecks`, so text units are 0. Billable surface is Lambda invocations only.
- **F4-6's `thresholds == (403.0,)` is decorative to its kind.** `oracle._decide`'s `ZERO_EVENTS`
  branch reads only `obs.adverse` and `n` and never consults `thresholds`, so the script must do the
  403/policy-id classification itself. `limits_by_reference` is **empty for all six** — verified
  against the sealed bindings 2026-08-11, correcting an earlier note that claimed F4-6 carried
  `("403",)` there. The banner prints `thresholds: (403.0,)` for F4-6 and
  `(none — kind is not thresholded)` for the other five; the `limits by REFERENCE` line never prints.
- **Only F4-1 and F4-3 are mandatory-mutation cases**, so only they must set `o.mutation_inverted`
  explicitly. `evaluate()` overrides a TRUE verdict to INCONCLUSIVE when the mutation is mandatory
  and `mutation_inverted is None`.
- **F4 owns restore on BOTH axes.** `infra/06_verify.py` pins the engine ARN but **neither mode**,
  with a comment saying F4 legitimately drives the mode to LOG_ONLY. Nothing outside this script will
  notice a mode left switched. Restore to values **measured at startup**, not assumed from the
  ledger, and re-run the blocking assertion (PREREGISTRATION `restore_verification`).
- **`UpdateGateway` is a REPLACE.** Resend the four required members **and** the full live config; a
  field omitted is a field reset, and resetting `exceptionLevel` would change every later error body.
  Readback from both the Update response and an independent `GetGateway` (their OUT shapes are
  identical), plus `04_gateway.wait_ready`.
- **`UpdatePolicy` must NOT resend `definition`.** Re-sending the Cedar body re-runs validation, and
  DC-1 is the finding that this exact statement fails validation without `IGNORE_ALL_FINDINGS`. Send
  `policyEngineId` + `policyId` + `enforcementMode`; read back `GetPolicy.enforcementMode`.
- **`policy` is structurally untaggable**, so the tag sweep cannot catch a leaked policy. F4's own
  `finally` is the only teardown channel for policies it creates.
- **F4-5's forbid arm must be an unconstrained `forbid` against the concrete gateway ARN** —
  `cedar.check_statement`'s lint refuses a scope naming a concrete action without
  `resource == AgentCore::Gateway::"<arn>"`.
- **Prediction on the record, before the run: F4-6 will REFUTE the document.** A gateway policy denial
  arrives as **HTTP 200** with `result.isError: true` and an `AuthorizeActionException`, not the
  HTTP 403 that doc L141 claims. Written down in advance so a confirmation cannot be presented as a
  discovery. Sites to amend if it holds: `C-s3-1-bullet-015` (L141), `C-s2-1-mermaid-002` (L56),
  `C-s9-mermaid-006` (L827).

### Two library fixes landed this session (both mutation-checked)

Written up as **DEV-P3-01**. Both were guards that reported clean while doing nothing, found before
F4's first call:

1. `"InvokeGateway": 10.0` added to `RATE_LIMITS` + `SELF_IMPOSED_LIMITS`. Service Quotas publishes
   **only concurrency** for this path (1000 connections, 1000 per gateway, 6 MB payload) and **no
   per-second rate**; the nearest published rate (25/s) is tool *search*, a different operation. 10/s
   is ours and is labelled as ours. Without the entry `wait("InvokeGateway")` returned 0.0.
2. `McpTransportError` now carries `error_class`, and `RETRYABLE_TRANSPORT` gained the **measured**
   urllib3 names (`NameResolutionError`, `NewConnectionError`, `ProtocolError`, `SSLError`). This was
   DEV-P1-11 on the data plane: the raise site computed the class name and threw it away, so every
   transport failure was classified permanent — and the pool is `retries=False` by design, so nothing
   else would retry either. New `lib/tests/test_mcp_retryability.py` (11 arms); `lib/mcp.py` had had
   **no test module at all**.

Library suite after both: **639 passed, 1 skipped**. `verify_prereg.py` green (`a2136a9d…`, 189
assertions) — neither file is a sealed bound artifact.

### Two gates fired on the new work — both fixed, both worth knowing about

- **`check_redaction.py` was at rc=1** (6 findings). Now **rc=0, 280 files, PASSED**. One was mine (a
  private-range IP literal in the new test → RFC 5737 TEST-NET-1); five were pre-existing false
  positives in offline fakes, now narrowly waived in `ALLOW` with per-entry written reasons. The
  waivers are **mutation-checked**: a real account id planted on a different line of a waived file
  still fails. ⚠️ Read the gate's exit code directly — `check_redaction.py | tail` reports `tail`'s
  rc and will read as a pass while the gate is failing.
- **`lib/tests/test_module_name_collisions.py` failed on `f4_modes/01_truth_table.py`.** The `_load`
  helper built its `sys.modules` key from a parameter, which that guard cannot read statically.
  Fixed by hoisting the key to a module-level constant `GW_MODULE_NAME`, **not** by adding an
  `UNRESOLVABLE` exemption. Any new script in this tree that loads `infra/NN_*.py` by path must pass
  a literal or module-level constant as the module name.

**Not yet done:** `./verify_phase0.sh` has not been re-run since these edits (it was 14/14 before).
`f4_modes/tests/` does not exist, so nothing in `f4_modes/` is under the gate yet.

## Where the work is

- Tree: `/Users/tmwu/Downloads/grx-validation/` (**not** a git repo — do not look for a branch, and
  never `git checkout -- <file>`: the working tree is ahead of anything git here knows about, so a
  mutation harness restores with `cp` only)
- Published to `github.com/timwukp/agentcore-guardrails-design-validation` **by API push only** — see
  the PR #12 note at the top of this file before pushing anything.
- Approved plan: `/Users/tmwu/.claude/plans/melodic-hatching-seal.md`
- Python: `.venv-oracle/bin/python` (botocore 1.43.67). `.venv-baseline` is 1.42.79 and is **data**, not a fallback.
- Full gate: `./verify_phase0.sh` — ~6 min, 14 gates.
- Full suite: `.venv-oracle/bin/python -m pytest -q --basetemp=<scratch>` → ~15 min. Pass
  `--basetemp`; the default location is what wedged the runner's disk (DEV-P4-31). Regenerate the
  pass count rather than trusting one written here.
- **Do not edit the tree while the suite runs.** The write guard watches `results/` and charges a
  concurrent modification to whichever test last spawned a subprocess, so an interactive edit
  surfaces as `ERROR at teardown of test_mutant[...]` naming a file that test never touched. Seen
  2026-08-13: editing `results/FINDING-P0-TRIAGE.md` mid-run errored
  `test_write_guard_mutation.py::test_mutant[M3-no-abspath]`, which passes 20/20 when the tree is
  quiescent. The guard is right — a write into the live results tree must not be excused — so the
  fix is to finish editing first, not to loosen it.
- Redaction gate: `.venv-oracle/bin/python check_redaction.py` — **>120 s**, last run rc=0 over 478
  files / 30,835,735 bytes. Read its exit code *directly*; piping it to `tail` reports `tail`'s rc.
  A run that reads **zero files is an error, not a pass.**

## There is live AWS state right now

**run_id `r20260810T130945Z`**, us-east-1, 25 resources in `state.json`:

| kind | n | kind | n |
|:---|--:|:---|--:|
| iam-role | 5 | delivery | 4 |
| delivery-source | 4 | delivery-destination | 3 |
| gateway | 2 | gateway-target | 2 |
| log-group | 2 | policy-engine | 1 |
| policy | 1 | lambda | 1 |

`ExpiresAt` on every tag is a **72 h TTL from creation**. If a reconnect happens after that window
and the work is not continuing, run `infra/99_teardown.py --run` and confirm zero survivors.

## Money spent so far

Still **under $2**, and the largest single line is now the runner rather than the experiments.
Derived, not remembered:

| item | how it is priced | to date |
|:---|:---|---:|
| control plane, CloudWatch Logs delivery objects | free to create and define | $0.00 |
| billable `tools/call` requests + span ingestion across F1–F7 | per request, all well under Cost Explorer's resolution | <$0.50 |
| EC2 runner `t3.small`, us-east-1 | $0.0208/h; provisioned 2026-08-11, ≤19 h wall-clock since | ≤$0.40 |
| runner root volume, 40 GB gp3 | $0.08/GB-month ⇒ $0.11/day | ≤$0.20 |

The `t3.small` figure is a **ceiling**: EC2's `LaunchTime` resets on stop/start (the volume was grown
from 20 GiB to 40 GB after DEV-P4-31), so uptime cannot be read off the current launch time and the
row above bills the whole window as if it never stopped. Phases 3–8 were projected at **$5.86**
combined and the measured spend is running well under that. **Stop the instance if the work pauses**
— `runner/provision.py` knows the instance id, and a stopped `t3.small` costs only its volume.

## Task state

| # | Task | State |
|--:|:---|:---|
| 1–6 | Phase 0 + Phase 1 foundations | done |
| 7 | Phase 2 testbed | done — gate satisfied, see below |
| 8 | Phase 3: F1 config surface + F4 truth table | F4 **6/6 done**; F1 **20/28** |
| 9 | Phase 4: F2 determinism + gateway F3 + F3-10 + F7 | **done** — F2 5/5, F3 11/11, F7 7/7 |
| **10** | **Phase 5 + 5c: F5 red team, watchdog, account-level gate** | **3/12 — this is the critical path** |
| 11 | Phase 6 + 6b: latency | **done** — F6 9/9, laptop-only by design |
| 12 | Phase 7 + 8: nine-region probe, F3-11 at +7d/+30d | partly done; `F3-11 --compare` owed 2026-08-18 and 2026-09-10 |
| 13 | Phase 9: analysis, figures, bilingual v1.3, NDA release gate | pending — blocked on the owed FINDING docs listed at the top |
| 14 | Phase 99: teardown + tag sweep, zero survivors | pending — **includes terminating the runner** |

## Task #7 — closed, with the evidence

The Phase 2 gate as pre-registered was "both gateways READY, benign call allowed on both, a span
carrying each gateway's ARN visible in `aws/spans`". All three hold:

- `06_verify.py` → **42/42 PASS**, rc=0. Re-runnable at any time; it is the precondition every
  later phase checks and Phase 5 re-runs after every restore.
- `07_traces.py --verify-only` → both gateways have a live TRACES delivery, symmetric.
- `08_smoke.py --run` → `tools/call` allowed end to end on both gateways (**831 ms** main,
  **432 ms** nopolicy, request ids archived), echo round trip confirms `context.output.*` is
  drivable, spans visible after 3 s (main) and 90 s (nopolicy).

To re-establish confidence after a drop, in order:
`06_verify.py` → `07_traces.py --verify-only`. Both are read-only and free. Do **not** re-run
`01`–`05`; they are `--ensure`-idempotent but there is nothing to fix.

### Five defects Phase 2's live run found, all written up in `DEVIATIONS.md`

Recorded because each was a real fault in our own harness, not in AWS, and three of them were
guards that would have reported clean while checking nothing:

- **DEV-P2-04** — the tag channel cannot see `iam-role` or `policy`; the fix moves the assertion
  to `list_role_tags`/`get_policy` and re-tests each exemption's premise every run.
- **DEV-P2-05** — the F6 pairing ignore list existed in two copies; `PAIR_IGNORE` is now shared and
  its justification is *checked* by `workload_identity_is_pure_identity()`, not written in a comment.
- **DEV-P2-06** — `put_delivery_*` accepts `tags` only on the create path, so `--ensure` was
  non-idempotent for every delivery resource; and the collision guard decided ownership by **name**,
  so it refused our own leftovers. Ownership is now by `Project`+`RunId` tag, fail-closed.
- **DEV-P2-07** — `SWEEP_TYPE_FILTERS` was a constant nothing applied, and three files reasoned
  from it to the opposite of the measured truth. Replaced by `TAG_INDEX_BLIND_KINDS`, whose values
  are the measurements.
- **DEV-P2-08** — the **evidence writer** broke the first billable call: an MCP `operation` contains
  a `/`, so the filename was a path. `evidence.safe_component()` + 10 test arms including a mutation
  arm. The aborted attempt's record is preserved under `P2-08-smoke-aborted-attempt-01/`.

## Constraints that must survive a reconnect

- **NEVER `git push`.** GitHub Git Data API only (`gh api`, 6-step flow); ref `~/Desktop/github-git-data-api-push.md`.
- Redact the management account id, both member account ids, all ARNs and all bucket names before
  **any** public push. Run `.venv-oracle/bin/python check_redaction.py`; it must read a non-zero
  file count and exit 0. (The ids are deliberately not written here — the first draft of this note
  spelled all three out and the gate reported it, which is the rule working.)
- Spend: act freely under $1000/mo project spend, but **always disclose**. Running total: <$2 (see
  the table above for how each row is priced).
- **Never touch**: the 6 pre-existing READY gateways, the 3 DRAFT guardrails (`demo`, `test`,
  `demo123`), the 2 abandoned policy engines (read-only evidence for F1-3), any `harness_*` /
  `uitestagent_*` runtime or Memory resource, and the **`nopolicy` gateway** — it is F6's paired
  baseline, so deleting it retroactively unmakes nine verdicts.
- Do **not** modify the account-wide `AWS-AttachIAMToInstance` /
  `SystemAssociationForManagingInstances` association. It targets every instance in the account and
  three other projects depend on it.
- `lib/stats.py`, `claims/triage.csv`, `claims/triage_rules.py`, `lib/oracle.py` and
  `PREREGISTRATION.yaml` itself are **sealed bound artifacts** pinned by sha256. Reading is fine;
  editing is not. `V13_CANDIDATES.md` is **generated** — regenerate it with
  `build_v13_candidates.py`, never by hand. `assert_transaction_search` **asserts, never enables.**
- `evidence/` is local-only by written policy and `.gitignore`d, as are `runner/.state/` and
  `f1_config/.wheel_cache/`. `results/` **is** distributable and is masked by `lib/redact.py`.
- Chinese for discussion, English for deliverables. `.md` and `.zh-TW.md` change together.

## Three things worth remembering about the testbed

1. **Gateway tracing is not a `CreateGateway`/`UpdateGateway` field** — `bedrock-agentcore-control`
   has zero operations matching Trac/Observ/Telem. It is a CloudWatch Logs **vended delivery**:
   `PutDeliverySource(resourceArn=<gateway arn>, logType="TRACES")` →
   `PutDeliveryDestination(deliveryDestinationType="XRAY")` → `CreateDelivery`. This makes F7-5 a
   *better* experiment: the mutation is `DeleteDelivery`/`CreateDelivery`, which flips one object and
   leaves the gateway config byte-identical, so "spans absent" cannot be confounded with "the gateway
   changed". Those `logs` describe calls take `{limit, nextToken}`, **not** `maxResults`.
2. **DC-1 is confirmed live, twice.** The baseline policy is ACTIVE with `enforcementMode=ACTIVE`
   only under `validationMode=IGNORE_ALL_FINDINGS` — which v1.2 never mentions. A reader following
   §3.1/§7.2/§8 verbatim gets a `CREATE_FAILED` policy.
3. **`state.json`'s `resources` is a LIST, not a dict.** Any ad-hoc inspection script needs
   `rows = res if isinstance(res, list) else list(res.values())`. This has cost time twice.
4. **The guardrail score lives in the application logs**, at
   `body.policy.guardrailFindings.<policy>.contentFilter[].score`, and it is a **string**. Three
   rigorous probes reported it absent before DEV-P4-27 found it, because all three surveyed the
   surfaces the *document* named. Scope an absence claim to the list you actually searched.
5. **`ps` truncates rows to `$COLUMNS` even when stdout is a pipe** (procps-ng; BSD `ps` does not off
   a tty), and pytest exports `COLUMNS`. `conftest._foreign_live_run` therefore ran blind on Linux
   for two days and convicted every innocent spawner — DEV-P4-32. Two consequences worth carrying:
   `ps -ww` everywhere, and **a process-table probe must find its target by PID**, because the row
   that gets cut is precisely the row that no longer contains the name you would search for.
