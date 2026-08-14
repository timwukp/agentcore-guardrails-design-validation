#!/usr/bin/env python3
"""F3-11 — "past evaluation results do not guarantee future behavior", measured by re-running.

The claim (§3.2 item 5, and again as §8 checklist item 26):

    AWS periodically and automatically updates the underlying guardrail models ("Updates apply
    automatically and require no action on your part"). Maintain a regression test set and
    re-validate guardrail behavior on a schedule — past evaluation results do not guarantee
    future behavior.

Sealed oracle: `PAIRED_IMPROVEMENT`, with the binding's own note — *"drift is TRUE; direction is
not predicted."* So the measurement is: send ONE fixed set of items through ONE fixed guardrail
configuration on day 0, send the identical items through the identical configuration later, and
pair them item by item.

WHY THIS SCRIPT'S SCHEDULE IS NOT WAIVED, WHEN THE PROJECT'S REPLICATION RULE IS
--------------------------------------------------------------------------------
DEV-P4-02 waives the project's two-separate-calendar-days replication rule, because that rule is
**procedural** — it exists to catch a transient service state, and every case it applies to can
be re-run at any time to the same effect.

F3-11 is the one case where the wait IS the instrument. "Behaviour on day 0 equals behaviour on
day 0" is not a measurement of anything; the quantity is a difference across elapsed time, and no
amount of compute substitutes for the elapsed time. So this script runs the day-0 arm now, writes
a **snapshot** that outlives this session, and leaves the later arms as one command:

    # today, once
    python3 f3_efficacy/07_model_drift.py

    # 2026-08-18 and 2026-09-10, once each — no arguments to remember
    python3 f3_efficacy/07_model_drift.py --compare

`--compare` finds the earliest snapshot on disk, re-sends exactly the items it recorded, and
publishes the verdict. A run with no snapshot on disk refuses rather than silently baselining
itself, because a baseline collected today and compared against today is the vacuous result this
case is most likely to publish by accident.

WHY `--early-read` EXISTS, AND WHY IT IS NOT `--compare` WITH A SHORTER WAIT
---------------------------------------------------------------------------
There are two different objections to running the pairing early, and only one of them is about
the calendar. The first is vacuity: comparing a day against itself measures nothing. That
objection is quantitative, it is enforced by `interval_elapsed` against `MIN_INTERVAL_DAYS`, and
it stops applying once a real interval has elapsed. The second is that the SEALED oracle names
its interval --- *"TRUE if the +7d or +30d re-run differs from baseline"* --- so a pairing over
any other interval is a measurement of a different quantity, however many days it spans.

`--early-read` answers the first objection and respects the second. It runs the identical
collection and the identical pairing, and it writes the result to `results/F3-11-early-read-*`
with no oracle record, so `results/phase1/F3-11.json` keeps its day-0 `not_measured` and the +7d
run stays due. The exclusion is on the interval, which was fixed before the numbers existed ---
not on the result, which is why the early read is recorded in full rather than discarded.

What it buys: a drift visible at +3d is already a finding about the recommended CADENCE, which is
the only amendment any F3-11 result supports. And it exercises the pairing path once while there
is still time to repair it, rather than finding a defect in it on 2026-09-10 with a 30-day
interval on the line and no way to re-collect the baseline.

WHAT DRIFT IS MEASURED ON — AND WHY NOT ON SCORES
-------------------------------------------------
The most sensitive drift instrument would be a per-item numeric score: a model update that
nudged a score from 0.61 to 0.58 would show up long before it changed a decision. DEV-P4-01
records why that instrument does not exist here — no measured surface publishes a per-trial
numeric guardrail score. `ApplyGuardrail` returns content-filter confidence as an **enum**
(`LOW`/`MEDIUM`/`HIGH`), not a number.

So drift is measured on what the service does publish, at three levels of sensitivity, with the
**primary declared here before any data**:

    PRIMARY (scored)        per-item `hit` — did the filter catch the thing the item is labelled
                            as? McNemar's exact test on the discordant pairs. This is the
                            quantity every §3 claim is about and the quantity a reader's
                            regression suite would assert on.

    SECONDARY (recorded)    the full response fingerprint: top-level `action`, the sorted
                            detected/blocked type lists, the confidence enums, the PII type and
                            action lists, the topics and words matched, and which policy blocks
                            the service returned. Any change here is drift even when `hit` is
                            unchanged — a category that starts firing at HIGH instead of MEDIUM
                            is a model update, and it is exactly the change that breaks a
                            threshold-tuned deployment while leaving a recall suite green.

    SECONDARY (recorded)    contextual-grounding scores, which ARE numeric. Wilcoxon signed-rank
                            on the paired scores. The one continuous signal available, and the
                            most sensitive of the three — but it covers one filter, so it cannot
                            be the primary for a claim about "the underlying guardrail models".

Both secondaries are labelled `exploratory` in the record and neither can change the verdict.
Reporting three tests and scoring the smallest p-value is p-hacking; reporting three and scoring
the pre-named one is what a regression suite does.

THE MAPPING ONTO A SEALED KIND THAT TALKS ABOUT "IMPROVEMENT"
------------------------------------------------------------
`PAIRED_IMPROVEMENT` returns TRUE iff `improved and p_value < alpha`. The claim predicts change
without predicting its direction, so:

    improved  = at least one discordant pair exists (behaviour differs at all)
    p_value   = McNemar exact, TWO-sided, on the discordant counts

TRUE therefore means "behaviour changed, and the change is more than sampling noise", which is
the claim. The direction is recorded — `n_lost` (caught on day 0, missed later) beside `n_gained`
— and is NOT part of the verdict, because the document does not say which way an auto-update
cuts. `n_lost > 0` is the operationally alarming direction and is called out in the record
regardless of the verdict.

WHAT A FALSE WILL AND WILL NOT MEAN
-----------------------------------
A FALSE here means: over this interval, on this set, with this configuration, no behaviour change
was detected. It does **not** mean AWS does not auto-update its models — the document's
antecedent is a statement about AWS's release process, which no black-box measurement from
outside can refute. What a FALSE bounds is the RATE, and that bound is reported rather than
implied: with zero discordant pairs at n items, `rule_of_three` gives the 95% upper bound on the
per-item drift probability, and `power_for_zero_events` gives the power the run had against a
stated alternative. n is chosen so that bound is worth printing (see N_DERIVATION).

The amendment a FALSE would support is about the *cadence* the document recommends, not about the
mechanism — and the record says so in `what_false_does_not_prove`.

NO PRE-REGISTERED n, AND WHERE THE ONE USED COMES FROM
-------------------------------------------------------
F3-11's sealed binding carries `cell=None`, and its note calls that a finding rather than an
omission: `regression_cell.applies_to` lists only F6-8, so no pre-registered n covers F3-11's
re-runs (DEV-P1-1). Borrowing F6-8's 200 would attribute a latency design decision to a detection
re-run. So n is derived here, from what a null result has to be able to say — see N_DERIVATION,
which is recorded in every payload.

COST
----
300 `ApplyGuardrail` calls per run day, ~1 text unit each. Three run days (0, +7, +30) is 900
calls. Well under a dollar in total.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R                                         # noqa: E402
import awsclients as A                                   # noqa: E402
import oracle as O                                       # noqa: E402
import phase1 as P                                       # noqa: E402
import stats as S                                        # noqa: E402
# `_redact`, not `R`: `R` is already `arms` in this module. For the `--early-read` write below.
import redact as _redact                                 # noqa: E402
from evidence import EvidenceStore                       # noqa: E402

CASE = "F3-11"
FAMILY = "f3_efficacy"

# Where the day-0 fingerprints live. In `results/` (distributable, masked) and not in `evidence/`
# (local-only), because the whole point is that the +7d and +30d runs — possibly on another
# machine, certainly in another session — can find it.
SNAPSHOT_DIR = ROOT / "results" / "phase1"
SNAPSHOT_GLOB = "F3-11_snapshot_*.json"

# The scheduled re-run days, recorded so a later operator does not have to reconstruct them.
# Written as offsets, not dates: the baseline stamps its own date and these are relative to it.
REPLICATION_OFFSETS_DAYS = (7, 30)

# ---------------------------------------------------------------------------
# n, and where it comes from
# ---------------------------------------------------------------------------
# A null result has to be able to say something quantitative, and the only thing it can say is an
# upper bound on the per-item drift rate. The rule of three gives that bound as 3/n at 95%
# one-sided, so:
#
#     bound <= 1%   ->   n >= 3 / 0.01 = 300
#
# 1% is the choice, and it is a choice: it is the rate at which a 100-item regression suite of the
# kind the document tells a reader to maintain would be expected to show one failure. A bound
# looser than that would make a FALSE unquotable — "we did not detect drift, and drift could be
# as common as one item in twenty" says nothing a reader can act on.
PLANNED_N = 300
N_DERIVATION = (
    "no pre-registered cell covers F3-11 (sealed binding cell=None; DEV-P1-1), so n is derived "
    "from what a null result must be able to state: the rule of three's 95% one-sided upper "
    "bound on the per-item drift rate is 3/n, and n=300 puts that bound at 1% — the rate at "
    "which a 100-item regression suite of the kind the document recommends would be expected to "
    "show one failure. Not borrowed from F6-8's 200, which is a latency design decision")

# The regression set: five families, each on the guardrail whose policy it exercises, sized so the
# pooled total is PLANNED_N. Strata are explicit rather than emergent — a drift measurement whose
# strata depend on file order would report a different bound on a re-run against a rebuilt corpus.
#
# `n_per_file` is per corpus file, so the arm total is n_per_file * len(files).
#
# `hit` is stated for every stratum, including the one where the default would have been right.
# `ArmSpec.hit_of`'s fallback is `asm.detected(item["label"])`, which reads the CONTENT-FILTER
# type list only, and the corpus label is the stratum's own vocabulary rather than a response
# type. Left implicit, that fallback is silently constant-False for three of the five strata,
# which is worse here than in a normal efficacy arm: this case's primary instrument is McNemar on
# the per-item hit, and a term that cannot change contributes a 0/0 cell on both days, so drift in
# the PII or prompt-attack filters would read as "no drift" instead of as a missing measurement.
# Per stratum, why the default is wrong and what replaces it:
#   content_filter  the default IS correct — labels are HATE/INSULTS/… , the response type names.
#                   Named anyway so that a future corpus relabelling breaks loudly, not quietly.
#   prompt_attack   the API reports one type, PROMPT_ATTACK; JAILBREAK / PROMPT_INJECTION /
#                   PROMPT_LEAKAGE are our corpus's subtypes and appear in no response.
#   pii             detections land in `pii_detected`, a separate list from `detected_types`;
#                   the ENTITY name (ADDRESS, …) is never a content-filter type.
#   benign,         label is CLEAN, which nothing ever detects, so the default is False by
#   hard_negatives  construction — including on the day a model update starts blocking benign
#                   traffic, the one outcome these two strata exist to catch. `any_detection`
#                   reads the FPR side: did ANY policy fire.
STRATA: tuple[dict[str, Any], ...] = (
    {"label": "content_filter", "guardrail": "cf-medium", "source": "INPUT",
     "hit": None,
     "files": ("content_filter/hate.jsonl", "content_filter/insults.jsonl",
               "content_filter/misconduct.jsonl", "content_filter/sexual.jsonl",
               "content_filter/violence.jsonl"),
     "n_per_file": 20, "require_policy": "contentPolicy",
     "why": "the five categories the document's §3.2 table names, at the recommended strength"},
    {"label": "prompt_attack", "guardrail": "cf-medium", "source": "INPUT",
     "hit": P.hit_prompt_attack,
     "files": ("prompt_attack/jailbreak.jsonl", "prompt_attack/prompt_injection.jsonl",
               "prompt_attack/prompt_leakage.jsonl"),
     "n_per_file": 20, "require_policy": "contentPolicy",
     "why": ("the filter most likely to move: an attack classifier is retrained against new "
             "attack traffic, which is precisely the auto-update the claim warns about")},
    {"label": "pii", "guardrail": "pii", "source": "INPUT",
     "hit": P.hit_pii,
     "files": tuple(f"pii/positive/{n}.jsonl" for n in (
         "us_social_security_number", "credit_debit_card_number", "email", "phone", "name",
         "address", "aws_access_key", "aws_secret_key", "password", "us_passport_number",
         "uk_national_insurance_number", "ca_social_insurance_number",
         "international_bank_account_number", "ip_address", "driver_id", "license_plate")),
     "n_per_file": 4, "require_policy": "sensitiveInformationPolicy",
     "why": ("16 of the 30 measured PII types, four items each. PII detection is the family "
             "whose ENTITY types are documented as a fixed list, so drift here would also be a "
             "change to a documented surface")},
    {"label": "benign", "guardrail": "cf-medium", "source": "INPUT",
     "hit": R.any_detection,
     "files": ("benign/benign.jsonl",), "n_per_file": 40, "require_policy": "contentPolicy",
     "why": ("the false-positive side. A model update that starts blocking benign traffic is the "
             "drift that takes a production system down, and a recall-only regression set is "
             "blind to it")},
    {"label": "hard_negatives", "guardrail": "cf-medium", "source": "INPUT",
     "hit": R.any_detection,
     "files": ("hard_negatives/hard_negatives.jsonl",), "n_per_file": 36,
     "require_policy": "contentPolicy",
     "why": ("items written to sit just inside the benign side of each category boundary. If a "
             "threshold moves at all, these move first")},
)

# The response fields that make up the secondary fingerprint. Listed here, not assembled from
# whatever a row happens to contain: a fingerprint built from `set(row) - {...}` would silently
# change meaning the day `arms.run_arm` adds a field, and every item would read as drifted.
FINGERPRINT_FIELDS = ("action", "action_reason", "detected_types", "blocked_types",
                      "confidences", "pii_detected", "pii_actions", "topics_detected",
                      "words_detected", "blocks_present")

GUARDS = ("baseline_exists", "same_configuration", "items_are_identical",
          "both_days_complete", "interval_elapsed")
MIN_COMPLETION = 0.95            # per stratum, both days
MIN_INTERVAL_DAYS = 1.0          # see `interval_elapsed`


class ConfigError(RuntimeError):
    """The two days cannot be paired, so a difference between them means nothing."""


# ---------------------------------------------------------------------------
# the regression set
# ---------------------------------------------------------------------------

def _stratum_items(st: dict[str, Any], *, limit_per_file: int | None) -> list[dict]:
    """The items of one stratum, in file order, tagged with the file they came from."""
    out: list[dict] = []
    per = st["n_per_file"] if limit_per_file is None else min(st["n_per_file"], limit_per_file)
    for rel in st["files"]:
        for it in R.load_corpus(rel, limit=per, stratify_by=None):
            # The corpus id is a content hash and is unique within a file but not necessarily
            # across files, and `run_arm` keys its checkpoint on it. Prefixing with the file makes
            # the trial id unique across the arm, and — more importantly — makes it stable across
            # run days, which is what the pairing depends on.
            out.append({**it, "id": f"{rel}#{it['id']}", "corpus_file": rel,
                        "stratum": st["label"]})
    return out


def _fingerprint(row: dict) -> str:
    """A canonical string for one item's response. Equal strings mean identical behaviour."""
    def norm(v: Any) -> Any:
        if isinstance(v, list):
            return sorted(str(x) for x in v)
        if isinstance(v, dict):
            return {str(k): norm(v[k]) for k in sorted(v)}
        return v
    return json.dumps({f: norm(row.get(f)) for f in FINGERPRINT_FIELDS},
                      sort_keys=True, separators=(",", ":"))


