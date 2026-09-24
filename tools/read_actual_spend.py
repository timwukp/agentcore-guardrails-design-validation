#!/usr/bin/env python3
"""Read this project's own spend off the meter, and refuse every shortcut that would fake it.

WHY THIS EXISTS
---------------
`FUTURE-WORK.md` item 40: `COST.md` published **actual to date $0.00** beside twelve projections in
the same table and the same typeface, and all thirteen phases carried `actual_usd: 0.0`. That zero was
never a measurement — it was a field nobody had filled. A zero that means "not measured" and a zero
that means "measured, cost nothing" must not print the same (`feedback_zero_needs_a_ran_flag`), and
this project publishes both kinds: `USE1-Guardrail-WordPolicyUnitsConsumed` really is $0.0000 over
1,144 consumed units, because the word-policy tier is free. One of those zeros is a result.

The method `cost_model.yaml` used to state could not produce the measurement either, and it fails in
three independent ways — each measured, not argued:

  1. **The tag key was never activated.** `ce:ListCostAllocationTags` returns 261 user-defined keys,
     of which exactly ONE is `Active` (`tums-project`). `Project` is `Inactive`, so
     `get_cost_and_usage` with `{"Tags": {"Key": "Project", "Values": [...]}}` returns `$0` with no
     error and no warning. The positive control is in the same log: the identical query shape against
     the one active key returns $23,477.99. A `$0` from Cost Explorer is a claim about the query
     (`feedback_empty_query_is_not_zero`).
  2. **The project uses TWO tag values.** 29 resources carry `Project=guardrails-doc-validation` and
     2 carry `Project=grx-validation`, so no single filter value sees both halves.
  3. **Cost Explorer's finest granularity is a calendar day, and this project ran several phases per
     day.** Per-phase actuals are therefore not recoverable at all: hourly and resource-level data
     would have had to be enabled BEFORE the spend, and it only retains 14 days. That is why
     `cost_model.yaml` keeps `actual_usd: null` per phase and records the project total instead.

WHAT THIS SCRIPT IS, AND WHAT IT IS NOT
---------------------------------------
It is NOT an attribution engine. Attribution is a judgement and it lives in `cost_model.yaml`'s
`actuals.ledger`, one entry per (service, usage type) with a `basis` and a reason a reader can attack.
This script's whole job is to make that ledger *checkable*: it re-reads the meter and fails on every
disagreement, so a stale or wishful ledger entry cannot sit in the file the way `actual to date $0.00`
sat in `COST.md` for six weeks.

It deliberately does NOT write `cost_model.yaml`, for the same reason `estimate_cost.py
--verify-prices` does not: a number changing is a decision a person makes, printed side by side, not
a silent edit.

WHY A LEDGER RATHER THAN A RULE
-------------------------------
Both rules a person reaches for when a tag turns out to be inactive were implemented and measured, and
they fail in OPPOSITE directions — which is the part any single number would have hidden:

  * **generous**, "claim the whole line if any of its spend lands on a project day": **$70,905.69 over
    1,154 lines**, 5,303x the truth on the 2026-09-21T15:51:30Z reading. This account's largest lines
    are shared storage and request traffic billed every single day, so every project day intersects
    every one of them — which is also why this one GROWS on every re-read: it measured $70,040.35 /
    5,238x thirty-four minutes earlier. The stamp travels with the figure because a recomputed number
    pasted into prose is a perishable claim (`feedback_perishable_claim_cannot_be_checked`).
  * **strict**, "claim a line only if all of its spend is on project days": **$11.70 over 105 lines**,
    which is BELOW the $13.37 ledger. It errs by omission and drops exactly the expensive lines — the
    volume and both Polly lines have spend from before this project began, and the EC2 instance has
    spend on three days no artifact backs. The orphaned 40 GB volume, the most valuable thing this
    measurement found, is invisible to it.

Both are recomputed and printed on every run, so neither number can go stale in prose, and together
they say something a single one could not: this is not a matter of being more careful with the day
list (`feedback_constraints_are_choices`). No rule keyed on days alone works here.

WHY THE CENSUS IS KEYED ON (SERVICE, USAGE TYPE)
------------------------------------------------
Because usage-type names are not unique. Measured over this window: **159** of the 1,309 lines' names
appear under more than one service. `DataTransfer-Out-Bytes` is metered under **ten** different
services, `TimedStorage-ByteHrs` under three (S3 $2,007.82, ECR $0.41, DynamoDB $0.00), and
`Requests-Tier1` under two. A census keyed on the name alone silently sums unrelated services into one
line, and the first version of this script did exactly that. Every ledger entry therefore names both,
and the lookup uses the pair. The run prints the collision count so the hazard stays visible rather
than becoming a comment nobody re-measures.

USAGE
    .venv-oracle/bin/python tools/read_actual_spend.py            # rc 0 = the ledger matches the meter
    .venv-oracle/bin/python tools/read_actual_spend.py --verbose   # the whole census, every line
    .venv-oracle/bin/python tools/read_actual_spend.py --census-json PATH   # check an offline census

Needs `ce:GetCostAndUsage` (read-only). Each request costs $0.01; a run pages the window once, MEASURED
at 17 requests for a 51-day window, so a live run costs $0.17 — disclosed rather than assumed.
`--census-json` replays a saved census for nothing, which is how this ledger was iterated on without
paying the meter per attempt.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "cost_model.yaml"

# A usage type's recorded cost may differ from a re-read by less than this and still be the same
# figure: Cost Explorer returns full-precision strings and the ledger records four to six decimals.
TOL_USD = 0.0005
# Usage quantities are counts (characters, units, invocations, instance-hours). Half a unit of slack
# is enough for the hours lines, which carry three decimals, and is far below one of anything else.
TOL_QTY = 0.5
# A resource_match entry derives its dollars from size x price x prorata, so it accumulates three
# roundings. A cent is generous and still an order of magnitude below the smallest line it guards.
TOL_DERIVED_USD = 0.01

BASES = ("day_set", "quantity_match", "resource_match")


def fatal(msg: str) -> int:
    print(f"FATAL: {msg}", file=sys.stderr)
    return 2


def key_of(service: str, usage_type: str) -> str:
    return f"{service} | {usage_type}"


# --------------------------------------------------------------------------- derived project days
def derive_project_days(root: Path) -> dict[str, set[str]]:
    """Every calendar day this repo's own artifacts say the project acted, and which artifact says so.

    Derived from FIVE producers rather than one, because each sees a different part of the work and a
    single-producer list would silently miss a family (`feedback_derive_from_every_producer`):
    `evidence/r<stamp>/` run directories, the EC2 runner's `incoming/<stamp>` transports, the two
    `results/day2_replication_<date>.json` files, timestamped filenames under `results/`, and
    `session-logs/` names.

    This is the set a ledger day is CHECKED against — a recorded day with no artifact behind it is a
    refusal. It is not the set attribution is derived from; see the module docstring for the two
    measured ways a day-keyed rule fails.

    Note the one honest imprecision, and why it cannot be fixed here: `session-logs/` names carry the
    LOCAL date of the day the log was written, while Cost Explorer bills in UTC. On a UTC+8 machine an
    evening render lands on the previous UTC day, which is exactly why
    `polly-spend-20260916-video.log` accounts for spend Cost Explorer dates 2026-09-15. A ledger entry
    may therefore claim a day this function does not produce, and must then list it in
    `unexplained_days` with a reason.
    """
    stamp = re.compile(r"(20\d\d)-?(\d\d)-?(\d\d)")
    days: dict[str, set[str]] = {}

    def add(day: str, source: str) -> None:
        days.setdefault(day, set()).add(source)

    def scan(pattern: str, source: str, *, recursive: bool = False) -> None:
        for p in glob.glob(str(root / pattern), recursive=recursive):
            m = stamp.search(os.path.basename(p))
            if m:
                add("-".join(m.groups()), source)

    scan("evidence/*", "evidence-run")
    scan("runner/.state/incoming/*", "runner-transport")
    scan("results/day2_replication_*.json", "day2-replication")
    scan("results/**/*T*Z*", "results-stamp", recursive=True)
    scan("session-logs/*", "session-log")
    return days


POLLY_TOTAL = re.compile(r"TOTAL\s+(\d[\d,]*)\s+characters", re.I)


def counted_polly_characters(root: Path) -> tuple[int, dict[str, int]]:
    """The character count the project counted for ITSELF, read out of its own spend logs.

    Polly is the one family where a day rule cannot work — the account billed Polly on 2026-08-04,
    five weeks before this project's first render, so "only on our days" is false for it. What stands
    in for the calendar is stronger: the two session logs counted 28,476 and 56,863 characters from
    CloudWatch `RequestCharacters` at render time, and Cost Explorer's own quantity over the render
    days is 85,339. Two meters, counted six days apart, agreeing to the character.

    Parsed from the logs rather than retyped here, so the two readers of that number must agree
    (`feedback_two_readers_one_format`). A log with no `TOTAL n characters` line contributes nothing
    and its absence is reported, because a regex that matched nothing must not read as zero.
    """
    per_log: dict[str, int] = {}
    for p in sorted(glob.glob(str(root / "session-logs" / "polly-spend-*.log"))):
        m = POLLY_TOTAL.search(Path(p).read_text(encoding="utf-8", errors="replace"))
        if m:
            per_log[os.path.basename(p)] = int(m.group(1).replace(",", ""))
    return sum(per_log.values()), per_log


# --------------------------------------------------------------------------------- classification
@dataclass
class Series:
    """One (service, usage type) line's daily readings over the window."""

    usage_type: str
    service: str
    days: dict[str, tuple[float, float]]      # day -> (usd, qty)

    @property
    def nonzero_days(self) -> list[str]:
        return sorted(d for d, (u, q) in self.days.items() if u != 0 or q != 0)

    @property
    def usd(self) -> float:
        return round(sum(u for u, _ in self.days.values()), 6)

    def usd_on(self, days) -> float:
        return round(sum(u for d, (u, _) in self.days.items() if d in days), 6)

    def qty_on(self, days) -> float:
        return round(sum(q for d, (_, q) in self.days.items() if d in days), 6)

    def max_daily_qty_on(self, days) -> float:
        vals = [q for d, (_, q) in self.days.items() if d in days]
        return max(vals) if vals else 0.0


