#!/usr/bin/env python3
"""Assert that the platform did not contaminate the measurement instruments.

WHAT AN "INSTRUMENT" MEANS HERE, LITERALLY
------------------------------------------
Several F1 and F8 verdicts *are* reads of a specific botocore version's service model: F1-19 and
F8-8's records say what a given SDK does and does not model, and the version is the measurement, not
the environment it happened in. Every published case file carries `ambient_sdk.botocore`, so the set
of versions this project has measured under is derivable rather than remembered — measured
2026-08-20: `1.43.67` in 98 cases and `1.42.79` in one (`F8-8`), which is why two pinned venvs exist.

Upgrading either venv to reach a newer AgentCore API would therefore silently re-date those verdicts.
This gate exists because that upgrade is a one-line, well-intentioned act — `pip install -U boto3`
while chasing a Harness field — and nothing else in the repository would notice.

THE THREE ARMS
--------------
1. **Declared pin.** `.venv-oracle` must carry exactly the boto3/botocore in
   `runner/requirements.txt`. That file is the pin the EC2 runner installs from, so a drift here also
   means the laptop and the runner are no longer the same instrument.
2. **Derived pin.** Every venv that has botocore at all must carry a version that appears in the
   published evidence's `ambient_sdk` set. This is the arm that catches a NEW venv, or a version
   nobody declared anywhere: `feedback_scope_as_namelist` — a list of names cannot notice a new name,
   so the rule is a property of the tree, not an enumeration of the three venvs known today.
3. **Import direction.** `platform/agent/` may not import `lib/` at all (it will run under
   `.venv-agentcore`, where the repository is not installed), and `platform/build/` may import only
   the two repo modules it is *supposed* to share — `lib.redact` and `check_redaction`. That second
   half is a CEILING, not a floor: sharing the masker and the pattern set is the design (one
   implementation, never a fork), while reaching into `lib.oracle` or `lib.stats` from a build script
   would put sealed verdict logic on a second code path. The walk is recursive and exempts
   `platform/build/tests/` **by decision, stated in the code** — a build test's job is to re-derive a
   number from the repository's own code and compare, which is the opposite of a second code path.
   With a non-recursive walk that exemption would instead have been an accident of `glob` vs `rglob`,
   and a subdirectory the ceiling does not reach is where the next unreviewed import goes.

Exit 0 = every arm passed. Exit 1 = a stated violation. Exit 2 = the gate could not run, which is
also a failure: `feedback_guard_tool_exit_codes`.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO / "runner" / "requirements.txt"
PUBLISHED = REPO / "results" / "phase1"

# Repo modules `platform/build/` is allowed to import, and the reason each one is allowed.
BUILD_MAY_IMPORT = {
    "lib.redact": "the masker at the write path; a second implementation would be a second policy",
    "lib": "package-level import of the above",
    "check_redaction": "PATTERNS/allowed()/scan_forms(); gate_payload imports, never forks them",
    "census": "load_register()/prereg_registry_sha(); the repo's own derivation of the sealed "
              "register and its hash. Re-deriving the register in the build would create the second "
              "source of truth the whole payload design exists to avoid.",
}

# A floor on the derivation in arm 2. Zero published files would make the derived set empty and every
# comparison against it vacuous.
MIN_PUBLISHED_FILES = 50

# A floor on arm 3's own reach. The ceiling is enforced by walking files; a walk that finds none
# reports "ceiling respected" (`feedback_zero_file_scan_is_error`). Set below today's count so a new
# build script does not have to touch this line, and far enough above zero that a broken path fails.
MIN_BUILD_FILES = 4  # six today, so a deleted script does not red the gate before its replacement lands


class Failure(Exception):
    pass


def parse_pins(requirements: Path) -> dict[str, str]:
    if not requirements.is_file():
        raise SystemExit(f"[gate cannot run] {requirements} is missing")
    pins: dict[str, str] = {}
    for line in requirements.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\s*([A-Za-z0-9_.\-]+)==([0-9][^\s#]*)\s*(#.*)?", line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    if not pins:
        raise SystemExit(f"[gate cannot run] no `name==version` pins parsed from {requirements}")
    return pins


def venv_versions(venv: Path) -> dict[str, str]:
    """Read installed versions from `*.dist-info/METADATA` rather than by running the interpreter.

    Running `venv/bin/python -c "import botocore"` would be the obvious way and is worse: it imports
    third-party code from a tree this gate is meant to be suspicious of, and it fails differently
    when the venv's interpreter is broken than when the package is absent.
    """
    versions: dict[str, str] = {}
    for site in venv.glob("lib/python*/site-packages"):
        for dist in site.glob("*.dist-info"):
            metadata = dist / "METADATA"
            if not metadata.is_file():
                continue
            name = version = None
            for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Name: "):
                    name = line[6:].strip().lower()
                elif line.startswith("Version: "):
                    version = line[9:].strip()
                elif not line.strip():
                    break
            if name and version:
                versions[name] = version
    return versions


def measured_sdk_versions() -> tuple[dict[str, set[str]], int]:
    """The botocore/boto3 versions the published verdicts were actually measured under."""
    found: dict[str, set[str]] = {"botocore": set(), "boto3": set()}
    files = sorted(PUBLISHED.glob("*.json"))
    if len(files) < MIN_PUBLISHED_FILES:
        raise SystemExit(
            f"[gate cannot run] only {len(files)} published case file(s) under {PUBLISHED}; the "
            f"derived version set would be empty or near-empty, making arm 2 vacuous"
        )

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in found and isinstance(value, str):
                    found[key].add(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in files:
        try:
            walk(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    if not found["botocore"]:
        raise SystemExit(
            "[gate cannot run] no botocore version found in any published case file. The evidence "
            "records `ambient_sdk`; if that field was renamed, this derivation must be updated "
            "rather than skipped."
        )
    return found, len(files)


def repo_imports(path: Path) -> set[str]:
    """Every module name imported by one file, as written. Parsed, not grepped: a grep for `import
    lib` misses `from lib.redact import mask` and hits it inside a docstring."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise SystemExit(f"[gate cannot run] {path} does not parse: {exc}") from exc
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def check_venvs(failures: list[str], notes: list[str]) -> None:
    pins = parse_pins(REQUIREMENTS)
    measured, n_files = measured_sdk_versions()
    notes.append(
        f"published evidence: botocore {sorted(measured['botocore'])} over {n_files} case files"
    )

    oracle = REPO / ".venv-oracle"
    if not oracle.is_dir():
        raise SystemExit(f"[gate cannot run] {oracle} is missing; it runs every producer")
    installed = venv_versions(oracle)
    for package in ("boto3", "botocore"):
        want, have = pins.get(package), installed.get(package)
        if want is None:
            failures.append(f"{REQUIREMENTS} does not pin {package}")
        elif have != want:
            failures.append(
                f".venv-oracle has {package} {have}, runner/requirements.txt pins {want}. That pin "
                "is a measurement instrument (F1/F8 verdicts read this SDK's service model) and is "
                "also what the EC2 runner installs, so a drift means the two are no longer the "
                "same instrument."
            )
        else:
            notes.append(f".venv-oracle {package} {have} == pin")

    for venv in sorted(REPO.glob(".venv*")):
        if not venv.is_dir():
            continue
        installed = venv_versions(venv)
        version = installed.get("botocore")
        if version is None:
            notes.append(f"{venv.name}: no botocore (nothing to compare)")
            continue
        if version not in measured["botocore"]:
            failures.append(
                f"{venv.name} has botocore {version}, which appears in NO published case's "
                f"`ambient_sdk` (measured: {sorted(measured['botocore'])}). Either an instrument was "
                "upgraded, or a new venv arrived carrying an unmeasured SDK."
            )
        else:
            notes.append(f"{venv.name}: botocore {version} is a measured version")


