#!/usr/bin/env python3
"""Phase 2 testbed state: what was created, so later phases and teardown can find it.

Why a state file exists at all, when `f3_efficacy/00_guardrails.py` deliberately refused one
--------------------------------------------------------------------------------------------
That script's docstring argues *against* a state file, and the argument is correct there: it
provisions guardrails whose names are a pure function of the run id, so `ListGuardrails` **is**
the state and a file could only ever disagree with it.

Phase 2 is not that shape, and the difference is not stylistic:

* A gateway's `policyEngineConfiguration.arn` points at a policy engine, and a policy points
  at an engine id. **Neither relationship is recoverable from a name.** `grx-gw-<runid>` and
  `grx-pe-<runid>` share a run id, but "the engine this gateway was pointed at" is a fact about
  a past API call, and F5-2 needs to restore exactly that value after mutating it.
* Six of the ten resource kinds here are named by the *service*, not by us:
  `policyEngineId`, `policyId`, `gatewayId` and the gateway URL all carry a service-generated
  suffix (`grx-pe-r2026...-las2q9c1tz`). A later phase cannot reconstruct them, only look them
  up — and looking up by name prefix across four services on every script start is the same
  work as reading one file, with more ways to match the wrong row.
* The gateway URL is required to invoke a tool and appears in **no** list operation.

So the state file records *identifiers and relationships*, and does **not** record status:
status is read live, because a file saying READY is a claim about the past.

The state file is NOT the teardown's source of truth
----------------------------------------------------
This is the load-bearing design decision, and it is the reverse of what a state file usually
means. `99_teardown.py` sweeps **by tag**, and this file is only a cross-check. The reason is
that the failure mode a teardown must survive is precisely the one that corrupts a state file:
a script killed between `create_gateway` returning and `state.write()` completing has made a
real resource that no file names. A tag sweep finds it; a state-file-driven teardown cannot,
and would report success.

Running both and **comparing them** is strictly better than either, because the comparison
detects the two silent failures neither channel sees alone:

* in state, absent from the sweep  -> the resource is untagged, or the tagging index does not
  cover its type. Either way the sweep's "zero survivors" is unproven for that type.
* in the sweep, absent from state  -> an orphan from an earlier killed run.

The first of those is not hypothetical here. Read-only probing on 2026-08-10 established that
`resourcegroupstaggingapi` indexes 69 `bedrock-agentcore` resources across five types
(`harness`, `runtime`, `online-evaluation-config`, `workload-identity-directory`, `memory`) and
**zero of type `gateway`** — while all six pre-existing gateways in this account carry no tags
at all. Those two facts do not distinguish "gateways are not indexed" from "no tagged gateway
has ever existed here", so the sweep cannot be trusted for gateways until a tagged one is
created and looked up. `99_teardown.py` therefore treats an indexed-but-not-found gateway as a
**finding about the index**, not as a clean result.

Redaction
---------
`state.json` lives at the repo root and is scanned by `check_redaction.py`, so ARNs are stored
account-masked via `lib/redact.py`. Everything the later phases need is preserved by that mask:
it replaces only the account field and leaves partition, service, Region, type and id intact
(`f8_regional/05_xregion.py` reads `parts[1]`/`parts[3]` positionally). The unmasked ARNs
remain in `evidence/`, which is the local-only audit archive.

An ARN with a masked account cannot be *passed back* to an API, so anything a later phase must
send — the policy engine ARN a gateway points at — is recorded as its plain **id** as well, and
the ARN is reconstructed at use time from the caller's own account. A masked ARN in an API call
would fail with a validation error, which is the honest failure; silently accepting it would be
worse.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import redact  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state.json"

# Resource kinds MEASURED to be absent from the tagging API's index in us-east-1, with the
# evidence. This replaces a constant named `SWEEP_TYPE_FILTERS` that listed
# ("bedrock", "bedrock-agentcore", "lambda", "iam") and described itself as "the resource-type
# filters the teardown sweep uses" — which nothing used (DEV-P2-07).
#
# `sweep_by_tag()` below passes `TagFilters` only and no `ResourceTypeFilters`, so the sweep was
# never type-restricted. Three files nevertheless reasoned FROM that constant, concluding that
# every `logs` resource was invisible to the tag channel because `logs` was not in the list. The
# measurement says the opposite: every one of this run's 9 ARN-bearing `logs` resources IS
# indexed, and the two types actually missing are ones the list claimed were covered. (9, not
# 13: the ledger holds 13 `logs` rows, but the 4 `delivery` rows record no ARN, so they are
# cross-checkable in neither direction and are counted separately below rather than folded into
# a numerator — `feedback_label_must_match_computation`.)
#
# Measured 2026-08-10, us-east-1, run r20260810T130945Z (ledger cross-check per kind):
#
#   indexed:      gateway 2/2, policy-engine 1/1, lambda 1/1, log-group 2/2,
#                 delivery-source 4/4, delivery-destination 3/3   (9/9 of the `logs` kinds)
#   NOT indexed:  iam-role 0/5, policy 0/1
#   no ARN in the ledger, so not cross-checkable in either direction: delivery (4), gateway-target
#                 — reported as a separate count, never folded into a coverage numerator
#
# The rule this encodes: a kind belongs here only with a measurement and a named replacement
# channel, and `06_verify.py` re-tests each entry's premise on every run so an entry cannot
# outlive its cause.
TAG_INDEX_BLIND_KINDS = {
    "iam-role": "681 roles in the account, 102 carrying >=1 tag, 0 returned by "
                "get_resources(ResourceTypeFilters=['iam:role']); filter 'iam' does return 3 rows "
                "(2 instance-profile, 1 oidc-provider), so the gap is iam:role specifically. "
                "Replacement channel: list_role_tags per role.",
    "policy": "structurally untaggable: CreatePolicy has no `tags` input member, and TagResource "
              "on a policy ARN returns AccessDenied for an AdministratorAccess principal while "
              "the same action succeeds on a gateway ARN. Replacement channel: get_policy.",
}


@dataclass
class Resource:
    """One created resource: what it is, how to delete it, how to find it again.

    `delete_op` and `delete_params` are stored as **data, not a closure**, for the same reason
    `lib/mutation_journal.py` will store undo intent as data: a teardown that must run in a
    *different process* from the one that created the resource (because the first was killed)
    cannot deserialize a Python function. A dict of operation name plus kwargs can be replayed
    by any process that can build a client.
    """

    kind: str                     # "iam-role", "lambda", "policy-engine", "gateway", ...
    logical: str                  # our stable name for it: "gw-exec", "echo", "gw-main"
    name: str                     # the AWS-visible name we chose
    service: str                  # boto3 client name to delete it with
    delete_op: str                # e.g. "delete_gateway"
    delete_params: dict           # e.g. {"gatewayIdentifier": "grx-gw-...-abc"}
    ids: dict = field(default_factory=dict)     # service-generated ids we cannot derive
    arn: str = ""                 # account-masked
    created_at: str = ""
    # Deletion order matters and is not derivable from `kind`: a gateway target must go before
    # its gateway, a gateway before the policy engine it references, a policy before its
    # engine, and an IAM role's inline policies before the role. Lower runs first.
    delete_priority: int = 50
    notes: str = ""

    def to_json(self) -> dict:
        return redact.mask({
            "kind": self.kind, "logical": self.logical, "name": self.name,
            "service": self.service, "delete_op": self.delete_op,
            "delete_params": self.delete_params, "ids": self.ids, "arn": self.arn,
            "created_at": self.created_at, "delete_priority": self.delete_priority,
            "notes": self.notes,
        })

    @classmethod
    def from_json(cls, d: dict) -> "Resource":
        return cls(kind=d["kind"], logical=d["logical"], name=d["name"],
                   service=d["service"], delete_op=d["delete_op"],
                   delete_params=d.get("delete_params") or {}, ids=d.get("ids") or {},
                   arn=d.get("arn", ""), created_at=d.get("created_at", ""),
                   delete_priority=d.get("delete_priority", 50), notes=d.get("notes", ""))


class State:
    """The testbed's resource ledger. Append-only within a run; keyed by (kind, logical).

    Written after **every** create, not once at the end. The window between a successful
    create and a recorded create is exactly the window in which a kill produces an untracked
    resource, so the goal is to make that window as short as the filesystem allows. It cannot
    be closed — the create returns before any code runs — which is why the tag sweep, and not
    this file, is teardown's primary channel.
    """

    def __init__(self, run_id: str, region: str, expires_at: str,
                 path: Path | None = None) -> None:
        self.run_id = run_id
        self.region = region
        self.expires_at = expires_at
        self.path = path or STATE_PATH
        self.resources: dict[tuple[str, str], Resource] = {}
        self.account_masked = True

    # -- persistence -------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "State":
        p = path or STATE_PATH
        if not p.exists():
            raise FileNotFoundError(
                f"{p} does not exist. Phase 2 has not been run, or was run with a different "
                f"--state path. Later phases must not invent resource names: run "
                f"`infra/01_iam.py --ensure` onward first.")
        d = json.loads(p.read_text(encoding="utf-8"))
        s = cls(d["run_id"], d["region"], d["expires_at"], path=p)
        for row in d.get("resources") or []:
            r = Resource.from_json(row)
            s.resources[(r.kind, r.logical)] = r
        return s

    @classmethod
    def load_or_new(cls, run_id: str, region: str, expires_at: str,
                    path: Path | None = None) -> "State":
        """Resume an existing ledger, or start one.

        Resuming keeps the run id from the FILE, not the argument, and raises if they
        disagree. Two run ids in one ledger would tag half the resources with each, and the
        teardown sweep filters by `RunId` — so the mismatch would leave a subset permanently
        invisible to a sweep for either value.
        """
        p = path or STATE_PATH
        if not p.exists():
            return cls(run_id, region, expires_at, path=p)
        s = cls.load(p)
        if s.run_id != run_id:
            raise ValueError(
                f"{p} was written by run {s.run_id!r} but this invocation is {run_id!r}. Two "
                f"run ids in one ledger would split the RunId tag across resources and leave "
                f"half of them invisible to any single teardown sweep. Pass "
                f"--run-id {s.run_id} to continue that run, or --state <other path>.")
        if s.region != region:
            raise ValueError(
                f"{p} is for region {s.region!r}, not {region!r}. A cross-region ledger would "
                f"make the teardown sweep — which is per-region — silently partial.")
        # `expires_at` is deliberately NOT overwritten on resume: the tag on already-created
        # resources still carries the original value, and a ledger claiming a later expiry
        # than the tags would misreport which resources are orphans.
        return s

    def write(self) -> Path:
        rows = sorted((r.to_json() for r in self.resources.values()),
                      key=lambda r: (r["delete_priority"], r["kind"], r["logical"]))
        payload = {
            "run_id": self.run_id,
            "region": self.region,
            "expires_at": self.expires_at,
            "written_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "account_masked": True,
            "n_resources": len(rows),
            "resources": rows,
        }
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        # Atomic: a kill mid-write must not truncate the ledger to zero resources, which would
        # read as "nothing was created" — the one lie teardown cannot recover from on its own.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path

    # -- recording ---------------------------------------------------------

    def record(self, resource: Resource) -> Resource:
        """Add or replace a resource and flush immediately."""
        if not resource.created_at:
            resource.created_at = (datetime.now(timezone.utc)
                                   .replace(microsecond=0).isoformat())
        resource.arn = redact.mask_text(resource.arn or "")
        self.resources[(resource.kind, resource.logical)] = resource
        self.write()
        return resource

    def get(self, kind: str, logical: str) -> Resource:
        try:
            return self.resources[(kind, logical)]
        except KeyError:
            have = sorted(f"{k}/{l}" for k, l in self.resources)
            raise KeyError(
                f"no {kind}/{logical} in {self.path.name}. Present: {have}. A later phase "
                f"must not fall back to a guessed name — a guess that happens to match "
                f"another run's resource would attribute its behaviour to this run."
            ) from None

    def find(self, kind: str, logical: str) -> Resource | None:
        return self.resources.get((kind, logical))

    def of_kind(self, kind: str) -> list[Resource]:
        return [r for (k, _), r in sorted(self.resources.items()) if k == kind]

    def drop(self, kind: str, logical: str) -> None:
        """Remove a resource from the ledger, after it has actually been deleted."""
        self.resources.pop((kind, logical), None)
        self.write()

    # -- derived -----------------------------------------------------------

    def deletion_order(self) -> list[Resource]:
        """Resources in an order that respects reference constraints.

        Ties broken by `created_at` **descending** — newest first — because within one
        priority band a later resource is the more likely to reference an earlier one.
        """
        return sorted(self.resources.values(),
                      key=lambda r: (r.delete_priority, _neg_str(r.created_at)))


def _neg_str(s: str) -> tuple:
    """Sort key that reverses a string's order within an otherwise ascending sort."""
    return tuple(-ord(c) for c in s)


