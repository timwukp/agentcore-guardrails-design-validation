#!/usr/bin/env python3
"""Publish the platform: gate everything, upload an immutable release, then flip the pointer.

WHAT MAKES THIS DIFFERENT FROM `aws s3 sync`
--------------------------------------------
Three properties, in the order they matter:

1. **No half-published release.** The bundle and the payload go to `v/<stamp>/`, which nothing points
   at yet. The pointer — a copy of that release's `index.html` at the distribution root — is written
   LAST, as a single object. A failure at any earlier step leaves the previous release serving, and a
   reader cannot observe a state where the shell is new and the payload is old. That ordering is the
   whole reason the site is not a `sync`: `sync` mutates the live document first if its name sorts
   first.

2. **Every gate's return code is read directly.** `subprocess.run(...).returncode`, never a pipeline's
   exit status, and never an `if 'PASSED' in output` heuristic. A gate that cannot run (missing file,
   ImportError, rc 127) must fail the publish, because "the check did not appear" reads exactly like
   "the check passed" in a log.

3. **A missing gate is an error, not a skip.** REQUIRED_GATES below is a list of files. If one is
   absent this refuses to publish and names it. The failure mode being designed against is a publish
   that keeps working after someone renames a gate — the site would keep updating and the check would
   simply stop existing.

THE STAMPED PREFIX, AND WHY THE SPA IS REBUILT HERE
---------------------------------------------------
The release is built with `vite build --base=/v/<stamp>/`, so `index.html` references
`/v/<stamp>/assets/…` absolutely and `site/src/lib/data.ts` resolves its payload prefix to
`/v/<stamp>/data` (it reads `import.meta.env.BASE_URL`). One document therefore works from both URLs
it is served at — `https://host/` (the root pointer copy) and `https://host/v/<stamp>/` (the
permanent link) — with no rewrite rule and no second cache behaviour. Measured before this script was
written: with `--base=/v/20260819T223754Z/`, the emitted bundle contains the literal
`/v/20260819T223754Z/data` and `index.html`'s script src is absolute.

Local development keeps `base: "./"` from `vite.config.ts`, where `BASE_URL` is `"./"` and everything
resolves relative to the document, so `csp_preview.py` is unaffected. The cost of rebuilding here is
that `site/dist` is left holding a stamped build and its `data` symlink is gone (vite empties the
directory); this script re-links it at the end and says so, because a developer who previews next and
sees 404s should not have to work out why.

CACHING
-------
`v/<stamp>/**` is `max-age=31536000, immutable` — safe because the stamp is in the path, so those
bytes are never rewritten. The two root objects are `no-cache, must-revalidate`, which CACHING_OPTIMIZED
honours down to its 1 s minimum TTL. That is the only place the caching split lives: adding a
CloudFront behaviour for `/v/*` would create a path whose Lambda@Edge auth association can be
forgotten (see `platform/infra/lib/site-stack.ts`).

USAGE
-----
    python3 platform/build/publish_web.py --dry-run          # gates + build, no AWS calls at all
    python3 platform/build/publish_web.py --confirm          # gates, build, upload, flip, verify

`--confirm` is required to touch AWS. There is no default that uploads.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SITE = REPO / "site"
DIST = SITE / "dist"
DEFAULT_PAYLOAD = REPO.parent / "grx-site-payload"
STACK_NAME = "GrxLive"

# The interpreters are separate on purpose and the reasons differ per venv; see platform/README.md.
# `.venv-oracle` is a measurement instrument (its botocore pin is what several F1/F8 verdicts read),
# so it is used to RUN code here and never modified.
VENV_ORACLE = REPO / ".venv-oracle" / "bin" / "python"
VENV_FIGS = REPO / ".venv-figs" / "bin" / "python"

# A collapse detector, not a census. `check_redaction.py` reported 890 scanned files on 2026-08-20;
# the floor exists so that a change which makes the scanner select almost nothing — a broken
# extension predicate, a widened skip list, a bad `--root` — fails the publish instead of passing it
# in 0.2 s. It is deliberately far below the real count so that deleting a directory is not a publish
# failure (`feedback_zero_file_scan_is_error`, `feedback_scope_as_namelist`: a floor AND a ceiling —
# the ceiling here is the set-equality assertion in gate_payload.py).
MIN_REPO_FILES_SCANNED = 500

# The same shape of floor for the SPA's own tests: `node --test` exits 0 when its glob matches nothing,
# so a renamed test file would publish as a clean run of no tests. 12 as of 2026-08-20; raise it when
# tests are added, which makes the addition visible here rather than only in the test directory.
SPA_TEST_FLOOR = 12

# The gates over AUTHORED curation, as data rather than as a chain of `if`s.
#
# Every entry says four things: the curation file a human writes (`curation`), the payload file the
# build derives from it (`emits`), the gate that enforces its rules (`script`), and what publishing it
# ungated would mean (`ungated_means`). Each runs only if its payload file is present, because these
# curations are authored incrementally and a gate that fails for a file nobody has written yet gets
# deleted rather than satisfied.
#
# The reason this is a table: a conditional gate's failure mode is silence. Emit the file under a
# different name, or rename the check, and the branch simply stops firing — the publish then reports a
# clean run with one fewer gate, which reads exactly like a run that passed it
# (`feedback_missing_check_is_not_pass`, `feedback_guard_tool_exit_codes`). A table can be walked by a
# test in both directions: every `script` must exist, and every `curation` file that exists on disk
# must have its `emits` in a real build's payload. Prose in this position cannot be walked.
CURATION_GATES = [
    {
        "name": "scenario curation gate",
        "curation": "platform/curation/scenarios.yaml",
        "emits": "scenarios.json",
        "script": "check_scenarios.py",
        "args": [],
        "absent": "the B2B/B2C lens has not been authored yet",
        "ungated_means":
            "The B2B/B2C lens is authored, not derived, and its governance rules (no INCONCLUSIVE "
            "case under a validated control, F5-3b and F1-19 never primary) are only real if a gate "
            "enforces them. Publishing the lens ungated is not an option.",
    },
    {
        "name": "architecture curation gate",
        "curation": "platform/curation/architecture.yaml",
        "emits": "architecture.json",
        "script": "check_architecture.py",
        "args": [],
        "absent": "the design diagrams have not been authored yet",
        "ungated_means":
            "A diagram is the payload's most quotable artifact and the one that travels furthest from "
            "its caveats — screenshotted into a deck, it carries a colour per component and no case "
            "table underneath. Its topology is authored, so the rules that keep a colour honest — every "
            "case in the register, every box either citing cases or stating in writing that nothing was "
            "measured, no INCONCLUSIVE-only box reading as validated, a NEVER_CITE case excluded in "
            "writing rather than by absence, and placed plus excluded equalling the register — are "
            "enforced by this gate and by nothing else at the authoring layer. Publishing a green box "
            "the register does not license is the loudest wrong claim this platform could make.",
    },
    {
        "name": "caveat curation gate",
        "curation": "platform/curation/caveats.yaml",
        "emits": "method.json",
        "script": "check_caveats.py",
        "args": [],
        "absent": "no bounds have been authored for the cases whose record states none",
        "ungated_means":
            "These are the only sentences on the site that speak in the platform's own voice on a page "
            "where the reader is looking at a verdict, for the 49 cases whose record bounds nothing. "
            "Ungated, three specific failures ship silently. A caveat authored for a case whose record "
            "already carries its own sentence puts a paraphrase where an artifact exists. A caveat left "
            "attached after a verdict flips is read as current. And a verdict resting on a "
            "non-observation — 0 events in n trials, a nonsignificant difference, a probe set that saw "
            "nothing — whose caveat neither states a ceiling nor names a rival world producing the same "
            "data is the exact over-read the section exists to prevent, written by us rather than by a "
            "reader. This gate is also the only thing holding the boundary the count depends on: "
            "authored coverage is a separate claim from what the record carries, and merging them is "
            "how '39 of 91' got into a docstring.",
    },
    {
        "name": "control curation gate (+ field-path re-introspection)",
        "curation": "platform/curation/controls.yaml",
        "emits": "controls.json",
        "script": "check_controls.py",
        # `--verify-field-paths` re-introspects the pinned botocore model, so a detect path the SDK no
        # longer carries fails the publish instead of quietly matching nothing in a reader's template
        # and reporting NOT_DECLARED. That is the asymmetric failure: it tells a reader the audit
        # looked and saw nothing, when in fact it could not look.
        "args": ["--verify-field-paths"],
        "absent": "the control inventory is not emitted by this build",
        "ungated_means":
            "The control inventory is authored, and its citation rules — F5-3b cited nowhere, "
            "`not_established` citing only INCONCLUSIVE cases, `not_measured` citing nothing and "
            "saying why, a PARTIAL or position-bound case dragging its scope into `scope_note` — are "
            "enforced by this gate and by nothing else. An audit report that cites F5-3b, or that "
            "turns an INCONCLUSIVE verdict into a recommendation, is this study contradicting its own "
            "editorial policy inside a document addressed to somebody else's production system.",
    },
]


@dataclass
class Step:
    """One gate. `rc_ok` decides which return codes are acceptable, so 'rc 1 means stale, which is
    data rather than a failure' can be expressed without weakening the default."""

    name: str
    argv: list[str]
    rc_ok: tuple[int, ...] = (0,)
    rc: int | None = None
    stdout: str = ""
    stderr: str = ""
    note: str = ""


