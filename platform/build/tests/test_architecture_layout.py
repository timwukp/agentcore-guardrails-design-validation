"""The diagram layout, asserted as geometry rather than as an impression.

WHY THIS IS A TEST AND NOT A LOOK

A crossing is not a cosmetic defect. Two arrows that meet where no relation exists read as a relation,
and an architecture picture is the artifact most likely to be quoted with no text beside it — so a
misreadable one is a claim this project did not make, travelling without its caveats
(`feedback_diagram_layout_rules`). "It looked fine" is also exactly the check that stops being
performed: the layout was verified once, by eye, against the topology of the day, and a box added six
months later moves twelve edges nobody re-examines.

WHY THE ASSERTIONS ARE EQUALITIES

Zero crossings, zero edges through a box. Not "few" and not "within tolerance". The layout in
`build_site_data._layout` is constrained precisely so that zero is achievable and provable — the spine
is a single column of rows, satellite boxes sit in their parent's row with their edges routed in a band
above it, and row-skipping edges take nested lanes in a left gutter. Under those constraints a
crossing can only come from a case the construction does not cover: two skip spans that properly
overlap, which a single gutter cannot draw cleanly. Asserting equality is what makes that case a build
failure with a name instead of a picture with a lie in it.

WHY ONE EDGE KIND IS EXEMPT FROM THE ORDERING ARM, AND WHAT REPLACES THE EXEMPTION

The closed-loop diagram is a loop: its last stage revises the policy the first hop enforces, and an
arrow that shows that has to point back up the page. So `test_the_spine_is_one_box_per_row_in_
topological_order` skips edges of kind `feedback` — and an exemption with nothing in its place is how a
rule quietly stops applying to the one case it was widened for. Two arms take over. Here,
`test_a_feedback_edge_points_up_the_page` requires every such edge to actually run upwards and to skip
a row, so the label cannot be attached to an ordinary forward step; and in `check_architecture.py`, the
graph minus its feedback edges must still be acyclic and every feedback edge must lie on a cycle in the
full graph. Between them the exemption buys exactly one thing: an arrow that closes a loop.

WHY A DELIBERATELY CROSSING FIXTURE IS PART OF THE FILE

A crossing detector that never fires is indistinguishable from a layout with no crossings, and the
first is far likelier (`feedback_vacuous_test_check`). So `test_the_detector_finds_a_real_crossing`
hands the same function a pair of segments that plainly cross and requires it to say so, and
`test_the_detector_finds_an_edge_through_a_box` does the same for the box arm. Without those two the
rest of this file would pass over a detector that returns an empty list unconditionally.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "platform" / "build"))

import build_site_data as bsd  # noqa: E402

pytest.importorskip("yaml", reason="the derivation itself refuses to run without PyYAML")

# Floors. A layout check over an empty diagram passes trivially, which is the one result that must not
# be reachable (`feedback_zero_file_scan_is_error`).
MIN_DIAGRAMS = 3
MIN_BOXES = 12
MIN_EDGES = 12
# The one kind of edge the ordering arm below exempts, so there must be at least this many of them for
# the exemption's replacement arm to assert anything. A count of zero would make
# `test_a_feedback_edge_points_up_the_page` pass over an empty set, which is the shape a rule takes
# when the diagram that needed the exemption is deleted and the exemption stays.
MIN_FEEDBACK_EDGES = 1


# --------------------------------------------------------------------------- geometry


def _segments(edge: dict) -> list[tuple[float, float, float, float]]:
    pts = edge["points"]
    return [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(len(pts) - 1)]


def _span(a: float, b: float) -> tuple[float, float]:
    return (a, b) if a <= b else (b, a)


def crossings(edges: list[dict]) -> list[str]:
    """Every pair of edge segments whose interiors meet, or that overlap collinearly.

    Axis-aligned throughout, so the cases are exhaustive and there is no floating-point tolerance to
    argue about. Touching at a shared endpoint is NOT a crossing: two edges out of one box legitimately
    meet at that box. Collinear overlap of more than a point IS reported — two arrows drawn on top of
    each other are one arrow as far as a reader is concerned.
    """
    out = []
    flat = [(e, s) for e in edges for s in _segments(e)]
    for i, (e1, s1) in enumerate(flat):
        for e2, s2 in flat[i + 1:]:
            if e1 is e2:
                continue
            x1a, y1a, x1b, y1b = s1
            x2a, y2a, x2b, y2b = s2
            v1, v2 = x1a == x1b, x2a == x2b
            name = (f"{e1['from']}->{e1['to']} {s1} x {e2['from']}->{e2['to']} {s2}")
            if v1 != v2:
                (vx, vy0, vy1), (hy, hx0, hx1) = (
                    ((x1a, *_span(y1a, y1b)), (y2a, *_span(x2a, x2b))) if v1
                    else ((x2a, *_span(y2a, y2b)), (y1a, *_span(x1a, x1b))))
                if hx0 < vx < hx1 and vy0 < hy < vy1:
                    out.append(f"crossing: {name}")
            elif v1 and x1a == x2a:
                lo, hi = max(min(y1a, y1b), min(y2a, y2b)), min(max(y1a, y1b), max(y2a, y2b))
                if lo < hi:
                    out.append(f"collinear overlap: {name}")
            elif not v1 and y1a == y2a:
                lo, hi = max(min(x1a, x1b), min(x2a, x2b)), min(max(x1a, x1b), max(x2a, x2b))
                if lo < hi:
                    out.append(f"collinear overlap: {name}")
    return out


def through_boxes(edges: list[dict], boxes: list[dict]) -> list[str]:
    """Every edge segment that passes through the interior of a box.

    An edge that ends on a box's boundary is how an arrow attaches; one that crosses the interior is
    an arrow drawn over a label, which is worse than a crossing because the box is what the reader is
    trying to read.
    """
    out = []
    for e in edges:
        for x0, y0, x1, y1 in _segments(e):
            sx, ex = _span(x0, x1)
            sy, ey = _span(y0, y1)
            for b in boxes:
                bx0, by0, bx1, by1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
                if sx < bx1 and ex > bx0 and sy < by1 and ey > by0:
                    out.append(f"{e['from']}->{e['to']} segment ({x0},{y0})-({x1},{y1}) "
                               f"enters box {b['id']}")
    return out


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def arch() -> dict:
    """The real derivation over the real tree — never a fixture diagram.

    A hand-built topology drifts from the authored one, and then this file certifies a picture nobody
    publishes. The cost is that a change to `architecture.yaml` can fail these tests, which is the
    entire point: the layout claim belongs to the file that is served.
    """
    cases, _, _, _ = bsd.derive_register({})
    published = bsd.derive_published({})
    archive = bsd.derive_archive({})
    _, by_case = bsd.derive_claims({})
    policy = bsd.derive_citation_policy({})
    restricted: dict[str, list[str]] = {}
    for r in policy.get("restrictions", []):
        for c in r.get("cases", []):
            restricted.setdefault(c, []).append(r["restriction"])
    families = bsd.derive_families({}, cases)
    controls = bsd.derive_controls({}, cases, published, restricted)
    figures = bsd.derive_figures({}, None)
    registers = bsd.derive_registers({})
    metrics = bsd.architecture_metrics(cases, published, restricted, archive, by_case, families,
                                      controls, figures, registers)
    # The design document's sections, in the same order the builder resolves them: a box that names a
    # section takes its cases from here, so a fixture that passed an empty mapping would lay out nine
    # boxes of the closed-loop diagram as though they carried no evidence at all.
    practices = bsd.derive_practices({}, cases, published, restricted)
    sections = {s["id"]: s for s in practices["sections"]}
    return bsd.derive_architecture({}, cases, published, restricted, metrics, sections)


# --------------------------------------------------------------------------- the layout


def test_the_payload_has_every_diagram_and_none_is_empty(arch):
    assert len(arch["diagrams"]) >= MIN_DIAGRAMS
    for d in arch["diagrams"]:
        assert d["n_boxes"] >= MIN_BOXES, d["id"]
        assert d["n_edges"] >= MIN_EDGES, d["id"]


def test_no_two_edges_cross(arch):
    for d in arch["diagrams"]:
        found = crossings(d["edges"])
        assert found == [], f"{d['id']}: {len(found)} crossing(s)\n" + "\n".join(found)


def test_no_edge_passes_through_a_box(arch):
    for d in arch["diagrams"]:
        found = through_boxes(d["edges"], d["boxes"])
        assert found == [], f"{d['id']}: {len(found)}\n" + "\n".join(found)


def test_no_two_boxes_overlap(arch):
    for d in arch["diagrams"]:
        bs = d["boxes"]
        for i, a in enumerate(bs):
            for b in bs[i + 1:]:
                apart = (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"]
                         or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])
                assert apart, f"{d['id']}: {a['id']} overlaps {b['id']}"


def test_every_box_and_every_point_is_inside_the_viewbox(arch):
    """Otherwise the SVG clips silently, and a clipped box is an absent box to the reader."""
    for d in arch["diagrams"]:
        v = d["viewbox"]
        x0, y0, x1, y1 = v["min_x"], v["min_y"], v["min_x"] + v["width"], v["min_y"] + v["height"]
        for b in d["boxes"]:
            assert x0 <= b["x"] and b["x"] + b["w"] <= x1, f"{d['id']}/{b['id']} clipped in x"
            assert y0 <= b["y"] and b["y"] + b["h"] <= y1, f"{d['id']}/{b['id']} clipped in y"
        for e in d["edges"]:
            for px, py in e["points"]:
                assert x0 <= px <= x1 and y0 <= py <= y1, f"{d['id']} edge point ({px},{py}) clipped"


def test_every_edge_starts_and_ends_on_its_boxes(arch):
    """A polyline whose ends float near the boxes is a diagram whose arrows point at whitespace."""
    for d in arch["diagrams"]:
        at = {b["id"]: b for b in d["boxes"]}
        for e in d["edges"]:
            for end, (px, py) in (("from", e["points"][0]), ("to", e["points"][-1])):
                b = at[e[end]]
                on_edge = ((px in (b["x"], b["x"] + b["w"]) and b["y"] <= py <= b["y"] + b["h"])
                           or (py in (b["y"], b["y"] + b["h"]) and b["x"] <= px <= b["x"] + b["w"]))
                assert on_edge, f"{d['id']} {e['from']}->{e['to']} {end} point ({px},{py}) is not on " \
                                f"the boundary of {b['id']}"


def test_a_satellite_box_sits_in_its_parents_row(arch):
    """The placement rule the crossing-free construction rests on, asserted rather than assumed.

    Over every satellite kind, not just `property`. `alternative` has the identical geometric contract —
    one parent, no children, its parent's row — and reading only `property` here would have left the
    construction's own precondition unchecked for the kind added last, which is the kind least likely to
    have been drawn by hand.
    """
    for d in arch["diagrams"]:
        at = {b["id"]: b for b in d["boxes"]}
        parents = {e["to"]: e["from"] for e in d["edges"]
                   if at[e["to"]]["kind"] in bsd.SATELLITE_KINDS}
        for box in d["boxes"]:
            if box["kind"] not in bsd.SATELLITE_KINDS:
                continue
            assert box["id"] in parents, f"{box['id']} has no incoming edge"
            parent = at[parents[box["id"]]]
            assert parent["kind"] not in bsd.SATELLITE_KINDS, \
                f"{box['id']} hangs off another satellite box"
            assert box["y"] == parent["y"], f"{box['id']} is not in {parent['id']}'s row"
            assert box["x"] > parent["x"], f"{box['id']} is not to the right of {parent['id']}"


def test_the_spine_is_one_box_per_row_in_topological_order(arch):
    """Every edge runs down the page — except the one kind whose meaning is that it does not.

    A feedback edge is exempt here and re-checked in the arm below, because an exemption with nothing in
    its place is how a rule stops applying to the case that needed it. `check_architecture.py` holds the
    other half: the graph minus the feedback edges must still be acyclic, so this exemption cannot be
    used to smuggle in a cycle among the forward edges.
    """
    for d in arch["diagrams"]:
        spine = [b for b in d["boxes"] if b["kind"] not in bsd.SATELLITE_KINDS]
        rows = [b["row"] for b in spine]
        assert sorted(rows) == list(range(len(spine))), f"{d['id']} rows are {sorted(rows)}"
        row_of = {b["id"]: b["row"] for b in spine}
        for e in d["edges"]:
            if e["kind"] == bsd.FEEDBACK_EDGE_KIND:
                continue
            if e["from"] in row_of and e["to"] in row_of:
                assert row_of[e["from"]] < row_of[e["to"]], \
                    f"{d['id']}: {e['from']}->{e['to']} points up the page"


def test_a_feedback_edge_points_up_the_page(arch):
    """The replacement for the exemption above, and the reason the edge kind exists at all.

    A `feedback` edge that happened to run downwards would be an ordinary step wearing a label that
    switches off the acyclicity check — the one thing the kind must not be able to do. It is also
    required to skip a row: the builder refuses an adjacent-row feedback edge, because in the spine band
    the arrowhead is the only thing distinguishing it from a forward step, and a reader following the
    column reads a step.
    """
    seen = 0
    for d in arch["diagrams"]:
        row_of = {b["id"]: b["row"] for b in d["boxes"]
                  if b["kind"] not in bsd.SATELLITE_KINDS}
        for e in d["edges"]:
            if e["kind"] != bsd.FEEDBACK_EDGE_KIND:
                continue
            assert e["from"] in row_of and e["to"] in row_of, \
                f"{d['id']}: {e['from']}->{e['to']} is a feedback edge onto a satellite box"
            assert row_of[e["from"]] > row_of[e["to"]], \
                f"{d['id']}: {e['from']}->{e['to']} is kind {bsd.FEEDBACK_EDGE_KIND} but runs down the " \
                f"page, so it exempts a forward step from the acyclicity check"
            assert row_of[e["from"]] - row_of[e["to"]] > 1, \
                f"{d['id']}: {e['from']}->{e['to']} spans adjacent rows, where only its arrowhead " \
                f"distinguishes it from the forward edge beside it"
            seen += 1
    assert seen >= MIN_FEEDBACK_EDGES, \
        f"the payload holds {seen} feedback edge(s); the exemption in the arm above would then be " \
        f"granted to nothing and checked against nothing"


# --------------------------------------------------------------- the detectors are not vacuous


def test_the_detector_finds_a_real_crossing():
    plus = [{"from": "a", "to": "b", "points": [[0, 50], [100, 50]]},
            {"from": "c", "to": "d", "points": [[50, 0], [50, 100]]}]
    assert len(crossings(plus)) == 1


def test_the_detector_finds_a_collinear_overlap():
    same = [{"from": "a", "to": "b", "points": [[0, 0], [100, 0]]},
            {"from": "c", "to": "d", "points": [[50, 0], [150, 0]]}]
    assert len(crossings(same)) == 1


def test_the_detector_allows_a_shared_endpoint():
    """Two edges leaving one box meet at that box. Reporting that would make the real arm unreadable."""
    corner = [{"from": "a", "to": "b", "points": [[0, 0], [0, 100]]},
              {"from": "a", "to": "c", "points": [[0, 0], [100, 0]]}]
    assert crossings(corner) == []


def test_the_detector_finds_an_edge_through_a_box():
    box = [{"id": "b", "x": 0, "y": 0, "w": 100, "h": 100}]
    edge = [{"from": "x", "to": "y", "points": [[-50, 50], [150, 50]]}]
    assert len(through_boxes(edge, box)) == 1


def test_the_box_arm_allows_an_edge_that_only_touches_a_boundary():
    box = [{"id": "b", "x": 0, "y": 0, "w": 100, "h": 100}]
    edge = [{"from": "x", "to": "y", "points": [[100, 50], [200, 50]]}]
    assert through_boxes(edge, box) == []


def test_a_properly_overlapping_pair_of_skip_spans_is_caught(arch):
    """The one case the construction cannot draw cleanly must FAIL rather than ship.

    Two row-skipping edges whose spans properly overlap — a<c<b<d — cannot both be routed in a single
    left gutter without a crossing. The layout does not detect that itself; this arm proves the
    detector does, by taking the real diagram's geometry and adding the pair by hand. If this ever
    stops finding a crossing, the equality assertions above have gone vacuous for exactly the case
    they exist to catch.
    """
    d = next(x for x in arch["diagrams"] if x["n_boxes"] >= MIN_BOXES)
    spine = sorted([b for b in d["boxes"] if b["kind"] not in bsd.SATELLITE_KINDS],
                   key=lambda b: b["row"])
    assert len(spine) >= 8, "this arm needs a spine long enough to hold two overlapping spans"
    a, b, c, e = spine[0], spine[4], spine[2], spine[6]
    mid = bsd.BOX_H / 2
    fake = [
        {"from": a["id"], "to": b["id"],
         "points": [[0, a["y"] + mid - 6], [-38, a["y"] + mid - 6], [-38, b["y"] + mid - 6],
                    [0, b["y"] + mid - 6]]},
        {"from": c["id"], "to": e["id"],
         "points": [[0, c["y"] + mid - 12], [-68, c["y"] + mid - 12], [-68, e["y"] + mid - 12],
                    [0, e["y"] + mid - 12]]},
    ]
    assert crossings(fake), "the detector missed a pair of properly overlapping gutter spans"
