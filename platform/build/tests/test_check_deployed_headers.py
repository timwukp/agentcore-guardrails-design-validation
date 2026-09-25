"""Arms for the check that reads the DEPLOYED headers instead of the source that describes them.

Every arm here runs against a fake reader, and the fake is written so that it CAN LIE -- it will
happily report a policy that does not match the stack, a behaviour pointing at another policy, a
missing `Cache-Control`, or no objects at all. A double that can only return the right answer proves
that the caller compiles, not that the check discriminates (`feedback_unreachable_branch_in_fake`).

The first arm is the no-mutant control. Without it, a suite of twelve failing-input arms cannot
distinguish "the check catches every defect" from "the check fails on everything it is given".

The second arm is the real defect, replayed: on 2026-09-21 the first live run of this script found
that the deployed ResponseHeadersPolicy was missing `media-src 'self'`, which the stack source had
carried since 2026-09-17. Four published videos were therefore blocked in every real browser while a
local preview -- serving a policy parsed out of that same source -- walked them with zero violations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "platform" / "build"))

import check_deployed_headers as chk  # noqa: E402

STACK_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; "
    "font-src 'self'; connect-src 'self'; media-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
DEPLOYED_WITHOUT_MEDIA = STACK_CSP.replace("media-src 'self'; ", "")
PREFIX = "/v/20260917T091943Z/"
POLICY = "ec3b1339-0000-0000-0000-000000000000"

# `None` is a value a real reader RETURNS -- `get_json` answers `None` when the object is absent -- so
# it cannot double as "argument not supplied". A fake whose default-handling swallows `None` cannot
# express the absent-object case at all, and the arm for it passed vacuously until this sentinel
# existed.
_DEFAULT = object()


class FakeReader:
    """A reader that returns whatever a test tells it to, including wrong answers.

    Defaults describe a deployment that agrees with the stack in every respect, so each arm below
    changes exactly ONE thing and the failure it produces is attributable to that thing.
    """

    def __init__(
        self,
        *,
        csp: str | None = STACK_CSP,
        policy_id: str = POLICY,
        behaviours: list[tuple[str, str | None]] | None = None,
        pointer=_DEFAULT,
        release_keys: list[str] | None = None,
        cache_control: dict[str, str | None] | None = None,
        absent: tuple[str, ...] = (),
    ) -> None:
        self._csp = csp
        self._policy_id = policy_id
        self._behaviours = behaviours if behaviours is not None else [("default", POLICY)]
        self._pointer = {"release_prefix": PREFIX} if pointer is _DEFAULT else pointer
        self._release_keys = (
            release_keys if release_keys is not None
            else [f"{PREFIX.lstrip('/')}index.html",
                  f"{PREFIX.lstrip('/')}data/media/overview.en.mp4",
                  f"{PREFIX.lstrip('/')}data/media/overview.en.vtt"]
        )
        self._cache_control = cache_control or {}
        self._absent = absent

    def response_headers_policy_id(self) -> str:
        return self._policy_id

    def deployed_csp(self, policy_id: str) -> str | None:
        assert policy_id == self._policy_id, "the check must ask about the policy the stack owns"
        return self._csp

    def attached_policy_ids(self) -> list[tuple[str, str | None]]:
        return list(self._behaviours)

    def get_json(self, key: str) -> dict | None:
        assert key == "current.json"
        return self._pointer

    def release_keys(self, release_prefix: str) -> list[str]:
        assert release_prefix == (self._pointer or {}).get("release_prefix")
        return list(self._release_keys)

    def head(self, key: str) -> dict | None:
        if key in self._absent:
            return None
        if key in self._cache_control:
            value = self._cache_control[key]
            return {} if value is None else {"CacheControl": value}
        want = chk.expected_cache_control(key, PREFIX)
        # S3 reads back the value WITHOUT the optional whitespace after the comma, which is what a
        # real `head-object` returned on 2026-09-21. The default double reproduces that, so the
        # normalisation is exercised by the control arm rather than only by its own arm.
        return {"CacheControl": want.replace(", ", ",")}


# --------------------------------------------------------------------------- the no-mutant control
def test_a_deployment_that_agrees_in_every_respect_passes():
    """The control. If this ever fails, no other arm in this file means anything."""
    rep = chk.check(FakeReader(), STACK_CSP)
    assert rep.problems == [], rep.problems
    assert rep.rc == 0
    assert rep.csp_read is True
    assert rep.objects_probed == 5, "2 mutable + 3 release keys, all read"
    assert rep.behaviours_checked == 1


# ------------------------------------------------------------------- the defect this script found
def test_the_deployed_policy_missing_media_src_is_caught_and_the_message_names_the_directive():
    """The 2026-09-21 finding, replayed.

    `media-src` is the one directive whose absence a header-text test cannot see and a local preview
    cannot see either, because the preview parses the same source file. The failure message has to
    name the directive: "CSP drift" alone sends the reader to diff two 200-character strings by eye.
    """
    rep = chk.check(FakeReader(csp=DEPLOYED_WITHOUT_MEDIA), STACK_CSP)
    assert rep.rc == 1
    joined = "\n".join(rep.problems)
    assert "DRIFT" in joined
    assert "media-src 'self'" in joined
    assert "MISSING from the deployed policy" in joined


def test_a_directive_deployed_but_absent_from_the_source_is_reported_in_the_other_direction():
    """Drift is not only omission. A console edit that ADDS a directive is drift too, and a check
    that only looks for missing ones would call it clean."""
    rep = chk.check(FakeReader(csp=STACK_CSP + "; report-uri /csp"), STACK_CSP)
    assert rep.rc == 1
    assert any("deployed but NOT in the stack source" in p for p in rep.problems)
    assert any("report-uri" in p for p in rep.problems)


def test_the_same_directives_in_a_different_order_still_fail_and_say_why():
    """Reordering is almost certainly harmless to a browser and is still a difference between the
    deployed policy and the source of record. The check refuses to decide which differences matter;
    it reports that the two strings are not the same and names the shape of the difference."""
    reordered = "; ".join(reversed([d.strip() for d in STACK_CSP.split(";")]))
    rep = chk.check(FakeReader(csp=reordered), STACK_CSP)
    assert rep.rc == 1
    assert any("different order or spacing" in p for p in rep.problems)


def test_a_policy_with_no_csp_at_all_is_drift_not_an_absence_of_opinion():
    rep = chk.check(FakeReader(csp=None), STACK_CSP)
    assert rep.rc == 1
    assert rep.csp_read is False
    assert any("NO ContentSecurityPolicy at all" in p for p in rep.problems)


# ------------------------------------------------------------- the policy is right, the wiring is not
def test_a_behaviour_referencing_another_policy_fails_even_though_the_policy_body_is_correct():
    """The third drift mode item 41 names, and the one a comparison of policy bodies cannot see.

    Here the stack's policy is deployed and correct; the distribution just does not use it. Every
    check that reads the policy alone passes, and the page a reader loads is unprotected.
    """
    rep = chk.check(
        FakeReader(behaviours=[("default", "00000000-dead-beef-0000-000000000000")]), STACK_CSP)
    assert rep.rc == 1
    assert any("not the policy this path serves" in p for p in rep.problems)


def test_one_correct_behaviour_does_not_excuse_a_second_behaviour_with_no_policy():
    """A distribution grows path behaviours. `/api/*` added later with no response headers policy is
    exactly how a site ends up half-protected, so every behaviour is checked, not just the default."""
    rep = chk.check(
        FakeReader(behaviours=[("default", POLICY), ("/data/*", None)]), STACK_CSP)
    assert rep.rc == 1
    assert rep.behaviours_checked == 2
    assert any("/data/*" in p for p in rep.problems)


def test_a_distribution_with_no_behaviours_cannot_report_clean():
    rep = chk.check(FakeReader(behaviours=[]), STACK_CSP)
    assert rep.rc != 0
    assert any("no cache behaviour at all" in p for p in rep.problems)


# ------------------------------------------------------------------------------ Cache-Control arms
def test_an_immutable_object_serving_no_cache_is_caught():
    """The direction that costs money and staleness: a release object that is not cacheable makes
    every reader re-fetch 4.7 MB of video on every page view."""
    key = f"{PREFIX.lstrip('/')}data/media/overview.en.mp4"
    rep = chk.check(FakeReader(cache_control={key: chk.FRESH_CACHE_CONTROL}), STACK_CSP)
    assert rep.rc == 1
    assert any(key in p and "Cache-Control is" in p for p in rep.problems)


def test_a_mutable_object_serving_immutable_is_caught_and_is_the_worse_direction():
    """`index.html` with `max-age=31536000, immutable` pins a reader to one release for a year, and
    no republish can reach them. This is the failure the publisher's docstring worries about and
    nothing checked until now."""
    rep = chk.check(
        FakeReader(cache_control={"index.html": chk.IMMUTABLE_CACHE_CONTROL}), STACK_CSP)
    assert rep.rc == 1
    assert any("index.html" in p for p in rep.problems)


def test_an_object_with_no_cache_control_header_at_all_is_caught():
    rep = chk.check(FakeReader(cache_control={"current.json": None}), STACK_CSP)
    assert rep.rc == 1
    assert any("no Cache-Control at all" in p for p in rep.problems)


def test_only_whitespace_after_the_comma_is_normalised_and_nothing_else_is():
    """The one difference S3 is allowed to introduce, and the boundary of the allowance.

    `max-age=31536000,immutable` and `max-age=31536000, immutable` are the same header value per
    RFC 9110's optional whitespace, so accepting both is correct. Changing the MAX-AGE is not
    whitespace, and must still fail -- otherwise the normalisation has eaten the check.
    """
    assert chk.normalise_cache_control("a=1, b") == chk.normalise_cache_control("a=1,b")
    assert chk.normalise_cache_control("max-age=31536000, immutable") != \
        chk.normalise_cache_control("max-age=60, immutable")
    rep = chk.check(
        FakeReader(cache_control={"current.json": "no-cache,   must-revalidate"}), STACK_CSP)
    assert rep.rc == 0, "extra whitespace after the separator is not a defect"
    rep = chk.check(
        FakeReader(cache_control={f"{PREFIX.lstrip('/')}index.html":
                                  "max-age=60, immutable"}), STACK_CSP)
    assert rep.rc == 1, "a different max-age is not whitespace"


def test_an_absent_object_is_a_problem_and_is_not_counted_as_probed():
    """Absent must not read as clean, and it must not inflate the probe count either -- otherwise a
    release whose objects are all missing reports five probes and no problems."""
    rep = chk.check(FakeReader(absent=("index.html",)), STACK_CSP)
    assert rep.rc == 1
    assert rep.objects_probed == 4
    assert any("not present in the origin bucket" in p for p in rep.problems)


# ----------------------------------------------------------------------- the ran flag, and the floor
def test_probing_fewer_objects_than_the_floor_cannot_exit_zero_even_with_no_problems():
    """`feedback_zero_needs_a_ran_flag`. A release listing that returns nothing would otherwise give
    two probed objects, an empty problem list, and rc 0 -- a pass that read almost nothing."""
    rep = chk.check(FakeReader(release_keys=[]), STACK_CSP)
    assert rep.problems == [], "nothing is WRONG here; the point is that too little was read"
    assert rep.objects_probed == 2 < chk.MIN_OBJECTS_PROBED
    assert rep.rc == 2


def test_a_pointer_with_no_release_prefix_stops_before_probing_anything():
    rep = chk.check(FakeReader(pointer={}), STACK_CSP)
    assert rep.rc != 0
    assert rep.objects_probed == 0
    assert any("no release_prefix" in p for p in rep.problems)


def test_a_missing_pointer_object_is_a_problem_not_a_crash():
    rep = chk.check(FakeReader(pointer=None), STACK_CSP)
    assert rep.rc != 0
    assert any("release_prefix" in p for p in rep.problems)


def test_a_key_outside_both_classes_raises_rather_than_defaulting_to_either_value():
    """There is no sensible default here. Guessing `immutable` would let a stray object pass; guessing
    `fresh` would fail every release object. A caller error must look like one."""
    with pytest.raises(ValueError, match="neither a known mutable object"):
        chk.expected_cache_control("some/other/key.json", PREFIX)


def test_the_two_expected_values_come_from_the_publisher_and_are_not_retyped_here():
    """If someone changes the publisher's cache policy, this check must move with it. Asserting the
    IDENTITY of the import is what makes that true; asserting the string would pin a copy.
    """
    import publish_web

    assert chk.IMMUTABLE_CACHE_CONTROL is publish_web.IMMUTABLE_CACHE_CONTROL
    assert chk.FRESH_CACHE_CONTROL is publish_web.FRESH_CACHE_CONTROL
    assert "immutable" in chk.IMMUTABLE_CACHE_CONTROL
    assert "no-cache" in chk.FRESH_CACHE_CONTROL


def test_the_csp_under_comparison_is_the_one_the_stack_file_holds():
    """The source side is `csp_preview.csp_from_stack()` -- the same parse the local preview serves
    behind -- so this check cannot drift from the preview. What makes it a real check is that the
    OTHER side is CloudFront's answer, which is exactly what was never read before.
    """
    parsed = chk.csp_from_stack()
    assert "default-src 'none'" in parsed
    assert "media-src 'self'" in parsed, \
        "the stack has carried media-src since 2026-09-17; if this fails the stack lost it"
    assert parsed.count(";") == parsed.count("; "), "the parse joins on '; ' by construction"
