"""The F3-family analysis functions and arm plans, tested by mutation.

F3 is the largest corpus consumer and the only family whose oracles are mostly *rates*, so
its characteristic failure is not a crash but a clean-looking number describing a comparison
that never happened. Three of those are already documented in the code and are pinned here:

* a denied-topic reader keyed on the item's label would report FPR exactly 0 for any
  configuration whatsoever, including one with no topic policy at all;
* a PROMPT_ATTACK reader keyed on the corpus subtype would report recall 0/360 for a filter
  that fired on every item, because the API has one PROMPT_ATTACK type and JAILBREAK is our
  label;
* a grounding request built with `.get` would send a request the service accepts and scores
  against nothing, producing a rate about an empty source.

The plans get the same treatment. `plan()` is what the dry-run cost projection is read off
and what `--n` caps, so a literal count, a missing arm or an uncapped smoke run is spend that
was never authorised. And `entity_types()` is a gate: F3-4's oracle is universally quantified
over entity types, so a stratum with no corpus would let the roll-up quantify over 30 of 31
and read as if it had covered them all — both directions of that check are mutation-tested.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import arms as R
import oracle as O
import phase1 as P

ROOT = Path(__file__).resolve().parents[2]
DEV_ROOT = ROOT / "corpora_deviation"


def _load(stem: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "f3_efficacy" / stem)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M1 = _load("01_content_filter.py", "f3_content_filter")
M2 = _load("02_pii.py", "f3_pii")
M3 = _load("03_prompt_attack.py", "f3_prompt_attack")
M4 = _load("04_topic.py", "f3_topic")
M5 = _load("05_words.py", "f3_words")
M6 = _load("06_grounding.py", "f3_grounding")


# ============================================ F3-4 — entity_types is a coverage gate

def test_entity_types_reads_the_enum_from_the_sdk_model():
    """Not a hand-written list. The enum is what the guardrail was configured from, and a
    literal here would be a second copy that drifts silently on the next SDK bump."""
    types = M2.entity_types()
    assert types == sorted(types), "returned unsorted, so the strata order is not stable"
    assert len(types) == 31
    assert "EMAIL" in types and "US_SOCIAL_SECURITY_NUMBER" in types


def test_every_entity_type_has_a_corpus_file():
    """The gate's purpose, restated as the property it protects: F3-4's oracle is
    universally quantified, so an unmeasurable stratum would make the roll-up quantify over
    fewer types than it claims while still reporting a verdict."""
    for e in M2.entity_types():
        assert (ROOT / "corpora" / M2.rel_for(e)).exists(), e


def test_a_missing_corpus_file_makes_entity_types_raise(tmp_path, monkeypatch):
    """Mutation check. `entity_types` reads the corpus directory off the module's ROOT, so
    pointing ROOT at an empty tree is the same fault as deleting a file."""
    (tmp_path / "corpora" / "pii" / "positive").mkdir(parents=True)
    monkeypatch.setattr(M2, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="missing corpora"):
        M2.entity_types()


def test_an_orphan_corpus_file_makes_entity_types_raise(tmp_path, monkeypatch):
    """The other direction, and it is not symmetric: an orphan means the corpus was built
    against a different SDK than the guardrail is configured with, so every stratum's
    labels are suspect, not just the extra one."""
    pos = tmp_path / "corpora" / "pii" / "positive"
    pos.mkdir(parents=True)
    for e in M2.entity_types():
        (pos / f"{e.lower()}.jsonl").write_text("")
    (pos / "not_an_entity_type.jsonl").write_text("")
    monkeypatch.setattr(M2, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="corpora with no matching type"):
        M2.entity_types()


def test_rel_for_lowercases_the_entity_type():
    assert M2.rel_for("US_SOCIAL_SECURITY_NUMBER") == \
        "pii/positive/us_social_security_number.jsonl"


def test_the_pii_plan_has_one_arm_per_entity_plus_the_negative_cell():
    rows = M2.plan(None)
    assert len(rows) == len(M2.entity_types()) + 1
    assert rows[-1][1] == M2.NEGATIVE


def test_the_negative_cell_is_not_one_of_the_entity_arms():
    """It is a validity check, not part of the universally-quantified roll-up. Folding it
    in would make a clean negative cell contribute a passing stratum."""
    rows = M2.plan(None)
    assert M2.NEGATIVE not in {rel for _l, rel, _n in rows[:-1]}


def test_the_sealed_pii_n_is_per_entity_not_total():
    """11 per entity over 31 strata, not 11 trials. Reading it as a total would under-run
    the case by a factor of 31 and the interval would still print."""
    assert O.planned_n("F3-4") == 11
    assert sum(n for _l, _r, n in M2.plan(None)) > 11 * 31


def test_hit_pii_reads_the_item_own_entity_type():
    """An item carrying an EMAIL that the service reported as a NAME is a miss for EMAIL —
    which is the distinction the per-entity table exists to make."""
    asm = R.Assessment(pii_detected=["NAME"])
    assert P.hit_pii({"label": "EMAIL"}, asm) is False
    assert P.hit_pii({"label": "NAME"}, asm) is True


def test_hit_pii_is_false_when_nothing_was_detected():
    assert P.hit_pii({"label": "EMAIL"}, R.Assessment()) is False


# ==================================== F3-1/2/3/9 — the content-filter arm lattice

def test_the_content_filter_plan_sweeps_every_strength_over_every_category():
    """F3-9's ROC needs the whole lattice; a missing strength is a missing operating
    point, and the polyline would be reported as if it had them all."""
    rows = M1.plan(None)
    for s in P.STRENGTHS:
        got = {rel for lbl, rel, _n in rows if lbl == f"cf-{s.lower()}"}
        assert set(M1.CF_CORPORA) <= got, s


def test_the_benign_arm_runs_at_every_strength():
    """FPR is half of both F3-2 and every ROC vertex. A benign arm at one strength would
    force three of the four vertices to reuse an FPR measured under a different config."""
    rows = M1.plan(None)
    for s in P.STRENGTHS:
        assert (f"cf-{s.lower()}", M1.BENIGN) in {(l, r) for l, r, _n in rows}


def test_the_hard_negatives_run_at_the_recommended_strength_only():
    """F3-3's oracle is about the recommendation; sweeping the lattice with them would
    quadruple the cell for a question no oracle asks."""
    rows = [lbl for lbl, rel, _n in M1.plan(None) if rel == M1.HARD]
    assert rows == [f"cf-{P.RECOMMENDED_CONTENT_STRENGTH.lower()}"]


def test_the_recommended_strengths_come_from_the_document_under_test():
    """The phrase "the recommended threshold" appears in four sealed oracles. Picking a
    different strength per case would make the four cases describe different experiments
    while reporting one number each."""
    assert P.RECOMMENDED_CONTENT_STRENGTH == "MEDIUM"
    assert P.RECOMMENDED_ATTACK_STRENGTH == "HIGH"
    assert P.RECOMMENDED_CONTENT_STRENGTH in P.STRENGTHS
    assert P.RECOMMENDED_ATTACK_STRENGTH in P.STRENGTHS


def test_the_plan_counts_come_from_the_corpus_files_not_from_literals():
    """A literal would be a second, unchecked copy of the sealed corpus size, and the dry
    run's total is what the cost projection is read off."""
    rows = M1.plan(None)
    by_rel = {rel: n for _l, rel, n in rows}
    for rel, n in by_rel.items():
        assert n == len(R.load_corpus(rel)), rel


