#!/usr/bin/env python3
"""The AgentCore Runtime deployment package, shared by the diagnostic and by F5-8.

WHY THIS IS ITS OWN MODULE
--------------------------
`f5_redteam/diag_runtime_code_artifact.py` established on 2026-08-14 that
`CreateAgentRuntime` accepts the `codeConfiguration` arm of the `agentRuntimeArtifact`
union --- an S3 zip plus `PYTHON_3_12` plus an entry point, with no container image, no ECR
repository and no arm64 builder. `f5_redteam/11_route_credential_reachability.py` then
publishes F5-8's sealed verdict through the same mechanism.

Those two need the SAME handler, byte for byte, and the reason is not tidiness. The
diagnostic is the artefact a reader consults to check that the producer's instrument was
sound before it was used to decide a case. If the producer carried its own copy of the
handler, the diagnostic would attest to a program that is not the one that produced the
verdict, and the divergence would be invisible --- both files would still say `/ping` and
`/invocations` and `GetCallerIdentity`. So there is one copy, here, and both import it.

WHAT THE HANDLER MEASURES
-------------------------
`GET /ping` and `POST /invocations` are the AgentCore HTTP service contract. `/invocations`
answers F5-8's question by probing every credential channel it can reach from inside the
microVM and then calling `sts:GetCallerIdentity` with a hand-rolled SigV4 signature.

The channel enumeration is the load-bearing part. The first version of this probe checked two
channels --- `AWS_*` environment variables and the container-credentials endpoint --- found
neither, and reported `credential_source: "none_found"`. Read as a measurement that would have
been F5-8 FALSE ("FALSE if credentials are unreachable"), refuting the premise under section
4.4 of the design document. It was a probe gap: the design document names the channel
explicitly --- claim C-s4-4-trow-009 says the credentials are readable "via the microVM
metadata service" --- and 169.254.169.254 had never been tried. It answers, with an IMDSv2
token, a role named `execution_role`, and credentials that STS accepts.

Every channel therefore appears in the output whether it was tried, skipped or refused, with
its status or its exception name, so that a future negative can be read against the list of
places somebody actually looked.

CREDENTIAL VALUES ARE NEVER EMITTED. Which mechanism the runtime is handed is the finding; the
secret itself is evidence of nothing and would have to be redacted out of the record anyway.
"""

from __future__ import annotations

import io
import zipfile

