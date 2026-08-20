#!/usr/bin/env python3
"""Redaction gate for the site payload, at the place the payload lands.

Why a second gate exists at all
-------------------------------
`check_redaction.py` scans the repository. The payload is not in the repository — deliberately, see
`build_site_data.py`'s docstring — so nothing in the repo gate reads the bytes CloudFront serves.
This is the gate for those bytes. It **imports** `PATTERNS`, `allowed()` and `scan_forms()` from
`check_redaction` and never re-derives them: two redaction gates with two copies of one pattern set
is the failure this project already had on 2026-08-19, where a masker and a gate that were supposed
to be independent turned out to share an assumption and therefore to be one layer. Sharing the
*implementation* while differing in *scope* is the opposite arrangement, and it is the safe one.

What it does that the repo gate cannot
--------------------------------------
1. **It reads every file, whatever the extension.** It scans everything under the payload root and
   skips only what it names, so a new artefact type (a Vite bundle, a source map, a font, a PNG) is
   covered the day it appears rather than the day someone remembers to add an extension. A file that
   will not decode as UTF-8 is scanned as latin-1 rather than skipped: an ASCII identifier embedded
   in a PNG text chunk or a compiled bundle is still an identifier, and "binary" is not a reason not
   to look.

   This is no longer a *difference* from the repo gate, and the way it stopped being one is worth
   recording. Until 2026-08-20 this paragraph read "the repo gate selects by `SCAN_EXT`, nine
   extensions, and `.log` is not among them — a live, open gap recorded as register item 35". Writing
   that sentence down as a scope claim is what got it measured: the allowlist was skipping **87 files
   / 701,558 bytes** of the repository, including all 56 `.jsonl` corpora and 22 `.log` files under
   `session-logs/`, and 7 unwaived identifiers were sitting in two of them. `check_redaction.py` then
   adopted this module's predicate wholesale, so the two gates now share the *inclusion rule* as well
   as `PATTERNS`, `allowed()` and `scan_forms()`, and differ only in *scope* — which is the
   arrangement the paragraph above argues for. `lib/tests/test_redaction_scan_predicate.py` holds the
   arms on the repo side (`feedback_guard_scope_is_a_claim`: the docstring excusing where a guard
   need not look is where the next instance hides).
2. **It inherits reviewed exceptions instead of granting new ones.** A payload file may legitimately
   contain a value that the ALLOW table excuses under a *source* path. Measured 2026-08-19 over the
   104-file payload: 2,410 pattern hits, of which 2,406 are excused by path-independent rules (an ARN
   whose account field is already `<account>`, a wildcard, an AWS-managed policy) and exactly **4**
   need a path-scoped excuse — `results/phase1/F5-7b.json`'s VPC CIDR, reaching `cases/F5-7b.json`
   and `findings.json`. Those 4 are excused by asking `allowed()` about the SOURCE the payload file
   derives from, read out of `MANIFEST.json`'s `provenance` map. Nothing here can waive anything on
   its own: if no source excuses a hit, it is a finding.
3. **It proves it gated the bytes that will be uploaded.** Set equality, both directions, between the
   files on disk, the manifest's `outputs_sha256`, and (when given) the upload list — plus a
   re-hash of every file against the manifest. A gate that scanned a payload and an uploader that
   uploaded a different one would otherwise both report success.

What it deliberately does NOT add
---------------------------------
A pattern for the bare runner-bucket name. `runner/iam_policy.py` builds it as
`grx-` + `runtime-code` + `-<account>-<region>`, and the plan for this gate called for a dedicated
pattern because an `s3://`-shaped pattern cannot see a bare name. Measured instead of assumed: the
character before the twelve digits there is a hyphen, which is a non-word character, so
`aws-account-id` already fires on it. A second pattern for a case the first one covers is a second
thing to keep true. `platform/build/tests/test_gate_payload.py` asserts the coverage instead, so a
future narrowing of the account pattern reds the suite rather than silently opening the hole this
paragraph says is closed.

Exit codes
----------
0 clean, 1 findings or a structural failure. rc must be read from the process, never through a pipe.

Usage
-----
    .venv-oracle/bin/python platform/build/gate_payload.py
    .venv-oracle/bin/python platform/build/gate_payload.py --payload ~/grx-site-payload --verbose
    .venv-oracle/bin/python platform/build/gate_payload.py --upload-list /path/to/list.txt
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PAYLOAD = ROOT.parent / "grx-site-payload"

# A payload with fewer files than this was not built. 104 today; the floor only has to be far enough
# below that never to false-alarm and far enough above zero to catch a walk that read the wrong
# directory. `feedback_zero_file_scan_is_error`: an empty scan must fail, not pass quietly.
MIN_FILES = 40

# Skipped by NAME, and the list is deliberately tiny. Everything not named here is read.
SKIP_NAMES = {".DS_Store"}
SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules"}

# The `sys.modules` name `load_subject()` registers `check_redaction.py` under. MODULE-LEVEL on
# purpose: `lib/tests/test_module_name_collisions.py` reads every by-path loader's name from the AST
# and demands a literal or a module-level string constant, so that no two loaders can quietly claim
# the same name. A function-local `name = "…"` is invisible to it, and this file was the tenth entry
# in the "cannot be read statically" set until the constant was hoisted — a file in that set is a
# file whose registered name nothing checks for collisions.
SUBJECT_MODULE_NAME = "_payload_check_redaction"


def load_subject():
    """`check_redaction` by path, under a name that is not its importable stem.

    `lib/tests/test_module_name_collisions.py` is the gate that says a by-path loader must not squat
    an importable top-level name, so the module is registered as `_payload_check_redaction`.
    """
    if SUBJECT_MODULE_NAME in sys.modules:
        return sys.modules[SUBJECT_MODULE_NAME]
    # The constant is passed DIRECTLY, not via a local alias: the gate reads the call site's first
    # argument, so `name = SUBJECT_MODULE_NAME; spec_from_file_location(name, …)` is still opaque
    # to it. The alias is what left this file unresolvable on the first attempt at this fix.
    spec = importlib.util.spec_from_file_location(SUBJECT_MODULE_NAME, ROOT / "check_redaction.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[SUBJECT_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


class GateError(RuntimeError):
    """A structural failure: the gate could not establish what it was asked to establish."""


def walk(payload: Path) -> list[Path]:
    out = []
    for p in sorted(payload.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(payload).parts
        if p.name in SKIP_NAMES or any(d in SKIP_DIR_NAMES for d in rel_parts[:-1]):
            continue
        out.append(p)
    return out


def text_of(p: Path) -> tuple[str, bool]:
    """The file's text and whether a lossy decode was needed.

    latin-1 never fails and maps every byte to a character, so a pattern written for ASCII still
    matches inside a compiled bundle or a PNG text chunk. The alternative — skipping what does not
    decode — is how a scan reports clean on files it did not read.
    """
    b = p.read_bytes()
    try:
        return b.decode("utf-8"), False
    except UnicodeDecodeError:
        return b.decode("latin-1"), True


# A path inside ROOT that no ALLOW suffix can match, used to ask "would this hit be excused with no
# reviewed exception available at all?" — which is how a shape-based excuse is told apart from an
# inherited one. It is never opened.
NO_ALLOW_PATH = ROOT / "__no_reviewed_exception_matches_this_path__"


def _ask(gate, path: Path, name: str, form: str, raw: str) -> str | None:
    """Both the matched form and the raw line, in `check_redaction.main()`'s order.

    An ALLOW needle is authored against the bytes a file contains, while the ARN excuse has to
    decompose the identifier and can only do that once the line is decoded.
    """
    why = gate.allowed(path, name, form)
    if not why and form != raw:
        why = gate.allowed(path, name, raw)
    return why


def excuse(gate, sources: list[str], name: str, form: str,
           raw: str) -> tuple[str | None, str] | None:
    """`(source, why)`, where `source` is None if no reviewed exception was needed.

    Two kinds of excuse reach this gate and conflating them is what makes a gate's output unreadable:

    * **shape-based** — an ARN whose account field is already `<account>`, an exact `*` wildcard, an
      AWS-managed policy. These hold for any file anywhere, and there are thousands of them (2,406 of
      2,410 in the 2026-08-19 payload). Nobody reviewed them individually and nobody should.
    * **inherited** — a path-scoped ALLOW entry a human wrote against a named source file. There were
      **4**. These are the ones worth a reader's attention, so they are printed unconditionally and
      counted separately.
    """
    generic = _ask(gate, NO_ALLOW_PATH, name, form, raw)
    if generic:
        return None, generic
    for src in sources:
        why = _ask(gate, ROOT / src, name, form, raw)
        if why:
            return src, why
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    ap.add_argument("--upload-list", help="file of payload-relative paths about to be uploaded; "
                                          "set equality with what was scanned is asserted")
    ap.add_argument("--verbose", action="store_true", help="print every inherited excuse")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    payload = Path(args.payload).resolve()
    if not payload.is_dir():
        raise GateError(f"payload root is not a directory: {payload}")
    if payload == ROOT or ROOT in payload.parents:
        raise GateError(
            f"{payload} is inside the repository. The payload is built outside it on purpose "
            f"(build_site_data.py refuses otherwise); gating a copy in the wrong place would pass "
            f"while the served bytes went unread.")

    gate = load_subject()

    manifest_path = payload / "MANIFEST.json"
    if not manifest_path.is_file():
        raise GateError(f"no MANIFEST.json under {payload}; provenance is what a reviewed exception "
                        f"is inherited from, and without it every hit fails closed anyway")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    provenance = manifest.get("provenance") or {}
    declared = dict(manifest.get("outputs_sha256") or {})
    if not provenance or not declared:
        raise GateError("MANIFEST.json carries no provenance or no output hashes")

    found = walk(payload)
    if len(found) < MIN_FILES:
        raise GateError(f"scanned {len(found)} file(s), below the floor of {MIN_FILES}: a payload "
                        f"this small was not built")

    rels = {str(p.relative_to(payload)) for p in found}

    # Set equality, both directions. `declared` excludes MANIFEST.json by construction, so it is
    # added rather than the comparison being loosened — a subset check here would pass a payload
    # carrying an extra file nobody derived.
    expected = set(declared) | {"MANIFEST.json"}
    extra, absent = sorted(rels - expected), sorted(expected - rels)
    if extra or absent:
        raise GateError(f"payload does not match its manifest: on disk but not declared={extra[:5]} "
                        f"declared but not on disk={absent[:5]}")

    no_prov = sorted(rels - set(provenance))
    if no_prov:
        raise GateError(f"no provenance for {no_prov[:5]}; a reviewed exception cannot be inherited "
                        f"for a file whose sources are unknown, so this would fail closed later "
                        f"with a much less useful message")

    # The bytes about to be uploaded must be the bytes the build produced.
    drifted = []
    for p in found:
        rel = str(p.relative_to(payload))
        if rel == "MANIFEST.json":
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() != declared[rel]:
            drifted.append(rel)
    if drifted:
        raise GateError(f"content differs from the manifest for {drifted[:5]}: the payload was "
                        f"modified after it was built, so gating it establishes nothing about what "
                        f"the build derived")

    if args.upload_list:
        listed = {l.strip() for l in Path(args.upload_list).read_text().splitlines() if l.strip()}
        if listed != rels:
            raise GateError(
                f"upload list does not match what was scanned: to upload but not scanned="
                f"{sorted(listed - rels)[:5]} scanned but not uploaded={sorted(rels - listed)[:5]}")

    findings: list[tuple[str, int, str, str]] = []
    inherited: list[tuple[str, int, str, str, str]] = []
    by_shape = 0
    n_bytes = 0
    lossy: list[str] = []
    for p in found:
        rel = str(p.relative_to(payload))
        text, was_lossy = text_of(p)
        n_bytes += len(text)
        if was_lossy:
            lossy.append(rel)
        sources = provenance[rel]
        for lineno, line in enumerate(text.splitlines(), 1):
            forms = gate.scan_forms(line)
            for name, rx, _desc in gate.PATTERNS:
                for form, note in forms:
                    if not rx.search(form):
                        continue
                    got = excuse(gate, sources, name, form, line)
                    if got:
                        src, why = got
                        if src is None:
                            by_shape += 1
                            if args.verbose:
                                print(f"  shape {rel}:{lineno} [{name}] {why[:70]}")
                        else:
                            inherited.append((rel, lineno, name, src, why))
                    else:
                        shown = name if not note else f"{name} ({note})"
                        findings.append((rel, lineno, shown, form.strip()[:120]))
                    break

    print(f"payload gate: {len(found)} file(s) under {payload}")
    print(f"  {n_bytes:,} characters read")
    print(f"  {by_shape} hit(s) excused by SHAPE — the identifier position is already a placeholder, "
          f"a wildcard, or an AWS-owned value; no reviewed exception involved")
    print(f"  {len(lossy)} file(s) needed a lossy decode and were scanned as latin-1"
          + (f": {lossy[:3]}" if lossy else ""))
    # Printed unconditionally. These are the only hits where a human's path-scoped judgment is doing
    # the work, and a reader who cannot see them cannot audit the inheritance.
    print(f"  {len(inherited)} hit(s) INHERITED a reviewed exception from a named source:")
    for rel, lineno, name, src, why in inherited[:20]:
        print(f"     {rel}:{lineno} [{name}] <- {src}: {why[:70]}")
    if len(inherited) > 20:
        print(f"     ... and {len(inherited) - 20} more")
    if findings:
        print(f"\nFAILED — {len(findings)} unredacted identifier(s):")
        for rel, lineno, name, snippet in findings[:40]:
            print(f"  {rel}:{lineno} [{name}] {snippet}")
        if len(findings) > 40:
            print(f"  ... and {len(findings) - 40} more")
        return 1
    print(f"\nPASSED — no unredacted cloud identifiers in {len(found)} payload files.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"GATE-FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
