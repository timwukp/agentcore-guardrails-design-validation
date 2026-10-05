# Cases with no verdict record, and why — census closure

**Date:** 2026-08-15, updated 2026-10-05
**Scope:** the sealed cases in `lib/oracle.py:BINDINGS` that hold no verdict record. There were 2
until 2026-10-05. There is now 1, F9-1, because F10-1 was measured (FALSE) on that date. The F10-1
section is kept below as the record of why it took seven weeks.
**Status:** F9-1 is recorded and skipped, and is not awaiting effort. F10-1 is closed by a verdict.

## The census

| | Count |
|---|---|
| Sealed cases in `O.BINDINGS` | **93** |
| Carrying a verdict record | **92** (91 until 2026-10-05) |
| Carrying none — this document | **1** (2 until 2026-10-05) |

Of the 92: TRUE 46, FALSE 24, INCONCLUSIVE 20, RECORDED 2, as reported by `census.py` on
2026-10-05, so the publishable count is now 91, not 90. The rest of this paragraph is the
2026-08-15 reading of the 91 records that existed then. They were counted after `F5-7b`'s
re-scored record was merged to this machine (it is the twentieth
INCONCLUSIVE, and it was measured on 2026-08-14 and re-scored on 2026-08-15). One of the 46 TRUE
verdicts, `F5-3b`, is **non-publishable** and may not be cited as confirmation, so the design
document's own count is 90 publishable, not 91. `results/phase1/` also holds
`F2_score_harvest_shared.json`, which is a shared input rather than a sealed case, and three
`case_id`s are claimed by more than one file (`F3-10`, `F3-11`, `F5-4a`) — a census keyed on
`case_id` alone silently collapses those and undercounts. This one collects into a list per id.

**INCONCLUSIVE is not the same thing as unmeasured.** The 20 INCONCLUSIVE cases were run; their
observations did not decide their oracles. They are not in this document, and they license no
amendment to the design document either way.

---

## F9-1 — untestable by pre-registration, not by outcome

**Sealed kind:** `NOT_TESTABLE`
**Sealed oracle text, verbatim:**

> Would be TRUE if an induced service-side evaluation timeout produced DENY. NOT TESTABLE:
> AgentCore exposes no fault-injection surface for policy evaluation. Nearest proxies are F5-4a
> (unevaluable policy) and F5-4b (guardrail evaluation impossible)

**The objective reason.** The claim is about what the policy engine does when *its own
service-side evaluation times out*. Measuring it requires inducing a timeout inside AWS's policy
evaluation path. AgentCore exposes no fault-injection surface for that path — no API, no
configuration, no throttle that reaches it. This is not a permissions limit, a cost limit, or a
scheduling problem, and no arrangement of client-side behaviour substitutes: a client-side timeout
is a fact about the client, which is precisely the error that made `F5-7b` unreadable (see
`results/FINDING-F5-7B.md` §3).

**Why this is a real record and not a convenient one.** The `NOT_TESTABLE` kind was sealed
*before* any testing, and the sealed files are read-only for the duration of the project. The
distinction matters: a project that can declare a case untestable *after* failing to measure it can
launder every failure into an exemption. The seal is what makes this a finding rather than an
excuse — the judgement is checkable against a file nobody could edit once data started arriving.

**What is known anyway, through the proxies the seal itself names.** Both ran and both are
`RECORDED` — the kind meaning the pre-registration declared the outcome unknown and *both* answers
are findings:

- **F5-4a** — an unevaluable policy.
- **F5-4b** — guardrail evaluation made impossible by removing `bedrock:InvokeGuardrailChecks`
  from the gateway execution role. Its recorded reading: **fail-closed for this failure mode.** The
  engine denied the violating request *and* the benign one, i.e. it stopped discriminating by
  content, which is what an evaluation that cannot run should look like.

F5-4b's own reading states the boundary explicitly: the `fail-secure` label is corroborated **for
the missing-permission mode specifically — not for the timeout mode**. So the design document's
fail-secure claim has partial empirical support, and F9-1 is exactly the part that has none and can
have none from this platform. That is the honest shape of the answer, and it is more useful than a
verdict would have been.

---

## F10-1 — three obstacles, only some of them objective

**Sealed kind:** `EXISTENCE`. `mutation_is_mandatory` is False; `planned_n` is None.
**Sealed oracle text, verbatim:**

> TRUE if a Cost-Explorer/tagged delta shows zero inference charge for input-blocked requests and
> full charge for output-blocked ones; FALSE if either differs

Stating these separately because they are not equally binding, and collapsing them into one
"blocked" would misrepresent the case.

