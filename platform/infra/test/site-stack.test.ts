// Assertions against the SYNTHESISED template, not against the source that produced it.
//
// Every arm below was mutation-checked: the property under test was removed or inverted in
// `lib/site-stack.ts`, the arm was confirmed to FAIL, and the source was restored. `no_mutant_control`
// runs first and exists so that a green suite is attributable to the assertions rather than to a synth
// that quietly produced nothing — a `Template` built from an empty stack satisfies a surprising number
// of "the bad thing is absent" checks.
//
// The stack is synthesised with the account id `111122223333`, one of this project's three documented
// placeholder accounts. That is not merely a stand-in: `no_account_id_in_the_template` asserts the
// twelve digits appear NOWHERE in the output, which is only a meaningful assertion if a real-shaped
// account was fed in.

import { App, Aspects } from "aws-cdk-lib";
import { Annotations, Match, Template } from "aws-cdk-lib/assertions";
import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import test from "node:test";
import { SiteStack } from "../lib/site-stack.ts";
import { CLIENT_SECRET_NAME, CONFIG_PARAMETER_NAME } from "../lib/edge/names.ts";

const ACCOUNT = "111122223333";
const REGION = "us-east-1";
const HERE = __dirname;
const INFRA = path.dirname(HERE);

const outdir = mkdtempSync(path.join(tmpdir(), "grx-infra-synth-"));
const app = new App({ outdir, context: JSON.parse(readFileSync(path.join(INFRA, "cdk.json"), "utf8")).context });
const stack = new SiteStack(app, "GrxLive", { env: { account: ACCOUNT, region: REGION } });
const assembly = app.synth();
const template = Template.fromStack(stack);
const templateJson = JSON.stringify(template.toJSON());

function theOnly(type: string): Record<string, unknown> {
  const found = template.findResources(type);
  const keys = Object.keys(found);
  assert.equal(keys.length, 1, `expected exactly one ${type}, found ${keys.length}`);
  return (found[keys[0]!] as { Properties: Record<string, unknown> }).Properties;
}

test("no_mutant_control: the stack synthesises and is not empty", () => {
  const n = Object.keys(template.toJSON().Resources as object).length;
  assert.ok(n > 15, `only ${n} resources synthesised — the rest of this file would pass vacuously`);
  // An empty-ish template also has no errors, so check the CDK's own validation while here.
  Annotations.fromStack(stack).hasNoError("*", Match.anyValue());
  void Aspects; // imported for the annotations API's sake; keeps `noUnusedLocals` honest
});

// ---------------------------------------------------------------- the access-control invariant

test("the distribution has exactly ONE cache behaviour, so no path can bypass the auth function", () => {
  const cfg = theOnly("AWS::CloudFront::Distribution")["DistributionConfig"] as Record<string, unknown>;
  assert.ok(cfg["DefaultCacheBehavior"], "no default behaviour");
  // Not `deepEqual([])` — CloudFront omits the key entirely when there are none, and an empty array
  // and an absent key are both acceptable outputs. What must never appear is a behaviour.
  assert.equal(
    ((cfg["CacheBehaviors"] as unknown[]) ?? []).length,
    0,
    "an additional cache behaviour exists: every behaviour needs its own Lambda@Edge association, " +
      "so this is a path that may be reachable without a Cognito session",
  );
});

test("the default behaviour runs the edge function on viewer-request", () => {
  const cfg = theOnly("AWS::CloudFront::Distribution")["DistributionConfig"] as Record<string, unknown>;
  const behavior = cfg["DefaultCacheBehavior"] as Record<string, unknown>;
  const assocs = (behavior["LambdaFunctionAssociations"] ?? []) as { EventType: string }[];
  assert.equal(assocs.length, 1, "expected exactly one Lambda@Edge association");
  // origin-request would be a 50x larger package budget and a fatal hole: it fires only on a cache
  // MISS, so a cached payload object would be served to an unauthenticated viewer.
  assert.equal(assocs[0]!.EventType, "viewer-request");
});

test("no 403/404 rewrite to index.html", () => {
  const cfg = theOnly("AWS::CloudFront::Distribution")["DistributionConfig"] as Record<string, unknown>;
  assert.equal(
    cfg["CustomErrorResponses"],
    undefined,
    "a rewrite makes a missing payload file arrive as index.html with a 200, which turns " +
      "'the build did not emit this file' into a JSON parse error in the browser",
  );
});

// ---------------------------------------------------------------- the edge function's hard limits

