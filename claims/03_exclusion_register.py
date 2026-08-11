#!/usr/bin/env python3
"""Generate EXCLUSION_REGISTER.md from triage.csv. $0, offline.

Why this file exists
--------------------
The plan states it plainly: "an accurate exclusion register is more credible than
a false 100%." A validation report claiming complete coverage of 546 claims would
be a lie — 161 of them (29.5%) get no experiment. What makes the project honest is
not the coverage percentage but that every one of those 161 is *named*, with the
reason written down and, where one exists, the nearest proxy that IS run.

The register is GENERATED, never hand-maintained. A hand-written register drifts
the moment a claim is reclassified, and it drifts silently in the direction that
flatters us — the row that became untestable is the row nobody remembers to add.
Regenerating from triage.csv makes drift impossible by construction.

Three distinct kinds of "not tested", which the register must not blur:

  D  definitional — the document's own framework (hop numbering, diagram labels,
     change log). NOT a gap. A naming convention has no truth value, and saying
     so is the correct scientific answer rather than manufacturing a test.
  N  normative — value judgements ("use aggressive thresholds only for high-risk
     categories"). No experiment can falsify a recommendation. These are the
     rows most at risk of being silently scored "passed", which is exactly what
     the class exists to prevent.
  X  excluded-but-testable-in-principle — a real gap. Each carries a reason and
     a remedy. These are the rows a reviewer should attack.

Self-checks (this script exits non-zero rather than emitting a register it cannot
stand behind):
  * every X row has a reason AND a remedy sentence
  * every case ID mentioned in any reason exists in the case registry — a reason
    that points at a proxy experiment must point at a REAL one, or the register
    offers false comfort
  * the class counts reconcile to the triage row count exactly

Usage: python3 03_exclusion_register.py [--check]
       --check regenerates and diffs against the committed file.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import triage_rules as R  # noqa: E402

TRIAGE = HERE / "triage.csv"
OUT = HERE.parent / "EXCLUSION_REGISTER.md"

TESTED = ("E", "S", "C", "O")
UNTESTED = ("X", "N", "D")

CLASS_LABEL = {
    "E": "empirical-deterministic",
    "S": "statistical",
    "C": "config-surface / API-truth",
    "O": "observability-truth",
    "D": "definitional",
    "N": "normative",
    "X": "excluded, testable in principle",
}

# A remedy is the sentence that tells a reviewer what would have to change for the
# claim to become testable. Without it, "excluded" is indistinguishable from
# "we did not feel like it".
REMEDY_RE = re.compile(r"Remedy:\s*(.+)", re.S)
CASE_RE = re.compile(r"\bF\d{1,2}-\d{1,2}[a-z]?\b")

# Anchors come in two shapes: section slugs ('s4-5-2' -> §4.5.2, 'appC' -> App. C)
# and heading slugs for untitled tables ('agentcore-policy-metrics'). Printing the
# raw slug with a '§' in front gives '§s4-5-2', which is not a section number a
# reader can look up.
_SECTION_RE = re.compile(r"^s(\d+(?:-\d+)*)$")
_APP_RE = re.compile(r"^app([A-Z])$")


def fmt_anchor(anchor: str) -> str:
    m = _SECTION_RE.match(anchor)
    if m:
        return "§" + m.group(1).replace("-", ".")
    m = _APP_RE.match(anchor)
    if m:
        return f"Appendix {m.group(1)}"
    return f"`{anchor}`"


def load() -> list[dict]:
    with TRIAGE.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def check(rows: list[dict]) -> list[str]:
    problems: list[str] = []

    for r in rows:
        if r["cls"] != "X":
            continue
        cid, reason = r["claim_id"], r["exclusion_reason"]
        if not reason.strip():
            problems.append(f"{cid}: class X with no exclusion reason")
            continue
        if not REMEDY_RE.search(reason):
            problems.append(
                f"{cid}: class X reason states no 'Remedy:' — a reader cannot tell "
                f"what would have to change for this claim to become testable")

    # A reason naming F5-4b as a proxy must name a case that exists. This is the
    # check that stops the register from offering false comfort — and it earned its
    # keep on the first run by catching a reason that cited F5-3c, an arm the plan
    # explicitly DECLINED, as though it were a test that runs.
    for r in rows:
        if r["cls"] not in UNTESTED:
            continue
        for case in CASE_RE.findall(r["exclusion_reason"]):
            if case not in R.CASES and case not in R.DECLINED_ARMS:
                problems.append(
                    f"{r['claim_id']}: reason cites case {case!r}, which is in neither "
                    f"CASES nor DECLINED_ARMS — the named proxy does not exist")

    counted = sum(1 for r in rows if r["cls"] in TESTED + UNTESTED)
    if counted != len(rows):
        stray = sorted({r["cls"] for r in rows} - set(TESTED + UNTESTED))
        problems.append(f"{len(rows) - counted} row(s) carry a class outside "
                        f"E/S/C/O/D/N/X: {stray}")
    return problems


def proxies(reason: str) -> list[str]:
    """Cases named in a reason that ARE run. Declined arms are excluded on purpose."""
    seen, out = set(), []
    for case in CASE_RE.findall(reason):
        if case not in seen and case in R.CASES:
            seen.add(case)
            out.append(case)
    return out


def declined(reason: str) -> list[str]:
    """Arms named in a reason that are designed but NOT run."""
    seen, out = set(), []
    for case in CASE_RE.findall(reason):
        if case not in seen and case in R.DECLINED_ARMS:
            seen.add(case)
            out.append(case)
    return out


def render(rows: list[dict]) -> str:
    n = len(rows)
    counts = defaultdict(int)
    for r in rows:
        counts[r["cls"]] += 1
    n_tested = sum(counts[c] for c in TESTED)
    n_untested = sum(counts[c] for c in UNTESTED)

    L: list[str] = []
    w = L.append

    w("# Exclusion Register")
    w("")
    w("**Generated** by `claims/03_exclusion_register.py` from `claims/triage.csv`. "
      "Do not edit by hand — edit the rules in `claims/triage_rules.py` and regenerate. "
      "`--check` fails if this file and the triage disagree.")
    w("")
    w(f"Scope: `agentcore_guardrails_best_practices_v1.2.md`, {n} atomic claims after "
      f"splits and merges.")
    w("")
    w("## 1. Why this register exists")
    w("")
    w("A report claiming 100% validation of a 961-line document would be false, and "
      "detectably so. This register is the honest denominator: it names every claim "
      "that receives **no experiment**, states why, and — where one exists — names the "
      "nearest test that *is* run. An accurate exclusion register is more credible "
      "than a false 100%.")
    w("")
    w("Three kinds of \"not tested\" are recorded separately, because collapsing them "
      "would hide the only one that is a real gap:")
    w("")
    w("| Class | Meaning | Is it a gap? |")
    w("|:--|:--|:--|")
    w("| **D** | Definitional — the document's own framework (hop numbering, diagram "
      "labels, change log, metadata) | **No.** A naming convention has no truth value. "
      "Manufacturing a test for it would be theatre. |")
    w("| **N** | Normative — value judgements and prescriptions addressed to the reader "
      "| **No, but they must never be scored \"passed.\"** The *capability* each "
      "recommendation presumes is tested; whether the recommendation is advisable is "
      "not an empirical question. |")
    w("| **X** | Excluded, testable in principle | **Yes.** Each row below carries a "
      "reason and a remedy. These are the rows to attack. |")
    w("")
    w("## 2. Arithmetic")
    w("")
    w("| | Claims | Share |")
    w("|:--|--:|--:|")
    for c in TESTED:
        w(f"| {c} — {CLASS_LABEL[c]} | {counts[c]} | {counts[c] / n:.1%} |")
    w(f"| **Directly tested (E+S+C+O)** | **{n_tested}** | **{n_tested / n:.1%}** |")
    for c in UNTESTED:
        w(f"| {c} — {CLASS_LABEL[c]} | {counts[c]} | {counts[c] / n:.1%} |")
    w(f"| **Not tested (D+N+X)** | **{n_untested}** | **{n_untested / n:.1%}** |")
    w(f"| **Total** | **{n}** | **100.0%** |")
    w("")
    w(f"The headline number is therefore **{n_tested}/{n} = {n_tested / n:.1%} of "
      f"claims carry an experiment**, and **{counts['X']} claims ({counts['X'] / n:.1%}) "
      f"are genuine gaps**. The {counts['D'] + counts['N']} D and N rows are accounted "
      f"for, not omitted: every one is listed in §4 and §5 with the reason it has no "
      f"truth value an experiment could reach.")
    w("")

    # ---- §3 the real gaps -------------------------------------------------
    xrows = [r for r in rows if r["cls"] == "X"]
    w("## 3. Class X — the real gaps")
    w("")
    w(f"{len(xrows)} claims. Each is testable in principle and is not being tested "
      f"here. Ordered as they appear in the document.")
    w("")
    for r in xrows:
        reason = " ".join(r["exclusion_reason"].split())
        m = REMEDY_RE.search(reason)
        body = reason[: m.start()].strip() if m else reason
        remedy = m.group(1).strip() if m else "—"
        px, dec = proxies(reason), declined(reason)
        w(f"### {r['claim_id']}  ·  {fmt_anchor(r['anchor'])}")
        w("")
        w(f"> {' '.join(r['text'].split())[:400]}")
        w("")
        w(f"- **Doc line** {r['doc_line']} · `sha1:{r['sha1'][:12]}` · rule "
          f"`{r['rule']}`")
        if r["merge_group"]:
            w(f"- **Merge group** `{r['merge_group']}`"
              + (" (canonical site)" if r["canonical"] == "yes"
                 else f" → canonical `{r['merged_into']}`"))
        w(f"- **Why excluded** {body}")
        w(f"- **Nearest proxy run** "
          + (", ".join(f"`{c}` ({R.CASES[c][1]})" for c in px) if px
             else "none — this claim has no experimental shadow at all"))
        if dec:
            w(f"- **Also named, but NOT run** "
              + ", ".join(f"`{c}`" for c in dec)
              + " — see §3.2. Named so the limit is identifiable; not evidence.")
        w(f"- **Remedy** {remedy}")
        w("")

    w("### 3.1 What the X rows have in common")
    w("")
    w("Four structural causes account for all of them, and naming the causes is more "
      "useful than the individual rows:")
    w("")
    w("1. **No fault-injection surface.** AgentCore exposes no way to induce a "
      "service-side evaluation timeout, so every \"fail-secure on timeout\" claim is "
      "unreachable. The nearest proxies (`F5-4a` unevaluable policy, `F5-4b` guardrail "
      "evaluation impossible) probe the same posture through different failure modes, "
      "and they are run. They are *proxies*, not substitutes: a system can be "
      "fail-closed on a malformed policy and fail-open on a timeout.")
    w("2. **Enforcement requires a constrained principal.** Testing that an SCP or an "
      "IAM condition key *blocks* something requires a principal that the control "
      "actually binds. This is the Organizations management account, where SCPs never "
      "apply, and `AssumeRole` into both member accounts is AccessDenied. Authoring and "
      "propagation are testable (`F5-3a`, `F5-3b`); enforcement from inside a "
      "constrained account is not.")
    w("3. **The claim is about a service we cannot see inside.** Service-owned "
      "evaluator credentials and Regions are not customer-observable at all. No amount "
      "of budget changes this; it needs an AWS-side attestation.")
    w("4. **Out of engagement scope.** DNS-based exfiltration from a sandbox is an "
      "actual exfiltration technique, and a live A/B significance study measures an "
      "Optimization feature rather than a guardrails property. Both are declined "
      "deliberately, not by omission.")
    w("")
    w("Cause 2 is worth one more sentence, because it is the one a reviewer will "
      "press on. Decision 5b excluded the member-account test as a matter of "
      "engagement policy: it is a 90-day irreversible Organizations change whose "
      "subject is generic SCP behaviour, not an AgentCore property. That is a scoping "
      "judgement, and it is recorded here as one rather than dressed up as an "
      "impossibility.")
    w("")
    w("### 3.2 Declined arms — designed, named, not run")
    w("")
    w("An exclusion reason may name one of these to identify a limit precisely. They "
      "are deliberately kept OUT of the case registry: an arm that does not run must "
      "never be citable as evidence, and if these were registry cases the tables above "
      "would list them under \"nearest proxy run\". Naming without crediting is the "
      "whole point of the distinction.")
    w("")
    for arm, why in sorted(R.DECLINED_ARMS.items()):
        w(f"- **`{arm}`** — {' '.join(why.split())}")
    w("")

    # ---- §4 and §5 — grouped, because 151 rows individually is noise -----
    for cls, heading, preamble in (
        ("N", "Class N — normative claims (no truth value)",
         "Value judgements and prescriptions addressed to the reader. Listed in full "
         "because the failure mode this class prevents is a recommendation being "
         "quietly counted as a validated fact. Grouped by the reason assigned; the "
         "reason states which experiments cover the *capability* each recommendation "
         "presumes.\n\nA recommendation that does make a falsifiable prediction is "
         "not in this list — it was operationalized into an E/S claim in "
         "`triage_rules.py` and appears in the coverage matrix instead."),
        ("D", "Class D — definitional claims (the document's own framework)",
         "The document's own conventions, diagram labels, table headers, metadata and "
         "change log. §2.1 says outright that the hop numbering is this document's "
         "framework and that AWS documentation has no hop concept. A convention can be "
         "useful or useless but not true or false, so there is nothing to measure. "
         "Grouped by reason."),
    ):
        sel = [r for r in rows if r["cls"] == cls]
        w(f"## {'4' if cls == 'N' else '5'}. {heading}")
        w("")
        w(f"{len(sel)} claims.")
        w("")
        for para in preamble.split("\n\n"):
            w(para)
            w("")
        groups = defaultdict(list)
        for r in sel:
            groups[" ".join(r["exclusion_reason"].split())].append(r)
        for reason, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            px = proxies(reason)
            w(f"**{len(rs)} claim(s)** — {reason}")
            if px:
                w("")
                w("Capability covered by: "
                  + ", ".join(f"`{c}`" for c in px))
            w("")
            w("| Claim | §  | Line | Text |")
            w("|:--|:--|--:|:--|")
            for r in rs:
                txt = " ".join(r["text"].split()).replace("|", "\\|")
                w(f"| `{r['claim_id']}` | {fmt_anchor(r['anchor'])} | {r['doc_line']} | "
                  f"{txt[:120]}{'…' if len(txt) > 120 else ''} |")
            w("")

    # ---- §6 designed-but-unrunnable -------------------------------------
    w("## 6. Designed experiments with no claim to serve")
    w("")
    w("The inverse bookkeeping: cases that exist in the registry but that no claim "
      "cites. Left in deliberately, each with a written justification, so the "
      "exclusion story points at a designed-but-unrunnable experiment rather than at "
      "nothing.")
    w("")
    for case, why in sorted(R.PLATFORM_CASES.items()):
        fam, title, cls, oracle, _method = R.CASES[case]
        w(f"### `{case}` — {title}")
        w("")
        w(f"- **Family** {fam} · **class** {cls}")
        w(f"- **Oracle** {oracle}")
        w(f"- **Why no claim cites it** {' '.join(why.split())}")
        w("")

    w("## 7. How to audit this register")
    w("")
    w("```sh")
    w("python3 claims/01_triage.py --check           # triage.csv reproduces from the rules")
    w("python3 claims/check_coverage.py              # 15 checks over every claim")
    w("python3 claims/check_coverage.py --self-test  # the checks can still fail")
    w("python3 claims/03_exclusion_register.py --check   # this file matches the triage")
    w("```")
    w("")
    w("The second and third commands matter together. `check_coverage.py` enforces "
      "that an untested claim carries a substantive reason and that an X claim names a "
      "remedy; `--self-test` mutates the triage 14 ways and requires the named check "
      "to fire on each, with a control arm proving no check fires on clean input. A "
      "gate that passed unconditionally would certify this register without reading "
      "it.")
    w("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="regenerate and diff against the committed file")
    args = ap.parse_args()

    rows = load()
    if not rows:
        print("triage.csv is empty — refusing to write a register", file=sys.stderr)
        return 2

    problems = check(rows)
    if problems:
        print(f"FAIL — {len(problems)} problem(s); no register written:\n",
              file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    text = render(rows)

    if args.check:
        if not OUT.exists():
            print(f"--check: {OUT.name} does not exist", file=sys.stderr)
            return 1
        if OUT.read_text(encoding="utf-8") != text:
            print(f"--check: {OUT.name} is stale — re-run 03_exclusion_register.py",
                  file=sys.stderr)
            return 1
        print(f"--check: {OUT.name} matches triage.csv")
        return 0

    OUT.write_text(text, encoding="utf-8")
    counts = defaultdict(int)
    for r in rows:
        counts[r["cls"]] += 1
    n = len(rows)
    tested = sum(counts[c] for c in TESTED)
    print(f"wrote {OUT.name}  ({len(text.splitlines())} lines)")
    print(f"  {n} claims: {tested} tested ({tested / n:.1%}), "
          f"{counts['X']} real gaps, {counts['N']} normative, "
          f"{counts['D']} definitional")
    print(f"  {len(R.PLATFORM_CASES)} designed-but-uncited cases declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
