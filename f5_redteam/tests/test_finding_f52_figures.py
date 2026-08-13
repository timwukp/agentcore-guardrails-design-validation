#!/usr/bin/env python3
"""Every figure FINDING-F5-2.md states must still be true of the two analysis records.

Why this file exists
--------------------
F5-2 publishes a two-day comparison: four arms, four chain legs, six propagation waits, two
revocation sequences, four mode-change latencies, two call times and a per-day evidence
census. Those numbers are prose in a markdown file, and prose is unchecked
(`feedback_prose_is_not_verified`). The specific decay this guards against is the flattering
one: day 2's `granted_mutation` went 2/5 -> 5/5 and its revocation stopped flapping, so an
edit that "tidied" the comparison table toward day 1's story would read as a cleaner result
than was measured.

Direction of the check is deliberate: each arm re-derives the figure from
`results/phase1/F5-2.json` (day 2) or `results/phase1/archive/F5-2__day1_2026-08-12.json`
(day 1) and then requires the document to state it. A number that exists in the record and
not in the doc is not a failure — the doc does not have to publish everything. A number the
doc states that the record contradicts is.

Most of these figures appear **twice**: once in the prose of §3–§7 and once in §9's
replication table. `_pin`'s `needle in doc` therefore only proves *one* site is right, which is
the stale-second-site hole `feedback_grep_the_claim_not_the_phrasing` names — a mutation
harness confirmed that editing either copy of `**325.0 s**` left `_pin` green. So §9 is checked
structurally instead: `_row()` parses that table and each cell is matched against the record it
came from, and `test_a_stale_cell_in_the_replication_table_is_caught` proves the parser really
reads the cell it claims to.

The evidence-census arms need `evidence/`, which is local-only by policy and absent on the
runner. They SKIP there rather than fail, and the skip is asserted to be the only reason
they can be quiet (`test_the_evidence_arms_are_not_silently_skipping_everything`).

    .venv-oracle/bin/python -m pytest f5_redteam/tests/test_finding_f52_figures.py -q
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("GRX_F52_ROOT") or Path(__file__).resolve().parents[2])
# `GRX_F52_FINDING` exists so test_finding_f52_mutation.py can point these arms at a doctored
# COPY of the finding. The live document is never written by a test — same mechanism, and same
# reason, as `GRX_F92_SCRIPT` in f9_failsecure/tests/test_mismatch_verdict_mutation.py.
DOC = Path(os.environ.get("GRX_F52_FINDING") or (ROOT / "results" / "FINDING-F5-2.md"))
DAY2 = ROOT / "results" / "phase1" / "F5-2.json"
DAY1 = ROOT / "results" / "phase1" / "archive" / "F5-2__day1_2026-08-12.json"
EVID = ROOT / "evidence" / "r20260810T130945Z" / "f5" / "F5-2"


@pytest.fixture(scope="module")
def doc() -> str:
    assert DOC.exists(), "FINDING-F5-2.md is not published"
    return DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def prose(doc) -> str:
    """Everything before §9.

    Figures that §3-§7 discuss and §9 tabulates must be pinned in the half they are being
    claimed about. Pinning them against the whole document lets §9's copy keep the assertion
    green while the prose goes stale — a mutation harness demonstrated exactly that for
    `**325.0 s**` and `**931.7 ms**`. §9 itself is checked cell by cell further down.
    """
    head, sep, _ = doc.partition("## 9.")
    assert sep, "the finding no longer has a §9; the prose/table split this file relies on is gone"
    return head


@pytest.fixture(scope="module")
def d1() -> dict:
    return json.loads(DAY1.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def d2() -> dict:
    return json.loads(DAY2.read_text(encoding="utf-8"))


def _pin(doc: str, needle: str, derived) -> None:
    assert needle in doc, (
        f"the record says {derived!r}, and FINDING-F5-2.md no longer states {needle!r}")


def _rows(doc: str) -> dict[str, tuple[str, str]]:
    """Parse §9's replication table into {row label: (day-1 cell, day-2 cell)}.

    Scoped to §9 so a same-shaped table elsewhere cannot satisfy a row lookup.
    """
    body = doc.split("## 9.", 1)[1].split("## 10.", 1)[0]
    out: dict[str, tuple[str, str]] = {}
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) != 3 or set(parts[0]) <= {"-"}:
            continue
        out[parts[0]] = (parts[1], parts[2])
    assert len(out) >= 20, f"§9's table parsed to {len(out)} rows; the parser or the table moved"
    return out


def _cell(rows: dict[str, tuple[str, str]], label: str) -> tuple[str, str]:
    hits = [k for k in rows if label in k]
    assert len(hits) == 1, f"{label!r} matched {hits} in §9's table"
    return rows[hits[0]]


# ---- the verdict and the pre-registered arm ---------------------------------------------

@pytest.mark.parametrize("day", ["d1", "d2"])
def test_the_closed_arm_is_identical_on_both_days(day, d1, d2, doc):
    rec = {"d1": d1, "d2": d2}[day]
    arm = rec["arms"]["closed_baseline"]
    assert (arm["n_attempted"], arm["n_usable"], arm["n_authorized"], arm["n_denied"]) == \
        (120, 120, 0, 120), arm
    assert arm["n_conflict"] == 0 and arm["n_unusable"] == 0
    assert arm["error_codes"] == ["AccessDeniedException"]
    assert rec["verdict"] == "TRUE"
    _pin(doc, "**0 / 0** | **120 / 120**", arm)


@pytest.mark.parametrize("day", ["d1", "d2"])
def test_all_eleven_guards_held_on_both_days(day, d1, d2, doc):
    guards = {"d1": d1, "d2": d2}[day]["guards"]
    assert len(guards) == 11 and all(guards.values()), guards
    _pin(doc, "| guards true | **11 / 11** | **11 / 11** |", len(guards))


@pytest.mark.parametrize("day", ["d1", "d2"])
def test_the_interval_and_ceiling_are_the_same_computation(day, d1, d2, prose):
    ev = {"d1": d1, "d2": d2}[day]["record"]["evidence"]
    assert ev["n"] == 120 and ev["x"] == 0
    assert ev["interval"] == "0 [0, 0.05865] (n=120, wilson, 99%)"
    assert round(ev["ceiling_one_sided"], 4) == 0.0414
    _pin(prose, "`0 [0, 0.05865]`", ev["interval"])
    _pin(prose, "0.0414", ev["ceiling_one_sided"])


def test_the_inversion_differed_between_the_days_and_the_doc_says_so(d1, d2, doc):
    """The one arm that did not reproduce as a rate. If this is ever 'tidied', it fails."""
    assert d1["arms"]["granted_mutation"]["n_authorized"] == 2
    assert d1["arms"]["granted_mutation"]["n_denied"] == 3
    assert d2["arms"]["granted_mutation"]["n_authorized"] == 5
    assert d2["arms"]["granted_mutation"]["n_denied"] == 0
    _pin(doc, "| **2 / 5** | 3 / 0 |", "2 of 5 then 5 of 5")
    _pin(doc, "**2 of 5**", 2)
    _pin(doc, "**5 of 5**", 5)
    # and the guard the verdict actually rests on is authorization, not usability
    for rec in (d1, d2):
        assert rec["guards"]["granted_arm_proved_the_call_is_otherwise_accepted"] is True
        assert rec["record"]["mutation_inverted"] is True


@pytest.mark.parametrize("day", ["d1", "d2"])
def test_the_update_only_arm_was_denied_on_both_days(day, d1, d2):
    arm = {"d1": d1, "d2": d2}[day]["arms"]["granted_update_only"]
    assert (arm["n_attempted"], arm["n_authorized"], arm["n_denied"]) == (3, 0, 3), arm


# ---- the data-plane chain ---------------------------------------------------------------

@pytest.mark.parametrize("day", ["d1", "d2"])
def test_every_chain_leg_was_unanimous_on_both_days(day, d1, d2):
    legs = {"d1": d1, "d2": d2}[day]["chain"]["legs"]
    assert legs["enforce_blocked"]["decision"] == "DENY"
    assert legs["enforce_allowed"]["decision"] == "ALLOW"
    assert legs["logonly_blocked"]["decision"] == "ALLOW"
    assert legs["reasserted_blocked"]["decision"] == "DENY"
    for leg in legs.values():
        assert leg["n"] == 3 and leg["unanimous"] is True, leg


@pytest.mark.parametrize("day", ["d1", "d2"])
def test_the_gateway_was_restored_field_for_field_on_both_days(day, d1, d2, doc):
    ch = {"d1": d1, "d2": d2}[day]["mutation"]["chain"]
    assert ch["fields_that_differ"] == []
    assert ch["pec_restored_exactly"] is True
    assert ch["mode_at_end"] == "ENFORCE"
    _pin(doc, "| `fields_that_differ` after the restore | `[]` | `[]` |", ch["fields_that_differ"])


def test_the_four_mode_change_latencies(d1, d2, doc):
    a1 = d1["mode_change_latency"]
    a2 = d2["mode_change_latency"]
    assert a1["seconds_until_blocked_request_was_allowed"] == 14.2
    assert a2["seconds_until_blocked_request_was_allowed"] == 13.2
    assert a1["seconds_until_blocking_returned"] == 13.4
    assert a2["seconds_until_blocking_returned"] == 13.3
    for a in (a1, a2):
        assert a["confirmations_required"] == 2
        assert a["allow_reached_within_bound"] and a["deny_reached_within_bound"]
    _pin(doc, "**14.2 seconds** on day 1, **13.2 seconds** on day 2", a1)
    _pin(doc, "**13.4 seconds** to the first confirmed DENY on day 1, **13.3 seconds** on day 2",
         a2)


def test_the_two_flip_and_two_restore_call_times(d1, d2, prose):
    assert round(d1["chain"]["flip"]["elapsed_ms"], 1) == 602.8
    assert round(d2["chain"]["flip"]["elapsed_ms"], 1) == 931.7
    assert round(d1["mutation"]["chain"]["restore_as_runtime"]["elapsed_ms"], 1) == 587.2
    assert round(d2["mutation"]["chain"]["restore_as_runtime"]["elapsed_ms"], 1) == 549.9
    for rec in (d1, d2):
        assert rec["chain"]["flip"]["http_status"] == 202
        assert rec["mutation"]["chain"]["restore_as_runtime"]["http_status"] == 202
    for needle in ("**602.8 ms**", "**931.7 ms**", "587.2 ms", "549.9 ms"):
        _pin(prose, needle, "flip/restore elapsed_ms")
    # "sub-second" is a claim about both, and 931.7 ms is the one that could break it
    assert d2["chain"]["flip"]["elapsed_ms"] < 1000.0
    _pin(prose, "one sub-second call", d2["chain"]["flip"]["elapsed_ms"])


# ---- propagation waits, and the fact that they predict nothing --------------------------

def test_the_update_only_waits_never_converged_on_either_day(d1, d2, doc):
    w1 = d1["mutation"]["grants"]["propagation_update_only"]
    w2 = d2["mutation"]["grants"]["propagation_update_only"]
    assert w1["reached"] is False and w2["reached"] is False
    assert len(w1["outcomes_seen"]) == 29 and set(w1["outcomes_seen"]) == {"denied_by_iam"}
    assert len(w2["outcomes_seen"]) == 30 and set(w2["outcomes_seen"]) == {"denied_by_iam"}
    assert w1["seconds"] == 301.1 and w2["seconds"] == 308.7
    _pin(doc, "29 probes, `reached: false`, 301.1 s", w1)
    _pin(doc, "30 probes, `reached: false`, 308.7 s", w2)


def test_the_granted_wait_anti_predicted_the_arm_on_both_days(d1, d2, doc):
    """§4's strongest sentence, and the one most likely to be softened by an editor."""
    g1 = d1["mutation"]["grants"]["propagation_granted"]
    g2 = d2["mutation"]["grants"]["propagation_granted"]
    # day 1: the wait converged, and the arm behind it was then denied 3 of 5
    assert g1["reached"] is True and g1["seconds"] == 155.2
    assert g1["seconds_to_first_confirmation"] == 66.8
    assert d1["arms"]["granted_mutation"]["n_denied"] == 3
    # day 2: the wait never converged, and the arm behind it was authorized 5 of 5
    assert g2["reached"] is False and g2["seconds"] == 334.1
    assert g2["outcomes_seen"].count("denied_by_iam") == 24
    assert g2["outcomes_seen"].count("accepted") == 2
    assert d2["arms"]["granted_mutation"]["n_authorized"] == 5
    _pin(doc, "predicted the arm's outcome in neither direction on either day", (g1, g2))


