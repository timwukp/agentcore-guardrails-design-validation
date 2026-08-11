"""Mutation tests for estimate_cost.py and cost_model.yaml.

The plan specifies a script that "refuses to run if the projection exceeds the
pre-registered ceiling". Two things were wrong with that as built: there was no script,
and there was no machine-readable ceiling -- the $55-95 figure lived only in the plan's
prose. So the tests here have to prove three refusals actually fire, not just that a
number gets printed:

1. over ceiling
2. unverified price (a projection whose inputs nobody looked up cannot certify itself)
3. unfunded replication -- a phase that may amend the document while declaring one day

(3) is the one that ties money to validity, and it is the reason this file sits beside
test_amendment_gate.py rather than in a costing corner of its own.

Also pinned: that the report is GENERATED. A COST.md with a hand-typed total is the
prose-is-not-verified defect wearing a table.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "estimate_cost.py"
MODEL = ROOT / "cost_model.yaml"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    dst = tmp_path / "repo"
    dst.mkdir()
    shutil.copy2(SCRIPT, dst / SCRIPT.name)
    shutil.copy2(MODEL, dst / MODEL.name)
    shutil.copy2(ROOT / "PREREGISTRATION.yaml", dst / "PREREGISTRATION.yaml")
    return dst


def run(tree: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(tree / SCRIPT.name), *args],
                          capture_output=True, text=True, cwd=tree)


def load(tree: Path) -> dict:
    return yaml.safe_load((tree / MODEL.name).read_text(encoding="utf-8"))


def dump(tree: Path, model: dict) -> None:
    (tree / MODEL.name).write_text(yaml.safe_dump(model, sort_keys=False),
                                   encoding="utf-8")


def kills(res: subprocess.CompletedProcess, needle: str, rc: int = 1) -> None:
    assert res.returncode == rc, (
        f"expected rc={rc}, got {res.returncode}\nstdout:\n{res.stdout}\n"
        f"stderr:\n{res.stderr}")
    assert needle in res.stderr, (
        f"killed, but not by the intended check — {needle!r} absent from:\n{res.stderr}")


# --------------------------------------------------------------------------- controls

def test_control_arm_the_unmutated_model_authorises(tree: Path) -> None:
    res = run(tree)
    assert res.returncode == 0, f"the real model must authorise:\n{res.stderr}"
    assert "AUTHORISED" in res.stdout


def test_control_arm_every_live_phase_is_individually_authorisable(tree: Path) -> None:
    """A green total must not hide a phase that could not be run.

    --authorise narrows the checks to one phase, so this also proves the narrowing
    does not accidentally skip them: an empty `scope` would pass everything.
    """
    model = load(tree)
    live = [p["id"] for p in model["phases"] if p["live"]]
    assert len(live) >= 8, f"only {len(live)} live phases — the model has shrunk"
    for pid in live:
        res = run(tree, "--authorise", pid)
        assert res.returncode == 0, f"phase {pid} is not authorisable:\n{res.stderr}"


def test_an_unknown_phase_is_not_silently_authorised(tree: Path) -> None:
    kills(run(tree, "--authorise", "42"), "no phase with id")


# ------------------------------------------------------------------ refusal 1: ceiling

def test_kills_a_projection_over_the_ceiling(tree: Path) -> None:
    model = load(tree)
    model["meta"]["ceiling_usd"] = 1.0
    dump(tree, model)
    kills(run(tree), "exceeds the ceiling")


def test_kills_a_ceiling_that_only_holds_if_nothing_goes_wrong(tree: Path) -> None:
    """projection + fully-drawn contingency must also fit.

    Without this arm a model could sit at $94 with $50 of contingency and report
    "within ceiling" — true only on the assumption that nothing triggers, which is not
    what a ceiling means.
    """
    model = load(tree)
    model["meta"]["ceiling_usd"] = 20.0        # above the $6.67 projection, below +$29
    dump(tree, model)
    res = run(tree)
    kills(res, "fully-drawn contingency")
    assert "not a ceiling" in res.stderr


def test_a_bigger_quantity_moves_the_projection(tree: Path) -> None:
    """Guards against a projection that ignores the model — the vacuous case.

    If project() returned a constant, every arm above would still pass: the ceiling
    arms mutate the ceiling, not the cost. This one mutates the cost.
    """
    before = float(re.search(r"projection \$([\d.]+)", run(tree).stdout).group(1))
    model = load(tree)
    for ph in model["phases"]:
        if ph["id"] == "6":
            for item in ph["items"]:
                if item["price"] == "guardrail_text_unit":
                    item["qty"] = int(item["qty"]) * 100
    dump(tree, model)
    after = float(re.search(r"projection \$([\d.]+)", run(tree).stdout).group(1))
    assert after > before * 10, (
        f"100x-ing the dominant guardrail line moved the projection only "
        f"${before:.2f} -> ${after:.2f}; the projection is not reading the quantities")


# ------------------------------------------------------------------- refusal 2: prices

def test_kills_a_live_phase_depending_on_an_unverified_price(tree: Path) -> None:
    model = load(tree)
    model["prices"]["guardrail_text_unit"]["verified"] = False
    dump(tree, model)
    res = run(tree, "--authorise", "6")
    kills(res, "unverified price")
    assert "run --verify-prices" in res.stderr


def test_an_unverified_price_does_not_block_an_offline_phase(tree: Path) -> None:
    """Phase 9 is offline and buys nothing; the refusal must be targeted.

    A gate that fires where it should not is one people learn to bypass, so this is
    load-bearing rather than a nicety.
    """
    model = load(tree)
    model["prices"]["guardrail_text_unit"]["verified"] = False
    dump(tree, model)
    assert run(tree, "--authorise", "9").returncode == 0


def test_kills_a_declared_total_that_disagrees_with_the_items(tree: Path) -> None:
    """A hand-typed phase total must be caught by the computed one.

    This is the money version of label-must-match-computation: a figure in the model
    that no longer follows from the line items.
    """
    model = load(tree)
    for ph in model["phases"]:
        if ph["id"] == "6":
            ph["projected_usd"] = 99.0
    dump(tree, model)
    kills(run(tree), "but the items compute to")


def test_kills_an_unknown_price_reference(tree: Path) -> None:
    """A typo'd price name must be fatal, not silently worth $0."""
    model = load(tree)
    for ph in model["phases"]:
        if ph["id"] == "6":
            ph["items"][0]["price"] = "guardrail_text_unti"
    dump(tree, model)
    kills(run(tree), "unknown price", rc=2)


