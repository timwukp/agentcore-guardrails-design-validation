"""Mutation coverage for `check_caveats.py`, one arm per rule it claims to enforce.

WHY EVERY RULE NEEDS AN ARM

The gate exits 0 against the real `caveats.yaml`. On its own that observation is worth nothing: a gate
whose every rule is unreachable exits 0 too, and from outside the two are indistinguishable
(`feedback_vacuous_test_check`). So each rule gets a mutant that ought to trip it, and every arm asserts
the exit code AND a fragment of the message — a rule that fires for the wrong reason will wave the wrong
file through later, and rc alone cannot tell those apart.

The control arm comes first and is not a formality. When this gate was first run against the real file it
returned 12 findings, all on the bound-language rule, and reading them changed the rule: 7 were genuine
hedges in the authored prose and 5 were the rule demanding a numeric ceiling from cases that had no n to
put in one. Without a control run whose output gets read, the temptation is to widen the pattern until
the file passes, which produces a green gate that checks nothing.

WHY THE MUTANTS ARE BUILT FROM THE REAL FILE

Each arm loads the real `caveats.yaml`, changes one thing in the loaded structure, dumps it to a
temporary path and points the gate at it. A hand-built fixture drifts from the document it stands for,
and then these arms certify a file nobody publishes.

WHY NO CASE ID IS TYPED INTO THIS FILE

Which cases are silent is derived by `build_site_data.caveat_census` from the verdict files, and which
verdict/kind pairs need a bound is derived from the oracles. An arm with `F4-3` in it would go vacuous
the day that case's record acquired its own sentence, and would meanwhile be testing a claim the census
no longer makes (`feedback_scope_as_namelist`). Every victim below is CHOSEN from the live census.

WHY THE ARMS ASSERT rc == 2 AND NEVER rc == 1

Both paths out of the gate — a finding and an unusable input — exit 2. 1 is what a Python traceback exits
with, so an arm accepting 1 would be accepting a crash as a detection.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import build_site_data as B  # noqa: E402
import check_caveats as cx  # noqa: E402

yaml = pytest.importorskip("yaml", reason="the gate itself refuses to run without PyYAML")


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def real() -> dict:
    return cx.load_yaml()


@pytest.fixture(scope="module")
def published() -> dict:
    return cx.load_published()


@pytest.fixture(scope="module")
def census(published) -> dict:
    return B.caveat_census(published)


def run(tmp_path: Path, data: dict) -> tuple[int, str]:
    """Dump `data` and run the gate over it, returning (rc, everything it printed)."""
    p = tmp_path / "caveats.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8")
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cx.main(["--caveats", str(p)])
    return rc, buf.getvalue()


def mutate(real: dict, cid: str, **changes) -> dict:
    """The real file with one entry's fields changed. Deep enough to not disturb the module fixture."""
    out = {k: v for k, v in real.items() if k != "caveats"}
    entries = {k: dict(v) for k, v in real["caveats"].items()}
    entries[cid] = {**entries.get(cid, {}), **changes}
    out["caveats"] = entries
    return out


def a_silent_case(census: dict) -> str:
    """A case the census says is silent — i.e. one this file is expected to author for.

    Fails with a reason rather than an IndexError: an empty silent set is the exact state in which every
    membership arm below goes vacuous, and a bare `list index out of range` sends the next reader looking
    for a bug in the test instead of at the census that stopped reporting anything.
    """
    silent = sorted(set(census["TRUE"]["silent"]) | set(census["FALSE"]["silent"]))
    if not silent:
        pytest.fail("the census reports no silent case, so there is nothing this file is owed for and "
                    "every membership arm is vacuous")
    return silent[0]


def a_case_carrying_its_own(census: dict) -> str:
    """A case whose record already states its own limits — the one kind this file may NOT author for."""
    have = sorted(census["TRUE"]["have"] + census["FALSE"]["have"])
    assert have, "no case carries its own caveat; the shadowing arm would be vacuous"
    return have[0]


