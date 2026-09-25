#!/usr/bin/env python3
"""Compute the cost projection from cost_model.yaml, and refuse when it is not safe.

The approved plan specifies a script that "refuses to run if the projection exceeds the
pre-registered ceiling". That control could not exist as written: the ceiling lived only
in the plan's prose ($55-95) and in my recollection, so nothing could read it. It is now
in `cost_model.yaml:meta.ceiling_usd`, and this script is the thing that reads it.

Three refusals, in increasing order of how easy they would be to skip:

1. **Over ceiling.** The obvious one.
2. **Unverified price.** A phase whose projection depends on a price nobody has looked
   up is not authorised, even if the number happens to be right. A projection built from
   guesses that reports "within ceiling" is feedback_vacuous_test_check applied to money:
   the check passes by construction. `--verify-prices` fetches the live figures.
3. **Unfunded replication.** A phase that may amend the document needs >= 2 calendar
   days of observation (validity_checks.reproduction_before_amendment). If such a phase
   declares `days: 1`, the projection is describing a phase whose results cannot be used
   — cheap and worthless rather than expensive. This is the refusal I would not have
   thought to write before the rule was gated, and it is the one that connects money to
   validity.
4. **An actual that nothing measured.** Every phase carried `actual_usd: 0.0` for the
   whole project, and this script printed it as `$0.00` in COST.md's Actual column and in
   an `actual to date $0.00` total. Nothing had ever been read off a meter; the zero was a
   placeholder that rendered as a measurement, and an empty query is not a zero
   (`feedback_empty_query_is_not_zero`). Cost Explorer's finest retroactive granularity is
   a calendar day and this project ran several phases per day, so a per-phase actual is not
   obtainable at all — the phases now carry `null`, this script prints `n/a`, and a
   *numeric* per-phase actual is refused unless it names an `actual_source`. The
   whole-project figure that IS measurable lives in `cost_model.yaml:actuals`, is checked
   against the meter by `tools/read_actual_spend.py`, and is published with its window.

Usage:
  estimate_cost.py                     # project and check
  estimate_cost.py --authorise PHASE   # exit 0 only if PHASE is safe to run now
  estimate_cost.py --verify-prices     # read live prices via the Pricing API
  estimate_cost.py --write-report      # regenerate COST.md from the model
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "cost_model.yaml"
PREREG = ROOT / "PREREGISTRATION.yaml"
REPORT = ROOT / "COST.md"

MIN_DAYS = 2


def fatal(msg: str) -> int:
    print(f"FATAL: {msg}", file=sys.stderr)
    return 2


def load() -> dict:
    return yaml.safe_load(MODEL.read_text(encoding="utf-8"))


def price_of(model: dict, name: str) -> dict:
    p = model["prices"].get(name)
    if p is None:
        raise KeyError(f"phase references unknown price {name!r}")
    return p


def ledger_total(acts: dict) -> float:
    """Sum the attributed ledger lines.

    `tools/read_actual_spend.py` computes this same sum against live Cost Explorer data. Two
    readers of one file must be asserted to AGREE (`feedback_two_readers_one_format`), or
    each will happily pin its own number while the other moves — so `check()` compares this
    sum with `actuals.measured_usd` rather than trusting the published total.
    """
    return round(sum(float(e.get("usd") or 0.0)
                     for e in (acts.get("ledger") or []) if e.get("attributed")), 4)


_MISSING = object()


def project(model: dict) -> tuple[list[dict], float]:
    """Per-phase projection. Sums are computed here and nowhere else.

    `actual` is deliberately tri-state: a float (measured, and then it must name a source),
    `None` (declared not measurable), or `_MISSING` (the field is absent, which `check()`
    refuses — an absent field used to arrive here as 0.0 and print as a measured zero).
    """
    rows = []
    for ph in model["phases"]:
        total = 0.0
        unverified = []
        for item in ph.get("items") or []:
            pr = price_of(model, item["price"])
            total += float(pr["usd"]) * float(item["qty"])
            if not pr.get("verified", False) and float(pr["usd"]) > 0:
                unverified.append(item["price"])
        rows.append({
            "id": ph["id"], "name": ph["name"], "live": ph["live"],
            "days": ph["days"], "amends": ph.get("amends") or [],
            "projected": round(total, 4),
            "declared": ph.get("projected_usd"),
            "actual": ph.get("actual_usd", _MISSING),
            "actual_source": ph.get("actual_source"),
            "unverified": sorted(set(unverified)),
            "status": ph.get("status", "pending"),
        })
    return rows, round(sum(r["projected"] for r in rows), 2)


def sealed_min_days(problems: list[str]) -> int:
    """Read the replication threshold from the sealed pre-registration.

    Same discipline as check_amendment_readiness.py: the number this script enforces
    must be the number that was registered, not one chosen here.
    """
    import re
    pr = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    vc = (pr.get("validity_checks") or {}).get("reproduction_before_amendment")
    if not vc:
        problems.append("PREREGISTRATION.yaml no longer seals "
                        "reproduction_before_amendment; the replication refusal below "
                        "would be enforcing an unregistered rule")
        return MIN_DAYS
    m = re.search(r">=\s*(\d+)\s+separate calendar days", str(vc.get("rule", "")))
    if not m:
        problems.append("the sealed rule no longer states '>= N separate calendar days'")
        return MIN_DAYS
    if int(m.group(1)) != MIN_DAYS:
        problems.append(f"the sealed rule requires {m.group(1)} days, this script "
                        f"enforces {MIN_DAYS}")
    return int(m.group(1))


def stamp_problems(stamp: str, now: datetime | None = None) -> list[str]:
    """Refuse an `actuals.read_at` that is not UTC, or that is in the future.

    The first value this field ever held was `2026-09-21T21:49Z`, typed by hand while the reading it
    described finished at `14:58:15Z`: local time on a UTC+8 machine wearing a `Z`. Nothing caught it,
    because the only rule was "not empty" -- and an unparseable or impossible stamp is not empty. The
    future check is the one that convicts this exact mistake, since a local stamp mislabelled UTC on
    this machine is always ahead of the clock. `read_actual_spend.py --save-census` now PRODUCES the
    value (`utc_stamp`), so this is the validator behind a producer rather than instead of one.

    `now` is injected by every arm. An arm about "eight hours in the future" written against
    `datetime.now()` would pass or fail by the timezone of whoever ran it, which is the defect itself.
    """
    out: list[str] = []
    try:
        read = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            read = datetime.strptime(stamp, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return [f"actuals.read_at is {stamp!r}, which is not an ISO UTC instant "
                    f"(YYYY-MM-DDThh:mm[:ss]Z). An unparseable stamp passes an 'is it blank' "
                    f"check and still cannot be compared to anything"]
    ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if read > ref:
        ahead = (read - ref).total_seconds() / 3600.0
        out.append(
            f"actuals.read_at is {stamp}, which is {ahead:.1f} hour(s) in the future against "
            f"{ref:%Y-%m-%dT%H:%M:%SZ}. A meter cannot have been read after now; the way this "
            f"field goes wrong is local time labelled Z on a UTC+8 machine, which lands about "
            f"eight hours ahead. Let `read_actual_spend.py --save-census` produce it")
    return out


def check(model: dict, rows: list[dict], total: float,
          only: str | None = None, now: datetime | None = None) -> list[str]:
    problems: list[str] = []
    min_days = sealed_min_days(problems)
    ceiling = float(model["meta"]["ceiling_usd"])
    contingency = round(sum(float(c["usd"]) for c in model.get("contingency") or []), 2)

    if total > ceiling:
        problems.append(f"projection ${total:.2f} exceeds the ceiling ${ceiling:.2f}")
    if total + contingency > ceiling:
        problems.append(
            f"projection ${total:.2f} + fully-drawn contingency ${contingency:.2f} = "
            f"${total + contingency:.2f} exceeds the ceiling ${ceiling:.2f}. Every "
            f"contingency trigger firing at once is unlikely, but a ceiling that only "
            f"holds when nothing goes wrong is not a ceiling")

    scope = [r for r in rows if only is None or r["id"] == only]
    if only is not None and not scope:
        problems.append(f"no phase with id {only!r}")

    for r in scope:
        if r["declared"] is not None and abs(r["declared"] - r["projected"]) > 0.005:
            problems.append(f"phase {r['id']}: declares ${r['declared']} but the items "
                            f"compute to ${r['projected']:.4f}")
        if r["live"] and r["unverified"]:
            problems.append(f"phase {r['id']} is live and depends on unverified "
                            f"price(s) {r['unverified']} — run --verify-prices before "
                            f"authorising it")
        if r["amends"] and r["days"] < min_days:
            problems.append(
                f"phase {r['id']} may amend {r['amends']} but declares "
                f"days={r['days']}; the sealed rule requires >= {min_days}. Its "
                f"results could not be used to change the document, so the money "
                f"would buy an observation and not a finding")
        # The converse check asks "is this phase replicated beyond a single day of
        # observation", which is 1 by definition — NOT ">= min_days". Writing it as
        # `>= min_days` made every confirm-only phase fail the moment the sealed rule was
        # relaxed to 1 day, because then days=1 satisfied the threshold. That surfaced
        # while mutation-testing the seal arm: a check whose meaning shifts when an
        # unrelated constant moves was reading the wrong quantity. Baseline observation
        # is one day; anything above it is replication and needs a reason.
        if not r["amends"] and r["days"] > 1:
            problems.append(
                f"phase {r['id']} declares days={r['days']} but names no `amends:` "
                f"targets — either it can amend something and should say so, or it is "
                f"being replicated for no stated reason")

    # The actual column, which is a claim about a meter and not an arithmetic result. These
    # run over every phase, not just the one being authorised: what they protect is the
    # honesty of the published file, which does not depend on which phase is in scope.
    for r in rows:
        if r["actual"] is _MISSING:
            problems.append(
                f"phase {r['id']} has no `actual_usd` field at all. Absent used to mean "
                f"0.0 here, and 0.0 prints as $0.00 in COST.md next to nine phases that "
                f"really did spend money. Write `null` and let the report say n/a")
        elif r["actual"] is not None and not str(r["actual_source"] or "").strip():
            problems.append(
                f"phase {r['id']} declares actual_usd=${float(r['actual']):.4f} and names "
                f"no `actual_source`. No per-phase actual can be read from Cost Explorer "
                f"(daily is its finest retroactive granularity and this project ran several "
                f"phases per day), so a number here has to say where it came from")

    acts = model.get("actuals")
    if acts is not None:
        if acts.get("measured_usd") is None:
            problems.append("actuals: exists but carries no measured_usd; the report would "
                            "announce a measurement and print nothing")
        win = acts.get("window") or {}
        if not (win.get("start") and win.get("end")):
            problems.append(
                "actuals.window is incomplete. A spend figure without its window is the "
                "share-without-a-denominator defect applied to money: $13.33 over seven "
                "weeks and $13.33 over one afternoon are different findings")
        stamp = str(acts.get("read_at") or "").strip()
        if not stamp:
            problems.append("actuals.read_at is absent; a meter reading is perishable and "
                            "an undated one cannot be re-checked")
        else:
            problems.extend(stamp_problems(stamp, now))
        summed = ledger_total(acts)
        recorded = acts.get("measured_usd")
        if recorded is not None and abs(float(recorded) - summed) > 0.005:
            problems.append(
                f"actuals.measured_usd says ${float(recorded):.4f} and its own attributed "
                f"ledger lines sum to ${summed:.4f}. COST.md publishes the first and this "
                f"file's other reader checks the second, so they have to agree")
        if not (acts.get("ledger") or []):
            problems.append("actuals: has no ledger; a total with no lines under it is a "
                            "figure nobody can attribute or refute")
    return problems


def write_report(model: dict, rows: list[dict], total: float) -> None:
    m = model["meta"]
    contingency = model.get("contingency") or []
    csum = round(sum(float(c["usd"]) for c in contingency), 2)
    live = [r for r in rows if r["live"]]
    acts = model.get("actuals") or {}
    # Two populations, counted separately, because the interesting number is how many phases
    # have an actual AT ALL. Summing `None` as zero is how "we never measured this" became
    # "this cost nothing" in every previous revision of this file.
    measured_rows = [r for r in rows
                     if r["actual"] is not _MISSING and r["actual"] is not None]
    spent = round(sum(float(r["actual"]) for r in measured_rows), 2)
    per_phase = (f"**per phase measured ${spent:.2f}** ({len(measured_rows)} of {len(rows)} "
                 f"phases)") if measured_rows else \
                (f"**per-phase actual: not obtainable** (0 of {len(rows)} phases)")
    meter = acts.get("measured_usd")
    win = acts.get("window") or {}

    L = []
    A = L.append
    A("# COST.md — projected vs actual, by phase")
    A("")
    A(f"*Generated by `estimate_cost.py` from `cost_model.yaml` v{m['version']}. "
      f"Do not edit by hand: every figure here is computed, and a number typed into "
      f"this file would be exactly the unverified prose the project screens for.*")
    A("")
    A(f"**Ceiling ${float(m['ceiling_usd']):.2f}** · "
      f"**projected ${total:.2f}** · "
      f"**contingency ${csum:.2f}** (worst case ${total + csum:.2f})")
    A("")
    if meter is not None:
        A(f"**Measured at the meter: ${float(meter):.4f}** for the whole project, "
          f"{win.get('start')} .. {win.get('end')} (end exclusive), read "
          f"{acts.get('read_at')} · {per_phase}")
    else:
        A(f"**No spend has been read off a meter.** {per_phase}")
    A("")
    A("Standing authorisation is $1000/mo of project spend, so this project never "
      "needed to ask. Per `feedback_spend_authorization` the authorisation removes the "
      "question, not the disclosure — hence this file.")
    A("")
    A(f"{m['attribution'].strip()}")
    A("")
    A("## Per phase")
    A("")
    A("| Phase | Live | Days | Projected | Actual | May amend | Status |")
    A("|:--|:--:|--:|--:|--:|:--|:--|")
    for r in rows:
        amends = ", ".join(r["amends"]) if r["amends"] else "—"
        act = ("n/a" if r["actual"] is None or r["actual"] is _MISSING
               else f"${float(r['actual']):.2f}")
        A(f"| **{r['id']}** {r['name']} | {'yes' if r['live'] else 'no'} | "
          f"{r['days']} | ${r['projected']:.2f} | {act} | "
          f"{amends} | {r['status']} |")
    tail = f"**${spent:.2f}**" if measured_rows else "**n/a**"
    A(f"| | | | **${total:.2f}** | {tail} | | |")
    A("")
    A("`Actual` reads **n/a**, not $0.00, and the difference is the point. Cost Explorer's "
      "finest retroactive granularity is a calendar day; this project ran several phases on "
      "most of its days, so no per-phase actual exists to be read. Every phase carried "
      "`actual_usd: 0.0` until 2026-09-21 and this table printed thirteen `$0.00`s and an "
      "`actual to date $0.00` — a column of placeholders that read as a column of "
      "measurements. The figure that *is* measurable is the whole-project one above, and it "
      "is measured, not projected.")
    A("")
    A("`Days` is the number of distinct calendar days of observation, and it is derived "
      "from `May amend`, not chosen. A phase that may amend the document needs >= 2 "
      "(sealed as `validity_checks.reproduction_before_amendment`, enforced by "
      "`check_amendment_readiness.py`); `estimate_cost.py` refuses to authorise a phase "
      "that names an amendment target and declares one day.")
    A("")
    if acts:
        A("## Actual spend, read off the meter")
        A("")
        A(f"*Read by `{acts.get('read_by')}` at {acts.get('read_at')}, over "
          f"{win.get('start')} .. {win.get('end')} (end exclusive). Every figure below is "
          f"re-derived from Cost Explorer on each run of that script, which refuses the "
          f"ledger if a line has drifted, if a metered day is neither claimed nor excluded, "
          f"or if a usage type in one of this project's services is missing from the table "
          f"altogether.*")
        A("")
        A(f"{str(acts.get('measured_usd_note', '')).strip()}")
        A("")
        A(f"{str(acts.get('ce_request_note', '')).strip()}")
        A("")
        A(f"Attribution rests on {len(acts.get('project_days') or [])} calendar days this "
          f"project's own artifacts place it on, across "
          f"{len(acts.get('services_touched') or [])} services it provably called. The days "
          f"are derived from the repository, not listed by hand, so a ledger line claiming a "
          f"day nothing happened on is refused.")
        A("")
        A("| Usage type | Service | Basis | USD |")
        A("|:--|:--|:--|--:|")
        ledger = acts.get("ledger") or []
        for e in [x for x in ledger if x.get("attributed")]:
            A(f"| `{e['usage_type']}` | {e['service']} | {e.get('basis', '—')} | "
              f"${float(e.get('usd') or 0.0):.4f} |")
        A(f"| | | **attributed to this project** | **${ledger_total(acts):.4f}** |")
        A("")
        rejected = [x for x in ledger if not x.get("attributed")]
        if rejected:
            A(f"And **{len(rejected)} lines this project will not claim**, with their real "
              f"amounts, because a rejection with no number attached cannot be checked:")
            A("")
            A("| Usage type | Service | USD at the meter | Why not claimed |")
            A("|:--|:--|--:|:--|")
            for e in rejected:
                why = " ".join(str(e.get("reason", "")).split())
                why = why if len(why) <= 180 else why[:177].rstrip() + "..."
                A(f"| `{e['usage_type']}` | {e['service']} | "
                  f"${float(e.get('usd') or 0.0):.4f} | {why} |")
            A("")
            A("The largest of these dwarf the project's entire spend. That is the finding, "
              "not an inconvenience: a day rule over this account's shared lines would have "
              "attributed hundreds of dollars of unrelated storage and request traffic to a "
              "guardrails study, and the attribution note above records the measured size of "
              "that error.")
            A("")
    A("## What the replication requirement cost")
    A("")
    A("Nothing, in eight of the ten live phases — and the reason is a design decision "
      "that is worth stating plainly, because the obvious reading of \"reproduce on two "
      "separate days\" is \"run it twice\", which would have doubled the most expensive "
      "phase in the project.")
    A("")
    A(f"{model['replication_rule']['split_not_double'].strip()}")
    A("")
    A("The two phases where it is not free:")
    A("")
    A("- **Phase 7** (nine-region probe) genuinely doubles: each region contributes one "
      "existence observation, so there is no *n* to deal across days. The calls are "
      "unmetered control-plane calls, so the doubling costs $0 and roughly ten minutes.")
    A("- **Phase 6** repeats its 20-call warm-up per night per arm, +320 calls. "
      "Immaterial against 16,640.")
    A("")
    A("And two where the requirement does not apply and the phase is deliberately *not* "
      "replicated: **5c** (account-level enforcement — the highest blast radius in the "
      "project; where the rule does not bind, the risk-minimising choice wins) and "
      "**6b**. Both are confirm-only. If either falsifies it acquires the requirement "
      "at that moment, which is what the contingency lines below are for.")
    A("")
    A("## The day-effect protocol, pre-specified")
    A("")
    A(f"{model['replication_rule']['day_effect_protocol'].strip()}")
    A("")
    A("### And its limitation, stated rather than buried")
    A("")
    A(f"{model['replication_rule']['power_of_the_split'].strip()}")
    A("")
    A("## Contingency")
    A("")
    A("Named and bounded, not a slush figure — each line states the observation that "
      "would draw it.")
    A("")
    A("| Trigger | Amount |")
    A("|:--|--:|")
    for c in contingency:
        A(f"| **{c['id']}** — {str(c['trigger']).strip()} | ${float(c['usd']):.2f} |")
    A(f"| | **${csum:.2f}** |")
    A("")
    A("## Unit prices")
    A("")
    A("| Price | USD | Unit | Verified |")
    A("|:--|--:|:--|:--:|")
    for name, p in model["prices"].items():
        A(f"| `{name}` | {float(p['usd']):.7f} | {p['unit']} | "
          f"{'yes' if p.get('verified') else '**no**'} |")
    A("")
    unver = sorted({u for r in rows for u in r["unverified"]})
    if unver:
        A(f"**{len(unver)} price(s) are unverified**: "
          + ", ".join(f"`{u}`" for u in unver) + ". "
          "`estimate_cost.py --authorise <phase>` exits non-zero for any live phase "
          "that depends on one. The projection above is therefore an *estimate built "
          "from unconfirmed figures* and is labelled as such rather than presented as "
          "a result; a projection whose inputs nobody looked up cannot certify itself "
          "as within ceiling.")
    else:
        A("All prices verified against the AWS Pricing API.")
    A("")
    A("---")
    A("")
    A(f"*Ceiling source: {str(m['ceiling_source']).strip()}*")
    A("")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")


def verify_prices(model: dict) -> int:
    """Read live unit prices from the AWS Pricing API and report every disagreement.

    Deliberately separate from the projection: fetching prices needs network and
    credentials, and a projection must be computable and checkable offline.

    This does NOT write to cost_model.yaml. It prints the live figure beside the
    recorded one and exits non-zero on any mismatch, so a price change is a decision a
    person makes rather than a silent edit — the same reason `check_reproducible` writes
    to a separate directory instead of rebuilding in place.

    Each price in the model carries a `pricing_api` block naming the exact service code
    and usagetype. Without it, "verified" would mean "some number was fetched", and a
    lookup pointed at the wrong usagetype is worse than no lookup: it stamps a guess.
    """
    try:
        import boto3
    except ImportError:
        return fatal("boto3 is not importable; cannot verify prices")
    import json as _json

    cli = boto3.client("pricing", region_name="us-east-1")
    problems: list[str] = []
    checked = 0

    for name, p in model["prices"].items():
        api = p.get("pricing_api")
        if api is None:
            if float(p["usd"]) == 0 and p.get("verified"):
                continue          # an asserted zero (unmetered calls) needs no lookup
            problems.append(f"{name}: no `pricing_api` block, so 'verified' could only "
                            f"ever mean 'a number was fetched from somewhere'")
            continue
        try:
            res = cli.get_products(
                ServiceCode=api["service_code"],
                Filters=[{"Type": "TERM_MATCH", "Field": "usagetype",
                          "Value": api["usagetype"]}],
                MaxResults=10)
        except Exception as e:                                # noqa: BLE001
            problems.append(f"{name}: Pricing API call failed "
                            f"({type(e).__name__}: {e}) — a failed lookup must not be "
                            f"recorded as a confirmation")
            continue

        found: list[tuple[float, str]] = []
        for pl in res["PriceList"]:
            d = _json.loads(pl)
            for term in d["terms"].get("OnDemand", {}).values():
                for dim in term["priceDimensions"].values():
                    found.append((float(dim["pricePerUnit"]["USD"]), dim["unit"]))
        if not found:
            problems.append(f"{name}: usagetype {api['usagetype']!r} returned no "
                            f"products under {api['service_code']}")
            continue

        want_tier = api.get("tier_description")
        live = min(v for v, _u in found) if want_tier == "cheapest" else found[0][0]
        recorded = float(p["usd"])
        checked += 1
        mark = "ok " if abs(live - recorded) < 1e-12 else "DIFF"
        print(f"  {mark} {name:<28} recorded {recorded:.10f}  live {live:.10f}  "
              f"[{api['usagetype']}]", file=sys.stderr)
        if mark == "DIFF":
            problems.append(f"{name}: model says {recorded:.10f}, the Pricing API says "
                            f"{live:.10f} for {api['usagetype']} — update "
                            f"cost_model.yaml deliberately, do not let the projection "
                            f"drift")

    print(f"\n{checked} price(s) checked against the live Pricing API", file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s):", file=sys.stderr)
        for pb in problems:
            print(f"  - {pb}", file=sys.stderr)
        return 1
    print("every priced line matches the live Pricing API", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorise", metavar="PHASE",
                    help="exit 0 only if PHASE is safe to run now")
    ap.add_argument("--verify-prices", action="store_true")
    ap.add_argument("--write-report", action="store_true")
    args = ap.parse_args(argv)

    if not MODEL.is_file():
        return fatal("cost_model.yaml is missing — the projection cannot be computed, "
                     "which is not the same as being within ceiling")
    if not PREREG.is_file():
        return fatal("PREREGISTRATION.yaml is missing — the replication rule this "
                     "script enforces cannot be confirmed")

    model = load()
    if args.verify_prices:
        return verify_prices(model)

    try:
        rows, total = project(model)
    except KeyError as e:
        return fatal(str(e))

    problems = check(model, rows, total, only=args.authorise)

    if args.write_report:
        write_report(model, rows, total)
        print(f"wrote {REPORT.relative_to(ROOT)}")

    ceiling = float(model["meta"]["ceiling_usd"])
    csum = round(sum(float(c["usd"]) for c in model.get("contingency") or []), 2)
    print(f"projection ${total:.2f} · contingency ${csum:.2f} · "
          f"worst case ${total + csum:.2f} · ceiling ${ceiling:.2f}")
    for r in rows:
        if r["live"]:
            flag = " UNVERIFIED-PRICE" if r["unverified"] else ""
            print(f"  phase {r['id']:<3} ${r['projected']:>7.2f}  "
                  f"{r['days']}d  {'amends ' + ','.join(r['amends']) if r['amends'] else 'confirm-only'}{flag}")

    if problems:
        what = f"phase {args.authorise}" if args.authorise else "the projection"
        print(f"\nNOT AUTHORISED — {len(problems)} problem(s) with {what}:",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("\nAUTHORISED" + (f" — phase {args.authorise}" if args.authorise else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
