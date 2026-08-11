"""boto3 client construction for this project, with the region made unforgeable.

Why a module instead of `boto3.client("bedrock-runtime")`
--------------------------------------------------------
Three facts about this environment, established read-only and not re-derivable from the
code:

1. `~/.aws/config` contains only `[default]`. There is **no** `region` key, so a client
   built without `region_name` resolves its region from `AWS_REGION`/`AWS_DEFAULT_REGION`
   or fails — and which of those happens depends on the shell that launched the script.
2. The main suite is pinned to **us-east-1**, because holding region constant is what makes
   latency and determinism interpretable. F8-1 deliberately varies region across nine.
3. AgentCore control-plane `List*` calls return 200 in regions where guardrails-in-policy
   is **not** available, so the regional restriction can only appear on mutations.

Put together: a client that quietly inherits a region from the environment would make the
regional claim unfalsifiable in the worst way — F8-1 would report a result for whatever
region the ambient variable named, and the record would say `us-east-1` because that is
what the analysis assumed. So `region` is a **required positional argument** here. Not a
keyword with a default; a positional, because a default region is exactly the thing that
must not exist.

The guarantee is *precedence*, not sanitization: `region_name` is passed to the `Session`
**and** to every `client()` call, and an explicit `region_name` outranks `AWS_REGION` and
`AWS_DEFAULT_REGION` in botocore's resolution order. So an ambient value cannot win, and
an omitted one raises in `__post_init__` rather than resolving to a surprise. Ambient
values are not deleted — they are *recorded* by `environment_region_hints()`, because a
record showing which hints existed and were overridden proves the precedence held, where
deleting them would leave nothing to check.

What this module deliberately does NOT do
-----------------------------------------
It does not retry, back off, or normalize responses. Retries belong to `lib/checkpoint.py`
(which knows what a trial is and can record an attempt count in the evidence), and
normalization belongs to `lib/evidence.py` (which records the raw response first). A
client that transparently retried would make `retry_attempts` in the evidence record a
lie, and that field is what tells a reader whether a latency figure includes a retry tail.

Rate limits are enforced, because they are a property of the API and not of any one script:
`CreatePolicyEngine`/`DeletePolicyEngine` are **1/s**, `CreatePolicy`/`DeletePolicy` and
`CreateGateway`/`UpdateGateway` are **5/s**, `ApplyGuardrail` is 100 rps. A throttle in the
middle of an n=300 determinism arm is not just slow: `ThrottlingException` retried by
botocore's default `standard` mode would add an invisible multi-second delay to that
trial's wall clock, which is a latency observation we would then publish.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

import boto3
import botocore
from botocore.config import Config

# The project's pinned region for every experiment except F8-1. Named so a reader of a
# call site can see which choice is being made, rather than reading a bare string.
MAIN_REGION = "us-east-1"

# The nine regions F8-1 probes. Five are on AWS's verified guardrails-in-policy list; four
# are not, and the pre-registered oracle expects mutations to fail there with a
# distinguishable error. Order is fixed so the evidence records sort reproducibly.
GUARDRAILS_IN_POLICY_SUPPORTED = (
    "us-east-1", "eu-west-2", "eu-north-1", "ap-southeast-2", "ap-northeast-1",
)
GUARDRAILS_IN_POLICY_UNSUPPORTED = (
    "us-west-2", "eu-central-1", "sa-east-1", "ap-south-1",
)
F8_1_REGIONS = GUARDRAILS_IN_POLICY_SUPPORTED + GUARDRAILS_IN_POLICY_UNSUPPORTED

# Documented rate ceilings, in calls per second, keyed by botocore operation name. A
# missing entry means "not rate-limited by us"; that is a deliberate distinction from
# "unlimited", and `rate_limit_for` says which it is.
RATE_LIMITS: dict[str, float] = {
    # policy engine lifecycle: 1/s
    "CreatePolicyEngine": 1.0,
    "DeletePolicyEngine": 1.0,
    "UpdatePolicyEngine": 1.0,
    # policy + gateway lifecycle: 5/s
    "CreatePolicy": 5.0,
    "DeletePolicy": 5.0,
    "UpdatePolicy": 5.0,
    "CreateGateway": 5.0,
    "UpdateGateway": 5.0,
    "DeleteGateway": 5.0,
    "CreateGatewayTarget": 5.0,
    "UpdateGatewayTarget": 5.0,
    "DeleteGatewayTarget": 5.0,
    # guardrail evaluation: 100 rps
    "ApplyGuardrail": 100.0,
    # InvokeGuardrailChecks advertises 1500 rpm = 25 rps
    "InvokeGuardrailChecks": 25.0,
    # Guardrail control plane: SELF-IMPOSED, not documented. Service Quotas advertises no
    # per-second rate for CreateGuardrail/GetGuardrail/ListGuardrails/DeleteGuardrail —
    # only "Guardrails per account: 100" and "Versions per guardrail: 20" (queried
    # 2026-08-10, `list_service_quotas ServiceCode=bedrock`). They are listed anyway
    # because omitting them made `lim.wait("CreateGuardrail")` in the provisioning script
    # a silent no-op: `wait` returns 0.0 for an unknown operation, so the call read as
    # rate-limited while doing nothing. A limit that is honest about being ours is better
    # than a call that looks like a limit and is not — and the polling loop in
    # `wait_ready` calls GetGuardrail in a tight loop over ~11 guardrails, which is
    # exactly the burst shape that earns a ThrottlingException on an unadvertised ceiling.
    # 2/s is a guess at a safe floor and is marked as one; if AWS publishes a figure it
    # replaces this and `SELF_IMPOSED_LIMITS` shrinks.
    "CreateGuardrail": 2.0,
    "UpdateGuardrail": 2.0,
    "DeleteGuardrail": 2.0,
    "GetGuardrail": 5.0,
    "ListGuardrails": 5.0,
    "CreateGuardrailVersion": 1.0,
    # Gateway DATA plane — the MCP `tools/call` / `tools/list` request. SELF-IMPOSED, and the
    # measurement behind that word is on the record: `list_service_quotas
    # ServiceCode=bedrock-agentcore` (us-east-1, queried 2026-08-11) returns 184 quotas, and
    # for the tool-call path it publishes only CONCURRENCY —
    #   "Tool-call/tool-list concurrent connections"             = 1000
    #   "Tool-call/tool-list concurrent connections per gateway" = 1000
    #   "Tool-call/tool-list/tool-search payload size"           = 6 MB
    # — with no per-second rate anywhere. The one rate that mentions tool calls,
    # "Rate of search-based tool-call requests = 25/s", is a DIFFERENT operation (tool search,
    # which this project never sends) and citing it here would be labelling our pacing with a
    # ceiling that governs something else.
    #
    # The key is `InvokeGateway` because `bedrock-agentcore:InvokeGateway` is the real IAM
    # action name for this request (infra/01_iam.py:213,261); the wire operation has no
    # botocore operation name at all, since the call is a signed POST rather than an SDK
    # method. Listed rather than omitted for exactly the reason the guardrail block above
    # gives: F4 sends up to 1,440 of these, and `wait()` returns 0.0 for an unknown
    # operation, so `lim.wait("InvokeGateway")` would have read as rate-limited while doing
    # nothing at all — a guard that cannot run must not report clean.
    #
    # 10/s is a chosen floor, not a discovered one. It is 1 serial client at ~10 req/s, two
    # orders of magnitude under the concurrency ceiling, and it makes F4's 1,440 calls take
    # ~2.5 minutes of pacing rather than arriving as a burst. If AWS publishes a figure it
    # replaces this and `SELF_IMPOSED_LIMITS` shrinks.
    "InvokeGateway": 10.0,
}

# Which entries above are *ours* rather than AWS's. A reader of the evidence record must be
# able to tell "the harness spaced these calls because AWS documents a ceiling" from "the
# harness spaced these calls because we were being careful": only the first is a fact about
# the service, and only the first belongs in a claim about it.
SELF_IMPOSED_LIMITS = frozenset({
    "CreateGuardrail", "UpdateGuardrail", "DeleteGuardrail", "GetGuardrail",
    "ListGuardrails", "CreateGuardrailVersion",
    "InvokeGateway",
})

# Per-policy ApplyGuardrail text-unit ceilings, per second (Service Quotas, us-east-1,
# queried 2026-08-10). These sit BELOW the 100 rps request ceiling for two policies, so
# "ApplyGuardrail: 100.0" is not the binding constraint for every arm:
#
#   denied topics, CLASSIC tier ......  50 /s   <-- the tightest, and F3-5's arm
#   denied topics, STANDARD tier ..... 200 /s
#   contextual grounding ............ 106 /s
#   content filters (either tier) .... 200 /s
#   word filters .................... 500 /s
#   sensitive information ........... 1000 /s
#
# The harness sends one text unit per call at ~1 call/s of real spacing, so no arm here
# approaches any of them; they are recorded because a future arm that batches content
# blocks would breach the CLASSIC denied-topic ceiling long before the request ceiling,
# and a ThrottlingException there would be read as guardrail unreliability rather than as
# a quota we chose to exceed.
TEXT_UNIT_LIMITS: dict[str, float] = {
    "topic_classic": 50.0,
    "topic_standard": 200.0,
    "contextual_grounding": 106.0,
    "content_filter": 200.0,
    "word_filter": 500.0,
    "sensitive_information": 1000.0,
}

# The tag set every created resource carries. `Project` is what COST.md attributes spend
# by: this account carries ~$27k/mo of unrelated spend, so service-level cost filtering
# would misattribute other systems' usage to this project.
PROJECT_TAG = "guardrails-doc-validation"
OWNER_TAG = "harness"


def tags_for(run_id: str, expires_at: str) -> dict[str, str]:
    """The tag set asserted by `99_teardown.py`'s sweep.

    Teardown finds resources **by tag**, not by name, because a name is chosen per script
    and a script that dies before recording its resource leaves nothing to look up. Both
    arguments are required for the same reason `region` is: an untagged resource is
    invisible to the sweep, and `ExpiresAt` is what makes an orphan identifiable as one
    rather than as somebody else's gateway.
    """
    if not run_id:
        raise ValueError("run_id is required — an untagged resource is invisible to the "
                         "teardown sweep, which is the only thing that finds orphans")
    if not expires_at:
        raise ValueError("expires_at is required — without it an orphaned resource cannot "
                         "be distinguished from one still in use")
    return {"Project": PROJECT_TAG, "RunId": run_id, "Owner": OWNER_TAG,
            "ExpiresAt": expires_at}


# --------------------------------------------------------------------------
# rate limiting
# --------------------------------------------------------------------------

class RateLimiter:
    """A per-operation minimum interval, shared across clients in one process.

    Deliberately a floor on *spacing*, not a token bucket. A bucket permits a burst that
    drains it, and the burst is precisely what produces a `ThrottlingException` in the
    middle of a determinism arm — where botocore's default retry would silently add
    seconds to one trial's wall clock and we would publish it as a latency observation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        self.waits: dict[str, float] = {}      # cumulative sleep, for the evidence record

    def wait(self, operation: str, *, now: float | None = None,
             sleep=time.sleep) -> float:
        """Block until `operation` may be called again. Returns the seconds waited."""
        rate = RATE_LIMITS.get(operation)
        if not rate:
            return 0.0
        interval = 1.0 / rate
        with self._lock:
            t = now if now is not None else time.monotonic()
            last = self._last.get(operation)
            delay = 0.0 if last is None else max(0.0, last + interval - t)
            # Record the *intended* next slot rather than the observed one, so a series of
            # calls converges on the rate instead of drifting slower by the call duration.
            self._last[operation] = t + delay
            self.waits[operation] = self.waits.get(operation, 0.0) + delay
        if delay:
            sleep(delay)
        return delay