def unmask_arn(masked: str, account_id: str) -> str:
    """Restore a real ARN from a masked one, for a value that must be sent to an API.

    Deliberately explicit at each call site rather than done on load. A masked ARN that
    reaches an API call fails loudly with a validation error; a silently unmasked ledger
    would put real account ids back into anything that then serializes state, which is the
    leak `lib/redact.py` exists to stop (82 files, 1,122 lines — DEV-P1-13).
    """
    if not masked:
        return ""
    if redact.ACCOUNT_PLACEHOLDER not in masked:
        return masked
    if not account_id or not account_id.isdigit() or len(account_id) != 12:
        raise ValueError(
            f"account_id must be the 12-digit account to restore {masked!r}; got "
            f"{account_id!r}")
    return masked.replace(f":{redact.ACCOUNT_PLACEHOLDER}:", f":{account_id}:", 1)


def policy_engine_arn(region: str, account_id: str, engine_id: str) -> str:
    """Build a policy engine ARN from its id.

    Exists because `CreateGateway.policyEngineConfiguration.arn` requires a real ARN and the
    ledger stores a masked one. Reconstructing from the id plus the *caller's* account is
    sounder than unmasking: it cannot silently carry another account's identifier, and it
    fails if the id is empty rather than sending a well-formed ARN for a resource that does
    not exist.
    """
    if not engine_id:
        raise ValueError("engine_id is required to build a policy engine ARN")
    if not account_id or not account_id.isdigit():
        raise ValueError(f"account_id must be 12 digits, got {account_id!r}")
    return f"arn:aws:bedrock-agentcore:{region}:{account_id}:policy-engine/{engine_id}"