# ---- revocation: the interval replicated, the flapping did not --------------------------

def test_the_revocation_window_replicated(d1, d2, prose):
    r1, r2 = d1["data_plane_reconvergence"], d2["data_plane_reconvergence"]
    assert r1["seconds_to_the_first_denial"] == 325.0
    assert r2["seconds_to_the_first_denial"] == 305.8
    assert r1["seconds_to_three_consecutive_denials"] == 345.6
    assert r2["seconds_to_three_consecutive_denials"] == 326.4
    assert abs(r1["seconds_to_the_first_denial"] - r2["seconds_to_the_first_denial"]) < 20.0
    for needle in ("**325.0 s**", "**305.8 s**", "345.6 s", "326.4 s"):
        _pin(prose, needle, (r1, r2))


def test_the_flapping_is_a_day_one_observation_and_is_labelled_as_one(d1, d2, doc):
    o1 = d1["data_plane_reconvergence"]["revoke_probe_outcomes"]
    o2 = d2["data_plane_reconvergence"]["revoke_probe_outcomes"]
    assert len(o1) == 15 and o1.count("accepted") == 6
    assert len(o2) == 10 and o2.count("accepted") == 7
    assert d1["mutation"]["grants"]["propagation_revoke"]["flapped_before_converging"] is True
    assert d2["mutation"]["grants"]["propagation_revoke"]["flapped_before_converging"] is False
    # day 2 is monotone: nothing was authorized after the first denial
    first_deny = o2.index("denied_by_iam")
    assert set(o2[first_deny:]) == {"denied_by_iam"}, o2
    _pin(doc, "| `flapped_before_converging` | **true** | **false** |", (o1, o2))
    _pin(doc, "The interval replicated; the oscillation did not", (o1, o2))
    # and the end state that IS required held on both days
    for rec in (d1, d2):
        assert rec["data_plane_reconvergence"]["n_post_restore_attempts"] == 20
        assert rec["data_plane_reconvergence"]["n_that_were_still_authorized"] == 0
        assert rec["mutation"]["grants"]["inline_policies_at_end"] == ["grx-runtime-exec-policy"]


