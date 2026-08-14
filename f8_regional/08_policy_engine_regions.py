#!/usr/bin/env python3
"""F8-1: is guardrails-in-policy available in exactly the 5 Regions the document lists?

    python3 f8_regional/08_policy_engine_regions.py --dry-run
    python3 f8_regional/08_policy_engine_regions.py

The sealed oracle (claims/triage_rules.CASES["F8-1"], kind C): TRUE if a policy-engine
MUTATION succeeds in the 5 listed Regions and fails in the others with a distinguishable
error; FALSE on any mismatch. Its second sentence is the design: "Control-plane List*
returns 200 everywhere, so only mutations can settle this." A `ListPolicyEngines` in a
Region where the feature does not exist is a 200 about nothing — the same shape as F8-8's
finding that an absent field is not a rejection — so the probe is one real
`CreatePolicyEngine` per Region, deleted in a `finally` the moment it has served.

WHERE THE REGION LISTS COME FROM, AND WHERE THEY DO NOT
-------------------------------------------------------
The five "listed Regions" are NOT typed in this file. They are parsed at run time out of
the sealed claim row `C-s1-quote-001` in `claims/triage.csv` — a bound artifact pinned by
sha256 in `PREREGISTRATION.yaml:meta.bound_artifacts` — which names them as display names
("US East (N. Virginia), Europe (London), Europe (Stockholm), Asia Pacific (Sydney), and
Asia Pacific (Tokyo)"). Display names are mapped to Region codes through the endpoints
data shipped inside botocore, which is itself an artifact of the pinned SDK and not a
recollection. The count 5 is parsed from the sealed case TITLE ("exactly 5 Regions") and
cross-checked against the sealed binding's threshold; the count 9 is parsed from the
sealed METHOD text ("9-region probe"). `f1_config/02_model_surface.py` states the
principle this follows: a paraphrase of a sealed value is an unchecked second copy, and a
parser that finds nothing must refuse loudly rather than substitute a guess.

The parse is then required to equal `lib/awsclients.GUARDRAILS_IN_POLICY_SUPPORTED` — the
list the client factory's own docstring calls F8-1's — and a disagreement stops the case:
two derivations of one sealed fact disagreeing means at least one of them is wrong, and
probing under either would attribute the choice to the seal.

TWO DEVIATIONS, STATED RATHER THAN SMOOTHED
-------------------------------------------
1. The seal names the 5 available Regions and does NOT name the 4 unavailable ones the
   9-region probe needs. Those four (`GUARDRAILS_IN_POLICY_UNSUPPORTED` in
   lib/awsclients.py: us-west-2, eu-central-1, sa-east-1, ap-south-1) are therefore a
   HARNESS choice, not a sealed one, and the payload records them as a deviation.
2. The one unavailable Region the seal DOES name — "Singapore (ap-southeast-1) ... NOT
   yet supported" — is not among the four probed. So the seal's single explicit negative
   example goes untested by the default Region set. Recorded as a named gap
   (`seal_named_unsupported_not_probed`); `--regions` can add it, and doing so is itself
   a further deviation the payload records.

"DISTINGUISHABLE ERROR" — THE TAXONOMY, AND WHAT EACH CLASS LICENSES
--------------------------------------------------------------------
TRUE requires the failures to identify the FEATURE as unavailable, not to be any failure
at all. Every non-success is classified (`classify_failure`), and the classes carry
different weight:

* `feature_not_available` — a service-side refusal whose code or message says the
  operation/feature is not supported/available/enabled there. The only class that fully
  supports the oracle's failure branch: the request crossed the network, the service
  answered, and the answer names the absence.
* `access_denied` — an IAM fact about THIS caller, not a regional fact about the service:
  a missing action in `runner/iam_policy.py` produces an error that reads exactly like
  unavailability in every Region at once. Never supports the verdict; any occurrence makes
  that Region unmeasured. (`CreatePolicyEngine` and `DeletePolicyEngine` ARE both mapped
  in `runner/iam_policy.py:MAPPING`, checked while writing this file — so an AccessDenied
  here would mean a caller other than the runner's derived role.)
* `endpoint_unresolvable` — botocore could not connect to (or resolve) the endpoint for
  this Region-service pair. THE POSITION TAKEN HERE: this is admissible as a
  distinguishable unavailability signal, but only CONDITIONALLY — when at least one other
  Region in the same run completed a round trip, which rules out "this machine is
  offline" as the explanation. The DNS zone for a service hostname is operated by AWS,
  so an NXDOMAIN is a fact about AWS's deployment of the service, not about this client;
  but it is weaker than a service-side refusal (an endpoint can exist behind a name the
  SDK's ruleset does not predict), and the payload labels every such Region
  `basis=endpoint_corroborated` so a reader can discount it separately.
* `throttled` — says only that the control plane exists and is busy; supports nothing;
  the Region is unmeasured.
* `unclassified` — an error nobody has read. NEVER scored as a supporting failure: an
  unanticipated error counted toward TRUE would let any new failure mode confirm the
  document, which is the filter-decides-the-finding defect
  `f8_regional/07_absent_surface.py` names. It forces INCONCLUSIVE with the code and
  message recorded.

"FALSE on any mismatch" is honored literally: one engine created in an unavailable
Region, or one clean feature_not_available in a listed Region, decides FALSE even if
other Regions are ambiguous. TRUE additionally requires every intended Region to be
decisive — a 7/9 probe cannot report on a 9-region claim.

WHAT A PROBE MUST NOT DAMAGE
----------------------------
Every engine this case creates is (a) named under its own prefix `grx_pe_f81_`,
(b) tagged via `A.tags_for` so the teardown sweep can find an orphan, and (c) deleted in
a `finally`, per Region. `assert_deletable` refuses to delete anything that is not in
this run's own created list — in particular the ledger's baseline engine
(state.json policy-engine/main, which later phases read), the two abandoned
`agentcore_test_pe_*` engines, and anything `harness_*`/`uitestagent_*`. Residue is
computed from the created list AGAINST the deletions list (`phase1.probe_residue`'s
two-list rule, restated in `residue()`): an engine whose delete was never ATTEMPTED
contributes no deletion row, so a residue read off the deletions alone reports zero
survivors in exactly the case where one exists. Residue is reported per engine id and
Region, never as one bool — a leaked policy engine in an unrelated Region is the worst
possible residue here, and "teardown failed" without an id is a sweep of a $27k/mo
account.

THE THREE PER-REGION FAILURE MODES THIS FILE DEFENDS AGAINST BY CONSTRUCTION
----------------------------------------------------------------------------
1. A silent default Region. `A.factory(region)` pins the region on the session and on
   every client, and `assert_region_pinned` still re-reads `client.meta.region_name`
   and the endpoint host BEFORE the call and records both: a probe that fell back to a
   default would report the default's availability nine times, which is the single most
   likely silent failure in a multi-region loop.
2. A loop whose exit status is its last iteration. Every Region prints a marker line
   (`REGION <r>: ...`) and its end state is verified per Region; the run's rc is
   computed from the intended-vs-probed comparison and the residue, never from whatever
   the ninth iteration happened to do.
3. An uncaught exception that skips the remaining Regions. Each Region's probe is
   wrapped; an exception becomes outcome `harness_error` for THAT Region and the loop
   continues. The count of Regions actually probed is then asserted against the intended
   list — this repo once lost 74 of 164 controls to a loop that died quietly partway.

n, AND WHY IT IS NEITHER 0 NOR A CORPUS SIZE
--------------------------------------------
`O.planned_n("F8-1")` is None (the binding names no sample-size cell) and
`O.mutation_is_mandatory("F8-1")` is False; both are read at run time and honored rather
than assumed. `n` is passed as the number of Regions whose probe completed. F1-4 passes
n=0 because its probes are validator runs against a shape — no request exists; that
reasoning was read and deliberately NOT copied: these nine probes are real mutations
against a live service, each one a trial the conjunction is evaluated over, so 9 is the
denominator a reader would check a sealed n against. With planned_n None, the value
asserts no shortfall either way; it records what ran.

COST
----
Control plane only. No model invocation, no ApplyGuardrail, no InvokeGuardrailChecks —
zero text units. Per infra/03_policy_engine.py (and cost_model.yaml, which prices policy
engines nowhere): policy engines carry no per-hour and no per-engine charge; evaluation
is billed at the gateway, and nothing here touches a gateway. The engines exist for the
seconds between create and delete. CreatePolicyEngine/DeletePolicyEngine are quota-limited
to 1/s (aws_documented), so the run's floor is ~14 s of pacing.
"""

