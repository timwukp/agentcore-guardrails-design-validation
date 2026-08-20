// The CDK app. Two assertions before anything is synthesised, both of which turn a silent wrong
// deployment into a refusal.
//
// REGION. A Lambda@Edge function must live in us-east-1 — CloudFront replicates it from there and from
// nowhere else. Synthesising this stack into another region produces a template that deploys and a
// distribution that fails to associate the function, with an error that names neither the region nor
// the reason. Pinning the region in code rather than trusting `AWS_REGION` also means the value cannot
// change because a shell had a different profile exported.
//
// ACCOUNT. The account comes from the deploy environment (`CDK_DEFAULT_ACCOUNT`, i.e. whatever
// credentials are in front of the CLI) and is never written down here. This project treats its own
// twelve-digit account id as something to redact from every distributable file, so a literal in
// `bin/` — or in a committed `cdk.context.json` — would be the leak the redaction gate exists to catch.
// Refusing to synthesise without credentials is the point: an unresolved account silently becomes an
// environment-agnostic stack, and environment-agnostic stacks cannot use `fromLookup` or a region-aware
// assertion.

import { App } from "aws-cdk-lib";
import { SiteStack } from "../lib/site-stack.ts";

const REQUIRED_REGION = "us-east-1";

const account = process.env.CDK_DEFAULT_ACCOUNT;
if (!account) {
  throw new Error(
    "CDK_DEFAULT_ACCOUNT is unset — the CDK CLI sets it from the credentials it resolved, so this " +
      "almost always means there are no working credentials. Refusing to synthesise an " +
      "environment-agnostic stack: the region assertion below would not run.",
  );
}

// `CDK_DEFAULT_REGION` is whatever the profile says; it is checked, not used, so that a misconfigured
// shell produces a message about the region instead of a distribution that will not create.
const region = process.env.CDK_DEFAULT_REGION ?? REQUIRED_REGION;
if (region !== REQUIRED_REGION) {
  throw new Error(
    `Lambda@Edge functions exist only in ${REQUIRED_REGION}, but the resolved region is ${region}. ` +
      `Deploy with AWS_REGION=${REQUIRED_REGION} (or a profile whose region is ${REQUIRED_REGION}).`,
  );
}

const app = new App();
new SiteStack(app, "GrxLive", {
  env: { account, region: REQUIRED_REGION },
  description: "GRX Live — private, invite-only delivery of the AgentCore validation payload",
});
