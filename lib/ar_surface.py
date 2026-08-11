#!/usr/bin/env python3
"""Enumerate the Automated Reasoning request surface in a botocore service model.

    .venv-oracle/bin/python lib/ar_surface.py --json          # under the pinned SDK
    python3 lib/ar_surface.py --json                          # under the ambient SDK

WHY THIS IS A SEPARATE MODULE AND NOT PART OF F8-8's SCRIPT
-----------------------------------------------------------
F8-8's whole content is *which fields the SDK model exposes*, so the sweep has to run under
the pinned oracle interpreter — `.venv-oracle` (botocore 1.43.67). That interpreter has no
numpy and no scipy, so it cannot import `lib/oracle.py` or `lib/stats.py`, and therefore
cannot evaluate a sealed oracle or write a result record. The two halves need different
interpreters.

So the sweep lives here, importing nothing but the standard library and botocore, and
`f8_regional/07_absent_surface.py` runs it as a subprocess under `.venv-oracle`, reads the
JSON back, and evaluates the oracle under the interpreter that has scipy. The alternative —
having the case script decide from whatever botocore happens to be ambient — would answer a
question about pip and report it as a fact about AWS.

Being importable also makes the sweep testable offline: `lib/tests/` exercises `walk_shape`
against hand-built shapes, which is the part with the real failure mode (a model is a graph,
not a tree, and a self-referential shape recursed naively looks like a crashed scan rather
than a completed one).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

import boto3
import botocore

# The two services that could carry the surface: `bedrock` is the control plane where an
# Automated Reasoning policy is authored, `bedrock-runtime` is where a check is invoked —
# and a per-request language or mode would have to live on the invocation, not the policy.
SERVICES = ("bedrock", "bedrock-runtime")

# The roots a language/locale/mode field would have to contain under any plausible naming.
# `enforc` rather than `enforcement` so `enforce`, `enforced` and `enforcementMode` all
# match; `lang` catches `language`, `languageCode`, `inputLanguage`. Deliberately loose: a
# false positive costs one line of manual reading in the payload, while a false negative
# would publish an absence that is not there.
FIELD_RE = re.compile(r"lang|locale|mode|enforc|english|en[-_]?us|detect|translat|i18n",
                      re.I)

# Enum VALUES that would indicate a mode exists. Compared upper-case: AWS enum values are
# conventionally SCREAMING_CASE, and a case-insensitive match would hit the word "detected"
# in every content-filter enum and drown the signal.
MODE_VALUES = ("DETECT", "ENFORCE", "DETECT_ONLY", "ENFORCEMENT", "ENFORCED")

MAX_DEPTH = 12


def walk_shape(shape, *, path: str = "", seen: set[str] | None = None,
               depth: int = 0) -> list[dict[str, Any]]:
    """Every member of `shape`, recursively, as flat rows.

    `seen` keys on shape NAME plus path, not on path alone: a service model is a graph, and
    a self-referential shape walked naively recurses until the interpreter's stack limit —
    which reads as a crashed scan rather than as a completed one, and a crashed scan that
    was reported as clean is exactly the defect this project screens documents for.

    Each row carries `is_string` and `enum` because the sweep asks two different questions
    of a member — does its NAME look like a language field, and does its TYPE admit a mode
    value — and a row recording only the name could answer just the first.
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
        for name, member in shape.members.items():
            here = f"{path}.{name}" if path else name
            rows.append({
                "path": here, "member": name,
                "shape": getattr(member, "name", "?"), "type": member.type_name,
                "is_string": member.type_name == "string",
                "enum": list(getattr(member, "enum", []) or []),
            })
            rows += walk_shape(member, path=here, seen=seen, depth=depth + 1)
    elif kind == "list":
        rows += walk_shape(shape.member, path=f"{path}[]", seen=seen, depth=depth + 1)
    elif kind == "map":
        rows += walk_shape(shape.value, path=f"{path}{{}}", seen=seen, depth=depth + 1)
    return rows


