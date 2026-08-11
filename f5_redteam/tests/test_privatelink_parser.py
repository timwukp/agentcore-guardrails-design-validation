"""Tests for F5-7a's documentation parser and classifier. Offline; no AWS, no HTTP.

Why these exist
---------------
Findings 4 and 5 of FINDING-F5-7A rest entirely on a **regex over an HTML page**.
If `parse_support_table` silently returned `{}` for a page that does contain a
support table, the classifier would report `NOT_TESTED_BY_THIS_INSTRUMENT` and the
document's claim would look untested rather than contradicted. If it returned a
row that isn't there, the reverse. Neither failure is visible in the output — both
produce a well-formed analysis.json.

So the parser is tested against **the real archived artifacts** this project
fetched, not against hand-written HTML (`feedback_verify_against_real_artifact`):
the pages in `evidence/<run>/f5/F5-7a/doc_*.html`. Where those are absent the tests
skip loudly rather than passing vacuously — a test suite that silently covers
nothing is the failure mode `feedback_vacuous_test_check` is about.

The classifier tests are mutation-style: each one changes exactly one input and
asserts the verdict changes. A classifier whose verdict never moves is not
classifying.
"""

from __future__ import annotations

import glob
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "f5_redteam" / "07a_privatelink_enum.py"

# Loaded by path because the filename starts with a digit and is not importable.
_spec = importlib.util.spec_from_file_location("f57a", SCRIPT)
f57a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f57a)


def _archived(pattern: str) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(
        str(ROOT / "evidence" / "*" / "f5" / "F5-7a" / pattern)))


def _text_of(p: Path) -> str:
    raw = p.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return f57a._text(raw)


# ---------------------------------------------------------------------------
# the parser, against the real archived pages
# ---------------------------------------------------------------------------

def test_live_page_yields_the_seven_primitive_rows():
    pages = _archived("doc_live.html")
    if not pages:
        pytest.skip("no archived live page; run 07a_privatelink_enum.py first")
    got = f57a.parse_support_table(_text_of(pages[-1]))
    assert got["has_support_table"] is True
    assert got["n_endpoints_stated"] == "three"
    assert got["endpoint_names_stated"] == [
        "bedrock-agentcore", "bedrock-agentcore-control", "bedrock-agentcore.gateway"]
    # Seven rows: Runtime, Memory, Built-in Tools, Identity, Gateway,
    # Evaluations and Optimizations, Policy.
    assert len(got["rows"]) == 7
    assert all(set(v) == {"data_plane", "control_plane"}
               for v in got["rows"].values())
    # No header cell leaked in as a primitive.
    assert not {"Primitive", "Data plane", "Control plane"} & set(got["rows"])


def test_live_page_evaluations_row_reads_supported_on_both_planes():
    """The observation finding 4 turns on. If this ever fails, re-read the page —
    it does NOT mean the parser broke; AWS may have changed the row again."""
    pages = _archived("doc_live.html")
    if not pages:
        pytest.skip("no archived live page")
    rows = f57a.parse_support_table(_text_of(pages[-1]))["rows"]
    ev = {k: v for k, v in rows.items() if "evaluat" in k.lower()}
    assert len(ev) == 1
    (_, verdicts), = ev.items()
    assert verdicts == {"data_plane": "Supported", "control_plane": "Supported"}


def test_2026_07_snapshot_says_not_yet_supported_and_has_no_optimization_row():
    """Findings 4 and 5 are different verdicts because of exactly this asymmetry."""
    pages = _archived("doc_wayback_202607*.html")
    if not pages:
        pytest.skip("no 2026-07 archived snapshot")
    rows = f57a.parse_support_table(_text_of(pages[-1]))["rows"]
    ev = {k: v for k, v in rows.items() if "evaluat" in k.lower()}
    assert len(ev) == 1
    (name, verdicts), = ev.items()
    assert verdicts["data_plane"] == "Not yet supported"
    assert verdicts["control_plane"] == "Supported"
    # AWS's page never carried an Optimization row -- silence, not contradiction.
    assert not [k for k in rows if "optimi" in k.lower()]
    assert "optimi" not in name.lower()


def test_pre_2026_snapshots_are_reported_absent_not_unparseable():
    """A page with no table must say so. Reporting it as a parse failure would hide
    the most informative observation: AWS published no support matrix at all."""
    pages = [p for p in _archived("doc_wayback_2025*.html")]
    if not pages:
        pytest.skip("no 2025 archived snapshot")
    for p in pages:
        got = f57a.parse_support_table(_text_of(p))
        assert got["has_support_table"] is False
        assert got["rows"] == {}


