"""Arms for lib/awsclients.py.

Every client this project builds carries three guarantees that a plain
`boto3.client("bedrock-runtime")` does not, and each one exists because breaking it would
corrupt a published number rather than raise an error:

1. **The region is chosen, never inherited.** `~/.aws/config` has only `[default]` with no
   `region` key, so an omitted `region_name` resolves from `AWS_REGION`/`AWS_DEFAULT_REGION`
   — i.e. from whichever shell launched the script. F8-1's whole result is regional, and a
   result attributed to us-east-1 that was actually collected elsewhere is unfalsifiable in
   the worst direction. So `region` is a required positional and explicit `region_name` is
   passed to the session *and* every client, where it outranks the ambient variables.
2. **Retries are not transparent.** `total_max_attempts: 1` turns botocore's retry off. A
   retried call reports one duration spanning several attempts, and an AccessDenied oracle
   that fired on attempt 3 would be recorded as if it fired immediately. Retries live in
   `lib/checkpoint.py`, where the attempt count reaches the evidence.
3. **Rate ceilings are spacing, not a bucket.** A burst that drains a token bucket is
   precisely what produces the throttle that (1) and (2) then mis-record.

These arms run under the autouse `no_aws` fixture, which nulls credentials and blocks
`socket.socket.connect`. Client *construction* is offline in botocore — no call is made
until an operation is invoked — so the whole file is a $0 test of the layer that decides
what every live call will look like. `test_no_arm_in_this_file_can_reach_the_network`
proves that claim rather than asserting it.
"""

from __future__ import annotations

import os

import boto3
import pytest
from botocore.config import Config

import awsclients as A


# ---------------------------------------------------------------------------
# the region is chosen, not inherited
# ---------------------------------------------------------------------------

def test_region_is_positional_and_required():
    """A keyword with a default region is exactly the thing that must not exist."""
    with pytest.raises(TypeError):
        A.factory()                                    # type: ignore[call-arg]


def test_the_dataclass_itself_has_no_default_region():
    """`factory()` is not the only door.

    A mutation run added `region: str = "us-east-1"` to the dataclass and every arm still
    passed, because they all go through `factory()`, whose own signature still required the
    argument. A script that constructs `ClientFactory(...)` directly — or a later refactor
    that makes `factory` forward `**kwargs` — would then inherit a silent default. The
    guarantee belongs to the field, so it is asserted on the field.
    """
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(A.ClientFactory)}
    region = fields["region"]
    assert region.default is dataclasses.MISSING, (
        "a default region on the dataclass would let a direct construction inherit one")
    assert region.default_factory is dataclasses.MISSING
    with pytest.raises(TypeError):
        A.ClientFactory()                              # type: ignore[call-arg]


def test_the_region_cannot_be_reassigned_after_construction():
    """Write-once, because the cached session is pinned at first use.

    Reassigning `region` would leave the session in the old region while every client built
    afterwards pins to the new one — one factory serving two regions, which is the F8-1
    confound in its most deniable form (nothing errors; the records simply say whichever
    region the analysis assumed). This is also what makes the cache key's second element
    unreachable by any legitimate path, so the key is defence in depth rather than the
    guarantee itself.
    """
    f = A.factory("us-east-1")
    assert f.bedrock().meta.region_name == "us-east-1"
    with pytest.raises(AttributeError, match="write-once"):
        f.region = "eu-west-2"
    assert f.region == "us-east-1"
    assert f.bedrock().meta.region_name == "us-east-1"
    # Re-assigning the same value is not a change and stays allowed, so a dataclass
    # `replace()` or a re-`__post_init__` does not trip over its own value.
    f.region = "us-east-1"


