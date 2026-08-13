"""Shared fixtures for the claims/ gates.

The whole-repo scratch copy and its exclusion list live in `repo_copy.py`, next to this file,
so the gate that pins the list (`test_repo_copy_exclusions.py`) imports the same object the
fixture uses rather than a second copy of it. See that module's docstring for DEV-P4-36 — the
11.3 GB scratch wedge that came from three hand-written exclusion lists disagreeing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_copy import copy_repo_tree


@pytest.fixture
def copy_repo():
    """Copy the repo into `dst`, without the trees `.gitignore` says are local-only.

    Returns the callable rather than a path, so an arm needing two copies (a control and a
    mutant) can take two, and so a caller that does not read `results/` can exclude it by name
    — `copy_repo(dst, "results")` — instead of editing a list every other caller shares.
    """
    def _copy(dst: Path, *extra: str) -> Path:
        return copy_repo_tree(dst, *extra)
    return _copy
