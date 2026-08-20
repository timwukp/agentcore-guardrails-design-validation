# GRX Live delivery stack

The AWS side of Phase 1: a private, invite-only way to read the validation payload in a browser. One
CDK stack (`GrxLive`), one region (`us-east-1`), no compute that the reader can reach other than the
authentication check itself.

```
browser
  └─ CloudFront distribution                     one cache behaviour, and only one
       ├─ viewer-request Lambda@Edge  ──────────  Cognito session check (cognito-at-edge 1.5.5)
       │     ├─ SSM /grx-live/edge-auth/config    non-secret config, read at cold start
       │     └─ Secrets grx-live/edge-auth/…      the app client secret, and nothing else
       ├─ ResponseHeadersPolicy                   CSP, nosniff, DENY, no-referrer, HSTS 365 d
       ├─ access logs ─→ S3 AccessLogs bucket     logIncludesCookies: false — the cookies ARE tokens
       └─ S3 origin via OAC                       private Payload bucket, TLS-only, RETAIN
                                                  ├─ index.html            (no-cache pointer)
                                                  ├─ current.json          (no-cache pointer)
                                                  └─ v/<stamp>/…           (immutable, 1 year)
Cognito user pool  ─ AdminCreateUser only, TOTP MFA required, 16-char minimum, 7-day sessions
```

`platform/build/publish_web.py` is what puts bytes in the bucket. This directory only creates the
place they go and the check in front of it.

## Deploy

```bash
cd platform/infra
npm ci
npm run typecheck          # tsc --noEmit
npm test                   # 15 assertions against the synthesised template
AWS_REGION=us-east-1 npx cdk deploy
```

`cdk deploy` prints the CloudFront domain, the pool id, the hosted-UI domain, and an `InviteCommand`
output — a ready-to-run `aws cognito-idp admin-create-user` line, because "invite-only" is only true
if inviting is a single documented act rather than a console session nobody wrote down.

There is no post-deploy wiring step. The app client's single callback URL is built from
`distribution.distributionDomainName` inside the stack, so it is correct by construction — Cognito
matches callback URLs exactly, and a hand-entered one with a trailing slash produces
`redirect_mismatch` at login rather than a warning at deploy. A test arm asserts the URL's *structure*
(`["https://", <domain ref>]` and nothing after the reference) rather than pattern-matching the
serialised form, which cannot distinguish the callback's trailing slash from the one inside `https://`.

The hosted-UI domain prefix defaults to `grx-live-84e6fcbf` and is overridable with
`-c domainPrefix=…`; it must be globally unique across all AWS accounts, so a collision surfaces as a
deploy-time error from Cognito.

After deploying, invite yourself with the `InviteCommand` output, then publish a payload with
`python platform/build/publish_web.py --confirm`.

## What is measured, not assumed

Four findings, each of which changed the design. They are recorded here because
`platform/infra/lib/edge/names.ts` and `platform/infra/lib/edge/auth.ts` cite this section, and because the alternative — a comment
asserting "we checked" — is a claim nothing reproduces.

### 1. `cognito-at-edge` 1.5.5 does not implement PKCE

Read from the installed package, not from its README. The library generates a PKCE verifier and writes
it into a cookie, then never sends `code_challenge` on the `/authorize` redirect and never sends
`code_verifier` to `/oauth2/token`. So the flow is a plain authorization-code exchange.

**Consequence, and the design response:** this platform enables CloudFront access logging, and the
callback request carries `?code=…` in its URI, so the code is written to the log. With a *public*
client and no PKCE, a logged code is a credential for anyone who can read the log bucket. The app
client is therefore **confidential** — `GenerateSecret: true` — and the token endpoint additionally
requires HTTP Basic authentication that only the edge function holds, which makes the logged code
inert. Codes are single-use and short-lived, so this narrows an already narrow window; it is written
down because "we turned on access logging" and "we made the logged value harmless" are two separate
decisions and only the first one is obvious.

### 2. `csrfProtection` breaks login, measurably

Enabling the library's `csrfProtection` without a `parseAuthPath` builds the post-login `Location`
header as `https://<host>/` concatenated with the state's `redirect_uri` — which is itself already a
full URL. Measured output: `https://d.cloudfront.net/https://d.cloudfront.net`. Login completes and
the browser then lands on a 404. So it is off, and that is a library defect rather than a preference.

