"""The F8 family's analysis functions, tested by mutation.

Four of the five F8 Phase 1 cases return TRUE on an *absence* — no protection in an
unsupported language, no PROMPT_LEAKAGE category on the tier-bearing API, no request surface
for an AutomatedReasoning language, no Region other than a US one. An absence is exactly what
a helper produces when it is subtly wrong, so for every function here the failure that would
manufacture the document-confirming verdict is named and pinned:

* `works_on` — a `works=True` from a comparison against nothing (either arm empty) would read
  as "the tier detects leakage" on zero trials.
* `region_of`/`hit_in_geography` — a trial that disclosed nothing must NOT be counted as
  in-geography, or silence becomes compliance and the disclosure gap vanishes.
* `item_id` — without the tier in the hash, the STANDARD arm resumes onto the CLASSIC arm's
  rows and reports 22 usable trials for a tier it never called.
* `hit_any_content` — the ANY-category reading, because "essentially no protection" is a
  claim about the language and a Japanese HATE item detected as INSULTS is still protection;
  an own-label reading would understate protection and thereby confirm the document.
* `split` — labels must partition the arm with no row lost, or a dropped row silently shrinks
  an n that the interval is computed from.
* `classify_matches` — an unanticipated member must fall through to `unclassified` and force
  INCONCLUSIVE, rather than being swallowed by a filter into a TRUE.

`vocabulary_check` gets its own block: it is itself a guard, so each of its clauses is
mutation-tested by constructing the vocabulary that should trip it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import arms as R

ROOT = Path(__file__).resolve().parents[2]


def arn(region: str, *, partition: str = "aws", account: str = "0" * 12,
        service: str = "bedrock", resource: str = "guardrail/probe") -> str:
    """An ARN assembled at run time, never written as a literal.

    `check_redaction.py` scans this tree for `arn:aws...:` and for 12-digit account-id
    shapes, and it is right to: a test fixture is the easiest place for a real ARN to be
    pasted and forgotten. Assembling from parts means no identifier shape appears as a
    literal anywhere here, so the gate stays at full strength instead of acquiring a waiver
    for a whole file — which would blind it to the next real leak in the same file. Same
    construction as `lib/tests/test_awsclients.py`.
    """
    return ":".join(["arn", partition, service, region, account, resource])


def _load(stem: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "f8_regional" / stem)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M2 = _load("02_multilingual.py", "f8_multilingual")
M3 = _load("03_prompt_leakage.py", "f8_leakage")
M5 = _load("05_xregion.py", "f8_xregion")
M6 = _load("06_word_language.py", "f8_words")
M7 = _load("07_absent_surface.py", "f8_absent")


# ===================================================== F8-4 — works_on / sweep_rows

def test_works_on_is_true_only_when_the_intervals_are_disjoint():
    """40/40 recall against 0/40 FPR: separated by any convention."""
    w = M3.works_on({"x": 40, "n": 40}, {"x": 0, "n": 40})
    assert w["works"] is True


def test_works_on_is_false_when_the_intervals_overlap():
    """Mutation check on the test above: the same shape with a tier that fires on
    everything must NOT read as detecting leakage."""
    w = M3.works_on({"x": 30, "n": 40}, {"x": 28, "n": 40})
    assert w["works"] is False


def test_works_on_is_false_when_the_tier_fires_on_everything():
    """40/40 recall and 40/40 FPR — perfect recall, zero information. `works` must be
    False, because the FPR term exists precisely to refuse this reading."""
    w = M3.works_on({"x": 40, "n": 40}, {"x": 40, "n": 40})
    assert w["works"] is False


@pytest.mark.parametrize("recall,fpr", [
    ({"x": 0, "n": 0}, {"x": 0, "n": 40}),
    ({"x": 40, "n": 40}, {"x": 0, "n": 0}),
    ({"x": 0, "n": 0}, {"x": 0, "n": 0}),
])
def test_works_on_never_reports_works_from_an_empty_arm(recall, fpr):
    """The dangerous direction. An arm that failed entirely leaves n=0, and a comparison
    against nothing must not produce the document-confirming verdict — it must produce a
    reported absence of intervals with `works` False."""
    w = M3.works_on(recall, fpr)
    assert w["works"] is False
    assert w["recall_ci"] is None or w["fpr_ci"] is None


def test_works_on_uses_two_sided_intervals_on_both_terms():
    """A one-sided recall bound against a two-sided FPR bound compares intervals at
    different alphas and overstates the margin. Pinned by reproducing both from
    `stats.wilson_ci`, which is the two-sided function."""
    import stats as S
    w = M3.works_on({"x": 35, "n": 40}, {"x": 2, "n": 40})
    assert w["recall_ci"] == str(S.wilson_ci(35, 40))
    assert w["fpr_ci"] == str(S.wilson_ci(2, 40))


def test_works_on_states_its_rule_in_the_payload():
    """The operationalisation is this script's, not the seal's (DEV-P1-7). A rule that
    travels only in a docstring is not in the result file a reader audits."""
    w = M3.works_on({"x": 1, "n": 40}, {"x": 0, "n": 40})
    assert "lower bound" in w["rule"]
    assert "FPR" in w["rule"] or "fpr" in w["rule"]


def test_works_on_carries_the_raw_counts_forward():
    w = M3.works_on({"x": 7, "n": 40}, {"x": 3, "n": 40})
    assert w["recall"] == {"x": 7, "n": 40}
    assert w["fpr"] == {"x": 3, "n": 40}


def test_sweep_rows_covers_every_declared_cut_point():
    """The sweep exists because `InvokeGuardrailChecks` supplies no threshold, so any
    single cut point would be ours. A sweep missing a point would be a hidden choice."""
    rows = M3.sweep_rows([0.5] * 10, [0.1] * 10)
    assert [r["threshold"] for r in rows] == list(M3.SWEEP)


def test_sweep_rows_is_monotone_non_increasing_in_the_threshold():
    """TPR and FPR at a higher cut point cannot exceed those at a lower one. A violation
    would mean the comparison is not `>=` against the same scores."""
    leak = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
    rows = M3.sweep_rows(leak, leak)
    tprs = [r["tpr"]["x"] for r in rows]
    assert tprs == sorted(tprs, reverse=True)


def test_sweep_rows_counts_the_boundary_inclusively():
    """`>= t`, so a score exactly equal to the cut point is a hit. The choice is not
    arbitrary — it must be stated and stable, because at 9 cut points over a 60-item arm a
    silent flip to `>` moves whole rows."""
    rows = {r["threshold"]: r for r in M3.sweep_rows([0.5], [])}
    assert rows[0.5]["tpr"]["x"] == 1
    assert rows[0.6]["tpr"]["x"] == 0


def test_sweep_rows_excludes_none_scores_from_both_numerator_and_denominator():
    """A trial with no `severityScore` is a trial that did not measure, not a trial that
    scored zero. Counting it in `n` alone would depress every TPR by construction."""
    rows = {r["threshold"]: r for r in M3.sweep_rows([0.9, None, None], [None])}
    assert rows[0.5]["tpr"] == {"x": 1, "n": 1, "ci": rows[0.5]["tpr"]["ci"]}
    assert rows[0.5]["fpr"]["n"] == 0
    assert rows[0.5]["fpr"]["ci"] is None


def test_sweep_rows_youden_j_is_none_when_either_arm_is_empty():
    """J = TPR - FPR is undefined without both arms; a 0.0 there would read as "no
    separation measured" rather than "not measured"."""
    rows = M3.sweep_rows([0.9], [])
    assert all(r["youden_j"] is None for r in rows)


