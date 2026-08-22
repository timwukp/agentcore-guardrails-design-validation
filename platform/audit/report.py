#!/usr/bin/env python3
"""Turn an inventory of a submitted template into three outputs: what you declared, what this study
measured about it, and what follows. Every line traceable to a case file or absent by name.

THE THREE OUTPUTS, AND WHY THEY ARE SEPARATE DOCUMENTS RATHER THAN THREE HEADINGS

1. **Control inventory** — what the templates declare, verbatim, with `file:line`. No judgment, no
   verdict, no colour. A reader must be able to check this section against their own repository
   without accepting anything this study claims; that is what makes the rest auditable rather than
   authoritative.
2. **Audit report** — per control, the study's measurement, in one of five states. The fifth,
   NOT MEASURED, is the one an audit tool usually lacks, and its absence is what makes such tools
   dishonest: "no finding" then covers both "we looked and it was fine" and "we never looked."
3. **Recommendations** — each one carrying the case id and verdict that licenses it. An INCONCLUSIVE
   verdict licenses **none**, and the report states how many recommendations it therefore withheld,
   because a withheld recommendation the reader cannot see is indistinguishable from one that was
   never considered.

WHAT THIS PROGRAM MUST NEVER EMIT, AND WHY IT IS A CORRECTNESS PROPERTY

**No pass rate. No score. No grade. No count of "controls passed."** Not a style preference — a ratio
here would be arithmetic over incommensurable things. Of 91 published verdicts, 23 are FALSE, 20 are
INCONCLUSIVE and 2 are RECORDED; dividing by 91 would treat "measured and the documented guidance did
not hold" and "nothing was established" as the same kind of miss, and treat a control this study never
examined as a pass. The reader would then have a number that feels like information and is not.

The headline is a **denominator statement** instead: how many of the reader's controls this study has
anything at all to say about. That is the honest summary, and it is the one that shrinks when the
study's coverage is thin — which is the direction a reader needs it to move.

**No amendment from an INCONCLUSIVE verdict.** The rule is enforced here in code, not trusted to
whoever writes the prose, and the same rule already governs the study's own document amendments.

**NOT_DECLARED never reads as absent.** The parser saw what it could parse. Every NOT_DECLARED line
says "not seen in the files that were parsed", and if the parse was truncated or the submission was
HCL-only, the caveat from the inventory is carried into this report rather than left behind in a JSON
field nobody opens.

DETERMINISM IS A TEST, NOT AN ASPIRATION

The same submission read against the same artifacts must produce a byte-identical report. So nothing
here reads a clock: `evidence_through` is derived from the study's own data, and the run date, if the
caller wants one in the document, arrives as `--as-of`. A report that changes when nothing changed
cannot be diffed, and a report that cannot be diffed cannot be trusted to have changed for a reason.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import check_controls  # noqa: E402  the gate owns the readers; a second one could disagree with it

# How a machine status becomes a sentence a reader can act on. Deliberately not colours or symbols:
# "PASS"/"FAIL" is exactly the collapse this report exists to refuse.
STATUS_LABEL = {
    "measured_true": "MEASURED — this study tested the documented behaviour and it held",
    "measured_false": "MEASURED — this study tested the documented behaviour and it did NOT hold",
    "not_established": "NOT ESTABLISHED — measured, and nothing could be concluded",
    "not_measured": "NOT MEASURED — this study never examined this control",
    "context_only": "CONTEXT ONLY — recorded, and not citable as a verdict",
}

# The states that may license a recommendation. `not_established` is absent on purpose and that
# absence is the enforcement (`feedback_constraints_are_choices`): an INCONCLUSIVE verdict cannot
# reach the recommendations section through any code path, rather than being filtered by a reviewer.
LICENSES_RECOMMENDATION = {"measured_true", "measured_false"}

# Fields a case file may use to state the limits of its own verdict. Several spellings exist across
# the 91 files; all are read, and a case carrying none is reported as carrying none.
CAVEAT_FIELDS = ("what_false_does_not_prove", "what_true_does_not_prove", "what_this_does_not_prove",
                 "false_means_what", "true_means_what", "why_inconclusive", "inconclusive_reason",
                 "limitations", "no_power_claim")

PHASE1 = REPO / "results" / "phase1"


def die(msg: str) -> None:
    print(f"REPORT-FAIL: {msg}", file=sys.stderr)
    raise SystemExit(2)


def as_text(value, limit: int = 700) -> str:
    """A case file's caveat may be a string, a list or a dict; render any of them without inventing."""
    if isinstance(value, str):
        out = value
    elif isinstance(value, list):
        out = " ".join(as_text(v, limit) for v in value)
    elif isinstance(value, dict):
        out = " ".join(f"{k}: {as_text(v, limit)}" for k, v in sorted(value.items()))
    else:
        out = str(value)
    out = " ".join(out.split())
    return out if len(out) <= limit else out[: limit - 1] + "…"


