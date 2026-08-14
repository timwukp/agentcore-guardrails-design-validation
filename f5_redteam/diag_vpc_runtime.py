#!/usr/bin/env python3
"""DIAGNOSTIC (not a registered case): can F5-7b's oracle be MEASURED, and with what instrument?

Why this exists
---------------
F5-7b is the last case in this project with no verdict that is neither untestable by its own seal
(F9-1) nor blocked on someone else's data pipeline (F10-1). Its sealed oracle is

    TRUE if a VPC-mode runtime without a NAT route fails IMAGE PULL and succeeds with one;
    FALSE if egress is reachable either way

and `mutation_is_mandatory("F5-7b")` is True, so both arms must actually run and the mutation must
be inverted and re-verified.

`results/DEPENDENCY-AUDIT-2026-08-13.md:103-125` recorded the blocker as an **arm64 container
build** on a t3.small/x86_64, and `f5_redteam/diag_runtime_code_artifact.py:28-32` narrowed it:
the `codeConfiguration` arm removed the container from F5-8's critical path, but *not* from
F5-7b's, because F5-7b's oracle is denominated in an image pull and **a code artifact pulls no
image**. Substituting the code arm here would be the F1-15 substitution defect exactly
(`results/FINDING-F1-15.md` §2): a one-word verdict silently answering a different question than
the seal asked. So the container stays.

What this diagnostic settles is whether the container has to be OURS. Read against the pinned
service model, `containerUri` is

    (([0-9]{12})\\.dkr\\.ecr\\.([a-z0-9-]+)\\.amazonaws\\.com(\\.cn)?|public\\.ecr\\.aws)/...

— the alternation admits **`public.ecr.aws`**. If AgentCore will pull a public multi-arch image,
then F5-7b needs no ECR repository, no Docker daemon, no arm64 cross-build and no `ecr:*` grant,
and the audit's blocker dissolves the same way the code arm dissolved F5-8's.

THE INSTRUMENT QUESTION, WHICH IS THE REAL ONE
----------------------------------------------
F5-7b's oracle asks about the PULL, so the instrument has to be able to say "the pull failed"
apart from "the pull succeeded and something later failed". A runtime that never reaches READY is
not automatically a runtime that never pulled. If `CREATE_FAILED` arrives with an opaque or
identical `failureReason` in both situations, then no VPC arrangement can answer this case and
F5-7b is INCONCLUSIVE for an instrument reason — which is a finding, and a cheap one.

So the two signatures this script needs are obtainable with **NO VPC AT ALL**, in `PUBLIC`
network mode where egress is not in question:

    arm `pull_ok_serve_bad`   a real public multi-arch image that pulls and then does NOT serve
                              AgentCore's contract (`/invocations` POST, `/ping` GET on :8080).
                              Expected: the pull succeeds and the runtime fails LATER.
    arm `pull_fails`          the same public repository at a tag that does not exist.
                              Expected: the pull itself fails.

If those two `failureReason` strings are DISTINGUISHABLE, F5-7b is measurable and this script has
handed its producer a reference signature for each half of the oracle, measured under full egress.
If they are not, F5-7b stops here and the reason is on the record.

Note what the second arm buys beyond viability: a pull failure caused by a MISSING IMAGE, obtained
with egress working. The producer's no-NAT arm must produce a pull failure caused by NO ROUTE. Two
different causes of the same class of failure, and a producer that cannot tell them apart would
report "pull failed" for a typo in a tag. That is the DEV-P4-22 shape — measuring a window the
mechanism under test never entered — and F1-15 has already paid for that lesson once.

    arm `vpc_shape`           `networkMode=VPC` with syntactically valid but nonexistent subnet
                              and security-group ids. This calls no VPC into existence and costs
                              nothing. A `ValidationException` about the ids being absent proves
                              VPC mode is live and validated server-side; a refusal of the MODE
                              would mean F5-7b is unconstructible, which is F1-15's answer and
                              would be reached here for a fraction of the cost of building a VPC.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It writes NO verdict and does not touch `results/phase1/`. It creates NO VPC, NO subnet, NO NAT
gateway and NO Elastic IP, so it needs no `ec2:*` grant beyond what the runner already has and it
cannot leak a billable network resource. Those belong to the producer, and the producer should not
be written until this script says it can succeed.

RESIDUE
-------
Every resource is created here and deleted here in a `finally`, and the report states what was
created and what was deleted so a reader can compare the two lists rather than trust a sentence.
Nothing is written to the ledger, for the reason `diag_runtime_code_artifact.py:56-63` gives: a
diagnostic that ledgered a failed probe would make it look like testbed the next teardown owns.
The cost is that a crash between create and delete leaks a runtime and a role, so every name
carries the run id and the report names them explicitly.

The execution role is `grx-runtime-vpcdiag-<run_id>` and NOT `grx-runtime-exec-<run_id>`: the
latter's inline policy set IS F5-1's published oracle, and the runner's own derived policy carries
an explicit Deny on `iam:PutRolePolicy` for `role/grx-runtime-exec-*` precisely so that this
mistake fails at the API rather than in a published verdict.

ROUND 1, MEASURED 2026-08-14 (`results/DIAG-vpc-runtime-20260814T092455Z.json`)
------------------------------------------------------------------------------
All three readings came back favourable, and the second came back on a channel this script had not
anticipated:

    pull_ok_serve_bad   READY after 10.1 s, `failureReason: ""`.
    pull_fails          NOT a CREATE_FAILED at all — `CreateAgentRuntime` refused SYNCHRONOUSLY:
                        `ValidationException: Public ECR resource not found for URI '...'.
                        Repository: 'nginx/nginx', Reference: 'grx-no-such-tag-f57b-diag'.`
                        Image EXISTENCE is validated by the control plane, on the control plane's
                        own network path, before any runtime is created.
    vpc_shape           CREATE_FAILED after 10.1 s, `The following subnets could not be found: ...`
                        VPC mode is live and validated asynchronously.

So the two halves of the oracle are not merely distinguishable, they arrive on **different
channels** — which is a better result than the script was built to hope for, and is what makes the
producer's typo-vs-no-route confusion (above) structurally impossible for a missing *image*.

THE WRONG LABEL, KEPT ON THE RECORD
-----------------------------------
Round 1's own derived reading said `f57b_is_measurable: false`. That was the SCRIPT's defect, not
the platform's. The predicate demanded a `failureReason` from each arm, which quietly assumed both
arms fail on the same channel; the synchronously-refused arm carries `error_message` instead, so an
absent field read as an absent signal and the most favourable measurement in the run was labelled
a dead end. Had the label been trusted, F5-7b would have been closed INCONCLUSIVE for an instrument
reason that did not exist.

What caught it was reading the per-arm record instead of the derived summary — the same discipline
that caught F1-15's false FALSE (`results/FINDING-F1-15.md` §6), and the second time in this project
that a *classifier* rather than a *measurement* was the thing that was wrong. `arm_signature()`
below is the fix at the general form: an arm's observable is read off whichever channel produced it,
and the comparison is channel-aware, so no future arm can fail into silence by succeeding at being
refused early.

THE TRAP THIS LEAVES FOR THE PRODUCER
-------------------------------------
READY arrived at the very FIRST poll — 10.1 s, i.e. exactly `POLL_SECONDS` — for the container arm
here and for F5-8's code arm alike. That is a strong hint that **READY does not mean the image has
been pulled**; the pull may be lazy or deferred to first invoke. A producer that scored F5-7b on
create-time status alone could therefore see its no-NAT arm reach READY and record "egress
reachable either way", which is the oracle's FALSE, on no evidence at all. So the producer must
measure create-time status AND an actual `InvokeAgentRuntime` on both arms.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import awsclients as A                                                # noqa: E402
import redact as R                                                    # noqa: E402
import testbed as T                                                   # noqa: E402
from evidence import EvidenceStore, capture                           # noqa: E402
from runtime_code_pkg import service_trust                            # noqa: E402

FAMILY = "f5_redteam"
LABEL = "DIAG-vpc-runtime"

# A multi-arch official image on the public registry. Chosen for three properties, in order of how
# much they matter: (1) it publishes a linux/arm64 manifest, which AgentCore requires; (2) it is
# large enough that a pull is a real network operation rather than a metadata read, so "the pull
# succeeded" is a claim with substance; (3) **it runs in the foreground and stays up**, while
# listening on :80 and never answering `/ping` on :8080 — so the runtime's failure lands on the
# health check, which is a step that cannot happen unless the image was fetched.
#
# Property 3 is why this is nginx and not `python:3.12-slim`, which an earlier draft of this file
# chose on the reasoning that "its entrypoint is a Python REPL, so it stays up". That is false
# without a TTY: `python3` with no arguments reads stdin, gets EOF immediately and exits 0. The
# container would DIE rather than fail a health check, and "the container exited" is a much weaker
# witness that a pull happened than "the container did not answer on :8080" — it is the confound
# this arm exists to avoid, and the first version of this comment walked into it while claiming to
# have avoided it.
PUBLIC_IMAGE = "public.ecr.aws/nginx/nginx:stable"

# The SAME repository at a tag that does not exist. Same registry, same repository, same
# credentials path, same network path — the ONLY difference from PUBLIC_IMAGE is that the manifest
# is absent. Holding the repository fixed is what makes this a control for the pull rather than a
# second experiment: if the two arms used different repositories, a difference in outcome could be
# a difference in repository permissions.
MISSING_TAG_IMAGE = "public.ecr.aws/nginx/nginx:grx-no-such-tag-f57b-diag"

# Syntactically valid ids for resources that do not exist. `subnet-` + 17 hex, `sg-` + 17 hex is
# the modern long-id form, so a rejection cannot be blamed on the id FORMAT.
FAKE_SUBNETS = ["subnet-0f57b0000000000aa", "subnet-0f57b0000000000bb"]
FAKE_SG = ["sg-0f57b0000000000cc"]

POLL_SECONDS = 10
POLL_TIMEOUT = 420
INTER_IAM_S = 2.0
TERMINAL = {"READY", "CREATE_FAILED", "UPDATE_FAILED"}

# Substrings that, if present in a `failureReason`, name the PULL as the failing step. Deliberately
# a list of candidates rather than one guess: this script does not know AgentCore's wording yet, and
# the whole point is to record it. `bucket_failure()` reports the raw string alongside its own
# label so that a wrong guess here is visible instead of decisive — the `body_head` lesson from
# `f1_config/diag_inference_body.py`.
PULL_MARKERS = ("pull", "image not found", "manifest", "not found", "unauthorized",
                "no such", "unable to retrieve", "registry", "denied")
# Substrings that name a step AFTER a successful pull. A container cannot be health-checked, fail
# to bind a port, or time out on `/ping` unless its image was fetched first.
POST_PULL_MARKERS = ("ping", "health", "8080", "port", "did not respond", "timed out",
                     "readiness", "container failed to start", "did not become healthy",
                     # A container that exited, or exited with a code, also ran — which also
                     # presupposes a fetched image. Kept even though PUBLIC_IMAGE is chosen NOT to
                     # exit, because the classifier should not depend on that choice holding.
                     "exited", "exit code", "crashloop", "restart")


def utcnow_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def bucket_failure(reason: str) -> tuple[str, str]:
    """Label a `failureReason` as pre-pull, post-pull, or unreadable — and say why.

    Returns `(label, why)`. The `why` is returned rather than logged because the caller writes it
    into the report next to the raw string: a label a reader cannot audit against the evidence
    that produced it is the defect that published a wrong F1-15 verdict.
    """
    if not reason:
        return "no_reason_given", "the service returned no failureReason at all"
    low = reason.lower()
    post = [m for m in POST_PULL_MARKERS if m in low]
    pre = [m for m in PULL_MARKERS if m in low]
    # Order matters. A post-pull marker is stronger evidence than a pull marker, because several
    # pull words ("not found", "denied") also appear in unrelated messages, whereas nothing
    # health-checks an image it did not fetch.
    if post:
        return "post_pull", f"names a step that presupposes a fetched image: {post}"
    if pre:
        return "pull", f"names the fetch itself: {pre}"
    return "unclassified", "matched no marker in either list — read the raw string"


def arm_signature(arm: dict) -> dict:
    """What an arm actually said, read off whichever channel it said it on.

    An arm can fail on two entirely separate channels: `CreateAgentRuntime` can refuse the call
    outright (an `error_code`/`error_message` pair, and no runtime ever exists), or the create can
    succeed and the runtime settle into a terminal `status` carrying a `failureReason`. Round 1
    measured one arm on each — see the module docstring — and the predicate that consumed these
    readings asked only for `failure_reason`, so the synchronously-refused arm registered as having
    said nothing and the run's most favourable result was labelled unmeasurable.

    Returning a `(channel, code, text)` triple rather than a string keeps that class of mistake out
    of every future comparison: a caller cannot accidentally compare two arms on a field only one of
    them populates, because the field it reads is chosen by the channel.
    """
    if arm.get("create_refused"):
        return {"channel": "create_refused",
                "code": str(arm.get("error_code") or ""),
                "text": str(arm.get("error_message") or "")}
    return {"channel": "terminal",
            "code": str(arm.get("terminal_status") or ""),
            "text": str(arm.get("failure_reason") or "")}


def make_role(iam, store, role_name: str, account: str, run_id: str, expires_at: str) -> str:
    """A minimal AgentCore Runtime execution role.

    No S3 read and no `bedrock:*`: this diagnostic's containers are pulled from a public registry
    and never invoked, so the role exists only to satisfy `CreateAgentRuntime`'s `roleArn` and to
    be assumable by the service. Granting it less is not austerity for its own sake — a role that
    can do nothing cannot make a `CREATE_FAILED` ambiguous by failing at something else.
    """
    rec = capture(store, "create_role", iam, RoleName=role_name,
                  AssumeRolePolicyDocument=json.dumps(service_trust(account)),
                  Description="GRX F5-7b diagnostic: VPC-mode runtime instrument probe",
                  Tags=[{"Key": k, "Value": v}
                        for k, v in A.tags_for(run_id, expires_at).items()]).raise_for_status()
    time.sleep(INTER_IAM_S)
    capture(store, "put_role_policy", iam, RoleName=role_name,
            PolicyName="grx-runtime-vpcdiag",
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Sid": "Logs", "Effect": "Allow",
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents",
                               "logs:DescribeLogStreams"],
                    "Resource": f"arn:aws:logs:*:{account}:log-group:/aws/bedrock-agentcore/*",
                }],
            })).raise_for_status()
    time.sleep(INTER_IAM_S)
    return rec.response["Role"]["Arn"]


def settle(ac, store, runtime_id: str) -> dict:
    """Poll one runtime to a terminal status and return what the service said about it."""
    t0 = time.monotonic()
    status, reason, err = "CREATING", "", ""
    while time.monotonic() - t0 < POLL_TIMEOUT:
        time.sleep(POLL_SECONDS)
        g = capture(store, "get_agent_runtime", ac, agentRuntimeId=runtime_id)
        if not g.ok:
            err = f"{g.error_code}: {g.error_message}"
            break
        status = (g.response or {}).get("status", "?")
        reason = (g.response or {}).get("failureReason", "") or reason
        if status in TERMINAL:
            break
    label, why = bucket_failure(reason)
    return {"terminal_status": status, "failure_reason": reason, "seconds": round(
        time.monotonic() - t0, 1), "step_label": label, "step_why": why, "poll_error": err}


def container_arm(ac, store, name: str, image: str, role_arn: str, run_id: str,
                  expires_at: str, network: dict) -> dict:
    """Create one container-artefact runtime, settle it, and delete it. Returns the reading."""
    out: dict = {"runtime_name": name, "container_uri": image,
                 "network_mode": network.get("networkMode"), "created": False, "deleted": False}
    rec = capture(store, "create_agent_runtime", ac,
                  agentRuntimeName=name,
                  description="GRX F5-7b diagnostic",
                  agentRuntimeArtifact={"containerConfiguration": {"containerUri": image}},
                  roleArn=role_arn,
                  networkConfiguration=network,
                  protocolConfiguration={"serverProtocol": "HTTP"},
                  tags=A.tags_for(run_id, expires_at))
    if not rec.ok:
        # A refusal at the CREATE is a first-class answer, not an error to retry. It is how the
        # `vpc_shape` arm is expected to end, and how `pull_ok_serve_bad` would end if
        # `public.ecr.aws` were not accepted at all.
        out.update({"create_refused": True, "error_code": rec.error_code,
                    "error_message": rec.error_message, "request_id": rec.request_id})
        return out
    out["created"] = True
    rid = rec.response["agentRuntimeId"]
    out["runtime_id"] = rid
    try:
        out.update(settle(ac, store, rid))
    finally:
        d = capture(store, "delete_agent_runtime", ac, agentRuntimeId=rid)
        out["deleted"] = bool(d.ok)
        if not d.ok:
            out["delete_error"] = f"{d.error_code}: {d.error_message}"
    return out


def main(argv: list[str] | None = None) -> int:                        # noqa: C901, PLR0915
    ap = argparse.ArgumentParser(description="F5-7b instrument diagnostic")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        print("F5-7b instrument diagnostic — dry run, no AWS call\n")
        print("would create one IAM role and THREE runtimes, in PUBLIC network mode:")
        print(f"  1. pull_ok_serve_bad  {PUBLIC_IMAGE}")
        print(f"  2. pull_fails         {MISSING_TAG_IMAGE}")
        print(f"  3. vpc_shape          {PUBLIC_IMAGE}  networkMode=VPC, nonexistent ids")
        print("\ncreates NO vpc, NO subnet, NO nat gateway, NO elastic ip — nothing billable "
              "beyond a few minutes of runtime create")
        print("writes results/DIAG-vpc-runtime-<stamp>.json and NO verdict")
        return 0

    stamp = utcnow_stamp()
    state = T.State.load()
    run_id, expires_at = state.run_id, state.expires_at
    fc = A.factory(args.region)
    account = A.account_id(fc)
    iam = fc.client("iam")
    ac = fc.client("bedrock-agentcore-control")
    store = EvidenceStore(run_id, FAMILY, LABEL)

    role_name = f"grx-runtime-vpcdiag-{run_id}"
    suffix = run_id.replace("-", "_").lower()
    report: dict = {
        "label": LABEL, "run_id": run_id, "region": args.region, "started_utc": stamp,
        "question": ("can F5-7b's image-pull oracle be measured, and is a public.ecr.aws image "
                     "enough to measure it with"),
        "writes_a_verdict": False,
        "created": [], "deleted": [], "arms": {},
        "public_image": PUBLIC_IMAGE, "missing_tag_image": MISSING_TAG_IMAGE,
    }
    role_arn = ""
    try:
        print(f"F5-7b instrument diagnostic  run={run_id}  region={args.region}")
        print(f"  role: {role_name}")
        role_arn = make_role(iam, store, role_name, account, run_id, expires_at)
        report["created"].append(f"iam-role/{role_name}")
        # A brand-new role's trust relationship is eventually consistent and
        # `CreateAgentRuntime` assumes it synchronously. A WAIT, not a retry loop: a retry would
        # also swallow a genuine trust-policy error and spend the timeout proving that public
        # images do not work when the defect is one line of JSON. F5-8:309-314, same trap.
        time.sleep(15)

        arms = [
            ("pull_ok_serve_bad", f"grxF57bPullOk_{suffix}", PUBLIC_IMAGE,
             {"networkMode": "PUBLIC"}),
            ("pull_fails", f"grxF57bPullBad_{suffix}", MISSING_TAG_IMAGE,
             {"networkMode": "PUBLIC"}),
            ("vpc_shape", f"grxF57bVpcShape_{suffix}", PUBLIC_IMAGE,
             {"networkMode": "VPC",
              "networkModeConfig": {"subnets": FAKE_SUBNETS, "securityGroups": FAKE_SG}}),
        ]
        for label, name, image, network in arms:
            print(f"\n  --- {label}  {network['networkMode']}  {image}")
            r = container_arm(ac, store, name[:48], image, role_arn, run_id, expires_at, network)
            report["arms"][label] = r
            if r.get("created"):
                report["created"].append(f"agent-runtime/{r.get('runtime_id')}")
                if r.get("deleted"):
                    report["deleted"].append(f"agent-runtime/{r.get('runtime_id')}")
            if r.get("create_refused"):
                print(f"      CREATE REFUSED  {r['error_code']}: {r['error_message']}")
            else:
                print(f"      {r.get('terminal_status')} after {r.get('seconds')}s  "
                      f"[{r.get('step_label')}]")
                print(f"      reason: {r.get('failure_reason') or '(none)'}")

        # ---- the three readings this was built to produce -----------------------
        ok = report["arms"].get("pull_ok_serve_bad", {})
        bad = report["arms"].get("pull_fails", {})
        shp = report["arms"].get("vpc_shape", {})

        ok_sig, bad_sig = arm_signature(ok), arm_signature(bad)

        public_accepted = bool(ok.get("created")) and not ok.get("create_refused")
        # Channel-aware. An arm has SPOKEN if it produced a code on either channel; the two arms
        # are DISTINGUISHABLE if what they said differs at all — including by arriving on different
        # channels, which is the case the first version of this predicate could not see.
        distinguishable = (
            bool(ok_sig["code"]) and bool(bad_sig["code"])
            and (ok_sig["channel"], ok_sig["code"], ok_sig["text"])
            != (bad_sig["channel"], bad_sig["code"], bad_sig["text"]))
        vpc_mode_live = bool(shp.get("created")) or (
            shp.get("create_refused")
            and "subnet" in str(shp.get("error_message", "")).lower())
        # Round 1's actual shape, promoted to a reading of its own because the producer needs it:
        # if a missing image is refused at create, then a pull failure observed AFTER a successful
        # create cannot have been a missing image, and the typo-vs-no-route ambiguity this script
        # was built to worry about is closed by the platform rather than by our classifier.
        pull_validated_at_create = bad_sig["channel"] == "create_refused"

        report["readings"] = {
            "public_ecr_image_accepted": public_accepted,
            "pull_and_post_pull_are_distinguishable": distinguishable,
            "vpc_mode_is_live_and_validated": vpc_mode_live,
            "image_existence_validated_synchronously_at_create": pull_validated_at_create,
            "f57b_is_measurable": bool(public_accepted and distinguishable and vpc_mode_live),
            "signatures": {"pull_ok_serve_bad": ok_sig, "pull_fails": bad_sig,
                           "vpc_shape": arm_signature(shp)},
            "why": {
                "public_ecr_image_accepted": (
                    "CreateAgentRuntime accepted a public.ecr.aws containerUri, so F5-7b needs no "
                    "ECR repository, no Docker daemon and no arm64 cross-build"
                    if public_accepted else
                    "CreateAgentRuntime refused the public.ecr.aws containerUri; F5-7b needs an "
                    "image of our own after all, and the audit's arm64 blocker stands"),
                "pull_and_post_pull_are_distinguishable": (
                    f"a missing manifest answered on the {bad_sig['channel']} channel with "
                    f"{bad_sig['code']!r} and a pulled-but-non-conforming image answered on the "
                    f"{ok_sig['channel']} channel with {ok_sig['code']!r}, so the producer can tell "
                    f"a failed pull from a failed start"
                    if distinguishable else
                    "the two arms produced the same observable on the same channel, so no VPC "
                    "arrangement can answer an oracle denominated in the pull"),
                "image_existence_validated_synchronously_at_create": (
                    "CreateAgentRuntime refused the nonexistent tag outright, so the control plane "
                    "resolves the manifest itself, on its own network path and not the customer "
                    "VPC's; a pull failure seen after a successful create is therefore not a "
                    "missing image"
                    if pull_validated_at_create else
                    "the nonexistent tag was accepted at create and failed later, so the producer "
                    "must distinguish a missing image from an unreachable registry itself"),
                "vpc_mode_is_live_and_validated": (
                    "networkMode=VPC was validated server-side against the ids supplied"
                    if vpc_mode_live else
                    "networkMode=VPC was not reached; check the error before building a VPC"),
            },
        }
        print("\n  READINGS")
        for k, v in report["readings"].items():
            if k in ("why", "signatures"):
                continue
            print(f"    {k}: {v}")
        # Printed off the signature triples, not off `failure_reason`: the whole correction above is
        # that an arm's observable does not always live in that field, and a reference the producer
        # will copy from must show the channel it was observed on.
        print(f"\n  reference signatures for the producer:")
        for label, sig in (("pull failed       ", bad_sig), ("pull ok, bad serve", ok_sig),
                           ("vpc mode          ", arm_signature(shp))):
            print(f"    {label} <{sig['channel']}> {sig['code']}  {sig['text'][:160]}")
    finally:
        if role_arn:
            d1 = capture(store, "delete_role_policy", iam, RoleName=role_name,
                         PolicyName="grx-runtime-vpcdiag")
            time.sleep(INTER_IAM_S)
            d2 = capture(store, "delete_role", iam, RoleName=role_name)
            if d1.ok and d2.ok:
                report["deleted"].append(f"iam-role/{role_name}")
            else:
                report["role_delete_error"] = {
                    "delete_role_policy": None if d1.ok else f"{d1.error_code}",
                    "delete_role": None if d2.ok else f"{d2.error_code}"}
        report["ended_utc"] = utcnow_stamp()
        report["residue_clean"] = sorted(report["created"]) == sorted(report["deleted"])
        out = ROOT / "results" / f"{LABEL}-{stamp}.json"
        out.write_text(json.dumps(R.mask(report), indent=2, sort_keys=True) + "\n")
        print(f"\n  created: {report['created']}")
        print(f"  deleted: {report['deleted']}")
        print(f"  residue clean: {report['residue_clean']}")
        print(f"  wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
