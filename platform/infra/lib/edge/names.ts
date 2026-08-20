// The fixed names the edge function and the stack must agree on, in ONE place.
//
// WHY THIS FILE EXISTS AT ALL
//
// A Lambda@Edge function cannot have environment variables. That is not a CDK limitation — CloudFront
// replicates the function to every edge location and the replica carries no per-deployment config — so
// the usual mechanism for handing a Lambda the id of a resource created in the same stack is simply
// unavailable. The function must therefore look its configuration up at cold start, by a name it has
// hardcoded, from a store the stack wrote under that same name.
//
// That makes the name a load-bearing invariant with two independent readers: the stack (which writes)
// and the handler (which reads). Two literals in two files agree until someone renames one of them,
// and the failure surfaces as "every request 503s after a deploy" — a long way from the edit. So the
// literal is declared once here and imported by both. `esbuild` inlines it into the handler bundle and
// `tsc` inlines it into the CDK app, so there is no runtime coupling; there is only one place to edit.

/** The region every edge replica must call. Lambda@Edge replicas run in the region nearest the viewer,
 *  but the parameter and the secret exist only in us-east-1 (where the function itself must live), so
 *  the SDK clients are pinned rather than left to default to the replica's own region. */
export const EDGE_REGION = "us-east-1";

/** SSM parameter holding the NON-SECRET half of the config as JSON. Parameter Store standard tier is
 *  free; Secrets Manager is $0.40/month per secret, so only the actual secret goes there. */
export const CONFIG_PARAMETER_NAME = "/grx-live/edge-auth/config";

/** Secrets Manager secret holding the Cognito app client secret, and nothing else.
 *
 *  The client is confidential (it has a secret) rather than public, and the reason is this platform's
 *  own CloudFront access logging: the authorization code arrives as `?code=…` on a request that gets
 *  written to the access log. With a public client and no PKCE that logged code is a credential — with
 *  a client secret it is inert, because the token endpoint additionally requires HTTP Basic auth that
 *  only this function holds. (Codes are single-use and short-lived, so this is a narrowing of an
 *  already narrow window, not the difference between safe and unsafe. It is stated because "we enabled
 *  access logging" and "we made the logged value harmless" are two decisions and only one is obvious.)
 *
 *  PKCE would be the other answer and it is NOT available here: `cognito-at-edge` 1.5.5 generates a
 *  PKCE verifier and sets it in a cookie but never sends `code_challenge` to `/authorize` nor
 *  `code_verifier` to `/oauth2/token` — measured against the installed package, not inferred from its
 *  README. See `README.md` under "What was measured, not assumed". */
export const CLIENT_SECRET_NAME = "grx-live/edge-auth/client-secret";

/** The JSON written to `CONFIG_PARAMETER_NAME`. Every field is what `cognito-at-edge` wants under the
 *  same name, so the handler does no mapping — a mapping is a third place a rename can hide. */
export interface EdgeAuthConfig {
  /** The Cognito pool's region, which is also `EDGE_REGION`; carried explicitly because the library
   *  takes it as a parameter and a value read from config is auditable in a way a constant is not. */
  region: string;
  userPoolId: string;
  userPoolAppId: string;
  /** Host only, no scheme and no trailing slash: the library interpolates it as
   *  `https://${userPoolDomain}/authorize`. */
  userPoolDomain: string;
  /** Kept equal to the app client's refresh-token validity. A cookie that outlives the refresh token
   *  produces a browser that believes it is signed in and a 302 loop on every navigation. */
  cookieExpirationDays: number;
}