def expand_range(pair: list[str]) -> list[str]:
    """`["2026-08-01", "2026-08-11"]` -> every day in that inclusive range.

    A range is written as its two ends so a reader can see its width at a glance, and expanded here so
    the arithmetic runs over every day rather than over the two endpoints.
    """
    a, b = date.fromisoformat(pair[0]), date.fromisoformat(pair[1])
    if b < a:
        raise ValueError(f"range {pair} ends before it starts")
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def naive_day_rule(census: dict[str, Series], project_days: set[str],
                   project_start: str) -> tuple[float, list[str]]:
    """The CONSERVATIVE day rule: claim a line only if all of its spend is on project days.

    "Attribute every line whose spend falls only on days the project ran, and which has no spend
    before the project began." Computed and printed on every run: a rejected method with a measured
    error is a finding, and a rejected method described only in prose is an opinion.

    Measured 2026-09-21: $11.70 over 105 lines -- BELOW the $13.33 ledger, not above it. This rule
    errs by omission, and what it omits is the expensive part: every shared line. It drops the 40 GB
    EBS volume entirely ($4.0912, because the volume's line has spend from 2026-08-01, long before
    this project), it drops both Polly lines (spend on 2026-08-04, before the project), and it drops
    the EC2 instance (spend on three days no artifact backs). The single most valuable thing this
    measurement found -- an orphaned volume still billing -- is invisible to it.
    """
    claimed, total = [], 0.0
    for k, s in census.items():
        nz = s.nonzero_days
        if not nz or any(d < project_start for d in nz):
            continue
        if set(nz) <= project_days:
            claimed.append(k)
            total += s.usd
    return round(total, 4), sorted(claimed)


