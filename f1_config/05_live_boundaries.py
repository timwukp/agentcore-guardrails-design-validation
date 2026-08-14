#!/usr/bin/env python3
"""F1-6 — does STANDARD tier require crossRegionConfig, and CLASSIC not?

    .venv-oracle/bin/python f1_config/05_live_boundaries.py --dry-run
    .venv-oracle/bin/python f1_config/05_live_boundaries.py

Sealed oracle (claims/triage_rules.CASES["F1-6"], kind C, quoted verbatim):

    TRUE if CreateGuardrail with tier=STANDARD and no crossRegionConfig is rejected and
    CLASSIC is accepted without it; FALSE if either succeeds anyway

Sealed method: "paired CreateGuardrail across tier x crossRegionConfig".

WHY THE DESIGN IS A FULL 2x2, NOT THE ORACLE'S TWO CELLS
--------------------------------------------------------
The oracle names two cells: (STANDARD, no crossRegionConfig) rejected and (CLASSIC, no
crossRegionConfig) accepted. This script runs all four cells of tier x crossRegionConfig,
because the two unnamed cells are what distinguish "STANDARD requires crossRegionConfig"
from "crossRegionConfig is required or forbidden generally":

  * (CLASSIC, WITH crossRegionConfig) accepted rules out "the field is CLASSIC-forbidden /
    STANDARD-only", i.e. that the pairing runs the other way too. If it were rejected, the
    honest reading is a hard coupling ("STANDARD iff crossRegionConfig") that the document's
    tier table does not state — reportable, though it does not decide the sealed cells.
  * (STANDARD, WITH crossRegionConfig) accepted rules out "STANDARD is unavailable in this
    account for an unrelated reason" — which would produce the SAME rejection in the
    (STANDARD, absent) cell that the oracle reads as TRUE. Without this control, an account
    limitation is indistinguishable from the claim holding, and the verdict would be about
    the account, not the API. If this control is rejected, the STANDARD-without rejection
    CANNOT be attributed to the missing field and the case is INCONCLUSIVE, not TRUE.

That is the difference between measuring the claim and measuring an account limitation, and
it is enforced in `decide()` rather than stated: a TRUE verdict is unavailable unless the
(STANDARD, present) control was accepted.

WHY BOTH POLICY BLOCKS, NOT ONE
-------------------------------
`tierConfig.tierName` is NOT a top-level CreateGuardrail member. Verified against the
shipped botocore model in `surface_check()` (and re-verified on every run, because a
statement about a model expires with the model): under botocore 1.43.67 it lives on exactly
two blocks — `contentPolicyConfig.tierConfig` and `topicPolicyConfig.tierConfig` — while
`crossRegionConfig` IS top-level with `guardrailProfileIdentifier` as its only (and
required) member. The oracle says "tier=STANDARD" without naming a block, so if the two
blocks disagreed — say contentPolicyConfig STANDARD demanded the field and topicPolicyConfig
STANDARD did not — a one-block design would report whichever answer its block gave and call
it the API's. So the 2x2 runs once per tier-carrying block: 8 probes. The conjunction is
universal over both blocks; one clean counterexample on either block is FALSE ("either
succeeds anyway"), and TRUE requires the pattern to hold on both.

Prior sightings, recorded as priors and not as the measurement: F8-5's smoke evidence
(evidence/smoke20260810T0305Z/f8/F8-5/0003_create_guardrail_err.json) holds ONE
topicPolicyConfig STANDARD-without-crossRegionConfig rejection with the message "Can't
configure guardrail policy tier. Enable cross-Region inference for your guardrail to use
Standard tier." — and that run was confounded twice (its next STANDARD probe drew a
ThrottlingException, and no with-crossRegionConfig control was ever sent). The F3
provisioner (evidence/r20260810T011502Z/f3/F3-00-provision/0001_create_guardrail_ok.json)
holds one ACCEPTED contentPolicyConfig CLASSIC create WITH crossRegionConfig — which is also
the provenance of PROFILE_ID below.

THE ERROR IS THE DATA, AND A REJECTION IS READ, NOT COUNTED
-----------------------------------------------------------
Each probe is one `phase1.create_probe_guardrail` call: nothing raises on a rejection, and
the error code/message/request id ARE the observation. But not every rejection is the
oracle firing. `classify_rejection()` splits rejections into a validation of THIS request
(the tier/cross-Region message above), a throttle, an access denial, a quota, or
unclassified — and `decide()` scores only the first as the claim holding. A
ThrottlingException in the decisive cell, an AccessDenied, a quota refusal, or a
ValidationException whose message names something OTHER than the tier/cross-Region
relationship all force INCONCLUSIVE with the cell and code named, because scoring them as
TRUE would publish the account's weather as the API's contract. Both of F8-5's confounders
are also avoided, not just detected: crossRegionConfig is supplied where the cell calls for
it, and the calls are paced (PACE_S beyond the limiter's self-imposed 2/s, plus a backoff
retry on throttle — F8-5 earned its ThrottlingException at the bare limiter rate).

WHAT IS HELD CONSTANT
---------------------
Within a block, the four cells differ ONLY in `tierName` and in the presence of
`crossRegionConfig` (asserted by the offline tests): same minimal policy config, same
name pattern, same description, same tags. The topic definition is far below the CLASSIC
200-char limit and the content filter uses one MEDIUM/MEDIUM VIOLENCE filter, so neither
F8-5's length boundary nor the all-NONE constraint can fire. The description is under the
model's 200-char maximum (the shared helper truncates it anyway — see
lib/tests/test_probe_guardrail.py for why an over-long description would read as the
boundary holding).

n, AND WHY IT IS 8 AND NOT 0
----------------------------
`O.planned_n("F1-6")` is None (the binding names no sample-size cell), so there is no
sealed n to fall short of. `obs_existence` still requires an explicit n, defined as "the
number of trials the conjunction was evaluated over". F1-4 passes n=0 because its probes
are ParamValidator runs against a shape — no service trial exists. F1-6's probes are live
service responses, one per cell, so n is the count of cells actually read: 8. Eight
deterministic control-plane probes, not trials against a rate; no power claim attaches.

TEARDOWN AND RESIDUE
--------------------
Every probe is tagged via `A.tags_for(run_id, expires_at)` and every accepted probe is
deleted in a `finally` via `phase1.delete_probe_guardrails`; residue is computed by
`phase1.probe_residue` from BOTH lists and reported per guardrail id, never as one bool.
This script creates only its own `grx-gr-f1-6-*` probes. It never touches the 3 DRAFT
guardrails, the 6 READY gateways, the 2 abandoned policy engines, the `nopolicy` gateway,
any `harness_*`/`uitestagent_*` resource, or results/phase1_guardrails.json.

DEFERRED CASES — DEFERRED, NOT DECIDED
--------------------------------------
`f1_config/02_model_surface.py` names this file as the successor for four more live-call
cases: F1-10 (tier x topic-definition length), F1-11 (asymmetric config then GetGuardrail
read-back), F1-12 (stream processing mode tokens and the omitted default), F1-13
(ApplyGuardrail character limits) — and F1-20 (InvokeGuardrailChecks at 10/11 blocks) also
points here. Those five are DEFERRED from this file, not decided by it, and this script
deliberately emits NOTHING for them: 02_model_surface.py already wrote each an
INCONCLUSIVE record naming this successor, and a second record from a script that did not
measure them would overwrite a truthful deferral with another one — while a case with no
file in results/phase1/ at all is indistinguishable from a case nobody triaged. The cell
machinery below (probe/read/classify/decide separated from transport) is shaped so those
cases slot in as additional cell tables without touching F1-6's.

EXIT CODES (repo convention): rc reports whether the test RAN, never whether the document
was right. rc=0: every cell read, verdict emitted, all probes deleted. rc=2: nothing
measured (surface moved, client-side enforcement, a confounded decisive cell, an
incomplete cell table) or residue survived. rc=1: an unclassified outcome.

EXPIRY: the model facts are dated by the pinned botocore (recorded per run in the payload);
a later model that moves tierConfig or changes crossRegionConfig's members flips
`surface_check()` to a refusal, and the behaviour change belongs in AWS-BEHAVIOR-CHANGES.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                              # noqa: E402
import oracle as O                                                  # noqa: E402
import phase1 as P                                                  # noqa: E402
import testbed as T                                                 # noqa: E402
from evidence import EvidenceStore                                  # noqa: E402

FAMILY = "f1"
CASE = "F1-6"

# Named so `test_deferred_cases_are_named_and_not_emitted` can pin the promise in the
# docstring: these get NO record from this script. 02_model_surface.py owns their deferral
# records and names this file as successor (F1-10/11/12/13 explicitly; F1-20 also).
DEFERRED = ("F1-10", "F1-11", "F1-12", "F1-13", "F1-20")

# The two CreateGuardrail policy blocks that carry a tierConfig, per the shipped model
# (surface_check() re-verifies this every run). wordPolicyConfig, sensitiveInformation-
# PolicyConfig and contextualGroundingPolicyConfig carry none.
BLOCKS = ("contentPolicyConfig", "topicPolicyConfig")
BLOCK_SLUG = {"contentPolicyConfig": "cf", "topicPolicyConfig": "tp"}

TIERS = ("CLASSIC", "STANDARD")

# The known-good guardrail profile identifier, from this project's own evidence and not
# from memory: evidence/r20260810T011502Z/f3/F3-00-provision/0001_create_guardrail_ok.json
# is an ACCEPTED CreateGuardrail whose params carry exactly this value (three sibling
# records in the same provisioning run carry it too). It also matches the model's
# GuardrailCrossRegionConfig pattern under botocore 1.43.67.
PROFILE_ID = "us.guardrail.v1:0"
PROFILE_ID_PROVENANCE = (
    "evidence/r20260810T011502Z/f3/F3-00-provision/0001_create_guardrail_ok.json — an "
    "accepted CreateGuardrail whose crossRegionConfig.guardrailProfileIdentifier is this "
    "value; not invented for this run")

# Constant probe content, held identical across every cell of a block so that tierName and
# crossRegionConfig presence are the ONLY manipulated variables. The topic definition is
# ~60 chars — far below the CLASSIC 200 limit F8-5 measured — so a length rejection cannot
# masquerade as a tier rejection. The single MEDIUM/MEDIUM filter clears the documented
# "at least one strength not NONE" constraint (phase1.UNREACHABLE_STRENGTHS).
TOPIC_DEFINITION = "Questions about the internal validation harness probe topic."
CONTENT_FILTER = {"type": "VIOLENCE", "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"}

# Pacing. The limiter's CreateGuardrail entry is a SELF-IMPOSED 2/s (lib/awsclients.py),
# and F8-5's smoke run drew a ThrottlingException at that spacing on its fourth create —
# one of the two confounders this design exists to avoid. So each create waits PACE_S on
# top of the limiter, and a throttled probe is retried after THROTTLE_BACKOFF_S up to
# THROTTLE_RETRIES times before it is declared a confound. Avoid first, detect second.
PACE_S = 3.0
THROTTLE_RETRIES = 2
THROTTLE_BACKOFF_S = 20.0

# Rejection classes. Only `tier_requires_cross_region` may be scored as the claim holding
# in the (STANDARD, absent) cell: it is the service validating THIS request's tier against
# THIS request's missing field. Everything in CONFOUND_CLASSES is a statement about the
# account, the harness's pacing, or a message nobody has read — and `other_validation` is
# decisive-cell-confounding too (see classify_rejection).
TIER_XREGION = "tier_requires_cross_region"
CONFOUND_CLASSES = frozenset({"throttle", "access", "quota", "unclassified"})


# ---------------------------------------------------------------------------
# pure functions — the offline-testable core
# ---------------------------------------------------------------------------

def cells() -> list[dict[str, Any]]:
    """The 8 probe cells: 2 blocks x 2 tiers x crossRegionConfig {absent, present}.

    `expect` is the document's prediction (§3.4 tier table), kept beside the observation in
    every reading — F8-5's `read_probe` pattern. `rules_out` is why each cell is in the
    design at all; the two the oracle does not name are the confound discriminators.
    """
    out: list[dict[str, Any]] = []
    for block in BLOCKS:
        for tier in TIERS:
            for xr in (False, True):
                expect = "rejected" if (tier == "STANDARD" and not xr) else "accepted"
                if tier == "STANDARD" and not xr:
                    rules_out = ("the oracle's TRUE cell: STANDARD without the field must "
                                 "be rejected")
                elif tier == "CLASSIC" and not xr:
                    rules_out = ("the oracle's other named cell: CLASSIC must be accepted "
                                 "without the field")
                elif tier == "CLASSIC":
                    rules_out = ("control, unnamed by the oracle: acceptance rules out "
                                 "'crossRegionConfig is forbidden outside STANDARD', i.e. "
                                 "that the field is a hard STANDARD-only switch rather "
                                 "than a STANDARD prerequisite")
                else:
                    rules_out = ("control, unnamed by the oracle: acceptance rules out "
                                 "'STANDARD is unavailable in this account for an "
                                 "unrelated reason', which would produce the same "
                                 "rejection the oracle reads as TRUE. Without it a TRUE "
                                 "verdict measures the account, not the claim")
                out.append({
                    "block": block,
                    "tier": tier,
                    "cross_region": xr,
                    "label": f"{BLOCK_SLUG[block]}-{tier.lower()}-{'xr' if xr else 'noxr'}",
                    "expect": expect,
                    "rules_out": rules_out,
                })
    return out


def config_for(cell: dict[str, Any]) -> dict[str, Any]:
    """The CreateGuardrail config for one cell.

    tierConfig goes ON the cell's policy block (it is not a top-level member);
    crossRegionConfig goes at the TOP level (it is not a block member). Everything else is
    the block's constant minimal config, so the two manipulated variables are the only
    difference between any two cells of a block — the property the offline test pins.
    """
    if cell["block"] == "contentPolicyConfig":
        block_cfg: dict[str, Any] = {
            "filtersConfig": [dict(CONTENT_FILTER)],
            "tierConfig": {"tierName": cell["tier"]},
        }
    else:
        block_cfg = {
            "topicsConfig": [{"name": "F1_6_Probe",
                              "definition": TOPIC_DEFINITION,
                              "type": "DENY"}],
            "tierConfig": {"tierName": cell["tier"]},
        }
    cfg: dict[str, Any] = {cell["block"]: block_cfg}
    if cell["cross_region"]:
        cfg["crossRegionConfig"] = {"guardrailProfileIdentifier": PROFILE_ID}
    return cfg


def classify_rejection(error_code: str | None, error_message: str | None) -> str:
    """What KIND of rejection this was. Called only on rejections.

    Classes:
      tier_requires_cross_region — a ValidationException whose message names the
          tier/cross-Region relationship. The one class that may be scored as the claim
          holding; the reference message is on the record in F8-5's evidence ("Can't
          configure guardrail policy tier. Enable cross-Region inference for your
          guardrail to use Standard tier.").
      other_validation — a ValidationException about something ELSE. NOT scored as the
          claim holding in the decisive cell: a rejection whose message nobody has read is
          the MODE_SCAN_FALSE_POSITIVES lesson from 02_model_surface.py — being wrong
          loudly beats being right silently.
      throttle / access / quota — the account or the harness's pacing, not this request's
          validity. F8-5's STANDARD half was confounded by exactly the first of these.
      unclassified — an error code this table does not anticipate; forces INCONCLUSIVE
          with the code named rather than being binned by guess.
    """
    code = (error_code or "").strip()
    msg = (error_message or "").lower()
    if not code:
        raise ValueError("classify_rejection is for rejections; an accepted probe has no "
                         "error code and nothing to classify")
    if code in ("ThrottlingException", "TooManyRequestsException",
                "RequestLimitExceeded") or "too many requests" in msg:
        return "throttle"
    if code in ("AccessDeniedException", "UnauthorizedException") \
            or "not authorized" in msg:
        return "access"
    if code in ("ServiceQuotaExceededException", "LimitExceededException") \
            or "quota" in msg:
        return "quota"
    if code == "ValidationException":
        if ("cross-region" in msg or "cross region" in msg) and "tier" in msg:
            return TIER_XREGION
        return "other_validation"
    return "unclassified"


def read_cell(p: P.ProbeGuardrail) -> dict[str, Any]:
    """One cell's reading, with `expected` kept beside `observed` (F8-5's read_probe).

    `matches_expected` is NOT the verdict — the verdict is `decide()`'s conjunction — but
    it is what lets a reader see WHICH cell of a FALSE broke, and `classification` is what
    keeps a throttle from being read as the boundary holding.
    """
    observed = "accepted" if p.accepted else "rejected"
    return {
        "label": p.label, "name": p.name,
        "block": p.detail["block"], "tier": p.detail["tier"],
        "cross_region": p.detail["cross_region"],
        "expect": p.detail["expect"], "observed": observed,
        "accepted": p.accepted,
        "matches_expected": observed == p.detail["expect"],
        "classification": None if p.accepted
        else classify_rejection(p.error_code, p.error_message),
        "guardrail_id": p.guardrail_id,
        "error_code": p.error_code, "error_message": p.error_message,
        "http_status": p.http_status, "request_id": p.request_id,
        "evidence": p.evidence,
        "attempts": p.detail.get("attempt", 1),
    }


def decide(readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold 8 cell readings into (measured?, observed?) with every confound named.

    Per block, in precedence order:
      fails      — a CLEAN counterexample: (STANDARD, absent) accepted ("succeeds
                   anyway"), or (CLASSIC, absent) rejected by a validation while
                   (CLASSIC, present) was accepted (so the rejection is attributable to
                   the field's absence and CLASSIC is NOT accepted without it).
      confounded — a decisive cell whose outcome cannot be attributed to the claim: a
                   throttle/access/quota/unclassified rejection in a decisive cell, an
                   unread ValidationException in the (STANDARD, absent) cell, a
                   (STANDARD, present) control that was itself rejected (account
                   limitation indistinguishable from the claim), or both CLASSIC cells
                   rejected (the base config is refused regardless of the manipulation).
      holds      — all four cells clean and in the claimed pattern.

    Case level: any block `fails` -> observed=False, measured=True (a clean counterexample
    decides a universally quantified conjunction even if the other block is confounded);
    else any block `confounded` -> measured=False (TRUE is not available through a
    confound); else observed=True. A confound can never be promoted to the claim holding —
    that is the invariant the offline tests mutate against.
    """
    by = {(r["block"], r["tier"], r["cross_region"]): r for r in readings}
    per_block: dict[str, Any] = {}
    confounds: list[str] = []
    counterexamples: list[str] = []
    notes: list[str] = []

    for block in BLOCKS:
        got = {k: by.get((block,) + k) for k in
               (("STANDARD", False), ("STANDARD", True),
                ("CLASSIC", False), ("CLASSIC", True))}
        missing = [k for k, v in got.items() if v is None]
        if missing:
            c = (f"{block}: cell(s) {missing} were never read; a conjunction evaluated "
                 f"over a partial table is a verdict over a smaller quantifier than the "
                 f"sealed text names")
            confounds.append(c)
            per_block[block] = {"result": "confounded", "why": [c]}
            continue
        std_no = got[("STANDARD", False)]
        std_with = got[("STANDARD", True)]
        cl_no = got[("CLASSIC", False)]
        cl_with = got[("CLASSIC", True)]

        fails: list[str] = []
        conf: list[str] = []

        # -- the (STANDARD, absent) cell: the oracle's TRUE cell ------------------------
        if std_no["accepted"]:
            fails.append(
                f"{block}: STANDARD without crossRegionConfig was ACCEPTED "
                f"(request-id {std_no['request_id']}) — the oracle's 'succeeds anyway'")
        else:
            cls = std_no["classification"]
            if cls in CONFOUND_CLASSES:
                conf.append(
                    f"{block}: the STANDARD-without-crossRegionConfig rejection is "
                    f"{cls} ({std_no['error_code']}), a statement about the account or "
                    f"the harness's pacing, not a validation of this request — it must "
                    f"not be scored as the claim holding")
            elif cls != TIER_XREGION:
                conf.append(
                    f"{block}: STANDARD without crossRegionConfig was rejected with a "
                    f"ValidationException whose message does not name the "
                    f"tier/cross-Region relationship: "
                    f"{(std_no['error_message'] or '')[:160]!r}. A rejection nobody has "
                    f"read must not be scored as the claim holding")
            elif not std_with["accepted"]:
                conf.append(
                    f"{block}: STANDARD WITH crossRegionConfig was ALSO rejected "
                    f"({std_with['error_code']}, class "
                    f"{std_with['classification']}), so the STANDARD-without rejection "
                    f"cannot be attributed to the missing field rather than to STANDARD "
                    f"being unavailable in this account for an unrelated reason")

        # -- the (CLASSIC, absent) cell: the oracle's other named cell ------------------
        if not cl_no["accepted"]:
            cls = cl_no["classification"]
            if cls in CONFOUND_CLASSES:
                conf.append(
                    f"{block}: the CLASSIC-without-crossRegionConfig rejection is {cls} "
                    f"({cl_no['error_code']}); the cell was not measured")
            elif cl_with["accepted"]:
                fails.append(
                    f"{block}: CLASSIC without crossRegionConfig was REJECTED "
                    f"({cl_no['error_code']}: {(cl_no['error_message'] or '')[:120]!r}) "
                    f"while CLASSIC WITH it was accepted — CLASSIC is not accepted "
                    f"without the field, refuting the oracle's second conjunct")
            else:
                conf.append(
                    f"{block}: BOTH CLASSIC cells were rejected, so the block's base "
                    f"config is refused regardless of the manipulated variables; the "
                    f"rejection is about the config, not the claim")

        # -- the (CLASSIC, present) control: interpretive only --------------------------
        if not cl_with["accepted"]:
            notes.append(
                f"{block}: CLASSIC WITH crossRegionConfig was rejected "
                f"({cl_with['error_code']}, class {cl_with['classification']}). This "
                f"does not decide the sealed cells, but if it is a validation it means "
                f"the field is a hard STANDARD-only switch, not merely a STANDARD "
                f"prerequisite — a tighter coupling than the tier table states")

        result = "fails" if fails else ("confounded" if conf else "holds")
        per_block[block] = {"result": result, "why": fails or conf or
                            [f"all four cells clean and in the claimed pattern; the "
                             f"STANDARD rejection's class is {TIER_XREGION} and the "
                             f"STANDARD-with control was accepted"]}
        counterexamples.extend(fails)
        confounds.extend(conf)

    results = [per_block[b]["result"] for b in BLOCKS if b in per_block]
    if counterexamples:
        measured, observed = True, False
        reason = ("a clean counterexample decides the universally quantified "
                  "conjunction: " + "; ".join(counterexamples))
    elif "confounded" in results:
        measured, observed = False, None
        reason = ("a decisive cell was confounded and TRUE is not available through a "
                  "confound: " + "; ".join(confounds))
    else:
        measured, observed = True, True
        reason = ("on both tier-carrying blocks, STANDARD without crossRegionConfig was "
                  "rejected with the tier/cross-Region validation, STANDARD with it was "
                  "accepted (ruling out an account limitation), and both CLASSIC cells "
                  "were accepted")
    return {"measured": measured, "observed": observed, "per_block": per_block,
            "confounds": confounds, "counterexamples": counterexamples,
            "notes": notes, "reason": reason}


