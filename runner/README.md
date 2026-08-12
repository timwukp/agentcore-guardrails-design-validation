# The EC2 runner

An Amazon EC2 instance that executes the remaining validation cases unattended, so a closed laptop
no longer ends a run.

```bash
.venv-oracle/bin/python runner/provision.py --dry-run   # resolve everything, create nothing
.venv-oracle/bin/python runner/provision.py             # ~90 s; idempotent
.venv-oracle/bin/python runner/sync.py push             # upload the working tree (~3 MB, seconds)
.venv-oracle/bin/python runner/sync.py push-evidence    # upload evidence/ (~178 MB, minutes)
.venv-oracle/bin/python runner/sync.py status           # ask the instance if it is ready
.venv-oracle/bin/python runner/sync.py session          # SSM shell (no SSH, no inbound port)
#   on the instance:  grx-refresh        re-pull the code
#                     grx-evidence       re-pull the evidence archive
#                     grx f3_efficacy/08b_log_surface_join.py --help
#                     grx-publish        push results/, state.json, evidence/ back to S3
.venv-oracle/bin/python runner/run.py --detach --label X 'CMD'   # survives a closed laptop
.venv-oracle/bin/python runner/run.py --jobs             # detached jobs and their exit codes
.venv-oracle/bin/python runner/run.py --tail X           # last 200 lines of a job's log
.venv-oracle/bin/python runner/sync.py pull             # download into runner/.state/incoming/
.venv-oracle/bin/python runner/teardown.py              # terminate + revoke; bucket kept
```

## What this actually buys, and what it does not

Most of what is left is **not compute bound**, so honesty first:

| remaining work | does the runner help? |
| --- | --- |
| Wall-clock cases — next-day replicates, anything that outlives a laptop session | **Yes.** This is the reason it exists. |
| Date-gated reads — F3-11 `--compare` at 2026-08-18 and 2026-09-10 | **Yes.** They can fire unattended. |
| Long sweeps (the τ-sweep for F2-2/F2-3/F2-4) | **Partly.** They are API-throughput bound, not CPU bound; the win is that they survive a disconnect. |
| F5-8, F5-7b | **No.** They need a minimal AgentCore Runtime to exist. |
| F5-3a | **No.** Needs an Organizations child OU. |
| F5-9 | **No.** Hard-gated on an account-level setting. |
| F6 latency | **Deliberately not.** See below. |

**F6 latency stays on the laptop.** Those numbers were taken from one network position. Re-taking
any of them from inside a VPC would answer a different question, and a corpus mixing the two would
be worse than either one alone. If a latency case ever needs re-running, it runs where the
original did.

**Publication stays on the laptop.** The instance holds no GitHub credential. It syncs to S3; the
redaction gate (`check_redaction.py`) and the full test suite run here, and the Git Data API push
happens from here. Nothing leaves the account without passing the gate on a machine that has it.

## What gets created

| resource | what it is | why this shape |
| --- | --- | --- |
| `t3.small`, 20 GiB gp3, **encrypted** | the runner | API-bound workload, so more vCPU buys nothing; the evidence tree lands on the volume, hence encryption |
| security group `grx-runner-sg` | **0 ingress rules**, egress tcp/443 | SSM dials out, so nothing needs to dial in; `provision.py` refuses to launch if an ingress rule exists |
| IMDSv2 required, hop limit 1 | metadata hardening | the instance role is what an SSRF would be after |
| role + profile `grx-runner-ec2` | the instance's credential | policy **derived** from `evidence/`, see below |
| `s3://grx-validation-runner-<suffix>` | transport both ways | private, SSE-S3, versioned, 90-day expiry; the suffix is 8 random bytes and the bucket is found again by **prefix + tags**, never re-derived — see below |

No SSH key is created and no port is opened. Access is `aws ssm start-session`.

### The bucket name is random, and the reason is a measurement

Bucket names live in a **global** namespace, so they leak wherever they are written and redaction
cannot reach them afterwards. The first version of this script solved that by deriving the name
from `sha256(account_id).hexdigest()[:16]`, on the stated grounds that a hash is not reversible.

That was wrong, and it was wrong by a wide margin. There are only 10^12 twelve-digit account ids,
which is a keyspace a laptop can walk: **measured 2,874,794 candidates/sec on one core** with the
exact expression the code used (CPython 3.12.12) — 4.0 days single-core, ~12 hours across 8 cores,
and roughly **100 seconds** on one consumer GPU at a published hashcat SHA-256 rate of 10 GH/s. For
a given 64-bit digest the expected number of *other* twelve-digit preimages is 10^12/2^64 = 5.4e-8,
so a hit is the account id itself, not one of many candidates. A truncated fast digest over a small
keyspace is an **encoding**, not a hash.

