#!/usr/bin/env python3
"""Gate over `platform/curation/controls.yaml` — the control→case mapping an audit report is built on.

WHAT THIS GATE IS FOR

`controls.yaml` is the file that turns 91 verdicts into "here is what your template needs to check".
That makes it the one authored file in the platform that can put words in the study's mouth: a
recommendation is a sentence about the reader's system, and if it cites a case that does not support
it, the study has been made to say something it did not measure. Prose cannot prevent that. The rules
below can, and every one of them is derived from an artifact rather than restated here:

  * which cases exist, and each one's verdict — from `results/_census.json` and `results/phase1/`.
  * which cases may be cited, and as what — from the machine block in `results/CITATION-POLICY.md`,
    whose own header declares `authoritative_for_tooling: true`. **No case id is hardcoded in this
    file.** `F5-3b` is unmentioned below; it is excluded because the citation policy gives it the
    `NEVER_CITE` restriction, so a future case that acquires that restriction is excluded too,
    without an edit here. A gate whose scope is a name list cannot notice a new name.
  * which field paths a detection rule may use — from live introspection of the pinned botocore in
    `.venv-oracle`, under `--verify-field-paths`.

THE CEILING MATTERS AS MUCH AS THE FLOOR

Every mapping is checked against an allowlist of keys and an unknown key is fatal. This is not
pedantry: `citess:` instead of `cites:` would otherwise read as a finding with no citation, and a
finding with no citation is exactly what the status rules are meant to make impossible. The same
applies to a control with zero findings, a file with zero controls, and a `when:` predicate naming a
value the detection rule cannot produce — each of those is a rule that can never fire, and a rule
that can never fire looks identical to a rule that passed.

EXIT CODES

0 = every rule holds. 2 = at least one violation, all of them printed. Never 1, because 1 is what a
Python traceback exits with and a crash must not be readable as "one finding".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CURATION = ROOT / "platform" / "curation" / "controls.yaml"
CENSUS = ROOT / "results" / "_census.json"
PHASE1 = ROOT / "results" / "phase1"
CITATION_POLICY = ROOT / "results" / "CITATION-POLICY.md"

MACHINE_RE = re.compile(r"<!--\s*machine\s*(\{.*?\})\s*-->", re.DOTALL)

# Floors. A file that shrank to nothing must fail rather than pass over an empty set
# (`feedback_zero_file_scan_is_error`).
MIN_CONTROLS = 10
MIN_PHASE1_FILES = 90

# Minimum lengths for the authored prose. Each of these fields is the human reason a machine cannot
# supply, and a one-word placeholder is the shape a forgotten justification takes.
MIN_WHY = 40
MIN_SAYS = 40
MIN_CONSEQUENCE = 40
MIN_WHY_NOT_MEASURED = 60
MIN_SCOPE_NOTE = 60

TOP_KEYS = {"schema", "field_paths", "vocabularies", "controls", "unverifiable_paths"}
CONTROL_KEYS = {"id", "label", "question", "detect", "measured_by", "measured",
                "why_not_measured", "findings"}
DETECT_KEYS = {"type_hint", "paths", "value_from", "values", "paths_source"}
MEASURED_BY_KEYS = {"case", "why"}
FINDING_KEYS = {"when", "status", "cites", "says", "consequence", "scope_note",
                "why_not_measured"}
WHEN_KEYS = {"value", "observation"}

STATUSES = {"measured_true", "measured_false", "not_established", "not_measured", "context_only"}
OBSERVATIONS = {"DECLARED", "NOT_DECLARED"}

# The verdict a status is allowed to rest on. `context_only` and `not_measured` are absent on
# purpose: the first is checked against the restriction table instead, the second must cite nothing.
STATUS_REQUIRES_VERDICT = {
    "measured_true": "TRUE",
    "measured_false": "FALSE",
    "not_established": "INCONCLUSIVE",
}

# Restrictions that disqualify a case from carrying a finding's weight. Read from the citation
# policy's own vocabulary; a restriction it grows that is not listed here is reported as unclassified
# rather than treated as benign, because "unknown restriction" must not read as "no restriction".
RESTRICTION_NEVER = {"NEVER_CITE"}
RESTRICTION_CONTEXT_ONLY = {"NOT_A_VERDICT", "UNMEASURED", "UNTESTABLE", "MECHANISM_ONLY",
                            "NO_CLAIM_MAPPED"}
RESTRICTION_NOT_ESTABLISHED_ONLY = {"NOT_EVIDENCE_AGAINST"}
RESTRICTION_NEEDS_SCOPE = {"PARTIAL", "REPLICATION_POSITION_BOUND"}
KNOWN_RESTRICTIONS = (RESTRICTION_NEVER | RESTRICTION_CONTEXT_ONLY
                      | RESTRICTION_NOT_ESTABLISHED_ONLY | RESTRICTION_NEEDS_SCOPE)


class Findings:
    """Collect every violation rather than dying on the first.

    A gate that stops at the first problem turns one authoring pass into N runs, and the fix for
    problem 1 is often the same edit as problem 7. The count is printed so a truncated read of the
    output cannot be mistaken for a clean one.
    """

    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, where: str, msg: str) -> None:
        self.items.append(f"{where}: {msg}")

    def report(self, subject: str) -> int:
        if not self.items:
            print(f"OK: {subject}")
            return 0
        print(f"\nGATE-FAIL: {len(self.items)} violation(s) in {subject}", file=sys.stderr)
        for item in self.items:
            print(f"  - {item}", file=sys.stderr)
        return 2


def die(msg: str) -> None:
    print(f"GATE-FAIL: {msg}", file=sys.stderr)
    raise SystemExit(2)


def rel(path: Path) -> str:
    """A repo-relative path for a message, falling back to the absolute one.

    `Path.relative_to` raises for anything outside ROOT, and every use here is inside an error
    string — so a test pointing the gate at a temporary file turned a finding into a ValueError
    traceback. A crash is not a finding: it exits 1, prints no GATE-FAIL line, and reads to a caller
    like the gate never ran (`feedback_cryptic_error_is_missing_guard`).
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------------- inputs


