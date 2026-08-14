#!/usr/bin/env python3
"""Incremental push of one concern's worth of files, via the Git Data API.

`tools/api_push_pr.py` is the INITIAL-upload pusher: its commit message, PR title and PR body are
module constants describing the full-project upload, and `main()` refuses any list under 300 paths
because a short list there means the `find` that built it read the wrong directory. Both are right
for what it does and wrong for a 12-file follow-up, so this script imports its primitives —
`token`, `call`, `git_sha`, `upload` — and supplies its own message, branch and list. The
primitives are the part that must not be re-derived: `upload` is where the returned blob SHA is
compared against a locally computed `git hash-object`, and that comparison is the only thing that
catches an accidentally empty upload the API answered 201 to.

Deliberately NOT using `gh api` for the calls. On the 17-file PR #7 push, `gh api -X POST --input`
returned HTTP 400 on 9 of 17 blobs and a TLS handshake timeout on a 10th, in no size order, while
curl uploaded the same bytes first try — the fault was measured to be in gh's HTTP client at that
body size. `api_push_pr.call` uses urllib, which was never implicated.

One check is added that `api_push_pr.main()` does not do: after the merge, `main`'s tree is listed
again and every pushed path re-compared. A merged PR is not proof that content landed on the
default branch (`feedback_merged_pr_is_not_landed`) — the merge can succeed against a tree that
never held the blob, and the only way to know is to look at `main` afterwards.

It lives here rather than in /tmp because the last version of it did not survive: the earlier
`/tmp/api_push3.sh`, whose curl rewrite was the fix for the gh-client defect above, was gone by the
next session and had to be re-derived from a session log before this push could run. A tool whose
absence costs a re-derivation is a tool that belongs in the repo.

Usage:
    tools/api_push_incremental.py <file-list> --branch B --title T --body-file F \
        --message-file M [--merge]

Build the file list with `tools/repo_diff.py`, which writes one.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_push_pr as P  # noqa: E402  sibling module; ROOT is derived there the same way

R = f"/repos/{P.OWNER}/{P.REPO}"


def tree_of(commit_sha: str) -> dict:
    t = P.call("GET", f"{R}/git/commits/{commit_sha}")["tree"]["sha"]
    listing = P.call("GET", f"{R}/git/trees/{t}?recursive=1")
    if listing.get("truncated"):
        raise SystemExit("tree listing TRUNCATED — verification would pass by omission")
    return {e["path"]: e["sha"] for e in listing["tree"] if e["type"] == "blob"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file_list")
    ap.add_argument("--branch", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--message-file", required=True)
    ap.add_argument("--merge", action="store_true")
    a = ap.parse_args()
    P.TOKEN = P.token()

    files = sorted({l.strip() for l in open(a.file_list) if l.strip()})
    if not files:
        raise SystemExit("empty file list")
    missing = [f for f in files if not os.path.isfile(os.path.join(P.ROOT, f))]
    if missing:
        raise SystemExit(f"not on disk: {missing}")
    body = open(a.body_file).read()
    message = open(a.message_file).read()

    base_sha = P.call("GET", f"{R}/git/refs/heads/main")["object"]["sha"]
    base_tree = P.call("GET", f"{R}/git/commits/{base_sha}")["tree"]["sha"]
    print(f"base main {base_sha[:12]}   pushing {len(files)} file(s) on {a.branch}")

    entries = [P.upload(f) for f in files]          # each SHA-verified inside upload()
    print(f"  blobs {len(entries)}/{len(files)}, every SHA matches git hash-object")

    tree_sha = P.call("POST", f"{R}/git/trees",
                      {"base_tree": base_tree, "tree": entries})["sha"]
    commit_sha = P.call("POST", f"{R}/git/commits",
                        {"message": message, "tree": tree_sha, "parents": [base_sha]})["sha"]
    P.call("POST", f"{R}/git/refs", {"ref": f"refs/heads/{a.branch}", "sha": commit_sha})
    print(f"  branch {a.branch} -> {commit_sha[:12]}")

    on_branch = tree_of(commit_sha)
    bad = [e["path"] for e in entries if on_branch.get(e["path"]) != e["sha"]]
    if bad:
        raise SystemExit(f"branch tree verification FAILED: {bad[:5]}")
    print(f"  branch tree verified: {len(files)} path(s)")

    pr = P.call("POST", f"{R}/pulls",
                {"title": a.title, "body": body, "head": a.branch, "base": "main"})
    print(f"  PR #{pr['number']}: {pr['html_url']}")

    if not a.merge:
        return
    m = P.call("PUT", f"{R}/pulls/{pr['number']}/merge",
               {"merge_method": "merge",
                "commit_title": f"{a.title} (#{pr['number']})"})
    if not m.get("merged"):
        raise SystemExit(f"merge refused: {m}")
    print(f"  merged -> {m['sha'][:12]}")

    # the check api_push_pr.main() does not do: is it actually on main?
    on_main = tree_of(P.call("GET", f"{R}/git/refs/heads/main")["object"]["sha"])
    absent = [e["path"] for e in entries if on_main.get(e["path"]) != e["sha"]]
    if absent:
        raise SystemExit(f"MERGED BUT NOT LANDED on main: {absent[:5]}")
    print(f"  landed on main: {len(files)} path(s), SHAs re-verified")


if __name__ == "__main__":
    main()
