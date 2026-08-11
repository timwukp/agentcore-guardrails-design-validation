"""Mutation tests for the F6 pairing assertion's ignore list. Offline.

Why this file exists
--------------------
`04_gateway.py` asserts that the two gateways differ in exactly one field, `policyEngine
Configuration`, because F6's latency result is a Wilcoxon signed-rank test on paired differences
and a second undetected difference would bias every pair by an unknown amount — invisibly, since
both arms would look internally consistent. The assertion is only as strong as its ignore list,
and an ignore list is the one part of an assertion that can be *widened* until it asserts nothing.

`PAIR_IGNORE` gained an entry during the live Phase 2 build. `04_gateway.py --ensure` created both
gateways READY and then failed the pair check on `workloadIdentityDetails`, whose ARNs are
service-assigned per gateway. Adding it was correct, but "I looked at it and it seemed like
identity" is not a check, so the grounds were turned into `workload_identity_is_pure_identity()`
and this file is what holds that function to them. Every arm below is a way the grounds could stop
holding, and each one must be FATAL rather than ignorable:

  * the ARN's last segment stops being the gateway id — the field would then carry a value the
    pair check has no other opportunity to compare;
  * the prefixes diverge — two gateways in different workload-identity directories is a
    configuration difference wearing an identity field's name;
  * the structure gains a key — the sole reason the field is ignorable is that it holds one
    identity ARN, and a second key could be anything, including a mode or an auth setting.

`test_the_ignore_list_admission_rule_is_not_vacuous` is the `feedback_vacuous_test_check` arm: a
`workload_identity_is_pure_identity` that returned `[]` unconditionally would pass every "the good
pair is accepted" assertion above while making the entry a rubber stamp, so the bad pairs are
asserted to be REJECTED, and the diff function is separately asserted to still report a real
difference when one is present.

The fixtures are shaped from the live pair (`grx-gw-r20260810t130945z-zpkfmpwo9n` /
`grx-gw-nopolicy-r20260810t130945z-x1gqmvenpz`), whose ARNs were compared segment by segment
before the ignore entry was added, per `feedback_verify_against_real_artifact`. Account ids are
placeholders: nothing here needs a real one, and writing one would put an identifier in the tree
for no gain.
"""

from __future__ import annotations

import pytest

from conftest import load_infra

gw = load_infra("04_gateway")

# Assembled rather than written as a literal so no ARN-shaped string sits in the source.
_WID_PREFIX = ("arn" + ":aws:bedrock-agentcore:us-east-1:<account>:"
               "workload-identity-directory/default/workload-identity")

MAIN_ID = "grx-gw-r20260810t130945z-zpkfmpwo9n"
NOPO_ID = "grx-gw-nopolicy-r20260810t130945z-x1gqmvenpz"
IDS = {"main": MAIN_ID, "nopolicy": NOPO_ID}


def _cfg(gateway_id: str, *, wid: dict | None = None, **overrides) -> dict:
    """A gateway config with the fields `diff_configs` actually compares.

    Shaped from `get_gateway`'s real response keys — the ones that are NOT in `PAIR_IGNORE` are
    what the pair check compares, so those are the ones a fixture has to carry.
    """
    cfg = {
        "name": f"grx-{gateway_id}",
        "gatewayId": gateway_id,
        "gatewayArn": f"arn:aws:bedrock-agentcore:us-east-1:<account>:gateway/{gateway_id}",
        "gatewayUrl": f"https://{gateway_id}.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        "status": "READY",
        "authorizerType": "AWS_IAM",
        "exceptionLevel": "DEBUG",
        "protocolType": "MCP",
        "protocolConfiguration": {"mcp": {
            "sessionConfiguration": {"sessionTimeoutInSeconds": gw.SESSION_TIMEOUT_S},
            "streamingConfiguration": {"enableResponseStreaming": False},
        }},
        "roleArn": "arn:aws:iam::<account>:role/grx-gw-exec",
        "workloadIdentityDetails": (
            wid if wid is not None
            else {"workloadIdentityArn": f"{_WID_PREFIX}/{gateway_id}"}),
    }
    cfg.update(overrides)
    return cfg