**What its absence costs, stated precisely:** `state` carries the requested path in clear text and is
attacker-supplied on the callback, and there is no nonce binding the callback to the browser that
started the flow. The residual risk is a *forced-login CSRF* — an attacker completing a login flow in
someone else's browser using their own account — which requires the attacker to already hold an
account in this pool. Self-signup is disabled and every user is created by `AdminCreateUser`, so the
population of possible attackers is the population of invited readers.

### 3. It is not an open redirect

The natural worry from (2) is that an attacker-supplied `state` becomes a redirect target. It does
not, and the reason is the same concatenation that breaks the CSRF mode: the `Location` is always
`https://<this distribution's host>/` + the supplied value, so the result is always a path on this
distribution. Measured against `https://evil.example`, `//evil.example`, and backslash variants — all
resolve to a path under `https://<distribution>/`. This is stated so that a future change to how
`Location` is built is understood to be load-bearing.

### 4. The bundle fits, with 74 % of the budget spent

The handler bundles both SDK v3 clients and `cognito-at-edge` into **995 KB raw / 270 KB deflated**,
against Lambda@Edge's **1,048,576-byte zipped limit for viewer-request** functions. `npm test`
re-measures this on every run: the arm locates the bundle in the synth assembly by a string only this
handler contains (there are two asset directories — the other is CDK's custom-resource provider
framework), sums `gzipSync` over its files, and fails if the total crosses the limit *or* if the raw
size is under 100 KB, since an esbuild stub would make the check vacuous.

This is the reason the function is `viewer-request` and the budget is tight at all. `origin-request`
has a 50 MB limit and is the tempting choice — and it is wrong here, because it fires only on a cache
**miss**. Once `/v/<stamp>/data/census.json` is in an edge cache, CloudFront would serve it without
invoking anything, to anyone.

### 5. The CSP does not silently break the page

A synth test asserting the header's *text* cannot tell a working policy from one that blocks a
stylesheet — the served page would render unstyled and every JSON assertion would still pass. So
`platform/build/csp_preview.py` serves `site/dist` behind exactly these header values and the SPA was
walked in Chromium: all ten routes plus a case drill-down, **zero CSP violations** in the console; the
one stylesheet reported **94 readable `cssRules`** (a blocked sheet raises `SecurityError` on
`cssRules`, so a number is proof of application, not merely of a 200); **14 elements** carried live
`style` attributes; and all **7 figure PNGs** reported a non-zero `naturalWidth`.

`style-src 'unsafe-inline'` is the one relaxation and it is required: React `style={{…}}` props are
inline styles. `script-src` has no such relaxation, and a test arm fails if one ever appears.

The preview **parses the policy out of `platform/infra/lib/site-stack.ts`** rather than holding a copy, and the test
arm "the CSP the preview server enforces is the CSP the distribution sends" compares the parse against
the synthesised template. So the reproducer cannot drift from what ships, and a refactor that breaks
the parse fails `npm test` instead of failing silently for whoever next runs the preview. The preview
deliberately omits HSTS — it serves `http://127.0.0.1`, where an HSTS header would pin the loopback
host to HTTPS in the developer's browser.

## Design decisions a reader should be able to challenge

**One cache behaviour, and a test that asserts there is only one.** The entire access-control argument
is that there is no path — not `/index.html`, not `/current.json`, not `/v/<stamp>/*` — that does not
pass through the viewer-request function. A second behaviour would need its own Lambda association,
and forgetting one creates an unauthenticated path with no error anywhere. So immutable-release
caching is done with per-object `Cache-Control` at upload time instead of with a path-scoped cache
policy, and `npm test` fails if `CacheBehaviors` is non-empty.

**No 403/404 rewrite to `index.html`.** The usual SPA setting turns a missing payload file into a
200 carrying HTML, which surfaces in the browser as a JSON parse error — "the build did not emit this
file" disguised as "the payload is corrupt". Routing is a `HashRouter` for the same reason: deep links
work without a rewrite. `site/src/lib/data.ts` additionally checks the content type, so if a rewrite
is ever added the two failures still read differently.

