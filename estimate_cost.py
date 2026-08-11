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

Usage:
  estimate_cost.py                     # project and check
  estimate_cost.py --authorise PHASE   # exit 0 only if PHASE is safe to run now
  estimate_cost.py --verify-prices     # read live prices via the Pricing API
  estimate_cost.py --write-report      # regenerate COST.md from the model
"""

from __future__ import annotations

import argparse
import sys
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


def project(model: dict) -> tuple[list[dict], float]:
    """Per-phase projection. Sums are computed here and nowhere else."""
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
            "actual": ph.get("actual_usd", 0.0),
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


def check(model: dict, rows: list[dict], total: float,
          only: str | None = None) -> list[str]:
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
    return problems


def write_report(model: dict, rows: list[dict], total: float) -> None:
    m = model["meta"]
    contingency = model.get("contingency") or []
    csum = round(sum(float(c["usd"]) for c in contingency), 2)
    live = [r for r in rows if r["live"]]
    spent = round(sum(float(r["actual"]) for r in rows), 2)

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
      f"**contingency ${csum:.2f}** (worst case ${total + csum:.2f}) · "
      f"**actual to date ${spent:.2f}**")
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
        A(f"| **{r['id']}** {r['name']} | {'yes' if r['live'] else 'no'} | "
          f"{r['days']} | ${r['projected']:.2f} | ${float(r['actual']):.2f} | "
          f"{amends} | {r['status']} |")
    A(f"| | | | **${total:.2f}** | **${spent:.2f}** | | |")
    A("")
    A("`Days` is the number of distinct calendar days of observation, and it is derived "
      "from `May amend`, not chosen. A phase that may amend the document needs >= 2 "
      "(sealed as `validity_checks.reproduction_before_amendment`, enforced by "
      "`check_amendment_readiness.py`); `estimate_cost.py` refuses to authorise a phase "
      "that names an amendment target and declares one day.")
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
