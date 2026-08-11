#!/usr/bin/env python3
"""Phase 2 step 6: verify the testbed against the LIVE service, not against the ledger.

The ledger records what an API call returned at the moment it returned. This script re-reads
every resource from the service and asserts the properties later phases *depend on* — which is a
different question from "did creation succeed", and it is the question that matters, because the
gate in the plan's Phase 2 row is "gateway READY; span visible for our ARN" and a run that
proceeds on a stale ledger spends Phases 3-6 measuring a testbed it cannot describe.

Why this is a separate script rather than assertions inside 01-05
----------------------------------------------------------------
Each build script already asserts its own resource. What none of them can assert is the
*conjunction*, and the conjunction is where the interesting failures live:

* `05_target.py` verified the tool schema on both gateways. It could not verify that the gateway
  still points at the policy engine `03` created — because `UpdateGateway` may have run since,
  and F5-2's mutation does exactly that. This script is what a later phase runs to establish a
  clean baseline before mutating, and to prove restoration afterwards.
* `02_lambda.py` asserted the deployed `CodeSha256`. It could not assert that the target's
  `lambdaArn` still resolves to that function. A target pointing at a deleted-and-recreated
  Lambda would produce plausible tool responses from unknown code.
* Nothing yet has checked that the gateway execution role can *still* assume-and-invoke: `01`
  wrote the role, `02` added the resource policy, and F5-4b's mutation removes a statement from
  it. The baseline "both statements present" must be a measured fact with a timestamp, or the
  red-team arm has nothing to restore to.

So this is the idempotent, read-only, $0 predicate that Phase 3 and every later phase calls
first, and that Phase 5 calls again after each restore. `--json` prints a machine-readable
verdict so a phase script can gate on it without parsing prose.

What it deliberately does not do
--------------------------------
No mutation, no creation, no `--ensure`. A verifier that repaired what it found would destroy
the observation it exists to make: "the gateway is not pointing at our engine" is a finding
about F5-2's restore path, and a script that silently fixed it would report a clean testbed and
lose the fact. Every check returns a verdict; the script's exit code is the conjunction.

Cost: $0. Every call is a Get/List/Describe.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "infra"))

import awsclients as A                                            # noqa: E402
import cedar                                                       # noqa: E402
import testbed as T                                               # noqa: E402
from evidence import EvidenceStore, capture                        # noqa: E402
from testbed import State                                          # noqa: E402

import echo_handler                                                # noqa: E402

# The two statements §3.1 tells readers to put on the gateway execution role. F5-4b removes the
# second one, so "both present" must be an established baseline with a timestamp rather than an
# assumption carried from 01_iam.py's run.
REQUIRED_GW_ACTIONS = ("bedrock-agentcore:*", "bedrock:InvokeGuardrailChecks")


class Checks:
    """A list of (name, ok, detail) verdicts. Every check runs; none short-circuits.

    Not fail-fast, deliberately: the first failure is rarely the informative one. A run where
    the gateway lost its policy engine AND the target lost its schema is a different diagnosis
    from either alone, and a script that stopped at the first would report the shallower cause.
    """

    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, bool(ok), detail))
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(ok for _n, ok, _d in self.rows)

    def failures(self) -> list[tuple[str, bool, str]]:
        return [r for r in self.rows if not r[1]]

    def print(self) -> None:
        width = max((len(n) for n, _o, _d in self.rows), default=10)
        for name, ok, detail in self.rows:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {name:<{width}}  {detail}")

    def to_json(self) -> dict:
        return {"ok": self.ok,
                "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in self.rows],
                "n_pass": sum(1 for _n, o, _d in self.rows if o),
                "n_fail": sum(1 for _n, o, _d in self.rows if not o)}


def verify_iam(iam, state: State, c: Checks) -> None:
    """The gateway role exists, is assumable by the service, and carries BOTH statements."""
    rec = state.find("iam-role", "gw-exec")
    if not c.add("iam/gw-exec present in ledger", rec is not None):
        return
    try:
        live = iam.get_role(RoleName=rec.name)["Role"]
    except Exception as exc:                                       # noqa: BLE001
        c.add("iam/gw-exec exists", False, f"{type(exc).__name__}: {exc}")
        return
    c.add("iam/gw-exec exists", True, rec.name)

    trust = live.get("AssumeRolePolicyDocument") or {}
    # boto3 URL-decodes the trust policy into a dict; a string means an older shape.
    if isinstance(trust, str):
        trust = json.loads(trust)
    principals = []
    for st in trust.get("Statement") or []:
        p = (st.get("Principal") or {}).get("Service")
        principals.extend([p] if isinstance(p, str) else (p or []))
    c.add("iam/gw-exec trusts agentcore",
          any("bedrock-agentcore" in s for s in principals),
          f"service principals: {principals}")

    # The F5-4b baseline. Both statements, read from the live inline policies — not from
    # 01_iam.py's spec, which is what the role was *asked* to be.
    actions: set[str] = set()
    for pol in iam.list_role_policies(RoleName=rec.name).get("PolicyNames") or []:
        doc = iam.get_role_policy(RoleName=rec.name, PolicyName=pol)["PolicyDocument"]
        if isinstance(doc, str):
            doc = json.loads(doc)
        for st in doc.get("Statement") or []:
            a = st.get("Action")
            actions.update([a] if isinstance(a, str) else (a or []))
    for want in REQUIRED_GW_ACTIONS:
        c.add(f"iam/gw-exec has {want}", want in actions,
              "F5-4b's mutation target" if want.startswith("bedrock:") else "")


# Ledger resource kinds the tagging API was MEASURED not to index, each with the evidence and
# the channel that replaces the assertion. Both entries are structural, so an entry here does not
# weaken the coverage claim; it relocates it (see `verify_tag_coverage`).
#
# Anything NOT listed here is asserted against the tag sweep as a hard failure, so the default is
# "must be indexed" and each exemption costs a measurement.
TAG_INDEX_BLIND = {
    "iam-role": (
        "measured 2026-08-10 in us-east-1: `list_role_tags` returns all four project tags on all "
        "five of our roles, while `get_resources(ResourceTypeFilters=['iam:role'])` returns 0 rows "
        "ACCOUNT-WIDE — against 681 roles of which 102 carry at least one tag. The index is not "
        "empty of IAM either: filter `iam` returns 3 rows (2 instance-profiles, 1 oidc-provider), "
        "so the gap is `iam:role` specifically and not IAM as a service. Replacement channel: "
        "`get_role` + `list_role_tags` per role, below."),
    "policy": (
        "policies are structurally untaggable, which is stronger than 'not indexed'. "
        "`CreatePolicy`'s input shape has NO `tags` member (`clientToken`, `definition`, "
        "`description`, `enforcementMode`, `name`, `policyEngineId`, `validationMode`) while "
        "`CreatePolicyEngine` and `CreateGateway` both have one; and `TagResource` on a policy ARN "
        "returns AccessDeniedException for an AdministratorAccess principal while the SAME action "
        "succeeds on a gateway ARN in the same session. An AccessDenied an administrator cannot "
        "fix is 'type does not support tagging' wearing an authorization error's name. "
        "Replacement channel: `get_policy`, already asserted by verify_engine."),
}


def verify_tag_coverage(f, state: State, account_id: str, c: Checks) -> list[dict]:
    """Cross-check the ledger against the tag channel, **per type**. Returns the sweep rows.

    Why per type rather than one assertion
    --------------------------------------
    This check used to be a single "tag index covers the ledger", and on the first live run it
    failed — correctly as a *fact* (6 ledger resources absent from the sweep) and wrongly as a
    *verdict*. `06_verify.py` is the idempotent precondition every later phase runs first and that
    Phase 5 re-runs after each restore; a check that fails permanently, for a cause no action can
    change, teaches its reader to ignore rc=1 — and rc=1 is the same signal a genuine mid-phase
    drift will use. Blunting the real signal is a higher cost than the missing one.

    The two failure modes it has to separate are opposite:
      * **our code failed to tag something** — a bug, and the assertion must stay hard;
      * **the index does not cover the type** — a fact about AWS, where the assertion has to move
        to a channel that can see the resource, not be dropped.

    They cannot be told apart by the sweep alone, so they were separated by measurement and the
    answers are in `TAG_INDEX_BLIND`. `04_gateway.py` measures the same question for gateways in
    the other direction and prints its answer, which is what makes this a per-type property.

    The exemptions cost no strength: a blind type is verified on its own channel *and* its
    exemption's premise is re-tested here, so an entry cannot outlive its cause. If AWS starts
    indexing `iam:role`, the arm below notices and says so.
    """
    try:
        swept = T.sweep_by_tag(f, state.run_id)
    except Exception as exc:                                       # noqa: BLE001
        # A sweep that cannot run must not report clean (`feedback_guard_tool_exit_codes`).
        c.add("tag sweep ran", False, f"{type(exc).__name__}: {exc}")
        return []
    swept_arns = {r["arn"] for r in swept}

    missing_indexed, missing_blind = [], []
    for r in state.resources.values():
        if not r.arn:
            continue
        real = T.unmask_arn(r.arn, account_id)
        if real in swept_arns:
            continue
        (missing_blind if r.kind in TAG_INDEX_BLIND else missing_indexed).append(
            f"{r.kind}/{r.logical}")

    # The hard half. Gateways, targets, the Lambda and the policy engine are all measured to be
    # indexed, so absence here is real drift: something was created untagged, or deleted.
    c.add("tag index covers every ledger type it indexes", not missing_indexed,
          f"{len(swept)} tagged resources found for this run" if not missing_indexed
          else f"NOT indexed: {', '.join(missing_indexed)} — these types ARE covered by the "
               f"tagging API, so absence means the resource is untagged or gone, and the "
               f"teardown's primary channel cannot prove zero survivors for them")

    # The premise of each exemption, re-tested rather than trusted. An exemption whose cause has
    # gone away is an assertion silently switched off.
    for kind, why in sorted(TAG_INDEX_BLIND.items()):
        recs = [r for r in state.resources.values() if r.kind == kind and r.arn]
        if not recs:
            continue
        still_blind = any(T.unmask_arn(r.arn, account_id) not in swept_arns for r in recs)
        c.add(f"TAG_INDEX_BLIND[{kind}] premise still holds", still_blind,
              f"{len(recs)} {kind} resource(s) absent from the sweep, as measured" if still_blind
              else f"the tagging API now indexes {kind} — the exemption is obsolete and the hard "
                   f"assertion should be extended to it. {why}")

    # And the replacement channel for iam-role, which is where the assertion actually lives now.
    iam = f.iam()
    for r in [x for x in state.resources.values() if x.kind == "iam-role"]:
        try:
            got = {t["Key"]: t["Value"] for t in
                   iam.list_role_tags(RoleName=r.name).get("Tags") or []}
        except Exception as exc:                                   # noqa: BLE001
            c.add(f"iam-role/{r.logical} tags readable", False, f"{type(exc).__name__}: {exc}")
            continue
        want = A.tags_for(state.run_id, state.expires_at)
        # Equality on the project keys, not a subset check: a role tagged with another run's
        # RunId would be swept by a `--all-runs` teardown, and a wrong ExpiresAt would let one
        # outlive the 72 h TTL the isolation rule rests on.
        bad = {k: (want[k], got.get(k)) for k in want if got.get(k) != want[k]}
        c.add(f"iam-role/{r.logical} carries the project tags", not bad,
              "Project/Owner/RunId/ExpiresAt all match — the tag exists, only the INDEX is blind"
              if not bad else f"tag mismatch {bad}")
    return swept


def verify_lambda(lam, state: State, c: Checks) -> str:
    """The function is Active and running the code the ledger's hash names. Returns its ARN."""
    rec = state.find("lambda", "echo")
    if not c.add("lambda/echo present in ledger", rec is not None):
        return ""
    try:
        cfg = lam.get_function_configuration(FunctionName=rec.name)
    except Exception as exc:                                       # noqa: BLE001
        c.add("lambda/echo exists", False, f"{type(exc).__name__}: {exc}")
        return ""
    c.add("lambda/echo exists", True, rec.name)
    c.add("lambda/echo Active",
          cfg.get("State") == "Active" and cfg.get("LastUpdateStatus") in (None, "Successful"),
          f"State={cfg.get('State')} LastUpdateStatus={cfg.get('LastUpdateStatus')}")
    want = rec.ids.get("code_sha256_b64", "")
    live = cfg.get("CodeSha256", "")
    # The whole point of the deterministic zip. Phase 8's +7d/+30d re-runs call this script and
    # this line is what turns "the target was unchanged" from an assertion into a measurement.
    c.add("lambda/echo code unchanged", bool(want) and live == want,
          f"CodeSha256 {live[:16]}… vs ledger {want[:16]}…")
    return cfg.get("FunctionArn", "")


