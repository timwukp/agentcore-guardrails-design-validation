#!/usr/bin/env python3
"""Generate V13_CANDIDATES.md — the amendment register, with every site derived.

Why generated and not written
-----------------------------
The one failure mode this register exists to prevent is amending a claim at one site and
leaving the others standing. The measurement is on the record: remembered wording once
located 6 of 10 sites (`feedback_grep_the_claim_not_the_phrasing`). The document restates
its load-bearing propositions across sections — the default-deny gotcha appears in 9
places across 7 sections, guardrail non-determinism in 8, the billing asymmetry in 7. A
hand-maintained list of "sections to change" is a list of the sections I happened to
think of.

So no candidate lists its own sites. Sites are **derived from `claims/triage.csv`** by
three expanders, in decreasing order of how much they can be trusted:

1. **`test_cases`** — the triage's `cases` column already assigns every claim to the
   experiments that test it. A candidate declaring `test_cases: [F5-7a]` inherits every
   claim F5-7a tests, whether or not I remembered that claim exists. This expander does
   the real work, and it is why the register cannot fall behind the triage: adding a
   claim to a case adds it here.
2. **`merge_groups`** — catches restatements the triage assigned to no case at all. The
   fail-secure group is class X with an empty `cases` column, so expander 1 misses all
   three of its sites.
3. **`claim_ids`** — a named escape hatch for a site neither of the above reaches. Every
   use needs a reason, because a hand-listed site is precisely what this file is built to
   avoid; `claim_id_rationale` is required and checked.

Anchors are deliberately NOT an expander. `s4-1` holds 30 claims and `s9` holds 29, so an
anchor-level site list would tell an editor to review a whole section rather than naming
the sentence — the coarse version of the same defect.

Two properties the generator refuses to write around
----------------------------------------------------
1. Every reference must resolve to at least one triage row. A typo'd case ID or merge
   group would otherwise yield a candidate with an empty site list, which reads as
   *nothing to change here* — a scan that reads zero files reporting clean
   (`feedback_zero_file_scan_is_error`).
2. Every candidate must point at a FINDING file that exists, or declare
   `evidence: none-yet` **and** name the cases that would produce it. A candidate with
   neither is an opinion in a table of measurements.

And one it reports rather than refuses: a claim assigned to a candidate's test case but
carrying a **different** merge group is listed under `related, not amended` instead of
being folded in. Two claims can share an experiment and not share a fate — one test can
confirm one and refute the other.

Exit codes: 0 written · 1 a candidate is malformed · 2 the generator could not run.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRIAGE = ROOT / "claims" / "triage.csv"
RESULTS = ROOT / "results"
OUT = ROOT / "V13_CANDIDATES.md"

# Severity drives ordering and nothing else. Three levels, not five: the distinction that
# matters operationally is "a reader following this gets a broken result" vs "a reader is
# misinformed" vs "a reader is under-informed".
BREAKS_READER = "breaks-the-reader"
MISINFORMS = "misinforms"
UNDERINFORMS = "underinforms"
SEVERITY_ORDER = [BREAKS_READER, MISINFORMS, UNDERINFORMS]

# Every status a candidate may carry, and what it means for the amendment.
STATUSES = {
    "MEASURED_READY": "evidence complete; the amendment can be drafted",
    "BLOCKED_ON_REPLICATION": "observations complete, waiting on a second calendar day",
    "AWAITING_EXPERIMENT": "the experiment that would settle it has not run",
    "PARTIALLY_DISCHARGED": "some sites are covered by our own evidence, some are not",
}

CANDIDATES = [
    {
        "id": "V13-01",
        "title": "§3.1's permit-policy instruction omits `validationMode`, so a reader "
                 "following it verbatim gets a CREATE_FAILED policy",
        "severity": BREAKS_READER,
        "status": "AWAITING_EXPERIMENT",
        "test_cases": ["F1-3"],
        "merge_groups": ["M-default-deny-permit-gotcha"],
        "claim_ids": [],
        "claim_id_rationale": "",
        "evidence": "DC-1, confirmed pre-experimentally from an abandoned engine in this "
                    "account; F1-3 measures it",
        "finding": None,
        "planned_cases": ["F1-3", "F4-1"],
        "doc_says": "Write an explicit baseline permit policy before enabling ENFORCE, "
                    "citing `permit(principal, action, resource is "
                    "AgentCore::Gateway);`.",
        "observed": "That exact statement sits in `CREATE_FAILED` in this account with "
                    "two `Overly Permissive` statusReasons, in a policy engine abandoned "
                    "in June 2026. The AWS getting-started page passes "
                    "`--validation-mode IGNORE_ALL_FINDINGS` on the same statement; the "
                    "document never mentions `validationMode` at all, and "
                    "`PolicyValidationMode` defaults to `FAIL_ON_ANY_FINDINGS`.",
        "proposed": "Add `validationMode` to the instruction and to the §8 checklist, "
                    "with the trade-off stated rather than buried: "
                    "`IGNORE_ALL_FINDINGS` is what makes the documented baseline policy "
                    "creatable, and it also silences the over-permissive warning that "
                    "policy legitimately earns.",
        "note": "The highest-value amendment in the project so far, and the only one "
                "where the document as written cannot be followed to a working result. "
                "Found before any experiment ran, by reading an engine somebody else "
                "abandoned in the account.",
    },
    {
        "id": "V13-02",
        "title": "§4.1 BP#6 and §7.1 prescribe an API surface absent from botocore below "
                 "1.43.32, with a trap window at 1.43.30–.31",
        "severity": BREAKS_READER,
        "status": "MEASURED_READY",
        "test_cases": ["F1-1"],
        "merge_groups": ["M-two-level-log-only"],
        "claim_ids": ["C-s3-1-bullet-009"],
        "claim_id_rationale": "The only place the document names "
                              "`bedrock:InvokeGuardrailChecks` as something to set up. "
                              "The triage assigns it to F1-3/F5-4b (it is an IAM claim), "
                              "so the F1-1 expander does not reach it — but it is where a "
                              "reader on botocore 1.42.79 grants a permission for an "
                              "operation their SDK has no model for, and the version note "
                              "has to be reachable from there.",
        "also_sites": ["C-s4-1-mermaid-005"],
        "also_sites_rationale":
            "The §4.1 decision node `Policy enforcementMode?` — the parameter this "
            "candidate is about, in the flowchart a reader follows. It carries no merge "
            "group (the group holds the two-level LOG_ONLY prose), so the default rule "
            "would file the diagram node as merely related to a finding about the "
            "parameter the node names.",
        "evidence": "F1-1 / F1-2 RESOLVED offline: 14 wheels probed, monotonicity "
                    "verified for all three predicates",
        "finding": "FINDING-F1-1.md",
        "doc_says": "Configure the engine `mode` and each policy's `enforcementMode`; "
                    "author Cedar bodies at `definition.policy`; call "
                    "`InvokeGuardrailChecks`.",
        "observed": "`CreatePolicy.enforcementMode` and `definition.policy` "
                    "(`PolicyStatement`) first appear at botocore **1.43.32**. "
                    "`bedrock-runtime.InvokeGuardrailChecks` first appears at "
                    "**1.43.30**. Monotonicity was verified rather than assumed. The "
                    "document states no minimum SDK version, and the bundled AWS CLI v2 "
                    "exposes no policy-engine subcommands at all.",
        "proposed": "State `botocore >= 1.43.32` (equivalently boto3 >= 1.43.32) as a "
                    "prerequisite, and name the **1.43.30–.31 window** explicitly: those "
                    "two releases expose `InvokeGuardrailChecks` *without* "
                    "`enforcementMode`, so a reader pinned there can build half of §4's "
                    "truth table and conclude the other half is unsupported. Note that "
                    "Python/boto3 is required because the CLI does not carry the "
                    "surface.",
        "note": "A version floor is not a stylistic footnote here. The failure it "
                "prevents is silent: an absent parameter is not rejected by botocore, it "
                "is missing from the model, so the call succeeds while doing something "
                "other than what the reader asked for. Nothing else in this finding "
                "amends the document — AWS's docs were right and the installed SDK was "
                "old.",
    },
    {
        "id": "V13-03",
        "title": "§4.5.3's PrivateLink matrix marks Evaluations and Optimization "
                 "unsupported; AWS's live page now marks both Supported",
        "severity": MISINFORMS,
        "status": "MEASURED_READY",
        "test_cases": ["F5-7a"],
        "merge_groups": ["M-optimization-no-privatelink"],
        "claim_ids": ["C-s4-5-3-thead-001"],
        "claim_id_rationale": "The table header `Service || Data plane || Control plane` "
                              "is class D with no case and no merge group, so no expander "
                              "reaches it — yet it carries the mislabelling the amendment "
                              "names: the rows list **primitives** while PrivateLink "
                              "attaches to **endpoint services**, and F5-7a measured that "
                              "mapping to be many-to-one (three endpoint services across "
                              "the six tabulated primitives). Correcting the marks and "
                              "leaving the header would preserve the category error.",
        "also_sites": ["C-s4-5-3-prose-001", "C-s4-5-3-trow-001"],
        "also_sites_rationale":
            "The rest of the same table. `C-s4-5-3-prose-001` tells the reader to *check "
            "coverage BEFORE designing* — the sentence the amendment rewrites into a dated "
            "pointer at the live AWS table; amending the rows and leaving their "
            "introduction unchanged would leave the matrix reading as current. "
            "`C-s4-5-3-trow-001` is the ✅/✅ row for the six other primitives, and it is a "
            "site for the same reason: F5-7a found only three `*bedrock-agentcore*` "
            "endpoint services, so a row asserting per-primitive data-plane support for "
            "six named primitives cannot be left standing beside a corrected header that "
            "says the mapping is many-to-one.",
        "evidence": "F5-7a, two instruments — ec2:DescribeVpcEndpointServices across 8 "
                    "regions, and the AWS page live plus 8 Internet Archive snapshots — "
                    "replicated on 2026-08-09 and 2026-08-10 (75 fields, 0 disagreements)",
        "finding": "FINDING-F5-7A.md",
        "doc_says": "Evaluations has no PrivateLink data-plane support; Optimization has "
                    "none on either plane. Sourced from Accelerator v2.9.",
        "observed": "Five dated snapshots (2026-04-12 → 07-14) agree with the document: "
                    "`Evaluations · Not yet supported`. The live page reads `Evaluations "
                    "and Optimizations · Supported · Supported`, on **both** 2026-08-09 "
                    "and 2026-08-10. So AWS behaviour **changed** for Evaluations; for "
                    "Optimization the document is refuted with the change date "
                    "**undetermined**, because the archived pages were silent about "
                    "Optimization rather than contradicting it. Separately, the three "
                    "endpoint services exist in 8 regions including ones the document "
                    "lists as unsupported — a limitation of this instrument, recorded as "
                    "one.",
        "proposed": "Replace both marks with a **dated** statement that AWS *documents* "
                    "support — not that support is functionally present, which no "
                    "read-only instrument establishes — plus a pointer to the live AWS "
                    "table, and record the change in `AWS-BEHAVIOR-CHANGES.md` so a later "
                    "reader can tell an expired claim from one that was always wrong. "
                    "Also fix the column header: it reads `Service` while the rows name "
                    "primitives, and PrivateLink attaches to endpoint services — a "
                    "many-to-one mapping the matrix hides.",
        "note": "Was blocked by design, and the block was lifted by evidence rather than "
                "by relaxing the rule. §7's alternative-explanation register listed 'the "
                "live page is a stale or A/B-tested CDN variant' as NOT excluded, because "
                "one read cannot separate a durable change from a transient publication "
                "state; `07a_compare_runs.py` compared 75 fields across the two days and "
                "found 0 disagreements. The first attempt at day 2 was caught as a "
                "same-day repeat — the local calendar had rolled to the 10th while UTC "
                "was still 2026-08-09T16:20. What replication does NOT establish is that "
                "the service matches its documentation; that is F5-7b, and the proposed "
                "wording above is scoped to the claim the evidence supports.",
    },
    {
        "id": "V13-04",
        "title": "§9's Hop #4 label asserts `fail-secure` as a blanket property, and "
                 "§3.3 BP#4 concedes the opposite in the same document",
        "severity": MISINFORMS,
        "status": "AWAITING_EXPERIMENT",
        "test_cases": [],
        "merge_groups": ["M-fail-secure-timeout-deny"],
        "claim_ids": [],
        "claim_id_rationale": "",
        "evidence": "none-yet",
        "finding": None,
        "planned_cases": ["F5-4a", "F5-4b", "F9-1"],
        "doc_says": "Hop #4 is labelled `fail-secure`, and §3.1/§4.1 state that policy "
                    "evaluation timeouts result in an automatic DENY, cited to the "
                    "Accelerator.",
        "observed": "Not yet measured. What is already known: only three failure modes "
                    "are inducible with the available surfaces — an unresolvable context "
                    "path (F5-4a), a guardrail evaluation that cannot run because the "
                    "execution role lacks `bedrock:InvokeGuardrailChecks` (F5-4b), and an "
                    "engine detached mid-flight. A real service-side evaluation timeout "
                    "has no fault-injection surface and is in the exclusion register, "
                    "which is why all three claims in this merge group are class **X** "
                    "with no test case. Meanwhile §3.3 BP#4 states that AWS does not "
                    "document fail-open vs fail-closed — so the document asserts and "
                    "concedes the same property.",
        "proposed": "Scope the label to the failure modes actually measured and make §9 "
                    "agree with §3.3 BP#4. A universal claim about failure behaviour "
                    "cannot rest on three inducible modes; saying which three, and that "
                    "the timeout case is untestable from outside AWS, is the stronger "
                    "statement.",
        "note": "The internal inconsistency is a defect independent of what F5-4 "
                "measures: the two sections cannot both be right as written. This is also "
                "the one candidate whose sites come entirely from the merge-group "
                "expander — the case expander finds nothing, because the triage assigned "
                "these claims to no experiment.",
    },
    {
        "id": "V13-05",
        "title": "§7.1 prescribes building the confusion matrix from LOG_ONLY telemetry; "
                 "whether that reconstruction is possible is untested",
        "severity": MISINFORMS,
        "status": "AWAITING_EXPERIMENT",
        "test_cases": ["F3-10"],
        "merge_groups": [],
        "claim_ids": [],
        "claim_id_rationale": "",
        "evidence": "none-yet",
        "finding": None,
        "planned_cases": ["F3-10", "F3-9"],
        "doc_says": "Run a golden set through a LOG_ONLY engine, then label results and "
                    "use the confidence scores in the logs to build a confusion matrix "
                    "comparing precision and recall across candidate thresholds.",
        "observed": "Not yet measured. F3-10 attempts the reconstruction twice: using "
                    "only CloudWatch metrics, then only `aws/spans`. Whether per-request "
                    "score-to-label linkage survives 1-minute metric aggregation is the "
                    "experiment, not an assumption of it. If it does not, a reader "
                    "following §7.1 cannot compute precision at all.",
        "proposed": "Name the instrument the reconstruction actually requires (spans, not "
                    "metrics) or, if neither suffices, replace the prescription with one "
                    "that can be carried out.",
        "note": "The only candidate where the document's *workflow* is under test rather "
                "than a statement of fact. A prescription that cannot be executed is a "
                "defect even when every fact around it is true.",
    },
    {
        "id": "V13-06",
        "title": "§6.1's per-hop latency table is labelled ILLUSTRATIVE in a document "
                 "that otherwise reads as authoritative",
        "severity": MISINFORMS,
        "status": "AWAITING_EXPERIMENT",
        "test_cases": ["F6-1", "F6-2", "F6-3", "F6-4", "F6-5", "F6-6", "F6-7", "F6-8"],
        "merge_groups": ["M-latency-hop1", "M-latency-hop2", "M-latency-hop3",
                         "M-latency-hop4", "M-latency-hop5", "M-latency-hop6"],
        "claim_ids": ["C-s6-1-quote-001", "C-s6-1-thead-001"],
        "claim_id_rationale": "The ILLUSTRATIVE disclaimer and the table header are "
                              "class D (definitional) with no test case and no merge "
                              "group, so neither expander reaches them. But replacing "
                              "the table means rewriting the sentence that calls it "
                              "illustrative, and leaving that disclaimer standing beside "
                              "measured quantiles would be worse than the current state.",
        "also_sites": ["C-s6-1-trow-007", "C-s9-mermaid-012-c", "C-s6-1-prose-002",
                       "C-s4-2-bullet-005"],
        "also_sites_rationale":
            "Four rows the latency cases reach but that the triage gave no merge group, "
            "and that the amendment cannot leave alone. `C-s6-1-trow-007` is the §6.1 "
            "table's own **Total ~800ms–31s+** row: it is arithmetic over the six hop "
            "rows above it, so replacing those rows with measured quantiles and leaving "
            "the total as an estimate would print a table that does not add up — the "
            "`feedback_label_must_match_computation` failure, in the document this "
            "project exists to correct. `C-s6-1-prose-002` and `C-s4-2-bullet-005` state "
            "the derived per-additional-tool-call cost (165–750ms, N × "
            "guardrail_evaluation), which F6-8's regression of Duration on N measures "
            "directly. `C-s9-mermaid-012-c` is the §9 restatement of that same "
            "per-N repetition.",
        "evidence": "none-yet",
        "finding": None,
        "planned_cases": ["F6-1 … F6-9"],
        "doc_says": "50–200ms, 100–500ms, 500ms–30s, 5–50ms, 50–200ms × N, 100–500ms, a "
                    "~800ms–31s+ total, and a derived 165–750ms per additional tool "
                    "invocation.",
        "observed": "Not yet measured. Phase 6 runs n=1000 per arm, paired and "
                    "interleaved, dealt across two nights. Every row is replaced by "
                    "measured p50/p90/p99 with distribution-free CIs, n, and instrument. "
                    "The additivity model `Duration_gw = GuardrailLatency + "
                    "TargetExecutionTime + ε` is itself under test: a negative residual "
                    "would mean the hops overlap and would falsify the model underlying "
                    "§6.1, §6.3 **and** §6.4 together.",
        "proposed": "Replace the table with measured quantiles, keeping the ILLUSTRATIVE "
                    "label only on rows that remain unmeasured and naming which. If "
                    "additivity is falsified, that is a structural amendment to three "
                    "sections, not a number correction to one.",
        "note": "The headline deliverable, and the candidate most likely to turn into a "
                "structural finding rather than a table of numbers.",
    },
    {
        "id": "V13-07",
        "title": "§6.4's alarm thresholds have a floor set by metric publish lag that the "
                 "document never states",
        "severity": UNDERINFORMS,
        "status": "AWAITING_EXPERIMENT",
        "test_cases": ["F7-6"],
        "merge_groups": [],
        "claim_ids": [],
        "claim_id_rationale": "",
        "evidence": "none-yet",
        "finding": None,
        "planned_cases": ["F7-6", "F7-1"],
        "doc_says": "Alarm on latency > P99 + 50%, block rate > 20% in 5 minutes, and "
                    "end-to-end duration over an SLA threshold.",
        "observed": "Not yet measured. F7-6 measures publish lag at n=30 (p50/p90/max). "
                    "Every alarm period in §6.4 is bounded below by that lag and the "
                    "document states no such bound, so a reader can configure an alarm "
                    "that cannot fire in time by construction.",
        "proposed": "State the measured publish lag and the minimum viable alarm period "
                    "derived from it.",
        "note": "The amendment supplies a number the document is missing rather than "
                "correcting one it gets wrong — hence `underinforms`, not `misinforms`.",
    },
    {
        "id": "V13-08",
        "title": "§4.4 and §4.5 cite the NDA Accelerator, which blocks external "
                 "distribution until each citation is replaced or downgraded",
        "severity": UNDERINFORMS,
        "status": "PARTIALLY_DISCHARGED",
        "test_cases": ["F5-7a"],
        "merge_groups": ["M-gateway-only-path"],
        "claim_ids": [],
        "claim_id_rationale": "",
        "evidence": "F5-7a covers the PrivateLink matrix with our own evidence; F5-8 "
                    "would cover the microVM credential premise",
        "finding": "FINDING-F5-7A.md",
        "planned_cases": ["F5-7a", "F5-8"],
        "doc_says": "Policies cannot be bypassed; the Gateway is the only path to tools; "
                    "PrivateLink coverage is as tabulated — all sourced from Accelerator "
                    "v2.9.",
        "observed": "F5-7a replaces the PrivateLink matrix citation with "
                    "`DescribeVpcEndpointServices` evidence across 8 regions plus a dated "
                    "documentation history. F5-8 would replace the microVM "
                    "credential-isolation premise with a public `sts:GetCallerIdentity` "
                    "call from inside a tool session. The non-bypassability claim is a "
                    "universal quantifier and cannot be proven at all — only the five "
                    "enumerated routes can be falsified.",
        "proposed": "Cite the experiment where our own evidence covers the claim; "
                    "downgrade to \"confirm with your AWS account team\" everywhere else. "
                    "State plainly that failure to bypass via five routes is not proof "
                    "that no sixth route exists.",
        "note": "The only candidate driven by distribution rights rather than truth, and "
                "a precondition for release rather than an improvement to it. Listed here "
                "so it cannot be discovered at the end, which is when release gates "
                "usually are.",
    },
    {
        "id": "V13-09",
        "title": "§3.2 does not separate `ApplyGuardrail` from `InvokeGuardrailChecks`, "
                 "which AWS meters as distinct paths",
        "severity": UNDERINFORMS,
        "status": "AWAITING_EXPERIMENT",
        "test_cases": ["F5-6"],
        "merge_groups": ["M-prompt-attack-input-tagging"],
        "claim_ids": [],
        "claim_id_rationale": "",
        "evidence": "FINDING-P0-PRICING, INTERNAL — billing-side, raises the prior and "
                    "amends nothing on its own; F5-6 measures behaviour",
        "finding": "FINDING-P0-PRICING.md",
        "planned_cases": ["F5-6"],
        "doc_says": "Prompt-attack detection requires input tagging on InvokeModel; "
                    "Converse requires `guardContent` on the block to be evaluated; "
                    "tagging scope is limited to the tagged block.",
        "observed": "DC-2: an in-house run recorded PROMPT_ATTACK firing without input "
                    "tags 5/5, but n=5 gives a Wilson interval of about [56%, 100%] and "
                    "cannot amend a documented AWS statement. Separately, the Pricing API "
                    "meters `GuardrailChecks-ContentFilterCheck` at $0.00007 per text "
                    "unit against `Guardrail-ContentPolicy` at $0.00015 — disjoint usage "
                    "types at different unit prices, so the two APIs are not two front "
                    "doors onto one evaluator.",
        "proposed": "Say which API each tagging requirement applies to. Pending F5-6's "
                    "4-arm measurement at 60 attacks + 60 benign per arm, with per-arm "
                    "Wilson intervals and pairwise McNemar.",
        "note": "Separate metering does not entail different detection behaviour — two "
                "evaluators can be billed differently and agree on every input in the "
                "corpus. The pricing observation raises the prior that the document is "
                "right about one API and wrong about the other, which is exactly what "
                "F5-6 was pre-registered to test.",
    },
]


def fatal(msg: str) -> int:
    print(f"FATAL: {msg}", file=sys.stderr)
    return 2


def load_triage() -> list[dict]:
    with TRIAGE.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def cases_of(row: dict) -> set[str]:
    return set((row.get("cases") or "").split())


def expand(cand: dict, rows: list[dict],
           problems: list[str]) -> tuple[list[dict], list[dict]]:
    """Resolve a candidate to (sites, related).

    `sites` are claims to amend. `related` are claims that share a declared test case but
    carry a *different* merge group — reported separately rather than folded in, because
    sharing an experiment does not mean sharing a fate.
    """
    hits: dict[str, tuple[dict, str]] = {}

    for case in cand["test_cases"]:
        members = [r for r in rows if case in cases_of(r)]
        if not members:
            problems.append(
                f"{cand['id']}: test case {case!r} is assigned to no triage row. Either "
                f"the case ID is wrong or the triage never mapped a claim to it; either "
                f"way this candidate lists sites it did not derive")
        for r in members:
            hits.setdefault(r["claim_id"], (r, f"case {case}"))

    for mg in cand["merge_groups"]:
        members = [r for r in rows if r["merge_group"] == mg]
        if not members:
            problems.append(
                f"{cand['id']}: merge group {mg!r} matches no triage row — the candidate "
                f"would silently list fewer sites than the claim has")
        for r in members:
            # A merge-group hit is stronger evidence of "this is the same claim" than a
            # shared test case, so it overwrites the recorded reason.
            hits[r["claim_id"]] = (r, f"merge group {mg}")

    named: set[str] = set()
    known = {r["claim_id"] for r in rows}
    for cid in cand["claim_ids"]:
        if cid not in known:
            problems.append(f"{cand['id']}: claim id {cid!r} is not in the triage")
            continue
        r = next(x for x in rows if x["claim_id"] == cid)
        hits.setdefault(cid, (r, "named explicitly"))
        named.add(cid)

    own_groups = set(cand["merge_groups"])
    # An explicitly named claim id is always a site. It has to be: the escape hatch exists
    # for claims *no expander reaches*, which in practice means claims with no merge group
    # — so subjecting them to the merge-group split would nullify the hatch for every
    # candidate that declares a group. That is not hypothetical; V13-06 named the §6.1
    # ILLUSTRATIVE disclaimer and the table header with a written rationale, and both were
    # demoted to "related" on the first run of this rule.
    promoted = set(cand.get("also_sites") or []) | named

    # A promotion may only *reclassify* something the expanders already found. Allowing a
    # promotion to introduce a claim id would rebuild the hand-written site list this file
    # exists to replace, one exception at a time. (`claim_ids` is the sanctioned door for
    # that, and it demands its own rationale.)
    declared = set(cand.get("also_sites") or [])
    for cid in sorted(declared - set(hits)):
        problems.append(
            f"{cand['id']}: also_sites names {cid!r}, which none of this candidate's "
            f"expanders reach. Promotion can only move a derived claim from 'related' to "
            f"'sites'; introducing one here would make the site list hand-written again — "
            f"declare the test case or merge group that reaches it, or list it under "
            f"claim_ids with a rationale")
    for cid in sorted(declared & named):
        problems.append(
            f"{cand['id']}: {cid!r} is in both claim_ids and also_sites. A named claim is "
            f"already a site, so the promotion is dead configuration that reads as a "
            f"second safeguard")
    if declared and not cand.get("also_sites_rationale", "").strip():
        problems.append(
            f"{cand['id']}: promotes {len(declared)} claim(s) with no "
            f"also_sites_rationale. The default is that a claim outside the candidate's "
            f"merge groups is related-not-amended, so overriding it needs a reason")

    sites, related = [], []
    for r, why in hits.values():
        mg = r["merge_group"]
        # The split rule, and why it is this and not something cleverer.
        #
        # A candidate that declares merge groups is making a claim about *which
        # proposition* it amends, and a case-derived hit outside those groups is a claim
        # the same experiment happens to test. V13-01 showed why this matters: F1-3
        # touches 19 claims, but 9 of them are §3.1 bullets like "Prompt Attack detection
        # (JAILBREAK, PROMPT_INJECTION, PROMPT_LEAKAGE)" — tested by the same experiment,
        # nothing to do with the missing `validationMode`. Amending those would be
        # editing sentences nobody decided to edit.
        #
        # But no derived rule gets this right on its own. §6.1's "Total ~800ms–31s+" row
        # carries no merge group and is unmistakably part of the latency table V13-06
        # replaces. So promotion is an explicit, *checked* decision: a claim id in
        # `also_sites` must already appear in the derivation (see check()), which means
        # the author can promote a derived claim but cannot invent a site.
        #
        # A candidate that declares no merge groups has no basis on which to call
        # anything unrelated, so its whole case expansion is sites — that is V13-05,
        # where F3-10's ten claims *are* the §7.1 workflow.
        if own_groups and r["claim_id"] not in promoted and mg not in own_groups:
            related.append({**r, "_why": why})
        else:
            if r["claim_id"] in promoted and mg not in own_groups:
                why += " · promoted"
            sites.append({**r, "_why": why})

    def key(r: dict) -> tuple[str, str]:
        return (r["anchor"], r["claim_id"])

    return sorted(sites, key=key), sorted(related, key=key)


def check(cand: dict, sites: list[dict], problems: list[str]) -> None:
    if cand["severity"] not in SEVERITY_ORDER:
        problems.append(f"{cand['id']}: unknown severity {cand['severity']!r}")
    if cand["status"] not in STATUSES:
        problems.append(f"{cand['id']}: unknown status {cand['status']!r}; add it to "
                        f"STATUSES with what it means for the amendment")
    if not sites:
        problems.append(f"{cand['id']}: resolves to zero sites, so amending it would "
                        f"change nothing in the document")
    if not (cand["test_cases"] or cand["merge_groups"] or cand["claim_ids"]):
        problems.append(f"{cand['id']}: declares no test case, merge group or claim id, "
                        f"so its site list is not derived from anything")
    if cand["claim_ids"] and not cand["claim_id_rationale"].strip():
        problems.append(f"{cand['id']}: names {len(cand['claim_ids'])} claim id(s) "
                        f"explicitly with no rationale. A hand-listed site is what this "
                        f"register exists to avoid, so each one needs a reason why "
                        f"neither expander reaches it")

    if cand["finding"]:
        if not (RESULTS / cand["finding"]).is_file():
            problems.append(f"{cand['id']}: names finding {cand['finding']!r}, which does "
                            f"not exist under results/")
    elif cand["evidence"] != "none-yet" and "DC-" not in cand["evidence"]:
        problems.append(f"{cand['id']}: claims evidence {cand['evidence']!r} but names no "
                        f"finding file")

    if not cand.get("planned_cases") and cand["evidence"] == "none-yet":
        problems.append(f"{cand['id']}: has no evidence and names no planned case — a "
                        f"candidate with neither is an opinion in a table of measurements")
    if cand["status"] == "MEASURED_READY" and not cand["finding"]:
        problems.append(f"{cand['id']}: status MEASURED_READY with no finding file")
    if cand["status"] == "BLOCKED_ON_REPLICATION" and not cand["finding"]:
        problems.append(f"{cand['id']}: status BLOCKED_ON_REPLICATION with no finding "
                        f"file; there is nothing to block on")

    for f in ("doc_says", "observed", "proposed"):
        if not str(cand.get(f, "")).strip():
            problems.append(f"{cand['id']}: {f} is empty")


def site_table(rows: list[dict]) -> list[str]:
    L = ["| Claim ID | Anchor | Class | Line | Derived from | Text |",
         "|:--|:--|:--:|--:|:--|:--|"]
    for r in rows:
        text = re.sub(r"\s+", " ", r["text"]).strip()
        if len(text) > 95:
            text = text[:92] + "…"
        text = text.replace("|", "\\|")
        canon = " ᶜ" if r.get("canonical") == "yes" else ""
        L.append(f"| `{r['claim_id']}`{canon} | {r['anchor']} | {r['cls']} | "
                 f"{r['doc_line']} | {r['_why']} | {text} |")
    return L


def render(resolved: list[tuple[dict, list[dict], list[dict]]]) -> str:
    n_sites = len({r["claim_id"] for _c, s, _rel in resolved for r in s})
    by_sev = {s: [c for c, _s, _r in resolved if c["severity"] == s]
              for s in SEVERITY_ORDER}

    L: list[str] = []
    A = L.append
    A("# V13_CANDIDATES.md — the amendment register for v1.3")
    A("")
    A("*Generated by `build_v13_candidates.py` from `claims/triage.csv`. Do not edit by "
      "hand — no candidate lists its own sites, and a site typed into this file would be "
      "exactly the unverified prose the project screens the document for.*")
    A("")
    A(f"**{len(resolved)} candidates** over **{n_sites} distinct document sites**. "
      f"{len(by_sev[BREAKS_READER])} break a reader who follows the document verbatim; "
      f"{len(by_sev[MISINFORMS])} state something false or unsupported; "
      f"{len(by_sev[UNDERINFORMS])} omit something load-bearing.")
    A("")
    A("Nothing here has been applied. Amendment is Phase 9, and every candidate is gated "
      "on `check_amendment_readiness.py`: two separate calendar days of observation "
      "before any claim in v1.2 changes. Both `.md` and `.zh-TW.md` are amended in the "
      "same change.")
    A("")
    A("## How the site lists are derived")
    A("")
    A("The document restates its load-bearing propositions across sections: the "
      "default-deny gotcha appears in **9 places across 7 sections**, guardrail "
      "non-determinism in 8, the billing asymmetry in 7. A claim amended at one site and "
      "left standing at eight others is **not amended** — and the measured version of "
      "that mistake is on the record: remembered wording once located 6 of 10 sites.")
    A("")
    A("So candidates declare *what they are about* and the sites are expanded from the "
      "triage:")
    A("")
    A("| Expander | What it catches | Why it is trusted this much |")
    A("|:--|:--|:--|")
    A("| `test_cases` | every claim the triage assigns to that experiment | the triage's "
      "`cases` column is maintained by the coverage gate, so this cannot fall behind the "
      "triage |")
    A("| `merge_groups` | restatements the triage assigned to **no** case | V13-04's "
      "three sites are class X with an empty `cases` column; the case expander finds none "
      "of them |")
    A("| `claim_ids` | a site neither expander reaches | a hand-listed site is the thing "
      "this file exists to avoid, so each one carries a required rationale |")
    A("")
    A("Anchors are deliberately not an expander: `s4-1` holds 30 claims and `s9` holds "
      "29, so an anchor-level list would say *review this section* rather than naming the "
      "sentence.")
    A("")
    A("A claim that shares a candidate's test case but carries a **different** merge "
      "group is listed under *related, not amended* rather than folded in. One experiment "
      "can confirm one claim and refute another, and collapsing that distinction is how a "
      "register starts amending things nobody decided to amend.")
    A("")
    A("ᶜ marks the canonical claim of a merge group.")
    A("")
    A("## Status summary")
    A("")
    A("| ID | Severity | Sites | Status | Evidence |")
    A("|:--|:--|--:|:--|:--|")
    for cand, sites, _rel in resolved:
        ev = (f"[`{cand['finding']}`](results/{cand['finding']})"
              if cand["finding"] else "— not yet")
        A(f"| [{cand['id']}](#{cand['id'].lower()}) | {cand['severity']} | {len(sites)} | "
          f"`{cand['status']}` | {ev} |")
    A("")
    A("| Status | Meaning |")
    A("|:--|:--|")
    for k in sorted(STATUSES):
        A(f"| `{k}` | {STATUSES[k]} |")
    A("")

    for cand, sites, related in resolved:
        A("---")
        A("")
        A(f"## {cand['id']}")
        A("")
        A(f"**{cand['title']}**")
        A("")
        planned = ", ".join(cand.get("planned_cases") or cand["test_cases"]) or "—"
        A(f"**Severity** {cand['severity']} · **Status** `{cand['status']}` · "
          f"**Test case(s)** {planned}")
        A("")
        A(f"**Evidence.** {cand['evidence']}"
          + (f" — [`results/{cand['finding']}`](results/{cand['finding']})"
             if cand["finding"] else ""))
        A("")
        A(f"**What v1.2 says.** {cand['doc_says']}")
        A("")
        A(f"**What we observed.** {cand['observed']}")
        A("")
        A(f"**Proposed amendment.** {cand['proposed']}")
        A("")
        if cand.get("note"):
            A(f"> {cand['note']}")
            A("")
        A(f"**Sites to amend: {len(sites)}.**")
        A("")
        L.extend(site_table(sites))
        A("")
        if cand["claim_ids"]:
            A(f"*Why {len(cand['claim_ids'])} site(s) are named explicitly:* "
              f"{cand['claim_id_rationale']}")
            A("")
        if related:
            A(f"**Related, not amended: {len(related)}.** These share a test case with "
              f"this candidate but belong to a different merge group, so the experiment "
              f"bears on them without this amendment covering them.")
            A("")
            L.extend(site_table(related))
            A("")

    A("---")
    A("")
    A("## Reproduction")
    A("")
    A("```bash")
    A("python3 build_v13_candidates.py     # regenerate; rc=1 if a candidate is malformed")
    A("python3 -m pytest claims/tests/test_v13_candidates.py -q")
    A("```")
    A("")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    if not TRIAGE.is_file():
        return fatal("claims/triage.csv is missing — sites cannot be derived, and a "
                     "register with no sites is worse than no register")
    rows = load_triage()
    if len(rows) < 500:
        return fatal(f"triage.csv holds {len(rows)} rows; expected the full 546. A "
                     f"truncated triage would silently shrink every site list while the "
                     f"register still reported a count")

    problems: list[str] = []
    resolved = []
    for cand in CANDIDATES:
        sites, related = expand(cand, rows, problems)
        check(cand, sites, problems)
        resolved.append((cand, sites, related))
    resolved.sort(key=lambda t: (SEVERITY_ORDER.index(t[0]["severity"]), t[0]["id"]))

    if problems:
        print(f"MALFORMED — {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    OUT.write_text(render(resolved), encoding="utf-8")
    distinct = len({r["claim_id"] for _c, s, _r in resolved for r in s})
    print(f"wrote {OUT.name}: {len(resolved)} candidates, {distinct} distinct sites")
    for cand, sites, related in resolved:
        extra = f" (+{len(related)} related)" if related else ""
        print(f"  {cand['id']}  {cand['severity']:<18} {len(sites):>2} site(s){extra:<16}"
              f"  {cand['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
