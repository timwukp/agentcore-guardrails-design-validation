#!/usr/bin/env python3
"""F7-1, F7-2, F7-3: are the documented CloudWatch metrics actually published?

    python3 f7_observability/03_metrics_existence.py --dry-run
    python3 f7_observability/03_metrics_existence.py --n 3      # smoke
    python3 f7_observability/03_metrics_existence.py            # n=10 fresh calls

Three sealed oracles, three verdicts, one script — because all three are the same
measurement against three tables, and splitting them would mean three inventories of the
same namespaces taken at three different times.

    F7-1  "Per metric: TRUE if datapoints appear for our dimensions after traffic that
           should produce them; FALSE if absent. A documented-but-absent metric is a
           document defect."                        (the policy metrics, AWS/Bedrock-AgentCore)
    F7-2  "TRUE if Latency/Duration/Invocations/TargetExecutionTime/Throttles/SystemErrors/
           UserErrors all publish; FALSE for any absentee."   (the gateway metrics, same ns)
    F7-3  "TRUE if the namespace (not AWS/Bedrock) carries the 7 documented metrics; FALSE
           if the namespace or names differ."               (AWS/Bedrock/Guardrails)

WHY THIS SCRIPT DECIDES THE FINAL SCOPE OF DEV-P4-01
----------------------------------------------------
DEV-P4-01 records that no surface publishes a numeric guardrail score, measured on two
surfaces: the ApplyGuardrail response (F2-5: a four-value enum) and the span path
(`00_span_shape_probe.py`: 58 attribute paths, zero score-shaped). CloudWatch metrics are the
**third** surface, and the document explicitly claims `ConfidenceScore / ConfidenceThreshold`
on it. F7-1 is that measurement, and the reading is **pre-committed either way**:

  - if `ConfidenceScore` publishes datapoints, DEV-P4-01 must be narrowed to the two surfaces
    it actually measured, and the case that a per-trial harvest is impossible rests on the
    aggregation argument alone;
  - if it does not, DEV-P4-01 stands across all three surfaces.

Either way it does **not** restore the per-trial harvest F2-2/F2-3/F2-4/F1-18 pre-registered:
a CloudWatch metric is a per-period *aggregate* over whatever dimensions it carries, so even
a fully published `ConfidenceScore` yields a per-minute statistic and never a score attached
to one identified trial. That sentence is written here, before the measurement, so it cannot
be composed after seeing which way it went.

THE INSTRUMENT: THREE READINGS PER DOCUMENTED METRIC, AND WHY ONE IS NOT ENOUGH
------------------------------------------------------------------------------
1. **`list_metrics` inventory**, paginated over the whole namespace. This answers "does the
   name exist here at all", independent of dimensions, and it also enumerates the dimension
   names the service actually publishes — which is the only way to check the document's
   dimension claims (`ToolName, Category, Filter, Mode, PolicyEnforcementMode` for policy;
   `Operation, GuardrailArn/GuardrailVersion, GuardrailContentSource, GuardrailPolicyType`
   for guardrails) without guessing them.
2. **`GetMetricData` with a `SEARCH` expression** per metric over the PROJECT window. A plain
   `GetMetricData` query needs the dimension set to match *exactly*, so a query written with
   guessed dimensions returns empty for a metric that exists — an absence manufactured by the
   query. `SEARCH('Namespace="..." MetricName="..." <our-id>', 'Sum', 300)` matches every
   dimension combination the service publishes that mentions our own resource, so an empty
   result is about the service and not about our guess at the dimension set. The scope term is
   there for two reasons, both load-bearing — see "WHY EVERY SEARCH IS SCOPED" below.
3. **the same SEARCH over the FRESH window**, covering traffic this script generates. Weaker
   on its own (10 calls in one minute), but it is the only reading that ties a datapoint to
   traffic whose exact time we know.

`list_metrics` and `SEARCH` share a horizon: CloudWatch surfaces metrics that reported data
in roughly the **last two weeks**. Every reading here is therefore a statement about the
window, not about all time, and the window is recorded.

"TRAFFIC THAT SHOULD PRODUCE THEM" IS ESTABLISHED INDEPENDENTLY, NOT ASSUMED
---------------------------------------------------------------------------
An absent metric is only a document defect if the traffic that should produce it happened.
Otherwise "no datapoints" measures our own test plan. Three exercise bases, each evidenced
outside CloudWatch so the metric reading is not its own justification:

  FRESH_GATEWAY     the n tool calls this script sends, timestamped by the client.
  PROJECT_POLICY    every policy evaluation this project has run, including F4's
                    guardrail-bearing ACTIVE policies in ENFORCE — counted from our own
                    evidence tree, not from CloudWatch.
  PROJECT_GUARDRAIL our recorded ApplyGuardrail calls — again counted from the evidence tree.

If an exercise basis turns out to be empty, the metrics that depend on it are reported
NOT_EXERCISED and the case goes INCONCLUSIVE rather than FALSE. That is the difference
between "the document is wrong" and "we did not test it".

A PRE-COMMITTED DEVIATION: THREE METRICS CANNOT BE EXERCISED WITHOUT ABUSING A SHARED SERVICE
--------------------------------------------------------------------------------------------
F7-2's sealed oracle names seven metrics and says "FALSE for any absentee". Three of them
publish only when something goes wrong:

  Throttles      requires HTTP 429, i.e. driving a shared AWS service past its quota
  SystemErrors   requires a 5xx from the service, which we cannot induce at all
  UserErrors     requires a 4xx — and F4-6 measured that policy denials are HTTP **200** with
                 JSON-RPC -32002, so ordinary denials do not produce one either

Manufacturing 429s against a shared service to satisfy an oracle is a denial-of-service
shaped action, and it is refused. So these three are EXCLUDABLE — registered as DEV-P4-03
rather than silently applied, because F7-2's oracle admits no exclusions. Direction of the
bias, stated because it favours the experimenter: excluding them makes F7-2 **more likely to
come out TRUE**, i.e. it favours the document under test. The exclusions are listed in the
payload and printed, never summarised away.

THE EXERCISE BASIS GATES ONLY THE ABSENT DIRECTION
-------------------------------------------------
"Excludable", not "excluded". The basis exists to stop *an absence* from being read as a
document defect when the producing traffic never happened; it has nothing to say about a
datapoint that exists. The first implementation applied it to both directions and threw away
positive evidence — the first run recorded `MismatchErrors`, `TotalMismatchedPolicies` and
`PolicyMismatch` as NOT_EXERCISED while their own rows said `published: true`. So:

    published            -> scored TRUE, whatever the basis
    absent, exercised    -> scored FALSE (a document defect)
    absent, unexercised  -> NOT_EXERCISED, excluded from the conjunction, listed in the payload

This turned out to decide DEV-P4-03's three metrics. Measured over the 13-day project window
with the scope term fixed, `Throttles`, `SystemErrors` and `UserErrors` each return **8 series
and 123 datapoints** for our own gateway: the service publishes them as counters that report
zero, so they exist without any error having occurred. The refusal to manufacture 429s stands
and was never necessary for this case.

WHAT KEEPS AN EXISTENCE SWEEP FROM CONFIRMING ITSELF
---------------------------------------------------
A sweep that reports "found" for everything is indistinguishable from a broken matcher. The
document supplies two **negative** claims, and they are used as controls:

  `FirstByteLatency` — the doc says outright it "is not a valid gateway metric name; use
                       Latency". It must be ABSENT from AWS/Bedrock-AgentCore.
  `AWS/Bedrock`      — the doc says guardrail telemetry lands in AWS/Bedrock/Guardrails and NOT
                       in AWS/Bedrock. No metric in AWS/Bedrock may carry a GUARDRAIL
                       DIMENSION (GuardrailArn/GuardrailId/GuardrailVersion/GuardrailName).

The second control was first written as "the seven documented NAMES must be absent from
AWS/Bedrock", and that was invalid on the document's own terms: four of the seven —
Invocations, InvocationLatency, InvocationClientErrors, InvocationServerErrors — are Bedrock
MODEL RUNTIME metric names, and the document itself says that namespace "holds model runtime
metrics". A control demanding the absence of something the document asserts is present can only
fail, and its failure says nothing about the document. The claim is about which namespace
guardrail telemetry lands in, and what distinguishes a guardrail datapoint from a model
datapoint is its DIMENSIONS, not its name. The name collision is still measured and reported —
it is why the document's warning is worth making — but it is not scored. See DEV-P4-05.

If either control "finds" something, the matcher is too loose and every positive in this run
is suspect, so both are guards: failing them yields INCONCLUSIVE for the affected case, not a
verdict. This is the same reason F2-1 required 499.9 to be allowed and 500.0 denied.

WHY EVERY SEARCH IS SCOPED, AND WHY ONE METRIC PER CALL
------------------------------------------------------
The first non-dry run of this script issued all 22 SEARCH expressions in ONE GetMetricData
call. Expressions in one call share a cap on returned time series, and the six busiest
expressions consumed exactly 500 of them (UserErrors 278, Invocations 154, AllowDecisions 46,
LogOnlyDecisionFlips 14, TotalMismatchedPolicies 4, PolicyMismatch 4) while the other sixteen
returned nothing. The script scored those empties as absences and published FALSE for eight
metrics its own ListMetrics inventory listed as PRESENT in the same run. Those verdicts are
retracted; see DEV-P4-04.

So: one metric per call, and a `scope` term in every SEARCH restricting the match to our own
resource. The scope is not merely a cap workaround — F7-1's oracle says "for our dimensions",
and a sweep across six other teams' gateways was never the question. The unscoped read is
still taken, RECORDED AND NEVER SCORED, because it separates "not published for our resources"
from "not published for anyone". A read is trusted only if every returned series' StatusCode
is Complete AND no message is present at either level: the fresh-window read hit the same
500-series cap with an EMPTY message list, so checking messages alone would not have caught it.

TRUST GATES THE ABSENT DIRECTION ONLY
------------------------------------
A partial read can be missing datapoints it should have returned. It cannot invent datapoints
it did return. So truncation undermines an ABSENCE and never a PRESENCE, exactly like the
exercise basis below. Run 3 got this wrong in the opposite direction from run 1: it refused to
score F7-1 and F7-2 at all because ONE metric — `AllowDecisions`, with 40 series and 200
datapoints over the project window — came back with StatusCode `Paginated` and no NextToken to
follow. Withholding a verdict over a truncated PRESENCE is not caution, it is discarding the
only kind of evidence truncation cannot corrupt. The guard is therefore evaluated on
`untrusted_absences`: no metric may be scored absent on a read CloudWatch called partial.

COST
----
n `tools/call` on a Lambda target plus CloudWatch reads. **Zero text units**: this script
sends no ApplyGuardrail and creates no guardrail — F7-3 rests on the project's already-spent
guardrail traffic, which is why it costs nothing to ask the question again. `GetMetricData`
and `ListMetrics` are billed per metric requested at fractions of a cent; the whole run is
well under $0.01. No mutation, no resource created or changed.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                   # noqa: E402
import mcp as M                                          # noqa: E402
import oracle as O                                       # noqa: E402
import phase1 as P                                       # noqa: E402
import testbed as T                                      # noqa: E402
from evidence import EvidenceStore, capture              # noqa: E402

FAMILY = "f7"
CASES = ("F7-1", "F7-2", "F7-3")

NS_AGENTCORE = "AWS/Bedrock-AgentCore"
NS_GUARDRAILS = "AWS/Bedrock/Guardrails"
NS_BEDROCK = "AWS/Bedrock"          # the namespace the doc says is the WRONG one

TOOL = "echo"
TEXT = "f7-1/2/3 metric traffic"
ARM = "metrics"
PLANNED_N = 10

# Exercise bases. A metric is scored only if its basis is non-empty, and each basis is
# evidenced OUTSIDE CloudWatch so the metric reading is not its own justification.
EX_FRESH = "FRESH_GATEWAY"
EX_POLICY = "PROJECT_POLICY"
EX_GUARDRAIL = "PROJECT_GUARDRAIL"
EX_NONE = "NOT_EXERCISED"

# How far back the PROJECT window reaches. CloudWatch's list_metrics / SEARCH horizon is
# ~2 weeks, so a longer window would silently become a 2-week window while claiming more.
PROJECT_WINDOW_DAYS = 13
PROJECT_PERIOD_S = 300
FRESH_PERIOD_S = 60

# Seconds to wait after the fresh traffic before reading the fresh window. Deliberately
# generous; F7-6 is the case that MEASURES this lag rather than assuming it.
FRESH_SETTLE_S = 240

# The documented metrics, transcribed from the sealed claim rows in `claims/triage.csv` rather
# than re-read from the document, so the list cannot drift from what was pre-registered. Rows
# naming two or three metrics with a "/" are split: the document's table cell
# "ConfidenceScore / ConfidenceThreshold" is two metrics, and a sweep that looked for the
# literal cell text would report both absent.
GATEWAY_METRICS = (
    ("Latency", EX_FRESH, "published for any gateway request"),
    ("Duration", EX_FRESH, "published for any gateway request"),
    ("Invocations", EX_FRESH, "published for any gateway request"),
    ("TargetExecutionTime", EX_FRESH, "our target is a Lambda, so it executes on every call"),
    ("Throttles", EX_NONE,
     "requires HTTP 429, i.e. driving a shared AWS service past its quota. Refused: that is "
     "a denial-of-service shaped action against a service other systems in this account use"),
    ("SystemErrors", EX_NONE,
     "requires a 5xx from the service, which cannot be induced from the client at all"),
    ("UserErrors", EX_NONE,
     "requires a 4xx. F4-6 measured that policy denials return HTTP 200 with JSON-RPC -32002 "
     "and a bare tool name returns HTTP 200 with -32602, so neither of the client-side "
     "errors this testbed can produce is a 4xx"),
)

POLICY_METRICS = (
    ("GuardrailLatency", EX_POLICY, "guardrail evaluation inside a policy — F4 ran "
                                    "guardrail-bearing ACTIVE policies in ENFORCE"),
    ("ConfidenceScore", EX_POLICY, "claimed per evaluation; this is DEV-P4-01's third surface"),
    ("ConfidenceThreshold", EX_POLICY, "claimed per evaluation, alongside ConfidenceScore"),
    ("AllowDecisions", EX_POLICY, "every allowed call is an authorization outcome"),
    ("DenyDecisions", EX_POLICY, "F4 and F2-1 both produced hundreds of policy denials"),
    ("SuppressOutputs", EX_NONE,
     "requires a policy with the suppressOutput effect. No such policy was created by any "
     "phase of this project, so an absence here would measure our plan, not the document"),
    ("LogOnlyMatches", EX_POLICY, "F4's LOG_ONLY cells produced would-be matches"),
    ("LogOnlyDecisionFlips", EX_POLICY, "F4's LOG_ONLY cells are exactly this signal"),
    ("LogOnlyEvalIncomplete", EX_NONE,
     "requires an evaluation that cannot complete — the missing-attribute condition F4 hit "
     "at CREATE time, not at request time. Not reproducible on demand without deliberately "
     "shipping a broken policy, which would also change the axis F4 measured"),
    ("MismatchErrors", EX_NONE,
     "requires a guardrail evaluation failing on missing attributes or type mismatches; same "
     "objection as LogOnlyEvalIncomplete"),
    ("TotalMismatchedPolicies", EX_NONE,
     "requires the same failing evaluation as MismatchErrors: a policy whose guardrail clause "
     "references an attribute the request does not carry. Reproducing it means shipping a "
     "deliberately broken policy, which would also perturb the axis F4 measures"),
    ("PolicyMismatch", EX_NONE,
     "requires the same failing evaluation as MismatchErrors, per-policy rather than totalled; "
     "not reproducible without deliberately shipping a broken policy"),
    # From the table's own "not exhaustive" prose, which names three more by hand.
    ("DeterminingPolicies", EX_POLICY, "named in the section's prose; a determining policy is "
                                       "what every ALLOW/DENY in F4 had"),
    ("NoDeterminingPolicies", EX_POLICY, "named in the section's prose; the nopolicy gateway "
                                         "and the pre-permit cells produce this condition"),
    ("TemporalLatency", EX_POLICY, "named in the section's prose; every request carries the "
                                   "temporal policy-session header"),
)

GUARDRAIL_METRICS = (
    ("Invocations", EX_GUARDRAIL, "every ApplyGuardrail call"),
    ("InvocationLatency", EX_GUARDRAIL, "every ApplyGuardrail call"),
    ("InvocationsIntervened", EX_GUARDRAIL, "the F3 corpora are built to be intervened on"),
    ("TextUnitCount", EX_GUARDRAIL, "billing is per text unit, so every call has one"),
    ("InvocationClientErrors", EX_NONE,
     "requires a client-side error against ApplyGuardrail. The project's calls were built to "
     "succeed, and manufacturing failures would change what the corpora measure"),
    ("InvocationServerErrors", EX_NONE,
     "requires a 5xx from the ApplyGuardrail service, which no client-side action can cause; "
     "an absence here would measure the impossibility of the test, not the document"),
    ("InvocationThrottles", EX_NONE,
     "requires exceeding the ApplyGuardrail quota — the same denial-of-service objection as "
     "the gateway's Throttles"),
)

# The counts DEV-P4-03 quotes, pinned here and checked at import.
#
# DEV-P4-03 is prose in a markdown file, and its argument turns on two numbers: how many
# documented metrics there are and how many are excluded. A number in a justification string is
# unchecked — edit a table above and the deviation entry silently starts describing a scope it
# no longer has. So the numbers live in data, are asserted below, and are asserted again from
# `lib/tests/test_f7_metric_tables.py` with mutation checks, which is what licenses the entry's
# sentence "the script asserts these counts at import time".
#
# `Invocations` appears in two namespaces and is a different metric in each, so the unit of
# count is the (namespace, metric) PAIR: 29 pairs across 28 distinct names.
DEV_P4_03_COUNTS = {
    "documented_pairs": 29,
    "distinct_names": 28,
    "excluded": 11,
    "scored": 18,
    "per_case": {"F7-1": {"scored": 10, "documented": 15},
                 "F7-2": {"scored": 4, "documented": 7},
                 "F7-3": {"scored": 4, "documented": 7}},
}

CASE_METRIC_TABLE = {"F7-1": POLICY_METRICS, "F7-2": GATEWAY_METRICS,
                     "F7-3": GUARDRAIL_METRICS}


def metric_table_counts() -> dict[str, Any]:
    """Derive, never transcribe, the counts DEV-P4-03 rests on."""
    tables = (GATEWAY_METRICS, POLICY_METRICS, GUARDRAIL_METRICS)
    pairs = [(nm, basis) for t in tables for nm, basis, _ in t]
    excluded = [nm for nm, basis in pairs if basis == EX_NONE]
    per_case = {}
    for case, table in CASE_METRIC_TABLE.items():
        per_case[case] = {"documented": len(table),
                          "scored": sum(1 for _, b, _ in table if b != EX_NONE)}
    return {"documented_pairs": len(pairs),
            "distinct_names": len({nm for nm, _ in pairs}),
            "excluded": len(excluded), "scored": len(pairs) - len(excluded),
            "per_case": per_case, "excluded_names": excluded}


def assert_dev_p4_03_counts() -> None:
    """Fail loudly if a table edit moved a number DEV-P4-03 quotes.

    A plain `assert` would vanish under `python -O`, and this check exists precisely to run in
    the same interpreter that produces the verdicts, so it raises explicitly.
    """
    got = metric_table_counts()
    for key, want in DEV_P4_03_COUNTS.items():
        if got[key] != want:
            raise ConfigError(
                f"metric table drift: {key} is {got[key]!r} but DEV-P4-03 in DEVIATIONS.md "
                f"states {want!r}. Either the tables changed or the deviation entry is now "
                f"wrong; both must be fixed together, because the entry's scope IS these "
                f"numbers")
    for nm, basis, why in (GATEWAY_METRICS + POLICY_METRICS + GUARDRAIL_METRICS):
        if basis == EX_NONE and len(why) < 40:
            raise ConfigError(
                f"{nm} is excluded from scoring with a {len(why)}-character reason. Every "
                f"exclusion must carry a stated rationale, since the exclusion list is the "
                f"whole content of DEV-P4-03")
        if basis not in (EX_FRESH, EX_POLICY, EX_GUARDRAIL, EX_NONE):
            raise ConfigError(f"{nm} names an unknown exercise basis {basis!r}")


# Documented dimension names, for the dimension claims. Checked against what list_metrics
# actually enumerates; a documented dimension the service does not publish is a document
# defect of the same kind as an absent metric, and is reported (not scored — the sealed
# oracles are about metrics).
DOC_DIMENSIONS = {
    NS_AGENTCORE: ("ToolName", "Category", "Filter", "Mode", "PolicyEnforcementMode"),
    NS_GUARDRAILS: ("Operation", "GuardrailArn", "GuardrailVersion", "GuardrailContentSource",
                    "GuardrailPolicyType"),
}

# Negative controls. Both are the DOCUMENT's own negative claims, used to prove the matcher
# can say "absent" at all.
CONTROL_ABSENT_NAME = "FirstByteLatency"
CONTROL_WRONG_NS = NS_BEDROCK

# What makes a metric in AWS/Bedrock a GUARDRAIL metric rather than a model-runtime metric.
#
# The first version of this control asked whether the seven documented guardrail metric NAMES
# were absent from `AWS/Bedrock`. It failed, and it deserved to: four of them —
# `Invocations`, `InvocationLatency`, `InvocationClientErrors`, `InvocationServerErrors` — are
# also the names of Bedrock's *model runtime* metrics, which live in `AWS/Bedrock` legitimately.
# The document says so itself, in the very sentence the control was built from: "not
# `AWS/Bedrock` — that namespace holds model runtime metrics". So the control was testing a
# claim the document never made (that these strings appear nowhere in `AWS/Bedrock`) instead of
# the one it did make (that the guardrail metrics are not there), and it turned F7-3 into an
# INCONCLUSIVE about our own matcher.
#
# The name is not the discriminator; the dimensions are. A guardrail metric is dimensioned by
# the guardrail it belongs to. So the control now asks whether ANY metric in `AWS/Bedrock`
# carries a guardrail dimension — which is falsifiable, is what the document claims, and still
# fails loudly if the namespaces are not actually separated. Registered as DEV-P4-05.
GUARDRAIL_DIMENSION_NAMES = ("GuardrailArn", "GuardrailId", "GuardrailVersion", "GuardrailName")

GUARDS = ("control_absent_name", "control_wrong_namespace", "exercise_basis_nonempty",
          "inventory_nonempty", "reads_are_complete", "scope_matches_inventory")


class ConfigError(RuntimeError):
    """The testbed or the reading is not in a state that can carry a verdict."""


assert_dev_p4_03_counts()       # runs on import, in the same interpreter as the verdicts


def _list_metrics(cw, store, namespace: str) -> dict[str, Any]:
    """Paginated ListMetrics for one namespace: names, dimension names, and dimension VALUES.

    The values matter as much as the names, and not for this case. F7-6 has to measure the lag
    from *our* request to *our* queryable datapoint, and this account holds six pre-existing
    READY gateways plus several harness runtimes that publish into the same namespace. A
    lag measured against a namespace-wide SEARCH would stop the clock on somebody else's
    datapoint landing in the same minute bucket — the same defect as reading the shared
    `aws/spans` log group without an ARN filter, and in the same direction: it makes the
    service look faster than it is. So the dimension values are captured here, where the
    inventory is already being paginated, and F7-6 reads them to build a query that can only
    match our own gateway.
    """
    names: dict[str, set[tuple[str, ...]]] = {}
    dim_values: dict[str, dict[str, set[str]]] = {}
    token, pages = None, 0
    while True:
        kw = {"Namespace": namespace}
        if token:
            kw["NextToken"] = token
        rec = capture(store, "list_metrics", cw, **kw)
        rec.raise_for_status()
        resp = rec.response or {}
        pages += 1
        for m in resp.get("Metrics") or []:
            nm = m["MetricName"]
            dims = tuple(sorted(d["Name"] for d in m.get("Dimensions") or []))
            names.setdefault(nm, set()).add(dims)
            for d in m.get("Dimensions") or []:
                dim_values.setdefault(nm, {}).setdefault(d["Name"], set()).add(d.get("Value", ""))
        token = resp.get("NextToken")
        if not token:
            break
        if pages > 50:                                  # pragma: no cover
            raise ConfigError(f"ListMetrics on {namespace} did not terminate in 50 pages")
    return {"namespace": namespace, "n_pages": pages,
            "names": {k: sorted(list(v) for v in sorted(vs)) for k, vs in sorted(names.items())},
            "dimension_names": sorted({d for vs in names.values() for dims in vs for d in dims}),
            "dimension_values": {k: {d: sorted(vs) for d, vs in sorted(v.items())}
                                 for k, v in sorted(dim_values.items())}}


def _one_search(cw, store, namespace: str, metric: str, *, scope: str,
                start: datetime, end: datetime, period: int) -> dict[str, Any]:
    """ONE GetMetricData call for ONE metric, and a completeness check that can fail.

    SEARCH rather than a dimensioned Metric query because a query whose Dimensions do not
    match EXACTLY returns empty — which would be an absence manufactured by our own guess at
    the dimensions. SEARCH matches every dimension combination the service publishes, so an
    empty series set is a statement about the service.

    ONE metric per call, and scoped, because of a defect this script had on its first live run
    and its first two published verdicts, both now retracted:

        22 SEARCH expressions went into a single GetMetricData call. CloudWatch caps how many
        time series one call may return, and `AWS/Bedrock-AgentCore` in this account is busy —
        154 series matched `Invocations` alone. The budget was exhausted, later expressions came
        back with zero series, and F7-1/F7-2 published FALSE naming `Latency`, `Duration`,
        `TargetExecutionTime`, `DenyDecisions`, `GuardrailLatency`, `DeterminingPolicies`,
        `NoDeterminingPolicies` and `LogOnlyMatches` as absent — every one of which was sitting
        in the ListMetrics inventory of the same run, which only lists metrics that reported
        data in the last two weeks. Two readings of the same namespace contradicted each other
        and the script preferred the broken one.

        The service had said so: every response carried
        `{"Code": "PartialData", "Value": "... one or more metrics have StatusCode 'Paginated'"}`.
        The old code collected that message into the payload as decoration and scored the read
        anyway. A tool that reports it could not answer must not be recorded as answering.

    So: one metric per call so each SEARCH gets the whole budget; a `scope` term so the match is
    restricted to our own resources — which is what F7-1's oracle says ("datapoints appear for
    OUR dimensions") and which the account-wide sweep was never doing; and `trusted=False` on
    any non-`Complete` StatusCode or any message, which the caller turns into a guard failure
    rather than a verdict.

    THE SCOPE TERM IS UNQUOTED, AND THAT IS NOT A DETAIL
    ---------------------------------------------------
    The first scoped run quoted it — `"grx-gw-..."` — and a quoted term in a SEARCH expression
    is an EXACT match against a whole dimension value, not a token match inside one. Measured
    on the live namespace, over the same 13-day window:

        metric                quoted            unquoted
        Latency               2 series,  21 dp  10 series, 144 dp
        Duration              0 series,   0 dp   8 series, 123 dp
        TargetExecutionTime   0 series,   0 dp   3 series,  51 dp
        Throttles             0 series,   0 dp   8 series, 123 dp

    `Latency` carries a `TargetResource` dimension whose value IS the bare gateway id, so the
    quoted form matched it. `Duration` does not: its only resource dimension is
    `Resource=arn:...:gateway/<id>`, where the id is a substring and never the whole value. So
    the quoted form reported four of the seven documented gateway metrics absent — a SECOND
    round of manufactured absences, from a different mechanism than the series budget, and
    again pointing at the document. The guardrail namespace failed the same way and worse: its
    only resource dimension is `GuardrailArn`, so ALL FOUR scored metrics read absent and F7-3
    published 0/4.

    Unquoted, the term is matched as a token and finds the id inside the ARN. Verified against
    the live API rather than reasoned about: bare token 1 series, quoted token 0 series, quoted
    full ARN 1 series, unscoped 16 series, for the same metric and window.
    """
    term = f" {scope}" if scope else ""
    q = {"Id": "q0",
         "Expression": (f'SEARCH(\'Namespace="{namespace}" MetricName="{metric}"{term}\', '
                        f"'Sum', {period})"),
         "ReturnData": True}
    results: list[dict] = []
    messages: list[dict] = []
    token, pages = None, 0
    while True:
        kw: dict[str, Any] = {"MetricDataQueries": [q], "StartTime": start, "EndTime": end,
                              "ScanBy": "TimestampDescending"}
        if token:
            kw["NextToken"] = token
        rec = capture(store, "get_metric_data", cw, **kw)
        rec.raise_for_status()
        resp = rec.response or {}
        results.extend(resp.get("MetricDataResults") or [])
        messages.extend(resp.get("Messages") or [])
        token = resp.get("NextToken")
        pages += 1
        if not token or pages > 20:
            break

    statuses = sorted({r.get("StatusCode", "") for r in results})
    per_series_msgs = sorted({json.dumps(m) for r in results for m in (r.get("Messages") or [])})
    top_msgs = sorted({json.dumps(m) for m in messages})
    trusted = (all(s == "Complete" for s in statuses) if statuses else True) \
        and not per_series_msgs and not top_msgs
    vals = [v for r in results for v in (r.get("Values") or [])]
    labels = sorted({r.get("Label", "") for r in results if r.get("Label")})
    return {
        "metric": metric, "scope": scope, "expression": q["Expression"], "n_pages": pages,
        "n_series": len(results), "n_datapoints": len(vals), "has_datapoints": bool(vals),
        "sum": sum(vals) if vals else None,
        "status_codes": statuses, "messages": top_msgs + per_series_msgs,
        "trusted": trusted,
        "why_untrusted": ("" if trusted else
                          "CloudWatch reported the result as incomplete (a non-Complete "
                          "StatusCode or a PartialData message), so neither presence nor "
                          "absence read from it is about the service"),
        "series_labels": labels[:40], "n_series_labels": len(labels),
    }


def _union_reads(metric: str, reads: list[dict[str, Any]],
                 scope: tuple[str, ...]) -> dict[str, Any]:
    """Combine one-term reads into the single reading a metric is scored on.

    A metric counts as published if ANY of our resources published it, so series and datapoints
    are summed. Trust is the opposite: it is a conjunction, because one untrusted term makes the
    union's absence unreliable even if the other terms answered cleanly.
    """
    if len(reads) == 1:
        r = dict(reads[0])
        r["per_term"] = {scope[0] if scope else "": {"n_series": r["n_series"],
                                                     "n_datapoints": r["n_datapoints"]}}
        return r
    return {
        "metric": metric, "scope": list(scope), "n_terms": len(reads),
        "expression": [r["expression"] for r in reads],
        "n_pages": sum(r["n_pages"] for r in reads),
        "n_series": sum(r["n_series"] for r in reads),
        "n_datapoints": sum(r["n_datapoints"] for r in reads),
        "has_datapoints": any(r["has_datapoints"] for r in reads),
        "sum": (sum(r["sum"] for r in reads if r["sum"] is not None)
                if any(r["sum"] is not None for r in reads) else None),
        "status_codes": sorted({s for r in reads for s in r["status_codes"]}),
        "messages": sorted({m for r in reads for m in r["messages"]}),
        "trusted": all(r["trusted"] for r in reads),
        "why_untrusted": next((r["why_untrusted"] for r in reads if not r["trusted"]), ""),
        "series_labels": sorted({x for r in reads for x in r["series_labels"]})[:40],
        "n_series_labels": sum(r["n_series_labels"] for r in reads),
        "per_term": {s: {"n_series": r["n_series"], "n_datapoints": r["n_datapoints"]}
                     for s, r in zip(scope, reads)},
        "why_union": ("a metric counts as published if ANY of our resources published it, so "
                      "series and datapoints are summed; trust is a conjunction, because one "
                      "untrusted term makes the union's absence unreliable"),
    }


def _search_datapoints(cw, store, namespace: str, metric_names: tuple[str, ...], *,
                       start: datetime, end: datetime, period: int, label: str,
                       scope: tuple[str, ...]) -> dict[str, Any]:
    """Per-metric scoped reads, plus an unscoped read kept as a secondary (unscored) reading.

    The scoped read decides; the unscoped one distinguishes "this metric does not publish for
    our resources" from "this metric does not publish for anyone", which are different findings
    and would otherwise be indistinguishable in the payload.

    `scope` is a TUPLE of terms and they are searched SEPARATELY, then unioned. SEARCH's
    free-text terms are ANDed, so putting two guardrail identifiers in one expression asks for
    a metric belonging to both and matches nothing — an absence of exactly the DEV-P4-04 kind.
    """
    out: dict[str, Any] = {"window": label, "namespace": namespace, "scope": list(scope),
                           "start": start.isoformat(), "end": end.isoformat(),
                           "period_s": period, "per_metric": {}, "unscoped": {},
                           "reads_per_call": 1,
                           "why_terms_are_separate_calls": (
                               "SEARCH terms are ANDed, so one expression cannot ask about two "
                               "resources; the union is taken over one call per term"),
                           "why_one_per_call": (
                               "22 SEARCH expressions in one call exhausted CloudWatch's "
                               "series budget and produced two retracted FALSE verdicts; see "
                               "_one_search")}
    for nm in metric_names:
        reads = [_one_search(cw, store, namespace, nm, scope=s,
                             start=start, end=end, period=period) for s in scope]
        out["per_metric"][nm] = _union_reads(nm, reads, scope)
        if scope:
            out["unscoped"][nm] = _one_search(cw, store, namespace, nm, scope="",
                                              start=start, end=end, period=period)
    out["all_reads_trusted"] = all(v["trusted"] for v in out["per_metric"].values())
    out["untrusted_metrics"] = sorted(k for k, v in out["per_metric"].items()
                                      if not v["trusted"])
    out["messages"] = sorted({m for v in out["per_metric"].values() for m in v["messages"]})
    return out


def _evidence_call_counts(since: datetime) -> dict[str, int]:
    """Count our own recorded calls, from the evidence tree — NOT from CloudWatch.

    This is the independent left-hand side that turns "no datapoints" into a document defect
    rather than a statement about our test plan. It is deliberately read off disk: a metric
    reading used to justify its own exercise basis would be circular.
    """
    root = ROOT / "evidence"
    counts = {"apply_guardrail": 0, "mcp_tools_call": 0, "invoke_guardrail_checks": 0}
    if not root.exists():
        return counts
    cutoff = since.timestamp()
    for p in root.rglob("*.json"):
        nm = p.name
        try:
            if p.stat().st_mtime < cutoff:
                continue
        except OSError:                                   # pragma: no cover
            continue
        if "apply_guardrail" in nm:
            counts["apply_guardrail"] += 1
        elif "invoke_guardrail_checks" in nm:
            counts["invoke_guardrail_checks"] += 1
        elif "tools-call" in nm or "tools_call" in nm:
            counts["mcp_tools_call"] += 1
    return counts


def _guardrail_scope(since: datetime) -> dict[str, Any]:
    """Every guardrail identifier the project's own recorded ApplyGuardrail calls name.

    Read from the recorded `apply_guardrail` params, because the traffic that should have
    produced these metrics is the project's own ApplyGuardrail traffic — most of it from earlier
    runs whose guardrails may since have been torn down. Scoping to the CURRENT run's guardrail
    would look for datapoints from traffic that never happened, and read as a document defect.

    ALL matching files are read, with no sampling cap. An earlier version read the 400 most
    recent of 8,692 and took the single most frequent identifier, which is a sample presented as
    a scope: it happened to find 2 identifiers and would have missed any guardrail whose traffic
    fell outside the most recent 400 records. The scope is the UNION of every identifier found,
    and each is searched separately, because SEARCH terms are ANDed and one expression cannot
    ask about two guardrails at once.
    """
    root = ROOT / "evidence"
    counts: dict[str, int] = {}
    files = []
    n_unparsable = 0
    if root.exists():
        files = [p for p in root.rglob("*apply_guardrail*.json")
                 if p.stat().st_mtime >= since.timestamp()]
    for p in files:
        try:
            gid = (json.loads(p.read_text()).get("params") or {}).get("guardrailIdentifier")
        except (OSError, ValueError, TypeError):
            n_unparsable += 1
            continue
        if gid:
            counts[gid] = counts.get(gid, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"scope": tuple(nm for nm, _ in ranked),
            "identifiers_seen": dict(ranked),
            "n_files_matching": len(files), "n_files_scanned": len(files),
            "n_files_unparsable": n_unparsable,
            "sample_cap": None, "cap_applied": False,
            "why_no_cap": ("every matching record is read. A capped scan would make the scope a "
                           "sample of our own traffic while the payload described it as the "
                           "scope, and a guardrail whose calls fell outside the sample would "
                           "have produced a manufactured absence of the DEV-P4-04 kind"),
            "why_from_evidence": ("the metrics that should exist come from the project's own "
                                 "ApplyGuardrail traffic, most of it from earlier runs; "
                                 "scoping to the current run's guardrail would search for "
                                 "datapoints from traffic that never happened")}


def _score(case: str, metrics: tuple, project: dict, fresh: dict, inventory: dict,
           basis_ok: dict[str, bool], scope: tuple[str, ...]) -> dict[str, Any]:
    """Per-metric readings plus the conjunction the case's verdict is taken on.

    THE EXERCISE BASIS GATES ONLY THE ABSENT DIRECTION
    -------------------------------------------------
    An exercise basis exists to stop "no datapoints" from being read as a document defect when
    the producing traffic never happened. It has nothing to say about a metric that DID publish:
    a datapoint is a datapoint, however it arose. The first version applied the basis to both
    directions and so threw away positive evidence — the first run recorded `MismatchErrors`,
    `TotalMismatchedPolicies` and `PolicyMismatch` as NOT_EXERCISED while their own rows said
    `published: true`. Under the corrected rule:

        published            -> scored TRUE, whatever the basis
        absent, exercised    -> scored FALSE  (a document defect)
        absent, unexercised  -> NOT_EXERCISED, excluded from the conjunction

    This is the rule DEV-P4-03 should have stated. Direction of the bias is unchanged and still
    towards the document: it can only move a metric from excluded to satisfied, never to absent.

    THE CROSS-INSTRUMENT CHECK
    -------------------------
    `scope_matched` compares the two instruments against each other per metric: if
    `ListMetrics` shows our scope token among a metric's published dimension VALUES but the
    scoped SEARCH returned ZERO SERIES, the search term failed to match and the read is about
    our matcher, not the service. Zero series and zero datapoints are different observations,
    and conflating them is what produced both rounds of retracted FALSEs:

        0 series               the SEARCH matched no metric at all -> matcher/scope failure
        >=1 series, 0 points   the metric exists and reported nothing in the window -> absence

    Both retractions in DEV-P4-04 would have been caught here, from data already in the payload.
    """
    dim_values = inventory.get("dimension_values") or {}
    rows = []
    for nm, basis, why in metrics:
        pm = project["per_metric"].get(nm, {})
        fm = fresh["per_metric"].get(nm, {}) if fresh else {}
        in_inv = nm in inventory["names"]
        published = bool(pm.get("has_datapoints") or fm.get("has_datapoints"))
        basis_exercised = basis != EX_NONE and basis_ok.get(basis, False)

        # Does the inventory say this metric publishes for the resource we scoped to?
        our_dims = sorted(f"{d}={v}" for d, vals in (dim_values.get(nm) or {}).items()
                          for v in vals if any(s and s in v for s in scope))
        n_series = (pm.get("n_series") or 0) + (fm.get("n_series") or 0)
        scope_matched = not (our_dims and n_series == 0)

        # Truncation, like the exercise basis, gates ONE direction. A read CloudWatch reports as
        # partial can be missing datapoints it should have returned; it cannot invent datapoints
        # it did return. So an untrusted read still proves publication and only ever undermines
        # an absence. `read_trusted` is recorded for every metric; only `absence_untrusted`
        # blocks a verdict.
        read_trusted = bool(pm.get("trusted", True)) and bool(fm.get("trusted", True))
        absence_untrusted = (not published) and (not read_trusted)

        rows.append({
            "metric": nm, "exercise_basis": basis, "why": why,
            "basis_exercised": basis_exercised,
            "read_trusted": read_trusted,
            "why_read_untrusted": (pm.get("why_untrusted") or fm.get("why_untrusted") or ""),
            "absence_rests_on_untrusted_read": absence_untrusted,
            # kept for the payload's readers: what the conjunction actually used
            "counted_in_conjunction": published or basis_exercised,
            "name_in_namespace_inventory": in_inv,
            "dimension_sets": inventory["names"].get(nm, []),
            "inventory_dimensions_carrying_our_scope": our_dims,
            "scope_matched": scope_matched,
            "project_window": {k: pm.get(k) for k in
                               ("has_datapoints", "n_series", "n_datapoints", "sum")},
            "fresh_window": {k: fm.get(k) for k in
                             ("has_datapoints", "n_series", "n_datapoints", "sum")},
            # Published = datapoints in EITHER window. The oracle asks whether the metric
            # publishes after traffic that should produce it, and project traffic is traffic.
            "published": published,
        })
    scored = [r for r in rows if r["counted_in_conjunction"]]
    absent = [r["metric"] for r in scored if not r["published"]]
    excluded = [{"metric": r["metric"], "reason": r["why"]}
                for r in rows if not r["counted_in_conjunction"]]
    unmatched = [r["metric"] for r in rows if not r["scope_matched"]]
    untrusted_absences = [r["metric"] for r in rows if r["absence_rests_on_untrusted_read"]]
    return {"rows": rows, "n_documented": len(rows), "n_scored": len(scored),
            "n_published": sum(1 for r in scored if r["published"]),
            "absent": absent, "excluded_not_exercised": excluded,
            "scope_unmatched_metrics": unmatched,
            "scope_matches_inventory": not unmatched,
            "untrusted_metrics": [r["metric"] for r in rows if not r["read_trusted"]],
            "untrusted_absences": untrusted_absences,
            "absences_are_from_trusted_reads": not untrusted_absences,
            "all_scored_published": bool(scored) and not absent}


def main(argv: list[str] | None = None) -> int:                     # noqa: C901, PLR0915
    ap = P.parser(CASES[0], __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else PLANNED_N
    is_smoke = args.n is not None

    if args.dry_run:
        for case in CASES:
            P.dry_run_banner(
                case, [(ARM, "fresh gateway calls; CloudWatch read over two windows", n)],
                operations={"tools/call": n}, mutations=0, billable=False, text_units=0,
                text_units_why=("no ApplyGuardrail and no guardrail is created: F7-3 rests on "
                                "the project's already-spent guardrail traffic"),
                extra=[
                    "one script, three verdicts: the same two namespaces are inventoried once "
                    "and read once, so splitting the cases would mean three inventories taken "
                    "at three different times",
                    "three readings per metric: paginated ListMetrics (does the NAME exist, "
                    "and what dimensions does the service actually publish), GetMetricData "
                    "with a SEARCH expression over a 13-day PROJECT window, and the same "
                    "SEARCH over a FRESH window covering this script's own traffic",
                    "SEARCH rather than a dimensioned query: a Metric query whose Dimensions "
                    "do not match EXACTLY returns empty, which would be an absence "
                    "manufactured by our own guess at the dimensions",
                    "'traffic that should produce them' is established from OUR EVIDENCE TREE "
                    "(recorded ApplyGuardrail and tools/call counts), not from CloudWatch. A "
                    "metric reading used to justify its own exercise basis would be circular",
                    "DEVIATION, pre-committed: Throttles/SystemErrors/UserErrors and five "
                    "policy metrics are NOT_EXERCISED because inducing them means driving a "
                    "shared AWS service past its quota or shipping a deliberately broken "
                    "policy. F7-2's sealed oracle says 'FALSE for any absentee', so excluding "
                    "them DEVIATES from it — registered as DEV-P4-03. The bias favours the "
                    "document: exclusion makes TRUE more likely",
                    f"negative controls, both the DOCUMENT's own negative claims: "
                    f"{CONTROL_ABSENT_NAME!r} must be ABSENT from {NS_AGENTCORE} (the doc says "
                    f"it is not a valid name), and the 7 guardrail metrics must be absent from "
                    f"{CONTROL_WRONG_NS} (the doc says not that namespace). A sweep that finds "
                    f"everything is indistinguishable from a broken matcher",
                    "F7-1 decides DEV-P4-01's final scope, and the reading is pre-committed "
                    "both ways in the module docstring: either way a per-minute AGGREGATE "
                    "cannot restore the per-trial score harvest F2-2/F2-3/F2-4/F1-18 assumed",
                    f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}",
                ])
            print()
        return 0

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    cw = fc.client("cloudwatch")
    store = EvidenceStore(run_id, FAMILY, "F7-1_2_3")
    store.write_environment()

    now = datetime.now(timezone.utc).replace(microsecond=0)
    project_start = now - timedelta(days=PROJECT_WINDOW_DAYS)

    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    tool_name = ""
    if gw and tgt:
        tool_name = next((a for a in (tgt.ids.get("cedar_action_ids") or [])
                          if a.endswith(f"___{TOOL}")), "")

    common: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "windows": {
            "project": {"start": project_start.isoformat(), "end": now.isoformat(),
                        "days": PROJECT_WINDOW_DAYS, "period_s": PROJECT_PERIOD_S,
                        "why_13_days": ("CloudWatch's ListMetrics/SEARCH horizon is about two "
                                        "weeks, so a longer window would silently become a "
                                        "two-week window while claiming more")},
            "fresh": {"period_s": FRESH_PERIOD_S, "settle_s": FRESH_SETTLE_S,
                      "why_settle": ("publish lag is not assumed here; F7-6 is the case that "
                                     "measures it")},
        },
        "instrument": {
            "inventory": "paginated ListMetrics per namespace",
            "datapoints": "GetMetricData with one SEARCH expression per documented metric",
            "why_search": ("a dimensioned Metric query must match Dimensions exactly, so a "
                           "guessed dimension set produces an absence of our own making"),
            "horizon_caveat": ("both instruments surface only metrics that reported data in "
                               "roughly the last two weeks, so every reading here is about "
                               "the window and not about all time"),
        },
        "deviation": {
            "id": "DEV-P4-03",
            "what": ("metrics whose publishing condition is an error or a deliberately broken "
                     "policy are scored NOT_EXERCISED and excluded from the verdict"),
            "why": ("inducing Throttles means driving a shared AWS service past its quota, "
                    "which is a denial-of-service shaped action; SystemErrors cannot be "
                    "induced from a client at all; and UserErrors needs a 4xx that this "
                    "testbed does not produce, because F4-6 measured denials as HTTP 200"),
            "conflicts_with": ("F7-2's sealed oracle, which names seven metrics and says "
                               "'FALSE for any absentee'"),
            "bias_direction": ("towards TRUE, i.e. towards the document under test. Stated "
                               "because a deviation that makes the subject look better is the "
                               "one most worth labelling"),
        },
        "guard_names": list(GUARDS),
        "metric_table_counts": metric_table_counts(),
        "documented_metric_count_note": (
            "F7-1's case TITLE says 19 policy metrics; the sealed claim row in "
            "claims/triage.csv names 15 once the '/'-joined table cells are split into "
            "individual metrics (12 in the table plus the 3 the section's prose adds by hand: "
            "DeterminingPolicies, NoDeterminingPolicies, TemporalLatency). The sealed oracle is "
            "per-metric existence and deliberately does not compare counts, so this is recorded "
            "as amendment material rather than scored: the discrepancy is between the "
            "document's own table and our title, and 19 is not reachable from the table by any "
            "splitting rule we can state"),
    }

    # ---- exercise bases, from our own evidence tree -------------------------------
    counts = _evidence_call_counts(project_start)
    basis_ok = {
        EX_FRESH: False,        # set after the traffic arm
        EX_POLICY: counts["mcp_tools_call"] > 0,
        EX_GUARDRAIL: counts["apply_guardrail"] > 0,
    }
    common["exercise_bases"] = {
        "counted_from": "the project's own evidence tree (file names), not CloudWatch",
        "since": project_start.isoformat(),
        "counts": counts,
    }
    print(f"F7-1/2/3 — metric existence, run_id={run_id}, region={region}")
    print(f"  exercise bases from evidence: {counts}")

    # ---- fresh traffic -----------------------------------------------------------
    fresh_trials: list[dict] = []
    fresh_error = ""
    if tool_name and gw:
        try:
            client = M.client_for(gw.ids["gateway_url"], fc, store=store,
                                  policy_session_id=M.policy_session_id(run_id, ARM),
                                  session_timeout_s=int(gw.ids.get("session_timeout_s", 900)))
            client.initialize()
            for i in range(1, n + 1):
                client.refresh_if_stale()
                d = client.call_tool(tool_name, {"text": f"{TEXT} {i}"})
                fresh_trials.append({"i": i, "outcome": d.outcome,
                                     "request_id": d.request_id})
        except M.McpTransportError as exc:
            fresh_error = str(exc)
    else:
        fresh_error = "no gateway/main or no ___echo action id in the ledger"

    fresh_start = now
    fresh_real = [t for t in fresh_trials
                  if t["outcome"] in ("allowed", "policy_denied")]
    basis_ok[EX_FRESH] = len(fresh_real) > 0
    print(f"  fresh traffic: {len(fresh_real)}/{n} real responses"
          + (f"  ({fresh_error})" if fresh_error else ""))
    common["fresh_traffic"] = {"n_sent": len(fresh_trials), "n_real": len(fresh_real),
                               "error": fresh_error,
                               "outcomes": sorted({t["outcome"] for t in fresh_trials})}

    if basis_ok[EX_FRESH]:
        print(f"  settling {FRESH_SETTLE_S}s before the fresh-window read")
        time.sleep(FRESH_SETTLE_S)
    fresh_end = datetime.now(timezone.utc).replace(microsecond=0)

    # ---- SEARCH scope terms ------------------------------------------------------
    # WHY a scope term at all. The first run of this script issued 22 SEARCH expressions in one
    # GetMetricData call. `Invocations` alone matched 154 time series, the call exhausted
    # CloudWatch's per-call series budget, and the later expressions came back EMPTY with a
    # `PartialData` message — which this script recorded as decoration and scored as absence.
    # It published FALSE for eight metrics that its own ListMetrics inventory listed as present
    # in the same run. Those verdicts are retracted; see DEV-P4-04.
    #
    # The scope term also makes the read match what F7-1's sealed oracle actually says — "for
    # our dimensions". An unscoped SEARCH answers a different question (does ANYONE in this
    # account publish this metric), so it is still issued, but as a SECONDARY read that is
    # recorded and never scored.
    gid = (gw.ids.get("gateway_id") or "") if gw else ""
    scope_ac: tuple[str, ...] = (gid,) if gid else ()
    gr_scope = _guardrail_scope(project_start)
    scope_gr: tuple[str, ...] = tuple(gr_scope["scope"])
    common["search_scope"] = {
        "AWS/Bedrock-AgentCore": {
            "scope": list(scope_ac),
            "source": "the gateway id in the run ledger",
            "confirmed_in_inventory": "checked below against inventory_dimension_values",
        },
        "AWS/Bedrock/Guardrails": {**gr_scope, "scope": list(scope_gr)},
        "terms_are_unquoted": (
            "a QUOTED SEARCH term is an exact match against a whole dimension value, so it "
            "misses an id that appears inside an ARN. Quoting is what made the second run "
            "report Duration, TargetExecutionTime and all four guardrail metrics absent while "
            "the inventory listed them; see DEV-P4-04"),
        "why": ("one SEARCH per metric, each restricted to our own resource, because multiple "
                "SEARCH expressions in one GetMetricData call share a returned-series cap and "
                "silently return empty results past it"),
        "secondary_unscoped_read": ("recorded, never scored: it separates 'the service does not "
                                    "publish this for our resources' from 'nobody in this "
                                    "account publishes it'"),
    }
    print(f"  search scope: agentcore={list(scope_ac)} guardrails={list(scope_gr)}"
          f"  (from {gr_scope['n_files_scanned']} recorded apply_guardrail files, no cap)")
    if not scope_ac or not scope_gr:
        for case in CASES:
            rec = O.not_measured(case, (
                "no SEARCH scope term could be established "
                f"(agentcore={list(scope_ac)}, guardrails={list(scope_gr)}). An unscoped "
                "SEARCH is what produced the retracted FALSE verdicts, so this script refuses "
                "to fall back to one"))
            P.emit(case, rec, {**common, "scope_error": True}, store)
        print("  INCONCLUSIVE: no scope term; refusing the unscoped read that caused DEV-P4-04")
        return 2

    # ---- inventories and datapoint sweeps ----------------------------------------
    try:
        inv_ac = _list_metrics(cw, store, NS_AGENTCORE)
        inv_gr = _list_metrics(cw, store, NS_GUARDRAILS)
        inv_bd = _list_metrics(cw, store, CONTROL_WRONG_NS)

        gw_names = tuple(m[0] for m in GATEWAY_METRICS)
        pol_names = tuple(m[0] for m in POLICY_METRICS)
        gr_names = tuple(m[0] for m in GUARDRAIL_METRICS)

        proj_ac = _search_datapoints(
            cw, store, NS_AGENTCORE, tuple(dict.fromkeys(gw_names + pol_names)),
            start=project_start, end=now, period=PROJECT_PERIOD_S, label="project",
            scope=scope_ac)
        proj_gr = _search_datapoints(
            cw, store, NS_GUARDRAILS, gr_names,
            start=project_start, end=now, period=PROJECT_PERIOD_S, label="project",
            scope=scope_gr)
        if basis_ok[EX_FRESH]:
            fresh_ac = _search_datapoints(
                cw, store, NS_AGENTCORE, tuple(dict.fromkeys(gw_names + pol_names)),
                start=fresh_start, end=fresh_end, period=FRESH_PERIOD_S, label="fresh",
                scope=scope_ac)
        else:
            fresh_ac = {"per_metric": {}, "window": "fresh", "skipped":
                        "no fresh traffic reached the gateway"}
        fresh_gr = {"per_metric": {}, "window": "fresh", "skipped":
                    "this script sends no ApplyGuardrail, so there is no fresh guardrail "
                    "traffic to read; F7-3 rests on the project window"}
    except ConfigError as exc:
        for case in CASES:
            rec = O.not_measured(CASE if (CASE := case) else case,
                                 f"the CloudWatch read could not be trusted: {exc}")
            P.emit(case, rec, {**common, "config_error": str(exc)}, store)
        return 2

    # ---- negative controls -------------------------------------------------------
    control_absent = CONTROL_ABSENT_NAME not in inv_ac["names"]

    # The name collision is expected and is recorded, but it is NOT the control — see
    # GUARDRAIL_DIMENSION_NAMES and DEV-P4-05.
    gr_names_also_in_bedrock = sorted(set(gr_names) & set(inv_bd["names"]))
    guardrail_dimensioned_in_bedrock = sorted(
        {f"{nm}[{d}]" for nm, dims in (inv_bd.get("dimension_values") or {}).items()
         for d in dims if d in GUARDRAIL_DIMENSION_NAMES})
    control_wrong_ns = not guardrail_dimensioned_in_bedrock

    controls = {
        "control_absent_name": {
            "name": CONTROL_ABSENT_NAME, "namespace": NS_AGENTCORE,
            "absent_as_documented": control_absent,
            "reading": ("the document says FirstByteLatency is not a valid gateway metric "
                        "name. Its absence here is what makes every 'present' in this run "
                        "meaningful: a matcher that finds it would find anything"),
        },
        "control_wrong_namespace": {
            "namespace": CONTROL_WRONG_NS,
            "test": ("no metric in AWS/Bedrock carries a guardrail dimension "
                     f"({', '.join(GUARDRAIL_DIMENSION_NAMES)})"),
            "guardrail_dimensioned_metrics_found_there": guardrail_dimensioned_in_bedrock,
            "absent_as_documented": control_wrong_ns,
            "n_names_in_that_namespace": len(inv_bd["names"]),
            "dimension_names_in_that_namespace": inv_bd["dimension_names"],
            "name_collision_recorded_not_scored": {
                "documented_guardrail_names_also_present_in_AWS_Bedrock":
                    gr_names_also_in_bedrock,
                "reading": (
                    "these names exist in AWS/Bedrock as MODEL RUNTIME metrics, which is what "
                    "the document itself says that namespace holds. The collision is why the "
                    "document's warning is worth making, and it is why the name-based version "
                    "of this control was invalid — it tested a claim the document never made. "
                    "See DEV-P4-05"),
            },
            "reading": ("the document says the guardrail metrics live under "
                        "AWS/Bedrock/Guardrails and NOT under AWS/Bedrock. A guardrail-"
                        "dimensioned metric in AWS/Bedrock would refute that; a same-named "
                        "model-runtime metric does not"),
        },
    }
    print(f"  control {CONTROL_ABSENT_NAME} absent from {NS_AGENTCORE}: {control_absent}")
    print(f"  control no guardrail-dimensioned metric in {CONTROL_WRONG_NS}: {control_wrong_ns}"
          + (f" (found {guardrail_dimensioned_in_bedrock})"
             if guardrail_dimensioned_in_bedrock else ""))
    if gr_names_also_in_bedrock:
        print(f"    (recorded, not scored: names also in {CONTROL_WRONG_NS} as model-runtime "
              f"metrics: {gr_names_also_in_bedrock})")

    # ---- score each case ---------------------------------------------------------
    plan = {
        "F7-1": (POLICY_METRICS, proj_ac, fresh_ac, inv_ac, NS_AGENTCORE),
        "F7-2": (GATEWAY_METRICS, proj_ac, fresh_ac, inv_ac, NS_AGENTCORE),
        "F7-3": (GUARDRAIL_METRICS, proj_gr, fresh_gr, inv_gr, NS_GUARDRAILS),
    }
    rc = 0
    for case in CASES:
        metrics, proj, fresh, inv, ns = plan[case]
        scope = scope_gr if ns == NS_GUARDRAILS else scope_ac
        sc = _score(case, metrics, proj, fresh, inv, basis_ok, scope)

        all_reads_trusted = bool(proj.get("all_reads_trusted", False)) and (
            bool(fresh.get("all_reads_trusted", False)) if fresh.get("per_metric") else True)

        guards = {
            "control_absent_name": control_absent,
            # F7-3 is the only case whose sealed oracle contains a namespace claim, so the
            # wrong-namespace control gates it and is reported (not gating) for the others.
            "control_wrong_namespace": control_wrong_ns if case == "F7-3" else True,
            "exercise_basis_nonempty": sc["n_scored"] > 0,
            "inventory_nonempty": bool(inv["names"]),
            # This guard was declared in GUARDS from the start and printed in the dry-run
            # banner, but the first two runs never evaluated it — an advertised check that
            # does not run reads as a passing check. See DEV-P4-04. It gates only the ABSENT
            # direction, for the reason given in `_score`: run 3 failed it on a metric that
            # returned 200 datapoints, i.e. on a PRESENCE a partial read cannot fabricate.
            "reads_are_complete": sc["absences_are_from_trusted_reads"],
            "scope_matches_inventory": sc["scope_matches_inventory"],
        }
        gd = {
            "controls": controls,
            "exercise_basis_nonempty": {
                "n_documented": sc["n_documented"], "n_scored": sc["n_scored"],
                "basis_ok": basis_ok,
                "why": ("with no exercised metric, an absence would measure this project's "
                        "test plan rather than the document")},
            "inventory_nonempty": {"namespace": ns, "n_names": len(inv["names"]),
                                   "n_pages": inv["n_pages"]},
            "reads_are_complete": {
                "test": ("no metric scored ABSENT may rest on a read CloudWatch reported as "
                         "partial or paginated. Presence is not gated"),
                "untrusted_absences": sc["untrusted_absences"],
                "untrusted_metrics_any_direction": sc["untrusted_metrics"],
                "every_read_trusted": all_reads_trusted,
                "project_trusted": proj.get("all_reads_trusted"),
                "fresh_trusted": fresh.get("all_reads_trusted"),
                "untrusted_project_metrics": proj.get("untrusted_metrics", []),
                "untrusted_fresh_metrics": fresh.get("untrusted_metrics", []),
                "messages": proj.get("messages", []) + fresh.get("messages", []),
                "why": ("a read CloudWatch reports as partial or paginated may be MISSING "
                        "datapoints it should have returned; it cannot INVENT datapoints it did "
                        "return. So it undermines an absence and never a presence. The first run "
                        "scored a truncated read as absence and published two retracted FALSE "
                        "verdicts; run 3 then made the opposite error, refusing to score at all "
                        "because one metric with 200 datapoints came back Paginated "
                        "(DEV-P4-04)")},
            "scope_matches_inventory": {
                "scope": scope,
                "unmatched_metrics": sc["scope_unmatched_metrics"],
                "test": ("for every metric whose ListMetrics dimension VALUES contain our "
                         "scope token, the scoped SEARCH must return at least one series"),
                "why": ("zero series and zero datapoints are different observations. Zero "
                        "series against a metric the inventory says is published for our own "
                        "resource means the search term did not match — a fact about our "
                        "matcher. This is the cross-instrument check that both retractions in "
                        "DEV-P4-04 needed, computed from data already in the payload")},
        }

        dims_doc = DOC_DIMENSIONS.get(ns, ())
        dims_seen = set(inv["dimension_names"])
        dim_report = {
            "documented": list(dims_doc),
            "published_in_namespace": inv["dimension_names"],
            "documented_but_not_published": [d for d in dims_doc if d not in dims_seen],
            "note": ("reported, NOT scored: the sealed oracles for this family are about "
                     "metrics. A documented dimension the service does not publish is "
                     "amendment material of the same kind as an absent metric"),
        }

        payload: dict[str, Any] = {
            **common,
            "namespace": ns, "guards": guards, "guard_detail": gd,
            "per_metric": sc["rows"],
            "n_documented": sc["n_documented"], "n_scored": sc["n_scored"],
            "n_published": sc["n_published"],
            "absent_though_exercised": sc["absent"],
            "excluded_not_exercised": sc["excluded_not_exercised"],
            "dimensions": dim_report,
            "inventory_names": sorted(inv["names"]),
            "inventory_dimension_values": inv.get("dimension_values", {}),
            "project_window_read": proj,
            "fresh_window_read": fresh,
            "verdict_rule": (
                "TRUE iff every EXERCISED documented metric has datapoints in the project or "
                "fresh window, with the guards holding. NOT_EXERCISED metrics are listed, not "
                "silently dropped (DEV-P4-03)"),
        }

        failed = [k for k, v in guards.items() if not v]
        if failed:
            rec = O.not_measured(
                case, "guard(s) " + ", ".join(failed) + " did not hold, so a presence or "
                "absence reading from this sweep cannot carry a verdict",
                guards=guards, guard_detail=gd)
            payload["why_inconclusive"] = (
                "a negative control that fails means the matcher cannot say 'absent', so no "
                "positive in the run is informative; an empty exercise basis means an absence "
                "would measure our test plan rather than the document")
            P.emit(case, rec, payload, store)
            rc = 2
            continue

        o = P.obs_existence(
            case, sc["all_scored_published"], n=sc["n_scored"],
            n_documented=sc["n_documented"], n_published=sc["n_published"],
            absent=sc["absent"], namespace=ns,
            n_excluded=len(sc["excluded_not_exercised"]))
        rec = O.evaluate(o)

        if case == "F7-1":
            conf = {r["metric"]: r["published"] for r in sc["rows"]
                    if r["metric"] in ("ConfidenceScore", "ConfidenceThreshold")}
            payload["dev_p4_01_third_surface"] = {
                "confidence_metrics_published": conf,
                "reading": (
                    "ConfidenceScore/ConfidenceThreshold DO publish on the metrics surface, so "
                    "DEV-P4-01 must be narrowed to the two surfaces it measured (the "
                    "ApplyGuardrail response and the span path)"
                    if any(conf.values()) else
                    "neither confidence metric publishes, so DEV-P4-01 stands across all "
                    "three surfaces the document claims a score on"),
                "why_it_changes_nothing_for_the_harvest": (
                    "pre-committed in this module's docstring before the measurement: a "
                    "CloudWatch metric is a per-period aggregate over whatever dimensions it "
                    "carries, so even a fully published ConfidenceScore yields a per-minute "
                    "statistic and never a score attached to one identified trial. The "
                    "per-trial harvest F2-2/F2-3/F2-4/F1-18 pre-registered is not restored "
                    "either way"),
            }
        payload["verdict_reading"] = (
            f"{rec['verdict']} for the {sc['n_scored']} of {sc['n_documented']} documented "
            f"metrics whose publishing condition this project's traffic actually creates. It "
            f"is not a statement about the {len(sc['excluded_not_exercised'])} excluded ones, "
            f"which remain untested rather than confirmed")
        payload["what_true_does_not_prove"] = (
            "that the metrics are timely (F7-6), that their timestamps are on the documented "
            "grid (F7-7), that the documented dimensions all exist (reported above, not "
            "scored), or anything about the metrics excluded as NOT_EXERCISED")
        P.emit(case, rec, payload, store)
        print(f"  {case}: {rec['verdict']}  scored {sc['n_published']}/{sc['n_scored']}"
              f"  absent={sc['absent']}  excluded={len(sc['excluded_not_exercised'])}")
        if rec["verdict"] not in O.DECISIVE:
            rc = 2

    return rc


if __name__ == "__main__":
    sys.exit(main())