def verify_engine(ac, state: State, c: Checks) -> None:
    rec = state.find("policy-engine", "main")
    if not c.add("policy-engine/main present in ledger", rec is not None):
        return
    eid = rec.ids["policy_engine_id"]
    try:
        live = ac.get_policy_engine(policyEngineId=eid)
    except Exception as exc:                                       # noqa: BLE001
        c.add("policy-engine ACTIVE", False, f"{type(exc).__name__}: {exc}")
        return
    c.add("policy-engine ACTIVE", live.get("status") == "ACTIVE",
          f"{eid} status={live.get('status')}")

    pol = state.find("policy", "baseline")
    if not c.add("policy/baseline present in ledger", pol is not None):
        return
    try:
        lp = ac.get_policy(policyEngineId=eid, policyId=pol.ids["policy_id"])
    except Exception as exc:                                       # noqa: BLE001
        c.add("policy/baseline ACTIVE", False, f"{type(exc).__name__}: {exc}")
        return
    # An ENFORCE engine whose only permit is CREATE_FAILED denies everything by Cedar
    # default-deny, and every arm's benign control would fail for a reason no arm measures.
    c.add("policy/baseline ACTIVE", lp.get("status") == "ACTIVE",
          f"status={lp.get('status')} enforcementMode={lp.get('enforcementMode')}")
    stmt = (((lp.get("definition") or {}).get("cedar") or {}).get("statement") or "")
    c.add("policy/baseline statement unchanged", stmt.strip() == cedar.baseline_permit(),
          "verbatim from our §3.1" if stmt.strip() == cedar.baseline_permit()
          else f"live={stmt!r}")