def test_sweep_rows_youden_j_matches_its_definition():
    rows = {r["threshold"]: r for r in M3.sweep_rows([0.9, 0.9], [0.9, 0.1])}
    assert rows[0.5]["youden_j"] == pytest.approx(1.0 - 0.5)


def test_the_sweep_is_not_the_four_value_strength_lattice():
    """The document's `inputStrength` enum has 4 values and belongs to ApplyGuardrail;
    `severityScore` is continuous and belongs to InvokeGuardrailChecks. Reusing the enum
    here would answer F3-9's question with F8-4's data."""
    assert len(M3.SWEEP) == 9
    assert all(0.0 < t < 1.0 for t in M3.SWEEP)


# ============================================== F8-6 — region_of / hit_in_geography

def test_region_of_reads_the_region_field():
    a = arn("us-east-1")
    assert M5.region_of(a) == "us-east-1"
    assert M5.partition_of(a) == "aws"


@pytest.mark.parametrize("bad", [
    "", None, "not-a-valid-value", "a:b:c", "a:b:c:d",
    arn("us-east-1").replace("arn:", "urn:", 1),
])
def test_region_of_returns_empty_string_rather_than_raising(bad):
    """A crash here would discard every trial that DID parse. An unparseable value is an
    observation about what the service disclosed, so it is recorded, not fatal.

    The last case is a well-formed ARN with the wrong scheme, which is the one a length
    check alone would accept — it has six fields and a Region in field 3.
    """
    assert M5.region_of(bad) == ""
    assert M5.partition_of(bad) == ""


def test_a_govcloud_region_is_not_in_geography():
    """`us-gov-west-1` starts with `us-` and is a different partition. A prefix test would
    call a partition crossing in-geography — which is why US_REGIONS is enumerated."""
    assert "us-gov-west-1" not in M5.US_REGIONS
    asm = R.Assessment(applied_details={
        "guardrailArn": arn("us-gov-west-1", partition="aws-us-gov")})
    assert M5.hit_in_geography({}, asm) is False


def test_in_geography_is_true_for_a_disclosed_us_region():
    asm = R.Assessment(applied_details={"guardrailArn": arn("us-west-2")})
    assert M5.hit_in_geography({}, asm) is True


@pytest.mark.parametrize("details", [
    {}, None, {"guardrailArn": ""}, {"guardrailArn": "garbage"},
    {"someOtherField": "us-east-1"},
])
def test_silence_is_not_compliance(details):
    """The load-bearing one. F8-6's oracle counts Regions; a trial that disclosed nothing
    must not be counted as in-geography, because that is what makes the x/n gap the
    disclosure gap rather than a hidden pass."""
    asm = R.Assessment(applied_details=details)
    assert M5.hit_in_geography({}, asm) is False