HANDLER = r'''"""Minimal AgentCore Runtime handler: /ping, /invocations. Standard library only.

/invocations answers the one question F5-8 asks --- what identity does code running inside a
runtime have --- by calling sts:GetCallerIdentity with a hand-rolled SigV4 signature. The
signature is hand-rolled rather than delegated to boto3 because boto3 is not known to be present
in the managed runtime and putting it in the zip would defeat the point of testing whether a
dependency-free zip deploys. boto3 is still *attempted* as one credential channel among eight:
if the runtime ships it, its resolution chain covers mechanisms this file has never heard of,
and that is worth knowing before concluding that credentials are unreachable.

Credential discovery is reported as a LIST OF NAMES, never values. Which mechanism the runtime
is handed is the finding; the secret itself is not evidence of anything and would have to be
redacted out of the record anyway.
"""
import datetime
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

CRED_ENV = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
            "AWS_CONTAINER_AUTHORIZATION_TOKEN", "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
            "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN", "AWS_REGION", "AWS_DEFAULT_REGION",
            "AWS_EXECUTION_ENV", "AWS_CONTAINER_CREDENTIALS_ENDPOINT")

# The link-local addresses. 169.254.169.254 is the one the design document names --- claim
# C-s4-4-trow-009 says the execution role's credentials are readable "via the microVM metadata
# service" --- so it is probed explicitly and its REACHABILITY is recorded separately from its
# response. Those are different findings: an endpoint that refuses the connection refutes the
# claim at the network layer, while an endpoint that answers 404 refutes only the path.
IMDS = "http://169.254.169.254"
ECS_LINK_LOCAL = "http://169.254.170.2"
SHARED_CRED_PATHS = ("/root/.aws/credentials", "/home/agent/.aws/credentials",
                     os.path.expanduser("~/.aws/credentials"), "/app/.aws/credentials")


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _http(url, method="GET", headers=None, data=None, timeout=4):
    """One request, never raising. Returns status plus body, or the exception name.

    The exception NAME and message matter as much as a status here: `Network is unreachable`,
    `Connection refused` and a read timeout are three different statements about whether a
    metadata service exists at that address, and collapsing them into a bare False is what
    turned the first run of this probe into an unpublishable `none_found`.
    """
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "body": r.read().decode("utf-8", "replace")[:4000]}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode("utf-8", "replace")[:1000]}
    except Exception as e:                                        # noqa: BLE001
        return {"status": None, "error": type(e).__name__ + ": " + str(e)[:200]}


def _from_json_creds(raw):
    """(ak, sk, token) out of the shape every AWS credential endpoint returns."""
    try:
        b = json.loads(raw)
    except Exception:                                             # noqa: BLE001
        return (None, None, None)
    return (b.get("AccessKeyId"), b.get("SecretAccessKey"), b.get("Token"))


def probe_channels():
    """Try EVERY credential channel, in order, and record what each one said.

    F5-8's FALSE branch --- "FALSE if credentials are unreachable" --- is publishable, and it
    would refute the premise under section 4.4. A negative is therefore only as good as the
    enumeration behind it, so the enumeration goes into the record: every channel appears in
    the output whether it was tried, skipped, or failed, and with what error. The first probe
    of this runtime checked two channels, reported `none_found`, and looked exactly like a
    finding.

    Returns (ak, sk, token, source, channels).
    """
    channels = []
    hit = (None, None, None, None)

    def note(name, **kw):
        channels.append(dict(channel=name, **kw))

    # 1. environment variables
    ak = os.environ.get("AWS_ACCESS_KEY_ID")
    note("environment", present=bool(ak))
    if ak and hit[0] is None:
        hit = (ak, os.environ.get("AWS_SECRET_ACCESS_KEY"),
               os.environ.get("AWS_SESSION_TOKEN"), "environment")

    # 2. the container credentials endpoint, from either env spelling
    uri = os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI")
    rel = os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    if rel and not uri:
        uri = ECS_LINK_LOCAL + rel
    if not uri:
        note("container_credentials_endpoint", skipped="neither FULL_URI nor RELATIVE_URI is set")
    else:
        tok = os.environ.get("AWS_CONTAINER_AUTHORIZATION_TOKEN")
        tf = os.environ.get("AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE")
        if not tok and tf and os.path.exists(tf):
            with open(tf) as fh:
                tok = fh.read().strip()
        r = _http(uri, headers={"Authorization": tok} if tok else None)
        note("container_credentials_endpoint", status=r.get("status"), error=r.get("error"),
             authorization_header_sent=bool(tok))
        a, s, t = _from_json_creds(r.get("body") or "")
        if a and hit[0] is None:
            hit = (a, s, t, "container_credentials_endpoint")

    # 3. IMDSv2 --- the channel the document names. Token first, as v2 requires.
    tk = _http(IMDS + "/latest/api/token", method="PUT", data=b"",
               headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"})
    note("imdsv2_token", status=tk.get("status"), error=tk.get("error"),
         address=IMDS, reachable=tk.get("status") is not None)
    imds_hdr = {}
    if tk.get("status") == 200 and tk.get("body"):
        imds_hdr = {"X-aws-ec2-metadata-token": tk["body"].strip()}

    # 4. IMDS role listing, with the v2 token if there is one and bare (v1) if there is not
    rl = _http(IMDS + "/latest/meta-data/iam/security-credentials/", headers=imds_hdr or None)
    note("imds_role_listing", status=rl.get("status"), error=rl.get("error"),
         used_v2_token=bool(imds_hdr), reachable=rl.get("status") is not None,
         roles=(rl.get("body") or "").split() if rl.get("status") == 200 else None)
    if rl.get("status") == 200 and (rl.get("body") or "").strip():
        role = (rl["body"] or "").strip().splitlines()[0].strip()
        cr = _http(IMDS + "/latest/meta-data/iam/security-credentials/" + role,
                   headers=imds_hdr or None)
        note("imds_role_credentials", status=cr.get("status"), error=cr.get("error"), role=role)
        a, s, t = _from_json_creds(cr.get("body") or "")
        if a and hit[0] is None:
            hit = (a, s, t, "imds_metadata_service")

    # 5. the ECS-style link-local address with no env var to tell us the path. Reachability
    #    only --- a 404 from a service that answers is a different fact from no service.
    el = _http(ECS_LINK_LOCAL + "/v2/credentials/")
    note("ecs_link_local_probe", status=el.get("status"), error=el.get("error"),
         address=ECS_LINK_LOCAL, reachable=el.get("status") is not None)

    # 6. web identity --- the file has to exist for AssumeRoleWithWebIdentity to be possible
    wif = os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")
    note("web_identity_token_file", env_set=bool(wif),
         file_exists=bool(wif and os.path.exists(wif)),
         role_arn_env_set=bool(os.environ.get("AWS_ROLE_ARN")))

    # 7. a shared credentials file on disk. Key NAMES are reported; no value ever is.
    for p in dict.fromkeys(SHARED_CRED_PATHS):
        if not os.path.exists(p):
            note("shared_credentials_file", path=p, exists=False)
            continue
        keys = []
        try:
            with open(p) as fh:
                for ln in fh:
                    if "=" in ln and not ln.strip().startswith("#"):
                        keys.append(ln.split("=", 1)[0].strip())
        except Exception as e:                                    # noqa: BLE001
            note("shared_credentials_file", path=p, exists=True,
                 error=type(e).__name__ + ": " + str(e)[:120])
            continue
        note("shared_credentials_file", path=p, exists=True, key_names=sorted(set(keys)))

    # 8. boto3's own resolution chain, if the managed runtime ships boto3 at all. This is the
    #    authoritative channel when it is available: it covers SSO, process credentials and
    #    every future mechanism, none of which the seven probes above know about.
    try:
        import boto3                                              # noqa: PLC0415
        import botocore                                           # noqa: PLC0415
        sess = boto3.Session()
        c = sess.get_credentials()
        frozen = c.get_frozen_credentials() if c else None
        note("boto3_default_chain", importable=True,
             boto3_version=boto3.__version__, botocore_version=botocore.__version__,
             resolved=bool(frozen), method=getattr(c, "method", None) if c else None)
        if frozen and hit[0] is None:
            hit = (frozen.access_key, frozen.secret_key, frozen.token,
                   "boto3_default_chain:" + str(getattr(c, "method", "unknown")))
    except ImportError as e:
        note("boto3_default_chain", importable=False, error=str(e)[:160])
    except Exception as e:                                        # noqa: BLE001
        note("boto3_default_chain", importable=True, resolved=False,
             error=type(e).__name__ + ": " + str(e)[:200])

    ak, sk, tok, source = hit
    return (ak, sk, tok, source or "none_found", channels)


def caller_identity():
    ak, sk, tok, source, channels = probe_channels()
    out = {"credential_source": source,
           "channels_probed": channels,
           "env_names_present": sorted(n for n in CRED_ENV if os.environ.get(n)),
           "all_aws_env_names": sorted(k for k in os.environ if k.startswith("AWS_"))}
    if not ak or not sk:
        out["error"] = ("no usable credentials were discoverable from inside the runtime "
                        "after probing every channel in `channels_probed`")
        return out
    host, service, region = "sts.amazonaws.com", "sts", "us-east-1"
    body = "Action=GetCallerIdentity&Version=2011-06-15"
    now = datetime.datetime.now(datetime.timezone.utc)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body.encode()).hexdigest()
    signed_headers = "content-type;host;x-amz-date"
    canonical_headers = ("content-type:application/x-www-form-urlencoded; charset=utf-8\n"
                         "host:" + host + "\nx-amz-date:" + amzdate + "\n")
    if tok:
        signed_headers += ";x-amz-security-token"
        canonical_headers += "x-amz-security-token:" + tok + "\n"
        # canonical headers must be sorted by name; security-token sorts after x-amz-date
    canonical = "\n".join(["POST", "/", "", canonical_headers, signed_headers, payload_hash])
    scope = "/".join([datestamp, region, service, "aws4_request"])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amzdate, scope,
                         hashlib.sha256(canonical.encode()).hexdigest()])
    k = _sign(("AWS4" + sk).encode("utf-8"), datestamp)
    k = _sign(k, region)
    k = _sign(k, service)
    k = _sign(k, "aws4_request")
    sig = hmac.new(k, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
               "X-Amz-Date": amzdate,
               "Authorization": ("AWS4-HMAC-SHA256 Credential=" + ak + "/" + scope +
                                 ", SignedHeaders=" + signed_headers + ", Signature=" + sig)}
    if tok:
        headers["X-Amz-Security-Token"] = tok
    req = urllib.request.Request("https://" + host + "/", data=body.encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            out["sts_http_status"] = r.status
            out["sts_response"] = r.read().decode("utf-8", "replace")[:2000]
    except urllib.error.HTTPError as e:
        out["sts_http_status"] = e.code
        out["sts_response"] = e.read().decode("utf-8", "replace")[:2000]
    except Exception as e:                                    # noqa: BLE001
        out["sts_error"] = type(e).__name__ + ": " + str(e)[:300]
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/") in ("/ping", ""):
            self._json(200, {"status": "Healthy"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/invocations":
            self._json(404, {"error": "not found"})
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        self._json(200, {"probe": "grx-runtime-code-artifact", "identity": caller_identity()})

    def log_message(self, fmt, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), H).serve_forever()
'''