def load_yaml_no_duplicate_keys(path: Path) -> dict:
    """Parse YAML, refusing a mapping that defines the same key twice.

    PyYAML keeps the last duplicate silently, which in an authored governance file means the line a
    human edited may be the one discarded. Same loader discipline as `build_site_data.py`; kept
    separate rather than imported, because a gate that imports the builder cannot fail the builder.
    """
    try:
        import yaml  # noqa: PLC0415 - only this loader needs it
    except ImportError:  # pragma: no cover - depends on the interpreter, not the tree
        die("PyYAML is not importable. Run this gate under .venv-oracle; do NOT add a fallback "
            "parser, because a second YAML grammar for a governance file is a second answer.")

    class NoDuplicates(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        seen: set = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=True)
            if key in seen:
                die(f"{path.name} defines {key!r} twice in one mapping "
                    f"(line {key_node.start_mark.line + 1}); PyYAML would keep the last silently")
            seen.add(key)
        return loader.construct_mapping(node, deep=True)

    NoDuplicates.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=NoDuplicates)  # noqa: S506
    except yaml.YAMLError as e:
        die(f"{path.name} is not readable YAML: {e}")
    if not isinstance(loaded, dict):
        die(f"{path.name} must be a mapping at the top level, not {type(loaded).__name__}")
    return loaded


def read_verdicts() -> tuple[set[str], dict[str, str]]:
    """The case ids in the sealed register, and the live verdict of each.

    Verdicts come from `results/phase1/*.json` keyed by `case_id`, excluding `archive/` exactly the
    way `census.py` excludes it — a superseded artifact is not a verdict. A case with no verdict file
    is absent from the verdict map rather than defaulted, so a status rule asking for its verdict
    fails instead of quietly matching.
    """
    if not CENSUS.is_file():
        die(f"{rel(CENSUS)} is missing; the gate cannot check a case id against the "
            f"register it is supposed to exist in")
    rows = json.loads(CENSUS.read_text(encoding="utf-8"))
    registered = {r["case"] for r in rows if isinstance(r, dict) and "case" in r}
    if not registered:
        die(f"{rel(CENSUS)} yielded zero case ids")

    files = sorted(PHASE1.glob("*.json"))
    if len(files) < MIN_PHASE1_FILES:
        die(f"results/phase1/ holds {len(files)} file(s), below the floor of {MIN_PHASE1_FILES}; a "
            f"verdict lookup over a truncated tree would report every case as unmeasured")
    verdicts: dict[str, str] = {}
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and isinstance(d.get("case_id"), str) and d.get("verdict"):
            verdicts[d["case_id"]] = d["verdict"]
    return registered, verdicts