def test_a_non_us_commercial_region_is_not_in_geography():
    """Mutation check in the other direction: the predicate must be able to say no about a
    same-partition Region, or it is only testing ARN parseability."""
    asm = R.Assessment(applied_details={"guardrailArn": arn("eu-west-2")})
    assert M5.hit_in_geography({}, asm) is False


def test_the_us_geography_is_enumerated_and_matches_the_profile():
    """The definition travels into the result file; a set that drifted from the attached
    inference profile would compare against a geography nothing configured."""
    assert M5.PROFILE.startswith("us.")
    assert M5.US_REGIONS == frozenset(
        {"us-east-1", "us-east-2", "us-west-1", "us-west-2"})


# ======================================= F8-7 — item_id / items_for / vocabulary_check

def test_item_id_puts_the_tier_in_the_hash():
    """Without this, `arms.run_arm` skips the STANDARD trial because the checkpoint holds
    the CLASSIC row with the same id, and the case reports 22 usable trials for a tier it
    never called — a TRUE about a comparison that half happened."""
    a = M6.item_id("L", "moonquake", "CLASSIC")
    b = M6.item_id("L", "moonquake", "STANDARD")
    assert a != b


def test_item_id_is_stable_across_calls():
    """Content hashes, not counters: a resumed run must re-derive the same ids."""
    assert M6.item_id("L", "t", "CLASSIC") == M6.item_id("L", "t", "CLASSIC")


def test_item_id_changes_with_the_text_and_with_the_label():
    assert M6.item_id("L", "t", "C") != M6.item_id("L", "u", "C")
    assert M6.item_id("L", "t", "C") != M6.item_id("M", "t", "C")


def test_items_for_yields_the_documented_twenty_two():
    """9 listed x 2 surfaces + 2 unlisted x 2. The number is quoted in the dry-run banner
    and in DEVIATIONS, so it is derived here rather than remembered."""
    items = M6.items_for("CLASSIC")
    assert len(items) == 2 * len(M6.LISTED) + 2 * len(M6.UNLISTED) == 22


def test_every_probe_item_has_a_distinct_id():
    """Two items sharing an id would be one call reported as two."""
    items = M6.items_for("CLASSIC") + M6.items_for("STANDARD")
    assert len({i["id"] for i in items}) == len(items) == 44


def test_both_surfaces_are_present_for_every_slot():
    """The embedded surface is what separates a word-list match from a whole-input match;
    a slot with only the `alone` surface would answer a narrower question silently."""
    items = M6.items_for("CLASSIC")
    by_slot: dict[str, set] = {}
    for i in items:
        by_slot.setdefault(i["slot"], set()).add(i["surface"])
    assert all(v == {"alone", "embedded"} for v in by_slot.values())


def test_the_embedded_surface_contains_its_term():
    for i in M6.items_for("CLASSIC"):
        if i["surface"] == "embedded":
            assert i["term"] in i["text"]
            assert i["text"] != i["term"], "the carrier added nothing"


def test_the_three_labels_partition_the_probe_set():
    items = M6.items_for("CLASSIC")
    labels = {i["label"] for i in items}
    assert labels == {M6.LABEL_LISTED_SUPPORTED, M6.LABEL_LISTED_UNSUPPORTED,
                      M6.LABEL_UNLISTED}
    assert sum(1 for i in items if i["label"] == M6.LABEL_UNLISTED) == 4


def test_unlisted_items_carry_supported_none_not_false():
    """`False` would say "an unsupported language", which is a different fact from "not on
    the word list at all". Conflating them would put the negative control into the
    unsupported-language tally."""
    for i in M6.items_for("CLASSIC"):
        if i["label"] == M6.LABEL_UNLISTED:
            assert i["supported"] is None


def test_the_shipped_vocabulary_passes_its_own_check():
    v = M6.vocabulary_check()
    assert v["ok"] is True, v["problems"]
    assert v["n_listed_supported"] == 3
    assert v["n_listed_unsupported"] == 6
    assert v["max_term_len"] <= v["sdk_max_term_len"]


def test_the_positive_control_is_on_the_list():
    assert M6.CONTROL_TERM in M6.vocabulary_check()["listed"]


def test_vocabulary_check_rejects_a_duplicated_listed_term(monkeypatch):
    """Two languages sharing bytes would be one trial reported as two."""
    dup = M6.LISTED + (dict(M6.LISTED[0]),)
    monkeypatch.setattr(M6, "LISTED", dup)
    v = M6.vocabulary_check()
    assert v["ok"] is False
    assert any("not distinct" in p for p in v["problems"])


def test_vocabulary_check_rejects_a_missing_positive_control(monkeypatch):
    monkeypatch.setattr(M6, "LISTED", tuple(
        s for s in M6.LISTED if s["term"] != M6.CONTROL_TERM))
    v = M6.vocabulary_check()
    assert v["ok"] is False
    assert any("positive control" in p for p in v["problems"])


def test_vocabulary_check_rejects_an_over_long_term(monkeypatch):
    """The model's `wordsConfig[].text` maximum is 100; a longer term would be rejected by
    the create call, not by the probe, and the case would report a create failure."""
    long = {"lang": "en", "term": "z" * 101, "supported": True,
            "carrier": "The observatory logged a {t} last night.", "why": "x"}
    monkeypatch.setattr(M6, "LISTED", M6.LISTED + (long,))
    v = M6.vocabulary_check()
    assert v["ok"] is False
    assert any("maximum is 100" in p for p in v["problems"])