def test_the_content_filter_plan_is_capped_by_n():
    assert all(n <= 3 for _l, _r, n in M1.plan(3))
    assert sum(n for _l, _r, n in M1.plan(3)) < sum(n for _l, _r, n in M1.plan(None))


def test_all_five_documented_categories_are_covered():
    assert set(P.CF_CATEGORIES) == {"VIOLENCE", "HATE", "SEXUAL", "MISCONDUCT", "INSULTS"}
    assert len(M1.CF_CORPORA) == 5
    for rel in M1.CF_CORPORA:
        assert (ROOT / "corpora" / rel).exists(), rel


def test_the_four_cases_share_one_set_of_arms():
    """Recorded as a property, because it is the reason the four verdicts are not
    independent evidence: the same benign arm is the FPR term for F3-2 and for every F3-9
    vertex, so a bad benign arm moves all four together."""
    assert M1.CASES == ("F3-1", "F3-2", "F3-3", "F3-9")
    assert len({rel for _l, rel, _n in M1.plan(None)}) == 7   # 5 categories + benign + hard


# ==================================================== F3-8 — prompt-attack subtypes

def test_the_prompt_attack_plan_pairs_a_tagged_arm_with_every_untagged_arm():
    """The pairing is what makes McNemar applicable here and nowhere else in the case
    (DEV-P1-6): the tagged and untagged arms send the SAME items."""
    rows = M3.plan(None)
    untagged = {lbl.split("untagged-", 1)[1]: (rel, n)
                for lbl, rel, n in rows if lbl.startswith("untagged-")}
    tagged = {lbl.split("tagged-", 1)[1]: (rel, n)
              for lbl, rel, n in rows if lbl.startswith("tagged-")}
    assert untagged == tagged
    assert set(untagged) == {s.lower() for s in P.ATTACK_SUBTYPES}


