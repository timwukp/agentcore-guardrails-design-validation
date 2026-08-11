"""Drive `03_permit_trap.main()` end-to-end against a FAKE agentcore-control client.

WHY THIS IS A TEST AND NOT A SCRIPT
-----------------------------------
Every guard in the permit trap and the whole verdict path, exercised offline. A guard proven
only by reasoning is not a guard (`feedback_vacuous_test_check`), and discovering a broken one
from a live run would cost a policy engine, four policies and the experiment — F1-3 is the
single highest-value case in the plan and its arms are not repeatable for free within a day.

This began life as `/tmp/f1_3_mutations.py`, a hand-run script. Two things moved it here.
It found a real defect in my own reasoning (M3: the docstring claimed the mutation "gates the
amendment" while nothing in the record enforced that), which is exactly the kind of finding
that must not depend on my remembering to re-run a file in `/tmp`. And it caused one: it
wrote 221 fabricated call records into the live evidence tree, because `main()` builds its own
`EvidenceStore` and the script never redirected the root. `lib/evidence.capture` now refuses
that combination outright; this module passes `--evidence-root <tmp>`, so the refusal is
*exercised* by every scenario below rather than merely trusted.

WHAT EACH SCENARIO IS FOR
-------------------------
The baseline reproduces measured reality. M1–M8 each break one thing and assert the harness
reports it correctly, per the exit-code convention: **rc reports whether the test RAN, never
whether the document was right.** A case that refutes the document exits 0 (M1); a case that
measured nothing exits 2 (M2, M5–M8); an unclassified hit exits 1 (M4).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import awsclients as A
import phase1 as P
import testbed as T

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "permit_trap", ROOT / "f1_config" / "03_permit_trap.py")
pt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pt)


class FakeAC:
    """Records calls; returns scripted statuses.

    `meta` is borrowed from a real client so `testbed.check_name` reads the genuine name
    pattern out of the service model rather than one I made up — the names this case sends
    are the thing DEV-P2-02 is about, and a hand-written pattern would test my memory of the
    grammar instead of the grammar.

    That borrowing is also why `lib/evidence.capture`'s provenance guard asks
    `isinstance(client, BaseClient)` and not the type of `client.meta`: this object's meta IS
    a genuine `ClientMeta`, so a meta-type check would acquit the one client known to have
    fabricated records.
    """

    def __init__(self, plan, meta):
        self.plan = plan           # arm slug -> (status, reasons), or an Exception to raise
        self.meta = meta
        self.calls = []
        self.policies = {}

    def create_policy_engine(self, **kw):
        self.calls.append(("create_policy_engine", kw))
        if self.plan.get("engine_create_fails"):
            raise ClientError(
                {"Error": {"Code": "ValidationException", "Message": "nope"},
                 "ResponseMetadata": {"HTTPStatusCode": 400, "RequestId": "rq-e"}},
                "CreatePolicyEngine")
        return {"policyEngineId": "pe-fake", "status": "CREATING",
                "ResponseMetadata": {"HTTPStatusCode": 202, "RequestId": "rq-e"}}

    def get_policy_engine(self, **kw):
        return {"policyEngineId": "pe-fake",
                "status": self.plan.get("engine_status", "ACTIVE"),
                "statusReasons": self.plan.get("engine_reasons", []),
                "ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": "rq-ge"}}

    @staticmethod
    def _arm_of(name):
        for slug in ("dflt", "failfind", "ignfind", "narrow"):
            if f"_{slug}_" in name:
                return slug
        raise AssertionError(f"unrecognised arm in policy name {name!r}")

    def create_policy(self, **kw):
        self.calls.append(("create_policy", kw))
        slug = self._arm_of(kw["name"])
        outcome = self.plan[slug]
        if isinstance(outcome, Exception):
            raise outcome
        pid = f"pol-{slug}"
        self.policies[pid] = outcome
        # 202, matching the live measurement. The first version of this fake returned 200
        # because the plan assumed 200; the live run showed 202 Accepted, and a fake that
        # kept the assumed value would quietly re-assert it in every offline arm.
        return {"policyId": pid, "name": kw["name"], "status": "CREATING",
                "policyArn": ("arn:aws:bedrock-agentcore:us-east-1:111122223333:"
                              f"policy-engine/pe-fake/policy/{pid}"),
                "enforcementMode": "ACTIVE",
                "ResponseMetadata": {"HTTPStatusCode": 202, "RequestId": f"rq-{slug}"}}

    def get_policy(self, **kw):
        status, reasons = self.policies[kw["policyId"]]
        return {"policyId": kw["policyId"], "status": status, "statusReasons": reasons,
                "enforcementMode": "ACTIVE",
                "ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": "rq-gp"}}

    def delete_policy(self, **kw):
        self.calls.append(("delete_policy", kw))
        self.policies.pop(kw["policyId"], None)
        return {"ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": "rq-dp"}}

    def delete_policy_engine(self, **kw):
        self.calls.append(("delete_policy_engine", kw))
        return {"ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": "rq-dpe"}}


# The two Overly Permissive reasons the live run returned, one per principal type. Verbatim
# rather than paraphrased: the classifier matches on this text, so a paraphrase would test
# the paraphrase.
OP = [
    "Overly Permissive: Policy Engine will allow every request for the specified principal "
    "(AgentCore::IamEntity), action (Any Future Tools) and resource (gateway/*) combination "
    "if the policy is added or updated",
    "Overly Permissive: Policy Engine will allow every request for the specified principal "
    "(AgentCore::OAuthUser), action (Any Future Tools) and resource (gateway/*) combination "
    "if the policy is added or updated",
]

SYNC_REJECT = ClientError(
    {"Error": {"Code": "ValidationException", "Message": "bad cedar"},
     "ResponseMetadata": {"HTTPStatusCode": 400, "RequestId": "rq-x"}},
    "CreatePolicy")

# (id, plan, expected rc, expected verdict, expected mutation_inverted)
SCENARIOS = [
    ("baseline",
     dict(dflt=("CREATE_FAILED", OP), failfind=("CREATE_FAILED", OP),
          ignfind=("ACTIVE", []), narrow=("ACTIVE", [])),
     0, "TRUE", True),

    ("M1-doc-arm-succeeds",
     dict(dflt=("ACTIVE", []), failfind=("ACTIVE", []),
          ignfind=("ACTIVE", []), narrow=("ACTIVE", [])),
     0, "FALSE", None),

    ("M2-control-also-fails",
     dict(dflt=("CREATE_FAILED", OP), failfind=("CREATE_FAILED", OP),
          ignfind=("ACTIVE", []), narrow=("CREATE_FAILED", OP)),
     2, "INCONCLUSIVE", None),

    ("M3-mutation-does-not-invert",
     dict(dflt=("CREATE_FAILED", OP), failfind=("CREATE_FAILED", OP),
          ignfind=("CREATE_FAILED", OP), narrow=("ACTIVE", [])),
     0, "TRUE", False),

    ("M4-unrelated-failure",
     dict(dflt=("CREATE_FAILED", ["Syntax error at line 1"]),
          failfind=("CREATE_FAILED", ["Syntax error at line 1"]),
          ignfind=("ACTIVE", []), narrow=("ACTIVE", [])),
     1, "INCONCLUSIVE", None),

    ("M5-synchronous-rejection",
     dict(dflt=SYNC_REJECT, failfind=("ACTIVE", []),
          ignfind=("ACTIVE", []), narrow=("ACTIVE", [])),
     2, "INCONCLUSIVE", None),

    ("M6-engine-never-active",
     dict(engine_status="CREATE_FAILED", engine_reasons=["encryption key invalid"],
          dflt=("CREATE_FAILED", OP), failfind=("CREATE_FAILED", OP),
          ignfind=("ACTIVE", []), narrow=("ACTIVE", [])),
     2, "INCONCLUSIVE", None),

    ("M7-engine-create-refused",
     dict(engine_create_fails=True,
          dflt=("CREATE_FAILED", OP), failfind=("CREATE_FAILED", OP),
          ignfind=("ACTIVE", []), narrow=("ACTIVE", [])),
     2, "INCONCLUSIVE", None),

    ("M8-doc-arm-never-settles",
     dict(dflt=("CREATING", []), failfind=("ACTIVE", []),
          ignfind=("ACTIVE", []), narrow=("ACTIVE", [])),
     2, "INCONCLUSIVE", None),
]


@pytest.fixture
def ledger(tmp_path):
    """A COPY of the real ledger.

    A copy, not the live `state.json`: `main()` records the policies it creates and drops
    them again in teardown, and nine scenarios writing that file would mutate the ledger a
    live testbed resumes from. Copied rather than synthesised because the case reads a real
    gateway ARN and caller role out of it — `build_statements` refuses to run without both,
    and a synthetic ledger would be me deciding what the control looks like.
    """
    src = T.STATE_PATH
    if not src.exists():
        pytest.skip("no ledger at state.json; the testbed is not built")
    dst = tmp_path / "state.json"
    shutil.copy2(src, dst)
    return dst


@pytest.fixture
def real_meta():
    """A genuine service-model meta, for `check_name`'s pattern read.

    Client construction is offline — botocore resolves credentials lazily — so this runs
    under the autouse `no_aws` socket block.
    """
    return A.factory("us-east-1").agentcore_control().meta


def run_scenario(plan, *, ledger, real_meta, tmp_path, monkeypatch):
    """Drive `main()` once and return `(rc, emitted_record)`."""
    fake = FakeAC(plan, real_meta)
    monkeypatch.setattr(
        pt.A, "factory",
        lambda *a, **k: types.SimpleNamespace(
            agentcore_control=lambda: fake,
            sts=lambda: types.SimpleNamespace(
                get_caller_identity=lambda: {"Account": "111122223333"})))

    # `wait_status` is replaced rather than sped up: the real one sleeps 3s between polls to a
    # 180s ceiling, so M8 alone would take three minutes. The replacement keeps the contract
    # that matters here — terminal statuses return, a non-terminal one raises TimeoutError.
    def _poll(get, ident, **kw):
        r = get(**ident)
        if r.get("status") in ("CREATING", "UPDATING"):
            raise TimeoutError(
                "status never became terminal in 180s; last=CREATING reasons=[]")
        return r
    monkeypatch.setattr(pt, "wait_status", _poll)

    emitted = {}

    def _emit(case_id, record, payload, store=None, **kw):
        emitted.update(case_id=case_id, record=record, payload=payload)
        return tmp_path / "analysis.json"
    monkeypatch.setattr(pt.P, "emit", _emit)

    rc = pt.main(["--state", str(ledger),
                  "--evidence-root", str(tmp_path / "evidence")])
    return rc, emitted


@pytest.mark.parametrize("name,plan,want_rc,want_verdict,want_inverted",
                         SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_scenario(name, plan, want_rc, want_verdict, want_inverted,
                  ledger, real_meta, tmp_path, monkeypatch):
    rc, emitted = run_scenario(plan, ledger=ledger, real_meta=real_meta,
                               tmp_path=tmp_path, monkeypatch=monkeypatch)
    rec = emitted.get("record") or {}
    assert rec, f"{name}: nothing was emitted, so nothing can be checked"
    assert rec["verdict"] == want_verdict, f"{name}: verdict"
    # rc reports whether the test RAN. M1 refutes the document and still exits 0.
    assert rc == want_rc, f"{name}: exit code"

    payload = emitted.get("payload") or {}
    got_inverted = (payload.get("mutation") or {}).get("inverted")
    assert got_inverted == want_inverted, f"{name}: mutation.inverted"


def test_no_record_is_written_into_the_live_evidence_tree(ledger, real_meta, tmp_path,
                                                         monkeypatch):
    """The 2026-08-10 incident, as an assertion rather than a resolution.

    Nine parametrized scenarios above pass `--evidence-root`; this arm proves the redirect
    is real by checking the tmp tree filled up AND that the live run directory did not gain
    a file. Both halves are needed: a redirect that silently wrote nowhere would satisfy the
    second alone.
    """
    live = pt.EvidenceStore.__module__ and __import__("evidence").EVIDENCE_ROOT
    before = {p for p in live.rglob("*.json")} if live.exists() else set()

    rc, emitted = run_scenario(
        dict(dflt=("CREATE_FAILED", OP), failfind=("CREATE_FAILED", OP),
             ignfind=("ACTIVE", []), narrow=("ACTIVE", [])),
        ledger=ledger, real_meta=real_meta, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert rc == 0

    after = {p for p in live.rglob("*.json")} if live.exists() else set()
    assert after == before, f"records leaked into the live evidence tree: {after - before}"
    written = list((tmp_path / "evidence").rglob("*.json"))
    assert written, "the redirect wrote nothing, so the leak check above proves nothing"
    # And what it wrote is a real record, not an empty placeholder.
    bodies = [json.loads(p.read_text(encoding="utf-8")) for p in written
              if p.name[0].isdigit()]
    assert any(b.get("operation") == "create_policy" for b in bodies)


def test_the_provenance_guard_would_have_caught_the_original_mistake(ledger, real_meta,
                                                                    monkeypatch, tmp_path):
    """Without `--evidence-root`, a fake client must be REFUSED, not recorded.

    This is the mutation check on the fix itself. If `capture`'s provenance guard were
    removed, this arm would pass silently while writing fabricated records into
    `evidence/<ledger run id>/f1/F1-3/` — so it asserts the refusal, and asserts that
    nothing was written.
    """
    import evidence as ev
    fake = FakeAC(dict(dflt=("CREATE_FAILED", OP), failfind=("CREATE_FAILED", OP),
                       ignfind=("ACTIVE", []), narrow=("ACTIVE", [])), real_meta)
    monkeypatch.setattr(
        pt.A, "factory",
        lambda *a, **k: types.SimpleNamespace(
            agentcore_control=lambda: fake,
            sts=lambda: types.SimpleNamespace(
                get_caller_identity=lambda: {"Account": "111122223333"})))
    monkeypatch.setattr(ev, "EVIDENCE_ROOT", tmp_path / "pretend-live")

    with pytest.raises(ev.EvidenceProvenanceError):
        pt.main(["--state", str(ledger)])

    leaked = list((tmp_path / "pretend-live").rglob("0*.json"))
    assert not leaked, f"fabricated records were written before the refusal: {leaked}"