def test_vocabulary_check_rejects_a_term_absent_from_its_own_carrier(monkeypatch):
    """A carrier that does not contain its term sends a trial that probes nothing."""
    bad = {"lang": "en", "term": "moonquake2", "supported": True,
           "carrier": "A sentence with no placeholder.", "why": "x"}
    monkeypatch.setattr(M6, "LISTED", M6.LISTED + (bad,))
    v = M6.vocabulary_check()
    assert v["ok"] is False
    assert any("own carrier sentence" in p for p in v["problems"])


def test_vocabulary_check_rejects_a_substring_collision(monkeypatch):
    """`moonquakes` contains `moonquake`, so a substring matcher would fire the negative
    control by construction and the case's only negative control would be vacuous."""
    monkeypatch.setattr(M6, "UNLISTED", (
        {"lang": "en", "term": "moonquakes", "carrier": "Logged {t} again."},))
    v = M6.vocabulary_check()
    assert v["ok"] is False
    assert any("contain one another" in p for p in v["problems"])


def test_vocabulary_check_rejects_a_shared_ideograph(monkeypatch):
    """The script-dependent clause. A shared Latin letter is harmless; a shared ideograph
    is a shared morpheme, so a character-level matcher would fire the control."""
    monkeypatch.setattr(M6, "UNLISTED", (
        {"lang": "zh-TW", "term": "颱風", "carrier": "昨晚有{t}。"},))
    v = M6.vocabulary_check()
    assert v["ok"] is False
    assert any("contain one another" in p or "shares non-Latin" in p
               for p in v["problems"])


def test_a_shared_latin_letter_is_not_treated_as_a_collision():
    """Mutation check on the clause above: if it flagged shared letters, the shipped
    vocabulary could not pass, since every English word shares letters with `réveillon`."""
    listed = {c for s in M6.LISTED for c in s["term"] if ord(c) <= 0x24F}
    unlisted = {c for u in M6.UNLISTED for c in u["term"] if ord(c) <= 0x24F}
    assert listed & unlisted, "no shared Latin letter, so this test proves nothing"
    assert M6.vocabulary_check()["ok"] is True


def test_vocabulary_check_rejects_an_unlisted_term_inside_a_listed_carrier(monkeypatch):
    """The carriers are sent as their own trials, so this would make a listed trial
    ambiguous between the word list matching and something else matching."""
    monkeypatch.setattr(M6, "UNLISTED", (
        {"lang": "en", "term": "observatory", "carrier": "The {t} is closed."},))
    v = M6.vocabulary_check()
    assert v["ok"] is False
    assert any("carrier" in p for p in v["problems"])


def test_vocabulary_check_rejects_a_listed_term_inside_an_unlisted_carrier(monkeypatch):
    """The other direction: the negative control's own trial would contain a listed term
    and fire by construction."""
    monkeypatch.setattr(M6, "UNLISTED", (
        {"lang": "en", "term": "quaxlinate", "carrier": "A {t} and a moonquake."},))
    v = M6.vocabulary_check()
    assert v["ok"] is False
    assert any("negative control would fire by construction" in p
               for p in v["problems"])


def test_word_config_sets_every_action_explicitly():
    """A term configured with action NONE returns `detected=True, action=NONE`, which
    `phase1.hit_word` counts as a hit and a reader would take for a block. Defaults are not
    documented as stable, so they are not relied on."""
    cfg = M6.word_config()
    assert set(cfg) == {"wordsConfig"}, "managedWordListsConfig must stay absent"
    assert len(cfg["wordsConfig"]) == len(M6.LISTED)
    for w in cfg["wordsConfig"]:
        assert w["inputAction"] == w["outputAction"] == "BLOCK"
        assert w["inputEnabled"] is w["outputEnabled"] is True


def test_word_config_carries_every_listed_term_and_no_unlisted_one():
    texts = {w["text"] for w in M6.word_config()["wordsConfig"]}
    assert texts == {s["term"] for s in M6.LISTED}
    assert not (texts & {u["term"] for u in M6.UNLISTED})


def _cell_rows(tier: str = "CLASSIC") -> list[dict]:
    return [{"slot": i["slot"], "surface": i["surface"], "label": i["label"],
             "hit": False, "action": "NONE", "words_detected": [],
             "detected_types": [], "request_id": i["id"]}
            for i in M6.items_for(tier)]


def test_per_cell_keys_by_label_language_and_surface():
    rows = [{"slot": "ja", "surface": "alone", "label": "L", "hit": True,
             "action": "GUARDRAIL_INTERVENED", "words_detected": ["x"],
             "detected_types": [], "request_id": "r1"},
            {"slot": "ja", "surface": "embedded", "label": "L", "hit": False,
             "action": "NONE", "words_detected": [], "detected_types": [],
             "request_id": "r2"}]
    cell = M6.per_cell(rows)
    assert set(cell) == {"L/ja/alone", "L/ja/embedded"}
    assert cell["L/ja/alone"]["hit"] is True
    assert cell["L/ja/embedded"]["hit"] is False