_LIMITER = RateLimiter()


def limiter() -> RateLimiter:
    return _LIMITER


def rate_limit_for(operation: str) -> float | None:
    """The ceiling this harness enforces for `operation`, or None if it enforces none.

    None means "no ceiling is enforced by this harness", which is **not** the same as "the
    API has no ceiling". Callers that need the distinction get it explicitly rather than
    from a 0.0 that reads as unlimited.

    A non-None value is likewise not automatically an AWS-documented figure — six entries
    are self-imposed. Use `limit_provenance` when the answer will be published.
    """
    return RATE_LIMITS.get(operation)


def limit_provenance(operation: str) -> str:
    """Where `operation`'s limit came from: 'aws_documented' | 'self_imposed' | 'none'.

    A rate the harness invented and a rate AWS publishes support different sentences. The
    first can only ever explain the harness's own pacing; only the second is admissible in
    a claim about the service. Keeping them in one dict without this distinction is how a
    self-imposed 2/s would end up cited as a service quota.
    """
    if operation not in RATE_LIMITS:
        return "none"
    return "self_imposed" if operation in SELF_IMPOSED_LIMITS else "aws_documented"


# --------------------------------------------------------------------------
# session and clients
# --------------------------------------------------------------------------

@dataclass
class ClientFactory:
    """Builds clients for one region, optionally under an assumed role.

    `role_arn` exists because Cedar sees the caller as an `AgentCore::IamEntity`: calling
    as the IAM **user** `timwu` makes principal matching in a policy depend on a principal
    the policy was not written for, so the harness assumes `grx-caller` and the policy
    names that role. The assumption happens here rather than in each script so that every
    script's principal is the same fact.
    """

    region: str
    role_arn: str | None = None
    session_name: str = "grx-harness"
    _session: boto3.session.Session | None = field(default=None, repr=False)
    _cache: dict[tuple[str, str], object] = field(default_factory=dict, repr=False)

    def __setattr__(self, name: str, value: object) -> None:
        # `region` is write-once. A mutation run found that the client cache could be keyed
        # on service alone and every behavioural arm still passed — true only because
        # nothing in the suite reassigned `region`. Reassignment is the actual hazard: the
        # cached `Session` would stay pinned to the old region while every subsequently
        # built client pinned to the new one, i.e. one factory in two regions at once,
        # producing evidence records that name whichever region the analysis assumed. There
        # is no legitimate reason to do it — build a second factory — so it raises here
        # rather than being caught by a cache key that happens to notice.
        if name == "region" and getattr(self, "region", None) not in (None, value):
            raise AttributeError(
                f"ClientFactory.region is write-once ({getattr(self, 'region', None)!r} -> "
                f"{value!r}). Reassigning it would leave the cached session in the old "
                f"region while new clients are built in the new one; build a second "
                f"factory instead.")
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        if not self.region:
            raise ValueError(
                "region is required. This project's config file has no default region, so "
                "an omitted region resolves from AWS_REGION/AWS_DEFAULT_REGION — which "
                "would make F8-1's regional result depend on the launching shell while "
                "the record said us-east-1")

    def session(self) -> boto3.session.Session:
        if self._session is not None:
            return self._session
        # region_name is set on the session AND on every client() call. Both are explicit,
        # and explicit outranks AWS_REGION/AWS_DEFAULT_REGION in botocore's resolution
        # order — so an ambient value cannot become the region a result is attributed to.
        base = boto3.session.Session(region_name=self.region)
        if self.role_arn:
            sts = base.client("sts", region_name=self.region,
                              config=self._config("sts"))
            creds = sts.assume_role(RoleArn=self.role_arn,
                                    RoleSessionName=self.session_name)["Credentials"]
            base = boto3.session.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=self.region)
        self._session = base
        return base

    def _config(self, service: str) -> Config:
        # `retries.mode = standard, total_max_attempts = 1` is the load-bearing setting:
        # it turns off botocore's transparent retry. A retried call reports one duration
        # covering several attempts, and an AccessDenied oracle that fired on attempt 3
        # would be recorded as if it fired immediately. Retries are the caller's business
        # (lib/checkpoint.py), where the attempt count can be written into the evidence.
        return Config(
            region_name=self.region,
            retries={"mode": "standard", "total_max_attempts": 1},
            connect_timeout=10,
            read_timeout=70,     # above the slowest documented guardrail evaluation
            user_agent_extra=f"grx-validation/{PROJECT_TAG}",
        )

    def client(self, service: str):
        """A region-pinned, retry-disabled client for `service`."""
        key = (service, self.region)
        if key not in self._cache:
            self._cache[key] = self.session().client(
                service, region_name=self.region, config=self._config(service))
        return self._cache[key]

    # Named accessors for the services this project uses, so a typo is an AttributeError
    # at import rather than a botocore UnknownServiceError at call time — which, in a
    # long overnight arm, would surface after the expensive part.
    def bedrock_runtime(self):
        return self.client("bedrock-runtime")

    def bedrock(self):
        return self.client("bedrock")

    def agentcore_control(self):
        return self.client("bedrock-agentcore-control")

    def agentcore(self):
        return self.client("bedrock-agentcore")

    def ec2(self):
        return self.client("ec2")

    def iam(self):
        return self.client("iam")

    def sts(self):
        return self.client("sts")

    def logs(self):
        return self.client("logs")

    def cloudwatch(self):
        return self.client("cloudwatch")

    def lambda_(self):
        return self.client("lambda")

    def organizations(self):
        return self.client("organizations")

    def pricing(self):
        return self.client("pricing")