@dataclass
class Publish:
    stamp: str
    payload: Path
    steps: list[Step] = field(default_factory=list)
    # A gate that did not run, and why. Separate from `steps` deliberately: a skipped gate has no
    # return code, and giving it one — even `null` inside the gates list — would let a reader scan the
    # list and see a row where nothing ran. It is recorded because "this curation is not authored yet"
    # is a fact about the release, and a release that silently omits a gate reads as one that passed it.
    skipped: list[dict] = field(default_factory=list)
    figure_check_rc: int | None = None
    uploaded: list[str] = field(default_factory=list)


def fail(msg: str) -> None:
    print(f"\nREFUSED — {msg}", file=sys.stderr)
    raise SystemExit(2)


def run(step: Step, cwd: Path = REPO) -> Step:
    """Run one step. Return code read from the process, output captured and echoed — never piped."""
    print(f"\n=== {step.name}\n    $ {' '.join(str(a) for a in step.argv)}")
    proc = subprocess.run(step.argv, cwd=cwd, capture_output=True, text=True, check=False)
    step.rc, step.stdout, step.stderr = proc.returncode, proc.stdout, proc.stderr
    tail = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()][-6:]
    for line in tail:
        print(f"    | {line[:160]}")
    print(f"    rc={step.rc}")
    if step.rc not in step.rc_ok:
        fail(f"{step.name} exited {step.rc} (accepted: {step.rc_ok}). {step.note}")
    return step