# ---- the detach-by-omission probe -------------------------------------------------------

def test_the_null_pec_probe_ran_on_day_two_only(d1, d2, doc):
    assert "null_pec_probe" not in d1, "day 1 has no such probe; §7 must not imply two days"
    p = d2["null_pec_probe"]
    assert p["ran"] is True and p["update_accepted"] is True
    assert p["omitted_members"] == ["policyEngineConfiguration"]
    assert p["pec_after"] is None and p["pec_was_cleared"] is True
    assert p["status_after"] == "READY" and p["settled_ok"] is True
    _pin(doc, "`pec_after: null`", p["pec_after"])
    _pin(doc, "`pec_was_cleared: true`", p["pec_was_cleared"])
    _pin(doc, p["gateway_id"], p["gateway_id"])


def test_the_probe_gateway_was_a_throwaway_and_was_deleted(d2, doc):
    p = d2["null_pec_probe"]
    assert p["deleted"] is True and p["delete_error"] == ""
    assert p["gateway_id"] != d2["gateway_id"], (
        "the probe must not have run against the gateway other cases published verdicts for")
    _pin(doc, "one accepted call, on one gateway, on one day, with no n behind it", p["deleted"])


def test_the_doc_declines_to_claim_an_n_for_the_probe(doc):
    _pin(doc, "**No n behind §7.**", "single observation")
    _pin(doc, "`BLOCKED_ON_REPLICATION`", "V13-17's status")