def naive_any_day_rule(census: dict[str, Series],
                       project_days: set[str]) -> tuple[float, list[str]]:
    """The GENEROUS day rule: claim a whole line if any of its spend lands on a project day.

    The tempting rule, and the reason this script exists. It is the one a person reaches for when a
    tag turns out to be inactive, and it is wrong by two orders of magnitude, because this account's
    largest lines are shared storage and request traffic that happen to be billed every single day --
    so every project day intersects them.

    Both rules are computed on every run because they fail in OPPOSITE directions, and only reporting
    the pair shows that the error is not a matter of being careful with a day list
    (`feedback_constraints_are_choices`): no rule keyed on days alone can work here.
    """
    claimed, total = [], 0.0
    for k, s in census.items():
        nz = set(s.nonzero_days)
        if nz & project_days:
            claimed.append(k)
            total += s.usd
    return round(total, 4), sorted(claimed)


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    lines_read: int = 0
    days_read: int = 0
    estimated_days: list[str] | None = field(default_factory=list)
    ledger_checked: int = 0
    attributed_entries: int = 0
    naive_total: float = 0.0
    naive_count: int = 0
    naive_any_total: float = 0.0
    naive_any_count: int = 0
    immaterial_lines: int = 0
    immaterial_usd: float = 0.0
    measured_usd: float = 0.0
    collisions: dict[str, list[str]] = field(default_factory=dict)

    @property
    def rc(self) -> int:
        if self.problems:
            return 1
        # A run that read nothing has checked nothing. These are `ran` flags, not budgets: the census
        # must have come back with data, and the ledger must have had entries to check. Without them a
        # broken reader and a clean ledger are indistinguishable.
        if self.lines_read == 0 or self.days_read == 0:
            return 2
        if self.ledger_checked == 0 or self.attributed_entries == 0:
            return 2
        return 0