def exit_code(*, n_read: int, n_cells: int, measured: bool, residue_clean: bool,
              verdict: str | None) -> int:
    """rc reports whether the test RAN, never whether the document was right.

    0 — every cell read, a decisive verdict emitted, every created probe deleted.
    2 — nothing measured (partial cell table, confounded decisive cell) or residue
        survived: a surviving probe guardrail is a teardown failure this run owns,
        whatever the verdict said.
    1 — an unclassified outcome (measured, complete, clean, yet no decisive verdict —
        a state decide() should make unreachable; if reached, it must be loud).
    """
    if n_read != n_cells:
        return 2
    if not residue_clean:
        return 2
    if not measured:
        return 2
    if verdict in (O.TRUE, O.FALSE):
        return 0
    return 1


# ---------------------------------------------------------------------------
# instrument checks — the model is part of the result
# ---------------------------------------------------------------------------

def surface_check() -> dict[str, Any]:
    """Verify the shipped model still has the surface this design manipulates.

    Read via `A.service_model` (no client, no credentials, no socket). The claims this
    script's docstring makes about the model — tierConfig on exactly the two BLOCKS,
    crossRegionConfig top-level and optional with guardrailProfileIdentifier its sole
    required member — are re-derived here on every run and recorded with the SDK version,
    because a statement about a model expires with the model. A model that moved would be
    a behaviour change for AWS-BEHAVIOR-CHANGES.md, and this instrument refuses to run
    against a surface it was not designed for.
    """
    m = A.service_model("bedrock")
    s = m.operation_model("CreateGuardrail").input_shape
    problems: list[str] = []
    facts: dict[str, Any] = {"sdk": A.sdk_versions()}

    xr = s.members.get("crossRegionConfig")
    facts["crossRegionConfig_top_level"] = xr is not None
    facts["crossRegionConfig_required_top_level"] = "crossRegionConfig" in s.required_members
    if xr is None:
        problems.append("crossRegionConfig is not a top-level CreateGuardrail member")
    else:
        facts["crossRegionConfig_members"] = sorted(xr.members)
        facts["crossRegionConfig_required_members"] = sorted(xr.required_members)
        if sorted(xr.members) != ["guardrailProfileIdentifier"]:
            problems.append(f"crossRegionConfig members are {sorted(xr.members)}, not "
                            f"exactly ['guardrailProfileIdentifier']")
    if facts["crossRegionConfig_required_top_level"]:
        problems.append("crossRegionConfig became REQUIRED at the top level: the absent "
                        "cells would be rejected by ParamValidator before reaching the "
                        "service, and every 'rejected' would be a fact about the SDK")

    tier_blocks = []
    for name, member in s.members.items():
        tc = getattr(member, "members", {}).get("tierConfig") \
            if hasattr(member, "members") else None
        if tc is not None:
            tier_blocks.append(name)
            enum = list(getattr(tc.members.get("tierName"), "enum", []) or [])
            facts[f"{name}.tierConfig.tierName_enum"] = enum
            if sorted(enum) != sorted(TIERS):
                problems.append(f"{name}.tierConfig.tierName enumerates {enum}, not "
                                f"{list(TIERS)}")
    facts["tier_carrying_blocks"] = sorted(tier_blocks)
    if sorted(tier_blocks) != sorted(BLOCKS):
        problems.append(f"tierConfig now lives on {sorted(tier_blocks)}, not on "
                        f"{sorted(BLOCKS)}; the per-block design no longer covers the "
                        f"tier surface")
    # Recorded because the docstring asserts it: the tier is NOT a top-level member, so a
    # design that set a top-level tierName would be manipulating a field that isn't there.
    facts["tierConfig_is_top_level"] = "tierConfig" in s.members
    if facts["tierConfig_is_top_level"]:
        problems.append("tierConfig became a TOP-LEVEL member; the per-block design no "
                        "longer manipulates the only tier surface")
    facts["ok"] = not problems
    facts["problems"] = problems
    return facts