def verify_gateways(ac, state: State, account_id: str, region: str, c: Checks) -> dict:
    """Both gateways READY, the pair still differing in one field, and `main` still pointing at
    our engine. Returns {logical: live config}."""
    live: dict[str, dict] = {}
    engine = state.find("policy-engine", "main")
    engine_id = engine.ids["policy_engine_id"] if engine else ""

    for logical in ("main", "nopolicy"):
        rec = state.find("gateway", logical)
        if not c.add(f"gateway/{logical} present in ledger", rec is not None):
            continue
        gid = rec.ids["gateway_id"]
        try:
            got = ac.get_gateway(gatewayIdentifier=gid)
        except Exception as exc:                                   # noqa: BLE001
            c.add(f"gateway/{logical} READY", False, f"{type(exc).__name__}: {exc}")
            continue
        live[logical] = got
        c.add(f"gateway/{logical} READY", got.get("status") == "READY",
              f"{gid} status={got.get('status')}")
        # The URL is not derivable and appears in no list operation, so a drift between the
        # ledger's copy and the live one would send every tool call somewhere unrecorded.
        c.add(f"gateway/{logical} url matches ledger",
              got.get("gatewayUrl", "") == rec.ids.get("gateway_url", ""),
              "" if got.get("gatewayUrl") == rec.ids.get("gateway_url")
              else "the ledger's gatewayUrl is stale; later phases would call the wrong host")

        pec = got.get("policyEngineConfiguration") or {}
        if logical == "main":
            want_arn = T.policy_engine_arn(region, account_id, engine_id) if engine_id else ""
            # This is the F5-2 baseline AND its restore assertion. `mode` is intentionally not
            # pinned here: F4 legitimately drives it to LOG_ONLY, so pinning it would make this
            # verifier fail during a phase that is working correctly. The ARN is pinned, because
            # nothing in the plan legitimately re-points the gateway at a different engine.
            c.add("gateway/main -> our policy engine", pec.get("arn") == want_arn,
                  f"mode={pec.get('mode')} arn={'ours' if pec.get('arn') == want_arn else pec.get('arn')}")
        else:
            # F6's paired baseline. If a mutation ever attached an engine here, every paired
            # difference would understate the policy hop cost by the amount of that engine.
            c.add("gateway/nopolicy has NO engine", not pec,
                  "" if not pec else f"unexpected policyEngineConfiguration: {pec}")

    if len(live) == 2:
        # Re-run 04's assertion against the live configs, because the pairing is a property of
        # the pair *now*, not of the pair as created — UpdateGateway has run since, twice, by
        # the time Phase 6 starts.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_gw04", Path(__file__).resolve().parent / "04_gateway.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # The ignore list comes from `04_gateway.PAIR_IGNORE`, not from a copy here. A copy is
        # what this file used to hold, and it is a latent contradiction: whichever list is
        # updated first, the other keeps asserting on the field, and the verifier then
        # "disagrees" with the script that just created the pair.
        #
        # The one ignored field justified by service behaviour is re-checked here rather than
        # trusted from creation time, for the same reason the diff is: the property is about the
        # pair *now*. If it fails, the pairing verdict below would be reported on grounds that
        # no longer hold, so it is a check of its own.
        wid = mod.workload_identity_is_pure_identity(
            live, {lg: state.get("gateway", lg).ids["gateway_id"]
                   for lg in ("main", "nopolicy")})
        c.add("workloadIdentityDetails is identity only (PAIR_IGNORE justification)", not wid,
              "shared prefix, tail == gatewayId" if not wid else "; ".join(wid))
        diffs = mod.diff_configs(live["main"], live["nopolicy"], ignore=mod.PAIR_IGNORE)
        c.add("F6 pairing still valid", not diffs,
              "identical except policyEngineConfiguration" if not diffs
              else "; ".join(diffs))
    return live