from __future__ import annotations

import csv
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
import testbed as T      # noqa: E402
from evidence import EvidenceStore, capture  # noqa: E402

FAMILY = "f8"
CASE = "F8-1"

TRIAGE_CSV = ROOT / "claims" / "triage.csv"

# The anchor inside the sealed claim text. A MARKER the parser requires, not a copy of
# the region list: if the sealed sentence is ever rewritten so the marker vanishes, the
# parse refuses and the case stops, rather than this file quietly supplying regions of
# its own. The display-name enumeration is consumed from immediately after it.
SEAL_AVAILABLE_MARKER = "available only in"

# The name grammar for CreatePolicyEngine forbids hyphens (^[A-Za-z][A-Za-z0-9_]*$, max
# 48 — DEV-P2-02), so the region code is folded to underscores. The prefix is this case's
# own namespace: `assert_deletable` refuses anything outside it, which is what keeps the
# ledger's baseline engine and the two abandoned `agentcore_test_pe_*` engines out of
# reach even if an id were somehow confused.
ENGINE_NAME_PREFIX = "grx_pe_f81_"

_REGION_CODE_RE = re.compile(r"\b[a-z]{2}(?:-[a-z]+)+-\d\b")

ENGINE_TERMINAL_OK = {"ACTIVE"}
ENGINE_TERMINAL_BAD = {"CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"}

# Error-code allowlists for the classifier. Codes, not families: an allowlist means a new
# code lands in `unclassified` and forces INCONCLUSIVE instead of being swallowed into a
# supporting class — the same direction `f1_config/02_model_surface.py` chooses for its
# mode-scan false positives.
_ACCESS_DENIED_CODES = frozenset({
    "AccessDeniedException", "AccessDenied", "UnauthorizedOperation",
    "UnauthorizedException", "AuthorizationErrorException",
})
_THROTTLE_CODES = frozenset({
    "ThrottlingException", "Throttling", "TooManyRequestsException",
    "RequestLimitExceeded", "ServiceQuotaExceededException",
})
_FEATURE_ABSENT_CODES = frozenset({
    "UnknownOperationException", "InvalidAction", "UnsupportedOperationException",
    "UnsupportedRegionException", "OperationNotPermittedException",
})
# Codes that are only feature-absence when their MESSAGE says so; the codes themselves
# are used for ordinary validation failures too, and counting a bare ValidationException
# as absence would score a malformed request as regional evidence.
_FEATURE_ABSENT_IF_MESSAGE = frozenset({
    "ValidationException", "BadRequestException", "ResourceNotFoundException",
    "ServiceUnavailableException", "InternalFailure",
})
_FEATURE_ABSENT_MESSAGE_RE = re.compile(
    r"(?i)\bnot\s+(?:yet\s+)?(?:supported|available|enabled|authorized to access)\b"
    r"|\bis\s+not\s+available\s+in\b|\bunsupported\s+region\b")
_ENDPOINT_ERROR_CLASSES = frozenset({
    "EndpointConnectionError", "ConnectTimeoutError", "EndpointResolutionError",
    "UnknownEndpointError", "EndpointURLError", "InvalidRegionError",
})
_ENDPOINT_MESSAGE_RE = re.compile(
    r"(?i)could not connect to the endpoint url|name or service not known"
    r"|nodename nor servname|failed to resolve|NXDOMAIN")


# ---------------------------------------------------------------------------
# region derivation — every list traced to the seal or declared a deviation
# ---------------------------------------------------------------------------

def region_descriptions() -> dict[str, str]:
    """AWS's own display-name -> Region-code map, from botocore's shipped endpoints data.

    This is the artifact that turns the sealed row's "Europe (Stockholm)" into
    `eu-north-1` without this file remembering the correspondence. Read off a bare
    botocore session for the reason `awsclients.service_model` gives: no client, no
    credential walk, no socket. Refuses an empty read — a display-name map with zero
    entries would make every parse return zero regions, and a zero-region scan must be
    an error, not a pass.
    """
    import botocore.session
    data = botocore.session.get_session().get_data("endpoints")
    out: dict[str, str] = {}
    for part in data.get("partitions") or []:
        if part.get("partition") != "aws":
            continue          # the claim is about the commercial partition
        for code, meta in (part.get("regions") or {}).items():
            desc = (meta or {}).get("description")
            if desc:
                out[desc] = code
    if not out:
        raise RuntimeError(
            "botocore's endpoints data yielded zero region descriptions; the display-name "
            "map is the instrument that reads the sealed row, and an empty instrument "
            "must stop the case rather than parse every seal as empty")
    return out