def client_side_check() -> dict[str, Any]:
    """Does ParamValidator reject any of the 8 requests before they leave the process?

    F8-5's re-check, re-derived for this surface: botocore enforces required members, so
    if a future model made crossRegionConfig (or a tierConfig sibling) required, the
    absent cells would be rejected in process and every 'rejected' below would be a
    client-side rejection reported as a service boundary. Re-run live before any
    mutating call; recorded either way.
    """
    from botocore.validate import ParamValidator
    shape = A.service_model("bedrock").operation_model("CreateGuardrail").input_shape
    v = ParamValidator()
    results: dict[str, str] = {}
    for cell in cells():
        params = {"name": "grx-clientside-probe",
                  "blockedInputMessaging": "x", "blockedOutputsMessaging": "x",
                  **config_for(cell)}
        report = v.validate(params, shape)
        results[cell["label"]] = ("client-side OK" if not report.has_errors()
                                  else report.generate_report())
    enforced = any(r != "client-side OK" for r in results.values())
    return {"param_validator": results,
            "client_side_rejects_any_cell": enforced,
            "instrument_is_sound": not enforced,
            "sdk": A.sdk_versions()}


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def run_cell(client, store, lim, cell: dict, *, tags: list[dict], run_id: str,
             sleep=time.sleep) -> list[P.ProbeGuardrail]:
    """One cell: create (paced), retry only on throttle, return every attempt.

    Every attempt is returned — not just the last — because a throttled attempt that
    somehow created a resource must still reach the teardown list. The READING is the
    last attempt; the retries exist to avoid F8-5's throttle confound, not to erase it
    (the attempt count travels in the reading).
    """
    attempts: list[P.ProbeGuardrail] = []
    for attempt in range(1, THROTTLE_RETRIES + 2):
        sleep(PACE_S)
        p = P.create_probe_guardrail(
            client, store, lim,
            case_id=CASE,
            label=cell["label"],
            name=f"grx-gr-f1-6-{cell['label']}-{run_id}",
            description=f"F1-6 tier x crossRegionConfig probe: {cell['label']}",
            tags=tags,
            config=config_for(cell),
            block=cell["block"], tier=cell["tier"],
            cross_region=cell["cross_region"], expect=cell["expect"],
            attempt=attempt)
        attempts.append(p)
        if p.accepted or classify_rejection(p.error_code, p.error_message) != "throttle":
            break
        if attempt <= THROTTLE_RETRIES:
            sleep(THROTTLE_BACKOFF_S)
    return attempts


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _dry_run() -> int:
    pr = cells()
    rc = P.dry_run_banner(
        CASE,
        [(c["label"],
          f"CreateGuardrail {c['block']} tier={c['tier']} "
          f"crossRegionConfig={'PRESENT' if c['cross_region'] else 'ABSENT'}", 1)
         for c in pr],
        operations={"CreateGuardrail": len(pr)},
        mutations=len(pr), billable=False,
        extra=[
            "",
            "billable: $0.00 — CreateGuardrail/DeleteGuardrail are CONTROL PLANE; no "
            "model is invoked and no text units exist to bill",
            "",
            "per-cell prediction (the document's §3.4 tier table):",
            *[f"  {c['label']:16s} sent: {c['block']}.tierConfig.tierName={c['tier']}, "
              f"crossRegionConfig "
              f"{'= {guardrailProfileIdentifier: ' + PROFILE_ID + '}' if c['cross_region'] else 'OMITTED'}"
              f"   predict: {c['expect'].upper()}"
              for c in pr],
            "",
            f"plus up to {sum(1 for c in pr if c['expect'] == 'accepted')} DeleteGuardrail "
            f"calls in the teardown finally — 'up to', because a rejected probe created "
            f"nothing to delete",
            f"the 2x2 runs on BOTH tier-carrying blocks ({', '.join(BLOCKS)}): the oracle "
            f"says 'tier=STANDARD' without naming a block, and a one-block design would "
            f"report its block's answer as the API's",
            "the two cells the oracle does not name are confound discriminators: "
            "STANDARD-with-crossRegionConfig accepted rules out an account limitation "
            "producing the same rejection TRUE reads on; CLASSIC-with rules out a hard "
            "STANDARD-only coupling",
            f"crossRegionConfig.guardrailProfileIdentifier = {PROFILE_ID!r}, from "
            f"{PROFILE_ID_PROVENANCE}",
            f"pacing: {PACE_S}s between creates on top of the limiter's self-imposed "
            f"2/s, throttle retried up to {THROTTLE_RETRIES}x after {THROTTLE_BACKOFF_S}s "
            f"— F8-5's STANDARD half was confounded by a ThrottlingException at the bare "
            f"limiter rate",
            "a rejection is READ, not counted: throttle/access/quota/unclassified in a "
            "decisive cell forces INCONCLUSIVE — an account-limitation rejection must "
            "not be scored as the claim holding",
            f"deferred, NOT decided, and deliberately emitting nothing here: "
            f"{', '.join(DEFERRED)} (02_model_surface.py owns their deferral records "
            f"and names this file as successor)",
            "every probe tagged via A.tags_for; every created guardrail deleted in a "
            "finally; residue per guardrail id. Touches nothing else in the account",
        ])
    return rc


