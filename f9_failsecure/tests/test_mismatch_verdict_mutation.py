#!/usr/bin/env python3
"""Mutation run for F9-2's emitter — proof that its arms can fail.

Why this file exists
--------------------
`test_mismatch_verdict.py` publishes 31 green arms over a script whose verdict is TRUE. A
green suite over a TRUE is the weakest evidence in the project: every guard could be a no-op
and the output would look identical. Two real bugs were caught DURING development by the
script's own refusals (the offset comparison and the baseline interval), and an arm written
after a bug is worth nothing until it is shown to fail without the fix.

It earned its keep through `M12-sum-accumulates-across-reads` — reading one firing twice and
adding the two Sums, so 20 mismatches from 20 requests would be published as 40. Writing the
mutant exposed that no arm asserted an episode's MAGNITUDE at all; the two `== 20.0`
assertions in `test_two_reads_of_one_firing_are_one_episode_not_two` and in the real-evidence
arm were added for it. That gap was measured rather than argued: with those four assertions
removed and M12 in place, the arms file reports **29 passed, 2 skipped, 0 failed** — the
mutant survives untouched. (Recorded here because a counterfactual stated in prose is
unchecked; this one was run.)

Why the live script is never touched
------------------------------------
Each mutant is applied to a COPY in the pytest sandbox and the arms file is pointed at it with
`GRX_F92_SCRIPT`. The real script is opened read-only, and its sha256 is compared at the end of
the run — so a crash, a kill -9 or a full disk cannot leave a deliberately broken emitter in the
tree. This mirrors `lib/tests/test_write_guard_mutation.py`'s `GRX_CONFTEST` mechanism, for the
same reason it was written there: a mutation harness that edits the tree in place is one signal
away from committing its own defect.

What the sandbox cannot cover
-----------------------------
The mutant copy lives outside the repo, so the script's own `ROOT` points at the sandbox and
the two arms that read the real archived evidence SKIP. Every kill below is therefore made by
a fixture arm. That is asserted rather than assumed (`test_control_arm_...` pins the skip
count), because "the real-evidence arm would have caught it" is exactly the kind of credit a
mutation table must not take on trust.

Reading the table
-----------------
* `Mutant` — a real defect. Surviving is a test-suite gap and this file fails, naming it.
* `killers` — the arm that MUST fail. A mutant killed only by some unrelated arm is not banked
  as a kill for the claim it was written against.

Run directly for the report:
    .venv-oracle/bin/python -m pytest f9_failsecure/tests/test_mismatch_verdict_mutation.py -q
"""

from __future__ import annotations

import hashlib
import shutil
import site
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "f9_failsecure" / "00_mismatch_verdict.py"
ARMS = Path(__file__).resolve().parent / "test_mismatch_verdict.py"

# Taken at import, before any mutant exists, and re-checked at the end of the run.
_LIVE_SHA = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Mutant:
    mid: str
    target: str                       # exact source substring, must appear exactly once
    replacement: str
    claim: str                        # what the mutation falsifies
    killers: tuple[str, ...] = field(default=())