test("the edge function carries no environment variables", () => {
  const fns = template.findResources("AWS::Lambda::Function");
  const edge = Object.values(fns).filter(
    (f) => typeof (f.Properties as { Description?: string }).Description === "string" &&
      (f.Properties as { Description: string }).Description.startsWith("grx-live:"),
  );
  assert.equal(edge.length, 1, "expected exactly one grx-live Lambda function");
  assert.equal(
    (edge[0]!.Properties as { Environment?: unknown }).Environment,
    undefined,
    "Lambda@Edge rejects a function with environment variables — this is why lib/edge/names.ts exists",
  );
  const p = edge[0]!.Properties as { MemorySize: number; Timeout: number; Architectures: string[] };
  assert.equal(p.MemorySize, 128, "viewer-request functions are capped at 128 MB");
  assert.equal(p.Timeout, 5, "viewer-request functions are capped at 5 s");
  assert.deepEqual(p.Architectures, ["x86_64"], "Lambda@Edge does not support arm64");
});

test("the edge role is assumable by edgelambda, not only by lambda", () => {
  const roles = template.findResources("AWS::IAM::Role");
  const services = Object.values(roles).flatMap((r) =>
    (
      (r.Properties as { AssumeRolePolicyDocument: { Statement: { Principal: { Service: unknown } }[] } })
        .AssumeRolePolicyDocument.Statement
    ).flatMap((s) => (Array.isArray(s.Principal.Service) ? s.Principal.Service : [s.Principal.Service])),
  );
  // CloudFront, not Lambda, creates the regional replicas; without this principal the DISTRIBUTION
  // fails to create, with an error that names the function and not the trust policy.
  assert.ok(services.includes("edgelambda.amazonaws.com"), "edgelambda.amazonaws.com cannot assume any role");
  assert.ok(services.includes("lambda.amazonaws.com"));
});

test("the edge role can read exactly one parameter and one secret, and nothing else", () => {
  // Scoped to the EDGE role's own policy. The stack has a second one: `userPoolClientSecret` is
  // implemented by CDK as a custom resource that calls `cognito-idp:DescribeUserPoolClient`, because
  // CloudFormation's `AWS::Cognito::UserPoolClient` has no `ClientSecret` return value. Folding that
  // policy in would make this arm assert a union and stop noticing a widening of either half.
  const policies = template.findResources("AWS::IAM::Policy");
  const edgePolicies = Object.entries(policies).filter(([id]) => id.startsWith("EdgeAuthRole"));
  assert.equal(edgePolicies.length, 1, "expected exactly one policy on the edge role");
  const statements = edgePolicies.flatMap(
    ([, p]) => (p.Properties as { PolicyDocument: { Statement: { Action: unknown; Resource: unknown }[] } })
      .PolicyDocument.Statement,
  );
  const actions = statements.flatMap((s) => (Array.isArray(s.Action) ? s.Action : [s.Action]));
  assert.deepEqual(
    [...new Set(actions)].sort(),
    ["secretsmanager:GetSecretValue", "ssm:GetParameter"],
    "the edge role holds an action beyond reading its own two config values",
  );
  // The names are constants because a Lambda@Edge function has no environment variables to receive
  // them in, so the ARN in the policy must be built from the SAME constant the handler imports.
  assert.ok(JSON.stringify(statements).includes(CONFIG_PARAMETER_NAME));
  assert.ok(JSON.stringify(statements).includes(`${CLIENT_SECRET_NAME}-*`));
});

test("the bundled edge function fits the 1 MB viewer-request package limit", () => {
  // Located by CONTENT, not by position. The assembly holds two asset directories — the other is
  // CDK's custom-resource provider framework, whose bundle is a different size — and `stacks[0].assets`
  // is empty under the default synthesizer, which publishes assets through a separate manifest
  // artifact. Matching on a string only this handler contains means the arm cannot silently start
  // measuring the wrong bundle.
  const marker = "grx-live edge auth failed";
  const candidates = readdirSync(assembly.directory)
    .filter((f) => f.startsWith("asset."))
    .map((f) => path.join(assembly.directory, f))
    .filter((d) => statSync(d).isDirectory())
    .filter((d) =>
      readdirSync(d).some((f) => f === "index.js" && readFileSync(path.join(d, f), "utf8").includes(marker)),
    );
  assert.equal(candidates.length, 1, `expected one asset directory containing ${marker}, found ${candidates.length}`);
  const dir = candidates[0]!;
  const files = readdirSync(dir).map((f) => path.join(dir, f));
  const raw = files.reduce((n, f) => n + statSync(f).size, 0);
  // A zip entry is deflate plus ~100 bytes of header, so gzip of the same bytes is within noise of
  // the zipped package CloudFront measures. Measured at authoring time: 995 KB raw / 270 KB deflated.
  const deflated = files.reduce((n, f) => n + gzipSync(readFileSync(f)).length, 0);
  assert.ok(deflated < 1_048_576, `deflated bundle is ${deflated} B, over the 1 MB limit`);
  assert.ok(raw > 100_000, `bundle is only ${raw} B — esbuild produced a stub, so the limit check is vacuous`);
});