def require_files(paths: dict[str, Path]) -> None:
    missing = {name: p for name, p in paths.items() if not p.exists()}
    if missing:
        lines = "\n".join(f"      {n}: {p}" for n, p in missing.items())
        fail(
            "a required gate or interpreter is absent, so the publish cannot state that it ran:\n"
            f"{lines}\n"
            "    A gate that does not exist must stop the publish. If one was renamed, update "
            "REQUIRED_GATES in this file — the point is that the change is visible here."
        )


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def parse_scanned_count(stdout: str) -> int:
    """`PASSED — no unredacted cloud identifiers in 890 scanned files.` -> 890.

    An unparseable line is a failure rather than a warning: this number is the only evidence that the
    gate read anything at all, and a gate that scanned zero files exits 0.
    """
    match = re.search(r"in ([\d,]+) scanned files", stdout)
    if not match:
        fail(
            "could not find the scanned-file count in check_redaction.py's output. That count is the "
            "only proof the gate read anything; treating its absence as 'fine' is how a zero-file "
            "scan passes."
        )
    return int(match.group(1).replace(",", ""))  # type: ignore[union-attr]


# ---------------------------------------------------------------------------- the gates
#
# Order is load-bearing. Sources before derived bytes: a redaction failure in `results/` must be
# reported against `results/`, not against the copy of it that reached `cases/F5-7b.json`.

