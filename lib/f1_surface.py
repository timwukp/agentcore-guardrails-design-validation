#!/usr/bin/env python3
"""Enumerate the config surface F1 asks about, across all four Bedrock service models.

    .venv-oracle/bin/python lib/f1_surface.py --json          # under the pinned SDK
    python3 lib/f1_surface.py                                 # human-readable, ambient SDK

WHY A SEPARATE MODULE, AND WHY FOUR SERVICES
--------------------------------------------
Same split as `lib/ar_surface.py`: this sweep's whole content is *which fields the SDK
model exposes*, so it must run under the pinned oracle interpreter (`.venv-oracle`,
botocore 1.43.67). That interpreter carries botocore only — no numpy, no scipy — so it
cannot import `lib/oracle.py` and cannot evaluate a sealed oracle. The sweep therefore
imports nothing but the standard library and botocore, and `f1_config/02_model_surface.py`
runs it as a subprocess and evaluates the oracles in the parent.

Four services, not two, and this is the correction of a mistake this project has already
made **twice**. Both times the method was the same: probe one service, find an empty list,
publish the absence.

  * `PutEnforcedGuardrailConfiguration` was reported absent after searching
    `bedrock-agentcore-control`. It is on `bedrock`.
  * The Optimization A/B-test and Recommendation groups were reported absent after
    searching `bedrock-agentcore-control`. They are on the data-plane `bedrock-agentcore`.

An absence claim is a claim about a search, so every direction here reports what it
**EXAMINED** — services, operations, shapes, members — beside what it found. A direction
that examined zero of something is a broken instrument, not a clean result
(`feedback_zero_file_scan_is_error`).

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
It does not decide anything. Every function returns counts, names and values; the mapping
onto a sealed oracle lives in the case script, where it can be read next to the oracle text
it is being compared against. A sweep that returned verdicts would put the classification
inside the instrument, where nobody re-reads it.

It also makes no AWS call. `boto3.client` loads a JSON service model off disk: no socket is
opened, no credential is used, nothing leaves the machine. `region_name` is passed
explicitly because `~/.aws/config` carries only `[default]`, and an unset region raises
`NoRegionError` — which would look like a failed sweep rather than a missing setting.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import boto3
import botocore
from botocore.validate import ParamValidator

# The four services that between them carry every surface F1 asks about. `bedrock` is the
# Guardrails control plane (CreateGuardrail, PutEnforcedGuardrailConfiguration);
# `bedrock-runtime` the Guardrails data plane (ApplyGuardrail, InvokeGuardrailChecks);
# `bedrock-agentcore-control` the AgentCore control plane (CreateGateway, CreatePolicy);
# `bedrock-agentcore` the AgentCore data plane (Optimization, Evaluations, A/B testing).
SERVICES = ("bedrock", "bedrock-runtime",
            "bedrock-agentcore-control", "bedrock-agentcore")

MAX_DEPTH = 12

# Enums read by exact shape name, each tagged with the case whose oracle names it. Read by
# NAME rather than by scanning for a value set, because the oracle is an exact-set claim:
# "the enum is exactly {...}". Scanning for a set that matches would find whatever matches
# and could never report a mismatch.
NAMED_ENUMS: dict[str, tuple[str, str]] = {
    # shape name                        -> (service, case that reads it)
    "GatewayPolicyEngineMode":          ("bedrock-agentcore-control", "F1-5"),
    "PolicyValidationMode":             ("bedrock-agentcore-control", "F1-3"),
    "PolicyStatus":                     ("bedrock-agentcore-control", "F1-3"),
    "EnforcementMode":                  ("bedrock-agentcore-control", "F1-1"),
    "GatewayInterceptionPoint":         ("bedrock-agentcore-control", "F1-16"),
    "GuardrailContentFilterType":       ("bedrock", "F1-7"),
    "GuardrailPiiEntityType":           ("bedrock", "F1-9"),
    "GuardrailTopicsTierName":          ("bedrock", "F1-10"),
    "GuardrailContentFiltersTierName":  ("bedrock", "F1-10"),
    "GuardrailFilterStrength":          ("bedrock", "F1-11"),
    "GuardrailContentFilterAction":     ("bedrock", "F1-11"),
    "GuardrailStreamProcessingMode":    ("bedrock-runtime", "F1-12"),
    "GuardrailContentQualifier":        ("bedrock-runtime", "F1-27"),
    "GuardrailChecksContentFilterCategory":         ("bedrock-runtime", "F1-7"),
    "GuardrailChecksPromptAttackCategory":          ("bedrock-runtime", "F1-8"),
    "GuardrailChecksSensitiveInformationEntityType": ("bedrock-runtime", "F1-9"),
}

# Capability groups for F1-22 (Optimization exposes Recommendations / Configuration Bundles
# / A/B Testing, Batch Evaluation belongs to Evaluations) and F1-23 (Evaluations exposes
# on-demand, batch and online modes). Each group is a substring matched against operation
# names across ALL FOUR services, and the service each hit came from is part of the result:
# the document's claim is about which capability exists, and reporting where it lives is how
# a reader can check the answer instead of trusting it.
CAPABILITY_GROUPS: dict[str, tuple[str, ...]] = {
    "recommendations":        ("Recommendation",),
    "configuration_bundles":  ("ConfigurationBundle",),
    "ab_testing":             ("ABTest",),
    "batch_evaluation":       ("BatchEvaluation",),
    "online_evaluation":      ("OnlineEvaluation",),
    "evaluation_job":         ("EvaluationJob",),
    "enforced_guardrail":     ("EnforcedGuardrail",),
    "guardrail_checks":       ("InvokeGuardrailChecks",),
    "interceptor":            ("Interceptor",),
}

# Groups matched on the WHOLE operation name rather than as a substring. F1-23's "on-demand"
# mode is the operation literally called `Evaluate`, and `Evaluate` as a substring matches
# every `*Evaluation*` operation there is — so a substring rule would report on-demand
# present because batch exists. An exact rule can return zero, which is what makes it able
# to falsify anything.
CAPABILITY_GROUPS_EXACT: dict[str, tuple[str, ...]] = {
    "on_demand_evaluation": ("Evaluate",),
}

# Tokens whose ABSENCE is itself a claim in the document. Each is scanned across every
# operation name, every shape name and every member path of all four services, and the
# examined counts travel with the answer. `suppressOutput` is the one that matters most:
# it is a Cedar policy EFFECT, and Cedar bodies travel as an opaque `definition.cedar
# .statement` string, so its absence from the model is expected and proves nothing about
# whether the service accepts it. Recording the examined counts is what lets the case
# script say so instead of reading the zero as a finding.
ABSENCE_TOKENS = ("suppressOutput", "streamProcessingMode", "interceptor",
                  "enforcementMode", "validationMode", "crossRegion")


def walk_shape(shape, *, path: str = "", seen: set[str] | None = None,
               depth: int = 0) -> list[dict[str, Any]]:
    """Every member of `shape`, recursively, as flat rows.

    Identical contract to `ar_surface.walk_shape` and identical reason for keying `seen` on
    shape NAME plus path rather than on path alone: a service model is a graph, and a
    self-referential shape walked naively recurses to the interpreter's stack limit, which
    reads as a crashed scan rather than as a completed one.

    Not imported from `ar_surface` on purpose. That module is the instrument of a *published*
    case (F8-8) whose result is dated by the exact code that produced it; importing it here
    would make an edit for F1's benefit silently re-interpret F8-8's evidence. The duplication
    is two dozen lines and it keeps the two findings independent.
    """
    seen = set() if seen is None else seen
    rows: list[dict[str, Any]] = []
    if shape is None or depth > MAX_DEPTH:
        return rows
    key = f"{getattr(shape, 'name', '?')}@{path}"
    if key in seen:
        return rows
    seen.add(key)
    kind = getattr(shape, "type_name", "")
    if kind == "structure":
        required = set(shape.metadata.get("required") or ())
        for name, member in shape.members.items():
            here = f"{path}.{name}" if path else name
            rows.append({
                "path": here, "member": name,
                "shape": getattr(member, "name", "?"), "type": member.type_name,
                "required": name in required,
                "enum": list(getattr(member, "enum", []) or []),
            })
            rows += walk_shape(member, path=here, seen=seen, depth=depth + 1)
    elif kind == "list":
        rows += walk_shape(shape.member, path=f"{path}[]", seen=seen, depth=depth + 1)
    elif kind == "map":
        rows += walk_shape(shape.value, path=f"{path}{{}}", seen=seen, depth=depth + 1)
    return rows


def operation_inventory(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 1: how big the search space is, per service.

    This is the denominator every absence in this sweep is quoted against.
    """
    out: dict[str, Any] = {}
    for svc, client in clients.items():
        model = client.meta.service_model
        out[svc] = {
            "n_operations": len(model.operation_names),
            "n_shapes": len(model.shape_names),
            "api_version": model.api_version,
        }
    return out


