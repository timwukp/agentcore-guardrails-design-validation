#!/usr/bin/env python3
"""F1-3: the statement our own document tells readers to write fails to create.

    python3 f1_config/03_permit_trap.py --dry-run
    python3 f1_config/03_permit_trap.py
    python3 f1_config/03_permit_trap.py --keep-engine   # skip teardown, for inspection

THE CLAIM UNDER TEST
--------------------
§3.1, §7.2 and §8 of the document under test all tell the reader to add

    permit(principal, action, resource is AgentCore::Gateway);

and none of the three mentions `validationMode`. The sealed oracle:

    TRUE if CreatePolicy with 'permit(principal, action, resource is AgentCore::Gateway);'
    and no validationMode reaches CREATE_FAILED with an Overly Permissive finding;
    FALSE if it reaches a usable state.

A TRUE verdict here means the document is wrong in the most consequential way a how-to
document can be wrong: a reader who follows it verbatim gets a policy that never enforces
anything, and — because CreatePolicy returns **HTTP 202 with a policyId** (measured; the
plan and an earlier draft of this file both assumed 200) — gets no error at the call site to
tell them so. The failure surfaces only in an asynchronously-settled `status` field they were
never told to read.

WHY A FRESH ENGINE, AND NOT THE PHASE-2 SIDE OBSERVATION
--------------------------------------------------------
Phase 2 already saw this once. Building the testbed, `infra/03_policy_engine.py` sent the
bare permit statement, watched it settle CREATE_FAILED, and recorded `dc1_reproduced: true`
in the ledger — then re-created the policy under `IGNORE_ALL_FINDINGS` to get a working
baseline. That is n=1 and it is **not** this result, for the reason that script's own
docstring gives:

    "That is F1-3 (Phase 3), the highest-value single test in the plan, and it must be run
     as a clean experiment against a fresh engine with the validation mode as its
     independent variable."

Three things make the Phase-2 sighting unusable as the finding. It was a side effect of
provisioning, so nothing was controlled. It has no comparison arm at all, so it cannot
distinguish "this statement is over-permissive" from "this engine rejects everything" — the
alternative explanation a paired design eliminates by construction. And the engine it ran
against now holds a live baseline policy, while the service's validator is documented to
reason about the policy SET: policy count on the engine is an uncontrolled variable, so a
second attempt there would not even be a repeat of the first.

THE DESIGN: ONE INDEPENDENT VARIABLE
------------------------------------
Four arms on ONE fresh engine, the same statement in every one but the control, differing
only in `validationMode`:

  A. `default`      — the parameter omitted entirely. This is the document's instruction
                      executed literally, and it is the arm the oracle is about. Omitted
                      rather than set to FAIL_ON_ANY_FINDINGS because "omitted" and
                      "explicitly defaulted" are different requests, and only the first is
                      what a reader following §3.1 produces.
  B. `failfind`     — `FAIL_ON_ANY_FINDINGS`, the documented default, stated. If A and B
                      agree, the service default is confirmed as fail-on-findings and the
                      document's silence is a documentation gap rather than a surprising
                      service behaviour — a distinction that changes how §3.1 is amended.
  C. `ignorefind`   — `IGNORE_ALL_FINDINGS`, what the AWS getting-started page passes for
                      this exact statement. **The mutation arm**: if C also fails, the cause
                      is not the finding gate, the reading collapses, and the remedy this
                      project would put in the document would be the wrong remedy.
  D. `narrow`       — a scoped statement (a concrete principal AND the real gateway) under
                      the SAME omitted-mode condition as A. **The control**: it is what makes
                      A's failure attributable to over-permissiveness rather than to the
                      engine, the account, the region or the day.

A → the claim. C → the mechanism. D → the control. B → the default's identity.

Only A and D are in the sealed verdict rule. C and B are in the AMENDMENT: the seal asks
whether arm A fails, and does not mark F1-3's mutation mandatory, so a non-inverting C cannot
change the verdict — and this script does not let it, because a harness that overrode its own
seal would be deciding its own question. What C and B gate is the remedy the amendment would
carry, and since `check_amendment_readiness.py` reads finding provenance blocks rather than
case payloads, that gate is written into the record as `local_amendment_blockers` rather than
asserted here in prose.

The control needs a real gateway ARN and this script REFUSES TO RUN without one. That is not
fastidiousness: `cedar.gateway_resource(None)` returns `resource is AgentCore::Gateway`, which
is the baseline. A missing ARN would silently turn the control into a second copy of the
treatment, both would fail, and the pair would read as "even the narrow policy is rejected" —
the exact wrong conclusion, reached by a design that looked complete.

WHAT COUNTS AS THE MEASUREMENT
------------------------------
Not the HTTP response. `CreatePolicy` returns **202 Accepted** and a policyId for a policy
that is already doomed; the verdict lives in the asynchronously-settled `status` plus `statusReasons`, polled
to terminal. That asymmetry IS the finding's operational sting, and it is why `wait_status`
is imported from `infra/03_policy_engine.py` rather than reimplemented — two definitions of
"terminal" would be two definitions of what CREATE_FAILED means, and this case's entire
verdict is a status read.

The oracle needs two things and both are checked separately: the arm reaches CREATE_FAILED,
**and** its reasons mention over-permissiveness. A CREATE_FAILED for an unrelated cause — a
malformed statement, a throttle, an engine that never became ACTIVE — would satisfy a naive
"did it fail" test while measuring nothing about the claim. `OVERLY_PERMISSIVE_TOKENS`
classifies the reasons, and an unclassified failure is INCONCLUSIVE with the reason text
recorded, not a TRUE.

WHAT THE ARM LABEL CANNOT BE READ BACK FROM
-------------------------------------------
Direction 4 of the F1 model sweep established that `validationMode` appears on exactly two
member paths in the whole API — `CreatePolicy:in` and `UpdatePolicy:in` — and is returned by
no operation: `GetPolicy`'s output shape carries `policyId, name, policyEngineId, createdAt,
updatedAt, policyArn, status, enforcementMode, definition, description, statusReasons` and
nothing else. So no response can confirm which mode an arm ran under; the label is carried by
the harness and by the request parameters recorded in the evidence store. That is a
provenance limitation of the API and it is recorded rather than papered over.

RUN ID: THIS JOINS PHASE 2'S LEDGER RATHER THAN STARTING ITS OWN
----------------------------------------------------------------
The run id and `ExpiresAt` are adopted from `state.json`, the way `infra/03_policy_engine.py`
does it, because one testbed must be one ledger: `State.load_or_new` raises on a run-id
mismatch precisely to stop two ids splitting the `RunId` tag across resources and leaving half
of them invisible to any single teardown sweep. Adopting the id costs nothing for the
replication rule — `07a_compare_runs.py` counts separate days from `t_start_utc` in the
records, not from the directory name, exactly as `new_run_id`'s docstring requires.

COST AND BLAST RADIUS
---------------------
Control-plane only: 1 CreatePolicyEngine, 4 CreatePolicy, GetPolicy polls, then up to 4
DeletePolicy and 1 DeletePolicyEngine. No text units, no model invocation, no gateway
mutated. Every resource is registered in `state.json` immediately on creation and tagged, so
a kill leaves an orphan both channels of `99_teardown.py` can find. Nothing pre-existing is
modified: the Phase-2 gateway ARN appears only inside a Cedar string, and the two abandoned
June-2026 engines — read-only evidence for this very case — are never named here.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A   # noqa: E402
import cedar as C        # noqa: E402
import oracle as O       # noqa: E402
import phase1 as P       # noqa: E402
import testbed as T      # noqa: E402
from evidence import EvidenceStore, capture  # noqa: E402

FAMILY = "f1"
CASE = "F1-3"

# `wait_status` and the terminal-status sets come from the provisioner rather than from a copy
# here. See the module docstring: one definition of "terminal", or the verdict is ambiguous.
_spec = importlib.util.spec_from_file_location(
    "_grx_policy_engine", ROOT / "infra" / "03_policy_engine.py")
_pe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pe)
wait_status = _pe.wait_status
TERMINAL_OK = _pe.TERMINAL_OK
TERMINAL_BAD = _pe.TERMINAL_BAD

# Substrings that make a creation failure attributable to over-permissiveness, matched
# case-insensitively against the joined statusReasons. A failure matching NONE of these is not
# evidence for this oracle however loudly it failed: DC-1's live sighting carried "Overly
# Permissive", and the sealed oracle names that finding specifically.
OVERLY_PERMISSIVE_TOKENS = ("overly permissive", "overlypermissive", "too permissive",
                            "permits all", "unconstrained", "overly broad")

# Slugs, not the arm keys, go into resource names: policy names must match
# `[A-Za-z][A-Za-z0-9_]*` with max 48 characters (DEV-P2-02 — no hyphens on this resource
# type), and `grx_f1_3_ignore_all_findings_<17-char run id>` would be 46 of the 48 with no
# headroom. Every name is validated against the model BEFORE the first create, so a length
# problem cannot surface after two arms have already run.
ARMS: tuple[dict[str, Any], ...] = (
    {"key": "default", "slug": "dflt", "mode": None, "statement": "baseline",
     "why": ("the document's instruction executed literally: the bare permit statement with "
             "no validationMode parameter at all. THIS is the arm the sealed oracle is "
             "about. The parameter is omitted rather than set to its documented default "
             "because an omitted parameter and an explicitly-defaulted one are different "
             "requests, and only the first is what a reader following §3.1 produces")},
    {"key": "failfind", "slug": "failfind", "mode": "FAIL_ON_ANY_FINDINGS",
     "statement": "baseline",
     "why": ("the documented default, stated explicitly. If this agrees with the omitted "
             "arm, the service default is confirmed to be fail-on-findings and the "
             "document's silence is a documentation gap rather than a surprising service "
             "behaviour — a distinction that changes how §3.1 should be amended")},
    {"key": "ignorefind", "slug": "ignfind", "mode": "IGNORE_ALL_FINDINGS",
     "statement": "baseline",
     "why": ("the MUTATION arm, and what the AWS getting-started page passes for this exact "
             "statement. If the finding gate is the cause of the failure, disabling it must "
             "let the identical statement through. If this arm ALSO fails, the cause is "
             "something else, the reading collapses, and 'add IGNORE_ALL_FINDINGS' would be "
             "the wrong remedy to write into the document — which is why it is run")},
    {"key": "narrow", "slug": "narrow", "mode": None, "statement": "narrow",
     "why": ("the CONTROL: a statement scoped to one principal and one gateway, under the "
             "same omitted-mode condition as the document's arm. It is what makes that arm's "
             "failure attributable to over-permissiveness rather than to this engine, this "
             "account, this region or this day. Without it, 'CreatePolicy failed' is equally "
             "consistent with an engine that refuses everything")},
)


def build_statements(gateway_arn: str, account_id: str, caller_role: str) -> dict[str, str]:
    """The two Cedar bodies, both from `lib/cedar.py` rather than typed here.

    `baseline_permit()` is DC-1 character-for-character; retyping it would make this case a
    test of a paraphrase. The narrow control is assembled from the same module's constructors
    so that if the harness's idea of a principal id or a resource reference is wrong, both
    arms are wrong the same way and the comparison survives — a shared error cancels in a
    paired design, while a hand-typed control would introduce an uncancelled one.

    Both arguments are required, with no `None` branch. `gateway_resource(None)` returns
    `resource is AgentCore::Gateway`, i.e. the baseline: a permissive fallback here would
    quietly replace the control with a copy of the treatment.
    """
    if not gateway_arn or not caller_role or not account_id:
        raise ValueError(
            "the narrow control needs a real gateway ARN, account id and caller role. "
            "cedar.gateway_resource(None) returns `resource is AgentCore::Gateway` — the "
            "BASELINE — so a fallback would make the control a second copy of the treatment, "
            "both arms would fail, and the pair would read as 'even the narrow policy is "
            "rejected'")
    return {
        "baseline": C.baseline_permit(),
        "narrow": C.statement("permit",
                              principal=C.principal_eq_role(account_id, caller_role),
                              resource=C.gateway_resource(gateway_arn)),
    }


def classify_failure(reasons: list[str]) -> dict[str, Any]:
    """Was this failure the one the oracle is about?

    A CREATE_FAILED whose reasons name a syntax error, an unknown entity type or a throttle
    would satisfy a bare "did it fail" check while measuring nothing about
    over-permissiveness. So the reasons are classified and an unmatched failure is reported
    unclassified rather than counted — the pattern the F1 mode-token scan uses for substring
    accidents. Being wrong loudly beats being right silently.
    """
    joined = " ".join(reasons).lower()
    hits = [t for t in OVERLY_PERMISSIVE_TOKENS if t in joined]
    return {"n_reasons": len(reasons), "reasons": reasons,
            "overly_permissive": bool(hits), "matched_tokens": hits,
            "classified_against": list(OVERLY_PERMISSIVE_TOKENS),
            "why_classified": (
                "the sealed oracle names an 'Overly Permissive finding', not any failure. A "
                "CREATE_FAILED for a syntax error or a throttle would pass a bare "
                "did-it-fail check while measuring nothing about the claim, so an unmatched "
                "failure is reported unclassified and forces INCONCLUSIVE")}


def _unclassified() -> dict[str, Any]:
    """The classification block for an arm that produced no terminal status to classify."""
    return {"n_reasons": 0, "reasons": [], "overly_permissive": False,
            "matched_tokens": [], "classified_against": list(OVERLY_PERMISSIVE_TOKENS)}


def plan_names(ac, run_id: str) -> dict[str, str]:
    """Every resource name, validated against the SDK's own pattern before the first create.

    All of them up front, deliberately. `check_name` raises locally instead of spending a
    live call, but a raise discovered at arm 3 would leave two policies and an engine already
    built and an experiment that can never be completed — so the length and grammar of the
    LAST name is checked before the FIRST call goes out.
    """
    names = {"__engine__": T.check_name(ac, "CreatePolicyEngine", f"grx_f1_3_pe_{run_id}")}
    for arm in ARMS:
        names[arm["key"]] = T.check_name(
            ac, "CreatePolicy", f"grx_f1_3_{arm['slug']}_{run_id}")
    return names


def run_arm(ac, store: EvidenceStore, state: T.State, *, engine_id: str,
            arm: dict[str, Any], statement: str, name: str, seq: int) -> dict[str, Any]:
    """Create one policy and poll it to terminal. Returns that arm's observation."""
    params: dict[str, Any] = {
        "name": name,
        "policyEngineId": engine_id,
        "definition": {"cedar": {"statement": statement}},
        "description": f"F1-3 arm {seq}/{len(ARMS)}: {arm['key']}",
    }
    if arm["mode"] is not None:
        params["validationMode"] = arm["mode"]

    print(f"  arm {seq}/{len(ARMS)}  {arm['key']:<11s} "
          f"validationMode={(arm['mode'] or '(omitted)'):<21s} {arm['statement']}")
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac, **params)

    out: dict[str, Any] = {
        "arm": arm["key"], "validation_mode": arm["mode"],
        "validation_mode_sent": arm["mode"] is not None,
        "statement_kind": arm["statement"], "statement": statement,
        "policy_name": name,
        "http_ok": rec.ok, "http_status": rec.http_status,
        "request_id": rec.request_id, "duration_ms": rec.duration_ms,
        "why_this_arm": arm["why"],
    }
    if not rec.ok:
        # A synchronous rejection is a different event from an asynchronous CREATE_FAILED: it
        # means no resource was created at all, so there is no status and nothing to classify.
        out.update(created=False, terminal_status=None, status_reasons=[],
                   reached_usable_state=False, create_failed=False,
                   error_code=rec.error_code, error_message=rec.error_message,
                   classification={**_unclassified(),
                                   "why_classified": "the call was rejected synchronously; "
                                                     "no policy exists, so there is no "
                                                     "status to classify"},
                   why_no_status=("CreatePolicy raised rather than being accepted. That is NOT "
                                  "the event the oracle is about — it is about reaching "
                                  "CREATE_FAILED, which requires having been created"))
        print(f"        synchronous rejection: {rec.error_code}: {rec.error_message}")
        return out

    pid = rec.response.get("policyId")
    out["policy_id"] = pid
    out["created"] = True
    # The status the HTTP response itself carried, kept beside the terminal one. The gap
    # between them is the finding's operational sting: a 202 Accepted plus a policyId for a
    # policy that is already doomed. Named `_at_accept` rather than `_at_http_200` because the
    # measured code is 202 and a field name that disagreed with its own value would be the
    # label-vs-computation defect this project screens for.
    out["status_at_accept"] = rec.response.get("status")
    out["enforcement_mode_at_accept"] = rec.response.get("enforcementMode")

    state.record(T.Resource(
        kind="policy", logical=f"f1_3_{arm['key']}", name=name,
        service="bedrock-agentcore-control",
        delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid,
             "validation_mode_sent": arm["mode"] or "(omitted)",
             "statement": statement},
        arn=rec.response.get("policyArn", ""),
        delete_priority=40,
        notes=(f"F1-3 arm {arm['key']}. Registered the moment CreatePolicy returned, before "
               f"its status was polled: a policy in CREATE_FAILED is still a resource, and a "
               f"kill during the poll would otherwise leave it untracked")))

    try:
        live = wait_status(ac.get_policy,
                           {"policyEngineId": engine_id, "policyId": pid})
    except TimeoutError as exc:
        out.update(terminal_status=None, status_reasons=[], timed_out=True,
                   reached_usable_state=False, create_failed=False,
                   timeout_detail=str(exc),
                   classification={**_unclassified(),
                                   "why_classified": "the status never settled, so there is "
                                                     "no terminal value to classify"})
        print("        status never became terminal")
        return out

    reasons = [str(r) for r in (live.get("statusReasons") or [])]
    out.update(terminal_status=live.get("status"), status_reasons=reasons, timed_out=False,
               classification=classify_failure(reasons),
               create_failed=live.get("status") == "CREATE_FAILED",
               reached_usable_state=live.get("status") in TERMINAL_OK,
               # Recorded, not tested here: `enforcementMode` is a second parameter §3.1
               # never mentions, and what the service defaults it to is F4's subject.
               enforcement_mode_settled=live.get("enforcementMode"))
    flag = "  [OVERLY PERMISSIVE]" if out["classification"]["overly_permissive"] else ""
    print(f"        HTTP {out['http_status']} status={out['status_at_accept']!r}"
          f"  ->  settled {out['terminal_status']}  reasons={len(reasons)}{flag}")
    for r in reasons:
        print(f"          - {r}")
    return out


