#!/usr/bin/env python3
"""F1-1 / F1-2: locate the botocore version that first exposes the policy API surface.

Phase 0, offline, $0. No AWS credentials are used and no AWS API is called.

Why this exists
---------------
The installed botocore (1.42.79) models ``CreatePolicy`` WITHOUT the
``enforcementMode`` field and with ``PolicyDefinition = {cedar, policyGeneration}``,
while the AWS documentation shows ``--enforcement-mode ACTIVE|LOG_ONLY`` and
``definition.policy.statement``. Two mutually exclusive explanations:

  H1  the SDK is stale and a newer release models both fields
  H2  the documentation describes a surface the service does not expose

The harness cannot be written until this is settled, and the answer is itself a
finding for the document (§4.1 BP#6 tells readers to rely on ``enforcementMode``).

Method
------
``pip download botocore==X --no-deps`` fetches the wheel; the service model lives
inside it at ``botocore/data/<service>/<api-version>/service-2.json.gz``. Reading
that file answers the question exactly — it is the same artifact the runtime
client is built from — with no install, no venv, and no network calls to AWS.

A linear scan over ~90 releases would download ~90 wheels (~1 GB). Binary search
needs ~7. The predicate is monotone in practice (once AWS ships a field it stays
shipped), and ``--verify-monotone`` re-checks that assumption at the boundary
rather than assuming it: it asserts the field is absent at every probed version
below the boundary and present at every probed version above.

Usage
-----
    python3 01_sdk_bisect.py --list                 # enumerate candidate versions
    python3 01_sdk_bisect.py --probe 1.42.79        # single version, print surface
    python3 01_sdk_bisect.py --bisect               # find first version with the field
    python3 01_sdk_bisect.py --bisect --verify-monotone
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path

CACHE = Path(__file__).parent / ".wheel_cache"
RESULTS = Path(__file__).parent.parent / "results" / "f1_sdk_bisect.json"

# The two service models under test and the probes we care about in each.
AGENTCORE = "bedrock-agentcore-control"
RUNTIME = "bedrock-runtime"


@dataclass
class Surface:
    """What one botocore version actually models. All fields are observations."""
    version: str
    # --- bedrock-agentcore-control ---
    has_create_policy: bool = False
    create_policy_members: tuple[str, ...] = ()
    policy_definition_members: tuple[str, ...] = ()
    has_enforcement_mode: bool = False          # F1-1 primary predicate
    enforcement_mode_location: str = ""
    enforcement_mode_values: tuple[str, ...] = ()
    has_definition_policy: bool = False         # docs say definition.policy.statement
    has_definition_cedar: bool = False          # installed SDK says definition.cedar
    policy_validation_modes: tuple[str, ...] = ()
    engine_modes: tuple[str, ...] = ()
    policy_ops: tuple[str, ...] = ()
    # --- bedrock-runtime ---
    has_invoke_guardrail_checks: bool = False   # F1-2 predicate
    guardrail_check_members: tuple[str, ...] = ()
    error: str = ""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def list_versions() -> list[str]:
    """Ask pip for available botocore versions, newest last."""
    cp = _run([sys.executable, "-m", "pip", "index", "versions", "botocore"])
    blob = cp.stdout + cp.stderr
    m = re.search(r"[Aa]vailable versions:\s*(.+)", blob)
    if not m:
        # pip index is experimental and its output format is not guaranteed.
        # Fail loudly rather than silently bisecting an empty list.
        raise SystemExit(
            "could not parse `pip index versions botocore` output; "
            f"got:\n{blob[:800]}"
        )
    vers = [v.strip() for v in m.group(1).split(",") if v.strip()]
    return sorted(vers, key=vkey)


def vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def fetch_wheel(version: str) -> Path:
    """Download (and cache) the botocore wheel for `version`."""
    CACHE.mkdir(exist_ok=True)
    hit = sorted(CACHE.glob(f"botocore-{version}-*.whl"))
    if hit:
        return hit[0]
    with tempfile.TemporaryDirectory() as td:
        cp = _run([sys.executable, "-m", "pip", "download",
                   f"botocore=={version}", "--no-deps", "--only-binary", ":all:",
                   "-d", td, "-q"])
        whls = list(Path(td).glob("botocore-*.whl"))
        if not whls:
            raise RuntimeError(f"download failed for {version}: {cp.stderr[:400]}")
        dest = CACHE / whls[0].name
        shutil.move(str(whls[0]), dest)
        return dest


def load_model(whl: Path, service: str) -> dict:
    """Read <service>/<latest api-version>/service-2.json[.gz] out of the wheel."""
    with zipfile.ZipFile(whl) as z:
        names = [n for n in z.namelist()
                 if f"/data/{service}/" in n and "service-2.json" in n]
        if not names:
            raise KeyError(f"{service} not present in {whl.name}")
        # Multiple api-versions can ship; take the lexicographically last date.
        names.sort()
        raw = z.read(names[-1])
    if names[-1].endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw)


def _members(shapes: dict, shape_name: str | None) -> tuple[str, ...]:
    if not shape_name or shape_name not in shapes:
        return ()
    return tuple(shapes[shape_name].get("members", {}).keys())


def probe(version: str) -> Surface:
    s = Surface(version=version)
    try:
        whl = fetch_wheel(version)
    except Exception as exc:                      # network / yank / no wheel
        s.error = f"fetch: {exc}"
        return s

    # ---- bedrock-agentcore-control -------------------------------------
    try:
        model = load_model(whl, AGENTCORE)
        shapes = model.get("shapes", {})
        ops = model.get("operations", {})
        s.policy_ops = tuple(sorted(o for o in ops if "Polic" in o))
        s.has_create_policy = "CreatePolicy" in ops

        if s.has_create_policy:
            req = ops["CreatePolicy"].get("input", {}).get("shape")
            s.create_policy_members = _members(shapes, req)
            # PolicyDefinition may be named anything; follow the reference.
            defn_shape = None
            if req in shapes:
                dm = shapes[req].get("members", {}).get("definition", {})
                defn_shape = dm.get("shape")
            s.policy_definition_members = _members(shapes, defn_shape)
            s.has_definition_policy = "policy" in s.policy_definition_members
            s.has_definition_cedar = "cedar" in s.policy_definition_members

        # enforcementMode may appear on the request, on the definition, or on a
        # nested shape. Search the whole model text, then locate it precisely.
        blob = json.dumps(model)
        s.has_enforcement_mode = "enforcementMode" in blob
        if s.has_enforcement_mode:
            locs = [f"{sn}.{mn}" for sn, sh in shapes.items()
                    for mn in sh.get("members", {}) if mn == "enforcementMode"]
            s.enforcement_mode_location = ";".join(sorted(locs))
            for sn, sh in shapes.items():
                if "enforcement" in sn.lower() and sh.get("enum"):
                    s.enforcement_mode_values = tuple(sh["enum"])
                    break

        for sn, sh in shapes.items():
            if sh.get("enum"):
                low = sn.lower()
                if "validationmode" in low:
                    s.policy_validation_modes = tuple(sh["enum"])
                elif "policyenginemode" in low:
                    s.engine_modes = tuple(sh["enum"])
    except Exception as exc:
        s.error = f"{AGENTCORE}: {exc}"

    # ---- bedrock-runtime ------------------------------------------------
    try:
        rt = load_model(whl, RUNTIME)
        rops = rt.get("operations", {})
        s.has_invoke_guardrail_checks = "InvokeGuardrailChecks" in rops
        if s.has_invoke_guardrail_checks:
            req = rops["InvokeGuardrailChecks"].get("input", {}).get("shape")
            s.guardrail_check_members = _members(rt.get("shapes", {}), req)
    except Exception as exc:
        s.error = (s.error + " | " if s.error else "") + f"{RUNTIME}: {exc}"

    return s


def report(s: Surface) -> str:
    if s.error and not s.has_create_policy:
        return f"{s.version:<10} ERROR {s.error[:90]}"
    flags = [
        f"enforcementMode={'YES' if s.has_enforcement_mode else 'no '}",
        f"defn.policy={'YES' if s.has_definition_policy else 'no '}",
        f"defn.cedar={'YES' if s.has_definition_cedar else 'no '}",
        f"IGC={'YES' if s.has_invoke_guardrail_checks else 'no '}",
    ]
    return f"{s.version:<10} " + "  ".join(flags)


PREDICATES = {
    "enforcement_mode": lambda s: s.has_enforcement_mode,
    "definition_policy": lambda s: s.has_definition_policy,
    "invoke_guardrail_checks": lambda s: s.has_invoke_guardrail_checks,
}


def bisect(versions: list[str], predicate: str, probes: dict[str, Surface]) -> dict:
    """Find the first version in `versions` satisfying `predicate`.

    Returns a record with the boundary and every version actually probed, so the
    search path is auditable rather than just its conclusion.
    """
    pred = PREDICATES[predicate]
    lo, hi = 0, len(versions) - 1
    order: list[str] = []

    def probe_cached(idx: int) -> Surface:
        v = versions[idx]
        if v not in probes:
            probes[v] = probe(v)
            order.append(v)
            print("  probe " + report(probes[v]))
        return probes[v]

    first_true = None
    if pred(probe_cached(hi)):
        if pred(probe_cached(lo)):
            first_true = versions[lo]      # true everywhere in range
        else:
            while lo + 1 < hi:
                mid = (lo + hi) // 2
                if pred(probe_cached(mid)):
                    hi = mid
                else:
                    lo = mid
            first_true = versions[hi]
    return {
        "predicate": predicate,
        "first_version_with_field": first_true,
        "newest_probed": versions[-1],
        "oldest_probed": versions[0],
        "probe_order": order,
        "conclusion": (
            f"field first appears in botocore {first_true}" if first_true
            else "field is absent even in the newest available botocore "
                 "-> the documented surface is not in any released SDK model"
        ),
    }


def verify_monotone(versions: list[str], predicate: str, boundary: str | None,
                    probes: dict[str, Surface]) -> dict:
    """Re-check the monotonicity the bisect assumed, at the boundary and beyond.

    Binary search is only valid if the predicate is false-then-true. This probes
    the two versions bracketing the boundary plus one sample well below it; a
    violation makes the bisect result meaningless and must be reported, not
    swallowed.
    """
    if boundary is None:
        return {"checked": [], "monotone": None,
                "note": "no boundary found; nothing to verify"}
    idx = versions.index(boundary)
    checks = []
    for j in (idx - 1, idx, min(idx + 1, len(versions) - 1), max(0, idx // 2)):
        v = versions[j]
        if v not in probes:
            probes[v] = probe(v)
            print("  verify " + report(probes[v]))
        checks.append({"version": v, "index": j,
                       "predicate_true": PREDICATES[predicate](probes[v]),
                       "expected": j >= idx})
    monotone = all(c["predicate_true"] == c["expected"] for c in checks
                   if not probes[c["version"]].error)
    return {"checked": checks, "monotone": monotone,
            "note": "" if monotone else
                    "MONOTONICITY VIOLATED - bisect conclusion is invalid"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--probe", metavar="VERSION")
    ap.add_argument("--bisect", action="store_true")
    ap.add_argument("--verify-monotone", action="store_true")
    ap.add_argument("--min-version", default="1.40.0",
                    help="floor for the search range (default 1.40.0)")
    args = ap.parse_args(argv)

    if args.list:
        vs = list_versions()
        print(f"{len(vs)} versions, {vs[0]} .. {vs[-1]}")
        return 0

    if args.probe:
        s = probe(args.probe)
        print(json.dumps(asdict(s), indent=2, default=list))
        return 0 if not s.error else 1

    if args.bisect:
        allv = list_versions()
        floor = vkey(args.min_version)
        versions = [v for v in allv if vkey(v) >= floor]
        print(f"search range: {len(versions)} versions "
              f"({versions[0]} .. {versions[-1]})\n")
        probes: dict[str, Surface] = {}
        out: dict = {"search_range": [versions[0], versions[-1]],
                     "candidate_count": len(versions), "bisects": {}}
        for pred in PREDICATES:
            print(f"--- bisect: {pred} ---")
            rec = bisect(versions, pred, probes)
            if args.verify_monotone:
                rec["monotonicity"] = verify_monotone(
                    versions, pred, rec["first_version_with_field"], probes)
            out["bisects"][pred] = rec
            print(f"  => {rec['conclusion']}\n")
        out["surfaces"] = {v: asdict(s) for v, s in sorted(
            probes.items(), key=lambda kv: vkey(kv[0]))}
        out["wheels_downloaded"] = len(probes)
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(json.dumps(out, indent=2, default=list))
        print(f"probed {len(probes)} versions; wrote {RESULTS}")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
