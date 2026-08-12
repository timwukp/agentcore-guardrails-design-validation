"""Mutation tests for the F5-7a sealed-oracle verdict emitter. Offline, $0.

What these guard
----------------
`07a_verdict.py` is one map: eleven per-claim tokens from `07a_privatelink_enum.py` into
one boolean the sealed EXISTENCE oracle can read. Everything that can go wrong with it goes
wrong quietly.

  * **Too permissive.** A token the table does not know, folded into "no mismatch" by
    default, publishes TRUE from a refutation. `test_an_unclassified_token_is_fatal` and
    `test_the_table_covers_every_token_the_producer_can_emit` are the two halves of that:
    one checks the runtime refusal, the other checks the table has not drifted behind the
    producer that feeds it. The token set is **derived from the producer's own code
    objects**, not typed here — a list typed in a test is a second copy of the thing under
    test (`feedback_derive_from_every_producer`).
  * **Vacuous.** A conjunction over zero bearing claims is TRUE by emptiness, and a
    findings table of nothing but instrument caveats would produce exactly that.
  * **Not load-bearing.** If the verdict were FALSE for some reason other than the two
    refuted rows, flipping those rows would leave it FALSE.
    `test_the_verdict_inverts_when_both_refutations_are_removed` is the arm that proves the
    mismatches are doing the work — without it, every other arm here is compatible with a
    function that returns FALSE unconditionally.
  * **Self-vouching.** `n` is a count of evidence records on disk. Reading it out of the
    analysis body would let the file being analysed state how much evidence backs it.

Fixtures are the project's **real** archived runs copied into `tmp_path`
(`feedback_verify_against_real_artifact`): a hand-built findings dict would only confirm my
own idea of the schema, and the schema is exactly what this reader depends on.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "f5_redteam" / "07a_verdict.py"
PRODUCER = ROOT / "f5_redteam" / "07a_privatelink_enum.py"


# The sys.modules names these by-path loads register. Module-level constants rather than
# parameters, because `lib/tests/test_module_name_collisions.py` reads every
# `spec_from_file_location(<name>, …)` in the tree statically and asserts that no such name
# shadows a real module in `lib/` — a name it cannot resolve is a blind spot in that gate,
# so a name threaded through a helper argument would have to be declared UNRESOLVABLE
# instead of checked.
VERDICT_MODULE = "f5_07a_verdict_under_test"
PRODUCER_MODULE = "f5_07a_privatelink_enum_for_token_extraction"


def _exec(spec):
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v57a = _exec(importlib.util.spec_from_file_location(VERDICT_MODULE, SCRIPT))


# ---------------------------------------------------------------------------
# fixtures — the real runs, copied so a mutation cannot touch the archive
# ---------------------------------------------------------------------------

@pytest.fixture
def tree(tmp_path) -> Path:
    """A copy of both archived F5-7a runs under a fresh root.

    Copied, never mutated in place: `evidence/` is the immutable archive whose request ids
    are the reason a claim can be checked at all, and a test that edited it would destroy
    the artifact it depends on.
    """
    for run in v57a.DEFAULT_RUNS:
        src = v57a.analysis_path(run).parent
        if not (src / "analysis.json").is_file():
            pytest.skip(f"archived run {run} is not present")
        dst = tmp_path / "evidence" / run / v57a.FAMILY / v57a.CASE
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
    return tmp_path


def _findings(tree: Path, run: str) -> dict:
    return json.loads(v57a.analysis_path(run, tree).read_text(encoding="utf-8"))


def _write(tree: Path, run: str, body: dict) -> None:
    v57a.analysis_path(run, tree).write_text(json.dumps(body, indent=2), encoding="utf-8")


def _set_token(tree: Path, run: str, claim: str, token: str) -> None:
    body = _findings(tree, run)
    body["analysis"]["findings"][claim]["verdict"] = token
    _write(tree, run, body)


# ---------------------------------------------------------------------------
# the control arm: the real archive, unmutated
# ---------------------------------------------------------------------------

def test_the_real_archive_yields_FALSE_from_two_named_mismatches(tree):
    """The control. Named mismatches, not just a boolean, so a later arm can invert them."""
    b = v57a.build(v57a.DEFAULT_RUNS, tree)
    d = b["decision"]
    assert d["observed_matrix_matches"] is False
    assert d["mismatched_claims"] == ["evaluations_data_plane_not_supported",
                                      "optimization_no_privatelink"]
    # The oracle names the Optimization gap explicitly, so that row failing is the reason
    # the sealed sentence is answerable at all rather than a detail.
    assert "optimization_no_privatelink" in d["mismatched_claims"]
    assert d["readings_agree"] is True, (
        "the primary and strict readings disagree, which is publishable but must not pass "
        "silently: the record's verdict would then depend on which reading a reader "
        f"prefers. {d}")


def test_the_published_record_reconciles_with_a_fresh_derivation():
    """The file in results/phase1/ must equal what the archive derives right now.

    A snapshot assertion on the file's contents would red on progress; this compares the
    published verdict to a re-derivation, so it fails only when the two disagree — which is
    the case where the published record is stale or hand-edited.
    """
    out = ROOT / "results" / "phase1" / f"{v57a.CASE}.json"
    if not out.is_file():
        pytest.skip("F5-7a has not been emitted yet")
    published = json.loads(out.read_text(encoding="utf-8"))
    try:
        b = v57a.build(v57a.DEFAULT_RUNS)
    except v57a.Refusal as exc:
        pytest.skip(f"the archive cannot be re-derived here: {exc}")
    want = "FALSE" if not b["decision"]["observed_matrix_matches"] else "TRUE"
    assert published["verdict"] == want, (
        f"results/phase1/{v57a.CASE}.json says {published['verdict']} and the archive "
        f"derives {want}; re-run f5_redteam/07a_verdict.py")
    assert published["record"]["n_usable"] == b["n"], (
        "the published n does not match the record count on disk")


# ---------------------------------------------------------------------------
# too permissive
# ---------------------------------------------------------------------------

def test_the_table_covers_every_token_the_producer_can_emit():
    """Derived from the producer's code objects, not from a list typed here.

    The tokens are string constants inside `classify` and the two verdict helpers, so they
    are read out of `co_consts` — exact, unlike a regex over source text, and it walks
    nested code objects because the comprehensions in `classify` carry their own.

    This is the arm that fails when someone adds a refutation branch to the producer and
    does not classify it. Without it, the new token would reach `CLASSIFICATION`, be absent,
    and — depending on the runtime guard alone — turn a real refutation into an rc=2 nobody
    reads instead of a verdict.
    """
    producer = _exec(importlib.util.spec_from_file_location(PRODUCER_MODULE, PRODUCER))

    def string_consts(fn) -> set[str]:
        out: set[str] = set()
        stack = [fn.__code__]
        while stack:
            code = stack.pop()
            for k in code.co_consts:
                if isinstance(k, str):
                    out.add(k)
                elif hasattr(k, "co_consts"):
                    stack.append(k)
        return out

    emitted = set()
    for fn in (producer.classify, producer._evaluations_verdict,
               producer._optimization_verdict):
        emitted |= {s for s in string_consts(fn)
                    if re.fullmatch(r"[A-Z][A-Z0-9_]{4,}", s)}

    assert emitted, ("no verdict-shaped constant was found in the producer, so this arm "
                     "measured nothing — the extraction broke, not the table")
    missing = sorted(emitted - set(v57a.CLASSIFICATION))
    assert not missing, (
        f"{missing} can be emitted by 07a_privatelink_enum.py and 07a_verdict.py does not "
        f"classify them. Classify each deliberately, with the reason it reads that way")


def test_an_unclassified_token_is_fatal(tree):
    for run in v57a.DEFAULT_RUNS:
        _set_token(tree, run, "optimization_no_privatelink", "DOC_TOTALLY_FINE_HONESTLY")
    with pytest.raises(v57a.Refusal, match="does not classify"):
        v57a.build(v57a.DEFAULT_RUNS, tree)


def test_silence_is_not_agreement(tree):
    """`NOT_TESTED_BY_THIS_INSTRUMENT` must not be able to carry a claim to TRUE.

    Both refuted rows come from instrument B. Turning both into "the instrument said
    nothing" is what an over-permissive table would score as no-mismatch-so-TRUE, and the
    verdict must instead rest on the claims that were actually settled.
    """
    for run in v57a.DEFAULT_RUNS:
        for claim in ("evaluations_data_plane_not_supported", "optimization_no_privatelink"):
            _set_token(tree, run, claim, "NOT_TESTED_BY_THIS_INSTRUMENT")
    d = v57a.build(v57a.DEFAULT_RUNS, tree)["decision"]
    assert d["mismatched_claims"] == []
    # TRUE now, and that is correct for this mutated input — the point of the arm is that
    # the two silent rows are NOT counted among the claims the conjunction ranges over.
    assert d["observed_matrix_matches"] is True
    assert "evaluations_data_plane_not_supported" in \
        d["claims_about_our_instrument_or_prose"]
    assert d["claims_bearing_on_the_oracle"] == 2, (
        "the two instrument-A confirmations should be the only bearing claims left")


# ---------------------------------------------------------------------------
# load-bearing: the arm that makes every other arm mean something
# ---------------------------------------------------------------------------

def test_the_verdict_inverts_when_both_refutations_are_removed(tree):
    """Flip the two refuted rows to the branch AWS not shipping would have produced.

    Without this arm the whole file is compatible with `observed = False` hard-coded.
    """
    for run in v57a.DEFAULT_RUNS:
        for claim in ("evaluations_data_plane_not_supported", "optimization_no_privatelink"):
            _set_token(tree, run, claim, "DOC_CONFIRMED")
    d = v57a.build(v57a.DEFAULT_RUNS, tree)["decision"]
    assert d["observed_matrix_matches"] is True
    assert d["mismatched_claims"] == []
    assert d["claims_bearing_on_the_oracle"] == 4


def test_either_refutation_alone_is_enough(tree):
    """"FALSE on any mismatch" — so one row is sufficient, and each is tested separately."""
    for keep in ("evaluations_data_plane_not_supported", "optimization_no_privatelink"):
        for run in v57a.DEFAULT_RUNS:
            body = _findings(tree, run)
            for claim in ("evaluations_data_plane_not_supported",
                          "optimization_no_privatelink"):
                if claim != keep:
                    body["analysis"]["findings"][claim]["verdict"] = "DOC_CONFIRMED"
            _write(tree, run, body)
        d = v57a.build(v57a.DEFAULT_RUNS, tree)["decision"]
        assert d["observed_matrix_matches"] is False, f"{keep} alone should decide it"
        assert d["mismatched_claims"] == [keep]
        # restore for the next iteration
        for run in v57a.DEFAULT_RUNS:
            src = v57a.analysis_path(run).read_text(encoding="utf-8")
            v57a.analysis_path(run, tree).write_text(src, encoding="utf-8")


def test_the_strict_reading_is_reported_and_does_not_change_this_verdict(tree):
    """DOC_IMPRECISE is not counted as a mismatch, and the record says what that costs.

    Both readings are FALSE here, so the choice is inert — but it is inert as a *measured*
    fact, not as an assumption, and if a future run made the readings diverge the control
    arm above goes red.
    """
    for run in v57a.DEFAULT_RUNS:
        for claim in ("evaluations_data_plane_not_supported", "optimization_no_privatelink"):
            _set_token(tree, run, claim, "DOC_CONFIRMED")
    d = v57a.build(v57a.DEFAULT_RUNS, tree)["decision"]
    assert d["observed_matrix_matches"] is True
    assert d["observed_matrix_matches_strict"] is False, (
        "with the two refutations gone, the strict reading should still fail on the "
        "document's imprecision — otherwise DOC_IMPRECISE is classified as nothing at all")
    assert d["strict_reading_adds"] == ["matrix_rows_are_primitives_not_endpoint_services"]
    assert d["readings_agree"] is False


# ---------------------------------------------------------------------------
# vacuity
# ---------------------------------------------------------------------------

def test_a_findings_table_with_no_bearing_claim_is_refused(tree):
    for run in v57a.DEFAULT_RUNS:
        body = _findings(tree, run)
        body["analysis"]["findings"] = {
            k: {**row, "verdict": "CONFIRMED_AS_LIMITATION"}
            for k, row in body["analysis"]["findings"].items()}
        _write(tree, run, body)
    with pytest.raises(v57a.Refusal, match="vacuity"):
        v57a.build(v57a.DEFAULT_RUNS, tree)


def test_an_empty_findings_table_is_refused(tree):
    for run in v57a.DEFAULT_RUNS:
        body = _findings(tree, run)
        body["analysis"]["findings"] = {}
        _write(tree, run, body)
    with pytest.raises(v57a.Refusal, match="records no"):
        v57a.build(v57a.DEFAULT_RUNS, tree)


def test_a_run_with_no_evidence_records_is_refused(tree):
    for run in v57a.DEFAULT_RUNS:
        d = v57a.analysis_path(run, tree).parent
        for f in d.glob("*.json"):
            if f.name not in v57a.NOT_A_RECORD:
                f.unlink()
    with pytest.raises(v57a.Refusal, match="zero per-call evidence records"):
        v57a.build(v57a.DEFAULT_RUNS, tree)


# ---------------------------------------------------------------------------
# replication and provenance
# ---------------------------------------------------------------------------

def test_one_run_is_refused(tree):
    with pytest.raises(v57a.Refusal, match="only 1 run"):
        v57a.build((v57a.DEFAULT_RUNS[0],), tree)


def test_the_two_days_must_agree_on_the_tokens_the_verdict_uses(tree):
    _set_token(tree, v57a.DEFAULT_RUNS[1], "caveat_b_third_gateway_endpoint",
               "NOT_CONFIRMED")
    with pytest.raises(v57a.Refusal, match="disagree on the per-claim verdicts"):
        v57a.build(v57a.DEFAULT_RUNS, tree)


def test_a_missing_run_names_the_command_that_produces_it(tree):
    v57a.analysis_path(v57a.DEFAULT_RUNS[1], tree).unlink()
    with pytest.raises(v57a.Refusal, match="07a_privatelink_enum.py"):
        v57a.build(v57a.DEFAULT_RUNS, tree)


def test_n_is_counted_on_disk_and_not_read_out_of_the_analysis(tree):
    """Delete one record; n must drop by exactly one.

    If `n` came from a field inside `analysis.json`, the file under analysis would be
    stating how much evidence backs it and this arm would show no change.
    """
    before = v57a.build(v57a.DEFAULT_RUNS, tree)["n"]
    d = v57a.analysis_path(v57a.DEFAULT_RUNS[0], tree).parent
    victim = next(f for f in sorted(d.glob("*.json")) if f.name not in v57a.NOT_A_RECORD)
    victim.unlink()
    after = v57a.build(v57a.DEFAULT_RUNS, tree)["n"]
    assert after == before - 1, f"n went {before} -> {after} when one record was removed"


def test_the_bookkeeping_files_are_not_counted_as_records(tree):
    """`analysis.json`, `environment.json` and `summary.json` are not observations.

    Counting them would inflate every run's denominator by up to three, and the inflation
    would look like data rather than like a bug.
    """
    d = v57a.analysis_path(v57a.DEFAULT_RUNS[0], tree).parent
    on_disk = {f.name for f in d.glob("*.json")}
    assert on_disk & v57a.NOT_A_RECORD, (
        "no bookkeeping file is present, so this arm cannot distinguish a reader that "
        "excludes them from one that does not")
    n = v57a.count_records(v57a.DEFAULT_RUNS[0], tree)
    assert n == len(on_disk - v57a.NOT_A_RECORD)
    assert n < len(on_disk)


# ---------------------------------------------------------------------------
# the front end
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing_and_prints_the_oracle(capsys):
    out = ROOT / "results" / "phase1" / f"{v57a.CASE}.json"
    before = out.read_bytes() if out.is_file() else None
    assert v57a.main(["--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "EXISTENCE" in text and "Optimization gap" in text
    assert (out.read_bytes() if out.is_file() else None) == before


def test_main_refuses_a_run_that_does_not_exist(capsys):
    assert v57a.main(["--runs", "r_no_such_run_a", "r_no_such_run_b"]) == 2
    assert "does not exist" in capsys.readouterr().err
