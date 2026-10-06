#!/usr/bin/env python3
"""F10-1: does an input-blocked request avoid the model charge that an output-blocked one pays?

    .venv-oracle/bin/python f10_billing/03_block_billing.py send --dry-run
    .venv-oracle/bin/python f10_billing/03_block_billing.py send
    .venv-oracle/bin/python f10_billing/03_block_billing.py read          # >= 24 h after send
    .venv-oracle/bin/python f10_billing/03_block_billing.py read --final  # emit even if undecided

THE SEALED ORACLE, VERBATIM (claims/triage_rules.CASES["F10-1"])
----------------------------------------------------------------
"TRUE if a Cost-Explorer/tagged delta shows zero inference charge for input-blocked requests
and full charge for output-blocked ones; FALSE if either differs" — method "n paired requests
per arm, cost attributed by resource tag". Class S, binding EXISTENCE, planned_n None.

The full design, and why it takes this shape, is `f10_billing/F10-1-DESIGN.md`. In short:

TWO PHASES, BECAUSE THE INSTRUMENT LAGS
---------------------------------------
Cost Explorer reports a day's usage roughly 24 h late, so one process cannot both send the
requests and read their bill. `send` makes the calls and writes every row to
`results/f10_billing/F10-1-sends.json`. `read` runs later: it queries Cost Explorer for the
days the rows name and decides. The rows file is the hand-off, so `read` never guesses
which requests it is pricing.

ONE GUARDRAIL, ONE MODEL, ONE MANIPULATED VARIABLE
--------------------------------------------------
Both arms call `Converse` with the same guardrail (the `words` key; its list is read from the
manifest) and the same model, each through its own application inference profile. Each
profile carries the tag `grx-f10-1-arm=<arm>`, which is activated as a cost allocation tag.
What differs is where the listed word appears:

  * input-blocked  — the user turn contains a listed word verbatim.
  * output-blocked — the user turn contains no listed word as a whole word, and asks the
                     model to join two fragments into one. The joined word is listed.

`manipulation_check()` asserts that property from the prompts before any call is made.
The output arm only exists if the model really emits the word, so `send` makes one
pre-flight call first, through the UNTAGGED system profile so that it cannot contaminate
either arm's bill. If that call is not output-blocked, `send` stops before any counted
request.

A THIRD ARM, BECAUSE THE RESPONSE HIDES WHAT THE MODEL CONSUMED
----------------------------------------------------------------
The first design took the output arm as its own positive control and priced it against the
`usage` its responses reported. The pre-flight on 2026-09-30 refuted both halves. A
guardrail-intervened `Converse` response reports `usage` 0 input / 0 output tokens on BOTH
arms, although the output check can only have fired on text the model generated. The same
prompt with no guardrail reports 29 / 4, identically on three calls
(`evidence/f10-1/reference-unguarded-20260930.json`). So:

  * the response cannot be the reference for "full charge", and
  * a $0 output-arm bill would be ambiguous between "output-blocked requests are not billed"
    (FALSE) and "the tag never reached the bill" (no reading at all).

The control arm sends the output arm's prompt with NO guardrail, through a third profile
tagged `control`. Its `usage` is truthful. That gives the per-request reference, and its
own bill is the positive control that tag attribution works.

WHAT DECIDES
------------
  * Control first. Its billed tokens must equal the tokens its responses reported, within
    one token per request. If it is unbilled, the tag's reach is not established and the
    result is undecided. If it is billed but wrong, the instrument is at fault.
  * "Zero inference charge" means the input arm has no `*NovaMicro-*-tokens` usage under its
    tag value.
  * "Full charge" is a number. The output arm's billed tokens must equal (its request count)
    x (the control's mean reported tokens per request), within one token per request.
  * Cost Explorer's `UsageQuantity` for these usage types is in thousands of tokens. `read`
    re-derives that unit from the bill itself (dollars / quantity must equal the list price
    per 1K), and a bill whose unit does not check out is an instrument fault.

Rows that landed in the wrong arm (an input-arm request that was not input-blocked, and so
on) are instrument faults: the arm's bill would then price a different treatment.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A    # noqa: E402
import oracle as O        # noqa: E402
import phase1 as P        # noqa: E402
import redact             # noqa: E402

CASE = "F10-1"
GUARDRAIL_KEY = "words"
GUARDRAIL_VERSION = "DRAFT"
REGION = "us-east-1"

# The untagged system profile both application profiles were copied from. The pre-flight
# call goes through it, so it is billed to neither arm.
SYSTEM_PROFILE = "us.amazon.nova-micro-v1:0"
TAG_KEY = "grx-f10-1-arm"
ARM_INPUT = "input-blocked"
ARM_OUTPUT = "output-blocked"
ARM_CONTROL = "control"
ARMS = (ARM_INPUT, ARM_OUTPUT, ARM_CONTROL)
PROFILE_NAME = {arm: f"grx-f10-1-{arm}" for arm in ARMS}

# Not a sealed n (planned_n is None). 20 per arm makes the output arm's billed quantity large
# enough to be read against the one-token-per-request rounding tolerance.
N_PER_ARM = 20
MAX_TOKENS = 20

# The cost allocation tag read Active at 2026-09-30T09:04:56Z, and activation can take up to
# 24 h to apply. Usage before it is not attributed to the tag, so `send` refuses earlier.
NOT_BEFORE = datetime(2026, 10, 1, 9, 5, tzinfo=timezone.utc)

# Cost Explorer lags roughly 24 h. `read` refuses to decide before this much time has passed
# since the last send.
READ_LAG = timedelta(hours=24)

# Nova Micro list prices per 1K tokens. `read` does NOT use them to price anything; it uses
# them to check that `UsageQuantity` is in thousands of tokens, which is what makes the
# token comparison valid. Source: the August 2026 meter lines in cost_model.yaml
# ($0.006893 / 196.956 = $0.000035 input; $0.020550 / 146.788 = $0.00014 output).
PRICE_PER_1K = {"input": 0.000035, "output": 0.00014}
UNIT_TOLERANCE = 0.02  # relative; Cost Explorer rounds dollars to about 1e-10 but not exactly

USAGE_TYPE_RE = re.compile(r"NovaMicro-(input|output)-tokens$")

SENDS_PATH = ROOT / "results" / "f10_billing" / "F10-1-sends.json"
EVIDENCE_DIR = ROOT / "evidence" / "f10-1"


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

def split_word(word: str) -> tuple[str, str]:
    """Two fragments that join to `word`, neither of which is the word itself."""
    mid = len(word) // 2
    return word[:mid], word[mid:]


def prompts(words: list[str]) -> dict[str, str]:
    """The user turn for each arm, built from the provisioned word list."""
    word = words[1] if len(words) > 1 else words[0]
    a, b = split_word(word)
    return {
        ARM_INPUT: f"In one short sentence, what might the word {word} mean?",
        ARM_OUTPUT: (f"Join the fragments '{a}' and '{b}' into a single word. "
                     f"Reply with only that word, in lowercase, and nothing else."),
        ARM_CONTROL: (f"Join the fragments '{a}' and '{b}' into a single word. "
                      f"Reply with only that word, in lowercase, and nothing else."),
        "_word": word,
    }


def contains_word(text: str, word: str) -> bool:
    """Whole-word, case-insensitive: the shape of a custom word match."""
    return re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text, re.I) is not None


def manipulation_check(words: list[str]) -> dict[str, Any]:
    """The input prompt carries a listed word; the output prompt carries none."""
    p = prompts(words)
    in_hits = [w for w in words if contains_word(p[ARM_INPUT], w)]
    same = p[ARM_CONTROL] == p[ARM_OUTPUT]
    out_hits = [w for w in words if contains_word(p[ARM_OUTPUT], w)]
    a, b = split_word(p["_word"])
    return {
        "ok": (bool(in_hits) and not out_hits and same
               and a + b == p["_word"] and bool(a) and bool(b)),
        "control_prompt_is_output_prompt": same,
        "input_prompt_words": in_hits,
        "output_prompt_words": out_hits,
        "fragments": [a, b],
        "word": p["_word"],
    }


# ---------------------------------------------------------------------------
# reading one Converse response
# ---------------------------------------------------------------------------

def _blocked_words(assessment: dict | None) -> list[str]:
    words = ((assessment or {}).get("wordPolicy") or {}).get("customWords") or []
    return [w.get("match", "") for w in words
            if w.get("action") == "BLOCKED" and w.get("detected", True)]


def summarize(resp: dict, *, arm: str, rep: int, sent_at: str) -> dict[str, Any]:
    """The facts `read` needs from one response, and nothing that identifies the account."""
    trace = ((resp.get("trace") or {}).get("guardrail")) or {}
    in_assess = next(iter((trace.get("inputAssessment") or {}).values()), None)
    out_lists = list((trace.get("outputAssessments") or {}).values())
    out_assess = out_lists[0][0] if out_lists and out_lists[0] else None
    usage = resp.get("usage") or {}
    return {
        "arm": arm,
        "rep": rep,
        "sent_at": sent_at,
        "request_id": (resp.get("ResponseMetadata") or {}).get("RequestId", ""),
        "stop_reason": resp.get("stopReason"),
        "input_blocked_words": _blocked_words(in_assess),
        "output_blocked_words": _blocked_words(out_assess),
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
    }


def landed_arm(row: dict) -> str | None:
    """Which treatment the request actually received, read off its own trace."""
    if row.get("stop_reason") == "end_turn" and not (row["input_blocked_words"]
                                                    or row["output_blocked_words"]):
        return ARM_CONTROL if (row.get("output_tokens") or 0) > 0 else None
    if row.get("stop_reason") != "guardrail_intervened":
        return None
    if row["input_blocked_words"]:
        return ARM_INPUT
    if row["output_blocked_words"]:
        return ARM_OUTPUT
    return None


# ---------------------------------------------------------------------------
# reading Cost Explorer
# ---------------------------------------------------------------------------

def billed(ce_pages: list[dict]) -> dict[str, dict[str, dict[str, float]]]:
    """{arm: {"input"|"output": {"qty": 1K-token units, "usd": dollars}}} from grouped pages.

    Groups are (TAG, USAGE_TYPE). A tag group key reads `grx-f10-1-arm$<value>`; the empty
    value is untagged spend and belongs to neither arm.
    """
    out: dict[str, dict[str, dict[str, float]]] = {
        arm: {k: {"qty": 0.0, "usd": 0.0} for k in ("input", "output")} for arm in ARMS}
    for page in ce_pages:
        for period in page.get("ResultsByTime", []):
            for g in period.get("Groups", []):
                tag, usage_type = g["Keys"]
                arm = tag.split("$", 1)[1] if "$" in tag else ""
                m = USAGE_TYPE_RE.search(usage_type)
                if arm not in ARMS or not m:
                    continue
                cell = out[arm][m.group(1)]
                cell["qty"] += float(g["Metrics"]["UsageQuantity"]["Amount"])
                cell["usd"] += float(g["Metrics"]["UnblendedCost"]["Amount"])
    return out


def reported(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Σ usage tokens per arm, as the responses themselves reported them."""
    out = {arm: {"input": 0, "output": 0, "n": 0} for arm in ARMS}
    for r in rows:
        if r["arm"] not in out:
            continue
        out[r["arm"]]["input"] += int(r.get("input_tokens") or 0)
        out[r["arm"]]["output"] += int(r.get("output_tokens") or 0)
        out[r["arm"]]["n"] += 1
    return out