def an_absence_shaped_case(census: dict, published: dict) -> str:
    """A silent case whose verdict rests on a non-observation, so its caveat must state a bound."""
    for cid in sorted(set(census["TRUE"]["silent"]) | set(census["FALSE"]["silent"])):
        pair = (published[cid]["verdict"], cx.kind_of(published, cid))
        if cx.ABSENCE_SHAPED.get(pair, (False, ""))[0]:
            return cid
    pytest.fail("no silent case is absence-shaped; the bound-language arm would be vacuous")


# --------------------------------------------------------------------------- the control


def test_the_real_file_passes(tmp_path, real):
    """The no-mutant control. Every arm below is only meaningful against a clean baseline: if the real
    file already failed, an arm's rc 2 would prove nothing about the mutant it injected."""
    rc, out = run(tmp_path, real)
    assert rc == 0, f"the real caveats.yaml does not pass its own gate:\n{out}"


def test_the_gate_reads_the_real_verdict_files(published):
    """A gate that read nothing would pass everything. `load_published` has its own floor, so this arm
    guards the weaker thing the floor cannot: that the SHAPE it builds is the one the census consumes,
    and that the census therefore finds a non-empty silent set to check against."""
    census = B.caveat_census(published)
    silent = set(census["TRUE"]["silent"]) | set(census["FALSE"]["silent"])
    assert len(published) >= cx.MIN_PHASE1_FILES
    assert silent, ("the census reports no silent case, so every membership arm below is vacuous. If "
                    "this is real the file should be deleted, not gated.")


# --------------------------------------------------------------------------- membership, both directions


def test_authoring_for_a_case_that_carries_its_own_caveat_is_refused(tmp_path, real, census, published):
    """The ceiling, and the more dangerous direction. Putting a platform paraphrase in the slot where the
    record has its own sentence is the one substitution this platform may never make."""
    victim = a_case_carrying_its_own(census)
    data = mutate(real, victim, verdict=published[victim]["verdict"], derived_from=["oracle_text"],
                  why="a bound that names the ceiling and is long enough to clear the length floor, "
                      "stated so this arm fails on membership rather than on prose. " * 2)
    rc, out = run(tmp_path, data)
    assert rc == 2
    assert "NOT in the published silent set" in out
    assert victim in out


def test_a_missing_caveat_is_refused(tmp_path, real, census):
    """The floor. A silent case with no authored bound leaves its page saying only that the record states
    no limits — which is true, and is exactly the gap this file exists to close."""
    victim = a_silent_case(census)
    entries = {k: v for k, v in real["caveats"].items() if k != victim}
    rc, out = run(tmp_path, {**{k: v for k, v in real.items() if k != "caveats"},
                             "caveats": entries})
    assert rc == 2
    assert "no caveat is" in out
    assert victim in out


def test_an_emptied_file_is_refused(tmp_path, real):
    """A file that shrank to nothing must fail rather than pass over an empty set
    (`feedback_zero_file_scan_is_error`). Both the floor and 49 membership findings should fire."""
    rc, out = run(tmp_path, {**{k: v for k, v in real.items() if k != "caveats"}, "caveats": {}})
    assert rc == 2
    assert "no `caveats` mapping" in out


def test_a_file_below_the_floor_is_refused(tmp_path, real, census):
    """The floor fires on its own, not only via an empty mapping: a file holding a handful of entries is
    parseable, non-empty, and still a collapse."""
    keep = sorted(real["caveats"])[: cx.MIN_AUTHORED - 1]
    data = {**{k: v for k, v in real.items() if k != "caveats"},
            "caveats": {k: real["caveats"][k] for k in keep}}
    rc, out = run(tmp_path, data)
    assert rc == 2
    # The count is asserted alongside the phrase because the per-entry `why` floor uses the same wording
    # with a different number; without it this arm could pass on the wrong rule.
    assert f"authors {len(keep)} caveat(s), below the floor of {cx.MIN_AUTHORED}" in out


