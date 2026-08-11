#!/usr/bin/env bash
# F5-7a Day 2: wait for UTC midnight, replicate, compare, and record the verdict.
#
# Why a script that sleeps rather than a command I run later
# ---------------------------------------------------------
# The §4.5.3 amendment needs observations on two separate calendar days, and the first
# attempt at Day 2 failed for a reason worth encoding: the *local* calendar had rolled
# to the 10th while UTC was still 2026-08-09T16:20, so a 6.8-hour repeat was minted as
# `r20260810T0930Z`. Evidence records carry UTC and the replication rule counts UTC
# days, so it was the same day. `lib/evidence.new_run_id` now refuses that name and
# `07a_compare_runs.py` refuses that pair, but neither makes the *waiting* happen.
#
# So the wait is computed from UTC here, once, instead of being a thing to remember at
# the right hour. Run it detached; it does nothing until UTC crosses midnight.
#
# Cost: $0. DescribeVpcEndpointServices is unmetered and creates nothing; the two doc
# fetches are HTTP GETs.
#
# Exit codes: 0 replicated (the amendment is unblocked) · 1 the two days disagree
# (a finding in its own right — do NOT amend) · 2 the run or comparison could not
# complete.

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2
ROOT="$PWD"
PY="${PYTHON:-python3}"
DAY1="${DAY1:-r20260809T094500Z}"
LOG="$ROOT/results/f5_7a_day2.log"

if [ ! -d "evidence/$DAY1" ]; then
  echo "FATAL: DAY1 run evidence/$DAY1 does not exist — there is nothing to replicate" >&2
  exit 2
fi

# Target 00:20Z rather than 00:00Z. A run that straddles midnight would write records
# on both sides of the boundary, and `observation_day` takes the earliest — so a
# 00:00:00 start could silently produce a same-day pair again.
target_epoch=$("$PY" - <<'EOF'
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
tgt = (now + timedelta(days=1)).replace(hour=0, minute=20, second=0, microsecond=0)
# Already past today's 00:20Z with a day-1 run from an earlier UTC day? Go now.
print(int(tgt.timestamp()))
EOF
)
now_epoch=$(date -u +%s)

day1_utc=$("$PY" - "$DAY1" <<'EOF'
import json, pathlib, sys
base = pathlib.Path("evidence") / sys.argv[1] / "f5" / "F5-7a"
days = set()
for f in sorted(base.glob("*.json")):
    if f.name in ("environment.json", "analysis.json", "summary.json"):
        continue
    try:
        ts = json.loads(f.read_text()).get("t_start_utc")
    except Exception:
        continue
    if ts:
        days.add(str(ts)[:10])
print(sorted(days)[0] if days else "")
EOF
)
today_utc=$(date -u +%F)

if [ -z "$day1_utc" ]; then
  echo "FATAL: $DAY1 has no dated evidence records" >&2
  exit 2
fi

# If UTC has already moved past day 1's date, no waiting is needed.
if [ "$today_utc" != "$day1_utc" ]; then
  echo "UTC today ($today_utc) already differs from day 1 ($day1_utc) — running now"
else
  wait_s=$(( target_epoch - now_epoch ))
  [ "$wait_s" -lt 0 ] && wait_s=0
  printf 'day 1 = %s, UTC now = %s. Sleeping %d s (%.2f h) until %s\n' \
    "$day1_utc" "$(date -u '+%FT%TZ')" "$wait_s" \
    "$("$PY" -c "print($wait_s/3600)")" \
    "$(date -u -r "$target_epoch" '+%FT%TZ' 2>/dev/null || echo 00:20Z)"
  sleep "$wait_s"
fi

RUN_ID="r$(date -u +%Y%m%dT%H%M%SZ)"
echo "=== F5-7a day 2: $RUN_ID (UTC $(date -u '+%FT%TZ')) ===" | tee -a "$LOG"

# Re-assert the day separation AFTER the sleep. The clock is the one input that
# changed while we were not looking, and a sleep that returns early (SIGCONT, a
# suspended laptop resuming) would otherwise run on the wrong day.
if [ "$(date -u +%F)" = "$day1_utc" ]; then
  echo "FATAL: UTC is still $day1_utc after the wait — refusing to collect a same-day" >&2
  echo "       repeat and label it a replication" >&2
  exit 2
fi

"$PY" f5_redteam/07a_privatelink_enum.py --run-id "$RUN_ID" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then
  echo "FATAL: the day-2 collection exited $rc; nothing to compare" | tee -a "$LOG" >&2
  exit 2
fi

"$PY" f5_redteam/07a_compare_runs.py "$DAY1" "$RUN_ID" \
      --json results/f5_7a_replication.json 2>&1 | tee -a "$LOG"
crc=${PIPESTATUS[0]}

if [ "$crc" -eq 0 ]; then
  echo "REPLICATED — flip FINDING-F5-7A provenance to READY_TO_AMEND" | tee -a "$LOG"
else
  echo "NOT REPLICATED (rc=$crc) — the disagreement is itself the finding; do not amend" \
    | tee -a "$LOG"
fi
exit "$crc"