def check(census: dict[str, Series], model: dict, root: Path,
          estimated_days: list[str] | None, days_read: int) -> Report:
    """Every refusal, over data an injected reader supplied. No boto3 in this function.

    `estimated_days` is tri-state: a list of days Cost Explorer marked Estimated, an EMPTY list
    meaning it marked none, or `None` meaning the source could not say -- which a legacy saved
    census cannot. Collapsing the third into the second is how a replay loses a caveat.
    """
    rep = Report(lines_read=len(census), days_read=days_read,
                 estimated_days=None if estimated_days is None else sorted(estimated_days))

    by_name: dict[str, list[str]] = {}
    for s in census.values():
        by_name.setdefault(s.usage_type, []).append(s.service)
    rep.collisions = {n: sorted(v) for n, v in by_name.items() if len(v) > 1}

    actuals = model.get("actuals")
    if not actuals:
        rep.problems.append(
            "cost_model.yaml has no `actuals:` block, so there is nothing to check the meter "
            "against; an absent ledger is not a clean one")
        return rep

    window = actuals.get("window") or {}
    start, end = str(window.get("start", "")), str(window.get("end", ""))
    recorded_days = [str(d) for d in (actuals.get("project_days") or [])]
    project_days = set(recorded_days)
    project_start = min(project_days) if project_days else start

    # 1. The recorded day list must be backed by artifacts in this repo.
    derived = derive_project_days(root)
    unbacked = [d for d in recorded_days if d not in derived]
    for d in unbacked:
        rep.problems.append(
            f"actuals.project_days lists {d}, and no artifact in this repo places the project on that "
            f"day; either name the artifact or drop the day")
    rep.notes.append(
        f"{len(recorded_days)} recorded project day(s), {len(recorded_days) - len(unbacked)} of them "
        f"backed by artifacts among the {len(derived)} days this repo's five producers name")

    # 2. Both naive rules, measured rather than asserted, because they fail in opposite directions.
    rep.naive_total, naive_claimed = naive_day_rule(census, project_days, project_start)
    rep.naive_count = len(naive_claimed)
    rep.naive_any_total, naive_any_claimed = naive_any_day_rule(census, project_days)
    rep.naive_any_count = len(naive_any_claimed)

    # 3. Every ledger entry against the meter.
    ledger = actuals.get("ledger") or []
    attributed_total = 0.0
    counted_chars, per_log = counted_polly_characters(root)
    qmatch_qty = 0.0
    qmatch_entries = 0
    prices = model.get("prices") or {}

    for e in ledger:
        ut, svc = str(e.get("usage_type", "")), str(e.get("service", ""))
        rep.ledger_checked += 1
        s = census.get(key_of(svc, ut))
        if s is None:
            rep.problems.append(
                f"ledger names {svc} | {ut} and the meter has no such line in {start}..{end}: either "
                f"the window moved, the service is wrong, or the name is. A ledger entry nothing can "
                f"confirm is worse than no entry")
            continue
        if not e.get("attributed", False):
            # A rejection is still an adjudication and still needs its reason on the record.
            if not str(e.get("reason", "")).strip():
                rep.problems.append(
                    f"{ut}: attributed: false with no reason — a rejection with no argument cannot be "
                    f"reviewed, and reads as an oversight")
            continue

        rep.attributed_entries += 1
        basis = str(e.get("basis", ""))
        if basis not in BASES:
            rep.problems.append(
                f"{ut}: basis {basis!r} is not one of {BASES}; an unnamed basis is an assertion")
            continue
        recorded_usd = float(e.get("usd", 0.0))
        attributed_total += recorded_usd

        if basis == "resource_match":
            rep.problems.extend(_check_resource_match(e, s, prices))
            continue

        claimed = [str(d) for d in (e.get("days") or [])]
        if not claimed:
            rep.problems.append(
                f"{ut}: attributed with basis {basis} and no `days`; the entry does not say what it is "
                f"claiming")
            continue
        excluded = {str(k): str(v) for k, v in (e.get("excluded_days") or {}).items()}

        # The partition. Every day the meter shows spend on must be either claimed or excluded with a
        # reason, and nothing may be claimed that the meter does not show. Without this, a line's
        # inconvenient days could simply be left out and the entry would still reconcile.
        unaccounted = [d for d in s.nonzero_days if d not in claimed and d not in excluded]
        if unaccounted:
            rep.problems.append(
                f"{ut}: the meter shows spend on {unaccounted}, which the ledger neither claims nor "
                f"excludes; an unmentioned day is an unexplained one "
                f"(feedback_unnumbered_is_uncounted)")
        phantom = [d for d in claimed if d not in s.nonzero_days]
        if phantom:
            rep.problems.append(
                f"{ut}: the ledger claims {phantom} and the meter shows nothing there")
        for d, why in excluded.items():
            if not why.strip():
                rep.problems.append(f"{ut}: excluded {d} with no reason")

        if abs(recorded_usd - s.usd_on(claimed)) > TOL_USD:
            rep.problems.append(
                f"{ut}: ledger records ${recorded_usd:.6f} over its claimed days, the meter now says "
                f"${s.usd_on(claimed):.6f}")
        if e.get("qty") is not None and abs(float(e["qty"]) - s.qty_on(claimed)) > TOL_QTY:
            rep.problems.append(
                f"{ut}: ledger records qty {float(e['qty']):.3f} over its claimed days, the meter now "
                f"says {s.qty_on(claimed):.3f}")

        # A claimed day must be a project day, or be listed as unexplained WITH a reason. This is the
        # clause that keeps `day_set` from becoming "any day we like".
        unexplained = {str(d) for d in (e.get("unexplained_days") or [])}
        if unexplained and not str(e.get("unexplained_reason", "")).strip():
            rep.problems.append(f"{ut}: lists unexplained_days and no unexplained_reason")
        for d in claimed:
            if d not in project_days and d not in unexplained:
                rep.problems.append(
                    f"{ut}: claims {d}, which is neither a recorded project day nor listed in "
                    f"unexplained_days")
            if d < project_start:
                rep.problems.append(
                    f"{ut}: claims {d}, before this project's first recorded day {project_start}")

        if e.get("max_daily_qty") is not None:
            cap = float(e["max_daily_qty"])
            worst = s.max_daily_qty_on(claimed)
            if worst > cap + TOL_QTY:
                rep.problems.append(
                    f"{ut}: the busiest claimed day meters {worst:.3f} against a declared ceiling of "
                    f"{cap:.3f} — the identification this entry rests on no longer holds")

        if basis == "quantity_match":
            qmatch_entries += 1
            qmatch_qty += s.qty_on(claimed)

    # 4. The quantity cross-check for the quantity_match lines, against the project's own count.
    if qmatch_entries:
        if not per_log:
            rep.problems.append(
                "the ledger has quantity_match entries and no session-logs/polly-spend-*.log states a "
                "`TOTAL n characters` line, so the independent count they rest on was never read")
        elif abs(qmatch_qty - counted_chars) > TOL_QTY:
            rep.problems.append(
                f"the {qmatch_entries} quantity_match line(s) total {qmatch_qty:.0f} at the meter and "
                f"this project counted {counted_chars} in {sorted(per_log)}; two meters that were "
                f"supposed to agree do not")
        else:
            rep.notes.append(
                f"quantity cross-check: {counted_chars} characters counted by this project in "
                f"{len(per_log)} log(s) == {qmatch_qty:.0f} at the meter, across {qmatch_entries} "
                f"line(s)")

    # 5. Completeness. A ledger is a name list, and a name list cannot notice a new name
    #    (`feedback_scope_as_namelist`), so every line the meter shows for a service this project
    #    touches, falling only on project days, must at least APPEAR in the ledger.
    services = [str(x) for x in (actuals.get("services_touched") or [])]
    present = {s.service for s in census.values()}
    for svc in services:
        if svc not in present:
            rep.problems.append(
                f"services_touched names {svc!r} and the meter shows no such service in the window; a "
                f"misspelled service name would silently switch the completeness check off")
    named = {key_of(str(e.get("service")), str(e.get("usage_type"))) for e in ledger}
    for k, s in census.items():
        if s.service not in services or k in named:
            continue
        nz = s.nonzero_days
        if not nz or any(d < project_start for d in nz) or not set(nz) <= project_days:
            continue
        if s.usd < TOL_USD:
            # Below the tolerance every other check in this script uses, so adjudicating it either way
            # cannot move a published figure. The first run produced 38 of these -- cross-region
            # `AWS-In-Bytes` / `AWS-Out-Bytes` meters in region pairs this project never used, each
            # $0.0000 -- and demanding a ledger entry per line would have buried fifteen real entries
            # under thirty-eight zeroes, which is how a guard gets switched off wholesale.
            #
            # This is an exemption, so it is COUNTED and its total is published as an upper bound
            # rather than dropped (`feedback_no_silent_caps`). The bound is what makes it safe: a line
            # that grows past the tolerance stops being exempt and becomes a problem again, by the
            # same comparison. No name list is involved, so a NEW immaterial line needs no edit here
            # and a new material one cannot hide.
            rep.immaterial_lines += 1
            rep.immaterial_usd += s.usd
            continue
        rep.problems.append(
            f"{s.usage_type} ({s.service}) is metered only on this project's own days and the ledger "
            f"does not mention it — ${s.usd:.4f} over {len(nz)} day(s). Adjudicate it either way, but "
            f"not by omission")

    if rep.immaterial_lines:
        rep.immaterial_usd = round(rep.immaterial_usd, 6)
        rep.notes.append(
            f"completeness exemption: {rep.immaterial_lines} line(s) in this project's services fall "
            f"only on project days, are absent from the ledger, and are each below ${TOL_USD} at the "
            f"meter. Together they total ${rep.immaterial_usd:.6f}, which is the whole amount this "
            f"exemption can hide; any one of them growing past the tolerance becomes a problem again")

    # 6. The published total must be the sum of the entries, computed here and nowhere else.
    rep.measured_usd = round(attributed_total, 4)
    recorded_total = actuals.get("measured_usd")
    if recorded_total is None:
        rep.problems.append("actuals.measured_usd is absent; COST.md would have nothing to publish")
    elif abs(float(recorded_total) - rep.measured_usd) > TOL_USD:
        rep.problems.append(
            f"actuals.measured_usd says ${float(recorded_total):.4f} and the attributed entries sum to "
            f"${rep.measured_usd:.4f}")

    # 7. The lag, stated. Not a problem — a property of the instrument a reader must be told.
    if census:
        newest = max(d for s in census.values() for d in s.days)
        rep.notes.append(
            f"newest day Cost Explorer returned: {newest} (window ends {end}, exclusive); days after "
            f"it are ABSENT, not zero")
        if rep.estimated_days is None:
            rep.notes.append(
                "this census file predates the Estimated-day field, so this run CANNOT say whether "
                "Cost Explorer still considers any of these days provisional. Re-save the census to "
                "get that caveat back; a replay that says less than the run it replays is worse than "
                "no replay")
        elif rep.estimated_days:
            rep.notes.append(
                f"{len(rep.estimated_days)} day(s) in the window are still marked Estimated by Cost "
                f"Explorer ({rep.estimated_days[0]}..{rep.estimated_days[-1]}); figures over them can "
                f"still move, and this script failing on that drift later is correct behaviour")
    return rep