def test_a_caveat_for_an_unknown_case_is_refused(tmp_path, real):
    """An entry naming a case that does not exist. Without this the file could accumulate caveats for
    cases that were renamed away, and every one of them would render nowhere while counting as authored."""
    data = mutate(real, "F99-9", verdict="TRUE", derived_from=["oracle_text"],
                  why="a bound long enough to clear the length floor, so this arm fails on the case id "
                      "rather than on the prose. " * 3)
    rc, out = run(tmp_path, data)
    assert rc == 2
    assert "not a published case" in out


# --------------------------------------------------------------------------- the verdict must still match


def test_a_caveat_authored_under_the_wrong_verdict_is_refused(tmp_path, real, census):
    """A caveat that outlives a verdict change is worse than no caveat, because the page reads it as
    current. The `verdict` field is the tripwire and this proves it is load-bearing."""
    victim = a_silent_case(census)
    published_verdict = "TRUE" if victim in census["TRUE"]["silent"] else "FALSE"
    data = mutate(real, victim, verdict="FALSE" if published_verdict == "TRUE" else "TRUE")
    rc, out = run(tmp_path, data)
    assert rc == 2
    assert "published verdict is" in out
    assert victim in out


# --------------------------------------------------------------------------- provenance


def test_the_provenance_field_list_is_not_empty():
    """Same defanging risk as the ban list: the arm below is parametrised over the gate's own tuple, so
    emptying that tuple would delete four arms instead of failing them."""
    assert set(cx.PROVENANCE_FIELDS) >= {"authored_by", "review_status"}, (
        f"the provenance list has shrunk to {cx.PROVENANCE_FIELDS}; a page that cannot say who wrote "
        f"these sentences, or whether a human has read them, is the failure this list exists to prevent")


@pytest.mark.parametrize("field", list(cx.PROVENANCE_FIELDS))
def test_missing_file_level_provenance_is_refused(tmp_path, real, field):
    """These sentences are not the study's words. A page that cannot say whose they are is a page
    presenting a later reader's reasoning at the strength of a measured artifact."""
    data = {k: v for k, v in real.items() if k != field}
    rc, out = run(tmp_path, data)
    assert rc == 2
    assert f"no `{field}`" in out


def test_an_unknown_key_is_refused(tmp_path, real, census):
    """A misspelt key is the quiet failure: `wyh` leaves `why` empty, and an empty caveat renders as a
    box with a heading and no bound. Allowlisting the keys makes the typo fatal instead."""
    victim = a_silent_case(census)
    data = mutate(real, victim, wyh="a typo for why")
    rc, out = run(tmp_path, data)
    assert rc == 2
    assert "unknown key(s)" in out


def test_derived_from_naming_a_field_the_record_lacks_is_refused(tmp_path, real, census):
    """A caveat citing evidence that does not exist is worse than silence: it tells the reader a bound was
    read off the record when nothing was."""
    victim = a_silent_case(census)
    data = mutate(real, victim, derived_from=["a_field_no_verdict_file_carries"])
    rc, out = run(tmp_path, data)
    assert rc == 2
    assert "does not\ncarry" in out or "does not carry" in out.replace("\n", " ")


def test_an_empty_derived_from_is_refused(tmp_path, real, census):
    """A bound with no named evidence is an opinion."""
    victim = a_silent_case(census)
    data = mutate(real, victim, derived_from=[])
    rc, out = run(tmp_path, data)
    assert rc == 2
    assert "non-empty list" in out


# --------------------------------------------------------------------------- what the prose may say


def test_a_one_line_placeholder_is_refused(tmp_path, real, census):
    """A caveat this short is a placeholder, and it renders in the same box, with the same weight, as a
    bound somebody thought about."""
    victim = a_silent_case(census)
    short = "too short to be a bound"
    data = mutate(real, victim, why=short)
    rc, out = run(tmp_path, data)
    assert rc == 2
    # Same reason as the file-level floor arm: the case id and the measured length pin this to the
    # per-entry rule rather than to any other message carrying the words "below the floor of".
    assert f"{victim}: `why` is {len(short)} characters, below the floor of {cx.MIN_WHY_CHARS}" in out