def required_gates() -> dict[str, Path]:
    return {
        "seal verifier": REPO / "verify_prereg.py",
        "repo redaction gate": REPO / "check_redaction.py",
        "payload builder": REPO / "platform" / "build" / "build_site_data.py",
        "payload redaction gate": REPO / "platform" / "build" / "gate_payload.py",
        "site invariants": REPO / "platform" / "build" / "check_site_invariants.py",
        "venv isolation": REPO / "platform" / "build" / "check_venv_isolation.py",
        ".venv-oracle interpreter": VENV_ORACLE,
        ".venv-figs interpreter": VENV_FIGS,
    }


def gate_sources(pub: Publish) -> None:
    pub.steps.append(run(Step(
        "sealed preregistration still matches its hash",
        [str(VENV_ORACLE), "verify_prereg.py"],
        note="PREREGISTRATION.yaml or a value derived from lib/stats.py changed. A drifted seal is "
             "the loudest signal this project has; it must never be published past.",
    )))

    redaction = run(Step(
        "repository redaction gate",
        [str(VENV_ORACLE), "check_redaction.py"],
        note="an unredacted cloud identifier exists in a source file.",
    ))
    scanned = parse_scanned_count(redaction.stdout)
    print(f"    scanned {scanned} files")
    if scanned < MIN_REPO_FILES_SCANNED:
        fail(
            f"check_redaction.py scanned only {scanned} files (floor {MIN_REPO_FILES_SCANNED}). "
            "It exited 0, which is what a gate that reads nothing does."
        )
    redaction.note = f"{scanned} files scanned"
    pub.steps.append(redaction)

    pub.steps.append(run(Step(
        "venv isolation",
        [str(VENV_ORACLE), "platform/build/check_venv_isolation.py"],
        note="the measurement venv's pin moved, or platform/ imported lib/.",
    )))


def build_payload(pub: Publish) -> None:
    # rc 1 means "the figures' numbers no longer match MANIFEST.json", which is a fact the site
    # RENDERS as a freshness badge. Publishing it is correct; hiding it is not. Any other non-zero rc
    # is a crash and tells us nothing, so it fails.
    figures = run(Step(
        "figure numeric check (result is data, not a gate)",
        [str(VENV_FIGS), "tools/whitepaper_figures.py", "--check"],
        rc_ok=(0, 1),
    ))
    pub.figure_check_rc = figures.rc
    pub.steps.append(figures)

    pub.steps.append(run(Step(
        "build payload",
        [str(VENV_ORACLE), "platform/build/build_site_data.py",
         "--out", str(pub.payload), "--clean", "--stamp", pub.stamp,
         "--figure-check-rc", str(pub.figure_check_rc)],
    )))

    # The SPA's own logic tests, before the bundle it would ship. Two of the functions they cover carry
    # properties nothing else in this pipeline can see: the intake refuses to compose a shell command
    # from a value carrying a metacharacter, and the report view refuses a JSON file that is not a
    # report rather than rendering it as a report with every section empty. `gate_payload.py` and
    # `check_site_invariants.py` read the built BYTES — they can confirm a stylesheet rule exists and
    # never that a function refuses what it must refuse.
    #
    # `node --test` with a glob that matches nothing exits 0, so the count is asserted below: a test run
    # that executed no tests is an error, not a pass (`feedback_zero_file_scan_is_error`).
    tests = run(Step(
        "SPA logic tests",
        ["node", "--test", "src/lib/**/*.test.ts"],
        note="a red assertion here means the intake or the report decoder changed behaviour.",
    ), cwd=SITE)
    pub.steps.append(tests)
    counted = re.search(r"^\s*(?:ℹ|#)\s*tests\s+(\d+)", tests.stdout, re.MULTILINE)
    if not counted or int(counted.group(1)) < SPA_TEST_FLOOR:
        fail(
            f"the SPA test run reported {counted.group(1) if counted else 'no'} test(s), fewer than the "
            f"floor of {SPA_TEST_FLOOR}. `node --test` exits 0 when its glob matches nothing, so a "
            "renamed file or a moved directory would otherwise publish as a clean run. Raise "
            "SPA_TEST_FLOOR in this file when tests are added — the point is that the change is visible."
        )
    print(f"    verified: {counted.group(1)} SPA test(s) actually ran")

    pub.steps.append(run(Step(
        f"build SPA at base /v/{pub.stamp}/",
        ["npm", "run", "build", "--", f"--base=/v/{pub.stamp}/"],
        note="the release's asset and payload URLs are absolute under the stamped prefix, which is "
             "what lets the root pointer copy load the same bytes.",
    ), cwd=SITE))

    index = DIST / "index.html"
    if not index.is_file():
        fail(f"{index} does not exist after the build")
    marker = f"/v/{pub.stamp}/"
    if marker not in index.read_text(encoding="utf-8"):
        fail(
            f"{index} does not reference {marker}. The --base flag did not take effect, so the root "
            "pointer copy would load assets from a path where nothing is published."
        )
    bundles = [p for p in files_under(DIST / "assets") if p.suffix == ".js"]
    if not any(marker in p.read_text(encoding="utf-8", errors="replace") for p in bundles):
        fail(
            f"no built bundle contains {marker}data. `import.meta.env.BASE_URL` is not reaching "
            "site/src/lib/data.ts, so the root copy of this release would fetch /data/… and 404."
        )
    print(f"    verified: index.html and the bundle both carry {marker}")