def test_parser_is_not_vacuous_removing_the_table_changes_the_answer():
    """Mutation: strip the trigger phrase from the real page and the parser must
    stop reporting rows. Without this, `has_support_table: True` could be a
    constant."""
    pages = _archived("doc_live.html")
    if not pages:
        pytest.skip("no archived live page")
    text = _text_of(pages[-1])
    assert f57a.parse_support_table(text)["rows"]           # control arm
    mutated = text.replace("support status for each AgentCore primitive", "XXXX")
    got = f57a.parse_support_table(mutated)
    assert got["has_support_table"] is False and got["rows"] == {}


def test_parser_does_not_invent_rows_from_prose():
    """The words 'Evaluations' and 'Supported' both appear in running prose on that
    page. A parser keying on their co-occurrence rather than on the table would
    fabricate rows here."""
    prose = ("| Evaluations are supported in some regions. | "
             "Optimization is Supported by the console. |")
    got = f57a.parse_support_table(prose)
    assert got["has_support_table"] is False
    assert got["rows"] == {}


def test_tags_collapse_to_a_cell_delimiter_not_whitespace():
    """`Evaluations</td><td>Not yet supported` must not become one token."""
    html = ("<p>support status for each AgentCore primitive</p><table><tr>"
            "<td>Evaluations</td><td>Not yet supported</td><td>Supported</td>"
            "</tr></table>")
    rows = f57a.parse_support_table(f57a._text(html.encode()))["rows"]
    assert rows == {"Evaluations": {"data_plane": "Not yet supported",
                                    "control_plane": "Supported"}}


# ---------------------------------------------------------------------------
# the classifier — one mutation per verdict
# ---------------------------------------------------------------------------

def _api(regions, n_agentcore=3, gateway=True, hits=None):
    out = []
    for r in regions:
        names = [f"com.amazonaws.{r}.bedrock-agentcore",
                 f"com.amazonaws.{r}.bedrock-agentcore-control"]
        if gateway:
            names.append(f"com.amazonaws.{r}.bedrock-agentcore.gateway")
        names = names[:n_agentcore]
        out.append({"region": r, "reachable": True,
                    "agentcore_services": names,
                    "agentcore_service_details": [{"service_name": n} for n in names],
                    "n_agentcore": len(names), "n_all_services": 600,
                    "primitive_keyword_hits": hits or {"evaluations": [],
                                                       "optimization": []}})
    return out


ALL_REGIONS = f57a.SUPPORTED_REGIONS + f57a.CONTROL_REGIONS


def _doc(ev_data, ev_ctrl="Supported", primitive="Evaluations and Optimizations"):
    return {"ok": True, "has_support_table": True, "n_endpoints_stated": "three",
            "rows": {primitive: {"data_plane": ev_data,
                                 "control_plane": ev_ctrl}}}


def _snap(ts, ev_data, primitive="Evaluations"):
    return {"timestamp": ts, "ok": True, "has_support_table": True,
            "rows": {primitive: {"data_plane": ev_data,
                                 "control_plane": "Supported"}}}


def test_gateway_endpoint_verdict_flips_when_the_third_endpoint_is_absent():
    with_gw = f57a.classify(_api(ALL_REGIONS), _doc("Supported"), [])
    without = f57a.classify(_api(ALL_REGIONS, n_agentcore=2, gateway=False),
                            _doc("Supported"), [])
    assert with_gw["findings"]["caveat_b_third_gateway_endpoint"]["verdict"] \
        == "CONFIRMED"
    assert without["findings"]["caveat_b_third_gateway_endpoint"]["verdict"] \
        == "NOT_CONFIRMED"


def test_dedicated_endpoint_verdict_flips_when_a_keyword_hit_appears():
    clean = f57a.classify(_api(ALL_REGIONS), _doc("Supported"), [])
    hit = f57a.classify(
        _api(ALL_REGIONS, hits={"evaluations": ["com.amazonaws.x.evaluations"],
                                "optimization": []}),
        _doc("Supported"), [])
    k = "no_dedicated_evaluations_or_optimization_endpoint_service"
    assert clean["findings"][k]["verdict"] == "CONFIRMED"
    assert hit["findings"][k]["verdict"] == "REFUTED"