def unit_check(bill: dict) -> dict[str, Any]:
    """Is `UsageQuantity` in thousands of tokens? Checked from dollars / quantity."""
    checks = []
    for arm in ARMS:
        for kind in ("input", "output"):
            c = bill[arm][kind]
            if c["qty"] > 0:
                per_unit = c["usd"] / c["qty"]
                rel = abs(per_unit - PRICE_PER_1K[kind]) / PRICE_PER_1K[kind]
                checks.append({"arm": arm, "kind": kind, "usd_per_unit": per_unit,
                               "expected": PRICE_PER_1K[kind], "ok": rel <= UNIT_TOLERANCE})
    return {"checks": checks, "ok": all(c["ok"] for c in checks)}


def decide(rows: list[dict], bill: dict) -> dict[str, Any]:
    """The verdict detail. `status` is "decided", "undecided" or "fault"."""
    wrong = [{"arm": r["arm"], "rep": r["rep"], "landed": landed_arm(r)}
             for r in rows if landed_arm(r) != r["arm"]]
    rep = reported(rows)
    tokens = {arm: {k: bill[arm][k]["qty"] * 1000 for k in ("input", "output")} for arm in ARMS}
    units = unit_check(bill)
    n_c, n_o = rep[ARM_CONTROL]["n"], rep[ARM_OUTPUT]["n"]
    control_billed = sum(tokens[ARM_CONTROL].values()) > 0
    control_exact = {k: abs(tokens[ARM_CONTROL][k] - rep[ARM_CONTROL][k]) <= n_c
                     for k in ("input", "output")}
    expected = {k: (n_o * rep[ARM_CONTROL][k] / n_c if n_c else None)
                for k in ("input", "output")}
    input_zero = sum(tokens[ARM_INPUT].values()) == 0
    full = {k: expected[k] is not None and abs(tokens[ARM_OUTPUT][k] - expected[k]) <= n_o
            for k in ("input", "output")}
    detail = {"billed_tokens": tokens, "reported_tokens": rep,
              "expected_output_arm_tokens": expected, "tolerance_tokens_per_request": 1,
              "unit_check": units, "wrong_arm_rows": wrong,
              "control_billed": control_billed, "control_matches_its_usage": control_exact,
              "input_arm_zero": input_zero, "output_arm_full": full}
    if wrong or not units["ok"] or (control_billed and not all(control_exact.values())):
        detail["status"] = "fault"
    elif not control_billed:
        detail["status"] = "undecided"
    else:
        detail["status"] = "decided"
        detail["observed"] = input_zero and all(full.values())
    return detail


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------