MUTANTS: list[Mutant] = [
    Mutant(
        "M1-baseline-compared-as-strings",
        'if r["end_utc"] <= t and (prev is None or r["start_utc"] > prev)',
        'if r["end"] <= positive[t]["t"] and (prev is None or r["start_utc"] > prev)',
        "The bug as it actually happened. Windows were sent +00:00 and datapoints came back "
        "+07:00, so a string comparison ordered a read that closed 96 seconds AFTER the firing "
        "as its baseline. Twelve reads were offered that way.",
        killers=("test_a_window_that_closes_after_the_firing_is_not_its_baseline",),
    ),
    Mutant(
        "M2-naive-timestamp-assumed-utc",
        "    if dt.tzinfo is None:\n        raise Refusal(",
        "    if dt.tzinfo is None:\n        return dt.replace(tzinfo=timezone.utc)\n"
        "    if False:\n        raise Refusal(",
        "Assuming UTC for a stamp that carries no offset is the assumption that produced M1. "
        "The refusal is the fix; without it the same class of bug returns silently the next "
        "time a record is written without an offset.",
        killers=("test_a_naive_timestamp_is_refused_rather_than_assumed_utc",),
    ),
    Mutant(
        "M3-baseline-interval-widened",
        'if r["end_utc"] <= t and (prev is None or r["start_utc"] > prev)',
        'if r["end_utc"] <= t',
        "The second bug. 'Any window that closed before this firing' makes every day-1 read a "
        "candidate baseline for day 2 — and day 1 fired, so the contamination guard then "
        "rejects an episode that is clean on its own interval.",
        killers=("test_an_earlier_firing_does_not_contaminate_a_later_episode",
                 "test_the_two_episodes_have_disjoint_baselines"),
    ),
    Mutant(
        "M4-conjunction-becomes-disjunction",
        '"observed": all(fired.values())',
        '"observed": any(fired.values())',
        "The sealed oracle names two metrics. With `any`, one firing metric carries the "
        "verdict and TRUE means less than the oracle says it does.",
        killers=("test_one_silent_named_metric_is_enough_to_make_it_false",),
    ),
    Mutant(
        "M5-tools-call-basis-unchecked",
        'if counts["mcp_tools_call"] <= 0:',
        "if False:",
        "Without the basis, a silent metric would be published as FALSE even when nothing was "
        "ever asked of a broken policy — a verdict about our test plan wearing the service's "
        "name.",
        killers=("test_no_tools_call_record_is_refused_rather_than_published_as_false",),
    ),
    Mutant(
        "M6-create-policy-basis-unchecked",
        'if counts["create_policy"] <= 0:',
        "if False:",
        "'when a policy cannot evaluate' presupposes such a policy existed. Unchecked, the "
        "verdict rests on a premise nothing establishes.",
        killers=("test_no_create_policy_record_is_refused",),
    ),
    Mutant(
        "M7-unclassified-metric-ignored",
        "    if unknown:",
        "    if False:",
        "A metric name this file has never seen would drop out of the conjunction by default, "
        "and the verdict would still say TRUE — the silent-omission shape.",
        killers=("test_an_unclassified_metric_name_is_fatal",),
    ),
    Mutant(
        "M8-a-missing-read-reads-as-silence",
        "        if required:\n            raise Refusal(",
        "        if False:\n            raise Refusal(",
        "A named metric nobody read would be reported as `fired: False` — our omission "
        "published as the service's silence, which is the exact asymmetry the exercise-basis "
        "rule exists to prevent.",
        killers=("test_a_named_metric_with_no_read_at_all_is_refused",),
    ),
    Mutant(
        "M9-increment-without-a-measured-zero",
        'if ep["n_baseline_reads"] <= 0:',
        "if False:",
        "'It incremented' is a claim about two readings. With no read that closed before the "
        "firing there is no zero to increment from, and the word means nothing.",
        killers=("test_a_window_that_closes_after_the_firing_is_not_its_baseline",),
    ),
    Mutant(
        "M10-dirty-baseline-accepted",
        'if ep["reads_before_the_firing_that_were_already_positive"]:',
        "if False:",
        "If the metric was already positive in the interval before the firing, the increment is "
        "not attributable to the unevaluable policy in either direction.",
        killers=("test_an_already_positive_baseline_interval_is_refused",),
    ),
    Mutant(
        "M11-reread-count-fixed-at-one",
        'slot["seen_in_reads"] += 1',
        'slot["seen_in_reads"] = 1',
        "How many reads saw a firing is how the record shows an episode was observed more than "
        "once. Pinned at 1, two reads of one firing look like one read.",
        killers=("test_two_reads_of_one_firing_are_one_episode_not_two",),
    ),
    Mutant(
        "M12-sum-accumulates-across-reads",
        'slot["sum"] = max(slot["sum"], dp["sum"])',
        'slot["sum"] += dp["sum"]',
        "The survivor from the first run of this harness. Reading one firing twice added the "
        "Sums, so 20 mismatches from 20 requests would have been published as 40. Nothing "
        "asserted an episode's magnitude until this mutant went unkilled.",
        killers=("test_two_reads_of_one_firing_are_one_episode_not_two",),
    ),
]


# --------------------------------------------------------------------------- static checks

def test_every_mutant_target_appears_exactly_once():
    """A mutation that does not apply is not a survivor, and must never be banked as a kill."""
    src = SCRIPT.read_text(encoding="utf-8")
    ids = [m.mid for m in MUTANTS]
    assert len(ids) == len(set(ids)), f"duplicate mutant ids: {ids}"
    bad = [(m.mid, src.count(m.target)) for m in MUTANTS if src.count(m.target) != 1]
    assert not bad, (
        "these mutation targets no longer appear exactly once in the emitter, so the mutants "
        "would not apply and their claims would be unmeasured:\n"
        + "\n".join(f"  {mid}: found {n} occurrence(s)" for mid, n in bad))


def test_every_named_killer_arm_exists():
    """A `killers` entry naming an arm that does not exist would assert nothing."""
    arms_src = ARMS.read_text(encoding="utf-8")
    missing = sorted({k for m in MUTANTS for k in m.killers
                      if f"def {k}(" not in arms_src})
    assert not missing, f"named as killers but absent from {ARMS.name}: {missing}"


