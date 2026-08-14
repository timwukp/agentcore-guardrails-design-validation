#!/usr/bin/env python3
"""F5-7b holds `ec2:Delete*` on `*`, and the only bound on it is in the script.

This is the first case in the project that builds a VPC, so it is the first that needed
`ec2:CreateVpc`, `ec2:CreateRoute` and their inverses in the runner's derived policy. EC2 network
resources are not nameable by ARN pattern the way IAM roles are, so those grants land on `*` and IAM
cannot express "not the runner's own network". The runner instance is reachable ONLY by SSM — no key
pair, no public ingress — so a `DeleteRoute` or `DeleteSubnet` aimed at the runner's own VPC would
sever the one channel that can run or clean up anything, including the failing script's own teardown.

The bound therefore lives in `12_vpc_egress_image_pull.py`, which means it is code, which means it
can regress silently. These tests are the thing that stops that. They are not about whether F5-7b
gets the right verdict; they are about whether a wrong F5-7b can take the testbed with it.

The second half of the file is about the verdict, and specifically about the two ways this case
would publish a confident falsehood:

* the oracle's FALSE is a positive claim about somebody else's product ("egress is reachable either
  way"), and `not TRUE` is the same boolean as `FALSE` while being a different claim. Two of the
  four possible arm pairs are neither verdict, and a bare `observed = (a and b)` would publish FALSE
  for both. F1-15 published exactly that error for 24 minutes.
* the diagnostic measured READY arriving at the FIRST poll, which suggests the image may not be
  fetched by the time the create settles. A scorer that read only the create channel could watch the
  no-route arm reach READY and call it "egress reachable", on no evidence about the fetch at all.

Nothing here makes an AWS call: `capture` is replaced wholesale where it is reached, and the guard
and scoring functions are pure.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

SCRIPT = ROOT / "f5_redteam" / "12_vpc_egress_image_pull.py"
_spec = importlib.util.spec_from_file_location("grx_f5_12_vpc_egress_image_pull", SCRIPT)
M = importlib.util.module_from_spec(_spec)
sys.modules["grx_f5_12_vpc_egress_image_pull"] = M
_spec.loader.exec_module(M)

import oracle as O      # noqa: E402

SRC = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(SRC)

# Every EC2 operation in this script that destroys or detaches something. Enumerated here rather
# than pattern-matched on "delete", because `disassociate_route_table`, `detach_internet_gateway`
# and `release_address` are all destructive and none of them contains the word.
DESTRUCTIVE_EC2 = {
    "delete_vpc", "delete_subnet", "delete_security_group", "delete_internet_gateway",
    "detach_internet_gateway", "delete_nat_gateway", "release_address", "delete_route_table",
    "disassociate_route_table", "delete_route", "delete_network_interface",
}


# ---------------------------------------------------------------------------- guard 1: deny-list
#
# The deny-list is RESOLVED AT RUNTIME from the runner's security-group name, so there are no ids to
# read off the source. That splits these tests in two: what `resolve_forbidden` builds from a given
# control-plane answer, and what `guard` does with the result. Both halves matter — an earlier draft
# hard-coded three ids, which made the guard untestable against staleness and, worse, meant a rebuilt
# runner would leave `guard()` passing on everything while protecting nothing.

# Deliberately not the runner's real ids: these tests must not need them, and a test file is the
# last place to write down the thing the script was just changed to stop writing down.
FAKE_RUNNER = {
    "vpc": "vpc-0runnerfake0000",
    "subnets": ["subnet-0runnerfakeaaa", "subnet-0runnerfakebbb"],
    "sgs": ["sg-0runnerfake111", "sg-0runnerfake222"],
}


class _Rec:
    """The two members of `Record` that `resolve_forbidden` touches."""

    def __init__(self, response):
        self.response = response

    def raise_for_status(self):
        return self


def _fake_capture(sg_groups=None, subnets=None, vpc_groups=None):
    """A `capture` that answers the three describes by which filter it was handed."""
    def cap(store, op, client, **params):
        name = params.get("Filters", [{}])[0].get("Name")
        if op == "describe_subnets":
            return _Rec({"Subnets": [{"SubnetId": s} for s in (subnets or [])]})
        if name == "group-name":
            return _Rec({"SecurityGroups": sg_groups if sg_groups is not None
                         else [{"GroupId": FAKE_RUNNER["sgs"][0], "VpcId": FAKE_RUNNER["vpc"]}]})
        return _Rec({"SecurityGroups": [{"GroupId": g} for g in (vpc_groups or [])]})
    return cap


@pytest.fixture
def resolved(monkeypatch):
    """Run `resolve_forbidden` against the fake control plane and yield the resulting set."""
    monkeypatch.setattr(M, "capture", _fake_capture(
        subnets=FAKE_RUNNER["subnets"], vpc_groups=FAKE_RUNNER["sgs"]))
    monkeypatch.setattr(M, "FORBIDDEN_IDS", frozenset())
    got = M.resolve_forbidden(object(), object())
    yield got
    monkeypatch.setattr(M, "FORBIDDEN_IDS", frozenset())


def test_the_deny_list_is_the_runners_vpc_and_all_of_its_subnets_and_groups(resolved):
    """Every subnet and every security group in the runner's VPC, not just the attached ones.

    This is the property the hard-coded version could not have: it named the one subnet and one SG
    that happened to be attached on the day it was written.
    """
    assert resolved == frozenset(
        [FAKE_RUNNER["vpc"], *FAKE_RUNNER["subnets"], *FAKE_RUNNER["sgs"]])
    kinds = sorted({i.split("-")[0] for i in resolved})
    assert kinds == ["sg", "subnet", "vpc"], sorted(resolved)


@pytest.mark.parametrize("bad", [FAKE_RUNNER["vpc"], *FAKE_RUNNER["subnets"],
                                 *FAKE_RUNNER["sgs"]])
def test_the_guard_refuses_every_id_belonging_to_the_runner(resolved, bad):
    """One test per id, so a partially-emptied deny-list fails specifically."""
    with pytest.raises(M.GuardTripped) as e:
        M.guard(bad)
    assert bad in str(e.value)
    assert "SSM" in str(e.value), (
        "the refusal must say WHY, because the next person to read it will be deciding whether to "
        "delete the check")


def test_an_unresolved_deny_list_refuses_everything_rather_than_allowing_it():
    """The failure mode that matters most. If `resolve_forbidden` never ran — an import-time use, a
    reordered `main`, a caught exception — the set is empty, and an empty deny-list must not read as
    "nothing is forbidden". `guard` has to fail closed."""
    assert M.FORBIDDEN_IDS == frozenset(), (
        "the module-level deny-list must start EMPTY; a populated default would be the hard-coded "
        "list again, wearing a different name")
    with pytest.raises(M.GuardTripped) as e:
        M.guard("vpc-0abc123")
    assert "empty" in str(e.value).lower()


@pytest.mark.parametrize("groups,why", [
    ([], "no security group by that name"),
    ([{"GroupId": "sg-0x", "VpcId": ""}], "found but reports no VpcId"),
])
def test_resolve_forbidden_raises_when_it_cannot_determine_the_runners_network(
        monkeypatch, groups, why):
    """An unresolvable deny-list stops the run; it never opens it. This runs before the first
    create, so raising here leaks nothing."""
    monkeypatch.setattr(M, "capture", _fake_capture(sg_groups=groups))
    monkeypatch.setattr(M, "FORBIDDEN_IDS", frozenset())
    with pytest.raises(M.GuardTripped):
        M.resolve_forbidden(object(), object())
    assert M.FORBIDDEN_IDS == frozenset(), f"{why}: the set must not be left half-built"


def test_resolve_forbidden_only_describes(monkeypatch):
    """It runs before anything exists, so it must not mutate. Any operation it names that is not a
    describe would be a mutation on the runner's own network, which is the exact thing being
    guarded against."""
    fn = next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == "resolve_forbidden")
    ops = [n.args[1].value for n in ast.walk(fn)
           if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "capture"
           and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)]
    assert ops, "the scan found no capture() calls — it no longer models the function"
    assert all(o.startswith("describe_") for o in ops), ops


def test_the_deny_list_is_resolved_before_the_first_create():
    """Ordering, by AST. `resolve_forbidden` must be called above every create in `main`, because a
    create that precedes it is a resource the teardown would have to guard without a deny-list."""
    main = next(n for n in ast.walk(TREE)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [(n.lineno, getattr(n.func, "id", "")) for n in ast.walk(main)
             if isinstance(n, ast.Call)]
    resolve_at = min(ln for ln, name in calls if name == "resolve_forbidden")
    build_at = min(ln for ln, name in calls if name == "build_network")
    assert resolve_at < build_at, (
        f"resolve_forbidden at line {resolve_at} must precede build_network at {build_at}")


def test_the_guard_aborts_rather_than_returning_false():
    """`guard` must RAISE. A predicate that returned False would be a check the caller can ignore,
    and every caller here is one line above a destructive API call."""
    src = ast.get_source_segment(SRC, next(
        n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == "guard"))
    assert "raise" in src
    assert "return False" not in src


def test_the_guard_refuses_an_empty_id(resolved):
    """The likelier failure in practice: a `.get()` on a ledger entry that was never completed
    yields `""`, and a destructive call assembled from partly-empty bookkeeping is not a call worth
    making.

    Takes `resolved` so the refusal is attributable to the empty ID and not to an empty deny-list —
    the two raise the same exception type, and without a populated list this would pass for the
    wrong reason.
    """
    with pytest.raises(M.GuardTripped) as e:
        M.guard("")
    assert "empty resource id" in str(e.value)
    with pytest.raises(M.GuardTripped):
        M.guard("vpc-0f57bown", "")


def test_the_guard_passes_this_runs_own_ids(resolved):
    """The other direction. A guard that refused everything would be green here and useless live —
    feedback_zero_file_scan_is_error applied to a predicate."""
    M.guard("vpc-0abc123", "subnet-0def456", "sg-0aaa111", "eipalloc-0bbb222")


def test_every_destructive_ec2_call_site_is_inside_a_function_that_guards():
    """The coverage property, checked by AST rather than by reading.

    Stated as "the enclosing function calls `guard`" rather than "a guard appears on the preceding
    line", because the deletes go through a helper and a line-adjacency rule would go red on an
    unrelated edit — a tripwire that goes red on an unrelated edit is a tripwire someone deletes.
    """
    funcs = [n for n in ast.walk(TREE)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    unguarded = []
    for fn in funcs:
        ops = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "capture"
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)):
                if node.args[1].value in DESTRUCTIVE_EC2:
                    ops.add(node.args[1].value)
        if not ops:
            continue
        guards = any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "guard"
                     for n in ast.walk(fn))
        if not guards:
            unguarded.append((fn.name, sorted(ops)))
    assert not unguarded, (
        f"these functions make a destructive EC2 call and never call guard(): {unguarded}")


def _destructive_op_literals() -> set[str]:
    """Every destructive EC2 operation this script names, on either of the two paths it can take.

    Most of them do NOT appear as an argument to `capture`: they are passed to `teardown._del`,
    which is the single choke point that applies both guards, and `_del` then calls
    `capture(store, op, client, **params)` with `op` as a variable. A scan that looked only at
    `capture` therefore found three of eleven and read as "almost nothing is destructive here" —
    which is how a scan that is broken in the safe-looking direction goes unnoticed.
    """
    found: set[str] = set()
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        fname = getattr(node.func, "id", "")
        # capture(store, "<op>", client, ...) — the direct sites
        if fname == "capture" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            if node.args[1].value in DESTRUCTIVE_EC2:
                found.add(node.args[1].value)
        # _del(kind, logical, "<op>", client, ...) — the choke point
        if fname == "_del" and len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
            if node.args[2].value in DESTRUCTIVE_EC2:
                found.add(node.args[2].value)
    return found


def test_the_scan_for_destructive_call_sites_finds_something():
    """feedback_zero_file_scan_is_error. A scan that matched nothing — a renamed `capture`, a
    reshuffled argument order — would make the assertion above pass while checking nothing."""
    found = _destructive_op_literals()
    assert len(found) >= 8, f"only found {sorted(found)} — the scan is broken"


def test_every_destructive_operation_the_script_names_is_reachable_only_through_a_guard():
    """The two paths, stated together.

    Either an operation goes through `_del` — which reads the ledger and calls `guard` — or it is a
    direct `capture` inside a function that calls `guard`. Anything else is an ungated destructive
    call, and this is the assertion that would catch one added later.
    """
    direct = {n.args[1].value for n in ast.walk(TREE)
              if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "capture"
              and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
              and n.args[1].value in DESTRUCTIVE_EC2}
    via_del = {n.args[2].value for n in ast.walk(TREE)
               if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_del"
               and len(n.args) >= 3 and isinstance(n.args[2], ast.Constant)
               and n.args[2].value in DESTRUCTIVE_EC2}
    # The three direct sites, each for a stated reason: the mutation's own inverse (measured, not
    # torn down), the IGW detach (needs two ids from one ledger entry), and the leftover ENIs
    # (which have no ledger entry at all).
    assert direct == {"delete_route", "detach_internet_gateway", "delete_network_interface"}, (
        f"a new direct destructive call site appeared: {sorted(direct - via_del)}. Route it through "
        f"_del, or state here why it cannot be.")
    assert _destructive_op_literals() == direct | via_del


# ---------------------------------------------------------------------------- guard 2: ledger ids

def test_the_generic_delete_helper_reads_the_ledger_and_never_a_describe():
    """Guard 2, at its single choke point.

    Every network delete goes through `teardown._del`, which must take its parameters from the
    ledger entry it was asked for. A `describe_*` filter that matched one id too widely would delete
    somebody else's subnet, and the tag it filtered on would be the reason it looked correct.
    """
    td = next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == "teardown")
    dl = next(n for n in ast.walk(td) if isinstance(n, ast.FunctionDef) and n.name == "_del")
    src = ast.get_source_segment(SRC, dl)
    assert "state.find(" in src, "_del must address the resource through the ledger"
    assert "entry.delete_params" in src, "_del must take its parameters from the ledger entry"
    assert "describe" not in src, (
        "_del must not consult a describe: the id it deletes has to come from what this run "
        "recorded, not from what the account currently contains")
    assert "guard(" in src


def test_the_one_describe_derived_delete_is_double_checked_against_this_runs_own_ids():
    """The single exception, and the reason it is allowed.

    Leftover ENIs have no ledger entry — the service creates them — so their ids can only come from
    a describe. That call site therefore re-checks SubnetId AND VpcId against this run's own values
    before deleting anything, and raises on a mismatch rather than skipping the row.
    """
    td = next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == "teardown")
    src = ast.get_source_segment(SRC, td)
    i = src.index("delete_network_interface")
    window = src[max(0, i - 1400):i]
    assert 'eni.get("SubnetId") != net["subnet_private"]' in window
    assert 'eni.get("VpcId") != net["vpc_id"]' in window
    assert "GuardTripped" in window, (
        "a mismatched row must abort, not be skipped: it means the describe returned something "
        "this run does not own, and the next row is no more trustworthy than that one")


def test_the_nat_gateway_is_ledgered_before_it_is_created():
    """The one resource here that bills hourly, and the window that would leak it.

    `build_network.step` records the ledger entry, creates, then RE-records with the real id.
    Asserted on the order of the statements rather than on their presence, because both orders
    contain both calls.
    """
    bn = next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == "build_network")
    step = next(n for n in ast.walk(bn) if isinstance(n, ast.FunctionDef) and n.name == "step")
    records = [n.lineno for n in ast.walk(step)
               if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "record"]
    creates = [n.lineno for n in ast.walk(step)
               if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "capture"]
    assert records and creates
    assert min(records) < min(creates), (
        "the ledger entry must be written BEFORE the create: the window between a successful "
        "create and a recorded create is the window in which a kill leaves a NAT gateway nobody "
        "knows about, at $0.045/h")
    assert max(records) > max(creates), (
        "and re-written after, or the entry carries no id and teardown cannot address it")


def test_the_delete_priorities_encode_the_documented_teardown_order():
    """`runner/teardown.py` replays the ledger by `delete_priority`, so if this script is killed the
    order it gets is whatever these numbers say. They must match the docstring's order, because that
    order is not a preference: an ENI pins a subnet, an attached EIP cannot be released, an
    associated route table cannot be deleted, and an IGW must be detached first.
    """
    # Keyed on `kind`, which is a string constant at every site, and matched EXACTLY. Two earlier
    # drafts keyed on `logical` and both were wrong in ways worth recording, because each failed in
    # the direction that looks like a script problem rather than a test problem:
    #   * substring matching put `f57b_runtime_exec` — the IAM ROLE — into the "runtime" bucket,
    #     so the role's own priority was never checked and "runtime" silently held two values;
    #   * the subnets and route tables are created in a `for` loop, so their `logical` reaches
    #     `step()` as a variable and no literal was there to match at all.
    want = ["agent-runtime", "iam-role", "ec2-route", "ec2-rtb-assoc", "ec2-rtb", "ec2-natgw",
            "ec2-eip", "ec2-igw", "ec2-sg", "ec2-subnet", "ec2-vpc"]
    got: dict[str, set[int]] = {}

    def note(kind, prio) -> None:
        if not (isinstance(kind, ast.Constant) and isinstance(kind.value, str)):
            return
        if not (isinstance(prio, ast.Constant) and isinstance(prio.value, int)):
            return
        if kind.value in want:
            got.setdefault(kind.value, set()).add(prio.value)

    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        # Direct T.Resource(...): the runtime, the role, the mutation route, the route-table
        # associations and the IGW's re-record after it is attached.
        if getattr(node.func, "attr", "") == "Resource":
            kw = {k.arg: k.value for k in node.keywords}
            note(kw.get("kind"), kw.get("delete_priority"))
        # build_network.step(kind, logical, name, delete_op, id_key, priority, ...): the VPC,
        # subnets, SG, IGW, EIP, NAT gateway and route tables, whose priority reaches T.Resource
        # as a variable.
        if getattr(node.func, "id", "") == "step" and len(node.args) >= 6:
            note(node.args[0], node.args[5])

    missing = [t for t in want if t not in got]
    assert not missing, f"no ledger entry found for {missing}; the scan or the script changed"
    for kind, prios in got.items():
        assert len(prios) == 1, (
            f"{kind} is ledgered with more than one delete_priority ({sorted(prios)}); teardown "
            f"would interleave two resources of the same kind at different points")
    ordered = [(t, min(got[t])) for t in want]
    assert ordered == sorted(ordered, key=lambda p: p[1]), (
        f"delete_priority does not increase in the documented teardown order: {ordered}")


# ---------------------------------------------------------------------------- the decision table

def _arm(**kw) -> dict:
    # The default invoke describes a response that ARRIVED and was refused: it carries an
    # `error_code`, which exists only because the service answered. So it must also carry an
    # `http_status` and a `request_id` — and it did not, which made the default fixture describe an
    # IMPOSSIBLE state: a classified step label with no HTTP response behind it. `pull_evidence`'s
    # no-response guard rejected exactly that the moment it was added, and it was right to. A
    # fixture that cannot occur in the field pins no real behaviour. Tests that want the genuinely
    # silent case say so explicitly, via `_no_response` below.
    base = {"created": True, "terminal_status": "READY", "failure_reason": "",
            "step_label": "no_reason_given", "step_why": "",
            "invoke": {"ok": False, "error_code": "RuntimeClientError", "http_status": 424,
                       "request_id": "11111111-2222-3333-4444-555555555555",
                       "error_message": "", "step_label": "unclassified", "step_why": ""}}
    inv = kw.pop("invoke", None)
    base.update(kw)
    if inv is not None:
        base["invoke"] = {**base["invoke"], **inv}
    return base


def _no_response(**inv) -> dict:
    """An arm whose invoke never got an HTTP response — the shape all three live arms produced.

    Measured 2026-08-14: `http_status` None, no request id, no error code, ~70 s of waiting. Kept as
    a named helper because the point is the ABSENCE of three fields together, and spelling that out
    at each call site invites one of them being left in by accident.
    """
    return _arm(invoke={"ok": False, "error_code": "", "http_status": None, "request_id": "",
                        "duration_ms": 70077.3, **inv})


@pytest.mark.parametrize("arm,expect", [
    # channel 1 — the create settled and named the step itself
    (_arm(terminal_status="CREATE_FAILED", failure_reason="failed to pull image",
          step_label="pull"), "pull_failed"),
    (_arm(terminal_status="CREATE_FAILED", failure_reason="container did not respond on 8080",
          step_label="post_pull"), "pull_succeeded"),
    (_arm(terminal_status="CREATE_FAILED", failure_reason="something else entirely",
          step_label="unclassified"), "ambiguous"),
    # channel 2 — READY, so the fetch is only observable at invoke
    (_arm(invoke={"ok": True, "body": "hello"}), "pull_succeeded"),
    (_arm(invoke={"step_label": "post_pull"}), "pull_succeeded"),
    (_arm(invoke={"step_label": "pull"}), "pull_failed"),
    (_arm(invoke={"step_label": "unclassified"}), "ambiguous"),
    (_arm(invoke={"step_label": "no_reason_given"}), "ambiguous"),
    # the create never happened, or never settled
    ({"created": False, "create_refused": True, "error_code": "ValidationException",
      "error_message": "nope"}, "ambiguous"),
    (_arm(terminal_status=""), "ambiguous"),
    # no HTTP response at all — the live shape. Ambiguous however the message reads, INCLUDING when
    # it reads like a pull failure, and including when the create failed rather than reaching READY.
    (_no_response(), "ambiguous"),
    (_no_response(error_message='Read timeout on endpoint URL: "https://bedrock-agentcore..."'),
     "ambiguous"),
    (_no_response(error_message="connection timed out while pulling image manifest"), "ambiguous"),
])
def test_pull_evidence_reads_whichever_channel_located_the_fetch(arm, expect):
    label, why = M.pull_evidence(arm)
    assert label == expect, why
    assert why, "every label must carry the sentence that justifies it — a verdict here is one word"


@pytest.mark.parametrize("message", [
    'Read timeout on endpoint URL: "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/x"',
    "connection timed out",
    "timed out waiting to pull the image from the registry",
    "network unreachable: could not pull manifest",
])
def test_an_invoke_that_never_got_a_response_cannot_name_the_fetch_whatever_it_says(message):
    """The defect that produced the first live run's wrong labels, pinned at the general form.

    All three arms of 2026-08-14 hung with `http_status` None and were labelled `pull_failed`,
    because `PULL_MARKERS` contained "timeout". The label was almost certainly wrong on the merits:
    the image is `public.ecr.aws/nginx/nginx:stable`, which binds :80 against AgentCore's :8080
    contract, so a SUCCESSFULLY pulled container produces the same silence as an unpulled one.

    The guard is structural — `http_status is None` — precisely so it cannot be defeated by the
    wording. A message written by botocore about an endpoint it gave up on may contain any word,
    and the third and fourth cases here contain the strongest pull words there are.
    """
    label, why = M.pull_evidence(_no_response(error_message=message))
    assert label == "ambiguous", f"{message!r} was read as {label!r}: {why}"
    assert "never received an HTTP response" in why


def test_the_pull_markers_do_not_contain_a_word_a_client_side_timeout_can_match():
    """`timeout`/`timed out` are gone from PULL_MARKERS, and this is why.

    They were legitimate while the marker lists only ever read a SERVICE-supplied `failureReason`.
    They stopped being legitimate when the same lists were pointed at a client-side error. The
    structural guard above is the real fix; this keeps the words from drifting back in and quietly
    re-labelling any future arm that does get a partial response.
    """
    for word in ("timeout", "timed out"):
        assert word not in M.PULL_MARKERS, (
            f"{word!r} is back in PULL_MARKERS. A client-side socket timeout matches it and says "
            f"nothing about any image fetch; see the 70082/70077/70073 ms arms of 2026-08-14.")


def test_a_ready_create_alone_is_never_enough_to_call_the_fetch_successful():
    """The trap the diagnostic named, pinned.

    READY arrived at the FIRST poll for the container the diagnostic measured, so READY may precede
    the fetch. A scorer that treated READY as proof of a pull would let the no-route arm read as
    "egress reachable", which is the oracle's FALSE, on no evidence about the fetch.
    """
    label, why = M.pull_evidence(_arm(invoke={"step_label": "unclassified"}))
    assert label == "ambiguous", why
    assert "does not distinguish" in why


def test_the_invoke_channel_is_measured_on_every_arm_including_failed_creates():
    """Both channels on every arm, or one arm has a channel the other does not and the comparison
    is between different instruments."""
    fn = next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == "runtime_arm")
    src = ast.get_source_segment(SRC, fn)
    assert "invoke_agent_runtime" in src
    body = src[src.index("invoke_agent_runtime"):]
    assert "if status" not in body.split("\n")[0], "the invoke must not be gated on the status"
    # The only early return before the invoke is the synchronous create refusal, where there is no
    # ARN to invoke and therefore no channel to measure.
    before = src[:src.index("invoke_agent_runtime")]
    assert before.count("return out") == 1, (
        f"{before.count('return out')} early returns sit before the invoke; only the "
        f"create-refused branch may, because it has no runtime ARN to call")


# ---------------------------------------------------------------------------- the verdict shapes

def _score(a: str, b: str, c: str, *, restored=True, route_gone=True):
    """Replay main()'s decision on a pair of labels, without AWS.

    The branching is duplicated here deliberately rather than refactored into a shared helper and
    then tested through it: the point is to state the intended table independently, so a change to
    the script's branching shows up as a disagreement rather than as both sides moving together.
    """
    if a == "missing" or b == "missing":
        return "NOT_MEASURED"
    if "ambiguous" in (a, b):
        return "NOT_MEASURED"
    if not (restored and route_gone and c == a):
        return "NOT_MEASURED"
    if (a, b) == ("pull_failed", "pull_succeeded"):
        return "TRUE"
    if (a, b) == ("pull_succeeded", "pull_succeeded"):
        return "FALSE"
    return "NOT_MEASURED"


@pytest.mark.parametrize("a,b,c,expect", [
    ("pull_failed", "pull_succeeded", "pull_failed", "TRUE"),
    ("pull_succeeded", "pull_succeeded", "pull_succeeded", "FALSE"),
    # the two pairs the oracle does not name. Both are `not TRUE`, neither is FALSE.
    ("pull_failed", "pull_failed", "pull_failed", "NOT_MEASURED"),
    ("pull_succeeded", "pull_failed", "pull_succeeded", "NOT_MEASURED"),
    # an ambiguous arm cannot be rounded to either verdict
    ("ambiguous", "pull_succeeded", "ambiguous", "NOT_MEASURED"),
    ("pull_failed", "ambiguous", "pull_failed", "NOT_MEASURED"),
])
def test_only_two_arm_pairs_are_decidable(a, b, c, expect):
    assert _score(a, b, c) == expect


@pytest.mark.parametrize("a,b,c,restored,route_gone", [
    ("pull_failed", "pull_succeeded", "pull_failed", True, True),
    ("pull_succeeded", "pull_succeeded", "pull_succeeded", True, True),
    ("pull_failed", "pull_failed", "pull_failed", True, True),
    ("pull_succeeded", "pull_failed", "pull_succeeded", True, True),
    ("ambiguous", "ambiguous", "ambiguous", True, True),
    ("ambiguous", "pull_succeeded", "ambiguous", True, True),
    ("pull_failed", "ambiguous", "pull_failed", True, True),
    ("missing", "pull_succeeded", "missing", True, True),
    ("pull_failed", "pull_succeeded", "pull_failed", False, True),
    ("pull_failed", "pull_succeeded", "pull_failed", True, False),
    ("pull_failed", "pull_succeeded", "pull_succeeded", True, True),
])
def test_decide_agrees_with_the_independently_stated_table(monkeypatch, a, b, c, restored,
                                                           route_gone):
    """`_score` above states the intended table; `M.decide` is the code that ships. Assert they
    agree on every row, including the rows `_score`'s own parametrisation does not carry.

    This test is the reason `_score` is allowed to stay a duplicate. Before 2026-08-14 the branch
    table was inline in `main()` and unreachable without AWS, so `_score` was the only executable
    statement of it and nothing checked the two against each other — a divergence would have shown
    up only in a live run's output. `decide()` is pure, so now it can be driven directly.

    `pull_evidence` is monkeypatched rather than driven through crafted arm dicts on purpose: the
    mapping from arm dict to LABEL is what the decision-table tests above cover, and the mapping
    from label to VERDICT is what this one covers. Feeding real arms here would test both at once
    and localise a failure to neither.
    """
    labels = {M.ARM_NO_ROUTE: a, M.ARM_WITH_ROUTE: b, M.ARM_RESTORED: c}
    monkeypatch.setattr(M, "pull_evidence", lambda arm: (labels[arm["which"]], "why"))

    arms = {name: {"which": name} for name in labels}
    scored = M.decide(arms, {"default_route_gone": route_gone}, mutation_restored=restored)

    want = _score(a, b, c, restored=restored, route_gone=route_gone)
    got = scored["record"]["verdict"]
    assert got == ("INCONCLUSIVE" if want == "NOT_MEASURED" else want), (
        f"decide() and _score() disagree on ({a}, {b}, {c}, restored={restored}, "
        f"route_gone={route_gone}): decide said {got}, the stated table says {want}")


def test_decide_touches_no_aws_and_no_clock():
    """`decide()` is called by the rederive path with no credentials and no `state` object. If it
    ever grows a client call or a timestamp, that path breaks — and it breaks by writing a result
    file, which is the worst place to discover it."""
    fn = next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == "decide")
    # Identifiers actually referenced, not a substring scan of `ast.dump` — the docstring explains
    # the fix in prose and the words "client-side" and "time" appear in it. A prose mention is not
    # a call, and a test that cannot tell the difference fails on its own documentation.
    used = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    used |= {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    for forbidden in ("factory", "client", "utcnow", "now", "sleep", "capture", "write_text",
                      "monotonic", "State", "EvidenceStore"):
        assert forbidden not in used, (
            f"decide() references {forbidden!r}; it must stay pure, because the rederive path "
            f"calls it with no credentials, no `state` and no evidence store")


def test_the_script_refuses_the_pairs_the_oracle_does_not_name():
    """The same property against the script's own source, so the table above cannot drift away from
    it silently. A bare `observed = (a == ... and b == ...)` with no preceding filter would send
    `(pull_succeeded, pull_failed)` straight into `O.evaluate` as a published FALSE."""
    # Anchored on `def decide(` rather than on the `# ---- the verdict` comment inside `main()`: the
    # branch table was lifted out of `main()` into that function on 2026-08-14, so that re-scoring
    # archived arms after the instrument fix runs the same code instead of a transcription of it.
    # Slicing the scoring function is also a tighter anchor than "everything after a comment" —
    # this test is about where the guard sits RELATIVE to `O.evaluate`, and both now live in one
    # function, so a slice that starts anywhere else could only weaken it.
    src = SRC[SRC.index("def decide("):]
    assert '("pull_failed", "pull_succeeded")' in src
    assert '("pull_succeeded", "pull_succeeded")' in src
    guard_at = src.index("not in ((\"pull_failed\", \"pull_succeeded\")")
    evaluate_at = src.index("O.evaluate(")
    assert guard_at < evaluate_at, (
        "the filter on decidable pairs must come BEFORE O.evaluate, or the undecidable pairs are "
        "already a FALSE by the time anyone looks")


@pytest.mark.parametrize("restored,route_gone,c", [
    (False, True, "pull_failed"),
    (True, False, "pull_failed"),
    (True, True, "pull_succeeded"),   # the restore returned 200 and did not restore
])
def test_an_unverified_restore_blocks_the_verdict(restored, route_gone, c):
    """PREREGISTRATION.yaml's `restore_verification` names F5-7b: "After every mutation: restore,
    then RE-RUN the blocking assertion. A restore is not assumed to have worked because the API call
    returned 200." So all three of these must block — including the last, where DeleteRoute
    succeeded and the route table read back clean and the re-run arm still behaved as though the
    route were there."""
    assert _score("pull_failed", "pull_succeeded", c,
                  restored=restored, route_gone=route_gone) == "NOT_MEASURED"


def test_the_restore_is_verified_by_reading_the_route_table_back():
    """The first half of the rule, which a `DeleteRoute` status code does not satisfy."""
    src = SRC[SRC.index("RESTORE: deleting the route"):]
    assert "describe_route_tables" in src
    assert "default_route_gone" in src
    i = src.index("default_route_gone")
    assert "DestinationCidrBlock" in src[:i + 400]


# ---------------------------------------------------------------------------- seal and safety

def test_the_case_is_still_sealed_with_a_mandatory_mutation():
    """This script implements a mutation arm and reports `mutations: 2`. If the seal ever stopped
    demanding one, the report would be describing a rule the seal no longer names — so the script
    refuses to run, and this test says why in the place someone will read it."""
    assert O.mutation_is_mandatory(M.CASE) is True
    assert O.planned_n(M.CASE) is None, (
        "planned_n is None, which is why n=1 per arm is the pre-registered denominator and not a "
        "shortfall")
    assert "image pull" in O.oracle_text(M.CASE)


def test_the_container_arm_is_used_and_not_the_code_arm():
    """F5-8 could use `codeConfiguration` and this case cannot: a code artifact pulls no image, and
    this oracle is denominated in the pull. Substituting it would be the F1-15 substitution
    defect — a one-word verdict silently answering a different question than the seal asked."""
    assert "containerConfiguration" in SRC
    assert "codeConfiguration" not in SRC.split('"""', 2)[2], (
        "the code artifact must not appear outside the docstring that explains why it is refused")


