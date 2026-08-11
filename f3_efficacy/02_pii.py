#!/usr/bin/env python3
"""F3-4: per-entity PII recall over all 31 documented entity types.

    python3 f3_efficacy/02_pii.py --dry-run
    python3 f3_efficacy/02_pii.py --n 3
    python3 f3_efficacy/02_pii.py

WHY THIS IS 31 CASES WEARING ONE CASE ID
----------------------------------------
The sealed oracle is "FALSE for **any** entity whose CI upper bound is below 0.5", and
the pre-registered n is 11 **per entity**, not 87 over the corpus (`BINDINGS['F3-4'].note`
says exactly that). A universally-quantified oracle is not a statement about the pooled
rate: a pooled recall of 0.94 over 341 items is arithmetically compatible with one entity
detecting nothing at all, and that entity is the finding. So each of the 31 entity types
is evaluated as its own stratum through `phase1.per_stratum`, and the roll-up rule (one
FALSE stratum decides the case) is printed with the result rather than left implicit.

The pooled figure is still reported — as a description, labelled as one. It is an average
weighted by a corpus composition we chose (11 per entity, i.e. uniform), so it is a
property of our design and not of the service.

WHAT COUNTS AS A HIT, AND WHY NOT "ANY ENTITY"
---------------------------------------------
`phase1.hit_pii` requires the item's own entity type in `piiEntities[].detected`. An
EMAIL item reported as USERNAME is a miss **for EMAIL**. That is the strict reading and
it is the right one here: the document's value to a reader is the per-entity table, and a
service that routed every entity to NAME would satisfy "something was detected" while
making the table wrong in 30 of 31 rows. `any_entity_detected` is tallied alongside for
every item so the laxer reading is recoverable without a second run.

THE 31 IS READ, NOT WRITTEN
---------------------------
The entity list comes from the same place the provisioner's does — the botocore service
model's `piiEntitiesConfig[].type` enum — via the manifest's own `purpose` string being
irrelevant and the corpus filenames being the check. A literal `31` here would keep
saying 31 after the SDK gained a 32nd type, and the missing corpus would then look like a
coverage gap rather than a stale constant. `--dry-run` asserts the two sets agree.

A NOTE ON THE NEGATIVE CELL
---------------------------
`corpora/pii/negative/clean.jsonl` (26 items) is run as a 32nd arm. It is NOT part of the
per-entity roll-up — F3-4's oracle says nothing about false positives — but a per-entity
recall table with no negative control cannot distinguish a working filter from one that
reports every entity on every input. Its rate is reported as a validity check, and it is
the reason `ENTITY_SCREEN`'s stated bound matters: the screen removes only structurally
decidable entities, so a clean negative cell means "no structurally obvious documented
entity", never "no documented entity".
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import arms as R          # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
from evidence import EvidenceStore  # noqa: E402

FAMILY = "f3"
CASE = "F3-4"
NEGATIVE = "pii/negative/clean.jsonl"


def entity_types() -> list[str]:
    """The documented entity types, from the SDK model, cross-checked against the corpus.

    Both directions are checked. A type with no corpus file is an unmeasurable stratum in
    a universally-quantified oracle — the roll-up would quantify over 30 of 31 and read
    as if it had covered them all. A corpus file with no type is a corpus built against a
    different SDK than the guardrail was configured with.
    """
    import awsclients as A
    c = A.factory(A.MAIN_REGION).bedrock()
    shape = (c.meta.service_model.operation_model("CreateGuardrail").input_shape
             .members["sensitiveInformationPolicyConfig"]
             .members["piiEntitiesConfig"].member.members["type"])
    types = sorted(shape.enum)
    have = {p.stem.upper() for p in (ROOT / "corpora" / "pii" / "positive").glob("*.jsonl")}
    missing = [t for t in types if t not in have]
    orphan = sorted(have - set(types))
    if missing or orphan:
        raise RuntimeError(
            f"the SDK's entity enum and the corpus disagree — missing corpora for "
            f"{missing}, corpora with no matching type {orphan}. F3-4's oracle is "
            f"universally quantified over entity types, so a stratum with no items would "
            f"make the roll-up quantify over fewer types than it claims")
    return types


def rel_for(entity: str) -> str:
    return f"pii/positive/{entity.lower()}.jsonl"


def plan(n: int | None) -> list[tuple[str, str, int]]:
    rows = [(f"pii-{e.lower()}", rel_for(e), len(R.load_corpus(rel_for(e), limit=n)))
            for e in entity_types()]
    rows.append(("pii-negative", NEGATIVE, len(R.load_corpus(NEGATIVE, limit=n))))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = P.parser(CASE, __doc__)
    args = ap.parse_args(argv)
    ents = entity_types()

    if args.dry_run:
        return P.dry_run_banner(
            CASE, plan(args.n),
            extra=[f"entity types read from the botocore model: {len(ents)}",
                   f"pre-registered n is PER ENTITY ({O.planned_n(CASE)}), so the "
                   f"roll-up is over {len(ents)} strata and one FALSE stratum decides "
                   f"the case",
                   "the negative cell is a validity check, not part of the roll-up"])

    run_id = P.resolve_run(args)
    man = P.manifest()
    gid = P.guardrail("pii", man=man)
    is_smoke = args.n is not None
    print(f"\nPII guardrail {gid}, {len(ents)} entity types")

    strata: dict[str, dict[str, int]] = {}
    tallies: list[dict] = []
    any_entity: dict[str, int] = {}

    for e in ents:
        rel = rel_for(e)
        items = R.load_corpus(rel, limit=args.n)
        spec = R.ArmSpec(case_id=CASE, family=FAMILY, corpus=rel, guardrail_id=gid,
                         region=args.region, label=f"pii-{e.lower()}", hit=P.hit_pii)
        t = P.run_arms([spec], [items], run_id=run_id, is_smoke=is_smoke)[0]
        tallies.append(t)
        strata[e] = {"x": t["x"], "n": t["n_usable"],
                     "n_attempted": t["n_attempted"],
                     "failure_codes": t["failure_codes"]}
        # The laxer reading, recorded per stratum so it never needs a second run: how
        # many items had ANY documented entity reported, whatever its type.
        any_entity[e] = sum(1 for r in t["rows"] if r.get("pii_detected"))

    items = R.load_corpus(NEGATIVE, limit=args.n)
    spec = R.ArmSpec(case_id=CASE, family=FAMILY, corpus=NEGATIVE, guardrail_id=gid,
                     region=args.region, label="pii-negative", hit=R.any_detection)
    neg = P.run_arms([spec], [items], run_id=run_id, is_smoke=is_smoke)[0]
    tallies.append(neg)

    rc = P.require_measured(tallies, is_smoke=is_smoke)
    if rc:
        return rc

    roll = P.per_stratum(CASE, strata)
    pooled_x = sum(c["x"] for c in strata.values())
    pooled_n = sum(c["n"] for c in strata.values())

    # The case record is the ROLL-UP, not the pooled proportion. Building the record from
    # the pooled counts would produce a verdict that reads as F3-4's and answers a
    # different question — and it would read TRUE while a stratum sat at zero.
    rec = dict(O.evaluate(P.obs_proportion(
        CASE, [{"x": pooled_x, "n_usable": pooled_n, "n_attempted": pooled_n,
                "failure_codes": []}], pooled_description_only=True)))
    rec["verdict"] = roll["rollup_verdict"]
    # The per-stratum AND, with its basis recorded: the sealed n=11 is PER ENTITY, so the
    # case-level n_met computed from the pooled counts answers a different question. The
    # helper also strips `evaluate`'s pooled shortfall note, which otherwise contradicted
    # the override and reached the published record as "n_usable=93 is below the
    # pre-registered 11" (DEVIATIONS.md/DEV-P1-12).
    rec = P.apply_rollup_n_met(rec, roll, unit="entity")
    rec["notes"] = list(rec.get("notes") or []) + [
        "the verdict is the per-stratum roll-up, not the pooled proportion; the pooled "
        "interval in `evidence` describes an average over a corpus composition we chose "
        "(uniform, 11 per entity) and is not a statement about any entity",
        f"n_met is evaluated per stratum: the pre-registered n={O.planned_n(CASE)} is "
        f"per entity",
    ]

    P.emit(CASE, rec, {
        "run_id": run_id, "is_smoke": is_smoke,
        "billable_calls": sum(t["n_usable"] for t in tallies), "mutations": 0,
        "rollup": roll,
        "pooled_description_only": {"x": pooled_x, "n": pooled_n},
        "any_entity_detected_by_stratum": any_entity,
        "hit_rule": ("phase1.hit_pii — the item's OWN entity type must appear in "
                     "piiEntities[].detected; `any_entity_detected_by_stratum` carries "
                     "the laxer reading"),
        "negative_control": {"x": neg["x"], "n": neg["n_usable"],
                             "corpus": NEGATIVE,
                             "role": ("validity check, NOT part of the roll-up — F3-4's "
                                      "oracle says nothing about false positives, but a "
                                      "recall table with no negative cell cannot "
                                      "distinguish a working filter from one that "
                                      "reports every entity on every input"),
                             "screen_bound": ("corpora/build.py ENTITY_SCREEN covers "
                                              "structurally decidable types only, so a "
                                              "clean cell means 'no structurally obvious "
                                              "documented entity', not 'no documented "
                                              "entity'")},
        "instrument": "ApplyGuardrail (source=INPUT, outputScope=FULL), all entities BLOCK",
    }, EvidenceStore(run_id, FAMILY, CASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
