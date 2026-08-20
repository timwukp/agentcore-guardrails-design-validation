# `platform/` — GRX Live

Everything that turns the finished measurement into something a person can read in a browser, and
nothing that produces a measurement. The rule that keeps this directory honest: **`platform/` reads
the repository's artifacts and never writes one.** No file under `results/`, `claims/`, `lib/` or
`PREREGISTRATION.yaml` is created, edited or moved by anything here.

```
platform/
  build/       the publish chain: derive a payload, gate it, upload it
  curation/    authored governance data (families.yaml; scenarios.yaml is not yet written)
  infra/       the CDK stack that receives the payload — see infra/README.md
  agent/       Phase 3, does not exist yet
```

## The publish chain

`build/publish_web.py` is the entry point and the only thing that talks to AWS. It runs the steps
below in order and stops at the first non-zero exit code. `--dry-run` runs every gate and makes no AWS
call; `--confirm` is required before anything is uploaded.

| # | Step | Interpreter | What it establishes |
|---|---|---|---|
| 1 | `verify_prereg.py` | `.venv-oracle` | The preregistration is sealed and its hash matches; 189 assertions, every derived value recomputed from `lib/stats.py`. |
| 2 | `check_redaction.py` | `.venv-oracle` | No unredacted cloud identifier anywhere in the repo tree. Its return code is read from `subprocess.run(...).returncode` directly — never through a pipe — and the count of files it scanned is parsed out and floored, because a scan that read zero files must not report clean. |
| 3 | `check_venv_isolation.py` | `.venv-oracle` | The measurement instruments are unchanged and nothing under `platform/` imports what it should not. |
| 4 | `whitepaper_figures.py --check` | `.venv-figs` | **Data, not a gate.** Its return code is recorded in the payload so the figure gallery can render "numbers drifted". `rc=1` does not stop a publish; a silent stale chart would. |
| 5 | `build_site_data.py` | `.venv-oracle` | The payload. The only writer of it. |
| 6 | `npm run build -- --base=/v/<stamp>/` | node | The SPA, compiled for the immutable release URL. Verified afterwards: the stamp appears in both `index.html` and a bundle. |
| 7 | `gate_payload.py` | `.venv-oracle` | The payload's bytes and the built SPA's bytes carry no identifier, and the set it scanned equals the set about to be uploaded — both directions. |
| 8 | `check_site_invariants.py` | `.venv-oracle` | The site cannot claim what the artifacts do not support. |
| 9 | `check_scenarios.py` | `.venv-oracle` | The curation lens obeys its own governance. **Required if and only if the payload contains `scenarios.json`** — see below. |
| 10 | upload | `aws` CLI | Content to `v/<stamp>/`, then `current.json`, then the root `index.html`. |
| 11 | `verify_served()` | `aws` CLI | Re-sync from S3 into a temp directory and re-run `gate_payload.py` over what the bucket actually holds. Zero objects fetched is a failure. |

Three properties of that list are load-bearing:

**A missing gate is an error, not a skip.** `publish_web.py` holds a list of the scripts and
interpreters it requires and refuses to start if any is absent. During development
`check_site_invariants.py` did not exist yet and the publisher refused to run — which is the correct
behaviour and the reason the file exists now. The one conditional step is `check_scenarios.py`, and its
condition is a property of the payload rather than of the developer's intent: if
`build_site_data.py` emitted `scenarios.json`, the gate is required.

**Publishing is pointer-last.** Immutable content goes to `v/<stamp>/` with
`Cache-Control: max-age=31536000, immutable`, then `current.json`, and the live document flips last as
a single no-cache `index.html` object. A plain `s3 sync` would mutate the live document *first*, so
there would be a window in which a fresh `index.html` requested assets that had not been uploaded yet.
`publish_web.py` also refuses to write into a `v/<stamp>/` prefix that already has objects.

**The last check reads the bucket, not the local tree.** Gating what was built and trusting the upload
would leave the difference unexamined. Step 11 fetches what S3 serves and re-gates it.

## The four virtual environments

They are not a packaging convenience. Two of them **are measurement instruments**: several F1 and F8
verdicts are statements about what a specific botocore version's service model contains, so the
version is part of the result and not part of the environment the result happened in. Every published
case records its `ambient_sdk.botocore`, which makes the set of versions this project has measured
under derivable rather than remembered — measured 2026-08-20: `1.43.67` in 98 cases and `1.42.79` in
one (`F8-8`). That derivation is exactly why two SDK venvs exist.

