#!/usr/bin/env python3
"""The amendment gate: no document claim is amended on a single day's data.

`PREREGISTRATION.yaml` seals this rule under
`validity_checks.reproduction_before_amendment`, alongside `mutation_pairing` and
`restore_verification`. All three are external-validity tests, not paperwork: a result
observed on one day has not excluded "transient state" as an explanation, exactly as a
control whose removal changes nothing has not excluded "the control was never
load-bearing".

**Why this file exists.** The rule was sealed and then enforced by nothing. A grep for
`reproduction_before_amendment`, `calendar` and `replicat` across every .py and .sh
returned the YAML and nothing else, while 358 tests and 8 gates passed. It held only
because I remembered it -- and per feedback_prose_is_not_verified, a rule that depends
on being recalled at the moment of writing is an intention, not a control. That memory
records the lesson being violated one screen below where it was written; this is the
same failure one level up, a rule instead of a number.

**Where the dates come from.** Observation dates are derived from `t_start_utc` in the
evidence records under `evidence/<run_id>/`, NOT from prose in the finding. A date
parsed out of a sentence would be the very defect this project screens the document
for: a number in a string that no check re-derives. A finding declares which run_ids
it rests on; the gate reads those runs' evidence and counts distinct UTC calendar days.

**What counts as needing two days.** Only findings that claim, or claim to be ready
for, a DOCUMENT AMENDMENT. A finding may legitimately be complete on one day if it
confirms the document, reports on our own instruments, or explicitly defers its
amendment -- FINDING-F5-7A does exactly that, and states in §7 why the deferral is a
test rather than a formality. Offline findings (no evidence, $0, deterministic) assert
nothing about live AWS behaviour and are out of scope; requiring two days of them would
make the gate noise, and a gate that fires on things it should not is one people learn
to bypass.

Exit codes: 0 every amendment-bearing finding is replicated; 1 one is not;
2 the gate could not run (per feedback_guard_tool_exit_codes -- a gate that cannot
execute must never be reported as clean).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
EVIDENCE = ROOT / "evidence"

# A finding declares its provenance in a fenced block so the gate does not have to
# parse prose. Keys are deliberately few: status, and the run_ids the claims rest on.
BLOCK_RE = re.compile(r"^<!--\s*provenance\s*\n(.*?)^-->", re.S | re.M)

# Statuses that assert the document has been, or may now be, changed. Matched as whole
# tokens against the declared status, not searched for in the body: "amendment BLOCKED
# pending Day-2 replication" contains the word AMENDED as a substring of nothing, but
# looser matching would eventually catch a sentence that merely discusses amending.
AMENDMENT_STATUSES = {"AMENDED", "READY_TO_AMEND"}
DEFERRED_STATUSES = {"OBSERVATIONS_COMPLETE", "AMENDMENT_DEFERRED"}
NO_AMENDMENT_STATUSES = {"RESOLVED", "CONFIRMS_DOCUMENT", "INTERNAL"}
VALID_STATUSES = AMENDMENT_STATUSES | DEFERRED_STATUSES | NO_AMENDMENT_STATUSES

MIN_DAYS = 2          # the sealed rule: ">= 2 separate calendar days"
MIN_FINDINGS = 5      # a scan that reads almost nothing must not report clean


def fatal(msg: str) -> int:
    print(f"FATAL: {msg}", file=sys.stderr)
    return 2


def observation_days(run_ids: list[str], problems: list[str], src: str) -> set[str]:
    """Distinct UTC calendar days across every evidence record in the given runs.

    Read from `t_start_utc`, which `lib/evidence.py` writes for every call, success or
    exception. Derived rather than declared: a finding cannot assert it was replicated.
    """
    days: set[str] = set()
    for rid in run_ids:
        d = EVIDENCE / rid
        if not d.is_dir():
            problems.append(f"{src}: declares run_id {rid!r}, which is not under "
                            f"evidence/ — the claim rests on records that are absent")
            continue
        recs = [p for p in d.rglob("*.json") if p.name != "environment.json"]
        if not recs:
            problems.append(f"{src}: run {rid} holds no evidence records, so its "
                            f"observation date cannot be established")
            continue
        for p in recs:
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                problems.append(f"{src}: {p.relative_to(ROOT)} is not readable JSON "
                                f"({e}), so its date cannot be counted")
                continue
            ts = rec.get("t_start_utc")
            if not ts:
                # summary.json and similar aggregates carry no per-call timestamp.
                continue
            days.add(str(ts)[:10])
    return days


def check_findings(problems: list[str]) -> int:
    n = 0
    findings = sorted(RESULTS.glob("FINDING-*.md"))
    n += 1
    if len(findings) < MIN_FINDINGS:
        problems.append(f"only {len(findings)} finding(s) found under results/; a scan "
                        f"that reads almost nothing must not report clean")
        return n

    for f in findings:
        src = f.name
        text = f.read_text(encoding="utf-8")
        m = BLOCK_RE.search(text)
        n += 1
        if not m:
            problems.append(
                f"{src}: no `<!-- provenance ... -->` block. Every finding must declare "
                f"its status and the run_ids its claims rest on, or the gate cannot "
                f"tell an amendment from an observation")
            continue

        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            problems.append(f"{src}: the provenance block is not valid JSON ({e})")
            continue

        n += 1
        status = meta.get("status")
        if status not in VALID_STATUSES:
            problems.append(f"{src}: status {status!r} is not one of "
                            f"{sorted(VALID_STATUSES)}")
            continue

        runs = meta.get("evidence_runs")
        n += 1
        if not isinstance(runs, list):
            problems.append(f"{src}: evidence_runs must be a list (use [] for an "
                            f"offline finding), got {type(runs).__name__}")
            continue

        # An offline finding asserts nothing about live AWS behaviour.
        if not runs:
            n += 1
            if status in AMENDMENT_STATUSES:
                problems.append(
                    f"{src}: status {status} with NO evidence runs — a document "
                    f"amendment cannot rest on zero observations")
            continue

        days = observation_days(runs, problems, src)
        n += 1
        if not days:
            problems.append(f"{src}: no observation date could be derived from runs "
                            f"{runs}, so replication cannot be assessed")
            continue

        n += 1
        if status in AMENDMENT_STATUSES and len(days) < MIN_DAYS:
            problems.append(
                f"{src}: status {status} but the evidence spans {len(days)} calendar "
                f"day(s) ({sorted(days)}). The sealed rule requires >= {MIN_DAYS}. A "
                f"single day cannot distinguish a durable observation from a transient "
                f"one — re-run on a later day, do not relax the status")

        # A deferred finding must say what it is waiting for, so the deferral is a
        # decision on the record rather than an omission.
        if status in DEFERRED_STATUSES:
            n += 1
            if not str(meta.get("blocked_on", "")).strip():
                problems.append(f"{src}: status {status} with no `blocked_on` — a "
                                f"deferral with no stated condition is indistinguishable "
                                f"from having forgotten")
    return n


def check_rule_is_still_sealed(problems: list[str]) -> int:
    """The gate must enforce the SEALED rule, not a number chosen here.

    Without this, MIN_DAYS could drift from the pre-registration and the gate would
    keep passing while enforcing something the project never registered.
    """
    n = 0
    import yaml
    pr = yaml.safe_load((ROOT / "PREREGISTRATION.yaml").read_text(encoding="utf-8"))
    n += 1
    vc = (pr.get("validity_checks") or {}).get("reproduction_before_amendment")
    if not vc:
        problems.append("PREREGISTRATION.yaml no longer carries "
                        "validity_checks.reproduction_before_amendment — this gate "
                        "would then be enforcing an unregistered rule")
        return n
    rule = str(vc.get("rule", ""))
    n += 1
    m = re.search(r">=\s*(\d+)\s+separate calendar days", rule)
    if not m:
        problems.append(f"the sealed rule no longer states '>= N separate calendar "
                        f"days'; cannot confirm MIN_DAYS={MIN_DAYS} is what was "
                        f"registered. Rule text: {rule[:120]!r}")
        return n
    n += 1
    if int(m.group(1)) != MIN_DAYS:
        problems.append(f"the sealed rule requires >= {m.group(1)} calendar days but "
                        f"this gate enforces {MIN_DAYS}")
    return n


CHECKS = [
    ("rule_is_sealed", check_rule_is_still_sealed, 3),
    ("findings_declare_and_meet_provenance", check_findings, 12),
]
REQUIRED_CHECKS = {"rule_is_sealed", "findings_declare_and_meet_provenance"}


def main(argv: list[str] | None = None) -> int:
    if not RESULTS.is_dir():
        return fatal("results/ does not exist — the gate cannot run, which is not "
                     "the same as passing")
    if not (ROOT / "PREREGISTRATION.yaml").is_file():
        return fatal("PREREGISTRATION.yaml is missing — the rule being enforced "
                     "cannot be confirmed")

    present = {name for name, _fn, _floor in CHECKS}
    if present != REQUIRED_CHECKS:
        return fatal(f"the CHECKS table does not match REQUIRED_CHECKS: "
                     f"missing={sorted(REQUIRED_CHECKS - present)} "
                     f"unexpected={sorted(present - REQUIRED_CHECKS)}")

    problems: list[str] = []
    starved: list[str] = []
    total = 0
    for name, fn, floor in CHECKS:
        got = fn(problems)
        total += got
        if got < floor:
            starved.append(f"{name} ran {got} assertion(s), expected >= {floor}")

    # Problems first: a check that short-circuits on a real failure yields few
    # assertions for a reason it has already explained (same precedence as
    # corpora/verify_corpora.py).
    if problems:
        print(f"FAILED — {len(problems)} problem(s) in {total} assertions:",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    if starved:
        print("A check that stops asserting is indistinguishable from a check that "
              "passes:", file=sys.stderr)
        for s in starved:
            print(f"  - {s}", file=sys.stderr)
        return 2

    findings = sorted(RESULTS.glob("FINDING-*.md"))
    summary = []
    for f in findings:
        m = BLOCK_RE.search(f.read_text(encoding="utf-8"))
        meta = json.loads(m.group(1))
        runs = meta.get("evidence_runs") or []
        days = sorted(observation_days(runs, [], f.name)) if runs else []
        summary.append((f.name, meta["status"], len(days), days))

    print(f"OK — {total} assertions over {len(findings)} findings")
    for name, status, nd, days in summary:
        where = f"{nd} day(s) {days}" if nd else "offline (no evidence runs)"
        print(f"  {name:<32} {status:<22} {where}")
    print(f"  the sealed rule (>= {MIN_DAYS} calendar days) binds every finding whose "
          f"status is in {sorted(AMENDMENT_STATUSES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