def test_the_two_region_name_passes_are_both_present_and_both_redundant():
    """A structural arm, and an honest statement of what it can and cannot show.

    `region_name` is passed to the `Session` *and* to each `client()` call, and `Config`
    carries it a third time. Dropping the `client()` one changes no observable behaviour
    today — `Config(region_name=...)` already pins the client — so a behavioural arm cannot
    distinguish two of the three, and a mutation run proved that by deleting one and
    finding all 51 arms still green. That redundancy is deliberate (botocore's resolution
    order is a botocore implementation detail, and this project's whole regional result
    rests on it), so it is asserted where it is actually visible: in the call, by source.
    """
    import inspect
    src = inspect.getsource(A.ClientFactory.client)
    assert src.count("region_name=self.region") == 1, (
        "the explicit region_name on client() is redundant with Config today and so is "
        "invisible to a behavioural arm; it is kept because botocore's precedence order "
        "is not ours to depend on twice-over, and removed only deliberately")
    assert "region_name=self.region" in inspect.getsource(A.ClientFactory.session)
    assert "region_name=self.region" in inspect.getsource(A.ClientFactory._config)


def test_an_empty_region_raises_with_the_reason():
    with pytest.raises(ValueError, match="region is required"):
        A.factory("")


@pytest.mark.parametrize("var", ["AWS_REGION", "AWS_DEFAULT_REGION"])
def test_an_ambient_region_cannot_become_the_clients_region(monkeypatch, var):
    """The load-bearing guarantee. Explicit region_name outranks both variables."""
    monkeypatch.setenv(var, "ap-northeast-3")
    f = A.factory("us-east-1")
    assert f.region == "us-east-1"
    assert f._config("bedrock-runtime").region_name == "us-east-1"
    client = f.bedrock_runtime()
    assert client.meta.region_name == "us-east-1"


def test_the_region_reaches_both_the_session_and_the_client(monkeypatch):
    """Both are set deliberately: a session-only region would be overridden by a
    client-level default, and a client-only region leaves STS resolving elsewhere."""
    seen: list[dict] = []
    real = boto3.session.Session

    class Recording(real):                             # type: ignore[misc,valid-type]
        def __init__(self, *a, **kw):
            seen.append(kw)
            super().__init__(*a, **kw)

    monkeypatch.setattr(boto3.session, "Session", Recording)
    f = A.factory("eu-west-2")
    f.bedrock()
    assert seen and seen[0]["region_name"] == "eu-west-2"
    assert f._config("bedrock").region_name == "eu-west-2"


