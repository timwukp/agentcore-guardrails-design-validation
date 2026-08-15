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
    tools/api_push_incremental.py [<file-list>] --branch B --title T --body-file F \
        --message-file M [--delete-list D] [--merge]

Build the file list with `tools/repo_diff.py`, which writes one. `--delete-list` removes paths from
the tree and may be used with no file list at all — a deletion-only commit is a legitimate change.
Deletions are never inferred from `repo_diff.py`'s remote-only list: a path can be missing locally
because it was deleted, or because it was never on this machine, and those want opposite actions.
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
    ap.add_argument("file_list", nargs="?")
    ap.add_argument("--branch", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--message-file", required=True)
    ap.add_argument("--delete-list", help="paths to REMOVE from the tree, one per line")
    ap.add_argument("--merge", action="store_true")
    a = ap.parse_args()
    P.TOKEN = P.token()

    files = sorted({l.strip() for l in open(a.file_list) if l.strip()}) if a.file_list else []
    missing = [f for f in files if not os.path.isfile(os.path.join(P.ROOT, f))]
    if missing:
        raise SystemExit(f"not on disk: {missing}")

    # Deletions. `repo_diff.py` reports remote-only paths but deliberately refuses to act on them,
    # because a path absent locally may be absent because it was never on this machine — so the
    # list is always passed in explicitly, never inferred.
    #
    # The guard is the important part: a path that STILL EXISTS locally is not a deletion, it is an
    # accident, and the Git Data API would carry it out silently. `sha: None` serialises to JSON
    # null, which is how a tree entry says "remove this"; there is no error if the path was never
    # there, so without this check a typo removes nothing and reports success.
    deletes = sorted({l.strip() for l in open(a.delete_list) if l.strip()}) if a.delete_list else []
    still_here = [d for d in deletes if os.path.exists(os.path.join(P.ROOT, d))]
    if still_here:
        raise SystemExit(f"REFUSING to delete paths that still exist locally: {still_here}")
    if not files and not deletes:
        raise SystemExit("nothing to push and nothing to delete")
    body = open(a.body_file).read()
    message = open(a.message_file).read()

    base_sha = P.call("GET", f"{R}/git/refs/heads/main")["object"]["sha"]
    base_tree = P.call("GET", f"{R}/git/commits/{base_sha}")["tree"]["sha"]
    print(f"base main {base_sha[:12]}   pushing {len(files)} file(s), "
          f"deleting {len(deletes)} on {a.branch}")

    # A deletion of a path the base tree does not carry is a silent no-op, so check first: the
    # request would succeed, the verification below would pass (the path is absent either way), and
    # the only thing that would be wrong is our belief about what the repo held.
    on_base = tree_of(base_sha)
    phantom = [d for d in deletes if d not in on_base]
    if phantom:
        raise SystemExit(f"not on main, nothing to delete: {phantom}")

    entries = [P.upload(f) for f in files]          # each SHA-verified inside upload()
    print(f"  blobs {len(entries)}/{len(files)}, every SHA matches git hash-object")

    # `sha: None` -> JSON null, the Git Data API's spelling of "remove this path from base_tree".
    tree = entries + [{"path": d, "mode": "100644", "type": "blob", "sha": None} for d in deletes]
    tree_sha = P.call("POST", f"{R}/git/trees",
                      {"base_tree": base_tree, "tree": tree})["sha"]
    commit_sha = P.call("POST", f"{R}/git/commits",
                        {"message": message, "tree": tree_sha, "parents": [base_sha]})["sha"]
    P.call("POST", f"{R}/git/refs", {"ref": f"refs/heads/{a.branch}", "sha": commit_sha})
    print(f"  branch {a.branch} -> {commit_sha[:12]}")

    on_branch = tree_of(commit_sha)
    bad = [e["path"] for e in entries if on_branch.get(e["path"]) != e["sha"]]
    left = [d for d in deletes if d in on_branch]
    if bad or left:
        raise SystemExit(f"branch tree verification FAILED: added={bad[:5]} not_deleted={left[:5]}")
    print(f"  branch tree verified: {len(files)} present, {len(deletes)} absent")

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
    survived = [d for d in deletes if d in on_main]
    if absent or survived:
        raise SystemExit(
            f"MERGED BUT NOT LANDED on main: missing={absent[:5]} still_present={survived[:5]}")
    print(f"  landed on main: {len(files)} present, {len(deletes)} removed, SHAs re-verified")


if __name__ == "__main__":
    main()
