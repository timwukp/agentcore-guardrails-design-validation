"""Mutation tests for `99_teardown.py`'s two safety gates. Offline.

Why this file exists and what it is guarding against
----------------------------------------------------
Teardown is the only script in this project that **destroys**, and it runs against an account
holding six live READY gateways, ~28 `harness_*`/`ui-test`/`bug-fix` CloudWatch delivery
resources, three pre-existing DRAFT guardrails and the two abandoned June-2026 policy engines
that are F1-3's read-only evidence. The isolation rule is written in the plan as prose. These
tests are the reason it is also true.

Both gates were **found defective by measurement**, not by review, and each defect has a test
here that fails against the original code:

1. `PROTECTED_SUBSTRINGS` listed `harness_` (underscore) because the runtimes are named that
   way. The delivery resources those runtimes own are named `harness-finance-traces`,
   `ui-test-traces-source`, `bug-fix-app-logs-source` — with hyphens. A literal match protected
   **0 of the 84** pre-existing delivery resources in this account.
   `test_protection_covers_every_preexisting_delivery_name` pins the real names.
2. A deny-list cannot enumerate what nobody thought of. The three pre-existing DRAFT guardrails
   are named `demo`, `test` and `demo123`; no substring in the list matches them and none
   reasonably could. `not_ours()` is the allow-list backing the deny-list, and
   `test_deny_list_alone_does_not_protect_the_draft_guardrails` asserts the deny-list's failure
   directly so nobody later "simplifies" the allow-list away believing the deny-list covers it.

`test_no_guard_is_vacuous` is the one that matters most (`feedback_vacuous_test_check`): every
test above can be defeated the same way — by making `protected()` or `not_ours()` return truthy
for everything, which would pass every "is it protected" assertion while making teardown
incapable of deleting the testbed. So the guards are checked in **both** directions.

The name fixtures are the account's **real** names, recorded from live `describe_*` calls
(`feedback_verify_against_real_artifact`). A hand-invented `harness-foo` would only confirm my
own idea of the naming convention, and the convention is exactly what the first defect was about.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from infra_by_path import load_infra

ROOT = Path(__file__).resolve().parents[2]

td = load_infra("99_teardown")


# The account's real delivery-resource names, read from describe_delivery_sources /
# _destinations / _deliveries. 84 resources across 28 source names; the distinct prefixes are
# what matter, so one representative per family is pinned plus the two that motivated the fix.
REAL_PREEXISTING = [
    "bug-fix-traces-source", "bug-fix-app-logs-source",
    "ui-test-traces-source", "ui-test-app-logs-source",
    "harness-finance-app-logs", "harness-finance-traces",
    "harness-healthcare-traces", "harness-insurance-app-logs",
    "harness-llmops_data_prep-KuSKXUaxyP-traces",
    "harness-llmops_deploy-nLLNWairTc-app-logs",
    "harness-llmops_eval-iuIIs96fFM-traces",
]

# The six live gateways and the two abandoned policy engines, verbatim from list_gateways /
# list_policy_engines.
REAL_GATEWAYS = ["finance-trading-gw", "healthcare-medical-gw", "insurance-claims-gw",
                 "manufacturing-maintenance-gw", "real-estate-valuation-gw",
                 "retail-inventory-gw"]
REAL_ENGINES = ["agentcore_test_pe_92a0735a", "agentcore_test_pe_e263a8a9"]

# The three pre-existing DRAFT guardrails. Named nothing in particular, which is the point.
REAL_DRAFT_GUARDRAILS = ["demo", "test", "demo123"]

# Names this project creates. Every one of these must be deletable by both gates.
OURS = [
    "grx-gw-r20260810T0345Z", "grx-gw-nopolicy-r20260810T0345Z",
    "grx-echo-r20260810T0345Z", "grx-gw-exec-r20260810T0345Z",
    "grx-caller-r20260810T0345Z", "grx-pe-r20260810T0345Z",
    "grx-main-traces-src-r20260810T0345Z", "grx-shared-traces-dst-r20260810T0345Z",
    "grx-gr-cf-high-r20260810T011502Z",
]


@pytest.mark.parametrize("name", REAL_PREEXISTING)
def test_protection_covers_every_preexisting_delivery_name(name):
    """The defect that motivated the separator normalization. Fails against the original list."""
    assert td.protected(name), (
        f"{name!r} is a pre-existing CloudWatch delivery resource owned by another system in "
        f"this account and it is NOT protected. With the original literal-match list, 0 of 84 "
        f"such resources matched.")


@pytest.mark.parametrize("name", REAL_GATEWAYS + REAL_ENGINES)
def test_protection_covers_gateways_and_abandoned_engines(name):
    assert td.protected(name), f"{name!r} must never be deletable by this project"


@pytest.mark.parametrize("name", REAL_DRAFT_GUARDRAILS)
def test_deny_list_alone_does_not_protect_the_draft_guardrails(name):
    """Asserts the deny-list's LIMIT, so the allow-list cannot be removed as redundant.

    This is deliberately an assertion that `protected()` returns falsy. If a future change adds
    `demo`/`test` to `PROTECTED_SUBSTRINGS`, this test fails and forces the author to notice that
    such substrings would also match any future `grx-...-test-...` resource — i.e. the fix would
    break teardown rather than harden it.
    """
    assert not td.protected(name), (
        f"{name!r} now matches PROTECTED_SUBSTRINGS. Substrings this generic will also match "
        f"resources a future phase creates, which would make teardown refuse to delete its own "
        f"testbed. The structural `not_ours()` allow-list is the right gate for these.")
    assert td.not_ours(name), (
        f"{name!r} is a pre-existing DRAFT guardrail and the allow-list must refuse it — this "
        f"is the ONLY gate covering it.")


@pytest.mark.parametrize("name", OURS)
def test_our_own_resources_are_deletable_by_both_gates(name):
    """The control direction. A guard that protects everything is a wall, not a control."""
    assert not td.protected(name), (
        f"{name!r} is one of ours and matched PROTECTED_SUBSTRINGS; teardown would refuse to "
        f"delete it and exit non-zero on every run.")
    assert not td.not_ours(name), f"{name!r} is one of ours and the allow-list rejected it"


def test_vended_log_group_path_is_judged_on_its_gateway_id():
    """`not_ours` reads the last path segment, which for a vended group is the gateway id."""
    ours = "/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/grx-gw-abc123"
    theirs = "/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/harness-finance-xyz"
    assert not td.not_ours(ours)
    assert td.not_ours(theirs)


def test_no_guard_is_vacuous():
    """Both gates must DISCRIMINATE. The mutation every other test in this file shares.

    `protected()` returning truthy for everything passes every "is it protected" assertion above
    while making teardown unable to delete anything. `not_ours()` returning falsy for everything
    passes every control assertion while removing the only gate over the DRAFT guardrails. So
    each is required to answer both ways on real inputs.
    """
    prot_yes = [n for n in REAL_PREEXISTING + REAL_GATEWAYS if td.protected(n)]
    prot_no = [n for n in OURS if not td.protected(n)]
    assert prot_yes and prot_no, (
        f"protected() does not discriminate: {len(prot_yes)} protected / {len(prot_no)} "
        f"unprotected. A guard that answers the same way for every input is not a guard.")

    ours_ok = [n for n in OURS if not td.not_ours(n)]
    theirs_ok = [n for n in REAL_DRAFT_GUARDRAILS + REAL_PREEXISTING if td.not_ours(n)]
    assert ours_ok and theirs_ok, (
        f"not_ours() does not discriminate: {len(ours_ok)} ours / {len(theirs_ok)} theirs")


def test_protected_substrings_cannot_match_our_own_prefix():
    """The import-time assertion, re-checked as a test so the reason is discoverable here.

    A new entry that matched `grx-` would make teardown refuse its own testbed and exit non-zero
    forever — residue that looks like a safety feature.
    """
    for s in td.PROTECTED_SUBSTRINGS:
        norm = s.replace("_", "-").lower()
        assert norm not in td._OUR_PREFIX and not td._OUR_PREFIX.startswith(norm), s


def test_gone_codes_and_retry_codes_overlap_is_handled_not_accidental():
    """`ValidationException` and `ConflictException` are in BOTH sets, deliberately.

    Some deletes 400 on an absent id (gone) and some 409/400 while a reference is still being
    released (retry). `delete_resource` resolves the ambiguity by retrying first and only then
    treating it as gone — so the overlap must be intentional, and a change that removed a code
    from `RETRY_CODES` while leaving it in `GONE_CODES` would silently turn a transient conflict
    into "already absent", i.e. into a survivor reported as a success.
    """
    overlap = td.GONE_CODES & td.RETRY_CODES
    assert overlap == {"ValidationException", "ConflictException"}, (
        f"the GONE/RETRY overlap changed to {overlap}. A code that is 'gone' but not 'retry' is "
        f"never retried, so a transient conflict would be recorded as already-absent and the "
        f"resource would survive with a clean exit code.")


def test_deletion_priorities_put_logs_resources_before_the_gateway():
    """A delivery source holds the gateway ARN, so it must be deleted first.

    Pinned as numbers because the ordering is the whole correctness argument of channel 1 and it
    lives in four separate files. `07_traces.py`'s priorities are read from the module rather
    than restated, so a change there fails here.
    """
    tr = load_infra("07_traces")
    gateway_priority = 30          # 04_gateway.py's _GATEWAY_PRIORITY
    for attr in ("_DELIVERY_PRIORITY", "_SOURCE_PRIORITY", "_DEST_PRIORITY",
                 "_LOGGROUP_PRIORITY"):
        assert getattr(tr, attr) < gateway_priority, (
            f"07_traces.{attr}={getattr(tr, attr)} is not below the gateway's "
            f"{gateway_priority}; teardown would try to delete the gateway while a delivery "
            f"source still references its ARN.")
    # And the delivery before the destination it points at.
    assert tr._DELIVERY_PRIORITY < tr._DEST_PRIORITY
    # And the phase-1 guardrails after everything Phase 2 built, because a Cedar policy may
    # carry a `when guardrails {...}` clause referencing one.
    rows = td.phase1_guardrails()
    if rows:
        assert all(r.delete_priority > gateway_priority for r in rows)


def test_phase1_guardrails_are_read_from_the_registry_not_invented():
    """The second dry-run finding: 12 tagged guardrails with no recorded delete operation.

    Skipped rather than faked when the registry is absent, because the assertion worth making is
    about the real file's schema — a synthetic registry would only confirm my own idea of it.
    """
    reg = ROOT / "results" / "phase1_guardrails.json"
    if not reg.exists():
        pytest.skip("results/phase1_guardrails.json absent; Phase 1 has not run here")
    data = json.loads(reg.read_text())
    rows = td.phase1_guardrails()
    assert len(rows) == len(data.get("guardrails") or {}), (
        "every guardrail in the registry must become a deletable row, or the tag sweep reports "
        "it as an orphan with no recorded delete_op and teardown can never exit clean")
    for r in rows:
        assert r.delete_op == "delete_guardrail"
        assert r.delete_params.get("guardrailIdentifier")
        assert r.service == "bedrock"


def test_missing_registry_yields_no_rows_rather_than_raising(monkeypatch, tmp_path):
    """A checkout that never ran Phase 1 must still be able to tear down Phase 2."""
    monkeypatch.setattr(td, "PHASE1_GUARDRAIL_REGISTRY", tmp_path / "absent.json")
    assert td.phase1_guardrails() == []


def test_dry_run_refuses_without_a_flag(offline_env):
    """No default that destroys. Exit code 2 and a message, not a deletion."""
    p = subprocess.run([sys.executable, str(ROOT / "infra" / "99_teardown.py")],
                       capture_output=True, text=True, env=offline_env, timeout=120)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "refusing to run" in p.stderr


@pytest.mark.parametrize("stem", ["07_traces", "08_smoke"])
def test_scripts_that_mutate_or_spend_refuse_without_a_flag(stem, offline_env):
    """No default that creates a resource or sends a billable request.

    `06_verify.py` is deliberately NOT in this list — see the next test. The gate exists to stop
    an accidental invocation from mutating or spending, and a read-only verifier does neither, so
    requiring the flag there would only make the idempotent predicate harder to call.
    """
    p = subprocess.run([sys.executable, str(ROOT / "infra" / f"{stem}.py")],
                       capture_output=True, text=True, env=offline_env, timeout=120)
    assert p.returncode == 2, f"{stem}: rc={p.returncode}\n{p.stdout}{p.stderr}"
    assert "refusing to run" in p.stderr


def test_verify_has_no_flag_gate_but_still_refuses_to_invent_names(offline_env):
    """The read-only verifier's bare invocation is its live path, and that is intentional.

    `06_verify.py` costs $0 and mutates nothing; Phase 3+ runs it as a precondition and Phase 5
    re-runs it after every restore, so a mandatory `--run` would add a flag with no risk to
    guard. What it must still refuse is running against a ledger that does not exist: without
    `state.json` there are no resource names to check, and a verifier that invented them would
    report on resources nobody created. So the assertion here is rc=1 with an actionable message,
    NOT rc=0 — a verifier that passed with an empty ledger would be vacuous.
    """
    p = subprocess.run([sys.executable, str(ROOT / "infra" / "06_verify.py")],
                       capture_output=True, text=True, env=offline_env, timeout=120)
    if (ROOT / "state.json").exists():
        pytest.skip("state.json exists here, so the absent-ledger path is not reachable")
    assert p.returncode == 1, f"rc={p.returncode}\n{p.stdout}{p.stderr}"
    combined = p.stdout + p.stderr
    assert "state.json does not exist" in combined, combined[-2000:]
    assert "must not invent resource names" in combined, combined[-2000:]


@pytest.mark.parametrize("stem", ["06_verify", "07_traces"])
def test_dry_run_makes_no_aws_call(stem, offline_env):
    """The dry-run contract, held to the script's own words.

    Credentials are unset in this environment, so a script that tried to call AWS would fail on
    credential resolution rather than succeed silently — which is what makes rc=0 plus the banner
    a meaningful assertion rather than a tautology.
    """
    p = subprocess.run([sys.executable, str(ROOT / "infra" / f"{stem}.py"), "--dry-run"],
                       capture_output=True, text=True, env=offline_env, timeout=120)
    assert p.returncode == 0, f"{stem}: rc={p.returncode}\n{p.stdout}{p.stderr}"
    assert "no AWS call made" in p.stdout, p.stdout