def verify_targets(ac, state: State, fn_arn: str, c: Checks) -> None:
    for logical in ("main", "nopolicy"):
        rec = state.find("gateway-target", logical)
        if not c.add(f"target/{logical} present in ledger", rec is not None):
            continue
        gid, tid = rec.ids["gateway_id"], rec.ids["target_id"]
        try:
            got = ac.get_gateway_target(gatewayIdentifier=gid, targetId=tid)
        except Exception as exc:                                   # noqa: BLE001
            c.add(f"target/{logical} READY", False, f"{type(exc).__name__}: {exc}")
            continue
        c.add(f"target/{logical} READY", got.get("status") == "READY",
              f"{tid} status={got.get('status')}")

        lam_cfg = (((got.get("targetConfiguration") or {}).get("mcp") or {})
                   .get("lambda") or {})
        live_arn = lam_cfg.get("lambdaArn", "")
        # A target pointing at a different function would return plausible tool responses from
        # unknown code — the failure mode 02_lambda.py's hash assertion cannot see, because it
        # only checks the function, not who points at it.
        c.add(f"target/{logical} -> our lambda",
              bool(fn_arn) and live_arn.split(":function:")[-1] == fn_arn.split(":function:")[-1],
              f"lambdaArn tail={live_arn.split(':function:')[-1] or '?'}")

        got_schema = (lam_cfg.get("toolSchema") or {}).get("inlinePayload")
        same = (got_schema is not None
                and json.dumps(got_schema, sort_keys=True)
                == json.dumps(echo_handler.TOOL_SCHEMA, sort_keys=True))
        c.add(f"target/{logical} schema unchanged", same,
              "" if same else "a drifted `amount` type makes every Cedar numeric arm take the "
                              "bad_request branch, which an arm reads as a policy deny")

        creds = got.get("credentialProviderConfigurations") or []
        types = [x.get("credentialProviderType") for x in creds]
        c.add(f"target/{logical} GATEWAY_IAM_ROLE", types == ["GATEWAY_IAM_ROLE"],
              f"{types} — F5-4b is only meaningful if the GATEWAY's role invokes the tool")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None)
    ap.add_argument("--json", action="store_true",
                    help="print the verdict as JSON so a phase script can gate on it")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the checks without calling AWS")
    args = ap.parse_args()

    if args.dry_run:
        print("Phase 2 step 6 — testbed verification (read-only, $0)")
        for name in ("iam/gw-exec exists + trusts agentcore + BOTH §3.1 statements",
                     "lambda/echo Active + CodeSha256 == ledger",
                     "policy-engine ACTIVE + baseline policy ACTIVE + statement verbatim",
                     "gateway/main READY + url matches ledger + points at OUR engine",
                     "gateway/nopolicy READY + has NO engine",
                     "F6 pairing still valid (live configs, not as-created)",
                     "targets READY + point at our lambda + schema unchanged + "
                     "GATEWAY_IAM_ROLE"):
            print(f"    - {name}")
        print("\nMutates nothing and repairs nothing: a repaired finding is a lost "
              "observation about F5-2's restore path.")
        print("\n--dry-run: no AWS call made.")
        return 0

    state = State.load(Path(args.state) if args.state else None)
    f = A.factory(args.region)
    account_id = f.sts().get_caller_identity()["Account"]

    store = EvidenceStore(state.run_id, "infra", "P2-06-verify")
    store.write_environment()

    c = Checks()
    print(f"Phase 2 step 6 — verifying testbed, run_id={state.run_id}, region={args.region}")
    verify_iam(f.iam(), state, c)
    fn_arn = verify_lambda(f.lambda_(), state, c)
    ac = f.agentcore_control()
    verify_engine(ac, state, c)
    verify_gateways(ac, state, account_id, args.region, c)
    verify_targets(ac, state, fn_arn, c)

    # The tag channel, cross-checked against the ledger — PER TYPE, because coverage is a
    # per-type property and this was measured, not assumed. See verify_tag_coverage.
    swept = verify_tag_coverage(f, state, account_id, c)

    c.print()
    verdict = c.to_json()
    verdict["run_id"] = state.run_id
    verdict["region"] = args.region
    verdict["n_tagged_resources"] = len(swept)
    store.write_summary(verdict)

    if args.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))

    if not c.ok:
        print(f"\n{len(c.failures())} check(s) FAILED. The testbed is not in the state the "
              f"ledger describes; running a phase against it would attribute this "
              f"discrepancy to whatever that phase measures.", file=sys.stderr)
        return 1
    print(f"\nall {verdict['n_pass']} checks passed — testbed matches the ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
