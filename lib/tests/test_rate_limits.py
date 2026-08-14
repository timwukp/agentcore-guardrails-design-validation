"""Every `lim.wait("X")` in the repository names an operation the limiter actually paces.

`RateLimiter.wait` returns 0.0 for any operation absent from `RATE_LIMITS`. That is a reasonable
default in isolation and a trap in aggregate: `lim.wait("Converse")` reads, at every call site and in
every review, as "this call is paced", while doing nothing whatsoever.

The hazard is not hypothetical and it is not new. `lib/awsclients.py` documents it twice, in the past
tense, for `CreateGuardrail` and for `InvokeGateway` — "a guard that cannot run must not report
clean". A repo-wide cross-check on 2026-08-13 found it had happened again in the meantime: 14 of the
29 distinct names passed to `wait()` were missing, across ten production scripts, including
`PutEnforcedGuardrailConfiguration` — the single most consequential call in the project, since it
changes account-level state in an account carrying ~$27k/mo of other workloads.

Two comments recording a lesson did not stop the lesson repeating. This file is the difference: a
name added to a `wait()` call and not to `RATE_LIMITS` is now a red test at desk.

The escape hatch is `DELIBERATELY_UNPACED` — a name may be excluded, but only in writing and only
with a reason, the same rule `RUNNER_EXTRAS` follows.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import awsclients as A          # noqa: E402

# Operations that may appear in a `wait()` call with no rate, each with the reason. Empty on purpose:
# every name found on 2026-08-13 was given a real limit instead, because "this one does not need
# pacing" was not true of any of them. Kept so the next case has somewhere to put a justified
# exception rather than a motive to delete this file.
DELIBERATELY_UNPACED: dict[str, str] = {}

# Files whose `wait()` calls may pass a non-literal, with the reason — the same
# reason-or-nothing rule as `DELIBERATELY_UNPACED`, applied to the scan's own soundness rather
# than to pacing. The one entry is a test OF the limiter, not a call this file protects.
#
# `test_rate_limits.py` is deliberately NOT here. The rule below used to exempt it by name, on the
# reasoning that this file's own arms exercise the limiter with computed names — they do not: they
# feed the scanner assembled SOURCE STRINGS and never call `wait()` at all, so the exemption was a
# waiver for a call that does not exist. The staleness arm below is what said so.
COMPUTED_NAME_ALLOWED: dict[str, str] = {
    "test_awsclients.py":
        "`UNPACED_SENTINEL` is a module constant naming an operation that is deliberately absent "
        "from RATE_LIMITS, so the 'an unlimited operation records no wait' arm keeps its meaning "
        "on the day the operation it used to name is given a rate",
}

# The scan is AST-based, not textual, and both halves of that mattered when this file was written.
# A regex for `.wait(` matched `threading.Event.wait`, botocore's waiters, `runner/teardown.py`'s
# `waiter.wait(InstanceIds=...)` and every vendored copy of urllib3 under `.venv-oracle/` — and it
# matched the sentence "Every other script in this repo calls `lim.wait(op)`" inside
# `f9_failsecure/01_throttle_burst.py`'s docstring, reporting the repo's own prose as a
# dynamically-computed operation name. Parsing sees calls; a regex sees characters that look like
# calls, and here the difference was four false findings and one imaginary one.
_LIMITER_RECEIVERS = {"lim", "_LIMITER", "limiter", "self.lim", "self._lim",
                      "A.limiter()", "awsclients.limiter()", "limiter()"}


def _py_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.py")
            if not any(part.startswith(".venv") for part in p.parts)
            and "__pycache__" not in p.parts
            and "site-packages" not in p.parts]


def _limiter_wait_calls() -> list[tuple[Path, ast.Call]]:
    """Every `<limiter>.wait(...)` call in the repo's own source, as (file, node) pairs."""
    out = []
    for path in _py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "wait"
                    and ast.unparse(node.func.value) in _LIMITER_RECEIVERS):
                out.append((path, node))
    return out


def _wait_sites() -> dict[str, list[Path]]:
    sites: dict[str, list[Path]] = {}
    for path, node in _limiter_wait_calls():
        if node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            sites.setdefault(node.args[0].value, []).append(path)
    return sites


def test_the_scan_finds_a_non_trivial_number_of_call_sites():
    """feedback_zero_file_scan_is_error: a regex that silently matched nothing would make every
    assertion below pass while checking nothing at all."""
    sites = _wait_sites()
    assert len(sites) >= 20, f"only {len(sites)} distinct wait() names found — the scan is broken"
    assert len(_py_files()) >= 150, f"only {len(_py_files())} .py files walked"


def test_every_waited_operation_has_a_rate_or_a_written_reason():
    """The property this file exists for."""
    sites = _wait_sites()
    unpaced = {name: paths for name, paths in sites.items()
               if name not in A.RATE_LIMITS and name not in DELIBERATELY_UNPACED}
    assert not unpaced, (
        "these operations are passed to lim.wait() but have no entry in RATE_LIMITS, so wait() "
        "returns 0.0 and the call is not paced at all:\n"
        + "\n".join(f"  {n}: {', '.join(str(p.relative_to(ROOT)) for p in sorted(set(ps)))}"
                    for n, ps in sorted(unpaced.items()))
        + "\nAdd a rate, or add the name to DELIBERATELY_UNPACED with the reason it needs none.")