def _check_resource_match(e: dict, s: Series, prices: dict) -> list[str]:
    """A step in a shared account-wide line, identified by size AND by dollar rate.

    Two numbers, two derivations (`feedback_two_numbers_two_claims`):

      * the QUANTITY step, measured as the difference between the daily mean before the resource
        existed and the daily mean after it settled, times the days in that month, must equal the size
        of the resource the entry names;
      * the DOLLARS, derived independently from size x unit price x days-held/days-in-month, must
        equal what the entry records.

    And a step is only a step if the regions either side of it are flat. A difference of two noisy
    means is not a measurement (`feedback_narrow_interval_is_not_stability`), so the within-region
    spread must be small against the step itself; otherwise this refuses rather than reporting a
    number.
    """
    ut = s.usage_type
    problems: list[str] = []
    sm = e.get("step_measurement") or {}
    try:
        base = expand_range([str(x) for x in sm["baseline_days"]])
        step = expand_range([str(x) for x in sm["step_days"]])
        month_days = int(sm["days_in_step_month"])
    except (KeyError, ValueError, TypeError) as exc:
        return [f"{ut}: basis resource_match needs step_measurement with baseline_days, step_days and "
                f"days_in_step_month ({type(exc).__name__}: {exc}); without the derivation the "
                f"identification is just a tag"]

    bq = [s.days[d][1] for d in base if d in s.days]
    sq = [s.days[d][1] for d in step if d in s.days]
    if len(bq) < 2 or len(sq) < 2:
        return [f"{ut}: the meter covers {len(bq)} baseline day(s) and {len(sq)} step day(s); a step "
                f"needs at least two of each to be a step rather than a pair of points"]

    step_qty = statistics.mean(sq) - statistics.mean(bq)
    spread = max(max(bq) - min(bq), max(sq) - min(sq))
    if step_qty <= 0:
        problems.append(
            f"{ut}: the measured step is {step_qty:.6f}/day — not positive, so nothing was added to "
            f"this line where the ledger says a resource appeared")
    elif spread > 0.5 * step_qty:
        problems.append(
            f"{ut}: the daily quantity varies by {spread:.6f} within the baseline/step regions "
            f"against a step of {step_qty:.6f}; the regions are not flat enough for their difference "
            f"to identify anything")

    recorded_size = e.get("resource_monthly_qty")
    if recorded_size is None:
        problems.append(
            f"{ut}: basis resource_match needs resource_monthly_qty — what the resource IS, to sit "
            f"beside what the meter charges for")
    elif step_qty > 0:
        measured = step_qty * month_days
        if abs(measured - float(recorded_size)) > TOL_QTY:
            problems.append(
                f"{ut}: the meter's step is {step_qty:.6f}/day x {month_days} = {measured:.3f} and "
                f"the entry names a resource of {float(recorded_size):.3f}; these must agree or the "
                f"line is not identified")

    price_key = str(e.get("price_key", ""))
    price = prices.get(price_key)
    prorata = e.get("prorata") or []
    if price is None:
        problems.append(f"{ut}: price_key {price_key!r} is not in cost_model.yaml's prices")
    elif not price.get("verified"):
        problems.append(
            f"{ut}: price {price_key} carries verified: false, and a dollar figure derived from an "
            f"unverified price is a guess wearing six decimals")
    elif not prorata:
        problems.append(
            f"{ut}: basis resource_match needs a prorata list; a GB-month price times a partial month "
            f"is not a multiplication anyone should do in their head")
    elif recorded_size is not None:
        unit = float(price["usd"])
        derived = sum(float(recorded_size) * unit * int(p["days_held"]) / int(p["days_in_month"])
                      for p in prorata)
        if abs(derived - float(e.get("usd", 0.0))) > TOL_DERIVED_USD:
            problems.append(
                f"{ut}: {float(recorded_size):.1f} x ${unit} prorated comes to ${derived:.4f} and the "
                f"entry records ${float(e.get('usd', 0.0)):.4f}")

    # The days-held total must still reach the newest day the meter knows about. This is what makes a
    # still-billing resource nag instead of quietly going stale: the figure is not wrong yet, it is
    # wrong from tomorrow.
    first = str(e.get("first_billed_day", ""))
    held = sum(int(p["days_held"]) for p in prorata)
    if first and s.days:
        newest = max(s.days)
        span = (date.fromisoformat(newest) - date.fromisoformat(first)).days + 1
        if held < span:
            problems.append(
                f"{ut}: prorata accounts for {held} day(s) held and the meter now covers {span} day(s) "
                f"from {first} to {newest}. If the resource is still there it is still billing, and "
                f"the ledger is {span - held} day(s) stale — deleting it is the fix, not editing this")
    return problems