def test_ambient_hints_are_recorded_rather_than_deleted(monkeypatch):
    """Deleting them would leave nothing to check.

    An empty dict here plus an explicit region in the record would look identical whether
    or not the precedence guarantee held; recording the overridden value is what makes it
    checkable after the fact.
    """
    monkeypatch.setenv("AWS_REGION", "sa-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    hints = A.environment_region_hints()
    assert hints == {"AWS_REGION": "sa-east-1", "AWS_DEFAULT_REGION": "ap-south-1"}
    # And they are still in the environment: recorded, not removed.
    assert os.environ["AWS_REGION"] == "sa-east-1"
    assert A.factory("us-east-1").region == "us-east-1"


def test_only_region_variables_are_recorded(monkeypatch):
    """A credential leaking into an evidence file would be a redaction incident."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "not-a-real-secret")
    assert set(A.environment_region_hints()) == {"AWS_REGION"}


def test_the_nine_f8_1_regions_partition_into_supported_and_unsupported():
    assert len(A.F8_1_REGIONS) == 9
    assert len(set(A.F8_1_REGIONS)) == 9, "a duplicated region would double-count a result"
    assert set(A.GUARDRAILS_IN_POLICY_SUPPORTED) & \
        set(A.GUARDRAILS_IN_POLICY_UNSUPPORTED) == set()
    assert len(A.GUARDRAILS_IN_POLICY_SUPPORTED) == 5
    assert len(A.GUARDRAILS_IN_POLICY_UNSUPPORTED) == 4
    assert A.MAIN_REGION in A.GUARDRAILS_IN_POLICY_SUPPORTED


def test_the_region_order_is_fixed_so_evidence_sorts_reproducibly():
    assert A.F8_1_REGIONS == tuple(A.GUARDRAILS_IN_POLICY_SUPPORTED) + \
        tuple(A.GUARDRAILS_IN_POLICY_UNSUPPORTED)


def test_the_cache_key_carries_the_region_even_though_nothing_can_change_it():
    """The second structural arm, for the same reason as the `region_name` one.

    With `region` write-once, one factory can only ever serve one region, so keying the
    cache on service alone is behaviourally equivalent and a mutation run confirmed it —
    the mutant survived all 54 behavioural arms. Two defences are kept because they fail
    independently: if `__setattr__`'s guard is ever loosened (a `dataclasses.replace`, a
    subclass, a refactor to a plain class), the key is what still keeps eu-west-2's client
    out of the us-east-1 arm. Asserting it by source is honest about the fact that no
    reachable input distinguishes it.
    """
    import inspect
    src = inspect.getsource(A.ClientFactory.client)
    assert "key = (service, self.region)" in src, (
        "keying on service alone is equivalent only while region is write-once; the key is "
        "the second, independent defence and is removed only deliberately")
    f = A.factory("us-east-1")
    f.bedrock()
    assert list(f._cache) == [("bedrock", "us-east-1")]


def test_two_regions_do_not_share_a_client_cache():
    """A cached client keyed on service alone would silently serve one region's client to
    the other arm — and F8-1 compares nine."""
    a = A.factory("us-east-1")
    b = A.factory("eu-west-2")
    assert a.bedrock().meta.region_name == "us-east-1"
    assert b.bedrock().meta.region_name == "eu-west-2"
    assert a.bedrock() is a.bedrock(), "the cache should still be a cache"
    assert a.bedrock() is not b.bedrock()


# ---------------------------------------------------------------------------
# retries are the caller's business
# ---------------------------------------------------------------------------

def test_transparent_retries_are_disabled():
    """One recorded call must be one attempt, or every latency figure is a sum."""
    cfg = A.factory("us-east-1")._config("bedrock-runtime")
    assert cfg.retries["total_max_attempts"] == 1
    assert cfg.retries["mode"] == "standard"


def test_the_built_client_really_carries_the_single_attempt_config():
    """Asserting the Config object alone would pass even if it were never handed to boto3."""
    client = A.factory("us-east-1").bedrock_runtime()
    assert client.meta.config.retries["total_max_attempts"] == 1


def test_a_default_boto_client_would_have_retried(monkeypatch):
    """Mutation control: the assertion above is only meaningful if the default differs."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    default = boto3.session.Session(region_name="us-east-1").client(
        "bedrock-runtime", config=Config(region_name="us-east-1"))
    assert default.meta.config.retries in (None, {}) or \
        default.meta.config.retries.get("total_max_attempts") != 1


def test_the_read_timeout_exceeds_the_slowest_documented_evaluation():
    """A 60s timeout would turn F6-6's documented ~31s upper band into a client error."""
    cfg = A.factory("us-east-1")._config("bedrock-runtime")
    assert cfg.read_timeout > 31
    assert cfg.connect_timeout <= 10


def test_the_user_agent_identifies_this_harness():
    """So a CloudTrail reader can tell our calls from the account's other ~$27k/mo."""
    cfg = A.factory("us-east-1")._config("bedrock")
    assert A.PROJECT_TAG in cfg.user_agent_extra


# ---------------------------------------------------------------------------
# tags: teardown finds resources by tag, not by name
# ---------------------------------------------------------------------------

def test_the_tag_set_is_exactly_what_teardown_asserts():
    tags = A.tags_for("run-123", "2026-08-11T00:00:00Z")
    assert tags == {"Project": A.PROJECT_TAG, "RunId": "run-123",
                    "Owner": A.OWNER_TAG, "ExpiresAt": "2026-08-11T00:00:00Z"}


@pytest.mark.parametrize("run_id,expires,match", [
    ("", "2026-08-11T00:00:00Z", "run_id is required"),
    ("run-123", "", "expires_at is required"),
])
def test_an_untagged_resource_is_refused_at_construction(run_id, expires, match):
    """An untagged resource is invisible to the sweep, which is the only thing finding
    orphans; a missing ExpiresAt makes an orphan indistinguishable from a live resource."""
    with pytest.raises(ValueError, match=match):
        A.tags_for(run_id, expires)


def test_the_project_tag_is_the_cost_attribution_key():
    """Service-level filtering would misattribute the account's unrelated spend to us."""
    assert A.PROJECT_TAG == "guardrails-doc-validation"