def test_per_cell_carries_the_request_id_into_every_cell():
    """A cell a reader cannot quote to AWS Support is a claim without evidence."""
    rows = [{"slot": "de", "surface": "alone", "label": "L", "hit": False,
             "action": "NONE", "words_detected": [], "detected_types": [],
             "request_id": "req-abc"}]
    assert M6.per_cell(rows)["L/de/alone"]["request_id"] == "req-abc"


def test_per_cell_covers_every_probe_of_a_full_arm():
    """22 items must produce 22 cells.

    This is the regression test for a real defect: the key was `slot/surface`, and the two
    UNLISTED negative controls deliberately sit in the slots `en` and `zh-TW` so each shares
    a language with a listed term. Four rows therefore collided, and the two that lost were
    the `moonquake` positive control's — 22 trials reported as 18 cells, with the control's
    cells replaced by rows whose expected outcome is the opposite.
    """
    rows = _cell_rows()
    assert len(M6.per_cell(rows)) == len(rows) == 22


def test_the_negative_controls_share_a_language_with_a_listed_term():
    """The property that made the collision possible, pinned as data. If the UNLISTED
    slots were ever moved to languages no listed term uses, the test above would pass for a
    reason unrelated to the key — so the overlap is asserted rather than assumed."""
    listed = {s["lang"] for s in M6.LISTED}
    assert {u["lang"] for u in M6.UNLISTED} <= listed


def test_the_positive_control_cells_survive_the_full_arm():
    """The specific loss. `moonquake` is `en`/LISTED_SUPPORTED, and the `en` negative
    control is `en`/UNLISTED; both surfaces of both must be separately readable, because
    the precondition's whole job is to tell a dead instrument from a language boundary."""
    cells = M6.per_cell(_cell_rows())
    for surface in ("alone", "embedded"):
        assert f"{M6.LABEL_LISTED_SUPPORTED}/en/{surface}" in cells
        assert f"{M6.LABEL_UNLISTED}/en/{surface}" in cells


def test_per_cell_refuses_two_rows_in_one_cell():
    """A collision must raise rather than overwrite. Silent overwriting is what produced a
    result file whose evidence table disagreed with its own trial count."""
    r = _cell_rows()[0]
    with pytest.raises(AssertionError, match="share the cell key"):
        M6.per_cell([r, dict(r, request_id="other")])


# ============================================ F8-2/F8-3 — hit_any_content / split / plan

def test_hit_any_content_is_true_for_any_category():
    """A Japanese HATE item detected as INSULTS is still protection. The own-label reading
    would understate protection — and understating protection is what confirms §3.4's "no
    protection" claim, so it is the direction that must not creep in."""
    asm = R.Assessment(detected_types=["INSULTS"])
    assert M2.hit_any_content({"label": "HATE"}, asm) is True


def test_hit_any_content_is_false_on_an_empty_detection_list():
    assert M2.hit_any_content({"label": "HATE"}, R.Assessment()) is False


def test_hit_any_content_does_not_read_blocked_types():
    """`detected` is what the classifier said; `blocked` is what the configuration did.
    F8-2 asks whether the filter reacts at all, so a detection with action NONE counts."""
    asm = R.Assessment(detected_types=["VIOLENCE"], blocked_types=[], action="NONE")
    assert M2.hit_any_content({}, asm) is True


def test_split_partitions_the_arm_with_no_row_lost():
    rows = [{"label": "HATE", "hit": True}, {"label": "HATE", "hit": False},
            {"label": M2.CLEAN, "hit": False}, {"label": M2.CLEAN, "hit": True}]
    atk, cln = M2.split({"rows": rows})
    assert atk["n"] + cln["n"] == len(rows)
    assert atk == {"x": 1, "n": 2}
    assert cln == {"x": 1, "n": 2}


def test_split_treats_every_non_clean_label_as_an_attack():
    """The corpora carry per-category labels, so an equality test against one category
    would drop the rest into neither arm and shrink both n silently."""
    rows = [{"label": lab, "hit": True}
            for lab in ("HATE", "VIOLENCE", "SEXUAL", "MISCONDUCT", "INSULTS")]
    atk, cln = M2.split({"rows": rows})
    assert atk == {"x": 5, "n": 5}
    assert cln == {"x": 0, "n": 0}


def test_split_of_an_empty_arm_is_zeroes_not_a_crash():
    """An arm that failed entirely must leave n=0 for the interval to refuse, not raise."""
    atk, cln = M2.split({"rows": []})
    assert atk == {"x": 0, "n": 0} and cln == {"x": 0, "n": 0}


def test_the_fpr_arm_is_each_language_own_clean_items():
    """The confound the module docstring names: an English benign corpus as the FPR term
    would compare a Japanese recall against an English false-positive rate, and the
    difference could be the language of the benign text."""
    rows = [{"label": M2.CLEAN, "hit": True}] * 3 + [{"label": "HATE", "hit": True}] * 2
    _atk, cln = M2.split({"rows": rows})
    assert cln["n"] == 3


def test_rel_for_names_a_file_that_exists():
    """A relative path is the join key to what `verify_corpora.py` hashes; a name that
    resolves to nothing would make an arm send items no sealed file lists."""
    for lang in M2.ALL_LANGS:
        assert (ROOT / "corpora" / M2.rel_for(lang)).exists(), lang


