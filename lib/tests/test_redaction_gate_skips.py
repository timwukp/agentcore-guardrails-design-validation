#!/usr/bin/env python3
"""Every directory the redaction gate skips must be a directory that is never published.

Why this gate exists
--------------------
`check_redaction.py` scans "everything that could be published" and skips `SKIP_DIRS`.
That list started as tooling only — venvs, caches, `.git` — where the skip is obviously
safe. It has since grown two entries holding PROJECT data:

* `evidence/`, 178 MB of raw API responses whose whole purpose is that a claim can be
  taken to AWS Support by request id and **full ARN**, so masking it would defeat it;
* `.state`, i.e. `runner/.state/`, which records the live instance id and the runner's
  S3 bucket name — and the bucket name is account-equivalent (DEV-P4-25), so it is
  precisely the value the gate exists to stop.

Both are safe *only because they are not distributed*, and until this file existed that
was a sentence in a comment. A skip is the strongest waiver in the gate: an `ALLOW` entry
excuses one pattern on one line, a skip blinds the gate to an entire subtree. So the
justification is checked, not written: **every entry of `SKIP_DIRS` must be matched by a
`.gitignore` rule**, with `.git` the single exception because git never tracks its own
directory by construction.

What this catches that nothing else does
----------------------------------------
The failure mode is silent in both directions and neither direction reds any existing
test:

1. A skip added for a directory that IS published. The gate keeps exiting 0 while no
   longer reading the subtree, and `MIN_FILES` cannot notice — 460 files minus one
   subdirectory is still far above a floor of 10. The gate would report clean *because*
   it stopped looking.
2. A `.gitignore` line deleted or narrowed while the skip stays. The directory becomes
   publishable and unscanned at the same moment, which is the worst possible pairing,
   and the deletion is a one-line edit in a file no test reads.

Both are `feedback_missing_check_is_not_pass` in directory form: the check that would
have caught the leak is the one that stopped running.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Registered under a name of this file's own, NOT `check_redaction`: that stem is an
# importable top-level name under pytest (the root conftest puts the repo root on
# sys.path), and `lib/tests/test_module_name_collisions.py` is the gate that says so.
# A literal, so the same gate can resolve it statically.
SUBJECT_MODULE_NAME = "_skipscan_check_redaction"

# `.git` is the one skip that cannot be justified by `.gitignore`, and the reason is
# structural rather than a judgement call: git does not track `.git`, so no ignore rule
# for it exists in any repository. Named here so the exception is one reviewed line
# instead of a relaxed assertion.
NOT_GITIGNORED_BY_CONSTRUCTION = {".git"}


def _subject():
    path = ROOT / "check_redaction.py"
    spec = importlib.util.spec_from_file_location(SUBJECT_MODULE_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def _gitignore_dir_rules() -> list[str]:
    """The directory rules in `.gitignore`, as their final path component.

    A rule is reduced to its last component because `SKIP_DIRS` is matched by the gate
    against individual path *parts* (`check_redaction.py:407`), not against a full
    relative path — that is what makes the bare entry `.state` match `runner/.state/`.
    Reducing the rule the same way keeps the two readings aligned; comparing a bare name
    against the full rule text would report `runner/.state/` as unmatched and send the
    next reader to widen the skip list instead.

    Comments and blank lines are dropped. Negations (`!`) are dropped too rather than
    interpreted: this repository has none, and a matcher that silently mis-handled one
    would be worse than one that reports a name as unmatched.
    """
    out: list[str] = []
    for raw in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        out.append(line.rstrip("/").split("/")[-1])
    return out


def _is_gitignored(name: str) -> bool:
    """Does some `.gitignore` rule match this directory name?

    `fnmatch`, because the venv rules are globs (`.venv-*/` is what covers
    `.venv-oracle` and `.venv-baseline`). Exact equality would report both as unmatched.
    """
    return any(fnmatch.fnmatch(name, rule) for rule in _gitignore_dir_rules())


# ------------------------------------------------------------------ the gate itself

def test_every_skipped_directory_is_gitignored():
    skips = _subject().SKIP_DIRS
    unjustified = sorted(
        n for n in skips
        if n not in NOT_GITIGNORED_BY_CONSTRUCTION and not _is_gitignored(n)
    )
    assert not unjustified, (
        "check_redaction.py skips these directories, but nothing in .gitignore keeps them "
        f"out of a push: {unjustified}\n"
        "A skipped directory that can be published is a subtree the gate has stopped "
        "reading while still exiting 0. Either add the .gitignore rule (and say why the "
        "directory is local-only) or remove the skip and let the gate scan it."
    )
    # The two project-data skips, pinned by name. The general assertion above would pass
    # if BOTH were deleted from SKIP_DIRS, and that is a different (also significant)
    # change — this arm makes it fail here, where the reasons are written down, rather
    # than surface later as a mysteriously larger file count.
    assert {"evidence", ".state", ".staging"} <= set(skips), (
        f"evidence/, runner/.state/ and/or runner/.staging/ are no longer skipped: "
        f"{sorted(skips)}. If that is deliberate, the docstrings in check_redaction.py and "
        ".gitignore that explain why they were local-only need to change in the same edit.")


def test_the_git_exception_is_real_and_is_the_only_one():
    """`.git` is exempt because no repository ignores it — verified, not assumed.

    Two ways this arm can fail, both worth being told about. If `.gitignore` ever grows a
    `.git` rule, the exemption is no longer needed and should go rather than sit there
    advertising a waiver that does nothing (the dead-`ALLOW`-entry defect, in a different
    file). If a SECOND name joins the exemption set, that is a skip being justified by
    assertion instead of by evidence, which is the thing this whole file replaced.
    """
    assert not _is_gitignored(".git"), (
        ".gitignore now has a rule matching `.git`, so the by-construction exemption in "
        "NOT_GITIGNORED_BY_CONSTRUCTION is dead and should be removed.")
    assert NOT_GITIGNORED_BY_CONSTRUCTION == {".git"}, (
        f"{sorted(NOT_GITIGNORED_BY_CONSTRUCTION)} — only `.git` has a structural reason "
        "to be unignorable. Any other name here is a skip nobody had to justify.")


def test_the_matcher_rejects_directories_that_are_not_ignored():
    """The vacuous-test check: a matcher that returns True for everything proves nothing.

    Per `feedback_vacuous_test_check`, the arm above is only meaningful if `_is_gitignored`
    can say no. The names below are real, tracked, published directories of this project —
    they are exactly what a mistaken skip would look like — so each one must come back
    False. `results` is the pointed case: it holds the distributable per-case JSON that
    `lib/redact.py` masks, so a skip for it would silence the gate over the release path
    itself.
    """
    published = ["lib", "results", "claims", "runner", "f3_efficacy", "infra", "docs"]
    tracked = [n for n in published if (ROOT / n).is_dir()]
    assert len(tracked) >= 5, (
        f"only {tracked} of {published} exist; this arm needs real published directories "
        "to test against, or it is asserting nothing")
    wrongly_matched = sorted(n for n in tracked if _is_gitignored(n))
    assert not wrongly_matched, (
        f"{wrongly_matched} are tracked, published directories that the matcher reports as "
        "gitignored. The matcher is too loose, so the arm above would pass for any skip.")

    # And the matcher can say yes — both spellings that matter, since they are matched by
    # different mechanisms: `evidence` by an exact rule, `.venv-oracle` by the `.venv-*/`
    # glob, and `.state` by a rule written as a PATH (`runner/.state/`) whose last
    # component is what the gate compares against.
    for name in ("evidence", ".venv-oracle", ".state", "__pycache__"):
        assert _is_gitignored(name), (
            f"{name!r} is not matched by any .gitignore rule any more; either the rule "
            "changed or _gitignore_dir_rules() stopped reading it")


def test_the_subject_still_consults_skip_dirs_per_path_component():
    """The premise every arm above rests on: bare names are matched against path parts.

    `.state` is a bare name and the ignore rule is `runner/.state/`. That pairing only
    works because the gate tests `any(part in SKIP_DIRS for part in ...parts)`. If it ever
    became a match on the relative path as a whole, `.state` would stop matching anything,
    `runner/.state/runner.json` would silently re-enter the scan, and this file's reading
    of `.gitignore` would have quietly become the wrong reading.
    """
    src = (ROOT / "check_redaction.py").read_text(encoding="utf-8")
    assert "any(part in SKIP_DIRS for part in" in src, (
        "check_redaction.py no longer filters SKIP_DIRS per path component. Re-derive how "
        "a bare skip name relates to a .gitignore rule written as a path before trusting "
        "the assertions in this file.")