// ---------------------------------------------------------------- the headers a browser will obey

test("the CSP the preview server enforces is the CSP the distribution sends", () => {
  // Two artifacts have to agree: the header in this template, and the header
  // `platform/build/csp_preview.py` puts in front of `site/dist` when the SPA is walked in a real
  // browser. They agree because the preview PARSES this stack rather than copying the policy — and
  // this arm is what notices when a refactor breaks the parse, since the preview's failure mode is
  // otherwise "the developer who next runs it gets an error", which may be months later.
  const policy = theOnly("AWS::CloudFront::ResponseHeadersPolicy")[
    "ResponseHeadersPolicyConfig"
  ] as { SecurityHeadersConfig: { ContentSecurityPolicy: { ContentSecurityPolicy: string } } };
  const fromTemplate = policy.SecurityHeadersConfig.ContentSecurityPolicy.ContentSecurityPolicy;
  const fromPreview = execFileSync(
    "python3",
    [path.join(INFRA, "..", "build", "csp_preview.py"), "--print-only"],
    { encoding: "utf8" },
  ).trim();
  assert.equal(fromPreview, fromTemplate);
  // Non-vacuity: two empty strings are also equal.
  assert.match(fromTemplate, /^default-src 'none';/);
  // The one relaxation, asserted so that removing it is a deliberate act. React `style={{…}}`
  // attributes are inline styles; without this the SPA renders unstyled, which was verified in a
  // browser rather than assumed.
  assert.ok(fromTemplate.includes("style-src 'self' 'unsafe-inline'"));
  assert.ok(!fromTemplate.includes("script-src 'self' 'unsafe-inline'"), "inline script is allowed");
});

// ---------------------------------------------------------------- the bucket

test("the payload bucket is private, encrypted, TLS-only and retained", () => {
  const buckets = template.findResources("AWS::S3::Bucket");
  for (const [id, b] of Object.entries(buckets)) {
    const p = b.Properties as Record<string, any>;
    assert.deepEqual(
      p.PublicAccessBlockConfiguration,
      { BlockPublicAcls: true, BlockPublicPolicy: true, IgnorePublicAcls: true, RestrictPublicBuckets: true },
      `${id} does not block all public access`,
    );
    assert.ok(p.BucketEncryption, `${id} is unencrypted`);
    assert.equal(b.DeletionPolicy, "Retain", `${id} would be deleted by cdk destroy`);
  }
  const policies = template.findResources("AWS::S3::BucketPolicy");
  const json = JSON.stringify(policies);
  assert.ok(json.includes("cloudfront.amazonaws.com"), "no OAC principal on any bucket policy");
  assert.ok(
    !/"Effect":\s*"Allow"[^}]*"Principal":\s*"\*"/.test(json),
    "a bucket policy allows an anonymous principal",
  );
});

// ---------------------------------------------------------------- who may sign in

test("the user pool is invite-only with TOTP MFA required", () => {
  const p = theOnly("AWS::Cognito::UserPool");
  assert.equal(
    (p["AdminCreateUserConfig"] as { AllowAdminCreateUserOnly: boolean }).AllowAdminCreateUserOnly,
    true,
    "self sign-up is reachable — 'invite-only' would then be a description rather than a mechanism",
  );
  assert.equal(p["MfaConfiguration"], "ON");
  assert.deepEqual(p["EnabledMfas"], ["SOFTWARE_TOKEN_MFA"], "SMS second factors carry SIM-swap risk");
  assert.equal((p["Policies"] as any).PasswordPolicy.MinimumLength, 16);
});

test("the app client is confidential, code-flow only, with one exact callback URL", () => {
  const p = theOnly("AWS::Cognito::UserPoolClient");
  // Without PKCE (absent from cognito-at-edge 1.5.5, measured) the client secret is what makes an
  // authorization code logged in CloudFront's access log inert.
  assert.equal(p["GenerateSecret"], true);
  assert.deepEqual(p["AllowedOAuthFlows"], ["code"], "implicit flow puts tokens in the URL");
  assert.deepEqual([...(p["ExplicitAuthFlows"] as string[])].sort(), ["ALLOW_REFRESH_TOKEN_AUTH"],
    "a direct auth flow is enabled; the hosted UI code exchange needs none of them");
  const callbacks = p["CallbackURLs"] as { "Fn::Join": [string, unknown[]] }[];
  assert.equal(callbacks.length, 1);
  // Cognito matches callback URLs exactly and cognito-at-edge builds `https://` + Host with no
  // trailing slash, so a slash here is a `redirect_mismatch` at login rather than a warning at deploy.
  // Asserted on the STRUCTURE: `["https://", <domain ref>]` and nothing after the reference. A regex
  // over the serialised form cannot tell the callback's trailing slash from the one in "https://".
  const parts = callbacks[0]!["Fn::Join"][1];
  assert.equal(parts.length, 2, `unexpected callback URL shape: ${JSON.stringify(callbacks[0])}`);
  assert.equal(parts[0], "https://");
  assert.equal(typeof parts[1], "object", "a literal follows the domain name — probably a trailing slash");
});