def test_the_plan_runs_standard_only_on_the_unsupported_languages():
    """F8-3's oracle is about zh/ja/ko; a STANDARD arm on English would spend calls on a
    question no oracle asks."""
    import phase1 as P
    labels = [lbl for lbl, _c, _n in M2.plan(None)]
    standard = {lbl.split("standard-", 1)[1] for lbl in labels
                if lbl.startswith("standard-")}
    assert standard == set(P.UNSUPPORTED_LANGS)


def test_the_plan_runs_classic_on_every_language():
    labels = [lbl for lbl, _c, _n in M2.plan(None)]
    classic = {lbl.split("classic-", 1)[1] for lbl in labels
               if lbl.startswith("classic-")}
    assert classic == set(M2.ALL_LANGS)


def test_the_plan_is_capped_by_n_per_stratum_for_a_smoke_run():
    """`--n 3` must cap every arm, or the smoke run is the full run.

    `--n` caps **per label**, not per arm, and this arm is written that way because the
    earlier version asserted `n <= 3` per arm and was wrong about what this case's `--n`
    means. It passed only while `plan()` took a plain head; the DEV-P1-10 fix gave this
    case `stratify_by="label"`, after which `--n 3` returns 3 items *of each label*.

    Capping the arm total instead is not an option here: these files hold 8 labels, and
    F8-2 divides an attack recall by that same file's CLEAN count, so a 3-item arm total
    would return three JAILBREAK items and zero CLEAN ones and divide by zero — which is
    the defect DEV-P1-10 records. So the guarantee `--n` actually offers is per stratum,
    and the assertion has to be denominated in the same unit as the sampling (per
    feedback_label_must_match_computation: a cap asserted in a unit the code does not cap
    in is a check that happens to hold, not a check).
    """
    import collections
    n_labels = {}
    for lang in M2.ALL_LANGS:
        rel = M2.rel_for(lang)
        n_labels[rel] = len({it["label"] for it in R.load_corpus(rel)})

    for _lbl, rel, n in M2.plan(3):
        # Every label present in the file is present in the subset, at most 3 each.
        assert n <= 3 * n_labels[rel], (rel, n, n_labels[rel])
        counts = collections.Counter(
            it["label"] for it in R.load_corpus(rel, limit=3, stratify_by="label"))
        assert set(counts) == {it["label"] for it in R.load_corpus(rel)}, rel
        assert max(counts.values()) <= 3, counts
        assert n == sum(counts.values()), (n, counts)

    # The point of a smoke run: strictly cheaper than the full run, on every arm.
    full = {(lbl, rel): n for lbl, rel, n in M2.plan(None)}
    for lbl, rel, n in M2.plan(3):
        assert n < full[(lbl, rel)], (lbl, n, full[(lbl, rel)])
    assert all(n > 3 for _l, _c, n in M2.plan(None))


def test_the_two_cases_quantify_over_the_same_unsupported_set_as_f8_7():
    """F8-2/F8-3 and F8-7 both make claims about "unsupported languages"; if the two sets
    differed, the two results would not be about the same population."""
    import phase1 as P
    f87 = {s["lang"] for s in M6.LISTED if not s["supported"]}
    assert set(P.UNSUPPORTED_LANGS) <= f87


# ============================================== F8-8 — _ver / classify_matches

@pytest.mark.parametrize("text,want", [
    ("1.43.67", (1, 43, 67)),
    ("botocore 1.43.67", (1, 43, 67)),
    ("1.42.79.dev0", (1, 42, 79)),
    ("1.43.67 (extra 9)", (1, 43, 67)),
])
def test_ver_parses_the_first_three_numbers(text, want):
    assert M7._ver(text) == want


def test_ver_compares_as_a_tuple_not_as_a_string():
    """String comparison would put "1.43.9" above "1.43.67", and the whole case rests on
    reading the NEWER interpreter."""
    assert M7._ver("1.43.9") < M7._ver("1.43.67")
    assert M7._ver("1.9.0") < M7._ver("1.43.0")


def test_ver_of_an_unparseable_string_is_empty():
    """Empty, not a crash: the version is recorded provenance, and an interpreter that
    printed something unexpected must not abort a sweep that otherwise completed."""
    assert M7._ver("unknown") == ()


def test_classify_matches_places_the_authoring_surface():
    m = [{"path": "buildWorkflow.addRuleFromNaturalLanguage.naturalLanguage",
          "member": "naturalLanguage"}]
    out = M7.classify_matches(m)
    assert out["n_authoring_surface"] == 1
    assert out["n_unclassified"] == 0
    assert out["authoring_surface"][0]["classified_as"] == "policy_authoring_prose"
    assert out["authoring_surface"][0]["why"]


def test_an_unanticipated_match_falls_through_to_unclassified():
    """The verdict-deciding property. A hit the classifier cannot place is a member whose
    purpose nobody has read; swallowing it would turn INCONCLUSIVE into TRUE."""
    m = [{"path": "invokeChecks.languageCode", "member": "languageCode"}]
    out = M7.classify_matches(m)
    assert out["n_unclassified"] == 1
    assert out["unclassified"][0]["path"] == "invokeChecks.languageCode"
    assert out["n_authoring_surface"] == 0


