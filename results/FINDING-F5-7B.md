# FINDING F5-7b — The VPC egress case ran, and did not measure what it exists to measure

**Status:** **AMENDMENT_DEFERRED** — ran live on EC2 in us-east-1 and returned INCONCLUSIVE, which
licenses no change to the document. The INCONCLUSIVE is an *instrument* result, not a platform
result: see §3
**Date:** 2026-08-14
**Verdict:** INCONCLUSIVE (`O.not_measured`) — correct, and reached for a reason the run's own note
states wrongly
**Script:** `f5_redteam/12_vpc_egress_image_pull.py`
**Diagnostics:** `f5_redteam/diag_vpc_runtime.py`
**Raw data:** `results/phase1/F5-7b.json`, `results/DIAG-vpc-runtime-20260814T092455Z.json`
**Class:** instrument defect (the case is still open) + two citable platform observations

<!-- provenance
{
  "status": "AMENDMENT_DEFERRED",
  "status_note": "The sealed verdict is INCONCLUSIVE and INCONCLUSIVE licenses no amendment. Observations are not complete either — the case's own oracle was never brought to bear, because the channel that was supposed to decide it returned a client-side constant on all three arms. So the token is AMENDMENT_DEFERRED rather than OBSERVATIONS_COMPLETE: this case is owed another run with a working instrument, not a write-up.",
  "evidence_runs": ["r20260810T130945Z"],
  "cases": ["F5-7b"],
  "amendment_licensed": false,
  "blocked_on": "A working invoke channel. The oracle is denominated in an IMAGE PULL, and on all three arms the only channel that could observe a pull returned a client-side botocore read timeout with http_status None, no request id, and duration_ms of 70082/70077/70073 — a fixed 70s socket timeout, identical across three different network configurations, carrying no information about whether an image was fetched. `pull_evidence()` labelled that `pull_failed` because `PULL_MARKERS` contains 'timeout'; the honest label is `ambiguous` on all three arms. Until the pull is made observable — an image that answers the AgentCore contract on :8080, or the runtime's CloudWatch log stream, which the execution role can already write — this case cannot be decided either way. Separately citable and NOT blocked: (1) a VPC-mode runtime with NO default route reached READY with an empty failureReason, so READY is not evidence of egress; (2) a VPC-mode runtime leaves a service-managed `agentic_ai` ENI attached by `amazon-aws` that outlives the runtime by more than 35 minutes and blocks subnet/SG/VPC teardown. Both are single-day and single-run.",
  "note": "The published verdict is safe despite the defect: the mislabelling can only ever produce `pull_failed`, and the oracle's TRUE requires the pair (pull_failed, pull_succeeded), so the defect cannot manufacture a TRUE. It also cannot manufacture the FALSE, which needs pull_succeeded on the no-route arm. The defect can only push the case toward 'not a pair the oracle names' — i.e. toward INCONCLUSIVE. Nothing wrong was published. What is wrong is the recorded REASON, which invites the wrong repair."
}
-->

## 1. What the case is for

Seal (`lib/oracle.py`, `Binding(kind='EXISTENCE')`):

> TRUE if a VPC-mode runtime without a NAT route fails image pull and succeeds with one;
> FALSE if egress is reachable either way

Three arms, in order, with the middle one a mandatory mutation and the third the
`restore_verification` re-run required by `PREREGISTRATION.yaml:520-524`:

| Arm | Private route table | Purpose |
|---|---|---|
| `no_nat_route` | local route only | the blocking assertion |
| `with_nat_route` | `0.0.0.0/0` → NAT gateway | the mutation |
| `route_removed_again` | local route only | re-run the assertion after restore |

## 2. What was observed

| Arm | Create | Time to READY | `failureReason` | Invoke | `duration_ms` |
|---|---|---|---|---|---|
| `no_nat_route` | **READY** | 261.9 s | *(empty)* | read timeout | **70082** |
| `with_nat_route` | **READY** | 20.2 s | *(empty)* | read timeout | **70077** |
| `route_removed_again` | **READY** | 20.2 s | *(empty)* | read timeout | **70073** |

Restore verified by reading the route table back: `default_route_gone: true`.

**All three creates succeeded, including the one with no path to the internet.** So the create-time
channel says nothing: a producer scoring this case on create status alone would have recorded
"egress is reachable either way" — the oracle's **FALSE**, a claim about someone else's networking —
on no evidence about any fetch. The producer was built expecting that and consults the invoke
channel instead. This run is the reason that was worth doing.

## 3. Why the invoke channel decided nothing, and how it nearly said otherwise