def factory(region: str, *, role_arn: str | None = None) -> ClientFactory:
    """The entry point. `region` is positional on purpose."""
    return ClientFactory(region=region, role_arn=role_arn)


def sdk_versions() -> dict[str, str]:
    """Recorded in every evidence file: which SDK saw which API surface.

    F1-1 established that `CreatePolicy.enforcementMode` and `definition.policy` first
    appear at botocore **1.43.32** and `InvokeGuardrailChecks` at **1.43.30**. A result
    collected under 1.42.79 is a statement about that SDK, not about AWS, so the version
    travels with every observation rather than being noted once in a README.
    """
    return {"boto3": boto3.__version__, "botocore": botocore.__version__}


def service_model(service: str):
    """The bundled service model for `service`, WITHOUT building a client.

    Why this is not `factory.client(service).meta.service_model`: constructing a client
    resolves credentials, and with no credentials on the box that walk reaches the EC2
    instance-metadata provider and opens a socket. Under the `no_aws` fixture that raises,
    and in a `--dry-run` it is a network call in a mode whose whole contract is "no AWS
    call" — even though the model itself is a JSON file shipped inside botocore and needs
    no account at all.

    So the model is read straight off a bare `botocore.session`. Config-surface claims (F1,
    F8-4, F8-5, F8-8) are statements about this file, and they should be derivable offline,
    for free, in the same run that prints them.

    `botocore.session.get_session()` is used rather than the module-level `boto3` default
    session so that no ambient region or profile can influence which model is loaded: the
    service model is region-independent, and reading it through a configured session would
    make that non-obvious.
    """
    import botocore.session
    return botocore.session.get_session().get_service_model(service)