def enum_reads(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 2: the named enums, read by exact shape name.

    A shape that is absent is reported as `present: false` with an empty value list, never
    as an empty enum: "the enum is []" and "there is no such shape" are different facts, and
    an ENUM_EXACT oracle fed the first would report a set mismatch when the truth is that
    the surface does not exist.
    """
    out: dict[str, Any] = {}
    for shape_name, (svc, case) in NAMED_ENUMS.items():
        client = clients.get(svc)
        entry: dict[str, Any] = {"service": svc, "read_for_case": case}
        if client is None:
            entry.update({"present": False, "why": f"no client for {svc}", "values": []})
            out[shape_name] = entry
            continue
        model = client.meta.service_model
        if shape_name not in set(model.shape_names):
            entry.update({"present": False, "values": [],
                          "why": f"shape absent from the {svc} model",
                          "n_shapes_examined": len(model.shape_names)})
            out[shape_name] = entry
            continue
        shape = model.shape_for(shape_name)
        entry.update({"present": True,
                      "values": list(getattr(shape, "enum", []) or []),
                      "type": shape.type_name,
                      "metadata": {k: v for k, v in shape.metadata.items()
                                   if k != "enum"}})
        out[shape_name] = entry
    return out


def capability_groups(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 3: which operations exist for each documented capability, and WHERE.

    Matched across all four services because that is the specific error this project made
    twice: two capability groups were reported absent after searching one service, and both
    were on another. The `services_searched` field is part of the answer.
    """
    per_service_ops = {svc: sorted(c.meta.service_model.operation_names)
                       for svc, c in clients.items()}
    out: dict[str, Any] = {"services_searched": list(per_service_ops),
                           "n_operations_searched": sum(len(v) for v in
                                                        per_service_ops.values()),
                           "groups": {}}
    for group, tokens in CAPABILITY_GROUPS.items():
        hits: list[dict[str, str]] = []
        for svc, ops in per_service_ops.items():
            for op in ops:
                if any(t.lower() in op.lower() for t in tokens):
                    hits.append({"service": svc, "operation": op})
        out["groups"][group] = {
            "tokens": list(tokens),
            "match": "substring",
            "present": bool(hits),
            "n_hits": len(hits),
            "services_with_hits": sorted({h["service"] for h in hits}),
            "operations": hits,
        }
    for group, names in CAPABILITY_GROUPS_EXACT.items():
        want = {n.lower() for n in names}
        hits = [{"service": svc, "operation": op}
                for svc, ops in per_service_ops.items()
                for op in ops if op.lower() in want]
        out["groups"][group] = {
            "tokens": list(names),
            "match": "exact_operation_name",
            "match_why": ("`Evaluate` as a substring matches every *Evaluation* operation, "
                          "so a substring rule would report the on-demand mode present "
                          "because the batch mode exists"),
            "present": bool(hits),
            "n_hits": len(hits),
            "services_with_hits": sorted({h["service"] for h in hits}),
            "operations": hits,
        }
    return out


def token_scan(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 4: every ABSENCE_TOKEN against operation names, shape names and members.

    Members are walked over every operation's input AND output shape, so a token that
    appears only on a response is still found. The examined counts are the point: an
    absence quoted without them is indistinguishable from a scan that ran over nothing.
    """
    scanned: dict[str, dict[str, Any]] = {}
    for svc, client in clients.items():
        model = client.meta.service_model
        ops = sorted(model.operation_names)
        member_paths: set[str] = set()
        for op in ops:
            om = model.operation_model(op)
            for io, shape in (("in", om.input_shape), ("out", om.output_shape)):
                for row in walk_shape(shape):
                    member_paths.add(f"{op}:{io}:{row['path']}")
        scanned[svc] = {
            "operations": ops,
            "shape_names": sorted(model.shape_names),
            "member_paths": sorted(member_paths),
        }
    out: dict[str, Any] = {
        "examined": {svc: {"n_operations": len(v["operations"]),
                           "n_shape_names": len(v["shape_names"]),
                           "n_member_paths": len(v["member_paths"])}
                     for svc, v in scanned.items()},
        "tokens": {},
    }
    out["examined_total"] = {
        "n_services": len(scanned),
        "n_operations": sum(v["n_operations"] for v in out["examined"].values()),
        "n_shape_names": sum(v["n_shape_names"] for v in out["examined"].values()),
        "n_member_paths": sum(v["n_member_paths"] for v in out["examined"].values()),
    }
    for token in ABSENCE_TOKENS:
        low = token.lower()
        found: dict[str, dict[str, list[str]]] = {}
        for svc, v in scanned.items():
            ops = [o for o in v["operations"] if low in o.lower()]
            shapes = [s for s in v["shape_names"] if low in s.lower()]
            members = [m for m in v["member_paths"] if low in m.rsplit(":", 1)[-1].lower()]
            if ops or shapes or members:
                found[svc] = {"operations": ops, "shape_names": shapes,
                              # capped so one common token cannot bloat the payload past
                              # what a reader will actually read; n_members carries the
                              # true count so the cap is visible rather than silent
                              "member_paths": members[:40],
                              "n_member_paths": len(members)}
        out["tokens"][token] = {
            "present_anywhere": bool(found),
            "services_with_hits": sorted(found),
            "hits": found,
        }
    return out


def required_fields(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 5: the required-member sets the document's instructions depend on.

    F1-21's oracle is about what is *required*, not what exists, so `required` has to be
    read off the shape metadata rather than inferred from a member being present.
    """
    targets = (
        ("bedrock", "CreateGuardrail", "F1-6/F1-10/F1-11"),
        ("bedrock", "PutEnforcedGuardrailConfiguration", "F1-21"),
        ("bedrock-runtime", "ApplyGuardrail", "F1-13/F1-27"),
        ("bedrock-runtime", "InvokeGuardrailChecks", "F1-2/F1-20"),
        ("bedrock-agentcore-control", "CreatePolicy", "F1-1/F1-3/F1-4"),
        ("bedrock-agentcore-control", "CreatePolicyEngine", "F1-5"),
        ("bedrock-agentcore-control", "CreateGateway", "F1-16"),
    )
    out: dict[str, Any] = {}
    for svc, op, cases in targets:
        client = clients.get(svc)
        key = f"{svc}:{op}"
        if client is None:
            out[key] = {"present": False, "why": f"no client for {svc}", "cases": cases}
            continue
        model = client.meta.service_model
        if op not in set(model.operation_names):
            out[key] = {"present": False, "cases": cases,
                        "why": f"operation absent from the {svc} model",
                        "n_operations_examined": len(model.operation_names)}
            continue
        shape = model.operation_model(op).input_shape
        rows = walk_shape(shape)
        out[key] = {
            "present": True,
            "cases": cases,
            "top_level_members": sorted(shape.members),
            "top_level_required": sorted(shape.metadata.get("required") or ()),
            "n_members_examined": len(rows),
            "required_paths": sorted(r["path"] for r in rows if r["required"]),
        }
    return out


def union_probe(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 6: is `PolicyDefinition` a tagged union, and what does the SDK enforce?

    F1-4's oracle is "exactly one arm is accepted per call", which is a claim about a
    VALIDATOR, so it is answered by running the validator rather than by reading the
    metadata flag. Four probes — one arm, the other arm, both arms, neither arm — and the
    diagnostic strings are kept verbatim: the finding is what the SDK says, and paraphrasing
    it here would put our wording between the reader and the evidence.

    The probes carry a deliberately short `policyEngineId` so a length finding appears in
    every report. That is a control, not sloppiness: it proves the validator ran and
    produced findings at all, so an arm reporting "no union finding" cannot be a validator
    that silently did nothing.
    """
    client = clients.get("bedrock-agentcore-control")
    if client is None:
        return {"available": False, "why": "no bedrock-agentcore-control client"}
    model = client.meta.service_model
    if "CreatePolicy" not in set(model.operation_names):
        return {"available": False,
                "why": "CreatePolicy is absent from this SDK's model",
                "n_operations_examined": len(model.operation_names)}
    ins = model.operation_model("CreatePolicy").input_shape
    definition = model.shape_for("PolicyDefinition")
    validator = ParamValidator()
    # 35 characters is the model's declared minimum for a statement; a shorter one produces
    # a length finding that would mask the union finding under test.
    stmt = "permit(principal, action, resource is AgentCore::Gateway);"
    arms = {
        "cedar_only": {"cedar": {"statement": stmt}},
        "policy_only": {"policy": {"statement": stmt}},
        "both_arms": {"cedar": {"statement": stmt}, "policy": {"statement": stmt}},
        "neither_arm": {},
    }
    probes: dict[str, Any] = {}
    for label, defn in arms.items():
        report = validator.validate(
            {"name": "grx_probe", "policyEngineId": "x", "definition": defn}, ins)
        text = report.generate_report() or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        probes[label] = {
            "definition_keys": sorted(defn),
            "findings": lines,
            "n_findings": len(lines),
            # The control: every arm must produce the engine-id length finding, which proves
            # the validator ran. `union_finding` is the one under test.
            "control_finding_present": any("policyEngineId" in ln for ln in lines),
            "union_finding": [ln for ln in lines if "union" in ln.lower()],
        }
    return {
        "available": True,
        "metadata_says_union": bool(definition.metadata.get("union")),
        "definition_members": {k: v.name for k, v in definition.members.items()},
        "probes": probes,
        "instrument": ("botocore.validate.ParamValidator against the CreatePolicy input "
                       "shape; no request is serialised and no socket is opened"),
    }


def enum_enforcement_probe(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 7: does the SDK refuse an out-of-enum value, or does the server decide?

    This is the same guard F8-5 needed and for the same reason. `botocore.validate` performs
    no enum membership check, so a value outside a documented enum is serialised and sent.
    That changes what an enum read *means*: the model tells us the documented value set, but
    it does not tell us that another value is rejected — and a case that read the enum and
    concluded "the document's value would be refused" would be asserting a client-side check
    that does not exist.

    Probed rather than asserted from reading `validate.py`, because that reading would expire
    the next time botocore adds a branch. If this flag ever flips to True, F1-12's payload
    changes meaning and the flag is in the record for a reader to notice.
    """
    client = clients.get("bedrock-runtime")
    if client is None:
        return {"available": False, "why": "no bedrock-runtime client"}
    model = client.meta.service_model
    name = "GuardrailStreamConfiguration"
    if name not in set(model.shape_names):
        return {"available": False, "why": f"{name} absent from the bedrock-runtime model"}
    shape = model.shape_for(name)
    validator = ParamValidator()
    probes: dict[str, Any] = {}
    # "sync" is in the enum, "ASYNCHRONOUS" is the token the document writes and is not.
    for label, value in (("in_enum", "sync"), ("documented_token", "ASYNCHRONOUS"),
                         ("nonsense", "NOT_A_MODE")):
        report = validator.validate(
            {"guardrailIdentifier": "gr-123456789012", "guardrailVersion": "1",
             "streamProcessingMode": value}, shape)
        text = report.generate_report() or ""
        probes[label] = {"value": value, "findings": text,
                         "refused_client_side": bool(text.strip())}
    return {
        "available": True,
        "shape": name,
        "enum": list(getattr(shape.members["streamProcessingMode"], "enum", []) or []),
        "declared_default": shape.members["streamProcessingMode"].metadata.get("default"),
        "probes": probes,
        "client_side_enforces_enum": any(p["refused_client_side"]
                                        for p in probes.values()),
        "consequence": ("with no client-side enum check, an out-of-enum value reaches the "
                        "service and only the SERVER can reject it. An enum read therefore "
                        "establishes what the documented value set IS, not what happens to "
                        "a value outside it"),
    }


def shape_limits(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 8: the min/max metadata behind every numeric limit the document states.

    Three of F1's oracles are BOUNDARY kinds — F1-10 (200 / 1,000-character denied-topic
    definitions), F1-13 (100,000 / 1,000 / 5,000-character grounding fields), F1-20 (10
    content blocks per message) — and a BOUNDARY verdict needs "accepted at the limit,
    rejected at limit+1". This direction answers the prior question a live probe cannot:
    *is the limit in the model at all?*

    That matters because the two answers put the case on different instruments. A limit the
    model carries is enforced by `ParamValidator` before a socket opens, so the boundary is
    measurable offline for $0 and the finding is dated by the SDK. A limit the model does
    NOT carry can only be enforced by the service, so the boundary needs live calls and the
    finding is dated by the deployment. Deciding that from the shape metadata is why this
    returns raw `metadata` dicts and no booleans: `{'min': 1, 'max': 200}` and `{'min': 1}`
    are different facts about the API, and collapsing either into `has_limit: true` would
    hide which one the reader is looking at.

    Members are reported with their own shape's metadata as well as the member metadata,
    because botocore puts a length constraint on the *referenced shape* while `required`
    lives on the containing structure — reading only one of the two would miss half the
    limits this direction exists to find.
    """
    targets = (
        # (service, shape, case, why this shape is the one the oracle is about)
        ("bedrock", "GuardrailTopicDefinition", "F1-10",
         "the denied-topic definition string whose documented length is 200 chars on "
         "CLASSIC and 1,000 on STANDARD"),
        ("bedrock", "GuardrailTopicsTierConfig", "F1-10",
         "the tier selector, to see whether the definition limit is expressed per tier"),
        ("bedrock", "GuardrailContentFilterConfig", "F1-11",
         "the filter whose input and output strengths and actions the document says are "
         "independent"),
        ("bedrock", "GuardrailPiiEntityConfig", "F1-11",
         "the PII entry, for the same input/output independence claim"),
        ("bedrock", "GuardrailContextualGroundingFilterConfig", "F1-13",
         "the grounding filter carrying the threshold; the documented character limits "
         "would live on the CONTENT it scores, not here"),
        ("bedrock", "GuardrailWordTextString", "F1-26",
         "the custom word-filter term"),
        ("bedrock-runtime", "GuardrailTextBlock", "F1-13",
         "the ApplyGuardrail text block the grounding character limits would constrain"),
        ("bedrock-runtime", "GuardrailChecksMessageList", "F1-20",
         "the InvokeGuardrailChecks message list"),
        ("bedrock-runtime", "GuardrailChecksContentBlockList", "F1-20",
         "the per-message content-block list whose documented cap is 10"),
        ("bedrock-runtime", "GuardrailChecksTextContent", "F1-20",
         "the text inside one checks content block"),
    )
    out: dict[str, Any] = {}
    for svc, shape_name, case, why in targets:
        key = f"{svc}:{shape_name}"
        client = clients.get(svc)
        if client is None:
            out[key] = {"present": False, "read_for_case": case, "why_this_shape": why,
                        "why": f"no client for {svc}"}
            continue
        model = client.meta.service_model
        if shape_name not in set(model.shape_names):
            out[key] = {"present": False, "read_for_case": case, "why_this_shape": why,
                        "why": f"shape absent from the {svc} model",
                        "n_shapes_examined": len(model.shape_names)}
            continue
        shape = model.shape_for(shape_name)
        entry: dict[str, Any] = {
            "present": True, "read_for_case": case, "why_this_shape": why,
            "type": shape.type_name,
            "metadata": dict(shape.metadata),
        }
        if shape.type_name == "structure":
            entry["members"] = {
                name: {"shape": getattr(member, "name", "?"),
                       "type": member.type_name,
                       "metadata": dict(member.metadata),
                       "required": name in set(shape.metadata.get("required") or ())}
                for name, member in shape.members.items()}
        elif shape.type_name == "list":
            entry["member"] = {"shape": getattr(shape.member, "name", "?"),
                               "type": shape.member.type_name,
                               "metadata": dict(shape.member.metadata)}
        out[key] = entry
    return out


def mode_enum_scan(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 9: every enum in all four models, searched for the document's mode tokens.

    Two oracles rest on a token appearing or not appearing in an enum, and neither can be
    answered by reading one named shape:

      * F1-12 says the streaming mode values are `SYNCHRONOUS` and `ASYNCHRONOUS`.
        `GuardrailStreamProcessingMode` says `sync` / `async`. Reading that one shape shows
        the document's tokens are not there, but not that they are nowhere — they could be
        an alias on another shape, and a FALSE published without looking would be the same
        false-absence this module was written to prevent.
      * F1-14 says Automated Reasoning is "detect mode only". A detect/enforce distinction
        would have to be *expressible* for "detect only" to be a constraint rather than a
        vacuous truth, and a mode can live as a value on a differently-named field, which
        no by-name read would find.

    So every enum of every service is walked, the examined count travels with the answer,
    and a hit is reported with its shape name and full value list rather than as a boolean:
    `GuardrailOrigin = [REQUEST, ACCOUNT_ENFORCED, ORGANIZATION_ENFORCED]` matches "ENFORCE"
    as a substring and has nothing to do with an Automated Reasoning mode. Classifying that
    is the case script's job; finding it is this one's.
    """
    tokens = ("SYNCHRONOUS", "ASYNCHRONOUS", "SYNC", "ASYNC", "DETECT", "ENFORCE")
    out: dict[str, Any] = {"tokens": list(tokens), "per_service": {}}
    for svc, client in clients.items():
        model = client.meta.service_model
        enums: dict[str, list[str]] = {}
        for shape_name in sorted(set(model.shape_names)):
            values = list(getattr(model.shape_for(shape_name), "enum", []) or [])
            if values:
                enums[shape_name] = values
        hits: dict[str, list[dict[str, Any]]] = {}
        for token in tokens:
            for shape_name, values in enums.items():
                matched = [v for v in values if token in v.upper()]
                if matched:
                    hits.setdefault(token, []).append(
                        {"shape": shape_name, "matched_values": matched,
                         "all_values": values})
        out["per_service"][svc] = {
            "n_enums_examined": len(enums),
            "n_enum_values_examined": sum(len(v) for v in enums.values()),
            "n_shapes_examined": len(set(model.shape_names)),
            "hits": hits,
        }
    out["examined_total"] = {
        "n_services": len(out["per_service"]),
        "n_enums": sum(v["n_enums_examined"] for v in out["per_service"].values()),
        "n_enum_values": sum(v["n_enum_values_examined"]
                             for v in out["per_service"].values()),
    }
    out["n_hits_total"] = sum(len(v) for s in out["per_service"].values()
                              for v in s["hits"].values())
    return out


def ar_streaming_reach(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 10: can an Automated Reasoning guardrail be attached to a STREAMING call?

    F1-14 carries the §3.2 clause "no streaming support", and the obvious instrument gives
    the wrong answer. `bedrock` has 24 AutomatedReasoning operations and zero streaming
    operations; `bedrock-runtime` has streaming operations and zero AutomatedReasoning
    operations. Counting operations per service therefore produces a clean-looking zero on
    both sides while measuring nothing, because the streaming path does not carry Automated
    Reasoning as an *operation* — it carries it as a guardrail attached by identifier and
    reported back inside the assessment trace.

    So the question is asked as two reachability facts per streaming operation:

      1. **attachable** — does the request carry a `guardrailIdentifier`? A guardrail
         created with `automatedReasoningPolicyConfig` is then attachable by construction:
         nothing in the request names its policies, so nothing in the request can exclude
         them.
      2. **reported** — does the response carry an `automatedReasoningPolicy` assessment?
         A path that reports AR findings is a path on which AR ran.

    Both halves are read off the walked member paths and the paths themselves are returned,
    because this is the direction most likely to contradict the document and a contradiction
    has to be checkable. The non-streaming operations are walked too, as the control: if
    `Converse` and `ConverseStream` looked identical to a broken walker, they would look
    identical here as well, and a difference between them is what makes the streaming
    reading mean anything.
    """
    client = clients.get("bedrock-runtime")
    if client is None:
        return {"available": False, "why": "no bedrock-runtime client"}
    model = client.meta.service_model
    ops = set(model.operation_names)
    streaming = ("ConverseStream", "InvokeModelWithResponseStream")
    non_streaming = ("Converse", "InvokeModel", "ApplyGuardrail")
    out: dict[str, Any] = {"available": True,
                           "streaming_operations": list(streaming),
                           "non_streaming_control": list(non_streaming),
                           "operations": {}}
    for op in streaming + non_streaming:
        if op not in ops:
            out["operations"][op] = {"present": False,
                                     "n_operations_examined": len(ops)}
            continue
        om = model.operation_model(op)
        in_rows = walk_shape(om.input_shape)
        out_rows = walk_shape(om.output_shape)
        guardrail_in = sorted(r["path"] for r in in_rows
                              if "guardrail" in r["path"].lower())
        ar_out = sorted(r["path"] for r in out_rows
                        if "automatedreasoning" in r["path"].lower())
        out["operations"][op] = {
            "present": True,
            "is_streaming": op in streaming,
            "n_input_paths_examined": len(in_rows),
            "n_output_paths_examined": len(out_rows),
            "guardrail_input_paths": guardrail_in,
            "attachable_by_identifier": any(p.lower().endswith("guardrailidentifier")
                                            for p in guardrail_in),
            "n_ar_output_paths": len(ar_out),
            # capped for readability; the count above is the true one, and the roots are
            # what a reader needs to see the assessment is reachable rather than incidental
            "ar_output_path_roots": sorted({p.split(".findings")[0] for p in ar_out})[:10],
            "reports_ar_assessment": bool(ar_out),
        }
    # The other half of the same clause: a guardrail can only carry AR if CreateGuardrail
    # lets one be configured, so that is read here rather than inferred.
    ctrl = clients.get("bedrock")
    if ctrl is not None:
        cmodel = ctrl.meta.service_model
        if "CreateGuardrail" in set(cmodel.operation_names):
            rows = walk_shape(cmodel.operation_model("CreateGuardrail").input_shape)
            ar_in = sorted(r["path"] for r in rows
                           if "automatedreasoning" in r["path"].lower())
            out["create_guardrail_ar_config"] = {
                "present": bool(ar_in), "paths": ar_in,
                "n_input_paths_examined": len(rows)}
    return out


def sweep(region: str) -> dict[str, Any]:
    """All ten directions, plus the SDK version that saw them."""
    session = boto3.session.Session()
    clients: dict[str, Any] = {}
    unavailable: dict[str, str] = {}
    for svc in SERVICES:
        try:
            clients[svc] = session.client(svc, region_name=region)
        except Exception as exc:                                  # noqa: BLE001
            # Recorded rather than raised: a service this botocore does not know is a fact
            # about the SDK and belongs in the payload. Raising would turn it into a failed
            # sweep, and the case script would then not be able to tell "the model has no
            # such service" from "the sweep crashed".
            unavailable[svc] = f"{type(exc).__name__}: {exc}"
    return {
        "sdk": {"boto3": boto3.__version__, "botocore": botocore.__version__},
        "python": sys.version.split()[0],
        "region_used_for_model_load": region,
        "services_requested": list(SERVICES),
        "services_available": sorted(clients),
        "services_unavailable": unavailable,
        "direction_1_operation_inventory": operation_inventory(clients),
        "direction_2_enum_reads": enum_reads(clients),
        "direction_3_capability_groups": capability_groups(clients),
        "direction_4_token_scan": token_scan(clients),
        "direction_5_required_fields": required_fields(clients),
        "direction_6_union_probe": union_probe(clients),
        "direction_7_enum_enforcement": enum_enforcement_probe(clients),
        "direction_8_shape_limits": shape_limits(clients),
        "direction_9_mode_enum_scan": mode_enum_scan(clients),
        "direction_10_ar_streaming_reach": ar_streaming_reach(clients),
        "aws_calls": 0,
        "why_no_aws_call": ("boto3.client loads the service model from the installed "
                           "package; no operation is invoked and no socket is opened"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--json", action="store_true",
                    help="write the sweep to stdout as JSON and nothing else")
    args = ap.parse_args(argv)
    data = sweep(args.region)
    if args.json:
        json.dump(data, sys.stdout)
        sys.stdout.write("\n")
        return 0
    print(f"botocore {data['sdk']['botocore']}   "
          f"services {len(data['services_available'])}/{len(SERVICES)}")
    for svc, v in data["direction_1_operation_inventory"].items():
        print(f"  {svc}: {v['n_operations']} operations, {v['n_shapes']} shapes")
    ex = data["direction_4_token_scan"]["examined_total"]
    print(f"  token scan examined {ex['n_operations']} operations, "
          f"{ex['n_shape_names']} shapes, {ex['n_member_paths']} member paths")
    for name, v in data["direction_2_enum_reads"].items():
        state = ",".join(v["values"]) if v["present"] else "ABSENT"
        print(f"  {name} [{v['read_for_case']}]: {state}")
    for group, v in data["direction_3_capability_groups"]["groups"].items():
        print(f"  {group}: {v['n_hits']} operation(s) in "
              f"{v['services_with_hits'] or 'no service'}")
    modes = data["direction_9_mode_enum_scan"]
    print(f"  mode enum scan: {modes['examined_total']['n_enums']} enums / "
          f"{modes['examined_total']['n_enum_values']} values examined, "
          f"{modes['n_hits_total']} hit(s)")
    reach = data["direction_10_ar_streaming_reach"]
    for op, v in reach.get("operations", {}).items():
        if v.get("present"):
            print(f"  {op}: attachable={v['attachable_by_identifier']} "
                  f"ar_assessment={v['reports_ar_assessment']} "
                  f"({v['n_ar_output_paths']} AR output paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