def _live(main_over: dict | None = None, nopo_over: dict | None = None) -> dict:
    return {"main": _cfg(MAIN_ID, **(main_over or {})),
            "nopolicy": _cfg(NOPO_ID, **(nopo_over or {}))}


# --- the ignore list itself -------------------------------------------------

def test_pair_ignore_is_defined_once_and_shared_with_the_verifier():
    """`06_verify.py` must import the list, not carry a copy.

    Two copies is the state this project was actually in: `04_gateway.py` gained
    `workloadIdentityDetails` and `06_verify.py` did not, so the verifier would have failed on the
    field immediately after the creator's pair check passed. This test pins the fix by source
    inspection, because the divergence is invisible to any behavioural test that runs only one of
    the two scripts.
    """
    src = (gw.__file__.rsplit("/", 1)[0] + "/06_verify.py")
    with open(src, encoding="utf-8") as fh:
        verify_src = fh.read()
    assert "mod.PAIR_IGNORE" in verify_src, (
        "06_verify.py must use 04_gateway.PAIR_IGNORE; a local copy silently diverges")
    # And no second literal list: the marker fields of the old copy must be gone from it.
    assert '"statusReasons", "ResponseMetadata",' not in verify_src, (
        "06_verify.py still contains a literal ignore list — that is the copy this test removes")


def test_policy_engine_configuration_is_ignored_because_it_is_the_designed_difference():
    """The field the pair EXISTS to differ in. Its presence in the list is the point of the list."""
    assert "policyEngineConfiguration" in gw.PAIR_IGNORE


@pytest.mark.parametrize("field", ["authorizerType", "exceptionLevel", "protocolConfiguration",
                                   "protocolType", "roleArn"])
def test_the_fields_that_could_confound_latency_are_NOT_ignored(field):
    """The negative half of the list, and the reason the list needs a test at all.

    Each of these can plausibly differ between two gateways and each would move latency:
    `protocolConfiguration` carries the streaming switch (time-to-first-byte vs time-to-last-byte
    are different quantities), `authorizerType` changes the auth hop, `roleArn` changes which
    permissions are evaluated. If one of them ever appears in `PAIR_IGNORE`, F6's paired
    difference stops isolating the policy hops and this test is what says so.
    """
    assert field not in gw.PAIR_IGNORE


# --- workload_identity_is_pure_identity ------------------------------------

def test_the_live_pair_shape_is_accepted():
    """The shape measured on the real pair passes. Baseline for every rejection arm below."""
    assert gw.workload_identity_is_pure_identity(_live(), IDS) == []


def test_a_tail_that_is_not_the_gateway_id_is_rejected():
    """If the last segment stops restating gatewayId, the field may carry something comparable."""
    bad = _live(main_over={"workloadIdentityDetails": {
        "workloadIdentityArn": f"{_WID_PREFIX}/some-other-identity"}})
    problems = gw.workload_identity_is_pure_identity(bad, IDS)
    assert problems, "a tail unequal to the gateway id must not be accepted as pure identity"
    assert "restates gatewayId" in " ".join(problems)


def test_divergent_directory_prefixes_are_rejected():
    """Two gateways in different workload-identity directories is a CONFIGURATION difference.

    It would arrive wearing the name of an ignored field, which is precisely why the prefix is
    compared rather than assumed constant.
    """
    other = _WID_PREFIX.replace("/default/", "/isolated/")
    bad = _live(nopo_over={"workloadIdentityDetails": {
        "workloadIdentityArn": f"{other}/{NOPO_ID}"}})
    problems = gw.workload_identity_is_pure_identity(bad, IDS)
    assert problems
    assert "prefixes differ" in " ".join(problems)