def test_every_nonzero_price_names_a_pricing_api_usagetype(tree: Path) -> None:
    """`verified: true` must mean a specific lookup, not "a number was fetched".

    Checked against the real model, not a mutant: this is a property the artefact must
    have, and a lookup pointed at the wrong usagetype stamps a guess as confirmed.
    """
    model = load(tree)
    for name, p in model["prices"].items():
        if float(p["usd"]) == 0:
            continue
        assert p.get("verified") is True, f"{name} is priced but unverified"
        api = p.get("pricing_api")
        assert api and api.get("service_code") and api.get("usagetype"), (
            f"{name} claims verified: true but names no pricing_api usagetype, so "
            f"nothing can re-derive it")


# -------------------------------------------------------------- refusal 3: replication

def test_kills_an_amending_phase_that_declares_one_day(tree: Path) -> None:
    """THE arm this file exists for: money spent on evidence that cannot be used.

    Phase 6 replaces §6.1's ILLUSTRATIVE table — the headline amendment. Declared at
    one day, its $3.55 buys an observation that check_amendment_readiness.py will
    refuse to let into the document.
    """
    model = load(tree)
    for ph in model["phases"]:
        if ph["id"] == "6":
            ph["days"] = 1
    dump(tree, model)
    res = run(tree, "--authorise", "6")
    kills(res, "the sealed rule requires >= 2")
    assert "would buy an observation and not a finding" in res.stderr


def test_kills_a_phase_replicated_for_no_stated_reason(tree: Path) -> None:
    """The converse: days >= 2 with no `amends:` target.

    Without this, padding the schedule would be free and undocumented. 5c is the case
    that matters — it is deliberately single-day because it is the highest-blast-radius
    action in the project, and that decision has to be visible rather than incidental.
    """
    model = load(tree)
    for ph in model["phases"]:
        if ph["id"] == "5c":
            ph["days"] = 2
    dump(tree, model)
    kills(run(tree, "--authorise", "5c"), "names no `amends:` targets")


