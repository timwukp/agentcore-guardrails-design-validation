#!/usr/bin/env python3
"""Mutation run for F5-2's figure arms — proof that they can fail.

Why this file exists
--------------------
`test_finding_f52_figures.py` publishes 33 green arms over a document whose verdict is TRUE and
which replicated on two days. That is the weakest evidence shape in the project: a suite of
`needle in doc` assertions over a document nobody edited will pass whether or not the assertions
watch anything. And the risk here is not random rot, it is *directional* — F5-2's day 2 was
cleaner than its day 1 (`granted_mutation` 2 of 5 -> 5 of 5, revocation flapping gone), so the
plausible future edit is the one that tidies the comparison toward the better day.

It earned its keep on the first run. Two mutants survived: rounding day 1's revocation window in
the **prose only**, and shrinking day 2's flip time in the **prose only**. Both survived because
every figure in this finding is stated twice — once in §3–§7 and once in §9's replication table —
so `needle in doc` was satisfied by the untouched copy while the sentence a reader actually reads
had gone stale. That is `feedback_grep_the_claim_not_the_phrasing` reproduced exactly. The fix
was the `prose` fixture (pins scoped to the half being claimed about) plus `_rows()` (§9 checked
cell by cell), and both survivors now die.

Why the live document is never touched
--------------------------------------
Each mutant is applied to a COPY in the pytest sandbox, and the arms are pointed at it with
`GRX_F52_FINDING`; `GRX_F52_ROOT` keeps them reading the real records and the real evidence tree,
read-only. `results/FINDING-F5-2.md` is opened for reading only, and its sha256 is compared at the
end of the run — so a crash, a kill -9 or a full disk cannot leave a doctored finding in the tree
to be published. An earlier version of this harness was a script in `/tmp` that mutated the live
file and restored it in a `finally:`; that is one signal away from committing its own defect, and
its result ("19 killed") was a number no one in the repository could reproduce.

Reading the table
-----------------
* `scope` — which half of the document the mutation is applied to. `prose` is everything before
  `## 9.`; `table` is §9 onward. For a figure stated in both halves the one-sided mutants are the
  interesting ones, and both directions are asserted to exist below.
* `killers` — the arm that MUST fail. A mutant killed only by some unrelated arm is not banked as
  a kill for the claim it was written against.
* `needs_evidence` — the killer arm reads `evidence/`, which is local-only by policy. Where the
  tree is absent that arm skips, so the mutant is skipped too rather than counted as surviving.

Run directly for the report:
    .venv-oracle/bin/python -m pytest f5_redteam/tests/test_finding_f52_mutation.py -q
"""

from __future__ import annotations

import hashlib
import re
import shutil
import site
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "results" / "FINDING-F5-2.md"
ARMS = Path(__file__).resolve().parent / "test_finding_f52_figures.py"
EVID = ROOT / "evidence" / "r20260810T130945Z" / "f5" / "F5-2"
SPLIT = "## 9."
TABLE_ARM = "test_the_replication_table_agrees_with_both_records"

# M15 needs a 12-digit account id to inject, and `check_redaction.py` reads this file like any
# other — a literal here fails that gate on a file whose whole purpose is to test for leaks
# (feedback_self_scanning_guard: assemble the sample, never exempt the scanner's own source by
# path). Digits 1-9 then 0,1,2, which is the shape the scanner matches.
_FAKE_ACCOUNT = "".join(str(i % 10) for i in range(1, 13))

