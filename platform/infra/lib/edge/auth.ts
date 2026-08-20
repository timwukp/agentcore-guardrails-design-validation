// The viewer-request Lambda@Edge function: the only thing standing between the internet and every
// byte of this payload.
//
// WHY VIEWER-REQUEST, AND WHY EXACTLY ONE CACHE BEHAVIOUR
//
// `origin-request` has a 50 MB package limit against viewer-request's 1 MB, which makes it the tempting
// choice. It is the wrong one: origin-request fires only on a cache MISS, so once `/data/census.json`
// is in an edge cache CloudFront serves it without invoking anything. An unauthenticated viewer would
// get the file. Viewer-request fires on every request, before the cache is consulted.
//
// The 1 MB limit is therefore a real constraint and it was measured rather than hoped: this handler,
// bundled and minified with both SDK clients and `cognito-at-edge`, is 995 KB raw / 270 KB zipped
// (limit 1,048,576 zipped). `npm test` re-measures it on every run — the arm named "the bundled edge
// function fits the 1 MB viewer-request package limit" locates this bundle in the synth assembly by a
// string only this handler contains, and fails both when the deflated size crosses the line and when
// the bundle is suspiciously small (an esbuild stub would make the limit check vacuous). It is measured
// rather than reasoned about because a bundle that crosses the line fails at CREATE time in CloudFront
// with an error that names the size and not the dependency that caused it.
//
// The distribution has ONE behaviour, the default one, and this function is attached to it. That is the
// whole access-control argument: there is no second behaviour, so there is no path — not `/data/*`, not
// `/v/<stamp>/*`, not `/index.html` — that can be reached without passing through here. Adding a
// behaviour to give one prefix a different cache policy would silently create such a path, which is why
// the immutable-release caching is done with per-object `Cache-Control` at upload time instead.
//
// FAIL CLOSED
//
// If the configuration cannot be read, this function throws. CloudFront turns that into a 502 for the
// viewer, and that is the correct outcome: the alternative — `return request` on error so the site
// stays up — is one line away and would publish the whole payload to the internet the first time an
// SSM call timed out. The failure mode of an auth check must be "nobody gets in".

import { Authenticator } from "cognito-at-edge";
import { GetSecretValueCommand, SecretsManagerClient } from "@aws-sdk/client-secrets-manager";
import { GetParameterCommand, SSMClient } from "@aws-sdk/client-ssm";
import type { CloudFrontRequest, CloudFrontRequestEvent, CloudFrontResultResponse } from "aws-lambda";
import { CLIENT_SECRET_NAME, CONFIG_PARAMETER_NAME, EDGE_REGION } from "./names.ts";
import type { EdgeAuthConfig } from "./names.ts";

/** Cached across invocations of one container — the point of doing this at cold start. Holds the
 *  PROMISE, not the value, so two concurrent first requests share one pair of API calls. */
let authenticator: Promise<Authenticator> | null = null;

async function build(): Promise<Authenticator> {
  // Region pinned, not defaulted: this code runs in whichever region the viewer is near, and both the
  // parameter and the secret exist only in us-east-1.
  const ssm = new SSMClient({ region: EDGE_REGION });
  const secrets = new SecretsManagerClient({ region: EDGE_REGION });

  const [parameter, secret] = await Promise.all([
    ssm.send(new GetParameterCommand({ Name: CONFIG_PARAMETER_NAME })),
    secrets.send(new GetSecretValueCommand({ SecretId: CLIENT_SECRET_NAME })),
  ]);

  const raw = parameter.Parameter?.Value;
  if (!raw) throw new Error(`config parameter ${CONFIG_PARAMETER_NAME} has no value`);
  const cfg = JSON.parse(raw) as EdgeAuthConfig;
  const userPoolAppSecret = secret.SecretString;
  if (!userPoolAppSecret) throw new Error(`secret ${CLIENT_SECRET_NAME} has no string value`);

  return new Authenticator({
    region: cfg.region,
    userPoolId: cfg.userPoolId,
    userPoolAppId: cfg.userPoolAppId,
    userPoolAppSecret,
    userPoolDomain: cfg.userPoolDomain,
    cookieExpirationDays: cfg.cookieExpirationDays,

    // `silent` is the library's default and it is the right one HERE, for a reason worth naming: at
    // `info` the library logs the decoded ID token claims of every forwarded request, and at `debug` it
    // logs the access, id and refresh tokens themselves. Those logs land in CloudWatch in whichever
    // region served the request. `warn` keeps genuine failures visible without writing bearer tokens
    // and the user's email address into thirteen regional log groups.
    logLevel: "warn",

    // Host-only cookies. The alternative sets `Domain=<distribution>.cloudfront.net`, which is legal
    // but pointlessly widens the cookie's scope on a shared parent domain.
    disableCookieDomain: true,
    httpOnly: true,

    // Lax, NOT Strict. The request that carries `?code=…` is a top-level navigation arriving FROM the
    // Cognito hosted UI — a different site — so under `Strict` the browser withholds the cookies this
    // function has just set and the user loops through login forever. `Lax` sends cookies on top-level
    // cross-site GETs, which is exactly and only what the OAuth redirect is.
    sameSite: "Lax",

    // `csrfProtection` is deliberately NOT enabled, and this is a defect in the library rather than a
    // preference. With it on and no `parseAuthPath`, the post-login `Location` is built as
    // `https://<host>/` + the state's `redirect_uri`, which is itself a full URL — measured output:
    // `https://d.cloudfront.net/https://d.cloudfront.net`. Login would complete and then 404.
    //
    // What it would have bought: a nonce binding the callback to the browser that started the flow.
    // What its absence costs: `state` is the requested path in clear text and is attacker-supplied on
    // the callback. That is NOT an open redirect — the same concatenation that breaks the CSRF mode
    // guarantees the `Location` is always on this distribution's own host (measured for
    // `https://evil.example`, `//evil.example` and backslash variants; all resolve to a path under
    // `https://<distribution>/`). The residual is a forced-login CSRF, which requires the attacker to
    // already hold a valid account in a pool whose self-signup is disabled and whose only users are
    // created by `AdminCreateUser`.
  });
}

export const handler = async (
  event: CloudFrontRequestEvent,
): Promise<CloudFrontRequest | CloudFrontResultResponse> => {
  try {
    // A rejected promise must not be cached: one transient SSM failure would otherwise wedge this
    // container permanently, and CloudFront would keep routing to it.
    authenticator ??= build().catch((err: unknown) => {
      authenticator = null;
      throw err;
    });
    return await (await authenticator).handle(event);
  } catch (err) {
    // Name only, never the error object: messages from these SDKs quote the full ARN of what they
    // failed to read, which carries the account id.
    console.error("grx-live edge auth failed:", err instanceof Error ? err.name : typeof err);
    throw err; // fail closed — see the header comment
  }
};