def check_name(client, operation: str, name: str, member: str = "name") -> str:
    """Validate a resource name against the SDK's own regex before spending a live call.

    Why this exists (DEV-P2-02)
    ---------------------------
    `CreatePolicyEngine` rejected `grx-pe-<runid>` with a ValidationException: policy engine and
    policy names must match `^[A-Za-z][A-Za-z0-9_]*$` — **no hyphens** — while gateways and
    gateway targets take `([0-9a-zA-Z][-]?){1,48}`, which does allow them. Two naming rules on
    one service, and the project had picked one convention for both.

    The failure cost a live call and a half-built testbed, and it was **entirely detectable
    offline**: the pattern is in the botocore service model, which this project already reads for
    F1-1's version bisect. A constraint that ships with the SDK and is discovered from a 400 is a
    constraint nobody checked (`feedback_verify_against_real_artifact`).

    So the check is derived from the model rather than from a copy of the regex here. A hard-coded
    pattern would be a second source of truth that drifts silently at the next botocore bump — and
    "the SDK says X" is the claim, so the SDK must be the one asserting it.

    Raises `ValueError` with the operation, pattern and offending name. Returns `name` unchanged
    when valid, so it can wrap a name at its point of use.
    """
    try:
        shape = client.meta.service_model.operation_model(operation).input_shape
        meta = shape.members[member].metadata
    except Exception:                                        # noqa: BLE001
        # An unknown operation or member means the model changed shape. Returning the name is the
        # right failure direction: this helper's job is to convert a remote 400 into a local
        # error, never to become a new way to block a call the service would have accepted.
        return name
    pattern = meta.get("pattern")
    lo, hi = meta.get("min"), meta.get("max")
    problems = []
    if pattern and not re.fullmatch(pattern, name or ""):
        problems.append(f"does not match {pattern!r}")
    if lo is not None and len(name or "") < lo:
        problems.append(f"is shorter than min={lo}")
    if hi is not None and len(name or "") > hi:
        problems.append(f"is longer than max={hi} (len={len(name or '')})")
    if problems:
        raise ValueError(
            f"{operation}.{member} = {name!r} {', and '.join(problems)}. This constraint is in "
            f"the botocore service model, so it is checkable offline; sending it would spend a "
            f"live call to be told the same thing by a ValidationException. Note that "
            f"bedrock-agentcore uses TWO name grammars: policy engines and policies forbid "
            f"hyphens, gateways and gateway targets allow them.")
    return name