def _mask(obj: Any) -> Any:
    return redact.mask(obj)


def profile_arns(bedrock) -> dict[str, str]:
    found = {}
    for page in bedrock.get_paginator("list_inference_profiles").paginate(typeEquals="APPLICATION"):
        for p in page["inferenceProfileSummaries"]:
            for arm, name in PROFILE_NAME.items():
                if p["inferenceProfileName"] == name and p["status"] == "ACTIVE":
                    found[arm] = p["inferenceProfileArn"]
    missing = [a for a in ARMS if a not in found]
    if missing:
        raise RuntimeError(f"no ACTIVE application inference profile for {missing}; see "
                           f"F10-1-DESIGN.md's execution log for how they were created")
    return found


def converse(runtime, model_id: str, gid: str | None, text: str) -> dict:
    """One call. `gid=None` is the control arm: the same request with no guardrail."""
    kw = {} if gid is None else {"guardrailConfig": {
        "guardrailIdentifier": gid, "guardrailVersion": GUARDRAIL_VERSION, "trace": "enabled"}}
    return runtime.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": text}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0}, **kw)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cmd_send(args, *, now: Callable[[], datetime] = _now) -> int:
    man = P.manifest()
    words = P.configured_words(man)
    manip = manipulation_check(words)
    if not manip["ok"]:
        print(f"FATAL: the two prompts do not differ as designed: {manip}", file=sys.stderr)
        return 1
    p = prompts(words)
    print(f"F10-1 send: {N_PER_ARM} per arm x {len(ARMS)} arms, interleaved, "
          f"word {manip['word']!r}")
    print(f"  input  prompt: {p[ARM_INPUT]}")
    print(f"  output prompt: {p[ARM_OUTPUT]}")
    print(f"  control      : the output prompt, with no guardrail")
    if args.dry_run:
        print("dry run: no call made")
        return 0
    if now() < NOT_BEFORE:
        print(f"REFUSED: the cost allocation tag may not apply before {NOT_BEFORE:%Y-%m-%dT%H:%MZ}"
              f" (now {now():%Y-%m-%dT%H:%MZ}); a request sent now may never reach its "
              f"tag's bill", file=sys.stderr)
        return 1
    if SENDS_PATH.exists():
        print(f"REFUSED: {SENDS_PATH.relative_to(ROOT)} already exists; a second send would "
              f"double the bill the rows describe", file=sys.stderr)
        return 1

    fc = A.factory(REGION)
    redact.register_account_id(A.account_id(fc))
    gid = P.guardrail(GUARDRAIL_KEY, man=man)
    runtime = fc.bedrock_runtime()
    arns = profile_arns(fc.bedrock())
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    pre = converse(runtime, SYSTEM_PROFILE, gid, p[ARM_OUTPUT])
    pre_row = summarize(pre, arm=ARM_OUTPUT, rep=-1, sent_at=now().isoformat())
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    (EVIDENCE_DIR / f"preflight-{stamp}.json").write_text(json.dumps(pre, default=str, indent=2))
    if landed_arm(pre_row) != ARM_OUTPUT:
        print(f"STOPPED: the pre-flight call was not output-blocked: {pre_row}. The output "
              f"arm would not be the treatment it names; nothing counted was sent.",
              file=sys.stderr)
        return 2
    print(f"  pre-flight (untagged system profile): output-blocked on "
          f"{pre_row['output_blocked_words']}")

    rows, raw = [], []
    for rep in range(N_PER_ARM):
        for arm in (ARMS[rep % 3:] + ARMS[:rep % 3]):  # rotate the order per rep
            sent_at = now().isoformat()
            resp = converse(runtime, arns[arm], None if arm == ARM_CONTROL else gid, p[arm])
            raw.append(resp)
            row = summarize(resp, arm=arm, rep=rep, sent_at=sent_at)
            rows.append(row)
            print(f"  {arm:15s} rep {rep:2d}: {row['stop_reason']}, landed "
                  f"{landed_arm(row)}, tokens {row['input_tokens']}/{row['output_tokens']}")
            time.sleep(0.2)
    (EVIDENCE_DIR / f"sends-raw-{stamp}.json").write_text(json.dumps(raw, default=str, indent=2))
    body = {"case_id": CASE, "tag_key": TAG_KEY, "profiles": arns, "guardrail_id": gid,
            "guardrail_version": GUARDRAIL_VERSION, "model_source": SYSTEM_PROFILE,
            "prompts": {a: p[a] for a in ARMS}, "manipulation_check": manip,
            "preflight": pre_row, "rows": rows, "sdk": A.sdk_versions()}
    SENDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENDS_PATH.write_text(redact.mask_text(json.dumps(_mask(body), indent=2, sort_keys=True))
                          + "\n", encoding="utf-8")
    wrong = [r for r in rows if landed_arm(r) != r["arm"]]
    print(f"\nwrote {SENDS_PATH.relative_to(ROOT)}: {len(rows)} rows, "
          f"{len(wrong)} landed in the wrong arm")
    return 0 if not wrong else 2