def read_restrictions() -> dict[str, set[str]]:
    """Per case, the set of citation restrictions in force, from the citation policy's machine block.

    This is the whole reason no case id appears in this module. The policy file is the single place
    the restrictions live and it declares itself authoritative for tooling; reproducing any part of
    it here would create a second answer that can disagree with the first.
    """
    if not CITATION_POLICY.is_file():
        die(f"{rel(CITATION_POLICY)} is missing. Without it this gate would have to "
            f"hardcode which verdicts are citable, which is the defect that file exists to fix.")
    m = MACHINE_RE.search(CITATION_POLICY.read_text(encoding="utf-8"))
    if not m:
        die(f"{rel(CITATION_POLICY)} has no `<!-- machine ... -->` block")
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        die(f"{rel(CITATION_POLICY)} machine block is not valid JSON: {e}")
    out: dict[str, set[str]] = {}
    entries = meta.get("restrictions") or []
    if not entries:
        die(f"{rel(CITATION_POLICY)} declares zero restrictions; every legality rule "
            f"in this gate would then pass over an empty table")
    for entry in entries:
        for case in entry.get("cases") or []:
            out.setdefault(case, set()).add(entry.get("restriction"))
    return out


# --------------------------------------------------------------------------------- rules


def check_shape(data: dict, f: Findings) -> list[dict]:
    """Keys, floors and uniqueness. Returns the control list, or an empty list if unusable."""
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        f.add("controls.yaml", f"unknown top-level key(s) {unknown}")
    if data.get("schema") != "grx-controls/1":
        f.add("controls.yaml", f"schema is {data.get('schema')!r}, expected 'grx-controls/1'")

    controls = data.get("controls")
    if not isinstance(controls, list) or not controls:
        f.add("controls.yaml", "`controls:` is missing or empty")
        return []
    if len(controls) < MIN_CONTROLS:
        f.add("controls.yaml", f"{len(controls)} control(s), below the floor of {MIN_CONTROLS}")

    seen: dict[str, int] = {}
    for i, c in enumerate(controls):
        if not isinstance(c, dict):
            f.add(f"controls[{i}]", f"is a {type(c).__name__}, not a mapping")
            continue
        cid = c.get("id")
        where = f"control {cid or f'[{i}]'}"
        if not isinstance(cid, str) or not cid:
            f.add(where, "has no `id:`")
        elif cid in seen:
            f.add(where, f"duplicates the id at controls[{seen[cid]}]")
        else:
            seen[cid] = i
        for key in ("label", "question", "detect", "findings"):
            if key not in c:
                f.add(where, f"has no `{key}:`")
        unknown = sorted(set(c) - CONTROL_KEYS)
        if unknown:
            f.add(where, f"unknown key(s) {unknown}")
        detect = c.get("detect")
        if isinstance(detect, dict):
            unknown = sorted(set(detect) - DETECT_KEYS)
            if unknown:
                f.add(where, f"detect has unknown key(s) {unknown}")
            paths = detect.get("paths")
            if not isinstance(paths, list) or not paths:
                f.add(where, "detect declares no `paths:`; it can never match anything")
            if not detect.get("paths_source"):
                f.add(where, "detect has no `paths_source:` — a field path with no stated origin is "
                             "an unverified claim wearing a detection rule's clothes")
        elif detect is not None:
            f.add(where, f"detect is a {type(detect).__name__}, not a mapping")
        findings = c.get("findings")
        if not isinstance(findings, list) or not findings:
            f.add(where, "has zero findings; a control that can produce no statement is a control "
                         "the report will silently omit")
    return [c for c in controls if isinstance(c, dict)]