def skip(pub: Publish, name: str, why: str) -> None:
    """Record a gate that did not run. Printing it is not recording it."""
    pub.skipped.append({"name": name, "why": why})
    print(f"\n=== {name}\n    skipped: {why}. Recorded in current.json under `gates_skipped`.")


def gate_payload(pub: Publish) -> None:
    payload_files = files_under(pub.payload)
    if not payload_files:
        fail(f"{pub.payload} is empty")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        for p in payload_files:
            fh.write(f"{p.relative_to(pub.payload).as_posix()}\n")
        upload_list = Path(fh.name)
    try:
        pub.steps.append(run(Step(
            "payload redaction gate (payload + built SPA)",
            [str(VENV_ORACLE), "platform/build/gate_payload.py",
             "--payload", str(pub.payload),
             "--upload-list", str(upload_list),
             "--also-scan", str(DIST)],
            note="an identifier reached the bytes CloudFront would serve.",
        )))
    finally:
        upload_list.unlink(missing_ok=True)

    pub.steps.append(run(Step(
        "site invariants (the site cannot claim what the artifacts do not support)",
        [str(VENV_ORACLE), "platform/build/check_site_invariants.py",
         "--payload", str(pub.payload), "--dist", str(DIST)],
    )))

    for gate in CURATION_GATES:
        script = REPO / "platform" / "build" / gate["script"]
        if not (pub.payload / gate["emits"]).exists():
            skip(pub, gate["name"], f"the payload contains no {gate['emits']} ({gate['absent']})")
            continue
        if not script.is_file():
            fail(f"the payload contains {gate['emits']} but platform/build/{gate['script']} does "
                 f"not exist. {gate['ungated_means']}")
        pub.steps.append(run(Step(gate["name"],
                                  [str(VENV_ORACLE), str(script), *gate["args"]])))


# ---------------------------------------------------------------------------- AWS
#
# The AWS CLI rather than an SDK, for one reason: `.venv-oracle`'s botocore version is a measurement
# instrument in this project and nothing in a publish path should give anyone a reason to bump it.