def read_case_caveats() -> dict[str, dict]:
    """Per case: its verdict, and its own statement of what that verdict does not prove.

    `present: False` is a fact about the study that the report is required to print: a FALSE verdict
    with no stated limit is precisely where a reader over-reads, so the report says "this case records
    no statement of what its verdict does not prove" rather than printing nothing and letting the
    silence read as "no limits".

    HOW MANY, AND WHY NO NUMBER APPEARS IN THIS SENTENCE

    This docstring used to say "39 of the 91 published cases carry no such statement". That was wrong
    twice over. The value this function's own scan yields is 33, not 39; 39 was the number of TIMES the
    field name `what_true_does_not_prove` occurs across the corpus, which counts INCONCLUSIVE, FALSE and
    RECORDED cases that carry the opposite verdict's field. A count of occurrences is not a count of
    cases. So no count is written here now — the caller renders the number this function derives, and a
    test asserts it. A number that lives only in prose is a number nothing checks.

    THIS COUNT IS NOT THE SITE'S COUNT, AND THEY ARE NOT MEANT TO AGREE

    `CAVEAT_FIELDS` is nine field names over all 91 published cases: "does the record say anything at
    all about limits". The site payload asks a narrower question — does a case carry the field named for
    ITS OWN verdict direction, over the 69 TRUE and FALSE cases that have a direction to over-read —
    and publishes 49 silent. Two definitions, two numbers, both derived. Neither is a correction of the
    other, and neither may be quoted without naming which question it answers.
    """
    out: dict[str, dict] = {}
    for path in sorted(PHASE1.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            die(f"{path.name} is not readable JSON ({type(e).__name__}); the report cannot state a "
                f"verdict's limits from a file it cannot read")
        cid = data.get("case_id")
        if not isinstance(cid, str):
            continue
        parts = [f"{f}: {as_text(data[f])}" for f in CAVEAT_FIELDS if data.get(f)]
        out[cid] = {"verdict": data.get("verdict"), "present": bool(parts),
                    "text": " | ".join(parts) if parts else None,
                    "title": data.get("title") or data.get("claim")}
    return out


def evidence_through(caveats: dict) -> str | None:
    """The latest UTC day the study observed anything, derived — never a clock read.

    Register item: F6's verdict files carry no machine-readable day stamp, so this is a floor over the
    families that do. It is reported as a floor and labelled as one; a date presented as exact when it
    is a lower bound is the kind of small lie that makes a reader distrust the large truths.
    """
    days = set()
    for path in sorted(PHASE1.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for key in ("t_start_utc", "started_utc", "ended_utc", "collected_at", "observed_on",
                    "measured_start", "reread_utc_day", "day_tag", "observation_day"):
            v = data.get(key)
            if isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-":
                days.add(v[:10])
    return max(days) if days else None


# --------------------------------------------------------------------------------- adjudication


def match_findings(control: dict, obs: dict) -> tuple[list[dict], str]:
    """**Every** authored finding that applies to what the template declared, and why they apply.

    Returning a list rather than the first match is load-bearing, and the smoke test is what proved it:
    four of the nineteen controls author two findings under the same `when`, because two separate
    measurements bear on the same declaration — `cedar_policy_set` DECLARED has one finding about what
    the statements do under ENFORCE and another about what happens to them under LOG_ONLY. A
    first-match lookup dropped the second one silently, and an authored finding that can never reach a
    reader is indistinguishable from one that did (`feedback_unnumbered_is_uncounted`). The curation
    gate is right to permit two, so the reporting side is where the obligation to render both lives.

    The empty-list case is the interesting one and is not an error: a value the study has no finding
    for means "your gateway is in a state this study did not measure", which the report must be able
    to say. Falling through to a default finding would attach someone else's measurement to the
    reader's configuration.
    """
    findings = control.get("findings") or []
    if control.get("measured") == "none":
        unmeasured = [f for f in findings if f.get("status") == "not_measured"]
        if unmeasured:
            return unmeasured, "this control is declared unmeasured by the study"
        return [], "this control is declared unmeasured and carries no finding to show"

    value = obs.get("value")
    observed = obs.get("observation")

    if value is not None:
        by_value = [f for f in findings
                    if "value" in (f.get("when") or {})
                    and str((f.get("when") or {})["value"]) == str(value)]
        if by_value:
            return by_value, f"the template declares {value!r}"

    by_observation = [f for f in findings if (f.get("when") or {}).get("observation") == observed]
    if by_observation:
        return by_observation, ("the properties this control reads are present in your templates"
                                if observed == "DECLARED"
                                else "those properties were not seen in the files that were parsed")

    if obs.get("disagreement"):
        return [], (f"the templates declare more than one value ({', '.join(obs['disagreement'])}), "
                    f"so no single measurement applies — each declaring resource needs reading "
                    f"separately")
    if value is not None:
        return [], (f"the template declares {value!r}, and this study has no measurement mapped to "
                    f"that value")
    if observed == "DECLARED":
        return [], ("the property is declared but its value could not be read statically (a "
                    "reference, a parameter or a token), so no measurement can be attached to it")
    return [], "not seen in the files that were parsed"


def build(inventory: dict, controls: list[dict], as_of: str | None) -> dict:
    ids, verdicts = check_controls.read_verdicts()
    restrictions = check_controls.read_restrictions()
    caveats = read_case_caveats()

    lines: list[dict] = []
    for control in sorted(controls, key=lambda c: str(c.get("id"))):
        cid = control.get("id")
        obs = next((o for o in inventory["observations"] if o.get("control") == cid), None)
        if obs is None:
            die(f"control {cid} has no observation in the inventory. The inventory and this report "
                f"must be built from the same controls file; one of them is stale, and a report "
                f"missing a control silently under-reports coverage")
        findings, why = match_findings(control, obs)

        measurements = []
        for finding in findings:
            cases = []
            for case_id in sorted(finding.get("cites") or []):
                if case_id not in ids:
                    die(f"{cid} cites {case_id}, which is not a registered case. The control curation "
                        f"gate should have caught this before publish")
                info = caveats.get(case_id, {})
                cases.append({
                    "case": case_id,
                    "verdict": verdicts.get(case_id, "not published"),
                    "restrictions": sorted(restrictions.get(case_id, set())),
                    "what_this_verdict_does_not_prove": info.get("text"),
                    "limits_stated_by_the_case": bool(info.get("present")),
                })
            status = finding.get("status")
            measurements.append({
                "status": status,
                "status_label": STATUS_LABEL.get(status, "NO MEASUREMENT MAPPED TO THIS STATE"),
                "says": finding.get("says"),
                "consequence": finding.get("consequence"),
                "scope_note": finding.get("scope_note"),
                "why_not_measured": finding.get("why_not_measured")
                                    or control.get("why_not_measured"),
                "cases": cases,
            })

        lines.append({
            "control": cid,
            "label": control.get("label"),
            "question": control.get("question"),
            "observation": obs.get("observation"),
            "value": obs.get("value"),
            "values_seen": obs.get("values_seen") or [],
            "disagreement": obs.get("disagreement"),
            "values_outside_the_declared_enum": obs.get("values_outside_the_declared_enum"),
            "sites": obs.get("sites") or [],
            "unresolved": obs.get("unresolved") or [],
            "why_this_status": why,
            "statuses": sorted({m["status"] for m in measurements if m["status"]}),
            "measurements": measurements,
        })

    recommendations = []
    withheld = []
    for line in lines:
        for m in line["measurements"]:
            if not m["consequence"]:
                continue
            citable = [c for c in m["cases"]
                       if c["verdict"] in ("TRUE", "FALSE") and "NEVER_CITE" not in c["restrictions"]]
            if m["status"] not in LICENSES_RECOMMENDATION or not citable:
                withheld.append({
                    "control": line["control"], "status": m["status"],
                    "why_withheld": ("this study established nothing about the state your template "
                                     "declares, and an INCONCLUSIVE or unmeasured result licenses no "
                                     "recommendation")
                    if m["status"] not in LICENSES_RECOMMENDATION else
                    ("the finding's supporting case(s) are not citable as a verdict, so no "
                     "recommendation may rest on them"),
                })
                continue
            recommendations.append({
                "control": line["control"],
                "label": line["label"],
                "observation": line["observation"],
                "because": m["says"],
                "recommendation": m["consequence"],
                "licensed_by": [{"case": c["case"], "verdict": c["verdict"]} for c in citable],
                "scope_note": m["scope_note"],
                "sites": [f"{s['file']}:{s['line']}" for s in line["sites"]],
            })

    def any_status(line: dict, *want: str) -> bool:
        return bool(set(line["statuses"]) & set(want))

    declared = [l for l in lines if l["observation"] == "DECLARED"]
    with_measurement = [l for l in declared
                        if any_status(l, "measured_true", "measured_false", "not_established")]
    contradicted = [l for l in declared if any_status(l, "measured_false")]
    never_measured = [l for l in declared if any_status(l, "not_measured")]
    unmapped = [l for l in declared if not l["statuses"]]

    n_limits = sum(1 for c in caveats.values() if c.get("present"))
    report_caveats = list(inventory.get("caveats") or [])
    report_caveats.append(
        f"{n_limits} of {len(caveats)} published case(s) state, in the case file itself, what their "
        f"verdict does not prove. The remaining {len(caveats) - n_limits} do not, and every line "
        f"above that rests on one of them says so. Treat those verdicts as narrower than they read.")
    report_caveats.append(
        "Every NOT_DECLARED result means 'not seen in the files that were parsed'. It is not evidence "
        "that the control is absent from your system: it may be set outside infrastructure-as-code, "
        "in a file this parser does not read, or at runtime.")
    report_caveats.append(
        "Detection matches property paths verified against the pinned service model. CloudFormation "
        "resource **type** spellings are matched by substring and were NOT verified against a synth "
        "artifact, so a resource whose type name does not contain the expected word will be missed.")

    return {
        "schema": "grx-audit-report/1",
        "as_of": as_of,
        "evidence_through_at_least": evidence_through(caveats),
        "study": {
            "cases_registered": len(ids),
            "verdicts_published": len(verdicts),
            "verdict_mix": {v: sum(1 for x in verdicts.values() if x == v)
                            for v in sorted(set(verdicts.values()))},
            "controls_this_study_can_speak_to": len(controls),
        },
        "headline": {
            "statement": (
                f"This study has something to say about {len(controls)} controls. Your submission "
                f"declares {len(declared)} of them. Of those, {len(with_measurement)} have a "
                f"measurement behind them, {len(never_measured)} are controls this study never "
                f"examined, and {len(unmapped)} are in a state no measurement covers."),
            "controls_the_study_covers": len(controls),
            "controls_you_declare": len(declared),
            "declared_with_a_measurement": len(with_measurement),
            "declared_where_the_guidance_did_not_hold": len(contradicted),
            "declared_never_measured_by_this_study": len(never_measured),
            "declared_in_a_state_no_measurement_covers": len(unmapped),
            "not_seen_in_the_parsed_files": len(lines) - len(declared),
            "why_this_report_gives_no_ratio": (
                "There is no pass rate in this report. Of this study's published verdicts, "
                f"{sum(1 for x in verdicts.values() if x == 'FALSE')} are FALSE and "
                f"{sum(1 for x in verdicts.values() if x == 'INCONCLUSIVE')} are INCONCLUSIVE; a "
                "ratio would treat 'measured, and the guidance did not hold' as the same kind of "
                "miss as 'nothing was established', and would count a control never examined as a "
                "pass."),
        },
        "inventory": {
            "submission": inventory.get("submission"),
            "resources": inventory.get("resources"),
        },
        "controls": lines,
        "recommendations": recommendations,
        "recommendations_withheld": withheld,
        "caveats": report_caveats,
    }


# --------------------------------------------------------------------------------- markdown


def markdown(report: dict) -> str:
    o: list[str] = []
    a = o.append
    a("# AgentCore security-design audit — measured against the GRX validation study")
    a("")
    h = report["headline"]
    a(f"**{h['statement']}**")
    a("")
    if report.get("as_of"):
        a(f"Report date: {report['as_of']}  ")
    if report.get("evidence_through_at_least"):
        a(f"Evidence collected through at least: {report['evidence_through_at_least']} "
          f"(a floor: some families carry no machine-readable day stamp)  ")
    s = report["study"]
    mix = ", ".join(f"{k} {v}" for k, v in sorted(s["verdict_mix"].items()))
    a(f"Study behind this report: {s['verdicts_published']} published verdicts over "
      f"{s['cases_registered']} registered cases — {mix}.")
    a("")
    a(f"> {h['why_this_report_gives_no_ratio']}")
    a("")

    a("## 1. Control inventory — what your templates declare")
    a("")
    a("This section contains no judgment. Each line is a property this study knows how to look for, "
      "and the file and line where your templates set it.")
    a("")
    sub = report["inventory"]["submission"] or {}
    a(f"Files yielding resources: {sub.get('files_yielding_resources')} · "
      f"resources parsed: {sub.get('resources_found')} · "
      f"parse complete: {sub.get('complete')} · "
      f"Terraform HCL files not parsed: {sub.get('hcl_files_not_parsed')}")
    a("")
    a("A control reads *present* when the properties it looks at appear in your templates. Some "
      "controls — enforcement latency, for one — are not something a template states directly; for "
      "those, *present* means the settings that determine the behaviour were found.")
    a("")
    a("| Control | In your templates | Value(s) read | Where |")
    a("|---|---|---|---|")
    for line in report["controls"]:
        where = "; ".join(f"`{x['file']}:{x['line']}`" for x in line["sites"][:4]) or "—"
        if len(line["sites"]) > 4:
            where += f" (+{len(line['sites']) - 4} more)"
        if line["value"]:
            val = f"`{line['value']}`"
        elif line.get("disagreement"):
            val = "**disagree:** " + ", ".join(f"`{v}`" for v in line["disagreement"])
        elif line["values_seen"]:
            val = ", ".join(f"`{v}`" for v in line["values_seen"][:6])
        elif line["unresolved"]:
            val = "unresolved reference"
        else:
            val = "—"
        present = "present" if line["observation"] == "DECLARED" else "not seen"
        a(f"| {line['label']} | {present} | {val} | {where} |")
    a("")
    for s_ in (sub.get("skipped") or [])[:20]:
        a(f"- skipped `{s_['path']}` — {s_['why']}")
    if sub.get("skipped"):
        a("")

    a("## 2. Audit — what this study measured about each control")
    a("")
    for line in report["controls"]:
        a(f"### {line['label']}")
        a("")
        a(f"*{line['question']}*")
        a("")
        present = "present" if line["observation"] == "DECLARED" else "not seen"
        a(f"- **Your templates:** {present}"
          + (f", value `{line['value']}`" if line["value"] else "")
          + (f" — **the templates disagree**: {', '.join(line['disagreement'])}"
             if line.get("disagreement") else ""))
        a(f"- **Why that reading:** {line['why_this_status']}")
        if line.get("values_outside_the_declared_enum"):
            a(f"- **Outside the values this study knows:** "
              f"{', '.join(line['values_outside_the_declared_enum'])}. No measurement covers it.")
        for m in line["measurements"]:
            a("")
            a(f"**{m['status_label']}**")
            a("")
            if m.get("says"):
                a(f"- **What was measured:** {' '.join(m['says'].split())}")
            if m.get("scope_note"):
                a(f"- **Scope of that measurement:** {' '.join(m['scope_note'].split())}")
            if m.get("why_not_measured"):
                a(f"- **Why this was never measured:** {' '.join(m['why_not_measured'].split())}")
            for c in m["cases"]:
                badge = f" [{', '.join(c['restrictions'])}]" if c["restrictions"] else ""
                a(f"- **{c['case']} — {c['verdict']}**{badge}")
                if c["limits_stated_by_the_case"]:
                    a(f"    - Limits of that verdict, from the case file: "
                      f"{c['what_this_verdict_does_not_prove']}")
                else:
                    a("    - This case records no statement of what its verdict does not prove. Read "
                      "it narrowly.")
        if not line["measurements"]:
            a("")
            a("**NO MEASUREMENT MAPPED TO THIS STATE** — no case in this study bears on what your "
              "templates declare here. That is a gap in this study's coverage, not a finding about "
              "your configuration.")
        a("")

    a("## 3. Recommendations")
    a("")
    if not report["recommendations"]:
        a("None. No control your submission declares is in a state this study measured, so this "
          "report recommends nothing. That is a statement about the study's coverage of your "
          "configuration, not a clean bill of health.")
        a("")

    def render(group: list[dict]) -> None:
        for r in group:
            licensed = ", ".join(f"{x['case']} ({x['verdict']})" for x in r["licensed_by"])
            # The case ids are in the heading because one control can carry two recommendations from
            # two separate measurements, and two identical headings make them look like a duplicate.
            cited = ", ".join(x["case"] for x in r["licensed_by"])
            a(f"### {r['label']} — {cited}")
            a("")
            a(f"{' '.join(r['recommendation'].split())}")
            a("")
            a(f"- **Because:** {' '.join((r['because'] or '').split())}")
            a(f"- **Licensed by:** {licensed}")
            if r.get("scope_note"):
                a(f"- **Only within this scope:** {' '.join(r['scope_note'].split())}")
            if r["sites"]:
                a(f"- **Applies to:** {', '.join(f'`{x}`' for x in r['sites'][:6])}")
            a("")

    on_declared = [r for r in report["recommendations"] if r["observation"] == "DECLARED"]
    on_absent = [r for r in report["recommendations"] if r["observation"] != "DECLARED"]
    if on_declared:
        a("### About settings found in your templates")
        a("")
        render(on_declared)
    if on_absent:
        # Kept separate and second, because the premise is weaker: the parser did not see the setting,
        # which is not the same as the setting being absent. Merging the two groups would let a
        # recommendation resting on "we did not find it" read as one resting on "you set it this way".
        a("### About settings this parser did not find")
        a("")
        a("Each of these rests on the *absence* of a setting in the files that were parsed. If you "
          "configure it outside infrastructure-as-code, or in a file this parser does not read, the "
          "recommendation does not apply to you.")
        a("")
        render(on_absent)
    if report["recommendations_withheld"]:
        a(f"**{len(report['recommendations_withheld'])} recommendation(s) withheld.** Listed so a "
          f"withheld recommendation is visible rather than absent:")
        a("")
        for w in report["recommendations_withheld"]:
            a(f"- `{w['control']}` — {w['why_withheld']}")
        a("")

    a("## Caveats")
    a("")
    for c in report["caveats"]:
        a(f"- {' '.join(c.split())}")
    a("")
    return "\n".join(o) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", type=Path, required=True, help="output of parse_iac.py")
    ap.add_argument("--controls", type=Path,
                    default=REPO / "platform" / "curation" / "controls.yaml")
    ap.add_argument("--as-of", help="a date for the document. Omitted rather than read from a clock, "
                                    "so the same submission produces a byte-identical report.")
    ap.add_argument("--out-json", type=Path)
    ap.add_argument("--out-md", type=Path)
    args = ap.parse_args(argv)

    try:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        die(f"cannot read {args.inventory}: {type(e).__name__}")
    if inventory.get("schema") != "grx-inventory/1":
        die(f"{args.inventory} is not a grx-inventory/1 document (got "
            f"{inventory.get('schema')!r}); refusing to report over an unknown shape")

    controls = (check_controls.load_yaml_no_duplicate_keys(args.controls) or {}).get("controls") or []
    if not controls:
        die(f"{args.controls} declares no controls")

    report = build(inventory, controls, args.as_of)
    text = json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    md = markdown(report)

    for path, body in ((args.out_json, text), (args.out_md, md)):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    if not args.out_json and not args.out_md:
        sys.stdout.write(md)

    h = report["headline"]
    print(f"{h['statement']}", file=sys.stderr)
    print(f"  {len(report['recommendations'])} recommendation(s), "
          f"{len(report['recommendations_withheld'])} withheld; "
          f"report sha256 {hashlib.sha256(text.encode()).hexdigest()[:16]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
