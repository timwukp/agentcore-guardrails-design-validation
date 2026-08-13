"""Mutation tests for the F0-1 verdict emitter. Offline, $0, no HTTP.

`02_references_verdict.py` reads an artifact it did not produce, so every guard in it is a
guard against trusting that artifact too far. The arms here are one per way the trust could
be misplaced:

  * **A truncated artifact published as a full one.** `02_check_references.py --limit`
    writes `n_checked: 3` and records nothing else to distinguish itself from a 24-row run.
    The denominator is therefore derived from `claims/triage.csv`, and
    `test_a_short_artifact_is_refused` / `test_the_denominator_comes_from_triage_not_the_-
    artifact` are the two directions of that: a short artifact must red, and *growing §10*
    must red the artifact that no longer covers it.
  * **Our network reported as the document's defect.** An unreachable URL scores `pass:
    false` in the producer, so `test_an_unreachable_url_is_refused_not_published_as_FALSE`
    requires a refusal instead of a verdict.
  * **The artifact vouching for itself.** `pass`, `n_checked` and `n_failed` are all summary
    fields, and all three are recomputed. Three arms flip one of them against the
    observations beside it and require a refusal.
  * **A weakening read as a strength.** Two `title_match` branches pass on the HTTP 200
    alone. `test_a_row_that_passed_on_http_200_alone_is_counted_separately` requires the
    record to distinguish them, so "24/24" cannot come to mean 24 rows of which some were
    waved through.
  * **Not load-bearing.** `test_one_dead_link_makes_the_verdict_FALSE` and
    `test_one_wrong_page_makes_the_verdict_FALSE` are what make the TRUE mean something:
    without them every arm here is compatible with a function that returns TRUE.

The fixture is the **real** archived artifact copied into `tmp_path`
(`feedback_verify_against_real_artifact`), and the copy is what gets mutated — the original
is the only observation of 2026-08-09 and `test_finding_numbers.py` pins the document's
"24/24" against it.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "claims" / "02_references_verdict.py"
PRODUCER = ROOT / "claims" / "02_check_references.py"


# A module-level constant, not a helper argument: `test_module_name_collisions.py` resolves
# every `spec_from_file_location(<name>, …)` in the tree statically to check that no by-path
# load shadows a module in `lib/`, and a name it cannot read is a blind spot there.
VERDICT_MODULE = "f0_1_references_verdict_under_test"

_spec = importlib.util.spec_from_file_location(VERDICT_MODULE, SCRIPT)
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)


@pytest.fixture
def art(tmp_path) -> Path:
    """The real artifact, copied. Mutations touch the copy only."""
    if not V.ARTIFACT.is_file():
        pytest.skip("the F0-1 artifact is not present")
    dst = tmp_path / "FINDING-F0-1-references.json"
    shutil.copy2(V.ARTIFACT, dst)
    return dst


def _read(art: Path) -> dict:
    return json.loads(art.read_text(encoding="utf-8"))


def _write(art: Path, body: dict) -> None:
    art.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# the control, and the arms that make it mean something
# ---------------------------------------------------------------------------

def test_the_real_artifact_yields_TRUE_with_every_row_on_the_strong_branch(art):
    b = V.build(art)
    assert b["observed_all_resolve_and_describe"] is True
    assert b["failures"] == []
    assert b["unreachable"] == 0
    assert b["n"] == b["expected_rows"] == 24
    assert b["rows_on_the_strong_branch"] == 24, (
        "some row passed on its HTTP 200 alone, which is weaker than a title match and "
        "must not be reported as part of a 24/24 title verification")
    assert b["rows_passed_on_http_200_alone"] == []


def test_one_dead_link_makes_the_verdict_FALSE(art):
    """Without this arm, every other arm is compatible with `return True`."""
    body = _read(art)
    body["results"][7]["http_status"] = 404
    body["results"][7]["pass"] = False
    body["n_failed"] = 1
    _write(art, body)
    b = V.build(art)
    assert b["observed_all_resolve_and_describe"] is False
    assert [f["claim_id"] for f in b["failures"]] == [body["results"][7]["claim_id"]]
    assert b["failures"][0]["http_status"] == 404


def test_one_wrong_page_makes_the_verdict_FALSE(art):
    """A 200 that resolves to an unrelated page — the failure the oracle calls worse than a 404."""
    body = _read(art)
    body["results"][3]["title_match"] = "NO"
    body["results"][3]["title_overlap"] = []
    body["results"][3]["pass"] = False
    body["n_failed"] = 1
    _write(art, body)
    b = V.build(art)
    assert b["observed_all_resolve_and_describe"] is False
    assert b["failures"][0]["http_status"] == 200, (
        "the failing row still served 200, so this arm is exercising the title clause and "
        "not the status clause")
    assert b["failures"][0]["title_match"] == "NO"


def test_a_row_that_passed_on_http_200_alone_is_counted_separately(art):
    body = _read(art)
    body["results"][5]["title_match"] = "unverifiable (page has no title)"
    body["results"][5]["page_title"] = ""
    body["results"][5]["title_overlap"] = []
    _write(art, body)
    b = V.build(art)
    assert b["observed_all_resolve_and_describe"] is True, "the branch is still a pass"
    assert b["rows_on_the_strong_branch"] == 23
    assert [w["claim_id"] for w in b["rows_passed_on_http_200_alone"]] == \
        [body["results"][5]["claim_id"]]


# ---------------------------------------------------------------------------
# the classification table, derived from the producer
# ---------------------------------------------------------------------------

def test_the_table_covers_every_title_match_the_producer_can_write():
    """Parsed out of `main`'s assignments to `match`, not typed here.

    A list typed into a test is a second copy of the thing under test. This walks the
    producer's AST for `match = "..."` and requires each literal to be classified, so a new
    branch in the producer reds this arm instead of reaching the verdict unclassified.
    """
    tree = ast.parse(PRODUCER.read_text(encoding="utf-8"))
    emitted = {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        and any(isinstance(t, ast.Name) and t.id == "match" for t in node.targets)}
    assert emitted, ("no `match = \"...\"` assignment was found in the producer, so this "
                     "arm measured nothing — the AST walk broke, not the table")
    missing = sorted(emitted - set(V.TITLE_MATCH))
    assert not missing, (
        f"{missing} can be written by 02_check_references.py and 02_references_verdict.py "
        f"does not classify them")


def test_which_branches_count_as_a_pass_is_derived_from_the_producer():
    """The producer's own `match in (...)` tuple decides which branches pass.

    Two copies of that decision is one too many: if the producer stops treating a branch as
    a pass and this table still does, the verdict silently disagrees with the instrument
    that produced it. So the tuple is read out of the source and compared.
    """
    tree = ast.parse(PRODUCER.read_text(encoding="utf-8"))
    passing: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Name) and node.left.id == "match"
                and len(node.ops) == 1 and isinstance(node.ops[0], ast.In)
                and isinstance(node.comparators[0], (ast.Tuple, ast.List, ast.Set))):
            passing |= {e.value for e in node.comparators[0].elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    assert passing, "the producer's `match in (...)` pass-list was not found"
    ours = {k for k, v in V.TITLE_MATCH.items() if v[0]}
    assert ours == passing, (
        f"02_references_verdict.py treats {sorted(ours)} as passes and "
        f"02_check_references.py treats {sorted(passing)}; the verdict and the instrument "
        f"disagree about what a pass is")


def test_an_unclassified_title_match_is_fatal(art):
    body = _read(art)
    body["results"][0]["title_match"] = "probably fine"
    _write(art, body)
    with pytest.raises(V.Refusal, match="does not classify"):
        V.build(art)


# ---------------------------------------------------------------------------
# the artifact is not allowed to vouch for itself
# ---------------------------------------------------------------------------

def test_a_row_whose_pass_disagrees_with_its_own_observations_is_refused(art):
    """The mutation a laundering read would miss: a 404 marked as a pass."""
    body = _read(art)
    body["results"][2]["http_status"] = 404
    _write(art, body)                      # pass left True
    with pytest.raises(V.Refusal, match="disagrees with itself"):
        V.build(art)


def test_a_summary_n_failed_that_disagrees_with_the_rows_is_refused(art):
    body = _read(art)
    body["n_failed"] = 3
    _write(art, body)
    with pytest.raises(V.Refusal, match="n_failed"):
        V.build(art)


def test_a_summary_n_checked_that_disagrees_with_the_rows_is_refused(art):
    body = _read(art)
    body["n_checked"] = 99
    _write(art, body)
    with pytest.raises(V.Refusal, match="n_checked"):
        V.build(art)


def test_an_unreachable_url_is_refused_not_published_as_FALSE(art):
    """Our network is not the document's defect.

    The mutation is the shape a real partial outage writes: status None, pass false, counted
    in both `n_failed` and `unreachable`. A reader that only recomputed rows would publish
    FALSE against §10 for a DNS failure.
    """
    body = _read(art)
    body["results"][1]["http_status"] = None
    body["results"][1]["page_title"] = ""
    body["results"][1]["title_overlap"] = []
    body["results"][1]["title_match"] = "unverifiable (page has no title)"
    body["results"][1]["error"] = "URLError: <urlopen error [Errno 8] nodename nor servname"
    body["results"][1]["pass"] = False
    body["n_failed"] = 1
    body["unreachable"] = 1
    _write(art, body)
    with pytest.raises(V.Refusal, match="unreachable"):
        V.build(art)


# ---------------------------------------------------------------------------
# the denominator
# ---------------------------------------------------------------------------

def test_a_short_artifact_is_refused(art):
    """The `--limit` shape: rows truncated, summary consistent with the truncation."""
    body = _read(art)
    body["results"] = body["results"][:3]
    body["n_checked"] = 3
    _write(art, body)
    with pytest.raises(V.Refusal, match="--limit"):
        V.build(art)


def test_the_denominator_comes_from_triage_not_the_artifact(art, tmp_path):
    """Add a §10 row; the unchanged 24-row artifact must stop being publishable."""
    src = V.TRIAGE.read_text(encoding="utf-8")
    grown = tmp_path / "triage_grown.csv"
    header, *lines = src.splitlines()
    s10 = next(l for l in lines if ",s10," in l and ",trow," in l)
    grown.write_text("\n".join([header, *lines, s10.replace("trow-001", "trow-099", 1)])
                     + "\n", encoding="utf-8")
    assert V.expected_rows(grown) == 25, "the grown triage table was not actually grown"
    with pytest.raises(V.Refusal, match="§10 has 25"):
        V.build(art, grown)


def test_a_triage_table_with_no_s10_rows_is_refused(tmp_path):
    """A derived denominator of 0 would make every artifact look complete."""
    src = V.TRIAGE.read_text(encoding="utf-8")
    header, *lines = src.splitlines()
    empty = tmp_path / "triage_no_s10.csv"
    empty.write_text("\n".join([header, *[l for l in lines
                                          if not (",s10," in l and ",trow," in l)]]) + "\n",
                     encoding="utf-8")
    with pytest.raises(V.Refusal, match="denominator"):
        V.expected_rows(empty)


def test_a_missing_artifact_names_the_command_that_produces_it(tmp_path):
    with pytest.raises(V.Refusal, match="02_check_references.py"):
        V.load_artifact(tmp_path / "nope.json")


def test_an_artifact_for_another_case_is_refused(art):
    body = _read(art)
    body["case"] = "F0-2"
    _write(art, body)
    with pytest.raises(V.Refusal, match="declares case"):
        V.build(art)


# ---------------------------------------------------------------------------
# the published record
# ---------------------------------------------------------------------------

def test_the_published_record_reconciles_with_a_fresh_derivation():
    out = ROOT / "results" / "phase1" / f"{V.CASE}.json"
    if not out.is_file():
        pytest.skip("F0-1 has not been emitted yet")
    published = json.loads(out.read_text(encoding="utf-8"))
    try:
        b = V.build()
    except V.Refusal as exc:
        pytest.skip(f"the artifact cannot be re-derived here: {exc}")
    want = "TRUE" if b["observed_all_resolve_and_describe"] else "FALSE"
    assert published["verdict"] == want, (
        f"results/phase1/{V.CASE}.json says {published['verdict']} and the artifact derives "
        f"{want}; re-run claims/02_references_verdict.py")
    assert published["record"]["n_usable"] == b["n"]


def test_dry_run_writes_nothing(capsys):
    out = ROOT / "results" / "phase1" / f"{V.CASE}.json"
    before = out.read_bytes() if out.is_file() else None
    assert V.main(["--dry-run"]) == 0
    assert "EXISTENCE" in capsys.readouterr().out
    assert (out.read_bytes() if out.is_file() else None) == before