# ------------------------------------------------------------------------------------- live wiring
class CostExplorerReader:
    """The only part of this file that talks to AWS. Returns plain data.

    Groups by SERVICE and USAGE_TYPE together, and reads the WHOLE account rather than a filtered
    slice, because the completeness check in `check()` needs the universe: a filter built from the
    ledger's own names could never surface a line the ledger forgot.
    """

    def __init__(self, start: str, end: str) -> None:
        import boto3

        self._ce = boto3.client("ce", region_name="us-east-1")
        self._start, self._end = start, end
        self.requests = 0

    def census(self) -> tuple[dict[str, Series], list[str], int]:
        token = None
        out: dict[str, Series] = {}
        estimated: set[str] = set()
        days: set[str] = set()
        while True:
            kw = dict(TimePeriod={"Start": self._start, "End": self._end}, Granularity="DAILY",
                      Metrics=["UnblendedCost", "UsageQuantity"],
                      GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"},
                               {"Type": "DIMENSION", "Key": "USAGE_TYPE"}])
            if token:
                kw["NextPageToken"] = token
            res = self._ce.get_cost_and_usage(**kw)
            self.requests += 1
            for t in res["ResultsByTime"]:
                day = t["TimePeriod"]["Start"]
                days.add(day)
                if t.get("Estimated"):
                    estimated.add(day)
                for g in t["Groups"]:
                    service, ut = g["Keys"][0], g["Keys"][1]
                    usd = float(g["Metrics"]["UnblendedCost"]["Amount"])
                    qty = float(g["Metrics"]["UsageQuantity"]["Amount"])
                    if not usd and not qty:
                        continue
                    s = out.setdefault(key_of(service, ut), Series(ut, service, {}))
                    prev = s.days.get(day, (0.0, 0.0))
                    s.days[day] = (prev[0] + usd, prev[1] + qty)
            token = res.get("NextPageToken")
            if not token:
                break
        return out, sorted(estimated), len(days)


