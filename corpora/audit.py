#!/usr/bin/env python3
"""The validity audit of the corpus labels (corpora/labeling_protocol.md §5).

Three steps, deliberately three separate invocations so that the rating cannot be
produced after seeing the score:

    python3 corpora/audit.py sample   -> corpora/audit_sample.jsonl   (id + text only)
    <the rater fills in corpora/audit_ratings.jsonl>
    python3 corpora/audit.py score    -> corpora/irr_report.json

`sample` writes a file containing **no labels**. `score` joins the ratings back to
the corpus and computes Cohen's kappa. The join is mechanical; there is no step in
which a rating can be revised in the light of the label it is being compared to.

What this kappa is, exactly (protocol §5.1): agreement between **one rater and the
constructive label** — a *validity* measure, not the plan's two-rater
*reliability* measure. One rater exists in this project. The number licenses "the
templates produce what they claim" and says nothing about how a different rater
would label these items, because the same person wrote the definitions, the
templates and the ratings. That limitation is reproduced in the report itself
rather than left in this docstring.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPORA = ROOT / "corpora"
sys.path.insert(0, str(ROOT))

from lib.stats import cohens_kappa, wilson_ci  # noqa: E402

SAMPLE = CORPORA / "audit_sample.jsonl"
RATINGS = CORPORA / "audit_ratings.jsonl"
REPORT = CORPORA / "irr_report.json"

# Sampling is stratified by RATING CLASS, not by corpus cell, because the class is
# the unit the statistic is computed over. Stratifying by cell wasted the audit's
# budget: the 31 PII cells all collapse to one rating class (`rating_target`), so a
# per-cell stride sampled 86 PII items to estimate agreement on a single class while
# giving VIOLENCE 30.
#
# hard_negatives is sampled ENTIRELY. It is the one judgement-labeled class
# (protocol §2.2), so it is the only class where disagreement is possible for a
# reason other than a defective template, and at 69 items sampling it at all would
# be a false economy.
PER_CLASS = 24
JUDGEMENT_CELLS = {"hard_negatives"}
LABEL_VOCABULARY = [
    "VIOLENCE", "HATE", "SEXUAL", "MISCONDUCT", "INSULTS",
    "JAILBREAK", "PROMPT_INJECTION", "PROMPT_LEAKAGE",
    "CLEAN", "HARD_NEGATIVE", "PII", "UNSURE",
]


def load_corpus() -> list[dict]:
    """Every built item, tagged with the cell it came from."""
    items = []
    for path in sorted(CORPORA.rglob("*.jsonl")):
        if path.name in {SAMPLE.name, RATINGS.name}:
            continue
        cell = path.parent.name if path.parent != CORPORA else path.stem
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append({**json.loads(line), "cell": cell,
                              "file": str(path.relative_to(CORPORA))})
    return items


def rating_target(item: dict) -> str:
    """The label a rater could reasonably be asked to produce.

    PII entity types collapse to a single `PII` class. Asking a rater to pick
    US_PASSPORT_NUMBER over PASSPORT is a test of the SDK's vocabulary, not of the
    corpus's validity, and disagreement there would say nothing about whether the
    item contains PII -- which is the only thing F3-4 needs the label to mean.
    """
    return "PII" if item["file"].startswith("pii/positive") else item["label"]


def do_sample() -> int:
    corpus = load_corpus()

    # Group by rating class, then take an evenly-spaced stride through each group so
    # the sample spans every template and surface rather than clustering on whichever
    # ones happen to sort first. Deterministic: no RNG, so `sample` is reproducible
    # and a rating file cannot be invalidated by re-running it.
    by_class: dict[str, list[dict]] = {}
    for item in corpus:
        by_class.setdefault(rating_target(item), []).append(item)

    chosen = []
    for cls, items in sorted(by_class.items()):
        if any(i["cell"] in JUDGEMENT_CELLS for i in items):
            chosen.extend(items)
            continue
        if len(items) <= PER_CLASS:
            chosen.extend(items)
            continue
        stride = len(items) / PER_CLASS
        chosen.extend(items[int(k * stride)] for k in range(PER_CLASS))

    # A label the rater has no way to write is unratable, and every item carrying
    # it would count as a disagreement no matter what the rater does. This fired on
    # the first run: banks.py used BENIGN for the multilingual clean seeds while the
    # rest of the corpus used CLEAN, so 42 items would have been guaranteed
    # disagreements and kappa would have been depressed by a naming inconsistency
    # rather than by anything about the corpus.
    escaped = sorted({rating_target(d) for d in chosen} - set(LABEL_VOCABULARY))
    if escaped:
        print(f"FATAL: {escaped} appear as corpus labels but are not in the rating "
              f"vocabulary, so no rater could ever agree with them. Either the "
              f"corpus label is wrong or LABEL_VOCABULARY is incomplete — a "
              f"guaranteed disagreement is not a measurement.", file=sys.stderr)
        return 2

    # Ordered by id (a content hash), so the file's order is independent of class,
    # cell, template and generation sequence. A sequential order would leak all
    # four and make the blinding decorative (protocol §6).
    chosen.sort(key=lambda d: d["id"])

    SAMPLE.write_text("".join(
        json.dumps({"id": d["id"], "text": d["text"]}, ensure_ascii=False,
                   sort_keys=True) + "\n" for d in chosen), encoding="utf-8")

    present = sorted({rating_target(d) for d in chosen})
    print(f"Wrote {len(chosen)} items to {SAMPLE.relative_to(ROOT)} "
          f"({len(corpus)} in the corpus).")
    print(f"  classes present: {', '.join(present)}")
    print(f"  the file contains id and text ONLY — no labels, no cell, no order "
          f"information")
    print(f"\nRate each item into exactly one of:\n  {', '.join(LABEL_VOCABULARY)}")
    print(f"Write {RATINGS.relative_to(ROOT)} as one "
          f'{{"id": ..., "rating": ...}} per line, then run: '
          f"python3 corpora/audit.py score")
    return 0


def do_score(gate: float) -> int:
    if not RATINGS.exists():
        print(f"FATAL: {RATINGS.relative_to(ROOT)} does not exist. Run "
              f"`sample`, rate the items, then `score`.", file=sys.stderr)
        return 2

    corpus = {d["id"]: d for d in load_corpus()}
    sample_ids = [json.loads(l)["id"]
                  for l in SAMPLE.read_text(encoding="utf-8").splitlines()
                  if l.strip()]
    ratings = {}
    for line in RATINGS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            ratings[r["id"]] = r["rating"]

    problems = []
    unknown = sorted(set(ratings) - set(sample_ids))
    if unknown:
        problems.append(f"{len(unknown)} rating(s) for ids not in the sample: "
                        f"{unknown[:5]}")
    missing = [i for i in sample_ids if i not in ratings]
    if missing:
        problems.append(f"{len(missing)} sampled item(s) were not rated "
                        f"({missing[:5]}) — an unrated item is not a dropped item, "
                        f"it is an incomplete audit")
    bad = sorted({v for v in ratings.values() if v not in LABEL_VOCABULARY})
    if bad:
        problems.append(f"rating(s) outside the vocabulary: {bad}")
    if problems:
        print("FAIL — the audit is not scorable:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    truth = [rating_target(corpus[i]) for i in sample_ids]
    rated = [ratings[i] for i in sample_ids]

    # UNSURE is NOT dropped (protocol §5). Dropping the items a rater could not
    # classify removes exactly the hard cases and inflates kappa, which is the
    # easiest way to pass this gate without deserving to. It stays in as a
    # disagreement.
    kappa = cohens_kappa(truth, rated)
    n_unsure = sum(1 for r in rated if r == "UNSURE")
    agree = sum(1 for t, r in zip(truth, rated) if t == r)

    per_class = {}
    for cls in sorted(set(truth)):
        idx = [i for i, t in enumerate(truth) if t == cls]
        hit = sum(1 for i in idx if rated[i] == truth[i])
        ci = wilson_ci(hit, len(idx))
        per_class[cls] = {
            "n": len(idx), "agreed": hit,
            "agreement": hit / len(idx),
            "wilson_lo": ci.lo, "wilson_hi": ci.hi,
            "disagreements": sorted({rated[i] for i in idx
                                     if rated[i] != truth[i]}),
        }

    disagreements = [{"id": i, "label": t, "rated": r, "text": corpus[i]["text"],
                      "file": corpus[i]["file"]}
                     for i, t, r in zip(sample_ids, truth, rated) if t != r]

    report = {
        "statistic": "cohens_kappa",
        "kappa": kappa,
        "gate": gate,
        "passes_gate": kappa >= gate,
        "n_rated": len(sample_ids),
        "n_corpus": len(corpus),
        "raw_agreement": agree / len(sample_ids),
        "n_unsure": n_unsure,
        "unsure_counted_as": "disagreement",
        "prereg_sha256": (ROOT / "PREREGISTRATION.sha256").read_text(
            encoding="utf-8").split()[0],
        "corpus_manifest_total": json.loads(
            (CORPORA / "MANIFEST.json").read_text(encoding="utf-8"))["total_items"],
        "per_class": per_class,
        "disagreements": disagreements,
        "what_this_kappa_is": (
            "Agreement between ONE rater and the constructive label — a validity "
            "measure. It is NOT the plan's two-independent-human reliability "
            "kappa; one rater exists in this project. It licenses 'the templates "
            "produce what they claim' and says nothing about how a different "
            "rater would label these items, because the same person wrote the "
            "definitions, the templates and the ratings. A second human rater "
            "remains an open item, and passing this gate is necessary for Phase 1 "
            "and NOT sufficient for publishing the corpus as human-validated."),
        "why_kappa_is_conservative_here": (
            "HARD_NEGATIVE is not disjoint from CLEAN. The protocol (§3) defines it "
            "as 'CLEAN, AND the text contains features characteristic of an attack "
            "class', so HARD_NEGATIVE is a SUBSET of CLEAN and a rater answering "
            "CLEAN has not made an error — the two labels differ in a judgement "
            "about resemblance, not in a claim about the text. Every CLEAN-for-"
            "HARD_NEGATIVE disagreement below is of that kind, so the reported "
            "kappa is a LOWER bound on validity rather than an unbiased estimate. "
            "The overlap is left in rather than collapsed: merging the labels would "
            "raise kappa without improving the corpus, and F3-3 needs the two cells "
            "kept apart because it computes a separate FPR over each."),
        "residual_read": (
            "The disagreements were read individually after scoring, and this is "
            "recorded because it is where DEV-P0-8 came from: the pre-fix run passed "
            "at kappa 0.9530 and its residual contained an item rated PII against a "
            "label asserting no documented entity type was present, which was a real "
            "corpus defect (9 hard negatives and 1 PII negative carried documented "
            "entity types). A gate answers the question it was built to ask; the "
            "items it disagreed with are where the unasked questions are. The "
            "remaining PII-for-HARD_NEGATIVE disagreements are Singapore NRIC/FIN "
            "items, checked against the live SDK enumeration: no Singapore national "
            "ID is among the 31 GuardrailPiiEntityType values, so the label is "
            "correct and the rating reflected real-world PII rather than the SDK's "
            "documented vocabulary. That gap is the stimulus those items exist to "
            "provide."),
        "limitations": [
            "Template-generated text is formulaic; a filter could respond to "
            "structure rather than content. F3 reports recall ON THIS CORPUS and "
            "claims no generalisation to natural attack text.",
            "One rater (see what_this_kappa_is).",
            "The rater wrote the template bank, so blinding removes recall of "
            "which item is which but not knowledge of the generator. This bounds "
            "the audit to template-level defects and leaves definition-level bias "
            "undetectable.",
            "Multilingual items are translated by the same author, so a "
            "language-specific translation artefact is indistinguishable from a "
            "language-specific filter weakness.",
            "Ratings for the 289 items that survived the DEV-P0-8 corpus change are "
            "carried over VERBATIM from the pre-fix rating pass; only the 11 items "
            "new to the sample were rated after the change. Re-rating the 289 would "
            "have meant revising ratings while knowing which items the previous run "
            "had disagreed with, which is the one thing the three-step design exists "
            "to prevent.",
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                 sort_keys=True) + "\n", encoding="utf-8")

    print(f"Cohen's kappa = {kappa:.4f}   gate >= {gate}   "
          f"{'PASS' if kappa >= gate else 'FAIL'}")
    print(f"  {agree}/{len(sample_ids)} raw agreement, {n_unsure} UNSURE "
          f"(counted as disagreement)")
    for cls, d in per_class.items():
        flag = "" if not d["disagreements"] else f"  <- rated {d['disagreements']}"
        print(f"    {cls:<18} {d['agreed']:>3}/{d['n']:<3} "
              f"[{d['wilson_lo']:.3f}, {d['wilson_hi']:.3f}]{flag}")
    print(f"  wrote {REPORT.relative_to(ROOT)}")
    return 0 if kappa >= gate else 1


def main(argv: list[str] | None = None) -> int:
    import yaml
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["sample", "score"])
    args = ap.parse_args(argv)
    if args.step == "sample":
        return do_sample()
    pr = yaml.safe_load((ROOT / "PREREGISTRATION.yaml").read_text(encoding="utf-8"))
    return do_score(pr["corpora"]["labelling"]["inter_rater"]["gate"])


if __name__ == "__main__":
    sys.exit(main())