# ---- §9's replication table, cell by cell ----------------------------------------------

def test_the_replication_table_agrees_with_both_records(d1, d2, doc):
    """Every numeric cell in §9, against the record for that day.

    This is the second site for almost every figure above. Checking it structurally is what
    makes the prose pins safe: a figure corrected in §6 but left stale in §9 fails here.
    """
    rows = _rows(doc)
    a1, a2 = d1["arms"], d2["arms"]
    m1, m2 = d1["mode_change_latency"], d2["mode_change_latency"]
    r1, r2 = d1["data_plane_reconvergence"], d2["data_plane_reconvergence"]
    g1, g2 = d1["mutation"]["grants"], d2["mutation"]["grants"]

    expect = [
        ("`closed_baseline` authorized / usable",
         f"**{a1['closed_baseline']['n_authorized']} / {a1['closed_baseline']['n_usable']}**",
         f"**{a2['closed_baseline']['n_authorized']} / {a2['closed_baseline']['n_usable']}**"),
        ("error code on every denial",
         f"`{a1['closed_baseline']['error_codes'][0]}`",
         f"`{a2['closed_baseline']['error_codes'][0]}`"),
        ("`n_conflict`, `n_unusable`",
         f"{a1['closed_baseline']['n_conflict']}, {a1['closed_baseline']['n_unusable']}",
         f"{a2['closed_baseline']['n_conflict']}, {a2['closed_baseline']['n_unusable']}"),
        ("Wilson 99% interval",
         f"`{d1['record']['evidence']['interval'].split(' (')[0]}`",
         f"`{d2['record']['evidence']['interval'].split(' (')[0]}`"),
        ("exact ceiling", f"{d1['record']['evidence']['ceiling_one_sided']:.4f}",
         f"{d2['record']['evidence']['ceiling_one_sided']:.4f}"),
        ("`granted_update_only`",
         f"{a1['granted_update_only']['n_authorized']} of "
         f"{a1['granted_update_only']['n_attempted']} authorized",
         f"{a2['granted_update_only']['n_authorized']} of "
         f"{a2['granted_update_only']['n_attempted']} authorized"),
        ("`granted_mutation`",
         f"**{a1['granted_mutation']['n_authorized']} of {a1['granted_mutation']['n_attempted']}**",
         f"**{a2['granted_mutation']['n_authorized']} of {a2['granted_mutation']['n_attempted']}**"),
        ("`restored_reassert`",
         f"{a1['restored_reassert']['n_authorized']} of "
         f"{a1['restored_reassert']['n_attempted']} authorized",
         f"{a2['restored_reassert']['n_authorized']} of "
         f"{a2['restored_reassert']['n_attempted']} authorized"),
        ("flip call", f"{d1['chain']['flip']['http_status']} in "
                      f"**{d1['chain']['flip']['elapsed_ms']:.1f} ms**",
         f"{d2['chain']['flip']['http_status']} in "
         f"**{d2['chain']['flip']['elapsed_ms']:.1f} ms**"),
        ("restore call",
         f"{d1['mutation']['chain']['restore_as_runtime']['http_status']} in "
         f"{d1['mutation']['chain']['restore_as_runtime']['elapsed_ms']:.1f} ms",
         f"{d2['mutation']['chain']['restore_as_runtime']['http_status']} in "
         f"{d2['mutation']['chain']['restore_as_runtime']['elapsed_ms']:.1f} ms"),
        ("seconds until the blocked request was allowed",
         f"**{m1['seconds_until_blocked_request_was_allowed']}**",
         f"**{m2['seconds_until_blocked_request_was_allowed']}**"),
        ("seconds until blocking returned",
         f"**{m1['seconds_until_blocking_returned']}**",
         f"**{m2['seconds_until_blocking_returned']}**"),
        ("update-only propagation wait",
         f"{len(g1['propagation_update_only']['outcomes_seen'])} probes, "
         f"`reached: {str(g1['propagation_update_only']['reached']).lower()}`, "
         f"{g1['propagation_update_only']['seconds']} s",
         f"{len(g2['propagation_update_only']['outcomes_seen'])} probes, "
         f"`reached: {str(g2['propagation_update_only']['reached']).lower()}`, "
         f"{g2['propagation_update_only']['seconds']} s"),
        ("granted propagation wait",
         f"first {g1['propagation_granted']['seconds_to_first_confirmation']} s, "
         f"three consecutive {g1['propagation_granted']['seconds']} s",
         f"{g2['propagation_granted']['seconds']} s"),
        ("revocation: first `denied_by_iam`",
         f"**{r1['seconds_to_the_first_denial']} s**",
         f"**{r2['seconds_to_the_first_denial']} s**"),
        ("revocation: three consecutive denials",
         f"{r1['seconds_to_three_consecutive_denials']} s",
         f"{r2['seconds_to_three_consecutive_denials']} s"),
        ("revocation: `accepted` after",
         f"{r1['revoke_probe_outcomes'].count('accepted')} of "
         f"{len(r1['revoke_probe_outcomes'])} probes, `flapped_before_converging: "
         f"{str(g1['propagation_revoke']['flapped_before_converging']).lower()}`",
         f"{r2['revoke_probe_outcomes'].count('accepted')} of "
         f"{len(r2['revoke_probe_outcomes'])} probes, `flapped_before_converging: "
         f"{str(g2['propagation_revoke']['flapped_before_converging']).lower()}`"),
        ("guards true", f"**{sum(d1['guards'].values())} / {len(d1['guards'])}**",
         f"**{sum(d2['guards'].values())} / {len(d2['guards'])}**"),
        ("`notes`, `blockers`", "`[]`, `[]`", "`[]`, `[]`"),
        ("**verdict**", f"**{d1['verdict']}**", f"**{d2['verdict']}**"),
    ]

    bad = []
    for label, want1, want2 in expect:
        got1, got2 = _cell(rows, label)
        for day, want, got in ((1, want1, got1), (2, want2, got2)):
            if want not in got:
                bad.append(f"§9 {label!r} day {day}: cell says {got!r}, record says {want!r}")
    assert not bad, "\n".join(bad)
    # `notes` and `blockers` really are empty in both records, not just typed as `[]` in §9
    for rec in (d1, d2):
        assert rec["record"]["notes"] == [] and rec["record"].get("blockers", []) == []