def test_the_ban_list_is_not_empty():
    """The arm below is parametrised over the gate's own tuple, which is what makes every listed phrase
    exercised — and also means deleting the list would make those arms VANISH rather than fail, shrinking
    the suite silently from 38 to 24. A floor turns that deletion into a red test."""
    assert len(cx.BANNED_PHRASES) >= 10, (
        f"only {len(cx.BANNED_PHRASES)} banned phrase(s); the parametrised arm below has been quietly "
        f"defanged rather than failed")


@pytest.mark.parametrize("phrase", list(cx.BANNED_PHRASES))
def test_every_banned_phrase_is_refused(tmp_path, real, census, phrase):
    """Greenland et al. 2016 item #20 — a value outside an interval has not been refuted or excluded by
    the data — and items #4/#6 — a nonsignificant result does not demonstrate absence. Parametrised over
    the real tuple so a phrase added to the ban without a working match cannot sit there unexercised."""
    victim = a_silent_case(census)
    data = mutate(real, victim, why=real["caveats"][victim]["why"] + f" This {phrase} in every arm.")
    rc, out = run(tmp_path, data)
    assert rc == 2, f"the ban on {phrase!r} never fired"
    assert repr(phrase) in out


def test_an_absence_shaped_verdict_with_no_bound_is_refused(tmp_path, real, census, published):
    """The rule that is not a length check and not a word ban. The mutant is LONG — well clear of
    MIN_WHY_CHARS — and says something true but unbounded, which is precisely the failure a length floor
    cannot see: it names a gap without saying what fills it, and a reader takes that as modesty."""
    victim = an_absence_shaped_case(census, published)
    data = mutate(real, victim,
                  why="that the behaviour generalises beyond this testbed. The study measured one "
                      "configuration and a reader's environment may differ in ways this case never "
                      "explored, so some caution is warranted when reading it. " * 2)
    rc, out = run(tmp_path, data)
    assert rc == 2
    assert "rests on a non-observation" in out
    assert victim in out


def test_a_bound_stated_as_a_ceiling_satisfies_the_rule(tmp_path, real, census, published):
    """The other half of the previous arm. A rule that refused every rewrite would be indistinguishable
    from one that only accepted the exact bytes already in the file, so this proves the CEILING form is
    genuinely accepted rather than the real prose merely being grandfathered in."""
    victim = an_absence_shaped_case(census, published)
    data = mutate(real, victim,
                  why="that the rate is zero. Zero events over the pre-registered n bounds the rate "
                      "from above rather than fixing it at 0, and any rate below that ceiling is "
                      "fully compatible with what was observed here.")
    rc, out = run(tmp_path, data)
    assert rc == 0, f"the ceiling form was refused:\n{out}"


def test_a_bound_stated_as_an_equivalence_satisfies_the_rule(tmp_path, real, census, published):
    """And the second accepted form. Coverage-limited cases have no n to put in a ceiling; naming the
    rival world that produces the same observation is the honest bound there, and demanding arithmetic
    instead would push an author to invent an n the record does not have."""
    victim = an_absence_shaped_case(census, published)
    data = mutate(real, victim,
                  why="that the thing does not exist. The probes that ran cover this study's own "
                      "request shapes, and a mechanism firing only under conditions never created here "
                      "would produce exactly this observation.")
    rc, out = run(tmp_path, data)
    assert rc == 0, f"the equivalence form was refused:\n{out}"


def test_a_hedge_is_not_a_bound(tmp_path, real, census, published):
    """The distinction the two arms above rest on. "Is unmeasured" names a gap and bounds nothing, and if
    the patterns ever widened far enough to accept it, both accepting arms would still pass while the
    rule had stopped meaning anything."""
    victim = an_absence_shaped_case(census, published)
    data = mutate(real, victim,
                  why="that this generalises. What happens outside the tested configuration is "
                      "unmeasured, and nothing here shows how another environment would behave; this "
                      "is a limitation of the study that readers should keep in mind throughout.")
    rc, out = run(tmp_path, data)
    assert rc == 2, "a pure hedge passed the bound rule"
    assert "rests on a non-observation" in out


# --------------------------------------------------------------------------- the classification table


