#!/usr/bin/env python3
"""Publish this project to GitHub via the Git Data REST API (no local git needed).

This project's workflow never uses `git push`; publication goes through the
GitHub REST API (blobs -> tree -> commit -> ref -> PR), following the standing
6-step recipe. Two verification rules from that workflow are enforced here:

* every uploaded blob's returned SHA is compared against a locally computed
  `git hash-object` SHA — the API happily returns HTTP 201 for an accidentally
  empty upload, and the SHA comparison is the only thing that catches it;
* after the push, the remote tree is listed recursively and re-compared
  blob-by-blob, so "pushed" means "verified present with the right content",
  not "the API said 201".

Empty-repo handling: the target repo may have zero commits, in which case no
ref exists to branch from. Step 0 creates an initial commit on `main` through
the contents API, and the upload lands on a feature branch + PR on top of it.

Usage:
    python3 tools/api_push_pr.py <file-list> [--branch feat/initial-upload]

<file-list> is a text file of repo-relative paths, one per line, already vetted
by check_redaction.py plus a separate scan of extensions the gate skips.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

OWNER, REPO = "timwukp", "agentcore-guardrails-design-validation"
API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COMMIT_MSG = """feat: GRX validation platform — full project upload

Pre-registered empirical validation of agentcore_guardrails_best_practices_v1.2:
sealed pre-registration + verifier, claim extraction, corpora (synthetic
fixtures only), per-family experiment scripts (F1-F10), shared instrument libs,
and the distributable results/ record. evidence/ is local-only by policy (see
check_redaction.py); the redaction gate passed on every distributed file.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
"""

PR_TITLE = "feat: GRX validation platform — full project upload"

PR_BODY = """## Summary
- Full upload of the GRX validation platform: pre-registered empirical validation of `agentcore_guardrails_best_practices_v1.2.md` against live Bedrock AgentCore.
- Includes: sealed `PREREGISTRATION.yaml` + SHA-256 seal + `verify_prereg.py`, claim extraction (`claims/`), synthetic corpora, per-family experiments (`f1_config/` ... `f10_billing/`), shared instrument (`lib/`), distributable `results/`, deviation and exclusion registers.
- `evidence/` is deliberately absent: local-only audit archive by written policy (see `check_redaction.py` docstring and `.gitignore`).

## State at upload
- F4 (enforcement-mode truth table) smoke is green: `--n 3` exits 0, all 8 cells complete, F4-1..F4-5 TRUE, F4-6 FALSE (the pre-registered expected refutation — denials arrive as HTTP 200 + JSON-RPC -32002, not the documented 403). Full n=120 run is the next step; see `RECONNECT.md`.