**`RemovalPolicy.RETAIN` on everything, and the bucket is never emptied.** `cdk destroy` leaves the
bucket, the pool and the secret behind. This mirrors `runner/teardown.py`, which always keeps its
bucket: in a project whose artifacts are the deliverable, an accidental `destroy` must not be able to
delete evidence.

**`cdk.out` is written to `../../../.grx-cdk-out/grx-live`, outside the repository.** Not tidiness:
the synthesised template legitimately contains the account id (see below) and
`cdk.json`'s manifest contains `aws://<account>/us-east-1`. `check_redaction.py` scans the repo tree
and is right to fail on those, so the output goes where it cannot be scanned or committed. A test arm
asserts the `output` setting resolves outside the repo root.

**Hand-built ARNs use `Aws.ACCOUNT_ID`, never `Stack.of(this).account`.** The latter resolves to the
literal twelve digits at synth time. A test arm asserts that the only twelve-digit literal anywhere in
the template is the CDK bootstrap asset bucket's name (`cdk-hnb659fds-assets-<account>-<region>`,
which appears exactly twice and cannot be removed — it is where the Lambda bundles were uploaded), and
that a pseudo-parameter reference exists at all, so the arm cannot pass by the ARN statements being
absent.

**The edge role reads exactly one parameter and one secret.** Asserted as a set equality on the
action list, scoped to the edge role's own policy. The stack has a second IAM policy: CDK implements
`userPoolClient.userPoolClientSecret` as a custom resource calling
`cognito-idp:DescribeUserPoolClient`, because CloudFormation's `AWS::Cognito::UserPoolClient` has no
`ClientSecret` return value. Folding both policies into one assertion would make it assert a union and
stop noticing a widening of either half.

## An honest limitation of how the client secret is obtained

Because CloudFormation does not return the app client's secret, CDK reads it through a custom resource
that calls `DescribeUserPoolClient`, and the value then passes through CloudFormation as a resource
attribute in order to be written into Secrets Manager. **Anyone who can describe that stack resource,
or read the stack's events and resource data, can read the client secret.** In this account that is
the same person who can read the secret directly, so it changes nothing here — the platform's audience
is one invited reader and the deployer is the same principal. It is written down because the mitigation
is not obvious (it would require creating the client outside CloudFormation, or rotating the secret
after deploy) and because a reader copying this stack into a multi-team account needs to know that the
secret's blast radius is "whoever can read this stack", not "whoever can read this secret".

The secret itself is worth what it protects: with it, an authorization code found in an access log can
be exchanged for tokens. Without a session cookie it grants nothing on its own.

## Files

| File | What it is |
|---|---|
| `platform/infra/bin/grx-live.ts` | The app. Refuses to synthesise outside `us-east-1` or without resolved credentials — both checked before the stack is constructed, and both mutation-tested including a passing control. |
| `platform/infra/lib/site-stack.ts` | The whole stack: two buckets (payload + CloudFront access logs), one distribution, **one** cache behaviour, one edge function, one user pool. `PriceClass.PRICE_CLASS_200` — Asia is included because that is where the only reader is; South America and Oceania are not. |
| `platform/infra/lib/edge/auth.ts` | The viewer-request handler. Fails closed: if config cannot be read it throws, CloudFront returns 502, and nobody gets in. |
| `platform/infra/lib/edge/names.ts` | The two fixed names the stack writes and the handler reads. A Lambda@Edge function has no environment variables, so the name is the only channel — declared once, imported by both sides. |
| `platform/infra/test/site-stack.test.ts` | 15 assertions against the synthesised template. Every load-bearing arm was mutation-checked: the property was removed or inverted in the source, the arm was confirmed to fail, and the source was restored. `no_mutant_control` runs first so a green suite is attributable to the assertions rather than to an empty synth. |

## Cost

At Phase 1 volumes — under 10 MB of payload, one reader — the stack is **$1–3/month**: CloudFront
requests and transfer, S3 storage and requests, Lambda@Edge invocations at roughly $1 per million,
Secrets Manager at $0.40 for the one secret, SSM Parameter Store standard tier free, and the Cognito
user pool inside the free tier. There is no NAT gateway, no ALB, no always-on compute, and no
database.