CENSUS_LINES_KEY = "lines"
CENSUS_ESTIMATED_KEY = "estimated_days"
CENSUS_READ_AT_KEY = "read_at"


def utc_stamp(now: datetime | None = None) -> str:
    """The one place a meter reading's timestamp is produced.

    It exists because the first `actuals.read_at` in `cost_model.yaml` was TYPED, and what got typed
    was local time wearing a `Z`: the reading finished at 14:58Z on a UTC+8 machine and the field
    said `21:49Z`, seven hours in the future. That is the same defect `check_out_stamp()` was written
    for in `platform/build/` three hours earlier, reproduced by hand in a different file, which is
    the tell that the fix there was a validator and not a producer (`feedback_mandatory_field_timing`,
    `feedback_newest_by_name_is_not_newest`). A stamp with no producer has whoever ran the command as
    its only author. `now` is injectable so an arm about "in the future" does not pass or fail by the
    timezone of whoever runs it -- the defect under test.
    """
    return (now or datetime.now(timezone.utc)).astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def census_to_json(path: Path, census: dict[str, Series],
                   estimated: list[str], read_at: str) -> None:
    """Write a census so `census_from_json` can read it back.

    This lived inline in `main()`'s `--save-census` branch, which is reachable only by a live Cost
    Explorer read, so no arm could touch it. A mutation that dropped `read_at` from the written object
    left all 48 arms green: the arm that claimed to hold writer and reader to one format
    (`feedback_two_readers_one_format`) hand-wrote the JSON itself and therefore only ever tested the
    reader against MY idea of the shape. Extracted so both sides of that claim run the same code.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {CENSUS_READ_AT_KEY: read_at,
         CENSUS_ESTIMATED_KEY: estimated,
         CENSUS_LINES_KEY: {k: {d: list(v) for d, v in s.days.items()}
                            for k, s in census.items()}},
        indent=1, sort_keys=True), encoding="utf-8")


def census_from_json(path: Path) -> tuple[dict[str, Series], list[str], int, str | None]:
    """Read a census previously saved by `--save-census`.

    Exists so a check can be re-run without paying Cost Explorer $0.17 again, and so the arms in
    `tools/tests/` can hand this function's output straight to `check()`.

    Two shapes are accepted. The current one wraps the lines and carries the days Cost Explorer
    marked `Estimated`; the flat legacy shape `{"service | usage_type": {day: [usd, qty]}}` has no
    room for them. The distinction matters because the first offline replay silently dropped the
    live run's loudest caveat -- that twenty days of September were still Estimated and every figure
    over them can still move -- and a replay that quietly says less than the run it replays is the
    narrower-smoke-test defect (`feedback_smoke_test_narrower_than_production`). A legacy file is
    therefore read, and its silence about Estimated days is reported as silence rather than as
    "none". `read_at` is returned the same way and for the same reason: the replay should name the
    moment the METER was read rather than the moment the replay ran, and a legacy file that cannot
    say so says nothing instead of guessing from its own mtime -- which on this machine would be the
    time the file was last copied.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    estimated: list[str] | None = None
    read_at: str | None = None
    if isinstance(raw.get(CENSUS_LINES_KEY), dict):
        # `in`, not `or []`. A wrapped file that is MISSING the field cannot say whether any day was
        # Estimated, and coercing that to "none were" is the same tri-state collapse the legacy shape
        # was fixed for -- one level further in, where a mutant that stopped writing the field left
        # every arm green. An empty list still means "the meter marked none", which is a real answer.
        if CENSUS_ESTIMATED_KEY in raw:
            estimated = [str(d) for d in (raw[CENSUS_ESTIMATED_KEY] or [])]
        read_at = str(raw[CENSUS_READ_AT_KEY]) if raw.get(CENSUS_READ_AT_KEY) else None
        raw = raw[CENSUS_LINES_KEY]
    out: dict[str, Series] = {}
    days: set[str] = set()
    for k, series in raw.items():
        service, sep, ut = k.partition(" | ")
        if not sep:
            raise SystemExit(f"{path}: key {k!r} is not 'service | usage_type'; a census keyed on the "
                             f"usage type alone merges services that share a name")
        out[k] = Series(ut, service, {d: (v[0], v[1]) for d, v in series.items()})
        days |= set(series)
    return out, estimated, len(days), read_at


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verbose", action="store_true",
                    help="print every line the window contains, not just the ledger's")
    ap.add_argument("--census-json", type=Path,
                    help="check against a saved census instead of calling Cost Explorer")
    ap.add_argument("--save-census", type=Path,
                    help="write the census read from Cost Explorer to this path")
    args = ap.parse_args(argv)

    if not MODEL.is_file():
        return fatal("cost_model.yaml is missing; there is no ledger to check")
    model = yaml.safe_load(MODEL.read_text(encoding="utf-8"))
    actuals = model.get("actuals") or {}
    window = actuals.get("window") or {}
    start, end = str(window.get("start", "")), str(window.get("end", ""))
    if not re.fullmatch(r"20\d\d-\d\d-\d\d", start) or not re.fullmatch(r"20\d\d-\d\d-\d\d", end):
        return fatal(f"actuals.window must carry an ISO start and end; got {start!r}..{end!r}")

    if args.census_json:
        census, estimated, days_read, read_at = census_from_json(args.census_json)
        source = f"saved census {args.census_json}"
    else:
        reader = CostExplorerReader(start, end)
        census, estimated, days_read = reader.census()
        read_at = utc_stamp()
        source = f"Cost Explorer, {reader.requests} request(s) (~${reader.requests * 0.01:.2f})"
        if args.save_census:
            census_to_json(args.save_census, census, estimated, read_at)

    rep = check(census, model, ROOT, estimated, days_read)

    print(f"window                {start} .. {end} (end exclusive)")
    print(f"read from             {source}")
    published = str(actuals.get("read_at") or "").strip()
    if read_at:
        print(f"meter read at         {read_at} (UTC, produced by this script, not typed)"
              + ("" if read_at == published else
                 f" — cost_model.yaml publishes {published or '(nothing)'}, so the figures below "
                 f"belong to THIS reading and the file describes another one"))
    else:
        print(f"meter read at         the saved census predates the {CENSUS_READ_AT_KEY} field, so "
              f"this run cannot say when the meter was read; cost_model.yaml publishes "
              f"{published or '(nothing)'}")
    print(f"lines read            {len(census)} (service, usage type) pair(s) over {days_read} day(s)")
    print(f"ledger entries        {rep.ledger_checked}, of which attributed {rep.attributed_entries}")
    print(f"attributed            ${rep.measured_usd:.4f}")
    print(f"day rule, generous    ${rep.naive_any_total:.2f} over {rep.naive_any_count} line(s) — "
          f"REJECTED, over by {rep.naive_any_total / rep.measured_usd:.0f}x"
          if rep.measured_usd else "day rule, generous    (no attributed total to compare)")
    print(f"day rule, strict      ${rep.naive_total:.2f} over {rep.naive_count} line(s) — REJECTED, "
          f"UNDER the ledger: it cannot see a shared line, so the volume and Polly vanish")
    if rep.immaterial_lines:
        print(f"immaterial lines      {rep.immaterial_lines} exempt from completeness, "
              f"${rep.immaterial_usd:.6f} in total — the bound on what that hides")
    if rep.collisions:
        worst = max(rep.collisions.items(), key=lambda kv: len(kv[1]))
        print(f"name collisions       {len(rep.collisions)} usage-type name(s) appear under more than "
              f"one service; worst is {worst[0]!r} under {len(worst[1])}")
    for n in rep.notes:
        print(f"note                  {n}")

    if args.verbose:
        print("\nevery line in the window, by cost:")
        for s in sorted(census.values(), key=lambda x: -x.usd):
            print(f"  {s.usd:12.4f}  {len(s.nonzero_days):3d}d  {s.service:<42} {s.usage_type}")

    if rep.problems:
        print(f"\nPROBLEMS ({len(rep.problems)})")
        for p in rep.problems:
            print(f"  - {p}")
    else:
        print("\nOK — every ledger entry agrees with the meter over the days it claims, every metered "
              "day is\n  claimed or excluded with a reason, every recorded project day has an artifact "
              "behind it, and no\n  line from a service this project touches is missing from the "
              "ledger.")

    print("\nSTILL OPEN, and this script cannot close it: per-PHASE actuals. Cost Explorer's finest "
          "granularity is a\n  calendar day and this project ran several phases per day, so the phase "
          "column in COST.md stays\n  `not measured` rather than being filled with a share somebody "
          "apportioned. Hourly and resource-level\n  data would have had to be enabled before the "
          "spend and retains 14 days; August is long past that.")
    return rep.rc


if __name__ == "__main__":
    sys.exit(main())
