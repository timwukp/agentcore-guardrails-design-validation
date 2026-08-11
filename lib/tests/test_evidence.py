"""Tests for lib/evidence.py, run offline under the autouse ``no_aws`` fixture.

What is actually at stake here
------------------------------
``capture()`` is the only thing standing between an AWS API call and the published
record of it. If it silently drops a request ID, or turns an ``AccessDenied`` into
an exception that nobody records, then a red-team case whose entire result lives in
the error path produces no evidence at all — and the failure is invisible, because
the test that used the wrapper would just show a stack trace and be re-run.

So these tests assert on the two properties that cannot be checked later:

  1. the error path is recorded as fully as the success path, and
  2. a recorded field is not present-but-empty (an empty ``request_id`` written to
     disk looks identical to a service that returned none).

Every client here is a stub. Per ``feedback_verify_against_real_artifact`` a stub
only confirms my own assumptions, so the stub response shapes are copied from real
botocore responses captured in this project's own evidence tree — specifically the
``ResponseMetadata`` block shape from a live ``DescribeVpcEndpointServices`` call
and the ``ClientError.response`` shape from a real ``AccessDenied``. What the stubs
are NOT relied on for is proof that the wrapper works against the service; that is
what the F5-7a live run provides.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

import evidence as ev


# --------------------------------------------------------------------------
# stubs
# --------------------------------------------------------------------------

class _ServiceModel:
    def __init__(self, name):
        self.service_name = name


class _Meta:
    def __init__(self, service, region):
        self.service_model = _ServiceModel(service)
        self.region_name = region


class StubClient:
    """Minimal boto3-client shape: ``.meta`` plus dynamically-named methods."""

    def __init__(self, service="ec2", region="us-east-1", result=None, raises=None):
        self.meta = _Meta(service, region)
        self._result = result
        self._raises = raises
        self.calls = []

    def __getattr__(self, name):
        def _call(**params):
            self.calls.append((name, params))
            if self._raises is not None:
                raise self._raises
            return self._result
        return _call


OK_RESPONSE = {
    "ServiceNames": ["com.amazonaws.us-east-1.bedrock-agentcore"],
    "ResponseMetadata": {
        "RequestId": "3db4b1f3-fab0-4293-914b-995973bf1901",
        "HTTPStatusCode": 200,
        "HTTPHeaders": {
            "x-amzn-requestid": "3db4b1f3-fab0-4293-914b-995973bf1901",
            "content-type": "text/xml;charset=UTF-8",
            "date": "Sat, 09 Aug 2026 08:00:00 GMT",
        },
        "RetryAttempts": 0,
    },
}

ACCESS_DENIED = ClientError(
    {
        "Error": {"Code": "AccessDenied",
                  "Message": "User is not authorized to perform: "
                             "bedrock-agentcore:UpdateGateway"},
        "ResponseMetadata": {
            "RequestId": "cbd079f8-859f-4159-9687-4bb40731818b",
            "HTTPStatusCode": 403,
            "HTTPHeaders": {
                "x-amzn-requestid": "cbd079f8-859f-4159-9687-4bb40731818b",
                "x-amzn-errortype": "AccessDeniedException",
            },
            "RetryAttempts": 0,
        },
    },
    "UpdateGateway",
)


@pytest.fixture
def store(tmp_path):
    return ev.EvidenceStore(run_id="rTEST", family="f5", case_id="F5-TEST",
                            root=tmp_path)


# --------------------------------------------------------------------------
# success path
# --------------------------------------------------------------------------

def test_success_captures_request_id_status_and_body(store):
    c = StubClient(result=OK_RESPONSE)
    rec = ev.capture(store, "describe_vpc_endpoint_services", c, Filters=[])

    assert rec.ok is True
    assert rec.request_id == "3db4b1f3-fab0-4293-914b-995973bf1901"
    assert rec.http_status == 200
    assert rec.retry_attempts == 0
    assert rec.response == {"ServiceNames":
                            ["com.amazonaws.us-east-1.bedrock-agentcore"]}
    # ResponseMetadata is captured into fields, not left duplicated in the body.
    assert "ResponseMetadata" not in (rec.response or {})
    assert rec.service == "ec2" and rec.region == "us-east-1"
    assert rec.duration_ms >= 0.0


def test_record_is_written_to_disk_and_is_valid_json(store):
    c = StubClient(result=OK_RESPONSE)
    rec = ev.capture(store, "describe_vpc_endpoint_services", c)
    written = sorted(store.dir.glob("*.json"))
    assert len(written) == 1
    body = json.loads(written[0].read_text())
    assert body["request_id"] == rec.request_id
    assert body["operation"] == "describe_vpc_endpoint_services"
    assert written[0].name.endswith("_ok.json")


def test_sequence_numbers_order_calls_within_the_same_millisecond(store):
    c = StubClient(result=OK_RESPONSE)
    for _ in range(3):
        ev.capture(store, "describe_vpc_endpoint_services", c)
    names = sorted(p.name for p in store.dir.glob("*.json"))
    assert [n.split("_")[0] for n in names] == ["0001", "0002", "0003"]


# --------------------------------------------------------------------------
# replication — a second store on the same directory must not erase the first
# --------------------------------------------------------------------------

def test_a_second_store_resumes_the_sequence_instead_of_overwriting(tmp_path):
    """The `>=2 separate calendar days` rule is discharged INTO an existing directory.

    Gateway-side cases adopt the ledger's run id, so day 2 necessarily writes to day 1's
    path. `check_amendment_readiness.py` counts distinct `t_start_utc` days across those
    files, so a sequence that restarted at 0 would delete day 1 and the replication would
    read as one day — the run that earns the amendment revoking it instead.
    """
    kw = dict(run_id="rTEST", family="f1", case_id="F1-TEST", root=tmp_path)
    day1 = ev.EvidenceStore(**kw)
    for _ in range(2):
        ev.capture(day1, "describe_vpc_endpoint_services", StubClient(result=OK_RESPONSE))
    # Contents, not names: a restarted sequence reuses the same NAMES with new contents, so
    # a set-of-names assertion would pass while the records underneath had been destroyed.
    day1_bodies = {p.name: p.read_text(encoding="utf-8") for p in day1.dir.glob("*.json")}

    day2 = ev.EvidenceStore(**kw)
    ev.capture(day2, "describe_vpc_endpoint_services", StubClient(result=OK_RESPONSE))

    for name, body in day1_bodies.items():
        assert (day2.dir / name).read_text(encoding="utf-8") == body, (
            f"{name} was rewritten by the second run — day 1's observation is gone")
    all_names = {p.name for p in day2.dir.glob("*.json")}
    assert len(all_names) == 3
    assert sorted(n.split("_")[0] for n in all_names) == ["0001", "0002", "0003"]


def test_resume_ignores_non_sequence_files(tmp_path):
    """summary.json / analysis.json / environment.json are indexes, not evidence.

    They are single-slot and overwritten by design. If `_highest_seq` counted them it
    would still return 0 here, so this arm pins that a directory holding ONLY indexes
    starts a fresh sequence at 0001 rather than skipping numbers.
    """
    kw = dict(run_id="rTEST", family="f1", case_id="F1-IDX", root=tmp_path)
    s = ev.EvidenceStore(**kw)
    s.write_environment()
    s.write_summary()
    again = ev.EvidenceStore(**kw)
    rec = ev.capture(again, "describe_vpc_endpoint_services", StubClient(result=OK_RESPONSE))
    assert Path(rec.path).name.startswith("0001_")


def test_highest_seq_reads_widths_above_four_digits(tmp_path):
    """A case exceeding 9999 calls must not wrap back into an existing name."""
    (tmp_path / "10000_apply_guardrail_ok.json").write_text("{}", encoding="utf-8")
    (tmp_path / "0007_apply_guardrail_ok.json").write_text("{}", encoding="utf-8")
    assert ev._highest_seq(tmp_path) == 10000


# --------------------------------------------------------------------------
# error path — this is where half the project's oracles live
# --------------------------------------------------------------------------

def test_client_error_is_data_not_an_exception(store):
    c = StubClient(raises=ACCESS_DENIED)
    rec = ev.capture(store, "update_gateway", c, gatewayIdentifier="gw-1")

    assert rec.ok is False
    assert rec.error_code == "AccessDenied"
    assert "UpdateGateway" in rec.error_message
    assert rec.error_class == "ClientError"
    assert rec.http_status == 403


def test_error_path_captures_the_request_id_too(store):
    """The AccessDenied request id IS the evidence for F5-1/F5-2/F5-3b."""
    c = StubClient(raises=ACCESS_DENIED)
    rec = ev.capture(store, "update_gateway", c)
    assert rec.request_id == "cbd079f8-859f-4159-9687-4bb40731818b"
    assert rec.request_id != ""


def test_error_record_is_written_and_marked_err(store):
    c = StubClient(raises=ACCESS_DENIED)
    ev.capture(store, "update_gateway", c)
    written = sorted(store.dir.glob("*.json"))
    assert len(written) == 1 and written[0].name.endswith("_err.json")
    body = json.loads(written[0].read_text())
    assert body["error_code"] == "AccessDenied"


def test_botocore_error_without_response_still_recorded(store):
    """A connection failure has no ResponseMetadata; it must not lose the record."""
    c = StubClient(raises=EndpointConnectionError(endpoint_url="https://x.invalid"))
    rec = ev.capture(store, "describe_vpc_endpoint_services", c)
    assert rec.ok is False
    assert rec.error_class == "EndpointConnectionError"
    assert rec.error_message                       # non-empty
    assert rec.request_id == ""                    # honestly absent, not fabricated
    assert rec.http_status is None


def test_unexpected_exception_is_not_swallowed(store):
    """Only ClientError/BotoCoreError are data. A TypeError is a harness bug and
    must propagate — recording it as a failed AWS call would attribute our own
    defect to the service."""
    c = StubClient(raises=TypeError("bad param"))
    with pytest.raises(TypeError):
        ev.capture(store, "describe_vpc_endpoint_services", c)


def test_raise_for_status_is_opt_in(store):
    c = StubClient(raises=ACCESS_DENIED)
    rec = ev.capture(store, "update_gateway", c)
    with pytest.raises(RuntimeError) as exc:
        rec.raise_for_status()
    assert "AccessDenied" in str(exc.value)
    assert "cbd079f8" in str(exc.value)            # the id travels with the error
    ok = ev.capture(store, "describe", StubClient(result=OK_RESPONSE))
    assert ok.raise_for_status() is ok             # returns self on success


def test_the_raised_error_carries_the_aws_error_code_not_just_its_text(store):
    """The code must survive as a *field*, because a downstream layer branches on it.

    `capture()` absorbs the `ClientError` deliberately — an error is data here, since half
    this project's oracles are `AccessDenied` — so `raise_for_status` is the only path by
    which the code leaves this module. The original raised a bare `RuntimeError` with the
    code interpolated into the message, and `lib/checkpoint.is_retryable` classifies an
    unrecognised exception as **permanent** (an allowlist, so a harness bug does not read
    as service flakiness). The two together meant a `ThrottlingException` reaching
    `run_trial` through this path got zero retries: the entire backoff mechanism was dead
    on the only code path that uses it, and the loss surfaced as a smaller denominator
    rather than as an error.

    Parsing the code back out of the message would be the other repair, and is worse: the
    message is for humans, and a retry policy that depends on its wording breaks the first
    time the wording improves.
    """
    c = StubClient(raises=ACCESS_DENIED)
    rec = ev.capture(store, "update_gateway", c)
    with pytest.raises(ev.CapturedCallError) as exc:
        rec.raise_for_status()
    assert exc.value.error_code == rec.error_code != ""
    assert exc.value.request_id == rec.request_id
    assert exc.value.error_class == rec.error_class
    # Still a RuntimeError, so every existing `except RuntimeError` keeps working: this
    # widens what a caller can see without narrowing what it already caught.
    assert isinstance(exc.value, RuntimeError)


# --------------------------------------------------------------------------
# header handling and serialization
# --------------------------------------------------------------------------

def test_request_id_falls_back_to_headers_when_metadata_omits_it(store):
    """Some responses carry the id only in the header block."""
    resp = {
        "Ok": True,
        "ResponseMetadata": {
            "HTTPStatusCode": 200,
            "HTTPHeaders": {"X-Amzn-RequestId": "MIXEDCASE-1234"},
        },
    }
    rec = ev.capture(store, "op", StubClient(result=resp))
    assert rec.request_id == "MIXEDCASE-1234"


def test_datetimes_and_bytes_survive_serialization(store):
    resp = {
        "createdAt": datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
        "blob": b"\x00\xff",
        "ResponseMetadata": {"RequestId": "x", "HTTPStatusCode": 200,
                             "HTTPHeaders": {}},
    }
    ev.capture(store, "op", StubClient(result=resp))
    body = json.loads(sorted(store.dir.glob("*.json"))[0].read_text())
    assert body["response"]["createdAt"] == "2026-08-09T12:00:00+00:00"
    assert body["response"]["blob"] == {"__bytes_latin1__": "\x00ÿ"}


def test_headers_are_lowercased_for_stable_lookup(store):
    resp = {"ResponseMetadata": {"HTTPStatusCode": 200,
                                 "HTTPHeaders": {"X-Amzn-Trace-Id": "Root=1-a-b"},
                                 "RequestId": "r"}}
    rec = ev.capture(store, "op", StubClient(result=resp))
    assert rec.trace_id == "Root=1-a-b"
    assert "x-amzn-trace-id" in rec.headers


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------

def test_prereg_hash_is_read_at_call_time_not_frozen_at_import(store, monkeypatch,
                                                               tmp_path):
    """Re-sealing mid-project must be visible on the face of the evidence."""
    seal = tmp_path / "SEAL"
    seal.write_text("aaaa1111 first\n")
    monkeypatch.setattr(ev, "PREREG_HASH_FILE", seal)
    r1 = ev.capture(store, "op", StubClient(result=OK_RESPONSE))
    seal.write_text("bbbb2222 second\n")
    r2 = ev.capture(store, "op", StubClient(result=OK_RESPONSE))
    assert (r1.prereg_sha256, r2.prereg_sha256) == ("aaaa1111", "bbbb2222")


def test_missing_seal_is_labelled_not_fatal(store, monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "PREREG_HASH_FILE", tmp_path / "does-not-exist")
    rec = ev.capture(store, "op", StubClient(result=OK_RESPONSE))
    assert rec.prereg_sha256 == "UNSEALED"


def test_environment_carries_no_account_identifier(store):
    """This file is published; the redaction gate treats 12 digits as a finding."""
    blob = json.dumps(store.environment())
    assert not re.search(r"\b\d{12}\b", blob)
    assert "arn:aws" not in blob
    assert store.environment()["sdk_version"]


def test_summary_indexes_every_call_including_failures(store):
    ev.capture(store, "ok_op", StubClient(result=OK_RESPONSE))
    ev.capture(store, "bad_op", StubClient(raises=ACCESS_DENIED))
    p = store.write_summary({"analysis_file": "analysis.json"})
    body = json.loads(p.read_text())
    assert body["n_calls"] == 2 and body["n_ok"] == 1 and body["n_err"] == 1
    assert {c["operation"] for c in body["calls"]} == {"ok_op", "bad_op"}
    assert body["analysis_file"] == "analysis.json"


def test_new_run_id_generates_a_utc_stamp():
    auto = ev.new_run_id()
    # "r" + YYYYMMDD + "T" + HHMMSS + "Z" = 1 + 8 + 1 + 6 + 1 = 17
    assert auto.startswith("r") and auto.endswith("Z") and len(auto) == 17
    assert re.fullmatch(r"r\d{8}T\d{6}Z", auto)


def test_new_run_id_accepts_a_stamp_that_agrees_with_the_utc_date():
    now = datetime(2026, 8, 9, 16, 20, tzinfo=timezone.utc)
    assert ev.new_run_id("r20260809T162000Z", now=now) == "r20260809T162000Z"


def test_new_run_id_refuses_a_stamp_naming_another_day():
    """The mistake this guard exists for, reproduced.

    `r20260810T0930Z` was minted for the F5-7a replication because the *local*
    calendar had rolled to the 10th while UTC was still 2026-08-09T16:20. Evidence
    records are stamped in UTC and the replication rule counts UTC days, so that run
    id labelled a 6.8-hour repeat as a second day of observation. The authoritative
    catch is downstream (07a_compare_runs.py reads t_start_utc, and
    check_amendment_readiness.py never trusts a run id) — but nothing downstream
    renames a directory, so a mislabelled name would mislead every later reader.
    """
    now = datetime(2026, 8, 9, 16, 20, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="names date 2026-08-10"):
        ev.new_run_id("r20260810T0930Z", now=now)
    # and the other direction: a stamp naming yesterday is equally wrong
    with pytest.raises(ValueError, match="names date 2026-08-08"):
        ev.new_run_id("r20260808T235959Z", now=now)


def test_new_run_id_refuses_an_unparseable_stamp():
    """`rFIXED` used to be accepted. A run id whose date cannot be read cannot be
    checked against the clock, so accepting one reintroduces the whole failure mode
    through a different door."""
    now = datetime(2026, 8, 9, 16, 20, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="not of the form"):
        ev.new_run_id("rFIXED", now=now)


# --------------------------------------------------------------------------
# filename safety — the evidence writer must not be the thing that fails
# --------------------------------------------------------------------------

MCP_METHODS = ("initialize", "notifications/initialized", "tools/list", "tools/call",
               "prompts/list", "prompts/get", "resources/list")


@pytest.mark.parametrize("method", MCP_METHODS)
def test_every_mcp_method_can_be_written_as_a_record(store, method):
    """The live failure, reproduced for the whole method set rather than the one that broke.

    `08_smoke.py --run` died with `FileNotFoundError` writing
    `0002_mcp:notifications/initialized_ok.json`: the `/` in a JSON-RPC method name is a
    directory separator, so the evidence writer tried to create a file inside a directory that
    does not exist. The AWS call had already succeeded and been billed at that point — the
    archive is what failed, which is the one failure mode this module exists to prevent.

    Parametrized over every method the harness sends because `initialize` is the only one
    without a `/`, and it passing is exactly what hid the bug.
    """
    rec = ev.Record(case_id=store.case_id, operation=f"mcp:{method}", service="mcp",
                    region="us-east-1", params={}, ok=True, http_status=200)
    store.add(rec)                       # must not raise
    written = sorted(store.dir.glob("*.json"))
    assert len(written) == 1
    assert written[0].parent == store.dir, "record escaped its case directory"
    # the lossy name does not cost us the operation: it is still exact in the body
    assert json.loads(written[0].read_text())["operation"] == f"mcp:{method}"


def test_the_record_path_field_points_at_the_file_that_exists(store):
    """`rec.path` is what an analysis follows to reopen a call. If `add()` sanitizes the name
    but records the unsanitized one, every MCP row in the archive carries a dangling path —
    silently, since nothing re-reads it until analysis."""
    rec = ev.Record(case_id=store.case_id, operation="mcp:tools/call", service="mcp",
                    region="us-east-1", params={}, ok=True, http_status=200)
    store.add(rec)
    assert (ev.ROOT / rec.path).exists() or Path(rec.path).exists()


@pytest.mark.parametrize("raw,expected", [
    ("tools/call", "tools-call"),
    ("mcp:tools/call", "mcp-tools-call"),
    ("create_gateway", "create_gateway"),          # the common case must be untouched
    ("describe_vpc_endpoint_services", "describe_vpc_endpoint_services"),
    ("a b", "a-b"),
    ("../../etc/passwd", "etc-passwd"),            # traversal cannot survive one component
    ("...", "unnamed"),                            # stripping must not yield an empty name
    ("", "unnamed"),
])
def test_safe_component_maps_the_cases_that_matter(raw, expected):
    assert ev.safe_component(raw) == expected


def test_safe_component_never_returns_a_path_separator_or_empty():
    """The property, not the examples: whatever goes in, the result is one usable component."""
    for raw in ("a/b", "a\\b", "/", "//", "..", "a:b*c?d", "\n", "é/ü"):
        out = ev.safe_component(raw)
        assert out, f"empty component for {raw!r}"
        assert "/" not in out and "\\" not in out
        assert out not in (".", ".."), f"{raw!r} produced a directory reference"


def test_the_filename_guard_is_load_bearing(store, monkeypatch):
    """Mutation check, per `feedback_vacuous_test_check`.

    The tests above would also pass against a `safe_component` that did nothing, IF the
    filesystem tolerated `/` in a name — it does not, but that is a property of the platform,
    not of this code, and the assertion should fail for the stated reason. So: neutralize the
    sanitizer and confirm the write actually breaks. If this test stops raising, the guard has
    become decoration and the parametrized tests above have stopped proving anything.
    """
    monkeypatch.setattr(ev, "safe_component", lambda s: s)
    rec = ev.Record(case_id=store.case_id, operation="mcp:tools/call", service="mcp",
                    region="us-east-1", params={}, ok=True, http_status=200)
    with pytest.raises((FileNotFoundError, NotADirectoryError, OSError)):
        store.add(rec)


# --------------------------------------------------------------------------
# provenance — a fabricated call may not be filed as an observation
# --------------------------------------------------------------------------

def test_synthetic_client_is_refused_when_the_store_is_in_the_live_tree(monkeypatch,
                                                                       tmp_path):
    """The 2026-08-10 F1-3 incident, pinned as an arm.

    The offline mutation harness drove `main()` against a fake bedrock-agentcore-control and
    wrote 221 fabricated records into `evidence/<ledger run id>/f1/F1-3/`, where
    `check_amendment_readiness.py` counts `t_start_utc` days. It patched the analysis writer,
    so no fake verdict shipped; nothing stopped the fake *evidence*.

    EVIDENCE_ROOT is monkeypatched to a tmp dir so this arm proves the rule without writing
    to the real tree — the store path is `<fake live root>/...`, which is what
    `is_relative_to` tests.
    """
    monkeypatch.setattr(ev, "EVIDENCE_ROOT", tmp_path / "evidence")
    store = ev.EvidenceStore(run_id="rTEST", family="f1", case_id="F1-3")
    with pytest.raises(ev.EvidenceProvenanceError) as e:
        ev.capture(store, "create_policy", StubClient(result=OK_RESPONSE), name="x")
    assert "synthetic" in str(e.value)
    assert not list(store.dir.glob("0*.json")), "a refused call must leave no record"


def test_synthetic_client_is_allowed_outside_the_live_tree(tmp_path):
    """Offline harnesses pass `root=`; what is blocked is forgetting to, not testing."""
    store = ev.EvidenceStore(run_id="rTEST", family="f1", case_id="F1-3",
                             root=tmp_path / "elsewhere")
    rec = ev.capture(store, "create_policy", StubClient(result=OK_RESPONSE), name="x")
    assert rec.ok is True
    assert len(list(store.dir.glob("0*.json"))) == 1


def test_a_real_botocore_client_meta_is_not_refused(monkeypatch, tmp_path):
    """The guard must acquit the innocent: a genuine client writing to the live tree.

    Built with `botocore.session` so it is a real `BaseClient` — per
    `feedback_verify_against_real_artifact`, a hand-made object asserting
    `isinstance(..., BaseClient)` would only confirm my own assumption about what the
    check reads. No credentials and no network: the call is monkeypatched out, so what is
    exercised is the provenance branch, not AWS.
    """
    import botocore.session
    client = botocore.session.get_session().create_client(
        "sts", region_name="us-east-1",
        aws_access_key_id="AKIAINVALID", aws_secret_access_key="x")
    assert isinstance(client, ev.BaseClient)
    monkeypatch.setattr(type(client), "get_caller_identity",
                        lambda self, **kw: OK_RESPONSE, raising=False)
    monkeypatch.setattr(ev, "EVIDENCE_ROOT", tmp_path / "evidence")
    store = ev.EvidenceStore(run_id="rTEST", family="f1", case_id="F1-REAL")
    rec = ev.capture(store, "get_caller_identity", client)
    assert rec.ok is True
    assert len(list(store.dir.glob("0*.json"))) == 1


def test_the_guard_fires_on_a_fake_that_borrowed_a_real_clientmeta(monkeypatch, tmp_path):
    """The exact shape of the 2026-08-10 offender, which the first guard would have passed.

    `f1_config/tests/f1_3_offline_mutations.py`'s FakeAC sets `self.meta = REAL_AC.meta` so
    `testbed.check_name` reads name patterns from the genuine service model. That makes
    `isinstance(client.meta, ClientMeta)` TRUE, so a meta-type check acquits the one client
    known to have fabricated 221 records. This arm pins the discriminator that does not.
    """
    import botocore.session
    real = botocore.session.get_session().create_client(
        "sts", region_name="us-east-1",
        aws_access_key_id="AKIAINVALID", aws_secret_access_key="x")

    class BorrowedMeta:
        def __init__(self):
            self.meta = real.meta
        def create_policy(self, **kw):
            return OK_RESPONSE

    import botocore.client
    assert isinstance(BorrowedMeta().meta, botocore.client.ClientMeta), (
        "the premise of this arm is that the borrowed meta is genuine")

    monkeypatch.setattr(ev, "EVIDENCE_ROOT", tmp_path / "evidence")
    store = ev.EvidenceStore(run_id="rTEST", family="f1", case_id="F1-3")
    with pytest.raises(ev.EvidenceProvenanceError):
        ev.capture(store, "create_policy", BorrowedMeta(), name="x")
    assert not list(store.dir.glob("0*.json"))
