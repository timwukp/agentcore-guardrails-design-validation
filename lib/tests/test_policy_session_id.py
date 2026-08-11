"""The policy-session-id header grammar, pinned as MEASURED data.

Every case in `MEASURED_ACCEPT` / `MEASURED_REJECT` was executed against the live main gateway
(`grx-gw-r20260810t130945z-zpkfmpwo9n`, us-east-1) on 2026-08-11 via `initialize`, one variable at
a time. These are not guesses about a plausible grammar; they are recorded observations, and the
comment beside each says what it isolates. If AWS widens the grammar later, this file is where the
change surfaces — which is the point of writing observations down as executable data instead of
prose (`feedback_prose_is_not_verified`).

Why it matters that the length ceiling is 128 and not "about 128": it was bisected (128 accepted,
129 rejected), so a future off-by-one in our own id construction is detectable.
"""

from __future__ import annotations

import re

import pytest

import mcp as M

# --------------------------------------------------------------------------
# what the live gateway actually did
# --------------------------------------------------------------------------

MEASURED_ACCEPT = [
    ("alnum_only", "grxa"),                       # baseline
    ("digits", "grx123"),                         # digits legal
    ("upper", "grxAaB"),                          # case is not folded away or rejected
    ("hyphen_interior", "grx-a-b"),               # hyphen legal
    ("hyphen_leading", "-grxa"),                  # ...in leading position too
    ("hyphen_trailing", "grx-a-"),                # ...and trailing
    ("len_128", "a" * 128),                       # the exact ceiling, bisected
    ("smoke_style", "r20260810T130945Z-smoke-main-0"),   # the id infra/08_smoke.py sends
]

MEASURED_REJECT = [
    ("underscore", "grxa_b"),                     # ONE underscore is enough to fail
    ("double_underscore", "enforce__guardrail_only__benign"),   # F4's cell key, the original bug
    ("dot", "grx.a.b"),
    ("colon", "grx:a:b"),
    ("tilde", "grx~a"),
    ("plus", "grx+a"),
    ("percent_encoded_underscore", "grx%5Fa"),    # %-encoding does NOT rescue a bad char
    ("percent_encoded_space", "grx%20a"),
    ("len_129", "a" * 129),                       # one past the bisected ceiling
    ("empty", ""),
]


@pytest.mark.parametrize("label,value", MEASURED_ACCEPT, ids=[c[0] for c in MEASURED_ACCEPT])
def test_measured_accepts_pass_the_guard(label, value):
    """A value the gateway accepted must not be blocked by our own guard.

    A guard that rejects legal ids would be worse than no guard: it would convert a working arm
    into a harness error and look like a service problem.
    """
    M.check_policy_session_id(value)
    assert re.match(M.POLICY_SESSION_GRAMMAR, value)


@pytest.mark.parametrize("label,value", MEASURED_REJECT, ids=[c[0] for c in MEASURED_REJECT])
def test_measured_rejects_fail_the_guard(label, value):
    with pytest.raises(M.McpTransportError) as exc:
        M.check_policy_session_id(value)
    # The message has to name the header, or it reproduces the very confusion it exists to end.
    assert "policy session id" in str(exc.value)
    assert M.POLICY_SESSION_GRAMMAR in str(exc.value)


@pytest.mark.parametrize("label,value", MEASURED_REJECT, ids=[c[0] for c in MEASURED_REJECT])
def test_normalize_repairs_every_measured_reject(label, value):
    """Normalization must produce something the gateway would accept, for every bad input."""
    if value == "":
        pytest.skip("an empty arm name is a caller bug, not something to silently invent an id for")
    out = M.normalize_policy_session_id(value)
    M.check_policy_session_id(out)
    assert len(out) <= M.POLICY_SESSION_MAX_LEN


def test_normalize_is_identity_on_legal_values():
    """Ids already legal must come back byte-identical.

    This is what keeps the fix from invalidating `evidence/` records written before it: the smoke
    run's ids contained no illegal character, so they must not acquire a hash suffix now.
    """
    for _, value in MEASURED_ACCEPT:
        assert M.normalize_policy_session_id(value) == value


def test_normalization_is_injective_on_colliding_arms():
    """`a_b` and `a-b` must not become the same session id.

    Character-mapping alone is not injective, and a collision here does not fail loudly: both arms
    return 200 while sharing one temporal-policy session, so their trials are silently no longer
    independent. This is the single defect the hash suffix exists to prevent, so it is tested
    directly rather than assumed from the implementation.
    """
    a = M.policy_session_id("r1", "enforce_guardrail_only_benign")
    b = M.policy_session_id("r1", "enforce-guardrail-only-benign")
    assert a != b
    M.check_policy_session_id(a)
    M.check_policy_session_id(b)


def test_injective_over_the_real_f4_cell_keys():
    """The 8 F4 cells, which is where the original bug actually bit."""
    modes = ("enforce", "log_only")
    subjects = ("guardrail_only", "policy_only")
    corpora = ("benign", "attack")
    keys = [f"{m}__{s}__{c}" for m in modes for s in subjects for c in corpora]
    ids = [M.policy_session_id("r20260810T130945Z", k) for k in keys]
    assert len(set(ids)) == len(keys), "two F4 cells would share one temporal session"
    for i in ids:
        M.check_policy_session_id(i)


def test_over_long_arm_is_truncated_and_still_distinct():
    """A 300-char arm name must not silently produce a 129+ id, and two of them must differ."""
    long_a = "x" * 300
    long_b = "x" * 299 + "y"
    ia = M.policy_session_id("r20260810T130945Z", long_a)
    ib = M.policy_session_id("r20260810T130945Z", long_b)
    for i in (ia, ib):
        M.check_policy_session_id(i)
        assert len(i) <= M.POLICY_SESSION_MAX_LEN
    assert ia != ib, "truncation alone loses the difference; the hash must carry it"


def test_client_constructor_refuses_a_bad_id_before_any_aws_call(monkeypatch):
    """The guard must fire in `__init__`, not on first POST.

    If it fired on the first request, a bad id would already have consumed a trial index and been
    recorded as an attempt, and the arm's n would be wrong by one in a way nothing else notices.
    """
    class _Creds:
        def get_frozen_credentials(self):
            raise AssertionError("signing must never be reached with an illegal session id")

    with pytest.raises(M.McpTransportError):
        M.McpClient("https://example.amazonaws.com/mcp", "us-east-1", _Creds(),
                    policy_session_id="bad_id_with_underscore")


def test_guard_can_fail_mutation():
    """Mutation check: the assertions above must be capable of failing.

    Per `feedback_vacuous_test_check`. If `POLICY_SESSION_ALLOWED` were widened to match nothing,
    every reject case would pass the guard, and `test_measured_rejects_fail_the_guard` would be
    vacuous. Here that mutation is applied and the guard is required to go silent — proving the
    test above is load-bearing on the real pattern.
    """
    original = M.POLICY_SESSION_ALLOWED
    try:
        M.POLICY_SESSION_ALLOWED = re.compile(r"[^\s\S]")      # matches nothing
        M.check_policy_session_id("grxa_b")                     # would raise with the real pattern
    finally:
        M.POLICY_SESSION_ALLOWED = original
    with pytest.raises(M.McpTransportError):
        M.check_policy_session_id("grxa_b")