Every arm's invoke failed with:

```
Read timeout on endpoint URL: "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/..."
```

with `http_status: None`, `request_id: ''`, `error_code: ''`. **No HTTP response ever arrived.** The
timeout is the local socket giving up; the service never spoke.

The decisive detail is the three durations: **70082, 70077, 70073 ms** — a spread of 9 ms across
three arms whose network configurations differ. Three differently-configured runtimes do not
coincidentally hang for the same 70.08 s. That is a fixed client-side read timeout being observed
three times. It measures this client's patience, not the platform.

`pull_evidence()` nevertheless labelled all three `pull_failed`, via `bucket_failure()`, because
`PULL_MARKERS` (line 198) contains `"timeout"` and `"timed out"`. Two mistakes compounded:

1. **A classifier applied outside its domain.** `bucket_failure()` was written to read a
   *service-supplied* `failureReason`, where "timeout" plausibly does mean the pull timed out. It
   was then pointed at a *client-side* socket error, whose text names the AWS endpoint URL and
   nothing about any container.
2. **The post-pull list cannot catch it.** `POST_PULL_MARKERS` is checked first and would have won,
   but it looks for `ping`, `health`, `8080`, `port`, `did not respond` — words a service emits. A
   botocore timeout string contains none of them, so it fell through to the pull list.

The irony is that the producer *anticipated this exact scenario* and says so at lines 701-705, which
return `pull_succeeded` when the invoke fails post-pull, "which is the expected shape for this
image: it serves :80 and AgentCore's contract is :8080". `public.ecr.aws/nginx/nginx:stable` is the
diagnostic's own `pull_ok_serve_bad` arm. **A successfully pulled, running nginx produces exactly
this hang** — it binds :80 and will never answer an AgentCore invocation. What the producer did not
foresee is that the platform reports this by saying *nothing*, so the observation arrives as a
client timeout rather than as a service message, and lands in the wrong bucket.

**This is F1-15's near-miss in mirror image.** There, two byte-identical 107-byte bodies at 38 ms and
59 ms were labelled `routed` and scored as a policy bypass; the finding records the 38 ms as "a
second tell, ignored: far too fast to have crossed an engine". Here the tell is the opposite shape —
suspiciously *exact* rather than suspiciously fast — and it is the same error: **a constant mistaken
for a measurement.** DEV-P4-22 has now arrived on two unrelated surfaces.

### 3.1 Why nothing wrong was published anyway

The verdict is INCONCLUSIVE and the run's note reads:

> not measured: the arms produced a pair the oracle does not name: no_nat_route=pull_failed,
> with_nat_route=pull_failed.

The **verdict is correct and safe**, and provably so rather than luckily: the defect can only ever
emit `pull_failed`. TRUE requires `(pull_failed, pull_succeeded)`; FALSE requires `pull_succeeded` on
the no-route arm. A defect that produces only `pull_failed` cannot reach either. It can only push the
case into "not a pair the oracle names" — INCONCLUSIVE. The pair table did its job.

The **recorded reason is wrong**, and that is the part that matters. It describes arms that were read
successfully and merely disagreed with the seal. The truth is that no arm was read at all. Left
standing, that note invites the wrong repair — relaxing the pair table to admit
`(pull_failed, pull_failed)` — which would convert a silent instrument failure into a published
FALSE. The right repair is to make the pull observable.

### 3.2 The timing difference is not evidence, and the restore arm is why

261.9 s to READY on the no-route arm against 20.2 s with the route is a 13× difference that lines up
with the route, and it is tempting. It does not survive the restore arm: `route_removed_again` has no
default route either, and took **20.2 s — the with-route figure, not the no-route figure**. If
create latency tracked egress, removing the route would have restored the 261.9 s. It did not.

First-create warm-up in a brand-new VPC explains the observation without reference to egress, and the
third arm is what distinguishes the two accounts. Recorded here as the alternative-explanation
register `reproduction_before_amendment` asks for. **The 261.9 s is not cited as evidence of
anything.**

A further possibility this run cannot rule out, and which would make the oracle's premise itself
wrong: the `agentic_ai` ENI is attached by `amazon-aws` (§5), and `networkModeConfig` carries a
`requireServiceS3Endpoint` flag, so AgentCore may pull images over service-managed infrastructure
where a customer NAT route is simply irrelevant. That would make "fails image pull without a NAT
route" false about the platform rather than untested. **This run cannot distinguish that from its own
instrument failure**, which is precisely why the case is still open.

## 4. What would actually measure it