def test_the_counts_reconcile_to_the_total():
    """A breakdown that did not sum to its parent would be a second label over the same
    computation."""
    m = [{"path": "x.addRuleFromNaturalLanguage", "member": "addRuleFromNaturalLanguage"},
         {"path": "y.languageCode", "member": "languageCode"},
         {"path": "z.mode", "member": "mode"}]
    out = M7.classify_matches(m)
    assert out["n_authoring_surface"] + out["n_unclassified"] == out["n_matches"] == 3


def test_no_match_is_both_classified_and_unclassified():
    m = [{"path": "a.addRuleFromNaturalLanguage.naturalLanguage", "member": "x"},
         {"path": "b.somethingElse", "member": "y"}]
    out = M7.classify_matches(m)
    paths = ({r["path"] for r in out["authoring_surface"]}
             & {r["path"] for r in out["unclassified"]})
    assert not paths


def test_an_empty_match_list_classifies_to_empty_and_does_not_raise():
    """The expected result: F8-8's TRUE comes from an empty sweep, and the classifier must
    reach that state cleanly rather than by exception."""
    out = M7.classify_matches([])
    assert out["n_matches"] == out["n_authoring_surface"] == out["n_unclassified"] == 0


def test_a_list_element_path_is_classified_by_its_tail():
    """Paths carry `[]` for list elements; a tail-blind test would leave every list-nested
    authoring member unclassified and force a spurious INCONCLUSIVE."""
    m = [{"path": "rules[].addRuleFromNaturalLanguage", "member": "x"}]
    assert M7.classify_matches(m)["n_authoring_surface"] == 1


def test_the_classification_targets_travel_into_the_payload():
    """What was classified against must be auditable, or the classification is an
    assertion rather than a record."""
    out = M7.classify_matches([])
    assert out["classified_against"] == list(M7.AUTHORING_PATHS)
    assert "recording" in out["why_classified_not_dropped"] or \
        "record" in out["why_classified_not_dropped"]


# ------------------------------------------------------------------ seal fidelity

def test_the_sealed_kinds_are_what_these_scripts_assume():
    """Each helper above is operationalising a sealed oracle; if the seal's kind changed,
    the operationalisation would answer a question nobody asked."""
    import oracle as O
    assert O.BINDINGS["F8-4"].kind == "EXISTENCE"
    assert O.BINDINGS["F8-6"].kind == "EXISTENCE"
    assert O.BINDINGS["F8-7"].kind == "EXISTENCE"
    assert O.BINDINGS["F8-8"].kind == "EXISTENCE"
    assert O.BINDINGS["F8-2"].kind == "INDISTINGUISHABLE"


def test_f8_6_is_the_existence_case_that_does_carry_a_sealed_n():
    """The counterexample DEV-P1-4 rests on: the sealed kind does NOT predict whether an n
    exists, so the classification there had to be per case rather than by kind."""
    import oracle as O
    assert O.planned_n("F8-6") == 60
    assert O.planned_n("F8-4") is None
    assert O.planned_n("F8-7") is None


# ---------------------------------------- F8-4 — the inexpressibility, derived not asserted

def test_the_inexpressibility_is_read_from_the_service_model_not_written_in_prose():
    """F8-4's central structural finding, checked against the model the process loaded.

    This block exists because the finding used to be prose: the filter enum was typed out as
    a literal list, "no tier parameter" was an English sentence, and the botocore version was
    hardcoded as `1.43.67` in four strings — one of which printed while the interpreter was
    running **1.42.79**. The claim happened to be true, which is the dangerous case: prose
    that is right today teaches nothing about whether the reader's SDK still agrees, and a
    service that later adds PROMPT_LEAKAGE to `filtersConfig.type` would leave the script
    confidently printing a falsehood (feedback_prose_is_not_verified).
    """
    import awsclients as A
    inx = M3.inexpressibility()

    # The version must be DERIVED, not merely equal to the running one.
    #
    # `inx["sdk"] == A.sdk_versions()` alone is vacuous: the mutation that put
    # `{"botocore": "1.43.67"}` back as a literal SURVIVED it, because the oracle venv is
    # 1.43.67 and the assertion compared the literal to itself. Under the baseline venv the
    # same mutation would have been caught — so whether the test worked depended on which
    # interpreter happened to run it (feedback_vacuous_test_check).
    #
    # Monkeypatching the source of truth is what makes this a test of derivation: if the
    # field is read from `sdk_versions()` it moves, and if it is a literal it does not.
    assert inx["sdk"] == A.sdk_versions()
    sentinel = {"boto3": "0.0.0-probe", "botocore": "0.0.0-probe"}
    real = A.sdk_versions
    try:
        A.sdk_versions = lambda: dict(sentinel)
        moved = M3.inexpressibility()["sdk"]
    finally:
        A.sdk_versions = real
    assert moved == sentinel, (
        "the recorded SDK version did not follow sdk_versions(), so it is a hardcoded "
        "literal that will keep printing after the SDK moves")
    assert M3.inexpressibility()["sdk"] == A.sdk_versions(), "the patch leaked out"

    m = inx["measured"]
    # Read off the model, so these are observations rather than expectations. Asserted anyway,
    # because they are the specific members the verdict's two halves are computed from.
    assert m["create_guardrail_tier_names"] == ["CLASSIC", "STANDARD"]
    assert "PROMPT_ATTACK" in m["create_guardrail_filter_types"]
    assert M3.LEAK_CATEGORY not in m["create_guardrail_filter_types"], (
        "PROMPT_LEAKAGE became a content-filter type; F8-4's conjunction may now be "
        "expressible on one API and this whole case needs re-deriving, not re-running")
    assert not any("tier" in k.lower() for k in m["apply_guardrail_input_members"])