| venv | Pin | Purpose | Never |
|---|---|---|---|
| `.venv-oracle` | `boto3`/`botocore` **1.43.67**, `scipy` 1.18.0, `numpy` 2.5.2, `pytest` 9.1.1 | Runs every producer, every gate, and `build_site_data.py`. Its pin equals `runner/requirements.txt`, so the laptop and the EC2 runner are the same instrument. | Upgraded to reach a newer AgentCore API. That would silently re-date the F1/F8 verdicts that read this SDK's model. |
| `.venv-baseline` | `boto3`/`botocore` **1.42.79** | The older SDK one published case (`F8-8`) was measured under. Kept so that verdict remains reproducible. | Used for a new measurement. |
| `.venv-figs` | `matplotlib` 3.11.1, `numpy` 2.5.2, `pillow` 12.3.0 — **no botocore at all** | Draws the eight canonical whitepaper figures and re-checks their numbers with `--check`. | Given AWS credentials or an SDK; it has no reason to make a network call. |
| `.venv-agentcore` | not yet created (Phase 3) | Will run the AgentCore Harness toolchain, which needs a *newer* boto3 than the oracle pin. | Importing `lib/`, or running a producer. |

`build/check_venv_isolation.py` enforces this, and it enforces it as a property of the tree rather than
as a list of the three venvs that exist today — a list of names cannot notice a new name. Its three
arms:

1. **Declared pin.** `.venv-oracle`'s boto3/botocore must equal `runner/requirements.txt`.
2. **Derived pin.** *Any* `.venv*` that has botocore must carry a version that appears in some
   published case's `ambient_sdk`. A new venv with an unmeasured SDK fails here. Versions are read from
   `*.dist-info/METADATA`, not by running each interpreter — running one would import third-party code
   from the very tree the gate is suspicious of.
3. **Import direction.** `platform/agent/` may not import `lib/` at all; `platform/build/` may import
   only `lib.redact`, `check_redaction` and `census`, each with its reason recorded in
   `BUILD_MAY_IMPORT`. That is a **ceiling, not a floor**: sharing the masker and the pattern set is
   the design — one implementation, never a fork — while reaching into `lib.oracle` or `lib.stats` from
   a build script would put sealed verdict logic on a second code path. Imports are parsed with `ast`,
   because a grep for `import lib` misses `from lib.redact import mask` and hits it inside a docstring.
   The walk is **recursive**, and `platform/build/tests/` is exempted **by a stated decision** rather
   than by the shape of a glob: a build test's job is to re-derive a number from the repository's own
   code and compare, which is the opposite of a second code path. With the non-recursive walk this
   check first shipped with, the exemption was an accident of `glob` vs `rglob` — and a subdirectory a
   ceiling cannot reach is where the next unreviewed import goes. It also carries a floor: a walk that
   finds no files would otherwise report "ceiling respected".

Mutation-checked: six mutants (bump the oracle pin; plant an unmeasured botocore; import `lib` from
`platform/agent/`; import `lib.oracle` from `platform/build/`; import `lib.stats` from a file one
directory *below* `platform/build/`, which the pre-`rglob` version could not see at all; point the walk
at a directory with no Python in it and require the floor to fire rather than a clean report). All six
killed, each with a passing control first.

## What each gate refuses

### `gate_payload.py` — the bytes

Imports `PATTERNS` and `allowed()` from `check_redaction.py` rather than reimplementing them: a second
copy of a redaction policy is a second policy. It adds one pattern the repo-level gate cannot have —
the **bare runner-bucket name**, which embeds the account id (`{prefix}{stem}-{account}-{region}`) and
so is invisible to an `s3://`-shaped pattern. It scans the built SPA as well as the JSON, since a Vite
environment variable carrying an ARN is the likeliest new leak vector. It asserts **set equality**
between what it scanned and what is about to be uploaded, in both directions, and keeps a minimum-file
floor because zero files scanned is an error rather than a pass.

Hits may **inherit** a reviewed exception from a named source: `cases/F5-7b.json`'s RFC1918 CIDR is
the same run-scoped address the producer file already records with a written justification. Inheritance
names the source file, so an exception cannot be granted to a payload value that no artifact carries.

### `check_site_invariants.py` — the claims

Ten arms, each answering "is every claim these bytes let the UI render backed by something on disk".
The one that exists because of a specific incident: on 2026-08-19 this project made a *process* claim —
that a replication had happened — which no *artifact* supported. So a case may only be presented as
replicated if its archive spans two distinct UTC calendar days, a `day1_*` archive exists, every
archive file it names is on disk with the recorded sha256, **and each archive's label is the artifact's
own filename** — otherwise the dates every count derives from would be free text that nothing on disk
supports. The archive is additionally set-equal to `results/phase1/archive/<case>__*.json` on disk, so
an omitted day-2 file cannot make an under-claim and an over-claim look identical from inside the
payload.

Other arms: the manifest is live (set equality both ways, hashes recomputed); no total appears in the
bundle as a string literal (`93 92 91 90 46 23 20` — every one is derived at runtime from
`denominators.json`); every "pass rate" occurrence is preceded by "there is no"; each denominator has a
real definition, an integer and a named source; the verdict buckets sum to the published denominator
with INCONCLUSIVE its own bucket; every citation restriction is wired to the case page that renders it,
both directions; every figure is a real PNG matching its recorded bytes and sha256; every case carries a
non-empty sealed `oracle_text` and the registry seal recomputes.