def sealed_rows_for_case(case_id: str, path: Path = TRIAGE_CSV) -> list[tuple[str, str]]:
    """(claim_id, text) for every sealed claim row bound to `case_id`.

    Read from claims/triage.csv — pinned by sha256 in PREREGISTRATION.yaml — via the
    header's own column names rather than positions, so a column added to the seal fails
    here loudly instead of silently shifting which field is read as the text.
    """
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise RuntimeError(f"{path} is empty; the sealed claim rows are the only source "
                           f"of the region list and an empty seal cannot supply one")
    header = rows[0]
    try:
        i_id, i_cases, i_text = (header.index(k) for k in ("claim_id", "cases", "text"))
    except ValueError as exc:
        raise RuntimeError(f"{path} header {header} lacks an expected column: {exc}")
    out = [(r[i_id], r[i_text]) for r in rows[1:]
           if len(r) > max(i_cases, i_text) and case_id in r[i_cases].split()]
    if not out:
        raise RuntimeError(f"no sealed claim row in {path.name} is bound to {case_id}; "
                           f"the region list has no sealed carrier")
    return out


_ENUM_SEPARATOR_RE = re.compile(r"[\s,]*(?:\band\s+)?")


def parse_supported_regions(text: str,
                            desc_to_code: dict[str, str]) -> tuple[str, ...]:
    """The Region codes the sealed sentence lists as available, in the seal's own order.

    The parse consumes the ENUMERATION itself: starting right after "available only in",
    it repeatedly accepts a separator (whitespace, commas, "and") followed by a FULL
    display name from botocore's map, and stops at the first token that is neither. That
    boundary is load-bearing in two directions: it survives the period inside
    "US East (N. Virginia)" — which breaks naive sentence splitting — and it stops
    before the NEXT sentence, so a display name mentioned later in a not-supported
    clause cannot leak into the available set. ("Singapore (ap-southeast-1)" is a raw
    code rather than a display name, and "most other Asia Pacific Regions" has no
    parenthesised city, so neither matches regardless.) An empty parse raises: a
    five-region oracle compared against an empty expected set would fail every Region
    from a parser that read nothing, exactly the defect `expected_enum_from_seal`
    refuses.
    """
    start = text.find(SEAL_AVAILABLE_MARKER)
    if start < 0:
        raise ValueError(
            f"the sealed text carries no {SEAL_AVAILABLE_MARKER!r} marker, so the "
            f"available-Region list cannot be located in it; refusing to guess")
    tail = text[start + len(SEAL_AVAILABLE_MARKER):]
    names_longest_first = sorted(desc_to_code, key=len, reverse=True)
    codes: list[str] = []
    i = 0
    while True:
        i = _ENUM_SEPARATOR_RE.match(tail, i).end()
        hit = next((d for d in names_longest_first if tail.startswith(d, i)), None)
        if hit is None:
            break
        codes.append(desc_to_code[hit])
        i += len(hit)
    found = tuple(codes)
    if not found:
        raise ValueError(
            "zero Region display names parsed out of the sealed availability sentence; "
            "an empty derivation must be an error, not a pass — a probe over zero "
            "Regions would confirm anything")
    if len(set(found)) != len(found):
        raise ValueError(f"duplicate Region codes parsed from the seal: {found}")
    return found


def explicitly_unsupported_from_seal(text: str,
                                     supported: tuple[str, ...]) -> tuple[str, ...]:
    """Raw Region codes the sealed text itself names as NOT supported.

    The seal writes exactly one — "Singapore (ap-southeast-1)" — as a literal code, not
    a display name. Extracted so the payload can say whether the probe set covers the
    seal's own negative example (today it does not; that is a recorded gap)."""
    return tuple(c for c in _REGION_CODE_RE.findall(text) if c not in set(supported))


def sealed_supported_count() -> int:
    """The 5 in "exactly 5 Regions", parsed from the sealed case TITLE.

    Cross-checked against the sealed binding's threshold (lib/oracle.py pins 5.0 with
    prose token "5", itself gate-checked against the oracle text) so the two sealed
    carriers of the same number cannot drift apart silently."""
    title = O.cases()[CASE][1]
    m = re.search(r"exactly\s+(\d+)\s+Regions", title)
    if not m:
        raise ValueError(f"the sealed title {title!r} carries no 'exactly N Regions' "
                         f"count to check the parsed region list against")
    n = int(m.group(1))
    thresholds = O.BINDINGS[CASE].thresholds
    if thresholds and int(thresholds[0]) != n:
        raise ValueError(f"the sealed title says {n} Regions but the sealed binding's "
                         f"threshold is {thresholds[0]}; two sealed carriers of one "
                         f"number disagree and neither may be preferred silently")
    return n


def sealed_probe_count() -> int:
    """The 9 in "9-region probe", parsed from the sealed METHOD text."""
    method = O.cases()[CASE][4]
    m = re.search(r"(\d+)-region", method)
    if not m:
        raise ValueError(f"the sealed method text {method!r} names no probe width")
    return int(m.group(1))