# ---------------------------------------------------------------------------
# rate limiting is spacing, not a bucket
# ---------------------------------------------------------------------------

def test_the_documented_ceilings_are_the_ones_recorded():
    assert A.rate_limit_for("CreatePolicyEngine") == 1.0
    assert A.rate_limit_for("DeletePolicyEngine") == 1.0
    assert A.rate_limit_for("CreatePolicy") == 5.0
    assert A.rate_limit_for("UpdateGateway") == 5.0
    assert A.rate_limit_for("ApplyGuardrail") == 100.0
    assert A.rate_limit_for("InvokeGuardrailChecks") == 25.0, "1500 rpm = 25 rps"


def test_an_unlimited_operation_returns_none_not_zero():
    """None means "this harness enforces no ceiling", which is not "the API has none". A
    0.0 would read as unlimited and divide by zero on the way there."""
    assert A.rate_limit_for("GetCallerIdentity") is None


def test_the_gateway_data_plane_is_paced_and_is_labelled_as_ours():
    """F4 sends up to 1,440 `tools/call` requests, and `wait()` no-ops on an unknown key.

    Both halves are asserted because either alone is a defect. Without the entry,
    `lim.wait("InvokeGateway")` returns 0.0 and the call reads as rate-limited while doing
    nothing — the vacuous-guard shape. With the entry but WITHOUT the self-imposed marking,
    an evidence record would cite 10/s as a service quota; Service Quotas
    (`ServiceCode=bedrock-agentcore`, us-east-1, 2026-08-11) publishes only CONCURRENCY for
    this path (1000 tool-call/tool-list connections, 1000 per gateway) and no per-second
    rate at all. The nearest published rate, "search-based tool-call requests = 25/s", is a
    different operation this project never sends.
    """
    assert A.rate_limit_for("InvokeGateway") == 10.0
    assert A.limit_provenance("InvokeGateway") == "self_imposed"
    assert "InvokeGateway" in A.SELF_IMPOSED_LIMITS


@pytest.mark.parametrize("op", sorted(A.SELF_IMPOSED_LIMITS))
def test_every_self_imposed_limit_is_actually_in_the_table(op):
    """A name in the marker set but not in `RATE_LIMITS` would report provenance 'none'.

    Parametrized over the set itself so adding a marker without adding the ceiling — the
    direction that leaves `wait()` a no-op while the name *looks* handled — fails here.
    """
    assert A.rate_limit_for(op) is not None
    assert A.limit_provenance(op) == "self_imposed"


def test_the_first_call_to_an_operation_does_not_wait():
    lim = A.RateLimiter()
    assert lim.wait("CreatePolicyEngine", now=1000.0, sleep=lambda _s: None) == 0.0


def test_a_second_call_waits_the_full_interval():
    lim = A.RateLimiter()
    slept: list[float] = []
    lim.wait("CreatePolicyEngine", now=1000.0, sleep=slept.append)
    delay = lim.wait("CreatePolicyEngine", now=1000.0, sleep=slept.append)
    assert delay == pytest.approx(1.0), "1/s means a 1-second floor between calls"
    assert slept == [1.0]


def test_a_call_after_the_interval_has_elapsed_does_not_wait():
    lim = A.RateLimiter()
    lim.wait("CreatePolicy", now=1000.0, sleep=lambda _s: None)
    assert lim.wait("CreatePolicy", now=1000.5, sleep=lambda _s: None) == 0.0, "5/s = 0.2s"


def test_operations_are_spaced_independently():
    """A shared clock would make the 1/s engine limit throttle the 100/s ApplyGuardrail
    path, adding a second to every trial of an n=1000 latency arm."""
    lim = A.RateLimiter()
    lim.wait("CreatePolicyEngine", now=1000.0, sleep=lambda _s: None)
    assert lim.wait("ApplyGuardrail", now=1000.0, sleep=lambda _s: None) == 0.0