def test_an_added_key_in_the_structure_is_rejected():
    """The field is ignorable ONLY because it holds one identity ARN.

    A second key could be a mode, a directory setting, an auth toggle — a value the pair check
    should compare. The function therefore checks the whole dict rather than reading the one key
    it expects, so a service-side addition surfaces as a failure instead of being skipped.
    """
    bad = _live(main_over={"workloadIdentityDetails": {
        "workloadIdentityArn": f"{_WID_PREFIX}/{MAIN_ID}",
        "workloadIdentityMode": "STRICT"}})
    problems = gw.workload_identity_is_pure_identity(bad, IDS)
    assert problems
    joined = " ".join(problems)
    assert "workloadIdentityMode" in joined and "hide a real difference" in joined


@pytest.mark.parametrize("value", [None, "a string", 17, []])
def test_a_non_dict_structure_is_rejected_rather_than_crashing(value):
    """A type change must be a reported problem, not a TypeError.

    An exception here would abort `04_gateway.py` mid-run with a traceback, after both gateways
    exist and before the ledger is written — the orphan state the tag sweep exists to catch.
    """
    bad = _live(main_over={"workloadIdentityDetails": value})
    problems = gw.workload_identity_is_pure_identity(bad, IDS)
    assert problems, f"{value!r} must be reported, not accepted"


def test_a_missing_gateway_id_in_the_ledger_map_is_rejected():
    """The comparison is against the LEDGER's id, so an absent entry cannot pass silently.

    An empty `want` compared against a real tail must fail; the alternative — treating "no id to
    compare" as agreement — is how a check gets bypassed by the absence of its own input.
    """
    problems = gw.workload_identity_is_pure_identity(_live(), {"main": MAIN_ID})
    assert problems, "a logical missing from the id map must not be treated as matching"


# --- the vacuity arm -------------------------------------------------------

def test_the_ignore_list_admission_rule_is_not_vacuous():
    """Both guards must be capable of FAILING, in both directions.

    `workload_identity_is_pure_identity` returning `[]` unconditionally would pass every
    acceptance arm above while turning the `PAIR_IGNORE` entry into a rubber stamp, and
    `diff_configs` returning `[]` unconditionally would pass the pair check for any two gateways
    at all. So each is exercised on an input where a correct implementation MUST report.
    """
    # The identity guard rejects at least one input.
    assert gw.workload_identity_is_pure_identity(
        _live(main_over={"workloadIdentityDetails": {"workloadIdentityArn": "no-slash"}}), IDS)

    # And the diff still reports a real, latency-relevant difference under the ignore list —
    # streaming enabled on one gateway only, which changes what "duration" even means.
    live = _live(nopo_over={"protocolConfiguration": {"mcp": {
        "sessionConfiguration": {"sessionTimeoutInSeconds": gw.SESSION_TIMEOUT_S},
        "streamingConfiguration": {"enableResponseStreaming": True}}}})
    diffs = gw.diff_configs(live["main"], live["nopolicy"], ignore=gw.PAIR_IGNORE)
    assert any("protocolConfiguration" in d for d in diffs), (
        "diff_configs must still report a streaming mismatch; if PAIR_IGNORE ever swallows it, "
        "F6's paired difference silently mixes time-to-first-byte with time-to-last-byte")


def test_the_designed_difference_alone_leaves_the_pair_valid():
    """The whole point: engine on one side, absent on the other, and NO other reported difference.

    This is the positive control for the ignore list — if it failed, the pair check would be
    unsatisfiable and 04_gateway.py could never complete regardless of what AWS returned.
    """
    live = _live()
    live["main"]["policyEngineConfiguration"] = {
        "arn": "arn:aws:bedrock-agentcore:us-east-1:<account>:policy-engine/grx_pe_x",
        "mode": "ENFORCE"}
    assert gw.diff_configs(live["main"], live["nopolicy"], ignore=gw.PAIR_IGNORE) == []