def check_measured(control: dict, registered: set[str], restrictions: dict[str, set[str]],
                   f: Findings) -> None:
    """`measured_by` XOR `measured: none`, and the reason when nothing measured it."""
    cid = control.get("id")
    where = f"control {cid}"
    measured_by = control.get("measured_by")
    declared_none = control.get("measured") == "none"

    if "measured" in control and not declared_none:
        f.add(where, f"`measured:` is {control['measured']!r}; the only accepted value is 'none'")
    if declared_none and measured_by:
        f.add(where, "declares both `measured: none` and `measured_by:`; it cannot be both "
                     "unmeasured and measured")
    if not declared_none and not measured_by:
        f.add(where, "has neither `measured_by:` nor `measured: none`. Nothing may be unmeasured by "
                     "omission — an absent mapping and a stated gap read identically in a report, "
                     "and only one of them is honest.")
    if declared_none:
        why = control.get("why_not_measured") or ""
        if len(why.strip()) < MIN_WHY_NOT_MEASURED:
            f.add(where, f"`measured: none` with a why_not_measured of {len(why.strip())} chars "
                         f"(need {MIN_WHY_NOT_MEASURED}). An unexplained gap is indistinguishable "
                         f"from an oversight.")
        statuses = {fi.get("status") for fi in control.get("findings") or [] if isinstance(fi, dict)}
        wrong = sorted(s for s in statuses if s != "not_measured")
        if wrong:
            f.add(where, f"is `measured: none` but has finding status(es) {wrong}; a control no case "
                         f"measured cannot produce a measured statement")
    else:
        if "why_not_measured" in control:
            f.add(where, "has `why_not_measured:` without `measured: none`")
        for j, entry in enumerate(measured_by or []):
            at = f"{where} measured_by[{j}]"
            if not isinstance(entry, dict):
                f.add(at, f"is a {type(entry).__name__}, not a mapping")
                continue
            unknown = sorted(set(entry) - MEASURED_BY_KEYS)
            if unknown:
                f.add(at, f"unknown key(s) {unknown}")
            case = entry.get("case")
            if not isinstance(case, str) or case not in registered:
                f.add(at, f"case {case!r} is not in the sealed register")
            elif RESTRICTION_NEVER & restrictions.get(case, set()):
                f.add(at, f"{case} carries a NEVER_CITE restriction; it may be cited as nothing at "
                          f"all, including as the case that measured a control")
            why = (entry.get("why") or "").strip()
            if len(why) < MIN_WHY:
                f.add(at, f"`why` is {len(why)} chars (need {MIN_WHY})")
        statuses = {fi.get("status") for fi in control.get("findings") or [] if isinstance(fi, dict)}
        if "not_measured" in statuses:
            f.add(where, "has `measured_by:` and also a `not_measured` finding; a control cannot "
                         "both rest on a case and report that no case looked at it")