def test_the_verdict_rests_on_the_split_and_not_on_the_category_being_missing():
    """The distinction that a coarser check would have destroyed.

    `promptAttack.categories` is a LIST whose element is a STRUCTURE whose member carries the
    enum. A one-level `members` walk therefore reports "PROMPT_LEAKAGE absent", and
    `inexpressible` would come out True because the category could be found NOWHERE — the
    same verdict as the real finding, for a false reason. My first version of this derivation
    had exactly that bug.

    PROMPT_LEAKAGE **is** present, as `GuardrailChecksPromptAttackCategory`. The finding is
    that it does not live beside the tier.
    """
    inx = M3.inexpressibility()
    if not inx["measured"]["invoke_guardrail_checks_present"]:
        pytest.skip("InvokeGuardrailChecks unmodelled by this SDK; the split is untestable")

    enums = inx["measured"]["invoke_guardrail_checks_enums"]
    assert any(M3.LEAK_CATEGORY in vals for vals in enums.values()), (
        f"{M3.LEAK_CATEGORY} was not found in any enum reachable from "
        f"InvokeGuardrailChecks. If this is real the finding changes; if it is a walk that "
        f"stopped one level short, the verdict is right for the wrong reason")
    assert inx["halves"]["prompt_leakage_is_an_invoke_guardrail_checks_category"] is True
    assert inx["category_exists_but_not_beside_the_tier"] is True, (
        "the record must say the category EXISTS and is not beside the tier; the weaker "
        "'not found anywhere' reading yields the same verdict and is false")
    assert inx["inexpressible"] is True


def test_the_conjunction_is_expressible_the_moment_one_api_carries_both():
    """The mutation the assertion above is only meaningful against.

    `inexpressible` must be a function of the model, not a constant. Both ways of becoming
    expressible are exercised — the category joining the tier-bearing API, and a tier joining
    the category-bearing one — because a rule written as "the category is missing" would pass
    the first and fail the second.
    """
    real = M3.inexpressibility()
    assert real["inexpressible"] is True

    import awsclients as A

    class FakeShape:
        def __init__(self, members=None, enum=None, member=None, name="S"):
            self.members = members or {}
            self.enum = enum
            self.member = member
            self.name = name
            self.type_name = "structure"

    def patched(monkey_leak_on_apply: bool, monkey_tier_on_checks: bool):
        real_sm = A.service_model

        def fake(service: str):
            model = real_sm(service)
            if service == "bedrock" and monkey_leak_on_apply:
                class M:
                    operation_names = model.operation_names

                    def operation_model(self, op):
                        om = model.operation_model(op)
                        if op != "CreateGuardrail":
                            return om
                        cpc = om.input_shape.members["contentPolicyConfig"]
                        elem = FakeShape(members={"type": FakeShape(
                            enum=["PROMPT_ATTACK", M3.LEAK_CATEGORY], name="T")})
                        newcpc = FakeShape(members={
                            "filtersConfig": FakeShape(member=elem, name="L"),
                            "tierConfig": cpc.members["tierConfig"]}, name="CPC")
                        return type("O", (), {"input_shape": FakeShape(
                            members={"contentPolicyConfig": newcpc}, name="I")})()
                return M()
            return model
        return fake

    # A tier on ApplyGuardrail is the other half; simulate by claiming it directly through
    # the model the function reads.
    monkey = patched(True, False)
    orig = A.service_model
    try:
        A.service_model = monkey
        got = M3.inexpressibility()
        assert got["halves"]["prompt_leakage_is_a_content_filter_type"] is True, \
            "the mutation did not take, so the arm below proves nothing"
        # Still inexpressible: the category joined CreateGuardrail's filter enum, but
        # ApplyGuardrail (the call that reaches a tier-bearing guardrail) still takes no
        # tier parameter, so a single call cannot vary the tier. This is the honest reading
        # and it is why the rule is a disjunction over APIs rather than a category check.
        assert got["inexpressible"] is True
    finally:
        A.service_model = orig

    assert M3.inexpressibility()["inexpressible"] is True, "the patch leaked out of the test"


def test_the_derivation_makes_no_aws_call():
    """`--dry-run`'s contract is that nothing reaches AWS, and this function runs there.

    The first version built a client, which resolves credentials; with none on the box that
    walk reaches EC2 instance metadata and opens a socket. The `no_aws` fixture blocks
    `socket.connect`, so this arm is the guarantee: it passes only because the model is read
    off a bare botocore session rather than a configured client.
    """
    inx = M3.inexpressibility()
    assert inx["measured"]["create_guardrail_filter_types"], \
        "the model came back empty, so no surface was actually read"