def sweep_by_tag(factory, run_id: str | None = None, *,
                 project: str = "guardrails-doc-validation") -> list[dict[str, Any]]:
    """Every resource the tagging API reports for this project, optionally one run.

    The teardown's PRIMARY channel: it finds resources whose creation was never recorded,
    which is the failure a ledger structurally cannot cover.

    Returns raw ARNs (unmasked) because the caller deletes with them; masking happens on the
    way into any file.

    `run_id=None` deliberately sweeps the whole project, across runs. That is what finds an
    orphan from a killed earlier run, and it is why `99_teardown.py` prints a per-run
    breakdown rather than a single count: deleting another run's live resources would be
    worse than leaving an orphan.
    """
    client = factory.client("resourcegroupstaggingapi")
    filters = [{"Key": "Project", "Values": [project]}]
    if run_id:
        filters.append({"Key": "RunId", "Values": [run_id]})
    out: list[dict[str, Any]] = []
    token = None
    while True:
        kw: dict[str, Any] = {"TagFilters": filters, "ResourcesPerPage": 100}
        if token:
            kw["PaginationToken"] = token
        resp = client.get_resources(**kw)
        for row in resp.get("ResourceTagMappingList") or []:
            arn = row["ResourceARN"]
            out.append({
                "arn": arn,
                "service": arn.split(":")[2] if arn.count(":") >= 2 else "",
                "type": _arn_type(arn),
                "tags": {t["Key"]: t["Value"] for t in row.get("Tags") or []},
            })
        token = resp.get("PaginationToken")
        if not token:
            break
    return sorted(out, key=lambda r: r["arn"])


def _arn_type(arn: str) -> str:
    """The resource type of an ARN: the segment before the first `/` in field 6."""
    parts = arn.split(":", 5)
    if len(parts) < 6:
        return ""
    tail = parts[5]
    return tail.split("/")[0] if "/" in tail else tail.split(":")[0]