def test_the_schedule_converges_on_the_rate_instead_of_drifting():
    """The limiter records the intended next slot, not the observed time.

    Recording `t` would add each call's own duration to the interval, so a series would
    drift slower and slower — and a rate limiter that is quietly 2x slower than the
    documented ceiling turns an n=1000 arm from 20 minutes into 40.
    """
    lim = A.RateLimiter()
    lim.wait("CreatePolicyEngine", now=1000.0, sleep=lambda _s: None)
    # Three back-to-back calls at the same instant: each waits one more interval than the
    # last, i.e. the slots are 1001, 1002, 1003 — not 1001, 1001, 1001.
    d1 = lim.wait("CreatePolicyEngine", now=1000.0, sleep=lambda _s: None)
    d2 = lim.wait("CreatePolicyEngine", now=1000.0, sleep=lambda _s: None)
    d3 = lim.wait("CreatePolicyEngine", now=1000.0, sleep=lambda _s: None)
    assert (d1, d2, d3) == pytest.approx((1.0, 2.0, 3.0))


def test_cumulative_waits_are_recorded_for_the_evidence():
    """A latency figure must be separable from the time we spent respecting a rate limit."""
    lim = A.RateLimiter()
    lim.wait("CreatePolicy", now=1000.0, sleep=lambda _s: None)
    lim.wait("CreatePolicy", now=1000.0, sleep=lambda _s: None)
    lim.wait("CreatePolicy", now=1000.0, sleep=lambda _s: None)
    assert lim.waits["CreatePolicy"] == pytest.approx(0.2 + 0.4)


def test_an_unlimited_operation_records_no_wait():
    lim = A.RateLimiter()
    lim.wait("GetCallerIdentity", now=1000.0, sleep=lambda _s: None)
    lim.wait("GetCallerIdentity", now=1000.0, sleep=lambda _s: None)
    assert "GetCallerIdentity" not in lim.waits


def test_the_process_wide_limiter_is_shared():
    """Two scripts' clients in one process must not each get their own budget."""
    assert A.limiter() is A.limiter()


# ---------------------------------------------------------------------------
# SDK surface: an absent parameter is not rejected, it is simply missing
# ---------------------------------------------------------------------------

def test_sdk_versions_are_recorded_not_noted_once_in_a_readme():
    """A result collected under 1.42.79 is a statement about that SDK, not about AWS."""
    v = A.sdk_versions()
    assert set(v) == {"boto3", "botocore"}
    assert all(x and x[0].isdigit() for x in v.values())


def test_has_operation_reads_the_loaded_service_model():
    client = A.factory("us-east-1").bedrock_runtime()
    assert A.has_operation(client, "ApplyGuardrail") is True
    assert A.has_operation(client, "OperationThatDoesNotExist") is False


def test_has_operation_is_case_sensitive_pascal_case():
    """botocore's model keys are PascalCase; a lowercase probe returning True would make
    the F1-1 pre-flight assertion vacuous."""
    client = A.factory("us-east-1").bedrock_runtime()
    assert A.has_operation(client, "applyGuardrail") is False


def test_has_shape_member_walks_a_dotted_path():
    """The F1-1 check: `CreatePolicy.definition.cedar` exists, `definition.policy` may not.

    Which of those is true at the installed botocore *is* the F1-1 result, so this arm
    asserts only the mechanism — that a real path resolves and a fabricated one does not —
    and never the answer.
    """
    client = A.factory("us-east-1").agentcore_control()
    assert A.has_shape_member(client, "CreatePolicy", "definition") is True
    assert A.has_shape_member(client, "CreatePolicy", "definition.cedar") is True
    assert A.has_shape_member(client, "CreatePolicy", "definition.notAMember") is False
    assert A.has_shape_member(client, "CreatePolicy", "notAMember.cedar") is False


def test_has_shape_member_on_an_absent_operation_is_false_not_an_error():
    client = A.factory("us-east-1").bedrock_runtime()
    assert A.has_shape_member(client, "NoSuchOperation", "anything") is False