def cmd_read(args, *, now: Callable[[], datetime] = _now) -> int:
    sends = json.loads(SENDS_PATH.read_text(encoding="utf-8"))
    rows = sends["rows"]
    last = max(datetime.fromisoformat(r["sent_at"]) for r in rows)
    first = min(datetime.fromisoformat(r["sent_at"]) for r in rows)
    if now() - last < READ_LAG:
        print(f"REFUSED: the last request was sent at {last:%Y-%m-%dT%H:%MZ}; Cost Explorer "
              f"lags about {READ_LAG}", file=sys.stderr)
        return 1
    start = first.date()
    end = min(now().date(), last.date() + timedelta(days=3))
    fc = A.factory(REGION)
    ce = fc.client("ce")
    req = {"TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
           "Granularity": "DAILY", "Metrics": ["UnblendedCost", "UsageQuantity"],
           "Filter": {"Tags": {"Key": TAG_KEY, "Values": list(ARMS)}},
           "GroupBy": [{"Type": "TAG", "Key": TAG_KEY},
                       {"Type": "DIMENSION", "Key": "USAGE_TYPE"}]}
    pages, token = [], None
    while True:
        resp = ce.get_cost_and_usage(**req, **({"NextPageToken": token} if token else {}))
        pages.append(resp)
        token = resp.get("NextPageToken")
        if not token:
            break
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / f"ce-read-{stamp}.json").write_text(
        json.dumps({"request": req, "pages": pages}, default=str, indent=2))

    bill = billed(pages)
    d = decide(rows, bill)
    for arm in ARMS:
        print(f"  {arm:15s} billed tokens {d['billed_tokens'][arm]}  reported "
              f"{d['reported_tokens'][arm]}")
    print(f"  status: {d['status']}")
    if d["status"] == "undecided" and not args.final:
        print("  the positive control has no billed usage yet; re-run `read` later, or "
              "`read --final` to record INCONCLUSIVE", file=sys.stderr)
        return 3

    if d["status"] == "decided":
        rec = O.evaluate(P.obs_existence(CASE, d["observed"], n=len(rows),
                                         input_arm_zero=d["input_arm_zero"],
                                         output_arm_full=d["output_arm_full"]))
    elif d["status"] == "fault":
        rec = O.not_measured(CASE, "instrument fault: rows landed in the wrong arm, the "
                                   "bill's unit did not check out, or the control arm's "
                                   "bill did not match its own usage", detail=d)
    else:
        rec = O.not_measured(CASE, "the positive control (unguarded control arm) showed no "
                                   "billed usage, so the tag's reach is not established",
                             detail=d)
    # The observation is the sends, so the record's observation days are the first and last
    # send. The read's own time is deliberately absent: Cost Explorer reporting on a later day
    # is the same observation, and counting it would make one day read as two to the
    # replication rule (check_amendment_readiness.py, >= 2 calendar days).
    P.emit(CASE, rec, {"t0_iso": first.isoformat(), "t1_iso": last.isoformat(),
                       "design": "f10_billing/F10-1-DESIGN.md",
                       "sends": str(SENDS_PATH.relative_to(ROOT)),
                       "cost_explorer_request": req, "billing": d,
                       "sdk": A.sdk_versions()})
    return 0 if d["status"] == "decided" else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=CASE, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send")
    s.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("read")
    r.add_argument("--final", action="store_true",
                   help="record INCONCLUSIVE if the positive control is still unbilled")
    args = ap.parse_args(argv)
    return cmd_send(args) if args.cmd == "send" else cmd_read(args)


if __name__ == "__main__":
    sys.exit(main())