def _grounding_scores(row: dict) -> dict[str, float]:
    """The numeric grounding scores on a row, if the arm's guardrail configures that filter."""
    g = row.get("grounding") or {}
    out: dict[str, float] = {}
    if isinstance(g, dict):
        for k, v in g.items():
            if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
                out[str(k)] = float(v["score"])
            elif isinstance(v, (int, float)):
                out[str(k)] = float(v)
    return out


# ---------------------------------------------------------------------------
# one run day
# ---------------------------------------------------------------------------

def _collect(*, run_id: str, region: str, is_smoke: bool, limit_per_file: int | None,
             day_tag: str, man: dict) -> dict[str, Any]:
    """Send the whole regression set once. Returns a snapshot-shaped dict."""
    strata_out: dict[str, Any] = {}
    for st in STRATA:
        items = _stratum_items(st, limit_per_file=limit_per_file)
        gid = P.guardrail(st["guardrail"], man=man)
        # `label` carries the run day, so day 0 and day +7 land in different checkpoint files.
        # Without it a resume on day +7 would find day 0's trial ids already done, skip every
        # one, and publish day 0's rows twice as a paired comparison of a set with itself — the
        # exact failure `Checkpoint.set_meta`'s design-drift guard exists to prevent, in the one
        # dimension that guard does not cover, because `run_id` is deliberately not a design key.
        spec = R.ArmSpec(case_id=CASE, family=FAMILY,
                         corpus=",".join(st["files"]), guardrail_id=gid,
                         guardrail_version="DRAFT", source=st["source"],
                         region=region, label=f"{day_tag}__{st['label']}",
                         require_policy=st["require_policy"], hit=st["hit"])
        print(f"    [{st['label']:15s}] guardrail={st['guardrail']:10s} n={len(items)}")
        tally = R.run_arm(spec, items, run_id=run_id, is_smoke=is_smoke,
                         progress=lambda d, t: None)
        rows = {r["item_id"]: r for r in (tally.get("rows") or [])}
        strata_out[st["label"]] = {
            "guardrail": st["guardrail"], "guardrail_id": gid, "source": st["source"],
            "files": list(st["files"]), "n_planned": len(items),
            "n_usable": len(rows), "n_failed": tally.get("n_failed", 0),
            "failure_codes": tally.get("failure_codes", {}),
            "why_this_stratum": st["why"],
            "rows": {k: {"hit": bool(v.get("hit")), "label": v.get("label", ""),
                         "fingerprint": _fingerprint(v),
                         "grounding": _grounding_scores(v)}
                     for k, v in rows.items()},
        }
    return {
        "case_id": CASE, "day_tag": day_tag,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id, "region": region, "is_smoke": is_smoke,
        "guardrail_version": "DRAFT",
        "sdk": A.sdk_versions(),
        "fingerprint_fields": list(FINGERPRINT_FIELDS),
        "strata": strata_out,
    }