def supported_regions_from_seal() -> dict[str, Any]:
    """The 5 available Regions, derived end to end, with the derivation recorded.

    The parse must agree with `awsclients.GUARDRAILS_IN_POLICY_SUPPORTED` — the constant
    the harness's probe machinery documents as F8-1's — because two derivations of one
    sealed fact disagreeing means at least one is wrong, and probing under either would
    attribute the choice to the seal.
    """
    descs = region_descriptions()
    rows = sealed_rows_for_case(CASE)
    parsed: tuple[str, ...] | None = None
    carrier = None
    text = ""
    for claim_id, row_text in rows:
        if SEAL_AVAILABLE_MARKER in row_text:
            if parsed is not None:
                raise RuntimeError(
                    f"two sealed rows for {CASE} both carry the availability marker "
                    f"({carrier} and {claim_id}); which one supplies the list would be a "
                    f"choice this script may not make silently")
            parsed = parse_supported_regions(row_text, descs)
            carrier, text = claim_id, row_text
    if parsed is None:
        raise RuntimeError(
            f"no sealed row bound to {CASE} carries the {SEAL_AVAILABLE_MARKER!r} "
            f"marker; the region list has no sealed carrier and this file refuses to "
            f"supply one from memory")
    want = sealed_supported_count()
    if len(parsed) != want:
        raise RuntimeError(
            f"the sealed row {carrier} yields {len(parsed)} Regions {parsed} but the "
            f"sealed title says exactly {want}; a partial parse must stop the case")
    harness = tuple(A.GUARDRAILS_IN_POLICY_SUPPORTED)
    if set(parsed) != set(harness):
        raise RuntimeError(
            f"the seal-derived list {parsed} disagrees with "
            f"awsclients.GUARDRAILS_IN_POLICY_SUPPORTED {harness}; two derivations of "
            f"one sealed fact disagree, so at least one is wrong and neither may be "
            f"probed under the seal's name")
    return {
        "regions": parsed,
        "sealed_carrier": carrier,
        "sealed_count": want,
        "seal_named_unsupported": explicitly_unsupported_from_seal(text, parsed),
        "display_name_map": "botocore endpoints data (aws partition)",
        "provenance": (
            f"parsed from claims/triage.csv row {carrier} (bound artifact, sha256-pinned "
            f"in PREREGISTRATION.yaml), display names mapped to codes via the endpoints "
            f"data shipped in the pinned botocore; count checked against the sealed "
            f"title and binding; result checked equal to "
            f"awsclients.GUARDRAILS_IN_POLICY_SUPPORTED"),
    }


def probe_regions(supported: tuple[str, ...]) -> dict[str, Any]:
    """The 9 probed Regions: the already-derived harness list, validated against the seal.

    `awsclients.F8_1_REGIONS` is imported rather than re-derived (its five supported
    members are the seal's; its four others are the harness's choice). Validated: the
    width must equal the sealed method's 9, the supported five must all be present, and
    the remainder is recorded as the DEVIATION it is — the seal names no unavailable
    Regions except ap-southeast-1, which this list does not include.
    """
    regions = tuple(A.F8_1_REGIONS)
    if not regions:
        raise RuntimeError("awsclients.F8_1_REGIONS is empty; a zero-region probe must "
                           "be an error, not a pass")
    if len(set(regions)) != len(regions):
        raise RuntimeError(f"duplicate Regions in the probe list {regions}")
    want = sealed_probe_count()
    if len(regions) != want:
        raise RuntimeError(
            f"the probe list has {len(regions)} Regions but the sealed method says a "
            f"{want}-region probe; the width is sealed even though the membership of "
            f"the unavailable side is not")
    missing = [r for r in supported if r not in regions]
    if missing:
        raise RuntimeError(f"the probe list omits sealed available Region(s) {missing}; "
                           f"the success half of the oracle would be unmeasurable")
    others = tuple(r for r in regions if r not in set(supported))
    return {
        "regions": regions,
        "unsupported_probed": others,
        "deviation": (
            f"the seal names the {len(supported)} available Regions and the probe WIDTH "
            f"({want}) but not which unavailable Regions fill it; the {len(others)} "
            f"others {list(others)} are lib/awsclients.py's choice, not the seal's — a "
            f"deviation for DEVIATIONS.md"),
    }


# ---------------------------------------------------------------------------
# the probe's pure parts, kept importable for the offline suite
# ---------------------------------------------------------------------------

def engine_name(run_id: str, region: str) -> str:
    """A per-Region, per-run engine name inside this case's own namespace.

    Underscores throughout: CreatePolicyEngine's name grammar forbids hyphens
    (DEV-P2-02), and `testbed.check_name` re-checks against the live model before any
    call is spent."""
    return f"{ENGINE_NAME_PREFIX}{region.replace('-', '_')}_{run_id}"


def assert_region_pinned(client, region: str) -> dict[str, Any]:
    """Prove the client is pinned to `region` BEFORE the call, and record the proof.

    A probe that silently resolved a default Region would report that Region's
    availability nine times while the records said otherwise. `awsclients.ClientFactory`
    already makes the region unforgeable; this re-reads what botocore actually resolved
    — the region and the endpoint host — because the guarantee worth publishing is the
    one that was checked on this run, not the one the factory's docstring promises.
    """
    resolved = client.meta.region_name
    endpoint = getattr(client.meta, "endpoint_url", "") or ""
    if resolved != region:
        raise RuntimeError(
            f"client resolved region {resolved!r}, not the intended {region!r}; a probe "
            f"under the wrong region would file this Region's verdict from another "
            f"Region's behaviour")
    if region not in endpoint:
        raise RuntimeError(
            f"client endpoint {endpoint!r} does not name region {region!r}; the region "
            f"attribute and the wire destination disagree, and the wire is what the "
            f"probe measures")
    return {"intended": region, "resolved": resolved, "endpoint": endpoint}


def classify_failure(*, error_code: str, error_class: str, error_message: str,
                     http_status: int | None) -> dict[str, Any]:
    """Place one non-success into the taxonomy the module docstring defends.

    The return's `supports_absence` is three-valued on purpose:
      "yes"          — service-side, names the absence; fully supports the oracle.
      "conditional"  — endpoint/DNS; supports only with a same-run network control.
      "never"        — IAM, throttle, or unread; the Region is unmeasured.
    """
    code, klass, msg = error_code or "", error_class or "", error_message or ""
    if code in _ACCESS_DENIED_CODES:
        return {"class": "access_denied", "supports_absence": "never",
                "licenses": ("a statement about THIS caller's IAM policy, not about the "
                             "Region: a missing action reads identically in every Region "
                             "at once, so it cannot distinguish anything regional")}
    if code in _THROTTLE_CODES or http_status == 429:
        return {"class": "throttled", "supports_absence": "never",
                "licenses": ("proof the control plane exists and is busy — which leans "
                             "AGAINST absence if anything; the Region is unmeasured")}
    if code in _FEATURE_ABSENT_CODES or (
            code in _FEATURE_ABSENT_IF_MESSAGE and
            _FEATURE_ABSENT_MESSAGE_RE.search(msg)):
        return {"class": "feature_not_available", "supports_absence": "yes",
                "matched_message": bool(_FEATURE_ABSENT_MESSAGE_RE.search(msg)),
                "licenses": ("a service-side refusal naming the absence: the request "
                             "crossed the network and the service answered that the "
                             "feature is not there — the distinguishable error the "
                             "sealed oracle requires")}
    if klass in _ENDPOINT_ERROR_CLASSES or _ENDPOINT_MESSAGE_RE.search(msg):
        return {"class": "endpoint_unresolvable", "supports_absence": "conditional",
                "licenses": ("the SDK found no reachable endpoint for this "
                             "Region-service pair. AWS operates the DNS zone, so an "
                             "unresolvable service hostname is evidence about AWS's "
                             "deployment — but it is client-adjacent, so it counts only "
                             "when another Region completed a round trip in the same "
                             "run, and it is labelled weaker than a service refusal")}
    return {"class": "unclassified", "supports_absence": "never",
            "licenses": ("an error nobody has read. Scoring it as a supporting failure "
                         "would let any new failure mode confirm the document; it "
                         "forces INCONCLUSIVE with the code and message on record")}


