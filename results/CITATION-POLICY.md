# Citation policy — what each verdict may and may not be used to say

**Purpose.** One place to check before citing a case. Every restriction below already existed
somewhere in this repository; the problem this file fixes is that they existed in **five different
places** — `results/CENSUS-NOT-MEASURED.md` prose, `FUTURE-WORK.md` prose, `WHITEPAPER-DESIGN.md`
prose, a `FINDING-*.md` section, and a per-case field — so the only way to know whether a case was
citable was to have read all five. A reader citing `results/phase1/F5-3b.json`, which says `TRUE` and
nothing else, had no way to discover that it may never be cited as confirmation.

**Why not `results/ERRATA.md`.** That file's own opening scopes it to factual errors in what a
*sealed* file says, and states it is "not for verdicts, which live in `results/` and the findings". A
weak oracle is not a wrong statement in a sealed file, and an errata entry for one would be a category
error. This file is the verdict-side counterpart.

**Standing of this file.** It is not sealed and it is not evidence. It records **editorial
restrictions derived from evidence**, each with the artifact that establishes it. Where this file and a
sealed artifact disagree, the sealed artifact wins and this file is the thing that is wrong.

---

## 1. Restrictions that survive the verdict

| Case(s) | Verdict on disk | May be cited as | May **not** be cited as | Established by |
|---|---|---|---|---|
| **F5-3b** | `TRUE` | nothing — it is excluded from every conclusion | confirmation of any claim, or a TRUE in any count | its own `every_boundary_transition_was_observed_to_settle` guard failed: two IAM boundary transitions never settled inside their ~307 s observation budgets. `results/CENSUS-NOT-MEASURED.md`; register item 12 |
| **F6-2**, **F6-5** | `FALSE` (day 1) | the p50 and p90 comparison, which is decisive on both days and inside the documented 100–500 ms band; and the server-reported latency *drop* between the two days | TRUE **or** FALSE on the **p99 tail** against the documented band | `results/FINDING-F6-DAY2-DECISIVENESS.md` §2. Day 2 scored TRUE on a p99 CI **435 ms / 375 ms wide** — as wide as the 400 ms band being adjudicated. Neither day-1's FALSE nor day-2's TRUE is established at n = 1,000 |
| **F6-8** | `FALSE` (day 1) | that the per-turn growth estimate is large relative to the documented range | TRUE or FALSE on whether the slope lies in `[165, 750]` | same finding. Day 2's CI `[736.40, 757.54]` overlaps the stated range by **13.6 ms** with 36 % of the CI still above 750; `CI_OVERLAPS` cannot distinguish that from containment |
| **F1-19** | `INCONCLUSIVE` | the **mechanism** observation recorded in its note — a thresholdless Cedar guardrails condition stops at `CREATE_FAILED`, and the same statement with an explicit `.greaterThan(decimal("0.2"))` reaches `ACTIVE` | a verdict on the documented default thresholds. The natural-language authoring path returned `GENERATED` with zero statements, so the 0.2 / 0.4 / 0.2 defaults are **untested, not wrong** | the case record and the annotation in both editions of the v1.4 document |
| **the 20 `INCONCLUSIVE` cases** | `INCONCLUSIVE` | that the study did not establish the claim, and — where a finding says so — that the *instrument* failed rather than the platform | evidence **against** the claim, or grounds for any document amendment | the study's editorial rule, stated in `agentcore_guardrails_best_practices_v1.4.md` §0: "An INCONCLUSIVE verdict is not evidence against a claim, and this version amends nothing on one." `F1-8 F1-10 F1-11 F1-12 F1-13 F1-15 F1-16 F1-17 F1-19 F1-20 F1-26 F1-27 F2-3 F3-11 F5-3a F5-5 F5-7b F5-9 F8-7 F9-3` |
| **F5-4a**, **F5-4b** | `RECORDED` | the observation as recorded, with its own stated scope | a TRUE or a FALSE. `RECORDED` is the state for an observation whose oracle could not adjudicate it | `PREREGISTRATION.yaml`'s verdict vocabulary; register item 20 on why that vocabulary is ours |
| **F9-1** | *no verdict* | that AgentCore exposes no fault-injection surface for policy evaluation, which is why the case is untestable | anything about fail-secure behaviour | its own sealed oracle declares it untestable; `results/CENSUS-NOT-MEASURED.md` |
| **F10-1** | *no verdict* | nothing | anything | unmeasured; the one case of the 92 verdict-eligible with no verdict on disk |

## 2. Restrictions on *what a citation licenses*, not on the verdict