def check_imports(failures: list[str], notes: list[str]) -> None:
    agent = REPO / "platform" / "agent"
    if agent.is_dir():
        files = sorted(agent.rglob("*.py"))
        notes.append(f"platform/agent: {len(files)} python file(s)")
        for path in files:
            for name in repo_imports(path):
                if name == "lib" or name.startswith("lib."):
                    failures.append(
                        f"{path.relative_to(REPO)} imports {name}. The agent's toolchain runs under "
                        ".venv-agentcore, where this repository is not installed; importing lib/ "
                        "there both breaks at runtime and re-couples the agent to the sealed "
                        "measurement code."
                    )
    else:
        notes.append("platform/agent does not exist yet (Phase 3); no files to check")

    # `rglob`, not `glob`, and the exemption below is a DECISION rather than the shape of a glob.
    # With `glob("*.py")` the ceiling stopped at the directory's top level, so `build/tests/*.py` sat
    # outside it by accident — and a subdirectory the ceiling does not reach is exactly where the next
    # unreviewed import goes (`feedback_guard_scope_is_a_claim`). Tests are then exempted on purpose:
    # a build test's job is to compare the build's output against the repository's OWN derivation, so
    # `platform/build/tests/test_build_site_data.py` must be free to import `census` or `lib.stats` to
    # re-derive a number independently. The ceiling exists to keep sealed logic off a second
    # PRODUCTION code path; a test asserting agreement is the opposite of a second path.
    build = REPO / "platform" / "build"
    scanned, exempt = 0, 0
    for path in sorted(build.rglob("*.py")):
        if "tests" in path.relative_to(build).parts:
            exempt += 1
            continue
        scanned += 1
        for name in repo_imports(path):
            top = name.split(".")[0]
            if top in {"lib", "check_redaction", "census", "verify_prereg"} or name in BUILD_MAY_IMPORT:
                if name not in BUILD_MAY_IMPORT:
                    failures.append(
                        f"{path.relative_to(REPO)} imports {name}, which is not in "
                        f"BUILD_MAY_IMPORT ({sorted(BUILD_MAY_IMPORT)}). Sharing lib.redact and "
                        "check_redaction is the design; reaching further puts sealed verdict logic "
                        "on a second code path. If the new import is right, add it here with its "
                        "reason so the widening is a visible act."
                    )
    if scanned < MIN_BUILD_FILES:
        failures.append(
            f"the import ceiling read {scanned} file(s) under platform/build, below the floor of "
            f"{MIN_BUILD_FILES}. A scan that reads nothing reports clean, which is the one outcome "
            "this check must never produce silently."
        )
    else:
        notes.append(f"platform/build: import ceiling {sorted(BUILD_MAY_IMPORT)} respected across "
                     f"{scanned} file(s); {exempt} test file(s) exempt by decision, see the comment")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="print every passing observation")
    args = parser.parse_args(argv)

    failures: list[str] = []
    notes: list[str] = []
    check_venvs(failures, notes)
    check_imports(failures, notes)

    if args.verbose or failures:
        for note in notes:
            print(f"  {note}")
    if failures:
        print("\nFAILED — venv isolation", file=sys.stderr)
        for item in failures:
            print(f"  * {item}", file=sys.stderr)
        return 1
    print(f"PASSED — instruments unchanged, import direction held ({len(notes)} observations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