def verdict_from_outcomes(outcomes: list[dict], supported: tuple[str, ...],
                          intended: tuple[str, ...]) -> dict[str, Any]:
    """Map per-Region outcomes onto the sealed oracle. Pure; no I/O.

    FALSE on any mismatch (literal in the seal): an engine CREATED where the document
    says unavailable, or a clean feature_not_available where it says available, decides
    the case even if other Regions are ambiguous. TRUE only if EVERY intended Region is
    decisive in the supporting direction. Anything else — access denied, throttle,
    unclassified, pin failure, harness error, uncorroborated endpoint failure, or a
    Region never probed — leaves the case unmeasured, not confirmed.
    """
    sup = set(supported)
    by_region = {o["region"]: o for o in outcomes}
    network_control_ok = any(
        o["outcome"] in ("created", "feature_not_available") for o in outcomes)
    mismatches: list[dict] = []
    supports: list[dict] = []
    ambiguous: list[dict] = []
    for region in intended:
        o = by_region.get(region)
        if o is None:
            ambiguous.append({"region": region, "why": "never probed"})
            continue
        avail = region in sup
        oc = o["outcome"]
        row = {"region": region, "predicted_available": avail, "outcome": oc}
        if oc == "created":
            (supports if avail else mismatches).append(
                {**row, "basis": "mutation succeeded"})
        elif oc == "feature_not_available":
            (mismatches if avail else supports).append(
                {**row, "basis": "service-side refusal naming the absence"})
        elif oc == "endpoint_unresolvable" and network_control_ok:
            (mismatches if avail else supports).append(
                {**row, "basis": "endpoint_corroborated — no endpoint for the pair, "
                                 "with a same-run round trip elsewhere as the network "
                                 "control; weaker than a service refusal"})
        else:
            ambiguous.append({**row, "why": {
                "access_denied": "an IAM gap reads exactly like unavailability",
                "throttled": "the service answered busy, not absent",
                "unclassified": "an unread error must not support the verdict",
                "endpoint_unresolvable": "no same-run round trip anywhere, so a local "
                                         "network fault is not ruled out",
                "region_pin_failed": "the client was not provably in this Region",
                "harness_error": "the probe itself failed before the service answered",
            }.get(oc, oc)})
    # Each intended Region contributes exactly one row to exactly one of the three
    # lists, so `len(supports) == len(intended)` alone says "every Region, decisive,
    # supporting" — an explicit `not ambiguous` conjunct would be a guard that can
    # never fire (feedback_vacuous_test_check). `supports and` is NOT redundant: it is
    # what stops an empty intended list from producing TRUE by vacuity.
    if mismatches:
        verdict_bool: bool | None = False
    elif supports and len(supports) == len(intended):
        verdict_bool = True
    else:
        verdict_bool = None
    return {"verdict_bool": verdict_bool, "mismatches": mismatches,
            "supports": supports, "ambiguous": ambiguous,
            "network_control_ok": network_control_ok}


def residue(created: list[dict], deletions: list[dict]) -> dict[str, Any]:
    """What this case left behind, per engine id AND Region, from BOTH lists.

    `phase1.probe_residue`'s rule, restated because the keys here are (region, id)
    pairs: deriving survivors from the deletions list alone is circular — an engine
    whose delete was never ATTEMPTED (the loop died, the process was killed between the
    create and the finally) contributes no deletion row at all, so that residue reports
    zero survivors in exactly the case where one exists. Never a single bool: a survivor
    without its Region and id is a sweep of the whole account.
    """
    made = [(c["region"], c["engine_id"]) for c in created if c.get("engine_id")]
    attempted = {(d["region"], d["engine_id"]) for d in deletions}
    deleted = {(d["region"], d["engine_id"]) for d in deletions if d.get("deleted")}
    surviving = [{"region": r, "engine_id": e} for r, e in made if (r, e) not in deleted]
    return {
        "n_created": len(made),
        "n_delete_attempted": len(attempted),
        "n_deleted": len(deleted),
        "surviving": surviving,
        "never_attempted": [{"region": r, "engine_id": e}
                            for r, e in made if (r, e) not in attempted],
        "clean": not surviving,
        "why_two_lists": (
            "an engine whose delete was never ATTEMPTED contributes no deletion row, so "
            "a residue computed from the deletions alone reports zero survivors for "
            "exactly the case where one exists; created-vs-deleted is compared instead"),
    }


def assert_deletable(engine_id: str, name: str, created_ids: frozenset[str],
                     protected_ids: frozenset[str]) -> None:
    """Refuse to delete anything this run did not itself create.

    Three independent conditions, each sufficient to refuse: the id must be in THIS
    run's created list; the name must sit in this case's own `grx_pe_f81_` namespace
    (which excludes the ledger's baseline `grx_pe_<runid>`, the abandoned
    `agentcore_test_pe_*` engines, and every `harness_*`/`uitestagent_*` resource by
    construction); and the id must not appear in the ledger's protected set even if the
    first two somehow passed. A teardown that can only delete what it made cannot damage
    what later phases read.
    """
    if engine_id in protected_ids:
        raise RuntimeError(f"refusing to delete {engine_id}: it is a protected ledger "
                           f"engine that later phases read")
    if engine_id not in created_ids:
        raise RuntimeError(f"refusing to delete {engine_id}: it is not in this run's "
                           f"own created list, so it is someone else's resource")
    if not name.startswith(ENGINE_NAME_PREFIX):
        raise RuntimeError(f"refusing to delete {engine_id} ({name!r}): outside this "
                           f"case's {ENGINE_NAME_PREFIX!r} namespace")


