#!/usr/bin/env python3
"""The gate that stops the site from stating a claim its artifacts do not support.

WHY A SEMANTIC GATE, SEPARATELY FROM THE REDACTION GATE
-------------------------------------------------------
`gate_payload.py` asks "do these bytes leak an identifier". This asks a different question: "is every
claim these bytes let the UI render backed by something on disk". The two failures are unrelated. A
perfectly redacted payload can still say a case was replicated when it was measured once, and that is
the exact defect this project incurred on 2026-08-19 — a *process* claim ("a replication happened")
that no *artifact* supported.

The strategy is to make the claim and its evidence be checked by the same build that emits them, so a
false claim fails the PUBLISH rather than being corrected in a later erratum.

THE ARMS, and what each one would have caught
---------------------------------------------
1.  `manifest_liveness` — every output the manifest names exists, hashes to what it says, and the set
    of files on disk equals the set the manifest lists, both directions. A stale manifest beside fresh
    files is a provenance stamp with two readings (`feedback_provenance_stamp_liveness`).
2.  `replication_needs_two_days` — a case may only be presentable as replicated if its archive spans
    two distinct UTC calendar days AND a `day1_*` archive exists AND every archive file it names is on
    disk with the recorded sha256. Plus the count in `method.json` is re-derived here from
    `archive.json` rather than trusted: two numbers produced by two paths must be derived twice
    (`feedback_two_numbers_two_claims`). `archive.json` is keyed by ARTIFACT, not only by case — two
    keys (`F3-10_log_surface_join`, `F5-4a_logonly_read`) are sub-artifact snapshots with no census row
    and no verdict — so the derivation is restricted to keys the census knows, and a separate check
    requires every non-case key to carry no verdict. An archived verdict for something the census does
    not count would be a verdict outside every denominator.
3.  `no_replication_claim_authored_by_the_build` — a forward guard, in two halves. Outside `record`
    (the derived layer, which the build writes) no key matching /replicat/ may be truthy for a case
    that is not in the two-day set. Inside `record` (a verbatim copy of the producer's evidence file,
    minus the heavy series arrays) such keys DO legitimately exist — F10-2's billing-scaling cells
    each carry `replicates_agree`, which is about repeated cells inside one run — so instead of
    excusing that subtree, every replication-named value in it is compared against the same path in
    the on-disk evidence file. Excusing a subtree is where the next instance hides
    (`feedback_guard_scope_is_a_claim`); proving the build authored nothing there costs one file read.
4.  `no_hardcoded_totals` — the seven load-bearing counts (93, 92, 91, 90, 46, 23, 20) may not appear
    in the built bundle as string literals. A typed total is a second source of truth that survives
    the next re-derivation and silently disagrees with it. STRING literals only: minified JS is full
    of bare `20`s and `23`s as offsets and lengths, so a bare-number rule would be unenforceable and
    would end up disabled.
5.  `no_pass_rate` — every occurrence of "pass rate" in the bundle must be preceded by "there is no",
    and at least one must exist. Not "must equal one exact sentence": the overview and the method page
    each deny it in their own words, and a rule that admitted only one wording would have to be
    widened every time the copy is edited, which is how a guard gets deleted. 46 TRUE over 91
    published is not 50.5% of anything — the denominators differ by definition and INCONCLUSIVE is a
    result, not a missing one.
6.  `denominators_carry_definitions` — each of the four has prose long enough to be a definition, an
    integer `n`, and a named derivation source. A number whose definition is missing is the one a
    reader will divide by.
7.  `verdict_mix_sums_to_published` — the four verdict buckets must sum to the published denominator,
    with INCONCLUSIVE its own bucket.
8.  `citation_policy_is_wired_both_ways` — every restriction names a case in the census, and that
    case's row carries the restriction. A policy the case pages cannot see is decoration.
9.  `figures_are_real_pngs` — each present figure exists, matches its recorded sha256 and byte count,
    and starts with the PNG signature. A figure isn't verified until something looks at the bytes
    (`feedback_chart_encoding_defects`); a JSON error page saved as `.png` renders as a broken image
    and no JSON assertion sees it. A non-zero `numeric_check` does not fail the publish — shipping a
    known drift honestly is allowed — but the bundle must then contain the wording that renders it, so
    a payload cannot know it drifted while the page stays silent.
10. `oracles_are_sealed` — every case carries a non-empty `oracle_text` marked sealed, and the
    registry hash the census reports recomputed equals the declared one.

Exit 0 = all arms pass. 1 = a violation. 2 = the gate could not run (missing payload, unreadable
JSON): a gate that cannot run must not report clean (`feedback_guard_tool_exit_codes`).

MUTATION-CHECKED, 2026-08-20 — 19/19, each mutant killed by the arm that watches the property it
broke, run against COPIES of the payload and `dist`
--------------------------------------------------------------------------------------------------
A no-mutant control ran first and exited 0, so a red run is attributable to the assertions rather than
to a copy the gate could not read at all. Two findings from that exercise are worth stating, because
both made the first version of this test worthless while it looked thorough:

* **`manifest_liveness` masked every other arm.** Any edit to a payload file changes its sha256, so
  the manifest arm fired first on all fourteen semantic mutants and the arms under test were never
  shown to fire at all — a red result for the wrong reason (`feedback_identical_output_wrong_assertion`
  in the opposite direction). Fixed by having the harness recompute the manifest after each mutation,
  which is also the realistic case: a defect that reaches publish arrives WITH a consistent manifest,
  because `build_site_data.py` hashes whatever it emitted, defect included.
* **One mutant never landed.** The typed-total mutant inserted itself after `const `, a string esbuild's
  minified output does not contain (it emits `var`/`let`), so the file was unchanged and the gate's
  clean exit proved nothing (`feedback_probe_must_reach_the_code`). The harness then asserted that
  every mutant changed at least one byte before running the gate.

The nineteen: no-mutant control; manifest sha256 flipped; unlisted file added; F6-5's two archives
re-dated to one day; a non-case archive key given a verdict; an archive's recorded sha256 corrupted; a
day-2 archive dropped from the payload with `method.json`'s counts made consistent with the omission;
an archive label re-dated away from the file it names; a one-day case flagged replicated in the derived
layer; a `record` value the producer never wrote; a typed `"46"`; a pass rate asserted; the drift
wording removed while `numeric_check` is non-zero; a definition cut to a stub; the verdict mix made not
to sum; a restricted case's page stripped of its badge; one PNG byte flipped; an "Access Denied" JSON
body saved as a `.png` with its recorded bytes and sha256 updated to match; one `oracle_text` blanked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = REPO / "results" / "phase1" / "archive"
DEFAULT_PAYLOAD = REPO.parent / "grx-site-payload"
DEFAULT_DIST = REPO / "site" / "dist"

# The counts the platform must always derive. Kept as strings because that is the form the check
# looks for, and listed here rather than computed so that the list itself is reviewable.
FORBIDDEN_LITERALS = ("93", "92", "91", "90", "46", "23", "20")

# The one sentence allowed to contain the phrase.
PASS_RATE_DISCLAIMER = "There is no pass rate on this platform."

MIN_DEFINITION_CHARS = 40


class Gate:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def fail(self, arm: str, msg: str) -> None:
        self.failures.append(f"[{arm}] {msg}")

    def note(self, arm: str, msg: str) -> None:
        self.notes.append(f"[{arm}] {msg}")

    def check(self, arm: str, ok: bool, msg: str, passed: str = "") -> bool:
        if ok:
            if passed:
                self.note(arm, passed)
            return True
        self.fail(arm, msg)
        return False


def cannot_run(msg: str) -> None:
    print(f"[gate cannot run] {msg}", file=sys.stderr)
    raise SystemExit(2)


def load(payload: Path, name: str) -> dict:
    path = payload / name
    if not path.is_file():
        cannot_run(f"{path} is missing; the payload is incomplete")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        cannot_run(f"{path} is not readable JSON: {exc}")
    return {}  # unreachable; keeps the type checker and `noImplicitReturns` habits honest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def days_from_labels(labels: list[str]) -> set[str]:
    """`day1_2026-08-10` / `day2_indecisive_2026-08-19` -> {'2026-08-10', '2026-08-19'}."""
    return {m.group(0) for label in labels if (m := re.search(r"\d{4}-\d{2}-\d{2}", label))}


# ---------------------------------------------------------------------------- arms

def arm_manifest_liveness(g: Gate, payload: Path) -> None:
    arm = "manifest_liveness"
    manifest = load(payload, "MANIFEST.json")
    outputs = manifest.get("outputs_sha256")
    if not isinstance(outputs, dict) or not outputs:
        g.fail(arm, "MANIFEST.json has no non-empty outputs_sha256")
        return
    on_disk = {
        p.relative_to(payload).as_posix()
        for p in payload.rglob("*")
        if p.is_file() and p.name != "MANIFEST.json"
    }
    listed = set(outputs)
    missing = sorted(listed - on_disk)
    extra = sorted(on_disk - listed)
    g.check(arm, not missing, f"the manifest names {len(missing)} file(s) that do not exist: "
                              f"{missing[:5]}")
    g.check(arm, not extra, f"{len(extra)} file(s) are in the payload but not in the manifest: "
                            f"{extra[:5]}. An unlisted file is one nothing verified.")
    drifted = [rel for rel, want in outputs.items()
               if rel in on_disk and sha256_file(payload / rel) != want]
    g.check(arm, not drifted,
            f"{len(drifted)} file(s) do not hash to the manifest's value: {drifted[:5]}. The stamp "
            "would then have two readings — the files, and the record of the files.",
            passed=f"{len(outputs)} outputs match their recorded sha256, set equality both ways")
    n_outputs = manifest.get("n_outputs")
    g.check(arm, isinstance(n_outputs, int) and n_outputs == len(outputs) + 1,
            f"n_outputs={n_outputs} but outputs_sha256 holds {len(outputs)} entries (+1 for "
            "MANIFEST.json itself)")


def arm_replication(g: Gate, payload: Path, census_cases: set[str]) -> set[str]:
    arm = "replication_needs_two_days"
    archive = load(payload, "archive.json").get("by_case", {})
    method = load(payload, "method.json")
    if not archive:
        g.fail(arm, "archive.json has no by_case block; the replication panel would have no source")
        return set()

    two_day: set[str] = set()
    for key, entries in archive.items():
        labels = [e.get("label", "") for e in entries]
        days = days_from_labels(labels)
        if len(days) >= 2 and key in census_cases:
            two_day.add(key)
            g.check(arm, any(lbl.startswith("day1_") for lbl in labels),
                    f"{key} spans {sorted(days)} but has no day1_* archive, so there is no "
                    "first-day file for a second day to be compared against")
        if key not in census_cases:
            # A sub-artifact snapshot. It may be archived, but it may not carry an adjudication: a
            # verdict for something with no census row is a verdict outside every denominator.
            verdicts = [e.get("verdict") for e in entries if e.get("verdict")]
            g.check(arm, not verdicts,
                    f"{key} is not a case in the census yet its archive records verdict(s) "
                    f"{verdicts}. Either the census is missing a row or an archive is asserting an "
                    "adjudication nothing counts.")
        for entry in entries:
            name = entry.get("file", "")
            path = ARCHIVE_DIR / name
            if not path.is_file():
                g.fail(arm, f"{key}: archive {name} is referenced but absent from {ARCHIVE_DIR}")
                continue
            digest = sha256_file(path)
            if digest != entry.get("sha256"):
                g.fail(arm, f"{key}: archive {name} hashes {digest[:12]}… but the payload records "
                            f"{str(entry.get('sha256'))[:12]}…")
            # The label is what the day count is derived from, so it may not be free text: it must be
            # the artifact's own name. Otherwise a payload could be internally consistent and still
            # wrong — every count in it derived from a label nothing on disk supports.
            g.check(arm, name == f"{key}__{entry.get('label')}.json",
                    f"{key}: label {entry.get('label')!r} does not name the file {name!r} it came "
                    "from, so the dates the replication panel counts are free text")

        # Set equality against the filesystem, not just existence. An archive file on disk that the
        # payload omits is a day the site cannot see — which is how an under-claimed replication and an
        # over-claimed one look identical from inside the payload.
        on_disk = {p.name for p in ARCHIVE_DIR.glob(f"{key}__*.json")}
        referenced = {e.get("file") for e in entries}
        g.check(arm, on_disk == referenced,
                f"{key}: {sorted(on_disk ^ referenced)} is in {ARCHIVE_DIR.name}/ or in the payload "
                "but not both")

    # Re-derived here rather than read: `method.json`'s count and `archive.json`'s labels are produced
    # by different code paths over the same evidence, so they must be derived twice and compared.
    declared = method.get("n_cases_with_two_distinct_archive_days")
    g.check(arm, declared == len(two_day),
            f"method.json says {declared} case(s) have two distinct archive days; re-deriving from "
            f"archive.json over census cases gives {len(two_day)} ({sorted(two_day)})",
            passed=f"{len(two_day)} case(s) span two distinct UTC days: {sorted(two_day)}")

    # Both directions over the KEY SET too, so a case dropped from the builder's map cannot agree with
    # it by being absent from both sides of a per-key comparison.
    declared_days = method.get("archive_days_by_case", {})
    with_days = {k for k, v in archive.items()
                 if k in census_cases and days_from_labels([e.get("label", "") for e in v])}
    g.check(arm, set(declared_days) == with_days,
            f"archive_days_by_case covers {sorted(set(declared_days) ^ with_days)[:5]} differently "
            "from the archive itself")
    mismatched = [
        key for key, entries in archive.items() if key in census_cases
        and set(declared_days.get(key, [])) != days_from_labels([e.get("label", "") for e in entries])
    ]
    g.check(arm, not mismatched,
            f"archive_days_by_case disagrees with the archive labels for {mismatched[:5]}")
    return two_day


def arm_no_authored_replication_claim(g: Gate, payload: Path, two_day: set[str]) -> None:
    arm = "no_replication_claim_authored_by_the_build"
    derived_offenders: list[str] = []
    authored_in_record: list[str] = []
    n_derived = n_verbatim = 0

    def replicat_paths(node: object, where: str, out: dict[str, object]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if re.search(r"replicat", str(key), re.IGNORECASE):
                    out[f"{where}/{key}"] = value
                replicat_paths(value, f"{where}/{key}", out)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                replicat_paths(value, f"{where}/{i}", out)

    def at(node: object, parts: list[str]) -> object:
        for part in parts:
            if isinstance(node, list):
                if not part.isdigit() or int(part) >= len(node):
                    return KeyError
                node = node[int(part)]
            elif isinstance(node, dict):
                if part not in node:
                    return KeyError
                node = node[part]
            else:
                return KeyError
        return node

    for path in sorted(payload.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        rel = path.relative_to(payload).as_posix()
        case_hint = path.stem  # cases/F6-5.json -> F6-5
        found: dict[str, object] = {}
        replicat_paths(data, "", found)
        if not found:
            continue

        # The verbatim half: `cases/<id>.json`'s `record` is the producer's evidence file with the
        # heavy series arrays split out. Anything replication-named in there must still be the
        # producer's value, byte for byte, at the same path.
        evidence: object = None
        if rel.startswith("cases/") and isinstance(data, dict) and data.get("verdict_file"):
            source = REPO / "results" / "phase1" / str(data["verdict_file"])
            if not source.is_file():
                g.fail(arm, f"{rel} names verdict_file {data['verdict_file']}, which is not on disk, "
                            "so its record cannot be checked against the producer's own bytes")
            else:
                evidence = json.loads(source.read_text(encoding="utf-8"))

        for where, value in found.items():
            parts = [p for p in where.split("/") if p]
            if parts and parts[0] == "record":
                n_verbatim += 1
                if evidence is None:
                    authored_in_record.append(f"{rel}:{where} (no evidence file to compare against)")
                elif at(evidence, parts[1:]) != value:
                    authored_in_record.append(
                        f"{rel}:{where} is {value!r} but the producer's file has "
                        f"{at(evidence, parts[1:])!r}"
                    )
                continue
            n_derived += 1
            if value is True and case_hint not in two_day:
                derived_offenders.append(f"{rel}:{where} is true for {case_hint}")

    g.check(arm, not derived_offenders,
            f"the derived layer sets a replication flag for a case outside the two-day set: "
            f"{derived_offenders[:5]}",
            passed=f"{n_derived} replication-named field(s) in the derived layer, none asserting a "
                   "single-day case is replicated")
    g.check(arm, not authored_in_record,
            f"a replication-named value under `record` differs from the producer's evidence file, so "
            f"the build authored it: {authored_in_record[:5]}",
            passed=f"{n_verbatim} replication-named field(s) under `record` are the producer's own "
                   "values at the same paths")


def arm_bundle_text(g: Gate, dist: Path) -> str:
    bundles = sorted(p for p in (dist / "assets").glob("*.js")) if dist.is_dir() else []
    if not bundles:
        cannot_run(f"no built bundle under {dist}/assets — nothing to check, which must not pass")
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in bundles)
    g.note("bundle", f"{len(bundles)} bundle(s), {len(text)} chars")

    arm = "no_hardcoded_totals"
    clean = True
    for literal in FORBIDDEN_LITERALS:
        # Quoted, and the whole literal: `"93"` but not `"2026-08-20"` and not a bare `93` offset.
        hits = re.findall(rf"""(["'`]){literal}\1""", text)
        clean &= g.check(arm, not hits,
                         f'the bundle contains the string literal "{literal}" {len(hits)} time(s). '
                         "Every total on this platform is derived from denominators.json at runtime; "
                         "a typed one survives the next re-derivation and disagrees with it silently.")
    if clean:
        g.note(arm, f"none of {FORBIDDEN_LITERALS} appears as a string literal")

    arm = "no_pass_rate"
    occurrences = list(re.finditer(r"pass[\s-]?rate", text, re.IGNORECASE))
    asserted = [m for m in occurrences
                if not re.search(r"there\s+is\s+no\s+$", text[max(0, m.start() - 24):m.start()],
                                 re.IGNORECASE)]
    g.check(arm, not asserted,
            f'{len(asserted)} of {len(occurrences)} "pass rate" occurrence(s) are not preceded by '
            f'"there is no": {[text[max(0, m.start() - 60):m.end() + 40] for m in asserted[:2]]}. '
            "There is no denominator on this platform that a verdict count may be divided by.")
    g.check(arm, bool(occurrences),
            "the phrase does not appear at all, so this arm proved nothing: the UI must actively "
            f"deny a pass rate, and {PASS_RATE_DISCLAIMER!r} is the wording the overview uses",
            passed=f"all {len(occurrences)} occurrence(s) of the phrase are denials")
    return text


def arm_denominators(g: Gate, payload: Path) -> dict:
    arm = "denominators_carry_definitions"
    denominators = load(payload, "denominators.json")
    g.check(arm, len(denominators) >= 4, f"only {len(denominators)} denominator(s) in the payload")
    for name, block in denominators.items():
        definition = str(block.get("definition", ""))
        g.check(arm, len(definition) >= MIN_DEFINITION_CHARS,
                f"{name}'s definition is {len(definition)} chars; these four numbers differ for "
                "stated reasons and the statement is the point")
        g.check(arm, isinstance(block.get("n"), int), f"{name}.n is not an integer")
        g.check(arm, bool(block.get("derived_from")), f"{name} does not name what it was derived from")
    g.note(arm, ", ".join(f"{k}={v.get('n')}" for k, v in sorted(denominators.items())))
    return denominators


def arm_verdict_mix(g: Gate, payload: Path, denominators: dict) -> None:
    arm = "verdict_mix_sums_to_published"
    census = load(payload, "census.json")
    mix = census.get("verdict_mix", {})
    g.check(arm, "INCONCLUSIVE" in mix,
            "INCONCLUSIVE is not a bucket of its own in verdict_mix; it must never be folded into "
            "either decisive column")
    published = (denominators.get("published") or {}).get("n")
    total = sum(v for v in mix.values() if isinstance(v, int))
    g.check(arm, total == published,
            f"the verdict buckets sum to {total} but the published denominator is {published}. Two "
            "counts derived from the same files must agree, or one of them is describing a "
            "different set than its label says.",
            passed=f"{mix} sums to the published denominator {published}")


def arm_citation_policy(g: Gate, payload: Path, census_cases: set[str]) -> None:
    arm = "citation_policy_is_wired_both_ways"
    policy = load(payload, "citation_policy.json")
    restrictions = policy.get("restrictions", [])
    g.check(arm, bool(restrictions), "citation_policy.json has no restrictions; the badges the case "
                                     "pages render would come from copy instead of data")
    n_wired = 0
    for entry in restrictions:
        named = entry.get("cases")
        if not isinstance(named, list) or not named:
            g.fail(arm, f"a restriction names no cases: {json.dumps(entry)[:140]}")
            continue
        g.check(arm, bool(str(entry.get("reason", "")).strip()),
                f"the restriction on {named} states no reason, so the badge would assert a rule with "
                "no ground")
        for case in named:
            if case not in census_cases:
                g.fail(arm, f"the policy restricts {case}, which is not in the census")
                continue
            # The case PAGE is what a reader sees, and it renders only what its own file carries.
            page = payload / "cases" / f"{case}.json"
            if not page.is_file():
                g.fail(arm, f"{case} is restricted but has no case page in the payload")
                continue
            carried = json.loads(page.read_text(encoding="utf-8")).get("citation_restrictions") or []
            if not any(r.get("reason") == entry.get("reason") for r in carried):
                g.fail(arm, f"{case}'s page does not carry the restriction whose reason begins "
                            f"{str(entry.get('reason'))[:60]!r}, so the badge cannot render")
            else:
                n_wired += 1
    g.note(arm, f"{len(restrictions)} restriction(s) covering {n_wired} case page(s), each wired both "
                "ways between the policy and the page that renders it")


def arm_figures(g: Gate, payload: Path, bundle_text: str) -> None:
    arm = "figures_are_real_pngs"
    figures = load(payload, "figures.json")
    present = figures.get("present", [])
    g.check(arm, bool(present), "no figures in the payload")
    for entry in present:
        path = payload / "figures" / entry["file"]
        if not path.is_file():
            g.fail(arm, f"{entry['file']} is listed present but absent from the payload")
            continue
        data = path.read_bytes()
        g.check(arm, data[:8] == b"\x89PNG\r\n\x1a\n",
                f"{entry['file']} does not start with the PNG signature; an error page saved under a "
                ".png name renders as a broken image and no JSON assertion notices")
        g.check(arm, len(data) == entry.get("bytes"),
                f"{entry['file']} is {len(data)} B, recorded as {entry.get('bytes')} B")
        g.check(arm, hashlib.sha256(data).hexdigest() == entry.get("sha256"),
                f"{entry['file']} does not match its recorded sha256")
    rc = figures.get("numeric_check")
    g.check(arm, isinstance(rc, int),
            "figures.json carries no integer numeric_check, so the freshness badge would be derived "
            "from nothing. It must be the rc of whitepaper_figures.py --check, passed in.")
    if isinstance(rc, int) and rc != 0:
        # Shipping a known drift is allowed; shipping it silently is not.
        g.check(arm, "drifted (rc " in bundle_text,
                f"numeric_check is {rc} — the figures' numbers no longer match the values recorded "
                "when they were drawn — but the bundle contains no wording that renders a drift, so "
                "the page would show stale charts as if they were current")
    for missing in figures.get("missing", []):
        g.check(arm, bool(str(missing).strip()), "a missing figure is listed with an empty name")
    g.note(arm, f"{len(present)} PNG(s) verified byte for byte, numeric_check rc={rc}, "
                f"missing={figures.get('missing')}")


def arm_oracles(g: Gate, payload: Path) -> None:
    arm = "oracles_are_sealed"
    census = load(payload, "census.json")
    seal = census.get("seal", {})
    g.check(arm, seal.get("registry_sha256_declared") == seal.get("registry_sha256_recomputed"),
            "the oracle registry's declared hash differs from the recomputed one: an oracle changed "
            "after its measurement ran",
            passed=f"registry seal live over {seal.get('n_cases_declared')} declared oracles")
    cases = sorted((payload / "cases").glob("*.json"))
    g.check(arm, len(cases) >= 90, f"only {len(cases)} case file(s) in the payload")
    for path in cases:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not str(data.get("oracle_text", "")).strip():
            g.fail(arm, f"{path.name} has an empty oracle_text; the case page would show a verdict "
                        "with no falsifying condition beside it")
        if data.get("oracle_is_sealed") is not True:
            g.fail(arm, f"{path.name} does not mark its oracle sealed")
    g.note(arm, f"{len(cases)} case files carry a sealed, non-empty oracle")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    payload = args.payload.expanduser()
    if not payload.is_dir():
        cannot_run(f"{payload} is not a directory")

    g = Gate()
    census = load(payload, "census.json")
    census_cases = {r["case"] for r in census.get("rows", []) if isinstance(r, dict) and "case" in r}
    if len(census_cases) < 90:
        cannot_run(f"census.json lists {len(census_cases)} case(s); every arm below is scoped to that "
                   "set and would be near-vacuous")

    arm_manifest_liveness(g, payload)
    two_day = arm_replication(g, payload, census_cases)
    arm_no_authored_replication_claim(g, payload, two_day)
    bundle = arm_bundle_text(g, args.dist.expanduser())
    denominators = arm_denominators(g, payload)
    arm_verdict_mix(g, payload, denominators)
    arm_citation_policy(g, payload, census_cases)
    arm_figures(g, payload, bundle)
    arm_oracles(g, payload)

    if args.verbose or g.failures:
        for note in g.notes:
            print(f"  {note}")
    if g.failures:
        print(f"\nFAILED — {len(g.failures)} site invariant violation(s)", file=sys.stderr)
        for item in g.failures:
            print(f"  * {item}", file=sys.stderr)
        return 1
    print(f"PASSED — {len(g.notes)} site invariants hold over {payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
