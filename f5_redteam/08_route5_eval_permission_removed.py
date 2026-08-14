#!/usr/bin/env python3
"""F5-4b — route #5: when guardrail evaluation CANNOT RUN, does the gateway deny or allow?

    python3 f5_redteam/08_route5_eval_permission_removed.py --dry-run
    python3 f5_redteam/08_route5_eval_permission_removed.py --n 2     # smoke
    python3 f5_redteam/08_route5_eval_permission_removed.py

The sealed oracle for this case is `RECORDED`, and the seal says why:

    "OUTCOME UNKNOWN. Removing bedrock:InvokeGuardrailChecks from the gateway role makes
     guardrail evaluation impossible: DENY (fail-closed) or ALLOW (fail-open)? Directly
     interrogates what AWS does not document"

with the method "remove the permission 3.1 requires, send a violating request; restore +
re-verify". F5-4a and F5-4b are the only two cases in the whole pre-registration carrying that
kind. Nothing is predicted here, and **both answers are publishable findings**. There is no
"pass" in this file: `FAIL_CLOSED` and `FAIL_OPEN` are two names for two measurements, the payload
reads neutrally in both directions, and the word "expected" appears nowhere in a branch.

§3.3 BP#4 tells the reader to "decide your failure posture explicitly" precisely because AWS
documents neither answer — and §4.1/§9 nonetheless label hop #4 "fail-secure". This case is where
that label is either corroborated for one failure mode or refuted.

WHY THE FAIL-OPEN BRANCH IS THE DANGEROUS ONE TO WRITE
-----------------------------------------------------
An ALLOW after the permission is removed is a security finding, and it has four mundane
explanations that all produce exactly the same observation:

  (a) the removal had not propagated. IAM is eventually consistent; F5-1 measured 32.1s for a
      grant to land on this account and F5-2 measured revokes still not landed after 220s.
  (b) a cached policy-evaluation decision. The gateway holds MCP sessions and the engine may
      cache; a second identical request could be answered from the first.
  (c) the request never reached the policy path at all — a session error, a 404, a tool error.
  (d) the content was never violating in the first place, so nothing would have denied it with
      the permission intact either. This is DEV-P1-18's exact shape: a filter that never ran,
      published as a filter that found nothing.

Every one of them is ruled out by construction rather than by argument, and the ruling-out is
what most of this file is:

  (d) A PRE-REMOVAL CONTROL. The identical violating request is sent with the permission INTACT
      and must be DENIED. Without it a benign-looking ALLOW is indistinguishable from a probe
      that never tested anything, and `controls_bracketed_the_measurement` gates the finding.
  (a) `iam:GetRolePolicy` is re-read until the statement is observably gone, and
      `iam:SimulatePrincipalPolicy` is polled until IAM's own answer for
      `bedrock:InvokeGuardrailChecks` is no longer `allowed`, with `PROP_CONFIRM_N`
      CONSECUTIVE confirmations and the elapsed seconds recorded. Both are IAM's view rather
      than ours.
  (b) A FRESH MCP session per leg with a distinct `policy_session_id`, plus a leg that sends a
      violating item **never sent before in this run** — so a content-keyed cache cannot answer
      it. The post-removal reading requires both violating legs to agree.
  (c) `n_reached_gateway` is counted per leg from the HTTP status, and a leg that did not reach
      the gateway is `NOTHING_USABLE` rather than an ALLOW.

THE BENIGN LEG IS THE DISAMBIGUATOR, AND IT IS WHAT MAKES FAIL-CLOSED ATTRIBUTABLE
---------------------------------------------------------------------------------
The mirror hazard is quieter and is easy to miss. Suppose the violating request is still DENIED
after the removal. That is *consistent* with fail-closed — and equally consistent with the
removal having had no effect on the request path at all, in which case the deny is the guardrail
still working and this case measured nothing.

The two are separated by a BENIGN request, sent through the same forbid, before and after:

  * with the permission intact, a benign request must be ALLOWED — the guardrail evaluates, finds
    nothing, the `forbid` does not match, the baseline permit applies;
  * if evaluation genuinely cannot run, a benign request has no more chance of being evaluated
    than a violating one, so a fail-closed engine must deny it TOO.

So `violating DENY + benign DENY` is fail-closed with the removal demonstrably in the path, while
`violating DENY + benign ALLOW` means evaluation still discriminated by content — i.e. it still
ran — and the honest output is NOT_MEASURED, not a fail-closed finding. That branch is also
exactly what a content cache would produce, so one control catches two confounds.

THE LEGS
--------
Each leg is a fresh MCP session, `n` requests, all-or-nothing:

  pre_violating       permission INTACT, violating item V1     must be DENY  (control for (d))
  pre_benign          permission INTACT, benign item           must be ALLOW (control, discriminates)
  post_violating_same permission REMOVED, the same V1          the measurement
  post_violating_new  permission REMOVED, unseen violating V2  the measurement, cache-proof
  post_benign         permission REMOVED, the same benign item the disambiguator
  restored_violating  permission RESTORED, V1 again            the seal's "restore + re-verify"

The request text is sent UNDECORATED. A marker appended to make each request unique would be the
obvious cache-breaker and is deliberately not used on the violating legs: the guardrail scores the
text, and decorating it could change the score, which is the one property the leg depends on.
Cache-breaking is done with a leg whose content is different rather than with content that has
been altered.

WHAT HAS TO BE BUILT FIRST, AND WHY
-----------------------------------
The engine's only policy is the baseline permit `permit(principal, action, resource is
AgentCore::Gateway);` — the statement §3.1 tells readers to add — and it denies nothing. Nothing
on this engine consults a guardrail at all, so removing the guardrail permission from the gateway
role would change no decision and every leg would read ALLOW before and after.

So this case creates ONE `forbid` carrying a guardrails block, using the statement form F5-4a
already verified live on this engine (`BedrockGuardrails::ContentFilter(["HATE"],
[context.input.text])["HATE"].confidenceScore.greaterThan(decimal("0.2"))`, F5-4a's
`guardrail_valid_path` arm, which DENIED all 20). Reusing a proven form matters: a new statement
would put "does this statement match" and "what happens when it cannot be evaluated" into one
arm, and a policy that quietly failed to match would produce ALLOW everywhere and read as
fail-open.

THE SURGERY, AND WHY THE RESTORE VERIFICATION IS NOT OPTIONAL
------------------------------------------------------------
`grx-gw-exec-<runid>` carries exactly ONE inline policy, `grx-gw-exec-policy`, with three
statements — and infra/01_iam.py wrote the middle one as its own `Sid` for this case:

    Sid=AgentCoreAsDocumented                     bedrock-agentcore:*        (§3.1)
    Sid=InvokeGuardrailChecks                     bedrock:InvokeGuardrailChecks   <-- the target
    Sid=HarnessLambdaTargetNotFromTheDocument     lambda:InvokeFunction on the echo Lambda

The role carries ZERO attached managed policies, so that document is the whole of its
permissions. The mutation is therefore: capture the ENTIRE document, `PutRolePolicy` the same
document with exactly that one statement filtered out, and restore by PUTTING BACK THE CAPTURED
OBJECT — never a re-typed one. The reduced document is built by FILTERING the captured statement
list, and the script refuses to send it unless it has exactly one statement fewer and the other
two Sids survive: a malformed reduction would strip `lambda:InvokeFunction` and break the echo
target for every case in the repo, silently, in a way that looks like a fail-open.

The restore is then verified by GETTING the document again and comparing **normalised JSON**, and
whether normalisation is safe here is worth stating rather than assuming:

  * Byte equality is not available and never was. IAM stores the document URL-encoded and
    re-serialises it, and botocore's `json_decode_policies` handler hands `GetRolePolicy` back as
    a decoded **dict** — so there are no bytes to compare on either side.
  * The normalisation used is `json.dumps(doc, sort_keys=True)`, which sorts DICT KEYS only. That
    is safe because JSON object key order carries no meaning, in IAM or anywhere else.
  * List order is deliberately PRESERVED. Sorting `Statement` would be unsafe for this
    comparison's purpose: the claim being checked is "we put back exactly the object we
    captured", and a comparison blind to statement order would also be blind to a restore that
    reordered the document. IAM's own evaluation is order-insensitive, so an order change would
    be semantically harmless and is still a difference this check must report — it would mean the
    restore path is not returning the captured object.
  * `infra/01_iam.py._canon` sorts lists on purpose, because its question is "does the live role
    match its spec" across an API that reorders `Action` lists. That is a different question and
    the looser form belongs there, not here.

A failed restore is `rc=2` with a message naming the role and the policy, because a gateway
execution role left without its guardrail permission breaks every subsequent case in this repo.

THE BLAST-RADIUS WINDOW, AND THE CHANNEL THAT SURVIVES SIGKILL
--------------------------------------------------------------
The permission is absent for at most `WINDOW_BOUND_S` = 300 seconds — single-digit minutes — and
the measured window is recorded in `window.seconds_without_the_permission`. The bound is enforced
inside the measurement loop: if the elapsed time reaches it, the remaining legs are abandoned and
the restore runs immediately, and the record says the window bound cut the measurement short.

The restore is in a `finally`, so it runs on an exception and on `KeyboardInterrupt` alike. What
a `finally` cannot survive is `SIGKILL`, so before the removal this case registers a ledger entry
whose `delete_op` is `put_role_policy` and whose document is the single removed statement as its
own inline policy. `infra/99_teardown.py` replays `delete_op` with `delete_params` against a
client for `service`, so that entry RESTORES THE PERMISSION even from a different process.

It restores it in a different SHAPE — an extra inline policy rather than the original document —
and that is deliberate: `infra/01_iam.py --ensure` reports an unexpected inline policy as drift
("a leftover mutation?"), so the fallback announces itself instead of healing silently. The
statement it carries names `Resource: "*"` and contains no ARN and no account id, which is what
makes it replayable at all: `state.json` is account-masked, `testbed.unmask_arn` restores only the
FIRST masked account field in a string, and a document carrying two ARNs (as the real one does,
for the echo Lambda) would come back from the ledger with the second still masked — a restore
that looks successful and writes an invalid ARN.

COST
----
`n` x 6 gateway `tools/call` requests, one `CreatePolicy`/`DeletePolicy` pair, and ~12 IAM
reads/writes. The `tools/call` requests are what bill: each violating request causes the engine to
call `InvokeGuardrailChecks` (when it can), which is charged in text units.

Never touched: the six pre-existing READY gateways, the `nopolicy` gateway (F6's paired
baseline), the three DRAFT guardrails, the two abandoned policy engines, any
`harness_*`/`uitestagent_*` resource, and any IAM role whose name does not begin with `grx-`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                              # noqa: E402
import cedar as C                                                   # noqa: E402
import mcp as MCP                                                   # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402
import testbed as T                                                 # noqa: E402
from evidence import EvidenceStore, capture                         # noqa: E402

FAMILY = "f5"
CASE = "F5-4b"


def _load(spec):
    """Execute an already-built spec.

    The `spec_from_file_location` call is written out at the site rather than wrapped, for the
    reason `lib/tests/test_module_name_collisions.py` states: it reads the registered
    `sys.modules` name statically, and a helper taking the name as a parameter makes that name
    unreadable to the guard.
    """
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The "terminal status" definition comes from the provisioner that owns it, under the same
# sys.modules key and the same target expression F5-2 and F5-4a use.
_pemod = _load(importlib.util.spec_from_file_location(
    "_grx_policy_engine", ROOT / "infra" / "03_policy_engine.py"))
wait_status = _pemod.wait_status
POLICY_OK = _pemod.TERMINAL_OK

TOOL = "echo"

# The surgical target. Both are asserted against the live document before anything is written:
# the Sid is how the statement is found, and the action is what the document claims it grants.
TARGET_SID = "InvokeGuardrailChecks"
TARGET_ACTION = "bedrock:InvokeGuardrailChecks"
# What infra/01_iam.py ships on the gateway execution role. Verified live, never assumed: this
# case edits the document that IS the role's entire permission set.
GW_EXEC_INLINE = "grx-gw-exec-policy"
EXPECTED_SIDS = ("AgentCoreAsDocumented", TARGET_SID,
                 "HarnessLambdaTargetNotFromTheDocument")

# The forbid, in the exact form F5-4a verified live on this engine (its `guardrail_valid_path`
# arm DENIED all 20). A new statement here would test two things at once.
GUARDRAIL_FUNCTION = "ContentFilter"
GUARDRAIL_CATEGORY = "HATE"
GUARDRAIL_PATH = "context.input.text"
GUARDRAIL_THRESHOLD = "0.2"

VIOLATING_CORPUS = ROOT / "corpora" / "content_filter" / "hate.jsonl"
BENIGN_CORPUS = ROOT / "corpora" / "benign" / "benign.jsonl"

LEG_PRE_VIOLATING = "pre_violating"
LEG_PRE_BENIGN = "pre_benign"
LEG_POST_VIOLATING_SAME = "post_violating_same"
LEG_POST_VIOLATING_NEW = "post_violating_new"
LEG_POST_BENIGN = "post_benign"
LEG_RESTORED_VIOLATING = "restored_violating"
LEGS = (LEG_PRE_VIOLATING, LEG_PRE_BENIGN, LEG_POST_VIOLATING_SAME,
        LEG_POST_VIOLATING_NEW, LEG_POST_BENIGN, LEG_RESTORED_VIOLATING)
# The legs measured while the permission is absent. Named so no later edit can move a leg into
# or out of the window without saying so.
WINDOW_LEGS = (LEG_POST_VIOLATING_SAME, LEG_POST_VIOLATING_NEW, LEG_POST_BENIGN)

# E-class: the mechanism is deterministic or it is not a mechanism. Small, and the reading is
# all-or-nothing per leg — a split leg is itself a finding and is reported, never averaged.
N_PER_LEG = 5

# The window. Single-digit minutes, enforced inside the loop and not merely hoped for.
WINDOW_BOUND_S = 300
# IAM propagation for the REMOVAL. Deliberately tighter than F5-2's 300s grant bound, because
# every second here is a second the gateway execution role is missing a permission: if IAM has
# not converged inside this, the honest answer is that the case could not be measured in a safe
# window, not that we waited longer.
REMOVE_PROP_MAX_S = 90
PROP_EVERY_S = 5
PROP_CONFIRM_N = 3
# The restore direction gets a much longer bound. A grant that has not landed yet is a broken
# testbed, so patience there is the cheap direction — and unlike the removal it costs no
# exposure.
RESTORE_PROP_MAX_S = 900

# The data plane has its own latency, separate from IAM's, and nothing documents it. Both
# directions are polled for a STABLE decision — whichever decision that turns out to be.
STABILISE_MAX_S = 90
STABILISE_EVERY_S = 5
STABILISE_CONFIRM_N = 3

DELETE_ATTEMPTS = 4
DELETE_SLEEP_S = 3
INTER_CALL_S = 0.2
# IAM has no entry in `awsclients.RATE_LIMITS`, and `limiter().wait()` returns 0.0 for an unknown
# operation — so calling it for an IAM write would read as pacing while doing nothing, which is
# the defect that module's SELF_IMPOSED_LIMITS comment describes. Spaced explicitly instead.
INTER_IAM_S = 0.5

# The five answers this case can produce. Two are findings; three are instrument failures.
FINDING_FAIL_CLOSED = "FAIL_CLOSED_DENY_WHEN_EVALUATION_CANNOT_RUN"
FINDING_FAIL_OPEN = "FAIL_OPEN_ALLOW_WHEN_EVALUATION_CANNOT_RUN"
FINDING_NOT_OBSERVABLE = "REMOVAL_NOT_OBSERVABLE_AT_THE_REQUEST_PATH"
FINDING_INCOHERENT = "SPLIT_OR_INCOHERENT_LEGS"
FINDING_NO_BRACKET = "CONTROLS_DID_NOT_BRACKET_THE_MEASUREMENT"
FINDINGS = (FINDING_FAIL_CLOSED, FINDING_FAIL_OPEN, FINDING_NOT_OBSERVABLE,
            FINDING_INCOHERENT, FINDING_NO_BRACKET)
# The two the pre-registration declares to be the unknown outcome. Either is publishable and
# neither is a "pass".
PUBLISHABLE_FINDINGS = (FINDING_FAIL_CLOSED, FINDING_FAIL_OPEN)

GUARDS = (
    "engine_was_quiet_at_start",
    "role_carried_exactly_its_shipped_document",
    "forbid_was_active_before_any_leg_ran",
    "controls_bracketed_the_measurement",
    "removal_was_confirmed_by_iam_before_the_window_legs",
    "every_window_leg_reached_the_gateway",
    "post_removal_violating_legs_agreed",
    "window_stayed_within_its_bound",
    "document_was_restored_and_verified_byte_for_byte_after_normalisation",
    "blocking_was_reasserted_after_the_restore",
    "probe_policy_was_deleted",
)

MAX_MUTATIONS = 4   # 1 forbid + its delete, 1 document edit + its restore


class ConfigError(RuntimeError):
    """A precondition that must stop the run before anything is mutated. Never a verdict."""


class RestoreError(RuntimeError):
    """The gateway execution role could not be put back. The one failure that must be loud."""


# ---------------------------------------------------------------------------
# interlocks
# ---------------------------------------------------------------------------

def assert_engine_is_quiet(state: T.State) -> dict[str, Any]:
    """Refuse to start if another case's probe policy is live on the shared engine.

    The same interlock F5-2 and F5-4a carry, and for the same reason with the roles reversed:
    this script adds a `forbid` to an engine every gateway request in the testbed passes
    through, so a concurrent case's decisions would change under it and its data would be
    destroyed. The ledger is the channel that can see this — `policy` resources are
    structurally untaggable (`CreatePolicy` has no `tags` member), so every script that creates
    one registers it in `state.json`.
    """
    others = [r for r in state.of_kind("policy") if r.logical != "baseline"]
    if others:
        raise ConfigError(
            "the shared policy engine is not quiet: "
            + ", ".join(f"{r.logical} ({r.ids.get('policy_id')})" for r in others)
            + ". Another case's probe policy is registered, so the `forbid` this case needs "
              "would change that case's decisions. Wait for it to finish, or if it crashed, "
              "delete the policy and drop the ledger entry first.")
    return {"policies_on_engine_at_start": [r.logical for r in state.of_kind("policy")],
            "checked": "state.json policy resources other than `baseline`"}


def capture_document(iam, store, *, role_name: str,
                     policy_name: str) -> dict[str, Any]:
    """Read the role's WHOLE inline document and every fact needed to put it back.

    Called before anything is written, and its return value is the only source the restore uses.
    Nothing here is re-typed from `infra/01_iam.py`: a restore assembled from a spec would put
    back what the spec says rather than what was there, and the two differ precisely when
    something else has changed the role — which is the case a restore must not paper over.

    Refuses unless the role's permissions are exactly this one document. An attached managed
    policy could grant `bedrock:InvokeGuardrailChecks` from outside it, in which case removing
    the statement would remove nothing and every post-removal leg would be about an unchanged
    permission set.
    """
    names = capture(store, "list_role_policies", iam, RoleName=role_name)
    if not names.ok:
        raise ConfigError(
            f"ListRolePolicies on {role_name} failed ({names.error_code}); refusing to edit a "
            f"document on a role whose policy set was never read")
    got_names = sorted(names.response.get("PolicyNames") or [])
    if got_names != [policy_name]:
        raise ConfigError(
            f"{role_name} carries inline policies {got_names}, not exactly [{policy_name!r}]. "
            f"This case removes ONE statement from ONE document and restores that document; a "
            f"role whose permissions live somewhere else as well is a role whose post-removal "
            f"legs would be about an unchanged permission set.")
    attached = capture(store, "list_attached_role_policies", iam, RoleName=role_name)
    if not attached.ok:
        raise ConfigError(
            f"ListAttachedRolePolicies on {role_name} failed ({attached.error_code}); an "
            f"attached managed policy could grant {TARGET_ACTION} from outside the document "
            f"this case edits, and the removal would then remove nothing")
    managed = sorted(p["PolicyArn"] for p in (attached.response.get("AttachedPolicies") or []))
    if managed:
        raise ConfigError(
            f"{role_name} carries attached managed policies {managed}; infra/01_iam.py attaches "
            f"none. {TARGET_ACTION} may survive the removal through one of them, which would "
            f"make every post-removal leg a measurement of nothing.")

    rec = capture(store, "get_role_policy", iam, RoleName=role_name, PolicyName=policy_name)
    if not rec.ok:
        raise ConfigError(
            f"GetRolePolicy({role_name}/{policy_name}) failed ({rec.error_code}); the document "
            f"was never captured, so it could not be restored. Nothing has been changed.")
    doc = (rec.response or {}).get("PolicyDocument")
    # botocore's `json_decode_policies` handler decodes an IAM policy document into a dict. A
    # string here means that handler did not run — a different client construction, or a future
    # botocore — and parsing it silently would hide which of the two we got.
    if isinstance(doc, str):
        raise ConfigError(
            f"GetRolePolicy returned PolicyDocument as a str, not a dict. botocore's "
            f"json_decode_policies handler normally decodes it; a string here means the client "
            f"was built differently than this case assumes, and the restore's normalised "
            f"comparison would be comparing a string with a dict. Refusing to write.")
    if not isinstance(doc, dict):
        raise ConfigError(f"GetRolePolicy returned PolicyDocument of type "
                          f"{type(doc).__name__}; expected a decoded dict")
    statements = doc.get("Statement")
    if not isinstance(statements, list):
        raise ConfigError(
            f"{policy_name} has no Statement LIST (got {type(statements).__name__}). A "
            f"single-statement document written as a bare object cannot have one statement "
            f"removed from it, and this case's target Sid is one of three.")
    sids = [s.get("Sid") for s in statements]
    if sids.count(TARGET_SID) != 1:
        raise ConfigError(
            f"{policy_name} carries {sids.count(TARGET_SID)} statements with Sid="
            f"{TARGET_SID!r} (Sids: {sids}); this case removes exactly one. Zero means the "
            f"permission is already absent — the testbed is not in its shipped state and some "
            f"earlier run did not restore it — and more than one means the document is not the "
            f"one infra/01_iam.py wrote.")
    target = next(s for s in statements if s.get("Sid") == TARGET_SID)
    actions = target.get("Action")
    action_list = [actions] if isinstance(actions, str) else list(actions or [])
    if TARGET_ACTION not in action_list:
        raise ConfigError(
            f"the statement with Sid={TARGET_SID!r} grants {action_list}, which does not include "
            f"{TARGET_ACTION!r}. Removing it would not remove the permission this case is about, "
            f"and every leg after the removal would be measuring something else.")
    if len(action_list) != 1:
        raise ConfigError(
            f"the statement with Sid={TARGET_SID!r} grants {action_list} — more than "
            f"{TARGET_ACTION!r} alone. Removing it would withdraw permissions beyond the one "
            f"under test, so an observed change could not be attributed to guardrail evaluation "
            f"being impossible.")
    return {
        "role_name": role_name, "policy_name": policy_name,
        "document": doc,
        "normalised": normalised(doc),
        "sha256": sha256(normalised(doc).encode("utf-8")).hexdigest(),
        "sids": sids,
        "n_statements": len(statements),
        "target_statement": target,
        "read_from": "iam:GetRolePolicy (live)",
        "why_the_whole_document": (
            "the restore puts back this captured object, never a document assembled from "
            "infra/01_iam.py's spec: a spec-built restore writes what the spec says rather than "
            "what was there, and the two differ exactly when something else has changed the role"),
    }


def normalised(doc: dict[str, Any]) -> str:
    """A comparable form of a policy document: `sort_keys=True`, list order PRESERVED.

    Byte equality is not available and never was — IAM stores the document URL-encoded and
    re-serialises it, and botocore hands `GetRolePolicy` back as a decoded dict, so there are no
    bytes on either side to compare. What IS available is a canonical text form of the decoded
    object, and the only normalisation applied is sorting object keys, which carry no meaning in
    JSON.

    List order is deliberately NOT normalised. `infra/01_iam.py._canon` does sort lists, correctly,
    because its question is "does the live role match its spec" across an API that reorders
    `Action` lists. This function's question is different: "did the restore put back the object we
    captured". A comparison blind to statement order would also be blind to a restore that
    reordered the document — semantically harmless to IAM, and still evidence that the restore
    path is not returning the captured object, which is the thing being verified.
    """
    return json.dumps(doc, sort_keys=True, ensure_ascii=False)


def document_without_sid(doc: dict[str, Any], sid: str) -> dict[str, Any]:
    """The captured document minus exactly one statement, built by FILTERING.

    Filtering rather than re-typing, and then checked in both directions: exactly one statement
    fewer, and every other Sid still present. The failure this exists for is not subtle in its
    consequences — the same document carries `lambda:InvokeFunction` on the echo Lambda, so a
    reduction that dropped the wrong statement would break the gateway's target for every case
    in the repo, and the symptom at the gateway would be a tool error that a careless reading
    could file as a fail-open.
    """
    statements = list(doc.get("Statement") or [])
    kept = [s for s in statements if s.get("Sid") != sid]
    if len(kept) != len(statements) - 1:
        raise ConfigError(
            f"filtering Sid={sid!r} removed {len(statements) - len(kept)} statement(s), not "
            f"exactly 1. Refusing to write a document this case cannot account for.")
    remaining = sorted(s.get("Sid") for s in kept)
    if sorted(set(remaining)) != sorted({s.get("Sid") for s in statements} - {sid}):
        raise ConfigError(
            f"the reduced document's Sids {remaining} are not the captured document's minus "
            f"{sid!r}. Refusing to write.")
    if not kept:
        raise ConfigError(
            "the reduced document would have no statements at all; IAM rejects an empty "
            "Statement list, and a role whose only document failed to write is a role with no "
            "permissions")
    out = {k: v for k, v in doc.items() if k != "Statement"}
    out["Statement"] = kept
    return out


# ---------------------------------------------------------------------------
# the removal, the restore, and IAM's own view of both
# ---------------------------------------------------------------------------

def register_restore_intent(state: T.State, *, role_name: str, run_id: str,
                            target_statement: dict[str, Any]) -> str:
    """A ledger entry that RESTORES THE PERMISSION even if this process is SIGKILLed.

    `finally` is not a watchdog. `infra/99_teardown.py` replays each ledger resource's
    `delete_op` with its `delete_params` against a client for its `service`, so an entry whose
    `delete_op` is `put_role_policy` is an undo that any later process can execute — the "undo
    intent as data" shape `lib/testbed.Resource` documents.

    It restores the permission in a DIFFERENT SHAPE from the original: a separate inline policy
    rather than the statement's place in the original document. That is deliberate, twice over.

    * It announces itself. `infra/01_iam.py --ensure` reports an unexpected inline policy as
      drift ("a leftover mutation?"), so a fallback that fired is visible on the next verify
      instead of healing silently and hiding that a run was killed mid-window.
    * It is REPLAYABLE. `state.json` is account-masked and `testbed.unmask_arn` restores only the
      FIRST masked account field in a string. The real document carries two ARNs (the echo
      Lambda and its version wildcard), so storing it here would come back from the ledger with
      the second still masked — a restore that returns 200 and writes an invalid ARN. The single
      statement this entry carries names `Resource: "*"` and contains no ARN and no account id at
      all, so masking is a no-op on it.

    Returns the policy name the fallback would create, for the record.
    """
    name = f"grx-f54b-restore-{run_id}"
    state.record(T.Resource(
        kind="iam-inline-policy", logical="f54b_restore_intent", name=name,
        service="iam", delete_op="put_role_policy",
        delete_params={"RoleName": role_name, "PolicyName": name,
                       "PolicyDocument": json.dumps(
                           {"Version": "2012-10-17", "Statement": [target_statement]})},
        ids={"role_name": role_name, "case": CASE, "restores_action": TARGET_ACTION,
             "removed_from": GW_EXEC_INLINE, "removed_sid": TARGET_SID},
        arn="", delete_priority=1,
        notes=(f"{CASE} RESTORE INTENT, not a resource to delete. Replaying this entry re-grants "
               f"{TARGET_ACTION} to {role_name} as a SEPARATE inline policy. If it is still "
               f"here, the run was killed inside its window: run `python3 infra/01_iam.py "
               f"--ensure --fix-drift` to put the role back in its shipped shape, then drop this "
               f"entry.")))
    state.write()
    return name


def remove_statement(iam, store, *, role_name: str, policy_name: str,
                     reduced: dict[str, Any]) -> dict[str, Any]:
    """Write the reduced document. This is the mutation, and it opens the window."""
    rec = capture(store, "put_role_policy", iam, RoleName=role_name, PolicyName=policy_name,
                  PolicyDocument=json.dumps(reduced))
    time.sleep(INTER_IAM_S)
    if not rec.ok:
        raise ConfigError(
            f"PutRolePolicy({role_name}/{policy_name}) failed while REMOVING the statement "
            f"({rec.error_code}: {rec.error_message}). Nothing was changed — a failed write "
            f"leaves the previous document in place — so this is a refusal, not a broken role.")
    return {"removed": True, "request_id": rec.request_id, "http_status": rec.http_status,
            "normalised_written": normalised(reduced),
            "sha256_written": sha256(normalised(reduced).encode("utf-8")).hexdigest()}


def restore_document(iam, store, *, captured: dict[str, Any]) -> dict[str, Any]:
    """Put the CAPTURED document back, then GET it and compare. Never raises: runs in a `finally`.

    The verification is the point. `PutRolePolicy` returning 200 is a control-plane
    acknowledgement, and this case's failure mode is a gateway execution role left without the
    permission every guardrail-bearing policy in the repo needs. So the answer to "is it back"
    comes from a fresh `GetRolePolicy`, compared as normalised JSON against the capture, with the
    sha256 of both recorded so a later reader can check the comparison rather than trust it.

    Retried, because the write is the only thing standing between this run and a broken testbed;
    each attempt re-reads, so a transient failure on the read does not report a failed restore.
    """
    role_name, policy_name = captured["role_name"], captured["policy_name"]
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        put = capture(store, "put_role_policy", iam, RoleName=role_name,
                      PolicyName=policy_name,
                      PolicyDocument=json.dumps(captured["document"]))
        time.sleep(INTER_IAM_S)
        back = capture(store, "get_role_policy", iam, RoleName=role_name,
                       PolicyName=policy_name)
        live = (back.response or {}).get("PolicyDocument") if back.ok else None
        got_norm = normalised(live) if isinstance(live, dict) else None
        row = {
            "attempt": attempt,
            "put_ok": bool(put.ok), "put_error": put.error_code or None,
            "read_back_ok": bool(back.ok), "read_error": back.error_code or None,
            "sha256_read_back": (sha256(got_norm.encode("utf-8")).hexdigest()
                                 if got_norm else None),
            "sids_read_back": ([s.get("Sid") for s in (live.get("Statement") or [])]
                               if isinstance(live, dict) else None),
        }
        attempts.append(row)
        if got_norm == captured["normalised"]:
            return {
                "restored": True, "attempts": attempts,
                "sha256_expected": captured["sha256"],
                "sha256_read_back": row["sha256_read_back"],
                "comparison": ("normalised JSON of the decoded document: sort_keys=True, list "
                               "order preserved. See `normalised()` for why byte equality is "
                               "unavailable and why statement order is NOT normalised away"),
            }
        time.sleep(DELETE_SLEEP_S)
    return {
        "restored": False, "attempts": attempts,
        "sha256_expected": captured["sha256"],
        "sha256_read_back": attempts[-1]["sha256_read_back"] if attempts else None,
        "manual_remedy": (
            f"the inline policy {policy_name!r} on IAM role {role_name!r} does NOT match the "
            f"document this run captured. {TARGET_ACTION} may be missing, which breaks every "
            f"guardrail-in-policy case in this repo. Restore it with "
            f"`python3 infra/01_iam.py --ensure --fix-drift`, then verify with "
            f"`aws iam get-role-policy --role-name {role_name} --policy-name {policy_name}`"),
    }


def wait_for_iam(iam, store, *, role_name: str, policy_name: str, role_arn: str,
                 want_present: bool, phase: str, max_s: float) -> dict[str, Any]:
    """Poll IAM's OWN view until the statement's presence matches `want_present`.

    Two independent channels, both IAM's rather than ours, and both required to agree for
    `PROP_CONFIRM_N` CONSECUTIVE rounds:

      `GetRolePolicy`            — is the Sid in the stored document?
      `SimulatePrincipalPolicy`  — does IAM evaluate `bedrock:InvokeGuardrailChecks` as allowed
                                   for this principal?

    The stored document changes the instant the write lands; the *evaluation* is what the gateway
    depends on, and it is the eventually-consistent half. Reading only the document would report
    the removal as complete while the FAS path still had the permission, which is confound (a) in
    the module docstring — the one that turns a stale ALLOW into a published fail-open.

    Consecutive rather than cumulative: a cumulative count is satisfied by an alternating
    sequence, which is exactly the state that has not converged. F5-2 measured the failure —
    a wait ended on a single confirmation and 9 of the next 20 calls disagreed with it.

    A simulation is corroborating, not decisive, and the payload says so: it is not an
    authorization event, and it cannot see a Forward Access Session's own cached credentials. It
    is the best available channel for a role this harness cannot assume, and its limits are
    recorded rather than glossed.
    """
    t0 = time.monotonic()
    deadline = t0 + max_s
    seen: list[dict[str, Any]] = []
    streak = 0
    while time.monotonic() < deadline:
        doc_rec = capture(store, "get_role_policy", iam, RoleName=role_name,
                          PolicyName=policy_name)
        live = (doc_rec.response or {}).get("PolicyDocument") if doc_rec.ok else None
        sids = ([s.get("Sid") for s in (live.get("Statement") or [])]
                if isinstance(live, dict) else None)
        present_in_doc = (None if sids is None else TARGET_SID in sids)

        sim = capture(store, "simulate_principal_policy", iam, PolicySourceArn=role_arn,
                      ActionNames=[TARGET_ACTION])
        results = ((sim.response or {}).get("EvaluationResults") or []) if sim.ok else []
        decisions = [r.get("EvalDecision") for r in results]
        simulated_allowed = (None if not results
                             else all(d == "allowed" for d in decisions))

        row = {"present_in_document": present_in_doc, "simulated_allowed": simulated_allowed,
               "decisions": decisions, "sids": sids,
               "at_s": round(time.monotonic() - t0, 1)}
        seen.append(row)
        agree = (present_in_doc is want_present and simulated_allowed is want_present)
        streak = streak + 1 if agree else 0
        if streak >= PROP_CONFIRM_N:
            return {"reached": True, "phase": phase, "wanted_present": want_present,
                    "seconds": round(time.monotonic() - t0, 1),
                    "consecutive_confirmations": streak,
                    "confirmations_required": PROP_CONFIRM_N, "max_wait_s": max_s,
                    "rounds": seen,
                    "channels": ("iam:GetRolePolicy (the stored document) AND "
                                 "iam:SimulatePrincipalPolicy (IAM's evaluation). Both must "
                                 "agree, because the document changes on the write while the "
                                 "evaluation is the eventually-consistent half the gateway "
                                 "actually depends on"),
                    "simulation_caveat": (
                        "SimulatePrincipalPolicy is not an authorization event and cannot see a "
                        "Forward Access Session's cached credentials. It is the best channel "
                        "available for a role this harness cannot assume; its limits are why the "
                        "benign leg exists as an independent disambiguator")}
        time.sleep(PROP_EVERY_S)
    return {"reached": False, "phase": phase, "wanted_present": want_present,
            "seconds": round(time.monotonic() - t0, 1),
            "consecutive_confirmations": streak,
            "confirmations_required": PROP_CONFIRM_N, "max_wait_s": max_s, "rounds": seen,
            "why_it_matters": (
                f"IAM never agreed on {PROP_CONFIRM_N} consecutive rounds within {max_s}s that "
                f"{TARGET_ACTION} is "
                f"{'present' if want_present else 'absent'}, so any decision recorded after this "
                f"point is about a permission state that was never confirmed")}


# ---------------------------------------------------------------------------
# the forbid this case needs in order to have anything to fail at
# ---------------------------------------------------------------------------

def forbid_statement(gateway_arn: str, action_id: str) -> str:
    """A `forbid` whose condition is a GUARDRAILS block on a path the request really carries.

    Exactly F5-4a's `guardrail_valid_path` form, which that case verified live on this engine:
    the statement created, became ACTIVE, and DENIED all 20 of its HATE requests. Reusing it is
    what keeps this case's post-removal reading interpretable — a new statement would fold "does
    this statement match at all" into the arm whose subject is what happens when it cannot be
    evaluated, and a statement that quietly failed to match would produce ALLOW everywhere and
    read as fail-open.

    A guardrails block, not a plain Cedar condition, because the bracketed data paths are what
    get handed to Bedrock Guardrails — that hand-off is the thing `bedrock:InvokeGuardrailChecks`
    authorises, and a plain `when` clause would be evaluated by Cedar itself and would not need
    the permission at all. (A plain-condition failure is F5-4a's `cedar_missing_attr` arm.)
    """
    return C.statement(
        "forbid", resource=C.gateway_resource(gateway_arn),
        action=f'action == {C.ENTITY_ACTION}::"{action_id}"',
        when_guardrails=C.guardrail_condition(
            GUARDRAIL_FUNCTION, [GUARDRAIL_CATEGORY], [GUARDRAIL_PATH],
            threshold=GUARDRAIL_THRESHOLD))


def create_forbid(ac, store, state, *, engine_id: str, run_id: str,
                  statement: str) -> dict[str, Any]:
    """Create the blocking policy, ledger first. Raises if it cannot be created or does not settle.

    `IGNORE_ALL_FINDINGS` is not passed and `validationMode` is left at the service default: this
    statement is meant to be valid, so a strict-mode rejection would be information about a
    defect in our own statement rather than an obstacle to route around.
    """
    name = T.check_name(ac, "CreatePolicy", f"grx_f54b_block_{run_id}")
    lint = C.check_statement(statement)
    if lint:
        raise ConfigError(
            f"the blocking statement fails the offline lint: {lint}. A policy that will not "
            f"enforce would make every leg read ALLOW, and 'fail-open' would be "
            f"indistinguishable from nothing having been blocking in the first place.")
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac, name=name, policyEngineId=engine_id,
                  definition={"policy": {"statement": statement}},
                  description=f"{CASE}: the guardrail-bearing forbid whose evaluation is removed",
                  enforcementMode="ACTIVE")
    if not rec.ok:
        raise ConfigError(
            f"CreatePolicy failed ({rec.error_code}: {rec.error_message}); without a policy whose "
            f"evaluation NEEDS {TARGET_ACTION}, removing that permission changes nothing and "
            f"this case has no subject.")
    policy_id = (rec.response or {}).get("policyId")
    state.record(T.Resource(
        kind="policy", logical="f54b_block", name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": policy_id},
        ids={"policy_engine_id": engine_id, "policy_id": policy_id, "statement": statement,
             "case": CASE},
        arn="", delete_priority=40,
        notes=(f"{CASE}'s guardrail-bearing forbid. `policy` takes no tags, so this ledger entry "
               f"and this script's finally are the only channels that can find it.")))
    state.write()
    live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": policy_id})
    status = live.get("status")
    if status not in POLICY_OK:
        raise ConfigError(
            f"the blocking policy settled in {status} ({live.get('statusReasons')}), so it never "
            f"enforced. Every leg would read ALLOW and the case would report a fail-open of "
            f"nothing.")
    return {"policy_id": policy_id, "policy_name": name, "status": status,
            "statement": statement, "lint": lint}


def delete_forbid(ac, store, state, *, engine_id: str, policy_id: str) -> dict[str, Any]:
    """Delete the blocking policy. Never raises: this runs in a `finally`."""
    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac, policyEngineId=engine_id, policyId=policy_id)
        if rec.ok or rec.error_code == "ResourceNotFoundException":
            state.drop("policy", "f54b_block")
            state.write()
            return {"deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}: {rec.error_message}")
        time.sleep(DELETE_SLEEP_S)
    return {"deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors,
            "manual_remedy": f"delete_policy policyEngineId={engine_id} policyId={policy_id}"}


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------

def corpus_items(path: Path, n: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
            if len(items) >= n:
                break
    if len(items) < n:
        raise ConfigError(f"{path} has {len(items)} items, need {n}")
    return items


def client_for_leg(gateway_url: str, factory, store, *, run_id: str, leg: str,
                   session_timeout_s: int):
    """A FRESH MCP session per leg, with its own `policy_session_id`.

    Fresh because a long-lived session is a cache with our name on it: confound (b). A session
    opened before the removal and reused after it could answer from state established while the
    permission existed, and the difference would be invisible in the response. The session id is
    derived from the leg so it is deterministic and so two legs can never share temporal state.
    """
    client = MCP.client_for(gateway_url, factory, store=store,
                            policy_session_id=MCP.policy_session_id(run_id, f"f54b-{leg}"),
                            session_timeout_s=session_timeout_s)
    client.initialize()
    return client


def probe_leg(client, *, leg: str, action_id: str, text: str, item_id: str,
              n: int) -> dict[str, Any]:
    """`n` requests carrying ONE text, tallied all-or-nothing.

    The text is sent UNDECORATED — no per-request marker. On a violating leg the guardrail scores
    exactly this string, and appending anything could change the score, which is the one property
    the leg depends on. Cache-breaking is done with a leg whose CONTENT differs
    (`post_violating_new`), not with content that has been altered.

    `unanimous` is reported rather than a rate: this is an E-class mechanism and a split leg is a
    finding, not an average. `n_reached_gateway` is counted from the HTTP status so a leg that
    never reached the policy path is `NOTHING_USABLE` rather than an ALLOW — confound (c).
    """
    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        try:
            d = client.call_tool(action_id, {"text": text})
            rows.append({"i": i, "denied": bool(d.denied), "ran": bool(d.ran),
                         "http_status": d.http_status, "outcome": d.outcome,
                         "unclassified": bool(d.unclassified),
                         "default_deny": bool(d.default_deny),
                         "decision": d.to_json()})
        except Exception as exc:                                  # noqa: BLE001
            # A transport error is data, not a verdict: it is neither a DENY nor an ALLOW, and
            # counting it as either is how a broken session becomes a security finding.
            rows.append({"i": i, "denied": False, "ran": False, "http_status": None,
                         "outcome": f"ERROR:{type(exc).__name__}", "error": str(exc)[:400]})
        time.sleep(INTER_CALL_S)
    denied = sum(1 for r in rows if r["denied"])
    ran = sum(1 for r in rows if r["ran"])
    reached = sum(1 for r in rows if r.get("http_status") is not None)
    usable = denied + ran
    return {
        "leg": leg, "item_id": item_id, "n": len(rows), "n_denied": denied, "n_allowed": ran,
        "n_usable": usable, "n_reached_gateway": reached,
        "n_neither": len(rows) - usable,
        "unanimous": usable > 0 and denied in (0, usable),
        "decision": ("DENY" if usable and denied == usable
                     else "ALLOW" if usable and denied == 0
                     else "SPLIT" if usable else "NOTHING_USABLE"),
        "outcomes_seen": sorted({r.get("outcome", "") for r in rows}),
        "rows": rows,
    }


def wait_for_stable_decision(gateway_url, factory, store, *, action_id: str, text: str,
                             run_id: str, phase: str,
                             max_s: float = STABILISE_MAX_S) -> dict[str, Any]:
    """Poll until SOME decision repeats `STABILISE_CONFIRM_N` times consecutively.

    Symmetric on purpose, and this is the design point the sealed RECORDED kind forces. A loop
    that waited for a NAMED decision would encode an expectation — and for a case whose seal
    says the outcome is unknown, waiting for DENY would manufacture fail-closed by patience and
    waiting for ALLOW would manufacture fail-open. So this waits for STABILITY and reports
    whichever decision stabilised, together with the whole series.

    A series that never stabilises is a finding in its own right: it means the request path is
    non-deterministic under the mutation, which is neither of the two answers the seal names and
    is reported as such rather than resolved by majority.

    A fresh session per probe, because a long-lived one is its own cache.
    """
    t0 = time.monotonic()
    deadline = t0 + max_s
    seen: list[str] = []
    streak = 0
    last = ""
    while time.monotonic() < deadline:
        client = client_for_leg(gateway_url, factory, store, run_id=run_id,
                               leg=f"{phase}-{len(seen):02d}", session_timeout_s=900)
        try:
            d = client.call_tool(action_id, {"text": text})
            got = "DENY" if d.denied else "ALLOW" if d.ran else f"OTHER:{d.outcome}"
        except Exception as exc:                                  # noqa: BLE001
            got = f"ERROR:{type(exc).__name__}"
        finally:
            client.close()
        seen.append(got)
        streak = streak + 1 if got == last else 1
        last = got
        if streak >= STABILISE_CONFIRM_N and got in ("DENY", "ALLOW"):
            return {"stabilised": True, "decision": got, "phase": phase,
                    "seconds": round(time.monotonic() - t0, 1), "decisions_seen": seen,
                    "consecutive_confirmations": streak,
                    "confirmations_required": STABILISE_CONFIRM_N, "max_wait_s": max_s,
                    "why_symmetric": (
                        "this loop waits for STABILITY, not for a named decision. A loop that "
                        "waited for DENY would manufacture fail-closed by patience, and one that "
                        "waited for ALLOW would manufacture fail-open")}
        time.sleep(STABILISE_EVERY_S)
    return {"stabilised": False, "decision": None, "phase": phase,
            "seconds": round(time.monotonic() - t0, 1), "decisions_seen": seen,
            "consecutive_confirmations": streak,
            "confirmations_required": STABILISE_CONFIRM_N, "max_wait_s": max_s,
            "why_it_matters": (
                f"no decision repeated {STABILISE_CONFIRM_N} times consecutively within "
                f"{max_s}s, so the request path is non-deterministic under the mutation. That is "
                f"neither of the two answers the seal names and is reported as itself")}


# ---------------------------------------------------------------------------
# the finding
# ---------------------------------------------------------------------------

def finding(legs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One of five named answers, and the reasoning that chose it — in the record, not in a comment.

    Order matters and the controls come FIRST. "The controls did not bracket the measurement" and
    "the engine allowed a violating request" are both ALLOW at the gateway, and consulting the
    decision first would publish a fail-open produced by a probe that never tested anything —
    DEV-P1-18's shape exactly.

    Neither publishable answer is privileged. `FAIL_CLOSED` and `FAIL_OPEN` are decided by the
    same expression read in two directions, and the two NOT_MEASURED branches sit between them
    rather than beside one of them:

      controls not DENY/ALLOW as required  -> CONTROLS_DID_NOT_BRACKET   (nothing was tested)
      the two violating legs disagree      -> SPLIT_OR_INCOHERENT        (path non-deterministic)
      violating ALLOW                      -> FAIL_OPEN                  (a finding)
      violating DENY and benign DENY       -> FAIL_CLOSED                (a finding)
      violating DENY and benign ALLOW      -> REMOVAL_NOT_OBSERVABLE     (evaluation still ran)

    The last row is the one a careless design gets wrong. A violating request still denied while
    a benign one is still allowed means the engine was still DISCRIMINATING BY CONTENT, which
    means evaluation still happened — so the deny is the guardrail working, not a fail-closed
    response to an impossible evaluation. It is also exactly what a content cache would produce.
    Publishing it as fail-closed would credit the service with a property this run did not
    observe.
    """
    pre_v = legs.get(LEG_PRE_VIOLATING, {}).get("decision")
    pre_b = legs.get(LEG_PRE_BENIGN, {}).get("decision")
    post_same = legs.get(LEG_POST_VIOLATING_SAME, {}).get("decision")
    post_new = legs.get(LEG_POST_VIOLATING_NEW, {}).get("decision")
    post_b = legs.get(LEG_POST_BENIGN, {}).get("decision")

    per_leg = {leg: legs.get(leg, {}).get("decision") for leg in LEGS}
    base = {"per_leg": per_leg,
            "controls": {"pre_violating": pre_v, "pre_benign": pre_b},
            "measurement": {"post_violating_same": post_same,
                            "post_violating_new": post_new, "post_benign": post_b}}

    if not (pre_v == "DENY" and pre_b == "ALLOW"):
        return {**base, "finding": FINDING_NO_BRACKET, "publishable": False,
                "why": (f"the controls did not bracket the measurement: with the permission "
                        f"INTACT the violating request read {pre_v} (must be DENY) and the "
                        f"benign request read {pre_b} (must be ALLOW). Without both, an ALLOW "
                        f"after the removal is indistinguishable from a probe that never tested "
                        f"anything, and a DENY is indistinguishable from a forbid that denies "
                        f"everything")}

    if post_same != post_new:
        return {**base, "finding": FINDING_INCOHERENT, "publishable": False,
                "why": (f"the two post-removal violating legs disagreed "
                        f"({LEG_POST_VIOLATING_SAME}={post_same}, "
                        f"{LEG_POST_VIOLATING_NEW}={post_new}). They differ only in WHICH "
                        f"violating item they carry, so a disagreement is either a "
                        f"content-keyed cache answering the repeated item or a path that is not "
                        f"deterministic — neither is one of the two answers the seal names")}

    if post_same == "ALLOW":
        return {**base, "finding": FINDING_FAIL_OPEN, "publishable": True,
                "why": ("with guardrail evaluation impossible, a request the same engine denied "
                        "minutes earlier was ALLOWED — and so was a violating item never sent "
                        "before, so a cache cannot explain it. The engine did not fall back to "
                        "denying what it could not evaluate")}

    if post_same == "DENY" and post_b == "DENY":
        return {**base, "finding": FINDING_FAIL_CLOSED, "publishable": True,
                "why": ("with guardrail evaluation impossible the engine denied the violating "
                        "request AND the benign one. Denying the benign request is what makes "
                        "this attributable: the engine stopped discriminating by content, which "
                        "is what 'cannot evaluate' should look like, rather than continuing to "
                        "evaluate and denying for the ordinary reason")}

    if post_same == "DENY" and post_b == "ALLOW":
        return {**base, "finding": FINDING_NOT_OBSERVABLE, "publishable": False,
                "why": ("the violating request was denied and the benign one allowed, so the "
                        "engine was still DISCRIMINATING BY CONTENT — which means guardrail "
                        "evaluation still ran and the removal was not observable at the request "
                        "path. The deny is the guardrail working, not a response to an "
                        "impossible evaluation. A content-keyed cache would produce exactly "
                        "this, as would a Forward Access Session still holding credentials "
                        "issued before the removal")}

    return {**base, "finding": FINDING_INCOHERENT, "publishable": False,
            "why": (f"the legs do not compose into either answer: violating={post_same}, "
                    f"benign={post_b}. A SPLIT or NOTHING_USABLE leg is reported as itself "
                    f"rather than rounded to whichever side had more trials")}


def guards(*, interlock_engine: dict[str, Any], captured: dict[str, Any],
           forbid: dict[str, Any], legs: dict[str, dict[str, Any]],
           removal_wait: dict[str, Any], window: dict[str, Any],
           restore: dict[str, Any], deletion: dict[str, Any]) -> dict[str, bool]:
    """Every condition under which this case's finding means what it says.

    Separate names because the remedies differ completely: a failed bracket means the instrument
    never worked, an unconfirmed removal means IAM had not converged, a failed restore means the
    testbed is broken and someone has to fix it now.
    """
    pre_v = legs.get(LEG_PRE_VIOLATING, {}).get("decision")
    pre_b = legs.get(LEG_PRE_BENIGN, {}).get("decision")
    post_same = legs.get(LEG_POST_VIOLATING_SAME, {}).get("decision")
    post_new = legs.get(LEG_POST_VIOLATING_NEW, {}).get("decision")
    return {
        "engine_was_quiet_at_start":
            interlock_engine.get("policies_on_engine_at_start") == ["baseline"],
        "role_carried_exactly_its_shipped_document":
            sorted(captured.get("sids") or []) == sorted(EXPECTED_SIDS),
        "forbid_was_active_before_any_leg_ran": forbid.get("status") in POLICY_OK,
        # The control for confound (d), and the discrimination control the fail-closed reading
        # depends on. Both halves, because a forbid that denied everything would make the benign
        # leg's post-removal DENY meaningless.
        "controls_bracketed_the_measurement": pre_v == "DENY" and pre_b == "ALLOW",
        "removal_was_confirmed_by_iam_before_the_window_legs":
            removal_wait.get("reached") is True,
        "every_window_leg_reached_the_gateway":
            bool(legs) and all(legs.get(leg, {}).get("n_reached_gateway", 0) >= 1
                               for leg in WINDOW_LEGS),
        "post_removal_violating_legs_agreed":
            post_same is not None and post_same == post_new,
        "window_stayed_within_its_bound": window.get("within_bound") is True,
        # Not "the put returned 200" but "a fresh GetRolePolicy matched the captured document".
        "document_was_restored_and_verified_byte_for_byte_after_normalisation":
            restore.get("restored") is True,
        "blocking_was_reasserted_after_the_restore":
            legs.get(LEG_RESTORED_VIOLATING, {}).get("decision") == "DENY",
        "probe_policy_was_deleted": deletion.get("deleted") is True,
    }


def residue(*, forbid_created: bool, statement_removed: bool, intent_registered: bool,
            restore: dict[str, Any], deletion: dict[str, Any],
            restore_intent_dropped: bool, sids_at_end: list[str] | None) -> dict[str, Any]:
    """What this run left behind, from a CREATED list and a REMOVED list — plus the STATE.

    The created/removed pair is the `phase1.probe_residue` argument: a mutation whose undo was
    never *attempted* contributes no row to a removals list, so a residue computed from that list
    alone reports zero survivors for exactly the case where one exists.

    The CREATED list is built from what this run actually did, not from what it planned. That
    matters in the branch where the controls failed to bracket: the window never opened, so the
    statement was never removed, and a created list written as a constant would have reported an
    unrestored statement as residue and exited 2 over a run that mutated nothing but its own
    probe policy.

    For this case the decisive term is neither list but a read-back STATE: is the target Sid back
    in the document? A missing statement is residue that no bookkeeping entry describes, and it
    is the residue that breaks every subsequent case in the repo. `sids_at_end is None` (the
    read-back failed) is residue too, not cleanliness — a permission we could not look at is not
    a permission we know is there. The state term is required only when the statement was
    actually removed; a run that never opened the window is not asked to prove it put something
    back.
    """
    created: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    if forbid_created:
        created.append({"id": "policy:forbid", "kind": "agentcore-policy"})
        removed.append({"id": "policy:forbid", "removed": bool(deletion.get("deleted"))})
    if statement_removed:
        created.append({"id": f"statement_removed:{TARGET_SID}", "kind": "iam-statement"})
        removed.append({"id": f"statement_removed:{TARGET_SID}",
                        "removed": bool(restore.get("restored"))})
    if intent_registered:
        created.append({"id": "ledger:f54b_restore_intent", "kind": "ledger-undo-intent"})
        removed.append({"id": "ledger:f54b_restore_intent",
                        "removed": bool(restore_intent_dropped)})
    surviving = [r["id"] for r in removed if not r["removed"]]
    statement_present = (None if sids_at_end is None else TARGET_SID in sids_at_end)
    return {
        "n_created": len(created), "n_removal_attempted": len(removed),
        "n_removed": sum(1 for r in removed if r["removed"]),
        "surviving": surviving, "created": created, "removed": removed,
        "window_opened": statement_removed,
        "statement_present_at_end": statement_present,
        "sids_at_end": sids_at_end,
        "clean": (not surviving
                  and (statement_present is True if statement_removed else True)),
        "why_two_lists": (
            "a mutation whose undo was never ATTEMPTED contributes no row to the removals, so a "
            "residue computed from that list alone reports zero survivors for exactly the case "
            "where one exists"),
        "why_the_state_is_read_back_too": (
            f"the decisive residue here is not a bookkeeping entry: it is {TARGET_ACTION} "
            f"missing from {GW_EXEC_INLINE}, which breaks every guardrail-in-policy case in "
            f"this repo. A failed read-back is residue, not cleanliness"),
    }


def narrative(*, found: dict[str, Any], window: dict[str, Any],
              sdk: str) -> dict[str, str]:
    """The five sentences every payload carries, written so BOTH answers read neutrally.

    In a function so a test can read both branches without faking a run — the fail-open branch
    has no live representative this project can rely on, and a branch first executed on the day
    it fires is a branch nobody has read. There is no "expected" outcome here and no branch
    phrased as a pass: `FAIL_CLOSED` corroborates §4.1's "fail-secure" label for one failure
    mode, `FAIL_OPEN` refutes it, and both are what the seal asked for.
    """
    name = found["finding"]
    per = found["per_leg"]
    if name == FINDING_FAIL_CLOSED:
        reading = (
            f"FAIL-CLOSED for this failure mode. With {TARGET_ACTION} removed from the gateway "
            f"execution role, the engine denied both the violating request and the benign one "
            f"({per}). It stopped discriminating by content, which is what an evaluation that "
            f"cannot run should look like, and §4.1/§9's 'fail-secure' label is corroborated for "
            f"the missing-permission mode specifically — not for the timeout mode, which no "
            f"fault-injection surface in AgentCore can induce")
    elif name == FINDING_FAIL_OPEN:
        reading = (
            f"FAIL-OPEN for this failure mode. With {TARGET_ACTION} removed, a request the same "
            f"engine had denied minutes earlier was ALLOWED, and so was a violating item never "
            f"sent before ({per}). An IAM permission an operator can remove — or fail to grant "
            f"during a migration — therefore silently disables enforcement rather than closing "
            f"the gateway, and §4.1/§9's 'fail-secure' label does not hold for this mode. This "
            f"is the direction §3.3 BP#4 warns is undocumented, measured")
    else:
        reading = (
            f"no answer: {name}. {found['why']} The legs read {per}. Reported rather than "
            f"resolved: this case's seal declares the OUTCOME unknown, which is not a licence to "
            f"pick whichever of the two answers the data leans toward")
    return {
        "verdict_rule": (
            "the sealed kind is RECORDED: the pre-registration declares the outcome unknown and "
            f"BOTH {FINDING_FAIL_CLOSED} and {FINDING_FAIL_OPEN} are findings. There is no pass "
            "condition. What IS gated is attributability, in this order: the controls must "
            "bracket the measurement (violating DENY and benign ALLOW with the permission "
            "intact), the two post-removal violating legs must agree, and — for a DENY — the "
            "benign leg must ALSO be denied, because a violating DENY beside a benign ALLOW "
            "means the engine was still discriminating by content and therefore still "
            "evaluating"),
        "verdict_reading": reading,
        "what_true_does_not_prove": (
            "nothing here is a TRUE. What this measurement does not cover, in either direction: "
            "the TIMEOUT failure mode, which is the one §3.1 and §4.1 actually claim and which "
            "AgentCore exposes no fault-injection surface to induce (claims "
            "C-s3-1-bullet-014-a and C-s4-1-bullet-008-a are excluded for exactly that); any "
            "failure mode of the CEDAR evaluator rather than the guardrails hand-off (F5-4a's "
            "cedar_missing_attr arm); an evaluation that fails INSIDE Bedrock Guardrails rather "
            "than at the IAM boundary; and the standalone ApplyGuardrail path in §3.3, which is "
            "the caller's own API call and whose failure posture the caller owns. A fail-closed "
            "result also says nothing about how long the engine keeps denying — this case "
            "restores the permission within minutes and does not measure a sustained outage"),
        "why_this_matters_operationally": (
            f"this is a permission an operator can remove in one call, forget in a migration, or "
            f"lose to a permissions boundary or an SCP tightening — and §3.1 lists it in a "
            f"bullet without saying what happens when it is absent. The two answers have "
            f"opposite runbooks. Fail-closed means the removal is an outage and belongs on an "
            f"availability alarm; fail-open means it is a silent loss of enforcement and belongs "
            f"on a config-drift alarm, with CloudTrail on PutRolePolicy against the gateway "
            f"execution role. The measured exposure window here was "
            f"{window.get('seconds_without_the_permission')}s against a bound of "
            f"{WINDOW_BOUND_S}s, which is also the number an operator should assume for how long "
            f"a mistake like this can go unnoticed"),
        "expiry": (
            f"a live behavioural measurement, dated by botocore {sdk} and by the run date. Its "
            f"subject is undocumented service behaviour with no contract behind it, so it can "
            f"change without notice and without a release note — this is the class of result "
            f"AWS-BEHAVIOR-CHANGES.md exists for. Re-run before quoting it in a runbook, and "
            f"re-run in particular if the engine gains a configurable failure posture, which "
            f"would make the question a setting rather than a behaviour"),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:            # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)
    n = min(args.n, N_PER_LEG) if args.n else N_PER_LEG
    is_smoke = args.n is not None

    if args.dry_run:
        return P.dry_run_banner(
            CASE,
            ((LEG_PRE_VIOLATING,
              "permission INTACT, violating item V1. Must be DENY — the control that rules out "
              "'the content was never violating'", n),
             (LEG_PRE_BENIGN,
              "permission INTACT, benign item. Must be ALLOW — the control that shows the "
              "forbid discriminates rather than denying everything", n),
             (LEG_POST_VIOLATING_SAME,
              "permission REMOVED, the IDENTICAL V1. The measurement", n),
             (LEG_POST_VIOLATING_NEW,
              "permission REMOVED, a violating item never sent before. The same measurement "
              "with a content cache ruled out", n),
             (LEG_POST_BENIGN,
              "permission REMOVED, the same benign item. The disambiguator: a fail-closed engine "
              "must deny this too, and a DENY here beside an ALLOW means evaluation still ran", n),
             (LEG_RESTORED_VIOLATING,
              "permission RESTORED, V1 again. The seal's 'restore + re-verify'", n)),
            operations={"mcp:tools/call": n * len(LEGS)},
            mutations=MAX_MUTATIONS,
            billable=True,
            extra=(
                f"sealed oracle ({O.BINDINGS[CASE].kind}): {O.oracle_text(CASE)}",
                f"BOTH outcomes are findings: {FINDING_FAIL_CLOSED} and {FINDING_FAIL_OPEN}. "
                f"There is no pass condition in this script, and the payload reads neutrally in "
                f"both directions",
                f"the three NOT_MEASURED answers sit BETWEEN them: {FINDING_NO_BRACKET}, "
                f"{FINDING_INCOHERENT}, {FINDING_NOT_OBSERVABLE} — the last being a violating "
                f"DENY beside a benign ALLOW, which means the engine was still discriminating by "
                f"content and therefore still evaluating",
                f"THE WINDOW: {TARGET_ACTION} is absent from {GW_EXEC_INLINE} on the gateway "
                f"execution role for at most {WINDOW_BOUND_S}s, enforced inside the measurement "
                f"loop. The restore is in a finally (so it survives an exception and a "
                f"KeyboardInterrupt) and a ledger entry whose delete_op is put_role_policy "
                f"restores the permission even after SIGKILL",
                f"the restore is verified by re-READING the document and comparing normalised "
                f"JSON (sort_keys, list order preserved) against the capture, with both sha256s "
                f"recorded. A failed restore is rc=2 with a message naming the role and policy",
                f"IAM propagation is polled through TWO of IAM's own channels — GetRolePolicy and "
                f"SimulatePrincipalPolicy — requiring {PROP_CONFIRM_N} CONSECUTIVE agreements "
                f"({REMOVE_PROP_MAX_S}s bound for the removal, deliberately tight because every "
                f"second is exposure; {RESTORE_PROP_MAX_S}s for the restore)",
                f"the data plane is polled for a STABLE decision, whichever it turns out to be "
                f"({STABILISE_MAX_S}s, {STABILISE_CONFIRM_N} consecutive). A loop waiting for a "
                f"NAMED decision would manufacture the answer by patience",
                f"one guardrail-bearing forbid is created on the SHARED engine (F5-4a's proven "
                f"statement form, HATE / {GUARDRAIL_PATH} / threshold {GUARDRAIL_THRESHOLD}) and "
                f"deleted in a finally. INTERLOCK: refuses to start if any policy other than "
                f"`baseline` is registered in state.json",
                "each leg opens a FRESH MCP session with its own policy_session_id; request text "
                "is sent UNDECORATED, because a marker appended to a violating item could change "
                "the score the guardrail assigns it",
                f"guards, all NOT_MEASURED-on-failure: {', '.join(GUARDS)}",
            ))

    state = T.State.load()
    run_id = state.run_id
    store = EvidenceStore(run_id, FAMILY, CASE)
    store.write_environment()
    fc_admin = A.factory(args.region)
    ac_admin = fc_admin.client("bedrock-agentcore-control")
    iam = fc_admin.iam()
    account_id = A.account_id(fc_admin)

    print(f"{CASE} — route #5: what happens when guardrail evaluation cannot run? "
          f"run_id={run_id} (adopted from the ledger), region={args.region}\n")

    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    gw_role = state.find("iam-role", "gw-exec")
    caller = state.find("iam-role", "caller")
    if not (gw and tgt and gw_role and caller):
        rec = O.not_measured(
            CASE,
            f"the ledger is missing a resource this case needs (gateway={bool(gw)}, "
            f"target={bool(tgt)}, gw-exec role={bool(gw_role)}, caller role={bool(caller)})",
            remedy="run infra/01_iam.py onward (Phase 2) first")
        P.emit(CASE, rec, {"instrument": "not built: incomplete ledger"}, store)
        return 2

    gateway_id = gw.ids["gateway_id"]
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    gateway_url = gw.ids["gateway_url"]
    session_timeout_s = int(gw.ids.get("session_timeout_s", 900))
    engine_id = gw.ids.get("policy_engine_id") or ""
    role_name = gw_role.ids["role_name"]
    role_arn = T.unmask_arn(gw_role.arn, account_id)
    caller_arn = T.unmask_arn(caller.arn, account_id)
    if not engine_id:
        rec = O.not_measured(CASE, "the main gateway has no policy engine in the ledger",
                             remedy="run infra/03_policy_engine.py and infra/04_gateway.py")
        P.emit(CASE, rec, {"instrument": "not built: no engine"}, store)
        return 2

    # The Cedar/gateway action id comes from the LEDGER, not concatenated here: it is
    # `<targetName>___<toolName>`, a function of how infra/05_target.py named the target, and a
    # literal that stopped matching would make every leg read ALLOW for a reason that has nothing
    # to do with the permission.
    action_ids = list(tgt.ids.get("cedar_action_ids") or [])
    action_id = next((a for a in action_ids if a.endswith(f"___{TOOL}")), "")
    if not action_id:
        rec = O.not_measured(
            CASE, f"no `___{TOOL}` action id in the ledger's target record (found {action_ids})",
            remedy="re-run infra/05_target.py")
        P.emit(CASE, rec, {"instrument": "not built: no action id"}, store)
        return 2

    fc_caller = A.factory(args.region, role_arn=caller_arn)

    common: dict[str, Any] = {
        "run_id": run_id, "region": args.region, "is_smoke": is_smoke,
        "ambient_sdk": A.sdk_versions(),
        "instrument": (
            f"{n} MCP tools/call requests per leg through gateway {gateway_id}, against a "
            f"guardrail-bearing forbid on engine {engine_id}, with {TARGET_ACTION} present and "
            f"then absent from {role_name}'s {GW_EXEC_INLINE}"),
        "gateway_id": gateway_id, "policy_engine_id": engine_id, "action_id": action_id,
        "gateway_execution_role": role_name, "inline_policy_edited": GW_EXEC_INLINE,
        "target_sid": TARGET_SID, "target_action": TARGET_ACTION,
        "n_per_leg": n, "legs": list(LEGS), "window_legs": list(WINDOW_LEGS),
        "why_recorded": (
            "the pre-registration declares this outcome unknown. Fail-closed and fail-open are "
            "both findings, neither is a confirmation or a refutation of a prediction this "
            "project made, and this script contains no branch phrased as a pass"),
        "why_the_benign_leg_exists": (
            "it is the disambiguator that makes a DENY attributable. A violating request still "
            "denied is consistent with fail-closed AND with the removal having had no effect on "
            "the request path; if evaluation genuinely cannot run, a benign request has no more "
            "chance of being evaluated than a violating one, so a fail-closed engine must deny "
            "it too. A violating DENY beside a benign ALLOW means the engine was still "
            "discriminating by content — evaluation still ran — and is reported as NOT_MEASURED"),
        "why_two_violating_legs": (
            "they differ only in WHICH violating item they carry. The repeated item satisfies "
            "the seal's 'send a violating request' with the identical request the control "
            "established as denied; the unseen item makes a content-keyed cache unable to "
            "explain an ALLOW. The finding requires both to agree"),
        "no_checkpoint_by_design": (
            "a leg is only meaningful inside the window its permission state defines, and a "
            "resumed process cannot re-enter a window whose mutation has been restored. A "
            "checkpoint would let a later run pair post-restore trials with a removal that no "
            "longer exists"),
    }

    interlock_engine: dict[str, Any] = {}
    captured: dict[str, Any] = {}
    forbid: dict[str, Any] = {}
    legs: dict[str, dict[str, Any]] = {}
    removal: dict[str, Any] = {}
    removal_wait: dict[str, Any] = {}
    restore_wait: dict[str, Any] = {}
    stabilise: dict[str, dict[str, Any]] = {}
    restore: dict[str, Any] = {"restored": False, "attempts": [],
                               "manual_remedy": "the restore never ran"}
    deletion: dict[str, Any] = {"deleted": True, "note": "no probe policy was created"}
    window: dict[str, Any] = {"opened": False, "within_bound": True,
                              "seconds_without_the_permission": None,
                              "bound_s": WINDOW_BOUND_S}
    restore_intent_name = ""
    restore_intent_dropped = False
    statement_removed = False
    config_error = ""
    t_removed: float | None = None
    # Read before the try and held here so the `finally` can re-send the SAME violating item for
    # the seal's "restore + re-verify" without re-reading the corpus — a second read that
    # returned a different first line would make the re-assertion a different experiment from the
    # control it is compared against.
    items: dict[str, dict[str, Any]] = {}

    def _leg(leg: str, text: str, item_id: str) -> dict[str, Any]:
        """One leg, with its own session, closed whatever happens."""
        client = client_for_leg(gateway_url, fc_caller, store, run_id=run_id, leg=leg,
                                session_timeout_s=session_timeout_s)
        try:
            out = probe_leg(client, leg=leg, action_id=action_id, text=text, item_id=item_id,
                            n=n)
        finally:
            client.close()
        legs[leg] = out
        print(f"    {leg:22s} {out['decision']:14s} "
              f"denied={out['n_denied']}/{out['n_usable']} reached={out['n_reached_gateway']}")
        return out

    try:
        interlock_engine = assert_engine_is_quiet(state)
        captured = capture_document(iam, store, role_name=role_name,
                                    policy_name=GW_EXEC_INLINE)
        common["captured_document"] = {k: v for k, v in captured.items()
                                       if k not in ("document", "target_statement")}
        print(f"interlocks: engine carries {interlock_engine['policies_on_engine_at_start']}; "
              f"{role_name}/{GW_EXEC_INLINE} carries Sids {captured['sids']} "
              f"(sha256 {captured['sha256'][:12]})\n")

        violating = corpus_items(VIOLATING_CORPUS, 2)
        benign = corpus_items(BENIGN_CORPUS, 1)
        v1, v2, b1 = violating[0], violating[1], benign[0]
        items.update({"v1": v1, "v2": v2, "b1": b1})
        common["items"] = {
            "violating_repeated": {"id": v1.get("id"), "label": v1.get("label")},
            "violating_unseen": {"id": v2.get("id"), "label": v2.get("label")},
            "benign": {"id": b1.get("id"), "label": b1.get("label")},
            "why_ids_not_text": ("the corpus text is not copied into results/: the items are "
                                 "identified by their corpus ids and the corpus is on disk"),
        }

        forbid = create_forbid(ac_admin, store, state, engine_id=engine_id, run_id=run_id,
                               statement=forbid_statement(gateway_arn, action_id))
        deletion = {"deleted": False, "note": "not yet attempted"}
        print(f"[forbid] {forbid['policy_id']} {forbid['status']}")

        # ---- the controls, with the permission INTACT ---------------------
        print("[controls] permission INTACT")
        _leg(LEG_PRE_VIOLATING, v1["text"], v1.get("id", "v1"))
        _leg(LEG_PRE_BENIGN, b1["text"], b1.get("id", "b1"))

        # Only open the window if the controls bracketed the measurement. Removing a permission
        # from the gateway execution role to collect legs nobody could interpret is exposure
        # bought for nothing.
        if not (legs[LEG_PRE_VIOLATING]["decision"] == "DENY"
                and legs[LEG_PRE_BENIGN]["decision"] == "ALLOW"):
            print("    controls did not bracket the measurement — the permission will NOT be "
                  "removed", file=sys.stderr)
        else:
            # ---- THE WINDOW OPENS ----------------------------------------
            restore_intent_name = register_restore_intent(
                state, role_name=role_name, run_id=run_id,
                target_statement=captured["target_statement"])
            reduced = document_without_sid(captured["document"], TARGET_SID)
            t_removed = time.monotonic()
            removal = remove_statement(iam, store, role_name=role_name,
                                       policy_name=GW_EXEC_INLINE, reduced=reduced)
            statement_removed = True
            window["opened"] = True
            print(f"[window OPEN] {TARGET_ACTION} removed from {role_name}/{GW_EXEC_INLINE}")

            removal_wait = wait_for_iam(iam, store, role_name=role_name,
                                        policy_name=GW_EXEC_INLINE, role_arn=role_arn,
                                        want_present=False, phase="removal",
                                        max_s=REMOVE_PROP_MAX_S)
            print(f"    IAM confirmed absence in {removal_wait['seconds']}s "
                  f"(reached={removal_wait['reached']})")

            stabilise["post_removal"] = wait_for_stable_decision(
                gateway_url, fc_caller, store, action_id=action_id, text=v1["text"],
                run_id=run_id, phase="post-removal")
            print(f"    data plane stabilised on {stabilise['post_removal']['decision']} "
                  f"after {stabilise['post_removal']['seconds']}s "
                  f"(stabilised={stabilise['post_removal']['stabilised']})")

            print("[measurement] permission REMOVED")
            for leg, item in ((LEG_POST_VIOLATING_SAME, v1),
                              (LEG_POST_VIOLATING_NEW, v2),
                              (LEG_POST_BENIGN, b1)):
                if time.monotonic() - t_removed >= WINDOW_BOUND_S:
                    # The bound is enforced, not hoped for. Abandoning a leg loses a
                    # measurement; overstaying leaves a gateway execution role without a
                    # documented permission for longer than this case declared, and the second
                    # is the one that costs somebody else their run.
                    window["within_bound"] = False
                    window["abandoned_legs"] = [
                        l for l in WINDOW_LEGS if l not in legs]
                    print(f"    WINDOW BOUND {WINDOW_BOUND_S}s REACHED — abandoning "
                          f"{window['abandoned_legs']} and restoring now", file=sys.stderr)
                    break
                _leg(leg, item["text"], item.get("id", leg))

    except ConfigError as exc:
        config_error = str(exc)
        print(f"REFUSED: {exc}", file=sys.stderr)
    finally:
        # ---- THE WINDOW CLOSES. This block is the reason the case is runnable. ----
        if statement_removed:
            restore = restore_document(iam, store, captured=captured)
            if t_removed is not None:
                window["seconds_without_the_permission"] = round(
                    time.monotonic() - t_removed, 1)
            window["restored"] = restore["restored"]
            print(f"[window CLOSED] after "
                  f"{window['seconds_without_the_permission']}s; "
                  f"restored={restore['restored']}")
            if restore["restored"]:
                state.drop("iam-inline-policy", "f54b_restore_intent")
                state.write()
                restore_intent_dropped = True
                restore_wait = wait_for_iam(iam, store, role_name=role_name,
                                            policy_name=GW_EXEC_INLINE, role_arn=role_arn,
                                            want_present=True, phase="restore",
                                            max_s=RESTORE_PROP_MAX_S)
                print(f"    IAM confirmed presence in {restore_wait['seconds']}s "
                      f"(reached={restore_wait['reached']})")
            else:
                print(f"    RESTORE FAILED: {restore['manual_remedy']}", file=sys.stderr)

            # The seal's "restore + re-verify" — PREREGISTRATION's restore_verification rule in
            # its own words: "After every mutation: restore, then RE-RUN the blocking assertion.
            # A restore is not assumed to have worked because the API call returned 200."
            #
            # Run only when the forbid is still on the engine to deny against: a re-assertion
            # after the policy had been deleted would read ALLOW and look exactly like a failed
            # restore. The data plane is stabilised first, for the same reason the removal
            # direction is — the grant has its own propagation and an immediate probe would
            # attribute IAM's lag to the restore.
            if restore["restored"] and forbid.get("policy_id") and items.get("v1"):
                stabilise["post_restore"] = wait_for_stable_decision(
                    gateway_url, fc_caller, store, action_id=action_id,
                    text=items["v1"]["text"], run_id=run_id, phase="post-restore")
                print(f"    data plane stabilised on "
                      f"{stabilise['post_restore']['decision']} after "
                      f"{stabilise['post_restore']['seconds']}s")
                try:
                    _leg(LEG_RESTORED_VIOLATING, items["v1"]["text"],
                         items["v1"].get("id", "v1"))
                except Exception as exc:                          # noqa: BLE001
                    # Recorded as an unusable leg, never as a DENY or an ALLOW: a transport
                    # failure during the re-assertion is not evidence about enforcement, and
                    # `blocking_was_reasserted_after_the_restore` fails on it, which is correct.
                    legs[LEG_RESTORED_VIOLATING] = {
                        "leg": LEG_RESTORED_VIOLATING, "decision": "NOTHING_USABLE",
                        "n": 0, "n_denied": 0, "n_allowed": 0, "n_usable": 0,
                        "n_reached_gateway": 0,
                        "error": f"{type(exc).__name__}: {exc}"}

        if forbid.get("policy_id"):
            deletion = delete_forbid(ac_admin, store, state, engine_id=engine_id,
                                     policy_id=forbid["policy_id"])
            if not deletion["deleted"]:
                print(f"    WARNING: the forbid was NOT deleted: {deletion['manual_remedy']}",
                      file=sys.stderr)

        # The end state, read back from IAM. A failed read is recorded as a failed read, never as
        # a restored permission (`feedback_guard_tool_exit_codes`).
        endr = capture(store, "get_role_policy", iam, RoleName=role_name,
                       PolicyName=GW_EXEC_INLINE)
        live_end = (endr.response or {}).get("PolicyDocument") if endr.ok else None
        sids_at_end = ([s.get("Sid") for s in (live_end.get("Statement") or [])]
                       if isinstance(live_end, dict) else None)
        # An intent that was never registered is not residue: the window never opened, so there
        # is nothing for a teardown to replay. Written out rather than folded into the call so
        # "never created" and "created and dropped" are two visible states, not one boolean.
        intent_gone = restore_intent_dropped or not restore_intent_name
        res = residue(forbid_created=bool(forbid.get("policy_id")),
                      statement_removed=statement_removed,
                      intent_registered=bool(restore_intent_name),
                      restore=restore, deletion=deletion,
                      restore_intent_dropped=intent_gone, sids_at_end=sids_at_end)

    found = finding(legs)
    g = guards(interlock_engine=interlock_engine, captured=captured, forbid=forbid, legs=legs,
               removal_wait=removal_wait, window=window, restore=restore, deletion=deletion)
    narr = narrative(found=found, window=window,
                     sdk=A.sdk_versions().get("botocore", "?"))

    detail = {
        **common, **narr,
        "legs": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in legs.items()},
        "leg_rows": {k: v.get("rows") for k, v in legs.items()},
        "finding": found, "findings_possible": list(FINDINGS),
        "publishable_findings": list(PUBLISHABLE_FINDINGS),
        "guards": g, "guards_failed": sorted(k for k, v in g.items() if not v),
        "window": window, "removal": removal, "restore": restore,
        "iam_propagation": {"removal": removal_wait, "restore": restore_wait},
        "data_plane_stabilisation": stabilise,
        "forbid": forbid, "forbid_deletion": deletion,
        "residue": res, "sids_at_end": sids_at_end,
        "restore_intent": {
            "ledger_logical": "f54b_restore_intent",
            "policy_name_it_would_create": restore_intent_name or None,
            "dropped_after_verified_restore": restore_intent_dropped,
            "why": ("a finally does not survive SIGKILL. This ledger entry's delete_op is "
                    "put_role_policy, so infra/99_teardown.py restores the permission from a "
                    "different process — in a deliberately different SHAPE, so the fallback "
                    "announces itself as drift instead of healing silently"),
        },
        "startup_engine_interlock": interlock_engine,
    }

    # ---- the restore is the one failure that overrides everything ---------
    if statement_removed and not restore["restored"]:
        rec = O.not_measured(
            CASE,
            f"THE RESTORE FAILED. The inline policy {GW_EXEC_INLINE!r} on IAM role "
            f"{role_name!r} does not match the document this run captured "
            f"(expected sha256 {restore.get('sha256_expected')}, read back "
            f"{restore.get('sha256_read_back')}). {TARGET_ACTION} may be missing, which breaks "
            f"every guardrail-in-policy case in this repo. Fix it before running anything else: "
            f"`python3 infra/01_iam.py --ensure --fix-drift`",
            legs={k: v.get("decision") for k, v in legs.items()}, residue=res)
        P.emit(CASE, rec, detail, store)
        print(f"\n{CASE}: rc=2 — RESTORE FAILED on {role_name}/{GW_EXEC_INLINE}",
              file=sys.stderr)
        return 2

    if config_error:
        rec = O.not_measured(CASE, config_error,
                             remedy="resolve the precondition and re-run", residue=res)
        P.emit(CASE, rec, {**detail, "config_error": config_error}, store)
        return 2

    if not found["publishable"]:
        rec = O.not_measured(
            CASE, f"{found['finding']}: {found['why']}",
            legs={k: v.get("decision") for k, v in legs.items()}, residue=res)
        P.emit(CASE, rec, detail, store)
        print(f"\n{CASE}: NOT_MEASURED — {found['finding']}", file=sys.stderr)
        return 2

    obs = P.obs_recorded(
        CASE,
        finding=found["finding"], finding_why=found["why"],
        legs={k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in legs.items()},
        guards=g, window=window,
        iam_propagation={"removal": removal_wait, "restore": restore_wait},
        data_plane_stabilisation=stabilise, residue=res,
        n_basis=(f"{n} requests per leg over {len(LEGS)} legs; the reading is all-or-nothing per "
                 f"leg because this is an E-class mechanism and a split leg is a finding, not a "
                 f"rate"))
    # An ATTRIBUTE, not a keyword: `obs_recorded` sweeps surplus keywords into `detail`, which the
    # decision rule never reads (`P._detail` refuses the keyword spelling outright).
    #
    # WHAT `mutation_inverted` MEANS FOR A RECORDED CASE, AND WHY IT IS NEVER SET FALSE HERE.
    # The pre-registration's rule is "a control whose removal does not change the outcome was
    # never load-bearing". Both publishable findings satisfy it, in different legs: fail-open
    # inverts the VIOLATING leg (DENY -> ALLOW) and fail-closed inverts the BENIGN leg
    # (ALLOW -> DENY). So the flag is computed as "at least one leg's decision changed", which is
    # symmetric between the two answers and privileges neither.
    #
    # False is never passed, deliberately. `oracle.evaluate` maps `mutation_inverted is False` to
    # verdict FALSE, and for a case whose seal declares the outcome UNKNOWN that would publish a
    # refutation of a claim the seal does not make. The branch where nothing changed is not a
    # verdict at all — it is an unmeasured instrument — and it is reported above through
    # `O.not_measured` as REMOVAL_NOT_OBSERVABLE_AT_THE_REQUEST_PATH, which is the only way this
    # code path can be reached with no inversion.
    obs.mutation_inverted = bool(
        legs.get(LEG_POST_VIOLATING_SAME, {}).get("decision")
        != legs.get(LEG_PRE_VIOLATING, {}).get("decision")
        or legs.get(LEG_POST_BENIGN, {}).get("decision")
        != legs.get(LEG_PRE_BENIGN, {}).get("decision"))
    # `evaluate` takes the Observation ALONE — the case id travels inside it.
    rec = O.evaluate(obs)
    P.emit(CASE, rec, detail, store)

    print(f"\n{CASE}: {found['finding']}  ->  verdict {rec['verdict']}")
    print(f"legs: " + ", ".join(f"{k}={v.get('decision')}" for k, v in legs.items()))
    print(f"window: {window['seconds_without_the_permission']}s "
          f"(bound {WINDOW_BOUND_S}s)   restore verified: {restore['restored']}")
    print("guards: " + ", ".join(f"{k}={v}" for k, v in g.items()))
    if not all(g.values()):
        print("\nAT LEAST ONE GUARD IS FALSE — the finding above is not publishable as it "
              f"stands; see results/phase1/{CASE}.json", file=sys.stderr)
    if not res["clean"]:
        print(f"\nRESIDUE SURVIVED: {res['surviving']} "
              f"statement_present_at_end={res['statement_present_at_end']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