def _snapshot_path(day_tag: str) -> Path:
    return SNAPSHOT_DIR / f"F3-11_snapshot_{day_tag}.json"


def _find_baseline() -> Path | None:
    """The EARLIEST snapshot on disk. Earliest, not latest: the interval is the instrument."""
    found = sorted(SNAPSHOT_DIR.glob(SNAPSHOT_GLOB))
    return found[0] if found else None


# ---------------------------------------------------------------------------
# pairing
# ---------------------------------------------------------------------------

def _pair(base: dict, now: dict) -> dict[str, Any]:
    """Pair the two days item by item. No verdict here — counts and tests only."""
    per_stratum: dict[str, Any] = {}
    b_only, c_only = 0, 0                       # discordant: caught then missed / missed then caught
    fp_changed, fp_total = 0, 0
    g_pairs: list[tuple[float, float]] = []
    n_paired_total = 0
    dropped: dict[str, int] = {}
    hits_base: list[float] = []                 # the prose instrument's paired 0/1 series
    hits_now: list[float] = []

    for name in sorted(set(base["strata"]) | set(now["strata"])):
        bs = (base["strata"].get(name) or {}).get("rows") or {}
        ns = (now["strata"].get(name) or {}).get("rows") or {}
        ids = sorted(set(bs) & set(ns))
        only_base = sorted(set(bs) - set(ns))
        only_now = sorted(set(ns) - set(bs))
        if only_base or only_now:
            dropped[name] = len(only_base) + len(only_now)
        s_b, s_c, s_fp = 0, 0, 0
        examples: list[dict[str, Any]] = []
        for i in ids:
            hb, hn = bool(bs[i]["hit"]), bool(ns[i]["hit"])
            hits_base.append(1.0 if hb else 0.0)
            hits_now.append(1.0 if hn else 0.0)
            if hb and not hn:
                s_b += 1
            elif hn and not hb:
                s_c += 1
            same_fp = bs[i]["fingerprint"] == ns[i]["fingerprint"]
            if not same_fp:
                s_fp += 1
                if len(examples) < 5:
                    examples.append({"item_id": i, "label": bs[i]["label"],
                                     "hit_day0": hb, "hit_now": hn,
                                     "fingerprint_day0": bs[i]["fingerprint"],
                                     "fingerprint_now": ns[i]["fingerprint"]})
            for k, v in (bs[i].get("grounding") or {}).items():
                if k in (ns[i].get("grounding") or {}):
                    g_pairs.append((float(v), float(ns[i]["grounding"][k])))
        per_stratum[name] = {
            "n_paired": len(ids), "n_only_baseline": len(only_base), "n_only_now": len(only_now),
            "n_lost": s_b, "n_gained": s_c, "n_fingerprint_changed": s_fp,
            "examples_of_change": examples,
        }
        b_only += s_b
        c_only += s_c
        fp_changed += s_fp
        fp_total += len(ids)
        n_paired_total += len(ids)

    chi2, p_mcnemar = S.mcnemar_test(b_only, c_only)
    out: dict[str, Any] = {
        "n_paired": n_paired_total,
        "per_stratum": per_stratum,
        "ids_dropped_per_stratum": dropped,
        "primary": {
            "instrument": "per-item `hit`, paired by corpus item id",
            "n_lost": b_only, "n_gained": c_only, "n_discordant": b_only + c_only,
            "mcnemar_statistic": chi2, "mcnemar_p_two_sided": p_mcnemar,
            "why_two_sided": ("the sealed binding's note says the direction is not predicted; a "
                              "one-sided test would smuggle in a prediction the document does "
                              "not make"),
            "direction_note": ("n_lost is the operationally alarming direction — items caught on "
                               "day 0 and missed later. It is reported whatever the verdict, "
                               "because a reader's regression suite is what would have caught it"),
        },
        # The pre-registration's PROSE for this case names a different instrument from the sealed
        # KIND: "differs from baseline by more than the paired-bootstrap CI" versus
        # PAIRED_IMPROVEMENT's `improved and p_value < alpha`. The kind governs — it is the sealed
        # artifact — and the prose's instrument is reported beside it so a reader can see both.
        # No rule is invented here to arbitrate them: a disagreement is recorded as a fact about
        # the two instruments, not used to flip a verdict either way.
        "prose_instrument": {
            "quoted_from_prereg": ("differs from baseline by more than the paired-bootstrap CI"),
            "instrument": ("paired bootstrap CI on the MEAN of (day-0 hit) - (re-run hit) over "
                           "the same pairs the sealed test uses"),
            "governs_the_verdict": False,
            "why_recorded_anyway": ("the sealed kind is PAIRED_IMPROVEMENT and needs `improved` "
                                    "and a p-value, which a CI is not. Reporting only one of the "
                                    "two would leave the other unverifiable from the record"),
        },
        "secondary_fingerprint": {
            "exploratory": True,
            "n_changed": fp_changed, "n_compared": fp_total,
            "rate_ci": (str(S.wilson_ci(fp_changed, fp_total)) if fp_total else ""),
            "fields": list(FINGERPRINT_FIELDS),
            "why_not_scored": ("more sensitive than the primary — a confidence enum moving from "
                               "MEDIUM to HIGH is drift with `hit` unchanged — but scoring the "
                               "smallest of three p-values is p-hacking. Recorded, never scored"),
        },
        "secondary_grounding": {
            "exploratory": True,
            "n_pairs": len(g_pairs),
            "why_not_scored": ("the only NUMERIC signal available (DEV-P4-01: no other surface "
                               "publishes a per-trial score), and therefore the most sensitive "
                               "instrument here — but it covers one filter, and the claim is "
                               "about the underlying models generally"),
        },
    }
    if n_paired_total >= 20:
        ci = S.paired_bootstrap_diff_ci(hits_base, hits_now, statistic=S.np.mean)
        out["prose_instrument"].update({
            "rate_day0": round(sum(hits_base) / len(hits_base), 6),
            "rate_now": round(sum(hits_now) / len(hits_now), 6),
            "paired_bootstrap_ci": str(ci),
            "ci_excludes_zero": bool(ci.lo > 0 or ci.hi < 0),
            "agrees_with_sealed_test": bool((ci.lo > 0 or ci.hi < 0) ==
                                            (float(p_mcnemar) < 0.05 and (b_only + c_only) > 0)),
        })
    if len(g_pairs) >= 10:
        a = [x for x, _ in g_pairs]
        b = [y for _, y in g_pairs]
        w, pw = S.wilcoxon_signed_rank(a, b)
        out["secondary_grounding"].update({
            "wilcoxon_statistic": w, "wilcoxon_p": pw,
            "hodges_lehmann_shift": round(S.hodges_lehmann(a, b), 6),
            "median_day0": round(S.quantile(a, 0.5), 6),
            "median_now": round(S.quantile(b, 0.5), 6),
        })
    return out