def test_evaluations_verdict_distinguishes_all_four_evidence_states():
    """The whole point of instrument B: same live observation, different history,
    different classification."""
    k = "evaluations_data_plane_not_supported"

    # (a) live page still agrees with our document
    r = f57a.classify(_api(ALL_REGIONS), _doc("Not yet supported"), [])
    assert r["findings"][k]["verdict"] == "DOC_CONFIRMED"

    # (b) live page says Supported AND a dated snapshot said otherwise -> changed
    r = f57a.classify(_api(ALL_REGIONS), _doc("Supported"),
                      [_snap("20260714091042", "Not yet supported")])
    assert r["findings"][k]["verdict"] == "AWS_BEHAVIOR_CHANGED"

    # (c) live page says Supported and history never disagreed -> doc contradicted
    r = f57a.classify(_api(ALL_REGIONS), _doc("Supported"),
                      [_snap("20260714091042", "Supported")])
    assert r["findings"][k]["verdict"] == "DOC_CONTRADICTED_BY_AWS_DOCS"

    # (d) the page could not be read at all -> not tested, NOT "confirmed"
    r = f57a.classify(_api(ALL_REGIONS), {"ok": False, "error": "timeout"}, [])
    assert r["findings"][k]["verdict"] == "NOT_TESTED_BY_THIS_INSTRUMENT"


def test_optimization_verdict_is_weaker_than_evaluations_on_the_same_evidence():
    """Finding 5's asymmetry, asserted rather than described.

    With a live 'Supported' row and NO historical Optimization row, Evaluations
    gets AWS_BEHAVIOR_CHANGED (its history disagreed) while Optimization must not:
    AWS was silent about it, and silence is not a transition.
    """
    snaps = [_snap("20260714091042", "Not yet supported", primitive="Evaluations")]
    r = f57a.classify(_api(ALL_REGIONS), _doc("Supported"), snaps)["findings"]
    assert r["evaluations_data_plane_not_supported"]["verdict"] \
        == "AWS_BEHAVIOR_CHANGED"
    assert r["optimization_no_privatelink"]["verdict"] \
        == "DOC_REFUTED_CHANGE_DATE_UNDETERMINED"
    assert r["optimization_no_privatelink"]["aws_page_history"] == []


def test_optimization_verdict_upgrades_when_its_own_history_disagreed():
    snaps = [_snap("20260714091042", "Not yet supported", primitive="Optimization")]
    r = f57a.classify(_api(ALL_REGIONS), _doc("Supported", primitive="Optimization"),
                      snaps)["findings"]
    assert r["optimization_no_privatelink"]["verdict"] == "AWS_BEHAVIOR_CHANGED"


def test_control_arm_is_inconclusive_without_control_regions():
    """The limitation in finding 6 must not be claimed when it was not measured."""
    k = "endpoint_service_existence_is_not_feature_availability"
    full = f57a.classify(_api(ALL_REGIONS), _doc("Supported"), [])
    only_supported = f57a.classify(_api(f57a.SUPPORTED_REGIONS),
                                   _doc("Supported"), [])
    assert full["findings"][k]["verdict"] == "CONFIRMED_AS_LIMITATION"
    assert only_supported["findings"][k]["verdict"] == "INCONCLUSIVE"


def test_unreachable_regions_are_reported_and_excluded_from_verdicts():
    api = _api(f57a.SUPPORTED_REGIONS)
    api.append({"region": "us-gov-west-1", "reachable": False,
                "error_code": "AuthFailure", "error_message": "no credentials"})
    r = f57a.classify(api, _doc("Supported"), [])
    assert r["regions_unreachable"] == [{"region": "us-gov-west-1",
                                         "error_code": "AuthFailure"}]
    assert "us-gov-west-1" not in r["regions_reachable"]
    assert r["findings"]["caveat_b_third_gateway_endpoint"]["n_regions"] == 5


def test_archived_analysis_matches_what_the_classifier_produces_now():
    """Guards against the finding document drifting from the code that produced it:
    re-classify the archived raw observations and require the same verdicts."""
    files = sorted(glob.glob(str(ROOT / "evidence" / "*" / "f5" / "F5-7a"
                                 / "analysis.json")))
    if not files:
        pytest.skip("no archived analysis.json")
    saved = json.loads(Path(files[-1]).read_text())
    redone = f57a.classify(saved["instrument_A"],
                           saved["instrument_B"]["live"],
                           saved["instrument_B"]["wayback"])
    assert {k: v["verdict"] for k, v in redone["findings"].items()} == \
           {k: v["verdict"] for k, v in saved["analysis"]["findings"].items()}