def test_the_two_regressions_that_actually_happened_are_both_covered():
    """M1 and M3 are the bugs the script's own guards caught. Neither may be dropped."""
    ids = {m.mid for m in MUTANTS}
    assert {"M1-baseline-compared-as-strings", "M3-baseline-interval-widened"} <= ids


# --------------------------------------------------------------------------- the run

def _sandbox(pytester: pytest.Pytester, monkeypatch, script_src: Path) -> pytest.Pytester:
    paths = [p for p in (site.getusersitepackages(), *sys.path) if p]
    monkeypatch.setenv("PYTHONPATH", ":".join(dict.fromkeys(paths)))
    monkeypatch.setenv("GRX_F92_SCRIPT", str(script_src))
    shutil.copyfile(ARMS, pytester.path / "test_arms_under_mutation.py")
    return pytester


def _staged(mutant: Mutant | None, dst_dir: Path) -> Path:
    """The script, mutated or not, written OUTSIDE the repo. The live file stays read-only.

    The copy keeps the original filename: the arms load it by path and the emitter resolves
    `lib/` from `ROOT`, which the copy's location changes — that is why the real-evidence arms
    skip in the sandbox, and the control run below pins how many.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    if mutant is not None:
        assert src.count(mutant.target) == 1, mutant.mid
        src = src.replace(mutant.target, mutant.replacement, 1)
    pkg = dst_dir / "f9_failsecure"
    pkg.mkdir(parents=True, exist_ok=True)
    # `lib` has to be importable from the copy's ROOT, since the emitter inserts ROOT/lib on
    # sys.path at import time. Symlinked rather than copied: a copy of lib/ could drift from
    # the real one and the mutants would be run against a different phase1/oracle.
    link = dst_dir / "lib"
    if not link.exists():
        link.symlink_to(ROOT / "lib", target_is_directory=True)
    out = pkg / SCRIPT.name
    out.write_text(src, encoding="utf-8")
    return out


def _run(pytester: pytest.Pytester, monkeypatch, tmp_path: Path,
         mutant: Mutant | None) -> pytest.RunResult:
    staged = _staged(mutant, tmp_path / ("mutant" if mutant else "control"))
    _sandbox(pytester, monkeypatch, staged)
    return pytester.runpytest_subprocess("-p", "no:cacheprovider", "-q",
                                         "test_arms_under_mutation.py")


def test_control_arm_the_unmutated_copy_passes_every_arm(
        pytester: pytest.Pytester, monkeypatch, tmp_path):
    """The control. Every kill below is worthless without it.

    An unmutated COPY, reached through exactly the `GRX_F92_SCRIPT` machinery the mutants use.
    If this reds, the kills are kills of the harness rather than of the mutations — the failure
    mode where a mutation run scores 12/12 against a tree in which no arm ran at all.
    """
    res = _run(pytester, monkeypatch, tmp_path, None)
    outcomes = res.parseoutcomes()
    assert outcomes.get("failed", 0) == 0, (
        f"the unmutated copy fails {outcomes.get('failed')} arm(s); the harness is broken, "
        f"not the script")
    assert outcomes.get("error", 0) == 0
    assert outcomes.get("passed", 0) >= 25, outcomes
    # The two real-evidence arms cannot see the archive from the sandbox. Pinned so a future
    # reader is not left thinking they contributed a kill.
    assert outcomes.get("skipped", 0) == 2, (
        f"expected exactly the 2 real-evidence arms to skip in the sandbox, got {outcomes}")


@pytest.mark.parametrize("mutant", MUTANTS, ids=[m.mid for m in MUTANTS])
def test_each_mutant_is_killed_by_the_arm_written_for_it(
        mutant: Mutant, pytester: pytest.Pytester, monkeypatch, tmp_path):
    res = _run(pytester, monkeypatch, tmp_path, mutant)
    outcomes = res.parseoutcomes()
    failed = outcomes.get("failed", 0) + outcomes.get("error", 0)
    assert failed, (
        f"{mutant.mid} SURVIVED — every arm passed with this defect in place.\n"
        f"  what it breaks: {mutant.claim}\n"
        f"  add an arm that fails under it; do not relax the mutation.")
    for arm in mutant.killers:
        res.stdout.fnmatch_lines([f"*{arm}*"])


def test_the_live_script_was_never_modified():
    """The safety argument, discharged rather than promised. Ordered last by filename."""
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == _LIVE_SHA, (
        "the emitter changed during the mutation run. Every mutant is applied to a copy, so "
        "this can only mean the harness wrote into the tree.")
