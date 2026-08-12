#!/usr/bin/env python3
"""F1-11 — does `UpdatePolicy` re-validate the STORED Cedar body?

UNPLANNED. This case did not exist in PREREGISTRATION.yaml. It was forced by a live failure
during F4's n=3 smoke on 2026-08-11, and the honest description of its status is: an unplanned
observation, recorded here with its full mechanism, NOT a pre-registered confirmatory result.
See DEVIATIONS.md. It is reported as a single counterexample plus its mutation, which is the one
shape that does not need a pre-registered n — a mechanism either reproduces or it does not.

WHAT HAPPENED

F4 drives the POLICY axis by calling `UpdatePolicy` with only `(policyEngineId, policyId,
enforcementMode)`. The Cedar body is deliberately NOT re-sent, and `f4_modes/01_truth_table.py`
argues at length that this avoids re-running validation on the baseline `permit` statement that
DC-1 (F1-3) showed fails validation. F4 even probes the claim first, against a sacrificial policy
it creates itself, and the probe PASSED: the body came back byte-identical and the policy stayed
ACTIVE.

Then the same call against the shared baseline policy produced:

    status = UPDATE_FAILED
    statusReasons = [
      "Overly Permissive: Policy Engine will allow every request for the specified principal
       (AgentCore::IamEntity), action (Any Future Tools) and resource (gateway/*) combination
       if the policy is added or updated",
      "Overly Permissive: ... (AgentCore::OAuthUser) ..."
    ]

Those are the SAME two findings DC-1 recorded at create time. So:

  1. `UpdatePolicy` re-validates the stored Cedar body even when the request carries no
     `definition` member at all. Omitting the body avoids REPLACING it; it does not avoid
     VALIDATING it.
  2. `UpdatePolicy` accepts a `validationMode` member (verified in the botocore 1.43.67 model:
     `UpdatePolicy:in` members are `['definition','description','enforcementMode',
     'policyEngineId','policyId','validationMode']`). The harness never sent it.

WHY F4'S PROBE COULD NOT HAVE CAUGHT THIS

The probe was sacrificial in the wrong dimension. It ran against F4's own guardrail policy, whose
statement is a narrowly-scoped `forbid` that PASSES validation cleanly. A probe for "does the
update re-validate?" run on a statement with no findings cannot fail: there is nothing for the
re-validation to reject. The hazard only manifests on a statement that carries findings, which is
precisely the statement the probe was built to protect. This is a design lesson worth more than
the finding: a sacrificial subject must be sacrificial IN THE PROPERTY UNDER TEST, not merely
disposable.

WHY IT MATTERS TO THE DOCUMENT

DC-1 said: a reader who follows our §3.1 checklist verbatim gets a CREATE_FAILED policy, because
the document never mentions `validationMode`. This finding extends it along the axis the document
actually recommends. §3.1 and §7.1 tell readers to deploy in LOG_ONLY, measure with shadow
evaluation, then switch to ACTIVE. That switch is an `UpdatePolicy`. So a reader who discovers
`validationMode` for themselves — from the AWS getting-started page, which does pass it — creates
the policy successfully and then still fails at the switch, with an error that names the same
finding they thought they had already dealt with. The document's central operational workflow has
a second, later failure point that neither the document nor (to our knowledge) the AWS
documentation states.

THE TEST

A three-step chain, which is also the repair. Step A is the claim, step B is the mutation that
proves `validationMode` was the load-bearing member and not an incidental change, step C restores.

  A. UpdatePolicy(enforcementMode=<unchanged>, validationMode=IGNORE_ALL_FINDINGS)
       -> predicted: status returns to ACTIVE
  B. UpdatePolicy(enforcementMode=<unchanged>)          # validationMode omitted, nothing else
       -> predicted: status returns to UPDATE_FAILED with the same two reasons
  C. repeat A                                            # leave the testbed ACTIVE

`enforcementMode` is held at whatever the policy already has in ALL THREE steps. The single
manipulated variable is the presence of `validationMode`. If B does not fail, the mechanism is
something else and this whole finding is withdrawn — which is why B is not optional.

B deliberately re-breaks the shared testbed. That is acceptable here and only here: A has just
demonstrated the repair, so the mutation is taken with a measured recovery in hand rather than a
hoped-for one. `--no-mutation` skips B for the case where this script is being used purely to
repair the testbed and no measurement is wanted.

EXIT CODES follow the repo convention: rc reports whether the test RAN, never whether the
document was right. rc=0 the chain completed and the testbed is verified back to ACTIVE; rc=2
nothing was measured or the testbed did not come back; rc=1 an unclassified outcome.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                              # noqa: E402
import testbed as T                                                 # noqa: E402
from evidence import EvidenceStore, capture                         # noqa: E402

FAMILY = "f1_config"
CASE = "F1-11"

IGNORE = "IGNORE_ALL_FINDINGS"
TERMINAL = ("ACTIVE", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED")
SETTLE_TIMEOUT_S = 120.0
SETTLE_SLEEP_S = 3.0

# The two findings DC-1 recorded at CREATE time, pinned as data rather than left in prose. The
# claim of this case is that the SAME findings reappear on an UPDATE, so "the same" has to be
# checkable rather than asserted. Matched on this substring, not on the full text: the sentence
# tail ("if the policy is added or updated") is service-authored and could be reworded without
# the finding changing.
DC1_FINDING_SUBSTR = "Overly Permissive"
DC1_PRINCIPALS = ("AgentCore::IamEntity", "AgentCore::OAuthUser")

VERIFY_MODULE_NAME = "grx_infra_06_verify"
_spec = importlib.util.spec_from_file_location(
    VERIFY_MODULE_NAME, ROOT / "infra" / "06_verify.py")
_vf = importlib.util.module_from_spec(_spec)
sys.modules[VERIFY_MODULE_NAME] = _vf
_spec.loader.exec_module(_vf)


def _status(ac, *, engine_id: str, policy_id: str) -> dict[str, Any]:
    """Raw GetPolicy — no evidence record. Poll loops are not evidence; the settled read is."""
    got = ac.get_policy(policyEngineId=engine_id, policyId=policy_id)
    got.pop("ResponseMetadata", None)
    return got


def _settle(ac, *, engine_id: str, policy_id: str,
            sleep=time.sleep) -> tuple[dict[str, Any], list[str]]:
    """Poll to a terminal status. Returns (last body, the status sequence observed).

    The sequence is kept, not just the final value. `UPDATING -> UPDATING -> UPDATE_FAILED` and
    an immediate `UPDATE_FAILED` are different facts about where the validation runs, and the
    difference is not recoverable from the endpoint alone.
    """
    deadline = time.monotonic() + SETTLE_TIMEOUT_S
    seen: list[str] = []
    while True:
        body = _status(ac, engine_id=engine_id, policy_id=policy_id)
        st = str(body.get("status") or "")
        seen.append(st)
        if st in TERMINAL:
            return body, seen
        if time.monotonic() + SETTLE_SLEEP_S >= deadline:
            return body, seen
        sleep(SETTLE_SLEEP_S)


def _reasons_match_dc1(reasons: list[str] | None) -> dict[str, Any]:
    """Are these the DC-1 findings, or merely some findings?

    A weaker check — "the update failed" — would be satisfied by a throttle, a transient service
    error or an unrelated validation rule, and the claim is specifically that the STORED
    statement's own findings are what re-fire. So the principals are matched too.
    """
    rs = list(reasons or [])
    joined = " || ".join(rs)
    return {
        "n_reasons": len(rs),
        "all_overly_permissive": bool(rs) and all(DC1_FINDING_SUBSTR in r for r in rs),
        "principals_present": [p for p in DC1_PRINCIPALS if p in joined],
        "matches_dc1": (bool(rs)
                        and all(DC1_FINDING_SUBSTR in r for r in rs)
                        and all(p in joined for p in DC1_PRINCIPALS)),
        "reasons": rs,
    }


def _step(ac, store: EvidenceStore, *, label: str, engine_id: str, policy_id: str,
          enforcement_mode: str, send_validation_mode: bool,
          sleep=time.sleep) -> dict[str, Any]:
    """One UpdatePolicy, then settle, then read the outcome. `definition` is never sent."""
    params: dict[str, Any] = {"policyEngineId": engine_id, "policyId": policy_id,
                              "enforcementMode": enforcement_mode}
    if send_validation_mode:
        params["validationMode"] = IGNORE

    A.limiter().wait("UpdatePolicy")
    rec = capture(store, "update_policy", ac, **params)
    out: dict[str, Any] = {
        "step": label,
        "sent_validation_mode": send_validation_mode,
        "sent_enforcement_mode": enforcement_mode,
        "sent_definition": False,
        "http_ok": rec.ok,
        "http_status": rec.http_status,
        "request_id": rec.request_id,
        "error_code": rec.error_code,
        "error_message": rec.error_message,
    }
    body, seen = _settle(ac, engine_id=engine_id, policy_id=policy_id, sleep=sleep)
    out["status_sequence"] = seen
    out["status"] = body.get("status")
    out["enforcement_mode_after"] = body.get("enforcementMode")
    out["updated_at"] = str(body.get("updatedAt") or "")
    out["statement_after"] = (((body.get("definition") or {}).get("cedar")
                              or (body.get("definition") or {}).get("policy") or {})
                             .get("statement") or "")
    out["definition_member_echoed"] = ",".join(sorted((body.get("definition") or {}).keys()))
    out["findings"] = _reasons_match_dc1(body.get("statusReasons"))
    out["settled_ok"] = out["status"] == "ACTIVE"
    return out


def _dry_run() -> int:
    print(f"{CASE} — does UpdatePolicy re-validate the STORED Cedar body?  (DRY RUN)")
    print()
    print("  status: UNPLANNED. Not in PREREGISTRATION.yaml. Forced by a live failure during")
    print("          F4's n=3 smoke on 2026-08-11. Reported as a single counterexample plus its")
    print("          mutation, which is the only shape that needs no pre-registered n.")
    print()
    print("  billable: False — control plane only, no model invocation, no text units.")
    print()
    print("  chain (enforcementMode held constant in all three steps; the ONLY manipulated")
    print("  variable is whether `validationMode` is present):")
    print(f"    A  UpdatePolicy(enforcementMode=<unchanged>, validationMode={IGNORE})")
    print("         predict: status -> ACTIVE   (this is also the repair)")
    print("    B  UpdatePolicy(enforcementMode=<unchanged>)          [MUTATION]")
    print("         predict: status -> UPDATE_FAILED with both DC-1 Overly Permissive findings")
    print("    C  repeat A                                            [restore]")
    print()
    print("  `definition` is NEVER sent in any step. That is the point: the claim is that the")
    print("  service validates a body the request did not carry.")
    print()
    print("  B is a deliberate re-break of the shared testbed, taken only because A has already")
    print("  demonstrated the repair in the same run. --no-mutation skips it.")
    print()
    print("  a NEGATIVE result withdraws the finding: if B leaves the policy ACTIVE, then")
    print("  something other than validationMode caused the original failure and this case")
    print("  reports no mechanism.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="F1-11 UpdatePolicy re-validation")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-mutation", action="store_true",
                    help="skip step B. Repairs the testbed but measures no mechanism.")
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--evidence-root", default=None)
    args = ap.parse_args(argv)

    if args.dry_run:
        return _dry_run()

    state = T.State.load(Path(args.state) if args.state else None)
    base = state.find("policy", "baseline")
    if base is None:
        print("FATAL: no policy/baseline in the ledger. Nothing to measure and nothing to "
              "repair.", file=sys.stderr)
        return 2
    engine_id = base.ids["policy_engine_id"]
    policy_id = base.ids["policy_id"]
    run_id = state.run_id

    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()
    ac = A.factory(args.region).agentcore_control()

    before = _status(ac, engine_id=engine_id, policy_id=policy_id)
    mode = str(before.get("enforcementMode") or "")
    print(f"{CASE} — UpdatePolicy re-validation, run_id={run_id} region={args.region}")
    print(f"  baseline policy {policy_id}")
    print(f"  measured before: status={before.get('status')!r} enforcementMode={mode!r}")
    print(f"  enforcementMode is HELD at {mode!r} in every step; the only manipulated "
          f"variable is validationMode")
    print()

    steps: list[dict[str, Any]] = []
    try:
        steps.append(_step(ac, store, label="A_with_validation_mode", engine_id=engine_id,
                           policy_id=policy_id, enforcement_mode=mode,
                           send_validation_mode=True))
        print(f"  A  validationMode={IGNORE}      -> status={steps[-1]['status']!r} "
              f"(polls: {'->'.join(steps[-1]['status_sequence'])})")

        if not args.no_mutation:
            if steps[-1]["status"] != "ACTIVE":
                print("  B  SKIPPED — A did not repair the policy, so the mutation would be "
                      "taken without a demonstrated recovery. That is not a risk this script "
                      "takes on a shared resource.", file=sys.stderr)
            else:
                steps.append(_step(ac, store, label="B_without_validation_mode",
                                   engine_id=engine_id, policy_id=policy_id,
                                   enforcement_mode=mode, send_validation_mode=False))
                print(f"  B  validationMode OMITTED         -> status={steps[-1]['status']!r} "
                      f"(polls: {'->'.join(steps[-1]['status_sequence'])}) "
                      f"matches_dc1={steps[-1]['findings']['matches_dc1']}")

                steps.append(_step(ac, store, label="C_restore", engine_id=engine_id,
                                   policy_id=policy_id, enforcement_mode=mode,
                                   send_validation_mode=True))
                print(f"  C  validationMode={IGNORE}      -> status={steps[-1]['status']!r} "
                      f"(polls: {'->'.join(steps[-1]['status_sequence'])})")
    finally:
        final = _status(ac, engine_id=engine_id, policy_id=policy_id)
        print()
        print("blocking assertion, re-run after the chain:")
        checks = _vf.Checks()
        _vf.verify_engine(ac, state, checks)
        _vf.verify_gateways(ac, state, A.account_id(A.factory(args.region)),
                            args.region, checks)
        verify_ok = bool(checks.ok)
        checks.print()

        by_label = {s["step"]: s for s in steps}
        a = by_label.get("A_with_validation_mode")
        b = by_label.get("B_without_validation_mode")
        payload = {
            "case_id": CASE,
            "status": "UNPLANNED — not in PREREGISTRATION.yaml; see DEVIATIONS.md",
            "instrument": "single_counterexample_with_mutation",
            "run_id": run_id,
            "region": args.region,
            "policy_engine_id": engine_id,
            "policy_id": policy_id,
            "enforcement_mode_held_at": mode,
            "definition_sent_in_any_step": False,
            "before": {"status": before.get("status"),
                       "enforcementMode": before.get("enforcementMode"),
                       "statusReasons": before.get("statusReasons")},
            "steps": steps,
            "final": {"status": final.get("status"),
                      "enforcementMode": final.get("enforcementMode"),
                      "statusReasons": final.get("statusReasons")},
            "verify_ok": verify_ok,
            "verify_checks": checks.to_json()["checks"],
            "reading": {
                "validation_mode_repairs": bool(a and a["status"] == "ACTIVE"),
                "omission_reproduces_failure": bool(b and b["status"] == "UPDATE_FAILED"),
                "reproduced_findings_are_dc1s": bool(b and b["findings"]["matches_dc1"]),
                "mechanism_confirmed": bool(
                    a and a["status"] == "ACTIVE"
                    and b and b["status"] == "UPDATE_FAILED"
                    and b["findings"]["matches_dc1"]),
                "mutation_taken": b is not None,
            },
            "not_a_verdict": (
                "This case was not pre-registered, so it does not carry a confirmatory verdict "
                "and no alpha is spent on it. What it establishes is a MECHANISM, reproduced "
                "in both directions within one run: adding `validationMode` repairs the policy "
                "and removing it re-breaks it, with the same two findings DC-1 recorded at "
                "create time. A mechanism shown to invert is a different kind of evidence from "
                "a rate estimate and needs no n — but it also cannot be reported as a "
                "pre-registered result, and is not."),
            "doc_consequence": (
                "Extends DC-1 along the axis the document recommends. §3.1/§7.1 tell readers to "
                "deploy in LOG_ONLY, measure, then switch to ACTIVE. That switch is an "
                "UpdatePolicy, and it re-validates the STORED statement, so it fails for the "
                "same reason the create did — even though the reader already solved the create. "
                "Neither the document nor, as far as we have found, the AWS documentation says "
                "`validationMode` is needed on updates as well as creates."),
        }
        out = store.write_summary(payload)
        print()
        print(f"wrote {out}")

    if not steps:
        print("FATAL: nothing was measured.", file=sys.stderr)
        return 2
    if not verify_ok:
        print("\nFATAL: the testbed did not verify back to a healthy state. Every later phase "
              "measures this policy engine.", file=sys.stderr)
        return 2
    if final.get("status") != "ACTIVE":
        print(f"\nFATAL: the baseline policy ended in {final.get('status')!r}, not ACTIVE.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