def check_findings(control: dict, registered: set[str], verdicts: dict[str, str],
                   restrictions: dict[str, set[str]], f: Findings) -> None:
    cid = control.get("id")
    detect = control.get("detect") if isinstance(control.get("detect"), dict) else {}
    allowed_values = detect.get("values")

    for j, fi in enumerate(control.get("findings") or []):
        where = f"control {cid} findings[{j}]"
        if not isinstance(fi, dict):
            f.add(where, f"is a {type(fi).__name__}, not a mapping")
            continue
        unknown = sorted(set(fi) - FINDING_KEYS)
        if unknown:
            f.add(where, f"unknown key(s) {unknown}")

        # --- the predicate must be able to fire
        when = fi.get("when")
        if not isinstance(when, dict) or not when:
            f.add(where, "has no `when:` predicate, so the report cannot decide when to emit it")
        else:
            unknown = sorted(set(when) - WHEN_KEYS)
            if unknown:
                f.add(where, f"`when` has unknown key(s) {unknown}")
            if "observation" in when and when["observation"] not in OBSERVATIONS:
                f.add(where, f"`when.observation` is {when['observation']!r}, not one of "
                             f"{sorted(OBSERVATIONS)}")
            if "value" in when:
                if not isinstance(allowed_values, list) or not allowed_values:
                    f.add(where, "matches on `when.value` but the detect rule declares no `values:` "
                                 "list, so nothing constrains what the parser may produce and this "
                                 "predicate cannot be shown to be reachable")
                elif when["value"] not in allowed_values:
                    f.add(where, f"`when.value` is {when['value']!r}, which the detect rule cannot "
                                 f"produce (its values are {allowed_values}). This rule can never "
                                 f"fire, and a rule that never fires reads as one that passed.")

        # --- the prose a machine cannot supply
        says = (fi.get("says") or "").strip()
        if len(says) < MIN_SAYS:
            f.add(where, f"`says` is {len(says)} chars (need {MIN_SAYS})")

        status = fi.get("status")
        if status not in STATUSES:
            f.add(where, f"`status` is {status!r}, not one of {sorted(STATUSES)}")
            continue

        cites = fi.get("cites")
        if cites is None:
            f.add(where, "has no `cites:` key at all. An absent list and an empty one mean "
                         "different things here, so the key is required even when empty.")
            cites = []
        elif not isinstance(cites, list):
            f.add(where, f"`cites` is a {type(cites).__name__}, not a list")
            cites = []

        if status == "not_measured":
            if cites:
                f.add(where, f"status not_measured but cites {cites}; a control no case measured has "
                             f"nothing to cite, and citing anything here would manufacture evidence "
                             f"from its absence")
            why = (fi.get("why_not_measured") or "").strip()
            if len(why) < MIN_WHY_NOT_MEASURED:
                f.add(where, f"status not_measured with a why_not_measured of {len(why)} chars "
                             f"(need {MIN_WHY_NOT_MEASURED}). 'Not measured' must say why, or a "
                             f"reader cannot tell an evidence gap from a tooling gap.")
            continue

        consequence = (fi.get("consequence") or "").strip()
        if len(consequence) < MIN_CONSEQUENCE:
            f.add(where, f"`consequence` is {len(consequence)} chars (need {MIN_CONSEQUENCE}); a "
                         f"finding a reader cannot act on is a sentence, not a recommendation")
        if not cites:
            f.add(where, f"status {status} cites nothing. Every statement about the reader's system "
                         f"must name the case that licenses it.")

        need = STATUS_REQUIRES_VERDICT.get(status)
        needs_scope = False
        for case in cites:
            at = f"{where} cites {case}"
            if not isinstance(case, str) or case not in registered:
                f.add(at, "is not in the sealed register")
                continue
            rs = restrictions.get(case, set())
            unclassified = sorted(r for r in rs if r not in KNOWN_RESTRICTIONS)
            if unclassified:
                f.add(at, f"carries restriction(s) {unclassified} this gate does not classify. An "
                          f"unknown restriction must not be treated as no restriction; classify it "
                          f"in check_controls.py before citing the case.")
            if RESTRICTION_NEVER & rs:
                f.add(at, "carries a NEVER_CITE restriction and may be cited as nothing at all")
            if (RESTRICTION_CONTEXT_ONLY & rs) and status != "context_only":
                f.add(at, f"carries {sorted(RESTRICTION_CONTEXT_ONLY & rs)} and may appear only "
                          f"under status context_only, not {status}")
            if (RESTRICTION_NOT_ESTABLISHED_ONLY & rs) and status != "not_established":
                f.add(at, f"carries {sorted(RESTRICTION_NOT_ESTABLISHED_ONLY & rs)} and may appear "
                          f"only under status not_established, not {status}. An INCONCLUSIVE verdict "
                          f"is not evidence against a claim.")
            if RESTRICTION_NEEDS_SCOPE & rs:
                needs_scope = True
            if need is not None:
                got = verdicts.get(case)
                if got != need:
                    f.add(at, f"has verdict {got!r} on disk but status {status} requires {need}")

        if needs_scope:
            note = (fi.get("scope_note") or "").strip()
            if len(note) < MIN_SCOPE_NOTE:
                f.add(where, f"cites a case restricted to part of its claim (PARTIAL or "
                             f"REPLICATION_POSITION_BOUND) with a scope_note of {len(note)} chars "
                             f"(need {MIN_SCOPE_NOTE}). The restriction travels with the citation; "
                             f"dropping it publishes a wider claim than the evidence carries.")
        elif fi.get("scope_note"):
            f.add(where, "has a `scope_note` but cites no case that needs one. A scope note on an "
                         "unrestricted citation trains readers to skip them.")


# --------------------------------------------------------------------------------- field paths


def model_paths(service: str, ops: list[str], depth: int = 4) -> set[str]:
    """Every lower-cased dotted member path reachable in `ops`' input shapes, to `depth`.

    Introspected live rather than transcribed. The point is not to prove a path is *used* but that it
    *exists*: a detection rule keyed on a field the service model does not have can never match, and
    would report NOT_DECLARED for every template forever — a false clean, which is the failure this
    whole file is arranged to prevent.
    """
    import boto3  # noqa: PLC0415 - only --verify-field-paths needs an SDK

    model = boto3.session.Session()._session.get_service_model(service)  # noqa: SLF001
    out: set[str] = set()

    def walk(shape, prefix: str, level: int) -> None:
        if level > depth:
            return
        members = getattr(shape, "members", None)
        if members:
            for name, sub in members.items():
                path = f"{prefix}{name}".lower()
                out.add(path)
                walk(sub, f"{path}.", level + 1)
            return
        member = getattr(shape, "member", None)   # a list: its element's members hang off the list
        if member is not None:
            walk(member, prefix, level)

    for op in ops:
        try:
            shape = model.operation_model(op).input_shape
        except Exception:                          # noqa: BLE001 - an absent op is a finding, not a crash
            continue
        if shape is not None:
            walk(shape, "", 1)
    return out