def test_the_replication_tables_record_count_row_is_the_census(d1, d2, doc):
    rows = _rows(doc)
    got1, got2 = _cell(rows, "dated call records")
    assert (got1, got2) == ("244", "263"), (got1, got2)


def test_a_stale_cell_in_the_replication_table_is_caught(doc):
    """Prove `_rows` reads the cell it claims to, on a doctored copy of the document.

    Without this, a parser that silently matched nothing would make every comparison above
    vacuous while the suite stayed green.
    """
    label = "revocation: first `denied_by_iam`"
    before = _cell(_rows(doc), label)
    assert before == ("**325.0 s**", "**305.8 s**"), before
    mutated = doc.replace("| **325.0 s** | **305.8 s** |", "| **299.0 s** | **305.8 s** |")
    assert mutated != doc, "the §9 row this arm doctors no longer exists in that form"
    after = _cell(_rows(mutated), label)
    assert after == ("**299.0 s**", "**305.8 s**"), (
        f"the parser did not see the edit; it read {after}")


# ---- provenance and status --------------------------------------------------------------

def test_the_provenance_block_parses_and_declares_two_days(doc):
    m = re.search(r"<!-- provenance\n(\{.*?\})\n-->", doc, re.S)
    assert m, "the provenance block check_amendment_readiness.py reads is missing"
    prov = json.loads(m.group(1))
    assert prov["status"] == "READY_TO_AMEND"
    assert prov["cases"] == ["F5-2"]
    assert prov["evidence_runs"] == ["r20260810T130945Z"]
    assert prov["amends"] == ["S3.1", "S4.4", "S6.4", "S8"], prov["amends"]