def test_every_attack_subtype_has_a_corpus_file():
    for st in P.ATTACK_SUBTYPES:
        assert (ROOT / "corpora" / M3.rel_for(st)).exists(), st


def test_the_three_subtypes_are_disjoint_corpora_with_no_matched_pairs():
    """The fact DEV-P1-6 rests on: the sealed between-subtype McNemar is not computable,
    because the subtypes share no item. Derived here rather than remembered."""
    ids = {}
    for st in P.ATTACK_SUBTYPES:
        items = R.load_corpus(M3.rel_for(st))
        ids[st] = {it["id"] for it in items}
    a, b, c = (ids[s] for s in P.ATTACK_SUBTYPES)
    assert not (a & b) and not (b & c) and not (a & c)


def test_each_subtype_stratum_meets_the_sealed_floor():
    """The seal says n>=60 each. A stratum below it would still produce a Wilson interval,
    just a wider one, so the floor has to be checked rather than assumed from the total."""
    for st in P.ATTACK_SUBTYPES:
        assert len(R.load_corpus(M3.rel_for(st))) >= 60, st


def test_hit_prompt_attack_reads_the_single_api_filter_not_the_corpus_label():
    """The label reader would look for a content-filter type called JAILBREAK, never find
    it, and report recall 0/360 for a filter that fired on every item."""
    asm = R.Assessment(detected_types=["PROMPT_ATTACK"])
    assert P.hit_prompt_attack({"label": "JAILBREAK"}, asm) is True
    assert P.hit_prompt_attack({"label": "PROMPT_LEAKAGE"}, asm) is True


def test_hit_prompt_attack_is_false_for_a_different_category():
    """Mutation check: a reader that returned True on any detection would score a VIOLENCE
    hit as prompt-attack recall."""
    asm = R.Assessment(detected_types=["VIOLENCE"])
    assert P.hit_prompt_attack({"label": "JAILBREAK"}, asm) is False


def test_the_attack_strength_is_the_recommended_one():
    assert M3.STRENGTH == P.RECOMMENDED_ATTACK_STRENGTH == "HIGH"


# ======================================================== F3-5 — denied topic

def test_the_topic_plan_has_both_arms_and_reads_the_deviation_tree():
    rows = M4.plan(None)
    assert [lbl for lbl, _r, _n in rows] == ["in-topic", "off-topic"]
    assert M4.DEV_ROOT.name == "corpora_deviation"
    for _l, rel, n in rows:
        assert n == len(R.load_corpus(rel, root=DEV_ROOT)) == 60


def test_the_topic_corpora_are_not_in_the_sealed_tree():
    """The provenance DEV-P1-4 turns on: these two files are unsealed, which is exactly
    why F3-5's `n_met` is vacuous. If they ever moved into `corpora/`, the deviation entry
    would be quietly wrong, so the absence is asserted."""
    assert not (ROOT / "corpora" / M4.IN_TOPIC).exists()
    assert not (ROOT / "corpora" / M4.OFF_TOPIC).exists()
    assert O.planned_n("F3-5") is None


def test_hit_topic_scores_both_arms_against_the_same_configured_topic():
    """A reader keyed on the item's label would look for a topic called TOPIC_OFF, never
    find it, and report an FPR of exactly zero for any configuration at all — including one
    with no topic policy."""
    hit = P.hit_topic("Investment Advice")
    on = R.Assessment(topics_detected=["Investment Advice"])
    assert hit({"label": "TOPIC_IN"}, on) is True
    assert hit({"label": "TOPIC_OFF"}, on) is True
    assert hit({"label": "TOPIC_IN"}, R.Assessment()) is False