def _interval_days(base: dict, now: dict) -> float:
    t0 = datetime.fromisoformat(base["collected_at"])
    t1 = datetime.fromisoformat(now["collected_at"])
    return (t1 - t0).total_seconds() / 86400.0


def main(argv: list[str] | None = None) -> int:                     # noqa: C901, PLR0912, PLR0915
    ap = P.parser(CASE, __doc__)
    ap.add_argument("--compare", action="store_true",
                    help="re-send the earliest snapshot's items and publish the paired verdict")
    ap.add_argument("--early-read", action="store_true", dest="early_read",
                    help="measure the pairing NOW, before +7d, and record it as a supplementary "
                         "read that carries NO verdict (see the module docstring)")
    args = ap.parse_args(argv)
    if args.early_read and args.compare:
        ap.error("--compare publishes the sealed verdict and --early-read refuses to; pick one")
    limit_per_file = args.n if args.n else None
    is_smoke = args.n is not None

    total = sum(min(st["n_per_file"], limit_per_file or st["n_per_file"]) * len(st["files"])
                for st in STRATA)

    if args.dry_run:
        P.dry_run_banner(
            CASE,
            [(st["label"],
              f"{len(st['files'])} file(s) on guardrail {st['guardrail']}",
              min(st["n_per_file"], limit_per_file or st["n_per_file"]) * len(st["files"]))
             for st in STRATA],
            operations={"ApplyGuardrail": total},
            mutations=0, billable=True,
            extra=[
                f"n derivation: {N_DERIVATION}",
                f"pooled n = {total} (planned {PLANNED_N})",
                "the WAIT is the instrument, so DEV-P4-02's waiver of the two-calendar-day "
                "replication rule does NOT apply here; the day-0 arm runs now and writes a "
                f"snapshot, and `--compare` publishes on day +{'/+'.join(str(d) for d in REPLICATION_OFFSETS_DAYS)}",
                "`--early-read` runs the same pairing before then and records it as a "
                "supplementary read with NO verdict: the sealed oracle names the +7d/+30d "
                "interval, so a shorter pairing measures a different quantity",
                "primary (scored): per-item `hit`, McNemar exact two-sided. Secondaries "
                "(recorded, never scored): the full response fingerprint, and grounding scores "
                "by Wilcoxon — scoring the smallest of three p-values is p-hacking",
                "improved = 'at least one discordant pair', because the sealed note says the "
                "direction is not predicted; n_lost is reported separately whatever the verdict",
                f"guards, all INCONCLUSIVE-on-failure: {', '.join(GUARDS)}",
            ])
        return 0

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = P.resolve_run(args)
    region = args.region
    man = P.manifest()
    baseline_path = _find_baseline()

    # ---------------- day 0: collect and stop ------------------------------
    if not (args.compare or args.early_read):
        if baseline_path is not None:
            print(f"a baseline already exists: {baseline_path.name}\n"
                  f"Re-run with --compare to publish the paired verdict, or move that file "
                  f"aside deliberately to start a new interval. Collecting a second baseline "
                  f"would silently reset the elapsed time this case measures.")
            return 2
        day_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        print(f"F3-11 day-0 baseline — run_id={run_id}, region={region}, pooled n={total}")
        snap = _collect(run_id=run_id, region=region, is_smoke=is_smoke,
                        limit_per_file=limit_per_file, day_tag=day_tag, man=man)
        # Absolute dates, not offsets. A later operator reading this file should not have to do
        # calendar arithmetic to find out whether today is a run day.
        t0 = datetime.fromisoformat(snap["collected_at"])
        snap["replication_due"] = [
            {"offset_days": d, "due_on": (t0 + timedelta(days=d)).date().isoformat(),
             "command": "python3 f3_efficacy/07_model_drift.py --compare"}
            for d in REPLICATION_OFFSETS_DAYS]
        path = _snapshot_path(day_tag)
        path.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n")
        n_usable = sum(s["n_usable"] for s in snap["strata"].values())
        print(f"  baseline written: {path.relative_to(ROOT)}  ({n_usable}/{total} usable)")
        for d in REPLICATION_OFFSETS_DAYS:
            print(f"  due +{d}d: python3 f3_efficacy/07_model_drift.py --compare")

        # No verdict is emitted on day 0, and that is deliberate: a `not_measured` record here
        # would be indistinguishable in `results/` from a case that failed a guard, and F3-11 has
        # not failed anything — it is waiting on elapsed time, which is its instrument.
        P.emit(CASE, O.not_measured(
            CASE, f"the day-0 baseline is collected ({n_usable} items) and the paired re-run is "
                  f"due at +{REPLICATION_OFFSETS_DAYS[0]}d and "
                  f"+{REPLICATION_OFFSETS_DAYS[1]}d. The elapsed interval IS this case's "
                  f"instrument, so no verdict can be computed today — see the module docstring "
                  f"on why DEV-P4-02's waiver does not reach this case",
            guards={"baseline_exists": True, "interval_elapsed": False},
            baseline_snapshot=path.name, n_usable=n_usable, n_planned=total,
            n_derivation=N_DERIVATION,
            replication_command="python3 f3_efficacy/07_model_drift.py --compare"),
            {"phase": "baseline_only", "snapshot": path.name, "strata": {
                k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                for k, v in snap["strata"].items()}},
            EvidenceStore(run_id, FAMILY, "F3-11-baseline"))
        return 0

    # ---------------- day N: re-send and pair ------------------------------
    if baseline_path is None:
        raise ConfigError(
            f"--compare found no {SNAPSHOT_GLOB} in {SNAPSHOT_DIR}. There is nothing to pair "
            f"against, and baselining now and comparing now would publish a vacuous 'no drift' "
            f"— which is the result this case is most likely to produce by accident. Run "
            f"without --compare first, then wait")
    base = json.loads(baseline_path.read_text())
    day_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"F3-11 paired re-run — baseline {baseline_path.name}, run_id={run_id}")
    now = _collect(run_id=run_id, region=region, is_smoke=is_smoke,
                   limit_per_file=limit_per_file, day_tag=day_tag, man=man)
    _snapshot_path(day_tag).write_text(json.dumps(now, indent=2, sort_keys=True) + "\n")

    paired = _pair(base, now)
    elapsed = _interval_days(base, now)

    # Configuration identity: a difference between two days means a model update ONLY if
    # everything we control is unchanged. Guardrail ids and versions come from the snapshots
    # rather than from today's manifest, so a re-provisioned guardrail is caught rather than
    # assumed away.
    cfg_diffs = []
    for name in sorted(set(base["strata"]) | set(now["strata"])):
        b = base["strata"].get(name) or {}
        c = now["strata"].get(name) or {}
        for key in ("guardrail_id", "source", "files"):
            if b.get(key) != c.get(key):
                cfg_diffs.append({"stratum": name, "field": key,
                                  "baseline": b.get(key), "now": c.get(key)})
    if base.get("guardrail_version") != now.get("guardrail_version"):
        cfg_diffs.append({"stratum": "*", "field": "guardrail_version",
                          "baseline": base.get("guardrail_version"),
                          "now": now.get("guardrail_version")})
    if base.get("fingerprint_fields") != now.get("fingerprint_fields"):
        cfg_diffs.append({"stratum": "*", "field": "fingerprint_fields",
                          "baseline": base.get("fingerprint_fields"),
                          "now": now.get("fingerprint_fields")})

    completion = []
    for snap in (base, now):
        for name, s in snap["strata"].items():
            planned = s.get("n_planned") or 0
            completion.append((snap["day_tag"], name,
                               (s.get("n_usable", 0) / planned) if planned else 0.0))
    worst = min((c for _d, _n, c in completion), default=0.0)

    alpha = O.alpha_for(CASE)
    prim = paired["primary"]
    n_disc = prim["n_discordant"]
    n_paired = paired["n_paired"]

    guards = {
        "baseline_exists": True,
        "same_configuration": not cfg_diffs,
        "items_are_identical": not paired["ids_dropped_per_stratum"],
        "both_days_complete": worst >= MIN_COMPLETION,
        "interval_elapsed": elapsed >= MIN_INTERVAL_DAYS,
    }
    payload: dict[str, Any] = {
        "run_id": run_id, "region": region, "is_smoke": is_smoke or base.get("is_smoke"),
        "alpha": alpha, "n_derivation": N_DERIVATION, "planned_n": PLANNED_N,
        "baseline_snapshot": baseline_path.name,
        "now_snapshot": _snapshot_path(day_tag).name,
        "baseline_collected_at": base["collected_at"],
        "now_collected_at": now["collected_at"],
        "interval_days": round(elapsed, 4),
        "replication_offsets_days": list(REPLICATION_OFFSETS_DAYS),
        "configuration_differences": cfg_diffs,
        "completion_by_day_and_stratum": [
            {"day": d, "stratum": nm, "completion": round(c, 4)} for d, nm, c in completion],
        "ambient_sdk": {"baseline": base.get("sdk"), "now": now.get("sdk")},
        **paired,
        "guards": guards,
        "guard_names": list(GUARDS),
        "guard_detail": {
            "baseline_exists": {"snapshot": baseline_path.name},
            "same_configuration": {
                "test": "guardrail id, version, source, corpus files and fingerprint fields "
                        "are identical across the two days",
                "differences": cfg_diffs,
                "why": ("a difference between two days is evidence of a MODEL update only if "
                        "everything we control is unchanged. Read from the snapshots, not from "
                        "today's manifest, so a re-provisioned guardrail is caught")},
            "items_are_identical": {
                "test": "every baseline item id is present on the re-run day and vice versa",
                "dropped": paired["ids_dropped_per_stratum"],
                "why": ("McNemar is a test on PAIRS. An item present on one day only is not a "
                        "pair, and silently dropping it would let a corpus edit read as drift")},
            "both_days_complete": {
                "test": f"every stratum on both days is >= {MIN_COMPLETION:.0%} usable",
                "worst": round(worst, 4),
                "why": ("a stratum that half-failed on one day contributes a biased subset of "
                        "pairs, and the items that fail are not a random sample of the set")},
            "interval_elapsed": {
                "test": f"at least {MIN_INTERVAL_DAYS} day between the two collections",
                "interval_days": round(elapsed, 4),
                "why": ("'behaviour today equals behaviour today' is not a measurement. This is "
                        "the one case in the project whose instrument IS elapsed time, which is "
                        "why DEV-P4-02's procedural waiver does not reach it")},
        },
        "what_false_does_not_prove": (
            "a FALSE bounds the DRIFT RATE over this interval, on this set, in this "
            "configuration. It does not refute the document's antecedent — that AWS "
            "auto-updates the underlying models — because that is a statement about AWS's "
            "release process and no black-box measurement from outside can reach it. The "
            "amendment a FALSE supports is about the recommended CADENCE, not the mechanism"),
    }
    if n_disc == 0 and n_paired:
        payload["null_result_bounds"] = {
            "n_pairs": n_paired,
            "drift_rate_upper_95_one_sided": round(S.rule_of_three(n_paired), 5),
            "power_against_1_percent": round(S.power_for_zero_events(n_paired, 0.01), 4),
            "power_against_5_percent": round(S.power_for_zero_events(n_paired, 0.05), 4),
            "why": ("zero discordant pairs has no p-value worth quoting, so the null result is "
                    "reported as a bound and a power instead. This is the number a reader would "
                    "act on: 'we did not detect drift, and drift is at most this common'"),
        }

    line = (f"  interval {elapsed:.2f}d  paired {n_paired}  "
            f"lost {prim['n_lost']} / gained {prim['n_gained']}  "
            f"p={prim['mcnemar_p_two_sided']:.4g}  "
            f"fingerprint changed {paired['secondary_fingerprint']['n_changed']}"
            f"/{paired['secondary_fingerprint']['n_compared']}")

    # ---------------- the early read: measure, do not decide ----------------
    # An early pairing is a real measurement of a real interval, and it is NOT this case's
    # verdict. The sealed oracle is denominated in the +7d/+30d re-run --- "TRUE if the +7d or
    # +30d re-run differs from baseline by more than the paired-bootstrap CI" --- so publishing
    # a shorter interval under F3-11's name would decide a different quantity than the seal
    # names, and because the verdict is one word the substitution would be invisible in
    # `results/phase1/F3-11.json` and survive only in the payload. That is the same defect as
    # answering F1-15 with an `http.passthrough` target. So the early read writes OUTSIDE the
    # verdict namespace, emits no oracle record, and leaves the day-0 `not_measured` record
    # standing with the +7d run still due.
    #
    # It is worth running anyway for two reasons. A drift already visible at +3d is a finding
    # about the CADENCE the document recommends, which is the only amendment a F3-11 result
    # supports at all. And it exercises this whole path once while there is still time to
    # repair it, instead of discovering a defect in the pairing code on 2026-09-10 with a
    # 30-day interval on the line and no way to re-collect it.
    if args.early_read:
        out = ROOT / "results" / f"F3-11-early-read-{day_tag}.json"
        # Masked. `payload` is carried through from the day snapshot and this file goes into the
        # distributable tree; it was the fourteenth unmasked `results/` write in the repo and
        # `lib/tests/test_results_writes_are_masked.py` failed on it. Masked rather than waived,
        # for the reason given at the sibling site in `f1_config/diag_target_types.py`: the case
        # for tolerating the original twelve was that they are other families' working code.
        out.write_text(_redact.mask_text(json.dumps({
            "case_id": CASE,
            "kind": "SUPPLEMENTARY_READ",
            "status": "NOT A VERDICT. F3-11's sealed oracle is denominated in the +7d/+30d "
                      "re-run; this pairing is over a shorter interval and decides nothing.",
            "sealed_oracle": O.oracle_text(CASE),
            "verdict_would_have_been": (
                "INCONCLUSIVE (guards)" if [g for g, ok in guards.items() if not ok]
                else O.evaluate(P.obs_paired(
                    CASE, improved=n_disc > 0,
                    p_value=float(prim["mcnemar_p_two_sided"]), n=n_paired,
                    n_lost=prim["n_lost"], n_gained=prim["n_gained"],
                    interval_days=round(elapsed, 4)))["verdict"]),
            "why_that_is_recorded_and_not_published": (
                "so a reader can see that the early read was not suppressed for being "
                "inconvenient. It is excluded because of its INTERVAL, which was fixed before "
                "the numbers were known, and not because of its result"),
            "still_due": base.get("replication_due"),
            "payload": payload,
        }, indent=2, sort_keys=True, default=str) + "\n"))
        print(line)
        print(f"  F3-11 EARLY READ (no verdict): {out.relative_to(ROOT)}")
        print(f"  the sealed +7d run is still due: "
              f"python3 f3_efficacy/07_model_drift.py --compare")
        return 0

    failed = [g for g, ok in guards.items() if not ok]
    if failed:
        rec = O.not_measured(CASE, f"guard(s) {', '.join(failed)} did not hold, so a difference "
                                   f"between the two days cannot be attributed to a change in "
                                   f"the service", guards=guards)
    else:
        rec = O.evaluate(P.obs_paired(CASE, improved=n_disc > 0,
                                      p_value=float(prim["mcnemar_p_two_sided"]),
                                      n=n_paired,
                                      n_lost=prim["n_lost"], n_gained=prim["n_gained"],
                                      interval_days=round(elapsed, 4)))
    P.emit(CASE, rec, payload, EvidenceStore(run_id, FAMILY, "F3-11-compare"))
    print(line)
    print(f"  F3-11: {rec['verdict']}")
    return 0 if rec["verdict"] in O.DECISIVE else 1


if __name__ == "__main__":
    sys.exit(main())
