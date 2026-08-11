#!/usr/bin/env python3
"""Provision the Phase 1 guardrails: a declared table, created idempotently.

Phase 1 needs more than one guardrail because several of its oracles are *about*
configuration, and a claim about a setting cannot be tested by a guardrail that
holds that setting fixed:

* **F3-9's ROC** is a curve over filter strength. Bedrock's content filters have no
  numeric threshold — the knob is `inputStrength ∈ {NONE, LOW, MEDIUM, HIGH}` —
  so the "7-vertex lattice" the pre-registration describes is realised as one
  guardrail per strength, evaluated over the *same* corpus. That is the whole
  reason the corpus is shared rather than per-arm: an ROC assembled from different
  items at each point measures the items, not the threshold.
* **F8-2/3/4/5/7** compare CLASSIC against STANDARD. `tierConfig` sits *inside*
  each policy block (`contentPolicyConfig.tierConfig`, `topicPolicyConfig.tierConfig`)
  and not at the guardrail root — checked against the 1.43.67 model, not assumed —
  so a tier comparison needs two guardrails that differ in exactly that field.
* **F3-2/F3-3's false-positive rates** are measured on the same guardrails as the
  recall arms. Deliberately: an FPR measured under a *different* configuration than
  the recall it is paired with cannot enter a precision calculation, and §7.1's
  arithmetic is exactly that pairing.

Everything here is tagged `Project=guardrails-doc-validation` with a `RunId` and an
`ExpiresAt`, so `99_teardown.py` finds it by tag. Nothing here touches the three
pre-existing DRAFT guardrails in this account.

Idempotence, and why it is by name rather than by a state file
--------------------------------------------------------------
`--ensure` lists existing guardrails and creates only what is missing, matching on
the deterministic name. A state file would be the obvious alternative and is worse:
if the file is lost or the script dies between the create and the write, the next
run creates a second guardrail with the same name and the account accumulates
orphans that the teardown sweep will find but the arm scripts will pick between
arbitrarily. The service's own list is the state.

**A matching name is not a matching configuration**, and `--ensure` checks both. This was
not the original design and the gap was not hypothetical: `tier-classic` was created on
2026-08-10 without a `crossRegionConfig`, the spec then gained one (because STANDARD cannot
be built without cross-Region inference, so holding it constant is the only way to keep
F8-2/3/4 a *tier* comparison), and a name-only `--ensure` reported `exists tier-classic` and
moved on. The run would have measured CLASSIC-same-region against STANDARD-multi-region and
attributed the difference to the tier. So `verify_config` re-reads the fields the arms
depend on and refuses the run when a live guardrail disagrees with its spec, naming the
field — a stale resource must not be able to pass as a provisioned one.


Cost: `CreateGuardrail` is unmetered; guardrails have no standing charge. Spend in
Phase 1 comes from `ApplyGuardrail` text units, which the arm scripts incur and
`estimate_cost.py` projects. Creating this table costs **$0**.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A                                            # noqa: E402
from evidence import EvidenceStore, capture, new_run_id           # noqa: E402

RESULTS = ROOT / "results"

# The five content-filter categories the corpora cover. PROMPT_ATTACK is configured
# separately (it is input-only in the API and is F3-8/F5-6's subject), so it is not
# in this list.
CF_CATEGORIES = ("VIOLENCE", "HATE", "SEXUAL", "MISCONDUCT", "INSULTS")

# The strength lattice for F3-9. Three settings, not six and not four.
#
# Six would be describing a knob this service does not have — the pre-registration's
# worked example used a six-value *score* lattice, which is a different object from
# `inputStrength`. Four is what the enum contains, and was what this tuple said until
# the first live `--ensure` run: `CreateGuardrail` rejects a contentPolicyConfig whose
# every filter sits at NONE with
#     ValidationException: At least one content filter strength must be set to not NONE.
# and rejects it identically when the filters are all `inputEnabled=False`, while
# accepting five categories at NONE with PROMPT_ATTACK at LOW. So the constraint is "at
# least one of the six strengths is non-NONE", and a guardrail that is configured but
# classifies nothing cannot be built at all.
#
# The consequence for F3-9 is carried into the analysis rather than smoothed over: 3
# configurable strengths plus the two trivial endpoints (0,0) and (1,1) is at most **5**
# vertices, under the sealed oracle's ceiling of 7. `lib/phase1.UNREACHABLE_STRENGTHS`
# carries the reason into the emitted record, because "the ROC has 3 vertices because a
# validation rule forbids the 4th" and "the ROC has 3 vertices" are different claims.
STRENGTHS = ("LOW", "MEDIUM", "HIGH")

# Denied topic used by F3-5, and by F8-5's length-limit boundary probe.
TOPIC_NAME = "InvestmentAdvice"
TOPIC_DEFINITION = (
    "Requests for specific personalised investment, securities or trading advice, "
    "including which assets to buy, sell or hold.")

# The custom word list for F3-6. Exact-match is the claim under test, so the list
# holds words whose *near* misses are in the corpus: a filter that blocks a
# substring or a stem would be detected by the near-miss items, which is what makes
# "exactly" falsifiable rather than decorative.
WORDS = ("moonquake", "zorbify", "quaxlinate")

# The cross-Region inference profile. Hoisted to a constant because THREE arms now depend
# on the same value — F8-6's `xregion` arm varies it deliberately, and F8-2/3/4's tier pair
# holds it constant to keep the tier comparison unconfounded (see the tier block below).
# Two copies of a profile id, one of which is silently different, would make a "tier effect"
# out of a routing difference.
XREGION_PROFILE = "us.guardrail.v1:0"


def guardrail_specs(run_id: str) -> dict[str, dict]:
    """The declared table. Keys are logical arm names used by the case scripts."""
    specs: dict[str, dict] = {}

    # --- F3-1/2/3/8/9: content filters at each strength, CLASSIC ----------
    for s in STRENGTHS:
        specs[f"cf-{s.lower()}"] = {
            "purpose": f"content filters at inputStrength={s} (F3-1/2/3/9 lattice)",
            "config": {
                "contentPolicyConfig": {
                    "filtersConfig": [
                        {"type": t, "inputStrength": s, "outputStrength": s,
                         "inputAction": "BLOCK", "outputAction": "BLOCK",
                         "inputEnabled": True, "outputEnabled": True}
                        for t in CF_CATEGORIES
                    ] + [
                        # PROMPT_ATTACK is input-only in the API: it takes
                        # outputStrength NONE. Set explicitly so the asymmetry is a
                        # recorded decision rather than a default we did not notice.
                        {"type": "PROMPT_ATTACK", "inputStrength": s,
                         "outputStrength": "NONE", "inputAction": "BLOCK",
                         "inputEnabled": True}
                    ],
                    "tierConfig": {"tierName": "CLASSIC"},
                },
            },
        }

    # --- F8-2/3/4: the tier pair, at HIGH ---------------------------------
    #
    # BOTH arms carry crossRegionConfig, and that is a correctness requirement, not
    # symmetry for its own sake. Measured 2026-08-10:
    #   STANDARD, no crossRegionConfig  -> ValidationException "Can't configure guardrail
    #                                      policy tier. Enable cross-Region inference for
    #                                      your guardrail to use Standard tier."
    #   STANDARD + crossRegionConfig    -> ACCEPTED
    #   CLASSIC,  no crossRegionConfig  -> ACCEPTED
    #   CLASSIC  + crossRegionConfig    -> ACCEPTED (GetGuardrail confirms tierName=CLASSIC
    #                                      with the profile attached, so the two settings are
    #                                      genuinely independent)
    # STANDARD therefore has a hard dependency on cross-Region inference and CLASSIC does
    # not. The first version of this table gave CLASSIC no profile, which would have made
    # every F8-2/3/4 difference a comparison of (CLASSIC, same-region) against (STANDARD,
    # multi-region): a tier effect and a routing effect summed, with no way to attribute
    # either. Because CLASSIC accepts the profile, the confound is removable rather than
    # merely reportable — hold cross-region fixed and `tierName` is the only difference
    # left. F8-6's `xregion` arm is what varies cross-region deliberately.
    for tier in ("CLASSIC", "STANDARD"):
        specs[f"tier-{tier.lower()}"] = {
            "purpose": f"{tier} tier at HIGH with cross-Region inference held constant "
                       f"(F8-2/3/4 multilingual + prompt leakage)",
            "config": {
                "crossRegionConfig": {"guardrailProfileIdentifier": XREGION_PROFILE},
                "contentPolicyConfig": {
                    "filtersConfig": [
                        {"type": t, "inputStrength": "HIGH", "outputStrength": "HIGH",
                         "inputAction": "BLOCK", "outputAction": "BLOCK",
                         "inputEnabled": True, "outputEnabled": True}
                        for t in CF_CATEGORIES
                    ] + [
                        {"type": "PROMPT_ATTACK", "inputStrength": "HIGH",
                         "outputStrength": "NONE", "inputAction": "BLOCK",
                         "inputEnabled": True}
                    ],
                    "tierConfig": {"tierName": tier},
                },
            },
        }

    # --- F3-5: denied topics ---------------------------------------------
    specs["topic"] = {
        "purpose": "denied topic (F3-5); also the F8-5 length-limit subject",
        "config": {
            "topicPolicyConfig": {
                "topicsConfig": [
                    {"name": TOPIC_NAME, "definition": TOPIC_DEFINITION,
                     "type": "DENY", "inputAction": "BLOCK", "outputAction": "BLOCK",
                     "inputEnabled": True, "outputEnabled": True}
                ],
                "tierConfig": {"tierName": "CLASSIC"},
            },
        },
    }

    # --- F3-6: exact-match word filter -----------------------------------
    specs["words"] = {
        "purpose": "custom word list, exact-match claim (F3-6); F8-7 language scope",
        "config": {
            "wordPolicyConfig": {
                "wordsConfig": [
                    {"text": w, "inputAction": "BLOCK", "outputAction": "BLOCK",
                     "inputEnabled": True, "outputEnabled": True} for w in WORDS
                ],
            },
        },
    }

    # --- F3-4: PII, every entity type the corpus covers -------------------
    pii = pii_entity_types()
    specs["pii"] = {
        # The count is computed, not written. "all 31" in a description string is an
        # unchecked number that stays 31 after the model gains a 32nd entity.
        "purpose": f"all {len(pii)} PII entity types at BLOCK (F3-4)",
        "config": {
            "sensitiveInformationPolicyConfig": {
                "piiEntitiesConfig": [
                    {"type": t, "action": "BLOCK",
                     "inputAction": "BLOCK", "outputAction": "BLOCK",
                     "inputEnabled": True, "outputEnabled": True}
                    for t in pii
                ],
            },
        },
    }

    # --- F3-7: contextual grounding --------------------------------------
    specs["grounding"] = {
        "purpose": "contextual grounding + relevance at 0.7 (F3-7)",
        "config": {
            "contextualGroundingPolicyConfig": {
                "filtersConfig": [
                    {"type": "GROUNDING", "threshold": 0.7, "action": "BLOCK",
                     "enabled": True},
                    {"type": "RELEVANCE", "threshold": 0.7, "action": "BLOCK",
                     "enabled": True},
                ],
            },
        },
    }

    # --- F8-6: STANDARD tier with cross-Region inference -------------------
    # `crossRegionConfig.guardrailProfileIdentifier` is the whole subject of F8-6
    # ("Standard tier's cross-Region inference stays in-geography"). The profile id is
    # a geography-scoped constant — `us.guardrail.v1:0` — and there is no
    # ListGuardrailProfiles operation in the 1.43.67 model to enumerate it from, so it
    # is written here as a literal. If it is wrong the create fails with a recorded
    # error rather than silently producing a same-Region guardrail, which is the
    # failure mode that would matter: an F8-6 arm run against a guardrail whose
    # cross-Region config never took effect would report "stays in-geography" for a
    # guardrail that was never cross-Region at all.
    specs["xregion"] = {
        "purpose": "STANDARD + crossRegionConfig us.guardrail.v1:0 (F8-6)",
        "config": {
            "crossRegionConfig": {"guardrailProfileIdentifier": XREGION_PROFILE},
            "contentPolicyConfig": {
                "filtersConfig": [
                    {"type": t, "inputStrength": "HIGH", "outputStrength": "HIGH",
                     "inputAction": "BLOCK", "outputAction": "BLOCK",
                     "inputEnabled": True, "outputEnabled": True}
                    for t in CF_CATEGORIES
                ],
                "tierConfig": {"tierName": "STANDARD"},
            },
        },
    }

    # --- F2-5: the determinism arm ----------------------------------------
    # Its own guardrail rather than reusing cf-high, because 300 identical calls
    # against a shared guardrail would interleave with the recall arms' traffic and
    # any observed variation could then be argued to come from concurrent load.
    specs["determinism"] = {
        "purpose": "fixed config for the n=300 repeated-input arm (F2-5)",
        "config": {
            "contentPolicyConfig": {
                "filtersConfig": [
                    {"type": t, "inputStrength": "MEDIUM", "outputStrength": "MEDIUM",
                     "inputAction": "BLOCK", "outputAction": "BLOCK",
                     "inputEnabled": True, "outputEnabled": True}
                    for t in CF_CATEGORIES
                ],
                "tierConfig": {"tierName": "CLASSIC"},
            },
        },
    }

    # --- F10-2: the text-unit ladder --------------------------------------
    # Its own guardrail for two reasons, and the second one is the important one.
    #
    # 1. `TextUnitCount` in CloudWatch is dimensioned by GuardrailArn, so a shared
    #    guardrail would pool F10-2's sum with every other arm's traffic and the
    #    comparison against the API-reported quantity would be against a denominator
    #    holding other cases' calls.
    # 2. **Every action is NONE while every filter stays ENABLED.** A text unit is
    #    consumed by *evaluation*, not by intervention, so a billing case wants the
    #    filters to run and to do nothing. Under BLOCK, any filler string that happened
    #    to trip a filter would be blocked, and a blocked request is a different thing
    #    from an evaluated one — the ladder would then be a mixture of two treatments and
    #    "units scale with length" would be measured across it. `inputAction: NONE` with
    #    `inputEnabled: True` removes the confound at the source rather than screening
    #    for it afterwards.
    specs["billing"] = {
        "purpose": ("content filters at MEDIUM with every action NONE — F10-2's "
                    "text-unit length ladder (evaluation without intervention)"),
        "config": {
            "contentPolicyConfig": {
                "filtersConfig": [
                    {"type": t, "inputStrength": "MEDIUM", "outputStrength": "MEDIUM",
                     "inputAction": "NONE", "outputAction": "NONE",
                     "inputEnabled": True, "outputEnabled": True}
                    for t in CF_CATEGORIES
                ],
                "tierConfig": {"tierName": "CLASSIC"},
            },
        },
    }

    for key, spec in specs.items():
        spec["name"] = f"grx-gr-{key}-{run_id}"
    return specs


_PII_CACHE: list[str] | None = None


def pii_entity_types() -> list[str]:
    """The entity types from the *service model*, not a hand-kept list.

    A hardcoded list would silently diverge from the SDK, and F3-4's oracle is
    per-entity-type: an entity the model gained after the list was written would be
    absent from the guardrail and would look like a corpus gap rather than a stale
    constant.

    Cached: reading it builds a client, and the count is printed as well as used, so
    an uncached version would build three clients to answer one question.
    """
    global _PII_CACHE
    if _PII_CACHE is None:
        f = A.factory(A.MAIN_REGION)
        c = f.bedrock()
        shape = (c.meta.service_model.operation_model("CreateGuardrail")
                 .input_shape.members["sensitiveInformationPolicyConfig"]
                 .members["piiEntitiesConfig"].member.members["type"])
        _PII_CACHE = list(shape.enum)
    return list(_PII_CACHE)


def existing_by_name(client) -> dict[str, dict]:
    """Map name -> the DRAFT row, paginating.

    `ListGuardrails` returns **one row per version**, so a name maps to several rows
    once anything has been versioned (`CreateGuardrailVersion` is what Phase 5c needs).
    Keying a plain dict on the name would keep whichever row happened to come last and
    the idempotence check would then compare against an arbitrary version. Every arm
    here applies `DRAFT`, so the DRAFT row is the one that decides "does this exist".
    """
    out: dict[str, dict] = {}
    token = None
    while True:
        kw = {"maxResults": 100}
        if token:
            kw["nextToken"] = token
        resp = client.list_guardrails(**kw)
        for g in resp.get("guardrails") or []:
            if g.get("version") == "DRAFT":
                out[g.get("name", "")] = g
        token = resp.get("nextToken")
        if not token:
            break
    return out


def verify_config(live: dict, spec: dict) -> list[str]:
    """Return the fields where a live guardrail disagrees with its spec.

    Only the fields an arm's *interpretation* depends on are compared, and the list is
    deliberately short rather than a deep diff. A full structural comparison would fail on
    fields the service adds (`guardrailProfileArn`, timestamps, versions) and the resulting
    noise would train me to pass `--force` habitually, which removes the check.

    - `tierName`   — the independent variable of F8-2/3/4.
    - cross-Region — the confound F8-2/3/4 holds constant and F8-6 varies; present or
                     absent is what matters, so the *identifier* is compared, not the ARN
                     the service derives from it.
    - content-filter strengths — the F3-9 lattice IS these values.
    - policy blocks present — a guardrail that lost its `wordPolicy` still answers
      ApplyGuardrail, just never intervenes, and F3-6 would read that as recall 0.
    """
    bad: list[str] = []
    cfg = spec["config"]

    want_xr = (cfg.get("crossRegionConfig") or {}).get("guardrailProfileIdentifier")
    got_xr = (live.get("crossRegionDetails") or {}).get("guardrailProfileId")
    if want_xr != got_xr:
        bad.append(f"crossRegionConfig: spec wants {want_xr!r}, live has {got_xr!r}")

    want_cp = cfg.get("contentPolicyConfig")
    if want_cp:
        want_tier = (want_cp.get("tierConfig") or {}).get("tierName")
        got_tier = ((live.get("contentPolicy") or {}).get("tier") or {}).get("tierName")
        if want_tier != got_tier:
            bad.append(f"contentPolicy tier: spec wants {want_tier!r}, live has {got_tier!r}")
        want_s = {f["type"]: (f.get("inputStrength"), f.get("outputStrength"))
                  for f in want_cp["filtersConfig"]}
        got_s = {f["type"]: (f.get("inputStrength"), f.get("outputStrength"))
                 for f in (live.get("contentPolicy") or {}).get("filters") or []}
        if want_s != got_s:
            bad.append(f"content filter strengths: spec {want_s}, live {got_s}")

    # `xPolicyConfig` in a create call comes back as `xPolicy` on the guardrail.
    for key in cfg:
        if key.endswith("PolicyConfig"):
            live_key = key[: -len("Config")]
            if not live.get(live_key):
                bad.append(f"{live_key} is absent from the live guardrail but the spec "
                           f"declares it")
    return bad


def wait_ready(client, ids: dict[str, str], lim, *, timeout_s: int = 180,
               sleep=None) -> dict[str, str]:
    """Poll GetGuardrail until every id leaves CREATING. Returns id -> terminal status.

    `CreateGuardrail` returns `status=CREATING`, not READY — so a script that creates
    and exits has provisioned nothing usable, and the first arm to call
    `ApplyGuardrail` would fail on a guardrail that is merely not finished yet. That
    failure would be indistinguishable from a real one in the checkpoint's failure map,
    which is exactly the confound `n_usable` exists to prevent; better to block here.

    FAILED is returned rather than raised so the caller can report *which* config the
    service rejected — `statusReasons` on a FAILED guardrail is the evidence (it is how
    DC-1's `Overly Permissive` finding was read off the abandoned policy).

    A transient transport error is retried rather than raised, and this is not defensive
    padding — it is a correctness fix. An unhandled `EndpointConnectionError` here aborts
    `main()` *before* the manifest is written, so a DNS blip loses the record of guardrails
    that were genuinely created and are now sitting in the account untracked: real
    resources, no manifest naming them, and `99_teardown.py`'s tag sweep as the only thing
    that would ever find them. Observed once, 2026-08-10, mid-run. The polling loop is
    read-only and idempotent, so retrying costs nothing but the wait.
    """
    import time as _t
    sleep = sleep or _t.sleep
    pending = dict(ids)
    final: dict[str, str] = {}
    errors: dict[str, int] = {}
    waited = 0.0
    while pending and waited < timeout_s:
        for key, gid in list(pending.items()):
            lim.wait("GetGuardrail")
            try:
                st = client.get_guardrail(guardrailIdentifier=gid,
                                          guardrailVersion="DRAFT")
            except Exception as exc:                      # noqa: BLE001 — see docstring
                errors[key] = errors.get(key, 0) + 1
                if errors[key] >= 5:
                    # Give up on THIS id, not on the run: the status is genuinely unknown,
                    # and saying so is different from reporting READY or CREATING.
                    final[key] = f"STATUS_UNKNOWN_AFTER_{errors[key]}_TRANSPORT_ERRORS: " \
                                 f"{type(exc).__name__}"
                    pending.pop(key)
                continue
            status = st.get("status", "")
            if status != "CREATING":
                final[key] = status
                if status != "READY":
                    final[key] = f"{status}: {st.get('statusReasons') or []}"
                pending.pop(key)
        if pending:
            sleep(3.0)
            waited += 3.0
    for key in pending:
        final[key] = "TIMEOUT_STILL_CREATING"
    return final


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the table and make no AWS call")
    ap.add_argument("--ensure", action="store_true",
                    help="create anything missing (idempotent by name)")
    ap.add_argument("--replace-stale", action="store_true",
                    help="delete and recreate any existing guardrail whose live config "
                         "disagrees with its spec. Off by default: deleting a resource is "
                         "not something --ensure should do silently, and a run that stops "
                         "and names the drifted field is more useful than one that "
                         "quietly rebuilds the account.")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--ttl-hours", type=int, default=72,
                    help="ExpiresAt offset written into the tag")
    ap.add_argument("--region", default=A.MAIN_REGION)
    args = ap.parse_args()

    if not args.dry_run and not args.ensure:
        print("refusing to run: pass --dry-run or --ensure. A script whose default "
              "action mutates the account is the wrong default.", file=sys.stderr)
        return 2

    # One run id, resolved once. `--dry-run` uses a fixed placeholder rather than a
    # fresh id so the printed table is byte-identical between dry runs and can be
    # diffed; `new_run_id()` is only called on the path that actually creates things.
    run_id = args.run_id or ("dryrun" if args.dry_run else new_run_id())
    specs = guardrail_specs(run_id)

    print(f"Phase 1 guardrail table — {len(specs)} guardrails, run_id={run_id}")
    for key, spec in specs.items():
        blocks = ", ".join(sorted(spec["config"]))
        print(f"  {key:16s} {spec['name']:44s} {blocks}")
        print(f"                   {spec['purpose']}")

    if args.dry_run:
        pii = pii_entity_types()
        print(f"\nPII entity types read from the SDK model: {len(pii)}")
        print("  " + ", ".join(pii))
        print("--dry-run: no mutating AWS call made "
              "(the SDK model is read from the local botocore package, not the API).")
        return 0

    expires = (datetime.now(timezone.utc)
               + timedelta(hours=args.ttl_hours)).replace(microsecond=0).isoformat()
    tags = A.tags_for(run_id, expires)
    tag_list = [{"key": k, "value": v} for k, v in sorted(tags.items())]

    f = A.factory(args.region)
    client = f.bedrock()
    store = EvidenceStore(run_id, "f3", "F3-00-provision")
    store.write_environment()
    lim = A.limiter()

    have = existing_by_name(client)
    manifest: dict[str, dict] = {}
    created = 0
    stale: list[str] = []
    for key, spec in specs.items():
        name = spec["name"]
        if name in have:
            g = have[name]
            gid = g.get("id")
            lim.wait("GetGuardrail")
            live = client.get_guardrail(guardrailIdentifier=gid, guardrailVersion="DRAFT")
            drift = verify_config(live, spec)
            if drift and args.replace_stale:
                print(f"  STALE   {key}: {'; '.join(drift)}\n          deleting and "
                      f"recreating", file=sys.stderr)
                lim.wait("DeleteGuardrail")
                client.delete_guardrail(guardrailIdentifier=gid)
                have.pop(name, None)
                # Fall through to the create path below.
            elif drift:
                print(f"  STALE   {key}: {'; '.join(drift)}", file=sys.stderr)
                manifest[key] = {"name": name, "guardrail_id": gid, "version": "DRAFT",
                                 "created_now": False, "purpose": spec["purpose"],
                                 "config_drift": drift}
                stale.append(key)
                continue
            else:
                manifest[key] = {"name": name, "guardrail_id": gid,
                                 "version": "DRAFT", "created_now": False,
                                 "config_verified": True, "purpose": spec["purpose"]}
                print(f"  exists  {key}  (config verified)")
                continue
        lim.wait("CreateGuardrail")
        rec = capture(store, "create_guardrail", client,
                      name=name,
                      description=spec["purpose"][:200],
                      blockedInputMessaging="Blocked by the validation harness.",
                      blockedOutputsMessaging="Blocked by the validation harness.",
                      tags=tag_list,
                      **spec["config"])
        if not rec.ok:
            print(f"  FAILED  {key}: {rec.error_code}: {rec.error_message}",
                  file=sys.stderr)
            manifest[key] = {"name": name, "error_code": rec.error_code,
                             "error_message": rec.error_message,
                             "request_id": rec.request_id}
            continue
        created += 1
        manifest[key] = {"name": name,
                         "guardrail_id": (rec.response or {}).get("guardrailId"),
                         "arn": "REDACTED",
                         "version": (rec.response or {}).get("version", "DRAFT"),
                         "created_now": True, "request_id": rec.request_id,
                         "purpose": spec["purpose"]}
        print(f"  created {key}  request-id {rec.request_id}")

    # Wait for READY before writing the manifest. CreateGuardrail returns
    # `status=CREATING`; a manifest written at that moment names guardrails that no arm
    # can use yet, and the resulting ApplyGuardrail errors would land in the checkpoint's
    # failure map indistinguishable from real ones.
    pending = {k: v["guardrail_id"] for k, v in manifest.items()
               if v.get("created_now") and v.get("guardrail_id")}
    if pending:
        print(f"\nwaiting for {len(pending)} guardrail(s) to leave CREATING...")
        statuses = wait_ready(client, pending, lim)
        for key, st in sorted(statuses.items()):
            manifest[key]["status"] = st
            print(f"  {key:16s} {st}")
    # Three states, and the defaulting must not merge them. `created_now` is absent on BOTH
    # a guardrail that already existed and one whose create call was rejected, so keying the
    # default on `not created_now` alone wrote `READY (pre-existing)` over eight genuine
    # failures — four ThrottlingExceptions and cf-none's ValidationException — while the
    # exit code correctly said 1. A manifest is read by every arm script; a status field
    # that reports a rejected create as READY is the shape of feedback_vacuous_test_check,
    # one level down: the artifact certifies a resource that does not exist.
    for key, v in manifest.items():
        if "error_code" in v:
            v["status"] = f"CREATE_FAILED: {v['error_code'] or 'TransportError'}"
        elif v.get("created_now"):
            v.setdefault("status", "UNKNOWN")
        else:
            v["status"] = "READY (pre-existing)"

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "phase1_guardrails.json"
    out.write_text(json.dumps({
        "run_id": run_id, "region": args.region, "expires_at": expires,
        "tags": tags, "created_now": created, "guardrails": manifest,
        "strength_lattice": list(STRENGTHS),
        "cf_categories": list(CF_CATEGORIES),
        "words": list(WORDS), "topic": TOPIC_NAME,
        "sdk": A.sdk_versions(),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    store.write_summary({"created_now": created, "n_specs": len(specs)})
    print(f"\nmanifest -> {out.relative_to(ROOT)}  ({created} created this run)")

    # Two separate failure modes, reported separately: the create call was rejected, or
    # the create succeeded and the service then failed to build it. The second carries
    # `statusReasons`, which is the only place the reason for a rejected *config* appears
    # (it is how DC-1's "Overly Permissive" was read off the abandoned policy).
    errored = [k for k, v in manifest.items() if "error_code" in v]
    not_ready = [k for k, v in manifest.items()
                 if "error_code" not in v and not str(v["status"]).startswith("READY")]
    if errored:
        print(f"FAIL: {len(errored)} guardrail(s) rejected at create: {errored}",
              file=sys.stderr)
    if not_ready:
        print(f"FAIL: {len(not_ready)} guardrail(s) did not reach READY: "
              f"{[(k, manifest[k]['status']) for k in not_ready]}", file=sys.stderr)
    # A stale guardrail is a failure, not a warning. It is READY and it answers
    # ApplyGuardrail, so nothing downstream would notice — the arms would simply measure a
    # different configuration than the one the analysis says they measured.
    if stale:
        print(f"FAIL: {len(stale)} guardrail(s) exist with a config that disagrees with "
              f"the spec: {stale}. Re-run with --replace-stale to rebuild them, or fix the "
              f"spec if the live config is the correct one.", file=sys.stderr)
    return 1 if (errored or not_ready or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
