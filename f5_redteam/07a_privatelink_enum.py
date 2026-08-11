#!/usr/bin/env python3
"""F5-7a: does the PrivateLink coverage matrix in §4.5.3 describe reality?

Phase 0, read-only, **$0**. `DescribeVpcEndpointServices` is not billed and creates
nothing. Route #2 of the five bypass routes (network egress) rests on §4.5.3, and
§5.3 BP#6 tells readers to check the matrix before designing a closed loop.

The document says (§4.5.3, cited to Accelerator v2.9):

    | Service                                                   | Data | Control |
    | Runtime, Memory, Built-in Tools, Identity, Gateway, Policy |  ✅  |   ✅    |
    | Evaluations                                               |  ❌  |   ✅    |
    | Optimization                                              |  ❌  |   ❌    |

    caveat (b): the Gateway has a third, separate PrivateLink endpoint.

What is and is not observable, stated before any data is collected
-----------------------------------------------------------------
This is the part that decides what the test can conclude, so it is written down
in the script rather than discovered in the analysis.

PrivateLink attaches to an **endpoint service name** (``com.amazonaws.<region>.<prefix>``),
not to a primitive. AgentCore has *three* prefixes and the document's matrix has
*three rows naming eight primitives*. The mapping from primitive to prefix is
therefore many-to-one, and:

  * **Directly observable** — which endpoint services exist, in which regions,
    with which private DNS names and AZ coverage. This is decisive for caveat (b)
    (a third endpoint either exists or it does not) and for "is there a separate
    Evaluations/Optimization endpoint service".
  * **NOT observable this way** — whether a *primitive* is reachable over an
    existing endpoint. ``Evaluate`` is an operation on the ``bedrock-agentcore``
    prefix, which *does* have an endpoint service. So "Evaluations data plane ❌"
    cannot be refuted by the absence of a ``bedrock-agentcore-evaluations``
    service, because the matrix was never claiming one existed. Refuting it
    requires either an AWS statement of support or a live call over an endpoint
    from inside a VPC, which is F5-7b (Phase 6b), not this test.

Confusing those two is the trap this script exists to avoid: an earlier pass of
this analysis nearly recorded "the matrix is wrong because ``Evaluate`` lives on a
prefix that has an endpoint", which does not follow.

So the API enumeration is paired with a second, independent instrument: the AWS
public documentation page the document already cites, read **now** and read from
the Internet Archive at earlier timestamps. A support matrix is a statement about
service state, and service state has a date. Comparing the same page across time
is what separates "the document was wrong" from "the document was right and AWS
shipped the feature afterwards" — and per the plan's Part 6 those two classes
lead to different amendments.

Instruments
-----------
  A. ``ec2:DescribeVpcEndpointServices`` per region, filtered on
     ``com.amazonaws.*.bedrock-agentcore*`` and also run unfiltered to count the
     denominator (a filtered call that returns 3 of 3 and a filtered call that
     returns 3 of 617 support different sentences).
  B. HTTP GET of ``vpc-interface-endpoints.html`` live, plus Wayback snapshots.
     Recorded verbatim to ``evidence/`` so the comparison is re-checkable after
     the pages change again.

Usage
-----
    python3 f5_redteam/07a_privatelink_enum.py --dry-run
    python3 f5_redteam/07a_privatelink_enum.py --regions us-east-1
    python3 f5_redteam/07a_privatelink_enum.py            # all 5 + 3 controls
    python3 f5_redteam/07a_privatelink_enum.py --no-docs  # instrument A only
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.evidence import EvidenceStore, capture, new_run_id  # noqa: E402

CASE = "F5-7a"
FAMILY = "f5"

# The five regions §3.4 / the guardrails-in-policy list calls supported, plus three
# regions it calls unsupported. The controls are not padding: if the endpoint
# services exist in unsupported regions too, then their existence is NOT evidence
# of feature availability, and that fact bounds what instrument A can conclude.
SUPPORTED_REGIONS = ["us-east-1", "eu-west-2", "eu-north-1",
                     "ap-southeast-2", "ap-northeast-1"]
CONTROL_REGIONS = ["us-west-2", "eu-central-1", "sa-east-1"]

SERVICE_FILTER = "com.amazonaws.*.bedrock-agentcore*"

# Keywords that WOULD appear in a dedicated endpoint service for these primitives.
# Searched over the full unfiltered service list, so "no such service" is a
# statement about all of PrivateLink in the region, not about our filter.
PRIMITIVE_KEYWORDS = {
    "evaluations": ("evaluat",),
    "optimization": ("agentcore-optimi", "agentcore.optimi"),
}

DOC_URL = ("https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/"
           "vpc-interface-endpoints.html")
WAYBACK_CDX = ("http://web.archive.org/cdx/search/cdx?url=docs.aws.amazon.com/"
               "bedrock-agentcore/latest/devguide/vpc-interface-endpoints.html"
               "&output=json&fl=timestamp,statuscode,digest&collapse=digest")
UA = {"User-Agent": "grx-validation/F5-7a (+doc-validation harness)"}


# ---------------------------------------------------------------------------
# instrument A — the live API
# ---------------------------------------------------------------------------

def enumerate_region(store: EvidenceStore, region: str) -> dict:
    """Filtered + unfiltered enumeration for one region. Errors are data."""
    import boto3

    ec2 = boto3.client("ec2", region_name=region)

    filt = capture(store, "describe_vpc_endpoint_services", ec2,
                   Filters=[{"Name": "service-name", "Values": [SERVICE_FILTER]}])
    allsvc = capture(store, "describe_vpc_endpoint_services", ec2)

    out: dict = {"region": region,
                 "filtered_request_id": filt.request_id,
                 "unfiltered_request_id": allsvc.request_id,
                 "reachable": filt.ok and allsvc.ok}
    if not out["reachable"]:
        bad = filt if not filt.ok else allsvc
        out["error_code"] = bad.error_code
        out["error_message"] = bad.error_message
        return out

    details = []
    for d in (filt.response or {}).get("ServiceDetails", []):
        details.append({
            "service_name": d.get("ServiceName"),
            "type": ",".join(t.get("ServiceType", "")
                             for t in d.get("ServiceType", [])),
            "owner": d.get("Owner"),
            "private_dns": d.get("PrivateDnsName"),
            "azs": sorted(d.get("AvailabilityZones", [])),
            "vpc_endpoint_policy_supported": d.get("VpcEndpointPolicySupported"),
            "acceptance_required": d.get("AcceptanceRequired"),
            "supported_ip_address_types": sorted(
                d.get("SupportedIpAddressTypes", [])),
        })
    details.sort(key=lambda d: d["service_name"] or "")

    all_names = sorted((allsvc.response or {}).get("ServiceNames", []))
    out["agentcore_services"] = [d["service_name"] for d in details]
    out["agentcore_service_details"] = details
    out["n_agentcore"] = len(details)
    out["n_all_services"] = len(all_names)
    out["primitive_keyword_hits"] = {
        prim: sorted(n for n in all_names
                     if any(k in n.lower() for k in keys))
        for prim, keys in PRIMITIVE_KEYWORDS.items()
    }
    return out


# ---------------------------------------------------------------------------
# instrument B — the documentation, now and in the past
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 60, attempts: int = 3) -> bytes:
    """GET with retry.

    The Internet Archive CDX endpoint times out intermittently, and on the first
    full run it did exactly that — which downgraded the Optimization verdict from
    ``AWS_BEHAVIOR_CHANGED`` to ``DOC_REFUTED_CHANGE_DATE_UNDETERMINED``. The
    degradation was correct behaviour (the script does not assert history it did
    not read), but a *transport* failure must not be able to decide a *classification*.
    Retrying with backoff makes the archive a measured instrument rather than a
    coin flip, and a still-failing fetch remains recorded as an explicit error.
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        except Exception as exc:                      # noqa: BLE001 — recorded, not hidden
            last = exc
            if i + 1 < attempts:
                time.sleep(2 * (i + 1))
    raise last if last else RuntimeError(f"unreachable: {url}")