In preference order:

1. **The runtime's CloudWatch log stream.** A pull failure is written there, and the execution role
   `grx-runtime-vpcegress-<run_id>` already carries logs permissions. This reads the service's own
   account of the fetch instead of inferring it from a client error, and needs no new image.
2. **An image that answers the AgentCore contract on :8080.** Then a fetched, started container
   returns 200 and `pull_succeeded` is positively observable rather than inferred from an absence.
   Costs a container build — the thing `public.ecr.aws` was chosen to avoid.
3. **Not** a nonexistent tag: the diagnostic measured that `CreateAgentRuntime` refuses an unknown
   public-ECR tag *synchronously* (`ValidationException`, request id `aaed56be-…`), which is a
   control-plane pre-check upstream of any VPC networking. It proves nothing about egress.

Minimum instrument fix regardless: move `timeout`/`timed out` out of `PULL_MARKERS`, and have
`pull_evidence()` treat any invoke with `http_status: None` and no request id as `ambiguous` by
construction — a response that never arrived cannot name a step.

## 5. Two citable platform observations

Both are direct API/wire observations rather than oracle outputs. Single-day, single-run.

1. **READY does not imply egress, or a fetched image.** A VPC-mode runtime whose private subnet
   carried only the local route reached `READY` with an empty `failureReason`. Any readiness check
   built on runtime status will pass on a runtime that cannot reach the internet. The diagnostic saw
   the sharper version of this in PUBLIC mode — READY at the very first poll, 10.1 s — which is what
   prompted measuring both channels.
2. **A VPC-mode runtime leaves a service-managed ENI that outlives it and blocks teardown.** After
   all three runtimes returned `ResourceNotFoundException`, one ENI remained:
   `InterfaceType: agentic_ai`, `Attachment.InstanceOwnerId: amazon-aws`, `AttachmentId: ela-attach-…`,
   `DeleteOnTermination: false`. It was still `in-use` more than 35 minutes later, and
   `delete_network_interface` returns `InvalidParameterValue: … currently in use`. An `ela-attach`
   attachment cannot be force-detached. It blocks `DeleteSecurityGroup`, `DeleteSubnet` and
   `DeleteVpc` behind it — the Lambda hyperplane-ENI pattern, on a new interface type.

   **Operational consequence:** any automation that creates a VPC-mode runtime and then tears down
   its own VPC must poll for ENI release on the service's schedule, not its own. This case's
   `ENI_CLEAR_TIMEOUT` of 420 s was not enough.

## 6. Safety and residue

**A new VPC, in 10.61.0.0/16**, chosen because the default VPC is 172.31/16 — so nothing this case
built could overlap anything already running.

**The deny-list was resolved at runtime and the widening was substantive.** It resolved to **20 ids
(1 VPC, 6 subnets, 13 security groups)** from the `grx-runner-sg` *name*. The three hard-coded ids it
replaced covered 1 VPC, 1 of those 6 subnets and 1 of those 13 security groups. The literal list was
protecting under a sixth of the runner's own network, and would have gone stale silently if the
runner were ever rebuilt. `guard()` now also refuses everything when the set is empty, so an
unresolved deny-list fails closed. The same resolution was re-asserted by hand in the follow-up
cleanup before any delete was issued.

**The NAT gateway — the only hourly-billing resource in the run (~$0.045/h) — was deleted**, polled
to state `deleted` (60.2 s) rather than trusted to return 200. The Elastic IP was released.

**Residue: 4 items, all of them behind the ENI of §5, and all billing $0.00/h** — one service-held
ENI, one security group, one private subnet, one empty VPC. Deleted in the run: 9 items. A detached
sweeper (`f57b-sweep`) retries the chain every 5 minutes for 4 hours, guarded by the same runtime
deny-list; the ledger retains all four entries so none is forgotten if it outlives the sweeper.

**Not a leak of anything that bills, and not a case of teardown having been skipped** — the teardown
ran, in the documented order, and was refused by the platform. That distinction is worth keeping:
`back_to_baseline: false` here means "AWS is still holding an interface", not "this run abandoned
resources".

## 7. Census effect

**None.** F5-7b was the only genuinely runnable-but-undone case in the project; it has now run, and
it returned INCONCLUSIVE without reaching its oracle. It moves from *not attempted* to *attempted and
not measured* — which is an honest change in status and no change at all in what the document may
say. The two remaining unrun cases are unchanged: `F9-1` (sealed UNTESTABLE by its own oracle) and
`F10-1` (blocked on Cost Explorer's ~24 h data lag).