| Population | Citable as a verdict? | Licenses a document amendment? | Why |
|---|---|---|---|
| The **twelve** v1.4 amendments resting on **one** calendar day | yes | **no** — they are already applied and owe a second day retroactively | register item 2. `check_amendment_readiness.py` does not look at them (register item 22), so its exit 0 is not a statement about these twelve |
| Any case whose finding status is `AMENDMENT_DEFERRED` | yes | no, until the `blocked_on` condition is discharged | `check_amendment_readiness.py`; currently `FINDING-F1-15`, `FINDING-F5-7B`, `FINDING-F6-DAY2-DECISIVENESS` |
| **F6-1**, **F6-3**, **F6-4** | yes | yes on the verdict; **but see below on re-running** | they agreed across 2026-08-10 and 2026-08-19 |
| Every **F6** case | yes | yes where the two-day rule is met | **but an F6 replication must be run from the same client and network position.** The estimator is a paired difference of client-measured wall clocks, so an EC2 re-run changes platform *and* network position — the one dimension a replication must hold fixed. A cloud-side F6 re-run is not a replication of F6 |
| **F1-4**, **F1-21** | yes | yes | no claim in `claims/triage.csv` points at either: their propositions are about the service model, not about a document sentence. They cannot be cited as evidence *for a document claim*, because there is no claim they map to |

## 3. Restrictions that are not about cases

- **The verdict taxonomy itself.** `TRUE / FALSE / INCONCLUSIVE / RECORDED` has **no located
  precedent** — a research pass searched 26 primary sources and found none. Define it operationally;
  do **not** present it as standard practice or cite a source for it. Register item 20.
- **Appendix D's eight URLs.** The 2026-08-15 research pass returned two citable figure anchors and
  left censoring, binomial intervals at zero successes, and three-state encoding unsourced. Do not
  cite any of the eight until the scoped verification pass over
  `results/RESEARCH-evidence-presentation-20260815.md` §5 has run.
- **Four research citation anchors are wrong** and are not to be reused until corrected: register
  item 30 names each wrong anchor and its replacement.
- **Anything under `results/phase1/archive/`** is a superseded or set-aside artifact, never a verdict.
  `census.py` excludes the directory by construction. The labels state why each was set aside:
  `__day1_` (replaced by an agreeing day-2), `__day2_indecisive_` (a day-2 that disagreed and was
  therefore **not** allowed to replace day 1), `__withdrawn_`, `__smoke_`, `__asrun_*_defect_`.

## 4. How the F6 day-2 disagreement was resolved, since it is the newest restriction

Three cases disagreed across the two days. The rule applied was **not** "prefer the FALSE": it is that
a disagreement licenses **no change to the published record**, and the published record was day 1. The
day-2 files are retained in full under `results/phase1/archive/F6-{2,5,8}__day2_indecisive_2026-08-19.json`
with their sha256s recorded in the finding, because both days' files carry the same `run_id` and the
archive filename is a label rather than evidence. `census.py` re-derives
**TRUE 46 / FALSE 23 / INCONCLUSIVE 20 / RECORDED 2**, which is what published `main` states; before
the restore it derived TRUE 49 / FALSE 20.

---