# Taken at import, before any mutant exists, and re-checked at the end of the run.
_LIVE_SHA = hashlib.sha256(DOC.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Mutant:
    mid: str
    scope: str                        # "prose" (before §9) or "table" (§9 onward)
    target: str                       # exact substring, must appear exactly once in that half
    replacement: str
    claim: str                        # what the mutation falsifies
    killers: tuple[str, ...] = field(default=())
    needs_evidence: bool = False
    # Set on the §9-side mutant of a figure this document states twice, naming its §3-§7
    # counterpart. The pair is the unit that measures staleness in BOTH directions; the count of
    # pairs is a figure the finding itself publishes, so it is derived here rather than typed.
    pairs_with: str = ""


MUTANTS: list[Mutant] = [
    Mutant(
        "M1-inversion-tidied-to-day-2s-rate", "prose",
        "| **2 / 5** | 3 / 0 |", "| **5 / 5** | 0 / 0 |",
        "The arms table is the one place a reader sees that the mutation arm was authorized 2 of "
        "5 times on day 1. Reported as 5 of 5 on both days, the finding claims a reproducibility "
        "it does not have, and §8's refusal to publish a rate stops making sense.",
        killers=("test_the_inversion_differed_between_the_days_and_the_doc_says_so",),
    ),
    Mutant(
        "M2-revocation-window-rounded-in-the-prose-only", "prose",
        "**325.0 s**", "**320.0 s**",
        "SURVIVOR of the first run. §6 states the day-1 window; §9 tabulates it. With the pin "
        "reading the whole document, editing §6 alone left the arm green on §9's copy.",
        killers=("test_the_revocation_window_replicated",),
    ),
    Mutant(
        "M3-revocation-window-rounded-in-section-9-only", "table",
        "**325.0 s**", "**320.0 s**",
        "The same staleness in the other copy — the direction a prose-scoped pin cannot see, and "
        "why §9 is parsed cell by cell rather than grepped.",
        killers=(TABLE_ARM,),
        pairs_with="M2-revocation-window-rounded-in-the-prose-only",
    ),
    Mutant(
        "M4-oscillation-claimed-to-replicate", "prose",
        "| `flapped_before_converging` | **true** | **false** |",
        "| `flapped_before_converging` | **true** | **true** |",
        "Day 2's revocation was monotone. Claiming it flapped would make the finding assert a "
        "two-day shape for an observation that has one day behind it.",
        killers=("test_the_flapping_is_a_day_one_observation_and_is_labelled_as_one",),
    ),
    Mutant(
        "M5-oscillation-claimed-to-replicate-in-section-9-only", "table",
        "`flapped_before_converging: false`", "`flapped_before_converging: true`",
        "The §9 cell carrying the same claim.",
        killers=(TABLE_ARM,),
        pairs_with="M4-oscillation-claimed-to-replicate",
    ),
    Mutant(
        "M6-section-7-disclaimer-dropped", "prose",
        "**No n behind §7.**", "Section 7 is a measurement.",
        "§7's detach-by-omission is one accepted call on one throwaway gateway on one day. "
        "Without the disclaimer it reads as a measured result, and V13-17's "
        "`BLOCKED_ON_REPLICATION` status becomes unexplained.",
        killers=("test_the_doc_declines_to_claim_an_n_for_the_probe",),
    ),
    Mutant(
        "M7-day-1-census-inflated", "prose",
        "Day 1: **244 records**", "Day 1: **260 records**",
        "The census is the count of dated call records in the evidence tree. A quoted number "
        "that no longer counts anything is prose wearing a measurement's clothes.",
        killers=("test_the_two_day_census_is_derived_not_quoted",),
        needs_evidence=True,
    ),
    Mutant(
        "M8-day-1-census-inflated-in-section-9-only", "table",
        "| dated call records | 244 | 263 |", "| dated call records | 260 | 263 |",
        "The §9 row carrying the same count.",
        killers=("test_the_replication_tables_record_count_row_is_the_census",),
        pairs_with="M7-day-1-census-inflated",
    ),
    Mutant(
        "M9-mode-change-latency-understated", "prose",
        "**14.2 seconds** on day 1, **13.2 seconds** on day 2",
        "**4.2 seconds** on day 1, **3.2 seconds** on day 2",
        "This is the number the whole §3.1 amendment rests on: how long a reconfiguration takes "
        "to reach the data plane. Understating it by 10 seconds makes the hazard look faster "
        "than measured and would be published as V13-16's interval.",
        killers=("test_the_four_mode_change_latencies",),
    ),
    Mutant(
        "M10-mode-change-latency-understated-in-section-9-only", "table",
        "| **14.2** | **13.2** |", "| **4.2** | **3.2** |",
        "The §9 rows carrying the same two latencies.",
        killers=(TABLE_ARM,),
        pairs_with="M9-mode-change-latency-understated",
    ),
    Mutant(
        "M11-day-2-flip-shown-as-sub-500ms", "prose",
        "**931.7 ms**", "**431.7 ms**",
        "SURVIVOR of the first run, for the same reason as M2. 931.7 ms is also the figure that "
        "makes 'sub-second' true on both days; a reader checking that claim reads the prose.",
        killers=("test_the_two_flip_and_two_restore_call_times",),
    ),
    Mutant(
        "M12-day-2-flip-shown-as-sub-500ms-in-section-9-only", "table",
        "**931.7 ms**", "**431.7 ms**",
        "The §9 cell carrying the same call time.",
        killers=(TABLE_ARM,),
        pairs_with="M11-day-2-flip-shown-as-sub-500ms",
    ),
    Mutant(
        "M13-anti-prediction-softened", "prose",
        "predicted the arm's outcome in neither direction on either day",
        "was a useful but imperfect signal",
        "§4's sharpest statement: the propagation wait's verdict had no predictive power in "
        "either direction (day 1 converged then the arm was denied; day 2 never converged and "
        "the arm was authorized 5 of 5). 'Useful but imperfect' is the reading the two days "
        "specifically refute, and it is the one an operator would act on.",
        killers=("test_the_granted_wait_anti_predicted_the_arm_on_both_days",),
    ),
    Mutant(
        "M14-provenance-status-overclaimed", "prose",
        '"status": "READY_TO_AMEND"', '"status": "AMENDED"',
        "`check_amendment_readiness.py` reads this block. A finding that says AMENDED claims the "
        "document has already been changed, which no one has done.",
        killers=("test_the_provenance_block_parses_and_declares_two_days",),
    ),
    Mutant(
        "M15-account-id-leaked", "table",
        "## 11.", f"## 11. (account {_FAKE_ACCOUNT})",
        "`results/` is distributable. A 12-digit account id reaching a finding is the 2026-07-26 "
        "incident (feedback_redact_cloud_metadata), and this arm is the copy of that gate which "
        "lives with the document rather than in the push path.",
        killers=("test_the_doc_carries_no_cloud_identifiers",),
    ),
    Mutant(
        "M16-update-gateway-total-restated-as-one-day", "prose",
        "417 `UpdateGateway` (200 + 217)", "217 `UpdateGateway`",
        "DEV-P4-34's scope is 'all 417 update_gateway records'. Restated as day 2's 217, the "
        "deviation understates the instrument defect by a full day of calls.",
        killers=("test_the_update_gateway_totals_reconcile_to_the_run",),
        needs_evidence=True,
    ),
    Mutant(
        "M17-closed-arm-weakened-in-section-9", "table",
        "| `closed_baseline` authorized / usable | **0 / 120** | **0 / 120** |",
        "| `closed_baseline` authorized / usable | **0 / 120** | **0 / 118** |",
        "The pre-registered arm is n=120 by PREREGISTRATION.yaml. 118 usable would mean the "
        "planned n was not reached, which changes the interval and the ceiling — a table that "
        "can say so without any arm objecting is not checking the arm.",
        killers=(TABLE_ARM,),
    ),
    Mutant(
        "M18-ceiling-never-computed", "table",
        "| exact ceiling, α = 0.00625 | 0.0414 | 0.0414 |",
        "| exact ceiling, α = 0.00625 | 0.0414 | 0.0250 |",
        "§9 argues the interval and the ceiling 'are the same computation over the same counts'. "
        "A day-2 ceiling that differs contradicts the sentence three lines below it, and no "
        "record produced 0.0250.",
        killers=(TABLE_ARM,),
    ),
    Mutant(
        "M19-section-9-table-truncated", "table",
        "| **verdict** | **TRUE** | **TRUE** |", "",
        "Deleting a row rather than falsifying one. A comparison table that quietly loses the "
        "verdict row still renders as a replication section; the parser must notice absence, not "
        "just disagreement.",
        killers=(TABLE_ARM,),
    ),
]


# --------------------------------------------------------------------------- static checks

def _half(text: str, scope: str) -> str:
    head, sep, tail = text.partition(SPLIT)
    assert sep, "the finding no longer has a §9; every mutant's scope is undefined"
    return head if scope == "prose" else sep + tail


def test_every_mutant_target_appears_exactly_once_in_its_half():
    """A mutation that does not apply is not a survivor, and must never be banked as a kill."""
    src = DOC.read_text(encoding="utf-8")
    ids = [m.mid for m in MUTANTS]
    assert len(ids) == len(set(ids)), f"duplicate mutant ids: {ids}"
    assert {m.scope for m in MUTANTS} <= {"prose", "table"}
    bad = [(m.mid, m.scope, _half(src, m.scope).count(m.target)) for m in MUTANTS
           if _half(src, m.scope).count(m.target) != 1]
    assert not bad, (
        "these targets no longer appear exactly once in the half they are scoped to, so the "
        "mutants would not apply and their claims would be unmeasured:\n"
        + "\n".join(f"  {mid} [{scope}]: found {n}" for mid, scope, n in bad))


def test_this_harness_carries_no_literal_account_id():
    """M15's payload must be assembled, not typed — this file is scanned like any other.

    The first run of the redaction gate over this file failed on exactly that: a leak test
    holding a literal 12-digit id. The fix is the sample, not an ALLOW entry keyed to this path,
    because a scanner exemption is permanent and invisible.
    """
    assert len(_FAKE_ACCOUNT) == 12 and _FAKE_ACCOUNT.isdigit(), _FAKE_ACCOUNT
    src = Path(__file__).read_text(encoding="utf-8")
    hits = re.findall(r"(?<![\d.])\d{12}(?![\d.])", src)
    assert not hits, f"a 12-digit literal is back in this file: {hits}"
    # and the assembled payload really is what M15 injects
    m15 = next(m for m in MUTANTS if m.mid == "M15-account-id-leaked")
    assert _FAKE_ACCOUNT in m15.replacement


def test_every_named_killer_arm_exists():
    """A `killers` entry naming an arm that does not exist would assert nothing."""
    arms_src = ARMS.read_text(encoding="utf-8")
    missing = sorted({k for m in MUTANTS for k in m.killers if f"def {k}(" not in arms_src})
    assert not missing, f"named as killers but absent from {ARMS.name}: {missing}"


def test_the_pairs_are_well_formed():
    """Each `pairs_with` must name a real prose mutant, and the pair must be two-sided."""
    by_id = {m.mid: m for m in MUTANTS}
    for m in MUTANTS:
        if not m.pairs_with:
            continue
        assert m.scope == "table", f"{m.mid} carries pairs_with but edits the prose half"
        other = by_id.get(m.pairs_with)
        assert other is not None, f"{m.mid} pairs with {m.pairs_with!r}, which does not exist"
        assert other.scope == "prose", f"{m.mid} pairs with {other.mid}, also a table mutant"
        assert not other.pairs_with, "pairing must be recorded on one side only"


def test_the_finding_states_this_harnesss_own_figures():
    """The finding's header publishes this harness's results, so they are derived here.

    A mutation score quoted in a document nobody re-derives is exactly the defect DEV-P1-19
    recorded ("8 killed, 2 survived", reproducible by nothing). These three figures — the mutant
    count, the pair count, and the number of mutants in pairs — come from `MUTANTS` and must match
    the sentence a reader will read.
    """
    doc = DOC.read_text(encoding="utf-8")
    n = len(MUTANTS)
    paired = [m for m in MUTANTS if m.pairs_with]
    assert f"**{n} of {n} killed, 0 survived**" in doc, (
        f"the finding no longer states a {n}-of-{n} mutation result")
    assert f"**Ten of the {'nineteen' if n == 19 else n} mutants are five pairs**" in doc, (
        f"the finding's pair sentence no longer matches {len(paired)} pairs over {n} mutants")
    assert len(paired) == 5 and 2 * len(paired) == 10, (
        f"{len(paired)} pair(s) recorded; the finding says five")


def test_both_staleness_directions_are_covered_for_a_repeated_figure():
    """The gap that motivated this file: a figure stated twice, edited on one side.

    Two mutants must exist for the same target — one in each half — or the suite is back to
    proving only that *some* copy of the number is right.
    """
    by_target: dict[str, set[str]] = {}
    for m in MUTANTS:
        by_target.setdefault(m.target, set()).add(m.scope)
    paired = {t for t, scopes in by_target.items() if scopes == {"prose", "table"}}
    assert "**325.0 s**" in paired and "**931.7 ms**" in paired, (
        f"the two first-run survivors are no longer covered in both halves; paired: {paired}")
    assert len(paired) >= 2


# --------------------------------------------------------------------------- the run

def _staged(mutant: Mutant | None, dst_dir: Path) -> Path:
    """The finding, mutated or not, written OUTSIDE the repo."""
    src = DOC.read_text(encoding="utf-8")
    if mutant is not None:
        half = _half(src, mutant.scope)
        assert half.count(mutant.target) == 1, mutant.mid
        edited = half.replace(mutant.target, mutant.replacement, 1)
        head, sep, tail = src.partition(SPLIT)
        src = edited + sep + tail if mutant.scope == "prose" else head + edited
    dst_dir.mkdir(parents=True, exist_ok=True)
    out = dst_dir / DOC.name
    out.write_text(src, encoding="utf-8")
    return out


def _run(pytester: pytest.Pytester, monkeypatch, tmp_path: Path,
         mutant: Mutant | None) -> pytest.RunResult:
    staged = _staged(mutant, tmp_path / (mutant.mid if mutant else "control"))
    paths = [p for p in (site.getusersitepackages(), *sys.path) if p]
    monkeypatch.setenv("PYTHONPATH", ":".join(dict.fromkeys(paths)))
    monkeypatch.setenv("GRX_F52_ROOT", str(ROOT))       # real records, real evidence, read-only
    monkeypatch.setenv("GRX_F52_FINDING", str(staged))  # doctored copy
    shutil.copyfile(ARMS, pytester.path / "test_arms_under_mutation.py")
    return pytester.runpytest_subprocess("-p", "no:cacheprovider", "-q",
                                         "test_arms_under_mutation.py")


def test_control_arm_the_unmutated_copy_passes_every_arm(
        pytester: pytest.Pytester, monkeypatch, tmp_path):
    """The control. Every kill below is worthless without it.

    An unmutated COPY, reached through exactly the two environment variables the mutants use. If
    this reds, the kills are kills of the harness rather than of the mutations — the failure mode
    where a mutation run scores 19/19 against a tree in which no arm ran at all.
    """
    res = _run(pytester, monkeypatch, tmp_path, None)
    outcomes = res.parseoutcomes()
    assert outcomes.get("failed", 0) == 0, (
        f"the unmutated copy fails {outcomes.get('failed')} arm(s); the harness is broken, not "
        f"the finding")
    assert outcomes.get("error", 0) == 0, outcomes
    assert outcomes.get("passed", 0) >= 29, outcomes
    # `evidence/` is local-only, so the four census arms run here and skip on the runner. Pinned
    # either way, so a future reader is not left thinking a skipped arm contributed a kill.
    expected_skips = 0 if EVID.is_dir() else 4
    assert outcomes.get("skipped", 0) == expected_skips, (
        f"expected {expected_skips} skip(s) with evidence {'present' if EVID.is_dir() else 'absent'}"
        f", got {outcomes}")
    # The finding's header publishes this arm count. Derived from the control run rather than
    # typed, so it cannot go stale in the document while the suite grows or shrinks.
    collected = outcomes.get("passed", 0) + outcomes.get("skipped", 0)
    assert f"**{collected} arms**" in DOC.read_text(encoding="utf-8"), (
        f"the control run collected {collected} arms; the finding states a different number")


@pytest.mark.parametrize("mutant", MUTANTS, ids=[m.mid for m in MUTANTS])
def test_each_mutant_is_killed_by_the_arm_written_for_it(
        mutant: Mutant, pytester: pytest.Pytester, monkeypatch, tmp_path):
    if mutant.needs_evidence and not EVID.is_dir():
        pytest.skip(f"{mutant.mid}'s killer arm reads evidence/, which is absent here; a skipped "
                    f"killer would report this mutant as a survivor for the wrong reason")
    res = _run(pytester, monkeypatch, tmp_path, mutant)
    outcomes = res.parseoutcomes()
    failed = outcomes.get("failed", 0) + outcomes.get("error", 0)
    assert failed, (
        f"{mutant.mid} SURVIVED — every arm passed with this defect in the document.\n"
        f"  what it breaks: {mutant.claim}\n"
        f"  add an arm that fails under it; do not relax the mutation.")
    for arm in mutant.killers:
        res.stdout.fnmatch_lines([f"*{arm}*"])


def test_the_live_finding_was_never_modified():
    """The safety argument, discharged rather than promised. Ordered last by definition order."""
    assert hashlib.sha256(DOC.read_bytes()).hexdigest() == _LIVE_SHA, (
        "results/FINDING-F5-2.md changed during the mutation run. Every mutant is applied to a "
        "copy, so this can only mean the harness wrote into the tree.")