def _text(raw: bytes) -> str:
    """HTML to pipe-delimited text, keeping table cell boundaries.

    Tags collapse to ``|`` rather than to a space: the support matrix is a table,
    and stripping tags to whitespace would run ``Evaluations`` and
    ``Not yet supported`` together with no way to tell a cell boundary from a
    line wrap.
    """
    t = raw.decode("utf-8", "replace")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "|", t))
    return re.sub(r"[ \t]+", " ", re.sub(r"\|+", "|", t))


def parse_support_table(text: str) -> dict:
    """Extract the primitive->support rows, or say the table is absent.

    Absent is a real state, not a parse failure: the page had no support table at
    all before mid-2026, and reporting that as "could not parse" would hide the
    most informative observation in this test.
    """
    out: dict = {"has_support_table": False, "n_endpoints_stated": None, "rows": {}}
    m = re.search(r"AgentCore provides (\w+) AWS PrivateLink endpoints", text)
    if m:
        out["n_endpoints_stated"] = m.group(1)
    out["endpoint_names_stated"] = sorted(set(re.findall(
        r"com\.amazonaws\.(?:region|<region>)\.(bedrock-agentcore[\w.-]*)", text)))
    if "support status for each AgentCore primitive" not in text:
        return out
    out["has_support_table"] = True
    seg = text.split("support status for each AgentCore primitive", 1)[1][:2500]
    cells = [c.strip() for c in seg.split("|")]
    cells = [c for c in cells if c]
    # Rows are <primitive> then two support verdicts, in order.
    verdict = re.compile(r"^(Supported|Not yet supported|Not supported)$", re.I)
    i = 0
    while i < len(cells):
        if verdict.match(cells[i]):
            # walk back to the nearest non-verdict cell = the primitive name
            j = i - 1
            while j >= 0 and verdict.match(cells[j]):
                j -= 1
            prim = cells[j] if j >= 0 else "?"
            data = cells[i]
            ctrl = cells[i + 1] if i + 1 < len(cells) and verdict.match(
                cells[i + 1]) else None
            if prim.lower() not in ("primitive", "data plane", "control plane"):
                out["rows"][prim] = {"data_plane": data, "control_plane": ctrl}
            i += 2 if ctrl else 1
            continue
        i += 1
    return out