def has_operation(client, operation: str) -> bool:
    """Whether the loaded service model exposes `operation` (PascalCase).

    The check F1-1 made routine: an absent parameter is not rejected by botocore, it is
    simply missing from the model, so a call built around it succeeds while doing something
    other than what was asked. Scripts assert this before collecting, so the failure is
    "your SDK cannot express this test" and not a silently different experiment.
    """
    return operation in set(client.meta.service_model.operation_names)


def has_shape_member(client, operation: str, member: str) -> bool:
    """Whether `operation`'s input shape has `member` (dot-separated path allowed)."""
    model = client.meta.service_model
    if operation not in set(model.operation_names):
        return False
    shape = model.operation_model(operation).input_shape
    for part in member.split("."):
        if shape is None or not hasattr(shape, "members"):
            return False
        members = shape.members
        if part not in members:
            return False
        shape = members[part]
    return True


def environment_region_hints() -> dict[str, str]:
    """Ambient region variables, recorded so a reader can see they were not used.

    An empty dict here and an explicit `region` in the record together say the region was
    chosen, not inherited. Recording only the chosen region would look identical whether
    or not this module's guarantee held.
    """
    return {k: v for k, v in os.environ.items()
            if k in ("AWS_REGION", "AWS_DEFAULT_REGION")}