def test_hit_topic_is_false_for_a_different_topic_name():
    """The mutation that a label-keyed reader would hide: a topic name that disagrees with
    the provisioned guardrail yields recall 0 and FPR 0, a clean-looking pair describing a
    comparison that never happened."""
    hit = P.hit_topic("Investment Advice")
    assert hit({}, R.Assessment(topics_detected=["Legal Advice"])) is False


def test_configured_topic_refuses_a_manifest_with_no_topic():
    """The manifest is the only place the provisioned name exists; silence there must be
    fatal rather than defaulting to a constant that may not have been provisioned.

    Passing `{}` also pins a real defect this test found: the readers used
    `man or manifest()`, so an EMPTY manifest — one read and found to record nothing — fell
    through to re-reading the file from disk, and the caller's stated-empty argument was
    silently replaced by whatever was on disk.
    """
    with pytest.raises(RuntimeError, match="records no `topic`"):
        P.configured_topic({})


def test_configured_words_refuses_a_manifest_with_no_words():
    with pytest.raises(RuntimeError, match="records no `words`"):
        P.configured_words({"topic": "Investment Advice"})


@pytest.mark.parametrize("reader,exc", [
    (P.configured_topic, RuntimeError),
    (P.configured_words, RuntimeError),
    (lambda man: P.guardrail("topic", man=man), KeyError),
])
def test_an_empty_manifest_is_not_treated_as_an_absent_one(reader, exc):
    """All three readers, because the fix had to land at all three sites.

    The failure mode is not cosmetic: with no `results/phase1_guardrails.json` on disk, the
    fall-through raised FileNotFoundError about a missing provisioning step instead of the
    missing key the caller passed — a diagnosis pointing at the wrong cause.
    """
    with pytest.raises(exc):
        reader({})


def test_configured_topic_returns_the_manifest_value():
    assert P.configured_topic({"topic": "Investment Advice"}) == "Investment Advice"
    assert P.configured_words({"words": ["moonquake"]}) == ["moonquake"]


def test_the_off_topic_controls_are_near_topic_by_construction():
    """The interpretive claim in the dry-run banner, checked against the corpus: a FALSE
    verdict means "the definition does not separate advice from adjacent finance", not
    "topic filtering does not work". That reading is only available if the controls really
    are near-topic, so the labels are verified rather than trusted."""
    off = R.load_corpus(M4.OFF_TOPIC, root=DEV_ROOT)
    assert {it["label"] for it in off} == {"TOPIC_OFF"}
    assert len(off) == 60


# ======================================================== F3-6 — word probe

def test_the_word_probe_labels_partition_into_expected_block_and_clear():
    items = R.load_corpus(M5.PROBE, root=DEV_ROOT)
    labels = {it["label"] for it in items}
    assert labels == set(M5.EXPECT_BLOCK) | set(M5.EXPECT_CLEAR)


def test_the_two_expectation_sets_are_disjoint():
    """An overlapping label would be counted as both an adverse event and a clean one, and
    the union the ceiling is denominated in would double-count it."""
    assert not (set(M5.EXPECT_BLOCK) & set(M5.EXPECT_CLEAR))


def test_case_folding_is_on_the_blocking_side():
    """`LISTED_CASE` is a case variant of a listed term, not a near-miss: if the service
    treats it as a miss, that is a finding about case sensitivity, and putting it on the
    clear side would make that finding unobservable."""
    assert "LISTED_CASE" in M5.EXPECT_BLOCK
    assert "LISTED_CASE" not in M5.EXPECT_CLEAR


def test_the_word_probe_has_items_on_both_sides():
    """A one-sided probe cannot falsify "exact match": with no near-misses, every possible
    result is consistent with a substring matcher."""
    items = R.load_corpus(M5.PROBE, root=DEV_ROOT)
    n_block = sum(1 for it in items if it["label"] in M5.EXPECT_BLOCK)
    n_clear = sum(1 for it in items if it["label"] in M5.EXPECT_CLEAR)
    assert n_block > 0 and n_clear > 0
    assert n_block + n_clear == len(items) == 66