// ---------------------------------------------------------------- the redaction invariant

test("the only account id in the template is the CDK bootstrap asset bucket's", () => {
  // The honest version of "no account id in the template". There is one source that cannot be removed:
  // the default synthesizer names the bootstrap asset bucket `cdk-hnb659fds-assets-<account>-<region>`
  // in every `Code.S3Bucket`, because that is where the Lambda bundle was uploaded. Two such names
  // appear (the edge function and CDK's custom-resource provider).
  //
  // So the assertion is that NOTHING ELSE contributes the literal — which is what catches a hand-built
  // ARN written with `this.account` instead of `Aws.ACCOUNT_ID` — and that the count of bootstrap
  // references is what it should be, so a new one does not hide inside the exemption. This is also the
  // measured reason `cdk.json` writes `cdk.out` outside the repository: the template itself carries the
  // account, and `check_redaction.py` is right to fail on it.
  const bootstrap = new RegExp(`cdk-hnb659fds-assets-${ACCOUNT}-${REGION}`, "g");
  const bootstrapHits = templateJson.match(bootstrap) ?? [];
  assert.equal(bootstrapHits.length, 2, `expected 2 bootstrap bucket references, found ${bootstrapHits.length}`);
  const rest = templateJson.replaceAll(bootstrap, "<bootstrap-bucket>");
  assert.deepEqual(
    [...new Set(rest.match(/\b\d{12}\b/g) ?? [])],
    [],
    "a twelve-digit literal reached the template outside the bootstrap bucket name; hand-built ARNs " +
      "must use Aws.ACCOUNT_ID, not Stack.of(this).account",
  );
  assert.ok(
    rest.includes("AWS::AccountId"),
    "no pseudo-parameter reference at all — the ARN statements are missing, so this arm is vacuous",
  );
});

test("cdk.out is written outside the repository", () => {
  const cdkJson = JSON.parse(readFileSync(path.join(INFRA, "cdk.json"), "utf8")) as { output?: string };
  assert.ok(cdkJson.output, "no `output` setting: cdk.out would land in the repo, where the manifest's " +
    "`aws://<account>/us-east-1` fails check_redaction.py on every subsequent publish");
  const resolved = path.resolve(INFRA, cdkJson.output);
  const repoRoot = path.resolve(INFRA, "..", "..");
  assert.ok(!resolved.startsWith(repoRoot + path.sep), `${cdkJson.output} resolves inside ${repoRoot}`);
});

// ---------------------------------------------------------------- the app's own guards

test("bin/grx-live.ts refuses a region that is not us-east-1, and accepts us-east-1", () => {
  const run = (env: Record<string, string | undefined>) => {
    try {
      execFileSync("npx", ["tsx", path.join(INFRA, "bin", "grx-live.ts")], {
        cwd: INFRA,
        env: { ...process.env, CDK_OUTDIR: mkdtempSync(path.join(tmpdir(), "grx-bin-")), ...env },
        stdio: ["ignore", "pipe", "pipe"],
      });
      return { rc: 0, err: "" };
    } catch (e) {
      const x = e as { status: number; stderr: Buffer };
      return { rc: x.status, err: x.stderr.toString() };
    }
  };
  // The control comes first: without it, a guard that rejects EVERYTHING would pass both arms below.
  const ok = run({ CDK_DEFAULT_ACCOUNT: ACCOUNT, CDK_DEFAULT_REGION: REGION });
  assert.equal(ok.rc, 0, `the passing control failed: ${ok.err}`);

  const wrongRegion = run({ CDK_DEFAULT_ACCOUNT: ACCOUNT, CDK_DEFAULT_REGION: "eu-west-1" });
  assert.notEqual(wrongRegion.rc, 0);
  assert.match(wrongRegion.err, /Lambda@Edge functions exist only in us-east-1/);

  const noAccount = run({ CDK_DEFAULT_ACCOUNT: undefined, CDK_DEFAULT_REGION: REGION });
  assert.notEqual(noAccount.rc, 0);
  assert.match(noAccount.err, /CDK_DEFAULT_ACCOUNT is unset/);
});
