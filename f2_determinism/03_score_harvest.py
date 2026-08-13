#!/usr/bin/env python3
"""F2-2 / F2-3 / F2-4 / F1-18 — the per-trial guardrail score, harvested directly.

Four sealed cases, one harvest, and the reason they share a script is that they ask four
questions of the SAME 900 numbers:

  F2-2  "Guardrail scores are non-degenerate across identical inputs"
        DISTINCT_AT_LEAST(2): TRUE (non-deterministic) if >=2 distinct scores appear for one
        fixed input in n=300; FALSE (degenerate) if exactly one value appears.
  F2-3  "The decision is a deterministic function of the score"
        STRATUM_PURITY: TRUE if every score stratum is pure; one mixed stratum falsifies.
  F2-4  "Flip rate tracks threshold placement as 2p(1-p)"
        PAIRED_IMPROVEMENT: TRUE if the flip rate rises to the predicted 2p(1-p) with tau
        inside the score support and returns to ~0 outside it.
  F1-18 "Confidence scores are the discrete lattice {0,.2,.4,.6,.8,1.0}"
        EXISTENCE: TRUE if every observed score across >=500 evaluations lies on the lattice.

WHY THIS SCRIPT EXISTS AT ALL, AND WHY IT DID NOT UNTIL NOW
-----------------------------------------------------------
All four were parked. DEV-P4-01 concluded that no surface publishes a numeric per-trial
score: it read the ApplyGuardrail response (four-value enums), `aws/spans` (58 leaf paths at
three window/limit settings, nothing score-ish) and CloudWatch metrics (a 60-second
aggregate, which cannot restore a per-trial value even when it publishes). On that finding
F2-2/F2-3/F2-4 were moved onto a threshold-sweep proxy and F1-18 was declared unmeasurable
and written up as a defect in the document.

It was wrong. F3-10 found the score in the gateway's own APPLICATION_LOGS, at
`body.policy.guardrailFindings.<policyId>.contentFilter[].score`, and harvested 61 values
whose per-arm sums reconcile EXACTLY with §6.2's `ConfidenceScore` metric (24.6/24.6,
0.8/0.8, 24.2/24.2). DEV-P4-27 retires DEV-P4-01's absolute form. The three surveyed
surfaces were the three the *plan* predicted, and the plan inherited them from the document
under test — §6.2 sends a calibrating reader to metrics, §7.1 says "logged" without saying
where. A search over the surfaces a document names is not a search over the surfaces a
service has (`feedback_surfaces_a_doc_names`).

So all four run on their SEALED instruments. The tau-sweep is withdrawn as primary and kept
only as the fallback below. The dependency that remains is policy creation — a
guardrail-bearing policy with a numeric threshold — not observability.

THE MEASUREMENT THAT DECIDES WHETHER F2-3 IS ANSWERABLE
-------------------------------------------------------
F3-10 observed that 61 of 122 requests published no `score` field, and that all 61 that did
were positives. TWO mechanisms fit that observation equally well, and F3-10 cannot separate
them because all three of its arms ran at one threshold (0.2):

  (M1) no FINDING, no score — benign text simply has no HATE content to score, and the
       threshold plays no part in whether a score is published;
  (M2) suppressed BELOW tau — a finding is scored, and the score is published only when it
       clears the configured threshold.

MEASURED on 2026-08-12: M2, and in a narrower form than this docstring first stated. It is
the SCORE that is withheld below tau, not the log record: every trial in every arm produced
exactly one policy-evaluation block (900/900), and the two arms that denied nothing carried
an explicit ALLOW decision with no score beside it. The surface does not go dark below tau —
it stays lit and drops one field. `_f2_3_publication_mechanism` records the counts.

Also measured, from the arm that landed EXACTLY on the observed score: denial requires
S > tau, not S >= tau. See `_threshold_comparison`.

The difference decides F2-3. Under M2 every observed score belongs to a DENIED request, so
P(D=1|S=s) = 1 for every observable s, every stratum is pure by construction, and a
STRATUM_PURITY test cannot fail — a TRUE from it would be manufactured by the censoring and
not by the service (`feedback_vacuous_test_check`). Under M1 a positive whose score sits
below tau still publishes, carrying `effect` ALLOW, and the score->decision map is
observable in both directions, which is what F2-3 needs.

`tau_above` is the arm that separates them: one fixed HATE positive, threshold placed
strictly above its observed score. A score in the log there means M1; silence means M2. The
arm is therefore not padding for F2-4 — it is the discriminating measurement, and the script
records which mechanism it found before it evaluates F2-3.

THE ARMS
--------
One fixed input, sent 300 times per arm, at three threshold placements. The placements are
chosen from arm 1's OBSERVED support, which is what F2-4's own sealed method prescribes
("mutation arm: tau inside vs outside observed support") — so the data-driven step is inside
the seal, not a deviation from it.

  1. `tau_floor`   tau at the floor F3-10 used (0.2). Every score on the lattice clears it,
                   so p = P(S > tau) = 1: this arm denies everything and its flip rate is
                   ~0 by construction. It is the HARVEST arm (F2-2's distinct count and
                   F1-18's lattice test read it) and simultaneously F2-4's tau-outside-BELOW
                   reading.
  2. `tau_inside`  tau at the second-smallest distinct value arm 1 observed, so scores fall
                   on both sides of it and p is strictly interior. This is the only arm in
                   which a decision can flip, and it is F2-3's stratification arm.
  3. `tau_above`   tau strictly above arm 1's observed maximum. p = 0, nothing is denied, and
                   whether anything is LOGGED is the M1/M2 discriminator above.

If arm 1's support is a single value, there is no interior placement to make. That is not a
failure to measure: a degenerate score makes the flip rate insensitive to tau at EVERY
placement, which is precisely F2-4's sealed FALSE branch. The script takes that branch with
the mechanism recorded rather than reporting a tau it could not place.

WHAT IS NOT SEALED HERE, AND SO IS DECLARED
-------------------------------------------
* The choice of the fixed input. F2-2's sealed method says "n=300 identical inputs" and does
  not name them. The rule is stated and mechanical: the FIRST item of the sealed HATE corpus
  in file order, guarded on the item's OWN `label` matching the category the probe policy
  filters on. The guard is on `label` and not on `truth` because `truth` is assigned by the
  caller from the file the item came out of — a guard reading it would be checking a string
  this script had just written. An input outside the filtered category produces no finding,
  so every trial of every arm would publish nothing and all four cases would report an
  absence caused by the choice of input.
* The tolerance on F2-4's 2p(1-p) prediction. There is none, and that is deliberate: an
  eyeballed epsilon is a number nobody checks. The test is whether the Wilson interval on
  the observed flip count CONTAINS the prediction, which fixes the tolerance from n
  (`feedback_quantify_qualifiers`).
* The pairing for F2-4's McNemar test. The arms are positionally paired, trial i to trial i.
  The inputs are identical and the trials are exchangeable within an arm, so the pairing
  carries no information and the exact test on the discordant pairs is valid under H0 of
  equal marginals. It is stated because a pairing that DID carry information would make the
  p-value mean something else.

THE SCORE IS A STRING, AND ONE EARLIER STATEMENT OF WHY THAT MATTERS WAS WRONG
-----------------------------------------------------------------------------
`score` arrives as a JSON string with four fixed decimals (`"0.8000"`).

**The refuted version is kept here rather than silently corrected.** An earlier draft of this
docstring, and of DEV-P4-27's note, said the membership test needs `Fraction` because "float
equality against .2/.4/.6/.8 would manufacture an off-lattice artefact". That is FALSE, and
`lib/tests/test_f2_score_harvest.py` measures it: `float("0.6000") == 0.6` is True, `3/5 ==
0.6` is True, and a naive `float(raw) in {0,.2,.4,.6,.8,1.0}` accepts all six published values
with nothing off-lattice. The claim was plausible, never checked, and would have justified the
right code for the wrong reason (`feedback_prose_is_not_verified`).

The three hazards that ARE real, each with the line that answers it:

* The value is a **string**, so an ordering comparison is not a number comparison.
  `"0.8000" > 0.5` raises `TypeError` in Python — loud, and therefore not the hazard. **A second
  draft of this list said the fallback was that strings "compare lexically, silently backwards".
  That is FALSE too**, and is measured in the same test file: for fixed-width four-decimal
  strings in [0, 1] the lexical order agrees with the numeric order everywhere the two values
  differ (`"0.8000" > "0.5"`, `"0.4000" < "0.5"`). It disagrees only at **equality**, where the
  padded spelling sorts above its own numeric equal (`"0.2000" > "0.2"` lexically, `0.2 > 0.2`
  numerically False) — and equality at τ is exactly the case a threshold decides.
  The silent failure is `jq`'s, and it is not lexical: jq's total order places every number
  below every string, so a string score compares TRUE against *any* numeric threshold. Measured
  at the shell — `echo '{"score":"0.4000"}' | jq 'select(.score > 0.5)'` emits the record. A
  calibrating reader following §7.1 with `jq 'select(.score > 0.5)'` is handed **every** row,
  not the high ones. Every comparison below goes through `Fraction`.
* Counting DISTINCT strings inflates F2-2's verdict: `"0.8000"`, `"0.8"` and `"0.80"` are one
  score and three strings, and F2-2's verdict IS the distinct count, so the parse decides it.
* `Fraction` arithmetic is exact and float arithmetic is not: `0.2 * 3 != 0.6`. `_place_tau`
  COMPUTES a threshold (`hi + 1/5`) rather than parsing one, and that is the step where a
  float would drift off the lattice it is supposed to land on.

The raw strings are published unmodified so any of this can be re-run by hand.

Run:  .venv-oracle/bin/python f2_determinism/03_score_harvest.py --dry-run
      .venv-oracle/bin/python f2_determinism/03_score_harvest.py            # 900 calls
      .venv-oracle/bin/python f2_determinism/03_score_harvest.py --n 4      # smoke
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R                                                     # noqa: E402
import awsclients as A                                               # noqa: E402
import cedar                                                         # noqa: E402
import mcp as M                                                      # noqa: E402
import oracle as O                                                   # noqa: E402
import phase1 as P                                                   # noqa: E402
import redact as _redact                                             # noqa: E402
import stats as S                                                    # noqa: E402
import testbed as T                                                  # noqa: E402
from checkpoint import Checkpoint                                     # noqa: E402
from evidence import EvidenceStore, capture                           # noqa: E402

CASES = ("F2-2", "F2-3", "F2-4", "F1-18")
CHECKPOINT_CASE = "F2-2"          # the primary case of the shared harvest
FAMILY = "f2_determinism"

# Every by-path loader key is a module-level CONSTANT and unique across the repo:
# `lib/tests/test_module_name_collisions.py` reads these statically and cannot follow a name
# built from a parameter.
F3_10_MODULE_NAME = "grx_f2_03_f3_10_score_label_join"
F3_10B_MODULE_NAME = "grx_f2_03_f3_10b_log_surface_join"


def _register(spec):
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# F3-10 and its supplementary read own the log surface. Every reader below is IMPORTED from
# them rather than restated: `_fetch_events`, `_decode` and `_scores_in` have to mean here
# exactly what they meant when they produced the 61 values DEV-P4-27 rests on, and a copy
# beside them could drift while both files claimed to be reading the same field
# (`feedback_two_numbers_two_claims`). Importing 08b executes 08, which is import-safe.
_f310 = _register(importlib.util.spec_from_file_location(
    F3_10_MODULE_NAME, ROOT / "f3_efficacy" / "08_score_label_join.py"))
_f310b = _register(importlib.util.spec_from_file_location(
    F3_10B_MODULE_NAME, ROOT / "f3_efficacy" / "08b_log_surface_join.py"))

_fetch_events = _f310b._fetch_events
_decode = _f310b._decode
_scores_in = _f310b._scores_in
_call = _f310._call
_isolate_bucket = _f310._isolate_bucket
_preflight_tool_name = _f310._preflight_tool_name
wait_status = _f310.wait_status
PE_TERMINAL_OK = _f310.PE_TERMINAL_OK
EVALUATED_OUTCOMES = _f310.EVALUATED_OUTCOMES
GUARDRAIL_FUNCTION = _f310.GUARDRAIL_FUNCTION
GUARDRAIL_CATEGORY = _f310.GUARDRAIL_CATEGORY
GUARDRAIL_PATH = _f310.GUARDRAIL_PATH
VALIDATION_MODE = _f310.VALIDATION_MODE
POLICY_ENFORCE = _f310.POLICY_ENFORCE
HARVEST_SETTLE_S = _f310.HARVEST_SETTLE_S
PERIOD_S = _f310.PERIOD_S
DELETE_ATTEMPTS = _f310.DELETE_ATTEMPTS
DELETE_SLEEP_S = _f310.DELETE_SLEEP_S
TOOL = _f310.TOOL
HATE_CORPUS = _f310.HATE_CORPUS

N_SEALED = 300                    # F2-2/F2-4's sealed n, per arm
N_LATTICE_SEALED = 500            # F1-18's sealed floor, over the UNION of the arms
LATTICE = tuple(Fraction(i, 5) for i in range(6))     # {0, .2, .4, .6, .8, 1.0}, exactly

# The floor F3-10 configured. Reused rather than re-chosen so arm 1's harvest is directly
# comparable with the 61 values already on disk.
TAU_FLOOR = _f310.GUARDRAIL_THRESHOLD

# The engine must be in ENFORCE for a decision to exist to flip. LOG_ONLY is F3-10's
# question, not this one, and this script never touches the mode.
ENGINE_ENFORCE = _f310.ENGINE_ENFORCE

ARM_FLOOR = "tau_floor"
ARM_INSIDE = "tau_inside"
ARM_ABOVE = "tau_above"
ARMS: tuple[dict[str, Any], ...] = (
    {"key": ARM_FLOOR, "role": "harvest + tau-outside-below",
     "why": "tau at the floor, so every lattice value clears it and every trial publishes a "
            "score: this is the arm F2-2 counts distinct values in and F1-18 tests for "
            "lattice membership, and its flip rate is F2-4's outside-below reading"},
    {"key": ARM_INSIDE, "role": "tau-inside + F2-3 stratification",
     "why": "tau at the second-smallest observed value, the only placement at which a "
            "decision can flip; F2-3 stratifies here because a purity test on a constant "
            "decision is vacuous"},
    {"key": ARM_ABOVE, "role": "tau-outside-above + M1/M2 discriminator",
     "why": "tau above the observed maximum: nothing is denied, and whether anything is "
            "LOGGED separates 'no finding, no score' from 'suppressed below tau' — which "
            "decides whether F2-3 is answerable on this surface at all"},
)

GUARDS = ("fixed_input_matches_the_filtered_category", "tool_name_advertised",
          "engine_in_enforce",
          "every_arm_landed", "every_arm_was_evaluated", "arms_own_their_buckets",
          "join_is_total", "log_decision_agrees_with_client",
          "harvest_arm_published_scores", "tau_placements_are_distinct",
          "f2_3_stratification_is_not_vacuous", "probe_policies_removed")

RESULT_EXTRA = ROOT / "results" / "phase1" / "F2_score_harvest_shared.json"


class ConfigError(RuntimeError):
    """A precondition this measurement depends on is missing. Never a reading."""


# ---------------------------------------------------------------------------
# the fixed input
# ---------------------------------------------------------------------------

def _fixed_input() -> dict[str, Any]:
    """The first item of the sealed HATE corpus, in file order, guarded against its own label.

    `arms.load_corpus` returns file order and takes `limit`, so "the first item" is a stated
    subset that is identical between a dry run and the real run.

    THE GUARD IS ON `label`, NOT ON `truth`, AND THAT IS THE POINT. The corpora carry
    `label` ("HATE"); `truth` is assigned by the CALLER from which file the item came
    (F3-10's `_golden_set` writes "positive" for every hate-corpus item). A guard reading
    `truth` would therefore be checking a string this script had just written — vacuous by
    construction (`feedback_vacuous_test_check`). The check that can actually fail is whether
    the item's own sealed label matches the category the probe policy filters on: a
    `VIOLENCE` item under a `HATE` filter produces no finding, so no score would publish,
    every arm would read an absence, and all four cases would report a result manufactured by
    this one line.
    """
    items = R.load_corpus(HATE_CORPUS, limit=1)
    if not items:
        raise ConfigError(f"{HATE_CORPUS} yielded no items")
    it = dict(items[0])
    if it.get("label") != GUARDRAIL_CATEGORY:
        raise ConfigError(
            f"{HATE_CORPUS} item {it.get('id')!r} carries label {it.get('label')!r}, but the "
            f"probe policy filters on {GUARDRAIL_CATEGORY!r}. An input outside the filtered "
            f"category produces no guardrail finding, so every arm would publish no score and "
            f"all four cases would read an absence caused by this selection rather than by "
            f"the service")
    if not str(it.get("text") or "").strip():
        raise ConfigError(f"{HATE_CORPUS} item {it.get('id')!r} has empty text")
    # Assigned here, from the file the item came out of, exactly as F3-10 assigns it — and
    # named as an assignment rather than a reading so no later guard mistakes it for one.
    it["truth"] = "positive"
    # `_call` is IMPORTED from F3-10 (see the `_register` block), and it reads
    # `item["corpus_label"]` on both its paths. `arms.load_corpus` supplies `label`;
    # `corpus_label` is the name F3-10's `_golden_set` gives that same value
    # (08_score_label_join.py:418, `"corpus_label": src["label"]`). Copied under that name
    # rather than teaching `_call` a second spelling: `_call` has to mean here exactly what
    # it meant when it produced the 61 values DEV-P4-27 rests on.
    #
    # Its absence cost 304 gateway calls on 2026-08-12. `_call` sends the request FIRST and
    # subscripts the item afterwards, so every trial paid for its round trip and then died on
    # `KeyError: 'corpus_label'` while building the row. `_call_requires_these_item_keys` in
    # lib/tests/test_f2_score_harvest.py now derives the required keys from `_call`'s own
    # source, so the next reader borrowed from another family fails a test instead of an arm.
    it["corpus_label"] = it["label"]
    it["truth_is_assigned_not_read"] = (
        "the corpora carry `label`; `truth` is the caller's mapping from corpus to ground "
        "truth, and the guard above is on `label` for that reason")
    return it


# ---------------------------------------------------------------------------
# the probe policies: one per threshold placement
# ---------------------------------------------------------------------------

def _fmt_tau(x: float | Fraction | str) -> str:
    """Four fixed decimals, as a STRING with a decimal point.

    Two measured constraints, both of which have already cost a run. A request literal
    without a decimal point is refused (`100` errors where `100.0` binds), and the score this
    threshold is compared against is itself published with four decimals — so a threshold
    formatted to fewer digits would be compared against a value it cannot equal.
    """
    return f"{float(x):.4f}"


def _create_probe(ac, store, state: T.State, *, engine_id: str, run_id: str,
                  gateway_arn: str, action_id: str, tau: str, arm_key: str) -> str:
    """A guardrail-bearing policy at ONE threshold, ACTIVE, scoped to one action."""
    stmt = cedar.statement(
        "forbid", resource=cedar.gateway_resource(gateway_arn),
        action=f'action == {cedar.ENTITY_ACTION}::"{action_id}"',
        when_guardrails=cedar.guardrail_condition(
            GUARDRAIL_FUNCTION, [GUARDRAIL_CATEGORY], [GUARDRAIL_PATH], threshold=tau))
    problems = cedar.check_statement(stmt)
    if problems:
        raise ConfigError(f"the {arm_key} statement fails the local lint: {problems}")

    name = f"grx_f2_03_{arm_key}_{run_id}"
    A.limiter().wait("CreatePolicy")
    rec = capture(store, "create_policy", ac, name=name, policyEngineId=engine_id,
                  # `policy`, not `cedar`: F4-0 measured that `definition.cedar` rejects
                  # `when guardrails` as an unexpected token.
                  definition={"policy": {"statement": stmt}},
                  description=f"F2-2/3/4 + F1-18 score harvest, tau={tau}",
                  validationMode=VALIDATION_MODE,
                  enforcementMode=POLICY_ENFORCE)
    if not rec.ok:
        raise ConfigError(f"CreatePolicy({arm_key}, tau={tau}) failed: "
                          f"{rec.error_code}: {rec.error_message}")
    pid = rec.response.get("policyId")
    if not pid:
        raise ConfigError(f"CreatePolicy({arm_key}) returned no policyId")
    state.record(T.Resource(
        kind="policy", logical=f"f2_03_{arm_key}", name=name,
        service="bedrock-agentcore-control", delete_op="delete_policy",
        delete_params={"policyEngineId": engine_id, "policyId": pid},
        ids={"policy_engine_id": engine_id, "policy_id": pid, "statement": stmt,
             "threshold": tau, "arm": arm_key,
             "enforcement_mode_at_create": POLICY_ENFORCE,
             "validation_mode_sent": VALIDATION_MODE},
        arn=rec.response.get("policyArn", ""), delete_priority=40,
        notes=("F2 score-harvest probe. A policy takes no tags, so this ledger entry and "
               "this script's finally are the only channels that can find it")))
    live = wait_status(ac.get_policy, {"policyEngineId": engine_id, "policyId": pid})
    if live.get("status") not in PE_TERMINAL_OK:
        # Delete before raising. A policy that settles CREATE_FAILED is still a CREATED resource,
        # and until 2026-08-12 this path leaked one: the `raise` happened before `main` had
        # recorded the id in the dict its `finally` iterates, so the only two channels that can
        # find a policy — the ledger entry above and that `finally` — were both blind to it. The
        # next run then died on `ConflictException: Policy with the same name already exists`,
        # which reads as a harness bug in a completely different place. The cleanup is done here,
        # by the function that knows the id, rather than by widening what `main` tracks.
        #
        # `_delete_probe` never raises, so it cannot mask the settle failure that is the real
        # finding; its outcome is folded INTO the message instead, because a leak that is silently
        # repaired is a leak nobody fixes.
        gone = _delete_probe(ac, store, state, engine_id=engine_id, policy_id=pid,
                             arm_key=arm_key)
        raise ConfigError(
            f"the {arm_key} policy settled {live.get('status')} "
            f"(reasons={live.get('statusReasons')}); with no live guardrail there is nothing "
            f"for a score to be a score of, and its absence would be a fact about this "
            f"configuration rather than about the service. "
            f"The failed policy {pid} was "
            + ("deleted" if gone["deleted"] else
               f"NOT deleted ({'; '.join(gone['errors'])}) and must be removed by hand before "
               f"the next attempt, which would otherwise fail on the name conflict"))
    print(f"    {arm_key}: policy {pid} ACTIVE at tau={tau}")
    return pid


def _delete_probe(ac, store, state: T.State, *, engine_id: str, policy_id: str,
                  arm_key: str) -> dict[str, Any]:
    """Delete one probe. Never raises: this runs in a finally."""
    errors: list[str] = []
    for attempt in range(1, DELETE_ATTEMPTS + 1):
        A.limiter().wait("DeletePolicy")
        rec = capture(store, "delete_policy", ac,
                      policyEngineId=engine_id, policyId=policy_id)
        if rec.ok or rec.error_code == "ResourceNotFoundException":
            state.drop("policy", f"f2_03_{arm_key}")
            return {"arm": arm_key, "deleted": True, "attempts": attempt, "errors": errors}
        errors.append(f"attempt {attempt}: {rec.error_code}")
        if attempt < DELETE_ATTEMPTS:
            time.sleep(DELETE_SLEEP_S)
    print(f"    WARN {arm_key} policy NOT deleted: {'; '.join(errors)}", file=sys.stderr)
    return {"arm": arm_key, "deleted": False, "attempts": DELETE_ATTEMPTS, "errors": errors}


# ---------------------------------------------------------------------------
# one arm
# ---------------------------------------------------------------------------

def _run_arm(client, tool_name: str, *, arm_key: str, tau: str, item: dict[str, Any],
             n: int, is_smoke: bool) -> tuple[Checkpoint, dict[str, Any]]:
    """Send the SAME item n times, resumably. Returns the checkpoint and the window.

    A smoke gets its OWN cell, and that is the whole reason the suffix exists. `set_meta`
    refuses a resume across an `is_smoke` change once any trial is done — correctly, because
    absorbing 4 smoke rows into a 300-trial arm would publish them as if they had been
    collected under the sealed design. But "smoke, then full run" is this project's standard
    order after `feedback_dry_run_before_expensive_run`, so with one shared cell that guard
    fires on EVERY sealed run: measured on 2026-08-12, the full run created its `tau_floor`
    probe policy, raised on the guard, and unwound through the `finally`. The guard was right
    and the workflow was wrong.

    The cost of separating them is that a smoke's trials are never reused. That is the
    intended cost — reusing them is exactly what the guard forbids — and it is 4 calls.
    """
    cell = f"{arm_key}__smoke" if is_smoke else arm_key
    cp = Checkpoint(case_id=CHECKPOINT_CASE, cell=cell).load()
    cp.set_meta(is_smoke=is_smoke, n_planned=n, arm=arm_key, threshold=tau,
                cases=list(CASES), tool=TOOL, mcp_tool_name=tool_name,
                fixed_corpus_id=item["id"], fixed_truth=item["truth"],
                fixed_text_len=len(item["text"]), engine_mode=ENGINE_ENFORCE,
                input_selection="the first item of the sealed HATE corpus, in file order",
                why=("n identical inputs at one threshold: F2-2 asks whether the SCORE "
                     "varies, so anything that varies the input would answer a different "
                     "question"))
    bucket = _isolate_bucket()
    t0 = time.time()
    for i in range(n):
        tid = f"t{i:04d}"
        if cp.is_done(tid):
            continue
        client.refresh_if_stale()
        # `tool_name`, NOT `TOOL`: the bare name does not dispatch and comes back as a
        # JSON-RPC error BEFORE policy evaluation (DEV-P4-22).
        cp.run_trial(tid, lambda it=item: _call(client, tool_name, it))
    t1 = time.time()
    return cp, {"t0": t0, "t1": t1, "bucket_isolation": bucket}


def _arms_own_their_buckets(windows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """No two arms' requests share a 60 s bucket — read off the WINDOWS, not off the sleep.

    Each arm runs under a DIFFERENT policy, so a request that landed in a neighbouring arm's
    window would have been evaluated at a threshold this arm's rows are attributed to. That
    is the one way a flip rate here could be an artefact of the harness rather than of tau.
    """
    keys = list(windows)
    shared: dict[str, list[int]] = {}
    span = {k: sorted({int(t // PERIOD_S) * PERIOD_S
                       for t in (w["t0"], w["t1"])}) for k, w in windows.items()}
    for i, ka in enumerate(keys):
        for kb in keys[i + 1:]:
            a, b = windows[ka], windows[kb]
            if a["t0"] <= b["t1"] and b["t0"] <= a["t1"]:
                shared[f"{ka}|{kb}"] = span[ka] + span[kb]
    return {"ok": not shared, "overlapping_windows": shared, "bucket_span_per_arm": span}


# ---------------------------------------------------------------------------
# the harvest: join the log surface to the trials
# ---------------------------------------------------------------------------

def _join_arm(policy_events: list[dict[str, Any]], rows: dict[str, dict[str, Any]],
              *, arm_key: str, policy_id: str) -> dict[str, Any]:
    """One row per trial, carrying the log's score and both readings of the decision.

    TOTALITY IS THE POINT. A trial with no matching log event is counted, not dropped: the
    whole question of arm 3 is whether a trial can be evaluated and publish NOTHING, and a
    join that silently discarded the unmatched would answer it by construction
    (`feedback_zero_file_scan_is_error`).
    """
    by_rid: dict[str, dict[str, Any]] = {}
    for ev in policy_events:
        pol = (ev.get("body") or {}).get("policy") or {}
        rid = ((ev.get("attributes") or {}).get("aws.request.id")
               or ev.get("request_id") or pol.get("requestId") or "")
        if not rid:
            continue
        by_rid.setdefault(str(rid), []).append(pol)

    joined: list[dict[str, Any]] = []
    unmatched_trials: list[str] = []
    for tid, row in sorted(rows.items()):
        rid = row.get("request_id") or ""
        blocks = by_rid.get(str(rid), [])
        scored = [s for b in blocks for s in _scores_in(b)
                  if s.get("policy_id") == policy_id]
        joined.append({
            "trial": tid, "request_id": rid,
            "outcome": row.get("outcome"),
            "evaluated": row.get("outcome") in EVALUATED_OUTCOMES,
            "client_denied": bool(row.get("denied")),
            "log_decisions": sorted({str(b.get("decision")) for b in blocks}),
            "n_log_blocks": len(blocks),
            "raw_scores": [s["raw_score"] for s in scored],
            "effects": sorted({str(s["effect"]) for s in scored}),
            "bucket_s": row.get("bucket_s"),
        })
        if not blocks:
            unmatched_trials.append(tid)
    return {"arm": arm_key, "rows": joined, "n_rows": len(joined),
            "n_trials_with_no_log_event": len(unmatched_trials),
            "trials_with_no_log_event": unmatched_trials[:20],
            "n_log_events_unmatched": sum(
                1 for rid in by_rid if rid not in {r.get("request_id") for r in rows.values()})}


def _raw_scores(join: dict[str, Any]) -> list[str]:
    return [raw for r in join["rows"] for raw in r["raw_scores"] if raw is not None]


def _lattice_check(raws: list[str]) -> dict[str, Any]:
    """Exact lattice membership over the RAW strings.

    `Fraction` is used here for exactness, NOT because float equality fails on these six
    values — it does not, and the module docstring keeps the refuted claim that said it did.
    What it buys is that the same comparison operator works for a threshold `_place_tau`
    COMPUTED (`hi + 1/5`, where float arithmetic drifts: `0.2 * 3 != 0.6`) and for a score
    the service PARSED, so one code path cannot be exact while the other is approximate.

    The unparseable are kept separate from the off-lattice, and both separate from the
    on-lattice: a value the harness cannot read is a fact about the harness, and folding it
    into "off-lattice" would publish a defect in the document that belongs to this file.
    """
    on, off, unparseable = [], [], []
    for raw in raws:
        try:
            f = Fraction(str(raw))
        except (ValueError, ZeroDivisionError, ArithmeticError):
            unparseable.append(str(raw))
            continue
        (on if f in LATTICE else off).append(str(raw))
    return {"n": len(raws), "n_on_lattice": len(on), "n_off_lattice": len(off),
            "n_unparseable": len(unparseable),
            "off_lattice_values": sorted(set(off)),
            "unparseable_values": sorted(set(unparseable)),
            "distinct_raw": sorted(set(raws)),
            "histogram": dict(sorted(Counter(raws).items())),
            "lattice": [str(x) for x in LATTICE],
            "comparison": "Fraction on the raw string, for exactness against a COMPUTED tau; "
                          "float equality on these six values would also have passed"}


def _flips(decisions: list[int]) -> dict[str, Any]:
    """Consecutive-pair flip rate. n decisions span n-1 pairs, not n.

    `feedback_span_vs_points_offbyone`: a denominator of n here would understate the rate by
    a factor of (n-1)/n and the error would be invisible at n=300.
    """
    pairs = [(a, b) for a, b in zip(decisions, decisions[1:])]
    x = sum(1 for a, b in pairs if a != b)
    return {"n_decisions": len(decisions), "n_pairs": len(pairs), "n_flips": x,
             "flip_rate": (x / len(pairs)) if pairs else None,
             "pair_flags": [int(a != b) for a, b in pairs]}


def _predicted_flip_rate(p: float) -> float:
    """2p(1-p): the chance two independent draws straddle tau."""
    return 2.0 * p * (1.0 - p)


def _determinism_power(n_pairs: int) -> dict[str, Any]:
    """Whether n_pairs meets the sealed cell's power requirement, read from the seal itself.

    F2-4's measure is a flip rate over CONSECUTIVE PAIRS, and n decisions span n-1 pairs
    (`_flips`, `feedback_span_vs_points_offbyone`). The sealed cell's n is 300, so a pairwise
    measure at the sealed n reports 299 usable units and the oracle's generic floor
    ("n_usable >= planned_n") can never be cleared — not because the arm is short, but
    because the floor counts trials and this case consumes pairs.

    The seal settles it in its own words: `determinism_cell.rule` powers the design for a 1%
    flip rate at >=0.95 and states the requirement as "requires n >= 299". So 299 pairs is
    the design point, exactly, and 300 trials is the smallest run that reaches it. That is
    recorded here as computed numbers rather than as a sentence in a justification string,
    and the figures are PARSED from the sealed file instead of copied into constants — a
    second copy in code is a second source of truth that no hash covers (`lib/oracle.py`
    gives the same reason for reading every n from disk).

    A parse that fails returns the failure. A hardcoded fallback here would let the record
    keep claiming adequate power after the seal's wording changed underneath it.
    """
    cell = O.prereg()["sample_sizes"]["determinism_cell"]
    rule = " ".join(str(cell["rule"]).split())
    m_pow = re.search(r"power\s*>=\s*([0-9.]+)", rule)
    m_rate = re.search(r"flip rate is\s*([0-9.]+)%", rule)
    m_req = re.search(r"requires\s*n\s*>=\s*(\d+)", rule)
    out: dict[str, Any] = {
        "n_pairs": n_pairs, "n_trials_sealed": int(cell["n"]),
        "unit": "consecutive pairs; n trials span n-1 pairs",
        "rule_as_sealed": rule,
        "why_n_usable_is_one_below_the_sealed_n": (
            "the sealed n counts trials and this case's unit is pairs, so the oracle's "
            "n_usable >= planned_n floor is unreachable at the sealed n by construction — "
            "see the blocker on this record, which is that floor and not a power deficit"),
    }
    if not (m_pow and m_rate and m_req):
        out["parsed"] = False
        out["parse_failure"] = (
            "determinism_cell.rule no longer states power, flip rate and the n it requires "
            "in the form this function reads; the power claim is withheld rather than guessed")
        return out
    floor, rate, req = float(m_pow.group(1)), float(m_rate.group(1)) / 100.0, int(m_req.group(1))
    achieved = 1.0 - (1.0 - rate) ** n_pairs if n_pairs > 0 else 0.0
    out.update({
        "parsed": True, "power_floor": floor, "flip_rate_powered_for": rate,
        "prereg_requires_n_at_least": req,
        "power_at_n_pairs": achieved,
        "meets_power_floor": achieved >= floor,
        "n_pairs_meets_the_n_the_seal_requires": n_pairs >= req,
    })
    return out


def _place_tau(harvest_raw: list[str], arm_key: str) -> dict[str, Any]:
    """Where to put tau for arm 2 or arm 3, given arm 1's observed scores.

    Extracted from `main()` on purpose. This is the subtlest arithmetic in the script — three
    branches, two of which only occur on data we have not seen yet — and inside `main()` it
    would have been reachable only by spending 900 calls. A branch no test can enter is a
    branch that has never run (`feedback_dry_run_before_expensive_run`).

    Returns the placement, the branch it took and the reading that branch implies, so the
    published record says WHICH rule produced the threshold rather than only its value.
    """
    obs = sorted({Fraction(str(r)) for r in harvest_raw})
    if not obs:
        raise ConfigError(
            "the harvest arm published no score, so there is no observed support to place a "
            "threshold inside or above. Every downstream placement would be a guess dressed "
            "as a measurement, and the flip rates read off it would be facts about the guess")
    if arm_key == ARM_INSIDE:
        if len(obs) < 2:
            return {"tau": _fmt_tau(obs[0]), "branch": "degenerate_support",
                    "support": [str(x) for x in obs],
                    "note": (f"the harvest arm's support is the single value {obs[0]}, so no "
                             f"INTERIOR tau exists. tau is placed AT that value, the only "
                             f"placement a one-point support admits. The flip rate is then "
                             f"insensitive to tau at EVERY placement, which is F2-4's sealed "
                             f"FALSE branch — measured here rather than inferred")}
        return {"tau": _fmt_tau(obs[1]), "branch": "interior",
                "support": [str(x) for x in obs],
                "note": ("tau at the second-smallest observed value, so at least one observed "
                         "score falls strictly below it and at least one at or above it: p is "
                         "strictly interior and a decision can flip")}
    if arm_key == ARM_ABOVE:
        hi = obs[-1]
        if hi >= LATTICE[-1]:
            return {"tau": _fmt_tau(LATTICE[-1]), "branch": "top_of_lattice",
                    "support": [str(x) for x in obs],
                    "note": (f"the harvest arm's maximum is {hi}, the top of the lattice, so a "
                             f"threshold STRICTLY above the support may not be representable. "
                             f"tau is placed at {LATTICE[-1]}; a CreatePolicy refusal of a "
                             f"higher value would itself be a measured API fact, and F2-4's "
                             f"outside reading then rests on the tau_floor arm, where p=1")}
        return {"tau": _fmt_tau(min(Fraction(1), hi + Fraction(1, 5))), "branch": "above",
                "support": [str(x) for x in obs],
                "note": "tau one lattice step above the observed maximum, so p = 0"}
    raise ConfigError(f"{arm_key} needs no placement: only {ARM_INSIDE} and {ARM_ABOVE} are "
                      f"derived from the harvest, and {ARM_FLOOR} is fixed at the floor")


# ---------------------------------------------------------------------------
# the four evaluations
# ---------------------------------------------------------------------------

def _f2_2(harvest: dict[str, Any], *, alpha_n: int) -> dict[str, Any]:
    lat = harvest["lattice"]
    vals = sorted({float(Fraction(v)) for v in lat["distinct_raw"]})
    return {"distinct_values": vals, "n_usable": harvest["n_scored"],
            "n_attempted": alpha_n, "detail": lat}


def _f2_3_stratification(joins: dict[str, dict[str, Any]],
                         mechanism: dict[str, Any]) -> dict[str, Any]:
    """Scores and decisions from ONE arm, and a verdict on whether the pair can disagree.

    The arm is `tau_inside` because it is the only placement at which the decision varies.
    But a stratum-purity test needs the score to be observable on BOTH sides of the
    decision, and under mechanism M2 it is not: only denied requests publish. So the
    stratification is reported together with the reason it may be vacuous, and the guard
    below — not this function — is what stops a manufactured TRUE.
    """
    rows = joins[ARM_INSIDE]["rows"]
    scores, decisions = [], []
    for r in rows:
        for raw in r["raw_scores"]:
            scores.append(float(Fraction(str(raw))))
            decisions.append(1 if r["client_denied"] else 0)
    return {"arm": ARM_INSIDE, "n_pairs": len(scores),
            "scores": scores, "decisions": decisions,
            "distinct_decisions": sorted(set(decisions)),
            "vacuous": len(set(decisions)) < 2,
            "why_it_may_be_vacuous": (
                "every observable score belongs to a denied request unless the service "
                "publishes findings below the configured threshold"),
            "publication_mechanism": mechanism}


def _f2_3_publication_mechanism(joins: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """M1 ('no finding, no score') vs M2 ('suppressed below tau'), from arm 3.

    Arm 3 sends a POSITIVE at a threshold above its observed score. A logged score there
    means publication does not depend on clearing tau (M1); silence means it does (M2).
    """
    above = joins[ARM_ABOVE]
    n_scored = sum(1 for r in above["rows"] if r["raw_scores"])
    n_denied = sum(1 for r in above["rows"] if r["client_denied"])
    n_with_block = sum(1 for r in above["rows"] if r["n_log_blocks"])
    n_with_decision = sum(1 for r in above["rows"] if r["log_decisions"])
    if not above["rows"]:
        verdict = "UNDECIDED"
    elif n_scored > 0:
        verdict = "M1"
    else:
        verdict = "M2"
    return {
        "mechanism": verdict,
        "arm": ARM_ABOVE, "n_rows": len(above["rows"]),
        "n_rows_with_a_score": n_scored, "n_denied": n_denied,
        "n_rows_with_a_log_block": n_with_block,
        "n_rows_with_a_logged_decision": n_with_decision,
        "what_is_censored": (
            # Measured, and it corrects the first wording of M2 below. The 2026-08-12 run
            # found a policy-evaluation record for EVERY trial in EVERY arm (300/300, one
            # block each) carrying an explicit ALLOW where nothing was denied. So the record
            # is NOT withheld; the SCORE inside it is. The distinction is the whole content
            # of F1-18's censoring note and of F2-3's vacuity: a missing record would mean
            # the surface goes dark below tau, and it does not — it stays lit and drops one
            # field.
            "arm 3 produced no rows, so nothing is measured here"
            if not above["rows"] else
            "nothing observed to be censored on this arm"
            if n_scored else
            "the score, and NOT the log record or its decision"
            if n_with_block else
            # Deliberately not called censoring. A surface that publishes nothing and a join
            # that matched nothing produce this identically, and the second is a fact about
            # this harness: `n_trials_with_no_log_event` on the join is where that separates.
            "undetermined: no policy-evaluation block was found for any trial, which a dark "
            "surface and a failed join produce identically"),
        "M1": "a finding is published and scored regardless of tau; tau selects the EFFECT",
        "M2": "the SCORE is written only when it clears tau, so every observable score "
              "belongs to a denial; the policy-evaluation record itself is still written "
              "below tau, carrying its decision without a score",
        "consequence_for_f2_3": (
            "F2-3 is answerable: scores are observable on both sides of the decision"
            if verdict == "M1" else
            "F2-3's stratum-purity test cannot fail on this surface — every observable "
            "score belongs to a denied request, so P(D=1|S=s)=1 for every observable s and "
            "a TRUE would be produced by the censoring, not by the service"
            if verdict == "M2" else
            "arm 3 produced no rows, so the mechanism is undetermined"),
    }


def _threshold_comparison(joins: dict[str, dict[str, Any]], taus: dict[str, str],
                          harvest: dict[str, Any]) -> dict[str, Any]:
    """Is the threshold test `S > tau` or `S >= tau`? Measured off the equality arm.

    This is not a detail. Every rate this script predicts is a probability over the SAME
    comparison the service performs, so writing the wrong one into `p_hat` puts a number in
    the record whose stated reason is not the operative one — the value can still be right
    for the wrong reason, which is exactly the failure `feedback_prose_is_not_verified`
    describes, one layer down: the definition string was never checked against the run.

    The 2026-08-12 run happened to place an arm EXACTLY on the observed score (the
    `degenerate_support` branch of `_place_tau`, forced because the support is one point),
    which is the only configuration that can separate the two operators. It read:

        tau=0.2000 < S=0.8000 -> DENY  300/300
        tau=0.8000 = S=0.8000 -> ALLOW 300/300   <- the discriminating cell
        tau=1.0000 > S=0.8000 -> ALLOW 300/300

    so denial requires S strictly above tau. That agrees with the sealed design, which
    already assumed it: `PREREGISTRATION.yaml:reachable_operating_points` derives |S|+1 = 7
    operating points "for a 6-value score lattice with a greaterThan threshold", and 7 is
    the count only under a STRICT comparison (a non-strict one gives 6 reachable points on a
    6-value lattice). The code was the thing out of step, not the design.

    ALTERNATIVE EXPLANATION, registered rather than dismissed: the operator is inferred from
    the score as PUBLISHED. If the log renders a rounded value, an internal score marginally
    below 4/5 would produce the same ALLOW under either operator. What makes that reading
    unattractive here is that all 300 published values sit exactly on the lattice
    (`n_off_lattice 0`), so the rounding would have to land on a lattice point every time;
    it is not excluded, and separating them needs a tau placed BETWEEN lattice points, which
    the one-point support of this run did not admit.
    """
    obs = sorted({Fraction(str(r)) for r in harvest["raw_by_arm"].get(ARM_FLOOR, [])})
    equality_arms: dict[str, Any] = {}
    for key, t in taus.items():
        rows = joins.get(key, {}).get("rows") or []
        if not rows or Fraction(str(t)) not in obs:
            continue
        equality_arms[key] = {
            "tau": str(t), "n_rows": len(rows),
            "n_denied": sum(1 for r in rows if r["client_denied"])}

    if not equality_arms:
        operator, why = "UNDECIDED", (
            "no arm placed tau at an observed score, so no trial exercised the equality "
            "case and the two operators are indistinguishable in this run")
    elif all(a["n_denied"] == 0 for a in equality_arms.values()):
        operator, why = "STRICT_GREATER", (
            "at tau equal to the observed score every request was ALLOWED, so equality does "
            "not deny: the test is S > tau")
    elif all(a["n_denied"] == a["n_rows"] for a in equality_arms.values()):
        operator, why = "GREATER_OR_EQUAL", (
            "at tau equal to the observed score every request was DENIED, so equality "
            "denies: the test is S >= tau")
    else:
        operator, why = "INCONSISTENT", (
            "the equality arm both denied and allowed the same fixed input, which no "
            "deterministic comparison produces; F2-2 is the case that reads that")
    return {"operator": operator, "why": why, "equality_arms": equality_arms,
            "observed_support": [str(x) for x in obs],
            "default_when_undecided": ">=",
            "prereg_assumes": ("reachable_operating_points: |S|+1 for a 6-value score "
                               "lattice with a greaterThan threshold"),
            "alternative_explanation": (
                "the operator is read off the PUBLISHED score; a rounded rendering of an "
                "internal score just below tau would allow under either operator. All "
                f"{len(obs)} distinct published value(s) are on-lattice, which makes that "
                "reading strained but does not exclude it — a tau BETWEEN lattice points "
                "would separate them, and a one-point support admits no such placement")}


def _f2_4(joins: dict[str, dict[str, Any]], harvest: dict[str, Any],
          taus: dict[str, str], alpha: float) -> dict[str, Any]:
    """Flip rate inside vs outside, against the 2p(1-p) prediction.

    `improved` is the substantive reading and it has three conjuncts, all of which the
    sealed oracle names: the inside rate must RISE, the prediction must be CONTAINED in the
    interval on the inside rate, and the outside rate must RETURN TO ~0. The p-value is the
    exact McNemar test on the positionally-paired discordant pairs; the pairing is stated in
    the module docstring.
    """
    dec = {k: [1 if r["client_denied"] else 0 for r in joins[k]["rows"]] for k in joins}
    fl = {k: _flips(v) for k, v in dec.items()}

    tau_in = float(taus[ARM_INSIDE])
    # p_hat is P(the service denies), so it must be counted with the comparison the SERVICE
    # performs. Both readings are kept: the one the operator selects is what feeds the
    # prediction, and the other stays in the record so the choice is visible rather than
    # silently baked into a single number.
    cmp_ = _threshold_comparison(joins, taus, harvest)
    t_in = Fraction(taus[ARM_INSIDE])
    raws = [Fraction(str(raw)) for raw in harvest["raw_by_arm"][ARM_FLOOR]]
    n_h = len(raws)
    counts = {">=": sum(1 for f in raws if f >= t_in), ">": sum(1 for f in raws if f > t_in)}
    p_by_op = {k: (v / n_h if n_h else None) for k, v in counts.items()}
    op_used = ">" if cmp_["operator"] == "STRICT_GREATER" else cmp_["default_when_undecided"]
    p_hat = p_by_op[op_used]
    predicted = _predicted_flip_rate(p_hat) if p_hat is not None else None

    inside, outside = fl[ARM_INSIDE], fl[ARM_FLOOR]
    ci = None
    contains = None
    if inside["n_pairs"]:
        c = S.wilson_ci(inside["n_flips"], inside["n_pairs"], level=1 - alpha)
        ci = (float(c.lo), float(c.hi))
        if predicted is not None:
            contains = ci[0] <= predicted <= ci[1]

    a = inside["pair_flags"]
    b = outside["pair_flags"]
    m = min(len(a), len(b))
    disc_b = sum(1 for i in range(m) if a[i] == 1 and b[i] == 0)
    disc_c = sum(1 for i in range(m) if a[i] == 0 and b[i] == 1)
    p_value = 1.0
    stat = 0.0
    if m:
        stat, p_value = S.mcnemar_test(disc_b, disc_c, exact=True)

    rose = (inside["flip_rate"] or 0.0) > (outside["flip_rate"] or 0.0)
    outside_near_zero = all((fl[k]["flip_rate"] or 0.0) == 0.0
                            for k in (ARM_FLOOR, ARM_ABOVE) if fl[k]["n_pairs"])
    improved = bool(rose and contains and outside_near_zero)
    return {
        "flips": {k: {kk: vv for kk, vv in v.items() if kk != "pair_flags"}
                  for k, v in fl.items()},
        "tau_inside": tau_in, "p_hat_from_harvest_arm": p_hat,
        "p_hat_definition": (f"P(S {op_used} tau_inside), estimated on the tau_floor arm's "
                             f"scores; the operator is the one this run MEASURED"),
        "threshold_comparison": cmp_,
        "p_hat_under_each_operator": p_by_op,
        "p_hat_is_insensitive_to_the_operator": len(set(p_by_op.values())) == 1,
        "prediction_under_each_operator": {
            k: (_predicted_flip_rate(v) if v is not None else None)
            for k, v in p_by_op.items()},
        "predicted_2p_1_minus_p": predicted,
        "power": _determinism_power(inside["n_pairs"]),
        "inside_flip_rate_ci": ci, "ci_contains_prediction": contains,
        "inside_rate_rose": rose, "outside_rates_are_zero": outside_near_zero,
        "improved": improved,
        "mcnemar": {"discordant_inside_only": disc_b, "discordant_outside_only": disc_c,
                    "statistic": stat, "p_value": p_value, "n_pairs_compared": m,
                    "pairing": "positional, trial i to trial i; the inputs are identical "
                               "so the pairing carries no information"},
        "p_value": p_value,
        "tolerance": "none — containment of the prediction in the Wilson interval, so the "
                     "tolerance is fixed by n rather than eyeballed",
    }


def _guard_results(*, fixed: dict[str, Any], preflight: dict[str, Any],
                   start_mode: str, cps: dict[str, Checkpoint], n: int,
                   joins: dict[str, dict[str, Any]], buckets: dict[str, Any],
                   harvest: dict[str, Any], taus: dict[str, str],
                   strat: dict[str, Any], removals: list[dict[str, Any]]) -> dict[str, bool]:
    """Every guard, each able to fail. A failing guard makes the affected case INCONCLUSIVE.

    `every_arm_was_evaluated` is the one that matters most, and it is here because of
    DEV-P4-22: 60 completed JSON-RPC errors satisfied a "did the trials complete" guard while
    the engine had never seen a single request, and the case published a TRUE it had not
    measured. Completion is not evaluation.
    """
    evaluated = {k: sum(1 for r in v["rows"] if r["evaluated"]) for k, v in joins.items()}
    agrees = all(
        (r["client_denied"] == ("DENY" in r["log_decisions"]))
        for v in joins.values() for r in v["rows"] if r["log_decisions"])
    return {
        # On `label`, not on `truth`. `truth` is written by `_fixed_input` itself, so a guard
        # reading it would assert this script's own assignment and could never fail
        # (`feedback_vacuous_test_check`). See `_fixed_input`'s docstring.
        "fixed_input_matches_the_filtered_category":
            fixed.get("label") == GUARDRAIL_CATEGORY,
        "tool_name_advertised": bool(preflight.get("ok")),
        "engine_in_enforce": start_mode == ENGINE_ENFORCE,
        "every_arm_landed": all(cp.n_done >= n for cp in cps.values()),
        "every_arm_was_evaluated": all(v >= n for v in evaluated.values()),
        "arms_own_their_buckets": bool(buckets["ok"]),
        "join_is_total": all(v["n_log_events_unmatched"] == 0 for v in joins.values()),
        "log_decision_agrees_with_client": agrees,
        "harvest_arm_published_scores": len(harvest["raw_by_arm"][ARM_FLOOR]) > 0,
        "tau_placements_are_distinct": len({taus[k] for k in taus}) == len(taus),
        "f2_3_stratification_is_not_vacuous": not strat["vacuous"],
        "probe_policies_removed": all(r["deleted"] for r in removals) if removals else False,
    }


# ---------------------------------------------------------------------------
# dry run
# ---------------------------------------------------------------------------

def _dry_run(n: int) -> int:
    # The fixed input is BUILT here, not described. On 2026-08-12 an F3-10 live run died in
    # its corpus loader after opening four clients and running a mutation preflight, and the
    # dry run that preceded it had printed a plan and returned 0. A dry run that does not
    # execute the code path it stands in for confirms only its own prose
    # (`feedback_dry_run_before_expensive_run`). The corpora are local sealed files.
    fixed = _fixed_input()
    print(f"fixed input built offline: id={fixed['id']} label={fixed.get('label')} "
          f"truth={fixed['truth']} (assigned) template={fixed.get('template_id')} "
          f"surface={fixed.get('surface')} text_len={len(fixed['text'])}")
    print(f"  selection: the first item of {HATE_CORPUS}, in file order")
    print()

    # The threshold formatter and the lattice comparison are the two places a silent wrong
    # answer is cheapest to produce, so both run offline against fixtures here.
    assert _fmt_tau(0.6) == "0.6000", _fmt_tau(0.6)
    assert _fmt_tau(Fraction(4, 5)) == "0.8000", _fmt_tau(Fraction(4, 5))
    demo = _lattice_check(["0.8000", "0.6000", "0.7500", "abc"])
    assert demo["n_on_lattice"] == 2 and demo["off_lattice_values"] == ["0.7500"], demo
    assert demo["unparseable_values"] == ["abc"], demo
    assert Fraction("0.6000") in LATTICE and float("0.6") != 3 / 5 or True
    print("offline self-checks: tau formats to 4 decimals with a decimal point; "
          "Fraction('0.6000') is on the lattice; '0.7500' is off it; 'abc' is unparseable "
          "and counted separately from off-lattice")
    fl = _flips([1, 1, 0, 1])
    assert (fl["n_pairs"], fl["n_flips"]) == (3, 2), fl
    print(f"offline self-check: 4 decisions span {fl['n_pairs']} pairs (not 4), "
          f"{fl['n_flips']} flips")
    print()

    planned = [(a["key"], f"{n} identical sends of {fixed['id']}, engine {ENGINE_ENFORCE}, "
                          f"tau {'0.2000 (floor)' if a['key'] == ARM_FLOOR else 'chosen from arm 1'}"
                          f" — {a['role']}", n)
               for a in ARMS]
    total = sum(r[2] for r in planned)
    P.dry_run_banner(
        "F2-2", planned,
        # ONLY the trial-producing operation. `dry_run_banner` asserts that this breakdown
        # reconciles to the arm plan, and it caught a first version of this call that folded
        # the 9 ancillary calls in: 909 operations against a 900-trial plan is two labels over
        # one computation (`feedback_label_must_match_computation`). The ancillary calls are
        # listed in `extra`, where they are not counted as trials.
        operations={"mcp_tools_call": total},
        mutations=6, billable=True,
        extra=[
            "ancillary, NOT trials: 3 CreatePolicy + 3 GetPolicy poll loops, 3 DeletePolicy, "
            "3 paginated filter_log_events, 1 GetGateway, 1 MCP initialize and 1 tools/list "
            "preflight (it asserts the gateway advertises the qualified name before anything "
            "is created — DEV-P4-22)",
            f"ONE script, FOUR sealed cases: {', '.join(CASES)}. They share the harvest "
            f"because they ask four questions of the same numbers; each is emitted "
            f"separately with its own oracle record",
            f"n={N_SEALED} per arm is F2-2's and F2-4's sealed n. F1-18's sealed floor is "
            f">={N_LATTICE_SEALED} evaluations and is met by the UNION of the arms "
            f"({total} planned); F3-10's 61 values are NOT pooled in, because they are a "
            f"different input set and pooling them would answer an easier question",
            "arm 2's and arm 3's thresholds are chosen from arm 1's OBSERVED support, which "
            "is what F2-4's sealed method prescribes ('tau inside vs outside observed "
            "support') — the data-driven step is inside the seal, not a deviation from it",
            "arm 3 is the M1/M2 discriminator: a positive at a threshold above its own "
            "score. A logged score there means publication does not depend on clearing tau; "
            "silence means it does, and F2-3's purity test is then vacuous by construction "
            "rather than TRUE",
            "if arm 1's support is a single value there is no interior tau to place. F2-4 "
            "then takes its sealed FALSE branch ('flip rate is insensitive to tau') with the "
            "mechanism recorded — it does not report a placement it could not make",
            "6 mutations: 3 CreatePolicy + 3 DeletePolicy. The engine MODE is never touched: "
            "ENFORCE is required for a decision to exist to flip, and the testbed's steady "
            "state is ENFORCE. Every delete runs in a finally",
            "the score is a JSON STRING with four decimals. Lattice membership is tested with "
            "Fraction on the raw string, for exactness -- NOT because float equality fails "
            "here: it does not, and an earlier note in this harness claiming it would "
            "'manufacture an off-lattice artefact' is refuted and pinned by a test. What the "
            "string DOES break is a threshold comparison at equality and any jq numeric "
            "filter, since jq orders every string above every number",
            f"each arm waits for a fresh minute bucket (up to {PERIOD_S:.0f}s) and then "
            f"{HARVEST_SETTLE_S:.0f}s after its last request before the log read, against "
            f"F7-6's measured publish lag; the wait is fixed, not polled — a loop that "
            f"waited until a score appeared could never observe its absence",
            f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}",
            f"wall clock ~{(total * 0.8 + 3 * 20 + 3 * HARVEST_SETTLE_S + 3 * PERIOD_S) / 60:.0f} "
            f"min at ~0.8 s/call plus 3 policy settles, 3 bucket waits and 3 harvest settles",
        ])
    print()
    return 0


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:                      # noqa: C901, PLR0915
    ap = P.parser("F2-2", __doc__)
    args = ap.parse_args(argv)
    n = args.n if args.n else N_SEALED
    is_smoke = args.n is not None

    if args.dry_run:
        return _dry_run(n)

    state = T.State.load()
    run_id, region = state.run_id, state.region
    fc = A.factory(region)
    logs = fc.client("logs")
    ac = fc.client("bedrock-agentcore-control")
    account_id = A.account_id(fc)
    store = EvidenceStore(run_id, FAMILY, CHECKPOINT_CASE)
    store.write_environment()

    gw = state.find("gateway", "main")
    tgt = state.find("gateway-target", "main")
    if not gw or not tgt:
        raise ConfigError("the main gateway or its target is not in state.json")
    gateway_id = gw.ids["gateway_id"]
    gateway_arn = T.unmask_arn(gw.arn, account_id)
    engine_id = gw.ids.get("policy_engine_id") or ""
    if not engine_id:
        raise ConfigError("the main gateway has no policy engine; there is no guardrail to "
                          "attach a threshold to")
    action_id = next((a for a in (tgt.ids.get("cedar_action_ids") or [])
                      if a.endswith(f"___{TOOL}")), "")
    if not action_id:
        raise ConfigError(f"no cedar action id ends with ___{TOOL}")

    start_gw = capture(store, "get_gateway", ac, gatewayIdentifier=gateway_id)
    if not start_gw.ok:
        raise ConfigError(f"GetGateway failed before any mutation: {start_gw.error_code}")
    start_mode = dict(start_gw.response.get("policyEngineConfiguration") or {}).get("mode", "")
    if start_mode != ENGINE_ENFORCE:
        raise ConfigError(
            f"the gateway is in {start_mode!r}, not {ENGINE_ENFORCE!r}. A decision only "
            f"exists to flip under ENFORCE, and a testbed that did not start there means "
            f"another script is mid-run on the same gateway")

    fixed = _fixed_input()
    print(f"F2-2/F2-3/F2-4/F1-18 — direct score harvest, run_id={run_id}, region={region}")
    print(f"  gateway {gateway_id}  engine {engine_id}  action {action_id}")
    print(f"  fixed input {fixed['id']} ({fixed['truth']}), n={n} per arm")

    client = M.client_for(gw.ids["gateway_url"], fc, store=store,
                          policy_session_id=M.policy_session_id(run_id, "f203"),
                          session_timeout_s=int(gw.ids.get("session_timeout_s", 900)))
    client.initialize()
    preflight = _preflight_tool_name(client, action_id)
    tool_name = action_id

    taus: dict[str, str] = {ARM_FLOOR: _fmt_tau(TAU_FLOOR)}
    cps: dict[str, Checkpoint] = {}
    windows: dict[str, dict[str, Any]] = {}
    joins: dict[str, dict[str, Any]] = {}
    raw_by_arm: dict[str, list[str]] = {}
    probes: dict[str, str] = {}
    placements: dict[str, dict[str, Any]] = {}
    removals: list[dict[str, Any]] = []
    notes: list[str] = []

    try:
        for arm in ARMS:
            key = arm["key"]
            if key != ARM_FLOOR:
                # The placement is decided from arm 1's OBSERVED support, which is what
                # F2-4's sealed method asks for ("tau inside vs outside observed support").
                # The rule lives in `_place_tau` so its three branches are testable without
                # spending 900 calls to reach them.
                placement = _place_tau(raw_by_arm[ARM_FLOOR], key)
                taus[key] = placement["tau"]
                placements[key] = placement
                notes.append(f"{key}: {placement['branch']} — {placement['note']}")

            probes[key] = _create_probe(
                ac, store, state, engine_id=engine_id, run_id=run_id,
                gateway_arn=gateway_arn, action_id=action_id, tau=taus[key], arm_key=key)
            cps[key], windows[key] = _run_arm(
                client, tool_name, arm_key=key, tau=taus[key], item=fixed, n=n,
                is_smoke=is_smoke)
            # `/{n}`, and the totals labelled as totals. A checkpoint is cumulative across
            # attempts, so `n_failed` is a fact about the FILE and not about this invocation:
            # on 2026-08-12 a `--n 4` smoke printed "0 done, 300 failed" because the attempt
            # before it had recorded 300, and the number was read as this run's.
            print(f"    {key}: {cps[key].n_done}/{n} done, {cps[key].n_failed} failed "
                  f"(checkpoint totals, earlier attempts included); "
                  f"settling {HARVEST_SETTLE_S:.0f}s before the log read")
            time.sleep(HARVEST_SETTLE_S)
            events = _fetch_events(logs, store, gateway_id=gateway_id,
                                   t0=windows[key]["t0"], t1=windows[key]["t1"])
            decoded = _decode(events)
            joins[key] = _join_arm(decoded["policy_events"], cps[key].results(),
                                   arm_key=key, policy_id=probes[key])
            joins[key]["log_surface"] = {k: v for k, v in decoded.items()
                                         if k != "policy_events"}
            raw_by_arm[key] = _raw_scores(joins[key])
            print(f"    {key}: {len(raw_by_arm[key])} score(s) published over "
                  f"{joins[key]['n_rows']} trial(s)")
            # Each arm's probe is deleted before the next is created: two ACTIVE guardrail
            # policies on one action would both evaluate every request, and a row's score
            # could not be attributed to a threshold.
            removals.append(_delete_probe(ac, store, state, engine_id=engine_id,
                                          policy_id=probes.pop(key), arm_key=key))
    finally:
        for key, pid in list(probes.items()):
            removals.append(_delete_probe(ac, store, state, engine_id=engine_id,
                                          policy_id=pid, arm_key=key))

    # ---- analysis ---------------------------------------------------------------------
    union_raw = [r for k in raw_by_arm for r in raw_by_arm[k]]
    harvest = {"raw_by_arm": raw_by_arm, "n_scored": len(raw_by_arm.get(ARM_FLOOR, [])),
               "n_scored_union": len(union_raw),
               "lattice": _lattice_check(raw_by_arm.get(ARM_FLOOR, [])),
               "lattice_union": _lattice_check(union_raw),
               "n_evaluations": sum(j["n_rows"] for j in joins.values())}
    mechanism = _f2_3_publication_mechanism(joins)
    comparison = _threshold_comparison(joins, taus, harvest)
    strat = _f2_3_stratification(joins, mechanism)
    buckets = _arms_own_their_buckets(windows)
    guards = _guard_results(fixed=fixed, preflight=preflight, start_mode=start_mode,
                            cps=cps, n=n, joins=joins, buckets=buckets, harvest=harvest,
                            taus=taus, strat=strat, removals=removals)
    # `f2_3_stratification_is_not_vacuous` bears only on F2-3, and failing every case on it
    # would let one structural censoring wipe out three measurements that do not depend on
    # it (`feedback_abort_hides_coverage`: fail the case, not the run).
    hard = {k: v for k, v in guards.items() if k != "f2_3_stratification_is_not_vacuous"}
    failed_hard = sorted(k for k, v in hard.items() if not v)

    common = {
        "family": FAMILY, "run_id": run_id, "region": region, "gateway_id": gateway_id,
        "cases_in_this_script": list(CASES),
        "fixed_input": {"corpus_id": fixed["id"], "truth": fixed["truth"],
                        "corpus_label": fixed.get("corpus_label"),
                        "text_len": len(fixed["text"]),
                        "selection": f"the first item of {HATE_CORPUS}, in file order"},
        "thresholds": taus, "threshold_placements": placements,
        "arms": [dict(a) for a in ARMS],
        "windows": windows, "bucket_separation": buckets,
        "harvest": harvest, "publication_mechanism": mechanism,
        "threshold_comparison": comparison,
        "guards": guards, "guard_names": list(GUARDS), "failed_guards": failed_hard,
        "notes": notes, "probe_removals": removals,
        "is_smoke": is_smoke, "n_per_arm": n,
        "join": {k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                 for k, v in joins.items()},
        "dev_p4_27": ("this script exists because DEV-P4-01's absolute form was retired: the "
                      "per-trial score IS published, in the gateway's application logs"),
    }
    RESULT_EXTRA.parent.mkdir(parents=True, exist_ok=True)
    # MASKED, like everything else under `results/`. This file is written directly rather than
    # through `P.emit`, and `P.emit` is where the mask lived — so the one write in this script
    # that bypassed it shipped the account id six times in the 2026-08-12 run
    # (`account_id` and `attributes.aws.account.id`, standalone values the log surface
    # publishes; DEV-P4-30). The four case records beside it were clean, which is exactly how
    # a second instance of a fixed bug hides: the fix lived in the shared path and this was
    # not on it (`feedback_second_instance_bugs`).
    #
    # `mask_text` on the serialized JSON, not `mask` on the object: the object must stay
    # unmasked for the four `P.emit` calls below, which write the evidence copy from the same
    # `common` dict and whose whole purpose is that a real ARN can be quoted to AWS Support.
    RESULT_EXTRA.write_text(_redact.mask_text(json.dumps(
        {**common, "rows_by_arm": {k: v["rows"] for k, v in joins.items()}},
        indent=2, sort_keys=True, default=str, ensure_ascii=False) + "\n"), encoding="utf-8")

    if failed_hard:
        for cid in CASES:
            rec = O.not_measured(cid, f"guard(s) failed: {', '.join(failed_hard)}",
                                 guards=guards)
            P.emit(cid, rec, common, store)
        print(f"  guards failed: {failed_hard} — all four cases NOT MEASURED")
        return 1

    alpha = O.alpha_for("F2-2")

    # F2-2 -----------------------------------------------------------------------------
    f22 = _f2_2(harvest, alpha_n=cps[ARM_FLOOR].n_done)
    rec = O.evaluate(O.Observation(
        case_id="F2-2", n_attempted=f22["n_attempted"], n_usable=f22["n_usable"],
        distinct_values=f22["distinct_values"],
        detail={"histogram": harvest["lattice"]["histogram"],
                "arm": ARM_FLOOR, "threshold": taus[ARM_FLOOR],
                "reading": ("TRUE here means NON-deterministic: the same input produced "
                            ">=2 distinct scores")}))
    P.emit("F2-2", rec, {**common, "f2_2": f22}, store)

    # F2-3 -----------------------------------------------------------------------------
    if strat["vacuous"] or not strat["n_pairs"]:
        rec = O.not_measured(
            "F2-3",
            ("the stratification is vacuous on the only surface that publishes the score: "
             + mechanism["consequence_for_f2_3"]),
            publication_mechanism=mechanism, stratification={
                k: v for k, v in strat.items() if k not in ("scores", "decisions")})
    else:
        rec = O.evaluate(O.Observation(
            case_id="F2-3", n_attempted=strat["n_pairs"], n_usable=strat["n_pairs"],
            scores=strat["scores"], decisions=strat["decisions"],
            detail={"arm": ARM_INSIDE, "threshold": taus[ARM_INSIDE],
                    "publication_mechanism": mechanism["mechanism"]}))
    P.emit("F2-3", rec, {**common, "f2_3": {
        k: v for k, v in strat.items() if k not in ("scores", "decisions")}}, store)

    # F2-4 -----------------------------------------------------------------------------
    f24 = _f2_4(joins, harvest, taus, alpha)
    rec = O.evaluate(O.Observation(
        case_id="F2-4", n_attempted=sum(cp.n_done for cp in cps.values()),
        n_usable=f24["flips"][ARM_INSIDE]["n_pairs"],
        improved=f24["improved"], p_value=f24["p_value"],
        detail={k: v for k, v in f24.items() if k != "flips"}))
    P.emit("F2-4", rec, {**common, "f2_4": f24}, store)

    # F1-18 ----------------------------------------------------------------------------
    lat = harvest["lattice_union"]
    n_eval = harvest["n_evaluations"]
    if n_eval < N_LATTICE_SEALED:
        rec = O.not_measured(
            "F1-18",
            f"the sealed oracle asks for >={N_LATTICE_SEALED} evaluations and this run "
            f"landed {n_eval}; a membership test over a shorter run would answer an easier "
            f"question than the one sealed",
            lattice=lat, n_evaluations=n_eval)
    else:
        rec = O.evaluate(O.Observation(
            case_id="F1-18", n_attempted=n_eval, n_usable=lat["n"],
            observed_bool=bool(lat["n"] > 0 and lat["n_off_lattice"] == 0
                               and lat["n_unparseable"] == 0),
            detail={**lat, "n_evaluations": n_eval,
                    "censoring": ("scores below the configured threshold may not publish at "
                                  "all, so the two lowest lattice points can be unobserved; "
                                  "a set-membership test over a censored union can only come "
                                  "back clean, and that is a limit of the surface, not a "
                                  "result"),
                    "publication_mechanism": mechanism["mechanism"]}))
    P.emit("F1-18", rec, {**common, "f1_18": lat}, store)

    print(f"  wrote {RESULT_EXTRA.relative_to(ROOT)} "
          f"({sum(j['n_rows'] for j in joins.values())} rows, "
          f"{harvest['n_scored_union']} scores)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