def test_the_replication_threshold_comes_from_the_sealed_prereg(tree: Path) -> None:
    """Relaxing the sealed rule must break the script, not license a cheaper schedule.

    Otherwise the cheapest way to fund a one-day Phase 6 would be to edit the YAML,
    which is precisely the substitution the pre-registration exists to prevent.
    """
    p = tree / "PREREGISTRATION.yaml"
    p.write_text(p.read_text(encoding="utf-8")
                 .replace(">= 2 separate calendar days", ">= 1 separate calendar days"),
                 encoding="utf-8")
    kills(run(tree), "this script\nenforces".replace("\n", " "))


def test_a_deleted_rule_does_not_disable_the_replication_check(tree: Path) -> None:
    p = tree / "PREREGISTRATION.yaml"
    p.write_text(p.read_text(encoding="utf-8")
                 .replace("reproduction_before_amendment:",
                          "reproduction_before_amendment_GONE:"),
                 encoding="utf-8")
    kills(run(tree), "no longer seals")


def test_every_phase_agrees_with_the_amendment_gate_vocabulary(tree: Path) -> None:
    """`amends:` targets must look like document sections, not free text.

    A typo'd target is invisible otherwise: the phase still counts as amending, so the
    day requirement still binds, but the trace back to the document is broken and
    Phase 9 cannot use it to find the merge-group sites.
    """
    model = load(tree)
    ok = re.compile(r"^(S\d+(\.\d+)*|Appendix[A-C]|DC-\d+)$")
    for ph in model["phases"]:
        for target in ph.get("amends") or []:
            assert ok.match(target), (
                f"phase {ph['id']} names amendment target {target!r}, which is not a "
                f"section reference (S6.1, AppendixB, DC-1)")


# --------------------------------------------------------- absence must not read as pass

def test_a_missing_model_is_rc2_not_a_pass(tree: Path) -> None:
    (tree / MODEL.name).unlink()
    kills(run(tree), "not the same as being within ceiling", rc=2)


def test_a_missing_prereg_is_rc2_not_a_pass(tree: Path) -> None:
    (tree / "PREREGISTRATION.yaml").unlink()
    kills(run(tree), "cannot be confirmed", rc=2)


# ------------------------------------------------------------------- the report is real

def test_the_report_is_generated_not_typed(tree: Path) -> None:
    """COST.md's total must follow from the model, or it is a table of prose.

    Changing a quantity and regenerating must change the report; if it does not, the
    figures in it are decorative.
    """
    run(tree, "--write-report")
    first = (tree / "COST.md").read_text(encoding="utf-8")
    total = re.search(r"\*\*projected \$([\d.]+)\*\*", first)
    assert total, "COST.md states no projected total"

    model = load(tree)
    for ph in model["phases"]:
        if ph["id"] == "6":
            for item in ph["items"]:
                if item["price"] == "guardrail_text_unit":
                    item["qty"] = int(item["qty"]) * 3
    dump(tree, model)
    run(tree, "--write-report")
    second = (tree / "COST.md").read_text(encoding="utf-8")
    assert second != first, "regenerating after a quantity change produced no diff"
    assert re.search(r"\*\*projected \$([\d.]+)\*\*", second).group(1) != total.group(1)


def test_the_committed_report_matches_the_committed_model(tree: Path) -> None:
    """COST.md in the repo must be the current output, not a stale generation.

    feedback_format_after_the_last_edit: a clean report expires on the next edit. The
    comparison is done in a scratch copy so the check cannot repair what it measures.
    """
    committed = (ROOT / "COST.md")
    assert committed.is_file(), "COST.md has not been generated"
    run(tree, "--write-report")
    assert (tree / "COST.md").read_text(encoding="utf-8") == \
        committed.read_text(encoding="utf-8"), (
            "COST.md is stale relative to cost_model.yaml — run "
            "`estimate_cost.py --write-report`")


def test_the_cost_gate_is_wired_into_verify_phase0(tree: Path) -> None:
    sh = (ROOT / "verify_phase0.sh").read_text(encoding="utf-8")
    assert "estimate_cost.py" in sh, (
        "estimate_cost.py is not invoked by verify_phase0.sh — an unrun gate is not a "
        "control")