def test_the_execution_role_is_not_the_one_that_is_f5_1s_published_oracle():
    """`grx-runtime-exec-*` carries an explicit Deny on `iam:PutRolePolicy` in the runner's derived
    policy precisely so this fails at the API. It should also fail at desk."""
    assert "grx-runtime-vpcegress-" in SRC
    assert "grx-runtime-exec-" not in SRC.replace(
        "role/grx-runtime-exec-*", "").replace("`grx-runtime-exec-<run_id>`", "")


def test_the_new_vpc_cannot_collide_with_the_runners_own_addressing():
    """Both subnets must sit inside the VPC, and the VPC must not be in the 172.31/16 space the
    default VPC uses — a collision would not be caught by the id deny-list, because the ids would
    be ours and the addresses would not."""
    assert M.VPC_CIDR.startswith("10.")
    assert M.PUBLIC_CIDR.startswith("10.61.") and M.PRIVATE_CIDR.startswith("10.61.")
    assert M.PUBLIC_CIDR != M.PRIVATE_CIDR


def test_the_two_settle_waits_are_waits_and_not_retry_loops():
    """A retry would let the with-route arm pass on its third attempt and publish "egress works"
    while hiding that it did not work at first — and would swallow a genuine trust-policy error as
    though it were a timing problem, which is the failure mode
    `diag_runtime_code_artifact.py` has a retracted paragraph about."""
    assert M.TRUST_SETTLE_S > 0 and M.ROUTE_SETTLE_S > 0
    src = SRC[SRC.index("THE MUTATION ---"):SRC.index("--- {ARM_WITH_ROUTE}")]
    assert "time.sleep(ROUTE_SETTLE_S)" in src
    assert "while" not in src, "the settle must be a wait, not a poll-until-it-works"
