#!/usr/bin/env python3
"""Turn a submitted repository's infrastructure-as-code into a control inventory. No judgment.

WHAT THIS PROGRAM IS AND IS NOT

It reads CloudFormation templates, CDK synth output and Terraform plan JSON, and records what they
declare about the AgentCore and Bedrock Guardrails controls named in `platform/curation/controls.yaml`.
It records **only what it saw, with the file and line it saw it at**. It reaches no conclusion; that
is `report.py`'s job, and the split is deliberate — an inventory a reader can check line by line is
what makes the report auditable rather than authoritative.

THREE THINGS IT MUST NEVER DO, AND WHY

1. **It never touches an AWS account.** Not the submitter's, not ours. A live audit would need
   credentials into someone else's account, which is a liability no report is worth; and it would
   destroy comparability, because a live reading varies Region, model and network position — the
   dimensions this study's replication discipline holds fixed. A static read of a template needs no
   credentials at all, which is its own security argument and the reason the scope was chosen.

2. **It never executes the submission.** No `cdk synth`, no `terraform`, no import, no eval. A
   submitted repository is untrusted input and running its build system to learn what it declares
   would hand it our machine. The cost is real and is stated in the output rather than hidden:
   Terraform HCL and un-synthesised CDK source are NOT parsed, because parsing them faithfully means
   running them. A submission of only HCL yields an inventory that says so — `n_files_parsed: 0` and
   a caveat naming the reason — never an empty inventory that reads like a clean template.

3. **It never resolves a reference.** `!Ref`, `!GetAtt`, `Fn::If`, a Terraform interpolation and a
   CDK token are recorded verbatim as the strings they are. A resolver would be inventing a value the
   template does not contain, and a report built on an invented value is worse than one that says
   "this is `!Ref EngineMode`, and what that resolves to at deploy time is outside what a static read
   can see."

WHY YAML'S COMPOSER, FOR JSON TOO

Every site in the inventory carries a real line number, because "your gateway is in LOG_ONLY" is a
claim a reader must be able to walk to. `json.loads` discards positions, so both formats go through
`yaml.compose_all`, which returns a node tree with `start_mark.line` on every node — and JSON is a
subset of YAML, so one code path serves both. It also handles CloudFormation's short tags (`!Ref`,
`!Sub`) for free: composing does not resolve tags, so an unknown one is data rather than an error,
where `yaml.safe_load` would refuse the file outright.

LIMITS ARE ENFORCED, NOT DOCUMENTED

Untrusted input gets a byte ceiling, a file-count ceiling, a nesting-depth ceiling and a refusal to
follow symlinks or leave the submission root. Each limit that bites is named in the output, because a
scan that silently stopped early and a scan that found nothing produce the same empty result, and only
one of them is a finding (`feedback_abort_hides_coverage`).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Ceilings. A submission that trips one is reported, never truncated in silence.
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_FILES_CONSIDERED = 4000
MAX_DEPTH = 40

CANDIDATE_SUFFIXES = {".json", ".yaml", ".yml", ".template"}

# Directories a submitted repository carries that cannot hold a template worth reading, skipped for
# time rather than for safety. `cdk.out` is deliberately NOT here: it is where synth output lives and
# is the single most valuable directory in a CDK submission.
SKIP_DIRS = {".git", "node_modules", ".terraform", "__pycache__", ".venv", "venv",
             ".mypy_cache", ".pytest_cache", "dist", "build", ".next", "coverage"}


def die(msg: str) -> None:
    print(f"PARSE-FAIL: {msg}", file=sys.stderr)
    raise SystemExit(2)


# --------------------------------------------------------------------------------- node walking


@dataclass
class Scalar:
    """A leaf value and where it was written. `tag` preserves `!Ref` and friends unresolved."""

    value: str
    line: int
    tag: str | None = None

    def as_json(self) -> dict:
        out: dict = {"value": self.value, "line": self.line}
        if self.tag:
            out["unresolved_tag"] = self.tag
        return out


@dataclass
class Doc:
    """One parsed document: its flattened leaves and the problems parsing it produced."""

    path: str
    root: object = None
    error: str | None = None


def _short_tag(node) -> str | None:
    """`!Ref` for a CloudFormation short tag, None for an ordinary scalar/map/sequence.

    A tag other than the implicit resolver's own means the template said something a static read
    cannot evaluate, and the report has to be able to say so rather than print a value that is really
    a reference to one.
    """
    tag = getattr(node, "tag", "") or ""
    if tag.startswith("tag:yaml.org,2002:"):
        return None
    return tag.lstrip("!") or None


def compose_file(path: Path, text: str) -> Doc:
    """Compose `text` into plain Python, keeping a line number on every leaf.

    Multi-document YAML is folded into a list, because a submitted file may hold several templates and
    dropping all but the first would under-report a real declaration.
    """
    import yaml  # noqa: PLC0415 - the parser is the only thing that needs it

    def convert(node, depth: int):
        if depth > MAX_DEPTH:
            raise ValueError(f"nesting deeper than {MAX_DEPTH} levels")
        if isinstance(node, yaml.MappingNode):
            out = {}
            for k, v in node.value:
                key = getattr(k, "value", None)
                if isinstance(key, str):
                    out[key] = convert(v, depth + 1)
            return out
        if isinstance(node, yaml.SequenceNode):
            return [convert(v, depth + 1) for v in node.value]
        return Scalar(value=str(node.value), line=node.start_mark.line + 1, tag=_short_tag(node))

    try:
        docs = [convert(n, 0) for n in yaml.compose_all(text) if n is not None]
    except (yaml.YAMLError, ValueError) as e:
        return Doc(path=str(path), error=f"{type(e).__name__}: {str(e)[:200]}")
    if not docs:
        return Doc(path=str(path), error="parsed to nothing")
    return Doc(path=str(path), root=docs[0] if len(docs) == 1 else docs)


def norm_segment(key: str) -> str:
    """`policy_engine_configuration` and `policyEngineConfiguration` → `policyengineconfiguration`.

    The authored paths in `controls.yaml` are derived from botocore's camelCase member names, lower-
    cased — so a segment there has no separator inside it. CloudFormation keeps camelCase and matches
    directly; **Terraform's AWS provider renames every attribute to snake_case**, so without dropping
    `_` and `-` a Terraform plan would match nothing and every control would come back NOT_DECLARED.
    That failure mode is a false clean — the single worst output this program can produce — which is
    why normalisation is preferred to the alternative of not supporting Terraform at all.

    The cost is a theoretical collision: a template with both `policy_engine.mode` and
    `policyengine.mode` would merge them. Both would be reported as sites of the same control with
    their own line numbers, so a reader still sees exactly what was matched and where.
    """
    return str(key).lower().replace("_", "").replace("-", "")


def flatten(obj, prefix: str = "", out: dict[str, list[Scalar]] | None = None,
            depth: int = 0) -> dict[str, list[Scalar]]:
    """Normalised dotted paths → every scalar found at that path.

    List indices are **collapsed**, so `filtersConfig[0].type` and `filtersConfig[3].type` both land
    under `filtersconfig.type` with two entries. That is what makes one authored path in
    `controls.yaml` match a guardrail with any number of filters, and it is why the value is a list:
    a control that reads a single value from a repeated field has to be able to see all of them
    rather than the first.
    """
    if out is None:
        out = {}
    if depth > MAX_DEPTH:
        return out
    if isinstance(obj, Scalar):
        if prefix:
            out.setdefault(prefix, []).append(obj)
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            seg = norm_segment(k)
            key = f"{prefix}.{seg}" if prefix else seg
            flatten(v, key, out, depth + 1)
        return out
    if isinstance(obj, list):
        for v in obj:
            flatten(v, prefix, out, depth + 1)
    return out


# --------------------------------------------------------------------------------- resources


@dataclass
class Resource:
    """One declared resource, with its type, its origin and its flattened properties."""

    logical_id: str
    type: str
    file: str
    line: int
    flat: dict[str, list[Scalar]] = field(default_factory=dict)
    source_kind: str = "cloudformation"


def _line_of(obj) -> int:
    """The smallest line number anywhere under `obj`, or 0. Used to anchor a resource."""
    if isinstance(obj, Scalar):
        return obj.line
    if isinstance(obj, dict):
        lines = [_line_of(v) for v in obj.values()]
    elif isinstance(obj, list):
        lines = [_line_of(v) for v in obj]
    else:
        return 0
    lines = [n for n in lines if n]
    return min(lines) if lines else 0


def roots_of(doc: Doc) -> list[dict]:
    """Every top-level mapping in the file.

    `compose_file` folds a multi-document YAML stream into a list, so an extractor that accepts only a
    dict silently reads document 1 and drops the rest — and a submission that puts its gateway in the
    second document of a file reads NOT_DECLARED. Same class of false clean as unparsed HCL, so it gets
    the same treatment: read them all.
    """
    if isinstance(doc.root, dict):
        return [doc.root]
    if isinstance(doc.root, list):
        return [d for d in doc.root if isinstance(d, dict)]
    return []


def resources_from_cloudformation(doc: Doc) -> list[Resource]:
    return [r for root in roots_of(doc) for r in _cfn_one(doc, root)]


def _cfn_one(doc: Doc, root: dict) -> list[Resource]:
    res = root.get("Resources") or root.get("resources")
    if not isinstance(res, dict):
        return []
    out = []
    for logical_id, body in res.items():
        if not isinstance(body, dict):
            continue
        rtype = body.get("Type") or body.get("type")
        rtype = rtype.value if isinstance(rtype, Scalar) else None
        if not rtype:
            continue
        props = body.get("Properties") or body.get("properties") or {}
        out.append(Resource(logical_id=str(logical_id), type=rtype, file=doc.path,
                            line=_line_of(body), flat=flatten(props)))
    return out


def resources_from_terraform_plan(doc: Doc) -> list[Resource]:
    """Resources from a `terraform show -json` plan, walking `planned_values.root_module`.

    Plan JSON rather than HCL for the reason in this module's docstring: a plan is already-evaluated
    output, so reading it needs no interpreter. Child modules are walked, because a submission that
    puts its gateway in a module would otherwise report NOT_DECLARED for everything — the exact false
    clean this whole program is arranged to avoid.
    """
    return [r for root in roots_of(doc) for r in _tf_one(doc, root)]


def _tf_one(doc: Doc, root: dict) -> list[Resource]:
    planned = root.get("planned_values")
    if not isinstance(planned, dict):
        return []
    out: list[Resource] = []

    def walk_module(module, depth: int = 0) -> None:
        if not isinstance(module, dict) or depth > MAX_DEPTH:
            return
        for r in module.get("resources") or []:
            if not isinstance(r, dict):
                continue
            rtype = r.get("type")
            rtype = rtype.value if isinstance(rtype, Scalar) else None
            if not rtype:
                continue
            addr = r.get("address")
            out.append(Resource(
                logical_id=addr.value if isinstance(addr, Scalar) else str(rtype),
                type=rtype, file=doc.path, line=_line_of(r),
                flat=flatten(r.get("values") or {}), source_kind="terraform_plan"))
        for child in module.get("child_modules") or []:
            walk_module(child, depth + 1)

    walk_module(planned.get("root_module"))
    return out


# --------------------------------------------------------------------------------- discovery


@dataclass
class Scan:
    considered: int = 0
    parsed: int = 0
    bytes_read: int = 0
    skipped: list[dict] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    hcl_files: int = 0
    limit_hit: str | None = None

    def skip(self, path: str, why: str) -> None:
        self.skipped.append({"path": path, "why": why})


def discover(root: Path, scan: Scan) -> list[Resource]:
    """Every resource in every parseable template under `root`, refusing to leave it."""
    root = root.resolve()
    if not root.is_dir():
        die(f"{root} is not a directory")
    resources: list[Resource] = []

    for path in sorted(root.rglob("*")):
        if scan.considered >= MAX_FILES_CONSIDERED:
            scan.limit_hit = (f"stopped after considering {MAX_FILES_CONSIDERED} files; the "
                              f"submission is larger than this parser will read, so the inventory "
                              f"below is INCOMPLETE and its NOT_DECLARED results mean 'not seen', "
                              f"not 'not present'")
            break
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_symlink():
            scan.skip(str(path.relative_to(root)), "symlink; not followed, because a submitted link "
                                                   "can point anywhere on the reading machine")
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() == ".tf":
            scan.hcl_files += 1
            continue
        if path.suffix.lower() not in CANDIDATE_SUFFIXES:
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except ValueError:
            scan.skip(str(path), "resolves outside the submission root")
            continue

        scan.considered += 1
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            scan.skip(str(path.relative_to(root)), f"{size} bytes, over the {MAX_FILE_BYTES}-byte "
                                                   f"per-file ceiling")
            continue
        if scan.bytes_read + size > MAX_TOTAL_BYTES:
            scan.limit_hit = (f"stopped after reading {scan.bytes_read} bytes; the inventory is "
                              f"INCOMPLETE and NOT_DECLARED below means 'not seen'")
            break
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            scan.skip(str(path.relative_to(root)), f"unreadable as UTF-8: {type(e).__name__}")
            continue
        scan.bytes_read += size

        # Cheap pre-filter, so a repository of unrelated JSON is not composed in full.
        if not any(marker in text for marker in ("Resources", "resources", "planned_values")):
            continue
        doc = compose_file(path.relative_to(root), text)
        if doc.error:
            scan.skip(str(path.relative_to(root)), f"not parseable: {doc.error}")
            continue
        found = resources_from_cloudformation(doc) or resources_from_terraform_plan(doc)
        if found:
            scan.parsed += 1
            resources.extend(found)

    if scan.hcl_files:
        scan.caveats.append(
            f"{scan.hcl_files} Terraform HCL file(s) (.tf) were found and NOT parsed. Reading HCL "
            f"faithfully means evaluating it, and this parser does not execute a submission. Run "
            f"`terraform show -json <plan>` and submit that instead; until then, no control below is "
            f"reported on the strength of your HCL, in either direction.")
    if scan.limit_hit:
        scan.caveats.append(scan.limit_hit)
    return resources


# --------------------------------------------------------------------------------- observations


def match_control(control: dict, resources: list[Resource]) -> dict:
    """What the templates say about one control: DECLARED with sites and values, or NOT_DECLARED.

    A path matches a flattened key when the path's segments occur in the key as a **whole-segment
    run**, so `policyengineconfiguration.mode` is found whether the template nests it under
    `Properties`, under a CDK construct path, or at the top of a Terraform `values` block. Segments
    rather than substring: `mode` must not match `crossregionmode`, and a substring test would.

    THE RUN IS MATCHED IN BOTH DIRECTIONS, AND THAT IS NOT A CONVENIENCE
    -------------------------------------------------------------------
    `flatten` records only scalars, so every key ends at a leaf. An authored path that names a
    **structure** — `targetconfiguration.mcp.lambda`, whose members are `lambdaArn` and nothing a
    reader writes at that level — is therefore a path no key can ever end with, and a suffix-only test
    reports such a control NOT_DECLARED for every submission on earth. That is the false clean this
    whole program exists to avoid, and it is worse than the usual kind because it is invisible: the
    control appears in the report, in the state that reads "not seen in your files".

    So a key also matches when the path is a prefix of it (or sits inside it) at segment boundaries:
    declaring `TargetConfiguration.Mcp.Lambda.LambdaArn` **is** declaring the structure above it.
    `value_from` keeps the narrower suffix test below, so a control's reported VALUE can still only
    come from the exact scalar the rule names, never from a descendant of a matched structure.
    """
    detect = control.get("detect") or {}
    def norm_path(p: str) -> str:
        return ".".join(norm_segment(s) for s in str(p).split("."))

    def path_matches(key: str, p: str) -> bool:
        ks, ps = key.split("."), p.split(".")
        return any(ks[i:i + len(ps)] == ps for i in range(len(ks) - len(ps) + 1))

    paths = [norm_path(p) for p in (detect.get("paths") or [])]
    # One control can live on more than one resource shape: `executionRoleArn` is a harness member and
    # `roleArn` a gateway member, and a single hint would silently exclude one of them — reported as
    # NOT_DECLARED, which reads as a fact about the template rather than about this rule.
    raw_hint = detect.get("type_hint") or []
    hints = [str(h).lower() for h in ([raw_hint] if isinstance(raw_hint, str) else raw_hint) if h]
    value_from = norm_path(detect.get("value_from")) if detect.get("value_from") else None
    allowed = detect.get("values")

    sites: list[dict] = []
    values: list[dict] = []
    for r in resources:
        if hints and not any(h in r.type.lower() for h in hints):
            continue
        for key, scalars in r.flat.items():
            for p in paths:
                if not path_matches(key, p):
                    continue
                for s in scalars:
                    site = {"resource": r.logical_id, "resource_type": r.type,
                            "file": r.file, "line": s.line, "path": key,
                            "matched_rule_path": p, "source_kind": r.source_kind,
                            **s.as_json()}
                    sites.append(site)
                    if value_from and (key == value_from or key.endswith("." + value_from)):
                        values.append(site)
                break

    observation = "DECLARED" if sites else "NOT_DECLARED"
    out: dict = {"control": control.get("id"), "label": control.get("label"),
                 "observation": observation, "sites": sites, "value": None,
                 "values_seen": [], "unresolved": []}

    seen = []
    for v in values:
        if v.get("unresolved_tag"):
            out["unresolved"].append(v)
            continue
        seen.append(v["value"])
    out["values_seen"] = sorted(set(seen))

    # A single value is only reported when the templates agree on one. Two gateways in different
    # modes is a real and important state, and collapsing it to the first would hide the LOG_ONLY one.
    if len(out["values_seen"]) == 1:
        out["value"] = out["values_seen"][0]
    elif len(out["values_seen"]) > 1:
        out["value"] = None
        out["disagreement"] = out["values_seen"]

    if allowed:
        unknown = [v for v in out["values_seen"] if v not in allowed]
        if unknown:
            out["values_outside_the_declared_enum"] = unknown
    return out


def build_inventory(root: Path, controls: list[dict]) -> dict:
    scan = Scan()
    resources = discover(root, scan)
    observations = [match_control(c, resources) for c in controls]

    if not resources:
        scan.caveats.append(
            "ZERO resources were parsed. This is not a clean result: every control below reads "
            "NOT_DECLARED because nothing was read, not because nothing was declared. Check that the "
            "submission contains CloudFormation templates, `cdk.out/*.template.json` synth output, "
            "or `terraform show -json` output.")

    return {
        "schema": "grx-inventory/1",
        "submission": {
            "files_considered": scan.considered,
            "files_yielding_resources": scan.parsed,
            "bytes_read": scan.bytes_read,
            "resources_found": len(resources),
            "skipped": scan.skipped,
            "hcl_files_not_parsed": scan.hcl_files,
            "complete": scan.limit_hit is None,
        },
        "caveats": scan.caveats,
        "resources": sorted(
            [{"logical_id": r.logical_id, "type": r.type, "file": r.file, "line": r.line,
              "source_kind": r.source_kind, "n_properties": len(r.flat)} for r in resources],
            key=lambda d: (d["file"], d["line"], d["logical_id"])),
        "observations": observations,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submission", type=Path, required=True,
                    help="directory holding the submitted repository. Never executed, never left.")
    ap.add_argument("--controls", type=Path,
                    default=Path(__file__).resolve().parent.parent / "curation" / "controls.yaml")
    ap.add_argument("--out", type=Path, help="write the inventory here (default: stdout)")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build"))
    import check_controls  # noqa: PLC0415 - reuse the gate's loader, never a second YAML grammar

    data = check_controls.load_yaml_no_duplicate_keys(args.controls)
    controls = data.get("controls") or []
    if not controls:
        die(f"{args.controls} declares no controls; an inventory over zero controls would report "
            f"nothing and exit 0")

    inventory = build_inventory(args.submission, controls)
    text = json.dumps(inventory, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        s = inventory["submission"]
        print(f"wrote {args.out} — {s['resources_found']} resource(s) from "
              f"{s['files_yielding_resources']} file(s); "
              f"{sum(1 for o in inventory['observations'] if o['observation'] == 'DECLARED')} of "
              f"{len(controls)} control(s) DECLARED")
        for caveat in inventory["caveats"]:
            print(f"  caveat: {caveat}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