Mutation-checked at 19/19 — see the module docstring, which also records the two ways the *first*
version of that check was worthless while looking thorough.

### `check_scenarios.py` — the curation lens

Not yet written, because the file it gates is not yet authored.
`curation/scenarios.yaml` is the B2B/B2C lens: the one thing in this platform that **cannot be
derived**. `claims/triage.csv` has no service-type dimension, `_census.json` carries only
case/family/title/tier/kind/sealed_binding/has_verdict, and there is no
b2b/b2c/multi-tenant/externally-facing vocabulary anywhere in the docs or the results. It is a
judgment about which verdicts matter to which service topology, so it is authored with a signed reason
per case — and it is authored by a human, not by this tooling.

`curation/families.yaml` **does** exist and already carries the machine-readable half: per family a
safety class, a cost class, whether it is schedulable, and `network_position_sensitive` (true for F6
only, because its estimator is a paired difference of client-measured wall clocks — re-running it in
EC2 would change platform *and* network position, the one dimension a replication must hold fixed).
Current derivation: 11 families, 7 schedulable, 1 network-position sensitive.

## Tests

```bash
.venv-oracle/bin/python -m pytest platform/build/tests -q     # 50 tests, ~30 s
```

Two files, and they deliberately do not repeat the gates. `check_site_invariants.py` and
`gate_payload.py` already assert properties of a finished payload on every publish; restating those
assertions in a test would be a second copy of one policy with no second derivation behind it. What
the tests cover is what only a test can reach:

| File | What only a test can reach |
|---|---|
| `test_gate_payload.py` | The gate's own refusals, driven by synthetic payloads: a planted account id, an empty payload against the file floor, a file dropped from the upload set, an inherited exception whose named source does not carry the value. |
| `test_build_site_data.py` | The **builder's refusals** — the families gate in both directions, the duplicate-key loader, the output-root guards — which produce no artifact, so nothing downstream can check them; the builder's own **provenance** claims, which `gate_payload.py` inherits redaction waivers along; the **series split**, invisible from either half alone; and the three states of `--figure-check-rc`, where defaulting an unrun check to 0 would render it as verified. |

Two conventions that keep them honest. **Counts are derived, never memorised**
(`feedback_test_suite_over_memory`): the case count comes from the register and the published count
from the verdict files, so a test cannot pass a build that dropped one case and gained a duplicate.
And the families-gate mutants **hand a mutated copy of the YAML to the deriver through a patched
reader** — the authored governance file is never written to, because a test that edits it is one
interrupted run away from leaving it edited.

Every assertion added here was mutation-checked with a passing control first, including the two whose
first drafts were wrong about the code rather than about the payload: the split leaves a **stub**
carrying `$series`/`n`/`bytes` where the array was (asserting absence would have demanded a page that
cannot say what it is missing), and a case page legitimately inherits its **own sub-artifacts** —
`cases/F3-10.json` reads `F3-10_log_surface_join.json` — so the rule is a prefix at a separator, under
which `F5-7b.json` is still foreign to `F5-7`.

### The SPA has no unit tests, and that is a stated gap

`site/` is verified three ways, none of which is a unit test: `tsc -b --noEmit`, the two gates that read
its built bytes (steps 7 and 8 above), and a Chromium walk-through. The walk is not a formality — it is
what found that the case page's heavy-series state survived a route change, so navigating from a case
with five split series to a case with one made the second case's row read `MISSING` and hid its load
button. `tsc` was clean, both gates were green, and no API assertion looks at two routes in sequence.
The state is now keyed by case id rather than cleared in an effect, because an effect repairs the second
frame and still renders the first one wrong. Until there is a component test here, a rendering
regression in `site/` does not red a test run: **assume it, and walk the routes you changed.**

## Local preview

```bash
python platform/build/csp_preview.py            # 127.0.0.1:8901, real CSP in front of site/dist
python platform/build/csp_preview.py --print-only
```

The preview parses the Content-Security-Policy **out of** `platform/infra/lib/site-stack.ts` instead of holding
a copy, and refuses to start if the parse yields no directives or no `default-src`. A CDK test arm
compares its output against the synthesised template, so the two cannot drift and a refactor that
breaks the parse fails `npm test` rather than failing months later for whoever next runs the preview.

Two housekeeping facts: `site/dist/data` is a symlink to the payload directory and must be re-created
after every `vite build` (`publish_web.py` re-creates it on exit); and a build made with
`--base=/v/<stamp>/` emits absolute asset URLs, so after a publish run `npm run build` in `site/` to
restore the relative-base build the local preview needs.