def run_exit_code(*, n_probed: int, n_intended: int, residue_clean: bool) -> int:
    """rc reports whether the test RAN, never whether the document was right.

    0: every intended Region's probe completed AND every created engine was deleted.
    2: nothing was measured at all, or an engine survived anywhere (a survivor is the
       one outcome that must never exit clean, whatever the verdict said).
    1: the in-between — some Regions probed but not all.
    """
    if not residue_clean or n_probed == 0:
        return 2
    if n_probed < n_intended:
        return 1
    return 0


# ---------------------------------------------------------------------------
# live probe
# ---------------------------------------------------------------------------

def _wait_engine_terminal(client, engine_id: str, *, timeout_s: int = 180,
                          sleep=time.sleep) -> str:
    """Poll until the engine's status is terminal, so the delete is not racing CREATING.

    Raw reads, not `capture`d: this is a wait, not an observation, and sixty polling
    records per engine would bury the nine records that decide the case. Paced with an
    explicit sleep because the limiter has no GetPolicyEngine entry, and `lim.wait` on
    an unlisted operation is a silent no-op (lib/awsclients.py says so).
    """
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        try:
            last = str(client.get_policy_engine(policyEngineId=engine_id).get("status"))
        except Exception:                                   # noqa: BLE001 — transport blip
            last = "(get failed)"
        if last in ENGINE_TERMINAL_OK or last in ENGINE_TERMINAL_BAD:
            return last
        sleep(2.0)
    return last


def teardown(created: list[dict], factories: dict[str, Any], store: EvidenceStore,
             lim, created_ids: frozenset[str],
             protected_ids: frozenset[str]) -> list[dict]:
    """Delete every engine this run created, per Region; verify the end state per engine.

    Every engine is attempted even if an earlier delete failed — stopping at the first
    failure would orphan the rest for a reason unrelated to them. `deleted` is true only
    when the delete call succeeded AND a verification read afterwards found the engine
    gone or going: a 202 whose resource is still ACTIVE is not a deletion.
    """
    out: list[dict] = []
    for c in created:
        region, engine_id, name = c["region"], c["engine_id"], c["name"]
        row: dict[str, Any] = {"region": region, "engine_id": engine_id, "name": name,
                               "deleted": False, "delete_ok": False,
                               "verified_gone": False, "error_code": None,
                               "request_id": ""}
        try:
            assert_deletable(engine_id, name, created_ids, protected_ids)
            client = factories[region].agentcore_control()
            settled = _wait_engine_terminal(client, engine_id)
            row["status_before_delete"] = settled
            lim.wait("DeletePolicyEngine")
            rec = capture(store, "delete_policy_engine", client,
                          policyEngineId=engine_id)
            row.update(delete_ok=rec.ok, error_code=rec.error_code or None,
                       request_id=rec.request_id, evidence=rec.path)
            # End-state verification, per engine: the delete's 202 is a promise, and a
            # promise is not a residue reading.
            ver = capture(store, "get_policy_engine", client, policyEngineId=engine_id)
            if not ver.ok and ver.error_code in ("ResourceNotFoundException",
                                                 "NotFoundException"):
                row["verified_gone"] = True
            elif ver.ok and str((ver.response or {}).get("status")) in (
                    "DELETING", "DELETED"):
                row["verified_gone"] = True
            row["verify_evidence"] = ver.path
            row["deleted"] = bool(rec.ok and row["verified_gone"])
        except Exception as exc:                            # noqa: BLE001 — see docstring
            row["teardown_error"] = f"{type(exc).__name__}: {exc}"
        out.append(row)
        print(f"REGION {region}: teardown engine={engine_id} "
              f"deleted={row['deleted']} (delete_ok={row['delete_ok']} "
              f"verified_gone={row['verified_gone']})")
    return out