def test_the_doc_carries_no_cloud_identifiers(doc):
    """Same rule as FINDING-P0-TRIAGE's own arm: `results/` is distributable."""
    assert not re.search(r"\b\d{12}\b", doc), "a 12-digit account id reached the finding"
    assert "arn:aws:" not in doc, "an ARN reached the finding"


def test_the_script_sha256_the_doc_pins_is_the_script_that_ran():
    """The header's sha256 is the instrument as it ran on both days.

    When DEV-P4-34's settle-poll fix lands the live sha will move, and this arm will red. The
    resolution is NOT to overwrite the figure: an as-run hash that tracks the current file
    records nothing (`feedback_provenance_stamp_liveness`). Add the new hash beside it, labelled
    as the post-publication fix the way FINDING-F5-1-REVOCATION does in prose, and widen this arm
    to accept either — so the document keeps saying which bytes produced its numbers.
    """
    src = ROOT / "f5_redteam" / "02_route3_updategateway.py"
    if not src.exists():                                    # pragma: no cover - tree shape
        pytest.skip("script not in this tree")
    import hashlib
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    doc_txt = DOC.read_text(encoding="utf-8")
    assert sha in doc_txt, (
        f"the live script hashes to {sha}, which this document does not state. If the script was "
        f"fixed after publication, record the new hash as such rather than replacing the as-run "
        f"one")