def test_the_word_probe_n_is_the_rule_of_three_size_named_in_the_deviation():
    """66 items buys a one-sided 95% ceiling of ~4.4% on a zero adverse count; 20 would
    buy 13.9%, which is nothing publishable. The size is the argument, so it is pinned."""
    import stats as S
    items = R.load_corpus(M5.PROBE, root=DEV_ROOT)
    assert len(items) == 66
    assert S.rule_of_three(len(items)) == pytest.approx(0.0444, abs=5e-4)
    assert S.rule_of_three(20) == pytest.approx(0.1391, abs=5e-4)


def test_hit_word_reads_any_match_not_the_item_slot():
    """A near-miss item that blocked would, by definition, not match a listed term.
    Restricting to the slot would score every near-miss block as a clean non-detection —
    discarding exactly the half of the corpus that makes "exact match" falsifiable."""
    asm = R.Assessment(words_detected=["moonquake"])
    assert P.hit_word({"slot": "quaxlinate"}, asm) is True
    assert P.hit_word({"slot": "moonquake"}, R.Assessment()) is False


def test_the_word_plan_is_a_single_arm_over_the_unsealed_probe():
    rows = M5.plan(None)
    assert len(rows) == 1
    assert rows[0][1] == M5.PROBE
    assert O.planned_n("F3-6") is None
    assert not (ROOT / "corpora" / M5.PROBE).exists()


# ======================================================== F3-7 — grounding

def test_three_blocks_tags_the_source_and_query_and_leaves_the_response_untagged():
    """The response block must carry no qualifier: a tagged response would be scored as
    source material against itself."""
    item = {"grounding_source": "S", "query": "Q", "text": "R"}
    blocks = M6.three_blocks(item)
    assert len(blocks) == 3
    assert blocks[0]["text"]["qualifiers"] == ["grounding_source"]
    assert blocks[1]["text"]["qualifiers"] == ["query"]
    assert "qualifiers" not in blocks[2]["text"]
    assert [b["text"]["text"] for b in blocks] == ["S", "Q", "R"]


@pytest.mark.parametrize("missing", ["grounding_source", "query", "text"])
def test_three_blocks_raises_on_a_missing_field(missing):
    """Direct indexing, deliberately. `.get` would send a request the service accepts and
    scores against an empty source — a rate about nothing, indistinguishable from a rate
    about a working filter."""
    item = {"grounding_source": "S", "query": "Q", "text": "R"}
    del item[missing]
    with pytest.raises(KeyError):
        M6.three_blocks(item)


def test_every_grounding_item_has_the_three_fields():
    """Mutation check on the guard above: if the corpus were missing a field, the raise
    would fire mid-run after the spend rather than here."""
    for rel in (M6.UNGROUNDED, M6.GROUNDED):
        for it in R.load_corpus(rel, root=DEV_ROOT):
            assert M6.three_blocks(it)


def test_content_units_counts_distinct_source_query_pairs_not_items():
    """The honesty of the interval depends on this: items sharing a (source, query) pair
    are not independent stimuli, so an interval at n=items is narrower than the design
    justifies."""
    items = [{"grounding_source": "S", "query": "Q", "text": "a"},
             {"grounding_source": "S", "query": "Q", "text": "b"},
             {"grounding_source": "T", "query": "Q", "text": "c"}]
    assert M6.content_units(items) == 2
    assert len(items) == 3


def test_the_shipped_grounding_corpus_has_fewer_units_than_items():
    """The condition that makes the disclosure necessary. If units == items the caveat
    would be true but vacuous, so the actual ratio is measured."""
    ung = R.load_corpus(M6.UNGROUNDED, root=DEV_ROOT)
    assert M6.content_units(ung) < len(ung) == 60


def test_content_units_of_an_empty_list_is_zero():
    assert M6.content_units([]) == 0


def test_the_grounding_plan_runs_the_ungrounded_arm_first():
    """Order matters for a smoke run: `--n 3` on the recall arm is the arm that can fail
    informatively, and spending the first three calls on the control would not."""
    rows = M6.plan(None)
    assert [lbl for lbl, _r, _n in rows] == ["ungrounded", "grounded"]
    assert all(n == 60 for _l, _r, n in rows)