def probe_one_region(region: str, *, supported: set[str], run_id: str, tags: dict,
                     store: EvidenceStore, lim, factories: dict) -> dict[str, Any]:
    """One Region's mutation probe. Returns the outcome row; never raises."""
    out: dict[str, Any] = {"region": region,
                           "predicted_available": region in supported}
    try:
        f = A.factory(region)
        factories[region] = f
        client = f.agentcore_control()
        out["region_pin"] = assert_region_pinned(client, region)
    except Exception as exc:                                # noqa: BLE001
        out.update(outcome="region_pin_failed",
                   error=f"{type(exc).__name__}: {exc}")
        return out
    try:
        name = T.check_name(client, "CreatePolicyEngine", engine_name(run_id, region))
        out["engine_name"] = name
        lim.wait("CreatePolicyEngine")
        rec = capture(store, "create_policy_engine", client,
                      name=name,
                      description="F8-1 nine-region availability probe; deleted by the "
                                  "same run's finally",
                      tags=tags)
        out.update(request_id=rec.request_id, http_status=rec.http_status,
                   evidence=rec.path)
        if rec.ok:
            out.update(outcome="created",
                       engine_id=(rec.response or {}).get("policyEngineId"))
        else:
            cls = classify_failure(error_code=rec.error_code,
                                   error_class=rec.error_class,
                                   error_message=rec.error_message,
                                   http_status=rec.http_status)
            out.update(outcome=cls["class"], classification=cls,
                       error_code=rec.error_code, error_class=rec.error_class,
                       error_message=(rec.error_message or "")[:500])
    except Exception as exc:                                # noqa: BLE001
        # An uncaught exception here must cost THIS Region, not the remaining ones: the
        # 74-of-164 loss was a loop that died quietly partway. Recorded, and the
        # intended-vs-probed assertion downstream keeps it from passing silently.
        out.update(outcome="harness_error", error=f"{type(exc).__name__}: {exc}")
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:                          # noqa: C901
    ap = P.parser(CASE, __doc__)
    ap.add_argument("--regions", default=None,
                    help="comma-separated override of the probe list (a DEVIATION, "
                         "recorded in the payload as such)")
    ap.add_argument("--state", default=None, help="path to state.json (the ledger)")
    ap.add_argument("--evidence-root", default=None)
    ap.add_argument("--ttl-hours", type=int, default=24)
    args = ap.parse_args(argv)

    seal = supported_regions_from_seal()
    supported: tuple[str, ...] = seal["regions"]
    plan = probe_regions(supported)
    regions: tuple[str, ...] = plan["regions"]

    override_deviation = None
    if args.regions:
        regions = tuple(r.strip() for r in args.regions.split(",") if r.strip())
        if not regions:
            print("FATAL: --regions parsed to zero Regions; a zero-region probe is an "
                  "error, not a pass", file=sys.stderr)
            return 2
        override_deviation = (f"--regions override in force: {list(regions)} replaces "
                              f"the derived probe list — a per-run deviation")

    want_n = O.planned_n(CASE)               # None per the seal; honored, not assumed
    must_mutate = O.mutation_is_mandatory(CASE)   # False per the seal; see payload note
    n_avail = sum(1 for r in regions if r in set(supported))

    if args.dry_run:
        arms = [(f"probe:{r}" + (":available" if r in set(supported)
                                 else ":unavailable"),
                 "CreatePolicyEngine" + (" + DeletePolicyEngine" if r in set(supported)
                                         else " (delete only if it succeeds)"),
                 2 if r in set(supported) else 1)
                for r in regions]
        return P.dry_run_banner(
            CASE, arms,
            operations={"CreatePolicyEngine": len(regions),
                        "DeletePolicyEngine": n_avail},
            mutations=len(regions) + n_avail, billable=False,
            extra=[
                f"the 5 'listed Regions' were PARSED from sealed row "
                f"{seal['sealed_carrier']} in claims/triage.csv (sha256-pinned), display "
                f"names resolved via botocore's endpoints data: {list(supported)}",
                f"the {len(plan['unsupported_probed'])} predicted-unavailable Regions "
                f"{list(plan['unsupported_probed'])} are lib/awsclients.py's choice, NOT "
                f"the seal's — a recorded deviation; the seal's own named-unsupported "
                f"Region(s) {list(seal['seal_named_unsupported'])} are "
                f"{'NOT ' if not set(seal['seal_named_unsupported']) & set(regions) else ''}"
                f"in the probe set",
                "sent per Region: CreatePolicyEngine{name=grx_pe_f81_<region>_<runid>, "
                "description, tags=Project/RunId/Owner/ExpiresAt via A.tags_for} on a "
                "client whose resolved region and endpoint host are asserted equal to "
                "the intended Region BEFORE the call",
                "every engine created is deleted in a finally, per Region, and the end "
                "state is verified per engine id (get_policy_engine after the delete); "
                "residue is created-vs-deleted over both lists, never one bool",
                "MUST NOT TOUCH: the ledger engine grx_pe_<runid> (baseline policy, read "
                "by later phases), the 2 abandoned engines, the 6 READY gateways, the 3 "
                "DRAFT guardrails, the nopolicy gateway, harness_*/uitestagent_* — "
                "assert_deletable refuses anything outside this run's own created list",
                "billable: control plane only — no model invocation, no ApplyGuardrail, "
                "no InvokeGuardrailChecks, ZERO text units; policy engines carry no "
                "per-hour and no per-engine charge (infra/03_policy_engine.py, "
                "cost_model.yaml prices them nowhere), so the projected spend is $0",
                f"pacing: CreatePolicyEngine/DeletePolicyEngine are 1/s "
                f"({A.limit_provenance('CreatePolicyEngine')}), so ~"
                f"{len(regions) + n_avail}s of rate-limit floor",
                f"planned_n={want_n!r} and mutation_is_mandatory={must_mutate} were read "
                f"from the seal at run time; n will be the count of Regions actually "
                f"probed (real mutations — NOT F1-4's n=0, which counts validator runs "
                f"that send nothing)",
                "rc: 0 = every intended Region probed and every engine deleted; 2 = "
                "nothing measured or residue survived; 1 = partial. The rc never encodes "
                "the verdict",
            ] + ([override_deviation] if override_deviation else []))

    # ---- live ----------------------------------------------------------------------
    protected_ids: frozenset[str] = frozenset()
    state = None
    try:
        state = T.State.load(Path(args.state) if args.state else None)
        run_id = args.run_id or state.run_id
        ledger_engine = state.find("policy-engine", "main")
        if ledger_engine:
            protected_ids = frozenset(
                v for v in ledger_engine.ids.values() if isinstance(v, str))
    except FileNotFoundError:
        run_id = P.resolve_run(args)
        print("note: no ledger found; the protected-id set is empty and the deletable "
              "guard rests on the created-list membership alone")

    expires = (datetime.now(timezone.utc)
               + timedelta(hours=args.ttl_hours)).replace(microsecond=0).isoformat()
    tags = A.tags_for(run_id, expires)
    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()
    lim = A.limiter()

    outcomes: list[dict] = []
    created: list[dict] = []
    factories: dict[str, Any] = {}
    deletions: list[dict] = []
    try:
        for region in regions:
            o = probe_one_region(region, supported=set(supported), run_id=run_id,
                                 tags=tags, store=store, lim=lim, factories=factories)
            outcomes.append(o)
            if o.get("outcome") == "created" and o.get("engine_id"):
                created.append({"region": region, "engine_id": o["engine_id"],
                                "name": o["engine_name"]})
            print(f"REGION {region}: predicted="
                  f"{'available' if o['predicted_available'] else 'unavailable'} "
                  f"outcome={o.get('outcome')} "
                  f"{o.get('engine_id') or o.get('error_code') or o.get('error') or ''}")
    finally:
        created_ids = frozenset(c["engine_id"] for c in created)
        deletions = teardown(created, factories, store, lim, created_ids,
                             protected_ids)

    res = residue(created, deletions)
    probed = [o for o in outcomes
              if o.get("outcome") not in (None, "harness_error", "region_pin_failed")]
    n_probed = len(probed)
    if n_probed != len(regions):
        missing = [o["region"] for o in outcomes if o not in probed]
        print(f"WARNING: {n_probed}/{len(regions)} intended Regions completed a probe; "
              f"incomplete: {missing}", file=sys.stderr)

    v = verdict_from_outcomes(outcomes, supported, regions)

    deviations = [plan["deviation"]]
    gap = [r for r in seal["seal_named_unsupported"] if r not in set(regions)]
    if gap:
        deviations.append(
            f"seal_named_unsupported_not_probed: the seal explicitly names {gap} as NOT "
            f"supported and the probe set does not include it/them, so the seal's own "
            f"negative example is untested by this run")
    if override_deviation:
        deviations.append(override_deviation)

    common: dict[str, Any] = {
        "run_id": run_id, "is_smoke": False,
        "billable_calls": 0,
        "mutations": len(regions) + len(deletions),
        "aws_calls": len(store.records),
        "ambient_sdk": A.sdk_versions(),
        "environment_region_hints": A.environment_region_hints(),
        "region_provenance": seal,
        "probe_plan": plan,
        "deviations": deviations,
        "planned_n_honored": {
            "planned_n": want_n,
            "mutation_is_mandatory": must_mutate,
            "reading": ("both read from the seal at run time. planned_n is None (the "
                        "binding names no sample-size cell), so n asserts no shortfall; "
                        "mutation_is_mandatory is False, and nothing here overrides "
                        "evaluate()'s downgrade rule should the seal ever change"),
        },
        "n_basis": ("n = Regions whose probe completed — real mutations against a live "
                    "service, one trial per Region of the conjunction. NOT F1-4's "
                    "deliberate n=0: that counts validator runs that send nothing, and "
                    "copying it here would erase nine live trials from the denominator"),
        "per_region": outcomes,
        "residue": res,
        "teardown": deletions,
        "error_taxonomy": {
            "feature_not_available": "supports the failure branch: service-side, names "
                                     "the absence",
            "access_denied": "never supports: an IAM gap reads exactly like "
                             "unavailability (CreatePolicyEngine/DeletePolicyEngine are "
                             "both mapped in runner/iam_policy.py, checked at writing)",
            "endpoint_unresolvable": "supports only with a same-run round trip "
                                     "elsewhere as the network control; labelled weaker",
            "throttled": "never supports: the control plane answered busy, not absent",
            "unclassified": "never supports; forces INCONCLUSIVE with the error named",
        },
        "instrument": ("one CreatePolicyEngine per Region on an explicitly "
                       "region-pinned bedrock-agentcore-control client, deleted in a "
                       "finally; List* is deliberately NOT used, because the sealed "
                       "oracle records that List* returns 200 everywhere"),
    }

    if res["surviving"]:
        print(f"FATAL: {len(res['surviving'])} engine(s) survived teardown: "
              f"{res['surviving']} — sweep with infra/99_teardown.py (tag "
              f"RunId={run_id})", file=sys.stderr)

    if v["verdict_bool"] is None:
        rec = O.not_measured(
            CASE,
            f"{len(v['ambiguous'])} Region(s) yielded no distinguishable outcome "
            f"({[a['region'] for a in v['ambiguous']]}); an ambiguous Region can be "
            f"neither the success nor the distinguishable failure the sealed oracle "
            f"requires, and no mismatch decided the case first",
            ambiguous=v["ambiguous"], supports=v["supports"])
        P.emit(CASE, rec, {**common, "why_inconclusive": (
            "access-denied, throttled, unclassified and uncorroborated endpoint "
            "failures are all indistinguishable from (or unreadable as) regional "
            "absence; scoring any of them would let the harness's own defects confirm "
            "the document")}, store)
        return run_exit_code(n_probed=n_probed, n_intended=len(regions),
                             residue_clean=res["clean"])

    o = P.obs_existence(
        CASE, v["verdict_bool"], n=n_probed,
        n_regions_intended=len(regions),
        n_regions_probed=n_probed,
        n_predicted_available=n_avail,
        n_supporting=len(v["supports"]),
        n_mismatch=len(v["mismatches"]),
        n_ambiguous=len(v["ambiguous"]),
        network_control_ok=v["network_control_ok"],
        outcomes_by_region={x["region"]: x.get("outcome") for x in outcomes})
    rec = O.evaluate(o)

    P.emit(CASE, rec, {
        **common,
        "verdict_rule": (
            "FALSE on any mismatch, literally per the seal: one engine created where "
            "the document says unavailable, or one service-side feature_not_available "
            "where it says available, decides the case even if other Regions are "
            "ambiguous. TRUE only if every one of the intended Regions is decisive in "
            "the supporting direction — a successful mutation in each of the 5, and a "
            "distinguishable (service-side, or endpoint-corroborated) refusal in each "
            "of the others. Ambiguity anywhere without a mismatch is INCONCLUSIVE"),
        "verdict_reading": (
            (f"TRUE: the mutation succeeded in exactly the {n_avail} sealed Regions "
             f"and was refused distinguishably in the other {len(regions) - n_avail}"
             if v["verdict_bool"] else
             "FALSE: at least one Region contradicts the sealed list — see mismatches")
            + ". Decided by mutations, not List*: a List* 200 in an absent Region is a "
              "200 about nothing, which is the sealed oracle's own second sentence"),
        "mismatches": v["mismatches"],
        "supports": v["supports"],
        "what_true_does_not_prove": (
            "that the 5-region list is COMPLETE against all ~34 commercial Regions — "
            "only 4 non-listed Regions were probed, and their membership is a harness "
            "choice, not the seal's; notably the seal's own named-unsupported Region "
            "(ap-southeast-1) is outside the default probe set. Nor anything about the "
            "feature WORKING in the 5: CreatePolicyEngine succeeding is the control "
            "plane accepting a mutation, not a policy evaluating a request — F4's truth "
            "table is where enforcement is measured. Nor that the list holds tomorrow: "
            "regional rollout is the most time-dependent claim in the document"),
        "why_this_matters_operationally": (
            "a reader who deploys AgentCore Gateway policy guardrails in a Region "
            "where the engine cannot be created ships a gateway with no policy hop at "
            "all, and the document's own §8 checklist item (sealed row "
            "C-s8-checkitem-003) tells them to confirm exactly this before designing a "
            "deployment"),
        "expiry": (
            "a statement about a ROLLOUT, and rollouts move in one direction: a Region "
            "joining the list flips its probe from refusal to success. Dated by this "
            "run's timestamps in the evidence records; a later success in a "
            "probed-unavailable Region belongs in AWS-BEHAVIOR-CHANGES.md, and "
            "re-running this script is how it is detected"),
    }, store)

    return run_exit_code(n_probed=n_probed, n_intended=len(regions),
                         residue_clean=res["clean"])


if __name__ == "__main__":
    sys.exit(main())
