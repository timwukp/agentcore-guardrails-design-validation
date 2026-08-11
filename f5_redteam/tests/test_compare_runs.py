"""Mutation tests for the F5-7a two-day replication comparator. Offline.

What these guard
----------------
`07a_compare_runs.py` is the thing that decides whether §4.5.3 may be amended. Two
failure modes matter, and they fail in opposite directions:

  * **Too permissive** — a comparator that misses a difference licenses an amendment
    from a single day of evidence dressed up as two. Most arms below mutate exactly one
    field of a real archived run and require the comparator to catch it.
  * **Too strict** — a comparator that fires on request IDs or on the Internet Archive's
    result set can never say yes, which is a wall, not a control. Two arms assert the
    control direction: the real pair of runs differs in both of those ways and must
    still be comparable.

`test_the_must_match_set_has_not_been_hollowed_out` exists because every arm here can
be defeated the same way — by moving a field out of MUST_MATCH. It measures the size of
the compared set instead of trusting it.

The fixtures are the project's **real** archived runs, not hand-built dicts
(`feedback_verify_against_real_artifact`): a synthetic analysis.json would only confirm
my own idea of the schema, and the schema is the thing the comparator depends on.
"""

from __future__ import annotations

import copy
import glob
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "f5_redteam" / "07a_compare_runs.py"

_spec = importlib.util.spec_from_file_location("cmp57a", SCRIPT)
cmp57a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmp57a)


def _real_runs() -> list[Path]:
    return sorted(Path(p).parents[2] for p in glob.glob(
        str(ROOT / "evidence" / "*" / "f5" / "F5-7a" / "analysis.json")))


@pytest.fixture
def runs() -> list[Path]:
    rs = _real_runs()
    if len(rs) < 2:
        pytest.skip(f"needs 2 archived F5-7a runs, found {len(rs)}")
    return rs


@pytest.fixture
def tree(tmp_path, runs) -> Path:
    """A copy of two real runs, rewritten so their evidence records fall on two days.

    The archived pair are both stamped 2026-08-09 (the local calendar had rolled while
    UTC had not — the mistake that motivated this comparator). Shifting the second
    copy's dates gives the arms a *passing* baseline to mutate away from; without one,
    every arm would fail for the same uninteresting reason and none of them would be
    testing what its name says.
    """
    ev = tmp_path / "evidence"
    for i, src in enumerate(runs[:2]):
        dst = ev / src.name
        dst.mkdir(parents=True)
        sd, dd = src / "f5" / "F5-7a", dst / "f5" / "F5-7a"
        dd.mkdir(parents=True)
        for f in sd.glob("*.json"):
            rec = json.loads(f.read_text(encoding="utf-8"))
            if i == 1 and isinstance(rec, dict):
                for k in ("t_start_utc", "t_end_utc"):
                    if rec.get(k):
                        rec[k] = str(rec[k]).replace("2026-08-09", "2026-08-10", 1)
            (dd / f.name).write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return ev


