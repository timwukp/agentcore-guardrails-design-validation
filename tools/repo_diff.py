#!/usr/bin/env python3
"""What the GitHub repo is missing, computed rather than remembered.

The working tree is not a git checkout — this project has never used `git push`, so there is no
local index to diff against. The comparison is therefore: local `git hash-object` SHA vs the SHA
the remote tree reports for the same path. That is the same comparison `tools/api_push_pr.py`
makes to decide a blob landed, which is why `git_sha` and `call` are IMPORTED from it rather than
re-derived here: a diff computed by one hash function and verified by another would agree by luck.

Exclusions come from `runner/sync.py:exclusions()`, i.e. from `.gitignore`, for the same reason —
`evidence/`, `runner/.state/` and the caches are local-only by written policy, and a pusher that
carried its own list would drift from the policy the moment `.gitignore` changed.

Prints three lists and writes the push list to the path given by `--out` (default
`/tmp/grx_push_list.txt`), which `tools/api_push_incremental.py` consumes. Reports deletions but
does NOT act on them: a path absent locally may be absent because it was never on this machine,
and this script cannot tell that from a deliberate removal.
"""
import os
import sys
from fnmatch import fnmatch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import api_push_pr as P          # noqa: E402  git_sha, call, token, OWNER, REPO
from runner import sync as S     # noqa: E402  exclusions()

P.TOKEN = P.token()
IGNORE = S.exclusions()


def ignored(rel: str) -> bool:
    """True if `rel` is excluded, matching rsync's two different pattern semantics.

    rsync treats a pattern CONTAINING a slash as anchored at the transfer root and matched against
    the path, and a pattern without one as matched against any single component. Both forms are in
    this `.gitignore`, and collapsing them either way is wrong in a way that is easy to miss:

    * per-component only — `runner/.state` is compared against `runner` and `.state` separately,
      matches neither, and 2,800 local-only bookkeeping files are proposed for publication. This
      is the version this script shipped with first, and the wrong number is what caught it.
    * whole-path only — `evidence` is compared against `evidence/f5/x.json`, does not match, and
      the audit archive that is local-only BY POLICY is proposed for publication.

    The second failure is the dangerous one, which is why this is spelled out rather than tuned
    until the count looked plausible.
    """
    parts = rel.split("/")
    for pat in IGNORE:
        if "/" in pat:
            if rel == pat or rel.startswith(pat + "/"):
                return True
        elif any(fnmatch(seg, pat) for seg in parts):
            return True
    return False


# ---- local side ------------------------------------------------------------------------------
local = {}
for dirpath, dirnames, filenames in os.walk(ROOT):
    rel_dir = os.path.relpath(dirpath, ROOT)
    rel_dir = "" if rel_dir == "." else rel_dir
    # prune, so an excluded tree is never walked at all — 30 MB of evidence/ is not worth hashing
    dirnames[:] = [d for d in dirnames if not ignored(f"{rel_dir}/{d}".lstrip("/"))]
    for fn in filenames:
        rel = f"{rel_dir}/{fn}".lstrip("/")
        if ignored(rel):
            continue
        with open(os.path.join(dirpath, fn), "rb") as fh:
            local[rel] = P.git_sha(fh.read())

# ---- remote side -----------------------------------------------------------------------------
head = P.call("GET", f"/repos/{P.OWNER}/{P.REPO}/git/refs/heads/main")["object"]["sha"]
commit = P.call("GET", f"/repos/{P.OWNER}/{P.REPO}/git/commits/{head}")
tree = P.call("GET", f"/repos/{P.OWNER}/{P.REPO}/git/trees/{commit['tree']['sha']}?recursive=1")
if tree.get("truncated"):
    raise SystemExit("remote tree listing TRUNCATED — a diff against a partial tree would "
                     "report every unlisted path as an addition")
remote = {e["path"]: e["sha"] for e in tree["tree"] if e["type"] == "blob"}

added = sorted(p for p in local if p not in remote)
modified = sorted(p for p in local if p in remote and local[p] != remote[p])
deleted = sorted(p for p in remote if p not in local)

print(f"remote main   {head[:12]}  {commit['message'].splitlines()[0][:70]}")
print(f"remote blobs  {len(remote)}")
print(f"local  files  {len(local)}  (exclusions: {', '.join(IGNORE)})")
print()
for name, lst in (("ADDED", added), ("MODIFIED", modified), ("DELETED remotely-present-only",
                                                             deleted)):
    print(f"{name} ({len(lst)}):")
    for p in lst:
        print(f"    {p}")
    print()

out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv \
    else "/tmp/grx_push_list.txt"
with open(out_path, "w") as fh:
    fh.write("".join(f"{p}\n" for p in added + modified))
print(f"push list -> {out_path}  ({len(added) + len(modified)} path(s))")