def aws(args: list[str], parse_json: bool = True):
    proc = subprocess.run(["aws", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        fail(f"aws {' '.join(args[:3])}… exited {proc.returncode}: {proc.stderr.strip()[:400]}")
    return json.loads(proc.stdout) if parse_json and proc.stdout.strip() else proc.stdout


def stack_outputs() -> dict[str, str]:
    data = aws(["cloudformation", "describe-stacks", "--stack-name", STACK_NAME,
                "--region", "us-east-1", "--output", "json"])
    outputs = data["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def upload(pub: Publish, bucket: str, distribution: str) -> None:
    prefix = f"s3://{bucket}/v/{pub.stamp}"
    # Refuse to write into an existing immutable prefix. Two publishes in the same second is the
    # obvious case; a resumed half-publish is the dangerous one, because `sync` would leave the old
    # objects in place and the release would be a mixture nobody can name.
    listing = aws(["s3api", "list-objects-v2", "--bucket", bucket,
                   "--prefix", f"v/{pub.stamp}/", "--max-items", "1", "--output", "json"])
    if isinstance(listing, dict) and listing.get("Contents"):
        fail(f"v/{pub.stamp}/ already has objects. An immutable prefix is never rewritten; "
             "re-run to get a new stamp.")

    immutable = "max-age=31536000, immutable"
    fresh = "no-cache, must-revalidate"

    print(f"\n=== upload release to {prefix}/")
    aws(["s3", "sync", str(DIST), f"{prefix}/", "--exclude", "data/*", "--exclude", "data",
         "--cache-control", immutable, "--only-show-errors"], parse_json=False)
    aws(["s3", "sync", str(pub.payload), f"{prefix}/data/",
         "--cache-control", immutable, "--only-show-errors"], parse_json=False)

    manifest = pub.payload / "MANIFEST.json"
    pointer = {
        "stamp": pub.stamp,
        "release_prefix": f"/v/{pub.stamp}/",
        "manifest_sha256": sha256_file(manifest) if manifest.is_file() else None,
        "figure_check_rc": pub.figure_check_rc,
        "gates": [{"name": s.name, "rc": s.rc, "note": s.note} for s in pub.steps],
        "gates_skipped": pub.skipped,
        "published_by": "platform/build/publish_web.py",
    }
    with tempfile.TemporaryDirectory() as tmp:
        current = Path(tmp) / "current.json"
        current.write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        aws(["s3", "cp", str(current), f"s3://{bucket}/current.json",
             "--cache-control", fresh, "--content-type", "application/json",
             "--only-show-errors"], parse_json=False)

    # THE FLIP. Last, and one object: the root index.html is the pointer. Every asset and every
    # payload file it names is already in place above.
    print("\n=== flip the pointer (root index.html)")
    aws(["s3", "cp", str(DIST / "index.html"), f"s3://{bucket}/index.html",
         "--cache-control", fresh, "--content-type", "text/html; charset=utf-8",
         "--only-show-errors"], parse_json=False)

    # Only the two mutable objects. `/v/<stamp>/*` has never been requested, so it cannot be cached.
    inval = aws(["cloudfront", "create-invalidation", "--distribution-id", distribution,
                 "--paths", "/index.html", "/current.json", "/", "--output", "json"])
    print(f"    invalidation {inval['Invalidation']['Id']} for /index.html, /current.json, /")

    pub.uploaded = [f"v/{pub.stamp}/index.html", "current.json", "index.html"]


def verify_served(pub: Publish, bucket: str) -> None:
    """Re-scan the bytes S3 now holds, rather than the bytes we meant to upload.

    CloudFront cannot be fetched from here — every path requires a Cognito session, which is the
    point of the platform — so the origin is the closest thing to 'what is served'. Downloading and
    re-running the patterns catches a class the pre-upload gate cannot: a truncated or mangled upload,
    and a file that reached the bucket without passing through the gate at all.

    **The two halves are fetched separately, because `upload()` writes them separately and they are
    scanned under different rules.** `--payload` inherits reviewed exceptions from the artifact a
    payload file was derived from — four RFC1918 hits in `cases/F5-7b.json` and `findings.json` do —
    while `--also-scan` grants no inheritance at all, by design, because a Vite bundle has no
    upstream artifact to inherit from. Syncing the whole release prefix into one directory and
    passing it as `--payload` therefore got this wrong in two ways at once, both found on 2026-08-20
    by running it against the first real release: `MANIFEST.json` lives at `data/MANIFEST.json` under
    the prefix, so the gate exited 1 with `no MANIFEST.json under <tmp>` and **the patterns never ran
    over a single served byte** — the loudest possible form of the right failure, but a check that
    had never once executed its own subject (`feedback_probe_must_reach_the_code`). Passing the same
    combined tree to `--also-scan` instead would have failed the other way, convicting those four
    reviewed exceptions. The shapes here mirror `upload()` line for line: payload → `data/`,
    `site/dist` minus `data` → the prefix root.

    Set equality against the local trees is asserted, not just a non-empty count. "A truncated or
    mangled upload" is what the docstring above has always claimed to catch, and a count cannot: one
    file missing and one file extra is the same integer.
    """
    print(f"\n=== verify what the origin now holds under v/{pub.stamp}/")
    with tempfile.TemporaryDirectory() as tmp:
        served_data, served_spa = Path(tmp) / "data", Path(tmp) / "spa"
        aws(["s3", "sync", f"s3://{bucket}/v/{pub.stamp}/data/", str(served_data),
             "--only-show-errors"], parse_json=False)
        aws(["s3", "sync", f"s3://{bucket}/v/{pub.stamp}/", str(served_spa),
             "--exclude", "data/*", "--only-show-errors"], parse_json=False)

        for label, served, local in (("payload", served_data, pub.payload),
                                     ("SPA", served_spa, DIST)):
            want = {p.relative_to(local) for p in files_under(local)
                    if label == "payload" or "data" not in p.relative_to(local).parts}
            got = {p.relative_to(served) for p in files_under(served)}
            if not got:
                fail(f"downloaded zero {label} objects from v/{pub.stamp}/ — the upload did not "
                     f"happen, and a gate over nothing would have passed")
            if got != want:
                fail(f"the {label} half of v/{pub.stamp}/ is not what was built. "
                     f"only in the bucket: {sorted(map(str, got - want))[:5]} | "
                     f"only on disk: {sorted(map(str, want - got))[:5]}")
            print(f"    fetched {len(got)} {label} object(s), set-equal to what was built")

        run(Step(
            "redaction patterns over the FETCHED bytes",
            [str(VENV_ORACLE), "platform/build/gate_payload.py",
             "--payload", str(served_data), "--also-scan", str(served_spa)],
            note="the bytes in the bucket differ from the bytes that were gated.",
        ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stamp", default=None, help="release stamp; default now, UTC")
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--dry-run", action="store_true",
                        help="run every gate and the build, make no AWS call")
    parser.add_argument("--confirm", action="store_true",
                        help="required to upload; without it this is a dry run")
    parser.add_argument("--bucket", default=None, help="override the site bucket from stack outputs")
    parser.add_argument("--distribution", default=None, help="override the distribution id")
    args = parser.parse_args(argv)

    if args.dry_run and args.confirm:
        fail("--dry-run and --confirm contradict each other")
    upload_wanted = bool(args.confirm)

    require_files(required_gates())
    pub = Publish(stamp=args.stamp or utc_stamp(), payload=args.payload.expanduser())
    print(f"GRX Live publish — stamp {pub.stamp}")
    print(f"  payload  {pub.payload}")
    print(f"  upload   {'YES' if upload_wanted else 'no (dry run)'}")

    gate_sources(pub)
    build_payload(pub)
    gate_payload(pub)

    if not upload_wanted:
        print("\nGATES PASSED — nothing uploaded (--confirm not given).")
        print(f"  release would be v/{pub.stamp}/ with the root index.html flipped to it")
    else:
        bucket = args.bucket
        distribution = args.distribution
        if not (bucket and distribution):
            outputs = stack_outputs()
            bucket = bucket or outputs.get("PayloadBucket")
            distribution = distribution or outputs.get("DistributionId")
        if not (bucket and distribution):
            fail(f"stack {STACK_NAME} has no PayloadBucket/DistributionId output; is it deployed?")
        upload(pub, bucket, distribution)
        verify_served(pub, bucket)
        print("\nPUBLISHED")
        print(f"  release  v/{pub.stamp}/")
        print(f"  pointer  s3://{bucket}/index.html and /current.json")

    # vite emptied `dist/`, taking the payload symlink a local preview depends on, with it.
    link = DIST / "data"
    if not link.exists():
        link.symlink_to(pub.payload)
        print(f"\nre-linked {link} -> {pub.payload} for csp_preview.py")
    print("NOTE: site/dist now holds a STAMPED build; `npm run build` in site/ restores the "
          "relative-base one used for local preview.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