**1. Cost Explorer's data lag — objective, and originally decisive.**
`results/DEPENDENCY-AUDIT-2026-08-13.md` recorded it as "blocked on physics": Cost Explorer data
lags roughly 24 hours, so no effort on the night of 2026-08-13 could produce the delta the oracle
reads. That was correct then. It is **no longer the operative blocker**, because two days have
passed — and this document says so rather than reusing a reason that has expired. A stale blocker
is indistinguishable from a live one in a status table, which is how cases quietly stop being
looked at.

**2. The runner role cannot call Cost Explorer — a choice, and it is mine.**
`grx-runner-ec2` is not authorized for `ce:GetCostAndUsage` (confirmed 2026-08-15,
`AccessDeniedException`, "no identity-based policy allows the ce:GetCostAndUsage action").
`runner/iam_policy.py` is *derived from captured evidence*: it grants what the cases were observed
to call, and no case has ever called Cost Explorer — because this one never ran. Widening a policy
that derives its legitimacy from evidence, in order to run an exploratory check, inverts that
relationship. The same reasoning was applied earlier to `ListAgentRuntimes` and the check was
dropped instead. **This obstacle is removable and I am declining to remove it unilaterally.** It is
recorded as a decision, not disguised as physics.

**3. The oracle needs a discriminator the instrument may not be able to supply — unresolved.**
The oracle reads a *delta* between input-blocked and output-blocked requests. Cost Explorer's
finest granularity is daily, grouped by usage type or tag. So the reading requires that the two
request classes be separable within a daily aggregate, in an account that also runs six READY
gateways and other `harness_*` / `uitestagent_*` workloads. Whether Bedrock inference charges are
attributable per request tag at all is **not established here**, and this document does not claim
it either way — it is flagged as the question a future attempt has to answer first, because if the
answer is no, obstacles 1 and 2 were never the real ones.

**Consequence for the document.** F10-1's claim is unsupported by measurement and stays unsupported.
Under `PREREGISTRATION.yaml`'s `reproduction_before_amendment` rule an unmeasured case licenses no
amendment, so nothing in the design document moves on its account — in either direction. Its
sibling **F10-3 is unaffected and did run**: it reads `usage.*Units` and
`guardrailCoverage.textCharacters` directly off the `ApplyGuardrail` response and needs no billing
data at all.

**2026-09-28: a design exists, and the record above is unchanged.** `f10_billing/F10-1-DESIGN.md`
proposes an answer to obstacle 3 built from the sealed method's own words, "cost attributed by resource
tag". It uses two tagged application inference profiles, one per arm, with the output-blocked arm
serving as the positive control that tag attribution reaches Cost Explorer at all. Obstacle 2 has
changed shape: the runner is gone, so the read would run from the operator's machine, and a read-only
Cost Explorer query was refused there by the session's permission layer, pending the user. **Nothing
has been sent, and F10-1 remains not measured.** Whether profile tags reach Cost Explorer line items is
the design's own unverified premise, and its positive control is what would establish or refute it.

**2026-10-05: measured. FALSE.** `results/phase1/F10-1.json`. The run is described step by step in
`f10_billing/F10-1-DESIGN.md`. Obstacle 2 went away with the runner. Obstacle 3 was answered by
the method above, plus a third arm the pre-flight forced. The arm is a control: the same prompt with no
guardrail, through its own tagged profile. Over 20 requests per arm on 2026-10-02, Cost Explorer billed
the control 580 input and 80 output tokens, exactly what its responses reported, so tag attribution
works. It billed the input-blocked arm nothing, as the claim says. It also billed the output-blocked arm
nothing, where the claim says it pays in full. Its expected charge, taken from the control, was 580/80.
An account-wide read of every Nova Micro usage type, with untagged spend kept, shows no other Nova
usage on that day. So the blocked arms' tokens did not land untagged instead.

The verdict rests on **one calendar day**. Under `reproduction_before_amendment` it therefore
licenses no amendment yet. The v1.4 sentences ("if the OUTPUT is blocked, you still pay full
inference") stand as written until a second day replicates the reading. See `FUTURE-WORK.md`
item 10.

---

## What this document does not claim

- That the 92 measured cases produced 92 useful answers. 20 are INCONCLUSIVE and several of those
  are instrument failures rather than platform facts — `F5-7b` is one, and its own re-score on
  2026-08-15 corrected the *reason* while leaving the verdict where it was.
- That F10-1's FALSE generalises. It was read on one model (Nova Micro), one word policy, the
  non-streaming `Converse` API, and one day.
- That recording F9-1 closes the project. `F5-8`'s day-2 replication, and the day-2
  replications owed by `F4-6` and `F2-1`, remain outstanding under
  `reproduction_before_amendment` — those are *measured* cases awaiting a second calendar day, a
  different thing from the one recorded here.
