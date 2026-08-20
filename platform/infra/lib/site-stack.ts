// GRX Live — the delivery stack: one private bucket, one distribution, one behaviour, one gate.
//
// WHAT THIS STACK IS FOR
//
// The payload it serves is a derived, redaction-gated export of a validation study: 91 published
// verdicts, the sealed oracle text behind each one, a deficiency register the study keeps against
// itself, and 546 triaged document claims. It is not public. The audience is one person, by name, and
// widening it requires a second de-identification review that has not happened. So the interesting
// property of this stack is not what it serves — it is that there is no way to reach any of it without
// a Cognito session, and that the "no way" is structural rather than configured per path.
//
// THE ONE-BEHAVIOUR ARGUMENT
//
// CloudFront applies cache behaviours by path pattern, and a Lambda@Edge association belongs to a
// behaviour, not to a distribution. So every additional behaviour is an additional place where the
// auth function can be forgotten — and the natural reason to add one is caching, because the payload
// splits cleanly into `/v/<stamp>/*` (immutable forever) and `/current.json` (must be fresh).
//
// This stack has exactly ONE behaviour, the default, and the caching split is achieved with per-object
// `Cache-Control` set by the publisher at upload time, which CloudFront honours inside the cache
// policy's min/max TTL. The result is the same caching with none of the exposure, and a test asserts
// the behaviour count so that "just add a behaviour for /v/*" cannot pass review by accident.
//
// WHAT IS DELIBERATELY ABSENT
//
//   * No `errorResponses` mapping 403/404 to `index.html`. The SPA is a hash router, so it never needs
//     a rewrite, and `site/src/lib/data.ts` relies on a missing payload file producing a real 404: with
//     a rewrite it would receive `index.html` with a 200 and parse HTML as JSON, turning "the build did
//     not emit this file" into an unreadable syntax error.
//   * No WAF, and no geo restriction. Both cost money to duplicate a decision the edge function has
//     already made (an unauthenticated request never reaches the origin), and a geo restriction is a
//     way to lock the only user out of their own evidence from an airport.
//   * No public bucket policy of any kind. Reads reach the bucket only through the Origin Access
//     Control identity of this one distribution.

import {
  Aws,
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  Tags,
  aws_cloudfront as cloudfront,
  aws_cloudfront_origins as origins,
  aws_cognito as cognito,
  aws_iam as iam,
  aws_lambda as lambda,
  aws_lambda_nodejs as nodejs,
  aws_s3 as s3,
  aws_secretsmanager as secretsmanager,
  aws_ssm as ssm,
  type StackProps,
} from "aws-cdk-lib";
import type { Construct } from "constructs";
import * as path from "node:path";
import { CLIENT_SECRET_NAME, CONFIG_PARAMETER_NAME, EDGE_REGION } from "./edge/names.ts";

/** How long a browser stays signed in before it must complete the hosted-UI flow again. The cookie
 *  lifetime and the refresh-token validity are set from this ONE constant: a cookie that outlives its
 *  refresh token is a browser that believes it is signed in and 302-loops on every navigation. */
const SESSION_DAYS = 7;

/** The Cognito hosted-UI domain prefix, which must be unique across every AWS account on earth.
 *
 *  The suffix is a one-time random 32 bits (`secrets.token_hex(4)`), generated once and committed. It
 *  is NOT derived from the account id, and that is deliberate: a hash of a 12-digit account number is
 *  not a one-way function in practice — the whole input space is 10^12 candidates, which is minutes of
 *  brute force — so "we only committed a hash of the account" would be a false claim. Nor is it taken
 *  from `this.stackId`, because a token here would defeat the prefix's own synth-time validation and
 *  turn a typo into a deploy-time error from Cognito. Override with `-c domainPrefix=…` if it ever
 *  collides; the value is not a secret and appears in the browser's address bar during login. */
const DEFAULT_DOMAIN_PREFIX = "grx-live-84e6fcbf";