## Redaction
- `check_redaction.py` PASSED on all scanned files (zero-file scan counts as failure by design).
- `.jsonl` / `.log` / `.sha256` files (outside the gate's extension list) were scanned separately: all identifier-shaped matches are synthetic fixtures or AWS-published documentation examples.
- The live account ID appears in 0 of the uploaded files (verified by direct scan of the exact upload list).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
"""


def token() -> str:
    t = subprocess.run(["gh", "auth", "token"], capture_output=True,
                       text=True, check=True).stdout.strip()
    if not t:
        raise SystemExit("gh auth token returned nothing")
    return t


TOKEN = None  # set in main()


def call(method: str, path: str, payload=None, ok404: bool = False):
    for attempt in range(5):
        req = urllib.request.Request(
            API + path, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": f"Bearer {TOKEN}",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "grx-push"})
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            # An EMPTY repo answers ref reads with 409 "Git Repository is empty.",
            # not 404 — measured on this repo's first push. Both mean "no ref".
            if e.code in (404, 409) and ok404:
                return None
            if e.code in (500, 502, 503) and attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(
                f"{method} {path} -> {e.code}: {e.read().decode()[:400]}") from e
    raise RuntimeError(f"{method} {path}: retries exhausted")


def git_sha(data: bytes) -> str:
    """SHA-1 of the git blob object, identical to `git hash-object`."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def upload(path: str) -> dict:
    data = open(os.path.join(ROOT, path), "rb").read()
    local = git_sha(data)
    remote = call("POST", f"/repos/{OWNER}/{REPO}/git/blobs",
                  {"content": base64.b64encode(data).decode(),
                   "encoding": "base64"})["sha"]
    if remote != local:
        raise RuntimeError(f"SHA MISMATCH {path}: local {local} != remote {remote}")
    mode = "100755" if os.access(os.path.join(ROOT, path), os.X_OK) else "100644"
    return {"path": path, "mode": mode, "type": "blob", "sha": remote}


def main() -> None:
    global TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("file_list")
    ap.add_argument("--branch", default="feat/initial-upload")
    args = ap.parse_args()
    TOKEN = token()

    files = sorted({l.strip() for l in open(args.file_list) if l.strip()})
    for extra in ("README.md", ".gitignore"):
        if extra not in files:
            files.append(extra)
    files = sorted(set(files))
    # A short list here means the find that built it read the wrong directory —
    # the same failure shape as a redaction scan that read zero files.
    if len(files) < 300:
        raise SystemExit(f"upload list suspiciously small: {len(files)}")

    # step 0: an empty repo has no refs; create the first commit via contents API
    main_ref = call("GET", f"/repos/{OWNER}/{REPO}/git/refs/heads/main", ok404=True)
    if main_ref is None:
        stub = ("# agentcore-guardrails-design-validation\n\n"
                "Initial commit; content arrives via PR.\n")
        r = call("PUT", f"/repos/{OWNER}/{REPO}/contents/README.md",
                 {"message": "chore: initialize main",
                  "content": base64.b64encode(stub.encode()).decode(),
                  "branch": "main"})
        base_sha = r["commit"]["sha"]
        print(f"initialized main at {base_sha}")
    else:
        base_sha = main_ref["object"]["sha"]
        print(f"main exists at {base_sha}")
    base_tree = call("GET", f"/repos/{OWNER}/{REPO}/git/commits/{base_sha}")["tree"]["sha"]

    # step 1: blobs, each verified against its locally computed git SHA
    entries = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(upload, files), 1):
            entries.append(res)
            if i % 50 == 0:
                print(f"  blobs {i}/{len(files)}")
    print(f"blobs done: {len(entries)}/{len(files)}, SHAs verified")

    # steps 2-4: tree -> commit -> branch ref
    tree_sha = call("POST", f"/repos/{OWNER}/{REPO}/git/trees",
                    {"base_tree": base_tree, "tree": entries})["sha"]
    commit_sha = call("POST", f"/repos/{OWNER}/{REPO}/git/commits",
                      {"message": COMMIT_MSG, "tree": tree_sha,
                       "parents": [base_sha]})["sha"]
    call("POST", f"/repos/{OWNER}/{REPO}/git/refs",
         {"ref": f"refs/heads/{args.branch}", "sha": commit_sha})
    print(f"branch {args.branch} -> {commit_sha}")

    # post-push: list the remote tree and re-compare every blob
    remote_tree = call("GET", f"/repos/{OWNER}/{REPO}/git/trees/{tree_sha}?recursive=1")
    if remote_tree.get("truncated"):
        raise SystemExit("tree listing truncated; verification incomplete")
    remote_by_path = {e["path"]: e["sha"]
                      for e in remote_tree["tree"] if e["type"] == "blob"}
    bad = [e["path"] for e in entries if remote_by_path.get(e["path"]) != e["sha"]]
    missing = [p for p in files if p not in remote_by_path]
    if bad or missing:
        raise SystemExit(f"tree verification FAILED: bad={bad[:5]} missing={missing[:5]}")
    print(f"tree verified: {len(files)} files, every SHA matches git hash-object")

    # step 5: the PR
    pr = call("POST", f"/repos/{OWNER}/{REPO}/pulls",
              {"title": PR_TITLE, "body": PR_BODY,
               "head": args.branch, "base": "main"})
    print("PR:", pr["html_url"])


if __name__ == "__main__":
    main()
