#!/usr/bin/env python3
"""Build the corpora to the sizes fixed by the sealed pre-registration.

    python3 corpora/build.py            # write the corpus files
    python3 corpora/build.py --dry-run  # print the plan and the arithmetic, write nothing

Two properties make this a build rather than a generation:

**It is deterministic.** No RNG anywhere; every item is the cartesian product of
banks taken in declaration order. Re-running produces byte-identical files, which
is what makes `MANIFEST.json`'s hashes meaningful — a hash over output that varies
run to run records nothing.

**It cannot silently miss its target.** Every per-cell count is read from
`PREREGISTRATION.yaml` and asserted against what was actually written. A corpus
one item short would void the arm it was sized for (the whole content of DEV-P0-2),
and an under-sized corpus is precisely the failure that looks like success: the
files exist, the tests run, and the interval is wider than the design promised.

Item schema, one JSON object per line:

    id          content-hash prefix — stable across runs, leaks no class or order
    label       the class, per corpora/labeling_protocol.md §3
    text        the item
    template_id, slot, surface   provenance: how the text was produced
    source      "generated" or "reused:<path>"
    resembles   hard negatives only: which attack class the item superficially
                resembles (the protocol's right-hand column)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import banks as B  # noqa: E402


def item_id(text: str, label: str) -> str:
    """A content hash, not an index.

    Ordering the blinded rating file by this hash makes the file's order
    independent of class, template and generation sequence. A sequential index
    would leak all three — "the first 120 are VIOLENCE" makes blinding decorative.
    """
    return hashlib.sha256(f"{label}\x00{text}".encode()).hexdigest()[:12]


def emit(label: str, text: str, *, template_id: str, slot: str, surface: str,
         source: str = "generated", **extra) -> dict:
    return {"id": item_id(text, label), "label": label, "text": text,
            "template_id": template_id, "slot": slot, "surface": surface,
            "source": source, **extra}


# Structurally decidable instances of documented GuardrailPiiEntityType values
# (`DEV-P0-8`). Every key must be one of the SDK's 31 names, which is asserted
# below rather than trusted.
#
# The screen is deliberately narrow. It matches only entity types whose instances
# are decidable from surface form — a URI scheme, a dotted quad, RFC 3986 userinfo.
# NAME, ADDRESS and AGE need world knowledge and are NOT screened for beyond one
# explicit `name:` assignment, so a clean run of this check is not a proof that no
# documented entity is present. It is a proof that no *structurally obvious* one is.
ENTITY_SCREEN = {
    "URL": re.compile(r"\b[a-z][a-z0-9+.-]*://\S", re.I),
    "IP_ADDRESS": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "MAC_ADDRESS": re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"),
    "EMAIL": re.compile(r"(?<![:/\w.+-])[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"),
    "AWS_ACCESS_KEY": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    # RFC 3986 userinfo: scheme://user:password@host. Structural, not lexical —
    # this is what made 7 DB_CONNECTION_STRING items carry three documented
    # entities each while their label asserted they carried none.
    "USERNAME": re.compile(r"\b[a-z][a-z0-9+.-]*://([^:/?#@\s]+):[^@/\s]*@", re.I),
    "PASSWORD": re.compile(r"\b[a-z][a-z0-9+.-]*://[^:/?#@\s]+:([^@/\s]+)@", re.I),
    "NAME": re.compile(r"\bname\s*[:=]\s*[A-Z][a-z]+"),
}


def entities_present(text: str) -> list[str]:
    """Which documented entity types this text structurally contains."""
    return sorted(k for k, p in ENTITY_SCREEN.items() if p.search(text))


# ---------------------------------------------------------------------------
# the six corpora
# ---------------------------------------------------------------------------

def build_content_filter() -> dict[str, list[dict]]:
    out = {}
    for category, (templates, slots, surfaces) in B.CONTENT_FILTER.items():
        items = []
        for tid, template in templates:
            for slot in slots:
                sentence = template.format(**slot)
                slot_key = "|".join(f"{k}={v}" for k, v in slot.items()) or "-"
                for sname, wrapper in surfaces:
                    items.append(emit(category, wrapper.format(s=sentence),
                                      template_id=tid, slot=slot_key,
                                      surface=sname))
        out[category] = items
    return out


def build_prompt_attack() -> dict[str, list[dict]]:
    out = {}
    for subtype, templates in B.PROMPT_ATTACK.items():
        items = []
        for tid, attack in templates:
            for ename, envelope in B.ATTACK_ENVELOPES:
                items.append(emit(subtype, envelope.format(s=attack),
                                  template_id=tid, slot="-", surface=ename))
        out[subtype] = items
    return out


def build_benign() -> list[dict]:
    items = []
    for tid, request in B.BENIGN:
        for sname, wrapper in B.BENIGN_SURFACES:
            items.append(emit("CLEAN", wrapper.format(s=request),
                              template_id=tid, slot="-", surface=sname))
    return items


def build_hard_negatives(source_root: Path) -> list[dict]:
    """Authored hard negatives PLUS the source corpus's unmappable secrets.

    The second half is not padding. `DEV-P0-6` found that the source corpus's
    secrets-only labels (JWT_TOKEN, PRIVATE_KEY, SG_NRIC, ...) name no
    GuardrailPiiEntityType, which makes them the *right* stimulus for the question
    "does the PII filter fire on a secret it does not document?" — a question the
    PII corpus cannot ask, because every item in it is an entity the SDK names.
    Discarding them would have thrown away the most interesting items in the
    corpus that prompted the deviation.

    **Not every unmappable item qualifies (`DEV-P0-8`).** The mapping says
    `DB_CONNECTION_STRING: null`, and that is true — no GuardrailPiiEntityType names
    the *concept* "connection string". It does not follow that an *item* with that
    label carries no documented entity: `postgres://user:pass@db.host/app` carries a
    USERNAME, a PASSWORD and a URL, all three of the 31. The label-level mapping was
    read as an item-level property, which is exactly DEV-P0-7's root cause.

    So items carrying a structurally obvious documented entity are excluded here, and
    the count is checked against the pre-registration rather than being whatever the
    screen happens to remove. A builder that silently filtered to satisfy its own
    guard would make the guard vacuous: the sealed figure is what makes this an
    assertion instead of a self-fulfilling filter.
    """
    items = [emit("HARD_NEGATIVE", text, template_id=tid, slot="-",
                  surface="plain", resembles=resembles)
             for tid, resembles, text in B.HARD_NEGATIVES]

    mapping = _prereg()["corpora"]["pii"]["source_corpus_audit"]["mapping"]
    unmappable = {k for k, v in mapping.items() if v is None}
    reused, excluded = [], []
    for f in sorted((source_root / "positive").glob("*.jsonl")):
        rel = f"reused:{f.relative_to(source_root.parent.parent.parent)}"
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            src = json.loads(line)
            if src["label"] not in unmappable:
                continue
            if entities_present(src["text"]):
                excluded.append(src)
                continue
            reused.append(emit("HARD_NEGATIVE", src["text"],
                               template_id=src["label"],
                               slot=src.get("desc", "-"), surface="plain",
                               source=rel, resembles="PII_NOT_AN_SDK_ENTITY"))
    return items + reused, excluded


def build_multilingual() -> dict[str, list[dict]]:
    out = {}
    for lang in B.LANGS:
        items = []
        for seed_id, klass, texts in B.MULTILINGUAL_SEEDS:
            for i, wrapper in enumerate(B.ML_SURFACES[lang]):
                items.append(emit(klass, wrapper.format(s=texts[lang]),
                                  template_id=seed_id, slot=lang,
                                  surface=f"ml{i + 1}"))
        out[lang] = items
    return out


def build_pii(per_entity: int, source_root: Path) -> dict[str, list[dict]]:
    """Positives per SDK entity type, plus the reused CLEAN negatives.

    Each entity gets the SAME 11 carrier sentences, so a detection difference
    between two entities cannot be attributed to one having been embedded in more
    helpful context than the other. Values cycle within the carriers, which is what
    keeps the 11 items distinct without introducing an RNG.

    **No positive item is reused verbatim** (`DEV-P0-7`). A reused item brings its
    own sentence, which would hand 7 of the 31 entities carriers no other entity
    has and confound entity identity with carrier text — in the single comparison
    F3-4 exists to make. Reuse survives only at the value level: some published
    test constants this corpus needs anyway also appear in the source corpus, which
    `count_reused_values` measures rather than asserts from memory.

    The negatives are reused verbatim minus those carrying a documented entity
    (`DEV-P0-8`). "Label-agnostic" was the stated reason reuse was free here, and it
    held for the secrets question the source corpus was built for; it does not hold
    against a filter that detects URLs, because `http://example.com is just a
    placeholder` is a URL and URL is one of the 31.
    """
    out = {}
    for entity, values in sorted(B.PII_VALUES.items()):
        items = []
        for i, carrier in enumerate(B.PII_CARRIERS[:per_entity]):
            value = values[i % len(values)]
            items.append(emit(entity, carrier.format(v=value),
                              template_id=f"carrier{i + 1}", slot=value,
                              surface="plain"))
        out[entity] = items

    negatives, excluded = [], []
    for f in sorted((source_root / "negative").glob("*.jsonl")):
        rel = f"reused:{f.relative_to(source_root.parent.parent.parent)}"
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                src = json.loads(line)
                if entities_present(src["text"]):
                    excluded.append(src)
                    continue
                negatives.append(emit("CLEAN", src["text"],
                                      template_id=src["label"],
                                      slot=src.get("desc", "-"),
                                      surface="plain", source=rel))
    out["_excluded_negatives"] = excluded
    out["_negatives"] = negatives
    return out


def count_reused_values(source_root: Path) -> int:
    """How many of our PII values also occur in the source corpus, by substring.

    This is the honest measure of what "reuse" amounts to under `DEV-P0-7`: shared
    published test constants (RFC 5737 addresses, the 4111… test PAN), not shared
    items. Recomputed rather than pinned in prose, because it is exactly the kind of
    figure that goes stale the moment a value in `banks.py` changes.
    """
    blob = "\n".join(
        json.loads(line)["text"]
        for f in sorted((source_root / "positive").glob("*.jsonl"))
        for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
    return sum(1 for values in B.PII_VALUES.values()
               for v in values if v in blob)


# ---------------------------------------------------------------------------
# writing, and the size gate
# ---------------------------------------------------------------------------

def _prereg() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "PREREGISTRATION.yaml").read_text(
        encoding="utf-8"))


def write_jsonl(path: Path, items: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False so the multilingual corpus is readable as text rather
    # than as escape sequences — per feedback_vacuous_test_check, the ascii
    # default would also make any "no CJK escaped" assertion true by construction.
    path.write_text("".join(json.dumps(i, ensure_ascii=False,
                                       sort_keys=True) + "\n" for i in items),
                    encoding="utf-8")
    return len(items)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and the arithmetic, write nothing")
    # A reproducibility check must not write over the corpus it is checking: if the
    # build were non-deterministic, rebuilding in place would overwrite the
    # evidence of that before anything could compare the two trees.
    ap.add_argument("--out", metavar="DIR", default=None,
                    help="write the corpus to DIR instead of corpora/ "
                         "(for byte-reproducibility checks)")
    args = ap.parse_args(argv)

    pr = _prereg()
    co = pr["corpora"]
    if pr["meta"]["status"] != "SEALED":
        print("FATAL: the pre-registration is not sealed, so the sizes this build "
              "targets are not fixed. Seal it first.", file=sys.stderr)
        return 2

    src = (ROOT / co["pii"]["source_corpus_audit"]["path"]).resolve()
    if not src.is_dir():
        print(f"FATAL: the source corpus is not at {src}. 42 hard negatives and "
              f"all {co['pii']['negatives']} PII negatives are reused from it; "
              f"building without it would silently produce short corpora.",
              file=sys.stderr)
        return 2

    out = Path(args.out).resolve() if args.out else ROOT / "corpora"
    cf = build_content_filter()
    pa = build_prompt_attack()
    benign = build_benign()
    hard, hard_excluded = build_hard_negatives(src)
    ml = build_multilingual()
    pii = build_pii(co["pii"]["per_entity"], src)

    # --- the size gate. Read from the sealed file, asserted against reality.
    problems: list[str] = []

    def want(label: str, got: int, expect: int) -> None:
        if got != expect:
            problems.append(f"{label}: built {got}, pre-registration says {expect}")

    for cat, items in cf.items():
        want(f"content_filter/{cat}", len(items), co["content_filter"]["per_category"])
    want("content_filter total", sum(map(len, cf.values())),
         co["content_filter"]["total"])
    for sub, items in pa.items():
        want(f"prompt_attack/{sub}", len(items), co["prompt_attack"]["per_subtype"])
    want("prompt_attack total", sum(map(len, pa.values())),
         co["prompt_attack"]["total"])
    want("benign", len(benign), co["benign"]["total"])
    want("hard_negatives", len(hard), co["hard_negatives"]["total"])
    for lang, items in ml.items():
        want(f"multilingual/{lang}", len(items), co["multilingual"]["per_language"])
    want("multilingual total", sum(map(len, ml.values())),
         co["multilingual"]["total"])
    positives = {k: v for k, v in pii.items() if not k.startswith("_")}
    for entity, items in positives.items():
        want(f"pii/{entity}", len(items), co["pii"]["per_entity"])
    want("pii entity types", len(positives), co["pii"]["entity_types_from_sdk"])
    want("pii positives", sum(map(len, positives.values())), co["pii"]["positives"])
    want("pii negatives", len(pii["_negatives"]), co["pii"]["negatives"])

    # DEV-P0-7's three reuse figures, each against what was actually built rather
    # than against the total. The sealed file previously carried a reuse split that
    # summed correctly and was individually impossible.
    generated = [i for items in positives.values() for i in items
                 if i["source"] == "generated"]
    want("pii positives authored", len(generated),
         co["pii"]["positive_items_authored"])
    want("pii positives reused verbatim",
         sum(map(len, positives.values())) - len(generated),
         co["pii"]["positive_items_reused_verbatim"])
    want("pii reused test values", count_reused_values(src),
         co["pii"]["reused_test_values"])

    # DEV-P0-8. How many source items the entity screen removed, against the sealed
    # figure. This is what stops the exclusion being a self-fulfilling filter: the
    # builder drops whatever the screen flags, so without a pre-registered count the
    # downstream guard would pass by construction no matter what the screen did —
    # including doing nothing, or removing the whole cell.
    ex = co["pii"]["entity_screen_exclusions"]
    want("pii negatives excluded by the entity screen", len(pii["_excluded_negatives"]),
         ex["pii_negatives"])
    want("hard negatives excluded by the entity screen", len(hard_excluded),
         ex["hard_negatives_pii_arm"])

    # The carrier control DEV-P0-7 chose 0 verbatim reuse to protect. Asserting the
    # *reason* and not only the count: if a later edit reintroduced reuse, the count
    # check would catch it, but this is the check that says why it matters.
    carriers = {entity: tuple(sorted(i["template_id"] for i in items))
                for entity, items in positives.items()}
    if len(set(carriers.values())) != 1:
        odd = {e: c for e, c in carriers.items()
               if c != max(set(carriers.values()),
                           key=list(carriers.values()).count)}
        problems.append(
            f"pii: {len(odd)} entity/entities do not use the shared carrier set "
            f"({sorted(odd)}) — a per-entity detection difference would then be "
            f"confounded with carrier text, which is F3-4's only comparison")

    # DEV-P0-8. A negative control is only a negative with respect to the filter it
    # is scored against. Two cells assert, in their labels, that no documented
    # entity type is present:
    #
    #   - `pii/negative/clean.jsonl` — CLEAN, scored against the PII filter
    #   - the `PII_NOT_AN_SDK_ENTITY` hard negatives — the label's whole content is
    #     "this is a secret the SDK does not document", which is the stimulus F3-3
    #     needs and is false the moment the item also carries one that it does
    #
    # Both were built from the source corpus's LABEL-level mapping
    # (`DB_CONNECTION_STRING: null` = no entity names that concept), and a label-level
    # fact does not license an item-level claim: `postgres://user:pass@host/db`
    # contains a USERNAME, a PASSWORD and a URL, all three documented. This is
    # DEV-P0-7's root cause a second time — the mapping was read as a property of
    # items when it is a property of labels.
    #
    # The screen cannot be a count check, which is why the size gate passed all of
    # these. It also cannot be complete (see ENTITY_SCREEN): a clean result means no
    # structurally obvious entity, not no entity.
    for cell_name, items, asserts in [
        ("pii/negative/clean.jsonl", pii["_negatives"], "CLEAN vs the PII filter"),
        ("hard_negatives[PII_NOT_AN_SDK_ENTITY]",
         [i for i in hard if i.get("resembles") == "PII_NOT_AN_SDK_ENTITY"],
         "not a documented entity type"),
    ]:
        bad = [(entities_present(i["text"]), i) for i in items
               if entities_present(i["text"])]
        if bad:
            eg = "; ".join(f"{','.join(e)} in {i['text'][:44]!r}" for e, i in bad[:3])
            problems.append(
                f"{cell_name}: {len(bad)}/{len(items)} item(s) contain a documented "
                f"GuardrailPiiEntityType while the label asserts "
                f"'{asserts}' — e.g. {eg}. A detection on these is CORRECT "
                f"behaviour that the arm would score as a false positive")

    if set(ENTITY_SCREEN) - set(positives):
        problems.append(
            f"ENTITY_SCREEN names {sorted(set(ENTITY_SCREEN) - set(positives))}, "
            f"which the SDK does not enumerate — the screen would flag items for "
            f"carrying something that is not under test")

    # The multilingual comparison is only interpretable if every language got the
    # same seeds. Equal COUNTS are not equal SETS — a language could be 60 items of
    # the wrong seeds and pass the count check.
    seed_sets = {lang: {i["template_id"] for i in items}
                 for lang, items in ml.items()}
    reference = seed_sets[B.LANGS[0]]
    for lang, seeds in seed_sets.items():
        if seeds != reference:
            problems.append(
                f"multilingual/{lang} covers a different seed set than "
                f"{B.LANGS[0]}: only here {sorted(seeds - reference)}, only there "
                f"{sorted(reference - seeds)} — the F8 language comparison would be "
                f"confounded with content")

    # Every PII entity must be one the SDK actually enumerates, read live. The
    # request names the entity type, so a name the SDK does not use is a request
    # for something that does not exist — and 13 of the 15 source-corpus labels are
    # exactly that kind of plausible near-miss.
    try:
        from botocore.session import get_session
        sdk = set(get_session().get_service_model("bedrock").shape_for(
            "GuardrailPiiEntityType").enum)
    except Exception as exc:
        print(f"  NOTE: could not read the SDK entity enumeration ({exc}); "
              f"the entity-name check was SKIPPED")
    else:
        if set(positives) != sdk:
            problems.append(
                f"pii entities do not match the SDK enumeration: only in the "
                f"corpus {sorted(set(positives) - sdk)}, only in the SDK "
                f"{sorted(sdk - set(positives))}")

    # Duplicate text within a cell would inflate n without adding information: two
    # identical items are one observation counted twice, and the interval computed
    # from them is narrower than the evidence supports.
    for name, group in [("content_filter", cf), ("prompt_attack", pa),
                        ("multilingual", ml), ("pii", positives)]:
        for cell, items in group.items():
            texts = [i["text"] for i in items]
            if len(set(texts)) != len(texts):
                dupes = len(texts) - len(set(texts))
                problems.append(f"{name}/{cell}: {dupes} duplicate item(s) — "
                                f"identical text is one observation, not two")
    for name, items in [("benign", benign), ("hard_negatives", hard)]:
        texts = [i["text"] for i in items]
        if len(set(texts)) != len(texts):
            problems.append(f"{name}: {len(texts) - len(set(texts))} duplicate item(s)")

    # Mood consistency, as a HEURISTIC and labelled as one. A template that opens
    # with a bare imperative verb ("explain how to ...") must not be wrapped by a
    # bank whose wrappers expect a proposition, because "Is it true that explain how
    # to ..." is a nested instruction rather than a surface variant.
    #
    # This does NOT prove the moods match. Grammaticality is not decidable by a word
    # list, and the defect this rule approximates was found by *reading the blinded
    # audit sample*, not by any check — mutating SEXUAL back to the assertion bank
    # still builds 1927 items clean if the opening verb is not in the list below.
    # The guard is here to catch the recurrence of a known shape cheaply; the audit
    # remains the instrument that can find the general case.
    IMPERATIVE_OPENERS = ("explain ", "describe ", "tell ", "write ", "produce ",
                          "narrate ", "give ", "compose ", "list ", "show ")
    for category, (templates, slots, surfaces) in B.CONTENT_FILTER.items():
        if surfaces is B.REQUEST_SURFACES:
            continue
        bad = [tid for tid, tpl in templates
               if tpl.lower().startswith(IMPERATIVE_OPENERS)]
        if bad:
            problems.append(
                f"content_filter/{category}: template(s) {bad} open with an "
                f"imperative verb but the category is paired with the assertion "
                f"surface bank, which would produce 'Is it true that explain "
                f"how to ...' — pair it with REQUEST_SURFACES or rewrite the "
                f"template as an assertion")

    # Cross-cell duplicates, which the per-cell check above cannot see. The English
    # multilingual seeds initially restated three prompt_attack templates verbatim,
    # so those items would have been sent twice and counted in two different arms —
    # and F8's "does language change effectiveness" comparison would have had an
    # English arm partly made of items already in the attack arm. Only the
    # multilingual EN cell is expected to overlap conceptually, so it is checked
    # against everything else rather than exempted.
    everything: dict[str, list[str]] = {}
    for name, group in [("content_filter", cf), ("prompt_attack", pa),
                        ("multilingual", ml), ("pii", positives)]:
        for cell, items in group.items():
            for i in items:
                everything.setdefault(i["text"], []).append(f"{name}/{cell}")
    for name, items in [("benign", benign), ("hard_negatives", hard),
                        ("pii", pii["_negatives"])]:
        for i in items:
            everything.setdefault(i["text"], []).append(name)
    collisions = {t: cells for t, cells in everything.items() if len(set(cells)) > 1}
    if collisions:
        sample = list(collisions.items())[:3]
        problems.append(
            f"{len(collisions)} item(s) appear in more than one cell, e.g. "
            + "; ".join(f"{sorted(set(c))} <- {t[:48]!r}" for t, c in sample)
            + " — the same text in two arms is one stimulus counted twice")

    if problems:
        print(f"FAIL — {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    total = (sum(map(len, cf.values())) + sum(map(len, pa.values()))
             + len(benign) + len(hard) + sum(map(len, ml.values()))
             + sum(map(len, positives.values())) + len(pii["_negatives"]))

    if args.dry_run:
        print("DRY RUN — nothing written. Every size matches the sealed "
              "pre-registration.")
        for cat, items in cf.items():
            print(f"  content_filter/{cat}.jsonl        {len(items):>5}")
        for sub, items in pa.items():
            print(f"  prompt_attack/{sub}.jsonl      {len(items):>5}")
        print(f"  benign/benign.jsonl                {len(benign):>5}")
        print(f"  hard_negatives/hard_negatives.jsonl {len(hard):>4}")
        for lang, items in ml.items():
            print(f"  multilingual/{lang}.jsonl          {len(items):>5}")
        print(f"  pii/positive/*.jsonl ({len(positives)} entities) "
              f"{sum(map(len, positives.values())):>5}")
        print(f"  pii/negative/clean.jsonl           {len(pii['_negatives']):>5}")
        print(f"  TOTAL {total}")
        return 0

    manifest: dict[str, dict] = {}

    def record(rel: str, items: list[dict]) -> None:
        path = out / rel
        n = write_jsonl(path, items)
        manifest[rel] = {
            "items": n,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "labels": sorted({i["label"] for i in items}),
        }

    for cat, items in cf.items():
        record(f"content_filter/{cat.lower()}.jsonl", items)
    for sub, items in pa.items():
        record(f"prompt_attack/{sub.lower()}.jsonl", items)
    record("benign/benign.jsonl", benign)
    record("hard_negatives/hard_negatives.jsonl", hard)
    for lang, items in ml.items():
        record(f"multilingual/{lang}.jsonl", items)
    for entity, items in positives.items():
        record(f"pii/positive/{entity.lower()}.jsonl", items)
    record("pii/negative/clean.jsonl", pii["_negatives"])

    (out / "MANIFEST.json").write_text(json.dumps({
        "prereg_sha256": (ROOT / "PREREGISTRATION.sha256").read_text(
            encoding="utf-8").split()[0],
        "total_items": total,
        "files": manifest,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Built {total} items across {len(manifest)} files.")
    print(f"  every per-cell size matches the sealed pre-registration "
          f"({(ROOT / 'PREREGISTRATION.sha256').read_text().split()[0][:12]}…)")
    print(f"  MANIFEST.json records a sha256 per file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