def operation_inventory(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 1: where the Automated Reasoning surface lives, per service."""
    out: dict[str, Any] = {}
    for svc, client in clients.items():
        names = sorted(client.meta.service_model.operation_names)
        ar = [n for n in names if "automatedreasoning" in n.lower()]
        out[svc] = {"n_operations_total": len(names),
                    "n_automated_reasoning": len(ar),
                    "automated_reasoning_operations": ar}
    return out


def member_sweep(clients: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    """Direction 2: every input member of every AR operation, matched against FIELD_RE."""
    examined = 0
    ops_examined = 0
    matches: list[dict[str, Any]] = []
    per_op: dict[str, int] = {}
    for svc, client in clients.items():
        model = client.meta.service_model
        for op in inventory[svc]["automated_reasoning_operations"]:
            ops_examined += 1
            rows = walk_shape(model.operation_model(op).input_shape)
            per_op[f"{svc}:{op}"] = len(rows)
            examined += len(rows)
            for r in rows:
                if FIELD_RE.search(r["member"]):
                    matches.append({"service": svc, "operation": op, **r})
    return {"n_operations_examined": ops_examined,
            "n_members_examined": examined,
            "members_examined_per_operation": per_op,
            "matches": matches,
            "n_matches": len(matches),
            "regex": FIELD_RE.pattern}


def enum_sweep(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 3: every enum in the WHOLE model, searched for a mode value.

    Whole-model rather than AR-scoped on purpose. A mode could be declared on a shared shape
    the AR operations reach indirectly, or on an operation whose name does not contain
    "AutomatedReasoning" at all; an AR-scoped enum sweep would report the absence without
    having looked where the thing would be.
    """
    out: dict[str, Any] = {}
    for svc, client in clients.items():
        model = client.meta.service_model
        n_shapes = n_enums = 0
        hits: list[dict[str, Any]] = []
        for name in model.shape_names:
            n_shapes += 1
            values = list(getattr(model.shape_for(name), "enum", []) or [])
            if not values:
                continue
            n_enums += 1
            found = [v for v in values if v.upper() in MODE_VALUES]
            if found:
                hits.append({"shape": name, "values": values, "mode_values": found})
        out[svc] = {"n_shapes_examined": n_shapes, "n_enums_examined": n_enums,
                    "hits": hits, "n_hits": len(hits),
                    "searched_for": list(MODE_VALUES)}
    return out


def response_sweep(clients: dict[str, Any]) -> dict[str, Any]:
    """Direction 4: what the AR assessment surfaces back on ApplyGuardrail.

    A mode that cannot be requested might still be REPORTED, and a report would mean the
    concept exists on the wire even where the request cannot name it.
    """
    client = clients.get("bedrock-runtime")
    if client is None:
        return {"available": False, "why": "no bedrock-runtime client"}
    model = client.meta.service_model
    if "ApplyGuardrail" not in set(model.operation_names):
        return {"available": False,
                "why": "ApplyGuardrail is absent from this SDK's bedrock-runtime model"}
    rows = walk_shape(model.operation_model("ApplyGuardrail").output_shape)
    ar = [r for r in rows if "automatedreasoning" in r["path"].lower()]
    return {
        "available": True,
        "n_output_members_examined": len(rows),
        "automated_reasoning_paths": [r["path"] for r in ar],
        "automated_reasoning_members": sorted({r["member"] for r in ar}),
        "field_regex_matches": [r["path"] for r in ar if FIELD_RE.search(r["member"])],
    }


def sweep(region: str) -> dict[str, Any]:
    """All four directions, plus the SDK version that saw them.

    Clients are built, never called: `boto3.client` loads a JSON model off disk and opens no
    socket, so this runs with no credentials and nothing leaves the machine. `region_name` is
    passed explicitly because `~/.aws/config` carries only `[default]` and an unset region
    raises `NoRegionError` — which would look like a failed sweep.
    """
    session = boto3.session.Session()
    clients = {svc: session.client(svc, region_name=region) for svc in SERVICES}
    inventory = operation_inventory(clients)
    return {
        "sdk": {"boto3": boto3.__version__, "botocore": botocore.__version__},
        "python": sys.version.split()[0],
        "region_used_for_model_load": region,
        "services": list(SERVICES),
        "direction_1_operation_inventory": inventory,
        "direction_2_member_sweep": member_sweep(clients, inventory),
        "direction_3_enum_sweep": enum_sweep(clients),
        "direction_4_response_sweep": response_sweep(clients),
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
        # `ensure_ascii=False` deliberately absent: this payload carries no non-ASCII text,
        # and the parent reads it with json.loads either way.
        json.dump(data, sys.stdout)
        sys.stdout.write("\n")
        return 0
    inv = data["direction_1_operation_inventory"]
    print(f"botocore {data['sdk']['botocore']}")
    for svc, v in inv.items():
        print(f"  {svc}: {v['n_automated_reasoning']} AutomatedReasoning of "
              f"{v['n_operations_total']} operations")
    m = data["direction_2_member_sweep"]
    print(f"  members examined: {m['n_members_examined']}  matches: {m['n_matches']}")
    for svc, v in data["direction_3_enum_sweep"].items():
        print(f"  {svc}: {v['n_enums_examined']} enums examined, {v['n_hits']} mode hits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