So the derivation is gone. `provision.py` generates `secrets.token_hex(8)` — `secrets`, not
`random`, because a name a reader can regenerate from a seed is a name that carries information
again — and the next run finds the same bucket by **prefix ∧ own-account ∧ tags**: `list_buckets`
only ever returns the caller's own buckets, which is what makes a prefix safe in a global namespace.
The bucket is tagged in the call immediately after `create_bucket`, because an untagged bucket is
invisible to the next run, which would then quietly create a second one beside it. Any bucket the
script cannot positively identify as its own is skipped rather than adopted — `NoSuchTagSet`,
`AccessDenied`, `PermanentRedirect` and `NoSuchBucket` all `continue`, because "cannot tell" must
never resolve to "yes".

The real name is written only to `runner/.state/runner.json`, which is gitignored and which the
redaction gate skips for that reason (`lib/tests/test_redaction_gate_skips.py` checks that the skip
and the ignore rule agree). It is recorded in `DEVIATIONS.md` as **DEV-P4-25**, together with the
second half of that finding: the leak reached a pushable session log, and the gate did not see it,
because a bare bucket name has no `s3://` scheme for the pattern to fire on.

## The instance policy is derived, not written

`runner/iam_policy.py` builds the role's inline policy from the calls this project has actually
made. Every AWS call is archived as
`evidence/<run>/<family>/<case>/NNNN_<operation>_<ok|err>.json` carrying its `service` and
`operation`, so the API surface is a fact on disk — currently **44 distinct `(service, operation)`
pairs across 25,650 archived calls**. `MAPPING` translates each pair to the IAM action it needs;
`runner/tests/test_runner_policy.py` asserts that **no measured pair is unmapped**, so a case that
starts calling a new API fails at desk rather than at 2 a.m. with an `AccessDenied` nobody is
awake to read.

Scoping, and what each bound is for:

- every IAM write (`CreateRole`, `PutRolePolicy`, `DeleteRolePolicy`) and `iam:PassRole` are bound
  to `arn:aws:iam::<account>:role/grx-*` — `PassRole` on `*` is the escalation this file exists to
  close, and it is asserted by test;
- Lambda is bound to `function:grx-*`, log-group **writes** to `/aws/vendedlogs/bedrock-agentcore/*`;
- log **reads** (`FilterLogEvents`, `DescribeLogGroups`) are on `*` on purpose: F7's instrument is
  a namespace-wide read of a *shared* namespace, and narrowing it would change what F7 measures;
- no action ends in `:*`, no `s3:Delete*` (the instance must not be able to erase the audit trail
  it produced), and **no X-Ray write at all** — `assert_transaction_search` asserts and never
  enables, and the policy makes that structural rather than a convention.

### What the policy cannot express

It cannot say "do not touch the six pre-existing READY gateways, the three DRAFT guardrails
(`demo`, `test`, `demo123`), the two abandoned policy engines that are F1-3's read-only evidence,
the `harness_*`/`uitestagent_*` resources, or the `nopolicy` gateway that is F6's paired
baseline". IAM has no way to say "every gateway except these". That protection lives in the case
scripts and their tests, and moving execution to an instance does not change it — it just means
the protection now matters on two machines instead of one.

## Cost

`t3.small` on demand in us-east-1 is **$0.0208/hour** — about **$15.20/month** running
continuously — plus **$1.60/month** for the 20 GiB gp3 root volume, plus S3 at $0.023/GB-month for
what is synced (tens of megabytes, so cents). About **$17/month while it is up**.

`runner/teardown.py --stop-only` drops that to ~$1.60/month and keeps the instance restartable.
Full `teardown.py` takes compute to $0 and deletes the role, which is the privilege revocation;
the bucket is **kept** by default because it holds the evidence a run produced, and
`--delete-bucket` is the explicit opt-in once the output has been pulled and merged.

## `evidence/` does go up — a correction

The first version of this runner deliberately left the evidence tree behind, on the reasoning that
it is a local-only audit archive and the instance should build its own. The first suite run on the
instance returned **156 failures and 170 errors**, every one of them a test that reads
`evidence/`; 26 test modules do. A runner that cannot run the project's own gate is half a runner,
so `sync.py push-evidence` uploads it as a separate object and `grx-evidence` extracts it.

"Local-only" is a rule about **distribution**: the tree is gitignored, excluded from the redaction
gate by directory, and never published, because its purpose is that a full ARN and request id can
be quoted to AWS Support. Copying it to a private, encrypted, public-access-blocked bucket in the
*same account that produced it* does not cross that boundary. It stays a separate subcommand
because it is 178 MB across 26,620 files and changes only when a live case runs, while `push` runs
after every edit.

## The return path is staged, never applied

`sync.py pull` writes into `runner/.state/incoming/<stamp>/` and stops. It does not overwrite
`results/` or `state.json`, for three reasons: an artifact that overwrites the published one before
the gate has seen it has already defeated the gate; `state.json` is a ledger, and two machines
appending to it is a merge rather than a copy; and `git checkout -- file` is never safe in this
repo, so an overwrite is not recoverable.

`runner/.state/` is gitignored — the runner's *source* is tracked, only its resolved instance,
subnet, security-group and VPC ids are not, because three of those id shapes are redaction targets
and a file needing a waiver on every run trains a reader to waive things.
