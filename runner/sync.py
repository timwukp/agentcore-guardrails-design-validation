#!/usr/bin/env python3
"""Move the working tree to the runner, and the runner's output back — via S3, never via GitHub.

Why S3 in both directions
-------------------------
The repo is private, so a clone on the instance would need a GitHub credential, and an instance
reachable by anyone with `ssm:StartSession` is the wrong place to keep one. So the code goes up as
a tarball and the output comes back as objects, and the instance never holds a token.

The return direction is the one that matters. `pull` writes into a STAGING directory, never over
`results/` or `state.json`, because:

  * the redaction gate and the full suite run on the laptop, and an artifact that has overwritten
    the published one before the gate has seen it has already defeated the gate;
  * `state.json` is the ledger, and two machines appending to it is a merge, not a copy — the
    staging copy is what a merge reads;
  * `git checkout -- file` is never used in this repo (the working tree runs ahead of git HEAD, so
    checkout destroys work), which means an overwrite here is not recoverable.

What goes UP and what does not
------------------------------
Up, in `push`: source, tests, corpora, `PREREGISTRATION.yaml`, `claims/`, `results/`,
`state.json`. The published results and the ledger have to travel, or a resumed run on the
instance re-does work that is already done and re-bills it.

Not up: `.git` (the instance has no reason to hold history), the venvs (built on the instance from
`runner/requirements.txt`), and `runner/.state/`.

Up, in `push-evidence`, as a SEPARATE object
--------------------------------------------
The first version of this file left `evidence/` out on the reasoning that it is a local-only audit
archive and the instance should build its own. Measured on the first instance: **156 failures and
170 errors** in the offline suite, every one of them a test that reads the evidence tree — 26 test
modules do. A runner that cannot run the project's own gate is half a runner, so that reasoning
was wrong and this is the correction.

"Local-only" is a rule about **distribution**: the tree is gitignored, excluded from the redaction
gate by directory, and never published, because its whole purpose is that a full ARN and request id
can be quoted to AWS Support. Copying it to a private, encrypted, public-access-blocked bucket in
the *same account that produced it*, read by an instance in that account, does not cross that
boundary — it is the same trust domain, not a wider one. It is a separate object and a separate
subcommand because it is 178 MB across 26,620 files and almost never changes, while `push` is run
every time a script is edited.

The return direction stays as it was: the instance publishes the evidence it produces under a
timestamped prefix, so nothing overwrites and no run id has two authors.

Up, in `push-inputs`, as a THIRD object
--------------------------------------
Two of the suite's inputs are not in the repo and never could be: the **document under test** and
the **PII source corpus** both live outside it, and both are named by `PREREGISTRATION.yaml`. A
validation project whose subject is a document has to be handed the document. See
`external_inputs()` for how the set is derived rather than listed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import time
from fnmatch import fnmatch
from pathlib import Path

import boto3
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runner"))
import provision as PV           # noqa: E402

STAGING = ROOT / "runner" / ".state" / "incoming"
PREREG = ROOT / "PREREGISTRATION.yaml"

# What the tarball leaves out is DERIVED from `.gitignore`, plus `.git` itself.
#
# The first version of this was a hand-written tuple, and it shipped 213 MB on the first push:
# `f1_config/.wheel_cache/` holds fifteen botocore wheels for F1's SDK-version matrix, is
# gitignored, and was not in my list. That is the two-lists-one-claim failure — a second
# enumeration of "what is not part of the distributable tree" drifts from the first the moment
# either changes. Reading `.gitignore` means the tarball and the repo cannot disagree, and a new
# ignored directory is excluded without anyone remembering to edit this file.
#
# `.git` is added because it is the one thing git does not ignore and the instance has no use for:
# history is not needed to run a case, and the push path is the Git Data API from the laptop.
# `runner/.state` is already gitignored and so needs no entry here.
EXTRA_EXCLUDE = (".git",)

# A ceiling on the packaged size, asserted at push time. 213 MB uploaded in ~2 minutes and would
# have gone unnoticed; 60 MB is comfortably above the real tree (~30 MB) and far below any
# accidental cache. The floor on file count below guards the opposite error.
MAX_TARBALL_BYTES = 60 * 1024 * 1024


def exclusions() -> tuple[str, ...]:
    """Patterns from `.gitignore`, plus `EXTRA_EXCLUDE`.

    Trailing slashes are dropped and the result is matched with `fnmatch`, which covers every form
    this repo's `.gitignore` uses: bare names (`.DS_Store`), directories (`evidence/`), globs
    (`.venv-*/`) and paths (`f1_config/.wheel_cache/`). Negation (`!`) and anchored patterns
    (`/name`) are NOT gitignore-equivalent under this reader, so they are refused rather than
    quietly mis-handled — an exclusion this function silently failed to honour would surface as a
    200 MB upload, not as an error.
    """
    out = list(EXTRA_EXCLUDE)
    unparsed = []
    for raw in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("!", "/")):
            unparsed.append(line)
            continue
        out.append(line.rstrip("/"))
    if unparsed:
        raise SystemExit(
            "runner/sync.py cannot honour these .gitignore patterns:\n"
            + "\n".join(f"  {p}" for p in unparsed)
            + "\nEither simplify the pattern or extend exclusions() to handle it.")
    return tuple(out)


def external_inputs() -> tuple[dict, ...]:
    """Every path `PREREGISTRATION.yaml` names OUTSIDE the repo, with where it has to land.

    Measured on the first instance's second suite run: of 47 non-green tests, 21 errors were one
    cause — `claims/tests/test_corpus_gate.py` refusing to run because the PII corpus is not at
    `/opt/grx/claude-code-enterprise-bedrock/tests/pii-corpus` — and most of the rest were another:
    the redaction gate and `verify_prereg.py` unable to find `agentcore_guardrails_best_practices_
    v1.2.md`. Neither is a code defect and neither could ever have travelled in `push`, because
    neither is in the tree. A validation project whose subject is a document has to be handed the
    document.

    The set is DERIVED, by walking the sealed pre-registration for any string value that begins
    `~/` or `../`. That is not a heuristic dressed up as a rule: those two prefixes are exactly the
    two ways this file can name something it does not contain, and they are resolved the same way by
    the code under test —

      * `~/…` against `Path.home()`, which is what `claims/check_coverage.py:40` and
        `verify_prereg.py:984` do, so the destination is the HOME of whoever runs the suite;
      * `../…` against the repo root, so the destination is beside the repo.

    A hand-written pair here would be a second enumeration of "what this suite needs from outside",
    and the day the pre-registration named a third input the runner would be silently short one
    while still reporting a green push (feedback_prose_is_not_verified, feedback_two_numbers_two_
    claims). An empty result is an error rather than a no-op: it would mean the walk stopped
    matching, not that the suite became self-contained.

    A declared `sha256` is CHECKED before upload, not recorded after. The document's hash is the
    thing that pins `claims/triage.csv`'s line mapping, so shipping a document that is not the
    sealed one would give the instance a different subject while every result still said v1.2.
    """
    pr = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    found: list[tuple[str, str, dict]] = []

    def walk(node, where: tuple[str, ...]) -> None:
        items = (node.items() if isinstance(node, dict)
                 else enumerate(node) if isinstance(node, list) else ())
        for key, val in items:
            at = where + (str(key) if isinstance(node, dict) else f"[{key}]",)
            if isinstance(val, str) and val.startswith(("~/", "../")):
                found.append((".".join(at), val, node if isinstance(node, dict) else {}))
            walk(val, at)

    walk(pr, ())
    if not found:
        raise SystemExit(f"{PREREG.name} names no external path; either the suite became "
                         "self-contained or external_inputs() stopped matching — check which")

    out = []
    for yaml_at, raw, sibling in found:
        if raw.startswith("~/"):
            kind, src, dest = "home", Path.home() / raw[2:], str(Path(raw[2:]).parent)
        else:
            kind, src, dest = "repo-parent", ROOT.parent / raw[3:], str(Path(raw[3:]).parent)
        if not src.exists():
            raise SystemExit(
                f"{yaml_at} = {raw} resolves to {src}, which does not exist here.\n"
                "This is an input the pre-registration requires; find it before pushing, because "
                "the instance cannot be given what this machine does not have.")
        sha = sibling.get("sha256") if src.is_file() else None
        if sha:
            got = hashlib.sha256(src.read_bytes()).hexdigest()
            if got != sha:
                raise SystemExit(
                    f"{src.name} is not the sealed artifact.\n  declared {sha}\n  measured {got}\n"
                    f"{PREREG.name} pins this hash; shipping a different file would give the runner "
                    "a different subject while every result still claimed this one.")
        out.append({"yaml_at": yaml_at, "declared": raw, "kind": kind, "src": src,
                    "dest_parent_rel": "" if dest == "." else dest, "sha256": sha})
    return tuple(out)


def cmd_push_inputs(args) -> int:
    """Upload the external inputs as their own object. See `external_inputs()` for why they exist.

    A separate object and subcommand for the same reason `push-evidence` is: these change on a
    different clock from the source. The corpus is 52 KB and has not moved since the audit that
    produced DEV-P0-6; the document is the sealed subject and moves only at a version bump.

    Archive layout is the destination, so the shell helper that unpacks it holds no path of its own
    to drift: members live under `inputs/home/…` and `inputs/repo-parent/…`, and `grx-inputs`
    extracts each prefix to the corresponding root.
    """
    st = _state()
    inputs = external_inputs()
    tgz = ROOT / "runner" / ".state" / "inputs.tar.gz"
    tgz.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    manifest = []
    with tarfile.open(tgz, "w:gz") as tar:
        for spec in inputs:
            base = f"inputs/{spec['kind']}"
            if spec["dest_parent_rel"]:
                base += "/" + spec["dest_parent_rel"]
            if spec["src"].is_file():
                tar.add(spec["src"], arcname=f"{base}/{spec['src'].name}")
                n += 1
            else:
                for path in sorted(spec["src"].rglob("*")):
                    if not path.is_file() or path.name == ".DS_Store":
                        continue
                    tar.add(path, arcname=f"{base}/{spec['src'].name}/"
                                          f"{path.relative_to(spec['src'])}")
                    n += 1
            manifest.append({k: (str(v) if isinstance(v, Path) else v)
                             for k, v in spec.items() if k != "src"})
    if not n:
        raise SystemExit("packaged 0 input files; the declared paths resolved to empty trees")
    digest = hashlib.sha256(tgz.read_bytes()).hexdigest()
    s3 = boto3.client("s3", region_name=st["region"])
    key = "code/inputs.tar.gz"
    s3.upload_file(str(tgz), st["bucket"], key,
                   ExtraArgs={"Metadata": {"sha256": digest, "files": str(n)}})
    head = s3.head_object(Bucket=st["bucket"], Key=key)
    if head["Metadata"].get("sha256") != digest or head["ContentLength"] != tgz.stat().st_size:
        raise SystemExit("uploaded object does not match what was packaged")
    for spec in manifest:
        print(f"  {spec['kind']:<12} {spec['declared']}"
              + (f"  sha256 {spec['sha256'][:16]}" if spec["sha256"] else ""))
    print(f"pushed {n} input files, {tgz.stat().st_size:,} bytes, sha256 {digest[:16]}")
    print("on the instance: grx-inputs")
    return 0


def _state() -> dict:
    """The resolved ids, plus a check that the instance is still the identity we scoped.

    The profile check is here rather than in each subcommand because EVERY subcommand either makes
    the instance touch S3 or runs code that will. An account-wide SSM association re-attaches a
    different, much broader profile to every instance hourly — `PV.ensure_instance_profile()` has
    the CloudTrail evidence and the reason it matters — so "the state file exists" is not the same
    question as "the instance can still read its own bucket". Reading the state without reading the
    identity is how a `403 Forbidden` came to look like a broken bucket policy.

    Repairs and SAYS SO, rather than repairing quietly: how often the clobber wins is the number
    that decides whether this transport should stop depending on the instance role at all.
    """
    if not PV.STATE_PATH.is_file():
        raise SystemExit(f"{PV.STATE_PATH.relative_to(ROOT)} is missing — "
                         "run runner/provision.py first")
    st = json.loads(PV.STATE_PATH.read_text(encoding="utf-8"))
    ec2 = boto3.client("ec2", region_name=st["region"])
    if repaired := PV.ensure_instance_profile(ec2, st["instance_id"]):
        print(f"! {repaired}")
    return st


def _skip(rel: str, patterns: tuple[str, ...]) -> bool:
    """True when `rel` is inside, or is, something excluded.

    Matched per path COMPONENT as well as on the whole relative path, because a gitignore entry
    like `evidence/` excludes the directory wherever it appears while `f1_config/.wheel_cache/`
    names one place.
    """
    parts = Path(rel).parts
    for pat in patterns:
        if "/" in pat:
            if rel == pat or rel.startswith(pat + "/"):
                return True
        elif any(fnmatch(part, pat) for part in parts):
            return True
    return False


def _run_on_instance(st: dict, script: str, *, timeout_s: int = 900) -> tuple[int, str, str]:
    """Run one shell script on the live instance and return `(rc, stdout, stderr)`.

    A separate helper rather than a fourth copy of the send/poll loop, and it returns the rc
    instead of printing it: the callers here decide a *verdict* from it, and a helper that
    swallowed the rc would make every verdict optimistic.
    """
    ssm = boto3.client("ssm", region_name=st["region"])
    cid = ssm.send_command(
        InstanceIds=[st["instance_id"]], DocumentName="AWS-RunShellScript",
        TimeoutSeconds=600,
        Parameters={"commands": [script],
                    "executionTimeout": [str(timeout_s)]})["Command"]["CommandId"]
    for _ in range(timeout_s // 5):
        time.sleep(5)
        try:
            inv = ssm.get_command_invocation(CommandId=cid, InstanceId=st["instance_id"])
        except ssm.exceptions.InvocationDoesNotExist:
            # The invocation is not registered the instant `send_command` returns. Treated as
            # "not yet" rather than as a failure -- and NOT as a success.
            continue
        if inv["Status"] in ("Pending", "InProgress", "Delayed"):
            continue
        rc = 0 if inv["Status"] == "Success" else (inv.get("ResponseCode") or 1)
        return rc, inv["StandardOutputContent"] or "", inv["StandardErrorContent"] or ""
    return 124, "", f"timed out after {timeout_s}s waiting for {cid}"


def cmd_push(args) -> int:
    st = _state()
    tgz = ROOT / "runner" / ".state" / "grx-validation.tar.gz"
    tgz.parent.mkdir(parents=True, exist_ok=True)
    patterns = exclusions()
    n = 0
    manifest: list[str] = []
    with tarfile.open(tgz, "w:gz") as tar:
        for path in sorted(ROOT.rglob("*")):
            rel = str(path.relative_to(ROOT))
            if _skip(rel, patterns) or not path.is_file():
                continue
            tar.add(path, arcname=f"grx-validation/{rel}")
            manifest.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}")
            n += 1
    # Both bounds. A tarball that read almost nothing extracts successfully and leaves the
    # instance with a repo that cannot run anything; one that read too much ships a 213 MB wheel
    # cache without complaint. Neither error announces itself, so both are asserted.
    if n < 100:
        raise SystemExit(f"only {n} files packaged; the exclusion list is over-matching")
    if tgz.stat().st_size > MAX_TARBALL_BYTES:
        big = sorted(((p.stat().st_size, str(p.relative_to(ROOT))) for p in ROOT.rglob("*")
                      if p.is_file() and not _skip(str(p.relative_to(ROOT)), patterns)),
                     reverse=True)[:5]
        raise SystemExit(
            f"packaged {tgz.stat().st_size:,} bytes, over the {MAX_TARBALL_BYTES:,} ceiling. "
            "Largest included files:\n"
            + "\n".join(f"  {s:>12,}  {p}" for s, p in big))
    digest = hashlib.sha256(tgz.read_bytes()).hexdigest()
    s3 = boto3.client("s3", region_name=st["region"])
    key = "code/grx-validation.tar.gz"
    s3.put_object(Bucket=st["bucket"], Key=key, Body=tgz.read_bytes(),
                  Metadata={"sha256": digest, "files": str(n)})
    # Verified by reading the object's own metadata back, not by trusting the 200: an upload that
    # reports success and stored nothing is a measured failure mode of this project
    # (feedback_verify_uploaded_blob_sha).
    head = s3.head_object(Bucket=st["bucket"], Key=key)
    if head["Metadata"].get("sha256") != digest or head["ContentLength"] != tgz.stat().st_size:
        raise SystemExit("uploaded object does not match what was packaged")
    print(f"pushed {n} files, {tgz.stat().st_size:,} bytes, sha256 {digest[:16]}")

    # ---------------------------------------------------------------- refresh, then VERIFY it
    # This block exists because of a measured failure, not as belt-and-braces. Until now `push`
    # uploaded the object and printed `on the instance: grx-refresh` as a HINT, leaving the
    # refresh to the operator. On 2026-08-12 the hint was read as a report: the push said
    # "pushed 526 files" and the instance kept the tree it already had, so a detached job ran
    # against code from four hours earlier. It survived only by luck -- the file it needed was
    # ABSENT, so python died with Errno 2 in the first second. Had the file merely been STALE the
    # job would have run to completion and published results attributed to code that never ran
    # them (`feedback_build_reported_success_built_nothing`, `feedback_no_deploy_path_no_component`).
    #
    # So the refresh is now part of `push`, and `push` does not report success until it has
    # confirmed the extracted tree file-by-file. `sha256sum -c` is the confirmation: it fails on
    # a content mismatch AND on a file the tarball carried that the tree does not have, which is
    # exactly the two ways a half-refresh presents.
    #
    # What this proves and what it does not: every one of the `n` packaged files is present on the
    # instance with the bytes packaged here. It does NOT prove the tree has nothing EXTRA -- `tar
    # -xzf` overwrites and never deletes, so a file deleted locally survives on the instance until
    # a rebootstrap. That residual is stated rather than implied by silence.
    man = ROOT / "runner" / ".state" / "manifest.txt"
    man.write_text("\n".join(manifest) + "\n", encoding="utf-8")
    s3.put_object(Bucket=st["bucket"], Key="code/MANIFEST.txt", Body=man.read_bytes())
    rc, out, err = _run_on_instance(st, f"""