def check_field_paths(data: dict, controls: list[dict], f: Findings) -> None:
    """Every `detect.paths` entry must exist in a service model, or be declared unverifiable.

    The exemption list is authored in the YAML rather than inferred here, and it is checked in BOTH
    directions: a path exempted that the model *does* have is reported too. Otherwise the exemption
    list becomes the place a real typo hides, which is the standing hazard of any "this guard need
    not look here" clause (`feedback_guard_scope_is_a_claim`).
    """
    known = (model_paths("bedrock-agentcore-control",
                         ["CreateGateway", "CreateGatewayTarget", "CreatePolicy",
                          "CreatePolicyEngine", "CreateHarness", "CreateMemory", "CreateRuntime"])
             | model_paths("bedrock", ["CreateGuardrail", "UpdateGuardrail"]))
    if len(known) < 100:
        die(f"introspection yielded only {len(known)} field path(s); the SDK in this interpreter is "
            f"not the one this check needs and every path would be reported as unverifiable")

    exempt: dict[str, str] = {}
    for entry in data.get("unverifiable_paths") or []:
        if not isinstance(entry, dict) or not entry.get("path") or not entry.get("why"):
            f.add("unverifiable_paths", f"entry {entry!r} needs both `path:` and `why:`")
            continue
        if len((entry["why"] or "").strip()) < MIN_WHY:
            f.add("unverifiable_paths", f"{entry['path']}: `why` is under {MIN_WHY} chars")
        exempt[entry["path"]] = entry["why"]

    used: set[str] = set()
    for c in controls:
        detect = c.get("detect") if isinstance(c.get("detect"), dict) else {}
        for path in detect.get("paths") or []:
            used.add(path)
            if path in known:
                continue
            if path in exempt:
                continue
            f.add(f"control {c.get('id')}", f"detect path {path!r} is in no service model and is "
                                            f"not listed under `unverifiable_paths:`. It can never "
                                            f"match, so the control would report NOT_DECLARED for "
                                            f"every template that ever configures it.")
        value_from = detect.get("value_from")
        if value_from and value_from not in (detect.get("paths") or []):
            f.add(f"control {c.get('id')}", f"`value_from: {value_from}` is not one of this rule's "
                                            f"own paths, so the value would be read from a field the "
                                            f"rule never matched on")

    for path, _ in sorted(exempt.items()):
        if path not in used:
            f.add("unverifiable_paths", f"{path!r} is exempted but no control uses it")
        elif path in known:
            f.add("unverifiable_paths", f"{path!r} is exempted as unverifiable but the service model "
                                        f"does have it. A stale exemption is where a real typo hides.")
    print(f"    {len(used)} detect path(s), {len(used & known)} verified against a live service "
          f"model, {len(exempt)} declared unverifiable with a reason")


# --------------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--controls", type=Path, default=CURATION)
    ap.add_argument("--verify-field-paths", action="store_true",
                    help="also re-introspect the pinned SDK and check every detect path exists. "
                         "Needs boto3, so it is opt-in; the publish chain passes it.")
    args = ap.parse_args(argv)

    if not args.controls.is_file():
        die(f"{args.controls} does not exist")
    data = load_yaml_no_duplicate_keys(args.controls)
    registered, verdicts = read_verdicts()
    restrictions = read_restrictions()
    print(f"=== control curation gate\n    {len(registered)} registered case(s), "
          f"{len(verdicts)} live verdict(s), {len(restrictions)} case(s) carrying a restriction")

    f = Findings()
    controls = check_shape(data, f)
    for control in controls:
        check_measured(control, registered, restrictions, f)
        check_findings(control, registered, verdicts, restrictions, f)
    if args.verify_field_paths:
        check_field_paths(data, controls, f)

    return f.report(f"{len(controls)} control(s) in {args.controls.name}")


if __name__ == "__main__":
    sys.exit(main())