<!-- machine
{
  "schema": "grx-citation-policy/1",
  "authoritative_for_tooling": true,
  "note": "The prose above explains each entry; this block is what a build reads so that a restriction is data rather than copy. Every case_id here must exist in results/_census.json, and every restriction must name the artifact that establishes it.",
  "restrictions": [
    {"cases": ["F5-3b"], "verdict_on_disk": "TRUE", "restriction": "NEVER_CITE",
     "citable_as": [], "not_citable_as": ["confirmation", "a TRUE in any count"],
     "reason": "its own every_boundary_transition_was_observed_to_settle guard failed",
     "source": "results/CENSUS-NOT-MEASURED.md; FUTURE-WORK item 12"},
    {"cases": ["F6-2", "F6-5"], "verdict_on_disk": "FALSE", "restriction": "PARTIAL",
     "citable_as": ["p50 and p90 vs the documented 100-500 ms band", "the server-reported latency drop between 2026-08-10 and 2026-08-19"],
     "not_citable_as": ["TRUE on the p99 tail", "FALSE on the p99 tail"],
     "reason": "day-2 p99 CI is 435 ms / 375 ms wide against a 400 ms band; neither day decides the tail",
     "source": "results/FINDING-F6-DAY2-DECISIVENESS.md"},
    {"cases": ["F6-8"], "verdict_on_disk": "FALSE", "restriction": "PARTIAL",
     "citable_as": ["that per-turn growth is large relative to the documented range"],
     "not_citable_as": ["TRUE on slope in [165,750]", "FALSE on slope in [165,750]"],
     "reason": "day-2 slope CI overlaps the stated range by 13.6 ms with 36% of the CI above 750; CI_OVERLAPS cannot distinguish that from containment",
     "source": "results/FINDING-F6-DAY2-DECISIVENESS.md"},
    {"cases": ["F1-19"], "verdict_on_disk": "INCONCLUSIVE", "restriction": "MECHANISM_ONLY",
     "citable_as": ["the mechanism observation: a thresholdless Cedar guardrails condition stops at CREATE_FAILED and an explicit .greaterThan(decimal(\"0.2\")) reaches ACTIVE"],
     "not_citable_as": ["a verdict on the documented default thresholds"],
     "reason": "the natural-language authoring path returned GENERATED with zero statements, so the 0.2/0.4/0.2 defaults are untested rather than wrong",
     "source": "results/phase1/F1-19.json; agentcore_guardrails_best_practices_v1.4.md annotation"},
    {"cases": ["F1-8", "F1-10", "F1-11", "F1-12", "F1-13", "F1-15", "F1-16", "F1-17", "F1-19", "F1-20", "F1-26", "F1-27", "F2-3", "F3-11", "F5-3a", "F5-5", "F5-7b", "F5-9", "F8-7", "F9-3"],
     "verdict_on_disk": "INCONCLUSIVE", "restriction": "NOT_EVIDENCE_AGAINST",
     "citable_as": ["that the study did not establish the claim"],
     "not_citable_as": ["evidence against the claim", "grounds for an amendment"],
     "reason": "the study's editorial rule: an INCONCLUSIVE verdict is not evidence against a claim",
     "source": "agentcore_guardrails_best_practices_v1.4.md section 0"},
    {"cases": ["F5-4a", "F5-4b"], "verdict_on_disk": "RECORDED", "restriction": "NOT_A_VERDICT",
     "citable_as": ["the observation as recorded, with its stated scope"],
     "not_citable_as": ["TRUE", "FALSE"],
     "reason": "RECORDED is the state for an observation whose oracle could not adjudicate it",
     "source": "PREREGISTRATION.yaml verdict vocabulary"},
    {"cases": ["F9-1"], "verdict_on_disk": null, "restriction": "UNTESTABLE",
     "citable_as": ["that AgentCore exposes no fault-injection surface for policy evaluation"],
     "not_citable_as": ["anything about fail-secure behaviour"],
     "reason": "its own sealed oracle declares the case untestable",
     "source": "results/CENSUS-NOT-MEASURED.md"},
    {"cases": ["F10-1"], "verdict_on_disk": null, "restriction": "UNMEASURED",
     "citable_as": [], "not_citable_as": ["anything"],
     "reason": "no verdict on disk; the one outstanding case of the 92 verdict-eligible",
     "source": "census.py"},
    {"cases": ["F1-4", "F1-21"], "verdict_on_disk": "TRUE", "restriction": "NO_CLAIM_MAPPED",
     "citable_as": ["the API-surface fact itself"],
     "not_citable_as": ["evidence for a document claim"],
     "reason": "no row in claims/triage.csv points at either; their propositions are about the service model, not a document sentence",
     "source": "census.py; claims/triage.csv"},
    {"cases": ["F6-1", "F6-2", "F6-3", "F6-4", "F6-5", "F6-6", "F6-7", "F6-8", "F6-9"],
     "verdict_on_disk": null, "restriction": "REPLICATION_POSITION_BOUND",
     "citable_as": ["the verdict"],
     "not_citable_as": ["a replication produced from a different client or network position"],
     "reason": "the estimator is a paired difference of client-measured wall clocks; an EC2 re-run changes platform and network position, the dimension a replication must hold fixed",
     "source": "tools/day2_replicate.py; results/FINDING-F6-DAY2-DECISIVENESS.md section 4"}
  ],
  "non_case_restrictions": [
    {"subject": "the TRUE/FALSE/INCONCLUSIVE/RECORDED taxonomy", "restriction": "DEFINE_DO_NOT_CITE",
     "reason": "no located precedent across 26 primary sources", "source": "FUTURE-WORK item 20"},
    {"subject": "the eight Appendix D URLs", "restriction": "DO_NOT_CITE_UNTIL_VERIFIED",
     "reason": "censoring, binomial intervals at zero successes and three-state encoding came back unsourced",
     "source": "results/RESEARCH-evidence-presentation-20260815.md section 5"},
    {"subject": "four research citation anchors", "restriction": "WRONG_ANCHOR",
     "reason": "each cited a landing page that does not carry the assertion",
     "source": "FUTURE-WORK item 30"},
    {"subject": "results/phase1/archive/**", "restriction": "NOT_A_VERDICT",
     "reason": "superseded or set-aside artifacts; census.py excludes the directory by construction",
     "source": "census.py"}
  ]
}
-->