def test_every_deliberate_exclusion_carries_a_reason_and_is_actually_used():
    """Both directions. A reason-less exclusion is unreviewable; an exclusion for a name nothing
    waits on is dead text that makes the list look more considered than it is."""
    assert all(isinstance(v, str) and len(v) > 20 for v in DELIBERATELY_UNPACED.values()), \
        [k for k, v in DELIBERATELY_UNPACED.items() if not (isinstance(v, str) and len(v) > 20)]
    sites = _wait_sites()
    stale = sorted(n for n in DELIBERATELY_UNPACED if n not in sites)
    assert not stale, f"excluded but never waited on: {stale}"
    both = sorted(n for n in DELIBERATELY_UNPACED if n in A.RATE_LIMITS)
    assert not both, f"listed as unpaced AND given a rate: {both}"

    # The same two directions for the computed-name waiver, which is the other place this file
    # can be quietly widened: a reason-less entry is unreviewable, and an entry for a file that no
    # longer passes a computed name is a waiver nobody has to justify because nothing tests it.
    assert all(isinstance(v, str) and len(v) > 20 for v in COMPUTED_NAME_ALLOWED.values()), \
        [k for k, v in COMPUTED_NAME_ALLOWED.items() if not (isinstance(v, str) and len(v) > 20)]
    computed_in = {path.name for path, node in _limiter_wait_calls()
                   if not (node.args and isinstance(node.args[0], ast.Constant)
                           and isinstance(node.args[0].value, str))}
    dead = sorted(set(COMPUTED_NAME_ALLOWED) - computed_in)
    assert not dead, (
        f"these files are exempted from the literal-argument rule but pass no computed name: "
        f"{dead}. Remove the entry rather than leaving a waiver in place for a call that is gone.")


def test_no_call_site_passes_a_computed_operation_name():
    """A static scan is only sound if the argument is always a literal. `lim.wait(op)` would be
    invisible to this file, so it is banned rather than tolerated — and the ban is asserted, not
    described, because the previous version of this rule was a comment.

    The one exemption is the limiter's own unit test, which is not a pacing site: it exercises
    `wait()` as a subject and needs a name that is NOT in `RATE_LIMITS`. Writing such a name as a
    literal is the landmine version — the 2026-08-13 sweep that gave 14 operations real rates is
    exactly what would turn an arm about "an unlimited operation" into an arm about a paced one.
    Hence a module constant there, and hence a named list here rather than a widened rule.
    """
    offenders = []
    for path, node in _limiter_wait_calls():
        if path.name in COMPUTED_NAME_ALLOWED:
            continue
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            continue
        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: "
                         f"lim.wait({ast.unparse(first) if first else ''})")
    assert not offenders, (
        "lim.wait() must take a string literal so the coverage test above can see it:\n"
        + "\n".join(sorted(offenders)))


def test_every_self_imposed_limit_actually_has_a_limit():
    """`SELF_IMPOSED_LIMITS` is what stops an evidence record citing our caution as a published
    AWS ceiling. A name in it with no rate would be labelling a limit that does not exist."""
    orphans = sorted(n for n in A.SELF_IMPOSED_LIMITS if n not in A.RATE_LIMITS)
    assert not orphans, orphans


def test_the_provenance_of_every_rate_is_declared():
    """Each entry is either ours or AWS's, and `rate_limit_provenance` is what an evidence reader
    uses to tell them apart. The AWS-documented set is asserted by NAME here: it is small, it is
    the half that may appear in a claim about the service, and a new entry silently joining it
    would turn a number we chose into a fact we assert."""
    documented = sorted(n for n in A.RATE_LIMITS if n not in A.SELF_IMPOSED_LIMITS)
    assert documented == sorted([
        "ApplyGuardrail", "InvokeGuardrailChecks",
        "CreatePolicyEngine", "DeletePolicyEngine", "UpdatePolicyEngine",
        "CreatePolicy", "DeletePolicy", "UpdatePolicy",
        "CreateGateway", "UpdateGateway", "DeleteGateway",
        "CreateGatewayTarget", "UpdateGatewayTarget", "DeleteGatewayTarget",
    ]), documented


def test_no_rate_is_zero_or_negative():
    """`wait()` computes `1.0 / rate`, and `if not rate` treats 0.0 as absent — so a 0.0 entry would
    read in this dict as "paced, very slowly" and behave as "not paced at all"."""
    bad = {n: r for n, r in A.RATE_LIMITS.items() if not isinstance(r, (int, float)) or r <= 0}
    assert not bad, bad


def test_the_account_state_changing_calls_are_paced_slowest():
    """Not a style rule. These two change account-level configuration in an account carrying other
    people's workloads; nothing in this repo needs either twice in one second, and a fast rate here
    would be a burst against the one surface where a burst is least acceptable."""
    for name in ("PutEnforcedGuardrailConfiguration", "DeleteEnforcedGuardrailConfiguration"):
        assert A.RATE_LIMITS[name] <= 1.0, (name, A.RATE_LIMITS[name])