set -uo pipefail
grx-refresh || {{ echo "grx-refresh FAILED with $?"; exit 9; }}
aws s3 cp s3://{st['bucket']}/code/MANIFEST.txt /opt/grx/tmp/manifest.txt \
    --region {st['region']} --quiet || exit 8
cd /opt/grx/grx-validation || exit 7
lines=$(wc -l < /opt/grx/tmp/manifest.txt)
# A zero-line manifest would make `sha256sum -c` verify nothing and is an ERROR, not a pass
# (feedback_zero_file_scan_is_error). The count is compared to what was packaged, so a manifest
# that arrived truncated cannot read as clean either (feedback_two_numbers_two_claims).
if [ "$lines" -ne {n} ]; then
    echo "manifest has $lines line(s), but {n} file(s) were packaged"; exit 6
fi
sha256sum -c --quiet /opt/grx/tmp/manifest.txt || exit 5
echo "VERIFIED $lines file(s) on the instance"
""")
    print((out or "").rstrip() or "(no output from the instance)")
    if err.strip():
        print("--- stderr from the instance", file=sys.stderr)
        print(err.rstrip()[:4000], file=sys.stderr)
    if rc != 0 or "VERIFIED" not in out:
        print(f"\nPUSH NOT CONFIRMED (rc={rc}). The instance is NOT known to be running this "
              f"tree; do not launch a job against it.", file=sys.stderr)
        return rc or 1
    return 0


def cmd_push_evidence(args) -> int:
    """Package `evidence/` and upload it as its own object. See the module docstring on why.

    Deliberately NOT folded into `push`: 178 MB across 26,620 files takes minutes to pack and the
    tree changes only when a live case runs, while `push` is run after every script edit. Two
    subcommands means the fast path stays fast, and the slow one is a decision rather than a tax.
    """
    st = _state()
    src = ROOT / "evidence"
    if not src.is_dir():
        raise SystemExit("evidence/ does not exist here; nothing to push")
    tgz = ROOT / "runner" / ".state" / "evidence.tar.gz"
    tgz.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(tgz, "w:gz") as tar:
        for path in sorted(src.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            tar.add(path, arcname=f"evidence/{path.relative_to(src)}")
            n += 1
    if n < 1_000:
        raise SystemExit(f"only {n} evidence files packaged; the tree looks truncated")
    digest = hashlib.sha256(tgz.read_bytes()).hexdigest()
    s3 = boto3.client("s3", region_name=st["region"])
    key = "code/evidence.tar.gz"
    s3.upload_file(str(tgz), st["bucket"], key,
                   ExtraArgs={"Metadata": {"sha256": digest, "files": str(n)}})
    head = s3.head_object(Bucket=st["bucket"], Key=key)
    if head["Metadata"].get("sha256") != digest or head["ContentLength"] != tgz.stat().st_size:
        raise SystemExit("uploaded object does not match what was packaged")
    print(f"pushed {n:,} evidence files, {tgz.stat().st_size:,} bytes, sha256 {digest[:16]}")
    print("on the instance: grx-evidence")
    return 0


def cmd_rebootstrap(args) -> int:
    """Re-run `runner/bootstrap.sh` on the LIVE instance, rendered by `provision.render_bootstrap`.

    User data runs once, at first boot. Everything bootstrap.sh installs that is not the repo
    itself — the `/usr/local/bin/grx-*` helpers, the scratch directory, the shell env — is
    therefore frozen at whatever the script said the day the instance launched. Measured: the
    running instance had no `grx-evidence` at all, because that helper was written after it booted,
    and the first attempt to pull the evidence archive by hand died on the tmpfs the later version
    of the script is what avoids. That is embedded-asset staleness in shell form: an edit that only
    reaches the NEXT instance is an edit that is not on the machine doing the work.

    So this ships the script through SSM instead of re-imaging. Every step in it is idempotent —
    `dnf install` on an installed package, `install -d` on an existing directory, `cat >` over a
    helper, and the `.bashrc` block is marker-guarded — so the safe move on any doubt is to run
    this rather than to reason about which half of the script already happened.
    """
    st = _state()
    script = PV.render_bootstrap(st["bucket"])
    ssm = boto3.client("ssm", region_name=st["region"])
    # Sent as a single command so the script runs as ONE program: it uses `set -uo pipefail`, an
    # `exec > >(tee)` redirect and shell functions, none of which survive being split into separate
    # SSM `commands` entries, each of which is its own shell.
    cid = ssm.send_command(
        InstanceIds=[st["instance_id"]], DocumentName="AWS-RunShellScript",
        TimeoutSeconds=600,
        Parameters={"commands": [script], "executionTimeout": ["1800"]})["Command"]["CommandId"]
    print(f"re-running bootstrap.sh ({len(script):,} bytes) as {cid}")
    for _ in range(120):
        time.sleep(5)
        inv = ssm.get_command_invocation(CommandId=cid, InstanceId=st["instance_id"])
        if inv["Status"] in ("Pending", "InProgress", "Delayed"):
            continue
        print((inv["StandardOutputContent"] or "").rstrip())
        err = (inv["StandardErrorContent"] or "").rstrip()
        if err:
            print("--- stderr", file=sys.stderr)
            print(err, file=sys.stderr)
        return 0 if inv["Status"] == "Success" else (inv.get("ResponseCode") or 1)
    print("timed out waiting for the bootstrap; check /var/log/grx-bootstrap.log on the instance")
    return 1


def cmd_pull(args) -> int:
    st = _state()
    s3 = boto3.client("s3", region_name=st["region"])
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=st["bucket"], Prefix="out/", Delimiter="/")
    stamps = sorted(p["Prefix"].split("/")[1]
                    for page in pages for p in page.get("CommonPrefixes", []))
    if not stamps:
        print("nothing published yet — run grx-publish on the instance")
        return 1
    stamp = args.stamp or stamps[-1]
    if stamp not in stamps:
        raise SystemExit(f"{stamp} not among {stamps}")
    dest = STAGING / stamp
    dest.mkdir(parents=True, exist_ok=True)
    n = size = 0
    for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=st["bucket"], Prefix=f"out/{stamp}/"):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(f"out/{stamp}/"):]
            if not rel:
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(st["bucket"], obj["Key"], str(out))
            n += 1
            size += obj["Size"]
    print(f"pulled {n} objects, {size:,} bytes -> {dest.relative_to(ROOT)}")
    print(f"published stamps available: {', '.join(stamps)}")
    print("NOT applied. Diff against results/ and state.json, then merge deliberately; "
          "the gate and the suite run here, not there.")
    return 0


def cmd_status(args) -> int:
    """Whether the bootstrap finished, asked of the instance rather than inferred from uptime."""
    st = _state()
    ssm = boto3.client("ssm", region_name=st["region"])
    online = ssm.describe_instance_information(Filters=[
        {"Key": "InstanceIds", "Values": [st["instance_id"]]}])["InstanceInformationList"]
    if not online:
        print(f"{st['instance_id']}: not registered with SSM yet")
        return 1
    info = online[0]
    print(f"{st['instance_id']}: SSM {info['PingStatus']}, "
          f"agent {info.get('AgentVersion')}, platform {info.get('PlatformName')} "
          f"{info.get('PlatformVersion')}")
    cmd = ssm.send_command(
        InstanceIds=[st["instance_id"]], DocumentName="AWS-RunShellScript",
        Parameters={"commands": [
            "cat /opt/grx/bootstrap.done 2>/dev/null || echo NOT-DONE",
            "/opt/grx/grx-validation/.venv-oracle/bin/python -V 2>/dev/null || echo NO-VENV",
            "cat /opt/grx/last-publish 2>/dev/null || echo NEVER-PUBLISHED",
            "df -h --output=avail /opt/grx | tail -1",
        ]})["Command"]["CommandId"]
    for _ in range(40):
        time.sleep(3)
        inv = ssm.get_command_invocation(CommandId=cmd, InstanceId=st["instance_id"])
        if inv["Status"] not in ("Pending", "InProgress", "Delayed"):
            print(inv["StandardOutputContent"].rstrip() or inv["StandardErrorContent"].rstrip())
            return 0 if inv["Status"] == "Success" else 1
    print("timed out waiting for the SSM command")
    return 1


def cmd_session(args) -> int:
    st = _state()
    print(f"aws ssm start-session --target {st['instance_id']} --region {st['region']}")
    return subprocess.call(["aws", "ssm", "start-session", "--target", st["instance_id"],
                            "--region", st["region"]])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("push", help="package the working tree and upload it").set_defaults(f=cmd_push)
    sub.add_parser("push-evidence",
                   help="upload evidence/ as its own object (slow; only when it has changed)"
                   ).set_defaults(f=cmd_push_evidence)
    sub.add_parser("push-inputs",
                   help="upload the inputs PREREGISTRATION.yaml names outside the repo "
                        "(document under test, PII corpus)").set_defaults(f=cmd_push_inputs)
    sub.add_parser("rebootstrap",
                   help="re-run bootstrap.sh on the live instance (helpers, scratch dirs, env)"
                   ).set_defaults(f=cmd_rebootstrap)
    p = sub.add_parser("pull", help="download published output into a staging dir")
    p.add_argument("--stamp", help="which publish to pull (default: the latest)")
    p.set_defaults(f=cmd_pull)
    sub.add_parser("status", help="ask the instance whether it is ready").set_defaults(f=cmd_status)
    sub.add_parser("session", help="open an SSM shell").set_defaults(f=cmd_session)
    args = ap.parse_args()
    return args.f(args)


if __name__ == "__main__":
    raise SystemExit(main())