def run(tree: Path, day1: str, day2: str) -> tuple[int, str]:
    """Invoke the comparator as a subprocess against a redirected evidence root."""
    monkey = tree.parent / "drive.py"
    monkey.write_text(
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('c', {str(SCRIPT)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        f"m.EVIDENCE = __import__('pathlib').Path({str(tree)!r})\n"
        "sys.exit(m.main(sys.argv[1:]))\n", encoding="utf-8")
    p = subprocess.run([sys.executable, str(monkey), day1, day2],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def ids(tree: Path) -> tuple[str, str]:
    return tuple(sorted(d.name for d in tree.iterdir() if d.is_dir()))[:2]


def load(tree: Path, run_id: str) -> dict:
    return json.loads((tree / run_id / "f5" / "F5-7a" / "analysis.json")
                      .read_text(encoding="utf-8"))


def save(tree: Path, run_id: str, obj: dict) -> None:
    (tree / run_id / "f5" / "F5-7a" / "analysis.json").write_text(
        json.dumps(obj, indent=2), encoding="utf-8")


def kills(res: tuple[int, str], needle: str, rc: int = 1) -> None:
    got_rc, out = res
    assert got_rc == rc, f"expected rc={rc}, got {got_rc}\n{out}"
    assert needle in out, f"expected {needle!r} in output\n{out}"


# ---------------------------------------------------------------------------
# control arms: the comparator must be able to say yes
# ---------------------------------------------------------------------------

def test_control_arm_two_real_runs_on_two_days_replicate(tree):
    """The baseline. If this fails, every mutation arm below is meaningless."""
    d1, d2 = ids(tree)
    rc, out = run(tree, d1, d2)
    assert rc == 0, out
    assert "REPLICATED" in out


def test_request_ids_differ_between_the_real_runs_and_do_not_block(tree):
    """A live-call identifier changes on every run by definition.

    Asserted against the real artifacts rather than by mutation: if these two runs
    happened to share request IDs, the control arm above would prove nothing about
    tolerance, so the difference is checked to actually exist.
    """
    d1, d2 = ids(tree)
    a, b = load(tree, d1), load(tree, d2)
    pairs = [(x["filtered_request_id"], y["filtered_request_id"])
             for x, y in zip(a["instrument_A"], b["instrument_A"])]
    assert any(x != y for x, y in pairs), \
        "the two archived runs share every request id; this arm cannot test tolerance"
    assert run(tree, d1, d2)[0] == 0


def test_the_wayback_result_set_shrank_between_the_real_runs_and_does_not_block(tree):
    """The CDX index returned 8 snapshots on day 1 and 6 on day 2.

    That is a property of a third-party index, not an observation about AWS. It is
    reported as a note and must not be fatal — otherwise the amendment would be
    hostage to archive.org's availability.
    """
    d1, d2 = ids(tree)
    a, b = load(tree, d1), load(tree, d2)
    ta = {w["timestamp"] for w in a["instrument_B"]["wayback"]}
    tb = {w["timestamp"] for w in b["instrument_B"]["wayback"]}
    assert ta != tb, "the archived runs have identical snapshot sets; arm is vacuous"
    rc, out = run(tree, d1, d2)
    assert rc == 0, out
    assert "snapshot(s) returned on day 1 and not day 2" in out


# ---------------------------------------------------------------------------
# the day rule
# ---------------------------------------------------------------------------

def test_kills_a_same_day_repeat(tree):
    """The central arm: the exact mistake that happened.

    `r20260810T0930Z` was minted while UTC was still 2026-08-09T16:20, so a 6.8-hour
    repeat carried a run id asserting a second day. Undo the fixture's date shift and
    the comparator must refuse.
    """
    d1, d2 = ids(tree)
    base = tree / d2 / "f5" / "F5-7a"
    for f in base.glob("0*.json"):
        rec = json.loads(f.read_text())
        for k in ("t_start_utc", "t_end_utc"):
            if rec.get(k):
                rec[k] = str(rec[k]).replace("2026-08-10", "2026-08-09", 1)
        f.write_text(json.dumps(rec, indent=2))
    kills(run(tree, d1, d2), "both runs were collected on 2026-08-09")


def test_the_run_id_is_not_trusted_for_the_date(tree):
    """A directory named for a later day whose records are same-day must still fail.

    The counterpart of lib.evidence.new_run_id's guard: that one refuses to *create*
    such a name, this one refuses to *believe* one that already exists.
    """
    d1, d2 = ids(tree)
    liar = "r20270101T000000Z"
    (tree / d2).rename(tree / liar)
    base = tree / liar / "f5" / "F5-7a"
    for f in base.glob("0*.json"):
        rec = json.loads(f.read_text())
        for k in ("t_start_utc", "t_end_utc"):
            if rec.get(k):
                rec[k] = str(rec[k]).replace("2026-08-10", "2026-08-09", 1)
        f.write_text(json.dumps(rec, indent=2))
    kills(run(tree, d1, liar), "both runs were collected on 2026-08-09")


def test_kills_a_run_with_no_dated_records(tree):
    d1, d2 = ids(tree)
    for f in (tree / d2 / "f5" / "F5-7a").glob("0*.json"):
        rec = json.loads(f.read_text())
        rec.pop("t_start_utc", None)
        f.write_text(json.dumps(rec, indent=2))
    kills(run(tree, d1, d2), "has no dated evidence records")


# ---------------------------------------------------------------------------
# instrument B — the live page, which is what the amendment quotes
# ---------------------------------------------------------------------------

def test_kills_a_changed_evaluations_row(tree):
    """The amendment's whole content. If day 2's page said something else, stop."""
    d1, d2 = ids(tree)
    b = load(tree, d2)
    rows = b["instrument_B"]["live"]["rows"]
    key = next(k for k in rows if "Evaluations" in k)
    rows[key] = {"control_plane": "Supported", "data_plane": "Not yet supported"}
    save(tree, d2, b)
    kills(run(tree, d1, d2), f"B:live:row:{key}")


def test_kills_a_live_page_that_stopped_parsing(tree):
    """`has_support_table: false` on day 2 is the CDN-variant hypothesis coming true."""
    d1, d2 = ids(tree)
    b = load(tree, d2)
    b["instrument_B"]["live"]["has_support_table"] = False
    save(tree, d2, b)
    kills(run(tree, d1, d2), "B:live:has_support_table")


def test_kills_a_dropped_row(tree):
    d1, d2 = ids(tree)
    b = load(tree, d2)
    key = next(k for k in b["instrument_B"]["live"]["rows"] if "Evaluations" in k)
    del b["instrument_B"]["live"]["rows"][key]
    save(tree, d2, b)
    kills(run(tree, d1, d2), "was observed on day 1 and is absent on day 2")


def test_kills_an_added_row(tree):
    d1, d2 = ids(tree)
    b = load(tree, d2)
    b["instrument_B"]["live"]["rows"]["Invented"] = {"control_plane": "Supported",
                                                    "data_plane": "Supported"}
    save(tree, d2, b)
    kills(run(tree, d1, d2), "appeared on day 2 and was absent on day 1")


def test_kills_a_changed_endpoint_count_in_the_prose(tree):
    """Caveat (b) rests on the page saying `three` endpoints."""
    d1, d2 = ids(tree)
    b = load(tree, d2)
    b["instrument_B"]["live"]["n_endpoints_stated"] = "two"
    save(tree, d2, b)
    kills(run(tree, d1, d2), "B:live:n_endpoints_stated")


def test_kills_an_archived_page_that_parsed_differently(tree):
    """An archived page is immutable, so this means a parse is wrong.

    Distinct in kind from every other arm: it does not mean AWS changed, it means
    instrument B is unreliable and no verdict from it can be trusted.
    """
    d1, d2 = ids(tree)
    b = load(tree, d2)
    snap = next(w for w in b["instrument_B"]["wayback"] if w["has_support_table"])
    snap["rows"] = {"Evaluations": {"control_plane": "Supported",
                                    "data_plane": "Supported"}}
    save(tree, d2, b)
    kills(run(tree, d1, d2), "an archived page is immutable")


# ---------------------------------------------------------------------------
# instrument A — the endpoint-service enumeration
# ---------------------------------------------------------------------------

def test_kills_a_disappeared_endpoint_service(tree):
    d1, d2 = ids(tree)
    b = load(tree, d2)
    reg = b["instrument_A"][0]
    reg["agentcore_services"] = reg["agentcore_services"][:-1]
    reg["agentcore_service_details"] = reg["agentcore_service_details"][:-1]
    reg["n_agentcore"] = 2
    save(tree, d2, b)
    kills(run(tree, d1, d2), "n_agentcore")


def test_kills_a_new_primitive_keyword_hit(tree):
    """A dedicated Evaluations endpoint service appearing would change the finding."""
    d1, d2 = ids(tree)
    b = load(tree, d2)
    b["instrument_A"][0]["primitive_keyword_hits"]["evaluations"] = [
        "com.amazonaws.us-east-1.bedrock-agentcore-evaluations"]
    save(tree, d2, b)
    kills(run(tree, d1, d2), "primitive_keyword_hits")


def test_kills_a_changed_private_dns_name(tree):
    d1, d2 = ids(tree)
    b = load(tree, d2)
    b["instrument_A"][0]["agentcore_service_details"][0]["private_dns"] = "elsewhere"
    save(tree, d2, b)
    kills(run(tree, d1, d2), "private_dns")


def test_kills_a_region_that_became_unreachable(tree):
    d1, d2 = ids(tree)
    b = load(tree, d2)
    b["analysis"]["regions_reachable"] = b["analysis"]["regions_reachable"][:-1]
    b["analysis"]["regions_unreachable"] = [{"region": "eu-north-1",
                                            "error_code": "AuthFailure"}]
    save(tree, d2, b)
    kills(run(tree, d1, d2), "regions_")


def test_kills_a_changed_verdict(tree):
    d1, d2 = ids(tree)
    b = load(tree, d2)
    name = "optimization_no_privatelink"
    b["analysis"]["findings"][name]["verdict"] = "CONFIRMED"
    save(tree, d2, b)
    kills(run(tree, d1, d2), f"verdict:{name}")


def test_kills_a_dropped_finding(tree):
    d1, d2 = ids(tree)
    b = load(tree, d2)
    del b["analysis"]["findings"]["caveat_b_third_gateway_endpoint"]
    save(tree, d2, b)
    kills(run(tree, d1, d2), "verdict:caveat_b_third_gateway_endpoint")


# ---------------------------------------------------------------------------
# the comparator's own integrity
# ---------------------------------------------------------------------------

def test_kills_a_missing_run(tree):
    d1, _ = ids(tree)
    kills(run(tree, d1, "rNOPE"), "does not exist", rc=2)


def test_kills_a_schema_change_rather_than_reporting_replicated(tree):
    """A run missing a field the comparator reads must be rc=2, never rc=0.

    The dangerous direction: a KeyError swallowed into "nothing differed" would report
    a replication from a run that could not be read.
    """
    d1, d2 = ids(tree)
    b = load(tree, d2)
    del b["instrument_B"]["live"]["rows"]
    save(tree, d2, b)
    rc, out = run(tree, d1, d2)
    assert rc == 2, f"expected rc=2 on a schema change, got {rc}\n{out}"
    assert "not comparable" in out


def test_the_must_match_set_has_not_been_hollowed_out(tree):
    """Every arm above can be defeated by shrinking MUST_MATCH. Measure it.

    The floor is well below the current yield (75) so that adding fields never
    requires editing this test — it is a tripwire for fields being *removed*.
    """
    d1, _ = ids(tree)
    fields = cmp57a.must_match(load(tree, d1))
    assert len(fields) >= 60, (
        f"only {len(fields)} field(s) in MUST_MATCH; the comparator has been hollowed "
        f"out and its 'REPLICATED' verdict no longer means what the arms above test")
    for needed in ("B:live:has_support_table", "verdict:optimization_no_privatelink",
                   "verdict:evaluations_data_plane_not_supported",
                   "endpoint_prefixes"):
        assert needed in fields, f"{needed} is no longer compared"
    assert any(k.startswith("B:live:row:") and "Evaluations" in k for k in fields), \
        "the Evaluations row — the entire content of the amendment — is not compared"


def test_the_assertion_floor_would_catch_a_hollowed_comparator(tree, monkeypatch):
    """Mutation-check the floor itself: if MIN_ASSERTIONS could never bind, it is prose.

    Shrink must_match to one field and require the run to fail *on the floor*, not
    on a difference. Without this, MIN_ASSERTIONS = 20 against a 75-field set is an
    unverified number in a constant — feedback_prose_is_not_verified.
    """
    d1, d2 = ids(tree)
    monkeypatch.setattr(cmp57a, "EVIDENCE", tree)
    monkeypatch.setattr(cmp57a, "must_match",
                        lambda a: {"only_one": a["analysis"]["endpoint_prefixes"]})
    bad, _notes, n = cmp57a.compare(d1, d2)
    assert n < cmp57a.MIN_ASSERTIONS
    assert any("below the floor" in x for x in bad), \
        f"the floor did not bind at n={n}; MIN_ASSERTIONS is decorative"


def test_wayback_only_snapshots_are_notes_not_disagreements(tree, monkeypatch):
    """Direct unit check of the MAY_VARY rule, independent of the real runs' contents."""
    d1, d2 = ids(tree)
    monkeypatch.setattr(cmp57a, "EVIDENCE", tree)
    b = load(tree, d2)
    b["instrument_B"]["wayback"] = b["instrument_B"]["wayback"][:1]
    save(tree, d2, b)
    bad, notes, _n = cmp57a.compare(d1, d2)
    assert not bad, bad
    assert any("not day 2" in x for x in notes)