def fetch_doc_now(outdir: Path) -> dict:
    try:
        raw = _get(DOC_URL)
    except (urllib.error.URLError, OSError) as exc:
        return {"url": DOC_URL, "ok": False, "error": str(exc)[:300]}
    (outdir / "doc_live.html").write_bytes(raw)
    text = _text(raw)
    rec = {"url": DOC_URL, "ok": True, "bytes": len(raw),
           "fetched_utc": datetime.now(timezone.utc).isoformat(),
           **parse_support_table(text)}
    return rec


def fetch_wayback(outdir: Path, limit: int) -> list[dict]:
    """Distinct-content snapshots of the same page, oldest first.

    ``collapse=digest`` asks the CDX API for one row per distinct content hash, so
    the returned timestamps are the dates the page *changed* rather than the dates
    a crawler happened to visit. That is exactly the axis this comparison needs.
    """
    try:
        rows = json.loads(_get(WAYBACK_CDX).decode("utf-8"))
    except Exception as exc:                                  # CDX is best-effort
        return [{"ok": False, "error": f"cdx: {str(exc)[:200]}"}]
    if not rows or len(rows) < 2:
        return [{"ok": False, "error": "cdx returned no snapshots"}]
    stamps = [r[0] for r in rows[1:] if r[1] == "200"]
    # Oldest, then evenly spaced, then always the newest: the newest is the one
    # that brackets the change against the live page.
    if len(stamps) > limit:
        step = (len(stamps) - 1) / (limit - 1)
        picked = sorted({stamps[round(k * step)] for k in range(limit)})
        picked = sorted(set(picked) | {stamps[-1]})
    else:
        picked = stamps
    snaps = []
    for ts in picked:
        url = f"https://web.archive.org/web/{ts}id_/{DOC_URL}"
        try:
            raw = _get(url)
        except Exception as exc:
            snaps.append({"timestamp": ts, "ok": False, "error": str(exc)[:200]})
            continue
        (outdir / f"doc_wayback_{ts}.html").write_bytes(raw)
        snaps.append({"timestamp": ts, "ok": True, "bytes": len(raw),
                      "archived_url": url, **parse_support_table(_text(raw))})
    return snaps


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def classify(api: list[dict], doc_now: dict, snaps: list[dict]) -> dict:
    """Turn observations into per-claim verdicts. No verdict is invented here that
    the observations do not license — ``NOT_TESTED_BY_THIS_INSTRUMENT`` is a
    first-class outcome and is used wherever the enumeration is silent."""
    ok = [r for r in api if r.get("reachable")]
    sup = [r for r in ok if r["region"] in SUPPORTED_REGIONS]
    ctl = [r for r in ok if r["region"] in CONTROL_REGIONS]

    names_by_region = {r["region"]: set(r["agentcore_services"]) for r in ok}
    suffixes = {frozenset(n.split(".", 3)[-1] for n in v)
                for v in names_by_region.values()}
    consistent = len(suffixes) <= 1
    gateway_ep = all(any(n.endswith(".bedrock-agentcore.gateway")
                         for n in v) for v in names_by_region.values()) and bool(ok)

    hits = {p: sorted({n for r in ok for n in r["primitive_keyword_hits"][p]})
            for p in PRIMITIVE_KEYWORDS}

    doc_rows = doc_now.get("rows", {}) if doc_now.get("ok") else {}
    def _row(pat: str) -> tuple[str, dict] | tuple[None, None]:
        for k, v in doc_rows.items():
            if pat.lower() in k.lower():
                return k, v
        return None, None

    # Looked up independently, because AWS may name them in one row or two and the
    # verdict for each must not depend on which. As of this writing the live page
    # carries a single merged row `Evaluations and Optimizations`, so both lookups
    # land on it; the 2026-07 snapshots carry `Evaluations` alone and NO
    # Optimization row at all, which is itself the observation for that claim.
    ev_key, ev_row = _row("evaluat")
    op_key, op_row = _row("optimi")
    hist = [s for s in snaps if s.get("ok") and s.get("has_support_table")]
    hist_ev, hist_op = [], []
    for s in hist:
        for k, v in s["rows"].items():
            if "evaluat" in k.lower():
                hist_ev.append({"timestamp": s["timestamp"], "primitive": k, **v})
            if "optimi" in k.lower():
                hist_op.append({"timestamp": s["timestamp"], "primitive": k, **v})

    findings = {
        "caveat_b_third_gateway_endpoint": {
            "doc_claim": "the Gateway has a third, separate PrivateLink endpoint "
                         "distinct from the data and control planes",
            "observation": sorted({n for v in names_by_region.values() for n in v}),
            "verdict": "CONFIRMED" if gateway_ep else "NOT_CONFIRMED",
            "instrument": "A (ec2:DescribeVpcEndpointServices)",
            "n_regions": len(ok),
        },
        "no_dedicated_evaluations_or_optimization_endpoint_service": {
            "observation": {"keyword_hits": hits,
                            "n_all_services_min": min(
                                (r["n_all_services"] for r in ok), default=None)},
            "verdict": ("CONFIRMED" if not any(hits.values()) else "REFUTED"),
            "what_this_does_and_does_not_show": (
                "Shows only that no endpoint service is NAMED for these "
                "primitives. It does NOT show they are unreachable over "
                "PrivateLink: `Evaluate` is an operation on endpoint prefix "
                "bedrock-agentcore, which HAS an endpoint service. Reachability "
                "of a primitive over an existing endpoint is F5-7b, not this test."),
            "instrument": "A",
        },
        "matrix_rows_are_primitives_not_endpoint_services": {
            "observation": {
                "n_endpoint_prefixes": len(next(iter(suffixes), ())),
                "n_primitives_named_in_doc_matrix": 8,
                "doc_page_states_n_endpoints": doc_now.get("n_endpoints_stated"),
            },
            "verdict": "DOC_IMPRECISE",
            "why": ("The document's column header is `Service` while its rows "
                    "name primitives, and PrivateLink attaches to endpoint "
                    "prefixes. A reader who searches for a `Policy` endpoint "
                    "service finds none and cannot tell whether that means "
                    "unsupported. AWS's own page uses the header `Primitive` and "
                    "lists the three prefixes above the table."),
            "instrument": "A + B",
        },
        "evaluations_data_plane_not_supported": {
            "doc_claim": "Evaluations data plane: NO PrivateLink",
            "aws_page_now": {"primitive": ev_key, **(ev_row or {})},
            "aws_page_history": hist_ev,
            "verdict": _evaluations_verdict(ev_row, hist_ev),
            "instrument": "B (AWS public documentation, live + Internet Archive)",
        },
        "optimization_no_privatelink": {
            "doc_claim": "Optimization: no PrivateLink on either plane",
            "aws_page_now": ({"primitive": op_key, **op_row} if op_row else
                             {"note": "no row matching 'optimi' on the AWS page"}),
            "aws_page_history": hist_op,
            "row_is_shared_with_evaluations": bool(
                op_key and ev_key and op_key == ev_key),
            "verdict": _optimization_verdict(op_key, op_row, hist_op),
            "instrument": "B",
        },
        "endpoint_service_existence_is_not_feature_availability": {
            "observation": {
                "supported_regions_with_all_3": sum(
                    1 for r in sup if r["n_agentcore"] == 3),
                "control_regions_with_all_3": sum(
                    1 for r in ctl if r["n_agentcore"] == 3),
                "control_regions_tested": [r["region"] for r in ctl],
            },
            "verdict": ("CONFIRMED_AS_LIMITATION"
                        if ctl and all(r["n_agentcore"] == 3 for r in ctl)
                        else "INCONCLUSIVE"),
            "why_it_matters": (
                "The three endpoint services exist in regions the document lists "
                "as NOT supporting guardrails-in-policy. Endpoint-service "
                "existence therefore carries no information about feature "
                "availability, which bounds every conclusion instrument A can "
                "reach and is the reason instrument B exists."),
            "instrument": "A (control arm)",
        },
    }
    return {
        "regions_reachable": [r["region"] for r in ok],
        "regions_unreachable": [{"region": r["region"],
                                 "error_code": r.get("error_code")}
                                for r in api if not r.get("reachable")],
        "endpoint_set_identical_across_regions": consistent,
        "endpoint_prefixes": sorted(next(iter(suffixes), ())),
        "findings": findings,
    }