export class SiteStack extends Stack {
  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);
    Tags.of(this).add("project", "grx-live");

    // ---------------------------------------------------------------- the payload bucket
    //
    // No `bucketName`. CloudFormation then generates `<stack>-<logicalid><hash>-<random>`, which
    // carries no account id — the runner bucket in this same account is named
    // `…-<account_id>-<region>` by `runner/iam_policy.py`, and that name has to be treated as a
    // secret precisely because it embeds the account. A generated name has nothing to redact.
    const site = new s3.Bucket(this, "Payload", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      minimumTLSVersion: 1.2,
      // The only recovery from a bad `current.json` flip that has already been cached: the previous
      // version of that one object. Superseded payload versions are not evidence, so they expire.
      versioned: true,
      lifecycleRules: [
        { id: "expire-superseded-versions", noncurrentVersionExpiration: Duration.days(90) },
        { id: "abort-incomplete-uploads", abortIncompleteMultipartUploadAfter: Duration.days(7) },
      ],
      // RETAIN, and no `autoDeleteObjects`. `cdk destroy` must not be able to delete a published
      // payload, and `autoDeleteObjects` would install a Lambda whose whole job is to do exactly that.
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // Access logs. An invite-only evidence platform that cannot say which objects were fetched, when,
    // and from where is weaker than one that can, for a few cents a month. 90 days matches the runner
    // bucket's lifecycle: longer retention of request logs is a liability, not a safeguard.
    const logs = new s3.Bucket(this, "AccessLogs", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      // CloudFront standard logging to S3 delivers with an ACL, so the bucket cannot be
      // ownership-enforced. This is the narrowest setting that still accepts the delivery.
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      lifecycleRules: [{ id: "expire", expiration: Duration.days(90) }],
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // ---------------------------------------------------------------- the edge auth function
    //
    // The role is built by hand rather than left to the L2 for one reason: Lambda@Edge replicas are
    // created by CloudFront, not by Lambda, so the trust policy must name `edgelambda.amazonaws.com`
    // in addition to `lambda.amazonaws.com`. Omitting it produces a distribution that fails to create
    // with a message about the function, not about the trust policy.
    const edgeRole = new iam.Role(this, "EdgeAuthRole", {
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("lambda.amazonaws.com"),
        new iam.ServicePrincipal("edgelambda.amazonaws.com"),
      ),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    });

    // The two config reads are granted by ARN PATTERN, not by `parameter.grantRead(edgeRole)`.
    //
    // That is not a style choice, it breaks a CloudFormation cycle. The app client's callback URL is
    // the distribution's domain name, so client → distribution → edge function → role. If the role's
    // policy also referenced the parameter and the secret, and those reference the client, the graph
    // closes. Pattern ARNs let the role hold its permissions without naming any resource in this
    // stack, and the names are fixed constants anyway — they have to be, because a Lambda@Edge
    // function has no environment variables to receive them in.
    //
    // `Aws.ACCOUNT_ID` is the `AWS::AccountId` pseudo-parameter, so the synthesised template carries
    // `{"Ref": "AWS::AccountId"}` and not the twelve digits. A test asserts that.
    edgeRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["ssm:GetParameter"],
        resources: [
          `arn:${Aws.PARTITION}:ssm:${EDGE_REGION}:${Aws.ACCOUNT_ID}:parameter${CONFIG_PARAMETER_NAME}`,
        ],
      }),
    );
    edgeRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        // Secrets Manager appends a random six-character suffix to the ARN, so the resource cannot be
        // written exactly without referencing the resource. The wildcard is anchored on the full
        // secret name, which makes it one secret in practice.
        resources: [
          `arn:${Aws.PARTITION}:secretsmanager:${EDGE_REGION}:${Aws.ACCOUNT_ID}:secret:${CLIENT_SECRET_NAME}-*`,
        ],
      }),
    );

    const edgeFn = new nodejs.NodejsFunction(this, "EdgeAuth", {
      entry: path.join(__dirname, "edge", "auth.ts"),
      handler: "handler",
      runtime: lambda.Runtime.NODEJS_22_X,
      // x86_64 is not a preference: Lambda@Edge does not support arm64.
      architecture: lambda.Architecture.X86_64,
      // The viewer-request ceilings, stated rather than defaulted so that a future edit which needs
      // more of either fails here instead of at distribution-create time.
      memorySize: 128,
      timeout: Duration.seconds(5),
      role: edgeRole,
      description: "grx-live: Cognito check on every viewer request; fails closed",
      bundling: {
        minify: true,
        sourceMap: false,
        target: "node22",
        // Bundle EVERYTHING, including `@aws-sdk/*`. The default is to treat the SDK as provided by
        // the runtime; relying on that here would make the function's behaviour depend on which SDK
        // minor version the edge runtime happens to ship. 270 KB zipped against a 1 MB limit buys the
        // certainty cheaply.
        externalModules: [],
      },
      // NOTE, and it is checked by a test: no `environment`. Lambda@Edge rejects a function that has
      // environment variables, which is the entire reason `lib/edge/names.ts` exists.
    });

    // ---------------------------------------------------------------- the distribution
    const securityHeaders = new cloudfront.ResponseHeadersPolicy(this, "SecurityHeaders", {
      comment: "grx-live: same-origin only",
      securityHeadersBehavior: {
        contentSecurityPolicy: {
          // `style-src 'unsafe-inline'` is required and not laziness: the SPA sets layout with React
          // `style={{…}}` attributes throughout, and CSP blocks inline STYLE ATTRIBUTES under
          // `style-src` without it. `img-src data:` covers nothing today and is kept out.
          //
          // MEASURED, not reasoned: `platform/build/csp_preview.py` serves `site/dist` behind exactly
          // these header values and the SPA was walked in Chromium — all ten routes plus a case
          // drill-down, zero CSP violations in the console; the one stylesheet reported 94 readable
          // `cssRules` (a blocked sheet reports a SecurityError instead), 14 elements carried live
          // `style` attributes, and all 7 figure PNGs reported a non-zero `naturalWidth`. That
          // matters because a CSP which silently blocks a stylesheet renders an unstyled page, and a
          // synth test asserting the header's TEXT cannot tell the difference.
          contentSecurityPolicy: [
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self'",
            "font-src 'self'",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
          ].join("; "),
          override: true,
        },
        contentTypeOptions: { override: true },
        frameOptions: { frameOption: cloudfront.HeadersFrameOption.DENY, override: true },
        referrerPolicy: {
          referrerPolicy: cloudfront.HeadersReferrerPolicy.NO_REFERRER,
          override: true,
        },
        strictTransportSecurity: {
          accessControlMaxAge: Duration.days(365),
          includeSubdomains: true,
          override: true,
        },
      },
    });

    const distribution = new cloudfront.Distribution(this, "Site", {
      comment: "grx-live: private validation platform",
      defaultRootObject: "index.html",
      // Asia is included because that is where the only user is; South America and Oceania are not.
      priceClass: cloudfront.PriceClass.PRICE_CLASS_200,
      httpVersion: cloudfront.HttpVersion.HTTP2_AND_3,
      enableLogging: true,
      logBucket: logs,
      logIncludesCookies: false, // the session cookies ARE the bearer tokens
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(site),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        // CACHING_OPTIMIZED honours the origin's `Cache-Control` between a 1 s minimum and a 1 year
        // maximum, which is what lets the publisher express "immutable release" and "check every
        // minute" per object without a second behaviour. It also puts nothing but the URL in the cache
        // key — correct here, because the auth decision is made in viewer-request BEFORE the cache is
        // consulted, so every authenticated viewer may safely share one cached copy.
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        responseHeadersPolicy: securityHeaders,
        compress: true,
        edgeLambdas: [
          {
            functionVersion: edgeFn.currentVersion,
            eventType: cloudfront.LambdaEdgeEventType.VIEWER_REQUEST,
            includeBody: false,
          },
        ],
      },
      // No additionalBehaviors. See the header comment; a test asserts the count.
    });

    // ---------------------------------------------------------------- who may sign in
    const pool = new cognito.UserPool(this, "Users", {
      userPoolName: "grx-live",
      // This IS what "invite-only" means mechanically: there is no sign-up API surface, so the only
      // way an account comes into existence is an operator calling AdminCreateUser.
      selfSignUpEnabled: false,
      signInAliases: { email: true, username: false },
      standardAttributes: { email: { required: true, mutable: false } },
      passwordPolicy: {
        minLength: 16,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      mfa: cognito.Mfa.REQUIRED,
      // TOTP only. SMS second factors need an SNS role and are the weaker factor; there is no reason
      // to accept SIM-swap risk for a pool with one member who owns an authenticator app.
      mfaSecondFactor: { otp: true, sms: false, email: false },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      // ESSENTIALS rather than PLUS: PLUS adds threat protection at $0.05 per monthly active user,
      // which for a single-user pool buys adaptive-risk scoring over a population of one.
      featurePlan: cognito.FeaturePlan.ESSENTIALS,
      deletionProtection: true,
      // Deleting the pool deletes the only credential that can read the platform, and it cannot be
      // recreated with the same `sub` — every ledger entry attributing a run to a user would dangle.
      removalPolicy: RemovalPolicy.RETAIN,
    });

    const domainPrefix = (this.node.tryGetContext("domainPrefix") as string) ?? DEFAULT_DOMAIN_PREFIX;
    const domain = pool.addDomain("HostedUi", { cognitoDomain: { domainPrefix } });

    const client = pool.addClient("EdgeAuth", {
      userPoolClientName: "grx-live-edge",
      // See `lib/edge/names.ts` for why this client is confidential rather than public.
      generateSecret: true,
      supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
      // Every direct auth flow off. The hosted UI's authorization-code exchange does not use any of
      // them, so leaving `userSrp` on would expose a password-guessing surface that nothing needs.
      authFlows: {
        user: false,
        userPassword: false,
        userSrp: false,
        custom: false,
        adminUserPassword: false,
      },
      oAuth: {
        flows: { authorizationCodeGrant: true, implicitCodeGrant: false, clientCredentials: false },
        // `openid` is what makes an ID token exist, and the ID token is what the edge function
        // verifies. `email` so that a CloudWatch warning about a rejected token can be attributed.
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
        // Exactly the string `cognito-at-edge` builds as `redirect_uri`: `https://` + the Host header,
        // no path and no trailing slash (measured against the installed package). Cognito matches
        // callback URLs exactly, so a trailing slash here is a `redirect_mismatch` at login.
        callbackUrls: [`https://${distribution.distributionDomainName}`],
        logoutUrls: [`https://${distribution.distributionDomainName}`],
      },
      preventUserExistenceErrors: true,
      enableTokenRevocation: true,
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(SESSION_DAYS),
    });

    // ---------------------------------------------------------------- config the edge reads
    const config = new ssm.StringParameter(this, "EdgeAuthConfig", {
      parameterName: CONFIG_PARAMETER_NAME,
      description: "grx-live: non-secret Cognito config read by the Lambda@Edge auth function",
      tier: ssm.ParameterTier.STANDARD,
      // The hosted-UI host is assembled from the SAME constant passed to `cognitoDomain.domainPrefix`
      // rather than from `domain.baseUrl()`, which is a token carrying a `https://` prefix this field
      // must not contain. The explicit dependency below is what makes the ordering real.
      stringValue: this.toJsonString({
        region: EDGE_REGION,
        userPoolId: pool.userPoolId,
        userPoolAppId: client.userPoolClientId,
        userPoolDomain: `${domainPrefix}.auth.${EDGE_REGION}.amazoncognito.com`,
        cookieExpirationDays: SESSION_DAYS,
      }),
    });
    config.node.addDependency(domain);

    new secretsmanager.Secret(this, "EdgeAuthClientSecret", {
      secretName: CLIENT_SECRET_NAME,
      description: "grx-live: Cognito app client secret for the Lambda@Edge token exchange",
      secretStringValue: client.userPoolClientSecret,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // ---------------------------------------------------------------- what the operator needs
    new CfnOutput(this, "SiteUrl", { value: `https://${distribution.distributionDomainName}` });
    new CfnOutput(this, "PayloadBucket", { value: site.bucketName });
    new CfnOutput(this, "DistributionId", { value: distribution.distributionId });
    new CfnOutput(this, "UserPoolId", { value: pool.userPoolId });
    new CfnOutput(this, "HostedUiDomain", {
      value: `${domainPrefix}.auth.${EDGE_REGION}.amazoncognito.com`,
    });
    new CfnOutput(this, "InviteCommand", {
      description: "The ONLY way an account comes into existence in this pool",
      value:
        `aws cognito-idp admin-create-user --region ${EDGE_REGION} --user-pool-id ${pool.userPoolId}` +
        " --username <email> --user-attributes Name=email,Value=<email> Name=email_verified,Value=true" +
        " --desired-delivery-mediums EMAIL",
    });
  }
}
