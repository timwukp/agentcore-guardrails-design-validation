#!/usr/bin/env python3
"""Account-field masking for everything written into `results/`.

Why this module exists, and why it is not two edits at two call sites
--------------------------------------------------------------------
`ApplyGuardrail` returns `assessments[].appliedGuardrailDetails.guardrailArn`, and
`GetGuardrail` returns `crossRegionDetails.guardrailProfileArn`. Both embed the account
ID. Both are *load-bearing evidence*: F8-6's entire instrument is the Region field of
that ARN, so the answer cannot be "stop recording it".

The first live Phase 1 run therefore wrote the account ID into **82 files and 1,122
lines** under `results/`, and the redaction gate caught it — correctly, and only after
the fact. Hand-editing those files would have been the second-instance defect in
`feedback_second_instance_bugs`: the next run, and every run after it, re-creates them,
because the leak is not in the files but in the path that writes them.

So the mask is applied at the **two writers into `results/`** — `Checkpoint.save()` and
`phase1.emit()` — rather than at the call sites that happen to read an ARN today. A new
case that records a new ARN-bearing field inherits the mask without knowing it exists,
which is the only version of this that survives a case being added by someone who has
not read this file.

`evidence/` is deliberately NOT masked
--------------------------------------
The evidence tree is the local audit archive whose whole purpose is that a claim can be
taken to AWS Support and looked up (see `evidence.py`'s docstring). A masked ARN there
would defeat that. It is excluded from the redaction gate by directory, and that
exclusion is now stated as a decision in `check_redaction.py` rather than looking like an
oversight — the gate's own docstring previously claimed to scan "JSON evidence" while
`SKIP_DIRS` excluded it, which is exactly the kind of contradiction that gets resolved in
the wrong direction later.

What is preserved, deliberately
-------------------------------
The ARN keeps its six-colon shape and every other field: partition, service, Region,
resource type and resource id all survive, and only the account field is replaced by
`ACCOUNT_PLACEHOLDER`.

No example ARN is written out here. An earlier draft of this docstring spelled one with a
literal twelve-digit account field to be illustrative, and thereby created two fresh
redaction findings *inside the module whose job is to prevent them* — the same mistake
`check_redaction.py`'s own ALLOW comment records making. The round trip is asserted in
`lib/tests/test_redact.py` instead, where a fixture is data rather than prose.

`f8_regional/05_xregion.py`'s `region_of`/`partition_of` read `parts[3]`/`parts[1]` of a
`split(":")`, so field *positions* must not move. A mask that dropped the field would
shift the Region into the account slot and silently re-label every trial's serving
Region — turning a redaction fix into a data corruption. Verified by test: masking is
idempotent and leaves `region_of` and `partition_of` unchanged.
"""

from __future__ import annotations

import re
from typing import Any

# The account field of an ARN: the 5th colon-delimited field. Anchored on the four
# fields before it rather than on `\b\d{12}\b` alone, so a 12-digit corpus fixture or a
# UUID tail elsewhere on the same line is not touched — this function's job is ARNs, and
# a broader substitution would corrupt PII corpus rows on their way into a checkpoint.
#
# The account field is optional-and-empty in some services' ARNs (S3), so `\d{12}` is
# matched rather than `[^:]*`: an already-empty field is left exactly as it is.
_ARN_ACCOUNT = re.compile(
    r"(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)(\d{12})(:)")

ACCOUNT_PLACEHOLDER = "<account>"


def mask_text(s: str) -> str:
    """Replace the account field of every ARN in `s`. Idempotent."""
    return _ARN_ACCOUNT.sub(rf"\g<1>{ACCOUNT_PLACEHOLDER}\g<3>", s)


def mask(obj: Any) -> Any:
    """Recursively mask ARN account fields in a JSON-shaped structure.

    Keys are masked as well as values. A checkpoint's `failed` map is keyed by trial id
    and its *values* hold error messages that quote the endpoint URL and ARN, but a
    future record keyed by an ARN would otherwise slip past a values-only walk.

    Containers are rebuilt rather than mutated in place: `Checkpoint.save()` masks on the
    way to disk and must not alter the in-memory record the running arm is still
    appending to. A mutating version would make the mask observable to the analysis,
    which is the one place the true ARN still has to be readable.
    """
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {mask(k) if isinstance(k, str) else k: mask(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(mask(v) for v in obj)
    return obj