def test_hit_grounding_names_the_filter_rather_than_taking_any_detection():
    """A corpus whose ungrounded items were also off-topic would let a RELEVANCE block be
    counted as grounding detection, and the two filters are configured together."""
    hit = P.hit_grounding("GROUNDING")
    g_only = R.Assessment(grounding=[{"type": "GROUNDING", "detected": True},
                                     {"type": "RELEVANCE", "detected": False}])
    r_only = R.Assessment(grounding=[{"type": "GROUNDING", "detected": False},
                                     {"type": "RELEVANCE", "detected": True}])
    assert hit({}, g_only) is True
    assert hit({}, r_only) is False
    assert P.hit_grounding("RELEVANCE")({}, r_only) is True


def test_hit_grounding_is_false_when_the_filter_did_not_report():
    """An absent assessment is not a non-detection reported as False by the service; both
    read False here, which is why the payload reports the raw grounding list too."""
    assert P.hit_grounding("GROUNDING")({}, R.Assessment()) is False


def test_the_grounding_call_sends_three_blocks_so_the_unit_projection_triples():
    """`blocks_per_call=3` in the dry run is not cosmetic: it is the text-unit projection
    the phase budget is approved against."""
    ung = R.load_corpus(M6.UNGROUNDED, root=DEV_ROOT)
    assert len(M6.three_blocks(ung[0])) == 3


# ============================================================= cross-case invariants

def test_every_f3_case_id_is_in_the_seal():
    for cid in list(M1.CASES) + [M2.CASE, M3.CASE, M4.CASE, M5.CASE, M6.CASE]:
        assert cid in O.BINDINGS, cid


def test_the_six_scripts_cover_the_nine_sealed_phase1_f3_cases():
    """F3-1..F3-9 minus nothing: if a case had no script, the coverage matrix would still
    list it and the gap would only show up as a missing result file."""
    covered = set(M1.CASES) | {M2.CASE, M3.CASE, M4.CASE, M5.CASE, M6.CASE}
    assert covered == {f"F3-{i}" for i in range(1, 10)}


def test_every_plan_is_a_list_of_label_corpus_count_triples():
    """`dry_run_banner` and `run_arms` both index these positionally; a shape drift would
    misreport the projection or send the wrong corpus."""
    for mod in (M1, M2, M3, M4, M5, M6):
        for row in mod.plan(None):
            assert len(row) == 3
            label, corpus, n = row
            assert isinstance(label, str) and label
            assert isinstance(corpus, str) and corpus
            assert isinstance(n, int) and n > 0


def test_every_plan_is_capped_by_a_smoke_n():
    """A `--n 3` that did not cap would make the smoke run the full run — the exact
    dry-run-before-expensive-run failure this project screens for."""
    for mod in (M1, M2, M3, M4, M5, M6):
        assert all(n <= 3 for _l, _c, n in mod.plan(3)), mod.__name__


def test_no_two_f3_cases_read_the_same_arm_label_from_different_corpora():
    """Labels are the join key in the result files; two corpora under one label would make
    a per-arm rate unattributable."""
    seen: dict[str, set] = {}
    for mod in (M1, M2, M3, M4, M5, M6):
        for label, corpus, _n in mod.plan(None):
            seen.setdefault(label, set()).add(corpus)
    multi = {k: v for k, v in seen.items() if len(v) > 1}
    # The content-filter arms deliberately share one label across the five category
    # corpora, because the arm IS the strength; every other label must be unique.
    assert all(k.startswith("cf-") for k in multi), multi


def test_the_unsealed_cases_are_exactly_the_three_named_in_the_deviation():
    """DEV-P1-4's actual deviation is F3-5, F3-6 and F3-7 — the three rate cases with no
    pre-registered n. Re-derived from the seal so the entry cannot drift."""
    f3 = [f"F3-{i}" for i in range(1, 10)]
    assert [c for c in f3 if O.planned_n(c) is None] == \
        ["F3-5", "F3-6", "F3-7", "F3-9"]
    # F3-9 is the ROC lattice: its oracle takes no rate, so it is not part of the
    # deviation. The three that are, all read `corpora_deviation/`.
    man = json.loads((DEV_ROOT / "MANIFEST.json").read_text())
    assert set(man["cases"].values()) == {"F3-5", "F3-6", "F3-7"}
    assert man["sealed"] is False