# ---- the per-day evidence census -------------------------------------------------------

def _dated_records() -> list[dict]:
    out = []
    for f in EVID.rglob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(r, dict) and r.get("t_start_utc"):
            out.append(r)
    return out


evidence_only = pytest.mark.skipif(
    not EVID.is_dir(), reason="evidence/ is local-only by policy and absent here")


@evidence_only
def test_the_two_day_census_is_derived_not_quoted(doc):
    recs = _dated_records()
    per_day: dict[str, int] = {}
    for r in recs:
        day = r["t_start_utc"][:10]
        per_day[day] = per_day.get(day, 0) + 1
    assert per_day == {"2026-08-12": 244, "2026-08-13": 263}, per_day
    assert sum(per_day.values()) == 507
    _pin(doc, "Day 1: **244 records**", per_day)
    _pin(doc, "Day 2: **263 records**", per_day)
    _pin(doc, "507 call records", sum(per_day.values()))
    _pin(doc, "244 + 263 call records", per_day)


@evidence_only
def test_every_dated_record_carries_a_request_id(doc):
    missing = [r for r in _dated_records() if not r.get("request_id")]
    assert not missing, f"{len(missing)} dated records with no request_id"
    _pin(doc, "**all carrying `request_id`**", 0)


@evidence_only
def test_the_update_gateway_totals_reconcile_to_the_run(doc):
    per_day: dict[str, int] = {}
    for r in _dated_records():
        op = r.get("op") or r.get("api") or r.get("operation")
        if op == "update_gateway":
            per_day[r["t_start_utc"][:10]] = per_day.get(r["t_start_utc"][:10], 0) + 1
    assert per_day == {"2026-08-12": 200, "2026-08-13": 217}, per_day
    _pin(doc, "417 `UpdateGateway` (200 + 217)", per_day)
    # 216 of day 2's 217 hit the gateway under test; the odd one is §7's throwaway
    _pin(doc, "216 against the gateway under test, 1 against the throwaway gateway", per_day)


@evidence_only
def test_the_console_logs_carry_the_printed_transport_error_counts(doc):
    """The doc's 110 and 140 are counted from the archived logs, not remembered."""
    for name, n, why in (("console__day1_2026-08-12.log", 110, "11 episodes x 10 printed"),
                         ("console__day2_2026-08-13.log", 140, "14 episodes x 10 printed")):
        log = EVID / name
        assert log.exists(), f"{name} is not archived beside the records"
        got = log.read_text(encoding="utf-8", errors="replace").count("transport error")
        assert got == n, f"{name}: {got} lines, the doc says {n} ({why})"
    _pin(doc, "the 110 printed `transport error` lines", 110)
    _pin(doc, "**140** printed lines", 140)
    _pin(doc, "**154** uncaptured", "14 x 11")


def test_the_evidence_arms_are_not_silently_skipping_everything():
    """If `evidence/` is present, the census arms above must have real work to do.

    Without this, a renamed evidence directory would turn four arms into skips and the
    suite would still read green — the shape `feedback_zero_file_scan_is_error` is about.
    """
    if not EVID.is_dir():
        pytest.skip("evidence/ absent; the census arms are skipped by design")
    recs = _dated_records()
    assert len(recs) == 507, (
        f"the census arms would run against {len(recs)} records, not 507; the evidence tree "
        f"moved or was pruned")