def main(argv: list[str] | None = None) -> int:                          # noqa: C901
    ap = P.parser(CASE, __doc__)
    ap.add_argument("--keep-engine", action="store_true",
                    help="skip teardown of the fresh engine and its policies (inspection "
                         "only; both teardown channels still find them)")
    ap.add_argument("--state", default=None)
    ap.add_argument("--evidence-root", default=None,
                    help="write call records under this directory instead of evidence/. "
                         "For OFFLINE harnesses only: a fake client's records must not land "
                         "in the published tree, where check_amendment_readiness.py counts "
                         "them as observation days. capture() refuses that combination, so "
                         "this flag is how an offline run says where its records belong")
    args = ap.parse_args(argv)

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            [(a["key"], f"validationMode={a['mode'] or '(omitted)'} / {a['statement']}", 1)
             for a in ARMS],
            operations={"CreatePolicy": len(ARMS)},
            mutations=len(ARMS) + 1, billable=False,
            text_units=0,
            text_units_why=(
                "control-plane only. CreatePolicy and CreatePolicyEngine send no content "
                "through ApplyGuardrail or InvokeGuardrailChecks, so no text unit is billed; "
                "this case's cost is API calls, which are free"),
            extra=[
                f"the {len(ARMS)} CreatePolicy calls in the breakdown are the arms. Also "
                f"sent, and not arms: 1 CreatePolicyEngine, GetPolicyEngine + GetPolicy "
                f"polls until terminal (3s apart, 180s ceiling), then in the teardown "
                f"finally up to {len(ARMS)} DeletePolicy and 1 DeletePolicyEngine — 'up to', "
                f"because an arm rejected synchronously created nothing to delete",
                "a FRESH policy engine, created and deleted by this script. Phase 2's "
                "dc1_reproduced side observation (n=1, no comparison arm, on an engine that "
                "now holds a live baseline policy) is NOT reused as the result: "
                "infra/03_policy_engine.py's own docstring requires this case be run as a "
                "clean experiment with the validation mode as its independent variable",
                "ONE independent variable. A omits validationMode (the document's literal "
                "instruction), B states the documented default, C sets IGNORE_ALL_FINDINGS "
                "(the mutation), D narrows the statement to one principal and one gateway "
                "under A's condition (the control that makes A's failure attributable)",
                "the control REFUSES to run without a real gateway ARN: "
                "cedar.gateway_resource(None) returns `resource is AgentCore::Gateway`, the "
                "baseline, so a fallback would silently make the control a copy of the "
                "treatment and the pair would read as 'even the narrow policy is rejected'",
                "the measurement is the ASYNCHRONOUSLY-SETTLED status, not the HTTP "
                "response: CreatePolicy returns 202 Accepted and a policyId for a policy that is "
                "already doomed, and that asymmetry is the finding's operational sting",
                "a CREATE_FAILED counts only if its statusReasons mention "
                "over-permissiveness; an unclassified failure is INCONCLUSIVE, because a "
                "syntax error or a throttle would pass a bare did-it-fail check",
                "validationMode appears on exactly 2 member paths in the whole API "
                "(CreatePolicy:in, UpdatePolicy:in) and is returned by no operation, so the "
                "arm label cannot be read back from the service and is carried by the "
                "harness plus the recorded request parameters",
                "run id and ExpiresAt are ADOPTED from state.json rather than minted: one "
                "testbed must be one ledger, or the RunId tag splits and half the resources "
                "become invisible to any single teardown sweep. Replication days are counted "
                "from t_start_utc in the records, not from the directory name",
                "nothing pre-existing is modified. The Phase-2 gateway ARN appears only "
                "inside a Cedar string; the two abandoned June-2026 engines — read-only "
                "evidence for this very case — are never named",
            ])

    # ---- the ledger is a precondition, not a convenience -----------------------------
    try:
        state = T.State.load(Path(args.state) if args.state else None)
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        rec = O.not_measured(
            CASE,
            "state.json is absent, so there is no gateway ARN for the narrow control and no "
            "run id to tag with. The control cannot be built from a fallback: "
            "cedar.gateway_resource(None) returns the BASELINE statement, which would make "
            "the control a second copy of the treatment",
            state_path=str(Path(args.state) if args.state else T.STATE_PATH),
            remedy="run infra/01_iam.py onward (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: no ledger"}, None)
        return 2

    run_id = state.run_id
    if args.run_id and args.run_id != run_id:
        print(f"FATAL: --run-id {args.run_id!r} disagrees with the ledger's {run_id!r}. Two "
              f"run ids in one ledger split the RunId tag across resources and leave half of "
              f"them invisible to any single teardown sweep.", file=sys.stderr)
        return 2

    fac = A.factory(args.region)
    ac = fac.agentcore_control()
    account_id = fac.sts().get_caller_identity()["Account"]
    tags = A.tags_for(run_id, state.expires_at)
    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    print(f"{CASE} — the permit trap, run_id={run_id} (adopted from the ledger), "
          f"region={args.region}\n")

    gw_res = state.find("gateway", "main")
    role_res = state.find("iam-role", "caller")
    gw_arn = T.unmask_arn(gw_res.arn, account_id) if gw_res and gw_res.arn else ""
    caller_role = (role_res.ids or {}).get("role_name", "") if role_res else ""
    try:
        statements = build_statements(gw_arn, account_id, caller_role)
    except ValueError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        rec = O.not_measured(
            CASE, f"the narrow control could not be built: {exc}",
            have_gateway=bool(gw_arn), have_caller_role=bool(caller_role),
            remedy="run infra/01_iam.py and infra/04_gateway.py (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: no control"}, store)
        return 2

    problems = C.check_statement(statements["narrow"])
    if problems:
        rec = O.not_measured(
            CASE, f"the narrow control statement failed lib/cedar.py's own grammar check "
                  f"({problems}), so a CREATE_FAILED on it would be attributable to the "
                  f"harness rather than to the service",
            statement=statements["narrow"], problems=problems)
        P.emit(CASE, rec, {"instrument": "not built: malformed control"}, store)
        return 2

    common: dict[str, Any] = {
        "run_id": run_id, "region": args.region,
        "is_smoke": args.n is not None,
        "billable_calls": 0, "text_units": 0,
        "ambient_sdk": A.sdk_versions(),
        "instrument": (
            "paired CreatePolicy against a FRESH policy engine with validationMode as the "
            "only independent variable; each policy polled to a terminal status via "
            "infra/03_policy_engine.wait_status (3s interval, 180s ceiling)"),
        "why_fresh_engine": (
            "Phase 2 saw this once as a side effect of provisioning (dc1_reproduced, n=1) "
            "with no comparison arm, and that engine now holds a live baseline policy while "
            "the service's validator is documented to reason about the policy SET — so "
            "policy count there is an uncontrolled variable and a second attempt would not "
            "even be a repeat. infra/03_policy_engine.py's own docstring refuses the "
            "sighting as the result: 'it must be run as a clean experiment against a fresh "
            "engine with the validation mode as its independent variable'"),
        "why_the_status_not_the_response": (
            "CreatePolicy returns HTTP 202 Accepted and a policyId for a policy that is already "
            "doomed; the outcome settles asynchronously into `status` and `statusReasons`. A "
            "reader following the document gets no error at the call site, which is what "
            "makes this a documentation defect rather than an inconvenience"),
        "arm_label_provenance": (
            "carried by the harness and by the request parameters recorded in the evidence "
            "store, NOT read back from the service: validationMode is on exactly two member "
            "paths in the whole API (CreatePolicy:in, UpdatePolicy:in) and GetPolicy's output "
            "shape does not include it"),
        "statements": statements,
        "control_binding": {
            "gateway_arn_masked": gw_res.arn if gw_res else "",
            "caller_role": caller_role,
            "why_both_required": (
                "cedar.gateway_resource(None) returns `resource is AgentCore::Gateway` — the "
                "baseline. A permissive fallback would replace the control with a copy of "
                "the treatment, both arms would fail, and the pair would read as 'even the "
                "narrow policy is rejected': the wrong conclusion from a design that looked "
                "complete"),
        },
        "gateway_is_read_only_here": (
            "the Phase-2 gateway ARN appears only inside a Cedar resource reference. No "
            "UpdateGateway, no attach, no call through it: the live testbed is untouched"),
        "run_id_adopted": (
            f"from state.json ({run_id}), not minted. State.load_or_new raises on a mismatch "
            f"because two ids in one ledger split the RunId tag and leave half the resources "
            f"invisible to a single sweep. The replication rule is unaffected: "
            f"07a_compare_runs.py counts days from t_start_utc in the records"),
        "n_rationale": (
            "n=1 per arm, by design and not by budget. This is a deterministic control-plane "
            "validator outcome, not a rate; PREREGISTRATION.yaml binds no n for F1-3 "
            "(planned_n is None, family descriptive_no_test). Four arms of one call each is "
            "what a single-independent-variable design needs, and the replication "
            "requirement is a second DAY, not a larger n on one day"),
    }

    engine_id: str | None = None
    results: list[dict[str, Any]] = []
    try:
        names = plan_names(ac, run_id)
        print(f"creating fresh policy engine {names['__engine__']}")
        A.limiter().wait("CreatePolicyEngine")
        erec = capture(store, "create_policy_engine", ac, name=names["__engine__"],
                       description=f"F1-3 permit trap, run {run_id}", tags=tags)
        if not erec.ok:
            rec = O.not_measured(
                CASE,
                f"the fresh policy engine could not be created ({erec.error_code}: "
                f"{erec.error_message}), so no arm ran and the document's instruction was "
                f"never actually attempted",
                error={"code": erec.error_code, "message": erec.error_message,
                       "request_id": erec.request_id})
            P.emit(CASE, rec, {**common, "why_inconclusive": (
                "with no engine there is no experiment. Reporting the Phase-2 sighting "
                "instead would substitute an uncontrolled n=1 for the controlled design "
                "this case exists to run")}, store)
            return 2
        engine_id = erec.response["policyEngineId"]
        state.record(T.Resource(
            kind="policy-engine", logical="f1_3_trap", name=names["__engine__"],
            service="bedrock-agentcore-control",
            delete_op="delete_policy_engine",
            delete_params={"policyEngineId": engine_id},
            ids={"policy_engine_id": engine_id},
            arn=T.policy_engine_arn(args.region, account_id, engine_id),
            delete_priority=70,
            notes=("F1-3's fresh engine. Registered before its status was polled, so a kill "
                   "during the wait leaves a tracked resource rather than an orphan; it is "
                   "also tagged, which is the channel that finds it if this write loses the "
                   "race")))

        got = wait_status(ac.get_policy_engine, {"policyEngineId": engine_id})
        if got.get("status") not in TERMINAL_OK:
            rec = O.not_measured(
                CASE,
                f"the fresh policy engine settled {got.get('status')} rather than ACTIVE, so "
                f"a policy failure on it could not be attributed to the policy",
                engine_status=got.get("status"),
                engine_status_reasons=got.get("statusReasons"))
            P.emit(CASE, rec, {**common, "engine_id": engine_id}, store)
            return 2
        print(f"  engine {engine_id} ACTIVE\n")

        for seq, arm in enumerate(ARMS, 1):
            results.append(run_arm(ac, store, state, engine_id=engine_id, arm=arm,
                                   statement=statements[arm["statement"]],
                                   name=names[arm["key"]], seq=seq))

        by = {r["arm"]: r for r in results}
        a, b, c, d = (by["default"], by["failfind"], by["ignorefind"], by["narrow"])

        # ---- guards: each one means the instrument, not the document, is what this run
        # ---- actually learned about -----------------------------------------------------
        if not a.get("created"):
            rec = O.not_measured(
                CASE,
                f"the document's arm was rejected SYNCHRONOUSLY ({a.get('error_code')}: "
                f"{a.get('error_message')}), so it never reached a status at all. The oracle "
                f"is about reaching CREATE_FAILED, which is a different event from never "
                f"having been created",
                arm_default=a)
            P.emit(CASE, rec, {**common, "arms": results, "engine_id": engine_id}, store)
            return 2

        if a.get("timed_out"):
            rec = O.not_measured(
                CASE, "the document's arm never settled to a terminal status inside the 180s "
                      "poll window, so nothing was measured",
                arm_default=a)
            P.emit(CASE, rec, {**common, "arms": results, "engine_id": engine_id}, store)
            return 2

        if not d.get("reached_usable_state"):
            rec = O.not_measured(
                CASE,
                f"the NARROW CONTROL did not reach a usable state (created="
                f"{d.get('created')}, status={d.get('terminal_status')}, reasons="
                f"{d.get('status_reasons')}). Without a control that succeeds, a failure of "
                f"the document's arm is equally consistent with an engine, account or region "
                f"that refuses every policy — the alternative explanation this arm exists to "
                f"eliminate",
                arm_narrow=d, arm_default=a)
            P.emit(CASE, rec, {
                **common, "arms": results, "engine_id": engine_id,
                "why_inconclusive": (
                    "the control is not decoration. Publishing a TRUE without it would be "
                    "the DEV-P1 defect class: an observed absence attributed to the wrong "
                    "cause")}, store)
            return 2

        if a.get("create_failed") and not a["classification"]["overly_permissive"]:
            rec = O.not_measured(
                CASE,
                f"the document's arm reached CREATE_FAILED but its statusReasons do not "
                f"mention over-permissiveness: {a['status_reasons']}. The sealed oracle names "
                f"an Overly Permissive finding specifically, and a failure for another cause "
                f"is not evidence for it",
                arm_default=a, classification=a["classification"])
            P.emit(CASE, rec, {**common, "arms": results, "engine_id": engine_id}, store)
            return 1

        # ---- the verdict ---------------------------------------------------------------
        observed = bool(a.get("create_failed")
                        and a["classification"]["overly_permissive"])
        # "Inverted" is a claim about a PAIR: disabling the finding gate turned A's failure
        # into a success. If A did not fail there is no failure to invert, so the field is
        # None (not-applicable) rather than True — `bool(c.reached_usable_state)` alone would
        # report `inverted: True` for a run where every arm succeeded, which is a label that
        # does not match its own computation (feedback_label_must_match_computation). This
        # cannot change the published record: it differs from the old value only when arm A
        # succeeded, i.e. only when the verdict is FALSE and the document was right.
        mutation_inverted = bool(c.get("reached_usable_state")) if observed else None

        # The sealed oracle for F1-3 asks only about arm A, and `mutation_is_mandatory` is
        # False for this case — so a non-inverting mutation does NOT change the verdict, and
        # must not: overriding the seal from inside a case script is how a harness starts
        # deciding its own questions. But the REMEDY is a separate claim from the verdict, and
        # it is the remedy ("pass IGNORE_ALL_FINDINGS, or scope the statement") that would go
        # into v1.3. If arm C failed too, that remedy is unsupported by this run.
        #
        # `check_amendment_readiness.py` cannot catch it: it reads each FINDING's provenance
        # block and the replication days, never a case payload. So the blocker is written into
        # the record as data and printed loudly, rather than left as a sentence in a docstring
        # claiming an enforcement that does not exist (feedback_prose_is_not_verified).
        local_blockers: list[str] = []
        # `is False`, not `not ...`: None means arm A succeeded, so there was no failure for
        # the mutation to invert. Blocking a remedy in that case would be incoherent — a
        # FALSE verdict proposes no remedy to withdraw support from.
        if mutation_inverted is False:
            local_blockers.append(
                f"the mutation arm did not invert: IGNORE_ALL_FINDINGS settled "
                f"{c.get('terminal_status')} on the identical statement. The finding gate is "
                f"therefore NOT established as the cause, and the remedy 'pass "
                f"validationMode=IGNORE_ALL_FINDINGS' is unsupported by this run. The sealed "
                f"verdict is unaffected — the seal asks only about arm A and does not mark "
                f"the mutation mandatory for F1-3 — but no v1.3 amendment proposing that "
                f"remedy may cite this record")
        if b.get("terminal_status") != a.get("terminal_status"):
            local_blockers.append(
                f"the omitted-mode arm settled {a.get('terminal_status')} while explicit "
                f"FAIL_ON_ANY_FINDINGS settled {b.get('terminal_status')}. Omitting the "
                f"parameter is then NOT equivalent to passing its documented default, so the "
                f"amendment cannot be written as 'state the default': what the service does "
                f"on omission is a third behaviour and needs naming on its own")
        if local_blockers:
            print("\nAMENDMENT BLOCKERS (the verdict stands; the remedy does not):",
                  file=sys.stderr)
            for bl in local_blockers:
                print(f"  - {bl}", file=sys.stderr)
        o = P.obs_existence(
            CASE, observed,
            n=1,                        # see common["n_rationale"]
            arms=results,
            default_arm_create_failed=a.get("create_failed"),
            default_arm_overly_permissive=a["classification"]["overly_permissive"],
            default_arm_status_at_accept=a.get("status_at_accept"),
            documented_default_agrees=(b.get("terminal_status")
                                       == a.get("terminal_status")),
            mutation_arm_status=c.get("terminal_status"),
            control_arm_status=d.get("terminal_status"),
            engine_id=engine_id)
        o.mutation_inverted = mutation_inverted
        rec = O.evaluate(o)
        P.emit(CASE, rec, {
            **common,
            "engine_id": engine_id,
            "arms": results,
            "local_amendment_blockers": local_blockers,
            "local_amendment_blockers_why": (
                "conditions that leave the sealed VERDICT intact but withdraw support from "
                "the REMEDY a v1.3 amendment would carry. They live in the record because "
                "check_amendment_readiness.py reads FINDING provenance blocks and replication "
                "days, not case payloads — so a claim that the mutation 'gates the amendment' "
                "would otherwise be prose asserting an enforcement nothing performs"),
            "verdict_rule": (
                "TRUE iff the document's arm — validationMode omitted, bare permit statement "
                "— settles CREATE_FAILED with an over-permissiveness finding, WHILE the "
                "narrow control under the same condition reaches a usable state. The control "
                "is part of the rule and not a sanity check: without it the observation is "
                "equally consistent with an engine that refuses everything"),
            "mutation": {
                "arm": "ignorefind",
                "validation_mode": "IGNORE_ALL_FINDINGS",
                "status": c.get("terminal_status"),
                "inverted": mutation_inverted,
                "mandatory_per_seal": O.mutation_is_mandatory(CASE),
                "why_it_matters": (
                    "if disabling the finding gate lets the IDENTICAL statement through, the "
                    "gate is the cause of the failure — which is what makes 'pass "
                    "validationMode=IGNORE_ALL_FINDINGS, or scope the statement' a CORRECT "
                    "remedy to write into the document. Had this arm also failed, the "
                    "reading would have collapsed and the remedy would have been wrong. The "
                    "seal does not mark the mutation mandatory for F1-3, so it does not gate "
                    "the verdict — and it is not overridden here, because a harness that "
                    "overrode its own seal would be deciding its own question. What a "
                    "non-inverting mutation does instead is land in "
                    "`local_amendment_blockers`, withdrawing support from the remedy while "
                    "leaving the verdict where the seal put it"),
            },
            "default_mode_identity": {
                "omitted_status": a.get("terminal_status"),
                "fail_on_any_findings_status": b.get("terminal_status"),
                "agree": b.get("terminal_status") == a.get("terminal_status"),
                "reading": (
                    "if the two agree, the service default IS fail-on-findings and the "
                    "document's silence is a documentation gap rather than surprising "
                    "service behaviour. That distinction sets the amendment: state the "
                    "default and the remedy, rather than describe a trap"),
            },
            "enforcement_mode_observed": {
                "settled_values": {r["arm"]: r.get("enforcement_mode_settled")
                                   for r in results},
                "why_recorded_not_tested": (
                    "`enforcementMode` is a SECOND parameter §3.1 never mentions, and it "
                    "exists on CreatePolicy:in only from botocore 1.43.32 (F1-1). What the "
                    "service defaults it to is F4's subject, not this case's; recording it "
                    "here costs nothing and gives F4 a same-engine reference point"),
            },
            "what_true_means_for_the_document": (
                "§3.1, §7.2 and §8 all instruct the reader to add this statement and none "
                "mentions validationMode. A reader following the checklist verbatim gets a "
                "policy in CREATE_FAILED — and because CreatePolicy returns HTTP 202 with a "
                "policyId, nothing at the call site says so. ALL THREE sites must be "
                "amended: per feedback_grep_the_claim_not_the_phrasing, a claim corrected at "
                "one of three sites is not corrected, and claims.csv's sites[] list is the "
                "checklist"),
            "what_true_does_not_prove": (
                "that the statement is invalid Cedar, or that AWS is wrong to reject it. "
                "Rejecting an unconstrained permit is defensible service behaviour. The "
                "finding is about OUR document telling readers to send it without telling "
                "them what happens — the defect is documentary, and the amendment is to "
                "state the mode and the remedy"),
            "replication_required": (
                "the conflict-resolution protocol requires reproduction on >=2 separate UTC "
                "days before the document is amended. This is day 1 of that requirement; "
                "Phase 2's sighting does not count as a day because it was not this "
                "experiment"),
            "expiry": (
                "a service behaviour, not a model read: AWS could change the default "
                "validationMode or the validator's finding set at any time. If it does, that "
                "is an AWS-BEHAVIOR-CHANGES.md entry, not a correction to this record"),
        }, store)
        return 0

    finally:
        # Teardown in a finally, and every resource was registered in the ledger BEFORE its
        # status was polled — so a death here leaves an orphan that both teardown channels
        # find, rather than an invisible resource.
        if args.keep_engine:
            print("\n--keep-engine: the fresh engine and its policies are left in place. "
                  "They are tagged and in state.json, so 99_teardown.py will remove them.")
        elif engine_id:
            print("\nteardown")
            for r in results:
                pid = r.get("policy_id")
                if not pid:
                    continue
                A.limiter().wait("DeletePolicy")
                drec = capture(store, "delete_policy", ac,
                               policyEngineId=engine_id, policyId=pid)
                if drec.ok:
                    state.drop("policy", f"f1_3_{r['arm']}")
                    print(f"  deleted policy {r['arm']}")
                else:
                    print(f"  WARN policy {r['arm']} not deleted: {drec.error_code}; it is "
                          f"tagged and still in state.json")
            # DeletePolicy releases asynchronously, so the engine can still hold policies for
            # a few seconds after every delete was accepted. Retry rather than leave an engine
            # behind on a race that resolves itself.
            for attempt in range(1, 6):
                A.limiter().wait("DeletePolicyEngine")
                erec2 = capture(store, "delete_policy_engine", ac,
                                policyEngineId=engine_id)
                if erec2.ok:
                    state.drop("policy-engine", "f1_3_trap")
                    print(f"  deleted engine {engine_id}")
                    break
                print(f"  engine delete attempt {attempt}/5 failed "
                      f"({erec2.error_code}); retrying")
                time.sleep(3.0 * attempt)
            else:
                print("  WARN engine not deleted. It is tagged and in state.json, so both "
                      "teardown channels will find it.", file=sys.stderr)
        store.write_summary()


if __name__ == "__main__":
    sys.exit(main())