def _evaluations_verdict(row: dict | None, hist: list[dict]) -> str:
    if not row:
        return "NOT_TESTED_BY_THIS_INSTRUMENT"
    now = (row.get("data_plane") or "").lower()
    past = {h["timestamp"]: (h.get("data_plane") or "").lower() for h in hist}
    said_no = any("not" in v for v in past.values())
    if "not" in now:
        return "DOC_CONFIRMED"
    if said_no:
        # The document matched AWS's page when it was written; the page changed.
        return "AWS_BEHAVIOR_CHANGED"
    return "DOC_CONTRADICTED_BY_AWS_DOCS"


def _optimization_verdict(key: str | None, row: dict | None,
                          hist: list[dict]) -> str:
    """Deliberately weaker than the Evaluations verdict, for a reason.

    Evaluations is decidable: AWS's page said "Not yet supported" on a dated
    snapshot and says "Supported" now, so the state demonstrably changed. For
    Optimization the earlier snapshots contain **no row at all** — AWS was silent,
    not contradictory. Silence is compatible with both "unsupported then, supported
    now" and "supported all along, merely undocumented", and this instrument cannot
    separate them. Returning ``AWS_BEHAVIOR_CHANGED`` would be asserting the first
    on the strength of the second's absence.
    """
    if not (key and "optimi" in key.lower() and row):
        return "NOT_TESTED_BY_THIS_INSTRUMENT"
    if "not" in (row.get("data_plane") or "").lower():
        return "DOC_CONFIRMED"
    if hist:
        return "AWS_BEHAVIOR_CHANGED"
    return "DOC_REFUTED_CHANGE_DATE_UNDETERMINED"


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan; make no API and no HTTP call")
    ap.add_argument("--regions", nargs="*", default=None,
                    help="override the region list (default: 5 supported + 3 controls)")
    ap.add_argument("--no-docs", action="store_true",
                    help="instrument A only; skip the documentation comparison")
    ap.add_argument("--wayback-snapshots", type=int, default=6)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)

    regions = args.regions if args.regions is not None else (
        SUPPORTED_REGIONS + CONTROL_REGIONS)

    if args.dry_run:
        print(f"{CASE} dry run — no AWS call, no HTTP request, $0\n")
        print(f"instrument A: ec2:DescribeVpcEndpointServices "
              f"x {len(regions)} regions x 2 calls (filtered + unfiltered)")
        for r in regions:
            tag = "supported" if r in SUPPORTED_REGIONS else "CONTROL (unsupported)"
            print(f"    {r:<16} {tag}")
        print(f"  filter: {SERVICE_FILTER}")
        print(f"  keyword search over the unfiltered list: "
              f"{ {k: v for k, v in PRIMITIVE_KEYWORDS.items()} }")
        print(f"\ninstrument B: GET {DOC_URL}")
        print(f"  + up to {args.wayback_snapshots} distinct-content Wayback snapshots")
        print(f"\ntotal AWS calls: {len(regions) * 2}   billable: 0   "
              f"mutations: 0")
        print("\nOracles:")
        print("  caveat (b) third gateway endpoint      -> present in every region")
        print("  no Evaluations/Optimization endpoint   -> zero keyword hits")
        print("  control regions also carry all 3       -> existence != availability")
        print("  Evaluations data-plane support         -> instrument B, dated")
        return 0

    store = EvidenceStore(run_id=args.run_id or new_run_id(),
                          family=FAMILY, case_id=CASE)
    store.write_environment()
    print(f"{CASE}  run {store.run_id}  ->  {store.dir.relative_to(ROOT)}")

    api = []
    for r in regions:
        rec = enumerate_region(store, r)
        api.append(rec)
        if rec.get("reachable"):
            print(f"  {r:<16} {rec['n_agentcore']} agentcore / "
                  f"{rec['n_all_services']} services   "
                  f"hits={ {k: len(v) for k, v in rec['primitive_keyword_hits'].items()} }")
        else:
            print(f"  {r:<16} UNREACHABLE {rec.get('error_code')}")

    doc_now: dict = {"ok": False, "error": "skipped (--no-docs)"}
    snaps: list[dict] = []
    if not args.no_docs:
        doc_now = fetch_doc_now(store.dir)
        snaps = fetch_wayback(store.dir, args.wayback_snapshots)
        print(f"  doc live: table={doc_now.get('has_support_table')} "
              f"rows={len(doc_now.get('rows', {}))}")
        for s in snaps:
            if s.get("ok"):
                ev = {k: v["data_plane"] for k, v in s.get("rows", {}).items()
                      if "evaluat" in k.lower()}
                print(f"  doc {s['timestamp']}: table={s['has_support_table']} "
                      f"evaluations={ev or '-'}")

    result = classify(api, doc_now, snaps)
    payload = {"case_id": CASE, "billable_calls": 0, "mutations": 0,
               "regions_requested": regions,
               "instrument_A": api,
               "instrument_B": {"live": doc_now, "wayback": snaps},
               "analysis": result}
    (store.dir / "analysis.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    store.write_summary({"analysis_file": "analysis.json"})

    print("\nverdicts:")
    for k, v in result["findings"].items():
        print(f"  {v['verdict']:<34} {k}")
    print(f"\nwrote {(store.dir / 'analysis.json').relative_to(ROOT)}")

    # Exit code reflects whether the test RAN, not whether the document was right.
    # A finding that contradicts the document is a successful test.
    unreachable = [r for r in api if not r.get("reachable")]
    if len(unreachable) == len(api):
        print("FATAL: no region was reachable — nothing was measured", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
