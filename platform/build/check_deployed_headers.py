#!/usr/bin/env python3
"""Read the headers a browser actually receives off the DEPLOYED resources, not off the source.

WHY THIS EXISTS
---------------
`FUTURE-WORK.md` item 41: three headers decide what a reader's browser does with the published bytes,
and until this file existed not one of them was ever read back from AWS.

  * `Content-Security-Policy` had **two** green checks — a CDK assertion against the synthesised
    template, and `csp_preview.py`, which serves the SPA behind the same policy. Both parse
    `platform/infra/lib/site-stack.ts`. Two checks over one source are one check
    (`feedback_verify_against_real_artifact`), and neither can see a console edit, a partial deploy, or
    a policy attached to the wrong cache behaviour.
  * `Cache-Control` — `max-age=31536000, immutable` on `v/<stamp>/**` and `no-cache, must-revalidate`
    on the two mutable objects — was set by flags on `publish_web.upload()`'s `s3` calls and checked by
    nothing at all.
  * The Lambda@Edge viewer decision was checked by a hand-run `curl` recorded in a session log.

This closes the first two. It CANNOT close the third: every viewer request is authorized by Cognito
with `mfa: REQUIRED` and this platform must never create an account, so no scripted client can fetch
an object through the distribution and read its response headers — an unauthenticated probe returns a
`302` and a redirect carries the redirect's headers. That half closes only as a dated human record, and
this script says so on every run rather than letting a pass be read as "item 41 is done".

WHAT IT PROVES, AND WHAT IT STILL ASSUMES
-----------------------------------------
Proves: the `ResponseHeadersPolicy` that the distribution's behaviours actually reference carries a
`ContentSecurityPolicy` string equal, character for character, to the one parsed out of the stack
source; and the objects in the origin bucket carry the `Cache-Control` the publisher claims to set.

Still assumes: that CloudFront applies a policy it is configured with, and that no Lambda@Edge or
CloudFront Function rewrites the header on the way out. Those are one layer further down than the
drift this item was opened for.

NO IDENTIFIER LITERALS
----------------------
The bucket name, the distribution id, the policy id and the site hostname are **never written in this
file**. Every one of them is resolved at run time from the CloudFormation stack, for two reasons: a
literal would be a redaction surface in a repository whose gate rejects account ids, ARNs and bucket
names, and a literal would also let this check pass against a stack that no longer exists.

USAGE

    .venv-oracle/bin/python platform/build/check_deployed_headers.py            # rc 0 = agrees
    .venv-oracle/bin/python platform/build/check_deployed_headers.py --verbose

Needs `cloudformation:DescribeStacks`, `cloudformation:DescribeStackResources`,
`cloudfront:GetResponseHeadersPolicy`, `cloudfront:GetDistributionConfig`, `s3:GetObject` and
`s3:HeadObject`. All read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "platform" / "build"))

from csp_preview import csp_from_stack  # noqa: E402  the ONE parse of the stack source, reused
from lib import redact  # noqa: E402

STACK_NAME = "GrxLive"
RHP_TYPE = "AWS::CloudFront::ResponseHeadersPolicy"

# What `publish_web.upload()` sends. Imported rather than retyped, so a change to the publisher moves
# this check with it -- and note the asymmetry that makes this legitimate rather than circular: the
# OTHER side of the comparison is a header read off a real object in S3.
from publish_web import FRESH_CACHE_CONTROL, IMMUTABLE_CACHE_CONTROL  # noqa: E402

# The two objects the publisher deliberately keeps mutable. Everything else it writes lives under
# `v/<stamp>/` and must be immutable.
MUTABLE_KEYS = ("current.json", "index.html")

# A probe budget, not a ceiling: fewer than this many objects READ means the script did not do its
# job, and a script that checked nothing must not exit 0 (`feedback_zero_needs_a_ran_flag`).
MIN_OBJECTS_PROBED = 3


def normalise_cache_control(value: str) -> str:
    """Collapse the one difference S3 is allowed to introduce: whitespace after a comma.

    `publish_web` sends `max-age=31536000, immutable`; a `head-object` reads back
    `max-age=31536000,immutable`. RFC 9110 lets a sender put optional whitespace after the
    list separator, so the two strings are the same header value and a byte comparison would
    report a defect that no browser can observe. NOTHING ELSE is normalised -- not case, not
    directive order, not duplicate directives -- because each of those would hide a real change.
    """
    return ",".join(part.strip() for part in (value or "").split(","))


def compare_csp(deployed: str, source: str) -> list[str]:
    """Character-for-character, then directive-by-directive so the message names the difference.

    The equality test is the check. The set difference exists only so that a failure reads
    "media-src 'self' is in the stack and not in the deployed policy" instead of dumping two
    185-character strings at a reader and leaving the diff to their eyes.
    """
    if deployed == source:
        return []
    problems = ["Content-Security-Policy DRIFT: the deployed policy is not the stack's policy"]
    dep = [d.strip() for d in deployed.split(";") if d.strip()]
    src = [d.strip() for d in source.split(";") if d.strip()]
    missing = [d for d in src if d not in dep]
    extra = [d for d in dep if d not in src]
    for d in missing:
        problems.append(f"  in the stack source, MISSING from the deployed policy: {d!r}")
    for d in extra:
        problems.append(f"  deployed but NOT in the stack source: {d!r}")
    if not missing and not extra:
        problems.append(
            "  the same directives in a different order or spacing: "
            f"deployed={deployed!r} source={source!r}")
    return problems


def expected_cache_control(key: str, release_prefix: str) -> str:
    """Which of the publisher's two values this key is supposed to carry.

    `release_prefix` arrives as `/v/<stamp>/` -- the form `current.json` publishes -- and an S3 key
    has no leading slash, so the comparison is made on the stripped form. A key that is neither one
    of the two mutable objects nor under the live release prefix is a caller error, not a header
    defect, and raises rather than defaulting to either value.
    """
    if key in MUTABLE_KEYS:
        return FRESH_CACHE_CONTROL
    if key.startswith(release_prefix.lstrip("/")):
        return IMMUTABLE_CACHE_CONTROL
    raise ValueError(
        f"{key!r} is neither a known mutable object {MUTABLE_KEYS} nor under the live release "
        f"prefix {release_prefix!r}; this script has no expectation to check it against")


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    objects_probed: int = 0
    csp_read: bool = False
    behaviours_checked: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def rc(self) -> int:
        if self.problems:
            return 1
        if not self.csp_read:
            return 2
        if self.objects_probed < MIN_OBJECTS_PROBED:
            return 2
        if self.behaviours_checked < 1:
            return 2
        return 0


def check(reader, source_csp: str) -> Report:
    """The whole check, over an injected reader, so every arm below is testable without AWS.

    `reader` supplies six methods -- `response_headers_policy_id()`, `deployed_csp(policy_id)`,
    `attached_policy_ids()`, `get_json(key)`, `release_keys(prefix)` and `head(key)` -- and this
    function contains no boto3. The live wiring is `Boto3Reader`; the tests pass a fake that can
    return a drifted policy, a missing directive, a wrong `Cache-Control`, or nothing at all.
    """
    rep = Report()

    policy_id = reader.response_headers_policy_id()
    deployed = reader.deployed_csp(policy_id)
    if deployed is None:
        rep.problems.append(
            "the deployed ResponseHeadersPolicy carries NO ContentSecurityPolicy at all; "
            "the stack source defines one, so this is drift, not a difference of opinion")
    else:
        rep.csp_read = True
        rep.problems.extend(compare_csp(deployed, source_csp))

    # A policy that exists and is right protects nothing if a behaviour does not reference it. This
    # is the third drift mode item 41 names, and it is invisible to a comparison of policy bodies.
    attached = reader.attached_policy_ids()
    rep.behaviours_checked = len(attached)
    if not attached:
        rep.problems.append("the distribution has no cache behaviour at all -- nothing was checked")
    for behaviour, pid in attached:
        if pid != policy_id:
            rep.problems.append(
                f"behaviour {behaviour!r} references response headers policy {pid!r}, not the "
                f"stack's {policy_id!r}: the policy checked above is not the policy this path serves")

    pointer = reader.get_json("current.json")
    release_prefix = (pointer or {}).get("release_prefix")
    if not release_prefix:
        rep.problems.append(
            "current.json carries no release_prefix, so there is no live release to probe; "
            "either nothing is published or the pointer is malformed")
        return rep
    rep.notes.append(f"live release {release_prefix}")

    keys = list(MUTABLE_KEYS) + reader.release_keys(release_prefix)
    for key in keys:
        head = reader.head(key)
        if head is None:
            rep.problems.append(f"{key}: not present in the origin bucket")
            continue
        rep.objects_probed += 1
        want = expected_cache_control(key, release_prefix)
        got = head.get("CacheControl")
        if got is None:
            rep.problems.append(
                f"{key}: no Cache-Control at all; the publisher claims to set {want!r}")
        elif normalise_cache_control(got) != normalise_cache_control(want):
            rep.problems.append(
                f"{key}: Cache-Control is {got!r}, the publisher claims to set {want!r}")
    return rep


# ------------------------------------------------------------------------------------- live wiring
class Boto3Reader:
    """The only part of this file that talks to AWS. Everything it returns is plain data."""

    def __init__(self, stack_name: str = STACK_NAME, media_probes: int = 2) -> None:
        import boto3

        self._cfn = boto3.client("cloudformation", region_name="us-east-1")
        self._cf = boto3.client("cloudfront", region_name="us-east-1")
        self._s3 = boto3.client("s3", region_name="us-east-1")
        self._stack = stack_name
        self._media_probes = media_probes
        out = self._cfn.describe_stacks(StackName=stack_name)["Stacks"][0].get("Outputs", [])
        self._outputs = {o["OutputKey"]: o["OutputValue"] for o in out}
        # Resolved through the choke point, which registers it with `redact.register_account_id` as
        # a side effect -- so any ARN this script prints has its account field masked. The first
        # draft called `get_caller_identity()` inline right here and registered the result by hand;
        # `lib/tests/test_account_id_choke_point.py` failed it, which is the whole reason that test
        # exists (the bucket name, the distribution id and the site hostname are simply never
        # printed). Imported here rather than at module scope because `awsclients` imports boto3,
        # and this file must stay importable under the interpreter that owns playwright.
        from lib import awsclients  # noqa: PLC0415  see above

        awsclients.account_id(awsclients.ClientFactory(region="us-east-1"))

    def outputs(self) -> dict[str, str]:
        return dict(self._outputs)

    def response_headers_policy_id(self) -> str:
        res = self._cfn.describe_stack_resources(StackName=self._stack)["StackResources"]
        ids = [r["PhysicalResourceId"] for r in res if r["ResourceType"] == RHP_TYPE]
        if len(ids) != 1:
            raise SystemExit(
                f"expected exactly one {RHP_TYPE} in stack {self._stack}, found {len(ids)}")
        return ids[0]

    def deployed_csp(self, policy_id: str) -> str | None:
        cfg = self._cf.get_response_headers_policy(Id=policy_id)["ResponseHeadersPolicy"][
            "ResponseHeadersPolicyConfig"]
        csp = cfg.get("SecurityHeadersConfig", {}).get("ContentSecurityPolicy")
        return csp.get("ContentSecurityPolicy") if csp else None

    def attached_policy_ids(self) -> list[tuple[str, str | None]]:
        dist = self._outputs["DistributionId"]
        cfg = self._cf.get_distribution_config(Id=dist)["DistributionConfig"]
        out = [("default", cfg["DefaultCacheBehavior"].get("ResponseHeadersPolicyId"))]
        for b in cfg.get("CacheBehaviors", {}).get("Items", []):
            out.append((b.get("PathPattern", "?"), b.get("ResponseHeadersPolicyId")))
        return out

    def get_json(self, key: str) -> dict | None:
        try:
            body = self._s3.get_object(Bucket=self._outputs["PayloadBucket"], Key=key)["Body"].read()
        except Exception:
            return None
        return json.loads(body)

    def release_keys(self, release_prefix: str) -> list[str]:
        """One immutable HTML object plus, if the release publishes media, one mp4 and one vtt.

        Derived from a listing rather than typed, because a typed asset name would make this check
        fail for a release that renamed its videos -- which is a change, not a defect.
        """
        prefix = release_prefix.lstrip("/")
        keys = [f"{prefix}index.html"]
        page = self._s3.list_objects_v2(
            Bucket=self._outputs["PayloadBucket"], Prefix=f"{prefix}data/media/")
        media = sorted(o["Key"] for o in page.get("Contents", []))
        for ext in (".mp4", ".vtt"):
            first = next((k for k in media if k.endswith(ext)), None)
            if first:
                keys.append(first)
        return keys[: 1 + self._media_probes]

    def head(self, key: str) -> dict | None:
        try:
            return self._s3.head_object(Bucket=self._outputs["PayloadBucket"], Key=key)
        except Exception:
            return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stack", default=STACK_NAME)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    source_csp = csp_from_stack()
    reader = Boto3Reader(args.stack)
    rep = check(reader, source_csp)

    print(f"stack                 {args.stack}")
    print(f"CSP parsed from       platform/infra/lib/site-stack.ts ({len(source_csp)} chars)")
    print(f"CSP read from         cloudfront:GetResponseHeadersPolicy "
          f"({'present' if rep.csp_read else 'ABSENT'})")
    print(f"behaviours checked    {rep.behaviours_checked}")
    print(f"objects probed        {rep.objects_probed} (floor {MIN_OBJECTS_PROBED})")
    for n in rep.notes:
        print(f"note                  {redact.mask_text(n)}")
    if args.verbose:
        print(f"\nsource CSP   {source_csp}")

    if rep.problems:
        print("\nPROBLEMS")
        for p in rep.problems:
            print(f"  {redact.mask_text(p)}")
    else:
        print("\nOK -- the deployed policy equals the stack's, every behaviour references it, and "
              "every probed object carries the Cache-Control the publisher claims to set.")

    # Printed on every run, pass or fail. Item 41 has three headers and this script reads two of
    # them; a reader who sees only "OK" must not conclude the third was checked.
    print("\nSTILL OPEN (item 41, and this script cannot close it): the Lambda@Edge viewer "
          "decision.\n  A viewer request needs a Cognito session on a pool with mfa: REQUIRED, and "
          "this platform never\n  creates an account. That half closes only as a DATED human "
          "record -- someone with the second\n  factor loading the live page once and pasting the "
          "response headers into a log, labelled with the\n  release stamp it was read against, "
          "because it expires on the next deploy.")
    return rep.rc


if __name__ == "__main__":
    sys.exit(main())