def test_every_verdict_kind_pair_in_the_silent_set_is_classified(census, published):
    """The table is a claim about scope, and an unlisted pair is not a safe pair. This asserts it
    positively rather than waiting for the gate to report it, so a new oracle kind arriving in the
    corpus names itself here instead of quietly skipping the bound rule."""
    unclassified = sorted(
        {(published[c]["verdict"], cx.kind_of(published, c))
         for c in set(census["TRUE"]["silent"]) | set(census["FALSE"]["silent"])}
        - set(cx.ABSENCE_SHAPED))
    assert not unclassified, (
        f"unclassified verdict/kind pairs in the silent set: {unclassified}. Decide for each whether "
        f"the verdict rests on a non-observation and add it to ABSENCE_SHAPED with its reason.")


def test_the_table_classifies_both_directions_of_the_kinds_it_names():
    """A sanity arm on the table's own shape: every kind it mentions should be reachable in the direction
    it was reasoned about, and the reason strings must not be blank — a table row with an empty reason is
    a classification nobody can audit."""
    assert cx.ABSENCE_SHAPED, "the table is empty; the bound rule cannot fire"
    for pair, (flag, reason) in cx.ABSENCE_SHAPED.items():
        assert pair[0] in ("TRUE", "FALSE"), pair
        assert isinstance(flag, bool)
        assert reason.strip(), f"{pair} carries no reason"


def test_at_least_one_pair_is_classified_each_way():
    """If every pair were absence-shaped the rule would be a blanket requirement, and if none were it
    would never fire. Either state would make the table decorative."""
    flags = {flag for flag, _ in cx.ABSENCE_SHAPED.values()}
    assert flags == {True, False}, f"the table classifies everything one way: {flags}"


# --------------------------------------------------------------------------- the count boundary


def test_each_published_caveat_count_is_derived_from_its_own_producer():
    """The defect that started this whole area: three definitions of "caveat coverage" sharing one name,
    so a number computed under one definition got published under another. `feedback_two_numbers_two_claims`
    — each is derived here from its own producer, and never one from another.

      record-carried  `cases_with_what_*_does_not_prove`  <- caveat_census, over the verdict files
      authored        `cases_with_an_authored_caveat`     <- the length of caveats.yaml
      off-direction   `caveats_for_a_direction_...`       <- off_direction_caveats, a different rule

    Adding the authored count into either record-carried count is the specific substitution the review's
    withdrawn R2 was built on, and it would still pass a test that only checked "the numbers are
    plausible". So each is recomputed and compared, not sanity-checked."""
    import json

    payload = REPO.parent / "grx-site-payload" / "method.json"
    if not payload.is_file():
        pytest.skip("no build present; the invariant harness asserts this against a real publish")
    c = json.loads(payload.read_text(encoding="utf-8"))["caveats"]
    published = cx.load_published()
    census = B.caveat_census(published)
    authored_file = yaml.safe_load(cx.CURATION.read_text(encoding="utf-8"))["caveats"]

    assert c["cases_with_what_true_does_not_prove"] == len(census["TRUE"]["have"])
    assert c["cases_with_what_false_does_not_prove"] == len(census["FALSE"]["have"])
    assert c["cases_with_an_authored_caveat"] == len(authored_file)
    assert len(c["caveats_for_a_direction_the_verdict_did_not_reach"]) == \
        len(B.off_direction_caveats(published))

    # The three are separate quantities, so no arithmetic relation between them may be assumed. What CAN
    # be asserted is that no record-carried count absorbed the authored one: each stays equal to its own
    # census figure above regardless of how many caveats this file holds.
    assert set(authored_file) <= set(census["TRUE"]["silent"]) | set(census["FALSE"]["silent"]), (
        "an authored caveat sits on a case whose record carries its own; the two counts would then be "
        "counting overlapping things under names that promise they do not")

    # The remainder is a set difference, not a subtraction of counts. It is empty today because all 49
    # were authored; it goes non-empty the moment an entry is dropped or a new silent case appears, which
    # is the only reason to publish it.
    assert c["cases_still_silent_after_authoring"] == sorted(
        (set(census["TRUE"]["silent"]) | set(census["FALSE"]["silent"])) - set(authored_file))