def main(argv: list[str] | None = None) -> int:                      # noqa: C901
    ap = argparse.ArgumentParser(
        prog=CASE, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print every cell, what is sent, what is predicted, and the "
                         "billable line; make no AWS call")
    ap.add_argument("--region", default=A.MAIN_REGION)
    ap.add_argument("--state", default=None,
                    help="path to the testbed ledger (default: the project state.json)")
    ap.add_argument("--evidence-root", default=None)
    args = ap.parse_args(argv)

    if args.dry_run:
        return _dry_run()

    state = T.State.load(Path(args.state) if args.state else None)
    run_id = state.run_id
    store = EvidenceStore(run_id, FAMILY, CASE,
                          root=Path(args.evidence_root) if args.evidence_root else None)
    store.write_environment()

    common: dict[str, Any] = {
        "run_id": run_id, "region": args.region, "is_smoke": False,
        "billable_calls": 0,
        "billable_note": ("CreateGuardrail and DeleteGuardrail are control-plane calls "
                          "and bill no text units; this case sends no ApplyGuardrail and "
                          "invokes no model"),
        "instrument": ("paired CreateGuardrail across tier x crossRegionConfig, on both "
                       "tier-carrying policy blocks; the error branch of each response "
                       "IS the observation, and each rejection is classified before it "
                       "may count"),
        "profile_id": PROFILE_ID,
        "profile_id_provenance": PROFILE_ID_PROVENANCE,
        "deferred_not_decided": {
            "cases": list(DEFERRED),
            "note": ("named as this file's successors by 02_model_surface.py; their "
                     "deferral records exist there and NOTHING is emitted for them "
                     "here, because a record from a script that did not measure them "
                     "would overwrite a truthful deferral")},
    }

    # -- instrument first: a probe against a moved surface measures nothing -----------
    sc = surface_check()
    common["surface_check"] = sc
    common["model_facts_dated_by"] = f"botocore {sc['sdk']['botocore']}"
    print(f"{CASE} — tier x crossRegionConfig, run_id={run_id} region={args.region}")
    print(f"  model (botocore {sc['sdk']['botocore']}): tierConfig on "
          f"{sc.get('tier_carrying_blocks')}, crossRegionConfig top-level "
          f"(required={sc['crossRegionConfig_required_top_level']}), members "
          f"{sc.get('crossRegionConfig_members')}")
    if not sc["ok"]:
        print(f"FATAL: the shipped model no longer carries the surface this design "
              f"manipulates: {sc['problems']}. A behaviour change belongs in "
              f"AWS-BEHAVIOR-CHANGES.md; this instrument refuses to guess.",
              file=sys.stderr)
        rec = O.not_measured(
            CASE, f"the CreateGuardrail model surface moved under botocore "
                  f"{sc['sdk']['botocore']}: {'; '.join(sc['problems'])}",
            surface_check=sc)
        P.emit(CASE, rec, {**common, "mutations": 0}, store)
        return 2

    cs = client_side_check()
    common["client_side_check"] = cs
    if cs["client_side_rejects_any_cell"]:
        print("FATAL: ParamValidator rejects at least one cell client-side, so that "
              "request never reaches the service and its 'rejected' would be a fact "
              "about the SDK reported as a service boundary.", file=sys.stderr)
        rec = O.not_measured(
            CASE, "botocore rejects at least one probe cell client-side; the instrument "
                  "cannot measure a SERVER boundary",
            client_side_check=cs)
        P.emit(CASE, rec, {**common, "mutations": 0}, store)
        return 2

    expires = (datetime.now(timezone.utc) + timedelta(hours=2)) \
        .replace(microsecond=0).isoformat()
    tags = [{"key": k, "value": v}
            for k, v in sorted(A.tags_for(run_id, expires).items())]
    client = A.factory(args.region).bedrock()
    lim = A.limiter()

    pr = cells()
    probes_made: list[P.ProbeGuardrail] = []
    readings: list[dict[str, Any]] = []
    deletions: list[dict[str, Any]] = []
    try:
        for cell in pr:
            attempts = run_cell(client, store, lim, cell, tags=tags, run_id=run_id)
            probes_made.extend(attempts)
            r = read_cell(attempts[-1])
            r["attempts"] = len(attempts)
            readings.append(r)
            mark = "ok " if r["matches_expected"] else "XX "
            print(f"  {mark}{r['label']:18s} -> {r['observed']}"
                  + (f" ({r['error_code']}: {r['classification']})"
                     if r["error_code"] else "")
                  + f"   request-id {r['request_id']}"
                  + (f"   [{len(attempts)} attempts]" if len(attempts) > 1 else ""))
    finally:
        # Over probes_made, not readings: a probe that created a guardrail and then raised
        # while being READ would be absent from readings and its guardrail would survive.
        if any(x.guardrail_id for x in probes_made):
            print(f"\ndeleting "
                  f"{sum(1 for x in probes_made if x.guardrail_id)} probe guardrail(s)...")
            deletions = P.delete_probe_guardrails(client, store, lim, probes_made)
            for d in deletions:
                if not d["deleted"]:
                    print(f"  WARNING: {d['guardrail_id']} not deleted "
                          f"({d['error_code']}); Phase 99's tag sweep will flag it",
                          file=sys.stderr)

    residue = P.probe_residue(probes_made, deletions)
    d = decide(readings)

    common.update({
        "mutations": len(probes_made),
        "mutation_note": (f"{len(probes_made)} CreateGuardrail probe attempt(s) over "
                          f"{len(readings)} cells, {residue['n_created']} of which "
                          f"created a resource, deleted in a finally. Touches nothing "
                          f"in results/phase1_guardrails.json and no shared resource"),
        "cells": readings,
        "per_block": d["per_block"],
        "confound_register": d["confounds"],
        "counterexamples": d["counterexamples"],
        "interpretive_notes": d["notes"],
        "deletions": deletions,
        "residue": residue,
        "pacing": {"pace_s": PACE_S, "throttle_retries": THROTTLE_RETRIES,
                   "throttle_backoff_s": THROTTLE_BACKOFF_S,
                   "why": ("F8-5's STANDARD half drew a ThrottlingException at the "
                           "limiter's self-imposed 2/s; both of its confounders — the "
                           "crossRegion prerequisite and the throttle — are avoided "
                           "here by construction, then still detected by "
                           "classification if they occur anyway")},
        "priors_on_record": {
            "topic_standard_noxr_rejection": (
                "evidence/smoke20260810T0305Z/f8/F8-5/0003_create_guardrail_err.json — "
                "one topicPolicyConfig STANDARD-without-crossRegionConfig "
                "ValidationException naming the tier/cross-Region relationship; from a "
                "run confounded twice, so a prior, not the measurement"),
            "content_classic_with_xr_accepted": (
                "evidence/r20260810T011502Z/f3/F3-00-provision/"
                "0001_create_guardrail_ok.json — one accepted contentPolicyConfig "
                "CLASSIC create WITH crossRegionConfig"),
        },
        "no_power_claim": (f"planned_n({CASE}) is None and this is not a rate: "
                           f"{len(pr)} deterministic control-plane probes, each decided "
                           f"by one service response. n={len(readings)} is the count of "
                           f"cells the conjunction was evaluated over — unlike F1-4's "
                           f"n=0, these are live service trials, so the denominator "
                           f"exists and is stated"),
    })

    if not d["measured"]:
        rec = O.not_measured(CASE, d["reason"], confounds=d["confounds"],
                             per_block=d["per_block"])
        P.emit(CASE, rec, {**common, "why_inconclusive": (
            "a decisive cell's outcome could not be attributed to the claim; scoring an "
            "account-limitation or throttle rejection as the boundary holding would "
            "publish the account's state as the API's contract")}, store)
        return exit_code(n_read=len(readings), n_cells=len(pr), measured=False,
                         residue_clean=residue["clean"], verdict=rec["verdict"])

    o = P.obs_existence(
        CASE, bool(d["observed"]),
        # n is the number of live cells the conjunction was evaluated over. NOT 0: F1-4's
        # n=0 is for validator runs with no service trial; each of these probes is one
        # service response. The seal names no planned_n for F1-6, so nothing is compared
        # against this — it is the honest denominator, stated.
        n=len(readings),
        per_block={b: v["result"] for b, v in d["per_block"].items()},
        n_confounds=len(d["confounds"]),
        n_counterexamples=len(d["counterexamples"]))
    if O.mutation_is_mandatory(CASE):
        # Not the case today (the seal's mutation_arms_are_mandatory list omits F1-6; the
        # paired CLASSIC cells are the design's own inversion of the manipulated
        # variable). Honored anyway: if the list ever names F1-6, the inversion is
        # whether the tier flip alone flipped the outcome on every block, and it is set
        # as an ATTRIBUTE (not **detail — see phase1._detail and the F5-1 incident).
        o.mutation_inverted = all(
            v["result"] in ("holds", "fails") for v in d["per_block"].values())
    rec = O.evaluate(o)

    P.emit(CASE, rec, {
        **common,
        "verdict_rule": (
            "TRUE iff, on BOTH tier-carrying blocks: (STANDARD, no crossRegionConfig) is "
            "rejected with a validation naming the tier/cross-Region relationship, "
            "(STANDARD, with) is accepted — the control that attributes the rejection to "
            "the missing field rather than to the account — and (CLASSIC, no) is "
            "accepted. FALSE on any clean counterexample in either direction (the sealed "
            "kind is EXISTENCE over the conjunction, so 'CLASSIC rejected without it' "
            "fails the conjunction exactly as 'STANDARD succeeds anyway' does). A "
            "confounded decisive cell yields INCONCLUSIVE via not_measured, never TRUE"),
        "verdict_reading": d["reason"],
        "what_true_does_not_prove": (
            "that cross-Region inference RUNS, or that STANDARD-tier evaluation behaves "
            "differently — acceptance of a create is a statement about request "
            "validation, not about evaluation (F8-2/F8-3 measure tier behaviour). Nor "
            "that the requirement holds in other regions: this is one region "
            f"({args.region}) and one account, and the STANDARD-with control only rules "
            "the account limitation OUT of the rejection, it does not certify every "
            "account behaves this way. Nor anything about wordPolicyConfig et al., "
            "which carry no tierConfig at all"),
        "why_this_matters_operationally": (
            "§3.4's tier table and decision tree tell a reader to pick STANDARD for "
            "multilingual coverage; if STANDARD silently requires a cross-Region profile "
            "the document does not flag at the call site, a reader's CreateGuardrail "
            "fails with an error about a field their config never mentioned — and a "
            "reader who cargo-cults crossRegionConfig onto CLASSIC needs to know whether "
            "that is accepted or a hard STANDARD-only switch"),
        "expiry": (f"the model facts are dated by botocore {sc['sdk']['botocore']} and "
                   f"the service behaviour by this run's request ids; a later change on "
                   f"either side belongs in AWS-BEHAVIOR-CHANGES.md"),
    }, store)

    return exit_code(n_read=len(readings), n_cells=len(pr), measured=True,
                     residue_clean=residue["clean"], verdict=rec["verdict"])


if __name__ == "__main__":
    sys.exit(main())