# IAM and Organizations are global services: botocore resolves them to the partition
# pseudo-region `aws-global` regardless of the region_name passed. That is correct — there
# is no regional IAM endpoint to pin — and it is recorded here rather than accommodated by
# loosening the assertion for all twelve, because a *regional* service silently resolving
# to aws-global would be the F8-1 confound this module exists to prevent.
_GLOBAL_ACCESSORS = {"iam", "organizations"}
_REGIONAL_ACCESSORS = ("bedrock_runtime", "bedrock", "agentcore_control", "agentcore",
                       "ec2", "sts", "logs", "cloudwatch", "lambda_", "pricing")


@pytest.mark.parametrize("name", _REGIONAL_ACCESSORS)
def test_every_regional_accessor_builds_a_client_in_the_pinned_region(name):
    """A typo in an accessor must be an AttributeError at import, not an
    UnknownServiceError surfacing after the expensive part of an overnight arm."""
    client = getattr(A.factory("us-east-1"), name)()
    assert client.meta.region_name == "us-east-1"
    assert "us-east-1" in client.meta.endpoint_url


@pytest.mark.parametrize("name", sorted(_GLOBAL_ACCESSORS))
def test_a_global_service_resolves_to_the_partition_endpoint(name):
    """Documented, not worked around: there is no regional IAM endpoint to pin.

    botocore rewrites `config.region_name` to `aws-global` as well, so the *built client*
    retains no trace of the region it was asked for. That is worth pinning rather than
    glossing: an F5-3b permissions-boundary result cannot be attributed to a region from the
    client at all, and the region in its evidence record has to come from
    `ClientFactory.region` — which this arm confirms is still what we asked for.
    """
    f = A.factory("us-east-1")
    client = getattr(f, name)()
    assert client.meta.region_name == "aws-global"
    assert client.meta.config.region_name == "aws-global", (
        "botocore rewrites the config too; the region in an evidence record for a global "
        "service must come from the factory, not from the client")
    assert f.region == "us-east-1"
    assert f._config(name).region_name == "us-east-1"


def test_a_regional_service_does_not_silently_resolve_to_aws_global(monkeypatch):
    """Mutation control for the split above: the exemption must be exactly two services."""
    f = A.factory("eu-west-2")
    for name in _REGIONAL_ACCESSORS:
        assert getattr(f, name)().meta.region_name == "eu-west-2", name


def test_the_accessor_list_covers_every_named_accessor_on_the_factory():
    """A new accessor added without a test would otherwise pass by not being looked at."""
    named = {n for n in dir(A.ClientFactory)
             if not n.startswith("_") and n not in
             ("client", "session", "region", "role_arn", "session_name")}
    assert named == set(_REGIONAL_ACCESSORS) | _GLOBAL_ACCESSORS


# ---------------------------------------------------------------------------
# the offline claim, proven rather than asserted
# ---------------------------------------------------------------------------

def test_no_arm_in_this_file_can_reach_the_network():
    """The conftest fixture is only a guarantee if it actually blocks.

    Client construction is offline in botocore, which is what makes this whole file free;
    an *operation* would need the network, and must fail.
    """
    import socket
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.socket().connect(("bedrock-runtime.us-east-1.amazonaws.com", 443))


def test_credentials_are_nulled_so_a_stray_call_cannot_succeed_quietly():
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_PROFILE"):
        assert var not in os.environ


def test_assuming_a_role_is_deferred_until_a_client_is_needed():
    """Constructing a factory must not call STS: `--dry-run` on every family script builds
    one, and a dry run that authenticates is not a dry run.

    The ARN is assembled at runtime rather than written as a literal. The redaction gate's
    patterns are shape-based (`\\b\\d{12}\\b` for an account ID), so an all-zeros placeholder
    trips them exactly as a real one would — correctly, since a gate that can tell a
    placeholder from an account ID by looking at it cannot exist. `check_redaction.py`'s own
    comment records this as the precedent: an earlier suite was *fixed* this way rather than
    waived, because a waiver for a fixture blinds the pattern for the next real leak.
    """
    arn = ":".join(["arn", "aws", "iam", "", "0" * 12, "role/grx-caller"])
    f = A.factory("us-east-1", role_arn=arn)
    assert f.role_arn.endswith("grx-caller")
    assert f._session is None, "constructing a factory must not have called sts:AssumeRole"