def build_zip() -> bytes:
    """The deployment package: one file, no dependencies.

    `external_attr` is set explicitly to 0o644. The AgentCore docs make this a requirement
    ("AgentCore Runtime needs 644 permissions for non-executable files"), and `writestr`
    defaults to 0o600 — readable only by the owner. A 0o600 entry is exactly the kind of
    failure that would come back as an opaque CREATE_FAILED and get attributed to the union
    arm instead of to the four bytes that caused it.

    HANDLER is compiled before it is zipped for the same reason. It is a string literal in this
    file, so nothing type-checks or byte-compiles it on the way past, and a syntax error in it
    would surface as a runtime that never answers `/ping` — which is indistinguishable, from the
    outside, from the union arm being unsupported. That is the whole question this diagnostic
    exists to answer, so it must not be answerable by a typo.
    """
    compile(HANDLER, "main.py", "exec")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("main.py", date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        z.writestr(info, HANDLER)
    return buf.getvalue()


def execution_policy(account: str, bucket: str, prefix: str, region: str) -> dict:
    """Least privilege for what this handler actually does, plus the code read.

    Composed from the "direct deploy execution role" in the AgentCore permissions page, minus
    every grant this handler cannot use: no `bedrock:InvokeModel` (it calls no model), no
    `cloudwatch:PutMetricData` (it emits no metric). `sts:GetCallerIdentity` needs no grant at
    all — it is unauthenticated with respect to IAM — so its presence here would be decoration
    that made the probe look like it depended on a permission it does not have.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "ReadTheCodeArtifact", "Effect": "Allow",
             "Action": ["s3:GetObject"],
             "Resource": [f"arn:aws:s3:::{bucket}/{prefix}*"]},
            {"Sid": "ListTheCodeBucket", "Effect": "Allow",
             "Action": ["s3:ListBucket"], "Resource": [f"arn:aws:s3:::{bucket}"],
             "Condition": {"StringLike": {"s3:prefix": [f"{prefix}*"]}}},
            {"Sid": "Logs", "Effect": "Allow",
             "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
                        "logs:DescribeLogStreams", "logs:DescribeLogGroups"],
             "Resource": [f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/*",
                          f"arn:aws:logs:{region}:{account}:log-group:*"]},
            {"Sid": "Xray", "Effect": "Allow",
             "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords",
                        "xray:GetSamplingRules", "xray:GetSamplingTargets"],
             "Resource": ["*"]},
        ],
    }


def service_trust(account: str) -> dict:
    """The trust policy an AgentCore Runtime execution role needs.

    `aws:SourceAccount` is not decoration. Without it the role is assumable by the AgentCore
    service principal on behalf of ANY account, which is the confused-deputy shape; this
    mirrors `infra/01_iam.py:service_trust`, which carries the same condition for the same
    reason. It is duplicated rather than imported because `infra/` provisions the sealed
    testbed and a case script must not be able to reach into it.
    """
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"aws:SourceAccount": account}},
        }],
    }
